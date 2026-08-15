"""Poverty snapshots, ranking computation, and allocation certification
(PRD §3.2, §3.3, §2.7)."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_school_allocation,
    build_user_headers,
    certify_snapshot,
    create_snapshot,
    create_snapshot_payload,
    finalize_allocations,
    get_grant,
    lock_rankings,
    open_grant,
    register_school,
    setup_allocated,
    setup_certified_allocation,
    setup_ranking_locked,
    snapshot_entry,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = build_user_headers("director-1", "FederalProgramsDirector")
ANALYST = build_user_headers("analyst-1", "ComplianceAnalyst")


class TestSnapshotCertificationGates:

    def test_lock_rankings_without_snapshot_returns_no_certified(self):
        """PRD §3.3: "It requires the grant to be in `SETUP` (else
        `ERR_GRANT_INVALID_STATE`) and requires at least one snapshot of the
        grant in `CERTIFIED` status — with none, the lock is rejected with
        `ERR_NO_CERTIFIED_SNAPSHOT`."

        Design: Corner/errors/lock_rankings_without_snapshot_returns_no_certified
        """
        grant = open_grant(2065, 5_000_000)
        resp = api_client.lock_rankings(grant["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_NO_CERTIFIED_SNAPSHOT)
        after = validate_success(api_client.get_grant(grant["id"], DIRECTOR))
        assert after["status"] == "SETUP"

    def test_certify_snapshot_twice_returns_not_certifiable(self):
        """PRD §3.2: "A snapshot may be certified only while it is `DRAFT`
        (otherwise `ERR_SNAPSHOT_NOT_CERTIFIABLE`), only while its grant is in
        `SETUP`, `RANKING_LOCKED`, or `ALLOCATED`, and only when the entries
        cover every active school exactly once — a missing or extra active
        school is rejected with `ERR_SNAPSHOT_INCOMPLETE_COVERAGE`."

        Design: Corner/errors/certify_snapshot_twice_returns_not_certifiable
        """
        school = register_school("Cert School", "100604")
        grant = open_grant(2066, 5_000_000)
        snap = create_snapshot(
            grant["id"], [snapshot_entry(school["id"], 50, 100)])
        certify_snapshot(snap["id"], grant["id"])
        # A second certification attempt with a freshly read grant version:
        # the state precondition (DRAFT-only) is the one that fires.
        current = get_grant(grant["id"])
        resp = api_client.certify_snapshot(
            snap["id"], {"expected_grant_version": current["version"]},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_NOT_CERTIFIABLE)

    def test_snapshot_incomplete_coverage_rejected_at_creation(self):
        """PRD §3.2: "Coverage is enforced at creation and again at
        certification: the entries must cover every school with `is_active`
        set exactly once, or the request is rejected with
        `ERR_SNAPSHOT_INCOMPLETE_COVERAGE`."

        Design: Corner/errors/snapshot_incomplete_coverage_rejected
        """
        s1 = register_school("Cov A", "100605", grade_span_high=5)
        register_school("Cov B", "100606", grade_span_low=6,
                        grade_span_high=8)
        grant = open_grant(2067, 5_000_000)
        # Entries cover only one of the two active schools: rejected now.
        resp = api_client.create_snapshot(
            create_snapshot_payload(
                grant["id"], [snapshot_entry(s1["id"], 50, 100)]),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_INCOMPLETE_COVERAGE)
        rows, meta = validate_paginated(
            api_client.list_snapshots(DIRECTOR, params={"grant_id": grant["id"]}))
        assert meta["total_count"] == 0, "no snapshot row may be persisted"

    def test_snapshot_incomplete_coverage_rejected_at_certification(self):
        """PRD §3.2: "Coverage is enforced at creation and again at
        certification: the entries must cover every school with `is_active`
        set exactly once, or the request is rejected with
        `ERR_SNAPSHOT_INCOMPLETE_COVERAGE`."
        PRD §3.2: "The `is_active` flag defaults to true and governs snapshot
        coverage: every active school must appear in every certified poverty
        snapshot."

        Design: Corner/errors/snapshot_incomplete_coverage_rejected
        """
        s1 = register_school("Cov A", "100605", grade_span_high=5)
        grant = open_grant(2067, 5_000_000)
        snap = create_snapshot(
            grant["id"], [snapshot_entry(s1["id"], 50, 100)])
        # A newly registered active school makes the draft's coverage stale.
        register_school("Cov B", "100606", grade_span_low=6,
                        grade_span_high=8)
        grant = get_grant(grant["id"])
        resp = api_client.certify_snapshot(
            snap["id"], {"expected_grant_version": grant["version"]},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_INCOMPLETE_COVERAGE)
        after = validate_success(api_client.get_snapshot(snap["id"], DIRECTOR))
        assert after["status"] == "DRAFT", "snapshot must stay DRAFT"

    def test_duplicate_school_entry_rejected(self):
        """PRD §3.2: "Within an entry the low-income count must be at least
        zero and at most the total, and the total must be strictly positive;
        repeating a `school_id` is rejected with
        `ERR_DUPLICATE_SCHOOL_ENTRY`."

        Design: Corner/errors/duplicate_school_entry_rejected
        """
        s1 = register_school("Dup School", "100607", grade_span_high=5)
        grant = open_grant(2068, 5_000_000)
        resp = api_client.create_snapshot(
            create_snapshot_payload(
                grant["id"],
                [snapshot_entry(s1["id"], 50, 100),
                 snapshot_entry(s1["id"], 51, 100)]),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCHOOL_ENTRY)
        rows, meta = validate_paginated(
            api_client.list_snapshots(DIRECTOR, params={"grant_id": grant["id"]}))
        assert meta["total_count"] == 0, "no snapshot row may be persisted"

    def test_deactivate_school_locked_by_snapshot_rejected(self):
        """PRD §3.2: "The analyst may later flip `is_active`, but a school
        that appears in any `CERTIFIED` snapshot can no longer be deactivated
        — the attempt is rejected with `ERR_SCHOOL_LOCKED_BY_SNAPSHOT`."

        Design: Corner/errors/deactivate_school_locked_by_snapshot_rejected
        """
        school = register_school("Locked School", "100611")
        grant = open_grant(2079, 5_000_000)
        snap = create_snapshot(
            grant["id"], [snapshot_entry(school["id"], 50, 100)])
        certify_snapshot(snap["id"], grant["id"])
        resp = api_client.update_school(school["id"], {"is_active": False},
                                        ANALYST)
        validate_error(resp, ApiErrorId.ERR_SCHOOL_LOCKED_BY_SNAPSHOT)

    def test_occ_stale_snapshot_certify_returns_412(self):
        """PRD §2.7: "Creating a budget amendment and certifying a poverty
        snapshot both require a non-optional `expected_grant_version` field in
        the request body, carrying the grant's `version` as the client last
        read it. If the value does not match the grant's current `version` —
        because a prior amendment create, approve, or void, a snapshot
        certification, a ranking lock, a finalization, or any other grant-row
        mutation has advanced it since the client's read — the request is
        rejected with `ERR_STALE_GRANT_VERSION` (HTTP 412), and nothing is
        written."

        Design: Corner/complexity_layers/occ_stale_snapshot_certify_returns_412
        """
        school = register_school("OCC Snap School", "100634")
        grant = open_grant(2047, 5_000_000)
        stale_version = grant["version"]
        n1 = create_snapshot(
            grant["id"], [snapshot_entry(school["id"], 50, 100)])
        certify_snapshot(n1["id"], grant["id"])  # advances the grant version
        n2 = create_snapshot(
            grant["id"], [snapshot_entry(school["id"], 55, 100)])
        resp = api_client.certify_snapshot(
            n2["id"], {"expected_grant_version": stale_version}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_STALE_GRANT_VERSION)
        n2_after = validate_success(api_client.get_snapshot(n2["id"], DIRECTOR))
        assert n2_after["status"] == "DRAFT", "nothing is written on 412"
        n1_after = validate_success(api_client.get_snapshot(n1["id"], DIRECTOR))
        assert n1_after["status"] == "CERTIFIED", \
            "N1 remains the sole CERTIFIED snapshot"


class TestRankingComputation:

    def test_rank_tie_break_by_headcount_then_created_at(self):
        """PRD §3.3: "`rank_position` orders every school in the snapshot by
        `poverty_pct_bp` descending; ties break on `low_income_student_count`
        descending, and any remaining tie breaks on the school's `created_at`
        ascending. The UUID `id` is never used as a tie-break. Positions are
        one-based: rank 1 is the highest-poverty school."

        Design: Corner/calculations/rank_tie_break_by_headcount_then_created_at
        """
        sa = register_school("Tie Alpha", "100301", grade_span_high=5)
        sb = register_school("Tie Beta", "100302", grade_span_high=5)
        sc = register_school("Tie Gamma", "100303", grade_span_high=5)
        grant = open_grant(2059, 10_000_000)
        snap = create_snapshot(
            grant["id"],
            [snapshot_entry(sa["id"], 100, 200),
             snapshot_entry(sb["id"], 100, 200),
             snapshot_entry(sc["id"], 150, 300)])
        certify_snapshot(snap["id"], grant["id"])
        lock_rankings(grant["id"])

        def rank_of(school_id):
            rows = validate_success(api_client.list_allocations(
                DIRECTOR, params={"grant_id": grant["id"],
                                  "school_id": school_id}))
            return rows[0]

        ra, rb, rc = rank_of(sa["id"]), rank_of(sb["id"]), rank_of(sc["id"])
        for row in (ra, rb, rc):
            assert_school_allocation(row)
            assert row["poverty_pct_bp"] == 5000, \
                "all three schools sit at exactly 5000 bp"
        assert rc["rank_position"] == 1, "headcount 150 wins the 5000 bp tie"
        assert ra["rank_position"] == 2, "earlier created_at wins over Beta"
        assert rb["rank_position"] == 3

    def test_must_serve_flag_at_75pct(self):
        """PRD §3.3: "`eligibility_flag` is evaluated on the rounded
        basis-point value: at least 7500 basis points (seventy-five percent)
        marks `MUST_SERVE`; at least 3500 but below 7500 marks `ELIGIBLE`;
        below 3500 marks `BELOW_THRESHOLD`."
        PRD §3.3: "`program_model` is `SCHOOLWIDE` when the school's poverty
        percentage reaches at least 4000 basis points (forty percent) and
        `TARGETED_ASSISTANCE` otherwise."

        Design: Corner/state_machines/must_serve_flag_at_75pct
        """
        ctx = setup_ranking_locked(2042, [(380, 500), (370, 500)])
        hi = ctx["allocations"][ctx["schools"][0]["id"]]
        lo = ctx["allocations"][ctx["schools"][1]["id"]]
        assert hi["poverty_pct_bp"] == 7600
        assert hi["eligibility_flag"] == "MUST_SERVE", "7600 bp >= 7500 bp"
        assert hi["program_model"] == "SCHOOLWIDE"
        assert lo["poverty_pct_bp"] == 7400
        assert lo["eligibility_flag"] == "ELIGIBLE", "7400 bp < 7500 bp"

    def test_schoolwide_threshold_exact_40pct(self):
        """PRD §3.3: "`program_model` is `SCHOOLWIDE` when the school's
        poverty percentage reaches at least 4000 basis points (forty percent)
        and `TARGETED_ASSISTANCE` otherwise."
        PRD §3.3: "`poverty_pct_bp` is the school's `low_income_student_count`
        multiplied by 10,000 and divided by its `total_student_count`, rounded
        half up to a whole basis point."

        Design: Difficulty/boundary_precision_check/schoolwide_threshold_exact_40pct
        """
        ctx = setup_ranking_locked(2045, [(200, 500), (195, 500)])
        hi = ctx["allocations"][ctx["schools"][0]["id"]]
        lo = ctx["allocations"][ctx["schools"][1]["id"]]
        assert hi["poverty_pct_bp"] == 4000, "200/500 is exactly 4000 bp"
        assert hi["program_model"] == "SCHOOLWIDE", \
            "the 4000 bp boundary is inclusive (at least 4000)"
        assert lo["poverty_pct_bp"] == 3900, "195/500 is exactly 3900 bp"
        assert lo["program_model"] == "TARGETED_ASSISTANCE"
        assert hi["eligibility_flag"] == "ELIGIBLE"
        assert lo["eligibility_flag"] == "ELIGIBLE", \
            "3500 <= 3900 < 7500 marks ELIGIBLE for both"

    def test_schoolwide_threshold_recomputed_on_recertification(self):
        """PRD §3.2: "At depth two, if the grant is `RANKING_LOCKED` or
        `ALLOCATED`, every school allocation of the grant is recomputed in
        place from the new snapshot: the ranking figures of §3.3 are
        re-derived, and when the grant is `ALLOCATED` the set-aside minimums,
        the equitable share, and the allocation waterfall of §3.4 are re-run
        as well; any allocation that had been `CERTIFIED` flips back to
        `PENDING`, and newly active schools receive fresh `PENDING` rows
        (schools absent from the new entries cannot exist among the old rows,
        because coverage is total over active schools)."
        PRD §3.3: "`program_model` is `SCHOOLWIDE` when the school's poverty
        percentage reaches at least 4000 basis points (forty percent) and
        `TARGETED_ASSISTANCE` otherwise."

        Design: Difficulty/boundary_precision_check/schoolwide_threshold_exact_40pct
        """
        school = register_school("Recompute School", "000701")
        grant = open_grant(2044, 10_000_000)
        snap1 = create_snapshot(
            grant["id"], [snapshot_entry(school["id"], 200, 500)])
        certify_snapshot(snap1["id"], grant["id"])
        lock_rankings(grant["id"])
        rows = validate_success(api_client.list_allocations(
            DIRECTOR, params={"grant_id": grant["id"],
                              "school_id": school["id"]}))
        assert rows[0]["program_model"] == "SCHOOLWIDE", "4000 bp at lock"
        # Recertify with the school now at 195/500 = 3900 bp: the ranking
        # figures are re-derived in place by the cascade.
        snap2 = create_snapshot(
            grant["id"], [snapshot_entry(school["id"], 195, 500)])
        certify_snapshot(snap2["id"], grant["id"])
        rows = validate_success(api_client.list_allocations(
            DIRECTOR, params={"grant_id": grant["id"],
                              "school_id": school["id"]}))
        assert rows[0]["poverty_pct_bp"] == 3900
        assert rows[0]["program_model"] == "TARGETED_ASSISTANCE", \
            "crossing below 4000 bp flips the program model"


class TestAllocationCertification:

    def test_allocation_certify_gated_by_grant_state(self):
        """PRD §3.3: "Once the grant is `ALLOCATED`, the director certifies
        individual allocations: a `PENDING` allocation transitions to
        `CERTIFIED` (a row in any other state is rejected with
        `ERR_ALLOCATION_NOT_PENDING`), and the operation requires the grant to
        be `ALLOCATED` (else `ERR_GRANT_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/allocation_certify_gated_by_grant_state
        """
        ctx = setup_ranking_locked(2046, [(100, 100)])
        allocation = ctx["allocations"][ctx["schools"][0]["id"]]
        assert allocation["status"] == "PENDING"
        resp = api_client.certify_allocation(allocation["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_GRANT_INVALID_STATE)
        still = validate_success(
            api_client.get_allocation(allocation["id"], DIRECTOR))
        assert still["status"] == "PENDING", "rejection must not mutate"
        finalize_allocations(ctx["grant"]["id"])
        ok = validate_success(
            api_client.certify_allocation(allocation["id"], DIRECTOR))
        assert ok["status"] == "CERTIFIED", \
            "the identical call succeeds once the grant is ALLOCATED"

    def test_allocation_certify_bumps_allocation_version(self):
        """PRD §3.3: "Certification bumps the allocation's own `version`."
        PRD §2.4: "`version` (integer): A system-managed integer that
        increments with every modification to the resource, enabling
        optimistic concurrency control."

        Design: Difficulty/cross_entity_state_dependency/allocation_certify_gated_by_grant_state
        """
        ctx = setup_allocated(2043, [(100, 100)])
        allocation = ctx["allocations"][ctx["schools"][0]["id"]]
        before = allocation["version"]
        certified = validate_success(
            api_client.certify_allocation(allocation["id"], DIRECTOR))
        assert certified["status"] == "CERTIFIED"
        assert certified["version"] == before + 1, \
            "certification increments the allocation's own version by one"

    def test_allocation_double_certify_rejected(self):
        """PRD §3.3: "a `PENDING` allocation transitions to `CERTIFIED` (a row
        in any other state is rejected with `ERR_ALLOCATION_NOT_PENDING`)".

        Design: Corner/errors/allocation_double_certify_rejected
        """
        ctx = setup_certified_allocation(2096, [(100, 100)])
        resp = api_client.certify_allocation(ctx["allocation"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_PENDING)


class TestCertifiedSnapshotCardinality:

    def test_snapshot_certify_supersedes_conserves_cardinality(self):
        """PRD §3.2: "At depth one, any other snapshot of the same grant
        currently in `CERTIFIED` flips to `SUPERSEDED` — the
        certified-cardinality invariant guarantees at most one certified
        snapshot per grant."

        Design: Difficulty/compensating_invariant/snapshot_certify_supersedes_conserves_cardinality
        """
        school = register_school("Nova School", "000504")
        grant = open_grant(2050, 5_000_000)
        n1 = create_snapshot(
            grant["id"], [snapshot_entry(school["id"], 50, 100)])
        certify_snapshot(n1["id"], grant["id"])
        rows, meta = validate_paginated(api_client.list_snapshots(
            DIRECTOR, params={"grant_id": grant["id"], "status": "CERTIFIED"}))
        assert meta["total_count"] == 1 and rows[0]["id"] == n1["id"], \
            "exactly one CERTIFIED snapshot before the second certify"
        n2 = create_snapshot(
            grant["id"], [snapshot_entry(school["id"], 55, 100)])
        certify_snapshot(n2["id"], grant["id"])
        rows, meta = validate_paginated(api_client.list_snapshots(
            DIRECTOR, params={"grant_id": grant["id"], "status": "CERTIFIED"}))
        assert meta["total_count"] == 1, \
            "the certify+supersede pair conserves certified cardinality at 1"
        assert rows[0]["id"] == n2["id"]
        n1_after = validate_success(api_client.get_snapshot(n1["id"], DIRECTOR))
        assert n1_after["status"] == "SUPERSEDED"

    def test_certified_cardinality_survives_repeated_recertification(self):
        """PRD §3.2: "At depth one, any other snapshot of the same grant
        currently in `CERTIFIED` flips to `SUPERSEDED` — the
        certified-cardinality invariant guarantees at most one certified
        snapshot per grant."
        PRD §2.6: "the system stamps a generation counter, `ranking_version`,
        that starts at zero and increments on every successful ranking lock
        and every snapshot certification — two events that re-baseline the
        school figures."

        Design: Difficulty/compensating_invariant/snapshot_certify_supersedes_conserves_cardinality
        """
        school = register_school("Nova School", "000504")
        grant = open_grant(2053, 5_000_000)
        n1 = create_snapshot(
            grant["id"], [snapshot_entry(school["id"], 50, 100)])
        certify_snapshot(n1["id"], grant["id"])
        n2 = create_snapshot(
            grant["id"], [snapshot_entry(school["id"], 55, 100)])
        certify_snapshot(n2["id"], grant["id"])
        # An uncertified draft must not disturb the certified cardinality.
        n3 = create_snapshot(
            grant["id"], [snapshot_entry(school["id"], 60, 100)])
        rows, meta = validate_paginated(api_client.list_snapshots(
            DIRECTOR, params={"grant_id": grant["id"], "status": "CERTIFIED"}))
        assert meta["total_count"] == 1 and rows[0]["id"] == n2["id"]
        certify_snapshot(n3["id"], grant["id"])
        rows, meta = validate_paginated(api_client.list_snapshots(
            DIRECTOR, params={"grant_id": grant["id"], "status": "CERTIFIED"}))
        assert meta["total_count"] == 1 and rows[0]["id"] == n3["id"], \
            "cardinality stays exactly 1 across a third certification"
        n2_after = validate_success(api_client.get_snapshot(n2["id"], DIRECTOR))
        assert n2_after["status"] == "SUPERSEDED"
        grant_after = get_grant(grant["id"])
        assert grant_after["ranking_version"] == 3, \
            "three certifications, no ranking lock: ranking_version == 3"

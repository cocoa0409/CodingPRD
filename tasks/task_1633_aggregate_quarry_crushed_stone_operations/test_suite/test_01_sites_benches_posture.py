"""Sites, benches, reclamation bonds, MSHA-driven posture and its cascades."""
import pytest

from test_helpers import (
    ADMIN,
    FINANCE,
    FOREMAN,
    MANAGER,
    NON_EXISTENT_UUID,
    SAFETY,
    ApiErrorId,
    create_approved_plan,
    create_bench,
    create_released_bench,
    create_site,
    create_site_payload,
    create_training,
    get_bench,
    get_shot_plan,
    get_site,
    issue_citation,
    open_inspection,
    post_bond,
    release_bench,
    set_clock,
    validate_error,
    validate_success,
)


class TestSiteCreation:
    def test_site_create_computed_defaults(self, api):
        """PRD 3.1: "A new site starts clean: `disturbed_acres`,
        `bond_required_usd`, and `bond_posted_usd` are all zero,
        `bond_adequacy` reads `ADEQUATE`, and `posture` reads `OPERATING`."

        Design: Corner/entities/site_create_computed_defaults
        """
        site = validate_success(
            api.create_site(create_site_payload(), ADMIN), 201)
        assert site["posture"] == "OPERATING"
        assert site["bond_adequacy"] == "ADEQUATE"
        assert site["disturbed_acres"] == pytest.approx(0, abs=1e-9)
        assert site["bond_required_usd"] == pytest.approx(0, abs=1e-9)
        assert site["bond_posted_usd"] == pytest.approx(0, abs=1e-9)
        assert isinstance(site["version"], int)


class TestBenchCrudGuards:
    def test_bench_get_unknown_id_not_found(self, api):
        """PRD 2.7 tier 4: "Existence — path identifiers must resolve, then
        body foreign-key identifiers must resolve, checked left-to-right in
        input order; the first unresolvable identifier determines the
        rejection, `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/bench_get_unknown_id_not_found
        """
        resp = api.get_bench(NON_EXISTENT_UUID, MANAGER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_bench_create_missing_required_acreage(self, api):
        """PRD 2.7 tier 3: "Request shape — required fields present, types
        valid, enum values within their declared sets, numeric bounds such as
        strictly positive quantities satisfied ... otherwise
        `ERR_INVALID_REQUEST` (400)."
        PRD 3.2: a bench requires "the `acreage` of disturbance the bench
        will represent once released (strictly positive)".

        Design: Corner/entities/bench_create_missing_required_acreage_returns_invalid_request
        """
        site = create_site()
        payload = {"site_id": site["id"], "bench_label": "B1",
                   "elevation_ft": 1400}
        resp = api.create_bench(payload, MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_bench_create_unknown_site_fk_returns_not_found(self, api):
        """PRD 2.7 tier 4: "Existence — path identifiers must resolve, then
        body foreign-key identifiers must resolve, checked left-to-right in
        input order; the first unresolvable identifier determines the
        rejection, `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/bench_create_unknown_site_fk_returns_not_found
        """
        payload = {"site_id": NON_EXISTENT_UUID, "bench_label": "B1",
                   "elevation_ft": 1400, "acreage": 5.0}
        resp = api.create_bench(payload, MANAGER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestComputedSiteRead:
    def test_computed_read_site_fields_after_release_and_bond(self, api):
        """PRD 3.1: "The `bond_required_usd` figure is phased to the
        life-cycle stage of the disturbance: acres on benches that are
        `RELEASED`, `ON_HOLD`, or `MINED_OUT` count at the full
        `bond_rate_per_acre_usd`".
        PRD 3.1: "The `bond_adequacy` reads `ADEQUATE` when posted coverage
        is at least the requirement, and `DEFICIENT` the moment coverage
        falls below it."

        Design: Corner/endpoints/computed_read_site_fields_after_release_and_bond
        """
        site = create_site()
        post_bond(site["id"], amount_usd=100000)
        create_released_bench(site["id"], acreage=5.0)
        site = get_site(site["id"])
        assert site["disturbed_acres"] == pytest.approx(5.0, abs=1e-6)
        assert site["bond_required_usd"] == pytest.approx(60000.00, abs=1e-6)
        assert site["bond_posted_usd"] == pytest.approx(100000.00, abs=1e-6)
        assert site["bond_adequacy"] == "ADEQUATE"
        assert site["posture"] == "OPERATING"


class TestBenchReleaseGates:
    def test_posture_restricted_blocks_bench_release(self, api):
        """PRD 3.2: "The site's posture must be `OPERATING` — a `RESTRICTED`
        or `SUSPENDED` site rejects the release with
        `ERR_SITE_POSTURE_BLOCKED`."

        Design: Corner/validations/posture_restricted_blocks_bench_release
        """
        site = create_site()
        # No bond posted: releasing B1 drops coverage to DEFICIENT.
        b1 = create_released_bench(site["id"], bench_label="B1",
                                   elevation_ft=1400, acreage=5.0)
        site = get_site(site["id"])
        assert site["posture"] == "RESTRICTED"
        assert site["bond_adequacy"] == "DEFICIENT"
        b2 = create_bench(site["id"], bench_label="B2", elevation_ft=1500,
                          acreage=2.0)
        resp = api.release_bench(b2["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_SITE_POSTURE_BLOCKED)
        assert get_bench(b2["id"])["status"] == "PLANNED"

    def test_bench_topdown_sequence_violation_rejected(self, api):
        """PRD 3.2: "Top-down ordering is enforced by elevation: every bench
        of the same site whose `elevation_ft` is greater than this bench's
        must already stand `MINED_OUT`, `RECLAMATION_IN_PROGRESS`, or
        `RECLAIMED`, otherwise the release fails with
        `ERR_BENCH_SEQUENCE_VIOLATION`."

        Design: Corner/validations/bench_topdown_sequence_violation_rejected
        """
        site = create_site()
        post_bond(site["id"], amount_usd=200000)
        b1 = create_bench(site["id"], bench_label="B1", elevation_ft=1400,
                          acreage=5.0)
        b2 = create_bench(site["id"], bench_label="B2", elevation_ft=1380,
                          acreage=3.0)
        resp = api.release_bench(b2["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_BENCH_SEQUENCE_VIOLATION)
        assert get_bench(b2["id"])["status"] == "PLANNED"
        # Releasing and mining out the higher bench unblocks the lower one.
        release_bench(b1["id"])
        validate_success(api.mark_bench_mined_out(b1["id"], MANAGER))
        b2 = release_bench(b2["id"])
        assert b2["status"] == "RELEASED"

    def test_permit_acreage_cap_rejected(self, api):
        """PRD 3.2: "Permit headroom is checked last among the release
        gates: the site's `disturbed_acres` after the release — the current
        figure plus this bench's `acreage` — must not exceed
        `permitted_acres`, with equality permitted, otherwise
        `ERR_PERMIT_ACREAGE_EXCEEDED`."

        Design: Corner/validations/permit_acreage_cap_rejected
        """
        site = create_site(permitted_acres=8.0)
        post_bond(site["id"], amount_usd=200000)
        create_released_bench(site["id"], bench_label="B1", elevation_ft=1500,
                              acreage=5.0)
        b2 = create_bench(site["id"], bench_label="B2", elevation_ft=1600,
                          acreage=4.0)
        resp = api.release_bench(b2["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_PERMIT_ACREAGE_EXCEEDED)
        assert get_bench(b2["id"])["status"] == "PLANNED"
        assert get_site(site["id"])["disturbed_acres"] == pytest.approx(
            5.0, abs=1e-6)

    def test_active_shotplan_blocks_mark_mined_out(self, api):
        """PRD 3.2: "The declaration is refused with `ERR_ACTIVE_SHOT_PLAN`
        while any shot plan on the bench stands in `APPROVED`, `DRILLING`,
        `DRILLED`, `LOADED`, or `ON_HOLD`."

        Design: Corner/validations/active_shotplan_blocks_mark_mined_out
        """
        site = create_site()
        post_bond(site["id"], amount_usd=100000)
        bench = create_released_bench(site["id"])
        plan = create_approved_plan(bench["id"])
        resp = api.mark_bench_mined_out(bench["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_SHOT_PLAN)
        # Cancelling the plan unblocks the mined-out declaration.
        validate_success(api.cancel_shot_plan(plan["id"], FOREMAN))
        bench = validate_success(api.mark_bench_mined_out(bench["id"],
                                                          MANAGER))
        assert bench["status"] == "MINED_OUT"


class TestReclamationLifecycle:
    def test_terminal_lockdown_reclaimed_bench_cannot_transition(self, api):
        """PRD 3.2: "`RECLAIMED` is terminal."
        PRD 2.7 tier 5: "Own state — the target resource's own state must
        permit the requested transition, and terminal states accept no
        further transitions at all, otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/terminal_lockdown_reclaimed_bench_cannot_transition
        """
        site = create_site()
        post_bond(site["id"], amount_usd=200000)
        bench = create_released_bench(site["id"])
        validate_success(api.mark_bench_mined_out(bench["id"], MANAGER))
        validate_success(api.start_reclamation(bench["id"], MANAGER))
        bench = validate_success(api.complete_reclamation(bench["id"],
                                                          MANAGER))
        assert bench["status"] == "RECLAIMED"
        resp = api.hold_bench(bench["id"], {"reason": "GEOTECH"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_bench(bench["id"])["status"] == "RECLAIMED"

    def test_reclamation_guard_reads_pre_transition_posture(self, api):
        """PRD 3.1: "Transition guards that consult posture — such as the
        reclamation-completion guard in §3.2 — always evaluate against the
        posture in force *before* the transition commits; the recomputation
        above applies only afterwards."

        Design: Difficulty/combinatorial_formula/bond_posture_circular_evaluation_order
        """
        site = create_site()
        post_bond(site["id"], amount_usd=50000)
        b1 = create_released_bench(site["id"], bench_label="B1",
                                   elevation_ft=1400, acreage=4.0)
        validate_success(api.mark_bench_mined_out(b1["id"], MANAGER))
        b2 = create_released_bench(site["id"], bench_label="B2",
                                   elevation_ft=1380, acreage=3.0)
        validate_success(api.mark_bench_mined_out(b2["id"], MANAGER))
        validate_success(api.start_reclamation(b2["id"], MANAGER))
        # required = 4.0*12000 + 3.0*12000*0.5 = 66000 > 50000 -> RESTRICTED
        assert get_site(site["id"])["posture"] == "RESTRICTED"
        # The guard reads the PRE-transition posture (RESTRICTED, allowed).
        b2 = validate_success(api.complete_reclamation(b2["id"], MANAGER))
        assert b2["status"] == "RECLAIMED"

    def test_reclamation_recomputes_posture_in_pinned_order(self, api):
        """PRD 3.2: "After the transition commits, the pinned order of §3.1
        runs in full — the bench's acres leave the disturbed set, the
        requirement is recomputed, adequacy is re-derived, and posture is
        re-derived — so a reclamation that cures a bond deficiency flips the
        site from `RESTRICTED` back to `OPERATING` inside the same request."

        Design: Difficulty/combinatorial_formula/bond_posture_circular_evaluation_order
        """
        site = create_site()
        post_bond(site["id"], amount_usd=50000)
        b1 = create_released_bench(site["id"], bench_label="B1",
                                   elevation_ft=1400, acreage=4.0)
        validate_success(api.mark_bench_mined_out(b1["id"], MANAGER))
        b2 = create_released_bench(site["id"], bench_label="B2",
                                   elevation_ft=1380, acreage=3.0)
        validate_success(api.mark_bench_mined_out(b2["id"], MANAGER))
        validate_success(api.start_reclamation(b2["id"], MANAGER))
        validate_success(api.complete_reclamation(b2["id"], MANAGER))
        site = get_site(site["id"])
        assert site["disturbed_acres"] == pytest.approx(4.0, abs=1e-6)
        assert site["bond_required_usd"] == pytest.approx(48000.00, abs=1e-6)
        assert site["bond_adequacy"] == "ADEQUATE"
        assert site["posture"] == "OPERATING"


class TestManualHoldVsPostureCascade:
    def test_manual_bench_hold_survives_posture_recovery(self, api):
        """PRD 3.9: "Leaving `SUSPENDED` for `OPERATING` or `RESTRICTED`
        fires the recovery cascade: exactly the benches whose `hold_reason`
        is `MSHA_SUSPENSION` are released back to `RELEASED`".
        PRD 3.9: "Benches held manually — any other `hold_reason` — are
        untouched by recovery and resume only through an explicit resume by
        a `SiteManager`."

        Design: Corner/state_machines/manual_bench_hold_survives_posture_recovery
        """
        site = create_site()
        post_bond(site["id"], amount_usd=100000)
        bench = create_released_bench(site["id"])
        bench = validate_success(
            api.hold_bench(bench["id"], {"reason": "GEOTECH"}, MANAGER))
        assert bench["hold_reason"] == "GEOTECH"
        insp = open_inspection(site["id"], inspection_type="SPOT")
        cit = issue_citation(insp["id"], s_and_s=True,
                             abatement_due_on="2026-07-15")
        assert get_site(site["id"])["posture"] == "SUSPENDED"
        validate_success(api.abate_msha_citation(cit["id"],
                                                 {"abated_on": "2026-08-01"},
                                                 SAFETY))
        assert get_site(site["id"])["posture"] == "OPERATING"
        bench = get_bench(bench["id"])
        assert bench["status"] == "ON_HOLD"
        assert bench["hold_reason"] == "GEOTECH"
        bench = validate_success(api.resume_bench(bench["id"], MANAGER))
        assert bench["status"] == "RELEASED"


class TestBondRelease:
    def test_bond_release_coverage_floor_and_exact_boundary(self, api):
        """PRD 3.1: "The governing rule is post-release coverage: the site's
        posted coverage after the release must remain at least
        `bond_required_usd`, otherwise the release is rejected with
        `ERR_BOND_BELOW_REQUIRED`."
        PRD 3.1: "A release that leaves a remainder moves the bond from
        `POSTED` to `PARTIALLY_RELEASED`".

        Design: Corner/validations/bond_release_coverage_floor_and_exact_boundary
        """
        site = create_site()
        bond = post_bond(site["id"], amount_usd=100000)
        b1 = create_released_bench(site["id"], bench_label="B1",
                                   elevation_ft=1400, acreage=5.0)
        validate_success(api.mark_bench_mined_out(b1["id"], MANAGER))
        b2 = create_released_bench(site["id"], bench_label="B2",
                                   elevation_ft=1380, acreage=3.0)
        validate_success(api.mark_bench_mined_out(b2["id"], MANAGER))
        validate_success(api.start_reclamation(b2["id"], MANAGER))
        # required = 5.0*12000 + 3.0*12000*0.5 = 78000.00
        assert get_site(site["id"])["bond_required_usd"] == pytest.approx(
            78000.00, abs=1e-6)
        bond_v = bond["version"]
        payload = {"release_amount_usd": 22001,
                   "expected_reclamation_bond_version": bond_v}
        resp = api.release_reclamation_bond(bond["id"], payload, FINANCE)
        validate_error(resp, ApiErrorId.ERR_BOND_BELOW_REQUIRED)
        # The rejected release consumed nothing: the same version still works.
        payload = {"release_amount_usd": 22000,
                   "expected_reclamation_bond_version": bond_v}
        bond = validate_success(
            api.release_reclamation_bond(bond["id"], payload, FINANCE))
        assert bond["status"] == "PARTIALLY_RELEASED"
        assert bond["released_usd"] == pytest.approx(22000, abs=1e-6)

    def test_occ_bond_release_stale_version(self, api):
        """PRD 2.8: "In each case, if the supplied value does not equal the
        resource's current `version` — because an accepted write (a
        production credit, a ticket draw, a reservation, a prior adjustment,
        a prior release, or a prior reprice) has advanced it since the
        client last read the resource — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated."

        Design: Corner/complexity_layers/occ_bond_release_stale_version
        """
        site = create_site()
        bond = post_bond(site["id"], amount_usd=100000)
        bond_v = bond["version"]
        payload = {"release_amount_usd": 10000,
                   "expected_reclamation_bond_version": bond_v}
        bond = validate_success(
            api.release_reclamation_bond(bond["id"], payload, FINANCE))
        assert bond["released_usd"] == pytest.approx(10000, abs=1e-6)
        assert bond["status"] == "PARTIALLY_RELEASED"
        assert bond["version"] == bond_v + 1
        stale = {"release_amount_usd": 5000,
                 "expected_reclamation_bond_version": bond_v}
        resp = api.release_reclamation_bond(bond["id"], stale, FINANCE)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        bond = validate_success(api.get_reclamation_bond(bond["id"], FINANCE))
        assert bond["released_usd"] == pytest.approx(10000, abs=1e-6)


class TestVersionIncrement:
    def test_version_increments_on_each_mutation(self, api):
        """PRD 2.5: "The `version` is an integer that increments on every
        mutation of the resource and underpins optimistic concurrency
        control (§2.8)."

        Design: Corner/complexity_layers/version_increments_on_each_mutation
        """
        site = create_site()
        post_bond(site["id"], amount_usd=100000)
        bench = create_bench(site["id"])
        v1 = bench["version"]
        bench = release_bench(bench["id"])
        assert bench["version"] == v1 + 1
        bench = validate_success(
            api.hold_bench(bench["id"], {"reason": "GEOTECH"}, MANAGER))
        assert bench["version"] == v1 + 2
        bench = validate_success(api.resume_bench(bench["id"], MANAGER))
        assert bench["version"] == v1 + 3


class TestPostureCascade:
    def _setup_operating_site_with_approved_plan(self, api):
        site = create_site()
        post_bond(site["id"], amount_usd=100000)
        bench = create_released_bench(site["id"])
        plan = create_approved_plan(bench["id"])
        insp = open_inspection(site["id"], inspection_type="REGULAR")
        return site, bench, plan, insp

    def test_overdue_citation_suspends_site_and_holds_bench_and_plan(self,
                                                                     api):
        """PRD 3.9: "Entering `SUSPENDED` fires the hold cascade: every
        bench of the site standing `RELEASED` moves to `ON_HOLD` with
        `hold_reason` set to the sentinel value `MSHA_SUSPENSION`, and every
        shot plan on those benches standing `APPROVED`, `DRILLING`,
        `DRILLED`, or `LOADED` moves to `ON_HOLD` with its prior status
        captured in `hold_return_state`."
        PRD 3.9: "the site is `SUSPENDED` when any citation reachable
        through its inspections stands `ISSUED`, is flagged
        significant-and-substantial, and is past its abatement deadline".

        Design: Difficulty/transitive_cascade/citation_overdue_posture_bench_shotplan_cascade
        """
        site, bench, plan, insp = \
            self._setup_operating_site_with_approved_plan(api)
        cit = issue_citation(insp["id"], s_and_s=True,
                             abatement_due_on="2026-07-15")
        assert cit["status"] == "ISSUED"
        site = get_site(site["id"])
        assert site["posture"] == "SUSPENDED"
        bench = get_bench(bench["id"])
        assert bench["status"] == "ON_HOLD"
        assert bench["hold_reason"] == "MSHA_SUSPENSION"
        plan = get_shot_plan(plan["id"])
        assert plan["status"] == "ON_HOLD"
        assert plan["hold_return_state"] == "APPROVED"

    def test_abatement_resumes_msha_suspension_holds(self, api):
        """PRD 3.9: "Leaving `SUSPENDED` for `OPERATING` or `RESTRICTED`
        fires the recovery cascade: exactly the benches whose `hold_reason`
        is `MSHA_SUSPENSION` are released back to `RELEASED`, and their held
        shot plans return to their captured `hold_return_state`, which then
        clears to null."

        Design: Difficulty/transitive_cascade/citation_overdue_posture_bench_shotplan_cascade
        """
        site, bench, plan, insp = \
            self._setup_operating_site_with_approved_plan(api)
        cit = issue_citation(insp["id"], s_and_s=True,
                             abatement_due_on="2026-07-15")
        assert get_site(site["id"])["posture"] == "SUSPENDED"
        validate_success(api.abate_msha_citation(cit["id"],
                                                 {"abated_on": "2026-08-01"},
                                                 SAFETY))
        assert get_site(site["id"])["posture"] == "OPERATING"
        bench = get_bench(bench["id"])
        assert bench["status"] == "RELEASED"
        assert bench["hold_reason"] is None
        plan = get_shot_plan(plan["id"])
        assert plan["status"] == "APPROVED"
        assert plan["hold_return_state"] is None


class TestMshaInspectionClose:
    def test_inspection_close_with_open_citations_rejected_then_succeeds(
            self, api):
        """PRD 3.9: "Closing the inspection moves it `OPEN` → `CLOSED` and
        stamps `closed_on`, but only once every citation of the inspection
        stands `ABATED` or `VACATED`; otherwise the close is rejected with
        `ERR_OPEN_CITATIONS`."

        Design: Corner/state_machines/inspection_close_with_open_citations_rejected_then_succeeds
        """
        site = create_site()
        insp = open_inspection(site["id"], inspection_type="REGULAR")
        cit = issue_citation(insp["id"], s_and_s=False,
                             abatement_due_on="2026-09-01")
        resp = api.close_msha_inspection(insp["id"], SAFETY)
        validate_error(resp, ApiErrorId.ERR_OPEN_CITATIONS)
        # Any ISSUED citation keeps the site RESTRICTED (PRD 3.1).
        assert get_site(site["id"])["posture"] == "RESTRICTED"
        validate_success(api.abate_msha_citation(cit["id"],
                                                 {"abated_on": "2026-08-01"},
                                                 SAFETY))
        insp = validate_success(api.close_msha_inspection(insp["id"], SAFETY))
        assert insp["status"] == "CLOSED"
        assert insp["closed_on"] == "2026-08-01"
        assert get_site(site["id"])["posture"] == "OPERATING"


class TestTrainingRecord:
    def test_training_record_expiry_computed(self, api):
        """PRD 3.9: "The record's `expires_on` is twelve months after
        `completed_on`, and `is_current` is true when `expires_on` falls on
        or after the current logical date — the expiry day itself still
        counts."

        Design: Corner/entities/training_record_expiry_computed
        """
        record = create_training(miner_user_id="bf-1",
                                 completed_on="2025-08-01")
        assert record["expires_on"] == "2026-08-01"
        # Default logical date 2026-08-01 is the expiry day: still current.
        assert record["is_current"] is True
        set_clock("2026-08-02T00:00:00Z")
        record = validate_success(
            api.get_training_record(record["id"], SAFETY))
        assert record["is_current"] is False

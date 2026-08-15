"""Cross-entity state dependencies, temporal overlap intervals, and
compensating invariants."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_roster_party,
    api_client,
    create_attorney,
    create_conflicts_partner,
    create_matter,
    create_party,
    fund_deposit,
    refund_deposit,
    get_deposit,
    get_success_data,
    issue_letter,
    list_hits_for_check,
    make_client_headers,
    make_conflicts_partner_headers,
    make_responsible_attorney_headers,
    record_credit_assessment,
    run_conflict_check,
    set_clock,
    setup_countersign_ready,
    setup_matter_with_confirmed_hit,
    setup_matter_with_issued_letter,
    setup_open_matter,
    transition_deposit_payload,
    transition_letter_payload,
    transition_wall_payload,
    validate_error,
    validate_success,
    create_letter,
    create_wall,
)

INTAKE = TEST_USERS["intake_specialist_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestCountersignGatedByMatterClearance:
    def test_countersign_with_funded_retainer_fails_solely_on_clearance(self):
        """PRD §3.7: "The matter's `clearance_status` must be `CLEARED` or
        `WAIVED`, else `ERR_MATTER_CLEARANCE_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/countersign_gated_by_matter_clearance
        """
        p_x, p_y, atty, m1 = setup_matter_with_confirmed_hit(
            "Victor Whiskey Inc", "Xray Yankee Corp"
        )
        record_credit_assessment(m1["id"], 800)
        letter = create_letter(m1, atty)
        issue_letter(letter["id"], atty)
        deposit = get_deposit(m1["id"])
        funded = fund_deposit(deposit["id"], 2000000)
        assert funded["status"] == "FUNDED", "fiscal gate passes"

        resp = api_client.transition_engagement_letter(
            letter["id"],
            transition_letter_payload("COUNTERSIGN"),
            make_client_headers(p_y["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MATTER_CLEARANCE_BLOCKED)

    def test_letter_countersign_blocked_even_when_credit_and_retainer_pass(self):
        """PRD §3.7: "Countersignature — a `COUNTERSIGN` action by the owning
        client — is the moment intake becomes an open matter, and it is guarded
        by a strict gate chain evaluated in order. The letter must be `ISSUED`,
        else `ERR_LETTER_INVALID_STATE`. The caller must be the owning client
        whose `X-User-ID` equals the matter's `client_party_id`, else
        `ERR_FORBIDDEN`. The matter's `clearance_status` must be `CLEARED` or
        `WAIVED`, else `ERR_MATTER_CLEARANCE_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/countersign_gated_by_matter_clearance
        """
        p_x, p_y, atty, m1 = setup_matter_with_confirmed_hit(
            "Gate X Inc", "Gate Y Corp"
        )
        record_credit_assessment(m1["id"], 800)
        letter = create_letter(m1, atty)
        issue_letter(letter["id"], atty)
        deposit = get_deposit(m1["id"])
        fund_deposit(deposit["id"], deposit["required_cents"])

        # All fiscal gates pass; clearance BLOCKED is the sole blocker.
        m1_now = get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)
        assert m1_now["clearance_status"] == "BLOCKED"
        resp = api_client.transition_engagement_letter(
            letter["id"],
            transition_letter_payload("COUNTERSIGN"),
            make_client_headers(p_y["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MATTER_CLEARANCE_BLOCKED)
        letter_after = get_success_data(
            api_client.list_matter_engagement_letters(m1["id"], INTAKE), 200
        )
        assert letter_after[0]["status"] == "ISSUED", (
            "a rejected countersign must not advance the letter"
        )


class TestWaiverCreateGatedByCheckState:
    def test_waiver_create_rejected_once_check_superseded(self):
        """PRD §3.6: "The referenced hit must be `CONFIRMED` — anything else
        fails with `ERR_HIT_NOT_CONFIRMED` — and the check that produced it
        must not be `SUPERSEDED`, or the draft fails with
        `ERR_CHECK_SUPERSEDED`".

        Design: Difficulty/cross_entity_state_dependency/waiver_create_gated_by_check_state
        """
        p_x = create_party("Zulu Alpha Inc")
        p_y = create_party("Bravo Charlie Corp")
        p_z = create_party("Extra Witness LLC")
        atty = create_attorney()
        create_matter(p_x["id"], atty["id"], matter_title="M0")
        m1 = create_matter(p_y["id"], atty["id"], matter_title="M1")
        add_roster_party(m1["id"], p_x["id"], "ADVERSE")
        chk = run_conflict_check(m1["id"], "STRICT")
        hit = list_hits_for_check(chk["id"])[0]
        ra = make_responsible_attorney_headers(atty["id"])
        get_success_data(
            api_client.review_conflict_hit(
                hit["id"], {"decision": "CONFIRMED"}, ra
            ),
            200,
        )
        # Roster add supersedes the COMPLETED INTAKE check.
        add_roster_party(m1["id"], p_z["id"], "WITNESS")

        resp = api_client.create_waiver_request(
            m1["id"],
            {"conflict_hit_id": hit["id"], "proposed_terms": "terms"},
            ra,
        )
        validate_error(resp, ApiErrorId.ERR_CHECK_SUPERSEDED)

    def test_confirmed_hit_alone_does_not_permit_waiver_after_supersede(self):
        """PRD §3.4: "Supersession moves the older check from `COMPLETED` to
        `SUPERSEDED`, cascades every one of its hits still `PENDING` to `STALE`
        with each such hit's `version` incremented, and triggers a clearance
        recompute on the matter."
        PRD §3.6: "The referenced hit must be `CONFIRMED` — anything else
        fails with `ERR_HIT_NOT_CONFIRMED` — and the check that produced it
        must not be `SUPERSEDED`, or the draft fails with
        `ERR_CHECK_SUPERSEDED`".

        Design: Difficulty/cross_entity_state_dependency/waiver_create_gated_by_check_state
        """
        p_x = create_party("Supersede X Inc")
        p_y = create_party("Supersede Y Corp")
        p_z = create_party("Supersede Witness LLC")
        atty = create_attorney()
        create_matter(p_x["id"], atty["id"], matter_title="M0")
        m1 = create_matter(p_y["id"], atty["id"], matter_title="M1")
        add_roster_party(m1["id"], p_x["id"], "ADVERSE")
        chk = run_conflict_check(m1["id"], "STRICT")
        hit = list_hits_for_check(chk["id"])[0]
        ra = make_responsible_attorney_headers(atty["id"])
        get_success_data(
            api_client.review_conflict_hit(
                hit["id"], {"decision": "CONFIRMED"}, ra
            ),
            200,
        )
        add_roster_party(m1["id"], p_z["id"], "WITNESS")

        # The hit remains CONFIRMED (only PENDING hits stale out) ...
        hit_now = get_success_data(
            api_client.get_conflict_hit(hit["id"], INTAKE), 200
        )
        assert hit_now["review_status"] == "CONFIRMED"
        # ... yet waiver creation still fails because the check is SUPERSEDED.
        resp = api_client.create_waiver_request(
            m1["id"],
            {"conflict_hit_id": hit["id"], "proposed_terms": "terms"},
            ra,
        )
        validate_error(resp, ApiErrorId.ERR_CHECK_SUPERSEDED)


class TestResponsibleAttorneyHalfOpenOverlap:
    def test_overlap_rejected_while_other_matter_open(self):
        """PRD §3.3: "Second, the adverse-overlap rule rejects the assignment
        with `ERR_ATTORNEY_ADVERSE_OVERLAP` when that attorney is already the
        responsible attorney on another matter currently `OPEN` and either the
        new matter's client appears on that other matter's roster in an
        `ADVERSE` role, or that other matter's client appears on the target
        matter's roster as `ADVERSE`."

        Design: Difficulty/resource_temporal_overlap/responsible_attorney_half_open_overlap
        """
        set_clock("2026-08-01T00:00:00Z")
        p_c = create_party("Halo Client Inc")
        p_a = create_party("Halo Adverse Corp")
        atty = create_attorney()
        partner = create_conflicts_partner()
        # Build M1 OPEN explicitly at the pinned clock.
        m1 = create_matter(p_c["id"], atty["id"], matter_title="M1")
        chk0 = run_conflict_check(m1["id"], "STRICT")
        assert chk0["hit_count"] == 0
        record_credit_assessment(m1["id"], 800)
        letter = create_letter(m1, atty)
        issue_letter(letter["id"], atty)
        dep = get_deposit(m1["id"])
        fund_deposit(dep["id"], 2000000)
        set_clock("2026-08-10T00:00:00Z")
        signed = validate_success(
            api_client.transition_engagement_letter(
                letter["id"],
                transition_letter_payload("COUNTERSIGN"),
                make_client_headers(p_c["id"]),
            ),
            200,
        )
        assert signed["status"] == "COUNTERSIGNED"
        add_roster_party(m1["id"], p_a["id"], "ADVERSE")

        resp = api_client.create_matter(
            {
                "client_party_id": p_a["id"],
                "responsible_attorney_id": atty["id"],
                "practice_group": "LITIGATION",
                "matter_title": "M2",
            },
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_ATTORNEY_ADVERSE_OVERLAP)

    def test_overlap_allowed_at_exact_close_instant_half_open_interval(self):
        """PRD §3.3: "The other matter's activity window is the half-open
        interval from its `opened_at` up to but not including its `closed_at`,
        so a closed matter whose `closed_at` is at or before the current time
        does not overlap."

        Design: Difficulty/resource_temporal_overlap/responsible_attorney_half_open_overlap
        """
        set_clock("2026-08-01T00:00:00Z")
        p_c = create_party("Halfopen Client Inc")
        p_a = create_party("Halfopen Adverse Corp")
        atty = create_attorney()
        partner = create_conflicts_partner()
        m1 = create_matter(p_c["id"], atty["id"], matter_title="M1")
        run_conflict_check(m1["id"], "STRICT")
        record_credit_assessment(m1["id"], 800)
        letter = create_letter(m1, atty)
        issue_letter(letter["id"], atty)
        dep = get_deposit(m1["id"])
        fund_deposit(dep["id"], 2000000)
        set_clock("2026-08-10T00:00:00Z")
        validate_success(
            api_client.transition_engagement_letter(
                letter["id"],
                transition_letter_payload("COUNTERSIGN"),
                make_client_headers(p_c["id"]),
            ),
            200,
        )
        add_roster_party(m1["id"], p_a["id"], "ADVERSE")

        set_clock("2026-08-20T00:00:00Z")
        closed = validate_success(
            api_client.transition_matter(
                m1["id"],
                {"action": "CLOSE"},
                make_conflicts_partner_headers(partner["id"]),
            ),
            200,
        )
        assert closed["lifecycle_status"] == "CLOSED"
        assert closed["closed_at"] == "2026-08-20T00:00:00.000Z"

        # At the SAME instant as closed_at, the half-open interval is disjoint.
        resp = api_client.create_matter(
            {
                "client_party_id": p_a["id"],
                "responsible_attorney_id": atty["id"],
                "practice_group": "LITIGATION",
                "matter_title": "M3",
            },
            INTAKE,
        )
        m3 = validate_success(resp, 201)
        assert m3["lifecycle_status"] == "INTAKE"


class TestLateralEmploymentClosedIntervalOverlap:
    def _open_matter_at(self, client_name: str, open_day: str, atty: dict) -> dict:
        """Create + clear + countersign a matter so it opens on `open_day`."""
        p = create_party(client_name)
        m = create_matter(p["id"], atty["id"], matter_title="M")
        run_conflict_check(m["id"], "STRICT")
        record_credit_assessment(m["id"], 800)
        letter = create_letter(m, atty)
        issue_letter(letter["id"], atty)
        dep = get_deposit(m["id"])
        fund_deposit(dep["id"], 2000000)
        set_clock(open_day)
        validate_success(
            api_client.transition_engagement_letter(
                letter["id"],
                transition_letter_payload("COUNTERSIGN"),
                make_client_headers(p["id"]),
            ),
            200,
        )
        return {"party": p, "matter": m}

    def test_matter_opened_on_employed_to_day_conflicts_inclusive_end(self):
        """PRD §2.7: "Lateral employment intervals treat
        `lateral_employed_to` as an inclusive last day."
        PRD §3.2: "A candidate matter overlaps the lateral's prior employment
        when its activity start day — the `opened_at` day for an `OPEN` or
        `CLOSED` matter, or the `created_at` day for an `INTAKE` matter, which
        counts as an active prospect — is on or before `lateral_employed_to`,
        and either the matter has no `closed_at` or its closing day is on or
        after `lateral_employed_from`."

        Design: Difficulty/resource_temporal_overlap/lateral_employment_closed_interval_overlap
        """
        set_clock("2025-06-30T00:00:00Z")
        atty = create_attorney()
        m0 = self._open_matter_at("Globex LLC", "2025-06-30T00:00:00Z", atty)

        set_clock("2026-08-10T00:00:00Z")
        lateral = create_attorney(
            full_name="Larry Lateral",
            bar_number="BAR009",
            hire_type="LATERAL",
            lateral_employed_from="2024-01-01",
            lateral_employed_to="2025-06-30",
            prior_client_names=["Globex"],
        )
        assert lateral["status"] == "LATERAL_PENDING", (
            "M0 opened_day 2025-06-30 <= employed_to 2025-06-30 (INCLUSIVE end) "
            "so the sweep created a hit"
        )
        hits = get_success_data(
            api_client.list_conflict_hits(
                make_conflicts_partner_headers(atty["id"]),
                params={"matched_matter_id": m0["matter"]["id"]},
            ),
            200,
        )
        assert hits[0]["matched_via"] == "LATERAL"
        assert hits[0]["matched_party_id"] == m0["party"]["id"]

    def test_matter_opened_day_after_employed_to_does_not_conflict(self):
        """PRD §2.7: "Lateral employment intervals treat
        `lateral_employed_to` as an inclusive last day."
        PRD §3.2: "The new attorney starts `LATERAL_PENDING` if the sweep
        created at least one hit, and `ACTIVE` otherwise; `INTERNAL` hires
        always start `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/lateral_employment_closed_interval_overlap
        """
        set_clock("2025-07-01T00:00:00Z")
        atty = create_attorney()
        self._open_matter_at("Initech Corp", "2025-07-01T00:00:00Z", atty)

        set_clock("2026-08-10T00:00:00Z")
        lateral = create_attorney(
            full_name="Lena Lateral",
            bar_number="BAR010",
            hire_type="LATERAL",
            lateral_employed_from="2024-01-01",
            lateral_employed_to="2025-06-30",
            prior_client_names=["Initech"],
        )
        assert lateral["status"] == "ACTIVE", (
            "M1 opened_day 2025-07-01 > employed_to 2025-06-30, so no overlap, "
            "no hit, immediate activation"
        )


class TestRetainerFundRefundConservation:
    def test_fund_then_equal_refund_restores_pending_and_zero_received(self):
        """PRD §3.8: "`funded_total_cents` and `refunded_total_cents` are
        cumulative sums that start at zero; `received_cents` is the currently
        held balance, computed as funded minus refunded. The deposit's `status`
        is re-derived after every mutation: `PENDING` when nothing is held,
        `PARTIALLY_FUNDED` when the held balance is greater than zero but below
        the requirement, and `FUNDED` when the held balance is greater than or
        equal to the requirement — equality counts as funded."

        Design: Difficulty/compensating_invariant/retainer_fund_refund_conservation
        """
        _, _, matter, _, deposit = setup_matter_with_issued_letter(
            "Conservation Client Inc"
        )
        assert deposit["required_cents"] == 2000000
        assert deposit["received_cents"] == 0
        assert deposit["status"] == "PENDING"

        mid = validate_success(
            api_client.transition_retainer_deposit(
                deposit["id"],
                transition_deposit_payload("FUND", 500000),
                BILLING,
            ),
            200,
        )
        assert mid["received_cents"] == 500000
        assert mid["status"] == "PARTIALLY_FUNDED"

        end = validate_success(
            api_client.transition_retainer_deposit(
                deposit["id"],
                transition_deposit_payload("REFUND", 500000),
                BILLING,
            ),
            200,
        )
        assert end["received_cents"] == 0, (
            "FUND(x) + REFUND(x) conserves received_cents"
        )
        assert end["status"] == "PENDING"
        assert end["funded_total_cents"] == 500000
        assert end["refunded_total_cents"] == 500000, (
            "cumulative totals prove the round trip, no drift"
        )

    def test_received_equals_funded_minus_refunded_throughout(self):
        """PRD §3.8: "`funded_total_cents` and `refunded_total_cents` are
        cumulative sums that start at zero; `received_cents` is the currently
        held balance, computed as funded minus refunded."
        PRD §3.8: "A refund must likewise be greater than zero and may not
        exceed the held balance — an amount above `received_cents` fails with
        `ERR_REFUND_EXCEEDS_BALANCE`; it adds to `refunded_total_cents` and
        re-derives status, cycling `FUNDED` → `PENDING` or `PARTIALLY_FUNDED` →
        `PENDING` when the full balance is returned, and dropping `FUNDED` →
        `PARTIALLY_FUNDED` on a partial refund."

        Design: Difficulty/compensating_invariant/retainer_fund_refund_conservation
        """
        _, _, matter, _, deposit = setup_matter_with_issued_letter(
            "Conservation Client Inc"
        )
        states = [deposit]
        states.append(fund_deposit(deposit["id"], 500000))
        states.append(refund_deposit(deposit["id"], 500000))
        for dep in states:
            assert dep["received_cents"] == (
                dep["funded_total_cents"] - dep["refunded_total_cents"]
            )
        assert [d["status"] for d in states] == [
            "PENDING",
            "PARTIALLY_FUNDED",
            "PENDING",
        ]


class TestWallExcludeReleaseConservation:
    def test_exclude_then_release_restores_original_exclusion_set(self):
        """PRD §3.5: "While a wall is `ACTIVE`, its exclusion list can be
        amended in place: an `EXCLUDE` action carrying an `attorney_id` appends
        that attorney, failing with `ERR_ATTORNEY_ALREADY_EXCLUDED` if the
        attorney is already listed, and a `RELEASE` action removes the named
        attorney, failing with `ERR_ATTORNEY_NOT_EXCLUDED` if the attorney is
        not currently listed. Both actions leave the wall `ACTIVE` and
        increment the wall's `version`."

        Design: Difficulty/compensating_invariant/wall_exclude_release_conservation
        """
        p_c = create_party("Wall Client Inc")
        atty_r = create_attorney()
        atty_a = create_attorney(full_name="Aaron Alpha", bar_number="BAR003")
        atty_b = create_attorney(full_name="Bella Beta", bar_number="BAR004")
        partner = create_conflicts_partner()
        matter = create_matter(p_c["id"], atty_r["id"], matter_title="M")
        wall = create_wall(
            matter["id"], partner, "CLIENT_REQUEST", [atty_a["id"]],
            memo="client requested screen",
        )
        assert wall["excluded_attorney_ids"] == [atty_a["id"]]
        assert wall["version"] == 1
        cp = make_conflicts_partner_headers(partner["id"])

        after_exclude = validate_success(
            api_client.transition_ethical_wall(
                wall["id"],
                transition_wall_payload("EXCLUDE", attorney_id=atty_b["id"]),
                cp,
            ),
            200,
        )
        assert set(after_exclude["excluded_attorney_ids"]) == {
            atty_a["id"],
            atty_b["id"],
        }
        assert after_exclude["status"] == "ACTIVE"
        assert after_exclude["version"] == 2

        after_release = validate_success(
            api_client.transition_ethical_wall(
                wall["id"],
                transition_wall_payload("RELEASE", attorney_id=atty_b["id"]),
                cp,
            ),
            200,
        )
        assert after_release["excluded_attorney_ids"] == [atty_a["id"]], (
            "EXCLUDE + RELEASE conserves the exclusion set"
        )
        assert after_release["status"] == "ACTIVE"
        assert after_release["version"] == 3

    def test_wall_stays_active_through_exclude_release_pair(self):
        """PRD §3.5: "Both actions leave the wall `ACTIVE` and increment the
        wall's `version`."

        Design: Difficulty/compensating_invariant/wall_exclude_release_conservation
        """
        p_c = create_party("Wall Version Client Inc")
        atty_r = create_attorney()
        atty_a = create_attorney(full_name="Aaron Alpha", bar_number="BAR003")
        atty_b = create_attorney(full_name="Bella Beta", bar_number="BAR004")
        partner = create_conflicts_partner()
        matter = create_matter(p_c["id"], atty_r["id"], matter_title="M")
        wall = create_wall(matter["id"], partner, "CLIENT_REQUEST", [atty_a["id"]])
        cp = make_conflicts_partner_headers(partner["id"])

        ex = validate_success(
            api_client.transition_ethical_wall(
                wall["id"],
                transition_wall_payload("EXCLUDE", attorney_id=atty_b["id"]),
                cp,
            ),
            200,
        )
        rel = validate_success(
            api_client.transition_ethical_wall(
                wall["id"],
                transition_wall_payload("RELEASE", attorney_id=atty_b["id"]),
                cp,
            ),
            200,
        )
        assert ex["status"] == "ACTIVE" and rel["status"] == "ACTIVE"
        assert rel["version"] == ex["version"] + 1

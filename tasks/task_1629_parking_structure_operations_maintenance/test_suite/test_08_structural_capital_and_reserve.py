"""Structural inspections, the CRITICAL cascade, capital reserve ledger, and
repair project lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_facility,
    create_inspection,
    create_parker,
    create_repair_project,
    enter_vehicle_at,
    get_facility,
    get_success_data,
    issue_credential,
    open_shift,
    pay_session_card_at,
    pay_session_cash,
    report_inspection,
    run_close_of_business,
    set_clock,
    setup_critical_reported_facility,
    setup_entry_ready_facility,
    setup_reported_inspection,
    submit_agreement,
    validate_error,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
ATT = TEST_USERS["parking_attendant_headers"]
AUD = TEST_USERS["revenue_auditor_headers"]
MS = TEST_USERS["maintenance_supervisor_headers"]


def test_structural_condition_index_weighted_scoring(api):
    """PRD: "The condition index is twenty times the weighted sum of the
    ratings — load-bearing at half weight, waterproofing at three-tenths,
    surface at one-fifth — rounded half-up to a whole number, so the index
    spans 20 to 100. The class follows: `CRITICAL` when the load-bearing
    rating is 2 or lower or the index falls below 40; otherwise `FAIR` when
    the index falls below 70; otherwise `SOUND`."
    PRD: "A `CRITICAL` report fires a three-link cascade."

    Design: Corner/calculations/structural_condition_index_weighted_scoring
    """
    facility = create_facility(name="WS Fac")
    inspection = setup_reported_inspection(
        facility["id"], load_bearing_rating=4, waterproofing_rating=3,
        surface_rating=2)
    assert inspection["condition_index"] == 66, (
        "round_half_up(20*(0.5*4 + 0.3*3 + 0.2*2)) = 66")
    assert inspection["condition_class"] == "FAIR", "66 < 70, load 4 above the override"
    assert get_facility(facility["id"])["posture"] == "NORMAL", (
        "no cascade for a non-CRITICAL class")


class TestCriticalInspectionCascade:
    """Depth-3 chain: CRITICAL report -> facility -> demotion -> revocation."""

    def _build(self, api):
        facility = create_facility(name="Cascade Fac", total_spaces=4,
                                   monthly_capacity=3, event_pool_spaces=0)
        agreements = []
        for i, name in enumerate(("One", "Two", "Three")):
            parker = create_parker(full_name=f"P {name}", email=f"p{i + 1}@x.com")
            agreement = submit_agreement(facility["id"], parker["id"])
            assert agreement["agreement_status"] == "APPROVED"
            agreements.append(agreement)
        credential = issue_credential(agreements[2]["id"], "TRANSPONDER", 5000)
        inspection = create_inspection(facility["id"], level_scope="L1")
        get_success_data(api.start_inspection(inspection["id"], MS))
        return facility, agreements, credential, inspection

    def test_report_computes_critical_and_restricts_facility(self, api):
        """PRD: "The load-bearing override dominates the arithmetic — ratings
        of (2, 5, 5) produce an index of 70 yet classify `CRITICAL`, not
        `SOUND`."
        PRD: "First, the facility's posture moves to `RESTRICTED`, its
        `closed_spaces` grows by the report's `closed_space_count`, and its
        `version` advances by one."

        Design: Difficulty/transitive_cascade/critical_inspection_cascades_to_credential_revocation
        """
        facility, agreements, credential, inspection = self._build(api)
        reported = validate_success(api.report_inspection(
            inspection["id"],
            {"load_bearing_rating": 2, "waterproofing_rating": 5,
             "surface_rating": 5, "closed_space_count": 2}, MS), 200)
        assert reported["condition_index"] == 70
        assert reported["condition_class"] == "CRITICAL", (
            "load-bearing 2 override fires even though index 70 is not < 40")
        after = get_facility(facility["id"])
        assert after["posture"] == "RESTRICTED"
        assert after["closed_spaces"] == 2

    def test_cascade_demotes_newest_approved_and_revokes_media(self, api):
        """PRD: "Second, the effective monthly capacity shrinks to the smaller
        of `monthly_capacity` and `total_spaces` minus the new
        `closed_spaces`, and the demotion loop of §3.4 runs: while committed
        agreements exceed effective capacity, the newest `APPROVED` agreement
        by descending `application_seq` flips to `WAITLISTED`. Third, for each
        demoted agreement, every credential standing `ACTIVE` flips to
        `REVOKED` and its deposit is refunded out of `deposit_liability_cents`."

        Design: Difficulty/transitive_cascade/critical_inspection_cascades_to_credential_revocation
        """
        facility, agreements, credential, inspection = self._build(api)
        get_success_data(api.report_inspection(
            inspection["id"],
            {"load_bearing_rating": 2, "waterproofing_rating": 5,
             "surface_rating": 5, "closed_space_count": 2}, MS))

        a3 = get_success_data(api.get_monthly_agreement(agreements[2]["id"], FM))
        assert a3["agreement_status"] == "WAITLISTED", (
            "committed 3 > effective capacity min(3, 4-2) = 2; newest demoted")
        a1 = get_success_data(api.get_monthly_agreement(agreements[0]["id"], FM))
        a2 = get_success_data(api.get_monthly_agreement(agreements[1]["id"], FM))
        assert a1["agreement_status"] == "APPROVED"
        assert a2["agreement_status"] == "APPROVED"

        cred_after = get_success_data(api.get_credential(credential["id"], FM))
        assert cred_after["credential_status"] == "REVOKED"
        assert get_facility(facility["id"])["deposit_liability_cents"] == 0


def test_inspection_cancel_after_report_rejected(api):
    """PRD: "The report lands the inspection in the terminal `REPORTED` with
    `condition_index` and `condition_class` stored."
    PRD: "the target resource's current state permits the
    requested transition; this covers wrong-from-state actions, terminal-state
    lockdown, and repeat runs such as a second close-of-business for one
    business date, else `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/inspection_cancel_after_report_rejected
    """
    facility = create_facility(name="IC Fac")
    inspection = setup_reported_inspection(facility["id"], load_bearing_rating=5,
                                           waterproofing_rating=5, surface_rating=5)
    res = api.cancel_inspection(inspection["id"], MS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    after = get_success_data(api.get_inspection(inspection["id"], FM))
    assert after["inspection_status"] == "REPORTED"


def test_structural_critical_blocks_posture_release(api):
    """PRD: "Release to `NORMAL` is guarded twice — no inspection of the
    facility may stand `REPORTED` with a `condition_class` of `CRITICAL` (else
    `ERR_STRUCTURAL_CRITICAL`), and no incident of severity `CRITICAL` may
    stand `OPEN` or `INVESTIGATING` (else `ERR_POSTURE_TRANSITION_BLOCKED`)."

    Design: Corner/errors/structural_critical_blocks_posture_release
    """
    facility, inspection = setup_critical_reported_facility(name="SC Fac")
    assert facility["posture"] == "RESTRICTED"
    res = api.transition_posture(facility["id"], "NORMAL", FM)
    validate_error(res, ApiErrorId.ERR_STRUCTURAL_CRITICAL)
    assert get_facility(facility["id"])["posture"] == "RESTRICTED"


class TestRepairFundRequiresReportedInspection:
    """Funding a project whose referenced inspection is not REPORTED fails;
    after the report, funding exactly the reserve balance succeeds."""

    def _build(self, api):
        facility, schedule, gate = setup_entry_ready_facility(name="Fund Fac")
        inspection = create_inspection(facility["id"], level_scope="L1")
        project = create_repair_project(facility["id"], title="L1 sealant",
                                        level_scope="L1", estimated_cost_cents=240,
                                        inspection_id=inspection["id"],
                                        closed_space_count=0)
        return facility, gate, inspection, project

    def test_fund_rejected_while_inspection_not_reported(self, api):
        """PRD: "A `FacilityManager` funds a `PROPOSED` project with an
        `amount_cents`; when the project references an inspection, that
        inspection must already stand `REPORTED` (else
        `ERR_INSPECTION_NOT_REPORTED`), and the amount must not exceed the
        facility's current `capital_reserve_cents` (else
        `ERR_INSUFFICIENT_RESERVE`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/repair_fund_requires_inspection_reported
        """
        facility, gate, inspection, project = self._build(api)
        res = api.fund_repair_project(project["id"], 100, FM)
        validate_error(res, ApiErrorId.ERR_INSPECTION_NOT_REPORTED)

    def test_fund_exactly_the_reserve_balance_succeeds(self, api):
        """PRD: "A funded project stands `FUNDED` with `funded_amount_cents`
        equal to the draw, and `capital_reserve_cents` falls by the same
        amount."
        PRD: "The levy is the positive part of that gross — a negative-gross
        day levies zero — multiplied by the facility's `levy_pct`, rounded
        half-up to whole cents, and `capital_reserve_cents` grows by exactly
        that levy."

        Design: Difficulty/cross_entity_state_dependency/repair_fund_requires_inspection_reported
        """
        facility, gate, inspection, project = self._build(api)
        validate_error(api.fund_repair_project(project["id"], 100, FM),
                       ApiErrorId.ERR_INSPECTION_NOT_REPORTED)

        # Build the reserve to exactly 240 via one CARD settle of 2400.
        session = enter_vehicle_at(facility["id"], gate, "XF-1", "2026-08-01T10:00:00Z")
        pay_session_card_at(session["id"], "2026-08-01T19:00:00Z")
        set_clock("2026-08-01T23:00:00Z")
        run_close_of_business(facility["id"])
        assert get_facility(facility["id"])["capital_reserve_cents"] == 240

        report_inspection(inspection["id"], 5, 5, 5, closed_space_count=0)
        funded = validate_success(api.fund_repair_project(project["id"], 240, FM), 200)
        assert funded["project_status"] == "FUNDED"
        assert funded["funded_amount_cents"] == 240
        assert get_facility(facility["id"])["capital_reserve_cents"] == 0, (
            "the == boundary is allowed: draw exactly the balance")


def test_insufficient_reserve_rejected(api):
    """PRD: "the amount must not exceed the facility's current
    `capital_reserve_cents` (else `ERR_INSUFFICIENT_RESERVE`, HTTP 422)."
    PRD: "The project stands `PROPOSED` with `funded_amount_cents` zero,
    `revision_count` zero, and both schedule stamps null."

    Design: Corner/validations/insufficient_reserve_rejected
    """
    facility = create_facility(name="IR Fac")
    project = create_repair_project(facility["id"], title="Paint",
                                    estimated_cost_cents=100)
    res = api.fund_repair_project(project["id"], 100, FM)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_RESERVE)
    after = get_success_data(api.get_repair_project(project["id"], FM))
    assert after["project_status"] == "PROPOSED"
    assert after["funded_amount_cents"] == 0


def test_reserve_refunded_on_funded_project_cancel(api):
    """PRD: "Cancellation from `PROPOSED`, `FUNDED`, or `DEFERRED` lands in
    the terminal `CANCELLED` — and when a `FUNDED` project is cancelled, its
    `funded_amount_cents` is returned to `capital_reserve_cents`, refunding
    the draw."

    Design: Corner/calculations/reserve_refunded_on_funded_project_cancel
    """
    facility, schedule, gate = setup_entry_ready_facility(name="RC Fac")
    session = enter_vehicle_at(facility["id"], gate, "RC-1", "2026-08-01T10:00:00Z")
    pay_session_card_at(session["id"], "2026-08-01T19:00:00Z")
    set_clock("2026-08-01T23:00:00Z")
    run_close_of_business(facility["id"])
    assert get_facility(facility["id"])["capital_reserve_cents"] == 240

    project = create_repair_project(facility["id"], title="Drain rebuild",
                                    level_scope="B1", estimated_cost_cents=240,
                                    closed_space_count=0)
    get_success_data(api.fund_repair_project(project["id"], 240, FM))
    cancelled = validate_success(api.cancel_repair_project(project["id"], FM), 200)
    assert cancelled["project_status"] == "CANCELLED"
    assert get_facility(facility["id"])["capital_reserve_cents"] == 240, (
        "draw fully refunded")


class TestRepairStartCloseoutConservesSpaces:
    """Start closes the project's spaces; close-out reopens exactly them."""

    def _build(self, api):
        facility, schedule, gate = setup_entry_ready_facility(
            name="Inv2 Fac", total_spaces=100)
        session = enter_vehicle_at(facility["id"], gate, "INV-2", "2026-08-01T10:00:00Z")
        pay_session_card_at(session["id"], "2026-08-01T19:00:00Z")
        set_clock("2026-08-01T23:00:00Z")
        run_close_of_business(facility["id"])
        project = create_repair_project(facility["id"], title="Deck sealing",
                                        level_scope="L3", estimated_cost_cents=240,
                                        closed_space_count=30)
        get_success_data(api.fund_repair_project(project["id"], 240, FM))
        get_success_data(api.schedule_repair_project(
            project["id"], "2026-08-05T06:00:00Z", "2026-08-07T18:00:00Z", MS))
        return facility, project

    def test_start_closes_project_spaces(self, api):
        """PRD: "Starting the work moves it to `IN_PROGRESS`, grows the
        facility's `closed_spaces` by the project's `closed_space_count`, and
        advances the facility's `version`"

        Design: Difficulty/compensating_invariant/repair_start_closeout_conserves_spaces
        """
        facility, project = self._build(api)
        started = validate_success(api.start_repair_project(project["id"], MS), 200)
        assert started["project_status"] == "IN_PROGRESS"
        after = get_facility(facility["id"])
        assert after["closed_spaces"] == 30
        assert after["total_spaces"] == 100, "total_spaces is never mutated"

    def test_closeout_reopens_exactly_the_same_spaces(self, api):
        """PRD: "closing out moves it to the terminal `CLOSED_OUT` and returns
        those spaces — `closed_spaces` falls by the same count and `version`
        advances again, the compensating pair to the start."

        Design: Difficulty/compensating_invariant/repair_start_closeout_conserves_spaces
        """
        facility, project = self._build(api)
        get_success_data(api.start_repair_project(project["id"], MS))
        closed_out = validate_success(api.close_out_repair_project(project["id"], MS), 200)
        assert closed_out["project_status"] == "CLOSED_OUT"
        after = get_facility(facility["id"])
        assert after["closed_spaces"] == 0, "invariant restored"
        assert after["total_spaces"] == 100
        assert after["capital_reserve_cents"] == 0, "240 levy - 240 draw"


class TestRepairDeferredRevisionLoop:
    """PROPOSED -> DEFERRED -> PROPOSED twice; revision_count accumulates."""

    def _build(self, api):
        facility = create_facility(name="Rep Fac")
        project = create_repair_project(facility["id"], title="L2 sealant",
                                        level_scope="L2", estimated_cost_cents=500000,
                                        closed_space_count=0)
        return project

    def test_revision_loop_returns_to_proposed_with_count_two(self, api):
        """PRD: "A `FacilityManager` may defer a `PROPOSED` project with a
        `reason`, moving it to `DEFERRED`; a `MaintenanceSupervisor` may later
        revise it back to `PROPOSED`, optionally restating
        `estimated_cost_cents`, and each revision increments `revision_count`."

        Design: Difficulty/non_linear_state_machine/repair_project_deferred_revision_loop
        """
        project = self._build(api)
        assert validate_success(api.defer_repair_project(
            project["id"], "budget timing", FM))["project_status"] == "DEFERRED"
        assert validate_success(api.revise_repair_project(
            project["id"], {"estimated_cost_cents": 480000}, MS))[
                "project_status"] == "PROPOSED"
        assert validate_success(api.defer_repair_project(
            project["id"], "weather window", FM))["project_status"] == "DEFERRED"
        final = validate_success(api.revise_repair_project(project["id"], {}, MS))
        assert final["project_status"] == "PROPOSED"
        assert final["revision_count"] == 2

    def test_revise_restates_estimated_cost(self, api):
        """PRD: "a `MaintenanceSupervisor` may later revise it back to
        `PROPOSED`, optionally restating `estimated_cost_cents`"

        Design: Difficulty/non_linear_state_machine/repair_project_deferred_revision_loop
        """
        project = self._build(api)
        get_success_data(api.defer_repair_project(project["id"], "budget timing", FM))
        revised = validate_success(api.revise_repair_project(
            project["id"], {"estimated_cost_cents": 480000}, MS), 200)
        assert revised["estimated_cost_cents"] == 480000


class TestCapitalReserveLevyOrder:
    """The levy reads settles-minus-refunds of the day; net is derived after
    and never fed back."""

    def _build(self, api):
        facility, schedule, gate = setup_entry_ready_facility(name="Levy Fac")
        shift = open_shift(facility["id"], opening_float_cents=10000)
        s1 = enter_vehicle_at(facility["id"], gate, "LV-1", "2026-08-01T10:00:00Z")
        s2 = enter_vehicle_at(facility["id"], gate, "LV-2", "2026-08-01T10:05:00Z")
        pay_session_card_at(s2["id"], "2026-08-01T12:35:00Z")  # 150min -> 3h -> 1100
        set_clock("2026-08-01T19:00:00Z")
        s1 = pay_session_cash(s1["id"], shift["id"])  # 9h -> capped 2400
        get_success_data(api.refund_session(
            s1["id"], {"amount_cents": 2400, "reason": "overcharge"}, AUD))
        set_clock("2026-08-01T23:00:00Z")
        return facility

    def test_levy_computed_on_gross_minus_same_day_refunds(self, api):
        """PRD: "The day's gross collection is the sum of `settled_fee_cents`
        over sessions settled on that business date under any tender, minus
        the sum of `refunded_cents` over refunds issued on that date. The levy
        is the positive part of that gross — a negative-gross day levies zero
        — multiplied by the facility's `levy_pct`, rounded half-up to whole
        cents, and `capital_reserve_cents` grows by exactly that levy."

        Design: Difficulty/combinatorial_formula/capital_reserve_levy_order_mode_c
        """
        facility = self._build(api)
        summary = run_close_of_business(facility["id"])
        assert summary["levy_credited_cents"] == 110, (
            "gross 2400 + 1100 - 2400 = 1100; levy round_half_up(1100 * 0.10)")

    def test_reserve_grows_by_levy_and_cumulative_tracks_net_collections(self, api):
        """PRD: "The day's net revenue is then reported as gross minus levy;
        this net figure is derived after the levy is fixed and is never fed
        back into the levy's own computation."
        PRD: "A recorded refund moves billing to the terminal `REFUNDED`,
        stores `refunded_cents` equal to the refunded amount, stamps
        `refunded_at`, and subtracts the amount from the facility's
        `cumulative_collected_cents` — the compensating pair to settlement."

        Design: Difficulty/combinatorial_formula/capital_reserve_levy_order_mode_c
        """
        facility = self._build(api)
        run_close_of_business(facility["id"])
        after = get_facility(facility["id"])
        assert after["capital_reserve_cents"] == 110
        assert after["cumulative_collected_cents"] == 1100, "2400 + 1100 - 2400"

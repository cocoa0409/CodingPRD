"""Training classes: attrition seat forecast, seat gate, OCC, and cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_training_class,
    confirm_enrollment,
    create_enrollment_payload,
    enroll,
    get_class,
    get_class_version,
    get_enrollment,
    list_ledger_entries,
    make_cleared_applicant,
    make_equipment,
    make_instructor,
    make_open_class,
    set_clock,
    setup_in_progress_enrollment,
    schedule_event,
    complete_event_at,
    get_applicant,
    get_success_data,
    start_enrollment,
    start_class,
    validate_error,
    validate_paginated,
    validate_success,
)

REC = TEST_USERS["recruiter_headers"]
TC = TEST_USERS["training_coordinator_headers"]
CS = TEST_USERS["crew_scheduler_headers"]


def _setup_three_active_mixed_class():
    """Class cap 10, attrition 0.25, IN_SESSION with e1/e2 IN_PROGRESS at
    GROUND_SCHOOL and e3 TENTATIVE."""
    eq = make_equipment(code="A320", sim_rate=45000, ioe_hours=10,
                        landings_required=3)
    ap1 = make_cleared_applicant("ann@x.com", "L001", full_name="Ann Ace",
                                 hours=3200, age=34)
    ap2 = make_cleared_applicant("bob@x.com", "L002", full_name="Bob Bay",
                                 hours=2900, age=41)
    ap3 = make_cleared_applicant("cid@x.com", "L003", full_name="Cid Cox",
                                 hours=2100, age=29)
    cls = make_open_class(eq["id"], class_date="2026-08-10T00:00:00Z",
                          seat_capacity=10, attrition=0.25)
    en1 = enroll(cls["id"], ap1["id"])
    confirm_enrollment(en1["id"])
    en2 = enroll(cls["id"], ap2["id"])
    confirm_enrollment(en2["id"])
    en3 = enroll(cls["id"], ap3["id"])
    set_clock("2026-08-10T09:00:00Z")
    start_class(cls["id"])
    start_enrollment(en1["id"])
    start_enrollment(en2["id"])
    return {"equipment": eq, "applicants": [ap1, ap2, ap3],
            "training_class": get_class(cls["id"]),
            "enrollments": [en1, en2, en3]}


class TestSeatForecastVariants:
    def test_projections_aggregate_and_walk_diverge(self, api):
        """PRD §3.2: "Variant A, exposed as `projected_completions_aggregate`,
        is `active_enrollment_count` multiplied by one minus the attrition
        rate, rounded down to a whole seat. Variant B, exposed as
        `projected_completions_walk`, walks the active enrollments oldest first
        by `created_at`, breaking ties by the applicant's `email` in ascending
        alphabetical order, and sums a survival probability per enrollment: one
        minus the attrition rate for `TENTATIVE` and `CONFIRMED` enrollments,
        0.80 for `REMEDIATION` enrollments, and for `IN_PROGRESS` enrollments a
        lookup by current phase — 0.90 for `GROUND_SCHOOL`, 0.95 for
        `SIMULATOR`, 0.97 for `CHECKRIDE`, 0.98 for `IOE` — with the resulting
        sum rounded half-up to a whole number."

        Design: Difficulty/dual_variant_calc/seat_forecast_aggregate_vs_walk_diverge
        """
        ctx = _setup_three_active_mixed_class()
        data = validate_success(api.get_training_class(
            ctx["training_class"]["id"], TC))
        assert_training_class(data)
        assert data["active_enrollment_count"] == 3
        # floor(3 * (1 - 0.25)) = floor(2.25) = 2
        assert data["projected_completions_aggregate"] == 2
        # round_half_up(0.90 + 0.90 + 0.75) = round_half_up(2.55) = 3
        assert data["projected_completions_walk"] == 3
        assert data["projected_completions_walk"] != data[
            "projected_completions_aggregate"], (
            "The two variants legitimately disagree on identical data")

    def test_max_seats_sellable_uses_current_attrition_rate(self, api):
        """PRD §3.2: "Second, `max_seats_sellable` — the overbooking ceiling —
        is computed from the current `base_attrition_rate` as `seat_capacity`
        multiplied by one plus the rate, rounded down to a whole seat."
        PRD §3.2: "`active_enrollment_count` counts enrollments in `TENTATIVE`,
        `CONFIRMED`, `IN_PROGRESS`, or `REMEDIATION`"

        Design: Difficulty/dual_variant_calc/seat_forecast_aggregate_vs_walk_diverge
        """
        ctx = _setup_three_active_mixed_class()
        data = validate_success(api.get_training_class(
            ctx["training_class"]["id"], TC))
        # floor(10 * 1.25) = 12
        assert data["max_seats_sellable"] == 12
        assert data["active_enrollment_count"] == 3
        assert data["over_committed"] is False


class TestSeatGatePinnedEvaluationOrder:
    def _setup_full_class_then_attrition_patch(self):
        """Class cap 2 attrition 0.50 OPEN with exactly 3 TENTATIVE
        enrollments (ceiling floor(2*1.5)=3, full but not over-committed);
        a fourth cleared applicant waits; then attrition PATCHed to 0.10."""
        eq = make_equipment(code="B777", sim_rate=50000, ioe_hours=12,
                            landings_required=3)
        applicants = [
            make_cleared_applicant(f"p{i:02d}@x.com", f"L10{i}",
                                   full_name=f"P{i:02d}", age=30)
            for i in range(1, 5)
        ]
        cls = make_open_class(eq["id"], class_date="2026-08-10T00:00:00Z",
                              seat_capacity=2, attrition=0.50)
        for ap in applicants[:3]:
            enroll(cls["id"], ap["id"])
        pre = get_class(cls["id"])
        return eq, applicants, cls, pre

    def test_attrition_patch_recomputes_ceiling_and_over_committed(self, api):
        """PRD §3.2: "Fourth and last, `over_committed` is set true exactly
        when `active_enrollment_count` exceeds `max_seats_sellable`, and these
        values gate future enrollment requests."
        PRD §3.2: "The edit request must carry
        `expected_training_class_version` per §2.6, and the forecast is
        recomputed with the new values, so an edit can push a class into
        `over_committed`"

        Design: Difficulty/combinatorial_formula/seat_gate_pinned_evaluation_order_after_attrition_patch
        """
        eq, applicants, cls, pre = self._setup_full_class_then_attrition_patch()
        assert pre["max_seats_sellable"] == 3, "floor(2 * 1.5) = 3"
        assert pre["active_enrollment_count"] == 3
        assert pre["over_committed"] is False

        patched = validate_success(api.patch_training_class(
            cls["id"], {"base_attrition_rate": 0.10,
                        "expected_training_class_version": pre["version"]}, TC))
        assert patched["max_seats_sellable"] == 2, "floor(2 * 1.1) = 2"
        assert patched["over_committed"] is True, (
            "active 3 exceeds the new ceiling 2")

    def test_over_committed_class_rejects_next_enrollment(self, api):
        """PRD §3.3: "then the seat gate rejects with `ERR_CLASS_FULL` (409)
        when the class is `over_committed` or `active_enrollment_count` has
        reached `max_seats_sellable`, both evaluated on pre-request state"
        PRD §3.2: "Fourth and last, `over_committed` is set true exactly when
        `active_enrollment_count` exceeds `max_seats_sellable`, and these
        values gate future enrollment requests."

        Design: Difficulty/combinatorial_formula/seat_gate_pinned_evaluation_order_after_attrition_patch
        """
        eq, applicants, cls, pre = self._setup_full_class_then_attrition_patch()
        patched = validate_success(api.patch_training_class(
            cls["id"], {"base_attrition_rate": 0.10,
                        "expected_training_class_version": pre["version"]}, TC))
        # The fourth applicant has no enrollment in the class, so only the
        # seat gate can fire.
        resp = api.create_enrollment(
            create_enrollment_payload(applicants[3]["id"], cls["id"],
                                      patched["version"]), TC)
        validate_error(resp, ApiErrorId.ERR_CLASS_FULL)


class TestSeatGateBoundary:
    def _setup_class_at_exact_ceiling(self):
        """Class cap 2 attrition 0.50 (ceiling exactly 3); three cleared
        applicants enrolled; a fourth cleared applicant ready."""
        eq = make_equipment(code="BCS3", sim_rate=45000, ioe_hours=10,
                            landings_required=3)
        applicants = [
            make_cleared_applicant(f"q{i:02d}@x.com", f"L20{i}",
                                   full_name=f"Q{i:02d}", age=30)
            for i in range(1, 5)
        ]
        cls = make_open_class(eq["id"], class_date="2026-08-10T00:00:00Z",
                              seat_capacity=2, attrition=0.50)
        enrollments = [enroll(cls["id"], ap["id"]) for ap in applicants[:3]]
        return eq, applicants, cls, enrollments

    def test_third_enrollment_at_ceiling_minus_one_succeeds(self, api):
        """PRD §3.3: "then the seat gate rejects with `ERR_CLASS_FULL` (409)
        when the class is `over_committed` or `active_enrollment_count` has
        reached `max_seats_sellable`, both evaluated on pre-request state"
        PRD §3.2: "Second, `max_seats_sellable` — the overbooking ceiling — is
        computed from the current `base_attrition_rate` as `seat_capacity`
        multiplied by one plus the rate, rounded down to a whole seat."

        Design: Difficulty/boundary_precision_check/seat_gate_at_exact_sellable_ceiling
        """
        _eq, _aps, cls, enrollments = self._setup_class_at_exact_ceiling()
        third = get_enrollment(enrollments[2]["id"])
        assert third["status"] == "TENTATIVE", (
            "active 2 < 3 before the write, so the third enrollment is allowed")
        data = validate_success(api.get_training_class(cls["id"], TC))
        assert data["max_seats_sellable"] == 3, (
            "floor(2 * 1.5) must not lose the exact-integer seat")
        assert data["active_enrollment_count"] == 3

    def test_fourth_enrollment_at_exact_ceiling_rejected(self, api):
        """PRD §3.3: "then the seat gate rejects with `ERR_CLASS_FULL` (409)
        when the class is `over_committed` or `active_enrollment_count` has
        reached `max_seats_sellable`, both evaluated on pre-request state"

        Design: Difficulty/boundary_precision_check/seat_gate_at_exact_sellable_ceiling
        """
        _eq, applicants, cls, _ens = self._setup_class_at_exact_ceiling()
        version = get_class_version(cls["id"])
        resp = api.create_enrollment(
            create_enrollment_payload(applicants[3]["id"], cls["id"], version),
            TC)
        validate_error(resp, ApiErrorId.ERR_CLASS_FULL)
        data = validate_success(api.get_training_class(cls["id"], TC))
        assert data["active_enrollment_count"] == 3, "No seat materialized"


class TestConfirmWithdrawSeatInvariant:
    def _setup_baseline_confirmed_plus_tentative(self):
        eq = make_equipment(code="A343", sim_rate=45000, ioe_hours=10,
                            landings_required=3)
        ap1 = make_cleared_applicant("kat@x.com", "L340", full_name="Kat Lee",
                                     hours=2200, age=32)
        ap2 = make_cleared_applicant("lou@x.com", "L341", full_name="Lou May",
                                     hours=2400, age=38)
        cls = make_open_class(eq["id"], class_date="2026-08-10T00:00:00Z",
                              seat_capacity=10, attrition=0.20)
        en1 = enroll(cls["id"], ap1["id"])
        confirm_enrollment(en1["id"])
        en2 = enroll(cls["id"], ap2["id"])
        return cls, en1, en2

    def test_confirm_then_withdraw_returns_counters_to_baseline(self, api):
        """PRD §3.2: "`active_enrollment_count` counts enrollments in
        `TENTATIVE`, `CONFIRMED`, `IN_PROGRESS`, or `REMEDIATION`, while
        `confirmed_count` counts enrollments in `CONFIRMED`, `IN_PROGRESS`,
        `REMEDIATION`, or `COMPLETED`."

        Design: Difficulty/compensating_invariant/confirm_withdraw_pair_conserves_class_seat_counters
        """
        cls, _en1, en2 = self._setup_baseline_confirmed_plus_tentative()
        mid = get_class(cls["id"])
        assert mid["confirmed_count"] == 1
        assert mid["active_enrollment_count"] == 2, (
            "The second TENTATIVE enrollment joins the active set")

        confirm_enrollment(en2["id"])
        get_success_data(api.withdraw_enrollment(en2["id"], TC))

        post = get_class(cls["id"])
        assert post["confirmed_count"] == 1, (
            "WITHDRAWN is excluded from the confirmed set — back to baseline")
        assert post["active_enrollment_count"] == 1, (
            "WITHDRAWN is excluded from the active set — back to baseline")

    def test_counter_identity_holds_at_each_step(self, api):
        """PRD §3.2: "`active_enrollment_count` counts enrollments in
        `TENTATIVE`, `CONFIRMED`, `IN_PROGRESS`, or `REMEDIATION`, while
        `confirmed_count` counts enrollments in `CONFIRMED`, `IN_PROGRESS`,
        `REMEDIATION`, or `COMPLETED`."

        Design: Difficulty/compensating_invariant/confirm_withdraw_pair_conserves_class_seat_counters
        """
        cls, en1, en2 = self._setup_baseline_confirmed_plus_tentative()
        base = get_class(cls["id"])
        # en1 CONFIRMED + en2 TENTATIVE: both count toward active; only en1
        # counts toward confirmed.
        assert base["confirmed_count"] == 1
        assert base["active_enrollment_count"] == 2

        confirm_enrollment(en2["id"])
        both_confirmed = get_class(cls["id"])
        assert both_confirmed["confirmed_count"] == 2
        assert both_confirmed["active_enrollment_count"] == 2

        get_success_data(api.withdraw_enrollment(en2["id"], TC))
        assert get_enrollment(en2["id"])["status"] == "WITHDRAWN"
        post = get_class(cls["id"])
        # The confirm+withdraw pair conserves en1's contribution: WITHDRAWN
        # drops en2 out of both sets, leaving exactly en1's 1/1.
        assert post["confirmed_count"] == 1
        assert post["active_enrollment_count"] == 1


class TestClassCancelCascade:
    def _setup_in_session_class_with_billed_event(self):
        ctx = setup_in_progress_enrollment(
            eq_kwargs={"code": "A333", "sim_rate": 45000, "ioe_hours": 10},
            ap_kwargs={"email": "ivy@x.com", "license_number": "L050",
                       "full_name": "Ivy Idd", "hours": 2700, "age": 37})
        ins = make_instructor("Lee Gnd", "GROUND", daily_max=6)
        ctx["instructor"] = ins
        ev = schedule_event(ctx["enrollment"]["id"], ins["id"],
                            "GROUND_SCHOOL", "SESSION",
                            "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        ctx["event"] = complete_event_at(ev["id"], 92, "2026-08-10T10:00:00Z")
        return ctx

    def test_class_cancel_cascades_enrollment_withdrawal(self, api):
        """PRD §3.2: "Cancellation moves a class from `SCHEDULED`, `OPEN`, or
        `IN_SESSION` to `CANCELLED`."
        PRD §3.2: "Link 1: every enrollment of the class in `TENTATIVE`,
        `CONFIRMED`, `IN_PROGRESS`, or `REMEDIATION` moves to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/class_cancel_cascade_depth3
        """
        ctx = self._setup_in_session_class_with_billed_event()
        cancelled = validate_success(
            api.cancel_training_class(ctx["training_class"]["id"], TC))
        assert cancelled["status"] == "CANCELLED"
        enrollment = get_enrollment(ctx["enrollment"]["id"])
        assert enrollment["status"] == "WITHDRAWN", (
            "Link 1: the in-progress enrollment is withdrawn by the cascade")

    def test_class_cancel_books_reversal_and_nets_balance_to_zero(self, api):
        """PRD §3.2: "Link 2, caused by link 1: for each withdrawn enrollment,
        every charge ledger entry not already reversed is mirrored by a
        `REVERSAL` entry whose `amount_cents` is the exact negation of the
        charge. Link 3, caused by link 2: each affected applicant's
        `ledger_balance_cents` is recomputed as the signed sum of all of their
        ledger entries."

        Design: Difficulty/transitive_cascade/class_cancel_cascade_depth3
        """
        ctx = self._setup_in_session_class_with_billed_event()
        pre = get_applicant(ctx["applicant"]["id"])
        assert pre["ledger_balance_cents"] == 150000, (
            "The completed ground-school session billed 150,000 cents")

        validate_success(api.cancel_training_class(ctx["training_class"]["id"], TC))

        reversals = list_ledger_entries(
            CS, enrollment_id=ctx["enrollment"]["id"], entry_type="REVERSAL")
        assert len(reversals) == 1, "Exactly one REVERSAL mirrors the charge"
        assert reversals[0]["amount_cents"] == -150000
        post = get_applicant(ctx["applicant"]["id"])
        assert post["ledger_balance_cents"] == 0, (
            "150000 charge + (-150000) reversal nets to zero")


class TestClassBasics:
    def test_equipment_landings_required_defaults_to_3(self, api):
        """PRD §3.2: "and `landings_required_90d`, the recency requirement used
        by the currency check, which defaults to 3 when omitted."

        Design: Corner/entities/equipment_landings_required_defaults_to_3
        """
        resp = api.create_equipment(
            {"code": "B735", "name": "Boeing 737-500",
             "simulator_cost_per_hour_cents": 40000, "ioe_hours_required": 8},
            TC)
        equipment = validate_success(resp, 201)
        assert equipment["landings_required_90d"] == 3, (
            "The recency requirement defaults to 3 when omitted")

    def test_enrollment_into_non_open_class_returns_class_not_open(self, api):
        """PRD §3.3: "The gates run in a fixed order: existence of both
        references first; then the class must be `OPEN`, otherwise
        `ERR_CLASS_NOT_OPEN` (409)"

        Design: Corner/validations/enrollment_into_non_open_class_returns_class_not_open
        """
        eq = make_equipment(code="DHC8", sim_rate=38000, ioe_hours=8)
        ap = make_cleared_applicant("ear@x.com", "L434", full_name="Ear Ly")
        cls = get_success_data(api.create_training_class(
            {"equipment_id": eq["id"], "class_date": "2026-08-10T00:00:00Z",
             "seat_capacity": 10, "base_attrition_rate": 0.20}, TC))
        assert cls["status"] == "SCHEDULED", "The class was never opened"
        resp = api.create_enrollment(
            create_enrollment_payload(ap["id"], cls["id"], cls["version"]), TC)
        validate_error(resp, ApiErrorId.ERR_CLASS_NOT_OPEN)

    def test_filtered_list_enrollments_by_training_class(self, api):
        """PRD §3.3: "Enrollments list with the filters `applicant_id`,
        `training_class_id`, and `status`."

        Design: Corner/endpoints/filtered_list_enrollments_by_training_class
        """
        eq = make_equipment(code="FK01", sim_rate=38000, ioe_hours=8)
        ap = make_cleared_applicant("fk@x.com", "L452", full_name="Fk Kid")
        cls_a = make_open_class(eq["id"], class_date="2026-08-10T00:00:00Z")
        en = enroll(cls_a["id"], ap["id"])
        cls_b = get_success_data(api.create_training_class(
            {"equipment_id": eq["id"], "class_date": "2026-09-10T00:00:00Z",
             "seat_capacity": 10, "base_attrition_rate": 0.20}, TC))

        data_a, meta_a = validate_paginated(
            api.list_enrollments(TC, params={"training_class_id": cls_a["id"]}))
        assert meta_a["total_count"] == 1
        assert [row["id"] for row in data_a] == [en["id"]]

        _data_b, meta_b = validate_paginated(
            api.list_enrollments(TC, params={"training_class_id": cls_b["id"]}))
        assert meta_b["total_count"] == 0


class TestOptimisticConcurrency:
    def test_stale_version_on_enrollment_create(self, api):
        """PRD §2.6: "A client that creates two enrollments back to back must
        therefore re-read the class between calls — a second create carrying
        the previously observed version is stale even though the class is still
        `OPEN` and the seat gate would otherwise pass."
        PRD §2.6: "If that value does not equal the class's current `version`,
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_enrollment_create
        """
        eq = make_equipment(code="FK07", sim_rate=38000, ioe_hours=8)
        ap1 = make_cleared_applicant("occ1@x.com", "L470", full_name="Occ One")
        ap2 = make_cleared_applicant("occ2@x.com", "L471", full_name="Occ Two")
        cls = make_open_class(eq["id"], class_date="2026-08-10T00:00:00Z")
        stale_version = get_class_version(cls["id"])
        validate_success(api.create_enrollment(
            create_enrollment_payload(ap1["id"], cls["id"], stale_version), TC),
            201)

        resp = api.create_enrollment(
            create_enrollment_payload(ap2["id"], cls["id"], stale_version), TC)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        _data, meta = validate_paginated(
            api.list_enrollments(TC, params={"training_class_id": cls["id"]}))
        assert meta["total_count"] == 1, "The stale create persisted nothing"

    def test_stale_version_on_attrition_patch(self, api):
        """PRD §2.6: "Both requests must carry the non-optional field
        `expected_training_class_version`, holding the class `version` the
        client last observed. If that value does not equal the class's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_attrition_patch
        """
        eq = make_equipment(code="FK08", sim_rate=38000, ioe_hours=8)
        cls = make_open_class(eq["id"], class_date="2026-08-10T00:00:00Z")
        version = get_class_version(cls["id"])
        patched = validate_success(api.patch_training_class(
            cls["id"], {"base_attrition_rate": 0.30,
                        "expected_training_class_version": version}, TC))
        assert patched["version"] > version, "The first edit advanced version"

        resp = api.patch_training_class(
            cls["id"], {"base_attrition_rate": 0.40,
                        "expected_training_class_version": version}, TC)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        current = get_class(cls["id"])
        assert current["base_attrition_rate"] == 0.30, (
            "The stale replay changed nothing")

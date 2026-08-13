"""Service-recovery ledger (self-approval, per-case ceiling, compensating
revocation) and patient-relations rounding (pairwise overlap, unit capacity,
staff availability, window sanity)."""
from test_helpers import (
    ApiErrorId,
    create_case,
    create_recovery_action_payload,
    create_rounding_session_payload,
    create_staff,
    create_unit,
    get_case,
    get_success_data,
    issue_recovery,
    make_advocate_headers,
    make_director_headers,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


class TestRecoveryCaseCap:
    def _setup_case_with_advocate(self, api):
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED South", "EMERGENCY")
        adv = create_staff("Ally Advocate", ["ADVOCATE"])
        case = create_case(unit["id"], patient_ref="P-8003",
                           received_at="2026-08-03T09:00:00.000Z", channel="IN_PERSON",
                           description="Parking fee frustration",
                           grievance_category="BILLING")
        return case, adv

    def test_cumulative_cap_exact_equality_allowed(self, api):
        """PRD §3.8: "At creation, the projected total — the sum of
        `value_cents` across the case's `ISSUED` actions plus the new action's
        value — is rejected with `ERR_RECOVERY_CASE_CAP_EXCEEDED` (HTTP 402)
        only when it strictly exceeds the ceiling; a projection landing exactly
        on 50,000 cents is allowed."

        Design: Difficulty/boundary_precision_check/recovery_cap_exact_equality_allowed_plus_one_rejected
        """
        case, adv = self._setup_case_with_advocate(api)
        kinds = ["PARKING_COMP", "MEAL_VOUCHER", "MEAL_VOUCHER", "GOODWILL_GESTURE"]
        for i, kind in enumerate(kinds, start=1):
            issue_recovery(case["id"], adv["id"], action_type=kind,
                           value_cents=10000,
                           justification=f"Gesture number {i} for the delay")
        fifth = issue_recovery(case["id"], adv["id"], action_type="GOODWILL_GESTURE",
                               value_cents=10000,
                               justification="Fifth gesture reaches the cap exactly")
        assert fifth["status"] == "ISSUED", (
            "projected 50000 == the ceiling is allowed (strict > rejects only)")
        assert get_case(case["id"])["outstanding_recovery_cents"] == 50000

    def test_one_cent_over_cap_rejected(self, api):
        """PRD §3.8: "At creation, the projected total — the sum of
        `value_cents` across the case's `ISSUED` actions plus the new action's
        value — is rejected with `ERR_RECOVERY_CASE_CAP_EXCEEDED` (HTTP 402)
        only when it strictly exceeds the ceiling; a projection landing exactly
        on 50,000 cents is allowed."

        Design: Difficulty/boundary_precision_check/recovery_cap_exact_equality_allowed_plus_one_rejected
        """
        case, adv = self._setup_case_with_advocate(api)
        for i in range(5):
            issue_recovery(case["id"], adv["id"], action_type="MEAL_VOUCHER",
                           value_cents=10000,
                           justification=f"Gesture number {i} for the delay")
        assert get_case(case["id"])["outstanding_recovery_cents"] == 50000

        resp = api.create_recovery_action(
            case["id"],
            create_recovery_action_payload(
                action_type="MEAL_VOUCHER", value_cents=1,
                justification="One cent over the case cap"),
            make_advocate_headers(adv["id"]))
        validate_error(resp, ApiErrorId.ERR_RECOVERY_CASE_CAP_EXCEEDED)


class TestRecoveryIssueRevokeInvariant:
    def _setup(self, api):
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED West", "EMERGENCY")
        adv = create_staff("Ally Advocate", ["ADVOCATE"])
        director = create_staff("Dana Director", ["DIRECTOR"])
        case = create_case(unit["id"], patient_ref="P-9201",
                           received_at="2026-08-03T09:00:00.000Z", channel="IN_PERSON",
                           description="Cafeteria overcharge",
                           grievance_category="BILLING")
        return case, adv, director

    def test_issue_revoke_pair_nets_to_zero(self, api):
        """PRD §3.8: "an action whose value does not exceed the issuer's
        `recovery_issuance_limit_cents` is born `ISSUED` and immediately raises
        the case's `outstanding_recovery_cents` by its value; an action above
        the ceiling is born `PENDING_APPROVAL` and touches no ledger until
        approved." and "Revocation is the compensating act on an `ISSUED`
        action: the director supplies a `revoke_reason`, the action moves to
        `REVOKED`, and the case's outstanding recovery falls by the action's
        value."

        Design: Difficulty/compensating_invariant/recovery_issue_revoke_conserves_outstanding_cents
        """
        case, adv, director = self._setup(api)
        a1 = issue_recovery(case["id"], adv["id"], action_type="MEAL_VOUCHER",
                            value_cents=8000,
                            justification="Meal voucher for overcharge one")
        issue_recovery(case["id"], adv["id"], action_type="PARKING_COMP",
                       value_cents=7000,
                       justification="Parking comp for long stay two")
        a3 = issue_recovery(case["id"], adv["id"], action_type="BILL_ADJUSTMENT",
                            value_cents=15000,
                            justification="Bill adjustment above personal limit")
        assert a1["status"] == "ISSUED"
        assert a3["status"] == "PENDING_APPROVAL", (
            "15000 exceeds the issuer's 10000-cent self-approval ceiling")

        revoked = validate_success(api.revoke_recovery_action(
            a1["id"], {"revoke_reason": "Voucher returned unused"},
            make_director_headers(director["id"])))
        assert revoked["status"] == "REVOKED"

        outstanding = get_case(case["id"])["outstanding_recovery_cents"]
        assert outstanding == 7000, (
            "ISSUE(8000) + ISSUE(7000) + REVOKE(8000) nets to exactly 7000; "
            "the PENDING_APPROVAL 15000 never entered the ledger")

    def test_pending_action_enters_ledger_only_on_approval(self, api):
        """PRD §3.8: "an action above the ceiling is born `PENDING_APPROVAL`
        and touches no ledger until approved." and "Approval stamps
        `approved_by_id` and moves the action to `ISSUED`, adding its value to
        the case's outstanding recovery."

        Design: Difficulty/compensating_invariant/recovery_issue_revoke_conserves_outstanding_cents
        """
        case, adv, director = self._setup(api)
        issue_recovery(case["id"], adv["id"], action_type="MEAL_VOUCHER",
                       value_cents=8000,
                       justification="Meal voucher for overcharge one")
        issue_recovery(case["id"], adv["id"], action_type="PARKING_COMP",
                       value_cents=7000,
                       justification="Parking comp for long stay two")
        a3 = issue_recovery(case["id"], adv["id"], action_type="BILL_ADJUSTMENT",
                            value_cents=15000,
                            justification="Bill adjustment above personal limit")
        assert get_case(case["id"])["outstanding_recovery_cents"] == 15000, (
            "only the two ISSUED actions count while the third is pending")

        approved = validate_success(api.approve_recovery_action(
            a3["id"], make_director_headers(director["id"])))
        assert approved["status"] == "ISSUED"
        assert approved["approved_by_id"] == director["id"]
        assert get_case(case["id"])["outstanding_recovery_cents"] == 30000, (
            "approval adds the action's value to the outstanding ledger")

    def test_sod_recovery_self_approve(self, api):
        """PRD §2.10: "The recovery approver must differ from the issuing
        advocate (`issued_by_id`). Each violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/sod_recovery_self_approve
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED", "EMERGENCY")
        hybrid = create_staff("Ally Hybrid", ["ADVOCATE", "DIRECTOR"])
        case = create_case(unit["id"], patient_ref="P-0304",
                           received_at="2026-08-03T09:00:00.000Z",
                           description="Billing issue", grievance_category="BILLING")
        action = issue_recovery(case["id"], hybrid["id"],
                                action_type="BILL_ADJUSTMENT", value_cents=15000,
                                justification="Adjustment above personal limit")
        assert action["status"] == "PENDING_APPROVAL"
        resp = api.approve_recovery_action(
            action["id"], make_director_headers(hybrid["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestRoundingOverlap:
    def _setup_advocate_with_session(self, api):
        set_clock("2026-08-03T08:00:00.000Z")
        unit = create_unit("Med-Surg 5", "INPATIENT")
        adv = create_staff("Ally Advocate", ["ADVOCATE"])
        headers = make_advocate_headers(adv["id"])
        first = validate_success(api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T10:00:00.000Z",
                end_at="2026-08-03T12:00:00.000Z"),
            headers), expected_status=201)
        return unit, adv, headers, first

    def test_half_open_adjacency_allowed_then_overlap_rejected(self, api):
        """PRD §3.8: "Pairwise, the new session must not overlap any of the
        same advocate's other `SCHEDULED` sessions: two windows overlap when
        the new one begins strictly before the existing one ends and the
        existing one begins strictly before the new one ends, so back-to-back
        adjacency is permitted; a conflict is rejected with
        `ERR_ROUNDING_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rounding_advocate_half_open_adjacency_rules
        """
        unit, _adv, headers, _first = self._setup_advocate_with_session(api)
        adjacent = api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T12:00:00.000Z",
                end_at="2026-08-03T14:00:00.000Z"),
            headers)
        assert validate_success(adjacent, expected_status=201)["status"] == "SCHEDULED", (
            "adjacency at exactly 12:00 is allowed — windows are half-open")

        overlapping = api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T13:00:00.000Z",
                end_at="2026-08-03T15:00:00.000Z"),
            headers)
        validate_error(overlapping, ApiErrorId.ERR_ROUNDING_OVERLAP)

    def test_second_adjacency_also_allowed(self, api):
        """PRD §3.8: "the session's `advocate_id` is the caller's own staff
        identity" and "two windows overlap when the new one begins strictly
        before the existing one ends and the existing one begins strictly
        before the new one ends, so back-to-back adjacency is permitted"

        Design: Difficulty/resource_temporal_overlap/rounding_advocate_half_open_adjacency_rules
        """
        unit, _adv, headers, _first = self._setup_advocate_with_session(api)
        validate_success(api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T12:00:00.000Z",
                end_at="2026-08-03T14:00:00.000Z"),
            headers), expected_status=201)
        third = api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T14:00:00.000Z",
                end_at="2026-08-03T15:00:00.000Z"),
            headers)
        assert validate_success(third, expected_status=201)["status"] == "SCHEDULED", (
            "starting exactly at the previous window's end occupies no shared instant")


class TestUnitRoundingCapacity:
    def _setup(self, api):
        set_clock("2026-08-03T08:00:00.000Z")
        unit = create_unit("PICU", "ICU", max_concurrent_roundings=1)
        adv_a = create_staff("Ally A", ["ADVOCATE"])
        adv_b = create_staff("Ally B", ["ADVOCATE"])
        validate_success(api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T10:00:00.000Z",
                end_at="2026-08-03T12:00:00.000Z"),
            make_advocate_headers(adv_a["id"])), expected_status=201)
        return unit, adv_a, adv_b

    def test_capacity_rejects_second_overlapping_advocate(self, api):
        """PRD §3.8: "Aggregately, the unit enforces occupancy: when the number
        of `SCHEDULED` sessions on the unit overlapping the requested window
        already equals the unit's `max_concurrent_roundings`, the request is
        rejected with `ERR_UNIT_ROUNDING_CAPACITY`; one fewer than the maximum
        is accepted."

        Design: Difficulty/resource_temporal_overlap/unit_rounding_capacity_aggregate_semantics
        """
        unit, _adv_a, adv_b = self._setup(api)
        resp = api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T11:00:00.000Z",
                end_at="2026-08-03T12:00:00.000Z"),
            make_advocate_headers(adv_b["id"]))
        validate_error(resp, ApiErrorId.ERR_UNIT_ROUNDING_CAPACITY)

    def test_adjacent_second_advocate_session_allowed(self, api):
        """PRD §3.8: "Aggregately, the unit enforces occupancy: when the number
        of `SCHEDULED` sessions on the unit overlapping the requested window
        already equals the unit's `max_concurrent_roundings`, the request is
        rejected with `ERR_UNIT_ROUNDING_CAPACITY`; one fewer than the maximum
        is accepted."

        Design: Difficulty/resource_temporal_overlap/unit_rounding_capacity_aggregate_semantics
        """
        unit, _adv_a, adv_b = self._setup(api)
        resp = api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T12:00:00.000Z",
                end_at="2026-08-03T13:00:00.000Z"),
            make_advocate_headers(adv_b["id"]))
        session = validate_success(resp, expected_status=201)
        assert session["status"] == "SCHEDULED", (
            "the adjacent window has zero overlapping occupants on the unit")


class TestStaffAvailabilityGate:
    def test_on_leave_advocate_overlap_reports_availability_not_overlap(self, api):
        """PRD §2.6: "When several violations are detectable on a single
        request, a fixed precedence ladder decides which rejection the caller
        sees; the first failing rung wins." and "then staff availability
        (`ERR_ADVOCATE_ON_LEAVE`); then the open-escalation approval gate"
        precedes rung 10's "rounding overlap and unit capacity". PRD §3.8: "An
        advocate flagged `on_leave` may not schedule at all
        (`ERR_ADVOCATE_ON_LEAVE`, HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/on_leave_advocate_overlap_safety_beats_constraint
        """
        set_clock("2026-08-03T08:00:00.000Z")
        unit = create_unit("Med-Surg 2", "INPATIENT")
        adv = create_staff("Ally Advocate", ["ADVOCATE"])
        headers = make_advocate_headers(adv["id"])
        validate_success(api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T10:00:00.000Z",
                end_at="2026-08-03T12:00:00.000Z"),
            headers), expected_status=201)
        get_success_data(api.patch_staff(adv["id"], {"on_leave": True}, ADMIN))

        resp = api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T11:00:00.000Z",
                end_at="2026-08-03T13:00:00.000Z"),
            headers)
        validate_error(resp, ApiErrorId.ERR_ADVOCATE_ON_LEAVE)
        assert resp.json()["data"]["error_id"] != "ERR_ROUNDING_OVERLAP", (
            "the availability gate (safety rung) fires before the occupancy "
            "constraint although the window also overlaps")

    def test_overlapping_session_without_leave_reports_overlap(self, api):
        """PRD §3.8: "An advocate flagged `on_leave` may not schedule at all
        (`ERR_ADVOCATE_ON_LEAVE`, HTTP 403)." and "a conflict is rejected with
        `ERR_ROUNDING_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/on_leave_advocate_overlap_safety_beats_constraint
        """
        set_clock("2026-08-03T08:00:00.000Z")
        unit = create_unit("Med-Surg 2", "INPATIENT")
        adv = create_staff("Ally Advocate", ["ADVOCATE"])
        headers = make_advocate_headers(adv["id"])
        validate_success(api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T10:00:00.000Z",
                end_at="2026-08-03T12:00:00.000Z"),
            headers), expected_status=201)

        resp = api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T11:00:00.000Z",
                end_at="2026-08-03T13:00:00.000Z"),
            headers)
        # Control: without the leave flag the same window violates the pairwise
        # overlap rule, proving the priority fixture genuinely carried both
        # violations.
        validate_error(resp, ApiErrorId.ERR_ROUNDING_OVERLAP)

    def test_rounding_window_inverted_rejected(self, api):
        """PRD §3.8: "The window must be sane — end strictly after start, and
        start not before the current clock — or it is rejected with
        `ERR_ROUNDING_WINDOW_INVALID`."

        Design: Corner/validations/rounding_window_inverted_rejected
        """
        set_clock("2026-08-03T08:00:00.000Z")
        unit = create_unit("ED", "EMERGENCY")
        adv = create_staff("Ally Advocate", ["ADVOCATE"])
        resp = api.create_rounding_session(
            create_rounding_session_payload(
                unit_id=unit["id"], start_at="2026-08-03T12:00:00.000Z",
                end_at="2026-08-03T10:00:00.000Z"),
            make_advocate_headers(adv["id"]))
        validate_error(resp, ApiErrorId.ERR_ROUNDING_WINDOW_INVALID)

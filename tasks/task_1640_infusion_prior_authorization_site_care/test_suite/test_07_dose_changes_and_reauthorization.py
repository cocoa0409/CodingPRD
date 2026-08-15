"""Dose changes: the delta computation, the 20.00 re-authorization
threshold, the parent-approval gate, the supersede cascade, and the
clearance hold/recompute cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    book_appointment,
    create_chair,
    create_dose_change,
    create_dose_change_payload,
    decide_dose_change,
    get_clearance,
    get_request,
    setup_approved_request,
    setup_approved_with_clearance,
    setup_approved_with_cleared_clearance_and_chair,
    setup_denied_request,
    setup_superseded_request,
    validate_error,
    validate_success,
    AUTH_COORDINATOR_HEADERS,
    FINANCE_SPECIALIST_HEADERS,
    SCHEDULER_HEADERS,
)


class TestDoseDeltaThreshold:
    def test_exactly_twenty_percent_triggers_reauth(self, api):
        """PRD §3.8: "The `reauth_required` flag is true when `delta_pct`
        reaches the re-authorization threshold of 20.00 — exactly 20.00
        triggers re-authorization, while 19.99 does not."

        Design: Difficulty/boundary_precision_check/dose_delta_threshold_twenty_exact
        """
        ws = setup_approved_request(drug_code="J9051", member_id="M701")
        assert ws["auth"]["approved_dose_mg"] == 500

        exact = create_dose_change(ws["auth"]["id"], 600)
        assert exact["delta_pct"] == pytest.approx(20.00)
        assert exact["reauth_required"] is True, (
            "20.00 reaches the threshold and triggers re-authorization")

        below = create_dose_change(ws["auth"]["id"], 599)
        assert below["delta_pct"] == pytest.approx(19.80)
        assert below["reauth_required"] is False

    def test_downward_delta_uses_absolute_difference(self, api):
        """PRD §3.8: "The `delta_pct` is the absolute difference between
        `new_dose_mg` and the request's `approved_dose_mg`, divided by
        `approved_dose_mg`, multiplied by one hundred to express it as a
        percentage, and rounded half-up to two decimal places."
        PRD §3.8: "The `reauth_required` flag is true when `delta_pct`
        reaches the re-authorization threshold of 20.00 — exactly 20.00
        triggers re-authorization, while 19.99 does not."

        Design: Difficulty/boundary_precision_check/dose_delta_threshold_twenty_exact
        """
        ws = setup_approved_request(drug_code="J9054", member_id="M704")

        down_exact = create_dose_change(ws["auth"]["id"], 400)
        assert down_exact["delta_pct"] == pytest.approx(20.00), (
            "abs(400 - 500) / 500 * 100 = 20.00")
        assert down_exact["reauth_required"] is True

        down_below = create_dose_change(ws["auth"]["id"], 401)
        assert down_below["delta_pct"] == pytest.approx(19.80)
        assert down_below["reauth_required"] is False

    def test_delta_rounded_half_up_to_two_decimals(self, api):
        """PRD §3.8: "The `delta_pct` is the absolute difference between
        `new_dose_mg` and the request's `approved_dose_mg`, divided by
        `approved_dose_mg`, multiplied by one hundred to express it as a
        percentage, and rounded half-up to two decimal places."
        PRD §2.6: "The `delta_pct` computed for a dose change is rounded
        half-up to two decimal places."

        Design: Corner/calculations/dose_delta_rounding_precision
        """
        ws = setup_approved_request(
            drug_code="J9120", member_id="M1120",
            request_overrides={"requested_dose_mg": 333})
        assert ws["auth"]["approved_dose_mg"] == 333

        change = create_dose_change(ws["auth"]["id"], 350)
        # 17 / 333 * 100 = 5.105105... -> 5.11 half-up to two decimals.
        assert change["delta_pct"] == pytest.approx(5.11)
        assert change["reauth_required"] is False


class TestDoseChangeGate:
    def test_dose_change_on_denied_request_rejected(self, api):
        """PRD §3.8: "Mid-course dose changes are filed by an
        `AuthCoordinator` against an `APPROVED` request — any other parent
        status is rejected with `ERR_AUTH_NOT_APPROVED`"

        Design: Difficulty/cross_entity_state_dependency/dose_change_create_requires_auth_approved
        """
        ws = setup_denied_request(drug_code="J9062", member_id="M802")
        assert ws["auth"]["status"] == "DENIED"

        resp = api.create_dose_change_request(
            ws["auth"]["id"], create_dose_change_payload(600),
            AUTH_COORDINATOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_APPROVED)

        changes = validate_success(api.list_dose_change_requests(
            ws["auth"]["id"], AUTH_COORDINATOR_HEADERS))
        assert changes == [], "No dose-change request is created"

    def test_dose_change_on_superseded_request_rejected(self, api):
        """PRD §3.8: "Mid-course dose changes are filed by an
        `AuthCoordinator` against an `APPROVED` request — any other parent
        status is rejected with `ERR_AUTH_NOT_APPROVED`"

        Design: Difficulty/cross_entity_state_dependency/dose_change_create_requires_auth_approved
        """
        ws = setup_superseded_request(drug_code="J9063", member_id="M803",
                                      new_dose_mg=600)
        assert ws["auth"]["status"] == "SUPERSEDED"

        resp = api.create_dose_change_request(
            ws["auth"]["id"], create_dose_change_payload(550),
            AUTH_COORDINATOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_APPROVED)


class TestSupersedeCascade:
    def test_approval_with_reauth_supersedes_and_cancels(self, api):
        """PRD §3.8: "When `reauth_required` is true, the parent authorization
        request cascades `APPROVED` → `SUPERSEDED`; every appointment of that
        request still in `SCHEDULED` or `CONFIRMED` status whose
        `scheduled_start` lies after the current logical clock moves to
        `CANCELLED`, releasing each chair's occupation; and the request's
        clearance remains `ON_HOLD`."
        PRD §3.8: "Creation has one immediate cascade: when `reauth_required`
        is true and the parent request has a clearance in `ESTIMATED` status
        (at most one can exist, per the duplicate-open-clearance rule), that
        clearance moves to `ON_HOLD` with a version increment, freezing
        financial clearance until the dose question resolves."

        Design: Difficulty/transitive_cascade/dose_change_approval_supersede_cascade
        """
        ws = setup_approved_with_clearance(
            drug_code="J9031", member_id="M501",
            line_items=(("drug", 100000, 100000),))
        chair = create_chair(site_type="OFFICE", label="CH-1",
                             turnover_buffer_minutes=15)
        appt = book_appointment(ws["auth"]["id"], chair["id"],
                                "2026-08-20T10:00:00Z", "2026-08-20T11:00:00Z")
        approved_version = ws["auth"]["version"]

        change = create_dose_change(ws["auth"]["id"], 600)
        assert change["reauth_required"] is True
        assert change["status"] == "PENDING"
        held = get_clearance(ws["clearance"]["id"])
        assert held["status"] == "ON_HOLD", (
            "Creation of a reauth-required dose change holds the clearance")

        decided = decide_dose_change(change["id"], "APPROVED")
        assert decided["status"] == "APPROVED"

        auth = get_request(ws["auth"]["id"])
        assert auth["status"] == "SUPERSEDED", "Hop 1: decision -> SUPERSEDED"
        assert auth["version"] == approved_version + 1

        appointments = validate_success(
            api.list_appointments(ws["auth"]["id"], SCHEDULER_HEADERS))
        by_id = {a["id"]: a for a in appointments}
        assert by_id[appt["id"]]["status"] == "CANCELLED", (
            "Hop 2: the future SCHEDULED appointment is cancelled")

        clearance = get_clearance(ws["clearance"]["id"])
        assert clearance["status"] == "ON_HOLD", (
            "The clearance remains ON_HOLD; the approval does not re-estimate")

    def test_rejection_releases_clearance_for_recompute(self, api):
        """PRD §3.8: "Rejection leaves the parent request untouched in
        `APPROVED`, and the `ON_HOLD` clearance (if any) becomes eligible for
        the recompute described in §3.6."
        PRD §3.6: "An `ON_HOLD` clearance returns to `ESTIMATED` through a
        recompute, which a `FinanceSpecialist` may invoke once the parent
        request is `APPROVED` again — reachable after the dose change is
        rejected — and attempting it while the parent is anything else is
        rejected with `ERR_AUTH_NOT_APPROVED`."

        Design: Difficulty/transitive_cascade/dose_change_approval_supersede_cascade
        """
        ws = setup_approved_with_clearance(
            drug_code="J9034", member_id="M504",
            line_items=(("drug", 100000, 100000),))
        estimate_before = ws["clearance"][
            "estimated_patient_responsibility_cents"]

        change = create_dose_change(ws["auth"]["id"], 600)
        assert change["reauth_required"] is True
        assert get_clearance(ws["clearance"]["id"])["status"] == "ON_HOLD"

        decided = decide_dose_change(change["id"], "REJECTED")
        assert decided["status"] == "REJECTED"

        auth = get_request(ws["auth"]["id"])
        assert auth["status"] == "APPROVED", (
            "Rejection leaves the parent request untouched")

        recomputed = validate_success(api.recompute_financial_clearance(
            ws["clearance"]["id"], FINANCE_SPECIALIST_HEADERS))
        assert recomputed["status"] == "ESTIMATED"
        assert (recomputed["estimated_patient_responsibility_cents"]
                == estimate_before), (
            "The recompute rebuilds the same estimate over the same lines")


class TestConditionalCascade:
    def test_supersede_cancels_only_future_appointments(self, api):
        """PRD §3.8: "When `reauth_required` is true, the parent authorization
        request cascades `APPROVED` → `SUPERSEDED`; every appointment of that
        request still in `SCHEDULED` or `CONFIRMED` status whose
        `scheduled_start` lies after the current logical clock moves to
        `CANCELLED`, releasing each chair's occupation; and the request's
        clearance remains `ON_HOLD`."

        Design: Corner/cross_cutting_layers/conditional_cascade_only_future_appointments
        """
        ws = setup_approved_with_cleared_clearance_and_chair(
            drug_code="J9182", member_id="M1182")
        chair_id = ws["chair"]["id"]

        past = book_appointment(ws["auth"]["id"], chair_id,
                                "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z")
        validate_success(api.confirm_appointment(past["id"], SCHEDULER_HEADERS))
        advance_clock("2026-08-06T00:00:00Z")
        future = book_appointment(ws["auth"]["id"], chair_id,
                                  "2026-08-20T10:00:00Z",
                                  "2026-08-20T11:00:00Z")

        change = create_dose_change(ws["auth"]["id"], 600)
        decide_dose_change(change["id"], "APPROVED")

        assert get_request(ws["auth"]["id"])["status"] == "SUPERSEDED"
        appointments = validate_success(
            api.list_chair_appointments(chair_id, SCHEDULER_HEADERS))
        by_id = {a["id"]: a for a in appointments}
        assert by_id[past["id"]]["status"] == "COMPLETED", (
            "The past, already-COMPLETED appointment is untouched")
        assert by_id[future["id"]]["status"] == "CANCELLED", (
            "The future SCHEDULED appointment (start after the clock) is "
            "cancelled")

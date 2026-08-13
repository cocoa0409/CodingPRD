"""Direct assignment lifecycle: proposal, response, confirmation, cancel."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    accept_assignment,
    api_client,
    assert_shift_assignment,
    complete_assignment,
    confirm_assignment,
    create_nurse,
    decline_assignment,
    get_shift,
    get_week_ledger,
    make_staff_nurse_headers,
    propose_assignment,
    setup_unit_with_shift,
    validate_error,
    validate_success,
    walk_to_accepted,
    walk_to_completed,
    walk_to_confirmed,
)


def _unit_shift_nurse(name, charge_qualified=False):
    """ICU unit, matrix, DAY shift 2026-08-10 (required 2), one CORE nurse."""
    sc = setup_unit_with_shift(name=name, census=(4, 0, 0, 0))
    nurse = create_nurse(full_name=f"{name} Nurse", employment_type="CORE",
                         competencies=["ICU"], base_hourly_rate_cents=5000,
                         home_unit_id=sc["unit"]["id"],
                         charge_qualified=charge_qualified)
    sc["nurse"] = nurse
    return sc


class TestAssignmentCreation:

    def test_assignment_initial_state_proposed(self):
        """PRD section 3.4: "A successfully created assignment enters in
        `PROPOSED` status with `source` set to `DIRECT`, `premium_multiplier`
        at 1.0, and `flat_bonus_cents` at 0."
        PRD section 2.9: "Both are twelve hours, so every assignment carries a
        `scheduled_hours` of 12.0 regardless of code."

        Design: Corner/state_machines/assignment_initial_state_proposed
        """
        sc = _unit_shift_nurse("Init ICU")
        data = propose_assignment(sc["shift"]["id"], sc["nurse"]["id"],
                                  sc["charge_headers"])
        assert_shift_assignment(data)
        assert data["status"] == "PROPOSED"
        assert data["source"] == "DIRECT"
        assert data["scheduled_hours"] == 12.0


class TestResponseLoop:

    def test_accept_twice_rejected(self):
        """PRD section 3.4: "calling either on an assignment in any other
        non-terminal state fails with `ERR_ASSIGNMENT_NOT_PROPOSED`".

        Design: Corner/state_machines/accept_twice_rejected
        """
        sc = _unit_shift_nurse("Idem ICU")
        asg = walk_to_accepted(sc["shift"]["id"], sc["nurse"],
                               sc["charge_headers"])
        assert asg["status"] == "ACCEPTED"
        resp = api_client.accept_assignment(
            asg["id"], make_staff_nurse_headers(sc["nurse"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED)

    def test_decline_releases_projected_hours(self):
        """PRD section 3.4: "Declining moves it to `DECLINED`, releases the
        twelve projected hours".
        PRD section 2.9: "Creating an assignment and then declining or
        cancelling that same assignment leaves `projected_hours` unchanged —
        the twelve hours enter on creation and leave on release."

        Design: Corner/state_machines/decline_releases_projected_hours
        """
        sc = _unit_shift_nurse("Decline ICU")
        asg = propose_assignment(sc["shift"]["id"], sc["nurse"]["id"],
                                 sc["charge_headers"])
        mid = get_week_ledger(sc["nurse"]["id"], "2026-08-10")
        assert mid["projected_hours"] == 12.0
        data = decline_assignment(asg["id"], sc["nurse"]["id"])
        assert data["status"] == "DECLINED"
        ledger = get_week_ledger(sc["nurse"]["id"], "2026-08-10")
        assert ledger["projected_hours"] == 0.0, \
            f"decline must release the 12.0 projected hours, got {ledger['projected_hours']}"


class TestConfirmationGates:

    def test_confirm_from_proposed_rejected(self):
        """PRD section 3.4: "it requires the assignment to be `ACCEPTED` (else
        `ERR_ASSIGNMENT_NOT_ACCEPTED`) and the shift to be unlocked (`OPEN` or
        `STAFFED`, else `ERR_SHIFT_NOT_OPEN`)."

        Design: Corner/state_machines/confirm_from_proposed_rejected
        """
        sc = _unit_shift_nurse("Skip ICU")
        asg = propose_assignment(sc["shift"]["id"], sc["nurse"]["id"],
                                 sc["charge_headers"])
        resp = api_client.confirm_assignment(asg["id"], sc["charge_headers"])
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED)

    def test_complete_from_accepted_rejected(self):
        """PRD section 3.8: "a `ChargeNurse` completes a `CONFIRMED` assignment
        — any other state fails with `ERR_ASSIGNMENT_NOT_CONFIRMED`".

        Design: Corner/state_machines/complete_from_accepted_rejected
        """
        sc = _unit_shift_nurse("Early ICU")
        asg = walk_to_accepted(sc["shift"]["id"], sc["nurse"],
                               sc["charge_headers"])
        resp = api_client.complete_assignment(
            asg["id"], {"actual_hours_worked": 12.0, "missed_breaks": 0},
            sc["charge_headers"])
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_CONFIRMED)

    def test_cancel_completed_rejected(self):
        """PRD section 3.4: "targeting a `COMPLETED`, `DECLINED`, or
        `CANCELLED` assignment fails with `ERR_ASSIGNMENT_TERMINAL`".

        Design: Corner/state_machines/cancel_completed_rejected
        """
        sc = _unit_shift_nurse("Done ICU")
        asg = walk_to_completed(sc["shift"]["id"], sc["nurse"],
                                sc["charge_headers"],
                                actual_hours_worked=12.0, missed_breaks=0)
        assert asg["status"] == "COMPLETED"
        resp = api_client.cancel_assignment(asg["id"], sc["charge_headers"])
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_TERMINAL)


class TestConfirmRevokeCycle:
    """Difficulty instance: assignment_confirm_revoke_cycle."""

    def test_confirm_revoke_reconfirm_status_cycle(self):
        """PRD section 3.4: "A confirmation may also be walked back: revoking a
        confirmation returns the assignment from `CONFIRMED` to `ACCEPTED` —
        requiring it to be `CONFIRMED` (else `ERR_ASSIGNMENT_NOT_CONFIRMED`)
        and the shift unlocked — and since `ACCEPTED` still counts toward
        staffing, the posture re-evaluation runs again on the unchanged
        numerator."

        Design: Difficulty/non_linear_state_machine/assignment_confirm_revoke_cycle
        """
        sc = _unit_shift_nurse("Cycle ICU", charge_qualified=True)
        asg = propose_assignment(sc["shift"]["id"], sc["nurse"]["id"],
                                 sc["charge_headers"], is_charge=True)
        accept_assignment(asg["id"], sc["nurse"]["id"])

        confirmed = confirm_assignment(asg["id"], sc["charge_headers"])
        assert confirmed["status"] == "CONFIRMED"

        revoked = validate_success(
            api_client.revoke_confirmation(asg["id"], sc["charge_headers"]),
            expected_status=200)
        assert revoked["status"] == "ACCEPTED", \
            f"revoke must return CONFIRMED -> ACCEPTED, got {revoked['status']}"

        reconfirmed = confirm_assignment(asg["id"], sc["charge_headers"])
        assert reconfirmed["status"] == "CONFIRMED", \
            "the cycle must close: re-confirm after revoke succeeds"

    def test_counted_assignments_stable_across_cycle(self):
        """PRD section 3.3: "`counted_assignments` tracks how many assignments
        sit in `ACCEPTED` or `CONFIRMED`".
        PRD section 3.4: "since `ACCEPTED` still counts toward staffing, the
        posture re-evaluation runs again on the unchanged numerator."

        Design: Difficulty/non_linear_state_machine/assignment_confirm_revoke_cycle
        """
        sc = _unit_shift_nurse("Cycle ICU 2", charge_qualified=True)
        asg = propose_assignment(sc["shift"]["id"], sc["nurse"]["id"],
                                 sc["charge_headers"], is_charge=True)
        accept_assignment(asg["id"], sc["nurse"]["id"])
        confirm_assignment(asg["id"], sc["charge_headers"])
        validate_success(
            api_client.revoke_confirmation(asg["id"], sc["charge_headers"]),
            expected_status=200)
        confirm_assignment(asg["id"], sc["charge_headers"])

        shift = get_shift(sc["shift"]["id"])
        assert shift["counted_assignments"] == 1, \
            f"ACCEPTED and CONFIRMED both count; the cycle must not double-count, got {shift['counted_assignments']}"
        assert shift["charge_covered"] is True

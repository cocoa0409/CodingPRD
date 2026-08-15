"""Assignment transfer-cycle tests: ACTIVE -> PENDING_TRANSFER -> ACTIVE on
cancel; OCC stale-version rejection; census reconciliation through the cycle.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    setup_assigned_patient,
)

ADMIN = TEST_USERS["group_admin_headers"]


def _two_hospit_setup(api):
    """H1 with ACTIVE shift holds P1; H2 exists as a transfer target."""
    h1 = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
    h2 = create_hospitalist("H Two", "ICU", max_census_cap=16)
    s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
    set_clock("2026-05-01T09:00:00Z")
    p1 = create_patient(mrn="M501", acuity="MEDIUM", admit_source="ED",
                        stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
    resp = api.create_admission({"patient_id": p1["id"]}, ADMIN)
    a1 = get_success_data(resp)
    accepted = get_success_data(api.accept_admission(
        a1["id"], make_hospitalist_headers(a1["offered_to_hospitalist_id"])
    ))
    asg_id = accepted["assignment_id"]
    return h1, h2, s1, p1, asg_id


class TestAssignmentTransferCycle:
    """Difficulty instance: assignment_transfer_cycle."""

    def test_transfer_then_cancel_restores_active_and_advances_version(self, api):
        """PRD §3.4: "Success moves the assignment `ACTIVE` → `PENDING_TRANSFER`,
        records the target, and increments the assignment's `version`."
        PRD §3.4: "cancelling requires the assignment to be `PENDING_TRANSFER`
        (else `ERR_ASSIGNMENT_INVALID_STATE`), moves `PENDING_TRANSFER` →
        `ACTIVE` again, clears `transfer_target_hospitalist_id`, increments
        the assignment's `version`, and leaves both hospitalists' census
        fields untouched".

        Design: Difficulty/non_linear_state_machine/assignment_transfer_cycle
        """
        h1, h2, s1, p1, asg_id = _two_hospit_setup(api)
        asg_v1 = get_success_data(api.get_assignment(asg_id, ADMIN))
        assert asg_v1["status"] == "ACTIVE"
        assert asg_v1["version"] == 1

        # Initiate transfer
        t = get_success_data(api.transfer_assignment(
            asg_id,
            {"target_hospitalist_id": h2["id"], "expected_assignment_version": asg_v1["version"]},
            make_hospitalist_headers(h1["id"]),
        ))
        assert t["status"] == "PENDING_TRANSFER"
        assert t["transfer_target_hospitalist_id"] == h2["id"]
        assert t["version"] == 2

        # Cancel transfer — cycle back
        c = get_success_data(api.cancel_transfer(asg_id, make_hospitalist_headers(h1["id"])))
        assert c["status"] == "ACTIVE"
        assert c["transfer_target_hospitalist_id"] is None
        assert c["version"] == 3

    def test_census_unchanged_through_cycle_and_continuity_flag_false(self, api):
        """PRD §3.4: "cancelling ... leaves both hospitalists' census fields
        untouched".
        PRD §3.3: "its `continuity_flag` set from the same 30-day continuity
        predicate the selector uses" — a fresh admission has no CLOSED pairing,
        so continuity_flag is false.

        Design: Difficulty/non_linear_state_machine/assignment_transfer_cycle
        """
        h1, h2, s1, p1, asg_id = _two_hospit_setup(api)
        asg_v1 = get_success_data(api.get_assignment(asg_id, ADMIN))
        assert asg_v1["continuity_flag"] is False

        api.transfer_assignment(
            asg_id,
            {"target_hospitalist_id": h2["id"], "expected_assignment_version": asg_v1["version"]},
            make_hospitalist_headers(h1["id"]),
        )
        api.cancel_transfer(asg_id, make_hospitalist_headers(h1["id"]))

        h1_now = get_success_data(api.get_hospitalist(h1["id"], ADMIN))
        h2_now = get_success_data(api.get_hospitalist(h2["id"], ADMIN))
        assert h1_now["current_census"] == 1
        assert h2_now["current_census"] == 0


class TestOccTransferStaleReturns412:
    """Corner instance: occ_transfer_stale_returns_412."""

    def test_full_cycle_then_replay_stale_version_rejected(self, api):
        """PRD §2.6: "initiating an assignment transfer requires
        `expected_assignment_version` holding the assignment's `version` as
        last observed. In both cases the field is non-optional, and a value
        that no longer matches the entity's current `version` is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.6: "an assignment may complete a full initiate-then-cancel
        cycle between a client's read and its transfer initiation, returning
        the status to `ACTIVE` while the version has moved; only the version
        check catches it."

        Design: Corner/validations/occ_transfer_stale_returns_412
        """
        h1, h2, s1, p1, asg_id = _two_hospit_setup(api)
        asg_v1 = get_success_data(api.get_assignment(asg_id, ADMIN))
        captured_version = asg_v1["version"]
        assert captured_version == 1

        # Complete a full initiate-then-cancel cycle
        api.transfer_assignment(
            asg_id,
            {"target_hospitalist_id": h2["id"], "expected_assignment_version": captured_version},
            make_hospitalist_headers(h1["id"]),
        )
        api.cancel_transfer(asg_id, make_hospitalist_headers(h1["id"]))

        # Replay with the stale captured version — status ACTIVE passes the state
        # check, but the version check rejects.
        resp = api.transfer_assignment(
            asg_id,
            {"target_hospitalist_id": h2["id"], "expected_assignment_version": captured_version},
            make_hospitalist_headers(h1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # Assignment remains ACTIVE at version 3
        asg_now = get_success_data(api.get_assignment(asg_id, ADMIN))
        assert asg_now["status"] == "ACTIVE"
        assert asg_now["version"] == 3

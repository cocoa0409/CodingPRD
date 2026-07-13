"""Assigning inspectors: assignment-count conservation, schedule buffer, and
the state-over-safety validation-priority conflict."""
import test_helpers as th
from test_helpers import ApiErrorId


# --------------------------------------------------------------------------
# Difficulty: compensating_invariant / assignment_count_conserved_on_cancel
# --------------------------------------------------------------------------
def test_cancel_from_assigned_restores_assignment_count(api):
    """PRD §3.4: "On a successful assignment the assigned_inspector_id is set on
    the inspection and the inspector's active_assignment_count is incremented by 1."
    PRD §3.4: "When the inspection being cancelled was ASSIGNED, cancellation
    additionally decrements the assigned inspector's active_assignment_count by 1
    — compensating the increment taken at assignment".

    Design: Difficulty/compensating_invariant/assignment_count_conserved_on_cancel
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.schedule_inspection(api, device["id"], itype="ANNUAL", start=1, end=2)
    th.assign_inspection(api, ins["id"], inspector["id"])
    after_assign = th.validate_success(api.get_inspector(inspector["id"], th.REG))
    assert after_assign["active_assignment_count"] == 1
    th.validate_success(api.cancel_inspection(ins["id"], th.REG))
    after_cancel = th.validate_success(api.get_inspector(inspector["id"], th.REG))
    assert after_cancel["active_assignment_count"] == 0, "assign+cancel must restore count to 0"


def test_cancel_from_assigned_clears_inspector_and_terminates(api):
    """PRD §3.4: "When the inspection being cancelled was `ASSIGNED`, cancellation
    additionally decrements the assigned inspector's `active_assignment_count` by 1
    — compensating the increment taken at assignment — and clears the
    `assigned_inspector_id` back to null."

    Design: Difficulty/compensating_invariant/assignment_count_conserved_on_cancel
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.schedule_inspection(api, device["id"], itype="ANNUAL", start=1, end=2)
    th.assign_inspection(api, ins["id"], inspector["id"])
    resp = api.cancel_inspection(ins["id"], th.REG)
    cancelled = th.validate_success(resp)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["assigned_inspector_id"] is None


# --------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / inspector_halfopen_buffer_conflict
# --------------------------------------------------------------------------
def test_buffered_window_conflict_rejected(api):
    """PRD §3.4: "a candidate assignment conflicts with an existing `ASSIGNED` or
    `IN_PROGRESS` inspection of the same inspector exactly when the candidate's
    `scheduled_start_period` is strictly less than that existing inspection's
    `scheduled_end_period` plus 1, and that existing inspection's
    `scheduled_start_period` is strictly less than the candidate's
    `scheduled_end_period` plus 1 (both comparisons strict)."

    Design: Difficulty/resource_temporal_overlap/inspector_halfopen_buffer_conflict
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    dev_a = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR", location_description="P-A")
    dev_b = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR", location_description="P-B")
    ins1 = th.schedule_inspection(api, dev_a["id"], itype="ANNUAL", start=10, end=12)
    th.assign_inspection(api, ins1["id"], inspector["id"])
    ins2 = th.schedule_inspection(api, dev_b["id"], itype="ANNUAL", start=12, end=14)
    resp = api.assign_inspection(ins2["id"], th.assign_payload(inspector["id"]), th.REG)
    th.validate_error(resp, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT.value)


def test_window_just_past_buffer_assigns_cleanly(api):
    """PRD §3.4: the conflict predicate is strict — "the candidate's
    `scheduled_start_period` is strictly less than that existing inspection's
    `scheduled_end_period` plus 1"; a candidate starting at 13 against an existing
    [10,12) is 13 < 13 == false, so there is no conflict.

    Design: Difficulty/resource_temporal_overlap/inspector_halfopen_buffer_conflict
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    dev_a = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR", location_description="P-A")
    dev_b = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR", location_description="P-B")
    ins1 = th.schedule_inspection(api, dev_a["id"], itype="ANNUAL", start=10, end=12)
    th.assign_inspection(api, ins1["id"], inspector["id"])
    ins2 = th.schedule_inspection(api, dev_b["id"], itype="ANNUAL", start=13, end=15)
    resp = api.assign_inspection(ins2["id"], th.assign_payload(inspector["id"]), th.REG)
    assigned = th.validate_success(resp)
    assert assigned["status"] == "ASSIGNED"


# --------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / assign_state_over_safety
# --------------------------------------------------------------------------
def test_assign_state_check_precedes_certification_check(api):
    """PRD §2.9: "(7) the target resource being in a state that permits the
    requested transition (ERR_*_NOT_<STATE>); and (8) onward, the operation-specific
    business rules ... Later checks never mask an earlier one: if a higher-priority
    condition fails, its error is returned before any lower-priority check runs."
    PRD §3.4: "the inspection must currently be `SCHEDULED`, or the request is
    rejected with `ERR_INSPECTION_NOT_SCHEDULED`."

    Design: Difficulty/priority_pair_validation_conflict/assign_state_over_safety
    """
    owner = th.new_owner(api)
    insp_good = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    insp_bad = th.new_inspector(api, categories=["ESCALATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.schedule_inspection(api, device["id"], itype="ANNUAL", start=1, end=2)
    th.assign_inspection(api, ins["id"], insp_good["id"])
    resp = api.assign_inspection(ins["id"], th.assign_payload(insp_bad["id"]), th.REG)
    th.validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_SCHEDULED.value)


def test_assign_conflict_does_not_surface_certification_error(api):
    """PRD §2.9: "Later checks never mask an earlier one: if a higher-priority
    condition fails, its error is returned before any lower-priority check runs."
    PRD §3.4: the certification check (ERR_INSPECTOR_NOT_CERTIFIED) is a lower
    priority business-safety rule than the SCHEDULED-state check, so it must not
    be the returned error when both fail.

    Design: Difficulty/priority_pair_validation_conflict/assign_state_over_safety
    """
    owner = th.new_owner(api)
    insp_good = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    insp_bad = th.new_inspector(api, categories=["ESCALATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.schedule_inspection(api, device["id"], itype="ANNUAL", start=1, end=2)
    th.assign_inspection(api, ins["id"], insp_good["id"])
    resp = api.assign_inspection(ins["id"], th.assign_payload(insp_bad["id"]), th.REG)
    assert resp.status_code == 409
    error_id = resp.json()["data"]["error_id"]
    assert error_id != ApiErrorId.ERR_INSPECTOR_NOT_CERTIFIED.value, \
        "state error must pre-empt the lower-priority certification error"

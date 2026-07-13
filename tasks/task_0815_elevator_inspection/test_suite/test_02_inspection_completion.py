"""Completing inspections: the PASS / FAIL / CONDITIONAL branch and its guards."""
import test_helpers as th
from test_helpers import ApiErrorId


# --------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / inspection_branching_fail_outcome
# --------------------------------------------------------------------------
def test_fail_branch_sets_failed_and_leaves_due_period_null(api):
    """PRD §3.5: "A result of FAIL drives the inspection to the terminal FAILED state."
    PRD §3.5: "On passing, the device's next_inspection_due_period is set to the
    inspection's performed_period plus the recurrence interval for the device's
    category" — the FAIL branch performs no such update, and a non-CRITICAL
    deficiency triggers no cascade, so the device remains REGISTERED.

    Design: Difficulty/non_linear_state_machine/inspection_branching_fail_outcome
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.inspection_in_progress(api, device["id"], inspector["id"], itype="ANNUAL", start=1, end=2)
    resp = api.complete_inspection(
        ins["id"], th.complete_payload("FAIL", [th.deficiency_entry("MAJ-1", "MAJOR", "governor slip")]),
        th.make_licensed_inspector_headers(inspector["id"]),
    )
    completed = th.validate_success(resp)
    assert completed["status"] == "FAILED"
    dev = th.get_device(api, device["id"])
    assert dev["next_inspection_due_period"] is None, "FAIL must not set next_inspection_due_period"
    assert dev["status"] == "REGISTERED", "MAJOR (non-CRITICAL) failure triggers no OOS cascade"


def test_fail_branch_opens_single_deficiency(api):
    """PRD §3.5: "The `deficiencies` list must be non-empty; an empty list is
    rejected with `ERR_FAIL_WITHOUT_DEFICIENCIES`. One `Deficiency`, in `OPEN`
    status, is created for each entry."

    Design: Difficulty/non_linear_state_machine/inspection_branching_fail_outcome
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.inspection_in_progress(api, device["id"], inspector["id"], itype="ANNUAL", start=1, end=2)
    th.complete_inspection(api, ins["id"], inspector["id"], "FAIL",
                           [th.deficiency_entry("MAJ-1", "MAJOR", "governor slip")])
    defs = th.deficiencies_for_inspection(api, ins["id"])
    assert len(defs) == 1, f"expected exactly 1 deficiency, got {len(defs)}"
    assert defs[0]["status"] == "OPEN"


# --------------------------------------------------------------------------
# Corner instances
# --------------------------------------------------------------------------
def test_pass_sets_next_inspection_due_period(api):
    """PRD §3.5: "On passing, the device's next_inspection_due_period is set to the
    inspection's performed_period plus the recurrence interval for the device's
    category, where the interval in months is 12 for a PASSENGER_ELEVATOR".

    Design: Corner/calculations/pass_sets_next_inspection_due_period
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.inspection_in_progress(api, device["id"], inspector["id"], itype="ANNUAL", start=1, end=2)
    resp = api.complete_inspection(ins["id"], th.complete_payload("PASS"),
                                   th.make_licensed_inspector_headers(inspector["id"]))
    completed = th.validate_success(resp)
    assert completed["status"] == "PASSED"
    dev = th.get_device(api, device["id"])
    assert dev["next_inspection_due_period"] == 12


def test_complete_on_passed_returns_not_in_progress(api):
    """PRD §3.5: "The acting inspector must again be the `assigned_inspector_id`
    (`ERR_NOT_RESOURCE_OWNER`) and the inspection must be `IN_PROGRESS`
    (`ERR_INSPECTION_NOT_IN_PROGRESS`)."

    Design: Corner/state_machines/complete_on_passed_returns_not_in_progress
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.inspection_in_progress(api, device["id"], inspector["id"], itype="ANNUAL", start=1, end=2)
    th.complete_inspection(api, ins["id"], inspector["id"], "PASS")
    resp = api.complete_inspection(ins["id"], th.complete_payload("PASS"),
                                   th.make_licensed_inspector_headers(inspector["id"]))
    th.validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_IN_PROGRESS.value)


def test_complete_pass_with_deficiencies_returns_error(api):
    """PRD §3.5: "A passing inspection must carry an empty `deficiencies` list; a
    non-empty list is rejected with `ERR_PASS_WITH_DEFICIENCIES`."

    Design: Corner/validations/complete_pass_with_deficiencies_returns_error
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.inspection_in_progress(api, device["id"], inspector["id"], itype="ANNUAL", start=1, end=2)
    resp = api.complete_inspection(
        ins["id"], th.complete_payload("PASS", [th.deficiency_entry("X", "MINOR", "x")]),
        th.make_licensed_inspector_headers(inspector["id"]),
    )
    th.validate_error(resp, ApiErrorId.ERR_PASS_WITH_DEFICIENCIES.value)


def test_complete_fail_without_deficiencies_returns_error(api):
    """PRD §3.5: "The `deficiencies` list must be non-empty; an empty list is
    rejected with `ERR_FAIL_WITHOUT_DEFICIENCIES`."

    Design: Corner/validations/complete_fail_without_deficiencies_returns_error
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.inspection_in_progress(api, device["id"], inspector["id"], itype="ANNUAL", start=1, end=2)
    resp = api.complete_inspection(ins["id"], th.complete_payload("FAIL"),
                                   th.make_licensed_inspector_headers(inspector["id"]))
    th.validate_error(resp, ApiErrorId.ERR_FAIL_WITHOUT_DEFICIENCIES.value)


def test_cancel_in_progress_returns_not_cancellable(api):
    """PRD §3.4: "An inspection may be cancelled by a Registrar while it is still
    SCHEDULED or ASSIGNED; cancelling in any other state is rejected with
    ERR_INSPECTION_NOT_CANCELLABLE."

    Design: Corner/state_machines/cancel_in_progress_returns_not_cancellable
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    ins = th.inspection_in_progress(api, device["id"], inspector["id"], itype="ANNUAL", start=1, end=2)
    resp = api.cancel_inspection(ins["id"], th.REG)
    th.validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_CANCELLABLE.value)


def test_resolve_open_deficiency_marks_resolved(api):
    """PRD §3.6: "A LicensedInspector resolves a deficiency once the underlying
    condition is corrected, moving it to the terminal RESOLVED state."

    Design: Corner/state_machines/resolve_open_deficiency_marks_resolved
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["PASSENGER_ELEVATOR"])
    device = th.new_device(api, owner["id"], category="PASSENGER_ELEVATOR")
    _, deficiency = th.conditional_with_deficiency(api, device["id"], inspector["id"], severity="MINOR", code="B4-1")
    resp = api.resolve_deficiency(deficiency["id"], th.make_licensed_inspector_headers(inspector["id"]))
    resolved = th.validate_success(resp)
    assert resolved["status"] == "RESOLVED"

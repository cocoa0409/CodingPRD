"""Transitive cascades: the CRITICAL-incident depth-3 chain and the repair-completion
depth-2 chain.

Difficulty queue A: transitive_cascade.
"""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    setup_certified_vessel, setup_registered_vessel,
    new_inspection, raise_deficiency, record_result,
    new_repair_order, complete_repair_order, file_incident,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# transitive_cascade / incident_suspend_revoke_cancel_scheduled_depth3
# ---------------------------------------------------------------------------
def _incident_cascade_ctx():
    ctx = setup_certified_vessel()
    insp2 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="EXTERNAL",
                           scheduled_start="2026-06-03T09:00:00Z", scheduled_end="2026-06-03T11:00:00Z")
    file_incident(ctx["vessel_id"], ctx["owner_id"], severity="CRITICAL",
                  occurred_at="2026-05-30T00:00:00Z", narrative="flame-out")
    ctx["insp2_id"] = insp2["id"]
    return ctx


def test_critical_incident_suspends_and_revokes(api):
    """PRD §3.8: "1. The vessel's `service_status` advances to `SUSPENDED`. 2. Any
    `ACTIVE` certificate on the vessel is revoked (`ACTIVE → REVOKED`), which in turn
    cancels the vessel's `SCHEDULED` non-`SPECIAL` inspections and clears
    `current_certificate_id`".

    Design: Difficulty/transitive_cascade/incident_suspend_revoke_cancel_scheduled_depth3
    """
    ctx = _incident_cascade_ctx()
    vessel = validate_success(api.get_vessel(ctx["vessel_id"], ADMIN))
    cert = validate_success(api.get_certificate(ctx["cert1_id"], ADMIN))
    assert vessel["service_status"] == "SUSPENDED"
    assert cert["status"] == "REVOKED"


def test_critical_incident_cancels_scheduled_inspection(api):
    """PRD §3.8: "which in turn cancels the vessel's `SCHEDULED` non-`SPECIAL`
    inspections and clears `current_certificate_id`, exactly as an ordinary revocation
    would."

    Design: Difficulty/transitive_cascade/incident_suspend_revoke_cancel_scheduled_depth3
    """
    ctx = _incident_cascade_ctx()
    insp2 = validate_success(api.get_inspection(ctx["insp2_id"], ADMIN))
    assert insp2["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# transitive_cascade / repair_complete_moves_deficiency_to_reinspection_depth2
# ---------------------------------------------------------------------------
def _repair_complete_ctx():
    ctx = setup_registered_vessel()
    insp1 = new_inspection(ctx["vessel_id"], ctx["insp_a_id"], inspection_type="INTERNAL")
    d1 = raise_deficiency(insp1["id"], ctx["insp_a_id"], severity="NON_CRITICAL", description="valve seepage")
    record_result(insp1["id"], ctx["insp_a_id"], "PASS_WITH_DEFICIENCIES")
    ro1 = new_repair_order(ctx["vessel_id"], [d1["id"]], ctx["owner_id"], description="reseat valve")
    complete_repair_order(ro1["id"], ctx["owner_id"])
    ctx.update({"d1_id": d1["id"], "ro1_id": ro1["id"]})
    return ctx


def test_repair_completion_marks_order_completed(api):
    """PRD §3.6: "it is permitted only while the order is `IN_PROGRESS`, and it advances
    the order `IN_PROGRESS → COMPLETED`."

    Design: Difficulty/transitive_cascade/repair_complete_moves_deficiency_to_reinspection_depth2
    """
    ctx = _repair_complete_ctx()
    data = validate_success(api.get_repair_order(ctx["ro1_id"], ADMIN))
    assert data["status"] == "COMPLETED"


def test_repair_completion_moves_deficiency_to_reinspection(api):
    """PRD §3.6: "As its cascade, each deficiency linked to the order advances
    `UNDER_REPAIR → REINSPECTION`, and the vessel's risk scores are recomputed."

    Design: Difficulty/transitive_cascade/repair_complete_moves_deficiency_to_reinspection_depth2
    """
    ctx = _repair_complete_ctx()
    data = validate_success(api.get_deficiency(ctx["d1_id"], ADMIN))
    assert data["status"] == "REINSPECTION"

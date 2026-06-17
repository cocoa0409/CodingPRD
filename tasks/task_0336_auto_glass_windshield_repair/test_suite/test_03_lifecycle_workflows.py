"""Work order lifecycle: branching at finish-install, cascade chains, and
invalid-transition / terminal-lockdown guards (PRD 3.5, 3.6, 3.7, state machines)."""
from test_helpers import validate_success, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADVISOR = fx.ADVISOR
MANAGER = fx.MANAGER


# ---------------------------------------------------------------------------
# Difficulty rule 3 — work_order_branch_install_to_curing_or_recalibration
# ---------------------------------------------------------------------------
def test_replace_adas_finish_install_goes_awaiting_recalibration(api):
    """PRD 3.5: "The destination state forks on recalibration: when
    recalibration_required is true the work order moves to AWAITING_RECALIBRATION".
    PRD 3.4: "its recalibration_required is set true exactly when the
    service_decision is REPLACE and the vehicle is ADAS-equipped".

    Design: Difficulty/non_linear_state_machine/work_order_branch_install_to_curing_or_recalibration
    """
    ctx = fx.setup_after_finish_install(adas_equipped=True, temp_c=25, humidity_pct=40)
    wo = ctx["work_order"]
    assert wo["recalibration_required"] is True, "ADAS REPLACE must set recalibration_required true"
    assert wo["status"] == "AWAITING_RECALIBRATION", (
        f"ADAS REPLACE must fork to AWAITING_RECALIBRATION, got {wo['status']}")


def test_replace_non_adas_finish_install_goes_curing(api):
    """PRD 3.5: "and when recalibration_required is false it moves to CURING."

    Design: Difficulty/non_linear_state_machine/work_order_branch_install_to_curing_or_recalibration
    """
    ctx = fx.setup_after_finish_install(adas_equipped=False, temp_c=25, humidity_pct=40)
    wo = ctx["work_order"]
    assert wo["recalibration_required"] is False, "non-ADAS REPLACE must leave recalibration_required false"
    assert wo["status"] == "CURING", (
        f"non-ADAS REPLACE must fork to CURING, got {wo['status']}")


# ---------------------------------------------------------------------------
# Difficulty rule 4 — finish_install_consumes_part_decrements_stock_depth3
# ---------------------------------------------------------------------------
def test_finish_install_consumes_part_and_decrements_reserved(api):
    """PRD 3.5: "it always stamps the work order's safe_drive_away_at, marks this
    work order's RESERVED part order as CONSUMED and decrements that part's
    reserved_qty by the quantity (the glass is now installed)".

    Design: Difficulty/transitive_cascade/finish_install_consumes_part_decrements_stock_depth3
    """
    ctx = fx.setup_after_finish_install(adas_equipped=True, temp_c=25, humidity_pct=40, on_hand_qty=5)
    wo = ctx["work_order"]
    po = ctx["part_order"]
    part_id = ctx["glass_part"]["id"]
    assert wo["status"] == "AWAITING_RECALIBRATION"
    po_after = validate_success(api.get_part_order(po["id"], ADVISOR), 200)
    assert po_after["status"] == "CONSUMED", f"part order must be CONSUMED, got {po_after['status']}"
    part_after = validate_success(api.get_glass_part(part_id, MANAGER), 200)
    # on_hand started 5, reserve drew to 4, consume draws reserved 1->0.
    assert part_after["reserved_qty"] == 0, f"reserved_qty must be 0 after consume, got {part_after['reserved_qty']}"
    assert part_after["on_hand_qty"] == 4, f"on_hand_qty must stay 4, got {part_after['on_hand_qty']}"


def test_finish_install_stamps_safe_drive_away_at(api):
    """PRD 3.5: "it always stamps the work order's safe_drive_away_at" — the
    depth-3 cascade originates from this finish-install side effect.

    Design: Difficulty/transitive_cascade/finish_install_consumes_part_decrements_stock_depth3
    """
    ctx = fx.setup_after_finish_install(adas_equipped=True, temp_c=25, humidity_pct=40)
    wo = ctx["work_order"]
    assert wo["safe_drive_away_at"] is not None, "finish-install must stamp safe_drive_away_at"


# ---------------------------------------------------------------------------
# Corner state_machines — repair_work_order_completes_directly_from_in_service
# ---------------------------------------------------------------------------
def test_repair_completes_directly_from_in_service_issues_chip_repair_warranty(api):
    """PRD 3.7: "A REPAIR job, which never cures or recalibrates, completes directly
    out of IN_SERVICE".
    PRD 3.7: "Completion issues a Warranty whose coverage_type is CHIP_REPAIR for a
    REPAIR job ... with status ACTIVE".

    Design: Corner/state_machines/repair_work_order_completes_directly_from_in_service
    """
    wo_done, warranty = fx.setup_completed_repair()
    assert wo_done["status"] == "COMPLETED", f"REPAIR must complete from IN_SERVICE, got {wo_done['status']}"
    assert warranty is not None, "completion must issue a warranty"
    assert warranty["coverage_type"] == "CHIP_REPAIR", (
        f"REPAIR warranty must be CHIP_REPAIR, got {warranty['coverage_type']}")
    assert warranty["status"] == "ACTIVE", f"issued warranty must be ACTIVE, got {warranty['status']}"


# ---------------------------------------------------------------------------
# Corner state_machines — accept_assessment_twice_invalid_state
# ---------------------------------------------------------------------------
def test_accept_assessment_twice_rejected(api):
    """PRD 3.3: "Acceptance is defined only from OPEN ... If the work order is not in
    OPEN, the acceptance is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/accept_assessment_twice_invalid_state
    """
    cust, veh, wo, asmt_id = fx.setup_assessed_work_order(decision="REPAIR")
    resp = api.accept_assessment(wo["id"], {"assessment_id": asmt_id}, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Corner state_machines — start_service_from_open_invalid_state
# ---------------------------------------------------------------------------
def test_start_service_from_open_rejected(api):
    """PRD 3.5: "starts service, advancing the work order from SCHEDULED to
    IN_SERVICE; this requires the work order to be SCHEDULED and its linked
    appointment to be CHECKED_IN".
    PRD 2.8: "the system evaluate whether the target resource is in a state from
    which the requested transition is defined".

    Design: Corner/state_machines/start_service_from_open_invalid_state
    """
    cust, veh = fx.setup_customer_and_vehicle()
    tech = fx.create_technician()
    wo = fx.create_work_order(cust["id"], veh["id"])
    tech_headers = fx.make_technician_headers(tech["id"])
    resp = api.start_service(wo["id"], tech_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Corner state_machines — cancel_completed_work_order_invalid_state
# (cancel an IN_SERVICE REPAIR work order, not from {OPEN,ASSESSED,SCHEDULED})
# ---------------------------------------------------------------------------
def test_cancel_in_service_work_order_rejected(api):
    """PRD 3.7: "A ServiceAdvisor cancels a work order that is in OPEN, ASSESSED, or
    SCHEDULED, moving it to CANCELLED; later states require the refund path rather
    than cancellation."

    Design: Corner/state_machines/cancel_completed_work_order_invalid_state
    """
    ctx = fx.setup_in_service(decision="REPAIR", adas_equipped=False)
    wo = ctx["work_order"]
    assert wo["status"] == "IN_SERVICE"
    resp = api.cancel_work_order(wo["id"], ADVISOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_work_order(wo["id"], ADVISOR), 200)
    assert after["status"] == "IN_SERVICE", f"work order must stay IN_SERVICE, got {after['status']}"


# ---------------------------------------------------------------------------
# Corner state_machines — void_warranty_twice_invalid_state
# ---------------------------------------------------------------------------
def test_void_warranty_twice_rejected(api):
    """PRD 3.7: "may be voided by the ShopManager while it is ACTIVE, moving it from
    ACTIVE to VOID". A second void is not defined from VOID (PRD 2.8 ERR_INVALID_STATE).

    Design: Corner/state_machines/void_warranty_twice_invalid_state
    """
    wo_done, warranty = fx.setup_completed_repair()
    assert warranty is not None
    first = api.void_warranty(warranty["id"], MANAGER)
    validate_success(first, 200)
    second = api.void_warranty(warranty["id"], MANAGER)
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Corner state_machines — finish_install_on_repair_work_order_invalid_state
# ---------------------------------------------------------------------------
def test_finish_install_on_repair_rejected(api):
    """PRD 3.5: "Finishing the install is defined only when the work order is
    IN_SERVICE and the service_decision is REPLACE". A REPAIR job has no such
    transition (PRD 2.8 ERR_INVALID_STATE).

    Design: Corner/state_machines/finish_install_on_repair_work_order_invalid_state
    """
    ctx = fx.setup_in_service(decision="REPAIR", adas_equipped=False)
    wo = ctx["work_order"]
    resp = api.finish_install(wo["id"], {"temp_c": 20, "humidity_pct": 40}, ctx["tech_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

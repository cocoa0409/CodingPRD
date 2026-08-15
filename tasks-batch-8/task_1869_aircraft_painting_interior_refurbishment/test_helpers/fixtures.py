"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
per test), so all preconditions are built here from PRD-declared endpoints.

Setup calls use get_success_data() so a failed precondition surfaces as a
clear "Setup step failed" error naming the step, not a confusing assertion.

Ownership threading: customer-side approvals use
make_customer_rep_headers(customer["id"]) — the CustomerRep identity is
entity-backed (PRD §2.1), so the header must carry the real Customer id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .constants import FIXTURE
from .factories import (
    create_aircraft_payload,
    create_booth_booking_payload,
    create_change_order_payload,
    create_customer_payload,
    create_delay_event_payload,
    create_discovery_item_payload,
    create_hangar_bay_payload,
    create_hangar_slot_payload,
    create_invoice_payload,
    create_paint_booth_payload,
    create_paint_scheme_payload,
    create_program_payload,
    create_quality_inspection_payload,
    create_soft_good_lot_payload,
    create_surface_assessment_payload,
    create_weight_record_payload,
    decide_assessment_payload,
    estimate_discovery_payload,
    record_burn_test_payload,
    record_inspection_result_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_rep_headers,
    make_quality_inspector_headers,
    make_shop_technician_headers,
)

_ADMIN = TEST_USERS["center_admin_headers"]
_PM = TEST_USERS["program_manager_headers"]
_DL = TEST_USERS["design_lead_headers"]
_TECH = TEST_USERS["shop_technician_headers"]
_QI = TEST_USERS["quality_inspector_headers"]
_FIN = TEST_USERS["finance_clerk_headers"]


# --------------------------------------------------------------------------
# Primitive creators
# --------------------------------------------------------------------------

def set_logical_clock(iso: str) -> None:
    get_success_data(_api.set_clock({"to_iso8601": iso}, _ADMIN))


def create_customer(**overrides) -> dict:
    resp = _api.create_customer(create_customer_payload(**overrides), _ADMIN)
    return get_success_data(resp, 201)


def create_aircraft(customer_id: str, **overrides) -> dict:
    payload = create_aircraft_payload(customer_id=customer_id, **overrides)
    resp = _api.create_aircraft(payload, _ADMIN)
    return get_success_data(resp, 201)


def create_program(aircraft_id: str, customer_id: str, **overrides) -> dict:
    payload = create_program_payload(
        aircraft_id=aircraft_id, customer_id=customer_id, **overrides
    )
    resp = _api.create_program(payload, _PM)
    return get_success_data(resp, 201)


def create_bay(**overrides) -> dict:
    resp = _api.create_hangar_bay(create_hangar_bay_payload(**overrides), _ADMIN)
    return get_success_data(resp, 201)


def create_booth(**overrides) -> dict:
    resp = _api.create_paint_booth(create_paint_booth_payload(**overrides), _ADMIN)
    return get_success_data(resp, 201)


def book_slot(bay_id: str, program_id: str, **overrides) -> dict:
    payload = create_hangar_slot_payload(bay_id=bay_id, program_id=program_id, **overrides)
    resp = _api.create_hangar_slot(payload, _PM)
    return get_success_data(resp, 201)


def book_booth_window(booth_id: str, program_id: str, **overrides) -> dict:
    payload = create_booth_booking_payload(
        booth_id=booth_id, program_id=program_id, **overrides
    )
    resp = _api.create_booth_booking(payload, _PM)
    return get_success_data(resp, 201)


def advance_program(program_id: str, to_phase: str) -> dict:
    resp = _api.advance_program(program_id, {"to_phase": to_phase}, _PM)
    return get_success_data(resp)


def get_program(program_id: str) -> dict:
    return get_success_data(_api.get_program(program_id, _PM))


def program_version(program_id: str) -> int:
    return get_program(program_id)["version"]


# --------------------------------------------------------------------------
# Paint scheme helpers (customer approval is ownership-gated + OCC-guarded)
# --------------------------------------------------------------------------

def create_scheme(program_id: str, **overrides) -> dict:
    payload = create_paint_scheme_payload(program_id=program_id, **overrides)
    resp = _api.create_paint_scheme(payload, _DL)
    return get_success_data(resp, 201)


def submit_scheme(scheme_id: str) -> dict:
    return get_success_data(_api.submit_paint_scheme(scheme_id, _DL))


def approve_scheme(scheme_id: str, customer_id: str, expected_program_version: int) -> dict:
    resp = _api.approve_paint_scheme(
        scheme_id,
        {"expected_program_version": expected_program_version},
        make_customer_rep_headers(customer_id),
    )
    return get_success_data(resp)


def create_and_approve_scheme(program_id: str, customer_id: str, **overrides) -> dict:
    """DRAFT -> SUBMITTED -> APPROVED, reading the program version fresh so the
    OCC precondition (expected_program_version == program.version) holds."""
    scheme = create_scheme(program_id, **overrides)
    submit_scheme(scheme["id"])
    return approve_scheme(scheme["id"], customer_id, program_version(program_id))


# --------------------------------------------------------------------------
# Surface assessment helpers
# --------------------------------------------------------------------------

def create_assessment(program_id: str) -> dict:
    resp = _api.create_surface_assessment(
        create_surface_assessment_payload(program_id=program_id), _TECH
    )
    return get_success_data(resp, 201)


def decide_assessment(assessment_id: str, decision="STRIP", corrosion_severity="NONE",
                      **overrides) -> dict:
    payload = decide_assessment_payload(
        decision=decision, corrosion_severity=corrosion_severity, **overrides
    )
    resp = _api.decide_surface_assessment(assessment_id, payload, _TECH)
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Discovery item helpers
# --------------------------------------------------------------------------

def create_discovery(program_id: str, **overrides) -> dict:
    payload = create_discovery_item_payload(program_id=program_id, **overrides)
    resp = _api.create_discovery_item(payload, _TECH)
    return get_success_data(resp, 201)


def estimate_discovery(item_id: str, **overrides) -> dict:
    resp = _api.estimate_discovery_item(item_id, estimate_discovery_payload(**overrides), _PM)
    return get_success_data(resp)


def create_estimated_discovery(program_id: str, **overrides) -> dict:
    """OPEN -> ESTIMATED discovery item."""
    est_cost = overrides.pop("est_cost_cents", 250000)
    est_hours = overrides.pop("est_hours", 40)
    item = create_discovery(program_id, **overrides)
    estimate_discovery(item["id"], est_cost_cents=est_cost, est_hours=est_hours)
    return get_success_data(_api.get_discovery_item(item["id"], _PM))


def approve_discovery(item_id: str, customer_id: str) -> dict:
    resp = _api.approve_discovery_item(
        item_id,
        {"expected_program_version": program_version_of_item(item_id)},
        make_customer_rep_headers(customer_id),
    )
    return get_success_data(resp)


def program_version_of_item(item_id: str) -> int:
    item = get_success_data(_api.get_discovery_item(item_id, _PM))
    return program_version(item["program_id"])


# --------------------------------------------------------------------------
# Change order helpers
# --------------------------------------------------------------------------

def create_change_order(program_id: str, **overrides) -> dict:
    payload = create_change_order_payload(program_id=program_id, **overrides)
    resp = _api.create_change_order(payload, _PM)
    return get_success_data(resp, 201)


def submit_change_order(order_id: str) -> dict:
    return get_success_data(_api.submit_change_order(order_id, _PM))


def create_submitted_change_order(program_id: str, **overrides) -> dict:
    order = create_change_order(program_id, **overrides)
    submit_change_order(order["id"])
    return get_success_data(_api.get_change_order(order["id"], _PM))


# --------------------------------------------------------------------------
# Inspection / certification / weight helpers
# --------------------------------------------------------------------------

def pass_inspection(program_id: str, inspection_type: str) -> dict:
    insp = get_success_data(
        _api.create_quality_inspection(
            create_quality_inspection_payload(
                program_id=program_id, inspection_type=inspection_type
            ),
            _QI,
        ),
        201,
    )
    resp = _api.record_inspection_result(
        insp["id"], record_inspection_result_payload(result="PASS"), _QI
    )
    return get_success_data(resp)


def create_and_certify_lot(program_id: str, **overrides) -> dict:
    lot = get_success_data(
        _api.create_soft_good_lot(
            create_soft_good_lot_payload(program_id=program_id, **overrides), _TECH
        ),
        201,
    )
    get_success_data(
        _api.record_burn_test(lot["id"], record_burn_test_payload(result="PASS"), _TECH), 201
    )
    return get_success_data(_api.get_soft_good_lot(lot["id"], _TECH))


def prepare_weight_record(program_id: str, scheme_id: str, variant="FINAL",
                          removal=100.0, installed=108.0, preparer="tech-1") -> dict:
    payload = create_weight_record_payload(
        program_id=program_id,
        scheme_id=scheme_id,
        variant=variant,
        removal_weight_lbs=removal,
        installed_weight_lbs=installed,
    )
    resp = _api.create_weight_balance_record(
        payload, make_shop_technician_headers(preparer)
    )
    return get_success_data(resp, 201)


def sign_off_weight_record(record_id: str, signer="qi-1") -> dict:
    resp = _api.sign_off_weight_balance_record(
        record_id, make_quality_inspector_headers(signer)
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Delay event helpers
# --------------------------------------------------------------------------

def create_delay_event(program_id: str, **overrides) -> dict:
    payload = create_delay_event_payload(program_id=program_id, **overrides)
    resp = _api.create_delay_event(payload, _PM)
    return get_success_data(resp, 201)


# --------------------------------------------------------------------------
# Invoice helpers
# --------------------------------------------------------------------------

def create_invoice(program_id: str, kind: str) -> dict:
    resp = _api.create_invoice(
        create_invoice_payload(program_id=program_id, kind=kind), _FIN
    )
    return get_success_data(resp, 201)


def issue_invoice(invoice_id: str) -> dict:
    return get_success_data(_api.issue_invoice(invoice_id, _FIN))


# --------------------------------------------------------------------------
# Composite engagement chains (program phase walker)
# --------------------------------------------------------------------------

def create_engagement(**program_overrides) -> dict:
    """Customer + aircraft + QUOTED program. Returns the context dict every
    composite helper threads through."""
    customer = create_customer()
    aircraft = create_aircraft(customer["id"])
    program = create_program(aircraft["id"], customer["id"], **program_overrides)
    return {"customer": customer, "aircraft": aircraft, "program": program}


def setup_booked_program(**program_overrides) -> dict:
    """QUOTED -> BOOKED: one bay + one BOOKED slot covering the clock, then advance."""
    set_logical_clock(FIXTURE["SLOT_START"])
    ctx = create_engagement(**program_overrides)
    ctx["bay"] = create_bay()
    ctx["slot"] = book_slot(ctx["bay"]["id"], ctx["program"]["id"])
    advance_program(ctx["program"]["id"], "BOOKED")
    ctx["program"] = get_program(ctx["program"]["id"])
    return ctx


def setup_inducted_program(**program_overrides) -> dict:
    """BOOKED -> INDUCTED: slot activated (clock inside its window), aircraft
    cascades to IN_REFURB."""
    ctx = setup_booked_program(**program_overrides)
    get_success_data(_api.activate_hangar_slot(ctx["slot"]["id"], _PM))
    advance_program(ctx["program"]["id"], "INDUCTED")
    ctx["program"] = get_program(ctx["program"]["id"])
    return ctx


def setup_surface_review_program(decision="STRIP", corrosion_severity="NONE",
                                 approve_scheme=True, **program_overrides) -> dict:
    """INDUCTED -> SURFACE_REVIEW with the assessment DECIDED (and, by default,
    a scheme already APPROVED — approval is legal through SURFACE_REVIEW)."""
    ctx = setup_inducted_program(**program_overrides)
    ctx["assessment"] = create_assessment(ctx["program"]["id"])
    advance_program(ctx["program"]["id"], "SURFACE_REVIEW")
    decide_assessment(
        ctx["assessment"]["id"], decision=decision, corrosion_severity=corrosion_severity
    )
    if approve_scheme:
        ctx["scheme"] = create_and_approve_scheme(
            ctx["program"]["id"], ctx["customer"]["id"]
        )
    ctx["program"] = get_program(ctx["program"]["id"])
    return ctx


def setup_in_work_program(complete_booth: bool = False, actual_hours: int = 8,
                          **program_overrides) -> dict:
    """SURFACE_REVIEW -> IN_WORK: DECIDED STRIP/NONE assessment, APPROVED
    scheme, one BOOKED booth booking. Optionally completes the booking."""
    ctx = setup_surface_review_program(**program_overrides)
    ctx["booth"] = create_booth()
    ctx["booking"] = book_booth_window(ctx["booth"]["id"], ctx["program"]["id"])
    advance_program(ctx["program"]["id"], "IN_WORK")
    if complete_booth:
        get_success_data(
            _api.complete_booth_booking(
                ctx["booking"]["id"], {"actual_hours": actual_hours}, _TECH
            )
        )
        ctx["booking"] = get_success_data(_api.get_booth_booking(ctx["booking"]["id"], _PM))
    ctx["program"] = get_program(ctx["program"]["id"])
    return ctx


def setup_in_inspection_program(**program_overrides) -> dict:
    """IN_WORK -> IN_INSPECTION: booth booking COMPLETED at exactly its
    scheduled 8 hours, no open discovery items."""
    ctx = setup_in_work_program(complete_booth=True, **program_overrides)
    advance_program(ctx["program"]["id"], "IN_INSPECTION")
    ctx["program"] = get_program(ctx["program"]["id"])
    return ctx


def pass_standard_inspections(ctx: dict) -> dict:
    """PAINT, INTERIOR, FINAL all PASSED (FINAL's prerequisite order honored)."""
    ctx.setdefault("inspections", {})
    for itype in ("PAINT", "INTERIOR", "FINAL"):
        ctx["inspections"][itype] = pass_inspection(ctx["program"]["id"], itype)
    return ctx


def setup_ready_for_delivery(**program_overrides) -> dict:
    """Full chain to READY_FOR_DELIVERY: inspections passed, one CERTIFIED lot,
    FINAL weight record SIGNED_OFF (delta 38.6 within the 50.0 limit)."""
    ctx = setup_in_inspection_program(**program_overrides)
    pass_standard_inspections(ctx)
    ctx["lot"] = create_and_certify_lot(ctx["program"]["id"])
    ctx["wbr"] = prepare_weight_record(
        ctx["program"]["id"], ctx["scheme"]["id"], variant="FINAL"
    )
    sign_off_weight_record(ctx["wbr"]["id"])
    advance_program(ctx["program"]["id"], "READY_FOR_DELIVERY")
    ctx["program"] = get_program(ctx["program"]["id"])
    return ctx


def setup_delivered_program(**program_overrides) -> dict:
    """READY_FOR_DELIVERY -> DELIVERED with the FINAL invoice PAID."""
    ctx = setup_ready_for_delivery(**program_overrides)
    invoice = create_invoice(ctx["program"]["id"], "FINAL")
    issue_invoice(invoice["id"])
    get_success_data(
        _api.pay_invoice(invoice["id"], make_customer_rep_headers(ctx["customer"]["id"]))
    )
    advance_program(ctx["program"]["id"], "DELIVERED")
    ctx["invoice"] = get_success_data(_api.get_invoice(invoice["id"], _FIN))
    ctx["program"] = get_program(ctx["program"]["id"])
    return ctx

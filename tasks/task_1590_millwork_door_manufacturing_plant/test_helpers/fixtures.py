"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database, so
these helpers build complete preconditions (project -> order -> openings ->
configure -> drawing -> approval -> program -> slot -> production -> finishing
-> staging -> trips -> labels -> punch) using only PRD-declared endpoints.

Segregation-of-duties user ids used throughout (PRD §2.9):
  drawing submitter "est-1" / approver "arch-1"
  label issuer "la-1" / applier "pl-1" / verifier "qa-1"
  punch reporter "qa-9" (or per-call) / verifier "qa-1"
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client
from .constants import SHEEN_TARGET_GU
from .factories import (
    create_project_payload, create_hardware_template_payload,
    create_moulder_machine_payload, create_spray_booth_payload,
    create_fire_label_roll_payload, create_order_payload, create_opening_payload,
    create_shop_drawing_payload, create_machining_program_payload,
    create_moulder_setup_slot_payload, create_finishing_batch_payload,
    create_label_allocation_payload, create_delivery_trip_payload,
    create_punch_item_payload,
)

# Canonical per-role user ids (opaque identities; only SoD comparisons matter).
PM = "pm-1"
EST = "est-1"
ARCH = "arch-1"
PL = "pl-1"
LA = "la-1"
QA = "qa-1"
SC = "sc-1"
ANY = "any-1"


def H(role: str, user_id: str) -> dict:
    return build_user_headers(user_id, role)


PM_H = H("PlantManager", PM)
EST_H = H("Estimator", EST)
ARCH_H = H("Architect", ARCH)
PL_H = H("ProductionLead", PL)
LA_H = H("LabelAuthority", LA)
QA_H = H("QAInspector", QA)
SC_H = H("ShippingCoordinator", SC)
ANY_H = H("Any", ANY)

# Per-target actor map for PUT /millwork/orders/{id}/status (PRD §2.1).
_ORDER_STATUS_ACTOR = {
    "CONFIGURED": EST_H,
    "CANCELLED": EST_H,
    "IN_PRODUCTION": PL_H,
    "FINISHING": PL_H,
    "READY_TO_SHIP": PL_H,
    "SHIPPED": SC_H,
    "CLOSED": PM_H,
}


# ---------------------------------------------------------------------------
# Tier 0: single-call creators (all lenient; raise AssertionError on failure)
# ---------------------------------------------------------------------------

def make_project(name="Test Project", site_address="1 Main St", contract_code="CC-1") -> dict:
    resp = api_client.create_project(
        create_project_payload(name=name, site_address=site_address, contract_code=contract_code),
        PM_H,
    )
    return get_success_data(resp)


def make_template(template_code="T-1", manufacturer="ACME", fire_rated_compatible=True) -> dict:
    resp = api_client.create_hardware_template(
        create_hardware_template_payload(
            template_code=template_code, manufacturer=manufacturer,
            fire_rated_compatible=fire_rated_compatible,
        ),
        PM_H,
    )
    return get_success_data(resp)


def make_machine(machine_code="M-1", supported_species=("OAK",), active=True) -> dict:
    resp = api_client.create_moulder_machine(
        create_moulder_machine_payload(
            machine_code=machine_code, supported_species=list(supported_species), active=active,
        ),
        PM_H,
    )
    return get_success_data(resp)


def make_booth(booth_code="B-1", capacity=2) -> dict:
    resp = api_client.create_spray_booth(
        create_spray_booth_payload(booth_code=booth_code, capacity=capacity), PM_H,
    )
    return get_success_data(resp)


def make_roll(label_series="UL_20MIN", serial_capacity=2) -> dict:
    resp = api_client.create_fire_label_roll(
        create_fire_label_roll_payload(label_series=label_series, serial_capacity=serial_capacity),
        PM_H,
    )
    return get_success_data(resp)


def make_trip(project_id, trip_code="T-1", truck_capacity_leaves=4,
              departure_date="2026-10-02", site_arrival_date="2026-10-04") -> dict:
    resp = api_client.create_delivery_trip(
        create_delivery_trip_payload(
            project_id, trip_code=trip_code, truck_capacity_leaves=truck_capacity_leaves,
            departure_date=departure_date, site_arrival_date=site_arrival_date,
        ),
        PM_H,
    )
    return get_success_data(resp)


def make_order(project_id, order_code="O-1", species="OAK", profile_code="PR-1",
               finish_system="STAIN", sheen_target="SATIN",
               hardware_prep_mode="INSTALLER_PREP", fire_rating_required="NONE",
               hardware_template_id=None) -> dict:
    payload = create_order_payload(
        project_id, order_code=order_code, species=species, profile_code=profile_code,
        finish_system=finish_system, sheen_target=sheen_target,
        hardware_prep_mode=hardware_prep_mode, fire_rating_required=fire_rating_required,
    )
    if hardware_template_id is not None:
        payload["hardware_template_id"] = hardware_template_id
    resp = api_client.create_order(payload, EST_H)
    return get_success_data(resp)


def make_opening(order_id, opening_no="1", width_in=36, height_in=84, leaf_count=1,
                 fire_rating="NONE", required_on_site_date="2026-10-01") -> dict:
    resp = api_client.create_opening(
        create_opening_payload(
            order_id, opening_no=opening_no, width_in=width_in, height_in=height_in,
            leaf_count=leaf_count, fire_rating=fire_rating,
            required_on_site_date=required_on_site_date,
        ),
        EST_H,
    )
    return get_success_data(resp)


def get_order(order_id) -> dict:
    return get_success_data(api_client.get_order(order_id, ANY_H))


def get_opening(opening_id) -> dict:
    return get_success_data(api_client.get_opening(opening_id, ANY_H))


def get_drawing(drawing_id) -> dict:
    return get_success_data(api_client.get_shop_drawing(drawing_id, ANY_H))


def get_program(program_id) -> dict:
    return get_success_data(api_client.get_machining_program(program_id, ANY_H))


def get_slot(slot_id) -> dict:
    return get_success_data(api_client.get_moulder_setup_slot(slot_id, ANY_H))


def get_batch(batch_id) -> dict:
    return get_success_data(api_client.get_finishing_batch(batch_id, ANY_H))


def get_roll(roll_id) -> dict:
    return get_success_data(api_client.get_fire_label_roll(roll_id, ANY_H))


def get_allocation(allocation_id) -> dict:
    return get_success_data(api_client.get_label_allocation(allocation_id, ANY_H))


def get_trip(trip_id) -> dict:
    return get_success_data(api_client.get_delivery_trip(trip_id, ANY_H))


def get_punch(punch_id) -> dict:
    return get_success_data(api_client.get_punch_item(punch_id, ANY_H))


# ---------------------------------------------------------------------------
# Tier 1: state progression primitives
# ---------------------------------------------------------------------------

def set_order_status(order_id, target_status) -> dict:
    headers = _ORDER_STATUS_ACTOR[target_status]
    resp = api_client.set_order_status(order_id, {"target_status": target_status}, headers)
    return get_success_data(resp)


def configure_order(order_id) -> dict:
    return set_order_status(order_id, "CONFIGURED")


def make_drawing(order_id) -> dict:
    """Create a DRAFT drawing revision under OCC on the order's current version."""
    version = get_order(order_id)["version"]
    resp = api_client.create_shop_drawing(
        create_shop_drawing_payload(order_id, version), EST_H,
    )
    return get_success_data(resp)


def submit_drawing(drawing_id, user_id=EST) -> dict:
    resp = api_client.set_shop_drawing_status(
        drawing_id, {"target_status": "SUBMITTED"}, H("Estimator", user_id),
    )
    return get_success_data(resp)


def approve_drawing(drawing_id, user_id=ARCH, review_note=None) -> dict:
    payload = {"target_status": "APPROVED"}
    if review_note is not None:
        payload["review_note"] = review_note
    resp = api_client.set_shop_drawing_status(drawing_id, payload, H("Architect", user_id))
    return get_success_data(resp)


def reject_drawing(drawing_id, user_id=ARCH, review_note=None) -> dict:
    payload = {"target_status": "REJECTED"}
    if review_note is not None:
        payload["review_note"] = review_note
    resp = api_client.set_shop_drawing_status(drawing_id, payload, H("Architect", user_id))
    return get_success_data(resp)


def void_drawing(drawing_id, user_id=EST) -> dict:
    resp = api_client.set_shop_drawing_status(
        drawing_id, {"target_status": "VOID"}, H("Estimator", user_id),
    )
    return get_success_data(resp)


def make_program(drawing_id, order_id, estimated_minutes=60) -> dict:
    resp = api_client.create_machining_program(
        create_machining_program_payload(drawing_id, order_id, estimated_minutes=estimated_minutes),
        PL_H,
    )
    return get_success_data(resp)


def book_slot(program_id, machine_id, start_hour=8, end_hour=10) -> dict:
    resp = api_client.create_moulder_setup_slot(
        create_moulder_setup_slot_payload(
            program_id, machine_id, start_hour=start_hour, end_hour=end_hour,
        ),
        PL_H,
    )
    return get_success_data(resp)


def complete_slot(slot_id) -> dict:
    resp = api_client.set_moulder_setup_slot_status(slot_id, {"target_status": "COMPLETED"}, PL_H)
    return get_success_data(resp)


def cancel_slot(slot_id) -> dict:
    resp = api_client.set_moulder_setup_slot_status(slot_id, {"target_status": "CANCELLED"}, PL_H)
    return get_success_data(resp)


def release_program(program_id) -> dict:
    resp = api_client.set_machining_program_status(program_id, {"target_status": "RELEASED"}, PL_H)
    return get_success_data(resp)


def void_program(program_id) -> dict:
    resp = api_client.set_machining_program_status(program_id, {"target_status": "VOID"}, PL_H)
    return get_success_data(resp)


def machine_opening(opening_id) -> dict:
    resp = api_client.set_opening_status(opening_id, {"target_fab_status": "MACHINED"}, PL_H)
    return get_success_data(resp)


def stage_opening(opening_id) -> dict:
    resp = api_client.set_opening_status(opening_id, {"target_fab_status": "STAGED"}, PL_H)
    return get_success_data(resp)


def make_batch(order_id, booth_id, cure_start_hour=10, cure_end_hour=16,
               is_rework_batch=False) -> dict:
    payload = create_finishing_batch_payload(
        order_id, booth_id, cure_start_hour=cure_start_hour, cure_end_hour=cure_end_hour,
    )
    if is_rework_batch:
        payload["is_rework_batch"] = True
    resp = api_client.create_finishing_batch(payload, PL_H)
    return get_success_data(resp)


def advance_batch(batch_id, target_status) -> dict:
    resp = api_client.set_finishing_batch_status(batch_id, {"target_status": target_status}, PL_H)
    return get_success_data(resp)


def measure_batch(batch_id, sheen_measured_gu, user_id=QA) -> dict:
    resp = api_client.measure_finishing_batch(
        batch_id, {"sheen_measured_gu": sheen_measured_gu}, H("QAInspector", user_id),
    )
    return get_success_data(resp)


def issue_labels(opening_id, roll_id, user_id=LA) -> dict:
    """Issue a label allocation under OCC on the roll's current version."""
    version = get_roll(roll_id)["version"]
    resp = api_client.create_label_allocation(
        create_label_allocation_payload(opening_id, roll_id, version),
        H("LabelAuthority", user_id),
    )
    return get_success_data(resp)


def apply_labels(allocation_id, user_id=PL) -> dict:
    resp = api_client.set_label_allocation_status(
        allocation_id, {"target_status": "APPLIED"}, H("ProductionLead", user_id),
    )
    return get_success_data(resp)


def verify_labels(allocation_id, user_id=QA) -> dict:
    resp = api_client.set_label_allocation_status(
        allocation_id, {"target_status": "VERIFIED"}, H("QAInspector", user_id),
    )
    return get_success_data(resp)


def void_labels(allocation_id, user_id=LA) -> dict:
    resp = api_client.set_label_allocation_status(
        allocation_id, {"target_status": "VOIDED"}, H("LabelAuthority", user_id),
    )
    return get_success_data(resp)


def retire_roll(roll_id, user_id=LA) -> dict:
    resp = api_client.set_fire_label_roll_status(
        roll_id, {"target_status": "RETIRED"}, H("LabelAuthority", user_id),
    )
    return get_success_data(resp)


def assign(trip_id, opening_id) -> dict:
    resp = api_client.assign_opening(trip_id, {"opening_id": opening_id}, SC_H)
    return get_success_data(resp)


def unassign(trip_id, opening_id) -> dict:
    resp = api_client.unassign_opening(trip_id, {"opening_id": opening_id}, SC_H)
    return get_success_data(resp)


def set_trip_status(trip_id, target_status) -> dict:
    resp = api_client.set_delivery_trip_status(trip_id, {"target_status": target_status}, SC_H)
    return get_success_data(resp)


def report_punch(opening_id, category="TRANSIT_DAMAGE", severity="MINOR",
                 description="deficiency", role="QAInspector", user_id="qa-9") -> dict:
    resp = api_client.create_punch_item(
        create_punch_item_payload(
            opening_id, category=category, severity=severity, description=description,
        ),
        H(role, user_id),
    )
    return get_success_data(resp)


def set_punch_status(punch_id, target_status, role, user_id) -> dict:
    resp = api_client.set_punch_item_status(
        punch_id, {"target_status": target_status}, H(role, user_id),
    )
    return get_success_data(resp)


def triage_punch(punch_id, user_id=QA) -> dict:
    return set_punch_status(punch_id, "TRIAGED", "QAInspector", user_id)


def authorize_rework(punch_id, user_id=PM) -> dict:
    return set_punch_status(punch_id, "REWORK_AUTHORIZED", "PlantManager", user_id)


def verify_punch(punch_id, user_id=QA) -> dict:
    return set_punch_status(punch_id, "VERIFIED", "QAInspector", user_id)


def reject_punch(punch_id, user_id=QA) -> dict:
    return set_punch_status(punch_id, "REJECTED_INVALID", "QAInspector", user_id)


def begin_rework(punch_id, rework_batch_id=None) -> dict:
    payload = {}
    if rework_batch_id is not None:
        payload["rework_batch_id"] = rework_batch_id
    resp = api_client.begin_rework(punch_id, payload, PL_H)
    return get_success_data(resp)


def resolve_punch(punch_id, user_id=PL) -> dict:
    resp = api_client.resolve_punch_item(punch_id, H("ProductionLead", user_id))
    return get_success_data(resp)


def accept_opening(opening_id, user_id=QA) -> dict:
    resp = api_client.accept_opening(opening_id, H("QAInspector", user_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: composite lifecycle drivers
# ---------------------------------------------------------------------------

def setup_approved_order(*, project=None, contract_code="CC-1", name="P",
                         site_address="1 Main St",
                         species="PAINT_GRADE", finish_system="PAINT", sheen_target="MATTE",
                         hardware_prep_mode="INSTALLER_PREP", fire_rating_required="NONE",
                         order_code="O-1", profile_code="PR-1",
                         template=None, template_code="T-1", template_fire_rated=True,
                         openings=({"opening_no": "1", "leaf_count": 1, "fire_rating": "NONE",
                                    "required_on_site_date": "2026-10-01"},),
                         submitter=EST, approver=ARCH) -> dict:
    """Project + order + openings, driven DRAFT -> CONFIGURED -> SUBMITTED -> APPROVED.

    Returns ctx: {project, order, openings, drawing, template}.
    """
    if project is None:
        project = make_project(name=name, site_address=site_address, contract_code=contract_code)
    if hardware_prep_mode == "TEMPLATE_PREP" and template is None:
        template = make_template(template_code=template_code,
                                 fire_rated_compatible=template_fire_rated)
    order = make_order(
        project["id"], order_code=order_code, species=species, profile_code=profile_code,
        finish_system=finish_system, sheen_target=sheen_target,
        hardware_prep_mode=hardware_prep_mode, fire_rating_required=fire_rating_required,
        hardware_template_id=template["id"] if template else None,
    )
    made_openings = [
        make_opening(order["id"], **spec) for spec in openings
    ]
    order = configure_order(order["id"])
    drawing = make_drawing(order["id"])
    submit_drawing(drawing["id"], user_id=submitter)
    drawing = approve_drawing(drawing["id"], user_id=approver)
    order = get_order(order["id"])
    return {
        "project": project, "order": order, "openings": made_openings,
        "drawing": drawing, "template": template,
    }


def setup_order_in_production(*, machine_code="M-1", machine_species=None,
                              slot_start=8, slot_end=10, estimated_minutes=60,
                              **approved_kwargs) -> dict:
    """setup_approved_order + machine + program booked/completed/RELEASED + IN_PRODUCTION.

    Adds keys: machine, program, slot.
    """
    ctx = setup_approved_order(**approved_kwargs)
    if machine_species is None:
        machine_species = [ctx["order"]["species"]]
    ctx["machine"] = make_machine(machine_code=machine_code, supported_species=machine_species)
    ctx["program"] = make_program(ctx["drawing"]["id"], ctx["order"]["id"],
                                  estimated_minutes=estimated_minutes)
    ctx["slot"] = book_slot(ctx["program"]["id"], ctx["machine"]["id"],
                            start_hour=slot_start, end_hour=slot_end)
    complete_slot(ctx["slot"]["id"])
    ctx["program"] = release_program(ctx["program"]["id"])
    ctx["order"] = set_order_status(ctx["order"]["id"], "IN_PRODUCTION")
    return ctx


def setup_order_finishing(*, machine_code="M-1", machine_species=None,
                          slot_start=8, slot_end=10, estimated_minutes=60,
                          **approved_kwargs) -> dict:
    """setup_order_in_production + every opening MACHINED + order FINISHING."""
    ctx = setup_order_in_production(
        machine_code=machine_code, machine_species=machine_species,
        slot_start=slot_start, slot_end=slot_end, estimated_minutes=estimated_minutes,
        **approved_kwargs,
    )
    ctx["openings"] = [machine_opening(op["id"]) for op in ctx["openings"]]
    ctx["order"] = set_order_status(ctx["order"]["id"], "FINISHING")
    return ctx


def setup_openings_finished(*, booth_code="B-1", booth_capacity=2,
                            cure_start=10, cure_end=16, measured_gu=None,
                            **finishing_kwargs) -> dict:
    """setup_order_finishing + booth + one batch walked to PASSED, so every
    non-cancelled opening of the order sits in FINISHED.

    Adds keys: booth, batch.
    """
    ctx = setup_order_finishing(**finishing_kwargs)
    ctx["booth"] = make_booth(booth_code=booth_code, capacity=booth_capacity)
    ctx["batch"] = make_batch(ctx["order"]["id"], ctx["booth"]["id"],
                              cure_start_hour=cure_start, cure_end_hour=cure_end)
    advance_batch(ctx["batch"]["id"], "SPRAYED")
    advance_batch(ctx["batch"]["id"], "CURED")
    if measured_gu is None:
        measured_gu = SHEEN_TARGET_GU[ctx["order"]["sheen_target"]]
    ctx["batch"] = measure_batch(ctx["batch"]["id"], measured_gu)
    ctx["openings"] = [get_opening(op["id"]) for op in ctx["openings"]]
    return ctx


def setup_openings_staged(*, stage_all=True, **finished_kwargs) -> dict:
    """setup_openings_finished + stage every (unrated) opening."""
    ctx = setup_openings_finished(**finished_kwargs)
    if stage_all:
        ctx["openings"] = [stage_opening(op["id"]) for op in ctx["openings"]]
    return ctx


def setup_delivered_opening(*, trip_code="T-1", truck_capacity_leaves=4,
                            departure_date="2026-10-02", site_arrival_date="2026-10-04",
                            **staged_kwargs) -> dict:
    """setup_openings_staged (single-opening orders) + trip assigned, DEPARTED,
    DELIVERED. Adds key: trip.
    """
    ctx = setup_openings_staged(**staged_kwargs)
    ctx["trip"] = make_trip(ctx["project"]["id"], trip_code=trip_code,
                            truck_capacity_leaves=truck_capacity_leaves,
                            departure_date=departure_date,
                            site_arrival_date=site_arrival_date)
    for op in ctx["openings"]:
        assign(ctx["trip"]["id"], op["id"])
    ctx["trip"] = set_trip_status(ctx["trip"]["id"], "DEPARTED")
    ctx["trip"] = set_trip_status(ctx["trip"]["id"], "DELIVERED")
    ctx["openings"] = [get_opening(op["id"]) for op in ctx["openings"]]
    return ctx


def setup_rated_labeled_opening(*, roll_series="UL_20MIN", roll_capacity=2,
                                issuer=LA, applier=PL, verifier=QA,
                                stage=False, **finished_kwargs) -> dict:
    """setup_openings_finished for a rated order + roll + one allocation walked
    ISSUED -> APPLIED -> VERIFIED on the first opening (which ends LABELED).

    Adds keys: roll, allocation. With stage=True the opening is also STAGED.
    """
    ctx = setup_openings_finished(**finished_kwargs)
    ctx["roll"] = make_roll(label_series=roll_series, serial_capacity=roll_capacity)
    ctx["allocation"] = issue_labels(ctx["openings"][0]["id"], ctx["roll"]["id"], user_id=issuer)
    ctx["allocation"] = apply_labels(ctx["allocation"]["id"], user_id=applier)
    ctx["allocation"] = verify_labels(ctx["allocation"]["id"], user_id=verifier)
    if stage:
        ctx["openings"][0] = stage_opening(ctx["openings"][0]["id"])
    ctx["openings"] = [get_opening(op["id"]) for op in ctx["openings"]]
    return ctx


def setup_rated_delivered_opening(*, trip_code="T-1", truck_capacity_leaves=5,
                                  departure_date="2026-10-08", site_arrival_date="2026-10-10",
                                  **labeled_kwargs) -> dict:
    """setup_rated_labeled_opening with the opening STAGED, then trip assigned,
    DEPARTED, DELIVERED. Adds key: trip."""
    labeled_kwargs.setdefault("stage", True)
    ctx = setup_rated_labeled_opening(**labeled_kwargs)
    ctx["trip"] = make_trip(ctx["project"]["id"], trip_code=trip_code,
                            truck_capacity_leaves=truck_capacity_leaves,
                            departure_date=departure_date,
                            site_arrival_date=site_arrival_date)
    assign(ctx["trip"]["id"], ctx["openings"][0]["id"])
    ctx["trip"] = set_trip_status(ctx["trip"]["id"], "DEPARTED")
    ctx["trip"] = set_trip_status(ctx["trip"]["id"], "DELIVERED")
    ctx["openings"] = [get_opening(op["id"]) for op in ctx["openings"]]
    return ctx

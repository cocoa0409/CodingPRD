"""FormularyProduct, DressingProtocol and OstomyEducationPlan (12 endpoints).

Filing a protocol drives the ConsultRequest to PLAN_ACTIVE; the education plan
walks ACTIVE -> TEACH_BACK_PASSED -> FOLLOWUP_SCHEDULED, collapsing the
SUPPLIES_TRANSITIONED hop into the same call as the scaffold prescribes.
"""

import calc
from core import (
    READ_ROLES,
    ROLE_DIRECTOR,
    ROLE_WOC_NURSE,
    TEACH_BACK_PASS_SCORE,
    F,
    apply_filters,
    authorize,
    bump,
    chrono,
    dt_of,
    fail,
    filters,
    insert,
    must,
    new_row,
    now,
    ok,
    ok_list,
    pagination,
    paginate,
    parse_input,
    public,
    public_list,
    rows_of,
    store,
)
from flask import Blueprint

bp = Blueprint("formulary", __name__)

CATEGORIES = ("FOAM", "HYDROCOLLOID", "ALGINATE", "SILVER_ANTIMICROBIAL",
              "OSTOMY_BARRIER", "SKIN_PROTECTANT")
TIERS = ("PREFERRED", "RESTRICTED", "NON_FORMULARY")
PRODUCT_STATUSES = ("ACTIVE", "ARCHIVED")
PROTOCOL_STATUSES = ("ACTIVE", "SUPERSEDED", "VOIDED")
PLAN_STATUSES = ("ACTIVE", "TEACH_BACK_PASSED", "SUPPLIES_TRANSITIONED",
                 "FOLLOWUP_SCHEDULED", "CLOSED_INCOMPLETE")
PROTOCOL_CONSULT_STATES = ("ASSESSED", "PLAN_ACTIVE")


# ---------------------------------------------------------------------------
# FormularyProduct
# ---------------------------------------------------------------------------
@bp.post("/formulary-products")
def create_product():
    authorize(ROLE_DIRECTOR)
    body = parse_input([
        F("sku", "string", required=True, min_len=3, max_len=24),
        F("name", "string", required=True, min_len=1, max_len=120),
        F("category", "enum", required=True, enum=CATEGORIES),
        F("unit_cost_cents", "int", required=True, minimum=0, maximum=1000000),
        F("formulary_tier", "enum", required=True, enum=TIERS),
    ])
    for existing in rows_of("formulary_products"):
        if existing.get("sku") == body["sku"]:
            fail("ERR_DUPLICATE_NATURAL_KEY", "sku is already in use.")
    product = new_row(
        "prod",
        sku=body["sku"],
        name=body["name"],
        category=body["category"],
        unit_cost_cents=body["unit_cost_cents"],
        formulary_tier=body["formulary_tier"],
        status="ACTIVE",
    )
    insert("formulary_products", product)
    return ok(public(product), 201)


@bp.get("/formulary-products")
def list_products():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({
        "category": CATEGORIES,
        "formulary_tier": TIERS,
        "status": PRODUCT_STATUSES,
    })
    rows = chrono(apply_filters(rows_of("formulary_products"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/formulary-products/<product_id>")
def get_product(product_id):
    authorize(*READ_ROLES)
    return ok(public(must("formulary_products", product_id)))


@bp.post("/formulary-products/<product_id>/archive")
def archive_product(product_id):
    authorize(ROLE_DIRECTOR)
    parse_input([F("reason", "string", required=True, min_len=1, max_len=2000)])
    product = must("formulary_products", product_id)
    if product.get("status") != "ACTIVE":
        fail("ERR_RESOURCE_NOT_ACTIVE", "Product is already archived.")
    product["status"] = "ARCHIVED"
    bump(product)
    # Existing ACTIVE protocols are deliberately left standing.
    return ok(public(product))


# ---------------------------------------------------------------------------
# DressingProtocol
# ---------------------------------------------------------------------------
def latest_assessment_for(consult_id):
    rows = [a for a in rows_of("skin_assessments")
            if a.get("consult_request_id") == consult_id]
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("created_at"), r.get("_seq", 0)))
    return rows[-1]


@bp.post("/dressing-protocols")
def create_protocol():
    authorize(ROLE_WOC_NURSE)
    body = parse_input([
        F("consult_request_id", "id", required=True),
        F("formulary_product_id", "id", required=True),
        F("change_frequency_hours", "int", required=True, minimum=8, maximum=168),
        F("units_per_change", "int", required=True, minimum=1, maximum=20),
        F("justification", "string", min_len=1, max_len=500, nullable=True),
    ])
    consult = must("consult_requests", body["consult_request_id"])
    product = must("formulary_products", body["formulary_product_id"])
    # Rung 10 — the consult must be assessed (or already carry a protocol).
    if consult.get("status") not in PROTOCOL_CONSULT_STATES:
        fail("ERR_CONSULT_INVALID_STATE")
    # Rung 17 — an archived product may not back a new protocol.
    if product.get("status") != "ACTIVE":
        fail("ERR_RESOURCE_NOT_ACTIVE", "Formulary product is archived.")
    # Rung 34 — the staging must be validated and no dispute hold outstanding.
    if consult.get("protocol_hold") is True:
        fail("ERR_STAGE_NOT_VALIDATED",
             "A disputed assessment holds protocol filing on this consult.")
    latest = latest_assessment_for(consult["id"])
    if latest is None or latest.get("validation_status") != "VALIDATED":
        fail("ERR_STAGE_NOT_VALIDATED",
             "The most recent skin assessment for this consult is not VALIDATED.")
    # Rung 56 — off-formulary spend needs a written justification.
    justification = body.get("justification")
    if product.get("formulary_tier") == "NON_FORMULARY":
        if justification is None or not str(justification).strip():
            fail("ERR_NON_FORMULARY_JUSTIFICATION_REQUIRED")

    changes, weekly_cost = calc.dressing_protocol_weekly_cost(
        body["change_frequency_hours"], product["unit_cost_cents"],
        body["units_per_change"], product["formulary_tier"])
    protocol = new_row(
        "protocol",
        consult_request_id=consult["id"],
        formulary_product_id=product["id"],
        change_frequency_hours=body["change_frequency_hours"],
        units_per_change=body["units_per_change"],
        justification=justification,
        changes_per_week=changes,
        weekly_cost_cents=weekly_cost,
        status="ACTIVE",
    )
    insert("dressing_protocols", protocol)
    # Any prior ACTIVE protocol on the same consult is superseded.
    for other in rows_of("dressing_protocols"):
        if other["id"] == protocol["id"]:
            continue
        if other.get("consult_request_id") != consult["id"]:
            continue
        if other.get("status") == "ACTIVE":
            other["status"] = "SUPERSEDED"
            bump(other)
    # ASSESSED -> PLAN_ACTIVE, or the PLAN_ACTIVE revision self-transition.
    consult["status"] = "PLAN_ACTIVE"
    bump(consult)
    return ok(public(protocol), 201)


@bp.get("/dressing-protocols")
def list_protocols():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({
        "consult_request_id": None,
        "formulary_product_id": None,
        "status": PROTOCOL_STATUSES,
    })
    rows = chrono(apply_filters(rows_of("dressing_protocols"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/dressing-protocols/<protocol_id>")
def get_protocol(protocol_id):
    authorize(*READ_ROLES)
    return ok(public(must("dressing_protocols", protocol_id)))


# ---------------------------------------------------------------------------
# OstomyEducationPlan
# ---------------------------------------------------------------------------
@bp.post("/ostomy-education-plans")
def create_plan():
    authorize(ROLE_WOC_NURSE)
    body = parse_input([
        F("consult_request_id", "id", required=True),
        F("patient_id", "id", required=True),
    ])
    consult = must("consult_requests", body["consult_request_id"])
    patient = must("patients", body["patient_id"])
    # Rung 6 — the plan must hang off the consult's own patient.
    if patient["id"] != consult.get("patient_id"):
        fail("ERR_ENTITY_LINK_MISMATCH",
             "patient_id must equal the consult's patient_id.")
    # Rung 10 — the consult must be assessed.
    if consult.get("status") not in PROTOCOL_CONSULT_STATES:
        fail("ERR_CONSULT_INVALID_STATE")
    # Rung 64 — an ostomy plan needs an ostomy patient on an OSTOMY consult.
    if patient.get("ostomy_present") is not True:
        fail("ERR_OSTOMY_PLAN_NOT_ELIGIBLE",
             "Patient does not carry an ostomy.")
    if consult.get("consult_type") != "OSTOMY":
        fail("ERR_OSTOMY_PLAN_NOT_ELIGIBLE",
             "Consult type must be OSTOMY.")
    plan = new_row(
        "plan",
        consult_request_id=consult["id"],
        patient_id=patient["id"],
        sessions_completed=0,
        teach_back_score=None,
        supply_transition_status="PENDING",
        followup_appointment_at=None,
        status="ACTIVE",
    )
    insert("ostomy_education_plans", plan)
    return ok(public(plan), 201)


@bp.get("/ostomy-education-plans")
def list_plans():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({
        "consult_request_id": None,
        "patient_id": None,
        "status": PLAN_STATUSES,
        "supply_transition_status": ("PENDING", "TRANSITIONED"),
    })
    rows = chrono(apply_filters(rows_of("ostomy_education_plans"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/ostomy-education-plans/<plan_id>")
def get_plan(plan_id):
    authorize(*READ_ROLES)
    return ok(public(must("ostomy_education_plans", plan_id)))


@bp.post("/ostomy-education-plans/<plan_id>/sessions")
def record_session(plan_id):
    authorize(ROLE_WOC_NURSE)
    body = parse_input([
        F("teach_back_score", "int", required=True, minimum=0, maximum=100),
    ])
    plan = must("ostomy_education_plans", plan_id)
    if plan.get("status") != "ACTIVE":
        fail("ERR_OSTOMY_PLAN_NOT_ELIGIBLE",
             "Sessions may only be recorded on an ACTIVE plan.")
    plan["sessions_completed"] = int(plan.get("sessions_completed") or 0) + 1
    plan["teach_back_score"] = body["teach_back_score"]
    if body["teach_back_score"] >= TEACH_BACK_PASS_SCORE:
        plan["status"] = "TEACH_BACK_PASSED"
    bump(plan)
    return ok(public(plan))


@bp.post("/ostomy-education-plans/<plan_id>/transition-supplies")
def transition_supplies(plan_id):
    authorize(ROLE_WOC_NURSE)
    body = parse_input([F("followup_appointment_at", "datetime", required=True)])
    plan = must("ostomy_education_plans", plan_id)
    if plan.get("status") != "TEACH_BACK_PASSED":
        fail("ERR_OSTOMY_PLAN_NOT_ELIGIBLE",
             "Teach-back must be passed before supplies are transitioned.")
    if dt_of(body["followup_appointment_at"]) <= dt_of(now()):
        fail("ERR_OSTOMY_PLAN_NOT_ELIGIBLE",
             "followup_appointment_at must be strictly in the future.")
    plan["supply_transition_status"] = "TRANSITIONED"
    plan["followup_appointment_at"] = body["followup_appointment_at"]
    # SUPPLIES_TRANSITIONED is traversed and left in the same call, so the plan
    # version moves exactly once.
    plan["status"] = "FOLLOWUP_SCHEDULED"
    bump(plan)
    patient = store("patients").get(plan.get("patient_id"))
    if patient is not None:
        patient["pending_outpatient_followup_count"] = int(
            patient.get("pending_outpatient_followup_count") or 0) + 1
        bump(patient)
    return ok(public(plan))

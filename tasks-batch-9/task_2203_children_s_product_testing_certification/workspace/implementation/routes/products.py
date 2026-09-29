"""Products, the bill of materials and the scoping fork (PRD 3.3, 3.4)."""

from flask import Blueprint

import auth
import db
import paging
import refs
import response
import validation
from errors import ApiError
from services import calc, engine

bp = Blueprint("products", __name__)

CERTIFICATION_STATES = {
    "DRAFT",
    "SCOPED",
    "EVIDENCE_RELIANCE",
    "FULL_TEST_PROGRAM",
    "EVIDENCE_COMPLETE",
    "CERTIFIED",
    "SUSPENDED",
    "REMEDIATION",
    "ARCHIVED",
}
POSTURES = {"UNSCOPED", "CLEARED", "RESTRICTED", "SUSPENDED"}
EVIDENCE_PATHS = {"COMPONENT_RELIANCE", "FULL_PRODUCT_TEST"}
MATERIAL_CLASSES = {
    "PAINTED_COATING",
    "PLASTICIZED_PLASTIC",
    "ACCESSIBLE_METAL",
    "TEXTILE",
    "RIGID_UNPAINTED_PLASTIC",
}
RELIANCE_STATUSES = {"PENDING", "VALID", "SUPERSEDED"}

PRODUCT_READ_ROLES = (
    "ComplianceAdministrator",
    "TestCoordinator",
    "CertificationOfficer",
    "DistributionManager",
)
PART_READ_ROLES = (
    "ComplianceAdministrator",
    "TestCoordinator",
    "CertificationOfficer",
    "SupplierUser",
)


def guard_not_archived(product):
    if product["certification_state"] == "ARCHIVED":
        raise ApiError("ERR_PRODUCT_ARCHIVED")


@bp.post("/products")
def create_product():
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    category_id = validation.id_field(body, "category_id")
    model_name = validation.string_field(body, "model_name", min_len=1, max_len=160)
    manufacture_site_code = validation.string_field(
        body, "manufacture_site_code", min_len=2, max_len=12,
        pattern=validation.RE_UPPER_ALNUM,
    )
    projected_annual_units = validation.int_field(
        body, "projected_annual_units", minimum=1
    )
    testing_budget_cents = validation.int_field(
        body, "testing_budget_cents", minimum=0, required=False, default=2000000
    )
    category = refs.category(category_id)
    row = db.insert(
        "products",
        {
            "category_id": category["id"],
            "model_name": model_name,
            "manufacture_site_code": manufacture_site_code,
            "projected_annual_units": projected_annual_units,
            "testing_budget_cents": testing_budget_cents,
            "certification_state": "DRAFT",
            "evidence_path": None,
            "compliance_posture": "UNSCOPED",
            "required_rule_ids": [],
            "risk_weighted_gap_score": 0,
            "units_held": 0,
            "units_released": 0,
            "units_stopped": 0,
            "units_destroyed": 0,
            "material_change_count": 0,
        },
    )
    return response.object_response(db.serialize("products", row), 201)


@bp.get("/products/<product_id>")
def get_product(product_id):
    auth.require_roles(*PRODUCT_READ_ROLES)
    row = refs.product(product_id)
    return response.object_response(db.serialize("products", row))


@bp.get("/products")
def list_products():
    auth.require_roles(*PRODUCT_READ_ROLES)
    category_id = validation.query_string("category_id")
    certification_state = validation.query_enum(
        "certification_state", CERTIFICATION_STATES
    )
    compliance_posture = validation.query_enum("compliance_posture", POSTURES)
    return paging.build(
        "products",
        [
            paging.eq_filter("category_id", category_id),
            paging.eq_filter("certification_state", certification_state),
            paging.eq_filter("compliance_posture", compliance_posture),
        ],
    )


@bp.get("/products/<product_id>/compliance-summary")
def compliance_summary(product_id):
    auth.require_roles(*PRODUCT_READ_ROLES)
    product = refs.product(product_id)

    snapshot = dict(product)
    snapshot["required_rule_ids"] = calc.derive_required_rule_ids(product)
    snapshot["risk_weighted_gap_score"] = calc.risk_weighted_gap_score(snapshot)
    snapshot["compliance_posture"] = calc.compliance_posture(snapshot)

    covered = []
    uncovered = []
    for rule_id in snapshot["required_rule_ids"]:
        if calc._rule_covered(snapshot, rule_id):
            covered.append(rule_id)
        else:
            uncovered.append(rule_id)

    open_case_count = len(
        [
            c
            for c in db.find("noncompliance_cases", product_id=product["id"])
            if c["case_state"] in calc.OPEN_CASE_STATES_FOR_SCORE
        ]
    )
    resample_due_plan_count = len(
        [
            p
            for p in db.find("sampling_plans", product_id=product["id"])
            if p["plan_state"] == "RESAMPLE_DUE"
        ]
    )
    batches = db.find("production_batches", product_id=product["id"])
    units_total_produced = sum(b["quantity"] for b in batches)
    ledger = dict(product)
    calc.recompute_distribution_ledger(ledger)
    counters = {
        "units_held": ledger["units_held"],
        "units_released": ledger["units_released"],
        "units_stopped": ledger["units_stopped"],
        "units_destroyed": ledger["units_destroyed"],
    }
    data = {
        "product_id": product["id"],
        "required_rule_ids": snapshot["required_rule_ids"],
        "covered_rule_ids": covered,
        "uncovered_rule_ids": uncovered,
        "risk_weighted_gap_score": snapshot["risk_weighted_gap_score"],
        "compliance_posture": snapshot["compliance_posture"],
        "open_case_count": open_case_count,
        "resample_due_plan_count": resample_due_plan_count,
        "units_held": counters["units_held"],
        "units_released": counters["units_released"],
        "units_stopped": counters["units_stopped"],
        "units_destroyed": counters["units_destroyed"],
        "units_total_produced": units_total_produced,
        "ledger_balanced": sum(counters.values()) == units_total_produced,
    }
    return response.object_response(data)


@bp.post("/products/<product_id>/submit-for-certification")
def submit_for_certification(product_id):
    auth.require_roles("TestCoordinator")
    body = validation.json_body()
    evidence_path = validation.enum_field(body, "evidence_path", EVIDENCE_PATHS)
    product = refs.product(product_id)
    guard_not_archived(product)
    if product["certification_state"] != "DRAFT":
        raise ApiError("ERR_PRODUCT_STATE_INVALID")

    parts = db.find("component_parts", product_id=product["id"])
    derived = calc.derive_required_rule_ids(product)
    if not parts:
        raise ApiError("ERR_NO_COMPONENT_PARTS")
    if not derived:
        raise ApiError("ERR_NO_APPLICABLE_RULES")
    if evidence_path == "COMPONENT_RELIANCE":
        for rule_id in derived:
            rule = db.get("applicable_rules", rule_id)
            if rule is not None and not rule["component_reliance_allowed"]:
                raise ApiError("ERR_COMPONENT_RELIANCE_NOT_ALLOWED")

    # Scoping hop.
    product["evidence_path"] = evidence_path
    product["required_rule_ids"] = derived
    product["certification_state"] = "SCOPED"
    engine.recompute_product_derived(product)
    engine.bump("products", product)

    # Automatic fork hop; a second version increment in its own right.
    if evidence_path == "COMPONENT_RELIANCE":
        product["certification_state"] = "EVIDENCE_RELIANCE"
        for part in parts:
            if part["reliance_status"] == "PENDING":
                part["reliance_status"] = "VALID"
                engine.bump("component_parts", part)
    else:
        product["certification_state"] = "FULL_TEST_PROGRAM"
    engine.recompute_product_derived(product)
    engine.bump("products", product)
    return response.object_response(db.serialize("products", product))


@bp.post("/products/<product_id>/archive")
def archive_product(product_id):
    auth.require_roles("ComplianceAdministrator")
    product = refs.product(product_id)
    guard_not_archived(product)
    if product["certification_state"] != "CERTIFIED":
        raise ApiError("ERR_PRODUCT_STATE_INVALID")
    for batch in db.find("production_batches", product_id=product["id"]):
        if batch["distribution_state"] in ("RELEASED", "STOP_DISTRIBUTION"):
            raise ApiError("ERR_BATCH_STATE_INVALID")

    product["certification_state"] = "ARCHIVED"
    for plan in db.find("sampling_plans", product_id=product["id"]):
        if plan["plan_state"] in ("DRAFT", "ACTIVE", "RESAMPLE_DUE"):
            plan["plan_state"] = "SUPERSEDED"
            engine.bump("sampling_plans", plan)
    product["compliance_posture"] = "UNSCOPED"
    engine.bump("products", product)
    return response.object_response(db.serialize("products", product))


# --------------------------------------------------------------------------
# Component parts
# --------------------------------------------------------------------------

@bp.post("/products/<product_id>/component-parts")
def create_component_part(product_id):
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    supplier_id = validation.id_field(body, "supplier_id")
    part_name = validation.string_field(body, "part_name", min_len=1, max_len=120)
    material_class = validation.enum_field(body, "material_class", MATERIAL_CLASSES)
    accessible_to_child = validation.bool_field(
        body, "accessible_to_child", required=False, default=True
    )
    small_part_when_detached = validation.bool_field(
        body, "small_part_when_detached", required=False, default=False
    )
    product = refs.product(product_id)
    supplier = refs.supplier(supplier_id)
    guard_not_archived(product)

    row = db.insert(
        "component_parts",
        {
            "product_id": product["id"],
            "supplier_id": supplier["id"],
            "part_name": part_name,
            "material_class": material_class,
            "accessible_to_child": accessible_to_child,
            "small_part_when_detached": small_part_when_detached,
            "reliance_status": "PENDING",
            "last_material_change_at": None,
        },
    )
    if product["certification_state"] in ("DRAFT", "SCOPED"):
        product["required_rule_ids"] = calc.derive_required_rule_ids(product)
        if product["certification_state"] != "DRAFT":
            engine.recompute_product_derived(product)
    engine.bump("products", product)
    return response.object_response(db.serialize("component_parts", row), 201)


@bp.get("/component-parts/<part_id>")
def get_component_part(part_id):
    auth.require_roles(*PART_READ_ROLES)
    row = refs.part(part_id)
    return response.object_response(db.serialize("component_parts", row))


@bp.get("/component-parts")
def list_component_parts():
    auth.require_roles(*PART_READ_ROLES)
    product_id = validation.query_string("product_id")
    supplier_id = validation.query_string("supplier_id")
    reliance_status = validation.query_enum("reliance_status", RELIANCE_STATUSES)
    return paging.build(
        "component_parts",
        [
            paging.eq_filter("product_id", product_id),
            paging.eq_filter("supplier_id", supplier_id),
            paging.eq_filter("reliance_status", reliance_status),
        ],
    )

"""Jurisdictions, stores, aisles, associates, training, accountability, clock."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import services
import views
from auth import actor_id, roles
from core import (
    ACCOUNTABILITY_VARIANTS,
    ACTION_TRIGGER_CODES,
    ACTION_TYPES,
    ALL_ROLES,
    ASSOCIATE_ROLE_CODES,
    CERTIFICATION_VALID_DAYS,
    DB,
    POSTURES,
    RATE_VARIANTS,
    REFUND_POLICIES,
    REMEDIAL_MODULE_CODE,
    ROUNDING_MODES,
    R_COMPLIANCE_OFFICER,
    R_CUSTOMER_SERVICE_DESK,
    R_LABEL_ASSOCIATE,
    R_PRICE_AUDITOR,
    R_PRICING_ADMIN,
    R_STORE_MANAGER,
    TRAINING_PASS_SCORE_PCT,
    TRAINING_STATUSES,
    UOM_RULES,
    apply_changes,
    arg_enum,
    arg_str,
    body,
    fail,
    insert,
    iso,
    must,
    now,
    ok,
    opt_bool,
    opt_enum,
    opt_int,
    opt_num,
    opt_str,
    opt_str_array,
    pagination,
    parse_dt,
    req_dt,
    req_enum,
    req_num,
    req_str,
    rows,
    set_clock,
    touch,
)

bp = Blueprint("estate", __name__)

READ_ALL = ALL_ROLES
STAFF_READ = [
    R_PRICING_ADMIN,
    R_COMPLIANCE_OFFICER,
    R_STORE_MANAGER,
    R_PRICE_AUDITOR,
    R_LABEL_ASSOCIATE,
]
ADMIN_READ = [R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER]


# ---------------------------------------------------------------- jurisdictions
def rulebook_fields(data, creating):
    out = {}
    if creating or "unit_price_required" in data:
        value = opt_bool(data, "unit_price_required", True if creating else None)
        if value is not None:
            out["unit_price_required"] = value
    if creating or "unit_price_uom_rule" in data:
        value = opt_enum(
            data, "unit_price_uom_rule", UOM_RULES,
            "PER_UNIT_MEASURE_CANONICAL" if creating else None,
        )
        if value is not None:
            out["unit_price_uom_rule"] = value
    if creating or "unit_price_decimal_places" in data:
        value = opt_int(data, "unit_price_decimal_places", 2, 3, 2 if creating else None)
        if value is not None:
            out["unit_price_decimal_places"] = value
    if creating or "unit_price_rounding" in data:
        value = opt_enum(
            data, "unit_price_rounding", ROUNDING_MODES,
            "ROUND_HALF_UP" if creating else None,
        )
        if value is not None:
            out["unit_price_rounding"] = value
    if creating or "scanner_error_rate_threshold_pct" in data:
        value = opt_num(
            data, "scanner_error_rate_threshold_pct", None, 100, 2,
            2.0 if creating else None,
        )
        if value is not None:
            if value <= 0:
                fail("ERR_INVALID_REQUEST", "scanner_error_rate_threshold_pct must be > 0")
            out["scanner_error_rate_threshold_pct"] = value
    if creating or "default_rate_variant" in data:
        value = opt_enum(
            data, "default_rate_variant", RATE_VARIANTS, "GROSS_MISMATCH" if creating else None
        )
        if value is not None:
            out["default_rate_variant"] = value
    if creating or "overcharge_refund_policy" in data:
        value = opt_enum(
            data, "overcharge_refund_policy", REFUND_POLICIES,
            "REFUND_DIFFERENCE_ONLY" if creating else None,
        )
        if value is not None:
            out["overcharge_refund_policy"] = value
    if creating or "refund_fixed_bonus_cents" in data:
        value = opt_int(data, "refund_fixed_bonus_cents", 0, None, 0 if creating else None)
        if value is not None:
            out["refund_fixed_bonus_cents"] = value
    for field, default in (
        ("refund_cap_cents", 5000),
        ("refund_budget_per_audit_cents", 100000),
        ("penalty_per_violation_cents", 5000),
        ("penalty_max_cents", 2000000),
    ):
        if creating or field in data:
            value = opt_int(data, field, 1, None, default if creating else None)
            if value is not None:
                out[field] = value
    if creating or "signage_disclosure_codes" in data:
        value = opt_str_array(
            data, "signage_disclosure_codes", 0, None, True, 1, [] if creating else None
        )
        if value is not None:
            out["signage_disclosure_codes"] = value
    if creating or "grace_period_hours" in data:
        value = opt_int(data, "grace_period_hours", 0, None, 48 if creating else None)
        if value is not None:
            out["grace_period_hours"] = value
    if creating or "accountability_variant" in data:
        value = opt_enum(
            data, "accountability_variant", ACCOUNTABILITY_VARIANTS,
            "OCCURRENCE_WEIGHTED" if creating else None,
        )
        if value is not None:
            out["accountability_variant"] = value
    return out


@bp.post("/price-integrity/jurisdictions")
@roles(R_PRICING_ADMIN)
def create_jurisdiction():
    data = body()
    code = req_str(data, "code", 2, 16, r"[A-Z0-9\-]+")
    name = req_str(data, "name", 1, 255)
    fields = rulebook_fields(data, True)
    if any(r["code"] == code for r in DB["jurisdictions"].values()):
        fail("ERR_DUPLICATE_RESOURCE", "jurisdiction code already registered")
    fields["code"] = code
    fields["name"] = name
    return ok(views.jurisdiction(insert("jurisdictions", fields)), 201)


@bp.get("/price-integrity/jurisdictions/<jid>")
@roles(*READ_ALL)
def get_jurisdiction(jid):
    return ok(views.jurisdiction(must("jurisdictions", jid)))


@bp.get("/price-integrity/jurisdictions")
@roles(*ADMIN_READ)
def list_jurisdictions():
    code = arg_str("code")
    limit, offset = pagination()
    items = [r for r in rows("jurisdictions") if code is None or r["code"] == code]
    return views.paged(items, views.jurisdiction, limit, offset)


@bp.patch("/price-integrity/jurisdictions/<jid>")
@roles(R_PRICING_ADMIN)
def amend_jurisdiction(jid):
    data = body()
    changes = rulebook_fields(data, False)
    juris = must("jurisdictions", jid)
    if changes:
        apply_changes(juris, changes)
    services.amend_jurisdiction_cascade(juris)
    return ok(views.jurisdiction(juris))


# ---------------------------------------------------------------- stores
@bp.post("/price-integrity/stores")
@roles(R_PRICING_ADMIN)
def create_store():
    data = body()
    store_number = req_str(data, "store_number", 1, 16)
    name = req_str(data, "name", 1, 255)
    jurisdiction_id = req_str(data, "jurisdiction_id")
    must("jurisdictions", jurisdiction_id)
    if any(r["store_number"] == store_number for r in DB["stores"].values()):
        fail("ERR_DUPLICATE_RESOURCE", "store_number already opened")
    store = insert(
        "stores",
        {
            "store_number": store_number,
            "name": name,
            "jurisdiction_id": jurisdiction_id,
            "compliance_posture": "OPEN",
            "label_backlog_count": 0,
            "open_finding_count": 0,
            "escalated_finding_count": 0,
            "failed_audit_count_30d": 0,
            "signage_violation_count": 0,
            "refund_liability_outstanding_cents": 0,
            "refund_paid_total_cents": 0,
            "cumulative_penalty_exposure_cents": 0,
            "executed_file_count": 0,
        },
    )
    return ok(views.store(store), 201)


@bp.get("/price-integrity/stores/<sid>")
@roles(*READ_ALL)
def get_store(sid):
    return ok(views.store(must("stores", sid)))


@bp.get("/price-integrity/stores")
@roles(*ADMIN_READ)
def list_stores():
    jurisdiction_id = arg_str("jurisdiction_id")
    posture = arg_enum("compliance_posture", POSTURES)
    limit, offset = pagination()
    items = [
        r
        for r in rows("stores")
        if (jurisdiction_id is None or r["jurisdiction_id"] == jurisdiction_id)
        and (posture is None or r["compliance_posture"] == posture)
    ]
    return views.paged(items, views.store, limit, offset)


@bp.get("/price-integrity/stores/<sid>/compliance-summary")
@roles(*ADMIN_READ)
def store_compliance_summary(sid):
    store = must("stores", sid)
    return ok(views.store(services.store_projection(store)))


# ---------------------------------------------------------------- aisles
@bp.post("/price-integrity/stores/<sid>/aisles")
@roles(R_STORE_MANAGER, R_PRICING_ADMIN)
def create_aisle(sid):
    data = body()
    aisle_code = req_str(data, "aisle_code", 1, 8)
    category_code = req_str(data, "category_code", 1, 24, upper=True)
    assigned = opt_str(data, "assigned_associate_id")
    store = must("stores", sid)
    associate = None
    if assigned is not None:
        associate = must("associates", assigned)
    if any(
        r["store_id"] == sid and r["aisle_code"] == aisle_code
        for r in DB["aisles"].values()
    ):
        fail("ERR_DUPLICATE_RESOURCE", "aisle_code already used in this store")
    if associate is not None and associate["store_id"] != store["id"]:
        fail("ERR_ASSOCIATE_STORE_MISMATCH", "associate belongs to another store")
    aisle = insert(
        "aisles",
        {
            "store_id": store["id"],
            "aisle_code": aisle_code,
            "category_code": category_code,
            "assigned_associate_id": assigned,
            "last_audit_closed_at": None,
        },
    )
    return ok(views.aisle(aisle), 201)


@bp.get("/price-integrity/aisles/<aid>")
@roles(*STAFF_READ)
def get_aisle(aid):
    return ok(views.aisle(must("aisles", aid)))


@bp.get("/price-integrity/stores/<sid>/aisles")
@roles(*STAFF_READ)
def list_store_aisles(sid):
    category_code = arg_str("category_code")
    limit, offset = pagination()
    must("stores", sid)
    items = [
        r
        for r in rows("aisles")
        if r["store_id"] == sid
        and (category_code is None or r["category_code"] == category_code)
    ]
    return views.paged(items, views.aisle, limit, offset)


@bp.get("/price-integrity/associates/<aid>/aisles")
@roles(*STAFF_READ)
def list_associate_aisles(aid):
    limit, offset = pagination()
    must("associates", aid)
    items = [r for r in rows("aisles") if r["assigned_associate_id"] == aid]
    return views.paged(items, views.aisle, limit, offset)


@bp.post("/price-integrity/aisles/<aid>/assign-associate")
@roles(R_STORE_MANAGER)
def assign_aisle_associate(aid):
    data = body()
    if "assigned_associate_id" not in data:
        fail("ERR_INVALID_REQUEST", "assigned_associate_id is required")
    assigned = opt_str(data, "assigned_associate_id")
    aisle = must("aisles", aid)
    associate = None
    if assigned is not None:
        associate = must("associates", assigned)
        if associate["store_id"] != aisle["store_id"]:
            fail("ERR_ASSOCIATE_STORE_MISMATCH", "associate belongs to another store")
    apply_changes(aisle, {"assigned_associate_id": assigned})
    return ok(views.aisle(aisle))


# ---------------------------------------------------------------- associates
@bp.post("/price-integrity/stores/<sid>/associates")
@roles(R_STORE_MANAGER, R_PRICING_ADMIN)
def hire_associate(sid):
    data = body()
    employee_number = req_str(data, "employee_number", 1, 64)
    full_name = req_str(data, "full_name", 1, 255)
    role_code = req_enum(data, "role_code", ASSOCIATE_ROLE_CODES)
    store = must("stores", sid)
    if any(
        r["store_id"] == sid and r["employee_number"] == employee_number
        for r in DB["associates"].values()
    ):
        fail("ERR_DUPLICATE_RESOURCE", "employee_number already used in this store")
    associate = insert(
        "associates",
        {
            "store_id": store["id"],
            "employee_number": employee_number,
            "full_name": full_name,
            "role_code": role_code,
            "training_status": "UNTRAINED",
            "certification_expires_at": None,
            "last_training_module_code": None,
            "last_training_score_pct": None,
            "accountability_score": 100,
            "issued_action_count": 0,
            "verified_placement_count": 0,
        },
    )
    return ok(views.associate(associate), 201)


@bp.get("/price-integrity/associates/<aid>")
@roles(*STAFF_READ)
def get_associate(aid):
    return ok(views.associate(must("associates", aid)))


@bp.get("/price-integrity/stores/<sid>/associates")
@roles(R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER, R_PRICE_AUDITOR)
def list_store_associates(sid):
    role_code = arg_enum("role_code", ASSOCIATE_ROLE_CODES)
    training_status = arg_enum("training_status", TRAINING_STATUSES)
    limit, offset = pagination()
    must("stores", sid)
    items = [
        r
        for r in rows("associates")
        if r["store_id"] == sid
        and (role_code is None or r["role_code"] == role_code)
        and (training_status is None or r["training_status"] == training_status)
    ]
    return views.paged(items, views.associate, limit, offset)


@bp.post("/price-integrity/associates/<aid>/training-completions")
@roles(R_STORE_MANAGER, R_PRICING_ADMIN)
def record_training(aid):
    data = body()
    module_code = req_str(data, "module_code", 1, 64)
    score_pct = req_num(data, "score_pct", 0, 100, 2)
    associate = must("associates", aid)
    status = associate["training_status"]
    passed = score_pct >= TRAINING_PASS_SCORE_PCT
    expiry = now() + timedelta(days=CERTIFICATION_VALID_DAYS)

    if status == "SUSPENDED":
        if module_code != REMEDIAL_MODULE_CODE:
            fail("ERR_ASSOCIATE_INVALID_STATE", "a suspended associate needs the remedial module")
        if not passed:
            fail("ERR_TRAINING_SCORE_TOO_LOW", "the remedial module requires at least 80")
        apply_changes(
            associate,
            {"last_training_module_code": module_code, "last_training_score_pct": score_pct},
        )
        for action in services.associate_actions(aid):
            if action["status"] == "ISSUED" and action["action_type"] in (
                "SUSPENSION",
                "RETRAINING_ASSIGNED",
            ):
                apply_changes(action, {"status": "COMPLETED"})
        services.recompute_associate(associate, allow_suspend=False)
        apply_changes(associate, {"certification_expires_at": expiry})
        if associate["accountability_score"] >= TRAINING_PASS_SCORE_PCT:
            apply_changes(associate, {"training_status": "CERTIFIED"})
        touch(associate)
        return ok(views.associate(associate))

    if status == "CERTIFIED" and not passed:
        fail("ERR_ASSOCIATE_INVALID_STATE", "a certified associate cannot record a failing result")

    changes = {
        "last_training_module_code": module_code,
        "last_training_score_pct": score_pct,
    }
    if passed:
        changes["training_status"] = "CERTIFIED"
        changes["certification_expires_at"] = expiry
    else:
        changes["training_status"] = "IN_TRAINING"
    apply_changes(associate, changes)
    touch(associate)
    return ok(views.associate(associate))


# ---------------------------------------------------- accountability actions
@bp.post("/price-integrity/associates/<aid>/accountability-actions")
@roles(R_STORE_MANAGER, R_COMPLIANCE_OFFICER)
def issue_accountability_action(aid):
    data = body()
    trigger_code = req_enum(data, "trigger_code", ACTION_TRIGGER_CODES)
    action_type = req_enum(data, "action_type", ACTION_TYPES)
    source_ref = opt_str(data, "source_ref", 1, 255)
    associate = must("associates", aid)
    if associate["training_status"] == "SUSPENDED":
        fail("ERR_ASSOCIATE_INVALID_STATE", "the associate is already suspended")
    issued_by = request.headers.get("X-User-ID") or None
    action = services.issue_action(
        associate, trigger_code, action_type, issued_by, source_ref
    )
    return ok(views.accountability_action(action), 201)


@bp.get("/price-integrity/accountability-actions/<xid>")
@roles(*STAFF_READ)
def get_accountability_action(xid):
    return ok(views.accountability_action(must("accountability_actions", xid)))


@bp.get("/price-integrity/associates/<aid>/accountability-actions")
@roles(*STAFF_READ)
def list_accountability_actions(aid):
    status = arg_enum("status", ["ISSUED", "COMPLETED", "VOIDED"])
    trigger_code = arg_enum("trigger_code", ACTION_TRIGGER_CODES)
    limit, offset = pagination()
    must("associates", aid)
    items = [
        r
        for r in rows("accountability_actions")
        if r["associate_id"] == aid
        and (status is None or r["status"] == status)
        and (trigger_code is None or r["trigger_code"] == trigger_code)
    ]
    return views.paged(items, views.accountability_action, limit, offset)


@bp.post("/price-integrity/accountability-actions/<xid>/transition")
@roles(R_STORE_MANAGER, R_COMPLIANCE_OFFICER)
def transition_accountability_action(xid):
    data = body()
    target_status = req_enum(data, "target_status", ["COMPLETED", "VOIDED"])
    void_reason = opt_str(data, "void_reason", 0, 500)
    action = must("accountability_actions", xid)
    if action["status"] != "ISSUED":
        fail("ERR_ACTION_INVALID_STATE", "the action is no longer issued")
    if target_status == "VOIDED":
        if void_reason is None or not void_reason.strip():
            fail("ERR_VOID_REASON_REQUIRED", "void_reason is required")
        apply_changes(action, {"status": "VOIDED", "void_reason": void_reason})
    else:
        apply_changes(action, {"status": "COMPLETED"})
    associate = DB["associates"].get(action["associate_id"])
    if associate is not None:
        services.recompute_associate(associate)
    return ok(views.accountability_action(action))


# ---------------------------------------------------------------- clock
@bp.post("/price-integrity/_clock/set_current_utc")
@roles(R_PRICING_ADMIN, R_COMPLIANCE_OFFICER)
def set_current_utc():
    data = body()
    current_utc = req_dt(data, "current_utc")
    set_clock(current_utc)
    return ok({"current_utc": iso(current_utc)})

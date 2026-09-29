from flask import Blueprint, request

import auth
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("criteria_mappings", __name__)

MAPPING_TYPES = ("PRIMARY", "SECONDARY")
PHASES = {"SCOPING", "READINESS", "OBSERVATION"}


@bp.post("/soc/criteria-mappings")
def create_mapping():
    auth.authenticate({"ComplianceLead"})
    body = auth.body()
    control = v.fk(body, "control_id", "controls")
    criterion = v.fk(body, "trust_criterion_id", "trust_criteria")
    v.req_id(body, "control_id")
    v.req_id(body, "trust_criterion_id")
    mapping_type = v.opt_enum(body, "mapping_type", MAPPING_TYPES, default="PRIMARY")
    rationale = v.opt_str(body, "rationale", 1, 2000)

    engagement = DB["engagements"][control["engagement_id"]]
    services.require_phase(engagement, PHASES)
    services.require_not_frozen(engagement)

    if not control["in_scope"] or control["design_status"] == "DESIGN_CARVED_OUT":
        raise ApiError("ERR_CONTROL_OUT_OF_SCOPE")
    if not services.criterion_in_scope(engagement, criterion):
        raise ApiError("ERR_CRITERION_OUT_OF_SCOPE")

    for m in DB["criteria_mappings"].values():
        if (
            m["status"] == "ACTIVE"
            and m["control_id"] == control["id"]
            and m["trust_criterion_id"] == criterion["id"]
        ):
            raise ApiError("ERR_DUPLICATE_RESOURCE")

    row = store.new_row(
        "criteria_mappings",
        {
            "control_id": control["id"],
            "trust_criterion_id": criterion["id"],
            "mapping_type": mapping_type,
            "rationale": rationale,
            "status": "ACTIVE",
            "retired_at": None,
        },
    )
    services.refresh_mapping_counts(control)
    if control["active_mapping_count"] == 1 and control["design_status"] == "DESIGN_DRAFT" \
            and control["in_scope"]:
        control["design_status"] = "DESIGN_MAPPED"
        store.touch(control)
    services.refresh_engagement(engagement)
    return ok(store.public(row), 201)


@bp.get("/soc/criteria-mappings/<criteria_mapping_id>")
def read_mapping(criteria_mapping_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("criteria_mappings", criteria_mapping_id)
    return ok(store.public(row))


@bp.get("/soc/criteria-mappings")
def list_mappings():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("criteria_mappings")
    for key in ("control_id", "trust_criterion_id", "status", "mapping_type"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.delete("/soc/criteria-mappings/<criteria_mapping_id>")
def retire_mapping(criteria_mapping_id):
    auth.authenticate({"ComplianceLead"})
    row = store.get_or_404("criteria_mappings", criteria_mapping_id)
    control = DB["controls"][row["control_id"]]
    engagement = DB["engagements"][control["engagement_id"]]
    services.require_phase(engagement, PHASES)
    services.require_not_frozen(engagement)
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    row["status"] = "RETIRED"
    row["retired_at"] = store.now_iso()
    store.touch(row)
    services.refresh_mapping_counts(control)
    if control["active_mapping_count"] == 0 and control["design_status"] == "DESIGN_MAPPED":
        control["design_status"] = "DESIGN_DRAFT"
        store.touch(control)
    services.refresh_engagement(engagement)
    return ok(store.public(row))

"""Away periods and checklist templates."""
from flask import Blueprint

import calc
import core
import gates
import serialize
from core import fail, get, new_row, parse_iso, touch

bp = Blueprint("catalog", __name__)

AWAY_SPEC = [
    ("property_id", "string", True),
    ("owner_id", "string", True),
    ("start_at", "datetime", True),
    ("end_at", "datetime", True),
    ("cadence_days", "integer", True),
]


@bp.post("/property-care/away-periods")
def create_away_period():
    role, user_id = gates.begin(["Owner", "AccountManager", "PlatformAdmin"])
    body = gates.body_json()
    # G3: rung 8 (owner_id) is numbered before rung 9 (property_id)
    if isinstance(body.get("owner_id"), str):
        gates.fetch_body_fk("owners", body["owner_id"], "ERR_OWNER_NOT_FOUND")
    prop = None
    if isinstance(body.get("property_id"), str):
        prop = gates.fetch_body_fk("properties", body["property_id"], "ERR_PROPERTY_NOT_FOUND")
    # G2 rung 4 once the target property is resolvable
    if prop is not None:
        gates.owner_scope(role, user_id, prop["owner_id"])
    gates.validate_payload(body, AWAY_SPEC)
    gates.fetch_body_fk("owners", body["owner_id"], "ERR_OWNER_NOT_FOUND")
    prop = gates.fetch_body_fk("properties", body["property_id"], "ERR_PROPERTY_NOT_FOUND")
    gates.check_interval(body, "start_at", "end_at")

    start_at = parse_iso(body["start_at"])
    end_at = parse_iso(body["end_at"])
    span_days = calc.whole_days((end_at - start_at).total_seconds())
    if span_days > core.AWAY_PERIOD_MAX_DAYS or body["owner_id"] != prop["owner_id"]:
        fail("ERR_AWAY_PERIOD_INVALID",
             "The away period exceeds the maximum span or names the wrong owner.")

    ap = new_row(
        "away_periods",
        property_id=body["property_id"],
        owner_id=body["owner_id"],
        start_at=start_at,
        end_at=end_at,
        cadence_days=body["cadence_days"],
        projected_visit_count=0,
        cadence_revision_count=0,
    )
    ap["projected_visit_count"] = calc.cadence_projection_initial(ap)
    return core.ok(serialize.away_period(ap), 201)


@bp.get("/property-care/away-periods")
def list_away_periods():
    gates.begin(["Owner", "AccountManager", "PlatformAdmin", "Dispatcher", "Auditor"])
    return gates.list_response("away_periods", ["property_id", "owner_id"], serialize.away_period)


@bp.get("/property-care/away-periods/<aid>")
def read_away_period(aid):
    role, user_id = gates.begin(["Owner", "AccountManager", "PlatformAdmin", "Dispatcher", "Auditor"])
    ap = gates.fetch_path("away_periods", aid)
    gates.owner_scope(role, user_id, ap["owner_id"])
    return core.ok(serialize.away_period(ap))


@bp.patch("/property-care/away-periods/<aid>/cadence")
def revise_cadence(aid):
    role, user_id = gates.begin(["Owner", "AccountManager", "Dispatcher"])
    ap = gates.fetch_path("away_periods", aid)
    gates.owner_scope(role, user_id, ap["owner_id"])
    body = gates.body_json()
    gates.validate_payload(body, [("cadence_days", "integer", True)])
    new_cadence = body["cadence_days"]
    ap["projected_visit_count"] = calc.cadence_projection_revision(ap, new_cadence)
    ap["cadence_days"] = new_cadence
    ap["cadence_revision_count"] += 1
    touch(ap)
    return core.ok(serialize.away_period(ap))


TEMPLATE_SPEC = [
    ("visit_type", "string", True),
    ("version_label", "string", True),
    ("item_codes", "string_array", True),
    ("critical_item_codes", "string_array", False),
    ("default_finding_category", "string", False),
    ("status", "string", False),
]


@bp.post("/property-care/checklist-templates")
def create_template():
    gates.begin(["PlatformAdmin", "Dispatcher"])
    body = gates.body_json()
    gates.validate_payload(body, TEMPLATE_SPEC,
                           enum_overrides={"default_finding_category": core.CATEGORIES})
    item_codes = body["item_codes"]
    tpl = new_row(
        "checklist_templates",
        visit_type=body["visit_type"],
        version_label=body["version_label"],
        item_codes=item_codes,
        critical_item_codes=body.get("critical_item_codes") or [],
        default_finding_category=body.get("default_finding_category", "OTHER"),
        required_item_count=len(item_codes),
        status=body.get("status", "ACTIVE"),
    )
    return core.ok(serialize.checklist_template(tpl), 201)


@bp.get("/property-care/checklist-templates")
def list_templates():
    gates.begin(["PlatformAdmin", "Dispatcher", "FieldTech", "Auditor"])
    return gates.list_response("checklist_templates", ["visit_type", "status"],
                               serialize.checklist_template)


@bp.get("/property-care/checklist-templates/<tid>")
def read_template(tid):
    gates.begin(["PlatformAdmin", "Dispatcher", "FieldTech", "Auditor"])
    tpl = gates.fetch_path("checklist_templates", tid)
    return core.ok(serialize.checklist_template(tpl))

"""PunchItem endpoints (§3.7): resolve/verify/fail-verification rework loop,
severity-gated waivers, live site punch counts."""
from flask import Blueprint

from db import store
from errors import ApiError, invalid_state
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response, require_state
from services.budget import recompute_punch_counts
from util import bump, new_entity, serialize
from validate import body_fk, get_or_404, json_body, req_enum, req_str

bp = Blueprint("punch_items", __name__)

TERMINAL = ("VERIFIED", "WAIVED")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")


@bp.route("/rollout/punch-items", methods=["POST"], strict_slashes=False)
@authed(["SiteSuperintendent"])
def create_punch_item():
    body = json_body()
    site = body_fk(body, "site_id", store.sites)
    # Step 5 — creation is only meaningful while the site is PUNCH or TURNOVER.
    if site is not None and site["status"] not in ("PUNCH", "TURNOVER"):
        invalid_state("site is not in PUNCH or TURNOVER")
    if site is None:
        from errors import invalid_request
        invalid_request("field 'site_id' is required")
    description = req_str(body, "description")
    severity = req_enum(body, "severity", SEVERITIES)
    item = new_entity(store)
    item.update({
        "site_id": site["id"],
        "description": description,
        "severity": severity,
        "reopen_count": 0,
        "status": "OPEN",
    })
    store.punch_items[item["id"]] = item
    recompute_punch_counts(site)
    return ok(serialize(item), status=201)


@bp.route("/rollout/punch-items", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_punch_items():
    return list_response(store.punch_items, [
        ("site_id", "site_id", "str"),
        ("status", "status", "str"),
        ("severity", "severity", "str"),
    ])


@bp.route("/rollout/punch-items/<punchItemId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_punch_item(punchItemId):
    return ok(serialize(get_or_404(store.punch_items, punchItemId, "punch item")))


@bp.route("/rollout/punch-items/<punchItemId>/resolve", methods=["POST"], strict_slashes=False)
@authed(["SiteSuperintendent"])
def resolve_punch_item(punchItemId):
    item = get_or_404(store.punch_items, punchItemId, "punch item")
    require_state(item, ("OPEN",), TERMINAL)
    item["status"] = "RESOLVED"  # RESOLVED still counts as open (§3.7)
    bump(item)
    return ok(serialize(item))


@bp.route("/rollout/punch-items/<punchItemId>/verify", methods=["POST"], strict_slashes=False)
@authed(["OperationsLead"])
def verify_punch_item(punchItemId):
    item = get_or_404(store.punch_items, punchItemId, "punch item")
    require_state(item, ("RESOLVED",), TERMINAL)
    item["status"] = "VERIFIED"
    bump(item)
    site = store.sites.get(item["site_id"])
    if site is not None:
        recompute_punch_counts(site)
    return ok(serialize(item))


@bp.route("/rollout/punch-items/<punchItemId>/fail-verification", methods=["POST"], strict_slashes=False)
@authed(["OperationsLead"])
def fail_verification(punchItemId):
    body = json_body()
    item = get_or_404(store.punch_items, punchItemId, "punch item")
    require_state(item, ("RESOLVED",), TERMINAL)
    req_str(body, "failure_note")
    item["status"] = "OPEN"
    item["reopen_count"] += 1
    bump(item)
    site = store.sites.get(item["site_id"])
    if site is not None:
        recompute_punch_counts(site)
    return ok(serialize(item))


@bp.route("/rollout/punch-items/<punchItemId>/waive", methods=["POST"], strict_slashes=False)
@authed(["OperationsLead"])
def waive_punch_item(punchItemId):
    item = get_or_404(store.punch_items, punchItemId, "punch item")
    require_state(item, ("OPEN", "RESOLVED"), TERMINAL)
    if item["severity"] not in ("MAJOR", "MINOR"):
        raise ApiError("ERR_PUNCH_NOT_WAIVABLE", 422,
                       "CRITICAL punch items are not waivable")
    item["status"] = "WAIVED"
    bump(item)
    site = store.sites.get(item["site_id"])
    if site is not None:
        recompute_punch_counts(site)
    return ok(serialize(item))

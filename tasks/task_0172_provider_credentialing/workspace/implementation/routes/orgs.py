"""Credentialing orgs, the deterministic clock, payers, sanctions sources."""
from flask import Blueprint

from db import store
from errors import err
from middleware import require_auth, require_role
from response import success_array, success_object
from services.calc import compute_expirable_band
from services.common import (
    parse_iso8601,
    parse_pagination,
    paginate,
    require_body,
    sort_by_created,
)
from services.lookups import get_org, get_payer, get_sanctions_source
from services.model import make_record, serialize, touch
from services.posture import recompute_provider

bp = Blueprint("orgs", __name__)

DEFAULT_CLOCK = "2026-01-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Credentialing Orgs
# ---------------------------------------------------------------------------
@bp.route("/credentialing-orgs", methods=["POST"])
def create_org():
    _, role = require_auth()
    require_role(role, {"SystemAdmin"})
    body = require_body()

    name = body.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise err("ERR_INVALID_REQUEST", "name is required.")

    recred = body.get("recred_cycle_days", 1095)
    if not isinstance(recred, int) or isinstance(recred, bool) or recred < 1:
        raise err("ERR_INVALID_REQUEST", "recred_cycle_days must be a positive integer.")

    window = body.get("expiring_soon_window_days", 90)
    if not isinstance(window, int) or isinstance(window, bool) or window < 0:
        raise err("ERR_INVALID_REQUEST", "expiring_soon_window_days must be a non-negative integer.")

    rec = make_record("orgs", {
        "name": name,
        "current_utc": DEFAULT_CLOCK,
        "recred_cycle_days": recred,
        "expiring_soon_window_days": window,
    })
    return success_object(serialize(rec), 201)


@bp.route("/credentialing-orgs/<rid>", methods=["GET"])
def get_org_route(rid):
    _, role = require_auth()
    require_role(role, {"SystemAdmin", "CredentialingSpecialist", "MedicalDirector",
                        "EnrollmentCoordinator", "ComplianceOfficer"})
    rec = get_org(rid)
    return success_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Deterministic clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_auth()
    require_role(role, {"SystemAdmin"})
    body = require_body()

    to_iso = body.get("to_iso8601")
    new_dt = parse_iso8601(to_iso, "to_iso8601")  # validates format

    # Apply to every org (each org owns its own clock; tests typically use one).
    from services.common import iso_from_dt
    new_value = iso_from_dt(new_dt)

    last_org = None
    for org in store.orgs.values():
        org["current_utc"] = new_value
        touch(org)
        last_org = org
        _advance_clock_effects(org)

    if last_org is None:
        raise err("ERR_NOT_FOUND", "No organization exists.")
    return success_object(serialize(last_org), 200)


def _advance_clock_effects(org):
    """1) recompute expirable_band for every item; 2) recompute posture/score
    for affected providers; 3) recred demotion CURRENT->RECRED_DUE when
    current_utc >= recred_due_date; 4) cascade enrollment termination handled
    inside recompute_provider."""
    # Step 1: recompute every credential item's band.
    for item in store.credential_items.values():
        prov = store.providers.get(item["provider_id"])
        if prov is None:
            continue
        band = compute_expirable_band(item, org)
        if band != item["expirable_band"]:
            item["expirable_band"] = band
            touch(item)

    # Step 3 prep + Step 2: for each provider in this org, apply recred demotion
    # then recompute posture/readiness (which cascades enrollment termination).
    for prov in store.providers.values():
        if prov.get("org_id") != org["id"]:
            continue
        # recred demotion: CURRENT and current_utc >= recred_due_date -> RECRED_DUE
        if prov["recred_state"] == "CURRENT" and prov.get("recred_due_date"):
            cur_ms = parse_iso8601(org["current_utc"]).timestamp()
            due_ms = parse_iso8601(prov["recred_due_date"]).timestamp()
            if cur_ms >= due_ms:
                prov["recred_state"] = "RECRED_DUE"
        recompute_provider(prov, recompute_readiness=True)


# ---------------------------------------------------------------------------
# Payers
# ---------------------------------------------------------------------------
@bp.route("/payers", methods=["POST"])
def create_payer():
    _, role = require_auth()
    require_role(role, {"SystemAdmin", "EnrollmentCoordinator"})
    body = require_body()

    org_id = body.get("org_id")
    if not isinstance(org_id, str) or org_id.strip() == "":
        raise err("ERR_INVALID_REQUEST", "org_id is required.")
    # org existence is a body FK -> priority 4, before other field validation
    if org_id not in store.orgs:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "org_id does not reference an existing organization.")

    name = body.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise err("ERR_INVALID_REQUEST", "name is required.")
    payer_type = body.get("payer_type")
    if payer_type not in ("COMMERCIAL", "MEDICARE", "MEDICAID"):
        raise err("ERR_INVALID_REQUEST", "payer_type must be COMMERCIAL, MEDICARE, or MEDICAID.")
    retro = body.get("retroactive_allowed", False)
    if not isinstance(retro, bool):
        raise err("ERR_INVALID_REQUEST", "retroactive_allowed must be a boolean.")
    panel = body.get("panel_capacity")
    if not isinstance(panel, int) or isinstance(panel, bool) or panel < 1:
        raise err("ERR_INVALID_REQUEST", "panel_capacity must be an integer >= 1.")

    rec = make_record("payers", {
        "org_id": org_id,
        "name": name,
        "payer_type": payer_type,
        "retroactive_allowed": retro,
        "panel_capacity": panel,
    })
    return success_object(serialize(rec), 201)


@bp.route("/payers", methods=["GET"])
def list_payers():
    _, role = require_auth()
    require_role(role, {"SystemAdmin", "EnrollmentCoordinator", "CredentialingSpecialist"})
    from flask import request
    org_id = request.args.get("org_id")
    limit, offset = parse_pagination()
    rows = [p for p in store.payers.values()
            if org_id is None or p["org_id"] == org_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


@bp.route("/payers/<rid>", methods=["GET"])
def get_payer_route(rid):
    _, role = require_auth()
    require_role(role, {"SystemAdmin", "EnrollmentCoordinator", "CredentialingSpecialist"})
    rec = get_payer(rid)
    return success_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Sanctions sources
# ---------------------------------------------------------------------------
@bp.route("/sanctions-sources", methods=["POST"])
def create_sanctions_source():
    _, role = require_auth()
    require_role(role, {"SystemAdmin", "ComplianceOfficer"})
    body = require_body()

    org_id = body.get("org_id")
    if not isinstance(org_id, str) or org_id.strip() == "":
        raise err("ERR_INVALID_REQUEST", "org_id is required.")
    # org existence is a body FK -> priority 4, before other field validation
    if org_id not in store.orgs:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "org_id does not reference an existing organization.")

    source_code = body.get("source_code")
    if source_code not in ("OIG_LEIE", "SAM_EXCLUSIONS"):
        raise err("ERR_INVALID_REQUEST", "source_code must be OIG_LEIE or SAM_EXCLUSIONS.")
    severity = body.get("severity_weight")
    if not isinstance(severity, int) or isinstance(severity, bool) or severity < 1:
        raise err("ERR_INVALID_REQUEST", "severity_weight must be a positive integer.")

    # unique source_code per org
    for s in store.sanctions_sources.values():
        if s["org_id"] == org_id and s["source_code"] == source_code:
            raise err("ERR_INVALID_REQUEST", "source_code already registered for this org.")

    rec = make_record("sanctions_sources", {
        "org_id": org_id,
        "source_code": source_code,
        "severity_weight": severity,
    })
    return success_object(serialize(rec), 201)


@bp.route("/sanctions-sources", methods=["GET"])
def list_sanctions_sources():
    _, role = require_auth()
    require_role(role, {"SystemAdmin", "ComplianceOfficer"})
    from flask import request
    org_id = request.args.get("org_id")
    limit, offset = parse_pagination()
    rows = [s for s in store.sanctions_sources.values()
            if org_id is None or s["org_id"] == org_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


@bp.route("/sanctions-sources/<rid>", methods=["GET"])
def get_sanctions_source_route(rid):
    _, role = require_auth()
    require_role(role, {"SystemAdmin", "ComplianceOfficer"})
    rec = get_sanctions_source(rid)
    return success_object(serialize(rec), 200)

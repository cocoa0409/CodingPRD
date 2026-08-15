"""TpaEngagement endpoints: engagement lifecycle and TPA oversight (§3.1)."""
from flask import Blueprint

from db import STORE
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_REMEDIATION_NOTE_SHORT,
    ERR_TPA_HAS_OPEN_WORK,
    ERR_TPA_NOT_SUSPENDED,
    ERR_TPA_WINDOW_OVERLAP,
)
from middleware import require_roles
from response import paginate, success
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from util import as_dt, as_str, body_json, check_enum, req

bp = Blueprint("tpa", __name__)

AUTHORITY_SCOPES = ("RESPONSE_ONLY", "RESPONSE_AND_HEARING", "FULL")
# Statuses under which a TPA may file. REINSTATED restores filing authority;
# SUSPENDED / TERMINATED reject with ERR_TPA_NOT_ACTIVE.
FILING_STATUSES = ("ACTIVE", "REINSTATED")


def engagement_covers(eng, when):
    """True when the engagement's status permits filing and `when` falls inside
    its inclusive effective window."""
    return (
        eng["oversight_status"] in FILING_STATUSES
        and eng["effective_from"] <= when <= eng["effective_to"]
    )


def scope_covers_response(eng):
    """Every declared scope authorizes response filings."""
    return eng["authority_scope"] in ("RESPONSE_ONLY", "RESPONSE_AND_HEARING", "FULL")


@bp.post("/ui/tpa-engagements")
def create_engagement():
    require_roles("TpaManager")
    body = body_json()
    employer_id = as_str(req(body, "employer_id"), "employer_id")
    tpa_name = as_str(req(body, "tpa_name"), "tpa_name")
    authority_scope = check_enum(
        as_str(req(body, "authority_scope"), "authority_scope"),
        AUTHORITY_SCOPES, "authority_scope",
    )
    effective_from = as_dt(req(body, "effective_from"), "effective_from")
    effective_to = as_dt(req(body, "effective_to"), "effective_to")
    # body FK resolution
    find_or_404(STORE.employers, employer_id, "employer")
    # Window exclusivity: closed-closed interval intersection against every
    # non-TERMINATED sibling engagement for the same employer. Windows that
    # merely touch at a boundary timestamp DO intersect.
    for other in STORE.tpa_engagements.values():
        if other["employer_id"] != employer_id or other["oversight_status"] == "TERMINATED":
            continue
        if effective_from <= other["effective_to"] and effective_to >= other["effective_from"]:
            raise err(
                ERR_TPA_WINDOW_OVERLAP,
                409,
                "engagement window intersects an existing non-TERMINATED engagement",
            )
    rec = new_record({
        "employer_id": employer_id,
        "tpa_name": tpa_name,
        "authority_scope": authority_scope,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "oversight_status": "ACTIVE",
        "breach_count": 0,
    })
    STORE.tpa_engagements[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/ui/tpa-engagements/<rid>")
def get_engagement(rid):
    require_roles("PlatformAdmin", "TpaManager", "ClaimsAnalyst")
    rec = find_or_404(STORE.tpa_engagements, rid, "tpa engagement")
    return success(serialize(rec))


@bp.get("/ui/tpa-engagements/<rid>/responses")
def engagement_responses(rid):
    require_roles("PlatformAdmin", "TpaManager", "ClaimsAnalyst")
    find_or_404(STORE.tpa_engagements, rid, "tpa engagement")
    items = [
        serialize(r) for r in sorted_created(STORE.responses.values())
        if r["filed_by_tpa_id"] == rid
    ]
    return paginate(items)


@bp.post("/ui/tpa-engagements/<rid>/suspend")
def suspend_engagement(rid):
    require_roles("TpaManager")
    eng = find_or_404(STORE.tpa_engagements, rid, "tpa engagement")
    if eng["oversight_status"] not in ("ACTIVE", "REINSTATED"):
        raise err(ERR_INVALID_STATE, 409, "only an ACTIVE or REINSTATED engagement can be suspended")
    eng["oversight_status"] = "SUSPENDED"
    touch(eng)
    return success(serialize(eng))


@bp.post("/ui/tpa-engagements/<rid>/reinstate")
def reinstate_engagement(rid):
    require_roles("TpaManager")
    body = body_json()
    note = as_str(req(body, "remediation_note"), "remediation_note")
    eng = find_or_404(STORE.tpa_engagements, rid, "tpa engagement")
    if eng["oversight_status"] != "SUSPENDED":
        raise err(ERR_TPA_NOT_SUSPENDED, 409, "reinstate requires a SUSPENDED engagement")
    if len(note) < 20:
        raise err(ERR_REMEDIATION_NOTE_SHORT, 422, "remediation note must be at least 20 characters")
    eng["oversight_status"] = "REINSTATED"
    eng["breach_count"] = 1  # reset to 1, not 0 — prior history retained
    touch(eng)
    return success(serialize(eng))


@bp.post("/ui/tpa-engagements/<rid>/terminate")
def terminate_engagement(rid):
    require_roles("TpaManager")
    eng = find_or_404(STORE.tpa_engagements, rid, "tpa engagement")
    if eng["oversight_status"] not in ("ACTIVE", "SUSPENDED"):
        raise err(ERR_INVALID_STATE, 409, "only an ACTIVE or SUSPENDED engagement can be terminated")
    # Open-work guard: any claim sitting in RESPONSE_IN_PROGRESS with a live
    # DRAFT response bound to this engagement blocks termination.
    for resp in STORE.responses.values():
        if resp["filed_by_tpa_id"] != rid or resp["status"] != "DRAFT":
            continue
        claim = STORE.claims.get(resp["claim_id"])
        if claim is not None and claim["status"] == "RESPONSE_IN_PROGRESS":
            raise err(ERR_TPA_HAS_OPEN_WORK, 409, "engagement owns in-progress responses")
    eng["oversight_status"] = "TERMINATED"
    touch(eng)
    return success(serialize(eng))

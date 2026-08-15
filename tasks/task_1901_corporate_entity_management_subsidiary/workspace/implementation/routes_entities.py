"""Routes: LegalEntity CRUD, lifecycle transitions, ownership chart, audit trail."""
from flask import Blueprint, request

import store
import services as svc
from errors import (
    ERR_INVALID_REQUEST, ERR_ENTITY_NOT_FOUND, ERR_JURISDICTION_NOT_FOUND,
    ERR_ENTITY_NOT_DRAFT, ERR_ENTITY_NOT_FORMATION_PENDING, ERR_ENTITY_NOT_ACTIVE,
    ERR_ENTITY_NOT_DISSOLUTION_PENDING, ERR_REQUIRED_RESOLUTION_MISSING,
    ERR_AGENT_COVERAGE_GAP, ERR_OPEN_QUALIFICATIONS_EXIST, ERR_DISSOLUTION_BLOCKED,
    raise_err,
)
from middleware import require_roles, get_body, ALL_ROLES
from response import ok_object, paginate, sort_records
from routes_misc import _require_str, _optional_int

bp = Blueprint("entities", __name__)

CS = ["CorporateSecretary"]

ENTITY_TYPES = {"CORPORATION", "LLC", "LIMITED_PARTNERSHIP", "NONPROFIT_CORPORATION"}


def get_entity_or_404(entity_id):
    entity = store.entities.get(entity_id)
    if entity is None:
        raise_err(ERR_ENTITY_NOT_FOUND)
    return entity


# ---------------------------------------------------------------------------
# Create / read / update
# ---------------------------------------------------------------------------
@bp.route("/api/entities", methods=["POST"])
def create_entity():
    require_roles(CS)
    body = get_body()
    # Priority 3: body FK existence
    fj_id = body.get("formation_jurisdiction_id")
    if fj_id is not None and fj_id not in store.jurisdictions:
        raise_err(ERR_JURISDICTION_NOT_FOUND)
    # Priority 4: schema
    legal_name = _require_str(body, "legal_name")
    entity_type = body.get("entity_type")
    if entity_type not in ENTITY_TYPES:
        raise_err(ERR_INVALID_REQUEST, "entity_type is invalid")
    if fj_id is None:
        raise_err(ERR_INVALID_REQUEST, "formation_jurisdiction_id is required")
    formation_date = body.get("formation_date")
    if not svc.is_valid_date(formation_date):
        raise_err(ERR_INVALID_REQUEST, "formation_date must be an ISO date")
    fiscal_month = _optional_int(body, "fiscal_year_end_month", 1, 12)
    shares = _optional_int(body, "authorized_shares", 0)

    rec = store.new_record()
    rec.update({
        "legal_name": legal_name,
        "entity_type": entity_type,
        "formation_jurisdiction_id": fj_id,
        "formation_date": formation_date,
        "fiscal_year_end_month": fiscal_month if fiscal_month is not None else 12,
        "authorized_shares": shares if shares is not None else 0,
        "status": "DRAFT",
        "compliance_posture": "GOOD_STANDING",
        "suspended_since": None,
        "fees_accrued_cents": 0,
        "dissolved_date": None,
    })
    store.entities[rec["id"]] = rec
    return ok_object(svc.serialize(rec), 201)


@bp.route("/api/entities", methods=["GET"])
def list_entities():
    require_roles(ALL_ROLES)
    records = sort_records(list(store.entities.values()))
    fj = request.args.get("formation_jurisdiction_id")
    if fj is not None:
        records = [r for r in records if r["formation_jurisdiction_id"] == fj]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    etype = request.args.get("entity_type")
    if etype is not None:
        records = [r for r in records if r["entity_type"] == etype]
    return paginate([svc.serialize(r) for r in records], request.args)


@bp.route("/api/entities/<entityId>", methods=["GET"])
def get_entity(entityId):
    require_roles(ALL_ROLES)
    entity = get_entity_or_404(entityId)
    svc.lazy_eval_entity(entity)
    return ok_object(svc.serialize(entity))


@bp.route("/api/entities/<entityId>", methods=["PATCH"])
def patch_entity(entityId):
    require_roles(CS)
    entity = get_entity_or_404(entityId)
    body = get_body()
    # Priority 4: schema on provided fields
    if "legal_name" in body and body["legal_name"] is not None:
        _require_str(body, "legal_name")
    if "fiscal_year_end_month" in body and body["fiscal_year_end_month"] is not None:
        _optional_int(body, "fiscal_year_end_month", 1, 12)
    if "authorized_shares" in body and body["authorized_shares"] is not None:
        _optional_int(body, "authorized_shares", 0)
    # Priority 5: state gate
    if entity["status"] != "ACTIVE":
        raise_err(ERR_ENTITY_NOT_ACTIVE, "PATCH requires status == ACTIVE")
    changed = False
    if body.get("legal_name") is not None:
        entity["legal_name"] = body["legal_name"]
        changed = True
    if body.get("fiscal_year_end_month") is not None:
        entity["fiscal_year_end_month"] = body["fiscal_year_end_month"]
        changed = True
    if body.get("authorized_shares") is not None:
        entity["authorized_shares"] = body["authorized_shares"]
        changed = True
    if changed:
        store.touch(entity)
    return ok_object(svc.serialize(entity))


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
@bp.route("/api/entities/<entityId>/submit-formation", methods=["POST"])
def submit_formation(entityId):
    require_roles(CS)
    entity = get_entity_or_404(entityId)
    get_body()
    svc.lazy_eval_entity(entity)
    if entity["status"] != "DRAFT":
        raise_err(ERR_ENTITY_NOT_DRAFT, "submit-formation requires status == DRAFT")
    if svc.find_authorizing_resolution(entity["id"], "AUTHORIZE_FORMATION") is None:
        raise_err(ERR_REQUIRED_RESOLUTION_MISSING,
                  "No ADOPTED/EFFECTIVE AUTHORIZE_FORMATION resolution exists")
    entity["status"] = "FORMATION_PENDING"
    store.touch(entity)
    return ok_object(svc.serialize(entity))


@bp.route("/api/entities/<entityId>/confirm-formation", methods=["POST"])
def confirm_formation(entityId):
    require_roles(CS)
    entity = get_entity_or_404(entityId)
    get_body()
    svc.lazy_eval_entity(entity)
    if entity["status"] != "FORMATION_PENDING":
        raise_err(ERR_ENTITY_NOT_FORMATION_PENDING,
                  "confirm-formation requires status == FORMATION_PENDING")
    today = store.today()
    fj_id = entity["formation_jurisdiction_id"]
    covered = any(
        a for a in svc.agent_appts_of(entity["id"])
        if a["jurisdiction_id"] == fj_id
        and a["status"] in ("ACTIVE", "NOTICE_PENDING")
        and svc.parse_date(a["start_date"]) <= today)
    if not covered:
        raise_err(ERR_AGENT_COVERAGE_GAP,
                  "No covering agent appointment for the formation jurisdiction")
    entity["status"] = "ACTIVE"
    store.touch(entity)
    jurisdiction = store.jurisdictions[fj_id]
    period_year = svc.parse_date(entity["formation_date"]).year + 1
    svc.generate_filings(entity, jurisdiction, period_year)
    svc.recompute_posture(entity)
    return ok_object(svc.serialize(entity))


@bp.route("/api/entities/<entityId>/commence-dissolution", methods=["POST"])
def commence_dissolution(entityId):
    require_roles(CS)
    entity = get_entity_or_404(entityId)
    get_body()
    svc.lazy_eval_entity(entity)
    if entity["status"] != "ACTIVE":
        raise_err(ERR_ENTITY_NOT_ACTIVE, "commence-dissolution requires status == ACTIVE")
    if svc.find_authorizing_resolution(entity["id"], "AUTHORIZE_DISSOLUTION") is None:
        raise_err(ERR_REQUIRED_RESOLUTION_MISSING,
                  "No ADOPTED/EFFECTIVE AUTHORIZE_DISSOLUTION resolution exists")
    open_quals = [q for q in svc.quals_of(entity["id"])
                  if q["status"] not in ("WITHDRAWN", "REVOKED")]
    if open_quals:
        raise_err(ERR_OPEN_QUALIFICATIONS_EXIST,
                  "All foreign qualifications must be WITHDRAWN or REVOKED")
    entity["status"] = "DISSOLUTION_PENDING"
    store.touch(entity)
    for f in svc.filings_of(entity["id"]):
        if f["status"] in ("SCHEDULED", "PREPARED"):
            f["status"] = "WITHDRAWN"
            store.touch(f)
            svc.append_event(entity["id"], "FILING_WITHDRAWN", {"filing_id": f["id"]})
    svc.append_event(entity["id"], "DISSOLUTION_COMMENCED", {})
    return ok_object(svc.serialize(entity))


@bp.route("/api/entities/<entityId>/revoke-dissolution", methods=["POST"])
def revoke_dissolution(entityId):
    require_roles(CS)
    entity = get_entity_or_404(entityId)
    get_body()
    svc.lazy_eval_entity(entity)
    if entity["status"] != "DISSOLUTION_PENDING":
        raise_err(ERR_ENTITY_NOT_DISSOLUTION_PENDING,
                  "revoke-dissolution requires status == DISSOLUTION_PENDING")
    if svc.find_authorizing_resolution(entity["id"], "REVOKE_DISSOLUTION") is None:
        raise_err(ERR_REQUIRED_RESOLUTION_MISSING,
                  "No ADOPTED/EFFECTIVE REVOKE_DISSOLUTION resolution exists")
    entity["status"] = "ACTIVE"
    store.touch(entity)
    svc.recompute_posture(entity)
    return ok_object(svc.serialize(entity))


@bp.route("/api/entities/<entityId>/finalize-dissolution", methods=["POST"])
def finalize_dissolution(entityId):
    require_roles(CS)
    entity = get_entity_or_404(entityId)
    get_body()
    svc.lazy_eval_entity(entity)
    if entity["status"] != "DISSOLUTION_PENDING":
        raise_err(ERR_ENTITY_NOT_DISSOLUTION_PENDING,
                  "finalize-dissolution requires status == DISSOLUTION_PENDING")
    blocking_filings = [f for f in svc.filings_of(entity["id"])
                        if f["status"] in svc.FILING_OPEN_STATUSES]
    if blocking_filings:
        raise_err(ERR_DISSOLUTION_BLOCKED, "Non-terminal filings are outstanding")
    if any(c for c in svc.certs_of(entity["id"]) if c["status"] == "REQUESTED"):
        raise_err(ERR_DISSOLUTION_BLOCKED, "A certificate request is outstanding")
    today_str = svc.fmt_date(store.today())
    entity["status"] = "DISSOLVED"
    entity["dissolved_date"] = today_str
    store.touch(entity)
    # Cascade hop 1: APPOINTED appointments -> REMOVED
    removed = []
    for appt in svc.officer_appts_of(entity["id"]):
        if appt["status"] == "APPOINTED":
            appt["status"] = "REMOVED"
            appt["end_date"] = today_str
            store.touch(appt)
            svc.append_event(entity["id"], "OFFICER_REMOVED",
                             {"appointment_id": appt["id"]})
            removed.append(appt)
    # Cascade hops 2+3: grants of removed officers (recursive incl. delegated)
    for appt in removed:
        svc.revoke_officer_grants(entity["id"], appt["officer_id"])
    svc.append_event(entity["id"], "DISSOLUTION_COMPLETED", {})
    svc.recompute_posture(entity)
    return ok_object(svc.serialize(entity))


# ---------------------------------------------------------------------------
# Ownership chart & compliance events
# ---------------------------------------------------------------------------
@bp.route("/api/entities/<entityId>/ownership-chart", methods=["GET"])
def get_ownership_chart(entityId):
    require_roles(ALL_ROLES)
    get_entity_or_404(entityId)
    return ok_object(svc.ownership_chart(entityId))


@bp.route("/api/entities/<entityId>/compliance-events", methods=["GET"])
def list_compliance_events(entityId):
    require_roles(ALL_ROLES)
    get_entity_or_404(entityId)
    records = [e for e in store.compliance_events.values() if e["entity_id"] == entityId]
    etype = request.args.get("event_type")
    if etype is not None:
        records = [e for e in records if e["event_type"] == etype]
    records.sort(key=lambda e: (e["occurred_at"], e["created_at"], e.get("_seq", 0)))
    return paginate([svc.serialize(e) for e in records], request.args)

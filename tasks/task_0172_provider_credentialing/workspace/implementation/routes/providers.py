"""Provider intake lifecycle, credential items, sanctions screenings."""
import re

from flask import Blueprint, request

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
    to_epoch_ms,
)
from services.lookups import get_provider, get_org
from services.model import make_record, serialize, touch
from services.posture import recompute_provider

bp = Blueprint("providers", __name__)

NPI_RE = re.compile(r"^\d{10}$")


# ---------------------------------------------------------------------------
# Provider CRUD
# ---------------------------------------------------------------------------
@bp.route("/providers", methods=["POST"])
def create_provider():
    user_id, role = require_auth()
    require_role(role, {"CredentialingSpecialist"})
    body = require_body()

    org_id = body.get("org_id")
    if not isinstance(org_id, str) or org_id.strip() == "":
        raise err("ERR_INVALID_REQUEST", "org_id is required.")
    # Body-FK existence (priority 4) runs before other field validation (priority 5).
    if org_id not in store.orgs:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "org_id does not reference an existing organization.")

    npi = body.get("npi")
    if not isinstance(npi, str) or not NPI_RE.match(npi):
        raise err("ERR_INVALID_REQUEST", "npi must be exactly 10 digits.")
    full_name = body.get("full_name")
    if not isinstance(full_name, str) or full_name.strip() == "":
        raise err("ERR_INVALID_REQUEST", "full_name is required.")
    specialty = body.get("specialty")
    if not isinstance(specialty, str) or specialty.strip() == "":
        raise err("ERR_INVALID_REQUEST", "specialty is required.")
    caqh_id = body.get("caqh_id")
    if caqh_id is not None and not isinstance(caqh_id, str):
        raise err("ERR_INVALID_REQUEST", "caqh_id must be a string.")

    # npi unique within org
    for p in store.providers.values():
        if p["org_id"] == org_id and p["npi"] == npi:
            raise err("ERR_INVALID_REQUEST", "npi must be unique within the organization.")

    rec = make_record("providers", {
        "org_id": org_id,
        "npi": npi,
        "caqh_id": caqh_id,
        "full_name": full_name,
        "specialty": specialty,
        "application_status": "DRAFT",
        "credentialing_status": "PENDING",
        "recred_state": "NOT_CLEARED",
        "readiness_score": 0,
        "credentialing_completed_date": None,
        "recred_due_date": None,
        "original_completed_date": None,
        "initiated_by_user_id": None,
        "sanction_score": 0,
    })
    return success_object(serialize(rec), 201)


@bp.route("/providers/<rid>", methods=["GET"])
def get_provider_route(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist", "MedicalDirector",
                        "EnrollmentCoordinator", "ComplianceOfficer", "SystemAdmin"})
    rec = get_provider(rid)
    return success_object(serialize(rec), 200)


@bp.route("/providers", methods=["GET"])
def list_providers():
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist", "MedicalDirector",
                        "EnrollmentCoordinator", "ComplianceOfficer", "SystemAdmin"})
    org_id = request.args.get("org_id")
    limit, offset = parse_pagination()
    rows = [p for p in store.providers.values()
            if org_id is None or p["org_id"] == org_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------
@bp.route("/providers/<rid>/submit-application", methods=["POST"])
def submit_application(rid):
    user_id, role = require_auth()
    require_role(role, {"CredentialingSpecialist"})
    prov = get_provider(rid)

    if prov["application_status"] != "DRAFT":
        raise err("ERR_APPLICATION_NOT_DRAFT", "Application is not in DRAFT.")
    if not prov.get("caqh_id") or str(prov["caqh_id"]).strip() == "":
        raise err("ERR_CAQH_REQUIRED", "caqh_id is required to submit.")
    has_license = any(
        ci["provider_id"] == rid and ci["item_type"] == "STATE_LICENSE"
        for ci in store.credential_items.values())
    if not has_license:
        raise err("ERR_NO_LICENSE_ON_FILE", "At least one STATE_LICENSE credential item is required.")

    prov["application_status"] = "SUBMITTED"
    prov["initiated_by_user_id"] = user_id
    touch(prov)
    return success_object(serialize(prov), 200)


@bp.route("/providers/<rid>/begin-verification", methods=["POST"])
def begin_verification(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist"})
    prov = get_provider(rid)

    if prov["application_status"] != "SUBMITTED":
        raise err("ERR_APPLICATION_NOT_SUBMITTED", "Application is not in SUBMITTED.")

    prov["application_status"] = "IN_VERIFICATION"
    touch(prov)
    # cascade: every UNVERIFIED CredentialItem -> PENDING_PSV
    for ci in store.credential_items.values():
        if ci["provider_id"] == rid and ci["verification_state"] == "UNVERIFIED":
            ci["verification_state"] = "PENDING_PSV"
            touch(ci)
    return success_object(serialize(prov), 200)


@bp.route("/providers/<rid>/finalize-verification", methods=["POST"])
def finalize_verification(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist"})
    prov = get_provider(rid)

    if prov["application_status"] != "IN_VERIFICATION":
        raise err("ERR_APPLICATION_NOT_IN_VERIFICATION", "Application is not in IN_VERIFICATION.")
    still_pending = any(
        ci["provider_id"] == rid and ci["verification_state"] == "PENDING_PSV"
        for ci in store.credential_items.values())
    if still_pending:
        raise err("ERR_VERIFICATIONS_INCOMPLETE", "A credential item is still PENDING_PSV.")

    prov["application_status"] = "READY_FOR_REVIEW"
    touch(prov)
    recompute_provider(prov, recompute_readiness=True)
    return success_object(serialize(prov), 200)


@bp.route("/providers/<rid>/start-recredentialing", methods=["POST"])
def start_recredentialing(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist"})
    prov = get_provider(rid)

    if prov["recred_state"] != "RECRED_DUE":
        raise err("ERR_RECRED_NOT_DUE", "Provider is not in RECRED_DUE.")

    prov["recred_state"] = "IN_RECREDENTIALING"
    prov["application_status"] = "IN_VERIFICATION"
    touch(prov)
    # conditional cascade: VERIFIED items whose expirable_band != VALID -> PENDING_PSV
    for ci in store.credential_items.values():
        if (ci["provider_id"] == rid
                and ci["verification_state"] == "VERIFIED"
                and ci["expirable_band"] != "VALID"):
            ci["verification_state"] = "PENDING_PSV"
            touch(ci)
    # posture recompute (recred_state changed); readiness reflects RECRED state
    recompute_provider(prov, recompute_readiness=True)
    return success_object(serialize(prov), 200)


# ---------------------------------------------------------------------------
# Credential items
# ---------------------------------------------------------------------------
@bp.route("/providers/<rid>/credential-items", methods=["POST"])
def create_credential_item(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist"})
    prov = get_provider(rid)
    body = require_body()

    item_type = body.get("item_type")
    if item_type not in ("STATE_LICENSE", "DEA_REGISTRATION", "BOARD_CERTIFICATION"):
        raise err("ERR_INVALID_REQUEST", "item_type is invalid.")
    identifier = body.get("identifier")
    if not isinstance(identifier, str) or identifier.strip() == "":
        raise err("ERR_INVALID_REQUEST", "identifier is required.")
    issued = body.get("issued_date")
    expiration = body.get("expiration_date")
    issued_dt = parse_iso8601(issued, "issued_date")
    expiration_dt = parse_iso8601(expiration, "expiration_date")
    if not (to_epoch_ms(expiration_dt) > to_epoch_ms(issued_dt)):
        raise err("ERR_INVALID_REQUEST", "expiration_date must be strictly after issued_date.")

    # interval-overlap check (priority 5.5): same item_type, closed-closed,
    # adjacency allowed -> reject strict interior overlap.
    new_issued = to_epoch_ms(issued_dt)
    new_expiration = to_epoch_ms(expiration_dt)
    for ci in store.credential_items.values():
        if ci["provider_id"] != rid or ci["item_type"] != item_type:
            continue
        ex_issued = to_epoch_ms(parse_iso8601(ci["issued_date"]))
        ex_expiration = to_epoch_ms(parse_iso8601(ci["expiration_date"]))
        # strict overlap: a.issued < b.expiration AND b.issued < a.expiration
        if new_issued < ex_expiration and ex_issued < new_expiration:
            raise err("ERR_CREDENTIAL_INTERVAL_OVERLAP",
                      "Credential interval overlaps an existing same-type item.")

    org = store.orgs.get(prov["org_id"])
    rec = make_record("credential_items", {
        "provider_id": rid,
        "item_type": item_type,
        "identifier": identifier,
        "issued_date": issued,
        "expiration_date": expiration,
        "verification_state": "UNVERIFIED",
        "expirable_band": "VALID",
    })
    rec["expirable_band"] = compute_expirable_band(rec, org)
    return success_object(serialize(rec), 201)


@bp.route("/providers/<rid>/credential-items", methods=["GET"])
def list_credential_items(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist", "MedicalDirector",
                        "ComplianceOfficer", "SystemAdmin"})
    get_provider(rid)
    limit, offset = parse_pagination()
    rows = [c for c in store.credential_items.values() if c["provider_id"] == rid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Sanctions screenings
# ---------------------------------------------------------------------------
@bp.route("/providers/<rid>/sanctions-screenings", methods=["POST"])
def create_screening(rid):
    _, role = require_auth()
    require_role(role, {"ComplianceOfficer"})
    prov = get_provider(rid)
    body = require_body()

    source_id = body.get("sanctions_source_id")
    if not isinstance(source_id, str) or source_id.strip() == "":
        raise err("ERR_INVALID_REQUEST", "sanctions_source_id is required.")
    # body FK: source must exist and belong to same org as the provider
    # (priority 4, before other field validation)
    src = store.sanctions_sources.get(source_id)
    if src is None or src["org_id"] != prov["org_id"]:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND",
                  "sanctions_source_id does not reference an in-org sanctions source.")

    result = body.get("result")
    if result not in ("CLEAR", "HIT"):
        raise err("ERR_INVALID_REQUEST", "result must be CLEAR or HIT.")
    resolution_note = body.get("resolution_note")
    if resolution_note is not None and not isinstance(resolution_note, str):
        raise err("ERR_INVALID_REQUEST", "resolution_note must be a string.")

    org = store.orgs.get(prov["org_id"])
    rec = make_record("sanctions_screenings", {
        "provider_id": rid,
        "sanctions_source_id": source_id,
        "screened_at": org["current_utc"],
        "result": result,
        "status": "OPEN",
        "resolution_note": resolution_note,
    })
    # recompute sanction_score & posture (HIT may drive EXCLUDED)
    recompute_provider(prov, recompute_readiness=True)
    return success_object(serialize(rec), 201)


@bp.route("/providers/<rid>/sanctions-screenings", methods=["GET"])
def list_provider_screenings(rid):
    _, role = require_auth()
    require_role(role, {"ComplianceOfficer", "CredentialingSpecialist",
                        "MedicalDirector", "SystemAdmin"})
    get_provider(rid)
    limit, offset = parse_pagination()
    rows = [s for s in store.sanctions_screenings.values() if s["provider_id"] == rid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)

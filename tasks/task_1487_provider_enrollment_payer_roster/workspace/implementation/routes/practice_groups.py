"""Practice groups, providers (with CAQH auto-creation), provider termination."""
from flask import Blueprint, request

from db import base_fields, store, touch
from errors import (
    ApiError,
    ERR_DUPLICATE_NPI,
    ERR_TERMINATION_DATE_INVALID,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, require_roles
from response import list_response, success_object
from serializers import provider_json, pub
from services import (
    ACTIVE_RECORD_STATES,
    IN_FLIGHT_APP_STATES,
    claim_order,
    claims_of,
    records_of,
    terminate_record,
)
from validate import body, req_date, req_str

bp = Blueprint("practice_groups", __name__)


@bp.post("/api/practice-groups")
@require_roles("ComplianceOfficer")
def create_practice_group():
    b = body()
    grp = base_fields()
    grp.update(
        {
            "name": req_str(b, "name"),
            "tax_id": req_str(b, "tax_id"),
            "group_npi": req_str(b, "group_npi"),
        }
    )
    store.practice_groups[grp["id"]] = grp
    return success_object(pub(grp), 201)


@bp.get("/api/practice-groups/<gid>")
@require_roles(*ALL_ROLES)
def get_practice_group(gid):
    grp = store.practice_groups.get(gid)
    if grp is None:
        raise not_found("PracticeGroup")
    return success_object(pub(grp))


@bp.post("/api/practice-groups/<gid>/providers")
@require_roles("EnrollmentSpecialist")
def create_provider(gid):
    grp = store.practice_groups.get(gid)
    if grp is None:
        raise not_found("PracticeGroup")
    b = body()
    npi = req_str(b, "npi")
    full_name = req_str(b, "full_name")
    specialty = req_str(b, "specialty")
    for p in store.providers.values():
        if p["npi"] == npi:
            raise ApiError(ERR_DUPLICATE_NPI, 409, "A provider with this npi already exists")
    prov = base_fields()
    prov.update(
        {
            "practice_group_id": gid,
            "npi": npi,
            "full_name": full_name,
            "specialty": specialty,
            "status": "ACTIVE",
            "termination_date": None,
            "termination_reason": None,
        }
    )
    store.providers[prov["id"]] = prov
    # Auto-create exactly one CAQH profile per provider.
    prof = base_fields()
    prof.update(
        {
            "provider_id": prov["id"],
            "status": "NEVER_ATTESTED",
            "last_attested_at": None,
            "due_at": None,
        }
    )
    store.caqh_profiles[prof["id"]] = prof
    return success_object(provider_json(prov), 201)


@bp.get("/api/practice-groups/<gid>/providers")
@require_roles(*ALL_ROLES)
def list_group_providers(gid):
    grp = store.practice_groups.get(gid)
    if grp is None:
        raise not_found("PracticeGroup")
    status = request.args.get("status")
    items = [
        p for p in store.providers.values()
        if p["practice_group_id"] == gid and (status is None or p["status"] == status)
    ]
    return list_response(items, provider_json)


@bp.get("/api/providers/<pid>")
@require_roles(*ALL_ROLES)
def get_provider(pid):
    prov = store.providers.get(pid)
    if prov is None:
        raise not_found("Provider")
    return success_object(provider_json(prov))


@bp.post("/api/providers/<pid>/terminate")
@require_roles("ComplianceOfficer")
def terminate_provider(pid):
    prov = store.providers.get(pid)
    if prov is None:
        raise not_found("Provider")
    b = body()
    t = req_date(b, "termination_effective_date")
    reason = req_str(b, "reason")
    if prov["status"] != "ACTIVE":
        raise invalid_state("Provider is not ACTIVE")
    # Every active-record effective_date must be <= the termination date.
    affected = sorted(
        (r for r in records_of(pid) if r["status"] in ACTIVE_RECORD_STATES),
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    for r in affected:
        if r["effective_date"] > t:
            raise ApiError(
                ERR_TERMINATION_DATE_INVALID,
                422,
                "termination_effective_date is earlier than an active enrollment's effective_date",
            )
    # Depth-3 cascade: provider -> records -> claims -> balances.
    prov["status"] = "TERMINATED"
    prov["termination_date"] = t
    prov["termination_reason"] = reason
    touch(prov)
    for r in affected:
        terminate_record(r, t)
    # Remaining HELD claims of the provider (no covering record) are denied.
    held = sorted(
        (c for c in claims_of(pid) if c["status"] == "HELD"), key=claim_order
    )
    for c in held:
        c["status"] = "DENIED"
        c["denial_reason"] = "ENROLLMENT_TERMINATED"
        touch(c)
    # In-flight applications are withdrawn by the system.
    for a in store.applications.values():
        if a["provider_id"] == pid and a["status"] in IN_FLIGHT_APP_STATES:
            a["status"] = "WITHDRAWN"
            touch(a)
    return success_object(provider_json(prov))


@bp.get("/api/providers/<pid>/caqh-profile")
@require_roles(*ALL_ROLES)
def get_provider_caqh_profile(pid):
    prov = store.providers.get(pid)
    if prov is None:
        raise not_found("Provider")
    prof = next(
        (p for p in store.caqh_profiles.values() if p["provider_id"] == pid), None
    )
    items = [prof] if prof is not None else []
    return list_response(items, pub)


@bp.get("/api/providers/<pid>/roster-lines")
@require_roles(*ALL_ROLES)
def list_provider_roster_lines(pid):
    prov = store.providers.get(pid)
    if prov is None:
        raise not_found("Provider")
    items = [l for l in store.roster_lines.values() if l["provider_id"] == pid]
    return list_response(items, pub)

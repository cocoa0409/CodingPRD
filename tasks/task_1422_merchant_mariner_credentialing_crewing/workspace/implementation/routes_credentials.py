"""Credential issuance, renewal loop, revocation, prerequisite chains (PRD 3.3)."""

from flask import Blueprint, request

from db import store
from errors import err
from helpers import (
    get_body,
    opt_str,
    paginate,
    req_dt,
    req_enum,
    req_str,
    require_roles,
    scope_mariner_id,
    scope_mariner_resource,
    sorted_items,
)
from response import success
from serialize import ser_credential
from services import (
    UPGRADE_REQUIREMENTS,
    credential_is_valid,
    recompute_mariner_with_cascade,
    upgrade_eligibility,
)

bp = Blueprint("credentials", __name__)

CREDENTIAL_TYPES = ("MMC_BASE", "OFFICER_ENDORSEMENT", "STCW", "TANKER", "SPECIAL")

ALL_ROLES = (
    "FleetAdmin",
    "CrewingManager",
    "CredentialingOfficer",
    "PortCaptain",
    "UnionDispatcher",
    "Mariner",
)


def _get_mariner(mariner_id):
    m = store.mariners.get(mariner_id)
    if m is None:
        raise err("ERR_MARINER_NOT_FOUND", "Mariner %s not found" % mariner_id)
    return m


def _get_credential_under_mariner(mariner_id, credential_id):
    c = store.credentials.get(credential_id)
    if c is None or c["mariner_id"] != mariner_id:
        raise err("ERR_CREDENTIAL_NOT_FOUND", "Credential %s not found" % credential_id)
    return c


@bp.route("/mariners/<mariner_id>/credentials", methods=["POST"])
@require_roles("CredentialingOfficer")
def create_credential(mariner_id):
    m = _get_mariner(mariner_id)
    body = get_body()
    prereq_id = body.get("prerequisite_credential_id")
    prereq = None
    if prereq_id is not None:
        # Body FK existence (pipeline step 5).
        prereq = store.credentials.get(prereq_id)
        if prereq is None:
            raise err(
                "ERR_CREDENTIAL_NOT_FOUND",
                "Credential %s not found" % prereq_id,
            )
    credential_type = req_enum(body, "credential_type", CREDENTIAL_TYPES)
    endorsement_code = req_str(body, "endorsement_code")
    issue_date = req_dt(body, "issue_date")
    expiry_date = req_dt(body, "expiry_date")
    # Endorsement chain (pipeline step 11): same mariner and VALID at issuance.
    if prereq is not None:
        if prereq["mariner_id"] != m["id"] or not credential_is_valid(
            prereq, store.clock
        ):
            raise err(
                "ERR_ENDORSEMENT_PREREQUISITE_INVALID",
                "Prerequisite credential must belong to the mariner and be VALID",
            )
    # Regulated upgrade gate.
    if (
        credential_type == "OFFICER_ENDORSEMENT"
        and endorsement_code in UPGRADE_REQUIREMENTS
    ):
        if not upgrade_eligibility(m, endorsement_code)["eligible"]:
            raise err(
                "ERR_UPGRADE_REQUIREMENTS_NOT_MET",
                "Upgrade requirements for %s are not met" % endorsement_code,
            )
    c = {
        "mariner_id": m["id"],
        "credential_type": credential_type,
        "endorsement_code": endorsement_code,
        "prerequisite_credential_id": prereq_id,
        "issue_date": issue_date,
        "expiry_date": expiry_date,
        "status": "VALID",
        "renewal_count": 0,
    }
    store.stamp(c)
    store.credentials[c["id"]] = c
    recompute_mariner_with_cascade(m)
    return success(ser_credential(c), code=201)


@bp.route("/mariners/<mariner_id>/credentials", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_mariner_credentials(mariner_id):
    scope_mariner_id(mariner_id)
    m = _get_mariner(mariner_id)
    items = [c for c in store.credentials.values() if c["mariner_id"] == m["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_credential(c) for c in page], response_type="array", pagination=meta
    )


@bp.route("/credentials", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_credentials():
    items = list(store.credentials.values())
    mariner_id = request.args.get("mariner_id")
    prereq = request.args.get("prerequisite_credential_id")
    status = request.args.get("status")
    endorsement = request.args.get("endorsement_code")
    if mariner_id is not None:
        items = [c for c in items if c["mariner_id"] == mariner_id]
    if prereq is not None:
        items = [c for c in items if c["prerequisite_credential_id"] == prereq]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if endorsement is not None:
        items = [c for c in items if c["endorsement_code"] == endorsement]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_credential(c) for c in page], response_type="array", pagination=meta
    )


@bp.route("/credentials/<credential_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_credential(credential_id):
    c = store.credentials.get(credential_id)
    if c is None:
        raise err("ERR_CREDENTIAL_NOT_FOUND", "Credential %s not found" % credential_id)
    scope_mariner_resource(c["mariner_id"])
    return success(ser_credential(c))


@bp.route(
    "/mariners/<mariner_id>/credentials/<credential_id>/submit-renewal",
    methods=["POST"],
)
@require_roles("Mariner", "CredentialingOfficer")
def submit_renewal(mariner_id, credential_id):
    scope_mariner_id(mariner_id)
    m = _get_mariner(mariner_id)
    c = _get_credential_under_mariner(mariner_id, credential_id)
    if c["status"] not in ("VALID", "EXPIRED"):
        raise err(
            "ERR_CREDENTIAL_NOT_RENEWABLE",
            "Only VALID or EXPIRED credentials can be submitted for renewal",
        )
    c["status"] = "RENEWAL_PENDING"
    store.bump(c)
    recompute_mariner_with_cascade(m)
    return success(ser_credential(c))


@bp.route(
    "/mariners/<mariner_id>/credentials/<credential_id>/approve-renewal",
    methods=["POST"],
)
@require_roles("CredentialingOfficer")
def approve_renewal(mariner_id, credential_id):
    m = _get_mariner(mariner_id)
    c = _get_credential_under_mariner(mariner_id, credential_id)
    body = get_body()
    new_issue = req_dt(body, "new_issue_date")
    new_expiry = req_dt(body, "new_expiry_date")
    if not new_expiry > new_issue:
        raise err(
            "ERR_INVALID_REQUEST",
            "new_expiry_date must be strictly later than new_issue_date",
        )
    if c["status"] != "RENEWAL_PENDING":
        raise err(
            "ERR_RENEWAL_NOT_PENDING",
            "Credential must be RENEWAL_PENDING to approve a renewal",
        )
    if not new_expiry > store.clock:
        raise err(
            "ERR_INVALID_REQUEST", "new_expiry_date must be later than the current time"
        )
    if c["prerequisite_credential_id"] is not None:
        prereq = store.credentials.get(c["prerequisite_credential_id"])
        if prereq is None or not credential_is_valid(prereq, store.clock):
            raise err(
                "ERR_ENDORSEMENT_PREREQUISITE_INVALID",
                "Prerequisite credential must be VALID to approve the renewal",
            )
    c["status"] = "VALID"
    c["issue_date"] = new_issue
    c["expiry_date"] = new_expiry
    c["renewal_count"] += 1
    store.bump(c)
    # Restore dependents stranded in SUSPENDED_PREREQ.
    for dep in store.credentials.values():
        if (
            dep["prerequisite_credential_id"] == c["id"]
            and dep["status"] == "SUSPENDED_PREREQ"
        ):
            dep["status"] = "VALID"
            store.bump(dep)
    recompute_mariner_with_cascade(m)
    return success(ser_credential(c))


@bp.route(
    "/mariners/<mariner_id>/credentials/<credential_id>/deny-renewal",
    methods=["POST"],
)
@require_roles("CredentialingOfficer")
def deny_renewal(mariner_id, credential_id):
    m = _get_mariner(mariner_id)
    c = _get_credential_under_mariner(mariner_id, credential_id)
    get_body()  # optional reason
    if c["status"] != "RENEWAL_PENDING":
        raise err(
            "ERR_RENEWAL_NOT_PENDING",
            "Credential must be RENEWAL_PENDING to deny a renewal",
        )
    c["status"] = "VALID"  # old dates kept; the next sweep re-expires if past
    store.bump(c)
    recompute_mariner_with_cascade(m)
    return success(ser_credential(c))


@bp.route(
    "/mariners/<mariner_id>/credentials/<credential_id>/revoke", methods=["POST"]
)
@require_roles("CredentialingOfficer")
def revoke_credential(mariner_id, credential_id):
    m = _get_mariner(mariner_id)
    c = _get_credential_under_mariner(mariner_id, credential_id)
    body = get_body()
    req_str(body, "reason")
    if c["status"] != "VALID":
        raise err("ERR_CREDENTIAL_NOT_VALID", "Only a VALID credential can be revoked")
    c["status"] = "REVOKED"
    store.bump(c)
    # Prerequisite cascade: dependents in VALID / RENEWAL_PENDING.
    for dep in store.credentials.values():
        if dep["prerequisite_credential_id"] == c["id"] and dep["status"] in (
            "VALID",
            "RENEWAL_PENDING",
        ):
            dep["status"] = "SUSPENDED_PREREQ"
            store.bump(dep)
    recompute_mariner_with_cascade(m)
    return success(ser_credential(c))


@bp.route(
    "/mariners/<mariner_id>/credentials/<credential_id>/reinstate", methods=["POST"]
)
@require_roles("CredentialingOfficer")
def reinstate_credential(mariner_id, credential_id):
    m = _get_mariner(mariner_id)
    c = _get_credential_under_mariner(mariner_id, credential_id)
    if c["status"] != "SUSPENDED_PREREQ":
        raise err(
            "ERR_INVALID_STATE",
            "Only a SUSPENDED_PREREQ credential can be reinstated",
        )
    if c["prerequisite_credential_id"] is not None:
        prereq = store.credentials.get(c["prerequisite_credential_id"])
        if prereq is None or not credential_is_valid(prereq, store.clock):
            raise err(
                "ERR_ENDORSEMENT_PREREQUISITE_INVALID",
                "Prerequisite credential must be VALID to reinstate",
            )
    c["status"] = "VALID"
    store.bump(c)
    recompute_mariner_with_cascade(m)
    return success(ser_credential(c))

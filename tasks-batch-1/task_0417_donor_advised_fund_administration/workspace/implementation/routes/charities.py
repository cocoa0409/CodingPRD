"""Charity endpoints and the vetting lifecycle (PRD 3.2)."""
from flask import Blueprint, request

from db import db, common_create_fields, touch, LOCK
from errors import err
from middleware import get_identity, require_role, get_json_body, get_pagination, paginate
from response import object_response, array_response
from services import serialize
from services.accounts import recompute_account
from services.lookup import (
    get_or_404, require_string, require_enum, optional_bool, optional_string,
    filtered_sorted,
)

bp = Blueprint("charities", __name__)

CREATE_ROLES = {"ComplianceOfficer", "SponsorAdmin"}
READ_ROLES = {"ComplianceOfficer", "SponsorAdmin", "DonorAdvisor", "GrantOfficer"}
DECISIONS = {"APPROVE", "WATCHLIST", "REVOKE"}


@bp.post("/daf/charities")
def create_charity():
    _, role = get_identity()
    require_role(role, CREATE_ROLES)
    body = get_json_body()
    sponsor_id = require_string(body, "sponsor_id")
    legal_name = require_string(body, "legal_name")
    ein = require_string(body, "ein")
    ntee_code = require_string(body, "ntee_code")
    is_private_foundation = optional_bool(body, "is_private_foundation", False)

    with LOCK:
        get_or_404(db.sponsors, sponsor_id)  # body FK existence
        # PRD 3.2: EIN unique among non-REVOKED charities under the same sponsor.
        for c in db.charities.values():
            if (c["sponsor_id"] == sponsor_id and c["ein"] == ein
                    and c["status"] != "REVOKED"):
                raise err("ERR_DUPLICATE_CHARITY_EIN")
        charity = common_create_fields()
        charity.update({
            "sponsor_id": sponsor_id,
            "legal_name": legal_name,
            "ein": ein,
            "ntee_code": ntee_code,
            "is_private_foundation": is_private_foundation,
            "status": "PENDING_VETTING",
            "vetting_note": None,
        })
        db.charities[charity["id"]] = charity
    return object_response(serialize.charity(charity), status=201)


@bp.get("/daf/charities/<charity_id>")
def get_charity(charity_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    charity = get_or_404(db.charities, charity_id)
    return object_response(serialize.charity(charity))


@bp.get("/daf/charities")
def list_charities():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    items = filtered_sorted(db.charities, {
        "sponsor_id": request.args.get("sponsor_id"),
        "status": request.args.get("status"),
        "ein": request.args.get("ein"),
    })
    page, meta = paginate(items, limit, offset)
    return array_response([serialize.charity(c) for c in page], meta)


@bp.post("/daf/charities/<charity_id>/vet")
def vet_charity(charity_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})  # only ComplianceOfficer (PRD 3.2)
    body = get_json_body()
    decision = require_enum(body, "decision", DECISIONS)
    vetting_note = optional_string(body, "vetting_note", None)

    with LOCK:
        charity = get_or_404(db.charities, charity_id)
        status = charity["status"]
        # REVOKED is terminal -> any decision is an invalid state transition.
        if status == "REVOKED":
            raise err("ERR_INVALID_STATE")

        if decision == "APPROVE":
            # Valid from PENDING_VETTING or WATCHLISTED. Re-approving VETTED is invalid.
            if status not in ("PENDING_VETTING", "WATCHLISTED"):
                raise err("ERR_INVALID_STATE")
            # Eligibility gate: private foundation cannot be VETTED.
            if charity["is_private_foundation"]:
                raise err("ERR_INELIGIBLE_GRANTEE")
            charity["status"] = "VETTED"
            charity["vetting_note"] = vetting_note
            touch(charity)

        elif decision == "WATCHLIST":
            # Valid from PENDING_VETTING or VETTED. Re-watchlisting WATCHLISTED is invalid.
            if status not in ("PENDING_VETTING", "VETTED"):
                raise err("ERR_INVALID_STATE")
            charity["status"] = "WATCHLISTED"
            charity["vetting_note"] = vetting_note
            touch(charity)

        elif decision == "REVOKE":
            # Valid from VETTED or WATCHLISTED.
            if status not in ("VETTED", "WATCHLISTED"):
                raise err("ERR_INVALID_STATE")
            charity["status"] = "REVOKED"
            charity["vetting_note"] = vetting_note
            touch(charity)
            _revoke_cascade(charity_id)

    return object_response(serialize.charity(charity))


def _revoke_cascade(charity_id):
    """PRD 3.2/2.8: every SCHEDULED grant referencing this charity -> CANCELLED;
    each affected account's committed_grants_cents and grantable_balance_cents
    recomputed; cascaded resources get updated_at + version bumps."""
    affected_accounts = set()
    for g in db.grants.values():
        if g["charity_id"] == charity_id and g["status"] == "SCHEDULED":
            g["status"] = "CANCELLED"
            touch(g)
            affected_accounts.add(g["donor_account_id"])
    for account_id in affected_accounts:
        account = db.accounts[account_id]
        recompute_account(account)
        touch(account)

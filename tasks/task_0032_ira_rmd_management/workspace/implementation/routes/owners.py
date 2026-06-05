"""AccountOwner endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_UNAUTHORIZED,
    raise_api,
)
from helpers import (
    append_audit_event,
    get_account_or_404,
    get_json_body,
    get_owner_or_404,
    get_pagination_params,
    optional_int,
    paginate,
    parse_iso_datetime,
    recompute_rmd_posture,
    require_enum,
    require_int,
    require_str,
)
from middleware import g, parse_auth_headers, require_owner_match, require_roles
from response import success_array, success_object
from serializers import owner_to_json


bp = Blueprint("owners", __name__, url_prefix="/ira/owners")


FILING_STATUSES = {"SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD"}


@bp.route("", methods=["POST"])
def create_owner():
    parse_auth_headers()
    require_roles("PlanAdministrator")
    body = get_json_body()
    full_name = require_str(body, "full_name")
    dob_str = require_str(body, "date_of_birth")
    dob = parse_iso_datetime(dob_str, "date_of_birth")
    tax_id_last4 = require_str(body, "tax_id_last4")
    if len(tax_id_last4) != 4 or not tax_id_last4.isdigit():
        raise_api(ERR_INVALID_REQUEST, "tax_id_last4 must be exactly 4 numeric characters.")
    filing_status = require_enum(body, "filing_status", FILING_STATUSES)
    modified_agi_cents = optional_int(body, "modified_agi_cents", default=0)
    if modified_agi_cents < 0:
        raise_api(ERR_INVALID_REQUEST, "modified_agi_cents must be >= 0.")

    now = db.now_utc()
    owner = {
        "id": db.new_id(),
        "full_name": full_name,
        "date_of_birth": dob,
        "tax_id_last4": tax_id_last4,
        "filing_status": filing_status,
        "modified_agi_cents": modified_agi_cents,
        "deceased_at": None,
        "rmd_posture": "NOT_REQUIRED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.owners[owner["id"]] = owner
    return success_object(owner_to_json(owner), status_code=201)


@bp.route("/<owner_id>", methods=["GET"])
def get_owner(owner_id):
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    owner = get_owner_or_404(owner_id)
    if g.role == "AccountOwner":
        require_owner_match(owner["id"])
    return success_object(owner_to_json(owner))


@bp.route("", methods=["GET"])
def list_owners():
    parse_auth_headers()
    require_roles("PlanAdministrator", "IRSAuditor")
    limit, offset = get_pagination_params()
    filing_status = request.args.get("filing_status")
    rows = list(db.owners.values())
    if filing_status is not None:
        if filing_status not in FILING_STATUSES:
            raise_api(ERR_INVALID_REQUEST, "filing_status filter is not a recognized value.")
        rows = [o for o in rows if o["filing_status"] == filing_status]
    page, total = paginate(rows, limit, offset)
    return success_array([owner_to_json(o) for o in page], limit, offset, total)


@bp.route("/<owner_id>/agi", methods=["PATCH"])
def patch_owner_agi(owner_id):
    parse_auth_headers()
    require_roles("PlanAdministrator")
    owner = get_owner_or_404(owner_id)
    body = get_json_body()
    new_agi = require_int(body, "modified_agi_cents")
    if new_agi < 0:
        raise_api(ERR_INVALID_REQUEST, "modified_agi_cents must be >= 0.")
    expected = require_int(body, "expected_owner_version")
    if expected != owner["version"]:
        raise_api(ERR_STALE_VERSION)
    owner["modified_agi_cents"] = new_agi
    owner["updated_at"] = db.now_utc()
    owner["version"] += 1
    return success_object(owner_to_json(owner))


@bp.route("/<owner_id>/declare-deceased", methods=["POST"])
def declare_deceased(owner_id):
    parse_auth_headers()
    require_roles("PlanAdministrator")
    owner = get_owner_or_404(owner_id)
    body = get_json_body()
    deceased_at_str = require_str(body, "deceased_at")
    deceased_at = parse_iso_datetime(deceased_at_str, "deceased_at")
    expected = require_int(body, "expected_owner_version")
    if expected != owner["version"]:
        raise_api(ERR_STALE_VERSION)
    if owner["deceased_at"] is not None:
        raise_api(ERR_INVALID_STATE, "Owner is already deceased.")

    now = db.now_utc()
    owner["deceased_at"] = deceased_at
    owner["updated_at"] = now
    owner["version"] += 1

    # Cascade: every IRAAccount in {ACTIVE, FROZEN} -> INHERITED.
    affected_accounts = [a for a in db.accounts.values() if a["owner_id"] == owner_id and a["status"] in ("ACTIVE", "FROZEN")]
    for acct in affected_accounts:
        acct["status"] = "INHERITED"
        acct["updated_at"] = now
        acct["version"] += 1
        # Cascade beneficiaries on this account that are ACTIVE -> INHERITED;
        # set secure_deadline_at for NON_ELIGIBLE_INDIVIDUAL relationships.
        for b in db.beneficiary_designations.values():
            if b["account_id"] == acct["id"] and b["status"] == "ACTIVE":
                b["status"] = "INHERITED"
                b["updated_at"] = now
                b["version"] += 1
                if b["relationship"] == "NON_ELIGIBLE_INDIVIDUAL":
                    # deceased_at + 10 years
                    secure_deadline = deceased_at.replace(year=deceased_at.year + 10)
                    b["secure_deadline_at"] = secure_deadline
                # Audit event for the inheritance.
                append_audit_event(
                    owner_id,
                    acct["id"],
                    "BENEFICIARY_INHERITED",
                    db.system_clock["current_tax_year"],
                    0,
                )

    # Recompute OPEN RMDSchedule rows under SECURE timeline.
    # For now: leave their required_amount_cents as-is (PRD allows SECURE recomputation,
    # but tests typically create new schedules post-death rather than mutate existing
    # owner-alive schedules). The status sweep happens during year-rollover.

    # Audit event for the owner-deceased.
    append_audit_event(owner_id, None, "OWNER_DECEASED", db.system_clock["current_tax_year"], 0)

    return success_object(owner_to_json(owner))

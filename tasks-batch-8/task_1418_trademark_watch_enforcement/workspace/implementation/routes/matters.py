"""EnforcementMatter endpoints (PRD 3.4) plus nested deadline/letter creates."""

from flask import Blueprint

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_PENDING_DEADLINES,
    ERR_MATTER_NOT_ACTIVE,
)
from middleware import require_roles, enforce_client_scope
from response import success
from services import domain
from services.domain import (
    ser_enforcement_matter, ser_deadline, ser_letter, open_deadline_count,
    deadline_variant, compute_due_at, moot_cascade, reopen_matter,
)
from util import (
    get_payload, reject_unknown_fields, require_string, require_enum,
    require_int, optional_int, require_datetime, stamp_new, touch, fmt_business,
)
from routes.common import do_list

bp = Blueprint("enforcement_matters", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")
OUTCOMES = ("FAVORABLE", "ADVERSE", "SETTLED")
DEADLINE_TYPES = ("OPPOSITION_WINDOW", "RESPONSE_DUE", "OFFICE_ACTION", "RENEWAL", "CUSTOM")
DEMAND_TYPES = ("CEASE_USE", "CANCEL_REGISTRATION", "DELIST_MARKETPLACE")


def _get_matter(matter_id):
    matter = db.enforcement_matters.get(matter_id)
    if matter is None:
        raise_error(ERR_NOT_FOUND, "EnforcementMatter not found")
    return matter


@bp.route("/brand/enforcement-matters", methods=["GET"])
def list_matters():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.enforcement_matters.values(), ser_enforcement_matter,
                   [("client_id", "client_id", None),
                    ("trademark_record_id", "trademark_record_id", None),
                    ("watch_alert_id", "watch_alert_id", None),
                    ("status", "status", None)],
                   user_id, role, "enforcement_matter")


@bp.route("/brand/enforcement-matters/<matter_id>", methods=["GET"])
def get_matter(matter_id):
    user_id, role = require_roles(*READ_ROLES)
    matter = _get_matter(matter_id)
    enforce_client_scope(user_id, role, matter["client_id"])
    return success(ser_enforcement_matter(matter), 200)


@bp.route("/brand/enforcement-matters/<matter_id>/resolve", methods=["POST"])
def resolve_matter(matter_id):
    user_id, role = require_roles("PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"outcome"})
    outcome = require_enum(body, "outcome", OUTCOMES)
    matter = _get_matter(matter_id)
    if matter["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "resolve is declared only from ACTIVE")
    # Resolve requires open_deadline_count == 0.
    if open_deadline_count(matter["id"]) != 0:
        raise_error(ERR_PENDING_DEADLINES, "Matter has open deadlines")
    matter["status"] = "RESOLVED"
    matter["resolution_outcome"] = outcome
    touch(matter)
    # Record outcome cascade (PRD 3.2): only fires while the record is
    # UNDER_CHALLENGE for challenge-type matters.
    record = db.trademark_records.get(matter["trademark_record_id"])
    if record is not None and record["status"] == "UNDER_CHALLENGE":
        if outcome == "ADVERSE" and matter["matter_type"] in ("OPPOSITION", "CANCELLATION"):
            record["status"] = "CANCELLED"
            touch(record)
            moot_cascade(record)
        elif outcome in ("FAVORABLE", "SETTLED"):
            if matter["matter_type"] == "OPPOSITION":
                record["status"] = "PUBLISHED"
                touch(record)
            elif matter["matter_type"] == "CANCELLATION":
                record["status"] = "REGISTERED"
                touch(record)
    return success(ser_enforcement_matter(matter), 200)


@bp.route("/brand/enforcement-matters/<matter_id>/reopen", methods=["POST"])
def reopen_matter_endpoint(matter_id):
    user_id, role = require_roles("PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    matter = _get_matter(matter_id)
    if matter["status"] != "RESOLVED":
        raise_error(ERR_INVALID_STATE, "reopen is declared only from RESOLVED")
    reopen_matter(matter, db.clock.now())
    return success(ser_enforcement_matter(matter), 200)


# ---------------------------------------------------------------------------
# Nested: POST /brand/enforcement-matters/{id}/deadlines (PRD 3.5)
# ---------------------------------------------------------------------------

@bp.route("/brand/enforcement-matters/<matter_id>/deadlines", methods=["POST"])
def docket_deadline(matter_id):
    user_id, role = require_roles("Paralegal", "AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"deadline_type", "statutory_basis", "basis_date",
                                 "offset_days", "max_extensions"})
    deadline_type = require_enum(body, "deadline_type", DEADLINE_TYPES)
    statutory_basis = require_string(body, "statutory_basis")
    basis_date = require_datetime(body, "basis_date")
    offset_days = require_int(body, "offset_days", minimum=1)
    max_extensions = optional_int(body, "max_extensions", default=3, minimum=0)
    matter = _get_matter(matter_id)
    # Docketing requires an ACTIVE matter.
    if matter["status"] != "ACTIVE":
        raise_error(ERR_MATTER_NOT_ACTIVE, "Deadlines may be docketed only on ACTIVE matters")
    variant = deadline_variant(deadline_type)
    due = compute_due_at(variant, basis_date, offset_days)
    deadline = {
        "enforcement_matter_id": matter["id"],
        "deadline_type": deadline_type,
        "statutory_basis": statutory_basis,
        "basis_date": fmt_business(basis_date),
        "offset_days": offset_days,
        "computation_variant": variant,
        "computed_due_at": fmt_business(due),
        "extension_count": 0,
        "max_extensions": max_extensions,
        "docketed_by_user_id": user_id,
        "verified_by_user_id": None,
        "satisfied_at": None,
        "satisfied_late": False,
        "requires_partner_review": False,
        "status": "DOCKETED",
    }
    stamp_new(deadline)
    db.deadlines[deadline["id"]] = deadline
    return success(ser_deadline(deadline), 201)


# ---------------------------------------------------------------------------
# Nested: POST /brand/enforcement-matters/{id}/cease-desist-letters (PRD 3.6)
# ---------------------------------------------------------------------------

@bp.route("/brand/enforcement-matters/<matter_id>/cease-desist-letters", methods=["POST"])
def draft_letter(matter_id):
    user_id, role = require_roles("AssociateAttorney", "PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"demand_type", "recipient_name", "recipient_address",
                                 "response_due_days", "settlement_amount_cents",
                                 "installment_count"})
    demand_type = require_enum(body, "demand_type", DEMAND_TYPES)
    recipient_name = require_string(body, "recipient_name")
    recipient_address = require_string(body, "recipient_address")
    response_due_days = optional_int(body, "response_due_days", default=14, minimum=1)
    settlement_amount_cents = optional_int(body, "settlement_amount_cents", default=None, minimum=0)
    installment_count = optional_int(body, "installment_count", default=1, minimum=1)
    matter = _get_matter(matter_id)
    # Drafting requires an ACTIVE matter.
    if matter["status"] != "ACTIVE":
        raise_error(ERR_MATTER_NOT_ACTIVE, "Letters may be drafted only on ACTIVE matters")
    letter = {
        "enforcement_matter_id": matter["id"],
        "demand_type": demand_type,
        "recipient_name": recipient_name,
        "recipient_address": recipient_address,
        "response_due_days": response_due_days,
        "settlement_amount_cents": settlement_amount_cents,
        "installment_count": installment_count,
        "drafted_by_user_id": user_id,
        "approved_by_user_id": None,
        "issued_at": None,
        "response_due_at": None,
        "reissue_count": 0,
        "installment_schedule": None,
        "status": "DRAFT",
        "_ever_issued": False,
    }
    stamp_new(letter)
    db.cease_desist_letters[letter["id"]] = letter
    return success(ser_letter(letter), 201)

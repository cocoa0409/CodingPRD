"""Compliance filing endpoints (PRD section 3.10).

ISF/AMS filings carry a frozen deadline snapshot from the voyage. Lateness is
strict (submitted_at > deadline_at); a late submission with penalty_status NONE
accrues the statutory penalty against the earliest-created qualifying bond.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BOOKING_INVALID_STATE,
    ERR_BOOKING_NOT_FOUND,
    ERR_FILING_EXISTS,
    ERR_FILING_INVALID_STATE,
    ERR_FILING_NOT_FOUND,
    ERR_VOYAGE_INVALID_STATE,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    get_json_body,
    has_field,
    paginate,
    parse_pagination,
    pub,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("compliance_filings", __name__)

FILING_TYPES = {"ISF", "AMS"}
OUTCOMES = {"ACCEPTED", "REJECTED"}
RESOLUTIONS = {"PAID", "WAIVED"}
FILING_BOOKING_STATES = {"CONFIRMED", "DOCUMENTATION_CLEARED", "LOADED", "DEPARTED"}


def _get_filing(filing_id: str) -> dict:
    filing = db.compliance_filings.get(filing_id)
    if filing is None:
        raise_err(ERR_FILING_NOT_FOUND, "ComplianceFiling id does not exist")
    return filing


@bp.route("/freight/compliance-filings", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_filing(_user_id: str, _role: str):
    body = get_json_body()

    # Band 3: booking FK existence.
    booking = None
    if has_field(body, "booking_id"):
        booking = db.bookings.get(body["booking_id"])
        if booking is None:
            raise_err(ERR_BOOKING_NOT_FOUND, "booking_id does not exist")

    # Band 5: body shape.
    require_string(body, "booking_id")
    filing_type = require_enum(body, "filing_type", FILING_TYPES)

    # Band 6: booking state permits filing.
    if booking["status"] not in FILING_BOOKING_STATES:
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking state does not permit filing creation")

    # Band 10: at most one filing per (booking_id, filing_type).
    for other in db.compliance_filings.values():
        if other["booking_id"] == booking["id"] and other["filing_type"] == filing_type:
            raise_err(ERR_FILING_EXISTS, "A filing already exists for this booking and filing type")

    voyage = db.voyages.get(booking["voyage_id"])
    deadline_at = None
    if voyage is not None:
        deadline_at = voyage["isf_deadline"] if filing_type == "ISF" else voyage["ams_deadline"]

    filing = {
        "booking_id": booking["id"],
        "filing_type": filing_type,
        "deadline_at": deadline_at,
        "submitted_at": None,
        "is_late": False,
        "penalty_status": "NONE",
        "penalty_amount_cents": 0,
        "filed_by_user_id": _user_id,
        "status": "PENDING",
        "_penalty_bond_id": None,
    }
    db.stamp_new(filing)
    db.compliance_filings[filing["id"]] = filing
    return success_object(pub(filing), 201)


@bp.route("/freight/compliance-filings", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_filings(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.compliance_filings.values()))
    items = apply_filters(items, ["booking_id", "filing_type", "status"])
    page, total = paginate(items, limit, offset)
    return success_list([pub(f) for f in page], limit, offset, total)


@bp.route("/freight/compliance-filings/<filing_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_filing(filing_id: str, _user_id: str, _role: str):
    return success_object(pub(_get_filing(filing_id)))


@bp.route("/freight/compliance-filings/<filing_id>/submit", methods=["POST"])
@require_roles("ComplianceOfficer")
def submit_filing(filing_id: str, _user_id: str, _role: str):
    filing = _get_filing(filing_id)
    get_json_body()
    if filing["status"] not in ("PENDING", "REJECTED"):
        raise_err(ERR_FILING_INVALID_STATE, "Filing must be PENDING or REJECTED to submit")
    booking = db.bookings.get(filing["booking_id"])
    if booking is None or booking["status"] not in FILING_BOOKING_STATES:
        raise_err(ERR_BOOKING_INVALID_STATE, "Booking state does not permit filing submission")
    voyage = db.voyages.get(booking["voyage_id"])
    if voyage is not None and voyage["status"] == "BLANKED":
        raise_err(ERR_VOYAGE_INVALID_STATE, "Voyage is BLANKED")

    filing["submitted_at"] = db.now_domain_iso()
    filing["status"] = "SUBMITTED"
    # Lateness is strict: submission exactly AT the deadline is on time.
    filing["is_late"] = db.parse_iso(filing["submitted_at"]) > db.parse_iso(filing["deadline_at"])

    # Penalty accrual: late + not yet accrued (no double accrual; on-time
    # resubmission never retroactively waives).
    if filing["is_late"] and filing["penalty_status"] == "NONE":
        filing["penalty_amount_cents"] = (
            domain.ISF_LATE_PENALTY_CENTS
            if filing["filing_type"] == "ISF"
            else domain.AMS_LATE_PENALTY_CENTS
        )
        filing["penalty_status"] = "ACCRUED"
        bond = domain.select_accrual_bond()
        filing["_penalty_bond_id"] = bond["id"] if bond is not None else None
        if bond is not None:
            domain.recompute_bond_coverage(bond)
    db.touch(filing)
    return success_object(pub(filing))


@bp.route("/freight/compliance-filings/<filing_id>/record-response", methods=["POST"])
@require_roles("ComplianceOfficer")
def record_response(filing_id: str, _user_id: str, _role: str):
    filing = _get_filing(filing_id)
    body = get_json_body()
    outcome = require_enum(body, "outcome", OUTCOMES)
    if filing["status"] != "SUBMITTED":
        raise_err(ERR_FILING_INVALID_STATE, "Filing must be SUBMITTED to record a response")
    filing["status"] = outcome  # ACCEPTED or REJECTED
    db.touch(filing)
    if outcome == "ACCEPTED":
        booking = db.bookings.get(filing["booking_id"])
        if booking is not None:
            domain.reevaluate_doc_gate(booking)
    return success_object(pub(filing))


@bp.route("/freight/compliance-filings/<filing_id>/resolve-penalty", methods=["POST"])
@require_roles("ComplianceOfficer")
def resolve_penalty(filing_id: str, _user_id: str, _role: str):
    filing = _get_filing(filing_id)
    body = get_json_body()
    resolution = require_enum(body, "resolution", RESOLUTIONS)
    if filing["penalty_status"] != "ACCRUED":
        raise_err(ERR_FILING_INVALID_STATE, "Filing has no ACCRUED penalty to resolve")
    filing["penalty_status"] = resolution  # PAID or WAIVED
    db.touch(filing)
    bond_id = filing.get("_penalty_bond_id")
    if bond_id:
        bond = db.surety_bonds.get(bond_id)
        if bond is not None:
            domain.recompute_bond_coverage(bond)
    return success_object(pub(filing))

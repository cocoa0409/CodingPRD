"""Citation endpoints: issue, list, get, pay, appeal, decide-appeal."""
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    bad_request,
    not_found,
    conflict,
    unprocessable,
    forbidden,
    ERR_LOT_NOT_FOUND,
    ERR_CITATION_NOT_FOUND,
    ERR_CITATION_NOT_ISSUED,
    ERR_PLATE_NOT_REGISTERED,
    ERR_APPEAL_ALREADY_EXISTS,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import get_caller, require_roles, require_ownership, ALL_ROLES
from response import success, success_list, parse_pagination
from services.core import (
    new_record,
    serialize,
    touch,
    compute_fine,
    recompute_patron_standing_and_permit_cascade,
    recompute_fund,
    round_half_up,
)

bp = Blueprint("citations", __name__)

VIOLATION_TYPES = ("NO_VALID_PERMIT", "EXPIRED_PERMIT", "WRONG_ZONE", "CLOSED_LOT")
APPEAL_OUTCOMES = ("UPHELD", "REDUCED", "VOIDED")


def _get_citation_or_404(citation_id: str) -> dict:
    record = db.citations.get(citation_id)
    if record is None:
        raise not_found(ERR_CITATION_NOT_FOUND, "No citation with the given id")
    return record


@bp.post("/parking/citations")
def issue_citation():
    caller = get_caller()
    require_roles(caller, ["EnforcementOfficer"])
    body = request.get_json(silent=True) or {}

    lot_id = body.get("lot_id")
    plate_number = body.get("plate_number")
    violation_type = body.get("violation_type")

    # Existence (priority 4): lot
    if not isinstance(lot_id, str) or not lot_id:
        raise bad_request("lot_id is required")
    lot = db.lots.get(lot_id)
    if lot is None:
        raise not_found(ERR_LOT_NOT_FOUND, "No parking lot with the given id")

    # Request shape (priority 6)
    if not isinstance(plate_number, str) or not plate_number:
        raise bad_request("plate_number is required")
    if violation_type not in VIOLATION_TYPES:
        raise bad_request("violation_type must be one of NO_VALID_PERMIT, EXPIRED_PERMIT, WRONG_ZONE, CLOSED_LOT")

    # Plate resolution (priority 8): must match at least one existing permit;
    # bind to the latest by created_at (any status)
    matches = [p for p in db.permits.values() if p["plate_number"] == plate_number]
    if not matches:
        raise unprocessable(ERR_PLATE_NOT_REGISTERED, "Plate does not resolve to any existing permit")
    matches.sort(key=lambda p: (p["created_at"], p["id"]))
    resolved = matches[-1]

    patron = db.patrons[resolved["patron_id"]]
    fine = compute_fine(patron, lot, violation_type)

    record = new_record()
    record.update(
        lot_id=lot_id,
        plate_number=plate_number,
        permit_id=resolved["id"],
        patron_id=patron["id"],
        violation_type=violation_type,
        fine_amount_cents=fine,
        status="ISSUED",
        issued_by_officer_id=caller.user_id,
        issued_at=db.iso_now(),
        appeal_reason=None,
        appeal_outcome="NONE",
        appeal_decided_by=None,
        reduction_pct=None,
    )
    record["_issued_at"] = db.now()
    db.citations[record["id"]] = record

    # Issuance cascade
    patron["outstanding_balance_cents"] += fine
    recompute_patron_standing_and_permit_cascade(patron)

    return success(serialize(record), 201)


@bp.get("/parking/citations")
def list_citations():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)

    lot_id = request.args.get("lot_id")
    permit_id = request.args.get("permit_id")
    patron_id = request.args.get("patron_id")
    plate_number = request.args.get("plate_number")
    status = request.args.get("status")

    items = list(db.citations.values())
    if lot_id is not None:
        items = [c for c in items if c["lot_id"] == lot_id]
    if permit_id is not None:
        items = [c for c in items if c["permit_id"] == permit_id]
    if patron_id is not None:
        items = [c for c in items if c["patron_id"] == patron_id]
    if plate_number is not None:
        items = [c for c in items if c["plate_number"] == plate_number]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serialize(c) for c in page], limit, offset, total)


@bp.get("/parking/citations/<citationId>")
def get_citation(citationId):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    record = _get_citation_or_404(citationId)
    return success(serialize(record), 200)


@bp.post("/parking/citations/<citationId>/pay")
def pay_citation(citationId):
    caller = get_caller()
    require_roles(caller, ["Commuter"])

    citation = _get_citation_or_404(citationId)
    require_ownership(caller, citation["patron_id"])

    if citation["status"] != "ISSUED":
        raise conflict(ERR_CITATION_NOT_ISSUED, "Pay requires citation status ISSUED")

    citation["status"] = "PAID"
    touch(citation)

    patron = db.patrons[citation["patron_id"]]
    patron["outstanding_balance_cents"] -= citation["fine_amount_cents"]
    recompute_patron_standing_and_permit_cascade(patron)

    for fund in db.funds.values():
        fund["citation_revenue_cents"] += citation["fine_amount_cents"]
        recompute_fund(fund)
        touch(fund)

    return success(serialize(citation), 200)


@bp.post("/parking/citations/<citationId>/appeal")
def appeal_citation(citationId):
    caller = get_caller()
    require_roles(caller, ["Commuter"])
    body = request.get_json(silent=True) or {}

    citation = _get_citation_or_404(citationId)
    require_ownership(caller, citation["patron_id"])

    # Request shape (priority 6): reason required
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        raise bad_request("reason is required")

    # State (priority 7)
    if citation["status"] != "ISSUED":
        raise conflict(ERR_CITATION_NOT_ISSUED, "Appeal requires citation status ISSUED")

    # Uniqueness (priority 11): one appeal per citation
    if citation["appeal_outcome"] != "NONE":
        raise conflict(ERR_APPEAL_ALREADY_EXISTS, "Citation has already been appealed")

    citation["status"] = "UNDER_APPEAL"
    citation["appeal_outcome"] = "PENDING"
    citation["appeal_reason"] = reason
    touch(citation)

    patron = db.patrons[citation["patron_id"]]
    patron["outstanding_balance_cents"] -= citation["fine_amount_cents"]
    recompute_patron_standing_and_permit_cascade(patron)

    return success(serialize(citation), 200)


@bp.post("/parking/citations/<citationId>/decide-appeal")
def decide_appeal(citationId):
    caller = get_caller()
    require_roles(caller, ["AppealsOfficer"])
    body = request.get_json(silent=True) or {}

    citation = _get_citation_or_404(citationId)

    # Request shape (priority 6): outcome required; reduction_pct iff REDUCED
    outcome = body.get("outcome")
    if outcome not in APPEAL_OUTCOMES:
        raise bad_request("outcome must be one of UPHELD, REDUCED, VOIDED")
    reduction_pct = body.get("reduction_pct")
    if outcome == "REDUCED":
        if reduction_pct is None:
            raise bad_request("reduction_pct is required when outcome is REDUCED")
        if not isinstance(reduction_pct, int) or isinstance(reduction_pct, bool) or not (1 <= reduction_pct <= 99):
            raise bad_request("reduction_pct must be an integer in 1..99")
    else:
        if reduction_pct is not None:
            raise bad_request("reduction_pct must be absent unless outcome is REDUCED")

    # State (priority 7)
    if citation["status"] != "UNDER_APPEAL":
        raise conflict(ERR_CITATION_NOT_ISSUED, "Decide-appeal requires status UNDER_APPEAL")

    # Segregation of duties (priority 10)
    if caller.user_id == citation["issued_by_officer_id"]:
        raise forbidden(
            ERR_SEGREGATION_OF_DUTIES,
            "Appeal decider must differ from the issuing officer",
        )

    patron = db.patrons[citation["patron_id"]]
    citation["appeal_decided_by"] = caller.user_id

    if outcome == "UPHELD":
        citation["status"] = "ISSUED"
        citation["appeal_outcome"] = "UPHELD"
        patron["outstanding_balance_cents"] += citation["fine_amount_cents"]
    elif outcome == "REDUCED":
        new_fine = round_half_up(
            Decimal(citation["fine_amount_cents"]) * Decimal(100 - reduction_pct) / Decimal(100)
        )
        citation["fine_amount_cents"] = new_fine
        citation["reduction_pct"] = reduction_pct
        citation["status"] = "ISSUED"
        citation["appeal_outcome"] = "REDUCED"
        patron["outstanding_balance_cents"] += new_fine
    else:  # VOIDED
        citation["status"] = "VOIDED"
        citation["appeal_outcome"] = "VOIDED"
        # no balance effect

    touch(citation)
    recompute_patron_standing_and_permit_cascade(patron)

    return success(serialize(citation), 200)

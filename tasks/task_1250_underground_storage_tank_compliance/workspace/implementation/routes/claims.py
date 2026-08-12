"""StateFundClaim creation, reservation, and adjudication (PRD 3.8)."""
from flask import Blueprint

from authz import (
    FACILITY_OWNER, READ_ROLES, STATE_REGULATOR, check_facility_ownership,
    require_roles,
)
from calc import compute_claim_amounts
from db import store
from errors import (
    claim_not_draft, claim_not_submitted, claim_not_withdrawable,
    claim_release_mismatch, claim_release_not_confirmed, fees_not_current,
    fund_cap_exceeded, fund_claim_not_found, invalid_request,
    posture_blocks_claim, release_event_not_found,
)
from respond import success
from routes.facilities import get_facility_or_404
from serialize import ser_fund_claim
from store_ops import (
    check_closed, get_or_404, json_body, new_common_fields, new_id, paginate,
    qparam, req_enum, req_field, req_list, req_str, sorted_by_creation, touch,
)

bp = Blueprint("fund_claims", __name__)

DECISIONS = ["APPROVED", "PARTIALLY_APPROVED", "DENIED"]
CLAIMABLE_RELEASE_STATUSES = ("CONFIRMED", "CLEANUP_IN_PROGRESS", "CLOSED")


def get_claim_or_404(claim_id):
    return get_or_404(store.fund_claims, claim_id, fund_claim_not_found)


def _validate_expense_lines(data):
    lines = req_list(data, "expense_lines")
    if not lines:
        raise invalid_request("expense_lines must be a non-empty array")
    for line in lines:
        if not isinstance(line, dict):
            raise invalid_request("Each expense_lines entry must be an object")
        check_closed(line, {"description", "amount_cents"})
        req_str(line, "description")
        amount = req_field(line, "amount_cents")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise invalid_request("Field amount_cents must be an integer > 0")
    return lines


@bp.route("/fund-claims", methods=["POST"])
def create_claim():
    uid, _ = require_roles([FACILITY_OWNER])
    data = json_body()
    check_closed(data, {"facility_id", "release_event_id", "expense_lines"})
    facility_id = req_str(data, "facility_id")
    release_event_id = req_str(data, "release_event_id")
    expense_lines = _validate_expense_lines(data)

    fac = get_facility_or_404(facility_id)
    check_facility_ownership(uid, fac)
    rel = store.release_events.get(release_event_id)
    if rel is None:
        raise release_event_not_found()
    # Priority 9: posture gate.
    if fac["compliance_posture"] == "NON_COMPLIANT":
        raise posture_blocks_claim()
    # Priority 17: claim/release cross-reference.
    if rel["facility_id"] != facility_id:
        raise claim_release_mismatch()
    # Priority 18: fiscal gates in pinned order — release status, fee currency,
    # fund-year cap.
    if rel["status"] not in CLAIMABLE_RELEASE_STATUSES:
        raise claim_release_not_confirmed()
    if fac["annual_fee_paid_through"] < store.clock:
        raise fees_not_current()
    deductible, eligible, payable = compute_claim_amounts(fac, expense_lines)
    if payable > fac["fund_cap_remaining_cents"]:
        raise fund_cap_exceeded()

    c = {
        "id": new_id(),
        "_seq": next(store.seq),
        "facility_id": facility_id,
        "release_event_id": release_event_id,
        "expense_lines": expense_lines,
        "deductible_applied_cents": deductible,
        "eligible_amount_cents": eligible,
        "payable_amount_cents": payable,
        "approved_amount_cents": None,
        "status": "DRAFT",
    }
    c.update(new_common_fields())
    store.fund_claims[c["id"]] = c
    return success(ser_fund_claim(c), status=201)


@bp.route("/fund-claims", methods=["GET"])
def list_claims():
    require_roles(READ_ROLES)
    items = store.fund_claims.values()
    for f in ("facility_id", "release_event_id", "status"):
        v = qparam(f)
        if v is not None:
            items = [c for c in items if c[f] == v]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_fund_claim(c) for c in page], response_type="array",
                   pagination=pagination)


@bp.route("/fund-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    require_roles(READ_ROLES)
    return success(ser_fund_claim(get_claim_or_404(claim_id)))


@bp.route("/fund-claims/<claim_id>/submit", methods=["POST"])
def submit_claim(claim_id):
    uid, _ = require_roles([FACILITY_OWNER])
    json_body()
    c = get_claim_or_404(claim_id)
    fac = get_facility_or_404(c["facility_id"])
    check_facility_ownership(uid, fac)
    if c["status"] != "DRAFT":
        raise claim_not_draft()
    # The fund-year cap is re-checked at submit (priority 18).
    if c["payable_amount_cents"] > fac["fund_cap_remaining_cents"]:
        raise fund_cap_exceeded()
    fac["fund_cap_remaining_cents"] -= c["payable_amount_cents"]  # reservation
    touch(fac)
    c["status"] = "SUBMITTED"
    touch(c)
    return success(ser_fund_claim(c))


@bp.route("/fund-claims/<claim_id>/withdraw", methods=["POST"])
def withdraw_claim(claim_id):
    uid, _ = require_roles([FACILITY_OWNER])
    json_body()
    c = get_claim_or_404(claim_id)
    fac = get_facility_or_404(c["facility_id"])
    check_facility_ownership(uid, fac)
    if c["status"] not in ("DRAFT", "SUBMITTED"):
        raise claim_not_withdrawable()
    if c["status"] == "SUBMITTED":
        # Compensating action: release the reservation.
        fac["fund_cap_remaining_cents"] += c["payable_amount_cents"]
        touch(fac)
    c["status"] = "WITHDRAWN"
    touch(c)
    return success(ser_fund_claim(c))


@bp.route("/fund-claims/<claim_id>/adjudicate", methods=["POST"])
def adjudicate_claim(claim_id):
    require_roles([STATE_REGULATOR])
    data = json_body()
    check_closed(data, {"decision", "approved_amount_cents"})
    decision = req_enum(data, "decision", DECISIONS)
    c = get_claim_or_404(claim_id)
    if c["status"] != "SUBMITTED":
        raise claim_not_submitted()
    fac = get_facility_or_404(c["facility_id"])

    if decision == "APPROVED":
        c["approved_amount_cents"] = c["payable_amount_cents"]
        # Reservation consumed: cap unchanged.
    elif decision == "PARTIALLY_APPROVED":
        amount = req_field(data, "approved_amount_cents")
        if isinstance(amount, bool) or not isinstance(amount, int) \
                or not (0 < amount < c["payable_amount_cents"]):
            raise invalid_request(
                "approved_amount_cents must lie strictly between 0 and payable_amount_cents")
        c["approved_amount_cents"] = amount
        fac["fund_cap_remaining_cents"] += (c["payable_amount_cents"] - amount)
        touch(fac)
    else:  # DENIED
        c["approved_amount_cents"] = 0
        fac["fund_cap_remaining_cents"] += c["payable_amount_cents"]
        touch(fac)

    if decision in ("APPROVED", "PARTIALLY_APPROVED") \
            and fac["fund_program_election"] == "AGGREGATE":
        fac["fund_year_deductible_remaining_cents"] -= c["deductible_applied_cents"]
        touch(fac)
    c["status"] = decision
    touch(c)
    return success(ser_fund_claim(c))

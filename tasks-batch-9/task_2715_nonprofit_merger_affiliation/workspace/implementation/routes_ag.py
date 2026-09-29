"""State attorney general notice and approval — PRD 3.7."""

from flask import Blueprint

import calc
import enums
import services
from auth import authenticate
from clock import CLOCK, add_days, fmt_ts
from db import FUNDS, ORGANIZATIONS, create_row, touch
from errors import fail
from response import ok_row
from validate import (STATE_PATTERN, bad, body_object, opt_str, req_enum, req_id,
                      req_int, req_str)

bp = Blueprint("ag", __name__)


def _contributing_funds(deal_id):
    """PRD 3.7: funds in any other transfer status contribute nothing."""
    return [f for f in FUNDS.values()
            if f["transfer_restructuring_id"] == deal_id
            and f["transfer_status"] == "TRANSFERRED"]


@bp.post("/ag-filings")
def submit_filing():
    authenticate(["CharitableTrustCounsel"])
    body = body_object()
    restructuring_id = req_id(body, "restructuring_id")
    state_code = req_str(body, "state_code", pattern=STATE_PATTERN)
    filing_type = req_enum(body, "filing_type", enums.FILING_TYPES)
    legal_costs_cents = req_int(body, "legal_costs_cents", minimum=0)

    deal = services.find_deal(restructuring_id)
    # Ladder rule 16: INTEGRATION is admitted so that rule 32 stays reachable.
    if deal["status"] not in ("REGULATORY_REVIEW", "INTEGRATION"):
        fail("ERR_INVALID_DEAL_STATE",
             "An attorney-general filing cannot be submitted while the deal is %s."
             % deal["status"])
    # Ladder rule 32.
    if not deal["ag_review_required"]:
        fail("ERR_AG_REVIEW_NOT_REQUIRED",
             "This transaction involves no attorney-general review state.")
    # Ladder rule 33.
    party_states = set()
    for org_id in services.parties(deal):
        org = ORGANIZATIONS.get(org_id)
        if org is not None:
            party_states.add(org["state_code"])
    if state_code not in party_states or state_code not in calc.AG_REVIEW_STATES:
        fail("ERR_AG_STATE_NOT_APPLICABLE",
             "The filing state must be a review state of incorporation of a party.")

    funds = _contributing_funds(deal["id"])
    asset_value = deal["unrestricted_transfer_value_cents"] + sum(
        f["transferred_amount_cents"] for f in funds)
    judicial_basis_present = any(f["transfer_basis"] == "JUDICIAL_MODIFICATION"
                                for f in funds)
    perm_endowment_present = any(f["fund_type"] == "PERM_ENDOWMENT" for f in funds)

    # Ladder rule 34: the filing type is validated, not chosen.
    required_type = calc.required_filing_type(asset_value, perm_endowment_present)
    if filing_type != required_type:
        fail("ERR_AG_FILING_TYPE_MISMATCH",
             "This transaction requires filing_type %s." % required_type)
    # Ladder rule 50.
    if asset_value <= 0:
        fail("ERR_NO_CHARITABLE_ASSETS_TRANSFERRED",
             "A filing must recite some transferred charitable asset value.")

    provisional = asset_value + legal_costs_cents
    fee = calc.ag_filing_fee_cents(provisional)
    closing_costs = legal_costs_cents + fee
    total = asset_value + closing_costs
    waiting_days = calc.statutory_waiting_days(filing_type, asset_value,
                                               deal["structure_type"],
                                               judicial_basis_present)
    submitted_at = CLOCK.now()

    row = create_row("AGFiling", {
        "restructuring_id": deal["id"],
        "state_code": state_code,
        "filing_type": filing_type,
        "legal_costs_cents": legal_costs_cents,
        "transferred_charitable_asset_value_cents": asset_value,
        "judicial_basis_present": judicial_basis_present,
        "provisional_consideration_cents": provisional,
        "ag_filing_fee_cents": fee,
        "closing_costs_cents": closing_costs,
        "total_consideration_cents": total,
        "statutory_waiting_days": waiting_days,
        "submitted_at": fmt_ts(submitted_at),
        "review_deadline_at": fmt_ts(add_days(submitted_at, waiting_days)),
        "decision_recorded_at": None,
        "objection_reason": None,
        "status": "SUBMITTED",
    })
    return ok_row(row, 201)


@bp.post("/ag-filings/<filing_id>/decision")
def record_decision(filing_id):
    authenticate(["StateCharitiesRegulator"])
    body = body_object()
    decision = req_enum(body, "decision", enums.AG_DECISIONS)
    objection_reason = opt_str(body, "objection_reason", min_len=1)
    # An OBJECTED decision must carry a non-blank reason (PRD 3.7).
    if decision == "OBJECTED" and objection_reason is None:
        bad("objection_reason is required and must not be blank on an OBJECTED "
            "decision.")

    filing = services.find_filing(filing_id)
    # Ladder rule 20.
    if filing["status"] != "SUBMITTED":
        fail("ERR_INVALID_FILING_STATE",
             "A decision may only be recorded against a SUBMITTED filing.")

    filing["decision_recorded_at"] = CLOCK.now_iso()
    if decision == "APPROVED":
        filing["status"] = "APPROVED"
        touch(filing)
        deal = services.find_deal(filing["restructuring_id"])
        if deal["status"] == "REGULATORY_REVIEW":
            deal["status"] = "INTEGRATION"
            touch(deal)
    else:
        filing["status"] = "OBJECTED"
        filing["objection_reason"] = objection_reason
        touch(filing)
        # The deal row is deliberately not touched: a fresh filing is required.
    return ok_row(filing)

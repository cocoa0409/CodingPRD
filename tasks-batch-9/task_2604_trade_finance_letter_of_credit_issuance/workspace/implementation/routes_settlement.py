"""Settlement claims, pricing and reimbursement (PRD 3.9)."""

from flask import Blueprint

import calc
import ledger
import validate as v
from db import clock_date, clock_instant, db, new_row, public, touch
from errors import bail
from middleware import (
    CORRESPONDENT_BANK,
    TRADE_FINANCE_OFFICER,
    must_find,
    pending,
    raise_pending,
    require,
)
from response import created, ok
from routes_presentations import presenting_bank_guard

bp = Blueprint("settlement", __name__)

CLAIM_TYPES = ("PAYMENT", "ACCEPTANCE", "NEGOTIATION", "DEFERRED_PAYMENT", "REIMBURSEMENT")

# PRD 3.9: every availability admits REIMBURSEMENT and nothing but its own form.
ADMITTED_CLAIM_TYPES = {
    "SIGHT_PAYMENT": ("PAYMENT", "REIMBURSEMENT"),
    "NEGOTIATION": ("NEGOTIATION", "REIMBURSEMENT"),
    "ACCEPTANCE": ("ACCEPTANCE", "REIMBURSEMENT"),
    "DEFERRED_PAYMENT": ("DEFERRED_PAYMENT", "REIMBURSEMENT"),
}

CLAIMABLE_EXAMINATION_STATUSES = ("COMPLYING", "PRECLUDED")
CLAIMABLE_SETTLEMENT_STATUSES = ("UNSETTLED", "MATURED")
USANCE_CLAIM_TYPES = ("ACCEPTANCE", "DEFERRED_PAYMENT")


def _nominated(credit, beneficiary, bank_id):
    """The presenting bank must still be a nominated bank of the credit."""
    allowed = [credit.get("advising_bank_id"), credit.get("confirming_bank_id")]
    if beneficiary is not None:
        allowed.append(beneficiary.get("nominated_bank_id"))
    return bank_id in [a for a in allowed if a]


def _settlement_screening_gate(presentation, awaiting_review_only):
    """The presented-documents screening gate.

    PRD 2.9 splits this deliberately: the awaiting-review result is a band-4
    cross-entity state guard, while BLOCKED and ESCALATED are band-5 compliance
    safety and therefore adjudicated one band later.
    """
    check = ledger.newest_document_screening(presentation["id"])
    if check is None:
        return
    result = check["result"]
    if awaiting_review_only:
        if result == "HIT_PENDING_REVIEW":
            bail("ERR_SCREENING_NOT_CLEARED")
        return
    if result == "BLOCKED":
        bail("ERR_SANCTIONS_BLOCK")
    if result == "ESCALATED":
        bail("ERR_DUAL_USE_ESCALATED")


# --------------------------------------------------------------------------
# POST /presentations/{id}/settlement-claims
# --------------------------------------------------------------------------

@bp.post("/presentations/<presentation_id>/settlement-claims")
def lodge_claim(presentation_id):
    principal = require(CORRESPONDENT_BANK)
    presentation, deferred = pending("presentations", presentation_id)
    presenting_bank_guard(principal, presentation)

    data = v.body()
    claim_type = v.req_enum(data, "claim_type", CLAIM_TYPES)
    claimed_amount_cents = v.req_int(data, "claimed_amount_cents", minimum=1)
    v.opt_str(data, "claim_note", 0, 500)
    raise_pending(deferred)

    credit = db.credits.get(presentation["credit_id"])
    beneficiary = db.beneficiaries.get((credit or {}).get("beneficiary_id"))

    # At most one live claim per presentation. Checked ahead of the state guard:
    # a presentation carrying a LODGED claim already sits at CLAIM_LODGED, so a
    # state-first reading would make this error unreachable.
    for existing in ledger.claims_of_presentation(presentation_id):
        if existing["status"] == "LODGED":
            bail("ERR_LIVE_REQUEST_EXISTS")

    # band 4 -- both status dimensions
    if presentation["examination_status"] not in CLAIMABLE_EXAMINATION_STATUSES:
        bail("ERR_PRESENTATION_NOT_COMPLYING")
    if presentation["settlement_status"] not in CLAIMABLE_SETTLEMENT_STATUSES:
        bail("ERR_PRESENTATION_NOT_COMPLYING")

    # band 5 -- explicitly ahead of the claim-type coherence check
    _settlement_screening_gate(presentation, awaiting_review_only=False)

    # band 8 -- referential coherence
    admitted = ADMITTED_CLAIM_TYPES.get((credit or {}).get("available_by"), ())
    if claim_type not in admitted:
        bail("ERR_CLAIM_TYPE_MISMATCH")
    if not _nominated(credit or {}, beneficiary, presentation["presenting_bank_id"]):
        bail("ERR_BANK_NOT_NOMINATED")
    if claimed_amount_cents != int(presentation["drawn_amount_cents"] or 0):
        bail("ERR_CLAIM_AMOUNT_MISMATCH")

    row = new_row(
        presentation_id=presentation_id,
        claim_type=claim_type,
        claimed_amount_cents=claimed_amount_cents,
        variant_applied=calc.settlement_variant(claim_type),
        commission_bps_applied=0,
        commission_cents=0,
        discount_cents=0,
        doc_examination_fee_cents=0,
        days_to_maturity=0,
        net_proceeds_cents=0,
        status="LODGED",
        settled_at=None,
        settled_by_user_id=None,
    )
    db.claims[row["id"]] = row

    presentation["settlement_status"] = "CLAIM_LODGED"
    touch(presentation)
    return created(public(row))


# --------------------------------------------------------------------------
# POST /settlement-claims/{id}/settle
# --------------------------------------------------------------------------

@bp.post("/settlement-claims/<claim_id>/settle")
def settle_claim(claim_id):
    principal = require(TRADE_FINANCE_OFFICER)
    data = v.body()
    v.opt_str(data, "settlement_note", 0, 500)
    claim = must_find("claims", claim_id)

    # band 4 -- the claim's own state, then the presentation's settlement state
    if claim["status"] != "LODGED":
        bail("ERR_CLAIM_NOT_LODGED")
    presentation = db.presentations.get(claim["presentation_id"])
    if presentation is None:
        bail("ERR_PRESENTATION_NOT_FOUND")
    if presentation["settlement_status"] != "CLAIM_LODGED":
        bail("ERR_CLAIM_NOT_LODGED")
    _settlement_screening_gate(presentation, awaiting_review_only=True)

    # band 5
    _settlement_screening_gate(presentation, awaiting_review_only=False)

    claim_type = claim["claim_type"]
    if claim_type in USANCE_CLAIM_TYPES and not presentation.get("maturity_date"):
        v.bad("the presentation carries no maturity_date: it cannot be accepted at maturity")

    variant = calc.settlement_variant(claim_type)
    documents = ledger.documents_of_presentation(presentation["id"])
    priced = calc.settlement_proceeds(presentation, documents, variant, clock_date())

    # band 9 -- fiscal, checked last of all
    if priced["net_proceeds_cents"] < 0:
        bail("ERR_CHARGES_EXCEED_PROCEEDS")

    claim["variant_applied"] = variant
    claim["commission_bps_applied"] = priced["commission_bps_applied"]
    claim["commission_cents"] = priced["commission_cents"]
    claim["discount_cents"] = priced["discount_cents"]
    claim["doc_examination_fee_cents"] = priced["doc_examination_fee_cents"]
    claim["days_to_maturity"] = priced["days_to_maturity"]
    claim["net_proceeds_cents"] = priced["net_proceeds_cents"]
    claim["status"] = "SETTLED"
    claim["settled_at"] = clock_instant()
    claim["settled_by_user_id"] = principal.user_id
    touch(claim)

    if claim_type == "REIMBURSEMENT":
        presentation["settlement_status"] = "REIMBURSED"
    elif claim_type == "NEGOTIATION":
        presentation["settlement_status"] = "NEGOTIATED"
    elif claim_type in USANCE_CLAIM_TYPES:
        # the undertaking runs to maturity: the money stays committed
        presentation["settlement_status"] = "ACCEPTED"
    else:
        presentation["settlement_status"] = "PAID"
    touch(presentation)

    credit = db.credits.get(presentation["credit_id"])
    if credit is not None:
        ledger.recompute_credit_drawable(credit)
        ledger.maybe_utilise(credit)
    return ok(public(claim))

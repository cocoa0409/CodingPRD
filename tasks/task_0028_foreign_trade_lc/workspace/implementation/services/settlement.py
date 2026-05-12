"""Settlement variants — sight, usance, negotiation — and reimbursement claim flow."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_VERSION_CONFLICT,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SETTLEMENT_TYPE_MISMATCH,
    ERR_BANK_ROLE_MISMATCH,
    ERR_MATURITY_NOT_REACHED,
    ERR_REIMBURSEMENT_ALREADY_HONORED,
    ERR_LC_INSUFFICIENT_AVAILABLE,
)
from services import audit
from services.banking import add_banking_days


NEGOTIATION_RATE_BPS = 350
DAYS_TO_REIMBURSEMENT = 7


def _check_version(row, payload):
    if payload and "version" in payload and payload["version"] is not None:
        if payload["version"] != row.get("version"):
            raise_error(ERR_VERSION_CONFLICT, "version mismatch")


def _has_been_discrepant(presentation_id):
    """Return True iff this presentation has historically been EXAMINED_DISCREPANT
    (i.e., audit log records an after_state of EXAMINED_DISCREPANT, OR there's a
    FINALIZED examination with final_outcome=DISCREPANT)."""
    # Check audit history
    for e in db.find_many("audit_log_entries", subject_type="PRESENTATION", subject_id=presentation_id):
        if e.get("after_state") == "EXAMINED_DISCREPANT":
            return True
    # Check examination report
    for r in db.find_many("examination_reports", presentation_id=presentation_id):
        if r.get("final_outcome") == "DISCREPANT":
            return True
    return False


def _was_auto_promoted(presentation_id):
    """Was the presentation auto-promoted from EXAMINED_DISCREPANT to EXAMINED_CLEAN?"""
    for e in db.find_many("audit_log_entries", subject_type="PRESENTATION", subject_id=presentation_id):
        if e.get("action") == "presentation.auto_promote_clean":
            return True
    return False


def _compute_proceeds(settlement, lc, presentation):
    principal = int(settlement["principal_minor_units"])

    # Discrepancy fee: charged only when presentation went through EXAMINED_DISCREPANT
    # then ACCEPTED_BY_APPLICANT (via applicant_decision=ACCEPTED or applicant_override).
    # Auto-promotion path (refusal-deadline elapsed) MUST NOT charge fee.
    fee = 0
    if _has_been_discrepant(presentation["id"]) and not _was_auto_promoted(presentation["id"]):
        # Only charge if presentation reached ACCEPTED_BY_APPLICANT in its history
        for e in db.find_many("audit_log_entries", subject_type="PRESENTATION", subject_id=presentation["id"]):
            if e.get("after_state") == "ACCEPTED_BY_APPLICANT":
                fee = int(lc.get("discrepancy_fee_minor_units", 0))
                break

    base = principal - fee

    if settlement["settlement_type"] == "NEGOTIATION":
        # Floor on the multiplicative discount
        # rate_fraction = 350 / 10000 * (7/360)
        # negotiation_discount_minor_units = floor(base * rate_fraction)
        discount = (base * NEGOTIATION_RATE_BPS * DAYS_TO_REIMBURSEMENT) // (10000 * 360)
        advance = base - discount
        proceeds = advance
        return {
            "discrepancy_fee_minor_units": fee,
            "negotiation_discount_minor_units": int(discount),
            "negotiation_advance_minor_units": int(advance),
            "beneficiary_proceeds_minor_units": int(proceeds),
        }

    # SIGHT or USANCE: discount = 0; proceeds = base; round once at end (no per-step rounding).
    # Since we're already in integer minor units, no actual rounding needed beyond int.
    return {
        "discrepancy_fee_minor_units": fee,
        "negotiation_discount_minor_units": 0,
        "negotiation_advance_minor_units": 0,
        "beneficiary_proceeds_minor_units": int(base),
    }


def _recompute_lc_drawn_and_avail(lc_id):
    """Re-derive drawn_amount_minor_units and available from settlements."""
    drawn = 0
    for s in db.find_many("payment_settlements", lc_id=lc_id):
        if s.get("status") in ("ACCEPTED", "PAID"):
            drawn += int(s.get("principal_minor_units", 0))
    lc = db.get_by_id("letters_of_credit", lc_id)
    cap = (int(lc["amount_minor_units"]) * (100 + (lc.get("tolerance_pct") or 0))) // 100
    avail = max(0, int(cap) - drawn)
    db.update("letters_of_credit", lc_id, {
        "drawn_amount_minor_units": drawn,
        "available_amount_minor_units": int(avail),
    })


# ---------- Settlement creation ----------

def create_settlement(presentation_id, payload, role, user_id):
    p = db.get_by_id("presentations", presentation_id)
    if p is None:
        raise_error(ERR_NOT_FOUND, "presentation not found")
    lc = db.get_by_id("letters_of_credit", p["lc_id"])
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")

    if p["status"] not in ("EXAMINED_CLEAN", "ACCEPTED_BY_APPLICANT"):
        raise_error(ERR_INVALID_STATE_TRANSITION, f"presentation not ready for settlement (status={p['status']})")

    payload = payload or {}
    override = payload.get("settlement_type_override")

    # Determine settlement_type
    if override is not None:
        if override != "NEGOTIATION":
            raise_error(ERR_INVALID_REQUEST, "only NEGOTIATION override allowed")
        settlement_type = "NEGOTIATION"
    else:
        if lc["lc_type"] == "SIGHT":
            settlement_type = "SIGHT_PAYMENT"
        elif lc["lc_type"] == "USANCE":
            settlement_type = "USANCE_ACCEPTANCE"
        else:
            raise_error(ERR_INVALID_REQUEST, "unsupported lc_type")

    # RBAC + identity
    if settlement_type == "NEGOTIATION":
        if role != "NegotiatingBank":
            raise_error(ERR_FORBIDDEN_FOR_ROLE, "NEGOTIATION settlement requires NegotiatingBank")
        if p["status"] != "EXAMINED_CLEAN":
            raise_error(ERR_INVALID_STATE_TRANSITION, "negotiation requires EXAMINED_CLEAN")
        bank = db.get_by_id("banks", user_id)
        if bank is None:
            raise_error(ERR_NOT_FOUND, "negotiating bank not found")
        if bank.get("bank_role") != "NEGOTIATING":
            raise_error(ERR_BANK_ROLE_MISMATCH, "bank_role must be NEGOTIATING")
        negotiating_bank_id = user_id
    else:
        if role != "IssuingBank":
            raise_error(ERR_FORBIDDEN_FOR_ROLE, f"{settlement_type} requires IssuingBank")
        if lc.get("issuing_bank_id") != user_id:
            raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
        negotiating_bank_id = None

    # Only one settlement per presentation in non-COMPENSATED state
    for s in db.find_many("payment_settlements", presentation_id=presentation_id):
        if s.get("status") != "COMPENSATED":
            raise_error(ERR_INVALID_STATE_TRANSITION, "settlement already exists for presentation")

    s = db.insert("payment_settlements", {
        "presentation_id": presentation_id,
        "lc_id": p["lc_id"],
        "settlement_type": settlement_type,
        "principal_minor_units": int(p["drawing_amount_minor_units"]),
        "discrepancy_fee_minor_units": 0,
        "negotiation_advance_minor_units": 0,
        "negotiation_discount_minor_units": 0,
        "beneficiary_proceeds_minor_units": 0,
        "maturity_date": None,
        "accepted_at": None,
        "paid_at": None,
        "status": "PENDING",
        "negotiating_bank_id": negotiating_bank_id,
    })
    audit.append("settlement.create", "SETTLEMENT", s["id"], lc_id=p["lc_id"],
                 before_state=None, after_state="PENDING", payload=payload)
    return s


def get_settlement(settlement_id):
    s = db.get_by_id("payment_settlements", settlement_id)
    if s is None:
        raise_error(ERR_NOT_FOUND, "settlement not found")
    return s


# ---------- Sight execute ----------

def execute_sight(settlement_id, payload, user_id):
    s = db.get_by_id("payment_settlements", settlement_id)
    if s is None:
        raise_error(ERR_NOT_FOUND, "settlement not found")
    lc = db.get_by_id("letters_of_credit", s["lc_id"])
    if lc is None or lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(s, payload)

    if s["settlement_type"] != "SIGHT_PAYMENT":
        raise_error(ERR_SETTLEMENT_TYPE_MISMATCH, "settlement is not SIGHT_PAYMENT")
    if s["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE_TRANSITION, "settlement not PENDING")

    p = db.get_by_id("presentations", s["presentation_id"])
    proceeds = _compute_proceeds(s, lc, p)

    db.update("payment_settlements", settlement_id, {
        **proceeds,
        "status": "PAID",
        "paid_at": db.now_iso(),
    })
    db.update("presentations", p["id"], {"status": "SETTLED"})
    _recompute_lc_drawn_and_avail(lc["id"])

    audit.append("settlement.execute_sight", "SETTLEMENT", settlement_id, lc_id=lc["id"],
                 before_state="PENDING", after_state="PAID", payload=payload)
    return db.get_by_id("payment_settlements", settlement_id)


# ---------- Usance acceptance ----------

def record_acceptance(settlement_id, payload, user_id):
    s = db.get_by_id("payment_settlements", settlement_id)
    if s is None:
        raise_error(ERR_NOT_FOUND, "settlement not found")
    lc = db.get_by_id("letters_of_credit", s["lc_id"])
    if lc is None or lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(s, payload)

    if s["settlement_type"] != "USANCE_ACCEPTANCE":
        raise_error(ERR_SETTLEMENT_TYPE_MISMATCH, "settlement is not USANCE_ACCEPTANCE")
    if s["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE_TRANSITION, "settlement not PENDING")

    accepted_at = db.now()
    tenor = lc.get("usance_tenor_days") or 0
    from datetime import timedelta
    maturity = accepted_at + timedelta(days=int(tenor))

    db.update("payment_settlements", settlement_id, {
        "status": "ACCEPTED",
        "accepted_at": db.now_iso(),
        "maturity_date": db.fmt_dt(maturity),
    })
    _recompute_lc_drawn_and_avail(lc["id"])

    audit.append("settlement.record_acceptance", "SETTLEMENT", settlement_id, lc_id=lc["id"],
                 before_state="PENDING", after_state="ACCEPTED", payload=payload)
    return db.get_by_id("payment_settlements", settlement_id)


# ---------- Negotiation advance ----------

def negotiation_advance(settlement_id, payload, user_id):
    s = db.get_by_id("payment_settlements", settlement_id)
    if s is None:
        raise_error(ERR_NOT_FOUND, "settlement not found")
    lc = db.get_by_id("letters_of_credit", s["lc_id"])
    if lc is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    _check_version(s, payload)

    if s["settlement_type"] != "NEGOTIATION":
        raise_error(ERR_SETTLEMENT_TYPE_MISMATCH, "settlement is not NEGOTIATION")
    if s.get("negotiating_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "NegotiatingBank does not own this settlement")
    if s["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE_TRANSITION, "settlement not PENDING")

    p = db.get_by_id("presentations", s["presentation_id"])
    if p["status"] != "EXAMINED_CLEAN":
        raise_error(ERR_INVALID_STATE_TRANSITION, "negotiation requires EXAMINED_CLEAN")

    proceeds = _compute_proceeds(s, lc, p)
    db.update("payment_settlements", settlement_id, {
        **proceeds,
        "status": "PAID",
        "paid_at": db.now_iso(),
    })
    db.update("presentations", p["id"], {"status": "SETTLED"})
    _recompute_lc_drawn_and_avail(lc["id"])

    # Cascade: auto-create ReimbursementClaim
    claim = db.insert("reimbursement_claims", {
        "payment_settlement_id": settlement_id,
        "lc_id": lc["id"],
        "claimed_amount_minor_units": int(s["principal_minor_units"]),
        "status": "SUBMITTED",
        "honored_amount_minor_units": 0,
        "honored_at": None,
    })
    audit.append("settlement.negotiation_advance", "SETTLEMENT", settlement_id, lc_id=lc["id"],
                 before_state="PENDING", after_state="PAID", payload=payload)
    audit.append("reimbursement.create", "REIMBURSEMENT", claim["id"], lc_id=lc["id"],
                 before_state=None, after_state="SUBMITTED", payload={})
    return db.get_by_id("payment_settlements", settlement_id)


# ---------- Compensation ----------

def compensate(settlement_id, payload, user_id):
    s = db.get_by_id("payment_settlements", settlement_id)
    if s is None:
        raise_error(ERR_NOT_FOUND, "settlement not found")
    lc = db.get_by_id("letters_of_credit", s["lc_id"])
    if lc is None or lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(s, payload)

    if s["status"] not in ("PAID", "ACCEPTED"):
        raise_error(ERR_INVALID_STATE_TRANSITION, "settlement not PAID/ACCEPTED")

    if not isinstance(payload, dict) or not payload.get("reason"):
        raise_error(ERR_INVALID_REQUEST, "reason required")

    db.update("payment_settlements", settlement_id, {"status": "COMPENSATED"})
    db.update("presentations", s["presentation_id"], {"status": "EXAMINED_CLEAN"})
    _recompute_lc_drawn_and_avail(lc["id"])

    audit.append("settlement.compensate", "SETTLEMENT", settlement_id, lc_id=lc["id"],
                 before_state=s["status"], after_state="COMPENSATED", payload=payload)
    return db.get_by_id("payment_settlements", settlement_id)


# ---------- Reimbursement claims ----------

def get_claim(claim_id):
    c = db.get_by_id("reimbursement_claims", claim_id)
    if c is None:
        raise_error(ERR_NOT_FOUND, "claim not found")
    return c


def honor_claim(claim_id, payload, user_id):
    c = db.get_by_id("reimbursement_claims", claim_id)
    if c is None:
        raise_error(ERR_NOT_FOUND, "claim not found")
    lc = db.get_by_id("letters_of_credit", c["lc_id"])
    if lc is None or lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(c, payload)

    if c["status"] == "HONORED":
        raise_error(ERR_REIMBURSEMENT_ALREADY_HONORED, "already honored")
    if c["status"] not in ("SUBMITTED", "DISPUTED"):
        raise_error(ERR_INVALID_STATE_TRANSITION, f"claim in {c['status']}")

    # Validate available headroom + drawn (i.e., LC has capacity)
    cap = (int(lc["amount_minor_units"]) * (100 + (lc.get("tolerance_pct") or 0))) // 100
    if int(c["claimed_amount_minor_units"]) > cap:
        raise_error(ERR_LC_INSUFFICIENT_AVAILABLE, "claim exceeds LC capacity")

    db.update("reimbursement_claims", claim_id, {
        "status": "HONORED",
        "honored_amount_minor_units": int(c["claimed_amount_minor_units"]),
        "honored_at": db.now_iso(),
    })
    audit.append("reimbursement.honor", "REIMBURSEMENT", claim_id, lc_id=lc["id"],
                 before_state=c["status"], after_state="HONORED", payload=payload)
    return db.get_by_id("reimbursement_claims", claim_id)


def dispute_claim(claim_id, payload, user_id):
    c = db.get_by_id("reimbursement_claims", claim_id)
    if c is None:
        raise_error(ERR_NOT_FOUND, "claim not found")
    lc = db.get_by_id("letters_of_credit", c["lc_id"])
    if lc is None or lc.get("issuing_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "IssuingBank does not own this LC")
    _check_version(c, payload)

    if c["status"] == "HONORED":
        raise_error(ERR_REIMBURSEMENT_ALREADY_HONORED, "already honored")
    if c["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE_TRANSITION, f"claim in {c['status']}")

    if not isinstance(payload, dict) or not payload.get("reason"):
        raise_error(ERR_INVALID_REQUEST, "reason required")

    db.update("reimbursement_claims", claim_id, {"status": "DISPUTED"})

    # Cascade: settlement compensated
    s = db.get_by_id("payment_settlements", c["payment_settlement_id"])
    if s is not None and s["status"] != "COMPENSATED":
        db.update("payment_settlements", s["id"], {"status": "COMPENSATED"})
        db.update("presentations", s["presentation_id"], {"status": "EXAMINED_CLEAN"})
        _recompute_lc_drawn_and_avail(lc["id"])
        audit.append("settlement.compensate", "SETTLEMENT", s["id"], lc_id=lc["id"],
                     before_state="PAID", after_state="COMPENSATED", payload={"cause": "dispute_cascade"})

    audit.append("reimbursement.dispute", "REIMBURSEMENT", claim_id, lc_id=lc["id"],
                 before_state="SUBMITTED", after_state="DISPUTED", payload=payload)
    return db.get_by_id("reimbursement_claims", claim_id)


def extinguish_claim(claim_id, payload, user_id):
    c = db.get_by_id("reimbursement_claims", claim_id)
    if c is None:
        raise_error(ERR_NOT_FOUND, "claim not found")
    s = db.get_by_id("payment_settlements", c["payment_settlement_id"])
    if s is None or s.get("negotiating_bank_id") != user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "NegotiatingBank does not own this claim")
    _check_version(c, payload)

    if c["status"] != "DISPUTED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "claim not DISPUTED")

    db.update("reimbursement_claims", claim_id, {"status": "EXTINGUISHED"})
    audit.append("reimbursement.extinguish", "REIMBURSEMENT", claim_id, lc_id=c["lc_id"],
                 before_state="DISPUTED", after_state="EXTINGUISHED", payload=payload)
    return db.get_by_id("reimbursement_claims", claim_id)

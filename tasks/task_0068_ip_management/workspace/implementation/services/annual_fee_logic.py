"""AnnualFeeSchedule logic: surcharges, pay, sweep, abandonment cascade."""
import math
from datetime import timedelta
from decimal import Decimal

import db
from errors import (APIError, ERR_REFERENCED_ENTITY_NOT_FOUND, ERR_INVALID_STATE, ERR_FEE_DATES_INVALID,
                    ERR_BAD_REQUEST, ERR_FEE_ALREADY_PAID)
from services import audit
from services.common import make_versioned, touch
from utils import round_half_up_cents


TIER_1_RATE = Decimal("0.10")
TIER_2_RATE = Decimal("0.25")
TIER_3_RATE = Decimal("0.50")


def schedule_annual_fee(right, body, actor_role, actor_id):
    from utils import get_str, get_int, get_bool
    jurisdiction = get_str(body, "jurisdiction")
    fee_year = get_int(body, "fee_year", required=True, min_value=1)
    base_fee = get_int(body, "base_fee_cents", required=True, min_value=0)
    due_date_str = get_str(body, "due_date")
    auto_pay_authorized = get_bool(body, "auto_pay_authorized", required=False, default=False)
    assigned_agent_id = get_str(body, "assigned_agent_id")

    if assigned_agent_id not in db.agents:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "assigned_agent_id does not resolve")

    # jurisdiction must match one of the right's filings
    siblings = [f for f in db.jurisdiction_filings.values() if f["ip_right_id"] == right["id"]]
    juris_matches = [f for f in siblings if f["jurisdiction"] == jurisdiction]
    if not juris_matches:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422,
                       "jurisdiction does not match any of the right's filings")

    due_date = db.parse_iso(due_date_str)
    if due_date is None:
        raise APIError(ERR_BAD_REQUEST, 422, "Invalid due_date")
    grace_end = due_date + timedelta(days=180)
    if not (due_date < grace_end):
        raise APIError(ERR_FEE_DATES_INVALID, 422, "due_date must be < grace_end_date")
    if grace_end - due_date != timedelta(days=180):
        raise APIError(ERR_FEE_DATES_INVALID, 422, "grace_end must equal due_date + 180 days")

    fee = make_versioned({
        "ip_right_id": right["id"],
        "jurisdiction": jurisdiction,
        "fee_year": fee_year,
        "base_fee_cents": base_fee,
        "due_date": db.to_iso(due_date),
        "grace_end_date": db.to_iso(grace_end),
        "paid_at": None,
        "total_paid_cents": 0,
        "surcharge_cents": 0,
        "auto_pay_authorized": auto_pay_authorized,
        "assigned_agent_id": assigned_agent_id,
        "status": "PENDING",
    })
    db.annual_fees[fee["id"]] = fee
    return fee


def compute_surcharge_cents(fee, at: 'datetime') -> int:
    due = db.parse_iso(fee["due_date"])
    days_late = math.floor((at - due).total_seconds() / 86400)
    if days_late <= 0:
        rate = Decimal("0")
    elif 1 <= days_late <= 30:
        rate = TIER_1_RATE
    elif 31 <= days_late <= 90:
        rate = TIER_2_RATE
    elif 91 <= days_late <= 180:
        rate = TIER_3_RATE
    else:
        rate = None  # past grace
    if rate is None:
        return None
    return round_half_up_cents(Decimal(fee["base_fee_cents"]) * rate)


def pay_fee(fee, actor_role, actor_id, via_external=False):
    """Pay or auto-pay an AnnualFeeSchedule."""
    if fee.get("paid_at") is not None:
        raise APIError(ERR_FEE_ALREADY_PAID, 409, "Fee already paid")
    if fee["status"] not in ("PENDING", "LATE"):
        raise APIError(ERR_INVALID_STATE, 409, f"Fee in {fee['status']} cannot be paid")
    # If external (auto-pay event), require auto_pay_authorized
    # The PRD says only FinanceManager may pay non-autopay; the external event flow is admin-driven,
    # but we still gate it on auto_pay_authorized when set via external event.
    if via_external and not fee.get("auto_pay_authorized"):
        # External payment cannot settle a non-autopay fee
        raise APIError(ERR_INVALID_STATE, 409, "auto_pay_authorized is false for this fee")

    now = db.now()
    grace = db.parse_iso(fee["grace_end_date"])
    if now > grace:
        # past grace — no surcharge booked, schedule should be in ABANDONED rather than payable
        raise APIError(ERR_INVALID_STATE, 409, "Beyond grace window")

    surcharge = compute_surcharge_cents(fee, now)
    if surcharge is None:
        raise APIError(ERR_INVALID_STATE, 409, "Beyond grace window")
    total_paid = fee["base_fee_cents"] + surcharge
    prior = fee["status"]
    fee["surcharge_cents"] = surcharge
    fee["total_paid_cents"] = total_paid
    fee["paid_at"] = db.now_iso()
    fee["status"] = "PAID"
    touch(fee)
    audit.emit("AnnualFeeSchedule", fee["id"], actor_role, actor_id,
               "PAYMENT_SETTLED", from_state=prior, to_state="PAID",
               payload={"base_fee_cents": fee["base_fee_cents"], "surcharge_cents": surcharge,
                        "total_paid_cents": total_paid})

    # Book a Cost row of category ANNUAL_FEE
    right = db.ip_rights.get(fee["ip_right_id"])
    business_unit_id = right["business_unit_id"] if right else None
    if business_unit_id and business_unit_id in db.business_units:
        from services.cost_logic import book_cost_for_event
        book_cost_for_event(category="ANNUAL_FEE",
                            amount_usd_cents=total_paid,
                            ip_right_id=fee["ip_right_id"],
                            protection_case_id=None,
                            agent_id=None,
                            business_unit_id=business_unit_id,
                            actor_role=actor_role,
                            actor_id=actor_id,
                            currency="USD")
    return fee


def sweep_annual_fees(actor_role, actor_id):
    """Run the annual-fee sweep transitions:
       - PENDING with now() > due_date and now() <= grace_end_date → LATE
       - LATE (or any unpaid) with now() > grace_end_date → ABANDONED
       Cascade abandonment to JurisdictionFiling and IPRight."""
    now = db.now()
    pending_to_late = []
    to_abandon = []
    for fee in db.annual_fees.values():
        if fee.get("paid_at") is not None:
            continue
        due = db.parse_iso(fee["due_date"])
        grace = db.parse_iso(fee["grace_end_date"])
        if fee["status"] == "PENDING":
            if now > due and now <= grace:
                pending_to_late.append(fee)
            elif now > grace:
                to_abandon.append(fee)
        elif fee["status"] == "LATE":
            if now > grace:
                to_abandon.append(fee)

    for fee in pending_to_late:
        prior = fee["status"]
        fee["status"] = "LATE"
        touch(fee)
        audit.emit("AnnualFeeSchedule", fee["id"], actor_role, actor_id,
                   "STATUS_CHANGE", from_state=prior, to_state="LATE")

    affected_rights = set()
    for fee in to_abandon:
        prior = fee["status"]
        fee["status"] = "ABANDONED"
        touch(fee)
        audit.emit("AnnualFeeSchedule", fee["id"], actor_role, actor_id,
                   "STATUS_CHANGE", from_state=prior, to_state="ABANDONED")
        # cascade to JurisdictionFiling of matching jurisdiction on the right
        right_id = fee["ip_right_id"]
        right = db.ip_rights.get(right_id)
        if right:
            affected_rights.add(right_id)
            for jf in db.jurisdiction_filings.values():
                if jf["ip_right_id"] == right_id and jf["jurisdiction"] == fee["jurisdiction"]:
                    if jf["status"] != "ABANDONED":
                        p = jf["status"]
                        jf["status"] = "ABANDONED"
                        touch(jf)
                        audit.emit("JurisdictionFiling", jf["id"], actor_role, actor_id,
                                   "STATUS_CHANGE", from_state=p, to_state="ABANDONED")

    # For each affected right, check bubble-up:
    # 1) if every JurisdictionFiling on this right is ABANDONED, IPRight -> ABANDONED
    # 2) if every AnnualFeeSchedule on a REGISTERED right is ABANDONED, IPRight -> ABANDONED
    for right_id in affected_rights:
        right = db.ip_rights.get(right_id)
        if not right or right["status"] == "ABANDONED":
            continue
        siblings = [f for f in db.jurisdiction_filings.values() if f["ip_right_id"] == right_id]
        all_filings_abandoned = bool(siblings) and all(f["status"] == "ABANDONED" for f in siblings)
        fees_for_right = [f for f in db.annual_fees.values() if f["ip_right_id"] == right_id]
        all_fees_abandoned = bool(fees_for_right) and all(f["status"] == "ABANDONED"
                                                          for f in fees_for_right)
        if all_filings_abandoned or all_fees_abandoned:
            p = right["status"]
            right["status"] = "ABANDONED"
            touch(right)
            audit.emit("IPRight", right["id"], actor_role, actor_id,
                       "STATUS_CHANGE", from_state=p, to_state="ABANDONED")

    return {
        "pending_to_late": [f["id"] for f in pending_to_late],
        "to_abandoned": [f["id"] for f in to_abandon],
    }

"""Sanction-order money: fine payments, vacatur, the recovery fund waterfall."""
from datetime import timedelta

from flask import Blueprint

import cascades
import computed
import envelope
import serialize
import shape
import store
from authz import guard
from errors import fail

bp = Blueprint("fund", __name__)

CLAIM_WINDOW_SECONDS = computed.CLAIM_WINDOW_DAYS * 86400


def _window_closed(order):
    return store.now() >= (store.dt_of(order["effective_at"])
                           + timedelta(seconds=CLAIM_WINDOW_SECONDS))


# --------------------------------------------------------------- fine payments
@bp.post("/commission/sanction-orders/<oid>/fine-payments")
def pay_fine(oid):
    user_id, role = guard(["Respondent", "LicensingAnalyst"])
    data = shape.body()
    amount = shape.req_int(data, "amount_cents", minimum=1)
    shape.req_date(data, "paid_on")

    order = computed.must("sanction_order", oid)
    if role == "Respondent" and user_id != order["respondent_licensee_id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Only the respondent named on the order may pay its fine.")
    if order["status"] == "VACATED":
        fail("ERR_ORDER_ALREADY_VACATED", "This order has been vacated.")
    if order["status"] not in ("ISSUED", "IN_DEFAULT"):
        fail("ERR_INVALID_STATE",
             "Payments are only accepted against an ISSUED or IN_DEFAULT order.")
    outstanding = order["fine_cents"] - order["fine_paid_cents"]
    if amount > outstanding:
        fail("ERR_PAYMENT_EXCEEDS_BALANCE",
             "The payment exceeds the outstanding balance of %d cents." % outstanding)

    order["fine_paid_cents"] = order["fine_paid_cents"] + amount
    order["fund_credited_cents"] = order["fund_credited_cents"] + amount
    if order["fine_paid_cents"] >= order["fine_cents"]:
        order["status"] = "SATISFIED"
    store.touch(order)

    fund = store.fund()
    fund["fine_credits_cents"] = fund["fine_credits_cents"] + amount
    fund["balance_cents"] = fund["balance_cents"] + amount
    store.touch(fund)
    return envelope.ok(serialize.sanction_order(order))


# ---------------------------------------------------------------------- vacatur
@bp.post("/commission/sanction-orders/<oid>/vacatur")
def vacate_order(oid):
    user_id, _ = guard(["HearingPanelChair"])
    data = shape.body()
    shape.req_str(data, "vacatur_reason")

    order = computed.must("sanction_order", oid)
    if order["status"] == "VACATED":
        fail("ERR_ORDER_ALREADY_VACATED", "This order has already been vacated.")
    if order["status"] not in ("ISSUED", "IN_DEFAULT", "SATISFIED"):
        fail("ERR_INVALID_STATE", "This order cannot be vacated from its state.")
    if order["source"] == "HEARING":
        hearing = store.get("hearing", order["hearing_id"])
        if hearing is not None and user_id == hearing["panel_chair_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "A chair may not vacate an order from their own hearing.")

    moment = store.now()
    order["status"] = "VACATED"
    order["vacated_at"] = store.fmt_dt(moment)
    store.touch(order)

    fund = store.fund()
    # COMPENSATION 1 - reverse the fine credits.
    credited = order["fund_credited_cents"]
    fund["fine_credits_cents"] = fund["fine_credits_cents"] - credited
    fund["balance_cents"] = fund["balance_cents"] - credited
    order["fund_credited_cents"] = 0
    order["fine_paid_cents"] = 0
    store.touch(fund)

    # COMPENSATION 2 - claw back every paid claim.
    for claim in computed.rows_where("recovery_claim", sanction_order_id=order["id"]):
        if claim["status"] in ("PARTIALLY_PAID", "PAID"):
            awarded = claim["awarded_cents"]
            claim["status"] = "CLAWED_BACK"
            fund["clawed_back_cents"] = fund["clawed_back_cents"] + awarded
            fund["balance_cents"] = fund["balance_cents"] + awarded
            claim["awarded_cents"] = 0
            store.touch(claim)
    store.touch(fund)

    # COMPENSATION 3 - deny every queued claim.
    for claim in computed.rows_where("recovery_claim", sanction_order_id=order["id"]):
        if claim["status"] == "ELIGIBLE":
            claim["status"] = "DENIED"
            claim["denial_reason"] = "ORDER_VACATED"
            store.touch(claim)

    # COMPENSATION 4 - restore the respondent.
    respondent = store.get("licensee", order["respondent_licensee_id"])
    snap = {}
    if respondent is not None:
        cascades.add_snapshot(snap, respondent.get("sponsoring_brokerage_id"))
        if respondent["license_status"] == "SUSPENDED":
            respondent["license_status"] = "ACTIVE"
            respondent["suspension_ends_at"] = None
            respondent["_suspension_order_id"] = None
            store.touch(respondent)
        elif respondent["license_status"] == "REVOKED":
            respondent["license_status"] = "INACTIVE"
            respondent["inactive_since"] = store.fmt_dt(moment)
            store.touch(respondent)
        if respondent["discipline_status"] == "SANCTIONED":
            remaining = [o for o in store.all_rows("sanction_order")
                         if o["respondent_licensee_id"] == respondent["id"]
                         and o["id"] != order["id"] and o["status"] != "VACATED"]
            if not remaining:
                respondent["discipline_status"] = "CLEARED"
                store.touch(respondent)

    # COMPENSATION 5 - recompute derived figures and the firm's posture last.
    complaint = store.get("complaint", order["complaint_id"])
    if complaint is not None:
        cascades.add_snapshot(snap, complaint.get("respondent_brokerage_id"))
    cascades.settle(snap)
    return envelope.ok(serialize.sanction_order(order))


# ------------------------------------------------------------ recovery claims
@bp.post("/commission/sanction-orders/<oid>/recovery-claims")
def file_claim(oid):
    guard(["Public", "RecoveryFundTrustee"])
    data = shape.body()
    claimant_name = shape.req_str(data, "claimant_name")
    claimed_loss = shape.req_int(data, "claimed_loss_cents", minimum=1)

    order = computed.must("sanction_order", oid)
    status = "ELIGIBLE"
    reason = None
    if order["sanction_type"] in ("REPRIMAND", "PROBATION"):
        status, reason = "DENIED", "ORDER_NOT_DISCIPLINARY"
    elif _window_closed(order):
        status, reason = "DENIED", "WINDOW_CLOSED"
    elif order["status"] == "VACATED":
        status, reason = "DENIED", "ORDER_VACATED"

    row = store.insert("recovery_claim", {
        "sanction_order_id": order["id"],
        "claimant_name": claimant_name,
        "claimed_loss_cents": claimed_loss,
        "filed_at": store.fmt_dt(store.now()),
        "status": status,
        "awarded_cents": 0,
        "denial_reason": reason,
        "paid_at": None,
    })
    return envelope.created(serialize.recovery_claim(row))


# ----------------------------------------------------------------- the fund
@bp.post("/commission/recovery-fund/appropriations")
def appropriate():
    guard(["RecoveryFundTrustee"])
    data = shape.body()
    amount = shape.req_int(data, "amount_cents", minimum=1)
    shape.opt_str(data, "appropriation_note")

    fund = store.fund()
    fund["balance_cents"] = fund["balance_cents"] + amount
    fund["appropriated_cents"] = fund["appropriated_cents"] + amount
    store.touch(fund)
    return envelope.ok(serialize.recovery_fund(fund))


@bp.post("/commission/recovery-fund/disbursements")
def disburse():
    guard(["RecoveryFundTrustee"])
    data = shape.body()
    order_id = shape.req_id(data, "sanction_order_id")
    expected = shape.req_int(data, "expected_recovery_fund_version")

    order = computed.must("sanction_order", order_id)
    fund = store.fund()
    if expected != fund["version"]:
        fail("ERR_RECOVERY_FUND_VERSION_CONFLICT",
             "The recovery fund has moved on; expected version %d." % fund["version"])
    if _window_closed(order):
        fail("ERR_CLAIM_WINDOW_CLOSED",
             "The 365-day recovery window on this order has closed.")
    if fund["balance_cents"] <= computed.FUND_RESERVE_FLOOR_CENTS:
        fail("ERR_FUND_RESERVE_FLOOR",
             "The fund balance does not exceed the reserve floor.")
    respondent = store.get("licensee", order["respondent_licensee_id"])
    already_paid = computed.recovery_paid_cents(order["respondent_licensee_id"])
    if already_paid >= computed.PER_LICENSEE_CAP_CENTS:
        fail("ERR_LICENSEE_CAP_EXHAUSTED",
             "The per-licensee recovery cap is exhausted.")

    candidates = [c for c in computed.rows_where("recovery_claim",
                                                 sanction_order_id=order["id"])
                  if c["status"] in ("ELIGIBLE", "PARTIALLY_PAID")]
    if not candidates:
        fail("ERR_NO_ELIGIBLE_CLAIMS", "No candidate claim exists on this order.")

    licensee_remaining = computed.PER_LICENSEE_CAP_CENTS - already_paid
    distributable = fund["balance_cents"] - computed.FUND_RESERVE_FLOOR_CENTS
    awards = []
    for claim in candidates:
        claim_room = claim["claimed_loss_cents"] - claim["awarded_cents"]
        cap_room = computed.PER_CLAIM_CAP_CENTS - claim["awarded_cents"]
        award = max(0, min(claim_room, cap_room, licensee_remaining, distributable))
        awards.append(award)
        licensee_remaining -= award
        distributable -= award
    total = sum(awards)
    if total <= 0:
        fail("ERR_NO_ELIGIBLE_CLAIMS",
             "Every candidate claim has no remaining room.")

    assessment = _assessment(total)
    shaved_claim_id = None
    if fund["balance_cents"] - total - assessment < computed.FUND_RESERVE_FLOOR_CENTS:
        deficit = computed.FUND_RESERVE_FLOOR_CENTS - (
            fund["balance_cents"] - total - assessment)
        shave = min(deficit, awards[-1])
        awards[-1] -= shave
        total -= shave
        assessment = _assessment(total)
        shaved_claim_id = candidates[-1]["id"]

    stamp = store.fmt_dt(store.now())
    paid_count = 0
    partial_count = 0
    for claim, award in zip(candidates, awards):
        if award <= 0:
            continue
        was_eligible = claim["status"] == "ELIGIBLE"
        claim["awarded_cents"] = claim["awarded_cents"] + award
        if claim["awarded_cents"] >= claim["claimed_loss_cents"]:
            claim["status"] = "PAID"
            paid_count += 1
        else:
            claim["status"] = "PARTIALLY_PAID"
            partial_count += 1
        if was_eligible:
            claim["paid_at"] = stamp
        store.touch(claim)

    fund["awarded_cents"] = fund["awarded_cents"] + total
    fund["assessment_cents"] = fund["assessment_cents"] + assessment
    fund["balance_cents"] = fund["balance_cents"] - (total + assessment)
    store.touch(fund)
    if respondent is not None:
        computed.recovery_paid_cents(respondent["id"])
    return envelope.ok({
        "total_awarded_cents": total,
        "assessment_cents": assessment,
        "balance_cents_after": fund["balance_cents"],
        "fund_version": fund["version"],
        "paid_claim_count": paid_count,
        "partially_paid_claim_count": partial_count,
        "shaved_claim_id": shaved_claim_id,
    })


def _assessment(total):
    return store.round_half_up(
        store.Decimal(total) * store.Decimal(computed.ASSESSMENT_RATE))

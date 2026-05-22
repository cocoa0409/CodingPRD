"""
Business-logic services: state machines, cascades, sweeps, helpers.

Each public function takes the entities it needs already resolved by the caller.
All mutations bump version + updated_at on every affected entity.
"""
from datetime import timedelta

import db
from common import CLOCK, ApiError, gen_uuid
from constants import (
    NO_SHOW_PENALTY_CENTS, NO_SHOW_WINDOW_DAYS, NO_SHOW_STRIKE_LIMIT,
    STRIKE_SUSPENSION_DAYS, CONFIRM_CUTOFF_MINUTES, RETRY_LIMIT,
    REFERRAL_REWARD_CENTS_BY_PLAN, grace_period_days,
)
from calculations import (
    compute_account_posture, compute_member_cancel_refund,
    compute_admin_cancel_refund, compute_late_payment_penalty,
    booking_provisional_price, plan_base_price,
)


# ----------------------------- low-level helpers -----------------------------
def bump(entity):
    entity["updated_at"] = CLOCK.now()
    entity["version"] = entity.get("version", 0) + 1


def recompute_posture(member):
    member["account_posture"] = compute_account_posture(
        member["billing_status"], member["access_status"]
    )


def member_wallet_ledger_append(member, kind, delta, ref_id=None, note=None):
    ledger = member.setdefault("wallet_ledger", [])
    ledger.append({
        "kind": kind,
        "delta_cents": delta,
        "balance_cents": member["wallet_credit_cents"],
        "ref_id": ref_id,
        "note": note,
        "at": CLOCK.now().isoformat(),
    })


# ------------------------- coupon helpers -----------------------------------
def coupon_set_status_if_needed(coupon):
    now = CLOCK.now()
    if coupon["status"] == "REVOKED":
        return
    if coupon["redemption_count"] >= coupon["max_redemptions"]:
        coupon["status"] = "EXHAUSTED"
    elif coupon["valid_until"] <= now:
        coupon["status"] = "EXPIRED"
    elif coupon["valid_from"] <= now < coupon["valid_until"]:
        coupon["status"] = "ACTIVE"


def coupon_validate_redeemable(coupon, context_kind, member=None):
    """Raise ERR_COUPON_INVALID / ERR_COUPON_EXHAUSTED as appropriate."""
    if coupon is None:
        raise ApiError("ERR_COUPON_INVALID", 400, "Coupon not found")
    now = CLOCK.now()
    if coupon["status"] == "REVOKED":
        raise ApiError("ERR_COUPON_INVALID", 400, "Coupon revoked")
    if coupon["redemption_count"] >= coupon["max_redemptions"]:
        raise ApiError("ERR_COUPON_EXHAUSTED", 409, "Coupon has reached max_redemptions")
    if not (coupon["valid_from"] <= now < coupon["valid_until"]):
        raise ApiError("ERR_COUPON_INVALID", 400, "Coupon outside validity window")
    if context_kind == "BOOKING" and coupon["applicable_to"] not in ("BOOKING", "BOTH"):
        raise ApiError("ERR_COUPON_INVALID", 400, "Coupon not applicable to booking")
    if context_kind == "SUBSCRIPTION" and coupon["applicable_to"] not in ("SUBSCRIPTION", "BOTH"):
        raise ApiError("ERR_COUPON_INVALID", 400, "Coupon not applicable to subscription")
    if coupon.get("tied_to_member_id") is not None and member is not None:
        if coupon["tied_to_member_id"] != member["id"]:
            raise ApiError("ERR_COUPON_INVALID", 400, "Coupon tied to another member")


def coupon_increment(coupon):
    coupon["redemption_count"] += 1
    coupon_set_status_if_needed(coupon)
    bump(coupon)


def coupon_decrement(coupon):
    if coupon["redemption_count"] > 0:
        coupon["redemption_count"] -= 1
    coupon_set_status_if_needed(coupon)
    bump(coupon)


# ------------------------- booking helpers ----------------------------------
def cascade_cancel_member_bookings(member, *, future_only=True, reason="admin_cascade"):
    """Cancel all of this member's non-terminal future bookings using ADMIN refund."""
    now = CLOCK.now()
    affected = []
    for b in list(db.bookings.values()):
        if b["member_id"] != member["id"]:
            continue
        if b["status"] in ("ATTENDED", "NO_SHOW", "CANCELLED"):
            continue
        if future_only and b["starts_at"] <= now:
            continue
        _cancel_booking_admin(b, member, reason=reason)
        affected.append(b)
    return affected


def _cancel_booking_admin(booking, member, *, reason="admin_cascade"):
    """Admin/cascade cancel: 100% refund of provisional_price, no no-show penalty even if previously CONFIRMED."""
    prov = booking.get("provisional_price_cents", 0) or 0
    refund, pct = compute_admin_cancel_refund(prov)
    booking["status"] = "CANCELLED"
    booking["final_price_cents"] = prov - refund
    bump(booking)
    if refund > 0:
        member["wallet_credit_cents"] = member.get("wallet_credit_cents", 0) + refund
        member_wallet_ledger_append(member, "booking_refund", refund, ref_id=booking["id"], note=f"admin_cancel pct={pct}")
        bump(member)
        recompute_posture(member)
    # release seat if had one
    if booking.get("class_session_id"):
        cs = db.class_sessions.get(booking["class_session_id"])
        if cs:
            if booking.get("_had_seat", False):
                cs["reserved_seat_count"] = max(0, cs["reserved_seat_count"] - 1)
                bump(cs)
    # release coupon
    cid = booking.get("applied_coupon_id")
    if cid:
        c = db.coupons.get(cid)
        if c:
            coupon_decrement(c)
    # promote waitlist for class sessions
    if booking.get("class_session_id"):
        cs = db.class_sessions.get(booking["class_session_id"])
        if cs:
            promote_waitlist(cs)


def cancel_booking_member(booking, member):
    """Member-driven cancel using state-specific refund schedule."""
    cs = db.class_sessions.get(booking.get("class_session_id")) if booking.get("class_session_id") else None
    if cs:
        ref_starts_at = cs["starts_at"]
    else:
        ref_starts_at = booking["starts_at"]
    now = CLOCK.now()
    hours_to_start = (ref_starts_at - now).total_seconds() / 3600.0
    prov = booking.get("provisional_price_cents", 0) or 0
    refund, pct = compute_member_cancel_refund(member["state_code"], prov, hours_to_start)
    booking["status"] = "CANCELLED"
    booking["final_price_cents"] = prov - refund
    bump(booking)
    if refund > 0:
        member["wallet_credit_cents"] = member.get("wallet_credit_cents", 0) + refund
        member_wallet_ledger_append(member, "booking_refund", refund, ref_id=booking["id"], note=f"member_cancel pct={pct}")
        bump(member)
        recompute_posture(member)
    # release seat
    if booking.get("class_session_id") and booking.get("_had_seat", False):
        if cs:
            cs["reserved_seat_count"] = max(0, cs["reserved_seat_count"] - 1)
            bump(cs)
    # release coupon
    cid = booking.get("applied_coupon_id")
    if cid:
        c = db.coupons.get(cid)
        if c:
            coupon_decrement(c)
    # waitlist promotion
    if cs:
        promote_waitlist(cs)


def promote_waitlist(class_session):
    """Promote eligible WAITLISTED bookings while capacity allows.

    Selector: oldest created_at first; owner.account_posture == OPEN; skip ineligible.
    """
    while class_session["reserved_seat_count"] < class_session["capacity"]:
        candidates = [
            b for b in db.bookings.values()
            if b.get("class_session_id") == class_session["id"]
               and b["status"] == "WAITLISTED"
        ]
        candidates.sort(key=lambda b: b["created_at"])
        promoted = None
        for cand in candidates:
            owner = db.members.get(cand["member_id"])
            if owner is None:
                continue
            if owner.get("account_posture") != "OPEN":
                continue
            promoted = cand
            break
        if promoted is None:
            return
        # promote
        promoted["status"] = "RESERVED"
        promoted["waitlist_position"] = None
        class_session["reserved_seat_count"] += 1
        promoted["_had_seat"] = True
        # recompute provisional_price_cents at present clock
        coupon = db.coupons.get(promoted["applied_coupon_id"]) if promoted.get("applied_coupon_id") else None
        member = db.members.get(promoted["member_id"])
        trainer = None
        promoted["provisional_price_cents"] = booking_provisional_price(
            booking_kind=promoted["booking_kind"],
            class_session=class_session,
            trainer=trainer,
            member_tier=member["tier"],
            starts_at=promoted["starts_at"],
            ends_at=promoted["ends_at"],
            coupon=coupon,
            now=CLOCK.now(),
        )
        bump(promoted)
        bump(class_session)


# ------------------------- member access cascades ----------------------------
def member_set_suspended(member, duration_days):
    now = CLOCK.now()
    member["suspension_window_start"] = now
    member["suspension_window_end"] = now + timedelta(days=duration_days)
    member["access_status"] = "SUSPENDED"
    recompute_posture(member)
    bump(member)
    cascade_cancel_member_bookings(member, future_only=True, reason="member_suspended")


def member_clear_suspension(member):
    member["suspension_window_start"] = None
    member["suspension_window_end"] = None
    if member["billing_status"] == "DELINQUENT":
        # Cannot go back to ACTIVE while billing is DELINQUENT
        member["access_status"] = "FROZEN"
    else:
        member["access_status"] = "ACTIVE"
    recompute_posture(member)
    bump(member)


def member_cascade_to_frozen(member):
    """Delinquency cascade: SUSPENDED then FROZEN, posture FROZEN, cancel future bookings."""
    member["access_status"] = "FROZEN"
    member["suspension_window_start"] = None
    member["suspension_window_end"] = None
    recompute_posture(member)
    bump(member)
    cascade_cancel_member_bookings(member, future_only=True, reason="delinquency")


def member_cascade_to_active(member):
    """Reinstatement: bring access back from FROZEN/SUSPENDED to ACTIVE."""
    member["access_status"] = "ACTIVE"
    member["suspension_window_start"] = None
    member["suspension_window_end"] = None
    recompute_posture(member)
    bump(member)


# ------------------------- payment-attempt processing -----------------------
def process_payment_attempt(*, member, subscription, outcome, attempt_id,
                            attempt_number, amount_cents, gateway_txn_id,
                            idempotency_key, failure_reason):
    """Apply post-payment side effects to subscription/member state machines.

    Returns the created PaymentAttempt dict (caller is responsible for persisting it).
    """
    now = CLOCK.now()
    pa = {
        "id": attempt_id,
        "subscription_id": subscription["id"],
        "member_id": member["id"],
        "attempt_number": attempt_number,
        "amount_cents": amount_cents,
        "gateway_txn_id": gateway_txn_id,
        "idempotency_key": idempotency_key,
        "outcome": outcome,
        "failure_reason": failure_reason,
        "created_at": now,
    }
    db.payment_attempts[pa["id"]] = pa
    sub_record_attempt(subscription, pa)

    if outcome == "SUCCESS":
        _on_success(member, subscription, pa)
    elif outcome in ("FAILED", "DECLINED"):
        _on_failure(member, subscription, pa)
    return pa


def sub_record_attempt(subscription, pa):
    """Cache an ordered list of attempts on the subscription for quick access."""
    attempts = subscription.setdefault("_attempts", [])
    attempts.append(pa["id"])


def _add_cycle(start, billing_cycle):
    from datetime import timedelta
    if billing_cycle == "MONTHLY":
        return start + timedelta(days=30)
    if billing_cycle == "ANNUAL":
        return start + timedelta(days=365)
    return start + timedelta(days=30)


def _on_success(member, subscription, pa):
    now = CLOCK.now()
    # Wallet: debit the wallet_applied that was used by this attempt's amount
    # We recompute wallet_applied as min(wallet, net_after_coupon) and debit.
    # But: if attempt_number > 1, the wallet was already consumed by attempt 1
    # so we skip the wallet debit on retries.
    if pa["attempt_number"] == 1:
        # Find applied coupon
        coupon = None
        if subscription.get("applied_coupon_id"):
            coupon = db.coupons.get(subscription["applied_coupon_id"])
        gross = subscription["base_price_cents"]
        if coupon and coupon["applicable_to"] in ("SUBSCRIPTION", "BOTH"):
            from decimal import Decimal
            from common import round_half_up_to_int
            if coupon["kind"] == "PERCENT_OFF":
                discount = round_half_up_to_int(Decimal(gross) * Decimal(coupon["value"]) / Decimal(100))
            elif coupon["kind"] == "FIXED_OFF_CENTS":
                discount = min(coupon["value"], gross)
            elif coupon["kind"] == "REFERRAL_REWARD":
                discount = min(coupon["value"], gross)
            else:
                discount = 0
        else:
            discount = 0
        net = gross - discount
        wallet = max(0, member.get("wallet_credit_cents", 0))
        wallet_applied = min(wallet, net)
        if wallet_applied > 0:
            member["wallet_credit_cents"] = member["wallet_credit_cents"] - wallet_applied
            member_wallet_ledger_append(member, "subscription_charge_wallet_debit",
                                        -wallet_applied, ref_id=pa["id"])
            bump(member)
        # Consume coupon if any
        if coupon is not None:
            coupon_increment(coupon)
            # Referral reward coupons consumed = mark referral as PAID_OUT
            if coupon["kind"] == "REFERRAL_REWARD":
                for r in db.referrals.values():
                    if r.get("minted_coupon_id") == coupon["id"] and r["status"] == "QUALIFIED":
                        r["status"] = "PAID_OUT"
                        bump(r)

    # Activate or roll the subscription forward
    if subscription["status"] == "PENDING_ACTIVATION":
        subscription["status"] = "ACTIVE"
        subscription["current_period_start"] = now
        subscription["current_period_end"] = _add_cycle(now, subscription["billing_cycle"])
        subscription["failed_payment_attempts"] = 0
        subscription["grace_period_end"] = None
        bump(subscription)
        # Tier resolution from plan
        member["tier"] = subscription["plan"]
        bump(member)
        # Referral: qualify the invitee's reward if any
        _try_qualify_referral(member, subscription, pa)
    else:
        prior_status = subscription["status"]
        # Reset failure counter and grace_period_end
        subscription["failed_payment_attempts"] = 0
        subscription["grace_period_end"] = None
        if prior_status in ("PAST_DUE", "GRACE"):
            subscription["status"] = "ACTIVE"
            member["billing_status"] = "REINSTATED"
            recompute_posture(member)
            bump(member)
        else:
            # Renewal SUCCESS — roll period forward
            subscription["current_period_start"] = subscription.get("current_period_end") or now
            subscription["current_period_end"] = _add_cycle(subscription["current_period_start"], subscription["billing_cycle"])
            # Clean rollover from REINSTATED -> CURRENT
            if member["billing_status"] == "REINSTATED":
                member["billing_status"] = "CURRENT"
                recompute_posture(member)
                bump(member)
        bump(subscription)


def _on_failure(member, subscription, pa):
    """Failed/Declined payment attempt — increment counter, transition states."""
    if subscription["status"] in ("ACTIVE", "PENDING_ACTIVATION"):
        # First failure of a new period: PAST_DUE cascade
        if pa["attempt_number"] == 1 and subscription["status"] == "ACTIVE":
            subscription["status"] = "PAST_DUE"
            subscription["failed_payment_attempts"] = 1
            bump(subscription)
            member["billing_status"] = "PAST_DUE"
            recompute_posture(member)
            bump(member)
        else:
            subscription["failed_payment_attempts"] = subscription.get("failed_payment_attempts", 0) + 1
            bump(subscription)
    elif subscription["status"] == "PAST_DUE":
        subscription["failed_payment_attempts"] = subscription.get("failed_payment_attempts", 0) + 1
        if subscription["failed_payment_attempts"] >= RETRY_LIMIT:
            # Enter GRACE
            subscription["status"] = "GRACE"
            subscription["grace_period_end"] = CLOCK.now() + timedelta(days=grace_period_days(member["state_code"]))
            member["billing_status"] = "GRACE"
            # Apply late-payment penalty to wallet
            penalty = compute_late_payment_penalty(member["state_code"], subscription["base_price_cents"])
            member["wallet_credit_cents"] = member.get("wallet_credit_cents", 0) - penalty
            member_wallet_ledger_append(member, "late_payment_penalty", -penalty,
                                        ref_id=subscription["id"],
                                        note=f"state={member['state_code']} pct={penalty}")
            recompute_posture(member)
            bump(member)
        bump(subscription)
    elif subscription["status"] == "GRACE":
        subscription["failed_payment_attempts"] = subscription.get("failed_payment_attempts", 0) + 1
        bump(subscription)
    elif subscription["status"] == "DELINQUENT":
        # No state change on failed attempts while delinquent (manual reinstate required)
        subscription["failed_payment_attempts"] = subscription.get("failed_payment_attempts", 0) + 1
        bump(subscription)


def _try_qualify_referral(member, subscription, pa):
    """If member has a pending referral (as invitee), QUALIFY it."""
    for r in list(db.referrals.values()):
        if r["invitee_member_id"] != member["id"]:
            continue
        if r["status"] != "PENDING":
            continue
        r["status"] = "QUALIFIED"
        r["qualifying_attempt_id"] = pa["id"]
        r["reward_value_cents"] = REFERRAL_REWARD_CENTS_BY_PLAN.get(subscription["plan"], 1000)
        # Mint coupon to sponsor
        coupon_id = gen_uuid()
        now = CLOCK.now()
        coupon = {
            "id": coupon_id,
            "code": _mint_coupon_code(),
            "kind": "REFERRAL_REWARD",
            "value": r["reward_value_cents"],
            "applicable_to": "SUBSCRIPTION",
            "valid_from": now,
            "valid_until": now + timedelta(days=365),
            "max_redemptions": 1,
            "redemption_count": 0,
            "status": "ACTIVE",
            "tied_to_member_id": r["sponsor_member_id"],
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.coupons[coupon_id] = coupon
        r["minted_coupon_id"] = coupon_id
        bump(r)


def _mint_coupon_code():
    import secrets, string
    return "REF" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(9))


# ------------------------- clock-driven sweeps ------------------------------
def clock_advance_cascades():
    """After CLOCK.now() has been moved forward, fire all time-gated transitions."""
    now = CLOCK.now()
    # 1. Class sessions: SCHEDULED -> LOCKED -> COMPLETED
    for cs in list(db.class_sessions.values()):
        if cs["status"] == "SCHEDULED":
            lock_at = cs["starts_at"] - timedelta(minutes=CONFIRM_CUTOFF_MINUTES)
            if now >= lock_at:
                cs["status"] = "LOCKED"
                bump(cs)
                # Cascade: cancel RESERVED bookings that have not confirmed
                for b in list(db.bookings.values()):
                    if b.get("class_session_id") == cs["id"] and b["status"] == "RESERVED":
                        owner = db.members.get(b["member_id"])
                        if owner is not None:
                            _cancel_booking_admin(b, owner, reason="session_locked")
        if cs["status"] == "LOCKED" and now > cs["ends_at"]:
            cs["status"] = "COMPLETED"
            bump(cs)
            # Cascade: CONFIRMED-without-checkin -> NO_SHOW
            for b in list(db.bookings.values()):
                if b.get("class_session_id") == cs["id"] and b["status"] == "CONFIRMED" and not b.get("gate_check_in_at"):
                    owner = db.members.get(b["member_id"])
                    if owner is not None:
                        _mark_no_show(b, owner)

    # 2. Subscriptions GRACE -> DELINQUENT
    for sub in list(db.subscriptions.values()):
        if sub["status"] == "GRACE" and sub.get("grace_period_end") and now >= sub["grace_period_end"]:
            sub["status"] = "DELINQUENT"
            bump(sub)
            member = db.members.get(sub["member_id"])
            if member:
                member["billing_status"] = "DELINQUENT"
                recompute_posture(member)
                bump(member)
                member_cascade_to_frozen(member)

    # 3. Subscriptions ACTIVE: period rolled over without a paid attempt
    # We don't auto-issue payment attempts. But we do flip Member.billing_status
    # REINSTATED -> CURRENT after a clean rollover with no failed first attempt.
    for sub in list(db.subscriptions.values()):
        if sub["status"] == "ACTIVE" and sub.get("current_period_end") and now > sub["current_period_end"] + timedelta(seconds=1):
            member = db.members.get(sub["member_id"])
            if member and member["billing_status"] == "REINSTATED":
                # Has there been a failed attempt since current_period_end?
                attempts_in_new_period = []
                for aid in sub.get("_attempts", []):
                    pa = db.payment_attempts.get(aid)
                    if pa and pa["created_at"] >= sub["current_period_end"]:
                        attempts_in_new_period.append(pa)
                if not any(a["outcome"] in ("FAILED", "DECLINED") and a["attempt_number"] == 1 for a in attempts_in_new_period):
                    member["billing_status"] = "CURRENT"
                    recompute_posture(member)
                    bump(member)

    # 4. Members SUSPENDED -> ACTIVE on suspension_window_end
    for m in list(db.members.values()):
        if m["access_status"] == "SUSPENDED" and m.get("suspension_window_end") and now >= m["suspension_window_end"]:
            member_clear_suspension(m)


def sweep_run():
    """Periodic sweep: NO_SHOW CONFIRMED bookings past ends_at; waitlist tidy-up."""
    now = CLOCK.now()
    for b in list(db.bookings.values()):
        if b["status"] != "CONFIRMED":
            continue
        cs = db.class_sessions.get(b.get("class_session_id")) if b.get("class_session_id") else None
        if cs is None:
            continue
        if now > cs["ends_at"] and not b.get("gate_check_in_at"):
            owner = db.members.get(b["member_id"])
            if owner:
                _mark_no_show(b, owner)
    # Waitlist promotion check
    for cs in list(db.class_sessions.values()):
        if cs["status"] in ("SCHEDULED", "LOCKED"):
            promote_waitlist(cs)


def _mark_no_show(booking, member):
    """Transition booking CONFIRMED -> NO_SHOW; apply penalty; maybe suspend member."""
    prov = booking.get("provisional_price_cents", 0) or 0
    booking["status"] = "NO_SHOW"
    booking["final_price_cents"] = prov + NO_SHOW_PENALTY_CENTS
    bump(booking)
    # Wallet debit for no-show penalty
    member["wallet_credit_cents"] = member.get("wallet_credit_cents", 0) - NO_SHOW_PENALTY_CENTS
    member_wallet_ledger_append(member, "no_show_penalty", -NO_SHOW_PENALTY_CENTS,
                                ref_id=booking["id"])
    # Recompute strike count
    strike_count = _recompute_strike_count(member)
    member["no_show_strike_count"] = strike_count
    bump(member)
    if strike_count >= NO_SHOW_STRIKE_LIMIT:
        # Cascade to SUSPENDED for STRIKE_SUSPENSION_DAYS
        member_set_suspended(member, STRIKE_SUSPENSION_DAYS)
    # Free the seat if it had one (since now terminal, seat no longer occupied)
    if booking.get("class_session_id") and booking.get("_had_seat", False):
        cs = db.class_sessions.get(booking["class_session_id"])
        if cs:
            cs["reserved_seat_count"] = max(0, cs["reserved_seat_count"] - 1)
            bump(cs)


def _recompute_strike_count(member):
    now = CLOCK.now()
    window_start = now - timedelta(days=NO_SHOW_WINDOW_DAYS)
    count = 0
    for b in db.bookings.values():
        if b["member_id"] != member["id"]:
            continue
        if b["status"] != "NO_SHOW":
            continue
        # use updated_at as the proxy for the NO_SHOW transition time
        when = b.get("updated_at") or b.get("created_at")
        if when and when >= window_start:
            count += 1
    return count

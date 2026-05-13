"""Card lifecycle, freeze, refund, transfer, renewal logic."""
import math
from clock import now, to_iso_ms, end_of_day, end_of_day_after_days, whole_days_between
from db import state, new_id, next_order, stamp_create, bump
from errors import raise_err
from .calc import round_half_up, mul_bp_round_half_up
from . import wallet as wallet_svc


# ---------------- Helpers ----------------

def get_card(card_id):
    return state["cards"].get(card_id)


def get_card_type(card_type_id):
    return state["card_types"].get(card_type_id)


def visits_remaining(card):
    ct = state["card_types"].get(card["card_type_id"])
    if not ct:
        return None
    quota = ct.get("visit_quota", 0)
    if quota <= 0:
        return None
    return max(quota - card.get("visits_consumed", 0), 0)


def freeze_episodes_for(card_id):
    return [f for f in state["freeze_episodes"].values() if f["card_id"] == card_id]


def cumulative_freeze_days(card_id):
    """Sum of actual_days for SETTLED episodes per §3.2 definition.

    This represents the days actually charged against the card lifetime budget.
    The 'effective_expiry' computation uses a different set ({SETTLED, APPROVED, CANCELED}).
    """
    return sum(
        f.get("actual_days", 0)
        for f in freeze_episodes_for(card_id)
        if f["status"] == "SETTLED"
    )


def compute_effective_expiry(card):
    """effective_expiry = original_expiry + sum of actual_days for episodes in
    {SETTLED, APPROVED, CANCELED}. End of day UTC."""
    if not card.get("original_expiry_date"):
        return None
    total = 0
    for f in freeze_episodes_for(card["id"]):
        if f["status"] in ("SETTLED", "APPROVED", "CANCELED"):
            total += f.get("actual_days", 0)
    from datetime import timedelta
    eff = card["original_expiry_date"] + timedelta(days=total)
    return end_of_day(eff)


def recompute_card_freeze_state(card):
    """Refresh cumulative_freeze_days and effective_expiry_date on card."""
    card["cumulative_freeze_days"] = cumulative_freeze_days(card["id"])
    card["effective_expiry_date"] = compute_effective_expiry(card)


# ---------------- Issuance ----------------

def issue_card(card_type_id, holder_member_id):
    ct = get_card_type(card_type_id)
    if not ct:
        raise_err("ERR_NOT_FOUND", "card_type not found")
    member = state["members"].get(holder_member_id)
    if not member:
        raise_err("ERR_NOT_FOUND", "holder member not found")
    # State check first: card type retired => ERR_CARD_TYPE_RETIRED
    if ct.get("status") != "ACTIVE":
        raise_err("ERR_CARD_TYPE_RETIRED", "card type is retired")
    # Wallet debit for the card price (fiscal)
    card_id = new_id()
    # Debit before card creation? PRD says issuance also debits wallet for
    # CardType.price_cents. If insufficient, ERR_INSUFFICIENT_BALANCE.
    if ct["price_cents"] > 0:
        wallet_svc.debit(
            holder_member_id, ct["price_cents"],
            service_type="CARD_ISSUANCE",
            ref_entity=f"Card:{card_id}",
        )
    card = {
        "id": card_id,
        "card_type_id": card_type_id,
        "holder_member_id": holder_member_id,
        "issuance_price_cents": ct["price_cents"],
        "activation_date": None,
        "original_expiry_date": None,
        "effective_expiry_date": None,
        "visits_consumed": 0,
        "cumulative_freeze_days": 0,
        "status": "PENDING",
        "parent_card_id": None,
    }
    stamp_create(card)
    state["cards"][card_id] = card
    return card


def activate_card(card):
    if card["status"] != "PENDING":
        raise_err("ERR_INVALID_STATE", "card not PENDING")
    ct = get_card_type(card["card_type_id"])
    if ct.get("status") != "ACTIVE":
        raise_err("ERR_CARD_TYPE_RETIRED", "card type retired")
    activation = now()
    card["activation_date"] = activation
    card["original_expiry_date"] = end_of_day_after_days(activation, ct["validity_days"])
    card["effective_expiry_date"] = card["original_expiry_date"]
    card["status"] = "ACTIVE"
    bump(card)
    return card


# ---------------- Freeze ----------------

def freeze_card(card, reason, requested_days):
    if card["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "card not ACTIVE")
    ct = get_card_type(card["card_type_id"])
    # Budget check (priority 22)
    remaining_budget = ct["max_freeze_days"] - card.get("cumulative_freeze_days", 0)
    if remaining_budget <= 0:
        # Create REQUESTED then REJECTED episode and raise
        fe = {
            "id": new_id(),
            "card_id": card["id"],
            "reason": reason,
            "requested_days": requested_days,
            "actual_days": 0,
            "starts_at": None,
            "ends_at": None,
            "status": "REJECTED",
        }
        stamp_create(fe)
        state["freeze_episodes"][fe["id"]] = fe
        raise_err("ERR_FREEZE_BUDGET_EXHAUSTED", "freeze budget exhausted")
    # In-progress check (priority 23) — only one APPROVED freeze
    for f in freeze_episodes_for(card["id"]):
        if f["status"] == "APPROVED":
            raise_err("ERR_FREEZE_IN_PROGRESS", "freeze in progress")
    # Booking conflict check (priority 24)
    actual_days = min(requested_days, remaining_budget)
    starts_at = now()
    ends_at = end_of_day_after_days(starts_at, actual_days)
    for b in state["pt_bookings"].values():
        if b["member_id"] == card["holder_member_id"] and b["status"] == "CONFIRMED":
            scheduled = b.get("scheduled_starts_at")
            if scheduled and starts_at <= scheduled <= ends_at:
                raise_err(
                    "ERR_FREEZE_CONFLICTS_WITH_BOOKING",
                    "card has CONFIRMED PT booking inside the freeze window",
                )
    # Approve
    fe = {
        "id": new_id(),
        "card_id": card["id"],
        "reason": reason,
        "requested_days": requested_days,
        "actual_days": actual_days,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "APPROVED",
    }
    stamp_create(fe)
    state["freeze_episodes"][fe["id"]] = fe
    # Cascade card
    card["status"] = "FROZEN"
    # cumulative_freeze_days per §3.5: rises by actual_days
    card["cumulative_freeze_days"] = card.get("cumulative_freeze_days", 0) + actual_days
    card["effective_expiry_date"] = compute_effective_expiry(card)
    bump(card)
    return fe


def settle_freeze(fe):
    """Time-driven SETTLED transition."""
    if fe["status"] != "APPROVED":
        return
    fe["status"] = "SETTLED"
    bump(fe)
    card = get_card(fe["card_id"])
    if card and card["status"] == "FROZEN":
        card["status"] = "ACTIVE"
        recompute_card_freeze_state(card)
        bump(card)


def cancel_freeze_early(card, freeze_episode_id):
    """POST /cards/{id}/unfreeze."""
    fe = state["freeze_episodes"].get(freeze_episode_id)
    if not fe:
        raise_err("ERR_NOT_FOUND", "freeze episode not found")
    if fe["card_id"] != card["id"]:
        raise_err("ERR_NOT_FOUND", "freeze episode not for this card")
    if fe["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "freeze episode not APPROVED")
    if card["status"] != "FROZEN":
        raise_err("ERR_INVALID_STATE", "card not FROZEN")
    # actual_days := ceil((now - starts_at) in days)
    delta_seconds = (now() - fe["starts_at"]).total_seconds()
    elapsed_days = max(0, math.ceil(delta_seconds / 86400))
    fe["actual_days"] = elapsed_days
    fe["ends_at"] = now()
    fe["status"] = "CANCELED"
    bump(fe)
    card["status"] = "ACTIVE"
    recompute_card_freeze_state(card)
    bump(card)
    return fe


# ---------------- Remaining value (forward-looking) ----------------

def remaining_value_forward(card):
    """Forward-looking remaining value in cents."""
    ct = get_card_type(card["card_type_id"])
    if ct["category"] == "PER_VISIT":
        quota = ct["visit_quota"]
        if quota <= 0:
            return 0
        from decimal import Decimal
        unit_value = Decimal(card["issuance_price_cents"]) / Decimal(quota)
        vr = visits_remaining(card) or 0
        return round_half_up(unit_value * Decimal(vr))
    else:  # MONTHLY / ANNUAL
        eff = card.get("effective_expiry_date")
        if not eff:
            return 0
        remaining_days = max(0, whole_days_between(eff, now()))
        from decimal import Decimal
        val = Decimal(card["issuance_price_cents"]) * Decimal(remaining_days) / Decimal(ct["validity_days"])
        return round_half_up(val)


def remaining_value_chronological(card):
    """Day-by-day, round-per-day, then sum. MONTHLY/ANNUAL only."""
    ct = get_card_type(card["card_type_id"])
    if ct["category"] == "PER_VISIT":
        return None
    eff = card.get("effective_expiry_date")
    if not eff:
        return 0
    remaining_days = max(0, whole_days_between(eff, now()))
    from decimal import Decimal
    per_day = Decimal(card["issuance_price_cents"]) / Decimal(ct["validity_days"])
    total = 0
    for _ in range(remaining_days):
        total += round_half_up(per_day)
    return total


# ---------------- Refund ----------------

def refund_card(card):
    if card["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "card not ACTIVE")
    ct = get_card_type(card["card_type_id"])
    # Eligibility fiscal-window check (priority 18) first
    eff = card.get("effective_expiry_date")
    remaining_days = whole_days_between(eff, now()) if eff else 0
    if remaining_days < ct["refund_eligibility_days"]:
        raise_err("ERR_REFUND_NOT_ELIGIBLE", "remaining validity below threshold")
    # Ever-frozen check (priority 19)
    for f in freeze_episodes_for(card["id"]):
        if f["status"] == "SETTLED":
            raise_err("ERR_REFUND_FROZEN_CARD_BLOCKED", "card was frozen")
    # Compute remaining value
    rv = remaining_value_forward(card)
    if rv > 0:
        wallet_svc.refund_credit(
            card["holder_member_id"], rv,
            ref_entity=f"Card:{card['id']}",
        )
    # Reverse unconsumed package commissions tied to this card's holder
    from . import package as pkg_svc
    pkg_svc.reverse_unconsumed_for_member(card["holder_member_id"])
    # State change
    card["status"] = "REFUNDED"
    bump(card)
    return card


# ---------------- Transfer ----------------

def transfer_card(card, to_member_id, actor_role, actor_id):
    if card["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "card not ACTIVE")
    if card.get("visits_consumed", 0) > 0:
        raise_err("ERR_TRANSFER_NOT_ELIGIBLE", "card has been used")
    # No active or settled freeze allowed for transfer
    for f in freeze_episodes_for(card["id"]):
        if f["status"] in ("APPROVED", "SETTLED"):
            raise_err("ERR_TRANSFER_NOT_ELIGIBLE", "card has freeze history")
    src_member = state["members"].get(card["holder_member_id"])
    dst_member = state["members"].get(to_member_id)
    if not dst_member:
        raise_err("ERR_NOT_FOUND", "destination member not found")
    ct = get_card_type(card["card_type_id"])
    # Relationship rule
    same_family = (
        src_member.get("family_group_id")
        and src_member.get("family_group_id") == dst_member.get("family_group_id")
    )
    family_share = ct.get("family_shareable", False)
    issued_within_7 = False
    if card.get("created_at"):
        delta_days = whole_days_between(now(), card["created_at"])
        if delta_days <= 7:
            issued_within_7 = True
    if not (same_family or family_share or issued_within_7):
        raise_err("ERR_TRANSFER_INELIGIBLE_RECIPIENT", "recipient not eligible")
    # Compute fee
    rv = remaining_value_forward(card)
    fee = mul_bp_round_half_up(rv, ct["transfer_fee_pct_bp"])
    MIN_FEE = 2000
    fee = max(fee, MIN_FEE)
    # Debit transfer fee from acting card's source member's wallet? PRD says
    # "the wallet is debited for the transfer fee" — implicit holder source.
    wallet_svc.debit(
        card["holder_member_id"], fee,
        service_type="TRANSFER_FEE",
        ref_entity=f"Card:{card['id']}",
    )
    # State transition source card
    source_card_id = card["id"]
    from_member_id = card["holder_member_id"]
    card["status"] = "TRANSFERRED"
    bump(card)
    # Create destination card
    new_card_id = new_id()
    new_card = {
        "id": new_card_id,
        "card_type_id": card["card_type_id"],
        "holder_member_id": to_member_id,
        "issuance_price_cents": card.get("issuance_price_cents"),
        "activation_date": card.get("activation_date"),
        "original_expiry_date": card.get("original_expiry_date"),
        "effective_expiry_date": card.get("original_expiry_date"),
        "visits_consumed": 0,
        "cumulative_freeze_days": 0,
        "status": "ACTIVE",
        "parent_card_id": source_card_id,
    }
    stamp_create(new_card)
    state["cards"][new_card_id] = new_card
    # Append TransferRecord
    tr = {
        "id": new_id(),
        "source_card_id": source_card_id,
        "destination_card_id": new_card_id,
        "from_member_id": from_member_id,
        "to_member_id": to_member_id,
        "remaining_value_cents": rv,
        "transfer_fee_cents": fee,
        "created_at": now(),
        "_order": next_order(),
    }
    state["transfer_records"][tr["id"]] = tr
    return tr


# ---------------- Renewal Quote ----------------

def renewal_quote(card):
    ct = get_card_type(card["card_type_id"])
    eff = card.get("effective_expiry_date")
    if not eff:
        # Card pending — quote at full price
        base_disc_bp = 0
        days_to_expiry = None
    else:
        days_to_expiry = whole_days_between(eff, now())
        if days_to_expiry > 30:
            base_disc_bp = 0
        elif days_to_expiry >= 7:
            base_disc_bp = ct.get("renewal_discount_pct_bp", 0)
        elif days_to_expiry >= 0:
            base_disc_bp = ct.get("renewal_discount_pct_bp", 0) + 500
        else:
            base_disc_bp = 0
    base = ct["price_cents"]
    from decimal import Decimal
    discounted = Decimal(base) * Decimal(10000 - base_disc_bp) / Decimal(10000)
    price = round_half_up(discounted)
    return {
        "card_id": card["id"],
        "card_type_id": ct["id"],
        "days_to_expiry": days_to_expiry,
        "discount_pct_bp": base_disc_bp,
        "renewal_price_cents": price,
        "base_price_cents": base,
    }


# ---------------- Expiry / sweep ----------------

def expire_card(card):
    """Card ACTIVE -> EXPIRED. Auto-renew cascade if authorized AND T0 reminder
    has already been dispatched for this card."""
    if card["status"] != "ACTIVE":
        return
    card["status"] = "EXPIRED"
    bump(card)
    member = state["members"].get(card["holder_member_id"])
    if not member:
        return
    # Look for T0 reminder already dispatched for this card
    t0_exists = any(
        r["card_id"] == card["id"] and r["tier"] == "T0"
        for r in state["renewal_reminders"].values()
    )
    if member.get("auto_renew_authorized") and t0_exists:
        # Renewal cascade — create child PENDING, debit, then activate immediately
        ct = state["card_types"].get(card["card_type_id"])
        # Renewal price uses formula but days_to_expiry is now <=0; discount is 0
        quote = renewal_quote(card)
        price = quote["renewal_price_cents"]
        child_id = new_id()
        # Debit before child create might fail with insufficient balance — but
        # we still mark T0 LAPSED in that case? PRD: cascade does the debit;
        # if it fails the system treats the cascade as failing. We'll fall back
        # to LAPSED reminder.
        try:
            if price > 0:
                wallet_svc.debit(
                    card["holder_member_id"], price,
                    service_type="CARD_ISSUANCE",
                    ref_entity=f"Card:{child_id}",
                )
        except Exception:
            # Mark T0 LAPSED
            _emit_t0_reminder(card, status="LAPSED")
            return
        child = {
            "id": child_id,
            "card_type_id": card["card_type_id"],
            "holder_member_id": card["holder_member_id"],
            "issuance_price_cents": ct["price_cents"],
            "activation_date": None,
            "original_expiry_date": None,
            "effective_expiry_date": None,
            "visits_consumed": 0,
            "cumulative_freeze_days": 0,
            "status": "PENDING",
            "parent_card_id": card["id"],
        }
        stamp_create(child)
        state["cards"][child_id] = child
        # Activate immediately
        activate_card(child)
    else:
        # Dispatch a T0 LAPSED reminder
        _emit_t0_reminder(card, status="LAPSED")


def _emit_t0_reminder(card, status):
    member = state["members"].get(card["holder_member_id"])
    if not member:
        return
    channels = set(member.get("notification_channels", []))
    allowed = {"SMS", "EMAIL", "IM", "PUSH"}
    dispatched = sorted(list(channels & allowed))
    r = {
        "id": new_id(),
        "card_id": card["id"],
        "tier": "T0",
        "channels_dispatched": dispatched,
        "status": status,
        "created_at": now(),
        "_order": next_order(),
    }
    state["renewal_reminders"][r["id"]] = r
    return r


# ---------------- Manual reminder dispatch ----------------

def send_reminder(card, tier):
    member = state["members"].get(card["holder_member_id"])
    if not member:
        raise_err("ERR_NOT_FOUND", "holder member missing")
    channels = set(member.get("notification_channels", []))
    if tier == "T30":
        allowed = {"SMS", "EMAIL"}
    elif tier == "T7":
        allowed = {"SMS", "EMAIL", "IM"}
    elif tier == "T0":
        allowed = {"SMS", "EMAIL", "IM", "PUSH"}
    else:
        raise_err("ERR_VALIDATION", "invalid tier")
    dispatched = sorted(list(channels & allowed))
    # Determine status — for manual T0, follow auto_renew rule
    status = "SENT"
    if tier == "T0":
        if member.get("auto_renew_authorized"):
            status = "AUTO_RENEW_TRIGGERED"
        else:
            # Manual T0 — if days_to_expiry < 0 then LAPSED, else SENT
            eff = card.get("effective_expiry_date")
            days = whole_days_between(eff, now()) if eff else 0
            if days < 0:
                status = "LAPSED"
            else:
                status = "SENT"
    r = {
        "id": new_id(),
        "card_id": card["id"],
        "tier": tier,
        "channels_dispatched": dispatched,
        "status": status,
        "created_at": now(),
        "_order": next_order(),
    }
    state["renewal_reminders"][r["id"]] = r
    return r


def run_renewal_sweep():
    """Scan ACTIVE cards; emit reminders at exact day thresholds 30, 7, 0/lapsed."""
    emitted = []
    for card in list(state["cards"].values()):
        if card["status"] != "ACTIVE":
            continue
        eff = card.get("effective_expiry_date")
        if not eff:
            continue
        member = state["members"].get(card["holder_member_id"])
        if not member:
            continue
        channels = set(member.get("notification_channels", []))
        days = whole_days_between(eff, now())
        if days == 30:
            tier = "T30"
            allowed = {"SMS", "EMAIL"}
            status = "SENT"
        elif days == 7:
            tier = "T7"
            allowed = {"SMS", "EMAIL", "IM"}
            status = "SENT"
        elif days <= 0:
            tier = "T0"
            allowed = {"SMS", "EMAIL", "IM", "PUSH"}
            if member.get("auto_renew_authorized"):
                status = "AUTO_RENEW_TRIGGERED"
            elif days < 0:
                status = "LAPSED"
            else:
                status = "SENT"
        else:
            continue
        dispatched = sorted(list(channels & allowed))
        r = {
            "id": new_id(),
            "card_id": card["id"],
            "tier": tier,
            "channels_dispatched": dispatched,
            "status": status,
            "created_at": now(),
            "_order": next_order(),
        }
        state["renewal_reminders"][r["id"]] = r
        emitted.append(r)
    return emitted

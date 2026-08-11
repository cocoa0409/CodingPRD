"""coordinator_commission and commission_payout_value."""

from decimal import Decimal

from core.constants import (COMMISSION_BAND_1_MAX_CENTS, COMMISSION_BAND_1_RATE,
                            COMMISSION_BAND_2_MAX_CENTS, COMMISSION_BAND_2_RATE,
                            COMMISSION_BAND_3_RATE, COMMISSION_CASH_FEE_MIN_CENTS,
                            COMMISSION_CASH_FEE_PCT, COMMISSION_STORE_CREDIT_BONUS_PCT,
                            COMMISSION_VOLUNTEER_UNMET_MULTIPLIER)
from core.money import round_half_up
from core.store import DB, ordered, touch


def band_rate(base_subtotal_cents):
    """FLAT band, not marginal: the whole base takes the single band rate."""
    if base_subtotal_cents <= COMMISSION_BAND_1_MAX_CENTS:
        return Decimal(COMMISSION_BAND_1_RATE)
    if base_subtotal_cents <= COMMISSION_BAND_2_MAX_CENTS:
        return Decimal(COMMISSION_BAND_2_RATE)
    return Decimal(COMMISSION_BAND_3_RATE)


def multiplier_for(drop_run):
    if drop_run["volunteer_obligation_met"]:
        return Decimal("1.00")
    return Decimal(COMMISSION_VOLUNTEER_UNMET_MULTIPLIER)


def accrue(drop_run):
    base = drop_run["received_subtotal_cents"]
    rate = band_rate(base)
    multiplier = multiplier_for(drop_run)
    accrued = round_half_up(Decimal(base) * rate * multiplier)
    return DB.insert("CommissionAccrual", {
        "drop_run_id": drop_run["id"],
        "coordinator_member_id": drop_run["coordinator_member_id"],
        "base_subtotal_cents": base,
        "rate_applied": float(rate),
        "volunteer_multiplier_applied": float(multiplier),
        "accrued_cents": accrued,
        "clawback_cents": 0,
        "net_cents": accrued,
        "payout_mode": None,
        "payout_value_cents": 0,
        "status": "ACCRUED",
    })


def accruals_of(drop_run):
    return ordered([a for a in DB.commission_accruals.values()
                    if a["drop_run_id"] == drop_run["id"]])


def adjust_for_volunteer(drop_run):
    """Volunteer cascade hop 3: the obligation flipped, so the multiplier does."""
    changed = []
    for accrual in accruals_of(drop_run):
        if accrual["status"] != "ACCRUED":
            continue
        multiplier = multiplier_for(drop_run)
        rate = Decimal(str(accrual["rate_applied"]))
        accrual["volunteer_multiplier_applied"] = float(multiplier)
        accrual["accrued_cents"] = round_half_up(
            Decimal(accrual["base_subtotal_cents"]) * rate * multiplier)
        accrual["net_cents"] = accrual["accrued_cents"] - accrual["clawback_cents"]
        accrual["status"] = "ADJUSTED"
        touch(accrual)
        changed.append(accrual)
    return changed


def adjust_for_refund(drop_run, refund_amount_cents):
    """Refund cascade hop 3."""
    changed = []
    for accrual in accruals_of(drop_run):
        if accrual["status"] not in ("ACCRUED", "ADJUSTED"):
            continue
        rate = Decimal(str(accrual["rate_applied"]))
        multiplier = Decimal(str(accrual["volunteer_multiplier_applied"]))
        accrual["clawback_cents"] = round_half_up(
            Decimal(refund_amount_cents) * rate * multiplier)
        accrual["net_cents"] = accrual["accrued_cents"] - accrual["clawback_cents"]
        accrual["status"] = "ADJUSTED"
        touch(accrual)
        changed.append(accrual)
    return changed


def payout_value(net_cents, payout_mode):
    if payout_mode == "STORE_CREDIT":
        return round_half_up(Decimal(net_cents)
                             * (Decimal("1") + Decimal(COMMISSION_STORE_CREDIT_BONUS_PCT)))
    fee = max(COMMISSION_CASH_FEE_MIN_CENTS,
              round_half_up(Decimal(net_cents) * Decimal(COMMISSION_CASH_FEE_PCT)))
    return net_cents - fee

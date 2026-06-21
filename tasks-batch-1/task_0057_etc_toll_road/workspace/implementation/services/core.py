"""Shared business logic: ledger, balance moves, auto-reload, fines, account status."""
from db import db, init_ledger, touch, now_iso
from util import round_half_up


# ---------------------------------------------------------------------------
# Ledger / balance
# ---------------------------------------------------------------------------
def append_ledger(account, entry_type, amount_cents, ref_transaction_id=None,
                  ref_violation_id=None):
    """Apply amount_cents (signed) to account balance, append a LedgerEntry."""
    account["balance_cents"] += amount_cents
    entry = {
        "account_id": account["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "ref_transaction_id": ref_transaction_id,
        "ref_violation_id": ref_violation_id,
        "balance_after_cents": account["balance_cents"],
    }
    init_ledger(entry)
    db.ledger_entries[entry["id"]] = entry
    return entry


def apply_debit_and_reload(account, amount_cents, entry_type, ref_transaction_id=None,
                           ref_violation_id=None):
    """Debit the account (amount_cents > 0 means debit that much), append ledger,
    then evaluate auto-reload. account is mutated and touched."""
    if amount_cents != 0:
        append_ledger(account, entry_type, -amount_cents,
                      ref_transaction_id=ref_transaction_id,
                      ref_violation_id=ref_violation_id)
    evaluate_auto_reload(account)
    touch(account)


def evaluate_auto_reload(account):
    """Fire auto-reload if armed and balance <= threshold (inclusive)."""
    if not account.get("auto_reload_enabled"):
        return
    if account["balance_cents"] > account["low_balance_threshold_cents"]:
        return
    if account["reload_policy"] == "FIXED":
        credit = account["reload_amount_cents"]
    else:  # RESTORE_TO_TARGET
        credit = max(0, account["target_balance_cents"] - account["balance_cents"])
    if credit <= 0:
        return
    append_ledger(account, "RELOAD_CREDIT", credit)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
def compute_gross_toll(plaza, declared_axles, is_peak):
    axle_extra = max(0, declared_axles - 2) * plaza["axle_surcharge_cents"]
    pre_peak = plaza["base_rate_cents"] + axle_extra
    if is_peak:
        peaked = round_half_up(pre_peak * (10000 + plaza["peak_multiplier_bps"]), 10000)
    else:
        peaked = pre_peak
    return peaked


def compute_toll_cents(gross, read_method, plaza, hov_exempt=False):
    if hov_exempt:
        return 0
    if read_method == "TRANSPONDER":
        return gross
    # PLATE
    return round_half_up(gross * (10000 + plaza["plate_surcharge_bps"]), 10000)


def interop_home_debit(toll_cents, agency):
    withheld = round_half_up(toll_cents * agency["settlement_fee_bps"], 10000)
    return toll_cents - withheld


# ---------------------------------------------------------------------------
# Violation fines
# ---------------------------------------------------------------------------
BASE_PENALTY_CENTS = 2500
TIER_STEP_CENTS = 1500


def compute_fine(toll_due_cents, escalation_tier):
    penalty = BASE_PENALTY_CENTS + (escalation_tier - 1) * TIER_STEP_CENTS
    return penalty, toll_due_cents + penalty


# ---------------------------------------------------------------------------
# Account derived fields / status cascades
# ---------------------------------------------------------------------------
def recompute_outstanding_fines(account):
    total = 0
    for v in db.violations.values():
        if v.get("account_id") == account["id"] and \
                v["settlement_status"] in ("ASSESSED", "CONTESTED"):
            total += v["fine_total_cents"]
    if account["outstanding_fines_cents"] != total:
        account["outstanding_fines_cents"] = total
        touch(account)
    return total


def maybe_clear_delinquency(account):
    """If outstanding fines are 0 and account is DELINQUENT, return to ACTIVE."""
    if account["status"] == "DELINQUENT" and account["outstanding_fines_cents"] == 0:
        account["status"] = "ACTIVE"
        touch(account)


def make_delinquent_if_active(account):
    if account["status"] == "ACTIVE":
        account["status"] = "DELINQUENT"
        touch(account)

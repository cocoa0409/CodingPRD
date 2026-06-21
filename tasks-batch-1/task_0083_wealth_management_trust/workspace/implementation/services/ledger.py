"""Ledger reconciliation engine: balances, DNI, taxable income, carry-out, K-1.

All recomputes here refresh updated_at and bump version on the touched entity,
per PRD §2.4 / §2.5 (derived-figure recomputation is a mutation).
"""
from decimal import Decimal

import db
from services import calc


# ---------------------------------------------------------------------------
# Account-scoped ledger queries
# ---------------------------------------------------------------------------
def account_receipts(account_id):
    return [r for r in db.receipts.values() if r["account_id"] == account_id]


def account_disbursements(account_id):
    return [d for d in db.disbursements.values() if d["account_id"] == account_id]


def account_distributions(account_id):
    return [d for d in db.distributions.values() if d["account_id"] == account_id]


def trust_accounts(trust_id):
    return [a for a in db.accounts.values() if a["trust_id"] == trust_id]


# ---------------------------------------------------------------------------
# Trust balances (PRD §2.7)
# ---------------------------------------------------------------------------
def recompute_trust_balances(trust):
    """Recompute principal/income balances across all of the trust's accounts."""
    principal = 0
    income = 0
    for acct in trust_accounts(trust["id"]):
        for r in account_receipts(acct["id"]):
            if r["ledger_side"] == "PRINCIPAL":
                principal += r["amount_cents"]
            else:
                income += r["amount_cents"]
        for d in account_disbursements(acct["id"]):
            if d["ledger_side"] == "PRINCIPAL":
                principal -= d["amount_cents"]
            else:
                income -= d["amount_cents"]
        for dist in account_distributions(acct["id"]):
            if dist["status"] == "PAID":
                principal -= dist["funded_from_principal_cents"]
                income -= dist["funded_from_income_cents"]
    trust["principal_balance_cents"] = principal
    trust["income_balance_cents"] = income


def recompute_inclusion_ratio(trust):
    trust["inclusion_ratio"] = calc.inclusion_ratio(
        trust["gst_exemption_allocated_cents"], trust["principal_balance_cents"]
    )


def recompute_grantor_remaining(grantor):
    """gst_exemption_remaining = total - sum of allocated across grantor's trusts."""
    allocated = 0
    for t in db.trusts.values():
        if t["grantor_id"] == grantor["id"]:
            allocated += t["gst_exemption_allocated_cents"]
    grantor["gst_exemption_remaining_cents"] = grantor["gst_exemption_total_cents"] - allocated


# ---------------------------------------------------------------------------
# DNI and taxable income (PRD §3.4, calculations.distributable_net_income/trust_taxable_income)
# ---------------------------------------------------------------------------
def compute_dni(account_id):
    income_receipts = sum(
        r["amount_cents"] for r in account_receipts(account_id) if r["ledger_side"] == "INCOME"
    )
    income_expenses = sum(
        d["amount_cents"] for d in account_disbursements(account_id) if d["ledger_side"] == "INCOME"
    )
    return max(0, income_receipts - income_expenses)


def compute_retained_capital_gains(account_id):
    return sum(
        r["amount_cents"]
        for r in account_receipts(account_id)
        if r["ledger_side"] == "PRINCIPAL" and r["receipt_kind"] == "CAPITAL_GAIN"
    )


def recompute_account_figures(account):
    """Recompute dni_cents, dni_carried_out_cents, taxable_income_cents for an account."""
    account["dni_cents"] = compute_dni(account["id"])
    # carry-out depends on PAID distributions; computed by the waterfall.
    recompute_carryout(account)
    rcg = compute_retained_capital_gains(account["id"])
    account["taxable_income_cents"] = max(
        0, account["dni_cents"] - account["dni_carried_out_cents"] + rcg
    )


# ---------------------------------------------------------------------------
# Carry-out waterfall (PRD §3.6, calculations.distribution_dni_carryout)
# ---------------------------------------------------------------------------
def recompute_carryout(account):
    """Tiered waterfall: MANDATORY before DISCRETIONARY, created_at ASC within tier.

    Sets dni_carried_amount_cents on each PAID distribution and the account's
    dni_carried_out_cents. Does NOT bump versions here (caller decides which
    distributions changed). Returns the set of distributions whose carried
    amount changed.
    """
    remaining = account["dni_cents"]
    paid = [d for d in account_distributions(account["id"]) if d["status"] == "PAID"]
    ordered = sorted(
        paid,
        key=lambda d: (0 if d["distribution_kind"] == "MANDATORY" else 1, d["_seq"]),
    )
    changed = []
    for d in ordered:
        carried = min(d["amount_cents"], remaining)
        if d["dni_carried_amount_cents"] != carried:
            d["dni_carried_amount_cents"] = carried
            changed.append(d)
        remaining -= carried
    account["dni_carried_out_cents"] = account["dni_cents"] - remaining
    return changed


# ---------------------------------------------------------------------------
# K-1 character allocation (PRD §3.6, calculations.k1_character_allocation)
# ---------------------------------------------------------------------------
def recompute_k1(account):
    """Recompute (and create/update) K-1 statements for an account.

    Returns nothing; mutates db.k1s. Each K-1 that changes is version-bumped.
    Zeroes/creates K-1s for beneficiaries with carried distributions.
    """
    total_carried = account["dni_carried_out_cents"]
    dni = account["dni_cents"]

    # Beneficiaries with PAID, carrying distributions on this account.
    paid = [d for d in account_distributions(account["id"]) if d["status"] == "PAID"]
    per_ben = {}  # beneficiary_id -> summed dni_carried_amount_cents
    ben_first_seq = {}  # beneficiary_id -> earliest created_at sequence (for tie-break)
    for d in paid:
        bid = d["beneficiary_id"]
        per_ben[bid] = per_ben.get(bid, 0) + d["dni_carried_amount_cents"]
        if bid not in ben_first_seq or d["_seq"] < ben_first_seq[bid]:
            ben_first_seq[bid] = d["_seq"]

    existing_k1 = {
        k["beneficiary_id"]: k
        for k in db.k1s.values()
        if k["account_id"] == account["id"]
    }

    if total_carried == 0 or dni == 0:
        # Every K-1 line on the period is zero.
        for bid in per_ben:
            _upsert_k1(account["id"], bid, 0, 0, 0, existing_k1)
        # Also zero any pre-existing K-1s on this account whose beneficiary
        # is no longer carrying (e.g. after a reversal).
        for bid, k in existing_k1.items():
            if bid not in per_ben:
                _set_k1_lines(k, 0, 0, 0)
        return

    # Character pools (INCOME ledger).
    income_receipts = [r for r in account_receipts(account["id"]) if r["ledger_side"] == "INCOME"]
    income_disb_total = sum(
        d["amount_cents"] for d in account_disbursements(account["id"]) if d["ledger_side"] == "INCOME"
    )
    ord_receipts = sum(
        r["amount_cents"] for r in income_receipts
        if r["receipt_kind"] in ("INTEREST", "DIVIDEND_ORDINARY")
    )
    ord_pool = ord_receipts - income_disb_total
    qd_pool = sum(r["amount_cents"] for r in income_receipts if r["receipt_kind"] == "DIVIDEND_QUALIFIED")
    cg_pool = sum(r["amount_cents"] for r in income_receipts if r["receipt_kind"] == "CAPITAL_GAIN")

    scale = Decimal(total_carried) / Decimal(dni)
    char_ord = calc.round_half_up(Decimal(ord_pool) * scale)
    char_qd = calc.round_half_up(Decimal(qd_pool) * scale)
    char_cg = calc.round_half_up(Decimal(cg_pool) * scale)

    # Per-beneficiary rounding, then residual reconciliation to largest carried
    # share (tie-break earliest created_at).
    # Order beneficiaries by carried share DESC, then created_at ASC for the
    # residual recipient selection.
    ben_order = sorted(
        per_ben.keys(),
        key=lambda b: (-per_ben[b], ben_first_seq[b]),
    )

    lines = {}  # bid -> [ord, qd, cg]
    for bid in per_ben:
        share = Decimal(per_ben[bid]) / Decimal(total_carried)
        lines[bid] = [
            calc.round_half_up(Decimal(char_ord) * share),
            calc.round_half_up(Decimal(char_qd) * share),
            calc.round_half_up(Decimal(char_cg) * share),
        ]

    # Reconcile each character's residual to the largest-share beneficiary.
    if ben_order:
        residual_recipient = ben_order[0]
        for idx, char_total in enumerate((char_ord, char_qd, char_cg)):
            allocated = sum(lines[b][idx] for b in per_ben)
            residual = char_total - allocated
            lines[residual_recipient][idx] += residual

    for bid in per_ben:
        o, q, c = lines[bid]
        _upsert_k1(account["id"], bid, o, q, c, existing_k1)

    # Zero out any K-1s for beneficiaries no longer carrying.
    for bid, k in existing_k1.items():
        if bid not in per_ben:
            _set_k1_lines(k, 0, 0, 0)


def _set_k1_lines(k, o, q, c):
    new_total = o + q + c
    if (k["ordinary_income_cents"] == o and k["qualified_dividend_cents"] == q
            and k["capital_gain_cents"] == c and k["total_carried_cents"] == new_total):
        return  # no change, no version bump
    k["ordinary_income_cents"] = o
    k["qualified_dividend_cents"] = q
    k["capital_gain_cents"] = c
    k["total_carried_cents"] = new_total
    db.touch(k)


def _upsert_k1(account_id, beneficiary_id, o, q, c, existing):
    k = existing.get(beneficiary_id)
    if k is None:
        k = db.base_fields()
        k.update({
            "account_id": account_id,
            "beneficiary_id": beneficiary_id,
            "ordinary_income_cents": o,
            "qualified_dividend_cents": q,
            "capital_gain_cents": c,
            "total_carried_cents": o + q + c,
        })
        db.k1s[k["id"]] = k
        existing[beneficiary_id] = k
    else:
        _set_k1_lines(k, o, q, c)
    return k


# ---------------------------------------------------------------------------
# Full account + trust recompute after a ledger mutation.
# ---------------------------------------------------------------------------
def recompute_after_ledger_mutation(account, trust):
    """Recompute balances, account figures, carry-out, K-1 atomically; bump versions."""
    recompute_trust_balances(trust)
    recompute_inclusion_ratio(trust)
    # account figures cover dni, carry-out, taxable income
    recompute_account_figures(account)
    recompute_k1(account)
    db.touch(account)
    db.touch(trust)
    # grantor remaining unaffected by ledger; touched only on allocation.

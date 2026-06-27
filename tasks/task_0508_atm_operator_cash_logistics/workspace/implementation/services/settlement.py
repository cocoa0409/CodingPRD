"""Settlement revenue + commission split (PRD §3.10, §3.11, SCAFFOLD §1.3).

Settle sweeps WITHDRAWAL txns on the run's ATM with created_at in the half-open
[window_start, window_end) whose settlement_run_id is still null. From that set:
  withdrawal_count          = count(swept)
  surcharge_revenue_cents   = sum(surcharge_cents)
  interchange_revenue_cents = sum(interchange_rate(monthly_seq))  [MARGINAL per txn]
  network_fee_cents         = 8 * withdrawal_count
  net_operator_revenue_cents= surcharge + interchange - network_fee

Commission cascade (pinned order):
  pct  = floor(net * commission_pct_bps / 10000)
  flat = commission_flat_per_wd_cents * withdrawal_count
  base = per commission_basis
  mtd  = sum(commission_cents of ACCRUED+PAID statements for the merchant whose
             created_at is in the same clock calendar month, excl VOIDED, excl self)
  remaining = max(0, ceiling - mtd)
  commission_cents = 0 if merchant SUSPENDED else min(base, remaining)
  operator_keeps_cents = net - commission_cents
"""
from constants import (
    BPS_DENOMINATOR,
    NETWORK_FEE_PER_WD_CENTS,
    TIER1_CENTS,
    TIER1_MAX_SEQ,
    TIER2_CENTS,
    TIER2_MAX_SEQ,
    TIER3_CENTS,
)
from errors import err
from util import parse_iso


def interchange_rate(monthly_seq):
    if monthly_seq <= TIER1_MAX_SEQ:
        return TIER1_CENTS
    if monthly_seq <= TIER2_MAX_SEQ:
        return TIER2_CENTS
    return TIER3_CENTS


def _window_withdrawals(store, run):
    """All WITHDRAWAL txns on the run's ATM in [window_start, window_end),
    regardless of whether they are already bound to a run."""
    atm_id = run["atm_id"]
    start = parse_iso(run["window_start"])
    end = parse_iso(run["window_end"])
    hits = []
    for t in store.transactions.values():
        if t["atm_id"] != atm_id or t["kind"] != "WITHDRAWAL":
            continue
        created = parse_iso(t["created_at"])
        if start <= created < end:
            hits.append(t)
    return hits


def check_can_settle(store, run, atm):
    """Settle preconditions (priority 11 then 18)."""
    # ERR_NO_FEE_DISCLOSURE (priority 11): ATM must have an APPROVED disclosure.
    if not atm.get("fee_disclosure_id"):
        raise err("ERR_NO_FEE_DISCLOSURE", "ATM has no approved fee disclosure.")
    # ERR_TXN_ALREADY_SETTLED (priority 18): none of the withdrawals this run is
    # about to sweep may already be bound to another settlement run.
    for t in _window_withdrawals(store, run):
        if t["settlement_run_id"] is not None:
            raise err(
                "ERR_TXN_ALREADY_SETTLED",
                "A withdrawal in the window is already bound to another settlement run.",
            )


def settle(store, run, atm):
    # By here check_can_settle guarantees no window withdrawal is pre-bound, so
    # every window withdrawal is unbound and forms the swept set.
    swept = _window_withdrawals(store, run)

    withdrawal_count = len(swept)
    surcharge_revenue = sum(t["surcharge_cents"] for t in swept)
    interchange_revenue = sum(interchange_rate(t["monthly_seq"]) for t in swept)
    network_fee = NETWORK_FEE_PER_WD_CENTS * withdrawal_count
    net = surcharge_revenue + interchange_revenue - network_fee

    run["withdrawal_count"] = withdrawal_count
    run["surcharge_revenue_cents"] = surcharge_revenue
    run["interchange_revenue_cents"] = interchange_revenue
    run["network_fee_cents"] = network_fee
    run["net_operator_revenue_cents"] = net
    run["status"] = "SETTLED"

    # Bind each swept transaction (Transaction is append-only EXCEPT for this
    # one system-managed binding field, per §3.10).
    for t in swept:
        t["settlement_run_id"] = run["id"]

    store.touch(run)

    statement = _generate_commission(store, run, atm)
    return statement


def _month_key(iso_str):
    dt = parse_iso(iso_str)
    return (dt.year, dt.month)


def _generate_commission(store, run, atm):
    location = store.locations.get(atm["location_id"])
    merchant = store.site_merchants.get(location["site_merchant_id"])

    net = run["net_operator_revenue_cents"]
    withdrawal_count = run["withdrawal_count"]

    pct = (net * merchant["commission_pct_bps"]) // BPS_DENOMINATOR
    flat = merchant["commission_flat_per_wd_cents"] * withdrawal_count

    basis = merchant["commission_basis"]
    if basis == "GREATER_OF":
        base = max(pct, flat)
    elif basis == "PCT_ONLY":
        base = pct
    else:  # FLAT_ONLY
        base = flat

    statement = {
        "settlement_run_id": run["id"],
        "site_merchant_id": merchant["id"],
        "pct_amount_cents": pct,
        "flat_amount_cents": flat,
        "commission_cents": 0,
        "operator_keeps_cents": 0,
        "status": "ACCRUED",
    }
    store.stamp_new(statement)

    # Month-to-date for the ceiling cap, keyed on this statement's created_at
    # clock month, excluding VOIDED and excluding this statement.
    this_month = _month_key(statement["created_at"])
    mtd = 0
    for s in store.commission_statements.values():
        if s["id"] == statement["id"]:
            continue
        if s["site_merchant_id"] != merchant["id"]:
            continue
        if s["status"] not in ("ACCRUED", "PAID"):
            continue
        if _month_key(s["created_at"]) != this_month:
            continue
        mtd += s["commission_cents"]

    remaining = max(0, merchant["commission_monthly_ceiling_cents"] - mtd)
    if merchant["payout_status"] == "SUSPENDED":
        commission = 0
    else:
        commission = min(base, remaining)

    statement["commission_cents"] = commission
    statement["operator_keeps_cents"] = net - commission

    store.commission_statements[statement["id"]] = statement
    return statement

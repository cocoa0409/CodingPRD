"""Shared domain machinery: lookups, posture gating, the ledger and cascades."""
from datetime import timedelta

import clock
import db
from constants import (
    LEASE_STATUSES, MASTER_TENANT,
)
from errors import NOT_FOUND, ApiError
from services import calc
from util import F, add_days, as_date, deadline_after_days, fmt_dt, round_half_up

import constants as C


# ---------------------------------------------------------------------------
# lookups (rungs 6 and 7)
# ---------------------------------------------------------------------------
def lookup(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return db.COLLECTIONS[kind].get(row_id)


def require(kind, row_id):
    row = lookup(kind, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[kind])
    return row


# ---------------------------------------------------------------------------
# posture (PRD 2.6) — rungs 10 and 11
# ---------------------------------------------------------------------------
def compute_posture(trust):
    prop = db.properties.get(trust.get("property_id"))
    if prop is not None and prop.get("status") == "CONTRACT_EXPIRED":
        return "FROZEN"
    for event in db.exit_events.values():
        if event.get("trust_id") == trust["id"] and event.get("status") == "APPROVED":
            return "FROZEN"
    if trust.get("status") == "OPERATING" and \
            trust.get("reserve_balance_cents", 0) < trust.get("reserve_floor_cents", 0):
        return "RESTRICTED"
    return "OPEN"


def check_frozen(trust):
    if trust.get("posture") == "FROZEN":
        raise ApiError("ERR_TRUST_FROZEN")


def check_restricted(trust):
    if trust.get("posture") == "RESTRICTED":
        raise ApiError("ERR_TRUST_RESTRICTED")


def check_trust_status(trust, allowed):
    if trust.get("status") not in allowed:
        raise ApiError("ERR_TRUST_INVALID_STATE")


# ---------------------------------------------------------------------------
# related-row helpers
# ---------------------------------------------------------------------------
def trust_of_offering(offering):
    return db.trusts[offering["trust_id"]]


def trust_of_subscription(subscription):
    return trust_of_offering(db.offerings[subscription["offering_id"]])


def live_loan(trust):
    """The trust's single facility in COMMITTED or FUNDED."""
    for loan in db.sorted_rows(db.loans):
        if loan["trust_id"] == trust["id"] and loan["status"] in ("COMMITTED", "FUNDED"):
            return loan
    return None


def loan_principal(trust):
    loan = live_loan(trust)
    return loan["principal_cents"] if loan else 0


def funded_loan(trust):
    for loan in db.sorted_rows(db.loans):
        if loan["trust_id"] == trust["id"] and loan["status"] == "FUNDED":
            return loan
    return None


def any_loan(trust):
    for loan in db.sorted_rows(db.loans):
        if loan["trust_id"] == trust["id"] and loan["status"] != "PAID_OFF":
            return loan
    for loan in db.sorted_rows(db.loans):
        if loan["trust_id"] == trust["id"]:
            return loan
    return None


def executed_lease(trust):
    for lease in db.sorted_rows(db.leases):
        if lease["trust_id"] == trust["id"] and lease["status"] == "EXECUTED":
            return lease
    return None


def lease_for_period(trust, period_start):
    """The single lease in EXECUTED or TERMINATED whose term covers period_start."""
    candidates = [
        lease for lease in db.sorted_rows(db.leases)
        if lease["trust_id"] == trust["id"] and lease["status"] in ("EXECUTED", "TERMINATED")
    ]
    day = as_date(period_start)
    for lease in candidates:
        if as_date(lease["term_start_on"]) <= day <= as_date(lease["term_end_on"]):
            return lease
    for lease in candidates:
        if lease["status"] == "EXECUTED":
            return lease
    return candidates[0] if candidates else None


def offerings_of_trust(trust):
    return [o for o in db.sorted_rows(db.offerings) if o["trust_id"] == trust["id"]]


def effective_offering(trust):
    for offering in offerings_of_trust(trust):
        if offering["status"] == "EFFECTIVE":
            return offering
    return None


def subscriptions_of_offering(offering):
    return [s for s in db.sorted_rows(db.subscriptions)
            if s["offering_id"] == offering["id"]]


def closed_subscriptions_of_trust(trust):
    rows = []
    for offering in offerings_of_trust(trust):
        for sub in subscriptions_of_offering(offering):
            if sub["status"] == "CLOSED":
                rows.append(sub)
    rows.sort(key=lambda s: (
        s["closing_sequence_no"] if s.get("closing_sequence_no") is not None else 0,
        s["created_at"], s["_seq"],
    ))
    return rows


# ---------------------------------------------------------------------------
# the trust ledger (PRD 2.9, calculation trust_balances)
# ---------------------------------------------------------------------------
def book(trust, entry_type, bucket, amount_cents, source_kind, memo=None,
         occurred_at=None, reversal_of_entry_id=None):
    return db.new_row(db.ledger_entries, {
        "trust_id": trust["id"],
        "reversal_of_entry_id": reversal_of_entry_id,
        "entry_type": entry_type,
        "bucket": bucket,
        "amount_cents": amount_cents,
        "occurred_at": occurred_at if occurred_at is not None else clock.now(),
        "memo": memo,
        "source_kind": source_kind,
    }, journal=True)


def entries_of_trust(trust_id):
    return [e for e in db.sorted_rows(db.ledger_entries) if e["trust_id"] == trust_id]


def unreversed_entries(trust_id):
    entries = entries_of_trust(trust_id)
    reversed_ids = set()
    for entry in entries:
        if entry["entry_type"] == "REVERSAL" and entry.get("reversal_of_entry_id"):
            reversed_ids.add(entry["reversal_of_entry_id"])
    return [e for e in entries if e["id"] not in reversed_ids]


def bucket_balance(trust_id, bucket):
    # PRD 2.11: a bucket balance is the sum of the signed amounts of *every*
    # entry in that bucket. A reversal and the entry it names contribute nothing
    # between them precisely because both legs are counted.
    return sum(e["amount_cents"] for e in entries_of_trust(trust_id)
               if e["bucket"] == bucket)


def recompute_trust(trust, force=False):
    """Recompute every derived trust field; bump the version when anything moved."""
    entries = entries_of_trust(trust["id"])
    operating = sum(e["amount_cents"] for e in entries if e["bucket"] == "OPERATING")
    reserve = sum(e["amount_cents"] for e in entries if e["bucket"] == "RESERVE")
    units_issued = 0
    equity_raised = 0
    for offering in offerings_of_trust(trust):
        for sub in subscriptions_of_offering(offering):
            if sub["status"] == "CLOSED":
                units_issued += sub["units_requested"]
                equity_raised += sub["investment_amount_cents"] or 0
    before = (
        trust.get("operating_balance_cents"), trust.get("reserve_balance_cents"),
        trust.get("units_issued"), trust.get("equity_raised_cents"), trust.get("posture"),
    )
    trust["operating_balance_cents"] = operating
    trust["reserve_balance_cents"] = reserve
    trust["units_issued"] = units_issued
    trust["equity_raised_cents"] = equity_raised
    trust["posture"] = compute_posture(trust)
    after = (operating, reserve, units_issued, equity_raised, trust["posture"])
    if force or before != after:
        db.touch(trust)
    return trust


def refresh_posture(trust, force=False):
    before = trust.get("posture")
    trust["posture"] = compute_posture(trust)
    if force or before != trust["posture"]:
        db.touch(trust)
    return trust


# ---------------------------------------------------------------------------
# offering derived state
# ---------------------------------------------------------------------------
def compute_stack(offering):
    trust = trust_of_offering(offering)
    prop = db.properties[trust["property_id"]]
    return calc.capital_stack(
        prop["purchase_price_cents"], offering["closing_costs_cents"],
        loan_principal(trust), offering["reserve_funding_pct"], offering["load_pct"],
        trust["total_units"], offering["unit_price_cents"],
    )


def pin_stack(offering):
    stack = compute_stack(offering)
    offering["initial_reserve_cents"] = stack["initial_reserve_cents"]
    offering["target_equity_cents"] = stack["target_equity_cents"]
    offering["sponsor_load_cents"] = stack["sponsor_load_cents"]
    return stack


def recompute_offering_totals(offering, force=False):
    units = 0
    equity = 0
    for sub in subscriptions_of_offering(offering):
        if sub["status"] in ("RESERVED", "CLOSED"):
            units += sub["units_requested"]
            equity += sub["investment_amount_cents"] or 0
    before = (offering.get("units_committed"), offering.get("equity_committed_cents"))
    offering["units_committed"] = units
    offering["equity_committed_cents"] = equity
    if force or before != (units, equity):
        db.touch(offering)
    return offering


def recompute_boots(offering):
    """The boot figure is recomputed whenever the capital stack is recomputed."""
    trust = trust_of_offering(offering)
    principal = loan_principal(trust)
    for sub in subscriptions_of_offering(offering):
        if sub["status"] not in ("RESERVED", "REVISION_REQUIRED"):
            continue
        exchange_file = db.exchange_files.get(sub["exchange_file_id"])
        if exchange_file is None:
            continue
        boot = calc.subscription_boot(
            principal, sub["units_requested"], trust["total_units"],
            sub["investment_amount_cents"], exchange_file["net_proceeds_cents"],
            exchange_file["debt_retired_cents"],
        )
        if sub.get("boot_cents") != boot:
            sub["boot_cents"] = boot
            db.touch(sub)


def renumber_closings(offering):
    """Dense 1..n by closed_at ascending, created_at as the only tie-break."""
    closed = [s for s in subscriptions_of_offering(offering) if s["status"] == "CLOSED"]
    closed.sort(key=lambda s: (s["closed_at"], s["created_at"], s["_seq"]))
    for index, sub in enumerate(closed, start=1):
        if sub.get("closing_sequence_no") != index:
            sub["closing_sequence_no"] = index
            db.touch(sub)


# ---------------------------------------------------------------------------
# ownership (rung 3)
# ---------------------------------------------------------------------------
def check_investor_owns(user_id, investor_id):
    if investor_id is not None and user_id != investor_id:
        raise ApiError("ERR_FORBIDDEN_NOT_OWNER")


def check_master_tenant_of(user_id, trust):
    """The acting tenant must hold an EXECUTED lease on the target trust."""
    for lease in db.sorted_rows(db.leases):
        if lease["trust_id"] == trust["id"] and lease["status"] == "EXECUTED" \
                and lease["master_tenant_user_id"] == user_id:
            return lease
    raise ApiError("ERR_FORBIDDEN_NOT_OWNER")


# ---------------------------------------------------------------------------
# the four-hop closing cascade (PRD 3.5)
# ---------------------------------------------------------------------------
def close_subscription(sub):
    now = clock.now()
    offering = db.offerings[sub["offering_id"]]
    trust = trust_of_offering(offering)
    exchange_file = db.exchange_files[sub["exchange_file_id"]]

    sub["status"] = "CLOSED"
    sub["closed_at"] = now
    sub["rescission_deadline"] = add_days(now, offering["rescission_window_days"])
    entry = book(trust, "EQUITY_CONTRIBUTION", "OPERATING",
                 sub["investment_amount_cents"], "SUBSCRIPTION_CLOSE",
                 memo="Subscription close", occurred_at=now)
    sub["_equity_entry_id"] = entry["id"]
    db.touch(sub)

    exchange_file["status"] = "CLOSED_MATCHED"
    db.touch(exchange_file)

    renumber_closings(offering)
    recompute_offering_totals(offering)
    recompute_trust(trust)

    # hop 2 — the trust flips to OPERATING once the raise is complete
    loan = funded_loan(trust)
    lease = executed_lease(trust)
    if trust["status"] == "FUNDING" and loan is not None and lease is not None and \
            trust["equity_raised_cents"] >= (offering["target_equity_cents"] or 0):
        prop = db.properties[trust["property_id"]]
        trust["status"] = "OPERATING"
        book(trust, "SPONSOR_LOAD", "OPERATING", -(offering["sponsor_load_cents"] or 0),
             "SUBSCRIPTION_CLOSE", memo="Sponsor load", occurred_at=now)
        book(trust, "ACQUISITION_PAYMENT", "OPERATING",
             -(prop["purchase_price_cents"] + offering["closing_costs_cents"]),
             "ACQUISITION", memo="Acquisition payment", occurred_at=now)
        initial_reserve = offering["initial_reserve_cents"] or 0
        book(trust, "RESERVE_FUNDING", "OPERATING", -initial_reserve, "ACQUISITION",
             memo="Initial reserve funding", occurred_at=now)
        book(trust, "RESERVE_FUNDING", "RESERVE", initial_reserve, "ACQUISITION",
             memo="Initial reserve funding", occurred_at=now)
        recompute_trust(trust, force=True)

        # hop 3 — the offering closes
        offering["status"] = "CLOSED"
        db.touch(offering)

        # hop 4 — every still-reserved subscription is swept to REJECTED
        for other in subscriptions_of_offering(offering):
            if other["status"] == "RESERVED":
                other["status"] = "REJECTED"
                db.touch(other)
        recompute_offering_totals(offering)


def rescind_subscription(sub):
    now = clock.now()
    offering = db.offerings[sub["offering_id"]]
    trust = trust_of_offering(offering)
    exchange_file = db.exchange_files.get(sub["exchange_file_id"])

    sub["status"] = "RESCINDED"
    sub["closing_sequence_no"] = None
    db.touch(sub)

    book(trust, "REVERSAL", "OPERATING", -(sub["investment_amount_cents"] or 0),
         "REVERSAL", memo="Rescission reversal", occurred_at=now,
         reversal_of_entry_id=sub.get("_equity_entry_id"))

    renumber_closings(offering)
    recompute_offering_totals(offering)
    recompute_trust(trust)

    if exchange_file is not None and exchange_file["status"] == "CLOSED_MATCHED":
        if now <= exchange_file["identification_deadline"]:
            exchange_file["status"] = "OPEN"
        else:
            exchange_file["status"] = "EXPIRED"
        db.touch(exchange_file)


def reject_outstanding_subscriptions(subs):
    """Sweep RESERVED / REVISION_REQUIRED subscriptions to REJECTED."""
    touched_offerings = set()
    for sub in subs:
        if sub["status"] in ("RESERVED", "REVISION_REQUIRED"):
            sub["status"] = "REJECTED"
            db.touch(sub)
            touched_offerings.add(sub["offering_id"])
    for offering_id in touched_offerings:
        recompute_offering_totals(db.offerings[offering_id])


# ---------------------------------------------------------------------------
# distributions (PRD 3.8)
# ---------------------------------------------------------------------------
def distribution_replenishment(trust, distribution):
    lease = lease_for_period(trust, distribution["period_start"])
    days = calc.period_days(distribution["period_start"], distribution["period_end"])
    if lease is None:
        return 0, days, None
    return (
        calc.reserve_replenishment(lease["base_rent_annual_cents"],
                                   trust["reserve_target_pct"], days),
        days,
        lease,
    )


def final_cash_gross(trust, distribution):
    total = 0
    for entry in unreversed_entries(trust["id"]):
        if entry["entry_type"] in ("RENT_RECEIPT", "DEBT_SERVICE") and \
                distribution["period_start"] <= entry["occurred_at"] < distribution["period_end"]:
            total += entry["amount_cents"]
    return total


# ---------------------------------------------------------------------------
# exit close (PRD 3.9)
# ---------------------------------------------------------------------------
def close_exit(event, trust, loan):
    now = clock.now()
    prop = db.properties[trust["property_id"]]

    # step 1 — proceeds and debt
    net_proceeds = calc.exit_net_proceeds(
        event["exit_mode"], event["gross_price_cents"], event["selling_costs_cents"],
        loan["principal_cents"],
    )
    book(trust, "SALE_PROCEEDS", "OPERATING",
         event["gross_price_cents"] - event["selling_costs_cents"], "EXIT",
         memo="Sale proceeds net of selling costs", occurred_at=now)
    if event["exit_mode"] == "ASSET_SALE":
        book(trust, "LOAN_PAYOFF", "OPERATING", -loan["principal_cents"], "EXIT",
             memo="Loan payoff", occurred_at=now)
    loan["status"] = "PAID_OFF"
    db.touch(loan)
    prop["status"] = "DISPOSED"
    db.touch(prop)

    # step 2 — sweep the reserve into operating as a two-legged pair
    reserve_balance = bucket_balance(trust["id"], "RESERVE")
    book(trust, "REVERSAL", "RESERVE", -reserve_balance, "EXIT",
         memo="Reserve sweep on exit", occurred_at=now)
    book(trust, "REVERSAL", "OPERATING", reserve_balance, "EXIT",
         memo="Reserve sweep on exit", occurred_at=now)

    # step 3 — the liquidating amount is the operating balance after steps 1-2
    liquidating_amount = bucket_balance(trust["id"], "OPERATING")

    # step 4 — the liquidating distribution
    db.new_row(db.distributions, {
        "trust_id": trust["id"],
        "kind": "LIQUIDATING",
        "period_start": now,
        "period_end": now + timedelta(milliseconds=1),
        "provisional_amount_cents": liquidating_amount,
        "final_amount_cents": None,
        "reconciliation_delta_cents": None,
        "declared_at": now,
        "paid_at": None,
        "status": "DECLARED",
    })

    # step 5 — one successor exchange file per closed subscription
    units_issued = trust["units_issued"]
    for sub in closed_subscriptions_of_trust(trust):
        units = sub["units_requested"]
        identification_deadline, exchange_deadline = calc.exchange_deadlines(now)
        db.new_row(db.exchange_files, {
            "investor_id": sub["investor_id"],
            "qi_reference": "SUCCESSOR-" + str(sub["closing_sequence_no"]),
            "relinquished_closed_on": now,
            "relinquished_sale_price_cents": round_half_up(
                F(event["gross_price_cents"]) * units / units_issued) if units_issued else 0,
            "net_proceeds_cents": round_half_up(
                F(liquidating_amount) * units / units_issued) if units_issued else 0,
            "debt_retired_cents": round_half_up(
                F(loan["principal_cents"]) * units / units_issued) if units_issued else 0,
            "identification_rule": "THREE_PROPERTY",
            "boot_tolerance_cents": 0,
            "source_exit_event_id": event["id"],
            "identification_deadline": identification_deadline,
            "exchange_deadline": exchange_deadline,
            "status": "OPEN",
        })

    # step 6 — the event and the trust reach their terminal states
    event["net_proceeds_cents"] = net_proceeds
    event["net_proceeds_per_unit_cents"] = calc.per_unit(net_proceeds, units_issued)
    event["closed_at"] = now
    event["status"] = "CLOSED"
    db.touch(event)

    trust["status"] = "TERMINATED" if event["exit_mode"] == "ASSET_SALE" else "CONVERTED_LLC"
    recompute_trust(trust, force=True)
    return liquidating_amount

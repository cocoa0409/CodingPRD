"""Settlement batches, the payout lifecycle and the reserve ledger."""
from flask import Blueprint

from db import by_seq, db, new_row, serialize, serialize_all
from errors import fail
from middleware import (
    authenticate,
    body,
    filter_enum,
    find_batch,
    find_merchant,
    find_reserve_account,
    own_merchant,
    pagination,
    req_date,
    req_enum,
    req_id,
    req_int,
    touch,
)
from response import object_response, paged_response
from services.calc import (
    NORMAL_PAYOUT_LAG_DAYS,
    RELEASE_COOLING_DAYS,
    VOLUME_LIMIT_TOLERANCE_BPS,
    settlement_waterfall,
)
from services.ledger import append_entry
from services.metrics import (
    activity_between,
    merchant_batches,
    mirror_reserve_balance,
    prior_scheduled_release,
    recompute_pending_payout,
    releasable_balance,
    reserve_account_of,
    trailing_volume_at,
)
from util import date_plus

bp = Blueprint("settlement", __name__)

PAYOUT_STATES = ("SCHEDULED", "DELAYED", "HELD", "PAID", "REVERSED")
REVERSAL_REASONS = ("RISK_HOLD", "FUNDING_ERROR", "TERMINATION", "APPEAL_REMEDY")
ENTRY_TYPES = ("HOLD", "RELEASE", "OFFSET_LOSS")
REASON_CODES = ("SETTLEMENT_HOLD", "SCHEDULED_RELEASE", "BATCH_REVERSAL_RELEASE",
                "LOSS_OFFSET", "REINSTATEMENT_RELEASE")
RESERVE_STATES = ("ACCRUING", "CAP_REACHED", "RELEASING", "CLOSED")
RESERVE_TYPES = ("ROLLING", "CAPPED")


def _account_not_closed(account):
    if account is not None and account["state"] == "CLOSED":
        fail("ERR_RESERVE_ACCOUNT_CLOSED", "The merchant's reserve account is CLOSED.")


# --------------------------------------------------------------------------
# settlement
# --------------------------------------------------------------------------
@bp.post("/settlement-batches")
def create_batch():
    user_id, _ = authenticate(["PortfolioController"])
    payload = body()
    merchant_id = req_id(payload, "merchant_id")
    period_start_date = req_date(payload, "period_start_date")
    period_end_date = req_date(payload, "period_end_date")
    gross_volume_cents = req_int(payload, "gross_volume_cents", lo=1)

    merchant = find_merchant(merchant_id)
    if merchant["account_state"] == "TERMINATED":
        fail("ERR_MERCHANT_ACCOUNT_STATE_INVALID",
             "The merchant account_state is TERMINATED.")
    account = reserve_account_of(merchant_id)
    _account_not_closed(account)

    clock_date = db.clock_date()
    if period_start_date > period_end_date or period_end_date > clock_date:
        fail("ERR_SETTLEMENT_PERIOD_INVALID",
             "The settlement period is malformed or ends in the future.")

    for other in merchant_batches(merchant_id):
        if other["payout_state"] == "REVERSED":
            continue
        if (period_start_date <= other["period_end_date"]
                and other["period_start_date"] <= period_end_date):
            fail("ERR_SETTLEMENT_PERIOD_OVERLAP",
                 "The period intersects settlement batch '%s'." % other["id"])

    lines = sorted(
        activity_between(merchant_id, period_start_date, period_end_date),
        key=lambda r: (r["business_date"], r["_seq"]),
    )
    if not lines:
        fail("ERR_EMPTY_SETTLEMENT_PERIOD",
             "No merchant day activity falls inside the settlement period.")

    period_volume = sum(line["volume_cents"] for line in lines)
    if gross_volume_cents != period_volume:
        fail("ERR_GROSS_VOLUME_MISMATCH",
             "gross_volume_cents %s does not equal the period volume %s."
             % (gross_volume_cents, period_volume))

    trailing = trailing_volume_at(merchant_id, period_end_date)
    if trailing * 10000 > merchant["monthly_volume_limit_cents"] * VOLUME_LIMIT_TOLERANCE_BPS:
        fail("ERR_MONTHLY_VOLUME_LIMIT_EXCEEDED",
             "Trailing 30-day volume exceeds 125 percent of the contracted monthly limit.")

    computed = settlement_waterfall(lines, gross_volume_cents, account)

    funding_state = merchant["funding_state"]
    if funding_state == "NORMAL":
        payout_state = "SCHEDULED"
        scheduled_payout_date = date_plus(period_end_date, NORMAL_PAYOUT_LAG_DAYS)
    elif funding_state == "DELAYED":
        payout_state = "DELAYED"
        scheduled_payout_date = date_plus(period_end_date, merchant["delayed_payout_days"])
    else:
        payout_state = "HELD"
        scheduled_payout_date = None

    batch = new_row()
    batch.update({
        "merchant_id": merchant_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "gross_volume_cents": gross_volume_cents,
        "day_line_count": computed["day_line_count"],
        "reserve_hold_cents": computed["reserve_hold_cents"],
        "loss_offset_from_settlement_cents": computed["loss_offset_from_settlement_cents"],
        "reserve_offset_cents": computed["reserve_offset_cents"],
        "uncovered_loss_cents": computed["uncovered_loss_cents"],
        "net_payout_cents": computed["net_payout_cents"],
        "payout_state": payout_state,
        "scheduled_payout_date": scheduled_payout_date,
        "paid_at": None,
        "reversed_at": None,
        "reversal_reason_code": None,
    })
    db.batches[batch["id"]] = batch

    if account is not None:
        if batch["reserve_hold_cents"] > 0:
            append_entry(
                account,
                entry_type="HOLD",
                reason_code="SETTLEMENT_HOLD",
                amount_cents=batch["reserve_hold_cents"],
                effective_date=period_end_date,
                settlement_batch_id=batch["id"],
                recorded_by_user_id=user_id,
            )
        if batch["reserve_offset_cents"] > 0:
            append_entry(
                account,
                entry_type="OFFSET_LOSS",
                reason_code="LOSS_OFFSET",
                amount_cents=batch["reserve_offset_cents"],
                effective_date=clock_date,
                settlement_batch_id=batch["id"],
                recorded_by_user_id=user_id,
            )
        mirror_reserve_balance(merchant, account)
    recompute_pending_payout(merchant)

    return object_response(serialize(batch), 201)


@bp.get("/settlement-batches/<batch_id>")
def get_batch(batch_id):
    authenticate(["MerchantUser", "RiskAnalyst", "PortfolioController"])
    batch = find_batch(batch_id)
    own_merchant(batch["merchant_id"])
    return object_response(serialize(batch))


@bp.get("/merchants/<merchant_id>/settlement-batches")
def list_batches(merchant_id):
    authenticate(["MerchantUser", "RiskAnalyst", "PortfolioController"])
    payout_state = filter_enum("payout_state", PAYOUT_STATES)
    limit, offset = pagination()
    find_merchant(merchant_id)
    own_merchant(merchant_id)
    rows = sorted(merchant_batches(merchant_id),
                  key=lambda b: (b["period_start_date"], b["_seq"]))
    if payout_state:
        rows = [r for r in rows if r["payout_state"] == payout_state]
    return paged_response(serialize_all(rows), limit, offset)


@bp.post("/settlement-batches/<batch_id>/pay")
def pay_batch(batch_id):
    authenticate(["PortfolioController"])
    batch = find_batch(batch_id)
    if batch["payout_state"] not in ("SCHEDULED", "DELAYED"):
        fail("ERR_BATCH_STATE_INVALID",
             "payout_state '%s' cannot be paid." % batch["payout_state"])
    clock_date = db.clock_date()
    if batch["scheduled_payout_date"] is None or clock_date < batch["scheduled_payout_date"]:
        fail("ERR_PAYOUT_NOT_DUE",
             "The payout is not due until '%s'." % batch["scheduled_payout_date"])

    batch["payout_state"] = "PAID"
    batch["paid_at"] = db.clock_iso()
    touch(batch)
    merchant = db.merchants.get(batch["merchant_id"])
    if merchant is not None:
        recompute_pending_payout(merchant)
    return object_response(serialize(batch))


@bp.post("/settlement-batches/<batch_id>/reverse")
def reverse_batch(batch_id):
    user_id, _ = authenticate(["PortfolioController"])
    payload = body()
    reversal_reason_code = req_enum(payload, "reversal_reason_code", REVERSAL_REASONS)

    batch = find_batch(batch_id)
    merchant = db.merchants.get(batch["merchant_id"])
    account = reserve_account_of(batch["merchant_id"]) if merchant is not None else None
    _account_not_closed(account)
    if batch["payout_state"] not in ("SCHEDULED", "DELAYED", "HELD"):
        fail("ERR_BATCH_STATE_INVALID",
             "payout_state '%s' cannot be reversed." % batch["payout_state"])

    clock_date = db.clock_date()
    batch["payout_state"] = "REVERSED"
    batch["reversed_at"] = db.clock_iso()
    batch["reversal_reason_code"] = reversal_reason_code
    touch(batch)

    if account is not None:
        if batch["reserve_hold_cents"] > 0:
            append_entry(
                account,
                entry_type="RELEASE",
                reason_code="BATCH_REVERSAL_RELEASE",
                amount_cents=batch["reserve_hold_cents"],
                effective_date=clock_date,
                settlement_batch_id=batch["id"],
                recorded_by_user_id=user_id,
            )
        if batch["reserve_offset_cents"] > 0:
            append_entry(
                account,
                entry_type="HOLD",
                reason_code="SETTLEMENT_HOLD",
                amount_cents=batch["reserve_offset_cents"],
                effective_date=clock_date,
                settlement_batch_id=batch["id"],
                recorded_by_user_id=user_id,
            )
    if merchant is not None:
        if account is not None:
            mirror_reserve_balance(merchant, account)
        recompute_pending_payout(merchant)
        merchant["lifetime_reversed_cents"] += (
            batch["uncovered_loss_cents"]
            + batch["reserve_offset_cents"]
            + batch["loss_offset_from_settlement_cents"]
        )
        touch(merchant)

    return object_response(serialize(batch))


@bp.get("/settlement-batches/<batch_id>/ledger-entries")
def batch_ledger_entries(batch_id):
    authenticate(["RiskAnalyst", "PortfolioController"])
    entry_type = filter_enum("entry_type", ENTRY_TYPES)
    limit, offset = pagination()
    find_batch(batch_id)
    rows = by_seq([e for e in db.ledger_entries.values()
                   if e["settlement_batch_id"] == batch_id])
    if entry_type:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    return paged_response(serialize_all(rows), limit, offset)


# --------------------------------------------------------------------------
# reserve accounts
# --------------------------------------------------------------------------
@bp.get("/reserve-accounts/<account_id>")
def get_reserve_account(account_id):
    authenticate(["MerchantUser", "RiskAnalyst", "PortfolioController"])
    account = find_reserve_account(account_id)
    own_merchant(account["merchant_id"])
    data = serialize(account)
    data["releasable_balance_cents"] = releasable_balance(account, db.clock_date())
    return object_response(data)


@bp.get("/reserve-accounts")
def list_reserve_accounts():
    authenticate(["RiskAnalyst", "PortfolioController"])
    state = filter_enum("state", RESERVE_STATES)
    reserve_type = filter_enum("reserve_type", RESERVE_TYPES)
    limit, offset = pagination()
    rows = by_seq(list(db.reserve_accounts.values()))
    if state:
        rows = [r for r in rows if r["state"] == state]
    if reserve_type:
        rows = [r for r in rows if r["reserve_type"] == reserve_type]
    return paged_response(serialize_all(rows), limit, offset)


@bp.get("/reserve-accounts/<account_id>/ledger-entries")
def account_ledger_entries(account_id):
    authenticate(["MerchantUser", "RiskAnalyst", "PortfolioController"])
    entry_type = filter_enum("entry_type", ENTRY_TYPES)
    reason_code = filter_enum("reason_code", REASON_CODES)
    limit, offset = pagination()
    account = find_reserve_account(account_id)
    own_merchant(account["merchant_id"])
    rows = by_seq([e for e in db.ledger_entries.values()
                   if e["reserve_account_id"] == account_id])
    if entry_type:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    if reason_code:
        rows = [r for r in rows if r["reason_code"] == reason_code]
    return paged_response(serialize_all(rows), limit, offset)


@bp.post("/reserve-accounts/<account_id>/release-requests")
def create_release_request(account_id):
    user_id, _ = authenticate(["PortfolioController"])
    payload = body()
    amount_cents = req_int(payload, "amount_cents", lo=1)
    tranche_start_date = req_date(payload, "tranche_start_date")
    tranche_end_date = req_date(payload, "tranche_end_date")
    expected_version = req_int(payload, "expected_reserve_account_version")

    account = find_reserve_account(account_id)
    if expected_version != account["version"]:
        fail("ERR_STALE_RESERVE_ACCOUNT_VERSION",
             "expected_reserve_account_version %s does not match the current version %s."
             % (expected_version, account["version"]))

    merchant = db.merchants.get(account["merchant_id"])
    if merchant is None or merchant["account_state"] != "ACTIVE":
        fail("ERR_MERCHANT_ACCOUNT_STATE_INVALID",
             "The merchant account_state must be ACTIVE to release reserve.")
    if merchant["funding_state"] != "NORMAL":
        fail("ERR_FUNDING_STATE_INVALID",
             "The merchant funding_state must be NORMAL to release reserve.")
    if account["state"] == "CLOSED":
        fail("ERR_RESERVE_ACCOUNT_CLOSED", "The reserve account is CLOSED.")

    clock_date = db.clock_date()
    prior = prior_scheduled_release(account_id)
    cooling_ok = prior is None or (
        tranche_start_date >= date_plus(prior["tranche_end_date"], RELEASE_COOLING_DAYS + 1)
    )
    if (not cooling_ok
            or tranche_start_date > tranche_end_date
            or tranche_end_date > clock_date):
        fail("ERR_RELEASE_TRANCHE_COOLING_VIOLATION",
             "The requested tranche window violates the tranche geometry rules.")

    releasable = releasable_balance(account, clock_date)
    if releasable <= 0:
        fail("ERR_NO_RELEASABLE_BALANCE", "No matured reserve is available for release.")
    if amount_cents > releasable:
        fail("ERR_RELEASE_AMOUNT_EXCEEDS_RELEASABLE",
             "amount_cents %s exceeds the releasable balance %s." % (amount_cents, releasable))

    entry = append_entry(
        account,
        entry_type="RELEASE",
        reason_code="SCHEDULED_RELEASE",
        amount_cents=amount_cents,
        effective_date=clock_date,
        settlement_batch_id=None,
        tranche_start_date=tranche_start_date,
        tranche_end_date=tranche_end_date,
        recorded_by_user_id=user_id,
    )
    account["last_release_tranche_end_date"] = tranche_end_date
    touch(account)
    mirror_reserve_balance(merchant, account)
    return object_response(serialize(entry), 201)

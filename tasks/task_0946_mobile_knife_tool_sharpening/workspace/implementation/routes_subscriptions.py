"""The standing-route subscription and its allowance ledger."""

import datetime

from flask import Blueprint

import calcs
import clock as clockmod
import envelope
import ladder
import serializers as ser
import services
from constants import (
    ALLOWANCE_KINDS,
    CADENCES,
    SKIP_WINDOW_HOURS,
    SUBSCRIPTION_STATUSES,
)
from errors import ApiError
from store import db, stamp_new, touch

bp = Blueprint("subscriptions", __name__)

SUBSCRIPTION_SPEC = ladder.Spec(
    required=[
        ("account_id", "string"),
        ("plan_tier_id", "string"),
        ("cadence", "string"),
        ("anchor_date", "string"),
    ],
    enums={"cadence": CADENCES},
    dates=["anchor_date"],
)

CADENCE_SPEC = ladder.Spec(
    required=[("cadence", "string"), ("expected_subscription_version", "integer")],
    enums={"cadence": CADENCES},
)


def _refresh_derived(subscription):
    subscription["cycle_end_date"] = calcs.cycle_end_date(subscription["cycle_start_date"])


def _skip_window_open(subscription):
    """The clock is at least 48 hours before midnight UTC of next_service_date."""
    target = subscription["next_service_date"]
    if target is None:
        return False
    midnight = datetime.datetime(
        target.year, target.month, target.day, tzinfo=clockmod.UTC
    )
    return clockmod.now() <= midnight - datetime.timedelta(hours=SKIP_WINDOW_HOURS)


def _proration_line(subscription, amount_cents, description):
    account = db.accounts.get(subscription["account_id"])
    if account is None:
        return
    invoice = services.draft_invoice_for(account)
    services.append_line(invoice, "PRORATION_CREDIT", description, amount_cents)
    services.recompute_invoice(invoice)
    touch(invoice)


# ---------------------------------------------------------------------------
# POST /sharpening/subscriptions
# ---------------------------------------------------------------------------
@bp.route("/sharpening/subscriptions", methods=["POST"])
def create_subscription():
    ctx = ladder.begin("AccountOwner")
    SUBSCRIPTION_SPEC.validate(ctx.body)
    services.own_account(ctx, ctx.body["account_id"])
    # Rung 9 sits before body-reference existence.
    services.account_active(db.accounts.get(ctx.body["account_id"]))
    account = ladder.must_exist(db.accounts, ctx.body["account_id"], "Account")
    tier = ladder.must_exist(db.plan_tiers, ctx.body["plan_tier_id"], "PlanTier")
    cadence = ctx.body["cadence"]
    if cadence not in tier["allowed_cadences"]:
        raise ApiError(
            "ERR_INVALID_STATE", "The cadence is not allowed on this plan tier."
        )
    # Rung 44.
    if services.account_subscription(account["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_ACTIVE_SUBSCRIPTION")

    anchor = clockmod.parse_date(ctx.body["anchor_date"])
    included = calcs.included_items_this_cycle(tier["included_items_per_cycle"], cadence)
    row = stamp_new(
        {
            "account_id": account["id"],
            "plan_tier_id": tier["id"],
            "cadence": cadence,
            "anchor_date": anchor,
            "status": "ACTIVE",
            "effective_monthly_fee_cents": calcs.effective_monthly_fee(
                tier["monthly_fee_cents"], cadence
            ),
            "included_items_this_cycle": included,
            "allowance_remaining": included,
            "cycle_index": 1,
            "cycle_start_date": anchor,
            "cycle_end_date": calcs.cycle_end_date(anchor),
            "next_service_date": calcs.next_service_date(
                anchor, cadence, clockmod.today(), "ANCHORED"
            ),
            "skip_count_this_cycle": 0,
            "paused_at": None,
        }
    )
    db.subscriptions[row["id"]] = row
    services.append_allowance_entry(row, "GRANTED", included, "CYCLE_OPEN")
    return envelope.created(ser.subscription(row))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.route("/sharpening/subscriptions/<id>", methods=["GET"])
def get_subscription(id):
    ctx = ladder.begin("PlatformAdmin", "AccountOwner", "BillingClerk")
    row = ladder.must_exist(db.subscriptions, id, "Subscription")
    services.own_account(ctx, row["account_id"])
    return envelope.ok(ser.subscription(row))


@bp.route("/sharpening/subscriptions", methods=["GET"])
def list_subscriptions():
    ctx = ladder.begin("PlatformAdmin", "AccountOwner", "BillingClerk")
    ladder.check_query_enums(ctx.query, {"status": SUBSCRIPTION_STATUSES})
    limit, offset = ladder.pagination(ctx.query)
    rows = list(db.subscriptions.values())
    for field in ("account_id", "plan_tier_id", "status"):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.subscription(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------
def _load_for_action(ctx, id, admin=False):
    row = ladder.must_exist(db.subscriptions, id, "Subscription")
    if not admin:
        services.own_account(ctx, row["account_id"])
    services.account_active(db.accounts.get(row["account_id"]))
    return row


@bp.route("/sharpening/subscriptions/<id>/pause", methods=["POST"])
def pause_subscription(id):
    ctx = ladder.begin("AccountOwner")
    row = _load_for_action(ctx, id)
    if row["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The subscription is not ACTIVE.")

    row["paused_at"] = clockmod.now()
    services.append_allowance_entry(row, "EXPIRED", row["allowance_remaining"], "PAUSE")
    row["allowance_remaining"] = 0
    row["next_service_date"] = None
    row["status"] = "PAUSED"
    amount = calcs.pause_proration(
        row["effective_monthly_fee_cents"],
        calcs.unused_days(clockmod.today(), row["cycle_end_date"]),
    )
    _proration_line(row, amount, "Subscription pause proration credit")
    touch(row)
    return envelope.ok(ser.subscription(row))


@bp.route("/sharpening/subscriptions/<id>/resume", methods=["POST"])
def resume_subscription(id):
    ctx = ladder.begin("AccountOwner")
    row = _load_for_action(ctx, id)
    if row["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if row["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", "The subscription is not PAUSED.")

    today = clockmod.today()
    row["anchor_date"] = today
    row["cycle_index"] += 1
    row["cycle_start_date"] = today
    _refresh_derived(row)
    services.append_allowance_entry(
        row, "GRANTED", row["included_items_this_cycle"], "RESUME"
    )
    row["allowance_remaining"] = row["included_items_this_cycle"]
    row["skip_count_this_cycle"] = 0
    row["next_service_date"] = calcs.next_service_date(
        today, row["cadence"], today, "RE_ANCHORED"
    )
    row["paused_at"] = None
    row["status"] = "ACTIVE"
    touch(row)
    return envelope.ok(ser.subscription(row))


@bp.route("/sharpening/subscriptions/<id>/cadence", methods=["POST"])
def change_cadence(id):
    ctx = ladder.begin("AccountOwner")
    row = ladder.must_exist(db.subscriptions, id, "Subscription")
    CADENCE_SPEC.validate(ctx.body)
    services.own_account(ctx, row["account_id"])
    services.account_active(db.accounts.get(row["account_id"]))
    # Rung 12 sits before every state precondition.
    services.occ(ctx.body, "expected_subscription_version", row)
    if row["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The subscription is not ACTIVE.")
    tier = db.plan_tiers.get(row["plan_tier_id"])
    cadence = ctx.body["cadence"]
    if cadence == row["cadence"]:
        raise ApiError("ERR_INVALID_STATE", "The cadence is unchanged.")
    if tier is None or cadence not in tier["allowed_cadences"]:
        raise ApiError("ERR_INVALID_STATE", "The cadence is not allowed on this tier.")
    # Rung 37.
    if not _skip_window_open(row):
        raise ApiError("ERR_CADENCE_CHANGE_TOO_LATE")

    old_fee = row["effective_monthly_fee_cents"]
    old_included = row["included_items_this_cycle"]
    row["cadence"] = cadence
    row["effective_monthly_fee_cents"] = calcs.effective_monthly_fee(
        tier["monthly_fee_cents"], cadence
    )
    row["included_items_this_cycle"] = calcs.included_items_this_cycle(
        tier["included_items_per_cycle"], cadence
    )
    new_included = row["included_items_this_cycle"]
    if new_included > old_included:
        services.append_allowance_entry(
            row, "GRANTED", new_included - old_included, "CADENCE_CHANGE"
        )
    elif new_included < old_included:
        services.append_allowance_entry(
            row, "EXPIRED", old_included - new_included, "CADENCE_CHANGE"
        )
    row["allowance_remaining"] = max(
        0, row["allowance_remaining"] + new_included - old_included
    )
    today = clockmod.today()
    unused = calcs.unused_days(today, row["cycle_end_date"])
    row["anchor_date"] = today
    row["next_service_date"] = calcs.next_service_date(
        today, cadence, today, "RE_ANCHORED"
    )
    amount = calcs.cadence_change_proration(
        row["effective_monthly_fee_cents"], old_fee, unused
    )
    _proration_line(row, amount, "Subscription cadence change proration")
    touch(row)
    return envelope.ok(ser.subscription(row))


@bp.route("/sharpening/subscriptions/<id>/skip", methods=["POST"])
def skip_subscription(id):
    ctx = ladder.begin("AccountOwner")
    row = _load_for_action(ctx, id)
    if row["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if row["status"] != "ACTIVE" or row["next_service_date"] is None:
        raise ApiError("ERR_INVALID_STATE", "The subscription has no next visit.")
    # Rung 36.
    if not _skip_window_open(row):
        raise ApiError("ERR_SKIP_WINDOW_CLOSED")

    skipped_date = row["next_service_date"]
    row["next_service_date"] = skipped_date + datetime.timedelta(
        days=calcs.CADENCE_INTERVAL_DAYS[row["cadence"]]
    )
    row["skip_count_this_cycle"] += 1
    for stop in list(db.route_stops.values()):
        if stop["status"] != "SCHEDULED" or stop["account_id"] != row["account_id"]:
            continue
        run = db.route_runs.get(stop["route_run_id"])
        if run is None or run["run_date"] != skipped_date:
            continue
        stop["status"] = "SKIPPED"
        touch(stop)
        request_row = db.service_requests.get(stop["service_request_id"])
        if request_row is not None and request_row["status"] == "SCHEDULED":
            request_row["status"] = "SUBMITTED"
            touch(request_row)
    touch(row)
    return envelope.ok(ser.subscription(row))


@bp.route("/sharpening/subscriptions/<id>/cancel", methods=["POST"])
def cancel_subscription(id):
    ctx = ladder.begin("AccountOwner")
    row = _load_for_action(ctx, id)
    if row["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if row["status"] == "ACTIVE":
        services.append_allowance_entry(
            row, "EXPIRED", row["allowance_remaining"], "CANCEL"
        )
        row["allowance_remaining"] = 0
    row["next_service_date"] = None
    row["status"] = "CANCELLED"
    touch(row)
    return envelope.ok(ser.subscription(row))


@bp.route("/sharpening/subscriptions/<id>/advance-cycle", methods=["POST"])
def advance_cycle(id):
    ctx = ladder.begin("PlatformAdmin")
    row = _load_for_action(ctx, id, admin=True)
    if row["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The subscription is not ACTIVE.")
    if clockmod.today() < row["cycle_end_date"]:
        raise ApiError("ERR_INVALID_STATE", "The cycle has not ended yet.")

    services.append_allowance_entry(
        row, "EXPIRED", row["allowance_remaining"], "CYCLE_END"
    )
    previous_end = row["cycle_end_date"]
    row["cycle_index"] += 1
    row["cycle_start_date"] = previous_end
    _refresh_derived(row)
    row["next_service_date"] = calcs.next_service_date(
        row["anchor_date"], row["cadence"], clockmod.today(), "ANCHORED"
    )
    services.append_allowance_entry(
        row, "GRANTED", row["included_items_this_cycle"], "CYCLE_OPEN"
    )
    row["allowance_remaining"] = row["included_items_this_cycle"]
    row["skip_count_this_cycle"] = 0
    touch(row)
    return envelope.ok(ser.subscription(row))


# ---------------------------------------------------------------------------
# Allowance ledger reads
# ---------------------------------------------------------------------------
@bp.route("/sharpening/allowance-entries/<id>", methods=["GET"])
def get_allowance_entry(id):
    ladder.begin("PlatformAdmin", "BillingClerk")
    row = ladder.must_exist(db.allowance_entries, id, "AllowanceLedgerEntry")
    return envelope.ok(ser.allowance_entry(row))


@bp.route("/sharpening/allowance-entries", methods=["GET"])
def list_allowance_entries():
    ctx = ladder.begin("PlatformAdmin", "BillingClerk", "AccountOwner")
    ladder.check_query_enums(ctx.query, {"kind": ALLOWANCE_KINDS})
    numbers = ladder.check_query_integers(ctx.query, ["cycle_index"])
    limit, offset = ladder.pagination(ctx.query)
    rows = list(db.allowance_entries.values())
    for field in ("subscription_id", "request_item_id", "kind"):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    if numbers["cycle_index"] is not None:
        rows = [r for r in rows if r["cycle_index"] == numbers["cycle_index"]]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.allowance_entry(r) for r in page], limit, offset, total)

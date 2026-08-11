"""Subscriptions: cadence, activation, pause, resume, cancel, generation."""

from flask import Blueprint

import calc
import constants as C
import serialize
import services
import shapes
import store
from auth import (api, get_subscription, get_child, lookup, get_pause,
                  require_account_owner)
from envelope import ok, created, paginate
from errors import ApiError
from routes.children import body_fk
from store import db, now, touch

bp = Blueprint("subs", __name__)

READ_ROLES = ["AccountHolder", "SupportAgent", "OpsAdmin"]


def _derive_cadence(sub):
    sub["cadence_interval_days"] = calc.cadence_interval_days(
        sub["pack_count"], sub["consumption_rate_per_day"],
        sub["cadence_override_days"])
    return sub


@api(bp, "POST", "/subscriptions", ["AccountHolder", "OpsAdmin"])
def create_subscription():
    data = shapes.body()
    body_fk(data, "account_id", db.accounts, "Account")
    body_fk(data, "plan_id", db.plans, "Plan")
    body_fk(data, "child_id", db.children, "Child")
    parsed = shapes.validate(data, [
        shapes.field("account_id", required=True, kind="string"),
        shapes.field("plan_id", required=True, kind="string"),
        shapes.field("child_id", required=True, kind="string"),
        shapes.field("consumption_rate_per_day", required=True, kind="number",
                     lo=C.CONSUMPTION_RATE_MIN_PER_DAY,
                     hi=C.CONSUMPTION_RATE_MAX_PER_DAY),
        shapes.field("pack_count", kind="int", lo=C.PACK_COUNT_MIN,
                     hi=C.PACK_COUNT_MAX, default=None),
    ])
    require_account_owner(parsed["account_id"])

    account = db.accounts[parsed["account_id"]]
    plan = db.plans[parsed["plan_id"]]
    child = db.children[parsed["child_id"]]
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    if child["archived"]:
        raise ApiError("ERR_CHILD_ARCHIVED")
    if child["account_id"] != parsed["account_id"]:
        raise ApiError("ERR_CHILD_ACCOUNT_MISMATCH")

    pack_count = parsed["pack_count"]
    if pack_count is None:
        pack_count = int(plan["default_pack_count"])

    row = store.base_row(full=True)
    row.update({
        "account_id": parsed["account_id"],
        "plan_id": parsed["plan_id"],
        "child_id": parsed["child_id"],
        "pack_count": pack_count,
        "consumption_rate_per_day": parsed["consumption_rate_per_day"],
        "cadence_override_days": None,
        "cadence_interval_days": 0,
        "anchor_date": None,
        "lifecycle_state": "DRAFT",
        "billing_state": "CURRENT",
        "free_shipping_eligible": False,
        "cumulative_pause_days": 0,
        "auto_resize_count_in_period": 0,
        "next_charge_cents": 0,
        "cancelled_at": None,
    })
    _derive_cadence(row)
    db.subscriptions[row["id"]] = row
    return created(serialize.subscription(row))


@api(bp, "GET", "/subscriptions/<id>", READ_ROLES)
def read_subscription(id):
    return ok(serialize.subscription(get_subscription(id)))


@api(bp, "GET", "/subscriptions", READ_ROLES)
def list_subscriptions():
    rows = [r for r in db.subscriptions.values()
            if shapes.match(r, "account_id", shapes.qs("account_id"))
            and shapes.match(r, "plan_id", shapes.qs("plan_id"))
            and shapes.match(r, "child_id", shapes.qs("child_id"))
            and shapes.match(r, "lifecycle_state", shapes.qs("lifecycle_state"))
            and shapes.match(r, "billing_state", shapes.qs("billing_state"))]
    return paginate(rows, serialize.subscription)


@api(bp, "PATCH", "/subscriptions/<id>", ["AccountHolder"])
def update_subscription(id):
    sub = get_subscription(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("pack_count", kind="int", lo=C.PACK_COUNT_MIN,
                     hi=C.PACK_COUNT_MAX),
        shapes.field("consumption_rate_per_day", kind="number",
                     lo=C.CONSUMPTION_RATE_MIN_PER_DAY,
                     hi=C.CONSUMPTION_RATE_MAX_PER_DAY),
    ])
    require_account_owner(sub["account_id"])
    if sub["lifecycle_state"] == "CANCELLED":
        raise ApiError("ERR_SUBSCRIPTION_STATE_INVALID")
    if shapes.supplied(parsed, "pack_count"):
        sub["pack_count"] = parsed["pack_count"]
    if shapes.supplied(parsed, "consumption_rate_per_day"):
        sub["consumption_rate_per_day"] = parsed["consumption_rate_per_day"]
    # While an override is in force, derivation is SUPPRESSED entirely.
    _derive_cadence(sub)
    touch(sub)
    return ok(serialize.subscription(sub))


@api(bp, "POST", "/subscriptions/<id>/activate", ["AccountHolder", "OpsAdmin"])
def activate_subscription(id):
    sub = get_subscription(id)
    require_account_owner(sub["account_id"])
    account = db.accounts.get(sub["account_id"])
    child = db.children.get(sub["child_id"])
    if account is None or account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    if sub["lifecycle_state"] != "DRAFT":
        raise ApiError("ERR_SUBSCRIPTION_STATE_INVALID")
    if child is None or child["archived"]:
        raise ApiError("ERR_CHILD_ARCHIVED")
    for other in services.subscriptions_of_account(sub["account_id"]):
        if other["id"] == sub["id"]:
            continue
        if other["child_id"] != sub["child_id"]:
            continue
        if other["lifecycle_state"] in ("ACTIVE", "PAUSED"):
            raise ApiError("ERR_DUPLICATE_ACTIVE_SUBSCRIPTION")

    sub["lifecycle_state"] = "ACTIVE"
    sub["anchor_date"] = store.plus_days(now(), C.CYCLE_LEAD_DAYS)
    _derive_cadence(sub)
    wallet = services.wallet_of_account(sub["account_id"])
    tier = wallet["tier"] if wallet else "BRONZE"
    sub["free_shipping_eligible"] = tier in ("SILVER", "GOLD")
    touch(sub)
    return ok(serialize.subscription(sub))


@api(bp, "POST", "/subscriptions/<id>/cadence-override", ["AccountHolder"])
def set_cadence_override(id):
    sub = get_subscription(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("cadence_override_days", required=True, kind="int",
                     lo=C.CADENCE_MIN_INTERVAL_DAYS,
                     hi=C.CADENCE_MAX_INTERVAL_DAYS),
    ])
    require_account_owner(sub["account_id"])
    if sub["lifecycle_state"] == "CANCELLED":
        raise ApiError("ERR_SUBSCRIPTION_STATE_INVALID")
    sub["cadence_override_days"] = parsed["cadence_override_days"]
    sub["cadence_interval_days"] = parsed["cadence_override_days"]
    touch(sub)
    return ok(serialize.subscription(sub))


@api(bp, "DELETE", "/subscriptions/<id>/cadence-override", ["AccountHolder"])
def clear_cadence_override(id):
    sub = get_subscription(id)
    require_account_owner(sub["account_id"])
    if sub["lifecycle_state"] == "CANCELLED":
        raise ApiError("ERR_SUBSCRIPTION_STATE_INVALID")
    sub["cadence_override_days"] = None
    _derive_cadence(sub)
    touch(sub)
    return ok(serialize.subscription(sub))


@api(bp, "POST", "/subscriptions/<id>/resizes", ["AccountHolder"])
def request_resize(id):
    sub = get_subscription(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("target_stage", required=True, kind="enum",
                     members=C.STAGE_ORDER),
        shapes.field("expected_subscription_version", required=True, kind="int"),
    ])
    require_account_owner(sub["account_id"])
    # G6 — optimistic concurrency on the parent's version.
    if parsed["expected_subscription_version"] != int(sub["version"]):
        raise ApiError("ERR_STALE_SUBSCRIPTION_VERSION")
    if sub["lifecycle_state"] == "CANCELLED":
        raise ApiError("ERR_SUBSCRIPTION_STATE_INVALID")

    child = db.children.get(sub["child_id"])
    if child is None:
        raise ApiError("ERR_CHILD_NOT_FOUND")
    from_stage = child["stage"]
    target = parsed["target_stage"]
    if calc.stage_distance(from_stage, target) != C.MAX_STAGE_STEP_PER_RESIZE:
        raise ApiError("ERR_NON_ADJACENT_STAGE")
    if child["stage_pinned"]:
        raise ApiError("ERR_STAGE_PINNED")

    status, target_id, current = services.resize_target_cycle(sub)
    child["stage"] = target
    touch(child)
    event = services.write_resize_event(
        sub, child, "MANUAL", from_stage, target, status, target_id, None)
    touch(sub)
    if status == "APPLIED_CURRENT" and current is not None:
        services.reallocate_cycle(current)
    return created(serialize.resize_event(event))


@api(bp, "POST", "/subscriptions/<id>/pauses", ["AccountHolder"])
def create_pause(id):
    sub = get_subscription(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("start_date", required=True, kind="date"),
        shapes.field("end_date", required=True, kind="date"),
    ])
    require_account_owner(sub["account_id"])
    if sub["lifecycle_state"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_STATE_INVALID")

    start = store.parse_date(parsed["start_date"])
    end = store.parse_date(parsed["end_date"])
    today = store.today()
    if start < today:
        raise ApiError("ERR_PAUSE_START_IN_PAST")
    if end < start:
        raise ApiError("ERR_PAUSE_INTERVAL_INVALID")
    for record in services.pause_records_of(sub["id"]):
        if record["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if not (end < record["start_date"] or start > record["end_date"]):
            raise ApiError("ERR_PAUSE_OVERLAP")

    services.recompute_pause_days(sub)
    projected = int(sub["cumulative_pause_days"]) + ((end - start).days + 1)
    if projected > C.PAUSE_MAX_CUMULATIVE_DAYS:
        raise ApiError("ERR_PAUSE_BUDGET_EXCEEDED")

    row = store.base_row(full=True)
    row.update({
        "subscription_id": sub["id"],
        "start_date": start,
        "end_date": end,
        "status": "ACTIVE" if start == today else "SCHEDULED",
        "actual_end_date": None,
        "consumed_days": 0,
    })
    db.pause_records[row["id"]] = row
    if row["status"] == "ACTIVE":
        sub["lifecycle_state"] = "PAUSED"
    services.recompute_pause_days(sub)
    touch(sub)
    return created(serialize.pause_record(row))


@api(bp, "POST", "/subscriptions/<id>/resume", ["AccountHolder"])
def resume_subscription(id):
    sub = get_subscription(id)
    require_account_owner(sub["account_id"])
    if sub["lifecycle_state"] != "PAUSED":
        raise ApiError("ERR_SUBSCRIPTION_STATE_INVALID")
    active = [p for p in services.pause_records_of(sub["id"])
              if p["status"] == "ACTIVE"]
    if len(active) != 1:
        raise ApiError("ERR_PAUSE_STATE_INVALID")
    record = active[0]

    record["status"] = "ENDED"
    record["actual_end_date"] = store.today()
    consumed = (record["actual_end_date"] - record["start_date"]).days + 1
    record["consumed_days"] = max(0, consumed)
    touch(record)

    sub["lifecycle_state"] = "ACTIVE"
    if sub["anchor_date"] is not None:
        sub["anchor_date"] = store.plus_days(sub["anchor_date"], record["consumed_days"])
    services.recompute_pause_days(sub)
    touch(sub)
    return ok(serialize.subscription(sub))


@api(bp, "POST", "/subscriptions/<id>/cancel", ["AccountHolder", "OpsAdmin"])
def cancel_subscription(id):
    sub = get_subscription(id)
    require_account_owner(sub["account_id"])
    if sub["lifecycle_state"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_SUBSCRIPTION_STATE_INVALID")

    # The refund target and its status are snapshotted BEFORE the cancellation
    # cascade, so a CUTOFF_LOCKED cycle still resolves the undispatched variant.
    refund_target = None
    refund_status = None
    candidates = [c for c in services.cycles_of_subscription(sub["id"])
                  if c["status"] in ("CUTOFF_LOCKED", "DISPATCHED")
                  and c["payment_status"] == "CHARGED"]
    if candidates:
        candidates.sort(key=lambda c: (c["window_start"], c["created_at"], c["_seq"]),
                        reverse=True)
        refund_target = candidates[0]
        refund_status = refund_target["status"]

    if sub["lifecycle_state"] == "PAUSED":
        for record in services.pause_records_of(sub["id"]):
            if record["status"] == "ACTIVE":
                record["status"] = "ENDED"
                record["actual_end_date"] = store.today()
                record["consumed_days"] = max(
                    0, (record["actual_end_date"] - record["start_date"]).days + 1)
                touch(record)

    sub["lifecycle_state"] = "CANCELLED"
    sub["cancelled_at"] = now()
    services.recompute_pause_days(sub)
    touch(sub)

    for cycle in services.cycles_of_subscription(sub["id"]):
        if cycle["status"] in ("PLANNED", "ALLOCATED", "CUTOFF_LOCKED"):
            services.return_cycle_stock(cycle, delete_lines=True)
            cycle["status"] = "CANCELLED"
            touch(cycle)

    if refund_target is not None:
        amount, fee = calc.cancel_refund_cents(
            refund_target, sub["cadence_interval_days"], now(),
            status_override=refund_status)
        services.create_refund(sub["account_id"], refund_target["id"], None,
                               "CANCEL", amount, fee)
    services.recompute_account_estimate(sub["account_id"])
    return ok(serialize.subscription(sub))


@api(bp, "POST", "/subscriptions/<id>/cycles", ["OpsAdmin"])
def generate_cycle(id):
    sub = get_subscription(id)
    if sub["billing_state"] == "DELINQUENT":
        raise ApiError("ERR_SUBSCRIPTION_DELINQUENT")
    if sub["lifecycle_state"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_STATE_INVALID")

    window_start = sub["anchor_date"]
    window_end = store.plus_days(window_start, int(sub["cadence_interval_days"]))
    for existing in services.cycles_of_subscription(sub["id"]):
        if existing["status"] in ("SKIPPED", "RETURNED", "CANCELLED"):
            continue
        if window_start < existing["window_end"] and \
                existing["window_start"] < window_end:
            raise ApiError("ERR_CYCLE_WINDOW_OVERLAP")

    sequence = len(services.cycles_of_subscription(sub["id"])) + 1
    row = store.base_row(full=True)
    row.update({
        "subscription_id": sub["id"],
        "sequence_number": sequence,
        "window_start": window_start,
        "window_end": window_end,
        "ship_date": window_start,
        "cutoff_at": store.plus_hours(
            window_start, -C.CYCLE_CUTOFF_HOURS_BEFORE_SHIP),
        "status": "PLANNED",
        "payment_status": "UNCHARGED",
        "stage_at_allocation": None,
        "subtotal_cents": 0,
        "shipping_cents": 0,
        "gift_credit_applied_cents": 0,
        "referral_credit_applied_cents": 0,
        "loyalty_redemption_applied_cents": 0,
        "loyalty_points_redeemed": 0,
        "promo_discount_cents": 0,
        "total_due_cents": 0,
        "charged_cash_cents": 0,
        "retained_cash_cents": 0,
        "points_earned": 0,
        "dispatched_at": None,
        "delivered_at": None,
    })
    db.cycles[row["id"]] = row
    sub["anchor_date"] = window_end
    touch(sub)
    services.recompute_account_estimate(sub["account_id"])
    return created(serialize.cycle(row))


@api(bp, "GET", "/subscriptions/<id>/cadence-projection", READ_ROLES)
def cadence_projection(id):
    sub = get_subscription(id)
    anchor = sub["anchor_date"]
    interval = int(sub["cadence_interval_days"])
    next_start = anchor
    next_end = store.plus_days(anchor, interval) if anchor else None
    next_cutoff = store.plus_hours(anchor, -C.CYCLE_CUTOFF_HOURS_BEFORE_SHIP) \
        if anchor else None
    return ok({
        "cadence_interval_days": interval,
        "anchor_date": anchor,
        "next_window_start": next_start,
        "next_window_end": next_end,
        "next_cutoff_at": next_cutoff,
        "override_active": sub["cadence_override_days"] is not None,
    })


# ---------------------------------------------------------------------------
# Pause records
# ---------------------------------------------------------------------------
@api(bp, "GET", "/pause-records/<id>", READ_ROLES)
def read_pause(id):
    return ok(serialize.pause_record(get_pause(id)))


@api(bp, "GET", "/pause-records", READ_ROLES)
def list_pauses():
    rows = [r for r in db.pause_records.values()
            if shapes.match(r, "subscription_id", shapes.qs("subscription_id"))
            and shapes.match(r, "status", shapes.qs("status"))]
    return paginate(rows, serialize.pause_record)


@api(bp, "DELETE", "/pause-records/<id>", ["AccountHolder"])
def cancel_pause(id):
    record = get_pause(id)
    sub = db.subscriptions.get(record["subscription_id"])
    if sub is not None:
        require_account_owner(sub["account_id"])
    if record["status"] != "SCHEDULED":
        raise ApiError("ERR_PAUSE_STATE_INVALID")
    record["status"] = "CANCELLED"
    record["consumed_days"] = 0
    touch(record)
    if sub is not None:
        services.recompute_pause_days(sub)
    return ok(serialize.pause_record(record))


# ---------------------------------------------------------------------------
# Resize events / skip records (reads)
# ---------------------------------------------------------------------------
@api(bp, "GET", "/resize-events/<id>", READ_ROLES)
def read_resize_event(id):
    return ok(serialize.resize_event(lookup(db.resize_events, id, "ResizeEvent")))


@api(bp, "GET", "/resize-events", READ_ROLES)
def list_resize_events():
    rows = [r for r in db.resize_events.values()
            if shapes.match(r, "subscription_id", shapes.qs("subscription_id"))
            and shapes.match(r, "child_id", shapes.qs("child_id"))
            and shapes.match(r, "target_cycle_id", shapes.qs("target_cycle_id"))
            and shapes.match(r, "origin", shapes.qs("origin"))
            and shapes.match(r, "status", shapes.qs("status"))]
    return paginate(rows, serialize.resize_event)


@api(bp, "GET", "/skip-records/<id>", READ_ROLES)
def read_skip_record(id):
    return ok(serialize.skip_record(lookup(db.skip_records, id, "SkipRecord")))


@api(bp, "GET", "/skip-records", READ_ROLES)
def list_skip_records():
    rows = [r for r in db.skip_records.values()
            if shapes.match(r, "subscription_id", shapes.qs("subscription_id"))
            and shapes.match(r, "cycle_id", shapes.qs("cycle_id"))
            and shapes.match(r, "status", shapes.qs("status"))]
    return paginate(rows, serialize.skip_record)

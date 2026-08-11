"""Service requests, their items, and the bench workflow."""

from flask import Blueprint

import calcs
import clock as clockmod
import envelope
import ladder
import serializers as ser
import services
from constants import (
    BILLING_STATUSES,
    CHANNELS,
    CUSTODY_LOCATIONS,
    DAMAGE_TIERS,
    ITEM_CLASSES,
    LOCKER_VALUE_AUTHORIZATION_CENTS,
    MAX_ITEMS_PER_REQUEST,
    PRIORITIES,
    REQUEST_STATUSES,
    SERVICE_STATUSES,
)
from errors import ApiError
from store import db, stamp_new, touch

bp = Blueprint("requests", __name__)

REQUEST_SPEC = ladder.Spec(
    required=[
        ("account_id", "string"),
        ("channel", "string"),
        ("requested_date", "string"),
    ],
    optional=[
        ("subscription_id", "string"),
        ("priority", "string"),
        ("locker_site_code", "string"),
        ("locker_high_value_authorized", "boolean"),
    ],
    enums={"channel": CHANNELS, "priority": PRIORITIES},
    dates=["requested_date"],
)

ITEM_SPEC = ladder.Spec(
    required=[
        ("item_class_spec_id", "string"),
        ("item_class", "string"),
        ("declared_damage_tier", "string"),
    ],
    enums={"item_class": ITEM_CLASSES, "declared_damage_tier": DAMAGE_TIERS},
)

ASSESS_SPEC = ladder.Spec(
    required=[("assessed_damage_tier", "string")],
    enums={"assessed_damage_tier": DAMAGE_TIERS},
)

BENCH_INTAKE_SPEC = ladder.Spec(required=[("bench_day_id", "string")])


def _request_shape(body):
    """Rung 4 extras: REWORK is never client-writable and a locker request
    must name its site."""
    if body.get("channel") == "REWORK":
        raise ApiError(
            "ERR_VALIDATION", "The REWORK channel is not client-writable."
        )
    if body.get("channel") == "LOCKER" and not body.get("locker_site_code"):
        raise ApiError(
            "ERR_VALIDATION", "locker_site_code is required on a LOCKER request."
        )


def _sync_quoted_total(request_row):
    request_row["quoted_total_cents"] = sum(
        i["quoted_gross_cents"] for i in ser.request_items(request_row["id"])
    )


def _item_spec(item):
    return db.item_class_specs.get(item["item_class_spec_id"])


def _certification_ok(technician, spec):
    if spec is None or spec["required_certification"] == "NONE":
        return True
    return spec["required_certification"] in (technician or {}).get("certifications", [])


# ---------------------------------------------------------------------------
# POST /sharpening/service-requests
# ---------------------------------------------------------------------------
@bp.route("/sharpening/service-requests", methods=["POST"])
def create_request():
    ctx = ladder.begin("AccountOwner")
    REQUEST_SPEC.validate(ctx.body, extra_shape=_request_shape)
    services.own_account(ctx, ctx.body["account_id"])
    services.account_active(db.accounts.get(ctx.body["account_id"]))
    account = ladder.must_exist(db.accounts, ctx.body["account_id"], "Account")
    subscription = None
    if ctx.body.get("subscription_id"):
        subscription = ladder.must_exist(
            db.subscriptions, ctx.body["subscription_id"], "Subscription"
        )
        # Rung 17.
        if subscription["status"] == "CANCELLED":
            raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE")
    requested_date = clockmod.parse_date(ctx.body["requested_date"])
    # Rung 32.
    if requested_date < clockmod.today():
        raise ApiError("ERR_DATE_IN_PAST")

    row = stamp_new(
        {
            "account_id": account["id"],
            "subscription_id": subscription["id"] if subscription else None,
            "origin_warranty_claim_id": None,
            "channel": ctx.body["channel"],
            "priority": ctx.body.get("priority", "STANDARD"),
            "requested_date": requested_date,
            "locker_site_code": ctx.body.get("locker_site_code"),
            "locker_high_value_authorized": bool(
                ctx.body.get("locker_high_value_authorized", False)
            ),
            "status": "DRAFT",
            "billing_status": "UNBILLED",
            "quoted_total_cents": 0,
            "completed_at": None,
            "_invoice_id": None,
        }
    )
    db.service_requests[row["id"]] = row
    return envelope.created(ser.service_request(row))


@bp.route("/sharpening/service-requests/<id>", methods=["GET"])
def get_request(id):
    ctx = ladder.begin(
        "AccountOwner", "Dispatcher", "Technician", "BillingClerk", "PlatformAdmin"
    )
    row = ladder.must_exist(db.service_requests, id, "ServiceRequest")
    services.own_account(ctx, row["account_id"])
    services.acting_technician(ctx)
    return envelope.ok(ser.service_request(row))


@bp.route("/sharpening/service-requests", methods=["GET"])
def list_requests():
    ctx = ladder.begin(
        "AccountOwner", "Dispatcher", "Technician", "BillingClerk", "PlatformAdmin"
    )
    ladder.check_query_enums(
        ctx.query,
        {
            "channel": CHANNELS,
            "status": REQUEST_STATUSES,
            "billing_status": BILLING_STATUSES,
        },
    )
    limit, offset = ladder.pagination(ctx.query)
    services.acting_technician(ctx)
    rows = list(db.service_requests.values())
    for field in (
        "account_id",
        "subscription_id",
        "origin_warranty_claim_id",
        "channel",
        "status",
        "billing_status",
    ):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.service_request(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /sharpening/service-requests/{id}/items
# ---------------------------------------------------------------------------
@bp.route("/sharpening/service-requests/<id>/items", methods=["POST"])
def add_item(id):
    ctx = ladder.begin("AccountOwner")
    request_row = ladder.must_exist(db.service_requests, id, "ServiceRequest")
    ITEM_SPEC.validate(ctx.body)
    services.own_account(ctx, request_row["account_id"])
    account = db.accounts.get(request_row["account_id"])
    services.account_active(account)
    spec = ladder.must_exist(
        db.item_class_specs, ctx.body["item_class_spec_id"], "ItemClassSpec"
    )
    services.credit_gate(account)
    # Rung 16.
    if request_row["status"] != "DRAFT":
        raise ApiError("ERR_REQUEST_NOT_MUTABLE")
    # Rung 26.
    if ctx.body["item_class"] != spec["item_class"]:
        raise ApiError("ERR_ITEM_CLASS_MISMATCH")
    # Rung 40.
    if len(ser.request_items(request_row["id"])) + 1 > MAX_ITEMS_PER_REQUEST:
        raise ApiError("ERR_ITEM_LIMIT_EXCEEDED")

    tier = ctx.body["declared_damage_tier"]
    gross = calcs.item_gross_cents(spec["list_price_cents"], tier)
    item = stamp_new(
        {
            "service_request_id": request_row["id"],
            "item_class_spec_id": spec["id"],
            "bench_day_id": None,
            "rework_of_request_item_id": None,
            "assessed_by_technician_id": None,
            "item_class": ctx.body["item_class"],
            "declared_damage_tier": tier,
            "assessed_damage_tier": None,
            "quoted_gross_cents": gross,
            "final_gross_cents": gross,
            "charged_service_cents": 0,
            "part_fee_cents": 0,
            "service_minutes_declared": calcs.item_minutes(
                spec["base_service_minutes"], tier
            ),
            "service_minutes_assessed": None,
            "requires_reauthorization": False,
            "authorization_status": "NOT_REQUIRED",
            "service_status": "INTAKE_PENDING",
            "custody_location": "CUSTOMER",
            "allowance_applied": False,
            "delivered_at": None,
        }
    )
    db.request_items[item["id"]] = item
    _sync_quoted_total(request_row)
    touch(request_row)
    return envelope.created(ser.request_item(item))


@bp.route("/sharpening/request-items/<id>", methods=["GET"])
def get_item(id):
    ctx = ladder.begin("AccountOwner", "Technician", "BillingClerk", "PlatformAdmin")
    item = ladder.must_exist(db.request_items, id, "RequestItem")
    parent = db.service_requests.get(item["service_request_id"])
    services.own_account(ctx, parent["account_id"] if parent else None)
    services.acting_technician(ctx)
    return envelope.ok(ser.request_item(item))


@bp.route("/sharpening/request-items", methods=["GET"])
def list_items():
    ctx = ladder.begin("AccountOwner", "Technician", "BillingClerk", "PlatformAdmin")
    ladder.check_query_enums(
        ctx.query,
        {"custody_location": CUSTODY_LOCATIONS, "service_status": SERVICE_STATUSES},
    )
    limit, offset = ladder.pagination(ctx.query)
    services.acting_technician(ctx)
    rows = list(db.request_items.values())
    for field in (
        "service_request_id",
        "item_class_spec_id",
        "bench_day_id",
        "rework_of_request_item_id",
        "assessed_by_technician_id",
        "custody_location",
        "service_status",
    ):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.request_item(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /sharpening/service-requests/{id}/submit
# ---------------------------------------------------------------------------
@bp.route("/sharpening/service-requests/<id>/submit", methods=["POST"])
def submit_request(id):
    ctx = ladder.begin("AccountOwner")
    request_row = ladder.must_exist(db.service_requests, id, "ServiceRequest")
    services.own_account(ctx, request_row["account_id"])
    account = db.accounts.get(request_row["account_id"])
    services.account_active(account)
    services.credit_gate(account)
    if request_row["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if request_row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "The request is not DRAFT.")
    if not ser.request_items(request_row["id"]):
        raise ApiError("ERR_INVALID_STATE", "The request holds no item.")

    _sync_quoted_total(request_row)
    request_row["status"] = "SUBMITTED"
    touch(request_row)
    return envelope.ok(ser.service_request(request_row))


# ---------------------------------------------------------------------------
# POST /sharpening/service-requests/{id}/cancel
# ---------------------------------------------------------------------------
@bp.route("/sharpening/service-requests/<id>/cancel", methods=["POST"])
def cancel_request(id):
    ctx = ladder.begin("AccountOwner")
    request_row = ladder.must_exist(db.service_requests, id, "ServiceRequest")
    services.own_account(ctx, request_row["account_id"])
    services.account_active(db.accounts.get(request_row["account_id"]))
    if request_row["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if request_row["status"] not in ("DRAFT", "SUBMITTED", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", "The request is already in service.")

    previous = request_row["status"]
    if previous == "SUBMITTED":
        compartment = services.compartment_holding(request_row["id"])
        if compartment is not None and compartment["status"] == "ASSIGNED":
            compartment["status"] = "AVAILABLE"
            compartment["access_code"] = None
            compartment["current_service_request_id"] = None
            compartment["last_released_at"] = clockmod.now()
            touch(compartment)
    elif previous == "SCHEDULED":
        for stop in db.route_stops.values():
            if (
                stop["service_request_id"] == request_row["id"]
                and stop["status"] == "SCHEDULED"
            ):
                stop["status"] = "SKIPPED"
                touch(stop)
                run = db.route_runs.get(stop["route_run_id"])
                if run is not None:
                    touch(run)
    request_row["status"] = "CANCELLED"
    touch(request_row)
    return envelope.ok(ser.service_request(request_row))


# ---------------------------------------------------------------------------
# POST /sharpening/service-requests/{id}/pickup
# ---------------------------------------------------------------------------
@bp.route("/sharpening/service-requests/<id>/pickup", methods=["POST"])
def pickup_request(id):
    ctx = ladder.begin("Technician")
    request_row = ladder.must_exist(db.service_requests, id, "ServiceRequest")
    stop = services.request_active_stop(request_row["id"])
    run = db.route_runs.get(stop["route_run_id"]) if stop else None
    services.own_run_technician(ctx, run)
    services.account_active(db.accounts.get(request_row["account_id"]))
    if request_row["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if request_row["status"] != "SCHEDULED" or request_row["channel"] not in (
        "VAN_ROUTE",
        "REWORK",
    ):
        raise ApiError("ERR_INVALID_STATE", "The request cannot be picked up.")
    if stop is None or stop["status"] != "ARRIVED":
        raise ApiError("ERR_INVALID_STATE", "The route stop has not been arrived at.")

    for item in ser.request_items(request_row["id"]):
        if item["custody_location"] == "CUSTOMER":
            item["custody_location"] = "VAN"
            touch(item)
    stop["status"] = "SERVICED"
    touch(stop)
    request_row["status"] = "IN_SERVICE"
    touch(request_row)
    return envelope.ok(ser.service_request(request_row))


# ---------------------------------------------------------------------------
# POST /sharpening/service-requests/{id}/bench-intake
# ---------------------------------------------------------------------------
@bp.route("/sharpening/service-requests/<id>/bench-intake", methods=["POST"])
def bench_intake(id):
    ctx = ladder.begin("Technician")
    request_row = ladder.must_exist(db.service_requests, id, "ServiceRequest")
    BENCH_INTAKE_SPEC.validate(ctx.body)
    services.acting_technician(ctx)
    services.account_active(db.accounts.get(request_row["account_id"]))
    bench = ladder.must_exist(db.bench_days, ctx.body["bench_day_id"], "BenchDay")
    # Rung 19 -- every item must sit in the custody this channel intakes from.
    required = "LOCKER" if request_row["channel"] == "LOCKER" else "VAN"
    items = ser.request_items(request_row["id"])
    if not items or any(i["custody_location"] != required for i in items):
        raise ApiError("ERR_ITEM_NOT_IN_CUSTODY")
    # Rung 20 -- reported before the capacity check at rung 54.
    if bench["bench_date"] != clockmod.today():
        raise ApiError("ERR_BENCH_DAY_DATE_MISMATCH")
    # Rung 54.
    incoming = sum(i["service_minutes_declared"] for i in items)
    if ser.bench_day_booked_minutes(bench["id"]) + incoming > bench["bench_minute_budget"]:
        raise ApiError("ERR_BENCH_CAPACITY_EXCEEDED")

    for item in items:
        item["bench_day_id"] = bench["id"]
        item["custody_location"] = "BENCH"
        touch(item)
    if request_row["channel"] == "LOCKER":
        compartment = services.compartment_holding(request_row["id"])
        if compartment is not None and compartment["status"] == "OCCUPIED":
            compartment["status"] = "ASSIGNED"
            touch(compartment)
    touch(request_row)
    return envelope.ok(ser.service_request(request_row))


# ---------------------------------------------------------------------------
# POST /sharpening/service-requests/{id}/deliver
# ---------------------------------------------------------------------------
@bp.route("/sharpening/service-requests/<id>/deliver", methods=["POST"])
def deliver_request(id):
    ctx = ladder.begin("Technician")
    request_row = ladder.must_exist(db.service_requests, id, "ServiceRequest")
    services.acting_technician(ctx)
    services.account_active(db.accounts.get(request_row["account_id"]))
    if request_row["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if request_row["status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE", "The request is not IN_SERVICE.")
    items = ser.request_items(request_row["id"])
    if any(i["service_status"] not in ("DONE", "RETURNED_UNSERVICED") for i in items):
        raise ApiError("ERR_INVALID_STATE", "An item is not finished.")

    now = clockmod.now()
    request_row["status"] = "COMPLETED"
    request_row["completed_at"] = now
    locker_channel = request_row["channel"] == "LOCKER"
    finished = [i for i in items if i["service_status"] == "DONE"]
    for item in finished:
        # Cascade link 1.
        item["service_status"] = "DELIVERED"
        if locker_channel:
            item["custody_location"] = "LOCKER"
        else:
            # Cascade link 2 -- custody and the warranty clock.
            item["custody_location"] = "DELIVERED"
            item["delivered_at"] = now
        touch(item)

    if locker_channel:
        compartment = services.compartment_holding(request_row["id"])
        if compartment is not None and compartment["status"] == "ASSIGNED":
            compartment["status"] = "OCCUPIED"
            compartment["hold_expires_at"] = services.hold_expiry()
            touch(compartment)
    else:
        # Cascade links 3 and 4 -- the loaner closes and the unit is inspected.
        issue = services.open_loaner_issue_for(request_row["id"])
        if issue is not None:
            services.close_loaner_issue(issue, damage_reported=False)
        if request_row["channel"] == "REWORK":
            for item in items:
                original = db.request_items.get(item["rework_of_request_item_id"])
                if original is not None and original["service_status"] == "REWORK_QUEUED":
                    original["service_status"] = "DELIVERED"
                    original["custody_location"] = "DELIVERED"
                    original["delivered_at"] = now
                    touch(original)

    touch(request_row)
    return envelope.ok(ser.service_request(request_row))


# ---------------------------------------------------------------------------
# POST /sharpening/service-requests/{id}/locker-assign
# ---------------------------------------------------------------------------
@bp.route("/sharpening/service-requests/<id>/locker-assign", methods=["POST"])
def locker_assign(id):
    ctx = ladder.begin("AccountOwner")
    request_row = ladder.must_exist(db.service_requests, id, "ServiceRequest")
    services.own_account(ctx, request_row["account_id"])
    account = db.accounts.get(request_row["account_id"])
    services.account_active(account)
    services.credit_gate(account)
    if request_row["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if request_row["channel"] != "LOCKER" or request_row["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "The request cannot take a compartment.")

    compartment = services.select_compartment(request_row)
    compartment["status"] = "ASSIGNED"
    compartment["access_code"] = services.mint_access_code()
    compartment["current_service_request_id"] = request_row["id"]
    compartment["hold_expires_at"] = services.hold_expiry()
    touch(compartment)
    return envelope.ok(ser.locker_compartment(compartment))


# ---------------------------------------------------------------------------
# POST /sharpening/request-items/{id}/assess
# ---------------------------------------------------------------------------
@bp.route("/sharpening/request-items/<id>/assess", methods=["POST"])
def assess_item(id):
    ctx = ladder.begin("Technician")
    item = ladder.must_exist(db.request_items, id, "RequestItem")
    ASSESS_SPEC.validate(ctx.body)
    technician = services.acting_technician(ctx)
    parent = db.service_requests.get(item["service_request_id"])
    services.account_active(db.accounts.get(parent["account_id"]) if parent else None)
    if item["service_status"] in ("RETURNED_UNSERVICED", "ABANDONED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if item["service_status"] != "INTAKE_PENDING":
        raise ApiError("ERR_INVALID_STATE", "The item is not awaiting intake.")
    # Rung 16.
    if parent is None or parent["status"] != "IN_SERVICE":
        raise ApiError("ERR_REQUEST_NOT_MUTABLE")
    # Rung 19.
    if item["custody_location"] != "BENCH":
        raise ApiError("ERR_ITEM_NOT_IN_CUSTODY")
    spec = _item_spec(item)
    # Rung 22.
    if not _certification_ok(technician, spec):
        raise ApiError("ERR_CERTIFICATION_MISSING")

    tier = ctx.body["assessed_damage_tier"]
    new_gross = calcs.item_gross_cents(spec["list_price_cents"], tier)
    # Rung 25 -- the compartment's stored value after the re-pricing.
    if parent["channel"] == "LOCKER" and not parent["locker_high_value_authorized"]:
        compartment = services.compartment_holding(parent["id"])
        if compartment is not None:
            projected = 0
            for sibling in ser.request_items(parent["id"]):
                if sibling["custody_location"] not in ("LOCKER", "BENCH"):
                    continue
                projected += (
                    new_gross if sibling["id"] == item["id"] else sibling["final_gross_cents"]
                )
            if projected > LOCKER_VALUE_AUTHORIZATION_CENTS:
                raise ApiError("ERR_LOCKER_VALUE_AUTHORIZATION_REQUIRED")

    item["assessed_damage_tier"] = tier
    item["assessed_by_technician_id"] = ctx.user_id
    item["service_minutes_assessed"] = calcs.item_minutes(
        spec["base_service_minutes"], tier
    )
    item["final_gross_cents"] = new_gross
    item["part_fee_cents"] = calcs.part_fee_for(tier)
    item["requires_reauthorization"] = calcs.requires_reauthorization(
        new_gross, item["quoted_gross_cents"]
    )
    item["authorization_status"] = (
        "PENDING" if item["requires_reauthorization"] else "NOT_REQUIRED"
    )
    item["service_status"] = "ASSESSED"
    touch(item)
    return envelope.ok(ser.request_item(item))


# ---------------------------------------------------------------------------
# POST /sharpening/request-items/{id}/authorize
# ---------------------------------------------------------------------------
@bp.route("/sharpening/request-items/<id>/authorize", methods=["POST"])
def authorize_item(id):
    ctx = ladder.begin("AccountOwner")
    item = ladder.must_exist(db.request_items, id, "RequestItem")
    parent = db.service_requests.get(item["service_request_id"])
    services.own_account(ctx, parent["account_id"] if parent else None)
    services.account_active(db.accounts.get(parent["account_id"]) if parent else None)
    if item["service_status"] in ("RETURNED_UNSERVICED", "ABANDONED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if item["authorization_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "The item is not awaiting authorization.")
    item["authorization_status"] = "AUTHORIZED"
    touch(item)
    return envelope.ok(ser.request_item(item))


# ---------------------------------------------------------------------------
# POST /sharpening/request-items/{id}/decline
# ---------------------------------------------------------------------------
@bp.route("/sharpening/request-items/<id>/decline", methods=["POST"])
def decline_item(id):
    ctx = ladder.begin("AccountOwner")
    item = ladder.must_exist(db.request_items, id, "RequestItem")
    parent = db.service_requests.get(item["service_request_id"])
    services.own_account(ctx, parent["account_id"] if parent else None)
    services.account_active(db.accounts.get(parent["account_id"]) if parent else None)
    if item["service_status"] in ("RETURNED_UNSERVICED", "ABANDONED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if item["service_status"] != "ASSESSED" or item["authorization_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "The item has no pending authorization.")
    # Rung 16.
    if parent is None or parent["status"] != "IN_SERVICE":
        raise ApiError("ERR_REQUEST_NOT_MUTABLE")

    item["authorization_status"] = "DECLINED"
    item["service_status"] = "RETURNED_UNSERVICED"
    item["charged_service_cents"] = 0
    item["part_fee_cents"] = 0
    # Releasing the item's bench minutes: it stops counting against the day.
    item["bench_day_id"] = None
    if item["allowance_applied"]:
        subscription = db.subscriptions.get(
            parent["subscription_id"] if parent else None
        )
        if subscription is not None:
            services.append_allowance_entry(
                subscription, "RESTORED", 1, "DECLINE", request_item_id=item["id"]
            )
            subscription["allowance_remaining"] += 1
            touch(subscription)
        item["allowance_applied"] = False
    touch(item)
    return envelope.ok(ser.request_item(item))


# ---------------------------------------------------------------------------
# POST /sharpening/request-items/{id}/start-work
# ---------------------------------------------------------------------------
@bp.route("/sharpening/request-items/<id>/start-work", methods=["POST"])
def start_work(id):
    ctx = ladder.begin("Technician")
    item = ladder.must_exist(db.request_items, id, "RequestItem")
    technician = services.acting_technician(ctx)
    parent = db.service_requests.get(item["service_request_id"])
    services.account_active(db.accounts.get(parent["account_id"]) if parent else None)
    if item["service_status"] in ("RETURNED_UNSERVICED", "ABANDONED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if item["service_status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", "The item is not ASSESSED.")
    # Rung 16.
    if parent is None or parent["status"] != "IN_SERVICE":
        raise ApiError("ERR_REQUEST_NOT_MUTABLE")
    # Rung 19.
    if item["custody_location"] != "BENCH":
        raise ApiError("ERR_ITEM_NOT_IN_CUSTODY")
    # Rung 22.
    if not _certification_ok(technician, _item_spec(item)):
        raise ApiError("ERR_CERTIFICATION_MISSING")
    # Rung 24.
    if item["authorization_status"] not in ("NOT_REQUIRED", "AUTHORIZED"):
        raise ApiError("ERR_AUTHORIZATION_REQUIRED")

    item["service_status"] = "IN_WORK"
    touch(item)
    return envelope.ok(ser.request_item(item))


# ---------------------------------------------------------------------------
# POST /sharpening/request-items/{id}/complete-work
# ---------------------------------------------------------------------------
@bp.route("/sharpening/request-items/<id>/complete-work", methods=["POST"])
def complete_work(id):
    ctx = ladder.begin("Technician")
    item = ladder.must_exist(db.request_items, id, "RequestItem")
    services.acting_technician(ctx)
    parent = db.service_requests.get(item["service_request_id"])
    services.account_active(db.accounts.get(parent["account_id"]) if parent else None)
    if item["service_status"] in ("RETURNED_UNSERVICED", "ABANDONED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if item["service_status"] != "IN_WORK":
        raise ApiError("ERR_INVALID_STATE", "The item is not IN_WORK.")
    # Rung 16.
    if parent is None or parent["status"] != "IN_SERVICE":
        raise ApiError("ERR_REQUEST_NOT_MUTABLE")

    item["service_status"] = "DONE"
    touch(item)
    return envelope.ok(ser.request_item(item))

"""Price files, price-file lines, publication and rollback."""

from db import db, base_row, fmt, now, parse_stored, touch
from errors import ApiError
from flask import Blueprint
from middleware import authenticate
from response import created, ok, ok_list
from services import flows, serialize
from validation import parse_body, pagination, q_int, q_str

bp = Blueprint("pricefiles", __name__)

ALL_ROLES = ("PlatformAdmin", "PricingAdmin", "CreditManager", "WarrantyAdmin",
             "BranchCounterRep", "Servicer")
PRICING_WRITERS = ("PricingAdmin", "PlatformAdmin")
LIFECYCLES = {"ACTIVE", "SUPERSEDED", "OBSOLETE", "NLA"}
PRICE_FILE_STATUSES = {"DRAFT", "PUBLISHED", "SUPERSEDED", "ROLLED_BACK"}


def _file_or_404(file_id):
    return flows.find(db.price_files, file_id, "ERR_PRICE_FILE_NOT_FOUND")


@bp.post("/price-files")
def create_price_file():
    authenticate(PRICING_WRITERS)
    body = parse_body([
        ("file_version", "posint", True),
        ("effective_at", "dt", True),
        ("effective_until", "dt", False),
    ])
    effective_at = body["effective_at"]
    effective_until = body.get("effective_until")
    if effective_until is not None and not (effective_until > effective_at):
        raise ApiError("ERR_PRICE_INTERVAL_INVALID",
                       "effective_until must be strictly after effective_at")
    for existing in db.price_files.values():
        if existing["file_version"] == body["file_version"]:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "file_version %d already exists" % body["file_version"])
    row = base_row()
    row.update({
        "file_version": body["file_version"],
        "effective_at": fmt(effective_at),
        "effective_until": fmt(effective_until) if effective_until else None,
        "price_file_status": "DRAFT",
        "published_at": None,
        "_autoclosed_file_ids": [],
    })
    db.price_files[row["id"]] = row
    return created(serialize.price_file(row))


@bp.post("/price-files/<file_id>/lines")
def add_price_file_line(file_id):
    authenticate(PRICING_WRITERS)
    body = parse_body([
        ("part_id", "str", True),
        ("new_list_price_cents", "posint", True),
        ("new_core_deposit_cents", "money", False),
        ("new_lifecycle_status", "enum", False, LIFECYCLES),
    ])
    price_file = _file_or_404(file_id)
    flows.part_or_404(body["part_id"])
    if price_file["price_file_status"] != "DRAFT":
        raise ApiError("ERR_PRICE_FILE_STATE_INVALID",
                       "Lines may only be added to a DRAFT price file")
    for existing in flows.price_file_lines_of(price_file):
        if existing["part_id"] == body["part_id"]:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "This file already carries a line for that part")
    row = base_row()
    row.update({
        "price_file_id": price_file["id"],
        "part_id": body["part_id"],
        "new_list_price_cents": body["new_list_price_cents"],
        "new_core_deposit_cents": body.get("new_core_deposit_cents"),
        "new_lifecycle_status": body.get("new_lifecycle_status"),
        "previous_list_price_cents": None,
        "previous_lifecycle_status": None,
        "previous_core_deposit_cents": None,
    })
    db.price_file_lines[row["id"]] = row
    touch(price_file)
    return created(serialize.price_file_line(row))


@bp.post("/price-files/<file_id>/publish")
def publish_price_file(file_id):
    authenticate(PRICING_WRITERS)
    parse_body([])
    price_file = _file_or_404(file_id)
    if price_file["price_file_status"] != "DRAFT":
        raise ApiError("ERR_PRICE_FILE_STATE_INVALID",
                       "Only a DRAFT price file may be published")
    effective_at = parse_stored(price_file["effective_at"])
    if effective_at > now():
        raise ApiError("ERR_PRICE_FILE_NOT_YET_EFFECTIVE",
                       "The file's effective_at is in the future")
    lines = flows.price_file_lines_of(price_file)
    if not lines:
        raise ApiError("ERR_PRICE_FILE_HAS_NO_LINES",
                       "A price file must carry at least one line to publish")

    # --- window reconciliation (all conflicts detected before anything is written)
    new_parts = set(line["part_id"] for line in lines)
    new_end = parse_stored(price_file["effective_until"])
    to_autoclose = []
    for other in flows.rows_sorted(db.price_files):
        if other["id"] == price_file["id"]:
            continue
        if other["price_file_status"] != "PUBLISHED":
            continue
        if not (flows.price_file_part_ids(other) & new_parts):
            continue
        other_start = parse_stored(other["effective_at"])
        other_end = parse_stored(other["effective_until"])
        starts_before_new_end = new_end is None or other_start < new_end
        new_starts_before_other_end = other_end is None or effective_at < other_end
        if starts_before_new_end and new_starts_before_other_end:
            if other["effective_until"] is None and other_start < effective_at:
                to_autoclose.append(other)
            else:
                raise ApiError("ERR_PRICE_WINDOW_OVERLAP",
                               "Window collides with published price file %s"
                               % other["id"])

    for other in to_autoclose:
        other["effective_until"] = price_file["effective_at"]
        other["price_file_status"] = "SUPERSEDED"
        touch(other)
        price_file["_autoclosed_file_ids"].append(other["id"])

    # --- hop 1: snapshot and apply catalog changes
    newly_obsolete = []
    for line in lines:
        part = db.parts.get(line["part_id"])
        if part is None:
            continue
        line["previous_list_price_cents"] = part["list_price_cents"]
        line["previous_core_deposit_cents"] = part["core_deposit_cents"]
        line["previous_lifecycle_status"] = part["lifecycle_status"]
        touch(line)
        was = part["lifecycle_status"]
        part["list_price_cents"] = line["new_list_price_cents"]
        if line["new_core_deposit_cents"] is not None:
            part["core_deposit_cents"] = line["new_core_deposit_cents"]
        if line["new_lifecycle_status"] is not None:
            part["lifecycle_status"] = line["new_lifecycle_status"]
        touch(part)
        if part["lifecycle_status"] == "OBSOLETE" and was != "OBSOLETE":
            newly_obsolete.append(part)

    # --- hop 2: push open lines into substitution
    affected_orders = []
    for part in newly_obsolete:
        for line in flows.rows_sorted(db.order_lines):
            if line["resolved_part_id"] != part["id"]:
                continue
            if line["line_status"] not in ("RESOLVED", "ALLOCATED"):
                continue
            flows.release_reservation(line)
            line["line_status"] = "SUBSTITUTE_PENDING"
            touch(line)
            request = base_row()
            request.update({
                "order_line_id": line["id"],
                "obsolete_part_id": part["id"],
                "proposed_substitute_part_id": None,
                "request_status": "PENDING",
                "price_variance_pct": None,
                "source": "PRICE_FILE_OBSOLESCENCE",
                "created_by_price_file_id": price_file["id"],
                "decided_by_user_id": None,
            })
            db.substitute_requests[request["id"]] = request
            order = db.part_orders.get(line["part_order_id"])
            if order is not None and order not in affected_orders:
                affected_orders.append(order)

    # --- hop 3: hold the affected orders and recompute their totals
    for order in affected_orders:
        if order["fulfillment_status"] == "ALLOCATED":
            order["fulfillment_status"] = "HELD"
            order["hold_reason"] = "SUBSTITUTE_PENDING"
        flows.recompute_totals(order, reassess_freight=False)
        touch(order)

    # --- hop 4: refresh each affected account's exposure
    for account in _accounts_of(affected_orders):
        flows.sync_account(account)

    price_file["price_file_status"] = "PUBLISHED"
    price_file["published_at"] = fmt(now())
    touch(price_file)
    return ok(serialize.price_file(price_file))


def _accounts_of(orders):
    seen = []
    for order in orders:
        account = db.servicer_accounts.get(order["servicer_account_id"])
        if account is not None and account not in seen:
            seen.append(account)
    return seen


@bp.post("/price-files/<file_id>/rollback")
def rollback_price_file(file_id):
    authenticate(PRICING_WRITERS)
    parse_body([("rollback_reason", "str", True)])
    price_file = _file_or_404(file_id)
    if price_file["price_file_status"] != "PUBLISHED":
        raise ApiError("ERR_PRICE_FILE_STATE_INVALID",
                       "Only a PUBLISHED price file may be rolled back")
    created_requests = [s for s in flows.rows_sorted(db.substitute_requests)
                        if s.get("created_by_price_file_id") == price_file["id"]]
    for request in created_requests:
        if request["request_status"] != "PENDING":
            raise ApiError("ERR_PRICE_FILE_STATE_INVALID",
                           "A substitute request created by this file has already "
                           "been decided")

    # replay each snapshot back onto its part
    for line in flows.price_file_lines_of(price_file):
        part = db.parts.get(line["part_id"])
        if part is None:
            continue
        if line["previous_list_price_cents"] is not None:
            part["list_price_cents"] = line["previous_list_price_cents"]
        if line["previous_core_deposit_cents"] is not None:
            part["core_deposit_cents"] = line["previous_core_deposit_cents"]
        if line["previous_lifecycle_status"] is not None:
            part["lifecycle_status"] = line["previous_lifecycle_status"]
        touch(part)

    affected_orders = []
    for request in created_requests:
        request["request_status"] = "WITHDRAWN"
        touch(request)
        line = db.order_lines.get(request["order_line_id"])
        if line is not None and line["line_status"] == "SUBSTITUTE_PENDING":
            line["line_status"] = "RESOLVED"
            touch(line)
        if line is not None:
            order = db.part_orders.get(line["part_order_id"])
            if order is not None and order not in affected_orders:
                affected_orders.append(order)

    for order in affected_orders:
        if order["fulfillment_status"] == "HELD":
            flows.release_order_if_ready(order)
        else:
            flows.recompute_totals(order, reassess_freight=False)
            touch(order)

    for other_id in price_file.get("_autoclosed_file_ids", []):
        other = db.price_files.get(other_id)
        if other is None:
            continue
        other["effective_until"] = None
        other["price_file_status"] = "PUBLISHED"
        touch(other)
    price_file["_autoclosed_file_ids"] = []

    for account in _accounts_of(affected_orders):
        flows.sync_account(account)

    price_file["price_file_status"] = "ROLLED_BACK"
    touch(price_file)
    return ok(serialize.price_file(price_file))


@bp.get("/price-files")
def list_price_files():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.price_files)
    status = q_str("price_file_status")
    if status is not None:
        rows = [r for r in rows if r["price_file_status"] == status]
    file_version = q_int("file_version")
    if file_version is not None:
        rows = [r for r in rows if r["file_version"] == file_version]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.price_file(r) for r in page], limit, offset, total)


@bp.get("/price-files/<file_id>")
def get_price_file(file_id):
    authenticate(ALL_ROLES)
    return ok(serialize.price_file(_file_or_404(file_id)))


@bp.get("/price-file-lines")
def list_price_file_lines():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.price_file_lines)
    for field in ("price_file_id", "part_id"):
        value = q_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.price_file_line(r) for r in page],
                   limit, offset, total)


@bp.get("/price-file-lines/<line_id>")
def get_price_file_line(line_id):
    authenticate(ALL_ROLES)
    row = flows.find(db.price_file_lines, line_id, "ERR_PRICE_FILE_LINE_NOT_FOUND")
    return ok(serialize.price_file_line(row))

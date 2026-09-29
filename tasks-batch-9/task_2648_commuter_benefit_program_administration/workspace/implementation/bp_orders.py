"""Procurement: regional order batches and the media order fulfillment cycle."""

from flask import Blueprint

import serialize
from auth import (
    authenticate,
    require_employee_scope,
    resolve_batch,
    resolve_election,
    resolve_media,
    resolve_order,
    resolve_window,
)
from calc import (
    batch_pending_lines,
    maybe_reconcile_batch,
    post_entry,
    price_batch,
    recompute_line_count,
    rederive_fulfillment,
    replacement_fee,
    resolve_account_for,
    MEDIA_REISSUE_LIMIT,
    WAIVABLE_UNDELIVERED_REASONS,
)
from errors import fail, invalid_request
from guards import (
    TERMINAL_BATCH,
    TERMINAL_MEDIA_ORDER,
    owner_of_media_order,
    require_before_cutoff,
    require_distinct_operator,
    require_employer_active,
    require_media_active,
    require_media_eligible,
    require_not_terminal,
    require_transition,
)
from responses import array_response, created_response, object_response, paginate
from store import bump, sorted_rows, stamp_new, store
from validate import (
    BATCH_STATUSES,
    MEDIA_ORDER_STATUSES,
    REGION_CODES,
    UNDELIVERED_REASONS,
    enum_filter,
    field,
    pagination,
    parse_body,
    str_filter,
)

bp = Blueprint("orders", __name__)


def _employer_of_batch(batch):
    window = store.election_windows.get(batch["election_window_id"])
    if window is None:
        return None
    return store.employers.get(window["employer_id"])


# ------------------------------------------------------------------ OrderBatch
@bp.post("/benefits/order-batches")
def create_batch():
    authenticate(["OrderDesk"])
    specs = [
        field("election_window_id", "id", required=True),
        field("region_code", "enum", required=True, choices=REGION_CODES),
    ]
    _body, values = parse_body(specs)
    window = resolve_window(values["election_window_id"])
    employer = store.employers.get(window["employer_id"])
    require_employer_active(employer)
    row = {
        "election_window_id": window["id"],
        "region_code": values["region_code"],
        "status": "OPEN",
        "line_count": 0,
        "subtotal_cents": 0,
        "discount_cents": 0,
        "total_cents": 0,
        "sealed_by_user_id": None,
        "released_by_user_id": None,
        "sealed_at": None,
    }
    stamp_new(row)
    store.order_batches[row["id"]] = row
    return created_response(serialize.order_batch(row))


@bp.get("/benefits/order-batches/<batch_id>")
def read_batch(batch_id):
    authenticate(["ProgramAdmin", "OrderDesk"])
    row = resolve_batch(batch_id)
    return object_response(serialize.order_batch(row))


@bp.get("/benefits/order-batches")
def list_batches():
    authenticate(["ProgramAdmin", "OrderDesk"])
    window_id = str_filter("election_window_id")
    status = enum_filter("status", BATCH_STATUSES)
    region_code = enum_filter("region_code", REGION_CODES)
    limit, offset = pagination()
    rows = []
    for row in store.order_batches.values():
        if window_id is not None and row["election_window_id"] != window_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if region_code is not None and row["region_code"] != region_code:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.order_batch(r) for r in page], limit, offset, total)


@bp.post("/benefits/order-batches/<batch_id>/seal")
def seal_batch(batch_id):
    principal = authenticate(["OrderDesk"])
    row = resolve_batch(batch_id)
    require_not_terminal(row, "status", TERMINAL_BATCH, "OrderBatch")
    require_transition(row["status"] == "OPEN",
                       "OrderBatch %s cannot be sealed from status %s."
                       % (row["id"], row["status"]))
    window = store.election_windows.get(row["election_window_id"])
    require_before_cutoff(window)
    if not batch_pending_lines(row["id"]):
        fail("ERR_EMPTY_ORDER_BATCH",
             "OrderBatch %s holds no PENDING media order lines." % row["id"])
    price_batch(row)
    row["status"] = "SEALED"
    row["sealed_by_user_id"] = principal.user_id
    row["sealed_at"] = store.clock_iso()
    bump(row)
    return object_response(serialize.order_batch(row))


@bp.post("/benefits/order-batches/<batch_id>/release")
def release_batch(batch_id):
    principal = authenticate(["OrderDesk"])
    row = resolve_batch(batch_id)
    require_not_terminal(row, "status", TERMINAL_BATCH, "OrderBatch")
    require_transition(row["status"] == "SEALED",
                       "OrderBatch %s cannot be released from status %s."
                       % (row["id"], row["status"]))
    window = store.election_windows.get(row["election_window_id"])
    require_transition(window is not None and window["status"] in ("OPEN", "LOCKED"),
                       "OrderBatch %s cannot be released because its election "
                       "window is not OPEN or LOCKED." % row["id"])
    require_distinct_operator(
        principal.user_id, row["sealed_by_user_id"],
        "The operator that sealed OrderBatch %s may not also release it."
        % row["id"])

    row["status"] = "RELEASED"
    row["released_by_user_id"] = principal.user_id
    touched_elections = []
    for line in batch_pending_lines(row["id"]):
        line["status"] = "SUBMITTED"
        bump(line)
        election = store.elections.get(line["election_id"])
        if election is not None and election["id"] not in \
                [e["id"] for e in touched_elections]:
            touched_elections.append(election)
    for election in touched_elections:
        rederive_fulfillment(election)
        bump(election)
    bump(row)
    return object_response(serialize.order_batch(row))


# ------------------------------------------------------------------ MediaOrder
@bp.post("/benefits/media-orders")
def create_media_order():
    authenticate(["OrderDesk"])
    specs = [
        field("election_id", "id", required=True),
        field("transit_media_id", "id", required=True),
        field("order_batch_id", "id", required=True),
        field("quantity", "integer", required=True, minimum=1),
        field("coverage_start_at", "datetime", required=True),
        field("coverage_end_at", "datetime", required=True),
        field("expected_election_version", "integer", required=True),
    ]
    body, values = parse_body(specs)
    if values["coverage_end_at"] <= values["coverage_start_at"]:
        invalid_request("Field 'coverage_end_at' must be strictly after "
                        "'coverage_start_at'.")

    # ladder 7 - body identifier resolution
    election = resolve_election(values["election_id"])
    media = resolve_media(values["transit_media_id"])
    batch = resolve_batch(values["order_batch_id"])

    window = store.election_windows.get(election["election_window_id"])
    employer = store.employers.get(window["employer_id"]) if window else None
    category = store.benefit_categories.get(election["benefit_category_id"])
    employee = store.employees.get(election["employee_id"])

    # ladder 9
    require_employer_active(employer)

    # ladder 11 - the batch must still be OPEN
    if batch["status"] != "OPEN":
        fail("ERR_ORDER_BATCH_NOT_OPEN",
             "OrderBatch %s is not OPEN." % batch["id"])

    # ladder 19, 20
    require_media_eligible(media, category, employee)
    require_media_active(media)

    # ladder 21 - account / election / batch coherence
    account = resolve_account_for(election["employee_id"], election["benefit_category_id"])
    if account is None:
        fail("ERR_ACCOUNT_MISMATCH",
             "No benefit account exists for this election's employee and benefit "
             "category pair.")
    if election["transit_media_id"] != media["id"]:
        fail("ERR_ACCOUNT_MISMATCH",
             "The supplied transit_media_id does not match the election's "
             "elected transit media.")
    if batch["election_window_id"] != election["election_window_id"]:
        fail("ERR_ACCOUNT_MISMATCH",
             "The order batch belongs to a different election window than the "
             "election.")

    # ladder 23
    require_before_cutoff(window)

    # the PENDING lines this create supersedes are exempt from the overlap test
    superseded = [o for o in store.media_orders.values()
                  if o["election_id"] == election["id"]
                  and o["transit_media_id"] == media["id"]
                  and o["status"] == "PENDING"]
    superseded = sorted_rows(superseded)
    exempt = set(o["id"] for o in superseded)

    # ladder 25 - closed coverage interval collision on the employee/media pair
    start = values["coverage_start_at"]
    end = values["coverage_end_at"]
    for other in store.media_orders.values():
        if other["id"] in exempt:
            continue
        if other["status"] == "CANCELLED":
            continue
        if other["transit_media_id"] != media["id"]:
            continue
        other_election = store.elections.get(other["election_id"])
        if other_election is None or \
                other_election["employee_id"] != election["employee_id"]:
            continue
        if start <= other["_coverage_end_at"] and end >= other["_coverage_start_at"]:
            fail("ERR_MEDIA_COVERAGE_OVERLAP",
                 "The requested coverage interval collides with media order %s."
                 % other["id"])

    # ladder 31 - optimistic concurrency on the parent election
    if values["expected_election_version"] != election["version"]:
        fail("ERR_STALE_ELECTION_VERSION",
             "The supplied expected_election_version does not match the current "
             "version of election %s." % election["id"])

    touched_batches = []
    for prior in superseded:
        prior["status"] = "CANCELLED"
        bump(prior)
        prior_batch = store.order_batches.get(prior["order_batch_id"])
        if prior_batch is not None and prior_batch["id"] not in \
                [b["id"] for b in touched_batches]:
            touched_batches.append(prior_batch)

    row = {
        "election_id": election["id"],
        "transit_media_id": media["id"],
        "order_batch_id": batch["id"],
        "superseded_media_order_id": superseded[-1]["id"] if superseded else None,
        "quantity": values["quantity"],
        "coverage_start_at": body["coverage_start_at"],
        "coverage_end_at": body["coverage_end_at"],
        "_coverage_start_at": start,
        "_coverage_end_at": end,
        "unit_price_cents_snapshot": media["unit_price_cents"],
        "line_gross_cents": 0,
        "line_surcharge_cents": 0,
        "line_total_cents": 0,
        "status": "PENDING",
        "tracking_ref": None,
        "undelivered_reason": None,
        "replacement_count": 0,
        "replacement_fee_charged_cents": 0,
    }
    stamp_new(row)
    store.media_orders[row["id"]] = row

    recompute_line_count(batch)
    for prior_batch in touched_batches:
        recompute_line_count(prior_batch)
        if maybe_reconcile_batch(prior_batch):
            bump(prior_batch)

    rederive_fulfillment(election)
    bump(election)
    return created_response(serialize.media_order(row))


@bp.get("/benefits/media-orders/<order_id>")
def read_media_order(order_id):
    authenticate(["ProgramAdmin", "OrderDesk", "Employee"])
    row = resolve_order(order_id)
    return object_response(serialize.media_order(row))


@bp.get("/benefits/media-orders")
def list_media_orders():
    authenticate(["ProgramAdmin", "OrderDesk", "Employee"])
    election_id = str_filter("election_id")
    media_id = str_filter("transit_media_id")
    batch_id = str_filter("order_batch_id")
    superseded_id = str_filter("superseded_media_order_id")
    status = enum_filter("status", MEDIA_ORDER_STATUSES)
    limit, offset = pagination()
    rows = []
    for row in store.media_orders.values():
        if election_id is not None and row["election_id"] != election_id:
            continue
        if media_id is not None and row["transit_media_id"] != media_id:
            continue
        if batch_id is not None and row["order_batch_id"] != batch_id:
            continue
        if superseded_id is not None and \
                row["superseded_media_order_id"] != superseded_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.media_order(r) for r in page], limit, offset, total)


@bp.post("/benefits/media-orders/<order_id>/ship")
def ship_media_order(order_id):
    authenticate(["OrderDesk"])
    row = resolve_order(order_id)
    _body, values = parse_body([field("tracking_ref", "string", required=True,
                                      min_len=1)])
    require_not_terminal(row, "status", TERMINAL_MEDIA_ORDER, "MediaOrder")
    media = store.transit_media.get(row["transit_media_id"])
    batch = store.order_batches.get(row["order_batch_id"])
    require_transition(row["status"] == "SUBMITTED",
                       "MediaOrder %s cannot be shipped from status %s."
                       % (row["id"], row["status"]))
    require_transition(media is not None and media["requires_physical_fulfillment"],
                       "MediaOrder %s references transit media that requires no "
                       "physical fulfillment." % row["id"])
    require_transition(batch is not None and
                       batch["status"] in ("RELEASED", "RECONCILED"),
                       "MediaOrder %s cannot be shipped because its batch has not "
                       "been released." % row["id"])
    row["status"] = "SHIPPED"
    row["tracking_ref"] = values["tracking_ref"]
    bump(row)
    election = store.elections.get(row["election_id"])
    if election is not None:
        rederive_fulfillment(election)
        bump(election)
    return object_response(serialize.media_order(row))


@bp.post("/benefits/media-orders/<order_id>/confirm-delivery")
def confirm_media_delivery(order_id):
    principal = authenticate(["OrderDesk", "Employee"])
    row = resolve_order(order_id)
    require_employee_scope(principal, owner_of_media_order(row))
    require_not_terminal(row, "status", TERMINAL_MEDIA_ORDER, "MediaOrder")
    require_transition(row["status"] == "SHIPPED",
                       "MediaOrder %s cannot be confirmed delivered from status %s."
                       % (row["id"], row["status"]))
    row["status"] = "DELIVERED"
    bump(row)
    election = store.elections.get(row["election_id"])
    if election is not None:
        rederive_fulfillment(election)
        bump(election)
    batch = store.order_batches.get(row["order_batch_id"])
    if maybe_reconcile_batch(batch):
        bump(batch)
    return object_response(serialize.media_order(row))


@bp.post("/benefits/media-orders/<order_id>/report-undelivered")
def report_media_undelivered(order_id):
    principal = authenticate(["Employee", "OrderDesk"])
    row = resolve_order(order_id)
    _body, values = parse_body([field("reason", "enum", required=True,
                                      choices=UNDELIVERED_REASONS)])
    require_employee_scope(principal, owner_of_media_order(row))
    require_not_terminal(row, "status", TERMINAL_MEDIA_ORDER, "MediaOrder")
    require_transition(row["status"] in ("SHIPPED", "DELIVERED"),
                       "MediaOrder %s cannot be reported undelivered from status %s."
                       % (row["id"], row["status"]))
    row["status"] = "UNDELIVERED"
    row["undelivered_reason"] = values["reason"]
    bump(row)
    election = store.elections.get(row["election_id"])
    if election is not None:
        rederive_fulfillment(election)
        bump(election)
    return object_response(serialize.media_order(row))


@bp.post("/benefits/media-orders/<order_id>/reissue")
def reissue_media_order(order_id):
    authenticate(["OrderDesk"])
    row = resolve_order(order_id)
    _body, values = parse_body([field("waive_replacement_fee", "boolean",
                                      default=False)])
    waive = values["waive_replacement_fee"]
    require_not_terminal(row, "status", TERMINAL_MEDIA_ORDER, "MediaOrder")
    require_transition(row["status"] == "UNDELIVERED",
                       "MediaOrder %s cannot be reissued from status %s."
                       % (row["id"], row["status"]))
    if row["replacement_count"] >= MEDIA_REISSUE_LIMIT:
        fail("ERR_REISSUE_LIMIT_EXCEEDED",
             "MediaOrder %s has already been reissued the maximum number of "
             "times." % row["id"])
    if waive and row["undelivered_reason"] not in WAIVABLE_UNDELIVERED_REASONS:
        fail("ERR_REPLACEMENT_FEE_NOT_WAIVABLE",
             "The replacement fee may only be waived when the media never "
             "arrived.")

    media = store.transit_media.get(row["transit_media_id"])
    fee = replacement_fee(row, media, waive)
    row["replacement_count"] += 1
    row["replacement_fee_charged_cents"] += fee
    row["status"] = "SUBMITTED"
    row["tracking_ref"] = None
    bump(row)

    election = store.elections.get(row["election_id"])
    if fee > 0 and election is not None:
        account = store.benefit_accounts.get(election["benefit_account_id"])
        if account is not None:
            account["fee_charged_cents"] += fee
            post_entry(account, "REPLACEMENT_FEE", -fee, "MediaOrder", row["id"],
                       "Replacement fee for a reissued media order.")
            bump(account)
    if election is not None:
        rederive_fulfillment(election)
        bump(election)
    return object_response(serialize.media_order(row))

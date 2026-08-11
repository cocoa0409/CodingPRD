"""Case aggregates, receipt lines and substitution offers (9 endpoints)."""

from flask import Blueprint

from core import clock, serialize
from core.constants import OFFER_STATUSES, ROLES
from core.envelope import created, ok, page
from core.errors import ApiError
from core.ladder import (body_fk, endpoint, enum_filter, free_filter,
                         gate_cycle_closed, gate_membership, gate_posted_ledger,
                         pagination, path_row, req_id, req_int, rung_occ,
                         rung_order_owner)
from core.serialize import exception_state
from core.store import DB, touch
from services import receiving, recompute, substitution

bp = Blueprint("receiving", __name__)
R5 = list(ROLES)


# ------------------------------------------------------- case aggregates ----

@bp.get("/case-aggregates")
@endpoint(R5)
def list_case_aggregates(ctx):
    limit, offset = pagination(ctx)
    route_run_id = free_filter(ctx, "route_run_id")
    item_id = free_filter(ctx, "item_id")
    overage = free_filter(ctx, "overage_order_line_id")
    rows = []
    for row in DB.all("CaseAggregate"):
        if route_run_id is not None and row["route_run_id"] != route_run_id:
            continue
        if item_id is not None and row["item_id"] != item_id:
            continue
        if overage is not None and row["overage_order_line_id"] != overage:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/case-aggregates/<case_aggregate_id>")
@endpoint(R5)
def read_case_aggregate(ctx, case_aggregate_id):
    return ok(serialize.case_aggregate(path_row("case_aggregate_id", case_aggregate_id)))


# ---------------------------------------------------------- receipt lines ---

@bp.post("/receipt-lines")
@endpoint(["ClubAdmin", "WarehouseOperator"])
def create_receipt_line(ctx):
    route_run = body_fk(ctx, "route_run_id")               # rung 5
    aggregate = body_fk(ctx, "case_aggregate_id")
    substitute_item = body_fk(ctx, "substitute_item_id")
    req_id(ctx, "route_run_id")                            # rung 7
    req_id(ctx, "case_aggregate_id")
    cases_received = req_int(ctx, "cases_received", minimum=0)
    req_int(ctx, "expected_route_run_version")
    gate_cycle_closed(route_run)                           # rung 9
    gate_posted_ledger(*recompute.drop_runs_of_route_run(route_run))   # rung 12
    if route_run["status"] != "RECEIVED":                  # rung 19
        raise ApiError("ERR_INVALID_ROUTE_RUN_STATE")
    rung_occ(ctx, "expected_route_run_version", route_run)  # rung 25
    units = receiving.units_for_cases(aggregate, cases_received, substitute_item)
    if aggregate["units_received"] + units > aggregate["covered_units"]:   # rung 42
        raise ApiError("ERR_RECEIPT_EXCEEDS_ORDERED")
    substitute_price = ctx.body.get("substitute_case_price_cents")         # rung 43
    if substitute_item is not None:
        if not isinstance(substitute_price, int) or isinstance(substitute_price, bool) \
                or substitute_price < 1:
            raise ApiError("ERR_VALIDATION",
                           "substitute_case_price_cents must accompany substitute_item_id.")
    elif substitute_price is not None:
        raise ApiError("ERR_VALIDATION",
                       "substitute_case_price_cents may not be supplied without "
                       "substitute_item_id.")
    row = receiving.record_receipt(route_run, aggregate, cases_received,
                                   substitute_item, substitute_price, ctx.user_id)
    return created(serialize.receipt_line(row))


@bp.get("/receipt-lines")
@endpoint(R5)
def list_receipt_lines(ctx):
    limit, offset = pagination(ctx)
    route_run_id = free_filter(ctx, "route_run_id")
    case_aggregate_id = free_filter(ctx, "case_aggregate_id")
    substitute_item_id = free_filter(ctx, "substitute_item_id")
    rows = []
    for row in DB.all("ReceiptLine"):
        if route_run_id is not None and row["route_run_id"] != route_run_id:
            continue
        if case_aggregate_id is not None and row["case_aggregate_id"] != case_aggregate_id:
            continue
        if substitute_item_id is not None and row["substitute_item_id"] != substitute_item_id:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/receipt-lines/<receipt_line_id>")
@endpoint(R5)
def read_receipt_line(ctx, receipt_line_id):
    return ok(serialize.receipt_line(path_row("receipt_line_id", receipt_line_id)))


# ---------------------------------------------------- substitution offers ---

@bp.get("/substitution-offers")
@endpoint(R5)
def list_substitution_offers(ctx):
    limit, offset = pagination(ctx)
    status = enum_filter(ctx, "status", OFFER_STATUSES)
    order_line_id = free_filter(ctx, "order_line_id")
    receipt_line_id = free_filter(ctx, "receipt_line_id")
    substitute_item_id = free_filter(ctx, "substitute_item_id")
    rows = []
    for row in DB.all("SubstitutionOffer"):
        if order_line_id is not None and row["order_line_id"] != order_line_id:
            continue
        if receipt_line_id is not None and row["receipt_line_id"] != receipt_line_id:
            continue
        if substitute_item_id is not None and row["substitute_item_id"] != substitute_item_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/substitution-offers/<substitution_offer_id>")
@endpoint(R5)
def read_substitution_offer(ctx, substitution_offer_id):
    return ok(serialize.substitution_offer(
        path_row("substitution_offer_id", substitution_offer_id)))


def _respond_prelude(ctx, substitution_offer_id):
    offer = path_row("substitution_offer_id", substitution_offer_id)   # rung 4
    line = DB.get("OrderLine", offer["order_line_id"])
    order = DB.get("MemberOrder", line["member_order_id"])
    gate_cycle_closed(offer)                               # rung 9
    gate_membership(DB.get("Member", order["member_id"]))  # rung 10
    # FRICTION 3 and 4 — rung 13's own applies_to list omits the substitution
    # responses, so the cycle-lock gate is not evaluated here; the operative
    # clock is rung 38's exception_state, which is where both the rung and the
    # transition precondition agree.
    if offer["status"] != "PENDING":                       # rung 20
        raise ApiError("ERR_INVALID_OFFER_STATE")
    rung_order_owner(ctx, order)                           # rung 26
    cycle = DB.get("Cycle", DB.get("DropRun", order["drop_run_id"])["cycle_id"])
    if exception_state(cycle) != "OPEN":                   # rung 38
        raise ApiError("ERR_EXCEPTION_WINDOW_CLOSED")
    if clock.now() >= clock.parse(offer["respond_by"]):
        raise ApiError("ERR_EXCEPTION_WINDOW_CLOSED")
    return offer, line


@bp.post("/substitution-offers/<substitution_offer_id>/approve")
@endpoint(["Member"])
def approve_offer(ctx, substitution_offer_id):
    offer, line = _respond_prelude(ctx, substitution_offer_id)
    offer["status"] = "APPROVED"
    touch(offer)
    substitution.apply_substitute(offer, line)
    return ok(serialize.substitution_offer(offer))


@bp.post("/substitution-offers/<substitution_offer_id>/decline")
@endpoint(["Member"])
def decline_offer(ctx, substitution_offer_id):
    offer, line = _respond_prelude(ctx, substitution_offer_id)
    offer["status"] = "DECLINED"
    touch(offer)
    substitution.apply_removal(offer, line)
    return ok(serialize.substitution_offer(offer))

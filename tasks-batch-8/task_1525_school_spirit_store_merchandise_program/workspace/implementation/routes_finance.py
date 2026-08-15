"""Exchange requests (open / decision / complete), activity accounts, and
allocation runs (waterfall computation, post, reverse)."""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

from flask import Blueprint, request

from core import (AD, SM, TRE, CUST, ApiError, DB,
                  ERR_ACCOUNT_NF, ERR_ALLOCATION_EXCEEDS, ERR_EXCHANGE_MISMATCH,
                  ERR_EXCHANGE_NF, ERR_EXCHANGE_WINDOW_CLOSED,
                  ERR_INSUFFICIENT_STOCK, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                  ERR_ORDER_NF, ERR_PAYMENT_MISMATCH, ERR_PROGRAM_NF,
                  ERR_PROGRAM_NOT_CLOSED, ERR_ROLE, ERR_RUN_NF, ERR_VARIANT_NF,
                  auth, body, dec, fetch, fetch_scoped, gate_active,
                  gate_closed, is_int, is_num, list_response, need_role,
                  new_entity, now_logical, pub, req_fields, req_int, success,
                  touch)

bp = Blueprint("finance", __name__)


# ---------------------------------------------------------- ExchangeRequest --
@bp.post("/spirit-store/exchanges")
def create_exchange():
    auth()
    uid, role = auth()
    need_role(role, CUST, TRE)
    data = body()
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    order = None
    if data.get("order_id") is not None:
        order = fetch_scoped("orders", data["order_id"], ERR_ORDER_NF,
                             data.get("program_id"))
    original = None
    if data.get("original_variant_id") is not None:
        original = fetch_scoped("variants", data["original_variant_id"],
                                ERR_VARIANT_NF, data.get("program_id"))
    new_variant = None
    if data.get("new_variant_id") is not None:
        new_variant = fetch_scoped("variants", data["new_variant_id"],
                                   ERR_VARIANT_NF, data.get("program_id"))
    # Customer ownership: X-User-ID must equal the exchanged order's customer.
    if role == CUST and order is not None and uid != order["customer_user_id"]:
        raise ApiError(ERR_ROLE, 403,
                       "customers may only open exchanges on their own "
                       "orders")
    req_fields(data, "program_id", "order_id", "original_variant_id",
               "new_variant_id")
    gate_active(program)
    # The order must be fulfilled: POS orders are fulfilled at sale, online
    # orders at pickup.
    if order["fulfillment_status"] not in ("POS_FULFILLED", "PICKED_UP"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "exchanges require a fulfilled order")
    # Exchange window (temporal): within exchange_window_days of fulfillment,
    # the final day still counts.
    base = order["_fulfilled_instant"]
    if base is None or now_logical() > base + timedelta(
            days=program["exchange_window_days"]):
        raise ApiError(ERR_EXCHANGE_WINDOW_CLOSED, 422,
                       "the exchange window has closed")
    # Constraints: original variant must appear in the order's lines; new
    # variant must share the design and differ in size.
    original_line = None
    for line in order["lines"]:
        if line["variant_id"] == original["id"]:
            original_line = line
            break
    if (original_line is None
            or new_variant["design_id"] != original["design_id"]
            or new_variant["size"] == original["size"]):
        raise ApiError(ERR_EXCHANGE_MISMATCH, 422,
                       "exchange requires the original variant in the order "
                       "and a new variant of the same design but a "
                       "different size")
    exchange = new_entity({
        "program_id": program["id"],
        "order_id": order["id"],
        "original_variant_id": original["id"],
        "new_variant_id": new_variant["id"],
        "status": "PENDING",
        # differential = new list price - unit price captured on the line.
        "differential_cents": (new_variant["unit_price_cents"]
                               - original_line["unit_price_cents"]),
        "condition": None,
    })
    DB["exchanges"][exchange["id"]] = exchange
    return success(pub(exchange), code=201)


@bp.get("/spirit-store/exchanges")
def list_exchanges():
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, CUST)
    items = list(DB["exchanges"].values())
    for param in ("program_id", "order_id", "original_variant_id",
                  "new_variant_id"):
        value = request.args.get(param)
        if value is not None:
            items = [e for e in items if e[param] == value]
    return list_response(items, pub)


@bp.get("/spirit-store/exchanges/<exchangeId>")
def get_exchange(exchangeId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, CUST)
    return success(pub(fetch("exchanges", exchangeId, ERR_EXCHANGE_NF)))


@bp.post("/spirit-store/exchanges/<exchangeId>/decision")
def exchange_decision(exchangeId):
    auth()
    uid, role = auth()
    need_role(role, TRE)
    exchange = fetch("exchanges", exchangeId, ERR_EXCHANGE_NF)
    data = body()
    req_fields(data, "decision")
    decision = data["decision"]
    if decision not in ("APPROVED", "REJECTED"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "decision must be APPROVED or REJECTED")
    program = DB["programs"].get(exchange["program_id"])
    gate_active(program)
    if exchange["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a PENDING exchange can be decided")
    if decision == "APPROVED":
        new_variant = DB["variants"].get(exchange["new_variant_id"])
        available = (new_variant["on_hand_qty"]
                     - new_variant["reserved_online_qty"])
        if available < 1:
            raise ApiError(ERR_INSUFFICIENT_STOCK, 422,
                           "the new variant has no available stock")
        # Hold one unit of the new variant for the swap.
        new_variant["reserved_online_qty"] += 1
        touch(new_variant)
        exchange["status"] = "APPROVED"
    else:
        exchange["status"] = "REJECTED"
    touch(exchange)
    return success(pub(exchange))


@bp.post("/spirit-store/exchanges/<exchangeId>/complete")
def exchange_complete(exchangeId):
    auth()
    uid, role = auth()
    need_role(role, TRE)
    exchange = fetch("exchanges", exchangeId, ERR_EXCHANGE_NF)
    data = body()
    req_fields(data, "condition")
    condition = data["condition"]
    if condition not in ("RESALEABLE", "DAMAGED"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "condition must be RESALEABLE or DAMAGED")
    program = DB["programs"].get(exchange["program_id"])
    gate_active(program)
    if exchange["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an APPROVED exchange can be completed")
    differential = exchange["differential_cents"]
    collected = data.get("amount_collected_cents")
    if differential > 0:
        # A positive differential must be collected exactly.
        if not is_int(collected) or collected != differential:
            raise ApiError(ERR_PAYMENT_MISMATCH, 422,
                           "amount_collected_cents must equal the positive "
                           "differential")
    elif collected is not None and (not is_int(collected) or collected < 0):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "amount_collected_cents must be a non-negative "
                       "integer")
    original = DB["variants"].get(exchange["original_variant_id"])
    new_variant = DB["variants"].get(exchange["new_variant_id"])
    # Returned unit: RESALEABLE goes back on the shelf; DAMAGED is written
    # off (no restock).
    if condition == "RESALEABLE":
        original["on_hand_qty"] += 1
        original["_consumed"] -= 1
        touch(original)
    # The held new unit leaves the shelf.
    new_variant["reserved_online_qty"] -= 1
    new_variant["on_hand_qty"] -= 1
    new_variant["_consumed"] += 1
    touch(new_variant)
    if differential < 0:
        # Refund owed against the original order.
        order = DB["orders"].get(exchange["order_id"])
        order["refunded_cents"] += -differential
        if order["refunded_cents"] >= order["total_cents"]:
            order["payment_status"] = "REFUNDED"
        else:
            order["payment_status"] = "PARTIALLY_REFUNDED"
        touch(order)
    exchange["condition"] = condition
    exchange["status"] = "COMPLETED"
    touch(exchange)
    return success(pub(exchange))


# ---------------------------------------------------------- ActivityAccount --
@bp.post("/spirit-store/activity-accounts")
def create_account():
    auth()
    uid, role = auth()
    need_role(role, AD)
    data = body()
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    req_fields(data, "program_id", "name", "allocation_weight")
    weight = data["allocation_weight"]
    if not is_num(weight) or weight <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "allocation_weight must be a number > 0")
    cap = data.get("cap_cents")
    if cap is not None and (not is_int(cap) or cap < 0):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "cap_cents must be null or an integer >= 0")
    account = new_entity({
        "program_id": program["id"],
        "name": data["name"],
        "allocation_weight": weight,
        "cap_cents": cap,
        "balance_cents": 0,
    })
    DB["accounts"][account["id"]] = account
    return success(pub(account), code=201)


@bp.get("/spirit-store/activity-accounts")
def list_accounts():
    auth()
    uid, role = auth()
    need_role(role, AD, TRE)
    items = list(DB["accounts"].values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [a for a in items if a["program_id"] == pid]
    return list_response(items, pub)


@bp.get("/spirit-store/activity-accounts/<accountId>")
def get_account(accountId):
    auth()
    uid, role = auth()
    need_role(role, AD, TRE)
    return success(pub(fetch("accounts", accountId, ERR_ACCOUNT_NF)))


# ------------------------------------------------------------ AllocationRun --
def waterfall(distributable, accounts):
    """§3.8 waterfall: floor shares, cap overflow redistribution, dust to the
    largest-weight eligible account (tie: created_at ascending)."""
    weights = {a["id"]: dec(a["allocation_weight"]) for a in accounts}
    total_weight = sum(weights.values())
    headroom = {}
    for a in accounts:
        if a["cap_cents"] is None:
            headroom[a["id"]] = None  # uncapped
        else:
            headroom[a["id"]] = max(0, a["cap_cents"] - a["balance_cents"])
    credit = {}
    capped_flag = {}
    if not accounts:
        return []
    for a in accounts:
        raw = int((Decimal(distributable) * weights[a["id"]]
                   / total_weight).to_integral_value(rounding=ROUND_FLOOR))
        if headroom[a["id"]] is None:
            credit[a["id"]] = raw
            capped_flag[a["id"]] = False
        else:
            credit[a["id"]] = min(raw, headroom[a["id"]])
            capped_flag[a["id"]] = raw > headroom[a["id"]]
        a["_raw_share"] = raw
    overflow = sum(max(0, a["_raw_share"] - credit[a["id"]])
                   for a in accounts)
    # Redistribute overflow iteratively among still-eligible accounts.
    while overflow > 0:
        recipients = [a for a in accounts
                      if headroom[a["id"]] is None
                      or credit[a["id"]] < headroom[a["id"]]]
        if not recipients:
            break  # unplaceable remainder stays in undistributed profit
        recip_weight = sum(weights[a["id"]] for a in recipients)
        moved = 0
        for a in recipients:
            share = int((Decimal(overflow) * weights[a["id"]]
                         / recip_weight).to_integral_value(
                             rounding=ROUND_FLOOR))
            if headroom[a["id"]] is not None:
                grant = min(share, headroom[a["id"]] - credit[a["id"]])
                if grant < share:
                    capped_flag[a["id"]] = True
            else:
                grant = share
            credit[a["id"]] += grant
            moved += grant
        overflow -= moved
        if moved == 0:
            break
    # Dust from flooring goes to the eligible account with the largest
    # weight; ties break by created_at ascending (i.e. _seq ascending).
    dust = distributable - sum(credit.values())
    if dust > 0:
        eligible = [a for a in accounts
                    if headroom[a["id"]] is None
                    or credit[a["id"]] < headroom[a["id"]]]
        if eligible:
            eligible.sort(key=lambda a: (-a["allocation_weight"], a["_seq"]))
            pick = eligible[0]
            grant = dust
            if headroom[pick["id"]] is not None:
                grant = min(dust, headroom[pick["id"]] - credit[pick["id"]])
            credit[pick["id"]] += grant
    lines = []
    for a in accounts:
        lines.append({"account_id": a["id"],
                      "credit_cents": credit[a["id"]],
                      "capped": capped_flag[a["id"]]})
        del a["_raw_share"]
    return lines


@bp.post("/spirit-store/allocation-runs")
def create_run():
    auth()
    uid, role = auth()
    need_role(role, TRE)
    data = body()
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    req_fields(data, "program_id", "distributable_cents")
    distributable = req_int(data, "distributable_cents")
    # Fiscal: at least 1 and no more than the program's undistributed profit.
    if (distributable < 1
            or distributable > program["undistributed_profit_cents"]):
        raise ApiError(ERR_ALLOCATION_EXCEEDS, 422,
                       "distributable_cents must be >= 1 and within the "
                       "program's undistributed profit")
    accounts = [a for a in DB["accounts"].values()
                if a["program_id"] == program["id"]]
    lines = waterfall(distributable, accounts)
    run = new_entity({
        "program_id": program["id"],
        "distributable_cents": distributable,
        "status": "DRAFT",
        "lines": lines,
        "posted_at": None,
    })
    DB["runs"][run["id"]] = run
    return success(pub(run), code=201)


@bp.get("/spirit-store/allocation-runs")
def list_runs():
    auth()
    uid, role = auth()
    need_role(role, AD, TRE)
    items = list(DB["runs"].values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [r for r in items if r["program_id"] == pid]
    return list_response(items, pub)


@bp.get("/spirit-store/allocation-runs/<runId>")
def get_run(runId):
    auth()
    uid, role = auth()
    need_role(role, AD, TRE)
    return success(pub(fetch("runs", runId, ERR_RUN_NF)))


@bp.post("/spirit-store/allocation-runs/<runId>/post")
def post_run(runId):
    auth()
    uid, role = auth()
    need_role(role, TRE)
    run = fetch("runs", runId, ERR_RUN_NF)
    program = DB["programs"].get(run["program_id"])
    # Posting requires the program CLOSED (program gate, pipeline step 6).
    gate_closed(program)
    if run["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT allocation run can be posted")
    total = 0
    for line in run["lines"]:
        account = DB["accounts"].get(line["account_id"])
        if account is not None:
            account["balance_cents"] += line["credit_cents"]
            touch(account)
        total += line["credit_cents"]
    program["undistributed_profit_cents"] -= total
    program["distributed_profit_cents"] += total
    touch(program)
    run["status"] = "POSTED"
    run["posted_at"] = now_logical()
    touch(run)
    return success(pub(run))


@bp.post("/spirit-store/allocation-runs/<runId>/reverse")
def reverse_run(runId):
    auth()
    uid, role = auth()
    need_role(role, TRE)
    run = fetch("runs", runId, ERR_RUN_NF)
    program = DB["programs"].get(run["program_id"])
    if run["status"] != "POSTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a POSTED allocation run can be reversed")
    total = 0
    for line in run["lines"]:
        account = DB["accounts"].get(line["account_id"])
        if account is not None:
            account["balance_cents"] -= line["credit_cents"]
            touch(account)
        total += line["credit_cents"]
    program["undistributed_profit_cents"] += total
    program["distributed_profit_cents"] -= total
    touch(program)
    run["status"] = "REVERSED"
    touch(run)
    return success(pub(run))

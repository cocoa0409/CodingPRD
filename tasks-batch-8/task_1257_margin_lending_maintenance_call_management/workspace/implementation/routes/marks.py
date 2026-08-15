"""Price marks and the official-close cascade (PRD 3.3).

REALTIME marks update mv_realtime on positions in the security and recompute
realtime fields of holders — nothing more. OFFICIAL_CLOSE marks additionally
run the full call evaluation: issue new calls (flipping accounts ACTIVE ->
RESTRICTED) and cure satisfied OPEN calls with MARKET_RECOVERY.
"""
from flask import Blueprint, request

from authz import ANY_ROLE, MARKET_OPS, require_roles
from calc import compute_basis, compute_buying_power
from cascades import recompute_and_evaluate
from db import store
from errors import invalid_mark, mark_not_found
from response import success
from serialize import ser_mark
from store_ops import (
    json_body,
    new_id,
    paginate,
    req_enum,
    req_int,
    req_str,
    sorted_by_creation,
    stamp_ledger,
    touch,
)
from routes.securities import get_security_or_404

bp = Blueprint("marks", __name__)

MARK_TYPES = ("REALTIME", "OFFICIAL_CLOSE")


@bp.route("/margin/market-marks", methods=["POST"])
def post_mark():
    data = json_body()
    security_id = req_str(data, "security_id")
    mark_type = req_enum(data, "mark_type", MARK_TYPES)
    price = req_int(data, "price_cents")
    require_roles([MARKET_OPS])
    get_security_or_404(security_id)  # body reference resolves (PRD 2.9)
    # Priority 9: mark prices must be positive.
    if price <= 0:
        raise invalid_mark()

    mark = {
        "id": new_id(),
        "security_id": security_id,
        "mark_type": mark_type,
        "price_cents": price,
        "marked_at": store.clock,
    }
    stamp_ledger(mark)
    store.marks[mark["id"]] = mark

    # Update the mv field on every position in this security (positions keep
    # both bases in sync with the latest marks).
    mv_field = "mv_realtime_cents" if mark_type == "REALTIME" else "mv_official_cents"
    affected_accounts = {}
    for p in store.positions.values():
        if p["security_id"] != security_id:
            continue
        if p[mv_field] != p["quantity"] * price:
            p[mv_field] = p["quantity"] * price
            touch(p)
        affected_accounts[p["account_id"]] = True

    for account_id in sorted(affected_accounts,
                             key=lambda aid: store.accounts[aid]["_seq"]):
        account = store.accounts[account_id]
        if account["account_status"] == "CLOSED":
            continue
        if mark_type == "REALTIME":
            # Realtime basis only: equity_rt, requirement_rt, buying power.
            rt = compute_basis(account, "REALTIME", write_mv=True)
            account["equity_realtime_cents"] = rt.equity
            account["reg_req_realtime_cents"] = rt.reg_req
            account["house_req_realtime_cents"] = rt.house_req
            account["buying_power_cents"] = compute_buying_power(account, rt)
            touch(account)
        else:
            # Official close: full recompute plus the call evaluation cascade.
            recompute_and_evaluate(account)

    return success(ser_mark(mark), status=201)


@bp.route("/margin/market-marks/<mid>", methods=["GET"])
def get_mark(mid):
    require_roles(ANY_ROLE)
    mark = store.marks.get(mid)
    if mark is None:
        raise mark_not_found()
    return success(ser_mark(mark))


@bp.route("/margin/market-marks", methods=["GET"])
def list_marks():
    require_roles(ANY_ROLE)
    security_id = request.args.get("security_id")
    mark_type = request.args.get("mark_type")
    items = list(store.marks.values())
    if security_id is not None:
        items = [m for m in items if m["security_id"] == security_id]
    if mark_type is not None:
        items = [m for m in items if m["mark_type"] == mark_type]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_mark(m) for m in page], response_type="array",
                   pagination=pagination)

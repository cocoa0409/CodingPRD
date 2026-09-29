"""Points liability snapshots (PRD 3.11)."""

from flask import Blueprint, request

from auth import caller_id, endpoint
from core import clock_dt, fmt_dt, must_find, new_row, ok, store
from errors import ApiError
from shapes import body, req_dt, req_enum
from svc_liability import compute
from views import ADMIN, FINANCE_READ, listing, plain

bp = Blueprint("liability", __name__)

METHODS = ("COST_BASIS", "FAIR_VALUE")


@bp.post("/liability-snapshots")
@endpoint(ADMIN)
def create_snapshot():
    data = body()
    as_of = req_dt(data, "as_of")
    method = req_enum(data, "method", METHODS)
    if as_of > clock_dt():
        raise ApiError(
            "ERR_SNAPSHOT_AS_OF_IN_FUTURE",
            "The snapshot cut-off may not be in the future.",
        )
    figures = compute(method, fmt_dt(as_of))
    row = new_row(
        "snapshots",
        {
            "as_of": fmt_dt(as_of),
            "method": method,
            "gross_outstanding_points": figures["gross_outstanding_points"],
            "dormant_outstanding_points": figures["dormant_outstanding_points"],
            "blended_cost_per_1k_cents": figures["blended_cost_per_1k_cents"],
            "effective_breakage_rate_bps": figures["effective_breakage_rate_bps"],
            "gross_liability_cents": figures["gross_liability_cents"],
            "breakage_credit_cents": figures["breakage_credit_cents"],
            "net_liability_cents": figures["net_liability_cents"],
            "generated_by_user_id": caller_id(),
        },
        audit=False,
    )
    store("snapshots", row)
    return ok(plain(row), 201)


@bp.get("/liability-snapshots/<snapshot_id>")
@endpoint(FINANCE_READ)
def read_snapshot(snapshot_id):
    return ok(plain(must_find("snapshots", snapshot_id)))


@bp.get("/liability-snapshots")
@endpoint(FINANCE_READ)
def list_snapshots():
    args = request.args
    return listing("snapshots", args, {"method": args.get("method")})

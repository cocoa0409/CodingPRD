from flask import Blueprint, request

import auth
import calcs
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("bridge_letters", __name__)


@bp.post("/soc/bridge-letters")
def create_letter():
    auth.authenticate({"AccountExecutive"})
    body = auth.body()
    engagement = v.fk(body, "engagement_id", "engagements")
    v.fk(body, "supersedes_bridge_letter_id", "bridge_letters")
    v.req_id(body, "engagement_id")
    coverage_start = v.req_dt(body, "coverage_start")
    as_of_date = v.req_dt(body, "as_of_date")
    supersedes = v.opt_id(body, "supersedes_bridge_letter_id")

    obs_end = store.parse_iso(engagement["observation_period_end"])
    if coverage_start < obs_end:
        raise ApiError("ERR_VALIDATION")
    if as_of_date < coverage_start:
        raise ApiError("ERR_VALIDATION")
    coverage_days = calcs.bridge_coverage_days(coverage_start, as_of_date)
    if coverage_days > calcs.MAX_BRIDGE_DAYS:
        raise ApiError("ERR_VALIDATION")

    row = store.new_row(
        "bridge_letters",
        {
            "engagement_id": engagement["id"],
            "coverage_start": store.fmt_iso(coverage_start),
            "as_of_date": store.fmt_iso(as_of_date),
            "status": "DRAFT",
            "supersedes_bridge_letter_id": supersedes,
            "coverage_days": coverage_days,
            "issued_at": None,
            "issued_by_user_id": None,
        },
    )
    return ok(store.public(row), 201)


@bp.get("/soc/bridge-letters/<bridge_letter_id>")
def read_letter(bridge_letter_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("bridge_letters", bridge_letter_id)
    return ok(store.public(row))


@bp.get("/soc/bridge-letters")
def list_letters():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("bridge_letters")
    for key in ("engagement_id", "status", "supersedes_bridge_letter_id"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/bridge-letters/<bridge_letter_id>/issue")
def issue_letter(bridge_letter_id):
    user_id, _role = auth.authenticate({"AccountExecutive"})
    row = store.get_or_404("bridge_letters", bridge_letter_id)
    engagement = DB["engagements"][row["engagement_id"]]

    services.require_phase(engagement, {"ISSUED"})
    services.require_not_frozen(engagement)
    services.require_posture_open(engagement)

    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    delivered = any(
        d["engagement_id"] == engagement["id"] and d["status"] == "DELIVERED"
        for d in DB["report_distributions"].values()
    )
    if not delivered:
        raise ApiError("ERR_REPORT_NOT_DELIVERED")

    start = store.parse_iso(row["coverage_start"])
    end = store.parse_iso(row["as_of_date"])
    for other in DB["bridge_letters"].values():
        if other["id"] == row["id"]:
            continue
        if other["engagement_id"] != engagement["id"] or other["status"] != "ISSUED":
            continue
        o_start = store.parse_iso(other["coverage_start"])
        o_end = store.parse_iso(other["as_of_date"])
        if start <= o_end and o_start <= end:
            raise ApiError("ERR_BRIDGE_WINDOW_OVERLAP")

    row["status"] = "ISSUED"
    row["issued_at"] = store.now_iso()
    row["issued_by_user_id"] = user_id
    store.touch(row)

    if row["supersedes_bridge_letter_id"]:
        prior = DB["bridge_letters"].get(row["supersedes_bridge_letter_id"])
        if prior is not None and prior["status"] == "ISSUED":
            prior["status"] = "SUPERSEDED"
            store.touch(prior)
    return ok(store.public(row))

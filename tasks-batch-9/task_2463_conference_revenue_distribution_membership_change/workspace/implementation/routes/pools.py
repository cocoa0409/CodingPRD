"""Revenue pools and the computation of distribution runs (PRD section 3.7)."""

from flask import Blueprint

import calc
import response
import serializers
import validation
from db import base_record, db, touch
from errors import ApiError
from middleware import api, current_user_id, raw_body
from routes import common
from services import distribution

bp = Blueprint("pools", __name__)

POOL_READ_ROLES = (
    "Commissioner",
    "FinanceOfficer",
    "Treasurer",
    "Auditor",
    "PlatformAdmin",
    "MemberRepresentative",
)

POOL_TYPES = ("MEDIA_RIGHTS", "POSTSEASON_UNIT", "CHAMPIONSHIP")
ALLOCATION_METHODS = ("APPEARANCE_PERFORMANCE_WEIGHTED", "EQUAL_SHARE", "UNIT_BASED")

PENDING_APPEARANCE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED")


# ---------------------------------------------------------------------------
# POST /revenue-pools  |  GET /revenue-pools/{id}  |  GET /revenue-pools
# ---------------------------------------------------------------------------


@bp.route("/revenue-pools", methods=["POST"])
@api(("FinanceOfficer",))
def create_pool():
    body = raw_body()
    conference_id = validation.get_id(body, "conference_id")
    fiscal_year = validation.get_int(body, "fiscal_year", minimum=None)
    pool_type = validation.get_enum(body, "pool_type", POOL_TYPES)
    allocation_method = validation.get_enum(body, "allocation_method", ALLOCATION_METHODS)
    gross_revenue_cents = validation.get_int(body, "gross_revenue_cents")
    estimated_expense_cents = validation.get_int(body, "estimated_expense_cents")

    pool = base_record()
    pool.update(
        {
            "conference_id": conference_id,
            "fiscal_year": fiscal_year,
            "pool_type": pool_type,
            "allocation_method": allocation_method,
            "gross_revenue_cents": gross_revenue_cents,
            "estimated_expense_cents": estimated_expense_cents,
            "audited_expense_cents": None,
            "status": "DRAFT",
        }
    )
    db.revenue_pools[pool["id"]] = pool
    return response.single(serializers.revenue_pool(pool), 201)


@bp.route("/revenue-pools/<pool_id>", methods=["GET"])
@api(POOL_READ_ROLES)
def read_pool(pool_id):
    return response.single(serializers.revenue_pool(common.get_pool(pool_id)))


@bp.route("/revenue-pools", methods=["GET"])
@api(POOL_READ_ROLES)
def list_pools():
    criteria = {
        "conference_id": common.string_filter("conference_id"),
        "fiscal_year": common.int_filter("fiscal_year"),
        "pool_type": common.string_filter("pool_type"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        list(db.revenue_pools.values()), serializers.revenue_pool, criteria=criteria
    )


# ---------------------------------------------------------------------------
# The pool status machine
# ---------------------------------------------------------------------------


@bp.route("/revenue-pools/<pool_id>/open", methods=["POST"])
@api(("FinanceOfficer",))
def open_pool(pool_id):
    pool = common.get_pool(pool_id)
    conference = db.conference
    if pool["status"] != "DRAFT":
        raise ApiError("ERR_POOL_STATE_INVALID")
    if conference["governance_status"] != "OPERATING":
        # Only ERR_POOL_STATE_INVALID is declared for this endpoint.
        raise ApiError("ERR_POOL_STATE_INVALID")
    pool["status"] = "OPEN"
    touch(pool)
    return response.single(serializers.revenue_pool(pool))


@bp.route("/revenue-pools/<pool_id>/close-books", methods=["POST"])
@api(("FinanceOfficer",))
def close_pool_books(pool_id):
    pool = common.get_pool(pool_id)
    body = raw_body()
    audited_expense_cents = validation.get_int(body, "audited_expense_cents")

    if pool["status"] != "OPEN":
        raise ApiError("ERR_POOL_STATE_INVALID")
    for appearance in db.bowl_appearances.values():
        if (
            appearance["fiscal_year"] == pool["fiscal_year"]
            and appearance["status"] in PENDING_APPEARANCE_STATUSES
        ):
            raise ApiError("ERR_BOWL_REVIEW_PENDING")

    pool["audited_expense_cents"] = audited_expense_cents
    pool["status"] = "BOOKS_CLOSED"
    touch(pool)
    return response.single(serializers.revenue_pool(pool))


@bp.route("/revenue-pools/<pool_id>/reopen", methods=["POST"])
@api(("FinanceOfficer",))
def reopen_pool(pool_id):
    pool = common.get_pool(pool_id)
    body = raw_body()
    validation.get_optional_str(body, "reason")

    if pool["status"] != "BOOKS_CLOSED":
        raise ApiError("ERR_POOL_STATE_INVALID")
    if _has_posted_run(pool["id"]):
        raise ApiError("ERR_POOL_STATE_INVALID")

    pool["status"] = "OPEN"
    pool["audited_expense_cents"] = None
    distribution.supersede_computed_runs(pool)
    touch(pool)
    return response.single(serializers.revenue_pool(pool))


@bp.route("/revenue-pools/<pool_id>/close", methods=["POST"])
@api(("FinanceOfficer",))
def close_pool(pool_id):
    pool = common.get_pool(pool_id)
    if pool["status"] != "BOOKS_CLOSED":
        raise ApiError("ERR_POOL_STATE_INVALID")
    if not _has_posted_run(pool["id"]):
        raise ApiError("ERR_POOL_STATE_INVALID")
    pool["status"] = "CLOSED"
    touch(pool)
    return response.single(serializers.revenue_pool(pool))


def _has_posted_run(pool_id):
    for run in db.distribution_runs.values():
        if run["revenue_pool_id"] == pool_id and run["status"] == "POSTED":
            return True
    return False


# ---------------------------------------------------------------------------
# POST /revenue-pools/{id}/distribution-runs  |  GET the same
# ---------------------------------------------------------------------------


@bp.route("/revenue-pools/<pool_id>/distribution-runs", methods=["POST"])
@api(("FinanceOfficer",))
def compute_distribution_run(pool_id):
    pool = common.get_pool(pool_id)
    conference = db.conference
    body = raw_body()

    variant = validation.get_enum(body, "variant", ("PROVISIONAL", "FINAL_AUDITED"))
    expected_version = validation.get_int(body, "expected_pool_version", minimum=None)
    memo = validation.get_optional_str(body, "memo")

    if expected_version != pool["version"]:
        raise ApiError("ERR_STALE_POOL_VERSION")

    required_status = "OPEN" if variant == "PROVISIONAL" else "BOOKS_CLOSED"
    if pool["status"] != required_status:
        raise ApiError("ERR_POOL_STATE_INVALID")

    if conference["reserve_posture"] == "FROZEN":
        raise ApiError("ERR_RESERVE_POSTURE_FROZEN")
    if variant == "FINAL_AUDITED" and pool["audited_expense_cents"] is None:
        raise ApiError("ERR_AUDITED_EXPENSE_MISSING")

    run = distribution.compute_run(pool, variant, memo, current_user_id())
    return response.single(serializers.distribution_run(run), 201)


@bp.route("/revenue-pools/<pool_id>/distribution-runs", methods=["GET"])
@api(POOL_READ_ROLES)
def list_pool_distribution_runs(pool_id):
    common.get_pool(pool_id)
    runs = [
        run
        for run in db.distribution_runs.values()
        if run["revenue_pool_id"] == pool_id
    ]
    criteria = {
        "superseded_by_run_id": common.string_filter("superseded_by_run_id"),
        "variant": common.string_filter("variant"),
        "status": common.string_filter("status"),
    }
    return common.listing(runs, serializers.distribution_run, criteria=criteria)

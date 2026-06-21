"""Draw resource: request (atomic disburse-or-reject), read, list.

A Draw is created REQUESTED and, when every precondition passes, disbursed in the
same request (DISBURSED). A non-version *business* precondition failure persists
the draw as REJECTED with no ledger change. Request-shape failures (auth, FK,
missing field, range) and the version/OCC failure persist no draw.
"""
from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, common_create_fields, touch
from middleware import require_role, get_json_body
from response import success, list_response
from services import calculations as calc
from services.jobledger import recompute_remaining
import validators as V

bp = Blueprint("draws", __name__)

ROLE_ALL = {"FieldAdjuster", "Estimator", "ProductionManager"}


def _persist_rejected(job_id, cumulative_pct, expected_version):
    """Record a REJECTED draw (no ledger change) and return it."""
    draw = common_create_fields(versioned=True)
    draw.update({
        "job_id": job_id,
        "cumulative_pct": cumulative_pct,
        "expected_job_version": expected_version,
        "gross_eligible_cents": None,
        "retainage_cents": None,
        "net_disbursed_cents": None,
        "is_final": None,
        "status": "REJECTED",
    })
    db.draws[draw["id"]] = draw
    return draw


@bp.route("/draws", methods=["POST"])
def create_draw():
    require_role({"ProductionManager"})
    body = get_json_body()
    job_id = V.require_field(body, "job_id")
    cumulative_pct = V.require_field(body, "cumulative_pct")
    expected_version = V.require_field(body, "expected_job_version")
    if not isinstance(job_id, str):
        V.missing_field("job_id")

    # FK (priority 4)
    job = V.resolve_fk(db.jobs, job_id)

    # range / type (priority 6)
    if not V.is_number(cumulative_pct):
        V.invalid_request("cumulative_pct must be a number")
    if not V.is_int(expected_version):
        V.invalid_request("expected_job_version must be an integer")
    # cumulative_pct must be in (0, 1]; out of range -> ERR_PCT_OUT_OF_RANGE 422
    if not (0 < cumulative_pct <= 1):
        raise ApiError(errors.ERR_PCT_OUT_OF_RANGE, 422,
                       "cumulative_pct must be in (0, 1]")

    with db.lock:
        # cross-entity (priority 8): job must be IN_PRODUCTION (records REJECTED)
        if job["status"] != "IN_PRODUCTION":
            _persist_rejected(job_id, cumulative_pct, expected_version)
            raise ApiError(errors.ERR_JOB_NOT_IN_PRODUCTION, 409,
                           "Job not IN_PRODUCTION")

        # fiscal (priority 10): pct strictly exceeds billed_pct (records REJECTED)
        if not (cumulative_pct > job["billed_pct"]):
            _persist_rejected(job_id, cumulative_pct, expected_version)
            raise ApiError(errors.ERR_PCT_NOT_INCREASING, 409,
                           "cumulative_pct must strictly exceed billed_pct")

        # OCC (priority 11): version match (does NOT record a REJECTED draw)
        if expected_version != job["version"]:
            raise ApiError(errors.ERR_STALE_JOB_VERSION, 412,
                           "expected_job_version is stale")

        # all preconditions pass -> disburse atomically
        gross_eligible, retainage, net_disbursed, is_final = calc.draw_amounts(
            job["contract_value_cents"], job["disbursed_gross_cents"],
            cumulative_pct, job["retainage_pct"],
        )

        draw = common_create_fields(versioned=True)
        draw.update({
            "job_id": job_id,
            "cumulative_pct": cumulative_pct,
            "expected_job_version": expected_version,
            "gross_eligible_cents": gross_eligible,
            "retainage_cents": retainage,
            "net_disbursed_cents": net_disbursed,
            "is_final": is_final,
            "status": "DISBURSED",
        })
        db.draws[draw["id"]] = draw

        # rewrite the job ledger (cascade)
        job["disbursed_gross_cents"] += gross_eligible
        job["disbursed_net_cents"] += net_disbursed
        job["retainage_held_cents"] += retainage
        job["billed_pct"] = cumulative_pct
        recompute_remaining(job)
        touch(job)  # the OCC bump a subsequent stale draw collides with

        return success(draw, status=201)


@bp.route("/draws/<entity_id>", methods=["GET"])
def get_draw(entity_id):
    require_role(ROLE_ALL)
    ent = V.find_or_404(db.draws, entity_id)
    return success(ent, status=200)


@bp.route("/draws", methods=["GET"])
def list_draws():
    require_role(ROLE_ALL)
    limit, offset = V.parse_pagination()
    items = list(db.draws.values())
    for key in ("job_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return list_response(page, limit, offset, total)

from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import auth
from response import object_response, list_response
from services import calc, domain
from services.query import get_or_404, get_ref_or_404, paginate
from validate import get_body, req_str, req_int, require, pagination_params

bp = Blueprint("estimates", __name__)


def _validate_line_items(raw):
    if not isinstance(raw, list):
        raise err("ERR_INVALID_REQUEST", "line_items must be an array.")
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise err("ERR_INVALID_REQUEST", "Each line item must be an object.")
        qty = entry.get("qty")
        unit_price_cents = entry.get("unit_price_cents")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise err("ERR_INVALID_REQUEST", "line item qty must be an integer.")
        if isinstance(unit_price_cents, bool) or not isinstance(unit_price_cents, int):
            raise err("ERR_INVALID_REQUEST", "line item unit_price_cents must be an integer.")
        if qty < 0 or unit_price_cents < 0:
            raise err("ERR_INVALID_REQUEST", "line item qty/unit_price_cents must be >= 0.")
        lines.append({"qty": qty, "unit_price_cents": unit_price_cents})
    return lines


@bp.route("/restoration/estimates", methods=["POST"])
def create_estimate():
    auth(["Estimator"])
    body = get_body()
    # priority 4: job_id body FK existence.
    job_id = req_str(body, "job_id")
    job = get_ref_or_404(db.jobs, job_id)

    # priority 5: field validity.
    estimated_drying_days = req_int(body, "estimated_drying_days", minimum=0)
    line_items = _validate_line_items(require(body, "line_items"))
    expected_job_version = req_int(body, "expected_job_version")

    # priority 13: OCC on the job version (after field validity).
    if expected_job_version != job["version"]:
        raise err("ERR_STALE_JOB_VERSION",
                  "expected_job_version does not match the current LossJob.version.")

    claim = db.claims.get(job["claim_id"])
    depreciation_pct = claim["depreciation_pct"] if claim is not None else 0
    tax_pct = claim["tax_pct"] if claim is not None else 0

    non_decomm = domain.non_decommissioned_chambers(job_id)
    scope_lines_total_cents = calc.compute_scope_lines_total_cents(line_items)
    equipment_estimate_cents = calc.compute_equipment_estimate_cents(
        estimated_drying_days, non_decomm)
    estimate_total_cents = scope_lines_total_cents + equipment_estimate_cents
    acv_total_cents = calc.compute_acv_total_cents(line_items, depreciation_pct, tax_pct)

    # supersede any prior DRAFT estimate on the job.
    for prior in domain.job_estimates(job_id):
        if prior["status"] == "DRAFT":
            prior["status"] = "SUPERSEDED"
            touch(prior)

    estimate = {
        "job_id": job_id,
        "estimated_drying_days": estimated_drying_days,
        "line_items": line_items,
        "scope_lines_total_cents": scope_lines_total_cents,
        "equipment_estimate_cents": equipment_estimate_cents,
        "estimate_total_cents": estimate_total_cents,
        "acv_total_cents": acv_total_cents,
        "status": "DRAFT",
    }
    stamp_create(estimate)
    db.estimates[estimate["id"]] = estimate

    # increment the job version (the create is OCC-guarded above).
    touch(job)

    return object_response(estimate, status=201)


@bp.route("/restoration/estimates/<estimate_id>", methods=["GET"])
def get_estimate(estimate_id):
    auth(["Estimator", "Adjuster", "Dispatcher", "PlatformAdmin"])
    return object_response(get_or_404(db.estimates, estimate_id))


@bp.route("/restoration/estimates", methods=["GET"])
def list_estimates():
    auth(["Estimator", "Adjuster", "Dispatcher", "PlatformAdmin"])
    job_id = request.args.get("job_id")
    status = request.args.get("status")
    limit, offset = pagination_params()

    items = list(db.estimates.values())
    if job_id is not None:
        items = [e for e in items if e["job_id"] == job_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/restoration/estimates/<estimate_id>/approve", methods=["POST"])
def approve_estimate(estimate_id):
    auth(["Adjuster"])
    estimate = get_or_404(db.estimates, estimate_id)

    # priority 6: state validity — only a DRAFT estimate may be approved.
    if estimate["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT estimate can be approved.")

    job = db.jobs.get(estimate["job_id"])
    claim = db.claims.get(job["claim_id"]) if job is not None else None

    # business preconditions (in scaffold order): claim OPEN, within coverage,
    # no other APPROVED estimate on the job.
    if claim is None or claim["status"] != "OPEN":
        raise err("ERR_CLAIM_ALREADY_SETTLED", "Parent claim is already SETTLED.")

    if estimate["estimate_total_cents"] > claim["coverage_limit_cents"]:
        raise err("ERR_OVER_COVERAGE_LIMIT",
                  "estimate_total_cents exceeds the claim coverage limit.")

    for other in domain.job_estimates(estimate["job_id"]):
        if other["id"] != estimate["id"] and other["status"] == "APPROVED":
            raise err("ERR_ESTIMATE_ALREADY_APPROVED",
                      "Another APPROVED estimate already exists on the job.")

    estimate["status"] = "APPROVED"
    touch(estimate)

    # cross-aggregate: settle the claim.
    claim["status"] = "SETTLED"
    claim["settled_estimate_id"] = estimate["id"]
    touch(claim)

    return object_response(estimate)

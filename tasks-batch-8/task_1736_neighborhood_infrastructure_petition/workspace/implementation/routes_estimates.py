"""CostEstimate endpoints (§3.3)."""
from flask import Blueprint

import errors
import shape
from envelope import ok_object
from helpers import get_or_404
from security import STAFF_ROLES, authenticate, require_role
from serializers import ser_estimate
from store import STORE, new_id, now, touch

bp = Blueprint("estimates", __name__)


@bp.route("/cost-estimates", methods=["POST"])
def create_estimate():
    body = shape.get_body()
    district_id = shape.req_str(body, "district_id")
    expected_version = shape.req_int(body, "expected_district_version")
    contract = shape.req_int(body, "contract_price_cents")
    contingency = shape.req_int(body, "contingency_cents")
    if contract <= 0:
        errors.raise_err(errors.INVALID_REQUEST, "contract_price_cents must be > 0")
    if contingency < 0:
        errors.raise_err(errors.INVALID_REQUEST, "contingency_cents must be >= 0")
    ctx = authenticate()
    require_role(ctx, ["CityEngineer"])
    d = get_or_404("districts", district_id, errors.DISTRICT_NOT_FOUND,
                   "District not found")
    if expected_version != d["version"]:
        errors.raise_err(errors.STALE_VERSION,
                         "expected_district_version does not match the district's current version")
    if d["status"] != "SCOPING":
        errors.raise_err(errors.DISTRICT_NOT_IN_SCOPING,
                         "Estimates may only be submitted while the district is in SCOPING")
    seq = sum(1 for e in STORE.estimates.values() if e["district_id"] == district_id) + 1
    # a fresh submission supersedes any estimate still SUBMITTED
    for e in STORE.estimates.values():
        if e["district_id"] == district_id and e["status"] == "SUBMITTED":
            e["status"] = "SUPERSEDED"
            touch(e)
    ts = now()
    e = {
        "id": new_id(),
        "district_id": district_id,
        "estimate_seq": seq,
        "contract_price_cents": contract,
        "contingency_cents": contingency,
        "total_estimated_cost_cents": contract + contingency,
        "status": "SUBMITTED",
        "submitted_by": ctx.user_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    STORE.put("estimates", e)
    touch(d)
    return ok_object(ser_estimate(e), 201)


@bp.route("/cost-estimates/<eid>", methods=["GET"])
def get_estimate(eid):
    ctx = authenticate()
    require_role(ctx, STAFF_ROLES)
    e = get_or_404("estimates", eid, errors.COST_ESTIMATE_NOT_FOUND,
                   "Cost estimate not found")
    return ok_object(ser_estimate(e))


@bp.route("/cost-estimates/<eid>/approve", methods=["POST"])
def approve_estimate(eid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityEngineer"])
    e = get_or_404("estimates", eid, errors.COST_ESTIMATE_NOT_FOUND,
                   "Cost estimate not found")
    if e["status"] != "SUBMITTED":
        errors.raise_err(errors.ESTIMATE_NOT_SUBMITTED,
                         "Estimate must be SUBMITTED to approve")
    d = STORE.districts[e["district_id"]]
    if d["status"] != "SCOPING":
        errors.raise_err(errors.DISTRICT_NOT_IN_SCOPING,
                         "District must be in SCOPING to approve an estimate")
    for other in STORE.estimates.values():
        if (other["district_id"] == e["district_id"] and other["id"] != e["id"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    e["status"] = "APPROVED"
    touch(e)
    return ok_object(ser_estimate(e))

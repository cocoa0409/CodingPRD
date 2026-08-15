"""RollForward endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_NO_APPROVED_PRIOR_STUDY,
    ERR_RUN_STALE,
)
from middleware import authorized
from response import success_object, success_list
from routes.helpers import new_common_record, sorted_by_creation
from services.calculations import (
    compute_actual_emergence_incurred,
    compute_actual_emergence_paid,
    compute_expected_emergence,
    matched_run_for_study,
)
from services.serializers import rollforward_view
from util import dec, prev_quarter, round_4dp
from validate import (
    get_body,
    parse_pagination,
    reject_server_managed,
    req_quarter,
    req_str,
    require_body_fk,
    require_path_resource,
)

bp = Blueprint("roll_forwards", __name__)

RF_COMPUTED = [
    "prior_valuation_quarter", "basis", "expected_emergence_cents",
    "actual_emergence_cents", "ave_variance_cents", "ave_variance_ratio",
]


@bp.post("/actuarial/roll-forwards")
def create_rollforward():
    authorized(["ActuarialAnalyst"])
    body = get_body()
    reject_server_managed(body, RF_COMPUTED)
    segment_id = req_str(body, "segment_id")
    valuation_quarter = req_quarter(body, "valuation_quarter")

    require_body_fk("segments", segment_id, "segment_id")

    prior_q = prev_quarter(valuation_quarter)

    # Unique non-WITHDRAWN study for (segment, prior_q).
    prior_study = None
    for s in db["studies"].values():
        if (s["segment_id"] == segment_id
                and s["valuation_quarter"] == prior_q
                and s["status"] != "WITHDRAWN"):
            prior_study = s
            break
    if prior_study is None or prior_study["status"] != "APPROVED":
        raise_error(ERR_NO_APPROVED_PRIOR_STUDY,
                    "no APPROVED study exists for the prior quarter")

    prior_run = matched_run_for_study(prior_study)
    if prior_run is None:
        # Either no run exists (shouldn't happen because study approved) or it's stale.
        raise_error(ERR_RUN_STALE, "prior study's matched run is stale")

    pattern = db["development_patterns"].get(prior_run.get("development_pattern_id"))
    if pattern is None:
        raise_error(ERR_RUN_STALE, "prior run's pattern is missing")

    basis = prior_study["selected_basis"]
    expected = compute_expected_emergence(prior_run, pattern)

    if basis == "PAID":
        actual = compute_actual_emergence_paid(segment_id, valuation_quarter)
    else:
        actual = compute_actual_emergence_incurred(segment_id, valuation_quarter, prior_q)

    variance = actual - expected
    if expected == 0:
        ratio = None
    else:
        ratio = round_4dp(dec(variance) / dec(expected))

    rec = new_common_record({
        "segment_id": segment_id,
        "valuation_quarter": valuation_quarter,
        "prior_valuation_quarter": prior_q,
        "basis": basis,
        "expected_emergence_cents": expected,
        "actual_emergence_cents": actual,
        "ave_variance_cents": variance,
        "ave_variance_ratio": ratio,
    })
    db["roll_forwards"][rec["id"]] = rec
    return success_object(rollforward_view(rec), status=201)


@bp.get("/actuarial/segments/<sid>/roll-forwards")
def list_rollforwards(sid):
    authorized(["ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    require_path_resource("segments", sid)
    limit, offset = parse_pagination()
    vq = request.args.get("valuation_quarter")
    items = [r for r in db["roll_forwards"].values() if r["segment_id"] == sid]
    if vq is not None:
        items = [r for r in items if r["valuation_quarter"] == vq]
    items = sorted_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([rollforward_view(r) for r in page], total, limit, offset)

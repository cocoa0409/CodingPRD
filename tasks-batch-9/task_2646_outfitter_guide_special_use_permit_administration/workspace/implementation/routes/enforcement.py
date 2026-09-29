"""Performance evaluations, enforcement actions and appeals (PRD 3.8)."""
from flask import Blueprint

import calc
import envelope
import security
import serialize
import shapes
import store
from errors import ApiError
from routes.common import match, qint, qstr
from security import ADMIN, ANY_ROLE, OFFICER, REPRESENTATIVE

bp = Blueprint("enforcement", __name__)

OPERABLE_FOR_ENFORCEMENT = ("ISSUED", "ACTIVE")
SEVERITIES = ("MINOR", "MODERATE", "MAJOR")
ACTION_TYPES = ("WARNING", "SUSPENSION", "REVOCATION")
ALLOWED_INSTRUMENTS = {
    "MINOR": ("WARNING",),
    "MODERATE": ("WARNING", "SUSPENSION"),
    "MAJOR": ("SUSPENSION", "REVOCATION"),
}
DECISIONS = ("UPHELD", "RESCINDED")


def resync_points(permit):
    """Points are a rolling sum recomputed from scratch, then compliance re-derives."""
    if permit is None:
        return
    calc.recompute_permit_signals(permit)
    store.touch(permit)
    calc.derive_compliance(permit)


@bp.post("/osup/permits/<permit_id>/performance-evaluations")
def record_evaluation(permit_id):
    caller = security.authenticate((OFFICER,))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    data = shapes.body()
    year = shapes.req_int(data, "evaluation_year", minimum=1900, maximum=9999)
    rp = shapes.req_int(data, "resource_protection_score", minimum=0, maximum=100)
    cs = shapes.req_int(data, "client_safety_score", minimum=0, maximum=100)
    rt = shapes.req_int(data, "reporting_timeliness_score", minimum=0, maximum=100)
    fc = shapes.req_int(data, "fee_compliance_score", minimum=0, maximum=100)
    # priority 7
    if permit["administrative_status"] not in OPERABLE_FOR_ENFORCEMENT:
        raise ApiError(
            "ERR_PERMIT_NOT_OPERATIONAL", "the permit is not ISSUED or ACTIVE"
        )
    # priority 11: one evaluation per permit and year
    for row in store.all_of("performance_evaluations"):
        if row["permit_id"] == permit["id"] and row["evaluation_year"] == year:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "an evaluation already exists for this permit and evaluation_year",
            )

    raw, provisional, penalty, weighted, rating = calc.performance_weighted_rating(
        rp, cs, rt, fc, permit["open_noncompliance_points"]
    )
    row = store.insert(
        "performance_evaluations",
        {
            "permit_id": permit["id"],
            "evaluation_year": year,
            "resource_protection_score": rp,
            "client_safety_score": cs,
            "reporting_timeliness_score": rt,
            "fee_compliance_score": fc,
            "raw_score": raw,
            "provisional_band": provisional,
            "penalty_points_applied": penalty,
            "weighted_score": weighted,
            "rating": rating,
            "evaluator_user_id": caller.user_id,
        },
        common=False,  # an evaluation is immutable: no updated_at, no version
    )
    calc.recompute_latest_performance_rating(permit)
    store.touch(permit)
    return envelope.ok(serialize.evaluation(row), 201)


@bp.get("/osup/permits/<permit_id>/performance-evaluations")
def list_evaluations(permit_id):
    security.authenticate(ANY_ROLE, mutating=False)
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    filters = {"evaluation_year": qint("evaluation_year")}
    rows = [
        e
        for e in store.all_of("performance_evaluations")
        if e["permit_id"] == permit["id"] and match(e, **filters)
    ]
    rows = store.sort_by(rows, [lambda e: e["evaluation_year"]])
    return envelope.paginate(rows, serialize.evaluation)


@bp.post("/osup/permits/<permit_id>/noncompliance-actions")
def issue_action(permit_id):
    caller = security.authenticate((OFFICER,))
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    data = shapes.body()
    severity = shapes.req_str(data, "severity", allowed=SEVERITIES)
    action_type = shapes.req_str(data, "action_type", allowed=ACTION_TYPES)
    provision = shapes.req_str(data, "cited_provision")
    deadline = shapes.req_date(data, "cure_deadline_date")
    # priority 7
    if permit["administrative_status"] not in OPERABLE_FOR_ENFORCEMENT:
        raise ApiError(
            "ERR_PERMIT_NOT_OPERATIONAL", "the permit is not ISSUED or ACTIVE"
        )
    # priority 11: the instrument must fit the severity
    if action_type not in ALLOWED_INSTRUMENTS[severity]:
        raise ApiError(
            "ERR_ACTION_TYPE_NOT_ALLOWED",
            "%s does not admit the instrument %s" % (severity, action_type),
        )

    action = store.insert(
        "noncompliance_actions",
        {
            "permit_id": permit["id"],
            "severity": severity,
            "action_type": action_type,
            "cited_provision": provision,
            "cure_deadline_date": deadline,
            "points": calc.POINTS_BY_SEVERITY[severity],
            "status": "ISSUED",
            "issued_by_user_id": caller.user_id,
            "appeal_basis": None,
            "appeal_decided_by_user_id": None,
            "corrective_summary": None,
        },
    )
    if action_type == "REVOCATION":
        permit["revocation_reason_code"] = "NONCOMPLIANCE_ACTION"
        calc.close_out_permit(permit, "REVOKED")
    resync_points(permit)
    return envelope.ok(serialize.action(action), 201)


@bp.get("/osup/permits/<permit_id>/noncompliance-actions")
def list_actions(permit_id):
    security.authenticate(ANY_ROLE, mutating=False)
    permit = store.get_or_404("permits", permit_id, "ERR_PERMIT_NOT_FOUND")
    filters = {"status": qstr("status"), "severity": qstr("severity")}
    rows = [
        a
        for a in store.all_of("noncompliance_actions")
        if a["permit_id"] == permit["id"] and match(a, **filters)
    ]
    return envelope.paginate(store.sort_created(rows), serialize.action)


@bp.post("/osup/noncompliance-actions/<action_id>/cure")
def cure_action(action_id):
    caller = security.authenticate((REPRESENTATIVE,))
    action = store.get_or_404(
        "noncompliance_actions", action_id, "ERR_NONCOMPLIANCE_ACTION_NOT_FOUND"
    )
    permit = store.get("permits", action["permit_id"])
    if permit is not None:
        security.require_owner(caller, permit["outfitter_id"])
    data = shapes.body()
    summary = shapes.req_str(data, "corrective_summary")
    # priority 7
    if action["status"] != "ISSUED":
        raise ApiError("ERR_ACTION_NOT_APPEALABLE", "the action is no longer ISSUED")
    # priority 10: the cure window closes at the end of the deadline day
    if store.today() > store.as_date(action["cure_deadline_date"]):
        raise ApiError("ERR_CURE_DEADLINE_PASSED", "the cure deadline has passed")

    action["status"] = "CURED"
    action["corrective_summary"] = summary
    store.touch(action)
    resync_points(permit)
    return envelope.ok(serialize.action(action))


@bp.post("/osup/noncompliance-actions/<action_id>/appeal")
def appeal_action(action_id):
    caller = security.authenticate((REPRESENTATIVE,))
    action = store.get_or_404(
        "noncompliance_actions", action_id, "ERR_NONCOMPLIANCE_ACTION_NOT_FOUND"
    )
    permit = store.get("permits", action["permit_id"])
    if permit is not None:
        security.require_owner(caller, permit["outfitter_id"])
    data = shapes.body()
    basis = shapes.req_str(data, "appeal_basis")
    # priority 7
    if action["status"] != "ISSUED":
        raise ApiError("ERR_ACTION_NOT_APPEALABLE", "the action is no longer ISSUED")

    action["status"] = "APPEALED"
    action["appeal_basis"] = basis
    store.touch(action)
    # appealing is not a stay: the points keep accruing
    resync_points(permit)
    return envelope.ok(serialize.action(action))


@bp.post("/osup/noncompliance-actions/<action_id>/decide-appeal")
def decide_appeal(action_id):
    caller = security.authenticate((OFFICER, ADMIN))
    action = store.get_or_404(
        "noncompliance_actions", action_id, "ERR_NONCOMPLIANCE_ACTION_NOT_FOUND"
    )
    data = shapes.body()
    decision = shapes.req_str(data, "decision", allowed=DECISIONS)
    # priority 7
    if action["status"] != "APPEALED":
        raise ApiError("ERR_ACTION_NOT_APPEALABLE", "no appeal is pending")
    # priority 11: the issuing officer may not decide its own appeal
    if caller.user_id == action["issued_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "the issuing officer may not decide this appeal"
        )

    action["status"] = decision
    action["appeal_decided_by_user_id"] = caller.user_id
    store.touch(action)
    permit = store.get("permits", action["permit_id"])
    resync_points(permit)
    return envelope.ok(serialize.action(action))

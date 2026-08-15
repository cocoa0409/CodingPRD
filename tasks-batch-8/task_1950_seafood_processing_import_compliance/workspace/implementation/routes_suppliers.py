"""Suppliers, supplier evaluations, and the logical clock endpoint."""
from flask import Blueprint, g

from db import store, new_entity, touch
from errors import (
    ApiError, ERR_SUPPLIER_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_EVALUATION_PERIOD_OVERLAP, ERR_VALIDATION_FAILED,
)
from middleware import require_roles, ANY_OPERATIONAL, ROLE_COMPLIANCE_MANAGER, ROLE_PLATFORM_ADMIN
from response import success
from services import (
    serialize_supplier, serialize_evaluation, supplier_risk, TIER_INTERVAL_MONTHS,
)
from utils import (
    get_body, req_str, opt_bool, req_num, req_int, req_dt, q2, paginate, iso_z,
    add_months, parse_dt,
)

bp = Blueprint("suppliers", __name__)
clock_bp = Blueprint("clock", __name__)


def get_supplier_or_404(supplier_id):
    s = store.suppliers.get(supplier_id)
    if s is None:
        raise ApiError(ERR_SUPPLIER_NOT_FOUND, "Supplier %s not found" % supplier_id, 404)
    return s


@bp.route("/seafood/suppliers", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def create_supplier():
    body = get_body()
    legal_name = req_str(body, "legal_name")
    country_code = req_str(body, "country_code")
    frn = req_str(body, "facility_registration_number")
    handles = opt_bool(body, "handles_histamine_susceptible_species", False)
    # facility_registration_number is unique across suppliers
    for s in store.suppliers.values():
        if s["facility_registration_number"] == frn:
            raise ApiError(
                ERR_VALIDATION_FAILED,
                "facility_registration_number %s already registered" % frn, 400)
    supplier = new_entity(
        legal_name=legal_name,
        country_code=country_code,
        facility_registration_number=frn,
        handles_histamine_susceptible_species=handles,
        fsvp_status="PENDING_EVALUATION",
        last_evaluation_period_end=None,
        next_evaluation_due=None,
    )
    store.suppliers[supplier["id"]] = supplier
    return success(serialize_supplier(supplier), "object", 201)


@bp.route("/seafood/suppliers/<sid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_supplier(sid):
    return success(serialize_supplier(get_supplier_or_404(sid)))


@bp.route("/seafood/suppliers/<sid>/suspend", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def suspend_supplier(sid):
    supplier = get_supplier_or_404(sid)
    if supplier["fsvp_status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an APPROVED supplier can be suspended", 409)
    supplier["fsvp_status"] = "SUSPENDED"
    touch(supplier)
    return success(serialize_supplier(supplier))


@bp.route("/seafood/supplier-evaluations", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def create_evaluation():
    body = get_body()
    # p4: body FK existence first when supplier_id looks like an id
    supplier_id = body.get("supplier_id")
    if isinstance(supplier_id, str) and supplier_id not in store.suppliers:
        raise ApiError(ERR_SUPPLIER_NOT_FOUND,
                       "Supplier %s not found" % supplier_id, 404)
    supplier_id = req_str(body, "supplier_id")
    supplier = store.suppliers[supplier_id]
    # p5: field validation
    expected_version = req_int(body, "expected_supplier_version")
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if period_end <= period_start:
        raise ApiError(ERR_VALIDATION_FAILED,
                       "period_end must be strictly after period_start", 400)
    hazard = req_num(body, "hazard_analysis_score")
    record = req_num(body, "record_review_score")
    perf = req_num(body, "performance_score")
    for name, v in (("hazard_analysis_score", hazard),
                    ("record_review_score", record),
                    ("performance_score", perf)):
        if v < 0 or v > 100:
            raise ApiError(ERR_VALIDATION_FAILED,
                           "%s must be within 0-100" % name, 400)
    hazard, record, perf = q2(hazard), q2(record), q2(perf)
    # overall per spec: 0.5*hazard + 0.3*record + 0.2*perf, round half-up 2dp
    from decimal import Decimal
    overall = q2(hazard * Decimal("0.5") + record * Decimal("0.3") + perf * Decimal("0.2"))
    if overall >= 70:
        outcome = "APPROVED"
    elif overall >= 50:
        outcome = "CONDITIONAL"
    else:
        outcome = "REJECTED"
    # p6: state-machine validity for this outcome from the supplier's posture
    status = supplier["fsvp_status"]
    valid = (
        (status == "PENDING_EVALUATION")
        or (status == "APPROVED")
        or (status == "REEVALUATION_DUE")
        or (status == "SUSPENDED" and outcome == "APPROVED")
    )
    if not valid:
        raise ApiError(
            ERR_INVALID_STATE,
            "No evaluation transition from %s with outcome %s" % (status, outcome),
            409)
    # p18: closed-interval period overlap for the same supplier
    for e in store.evaluations.values():
        if e["supplier_id"] != supplier["id"]:
            continue
        if period_start <= e["period_end"] and e["period_start"] <= period_end:
            raise ApiError(
                ERR_EVALUATION_PERIOD_OVERLAP,
                "Evaluation period overlaps an existing evaluation", 422)
    # p27: OCC on the supplier version
    if expected_version != supplier["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_supplier_version does not match current supplier version", 412)

    evaluation = new_entity(
        supplier_id=supplier["id"],
        period_start=period_start,
        period_end=period_end,
        hazard_analysis_score=hazard,
        record_review_score=record,
        performance_score=perf,
        overall_score=overall,
        outcome=outcome,
        evaluated_by=g.user_id,
    )
    store.evaluations[evaluation["id"]] = evaluation

    # apply the supplier posture transition
    if status == "PENDING_EVALUATION":
        if outcome == "APPROVED":
            supplier["fsvp_status"] = "APPROVED"
            _certify(supplier, period_end)
        elif outcome == "REJECTED":
            supplier["fsvp_status"] = "REJECTED"
        # CONDITIONAL: stays PENDING_EVALUATION
    elif status == "APPROVED":
        if outcome in ("APPROVED", "CONDITIONAL"):
            _certify(supplier, period_end)
        else:
            supplier["fsvp_status"] = "SUSPENDED"
    elif status == "REEVALUATION_DUE":
        if outcome in ("APPROVED", "CONDITIONAL"):
            supplier["fsvp_status"] = "APPROVED"
            _certify(supplier, period_end)
        else:
            supplier["fsvp_status"] = "SUSPENDED"
    elif status == "SUSPENDED":
        # outcome == APPROVED guaranteed by the state check above
        supplier["fsvp_status"] = "APPROVED"
        _certify(supplier, period_end)
    touch(supplier)
    return success(serialize_evaluation(evaluation), "object", 201)


def _certify(supplier, period_end):
    """Set last_evaluation_period_end + next_evaluation_due from the new tier."""
    supplier["last_evaluation_period_end"] = period_end
    _score, tier = supplier_risk(supplier)
    months = TIER_INTERVAL_MONTHS[tier]
    supplier["next_evaluation_due"] = add_months(period_end, months)


@bp.route("/seafood/supplier-evaluations/<eid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_evaluation(eid):
    e = store.evaluations.get(eid)
    if e is None:
        raise ApiError("ERR_EVALUATION_NOT_FOUND",
                       "Evaluation %s not found" % eid, 404)
    return success(serialize_evaluation(e))


@bp.route("/seafood/supplier-evaluations", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def list_evaluations():
    from flask import request
    items = list(store.evaluations.values())
    supplier_id = request.args.get("supplier_id")
    if supplier_id is not None:
        items = [e for e in items if e["supplier_id"] == supplier_id]
    page, meta = paginate(items)
    return success([serialize_evaluation(e) for e in page], "array", 200, meta)


@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles(ROLE_PLATFORM_ADMIN)
def set_clock():
    body = get_body()
    raw = body.get("to_iso8601")
    try:
        target = parse_dt(raw)
    except (ValueError, TypeError):
        raise ApiError(ERR_VALIDATION_FAILED,
                       "to_iso8601 must be an ISO8601 datetime", 400)
    store.clock = target
    # sweep: APPROVED suppliers whose next_evaluation_due <= now lapse
    for supplier in store.suppliers.values():
        due = supplier.get("next_evaluation_due")
        if (supplier["fsvp_status"] == "APPROVED" and due is not None
                and due <= store.clock):
            supplier["fsvp_status"] = "REEVALUATION_DUE"
            touch(supplier)
    return success({"current_utc": iso_z(store.clock)})

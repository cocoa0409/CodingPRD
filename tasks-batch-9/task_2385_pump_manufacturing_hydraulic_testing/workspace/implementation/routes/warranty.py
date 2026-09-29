"""Field troubleshooting, warranty adjudication and settlement."""

from flask import Blueprint, g

from db import by_seq, db, new_record
from errors import ApiError
from helpers import (
    apply_filters,
    config_of_selection,
    model_of_selection,
    paginate,
    path_lookup,
    points_of_run,
    ref_lookup,
    selection_of_build,
    touch,
)
from middleware import ALL_ROLES, authorize
from response import list_response, object_response
from serializers import dump, dump_all
from services import calc
from validation import (
    CLAIM_CATEGORIES,
    check_keys,
    get_body,
    pagination,
    query_value,
    req_array,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("warranty", __name__)

LINE_KEYS = ("line_code", "category", "gross_amount")


def _no_body_allowed():
    check_keys(get_body(), ())


def _collection(records, limit, offset):
    window, total = paginate(records, limit, offset)
    return list_response(dump_all(window), limit, offset, total)


def _validate_claim_lines(raw):
    """Rung 3 handles shape; the emptiness and positivity rules live at rung 60."""
    for element in raw:
        if not isinstance(element, dict):
            raise ApiError(
                "ERR_INVALID_REQUEST", "Field 'claim_lines' members must be JSON objects"
            )
        for key in element.keys():
            if key not in LINE_KEYS:
                raise ApiError(
                    "ERR_INVALID_REQUEST", "Unknown field 'claim_lines.%s'" % key
                )
        req_string(element, "line_code")
        category = element.get("category")
        if not isinstance(category, str) or category not in CLAIM_CATEGORIES:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field 'claim_lines.category' must be one of %s" % ", ".join(CLAIM_CATEGORIES),
            )
        amount = element.get("gross_amount")
        if amount is None or isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ApiError(
                "ERR_INVALID_REQUEST", "Field 'claim_lines.gross_amount' must be a number"
            )


def _claim_lines_present_and_positive(raw):
    if not raw:
        raise ApiError("ERR_EMPTY_CLAIM_LINES")
    for element in raw:
        if calc.D(element["gross_amount"]) <= 0:
            raise ApiError("ERR_EMPTY_CLAIM_LINES")


def _chain(claim):
    """package -> build order -> selection -> model / config, plus the test run."""
    package = db.pump_packages.get(claim["pump_package_id"])
    order = db.build_orders.get(package["build_order_id"]) if package else None
    selection = selection_of_build(order) if order else None
    run = db.test_runs.get(package["test_run_id"]) if package else None
    return package, selection, model_of_selection(selection), config_of_selection(selection), run


@bp.post("/warranty-claims")
def create_warranty_claim():
    authorize("ApplicationEngineer")
    body = get_body()
    check_keys(
        body,
        (
            "pump_package_id",
            "as_found_flow_m3h",
            "as_found_head_m",
            "as_found_npsha_m",
            "as_found_solids_pct",
            "as_found_viscosity_cst",
            "as_found_speed_rpm",
            "claim_lines",
        ),
    )
    pump_package_id = req_string(body, "pump_package_id")
    as_found_flow = req_number(body, "as_found_flow_m3h", exclusive_min=0)
    as_found_head = req_number(body, "as_found_head_m", exclusive_min=0)
    as_found_npsha = req_number(body, "as_found_npsha_m", exclusive_min=0)
    as_found_solids = req_number(body, "as_found_solids_pct", minimum=0)
    as_found_viscosity = req_number(body, "as_found_viscosity_cst", exclusive_min=0)
    as_found_speed = req_int(body, "as_found_speed_rpm", minimum=300)
    claim_lines = req_array(body, "claim_lines")
    _validate_claim_lines(claim_lines)

    package = ref_lookup(db.pump_packages, pump_package_id)

    if package["status"] != "SHIPPED":
        raise ApiError("ERR_PACKAGE_NOT_SHIPPED")

    months = calc.whole_months_between(package["actual_ship_date"], db.clock)
    if months > calc.WARRANTY_MONTHS:
        raise ApiError("ERR_WARRANTY_EXPIRED")

    _claim_lines_present_and_positive(claim_lines)

    factor = calc.coverage_factor(months)

    record = new_record(
        "WarrantyClaim",
        pump_package_id=pump_package_id,
        as_found_flow_m3h=as_found_flow,
        as_found_head_m=as_found_head,
        as_found_npsha_m=as_found_npsha,
        as_found_solids_pct=as_found_solids,
        as_found_viscosity_cst=as_found_viscosity,
        as_found_speed_rpm=as_found_speed,
        claim_lines=[dict((k, line[k]) for k in LINE_KEYS) for line in claim_lines],
        submitted_by_user_id=g.user_id,
        adjudicated_by_user_id=None,
        info_request_note=None,
        liability_basis=None,
        expected_head_m=None,
        head_shortfall_pct=None,
        application_error_flags=[],
        determination=None,
        months_since_ship=months,
        coverage_factor=factor,
        settlement_subtotal=None,
        admin_fee=None,
        settlement_total=None,
        status="SUBMITTED",
    )
    db.warranty_claims[record["id"]] = record
    return object_response(dump(record), 201)


@bp.get("/warranty-claims")
def list_warranty_claims():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.warranty_claims.values()),
        [
            (query_value("pump_package_id"), "pump_package_id"),
            (query_value("status"), "status"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/warranty-claims/<resource_id>")
def read_warranty_claim(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.warranty_claims, resource_id)))


@bp.post("/warranty-claims/<resource_id>/begin-adjudication")
def begin_adjudication(resource_id):
    authorize("WarrantyAdjudicator")
    _no_body_allowed()
    claim = path_lookup(db.warranty_claims, resource_id)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    claim["status"] = "UNDER_ADJUDICATION"
    touch(claim)
    return object_response(dump(claim))


@bp.post("/warranty-claims/<resource_id>/request-info")
def request_info(resource_id):
    authorize("WarrantyAdjudicator")
    body = get_body()
    check_keys(body, ("info_request_note",))
    note = req_string(body, "info_request_note")
    claim = path_lookup(db.warranty_claims, resource_id)
    if claim["status"] != "UNDER_ADJUDICATION":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    claim["status"] = "INFO_REQUESTED"
    claim["info_request_note"] = note
    touch(claim)
    return object_response(dump(claim))


@bp.post("/warranty-claims/<resource_id>/resume-adjudication")
def resume_adjudication(resource_id):
    authorize("WarrantyAdjudicator")
    _no_body_allowed()
    claim = path_lookup(db.warranty_claims, resource_id)
    if claim["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    claim["status"] = "UNDER_ADJUDICATION"
    claim["info_request_note"] = None
    touch(claim)
    return object_response(dump(claim))


def _expected_head(claim, selection, model, run):
    as_found_flow = calc.D(claim["as_found_flow_m3h"])
    if claim["liability_basis"] == "CERTIFIED_CURVE":
        _, rows = calc.reported_points(model, run, points_of_run(run["id"]))
        # Outside the reported flow range the nearest endpoint is the promise.
        pair = calc.interpolate(rows, as_found_flow, clamp=True)
        if pair is None:
            return None
        return calc.rhu(pair[0], 2)
    k = (calc.D(model["shutoff_head_m"]) - calc.D(model["bep_head_m"])) / (
        calc.D(model["bep_flow_m3h"]) ** 2
    )
    ratio = calc.D(selection["diameter_ratio"])
    return calc.rhu(
        ratio ** 2 * calc.D(model["shutoff_head_m"]) - k * as_found_flow ** 2, 2
    )


def _application_error_flags(claim, selection, model, config):
    flags = []
    if calc.D(claim["as_found_solids_pct"]) > calc.D(config["max_solids_pct"]):
        flags.append("SOLIDS_EXCEEDS_CONFIG")
    if calc.D(claim["as_found_viscosity_cst"]) > calc.D(config["max_viscosity_cst"]):
        flags.append("VISCOSITY_EXCEEDS_CONFIG")
    if calc.D(claim["as_found_npsha_m"]) < calc.D(selection["npshr_certified_m"]) + calc.NPSHA_CLAIM_MARGIN_M:
        flags.append("NPSHA_BELOW_CERTIFIED")
    if claim["as_found_speed_rpm"] > model["rated_speed_rpm"]:
        flags.append("SPEED_ABOVE_RATED")
    return flags


@bp.post("/warranty-claims/<resource_id>/adjudicate")
def adjudicate(resource_id):
    authorize("WarrantyAdjudicator")
    _no_body_allowed()
    claim = path_lookup(db.warranty_claims, resource_id)
    # Rung 9 sits above the rung-17 state check.
    if g.user_id == claim["submitted_by_user_id"]:
        raise ApiError("ERR_ADJUDICATOR_CONFLICT")
    if claim["status"] != "UNDER_ADJUDICATION":
        raise ApiError("ERR_CLAIM_INVALID_STATE")

    package, selection, model, config, run = _chain(claim)

    claim["liability_basis"] = package["guarantee_basis"]
    expected_head = _expected_head(claim, selection, model, run)
    claim["expected_head_m"] = expected_head
    shortfall = calc.rhu(
        (calc.D(claim["as_found_head_m"]) - expected_head) / expected_head * calc.HUNDRED, 2
    )
    claim["head_shortfall_pct"] = shortfall
    flags = _application_error_flags(claim, selection, model, config)
    claim["application_error_flags"] = flags

    head_tolerance = calc.GRADE_TOLERANCES[run["test_grade"]]["head_pct"]
    if shortfall >= -head_tolerance:
        determination = "NO_DEFECT_FOUND"
        claim["status"] = "ADJUDICATED_NO_DEFECT"
        counter = "no_defect_count"
    elif flags:
        determination = "APPLICATION_ERROR"
        claim["status"] = "ADJUDICATED_APPLICATION_ERROR"
        counter = "application_error_count"
    else:
        determination = "MANUFACTURING_DEFECT"
        claim["status"] = "ADJUDICATED_MANUFACTURING"
        counter = "warranty_defect_count"
    claim["determination"] = determination
    claim["adjudicated_by_user_id"] = g.user_id
    touch(claim)

    if determination == "APPLICATION_ERROR":
        package["application_error_flagged"] = True
        touch(package)
    model[counter] += 1
    touch(model)
    return object_response(dump(claim))


@bp.post("/warranty-claims/<resource_id>/settle")
def settle(resource_id):
    authorize("WarrantyAdjudicator")
    _no_body_allowed()
    claim = path_lookup(db.warranty_claims, resource_id)
    if claim["status"] != "ADJUDICATED_MANUFACTURING":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    _, subtotal, admin_fee, total = calc.settlement(
        claim["claim_lines"], calc.D(claim["coverage_factor"])
    )
    claim["settlement_subtotal"] = subtotal
    claim["admin_fee"] = admin_fee
    claim["settlement_total"] = total
    claim["status"] = "SETTLED"
    touch(claim)
    return object_response(dump(claim))

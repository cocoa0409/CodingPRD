"""Operating hour appends (single + all-or-nothing bulk), reads and the
missing-data substitution procedure (PRD 3.5 / 3.6).
"""

from flask import Blueprint

from constants import (
    API_PREFIX,
    APPENDIX_D_FORBIDDEN_FIELDS,
    APPENDIX_D_REQUIRED_FIELDS,
    BULK_MAX_HOURS,
    BULK_MIN_HOURS,
    CEMS_FORBIDDEN_FIELDS,
    CEMS_REQUIRED_FIELDS,
    DATA_QUALITIES,
    HEAT_INPUT_METHODS,
    ROLE_FACILITY_OPERATOR,
    ROLE_PREPARER,
    SUBSTITUTION_METHODS,
)
from db import db, public, public_list, sort_rows
from errors import fail
from lookup import facility_of_unit, find, get
from middleware import ANY_ROLE, authenticate, enforce_facility_scope
from response import array_response, object_response, plain_array_response
from services import hours as hours_service
from services.reports import find_open_report
from util import is_on_the_hour, quarter_of
from validation import (
    apply_pagination,
    body_dict,
    check_range,
    dt_field,
    enum_field,
    id_field,
    int_field,
    list_field,
    match_filters,
    num_field,
    pagination,
    query_filters,
)

bp = Blueprint("operating_hours", __name__)

APPEND_ROLES = (ROLE_FACILITY_OPERATOR, ROLE_PREPARER)

MEASUREMENT_FIELDS = (
    "flow_scfh",
    "co2_conc_pct",
    "so2_conc_ppm",
    "nox_rate_lb_mmbtu",
    "fuel_flow_lbs",
)


# ---------------------------------------------------------------------------
# per-hour stages -- shared verbatim by the single and the bulk append so the
# two endpoints cannot drift apart
# ---------------------------------------------------------------------------

def _parse_hour(item):
    """Stage 1: request shape only. Blind to the method field families."""
    if not isinstance(item, dict):
        fail("ERR_INVALID_REQUEST", "Each entry of 'hours' must be a JSON object.")
    raw, parsed = dt_field(item, "hour_begin_utc", required=True)
    spec = {
        "hour_begin_utc_raw": raw,
        "hour_begin_utc": parsed,
        "op_time_fraction": num_field(item, "op_time_fraction", required=True),
        "heat_input_method": enum_field(
            item, "heat_input_method", HEAT_INPUT_METHODS, required=True
        ),
        "gross_load_mw": num_field(item, "gross_load_mw"),
        "flow_scfh": num_field(item, "flow_scfh"),
        "co2_conc_pct": num_field(item, "co2_conc_pct"),
        "so2_conc_ppm": num_field(item, "so2_conc_ppm"),
        "nox_rate_lb_mmbtu": num_field(item, "nox_rate_lb_mmbtu"),
        "fuel_flow_lbs": num_field(item, "fuel_flow_lbs"),
        "fuel_sample_id": id_field(item, "fuel_sample_id"),
    }
    return spec


def _resolve_fuel_sample(unit, spec):
    """Stages 110 / 120: body foreign key, then the belongs-to-parent rule."""
    sample_id = spec.get("fuel_sample_id")
    if sample_id is None:
        spec["fuel_sample"] = None
        return
    sample = get("fuel_sample", sample_id)
    if sample["unit_id"] != unit["id"]:
        fail("ERR_FUEL_SAMPLE_NOT_FOUND", "The fuel sample does not belong to this unit.")
    spec["fuel_sample"] = sample


def _resolve_report(unit, spec):
    """The hour's own timestamp selects its report (never the client)."""
    hour_begin = spec["hour_begin_utc"]
    report = find_open_report(unit["id"], hour_begin.year, quarter_of(hour_begin))
    spec["report"] = report
    return report


def _check_duplicate(unit, spec, seen):
    hour_begin = spec["hour_begin_utc"]
    for existing in db.operating_hours.values():
        if existing["unit_id"] == unit["id"] and existing["_hour_begin"] == hour_begin:
            fail("ERR_DUPLICATE_OPERATING_HOUR", "This unit already has that clock hour.")
    if hour_begin in seen:
        fail("ERR_DUPLICATE_OPERATING_HOUR", "The array repeats one clock hour.")
    seen.add(hour_begin)


def _check_sample_analyzed(spec):
    sample = spec.get("fuel_sample")
    if sample is not None and sample["status"] != "ANALYZED":
        fail(
            "ERR_FUEL_SAMPLE_NOT_ANALYZED",
            "The referenced fuel sample is not standing at ANALYZED.",
        )


def _check_period(spec):
    if not is_on_the_hour(spec["hour_begin_utc"]):
        fail("ERR_HOUR_OUTSIDE_REPORT_PERIOD", "hour_begin_utc must be exactly on the hour.")
    if spec.get("report") is None:
        fail(
            "ERR_HOUR_OUTSIDE_REPORT_PERIOD",
            "No DRAFT or VALIDATED report covers this unit and calendar quarter.",
        )


def _check_method_fields(unit, spec):
    method = spec["heat_input_method"]
    if method == "CEMS_FLOW_CO2":
        required, forbidden = CEMS_REQUIRED_FIELDS, CEMS_FORBIDDEN_FIELDS
    else:
        required, forbidden = APPENDIX_D_REQUIRED_FIELDS, APPENDIX_D_FORBIDDEN_FIELDS
    for name in required:
        if spec.get(name) is None:
            fail("ERR_METHOD_FIELD_MISMATCH", "%s is required by %s." % (name, method))
    for name in forbidden:
        if spec.get(name) is not None:
            fail("ERR_METHOD_FIELD_MISMATCH", "%s is forbidden by %s." % (name, method))
    if not hours_service.unit_supports_method(unit["id"], method):
        fail(
            "ERR_METHOD_FIELD_MISMATCH",
            "The unit owns no monitoring system whose system_type matches %s." % method,
        )


def _check_ranges(spec):
    check_range("op_time_fraction", spec["op_time_fraction"], minimum=0, maximum=1)
    check_range("gross_load_mw", spec["gross_load_mw"], minimum=0)
    check_range("flow_scfh", spec["flow_scfh"], minimum=0, min_exclusive=True)
    check_range("co2_conc_pct", spec["co2_conc_pct"], minimum=0, maximum=20, min_exclusive=True)
    check_range("so2_conc_ppm", spec["so2_conc_ppm"], minimum=0, maximum=2000)
    check_range("nox_rate_lb_mmbtu", spec["nox_rate_lb_mmbtu"], minimum=0, maximum=2)


# ---------------------------------------------------------------------------
# single append
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/units/<unit_id>/operating-hours", methods=["POST"])
def append_hour(unit_id):
    caller = authenticate(APPEND_ROLES)
    body = body_dict()
    enforce_facility_scope(caller, facility_of_unit(find("unit", unit_id)))

    expected_version = int_field(body, "expected_quarterly_report_version", required=True)
    spec = _parse_hour(body)

    unit = get("unit", unit_id)
    _resolve_fuel_sample(unit, spec)
    report = _resolve_report(unit, spec)

    if report is not None and expected_version != report["version"]:
        fail(
            "ERR_STALE_REPORT_VERSION",
            "expected_quarterly_report_version does not match the stored version.",
        )

    _check_duplicate(unit, spec, set())
    _check_sample_analyzed(spec)
    _check_period(spec)
    _check_method_fields(unit, spec)
    _check_ranges(spec)

    hour = hours_service.build_hour(unit, report, spec)
    hours_service.finalize_append(unit, [hour], [report])
    return object_response(public(hour), 201)


# ---------------------------------------------------------------------------
# bulk append -- strictly all or nothing
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/units/<unit_id>/operating-hours/bulk", methods=["POST"])
def append_hours_bulk(unit_id):
    caller = authenticate(APPEND_ROLES)
    body = body_dict()
    enforce_facility_scope(caller, facility_of_unit(find("unit", unit_id)))

    expected_version = int_field(body, "expected_quarterly_report_version", required=True)
    items = list_field(body, "hours", required=True)

    unit = get("unit", unit_id)

    if len(items) < BULK_MIN_HOURS:
        # Nothing else can be evaluated against an empty array.
        fail("ERR_BULK_SIZE_INVALID", "hours must hold between 1 and 200 entries.")

    specs = [_parse_hour(item) for item in items]
    specs.sort(key=lambda s: s["hour_begin_utc"])

    for spec in specs:
        _resolve_fuel_sample(unit, spec)
    for spec in specs:
        _resolve_report(unit, spec)

    # The guard is held once for the whole array: it is matched against the
    # report of the earliest hour that resolves to one.
    guarded = next((s["report"] for s in specs if s["report"] is not None), None)
    if guarded is not None and expected_version != guarded["version"]:
        fail(
            "ERR_STALE_REPORT_VERSION",
            "expected_quarterly_report_version does not match the stored version.",
        )

    seen = set()
    for spec in specs:
        _check_duplicate(unit, spec, seen)
    for spec in specs:
        _check_sample_analyzed(spec)
    for spec in specs:
        _check_period(spec)
    for spec in specs:
        _check_method_fields(unit, spec)
    for spec in specs:
        _check_ranges(spec)

    if len(specs) > BULK_MAX_HOURS:
        fail("ERR_BULK_SIZE_INVALID", "hours must hold between 1 and 200 entries.")

    created = []
    reports = []
    for spec in specs:
        report = spec["report"]
        created.append(hours_service.build_hour(unit, report, spec))
        if report is not None and report["id"] not in [r["id"] for r in reports]:
            reports.append(report)
    hours_service.finalize_append(unit, created, reports)
    return plain_array_response(public_list(created), 201)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/operating-hours", methods=["GET"])
def list_hours():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {
            "unit_id": "str",
            "quarterly_report_id": "str",
            "fuel_sample_id": "str",
            "data_quality": DATA_QUALITIES,
            "substitution_method": SUBSTITUTION_METHODS,
            "heat_input_method": HEAT_INPUT_METHODS,
            "from_hour_utc": "dt",
            "to_hour_utc": "dt",
        }
    )
    limit, offset = pagination()
    rows = match_filters(
        list(db.operating_hours.values()),
        filters,
        fields=[
            "unit_id",
            "quarterly_report_id",
            "fuel_sample_id",
            "data_quality",
            "substitution_method",
            "heat_input_method",
        ],
    )
    # half-open [from_hour_utc, to_hour_utc) over hour_begin_utc
    if "from_hour_utc" in filters:
        rows = [r for r in rows if r["_hour_begin"] >= filters["from_hour_utc"]]
    if "to_hour_utc" in filters:
        rows = [r for r in rows if r["_hour_begin"] < filters["to_hour_utc"]]
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/operating-hours/<hour_id>", methods=["GET"])
def read_hour(hour_id):
    authenticate(ANY_ROLE)
    return object_response(public(get("operating_hour", hour_id)))


# ---------------------------------------------------------------------------
# missing data substitution
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/units/<unit_id>/missing-data/substitutions", methods=["POST"])
def substitute_missing_data(unit_id):
    caller = authenticate(APPEND_ROLES)
    body = body_dict()
    enforce_facility_scope(caller, facility_of_unit(find("unit", unit_id)))

    _, start = dt_field(body, "from_hour_utc", required=True)
    _, end = dt_field(body, "to_hour_utc", required=True)

    unit = get("unit", unit_id)

    if start >= end:
        fail("ERR_INVALID_INTERVAL", "to_hour_utc must be strictly later than from_hour_utc.")

    targets = hours_service.substitutable_targets(unit["id"], start, end)
    if not targets:
        fail("ERR_NO_SUBSTITUTABLE_HOURS", "The range holds no UNAVAILABLE hour.")

    hours_service.run_substitutions(unit, targets)
    return plain_array_response(public_list(targets))

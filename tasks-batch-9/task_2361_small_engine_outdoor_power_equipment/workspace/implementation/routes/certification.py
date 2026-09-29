"""Emission certification families, shared engine platforms and durability runs."""

from collections import OrderedDict

from flask import Blueprint

import calc
import store
import svc
import validation as v
from auth import endpoint, READ_ROLES, user_id
from errors import ApiError
from response import list_response, object_response
from store import db, bump, set_fields

bp = Blueprint("certification", __name__)

FAMILY_STATUSES = (
    "DRAFT", "DURABILITY_TESTING", "DURABILITY_COMPLETE", "SUBMITTED",
    "CERTIFIED", "AUDIT_HOLD", "SUSPENDED",
)


def _family_view(family):
    return store.public(family)


# ------------------------------------------------------- certification families

@bp.route("/certification-families", methods=["POST"])
@endpoint(["CertificationEngineer"])
def create_family():
    payload = v.body()
    family_code = v.string_field(payload, "family_code", 1, 40, r"^[A-Z0-9\-]+$")
    model_year = v.int_field(payload, "model_year", 2026, 2035)
    emission_standard = v.enum_field(payload, "emission_standard", ("EPA_PHASE3", "CARB_2024"))
    displacement_min_cc = v.int_field(payload, "displacement_min_cc", 50, 1000)
    displacement_max_cc = v.int_field(payload, "displacement_max_cc", 50, 1000)
    if displacement_max_cc < displacement_min_cc:
        v.bad("displacement_max_cc must be at least displacement_min_cc.")
    durability_hours = v.int_field(payload, "durability_hours", choices=(125, 250, 500, 1000))
    limit = v.number_field(payload, "family_emission_limit_g_per_kwh", exclusive_min=0)
    baseline = v.number_field(payload, "declared_baseline_emission_g_per_kwh", exclusive_min=0)

    svc.require_unique(db.families, "family_code", family_code)

    family = store.new_record(OrderedDict([
        ("family_code", family_code),
        ("model_year", model_year),
        ("emission_standard", emission_standard),
        ("displacement_min_cc", displacement_min_cc),
        ("displacement_max_cc", displacement_max_cc),
        ("durability_hours", durability_hours),
        ("family_emission_limit_g_per_kwh", limit),
        ("declared_baseline_emission_g_per_kwh", baseline),
        ("status", "DRAFT"),
        ("deterioration_factor", None),
        ("certified_emission_g_per_kwh", None),
        ("compliance_margin_pct", None),
        ("submitted_by_user_id", None),
        ("certified_by_user_id", None),
        ("certified_at", None),
        ("cumulative_audit_failures", 0),
        ("audit_hold_at", None),
    ]))
    db.families[family["id"]] = family
    return object_response(_family_view(family), 201)


@bp.route("/certification-families/<family_id>", methods=["GET"])
@endpoint(READ_ROLES)
def read_family(family_id):
    family = svc.get_family(family_id)
    return object_response(_family_view(family), 200)


@bp.route("/certification-families/<family_id>/engine-platforms", methods=["GET"])
@endpoint(READ_ROLES)
def list_family_platforms(family_id):
    limit, offset = v.pagination()
    family = svc.get_family(family_id)
    rows = svc.family_platforms(family["id"])
    page, total = v.paginate(rows, limit, offset)
    return list_response([store.public(r) for r in page], limit, offset, total)


@bp.route("/certification-families/<family_id>/submit", methods=["POST"])
@endpoint(["CertificationEngineer"])
def submit_family(family_id):
    v.body()
    family = svc.get_family(family_id)
    if family["status"] != "DURABILITY_COMPLETE" or family["certified_emission_g_per_kwh"] is None:
        raise ApiError(
            "ERR_FAMILY_STATE_INVALID",
            "Only a family whose durability testing is complete may be submitted.",
        )
    set_fields(family, status="SUBMITTED", submitted_by_user_id=user_id())
    svc.recompute_postures(family)
    return object_response(_family_view(family), 200)


@bp.route("/certification-families/<family_id>/certify", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def certify_family(family_id):
    v.body()
    family = svc.get_family(family_id)
    if family["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_FAMILY_STATE_INVALID",
            "Only a SUBMITTED family may be certified.",
        )
    if family["submitted_by_user_id"] is not None and family["submitted_by_user_id"] == user_id():
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The certifying operator may not be the submitting operator.",
        )
    certified = family["certified_emission_g_per_kwh"]
    limit = family["family_emission_limit_g_per_kwh"]
    if certified is None or calc.dec(certified) > calc.dec(limit):
        raise ApiError(
            "ERR_CERTIFIED_EMISSION_EXCEEDS_LIMIT",
            "The certified emission exceeds the family emission limit.",
        )
    margin = family["compliance_margin_pct"]
    if margin is None or calc.dec(margin) < calc.MIN_COMPLIANCE_MARGIN_PCT:
        raise ApiError(
            "ERR_COMPLIANCE_MARGIN_TOO_LOW",
            "The compliance margin is below the minimum required headroom.",
        )

    set_fields(
        family,
        status="CERTIFIED",
        certified_by_user_id=user_id(),
        certified_at=store.now_clock(),
    )
    svc.recompute_postures(family)
    svc.certification_compensation(family)
    return object_response(_family_view(family), 200)


# --------------------------------------------------------------- engine platforms

@bp.route("/engine-platforms", methods=["POST"])
@endpoint(["PlantAdmin"])
def create_platform():
    payload = v.body()
    family_id = v.id_field(payload, "certification_family_id")
    platform_code = v.string_field(payload, "platform_code", 1, 30)
    displacement_cc = v.int_field(payload, "displacement_cc", 50, 1000)
    torque_spec_nm = v.number_field(payload, "torque_spec_nm", exclusive_min=0)
    torque_tolerance_pct = v.number_field(payload, "torque_tolerance_pct", "0.01", "0.20")
    required_fastener_count = v.int_field(payload, "required_fastener_count", 1, 12)
    hot_test_min_rpm = v.int_field(payload, "hot_test_min_rpm", 500, 8000)
    hot_test_max_rpm = v.int_field(payload, "hot_test_max_rpm", None, 8000)
    if hot_test_max_rpm <= hot_test_min_rpm:
        v.bad("hot_test_max_rpm must be strictly greater than hot_test_min_rpm.")

    family = svc.get_family(family_id)
    svc.require_unique(db.platforms, "platform_code", platform_code)
    if not (family["displacement_min_cc"] <= displacement_cc <= family["displacement_max_cc"]):
        raise ApiError(
            "ERR_DISPLACEMENT_OUT_OF_FAMILY",
            "The platform displacement falls outside the family's declared band.",
        )

    platform = store.new_record(OrderedDict([
        ("certification_family_id", family["id"]),
        ("platform_code", platform_code),
        ("displacement_cc", displacement_cc),
        ("torque_spec_nm", torque_spec_nm),
        ("torque_tolerance_pct", torque_tolerance_pct),
        ("required_fastener_count", required_fastener_count),
        ("hot_test_min_rpm", hot_test_min_rpm),
        ("hot_test_max_rpm", hot_test_max_rpm),
        ("certification_posture", calc.POSTURE_BY_FAMILY_STATUS[family["status"]]),
    ]))
    db.platforms[platform["id"]] = platform
    return object_response(store.public(platform), 201)


@bp.route("/engine-platforms/<platform_id>", methods=["GET"])
@endpoint(READ_ROLES)
def read_platform(platform_id):
    platform = svc.get_platform(platform_id)
    return object_response(store.public(platform), 200)


@bp.route("/engine-platforms/<platform_id>/product-models", methods=["GET"])
@endpoint(READ_ROLES)
def list_platform_models(platform_id):
    limit, offset = v.pagination()
    platform = svc.get_platform(platform_id)
    rows = svc.models_of_platform(platform["id"])
    page, total = v.paginate(rows, limit, offset)
    return list_response([store.public(r) for r in page], limit, offset, total)


# -------------------------------------------------------------- durability runs

@bp.route("/durability-tests", methods=["POST"])
@endpoint(["CertificationEngineer"])
def create_durability_test():
    payload = v.body()
    family_id = v.id_field(payload, "certification_family_id")
    platform_id = v.id_field(payload, "engine_platform_id")
    start_at = v.datetime_field(payload, "scheduled_start_at")
    end_at = v.datetime_field(payload, "scheduled_end_at")
    if end_at <= start_at:
        v.bad("scheduled_end_at must be strictly after scheduled_start_at.")
    target_hours = v.int_field(payload, "target_hours", 1, 2000)
    initial_emission = v.number_field(payload, "initial_emission_g_per_kwh", exclusive_min=0)
    expected_version = v.int_field(payload, "expected_certification_family_version")

    family = svc.get_family(family_id)
    platform = svc.get_platform(platform_id)

    if expected_version != family["version"]:
        raise ApiError(
            "ERR_STALE_FAMILY_VERSION",
            "The certification family has advanced since it was read.",
        )

    if family["status"] not in ("DRAFT", "DURABILITY_TESTING", "AUDIT_HOLD"):
        raise ApiError(
            "ERR_FAMILY_STATE_INVALID",
            "The family's status does not admit scheduling a durability run.",
        )
    if family["status"] == "AUDIT_HOLD" and family["audit_hold_at"] is not None:
        hold_at = v.parse_iso_datetime(family["audit_hold_at"], "audit_hold_at")
        if start_at < hold_at:
            raise ApiError(
                "ERR_FAMILY_STATE_INVALID",
                "A remediation run must start at or after the family's audit hold.",
            )

    if platform["certification_family_id"] != family["id"]:
        raise ApiError(
            "ERR_PLATFORM_MISMATCH",
            "The named platform does not belong to the named certification family.",
        )

    for run in db.durability_tests.values():
        if run["engine_platform_id"] != platform["id"]:
            continue
        if run["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        other_start = v.parse_iso_datetime(run["scheduled_start_at"], "scheduled_start_at")
        other_end = v.parse_iso_datetime(run["scheduled_end_at"], "scheduled_end_at")
        if start_at < other_end and other_start < end_at:
            raise ApiError(
                "ERR_PLATFORM_TEST_WINDOW_OVERLAP",
                "The window overlaps another run on the same platform.",
            )

    run = store.new_record(OrderedDict([
        ("certification_family_id", family["id"]),
        ("engine_platform_id", platform["id"]),
        ("scheduled_start_at", store.iso_clock(start_at)),
        ("scheduled_end_at", store.iso_clock(end_at)),
        ("target_hours", target_hours),
        ("initial_emission_g_per_kwh", initial_emission),
        ("accumulated_hours", None),
        ("final_emission_g_per_kwh", None),
        ("df_method", calc.df_method_for(family)),
        ("computed_deterioration_factor", None),
        ("extrapolated", False),
        ("status", "SCHEDULED"),
        ("completed_at", None),
    ]))
    run["_certified_emission_g_per_kwh"] = None
    run["_compliance_margin_pct"] = None
    db.durability_tests[run["id"]] = run

    family["status"] = "DURABILITY_TESTING"
    bump(family)
    svc.recompute_postures(family)

    return object_response(store.public(run), 201)


@bp.route("/durability-tests/<run_id>", methods=["GET"])
@endpoint(READ_ROLES)
def read_durability_test(run_id):
    run = svc.get_durability_test(run_id)
    return object_response(store.public(run), 200)


@bp.route("/durability-tests", methods=["GET"])
@endpoint(READ_ROLES)
def list_durability_tests():
    limit, offset = v.pagination()
    family_id = v.query_string("certification_family_id")
    platform_id = v.query_string("engine_platform_id")
    status = v.query_enum("status", ("SCHEDULED", "COMPLETED"))
    rows = store.sort_created_asc(list(db.durability_tests.values()))
    if family_id is not None:
        rows = [r for r in rows if r["certification_family_id"] == family_id]
    if platform_id is not None:
        rows = [r for r in rows if r["engine_platform_id"] == platform_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return list_response([store.public(r) for r in page], limit, offset, total)


@bp.route("/durability-tests/<run_id>/complete", methods=["POST"])
@endpoint(["CertificationEngineer"])
def complete_durability_test(run_id):
    payload = v.body()
    accumulated_hours = v.int_field(payload, "accumulated_hours", 1, 2000)
    final_emission = v.number_field(payload, "final_emission_g_per_kwh", exclusive_min=0)

    run = svc.get_durability_test(run_id)
    family = svc.get_family(run["certification_family_id"])
    if family["status"] == "SUSPENDED":
        raise ApiError(
            "ERR_FAMILY_STATE_INVALID",
            "No operation is admitted on a SUSPENDED family.",
        )
    if run["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_DURABILITY_TEST_STATE_INVALID",
            "Only a SCHEDULED durability run may be completed.",
        )

    df_method, df, certified, margin, extrapolated = calc.deterioration(
        family, run["initial_emission_g_per_kwh"], final_emission, accumulated_hours
    )
    set_fields(
        run,
        accumulated_hours=accumulated_hours,
        final_emission_g_per_kwh=final_emission,
        df_method=df_method,
        computed_deterioration_factor=df,
        extrapolated=extrapolated,
        status="COMPLETED",
        completed_at=store.now_clock(),
    )
    run["_certified_emission_g_per_kwh"] = certified
    run["_compliance_margin_pct"] = margin

    latest = _latest_completed_run(family["id"])
    set_fields(
        family,
        deterioration_factor=latest["computed_deterioration_factor"],
        certified_emission_g_per_kwh=latest["_certified_emission_g_per_kwh"],
        compliance_margin_pct=latest["_compliance_margin_pct"],
        status="DURABILITY_COMPLETE",
    )
    svc.recompute_postures(family)

    return object_response(store.public(run), 200)


def _latest_completed_run(family_id):
    rows = [
        r for r in db.durability_tests.values()
        if r["certification_family_id"] == family_id and r["status"] == "COMPLETED"
    ]
    rows.sort(key=lambda r: (r["completed_at"], r["created_at"], r["_seq"]), reverse=True)
    return rows[0]

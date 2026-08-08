"""Biometrics and health-risk scoring (PRD 3.6)."""

from core import calc, constants, ladder, payload, serializers, store, timeutil
from core.errors import ApiError
from core.ladder import ObjectResult, Spec, paginate

from .common import filter_rows, scope_rule

_CLINIC_METRICS_INT = ("systolic_mmhg", "diastolic_mmhg", "ldl_mg_dl")
_CLINIC_METRICS_NUM = ("bmi", "a1c_pct", "cotinine_ng_ml")


def _role_extra(ctx):
    """Rung 2: only a Clinician may create a CLINIC_MEASURED row."""
    if (
        ctx.body.get("source_type") == "CLINIC_MEASURED"
        and ctx.role != constants.ROLE_CLINICIAN
    ):
        raise ApiError("ERR_FORBIDDEN_ROLE")


def _freeze(ctx):
    participant = ctx.entity("participant_id")
    employer_id = participant["employer_id"] if participant else None
    ladder.freeze_if_covered(employer_id, timeutil.parse_date(ctx.body.get("measurement_date")))


def _validate_create(ctx):
    payload.require_id(ctx.body, "participant_id")
    source_type = payload.require_present(ctx.body, "source_type")
    if not isinstance(source_type, str):
        raise ApiError("ERR_VALIDATION", "Field 'source_type' must be a string.")
    payload.require_date(ctx.body, "measurement_date")
    payload.optional_id(ctx.body, "visit_id")
    for field in _CLINIC_METRICS_INT:
        payload.optional_int(ctx.body, field)
    for field in _CLINIC_METRICS_NUM:
        payload.optional_number(ctx.body, field)
    payload.optional_bool(ctx.body, "self_reported_tobacco")

    if source_type == "CLINIC_MEASURED":
        payload.require_present(ctx.body, "visit_id")
        for field in _CLINIC_METRICS_INT + _CLINIC_METRICS_NUM:
            payload.require_present(ctx.body, field)
    elif source_type == "SELF_ATTESTED":
        payload.require_absent(ctx.body, "visit_id", "for a SELF_ATTESTED assessment")
        payload.require_present(ctx.body, "bmi")
        payload.require_present(ctx.body, "self_reported_tobacco")


def _eligible(ctx):
    participant = ctx.entity("participant_id")
    if participant is None or participant["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_NOT_ELIGIBLE_ON_DATE")
    record = store.get("eligibility", participant["eligibility_record_id"])
    measurement_date = timeutil.parse_date(ctx.body["measurement_date"])
    if record is None or not calc.coverage_covers(record, measurement_date):
        raise ApiError("ERR_NOT_ELIGIBLE_ON_DATE")


def _create(ctx):
    body = ctx.body
    source_type = body["source_type"]
    raw, total, band, met, credit = calc.health_risk_score(
        source_type,
        body.get("systolic_mmhg"),
        body.get("diastolic_mmhg"),
        body.get("bmi"),
        body.get("a1c_pct"),
        body.get("ldl_mg_dl"),
        body.get("cotinine_ng_ml"),
        body.get("self_reported_tobacco"),
    )
    row = store.insert(
        "assessment",
        {
            "participant_id": body["participant_id"],
            "visit_id": body.get("visit_id"),
            "source_type": source_type,
            "measurement_date": body["measurement_date"],
            "systolic_mmhg": body.get("systolic_mmhg"),
            "diastolic_mmhg": body.get("diastolic_mmhg"),
            "bmi": body.get("bmi"),
            "a1c_pct": body.get("a1c_pct"),
            "ldl_mg_dl": body.get("ldl_mg_dl"),
            "cotinine_ng_ml": body.get("cotinine_ng_ml"),
            "self_reported_tobacco": body.get("self_reported_tobacco"),
            "risk_points_raw": raw,
            "risk_points_total": total,
            "risk_band": band,
            "outcome_standard_met": met,
            "outcome_credit_status": credit,
        },
    )
    return ObjectResult(serializers.dump("assessment", row), 201)


def _list(ctx):
    rows = filter_rows(
        store.all_rows("assessment"),
        {
            "participant_id": ctx.args.get("participant_id"),
            "visit_id": ctx.args.get("visit_id"),
            "source_type": ctx.args.get("source_type"),
        },
    )
    return paginate(ctx, "assessment", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("assessment", ctx.entity("assessment_id")), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_CLINICIAN,
    constants.ROLE_CARE_NAVIGATOR,
    constants.ROLE_PARTICIPANT,
    constants.ROLE_EMPLOYER_BENEFITS_ADMIN,
]

SPECS = [
    Spec(
        method="POST",
        path="/health-assessments",
        roles=[constants.ROLE_CLINICIAN, constants.ROLE_PARTICIPANT],
        handler=_create,
        status=201,
        body_fks=[
            ("participant_id", "participant", True),
            ("visit_id", "visit", False),
        ],
        role_extra=_role_extra,
        scope=scope_rule(participant_of=lambda ctx: ctx.body.get("participant_id")),
        freeze=_freeze,
        payload=_validate_create,
        enums=[("source_type", "source_type")],
        checks={12: _eligible},
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/health-assessments",
        roles=_READ_ROLES,
        handler=_list,
        walled=True,
    ),
    Spec(
        method="GET",
        path="/health-assessments/{assessment_id}",
        roles=_READ_ROLES,
        handler=_read,
        walled=True,
        path_ids=[("assessment_id", "assessment")],
        scope=scope_rule(
            participant_of=lambda ctx: ctx.entity("assessment_id")["participant_id"]
        ),
    ),
]

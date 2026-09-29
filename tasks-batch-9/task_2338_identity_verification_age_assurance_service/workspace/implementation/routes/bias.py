"""Bias audits, cohort observations, disparity evaluation and remediation (PRD 3.9)."""
from flask import Blueprint

import auth
import calc
import clock
import db
import derived
import response
import schema
import services
import views
from errors import fail
from schema import Field
from . import support

bp = Blueprint("bias", __name__)

COHORT_CODES = ("AGE_13_17", "AGE_18_24", "AGE_25_44", "AGE_45_64", "AGE_65_PLUS",
                "SKIN_TONE_I_III", "SKIN_TONE_IV_VI")
LIVE_AUDIT_STATES = ("COLLECTING", "EVALUATED", "REMEDIATION_REQUIRED")

AUDIT_FIELDS = (
    Field("method_profile_id", "string", required=True),
    Field("window_start", "string", required=True),
    Field("window_end", "string", required=True),
)

COHORT_FIELDS = (
    Field("cohort_code", "string", required=True, enum=COHORT_CODES),
    Field("attempt_count", "int", required=True, minimum=0),
    Field("false_reject_count", "int", required=True, minimum=0),
    Field("false_accept_count", "int", required=True, minimum=0),
)

REMEDIATION_FIELDS = (
    Field("expected_method_profile_version", "int", required=True, minimum=0),
    Field("remediation_note", "string", required=True, min_len=1, max_len=500),
)


def _audit_or_404(audit_id):
    audit = db.get(db.BIAS_AUDITS, audit_id)
    if audit is None:
        fail("ERR_AUDIT_NOT_FOUND")
    return audit


def _parse_instant(text, field):
    parsed = clock.parse_iso(text)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC timestamp." % field)
    return parsed


@bp.post("/idv/bias-audits")
def create_bias_audit():
    auth.authenticate((auth.COMPLIANCE_OFFICER,))
    values = schema.validate(schema.read_body(), AUDIT_FIELDS)
    window_start = _parse_instant(values["window_start"], "window_start")
    window_end = _parse_instant(values["window_end"], "window_end")
    if window_end <= window_start:
        fail("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")
    profile = db.get(db.METHOD_PROFILES, values["method_profile_id"])
    if profile is None:
        fail("ERR_METHOD_PROFILE_NOT_FOUND")
    for other in derived.bias_audits_of_profile(profile["id"]):
        if other["state"] not in LIVE_AUDIT_STATES:
            continue
        if window_start < other["window_end"] and other["window_start"] < window_end:
            fail("ERR_AUDIT_WINDOW_OVERLAP")

    record = {
        "method_profile_id": profile["id"],
        "window_start": window_start,
        "window_end": window_end,
        "state": "COLLECTING",
        "remediation_round": 0,
        "included_cohort_count": 0,
        "excluded_cohort_count": 0,
        "insufficient_sample": False,
        "max_frr_bps": None,
        "min_frr_bps": None,
        "pooled_frr_bps": None,
        "disparity_ratio_max_to_min_bps": None,
        "disparity_ratio_max_to_pooled_bps": None,
        "worst_cohort_code": None,
        "evaluated_by_user_id": None,
        "remediated_by_user_id": None,
        "remediated_at": None,
    }
    db.insert(db.BIAS_AUDITS, record)
    return response.object_response(views.bias_audit_view(record), 201)


@bp.get("/idv/bias-audits/<audit_id>")
def read_bias_audit(audit_id):
    auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER))
    audit = _audit_or_404(audit_id)
    return response.object_response(views.bias_audit_view(audit))


@bp.post("/idv/bias-audits/<audit_id>/cohort-metrics")
def create_cohort_metric(audit_id):
    auth.authenticate((auth.COMPLIANCE_OFFICER,))
    audit = _audit_or_404(audit_id)
    values = schema.validate(schema.read_body(), COHORT_FIELDS)
    if values["false_reject_count"] > values["attempt_count"]:
        fail("ERR_INVALID_REQUEST", "false_reject_count must not exceed attempt_count.")
    if values["false_accept_count"] > values["attempt_count"]:
        fail("ERR_INVALID_REQUEST", "false_accept_count must not exceed attempt_count.")
    if audit["state"] != "COLLECTING":
        fail("ERR_AUDIT_STATE_INVALID")
    for existing in derived.cohort_metrics_of_audit(audit["id"]):
        if existing["cohort_code"] == values["cohort_code"]:
            fail("ERR_COHORT_DUPLICATE")

    record = {
        "bias_audit_id": audit["id"],
        "cohort_code": values["cohort_code"],
        "attempt_count": values["attempt_count"],
        "false_reject_count": values["false_reject_count"],
        "false_accept_count": values["false_accept_count"],
        "frr_bps": calc.cohort_rate(values["false_reject_count"], values["attempt_count"]),
        "far_bps": calc.cohort_rate(values["false_accept_count"], values["attempt_count"]),
        "included_in_ratio": values["attempt_count"] >= calc.MIN_COHORT_SAMPLE,
    }
    db.insert(db.COHORT_METRICS, record, versioned=False)
    return response.object_response(views.cohort_metric_view(record), 201)


@bp.get("/idv/bias-audits/<audit_id>/cohort-metrics")
def list_cohort_metrics(audit_id):
    auth.authenticate((auth.PLATFORM_ADMIN, auth.COMPLIANCE_OFFICER))
    audit = _audit_or_404(audit_id)
    records = derived.cohort_metrics_of_audit(audit["id"])
    page, limit, offset, total = support.paginated(records)
    return response.list_response([views.cohort_metric_view(m) for m in page],
                                 limit, offset, total)


@bp.post("/idv/bias-audits/<audit_id>/evaluate")
def evaluate_bias_audit(audit_id):
    caller = auth.authenticate((auth.COMPLIANCE_OFFICER,))
    audit = _audit_or_404(audit_id)
    schema.no_body()
    if audit["state"] != "COLLECTING":
        fail("ERR_AUDIT_STATE_INVALID")
    profile = db.get(db.METHOD_PROFILES, audit["method_profile_id"])
    if profile is not None and profile["bias_state"] == "RESTRICTED":
        fail("ERR_METHOD_RESTRICTED_BY_BIAS")

    in_scope = [m for m in derived.cohort_metrics_of_audit(audit["id"])
                if audit["remediated_at"] is None or m["created_at"] >= audit["remediated_at"]]
    if len(in_scope) < calc.MIN_COHORT_COUNT:
        fail("ERR_INSUFFICIENT_COHORT_COVERAGE")

    included = [m for m in in_scope if m["included_in_ratio"]]
    audit["included_cohort_count"] = len(included)
    audit["excluded_cohort_count"] = len(in_scope) - len(included)
    audit["evaluated_by_user_id"] = caller.user_id

    if len(included) < 2:
        audit["insufficient_sample"] = True
        audit["max_frr_bps"] = None
        audit["min_frr_bps"] = None
        audit["pooled_frr_bps"] = None
        audit["disparity_ratio_max_to_min_bps"] = None
        audit["disparity_ratio_max_to_pooled_bps"] = None
        audit["worst_cohort_code"] = None
        audit["state"] = "EVALUATED"
        db.touch(audit)
        return response.object_response(views.bias_audit_view(audit))

    audit["insufficient_sample"] = False
    max_frr = max(m["frr_bps"] for m in included)
    min_frr = min(m["frr_bps"] for m in included)
    pooled = calc.round_half_up_div(
        10000 * sum(m["false_reject_count"] for m in included),
        sum(m["attempt_count"] for m in included))
    worst = sorted([m for m in included if m["frr_bps"] == max_frr],
                   key=lambda m: m["cohort_code"])[0]
    audit["max_frr_bps"] = max_frr
    audit["min_frr_bps"] = min_frr
    audit["pooled_frr_bps"] = pooled
    audit["worst_cohort_code"] = worst["cohort_code"]
    audit["disparity_ratio_max_to_min_bps"] = (
        None if min_frr == 0 else calc.round_half_up_div(10000 * max_frr, min_frr))
    gating = None if pooled == 0 else calc.round_half_up_div(10000 * max_frr, pooled)
    audit["disparity_ratio_max_to_pooled_bps"] = gating

    if gating is not None and gating >= calc.DISPARITY_RESTRICT_BPS:
        audit["state"] = "REMEDIATION_REQUIRED"
        db.touch(audit)
        services.apply_restriction_cascade(profile, caller)
    elif gating is not None and gating >= calc.DISPARITY_MONITOR_BPS:
        audit["state"] = "EVALUATED"
        db.touch(audit)
        if profile is not None:
            profile["bias_state"] = "MONITORED"
            db.touch(profile)
    else:
        if audit["remediation_round"] >= 1:
            audit["state"] = "REMEDIATED"
        else:
            audit["state"] = "EVALUATED"
        db.touch(audit)
        if profile is not None:
            profile["bias_state"] = "CLEARED"
            profile["restricted_at"] = None
            db.touch(profile)
    return response.object_response(views.bias_audit_view(audit))


@bp.post("/idv/bias-audits/<audit_id>/remediation")
def remediate_bias_audit(audit_id):
    caller = auth.authenticate((auth.COMPLIANCE_OFFICER,))
    audit = _audit_or_404(audit_id)
    values = schema.validate(schema.read_body(), REMEDIATION_FIELDS)
    if audit["state"] != "REMEDIATION_REQUIRED":
        fail("ERR_AUDIT_STATE_INVALID")
    profile = db.get(db.METHOD_PROFILES, audit["method_profile_id"])
    current_version = profile["version"] if profile is not None else None
    if values["expected_method_profile_version"] != current_version:
        fail("ERR_STALE_METHOD_PROFILE_VERSION")
    if audit["evaluated_by_user_id"] == caller.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    audit["state"] = "COLLECTING"
    audit["remediation_round"] = audit["remediation_round"] + 1
    audit["remediated_at"] = clock.now()
    audit["remediated_by_user_id"] = caller.user_id
    db.touch(audit)
    services.apply_remediation_cascade(profile, caller)
    return response.object_response(views.bias_audit_view(audit))

"""Composite setup helpers for the MRM test suite.

Every helper builds preconditions from scratch through the public API (the server
is restarted and the database emptied before each test). Helpers use the lenient
``get_success_data`` validator so setup failures surface as clear setup errors.

Default actor wiring (opaque operator ids):
  - models are registered by u_own_a (ModelOwner) unless overridden;
  - documentation decisions and other officer actions run as u_cro;
  - engagements are opened/completed by u_val (independent of u_own_a, satisfying
    the segregation-of-duties gate);
  - clock control runs as u_admin (PlatformAdmin).
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    U_OWN_A,
    U_VAL,
    make_owner_headers,
    make_risk_officer_headers,
    make_validator_headers,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OWNER_B = TEST_USERS["model_owner_b_headers"]
VALIDATOR = TEST_USERS["model_validator_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]
REPORTER = TEST_USERS["reporter_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------

def create_model(
    name=None,
    declared_complexity="LOW",
    usage_scope="SINGLE_DESK",
    exposure_amount=100,
    is_vendor_model=None,
    business_unit="Risk",
    owner_headers=None,
):
    """Register a model. ``is_vendor_model=None`` omits the optional flag entirely
    (server applies its default). Returns the created Model."""
    payload = factories.create_model_payload(
        business_unit=business_unit,
        declared_complexity=declared_complexity,
        usage_scope=usage_scope,
        exposure_amount=exposure_amount,
    )
    if name is not None:
        payload["name"] = name
    if is_vendor_model is not None:
        payload["is_vendor_model"] = is_vendor_model
    resp = api_client.create_model(payload, owner_headers or OWNER_A)
    return get_success_data(resp)


def get_model(model_id, headers=None):
    return get_success_data(api_client.get_model(model_id, headers or OFFICER))


def submit_documentation(model_id, owner_headers=None, version_label="1.0", **flags):
    payload = factories.create_documentation_payload(version_label=version_label, **flags)
    resp = api_client.submit_documentation(model_id, payload, owner_headers or OWNER_A)
    return get_success_data(resp)


def decide_documentation(model_id, doc_id, decision="APPROVE", officer_headers=None):
    resp = api_client.decide_documentation(
        model_id, doc_id, factories.decide_payload(decision), officer_headers or OFFICER
    )
    return get_success_data(resp)


def create_model_with_approved_doc(doc_label="1.0", owner_headers=None, **model_kwargs):
    """Model + one documentation package approved by the risk officer.
    Returns (model, doc)."""
    owner_headers = owner_headers or OWNER_A
    model = create_model(owner_headers=owner_headers, **model_kwargs)
    doc = submit_documentation(model["id"], owner_headers=owner_headers, version_label=doc_label)
    doc = decide_documentation(model["id"], doc["id"], "APPROVE")
    return model, doc


def open_engagement(
    model_id,
    period_start="2026-08-01T00:00:00Z",
    period_end="2026-08-01T06:00:00Z",
    scope_conceptual_soundness=True,
    scope_outcomes_analysis=True,
    validator_headers=None,
):
    payload = factories.create_engagement_payload(
        period_start=period_start,
        period_end=period_end,
        scope_conceptual_soundness=scope_conceptual_soundness,
        scope_outcomes_analysis=scope_outcomes_analysis,
    )
    resp = api_client.create_engagement(model_id, payload, validator_headers or VALIDATOR)
    return get_success_data(resp)


def complete_engagement(engagement_id, outcome="EFFECTIVE", assessed_complexity="LOW", validator_headers=None):
    resp = api_client.complete_engagement(
        engagement_id,
        factories.complete_engagement_payload(outcome, assessed_complexity),
        validator_headers or VALIDATOR,
    )
    return get_success_data(resp)


def reopen_engagement(engagement_id, validator_headers=None):
    return get_success_data(api_client.reopen_engagement(engagement_id, validator_headers or VALIDATOR))


def create_finding(model_id, severity="LOW", title=None, raiser_headers=None):
    payload = factories.create_finding_payload(severity, title)
    resp = api_client.create_finding(model_id, payload, raiser_headers or OFFICER)
    return get_success_data(resp)


def create_change_request(model_id, change_type, expected_model_version, owner_headers=None, description=None):
    payload = factories.create_change_request_payload(change_type, expected_model_version)
    if description is not None:
        payload["description"] = description
    resp = api_client.create_change_request(model_id, payload, owner_headers or OWNER_A)
    return get_success_data(resp)


def decide_change_request(model_id, cr_id, decision="APPROVE", officer_headers=None):
    resp = api_client.decide_change_request(
        model_id, cr_id, factories.decide_payload(decision), officer_headers or OFFICER
    )
    return get_success_data(resp)


def create_vendor_assessment(model_id, completeness_score=80, valid_months=6, officer_headers=None):
    payload = factories.create_vendor_assessment_payload(completeness_score, valid_months)
    resp = api_client.create_vendor_assessment(model_id, payload, officer_headers or OFFICER)
    return get_success_data(resp)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: approvable / approved model chains
# ---------------------------------------------------------------------------

def create_approvable_model(
    assessed_complexity="LOW",
    outcome="EFFECTIVE",
    eng_window=("2026-08-01T00:00:00Z", "2026-08-01T06:00:00Z"),
    vendor_completeness=80,
    vendor_valid_months=12,
    owner_headers=None,
    validator_headers=None,
    **model_kwargs,
):
    """Model with an APPROVED documentation package and one COMPLETED engagement
    (validator independent of the owner). Still REGISTERED. For vendor models a
    CURRENT vendor assessment (default completeness 80) is recorded so the vendor
    gate can pass. Returns a dict with model/doc/engagement."""
    owner_headers = owner_headers or OWNER_A
    validator_headers = validator_headers or VALIDATOR
    model, doc = create_model_with_approved_doc(owner_headers=owner_headers, **model_kwargs)
    eng = open_engagement(
        model["id"],
        period_start=eng_window[0],
        period_end=eng_window[1],
        validator_headers=validator_headers,
    )
    eng = complete_engagement(eng["id"], outcome=outcome, assessed_complexity=assessed_complexity,
                              validator_headers=validator_headers)
    assessment = None
    if model.get("is_vendor_model"):
        assessment = create_vendor_assessment(
            model["id"], completeness_score=vendor_completeness, valid_months=vendor_valid_months
        )
    return {
        "model": get_model(model["id"]),
        "doc": doc,
        "engagement": eng,
        "assessment": assessment,
        "owner_headers": owner_headers,
        "validator_headers": validator_headers,
    }


def approve_model(model_id, officer_headers=None):
    return get_success_data(api_client.approve_model(model_id, officer_headers or OFFICER))


def create_approved_model(**kwargs):
    """Model walked all the way to APPROVED_FOR_USE. Returns the ctx dict from
    create_approvable_model with the refreshed model."""
    ctx = create_approvable_model(**kwargs)
    ctx["model"] = approve_model(ctx["model"]["id"])
    return ctx


def add_metric(
    model_id,
    metric_name="psi",
    direction="ABOVE_IS_BREACH",
    threshold_value=0.25,
    owner_headers=None,
):
    payload = factories.create_metric_payload(metric_name, direction, threshold_value)
    resp = api_client.create_metric(model_id, payload, owner_headers or OWNER_A)
    return get_success_data(resp)


def create_approved_model_with_metric(
    metric_name="psi",
    direction="ABOVE_IS_BREACH",
    threshold_value=0.25,
    **model_kwargs,
):
    """APPROVED_FOR_USE model plus one ACTIVE monitoring metric.
    Returns (model, metric, ctx)."""
    ctx = create_approved_model(**model_kwargs)
    metric = add_metric(
        ctx["model"]["id"], metric_name, direction, threshold_value, owner_headers=ctx["owner_headers"]
    )
    return ctx["model"], metric, ctx


def record_reading(metric_id, value, observed_at, owner_headers=None):
    payload = factories.create_reading_payload(value, observed_at)
    resp = api_client.record_reading(metric_id, payload, owner_headers or OWNER_A)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: suspension / retirement composite states
# ---------------------------------------------------------------------------

def create_suspended_tier1_model(
    severity="CRITICAL",
    finding_time="2026-08-02T00:00:00Z",
    sweep_to="2026-08-24T00:00:00Z",
    metric_names=("psi",),
    eng_window=("2026-08-01T00:00:00Z", "2026-08-01T06:00:00Z"),
):
    """APPROVED_FOR_USE TIER_1 model (HIGH / SINGLE_DESK / 100, completed with
    assessed HIGH) with ACTIVE metrics, driven to SUSPENDED by an escalating
    HIGH|CRITICAL finding via the clock sweep. Returns a dict with model, metrics
    (name -> metric), finding, and actor headers.

    Default timing: CRITICAL finding created at logical 2026-08-02 -> due
    2026-08-16 (14 days at TIER_1) -> escalates once now > 2026-08-23; the sweep
    to 2026-08-24 escalates it and suspends the model.
    """
    ctx = create_approved_model(
        declared_complexity="HIGH",
        usage_scope="SINGLE_DESK",
        exposure_amount=100,
        assessed_complexity="HIGH",
        eng_window=eng_window,
    )
    model = ctx["model"]
    metrics = {}
    for name in metric_names:
        direction = "BELOW_IS_BREACH" if name == "auc" else "ABOVE_IS_BREACH"
        threshold = 0.7 if name == "auc" else 0.25
        metrics[name] = add_metric(model["id"], name, direction, threshold, owner_headers=ctx["owner_headers"])
    set_clock(finding_time)
    finding = create_finding(model["id"], severity=severity, title="suspend driver")
    set_clock(sweep_to)
    return {
        "model": get_model(model["id"]),
        "metrics": metrics,
        "finding": finding,
        "ctx": ctx,
        "owner_headers": ctx["owner_headers"],
    }


def create_retired_pair(**model_kwargs):
    """Two fully approved models; the first retired into the second.
    Returns (retired_model, replacement_model)."""
    kwargs = {"declared_complexity": "LOW", "usage_scope": "SINGLE_DESK", "exposure_amount": 100, **model_kwargs}
    ctx1 = create_approved_model(**kwargs)
    ctx2 = create_approved_model(**kwargs)
    retired = get_success_data(api_client.retire_model(
        ctx1["model"]["id"], {"replacement_model_id": ctx2["model"]["id"]}, OFFICER
    ))
    return retired, get_model(ctx2["model"]["id"])


# ---------------------------------------------------------------------------
# Tier 4: monitoring / breach accumulation
# ---------------------------------------------------------------------------

def record_breach_run(metric_id, values, start_date="2026-08-02", owner_headers=None):
    """Record readings at consecutive days from start_date (YYYY-MM-DD).
    Returns the list of created readings."""
    readings = []
    yyyy, mm, dd = (int(p) for p in start_date.split("-"))
    for i, value in enumerate(values):
        day = dd + i
        observed = f"{yyyy:04d}-{mm:02d}-{day:02d}T00:00:00Z"
        readings.append(record_reading(metric_id, value, observed, owner_headers=owner_headers))
    return readings


def setup_metric_with_breaches(num_breaches, breach_value=0.30, **model_kwargs):
    """Approved model with metric psi (ABOVE 0.25) and num_breaches consecutive
    breaching readings. Returns (model, metric, ctx)."""
    model, metric, ctx = create_approved_model_with_metric(**model_kwargs)
    for i in range(num_breaches):
        record_reading(
            metric["id"],
            breach_value + i * 0.01,
            f"2026-08-{2 + i:02d}T00:00:00Z",
            owner_headers=ctx["owner_headers"],
        )
    return get_model(model["id"]), get_success_data(api_client.get_metric(metric["id"], OWNER_A)), ctx


# ---------------------------------------------------------------------------
# Tier 5: reporting
# ---------------------------------------------------------------------------

def create_draft_report(
    report_type="BOARD_QUARTERLY",
    period_start="2026-07-01T00:00:00Z",
    period_end="2026-09-30T00:00:00Z",
    aggregation_method="EQUAL_WEIGHTED",
):
    payload = factories.create_report_payload(report_type, period_start, period_end, aggregation_method)
    return get_success_data(api_client.create_report(payload, REPORTER))


def create_submitted_report(**kwargs):
    report = create_draft_report(**kwargs)
    return get_success_data(api_client.submit_report(report["id"], REPORTER))


def make_officer_headers_for(user_id):
    return make_risk_officer_headers(user_id)


def make_validator_headers_for(user_id):
    return make_validator_headers(user_id)


def make_owner_headers_for(user_id):
    return make_owner_headers(user_id)

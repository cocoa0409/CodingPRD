"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so every helper here builds its preconditions from scratch
using only PRD-declared endpoints. Helpers use the lenient get_success_data()
validator so setup failures surface as clear "Setup step failed" errors.

Identity threading: Underwriter and Inspector are entity_backed; any ownership /
identity-resolved call uses make_underwriter_headers(uw_id) /
make_inspector_headers(insp_id) with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_agent_headers,
    make_underwriter_headers,
    make_inspector_headers,
)
from . import factories as f

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]


# --- Default epoch windows / coverage dates (well past Unix epoch, no collisions
#     within a single test because each test owns a fresh DB). ---
DEFAULT_WINDOW_START = 1750000000
DEFAULT_WINDOW_END = 1750007200
DEFAULT_EFFECTIVE = 1751000000
DEFAULT_EXPIRATION = 1782536000


# ---------------------------------------------------------------------------
# Tier 0: single-entity primitives
# ---------------------------------------------------------------------------
def create_underwriter(authority_limit=1000000, full_name="Uma UW") -> dict:
    resp = api_client.create_underwriter(
        f.create_underwriter_payload(full_name=full_name, authority_limit=authority_limit), ADMIN
    )
    return get_success_data(resp)


def create_inspector(buffer_minutes=60, full_name="Ivy Insp", license_state="CA") -> dict:
    resp = api_client.create_inspector(
        f.create_inspector_payload(
            full_name=full_name, license_state=license_state, buffer_minutes=buffer_minutes
        ),
        ADMIN,
    )
    return get_success_data(resp)


def create_property(**overrides) -> dict:
    resp = api_client.create_property(f.create_property_payload(**overrides), AGENT)
    return get_success_data(resp)


def commit_estimate(property_id, method="COMPONENT") -> dict:
    resp = api_client.estimate_replacement_cost(
        property_id, f.estimate_payload(method=method), AGENT
    )
    return get_success_data(resp)


def create_risk_assessment(property_id, **overrides) -> dict:
    resp = api_client.create_risk_assessment(
        f.create_risk_assessment_payload(property_id, **overrides),
        TEST_USERS["underwriter_headers"],
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: property prepared for application (estimate + risk assessment)
# ---------------------------------------------------------------------------
def setup_estimated_property(method="COMPONENT", ra_overrides=None, **prop_overrides):
    """ACTIVE Property with a committed estimate and a PROVISIONAL RiskAssessment.
    Returns (property, risk_assessment)."""
    prop = create_property(**prop_overrides)
    commit_estimate(prop["id"], method=method)
    ra = create_risk_assessment(prop["id"], **(ra_overrides or {}))
    # re-read property to get the post-estimate replacement_cost / tiv
    prop = get_success_data(api_client.get_property(prop["id"], AGENT))
    return prop, ra


# ---------------------------------------------------------------------------
# Tier 1b: inspection lifecycle
# ---------------------------------------------------------------------------
def schedule_inspection(property_id, inspector_id, window_start=DEFAULT_WINDOW_START,
                        window_end=DEFAULT_WINDOW_END) -> dict:
    resp = api_client.create_inspection(
        f.create_inspection_payload(property_id, inspector_id, window_start, window_end),
        TEST_USERS["underwriter_headers"],
    )
    return get_success_data(resp)


def complete_inspection(inspection_id, inspector_id, roof_ok=True, electrical_ok=True,
                        plumbing_ok=True, hvac_ok=True) -> dict:
    resp = api_client.complete_inspection(
        inspection_id,
        f.complete_inspection_payload(roof_ok, electrical_ok, plumbing_ok, hvac_ok),
        make_inspector_headers(inspector_id),
    )
    return get_success_data(resp)


def setup_passed_inspection(property_id, inspector_id=None,
                            window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END):
    """Schedule + complete (all 4 points) so the inspection PASSES and the
    property's RiskAssessment goes FINAL. Returns (inspector_id, inspection)."""
    if inspector_id is None:
        inspector_id = create_inspector()["id"]
    insp = schedule_inspection(property_id, inspector_id, window_start, window_end)
    insp = complete_inspection(insp["id"], inspector_id)
    return inspector_id, insp


# ---------------------------------------------------------------------------
# Tier 2: application lifecycle
# ---------------------------------------------------------------------------
def create_application(property_id, requested_coverage_a=300000, wind_hail_deductible_pct=None) -> dict:
    overrides = {}
    if wind_hail_deductible_pct is not None:
        overrides["wind_hail_deductible_pct"] = wind_hail_deductible_pct
    resp = api_client.create_application(
        f.create_application_payload(property_id, requested_coverage_a, **overrides), AGENT
    )
    return get_success_data(resp)


def create_endorsement(application_id, kind, peril_code, coverage_limit=None) -> dict:
    resp = api_client.create_endorsement(
        f.create_endorsement_payload(application_id, kind, peril_code, coverage_limit), AGENT
    )
    return get_success_data(resp)


def attach_endorsement(endorsement_id) -> dict:
    resp = api_client.attach_endorsement(endorsement_id, AGENT)
    return get_success_data(resp)


def submit_application(application_id) -> dict:
    resp = api_client.submit_application(application_id, AGENT)
    return get_success_data(resp)


def take_review(application_id, uw_id) -> dict:
    resp = api_client.take_review_application(application_id, make_underwriter_headers(uw_id))
    return get_success_data(resp)


def setup_submitted_application(requested_coverage_a=300000, wind_hail_deductible_pct=None,
                                method="COMPONENT", ra_overrides=None, prop_overrides=None):
    """A SUBMITTED application on an estimated property with a risk assessment.
    Returns (property, risk_assessment, application)."""
    prop, ra = setup_estimated_property(
        method=method, ra_overrides=ra_overrides, **(prop_overrides or {})
    )
    app = create_application(prop["id"], requested_coverage_a, wind_hail_deductible_pct)
    app = submit_application(app["id"])
    return prop, ra, app


def setup_under_review_application(requested_coverage_a=300000, wind_hail_deductible_pct=None,
                                   authority_limit=1000000, method="COMPONENT",
                                   ra_overrides=None, prop_overrides=None,
                                   with_passed_inspection=False):
    """An UNDER_REVIEW application assigned to a fresh underwriter.
    Optionally also creates a PASSED inspection (so the property's RA is FINAL).
    Returns dict with keys: property, risk_assessment, application, underwriter,
    app_version (the version observed right after take-review)."""
    uw = create_underwriter(authority_limit=authority_limit)
    prop, ra = setup_estimated_property(
        method=method, ra_overrides=ra_overrides, **(prop_overrides or {})
    )
    inspection = None
    inspector_id = None
    if with_passed_inspection:
        inspector_id, inspection = setup_passed_inspection(prop["id"])
    app = create_application(prop["id"], requested_coverage_a, wind_hail_deductible_pct)
    app = submit_application(app["id"])
    app = take_review(app["id"], uw["id"])
    return {
        "property": prop,
        "risk_assessment": ra,
        "application": app,
        "underwriter": uw,
        "inspector_id": inspector_id,
        "inspection": inspection,
        "app_version": app["version"],
    }


# ---------------------------------------------------------------------------
# Tier 3: bind -> policy lifecycle
# ---------------------------------------------------------------------------
def bind_application(application_id, expected_version, uw_id,
                     effective_date=DEFAULT_EFFECTIVE, expiration_date=DEFAULT_EXPIRATION) -> dict:
    resp = api_client.bind_application(
        application_id,
        f.bind_application_payload(effective_date, expiration_date, expected_version),
        make_underwriter_headers(uw_id),
    )
    return get_success_data(resp)


def get_policy_for_application(application_id) -> dict:
    data, _ = _paginate(api_client.list_policies(
        TEST_USERS["underwriter_headers"], params={"application_id": application_id}
    ))
    assert data, f"No policy found for application {application_id}"
    return data[0]


def _paginate(resp):
    body = resp.json()
    return body["data"], body.get("meta", {})


def setup_bound_policy(requested_coverage_a=300000, wind_hail_deductible_pct=2,
                       endorsements=None, effective_date=DEFAULT_EFFECTIVE,
                       expiration_date=DEFAULT_EXPIRATION, authority_limit=1000000,
                       ra_overrides=None, prop_overrides=None):
    """Full chain through to a PENDING_PAYMENT Policy created by bind.

    endorsements: optional list of (kind, peril_code, coverage_limit) tuples,
    each created as DRAFT and attached (PENDING) before submit, so they become
    APPLIED on bind.

    Returns dict: property, risk_assessment, application(BOUND), underwriter,
    policy(PENDING_PAYMENT), endorsements(list of attached endorsement dicts),
    inspector_id.
    """
    uw = create_underwriter(authority_limit=authority_limit)
    prop, ra = setup_estimated_property(ra_overrides=ra_overrides, **(prop_overrides or {}))
    inspector_id, _ = setup_passed_inspection(prop["id"])
    app = create_application(prop["id"], requested_coverage_a, wind_hail_deductible_pct)

    endo_objs = []
    for (kind, peril_code, coverage_limit) in (endorsements or []):
        e = create_endorsement(app["id"], kind, peril_code, coverage_limit)
        e = attach_endorsement(e["id"])
        endo_objs.append(e)

    app = submit_application(app["id"])
    app = take_review(app["id"], uw["id"])
    app = bind_application(app["id"], app["version"], uw["id"], effective_date, expiration_date)
    policy = get_policy_for_application(app["id"])
    return {
        "property": prop,
        "risk_assessment": ra,
        "application": app,
        "underwriter": uw,
        "policy": policy,
        "endorsements": endo_objs,
        "inspector_id": inspector_id,
    }


def pay_binding(policy_id, amount) -> dict:
    resp = api_client.create_payment(
        f.create_payment_payload(policy_id, "BINDING", amount), AGENT
    )
    return get_success_data(resp)


def pay_reinstatement(policy_id, amount) -> dict:
    resp = api_client.create_payment(
        f.create_payment_payload(policy_id, "REINSTATEMENT", amount), AGENT
    )
    return get_success_data(resp)


def setup_active_policy(requested_coverage_a=300000, wind_hail_deductible_pct=2,
                        endorsements=None, binding_amount=997.50,
                        effective_date=DEFAULT_EFFECTIVE, expiration_date=DEFAULT_EXPIRATION,
                        authority_limit=1000000, ra_overrides=None, prop_overrides=None):
    """Bound policy + settled binding payment -> ACTIVE.

    Returns the same dict as setup_bound_policy, but with policy re-read in
    ACTIVE state and an extra key 'payment'.
    """
    ctx = setup_bound_policy(
        requested_coverage_a=requested_coverage_a,
        wind_hail_deductible_pct=wind_hail_deductible_pct,
        endorsements=endorsements,
        effective_date=effective_date,
        expiration_date=expiration_date,
        authority_limit=authority_limit,
        ra_overrides=ra_overrides,
        prop_overrides=prop_overrides,
    )
    payment = pay_binding(ctx["policy"]["id"], binding_amount)
    ctx["payment"] = payment
    ctx["policy"] = get_success_data(
        api_client.get_policy(ctx["policy"]["id"], TEST_USERS["underwriter_headers"])
    )
    return ctx


def lapse_policy(policy_id, expected_version, uw_id) -> dict:
    resp = api_client.lapse_policy(
        policy_id, {"expected_policy_version": expected_version}, make_underwriter_headers(uw_id)
    )
    return get_success_data(resp)


def cancel_policy(policy_id, uw_id) -> dict:
    resp = api_client.cancel_policy(policy_id, make_underwriter_headers(uw_id))
    return get_success_data(resp)


def remove_endorsement(endorsement_id, uw_id) -> dict:
    resp = api_client.remove_endorsement(endorsement_id, make_underwriter_headers(uw_id))
    return get_success_data(resp)


def get_property(property_id) -> dict:
    return get_success_data(api_client.get_property(property_id, AGENT))


def get_policy(policy_id) -> dict:
    return get_success_data(
        api_client.get_policy(policy_id, TEST_USERS["underwriter_headers"])
    )


def get_endorsement(endorsement_id) -> dict:
    return get_success_data(api_client.get_endorsement(endorsement_id, AGENT))


def get_risk_assessment(ra_id) -> dict:
    return get_success_data(
        api_client.get_risk_assessment(ra_id, TEST_USERS["underwriter_headers"])
    )


def get_quote_for_application(application_id) -> dict:
    """Latest BOUND_OFFER quote for an application (or first quote if none)."""
    data, _ = _paginate(api_client.list_quotes(
        AGENT, params={"application_id": application_id}
    ))
    assert data, f"No quote found for application {application_id}"
    bound = [q for q in data if q.get("status") == "BOUND_OFFER"]
    return bound[0] if bound else data[0]

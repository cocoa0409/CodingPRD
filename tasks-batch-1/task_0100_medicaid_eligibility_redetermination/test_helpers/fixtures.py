"""Composite setup helpers.

Encapsulates the multi-step setup sequences that the eligibility lifecycle
requires so tests focus on assertions, not plumbing. Every fixture builds its
preconditions from scratch (the server starts against an empty database before
every test) using only PRD-declared endpoints.

Fixtures use get_success_data() (lenient) internally so a setup failure surfaces
clearly rather than as a confusing assertion failure deep in a test.

Conventions
-----------
- All config/state-mutating CaseWorker calls use a single caseworker identity by
  default; segregation-of-duties fixtures take explicit operator ids.
- The MAGI scenarios use a size-1 CA household with WAGES monthly 120000, which
  is comfortably ELIGIBLE, so the application can be approved and enrolled.
- To drive a redetermination to TERMINATED we raise the household's income before
  the renewal determination so the fresh determination comes back INELIGIBLE.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client as _api
from .test_users import TEST_USERS, make_caseworker_headers, make_hearing_officer_headers
from .factories import (
    create_fpl_schedule_payload,
    create_state_rule_payload,
    create_household_payload,
    create_member_payload,
    create_income_source_payload,
    create_application_payload,
    create_enrollment_payload,
    create_redetermination_payload,
    create_appeal_payload,
)

CW = TEST_USERS["caseworker_headers"]
APP = TEST_USERS["applicant_headers"]
HO = TEST_USERS["hearing_officer_headers"]


def _d(resp):
    """Lenient extract of the data payload from a setup response."""
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 0: reference configuration
# ---------------------------------------------------------------------------
def setup_config(state="CA", **state_overrides):
    """Create the 2026 FPL schedule and a state rule. Returns (fpl, state_rule).

    Pass state="TX" for the non-expansion state, or override individual
    state-rule fields (e.g. continuous_coverage_active=True)."""
    fpl = _d(_api.create_fpl_schedule(create_fpl_schedule_payload(), CW))
    if state == "TX":
        from .constants import STATE_RULE_TX
        payload = dict(STATE_RULE_TX)
        payload.update(state_overrides)
    else:
        payload = create_state_rule_payload(**state_overrides)
    rule = _d(_api.create_state_rule(payload, CW))
    return fpl, rule


# ---------------------------------------------------------------------------
# Tier 1 / 2: household assembly
# ---------------------------------------------------------------------------
def setup_household(state="CA", name="Test Applicant", **state_overrides):
    """Config + an empty household in `state`. Returns the household dict."""
    setup_config(state=state, **state_overrides)
    hh = _d(_api.create_household(
        create_household_payload(state_code=state, primary_applicant_name=name), CW))
    return hh


def add_member(household_id, **overrides):
    """Add one member to a household. Returns the member dict."""
    return _d(_api.add_member(household_id, create_member_payload(**overrides), CW))


def add_income(member_id, **overrides):
    """Add one income source to a member. Returns the income source dict."""
    return _d(_api.add_income_source(member_id, create_income_source_payload(**overrides), CW))


def add_asset(household_id, asset_type, value_cents):
    """Add one asset to a household. Returns the asset dict."""
    return _d(_api.add_asset(household_id, {"asset_type": asset_type, "value_cents": value_cents}, CW))


def setup_household_with_member(state="CA", member_overrides=None, income_overrides=None):
    """Config + household + one COUNTED member + (optionally) one income source.

    Returns (household, member). If income_overrides is provided an income source
    is added; pass income_overrides={} for the default WAGES 120000 source."""
    hh = setup_household(state=state)
    member = add_member(hh["id"], **(member_overrides or {}))
    if income_overrides is not None:
        add_income(member["id"], **income_overrides)
    return hh, member


# ---------------------------------------------------------------------------
# Tier 3: application lifecycle
# ---------------------------------------------------------------------------
def open_application(household_id, **overrides):
    """Open a DRAFT application against a household. Returns the application dict."""
    return _d(_api.create_application(household_id, create_application_payload(**overrides), CW))


def setup_application_under_review(state="CA", app_overrides=None, member_overrides=None,
                                   income_overrides=None, cw_headers=None):
    """Config + household + member + (optional income) + application taken to
    UNDER_REVIEW (DRAFT -> submit -> claim-review).

    cw_headers pins the claiming CaseWorker identity (assigned_caseworker_id).
    Returns (household, member, application)."""
    cw = cw_headers or CW
    hh, member = setup_household_with_member(
        state=state, member_overrides=member_overrides, income_overrides=income_overrides)
    app = open_application(hh["id"], **(app_overrides or {}))
    _api.submit_application(app["id"], APP)
    _api.claim_review(app["id"], cw)
    app = _d(_api.get_application(app["id"], CW))
    return hh, member, app


def setup_eligible_approved_application(state="CA", income_monthly=120000,
                                        member_overrides=None, cw_headers=None):
    """Config + size-1 household + WAGES income + application run through to
    review_status=APPROVED (determination ELIGIBLE, verified, decided APPROVED).

    Returns (household, member, application, determination)."""
    cw = cw_headers or CW
    hh, member, app = setup_application_under_review(
        state=state,
        member_overrides=member_overrides,
        income_overrides={"monthly_amount_cents": income_monthly},
        cw_headers=cw,
    )
    det = _d(_api.run_determination(app["id"], CW))
    _api.verify_application(app["id"], CW)
    _api.decide_application(app["id"], {"target_status": "APPROVED"}, CW)
    app = _d(_api.get_application(app["id"], CW))
    return hh, member, app, det


# ---------------------------------------------------------------------------
# Tier 4 / 5: enrollment + redetermination + appeal lifecycles
# ---------------------------------------------------------------------------
def setup_active_enrollment(state="CA", income_monthly=120000, second_member=False,
                            cw_headers=None, **enrollment_overrides):
    """Full chain to an ACTIVE enrollment.

    Builds an eligible approved application, creates the enrollment, activates it.
    With second_member=True a SPOUSE is added before approval so household_size=2
    (member_months becomes 24). Returns (household, application, enrollment, member).
    The returned enrollment dict is the activation response (carries the post-activate
    version in enrollment["version"])."""
    cw = cw_headers or CW
    hh, member, app, _det = setup_eligible_approved_application(
        state=state, income_monthly=income_monthly, cw_headers=cw)
    if second_member:
        add_member(hh["id"], full_name="Spouse", age=28, relationship="SPOUSE")
        # Re-approval is not needed; size is read at activation time.
    enr = _d(_api.create_enrollment(
        create_enrollment_payload(hh["id"], app["id"], **enrollment_overrides), CW))
    activated = _d(_api.activate_enrollment(enr["id"], cw))
    return hh, app, activated, member


def setup_in_redetermination(state="CA", make_ineligible=False, second_member=False,
                             cw_headers=None, **state_overrides):
    """Full chain to an enrollment in IN_REDETERMINATION with an INITIATED
    redetermination open over [2026-11-01, 2026-12-15).

    If make_ineligible=True, the household income is raised before the renewal
    determination so that fresh determination comes back INELIGIBLE (used to drive
    a TERMINATED finalize). Returns
    (household, application, enrollment, redetermination, renewal_determination)."""
    cw = cw_headers or CW
    # Build config with any state overrides (e.g. continuous_coverage_active).
    setup_config(state=state, **state_overrides)
    hh = _d(_api.create_household(
        create_household_payload(state_code=state, primary_applicant_name="Redet HH"), CW))
    member = add_member(hh["id"])
    add_income(member["id"], income_type="WAGES", monthly_amount_cents=120000)
    if second_member:
        add_member(hh["id"], full_name="Spouse", age=28, relationship="SPOUSE")
    app = open_application(hh["id"])
    _api.submit_application(app["id"], APP)
    _api.claim_review(app["id"], cw)
    _api.run_determination(app["id"], CW)
    _api.verify_application(app["id"], CW)
    _api.decide_application(app["id"], {"target_status": "APPROVED"}, CW)
    enr = _d(_api.create_enrollment(create_enrollment_payload(hh["id"], app["id"]), CW))
    activated = _d(_api.activate_enrollment(enr["id"], cw))
    enr_v = activated["version"]
    # Renewal determination: optionally raise income so it lands INELIGIBLE.
    if make_ineligible:
        add_income(member["id"], income_type="WAGES", monthly_amount_cents=900000)
    renewal_det = _d(_api.run_determination(app["id"], CW))
    redet = _d(_api.create_redetermination(
        create_redetermination_payload(enr["id"], renewal_det["id"], enr_v), CW))
    return hh, app, enr, redet, renewal_det


def setup_terminated_enrollment(state="CA", cw_id="cw-1", cw_headers=None, **state_overrides):
    """Full chain to a TERMINATED enrollment: open redetermination with an
    INELIGIBLE renewal determination, then finalize it TERMINATED (continuous
    coverage must be inactive). The terminating redetermination is left in
    TERMINATED. Returns (household, application, enrollment, redetermination).

    cw_id pins the claiming CaseWorker identity so a later segregation-of-duties
    check can compare against it."""
    cw = cw_headers or make_caseworker_headers(cw_id)
    setup_config(state=state, **state_overrides)
    hh = _d(_api.create_household(
        create_household_payload(state_code=state, primary_applicant_name="Term HH"), CW))
    member = add_member(hh["id"])
    add_member(hh["id"], full_name="Spouse", age=28, relationship="SPOUSE")
    add_income(member["id"], income_type="WAGES", monthly_amount_cents=120000)
    app = open_application(hh["id"])
    _api.submit_application(app["id"], APP)
    _api.claim_review(app["id"], cw)
    _api.run_determination(app["id"], CW)
    _api.verify_application(app["id"], CW)
    _api.decide_application(app["id"], {"target_status": "APPROVED"}, CW)
    enr = _d(_api.create_enrollment(create_enrollment_payload(hh["id"], app["id"]), CW))
    activated = _d(_api.activate_enrollment(enr["id"], cw))
    enr_v = activated["version"]
    # Raise income so the renewal determination is INELIGIBLE.
    add_income(member["id"], income_type="WAGES", monthly_amount_cents=900000)
    renewal_det = _d(_api.run_determination(app["id"], CW))
    redet = _d(_api.create_redetermination(
        create_redetermination_payload(enr["id"], renewal_det["id"], enr_v), CW))
    _api.finalize_redetermination(redet["id"], {"target_status": "TERMINATED"}, CW)
    enr_after = _d(_api.get_enrollment(enr["id"], CW))
    return hh, app, enr_after, redet


def setup_heard_appeal(state="CA", cw_id="cw-1", ho_id="ho-9"):
    """Full chain to an appeal in HEARD on a TERMINATED enrollment.

    The HearingOfficer (ho_id) differs from the claiming CaseWorker (cw_id) so the
    segregation-of-duties check passes. Returns
    (household, enrollment, redetermination, appeal)."""
    hh, app, enr, redet = setup_terminated_enrollment(state=state, cw_id=cw_id)
    enr_v2 = enr["version"]
    appeal = _d(_api.create_appeal(
        create_appeal_payload(enr["id"], redet["id"], enr_v2), APP))
    ho = make_hearing_officer_headers(ho_id)
    _api.schedule_appeal(appeal["id"], ho)
    _api.hear_appeal(appeal["id"], ho)
    appeal = _d(_api.get_appeal(appeal["id"], CW))
    return hh, enr, redet, appeal


def setup_filed_appeal(state="CA", cw_id="cw-1"):
    """Full chain to an appeal in FILED on a TERMINATED enrollment.

    Returns (household, enrollment, redetermination, appeal)."""
    hh, app, enr, redet = setup_terminated_enrollment(state=state, cw_id=cw_id)
    appeal = _d(_api.create_appeal(
        create_appeal_payload(enr["id"], redet["id"], enr["version"]), APP))
    return hh, enr, redet, appeal


def setup_renewed_redetermination(state="CA", cw_headers=None, **state_overrides):
    """Full chain to a redetermination finalized RENEWED (terminal) with the
    enrollment back to ACTIVE. The renewal determination is ELIGIBLE.
    Returns (household, application, enrollment, redetermination)."""
    cw = cw_headers or CW
    hh, app, enr, redet, _det = setup_in_redetermination(
        state=state, make_ineligible=False, cw_headers=cw, **state_overrides)
    _api.finalize_redetermination(redet["id"], {"target_status": "RENEWED"}, cw)
    redet_after = _d(_api.get_redetermination(redet["id"], CW))
    enr_after = _d(_api.get_enrollment(enr["id"], CW))
    return hh, app, enr_after, redet_after

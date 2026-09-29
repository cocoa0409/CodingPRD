"""Precondition builders.

The server is restarted with an empty store before every test, so every helper
here builds its preconditions from scratch through the public API. Nothing
touches storage directly, and nothing assumes a row another test created.

Ownership-gated calls always thread the acting originator's own row id through
the headers, because the originator role is entity-backed.
"""
import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.constants import CLOCK_STARTUP_INSTANT, TEST_DEFAULTS
from test_helpers.test_users import (
    admin_headers,
    analyst_headers,
    designer_headers,
    examiner_headers,
    loan_ops_headers,
    make_originator_headers,
    officer_headers,
)


def _data(response, what, expected_status=None):
    """Unwrap a setup call, failing loudly with the server's own error body."""
    assert response.status_code < 400, (
        f"Setup failed: {what} returned {response.status_code}: {response.text}"
    )
    return get_success_data(response, expected_status)


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------


def set_clock(api, instant):
    """Move the logical compliance clock and return the echoed instant."""
    data = _data(api.set_clock(factories.build_clock(instant), admin_headers()), "clock set")
    return data["current_utc"]


def reset_clock(api):
    """Return the clock to the instant it reads at startup."""
    return set_clock(api, CLOCK_STARTUP_INSTANT)


# ---------------------------------------------------------------------------
# Originators, licences and sponsorship
# ---------------------------------------------------------------------------


def create_originator(api, **overrides):
    """Register an originator and return the created row."""
    payload = factories.build_originator(**overrides)
    return _data(api.create_originator(payload, analyst_headers()), "originator registration", 201)


def get_originator(api, originator_id):
    """Re-read an originator, for example to observe a recomputed field."""
    return _data(api.get_originator(originator_id, analyst_headers()), "originator read")


def set_employment_status(api, originator_id, employment_status):
    """Move an originator's employment posture, recomputing its authority."""
    return _data(
        api.update_originator(
            originator_id, {"employment_status": employment_status}, analyst_headers()
        ),
        "originator employment update",
    )


def file_license(api, originator_id, **overrides):
    """File a state licence, which starts in PENDING and confers no authority."""
    payload = factories.build_license_registration(originator_id, **overrides)
    return _data(
        api.create_license_registration(payload, analyst_headers()), "licence filing", 201
    )


def get_license(api, license_id):
    """Re-read a licence, for example to observe its recomputed CE posture."""
    return _data(api.get_license_registration(license_id, analyst_headers()), "licence read")


def activate_license(api, license_id):
    """Activate a pending licence, stamping the instant its authority runs from."""
    return _data(
        api.activate_license_registration(license_id, analyst_headers()), "licence activation"
    )


def claim_sponsorship(api, license_id, expected_license_registration_version, **overrides):
    """Record a sponsorship claim under the stale-version guard."""
    payload = factories.build_sponsorship_transfer(
        expected_license_registration_version, **overrides
    )
    return _data(
        api.create_sponsorship_transfer(license_id, payload, analyst_headers()),
        "sponsorship claim",
        201,
    )


def relinquish_sponsorship(api, sponsorship_id):
    """Close a sponsorship interval directly."""
    return _data(
        api.relinquish_sponsorship_transfer(sponsorship_id, analyst_headers()),
        "sponsorship relinquishment",
    )


def license_status_action(api, license_id, action, **overrides):
    """Surrender, revoke or reinstate a licence."""
    payload = factories.build_license_status_action(action, **overrides)
    return _data(
        api.create_license_status_action(license_id, payload, analyst_headers()),
        f"licence {action.lower()}",
    )


def setup_authorized_originator(
    api,
    state_code=None,
    sponsorship_effective_at=CLOCK_STARTUP_INSTANT,
    originator_overrides=None,
    license_overrides=None,
):
    """An originator authorised to originate in one state.

    Registers the originator, files a licence for the state, activates it and
    claims sponsorship from `sponsorship_effective_at`, which is what actually
    puts the state into `authorized_state_codes`.
    """
    state_code = state_code or TEST_DEFAULTS["STATE_CODE"]
    originator = create_originator(api, **(originator_overrides or {}))
    license_kwargs = {"state_code": state_code}
    license_kwargs.update(license_overrides or {})
    licence = file_license(api, originator["id"], **license_kwargs)
    licence = activate_license(api, licence["id"])
    sponsorship = claim_sponsorship(
        api, licence["id"], licence["version"], effective_at=sponsorship_effective_at
    )
    return {
        "originator": get_originator(api, originator["id"]),
        "license": get_license(api, licence["id"]),
        "sponsorship": sponsorship,
        "state_code": state_code,
    }


def add_authorized_state(api, originator_id, state_code, sponsorship_effective_at=CLOCK_STARTUP_INSTANT, **license_overrides):
    """Give an already-registered originator authority in a further state."""
    licence = file_license(api, originator_id, state_code=state_code, **license_overrides)
    licence = activate_license(api, licence["id"])
    sponsorship = claim_sponsorship(
        api, licence["id"], licence["version"], effective_at=sponsorship_effective_at
    )
    return {"license": get_license(api, licence["id"]), "sponsorship": sponsorship}


# ---------------------------------------------------------------------------
# Continuing education
# ---------------------------------------------------------------------------


def create_ce_course(api, **overrides):
    """Add a course to the catalogue."""
    payload = factories.build_ce_course(**overrides)
    return _data(api.create_ce_course(payload, analyst_headers()), "CE course creation", 201)


def rescind_ce_course(api, course_id):
    """Rescind a course's provider approval, voiding the credits it sourced."""
    return _data(api.rescind_ce_course(course_id, analyst_headers()), "CE course rescission")


def file_ce_credit(api, originator_id, ce_course_id, **overrides):
    """File a continuing-education credit."""
    payload = factories.build_ce_credit(originator_id, ce_course_id, **overrides)
    return _data(api.create_ce_credit(payload, analyst_headers()), "CE credit filing", 201)


def void_ce_credit(api, credit_id):
    """Void a mis-filed credit, restoring the CE-hours conserved quantity."""
    return _data(api.void_ce_credit(credit_id, analyst_headers()), "CE credit void")


def setup_ce_baseline_seven_hours(
    api,
    originator_id,
    completion_date="2026-06-15T00:00:00Z",
    reporting_period_year=None,
):
    """The three category minimums exactly: 3 federal-law, 2 ethics, 2 non-traditional.

    Seven hours in total, which is one short of the default eight-hour
    requirement — the shortfall the eighth hour then closes.
    """
    reporting_period_year = reporting_period_year or TEST_DEFAULTS["CE_REPORTING_YEAR"]
    spec = (("FEDERAL_LAW", 3), ("ETHICS", 2), ("NONTRADITIONAL", 2))
    courses = {}
    credits = []
    for category, hours in spec:
        course = create_ce_course(api, credit_hours=hours, category=category)
        courses[category] = course
        credits.append(
            file_ce_credit(
                api,
                originator_id,
                course["id"],
                completion_date=completion_date,
                reporting_period_year=reporting_period_year,
            )
        )
    return {"courses": courses, "credits": credits}


def file_elective_credit(
    api,
    originator_id,
    credit_hours=1,
    completion_date="2026-06-20T00:00:00Z",
    reporting_period_year=None,
    is_makeup=False,
    course=None,
):
    """File an elective credit, the category that counts only toward the overall total."""
    reporting_period_year = reporting_period_year or TEST_DEFAULTS["CE_REPORTING_YEAR"]
    course = course or create_ce_course(api, credit_hours=credit_hours, category="ELECTIVE")
    credit = file_ce_credit(
        api,
        originator_id,
        course["id"],
        completion_date=completion_date,
        reporting_period_year=reporting_period_year,
        is_makeup=is_makeup,
    )
    return {"course": course, "credit": credit}


def read_ce_compliance(api, originator_id, **params):
    """Read the computed continuing-education aggregates."""
    return _data(
        api.get_originator_ce_compliance(originator_id, analyst_headers(), params=params or None),
        "CE compliance read",
    )


# ---------------------------------------------------------------------------
# Compensation plans
# ---------------------------------------------------------------------------


def draft_plan(api, **overrides):
    """Draft a compensation plan, which starts in DRAFT."""
    payload = factories.build_compensation_plan(**overrides)
    return _data(
        api.create_compensation_plan(payload, designer_headers()), "plan drafting", 201
    )


def declare_variable(api, plan_id, **overrides):
    """Declare one pay variable against a draft plan."""
    payload = factories.build_compensation_variable(**overrides)
    return _data(
        api.create_compensation_variable(plan_id, payload, designer_headers()),
        "pay variable declaration",
        201,
    )


def decide_plan(api, plan_id, decision, headers=None, **overrides):
    """Approve or reject a drafted plan, honouring segregation of duties."""
    payload = factories.build_plan_decision(decision, **overrides)
    return _data(
        api.create_plan_approval(plan_id, payload, headers or officer_headers()),
        f"plan {decision.lower()}",
    )


def setup_approved_plan(api, weight_pct=100, variable_type="LOAN_VOLUME_UNITS", **plan_overrides):
    """A plan in ACTIVE: drafted by a designer, approved by a different officer."""
    plan = draft_plan(api, **plan_overrides)
    declare_variable(api, plan["id"], variable_type=variable_type, weight_pct=weight_pct)
    return decide_plan(api, plan["id"], "APPROVE")


def assign_plan(api, originator_id, compensation_plan_id, expected_originator_version, **overrides):
    """Assign an active plan to an originator over a closed interval."""
    payload = factories.build_plan_assignment(
        compensation_plan_id, expected_originator_version, **overrides
    )
    return _data(
        api.assign_compensation_plan(originator_id, payload, officer_headers()),
        "plan assignment",
        200,
    )


def setup_originator_with_plan(
    api,
    state_code=None,
    plan_overrides=None,
    originator_overrides=None,
    license_overrides=None,
    assignment_overrides=None,
    sponsorship_effective_at=CLOCK_STARTUP_INSTANT,
):
    """An authorised originator carrying an ACTIVE assigned plan.

    This is the precondition for taking, locking and closing a loan: authority
    comes from the licence and sponsorship, and commission comes from the plan.
    """
    context = setup_authorized_originator(
        api,
        state_code=state_code,
        sponsorship_effective_at=sponsorship_effective_at,
        originator_overrides=originator_overrides,
        license_overrides=license_overrides,
    )
    plan = setup_approved_plan(api, **(plan_overrides or {}))
    originator = assign_plan(
        api,
        context["originator"]["id"],
        plan["id"],
        context["originator"]["version"],
        **(assignment_overrides or {}),
    )
    context["plan"] = _data(
        api.get_compensation_plan(plan["id"], officer_headers()), "plan read"
    )
    context["originator"] = originator
    context["headers"] = make_originator_headers(originator["id"])
    return context


# ---------------------------------------------------------------------------
# Loan applications
# ---------------------------------------------------------------------------


def take_loan(api, originator_id, **overrides):
    """Take a loan application as the owning originator."""
    payload = factories.build_loan_application(originator_id, **overrides)
    return _data(
        api.create_loan_application(payload, make_originator_headers(originator_id)),
        "loan intake",
        201,
    )


def lock_loan(api, loan_id, originator_id, **overrides):
    """Lock the rate, which re-verifies authority from scratch."""
    payload = factories.build_loan_lock(**overrides)
    return _data(
        api.lock_loan_application(loan_id, payload, make_originator_headers(originator_id)),
        "rate lock",
    )


def close_loan(api, loan_id, **overrides):
    """Close a locked loan, which is where commission first enters the ledger."""
    payload = factories.build_loan_close(**overrides)
    return _data(api.close_loan_application(loan_id, payload, loan_ops_headers()), "loan close")


def payoff_loan(api, loan_id, payoff_date, **overrides):
    """Post a payoff, running the recapture arithmetic."""
    payload = factories.build_loan_payoff(payoff_date, **overrides)
    return _data(api.payoff_loan_application(loan_id, payload, loan_ops_headers()), "loan payoff")


def withdraw_loan(api, loan_id, originator_id):
    """Withdraw a live application."""
    return _data(
        api.withdraw_loan_application(loan_id, make_originator_headers(originator_id)),
        "loan withdrawal",
    )


def release_compensation(api, loan_id):
    """Release compensation withheld at close."""
    return _data(api.release_loan_compensation(loan_id, officer_headers()), "compensation release")


def get_loan(api, loan_id):
    """Re-read a loan, for example to observe a cascade that reached it."""
    return _data(api.get_loan_application(loan_id, loan_ops_headers()), "loan read")


def setup_locked_loan(api, context=None, loan_overrides=None, lock_overrides=None, **plan_kwargs):
    """A loan sitting in LOCKED under an authorised originator with an active plan."""
    context = context or setup_originator_with_plan(api, **plan_kwargs)
    originator_id = context["originator"]["id"]
    loan_kwargs = {"state_code": context["state_code"]}
    loan_kwargs.update(loan_overrides or {})
    loan = take_loan(api, originator_id, **loan_kwargs)
    loan = lock_loan(api, loan["id"], originator_id, **(lock_overrides or {}))
    context["loan"] = loan
    return context


def setup_closed_loan(
    api, context=None, loan_overrides=None, lock_overrides=None, close_overrides=None, **plan_kwargs
):
    """A loan sitting in CLOSED with its provisional ledger line written."""
    context = setup_locked_loan(
        api,
        context=context,
        loan_overrides=loan_overrides,
        lock_overrides=lock_overrides,
        **plan_kwargs,
    )
    context["loan"] = close_loan(api, context["loan"]["id"], **(close_overrides or {}))
    return context


def setup_reconciled_loan(
    api, context=None, loan_overrides=None, lock_overrides=None, close_overrides=None, **plan_kwargs
):
    """A closed loan whose ledger line has been reconciled, so `paid_cents` is real."""
    context = setup_closed_loan(
        api,
        context=context,
        loan_overrides=loan_overrides,
        lock_overrides=lock_overrides,
        close_overrides=close_overrides,
        **plan_kwargs,
    )
    context["reconciliation"] = run_reconciliation(api, context["originator"]["id"])
    context["loan"] = get_loan(api, context["loan"]["id"])
    return context


def run_reconciliation(api, originator_id):
    """Run reconciliation for one originator and return the run report."""
    return _data(
        api.run_compensation_reconciliation(originator_id, officer_headers()),
        "compensation reconciliation",
    )


# ---------------------------------------------------------------------------
# Pricing exceptions
# ---------------------------------------------------------------------------


def request_pricing_exception(api, loan_id, originator_id, **overrides):
    """File a pricing exception against a locked file, as its owning originator."""
    payload = factories.build_pricing_exception(**overrides)
    return _data(
        api.create_pricing_exception(loan_id, payload, make_originator_headers(originator_id)),
        "pricing exception request",
        201,
    )


def decide_pricing_exception(api, exception_id, decision, headers=None, **overrides):
    """Approve or deny a pricing exception."""
    payload = factories.build_pricing_exception_decision(decision, **overrides)
    return _data(
        api.create_pricing_exception_decision(
            exception_id, payload, headers or officer_headers()
        ),
        f"pricing exception {decision.lower()}",
    )


def get_pricing_exception(api, exception_id):
    """Re-read a pricing exception."""
    return _data(api.get_pricing_exception(exception_id, officer_headers()), "exception read")


# ---------------------------------------------------------------------------
# Ledger reads
# ---------------------------------------------------------------------------


def list_records_for_loan(api, loan_id):
    """The ledger lines belonging to one loan, in `created_at` order."""
    response = api.list_compensation_records(officer_headers(), params={"loan_application_id": loan_id})
    return _data(response, "ledger listing")


def list_records_for_originator(api, originator_id, **filters):
    """The ledger lines belonging to one originator."""
    params = {"originator_id": originator_id}
    params.update(filters)
    return _data(api.list_compensation_records(officer_headers(), params=params), "ledger listing")


def sole_record_for_loan(api, loan_id):
    """The single ledger line a closed loan carries."""
    records = list_records_for_loan(api, loan_id)
    assert len(records) == 1, f"expected exactly one ledger line, found {len(records)}: {records}"
    return records[0]


# ---------------------------------------------------------------------------
# Advertising
# ---------------------------------------------------------------------------


def draft_advertisement(api, originator_id, **overrides):
    """Draft advertising copy as its owning originator."""
    payload = factories.build_advertisement(originator_id, **overrides)
    return _data(
        api.create_advertisement(payload, make_originator_headers(originator_id)),
        "advertisement drafting",
        201,
    )


def submit_advertisement(api, advertisement_id, originator_id):
    """Submit copy for review, running the disclosure inspection."""
    return _data(
        api.submit_advertisement(advertisement_id, make_originator_headers(originator_id)),
        "advertisement submission",
    )


def review_advertisement(api, advertisement_id, decision, **overrides):
    """Approve or reject submitted copy."""
    payload = factories.build_advertisement_review(decision, **overrides)
    return _data(
        api.create_advertisement_review(advertisement_id, payload, officer_headers()),
        f"advertisement {decision.lower()}",
    )


def revise_advertisement(api, advertisement_id, originator_id, content_text, **overrides):
    """Revise rejected copy back to draft."""
    payload = factories.build_advertisement_revision(content_text, **overrides)
    return _data(
        api.revise_advertisement(advertisement_id, payload, make_originator_headers(originator_id)),
        "advertisement revision",
    )


def publish_advertisement(api, advertisement_id, originator_id):
    """Publish approved copy under the live authority check."""
    return _data(
        api.publish_advertisement(advertisement_id, make_originator_headers(originator_id)),
        "advertisement publication",
    )


# ---------------------------------------------------------------------------
# Examinations and investigations
# ---------------------------------------------------------------------------


def log_inquiry(api, **overrides):
    """Log a regulatory examination inquiry."""
    payload = factories.build_examination_inquiry(**overrides)
    return _data(api.create_examination_inquiry(payload, examiner_headers()), "inquiry log", 201)


def file_response(api, inquiry_id, **overrides):
    """File a response against an inquiry, advancing its round count."""
    payload = factories.build_examination_response(**overrides)
    return _data(
        api.create_examination_response(inquiry_id, payload, examiner_headers()),
        "examination response",
    )


def request_more_info(api, inquiry_id, **overrides):
    """Record a regulator's further-information request."""
    payload = factories.build_examination_info_request(**overrides)
    return _data(
        api.create_examination_info_request(inquiry_id, payload, examiner_headers()),
        "further-information request",
    )


def open_investigation(api, loan_application_id, **overrides):
    """Open an investigation by hand."""
    payload = factories.build_investigation(loan_application_id, **overrides)
    return _data(
        api.create_investigation(payload, officer_headers()), "investigation opening", 201
    )


def enter_finding(api, investigation_id, finding, restitution_cents, **overrides):
    """Enter a finding, rewriting the loan's authority record."""
    payload = factories.build_investigation_finding(finding, restitution_cents, **overrides)
    return _data(
        api.create_investigation_finding(investigation_id, payload, officer_headers()),
        "investigation finding",
    )


def remediate(api, investigation_id, **overrides):
    """Record remediation of a substantiated case."""
    payload = factories.build_investigation_remediation(**overrides)
    return _data(
        api.remediate_investigation(investigation_id, payload, officer_headers()),
        "investigation remediation",
    )


def list_investigations(api, **filters):
    """List investigations, the only route to cascade-created ones."""
    return _data(
        api.list_investigations(officer_headers(), params=filters or None),
        "investigation listing",
    )


# ---------------------------------------------------------------------------
# Sweep and audit trail
# ---------------------------------------------------------------------------


def run_sweep(api):
    """Trigger the nightly compliance sweep and return its report."""
    return _data(api.run_daily_license_sweep(admin_headers()), "nightly sweep")


def list_audit_events(api, **filters):
    """List audit entries, ordered by their own sequence number."""
    return _data(api.list_audit_events(admin_headers(), params=filters or None), "audit listing")


def audit_events_for(api, subject_type, subject_ref, **filters):
    """The audit entries naming one subject row."""
    params = {"subject_type": subject_type, "subject_ref": subject_ref}
    params.update(filters)
    return list_audit_events(api, **params)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api():
    """A fresh client against the server the runner started for this test."""
    return ApiClient()


@pytest.fixture
def authorized_originator(api):
    """An originator authorised in the default state."""
    return setup_authorized_originator(api)


@pytest.fixture
def originator_with_plan(api):
    """An authorised originator carrying an ACTIVE assigned compensation plan."""
    return setup_originator_with_plan(api)


@pytest.fixture
def locked_loan(api):
    """A loan sitting in LOCKED, ready to close or to carry a pricing exception."""
    return setup_locked_loan(api)

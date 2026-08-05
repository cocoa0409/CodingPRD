"""Claim submission gates: credentialing, enrollment, segregation of duties,
timely filing, and the fixed precedence among them.

Translates the cross_entity_state_dependency, priority_pair_validation_conflict,
and boundary_precision_check (timely filing) difficulty instances plus the
segregation-of-duties corner instance.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_account_manager_headers, make_biller_headers, make_coder_headers,
)
from test_helpers import fixtures as fx

AM = make_account_manager_headers()


# ---- Difficulty: cross_entity_state_dependency / provider credentialed ----
def test_submit_blocked_when_provider_not_credentialed(api):
    """PRD §3.4: "First it checks the rendering provider's credentialing: the provider
    must be `APPROVED` and not past expiration. If the provider is currently `APPROVED`
    but the logical clock has reached or passed the provider's
    `credentialing_expiration_date`, the provider is auto-expired ... and, together with
    any provider that is simply not `APPROVED`, the submission is rejected with
    `ERR_PROVIDER_NOT_CREDENTIALED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_depends_on_provider_credentialed_returns_not_credentialed
    """
    ctx = fx.setup_scrubbed_claim(api, credential="submitted", enrollment="none",
                                  service_date="2026-05-15T00:00:00Z", coder_user_id="coder-7")
    resp = api.submit_claim(ctx["claim"]["id"], make_biller_headers("biller-7"))
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_CREDENTIALED.value)


def test_submit_not_credentialed_leaves_claim_scrubbed(api):
    """PRD §3.4: "together with any provider that is simply not `APPROVED`, the
    submission is rejected with `ERR_PROVIDER_NOT_CREDENTIALED` (HTTP 422)."
    PRD §3.4: "Submission is a `Biller`'s responsibility and moves a claim from
    `SCRUBBED` to `SUBMITTED`."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_depends_on_provider_credentialed_returns_not_credentialed
    """
    ctx = fx.setup_scrubbed_claim(api, credential="submitted", enrollment="none",
                                  service_date="2026-05-15T00:00:00Z", coder_user_id="coder-7")
    api.submit_claim(ctx["claim"]["id"], make_biller_headers("biller-7"))
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    assert claim["status"] == "SCRUBBED"


# ---- Difficulty: cross_entity_state_dependency / active enrollment ----
def test_submit_blocked_when_enrollment_not_active(api):
    """PRD §3.4: "Then referential eligibility is checked: an `ACTIVE` `PayerEnrollment`
    must exist for the claim's provider-and-payer pair whose participation period covers
    the claim's `service_date`, or the submission is rejected with
    `ERR_ENROLLMENT_NOT_ACTIVE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_depends_on_active_enrollment_returns_enrollment_not_active
    """
    ctx = fx.setup_scrubbed_claim(api, credential="approved", enrollment="pending",
                                  service_date="2026-05-15T00:00:00Z", coder_user_id="coder-7")
    resp = api.submit_claim(ctx["claim"]["id"], make_biller_headers("biller-7"))
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


def test_submit_enrollment_pending_leaves_claim_scrubbed(api):
    """PRD §3.4: "an `ACTIVE` `PayerEnrollment` must exist for the claim's
    provider-and-payer pair whose participation period covers the claim's
    `service_date`, or the submission is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`
    (HTTP 422)."
    PRD §3.4: "Submission is a `Biller`'s responsibility and moves a claim from
    `SCRUBBED` to `SUBMITTED`."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_depends_on_active_enrollment_returns_enrollment_not_active
    """
    ctx = fx.setup_scrubbed_claim(api, credential="approved", enrollment="pending",
                                  service_date="2026-05-15T00:00:00Z", coder_user_id="coder-7")
    api.submit_claim(ctx["claim"]["id"], make_biller_headers("biller-7"))
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    assert claim["status"] == "SCRUBBED"


# ---- Difficulty: priority_pair / credentialing beats timely filing ----
def test_credentialing_gate_precedes_timely_filing(api):
    """PRD §3.4: "the submit workflow runs a series of gates in a fixed order. First it
    checks the rendering provider's credentialing ... Finally the timely-filing deadline
    is enforced: the number of whole days from the claim's `service_date` to the current
    logical clock must not exceed the payer's `timely_filing_days`, or the submission is
    rejected with `ERR_TIMELY_FILING_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/submit_credentialing_beats_timely_filing_returns_not_credentialed
    """
    ctx = fx.setup_scrubbed_claim(api, credential="submitted", enrollment="none",
                                  timely_filing_days=90, service_date="2026-01-01T00:00:00Z",
                                  coder_user_id="coder-5")
    resp = api.submit_claim(ctx["claim"]["id"], make_biller_headers("biller-5"))
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_CREDENTIALED.value)


def test_credentialing_precedence_leaves_claim_scrubbed(api):
    """PRD §3.4: "First it checks the rendering provider's credentialing: the provider
    must be `APPROVED` and not past expiration."
    PRD §3.4: "Submission is a `Biller`'s responsibility and moves a claim from
    `SCRUBBED` to `SUBMITTED`."

    Design: Difficulty/priority_pair_validation_conflict/submit_credentialing_beats_timely_filing_returns_not_credentialed
    """
    ctx = fx.setup_scrubbed_claim(api, credential="submitted", enrollment="none",
                                  timely_filing_days=90, service_date="2026-01-01T00:00:00Z",
                                  coder_user_id="coder-5")
    api.submit_claim(ctx["claim"]["id"], make_biller_headers("biller-5"))
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    assert claim["status"] == "SCRUBBED"


# ---- Difficulty: priority_pair / enrollment beats timely filing ----
def test_enrollment_gate_precedes_timely_filing(api):
    """PRD §3.4: "Then referential eligibility is checked: an `ACTIVE` `PayerEnrollment`
    must exist ... Finally the timely-filing deadline is enforced: the number of whole
    days from the claim's `service_date` to the current logical clock must not exceed
    the payer's `timely_filing_days`, or the submission is rejected with
    `ERR_TIMELY_FILING_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/submit_enrollment_beats_timely_filing_returns_enrollment_not_active
    """
    ctx = fx.setup_scrubbed_claim(api, credential="approved", enrollment="pending",
                                  timely_filing_days=90, service_date="2026-01-01T00:00:00Z",
                                  coder_user_id="coder-5")
    resp = api.submit_claim(ctx["claim"]["id"], make_biller_headers("biller-5"))
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


def test_enrollment_precedence_leaves_claim_scrubbed(api):
    """PRD §3.4: "Then referential eligibility is checked: an `ACTIVE` `PayerEnrollment`
    must exist for the claim's provider-and-payer pair whose participation period covers
    the claim's `service_date`, or the submission is rejected with
    `ERR_ENROLLMENT_NOT_ACTIVE` (HTTP 422)."
    PRD §3.4: "Submission is a `Biller`'s responsibility and moves a claim from
    `SCRUBBED` to `SUBMITTED`."

    Design: Difficulty/priority_pair_validation_conflict/submit_enrollment_beats_timely_filing_returns_enrollment_not_active
    """
    ctx = fx.setup_scrubbed_claim(api, credential="approved", enrollment="pending",
                                  timely_filing_days=90, service_date="2026-01-01T00:00:00Z",
                                  coder_user_id="coder-5")
    api.submit_claim(ctx["claim"]["id"], make_biller_headers("biller-5"))
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    assert claim["status"] == "SCRUBBED"


# ---- Difficulty: boundary_precision_check / timely filing at exactly 90 days ----
def test_timely_filing_at_exact_boundary_submits(api):
    """PRD §3.4: "Finally the timely-filing deadline is enforced: the number of whole
    days from the claim's `service_date` to the current logical clock must not exceed
    the payer's `timely_filing_days`, or the submission is rejected with
    `ERR_TIMELY_FILING_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/timely_filing_exact_boundary_submits_at_90_days
    """
    ctx = fx.setup_scrubbed_claim(api, credential="approved", enrollment="active",
                                  timely_filing_days=90, service_date="2026-03-03T00:00:00Z",
                                  coder_user_id="coder-6")
    claim = fx.submit_claim(api, ctx["claim"]["id"], "biller-6")
    assert claim["status"] == "SUBMITTED", claim["status"]


def test_timely_filing_boundary_stamps_submission_date(api):
    """PRD §3.4: "On success the platform stamps `submission_date` with the current
    clock, records the submitting operator's `X-User-ID` as `submitted_by_user_id`,
    sets the claim to `SUBMITTED`, and increments the claim's `version` by one."
    PRD §2.4: "The `created_at` field is an ISO 8601 UTC timestamp with three
    fractional digits recording when the resource was first created."

    Design: Difficulty/boundary_precision_check/timely_filing_exact_boundary_submits_at_90_days
    """
    ctx = fx.setup_scrubbed_claim(api, credential="approved", enrollment="active",
                                  timely_filing_days=90, service_date="2026-03-03T00:00:00Z",
                                  coder_user_id="coder-6")
    claim = fx.submit_claim(api, ctx["claim"]["id"], "biller-6")
    assert claim["submission_date"] == "2026-06-01T00:00:00.000Z", claim["submission_date"]


# ---- Corner: validations / segregation of duties ----
def test_submit_same_user_as_scrubber_returns_segregation_of_duties(api):
    """PRD §2.7: "At submit time, if the submitting operator's `X-User-ID` equals the
    stored `scrubbed_by_user_id`, the submission is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/submit_same_user_as_scrubber_returns_segregation_of_duties
    """
    ctx = fx.setup_scrubbed_claim(api, credential="approved", enrollment="active",
                                  service_date="2026-05-15T00:00:00Z", coder_user_id="u-shared")
    resp = api.submit_claim(ctx["claim"]["id"], make_biller_headers("u-shared"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    assert claim["status"] == "SCRUBBED"

"""Business rules isolated to one failing condition each.

Each scenario below arranges the data so that exactly one rule can fire, then
asserts the exact error identifier the PRD names for it - and, where the rule has
a satisfiable side, repairs the single offending input and asserts the same call
then succeeds. The rules exercised are the plan-approval gates (PRD 3.3), the
conditional justification floor for `PRICING_ERROR` (PRD 3.6), the inclusive
examination-response deadline (PRD 3.9), the live authority check at publication
(PRD 3.8), originator uniqueness (PRD 3.1), the pagination bounds (PRD 2.3) and
the open-pipeline block on surrender (PRD 3.1).
"""
from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    build_examination_response,
    build_license_status_action,
    build_originator,
    build_plan_decision,
    build_pricing_exception,
)
from test_helpers.fixtures import (
    create_originator,
    declare_variable,
    decide_plan,
    draft_advertisement,
    draft_plan,
    file_response,
    get_license,
    get_originator,
    license_status_action,
    lock_loan,
    log_inquiry,
    publish_advertisement,
    request_pricing_exception,
    review_advertisement,
    set_clock,
    set_employment_status,
    setup_authorized_originator,
    submit_advertisement,
    take_loan,
    withdraw_loan,
)
from test_helpers.test_users import (
    OFFICER_USER_ID,
    analyst_headers,
    examiner_headers,
    make_originator_headers,
    officer_headers,
)

# A justification that clears the forty-character schema floor of PRD 3.6 but
# not the one-hundred-and-twenty-character floor PRICING_ERROR adds: 58 chars.
JUSTIFICATION_58 = "Rate sheet was misread at lock; corrected pricing applied."
# The same explanation written out to 165 characters, which clears both floors.
JUSTIFICATION_165 = (
    "Rate sheet was misread at lock on 2026-08-02; the corrected par price is "
    "documented in the lock desk log and the concession restores the borrower to "
    "the quoted rate."
)
PERMISSIBLE_JUSTIFICATION = (
    "Closed unit volume is a permissible compensation variable and is not a term "
    "of the transaction."
)
NMLS_ID = "2200001"
LICENSE_NUMBER = "CA-DFPI-70001"


def _instant(value):
    """Parse an ISO 8601 UTC timestamp, so two encodings of one moment compare equal."""
    assert value is not None, "expected a timestamp, found null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _flat_plan(api):
    """A DRAFT plan at 105 bps with no tier and no absorption."""
    return draft_plan(
        api,
        base_basis_points=105,
        min_fee_cents=0,
        max_fee_cents=5_000_000,
        volume_tier_enabled=False,
        concession_absorption_enabled=False,
    )


def test_plan_approval_with_an_interest_rate_variable_is_refused(api):
    """A rate-keyed variable is recorded, then blocks approval on its own.

    PRD 3.3 accepts the declaration but classifies it: eight variable types
    "are `PROHIBITED` because they are terms of the transaction:
    `INTEREST_RATE`, `APR`, `LOAN_TERM_MONTHS`, `LTV_RATIO`, `CREDIT_SCORE`,
    `PRODUCT_TYPE`, `PREPAYMENT_PENALTY_FLAG` and `LOAN_PROFITABILITY`", and "A
    prohibited variable is nonetheless **accepted** into the draft rather than
    refused - the compliance office wants the attempt on the record - but
    declaring one raises the plan's recomputed `prohibited_variable_count`".

    Approval then fails on that count alone, per PRD 3.3: it requires "that
    `prohibited_variable_count` is exactly zero, so that any plan carrying even
    one term-of-the-transaction variable is unapprovable and is rejected with
    `ERR_PROHIBITED_COMP_VARIABLE` (HTTP 422)". The two weights total exactly one
    hundred, so the weight-sum rule cannot also fire, and the approving officer
    is not the drafting designer, so segregation of duties cannot fire either.

    Design: Corner/validations/plan_approval_with_interest_rate_variable_returns_prohibited_comp_variable
    """
    plan = _flat_plan(api)
    permissible = declare_variable(
        api,
        plan["id"],
        variable_type="LOAN_VOLUME_UNITS",
        weight_pct=60,
        justification_text=PERMISSIBLE_JUSTIFICATION,
    )
    prohibited = declare_variable(
        api,
        plan["id"],
        variable_type="INTEREST_RATE",
        weight_pct=40,
        justification_text=(
            "Designer argues the note rate reflects effort, which Regulation Z "
            "does not permit."
        ),
    )
    assert permissible["permissibility"] == "PERMISSIBLE"
    assert prohibited["permissibility"] == "PROHIBITED"

    drafted = validate_success(api.get_compensation_plan(plan["id"], officer_headers()))
    assert drafted["prohibited_variable_count"] == 1

    response = api.create_plan_approval(
        plan["id"], build_plan_decision("APPROVE"), officer_headers()
    )
    validate_error(response, ApiErrorId.ERR_PROHIBITED_COMP_VARIABLE.value)

    unchanged = validate_success(api.get_compensation_plan(plan["id"], officer_headers()))
    assert unchanged["status"] == "DRAFT"
    assert unchanged["approved_by_user_id"] is None


def test_plan_approval_needs_weights_totalling_exactly_one_hundred(api):
    """Two individually valid weights that total ninety block approval until topped up.

    Both variables are permissible and each `weight_pct` is inside its own
    permitted range, so only the collective total is wrong. PRD 3.3 requires
    "that the plan has at least one declared variable whose `weight_pct` values
    sum to exactly one hundred, with any other total - including a plan with no
    variables at all - rejected as `ERR_PLAN_WEIGHTS_NOT_100` (HTTP 422)".

    Declaring a third permissible variable at ten lifts the total to exactly one
    hundred, and the identical approval then succeeds: PRD 3.3 says "**Approval**
    advances the plan `DRAFT → ACTIVE`" and "On success `approved_by_user_id` is
    stamped with the approver's `X-User-ID`".

    Design: Corner/validations/plan_approval_with_weights_summing_to_ninety_rejected
    """
    plan = _flat_plan(api)
    declare_variable(
        api,
        plan["id"],
        variable_type="LOAN_VOLUME_UNITS",
        weight_pct=60,
        justification_text=PERMISSIBLE_JUSTIFICATION,
    )
    declare_variable(
        api,
        plan["id"],
        variable_type="HOURS_WORKED",
        weight_pct=30,
        justification_text=(
            "Hours actually worked on the file is a permissible compensation "
            "variable under Regulation Z."
        ),
    )

    refused = api.create_plan_approval(
        plan["id"], build_plan_decision("APPROVE"), officer_headers()
    )
    validate_error(refused, ApiErrorId.ERR_PLAN_WEIGHTS_NOT_100.value)

    third = declare_variable(
        api,
        plan["id"],
        variable_type="FILE_QUALITY_SCORE",
        weight_pct=10,
        justification_text=(
            "File quality is a permissible compensation variable and is not a "
            "term of the transaction."
        ),
    )
    assert third["permissibility"] == "PERMISSIBLE"

    approved = decide_plan(api, plan["id"], "APPROVE")
    assert approved["status"] == "ACTIVE"
    assert approved["approved_by_user_id"] == OFFICER_USER_ID
    assert approved["prohibited_variable_count"] == 0


def _locked_file_without_a_plan(api):
    """An authorised originator with one CA loan locked at 20,000,000 cents.

    The two-percent concession ceiling on this file is 400,000 cents, so a
    100,000-cent concession can never trip the cap rule (PRD 3.6).
    """
    context = setup_authorized_originator(
        api,
        originator_overrides={"nmls_unique_id": NMLS_ID, "legal_name": "Avery Lane"},
        license_overrides={"license_number": LICENSE_NUMBER},
    )
    originator_id = context["originator"]["id"]
    loan = take_loan(api, originator_id, requested_amount_cents=20_000_000, par_rate_bps=650)
    lock_loan(api, loan["id"], originator_id, note_rate_bps=650, locked_amount_cents=20_000_000)
    return originator_id, loan["id"]


def test_pricing_error_rejects_a_justification_below_the_heightened_floor(api):
    """Fifty-eight characters clears the schema floor but not the PRICING_ERROR floor.

    PRD 3.6 makes the longer floor conditional on the reason code: "A
    `PRICING_ERROR` exception - the office's own mistake - demands a heavier
    written record: its `justification_text` must run to at least one hundred and
    twenty characters, and a shorter-but-schema-valid justification is rejected
    with `ERR_JUSTIFICATION_INSUFFICIENT` (HTTP 422)." The text used here is
    fifty-eight characters, so it satisfies the generic floor PRD 3.6 describes
    as "The generic forty-character floor that applies to every reason code is
    enforced earlier, as a request-shape violation reported as
    `ERR_INVALID_REQUEST`" and isolates the conditional rule. The rejected call
    creates nothing, so the loan still carries no exception at all.

    Design: Corner/validations/pricing_error_reason_requires_longer_justification_than_other_reasons
    """
    assert len(JUSTIFICATION_58) == 58

    originator_id, loan_id = _locked_file_without_a_plan(api)

    response = api.create_pricing_exception(
        loan_id,
        build_pricing_exception(
            requested_rate_bps=620,
            concession_cents=100_000,
            reason_code="PRICING_ERROR",
            justification_text=JUSTIFICATION_58,
        ),
        make_originator_headers(originator_id),
    )
    validate_error(response, ApiErrorId.ERR_JUSTIFICATION_INSUFFICIENT.value)

    _, meta = validate_paginated(
        api.list_pricing_exceptions(officer_headers(), params={"loan_application_id": loan_id})
    )
    assert meta["total_count"] == 0


def test_other_reason_codes_accept_the_shorter_justification(api):
    """The identical text is filed under COMPETITIVE_MATCH, and a longer one under PRICING_ERROR.

    PRD 3.6 attaches the heavier record only to one reason code - "A
    `PRICING_ERROR` exception - the office's own mistake - demands a heavier
    written record: its `justification_text` must run to at least one hundred and
    twenty characters" - so the fifty-eight-character text that PRICING_ERROR
    refuses is perfectly filable under `COMPETITIVE_MATCH`, which faces only the
    generic floor of "the `justification_text` retained for examination, of
    between forty and two thousand characters". A one-hundred-and-sixty-five
    character text then satisfies PRICING_ERROR itself. Both filings start where
    PRD 3.6 says they must: "A filed exception starts in `SUBMITTED` with
    `comp_impact_cents` at `0`, `requested_by_user_id` stamped from the filing
    originator's `X-User-ID`".

    Design: Corner/validations/pricing_error_reason_requires_longer_justification_than_other_reasons
    """
    assert len(JUSTIFICATION_58) == 58
    assert len(JUSTIFICATION_165) == 165

    originator_id, loan_id = _locked_file_without_a_plan(api)

    competitive = request_pricing_exception(
        api,
        loan_id,
        originator_id,
        requested_rate_bps=620,
        concession_cents=100_000,
        reason_code="COMPETITIVE_MATCH",
        justification_text=JUSTIFICATION_58,
    )
    assert competitive["status"] == "SUBMITTED"
    assert competitive["reason_code"] == "COMPETITIVE_MATCH"
    assert competitive["requested_by_user_id"] == originator_id
    assert competitive["comp_impact_cents"] == 0

    pricing_error = request_pricing_exception(
        api,
        loan_id,
        originator_id,
        requested_rate_bps=620,
        concession_cents=100_000,
        reason_code="PRICING_ERROR",
        justification_text=JUSTIFICATION_165,
    )
    assert pricing_error["status"] == "SUBMITTED"
    assert pricing_error["reason_code"] == "PRICING_ERROR"

    _, meta = validate_paginated(
        api.list_pricing_exceptions(officer_headers(), params={"loan_application_id": loan_id})
    )
    assert meta["total_count"] == 2


def test_examination_response_filed_on_the_deadline_instant_is_accepted(api):
    """At exactly `response_due_at` the response is still on time.

    PRD 3.9 makes the comparison inclusive: "an inquiry whose `status` is `OPEN`
    or `INFO_REQUESTED` advances to `RESPONSE_SUBMITTED`, provided the logical
    clock instant is at or before `response_due_at`." And it fixes the two
    counters: "Every entry into `RESPONSE_SUBMITTED` increments
    `response_round_count` by one - including the cyclic re-entries described
    next - and stamps `last_response_at` from the logical clock."

    Design: Corner/validations/examination_response_at_deadline_passes_and_after_deadline_rejected
    """
    inquiry = log_inquiry(api, state_code="CA", response_due_at="2026-08-10T00:00:00Z")
    assert inquiry["status"] == "OPEN"
    assert inquiry["response_round_count"] == 0

    set_clock(api, "2026-08-10T00:00:00Z")
    responded = file_response(
        api,
        inquiry["id"],
        narrative=(
            "Response filed on the deadline instant with the full licence and "
            "compensation record."
        ),
    )
    assert responded["status"] == "RESPONSE_SUBMITTED"
    assert responded["response_round_count"] == 1
    assert _instant(responded["last_response_at"]) == _instant("2026-08-10T00:00:00Z")


def test_examination_response_filed_after_the_deadline_is_refused(api):
    """One day past `response_due_at` the same filing is refused and changes nothing.

    PRD 3.9: "Filing after the deadline is rejected with
    `ERR_RESPONSE_DEADLINE_PASSED` (HTTP 422)." The inquiry therefore stays in
    the state PRD 3.9 gives a fresh one - "A new inquiry starts in `OPEN` with
    `opened_at` stamped from the logical clock, `response_round_count` at `0`,
    `last_response_at` null and `escalation_reason` null" - because the rejected
    call increments no counter and stamps no instant.

    Design: Corner/validations/examination_response_at_deadline_passes_and_after_deadline_rejected
    """
    inquiry = log_inquiry(api, state_code="CA", response_due_at="2026-08-10T00:00:00Z")

    set_clock(api, "2026-08-11T00:00:00Z")
    response = api.create_examination_response(
        inquiry["id"],
        build_examination_response(
            narrative="Late response filed one day after the deadline instant."
        ),
        examiner_headers(),
    )
    validate_error(response, ApiErrorId.ERR_RESPONSE_DEADLINE_PASSED.value)

    unchanged = validate_success(
        api.get_examination_inquiry(inquiry["id"], examiner_headers())
    )
    assert unchanged["status"] == "OPEN"
    assert unchanged["response_round_count"] == 0
    assert unchanged["last_response_at"] is None


def _approved_web_advertisement(api, originator_id, content_text):
    """A WEB advertisement carried through submission to APPROVED with no findings."""
    advertisement = draft_advertisement(
        api,
        originator_id,
        medium="WEB",
        content_text=content_text,
        target_state_codes=["CA"],
        disclosed_nmls_ids=[NMLS_ID],
        disclosed_license_numbers=[LICENSE_NUMBER],
    )
    submitted = submit_advertisement(api, advertisement["id"], originator_id)
    assert submitted["disclosure_findings"] == []
    reviewed = review_advertisement(api, advertisement["id"], "APPROVE")
    assert reviewed["status"] == "APPROVED"
    return reviewed


def test_publication_is_blocked_once_employment_is_suspended(api):
    """Suspending employment strips the authority publication needs, on another entity.

    Publication reads the originator's live authority, not the advertisement's own
    fields. PRD 3.8: "**every** state code in `target_state_codes` must be present
    in the originator's `authorized_state_codes` at the logical clock instant, and
    a target state the originator is no longer authorised in is rejected with
    `ERR_STATE_NOT_AUTHORIZED` (HTTP 422)." Employment is one of the inputs to
    that list, per PRD 3.1: "because employment is an input to the authority
    computation, `authorized_state_codes` is recomputed immediately: moving an
    originator to `SUSPENDED` or `TERMINATED` strips every state authority it
    held, even though its licences remain untouched and still read `ACTIVE`."

    The first advertisement publishes while the originator is EMPLOYED and, per
    PRD 3.8, "On success `published_at` is stamped from the logical clock". The
    second, identically approved, is refused and keeps `published_at` null.

    Design: Corner/validations/advertisement_publish_blocked_when_employment_status_is_suspended
    """
    context = setup_authorized_originator(
        api,
        originator_overrides={"nmls_unique_id": NMLS_ID, "legal_name": "Avery Lane"},
        license_overrides={"license_number": LICENSE_NUMBER},
    )
    originator_id = context["originator"]["id"]
    license_id = context["license"]["id"]
    assert context["originator"]["authorized_state_codes"] == ["CA"]

    first = _approved_web_advertisement(
        api,
        originator_id,
        "Refinance with Avery Lane, NMLS 2200001, California licence "
        "CA-DFPI-70001. APR varies by term and credit profile.",
    )
    second = _approved_web_advertisement(
        api,
        originator_id,
        "Second campaign from Avery Lane, NMLS 2200001, California licence "
        "CA-DFPI-70001. APR varies by term.",
    )

    published = publish_advertisement(api, first["id"], originator_id)
    assert published["status"] == "PUBLISHED"
    assert _instant(published["published_at"]) == _instant("2026-08-01T00:00:00Z")

    suspended = set_employment_status(api, originator_id, "SUSPENDED")
    assert suspended["employment_status"] == "SUSPENDED"
    assert suspended["authorized_state_codes"] == []
    assert get_license(api, license_id)["status"] == "ACTIVE"

    response = api.publish_advertisement(second["id"], make_originator_headers(originator_id))
    validate_error(response, ApiErrorId.ERR_STATE_NOT_AUTHORIZED.value)

    unchanged = validate_success(api.get_advertisement(second["id"], officer_headers()))
    assert unchanged["status"] == "APPROVED"
    assert unchanged["published_at"] is None


def test_duplicate_nmls_unique_id_is_refused_while_a_fresh_one_is_accepted(api):
    """The NMLS identifier is globally unique regardless of name or hire date.

    PRD 3.1 describes it as "the NMLS unique identifier that must be printed on
    every advertisement and disclosure, given as a string of between six and eight
    decimal digits and unique across all originators in the system", and then
    fixes the failure: "A duplicate `nmls_unique_id` is rejected with
    `ERR_DUPLICATE_KEY`." PRD 2.9 rule 9 repeats the scope: "an originator's
    `nmls_unique_id` is globally unique". The refused registration creates no row,
    so the collection still holds one; a different identifier is accepted and
    lifts it to two.

    Design: Corner/validations/duplicate_nmls_unique_id_rejected
    """
    first = create_originator(
        api, nmls_unique_id=NMLS_ID, legal_name="Avery Lane", hire_date="2024-01-15T00:00:00Z"
    )

    response = api.create_originator(
        build_originator(
            nmls_unique_id=NMLS_ID,
            legal_name="Avery R. Lane",
            hire_date="2025-03-01T00:00:00Z",
        ),
        analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value)

    _, meta = validate_paginated(
        api.list_originators(analyst_headers(), params={"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1

    second = create_originator(
        api,
        nmls_unique_id="2200002",
        legal_name="Avery R. Lane",
        hire_date="2025-03-01T00:00:00Z",
    )
    assert second["nmls_unique_id"] == "2200002"
    assert second["id"] != first["id"]

    _, meta = validate_paginated(
        api.list_originators(analyst_headers(), params={"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 2


def test_pagination_bounds_reject_limit_zero_and_a_negative_offset(api):
    """The lower bound of `limit` is one, not zero, and `offset` may not be negative.

    PRD 2.3: "`limit` defaults to `10`, must be an integer, and must fall between
    a minimum of `1` and a maximum of `100` inclusive. `offset` defaults to `0`,
    must be an integer, and must be zero or greater; there is no upper bound on
    `offset`. A `limit` outside the permitted range, or a negative `offset`, or a
    non-integer value for either, is rejected with `ERR_INVALID_PAGINATION`
    (HTTP 400)."

    A `limit` of one then succeeds against the same two rows, which proves the
    rejection is the pagination rule rather than an empty collection.

    Design: Corner/validations/list_with_limit_zero_returns_invalid_pagination
    """
    create_originator(
        api, nmls_unique_id=NMLS_ID, legal_name="Avery Lane", hire_date="2024-01-15T00:00:00Z"
    )
    create_originator(
        api,
        nmls_unique_id="2200002",
        legal_name="Blake Rivers",
        hire_date="2024-02-20T00:00:00Z",
    )

    zero_limit = api.list_originators(analyst_headers(), params={"limit": 0, "offset": 0})
    validate_error(zero_limit, ApiErrorId.ERR_INVALID_PAGINATION.value)

    negative_offset = api.list_originators(analyst_headers(), params={"limit": 10, "offset": -1})
    validate_error(negative_offset, ApiErrorId.ERR_INVALID_PAGINATION.value)

    data, meta = validate_paginated(
        api.list_originators(analyst_headers(), params={"limit": 1, "offset": 0})
    )
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_surrender_is_blocked_by_a_locked_file_then_allowed_once_it_is_withdrawn(api):
    """The open-pipeline block counts live files in the surrendering state only.

    PRD 3.1: "**Surrender** advances the licence to `SURRENDERED` and is permitted
    when the licence's `status` is `ACTIVE` or `RENEWAL_PENDING`; it additionally
    requires that no loan application for that same originator and that same
    `state_code` is currently in `status` `TAKEN` or `LOCKED`, since surrendering
    while a file is still in the pipeline would strand it - such an attempt is
    rejected with `ERR_OPEN_PIPELINE_BLOCKS_SURRENDER` (HTTP 422)."

    Withdrawal empties the pipeline, because PRD 3.4 says "an originator may
    withdraw a loan whose `status` is `TAKEN` or `LOCKED`, advancing it to
    `WITHDRAWN`", and the identical surrender then succeeds with the consequences
    PRD 3.1 lists: "On surrender the licence's `ACTIVE` sponsorship is
    relinquished, `authorized_state_codes` is recomputed" - and a relinquished row
    is one that "moves `ACTIVE → RELINQUISHED`" per PRD 3.1.

    Design: Corner/validations/surrender_blocked_by_locked_pipeline_then_allowed_after_withdrawal
    """
    context = setup_authorized_originator(
        api,
        originator_overrides={"nmls_unique_id": NMLS_ID, "legal_name": "Avery Lane"},
        license_overrides={"license_number": LICENSE_NUMBER},
    )
    originator_id = context["originator"]["id"]
    license_id = context["license"]["id"]
    sponsorship_id = context["sponsorship"]["id"]

    loan = take_loan(api, originator_id, requested_amount_cents=20_000_000, par_rate_bps=650)
    locked = lock_loan(
        api, loan["id"], originator_id, note_rate_bps=650, locked_amount_cents=20_000_000
    )
    assert locked["status"] == "LOCKED"

    blocked = api.create_license_status_action(
        license_id,
        build_license_status_action(
            "SURRENDER", note="First surrender attempt with a locked file in the pipeline."
        ),
        analyst_headers(),
    )
    validate_error(blocked, ApiErrorId.ERR_OPEN_PIPELINE_BLOCKS_SURRENDER.value)
    assert get_license(api, license_id)["status"] == "ACTIVE"

    withdrawn = withdraw_loan(api, loan["id"], originator_id)
    assert withdrawn["status"] == "WITHDRAWN"

    surrendered = license_status_action(
        api,
        license_id,
        "SURRENDER",
        note="Second surrender attempt with an empty pipeline.",
    )
    assert surrendered["status"] == "SURRENDERED"

    sponsorship = validate_success(
        api.get_sponsorship_transfer(sponsorship_id, analyst_headers())
    )
    assert sponsorship["status"] == "RELINQUISHED"
    assert get_originator(api, originator_id)["authorized_state_codes"] == []

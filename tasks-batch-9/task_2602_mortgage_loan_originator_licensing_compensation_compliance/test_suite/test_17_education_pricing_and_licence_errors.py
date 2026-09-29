"""Rejections guarding continuing education, pricing concessions and licences.

Each test drives one rejection to its exact `error_id` and pairs it with the
control the same setup makes succeed, or with the state the refused write left
untouched. PRD 2.9 fixes which rejection wins and PRD 5 fixes each status.

The server is restarted with an empty store before every test and the logical
clock reads 2026-08-01T00:00:00Z at that point, so every precondition below is
built through the API inside the test.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    analyst_headers,
    examiner_headers,
    make_originator_headers,
    officer_headers,
)

# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _instant(value):
    """Parse an ISO 8601 instant so two spellings of one instant compare equal.

    Server-computed instants are compared as instants rather than as strings,
    because `...T00:00:00Z` and `...T00:00:00.000Z` denote the same moment.
    """
    assert value is not None, "expected an instant, got null"
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def _assign_plan(api, originator_id, plan_id, expected_originator_version, **overrides):
    """Assign a plan and accept whichever 2xx the endpoint answers with.

    The assertions below read the returned originator record, never the exact
    2xx status of a successful assignment.
    """
    payload = factories.build_plan_assignment(
        plan_id, expected_originator_version, **overrides
    )
    return get_success_data(
        api.assign_compensation_plan(originator_id, payload, officer_headers())
    )


# ---------------------------------------------------------------------------
# PRD 3.2 / 2.9 rule 26 — a rescinded provider cannot source new hours
# ---------------------------------------------------------------------------


def test_ce_credit_against_a_rescinded_course_is_rejected(api):
    """PRD 3.2: "Filing a new credit against a course whose `provider_status` is
    `RESCINDED` is rejected with `ERR_COURSE_PROVIDER_RESCINDED` (HTTP 422)."
    PRD 3.2: "`approved_state_codes` lists the two-letter state codes whose
    regulator accepts the course; it defaults to an empty list, and an empty list
    means the course is accepted in **every** state rather than in none."
    PRD 3.2: "Three of the stored fields are server-computed and any
    client-supplied value for them is ignored: `credit_hours` and `category` are
    copied from the course at creation, and `attributed_year` is derived."
    PRD 3.2: "A new course starts with `provider_status` `APPROVED`."
    PRD 3.2: "When an analyst rescinds a course, its `provider_status` moves to
    `RESCINDED`, and every CE credit sourced from that course that was still
    counting — every credit whose `credit_status` was `APPLIED` — moves to `VOIDED`
    with `void_reason` set to `PROVIDER_RESCINDED`."

    Both courses leave `approved_state_codes` empty, so the state rule of PRD 2.9
    is out of play and provider standing is the only difference between the two
    filings. The refused filing writes no row: the ledger holds exactly the one
    credit sourced from the still-approved course.

    Design: Corner/errors/ce_credit_from_rescinded_provider_returns_course_provider_rescinded
    """
    originator = fixtures.create_originator(api)
    rescinded_course = fixtures.create_ce_course(
        api, credit_hours=3, category="FEDERAL_LAW"
    )
    approved_course = fixtures.create_ce_course(api, credit_hours=2, category="ETHICS")

    rescinded = fixtures.rescind_ce_course(api, rescinded_course["id"])
    assert rescinded["provider_status"] == "RESCINDED", (
        f"expected the provider to be RESCINDED, got {rescinded['provider_status']}"
    )
    assert approved_course["provider_status"] == "APPROVED"

    response = api.create_ce_credit(
        factories.build_ce_credit(
            originator["id"],
            rescinded_course["id"],
            completion_date="2026-07-15T00:00:00Z",
            reporting_period_year=2026,
        ),
        analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_COURSE_PROVIDER_RESCINDED.value)

    accepted = fixtures.file_ce_credit(
        api,
        originator["id"],
        approved_course["id"],
        completion_date="2026-07-15T00:00:00Z",
        reporting_period_year=2026,
    )
    assert accepted["credit_status"] == "APPLIED"
    assert accepted["credit_hours"] == 2, "the hours are copied from the course"
    assert accepted["category"] == "ETHICS", "the category is copied from the course"
    assert accepted["attributed_year"] == 2026

    _, meta = validate_paginated(
        api.list_ce_credits(analyst_headers(), params={"originator_id": originator["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the rejected filing must have created nothing, found {meta['total_count']} credits"
    )


# ---------------------------------------------------------------------------
# PRD 3.2 / 2.9 rule 27 — the course must be approved in a state held
# ---------------------------------------------------------------------------


def test_ce_credit_for_a_course_approved_only_elsewhere_is_rejected(api):
    """PRD 3.2: "And when the course carries a non-empty `approved_state_codes`, the
    originator must hold at least one licence whose `status` is `PENDING`, `ACTIVE`
    or `RENEWAL_PENDING` and whose `state_code` is a member of that list; otherwise
    the filing is rejected with `ERR_COURSE_NOT_APPROVED_IN_STATE` (HTTP 422)."
    PRD 3.1: "A newly filed licence confers no authority whatsoever."

    The single CA licence is deliberately left in PENDING, which this rule accepts
    even though it confers no authority to originate. The rule is a set
    intersection rather than string equality, so a course approved in CA and NV is
    accepted while one approved only in TX is not.

    Design: Corner/errors/ce_credit_for_course_not_approved_in_any_held_state_rejected
    """
    originator = fixtures.create_originator(api)
    licence = fixtures.file_license(api, originator["id"], state_code="CA")
    assert licence["status"] == "PENDING", (
        f"the licence must stay unactivated, got {licence['status']}"
    )

    texas_course = fixtures.create_ce_course(
        api, credit_hours=2, category="STATE_SPECIFIC", approved_state_codes=["TX"]
    )
    western_course = fixtures.create_ce_course(
        api, credit_hours=2, category="STATE_SPECIFIC", approved_state_codes=["CA", "NV"]
    )

    response = api.create_ce_credit(
        factories.build_ce_credit(
            originator["id"],
            texas_course["id"],
            completion_date="2026-07-15T00:00:00Z",
            reporting_period_year=2026,
        ),
        analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_COURSE_NOT_APPROVED_IN_STATE.value)

    accepted = fixtures.file_ce_credit(
        api,
        originator["id"],
        western_course["id"],
        completion_date="2026-07-15T00:00:00Z",
        reporting_period_year=2026,
    )
    assert accepted["credit_status"] == "APPLIED"
    assert accepted["originator_id"] == originator["id"]

    _, meta = validate_paginated(
        api.list_ce_credits(
            analyst_headers(),
            params={"originator_id": originator["id"], "credit_status": "APPLIED"},
        )
    )
    assert meta["total_count"] == 1, (
        f"only the CA/NV credit may exist, found {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# PRD 3.3 / 3.2 / 2.9 rule 31 — one error id over two date surfaces
# ---------------------------------------------------------------------------


def test_zero_length_plan_assignment_interval_is_rejected(api):
    """PRD 3.3: "`effective_to` must be strictly after `effective_from`, and an
    inverted or degenerate range is rejected with `ERR_INVALID_DATE_RANGE`
    (HTTP 422)."
    PRD 3.3: "A `ComplianceOfficer` supplies the `compensation_plan_id` of the plan,
    the `effective_from` and `effective_to` instants bounding the assignment
    inclusively at both ends, and the `expected_originator_version` stale-version
    guard of §2.7."

    The interval is not inverted — its two ends are the same instant — and a closed
    interval bounded inclusively at both ends would still contain that instant, yet
    "strictly after" makes it invalid. Widening it by a single day, with the very
    same version guard, is accepted.

    Design: Corner/errors/non_positive_interval_and_future_completion_date_return_invalid_date_range
    """
    originator = fixtures.create_originator(api)
    plan = fixtures.setup_approved_plan(
        api,
        base_basis_points=105,
        min_fee_cents=0,
        max_fee_cents=5_000_000,
        volume_tier_enabled=False,
        concession_absorption_enabled=False,
    )
    assert plan["status"] == "ACTIVE"
    version_before = originator["version"]

    response = api.assign_compensation_plan(
        originator["id"],
        factories.build_plan_assignment(
            plan["id"],
            version_before,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z",
        ),
        officer_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value)

    untouched = fixtures.get_originator(api, originator["id"])
    assert untouched["compensation_plan_id"] is None
    assert untouched["version"] == version_before

    assigned = _assign_plan(
        api,
        originator["id"],
        plan["id"],
        version_before,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-08-02T00:00:00Z",
    )
    assert assigned["compensation_plan_id"] == plan["id"], (
        "a one-day interval must be accepted"
    )


def test_ce_credit_completed_after_the_clock_instant_is_rejected(api):
    """PRD 3.2: "A `completion_date` later than the logical clock instant is rejected
    with `ERR_INVALID_DATE_RANGE` (HTTP 422)."
    PRD 3.2: "A credit filed with `is_makeup` false is attributed to the calendar
    year, in UTC, of its `completion_date`."

    The same error id guards a second surface. A completion one month in the future
    is refused, while a completion at exactly the clock instant — the boundary the
    rule calls "later than" — is accepted and counts.

    Design: Corner/errors/non_positive_interval_and_future_completion_date_return_invalid_date_range
    """
    originator = fixtures.create_originator(api)
    course = fixtures.create_ce_course(api, credit_hours=2, category="ETHICS")

    response = api.create_ce_credit(
        factories.build_ce_credit(
            originator["id"],
            course["id"],
            completion_date="2026-09-01T00:00:00Z",
            reporting_period_year=2026,
        ),
        analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value)

    _, meta = validate_paginated(
        api.list_ce_credits(analyst_headers(), params={"originator_id": originator["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the future-dated filing must have created nothing, found {meta['total_count']}"
    )

    accepted = fixtures.file_ce_credit(
        api,
        originator["id"],
        course["id"],
        completion_date="2026-08-01T00:00:00Z",
        reporting_period_year=2026,
    )
    assert accepted["credit_status"] == "APPLIED"
    assert _instant(accepted["completion_date"]) == _instant("2026-08-01T00:00:00Z")
    assert accepted["attributed_year"] == 2026


# ---------------------------------------------------------------------------
# PRD 3.6 / 2.9 rule 34 — the two-percent per-loan concession cap
# ---------------------------------------------------------------------------


def test_concession_one_cent_above_the_per_loan_cap_is_rejected(api):
    """PRD 3.6: "Precisely, `concession_cents` must not exceed the loan's
    `locked_amount_cents` multiplied by two, divided by one hundred, and then
    floored to a whole cent; anything above that ceiling is rejected with
    `ERR_CONCESSION_EXCEEDS_CAP` (HTTP 422)."
    PRD 3.6: "A filed exception starts in `SUBMITTED` with `comp_impact_cents` at
    `0`, `requested_by_user_id` stamped from the filing originator's `X-User-ID`,
    and `decided_by_user_id`, `second_decided_by_user_id`, `decided_at` and
    `decision_note` all null."

    On a file locked at 20,000,000 cents the ceiling is 400,000 cents. The cap keys
    on `locked_amount_cents`, and the comparison is "must not exceed", so 400,001
    is refused while exactly 400,000 is accepted and is the only exception the loan
    ends up carrying.

    Design: Corner/errors/concession_one_cent_over_the_two_percent_cap_rejected
    """
    context = fixtures.setup_authorized_originator(
        api,
        state_code="CA",
        sponsorship_effective_at="2026-07-01T00:00:00Z",
        license_overrides={
            "issue_date": "2026-01-02T00:00:00Z",
            "expiration_date": "2027-01-31T00:00:00Z",
        },
    )
    originator_id = context["originator"]["id"]
    loan = fixtures.take_loan(
        api,
        originator_id,
        state_code="CA",
        requested_amount_cents=20_000_000,
        par_rate_bps=650,
    )
    loan = fixtures.lock_loan(
        api, loan["id"], originator_id, note_rate_bps=650, locked_amount_cents=20_000_000
    )
    assert loan["locked_amount_cents"] == 20_000_000
    cap_cents = factories.max_concession_for(loan["locked_amount_cents"])
    assert cap_cents == 400_000, f"the two-percent floor of the file is 400000, got {cap_cents}"

    response = api.create_pricing_exception(
        loan["id"],
        factories.build_pricing_exception(
            requested_rate_bps=600,
            concession_cents=cap_cents + 1,
            reason_code="COMPETITIVE_MATCH",
            justification_text=(
                "Competitor concession quoted one cent above our policy cap for this "
                "locked amount."
            ),
        ),
        make_originator_headers(originator_id),
    )
    validate_error(response, ApiErrorId.ERR_CONCESSION_EXCEEDS_CAP.value)

    accepted = fixtures.request_pricing_exception(
        api,
        loan["id"],
        originator_id,
        requested_rate_bps=600,
        concession_cents=cap_cents,
        reason_code="COMPETITIVE_MATCH",
        justification_text=(
            "Competitor concession quoted at exactly our policy cap for this locked amount."
        ),
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["concession_cents"] == 400_000
    assert accepted["comp_impact_cents"] == 0
    assert accepted["decided_by_user_id"] is None

    _, meta = validate_paginated(
        api.list_pricing_exceptions(
            officer_headers(), params={"loan_application_id": loan["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the at-cap exception may exist, found {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# PRD 3.9 / 2.9 rule 36 — restitution must agree with the finding
# ---------------------------------------------------------------------------


def _open_investigation_on_a_locked_loan(api):
    """A manually opened investigation in OPEN naming a LOCKED CA loan."""
    context = fixtures.setup_authorized_originator(
        api,
        state_code="CA",
        sponsorship_effective_at="2026-07-01T00:00:00Z",
        license_overrides={
            "issue_date": "2026-01-02T00:00:00Z",
            "expiration_date": "2027-01-31T00:00:00Z",
        },
    )
    originator_id = context["originator"]["id"]
    loan = fixtures.take_loan(api, originator_id, state_code="CA", par_rate_bps=650)
    loan = fixtures.lock_loan(
        api, loan["id"], originator_id, note_rate_bps=650, locked_amount_cents=20_000_000
    )
    investigation = fixtures.open_investigation(
        api, loan["id"], trigger_reason="MANUAL_REFERRAL"
    )
    assert investigation["status"] == "OPEN", (
        f"a manually opened investigation starts in OPEN, got {investigation['status']}"
    )
    assert investigation["restitution_cents"] == 0
    context["loan"] = loan
    context["investigation"] = investigation
    return context


def test_finding_whose_restitution_contradicts_it_is_rejected_in_both_directions(api):
    """PRD 3.9: "The officer supplies a `finding` of either `SUBSTANTIATED` or
    `UNSUBSTANTIATED` together with a `restitution_cents` amount, and the two must
    agree: a `SUBSTANTIATED` finding requires `restitution_cents` of at least 1, an
    `UNSUBSTANTIATED` finding requires exactly `0`, and any mismatch is rejected
    with `ERR_RESTITUTION_MISMATCH` (HTTP 422)."
    PRD 3.9: "A manually opened investigation records `opened_by` as `MANUAL`, copies
    its `originator_id` from the named loan rather than accepting one from the
    caller, stamps `detected_at` from the logical clock, starts in `status` `OPEN`,
    and triggers a recompute of the originator's `open_investigation_count` — which
    at all times equals the number of that originator's investigations whose
    `status` is `OPEN` or `SUBSTANTIATED`."

    The agreement is policed in both directions from the one error id, and neither
    refused finding writes anything: the investigation is still OPEN with zero
    restitution after both attempts.

    Design: Corner/errors/investigation_finding_with_mismatched_restitution_rejected
    """
    context = _open_investigation_on_a_locked_loan(api)
    investigation_id = context["investigation"]["id"]

    substantiated_without_money = api.create_investigation_finding(
        investigation_id,
        factories.build_investigation_finding("SUBSTANTIATED", 0),
        officer_headers(),
    )
    validate_error(
        substantiated_without_money, ApiErrorId.ERR_RESTITUTION_MISMATCH.value
    )

    unsubstantiated_with_money = api.create_investigation_finding(
        investigation_id,
        factories.build_investigation_finding("UNSUBSTANTIATED", 500),
        officer_headers(),
    )
    validate_error(unsubstantiated_with_money, ApiErrorId.ERR_RESTITUTION_MISMATCH.value)

    still_open = get_success_data(
        api.get_investigation(investigation_id, officer_headers()), 200
    )
    assert still_open["status"] == "OPEN", (
        f"neither rejection may transition the investigation, got {still_open['status']}"
    )
    assert still_open["restitution_cents"] == 0
    assert still_open["finding_by_user_id"] is None
    assert fixtures.get_loan(api, context["loan"]["id"])["authority_flag"] == "VERIFIED"


def test_agreeing_finding_substantiates_and_marks_the_loan_unauthorized(api):
    """PRD 3.9: "A substantiated finding advances the investigation
    `OPEN → SUBSTANTIATED`, records the ordered borrower restitution in
    `restitution_cents`, and sets the referenced loan's `authority_flag` to
    `UNAUTHORIZED`."

    The same investigation the mismatched attempts could not move is transitioned by
    a `SUBSTANTIATED` finding carrying restitution of at least one cent, which
    confirms the earlier refusals were about the disagreement alone.

    Design: Corner/errors/investigation_finding_with_mismatched_restitution_rejected
    """
    context = _open_investigation_on_a_locked_loan(api)

    decided = fixtures.enter_finding(
        api, context["investigation"]["id"], "SUBSTANTIATED", 500
    )
    assert decided["status"] == "SUBSTANTIATED"
    assert decided["restitution_cents"] == 500

    loan = fixtures.get_loan(api, context["loan"]["id"])
    assert loan["authority_flag"] == "UNAUTHORIZED", (
        f"a substantiated finding invalidates the loan's authority, got {loan['authority_flag']}"
    )


# ---------------------------------------------------------------------------
# PRD 3.2 / 2.9 rule 37 — the reinstatement loop is walkable exactly twice
# ---------------------------------------------------------------------------


def test_third_reinstatement_of_one_licence_is_rejected(api):
    """PRD 3.2: "It requires that the licence's `status` is `EXPIRED`, that
    `ce_satisfied` is true for the licence's current `ce_reporting_year`, that
    `reinstatement_count` is less than two, and that the owning originator's
    `employment_status` is `EMPLOYED`."
    PRD 3.2: "A third reinstatement attempt on the same licence is rejected with
    `ERR_REINSTATEMENT_LIMIT_REACHED` (HTTP 422)."
    PRD 3.2: "On success `reinstatement_count` increments by one, `expiration_date`
    is set to the logical clock instant plus 365 days, `renewal_window_opens_at` is
    set to the logical clock instant plus 305 days, and — unlike the renewal loop —
    `authority_effective_at` is **re-stamped** from the logical clock."
    PRD 3.9: "First, every licence whose `status` is `ACTIVE` or `RENEWAL_PENDING`
    and whose `expiration_date` is at or before the logical clock instant moves to
    `EXPIRED` and runs the full five-hop authority-lapse cascade of §3.1 — relinquish
    the `ACTIVE` sponsorship with `relinquished_at` stamped from the clock, clear the
    licence's denormalised sponsorship fields and recompute `authorized_state_codes`,
    suspend the originator's `TAKEN` and `LOCKED` loans in that state by setting
    `authority_flag` to `SUSPENDED`, open one `CASCADE` investigation with
    `trigger_reason` `AUTHORITY_LAPSE` per suspended loan, and recompute
    `open_investigation_count` — with the licences processed in order of
    `expiration_date` ascending and then `created_at` ascending, and with each
    licence's audit entries appended as one `LICENSE_STATUS_CHANGED` followed by one
    `INVESTIGATION_OPENED` per investigation it opened."
    PRD 3.2: "The licence's `ce_satisfied` is set true only when all four of the
    following minimums are met: the overall total is at least the licence's own
    `required_ce_hours`, the federal-law total is at least three hours, the ethics
    total is at least two hours, and the non-traditional total is at least two
    hours."

    Eight hours split 3 federal / 2 ethics / 2 non-traditional / 1 elective satisfy
    every minimum, and because no renewal completion ever runs the reporting year
    never advances — so the same credits keep the CE precondition satisfied through
    all three attempts and the counter is the only thing that changes. Each
    reinstatement re-bases the calendar off the clock rather than off the previous
    `expiration_date`, and the refused third attempt bumps nothing.

    Design: Corner/errors/third_reinstatement_returns_reinstatement_limit_reached
    """
    originator = fixtures.create_originator(api)
    licence = fixtures.file_license(
        api,
        originator["id"],
        state_code="CA",
        issue_date="2026-01-02T00:00:00Z",
        expiration_date="2026-09-01T00:00:00Z",
        renewal_window_opens_at="2026-08-15T00:00:00Z",
        ce_reporting_year=2026,
        required_ce_hours=8,
    )
    licence_id = licence["id"]
    fixtures.activate_license(api, licence_id)

    for hours, category in ((3, "FEDERAL_LAW"), (2, "ETHICS"), (2, "NONTRADITIONAL"), (1, "ELECTIVE")):
        course = fixtures.create_ce_course(api, credit_hours=hours, category=category)
        fixtures.file_ce_credit(
            api,
            originator["id"],
            course["id"],
            completion_date="2026-08-01T00:00:00Z",
            reporting_period_year=2026,
        )

    before = fixtures.get_license(api, licence_id)
    assert before["ce_hours_applied"] == 8, (
        f"3 + 2 + 2 + 1 hours all count toward 2026, got {before['ce_hours_applied']}"
    )
    assert before["ce_satisfied"] is True
    assert before["reinstatement_count"] == 0

    # First trip round the loop: expire at 2026-09-02, then reinstate.
    fixtures.set_clock(api, "2026-09-02T00:00:00Z")
    first_sweep = fixtures.run_sweep(api)
    assert licence_id in first_sweep["expired_license_ids"], (
        "the sweep is the only thing that expires a licence"
    )
    assert first_sweep["opened_investigation_ids"] == [], (
        "there are no loans to suspend, so no cascade investigation is opened"
    )

    first = fixtures.license_status_action(
        api, licence_id, "REINSTATE", note="First reinstatement; CE for 2026 remains satisfied."
    )
    assert first["status"] == "ACTIVE"
    assert first["reinstatement_count"] == 1
    assert _instant(first["expiration_date"]) == _instant("2027-09-02T00:00:00Z"), (
        "the clock instant 2026-09-02 plus 365 days"
    )
    assert _instant(first["renewal_window_opens_at"]) == _instant("2027-07-04T00:00:00Z"), (
        "the clock instant 2026-09-02 plus 305 days"
    )
    assert _instant(first["authority_effective_at"]) == _instant("2026-09-02T00:00:00Z"), (
        "authority is re-stamped from the clock at reinstatement"
    )

    # Second and final permitted trip: expire at 2027-09-03, then reinstate.
    fixtures.set_clock(api, "2027-09-03T00:00:00Z")
    second_sweep = fixtures.run_sweep(api)
    assert licence_id in second_sweep["expired_license_ids"]

    second = fixtures.license_status_action(
        api, licence_id, "REINSTATE", note="Second and final permitted reinstatement."
    )
    assert second["status"] == "ACTIVE"
    assert second["reinstatement_count"] == 2
    assert _instant(second["expiration_date"]) == _instant("2028-09-02T00:00:00Z"), (
        "the calendar is re-based off the clock 2027-09-03, not off 2027-09-02"
    )
    assert _instant(second["renewal_window_opens_at"]) == _instant("2028-07-04T00:00:00Z")

    # Third attempt: refused.
    fixtures.set_clock(api, "2028-09-04T00:00:00Z")
    third_sweep = fixtures.run_sweep(api)
    assert licence_id in third_sweep["expired_license_ids"]

    response = api.create_license_status_action(
        licence_id,
        factories.build_license_status_action(
            "REINSTATE", note="Third attempt; must be refused."
        ),
        analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_REINSTATEMENT_LIMIT_REACHED.value)

    final = fixtures.get_license(api, licence_id)
    assert final["status"] == "EXPIRED", (
        f"the refusal left the licence lapsed, got {final['status']}"
    )
    assert final["reinstatement_count"] == 2, (
        f"the failed attempt must not bump the counter, got {final['reinstatement_count']}"
    )
    assert _instant(final["expiration_date"]) == _instant("2028-09-02T00:00:00Z")
    assert final["ce_reporting_year"] == 2026, "no renewal completion ever ran"

    authority = get_success_data(
        api.get_originator_authority(originator["id"], examiner_headers()), 200
    )
    assert authority["authorized_state_codes"] == [], (
        f"an EXPIRED licence confers no authority, got {authority['authorized_state_codes']}"
    )

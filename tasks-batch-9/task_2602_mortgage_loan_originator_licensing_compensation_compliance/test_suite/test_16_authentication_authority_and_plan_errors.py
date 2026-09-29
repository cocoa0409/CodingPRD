"""Rejections guarding authentication, sponsored authority and plan assignment.

Every test here drives one rejection to its exact `error_id` and then pins the
state the refused write must not have changed, or the control call that the same
setup makes succeed. The order the rejections fire in is fixed by PRD 2.9 and
each error's HTTP status by PRD 5.

The server is restarted with an empty store before every test and the logical
clock reads 2026-08-01T00:00:00Z at that point, so each test builds all of its
preconditions through the API.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    OFFICER_USER_ID,
    SECOND_OFFICER_USER_ID,
    analyst_headers,
    examiner_headers,
    loan_ops_headers,
    make_originator_headers,
    officer_headers,
)

# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _assign_plan(api, originator_id, plan_id, expected_originator_version, **overrides):
    """Assign a plan and accept whichever 2xx the endpoint answers with.

    PRD 3.3 fixes the response body — the updated originator record — but the
    tests below assert only that body, never the particular 2xx status, so the
    lenient reader is used deliberately here.
    """
    payload = factories.build_plan_assignment(
        plan_id, expected_originator_version, **overrides
    )
    return get_success_data(
        api.assign_compensation_plan(originator_id, payload, officer_headers())
    )


# ---------------------------------------------------------------------------
# PRD 2.1 / 2.9 rule 1 — both authentication headers present and non-empty
# ---------------------------------------------------------------------------


def test_list_request_without_either_auth_header_is_rejected(api):
    """PRD 2.1: "If either header is absent or present but empty, the request is
    rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."
    PRD 2.1: "This check does not apply to the shared read endpoints, which every
    one of the seven roles may call against any resource."

    One originator exists, so the 401 cannot be an artefact of an empty table:
    the very same list call carrying both headers reports that row.

    Design: Corner/errors/request_with_missing_auth_headers_returns_401
    """
    originator = fixtures.create_originator(api)

    response = api._request("GET", "/originators", None, {})
    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    listing = api.list_originators(analyst_headers(), params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(listing)
    assert meta["total_count"] == 1, (
        f"expected the one registered originator to be listed, got {meta['total_count']}"
    )
    assert [row["id"] for row in data] == [originator["id"]]


def test_list_request_with_empty_user_id_header_is_rejected(api):
    """PRD 2.1: "If either header is absent or present but empty, the request is
    rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

    The role header is a well-formed `LicensingAnalyst`; only `X-User-ID` is
    empty, which is enough on its own to fail PRD 2.9's first rule.

    Design: Corner/errors/request_with_missing_auth_headers_returns_401
    """
    fixtures.create_originator(api)

    response = api._request(
        "GET",
        "/originators",
        None,
        {"X-User-ID": "", "X-User-Role": "LicensingAnalyst"},
    )
    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)


# ---------------------------------------------------------------------------
# PRD 2.1 / 2.9 rule 2 — the presented role is one of the seven
# ---------------------------------------------------------------------------


def test_undeclared_role_header_is_rejected_as_unknown_role(api):
    """PRD 2.1: "If `X-User-Role` carries a value that is not one of the seven
    roles enumerated below, the request is rejected with `ERR_UNKNOWN_ROLE`
    (HTTP 401)."
    PRD 2.1: "This check does not apply to the shared read endpoints, which every
    one of the seven roles may call against any resource."

    `Underwriter` is deliberately not one of the seven declared roles, so the
    read is refused at PRD 2.9's second rule with a 401 rather than the 403 a
    declared-but-unpermitted role would earn. A declared role reads the same
    path successfully.

    Design: Corner/errors/request_with_invalid_role_header_returns_unknown_role
    """
    originator = fixtures.create_originator(api)

    response = api._request(
        "GET",
        f"/originators/{originator['id']}",
        None,
        {"X-User-ID": "user-underwriter-01", "X-User-Role": "Underwriter"},
    )
    validate_error(response, ApiErrorId.ERR_UNKNOWN_ROLE.value)

    readable = validate_success(
        api.get_originator(originator["id"], examiner_headers()), 200
    )
    assert readable["nmls_unique_id"] == originator["nmls_unique_id"]


# ---------------------------------------------------------------------------
# PRD 3.4 / 2.9 rule 15 — intake needs a sponsorship covering the instant
# ---------------------------------------------------------------------------


def _unsponsored_active_license(api):
    """An ACTIVE, unsponsored CA licence with the clock at 2026-08-02.

    The licence is activated at 2026-08-01, sponsored from 2026-07-01 and that
    sponsorship is then relinquished at 2026-08-01, so the licence keeps its
    authority interval but has no sponsorship covering the later instant.
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
    relinquished = fixtures.relinquish_sponsorship(api, context["sponsorship"]["id"])
    assert relinquished["status"] == "RELINQUISHED", (
        f"expected the sponsorship to close, got {relinquished['status']}"
    )
    fixtures.set_clock(api, "2026-08-02T00:00:00Z")
    context["license"] = fixtures.get_license(api, context["license"]["id"])
    return context


def test_intake_on_an_unsponsored_active_license_is_rejected(api):
    """PRD 3.4: "Third, the authorising licence must have a sponsorship interval
    whose half-open span from `effective_at` up to `relinquished_at` covers the
    logical clock instant; a licence with no covering sponsorship is rejected with
    `ERR_SPONSORSHIP_REQUIRED` (HTTP 422)."
    PRD 3.1: "The system stamps `relinquished_at` from the logical clock, clears
    the licence's `active_sponsoring_institution_code` and
    `active_sponsorship_effective_at` to null, increments the licence's `version`
    by one, recomputes the originator's `authorized_state_codes` — the state drops
    out, because an unsponsored licence confers no authority at all — and appends
    a `SPONSORSHIP_CHANGED` audit entry."

    2026-08-02 sits inside the licence's own half-open interval and the originator
    is EMPLOYED, so the earlier licence-status and state-authority rules of
    PRD 2.9 are both satisfied; only the sponsorship is missing. The refusal
    leaves the licence itself untouched in ACTIVE.

    Design: Corner/errors/taking_application_without_active_sponsorship_returns_sponsorship_required
    """
    context = _unsponsored_active_license(api)
    originator_id = context["originator"]["id"]

    response = api.create_loan_application(
        factories.build_loan_application(originator_id, state_code="CA"),
        make_originator_headers(originator_id),
    )
    validate_error(response, ApiErrorId.ERR_SPONSORSHIP_REQUIRED.value)

    licence = fixtures.get_license(api, context["license"]["id"])
    assert licence["status"] == "ACTIVE", (
        f"the licence never left ACTIVE, got {licence['status']}"
    )
    assert licence["active_sponsoring_institution_code"] is None
    assert licence["active_sponsorship_effective_at"] is None
    assert "CA" not in fixtures.get_originator(api, originator_id)["authorized_state_codes"]


def test_intake_succeeds_once_an_adjacent_sponsorship_covers_the_instant(api):
    """PRD 3.1: "Exact adjacency is legal and is the intended way to hand a licence
    from one institution to the next: an incoming `effective_at` equal to a previous
    row's `relinquished_at` is accepted."
    PRD 3.4: "A successfully taken application stamps `application_taken_at` from
    the logical clock — this is the instant the authority window check was
    evaluated against, and it is recorded so that a later examination can
    reconstruct the decision — and initialises `status` to `TAKEN`,
    `compensation_status` to `NOT_APPLICABLE` and `authority_flag` to `VERIFIED`."

    A second institution claims the same licence from 2026-08-02 — one day after
    the first interval closed at 2026-08-01 — and the intake that was refused for
    want of sponsorship now succeeds.

    Design: Corner/errors/taking_application_without_active_sponsorship_returns_sponsorship_required
    """
    context = _unsponsored_active_license(api)
    originator_id = context["originator"]["id"]

    sponsorship = fixtures.claim_sponsorship(
        api,
        context["license"]["id"],
        context["license"]["version"],
        sponsoring_institution_code="INST-0002",
        effective_at="2026-08-02T00:00:00Z",
    )
    assert sponsorship["status"] == "ACTIVE", (
        "adjacency at 2026-08-01 -> 2026-08-02 must be accepted, got "
        f"{sponsorship['status']}"
    )
    assert sponsorship["relinquished_at"] is None

    loan = fixtures.take_loan(api, originator_id, state_code="CA")
    assert loan["status"] == "TAKEN"
    assert loan["authority_flag"] == "VERIFIED"
    assert loan["compensation_status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------------------
# PRD 3.6 / 2.9 rule 18 — an ELEVATED originator needs a second approver
# ---------------------------------------------------------------------------

FIRST_EXCEPTION_JUSTIFICATION = (
    "Competitor quoted 700 bps on an identical file; the concession retains the borrower."
)
SECOND_EXCEPTION_JUSTIFICATION = (
    "Appraisal delay caused by our vendor; the concession compensates the borrower "
    "for the extension."
)


def _elevated_originator_with_locked_loan(api):
    """An ELEVATED originator plus a second loan sitting in LOCKED.

    The first loan carries an APPROVED exception, an 80-bps note-over-par spread
    and dual compensation at close, which is what drives the exposure score to
    70 and monitoring to ELEVATED while the originator is still STANDARD.
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

    plan = fixtures.setup_approved_plan(
        api,
        base_basis_points=105,
        min_fee_cents=0,
        max_fee_cents=5_000_000,
        volume_tier_enabled=False,
        concession_absorption_enabled=False,
    )
    _assign_plan(
        api,
        originator_id,
        plan["id"],
        context["originator"]["version"],
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
    )

    first_loan = fixtures.take_loan(api, originator_id, state_code="CA", par_rate_bps=650)
    fixtures.lock_loan(
        api,
        first_loan["id"],
        originator_id,
        note_rate_bps=730,
        locked_amount_cents=20_000_000,
    )
    first_exception = fixtures.request_pricing_exception(
        api,
        first_loan["id"],
        originator_id,
        requested_rate_bps=700,
        concession_cents=100_000,
        reason_code="COMPETITIVE_MATCH",
        justification_text=FIRST_EXCEPTION_JUSTIFICATION,
    )
    assert first_exception["requires_second_approval"] is False, (
        "a STANDARD originator's exception must not demand a second approver"
    )
    decided = fixtures.decide_pricing_exception(api, first_exception["id"], "APPROVE")
    assert decided["status"] == "APPROVED"

    fixtures.close_loan(
        api,
        first_loan["id"],
        funded_amount_cents=20_000_000,
        funded_at="2026-08-10T00:00:00Z",
        lender_paid_comp_cents=200_000,
        borrower_paid_comp_cents=10_000,
        file_quality_score=95,
        hours_worked_pct=80,
    )
    originator = fixtures.get_originator(api, originator_id)
    assert originator["exposure_score"] == 70, (
        "0.35*100 + 0.25*80 + 0.15*100 + 0.25*0 rounds to 70, got "
        f"{originator['exposure_score']}"
    )
    assert originator["monitoring_status"] == "ELEVATED", (
        f"a score of 70 must read ELEVATED, got {originator['monitoring_status']}"
    )

    second_loan = fixtures.take_loan(api, originator_id, state_code="CA", par_rate_bps=650)
    second_loan = fixtures.lock_loan(
        api,
        second_loan["id"],
        originator_id,
        note_rate_bps=650,
        locked_amount_cents=20_000_000,
    )
    context["originator"] = originator
    context["loan"] = second_loan
    return context


def _request_second_exception(api, loan_id, originator_id):
    """The exception filed once the originator is already ELEVATED."""
    exception = fixtures.request_pricing_exception(
        api,
        loan_id,
        originator_id,
        requested_rate_bps=630,
        concession_cents=100_000,
        reason_code="SERVICE_ISSUE",
        justification_text=SECOND_EXCEPTION_JUSTIFICATION,
    )
    assert exception["requires_second_approval"] is True, (
        "an exception filed by an ELEVATED originator must be stamped as needing a "
        "second approver"
    )
    return exception


def test_approving_an_elevated_originators_exception_without_a_second_approver_is_rejected(api):
    """PRD 3.6: "A missing second approver on an exception that requires one is
    rejected with `ERR_SECOND_APPROVAL_REQUIRED` (HTTP 422); a second approver who
    is the decider or the requester, and equally a decider who is the requester, is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) — and per §2.9 the
    segregation rejection is reported ahead of the missing-second-approver
    rejection."
    PRD 3.6: "One further field is stamped at filing: `requires_second_approval` is
    set true when the owning originator's `monitoring_status` reads `ELEVATED` at
    that instant, and false otherwise."
    PRD 3.6: "A filed exception starts in `SUBMITTED` with `comp_impact_cents` at
    `0`, `requested_by_user_id` stamped from the filing originator's `X-User-ID`,
    and `decided_by_user_id`, `second_decided_by_user_id`, `decided_at` and
    `decision_note` all null."

    The refused approval leaves the exception in SUBMITTED with neither decider
    recorded, so the second attempt in the companion test is a first decision
    rather than a re-decision.

    Design: Corner/errors/elevated_originator_pricing_exception_requires_second_approver
    """
    context = _elevated_originator_with_locked_loan(api)
    exception = _request_second_exception(
        api, context["loan"]["id"], context["originator"]["id"]
    )

    response = api.create_pricing_exception_decision(
        exception["id"],
        factories.build_pricing_exception_decision(
            "APPROVE", decision_note="Approval attempted without a second approver."
        ),
        officer_headers(),
    )
    validate_error(response, ApiErrorId.ERR_SECOND_APPROVAL_REQUIRED.value)

    unchanged = fixtures.get_pricing_exception(api, exception["id"])
    assert unchanged["status"] == "SUBMITTED", (
        f"the exception must still be awaiting decision, got {unchanged['status']}"
    )
    assert unchanged["decided_by_user_id"] is None
    assert unchanged["second_decided_by_user_id"] is None
    assert unchanged["comp_impact_cents"] == 0


def test_naming_a_second_approver_completes_the_elevated_exception_approval(api):
    """PRD 3.6: "It requires that the exception is still `SUBMITTED`; that the loan
    it names is still in `status` `LOCKED`; that the deciding `X-User-ID` differs
    from `requested_by_user_id`; that, when `requires_second_approval` is true, the
    request carries a non-empty `second_approver_user_id` whose value differs from
    **both** the deciding `X-User-ID` and `requested_by_user_id`; and that the
    owning originator's `compensation_plan_id` is non-null with that plan's
    `status` equal to `ACTIVE`."
    PRD 3.6: "On approval the system writes `decided_by_user_id` from the deciding
    `X-User-ID`, stamps `decided_at` from the logical clock, stores the supplied
    `decision_note`, sets `second_decided_by_user_id` to the supplied
    `second_approver_user_id` when `requires_second_approval` is true and to null
    otherwise, computes `comp_impact_cents` as described below, recomputes the
    originator's `exposure_score` and `monitoring_status`, appends an
    `EXCEPTION_DECIDED` audit entry, and increments the exception's `version` by
    one."

    The same approval that PRD 2.9's rule 18 refuses succeeds once a distinct
    second officer is named, which shows the rejection is about the missing
    approver rather than about the exception itself.

    Design: Corner/errors/elevated_originator_pricing_exception_requires_second_approver
    """
    context = _elevated_originator_with_locked_loan(api)
    exception = _request_second_exception(
        api, context["loan"]["id"], context["originator"]["id"]
    )

    decided = fixtures.decide_pricing_exception(
        api,
        exception["id"],
        "APPROVE",
        decision_note="Approval with the required second approver.",
        second_approver_user_id=SECOND_OFFICER_USER_ID,
    )
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == OFFICER_USER_ID
    assert decided["second_decided_by_user_id"] == SECOND_OFFICER_USER_ID


# ---------------------------------------------------------------------------
# PRD 3.3 / 2.9 rule 23 — only an ACTIVE plan can be assigned
# ---------------------------------------------------------------------------


def test_assigning_a_draft_plan_is_rejected_then_accepted_once_approved(api):
    """PRD 3.3: "The referenced plan's `status` must be `ACTIVE`; assigning a plan
    in `DRAFT`, `REJECTED` or `SUPERSEDED` is rejected with `ERR_PLAN_NOT_ACTIVE`
    (HTTP 422)."
    PRD 3.1: "`compensation_plan_id` is never set by a client on the originator
    record — it is written only by a plan assignment and cleared only by assignment
    expiry during the nightly sweep."

    The plan exists and the optimistic-concurrency version supplied is current, so
    DRAFT status is the only defect. The rejected assignment bumps nothing — the
    originator's `version` is unchanged, which is why the very same
    `expected_originator_version` is still accepted after the plan is approved.

    Design: Corner/errors/assigning_a_draft_plan_returns_plan_not_active
    """
    originator = fixtures.create_originator(api)
    assert originator["compensation_plan_id"] is None
    version_before = originator["version"]

    plan = fixtures.draft_plan(
        api,
        base_basis_points=105,
        min_fee_cents=0,
        max_fee_cents=5_000_000,
        volume_tier_enabled=False,
        concession_absorption_enabled=False,
    )
    assert plan["status"] == "DRAFT", f"expected a DRAFT plan, got {plan['status']}"
    fixtures.declare_variable(
        api, plan["id"], variable_type="LOAN_VOLUME_UNITS", weight_pct=100
    )

    payload = factories.build_plan_assignment(
        plan["id"],
        version_before,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
    )
    response = api.assign_compensation_plan(originator["id"], payload, officer_headers())
    validate_error(response, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)

    untouched = fixtures.get_originator(api, originator["id"])
    assert untouched["compensation_plan_id"] is None, (
        "the refused assignment must not have bound the plan"
    )
    assert untouched["version"] == version_before, (
        f"the refused write bumped the version to {untouched['version']}"
    )

    approved = fixtures.decide_plan(api, plan["id"], "APPROVE")
    assert approved["status"] == "ACTIVE"

    assigned = _assign_plan(
        api,
        originator["id"],
        plan["id"],
        version_before,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
    )
    assert assigned["compensation_plan_id"] == plan["id"], (
        "the identical assignment must succeed once the plan is ACTIVE"
    )


# ---------------------------------------------------------------------------
# PRD 3.5 / 2.9 rule 24 — closing needs the originator to carry a plan
# ---------------------------------------------------------------------------


def test_closing_a_loan_with_no_assigned_plan_is_rejected(api):
    """PRD 3.5: "The originator must carry a plan at all — a null
    `compensation_plan_id` on the originator is rejected with
    `ERR_NO_ACTIVE_COMP_PLAN` (HTTP 422) — that plan's `status` must be `ACTIVE`,
    rejected otherwise with `ERR_PLAN_NOT_ACTIVE`, and the plan's closed assignment
    interval from `assignment_effective_from` through `assignment_effective_to`,
    inclusive at both ends, must contain the supplied `funded_at`."
    PRD 3.4: "Its `note_rate_bps` and `locked_amount_cents` read null while the loan
    is `TAKEN`; its `funded_amount_cents`, `funded_at`, `payoff_date` and
    `closed_unit_index` read null until the loan closes or pays off; its
    `compensation_plan_id` reads null until close; and its
    `lender_paid_comp_cents`, `borrower_paid_comp_cents`, `file_quality_score` and
    `hours_worked_pct` all read `0` until they are reported at close."
    PRD 2.11: "An originator's `lifetime_accrued_cents` is at all times the sum of
    `accrued_cents` over every one of that originator's ledger lines in any status,
    `lifetime_clawed_back_cents` is at all times the sum of `clawback_cents` over
    the same set, and `net_compensation_cents` is at all times exactly
    `lifetime_accrued_cents` less `lifetime_clawed_back_cents` — it is a derived
    balance and is never written directly."

    The missing plan is caught before the reported compensation could be measured
    against any cap, so nothing about the close is recorded: the loan stays LOCKED
    with no funded amount and no ledger line comes into existence.

    Design: Corner/errors/closing_a_loan_with_no_assigned_plan_returns_no_active_comp_plan
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
    assert context["originator"]["compensation_plan_id"] is None

    loan = fixtures.take_loan(api, originator_id, state_code="CA", par_rate_bps=650)
    loan = fixtures.lock_loan(
        api, loan["id"], originator_id, note_rate_bps=650, locked_amount_cents=20_000_000
    )

    response = api.close_loan_application(
        loan["id"],
        factories.build_loan_close(
            funded_amount_cents=20_000_000,
            funded_at="2026-08-20T00:00:00Z",
            lender_paid_comp_cents=210_000,
            borrower_paid_comp_cents=0,
            file_quality_score=95,
            hours_worked_pct=80,
        ),
        loan_ops_headers(),
    )
    validate_error(response, ApiErrorId.ERR_NO_ACTIVE_COMP_PLAN.value)

    unchanged = fixtures.get_loan(api, loan["id"])
    assert unchanged["status"] == "LOCKED", (
        f"the loan must still be LOCKED, got {unchanged['status']}"
    )
    assert unchanged["compensation_status"] == "NOT_APPLICABLE"
    assert unchanged["closed_unit_index"] is None
    assert unchanged["funded_amount_cents"] is None
    assert unchanged["funded_at"] is None

    _, meta = validate_paginated(
        api.list_compensation_records(
            officer_headers(), params={"loan_application_id": loan["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no ledger line may exist for a refused close, found {meta['total_count']}"
    )
    assert fixtures.get_originator(api, originator_id)["lifetime_accrued_cents"] == 0

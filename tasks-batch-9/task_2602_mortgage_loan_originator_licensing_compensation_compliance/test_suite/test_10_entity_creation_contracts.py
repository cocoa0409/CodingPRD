"""What a freshly created row reads back as.

Every test here builds its own preconditions from scratch: the runner restarts
the server with an empty store before each test, and the logical compliance
clock reads 2026-08-01T00:00:00Z until a test moves it.
"""
from datetime import datetime

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_ce_course,
    assert_compensation_record,
    assert_license_registration,
    assert_loan_application,
    assert_originator,
)
from test_helpers.test_users import analyst_headers, officer_headers


def _instant(value):
    """The instant an ISO 8601 string denotes, independent of its serialisation.

    The specification pins which instant a stamped field carries; it does not pin
    whether that field is rendered with or without fractional-second digits, so
    stamped instants are compared as instants.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_originator_registration_returns_inert_row_with_zeroed_ledger(api):
    """PRD §3.1: "A freshly registered originator is deliberately inert. Its
    `monitoring_status` reads `STANDARD` and its `exposure_score` reads `0`; its three
    ledger fields `lifetime_accrued_cents`, `lifetime_clawed_back_cents` and
    `net_compensation_cents` all read `0`; its `authorized_state_codes` is an empty list;
    its `open_investigation_count` is `0`; and its `compensation_plan_id` is null, because
    no plan has been assigned yet."
    PRD §3.1: "An `employment_status` may optionally be supplied; when it is omitted the
    record starts as `EMPLOYED`, and the only other permitted values are `SUSPENDED` and
    `TERMINATED`."
    PRD §2.5: "Every resource in this system except the audit trail additionally carries an
    `updated_at` timestamp in the same format, refreshed on every mutation of that row, and
    a `version` integer that starts at `1` when the row is created and increments by exactly
    one on every mutation of that row."

    Design: Corner/entities/originator_creation_returns_full_row_with_zeroed_ledger
    """
    response = api.create_originator(
        {
            "nmls_unique_id": "2200001",
            "legal_name": "Avery Lane",
            "hire_date": "2024-01-15T00:00:00Z",
            "employment_status": "EMPLOYED",
        },
        analyst_headers(),
    )
    originator = validate_success(response, 201)

    assert_originator(originator)
    assert originator["nmls_unique_id"] == "2200001"
    assert originator["legal_name"] == "Avery Lane"
    assert originator["employment_status"] == "EMPLOYED"
    assert originator["monitoring_status"] == "STANDARD"
    assert originator["exposure_score"] == 0
    assert originator["lifetime_accrued_cents"] == 0
    assert originator["lifetime_clawed_back_cents"] == 0
    assert originator["net_compensation_cents"] == 0
    assert originator["authorized_state_codes"] == []
    assert originator["open_investigation_count"] == 0
    assert originator["compensation_plan_id"] is None
    assert originator["version"] == 1


def test_license_registration_read_back_reads_pending_and_unsponsored(api):
    """PRD §3.1: "A newly filed licence confers no authority whatsoever. It starts in
    `PENDING` with `authority_effective_at` null, `ce_hours_applied` at `0`, `ce_satisfied`
    false and `reinstatement_count` at `0`."
    PRD §3.1: "Reading a licence back returns its computed compliance posture alongside its
    filed data: `ce_hours_applied` and `ce_satisfied` for the current reporting year, and the
    two denormalised sponsorship fields `active_sponsoring_institution_code` and
    `active_sponsorship_effective_at`, which mirror the licence's currently `ACTIVE`
    sponsorship and read null while the licence is unsponsored."

    Design: Corner/entities/license_registration_get_returns_stored_row_in_pending
    """
    originator = fixtures.create_originator(api, nmls_unique_id="2200001")
    filed = fixtures.file_license(
        api,
        originator["id"],
        state_code="CA",
        license_number="CA-DFPI-70001",
        issue_date="2026-01-02T00:00:00Z",
        expiration_date="2027-01-31T00:00:00Z",
        renewal_window_opens_at="2026-11-01T00:00:00Z",
        ce_reporting_year=2026,
        required_ce_hours=8,
    )

    licence = validate_success(api.get_license_registration(filed["id"], officer_headers()))

    assert_license_registration(licence)
    assert licence["status"] == "PENDING"
    assert licence["state_code"] == "CA"
    assert licence["license_number"] == "CA-DFPI-70001"
    assert licence["authority_effective_at"] is None
    assert licence["ce_hours_applied"] == 0
    assert licence["ce_satisfied"] is False
    assert licence["active_sponsoring_institution_code"] is None
    assert licence["active_sponsorship_effective_at"] is None
    assert licence["reinstatement_count"] == 0
    assert licence["required_ce_hours"] == 8
    assert licence["originator_id"] == originator["id"]


def test_compensation_records_list_filters_by_originator_and_paginates(api):
    """PRD §2.10: "Sub-resource collections are also reachable as peer top-level collections
    with filters, and every such list endpoint accepts the parent's foreign key as a filter so
    that a client can walk the graph in either direction."
    PRD §2.3: "Successful list responses carry four pagination fields in the `meta` object:
    `limit` and `offset` echoing the effective values used, `total_count` giving the number of
    rows matching the filters before paging, and `has_more` indicating whether any matching
    rows remain beyond this page."
    PRD §3.5: "When `authority_flag` reads `VERIFIED`, `compensation_status` is set to
    `ACCRUED` and exactly one ledger line is created for the loan with `variant` `PROVISIONAL`,
    computed as described below."
    PRD §3.5: "The effective rate in basis points is the plan's `base_basis_points` plus the
    `tier_bps_adder`."
    PRD §3.5: "When the governing plan's `volume_tier_enabled` is false the adder is zero and
    nothing further is evaluated."

    Design: Corner/entities/compensation_records_list_filters_by_originator_and_paginates
    """
    context = fixtures.setup_originator_with_plan(
        api,
        plan_overrides={
            "base_basis_points": 105,
            "min_fee_cents": 0,
            "max_fee_cents": 5_000_000,
            "volume_tier_enabled": False,
            "concession_absorption_enabled": False,
        },
    )
    originator_id = context["originator"]["id"]

    first = fixtures.take_loan(
        api, originator_id, state_code="CA", requested_amount_cents=20_000_000, par_rate_bps=650
    )
    fixtures.lock_loan(api, first["id"], originator_id, note_rate_bps=650, locked_amount_cents=20_000_000)
    second = fixtures.take_loan(
        api, originator_id, state_code="CA", requested_amount_cents=10_000_000, par_rate_bps=650
    )
    fixtures.lock_loan(api, second["id"], originator_id, note_rate_bps=650, locked_amount_cents=10_000_000)

    fixtures.set_clock(api, "2026-08-21T00:00:00Z")
    fixtures.close_loan(
        api,
        first["id"],
        funded_amount_cents=20_000_000,
        funded_at="2026-08-20T00:00:00Z",
        lender_paid_comp_cents=210_000,
        borrower_paid_comp_cents=0,
        file_quality_score=95,
        hours_worked_pct=80,
    )
    fixtures.close_loan(
        api,
        second["id"],
        funded_amount_cents=10_000_000,
        funded_at="2026-08-21T00:00:00Z",
        lender_paid_comp_cents=105_000,
        borrower_paid_comp_cents=0,
        file_quality_score=95,
        hours_worked_pct=80,
    )

    page_zero, meta_zero = validate_paginated(
        api.list_compensation_records(
            officer_headers(), params={"originator_id": originator_id, "limit": 1, "offset": 0}
        )
    )
    page_one, meta_one = validate_paginated(
        api.list_compensation_records(
            officer_headers(), params={"originator_id": originator_id, "limit": 1, "offset": 1}
        )
    )

    assert meta_zero["total_count"] == 2, f"expected two ledger lines, meta was {meta_zero}"
    assert meta_one["total_count"] == 2, f"expected two ledger lines, meta was {meta_one}"
    assert meta_zero["has_more"] is True, "one row of two remains beyond the first page"
    assert meta_one["has_more"] is False, "no row remains beyond the second page"
    assert len(page_zero) == 1, f"limit 1 must return one element: {page_zero}"
    assert len(page_one) == 1, f"limit 1 must return one element: {page_one}"

    for record in (page_zero[0], page_one[0]):
        assert_compensation_record(record)
        assert record["originator_id"] == originator_id
        assert record["variant"] == "PROVISIONAL"

    amounts = sorted([page_zero[0]["accrued_cents"], page_one[0]["accrued_cents"]])
    assert amounts == [105_000, 210_000], (
        f"expected 105000 cents on the 10000000-cent loan and 210000 on the "
        f"20000000-cent loan at 105 basis points, got {amounts}"
    )


def test_get_originator_with_unknown_id_returns_not_found(api):
    """PRD §2.9: "Every id in the request path resolves to an existing row, checked left to
    right — otherwise `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/get_originator_with_unknown_id_returns_not_found
    """
    response = api.get_originator(NON_EXISTENT_UUID, analyst_headers())
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    rows, meta = validate_paginated(api.list_originators(analyst_headers()))
    assert meta["total_count"] == 0, f"the failed read must create nothing: {rows}"


def test_file_license_without_expiration_date_rejected(api):
    """PRD §3.1: "The analyst supplies the `originator_id` of the individual, the `state_code`
    — an uppercase two-letter USPS code — the state-issued `license_number` as a string of
    between four and thirty-two characters, the `issue_date` on which the state issued it, the
    `expiration_date` at which authority lapses unless renewal completes, and the
    `renewal_window_opens_at` instant that is the earliest a renewal may be filed."
    PRD §2.9: "The request body conforms to the endpoint's declared input shape: required
    fields present, types correct, enum members recognised, numeric ranges honoured, ISO 8601
    timestamps parseable, array element formats correct — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_license_registration_without_expiration_date_rejected
    """
    originator = fixtures.create_originator(api, nmls_unique_id="2200001")

    response = api.create_license_registration(
        {
            "originator_id": originator["id"],
            "state_code": "CA",
            "license_number": "CA-DFPI-70001",
            "issue_date": "2026-01-02T00:00:00Z",
            "renewal_window_opens_at": "2026-11-01T00:00:00Z",
            "ce_reporting_year": 2026,
        },
        analyst_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, meta = validate_paginated(
        api.list_license_registrations(analyst_headers(), params={"originator_id": originator["id"]})
    )
    assert meta["total_count"] == 0, f"the rejected filing must persist no licence: {rows}"


def test_ce_course_omitted_flags_take_their_declared_defaults(api):
    """PRD §3.2: "`approved_state_codes` lists the two-letter state codes whose regulator
    accepts the course; it defaults to an empty list, and an empty list means the course is
    accepted in **every** state rather than in none."
    PRD §3.2: "`successive_year_blocked` defaults to true and, when true, means the same
    `course_code` may not be applied in two consecutive attributed years for one originator —
    the NMLS successive-years rule."
    PRD §3.2: "A new course starts with `provider_status` `APPROVED`."

    Design: Corner/entities/ce_course_omitted_flags_default_to_all_states_and_successive_block
    """
    response = api.create_ce_course(
        {"course_code": "CE-DEF-4H", "credit_hours": 4, "category": "ELECTIVE"},
        analyst_headers(),
    )
    course = validate_success(response, 201)

    assert_ce_course(course)
    assert course["approved_state_codes"] == []
    assert course["successive_year_blocked"] is True
    assert course["provider_status"] == "APPROVED"
    assert course["credit_hours"] == 4
    assert course["category"] == "ELECTIVE"
    assert course["course_code"] == "CE-DEF-4H"


def test_loan_close_computes_closed_unit_index_and_pins_plan_id(api):
    """PRD §3.4: "A successfully taken application stamps `application_taken_at` from the
    logical clock — this is the instant the authority window check was evaluated against, and
    it is recorded so that a later examination can reconstruct the decision — and initialises
    `status` to `TAKEN`, `compensation_status` to `NOT_APPLICABLE` and `authority_flag` to
    `VERIFIED`."
    PRD §3.5: "The loan pins its `compensation_plan_id` from the originator's current
    `compensation_plan_id`, freezing the plan that governs this file even if the originator is
    reassigned later."
    PRD §3.5: "It also receives its `closed_unit_index`: the one-based chronological ordinal of
    this loan among the originator's closed loans, computed as one plus the count of that
    originator's loans already sitting in `status` `CLOSED` or `PAID_OFF`, with the ordering
    taken by `funded_at` ascending and then `created_at` ascending."
    PRD §3.5: "This ordinal is null until the loan closes and is the unit count the provisional
    commission tier reads."
    PRD §3.5: "Every provisional line is created with `variant` `PROVISIONAL` and `status`
    `ACCRUED`, and it copies the loan's `loan_application_id`, the originator's `originator_id`
    and the pinned `compensation_plan_id` onto itself; none of those three is client-supplied."

    Design: Corner/entities/loan_close_computes_closed_unit_index_and_pins_plan_id
    """
    context = fixtures.setup_originator_with_plan(
        api,
        plan_overrides={
            "base_basis_points": 105,
            "min_fee_cents": 0,
            "max_fee_cents": 5_000_000,
            "volume_tier_enabled": False,
            "concession_absorption_enabled": False,
        },
    )
    originator_id = context["originator"]["id"]
    plan_id = context["plan"]["id"]

    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    loan = fixtures.take_loan(
        api, originator_id, state_code="CA", requested_amount_cents=20_000_000, par_rate_bps=650
    )
    assert_loan_application(loan)
    assert _instant(loan["application_taken_at"]) == _instant("2026-08-05T00:00:00Z"), (
        "application_taken_at is stamped from the logical clock: "
        f"{loan['application_taken_at']}"
    )
    assert loan["closed_unit_index"] is None, "closed_unit_index stays null until the loan closes"
    assert loan["compensation_plan_id"] is None, "the plan is pinned only at close"

    fixtures.lock_loan(api, loan["id"], originator_id, note_rate_bps=650, locked_amount_cents=20_000_000)
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    closed = fixtures.close_loan(
        api,
        loan["id"],
        funded_amount_cents=20_000_000,
        funded_at="2026-08-20T00:00:00Z",
        lender_paid_comp_cents=210_000,
        borrower_paid_comp_cents=0,
        file_quality_score=95,
        hours_worked_pct=80,
    )

    assert_loan_application(closed)
    assert closed["status"] == "CLOSED"
    assert closed["compensation_status"] == "ACCRUED"
    assert closed["closed_unit_index"] == 1, (
        f"the originator's first closed loan is unit one: {closed['closed_unit_index']}"
    )
    assert closed["compensation_plan_id"] == plan_id
    assert closed["note_rate_bps"] == 650, "note_rate_bps is written by the lock, not by the close"

    record = fixtures.sole_record_for_loan(api, loan["id"])
    assert_compensation_record(record)
    assert record["variant"] == "PROVISIONAL"
    assert record["status"] == "ACCRUED"
    assert record["loan_application_id"] == loan["id"]
    assert record["originator_id"] == originator_id
    assert record["compensation_plan_id"] == plan_id
    assert record["accrued_cents"] == 210_000, (
        f"20000000 cents at 105 basis points is 210000 cents: {record['accrued_cents']}"
    )

"""Validation gates on complaint intake, screening and request plumbing.

Covers the jurisdictional tests a complaint must survive at screening — the
pleaded-loss minimum, the limitation period and the licensure-precedence rule —
together with the two plumbing rules that outrank them: the role check and the
pagination band. Every test drives the API from an empty database.
"""

from test_helpers import (
    LICENSING_ANALYST_HEADERS,
    assert_fields,
    factories as F,
    fixtures as X,
    get_success_data,
    make_consumer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_loss_below_the_jurisdictional_minimum_is_refused_at_screening(api):
    """A pleaded loss under the statutory floor cannot be taken up.

    PRD: "Third the **jurisdictional minimum**: `alleged_loss_cents` must be at
    least 500 dollars — 50,000 cents — and a smaller pleaded loss draws
    `ERR_LOSS_BELOW_JURISDICTIONAL_MINIMUM`."

    Design: Corner/validations/corner_loss_below_the_jurisdictional_minimum_is_rejected_at_screening
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    consumer = X.register_consumer(
        api, full_name="Min Minimum", contact_email="min@home.test"
    )
    complaint = get_success_data(
        api.create_complaint(
            {
                "consumer_id": consumer["id"],
                "subject_business_name": "Pennywise Handyman",
                "alleged_loss_cents": 40000,
                "contract_date": "2026-07-01",
                "description": "Small deposit taken for a job never started.",
            },
            make_consumer_headers(consumer["id"]),
        )
    )

    response = api.screen_complaint(
        complaint["id"], F.screening_payload("ACCEPTED"), LICENSING_ANALYST_HEADERS
    )

    validate_error(response, "ERR_LOSS_BELOW_JURISDICTIONAL_MINIMUM")
    assert_fields(
        validate_success(api.get_complaint(complaint["id"], LICENSING_ANALYST_HEADERS)),
        {"status": "RECEIVED", "jurisdiction_basis": None},
    )


def test_complaint_outside_the_limitation_period_is_refused_at_screening(api):
    """Work finished more than four years before the clock is time-barred.

    PRD: "First the **statute of limitations**: the clock date must be no later
    than the reference date — the `work_completed_on` when it exists, otherwise
    the `contract_date` — advanced by forty-eight months, which is four years.
    Accepting later draws `ERR_STATUTE_OF_LIMITATIONS_EXPIRED`."

    Design: Corner/validations/corner_complaint_outside_the_statute_of_limitations_is_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    consumer = X.register_consumer(
        api, full_name="Stale Stanley", contact_email="stale@home.test"
    )
    complaint = X.file_unlicensed_complaint(
        api,
        consumer["id"],
        "Long Ago Remodelers",
        alleged_loss_cents=400000,
        contract_date="2022-01-01",
        work_completed_on="2022-01-01",
        description="Kitchen remodel abandoned four years ago.",
    )

    response = api.screen_complaint(
        complaint["id"], F.screening_payload("ACCEPTED"), LICENSING_ANALYST_HEADERS
    )

    validate_error(response, "ERR_STATUTE_OF_LIMITATIONS_EXPIRED")
    assert_fields(
        validate_success(api.get_complaint(complaint["id"], LICENSING_ANALYST_HEADERS)),
        {"status": "RECEIVED", "jurisdiction_basis": None},
    )


def test_contract_predating_licensure_is_refused_at_screening(api):
    """Conduct contracted before the licence issued is outside jurisdiction.

    PRD: "Second, and only when the complaint names a licence, the **licensure
    precedence** test: the `contract_date` must be on or after that licence's
    `issued_on`, because conduct predating licensure is outside the board's
    jurisdiction over the licensee; a contract signed before the licence issued
    draws `ERR_CONTRACT_PREDATES_LICENSE`."

    Design: Corner/validations/corner_contract_predating_licensure_is_rejected_at_screening
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    classification = X.create_c10_classification(api)
    ctx = X.mint_active_license(
        api,
        classification,
        legal_name="Early Contract Electric LLC",
        contact_email="early@x.test",
        full_name="Ellis Early",
        verified_experience_months=60,
        education_credential="NONE",
        declared_net_worth_cents=400000,
    )
    consumer = X.register_consumer(
        api, full_name="Pete Predate", contact_email="pete@home.test"
    )
    complaint = X.file_complaint(
        api,
        consumer["id"],
        ctx.license_id,
        alleged_loss_cents=400000,
        contract_date="2026-07-01",
        work_completed_on="2026-07-20",
        description="Service upgrade contracted a month before the licence issued.",
    )

    response = api.screen_complaint(
        complaint["id"], F.screening_payload("ACCEPTED"), LICENSING_ANALYST_HEADERS
    )

    validate_error(response, "ERR_CONTRACT_PREDATES_LICENSE")
    assert_fields(
        validate_success(api.get_complaint(complaint["id"], LICENSING_ANALYST_HEADERS)),
        {"status": "RECEIVED"},
    )
    assert_fields(X.read_license(api, ctx.license_id), {"issued_on": "2026-08-01"})


def test_role_refusal_outranks_the_complaint_state_refusal(api):
    """A consumer screening an already-screened complaint is refused on role.

    The complaint has left `RECEIVED`, so a permitted actor would be refused on
    state; because the role check sits in the earlier band, the role refusal is
    the one reported.

    PRD: "The bands, in ascending order of evaluation, are: request plumbing
    (authentication, role, schema, existence, ownership, pagination), then
    optimistic concurrency, then state, then business safety, then business
    referential integrity, then business temporal windows, then business
    constraints, and finally business fiscal rules."

    Design: Corner/validations/corner_role_check_at_priority_two_outranks_the_state_check_at_twenty
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    consumer = X.register_consumer(
        api, full_name="Pria Priority", contact_email="pria@home.test"
    )
    complaint = get_success_data(
        api.create_complaint(
            {
                "consumer_id": consumer["id"],
                "subject_business_name": "Backyard Builders",
                "alleged_loss_cents": 400000,
                "contract_date": "2026-07-01",
                "description": "Deck framing left unfinished and unpermitted.",
            },
            make_consumer_headers(consumer["id"]),
        )
    )
    screened = X.screen_accepted(api, complaint["id"])
    assert_fields(screened, {"status": "INVESTIGATION"})

    response = api.screen_complaint(
        complaint["id"],
        F.screening_payload("ACCEPTED"),
        make_consumer_headers(consumer["id"]),
    )

    validate_error(response, "ERR_ROLE_NOT_PERMITTED")
    assert_fields(
        validate_success(api.get_complaint(complaint["id"], LICENSING_ANALYST_HEADERS)),
        {"status": "INVESTIGATION"},
    )


def test_pagination_limit_above_the_maximum_is_refused(api):
    """A page size one past the top of the band is refused.

    PRD: "A `limit` outside the one-to-one-hundred band, a negative `offset`, or
    a non-integer value for either is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/corner_pagination_limit_above_the_maximum_is_rejected
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    consumer = X.register_consumer(
        api, full_name="Page Pager", contact_email="page@home.test"
    )
    X.file_unlicensed_complaint(
        api,
        consumer["id"],
        "Overpage Contracting",
        alleged_loss_cents=400000,
        contract_date="2026-07-01",
        work_completed_on="2026-07-20",
        description="Framing crew never returned after the first payment.",
    )

    response = api.list_complaints(LICENSING_ANALYST_HEADERS, {"limit": 101, "offset": 0})

    validate_error(response, "ERR_INVALID_REQUEST")
    _, meta = validate_paginated(
        api.list_complaints(LICENSING_ANALYST_HEADERS, {"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1

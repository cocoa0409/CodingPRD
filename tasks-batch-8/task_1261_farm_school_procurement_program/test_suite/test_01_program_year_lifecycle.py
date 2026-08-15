"""Program year lifecycle: creation defaults, state guards, close gate, clock."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_program_year,
    create_claim,
    create_forecast_line,
    create_program_year,
    create_product,
    create_approved_farm,
    create_offering,
    make_farm_manager_headers,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_claims_coordinator_headers

ADMIN = TEST_USERS["admin_headers"]
CLAIMS = TEST_USERS["claims_headers"]


def test_program_year_create_applies_defaults(api):
    """PRD section 3.1: "The `preference_model` field selects how geographic
    preference points are scored and takes one of the exact values `LINEAR` or
    `TIERED`, defaulting to `LINEAR` when omitted."
    PRD section 3.1: "A new program year is born `DRAFT` with
    `grant_drawn_cents` at zero."
    PRD section 3.1: "and `grant_remaining_cents` is always the award minus the
    drawn amount."

    Design: Corner/entities/ent_program_year_create_defaults
    """
    resp = api.create_program_year(
        {
            "school_year_label": "Y1",
            "start_date": "2026-07-01",
            "end_date": "2027-06-24",
            "local_radius_miles": 100,
            "grant_award_cents": 1000000,
            "local_spend_target_pct": 30,
        },
        ADMIN,
    )
    year = validate_success(resp, 201)
    assert_program_year(year)
    assert year["preference_model"] == "LINEAR", (
        f"omitted preference_model must default to LINEAR, got {year['preference_model']}"
    )
    assert year["grant_drawn_cents"] == 0
    assert year["grant_remaining_cents"] == 1000000
    assert year["status"] == "DRAFT"


def test_program_year_state_family_errors(api):
    """PRD section 3.1: "Opening the year — a `DRAFT` → `OPEN` transition that
    fails with `ERR_PROGRAM_YEAR_NOT_DRAFT` unless the year is `DRAFT` — unlocks
    child creation: offerings, forecast lines, planting agreements,
    reimbursement claims, and substitution requests may only be created while
    the year is `OPEN`, and attempts against a year in any other state are
    rejected with `ERR_PROGRAM_YEAR_NOT_OPEN`."
    PRD section 3.1: "Closing the year requires it to stand in `OPEN` — any
    other state draws `ERR_PROGRAM_YEAR_NOT_OPEN` — and moves it to `CLOSED`,
    the terminal state; closure is also refused with `ERR_CLAIMS_UNRESOLVED`
    while any of the year's reimbursement claims remain `OPEN`, `SUBMITTED`,
    or `UNDER_REVIEW`."

    Design: Corner/state_machines/sm_year_state_family_errors
    """
    year = create_program_year(open_it=False)
    product = create_product()
    farm = create_approved_farm()

    # Child creation against a DRAFT year.
    resp = create_offering(farm["id"], year["id"], product["id"])
    validate_error(resp, ApiErrorId.ERR_PROGRAM_YEAR_NOT_OPEN)

    # First open succeeds; second open fails.
    validate_success(api.open_program_year(year["id"], ADMIN), 200)
    resp = api.open_program_year(year["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_YEAR_NOT_DRAFT)

    # First close succeeds; second close fails (CLOSED is not OPEN).
    validate_success(api.close_program_year(year["id"], ADMIN), 200)
    resp = api.close_program_year(year["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_YEAR_NOT_OPEN)


def test_year_close_blocked_by_unresolved_claim(api):
    """PRD section 3.1: "closure is also refused with `ERR_CLAIMS_UNRESOLVED`
    while any of the year's reimbursement claims remain `OPEN`, `SUBMITTED`,
    or `UNDER_REVIEW`."

    Design: Corner/state_machines/sm_year_close_blocked_by_open_claim
    """
    year = create_program_year()
    create_claim(year["id"], "2026-08")
    resp = api.close_program_year(year["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLAIMS_UNRESOLVED)
    year_after = validate_success(api.get_program_year(year["id"], ADMIN), 200)
    assert year_after["status"] == "OPEN", (
        f"year must stay OPEN when closure is refused, got {year_after['status']}"
    )


def test_claim_period_outside_year_rejected(api):
    """PRD section 3.7: "the period must overlap the program year, failing
    which creation is rejected with `ERR_PERIOD_OUTSIDE_YEAR`."

    Design: Corner/errors/err_period_outside_year_rejected
    """
    year = create_program_year()
    resp = api.create_claim(
        {"program_year_id": year["id"], "period_month": "2025-01"}, CLAIMS
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_OUTSIDE_YEAR)


def test_clock_regression_rejected(api):
    """PRD section 2.8: "the clock is monotonic, and an attempt to move it to
    an earlier instant is rejected with `ERR_CLOCK_REGRESSION`."

    Design: Corner/validations/val_clock_regression_rejected
    """
    advance_clock("2026-08-05T00:00:00Z")
    resp = set_clock("2026-07-01T00:00:00Z")
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)

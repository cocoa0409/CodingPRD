"""Substitutions for uncovered demand and forecast-line uniqueness."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_forecast_line,
    assert_substitution_request,
    create_forecast_line,
    create_product,
    create_program_year,
    create_substitution_request_payload,
    setup_procurement_chain,
    sign_agreement,
    create_agreement,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _open_year_with_gap(planned=1000, week=6):
    """OPEN year + two products + a forecast line with uncovered demand."""
    year = create_program_year()
    product = create_product(name="Tomato")
    substitute = create_product(
        name="Apple", unit="CASE", season_start_week=30, season_end_week=45
    )
    line = create_forecast_line(
        year["id"], product["id"], week_number=week, planned_quantity=planned
    )
    return year, product, substitute, line


def test_substitution_same_product_rejected(api):
    """PRD section 3.8: "a `substitute_product_id` that must differ from the
    line's own product (`ERR_SAME_PRODUCT_SUBSTITUTION`)"

    Design: Corner/validations/val_substitution_same_product_rejected
    """
    _year, product, _substitute, line = _open_year_with_gap(planned=100)
    resp = api.create_substitution_request(
        {
            "forecast_line_id": line["id"],
            "substitute_product_id": product["id"],
            "quantity": 10,
            "reason": "SUPPLY_SHORTFALL",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_SAME_PRODUCT_SUBSTITUTION)


def test_substitution_exceeds_gap_boundary(api):
    """PRD section 3.8: "a `quantity` of at least 1 that may not exceed the
    line's `uncovered_quantity` (`ERR_SUBSTITUTION_EXCEEDS_GAP`)"

    Design: Corner/validations/val_substitution_exceeds_gap_boundary
    """
    # Planned 400 with a signed 350 commitment leaves an uncovered 50; the
    # product-year cap (floor(20% of 400) = 80) stays above the gap so the
    # gap rule is exercised in isolation.
    chain = setup_procurement_chain(with_agreement=False)
    substitute = create_product(
        name="Apple", unit="CASE", season_start_week=30, season_end_week=45
    )
    agr = validate_success(
        create_agreement(chain.year["id"], chain.offering["id"], committed_quantity=350),
        201,
    )
    sign_agreement(agr["id"], chain.farm["id"])

    resp = api.create_substitution_request(
        {
            "forecast_line_id": chain.forecast_line["id"],
            "substitute_product_id": substitute["id"],
            "quantity": 60,
            "reason": "SUPPLY_SHORTFALL",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_EXCEEDS_GAP)

    # Exactly the gap is admitted.
    request = validate_success(
        api.create_substitution_request(
            {
                "forecast_line_id": chain.forecast_line["id"],
                "substitute_product_id": substitute["id"],
                "quantity": 50,
                "reason": "SUPPLY_SHORTFALL",
            },
            ADMIN,
        ),
        201,
    )
    assert_substitution_request(request)
    assert request["status"] == "REQUESTED"


def test_substitution_cap_exceeded_at_approval(api):
    """PRD section 3.8: "For the request's product in the request's program
    year, the cap is twenty percent of the total `planned_quantity` across all
    of that product's forecast lines, rounded down to a whole unit. The sum of
    `quantity` over that product and year's already-`APPROVED` requests, plus
    the quantity under consideration, may not exceed the cap — and a request
    landing exactly on the cap is permitted. The cap is enforced when the
    request is created and checked again at approval time, since intervening
    approvals may have consumed the remaining room; a breach at either point is
    rejected with `ERR_SUBSTITUTION_CAP_EXCEEDED`."

    Design: Corner/errors/err_substitution_cap_exceeded_at_approval
    """
    _year, _product, substitute, line = _open_year_with_gap(planned=1000)
    r1 = validate_success(
        api.create_substitution_request(
            {
                "forecast_line_id": line["id"],
                "substitute_product_id": substitute["id"],
                "quantity": 200,
                "reason": "SEASONALITY_GAP",
            },
            ADMIN,
        ),
        201,
    )
    r2 = validate_success(
        api.create_substitution_request(
            {
                "forecast_line_id": line["id"],
                "substitute_product_id": substitute["id"],
                "quantity": 1,
                "reason": "SEASONALITY_GAP",
            },
            ADMIN,
        ),
        201,
    )

    # The cap is floor(0.20 * 1000) = 200: the first request lands exactly on
    # it and is permitted.
    approved = validate_success(api.approve_substitution_request(r1["id"], AUDITOR), 200)
    assert approved["status"] == "APPROVED"

    # The second request now exceeds the cap at approval time.
    resp = api.approve_substitution_request(r2["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_CAP_EXCEEDED)


def test_substitution_terminal_lockdown(api):
    """PRD section 3.8: "A `StateGrantAuditor` approves or denies a request
    standing in `REQUESTED` (any other state draws
    `ERR_SUBSTITUTION_NOT_PENDING`); both `APPROVED` and `DENIED` are
    terminal."

    Design: Corner/state_machines/sm_substitution_terminal_error
    """
    _year, _product, substitute, line = _open_year_with_gap(planned=1000)
    request = validate_success(
        api.create_substitution_request(
            {
                "forecast_line_id": line["id"],
                "substitute_product_id": substitute["id"],
                "quantity": 10,
                "reason": "SEASONALITY_GAP",
            },
            ADMIN,
        ),
        201,
    )
    validate_success(api.approve_substitution_request(request["id"], AUDITOR), 200)
    resp = api.approve_substitution_request(request["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_NOT_PENDING)


def test_substitution_zero_gap_boundary(api):
    """PRD section 3.8: "A line with no gap at all — an `uncovered_quantity`
    of zero — cannot anchor a request (`ERR_NO_SEASONALITY_GAP`)."
    PRD section 3.4: "the `uncovered_quantity` is the planned quantity minus
    the reserved quantity, floored at zero, so a fully reserved line reports
    an uncovered quantity of exactly zero."

    Design: Difficulty/boundary_precision_check/substitution_zero_gap_boundary
    """
    chain = setup_procurement_chain(with_agreement=False)
    substitute = create_product(
        name="Apple", unit="CASE", season_start_week=30, season_end_week=45
    )
    # Committed exactly equal to the planned 400: the boundary is inclusive.
    agr = validate_success(
        create_agreement(chain.year["id"], chain.offering["id"], committed_quantity=400),
        201,
    )
    sign_agreement(agr["id"], chain.farm["id"])

    line = validate_success(api.get_forecast_line(chain.forecast_line["id"], ADMIN), 200)
    assert line["reserved_quantity"] == 400
    assert line["uncovered_quantity"] == 0

    resp = api.create_substitution_request(
        {
            "forecast_line_id": chain.forecast_line["id"],
            "substitute_product_id": substitute["id"],
            "quantity": 1,
            "reason": "SEASONALITY_GAP",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NO_SEASONALITY_GAP)


def test_substitution_zero_gap_boundary_equality_is_covered(api):
    """PRD section 3.4: "the `uncovered_quantity` is the planned quantity minus
    the reserved quantity, floored at zero, so a fully reserved line reports
    an uncovered quantity of exactly zero."
    PRD section 3.8: "A line with no gap at all — an `uncovered_quantity`
    of zero — cannot anchor a request (`ERR_NO_SEASONALITY_GAP`)."

    Design: Difficulty/boundary_precision_check/substitution_zero_gap_boundary
    """
    chain = setup_procurement_chain(with_agreement=False)
    substitute = create_product(
        name="Apple", unit="CASE", season_start_week=30, season_end_week=45
    )

    # Just below full coverage a gap remains and a request is admitted.
    agr = validate_success(
        create_agreement(chain.year["id"], chain.offering["id"], committed_quantity=399),
        201,
    )
    sign_agreement(agr["id"], chain.farm["id"])
    line = validate_success(api.get_forecast_line(chain.forecast_line["id"], ADMIN), 200)
    assert line["reserved_quantity"] == 399
    assert line["uncovered_quantity"] == 1
    request = validate_success(
        api.create_substitution_request(
            {
                "forecast_line_id": chain.forecast_line["id"],
                "substitute_product_id": substitute["id"],
                "quantity": 1,
                "reason": "SEASONALITY_GAP",
            },
            ADMIN,
        ),
        201,
    )
    assert request["status"] == "REQUESTED"

    # One more committed unit closes the gap entirely; now even quantity 1 is
    # refused.
    chain2 = setup_procurement_chain(with_agreement=False)
    agr2 = validate_success(
        create_agreement(
            chain2.year["id"], chain2.offering["id"], committed_quantity=400
        ),
        201,
    )
    sign_agreement(agr2["id"], chain2.farm["id"])
    resp = api.create_substitution_request(
        {
            "forecast_line_id": chain2.forecast_line["id"],
            "substitute_product_id": substitute["id"],
            "quantity": 1,
            "reason": "SEASONALITY_GAP",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NO_SEASONALITY_GAP)


def test_duplicate_forecast_line(api):
    """PRD section 3.4: "The triple of year, product, and week is unique: a
    second line for the same combination is rejected with
    `ERR_FORECAST_LINE_EXISTS`."

    Design: Corner/validations/val_duplicate_forecast_line
    """
    year = create_program_year()
    product = create_product()
    create_forecast_line(year["id"], product["id"], week_number=6, planned_quantity=400)
    resp = api.create_forecast_line(
        {
            "program_year_id": year["id"],
            "product_id": product["id"],
            "week_number": 6,
            "planned_quantity": 100,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_FORECAST_LINE_EXISTS)

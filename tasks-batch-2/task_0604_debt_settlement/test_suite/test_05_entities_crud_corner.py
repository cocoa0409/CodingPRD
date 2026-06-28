"""Corner-queue tests: entity creation, defaults, required/type constraints,
not-found, system-field protection, and duplicate account numbers."""
import pytest
from test_helpers import (
    ApiErrorId, TEST_USERS, validate_success, validate_error, get_success_data,
    create_client_payload, create_program_payload, create_debt_payload,
    create_offer_payload,
    set_clock, create_client, create_program, create_debt,
)

ADMIN = TEST_USERS["program_admin_headers"]
AGENT = TEST_USERS["negotiation_agent_headers"]


def test_create_program_defaults_and_zeroed_aggregates(api):
    """PRD §3.1: "A newly enrolled program enters lifecycle phase `ENROLLING` with
    `account_standing` of `CURRENT`, all computed aggregates initialized to zero"
    PRD §3.1: "target_settlement_pct` (the forward-looking assumed settlement fraction used by the savings estimate, defaulting to 0.50, ...), and `reserve_floor` (the protective account minimum, defaulting to 0)."
    PRD §3.1: "`deposit_day_of_month` (the day the recurring deposit is due, defaulting to 1)"

    Design: Corner/entities/create_program_returns_201_with_defaults_and_zeroed_aggregates
    """
    client = create_client(full_name="New Client", email="nc@x.com", state_code="CA")
    res = api.create_program(create_program_payload(client["id"], monthly_deposit_amount=600),
                            ADMIN)
    prog = validate_success(res, 201)
    assert prog["program_phase"] == "ENROLLING"
    assert prog["account_standing"] == "CURRENT"
    assert prog["target_settlement_pct"] == pytest.approx(0.50, abs=0.0001)
    assert prog["deposit_day_of_month"] == 1
    assert prog["total_enrolled_balance"] == pytest.approx(0, abs=0.01)
    assert prog["estimated_total_savings"] == pytest.approx(0, abs=0.01)
    assert prog["realized_total_savings"] == pytest.approx(0, abs=0.01)


def test_create_program_missing_monthly_deposit_amount_invalid_request(api):
    """PRD §2.6: "Any malformed body, missing required field, invalid enum, or out-of-range number is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "The administrator then enrolls a `Program` for that client by referencing the `client_id` and supplying the recurring `monthly_deposit_amount`."

    Design: Corner/entities/create_program_missing_monthly_deposit_amount_returns_invalid_request
    """
    client = create_client(full_name="C", email="c@x.com", state_code="CA")
    res = api.create_program({"client_id": client["id"]}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_offer_offer_pct_out_of_range_invalid_request(api):
    """PRD §2.6: "An offer's `offer_pct` and a program's `target_settlement_pct` must each be greater than zero and at most one."
    PRD §2.6: "Any malformed body, missing required field, invalid enum, or out-of-range number is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_offer_invalid_offer_pct_out_of_range_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c2@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    debt = create_debt(program["id"], creditor_name="Cred", account_number="X-1",
                      original_balance=5000)
    get_success_data(api.activate_program(program["id"], ADMIN))
    res = api.create_offer(
        create_offer_payload(program["id"], debt["id"], offer_pct=1.5,
                            due_date="2026-12-01T00:00:00Z"), AGENT)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_program_nonexistent_not_found(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any later reference or business rule is evaluated."

    Design: Corner/entities/get_program_nonexistent_returns_not_found
    """
    res = api.get_program("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_debt_fee_rate_and_status_are_server_set(api):
    """PRD §3.2: "A new debt enters status `ENROLLED`."
    PRD §3.2: "From the resulting total it selects the band: a total below 10,000 dollars yields a rate of 0.25; ... That selected band is frozen onto the new debt as its `fee_rate_pct`."

    Design: Corner/entities/debt_system_fields_ignore_client_input_for_fee_rate_and_status
    """
    client = create_client(full_name="C", email="c3@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    res = api.create_debt(
        create_debt_payload(program["id"], creditor_name="Cred",
                           account_number="SYS-1", original_balance=5000), ADMIN)
    debt = validate_success(res, 201)
    # total 5000 < 10000 -> 0.25
    assert debt["fee_rate_pct"] == pytest.approx(0.25, abs=0.0001)
    assert debt["status"] == "ENROLLED"


def test_duplicate_account_number_conflict(api):
    """PRD §3.2: "The `account_number` must be unique within its program; a duplicate is rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER` (HTTP 409)."

    Design: Corner/entities/duplicate_account_number_within_program_returns_conflict
    """
    client = create_client(full_name="C", email="c4@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    create_debt(program["id"], creditor_name="Cred", account_number="DUP-1",
               original_balance=5000)
    res = api.create_debt(
        create_debt_payload(program["id"], creditor_name="Cred2",
                           account_number="DUP-1", original_balance=3000), ADMIN)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ACCOUNT_NUMBER)

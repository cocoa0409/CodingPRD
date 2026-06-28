"""Corner-queue tests: offer-quote correctness, fee-tier top band, non-`reportable`
tax events, and validation violations (expired offer, insufficient reserve, ownership)."""
import pytest
from test_helpers import (
    ApiErrorId, TEST_USERS, make_client_headers, validate_success, validate_error,
    get_success_data, create_offer_payload, create_settlement_payload,
    create_deposit_payload,
    set_clock, create_client, create_program, create_debt, create_offer, accept_offer,
)

ADMIN = TEST_USERS["program_admin_headers"]
AGENT = TEST_USERS["negotiation_agent_headers"]


def test_standard_offer_quote_no_surcharge(api):
    """PRD §3.5: "The `settlement_amount` is the principal that would be paid: the debt's `current_balance` multiplied by `offer_pct`, rounded half-up to two decimal places. The `projected_fee` is then computed on that rounded principal: `settlement_amount` multiplied by the effective fee rate, again rounded half-up to two decimal places."
    PRD §3.5: "for an `ENROLLED` or `IN_NEGOTIATION` debt no surcharge applies and the effective rate is exactly the frozen rate."

    Design: Corner/calculations/standard_offer_quote_no_surcharge_correct
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c11@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    debt = create_debt(program["id"], creditor_name="Cred", account_number="SQ-1",
                      original_balance=5000)
    get_success_data(api.activate_program(program["id"], ADMIN))
    offer = get_success_data(api.create_offer(
        create_offer_payload(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z"), AGENT))
    assert offer["settlement_amount"] == pytest.approx(2000.00, abs=0.01)
    assert offer["projected_fee"] == pytest.approx(500.00, abs=0.01)


def test_fee_tier_top_band_at_30000(api):
    """PRD §3.2: "a total of 30,000 dollars or more yields 0.18. That selected band is frozen onto the new debt as its `fee_rate_pct`."

    Design: Corner/calculations/fee_tier_top_band_at_30000
    """
    client = create_client(full_name="C", email="c12@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    res = api.create_debt(
        {"program_id": program["id"], "creditor_name": "Cred",
         "account_number": "TB-1", "original_balance": 30000}, ADMIN)
    debt = validate_success(res, 201)
    assert debt["fee_rate_pct"] == pytest.approx(0.18, abs=0.0001)


def test_tax_event_non_reportable_below_floor(api):
    """PRD §3.7: "A `TaxEvent` is always issued whenever the forgiven amount is greater than zero."
    PRD §3.7: "a `reportable` flag that is true when the forgiven amount is at least 600 dollars (the IRS 1099-C reporting threshold) and false when it is greater than zero but below 600."

    Design: Corner/calculations/tax_1099c_non_reportable_below_floor
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c13@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
    debt = create_debt(program["id"], creditor_name="Cred", account_number="NR-1",
                      original_balance=1000)
    activated = get_success_data(api.activate_program(program["id"], ADMIN))
    v1 = activated["version"]
    for m in (4, 5):
        api.create_deposit(
            {"program_id": program["id"], "scheduled_for": f"2026-{m:02d}-10T00:00:00Z",
             "amount": 600}, make_client_headers(client["id"]))
    offer = create_offer(program["id"], debt["id"], offer_pct=0.41,
                        due_date="2026-12-01T00:00:00Z")
    accept_offer(offer["id"], v1)
    settle = get_success_data(api.create_settlement(
        create_settlement_payload(program["id"], offer["id"]), AGENT))
    get_success_data(api.complete_settlement(settle["id"], AGENT))
    tes = get_success_data(api.list_tax_events(
        ADMIN, params={"source_settlement_id": settle["id"]}))
    # 1000 - 410 = 590
    assert tes[0]["forgiven_amount"] == pytest.approx(590.00, abs=0.01)
    assert tes[0]["reportable"] is False


def test_create_offer_past_due_date_returns_offer_expired(api):
    """PRD §3.5: "An offer's `due_date` must lie strictly after the current logical clock; an offer whose `due_date` is at or before the current time is already expired and cannot be created, drawing `ERR_OFFER_EXPIRED` (HTTP 409)."

    Design: Corner/validations/create_offer_past_due_date_returns_offer_expired
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c14@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    debt = create_debt(program["id"], creditor_name="Cred", account_number="EX-1",
                      original_balance=5000)
    get_success_data(api.activate_program(program["id"], ADMIN))
    res = api.create_offer(
        create_offer_payload(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-05-01T00:00:00Z"), AGENT)
    validate_error(res, ApiErrorId.ERR_OFFER_EXPIRED)


def test_fund_settlement_insufficient_reserve(api):
    """PRD §3.7: "Funding is also subject to an instantaneous reserve check: at funding time the account's current `balance` must be at least the sum of `settlement_amount`, `projected_fee`, and `reserve_floor`, and a shortfall is rejected with `ERR_INSUFFICIENT_RESERVE` (HTTP 402)."

    Design: Corner/validations/fund_settlement_insufficient_reserve_returns_insufficient_reserve
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c15@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600,
                             deposit_day_of_month=15, reserve_floor=0)
    debt = create_debt(program["id"], creditor_name="Cred", account_number="IR-1",
                      original_balance=5000)
    activated = get_success_data(api.activate_program(program["id"], ADMIN))
    v1 = activated["version"]
    api.create_deposit(
        {"program_id": program["id"], "scheduled_for": "2026-05-15T00:00:00Z",
         "amount": 600}, make_client_headers(client["id"]))
    offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                        due_date="2026-12-31T00:00:00Z")
    accept_offer(offer["id"], v1)
    # at funding time only 600 on hand; need 2000 + 500
    res = api.create_settlement(create_settlement_payload(program["id"], offer["id"]), AGENT)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_RESERVE)


def test_client_not_owner_deposit_returns_not_program_owner(api):
    """PRD §2.1: "for the two client-exclusive operations — recording a deposit and dropping a program — the acting client must own the target program; if the program's `client_id` does not equal `X-User-ID`, the request is rejected with `ERR_NOT_PROGRAM_OWNER` (HTTP 403)."

    Design: Corner/validations/client_not_owner_deposit_returns_not_program_owner
    """
    client_a = create_client(full_name="Owner A", email="a@x.com", state_code="CA")
    client_b = create_client(full_name="Other B", email="b@x.com", state_code="CA")
    program = create_program(client_a["id"], monthly_deposit_amount=600)
    res = api.create_deposit(
        create_deposit_payload(program["id"], "2026-05-10T00:00:00Z", amount=600),
        make_client_headers(client_b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_PROGRAM_OWNER)

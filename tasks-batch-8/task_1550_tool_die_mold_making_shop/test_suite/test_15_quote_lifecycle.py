"""Quote lifecycle edges: lazy expiry on respond and terminal-state lockdown
(PRD §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_customer,
    create_quote,
    create_released_design,
    get_success_data,
    issue_quote,
    make_customer_headers,
    respond_quote,
    set_clock,
    validate_error,
)

ESTIMATOR = TEST_USERS["estimator_headers"]


def _issued_firm_quote(company_name, part_number):
    customer = create_customer(company_name=company_name)
    design = create_released_design(customer["id"], part_number=part_number)
    quote = create_quote(customer["id"], design["id"], quote_kind="FIRM",
                         requested_lead_weeks=12)
    quote = issue_quote(quote["id"])
    return customer, quote


def test_quote_expiry_lazy_transition_on_respond(api):
    """PRD §3.3: "If the logical clock has passed `valid_until`, the quote
    lazily transitions from `ISSUED` to `EXPIRED` and the response call itself
    fails with `ERR_QUOTE_EXPIRED` — this applies equally to accepts and
    declines."
    PRD §3.3: "Issuance stamps `issued_at` from the logical clock and computes
    `valid_until` as fourteen days after issuance for `BUDGETARY` quotes and
    thirty days for `FIRM` quotes (both remain null while the quote is in
    `DRAFT`)."

    Design: Corner/state_machines/quote_expiry_lazy_transition_on_respond
    """
    customer, quote = _issued_firm_quote("Exp Co", "PN-EX1")
    assert quote["status"] == "ISSUED"
    assert quote["issued_at"].startswith("2026-08-01T00:00:00")
    # FIRM validity is issued_at + 30 days.
    assert quote["valid_until"].startswith("2026-08-31T00:00:00"), (
        f"FIRM validity is issued_at + 30 days, got {quote['valid_until']}"
    )

    # Move the logical clock past valid_until.
    set_clock("2026-09-01T00:00:00Z")

    res = api_client.respond_quote(
        quote["id"], {"decision": "ACCEPTED"}, make_customer_headers(customer["id"]),
    )
    error = validate_error(res, ApiErrorId.ERR_QUOTE_EXPIRED)
    assert error["error_id"] == "ERR_QUOTE_EXPIRED"
    assert res.status_code == 409

    expired = get_success_data(api_client.get_quote(quote["id"], ESTIMATOR))
    assert expired["status"] == "EXPIRED", (
        f"the rejected respond must persist the lazy EXPIRED transition, got "
        f"{expired['status']}"
    )
    assert expired["valid_until"].startswith("2026-08-31T00:00:00")


def test_quote_terminal_lockdown_double_respond_rejected(api):
    """PRD §3.3: "`ACCEPTED`, `DECLINED`, `EXPIRED`, and `SUPERSEDED` are all
    terminal for a quote."
    PRD §2.7: "The target resource must be in the state machine's required
    from-state — otherwise `ERR_INVALID_STATE`, `ERR_JOB_ON_HOLD`, or
    `ERR_JOB_PHASE_MISMATCH` (HTTP 409)."

    Design: Corner/state_machines/quote_terminal_lockdown_double_respond_rejected
    """
    customer, quote = _issued_firm_quote("Term Co", "PN-TM1")
    declined = respond_quote(quote["id"], "DECLINED", customer["id"])
    assert declined["status"] == "DECLINED"

    res = api_client.respond_quote(
        quote["id"], {"decision": "ACCEPTED"}, make_customer_headers(customer["id"]),
    )
    error = validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert error["error_id"] == "ERR_INVALID_STATE"
    assert res.status_code == 409

    after = get_success_data(api_client.get_quote(quote["id"], ESTIMATOR))
    assert after["status"] == "DECLINED", "the first decision stands"

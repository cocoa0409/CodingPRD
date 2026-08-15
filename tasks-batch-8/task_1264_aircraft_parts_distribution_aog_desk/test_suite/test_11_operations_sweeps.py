"""The operations sweep: overdue flips, lease forward-billing, tier recompute,
and balance-driven suspension (PRD §3.9)."""
from test_helpers import (
    validate_success, validate_error,
    create_customer, create_part, create_unit, create_aog_request,
    create_quote, make_quote_line, issue_quote, accept_quote_and_get_order,
    allocate_all_lines, clear_order_compliance, create_shipment_payload,
    create_loan, get_core_return_for_line,
    set_clock, run_sweeps, TEST_USERS,
)

AGENT = TEST_USERS["aog_desk_agent_headers"]
WAREHOUSE = TEST_USERS["warehouse_operator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


def test_core_overdue_and_loan_overdue_sweeps(api):
    """PRD §3.9: "every `ACTIVE` loan past its `due_at` flips to `OVERDUE`,
    incrementing `version`" — and a loan whose due instant has not yet passed
    is untouched.

    Clock 2026-05-10T00:00:01Z: loan 1 (due 2026-05-10T00:00:00Z) is past due;
    loan 2 (due 2026-06-10) is not.

    Design: Corner/state_machines/core_overdue_and_loan_overdue_sweeps
    """
    customer = create_customer(name="SweepAir")
    part = create_part(part_number="PN-SW", rotable=True,
                       list_price_cents=100_000, core_value_cents=40_000)
    u1 = create_unit(part["id"], serial_number="SN-SW1", condition="OVERHAULED")
    u2 = create_unit(part["id"], serial_number="SN-SW2", condition="OVERHAULED")
    ln1 = create_loan(customer["id"], u1["id"], loan_type="LOAN",
                      daily_rate_cents=10_000,
                      start_at="2026-05-01T00:00:00Z",
                      due_at="2026-05-10T00:00:00Z")
    ln2 = create_loan(customer["id"], u2["id"], loan_type="LOAN",
                      daily_rate_cents=10_000,
                      start_at="2026-05-01T00:00:00Z",
                      due_at="2026-06-10T00:00:00Z")

    set_clock("2026-05-10T00:00:01Z")
    result = run_sweeps()
    assert result["overdue_loans"] == 1

    loan1 = validate_success(api.get_loan(ln1["id"], AGENT))
    assert loan1["status"] == "OVERDUE"
    loan2 = validate_success(api.get_loan(ln2["id"], AGENT))
    assert loan2["status"] == "ACTIVE"


def _settle_one_exchange_cycle(api, customer, part, unit, needed_by,
                               receive_clock, serial_suffix):
    """Full exchange cycle ending with the core received on time and inspected
    ACCEPTED (SETTLED). Returns the core return row."""
    aog = create_aog_request(
        customer["id"], part["id"], needed_by_utc=needed_by,
        condition_acceptable=["OVERHAULED"],
    )
    validate_success(api.source_search(aog["id"], AGENT))
    quote = create_quote(
        aog["id"], customer["id"],
        [make_quote_line(part["id"], sale_type="EXCHANGE",
                         unit_price_cents=250_000,
                         condition_required="OVERHAULED")],
    )
    issued = issue_quote(quote["id"])
    ctx = {"customer": customer, "part": part, "aog": aog, "quote": issued}
    accept_quote_and_get_order(ctx)
    allocate_all_lines(ctx, unit_ids=[unit["id"]])
    clear_order_compliance(ctx)
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(ctx["order"]["id"]), WAREHOUSE,
    ), 201)
    validate_success(api.tender_shipment(shipment["id"], {}, WAREHOUSE))
    validate_success(api.deliver_shipment(shipment["id"], WAREHOUSE))
    core = get_core_return_for_line(ctx["lines"][0]["id"])
    set_clock(receive_clock)
    validate_success(api.receive_core_return(
        core["id"], {"core_serial_number": f"SN-TBC{serial_suffix}"}, WAREHOUSE,
    ))
    return validate_success(api.inspect_core_return(
        core["id"], {"verdict": "ACCEPTED"}, WAREHOUSE,
    ))


def test_customer_tier_progression_at_count_boundary(api):
    """PRD §3.9: "A customer with at least two settled returns, an on-time
    rate of at least 0.95, and zero `warranty_fraud_flags` earns `PLATINUM`;
    otherwise at least one settled return, an on-time rate of at least 0.90,
    and zero fraud flags earns `PRIORITY`; everyone else is `STANDARD`."

    After one on-time settle the count boundary (1 < 2) blocks PLATINUM even
    at rate 1.0; the second on-time settle earns PLATINUM.

    Design: Corner/calculations/customer_tier_progression_at_count_boundary
    """
    customer = create_customer(name="TierCo")
    part = create_part(part_number="PN-TB", rotable=True,
                       list_price_cents=250_000, core_value_cents=500_000,
                       warranty_months=24)
    u1 = create_unit(part["id"], serial_number="SN-TB1", condition="OVERHAULED",
                     trace_doc_level="DUAL_RELEASE")
    u2 = create_unit(part["id"], serial_number="SN-TB2", condition="OVERHAULED",
                     trace_doc_level="DUAL_RELEASE")

    core1 = _settle_one_exchange_cycle(
        api, customer, part, u1, "2026-06-01T00:00:00Z",
        "2026-05-10T00:00:00Z", "1",
    )
    assert core1["status"] == "SETTLED"
    run_sweeps()
    cust = validate_success(api.get_customer(customer["id"], FINANCE))
    assert cust["priority_tier"] == "PRIORITY"
    assert cust["core_returns_settled_180d"] == 1

    core2 = _settle_one_exchange_cycle(
        api, customer, part, u2, "2026-07-01T00:00:00Z",
        "2026-05-15T00:00:00Z", "2",
    )
    assert core2["status"] == "SETTLED"
    run_sweeps()
    cust = validate_success(api.get_customer(customer["id"], FINANCE))
    assert cust["priority_tier"] == "PLATINUM"
    assert cust["core_returns_settled_180d"] == 2
    assert cust["core_returns_on_time_180d"] == 2


class TestLeaseSweepSuspensionCascade:
    def _setup(self, api):
        customer = create_customer(name="LeaseCo", credit_limit_cents=1_200_000)
        part = create_part(part_number="PN-LEASE", rotable=True,
                           list_price_cents=900_000, core_value_cents=200_000)
        unit = create_unit(part["id"], serial_number="SN-LE1",
                           condition="OVERHAULED")
        loan = create_loan(customer["id"], unit["id"], loan_type="LEASE",
                           daily_rate_cents=25_000, lease_periods=2,
                           start_at="2026-05-01T00:00:00Z",
                           due_at="2026-06-30T00:00:00Z")
        set_clock("2026-06-01T00:00:00Z")
        # A quotable request + DRAFT quote created while we can still observe
        # the downstream effect of the sweep-driven suspension.
        part2 = create_part(part_number="PN-X", list_price_cents=1_000)
        aog = create_aog_request(customer["id"], part2["id"],
                                 aircraft_tail="N800LC", airport_code="ATL",
                                 min_trace_doc="TRACE_MISSING",
                                 needed_by_utc="2026-07-01T00:00:00Z")
        quote = create_quote(aog["id"], customer["id"],
                             [make_quote_line(part2["id"],
                                              unit_price_cents=1_000)])
        return customer, loan, quote

    def test_lease_boundary_debit_then_suspension(self, api):
        """PRD §3.9: "for each lease, a period debit of 30 days times the
        daily rate posts for every 30-day boundary crossed since the last
        posting" and "The same step suspends any customer whose outstanding
        balance is strictly greater than their credit limit".

        750000 posted at activation plus one 750000 period debit at the
        2026-05-31 boundary -> balance 1500000 > limit 1200000 -> SUSPENDED.

        Design: Difficulty/transitive_cascade/lease_sweep_suspension_cascade
        """
        customer, loan, _ = self._setup(api)
        result = run_sweeps()
        assert result["lease_debits_posted"] == 1
        assert result["customers_suspended"] == 1

        cust = validate_success(api.get_customer(customer["id"], FINANCE))
        assert cust["outstanding_balance_cents"] == 1_500_000
        assert cust["status"] == "SUSPENDED"

        loan_after = validate_success(api.get_loan(loan["id"], AGENT))
        assert loan_after["status"] == "ACTIVE", (
            "due 2026-06-30 not yet reached at clock 2026-06-01"
        )

    def test_suspension_gates_quote_issue(self, api):
        """PRD §3.4: "Issuing requires the customer to be `ACTIVE`
        (`ERR_CUSTOMER_SUSPENDED` otherwise)"; PRD §3.1: "A `SUSPENDED`
        customer cannot have a quote issued or accepted on its behalf, and
        cannot take out a new loan; any of those attempts is rejected with
        `ERR_CUSTOMER_SUSPENDED`."

        Design: Difficulty/transitive_cascade/lease_sweep_suspension_cascade
        """
        _, _, quote = self._setup(api)
        run_sweeps()
        res = api.issue_quote(quote["id"], AGENT)
        validate_error(res, "ERR_CUSTOMER_SUSPENDED", expected_status=409)

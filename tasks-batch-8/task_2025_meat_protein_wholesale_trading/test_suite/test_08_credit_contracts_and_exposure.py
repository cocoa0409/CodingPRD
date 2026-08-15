"""Credit exposure boundaries, forward-contract lifecycle and earmark
validation, contract OCC, and the net hedging exposure report."""
from test_helpers import (
    WEEK_1,
    WEEK_2,
    ApiErrorId,
    add_sheet_line,
    amend_forward_contract_payload,
    api_client,
    assert_exposure_report,
    book_po,
    create_allocation_payload,
    create_customer,
    create_forward_contract,
    create_forward_contract_payload,
    create_product,
    create_sheet,
    get_allocation,
    get_contract,
    get_customer,
    get_po,
    make_customer_rep_headers,
    post_offer,
    accept_claim,
    publish_sheet,
    receive_po,
    request_allocation,
    run_sheet,
    set_clock,
    setup_confirmed_allocation,
    setup_filed_claim,
    validate_error,
    validate_success,
)


class TestCreditExactEqualityBoundary:
    def test_exposure_equal_to_limit_stays_active_over_limit_holds(self):
        """PRD §2.10: "The comparison is strict. An `ACTIVE` customer whose
        exposure rises strictly above the limit transitions to `CREDIT_HOLD`;
        a customer on `CREDIT_HOLD` whose exposure falls to the limit or below
        transitions back to `ACTIVE`."

        Design: Difficulty/boundary_precision_check/credit_exact_equality_boundary
        """
        product = create_product(product_code="RIBEYE-H", max_fat_pct=12.0)
        c1 = create_customer(customer_code="CEQ-1", credit_limit_cents=350_000)
        c2 = create_customer(customer_code="CEQ-2", credit_limit_cents=349_999)
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 100_000)
        publish_sheet(sheet["id"])
        a1 = request_allocation(c1, line["id"], 500)
        a2 = request_allocation(c2, line["id"], 500)

        run_sheet(sheet["id"])

        a1_after = get_allocation(a1["id"])
        assert a1_after["status"] == "CONFIRMED"
        assert a1_after["allocated_lbs"] == 500
        c1_after = get_customer(c1["id"])
        assert c1_after["outstanding_exposure_cents"] == 350_000
        assert c1_after["status"] == "ACTIVE", \
            "exposure exactly equal to the limit does not trigger the hold"

        a2_after = get_allocation(a2["id"])
        assert a2_after["status"] == "CONFIRMED"
        assert a2_after["allocated_lbs"] == 500
        c2_after = get_customer(c2["id"])
        assert c2_after["outstanding_exposure_cents"] == 350_000
        assert c2_after["status"] == "CREDIT_HOLD", \
            "exposure one cent above the limit forces the hold"

    def test_release_to_exactly_the_limit_reactivates_customer(self):
        """PRD §2.10: "a customer on `CREDIT_HOLD` whose exposure falls to the
        limit or below transitions back to `ACTIVE`."
        PRD §3.8: "the base settlement is the smaller of `current_offer_cents`
        and the liability cap"

        Design: Difficulty/boundary_precision_check/credit_exact_equality_boundary
        """
        # Exposure 350000 against a 200000 limit -> CREDIT_HOLD; settling a
        # 150000-cent claim brings exposure to exactly the limit -> ACTIVE.
        ctx = setup_filed_claim(credit_limit_cents=200_000,
                                claimed_amount_cents=200_000,
                                claim_type="QUALITY_DEFECT")
        customer = ctx["customer"]
        assert get_customer(customer["id"])["status"] == "CREDIT_HOLD"

        claim = ctx["claim"]
        post_offer(claim["id"], 150_000, claim["version"])
        accepted = accept_claim(claim["id"], customer)
        assert accepted["final_settlement_cents"] == 150_000

        after = get_customer(customer["id"])
        assert after["outstanding_exposure_cents"] == 200_000, (
            f"350000 - 150000 lands exactly on the limit, got "
            f"{after['outstanding_exposure_cents']}"
        )
        assert after["status"] == "ACTIVE", \
            "falling to exactly the limit releases the hold"


class TestCreditHoldGate:
    def test_credit_hold_blocks_new_allocation_returns_402(self):
        """PRD §3.6: "the customer must be `ACTIVE`: a customer on
        `CREDIT_HOLD` may not request allocations and is turned away with
        `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402)."

        Design: Corner/validations/credit_hold_blocks_new_allocation_returns_402
        """
        product = create_product(product_code="RIBEYE-CH", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-CH",
                                   credit_limit_cents=349_999)
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 100_000)
        publish_sheet(sheet["id"])
        request_allocation(customer, line["id"], 500)
        run_sheet(sheet["id"])
        assert get_customer(customer["id"])["status"] == "CREDIT_HOLD"

        resp = api_client.create_allocation(
            create_allocation_payload(customer["id"], line["id"], 10),
            make_customer_rep_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD)


class TestForwardContractLifecycle:
    def test_contract_default_on_clock_and_amend_rejected(self, trader_headers):
        """PRD §2.4: "In the second sweep, every `OPEN` forward contract whose
        delivery week has fully elapsed — the logical date is on or after the
        Monday immediately following the delivery week — while its
        `delivered_lbs` remains below its `committed_lbs` transitions to
        `DEFAULTED` and is removed from the forward component of net exposure."
        PRD §3.6: "the contract must be `OPEN`, else `ERR_CONTRACT_NOT_OPEN`"

        Design: Corner/state_machines/contract_default_on_clock_and_amend_rejected
        """
        product = create_product(product_code="RIBEYE-DF", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-DF")
        fc = create_forward_contract(customer, product["id"], committed_lbs=100,
                                     fixed_price_per_lb_cents=650,
                                     delivery_week_start=WEEK_1)

        sweep = set_clock("2026-08-10T00:00:00Z")
        assert fc["id"] in sweep["defaulted_contract_ids"]
        assert get_contract(fc["id"])["status"] == "DEFAULTED"

        resp = api_client.amend_forward_contract(
            fc["id"],
            amend_forward_contract_payload(200, 660, WEEK_2, fc["version"]),
            trader_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_OPEN)

    def test_contract_cancel_blocked_by_confirmed_earmark(self,
                                                          risk_officer_headers):
        """PRD §3.6: "And a `RiskOfficer` may cancel an `OPEN` contract — else
        `ERR_CONTRACT_NOT_OPEN` — provided no `CONFIRMED` allocation is
        earmarked to it, a block reported as
        `ERR_CONTRACT_HAS_CONFIRMED_ALLOCATIONS`"

        Design: Corner/validations/contract_cancel_blocked_by_confirmed_earmark
        """
        product = create_product(product_code="RIBEYE-CX", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-CX")
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 5_000)
        publish_sheet(sheet["id"])
        contract = create_forward_contract(customer, product["id"],
                                           committed_lbs=1000,
                                           fixed_price_per_lb_cents=650,
                                           delivery_week_start=WEEK_1)
        request_allocation(customer, line["id"], 400,
                           forward_contract_id=contract["id"])
        run_sheet(sheet["id"])

        resp = api_client.cancel_forward_contract(contract["id"],
                                                  risk_officer_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_HAS_CONFIRMED_ALLOCATIONS)
        assert get_contract(contract["id"])["status"] == "OPEN"

    def test_forward_week_in_past_returns_422(self, trader_headers):
        """PRD §2.7: "A forward contract's delivery week may not be earlier
        than the current logical week — neither at creation nor when amended —
        and such a request is rejected with `ERR_FORWARD_WEEK_PASSED`
        (HTTP 422)."
        PRD §2.4: "Before any operator advances it, the clock reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time."

        Design: Corner/validations/forward_week_in_past_returns_422
        """
        product = create_product(product_code="RIBEYE-FW", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-FW")
        resp = api_client.create_forward_contract(
            create_forward_contract_payload(customer["id"], product["id"],
                                            committed_lbs=100,
                                            delivery_week_start="2026-07-20"),
            trader_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORWARD_WEEK_PASSED)


class TestEarmarkValidation:
    def test_forward_customer_mismatch_returns_422(self):
        """PRD §3.6: "the earmark is validated three ways — the contract must
        belong to the same customer, else
        `ERR_FORWARD_CONTRACT_CUSTOMER_MISMATCH`; the contract's product must
        be the same product as the line's, else `ERR_PRODUCT_KIND_MISMATCH`;
        and the contract's delivery week must equal the sheet's week, else
        `ERR_FORWARD_CONTRACT_WEEK_MISMATCH`."

        Design: Corner/validations/forward_customer_mismatch_returns_422
        """
        product = create_product(product_code="RIBEYE-FM", max_fat_pct=12.0)
        cust_a = create_customer(customer_code="FCM-A")
        cust_b = create_customer(customer_code="FCM-B")
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 10_000)
        publish_sheet(sheet["id"])
        contract = create_forward_contract(cust_b, product["id"],
                                           committed_lbs=100,
                                           delivery_week_start=WEEK_1)

        resp = api_client.create_allocation(
            create_allocation_payload(cust_a["id"], line["id"], 10,
                                      forward_contract_id=contract["id"]),
            make_customer_rep_headers(cust_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORWARD_CONTRACT_CUSTOMER_MISMATCH)

    def test_forward_week_mismatch_returns_422(self):
        """PRD §3.6: "the earmark is validated three ways — the contract must
        belong to the same customer, else
        `ERR_FORWARD_CONTRACT_CUSTOMER_MISMATCH`; the contract's product must
        be the same product as the line's, else `ERR_PRODUCT_KIND_MISMATCH`;
        and the contract's delivery week must equal the sheet's week, else
        `ERR_FORWARD_CONTRACT_WEEK_MISMATCH`."

        Design: Corner/validations/forward_week_mismatch_returns_422
        """
        product = create_product(product_code="RIBEYE-WM", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-WM")
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 10_000)
        publish_sheet(sheet["id"])
        contract = create_forward_contract(customer, product["id"],
                                           committed_lbs=100,
                                           delivery_week_start=WEEK_2)

        resp = api_client.create_allocation(
            create_allocation_payload(customer["id"], line["id"], 10,
                                      forward_contract_id=contract["id"]),
            make_customer_rep_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORWARD_CONTRACT_WEEK_MISMATCH)


class TestContractOcc:
    def test_occ_contract_amend_stale_version(self, trader_headers):
        """PRD §2.9: "Amending a forward contract requires the request to carry
        `expected_contract_version` equal to the contract's current `version`.
        An amendment replaces the contract's terms while the contract stays
        `OPEN`, so a second sequential amendment carrying a stale
        `expected_contract_version` likewise sees identical business state; a
        mismatch is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."
        PRD §3.6: "A successful amendment replaces `committed_lbs`,
        `fixed_price_per_lb_cents`, and `delivery_week_start` wholesale with
        the payload values, increments `amendment_round` by one, and increments
        the contract's `version` by one; the contract remains `OPEN`."

        Design: Corner/cross_cutting/occ_contract_amend_stale_version
        """
        product = create_product(product_code="RIBEYE-OCC", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-OCC")
        fc = create_forward_contract(customer, product["id"], committed_lbs=100,
                                     fixed_price_per_lb_cents=650,
                                     delivery_week_start=WEEK_1)
        v1 = fc["version"]

        first = api_client.amend_forward_contract(
            fc["id"], amend_forward_contract_payload(200, 640, WEEK_1, v1),
            trader_headers,
        )
        amended = validate_success(first)
        assert amended["version"] == v1 + 1
        assert amended["amendment_round"] == 1
        assert amended["committed_lbs"] == 200
        assert amended["status"] == "OPEN"

        stale = api_client.amend_forward_contract(
            fc["id"], amend_forward_contract_payload(300, 630, WEEK_1, v1),
            trader_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_CONTRACT_VERSION)

        after = get_contract(fc["id"])
        assert after["committed_lbs"] == 200, \
            "a stale amendment must not overwrite the negotiated terms"
        assert after["amendment_round"] == 1


class TestHedgingExposureReport:
    def test_hedging_exposure_report_math(self, trader_headers):
        """PRD §3.9: "`physical_lbs` is the sum of `current_weight_lbs` over
        lots of the product in `AVAILABLE` status. `inbound_lbs` is the sum of
        `ordered_weight_lbs` over the product's purchase orders in `BOOKED`
        status. `forward_lbs` is the sum, over the product's `OPEN` forward
        contracts whose `delivery_week_start` equals the requested week, of
        each contract's `committed_lbs` minus its `delivered_lbs`. `spot_lbs`
        is the sum of `allocated_lbs` over `CONFIRMED` allocations whose line
        prices the product and whose line's sheet has `week_start_date` equal
        to the requested week. The net pound figure, `exposure_lbs`, is
        physical plus inbound minus forward minus spot."
        PRD §3.9: "The basis price is the most recently published sheet's line
        price for the product under the §2.7 selector — zero when no such line
        exists — and `exposure_value_cents` is `exposure_lbs` multiplied by
        that basis price, rounded half-up to whole cents."

        Design: Corner/calculations/hedging_exposure_report_math
        """
        ctx = setup_confirmed_allocation(requested_lbs=200, lot_weight=1000,
                                         price_per_lb_cents=700)
        product = ctx["product"]
        customer = ctx["customer"]
        # Inbound component: a second PO of 500 lbs stays BOOKED.
        po2 = book_po(ctx["supplier"]["id"], product["id"],
                      ordered_weight_lbs=500,
                      required_delivery_date="2026-08-06")
        assert get_po(po2["id"])["status"] == "BOOKED"
        # Forward component: OPEN contract for 300 lbs in the same week.
        create_forward_contract(customer, product["id"], committed_lbs=300,
                                fixed_price_per_lb_cents=650,
                                delivery_week_start=WEEK_1)

        resp = api_client.get_exposure(
            trader_headers,
            params={"product_id": product["id"], "week_start": WEEK_1},
        )
        data = validate_success(resp)
        assert_exposure_report(data)
        assert data["physical_lbs"] == 1000
        assert data["inbound_lbs"] == 500
        assert data["forward_lbs"] == 300
        assert data["spot_lbs"] == 200
        # physical + inbound - forward - spot = 1000 + 500 - 300 - 200
        assert data["exposure_lbs"] == 1000
        assert data["exposure_value_cents"] == 700_000  # 1000 lbs x 700c

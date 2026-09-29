"""Uniqueness scopes, inclusive bounds and the order the gates speak in."""

from test_helpers import (
    ADMIN,
    ANALYST,
    REVIEWER,
    REVIEWER_ALT,
    TRADER,
    ApiErrorId,
    api_client,
    assert_loan,
    assert_repurchase_demand,
    factories,
    fixtures,
    make_seller_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestUniquenessScopes:
    """Two keys are global, the third is only unique inside its parent."""

    def test_a_second_tin_and_a_second_product_code_are_both_refused_platform_wide(self):
        """Neither key may repeat anywhere, and neither refusal disturbs the original.

        The taxpayer number is re-offered under a different legal name and the
        product code under a different base price; both are refused and the
        originals are untouched, so the platform still holds exactly one seller and
        the product still prices at 101.250.

        PRD: "Taxpayer identification numbers are unique across the whole platform;
        a second registration carrying an existing `tin` is refused with
        `ERR_DUPLICATE_TIN`."

        Design: Corner/validations/duplicate_tin_product_code_and_adjustment_code_are_rejected
        """
        fixtures.setup_clock()
        seller = fixtures.setup_seller()
        product = fixtures.setup_product()

        validate_error(
            api_client.create_seller(
                factories.seller_payload(legal_name="Harbor Point Mortgage Co"), ANALYST
            ),
            ApiErrorId.ERR_DUPLICATE_TIN,
            409,
        )
        validate_error(
            api_client.create_product(
                factories.product_payload(base_price_pct=99.500), ADMIN
            ),
            ApiErrorId.ERR_DUPLICATE_PRODUCT_CODE,
            409,
        )

        _, meta = validate_paginated(api_client.list_sellers(ANALYST))
        assert meta["total_count"] == 1
        assert fixtures.read_seller(seller["id"])["legal_name"] == "Harbor Point Mortgage LLC"
        assert validate_success(api_client.get_product(product["id"], ADMIN))[
            "base_price_pct"
        ] == 101.250

    def test_an_adjustment_code_may_repeat_on_a_different_product_only(self):
        """The same grid code is a collision here and perfectly legal next door.

        Re-offering LLPA-F700-L85 under the product that already carries it is
        refused, while the identical code under a second product is accepted and
        belongs to that second product.

        PRD: "Each row carries an `adjustment_code` of between 3 and 48 characters,
        unique within its product — a repeat within the same product is
        `ERR_DUPLICATE_ADJUSTMENT_CODE`, while the same code on a different product
        is perfectly legal — and a signed `price_adjustment_bps` between -300 and
        100 that is applied when the row's band matches."

        Design: Corner/validations/duplicate_tin_product_code_and_adjustment_code_are_rejected
        """
        fixtures.setup_clock()
        first = fixtures.setup_product_with_grid()
        second = fixtures.setup_product(product_code="CONF15F")

        validate_error(
            api_client.create_pricing_adjustment(
                first["product_id"],
                factories.pricing_adjustment_payload(price_adjustment_bps=-75),
                ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_ADJUSTMENT_CODE,
            409,
        )

        accepted = validate_success(
            api_client.create_pricing_adjustment(
                second["id"], factories.pricing_adjustment_payload(), ADMIN
            ),
            201,
        )
        assert accepted["product_id"] == second["id"]
        assert accepted["adjustment_code"] == "LLPA-F700-L85"

        rows, meta = validate_paginated(
            api_client.list_pricing_adjustments(first["product_id"], ADMIN)
        )
        assert meta["total_count"] == 1
        assert rows[0]["price_adjustment_bps"] == -50


class TestSellerLoanNumberScope:
    """The uniqueness key is the seller, not the commitment it was sold under."""

    def test_the_same_loan_number_collides_within_a_seller_and_not_across_sellers(self):
        """HP-0001 is refused on the seller's second line and fine for a stranger.

        The number is taken on the seller's first line, so a delivery of the same
        number against a different line of the same seller is refused and consumes
        no capacity; an entirely different seller delivers HP-0001 without trouble.

        PRD: "The `seller_loan_number` must be unique across all loans of that same
        seller, regardless of which commitment they were delivered against; a repeat
        is `ERR_DUPLICATE_SELLER_LOAN_NUMBER`, while the same number used by a
        different seller is fine."

        Design: Corner/validations/seller_loan_number_uniqueness_is_scoped_to_the_seller_not_the_commitment
        """
        staged = fixtures.setup_lock_ready_seller()
        first_line = fixtures.setup_commitment(
            staged["seller_id"], staged["product_id"]
        )
        second_line = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            commitment_type="BEST_EFFORTS",
        )
        original = fixtures.deliver_loan(
            first_line["id"], staged["seller_id"], seller_loan_number="HP-0001"
        )
        assert_loan(original)
        assert original["seller_loan_number"] == "HP-0001"

        validate_error(
            api_client.deliver_loan(
                second_line["id"],
                factories.loan_payload(
                    second_line["version"], seller_loan_number="HP-0001"
                ),
                staged["seller_headers"],
            ),
            ApiErrorId.ERR_DUPLICATE_SELLER_LOAN_NUMBER,
            409,
        )
        assert fixtures.read_commitment(second_line["id"])["allocated_amount_cents"] == 0

        stranger = fixtures.setup_approved_seller(
            seller_overrides={
                "legal_name": "Cascade Funding Inc",
                "tin": "770112238",
                "seller_type": "BANK",
            }
        )
        stranger_line = fixtures.setup_commitment(
            stranger["seller_id"], staged["product_id"]
        )
        twin = fixtures.deliver_loan(
            stranger_line["id"],
            stranger["seller_id"],
            seller_loan_number="HP-0001",
            note_amount_cents=30000000,
        )

        assert twin["seller_id"] == stranger["seller_id"]
        assert twin["seller_loan_number"] == "HP-0001"
        assert fixtures.read_commitment(first_line["id"])["allocated_amount_cents"] == 40000000
        assert fixtures.read_commitment(stranger_line["id"])["allocated_amount_cents"] == 30000000


class TestClearGatePriorityOrder:
    """Three files, three different lowest-numbered violated gates."""

    @staticmethod
    def _three_files_with_different_open_items() -> dict:
        staged = fixtures.setup_lock_ready_seller()
        commitment = fixtures.setup_commitment(
            staged["seller_id"], staged["product_id"], notional_amount_cents=120000000
        )
        loans = {}
        for key, number in (
            ("non_curable", "HP-0001"),
            ("curable", "HP-0002"),
            ("condition", "HP-0003"),
        ):
            loan = fixtures.deliver_loan(
                commitment["id"], staged["seller_id"], seller_loan_number=number
            )
            fixtures.open_loan_review(loan["id"])
            loans[key] = loan["id"]

        staged["non_curable_defect"] = fixtures.record_defect(
            loans["non_curable"], "COMP-TRID-4001", "COMPLIANCE", "HIGH"
        )
        fixtures.record_defect(loans["non_curable"], "CRED-DTI-2210", "CREDIT", "HIGH")
        fixtures.add_suspense_condition(loans["non_curable"], "COND-HOI-01")

        fixtures.record_defect(loans["curable"], "CRED-DTI-2210", "CREDIT", "HIGH")
        fixtures.add_suspense_condition(loans["curable"], "COND-HOI-01")

        staged["condition"] = fixtures.add_suspense_condition(
            loans["condition"], "COND-HOI-01"
        )
        staged["loans"] = loans
        staged["commitment_id"] = commitment["id"]
        return staged

    def test_each_file_reports_only_its_lowest_numbered_violated_gate(self):
        """All three gates are violated on the first file, and one error comes back.

        The file carrying a non-curable finding also carries a curable one and an
        open condition, yet it answers on the non-curable gate alone; the file with
        a curable finding and a condition answers on open defects; the file with only
        a condition answers on open conditions.

        PRD: "Clearing a loan file evaluates the non-curable gate
        (`ERR_NON_CURABLE_DEFECT_PRESENT`, in group 9) **before** the open-defect
        and open-suspense gates (`ERR_OPEN_DEFECTS_PRESENT` and
        `ERR_OPEN_SUSPENSE_CONDITIONS`, in group 12), so a file carrying an open
        non-curable defect reports the non-curable error even though it also has open
        items."

        Design: Corner/validations/clear_for_purchase_gates_speak_in_priority_order_across_three_loans
        """
        staged = self._three_files_with_different_open_items()

        validate_error(
            api_client.clear_loan(staged["loans"]["non_curable"], REVIEWER),
            ApiErrorId.ERR_NON_CURABLE_DEFECT_PRESENT,
            409,
        )
        validate_error(
            api_client.clear_loan(staged["loans"]["curable"], REVIEWER),
            ApiErrorId.ERR_OPEN_DEFECTS_PRESENT,
            409,
        )
        validate_error(
            api_client.clear_loan(staged["loans"]["condition"], REVIEWER),
            ApiErrorId.ERR_OPEN_SUSPENSE_CONDITIONS,
            409,
        )

        assert staged["non_curable_defect"]["classification"] == "NON_CURABLE"
        blocked = fixtures.read_loan(staged["loans"]["non_curable"])
        assert blocked["non_curable_defect_count"] == 1
        assert blocked["purchase_status"] == "SUSPENDED"
        assert fixtures.read_loan(staged["loans"]["curable"])["purchase_status"] == "SUSPENDED"

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert commitment["allocated_amount_cents"] == 120000000
        assert commitment["available_amount_cents"] == 0
        assert commitment["status"] == "LOCKED"

    def test_clearing_the_last_open_condition_lets_that_file_through(self):
        """Removing the only blocker turns the same refusal into a clearance.

        The third file's single condition is cleared on its document, which returns
        the file to review and empties its counters, and the identical clear call
        then moves it to cleared for purchase with one completed review cycle behind
        it.

        PRD: "Clearing moves the loan `IN_REVIEW → CLEARED_FOR_PURCHASE` and
        increments its `version` by 1."

        Design: Corner/validations/clear_for_purchase_gates_speak_in_priority_order_across_three_loans
        """
        staged = self._three_files_with_different_open_items()
        loan_id = staged["loans"]["condition"]
        validate_error(
            api_client.clear_loan(loan_id, REVIEWER),
            ApiErrorId.ERR_OPEN_SUSPENSE_CONDITIONS,
            409,
        )

        fixtures.clear_suspense_condition(staged["condition"]["id"], "HOI-2026-0001")
        cleared = fixtures.clear_loan_for_purchase(loan_id)

        assert cleared["purchase_status"] == "CLEARED_FOR_PURCHASE"
        assert cleared["review_cycle_count"] == 1
        assert cleared["open_suspense_count"] == 0
        assert cleared["open_defect_count"] == 0


class TestMandatoryExposureAggregate:
    """The exposure line admits its own value and is freed by a pair-off."""

    @staticmethod
    def _seller_exactly_on_its_exposure_limit() -> dict:
        staged = fixtures.setup_lock_ready_seller(with_adjustment=False)
        assert fixtures.read_seller(staged["seller_id"])[
            "mandatory_exposure_limit_cents"
        ] == 3000000000
        staged["first_id"] = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            notional_amount_cents=1500000000,
            reference_fico=760,
            reference_ltv_pct=75.0,
        )["id"]
        staged["second"] = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            notional_amount_cents=1500000000,
            delivery_window_start="2026-08-31",
            delivery_expiry_date="2026-09-30",
            reference_fico=760,
            reference_ltv_pct=75.0,
        )
        return staged

    @staticmethod
    def _one_more_lock(staged: dict, commitment_type: str):
        return api_client.create_commitment(
            factories.commitment_payload(
                staged["seller_id"],
                staged["product_id"],
                commitment_type=commitment_type,
                notional_amount_cents=100000000,
                delivery_window_start="2026-09-30",
                delivery_expiry_date="2026-10-30",
                reference_fico=760,
                reference_ltv_pct=75.0,
            ),
            TRADER,
        )

    def test_landing_exactly_on_the_limit_is_allowed_and_one_cent_of_room_is_not(self):
        """Two lines fill the line to the brim; the next mandatory lock has nowhere to go.

        The aggregate sits precisely on 3,000,000,000, which the rule permits, so
        only the third mandatory request is refused — and a best-efforts request of
        the very same size is waved through without touching the aggregate.

        PRD: "The seller's current `open_mandatory_exposure_cents` plus the new
        `notional_amount_cents` must not exceed its `mandatory_exposure_limit_cents`;
        landing exactly on the limit is permitted, and only exceeding it is refused
        with `ERR_MANDATORY_EXPOSURE_LIMIT_EXCEEDED`."

        Design: Corner/validations/mandatory_exposure_aggregate_admits_the_exact_limit_and_is_freed_by_pair_off
        """
        staged = self._seller_exactly_on_its_exposure_limit()
        assert staged["second"]["commitment_price_pct"] == 101.380
        assert fixtures.read_seller(staged["seller_id"])[
            "open_mandatory_exposure_cents"
        ] == 3000000000

        validate_error(
            self._one_more_lock(staged, "MANDATORY"),
            ApiErrorId.ERR_MANDATORY_EXPOSURE_LIMIT_EXCEEDED,
            409,
        )
        assert fixtures.read_seller(staged["seller_id"])[
            "open_mandatory_exposure_cents"
        ] == 3000000000

        best_efforts = validate_success(
            self._one_more_lock(staged, "BEST_EFFORTS"), 201
        )
        assert best_efforts["commitment_type"] == "BEST_EFFORTS"
        assert fixtures.read_seller(staged["seller_id"])[
            "open_mandatory_exposure_cents"
        ] == 3000000000

    def test_pairing_off_a_line_frees_its_whole_notional_for_the_refused_lock(self):
        """The refused request succeeds unchanged once room is made.

        Pairing off the second line at exactly its own locked price produces no
        market loss, so only the flat administrative charge is booked, and the full
        1,500,000,000 comes back off the aggregate — enough for the previously
        refused 100,000,000 lock to go through.

        PRD: "The pair-off then moves the commitment `LOCKED → PAIRED_OFF` or
        `PARTIALLY_FULFILLED → PAIRED_OFF`, absorbing the whole remaining
        `available_amount_cents` into `paired_off_amount_cents` and driving the
        residual to zero, records the supplied `pair_off_market_price_pct`, writes
        `pair_off_fee_cents` and `pair_off_method`, adds the fee to the seller's
        `fee_receivable_cents`, releases the seller's mandatory exposure by the full
        `notional_amount_cents` when the commitment was `MANDATORY`, and increments
        the commitment's `version` by 1."

        Design: Corner/validations/mandatory_exposure_aggregate_admits_the_exact_limit_and_is_freed_by_pair_off
        """
        staged = self._seller_exactly_on_its_exposure_limit()
        validate_error(
            self._one_more_lock(staged, "MANDATORY"),
            ApiErrorId.ERR_MANDATORY_EXPOSURE_LIMIT_EXCEEDED,
            409,
        )

        paired = fixtures.pair_off_commitment(staged["second"]["id"], 101.380)
        assert paired["status"] == "PAIRED_OFF"
        assert paired["pair_off_method"] == "MANDATORY_MARK_TO_MARKET"
        assert paired["pair_off_fee_cents"] == 25000
        assert paired["paired_off_amount_cents"] == 1500000000
        assert paired["available_amount_cents"] == 0

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["fee_receivable_cents"] == 25000
        assert seller["open_mandatory_exposure_cents"] == 1500000000

        retried = validate_success(self._one_more_lock(staged, "MANDATORY"), 201)
        assert retried["notional_amount_cents"] == 100000000
        assert fixtures.read_seller(staged["seller_id"])[
            "open_mandatory_exposure_cents"
        ] == 1600000000


class TestDeliveryCapacityBounds:
    """Allocation is inclusive at the top and unforgiving one cent above it."""

    def test_the_residual_takes_a_loan_equal_to_it_and_refuses_one_cent_more(self):
        """76,650,000 then 23,350,000 exactly consumes the line; 23,350,001 does not.

        The first file is delivered at exactly the product's largest accepted note
        amount, which is inside the matrix, leaving 23,350,000 of room. One cent
        above that residual is refused without touching the line's version, and the
        retry at exactly the residual empties the available bucket while the status
        stays locked, because allocation is not fulfilment.

        PRD: "And last of all, the delivered `note_amount_cents` must not exceed the
        commitment's `available_amount_cents`, else
        `ERR_COMMITMENT_CAPACITY_EXCEEDED`."

        Design: Corner/validations/delivery_at_the_exact_available_balance_passes_and_one_cent_over_is_refused
        """
        staged = fixtures.setup_lock_ready_seller()
        commitment = fixtures.setup_commitment(
            staged["seller_id"], staged["product_id"]
        )

        at_the_product_ceiling = fixtures.deliver_loan(
            commitment["id"],
            staged["seller_id"],
            seller_loan_number="HP-0001",
            note_amount_cents=76650000,
        )
        assert at_the_product_ceiling["note_amount_cents"] == 76650000

        after_first = fixtures.read_commitment(commitment["id"])
        assert after_first["available_amount_cents"] == 23350000
        version_before_refusal = after_first["version"]

        validate_error(
            api_client.deliver_loan(
                commitment["id"],
                factories.loan_payload(
                    version_before_refusal,
                    seller_loan_number="HP-0002",
                    note_amount_cents=23350001,
                ),
                staged["seller_headers"],
            ),
            ApiErrorId.ERR_COMMITMENT_CAPACITY_EXCEEDED,
            409,
        )
        assert fixtures.read_commitment(commitment["id"])["version"] == version_before_refusal

        exact = fixtures.deliver_loan(
            commitment["id"],
            staged["seller_id"],
            seller_loan_number="HP-0003",
            note_amount_cents=23350000,
            expected_version=version_before_refusal,
        )
        assert exact["note_amount_cents"] == 23350000

        filled = fixtures.read_commitment(commitment["id"])
        assert filled["allocated_amount_cents"] == 100000000
        assert filled["available_amount_cents"] == 0
        assert filled["fulfilled_amount_cents"] == 0
        assert filled["status"] == "LOCKED"


class TestDeliveryWindowIsHalfOpen:
    """The start instant is inside; the expiry instant already is not."""

    def test_the_last_second_of_the_window_delivers_and_the_expiry_instant_does_not(self):
        """One second decides it, and the line does not expire of its own accord.

        A delivery on the window's opening instant and another at 2026-08-15T23:59:59Z
        are both booked, while the identical file one second later, on the expiry
        instant itself, is refused. The line is still locked with 80,000,000
        allocated, and the sweep run at that same instant skips it precisely because
        of that allocation.

        PRD: "The logical clock must fall inside the commitment's half-open delivery
        window, from `delivery_window_start` at midnight UTC up to but not including
        `delivery_expiry_date` at midnight UTC — a delivery attempted on the expiry
        date itself is already too late and is refused with
        `ERR_COMMITMENT_EXPIRED`."

        Design: Corner/validations/delivery_inside_the_half_open_window_passes_and_on_the_expiry_instant_is_refused
        """
        staged = fixtures.setup_lock_ready_seller()
        commitment = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            notional_amount_cents=150000000,
            delivery_expiry_date="2026-08-16",
        )
        assert commitment["lock_term_days"] == 15

        fixtures.deliver_loan(
            commitment["id"], staged["seller_id"], seller_loan_number="HP-0001"
        )

        fixtures.setup_clock("2026-08-15T23:59:59Z")
        last_instant = fixtures.deliver_loan(
            commitment["id"],
            staged["seller_id"],
            seller_loan_number="HP-0002",
            closing_date="2026-08-10",
            first_payment_due_date="2026-10-01",
        )
        assert last_instant["purchase_status"] == "DELIVERED"

        fixtures.setup_clock("2026-08-16T00:00:00Z")
        validate_error(
            api_client.deliver_loan(
                commitment["id"],
                factories.loan_payload(
                    fixtures.commitment_version(commitment["id"]),
                    seller_loan_number="HP-0003",
                    closing_date="2026-08-14",
                    first_payment_due_date="2026-10-01",
                ),
                staged["seller_headers"],
            ),
            ApiErrorId.ERR_COMMITMENT_EXPIRED,
            409,
        )

        still_live = fixtures.read_commitment(commitment["id"])
        assert still_live["status"] == "LOCKED"
        assert still_live["allocated_amount_cents"] == 80000000

        summary = fixtures.sweep_due_commitments(staged["seller_id"])
        assert summary["expired_count"] == 0
        assert fixtures.read_commitment(commitment["id"])["status"] == "LOCKED"


class TestLockGateOrderOnAnUnapprovedSeller:
    """One request violating three lock gates answers on the first of them."""

    def test_a_freshly_registered_seller_is_told_only_that_it_is_not_approved(self):
        """Standing and exposure are equally hopeless, and neither is mentioned.

        A brand new seller is not approved, is not eligible to deliver, and has an
        exposure limit of zero that any positive notional would breach; the single
        error names the approval gate, which sits highest in the ladder, and no
        commitment is created.

        PRD: "The seller's `approval_status` must be `APPROVED`, else
        `ERR_SELLER_NOT_APPROVED`."

        Design: Corner/validations/unapproved_seller_gate_outranks_the_standing_and_exposure_gates_on_one_lock
        """
        fixtures.setup_clock()
        product = fixtures.setup_product()
        seller = fixtures.setup_seller()
        assert seller["delivery_standing"] == "NOT_ELIGIBLE"
        assert seller["mandatory_exposure_limit_cents"] == 0

        error = validate_error(
            api_client.create_commitment(
                factories.commitment_payload(seller["id"], product["id"]), TRADER
            ),
            ApiErrorId.ERR_SELLER_NOT_APPROVED,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_SELLER_DELIVERY_SUSPENDED.value
        assert error["error_id"] != ApiErrorId.ERR_MANDATORY_EXPOSURE_LIMIT_EXCEEDED.value
        assert error["message"]

        _, meta = validate_paginated(
            api_client.list_commitments(TRADER, {"seller_id": seller["id"]})
        )
        assert meta["total_count"] == 0


class TestEarlyPaymentDefaultDemandGates:
    """Two independent gates on twin purchased loans."""

    @staticmethod
    def _twin_purchased_loans() -> dict:
        staged = fixtures.setup_purchased_loan(funding_reference="WIRE-A-0001")
        twin = fixtures.purchase_additional_loan(
            staged["commitment_id"],
            staged["seller_id"],
            "HP-0002",
            funding_reference="WIRE-B-0001",
        )
        staged["twin_loan_id"] = twin["loan_id"]
        return staged

    def test_a_demand_before_the_payment_is_recorded_is_refused_then_accepted_on_day_120(self):
        """The flag is what establishes the default, and day 120 is inside the window.

        While the first payment is still unrecorded the demand has nothing to stand
        on, so it is refused and the loan stays purchased. Recording the missed
        payment establishes the default, and a demand raised exactly 120 days after
        the first payment was due is accepted, pinning the recovery to the
        40,377,389 that was actually wired plus the flat administrative fee.

        PRD: "An `EPD` demand must carry no `source_defect_id` at all, and instead
        depends entirely on the payment record: the loan's `first_payment_status`
        must be `MISSED`, else `ERR_EPD_NOT_ESTABLISHED`, and the logical clock must
        be within 120 days after the loan's `first_payment_due_date`, else
        `ERR_EPD_WINDOW_EXPIRED`."

        PRD: "The `admin_fee_cents` is a flat 50,000 cents, and the
        `repurchase_price_cents` is the sum of the two."

        Design: Corner/validations/epd_demand_needs_a_missed_first_payment_and_dies_on_day_one_hundred_twenty_one
        """
        staged = self._twin_purchased_loans()
        assert staged["advice"]["net_wire_cents"] == 40377389

        validate_error(
            api_client.create_repurchase_demand(
                staged["loan_id"],
                factories.repurchase_demand_payload("EPD", "RD-2026-0001"),
                REVIEWER,
            ),
            ApiErrorId.ERR_EPD_NOT_ESTABLISHED,
            409,
        )
        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "PURCHASED"

        missed = fixtures.record_payment_event(staged["loan_id"], "FIRST_PAYMENT_MISSED")
        assert missed["first_payment_status"] == "MISSED"

        fixtures.setup_clock("2026-12-30T00:00:00Z")
        demand = fixtures.issue_repurchase_demand(
            staged["loan_id"], "EPD", "RD-2026-0002"
        )

        assert_repurchase_demand(demand)
        assert demand["status"] == "ISSUED"
        assert demand["reason"] == "EPD"
        assert demand["seller_id"] == staged["seller_id"]
        assert demand["source_defect_id"] is None
        assert demand["funding_recovery_cents"] == 40377389
        assert demand["admin_fee_cents"] == 50000
        assert demand["repurchase_price_cents"] == 40427389
        assert demand["appeal_deadline_at"] == "2027-01-29T00:00:00.000Z"
        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "REPURCHASE_DEMANDED"

    def test_a_demand_one_day_past_the_window_is_refused_even_on_a_missed_payment(self):
        """Day 121 is outside, and the missed payment cannot rescue it.

        The twin loan's payment was missed too, but the demand is raised on
        2026-12-31 — one day past the 120 days that follow its 2026-09-01 first
        payment date — so the window closes the matter and the loan stays purchased.

        PRD: "The window check is evaluated **before** the missed-payment check
        (§2.5), so a demand raised long after the window closed on a loan whose
        payment was never even recorded reports the expired window rather than the
        unestablished default."

        Design: Corner/validations/epd_demand_needs_a_missed_first_payment_and_dies_on_day_one_hundred_twenty_one
        """
        staged = self._twin_purchased_loans()
        fixtures.record_payment_event(staged["twin_loan_id"], "FIRST_PAYMENT_MISSED")

        fixtures.setup_clock("2026-12-31T00:00:00Z")
        error = validate_error(
            api_client.create_repurchase_demand(
                staged["twin_loan_id"],
                factories.repurchase_demand_payload("EPD", "RD-2026-0003"),
                REVIEWER,
            ),
            ApiErrorId.ERR_EPD_WINDOW_EXPIRED,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_EPD_NOT_ESTABLISHED.value
        assert fixtures.read_loan(staged["twin_loan_id"])["purchase_status"] == "PURCHASED"


class TestDemandLifecycleRefusals:
    """Three illegal moves on one demand, and the path that does work."""

    @staticmethod
    def _two_demanded_loans() -> dict:
        staged = fixtures.setup_loan_with_waived_defect(
            defect_code="INC-DOCS-2201", category="INCOME", severity="HIGH"
        )
        fixtures.clear_loan_for_purchase(staged["loan_id"])
        advice = fixtures.issue_purchase_advice(staged["loan_id"])
        staged["advice"] = fixtures.settle_purchase_advice(advice["id"], "WIRE-A-0001")

        twin = fixtures.deliver_loan(
            staged["commitment_id"], staged["seller_id"], seller_loan_number="HP-0002"
        )
        fixtures.open_loan_review(twin["id"])
        twin_defect = fixtures.record_defect(
            twin["id"], "INC-DOCS-2201", "INCOME", "HIGH"
        )
        fixtures.waive_defect(twin_defect["id"], -25)
        fixtures.clear_loan_for_purchase(twin["id"])
        twin_advice = fixtures.issue_purchase_advice(twin["id"])
        fixtures.settle_purchase_advice(twin_advice["id"], "WIRE-B-0001")
        staged["twin_loan_id"] = twin["id"]

        fixtures.setup_clock("2026-08-10T00:00:00Z")
        first = fixtures.issue_repurchase_demand(
            staged["loan_id"], "DEFECT", "RD-2026-0001", staged["defect_id"]
        )
        second = fixtures.issue_repurchase_demand(
            staged["twin_loan_id"], "DEFECT", "RD-2026-0002", twin_defect["id"]
        )
        staged["demand"] = first
        staged["demand_id"] = first["id"]
        staged["twin_demand_id"] = second["id"]
        return staged

    def test_uphold_before_an_appeal_a_second_appeal_and_settlement_during_one_all_fail(self):
        """Each refusal names the precondition it broke, and the demand keeps moving.

        Upholding an uncontested demand is refused because there is nothing to
        uphold; once the seller appeals, a second appeal is refused because appealing
        requires an issued demand; and remitting against a live appeal is refused
        because settlement requires an issued or upheld demand.

        PRD: "`UPHOLD` is available **only** from `APPEALED`, else
        `ERR_DEMAND_NOT_ACTIONABLE`."

        PRD: "The demand must be in `ISSUED` or `UPHELD` status, else
        `ERR_DEMAND_NOT_SETTLEABLE` — a rescinded demand is dead and an appealed
        demand must be decided first — and the acting `X-User-ID` must equal the
        demand's `seller_id`, else `ERR_SELLER_SCOPE_VIOLATION`."

        Design: Corner/validations/demand_lifecycle_refuses_uphold_before_appeal_settlement_during_appeal_and_late_appeals
        """
        staged = self._two_demanded_loans()
        assert staged["advice"]["net_wire_cents"] == 40277389
        assert staged["demand"]["funding_recovery_cents"] == 40277389
        assert staged["demand"]["repurchase_price_cents"] == 40327389
        assert staged["demand"]["appeal_deadline_at"] == "2026-09-09T00:00:00.000Z"

        validate_error(
            api_client.decide_repurchase_demand(
                staged["demand_id"], {"decision": "UPHOLD"}, REVIEWER_ALT
            ),
            ApiErrorId.ERR_DEMAND_NOT_ACTIONABLE,
            409,
        )

        appealed = fixtures.appeal_repurchase_demand(
            staged["demand_id"],
            staged["seller_id"],
            "income documentation was complete at closing",
        )
        assert appealed["status"] == "APPEALED"

        validate_error(
            api_client.appeal_repurchase_demand(
                staged["demand_id"],
                {"appeal_reason": "second bite"},
                make_seller_user_headers(staged["seller_id"]),
            ),
            ApiErrorId.ERR_DEMAND_NOT_ACTIONABLE,
            409,
        )
        validate_error(
            api_client.settle_repurchase_demand(
                staged["demand_id"],
                {"remittance_reference": "RMT-0001"},
                make_seller_user_headers(staged["seller_id"]),
            ),
            ApiErrorId.ERR_DEMAND_NOT_SETTLEABLE,
            409,
        )
        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "REPURCHASE_DEMANDED"

    def test_a_late_appeal_dies_while_the_upheld_demand_is_still_satisfiable(self):
        """The deadline bars the seller's appeal, not the aggregator's decision.

        On 2026-09-10 the twin demand's appeal window has closed, so that appeal is
        refused and the twin stays issued. The first demand, appealed in time, is
        upheld after its own deadline has passed and then remitted, which unwinds the
        purchase: the loan is repurchased, its advice reversed, and the seller's
        funded total returns to exactly the value that the surviving purchase
        accounts for while the administrative fee stays booked.

        PRD: "the logical clock must be at or before `appeal_deadline_at`, else
        `ERR_APPEAL_WINDOW_EXPIRED`; and the acting `X-User-ID` must equal the
        demand's `seller_id`, else `ERR_SELLER_SCOPE_VIOLATION`."

        Design: Corner/validations/demand_lifecycle_refuses_uphold_before_appeal_settlement_during_appeal_and_late_appeals
        """
        staged = self._two_demanded_loans()
        assert fixtures.read_seller(staged["seller_id"])["net_funded_cents"] == 80554778
        fixtures.appeal_repurchase_demand(
            staged["demand_id"],
            staged["seller_id"],
            "income documentation was complete at closing",
        )

        fixtures.setup_clock("2026-09-10T00:00:00Z")
        validate_error(
            api_client.appeal_repurchase_demand(
                staged["twin_demand_id"],
                {"appeal_reason": "filed after the deadline"},
                make_seller_user_headers(staged["seller_id"]),
            ),
            ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED,
            409,
        )
        twin_demand = validate_success(
            api_client.get_repurchase_demand(staged["twin_demand_id"], REVIEWER)
        )
        assert twin_demand["status"] == "ISSUED"

        upheld = fixtures.decide_repurchase_demand(
            staged["demand_id"], "UPHOLD", "appeal reviewed and rejected", REVIEWER_ALT
        )
        assert upheld["status"] == "UPHELD"
        assert upheld["decided_by_user_id"] == "u-pr-2"

        satisfied = fixtures.satisfy_repurchase_demand(
            staged["demand_id"], staged["seller_id"], "RMT-0002"
        )
        assert satisfied["status"] == "SATISFIED"
        assert satisfied["satisfied_at"] == "2026-09-10T00:00:00.000Z"

        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "REPURCHASED"
        advices = fixtures.read_loan_advices(staged["loan_id"])
        assert advices[0]["status"] == "REVERSED"

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["net_funded_cents"] == 40277389
        assert seller["fee_receivable_cents"] == 50000


class TestDefectEvidenceForADemand:
    """Four near-miss references, and the one that actually is evidence."""

    @staticmethod
    def _purchased_loan_carrying_every_defect_shape() -> dict:
        staged = fixtures.setup_loan_in_review()
        cured = fixtures.record_defect(
            staged["loan_id"], "INC-DOCS-2201", "INCOME", "HIGH"
        )
        waived_high = fixtures.record_defect(
            staged["loan_id"], "CRED-ASSET-2210", "CREDIT", "HIGH"
        )
        waived_low = fixtures.record_defect(
            staged["loan_id"], "DOC-MISSING-1008", "DOCUMENTATION", "LOW"
        )
        fixtures.cure_defect(cured["id"], staged["seller_id"], "CURE-W2-0001")
        fixtures.waive_defect(waived_high["id"], -25)
        fixtures.waive_defect(waived_low["id"], -10)
        fixtures.clear_loan_for_purchase(staged["loan_id"])
        advice = fixtures.issue_purchase_advice(staged["loan_id"])
        staged["advice"] = advice
        fixtures.settle_purchase_advice(advice["id"], "WIRE-0001")
        staged["post_purchase"] = fixtures.record_defect(
            staged["loan_id"], "QC-POST-3301", "INCOME", "HIGH"
        )
        staged["cured_id"] = cured["id"]
        staged["waived_high_id"] = waived_high["id"]
        staged["waived_low_id"] = waived_low["id"]
        return staged

    @staticmethod
    def _demand(loan_id, reference, source_defect_id=None, reason="DEFECT"):
        return api_client.create_repurchase_demand(
            loan_id,
            factories.repurchase_demand_payload(reason, reference, source_defect_id),
            REVIEWER,
        )

    def test_four_near_miss_references_are_all_refused_as_insufficient_evidence(self):
        """Missing, cured, too mild and still open — none of them is evidence.

        The waived findings cost the seller 140,000 at pricing, and the file also
        carries a cured high finding, a waived low one and a post-purchase high one
        that is still open. A defect-reason demand naming none of them, or naming any
        of those three, is refused on evidence in every case.

        PRD: "A `DEFECT` or `MISREPRESENTATION` demand **requires** a
        `source_defect_id` naming a defect **of this same loan** whose `severity` is
        `HIGH` or `CRITICAL` and whose `status` is `WAIVED` or `EXPIRED`."

        Design: Corner/validations/defect_reason_demand_requires_high_severity_evidence_in_waived_or_expired_status
        """
        staged = self._purchased_loan_carrying_every_defect_shape()
        assert staged["advice"]["defect_price_adjustment_cents"] == -140000
        assert staged["advice"]["net_wire_cents"] == 40237389
        assert staged["post_purchase"]["status"] == "OPEN"
        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "PURCHASED"

        for reference, source_defect_id in (
            ("RD-2026-0001", None),
            ("RD-2026-0002", staged["cured_id"]),
            ("RD-2026-0003", staged["waived_low_id"]),
            ("RD-2026-0004", staged["post_purchase"]["id"]),
        ):
            validate_error(
                self._demand(staged["loan_id"], reference, source_defect_id),
                ApiErrorId.ERR_DEFECT_EVIDENCE_REQUIRED,
                422,
            )

        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "PURCHASED"

    def test_the_waived_high_finding_supports_a_misrepresentation_demand(self):
        """The evidence rule spans both defect-backed reasons, not just DEFECT.

        The one qualifying finding — high severity and waived — carries a
        misrepresentation demand through, and the demand's money is pinned to the
        40,237,389 that was wired rather than to the note amount.

        PRD: "The `funding_recovery_cents` is set to the `net_wire_cents` of the
        loan's single `SETTLED` purchase advice — superseded, voided and reversed
        advices are ignored, and exactly one settled advice exists for any loan that
        reached `PURCHASED` or beyond."

        Design: Corner/validations/defect_reason_demand_requires_high_severity_evidence_in_waived_or_expired_status
        """
        staged = self._purchased_loan_carrying_every_defect_shape()

        accepted = validate_success(
            self._demand(
                staged["loan_id"],
                "RD-2026-0005",
                staged["waived_high_id"],
                reason="MISREPRESENTATION",
            ),
            201,
        )

        assert accepted["reason"] == "MISREPRESENTATION"
        assert accepted["source_defect_id"] == staged["waived_high_id"]
        assert accepted["funding_recovery_cents"] == 40237389
        assert accepted["repurchase_price_cents"] == 40287389
        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "REPURCHASE_DEMANDED"

"""What the donor may claim: drafting, issuing, voiding and revaluing receipts."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_tax_receipt,
    create_tax_receipt_payload,
    new_charity,
    new_donor,
    new_venue,
    read_charity,
    read_donation,
    read_receipt,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    donation_ledger,
    draft_receipt,
    inspect_vehicle,
    new_lot,
    new_title,
    new_vehicle,
    read_title,
    sell_lot,
    setup_dropoff_in_custody,
    setup_listed_lot,
    setup_sold_donation,
)


class TestValuationVariants:
    def test_a_sold_donation_without_an_exception_claims_the_hammer_price(self, api):
        """PRD §3.8: "Otherwise, if the donation's `gross_proceeds_cents` is **strictly
        greater than** five hundred dollars (fifty thousand cents), the `GROSS_PROCEEDS`
        rule applies: `valuation_variant` is `GROSS_PROCEEDS`, `form_type` is
        `FORM_1098C_BOX_4A`, and `claimed_amount_cents` is the `gross_proceeds_cents`
        itself, ignoring the fair-market estimate entirely."
        PRD §3.8: "Issuing also closes the donation: it moves `SOLD → CLOSED` or
        `UNSOLD → CLOSED`, copies `claimed_amount_cents` onto the donation's
        `deduction_amount_cents`, and marks every `RECEIPT_DELIVERY` follow-up on that
        donation still `OPEN` or `ESCALATED` as `DONE` with a `resolution_note` of exactly
        `receipt issued`."

        Design: Difficulty/dual_variant_calc/receipt_gross_proceeds_vs_fmv_full_on_one_sold_donation
        """
        bundle = setup_listed_lot(
            with_vehicle=True,
            vehicle_overrides={"base_book_value_cents": 480_000},
            reserve_price_cents=50_000,
        )
        inspect_vehicle(bundle["vehicle"]["id"], odometer_miles=120_000, condition_grade="GOOD")
        sell_lot(bundle["lot"]["id"], bundle["donation"]["id"], 120_000)
        assert read_donation(bundle["donation"]["id"])["fmv_estimate_cents"] == 346_800

        receipt = draft_receipt(bundle["donation"]["id"])
        assert_tax_receipt(receipt)
        assert receipt["valuation_variant"] == "GROSS_PROCEEDS"
        assert receipt["form_type"] == "FORM_1098C_BOX_4A"
        assert receipt["claimed_amount_cents"] == 120_000

        validate_success(api.issue_receipt(receipt["id"], TEST_USERS["finance_officer_headers"]), 200)
        donation = read_donation(bundle["donation"]["id"])
        assert donation["status"] == "CLOSED"
        assert donation["deduction_amount_cents"] == 120_000

    def test_recording_an_exception_flips_the_reissued_receipt_to_full_fair_market_value(
        self, api, program_admin_headers, finance_officer_headers
    ):
        """PRD §3.8: "If the donation carries any `exception_type` other than `NONE`, the
        `FMV_FULL` rule applies: `valuation_variant` is `FMV_FULL`, `form_type` is
        `FORM_1098C_BOX_4B`, and `claimed_amount_cents` is the donation's full
        `fmv_estimate_cents`."
        PRD §3.8: "**Reissuing** returns a voided receipt to the desk. It requires the
        receipt to be `VOIDED` and the donation to be `SOLD` or `UNSOLD`, moves the receipt
        `VOIDED → DRAFT`, raises `reissue_count` by one, clears `void_reason`, and
        recomputes `claimed_amount_cents`, `form_type`, and `valuation_variant` against the
        donation's current fields."
        PRD §3.8: "It also reopens the donation from `CLOSED` and clears
        `deduction_amount_cents`: the donation returns to `SOLD` when its
        `gross_proceeds_cents` is greater than zero, and to `UNSOLD` when its
        `gross_proceeds_cents` is zero."

        Design: Difficulty/dual_variant_calc/receipt_gross_proceeds_vs_fmv_full_on_one_sold_donation
        """
        bundle = setup_listed_lot(
            with_vehicle=True,
            vehicle_overrides={"base_book_value_cents": 480_000},
            reserve_price_cents=50_000,
        )
        inspect_vehicle(bundle["vehicle"]["id"], odometer_miles=120_000, condition_grade="GOOD")
        sell_lot(bundle["lot"]["id"], bundle["donation"]["id"], 120_000)
        receipt = draft_receipt(bundle["donation"]["id"])
        validate_success(api.issue_receipt(receipt["id"], finance_officer_headers), 200)

        validate_success(
            api.void_receipt(
                receipt["id"],
                {"void_reason": "exception discovered after issue"},
                program_admin_headers,
            ),
            200,
        )
        reopened = read_donation(bundle["donation"]["id"])
        assert reopened["status"] == "SOLD"
        assert reopened["deduction_amount_cents"] is None

        validate_success(
            api.record_exception(
                bundle["donation"]["id"],
                {"exception_type": "MATERIAL_IMPROVEMENT"},
                program_admin_headers,
            ),
            200,
        )
        reissued = validate_success(api.reissue_receipt(receipt["id"], finance_officer_headers), 200)

        assert reissued["valuation_variant"] == "FMV_FULL"
        assert reissued["form_type"] == "FORM_1098C_BOX_4B"
        assert reissued["claimed_amount_cents"] == 346_800
        assert reissued["status"] == "DRAFT"
        assert reissued["reissue_count"] == 1
        assert read_donation(bundle["donation"]["id"])["gross_proceeds_cents"] == 120_000


class TestGrossProceedsThreshold:
    def test_gross_exactly_at_the_threshold_takes_the_safe_harbour_branch(self, api):
        """PRD §3.8: "Otherwise the `FMV_SAFE_HARBOR` rule applies: `valuation_variant` is
        `FMV_SAFE_HARBOR`, `form_type` is `ACKNOWLEDGMENT_ONLY`, and
        `claimed_amount_cents` is the lesser of the donation's `fmv_estimate_cents` and
        fifty thousand cents."
        PRD §3.8: "The comparison in the second rule is strict: gross proceeds landing
        exactly on fifty thousand cents take the safe-harbour branch, not the
        gross-proceeds branch. No rounding occurs in this calculation — both inputs are
        already whole cents."

        Design: Difficulty/boundary_precision_check/receipt_threshold_exactly_500_dollars_takes_safe_harbor_branch
        """
        bundle = setup_sold_donation(
            sale_price_cents=50_000,
            reserve_price_cents=10_000,
            with_vehicle=True,
            vehicle_overrides={"base_book_value_cents": 480_000},
        )
        assert bundle["vehicle"]["fmv_estimate_cents"] == 408_000

        receipt = draft_receipt(bundle["donation"]["id"])

        assert receipt["form_type"] == "ACKNOWLEDGMENT_ONLY"
        assert receipt["valuation_variant"] == "FMV_SAFE_HARBOR"
        assert receipt["claimed_amount_cents"] == 50_000, "the lesser of 408000 and 50000"
        assert read_donation(bundle["donation"]["id"])["net_to_charity_cents"] == 40_000

    def test_gross_one_cent_above_the_threshold_claims_the_hammer_price(self, api):
        """PRD §3.8: "Otherwise, if the donation's `gross_proceeds_cents` is **strictly
        greater than** five hundred dollars (fifty thousand cents), the `GROSS_PROCEEDS`
        rule applies: `valuation_variant` is `GROSS_PROCEEDS`, `form_type` is
        `FORM_1098C_BOX_4A`, and `claimed_amount_cents` is the `gross_proceeds_cents`
        itself, ignoring the fair-market estimate entirely."

        Design: Difficulty/boundary_precision_check/receipt_threshold_exactly_500_dollars_takes_safe_harbor_branch
        """
        bundle = setup_sold_donation(
            sale_price_cents=50_001,
            reserve_price_cents=10_000,
            with_vehicle=True,
            vehicle_overrides={"base_book_value_cents": 480_000},
        )
        assert bundle["vehicle"]["fmv_estimate_cents"] == 408_000

        receipt = draft_receipt(bundle["donation"]["id"])

        assert receipt["form_type"] == "FORM_1098C_BOX_4A"
        assert receipt["valuation_variant"] == "GROSS_PROCEEDS"
        assert receipt["claimed_amount_cents"] == 50_001
        assert read_donation(bundle["donation"]["id"])["net_to_charity_cents"] == 40_001


class TestIndependentAxes:
    def test_withholding_moves_only_the_money_axis(self, api, program_admin_headers):
        """PRD §3.7: "**Withholding a payout**, supplied with a `reason`, drives the money
        axis to `WITHHELD` and is permitted while `payout_status` is either `PENDING` or
        `ACCRUED`; from any other value it is refused with `ERR_INVALID_PAYOUT_STATE`."
        PRD §3.7: "Withholding from `ACCRUED` is a genuine reversal: it requires that the
        donation not already be frozen into a `CLOSED` or `PAID` batch (otherwise
        `ERR_DONATION_SETTLED`), lowers the affiliate's `pledged_balance_cents` by the
        donation's `net_to_charity_cents`, and appends one `REVERSAL` entry as a `DEBIT`
        for that same amount."

        Design: Difficulty/non_linear_state_machine/donation_status_and_payout_axes_advance_independently
        """
        bundle = setup_sold_donation(
            sale_price_cents=120_000, reserve_price_cents=10_000, with_vehicle=True
        )

        withheld = validate_success(
            api.withhold_payout(
                bundle["donation"]["id"],
                {"reason": "donor dispute under review"},
                program_admin_headers,
            ),
            200,
        )

        assert withheld["status"] == "SOLD", "the disposition axis does not move"
        assert withheld["payout_status"] == "WITHHELD"
        assert withheld["net_to_charity_cents"] == 103_100, "the computed net is unchanged"
        assert read_charity(bundle["charity"]["id"])["pledged_balance_cents"] == 0
        reversals = [
            entry for entry in donation_ledger(bundle["donation"]["id"])
            if entry["entry_type"] == "REVERSAL"
        ]
        assert len(reversals) == 1
        assert reversals[0]["direction"] == "DEBIT"
        assert reversals[0]["amount_cents"] == 103_100

    def test_issuing_closes_the_donation_while_the_money_axis_stays_withheld(
        self, api, program_admin_headers, finance_officer_headers
    ):
        """PRD §3.8: "Issuing also closes the donation: it moves `SOLD → CLOSED` or
        `UNSOLD → CLOSED`, copies `claimed_amount_cents` onto the donation's
        `deduction_amount_cents`, and marks every `RECEIPT_DELIVERY` follow-up on that
        donation still `OPEN` or `ESCALATED` as `DONE` with a `resolution_note` of exactly
        `receipt issued`."
        PRD §3.8: "On issue the server mints a sequential `control_number`, stamps
        `issued_at_utc` from the logical clock and `issued_by_user_id` from the acting
        officer's `X-User-ID`, and **recomputes** `claimed_amount_cents`, `form_type`, and
        `valuation_variant` against the donation as it stands at that moment — a draft
        written before an exception was recorded is therefore corrected at issue rather
        than issued stale."
        PRD §3.2: "The money axis ranges over `PENDING`, `ACCRUED`, `REMITTED`, and
        `WITHHELD`, of which `REMITTED` and `WITHHELD` are terminal."

        Design: Difficulty/non_linear_state_machine/donation_status_and_payout_axes_advance_independently
        """
        bundle = setup_sold_donation(
            sale_price_cents=120_000, reserve_price_cents=10_000, with_vehicle=True
        )
        validate_success(
            api.withhold_payout(
                bundle["donation"]["id"],
                {"reason": "donor dispute under review"},
                program_admin_headers,
            ),
            200,
        )

        receipt = draft_receipt(bundle["donation"]["id"])
        issued = validate_success(api.issue_receipt(receipt["id"], finance_officer_headers), 200)

        donation = read_donation(bundle["donation"]["id"])
        assert donation["status"] == "CLOSED"
        assert donation["payout_status"] == "WITHHELD", "the money axis is terminal and unmoved"
        assert donation["net_to_charity_cents"] == 103_100
        assert issued["claimed_amount_cents"] == 120_000
        assert issued["form_type"] == "FORM_1098C_BOX_4A"
        assert issued["issued_by_user_id"] == finance_officer_headers["X-User-ID"]


class TestDraftingPreconditions:
    def test_title_clearance_is_checked_before_the_missing_asset_record(
        self, api, finance_officer_headers
    ):
        """PRD §2.8: "**Title clearance.** A title record exists for the donation and its
        `state` is `CLEARED` — otherwise `ERR_TITLE_NOT_CLEARED` (HTTP 409). This guards
        sale recording, receipt drafting, and receipt issue."
        PRD §2.8: "**Asset record present.** A vehicle row exists for the donation, because
        the receipt's fallback valuation reads its fair-market estimate — otherwise
        `ERR_VEHICLE_RECORD_MISSING` (HTTP 409). This guards receipt drafting."

        Design: Difficulty/priority_pair_validation_conflict/title_compliance_error_beats_missing_vehicle_referential_error
        """
        bundle = setup_dropoff_in_custody(declared_condition="POOR")
        title = new_title(bundle["donation"]["id"], owner_name="Pat Ord")
        validate_success(
            api.submit_title_to_dmv(title["id"], TEST_USERS["title_clerk_headers"]), 200
        )
        venue = new_venue()
        lot = new_lot(bundle["donation"]["id"], venue["id"], reserve_price_cents=90_000)
        validate_success(
            api.record_no_sale(
                lot["id"], {"reason": "no bidders"}, TEST_USERS["auction_manager_headers"]
            ),
            200,
        )

        response = api.create_tax_receipt(
            create_tax_receipt_payload(bundle["donation"]["id"]), finance_officer_headers
        )

        validate_error(response, ApiErrorId.ERR_TITLE_NOT_CLEARED.value)

    def test_the_refused_draft_leaves_the_donation_unsold_and_receiptless(
        self, api, finance_officer_headers
    ):
        """PRD §3.8: "Drafting further requires that the donation already have an asset
        record, since the fallback valuation reads its fair-market estimate — otherwise
        `ERR_VEHICLE_RECORD_MISSING` — and that its title be `CLEARED`."
        PRD §3.6: "**Recording a no-sale.** When the block passes on a lot, the manager
        records the outcome with an optional `reason`. The lot moves `LISTED → NO_SALE` and
        the donation moves `IN_CUSTODY → UNSOLD`."

        Design: Difficulty/priority_pair_validation_conflict/title_compliance_error_beats_missing_vehicle_referential_error
        """
        bundle = setup_dropoff_in_custody(declared_condition="POOR")
        title = new_title(bundle["donation"]["id"], owner_name="Pat Ord")
        validate_success(
            api.submit_title_to_dmv(title["id"], TEST_USERS["title_clerk_headers"]), 200
        )
        venue = new_venue()
        lot = new_lot(bundle["donation"]["id"], venue["id"], reserve_price_cents=90_000)
        validate_success(
            api.record_no_sale(
                lot["id"], {"reason": "no bidders"}, TEST_USERS["auction_manager_headers"]
            ),
            200,
        )

        refused = api.create_tax_receipt(
            create_tax_receipt_payload(bundle["donation"]["id"]), finance_officer_headers
        )
        validate_error(refused, ApiErrorId.ERR_TITLE_NOT_CLEARED.value)

        donation = read_donation(bundle["donation"]["id"])
        assert donation["status"] == "UNSOLD"
        assert donation["deduction_amount_cents"] is None
        rows, meta = validate_paginated(
            api.list_tax_receipts(
                finance_officer_headers, params={"donation_id": bundle["donation"]["id"]}
            )
        )
        assert rows == [] and meta["total_count"] == 0
        assert read_title(title["id"])["state"] == "SUBMITTED"

    def test_a_second_draft_while_one_is_active_is_refused(self, api, finance_officer_headers):
        """PRD §3.8: "A donation may hold at most one receipt that is not voided; a second
        attempt while one sits in `DRAFT` or `ISSUED` is refused with
        `ERR_RECEIPT_ALREADY_ACTIVE`."

        Design: Corner/errors/corner_receipt_draft_while_another_receipt_is_active_is_refused
        """
        bundle = setup_sold_donation(
            sale_price_cents=60_000, reserve_price_cents=1_000, with_vehicle=True
        )
        first = draft_receipt(bundle["donation"]["id"])

        response = api.create_tax_receipt(
            create_tax_receipt_payload(bundle["donation"]["id"]), finance_officer_headers
        )

        validate_error(response, ApiErrorId.ERR_RECEIPT_ALREADY_ACTIVE.value)
        rows, _ = validate_paginated(
            api.list_tax_receipts(
                finance_officer_headers, params={"donation_id": bundle["donation"]["id"]}
            )
        )
        assert len(rows) == 1
        stored = read_receipt(first["id"])
        assert stored["status"] == "DRAFT"
        assert stored["claimed_amount_cents"] == 60_000
        assert stored["form_type"] == "FORM_1098C_BOX_4A"


class TestEntitySpecificStateErrors:
    def test_state_errors_name_the_entity_that_blocked_the_call(
        self, api, title_clerk_headers, finance_officer_headers
    ):
        """PRD §3.4: "A decision recorded against a record that is not `SUBMITTED` is
        refused with `ERR_INVALID_TITLE_STATE`."
        PRD §3.4: "Resubmission moves the record `REJECTED → SUBMITTED`, re-mints
        `dmv_filing_reference`, restamps `submitted_at_utc`, and may optionally correct the
        `title_number` or the `owner_name` in the same call."
        PRD §3.8: "The receipt cycle `DRAFT → ISSUED → VOIDED → DRAFT` has no terminal
        state; a receipt acted on from a state that does not admit the act is refused with
        `ERR_INVALID_RECEIPT_STATE`."

        Design: Corner/errors/corner_title_and_receipt_state_errors_are_entity_specific
        """
        charity = new_charity(name="State Trust")
        donor = new_donor(full_name="Sta Err")
        bundle = setup_dropoff_in_custody(charity=charity, donor=donor)
        new_vehicle(bundle["donation"]["id"], base_book_value_cents=480_000)
        title = new_title(bundle["donation"]["id"], owner_name="Sta Err")

        early_resubmit = api.resubmit_title(
            title["id"], {"owner_name": "Sta Err"}, title_clerk_headers
        )
        validate_error(early_resubmit, ApiErrorId.ERR_INVALID_TITLE_STATE.value)
        still_draft = read_title(title["id"])
        assert still_draft["state"] == "DRAFT"
        assert still_draft["rejection_count"] == 0

        validate_success(api.submit_title_to_dmv(title["id"], title_clerk_headers), 200)
        validate_success(
            api.record_dmv_decision(title["id"], {"outcome": "CLEARED"}, title_clerk_headers), 200
        )
        venue = new_venue()
        lot = new_lot(bundle["donation"]["id"], venue["id"], reserve_price_cents=1_000)
        sell_lot(lot["id"], bundle["donation"]["id"], 60_000)
        receipt = draft_receipt(bundle["donation"]["id"])
        validate_success(api.issue_receipt(receipt["id"], finance_officer_headers), 200)

        second_issue = api.issue_receipt(receipt["id"], finance_officer_headers)
        validate_error(second_issue, ApiErrorId.ERR_INVALID_RECEIPT_STATE.value)

        stored = read_receipt(receipt["id"])
        assert stored["status"] == "ISSUED"
        assert stored["claimed_amount_cents"] == 60_000
        donation = read_donation(bundle["donation"]["id"])
        assert donation["status"] == "CLOSED"
        assert donation["deduction_amount_cents"] == 60_000

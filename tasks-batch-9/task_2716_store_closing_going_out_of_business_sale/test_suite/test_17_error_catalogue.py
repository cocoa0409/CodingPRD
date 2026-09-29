"""Error reachability: every catalogued refusal reached on a real request.

Each case builds the state in which one guard genuinely bites, checks the error
id and HTTP status the contract names for it, and then reads the affected rows
back to prove the refusal wrote nothing.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_employee,
    add_inventory_lot,
    add_markdown_stage,
    add_store,
    api_client,
    assert_instant_equals,
    assert_lease_disposition,
    assert_settlement,
    assert_surrender_waterfall_invariants,
    accept_settlement,
    activate_markdown_stage,
    checkpoint_markdown_stage,
    close_store,
    consignment_payload,
    create_engagement,
    create_jurisdiction,
    employee_payload,
    engagement_version,
    file_consignment_disclosure,
    gob_license_payload,
    make_compliance_headers,
    make_consultant_headers,
    make_controller_headers,
    make_store_manager_headers,
    markdown_stage_payload,
    open_lease_disposition,
    pin_clock,
    propose_consignment,
    propose_settlement,
    read_engagement,
    read_store,
    receive_consignment,
    record_landlord_response,
    revoke_license,
    run_compliance_sweep,
    run_employment_action,
    sales_day_payload,
    send_lease_offer,
    settlement_payload,
    setup_selling_engagement,
    setup_selling_store,
    store_payload,
    store_version,
    surrender_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "augmentation_prohibited": False, "prohibited_claim_codes": [],
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
MA_RULES = dict(
    NY_RULES, code="MA", name="Massachusetts", augmentation_prohibited=True,
)
CA_RULES = dict(
    NY_RULES, code="CA", name="California", license_cooling_off_days=0,
    advertising_disclosure_required=True,
)
APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}
LICENSE_PERIOD = {
    "period_start_date": "2026-09-15", "period_end_date": "2026-10-14",
}
KESTREL_LEASE = {
    "landlord_name": "Kestrel Realty",
    "surrender_deadline_date": "2026-12-01",
    "daily_holdover_rate_cents": 25000,
    "rent_arrears_cents": 400000,
    "cam_arrears_cents": 150000,
    "restoration_cost_cents": 600000,
    "fixture_reserve_price_cents": 500000,
    "surrender_credit_cents": 0,
}
FIRST_STAGE = {
    "stage_index": 1, "discount_pct": 0.2, "sell_through_target_pct": 0.25,
    "window_start_date": "2026-09-16", "window_end_date": "2026-10-01",
}
SECOND_STAGE = {
    "stage_index": 2, "discount_pct": 0.3, "sell_through_target_pct": 0.5,
    "window_start_date": "2026-10-01", "window_end_date": "2026-10-14",
}
FIFTY_APPAREL_UNITS = {
    "supplier_name": "Northgate Supply", "category": "APPAREL",
    "units_supplied": 50, "unit_cost_cents": 2000, "unit_retail_cents": 5000,
    "delivery_window_start_date": "2026-09-16",
    "delivery_window_end_date": "2026-09-20",
}


def _selling_store(store_code, license_number, jurisdiction_overrides=None,
                   lot_overrides=None):
    """One licensed SELLING store carrying a thousand original apparel units."""
    return setup_selling_store(
        jurisdiction_overrides=jurisdiction_overrides or NY_RULES,
        store_overrides={
            "store_code": store_code,
            "address_line": f"{store_code} Liquidation Row",
        },
        lot_overrides=lot_overrides or APPAREL_LOT,
        license_overrides=dict(
            LICENSE_PERIOD, license_number=license_number,
            advertising_claim_codes=["EVERYTHING_MUST_GO"],
        ),
    )


def _agreed_lease_on_a_closed_store(store_code, license_number):
    """A Kestrel lease agreed on 2026-09-15 over a store that has since closed."""
    scenario = _selling_store(store_code, license_number)
    store_id = scenario["store"]["id"]
    disposition = open_lease_disposition(store_id, **KESTREL_LEASE)
    send_lease_offer(disposition["id"], 300000)
    disposition = record_landlord_response(disposition["id"], "ACCEPT")
    close_store(store_id)
    return scenario, disposition


def _surrender_raw(disposition_id, fixture_sale_price_cents, **extra):
    payload = {"fixture_sale_price_cents": fixture_sale_price_cents}
    payload.update(extra)
    return api_client.surrender_lease(
        disposition_id, payload, make_consultant_headers()
    )


class TestSurrenderGuardsFireNoticeThenReserveThenState:
    def test_five_days_of_notice_falls_short_of_the_ten_the_jurisdiction_demands(self):
        """The landlord agreed on the fifteenth and the clock reads the twentieth.

        The PRD says: "And the notice period must be honoured: the days elapsed from
        `landlord_agreed_date` to the current logical-clock date must be at least the
        store's jurisdiction's `surrender_notice_days`, otherwise
        `ERR_SURRENDER_NOTICE_SHORT`."

        Design: Corner/errors/surrender_errors_notice_then_reserve_then_terminal_state
        """
        _scenario, disposition = _agreed_lease_on_a_closed_store(
            "S-6001", "NY-GOB-6001"
        )
        assert disposition["landlord_agreed_date"] == "2026-09-15"
        pin_clock("2026-09-20T00:00:00Z")
        response = _surrender_raw(disposition["id"], 600000)
        validate_error(
            response, ApiErrorId.ERR_SURRENDER_NOTICE_SHORT.value, 409
        )
        still_agreed = validate_success(
            api_client.get_lease_disposition(
                disposition["id"], make_consultant_headers()
            )
        )
        assert still_agreed["disposition_status"] == "AGREED"
        assert still_agreed["surrendered_at"] is None

    def test_at_exactly_ten_days_the_notice_passes_and_the_reserve_bites(self):
        """A 400,000 price against a 500,000 reserve is the next failure, not the notice.

        The PRD says: "The `fixture_sale_price_cents` must be at least the
        `fixture_reserve_price_cents` unless `reserve_waived` is exactly true, otherwise
        `ERR_FIXTURE_BELOW_RESERVE`; the waiver is the deliberate escape hatch for a
        fixture package nobody will pay the reserve for."

        Design: Corner/errors/surrender_errors_notice_then_reserve_then_terminal_state
        """
        _scenario, disposition = _agreed_lease_on_a_closed_store(
            "S-6001", "NY-GOB-6001"
        )
        pin_clock("2026-09-25T00:00:00Z")
        response = _surrender_raw(disposition["id"], 400000)
        error = validate_error(
            response, ApiErrorId.ERR_FIXTURE_BELOW_RESERVE.value, 422
        )
        assert error["error_id"] != ApiErrorId.ERR_SURRENDER_NOTICE_SHORT.value

    def test_the_waiver_lets_the_below_reserve_price_through_and_runs_the_waterfall(self):
        """Four hundred thousand of funds is swallowed whole by the rent bucket.

        The PRD says: "Those funds are poured into exactly four buckets in a fixed
        order that must not be reordered: first the rent arrears, second the CAM
        arrears, third the restoration cost, and fourth the holdover penalty."

        Design: Corner/errors/surrender_errors_notice_then_reserve_then_terminal_state
        """
        scenario, disposition = _agreed_lease_on_a_closed_store(
            "S-6001", "NY-GOB-6001"
        )
        pin_clock("2026-09-25T00:00:00Z")
        surrendered = validate_success(
            _surrender_raw(disposition["id"], 400000, reserve_waived=True)
        )
        assert_lease_disposition(surrendered)
        assert surrendered["disposition_status"] == "SURRENDERED"
        assert surrendered["holdover_days"] == 0
        assert surrendered["holdover_penalty_cents"] == 0
        assert surrendered["allocated_rent_cents"] == 400000
        assert surrendered["allocated_cam_cents"] == 0
        assert surrendered["allocated_restoration_cents"] == 0
        assert surrendered["allocated_holdover_cents"] == 0
        assert surrendered["unpaid_landlord_balance_cents"] == 750000
        assert surrendered["residual_to_retailer_cents"] == 0
        assert_surrender_waterfall_invariants(surrendered)
        assert read_store(scenario["store"]["id"])["store_status"] == "SURRENDERED"

    def test_a_second_surrender_on_a_surrendered_disposition_is_a_state_violation(self):
        """The terminal reading has no surrender transition left to take.

        The PRD says: "The disposition must be `AGREED`, otherwise
        `ERR_LEASE_STATE_INVALID`."

        Design: Corner/errors/surrender_errors_notice_then_reserve_then_terminal_state
        """
        _scenario, disposition = _agreed_lease_on_a_closed_store(
            "S-6001", "NY-GOB-6001"
        )
        pin_clock("2026-09-25T00:00:00Z")
        surrender_lease(disposition["id"], 400000, reserve_waived=True)
        response = _surrender_raw(disposition["id"], 400000, reserve_waived=True)
        validate_error(response, ApiErrorId.ERR_LEASE_STATE_INVALID.value, 409)


def _active_engagement_with_one_selling_store():
    """One licensed SELLING store on an ACTIVE engagement, nothing yet posted."""
    scenario = _selling_store("S-6002", "NY-GOB-6002")
    assert scenario["engagement"]["engagement_status"] == "ACTIVE"
    return scenario["engagement"]["id"]


def _create_settlement_raw(engagement_id, expected_engagement_version, **extra):
    return api_client.create_settlement(
        engagement_id,
        settlement_payload(expected_engagement_version, **extra),
        make_consultant_headers(),
    )


def _read_settlement(settlement_id):
    return validate_success(
        api_client.get_settlement(settlement_id, make_consultant_headers())
    )


class TestSettlementBasisAndOpenWorksheetGuards:
    def test_a_final_worksheet_cannot_be_opened_while_the_engagement_is_active(self):
        """FINAL is the closing document and the engagement has not wound down.

        The PRD says: "A `PROVISIONAL` worksheet is an interim look at the books and may
        be opened while the engagement is `ACTIVE`; a `FINAL` worksheet is the closing
        document and may only be opened once the engagement has reached `WIND_DOWN`,
        with a premature attempt refused as `ERR_SETTLEMENT_BASIS_INVALID`."

        Design: Corner/errors/settlement_basis_and_open_worksheet_errors_are_both_reachable
        """
        engagement_id = _active_engagement_with_one_selling_store()
        response = _create_settlement_raw(
            engagement_id, engagement_version(engagement_id),
            settlement_basis="FINAL",
        )
        validate_error(
            response, ApiErrorId.ERR_SETTLEMENT_BASIS_INVALID.value, 409
        )
        _rows, meta = validate_paginated(
            api_client.list_settlements(engagement_id, make_consultant_headers())
        )
        assert meta["total_count"] == 0

    def test_the_provisional_worksheet_opens_in_draft_with_no_split_written(self):
        """An interim look at the books is admissible while the sale is running.

        The PRD says: "A new worksheet opens at `settlement_status` of `DRAFT` with every
        split figure unset, and the create increments the engagement's `version` — which
        is exactly why a second create replaying the same `expected_engagement_version`
        fails the version pin."

        Design: Corner/errors/settlement_basis_and_open_worksheet_errors_are_both_reachable
        """
        engagement_id = _active_engagement_with_one_selling_store()
        before = engagement_version(engagement_id)
        worksheet = validate_success(
            _create_settlement_raw(engagement_id, before), 201
        )
        assert worksheet["settlement_basis"] == "PROVISIONAL"
        assert worksheet["settlement_status"] == "DRAFT"
        assert worksheet["computed_at"] is None
        assert worksheet["proposed_by_user_id"] is None
        assert engagement_version(engagement_id) == before + 1

    def test_a_second_open_worksheet_is_refused_without_the_supersede_flag(self):
        """The incumbent DRAFT worksheet holds the only open slot.

        The PRD says: "At most one worksheet per engagement may be open at a time:
        creating one while an incumbent sits in `DRAFT`, `PROPOSED`, or `DISPUTED`
        requires `supersede_open` to be exactly true, which drives the incumbent to
        `SUPERSEDED`; without the flag the request is refused with
        `ERR_SETTLEMENT_ALREADY_OPEN`, and an incumbent already in `ACCEPTED` is refused
        even with the flag, because `ACCEPTED` has no transition to `SUPERSEDED` and an
        accepted settlement may only move forward to `FINALIZED`."

        Design: Corner/errors/settlement_basis_and_open_worksheet_errors_are_both_reachable
        """
        engagement_id = _active_engagement_with_one_selling_store()
        first = validate_success(
            _create_settlement_raw(engagement_id, engagement_version(engagement_id)),
            201,
        )
        response = _create_settlement_raw(
            engagement_id, engagement_version(engagement_id)
        )
        validate_error(
            response, ApiErrorId.ERR_SETTLEMENT_ALREADY_OPEN.value, 409
        )
        assert _read_settlement(first["id"])["settlement_status"] == "DRAFT"

    def test_the_flagged_retry_drives_the_incumbent_to_superseded(self):
        """One flag turns the refusal into an accepted create and retires the incumbent.

        The PRD says: "At most one worksheet per engagement may be open at a time:
        creating one while an incumbent sits in `DRAFT`, `PROPOSED`, or `DISPUTED`
        requires `supersede_open` to be exactly true, which drives the incumbent to
        `SUPERSEDED`; without the flag the request is refused with
        `ERR_SETTLEMENT_ALREADY_OPEN`, and an incumbent already in `ACCEPTED` is refused
        even with the flag, because `ACCEPTED` has no transition to `SUPERSEDED` and an
        accepted settlement may only move forward to `FINALIZED`."

        Design: Corner/errors/settlement_basis_and_open_worksheet_errors_are_both_reachable
        """
        engagement_id = _active_engagement_with_one_selling_store()
        first = validate_success(
            _create_settlement_raw(engagement_id, engagement_version(engagement_id)),
            201,
        )
        second = validate_success(
            _create_settlement_raw(
                engagement_id, engagement_version(engagement_id),
                supersede_open=True,
            ),
            201,
        )
        assert second["id"] != first["id"]
        assert second["settlement_status"] == "DRAFT"
        assert _read_settlement(first["id"])["settlement_status"] == "SUPERSEDED"

    def test_a_provisional_worksheet_computes_a_zero_split_at_the_lowest_fee_band(self):
        """No selling day was posted, so the ratio denominator decides nothing.

        The PRD says: "The `fee_rate` is then selected from the ratio by a three-band
        tier table: a ratio below 0.60 draws 0.0200, a ratio from 0.60 up to but
        excluding 0.80 draws 0.0350, and a ratio of 0.80 or more draws 0.0500."

        Design: Corner/errors/settlement_basis_and_open_worksheet_errors_are_both_reachable
        """
        engagement_id = _active_engagement_with_one_selling_store()
        worksheet = validate_success(
            _create_settlement_raw(engagement_id, engagement_version(engagement_id)),
            201,
        )
        proposed = propose_settlement(worksheet["id"])
        assert_settlement(proposed)
        assert proposed["settlement_status"] == "PROPOSED"
        assert proposed["gross_recovery_cents"] == 0
        assert proposed["recovery_ratio"] == pytest.approx(0.0000, abs=0.00001)
        assert proposed["fee_rate"] == pytest.approx(0.0200, abs=0.00001)
        assert proposed["liquidator_fee_cents"] == 0

    def test_an_accepted_provisional_worksheet_still_cannot_be_finalized(self):
        """The basis guard outlives the state machine: PROVISIONAL is a dead end.

        The PRD says: "The worksheet's basis must be `FINAL`, otherwise
        `ERR_SETTLEMENT_BASIS_INVALID` — a `PROVISIONAL` worksheet may be proposed,
        disputed, re-proposed, and even accepted, but it can never be finalized, and it
        is a permanent dead end whose only other exit is being superseded."

        Design: Corner/errors/settlement_basis_and_open_worksheet_errors_are_both_reachable
        """
        engagement_id = _active_engagement_with_one_selling_store()
        worksheet = validate_success(
            _create_settlement_raw(engagement_id, engagement_version(engagement_id)),
            201,
        )
        propose_settlement(worksheet["id"])
        accepted = accept_settlement(worksheet["id"])
        assert accepted["settlement_status"] == "ACCEPTED"
        response = api_client.finalize_settlement(
            worksheet["id"], make_consultant_headers()
        )
        validate_error(
            response, ApiErrorId.ERR_SETTLEMENT_BASIS_INVALID.value, 409
        )
        assert _read_settlement(worksheet["id"])["settlement_status"] == "ACCEPTED"
        assert read_engagement(engagement_id)["engagement_status"] == "ACTIVE"


def _propose_raw(store_id, **overrides):
    return api_client.create_augmentation_consignment(
        store_id, consignment_payload(**overrides), make_consultant_headers()
    )


class TestAugmentationProhibitedJurisdictionRefusesTheProposal:
    def test_the_proposal_is_refused_outright_and_no_consignment_row_survives(self):
        """Massachusetts bans the practice, so nothing may even be offered.

        The PRD says: "A jurisdiction that has set `augmentation_prohibited` forbids the
        practice outright, and a proposal for a store there is refused with
        `ERR_AUGMENTATION_PROHIBITED` — nothing may even be offered."

        Design: Corner/errors/augmentation_prohibited_jurisdiction_refuses_the_proposal_outright
        """
        scenario = _selling_store(
            "S-6003", "MA-GOB-6003", jurisdiction_overrides=MA_RULES
        )
        store_id = scenario["store"]["id"]
        response = _propose_raw(store_id, **FIFTY_APPAREL_UNITS)
        validate_error(response, ApiErrorId.ERR_AUGMENTATION_PROHIBITED.value, 409)
        _rows, meta = validate_paginated(
            api_client.list_augmentation_consignments(
                store_id, make_consultant_headers()
            )
        )
        assert meta["total_count"] == 0

    def test_the_store_augmentation_aggregates_never_move(self):
        """The block lands at proposal time, so the cap and the ledger never engage.

        The PRD says: "A jurisdiction that has set `augmentation_prohibited` forbids the
        practice outright, and a proposal for a store there is refused with
        `ERR_AUGMENTATION_PROHIBITED` — nothing may even be offered."

        Design: Corner/errors/augmentation_prohibited_jurisdiction_refuses_the_proposal_outright
        """
        scenario = _selling_store(
            "S-6003", "MA-GOB-6003", jurisdiction_overrides=MA_RULES
        )
        store_id = scenario["store"]["id"]
        _propose_raw(store_id, **FIFTY_APPAREL_UNITS)
        store = read_store(store_id)
        assert store["augmentation_cost_value_cents"] == 0
        assert store["augmentation_units_accounted"] == 0
        assert store["original_cost_value_cents"] == 2000000
        assert store["units_initial_total"] == 1000


def _two_license_pending_california_stores():
    """A CA engagement approved into two stores that both await a licence."""
    scenario = setup_selling_engagement(
        store_specs=[
            {
                "store": {
                    "store_code": "S-6004A",
                    "address_line": "S-6004A Liquidation Row",
                },
                "lots": [APPAREL_LOT],
            },
            {
                "store": {
                    "store_code": "S-6004B",
                    "address_line": "S-6004B Liquidation Row",
                },
                "lots": [APPAREL_LOT],
            },
        ],
        jurisdiction_overrides=CA_RULES,
        license_each=False,
    )
    for store in scenario["stores"]:
        assert store["store_status"] == "LICENSE_PENDING"
    return scenario["stores"]


def _apply_raw(store_id, **overrides):
    return api_client.create_gob_license(
        store_id, gob_license_payload(**overrides), make_compliance_headers()
    )


class TestAdvertisingDisclosureIsKeyedOnTheClaimCodes:
    def test_a_price_comparison_claim_alone_is_refused(self):
        """BELOW_COST without the disclosure code cannot be advertised in California.

        The PRD says: "Second, where the jurisdiction sets
        `advertising_disclosure_required`, an application that declares either of the two
        price-comparison claims — exactly `BELOW_COST` and `LOWEST_PRICES_EVER`, and no
        others — must also declare `AUGMENTED_MERCHANDISE_DISCLOSURE`, failing which it
        is refused with `ERR_ADVERTISING_DISCLOSURE_REQUIRED`; applications that declare
        neither of those two codes are unaffected by this rule whatever else they claim."

        Design: Corner/errors/advertising_disclosure_is_required_only_for_price_comparison_claims
        """
        store_a, _store_b = _two_license_pending_california_stores()
        response = _apply_raw(
            store_a["id"], license_number="CA-GOB-6004-A",
            advertising_claim_codes=["BELOW_COST"], **LICENSE_PERIOD,
        )
        validate_error(
            response, ApiErrorId.ERR_ADVERTISING_DISCLOSURE_REQUIRED.value, 409
        )
        _rows, meta = validate_paginated(
            api_client.list_gob_licenses(store_a["id"], make_compliance_headers())
        )
        assert meta["total_count"] == 0

    def test_the_same_application_carrying_the_disclosure_is_accepted(self):
        """One extra code satisfies the rule and the application is stored as APPLIED.

        The PRD says: "Second, where the jurisdiction sets
        `advertising_disclosure_required`, an application that declares either of the two
        price-comparison claims — exactly `BELOW_COST` and `LOWEST_PRICES_EVER`, and no
        others — must also declare `AUGMENTED_MERCHANDISE_DISCLOSURE`, failing which it
        is refused with `ERR_ADVERTISING_DISCLOSURE_REQUIRED`; applications that declare
        neither of those two codes are unaffected by this rule whatever else they claim."

        Design: Corner/errors/advertising_disclosure_is_required_only_for_price_comparison_claims
        """
        store_a, _store_b = _two_license_pending_california_stores()
        _apply_raw(
            store_a["id"], license_number="CA-GOB-6004-A",
            advertising_claim_codes=["BELOW_COST"], **LICENSE_PERIOD,
        )
        license_row = validate_success(
            _apply_raw(
                store_a["id"], license_number="CA-GOB-6004-B",
                advertising_claim_codes=[
                    "BELOW_COST", "AUGMENTED_MERCHANDISE_DISCLOSURE",
                ],
                **LICENSE_PERIOD,
            ),
            201,
        )
        assert license_row["license_status"] == "APPLIED"
        assert license_row["license_number"] == "CA-GOB-6004-B"
        assert license_row["requested_days"] == 30
        _rows, meta = validate_paginated(
            api_client.list_gob_licenses(store_a["id"], make_compliance_headers())
        )
        assert meta["total_count"] == 1

    def test_a_non_comparative_claim_is_untouched_by_the_rule(self):
        """FINAL_DAYS compares no prices, so the same jurisdiction lets it through bare.

        The PRD says: "Second, where the jurisdiction sets
        `advertising_disclosure_required`, an application that declares either of the two
        price-comparison claims — exactly `BELOW_COST` and `LOWEST_PRICES_EVER`, and no
        others — must also declare `AUGMENTED_MERCHANDISE_DISCLOSURE`, failing which it
        is refused with `ERR_ADVERTISING_DISCLOSURE_REQUIRED`; applications that declare
        neither of those two codes are unaffected by this rule whatever else they claim."

        Design: Corner/errors/advertising_disclosure_is_required_only_for_price_comparison_claims
        """
        _store_a, store_b = _two_license_pending_california_stores()
        license_row = validate_success(
            _apply_raw(
                store_b["id"], license_number="CA-GOB-6004-C",
                advertising_claim_codes=["FINAL_DAYS"], **LICENSE_PERIOD,
            ),
            201,
        )
        assert license_row["license_status"] == "APPLIED"
        assert license_row["advertising_claim_codes"] == ["FINAL_DAYS"]


def _store_with_stage_one_active_and_stage_two_armed():
    """A licensed store whose first stage is running and whose second is armed."""
    scenario = _selling_store("S-6005", "NY-GOB-6005")
    store_id = scenario["store"]["id"]
    first = add_markdown_stage(store_id, **FIRST_STAGE)
    first = activate_markdown_stage(first["id"])
    assert first["stage_status"] == "ACTIVE"
    second = add_markdown_stage(store_id, **SECOND_STAGE)
    assert second["stage_status"] == "ARMED"
    return store_id, first, second


def _read_stage(stage_id):
    return validate_success(
        api_client.get_markdown_stage(stage_id, make_consultant_headers())
    )


class TestOnlyOneMarkdownStageMayBeActivePerStore:
    def test_the_second_activation_is_blocked_by_its_running_sibling(self):
        """Stage two is validly armed with a covered window and is still refused.

        The PRD says: "And no other stage of the store may already be `ACTIVE`, otherwise
        `ERR_STAGE_ALREADY_ACTIVE`."

        Design: Corner/errors/only_one_markdown_stage_may_be_active_per_store
        """
        _store_id, _first, second = _store_with_stage_one_active_and_stage_two_armed()
        response = api_client.activate_markdown_stage(
            second["id"], make_consultant_headers()
        )
        validate_error(response, ApiErrorId.ERR_STAGE_ALREADY_ACTIVE.value, 409)
        read_back = _read_stage(second["id"])
        assert read_back["stage_status"] == "ARMED"
        assert read_back["activated_at"] is None

    def test_both_stages_stay_in_the_planned_set_after_the_refusal(self):
        """Twenty and thirty percent still average to a planned quarter.

        The PRD says: "Activation does not move `planned_avg_discount_pct`, since `ARMED`
        and `ACTIVE` stages both belong to the planned set; the stage's `version`
        increments by 1."

        Design: Corner/errors/only_one_markdown_stage_may_be_active_per_store
        """
        store_id, first, second = _store_with_stage_one_active_and_stage_two_armed()
        api_client.activate_markdown_stage(second["id"], make_consultant_headers())
        assert _read_stage(first["id"])["stage_status"] == "ACTIVE"
        store = read_store(store_id)
        assert store["planned_avg_discount_pct"] == pytest.approx(
            0.2500, abs=0.00001
        )
        _rows, meta = validate_paginated(
            api_client.list_markdown_stages(store_id, make_consultant_headers())
        )
        assert meta["total_count"] == 2


def _file_raw(store_id, headers, **overrides):
    return api_client.create_sales_day(
        store_id, sales_day_payload(**overrides), headers
    )


class TestSalesDayMoneyAndUnitGuardsRejectTheWholePosting:
    def test_augmentation_money_without_augmentation_units_is_refused_at_filing(self):
        """Five thousand cents of augmentation revenue against zero augmentation units.

        The PRD says: "And the totals must cohere: `net_sales_cents` must equal
        `original_net_sales_cents` plus `augmentation_net_sales_cents`, and
        `augmentation_net_sales_cents` must be 0 whenever `augmentation_units_sold` is 0,
        because augmentation money cannot arise from no augmentation units; either fault
        is refused as `ERR_SALES_TOTALS_INCONSISTENT`."

        Design: Corner/errors/sales_day_money_and_unit_guards_reject_the_whole_posting
        """
        scenario = _selling_store("S-6006", "NY-GOB-6006")
        store_id = scenario["store"]["id"]
        headers = make_store_manager_headers(store_id)
        response = _file_raw(
            store_id, headers, business_date="2026-09-15",
            original_net_sales_cents=100000, augmentation_net_sales_cents=5000,
            original_units_sold=40, augmentation_units_sold=0,
        )
        validate_error(
            response, ApiErrorId.ERR_SALES_TOTALS_INCONSISTENT.value, 422
        )
        _rows, meta = validate_paginated(
            api_client.list_sales_days(store_id, headers)
        )
        assert meta["total_count"] == 0

    def test_an_over_sold_unit_count_survives_the_filing_untouched(self):
        """Twelve hundred units against a thousand on hand is stored, not judged.

        The PRD says: "Filing moves no inventory and no ledger figure whatsoever —
        nothing happens to units or money until the retailer posts the day."

        Design: Corner/errors/sales_day_money_and_unit_guards_reject_the_whole_posting
        """
        scenario = _selling_store("S-6006", "NY-GOB-6006")
        store_id = scenario["store"]["id"]
        headers = make_store_manager_headers(store_id)
        day = validate_success(
            _file_raw(
                store_id, headers, business_date="2026-09-15",
                original_net_sales_cents=500000, augmentation_net_sales_cents=0,
                original_units_sold=1200, augmentation_units_sold=0,
            ),
            201,
        )
        assert day["day_status"] == "PENDING_REVIEW"
        assert day["net_sales_cents"] == 500000
        assert day["original_units_sold"] == 1200
        lots, _lot_meta = validate_paginated(
            api_client.list_inventory_lots(store_id, make_consultant_headers())
        )
        assert lots[0]["units_on_hand"] == 1000
        assert lots[0]["units_sold"] == 0

    def test_the_posting_is_refused_whole_with_no_partial_lot_writes(self):
        """The capacity test runs before any lot is touched, so nothing moves.

        The PRD says: "A shortfall on either side refuses the entire request with
        `ERR_UNITS_EXCEED_ON_HAND`, leaving zero partial writes — there is no such thing
        as a half-posted day."

        Design: Corner/errors/sales_day_money_and_unit_guards_reject_the_whole_posting
        """
        scenario = _selling_store("S-6006", "NY-GOB-6006")
        store_id = scenario["store"]["id"]
        manager = make_store_manager_headers(store_id)
        day = validate_success(
            _file_raw(
                store_id, manager, business_date="2026-09-15",
                original_net_sales_cents=500000, augmentation_net_sales_cents=0,
                original_units_sold=1200, augmentation_units_sold=0,
            ),
            201,
        )
        response = api_client.review_sales_day(
            day["id"], {"decision": "POST"}, make_controller_headers()
        )
        validate_error(response, ApiErrorId.ERR_UNITS_EXCEED_ON_HAND.value, 422)
        rows, _meta = validate_paginated(
            api_client.list_inventory_lots(store_id, make_consultant_headers())
        )
        assert len(rows) == 1
        assert rows[0]["units_on_hand"] == 1000
        assert rows[0]["units_sold"] == 0
        assert rows[0]["lot_status"] == "ON_FLOOR"
        days, _day_meta = validate_paginated(
            api_client.list_sales_days(store_id, manager)
        )
        assert days[0]["day_status"] == "PENDING_REVIEW"
        assert read_store(store_id)["realized_gross_recovery_cents"] == 0


def _engagement_with_store_6008_and_one_employee():
    """One NY jurisdiction, an engagement holding S-6008, and EMP-A on that store."""
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement()
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-6008", address_line="S-6008 Liquidation Row",
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    add_employee(
        store["id"], employee_code="EMP-A", retention_bonus_cents=100000,
        retention_start_date="2026-09-15", retention_target_date="2026-11-15",
        attendance_rate=0.95,
    )
    return jurisdiction, engagement, store


class TestDuplicateNaturalKeysAreRefusedWithinTheirDeclaredScope:
    def test_a_repeat_jurisdiction_code_is_refused_globally(self):
        """The code is the jurisdiction's global identity, whatever name follows it.

        The PRD says: "A `ComplianceOfficer` registers each jurisdiction whose
        going-out-of-business rules will govern a closing store, supplying a short `code`
        of two to eight uppercase characters that must be globally unique — a second
        registration of the same code is refused with `ERR_DUPLICATE_JURISDICTION_CODE` —
        together with a human-readable `name` and the rule set itself."

        Design: Corner/errors/duplicate_natural_keys_are_refused_within_their_declared_scope
        """
        _jurisdiction, _engagement, _store = _engagement_with_store_6008_and_one_employee()
        response = api_client.create_jurisdiction(
            dict(NY_RULES, name="New York duplicate"), make_compliance_headers()
        )
        validate_error(
            response, ApiErrorId.ERR_DUPLICATE_JURISDICTION_CODE.value, 409
        )

    def test_a_repeat_store_code_inside_one_engagement_is_refused(self):
        """S-6008 is already taken under this engagement, address notwithstanding.

        The PRD says: "A store carries the `engagement_id` of the engagement it was added
        under, the `jurisdiction_id` of the jurisdiction whose rules govern it, the
        retailer's own `store_code` — which must be unique within that engagement, a
        repeat drawing `ERR_DUPLICATE_STORE_CODE` — and the street `address_line` of the
        closing location."

        Design: Corner/errors/duplicate_natural_keys_are_refused_within_their_declared_scope
        """
        jurisdiction, engagement, _store = _engagement_with_store_6008_and_one_employee()
        response = api_client.create_store(
            engagement["id"],
            store_payload(
                jurisdiction["id"], store_code="S-6008", address_line="9 Twin Rd"
            ),
            make_consultant_headers(),
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_STORE_CODE.value, 409)
        _rows, meta = validate_paginated(
            api_client.list_stores(
                make_consultant_headers(),
                params={"engagement_id": engagement["id"]},
            )
        )
        assert meta["total_count"] == 1

    def test_a_repeat_employee_code_inside_one_store_is_refused(self):
        """The payroll code is unique per store, so EMP-A cannot be enrolled twice.

        The PRD says: "An enrolment declares the payroll `employee_code`, which must be
        unique within the store — a repeat draws `ERR_DUPLICATE_EMPLOYEE_CODE` — the
        `retention_bonus_cents` offered for staying to the target date (at least 0), the
        `retention_start_date` from which service is counted, the `retention_target_date`
        through which it is counted, which may not precede the start, and the
        `attendance_rate` the manager reports as a fraction between 0 and 1 inclusive to
        four decimal places."

        Design: Corner/errors/duplicate_natural_keys_are_refused_within_their_declared_scope
        """
        _jurisdiction, _engagement, store = _engagement_with_store_6008_and_one_employee()
        response = api_client.create_employee(
            store["id"],
            employee_payload(
                employee_code="EMP-A", retention_bonus_cents=100000,
                retention_start_date="2026-09-15",
                retention_target_date="2026-11-15", attendance_rate=0.95,
            ),
            make_consultant_headers(),
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_CODE.value, 409)
        _rows, meta = validate_paginated(
            api_client.list_employees(store["id"], make_consultant_headers())
        )
        assert meta["total_count"] == 1

    def test_a_second_engagement_may_reuse_the_same_store_code(self):
        """The scope is the engagement, so S-6008 is free again under a new agreement.

        The PRD says: "Uniqueness rules sit alongside the existence checks of step 8 and
        fire before any state or business rule: a duplicate jurisdiction `code` draws
        `ERR_DUPLICATE_JURISDICTION_CODE`, a duplicate `store_code` within one engagement
        draws `ERR_DUPLICATE_STORE_CODE`, and a duplicate `employee_code` within one
        store draws `ERR_DUPLICATE_EMPLOYEE_CODE`; all three carry HTTP 409."

        Design: Corner/errors/duplicate_natural_keys_are_refused_within_their_declared_scope
        """
        jurisdiction, _engagement, _store = _engagement_with_store_6008_and_one_employee()
        second_engagement = create_engagement()
        twin = validate_success(
            api_client.create_store(
                second_engagement["id"],
                store_payload(
                    jurisdiction["id"], store_code="S-6008",
                    address_line="9 Twin Rd",
                ),
                make_consultant_headers(),
            ),
            201,
        )
        assert twin["store_code"] == "S-6008"
        assert twin["engagement_id"] == second_engagement["id"]
        _rows, meta = validate_paginated(
            api_client.list_stores(make_consultant_headers())
        )
        assert meta["total_count"] == 2


class TestUnknownIdsReturnTheEntitySpecificNotFoundError:
    def test_the_jurisdiction_lot_stage_and_licence_readers_each_name_themselves(self):
        """One unused UUID, four readers, four different error ids.

        The PRD says: "Each entity type has its own not-found error:
        `ERR_JURISDICTION_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_STORE_NOT_FOUND`,
        `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_CONSIGNMENT_NOT_FOUND`,
        `ERR_MARKDOWN_STAGE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
        `ERR_EMPLOYEE_NOT_FOUND`, `ERR_SALES_DAY_NOT_FOUND`,
        `ERR_EXPENSE_ITEM_NOT_FOUND`, `ERR_LEASE_DISPOSITION_NOT_FOUND`, and
        `ERR_SETTLEMENT_NOT_FOUND`, each with HTTP 404."

        Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_error
        """
        pin_clock("2026-09-15T00:00:00Z")
        compliance = make_compliance_headers()
        consultant = make_consultant_headers()
        validate_error(
            api_client.get_jurisdiction(NON_EXISTENT_UUID, compliance),
            ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_inventory_lot(NON_EXISTENT_UUID, consultant),
            ApiErrorId.ERR_INVENTORY_LOT_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_markdown_stage(NON_EXISTENT_UUID, consultant),
            ApiErrorId.ERR_MARKDOWN_STAGE_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_gob_license(NON_EXISTENT_UUID, compliance),
            ApiErrorId.ERR_LICENSE_NOT_FOUND.value, 404,
        )

    def test_the_consignment_employee_expense_lease_and_settlement_readers_follow_suit(self):
        """The remaining five readers resolve their own entity and never a generic 404.

        The PRD says: "Each entity type has its own not-found error:
        `ERR_JURISDICTION_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_STORE_NOT_FOUND`,
        `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_CONSIGNMENT_NOT_FOUND`,
        `ERR_MARKDOWN_STAGE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`,
        `ERR_EMPLOYEE_NOT_FOUND`, `ERR_SALES_DAY_NOT_FOUND`,
        `ERR_EXPENSE_ITEM_NOT_FOUND`, `ERR_LEASE_DISPOSITION_NOT_FOUND`, and
        `ERR_SETTLEMENT_NOT_FOUND`, each with HTTP 404."

        Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_error
        """
        pin_clock("2026-09-15T00:00:00Z")
        consultant = make_consultant_headers()
        for call, expected in (
            (api_client.get_augmentation_consignment,
             ApiErrorId.ERR_CONSIGNMENT_NOT_FOUND.value),
            (api_client.get_employee, ApiErrorId.ERR_EMPLOYEE_NOT_FOUND.value),
            (api_client.get_expense_item,
             ApiErrorId.ERR_EXPENSE_ITEM_NOT_FOUND.value),
            (api_client.get_lease_disposition,
             ApiErrorId.ERR_LEASE_DISPOSITION_NOT_FOUND.value),
            (api_client.get_settlement, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value),
        ):
            response = call(NON_EXISTENT_UUID, consultant)
            validate_error(response, expected, 404)
            assert response.json()["response_type"] == "error"

    def test_existence_is_reported_before_any_state_rule_on_a_sales_day_review(self):
        """The review of a day that does not exist is a 404, never a state conflict.

        The PRD says: "When several rules could reject the same request, they are
        evaluated in one strict order and the first rule whose condition holds returns its
        error; no later rule is evaluated and no partial write occurs."

        Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_error
        """
        pin_clock("2026-09-15T00:00:00Z")
        response = api_client.review_sales_day(
            NON_EXISTENT_UUID, {"decision": "POST"}, make_controller_headers()
        )
        error = validate_error(
            response, ApiErrorId.ERR_SALES_DAY_NOT_FOUND.value, 404
        )
        assert error["error_id"] != ApiErrorId.ERR_SALES_DAY_STATE_INVALID.value


def _store_with_a_received_consignment_a_noticed_employee_and_a_posted_day():
    """S-6010 carrying every row the four repeat-action guards need."""
    scenario = _selling_store("S-6010", "NY-GOB-6010")
    store_id = scenario["store"]["id"]
    manager = make_store_manager_headers(store_id)
    consignment = propose_consignment(store_id, **FIFTY_APPAREL_UNITS)
    file_consignment_disclosure(consignment["id"], "NY-DISC-6010")
    employee = validate_success(
        api_client.create_employee(
            store_id,
            employee_payload(
                employee_code="EMP-A", retention_bonus_cents=100000,
                retention_start_date="2026-09-15",
                retention_target_date="2026-11-15", attendance_rate=0.95,
            ),
            manager,
        ),
        201,
    )
    run_employment_action(employee["id"], "GIVE_NOTICE", manager)
    day = validate_success(
        _file_raw(
            store_id, manager, business_date="2026-09-15",
            original_net_sales_cents=60000, augmentation_net_sales_cents=0,
            original_units_sold=20, augmentation_units_sold=0,
        ),
        201,
    )
    day = validate_success(
        api_client.review_sales_day(
            day["id"], {"decision": "POST"}, make_controller_headers()
        )
    )
    assert day["day_status"] == "POSTED"
    consignment = receive_consignment(consignment["id"])
    assert consignment["consignment_status"] == "RECEIVED"
    return store_id, consignment, employee, day


class TestRepeatActionsReturnEntitySpecificStateErrors:
    def test_a_second_disclosure_filing_hits_the_consignment_state_guard(self):
        """The consignment has moved on to RECEIVED, so the filing has no source state.

        The PRD says: "Filing against a consignment in any other status is refused with
        `ERR_CONSIGNMENT_STATE_INVALID`."

        Design: Corner/errors/repeat_actions_return_entity_specific_state_errors_and_the_return_cap
        """
        _store_id, consignment, _employee, _day = (
            _store_with_a_received_consignment_a_noticed_employee_and_a_posted_day()
        )
        response = api_client.file_consignment_disclosure(
            consignment["id"], make_compliance_headers(),
            {"disclosure_reference": "NY-DISC-6010-B"},
        )
        validate_error(
            response, ApiErrorId.ERR_CONSIGNMENT_STATE_INVALID.value, 409
        )
        read_back = validate_success(
            api_client.get_augmentation_consignment(
                consignment["id"], make_consultant_headers()
            )
        )
        assert read_back["consignment_status"] == "RECEIVED"
        assert read_back["disclosure_reference"] == "NY-DISC-6010"

    def test_a_second_notice_hits_the_employee_state_guard(self):
        """Giving notice is defined only from ACTIVE and the employee left it already.

        The PRD says: "An action that is not defined from the employee's current
        employment status is refused with `ERR_EMPLOYEE_STATE_INVALID`, and a
        `StoreManager` acting outside its own store is refused with
        `ERR_STORE_SCOPE_VIOLATION`."

        Design: Corner/errors/repeat_actions_return_entity_specific_state_errors_and_the_return_cap
        """
        store_id, _consignment, employee, _day = (
            _store_with_a_received_consignment_a_noticed_employee_and_a_posted_day()
        )
        manager = make_store_manager_headers(store_id)
        response = api_client.employment_action(
            employee["id"], {"action": "GIVE_NOTICE"}, manager
        )
        validate_error(response, ApiErrorId.ERR_EMPLOYEE_STATE_INVALID.value, 409)
        read_back = validate_success(api_client.get_employee(employee["id"], manager))
        assert read_back["employment_status"] == "NOTICE_GIVEN"
        assert read_back["bonus_status"] == "PENDING"

    def test_a_second_review_of_a_posted_day_hits_the_day_state_guard(self):
        """A posted day cannot be talked back into a rejection.

        The PRD says: "The day must still be `PENDING_REVIEW`, otherwise
        `ERR_SALES_DAY_STATE_INVALID`, and the reviewing identity may not equal
        `submitted_by_user_id`, otherwise `ERR_SELF_APPROVAL_FORBIDDEN`."

        Design: Corner/errors/repeat_actions_return_entity_specific_state_errors_and_the_return_cap
        """
        store_id, _consignment, _employee, day = (
            _store_with_a_received_consignment_a_noticed_employee_and_a_posted_day()
        )
        response = api_client.review_sales_day(
            day["id"], {"decision": "REJECT", "reject_reason": "changed my mind"},
            make_controller_headers(),
        )
        validate_error(response, ApiErrorId.ERR_SALES_DAY_STATE_INVALID.value, 409)
        rows, _meta = validate_paginated(
            api_client.list_sales_days(store_id, make_consultant_headers())
        )
        assert [row["day_status"] for row in rows] == ["POSTED"]

    def test_a_return_beyond_the_units_on_hand_is_refused(self):
        """Nine hundred and ninety-nine units were never consigned in the first place.

        The PRD says: "The return is a compensating action: the consultant declares the
        `units_returned` being sent back, which may not exceed the units still on hand in
        the consignment's lot — an excess is refused with
        `ERR_RETURN_UNITS_EXCEED_UNSOLD` — and the consignment must be `RECEIVED` with at
        least one unit still on hand, failing which `ERR_CONSIGNMENT_STATE_INVALID`
        applies."

        Design: Corner/errors/repeat_actions_return_entity_specific_state_errors_and_the_return_cap
        """
        store_id, consignment, _employee, _day = (
            _store_with_a_received_consignment_a_noticed_employee_and_a_posted_day()
        )
        response = api_client.return_unsold_consignment(
            consignment["id"], make_consultant_headers(), {"units_returned": 999}
        )
        validate_error(
            response, ApiErrorId.ERR_RETURN_UNITS_EXCEED_UNSOLD.value, 422
        )
        read_back = validate_success(
            api_client.get_augmentation_consignment(
                consignment["id"], make_consultant_headers()
            )
        )
        assert read_back["consignment_status"] == "RECEIVED"
        assert read_back["units_returned"] == 0
        assert read_store(store_id)["augmentation_units_accounted"] == 50


def _restricted_engagement_with_a_second_store_ready_to_run():
    """Store A's licence revoked; store B armed, disclosed and still selling."""
    scenario = setup_selling_engagement(
        store_specs=[
            {
                "store": {
                    "store_code": "S-6011A",
                    "address_line": "S-6011A Liquidation Row",
                },
                "lots": [APPAREL_LOT],
                "license": dict(LICENSE_PERIOD, license_number="NY-GOB-6011A"),
            },
            {
                "store": {
                    "store_code": "S-6011B",
                    "address_line": "S-6011B Liquidation Row",
                },
                "lots": [APPAREL_LOT],
                "license": dict(LICENSE_PERIOD, license_number="NY-GOB-6011B"),
            },
        ],
        jurisdiction_overrides=NY_RULES,
    )
    store_a, store_b = scenario["stores"]
    stage = add_markdown_stage(store_b["id"], **FIRST_STAGE)
    consignment = propose_consignment(store_b["id"], **FIFTY_APPAREL_UNITS)
    file_consignment_disclosure(consignment["id"], "NY-DISC-6011")
    revoke_license(
        scenario["licenses"][0]["id"],
        revoked_reason="signage violation at store A",
    )
    return {
        "engagement_id": scenario["engagement"]["id"],
        "store_a_id": store_a["id"],
        "store_b_id": store_b["id"],
        "stage": stage,
        "consignment": consignment,
    }


class TestRestrictedPostureBlocksNewCadenceAndReceiptsOnly:
    def test_one_revocation_puts_the_whole_engagement_in_restricted(self):
        """The strike came from store A and the posture is engagement-wide.

        The PRD says: "The posture is derived from the count and nothing else: `OPEN` when
        the count is exactly 0, `RESTRICTED` when the count is 1 or 2, and `FROZEN` when
        the count is 3 or more."

        Design: Corner/errors/restricted_posture_blocks_new_cadence_and_receipts_but_not_activation_or_proposals
        """
        world = _restricted_engagement_with_a_second_store_ready_to_run()
        engagement = read_engagement(world["engagement_id"])
        assert engagement["compliance_strike_count"] == 1
        assert engagement["compliance_posture"] == "RESTRICTED"
        assert read_store(world["store_b_id"])["store_status"] == "SELLING"

    def test_the_struck_store_is_suspended_for_the_revocation(self):
        """Hop two of the revocation chain lands on store A alone.

        The PRD says: "Hop two, caused by hop one, takes the licensed store from
        `SELLING` to `SUSPENDED` with `suspension_reason` set to `LICENSE_REVOKED`."

        Design: Corner/errors/restricted_posture_blocks_new_cadence_and_receipts_but_not_activation_or_proposals
        """
        world = _restricted_engagement_with_a_second_store_ready_to_run()
        store_a = read_store(world["store_a_id"])
        assert store_a["store_status"] == "SUSPENDED"
        assert store_a["suspension_reason"] == "LICENSE_REVOKED"

    def test_an_already_armed_stage_may_still_be_put_into_force(self):
        """A cadence already written may be run even under the restriction.

        The PRD says: "Activation is refused while the posture is `FROZEN` but remains
        permitted while it is `RESTRICTED`: a cadence already authored may be run, even
        though a new one may not be written."

        Design: Corner/errors/restricted_posture_blocks_new_cadence_and_receipts_but_not_activation_or_proposals
        """
        world = _restricted_engagement_with_a_second_store_ready_to_run()
        activated = validate_success(
            api_client.activate_markdown_stage(
                world["stage"]["id"], make_consultant_headers()
            )
        )
        assert activated["stage_status"] == "ACTIVE"

    def test_authoring_a_new_stage_is_refused_under_the_restriction(self):
        """The next markdown cannot be written while the engagement is restricted.

        The PRD says: "While the posture is `RESTRICTED`, two operations are refused with
        `ERR_ENGAGEMENT_COMPLIANCE_RESTRICTED`: authoring a new markdown stage, and
        receiving an augmentation consignment."

        Design: Corner/errors/restricted_posture_blocks_new_cadence_and_receipts_but_not_activation_or_proposals
        """
        world = _restricted_engagement_with_a_second_store_ready_to_run()
        store_b_id = world["store_b_id"]
        api_client.activate_markdown_stage(
            world["stage"]["id"], make_consultant_headers()
        )
        response = api_client.create_markdown_stage(
            store_b_id,
            markdown_stage_payload(store_version(store_b_id), **SECOND_STAGE),
            make_consultant_headers(),
        )
        validate_error(
            response, ApiErrorId.ERR_ENGAGEMENT_COMPLIANCE_RESTRICTED.value, 409
        )
        _rows, meta = validate_paginated(
            api_client.list_markdown_stages(store_b_id, make_consultant_headers())
        )
        assert meta["total_count"] == 1

    def test_receiving_the_disclosed_consignment_is_refused_under_the_restriction(self):
        """The goods stay on the dock and the consignment keeps its filed disclosure.

        The PRD says: "The engagement's `compliance_posture` must be `OPEN`: a
        `RESTRICTED` posture refuses with `ERR_ENGAGEMENT_COMPLIANCE_RESTRICTED` and a
        `FROZEN` posture refuses with `ERR_ENGAGEMENT_COMPLIANCE_FROZEN`."

        Design: Corner/errors/restricted_posture_blocks_new_cadence_and_receipts_but_not_activation_or_proposals
        """
        world = _restricted_engagement_with_a_second_store_ready_to_run()
        response = api_client.receive_consignment(
            world["consignment"]["id"], make_consultant_headers()
        )
        validate_error(
            response, ApiErrorId.ERR_ENGAGEMENT_COMPLIANCE_RESTRICTED.value, 409
        )
        read_back = validate_success(
            api_client.get_augmentation_consignment(
                world["consignment"]["id"], make_consultant_headers()
            )
        )
        assert read_back["consignment_status"] == "DISCLOSURE_FILED"
        assert read_store(world["store_b_id"])["augmentation_units_accounted"] == 0


def _store_suspended_by_an_expiry_sweep():
    """S-6012 licensed to 2026-10-14, swept at 2026-10-20 and left suspended."""
    scenario = _selling_store("S-6012", "NY-GOB-6012")
    pin_clock("2026-10-20T00:00:00Z")
    tally = run_compliance_sweep(scenario["engagement"]["id"])
    assert tally["expired_license_count"] == 1
    assert tally["suspended_store_count"] == 1
    return scenario["engagement"]["id"], scenario["store"]["id"]


class TestResumeWithoutACoveringLicenceIsRefused:
    def test_the_resume_is_refused_because_no_approved_licence_covers_the_clock(self):
        """The only licence expired six days ago, so there is nothing to resume under.

        The PRD says: "Where the jurisdiction requires a licence, the store must hold at
        least one licence at `license_status` of `APPROVED` whose period covers the
        current logical clock date, failing which the resume is refused with
        `ERR_LICENSE_NOT_ACTIVE`; in a jurisdiction that requires no licence the check
        does not apply."

        Design: Corner/errors/resume_without_a_covering_license_is_refused
        """
        _engagement_id, store_id = _store_suspended_by_an_expiry_sweep()
        response = api_client.resume_store(store_id, make_compliance_headers())
        validate_error(response, ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value, 409)

    def test_the_store_stays_suspended_on_the_expiry_reason(self):
        """The suspension reason records the expiry, and the licence reads EXPIRED.

        The PRD says: "Every `APPROVED` licence of the engagement whose `period_end_date`
        falls strictly before the current logical clock date moves `APPROVED → EXPIRED`;
        each such expiry suspends its still-`SELLING` store with `suspension_reason` of
        `LICENSE_EXPIRED`, closes that store's `ACTIVE` stage with `closed_reason` of
        `LICENSE_LOST` and no escalation, and increments the engagement's
        `compliance_strike_count` by 1 with the posture re-derived."

        Design: Corner/errors/resume_without_a_covering_license_is_refused
        """
        _engagement_id, store_id = _store_suspended_by_an_expiry_sweep()
        api_client.resume_store(store_id, make_compliance_headers())
        store = read_store(store_id)
        assert store["store_status"] == "SUSPENDED"
        assert store["suspension_reason"] == "LICENSE_EXPIRED"
        rows, meta = validate_paginated(
            api_client.list_gob_licenses(store_id, make_compliance_headers())
        )
        assert meta["total_count"] == 1
        assert rows[0]["license_status"] == "EXPIRED"

    def test_a_refused_resume_neither_adds_nor_clears_a_strike(self):
        """The counter records licence losses only, and it never runs backwards.

        The PRD says: "Resumption does not reopen the stages the suspension closed — a
        lost stage is lost — and it does not reduce the strike count."

        Design: Corner/errors/resume_without_a_covering_license_is_refused
        """
        engagement_id, store_id = _store_suspended_by_an_expiry_sweep()
        before = read_engagement(engagement_id)
        assert before["compliance_strike_count"] == 1
        api_client.resume_store(store_id, make_compliance_headers())
        after = read_engagement(engagement_id)
        assert after["compliance_strike_count"] == 1
        assert after["compliance_posture"] == "RESTRICTED"


def _store_with_one_armed_stage_and_no_posted_sales():
    """S-6013 licensed to 2026-10-14 with a single ARMED stage and nothing sold."""
    scenario = _selling_store("S-6013", "NY-GOB-6013")
    store_id = scenario["store"]["id"]
    stage = add_markdown_stage(store_id, **FIRST_STAGE)
    assert stage["stage_status"] == "ARMED"
    assert read_store(store_id)["realized_sell_through_pct"] == pytest.approx(
        0.0000, abs=0.00001
    )
    return store_id, stage


class TestStageActivationAndCheckpointGuardTheirOwnStageState:
    def test_checkpointing_an_armed_stage_is_refused(self):
        """The checkpoint is defined from ACTIVE and this stage has not started.

        The PRD says: "The consultant closes an `ACTIVE` stage against its target, moving
        it `ACTIVE → CLOSED`; the stage must be `ACTIVE` (otherwise
        `ERR_STAGE_STATE_INVALID`) and the store must be `SELLING` (otherwise
        `ERR_STORE_NOT_SELLING`)."

        Design: Corner/errors/stage_activation_and_checkpoint_each_guard_their_own_stage_state
        """
        _store_id, stage = _store_with_one_armed_stage_and_no_posted_sales()
        response = api_client.checkpoint_markdown_stage(
            stage["id"], make_consultant_headers()
        )
        validate_error(response, ApiErrorId.ERR_STAGE_STATE_INVALID.value, 409)
        read_back = _read_stage(stage["id"])
        assert read_back["stage_status"] == "ARMED"
        assert read_back["checkpoint_sell_through_pct"] is None

    def test_the_legal_activation_stamps_the_logical_clock_instant(self):
        """One activation is admissible and it records when the markdown took effect.

        The PRD says: "Putting a stage into force takes it `ARMED → ACTIVE` and stamps
        `activated_at` with the current logical-clock instant."

        Design: Corner/errors/stage_activation_and_checkpoint_each_guard_their_own_stage_state
        """
        _store_id, stage = _store_with_one_armed_stage_and_no_posted_sales()
        activated = activate_markdown_stage(stage["id"])
        assert activated["stage_status"] == "ACTIVE"
        assert_instant_equals(
            activated["activated_at"], "2026-09-15T00:00:00Z", "activated_at"
        )

    def test_re_activating_an_active_stage_is_refused_by_its_own_state(self):
        """The guard is the stage's own reading, not the sibling-stage rule.

        The PRD says: "The stage must currently be `ARMED`, otherwise
        `ERR_STAGE_STATE_INVALID`."

        Design: Corner/errors/stage_activation_and_checkpoint_each_guard_their_own_stage_state
        """
        _store_id, stage = _store_with_one_armed_stage_and_no_posted_sales()
        activate_markdown_stage(stage["id"])
        response = api_client.activate_markdown_stage(
            stage["id"], make_consultant_headers()
        )
        error = validate_error(response, ApiErrorId.ERR_STAGE_STATE_INVALID.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_STAGE_ALREADY_ACTIVE.value

    def test_the_legal_checkpoint_escalates_at_the_cap_with_no_successor_to_carry_it(self):
        """A quarter-point shortfall is five bands and the raise is capped at 0.2000.

        The PRD says: "Stages that are already `CLOSED` or `VOIDED` are never adjusted,
        and where no armed successor exists the escalation is recorded on the checkpointed
        stage alone and nothing else moves."

        Design: Corner/errors/stage_activation_and_checkpoint_each_guard_their_own_stage_state
        """
        store_id, stage = _store_with_one_armed_stage_and_no_posted_sales()
        activate_markdown_stage(stage["id"])
        closed = checkpoint_markdown_stage(stage["id"])
        assert closed["stage_status"] == "CLOSED"
        assert closed["checkpoint_sell_through_pct"] == pytest.approx(
            0.0000, abs=0.00001
        )
        assert closed["closed_reason"] == "ESCALATED"
        assert closed["escalation_applied_pct"] == pytest.approx(
            0.2000, abs=0.00001
        )
        rows, meta = validate_paginated(
            api_client.list_markdown_stages(
                store_id, make_consultant_headers(),
                params={"stage_status": "CLOSED"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == stage["id"]

    def test_re_checkpointing_a_closed_stage_is_refused_and_nothing_else_moved(self):
        """The same id answers from a third state, and the store's other rows are empty.

        The PRD says: "The consultant closes an `ACTIVE` stage against its target, moving
        it `ACTIVE → CLOSED`; the stage must be `ACTIVE` (otherwise
        `ERR_STAGE_STATE_INVALID`) and the store must be `SELLING` (otherwise
        `ERR_STORE_NOT_SELLING`)."

        Design: Corner/errors/stage_activation_and_checkpoint_each_guard_their_own_stage_state
        """
        store_id, stage = _store_with_one_armed_stage_and_no_posted_sales()
        activate_markdown_stage(stage["id"])
        checkpoint_markdown_stage(stage["id"])
        response = api_client.checkpoint_markdown_stage(
            stage["id"], make_consultant_headers()
        )
        validate_error(response, ApiErrorId.ERR_STAGE_STATE_INVALID.value, 409)
        consultant = make_consultant_headers()
        _days, day_meta = validate_paginated(
            api_client.list_sales_days(store_id, consultant)
        )
        assert day_meta["total_count"] == 0
        _employees, employee_meta = validate_paginated(
            api_client.list_employees(store_id, consultant)
        )
        assert employee_meta["total_count"] == 0
        _licenses, license_meta = validate_paginated(
            api_client.list_gob_licenses(
                store_id, consultant, params={"license_status": "APPROVED"}
            )
        )
        assert license_meta["total_count"] == 1
        store = read_store(store_id)
        _items, item_meta = validate_paginated(
            api_client.list_engagement_expense_items(
                store["engagement_id"], consultant
            )
        )
        assert item_meta["total_count"] == 0

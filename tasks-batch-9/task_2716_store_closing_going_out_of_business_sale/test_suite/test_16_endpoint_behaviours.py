"""Endpoint-level behaviour: computed reads, bulk actions, links, and CRUD round trips.

Each case exercises one endpoint shape end to end — a derived summary that stores
nothing, a sweep that answers with a tally, a cascade that is the sole author of a row,
a conditional action that runs exactly once, and a create-read-list round trip whose
filter must track the state machine.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    add_inventory_lot,
    add_store,
    api_client,
    activate_markdown_stage,
    add_markdown_stage,
    apply_for_license,
    approve_engagement,
    assert_compliance_sweep_tally,
    assert_inventory_lot,
    assert_lease_disposition,
    assert_recovery_summary,
    create_engagement,
    create_jurisdiction,
    decide_license,
    file_consignment_disclosure,
    inventory_lot_payload,
    lease_disposition_payload,
    make_compliance_headers,
    make_consultant_headers,
    make_controller_headers,
    pin_clock,
    propose_consignment,
    read_engagement,
    read_store,
    receive_consignment,
    submit_engagement,
    submit_expense_item,
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
FEE_BASED_LIQUIDATOR = {
    "economics_model": "FEE_BASED", "guaranty_pct": 0,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "LIQUIDATOR",
    "shared_expense_liquidator_pct": 0, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}
GUARANTEED_AT_ONE_AND_A_HALF = {
    "economics_model": "GUARANTEED", "guaranty_pct": 1.5,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "LIQUIDATOR",
    "shared_expense_liquidator_pct": 0, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}
APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}
LICENSE_PERIOD = {
    "period_start_date": "2026-09-15", "period_end_date": "2026-10-14",
    "advertising_claim_codes": ["EVERYTHING_MUST_GO"],
}


def _license_the_store(store_id, license_number, **period):
    application = apply_for_license(
        store_id, license_number=license_number, **{**LICENSE_PERIOD, **period}
    )
    return decide_license(application["id"])


def _selling_store(store_code, license_number, engagement_overrides=None):
    """The shortest chain from an empty database to one licensed SELLING store."""
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(
        **(engagement_overrides or FEE_BASED_LIQUIDATOR)
    )
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code=store_code, address_line=f"{store_code} Liquidation Row",
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = _license_the_store(store["id"], license_number)
    return {
        "jurisdiction": jurisdiction, "engagement": engagement,
        "store": store, "license": license_row,
    }


def _guaranteed_store_with_a_sixty_percent_stage_armed():
    """A 3,000,000-cent guaranty over a 2,000,000-cent floor marked down 60 percent."""
    scenario = _selling_store(
        "S-5001", "NY-GOB-5001",
        engagement_overrides=GUARANTEED_AT_ONE_AND_A_HALF,
    )
    scenario["stage"] = add_markdown_stage(
        scenario["store"]["id"], stage_index=1, discount_pct=0.6,
        sell_through_target_pct=0.5,
        window_start_date="2026-09-16", window_end_date="2026-10-01",
    )
    return scenario


def _summary_of(engagement_id):
    return validate_success(
        api_client.get_recovery_summary(engagement_id, make_controller_headers())
    )


class TestRecoverySummaryIsEntirelyDerived:
    def test_the_summary_restates_the_engagement_s_base_and_store_count(self):
        """One store and 2,000,000 cents of original cost, both re-derived on read.

        The PRD says: "It returns `projected_gross_recovery_cents`,
        `projected_recovery_ratio`, `realized_gross_recovery_cents`,
        `realized_recovery_ratio`, `planned_avg_discount_pct`,
        `projected_shortfall_cents`, `guaranty_amount_cents`,
        `original_cost_value_cents`, and `store_count`, the number of stores in the
        engagement."

        Design: Corner/endpoints/recovery_summary_read_reports_the_guaranty_shortfall_from_the_planned_cadence
        """
        scenario = _guaranteed_store_with_a_sixty_percent_stage_armed()
        summary = _summary_of(scenario["engagement"]["id"])
        assert_recovery_summary(summary)
        assert summary["store_count"] == 1
        assert summary["original_cost_value_cents"] == 2000000

    def test_the_armed_stage_drives_the_projected_half_of_the_summary(self):
        """A 0.6000 planned discount leaves 1,700,000 cents at a 0.8500 ratio.

        The PRD says: "The store's `projected_gross_recovery_cents` is the exact integer
        sum of those per-lot rounded amounts — rounded per lot first, summed second."

        Design: Corner/endpoints/recovery_summary_read_reports_the_guaranty_shortfall_from_the_planned_cadence
        """
        scenario = _guaranteed_store_with_a_sixty_percent_stage_armed()
        summary = _summary_of(scenario["engagement"]["id"])
        assert summary["planned_avg_discount_pct"] == pytest.approx(
            0.6000, abs=0.00001
        )
        assert summary["projected_gross_recovery_cents"] == 1700000
        assert summary["projected_recovery_ratio"] == pytest.approx(
            0.8500, abs=0.00001
        )

    def test_the_shortfall_is_the_guaranty_less_the_projection(self):
        """3,000,000 guaranteed against 1,700,000 projected leaves 1,300,000 short.

        The PRD says: "At the engagement level the projection rolls up:
        `projected_gross_recovery_cents` is the sum of the same field over every store of
        the engagement, and `projected_shortfall_cents` is the guaranty amount less that
        projected gross recovery, floored at 0 so that a projection which clears the
        guaranty reports no shortfall at all."

        Design: Corner/endpoints/recovery_summary_read_reports_the_guaranty_shortfall_from_the_planned_cadence
        """
        scenario = _guaranteed_store_with_a_sixty_percent_stage_armed()
        summary = _summary_of(scenario["engagement"]["id"])
        assert summary["guaranty_amount_cents"] == 3000000
        assert summary["projected_shortfall_cents"] == 1300000
        assert (
            summary["guaranty_amount_cents"]
            - summary["projected_gross_recovery_cents"]
            == summary["projected_shortfall_cents"]
        )

    def test_the_realized_half_is_still_zero_with_no_day_posted(self):
        """Nothing has sold, so both realized lines read zero.

        The PRD says: "Realized recovery is the chronological half and counts only money
        that has been posted to the ledger."

        Design: Corner/endpoints/recovery_summary_read_reports_the_guaranty_shortfall_from_the_planned_cadence
        """
        scenario = _guaranteed_store_with_a_sixty_percent_stage_armed()
        summary = _summary_of(scenario["engagement"]["id"])
        assert summary["realized_gross_recovery_cents"] == 0
        assert summary["realized_recovery_ratio"] == pytest.approx(
            0.0000, abs=0.00001
        )


def _two_licensed_stores_one_licence_about_to_lapse():
    """Store A's licence ends 2026-09-20; store B sells on with an ACTIVE stage.

    The clock is then advanced to 2026-09-26, which is past A's licence end and past
    the end of B's stage window, so a single sweep has two different jobs to do.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store_a = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-5002A", address_line="S-5002A Liquidation Row",
    )
    add_inventory_lot(store_a["id"], **APPAREL_LOT)
    store_b = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-5002B", address_line="S-5002B Liquidation Row",
    )
    add_inventory_lot(store_b["id"], **APPAREL_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    _license_the_store(
        store_a["id"], "NY-GOB-5002A", period_end_date="2026-09-20"
    )
    _license_the_store(store_b["id"], "NY-GOB-5002B")
    stage = add_markdown_stage(
        store_b["id"], stage_index=1, discount_pct=0.2,
        sell_through_target_pct=0.25,
        window_start_date="2026-09-16", window_end_date="2026-09-25",
    )
    activate_markdown_stage(stage["id"])
    pin_clock("2026-09-26T00:00:00Z")
    return {
        "engagement": engagement, "store_a": store_a, "store_b": store_b,
        "stage": stage,
    }


def _read_stage(stage_id):
    return validate_success(
        api_client.get_markdown_stage(stage_id, make_consultant_headers())
    )


class TestComplianceSweepTallyCountsEachEffectSeparately:
    def test_the_tally_separates_the_expiry_from_the_window_end_closure(self):
        """One expiry, one suspension, one stage closure and one strike.

        The PRD says: "The sweep answers with a tally rather than a resource:
        `expired_license_count`, `closed_stage_count`, `suspended_store_count`, and the
        engagement's resulting `compliance_strike_count` and `compliance_posture`."

        Design: Corner/endpoints/compliance_sweep_reports_separate_counts_for_expiries_suspensions_and_stage_closures
        """
        scenario = _two_licensed_stores_one_licence_about_to_lapse()
        tally = validate_success(
            api_client.run_compliance_sweep(
                scenario["engagement"]["id"], make_compliance_headers()
            )
        )
        assert_compliance_sweep_tally(tally)
        assert tally["expired_license_count"] == 1
        assert tally["suspended_store_count"] == 1
        assert tally["closed_stage_count"] == 1
        assert tally["compliance_strike_count"] == 1
        assert tally["compliance_posture"] == "RESTRICTED"

    def test_only_the_store_whose_licence_lapsed_is_suspended(self):
        """Store A is suspended for the expiry while store B keeps selling.

        The PRD says: "Every `APPROVED` licence of the engagement whose `period_end_date`
        falls strictly before the current logical clock date moves `APPROVED → EXPIRED`;
        each such expiry suspends its still-`SELLING` store with `suspension_reason` of
        `LICENSE_EXPIRED`, closes that store's `ACTIVE` stage with `closed_reason` of
        `LICENSE_LOST` and no escalation, and increments the engagement's
        `compliance_strike_count` by 1 with the posture re-derived."

        Design: Corner/endpoints/compliance_sweep_reports_separate_counts_for_expiries_suspensions_and_stage_closures
        """
        scenario = _two_licensed_stores_one_licence_about_to_lapse()
        api_client.run_compliance_sweep(
            scenario["engagement"]["id"], make_compliance_headers()
        )
        store_a = read_store(scenario["store_a"]["id"])
        store_b = read_store(scenario["store_b"]["id"])
        assert store_a["store_status"] == "SUSPENDED"
        assert store_a["suspension_reason"] == "LICENSE_EXPIRED"
        assert store_b["store_status"] == "SELLING"
        assert store_b["suspension_reason"] == "NONE"

    def test_the_stage_whose_window_ran_out_closes_without_escalation(self):
        """Store B's stage retires ON_SCHEDULE, however its sell-through looked.

        The PRD says: "In the same pass the sweep also retires stages that simply ran
        their course: every `ACTIVE` markdown stage whose `window_end_date` is on or
        before the current logical clock date moves `ACTIVE → CLOSED` with `closed_reason`
        of `ON_SCHEDULE` and `escalation_applied_pct` of exactly 0.0000 — the sweep never
        escalates a markdown, whatever the sell-through — and where that stage has an
        `ARMED` successor at the next cadence position, the successor is promoted to
        `ACTIVE` provided the store is still `SELLING`."

        Design: Corner/endpoints/compliance_sweep_reports_separate_counts_for_expiries_suspensions_and_stage_closures
        """
        scenario = _two_licensed_stores_one_licence_about_to_lapse()
        api_client.run_compliance_sweep(
            scenario["engagement"]["id"], make_compliance_headers()
        )
        stage = _read_stage(scenario["stage"]["id"])
        assert stage["stage_status"] == "CLOSED"
        assert stage["closed_reason"] == "ON_SCHEDULE"
        assert stage["escalation_applied_pct"] == pytest.approx(0.0000, abs=0.00001)

    def test_the_retired_stage_leaves_store_b_s_planned_discount(self):
        """With no armed or active stage left, the projection returns to full ticket.

        The PRD says: "Projected recovery is then recomputed for every affected store and
        rolled up to the engagement, whose `version` increments by 1."

        Design: Corner/endpoints/compliance_sweep_reports_separate_counts_for_expiries_suspensions_and_stage_closures
        """
        scenario = _two_licensed_stores_one_licence_about_to_lapse()
        api_client.run_compliance_sweep(
            scenario["engagement"]["id"], make_compliance_headers()
        )
        store_b = read_store(scenario["store_b"]["id"])
        assert store_b["planned_avg_discount_pct"] == pytest.approx(
            0.0000, abs=0.00001
        )
        assert store_b["projected_gross_recovery_cents"] == 4250000

    def test_the_sweep_creates_and_removes_no_store(self):
        """The engagement still holds exactly the two stores it started with.

        The PRD says: "A compliance officer runs the compliance sweep against the
        engagement, and the sweep is what observes the passage of logical time."

        Design: Corner/endpoints/compliance_sweep_reports_separate_counts_for_expiries_suspensions_and_stage_closures
        """
        scenario = _two_licensed_stores_one_licence_about_to_lapse()
        api_client.run_compliance_sweep(
            scenario["engagement"]["id"], make_compliance_headers()
        )
        _rows, meta = validate_paginated(
            api_client.list_stores(
                make_compliance_headers(),
                params={"engagement_id": scenario["engagement"]["id"]},
            )
        )
        assert meta["total_count"] == 2


def _store_with_a_disclosed_consignment_of_fifty_units():
    """Fifty consigned APPAREL units worth 100,000 cents against a 2,000,000 base.

    That is a ratio of 0.0500 against New York's 0.10 cap, so the receipt will clear.
    """
    scenario = _selling_store("S-5003", "NY-GOB-5003")
    consignment = propose_consignment(
        scenario["store"]["id"], supplier_name="Northgate Supply",
        category="APPAREL", units_supplied=50, unit_cost_cents=2000,
        unit_retail_cents=5000, delivery_window_start_date="2026-09-15",
        delivery_window_end_date="2026-09-20",
    )
    file_consignment_disclosure(consignment["id"], "NY-DISC-5003")
    scenario["consignment"] = consignment
    return scenario


def _consignment_lots(consignment_id):
    rows, meta = validate_paginated(
        api_client.list_consignment_inventory_lots(
            consignment_id, make_consultant_headers()
        )
    )
    return rows, meta


class TestReceiptIsTheSoleAuthorOfAugmentationLots:
    def test_the_receipt_creates_one_lot_linked_to_both_parents(self):
        """The new lot names its store and its consignment and copies the unit terms.

        The PRD says: "Its `source` is `AUGMENTATION`, its `consignment_id` points back at
        the consignment, and its `category`, `unit_cost_cents`, and `unit_retail_cents`
        are copied from the consignment while its `units_initial` and `units_on_hand` are
        both set to the consignment's `units_supplied`, at `lot_status` of `ON_FLOOR`."

        Design: Corner/endpoints/receiving_a_consignment_links_a_new_augmentation_lot_to_both_store_and_consignment
        """
        scenario = _store_with_a_disclosed_consignment_of_fifty_units()
        received = receive_consignment(scenario["consignment"]["id"])
        assert received["consignment_status"] == "RECEIVED"
        rows, meta = _consignment_lots(scenario["consignment"]["id"])
        assert meta["total_count"] == 1
        lot = rows[0]
        assert_inventory_lot(lot)
        assert lot["source"] == "AUGMENTATION"
        assert lot["consignment_id"] == scenario["consignment"]["id"]
        assert lot["store_id"] == scenario["store"]["id"]
        assert lot["units_initial"] == 50
        assert lot["units_on_hand"] == 50
        assert lot["cost_value_cents"] == 100000
        assert lot["lot_status"] == "ON_FLOOR"

    def test_the_linked_lot_reads_individually_with_its_own_projection(self):
        """Forty-two projected units at full ticket are 210,000 cents.

        The PRD says: "Because that lot was never filed through the store's own inventory
        collection, the consignment's own lot listing — filterable by `lot_status` — is the
        only discovery channel for it."

        Design: Corner/endpoints/receiving_a_consignment_links_a_new_augmentation_lot_to_both_store_and_consignment
        """
        scenario = _store_with_a_disclosed_consignment_of_fifty_units()
        receive_consignment(scenario["consignment"]["id"])
        rows, _meta = _consignment_lots(scenario["consignment"]["id"])
        lot = validate_success(
            api_client.get_inventory_lot(rows[0]["id"], make_consultant_headers())
        )
        assert lot["projected_recovery_cents"] == 210000

    def test_the_consigned_cost_lands_beside_the_retailer_s_own_and_not_inside_it(self):
        """The projection grows to 4,460,000 while the 2,000,000 denominator holds.

        The PRD says: "The store's `augmentation_cost_value_cents`, `units_initial_total`,
        `augmentation_units_accounted`, and `realized_sell_through_pct` are recomputed,
        followed by the store's projected recovery figures and the engagement roll-up; the
        store's `original_cost_value_cents` is pointedly not touched, because consigned
        goods are not the retailer's own cost."

        Design: Corner/endpoints/receiving_a_consignment_links_a_new_augmentation_lot_to_both_store_and_consignment
        """
        scenario = _store_with_a_disclosed_consignment_of_fifty_units()
        receive_consignment(scenario["consignment"]["id"])
        store = read_store(scenario["store"]["id"])
        assert store["augmentation_cost_value_cents"] == 100000
        assert store["augmentation_units_accounted"] == 50
        assert store["units_initial_total"] == 1050
        assert store["original_cost_value_cents"] == 2000000
        assert store["projected_gross_recovery_cents"] == 4460000
        assert store["projected_recovery_ratio"] == pytest.approx(
            2.2300, abs=0.00001
        )

    def test_the_direct_lot_endpoint_refuses_an_augmentation_source(self):
        """No second augmentation lot can be filed through the store's own collection.

        The PRD says: "Filing a lot directly is only ever permitted for original
        merchandise: a filing that declares an augmentation source is refused with
        `ERR_AUGMENTATION_SOURCE_FORBIDDEN`, because augmentation lots exist only as the
        product of the consignment receipt cascade of §3.5."

        Design: Corner/endpoints/receiving_a_consignment_links_a_new_augmentation_lot_to_both_store_and_consignment
        """
        scenario = _store_with_a_disclosed_consignment_of_fifty_units()
        receive_consignment(scenario["consignment"]["id"])
        response = api_client.create_inventory_lot(
            scenario["store"]["id"],
            inventory_lot_payload(
                category="APPAREL", source="AUGMENTATION", units_initial=10,
                unit_cost_cents=2000, unit_retail_cents=5000,
            ),
            make_consultant_headers(),
        )
        validate_error(
            response, ApiErrorId.ERR_AUGMENTATION_SOURCE_FORBIDDEN.value, 400
        )
        rows, meta = _consignment_lots(scenario["consignment"]["id"])
        assert meta["total_count"] == 1
        assert rows[0]["units_initial"] == 50


def _engagement_with_one_submitted_advertising_expense():
    """A LIQUIDATOR-responsibility engagement holding one 90,000-cent expense."""
    scenario = _selling_store("S-5004", "NY-GOB-5004")
    scenario["expense"] = submit_expense_item(
        scenario["engagement"]["id"], store_id=scenario["store"]["id"],
        expense_category="ADVERTISING", amount_cents=90000,
        incurred_date="2026-09-15",
    )
    return scenario


def _decide(expense_item_id, action, **extra):
    return api_client.decide_expense_item(
        expense_item_id, {"action": action, **extra}, make_controller_headers()
    )


class TestExpenseDecisionIsConditionalAndRunsOnce:
    def test_the_first_approval_allocates_the_whole_amount_to_the_liquidator(self):
        """Under LIQUIDATOR responsibility the retailer's share is nothing at all.

        The PRD says: "Under `LIQUIDATOR` responsibility the liquidator's share is the
        item's whole `amount_cents`; under `RETAILER` responsibility it is 0; under
        `SHARED` responsibility it is `amount_cents` multiplied by the engagement's
        `shared_expense_liquidator_pct`, rounded half up to whole cents once per item."

        Design: Corner/endpoints/expense_decision_is_a_conditional_action_that_runs_only_once
        """
        scenario = _engagement_with_one_submitted_advertising_expense()
        approved = validate_success(_decide(scenario["expense"]["id"], "APPROVE"))
        assert approved["expense_status"] == "APPROVED"
        assert approved["liquidator_share_cents"] == 90000
        assert approved["retailer_share_cents"] == 0
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["expense_total_cents"] == 90000
        assert engagement["expense_liquidator_share_cents"] == 90000

    def test_a_second_approval_is_refused_and_cannot_double_count(self):
        """Approval is defined from SUBMITTED alone, so the repeat is a state error.

        The PRD says: "Approval is defined only from `SUBMITTED` and requires the
        engagement to be `ACTIVE` or `WIND_DOWN`, otherwise
        `ERR_ENGAGEMENT_STATE_INVALID`; it takes the item `SUBMITTED → APPROVED` and runs
        the responsibility split."

        Design: Corner/endpoints/expense_decision_is_a_conditional_action_that_runs_only_once
        """
        scenario = _engagement_with_one_submitted_advertising_expense()
        _decide(scenario["expense"]["id"], "APPROVE")
        response = _decide(
            scenario["expense"]["id"], "APPROVE", decision_note="again"
        )
        validate_error(response, ApiErrorId.ERR_EXPENSE_STATE_INVALID.value, 409)
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["expense_total_cents"] == 90000

    def test_the_void_restores_the_aggregates_to_their_pre_approval_values(self):
        """Voiding the approved item empties all three engagement aggregates again.

        The PRD says: "Voiding a `SUBMITTED` item is aggregate-neutral, because a submitted
        item was never inside the three engagement aggregates to begin with; voiding an
        `APPROVED` item is a compensating action that removes it from all three, restoring
        them to exactly their pre-approval values."

        Design: Corner/endpoints/expense_decision_is_a_conditional_action_that_runs_only_once
        """
        scenario = _engagement_with_one_submitted_advertising_expense()
        _decide(scenario["expense"]["id"], "APPROVE")
        _decide(scenario["expense"]["id"], "APPROVE", decision_note="again")
        voided = validate_success(
            _decide(scenario["expense"]["id"], "VOID", decision_note="withdrawn")
        )
        assert voided["expense_status"] == "VOIDED"
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["expense_total_cents"] == 0
        assert engagement["expense_liquidator_share_cents"] == 0
        assert engagement["expense_retailer_share_cents"] == 0

    def test_a_voided_item_can_never_be_revived_by_a_later_approval(self):
        """VOIDED is terminal, so the post-void approval is refused too.

        The PRD says: "Voiding is defined from `SUBMITTED` and from `APPROVED`; an item
        already `VOIDED` or `SETTLED` draws `ERR_EXPENSE_STATE_INVALID`."

        Design: Corner/endpoints/expense_decision_is_a_conditional_action_that_runs_only_once
        """
        scenario = _engagement_with_one_submitted_advertising_expense()
        _decide(scenario["expense"]["id"], "APPROVE")
        _decide(scenario["expense"]["id"], "VOID", decision_note="withdrawn")
        response = _decide(
            scenario["expense"]["id"], "APPROVE", decision_note="revive"
        )
        validate_error(response, ApiErrorId.ERR_EXPENSE_STATE_INVALID.value, 409)
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["expense_total_cents"] == 0


KESTREL_LEASE = {
    "landlord_name": "Kestrel Realty",
    "surrender_deadline_date": "2026-12-01",
    "daily_holdover_rate_cents": 25000,
    "rent_arrears_cents": 400000,
    "cam_arrears_cents": 150000,
    "restoration_cost_cents": 600000,
    "fixture_reserve_price_cents": 500000,
    "surrender_credit_cents": 25000,
}


def _open_lease_raw(store_id):
    return api_client.create_lease_disposition(
        store_id, lease_disposition_payload(**KESTREL_LEASE),
        make_consultant_headers(),
    )


def _draft_filtered_list(store_id):
    return validate_paginated(
        api_client.list_lease_dispositions(
            store_id, make_consultant_headers(),
            params={"disposition_status": "DRAFT"},
        )
    )


class TestLeaseDispositionRoundTrip:
    def test_the_create_opens_the_negotiation_in_draft_at_round_zero(self):
        """Nothing has been offered yet, so the round counter is still zero.

        The PRD says: "The disposition opens at `disposition_status` of `DRAFT` with
        `negotiation_round` at 0 and every negotiated, computed, and allocation field
        unset."

        Design: Corner/endpoints/lease_disposition_create_read_and_filtered_list_round_trip
        """
        scenario = _selling_store("S-5005", "NY-GOB-5005")
        disposition = validate_success(
            _open_lease_raw(scenario["store"]["id"]), 201
        )
        assert_lease_disposition(disposition)
        assert disposition["disposition_status"] == "DRAFT"
        assert disposition["negotiation_round"] == 0
        assert disposition["surrender_credit_cents"] == 25000
        assert disposition["version"] == 1

    def test_the_item_read_returns_the_four_claim_figures_as_filed(self):
        """The read agrees with the create on every money field of the claim.

        The PRD says: "The `LiquidationConsultant` opens a lease disposition against the
        store, naming the `landlord_name` counterparty, the `surrender_deadline_date` by
        which possession must be delivered before holdover charges begin to accrue, the
        `daily_holdover_rate_cents` the contract charges for each day beyond it, and the
        four figures the negotiation will argue over: `rent_arrears_cents` for unpaid base
        rent, `cam_arrears_cents` for unpaid common-area maintenance,
        `restoration_cost_cents` for the landlord's restoration and condition obligation,
        `fixture_reserve_price_cents` as the floor below which the store's fixtures and
        equipment may not be sold, and `surrender_credit_cents` as the cash credit the
        retailer is willing to contribute toward the landlord's claim, defaulting to 0."

        Design: Corner/endpoints/lease_disposition_create_read_and_filtered_list_round_trip
        """
        scenario = _selling_store("S-5005", "NY-GOB-5005")
        created = validate_success(_open_lease_raw(scenario["store"]["id"]), 201)
        read_back = validate_success(
            api_client.get_lease_disposition(
                created["id"], make_controller_headers()
            )
        )
        assert read_back["id"] == created["id"]
        assert read_back["landlord_name"] == "Kestrel Realty"
        assert read_back["rent_arrears_cents"] == 400000
        assert read_back["cam_arrears_cents"] == 150000
        assert read_back["restoration_cost_cents"] == 600000
        assert read_back["fixture_reserve_price_cents"] == 500000
        assert read_back["daily_holdover_rate_cents"] == 25000

    def test_the_draft_filter_finds_the_new_disposition(self):
        """One row matches the DRAFT filter and no rows remain beyond the window.

        The PRD says: "Dispositions are listable per store filtered by
        `disposition_status` and readable individually together with their waterfall
        allocations."

        Design: Corner/endpoints/lease_disposition_create_read_and_filtered_list_round_trip
        """
        scenario = _selling_store("S-5005", "NY-GOB-5005")
        _open_lease_raw(scenario["store"]["id"])
        rows, meta = _draft_filtered_list(scenario["store"]["id"])
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert rows[0]["disposition_status"] == "DRAFT"

    def test_sending_the_offer_consumes_the_first_round(self):
        """OFFER_SENT at round 1 with the offered figure recorded.

        The PRD says: "The consultant sends an offer carrying
        `offered_surrender_payment_cents`, which is defined from `DRAFT` and from
        `LANDLORD_COUNTERED` and takes the disposition to `OFFER_SENT`, incrementing
        `negotiation_round` by 1 and recording the offered figure over any previous one."

        Design: Corner/endpoints/lease_disposition_create_read_and_filtered_list_round_trip
        """
        scenario = _selling_store("S-5005", "NY-GOB-5005")
        created = validate_success(_open_lease_raw(scenario["store"]["id"]), 201)
        offered = validate_success(
            api_client.send_lease_offer(
                created["id"], {"offered_surrender_payment_cents": 300000},
                make_consultant_headers(),
            )
        )
        assert offered["disposition_status"] == "OFFER_SENT"
        assert offered["offered_surrender_payment_cents"] == 300000
        assert offered["negotiation_round"] == 1

    def test_the_offer_drops_the_row_out_of_the_draft_filter_only(self):
        """The DRAFT filter empties while the unfiltered list still holds one row.

        The PRD says: "The `meta` block of a list response carries `limit`, `offset`,
        `total_count` — the count of rows matching the filter before the window is applied
        — and `has_more`, which is true when rows remain beyond the current window."

        Design: Corner/endpoints/lease_disposition_create_read_and_filtered_list_round_trip
        """
        scenario = _selling_store("S-5005", "NY-GOB-5005")
        created = validate_success(_open_lease_raw(scenario["store"]["id"]), 201)
        api_client.send_lease_offer(
            created["id"], {"offered_surrender_payment_cents": 300000},
            make_consultant_headers(),
        )
        _rows, filtered_meta = _draft_filtered_list(scenario["store"]["id"])
        assert filtered_meta["total_count"] == 0
        _all_rows, all_meta = validate_paginated(
            api_client.list_lease_dispositions(
                scenario["store"]["id"], make_consultant_headers()
            )
        )
        assert all_meta["total_count"] == 1

"""Cyclic deal/title lifecycles, transitive fund/contract cascades, and
cross-entity state dependencies.

Difficulty queue (A) instances: non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    ApiErrorId, TEST_USERS, fixtures,
)
from test_helpers import factories as f

INV = TEST_USERS["inventory_clerk_headers"]
SALES = TEST_USERS["sales_manager_headers"]
FIN = TEST_USERS["finance_manager_headers"]
TITLE = TEST_USERS["title_clerk_headers"]


# ===========================================================================
# non_linear_state_machine / nonlinear_deal_cyclic_rehash_loop
# ===========================================================================
class TestDealCyclicRehash:
    def _approved_with_contract(self):
        ctx = fixtures.create_approved_deal(deal_overrides=dict(sale_price_cents=3200000, tax_rate_bps=725))
        deal_id = ctx["deal_id"]
        fc = fixtures.add_finance_contract(deal_id, ctx["lender_program_id"], ctx["deal"]["version"],
                                           markup_bps=200, term_months=72)
        return deal_id, fc["id"]

    def test_redesk_approved_returns_to_desking_and_clears_approval(self, api):
        """PRD §3.3: "a deal in `APPROVED` may be desked back to `DESKING`, which
        invalidates the approval (the deal's `approved_lender_program_id` is
        cleared to null) and supersedes any ACTIVE finance contract on the deal
        (that contract transitions `ACTIVE → SUPERSEDED`), then re-quotes; again
        the vehicle must still be `ON_DEAL` for this deal."

        Design: Difficulty/non_linear_state_machine/nonlinear_deal_cyclic_rehash_loop
        """
        deal_id, fc_id = self._approved_with_contract()
        redesked = validate_success(api.desk_deal(deal_id, SALES))
        assert redesked["status"] == "DESKING"
        assert redesked["approved_lender_program_id"] is None

    def test_redesk_approved_supersedes_active_contract(self, api):
        """PRD §3.3: "a deal in `APPROVED` may be desked back to `DESKING`, which
        invalidates the approval (the deal's `approved_lender_program_id` is
        cleared to null) and supersedes any ACTIVE finance contract on the deal
        (that contract transitions `ACTIVE → SUPERSEDED`), then re-quotes; again
        the vehicle must still be `ON_DEAL` for this deal."

        Design: Difficulty/non_linear_state_machine/nonlinear_deal_cyclic_rehash_loop
        """
        deal_id, fc_id = self._approved_with_contract()
        get_success_data(api.desk_deal(deal_id, SALES))
        fc = validate_success(api.get_finance_contract(fc_id, FIN))
        assert fc["status"] == "SUPERSEDED"


# ===========================================================================
# non_linear_state_machine / nonlinear_title_registration_reject_resubmit_cycle
# ===========================================================================
class TestTitleRejectResubmitCycle:
    def _rejected_title(self):
        ctx = fixtures.create_submitted_title()
        tr_id = ctx["title_registration_id"]
        get_success_data(api_client.dmv_result(
            tr_id, {"result": "REJECT", "rejection_reason": "ODOMETER_MISMATCH"}, TITLE))
        return tr_id

    def test_resubmit_from_rejected_returns_to_submitted(self, api):
        """PRD §3.7: "Submission is allowed from `PENDING` (advancing
        `PENDING → SUBMITTED`) and again from `REJECTED` as a resubmit (advancing
        `REJECTED → SUBMITTED`)."

        Design: Difficulty/non_linear_state_machine/nonlinear_title_registration_reject_resubmit_cycle
        """
        tr_id = self._rejected_title()
        resubmitted = validate_success(api.submit_title_registration(tr_id, TITLE))
        assert resubmitted["status"] == "SUBMITTED"

    def test_resubmit_increments_count_and_clears_reason(self, api):
        """PRD §3.7: "On a resubmission from `REJECTED`, the `resubmit_count`
        increases by one, the `rejection_reason` is cleared, and the `version`
        increments — this branching revert reopens the DMV submission after a
        rejection."

        Design: Difficulty/non_linear_state_machine/nonlinear_title_registration_reject_resubmit_cycle
        """
        tr_id = self._rejected_title()
        resubmitted = validate_success(api.submit_title_registration(tr_id, TITLE))
        assert resubmitted["resubmit_count"] == 1
        assert resubmitted["rejection_reason"] is None


# ===========================================================================
# transitive_cascade / cascade_fund_vehicle_floorplan_title_depth3
# ===========================================================================
class TestFundDepth3Cascade:
    def test_fund_sells_vehicle_and_pays_off_floor_plan(self, api):
        """PRD §3.6: "First, the vehicle is sold: it transitions `ON_DEAL → SOLD`
        and its `version` increments. Second, as a consequence of the sale, the
        vehicle's ACTIVE floor-plan line (if any) is paid off: it transitions
        `ACTIVE → PAID_OFF` and its `principal_outstanding_cents` is set to zero."

        Design: Difficulty/transitive_cascade/cascade_fund_vehicle_floorplan_title_depth3
        """
        ctx = fixtures.create_funded_deal(
            deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725),
            floor_overrides=dict(principal_cents=1800000),
        )
        assert ctx["deal"]["status"] == "FUNDED"
        veh = validate_success(api.get_vehicle(ctx["vehicle_id"], FIN))
        assert veh["status"] == "SOLD"
        line = validate_success(api.get_floor_plan_line(ctx["floor_plan_line_id"], FIN))
        assert line["status"] == "PAID_OFF"
        assert line["principal_outstanding_cents"] == 0

    def test_fund_auto_creates_pending_title(self, api):
        """PRD §3.6: "Third, as a consequence of that payoff, the system
        auto-creates a title registration for this deal in status `PENDING`."

        Design: Difficulty/transitive_cascade/cascade_fund_vehicle_floorplan_title_depth3
        """
        ctx = fixtures.create_funded_deal(
            deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725),
            floor_overrides=dict(principal_cents=1800000),
            with_odometer=False,
        )
        data, meta = validate_pagination_or_list(api.list_title_registrations(TITLE, params={"deal_id": ctx["deal_id"]}))
        assert len(data) == 1, f"expected exactly 1 auto-created title, got {len(data)}"
        assert data[0]["status"] == "PENDING"


# ===========================================================================
# transitive_cascade / cascade_contract_trade_accept_recon_vehicle_depth2
# ===========================================================================
class TestContractDepth2Cascade:
    def _approved_with_trade_and_contract(self):
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        lp = fixtures.create_lender_program(tier="TIER_A", buy_rate_bps=549, max_markup_bps=200,
                                            max_ltv_bps=12500, max_pti_bps=1800, max_term_months=72)
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        deal_id = deal["id"]
        td = get_success_data(api_client.attach_trade_in(
            deal_id, f.create_trade_in_payload(vin="9HGAC1ANCM1000077", acv_cents=800000,
                                               allowance_cents=800000, payoff_cents=500000), SALES))
        get_success_data(api_client.desk_deal(deal_id, SALES))
        fixtures.upload_document(deal_id, "CREDIT_APP")
        fixtures.upload_document(deal_id, "INSURANCE")
        get_success_data(api_client.submit_to_lender(deal_id, SALES))
        approved = get_success_data(api_client.lender_decision(
            deal_id, {"decision": "APPROVE", "lender_program_id": lp["id"]}, FIN))
        fixtures.add_finance_contract(deal_id, lp["id"], approved["version"], markup_bps=100, term_months=72)
        return deal_id, td["id"]

    def test_contract_accepts_attached_trade(self, api):
        """PRD §3.5: "If a trade-in is attached in status `APPRAISED`, it
        transitions `APPRAISED → ACCEPTED`; and as a direct consequence of that
        acceptance, the system creates a `USED` vehicle in status `RECON`
        carrying the trade's `vin`, sets the trade's `acquired_vehicle_id` to the
        new vehicle, and sets the new vehicle's `acquired_from_trade_in_id` back
        to the trade."

        Design: Difficulty/transitive_cascade/cascade_contract_trade_accept_recon_vehicle_depth2
        """
        deal_id, trade_id = self._approved_with_trade_and_contract()
        contracted = validate_success(api.contract_deal(deal_id, FIN))
        assert contracted["status"] == "CONTRACTED"
        trade = validate_success(api.get_trade_in(trade_id, FIN))
        assert trade["status"] == "ACCEPTED"

    def test_contract_creates_recon_vehicle_from_trade(self, api):
        """PRD §3.5: "If a trade-in is attached in status `APPRAISED`, it
        transitions `APPRAISED → ACCEPTED`; and as a direct consequence of that
        acceptance, the system creates a `USED` vehicle in status `RECON`
        carrying the trade's `vin`, sets the trade's `acquired_vehicle_id` to the
        new vehicle, and sets the new vehicle's `acquired_from_trade_in_id` back
        to the trade."

        Design: Difficulty/transitive_cascade/cascade_contract_trade_accept_recon_vehicle_depth2
        """
        deal_id, trade_id = self._approved_with_trade_and_contract()
        get_success_data(api.contract_deal(deal_id, FIN))
        data, meta = validate_pagination_or_list(
            api.list_vehicles(INV, params={"acquired_from_trade_in_id": trade_id}))
        assert len(data) == 1, f"expected exactly 1 RECON vehicle from trade, got {len(data)}"
        assert data[0]["status"] == "RECON"
        assert data[0]["vin"] == "9HGAC1ANCM1000077"


# ===========================================================================
# cross_entity_state_dependency / cross_entity_title_submit_requires_deal_funded
# ===========================================================================
class TestTitleSubmitRequiresFunded:
    def test_title_submit_succeeds_when_deal_funded(self, api):
        """PRD §3.7: "Both submissions are gated identically: the referenced deal
        must be in `FUNDED`, or the submission is rejected with
        `ERR_DEAL_NOT_FUNDED`; and a deal-jacket document of type `ODOMETER` must
        exist for the deal, or it is rejected with `ERR_STIP_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_title_submit_requires_deal_funded
        """
        ctx = fixtures.create_funded_deal(
            deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725),
            floor_overrides=dict(principal_cents=1800000), with_odometer=True)
        submitted = validate_success(api.submit_title_registration(ctx["title_registration_id"], TITLE))
        assert submitted["status"] == "SUBMITTED"

    def test_funded_deal_title_record_starts_pending(self, api):
        """PRD §3.7: "A title registration is auto-created in status `PENDING`
        when its deal funds, referencing the `deal_id`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_title_submit_requires_deal_funded
        """
        ctx = fixtures.create_funded_deal(
            deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725),
            floor_overrides=dict(principal_cents=1800000), with_odometer=False)
        tr = validate_success(api.get_title_registration(ctx["title_registration_id"], TITLE))
        assert tr["status"] == "PENDING"
        assert tr["deal_id"] == ctx["deal_id"]


# ===========================================================================
# cross_entity_state_dependency / cross_entity_deal_contract_requires_vehicle_on_deal
# ===========================================================================
class TestDeskRequiresVehicleAvailable:
    def test_second_deal_on_sold_vehicle_cannot_desk(self, api):
        """PRD §3.3: "The act of desking also reserves the vehicle: the
        referenced vehicle must be `AVAILABLE` (or already `ON_DEAL` reserved to
        this very deal), otherwise the desk is rejected with
        `ERR_VEHICLE_NOT_AVAILABLE`; on a first desk an `AVAILABLE` vehicle
        transitions `AVAILABLE → ON_DEAL` and the vehicle's `version` increments
        by one."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_deal_contract_requires_vehicle_on_deal
        """
        # Fund deal A on a vehicle, which leaves the vehicle SOLD.
        ctx = fixtures.create_funded_deal(
            deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725),
            floor_overrides=dict(principal_cents=1800000))
        vehicle_id = ctx["vehicle_id"]
        # A second deal B references the now-SOLD vehicle.
        cust_b = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        deal_b = fixtures.create_deal(vehicle_id, cust_b["id"], deal_type="FINANCE",
                                      sale_price_cents=2000000, tax_rate_bps=725)
        resp = api.desk_deal(deal_b["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_AVAILABLE.value)

    def test_desk_on_available_vehicle_reserves_it(self, api):
        """PRD §3.3: "on a first desk an `AVAILABLE` vehicle transitions
        `AVAILABLE → ON_DEAL` and the vehicle's `version` increments by one."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_deal_contract_requires_vehicle_on_deal
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        desked = validate_success(api.desk_deal(deal["id"], SALES))
        assert desked["status"] == "DESKING"
        veh_after = get_success_data(api.get_vehicle(veh["id"], FIN))
        assert veh_after["status"] == "ON_DEAL"


# --------------------------------------------------------------------------- #
# helper: tolerate paginated or plain-array list responses
# --------------------------------------------------------------------------- #
def validate_pagination_or_list(response):
    body = response.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    assert response.status_code == 200, f"list expected 200, got {response.status_code}: {body}"
    return data, meta

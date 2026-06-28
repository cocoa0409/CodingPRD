"""Non-linear state machines and transitive cascades (depth queue A — rules 3, 4).

Covers the cyclic renewal loop, the parallel schedule/billing dimensions, and the two
depth-3 cascades: renewal accept (new contract minted + old expired) and RESTOCK settle
(restock order minted + inventory decremented).
"""
import pytest
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_paginated,
    create_crew_payload,
    create_damage_report_payload,
    setup_active_contract,
    create_work_order_with_visits,
    schedule_work_order,
    create_completed_takedown,
    setup_sent_renewal_offer,
    make_client_contact_headers,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
PA = TEST_USERS["platform_admin_headers"]


# =====================================================================
# Rule 3 — non_linear_state_machine
# =====================================================================
class TestContractRenewalCycleRevisitsActive:
    """Difficulty/non_linear_state_machine/contract_renewal_cycle_revisits_active."""

    def _build_sent_offer(self):
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="TREE-E-CYC", sku_overrides={"unit_replacement_cents": 9000, "on_hand_qty": 30},
            line_quantity=4, unit_install_cents=5000)
        renewal = setup_sent_renewal_offer(ctx)
        return ctx, renewal

    def test_decline_reverts_contract_to_active(self):
        """PRD §3.9: "Declining advances the offer `SENT` to `DECLINED` (permitted only when
        `SENT`) and reverts the parent contract from `RENEWAL_OFFERED` back to `ACTIVE`, so
        that another offer may be issued later — the renewal loop is cyclic."

        Design: Difficulty/non_linear_state_machine/contract_renewal_cycle_revisits_active
        """
        ctx, renewal = self._build_sent_offer()
        cc = make_client_contact_headers(ctx["client_id"])
        validate_success(api_client.decline_renewal_offer(renewal["offer"]["id"], cc), 200)
        contract = validate_success(api_client.get_contract(ctx["contract_id"], AM), 200)
        assert contract["status"] == "ACTIVE", (
            f"expected contract reverted to ACTIVE, got {contract['status']}")

    def test_decline_sets_offer_declined(self):
        """PRD §3.9: "Declining advances the offer `SENT` to `DECLINED` (permitted only when
        `SENT`) and reverts the parent contract from `RENEWAL_OFFERED` back to `ACTIVE`, so
        that another offer may be issued later — the renewal loop is cyclic."

        Design: Difficulty/non_linear_state_machine/contract_renewal_cycle_revisits_active
        """
        ctx, renewal = self._build_sent_offer()
        cc = make_client_contact_headers(ctx["client_id"])
        declined = validate_success(api_client.decline_renewal_offer(renewal["offer"]["id"], cc), 200)
        assert declined["status"] == "DECLINED", (
            f"expected offer DECLINED, got {declined['status']}")


class TestWorkOrderParallelDimensionsIndependent:
    """Difficulty/non_linear_state_machine/workorder_parallel_dimensions_independent_on_workorder."""

    def _build_completed_wo(self):
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="WREATH-F-PAR", sku_overrides={"category": "WREATH", "unit_replacement_cents": 7000, "on_hand_qty": 30},
            line_quantity=4, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="Delta PAR"), FS))
        wo, visits = create_work_order_with_visits(ctx["contract_id"], job_type="INSTALL")
        schedule_work_order(wo["id"], crew["id"], "2026-11-25T00:00:00Z")
        get_success_data(api_client.dispatch_work_order(wo["id"], FS))
        get_success_data(api_client.complete_visit(visits[0]["id"], {"actual_minutes": 60}, FS))
        completed = get_success_data(api_client.complete_work_order(wo["id"], FS))
        return wo, completed

    def test_schedule_status_completed_after_complete(self):
        """PRD §3.4: "from `DISPATCHED` completes it, moving it to `COMPLETED`."

        Design: Difficulty/non_linear_state_machine/workorder_parallel_dimensions_independent_on_workorder
        """
        _wo, completed = self._build_completed_wo()
        assert completed["schedule_status"] == "COMPLETED"
        assert completed["billing_status"] == "PENDING"

    def test_billing_status_advances_independently_of_schedule(self):
        """PRD §3.5: "An account manager invoices a work order, advancing its `billing_status`
        from `PENDING` to `INVOICED`; invoicing requires the `billing_status` to be `PENDING`
        and the `schedule_status` to already be `COMPLETED`."

        Design: Difficulty/non_linear_state_machine/workorder_parallel_dimensions_independent_on_workorder
        """
        wo, _completed = self._build_completed_wo()
        invoiced = validate_success(api_client.invoice_work_order(wo["id"], AM), 200)
        assert invoiced["schedule_status"] == "COMPLETED", (
            "schedule_status must stay COMPLETED while billing advances")
        assert invoiced["billing_status"] == "INVOICED"


# =====================================================================
# Rule 4 — transitive_cascade
# =====================================================================
class TestRenewalAcceptDepth3:
    """Difficulty/transitive_cascade/renewal_accept_depth3_new_contract_and_expire."""

    def _build_and_accept(self):
        # No damage: final == provisional == 514500 (490000 * 1.05).
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="TREE-G-CAS", sku_overrides={"unit_replacement_cents": 9000, "on_hand_qty": 60},
            line_quantity=50, unit_install_cents=10000)
        renewal = setup_sent_renewal_offer(ctx)
        cc = make_client_contact_headers(ctx["client_id"])
        accepted = validate_success(api_client.accept_renewal_offer(renewal["offer"]["id"], cc), 200)
        return ctx, accepted

    def test_accept_marks_offer_accepted_with_final_price(self):
        """PRD §3.9: "First the offer is marked `ACCEPTED` and its `final_price_cents` is
        computed by the renewal-pricing rule above."

        Design: Difficulty/transitive_cascade/renewal_accept_depth3_new_contract_and_expire
        """
        _ctx, accepted = self._build_and_accept()
        assert accepted["status"] == "ACCEPTED"
        assert accepted["final_price_cents"] == 514500, (
            f"expected final 514500, got {accepted['final_price_cents']}")

    def test_accept_expires_old_and_mints_new_signed_contract(self):
        """PRD §3.9: "Second, a brand-new `Contract` is minted in `status` `SIGNED`, with its
        `renewed_from_contract_id` set to the accepted offer's contract `id`, its
        `total_amount_cents` set to the offer's `final_price_cents`, and its `season_year` set
        to the old contract's `season_year` plus one. Third, the old contract's `status` is
        moved to `EXPIRED`, retiring it."

        Design: Difficulty/transitive_cascade/renewal_accept_depth3_new_contract_and_expire
        """
        ctx, _accepted = self._build_and_accept()
        old = validate_success(api_client.get_contract(ctx["contract_id"], AM), 200)
        assert old["status"] == "EXPIRED"
        data, _meta = validate_paginated(api_client.list_contracts(
            AM, params={"renewed_from_contract_id": ctx["contract_id"]}))
        assert len(data) == 1, f"expected exactly 1 renewed contract, got {len(data)}"
        new_contract = data[0]
        assert new_contract["status"] == "SIGNED"
        assert new_contract["total_amount_cents"] == 514500


class TestDamageRestockSettleDepth3:
    """Difficulty/transitive_cascade/damage_restock_settle_depth3_inventory_decrement."""

    def _build_assessed_restock(self):
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="STRAND-RS-CAS", sku_overrides={"category": "LIGHTING", "unit_replacement_cents": 4500, "on_hand_qty": 20},
            line_quantity=4, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="Hotel CAS"), FS))
        completed_wo = create_completed_takedown(ctx, crew["id"], scheduled_date="2027-01-10T00:00:00Z")
        dr = get_success_data(api_client.create_damage_report(
            completed_wo["id"], create_damage_report_payload(ctx["sku_id"], damaged_qty=4), FS))
        get_success_data(api_client.assess_damage_report(dr["id"], {"resolution_path": "RESTOCK"}, FS))
        return ctx, dr

    def test_restock_settle_mints_restock_order(self):
        """PRD §3.7: "settling mints a new `RestockOrder` in `status` `REQUESTED` whose
        `damage_report_id` points back to this report and whose `quantity` equals the report's
        `damaged_qty`, and then decrements the referenced inventory item's `on_hand_qty` by
        `damaged_qty`, floored at 0 so stock never goes negative."

        Design: Difficulty/transitive_cascade/damage_restock_settle_depth3_inventory_decrement
        """
        _ctx, dr = self._build_assessed_restock()
        settled = validate_success(api_client.settle_damage_report(dr["id"], FS), 200)
        assert settled["status"] == "SETTLED"
        data, _meta = validate_paginated(api_client.list_restock_orders(
            FS, params={"damage_report_id": dr["id"]}))
        assert len(data) == 1, f"expected exactly 1 restock order, got {len(data)}"
        assert data[0]["quantity"] == 4
        assert data[0]["status"] == "REQUESTED"

    def test_restock_settle_decrements_inventory(self):
        """PRD §3.7: "settling mints a new `RestockOrder` in `status` `REQUESTED` whose
        `damage_report_id` points back to this report and whose `quantity` equals the report's
        `damaged_qty`, and then decrements the referenced inventory item's `on_hand_qty` by
        `damaged_qty`, floored at 0 so stock never goes negative."

        Design: Difficulty/transitive_cascade/damage_restock_settle_depth3_inventory_decrement
        """
        ctx, dr = self._build_assessed_restock()
        validate_success(api_client.settle_damage_report(dr["id"], FS), 200)
        item = validate_success(api_client.get_inventory_item(ctx["sku_id"], PA), 200)
        assert item["on_hand_qty"] == 16, (
            f"expected on_hand 20->16 after RESTOCK settle, got {item['on_hand_qty']}")

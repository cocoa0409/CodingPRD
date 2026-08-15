"""Two-variant fee engine, invoice composition, incident hold (PRD §3.6, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_invoice, assert_instant_equals,
    create_main_tariff, place_order, complete,
    invoice_of_assignment,
    make_incident_payload, make_tariff_schedule_payload,
    setup_aboard_scenario, setup_completed_scenario,
)

FINANCE = TEST_USERS["finance_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


class TestDualVariantTariff:
    """gt 25000 / draft 120: the average-rate provisional (single tier prices
    the whole tonnage) and the marginal-rate final (per-tier slices) diverge."""

    def test_provisional_average_rate_at_intake(self, api, vessel_agent_headers):
        """PRD §3.6: "The **provisional average-rate** variant fires at order
        intake and on every amendment that changes `gt` or `draft_dm`: the
        single tier whose band contains the order's `gt` prices the entire
        tonnage at that tier's rate". "when the order's `draft_dm` is strictly
        greater than the schedule's `draft_surcharge_threshold_dm`, the base is
        multiplied by one plus the `draft_surcharge_pct` and rounded half-up to
        integer cents".

        25000 gt in the (20000, inf) tier at 10c -> 250000; draft 120 > 100 ->
        x1.15 -> 287500.

        Design: Difficulty/dual_variant_calc/tariff_provisional_average_vs_final_marginal
        """
        create_main_tariff()
        order = place_order(vessel_name="MV Aurora", gt=25000, draft_dm=120)
        assert order["provisional_fee_cents"] == 287500

    def test_final_marginal_invoice_composition_at_completion(self, api):
        """PRD §3.6: "The **final marginal-rate** variant fires at assignment
        completion and becomes the invoice's `base_fee_cents`: each tier prices
        only the tonnage actually inside its band". "The detention component,
        `detention_fee_cents`, charges for claimed detention beyond the
        schedule's free allowance". "The delay component, `delay_fee_cents`,
        charges the full `delay_minutes` at `delay_rate_cents_per_minute` with
        no allowance." "each component is rounded half-up to integer cents
        first, and `total_cents` is the sum of the three rounded components."
        PRD §3.4: "Completion then mints the invoice: exactly one invoice per
        assignment, born in `ISSUED` status".

        Marginal base: 5000x20 + 15000x15 + 5000x10 = 375000, x1.15 -> 431250.
        Detention: (45-30) x 200 = 3000. Delay: 20 x 150 = 3000. The same
        declared inputs price differently under the two variants
        (287500 at intake vs 431250 here).

        Design: Difficulty/dual_variant_calc/tariff_provisional_average_vs_final_marginal
        """
        ctx = setup_aboard_scenario(gt=25000, draft_dm=120, vessel_name="MV Aurora",
                                    scheduled_start="2026-08-10T10:00:00Z",
                                    scheduled_end="2026-08-10T12:00:00Z")
        complete(ctx["assignment"], detention_minutes=45, delay_minutes=20)
        invoice = invoice_of_assignment(ctx["assignment"]["id"])
        assert_invoice(invoice)
        assert invoice["base_fee_cents"] == 431250
        assert invoice["detention_fee_cents"] == 3000
        assert invoice["delay_fee_cents"] == 3000
        assert invoice["total_cents"] == 437250
        assert invoice["status"] == "ISSUED"
        assert 431250 != ctx["order"]["provisional_fee_cents"]


class TestMarginalStraddle:
    def _complete_gt8000_draft120(self, detention, delay):
        ctx = setup_aboard_scenario(gt=8000, draft_dm=120, vessel_name="MV Bravo",
                                    order_type="DEPARTURE",
                                    scheduled_start="2026-08-10T10:00:00Z",
                                    scheduled_end="2026-08-10T12:00:00Z")
        complete(ctx["assignment"], detention, delay)
        return invoice_of_assignment(ctx["assignment"]["id"])

    def test_final_base_marginal_straddle_with_surcharge(self, api):
        """PRD §3.6: "each tier prices only the tonnage actually inside its
        band — for each tier, the chargeable tonnage is the smaller of the
        order's `gt` and the tier's upper bound, minus the tier's lower bound,
        floored at zero — and the per-tier products are summed." "when the
        order's `draft_dm` is strictly greater than the schedule's
        `draft_surcharge_threshold_dm`, the base is multiplied by one plus the
        `draft_surcharge_pct` and rounded half-up to integer cents".

        gt 8000 straddles two tiers: 5000x20 + 3000x15 = 145000; draft 120 >
        100 triggers x1.15 -> 166750.

        Design: Difficulty/combinatorial_formula/tariff_marginal_tier_straddle_with_conditional_surcharge
        """
        invoice = self._complete_gt8000_draft120(detention=10, delay=5)
        assert invoice["base_fee_cents"] == 166750

    def test_detention_within_free_allowance_and_delay_charged(self, api):
        """PRD §3.6: "The detention component, `detention_fee_cents`, charges
        for claimed detention beyond the schedule's free allowance: the greater
        of zero and (`detention_minutes` minus `detention_free_minutes`),
        multiplied by `detention_rate_cents_per_minute`. The delay component,
        `delay_fee_cents`, charges the full `delay_minutes` at
        `delay_rate_cents_per_minute` with no allowance."

        Detention 10 < 30 free -> 0; delay 5 x 150 = 750; total is base +
        detention + delay.

        Design: Difficulty/combinatorial_formula/tariff_marginal_tier_straddle_with_conditional_surcharge
        """
        invoice = self._complete_gt8000_draft120(detention=10, delay=5)
        assert invoice["detention_fee_cents"] == 0
        assert invoice["delay_fee_cents"] == 750
        assert invoice["total_cents"] == 167500


class TestIncidentHoldOnFinalize:
    def test_finalize_blocked_while_incident_open(self, api):
        """PRD §3.8: "While any incident on the assignment sits in `REPORTED`
        or `UNDER_REVIEW`, finalization is rejected with
        `ERR_INCIDENT_HOLD_ACTIVE` (HTTP 422)."

        Both open states block the same finalize call.

        Design: Difficulty/cross_entity_state_dependency/invoice_finalize_blocked_by_open_incident
        """
        ctx = setup_completed_scenario()
        incident = validate_success(api.create_incident(
            make_incident_payload(ctx["assignment"]["id"], incident_type="EQUIPMENT",
                description="radio failure reported"), DISPATCHER), 201)

        res = api.finalize_invoice(ctx["invoice"]["id"], FINANCE)
        validate_error(res, ApiErrorId.ERR_INCIDENT_HOLD_ACTIVE)

        validate_success(api.open_incident_review(incident["id"], INVESTIGATOR), 200)
        res2 = api.finalize_invoice(ctx["invoice"]["id"], FINANCE)
        validate_error(res2, ApiErrorId.ERR_INCIDENT_HOLD_ACTIVE)

    def test_finalize_unblocked_after_incident_dismissed(self, api):
        """PRD §3.8: "A `FinanceOfficer` finalizes an `ISSUED` invoice, stamping
        `finalized_at` from the logical clock — but only when no incident
        attached to the same assignment is still open."
        PRD §3.9: "Dismissal moves `UNDER_REVIEW → DISMISSED`".

        After the incident is dismissed the same finalize succeeds; with the
        clock never advanced, `finalized_at` is the startup instant.

        Design: Difficulty/cross_entity_state_dependency/invoice_finalize_blocked_by_open_incident
        """
        ctx = setup_completed_scenario()
        incident = validate_success(api.create_incident(
            make_incident_payload(ctx["assignment"]["id"], incident_type="EQUIPMENT",
                description="radio failure reported"), DISPATCHER), 201)
        validate_success(api.open_incident_review(incident["id"], INVESTIGATOR), 200)
        validate_success(api.dismiss_incident(incident["id"], INVESTIGATOR), 200)

        finalized = validate_success(
            api.finalize_invoice(ctx["invoice"]["id"], FINANCE), 200)
        assert finalized["status"] == "FINALIZED"
        assert_instant_equals(finalized["finalized_at"], "2026-08-01T00:00:00Z")


class TestFinalizeRbac:
    def test_rbac_vesselagent_cannot_finalize_forbidden(self, api, vessel_agent_headers):
        """PRD §2.1: "A request whose role is not permitted on the targeted
        endpoint, or that fails an ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST `/pilotage/invoices/{id}/finalize` | Finalize an `ISSUED`
        invoice; blocked by open incidents on the assignment | FinanceOfficer".

        Design: Corner/rbac/rbac_vesselagent_cannot_finalize_forbidden
        """
        ctx = setup_completed_scenario()
        res = api.finalize_invoice(ctx["invoice"]["id"], vessel_agent_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        invoice = validate_success(
            api.get_invoice(ctx["invoice"]["id"], FINANCE), 200)
        assert invoice["status"] == "ISSUED"


class TestTariffPublicationRbac:
    def test_tariff_create_by_dispatcher_forbidden(self, api, dispatcher_headers):
        """PRD §2.1: "A request whose role is not permitted on the targeted
        endpoint, or that fails an ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST `/pilotage/tariff-schedules` | Publish an effective-dated
        tariff schedule | AssociationAdmin".

        Design: Corner/validations/tariff_create_by_dispatcher_forbidden
        """
        res = api.create_tariff_schedule(make_tariff_schedule_payload(),
                                         dispatcher_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

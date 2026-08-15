"""Alpha-acid lab tests: posting gates, immutability, and the regrade cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_lab_test_payload, create_dried_lot, setup_harvesting_plan_with_kiln,
    setup_delivered_allocation, assert_lab_test,
)


def _setup_dried_lot_with_provisional():
    """One DRIED lot carrying a PROVISIONAL 12.0 result (no FINAL)."""
    ctx = setup_harvesting_plan_with_kiln()
    lot = create_dried_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                           wet_lbs=1875, dried_lbs=500, provisional_alpha=12.0)
    return ctx, lot


class TestFinalPostingGates:
    def test_final_without_provisional_rejected(self, api, lab_technician_headers):
        """PRD §3.3: "A `FINAL` result is stricter: the lot must already carry at
        least one provisional, otherwise the final is rejected with
        `ERR_PROVISIONAL_REQUIRED`".

        Design: Corner/validations/provisional_required_before_final
        """
        ctx = setup_harvesting_plan_with_kiln()
        lot = create_dried_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                               wet_lbs=1875, dried_lbs=500)
        res = api.create_lab_test(
            create_lab_test_payload(lot["id"], "FINAL", 12.0), lab_technician_headers)
        validate_error(res, ApiErrorId.ERR_PROVISIONAL_REQUIRED)

    def test_second_final_rejected(self, api, lab_technician_headers):
        """PRD §3.3: "a lot may carry at most one final — a second is rejected
        with `ERR_DUPLICATE_FINAL_TEST`."

        Design: Corner/validations/duplicate_final_test_rejected
        """
        ctx, lot = _setup_dried_lot_with_provisional()
        validate_success(api.create_lab_test(
            create_lab_test_payload(lot["id"], "FINAL", 12.0),
            lab_technician_headers), 201)
        res = api.create_lab_test(
            create_lab_test_payload(lot["id"], "FINAL", 12.5), lab_technician_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_FINAL_TEST)


class TestLabTestImmutability:
    def test_lab_test_record_carries_no_version_or_updated_at(
            self, api, lab_technician_headers):
        """PRD §2.4: "One resource family is deliberately leaner: a `LabTest`
        carries only `id` and `created_at` — a posted lab result is an immutable
        record, and both `updated_at` and `version` are absent from it."

        Design: Corner/entities/labtest_immutability
        """
        ctx, lot = _setup_dried_lot_with_provisional()
        created = get_success_data(api.list_lab_tests(
            lab_technician_headers, params={"harvest_lot_id": lot["id"]}))
        test_id = created[0]["id"]
        data = validate_success(api.get_lab_test(test_id, lab_technician_headers), 200)
        assert_lab_test(data)
        assert data["harvest_lot_id"] == lot["id"]
        assert data["test_type"] == "PROVISIONAL"
        assert data["alpha_pct"] == 12.0


class TestRegradeCascade:
    def _setup_pending_final_delivery(self, api):
        """Pellet lot from source A (dried 500, PROVISIONAL 13.0 only) and source
        B (dried 300, PROVISIONAL+FINAL 14.0); contract for exactly the pellet
        quantity; allocation confirmed and delivered."""
        return setup_delivered_allocation(
            sources=[
                {"wet_lbs": 1875, "dried_lbs": 500, "provisional_alpha": 13.0},
                {"wet_lbs": 1125, "dried_lbs": 300, "provisional_alpha": 14.0,
                 "final_alpha": 14.0},
            ],
            contract_overrides={"annual_volume_lbs": 736},
        )

    def test_final_post_regrades_pellet_blend(self, api, farm_manager_headers,
                                              lab_technician_headers):
        """PRD §3.3: "Posting a final fires the **regrade cascade**. Every pellet
        lot whose blend includes the tested lot recomputes its
        `blended_alpha_pct` (§3.4)". PRD §3.4: "for each source lot, the
        effective alpha is its `alpha_pct_final` when set, otherwise its
        `alpha_pct_provisional`". Blend moves (500 x 13.0 + 300 x 14.0) / 800 =
        13.38 to (500 x 12.0 + 300 x 14.0) / 800 = 12.75.

        Design: Difficulty/transitive_cascade/lab_finalize_regrades_downstream
        """
        ctx = self._setup_pending_final_delivery(api)
        assert ctx["pellet"]["blended_alpha_pct"] == 13.38, "pre-cascade blend"
        lot_a = ctx["lots"][0]
        validate_success(api.create_lab_test(
            create_lab_test_payload(lot_a["id"], "FINAL", 12.0),
            lab_technician_headers), 201)
        lot_after = validate_success(
            api.get_harvest_lot(lot_a["id"], farm_manager_headers), 200)
        assert lot_after["alpha_pct_final"] == 12.0, "the final posts onto the lot"
        pellet_after = validate_success(
            api.get_pellet_lot(ctx["pellet"]["id"], farm_manager_headers), 200)
        assert pellet_after["blended_alpha_pct"] == 12.75, (
            "regrade recomputes the blend over the improved alpha data")

    def test_final_post_reprices_delivered_allocation(self, api, contract_manager_headers,
                                                      lab_technician_headers):
        """PRD §3.3: "every allocation that has been delivered but not yet settled
        and whose delivered lots include such a pellet lot recomputes its
        `delivered_alpha_pct` and its `estimated_unit_price_cents` — the
        provisional pricing variant runs again over the improved alpha data."
        Estimate moves 500 + 1.38 x 40 = 555 to 500 + 0.75 x 40 = 530.

        Design: Difficulty/transitive_cascade/lab_finalize_regrades_downstream
        """
        ctx = self._setup_pending_final_delivery(api)
        allocation = ctx["allocation"]
        assert allocation["delivered_alpha_pct"] == 13.38
        assert allocation["estimated_unit_price_cents"] == 555, (
            "provisional variant over blend 13.38 against floor 12.0")
        lot_a = ctx["lots"][0]
        validate_success(api.create_lab_test(
            create_lab_test_payload(lot_a["id"], "FINAL", 12.0),
            lab_technician_headers), 201)
        after = validate_success(
            api.get_allocation(allocation["id"], contract_manager_headers), 200)
        assert after["delivered_alpha_pct"] == 12.75
        assert after["estimated_unit_price_cents"] == 530, (
            "the provisional variant runs again over the regraded blend")

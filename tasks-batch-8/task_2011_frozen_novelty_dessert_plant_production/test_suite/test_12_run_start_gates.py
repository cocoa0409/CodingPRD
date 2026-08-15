"""Run-start gates, mix-litre conservation, format/copack/discontinued
referential checks (PRD §3.1, §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    complete_run_ok,
    create_booking,
    create_contract,
    create_customer,
    create_product,
    create_released_batch,
    create_run,
    create_verified_changeover,
    get_lot_for_run,
    get_success_data,
    make_customer_rep_headers,
    make_line_operator_headers,
    make_qa_manager_headers,
    setup_mix_assigned_run,
    setup_plant,
    start_run,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PM, PLANNER
from test_helpers.factories import create_product_payload


class TestMixLitresConservation:
    def test_mix_litres_conservation_consume_then_reject(self, api):
        """PRD §3.3: "litres_consumed is the running sum of metered litres
        consumed by completed runs, litres_wasted is the litres written off
        at reject or expiry, and litres_remaining is always litres_produced
        minus litres_consumed minus litres_wasted." After a 200-litre
        consumption, rejecting the 500-litre batch writes off the remaining
        300: consumed 200.0, wasted 300.0, remaining 0.0.

        Design: Difficulty/compensating_invariant/mix_litres_conservation
        """
        ctx = _consume_200(api)
        rejected = validate_success(api.reject_mix_batch(
            ctx["batch"]["id"], _qa()))
        assert rejected["status"] == "REJECTED"
        assert rejected["litres_consumed"] == 200.0
        assert rejected["litres_wasted"] == 300.0
        assert rejected["litres_remaining"] == 0.0

    def test_mix_litres_conservation_cancel_detaches_cleanly(self, api):
        """PRD §3.5: "from MIX_ASSIGNED it clears mix_batch_id to null with
        no litres consumed." A run canceled from MIX_ASSIGNED consumes
        nothing, so the batch's 500.0 produced litres remain fully
        available until the reject writes the un-consumed remainder off.

        Design: Difficulty/compensating_invariant/mix_litres_conservation
        """
        ctx = _consume_200(api)
        # Second run assigns the same batch, then is canceled from
        # MIX_ASSIGNED — the compensating un-assign consumes nothing.
        run2 = create_run(ctx["product"]["id"], ctx["line"]["id"],
                          run_code="R-V2", planned_units=1000,
                          scheduled_start="2026-08-10T16:00:00Z")
        validate_success(api.assign_mix(
            run2["id"], {"mix_batch_id": ctx["batch"]["id"]}, PLANNER))
        canceled = validate_success(api.cancel_run(run2["id"], PLANNER))
        assert canceled["status"] == "CANCELED"
        assert canceled["mix_batch_id"] is None
        rejected = validate_success(api.reject_mix_batch(
            ctx["batch"]["id"], _qa()))
        assert rejected["litres_consumed"] == 200.0
        assert rejected["litres_wasted"] == 300.0
        assert rejected["litres_remaining"] == 0.0


class TestRunStartGates:
    def test_allergen_clean_not_verified_rejected(self, api):
        """PRD §3.5: "a VERIFIED Changeover to the run's product must exist
        on the run's line, else ERR_ALLERGEN_CLEAN_NOT_VERIFIED
        (HTTP 422)."

        Design: Corner/validations/allergen_clean_not_verified_rejected
        """
        ctx = setup_mix_assigned_run(run_code="R-AL", with_changeover=False,
                                     with_booking=True)
        resp = api.start_run(ctx["run"]["id"], make_line_operator_headers("op_1"))
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_CLEAN_NOT_VERIFIED)
        run = get_success_data(api.get_production_run(ctx["run"]["id"], PM))
        assert run["status"] == "MIX_ASSIGNED"

    def test_run_start_without_booking_rejected(self, api):
        """PRD §3.5: "a BOOKED TunnelBooking for the run must exist, else
        ERR_TUNNEL_BOOKING_REQUIRED (HTTP 422)."

        Design: Corner/validations/run_start_without_booking_rejected
        """
        ctx = setup_mix_assigned_run(run_code="R-NB", with_changeover=True,
                                     with_booking=False)
        resp = api.start_run(ctx["run"]["id"], make_line_operator_headers("op_1"))
        validate_error(resp, ApiErrorId.ERR_TUNNEL_BOOKING_REQUIRED)
        run = get_success_data(api.get_production_run(ctx["run"]["id"], PM))
        assert run["status"] == "MIX_ASSIGNED"

    def test_start_wrong_state_beats_allergen_check(self, api):
        """PRD §2.9: "The evaluation order, from highest priority to lowest,
        is: authentication first, then role authorization, ... then state-
        machine validity, then ownership, then segregation of duties, then
        the domain-specific business, temporal, referential, and fiscal
        checks detailed in §3." A SCHEDULED run (no mix assigned) also lacks
        a verified changeover; state-machine validity outranks the §3 safety
        gate, so the rejection is ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/start_wrong_state_beats_allergen_check
        """
        product, line, _, _ = setup_plant()
        run = create_run(product["id"], line["id"], run_code="R-W",
                         scheduled_start="2026-08-10T14:00:00Z")
        resp = api.start_run(run["id"], make_line_operator_headers("op_1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        run_after = get_success_data(api.get_production_run(run["id"], PM))
        assert run_after["status"] == "SCHEDULED"

    def test_start_wrong_state_masks_allergen_failure(self, api):
        """PRD §2.9: "This ordering means a caller who is both
        unauthenticated and forbidden sees the authentication error, and a
        run-start request that fails both allergen verification and mix
        expiry surfaces the allergen error first." State-machine validity
        sits higher in that same ordering ("then state-machine validity,
        then ownership, then segregation of duties, then the
        domain-specific business ... checks"), so the state failure is
        surfaced and the allergen safety error is not the one returned.

        Design: Difficulty/priority_pair_validation_conflict/start_wrong_state_beats_allergen_check
        """
        product, line, _, _ = setup_plant()
        run = create_run(product["id"], line["id"], run_code="R-W2",
                         scheduled_start="2026-08-10T14:00:00Z")
        resp = api.start_run(run["id"], make_line_operator_headers("op_1"))
        assert resp.status_code == 409, (
            f"expected 409 ERR_INVALID_STATE, got {resp.status_code}: "
            f"{resp.text}")
        assert resp.json()["data"]["error_id"] == "ERR_INVALID_STATE"
        assert resp.json()["data"]["error_id"] != "ERR_ALLERGEN_CLEAN_NOT_VERIFIED"


class TestReferentialGates:
    def test_line_format_mismatch_rejected(self, api):
        """PRD §3.5: "The line's format must equal the product's format
        (ERR_LINE_FORMAT_MISMATCH)."

        Design: Corner/validations/line_format_mismatch_rejected
        """
        product = create_product(**create_product_payload(
            sku_code="BULK-PINT", product_name="Vanilla Pint", format="BULK",
            fill_volume_ml_per_unit=473, target_overrun_pct=30))
        _, line, _, _ = setup_plant()
        resp = api.create_production_run(
            {"run_code": "R-FM", "product_id": product["id"],
             "line_id": line["id"], "planned_units": 100,
             "scheduled_start": "2026-08-10T14:00:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_LINE_FORMAT_MISMATCH)

    def test_copack_contract_required_rejected(self, api):
        """PRD §3.5: "If the product has co_pack_only true, an ACTIVE
        co-pack contract covering that product must exist, else
        ERR_COPACK_CONTRACT_REQUIRED (HTTP 422)."

        Design: Corner/validations/copack_contract_required_rejected
        """
        product = create_product(**create_product_payload(
            sku_code="CP-BAR", product_name="PL Bar", co_pack_only=True))
        _, line, _, _ = setup_plant()
        resp = api.create_production_run(
            {"run_code": "R-NC", "product_id": product["id"],
             "line_id": line["id"], "planned_units": 100,
             "scheduled_start": "2026-08-10T14:00:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_COPACK_CONTRACT_REQUIRED)

    def test_run_create_with_discontinued_product_rejected(self, api):
        """PRD §3.1: "A DISCONTINUED product cannot be referenced by new
        production runs, new changeovers, or new build plans — such
        references are rejected with ERR_PRODUCT_DISCONTINUED (HTTP 422)."

        Design: Corner/validations/run_create_with_discontinued_product_rejected
        """
        product = create_product(sku_code="BAR-OLD", product_name="Old Bar")
        validate_success(api.discontinue_product(product["id"], PM))
        _, line, _, _ = setup_plant()
        resp = api.create_production_run(
            {"run_code": "R-DISC", "product_id": product["id"],
             "line_id": line["id"], "planned_units": 100,
             "scheduled_start": "2026-08-10T14:00:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED)


class TestProductVersionPinned:
    def test_product_version_pinned_rejected(self, api):
        """PRD §3.1: "Editing a product's spec is permitted only while no
        APPROVED or ACTIVE co-pack contract has pinned this product's
        version; an edit attempted while pinned is rejected with
        ERR_PRODUCT_VERSION_PINNED (HTTP 409)."

        Design: Corner/validations/product_version_pinned_rejected
        """
        product = create_product(**create_product_payload(
            sku_code="CP-BAR", product_name="PL Bar", co_pack_only=True))
        customer = create_customer(customer_code="PL-1",
                                   display_name="Big Retailer",
                                   kind="PRIVATE_LABEL")
        contract = create_contract(customer["id"], product["id"],
                                   contract_code="CT-PV")
        validate_success(api.submit_contract(
            contract["id"], make_customer_rep_headers(customer["id"])))
        validate_success(api.approve_contract(contract["id"], PM))
        resp = api.patch_product(product["id"], {"target_overrun_pct": 45}, PM)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_VERSION_PINNED)
        unchanged = get_success_data(api.get_product(product["id"], PM))
        assert unchanged["target_overrun_pct"] == 40


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _qa():
    return make_qa_manager_headers("qa_1")


def _consume_200(api):
    """500-litre batch RELEASED for BAR-VAN-70; one 4000-unit run consumes
    200.0 litres at completion. Returns the fixture context."""
    product, line, tunnel, zone = setup_plant()
    batch = create_released_batch(product["id"], batch_code="MB-V",
                                  litres=500)
    run = create_run(product["id"], line["id"], run_code="R-V1",
                     planned_units=4000,
                     scheduled_start="2026-08-10T14:00:00Z")
    create_verified_changeover(line["id"], product["id"])
    create_booking(tunnel["id"], run["id"])
    validate_success(api.assign_mix(run["id"], {"mix_batch_id": batch["id"]},
                                    PLANNER))
    start_run(run["id"])
    complete_run_ok(run["id"], 4000, 200.0, zone["id"])
    get_lot_for_run(run["id"])
    return {"product": product, "line": line, "tunnel": tunnel,
            "zone": zone, "batch": batch, "run": run}

"""Completing a transfer: side effects, cross-checks and the measurement fork.

Completion is the busiest single call in the system — it closes the logistics
dimension, opens the measurement dimension, releases committed tonnage, rescores
the barge and cascades the stem. Two guards stand in front of it, and the fork it
opens can still be redirected afterwards: a supplier-figures buyer who disputes
ends up settled on an independent surveyor's figure.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    COMPLIANCE,
    OPS,
    add_fuel_grade,
    add_index_quote,
    api_client,
    assert_order_state,
    build_delivered_order,
    build_pumping_order,
    build_reference_data,
    complete_pumping,
    complete_pumping_payload,
    create_delivery_order_payload,
    create_nomination_payload,
    file_joint_survey,
    make_barge_master_headers,
    read_asset,
    read_nomination,
    read_order,
    submit_compliance_decision,
    submit_quantity_decision,
    validate_error,
    validate_success,
)

HSFO_GRADE = {
    "grade_code": "HSFO-380",
    "max_sulfur_pct": 3.500,
    "eca_permitted": False,
    "test_tolerance_pct": 0.050,
    "index_code": "HSFO-ARA",
    "base_barging_rate_usd_per_mt": 8.50,
    "min_barging_fee_usd": 2000.00,
    "cross_contamination_group": "RESIDUAL",
}
HSFO_QUOTE = {"quote_date": "2026-08-03T00:00:00Z", "price_usd_per_mt": 480.00}
MGO_QUOTE = {"quote_date": "2026-08-03T00:00:00Z", "price_usd_per_mt": 705.00}

SCRUBBER_STEM = {
    "vessel_imo": "9990011",
    "vessel_name": "MV Scrubbatrix",
    "scrubber_fitted": True,
    "declared_sulfur_pct": 3.400,
    "eca_documentation_ref": None,
}
HSFO_FIGURES = {
    "barge_sounding_mt": 1198.000,
    "vessel_sounding_mt": 1195.000,
    "meter_mt": 1197.500,
}
HSFO_PUMPING_CLOCK = "2026-08-10T11:30:00Z"

SECOND_WINDOW_START = "2026-08-12T06:00:00Z"
SECOND_WINDOW_END = "2026-08-13T06:00:00Z"
SECOND_SLOT_END = "2026-08-12T12:00:00Z"

INCONSISTENT_FIGURES = {
    "barge_sounding_mt": 1198.450,
    "vessel_sounding_mt": 1197.900,
    "meter_mt": 1196.900,
}

SURVEYED_MT = 1193.700


class TestCompletionSideEffects:
    """One request closes the transfer and settles the tonnage."""

    def test_completion_fires_every_declared_side_effect_at_once(self):
        """PRD §3.5: "A successful completion does a great deal at once. The order
        advances `PUMPING → DELIVERED` on its logistics dimension and `NOT_STARTED →
        FIGURES_RECORDED` on its measurement dimension, storing all three figures. The
        order leaves the asset's committed set, so `committed_quantity_mt` is recomputed.
        The asset's `compliance_score` is recomputed, because a delivered order with no
        spill against it earns the clean-delivery bonus described in §3.6. And the
        nomination cascades `SCHEDULED → DELIVERED` on its fulfilment dimension."
        PRD §3.5: "The supplier's own barge tank sounding governs: `agreed_quantity_mt`
        is `barge_sounding_mt` rounded to three decimal places, `measurement_basis` is
        set to `SUPPLIER_FIGURES`, and `shortfall_mt` is 0.000, because the governing
        figure and the pumped figure are one and the same."
        PRD §3.5: "A successful start writes the nomination's grade onto the asset as
        its `last_grade_id`, which is what makes the segregation rule bite on the asset's
        next stem."
        PRD §3.6: "The score is then 100.00 minus the accumulated penalty plus the bonus,
        rounded to two decimal places, and finally clamped into the inclusive range from
        0.00 to 100.00."

        The buyer contracts on supplier figures, so the measurement dimension runs
        straight through to `AGREED` inside this same request, and the one clean
        delivery's bonus point cannot lift the score past its 100.00 ceiling.

        Design: Corner/state_machines/complete_pumping_executes_all_declared_side_effects
        """
        ctx = build_pumping_order()

        order = complete_pumping(ctx)

        assert_order_state(order, "DELIVERED", "AGREED")
        assert order["agreed_quantity_mt"] == pytest.approx(1198.450, abs=0.0005), (
            "The barge sounding must govern, got "
            f"{order['agreed_quantity_mt']}"
        )
        assert order["measurement_basis"] == "SUPPLIER_FIGURES", (
            f"Expected SUPPLIER_FIGURES, got {order['measurement_basis']}"
        )
        assert order["shortfall_mt"] == pytest.approx(0.000, abs=0.0005), (
            "The governing and pumped figures are the same, so there is no shortfall, "
            f"got {order['shortfall_mt']}"
        )
        assert read_nomination(ctx)["fulfillment_status"] == "DELIVERED", (
            "The stem must cascade to DELIVERED, got "
            f"{read_nomination(ctx)['fulfillment_status']}"
        )
        asset = read_asset(ctx)
        assert asset["committed_quantity_mt"] == pytest.approx(0.000, abs=0.0005), (
            "The delivered order leaves the committed set, got "
            f"{asset['committed_quantity_mt']}"
        )
        assert asset["last_grade_id"] == ctx["grade"]["id"], (
            "The grade written at start-of-pumping must persist, got "
            f"{asset['last_grade_id']}"
        )
        assert asset["compliance_score"] == pytest.approx(100.00, abs=0.01), (
            "No penalty and a bonus clamped at the ceiling leaves 100.00, got "
            f"{asset['compliance_score']}"
        )

    def test_a_meter_more_than_one_tonne_from_the_sounding_blocks_completion(self):
        """PRD §3.5: "The barge sounding and the meter totaliser must agree within a
        tolerance of one tonne — the absolute difference between `barge_sounding_mt` and
        `meter_mt` must be no greater than 1.000 metric tonnes — or the request is
        rejected with `ERR_MEASUREMENT_FIGURES_INCONSISTENT`."
        PRD §3.5: "`meter_mt` exists only to police the barge sounding through the
        one-tonne cross-check at completion."
        PRD §3.1: "`committed_quantity_mt` is the sum of `planned_quantity_mt` across
        the asset's delivery orders whose `logistics_status` is `SCHEDULED`, `CLEARED`
        or `PUMPING`, held to three decimals and initialised to 0.000; it is recomputed
        whenever an order enters or leaves that set."

        A 1.550-tonne gap between sounding and totaliser exceeds the tolerance, so no
        figure may be stored and the order stays mid-transfer.

        Design: Corner/validations/measurement_figures_inconsistent_rejected
        """
        ctx = build_pumping_order()

        response = api_client.complete_pumping(
            ctx["order"]["id"],
            complete_pumping_payload(**INCONSISTENT_FIGURES),
            make_barge_master_headers(ctx["asset"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_MEASUREMENT_FIGURES_INCONSISTENT)
        order = read_order(ctx)
        assert_order_state(order, "PUMPING", "NOT_STARTED")
        for field in ("barge_sounding_mt", "vessel_sounding_mt", "meter_mt",
                      "agreed_quantity_mt"):
            assert order[field] is None, (
                f"A refused completion must store no figure, but {field} is "
                f"{order[field]}"
            )
        assert read_nomination(ctx)["fulfillment_status"] == "SCHEDULED", (
            "The stem must not cascade, got "
            f"{read_nomination(ctx)['fulfillment_status']}"
        )
        assert read_asset(ctx)["committed_quantity_mt"] == pytest.approx(
            1200.000, abs=0.0005
        ), (
            "The order is still in the committed set, got "
            f"{read_asset(ctx)['committed_quantity_mt']}"
        )


class TestDisputeRedirectsTheSettlementBasis:
    """A supplier-figures buyer can still end up settled on a survey figure."""

    def test_the_surveyors_figure_governs_after_a_dispute(self):
        """PRD §3.5: "That dispute right is exercised by the buyer's representative
        through a quantity `decision` of `DISPUTE`, which moves the measurement dimension
        `AGREED → DISPUTED` and clears `agreed_quantity_mt`, `measurement_basis` and
        `shortfall_mt` back to null."
        PRD §3.5: "A disputed order returns to `RESURVEYED` when the surveyor files a
        fresh `surveyed_mt`, which overwrites the previous survey figure, and the cycle
        `AGREED → DISPUTED → RESURVEYED → AGREED` closes when the surveyor agrees the
        resurveyed figure on the joint-survey basis."
        PRD §3.5: "The surveyor then closes the loop with a quantity `decision` of
        `AGREE`, advancing `RESURVEYED → AGREED` provided `surveyed_mt` is not null: the
        surveyor's figure governs, so `agreed_quantity_mt` is `surveyed_mt` rounded to
        three decimal places, `measurement_basis` is set to `JOINT_SURVEY`, and
        `shortfall_mt` is `barge_sounding_mt` minus `agreed_quantity_mt`, rounded to
        three decimal places — normally a positive difference the supplier absorbs."

        The buyer's contract is `SUPPLIER_FIGURES`, so the first settlement was on the
        barge sounding of 1198.450; after the dispute the 1193.700 survey governs and
        the supplier absorbs the 4.750-tonne difference.

        Design: Corner/calculations/joint_survey_variant_selected_after_dispute_despite_supplier_basis
        """
        ctx = build_delivered_order()
        assert ctx["customer"]["settlement_basis"] == "SUPPLIER_FIGURES", (
            "The buyer must contract on supplier figures, got "
            f"{ctx['customer']['settlement_basis']}"
        )
        assert ctx["order"]["measurement_basis"] == "SUPPLIER_FIGURES", (
            "The first settlement must be on the supplier basis, got "
            f"{ctx['order']['measurement_basis']}"
        )

        disputed = submit_quantity_decision(ctx, "DISPUTE")
        assert disputed["measurement_status"] == "DISPUTED", (
            f"Expected DISPUTED, got {disputed['measurement_status']}"
        )
        assert disputed["measurement_basis"] is None, (
            "The dispute must clear the basis, got "
            f"{disputed['measurement_basis']}"
        )
        file_joint_survey(ctx, SURVEYED_MT)

        agreed = submit_quantity_decision(ctx, "AGREE")

        assert_order_state(agreed, "DELIVERED", "AGREED")
        assert agreed["measurement_basis"] == "JOINT_SURVEY", (
            "The survey basis must supersede the contractual one, got "
            f"{agreed['measurement_basis']}"
        )
        assert agreed["agreed_quantity_mt"] == pytest.approx(SURVEYED_MT, abs=0.0005), (
            f"The survey figure must govern, got {agreed['agreed_quantity_mt']}"
        )
        assert agreed["shortfall_mt"] == pytest.approx(4.750, abs=0.0005), (
            "1198.450 less 1193.700 is 4.750, got "
            f"{agreed['shortfall_mt']}"
        )
        assert agreed["barge_sounding_mt"] == pytest.approx(1198.450, abs=0.0005), (
            "The pumped figures are evidence and must survive, got "
            f"{agreed['barge_sounding_mt']}"
        )
        assert agreed["meter_mt"] == pytest.approx(1197.800, abs=0.0005), (
            f"The totaliser must survive too, got {agreed['meter_mt']}"
        )


class TestQuarantineReleasePrecondition:
    """Return-to-service is defined only out of `QUARANTINED`."""

    def test_returning_an_available_barge_to_service_is_refused(self):
        """PRD §3.6: "Releasing a quarantined asset back into service is likewise the
        compliance desk's call, moving `status` `QUARANTINED → AVAILABLE`. The asset must
        actually be quarantined — a request against an already-available asset is
        rejected with `ERR_INVALID_ASSET_STATE` — and no spill incident on the asset may
        remain `OPEN`, else the request is rejected with `ERR_OPEN_SPILL_INCIDENT`."
        PRD §3.1: "`status` is `AVAILABLE` on registration and becomes `QUARANTINED`
        only through the major-spill cascade described in §3.6."
        PRD §3.1: "`compliance_score` is initialised to 100.00 and is the asset's
        spill-history score, computed as described in §3.6."

        The barge has never spilled, so the release has nothing to release and must not
        silently succeed or rescore anything.

        Design: Corner/state_machines/return_to_service_on_available_asset_rejected
        """
        ctx = build_reference_data(quotes=[])
        assert ctx["asset"]["status"] == "AVAILABLE", (
            f"A freshly registered barge is available, got {ctx['asset']['status']}"
        )

        response = api_client.return_asset_to_service(ctx["asset"]["id"], COMPLIANCE)

        validate_error(response, ApiErrorId.ERR_INVALID_ASSET_STATE)
        asset = read_asset(ctx)
        assert asset["status"] == "AVAILABLE", (
            f"The refused release must leave the status alone, got {asset['status']}"
        )
        assert asset["compliance_score"] == pytest.approx(100.00, abs=0.01), (
            "An unblemished barge keeps its perfect score, got "
            f"{asset['compliance_score']}"
        )


class TestGradeSegregationAcrossStems:
    """What the barge last carried constrains what it may carry next."""

    def test_a_distillate_stem_is_refused_on_a_barge_that_last_ran_residual(self):
        """PRD §3.4: "And the asset must be able to carry the grade: either its
        `last_grade_id` is null, or the cross-contamination family of the grade it last
        carried matches the family of the nominated grade, or the asset has
        `segregated_tanks`; failing all three, the request is rejected with
        `ERR_GRADE_INCOMPATIBLE_ASSET`."
        PRD §3.5: "A successful start writes the nomination's grade onto the asset as
        its `last_grade_id`, which is what makes the segregation rule bite on the asset's
        next stem."
        PRD §3.1: "`cross_contamination_group` places the grade in a segregation family
        — `DISTILLATE`, `RESIDUAL` or `BIOBLEND` — which later determines whether a barge
        that last carried something else needs segregated tanks."

        The barge has just run a `RESIDUAL` stem and has no segregated tanks, so the
        `DISTILLATE` stem behind it cannot be slotted onto it at all.

        Design: Corner/validations/residual_then_distillate_on_unsegregated_barge_rejected
        """
        ctx = build_delivered_order(
            grade=HSFO_GRADE,
            quotes=[HSFO_QUOTE],
            asset={"segregated_tanks": False},
            nomination=SCRUBBER_STEM,
            figures=HSFO_FIGURES,
            pumping_clock=HSFO_PUMPING_CLOCK,
        )
        residual_grade_id = ctx["grade"]["id"]
        distillate = add_fuel_grade()
        add_index_quote(distillate["id"], **MGO_QUOTE)
        distillate_stem = validate_success(
            api_client.create_nomination(
                create_nomination_payload(
                    ctx["customer"]["id"],
                    ctx["port"]["id"],
                    distillate["id"],
                    vessel_imo="9445566",
                    vessel_name="MV Distillatus",
                    window_start=SECOND_WINDOW_START,
                    window_end=SECOND_WINDOW_END,
                    eca_documentation_ref="CHG-2026-0013",
                ),
                OPS,
            ),
            201,
        )
        submit_compliance_decision(ctx, "APPROVE", nomination_id=distillate_stem["id"])
        confirmed = validate_success(
            api_client.confirm_nomination(distillate_stem["id"], OPS)
        )

        response = api_client.create_delivery_order(
            create_delivery_order_payload(
                confirmed["id"],
                ctx["asset"]["id"],
                confirmed["version"],
                slot_start=SECOND_WINDOW_START,
                slot_end=SECOND_SLOT_END,
            ),
            OPS,
        )

        validate_error(response, ApiErrorId.ERR_GRADE_INCOMPATIBLE_ASSET)
        asset = read_asset(ctx)
        assert asset["last_grade_id"] == residual_grade_id, (
            "The barge must still record the residual grade it ran, got "
            f"{asset['last_grade_id']}"
        )
        assert asset["status"] == "AVAILABLE", (
            f"The refusal is not a quarantine, got {asset['status']}"
        )
        assert asset["committed_quantity_mt"] == pytest.approx(0.000, abs=0.0005), (
            "No tonnage may be committed by a refused slot, got "
            f"{asset['committed_quantity_mt']}"
        )
        after = read_nomination(nomination_id=confirmed["id"])
        assert after["fulfillment_status"] == "CONFIRMED", (
            f"The refused stem must stay CONFIRMED, got {after['fulfillment_status']}"
        )
        assert after["version"] == confirmed["version"], (
            f"A refused slot must not move the version, expected "
            f"{confirmed['version']}, got {after['version']}"
        )

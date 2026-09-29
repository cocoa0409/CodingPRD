"""Line-of-sight variants and the pinned money arithmetic.

Four families of claims live here, all of them arithmetic the PRD pins down to a
single answer:

* the desktop path study and its field-survey twin, which share every formula and
  differ only in the two heights they read;
* the equipment settlement, whose sign flips between a rental liability and a
  purchase refund;
* the install invoice, whose discount tier is chosen from the pre-discount
  subtotal while the regulatory fee is charged on the post-discount net;
* the ground-lease escalation, which compounds on the already-rounded rent of the
  previous lease year.

Every helper and fixture comes from `test_helpers`; the harness restarts the
server with an empty database before each test, so each test builds its own plant.
"""

import pytest

from test_helpers import validate_success
from test_helpers.assertions import (
    assert_equipment_assignment,
    assert_install_work_order,
    assert_no_mutation,
    assert_serviceability_request,
    assert_tower,
)
from test_helpers.fixtures import (
    SURVEY_PRESETS,
    SURVEYOR_USER_ID,
    advance_clock,
    cancel_subscriber,
    complete_work_order,
    create_serviceability_request,
    create_subscriber,
    create_tower,
    create_work_order,
    decide_exception,
    get_assignment_for_subscriber,
    get_serviceability_request,
    get_subscriber,
    get_tower,
    hold_for_request,
    return_equipment,
    set_clock,
    settle_unreturned_equipment,
    setup_active_subscriber,
    setup_return_pending_assignment,
    setup_scheduled_work_order,
    setup_write_off_ready_assignment,
    survey_work_order,
)


# --------------------------------------------------------------------------
# Local composite setups, built from the Tier-0 helpers of test_helpers.
# --------------------------------------------------------------------------


def _setup_rental_and_purchase_return_pending(months_in_service: int = 5) -> dict:
    """Two accounts on one sector — one on `RENTAL`, one on `PURCHASE` — installed
    at the same instant, then both cancelled from `ACTIVE` so both radios sit in
    `RETURN_PENDING` with the same tenure behind them.

    The clock is left at the cancellation instant, which is `months_in_service`
    settlement months after deployment. Returns
    {"rental": {...}, "purchase": {...}, "return_due_at": "..."} where each of the
    first two entries carries "subscriber" and "assignment".
    """
    scenario = setup_active_subscriber(equipment_mode="RENTAL")
    tower_id = scenario["tower"]["id"]
    plan_id = scenario["plan"]["id"]

    purchase_request = create_serviceability_request(
        tower_id,
        plan_id,
        contact_name="Bo Iversen",
        premise_latitude=41.2601,
        premise_longitude=-104.7601,
    )
    hold_for_request(purchase_request["id"])
    purchase_subscriber = create_subscriber(
        purchase_request["id"],
        plan_id,
        equipment_mode="PURCHASE",
        billing_email="purchase.b@example.com",
    )
    purchase_work_order = create_work_order(
        purchase_subscriber["id"], scheduled_at="2026-08-02T16:00:00Z"
    )
    survey_work_order(
        purchase_work_order["id"], **SURVEY_PRESETS["NON_PEN_ROOF_TRIPOD"]
    )
    complete_work_order(purchase_work_order["id"], installed_mast_height_m=2.5)

    if months_in_service:
        advance_clock(days=30 * months_in_service)

    cancel_subscriber(scenario["subscriber"]["id"])
    cancel_subscriber(purchase_subscriber["id"])

    rental_assignment = get_assignment_for_subscriber(scenario["subscriber"]["id"])
    purchase_assignment = get_assignment_for_subscriber(purchase_subscriber["id"])

    return {
        "rental": {
            "subscriber": scenario["subscriber"],
            "assignment": rental_assignment,
        },
        "purchase": {
            "subscriber": purchase_subscriber,
            "assignment": purchase_assignment,
        },
        "return_due_at": rental_assignment["return_due_at"],
    }


def _setup_mount_approved(band: str) -> dict:
    """A `MOUNT_APPROVED` truck roll whose `approved_mounting_type` is `band`.

    `WALL_BRACKET` and `NON_PEN_ROOF_TRIPOD` are reached straight from the survey;
    `ROOF_MAST_GUYED` and `GROUND_POLE_MAST` go through an engineering exception
    decided by an operator other than the surveyor.
    """
    if band in ("WALL_BRACKET", "NON_PEN_ROOF_TRIPOD"):
        scenario = setup_scheduled_work_order()
        scenario["work_order"] = survey_work_order(
            scenario["work_order"]["id"], **SURVEY_PRESETS[band]
        )
        return scenario
    scenario = setup_scheduled_work_order()
    scenario["work_order"] = survey_work_order(
        scenario["work_order"]["id"], **SURVEY_PRESETS[band]
    )
    scenario["work_order"] = decide_exception(
        scenario["work_order"]["id"],
        "APPROVE",
        note="Structural review on file",
        approved_mounting_type=band,
    )
    return scenario


# --------------------------------------------------------------------------
# The desktop LiDAR study versus its field-survey twin
# --------------------------------------------------------------------------


class TestDesktopVersusFieldLineOfSight:
    """One premise, two runs of the same clearance arithmetic on different heights."""

    def test_field_survey_diverges_from_desktop_study_on_mounting_band(self):
        """PRD §3.5: "The required antenna height above mean sea level is therefore the obstruction top height plus the clearance requirement plus the partial-path allowance plus the 0.5 metre safety margin."
        PRD §3.5: "The link margin is the tower antenna's height above mean sea level less that required height, rounded half up to one decimal place; a negative margin means the tower cannot see over the obstruction at all."
        PRD §3.5: "The rounded mast requirement selects a mounting band, with every upper bound inclusive: at or below 1.0 metre a `WALL_BRACKET`; above that and at or below 3.0 metres a `NON_PEN_ROOF_TRIPOD`; above that and at or below 6.0 metres a `ROOF_MAST_GUYED`; above that and at or below 12.0 metres a `GROUND_POLE_MAST`."
        PRD §3.7: "Every formula, every clearance band, the partial-path allowance, the 0.5 metre safety margin, the half-metre mast rounding and the four mounting bands are identical; the only differences are that the obstruction height comes from `measured_tree_line_height_m` rather than `declared_tree_line_height_m`, and the mounting surface height comes from `measured_roof_height_m` rather than `roof_height_m`."
        PRD §3.7: "When `field_los_margin_m` is at or above zero, `recommended_mast_height_m` is at or below 12.0, and `recommended_mounting_type` is `ROOF_MAST_GUYED` or `GROUND_POLE_MAST` — with the additional requirement that `structure_penetration_allowed` is true when the band is `ROOF_MAST_GUYED` — the work order moves `SCHEDULED → EXCEPTION_PENDING` and `approved_mounting_type` is deliberately left absent."

        Design: Difficulty/dual_variant_calc/los_desktop_lidar_vs_field_survey_variant_divergence
        """
        scenario = setup_scheduled_work_order()
        request = get_serviceability_request(scenario["request"]["id"])

        # Desktop variant: declared tree line 3.0 m on a 5.0 km path.
        assert_serviceability_request(request)
        assert request["desktop_los_margin_m"] == pytest.approx(28.5, abs=0.01), (
            "desktop_los_margin_m is 1245.0 m of tower antenna less the 1216.5 m "
            f"required over a declared 3.0 m tree line, got {request['desktop_los_margin_m']}"
        )
        assert request["desktop_required_mast_height_m"] == pytest.approx(2.5, abs=0.01), (
            f"desktop_required_mast_height_m must be 2.5, got {request['desktop_required_mast_height_m']}"
        )
        assert request["desktop_mounting_type"] == "NON_PEN_ROOF_TRIPOD", (
            f"a 2.5 m mast selects NON_PEN_ROOF_TRIPOD, got {request['desktop_mounting_type']!r}"
        )

        # Field variant: the technician measures the same tree line at 5.5 m.
        work_order = survey_work_order(
            scenario["work_order"]["id"], **SURVEY_PRESETS["ROOF_MAST_GUYED"]
        )
        assert_install_work_order(work_order)
        assert work_order["field_los_margin_m"] == pytest.approx(26.0, abs=0.01), (
            f"field_los_margin_m must be 26.0, got {work_order['field_los_margin_m']}"
        )
        assert work_order["recommended_mast_height_m"] == pytest.approx(5.0, abs=0.01), (
            f"recommended_mast_height_m must be 5.0, got {work_order['recommended_mast_height_m']}"
        )
        assert work_order["recommended_mounting_type"] == "ROOF_MAST_GUYED", (
            f"a 5.0 m mast selects ROOF_MAST_GUYED, got {work_order['recommended_mounting_type']!r}"
        )

        # The two variants disagree, and the fork follows the field variant.
        assert work_order["recommended_mast_height_m"] != request["desktop_required_mast_height_m"], (
            "the field variant must not reuse the desktop mast requirement"
        )
        assert work_order["recommended_mounting_type"] != request["desktop_mounting_type"], (
            "the field variant must not reuse the desktop mounting band"
        )
        assert work_order["status"] == "EXCEPTION_PENDING", (
            f"a ROOF_MAST_GUYED recommendation with penetration allowed holds for an "
            f"engineering exception, got {work_order['status']!r}"
        )
        assert work_order.get("approved_mounting_type") is None, (
            "approved_mounting_type is deliberately left absent in EXCEPTION_PENDING, got "
            f"{work_order.get('approved_mounting_type')!r}"
        )
        assert work_order["surveyed_by_user_id"] == SURVEYOR_USER_ID, (
            "surveyed_by_user_id records the surveying technician's identifier, got "
            f"{work_order['surveyed_by_user_id']!r}"
        )

    def test_field_survey_leaves_the_desktop_estimate_untouched(self):
        """PRD §3.5: "The desktop study writes its findings onto the enquiry as `desktop_los_margin_m`, `desktop_required_mast_height_m` and `desktop_mounting_type`; a denial reached at step 1 or step 2 records no geometry, and a denial for mast limit records the margin and the mast requirement while leaving `desktop_mounting_type` absent."
        PRD §3.7: "It **never** mutates the enquiry: the `desktop_los_margin_m`, `desktop_required_mast_height_m` and `desktop_mounting_type` recorded at intake are preserved as the historical estimate, and the field variant cannot deny an enquiry or change its `status`."

        Design: Difficulty/dual_variant_calc/los_desktop_lidar_vs_field_survey_variant_divergence
        """
        scenario = setup_scheduled_work_order()
        before = get_serviceability_request(scenario["request"]["id"])

        work_order = survey_work_order(
            scenario["work_order"]["id"], **SURVEY_PRESETS["ROOF_MAST_GUYED"]
        )
        after = get_serviceability_request(scenario["request"]["id"])

        assert work_order["recommended_mast_height_m"] == pytest.approx(5.0, abs=0.01)
        assert after["desktop_los_margin_m"] == pytest.approx(
            before["desktop_los_margin_m"], abs=0.01
        ), "desktop_los_margin_m is preserved as the historical estimate"
        assert after["desktop_required_mast_height_m"] == pytest.approx(
            before["desktop_required_mast_height_m"], abs=0.01
        ), "desktop_required_mast_height_m is preserved as the historical estimate"
        assert after["desktop_mounting_type"] == before["desktop_mounting_type"], (
            "desktop_mounting_type is preserved as the historical estimate"
        )
        assert after["status"] == before["status"], (
            f"the field variant cannot change the enquiry's status: "
            f"{before['status']!r} -> {after['status']!r}"
        )
        assert_no_mutation(before, after, "qualification")

    @pytest.mark.parametrize(
        "measured_tree_line_height_m, expected_margin_m, expected_mast_m, expected_band, expected_status",
        [
            # mast = measured tree line + 3.0 clearance + 0.5 safety - 4.0 roof,
            # then raised to the next multiple of 0.5 metres.
            (1.4, 30.1, 1.0, "WALL_BRACKET", "MOUNT_APPROVED"),
            (1.5, 30.0, 1.0, "WALL_BRACKET", "MOUNT_APPROVED"),
            (3.5, 28.0, 3.0, "NON_PEN_ROOF_TRIPOD", "MOUNT_APPROVED"),
            (3.6, 27.9, 3.5, "ROOF_MAST_GUYED", "EXCEPTION_PENDING"),
            (6.5, 25.0, 6.0, "ROOF_MAST_GUYED", "EXCEPTION_PENDING"),
            (6.6, 24.9, 6.5, "GROUND_POLE_MAST", "EXCEPTION_PENDING"),
            (12.5, 19.0, 12.0, "GROUND_POLE_MAST", "EXCEPTION_PENDING"),
        ],
    )
    def test_field_variant_mounting_band_boundaries(
        self,
        measured_tree_line_height_m,
        expected_margin_m,
        expected_mast_m,
        expected_band,
        expected_status,
    ):
        """PRD §3.5: "That raw figure is then rounded **upward** to the next whole multiple of 0.5 metres, because masts are only sold in half-metre sections: a raw requirement of 2.6 metres becomes 3.0, and a raw requirement of exactly 3.0 stays 3.0."
        PRD §3.5: "The rounded mast requirement selects a mounting band, with every upper bound inclusive: at or below 1.0 metre a `WALL_BRACKET`; above that and at or below 3.0 metres a `NON_PEN_ROOF_TRIPOD`; above that and at or below 6.0 metres a `ROOF_MAST_GUYED`; above that and at or below 12.0 metres a `GROUND_POLE_MAST`."
        PRD §3.7: "The field variant writes its findings onto the work order as `field_los_margin_m`, `recommended_mast_height_m` and `recommended_mounting_type`, and stamps `surveyed_by_user_id` with the surveying technician's identifier."

        Design: Difficulty/dual_variant_calc/los_desktop_lidar_vs_field_survey_variant_divergence
        """
        scenario = setup_scheduled_work_order()
        work_order = survey_work_order(
            scenario["work_order"]["id"],
            measured_tree_line_height_m=measured_tree_line_height_m,
            measured_roof_height_m=4.0,
            structure_penetration_allowed=True,
        )

        assert work_order["field_los_margin_m"] == pytest.approx(expected_margin_m, abs=0.01), (
            f"a measured tree line of {measured_tree_line_height_m} m gives a field margin of "
            f"{expected_margin_m}, got {work_order['field_los_margin_m']}"
        )
        assert work_order["recommended_mast_height_m"] == pytest.approx(expected_mast_m, abs=0.01), (
            f"a measured tree line of {measured_tree_line_height_m} m needs a "
            f"{expected_mast_m} m mast, got {work_order['recommended_mast_height_m']}"
        )
        assert work_order["recommended_mounting_type"] == expected_band, (
            f"a {expected_mast_m} m mast selects {expected_band}, got "
            f"{work_order['recommended_mounting_type']!r}"
        )
        assert work_order["status"] == expected_status, (
            f"expected {expected_status} for a {expected_band} recommendation, got "
            f"{work_order['status']!r}"
        )

    def test_field_variant_above_the_mast_limit_fails_the_survey(self):
        """PRD §3.5: "A requirement above 12.0 metres selects no band at all and leaves the mounting recommendation absent, because 12.0 metres is the structural limit of anything the field crews will erect at a residential premise."
        PRD §3.7: "When `field_los_margin_m` is strictly below zero, or `recommended_mast_height_m` is strictly above 12.0, the work order moves `SCHEDULED → SURVEY_FAILED`, which is terminal."
        PRD §3.7: "When the failure is the mast limit, `recommended_mounting_type` is left absent because no band accommodates the requirement."

        Design: Difficulty/dual_variant_calc/los_desktop_lidar_vs_field_survey_variant_divergence
        """
        scenario = setup_scheduled_work_order()
        work_order = survey_work_order(
            scenario["work_order"]["id"],
            measured_tree_line_height_m=13.0,
            measured_roof_height_m=4.0,
            structure_penetration_allowed=True,
        )

        assert work_order["recommended_mast_height_m"] == pytest.approx(12.5, abs=0.01), (
            f"a 13.0 m tree line needs a 12.5 m mast, got {work_order['recommended_mast_height_m']}"
        )
        assert work_order["status"] == "SURVEY_FAILED", (
            f"a mast above 12.0 m fails the survey, got {work_order['status']!r}"
        )
        assert work_order.get("recommended_mounting_type") is None, (
            "no band accommodates a mast above 12.0 m, got "
            f"{work_order.get('recommended_mounting_type')!r}"
        )
        assert work_order["field_los_margin_m"] == pytest.approx(18.5, abs=0.01)

    def test_partial_obstruction_metre_is_carried_into_both_variants(self):
        """PRD §3.5: "A partially obstructed path buys an extra allowance: when the enquiry's `obstruction_class` is `PARTIAL`, a further 1.0 metre is added."
        PRD §3.5: "Both variants read `obstruction_class` from the enquiry — the field survey does not re-classify obstruction, so a premise recorded as `PARTIAL` at intake still carries the extra metre when the technician's measurements are used."
        PRD §3.7: "The `obstruction_class` is still read from the enquiry, so the extra 1.0 metre for a `PARTIAL` path applies to the field variant exactly as it does to the desktop variant."

        Design: Difficulty/dual_variant_calc/los_desktop_lidar_vs_field_survey_variant_divergence
        """
        scenario = setup_scheduled_work_order(
            request_overrides={"obstruction_class": "PARTIAL"}
        )
        request = get_serviceability_request(scenario["request"]["id"])

        assert request["desktop_los_margin_m"] == pytest.approx(27.5, abs=0.01), (
            "the PARTIAL metre lowers the desktop margin from 28.5 to 27.5, got "
            f"{request['desktop_los_margin_m']}"
        )
        assert request["desktop_required_mast_height_m"] == pytest.approx(3.5, abs=0.01), (
            "the PARTIAL metre raises the desktop mast requirement from 2.5 to 3.5, got "
            f"{request['desktop_required_mast_height_m']}"
        )
        assert request["desktop_mounting_type"] == "ROOF_MAST_GUYED"

        work_order = survey_work_order(
            scenario["work_order"]["id"], **SURVEY_PRESETS["ROOF_MAST_GUYED"]
        )
        assert work_order["field_los_margin_m"] == pytest.approx(25.0, abs=0.01), (
            "the PARTIAL metre lowers the field margin from 26.0 to 25.0, got "
            f"{work_order['field_los_margin_m']}"
        )
        assert work_order["recommended_mast_height_m"] == pytest.approx(6.0, abs=0.01), (
            "the PARTIAL metre raises the field mast requirement from 5.0 to 6.0, got "
            f"{work_order['recommended_mast_height_m']}"
        )
        assert work_order["recommended_mounting_type"] == "ROOF_MAST_GUYED", (
            "a 6.0 m mast is still at the inclusive ROOF_MAST_GUYED ceiling, got "
            f"{work_order['recommended_mounting_type']!r}"
        )
        assert work_order["status"] == "EXCEPTION_PENDING"


# --------------------------------------------------------------------------
# The equipment settlement: a rental liability against a purchase refund
# --------------------------------------------------------------------------


class TestEquipmentSettlementSignInversion:
    """The same tenure, the same radio, opposite signs on `settlement_cents`."""

    def test_rental_write_off_charges_while_purchase_return_refunds(self):
        """PRD §3.8: "First establish the tenure: `months_in_service` is the number of whole days from `deployed_at` to the settlement instant divided by a settlement month of 30 days, with any fractional part discarded downward."
        PRD §3.8: "When the record is being written off as unreturned, the rent already collected is credited against the loss: the rental credit is `monthly_rental_cents` multiplied by `months_in_service`, capped at 60 percent of `replacement_cost_cents` with the cap's fractional cents discarded downward — on the standard 34900-cent radio the cap is 20940 cents, which a 1000-cent monthly rental reaches after 21 months and never exceeds however long the customer keeps it."
        PRD §3.8: "`settlement_cents` is `replacement_cost_cents` less that credit, a positive amount owed by the customer, and `settlement_basis` is `RENTAL_CREDIT_OFFSET`."
        PRD §3.8: "For a `PURCHASE` record, the customer already owns the radio, which inverts every case."
        PRD §3.8: "When the record is returned, in **either** condition, the operator buys it back at a depreciated value: the residual is `purchase_price_cents` multiplied by the depreciation months remaining, being 36 less `months_in_service` and floored at zero, divided by 36, rounded half up to whole cents; a restocking fee of 15 percent of that residual is then computed and rounded half up to whole cents; and `settlement_cents` is the **negative** of the residual less the restocking fee, signalling a refund the operator owes rather than a charge the customer owes."
        PRD §3.8: "`settlement_basis` is `DEPRECIATED_REFUND`."

        Design: Difficulty/dual_variant_calc/equipment_settlement_rental_liability_vs_purchase_refund_sign_inversion
        """
        pair = _setup_rental_and_purchase_return_pending(months_in_service=5)

        # PURCHASE variant, returned in GOOD condition after five settlement months:
        # residual 29900 * 31 / 36 = 25747, restocking fee 3862, refund -21885.
        purchase = return_equipment(pair["purchase"]["assignment"]["id"], "GOOD")
        assert_equipment_assignment(purchase)
        assert purchase["status"] == "RETURNED", (
            f"a filed return lands in RETURNED, got {purchase['status']!r}"
        )
        assert purchase["settlement_cents"] == -21885, (
            "the purchase refund is the negative of the 25747-cent residual less the "
            f"3862-cent restocking fee, expected -21885, got {purchase['settlement_cents']}"
        )
        assert purchase["settlement_basis"] == "DEPRECIATED_REFUND", (
            f"expected DEPRECIATED_REFUND, got {purchase['settlement_basis']!r}"
        )

        # RENTAL variant, written off unreturned at the same tenure:
        # credit 1000 * 5 = 5000 against a 34900-cent replacement cost.
        set_clock(pair["return_due_at"])
        rental = settle_unreturned_equipment(
            pair["rental"]["assignment"]["id"], note="Radio never returned"
        )
        assert_equipment_assignment(rental)
        assert rental["status"] == "UNRETURNED_BILLED", (
            f"an unreturned write-off lands in UNRETURNED_BILLED, got {rental['status']!r}"
        )
        assert rental["settlement_cents"] == 29900, (
            "the rental liability is 34900 less the 5000-cent rental credit, expected "
            f"29900, got {rental['settlement_cents']}"
        )
        assert rental["settlement_basis"] == "RENTAL_CREDIT_OFFSET", (
            f"expected RENTAL_CREDIT_OFFSET, got {rental['settlement_basis']!r}"
        )

        # The two variants of the same calculation carry opposite signs.
        assert rental["settlement_cents"] > 0, "the rental write-off is a charge to the customer"
        assert purchase["settlement_cents"] < 0, "the purchase buy-back is a refund from the operator"

    def test_settlement_balance_follows_the_sign_of_each_variant(self):
        """PRD §3.8: "The account's `settlement_balance_cents` is the sum of `settlement_cents` over its equipment records whose `status` is `RETURNED`, `UNRETURNED_BILLED` or `VOIDED`."
        PRD §3.8: "Because a purchase refund is negative, the balance can legitimately be below zero."

        Design: Difficulty/dual_variant_calc/equipment_settlement_rental_liability_vs_purchase_refund_sign_inversion
        """
        pair = _setup_rental_and_purchase_return_pending(months_in_service=5)

        purchase_before = get_subscriber(pair["purchase"]["subscriber"]["id"])
        assert purchase_before["settlement_balance_cents"] == 0, (
            "a RETURN_PENDING record is not yet in the balance, got "
            f"{purchase_before['settlement_balance_cents']}"
        )

        return_equipment(pair["purchase"]["assignment"]["id"], "GOOD")
        set_clock(pair["return_due_at"])
        settle_unreturned_equipment(pair["rental"]["assignment"]["id"])

        purchase_after = get_subscriber(pair["purchase"]["subscriber"]["id"])
        rental_after = get_subscriber(pair["rental"]["subscriber"]["id"])

        assert purchase_after["settlement_balance_cents"] == -21885, (
            "the purchase account's balance is its single -21885-cent refund, got "
            f"{purchase_after['settlement_balance_cents']}"
        )
        assert rental_after["settlement_balance_cents"] == 29900, (
            "the rental account's balance is its single 29900-cent liability, got "
            f"{rental_after['settlement_balance_cents']}"
        )

    @pytest.mark.parametrize(
        "months_in_service, expected_settlement_cents",
        [
            (20, 14900),  # credit 20000, below the 20940-cent cap
            (21, 13960),  # credit 21000 clipped to the cap
            (30, 13960),  # the cap never moves again
        ],
    )
    def test_rental_credit_is_capped_at_sixty_percent_of_replacement_cost(
        self, months_in_service, expected_settlement_cents
    ):
        """PRD §3.8: "When the record is being written off as unreturned, the rent already collected is credited against the loss: the rental credit is `monthly_rental_cents` multiplied by `months_in_service`, capped at 60 percent of `replacement_cost_cents` with the cap's fractional cents discarded downward — on the standard 34900-cent radio the cap is 20940 cents, which a 1000-cent monthly rental reaches after 21 months and never exceeds however long the customer keeps it."
        PRD §3.8: "`settlement_cents` is `replacement_cost_cents` less that credit, a positive amount owed by the customer, and `settlement_basis` is `RENTAL_CREDIT_OFFSET`."

        Design: Difficulty/dual_variant_calc/equipment_settlement_rental_liability_vs_purchase_refund_sign_inversion
        """
        scenario = setup_write_off_ready_assignment(
            equipment_mode="RENTAL", months_in_service=months_in_service
        )
        assignment = settle_unreturned_equipment(scenario["assignment"]["id"])

        assert assignment["settlement_cents"] == expected_settlement_cents, (
            f"after {months_in_service} settlement months the write-off is "
            f"{expected_settlement_cents}, got {assignment['settlement_cents']}"
        )
        assert assignment["settlement_basis"] == "RENTAL_CREDIT_OFFSET"
        assert assignment["status"] == "UNRETURNED_BILLED"

    @pytest.mark.parametrize("return_condition", ["GOOD", "DAMAGED"])
    def test_purchase_refund_ignores_the_return_condition(self, return_condition):
        """PRD §3.8: "When the record is returned, in **either** condition, the operator buys it back at a depreciated value: the residual is `purchase_price_cents` multiplied by the depreciation months remaining, being 36 less `months_in_service` and floored at zero, divided by 36, rounded half up to whole cents; a restocking fee of 15 percent of that residual is then computed and rounded half up to whole cents; and `settlement_cents` is the **negative** of the residual less the restocking fee, signalling a refund the operator owes rather than a charge the customer owes."
        PRD §3.8: "Note the order: the residual is rounded to whole cents first and the restocking fee is computed from that rounded residual, not from a full-precision value."

        Design: Difficulty/dual_variant_calc/equipment_settlement_rental_liability_vs_purchase_refund_sign_inversion
        """
        scenario = setup_return_pending_assignment(
            equipment_mode="PURCHASE", months_in_service=5
        )
        assignment = return_equipment(scenario["assignment"]["id"], return_condition)

        assert assignment["settlement_cents"] == -21885, (
            f"a {return_condition} purchase return after five months refunds 21885 cents, got "
            f"{assignment['settlement_cents']}"
        )
        assert assignment["settlement_basis"] == "DEPRECIATED_REFUND", (
            f"expected DEPRECIATED_REFUND for a {return_condition} purchase return, got "
            f"{assignment['settlement_basis']!r}"
        )
        assert assignment["return_condition"] == return_condition
        assert assignment["status"] == "RETURNED"

    def test_purchase_write_off_charges_nothing(self):
        """PRD §3.8: "When the record is being written off as unreturned, `settlement_cents` is zero and `settlement_basis` is `NONE` — the operator cannot bill a customer for failing to return their own property."

        Design: Difficulty/dual_variant_calc/equipment_settlement_rental_liability_vs_purchase_refund_sign_inversion
        """
        scenario = setup_write_off_ready_assignment(
            equipment_mode="PURCHASE", months_in_service=5
        )
        assignment = settle_unreturned_equipment(scenario["assignment"]["id"])

        assert assignment["settlement_cents"] == 0, (
            "an unreturned purchase radio is the customer's own property, expected 0, got "
            f"{assignment['settlement_cents']}"
        )
        assert assignment["settlement_basis"] == "NONE", (
            f"expected NONE, got {assignment['settlement_basis']!r}"
        )
        assert assignment["status"] == "UNRETURNED_BILLED"
        assert get_subscriber(scenario["subscriber"]["id"])["settlement_balance_cents"] == 0

    @pytest.mark.parametrize(
        "return_condition, months_in_service, expected_settlement_cents, expected_basis",
        [
            ("GOOD", 0, 0, "NONE"),
            ("GOOD", 5, 0, "NONE"),
            ("DAMAGED", 0, 17450, "RENTAL_DAMAGE"),
            ("DAMAGED", 5, 17450, "RENTAL_DAMAGE"),
        ],
    )
    def test_rental_return_charges_damage_only_and_ignores_tenure(
        self, return_condition, months_in_service, expected_settlement_cents, expected_basis
    ):
        """PRD §3.8: "When the record is being returned with a `return_condition` of `GOOD`, `settlement_cents` is zero and `settlement_basis` is `NONE`."
        PRD §3.8: "When the record is being returned with a `return_condition` of `DAMAGED`, `settlement_cents` is 50 percent of `replacement_cost_cents` rounded half up to whole cents, and `settlement_basis` is `RENTAL_DAMAGE`; the tenure is irrelevant to a damage charge."

        Design: Difficulty/dual_variant_calc/equipment_settlement_rental_liability_vs_purchase_refund_sign_inversion
        """
        scenario = setup_return_pending_assignment(
            equipment_mode="RENTAL", months_in_service=months_in_service
        )
        assignment = return_equipment(scenario["assignment"]["id"], return_condition)

        assert assignment["settlement_cents"] == expected_settlement_cents, (
            f"a {return_condition} rental return after {months_in_service} months settles at "
            f"{expected_settlement_cents}, got {assignment['settlement_cents']}"
        )
        assert assignment["settlement_basis"] == expected_basis, (
            f"expected {expected_basis}, got {assignment['settlement_basis']!r}"
        )
        assert assignment["status"] == "RETURNED"
        assert (
            get_subscriber(scenario["subscriber"]["id"])["settlement_balance_cents"]
            == expected_settlement_cents
        )


# --------------------------------------------------------------------------
# The install invoice: tier from the subtotal, fee from the net
# --------------------------------------------------------------------------


class TestInstallInvoicePinnedOrder:
    """Trip plus labour plus mast kit, then the tier, then the regulatory fee."""

    def test_regulatory_fee_is_charged_on_the_discounted_net(self):
        """PRD §3.7: "Begin with a labour charge selected by `approved_mounting_type`: 4900 cents for a `WALL_BRACKET`, 9900 for a `NON_PEN_ROOF_TRIPOD`, 19900 for a `ROOF_MAST_GUYED`, and 34900 for a `GROUND_POLE_MAST`."
        PRD §3.7: "Add a mast kit charge of 1750 cents per half-metre section, where the number of sections is `installed_mast_height_m` divided by 0.5 and rounded **upward** to a whole number — a 2.6 metre mast bills six sections."
        PRD §3.7: "Add the fixed trip charge of 9900 cents. The sum of trip charge, labour and mast kit is the subtotal."
        PRD §3.7: "A volume discount is then read off the **subtotal only**, with inclusive lower bounds: a subtotal at or above 30000 cents earns 5000 cents off, at or above 20000 earns 3000, at or above 10000 earns 1000, and anything below 10000 earns nothing."
        PRD §3.7: "The net amount is the subtotal less that discount. A regulatory cost-recovery fee of 3.25 percent is then applied to the **net** amount and rounded half up to whole cents, and `install_invoice_total_cents` is the net amount plus that fee."
        PRD §3.7: "On success the work order moves `MOUNT_APPROVED → INSTALLED`, which is terminal, storing `installed_mast_height_m`, `radio_serial` and an `installed_at` stamp taken from the logical clock, and computing `install_invoice_total_cents`."

        Design: Difficulty/combinatorial_formula/install_invoice_promo_tier_pinned_before_regulatory_recovery_fee
        """
        scenario = _setup_mount_approved("ROOF_MAST_GUYED")
        work_order = complete_work_order(
            scenario["work_order"]["id"], installed_mast_height_m=5.0
        )

        assert_install_work_order(work_order)
        assert work_order["status"] == "INSTALLED", (
            f"a completed install is terminal in INSTALLED, got {work_order['status']!r}"
        )
        assert work_order["installed_mast_height_m"] == pytest.approx(5.0, abs=0.01)
        # trip 9900 + labour 19900 + ten mast sections 17500 = 47300 subtotal,
        # less the 5000-cent tier = 42300 net, plus a 1374.75 -> 1375-cent fee.
        assert work_order["install_invoice_total_cents"] == 43675, (
            "the 3.25 percent fee is charged on the 42300-cent net, expected 43675, got "
            f"{work_order['install_invoice_total_cents']}"
        )
        assert work_order["install_invoice_total_cents"] != 43837, (
            "43837 is the fee charged on the 47300-cent subtotal before the discount"
        )
        assert work_order["installed_at"].startswith("2026-08-01T00:00:00"), (
            f"installed_at is stamped from the logical clock, got {work_order['installed_at']!r}"
        )

    @pytest.mark.parametrize(
        "installed_mast_height_m, expected_total_cents",
        [
            (0.5, 19153),  # 1 section, subtotal 21550, net 18550, fee 603
            (2.0, 24574),  # 4 sections, subtotal 26800, net 23800, fee 773.5 -> 774
            (2.5, 26380),  # 5 sections, subtotal 28550, net 25550, fee 830
            (2.6, 26122),  # 6 sections, subtotal 30300, net 25300, fee 822
            (3.0, 26122),  # 6 sections again, identical invoice
        ],
    )
    def test_mast_kit_sections_round_upward_and_the_fee_rounds_half_up(
        self, installed_mast_height_m, expected_total_cents
    ):
        """PRD §3.7: "Add a mast kit charge of 1750 cents per half-metre section, where the number of sections is `installed_mast_height_m` divided by 0.5 and rounded **upward** to a whole number — a 2.6 metre mast bills six sections."
        PRD §3.7: "A regulatory cost-recovery fee of 3.25 percent is then applied to the **net** amount and rounded half up to whole cents, and `install_invoice_total_cents` is the net amount plus that fee."

        Design: Difficulty/combinatorial_formula/install_invoice_promo_tier_pinned_before_regulatory_recovery_fee
        """
        scenario = _setup_mount_approved("NON_PEN_ROOF_TRIPOD")
        work_order = complete_work_order(
            scenario["work_order"]["id"],
            installed_mast_height_m=installed_mast_height_m,
        )

        assert work_order["install_invoice_total_cents"] == expected_total_cents, (
            f"a {installed_mast_height_m} m mast on a NON_PEN_ROOF_TRIPOD invoices "
            f"{expected_total_cents}, got {work_order['install_invoice_total_cents']}"
        )

    def test_discount_tier_is_never_re_evaluated_after_the_discount(self):
        """PRD §3.7: "The discount tier is selected once, from the pre-discount subtotal, and is **never** re-evaluated after the discount or the regulatory fee has moved the running total — an invoice whose subtotal was 20100 keeps its 3000-cent discount even though the net of 17100 would have qualified only for 1000."
        PRD §3.7: "A volume discount is then read off the **subtotal only**, with inclusive lower bounds: a subtotal at or above 30000 cents earns 5000 cents off, at or above 20000 earns 3000, at or above 10000 earns 1000, and anything below 10000 earns nothing."

        Design: Difficulty/combinatorial_formula/install_invoice_promo_tier_pinned_before_regulatory_recovery_fee
        """
        # Subtotal 21550 keeps the 3000-cent tier even though its 18550-cent net
        # would only have earned 1000. Re-reading the tier would give 21218.
        small = _setup_mount_approved("NON_PEN_ROOF_TRIPOD")
        small_work_order = complete_work_order(
            small["work_order"]["id"], installed_mast_height_m=0.5
        )
        assert small_work_order["install_invoice_total_cents"] == 19153, (
            "the 3000-cent tier chosen from the 21550-cent subtotal stands, expected 19153, got "
            f"{small_work_order['install_invoice_total_cents']}"
        )
        assert small_work_order["install_invoice_total_cents"] != 21218, (
            "21218 is the tier re-read from the 18550-cent net"
        )

        # One extra 10-centimetre section pushes the subtotal from 28550 to 30300,
        # which buys a 5000-cent tier and a *smaller* invoice.
        cheaper = _setup_mount_approved("NON_PEN_ROOF_TRIPOD")
        cheaper_work_order = complete_work_order(
            cheaper["work_order"]["id"], installed_mast_height_m=2.6
        )
        dearer = _setup_mount_approved("NON_PEN_ROOF_TRIPOD")
        dearer_work_order = complete_work_order(
            dearer["work_order"]["id"], installed_mast_height_m=2.5
        )

        assert cheaper_work_order["install_invoice_total_cents"] == 26122
        assert dearer_work_order["install_invoice_total_cents"] == 26380
        assert (
            cheaper_work_order["install_invoice_total_cents"]
            < dearer_work_order["install_invoice_total_cents"]
        ), (
            "the larger 30300-cent subtotal crosses into the 5000-cent tier and invoices less "
            f"than the 28550-cent subtotal: {cheaper_work_order['install_invoice_total_cents']} "
            f"vs {dearer_work_order['install_invoice_total_cents']}"
        )

    @pytest.mark.parametrize(
        "band, installed_mast_height_m, expected_total_cents",
        [
            ("WALL_BRACKET", 1.0, 17862),  # subtotal 18300, tier 1000, net 17300
            ("NON_PEN_ROOF_TRIPOD", 2.5, 26380),  # subtotal 28550, tier 3000
            ("ROOF_MAST_GUYED", 5.0, 43675),  # subtotal 47300, tier 5000
            ("GROUND_POLE_MAST", 11.5, 82652),  # subtotal 85050, tier 5000
        ],
    )
    def test_labour_charge_is_selected_by_the_approved_mounting_type(
        self, band, installed_mast_height_m, expected_total_cents
    ):
        """PRD §3.7: "Begin with a labour charge selected by `approved_mounting_type`: 4900 cents for a `WALL_BRACKET`, 9900 for a `NON_PEN_ROOF_TRIPOD`, 19900 for a `ROOF_MAST_GUYED`, and 34900 for a `GROUND_POLE_MAST`."
        PRD §3.7: "A volume discount is then read off the **subtotal only**, with inclusive lower bounds: a subtotal at or above 30000 cents earns 5000 cents off, at or above 20000 earns 3000, at or above 10000 earns 1000, and anything below 10000 earns nothing."
        PRD §3.7: "The net amount is the subtotal less that discount. A regulatory cost-recovery fee of 3.25 percent is then applied to the **net** amount and rounded half up to whole cents, and `install_invoice_total_cents` is the net amount plus that fee."

        Design: Difficulty/combinatorial_formula/install_invoice_promo_tier_pinned_before_regulatory_recovery_fee
        """
        scenario = _setup_mount_approved(band)
        assert scenario["work_order"]["approved_mounting_type"] == band

        work_order = complete_work_order(
            scenario["work_order"]["id"],
            installed_mast_height_m=installed_mast_height_m,
        )
        assert work_order["install_invoice_total_cents"] == expected_total_cents, (
            f"a {installed_mast_height_m} m mast on a {band} invoices "
            f"{expected_total_cents}, got {work_order['install_invoice_total_cents']}"
        )


# --------------------------------------------------------------------------
# The ground lease: compounding on the already-rounded rent
# --------------------------------------------------------------------------


class TestGroundLeaseEscalationSchedule:
    """Each anniversary rounds, and the next year compounds on that rounded figure."""

    def test_each_anniversary_compounds_on_the_already_rounded_rent(
        self, api, network_engineer
    ):
        """PRD §3.1: "First count how many anniversaries of `lease_start_date` fall at or before the current logical clock; an anniversary landing exactly on the clock counts."
        PRD §3.1: "The rent for lease year zero is `lease_monthly_base_rent_cents` exactly. The rent for each subsequent lease year is the previous year's rent multiplied by one plus `lease_escalator_pct`, rounded half up to whole cents. Crucially, each year compounds on the **already-rounded** rent of the year before, not on a full-precision running value. `current_monthly_rent_cents` is the rent of the lease year the clock currently sits in. To make the difference concrete: a base rent of 45000 cents escalating at 0.0275 for three elapsed years yields 48817 cents under the pinned order, whereas compounding at full precision and rounding once at the end yields 48816 cents — the latter is wrong."
        PRD §3.1: "It reports the `tower_id` it describes, `years_elapsed` as the count of anniversaries at or before the clock, `current_monthly_rent_cents`, `next_anniversary_date` as `lease_start_date` advanced by one more year than have elapsed, and `total_committed_cents`."
        PRD §3.1: "The committed total sums, over every lease year from year zero through the final year of the term — that is, over `lease_term_months` divided by twelve years — that year's escalated monthly rent multiplied by twelve."

        Design: Difficulty/combinatorial_formula/tower_lease_rent_rounded_at_each_anniversary_not_at_the_end
        """
        tower = create_tower(
            lease_monthly_base_rent_cents=45000,
            lease_escalator_pct=0.0275,
            lease_start_date="2023-04-01",
            lease_term_months=60,
        )

        schedule = validate_success(api.get_lease_schedule(tower["id"], network_engineer))

        assert schedule["tower_id"] == tower["id"]
        assert schedule["years_elapsed"] == 3, (
            "the 2024, 2025 and 2026 anniversaries fall at or before the 2026-08-01 clock, "
            f"expected 3, got {schedule['years_elapsed']}"
        )
        assert schedule["current_monthly_rent_cents"] == 48817, (
            "45000 -> 46238 -> 47510 -> 48817 with every step rounded, expected 48817, got "
            f"{schedule['current_monthly_rent_cents']}"
        )
        assert schedule["current_monthly_rent_cents"] != 48816, (
            "48816 is the full-precision compounding rounded once at the end"
        )
        assert schedule["next_anniversary_date"] == "2027-04-01", (
            "the next anniversary is lease_start_date advanced by four years, got "
            f"{schedule['next_anniversary_date']!r}"
        )
        # (45000 + 46238 + 47510 + 48817 + 50159) * 12 over the five-year term.
        assert schedule["total_committed_cents"] == 2852688, (
            "the committed total sums twelve months of each of the five lease years, expected "
            f"2852688, got {schedule['total_committed_cents']}"
        )

    def test_tower_reports_the_escalated_rent_from_registration(self):
        """PRD §3.1: "Upon registration the site opens in `PLANNED` `status`, with `active_sector_count` at zero and `backhaul_accepted_mbps` at zero, and its `current_monthly_rent_cents` is derived immediately."
        PRD §3.1: "The rent for each subsequent lease year is the previous year's rent multiplied by one plus `lease_escalator_pct`, rounded half up to whole cents."
        PRD §3.1: "Crucially, each year compounds on the **already-rounded** rent of the year before, not on a full-precision running value."

        Design: Difficulty/combinatorial_formula/tower_lease_rent_rounded_at_each_anniversary_not_at_the_end
        """
        tower = create_tower(
            lease_monthly_base_rent_cents=45000,
            lease_escalator_pct=0.0275,
            lease_start_date="2023-04-01",
            lease_term_months=60,
        )
        assert_tower(tower)
        assert tower["status"] == "PLANNED"
        assert tower["active_sector_count"] == 0
        assert tower["backhaul_accepted_mbps"] == 0
        assert tower["current_monthly_rent_cents"] == 48817, (
            "three elapsed anniversaries put the site in lease year three at 48817 cents, got "
            f"{tower['current_monthly_rent_cents']}"
        )
        assert get_tower(tower["id"])["current_monthly_rent_cents"] == 48817

    @pytest.mark.parametrize(
        "clock, expected_years_elapsed, expected_rent_cents, expected_next_anniversary",
        [
            ("2026-03-31T23:59:00Z", 2, 47510, "2026-04-01"),
            ("2026-04-01T00:00:00Z", 3, 48817, "2027-04-01"),
            ("2026-04-01T00:01:00Z", 3, 48817, "2027-04-01"),
        ],
    )
    def test_anniversary_landing_on_the_clock_counts(
        self,
        api,
        network_engineer,
        clock,
        expected_years_elapsed,
        expected_rent_cents,
        expected_next_anniversary,
    ):
        """PRD §3.1: "First count how many anniversaries of `lease_start_date` fall at or before the current logical clock; an anniversary landing exactly on the clock counts."
        PRD §3.1: "`current_monthly_rent_cents` is the rent of the lease year the clock currently sits in."
        PRD §3.1: "It reports the `tower_id` it describes, `years_elapsed` as the count of anniversaries at or before the clock, `current_monthly_rent_cents`, `next_anniversary_date` as `lease_start_date` advanced by one more year than have elapsed, and `total_committed_cents`."

        Design: Difficulty/combinatorial_formula/tower_lease_rent_rounded_at_each_anniversary_not_at_the_end
        """
        set_clock(clock)
        tower = create_tower(
            lease_monthly_base_rent_cents=45000,
            lease_escalator_pct=0.0275,
            lease_start_date="2023-04-01",
            lease_term_months=60,
        )

        schedule = validate_success(api.get_lease_schedule(tower["id"], network_engineer))

        assert schedule["years_elapsed"] == expected_years_elapsed, (
            f"at {clock} the lease has {expected_years_elapsed} elapsed years, got "
            f"{schedule['years_elapsed']}"
        )
        assert schedule["current_monthly_rent_cents"] == expected_rent_cents, (
            f"at {clock} the rent is {expected_rent_cents}, got "
            f"{schedule['current_monthly_rent_cents']}"
        )
        assert schedule["next_anniversary_date"] == expected_next_anniversary, (
            f"at {clock} the next anniversary is {expected_next_anniversary}, got "
            f"{schedule['next_anniversary_date']!r}"
        )

    def test_committed_total_does_not_move_with_the_clock(self, api, network_engineer):
        """PRD §3.1: "The committed total sums, over every lease year from year zero through the final year of the term — that is, over `lease_term_months` divided by twelve years — that year's escalated monthly rent multiplied by twelve."
        PRD §3.1: "Note that the total is a whole-lease figure and does not depend on where the clock sits, whereas `current_monthly_rent_cents` and `next_anniversary_date` do."

        Design: Difficulty/combinatorial_formula/tower_lease_rent_rounded_at_each_anniversary_not_at_the_end
        """
        tower = create_tower(
            lease_monthly_base_rent_cents=45000,
            lease_escalator_pct=0.0275,
            lease_start_date="2023-04-01",
            lease_term_months=60,
        )

        set_clock("2023-04-01T00:00:00Z")
        at_commencement = validate_success(
            api.get_lease_schedule(tower["id"], network_engineer)
        )
        set_clock("2027-06-01T00:00:00Z")
        late = validate_success(api.get_lease_schedule(tower["id"], network_engineer))

        assert at_commencement["years_elapsed"] == 0, (
            "the commencement date is not itself an anniversary, got "
            f"{at_commencement['years_elapsed']}"
        )
        assert at_commencement["current_monthly_rent_cents"] == 45000, (
            "lease year zero is the base rent exactly, got "
            f"{at_commencement['current_monthly_rent_cents']}"
        )
        assert at_commencement["next_anniversary_date"] == "2024-04-01"

        assert late["years_elapsed"] == 4, (
            f"four anniversaries fall at or before 2027-06-01, got {late['years_elapsed']}"
        )
        assert late["current_monthly_rent_cents"] == 50159, (
            "lease year four compounds 48817 to 50159, got "
            f"{late['current_monthly_rent_cents']}"
        )
        assert late["next_anniversary_date"] == "2028-04-01"

        assert at_commencement["total_committed_cents"] == 2852688
        assert late["total_committed_cents"] == 2852688, (
            "the committed total is a whole-lease figure and does not move with the clock, got "
            f"{late['total_committed_cents']} against "
            f"{at_commencement['total_committed_cents']}"
        )

    def test_pinned_rounding_diverges_further_at_the_maximum_escalator(
        self, api, network_engineer
    ):
        """PRD §3.1: "The rent for each subsequent lease year is the previous year's rent multiplied by one plus `lease_escalator_pct`, rounded half up to whole cents. Crucially, each year compounds on the **already-rounded** rent of the year before, not on a full-precision running value."
        PRD §3.1: "`lease_escalator_pct` is the annual escalator expressed as a decimal fraction to four decimal places between 0.0 and 0.15 inclusive, so a two-and-three-quarter-percent annual step is recorded as 0.0275 rather than as 2.75."
        PRD §3.1: "The committed total sums, over every lease year from year zero through the final year of the term — that is, over `lease_term_months` divided by twelve years — that year's escalated monthly rent multiplied by twelve."

        Design: Difficulty/combinatorial_formula/tower_lease_rent_rounded_at_each_anniversary_not_at_the_end
        """
        tower = create_tower(
            lease_monthly_base_rent_cents=45000,
            lease_escalator_pct=0.15,
            lease_start_date="2023-04-01",
            lease_term_months=60,
        )

        schedule = validate_success(api.get_lease_schedule(tower["id"], network_engineer))

        assert schedule["years_elapsed"] == 3
        # 45000 -> 51750 -> 59513 (59512.5 rounded up) -> 68440 (68439.95 rounded up).
        assert schedule["current_monthly_rent_cents"] == 68440, (
            "the year-two rounding of 59512.5 up to 59513 carries into year three, expected "
            f"68440, got {schedule['current_monthly_rent_cents']}"
        )
        assert schedule["current_monthly_rent_cents"] != 68439, (
            "68439 is 45000 compounded at full precision and rounded once at the end"
        )
        # (45000 + 51750 + 59513 + 68440 + 78706) * 12 over the five-year term.
        assert schedule["total_committed_cents"] == 3640908, (
            f"expected 3640908, got {schedule['total_committed_cents']}"
        )
        assert tower["current_monthly_rent_cents"] == 68440

"""Quarter bucketing, fee rounding and the equipment valuation behind a recall.

Which quarters enter an assessment, which readings offset a quarter, where the half
cent lands, how whole months in service erode book value, and what happens when the
exposure lands exactly on the recall floor.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    activate_agreement,
    add_telemetry,
    assess_shortfall_payload,
    create_agreement,
    create_outlet,
    create_supply_item,
    create_unit,
    pin_clock,
    place_service_hold,
    read_agreement,
    read_unit,
    recall_decision_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
TECH = TEST_USERS["technician_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _active_agreement(equipment_value_cents=480000, installed_at="2025-11-01T00:00:00Z",
                      annual_commitment_gallons=8000):
    """One ACTIVE agreement at Riverside Diner carrying a single machine."""
    pin_clock(CLOCK)
    outlet = create_outlet(
        name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=annual_commitment_gallons,
        equipment_value_cents=equipment_value_cents,
    )
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at=installed_at,
    )
    activate_agreement(agreement["id"])
    return outlet, agreement, unit


def _bag_in_box_sku():
    return create_supply_item(
        sku_code="SKU-COLA",
        brand_name="Cola Classic",
        supply_form="BAG_IN_BOX",
        case_pack_units=4,
        ounces_per_unit=1000,
    )


class TestQuarterBucketing:
    def test_a_three_month_period_assesses_the_one_quarter_it_opens_on(self, api):
        """PRD §3.9: "The fee arithmetic works on calendar quarters, and a quarter
        enters the assessment when the quarter's own start instant falls inside the
        half-open request period. The quarterly commitment is the agreement's
        `annual_commitment_gallons` divided by four, held exactly and **never**
        rounded." The write-back is equally pinned: "A successful assessment writes
        `assessed_shortfall_gallons`, `assessed_fee_cents`, `recall_exposure_cents`, the
        `exposure_variant` actually used, `assessment_period_start` and
        `assessment_period_end` from the submitted period bounds, and
        `shortfall_assessed_by_user_id` from the acting `X-User-ID`, and advances the
        agreement's `version` by one."

        Design: Corner/calculations/shortfall_single_quarter_with_no_telemetry_correct_result
        """
        _outlet, agreement, _unit = _active_agreement()

        assessed = validate_success(
            api.assess_shortfall(
                agreement["id"],
                assess_shortfall_payload(
                    "2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z"
                ),
                ADMIN,
            )
        )
        assert assessed["status"] == "SHORTFALL_REVIEW"
        assert assessed["assessed_shortfall_gallons"] == pytest.approx(2000.00, abs=0.01)
        assert assessed["assessed_fee_cents"] == 100000
        assert assessed["assessment_period_start"] == "2026-07-01T00:00:00Z"
        assert assessed["assessment_period_end"] == "2026-10-01T00:00:00Z"
        assert assessed["shortfall_assessed_by_user_id"] == ADMIN["X-User-ID"]
        assert assessed["exposure_variant"] == "BOOK_VALUE"

    def test_a_six_month_period_charges_both_quarters_it_opens_on(self, api):
        """PRD §3.9: "The fee arithmetic works on calendar quarters, and a quarter
        enters the assessment when the quarter's own start instant falls inside the
        half-open request period." The two quarters are then added together:
        "The agreement's `assessed_shortfall_gallons` is then the sum of the per-quarter
        shortfall gallons, rounded half up to two decimal places, and its
        `assessed_fee_cents` is the sum of the **already-rounded** per-quarter cent
        amounts."

        Design: Corner/calculations/shortfall_two_quarters_aggregate_into_one_assessment
        """
        _outlet, agreement, _unit = _active_agreement()

        assessed = validate_success(
            api.assess_shortfall(
                agreement["id"],
                assess_shortfall_payload(
                    "2026-04-01T00:00:00Z", "2026-10-01T00:00:00Z"
                ),
                ADMIN,
            )
        )
        assert assessed["assessed_shortfall_gallons"] == pytest.approx(4000.00, abs=0.01)
        assert assessed["assessed_fee_cents"] == 200000
        assert assessed["status"] == "SHORTFALL_REVIEW"

    def test_volume_poured_in_an_unassessed_quarter_offsets_nothing(self, api):
        """PRD §3.9: "The quarter's dispensed volume is the sum of `dispensed_ounces`
        over every telemetry reading of every dispenser unit whose `agreement_id` is
        this agreement, whose `reading_at` is at or after the quarter's start and
        strictly before the quarter's end, divided by 128 to convert ounces to gallons."
        The machine's own odometer still counts everything, per §3.4: "Each ingestion
        refreshes the receiving machine's `lifetime_dispensed_gallons`, which is defined
        as the total ounces ever reported for that unit divided by 128 and then rounded
        half up to two decimal places."

        Design: Corner/calculations/shortfall_ignores_readings_outside_the_assessed_quarter
        """
        _outlet, agreement, unit = _active_agreement()
        item = _bag_in_box_sku()
        add_telemetry(
            unit["id"], item["id"], 128000, "2026-07-15T00:00:00Z", window_days=30
        )
        add_telemetry(
            unit["id"], item["id"], 128000, "2026-05-15T00:00:00Z", window_days=30
        )

        assessed = validate_success(
            api.assess_shortfall(
                agreement["id"],
                assess_shortfall_payload(
                    "2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z"
                ),
                ADMIN,
            )
        )
        assert assessed["assessed_shortfall_gallons"] == pytest.approx(1000.00, abs=0.01)
        assert assessed["assessed_fee_cents"] == 50000
        assert read_unit(unit["id"])["lifetime_dispensed_gallons"] == pytest.approx(
            2000.00, abs=0.01
        )

    def test_a_half_cent_residue_is_charged_upward(self, api):
        """PRD §3.9: "The quarter's shortfall in gallons is the quarterly commitment
        less that dispensed volume, clamped up to zero when the outlet over-poured."
        The money is then settled per quarter: "The quarter's fee is that shortfall
        multiplied by the agreement's `shortfall_fee_cents_per_gallon` and **rounded
        half up to whole cents at this point**."

        Design: Corner/calculations/shortfall_half_cent_residue_rounds_half_up_within_the_quarter
        """
        _outlet, agreement, unit = _active_agreement()
        item = _bag_in_box_sku()
        add_telemetry(
            unit["id"], item["id"], 127998.72, "2026-07-15T00:00:00Z", window_days=30
        )
        assert read_unit(unit["id"])["lifetime_dispensed_gallons"] == pytest.approx(
            999.99, abs=0.01
        )

        assessed = validate_success(
            api.assess_shortfall(
                agreement["id"],
                assess_shortfall_payload(
                    "2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z"
                ),
                ADMIN,
            )
        )
        assert assessed["assessed_shortfall_gallons"] == pytest.approx(1000.01, abs=0.01)
        assert assessed["assessed_fee_cents"] == 50001


class TestEquipmentExposure:
    def test_a_machine_not_yet_a_month_old_is_worth_its_placement_value(self, api):
        """PRD §3.9: "Each contributing unit's whole months in service are counted as
        the elapsed time from its `installed_at` to the logical clock divided by 30 days
        and truncated downward. Under the `BOOK_VALUE` variant the unit's exposure is
        the agreement's `equipment_value_cents` multiplied by one minus one percent per
        whole month in service, with that multiplier clamped up to zero so a very old
        machine is worth nothing rather than a negative amount."

        Design: Corner/calculations/recall_exposure_with_zero_whole_months_equals_placement_value
        """
        _outlet, agreement, _unit = _active_agreement(
            equipment_value_cents=450000, installed_at="2026-07-20T00:00:00Z"
        )

        assessed = validate_success(
            api.assess_shortfall(
                agreement["id"],
                assess_shortfall_payload(
                    "2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z",
                    exposure_variant="BOOK_VALUE",
                ),
                ADMIN,
            )
        )
        assert assessed["recall_exposure_cents"] == 450000
        assert assessed["exposure_variant"] == "BOOK_VALUE"
        assert assessed["status"] == "SHORTFALL_REVIEW"

    def test_a_machine_on_service_hold_is_still_equipment_at_risk(self, api):
        """PRD §3.9: "The exposure is summed over the agreement's dispenser units whose
        `status` is `IN_SERVICE`, `SERVICE_HOLD` or `RECALL_STAGED`; units already
        `RETURNED` contribute nothing." The summation order is pinned too: "Either way
        each unit's exposure is rounded half up to whole cents **before** the units are
        summed, and the total is stored as the agreement's `recall_exposure_cents`."

        Design: Corner/calculations/recall_exposure_sums_the_service_hold_unit_into_the_fleet_total
        """
        outlet, agreement, first = _active_agreement(
            equipment_value_cents=300000, installed_at="2026-07-20T00:00:00Z"
        )
        second = create_unit(
            outlet["id"], agreement["id"],
            serial_number="SN-9002", installed_at="2026-07-20T00:00:00Z",
        )
        place_service_hold(second["id"], TECH)
        assert read_unit(first["id"])["status"] == "IN_SERVICE"
        assert read_unit(second["id"])["status"] == "SERVICE_HOLD"

        assessed = validate_success(
            api.assess_shortfall(
                agreement["id"],
                assess_shortfall_payload(
                    "2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z",
                    exposure_variant="BOOK_VALUE",
                ),
                ADMIN,
            )
        )
        assert assessed["recall_exposure_cents"] == 600000
        assert assessed["assessed_fee_cents"] == 100000


class TestRecallFloor:
    def test_an_exposure_sitting_exactly_on_the_floor_clears_it(self, api):
        """PRD §3.9: "And the exposure must be worth the trouble:
        `recall_exposure_cents` must be at least 450000 — four thousand five hundred
        dollars in cents — with anything below that floor refused as
        `ERR_RECALL_EXPOSURE_BELOW_FLOOR`. Where both hold, the agreement moves
        `SHORTFALL_REVIEW → RECALL_PENDING` and every dispenser unit of that agreement
        whose `status` is `IN_SERVICE` or `SERVICE_HOLD` is driven to `RECALL_STAGED`,
        each advancing its own `version` by one."

        Design: Corner/calculations/recall_permitted_when_exposure_sits_exactly_on_the_floor
        """
        _outlet, agreement, unit = _active_agreement(
            equipment_value_cents=450000, installed_at="2026-07-20T00:00:00Z"
        )
        validate_success(
            api.assess_shortfall(
                agreement["id"],
                assess_shortfall_payload(
                    "2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z",
                    exposure_variant="BOOK_VALUE",
                ),
                ADMIN,
            )
        )

        decided = validate_success(
            api.recall_decision(
                agreement["id"], recall_decision_payload("RECALL"), OFFICER
            )
        )
        assert decided["recall_exposure_cents"] == 450000
        assert decided["status"] == "RECALL_PENDING"
        assert decided["recall_decided_by_user_id"] == OFFICER["X-User-ID"]
        assert read_unit(unit["id"])["status"] == "RECALL_STAGED"
        assert read_agreement(agreement["id"])["status"] == "RECALL_PENDING"

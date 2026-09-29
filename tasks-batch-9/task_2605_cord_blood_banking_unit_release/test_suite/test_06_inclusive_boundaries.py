"""Boundaries that are inclusive on one side only: the receipt window and the public floor."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    build_bank_scenario,
    build_public_scenario,
    commission_tank,
    cryopreserve,
    expected_potency_grade,
    expected_quality_acceptance_score,
    make_registry_operator_headers,
    make_technologist_headers,
    read_collection,
    read_tank,
    publish_listing,
    read_unit,
    receive_collection,
    set_clock,
    unit_version,
    validate_error,
    validate_success,
)


def _collected_but_unreceived(*, parent_name, kit_lot_code, courier_tracking_code, consent_hash):
    """A private collection sitting in `COLLECTED`, with no tank anywhere in the picture."""
    return build_bank_scenario(
        stage="collected",
        tank_code=None,
        program_type="PRIVATE_FAMILY",
        primary_parent_name=parent_name,
        collection_site_code="SITE-09",
        consent_document_hash=consent_hash,
        kit_lot_code=kit_lot_code,
        courier_tracking_code=courier_tracking_code,
    )


class TestReceiptWindowBoundary:
    def test_a_shipment_arriving_at_exactly_forty_eight_hours_is_accepted(self):
        """The transit ceiling is inclusive at exactly 48.0 hours.

        "the elapsed time from `collected_at` to the logical clock, expressed in hours as an
        exact value, must not exceed 48.0 hours, and a shipment arriving at exactly 48.0 hours
        is accepted while 48.01 hours is not."

        Design: Difficulty/boundary_precision_check/receipt_window_inclusive_at_exactly_48_hours
        """
        scenario = _collected_but_unreceived(
            parent_name="Edge Parent A",
            kit_lot_code="LOT-2026-B1",
            courier_tracking_code="TRK-0901",
            consent_hash="hash-b1-v1",
        )

        set_clock("2026-08-12T05:00:00Z")
        received = receive_collection(scenario["collection"]["id"], transport_temp_c=20.0)

        assert received["status"] == "RECEIVED"
        assert received["hours_to_receipt"] == pytest.approx(48.00, abs=0.01)
        assert received["received_at"].startswith("2026-08-12T05:00:00")

    def test_the_accepted_receipt_mints_exactly_one_unit(self):
        """Receipt is the one and only way a unit comes into existence.

        "A successful receipt advances the collection `COLLECTED → RECEIVED`, stamps
        `received_at` from the logical clock, and **mints the CordBloodUnit** — the one and
        only way a unit ever comes into existence, exactly one per collection."

        Design: Difficulty/boundary_precision_check/receipt_window_inclusive_at_exactly_48_hours
        """
        scenario = _collected_but_unreceived(
            parent_name="Edge Parent A",
            kit_lot_code="LOT-2026-B1",
            courier_tracking_code="TRK-0901",
            consent_hash="hash-b1-v1",
        )
        assert scenario["collection"]["net_volume_ml"] == pytest.approx(105.0, abs=0.01)

        set_clock("2026-08-12T05:00:00Z")
        receive_collection(scenario["collection"]["id"], transport_temp_c=20.0)

        units = validate_success(
            api_client.list_collection_units(
                scenario["collection"]["id"], make_technologist_headers()
            )
        )
        assert len(units) == 1
        assert units[0]["processing_status"] == "RECEIVED"

    def test_a_shipment_half_an_hour_late_is_refused_and_mints_nothing(self):
        """Thirty minutes past the ceiling refuses the receipt outright.

        "the elapsed time from `collected_at` to the logical clock, expressed in hours as an
        exact value, must not exceed 48.0 hours, and a shipment arriving at exactly 48.0 hours is
        accepted while 48.01 hours is not. Exceeding the window is
        `ERR_PROCESSING_WINDOW_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/receipt_window_inclusive_at_exactly_48_hours
        """
        scenario = _collected_but_unreceived(
            parent_name="Edge Parent B",
            kit_lot_code="LOT-2026-B2",
            courier_tracking_code="TRK-0902",
            consent_hash="hash-b2-v1",
        )

        set_clock("2026-08-12T05:30:00Z")
        response = api_client.receive_collection(
            scenario["collection"]["id"], {"transport_temp_c": 20.0}, make_technologist_headers()
        )

        validate_error(response, ApiErrorId.ERR_PROCESSING_WINDOW_EXCEEDED.value, 422)

        collection = read_collection(scenario["collection"]["id"])
        assert collection["status"] == "COLLECTED"
        assert collection["received_at"] is None
        assert collection["hours_to_receipt"] is None

        units = validate_success(
            api_client.list_collection_units(
                scenario["collection"]["id"], make_technologist_headers()
            )
        )
        assert units == []


def _public_unit_at_count(*, tank, count, parent_name, slot_code, kit_lot_code, consent_hash):
    """A determined public unit whose stored cell count is exactly ``count``."""
    return build_public_scenario(
        stage="determined",
        tank=tank,
        primary_parent_name=parent_name,
        collection_site_code="SITE-10",
        hla_typing_consent=True,
        consent_document_hash=consent_hash,
        kit_lot_code=kit_lot_code,
        run_method="AUTOMATED_SEPARATION",
        pre_tnc_millions=1000,
        post_tnc_millions=count,
        quality_tnc_millions=count,
        quality_cd34_thousands=3000,
        quality_viability_pct=99.0,
        quality_volume_ml=25.0,
        slot_code=slot_code,
    )


class TestPublicListingFloorBoundary:
    def test_a_unit_at_exactly_nine_hundred_millions_may_be_published(self):
        """The public listing floor is inclusive at 900 million cells.

        "`post_processing_tnc_millions` at least 900, `post_processing_cd34_thousands` at
        least 1500, `post_processing_viability_pct` at least 85.0, and
        `quality_acceptance_score` at least 70.00, each boundary inclusive"

        Design: Difficulty/boundary_precision_check/public_listing_tnc_floor_inclusive_at_900_millions
        """
        tank = commission_tank(tank_code="TANK-I", tank_class="STANDARD", capacity_slots=5)
        floor_unit = _public_unit_at_count(
            tank=tank,
            count=900,
            parent_name="Floor Parent A",
            slot_code="I-01",
            kit_lot_code="LOT-2026-I1",
            consent_hash="hash-i1-v1",
        )
        assert floor_unit["unit"]["quality_acceptance_score"] == pytest.approx(80.67, abs=0.01)
        assert floor_unit["unit"]["eligibility_status"] == "ELIGIBLE"
        cryopreserve(
            floor_unit["unit"]["id"], tank["id"], slot_code="I-01", freeze_at="2026-08-11T02:00:00Z"
        )
        listing = publish_listing(floor_unit["unit"]["id"])

        assert listing["listing_status"] == "ACTIVE"
        assert listing["potency_grade"] == "C"
        assert listing["potency_grade"] == expected_potency_grade(900, 3000)
        assert read_unit(floor_unit["unit"]["id"])["availability_status"] == "LISTED"

    def test_a_unit_one_million_short_is_refused_at_the_public_threshold(self):
        """899 million cells is below the floor even though the unit is eligible.

        "Note that this floor is the same triple the `PUBLIC_TIER` quality test uses, so a
        unit may be eligible on its own merits and still be too weak for the public registry."

        Design: Difficulty/boundary_precision_check/public_listing_tnc_floor_inclusive_at_900_millions
        """
        tank = commission_tank(tank_code="TANK-I", tank_class="STANDARD", capacity_slots=5)
        short_unit = _public_unit_at_count(
            tank=tank,
            count=899,
            parent_name="Floor Parent B",
            slot_code="I-02",
            kit_lot_code="LOT-2026-I2",
            consent_hash="hash-i2-v1",
        )
        assert short_unit["unit"]["quality_acceptance_score"] == pytest.approx(80.64, abs=0.01)
        assert short_unit["unit"]["quality_acceptance_score"] == pytest.approx(
            expected_quality_acceptance_score("PUBLIC_DONATION", 899, 3000, 99.0, 25.0), abs=0.01
        )
        assert short_unit["unit"]["eligibility_status"] == "ELIGIBLE"
        cryopreserve(
            short_unit["unit"]["id"], tank["id"], slot_code="I-02", freeze_at="2026-08-11T02:00:00Z"
        )
        headers = make_registry_operator_headers()
        version = unit_version(short_unit["unit"]["id"], headers)

        response = api_client.create_registry_listing(
            {
                "unit_id": short_unit["unit"]["id"],
                "registry_code": "NMDP",
                "hla_a": "A*02:01",
                "hla_b": "B*08:01",
                "hla_drb1": "DRB1*03:01",
                "expected_unit_version": version,
            },
            headers,
        )

        validate_error(response, ApiErrorId.ERR_QUALITY_BELOW_PUBLIC_THRESHOLD.value, 422)

    def test_the_refused_publication_leaves_the_unit_and_its_version_alone(self):
        """Nothing is written when publication is refused at the quality rung.

        "A successful publication stamps `listed_at` from the logical clock, sets
        `listing_status` to `ACTIVE`, moves the unit `UNAVAILABLE → LISTED`, increments the unit's
        `version` by one, and freezes a `potency_grade` on the listing row."

        Design: Difficulty/boundary_precision_check/public_listing_tnc_floor_inclusive_at_900_millions
        """
        tank = commission_tank(tank_code="TANK-I", tank_class="STANDARD", capacity_slots=5)
        short_unit = _public_unit_at_count(
            tank=tank,
            count=899,
            parent_name="Floor Parent B",
            slot_code="I-02",
            kit_lot_code="LOT-2026-I2",
            consent_hash="hash-i2-v1",
        )
        cryopreserve(
            short_unit["unit"]["id"], tank["id"], slot_code="I-02", freeze_at="2026-08-11T02:00:00Z"
        )
        headers = make_registry_operator_headers()
        version_before = unit_version(short_unit["unit"]["id"], headers)

        api_client.create_registry_listing(
            {
                "unit_id": short_unit["unit"]["id"],
                "registry_code": "NMDP",
                "hla_a": "A*02:01",
                "hla_b": "B*08:01",
                "hla_drb1": "DRB1*03:01",
                "expected_unit_version": version_before,
            },
            headers,
        )

        unit_after = read_unit(short_unit["unit"]["id"])
        assert unit_after["availability_status"] == "UNAVAILABLE"
        assert unit_after["version"] == version_before
        listings = validate_success(
            api_client.list_unit_registry_listings(short_unit["unit"]["id"], headers)
        )
        assert listings == []
        assert read_tank(tank["id"])["occupied_slots"] == 1

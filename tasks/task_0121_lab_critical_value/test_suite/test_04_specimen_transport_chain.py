"""Specimen collection, transport-leg chain monotonicity, time-order
invariants.

PRD §3.3 fixes collection and the transport-leg chain; PRD §2.8 fixes
the time-order and chain-of-custody invariants.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    LAB_LOCATION_CODE,
    anchor_clock,
    arrive_leg,
    arrive_transport_leg_payload,
    assert_specimen,
    assert_transport_leg,
    attempt_open_transport_leg,
    collect_specimen,
    create_catalog_bundle,
    create_specimen_payload,
    create_transport_leg_payload,
    iso_anchor_offset,
    make_lab_tech_headers,
    open_transport_leg,
    place_lab_order,
    reget_lab_order,
    reget_specimen,
    setup_specimen_with_arrived_first_leg,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 Collection
# ===========================================================================
class TestSpecimenCollection:

    def test_collection_creates_specimen_and_advances_order(self, api):
        """PRD §3.3: "A successful collection creates a `Specimen`
        whose `lab_order_id` references the order, whose
        `collected_by_id` and `collected_at` reflect the input, whose
        `received_at` is initially absent, whose `rejected_reason` is
        initially absent, and whose `status` begins at `COLLECTED`
        (the initial specimen state). The parent order transitions
        from `ORDERED` to `COLLECTED`."

        Claim: POST /lab-orders/{id}/specimens returns 201 with
        specimen status=COLLECTED and the order transitions to
        COLLECTED.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        spec = collect_specimen(bundle, order)
        assert_specimen(spec)
        assert spec["status"] == "COLLECTED"
        order_after = reget_lab_order(bundle, order["id"])
        assert order_after["status"] == "COLLECTED"

    def test_second_specimen_on_same_order_rejected(self, api):
        """PRD §2.12: "Two simultaneous specimen-creation attempts
        against the same `LabOrder` serialize on the uniqueness of
        `Specimen.lab_order_id`; the first writer wins and the second
        is rejected with `ERR_SPECIMEN_ALREADY_EXISTS`."

        Claim: a serial second POST to /lab-orders/{id}/specimens
        returns ERR_SPECIMEN_ALREADY_EXISTS.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        collect_specimen(bundle, order)
        tech = bundle["lab_tech"]
        res = api.create_specimen(
            order["id"],
            create_specimen_payload(
                collected_by_id=tech["id"],
                collected_at=iso_anchor_offset(minutes=-3),
            ),
            make_lab_tech_headers(tech["id"]),
        )
        validate_error(res, "ERR_SPECIMEN_ALREADY_EXISTS")

    def test_future_dated_collection_rejected(self, api):
        """PRD §2.8: "The collection timestamp `collected_at` on a
        specimen creation must be at or before the server's current
        clock."

        PRD §2.8: "Any violation of these orderings is rejected with
        `ERR_TIME_ORDER_INVALID`."

        Claim: collected_at strictly after now() ->
        ERR_TIME_ORDER_INVALID.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        tech = bundle["lab_tech"]
        future = iso_anchor_offset(hours=2)
        payload = create_specimen_payload(
            collected_by_id=tech["id"], collected_at=future,
        )
        res = api.create_specimen(
            order["id"], payload, make_lab_tech_headers(tech["id"]),
        )
        validate_error(res, "ERR_TIME_ORDER_INVALID")


# ===========================================================================
# §3.3 First leg opens
# ===========================================================================
class TestFirstLegOpens:

    def test_first_leg_flips_specimen_and_order_to_in_transit(self, api):
        """PRD §3.3: "The leg is persisted with `specimen_id` set to
        the parent, `leg_index` set to 1 (the first leg of the chain),
        `arrived_at` initially absent, and `status` set to `DEPARTED`
        (the initial leg state). Opening the first leg transitions the
        specimen from `COLLECTED` to `IN_TRANSIT` and the parent order
        from `COLLECTED` to `IN_TRANSIT`."

        Claim: POST /specimens/{id}/transport-legs creates a leg with
        leg_index=1 and DEPARTED status, and both specimen and order
        transition to IN_TRANSIT.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        spec = collect_specimen(bundle, order)
        leg = open_transport_leg(
            bundle, spec,
            from_location="CLINIC_A", to_location=LAB_LOCATION_CODE,
        )
        assert_transport_leg(leg)
        assert leg["status"] == "DEPARTED"
        assert leg["leg_index"] == 1
        spec_after = reget_specimen(bundle, spec["id"])
        assert spec_after["status"] == "IN_TRANSIT"
        order_after = reget_lab_order(bundle, order["id"])
        assert order_after["status"] == "IN_TRANSIT"

    def test_first_leg_departed_before_collected_rejected(self, api):
        """PRD §2.8: "the first leg's `departed_at` must be at or
        later than the specimen's `collected_at`."

        PRD §2.8: "Any violation of these orderings is rejected with
        `ERR_TIME_ORDER_INVALID`."

        Claim: departed_at strictly before collected_at ->
        ERR_TIME_ORDER_INVALID.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        tech = bundle["lab_tech"]
        spec_payload = create_specimen_payload(
            collected_by_id=tech["id"],
            collected_at=iso_anchor_offset(minutes=0),
        )
        spec = validate_success(
            api.create_specimen(
                order["id"], spec_payload,
                make_lab_tech_headers(tech["id"]),
            ),
            201,
        )
        bad_payload = create_transport_leg_payload(
            from_location="CLINIC_A", to_location=LAB_LOCATION_CODE,
            departed_at=iso_anchor_offset(minutes=-10),
        )
        res = api.create_transport_leg(
            spec["id"], bad_payload, make_lab_tech_headers(tech["id"]),
        )
        validate_error(res, "ERR_TIME_ORDER_INVALID")


# ===========================================================================
# §2.8 Transport-leg chain monotonicity
# difficulty: resource_temporal_overlap /
#             transport_leg_chain_contiguity_no_gap
# ===========================================================================
class TestTransportChainMonotonicity:

    def test_new_leg_from_location_mismatch_rejected(self, api):
        """PRD §2.8: "When a new leg is opened on a specimen via the
        leg-creation endpoint, its `leg_index` must be exactly one
        greater than the maximum existing `leg_index` on that
        specimen, and its `from_location` must equal the previous
        leg's `to_location`. A break in this chain is rejected with
        `ERR_TRANSPORT_CHAIN_BROKEN`."

        Claim: a second leg whose from_location differs from the prior
        leg's to_location returns ERR_TRANSPORT_CHAIN_BROKEN.

        # difficulty: resource_temporal_overlap/transport_leg_chain_contiguity_no_gap
        """
        ctx = setup_specimen_with_arrived_first_leg()
        bundle, spec = ctx["bundle"], ctx["specimen"]
        res = attempt_open_transport_leg(
            bundle, spec,
            from_location="CLINIC_X", to_location=LAB_LOCATION_CODE,
            departed_at=iso_anchor_offset(minutes=8),
        )
        validate_error(res, "ERR_TRANSPORT_CHAIN_BROKEN")

    def test_new_leg_from_location_matches_chain_accepted(self, api):
        """PRD §2.8: "When a new leg is opened on a specimen via the
        leg-creation endpoint, its `leg_index` must be exactly one
        greater than the maximum existing `leg_index` on that
        specimen, and its `from_location` must equal the previous
        leg's `to_location`."

        Claim: a second leg whose from_location equals the previous
        leg's to_location is accepted with leg_index=2.

        # difficulty: resource_temporal_overlap/transport_leg_chain_contiguity_no_gap
        """
        ctx = setup_specimen_with_arrived_first_leg()
        bundle, spec = ctx["bundle"], ctx["specimen"]
        good = attempt_open_transport_leg(
            bundle, spec,
            from_location="HUB_B", to_location=LAB_LOCATION_CODE,
            departed_at=iso_anchor_offset(minutes=8),
        )
        leg2 = validate_success(good, 201)
        assert leg2["from_location"] == "HUB_B"
        assert leg2["to_location"] == LAB_LOCATION_CODE
        assert leg2["leg_index"] == 2

    def test_open_new_leg_while_previous_departed_rejected(self, api):
        """PRD §2.8: "The previous leg must also itself be in the
        `ARRIVED` state before a new leg may be opened; an attempt to
        open a new leg while a prior leg is still `DEPARTED` is the
        same chain-monotonicity violation and is reported with the
        same `ERR_TRANSPORT_CHAIN_BROKEN`."

        Claim: opening a second leg while leg1 is still DEPARTED ->
        ERR_TRANSPORT_CHAIN_BROKEN.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        spec = collect_specimen(bundle, order)
        leg1 = open_transport_leg(
            bundle, spec,
            from_location="CLINIC_A", to_location="HUB_B",
        )
        assert leg1["status"] == "DEPARTED"
        res = attempt_open_transport_leg(
            bundle, spec,
            from_location="HUB_B", to_location=LAB_LOCATION_CODE,
            departed_at=iso_anchor_offset(minutes=8),
        )
        validate_error(res, "ERR_TRANSPORT_CHAIN_BROKEN")


# ===========================================================================
# §2.8 Leg arrival time order
# ===========================================================================
class TestLegArrivalTimeOrder:

    def test_arrived_at_before_departed_at_rejected(self, api):
        """PRD §2.8: "Within a transport leg, the leg's `arrived_at`
        must be at or later than its `departed_at`; and across the leg
        sequence, the first leg's `departed_at` must be at or later
        than the specimen's `collected_at`."

        PRD §2.8: "Any violation of these orderings is rejected with
        `ERR_TIME_ORDER_INVALID`."

        Claim: arrived_at strictly earlier than departed_at ->
        ERR_TIME_ORDER_INVALID.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        spec = collect_specimen(bundle, order)
        leg = open_transport_leg(
            bundle, spec,
            from_location="CLINIC_A", to_location=LAB_LOCATION_CODE,
            departed_at=iso_anchor_offset(minutes=10),
        )
        tech = bundle["lab_tech"]
        res = api.arrive_transport_leg(
            leg["id"],
            arrive_transport_leg_payload(
                arrived_at=iso_anchor_offset(minutes=5),
            ),
            make_lab_tech_headers(tech["id"]),
        )
        validate_error(res, "ERR_TIME_ORDER_INVALID")


# ===========================================================================
# §2.12 Concurrency — double arrival
# ===========================================================================
class TestDoubleArrivalSerial:

    def test_serial_second_arrive_returns_leg_already_arrived(self, api):
        """PRD §2.12: "Two simultaneous arrival reports on the same
        transport leg serialize on the leg's `status` flip from
        `DEPARTED` to `ARRIVED`; the first writer wins and the second
        is rejected with `ERR_LEG_ALREADY_ARRIVED`."

        Claim: a serial second POST /transport-legs/{id}/arrive after
        the first arrival succeeded returns ERR_LEG_ALREADY_ARRIVED.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        spec = collect_specimen(bundle, order)
        leg = open_transport_leg(
            bundle, spec,
            from_location="CLINIC_A", to_location="HUB_B",
        )
        arrive_leg(
            bundle, leg, arrived_at=iso_anchor_offset(minutes=10),
        )
        tech = bundle["lab_tech"]
        res = api.arrive_transport_leg(
            leg["id"],
            arrive_transport_leg_payload(
                arrived_at=iso_anchor_offset(minutes=11),
            ),
            make_lab_tech_headers(tech["id"]),
        )
        validate_error(res, "ERR_LEG_ALREADY_ARRIVED")

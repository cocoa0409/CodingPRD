"""Two calendars with opposite interval conventions: half-open inspection
windows where touching endpoints are legal, and closed-closed lot windows where
the very same touch is a collision.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import REVIEWER_HEADERS
from test_helpers import api_errors as E
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X


def _establishment_with_two_booked_windows(api):
    """A routine engagement over 2026-09-01..05 and an adjacent for-cause one."""
    facility = X.create_registered_facility(
        api, facility_name="Bramble Compounding", owner_operator_name="Bramble Co",
        state_or_province="IN",
    )
    routine = X.schedule_inspection(
        api, facility["id"], "2026-09-01", "2026-09-05", K.INSPECTION_TYPE_GMP_ROUTINE
    )
    adjacent = X.schedule_inspection(
        api, facility["id"], "2026-09-05", "2026-09-08", K.INSPECTION_TYPE_FOR_CAUSE
    )
    return facility, routine, adjacent


class TestInspectionCalendarAdjacencyAndBuffer:
    """Adjacency is legal, real overlap is not, and the same-type buffer bites wider."""

    def test_a_different_type_window_may_start_the_day_the_previous_one_ends(self, api):
        """The for-cause window starts on the routine window's exclusive end date, so the
        two engagements share no on-site day and the booking is accepted.

        PRD: "The **overlap** rule applies to every existing non-terminal engagement of the establishment regardless of type: the requested half-open window must not overlap theirs, though adjacency is explicitly legal — an existing window whose `window_end` equals the requested `window_start` is fine, because the half-open convention means those two engagements share no on-site day."

        Design: Difficulty/resource_temporal_overlap/inspection_half_open_windows_allow_adjacency_but_enforce_same_type_buffer
        """
        _facility, routine, adjacent = _establishment_with_two_booked_windows(api)

        assert routine["status"] == K.INSPECTION_STATUS_SCHEDULED
        assert routine["window_start"] == "2026-09-01"
        assert routine["window_end"] == "2026-09-05"
        assert routine["observation_count"] == 0
        assert routine["readiness_score"] is None

        assert adjacent["status"] == K.INSPECTION_STATUS_SCHEDULED
        assert adjacent["window_start"] == routine["window_end"]
        assert adjacent["inspection_type"] == K.INSPECTION_TYPE_FOR_CAUSE

    def test_a_window_that_truly_overlaps_two_others_is_refused_on_the_overlap_rule(self, api):
        """The requested window shares on-site days with both existing engagements and
        matches the type of neither, so the buffer cannot be the cause and the overlap rule
        is what refuses it.

        PRD: "A violation is refused with `ERR_INSPECTION_WINDOW_OVERLAP` (HTTP 409). The buffer rule outranks the overlap rule, so two overlapping `GMP_ROUTINE` windows report the buffer error while a `GMP_ROUTINE` window overlapping a `FOR_CAUSE` window reports the overlap error."

        Design: Difficulty/resource_temporal_overlap/inspection_half_open_windows_allow_adjacency_but_enforce_same_type_buffer
        """
        facility, _routine, _adjacent = _establishment_with_two_booked_windows(api)

        validate_error(
            api.schedule_inspection(
                facility["id"],
                F.inspection_payload(
                    "2026-09-04", "2026-09-06", K.INSPECTION_TYPE_PREANNOUNCED_FOLLOWUP
                ),
                REVIEWER_HEADERS,
            ),
            E.ERR_INSPECTION_WINDOW_OVERLAP,
        )

        rows, _meta = validate_paginated(api.list_inspections(facility["id"], REVIEWER_HEADERS))
        assert len(rows) == 2

    def test_five_clear_days_is_not_enough_for_a_second_window_of_the_same_type(self, api):
        """The requested routine window overlaps nothing at all, yet only five clear days
        separate it from the existing routine window, short of the seven the same-type buffer
        demands on both sides.

        PRD: "The **same-type buffer** applies to every existing non-terminal engagement of the same establishment carrying the **same** `inspection_type`: the requested window must be separated from each of those windows by at least seven clear days on **both** sides."

        Design: Difficulty/resource_temporal_overlap/inspection_half_open_windows_allow_adjacency_but_enforce_same_type_buffer
        """
        facility, _routine, _adjacent = _establishment_with_two_booked_windows(api)

        validate_error(
            api.schedule_inspection(
                facility["id"],
                F.inspection_payload("2026-09-10", "2026-09-14", K.INSPECTION_TYPE_GMP_ROUTINE),
                REVIEWER_HEADERS,
            ),
            E.ERR_INSPECTION_TYPE_BUFFER_VIOLATION,
        )

    def test_ten_clear_days_is_enough_and_scheduling_alone_scores_nothing(self, api):
        """Pushed out to ten clear days the same-type booking is accepted, the calendar then
        holds three engagements of which two are routine, and the establishment is still
        unscored because scheduling decides nothing.

        PRD: "The engagement is created `SCHEDULED` with `observation_count` 0 and `readiness_score`, `outcome_class`, `category_subscores`, `response_due_at`, `response_submitted_at` and `response_summary` all null."

        Design: Difficulty/resource_temporal_overlap/inspection_half_open_windows_allow_adjacency_but_enforce_same_type_buffer
        """
        facility, _routine, _adjacent = _establishment_with_two_booked_windows(api)

        third = X.schedule_inspection(
            api, facility["id"], "2026-09-15", "2026-09-18", K.INSPECTION_TYPE_GMP_ROUTINE
        )
        assert third["status"] == K.INSPECTION_STATUS_SCHEDULED
        assert third["outcome_class"] is None
        assert third["category_subscores"] is None

        rows, _meta = validate_paginated(
            api.list_inspections(facility["id"], REVIEWER_HEADERS, {"limit": K.MAX_LIMIT})
        )
        assert len(rows) == 3
        routine_rows, _routine_meta = validate_paginated(
            api.list_inspections(
                facility["id"], REVIEWER_HEADERS,
                {"limit": K.MAX_LIMIT, "inspection_type": K.INSPECTION_TYPE_GMP_ROUTINE},
            )
        )
        assert len(routine_rows) == 2

        assert X.read_facility(api, facility["id"])["gmp_readiness_score"] is None


LOT_CEILING = 1000
FIRST_SHIPMENT_UNITS = 600
SECOND_LOT_UNITS = 300
CEILING_FILLING_UNITS = 400


def _listing_with_one_booked_lot_window(api):
    """A listing capped at 1000 units per lot, with 600 of LOT-A already shipped
    over the closed-closed window 2026-08-10..2026-08-15."""
    bundle = X.registered_facility_with_listing(
        api,
        facility_overrides={
            "facility_name": "Selkirk Packaging",
            "owner_operator_name": "Selkirk LLC",
            "facility_type": "PROCESSOR",
            "state_or_province": "WA",
        },
        listing_overrides={
            "product_name": "Selkirk Bath Salt Duo",
            "category_code": "02C",
            "product_form": K.PRODUCT_FORM_RINSE_OFF,
            "lot_authorized_units": LOT_CEILING,
        },
    )
    records = X.create_distribution_records(
        api, bundle["listing_id"], bundle["agent"],
        [{"lot_code": "LOT-A", "ship_date": "2026-08-10", "delivery_date": "2026-08-15",
          "units_shipped": FIRST_SHIPMENT_UNITS, "consignee_name": "Sound Wholesale",
          "consignee_class": "WHOLESALE"}],
    )
    bundle["first_record"] = records[0]
    return bundle


class TestLotWindowsTouchAndAggregateAgainstTheCeiling:
    """Closed-closed windows collide on a touch, and the ceiling is a per-lot sum."""

    def test_the_first_shipment_opens_the_lot_and_counts_against_the_product(self, api):
        """A new record starts with everything outstanding and nothing recovered, and the
        product's distributed total rises by the units shipped.

        PRD: "A new record is created with `withdrawal_id` null, all five recovery buckets at 0 and `units_outstanding` equal to `units_shipped`, and the listing's `distributed_units_total` rises by the units shipped."

        Design: Difficulty/resource_temporal_overlap/distribution_lot_windows_touch_and_aggregate_against_lot_ceiling
        """
        bundle = _listing_with_one_booked_lot_window(api)

        record = bundle["first_record"]
        assert record["units_shipped"] == FIRST_SHIPMENT_UNITS
        assert record["units_outstanding"] == FIRST_SHIPMENT_UNITS
        assert record["withdrawal_id"] is None
        assert record["ship_date"] == "2026-08-10"
        assert record["delivery_date"] == "2026-08-15"

        assert X.read_listing(api, bundle["listing_id"])["distributed_units_total"] == (
            FIRST_SHIPMENT_UNITS
        )

    def test_a_same_lot_window_that_merely_touches_the_existing_one_collides(self, api):
        """Shipping the same lot again from the exact day the first consignment was
        delivered is a collision, because distribution windows are inclusive at both ends.

        PRD: "Two window rules apply, in order after the ordinary bounds check that `ship_date` be no later than `delivery_date`: the requested window must not overlap **or even touch** any existing window of the same listing bearing the same `lot_code` — an existing record whose `delivery_date` equals the requested `ship_date` is a collision, refused with `ERR_LOT_WINDOW_CONFLICT` (HTTP 409) — and then the lot's aggregate capacity must hold: the sum of `units_shipped` over the listing's existing records with that same `lot_code`, plus the units now requested, must not exceed the listing's `lot_authorized_units`, or the shipment is refused with `ERR_LOT_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/distribution_lot_windows_touch_and_aggregate_against_lot_ceiling
        """
        bundle = _listing_with_one_booked_lot_window(api)

        validate_error(
            api.create_distribution_record(
                bundle["listing_id"],
                F.distribution_record_payload(
                    lot_code="LOT-A", ship_date="2026-08-15", delivery_date="2026-08-20",
                    units_shipped=100,
                ),
                bundle["agent"],
            ),
            E.ERR_LOT_WINDOW_CONFLICT,
        )

        assert X.read_listing(api, bundle["listing_id"])["distributed_units_total"] == (
            FIRST_SHIPMENT_UNITS
        )

    def test_the_identical_window_is_free_for_a_different_lot(self, api):
        """The window rule is scoped to the lot code, so the window that just collided is
        available to a second lot of the same product.

        PRD: "Note the asymmetry with the lot-window rule of §3.8: inspection windows are half-open and tolerate touching endpoints, distribution windows are closed-closed and do not."

        Design: Difficulty/resource_temporal_overlap/distribution_lot_windows_touch_and_aggregate_against_lot_ceiling
        """
        bundle = _listing_with_one_booked_lot_window(api)

        other_lot = get_success_data(
            api.create_distribution_record(
                bundle["listing_id"],
                F.distribution_record_payload(
                    lot_code="LOT-B", ship_date="2026-08-15", delivery_date="2026-08-20",
                    units_shipped=SECOND_LOT_UNITS,
                ),
                bundle["agent"],
            )
        )

        assert other_lot["lot_code"] == "LOT-B"
        assert other_lot["units_outstanding"] == SECOND_LOT_UNITS
        assert X.read_listing(api, bundle["listing_id"])["distributed_units_total"] == (
            FIRST_SHIPMENT_UNITS + SECOND_LOT_UNITS
        )

    def test_the_aggregate_ceiling_refuses_a_window_that_no_temporal_rule_touches(self, api):
        """A clear window is not enough: the lot's running total of 600 plus 500 more would
        breach the 1000-unit ceiling, and the ceiling is an aggregate over the lot's records
        rather than a per-record limit.

        PRD: "That second rule is an aggregate: every individual record can be small enough to pass while the collection breaches the ceiling."

        Design: Difficulty/resource_temporal_overlap/distribution_lot_windows_touch_and_aggregate_against_lot_ceiling
        """
        bundle = _listing_with_one_booked_lot_window(api)

        validate_error(
            api.create_distribution_record(
                bundle["listing_id"],
                F.distribution_record_payload(
                    lot_code="LOT-A", ship_date="2026-08-16", delivery_date="2026-08-20",
                    units_shipped=500,
                ),
                bundle["agent"],
            ),
            E.ERR_LOT_CAPACITY_EXCEEDED,
        )

    def test_the_ceiling_admits_the_shipment_that_lands_exactly_on_it(self, api):
        """600 plus 400 is exactly the authorised total for the lot, which the rule admits,
        and the product's own distributed total counts every lot together.

        PRD: "That total counts every record of the listing, whatever its recovery state and whether or not it is linked to a withdrawal."

        Design: Difficulty/resource_temporal_overlap/distribution_lot_windows_touch_and_aggregate_against_lot_ceiling
        """
        bundle = _listing_with_one_booked_lot_window(api)
        get_success_data(
            api.create_distribution_record(
                bundle["listing_id"],
                F.distribution_record_payload(
                    lot_code="LOT-B", ship_date="2026-08-15", delivery_date="2026-08-20",
                    units_shipped=SECOND_LOT_UNITS,
                ),
                bundle["agent"],
            )
        )

        at_ceiling = get_success_data(
            api.create_distribution_record(
                bundle["listing_id"],
                F.distribution_record_payload(
                    lot_code="LOT-A", ship_date="2026-08-16", delivery_date="2026-08-20",
                    units_shipped=CEILING_FILLING_UNITS,
                ),
                bundle["agent"],
            )
        )

        assert at_ceiling["units_shipped"] == CEILING_FILLING_UNITS
        assert X.read_listing(api, bundle["listing_id"])["distributed_units_total"] == (
            FIRST_SHIPMENT_UNITS + SECOND_LOT_UNITS + CEILING_FILLING_UNITS
        )

        lot_a_rows, _meta = validate_paginated(
            api.list_distribution_records(
                bundle["agent"],
                {"listing_id": bundle["listing_id"], "lot_code": "LOT-A",
                 "limit": K.MAX_LIMIT},
            )
        )
        assert len(lot_a_rows) == 2
        assert all(row["lot_code"] == "LOT-A" for row in lot_a_rows)

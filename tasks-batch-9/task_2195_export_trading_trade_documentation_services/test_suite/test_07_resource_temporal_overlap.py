"""Two overlap geometries pulling in opposite directions: half-open and closed."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    OPS_ALICE,
    ApiErrorId,
    approx_weight,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

Json = Dict[str, Any]


def _rebooked_into_an_overlapping_window(api) -> Json:
    """Cancel a booking on one sailing, then book an interval that overlaps it."""
    ctx = fx.cleared_order(api)
    ctx["sailing_four"] = fx.create_sailing(
        api,
        cutoff_at="2026-08-15T00:00:00Z",
        etd="2026-08-18T00:00:00Z",
        eta="2026-09-01T00:00:00Z",
    )
    ctx["sailing_five"] = fx.create_sailing(
        api,
        cutoff_at="2026-08-16T00:00:00Z",
        etd="2026-08-19T00:00:00Z",
        eta="2026-09-02T00:00:00Z",
    )
    ctx["booking_four"] = fx.data(
        api.create_booking(
            f.booking_payload(
                ctx["order_id"],
                ctx["sailing_four"]["id"],
                ctx["sailing_four"]["version"],
                booked_weight_kg=400.000,
                container_type="LCL",
            ),
            OPS_ALICE,
        )
    )
    fx.data(
        api.cancel_booking(
            ctx["booking_four"]["id"],
            {"cancel_reason": "carrier rolled the container to a later sailing"},
            OPS_ALICE,
        )
    )
    ctx["attempt"] = api.create_booking(
        f.booking_payload(
            ctx["order_id"],
            ctx["sailing_five"]["id"],
            fx.sailing_version(api, ctx["sailing_five"]["id"]),
            booked_weight_kg=400.000,
            container_type="LCL",
        ),
        OPS_ALICE,
    )
    return ctx


class TestCancelledIntervalIsExcludedFromTheOverlapCheck:
    def test_rebooking_across_an_overlapping_interval_is_accepted(self, api):
        """PRD §2.11: "The new booking's occupation interval does not intersect
        the interval of any live booking of the same order, treating the interval
        as half-open so that touching endpoints do **not** overlap."

        Design: Difficulty/resource_temporal_overlap/rebooking_into_an_overlapping_window_succeeds_because_the_cancelled_interval_is_excluded
        """
        ctx = _rebooked_into_an_overlapping_window(api)
        booking = validate_success(ctx["attempt"], 201)

        assert booking["status"] == "BOOKED"
        assert booking["effective_window_start"] == "2026-08-16T00:00:00Z"
        assert booking["effective_window_end"] == "2026-08-20T00:00:00Z"

    def test_cancelled_booking_keeps_its_window_and_frees_its_sailing(self, api):
        """PRD §3.6: "the sailing's `booked_weight_kg` is recomputed from its
        remaining live bookings and the sailing returns from `FULL` to `OPEN` when
        the recomputed figure is strictly below `capacity_weight_kg` **and** the
        clock is still strictly before `cutoff_at`"

        Design: Difficulty/resource_temporal_overlap/rebooking_into_an_overlapping_window_succeeds_because_the_cancelled_interval_is_excluded
        """
        ctx = _rebooked_into_an_overlapping_window(api)
        validate_success(ctx["attempt"], 201)

        cancelled = fx.data(api.get_booking(ctx["booking_four"]["id"], OPS_ALICE))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["effective_window_start"] == "2026-08-15T00:00:00Z"
        assert cancelled["effective_window_end"] == "2026-08-19T00:00:00Z"

        sailing_four = fx.read_sailing(api, ctx["sailing_four"]["id"])
        assert sailing_four["booked_weight_kg"] == approx_weight(0.000)
        assert sailing_four["status"] == "OPEN"

        sailing_five = fx.read_sailing(api, ctx["sailing_five"]["id"])
        assert sailing_five["booked_weight_kg"] == approx_weight(400.000)
        assert sailing_five["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Licence validity intervals are closed, so touching endpoints collide
# ---------------------------------------------------------------------------

LICENSE_REQUIRED_DECISION = {"license_determination": "LICENSE_REQUIRED", "eccn": "3A001"}


def _two_licences_touching_at_one_instant(api) -> Json:
    buyer = fx.create_buyer(api)
    ctx_one = fx.cleared_order_for_buyer(
        api, buyer, decision_overrides=LICENSE_REQUIRED_DECISION
    )
    licence_one = fx.data(
        api.create_license(
            ctx_one["screening_id"],
            f.license_payload(
                license_number="LIC-2195-A",
                eccn="3A001",
                valid_from="2026-07-01T00:00:00Z",
                valid_to="2026-08-31T00:00:00Z",
                licensed_value_usd=100000.00,
            ),
            COMPLIANCE_CARL,
        )
    )
    ctx_two = fx.cleared_order_for_buyer(
        api, buyer, decision_overrides=LICENSE_REQUIRED_DECISION
    )
    attempt = api.create_license(
        ctx_two["screening_id"],
        f.license_payload(
            license_number="LIC-2195-B",
            eccn="3A001",
            valid_from="2026-08-31T00:00:00Z",
            valid_to="2026-12-31T00:00:00Z",
            licensed_value_usd=100000.00,
        ),
        COMPLIANCE_CARL,
    )
    return {"licence_one": licence_one, "attempt": attempt}


class TestClosedLicenceIntervalsCollideOnTouchingEndpoints:
    def test_second_licence_starting_at_the_first_ones_last_instant_is_refused(self, api):
        """PRD §3.3: "because both endpoints are inclusive, **touching intervals
        do overlap**: a license running to the last instant of March conflicts with
        one starting at that same instant."

        Design: Difficulty/resource_temporal_overlap/second_license_rejected_because_closed_interval_endpoints_touch_exactly
        """
        ctx = _two_licences_touching_at_one_instant(api)
        validate_error(ctx["attempt"], ApiErrorId.ERR_LICENSE_WINDOW_OVERLAP.value)

    def test_refused_licence_is_not_persisted_and_the_first_stays_issued(self, api):
        """PRD §3.3: "The license is created with `status` `ISSUED`,
        `consumed_value_usd` 0.00 and `remaining_value_usd` equal to
        `licensed_value_usd`."

        Design: Difficulty/resource_temporal_overlap/second_license_rejected_because_closed_interval_endpoints_touch_exactly
        """
        ctx = _two_licences_touching_at_one_instant(api)

        licences = fx.rows(api.list_licenses(COMPLIANCE_CARL, {"limit": 100, "offset": 0}))
        assert len(licences) == 1
        assert licences[0]["id"] == ctx["licence_one"]["id"]
        assert licences[0]["status"] == "ISSUED"
        assert licences[0]["remaining_value_usd"] == 100000.00

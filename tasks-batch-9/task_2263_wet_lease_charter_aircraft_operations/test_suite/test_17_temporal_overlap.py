"""Two interval comparisons with opposite conventions.

Airframe occupancy is buffered and half-open; insurance coverage is unbuffered and
closed, so intervals that merely touch collide there and only there.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_flight_leg_payload,
    create_insurance_certificate_payload,
    get_success_data,
    schedule_leg,
    setup_active_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
UNDERWRITER = TEST_USERS["insurance_underwriter_headers"]

BASE_LEG_OUT = "2026-09-25T06:00:00Z"
BASE_LEG_IN = "2026-09-25T10:00:00Z"


def _candidate_leg_payload(scenario, scheduled_out: str, scheduled_in: str) -> dict:
    """A return leg on the same airframe and crew pair as the scenario's base leg."""
    return create_flight_leg_payload(
        scenario["lease"]["id"],
        scenario["aircraft"]["id"],
        scenario["captain"]["id"],
        scenario["first_officer"]["id"],
        scheduled_out=scheduled_out,
        scheduled_in=scheduled_in,
        origin_icao="LEPA",
        dest_icao="EGSS",
        leg_class="REVENUE",
    )


def _lease_with_base_leg(api):
    """ACTIVE lease carrying one SCHEDULED 06:00Z-10:00Z leg on its primary airframe."""
    scenario = setup_active_lease(api)
    base_leg = schedule_leg(api, scenario, BASE_LEG_OUT, BASE_LEG_IN)
    return scenario, base_leg


class TestAirframeOccupancyBoundary:
    def test_candidate_one_minute_inside_the_post_flight_buffer_conflicts(self, api):
        """PRD §3.6: An existing leg on the same airframe, in `SCHEDULED`, `DISPATCHED` or `COMPLETED`, occupies its airframe from forty-five minutes before its `scheduled_out` until forty-five minutes after its `scheduled_in`, and that occupancy window is half-open — the start instant belongs to it, the end instant does not.
        PRD §3.6: The two conflict when the candidate's off-blocks instant is strictly earlier than the occupancy window's end *and* the occupancy window's start is strictly earlier than the candidate's on-blocks instant.
        PRD §3.6: A conflict is refused with `ERR_AIRCRAFT_SCHEDULE_CONFLICT` (HTTP 409).

        Design: Difficulty/resource_temporal_overlap/aircraft_occupancy_half_open_with_forty_five_minute_buffer_boundary
        """
        scenario, base_leg = _lease_with_base_leg(api)

        response = api.create_flight_leg(
            _candidate_leg_payload(
                scenario, "2026-09-25T10:44:00Z", "2026-09-25T12:00:00Z"
            ),
            OPS,
        )
        validate_error(response, ApiErrorId.ERR_AIRCRAFT_SCHEDULE_CONFLICT)

        legs, _ = validate_paginated(
            api.list_flight_legs(OPS, params={"aircraft_id": scenario["aircraft"]["id"]})
        )
        assert [leg["id"] for leg in legs] == [base_leg["id"]], (
            "the conflicting candidate must not be persisted, expected only the base leg "
            f"on the airframe, got {[leg['id'] for leg in legs]}"
        )

    def test_candidate_starting_exactly_at_the_buffer_end_is_admitted(self, api):
        """PRD §3.6: Consequently a candidate that begins exactly at an occupancy window's end does **not** conflict.
        PRD §3.6: `scheduled_block_minutes` is computed once at creation and never changes: it is the whole number of minutes between `scheduled_out` and `scheduled_in`, with any remaining seconds discarded.
        PRD §3.6: The leg is created with `status` `SCHEDULED` and `billing_state` `UNBILLED`; `actual_out`, `actual_in`, `cancelling_party` and `cancel_reason` are all null, `technical_delay_minutes` is 0, `block_minutes` and `billable_block_minutes` are 0, and `crew_requalification_required` is false.

        Design: Difficulty/resource_temporal_overlap/aircraft_occupancy_half_open_with_forty_five_minute_buffer_boundary
        """
        scenario, base_leg = _lease_with_base_leg(api)

        admitted = validate_success(
            api.create_flight_leg(
                _candidate_leg_payload(
                    scenario, "2026-09-25T10:45:00Z", "2026-09-25T12:00:00Z"
                ),
                OPS,
            ),
            201,
        )
        assert admitted["status"] == "SCHEDULED", (
            "a candidate starting exactly at the occupancy window's end must be "
            f"scheduled, got status {admitted['status']}"
        )
        assert admitted["scheduled_block_minutes"] == 75, (
            "10:45Z to 12:00Z is 75 scheduled block minutes, got "
            f"{admitted['scheduled_block_minutes']}"
        )

        legs, _ = validate_paginated(
            api.list_flight_legs(OPS, params={"aircraft_id": scenario["aircraft"]["id"]})
        )
        assert sorted(leg["id"] for leg in legs) == sorted(
            [base_leg["id"], admitted["id"]]
        ), (
            "both the base leg and the adjacent candidate must exist on the airframe, "
            f"got {[leg['id'] for leg in legs]}"
        )


class TestInsuranceCoveragePeriodBoundary:
    def test_replacement_certificate_touching_the_incumbent_expiry_is_refused(self, api):
        """PRD §3.3: The coverage interval is treated as **closed on both ends**: an instant exactly equal to `effective_from` or exactly equal to `expires_at` is covered.
        PRD §3.3: Overlap is judged with both comparisons inclusive — the new window's start not later than the existing window's end, and the existing window's start not later than the new window's end — so two intervals that merely touch at a single instant *do* conflict, and the rejection is `ERR_INSURANCE_PERIOD_OVERLAP` (HTTP 409).
        PRD §3.3: Separately, a new certificate's closed interval must not overlap that of any existing `ACTIVE` certificate on the same lease.

        Design: Difficulty/resource_temporal_overlap/insurance_coverage_closed_interval_touching_endpoint_collides
        """
        scenario = setup_active_lease(
            api, certificate_overrides={"expires_at": "2026-10-31T23:59:59Z"}
        )
        lease_id = scenario["lease"]["id"]

        response = api.create_insurance_certificate(
            create_insurance_certificate_payload(
                lease_id,
                certificate_no="COI-88002",
                effective_from="2026-10-31T23:59:59Z",
                expires_at="2027-03-31T23:59:59Z",
            ),
            UNDERWRITER,
        )
        validate_error(response, ApiErrorId.ERR_INSURANCE_PERIOD_OVERLAP)

        certificates, _ = validate_paginated(
            api.list_insurance_certificates(UNDERWRITER, params={"lease_id": lease_id})
        )
        assert [cert["certificate_no"] for cert in certificates] == ["COI-88001"], (
            "the touching certificate must never be persisted, expected only COI-88001 "
            f"on the lease, got {[cert['certificate_no'] for cert in certificates]}"
        )

    def test_replacement_certificate_starting_one_second_later_is_accepted(self, api):
        """PRD §3.3: A new certificate is created with `status` `ACTIVE` and `revocation_reason` null.
        PRD §3.3: Overlap is judged with both comparisons inclusive — the new window's start not later than the existing window's end, and the existing window's start not later than the new window's end — so two intervals that merely touch at a single instant *do* conflict, and the rejection is `ERR_INSURANCE_PERIOD_OVERLAP` (HTTP 409).
        PRD §3.3: When the lease is `SUSPENDED` with `suspension_reason` `INSURANCE_LAPSED` and a prior certificate on that lease is still `ACTIVE` while its window does not overlap the new one, that prior certificate moves from `ACTIVE` to `SUPERSEDED`: the lease's state is unchanged by the supersession itself, and the superseded certificate stops counting toward dispatch cover.
        PRD §3.5: `suspension_reason` is null in every state other than `SUSPENDED`.

        Design: Difficulty/resource_temporal_overlap/insurance_coverage_closed_interval_touching_endpoint_collides
        """
        scenario = setup_active_lease(
            api, certificate_overrides={"expires_at": "2026-10-31T23:59:59Z"}
        )
        lease_id = scenario["lease"]["id"]
        incumbent_id = scenario["certificate"]["id"]

        accepted = validate_success(
            api.create_insurance_certificate(
                create_insurance_certificate_payload(
                    lease_id,
                    certificate_no="COI-88003",
                    effective_from="2026-11-01T00:00:00Z",
                    expires_at="2027-03-31T23:59:59Z",
                ),
                UNDERWRITER,
            ),
            201,
        )
        assert accepted["status"] == "ACTIVE", (
            "a certificate starting one second after the incumbent's expiry must be "
            f"created ACTIVE, got {accepted['status']}"
        )

        incumbent = get_success_data(
            api.get_insurance_certificate(incumbent_id, UNDERWRITER)
        )
        assert incumbent["status"] == "ACTIVE", (
            "the lease is ACTIVE, so no supersession occurs and the incumbent stays "
            f"ACTIVE, got {incumbent['status']}"
        )

        certificates, _ = validate_paginated(
            api.list_insurance_certificates(UNDERWRITER, params={"lease_id": lease_id})
        )
        assert sorted(cert["certificate_no"] for cert in certificates) == [
            "COI-88001",
            "COI-88003",
        ], (
            "the lease must carry exactly the incumbent and the accepted replacement, "
            f"got {sorted(cert['certificate_no'] for cert in certificates)}"
        )

        lease = get_success_data(api.get_lease(lease_id, OPS))
        assert lease["status"] == "ACTIVE", (
            f"attaching a future certificate must not move the lease, got {lease['status']}"
        )
        assert lease["suspension_reason"] is None, (
            "suspension_reason is null in every state other than SUSPENDED, got "
            f"{lease['suspension_reason']}"
        )

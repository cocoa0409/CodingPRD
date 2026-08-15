"""Banner fabrication lifecycle: revision promotion forces refab, and banner
readiness gates slot booking ahead of the seasonal-capacity check."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_draft_banner,
    create_ready_banner,
    fabricate_banner,
    get_capacity,
    make_client_headers,
    propose_and_activate_revision,
    setup_operation,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN


class TestRevisionPromotionForcesRefab:

    def test_approve_new_revision_demotes_ready_banner(self, api):
        """PRD §3.3: "Approval moves it to `APPROVED`, and the system
        immediately and automatically promotes it to `ACTIVE`, performing
        three steps in a pinned order: first the prior `ACTIVE` revision on
        the same banner becomes `SUPERSEDED`; second, if the banner's status
        is `IN_FABRICATION` or `READY`, it is forced back to `DRAFT`; third,
        the banner's `current_revision_id` is updated to the newly active
        revision."

        Design: Difficulty/non_linear_state_machine/banner_revision_cycle_forces_refab
        """
        sc = setup_operation(base_code="KRF1", with_ready_banner=False)
        banner, rev1 = create_ready_banner(sc["campaign"]["id"],
                                           sc["client"]["id"], text="MSG-1")
        assert banner["status"] == "READY"
        rev2 = propose_and_activate_revision(banner["id"], sc["client"]["id"],
                                             text="MSG-2",
                                             artwork_hash="art-hash-2")
        after = validate_success(api.get_banner(banner["id"], ADMIN),
                                 expected_status=200)
        assert after["status"] == "DRAFT", (
            f"READY banner must be forced back to DRAFT on revision "
            f"promotion, got {after['status']}"
        )
        assert after["current_revision_id"] == rev2["id"], (
            f"banner must reference the newly active revision, got "
            f"{after['current_revision_id']}"
        )
        rev1_after = validate_success(api.get_banner_revision(rev1["id"], ADMIN),
                                      expected_status=200)
        assert rev1_after["status"] == "SUPERSEDED", (
            f"prior ACTIVE revision must become SUPERSEDED, got "
            f"{rev1_after['status']}"
        )
        assert rev2["status"] == "ACTIVE"

    def test_approve_new_revision_demotes_in_fabrication_banner(self, api):
        """PRD §3.3: "if the banner's status is `IN_FABRICATION` or `READY`,
        it is forced back to `DRAFT`". PRD §3.3: "Any later revision promotion
        — whether the banner sits `IN_FABRICATION` or `READY` — knocks it back
        to `DRAFT` automatically and updates its `current_revision_id`".

        Design: Difficulty/non_linear_state_machine/banner_revision_cycle_forces_refab
        """
        sc = setup_operation(base_code="KRF2", with_ready_banner=False)
        banner = create_draft_banner(sc["campaign"]["id"], sc["client"]["id"])
        rev1 = propose_and_activate_revision(banner["id"], sc["client"]["id"],
                                             text="MSG-1")
        fabricate_banner(banner["id"])
        mid = validate_success(api.get_banner(banner["id"], ADMIN),
                               expected_status=200)
        assert mid["status"] == "IN_FABRICATION"
        rev2 = propose_and_activate_revision(banner["id"], sc["client"]["id"],
                                             text="MSG-2",
                                             artwork_hash="art-hash-2")
        after = validate_success(api.get_banner(banner["id"], ADMIN),
                                 expected_status=200)
        assert after["status"] == "DRAFT", (
            f"IN_FABRICATION banner must be forced back to DRAFT on revision "
            f"promotion, got {after['status']}"
        )
        assert after["current_revision_id"] == rev2["id"]
        rev1_after = validate_success(api.get_banner_revision(rev1["id"], ADMIN),
                                      expected_status=200)
        assert rev1_after["status"] == "SUPERSEDED"


class TestBannerReadinessGatesBooking:

    def test_draft_banner_blocks_slot_booking(self, api):
        """PRD §3.5: "then banner readiness, which requires the banner to be
        `READY` with its `current_revision_id` set and long enough for the
        route, failing as `ERR_BANNER_NOT_READY` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/slot_booking_requires_banner_ready
        """
        sc = setup_operation(base_code="KBNR1", with_ready_banner=False)
        banner = create_draft_banner(sc["campaign"]["id"], sc["client"]["id"])
        resp = api_client.create_flight_slot(
            sc["campaign"]["id"],
            {
                "route_id": sc["route"]["id"],
                "airspace_approval_id": sc["approval"]["id"],
                "banner_id": banner["id"],
                "date_local": "2026-08-13",
                "planned_start_utc": "2026-08-13T15:00:00Z",
                "planned_duration_hours": 1,
                "expected_seasonal_capacity_version": sc["capacity"]["version"],
            },
            make_client_headers(sc["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BANNER_NOT_READY, expected_status=409)

    def test_in_fabrication_banner_blocks_slot_booking(self, api):
        """PRD §3.5: "then banner readiness, which requires the banner to be
        `READY` with its `current_revision_id` set and long enough for the
        route, failing as `ERR_BANNER_NOT_READY` (HTTP 409)". A banner that
        has an active revision but is still being printed is not `READY`.

        Design: Difficulty/cross_entity_state_dependency/slot_booking_requires_banner_ready
        """
        sc = setup_operation(base_code="KBNR2", with_ready_banner=False)
        banner = create_draft_banner(sc["campaign"]["id"], sc["client"]["id"])
        propose_and_activate_revision(banner["id"], sc["client"]["id"])
        fabricate_banner(banner["id"])  # IN_FABRICATION, never marked READY
        capacity = get_capacity(sc["capacity"]["id"])
        resp = api_client.create_flight_slot(
            sc["campaign"]["id"],
            {
                "route_id": sc["route"]["id"],
                "airspace_approval_id": sc["approval"]["id"],
                "banner_id": banner["id"],
                "date_local": "2026-08-13",
                "planned_start_utc": "2026-08-13T15:00:00Z",
                "planned_duration_hours": 1,
                "expected_seasonal_capacity_version": capacity["version"],
            },
            make_client_headers(sc["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BANNER_NOT_READY, expected_status=409)


class TestBookingCheckOrderBannerBeforeCapacity:

    def test_banner_not_ready_preempts_capacity_exceeded(self, api):
        """PRD §3.5: "the business rules fire in this sequence: first the TFR
        check of §3.4, then confirmation that the airspace approval is
        `GRANTED` and covers the slot" ... "then banner readiness, which
        requires the banner to be `READY` with its `current_revision_id` set
        and long enough for the route, failing as `ERR_BANNER_NOT_READY`
        (HTTP 409)" ... "Capacity is checked next: the `hours_remaining` of
        the target base-and-month `SeasonalCapacity` must be at least the
        slot's `planned_duration_hours`, failing as
        `ERR_SEASONAL_CAPACITY_EXCEEDED` (HTTP 409)."

        With a DRAFT banner AND a zero-hour quota both violated, the banner
        rejection surfaces.

        Design: Difficulty/priority_pair_validation_conflict/business_fiscal_vs_business_constraint_on_booking
        """
        sc = setup_operation(base_code="KORD1", with_ready_banner=False, quota=0)
        banner = create_draft_banner(sc["campaign"]["id"], sc["client"]["id"])
        resp = api_client.create_flight_slot(
            sc["campaign"]["id"],
            {
                "route_id": sc["route"]["id"],
                "airspace_approval_id": sc["approval"]["id"],
                "banner_id": banner["id"],
                "date_local": "2026-08-13",
                "planned_start_utc": "2026-08-13T15:00:00Z",
                "planned_duration_hours": 1,
                "expected_seasonal_capacity_version": sc["capacity"]["version"],
            },
            make_client_headers(sc["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BANNER_NOT_READY, expected_status=409)

    def test_banner_without_active_revision_preempts_capacity_exceeded(self, api):
        """PRD §3.5: "banner readiness, which requires the banner to be
        `READY` with its `current_revision_id` set and long enough for the
        route, failing as `ERR_BANNER_NOT_READY` (HTTP 409)" precedes the
        capacity check, which "is checked next" per the same pinned sequence.

        Here the banner was fabricated with no revision ever proposed
        (current_revision_id unset), and the quota is zero.

        Design: Difficulty/priority_pair_validation_conflict/business_fiscal_vs_business_constraint_on_booking
        """
        sc = setup_operation(base_code="KORD2", with_ready_banner=False, quota=0)
        banner = create_draft_banner(sc["campaign"]["id"], sc["client"]["id"])
        resp = api_client.create_flight_slot(
            sc["campaign"]["id"],
            {
                "route_id": sc["route"]["id"],
                "airspace_approval_id": sc["approval"]["id"],
                "banner_id": banner["id"],
                "date_local": "2026-08-13",
                "planned_start_utc": "2026-08-13T16:00:00Z",
                "planned_duration_hours": 1,
                "expected_seasonal_capacity_version": sc["capacity"]["version"],
            },
            make_client_headers(sc["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BANNER_NOT_READY, expected_status=409)

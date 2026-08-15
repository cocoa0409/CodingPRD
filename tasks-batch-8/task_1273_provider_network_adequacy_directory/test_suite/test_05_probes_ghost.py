"""Availability probes: wait-day thresholds, ghost-strike boundary (PRD §3.5)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_probe_payload,
    set_clock, create_region, create_standard, create_provider, create_location,
    create_listing, publish_listing, create_probe, get_listing, setup_listed_network,
)

NM = TEST_USERS["network_manager_headers"]


def _setup_listing_with_three_probes():
    ctx = setup_listed_network(county_fips="06029", enrolled_member_count=100,
                               listing_overrides={"display_name": "Heart 21",
                                                  "phone": "555-0121"})
    set_clock("2026-05-04T09:00:00Z")
    pb1 = create_probe(ctx["listing"]["id"], requested_date="2026-05-02")
    pb2 = create_probe(ctx["listing"]["id"], requested_date="2026-05-03")
    pb3 = create_probe(ctx["listing"]["id"], requested_date="2026-05-04")
    return ctx, [pb1, pb2, pb3]


class TestGhostStrikeBoundary:
    def test_two_consecutive_fails_keep_listing_listed(self, api):
        """PRD §3.5: "When the recomputed count reaches 3 and the listing is currently
        `LISTED`, the listing automatically transitions to `UNDER_REVIEW` and its
        `version` increments by 1 — this is the system's way of pulling the listing out
        of the counted adequacy set while a human decides whether the ghost is
        confirmed."

        Design: Difficulty/boundary_precision_check/third_consecutive_probe_fail_moves_listing_to_under_review
        """
        ctx, probes = _setup_listing_with_three_probes()
        record1 = validate_success(api.record_probe(probes[0]["id"],
                                                    {"outcome": "UNREACHABLE"}, NM))
        assert record1["result"] == "FAIL"
        record2 = validate_success(api.record_probe(probes[1]["id"],
                                                    {"outcome": "UNREACHABLE"}, NM))
        assert record2["result"] == "FAIL"
        listing = get_listing(ctx["listing"]["id"])
        assert listing["status"] == "LISTED", "two strikes must not trip the threshold"
        assert listing["ghost_strike_count"] == 2

    def test_third_consecutive_fail_moves_listing_to_under_review(self, api):
        """PRD §3.5: "When the recomputed count reaches 3 and the listing is currently
        `LISTED`, the listing automatically transitions to `UNDER_REVIEW` and its
        `version` increments by 1 — this is the system's way of pulling the listing out
        of the counted adequacy set while a human decides whether the ghost is
        confirmed. The threshold boundary is inclusive: the third consecutive `FAIL`
        transitions."

        Design: Difficulty/boundary_precision_check/third_consecutive_probe_fail_moves_listing_to_under_review
        """
        ctx, probes = _setup_listing_with_three_probes()
        validate_success(api.record_probe(probes[0]["id"], {"outcome": "UNREACHABLE"}, NM))
        validate_success(api.record_probe(probes[1]["id"], {"outcome": "UNREACHABLE"}, NM))
        validate_success(api.record_probe(probes[2]["id"], {"outcome": "UNREACHABLE"}, NM))
        listing = get_listing(ctx["listing"]["id"])
        assert listing["status"] == "UNDER_REVIEW", "the 3rd consecutive FAIL transitions"
        assert listing["ghost_strike_count"] == 3


class TestProbeWaitDays:
    def test_probe_wait_days_inclusive_threshold(self, api):
        """PRD §3.5: "`result` is `PASS` when the outcome is `KEPT` and
        `days_to_appointment` is at or below the applicable standard's wait ceiling —
        `max_wait_days_routine` for a `ROUTINE` probe, `max_wait_days_urgent` for an
        `URGENT` probe — and `FAIL` otherwise; the boundary is inclusive, so a wait
        equal to the ceiling passes."

        Design: Corner/calculations/probe_wait_days_inclusive_threshold
        """
        ctx = setup_listed_network(county_fips="06069", enrolled_member_count=100,
                                   listing_overrides={"display_name": "L57",
                                                      "phone": "555-0157"})
        set_clock("2026-06-01T09:00:00Z")
        pb15 = create_probe(ctx["listing"]["id"], probe_type="ROUTINE",
                            requested_date="2026-06-01")
        pb16 = create_probe(ctx["listing"]["id"], probe_type="ROUTINE",
                            requested_date="2026-06-01")
        pbu = create_probe(ctx["listing"]["id"], probe_type="URGENT",
                           requested_date="2026-06-01")
        set_clock("2026-06-17T00:00:00Z")
        r15 = validate_success(api.record_probe(
            pb15["id"], {"outcome": "KEPT", "offered_appointment_date": "2026-06-16"}, NM))
        assert r15["days_to_appointment"] == 15
        assert r15["result"] == "PASS", "15 == max_wait_days_routine passes (inclusive)"
        r16 = validate_success(api.record_probe(
            pb16["id"], {"outcome": "KEPT", "offered_appointment_date": "2026-06-17"}, NM))
        assert r16["days_to_appointment"] == 16
        assert r16["result"] == "FAIL", "one day over the routine ceiling fails"
        ru = validate_success(api.record_probe(
            pbu["id"], {"outcome": "KEPT", "offered_appointment_date": "2026-06-04"}, NM))
        assert ru["days_to_appointment"] == 3
        assert ru["result"] == "FAIL", "3 days exceeds the URGENT ceiling of 2"


class TestProbeGuards:
    def test_probe_record_with_offered_before_requested_rejected(self, api):
        """PRD §3.5: "When `outcome` is `KEPT`, `offered_appointment_date` is required
        and must be on or after `requested_date` (else `ERR_PROBE_DATE_ORDER`); when
        `outcome` is `UNREACHABLE` or `NO_APPOINTMENT_OFFERED`,
        `offered_appointment_date` stays null."

        Design: Corner/validations/probe_record_with_offered_before_requested_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        ctx = setup_listed_network(county_fips="06081", enrolled_member_count=100,
                                   clock="2026-06-01T00:00:00Z",
                                   listing_overrides={"display_name": "L69",
                                                      "phone": "555-0169"})
        probe = create_probe(ctx["listing"]["id"], requested_date="2026-05-30")
        resp = api.record_probe(
            probe["id"], {"outcome": "KEPT", "offered_appointment_date": "2026-05-29"}, NM)
        validate_error(resp, ApiErrorId.ERR_PROBE_DATE_ORDER)

    def test_probe_create_on_draft_listing_rejected(self, api):
        """PRD §3.5: "A `NetworkManager` schedules a probe against a listing that must
        currently be `LISTED` (else `ERR_LISTING_NOT_LISTED`), supplying `probe_type`
        (`ROUTINE` or `URGENT`) and `requested_date`."

        Design: Corner/errors/probe_create_on_draft_listing_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        region = create_region(county_fips="06103", name="Mono2")
        provider = create_provider(legal_name="P85")
        location = create_location(provider["id"], region["id"], address_line="85 A St")
        listing = create_listing(provider["id"], location["id"], display_name="L85",
                                 phone="555-0185")
        resp = api.create_probe(
            create_probe_payload(listing["id"], requested_date="2026-04-30"), NM)
        validate_error(resp, ApiErrorId.ERR_LISTING_NOT_LISTED)

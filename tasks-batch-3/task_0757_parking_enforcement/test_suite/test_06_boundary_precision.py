"""Difficulty rule: boundary_precision_check.

Integer-count boundaries checked at X-1 and X:
  (A) scofflaw flips to SCOFFLAW exactly at unpaid_citation_count >= 3;
  (B) closing a shift with zero citations pins citations_per_hour to 0.00
      (no divide-by-zero), not an error.
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    TEST_USERS,
    setup_issuing_context,
    issue_in_context,
    create_officer,
    create_beat,
    open_shift,
    close_shift,
)

ADMIN = TEST_USERS["admin_headers"]


class TestScofflawUnpaidCountThreshold:
    def test_two_unpaid_citations_stay_none(self, api):
        """PRD §3.4: "Otherwise, if the `unpaid_citation_count` is at least 3, the
        vehicle is `SCOFFLAW`. Otherwise it is `NONE`."

        Design: Difficulty/boundary_precision_check/scofflaw_unpaid_count_threshold
        """
        # STREET_CLEAN base 6000, RESIDENTIAL: 6000 + 9000 = 15000, count 2 -> NONE.
        ctx = setup_issuing_context(base_fine_cents=6000, code="STREET_CLEAN",
                                    is_booting_eligible=False)
        issue_in_context(ctx, evidence_photo_url="https://ev/b1.jpg")
        issue_in_context(ctx, evidence_photo_url="https://ev/b2.jpg")
        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert veh["unpaid_citation_count"] == 2
        assert veh["scofflaw_status"] == "NONE", \
            f"count 2 is below the SCOFFLAW threshold, got {veh['scofflaw_status']}"

    def test_third_unpaid_citation_flips_to_scofflaw(self, api):
        """PRD §3.4: "Otherwise, if the `unpaid_citation_count` is at least 3, the
        vehicle is `SCOFFLAW`. Otherwise it is `NONE`."

        Design: Difficulty/boundary_precision_check/scofflaw_unpaid_count_threshold
        """
        ctx = setup_issuing_context(base_fine_cents=6000, code="STREET_CLEAN",
                                    is_booting_eligible=False)
        issue_in_context(ctx, evidence_photo_url="https://ev/b1.jpg")
        issue_in_context(ctx, evidence_photo_url="https://ev/b2.jpg")
        issue_in_context(ctx, evidence_photo_url="https://ev/b3.jpg")
        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert veh["unpaid_citation_count"] == 3
        assert veh["outstanding_balance_cents"] == 27000, \
            f"expected 27000 (6000+9000+12000), got {veh['outstanding_balance_cents']}"
        assert veh["scofflaw_status"] == "SCOFFLAW", \
            f"count 3 must flip to SCOFFLAW, got {veh['scofflaw_status']}"
        # Balance 27000 < 50000 so no boot order was auto-created.
        _, ometa = validate_paginated(
            api.list_boot_tow_orders(ADMIN, params={"vehicle_id": ctx["vehicle"]["id"]}))
        assert ometa["total_count"] == 0, \
            f"SCOFFLAW tier must not create a boot order, got {ometa['total_count']}"


class TestShiftCloseZeroCitations:
    def _empty_open_shift(self):
        officer = create_officer(badge_number="B-BP2")
        beat = create_beat(patrol_zone="RESIDENTIAL", beat_code="RESB")
        return open_shift(officer["id"], beat["id"],
                          scheduled_start="2026-03-02T08:00:00Z",
                          scheduled_end="2026-03-02T10:00:00Z"), officer

    def test_zero_citations_gross_and_net_are_zero(self, api):
        """PRD §3.2: "The `gross_citation_count` is the raw count of every citation
        issued during the shift, including any later voided or dismissed. The
        `net_citation_count` is the quality-adjusted count: every citation of the
        shift whose `status` is not `VOID` and not `DISMISSED`."

        Design: Difficulty/boundary_precision_check/shift_close_zero_citations_productivity
        """
        shift, officer = self._empty_open_shift()
        closed = close_shift(shift["id"], officer["id"])
        assert closed["gross_citation_count"] == 0
        assert closed["net_citation_count"] == 0

    def test_zero_net_pins_per_hour_to_zero_no_divide(self, api):
        """PRD §3.2: "the elapsed time from `scheduled_start` to `scheduled_end`,
        which validation guarantees is positive — and is rounded half-up to two
        decimal places; when the net count is zero, `citations_per_hour` is exactly
        0.00."

        Design: Difficulty/boundary_precision_check/shift_close_zero_citations_productivity
        """
        shift, officer = self._empty_open_shift()
        closed = close_shift(shift["id"], officer["id"])
        assert closed["citations_per_hour"] == 0.00, \
            f"zero net count must yield 0.00, got {closed['citations_per_hour']}"
        assert closed["status"] == "CLOSED"

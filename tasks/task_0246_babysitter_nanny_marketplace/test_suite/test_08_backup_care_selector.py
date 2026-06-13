"""Backup-care dispatch selector: rating-first ranking among eligible caregivers,
and the empty-eligibility rejection.

Translates corner calculations instances under select_backup_caregiver.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    set_clock, create_family, create_caregiver, create_cleared_available_caregiver,
    create_open_posting, offer_booking, confirm_booking, first_session, complete_session,
    submit_review, publish_review, open_backup_request, clear_background_check,
    make_family_headers, make_caregiver_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


class TestBackupSelectorRanking:
    """Corner calculations / backup_selector_ranks_rating_then_rate."""

    def test_higher_rated_caregiver_matched_over_cheaper(self, api):
        """PRD §3.8: "Among the eligible caregivers, the selector ranks by, in
        descending priority: highest `rating_avg` first (compared at two decimal
        places); then, breaking ties, the lowest `hourly_rate_floor_cents`
        (cheaper preferred); then, breaking remaining ties, the earliest
        `created_at` — never the `id`. The first caregiver under that ranking
        becomes the `matched_caregiver_id`".

        HI: rating 5.0, floor 2500. LO: rating 0, floor 1500. Both eligible
        (BASIC, floor <= 3000). HI matched on rating despite being pricier.

        Design: Corner/calculations/backup_selector_ranks_rating_then_rate
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=200000, num_children=1,
                            required_tier="BASIC", email="bk@x.com")

        # HI caregiver: clear, available, floor 2500, earns a published 5-star.
        hi = create_cleared_available_caregiver(tier="BASIC", hourly_rate_floor_cents=2500,
                                                email="hi@x.com")
        ph = create_open_posting(fam["id"], care_type="ONE_TIME",
                                 family_pay_rate_cents=2500, required_tier="BASIC", title="Hp")
        bh = offer_booking(fam["id"], hi["id"], ph["id"], agreed_rate_cents=2500,
                           scheduled_start="2026-04-05T08:00:00Z",
                           scheduled_end="2026-04-05T12:00:00Z")
        bh = confirm_booking(bh["id"], hi["id"])
        sh = first_session(bh["id"])
        complete_session(sh, hi["id"], clock_in="2026-04-05T08:00:00Z",
                         clock_out="2026-04-05T12:00:00Z")
        rvh = submit_review(bh["id"], fam["id"], hi["id"], 5)
        publish_review(rvh["id"])
        # clock-out returned HI to AVAILABLE; assert that explicitly.
        get_success_data(api.set_availability(
            hi["id"], {"availability_status": "AVAILABLE"}, make_caregiver_headers(hi["id"])))

        # LO caregiver: clear, available, floor 1500, no reviews (rating 0).
        lo = create_cleared_available_caregiver(tier="BASIC", hourly_rate_floor_cents=1500,
                                                email="lo@x.com")

        set_clock("2026-05-01T00:00:00Z")
        req = open_backup_request(fam["id"], needed_start="2026-05-02T08:00:00Z",
                                  needed_end="2026-05-02T12:00:00Z",
                                  required_tier="BASIC", max_rate_cents=3000)
        matched = validate_success(api.match_backup_request(
            req["id"], {"expected_backuprequest_version": req["version"]}, ADMIN), 200)
        assert matched["status"] == "MATCHED"
        assert matched["matched_caregiver_id"] == hi["id"], \
            "rating-first ranking must match the higher-rated caregiver"


class TestBackupNoEligibleCaregiver:
    """Corner calculations / backup_match_no_eligible_caregiver_returns_error."""

    def test_no_eligible_caregiver_rejected_request_stays_open(self, api):
        """PRD §3.8: "If no caregiver is eligible, the match is rejected with
        `ERR_NO_ELIGIBLE_CAREGIVER` and no match is recorded."
        PRD §3.8: "a caregiver qualifies only if their `availability_status` is
        `AVAILABLE`".

        Only caregiver is CLEAR at BASIC but OFFLINE → no eligible caregiver →
        422, request stays OPEN.

        Design: Corner/calculations/backup_match_no_eligible_caregiver_returns_error
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=50000, num_children=1,
                            required_tier="BASIC", email="ne@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="off@x.com")
        # cleared but left OFFLINE (never set AVAILABLE).
        clear_background_check(cg["id"], tier="BASIC")
        req = open_backup_request(fam["id"], needed_start="2026-03-05T08:00:00Z",
                                  needed_end="2026-03-05T12:00:00Z",
                                  required_tier="BASIC", max_rate_cents=3000)
        res = api.match_backup_request(
            req["id"], {"expected_backuprequest_version": req["version"]}, ADMIN)
        validate_error(res, "ERR_NO_ELIGIBLE_CAREGIVER")
        after = validate_success(api.get_backup_request(req["id"], ADMIN), 200)
        assert after["status"] == "OPEN"

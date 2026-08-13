"""Talent booking fees and conflicts; sponsor deal workflow and ownership."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_logical_clock_instant,
    create_sponsor_deal,
    create_talent,
    create_talent_booking,
    create_tournament,
    get_talent_booking,
    make_sponsor_manager_headers,
    setup_in_progress_2team,
    setup_seeded_tournament,
    transition_sponsor_deal,
    transition_talent_booking,
    validate_error,
)

ADMIN = TEST_USERS["organizer_admin_headers"]
PRODUCER = TEST_USERS["broadcast_producer_headers"]


class TestTalentFeeVariants:

    def test_talent_fee_quote_at_creation_and_confirm(self):
        """PRD §3.10: "A new booking lands in `TENTATIVE` with
        `fee_quote_cents` computed by the provisional talent-fee variant: the
        shift duration in hours is the difference between end and start in
        minutes divided by 60, taken exactly; the day units are that duration
        divided by 8 rounded up to a whole number; the quote is
        `day_rate_cents` multiplied by the day units, with no uplift, no
        overtime, and no royalty."

        Design: Difficulty/dual_variant_calc/talent_fee_quote_vs_settled
        """
        ctx = setup_seeded_tournament("Fee Cup", region="EU")
        tournament_id = ctx["tournament"]["id"]
        talent = create_talent("CasterPrime", "NA", 80000, cross_region=True)
        booking = create_talent_booking(
            tournament_id, talent["id"], "MAIN",
            "2026-08-12T10:00:00Z", "2026-08-12T20:00:00Z")
        # 10 hours -> ceil(10/8) = 2 day units * 80000 cents.
        assert booking["status"] == "TENTATIVE"
        assert booking["fee_quote_cents"] == 160000, \
            "PROVISIONAL quote: raw day units only, no uplift/overtime/royalty"

        confirmed = transition_talent_booking(booking["id"], "CONFIRM")
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["fee_quote_cents"] == 160000, \
            "the quote is not recomputed at confirm time"

    def test_talent_fee_settled_final_components(self):
        """PRD §3.10: "Step 3 applies the cross-region uplift: if the
        talent's `home_region` differs from the tournament's `region`, the
        base is multiplied by 1.15 and rounded half-up to integer cents; the
        uplift applies to the base only, never to overtime."
        PRD §3.10: "Step 4 computes overtime as the number of hours by which
        the duration exceeds 8 (zero when the duration is 8 or less),
        multiplied by the hourly rate (`day_rate_cents` divided by 8),
        multiplied by 1.5, rounded half-up."
        PRD §3.10: "Step 6 assembles the final fee as base plus overtime plus
        royalty."
        PRD §3.10: "Identical inputs settle to a strictly larger
        `fee_final_cents` than `fee_quote_cents` whenever any of the uplift,
        overtime, or royalty components is nonzero."

        Design: Difficulty/dual_variant_calc/talent_fee_quote_vs_settled
        """
        ctx = setup_in_progress_2team("Fee Cup", region="EU")
        tournament_id = ctx["tournament"]["id"]
        talent = create_talent("CasterPrime", "NA", 80000, cross_region=True)
        booking = create_talent_booking(
            tournament_id, talent["id"], "MAIN",
            "2026-08-12T10:00:00Z", "2026-08-12T20:00:00Z")
        transition_talent_booking(booking["id"], "CONFIRM")

        settled = transition_talent_booking(booking["id"], "SETTLE")
        assert settled["status"] == "SETTLED"
        # base 160000 -> uplifted 15% to 184000; overtime 2h * 10000 * 1.5 =
        # 30000; royalty band 0% because 184000 < 200000.
        assert settled["fee_final_cents"] == 214000
        assert settled["fee_quote_cents"] == 160000
        assert settled["fee_final_cents"] != settled["fee_quote_cents"]


class TestTalentRoyaltyBand:

    def test_royalty_band_selected_from_base_not_total(self):
        """PRD §3.10: "Step 5 selects the royalty band from the post-uplift
        base only — never from the total, which is what makes the order
        load-bearing: a base below 200000 cents carries 0% royalty; a base of
        at least 200000 but below 500000 carries 5%; a base of at least
        500000 carries 10%."

        Design: Difficulty/combinatorial_formula/talent_royalty_band_on_base_not_total
        """
        ctx = setup_in_progress_2team("Royalty Cup", region="NA")
        tournament_id = ctx["tournament"]["id"]
        talent = create_talent("CasterLocal", "NA", 95000)
        booking = create_talent_booking(
            tournament_id, talent["id"], "MAIN",
            "2026-08-12T10:00:00Z", "2026-08-12T20:00:00Z")
        transition_talent_booking(booking["id"], "CONFIRM")

        settled = transition_talent_booking(booking["id"], "SETTLE")
        # base = 2 day units * 95000 = 190000 (no uplift, same region);
        # overtime = 2h * (95000/8) * 1.5 = 35625; royalty = 0 because the
        # band is read from base 190000 (< 200000), never from the total.
        assert settled["fee_final_cents"] == 225625, \
            "190000 base + 35625 overtime + 0 royalty; reading the band from the 225625 total would wrongly imply 5%"

    def test_royalty_band_two_lower_bound_inclusive(self):
        """PRD §3.10: "a base below 200000 cents carries 0% royalty; a base
        of at least 200000 but below 500000 carries 5%; a base of at least
        500000 carries 10%."
        PRD §3.10: "Step 6 assembles the final fee as base plus overtime plus
        royalty."

        Design: Difficulty/combinatorial_formula/talent_royalty_band_on_base_not_total
        """
        ctx = setup_in_progress_2team("Royalty2 Cup", region="NA")
        tournament_id = ctx["tournament"]["id"]
        talent = create_talent("CasterBand", "NA", 100000)
        booking = create_talent_booking(
            tournament_id, talent["id"], "MAIN",
            "2026-08-12T10:00:00Z", "2026-08-13T02:00:00Z")
        transition_talent_booking(booking["id"], "CONFIRM")

        settled = transition_talent_booking(booking["id"], "SETTLE")
        # 16 hours -> 2 day units -> base exactly 200000 -> 5% band
        # (inclusive lower bound): royalty 10000; overtime 8h * 12500 * 1.5 =
        # 150000; total 200000 + 150000 + 10000.
        assert settled["fee_final_cents"] == 360000


class TestTalentWindowConflict:

    def test_touching_shifts_conflict(self):
        """PRD §3.10: "The talent window conflict rule treats each confirmed
        booking as the closed interval from `shift_start_at` to
        `shift_end_at`: two such intervals for the same talent among
        `CONFIRMED` bookings must be disjoint, and back-to-back bookings
        where the prior shift's end equals the next shift's start are a
        conflict (unlike the server window rule). A collision is rejected
        with `ERR_TALENT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/talent_closed_interval_touch_conflicts
        """
        ctx = setup_seeded_tournament("Talent Cup")
        tournament_id = ctx["tournament"]["id"]
        talent = create_talent("CasterTouch", "NA", 80000)
        booking = create_talent_booking(
            tournament_id, talent["id"], "MAIN",
            "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z")
        transition_talent_booking(booking["id"], "CONFIRM")

        resp = api_client.create_talent_booking(
            {"tournament_id": tournament_id, "talent_id": talent["id"],
             "stage_label": "MAIN",
             "shift_start_at": "2026-08-12T12:00:00Z",
             "shift_end_at": "2026-08-12T14:00:00Z"},
            PRODUCER)
        # closed-interval semantics: end == start touches and conflicts
        validate_error(resp, ApiErrorId.ERR_TALENT_WINDOW_CONFLICT)
        assert get_talent_booking(booking["id"])["status"] == "CONFIRMED"

    def test_conflict_check_only_against_confirmed(self):
        """PRD §3.10: "The talent window conflict rule treats each confirmed
        booking as the closed interval from `shift_start_at` to
        `shift_end_at`: two such intervals for the same talent among
        `CONFIRMED` bookings must be disjoint"
        PRD §3.10: "Confirming a booking moves `TENTATIVE → CONFIRMED` and
        requires the tournament to be in `SEEDED` or `IN_PROGRESS`; the
        closed-interval conflict check among other `CONFIRMED` bookings is
        re-applied at confirm time."

        Design: Difficulty/resource_temporal_overlap/talent_closed_interval_touch_conflicts
        """
        ctx = setup_seeded_tournament("ConfirmCheck Cup")
        tournament_id = ctx["tournament"]["id"]
        talent = create_talent("CasterDup", "NA", 80000)
        # Overlapping TENTATIVE bookings coexist: only CONFIRMED bookings
        # participate in the conflict set.
        b1 = create_talent_booking(
            tournament_id, talent["id"], "MAIN",
            "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z")
        b2 = create_talent_booking(
            tournament_id, talent["id"], "B-STREAM",
            "2026-08-12T11:00:00Z", "2026-08-12T13:00:00Z")
        assert b1["status"] == "TENTATIVE" and b2["status"] == "TENTATIVE"

        transition_talent_booking(b1["id"], "CONFIRM")
        resp = api_client.transition_talent_booking(
            b2["id"], {"action": "CONFIRM"}, PRODUCER)
        # the conflict check is re-applied at confirm time
        validate_error(resp, ApiErrorId.ERR_TALENT_WINDOW_CONFLICT)
        assert get_talent_booking(b2["id"])["status"] == "TENTATIVE"


class TestBookingStateMachine:

    def test_settle_tentative_booking_returns_invalid_booking_status(self):
        """PRD §3.10: "Settling moves `CONFIRMED → SETTLED` and requires the
        tournament to be in `IN_PROGRESS` or `COMPLETED`."
        PRD §2.7: "requesting a transition from a state that does not permit
        it is rejected with the machine's specific invalid-status error
        (HTTP 409)."

        Design: Corner/errors/settle_tentative_booking_returns_invalid_booking_status
        """
        ctx = setup_in_progress_2team("Book Cup")
        talent = create_talent("CasterY", "NA", 80000)
        booking = create_talent_booking(
            ctx["tournament"]["id"], talent["id"], "MAIN",
            "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z")
        resp = api_client.transition_talent_booking(
            booking["id"], {"action": "SETTLE"}, PRODUCER)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATUS)
        after = get_talent_booking(booking["id"])
        assert after["status"] == "TENTATIVE"

    def test_cross_region_booking_without_flag_returns_region_mismatch(self):
        """PRD §3.10: "The talent region rule applies: when the talent's
        `home_region` differs from the tournament's `region`, the talent's
        `cross_region` must be true, else `ERR_TALENT_REGION_MISMATCH`."

        Design: Corner/errors/cross_region_booking_without_flag_returns_region_mismatch
        """
        tournament = create_tournament("Region Cup", region="NA")
        talent_eu = create_talent("CasterEU", "EU", 80000, cross_region=False)
        talent_x = create_talent("CasterXReg", "EU", 80000, cross_region=True)

        resp = api_client.create_talent_booking(
            {"tournament_id": tournament["id"], "talent_id": talent_eu["id"],
             "stage_label": "MAIN",
             "shift_start_at": "2026-08-12T10:00:00Z",
             "shift_end_at": "2026-08-12T12:00:00Z"},
            PRODUCER)
        validate_error(resp, ApiErrorId.ERR_TALENT_REGION_MISMATCH)

        booking = create_talent_booking(
            tournament["id"], talent_x["id"], "MAIN",
            "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z")
        assert booking["status"] == "TENTATIVE"
        assert booking["fee_quote_cents"] == 80000, \
            "2 hours rounds up to 1 day unit at 80000 cents"


class TestSponsorDealWorkflow:

    def test_sponsor_deal_walk_and_activate_ownership(self):
        """PRD §3.11: "Contracting (`PROPOSED → CONTRACTED`) and voiding
        (from `PROPOSED`, `CONTRACTED`, or `ACTIVATED` to `VOID`) are
        `OrganizerAdmin` operations. Activation (`CONTRACTED → ACTIVATED`) is
        performed by the owning `SponsorManager` — the deal's
        `contact_user_id` must equal the caller's `X-User-ID`, enforced with
        `ERR_OWNERSHIP_MISMATCH` — and records `activated_at` as the logical
        clock."
        PRD §2.4: "The `version` starts at 1 at creation and increments by
        exactly 1 on every mutation, regardless of how many fields change;
        `updated_at` refreshes on every mutation."

        Design: Corner/state_machines/sponsor_deal_walk_and_activate_ownership
        """
        tournament = create_tournament("Sponsor Cup")
        deal = create_sponsor_deal(tournament["id"], "Acme Energy", "sm-1",
                                   "TITLE", 200000, ["VOD", "CLIPS"])
        assert deal["status"] == "PROPOSED" and deal["version"] == 1

        resp = api_client.transition_sponsor_deal(
            deal["id"], {"action": "ACTIVATE"},
            make_sponsor_manager_headers("sm-9"))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        assert api_client.get_sponsor_deal(
            deal["id"], TEST_USERS["sponsor_manager_headers"]).json()[
            "data"]["status"] == "PROPOSED"

        contracted = transition_sponsor_deal(deal["id"], "CONTRACT")
        assert contracted["status"] == "CONTRACTED"

        resp = api_client.transition_sponsor_deal(
            deal["id"], {"action": "ACTIVATE"},
            make_sponsor_manager_headers("sm-1"))
        activated = resp.json()["data"]
        assert activated["status"] == "ACTIVATED"
        assert_logical_clock_instant(activated["activated_at"],
                                     "2026-08-01T00:00:00Z")
        assert activated["version"] == 3, \
            "one version increment per successful transition"

    def test_activate_proposed_deal_returns_invalid_deal_status(self):
        """PRD §3.11: "Activation (`CONTRACTED → ACTIVATED`) is performed by
        the owning `SponsorManager`"
        PRD §3.11: "A new deal lands in `PROPOSED` with `activated_at` null."
        PRD §2.7: "requesting a transition from a state that does not permit
        it is rejected with the machine's specific invalid-status error
        (HTTP 409)."

        Design: Corner/errors/activate_proposed_deal_returns_invalid_deal_status
        """
        tournament = create_tournament("Deal Cup")
        deal = create_sponsor_deal(tournament["id"], "Acme", "sm-1",
                                   "SUPPORTING", 50000, ["LOGOS"])
        resp = api_client.transition_sponsor_deal(
            deal["id"], {"action": "ACTIVATE"},
            make_sponsor_manager_headers("sm-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_DEAL_STATUS)
        after = api_client.get_sponsor_deal(
            deal["id"], TEST_USERS["sponsor_manager_headers"]).json()["data"]
        assert after["status"] == "PROPOSED"
        assert after["activated_at"] is None

"""Standby waitlist: promotion ranking, the cancel->promote->mint-hold cascade,
decline-and-re-promote, and the OCC-guarded claim (PRD §3.6, §2.9, §2.10)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_candidate_headers,
    fixtures,
)


def _full_session_two_standby(api, gen_clock, fw_clock):
    """Capacity-1 session full (one CONFIRMED). A GENERAL standby joined at
    gen_clock; a FEE_WAIVER standby joined at fw_clock. Returns
    (center, session, holder, holder_reg, sb_gen, sb_fw, cand_gen, cand_fw)."""
    fixtures.set_clock(gen_clock)
    center, holder, session, reg = fixtures.create_full_session_with_one_confirmed()
    cand_gen = fixtures.make_alt_candidate("Gen", "Eral")
    cand_fw = fixtures.make_alt_candidate("Fee", "Waiver")
    sb_gen = fixtures.add_standby_entry(session["id"], cand_gen, "GENERAL")
    fixtures.set_clock(fw_clock)
    sb_fw = fixtures.add_standby_entry(session["id"], cand_fw, "FEE_WAIVER")
    return center, session, holder, reg, sb_gen, sb_fw, cand_gen, cand_fw


class TestPromotionRanking:
    def test_fee_waiver_outranks_long_waiting_general(self, api):
        """PRD §3.6: "Each entry's tier contributes a base weight: 300 for
        FEE_WAIVER, 200 for SCHOOL_DAY, and 100 for GENERAL." PRD §3.6: "To that
        the system adds a recency bonus equal to the whole number of hours the
        entry has waited since its created_at measured against the simulated
        clock, but capped at 48 — so the recency contribution is the lesser of the
        elapsed whole hours and 48, and is never negative."

        Design: Difficulty/combinatorial_formula/standby_promotion_score_weighted_nonlinear_tier_plus_capped_recency
        """
        # GENERAL joined ~100h earlier (capped recency 48 -> score 148); FEE_WAIVER
        # joins now (score 300). Cancelling the held seat must promote FEE_WAIVER.
        center, session, holder, reg, sb_gen, sb_fw, cand_gen, cand_fw = _full_session_two_standby(
            api, gen_clock="2026-06-01T00:00:00.000Z", fw_clock="2026-06-05T04:00:00.000Z",
        )
        validate_success(api.cancel_registration(reg["id"], make_candidate_headers(holder["id"])))
        fw_after = get_success_data(api.get_standby_entry(sb_fw["id"], TEST_USERS["candidate_headers"]))
        gen_after = get_success_data(api.get_standby_entry(sb_gen["id"], TEST_USERS["candidate_headers"]))
        assert fw_after["status"] == "OFFERED", "FEE_WAIVER score 300 > GENERAL score 148"
        assert gen_after["status"] == "WAITING"

    def test_promotion_score_value_fee_waiver_zero_recency(self, api):
        """PRD §3.6: "The promotion_score is the tier weight plus that capped
        recency bonus." PRD §3.6: "Each entry's tier contributes a base weight:
        300 for FEE_WAIVER, 200 for SCHOOL_DAY, and 100 for GENERAL."

        Design: Difficulty/combinatorial_formula/standby_promotion_score_weighted_nonlinear_tier_plus_capped_recency
        """
        center, session, holder, reg, sb_gen, sb_fw, cand_gen, cand_fw = _full_session_two_standby(
            api, gen_clock="2026-06-01T00:00:00.000Z", fw_clock="2026-06-05T04:00:00.000Z",
        )
        # FEE_WAIVER joined "now" relative to the clock at its creation -> 0 waited
        # hours -> promotion_score == 300 (tier weight + 0).
        fw = get_success_data(api.get_standby_entry(sb_fw["id"], TEST_USERS["candidate_headers"]))
        assert fw["promotion_score"] == 300
        validate_success(api.cancel_registration(reg["id"], make_candidate_headers(holder["id"])))
        fw_after = get_success_data(api.get_standby_entry(sb_fw["id"], TEST_USERS["candidate_headers"]))
        assert fw_after["status"] == "OFFERED"
        assert fw_after["offered_registration_id"] is not None


class TestCancelCascade:
    def test_cancel_frees_seat_promotes_standby_mints_offer_hold(self, api):
        """PRD §3.6: "Promotion moves the chosen entry from WAITING to OFFERED and
        mints an offer-hold registration for it: a new registration with lifecycle
        status RESERVED, seat_kind of STANDARD, and is_standby_origin set to true,
        whose id is recorded on the entry as offered_registration_id." PRD §3.6:
        "Minting the hold re-takes the freed seat — standard_seats_reserved is
        raised by one — and increments the session version."

        Design: Difficulty/transitive_cascade/cancel_frees_seat_promotes_standby_mints_offer_hold_depth3
        """
        fixtures.set_clock("2026-06-01T00:00:00.000Z")
        center, holder, session, reg = fixtures.create_full_session_with_one_confirmed()
        cand_alt = fixtures.make_alt_candidate("Alt", "Ernate")
        sb_alt = fixtures.add_standby_entry(session["id"], cand_alt, "GENERAL")

        validate_success(api.cancel_registration(reg["id"], make_candidate_headers(holder["id"])))

        sb_after = get_success_data(api.get_standby_entry(sb_alt["id"], TEST_USERS["candidate_headers"]))
        assert sb_after["status"] == "OFFERED"
        assert sb_after["offered_registration_id"] is not None, "offer-hold minted"
        hold = get_success_data(
            api.get_registration(sb_after["offered_registration_id"], TEST_USERS["candidate_headers"])
        )
        assert hold["is_standby_origin"] is True
        assert hold["lifecycle_status"] == "RESERVED"
        sess_after = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        assert sess_after["standard_seats_reserved"] == 1, "freed seat re-taken by the hold"

    def test_cancel_cascade_promotes_then_holds_seat_chain(self, api):
        """PRD §3.7: "if the freed seat was a standard seat and a waiting alternate
        exists, the standby promotion cascade of §3.6 runs, which itself mints an
        offer-hold registration and bumps the version again — a settlement that can
        run three levels deep within the single cancel request." PRD §3.6: "Minting
        the hold re-takes the freed seat — standard_seats_reserved is raised by one
        — and increments the session version."

        Design: Difficulty/transitive_cascade/cancel_frees_seat_promotes_standby_mints_offer_hold_depth3
        """
        fixtures.set_clock("2026-06-01T00:00:00.000Z")
        center, holder, session, reg = fixtures.create_full_session_with_one_confirmed()
        cand_alt = fixtures.make_alt_candidate("Alt", "Ernate")
        sb_alt = fixtures.add_standby_entry(session["id"], cand_alt, "GENERAL")
        # The single cancel request must, in one settlement, free the seat (B),
        # promote the entry to OFFERED (C), and mint the linked offer-hold (D).
        validate_success(api.cancel_registration(reg["id"], make_candidate_headers(holder["id"])))
        # The cancelled original registration is terminal; the standby entry now
        # holds the re-taken seat through its freshly minted offer-hold.
        orig = get_success_data(api.get_registration(reg["id"], TEST_USERS["candidate_headers"]))
        assert orig["lifecycle_status"] == "CANCELLED"
        sb_after = get_success_data(api.get_standby_entry(sb_alt["id"], TEST_USERS["candidate_headers"]))
        assert sb_after["status"] == "OFFERED"
        hold = get_success_data(
            api.get_registration(sb_after["offered_registration_id"], TEST_USERS["candidate_headers"])
        )
        assert hold["is_standby_origin"] is True
        assert hold["candidate_id"] == cand_alt["id"], "hold minted for the promoted alternate"

    def test_cancel_cascade_settles_immediately(self, api):
        """PRD §2.10: "Several operations mutate more than one resource, and all
        such cascades settle inside the triggering request — there is no deferred
        reconciliation."

        Design: Corner/consistency_model/cancel_cascade_settles_in_same_request_immediate
        """
        fixtures.set_clock("2026-06-01T00:00:00.000Z")
        center, holder, session, reg = fixtures.create_full_session_with_one_confirmed()
        cand_alt = fixtures.make_alt_candidate("Alt", "Ernate")
        sb_alt = fixtures.add_standby_entry(session["id"], cand_alt, "GENERAL")
        validate_success(api.cancel_registration(reg["id"], make_candidate_headers(holder["id"])))
        # Immediately observable, no deferred reconciliation.
        sb_after = get_success_data(api.get_standby_entry(sb_alt["id"], TEST_USERS["candidate_headers"]))
        assert sb_after["status"] == "OFFERED"


class TestDeclineRePromote:
    def test_decline_promotes_next_alternate_and_chains(self, api):
        """PRD §3.6: "Declining then re-runs promotion for the next-best waiting
        alternate; when that next alternate is promoted, its promoted_from_entry_id
        is set to the declining entry's id, recording the chain of re-queued
        offers for audit."

        Design: Corner/state_machines/standby_decline_then_promote_next_alternate_cascade
        """
        fixtures.set_clock("2026-06-01T00:00:00.000Z")
        center, holder, session, reg = fixtures.create_full_session_with_one_confirmed()
        cand_a1 = fixtures.make_alt_candidate("Alt", "First")
        sb1 = fixtures.add_standby_entry(session["id"], cand_a1, "GENERAL")
        fixtures.set_clock("2026-06-01T01:00:00.000Z")
        cand_a2 = fixtures.make_alt_candidate("Alt", "Second")
        sb2 = fixtures.add_standby_entry(session["id"], cand_a2, "GENERAL")
        # Cancel offers sb1 (older, tie-break by created_at ASC).
        validate_success(api.cancel_registration(reg["id"], make_candidate_headers(holder["id"])))
        sb1_offered = get_success_data(api.get_standby_entry(sb1["id"], TEST_USERS["candidate_headers"]))
        assert sb1_offered["status"] == "OFFERED"
        # Decline sb1 -> promote sb2 with promoted_from_entry_id == sb1.
        validate_success(api.decline_standby_entry(sb1["id"], make_candidate_headers(cand_a1["id"])))
        sb1_after = get_success_data(api.get_standby_entry(sb1["id"], TEST_USERS["candidate_headers"]))
        sb2_after = get_success_data(api.get_standby_entry(sb2["id"], TEST_USERS["candidate_headers"]))
        assert sb1_after["status"] == "DECLINED"
        assert sb2_after["status"] == "OFFERED"
        assert sb2_after["promoted_from_entry_id"] == sb1["id"]
        sess_after = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        assert sess_after["standard_seats_reserved"] == 1, "next hold re-takes the seat"


class TestStandbyClaimOCC:
    def _promotion_setup(self, api):
        """Capacity-1 session: holder CONFIRMED, one GENERAL standby, holder
        cancels -> standby OFFERED, version advanced. Returns (session, sb_alt,
        cand_alt, version_after_promotion)."""
        fixtures.set_clock("2026-06-01T00:00:00.000Z")
        center, holder, session, reg = fixtures.create_full_session_with_one_confirmed()
        cand_alt = fixtures.make_alt_candidate("Alt", "Ernate")
        sb_alt = fixtures.add_standby_entry(session["id"], cand_alt, "GENERAL")
        cancel_resp = validate_success(api.cancel_registration(reg["id"], make_candidate_headers(holder["id"])))
        version_after = cancel_resp["version"]
        return session, sb_alt, cand_alt, version_after

    def test_standby_claim_correct_version_succeeds(self, api):
        """PRD §3.6: "A successful claim moves the entry from OFFERED to CLAIMED,
        advances the offer-hold registration from RESERVED to CONFIRMED, captures
        the fee by setting that registration's amount_paid_cents to the session's
        base_fee_cents, adds that base_fee_cents to the center's net_revenue_cents,
        and increments the session version once more — which settles the
        concurrency token so that a second, stale claim against the same offer
        fails."

        Design: Corner/cross_cutting_complexity_layers/occ_standby_claim_correct_version_succeeds
        """
        session, sb_alt, cand_alt, version_after = self._promotion_setup(api)
        sb_offered = get_success_data(api.get_standby_entry(sb_alt["id"], TEST_USERS["candidate_headers"]))
        offer_reg_id = sb_offered["offered_registration_id"]
        # Need the live session version (the cancel response carried it).
        sess_now = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        resp = api.claim_standby_entry(
            sb_alt["id"], {"expected_test_session_version": sess_now["version"]},
            make_candidate_headers(cand_alt["id"]),
        )
        claimed = validate_success(resp)
        assert claimed["status"] == "CLAIMED"
        hold = get_success_data(api.get_registration(offer_reg_id, TEST_USERS["candidate_headers"]))
        assert hold["lifecycle_status"] == "CONFIRMED"
        assert hold["amount_paid_cents"] == 6000

    def test_standby_claim_stale_version_rejected(self, api):
        """PRD §2.9: "A standby claim must also carry expected_test_session_version
        matching the session's current version. If a cancel-or-promotion cascade
        has re-allocated the freed seat and advanced the version since the
        candidate received their offer, the claim is rejected with
        ERR_STALE_SESSION_VERSION (HTTP 412), because the seat the claimant
        expected to take may already have been legitimately reallocated."

        Design: Corner/cross_cutting_complexity_layers/occ_standby_claim_stale_session_rejected
        """
        session, sb_alt, cand_alt, version_after = self._promotion_setup(api)
        sess_now = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        stale_version = sess_now["version"] - 1
        resp = api.claim_standby_entry(
            sb_alt["id"], {"expected_test_session_version": stale_version},
            make_candidate_headers(cand_alt["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SESSION_VERSION.value)

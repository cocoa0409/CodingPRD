"""Content strikes, the two-round appeal cycle, and posture/trust scoring."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    appeal_strike,
    assert_instant_equals,
    assert_strike,
    create_channel,
    create_verified_channel,
    get_channel,
    get_success_data,
    issue_strike,
    make_appeals_officer_headers,
    make_creator_headers,
    make_trust_agent_headers,
    resolve_strike,
    run_ops,
    set_clock,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestTrustScore:
    def test_trust_score_constant_penalty(self, api):
        """PRD §2.7: "The companion `active_strike_count` counts the channel's
        strikes currently in `ISSUED`, `UNDER_APPEAL`, or `UPHELD` status, and
        `trust_score_bp` is ten thousand minus 2,500 basis points per unit of
        active strike weight, floored at zero."

        Design: Corner/calculations/trust_score_constant_penalty
        """
        channel = create_channel(handle="calc_tr", home_platform="TWITCH")
        set_clock("2026-08-01T00:00:00Z")
        issue_strike(channel["id"], policy_code="SPAM", severity="MAJOR",
                     evidence_ref="clip://30")

        channel_after = get_channel(channel["id"])
        assert channel_after["trust_score_bp"] == 5000, (
            "10000 - 2500 * 2 for one MAJOR strike")
        assert channel_after["active_strike_count"] == 1
        assert channel_after["monetization_posture"] == "RESTRICTED"


class TestStrikeWeightSuspensionBoundary:
    def test_weight_two_stays_restricted(self, api):
        """PRD §2.7: "`SUSPENDED` applies whenever the active strike weight
        reaches three or more — the comparison is inclusive. Everything else
        is `RESTRICTED`, which is also the posture every channel is born
        with, since no channel has a verified tax form at onboarding."
        PRD §2.7: "The companion `active_strike_count` counts the channel's
        strikes currently in `ISSUED`, `UNDER_APPEAL`, or `UPHELD` status, and
        `trust_score_bp` is ten thousand minus 2,500 basis points per unit of
        active strike weight, floored at zero."

        Design: Difficulty/boundary_precision_check/strike_weight_suspension_boundary
        """
        channel, _form = create_verified_channel("bp_strike")
        set_clock("2026-08-01T00:00:00Z")
        issue_strike(channel["id"], policy_code="SPAM", severity="MAJOR",
                     evidence_ref="clip://20")

        channel_after = get_channel(channel["id"])
        assert channel_after["monetization_posture"] == "RESTRICTED", (
            "weight 2 is below the inclusive suspension boundary")
        assert channel_after["trust_score_bp"] == 5000
        assert channel_after["active_strike_count"] == 1

    def test_weight_exactly_three_suspends(self, api):
        """PRD §2.7: "`SUSPENDED` applies whenever the active strike weight
        reaches three or more — the comparison is inclusive."
        PRD §2.7: "A single `SEVERE` strike therefore suspends a channel by
        itself, as does one `MINOR` plus one `MAJOR`."

        Design: Difficulty/boundary_precision_check/strike_weight_suspension_boundary
        """
        channel, _form = create_verified_channel("bp_strike2")
        set_clock("2026-08-01T00:00:00Z")
        issue_strike(channel["id"], policy_code="SPAM", severity="MAJOR",
                     evidence_ref="clip://20")
        issue_strike(channel["id"], policy_code="COPYRIGHT", severity="MINOR",
                     evidence_ref="clip://21")

        channel_after = get_channel(channel["id"])
        assert channel_after["monetization_posture"] == "SUSPENDED", (
            "weight exactly 3 crosses the inclusive boundary")
        assert channel_after["trust_score_bp"] == 2500, "10000 - 2500 * 3"
        assert channel_after["active_strike_count"] == 2


class TestStrikeHardWindowVsProjectedDecay:
    def _expired_minor_strike_channel(self, handle):
        """STANDARD channel whose MINOR strike (issued at 2026-08-01, expiring
        at the 90-day hard boundary) has been swept by an ops run at
        2026-10-31 — strike age 91 days."""
        channel, _form = create_verified_channel(handle)
        set_clock("2026-08-01T00:00:00Z")
        strike = issue_strike(channel["id"], policy_code="COPYRIGHT",
                              severity="MINOR", evidence_ref="vod://1")
        set_clock("2026-10-31T00:00:00Z")
        run_ops()
        return channel, strike

    def test_hard_window_expiry_restores_standard(self, api):
        """PRD §3.6: "An ops run expires any strike in `ISSUED` or `UPHELD`
        whose `expires_at` has been reached or passed, moving it to the
        terminal `EXPIRED`, removing its weight, and recomputing posture."
        PRD §2.7: "`STANDARD` requires the channel's active strike weight to
        be exactly zero **and** the channel's current tax form to be
        `VERIFIED`."

        Design: Difficulty/dual_variant_calc/strike_weight_hard_window_vs_projected_decay
        """
        channel, strike = self._expired_minor_strike_channel("dv_strike")

        strikes = get_success_data(api.list_strikes(
            channel["id"], make_trust_agent_headers()))
        current = [s for s in strikes if s["id"] == strike["id"]][0]
        assert current["strike_status"] == "EXPIRED", (
            "the hard window closed at the 90-day boundary")

        channel_after = get_channel(channel["id"])
        assert channel_after["monetization_posture"] == "STANDARD", (
            "canonical hard-window weight is exactly zero")
        assert channel_after["active_strike_count"] == 0

    def test_projected_decay_nonzero_where_canonical_is_zero(self, api):
        """PRD §3.6: "`projected_strike_weight` is an analytics-only
        projection: over the channel's strikes in `ISSUED`, `UNDER_APPEAL`,
        `UPHELD`, or `EXPIRED` status within the last 180 days, each strike
        contributes its severity weight multiplied by a continuous decay
        factor — one-half raised to the power of the strike's age in days
        divided by thirty, so a strike loses half its contribution every
        thirty days — and the contributions are summed and rounded half up to
        four decimal places."
        PRD §3.6: "The projection therefore declines smoothly instead of
        falling off the ninety-day cliff, and it **never** gates posture; the
        canonical hard-window weight of §2.7 is the only weight that does."

        Design: Difficulty/dual_variant_calc/strike_weight_hard_window_vs_projected_decay
        """
        channel, _strike = self._expired_minor_strike_channel("dv_strike2")

        channel_after = get_channel(channel["id"])
        assert channel_after["active_strike_count"] == 0, (
            "canonical weight is zero at day 91")
        # 1 * 2^(-91/30) rounded half-up to 4 decimal places.
        assert channel_after["projected_strike_weight"] == pytest.approx(
            0.1221, abs=1e-9), (
            "the decay variant is still nonzero where the canonical variant "
            "is already zero")


class TestStrikeAppeals:
    def test_strike_appeal_window_closed(self, api):
        """PRD §3.6: "The strike is born `ISSUED`; `issued_at` is stamped from
        the clock; `expires_at` is set ninety days out, the hard-window decay
        boundary of §2.7; `appeal_deadline` is set fourteen days out;
        `appeal_round` starts at 0; and the issuer's `X-User-ID` is recorded
        as `issued_by_user_id` for the segregation-of-duties check below."
        PRD §3.6: "Two gates guard the move, checked in the §2.9 order: the
        clock must not have passed the strike's `appeal_deadline`
        (`ERR_APPEAL_WINDOW_CLOSED`), and `appeal_round` must still be below
        the cap of 2 (`ERR_APPEAL_LIMIT_REACHED`)."

        Design: Corner/validations/strike_appeal_window_closed
        """
        channel = create_channel(handle="val_appw", home_platform="YOUTUBE")
        set_clock("2026-08-01T00:00:00Z")
        strike = issue_strike(channel["id"], policy_code="COPYRIGHT",
                              severity="MINOR", evidence_ref="clip://40")
        assert_instant_equals(strike["appeal_deadline"], "2026-08-15T00:00:00Z",
                              label="appeal_deadline = issued_at + 14 days")
        set_clock("2026-08-15T00:00:01Z")

        resp = api.appeal_strike(strike["id"], {"statement": "late"},
                                 make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

        strikes = get_success_data(api.list_strikes(channel["id"], ADMIN))
        current = [s for s in strikes if s["id"] == strike["id"]][0]
        assert current["strike_status"] == "ISSUED"
        assert current["appeal_round"] == 0

    def test_strike_appeal_limit_reached(self, api):
        """PRD §3.6: "Two gates guard the move, checked in the §2.9 order: the
        clock must not have passed the strike's `appeal_deadline`
        (`ERR_APPEAL_WINDOW_CLOSED`), and `appeal_round` must still be below
        the cap of 2 (`ERR_APPEAL_LIMIT_REACHED`)."
        PRD §2.9: "**Appeal rounds.** An appeal filed when `appeal_round` has
        already reached the cap of 2 is rejected with
        `ERR_APPEAL_LIMIT_REACHED`. The window check outranks the round check,
        so an appeal that violates both reports the closed window."

        Design: Corner/validations/strike_appeal_limit_reached
        """
        channel = create_channel(handle="val_appl", home_platform="TWITCH")
        set_clock("2026-08-01T00:00:00Z")
        strike = issue_strike(channel["id"], policy_code="HATE_SPEECH",
                              severity="MAJOR", evidence_ref="clip://41")
        appeal_strike(strike["id"], channel["id"], statement="a1")
        set_clock("2026-08-03T00:00:00Z")
        resolve_strike(strike["id"], outcome="UPHELD", resolution_note="n1")
        set_clock("2026-08-04T00:00:00Z")
        appeal_strike(strike["id"], channel["id"], statement="a2")
        set_clock("2026-08-05T00:00:00Z")
        resolved = resolve_strike(strike["id"], outcome="UPHELD",
                                  resolution_note="n2")
        assert resolved["appeal_round"] == 2
        set_clock("2026-08-06T00:00:00Z")

        resp = api.appeal_strike(strike["id"], {"statement": "a3"},
                                 make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)

        strikes = get_success_data(api.list_strikes(channel["id"], ADMIN))
        current = [s for s in strikes if s["id"] == strike["id"]][0]
        assert current["strike_status"] == "UPHELD"
        assert current["appeal_round"] == 2

    def _upheld_severe_strike(self, handle):
        """STANDARD channel; SEVERE strike; appeal 1 upheld at 2026-08-05."""
        channel, _form = create_verified_channel(handle)
        set_clock("2026-08-01T00:00:00Z")
        strike = issue_strike(channel["id"], policy_code="NUDITY",
                              severity="SEVERE", evidence_ref="clip://9")
        appeal_strike(strike["id"], channel["id"], statement="appeal one")
        set_clock("2026-08-05T00:00:00Z")
        resolve_strike(strike["id"], outcome="UPHELD", resolution_note="stands")
        return channel, strike

    def test_strike_appeal_second_round_reopens_under_appeal(self, api):
        """PRD §3.6: "From `ISSUED`, and again from `UPHELD`, the owner may
        appeal with a `statement` making their case."
        PRD §3.6: "A valid appeal moves the strike to `UNDER_APPEAL` and
        increments `appeal_round` by 1; the strike's weight still counts
        while the appeal is pending, so posture is recomputed but rarely
        changes on this arc."

        Design: Difficulty/non_linear_state_machine/strike_appeal_two_round_cycle
        """
        channel, strike = self._upheld_severe_strike("nl_strike")

        second = appeal_strike(strike["id"], channel["id"],
                               statement="appeal two")
        assert_strike(second)
        assert second["strike_status"] == "UNDER_APPEAL", (
            "the UPHELD -> UNDER_APPEAL cycle edge is traversed")
        assert second["appeal_round"] == 2, "the second and final round"

    def test_strike_appeal_cycle_keeps_posture_suspended(self, api):
        """PRD §3.6: "A valid appeal moves the strike to `UNDER_APPEAL` and
        increments `appeal_round` by 1; the strike's weight still counts
        while the appeal is pending, so posture is recomputed but rarely
        changes on this arc."
        PRD §3.6: "Upholding stamps `upheld_at`, recomputes `appeal_deadline`
        as fourteen days after `upheld_at` — opening the second and final
        appeal window — and recomputes posture."

        Design: Difficulty/non_linear_state_machine/strike_appeal_two_round_cycle
        """
        channel, strike = self._upheld_severe_strike("nl_strike2")

        after_uphold = [s for s in get_success_data(api.list_strikes(
            channel["id"], ADMIN)) if s["id"] == strike["id"]][0]
        assert after_uphold["strike_status"] == "UPHELD"
        assert_instant_equals(after_uphold["appeal_deadline"],
                              "2026-08-19T00:00:00Z",
                              label="appeal_deadline = upheld_at + 14 days")
        assert get_channel(channel["id"])["monetization_posture"] == "SUSPENDED"

        appeal_strike(strike["id"], channel["id"], statement="appeal two")
        assert get_channel(channel["id"])["monetization_posture"] == "SUSPENDED", (
            "weight 3 still counts while the second appeal is pending")


class TestSegregationOfDuties:
    def test_appeals_officer_self_review_forbidden(self, api):
        """PRD §3.6: "Resolution belongs to an `AppealsOfficer`, never to the
        issuer: the resolver's `X-User-ID` must differ from the strike's
        `issued_by_user_id`, and a self-review is rejected with
        `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/appeals_officer_self_review_forbidden
        """
        channel = create_channel(handle="rb_sod", home_platform="YOUTUBE")
        set_clock("2026-08-01T00:00:00Z")
        strike = issue_strike(channel["id"], policy_code="COPYRIGHT",
                              severity="MINOR", evidence_ref="clip://50",
                              issuer_user_id="trust_nina")
        appeal_strike(strike["id"], channel["id"], statement="appeal")

        self_review = api.resolve_strike_appeal(
            strike["id"],
            {"outcome": "REVERSED", "resolution_note": "self review"},
            make_appeals_officer_headers("trust_nina"))
        validate_error(self_review, ApiErrorId.ERR_SELF_REVIEW_FORBIDDEN)

        strikes = get_success_data(api.list_strikes(channel["id"], ADMIN))
        assert [s for s in strikes
                if s["id"] == strike["id"]][0]["strike_status"] == "UNDER_APPEAL"

        resolved = resolve_strike(strike["id"], outcome="REVERSED",
                                  resolution_note="independent")
        assert resolved["strike_status"] == "REVERSED"


class TestStrikeListEnvelope:
    def test_list_endpoint_pagination_envelope(self, api):
        """PRD §2.3: "`limit` defaults to 10, must be at least 1, and may not
        exceed 100. `offset` defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`, so a caller
        can always tell how many records exist in total and whether further
        pages remain."
        PRD §2.7: "`SUSPENDED` applies whenever the active strike weight
        reaches three or more — the comparison is inclusive."

        Design: Corner/endpoints/list_endpoint_pagination_envelope
        """
        channel = create_channel(handle="ep_page", home_platform="TWITCH")
        set_clock("2026-08-01T00:00:00Z")
        for ref in ("e1", "e2", "e3"):
            issue_strike(channel["id"], policy_code="SPAM", severity="MINOR",
                         evidence_ref=ref)

        resp = api.list_strikes(channel["id"], make_trust_agent_headers())
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(meta["api_request_id"], str)
        assert isinstance(meta["api_request_timestamp"], str)
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "declared default page size"
        assert meta["offset"] == 0
        assert len(data) == 3

        assert get_channel(channel["id"])["monetization_posture"] == "SUSPENDED", (
            "three MINOR strikes accumulate weight 3 — visible in the same "
            "read set")

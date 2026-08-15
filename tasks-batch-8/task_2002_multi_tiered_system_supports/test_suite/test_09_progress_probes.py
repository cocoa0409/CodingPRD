"""Progress probes: aimline projection, the slope decision rule, and cadence
enforcement (PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_progress_probe,
    make_interventionist_role_headers,
    record_biweekly_probes,
    record_probe_payload,
    record_weekly_probes,
    set_clock,
    setup_active_plan,
    validate_error,
)

LEAD = TEST_USERS["team_lead_headers"]


class TestSlopeDecisionRule:
    def test_slope_rule_responsive_when_trajectory_rises_below_aimline(self, api):
        """PRD §3.6: "Under the default slope rule, a least-squares regression
        slope is fitted over the window's probe scores, using each probe's
        position in the window — zero for the oldest, counting up to k minus one
        for the newest — as the x-coordinate, and a second least-squares slope is
        fitted over the same window's `aimline_score` values. The decision is
        `RESPONSIVE` when the score slope is greater than or equal to the aimline
        slope, and `NON_RESPONSIVE` otherwise; the comparison is an exact
        rational comparison with no rounding."
        PRD §3.6: "The slope variant is what the API persists."
        PRD §3.6: "The expected value at the k-th probe — the first probe is k
        equal to 1 — is the baseline plus the gap between goal and baseline,
        scaled by k divided by the total probe count, rounded half-up to a whole
        number."

        Baseline 100, goal 130, WEEKLY (total 8): aimlines are 104, 108, 111,
        115. Scores 102, 105, 109, 113 rise with regression slope 3.7 against the
        aimline slope 3.6, so probe 4 is RESPONSIVE even though its score (113)
        sits below its aimline (115) — the divergence the persisted slope variant
        pins.

        Design: Difficulty/dual_variant_calc/slope_decision_slope_vs_endpoint
        """
        ctx = setup_active_plan(api, tier="TIER_2", raw_score=100,
                                tier2_max_score=130, tier3_max_score=90,
                                probe_frequency="WEEKLY")
        probes = record_weekly_probes(api, ctx, [102, 105, 109, 113],
                                      first_date="2026-08-12")
        assert [p["aimline_score"] for p in probes] == [104, 108, 111, 115], (
            "aimline: baseline 100, goal 130, k/8 scaling, rounded half-up")
        probe4 = probes[-1]
        assert_progress_probe(probe4)
        assert probe4["slope_decision"] == "RESPONSIVE", (
            "score slope 3.7 >= aimline slope 3.6 over the trailing four probes")

    def test_slope_rule_non_responsive_on_flat_scores(self, api):
        """PRD §3.6: "The decision is `RESPONSIVE` when the score slope is
        greater than or equal to the aimline slope, and `NON_RESPONSIVE`
        otherwise; the comparison is an exact rational comparison with no
        rounding."
        PRD §3.6: "The slope variant is what the API persists."

        Baseline 95, goal 120, WEEKLY: aimlines climb 98, 101, 104, 108 while the
        scores stay flat at 95, 95, 96, 96, so every multi-probe trailing window
        has a score slope below the aimline slope.

        Design: Difficulty/dual_variant_calc/slope_decision_slope_vs_endpoint
        """
        ctx = setup_active_plan(api, tier="TIER_2", raw_score=95,
                                tier2_max_score=120, tier3_max_score=90,
                                probe_frequency="WEEKLY")
        probes = record_weekly_probes(api, ctx, [95, 95, 96, 96],
                                      first_date="2026-08-12")
        assert [p["aimline_score"] for p in probes] == [98, 101, 104, 108]
        for probe in probes[1:]:
            assert probe["slope_decision"] == "NON_RESPONSIVE", (
                "flat scores against a rising aimline are non-responsive")


class TestAimlineAndCadence:
    def test_aimline_first_probe_biweekly_frequency(self, api):
        """PRD §3.6: "The expected value at the k-th probe — the first probe is k
        equal to 1 — is the baseline plus the gap between goal and baseline,
        scaled by k divided by the total probe count, rounded half-up to a whole
        number. The total probe count is eight for a `WEEKLY` probe frequency and
        four for `BIWEEKLY`."

        Baseline 100, goal 120, BIWEEKLY (total 4): k=1 gives
        100 + 20 x 1/4 = 105.

        Design: Corner/calculations/aimline_score_k1_biweekly
        """
        ctx = setup_active_plan(api, tier="TIER_2", raw_score=100,
                                tier2_max_score=120, tier3_max_score=90,
                                probe_frequency="BIWEEKLY")
        # Plan activated at 2026-08-05, so the first BIWEEKLY probe is due 08-19.
        assert ctx["plan"]["probe_due_on"] == "2026-08-19"
        probes = record_biweekly_probes(api, ctx, [105], first_date="2026-08-19")
        assert probes[0]["aimline_score"] == 105, (
            "BIWEEKLY total probe count is 4, not 8")

    def test_probe_before_due_date_rejected(self, api):
        """PRD §3.6: "Cadence is enforced: a probe may only be recorded while the
        plan is `ACTIVE` and when the current date is on or after the plan's
        `probe_due_on`; an early probe is rejected with `ERR_PROBE_NOT_DUE`
        (HTTP 422)."

        The WEEKLY plan activated at 2026-08-05 is not due until 2026-08-12; the
        clock is still at 2026-08-06.

        Design: Corner/validations/probe_before_due_date_rejected
        """
        ctx = setup_active_plan(api, tier="TIER_2", probe_frequency="WEEKLY")
        assert ctx["plan"]["probe_due_on"] == "2026-08-12"
        set_clock(api, "2026-08-06T00:00:00Z")
        resp = api.record_probe(
            ctx["district"]["id"], ctx["school"]["id"], ctx["student"]["id"],
            ctx["plan"]["id"], record_probe_payload("2026-08-06", 85),
            # Probes are recorded by the delivering interventionist (ownership).
            make_interventionist_role_headers(ctx["interventionist"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PROBE_NOT_DUE, 422)

"""Two-variant measures: the two abandonment rates and the two complaint risk scores.

Each variant pair is computed from one body of evidence, and the pair only becomes
observable when the two variants disagree — a machine answer for the abandonment
measures, an adjudication for the risk scores.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    AllegedViolationType,
    AttemptOutcome,
    CampaignStatus,
    ComplaintSource,
    ComplaintStatus,
    ComplianceWorld,
    DialerLockedReason,
    DialerProfileStatus,
    InternalDncStatus,
    RiskTier,
    SuspensionReason,
    assert_decimal_equals,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_status,
)

# Three instants on 2026-08-03, spaced so that each attempt clears the closed
# thirty-minute contact cooldown left behind by the previous one.
FIRST_ATTEMPT_AT = "2026-08-03T00:00:00Z"
SECOND_ATTEMPT_AT = "2026-08-03T00:31:00Z"
THIRD_ATTEMPT_AT = "2026-08-03T01:02:00Z"


def _place_and_record(
    world: ComplianceWorld,
    built: Dict[str, Any],
    at_instant: str,
    **outcome: Any,
) -> Dict[str, Any]:
    """Move the clock, place one attempt on the running campaign, record its outcome."""
    world.set_clock(at_instant)
    attempt = world.create_attempt(built["campaign"]["id"], built["contact"]["id"])
    return world.record_outcome(attempt["id"], **outcome)


def _campaign_with_three_recorded_attempts(
    world: ComplianceWorld, **build_overrides: Any
) -> Dict[str, Any]:
    """A running campaign whose consumer has three non-voided, dispositioned attempts."""
    built = world.build(attempt_budget_total=3, **build_overrides)
    _place_and_record(
        world,
        built,
        FIRST_ATTEMPT_AT,
        outcome=AttemptOutcome.CONNECTED_LIVE,
        agent_connect_seconds=2,
    )
    _place_and_record(world, built, SECOND_ATTEMPT_AT, outcome=AttemptOutcome.NO_ANSWER)
    _place_and_record(
        world,
        built,
        THIRD_ATTEMPT_AT,
        outcome=AttemptOutcome.CONNECTED_LIVE,
        agent_connect_seconds=1,
    )
    return built


class TestAbandonmentMeasureVariants:
    """The regulatory and internal abandonment rates over one measurement day."""

    def test_01_machine_answer_moves_only_the_internal_abandonment_measure(self, world):
        """A machine answer widens the internal denominator and leaves the regulatory rate put.

        PRD §3.8:
        "`live_answer_count_today` is deliberately untouched, which is why a machine
        answer leaves `regulatory_abandonment_rate_pct` exactly where it was while
        moving `internal_abandonment_rate_pct`."
        PRD §3.8:
        "`internal_abandonment_rate_pct` is `0.00` when `live_answer_count_today` plus
        `machine_count_today` is zero, and otherwise 100 multiplied by
        `abandoned_count_today`, divided by the sum of `live_answer_count_today` and
        `machine_count_today`, rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/abandonment_rate_regulatory_vs_internal_divergence
        """
        built = world.build(attempt_budget_total=3, abandonment_limit_pct=50.0)
        _place_and_record(
            world,
            built,
            FIRST_ATTEMPT_AT,
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )
        _place_and_record(
            world,
            built,
            SECOND_ATTEMPT_AT,
            outcome=AttemptOutcome.ABANDONED,
            abandon_message_played=True,
        )
        machine = _place_and_record(
            world, built, THIRD_ATTEMPT_AT, outcome=AttemptOutcome.MACHINE_ANSWERED
        )

        assert_status(machine, AttemptOutcome.MACHINE_ANSWERED, field="outcome")

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(
            campaign,
            live_answer_count_today=2,
            abandoned_count_today=1,
            machine_count_today=1,
        )
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 50.00)
        assert_decimal_equals(campaign["internal_abandonment_rate_pct"], 33.33)
        assert_decimal_equals(
            campaign["regulatory_abandonment_rate_pct"]
            - campaign["internal_abandonment_rate_pct"],
            16.67,
        )

    def test_02_both_measures_agree_while_no_machine_answer_exists(self, world):
        """With no machine answer the two denominators coincide, and 50.00 does not breach 50.00.

        PRD §3.8:
        "`regulatory_abandonment_rate_pct` is `0.00` when `live_answer_count_today` is
        zero, and otherwise 100 multiplied by `abandoned_count_today`, divided by
        `live_answer_count_today`, rounded half up to two decimal places — a denominator
        of live answers only, meaning connected-live and abandoned dispositions, with
        machine answers excluded entirely."
        PRD §3.8:
        "The comparison is strict, so a rate exactly equal to the configured limit does
        not breach."

        Design: Difficulty/dual_variant_calc/abandonment_rate_regulatory_vs_internal_divergence
        """
        built = world.build(attempt_budget_total=3, abandonment_limit_pct=50.0)
        _place_and_record(
            world,
            built,
            FIRST_ATTEMPT_AT,
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )
        _place_and_record(
            world,
            built,
            SECOND_ATTEMPT_AT,
            outcome=AttemptOutcome.ABANDONED,
            abandon_message_played=True,
        )

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(
            campaign,
            live_answer_count_today=2,
            abandoned_count_today=1,
            machine_count_today=0,
        )
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 50.00)
        assert_decimal_equals(campaign["internal_abandonment_rate_pct"], 50.00)
        assert_status(campaign, CampaignStatus.ACTIVE)
        assert_fields_null(campaign, "suspension_reason")

        profile = assert_ok(
            world.api.get_dialer_profile(built["profile"]["id"], world.operator)
        )
        assert_status(profile, DialerProfileStatus.APPROVED)

    def test_03_only_the_regulatory_measure_can_suspend_the_campaign(self, world):
        """A 50.00 regulatory rate breaches a 40.00 ceiling although the internal rate is 33.33.

        PRD §3.8:
        "This is the regulatory measure, and it is the only one ever compared against the
        profile's `abandonment_limit_pct`, therefore the only one that can suspend a
        campaign."
        PRD §3.8:
        "The campaign moves `ACTIVE → SUSPENDED` with `suspension_reason`
        `ABANDONMENT_BREACH`, voiding its `PENDING` attempts with `void_reason`
        `CAMPAIGN_SUSPENDED` and crediting those consumers' attempt budgets, and its
        `version` increments."

        Design: Difficulty/dual_variant_calc/abandonment_rate_regulatory_vs_internal_divergence
        """
        built = world.build(attempt_budget_total=3, abandonment_limit_pct=40.0)
        _place_and_record(
            world,
            built,
            FIRST_ATTEMPT_AT,
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )
        _place_and_record(
            world, built, SECOND_ATTEMPT_AT, outcome=AttemptOutcome.MACHINE_ANSWERED
        )
        _place_and_record(
            world,
            built,
            THIRD_ATTEMPT_AT,
            outcome=AttemptOutcome.ABANDONED,
            abandon_message_played=True,
        )

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 50.00)
        assert_decimal_equals(campaign["internal_abandonment_rate_pct"], 33.33)
        assert_status(campaign, CampaignStatus.SUSPENDED)
        assert_fields_equal(
            campaign, suspension_reason=SuspensionReason.ABANDONMENT_BREACH
        )

        profile = assert_ok(
            world.api.get_dialer_profile(built["profile"]["id"], world.operator)
        )
        assert_status(profile, DialerProfileStatus.LOCKED)
        assert_fields_equal(
            profile, locked_reason=DialerLockedReason.ABANDONMENT_BREACH
        )


class TestComplaintRiskScoreVariants:
    """The provisional score written at intake and the adjudicated score written at finding."""

    def test_04_provisional_score_caps_the_attempt_contribution_at_intake(self, world):
        """Intake scores 15 source points plus 10 violation points plus 2 points per charged attempt.

        PRD §3.9:
        "The provisional variant runs at intake, when nothing has been investigated yet,
        and lands in `provisional_risk_score`."
        PRD §3.9:
        "To those two weighted terms it adds an attempt contribution: the lesser of the
        consumer's `attempts_charged` and a cap of 5 attempts, multiplied by 2
        provisional points per attempt."

        Design: Difficulty/dual_variant_calc/complaint_risk_provisional_vs_adjudicated_divergence
        """
        built = _campaign_with_three_recorded_attempts(world)
        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(contact, attempts_charged=3)

        complaint = world.create_complaint(
            built["contact"]["id"],
            built["campaign"]["id"],
            source=ComplaintSource.FTC,
            alleged_violation_type=AllegedViolationType.DNC_VIOLATION,
            litigation_flag=False,
        )

        assert_decimal_equals(complaint["provisional_risk_score"], 31.00)
        assert_status(complaint, ComplaintStatus.OPEN)
        assert_fields_null(
            complaint,
            "adjudicated_risk_score",
            "verified_attempt_count",
            "exposure_cents",
            "willful",
            "finding_note",
            "dismissal_note",
        )
        assert_fields_equal(complaint, pattern_cluster_size=1)

    def test_05_adjudication_reprices_the_same_evidence_and_retiers_the_consumer(
        self, world
    ):
        """The same three attempts score 31.00 provisionally and 37.00 once adjudicated.

        PRD §3.9:
        "Its attempt contribution is uncapped and worth more: `verified_attempt_count`
        multiplied by 4 adjudicated points per attempt, where `verified_attempt_count` is
        the number of contact attempts of the complained-about pairing — the complaint's
        `contact_id` together with its `campaign_id` — whose `voided_at` is null and whose
        `outcome` is anything other than `PENDING`."
        PRD §3.9:
        "Otherwise the thresholds are inclusive at each step: a peak of at least 55 makes
        the tier `CRITICAL`, otherwise a peak of at least 40 makes it `HIGH`, otherwise a
        peak of at least 20 makes it `MEDIUM`, and anything below 20 leaves it `LOW`."

        Design: Difficulty/dual_variant_calc/complaint_risk_provisional_vs_adjudicated_divergence
        """
        built = _campaign_with_three_recorded_attempts(world)
        complaint = world.create_complaint(
            built["contact"]["id"],
            built["campaign"]["id"],
            source=ComplaintSource.FTC,
            alleged_violation_type=AllegedViolationType.DNC_VIOLATION,
            litigation_flag=False,
        )
        assert_decimal_equals(complaint["provisional_risk_score"], 31.00)

        adjudicated = world.substantiate_complaint(complaint["id"], willful=False)

        assert_status(adjudicated, ComplaintStatus.SUBSTANTIATED)
        assert_decimal_equals(adjudicated["provisional_risk_score"], 31.00)
        assert_decimal_equals(adjudicated["adjudicated_risk_score"], 37.00)
        assert_fields_equal(
            adjudicated, verified_attempt_count=3, exposure_cents=150000, willful=False
        )

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(
            contact,
            risk_tier=RiskTier.MEDIUM,
            internal_dnc_status=InternalDncStatus.CLEAR,
        )

    def test_06_litigation_bonus_lands_on_the_adjudicated_variant_alone(self, world):
        """An engaged-counsel flag leaves the provisional score at 31.00 and lifts the finding to 52.00.

        PRD §3.9:
        "`litigation_flag` contributes nothing to this variant."
        PRD §3.9:
        "To that it adds a flat litigation bonus of 15 points when the complaint's
        `litigation_flag` is true, and nothing when it is false."

        Design: Difficulty/dual_variant_calc/complaint_risk_provisional_vs_adjudicated_divergence
        """
        built = _campaign_with_three_recorded_attempts(world)
        complaint = world.create_complaint(
            built["contact"]["id"],
            built["campaign"]["id"],
            source=ComplaintSource.FTC,
            alleged_violation_type=AllegedViolationType.DNC_VIOLATION,
            litigation_flag=True,
        )
        assert_decimal_equals(complaint["provisional_risk_score"], 31.00)

        adjudicated = world.substantiate_complaint(complaint["id"], willful=False)

        assert_decimal_equals(adjudicated["provisional_risk_score"], 31.00)
        assert_decimal_equals(adjudicated["adjudicated_risk_score"], 52.00)
        assert_fields_equal(adjudicated, verified_attempt_count=3)

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(contact, risk_tier=RiskTier.HIGH)

    def test_07_willfulness_triples_exposure_without_touching_either_score(self, world):
        """A willful finding multiplies the cents by three while the adjudicated score stays 37.00.

        PRD §3.9:
        "Statutory exposure is the plainest calculation in the domain: `exposure_cents` is
        `verified_attempt_count` multiplied by a statutory base of 50000 cents per attempt,
        multiplied by 3 when the supplied `willful` is true and by 1 when it is false."

        Design: Difficulty/dual_variant_calc/complaint_risk_provisional_vs_adjudicated_divergence
        """
        built = _campaign_with_three_recorded_attempts(world)
        complaint = world.create_complaint(
            built["contact"]["id"],
            built["campaign"]["id"],
            source=ComplaintSource.FTC,
            alleged_violation_type=AllegedViolationType.DNC_VIOLATION,
            litigation_flag=False,
        )

        adjudicated = world.substantiate_complaint(complaint["id"], willful=True)

        assert_fields_equal(
            adjudicated, willful=True, verified_attempt_count=3, exposure_cents=450000
        )
        assert_decimal_equals(adjudicated["adjudicated_risk_score"], 37.00)
        assert_decimal_equals(adjudicated["provisional_risk_score"], 31.00)

    def test_08_dismissal_keeps_the_provisional_score_and_never_adjudicates(self, world):
        """A dismissed complaint keeps 31.00, gains no adjudicated figures and re-tiers nobody.

        PRD §3.9:
        "A complaint that is dismissed keeps its provisional score and never receives an
        adjudicated one."
        PRD §3.9:
        "It produces none of the substantiation side effects: `adjudicated_risk_score`,
        `verified_attempt_count`, `exposure_cents` and `willful` all stay null, and the
        consumer's `risk_tier` is not recomputed at all."

        Design: Difficulty/dual_variant_calc/complaint_risk_provisional_vs_adjudicated_divergence
        """
        built = _campaign_with_three_recorded_attempts(world)
        complaint = world.create_complaint(
            built["contact"]["id"],
            built["campaign"]["id"],
            source=ComplaintSource.FTC,
            alleged_violation_type=AllegedViolationType.DNC_VIOLATION,
            litigation_flag=False,
        )

        dismissed = world.dismiss_complaint(complaint["id"])

        assert_status(dismissed, ComplaintStatus.DISMISSED)
        assert_decimal_equals(dismissed["provisional_risk_score"], 31.00)
        assert_fields_null(
            dismissed,
            "adjudicated_risk_score",
            "verified_attempt_count",
            "exposure_cents",
            "willful",
        )

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(
            contact,
            risk_tier=RiskTier.LOW,
            internal_dnc_status=InternalDncStatus.CLEAR,
        )

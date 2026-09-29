"""The two injury models, the distance floor, the zero clamp and the offset set.

PRD §3.5: "Because one model attenuates and the other does not,
`SEASONAL_AVERAGE` can produce either a higher or a lower net injury than
`INSTANTANEOUS_DEPLETION` depending on the distance; the two cross over at a move
of 15.22 river miles."
"""
import pytest
from test_helpers import api_client, get_success_data
from test_helpers.fixtures import (
    ANALYST,
    add_injury_analysis,
    conditions_of,
    create_claimant,
    file_protest,
    read_application,
    resolve_protest,
    route_protest,
    setup_draft_application,
    setup_published_application,
)

CLOCK = "2026-03-01T00:00:00Z"


def _read_analysis(analysis_id):
    return get_success_data(api_client.get_injury_analysis(analysis_id, ANALYST))


class TestTheTwoInjuryModelsDivergeOnIdenticalInputs:
    """PRD §3.5 — one application, one set of stored inputs, two answers.

    A certified right of 195.00 AF carries a `DRAFT` change-of-use application
    for 100.00 AF. Two analyses are prepared in turn from byte-identical inputs —
    `pod_move_miles` of 4.00 and no return-flow credit — differing only in
    `method`, which PRD §3.5 makes the sole branch selector.
    """

    def _draft(self):
        return setup_draft_application(requested_af=100.00, clock=CLOCK)

    def test_the_instantaneous_model_attenuates_the_depletion_for_distance(self):
        """PRD §3.5: "Under `INSTANTANEOUS_DEPLETION`, a distance factor is computed
        as one minus fifteen thousandths for each river mile of the move, rounded to
        4 decimal places, and then floored at 0.55 by taking whichever of the two is
        larger."

        A 4.00-mile move gives 1 − 0.060 = 0.9400, well clear of the floor. PRD
        §3.5: "Gross depletion is the application's `requested_af` multiplied by a
        depletion factor of 0.92 and then by that distance factor, rounded to 2
        decimal places" — 100.00 × 0.92 × 0.9400 = 86.48. With no stipulated
        protests and no return-flow credit the net equals the gross.

        Design: Corner/calculations/calc_injury_variant_divergence_same_inputs_two_methods
        """
        bundle = self._draft()

        analysis = add_injury_analysis(
            bundle["application"]["id"],
            "INSTANTANEOUS_DEPLETION",
            4.00,
            return_flow_credit_af=0.00,
        )

        assert analysis["method"] == "INSTANTANEOUS_DEPLETION"
        assert analysis["pod_move_miles"] == pytest.approx(4.00, abs=0.01)
        assert analysis["gross_depletion_af"] == pytest.approx(86.48, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(0.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(86.48, abs=0.01)

    def test_the_seasonal_model_on_the_same_inputs_returns_a_flat_factor(self):
        """PRD §3.5: "gross depletion is simply `requested_af` multiplied by a flat
        seasonal factor of 0.78, rounded to 2 decimal places."

        The seasonal reading of the identical 100.00 AF request is 78.00, which is
        8.48 AF below the instantaneous reading of the same row: 0.92 × 0.9400 is
        0.8648, and no rounding of one figure produces the other. PRD §3.5 also
        keeps the superseded arithmetic on the record — "Preparing a new one moves
        any existing `DRAFT` analysis on the same application to the terminal
        `VOIDED`" — so the voided row still reads 86.48.

        Design: Corner/calculations/calc_injury_variant_divergence_same_inputs_two_methods
        """
        bundle = self._draft()
        instantaneous = add_injury_analysis(
            bundle["application"]["id"],
            "INSTANTANEOUS_DEPLETION",
            4.00,
            return_flow_credit_af=0.00,
        )

        seasonal = add_injury_analysis(
            bundle["application"]["id"],
            "SEASONAL_AVERAGE",
            4.00,
            return_flow_credit_af=0.00,
        )

        assert seasonal["status"] == "DRAFT"
        assert seasonal["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert seasonal["net_injury_af"] == pytest.approx(78.00, abs=0.01)
        assert instantaneous["gross_depletion_af"] - seasonal[
            "gross_depletion_af"
        ] == pytest.approx(8.48, abs=0.01)
        voided = _read_analysis(instantaneous["id"])
        assert voided["status"] == "VOIDED"
        assert voided["gross_depletion_af"] == pytest.approx(86.48, abs=0.01)
        assert voided["net_injury_af"] == pytest.approx(86.48, abs=0.01)


class TestTheSeasonalBranchIgnoresTheMileage:
    """PRD §3.5 — "`pod_move_miles` is read from the payload, stored, and then
    ignored by the arithmetic".

    Four analyses are run in turn on one 100.00 AF application, pairing each method
    with a 0.00-mile move and a 40.00-mile move, so the mileage's effect on each
    branch is visible on the same request volume.
    """

    def _draft(self):
        return setup_draft_application(requested_af=100.00, clock=CLOCK)

    def test_forty_miles_of_move_changes_nothing_under_the_seasonal_model(self):
        """PRD §3.5: "Under `SEASONAL_AVERAGE` there is no distance attenuation
        whatsoever — `pod_move_miles` is read from the payload, stored, and then
        ignored by the arithmetic — and gross depletion is simply `requested_af`
        multiplied by a flat seasonal factor of 0.78, rounded to 2 decimal places."

        A forty-mile difference in the stored input leaves both rows at 78.00, and
        each row still reports back the mileage it was given: the input is retained
        even where the selected branch never consults it.

        Design: Corner/calculations/calc_injury_variant_selection_seasonal_ignores_pod_move_miles
        """
        bundle = self._draft()

        near = add_injury_analysis(bundle["application"]["id"], "SEASONAL_AVERAGE", 0.00)
        far = add_injury_analysis(bundle["application"]["id"], "SEASONAL_AVERAGE", 40.00)

        assert near["pod_move_miles"] == pytest.approx(0.00, abs=0.01)
        assert far["pod_move_miles"] == pytest.approx(40.00, abs=0.01)
        for analysis in (near, far):
            assert analysis["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
            assert analysis["net_injury_af"] == pytest.approx(78.00, abs=0.01)

    def test_the_same_two_mileages_diverge_sharply_under_the_other_model(self):
        """PRD §3.5: "Moving the diversion far downstream therefore materially
        reduces computed injury, but only down to the floor."

        The instantaneous branch reads the very same stored inputs and answers
        differently for each: an unmoved headgate gives a distance factor of 1.0000
        and 92.00 AF, while forty miles is deep past the floor at 0.5500 and gives
        50.60 AF. The stored `method` is the only thing that decides whether the
        mileage matters at all.

        Design: Corner/calculations/calc_injury_variant_selection_seasonal_ignores_pod_move_miles
        """
        bundle = self._draft()

        near = add_injury_analysis(
            bundle["application"]["id"], "INSTANTANEOUS_DEPLETION", 0.00
        )
        far = add_injury_analysis(
            bundle["application"]["id"], "INSTANTANEOUS_DEPLETION", 40.00
        )

        assert near["gross_depletion_af"] == pytest.approx(92.00, abs=0.01)
        assert far["gross_depletion_af"] == pytest.approx(50.60, abs=0.01)
        assert far["pod_move_miles"] == pytest.approx(40.00, abs=0.01)


class TestTheDistanceFactorFloorClampsTheAttenuation:
    """PRD §3.5 — the floor is reached exactly at thirty miles.

    Three instantaneous analyses on one 100.00 AF application straddle the floor at
    29.00, 30.00 and 31.00 river miles.
    """

    def _draft(self):
        return setup_draft_application(requested_af=100.00, clock=CLOCK)

    def test_the_last_unclamped_mile_still_attenuates(self):
        """PRD §3.5: "a distance factor is computed as one minus fifteen thousandths
        for each river mile of the move, rounded to 4 decimal places, and then
        floored at 0.55 by taking whichever of the two is larger."

        At 29.00 miles the arithmetic gives 0.5650, still above the floor, and
        100.00 × 0.92 × 0.5650 is 51.98. At 30.00 miles the arithmetic gives exactly
        0.5500, so taking the larger of the two is a no-op and the answer drops to
        50.60. The factor is stored at the full four decimal places the rule names,
        not narrowed to the two that carry the volumes.

        Design: Corner/calculations/calc_injury_distance_factor_floor_clamps_at_the_declared_minimum
        """
        bundle = self._draft()

        below = add_injury_analysis(
            bundle["application"]["id"], "INSTANTANEOUS_DEPLETION", 29.00
        )
        at_floor = add_injury_analysis(
            bundle["application"]["id"], "INSTANTANEOUS_DEPLETION", 30.00
        )

        assert below["gross_depletion_af"] == pytest.approx(51.98, abs=0.01)
        assert at_floor["gross_depletion_af"] == pytest.approx(50.60, abs=0.01)

    def test_beyond_the_floor_the_extra_mile_buys_nothing(self):
        """PRD §3.5: "then floored at 0.55 by taking whichever of the two is
        larger."

        At 31.00 miles the unclamped arithmetic would give 0.5350, so the floor
        genuinely binds and the row reads 0.5500 — identical to the 30.00-mile row
        in both the factor and the 50.60 AF gross depletion. An implementation that
        omitted the floor would report a smaller injury for the longer move.

        Design: Corner/calculations/calc_injury_distance_factor_floor_clamps_at_the_declared_minimum
        """
        bundle = self._draft()
        at_floor = add_injury_analysis(
            bundle["application"]["id"], "INSTANTANEOUS_DEPLETION", 30.00
        )

        beyond = add_injury_analysis(
            bundle["application"]["id"], "INSTANTANEOUS_DEPLETION", 31.00
        )

        assert beyond["gross_depletion_af"] == pytest.approx(50.60, abs=0.01)
        assert beyond["gross_depletion_af"] == pytest.approx(
            at_floor["gross_depletion_af"], abs=0.01
        )


class TestNetInjuryIsFlooredAtZero:
    """PRD §3.5 — a credit larger than the depletion cannot manufacture a negative.

    One 100.00 AF application is analysed twice under `SEASONAL_AVERAGE`, whose
    gross depletion is 78.00. The first analysis over-credits the return flow at
    100.00 AF; the second credits 77.99, one cent short of the whole depletion.
    """

    def _draft(self):
        return setup_draft_application(requested_af=100.00, clock=CLOCK)

    def test_an_over_credited_analysis_reads_exactly_zero(self):
        """PRD §3.5: "`net_injury_af` is then gross depletion less `offset_af` less
        `return_flow_credit_af`, floored at 0.00 by taking whichever of that
        difference and zero is larger, and rounded to 2 decimal places."

        The unclamped difference is 78.00 − 0.00 − 100.00 = −22.00, and the stored
        answer is 0.00. The gross depletion and the credit are both retained as
        supplied, so the clamp is visible as a clamp rather than as lost input.

        Design: Corner/calculations/calc_injury_net_clamped_to_zero_never_negative
        """
        bundle = self._draft()

        analysis = add_injury_analysis(
            bundle["application"]["id"],
            "SEASONAL_AVERAGE",
            0.00,
            return_flow_credit_af=100.00,
        )

        assert analysis["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert analysis["return_flow_credit_af"] == pytest.approx(100.00, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(0.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(0.00, abs=0.005)

    def test_one_cent_of_injury_survives_the_subtraction(self):
        """PRD §3.5: "The two credits are independent and both are subtracted."

        A credit of 77.99 against a depletion of 78.00 leaves exactly 0.01, which is
        the smallest figure the clamp does not swallow — and PRD §3.7 makes that
        cent decisive: "A residual injury of exactly 0.01 blocks it and yields
        `ERR_UNMITIGATED_INJURY` (HTTP 422)".

        Design: Corner/calculations/calc_injury_net_clamped_to_zero_never_negative
        """
        bundle = self._draft()

        analysis = add_injury_analysis(
            bundle["application"]["id"],
            "SEASONAL_AVERAGE",
            0.00,
            return_flow_credit_af=77.99,
        )

        assert analysis["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert analysis["return_flow_credit_af"] == pytest.approx(77.99, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(0.01, abs=0.005)


class TestOnlyNegotiationStipulationsFeedTheOffset:
    """PRD §3.5 — "hearing-track resolutions contribute nothing to it."

    A published 100.00 AF application carries a `SEASONAL_AVERAGE` analysis with a
    gross depletion of 78.00 and no return-flow credit. Four separate protestants
    file one protest each — 10.00, 8.00, 6.00 and 4.00 acre-feet of claimed injury
    — and they are routed two to negotiation and two to a hearing, so all three
    admissible resolution combinations are exercised on a single analysis.
    """

    PROTESTANTS = (
        ("negotiated_first", "Cottonwood Cattle Co", "b@cotton.example", "INDIVIDUAL", 10.00, "INJURY_TO_SENIOR_RIGHT", "NEGOTIATION"),
        ("heard_stipulation", "City of Rill", "c@rill.example", "MUNICIPALITY", 8.00, "ENLARGEMENT", "HEARING"),
        ("heard_dismissal", "Shoshone-Paiute Tribes", "d@tribe.example", "TRIBE", 6.00, "PUBLIC_INTEREST", "HEARING"),
        ("negotiated_second", "Owyhee Grazing Trust", "e@owyhee.example", "INDIVIDUAL", 4.00, "NO_BENEFICIAL_USE", "NEGOTIATION"),
    )
    DUE = "2026-06-01T00:00:00Z"

    def _four_routed_protests(self):
        bundle = setup_published_application(
            requested_af=100.00,
            clock=CLOCK,
            injury_method="SEASONAL_AVERAGE",
            pod_move_miles=0.00,
            analysis_overrides={"return_flow_credit_af": 0.00},
        )
        assert bundle["analysis"]["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        bundle["protests"] = {}
        for key, name, email, entity, claimed, basis, track in self.PROTESTANTS:
            protestant = create_claimant(
                name, contact_email=email, entity_type=entity
            )
            protest = file_protest(
                bundle["application"]["id"], protestant["id"], claimed, basis=basis
            )
            route_protest(protest["id"], track)
            bundle["protests"][key] = protest
        return bundle

    def test_a_negotiated_stipulation_is_the_only_thing_that_lowers_the_net(self):
        """PRD §3.5: "`offset_af` is not an input. It is the sum, rounded to 2 decimal
        places, of the stipulated offset of every protest on this application that
        has reached `RESOLVED_STIPULATED` on the negotiation track".

        PRD §3.6: "On the negotiation branch the protest moves `IN_NEGOTIATION →
        RESOLVED_STIPULATED`, the `stipulated_offset_af` is recorded, and the
        application's `DRAFT` injury analysis recomputes `offset_af` as the sum of
        stipulated offsets across all negotiation-track resolved protests and
        recomputes `net_injury_af` accordingly". A 5.00 AF concession against a
        78.00 AF depletion leaves 73.00.

        Design: Corner/calculations/calc_injury_offset_input_set_filtering_negotiation_stipulations_only
        """
        bundle = self._four_routed_protests()

        resolve_protest(
            bundle["protests"]["negotiated_first"]["id"],
            "STIPULATE",
            resolution_note="Negotiated 5.00 AF forbearance offset.",
            stipulated_offset_af=5.00,
        )

        analysis = _read_analysis(bundle["analysis"]["id"])
        assert analysis["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(5.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(73.00, abs=0.01)
        assert analysis["status"] == "DRAFT"

    def test_a_hearing_stipulation_buys_a_condition_but_no_volume(self):
        """PRD §3.6: "On the hearing branch the protest moves `IN_HEARING →
        RESOLVED_STIPULATED`, `stipulated_offset_af` stays at 0.00 because the
        hearing branch grants no volumetric offset at all and therefore leaves
        `net_injury_af` untouched, and instead one approval condition is created on
        the application with `source` set to `HEARING_RESOLUTION`, `status`
        `IMPOSED` and `required_af` equal to the protest's `claimed_injury_af`."

        The 8.00 AF hearing claim is fully answered by a measuring device and the
        6.00 AF dismissal is answered by nothing at all, so 14.00 acre-feet of
        claimed injury leaves the offset exactly where the single negotiation
        stipulation put it. PRD §3.6: "The dismissal branch moves the protest
        `IN_HEARING → DISMISSED` with neither an offset nor a condition."

        Design: Corner/calculations/calc_injury_offset_input_set_filtering_negotiation_stipulations_only
        """
        bundle = self._four_routed_protests()
        resolve_protest(
            bundle["protests"]["negotiated_first"]["id"],
            "STIPULATE",
            resolution_note="Negotiated 5.00 AF forbearance offset.",
            stipulated_offset_af=5.00,
        )

        heard = resolve_protest(
            bundle["protests"]["heard_stipulation"]["id"],
            "STIPULATE",
            resolution_note="Hearing stipulation with a measuring device.",
            condition_type="MEASUREMENT_DEVICE",
            compliance_due_date=self.DUE,
        )
        dismissed = resolve_protest(
            bundle["protests"]["heard_dismissal"]["id"],
            "DISMISS",
            resolution_note="Public-interest claim not substantiated.",
        )

        assert heard["status"] == "RESOLVED_STIPULATED"
        assert heard["stipulated_offset_af"] == pytest.approx(0.00, abs=0.01)
        assert dismissed["status"] == "DISMISSED"
        analysis = _read_analysis(bundle["analysis"]["id"])
        assert analysis["offset_af"] == pytest.approx(5.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(73.00, abs=0.01)
        conditions = conditions_of(bundle["application"]["id"])
        assert len(conditions) == 1
        assert conditions[0]["source"] == "HEARING_RESOLUTION"
        assert conditions[0]["condition_type"] == "MEASUREMENT_DEVICE"
        assert conditions[0]["status"] == "IMPOSED"
        assert conditions[0]["required_af"] == pytest.approx(8.00, abs=0.01)

    def test_the_negotiated_offsets_sum_and_freeze_on_the_last_clearance(self):
        """PRD §3.5: "It is the sum, rounded to 2 decimal places, of the stipulated
        offset of every protest on this application that has reached
        `RESOLVED_STIPULATED` on the negotiation track".

        The second negotiation stipulation adds to the first rather than replacing
        it, so the offset reads 9.00 and never 4.00, and it excludes the 8.00 AF
        hearing claim, so it never reads 17.00. That fourth resolution is also the
        last clearance, and PRD §3.6 freezes the arithmetic there: "its `DRAFT`
        injury analysis moves to the terminal `FINALIZED`, freezing
        `gross_depletion_af`, `offset_af` and `net_injury_af`".

        Design: Corner/calculations/calc_injury_offset_input_set_filtering_negotiation_stipulations_only
        """
        bundle = self._four_routed_protests()
        resolve_protest(
            bundle["protests"]["negotiated_first"]["id"],
            "STIPULATE",
            resolution_note="Negotiated 5.00 AF forbearance offset.",
            stipulated_offset_af=5.00,
        )
        resolve_protest(
            bundle["protests"]["heard_stipulation"]["id"],
            "STIPULATE",
            resolution_note="Hearing stipulation with a measuring device.",
            condition_type="MEASUREMENT_DEVICE",
        )
        resolve_protest(
            bundle["protests"]["heard_dismissal"]["id"],
            "DISMISS",
            resolution_note="Public-interest claim not substantiated.",
        )

        resolve_protest(
            bundle["protests"]["negotiated_second"]["id"],
            "STIPULATE",
            resolution_note="Negotiated a further 4.00 AF offset.",
            stipulated_offset_af=4.00,
        )

        analysis = _read_analysis(bundle["analysis"]["id"])
        assert analysis["status"] == "FINALIZED"
        assert analysis["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(9.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(69.00, abs=0.01)
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "READY_FOR_DECISION"
        assert application["unresolved_protest_count"] == 0

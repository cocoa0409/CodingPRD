"""The decree waterfall, the strict credit floor, and the status precedence.

PRD §3.10: "The decreed volume runs a waterfall whose evaluation order is pinned."

PRD §2.10: "Because `PARTIALLY_TRANSFERRED` outranks `ENCUMBERED`, a right holding
both a completed transfer and a fresh escrow reads `PARTIALLY_TRANSFERRED`."
"""
import pytest
from test_helpers import api_client, get_success_data
from test_helpers.fixtures import (
    ADJUDICATOR,
    ANALYST,
    activate_right,
    add_injury_analysis,
    add_use_record,
    create_water_right,
    decide,
    draft_application,
    examine_claim,
    file_claim,
    open_docket,
    read_account,
    read_claim,
    read_docket,
    read_right,
    reserve_lease,
    set_clock,
    setup_application_ready_for_decision,
    setup_base_right,
    setup_docket_in_objection_period,
    setup_authorized_headgate_account,
    submit_application,
    verify_claim,
)

CLOCK = "2026-03-01T00:00:00Z"
FILING_DEADLINE = "2026-04-01T00:00:00Z"
DEADLINE_REACHED = "2026-04-02T00:00:00Z"
RECORDED_PRIORITY = "1901-05-01T00:00:00Z"
WITHIN_TOLERANCE = "1900-04-30T00:00:00Z"
BEYOND_TOLERANCE = "1900-04-29T00:00:00Z"


def _advance(docket_id, target_phase):
    return get_success_data(
        api_client.advance_docket_phase(docket_id, target_phase, ADJUDICATOR)
    )


def _decree(claim_id, decree_note):
    return get_success_data(
        api_client.decree_adjudication_claim(claim_id, decree_note, ADJUDICATOR)
    )


def _object(claim_id, basis="PRIORITY_DATE"):
    return get_success_data(
        api_client.object_to_adjudication_claim(
            claim_id, basis, "Claimed 1900 priority is unsupported.", ADJUDICATOR
        )
    )


class TestTheHaircutsLandOnTheExaminerFloor:
    """PRD §3.10 — a claim of 100.00 against a recommendation of 87.77.

    The claim also carries one objection and a priority discrepancy well beyond
    tolerance, so both haircuts apply, and they apply to the recommendation rather
    than to the claim. An implementation that haircut `claimed_af` would decree
    81.00; the pinned order decrees 71.09.
    """

    def _objected_claim(self):
        bundle = setup_docket_in_objection_period(
            clock=CLOCK,
            examiner_recommended_af=87.77,
            claim_filing_deadline=FILING_DEADLINE,
            deadline_reached_at=DEADLINE_REACHED,
            claimed_af=100.00,
            claimed_priority_date=BEYOND_TOLERANCE,
            use_years=(2025,),
        )
        bundle["claim"] = _object(bundle["claim"]["id"])
        return bundle

    def test_the_floored_volume_is_what_the_two_haircuts_compound_on(self):
        """PRD §3.10: "First the volume is floored at the lesser of `claimed_af` and
        `examiner_recommended_af`. Second, when `objection_count` is at least 1, that
        figure is multiplied by 0.90 and rounded to 3 decimal places. Third, when the
        absolute difference between the claim's `claimed_priority_date` and the
        right's recorded `priority_date` is more than 366 whole days, the running
        figure is multiplied by 0.90 again and rounded to 3 decimal places; the
        tolerance test is strict, so a discrepancy of exactly 366 days is within
        tolerance and 367 days is not. Fourth, `decreed_af` is the running figure
        rounded once to 2 decimal places."

        87.77 floors the claim, 78.993 survives the objection, 71.094 survives the
        priority mismatch, and 71.09 is what a single final rounding leaves.

        Design: Corner/calculations/calc_decreed_volume_pinned_haircut_order_on_the_examiner_floor
        """
        bundle = self._objected_claim()

        claim = _decree(bundle["claim"]["id"], "Decree entered on the objected claim.")

        assert claim["filing_status"] == "DECREED"
        assert claim["objection_count"] == 1
        assert claim["claimed_af"] == pytest.approx(100.00, abs=0.01)
        assert claim["examiner_recommended_af"] == pytest.approx(87.77, abs=0.01)
        assert claim["decreed_af"] == pytest.approx(71.09, abs=0.005)

    def test_the_docket_bubbles_up_carrying_the_haircut_total(self):
        """PRD §3.10: "Because the haircuts compound multiplicatively and each
        intermediate is rounded to 3 decimal places before the next is applied, a
        claim carrying both an objection and a priority mismatch retains 0.81 of its
        floored volume rather than losing 0.20 of it, and the single final
        2-decimal-place rounding is applied only once, at the end."

        The decreed figure is also what the docket totals, so the retained 0.81 of
        87.77 is visible on both rows.

        Design: Corner/calculations/calc_decreed_volume_pinned_haircut_order_on_the_examiner_floor
        """
        bundle = self._objected_claim()

        claim = _decree(bundle["claim"]["id"], "Decree entered on the objected claim.")

        assert claim["priority_rank"] == 1
        docket = read_docket(bundle["docket"]["id"])
        assert docket["phase"] == "DECREE_ENTERED"
        assert docket["claim_count"] == 1
        assert docket["decreed_claim_count"] == 1
        assert docket["total_decreed_af"] == pytest.approx(71.09, abs=0.005)


class TestThePriorityToleranceIsStrictAtThreeHundredSixtySix:
    """PRD §3.10 — two claims one calendar day apart against the same recorded date.

    Both rights are recorded at 1901-05-01 and both claims are recommended at the
    full 100.00 with no objection, so the priority discrepancy is the only variable
    left: 366 days on one claim and 367 on the other.
    """

    def _two_claims(self):
        bundle = setup_base_right(CLOCK, use_years=(2025,))
        second = create_water_right(
            bundle["claimant"]["id"],
            right_number="WR-2198-002",
            priority_date=RECORDED_PRIORITY,
        )
        add_use_record(
            second["id"],
            2025,
            reported_diversion_af=300.000,
            irrigated_acres=100.00,
            verification_source="METER",
        )
        bundle["second_right"] = activate_right(second["id"])
        bundle["docket"] = open_docket(FILING_DEADLINE)
        bundle["in_tolerance"] = file_claim(
            bundle["docket"]["id"], bundle["right"]["id"], WITHIN_TOLERANCE, 100.00
        )
        bundle["beyond_tolerance"] = file_claim(
            bundle["docket"]["id"], bundle["second_right"]["id"], BEYOND_TOLERANCE, 100.00
        )
        set_clock(DEADLINE_REACHED)
        _advance(bundle["docket"]["id"], "EXAMINATION")
        for key in ("in_tolerance", "beyond_tolerance"):
            examine_claim(bundle[key]["id"], 100.00)
            bundle[key] = verify_claim(bundle[key]["id"])
        bundle["docket"] = _advance(bundle["docket"]["id"], "OBJECTION_PERIOD")
        return bundle

    def test_exactly_three_hundred_sixty_six_days_is_within_tolerance(self):
        """PRD §3.10: "the tolerance test is strict, so a discrepancy of exactly 366
        days is within tolerance and 367 days is not."

        1900-04-30 to 1901-05-01 is exactly 366 whole days, so no haircut applies at
        all and the recommendation floor is decreed intact.

        Design: Corner/calculations/calc_decreed_volume_priority_tolerance_boundary_366_versus_367_days
        """
        bundle = self._two_claims()

        claim = _decree(
            bundle["in_tolerance"]["id"], "366-day discrepancy is within tolerance."
        )

        assert claim["objection_count"] == 0
        assert claim["decreed_af"] == pytest.approx(100.00, abs=0.005)
        assert claim["filing_status"] == "DECREED"

    def test_one_day_further_back_costs_a_tenth_of_the_volume(self):
        """PRD §3.10: "Third, when the absolute difference between the claim's
        `claimed_priority_date` and the right's recorded `priority_date` is more than
        366 whole days, the running figure is multiplied by 0.90 again and rounded to
        3 decimal places".

        1900-04-29 is 367 days out, so 100.00 becomes 90.00. The haircut is
        volumetric only: seniority still reads off `claimed_priority_date`, so the
        haircut claim — being the earlier of the two — still takes rank 1. PRD §3.10:
        "`priority_rank` is recomputed for *every* decreed claim on the docket, not
        merely the new one, as a 1-based rank ordered by `claimed_priority_date`
        ascending and tie-broken by `created_at` ascending, never by `id`; each
        re-ranked claim bumps its own `version`."

        Design: Corner/calculations/calc_decreed_volume_priority_tolerance_boundary_366_versus_367_days
        """
        bundle = self._two_claims()
        _decree(bundle["in_tolerance"]["id"], "366-day discrepancy is within tolerance.")

        haircut = _decree(
            bundle["beyond_tolerance"]["id"], "367-day discrepancy exceeds tolerance."
        )

        assert haircut["decreed_af"] == pytest.approx(90.00, abs=0.005)
        assert haircut["priority_rank"] == 1
        assert read_claim(bundle["in_tolerance"]["id"])["priority_rank"] == 2
        docket = read_docket(bundle["docket"]["id"])
        assert docket["phase"] == "DECREE_ENTERED"
        assert docket["decreed_claim_count"] == 2
        assert docket["total_decreed_af"] == pytest.approx(190.00, abs=0.01)


class TestTheLowCreditFloorIsStrict:
    """PRD §2.10 — one hundredth of an acre-foot decides the posture.

    A funded account holds 25.00 acre-feet of credit against an
    `IN_GOOD_STANDING` holder with no suspended lease, so the low-credit trigger
    is the only one in play. Two reservations on the same headgate over adjacent,
    non-overlapping windows walk `available_credit_af` from 25.00 to 5.00 and then
    to 4.99.
    """

    FIRST_WINDOW = ("2026-04-01T00:00:00Z", "2026-07-01T00:00:00Z")
    SECOND_WINDOW = ("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")

    def _funded_account(self):
        return setup_authorized_headgate_account(deposit_af=25.00, clock=CLOCK)

    def _reserve(self, bundle, window, requested_af):
        return get_success_data(
            reserve_lease(
                bundle["account"]["id"],
                bundle["right"]["id"],
                bundle["pod"]["id"],
                window[0],
                window[1],
                requested_af,
            )
        )

    def test_exactly_five_acre_feet_of_available_credit_is_still_open(self):
        """PRD §2.10: "The credit floor is strict: an available credit of exactly 5.00
        acre-feet is not `RESTRICTED`, while 4.99 is; and a single suspended lease is
        already enough for `FROZEN`."

        Committing 20.00 of the 25.00 leaves the available bucket sitting exactly on
        the floor. PRD §3.9: "The lease is created in `RESERVED`,
        `committed_credit_af` increases and `available_credit_af` decreases by
        `requested_af` — the credit identity is conserved because the total is merely
        repartitioned — and the posture is recomputed, since committing credit can
        drop `available_credit_af` below the 5.00 acre-foot floor and force
        `RESTRICTED`."

        Design: Corner/calculations/calc_bank_posture_low_credit_floor_is_strict_below_five_af
        """
        bundle = self._funded_account()
        assert bundle["account"]["available_credit_af"] == pytest.approx(25.00, abs=0.01)
        assert bundle["account"]["posture"] == "OPEN"

        lease = self._reserve(bundle, self.FIRST_WINDOW, 20.00)

        assert lease["status"] == "RESERVED"
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(25.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(20.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(5.00, abs=0.005)
        assert account["posture"] == "OPEN"

    def test_one_hundredth_below_the_floor_restricts_the_account(self):
        """PRD §2.10: "Failing that, it reads `RESTRICTED` when the holding
        claimant's `standing_status` is `DELINQUENT` or when `available_credit_af` is
        strictly below 5.00 acre-feet."

        A second reservation of 0.01 acre-feet is the whole difference. Nothing else
        moves: no deposit, no suspension, no change of standing, and the two windows
        are adjacent rather than overlapping — PRD §3.9 measures the delivery window
        as at or after `lease_start_date` and strictly before `lease_end_date`.

        Design: Corner/calculations/calc_bank_posture_low_credit_floor_is_strict_below_five_af
        """
        bundle = self._funded_account()
        first = self._reserve(bundle, self.FIRST_WINDOW, 20.00)

        second = self._reserve(bundle, self.SECOND_WINDOW, 0.01)

        assert first["status"] == "RESERVED"
        assert second["status"] == "RESERVED"
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(25.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(20.01, abs=0.005)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(4.99, abs=0.005)
        assert account["suspended_lease_count"] == 0
        assert account["posture"] == "RESTRICTED"


class TestPartiallyTransferredOutranksEncumbered:
    """PRD §2.10 — the derivation is read top to bottom on one right, three times.

    A right certified at 195.00 permanently transfers 100.00 through an approved
    application, then escrows a fresh 50.00 on a second application, then releases
    that escrow again. `transferred_away_af` is tested before `encumbered_af`, so
    the status never moves off `PARTIALLY_TRANSFERRED` once it lands there.
    """

    DEADLINE_REACHED = "2026-04-01T00:00:00Z"

    def _partially_transferred(self):
        bundle = setup_application_ready_for_decision(
            requested_af=100.00,
            clock=CLOCK,
            deadline_reached_at=self.DEADLINE_REACHED,
            analysis_overrides={"return_flow_credit_af": 78.00},
        )
        bundle["application"] = decide(
            bundle["application"]["id"],
            "APPROVE",
            decision_note="No protests; injury fully offset.",
        )
        bundle["right"] = read_right(bundle["right"]["id"])
        return bundle

    def _escrow_a_second_application(self, bundle):
        second = draft_application(
            bundle["right"]["id"],
            bundle["study"]["id"],
            50.00,
            proposed_purpose_of_use="STOCKWATER",
        )
        add_injury_analysis(second["id"], "SEASONAL_AVERAGE", 0.00, return_flow_credit_af=39.00)
        bundle["second_application"] = submit_application(
            second["id"], bundle["right"]["id"]
        )
        bundle["right"] = read_right(bundle["right"]["id"])
        return bundle

    def test_an_approved_transfer_moves_the_volume_permanently_away(self):
        """PRD §3.7: "On success the application moves `READY_FOR_DECISION →
        APPROVED`, `escrowed_af` is set to 0.00, and on the right the escrowed volume
        moves out of `encumbered_af` and into `transferred_away_af` so that the
        conserved identity holds across the move. The right's status is re-derived,
        which lands it on `PARTIALLY_TRANSFERRED`."

        PRD §2.10: "otherwise a right whose `transferred_away_af` is strictly greater
        than 0.00 reads `PARTIALLY_TRANSFERRED`". 195.00 == 95.00 + 0.00 + 100.00.

        Design: Corner/calculations/calc_right_status_derivation_partially_transferred_outranks_encumbered
        """
        bundle = self._partially_transferred()

        right = bundle["right"]
        assert bundle["application"]["status"] == "APPROVED"
        assert bundle["application"]["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(100.00, abs=0.01)
        assert right["status"] == "PARTIALLY_TRANSFERRED"

    def test_a_fresh_escrow_does_not_downgrade_the_status_to_encumbered(self):
        """PRD §2.10: "It is derived, and the precedence is pinned and evaluated top to
        bottom with the first match winning: a right already `FORFEITED` stays
        `FORFEITED`, because forfeiture is terminal and sticky; otherwise a right
        already `SUSPENDED` stays `SUSPENDED`, because reinstatement is the only route
        out; otherwise a right that has never been activated reads `UNADJUDICATED`;
        otherwise a right whose `transferred_away_af` is strictly greater than 0.00
        reads `PARTIALLY_TRANSFERRED`; otherwise a right whose `encumbered_af` is
        strictly greater than 0.00 reads `ENCUMBERED`; otherwise it reads `ACTIVE`."

        Both buckets are now positive, and the earlier test wins.

        Design: Corner/calculations/calc_right_status_derivation_partially_transferred_outranks_encumbered
        """
        bundle = self._partially_transferred()
        version_before = bundle["right"]["version"]

        self._escrow_a_second_application(bundle)

        right = bundle["right"]
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(45.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(50.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(100.00, abs=0.01)
        assert right["status"] == "PARTIALLY_TRANSFERRED"
        assert right["version"] > version_before

    def test_releasing_the_escrow_does_not_restore_active(self):
        """PRD §3.4: "The application reaches the terminal `WITHDRAWN`; `escrowed_af`
        is released to 0.00 and the released volume moves from the right's
        `encumbered_af` back into its `transferable_af`, conserving the ledger, with
        the right's status re-derived and its `version` bumped."

        The ledger returns to exactly where the approval left it, and because
        `transferred_away_af` never decreases the re-derivation cannot reach `ACTIVE`.

        Design: Corner/calculations/calc_right_status_derivation_partially_transferred_outranks_encumbered
        """
        bundle = self._escrow_a_second_application(self._partially_transferred())

        withdrawn = get_success_data(
            api_client.withdraw_transfer_application(
                bundle["second_application"]["id"], "Lessee walked away.", ANALYST
            )
        )

        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(100.00, abs=0.01)
        assert right["status"] == "PARTIALLY_TRANSFERRED"

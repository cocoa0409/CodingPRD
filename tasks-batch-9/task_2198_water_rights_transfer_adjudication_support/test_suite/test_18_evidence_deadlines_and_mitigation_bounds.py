"""Bounds that decide a single call: the recommendation ceiling, the evidence
standard, the filing instant, and the mitigation sum.

PRD §3.10: "Neither operation on one axis ever touches the other axis, and no
docket counter moves on a verification."
"""
import pytest
from test_helpers import (
    HTTP_STATUS_CODES,
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
)
from test_helpers.factories import (
    condition_entry,
    create_adjudication_claim_payload,
    decide_payload,
)
from test_helpers.fixtures import (
    ADJUDICATOR,
    ANALYST,
    DECIDER,
    add_use_record,
    conditions_of,
    create_water_right,
    file_claim,
    open_docket,
    read_application,
    read_claim,
    read_claimant,
    read_docket,
    read_right,
    set_clock,
    setup_application_ready_for_decision,
    setup_documented_right,
)

CLOCK = "2026-03-01T00:00:00Z"
FILING_DEADLINE = "2026-04-01T00:00:00Z"
DEADLINE_REACHED = "2026-04-02T00:00:00Z"
RECORDED_PRIORITY = "1901-05-01T00:00:00Z"


def _examine(claim_id, examiner_recommended_af, note):
    return api_client.examine_adjudication_claim(
        claim_id, examiner_recommended_af, note, ADJUDICATOR
    )


def _verify(claim_id, outcome, field_note):
    return api_client.verify_adjudication_claim(claim_id, outcome, field_note, ANALYST)


class TestTheRecommendationBoundIsInclusiveAtTheTop:
    """PRD §3.10 — three claims of 100.00 acre-feet each, examined differently.

    One recommendation equals the claim exactly, one sits a cent above it, and one
    is zero. The same rule answers all three.
    """

    def _three_filed_claims(self):
        bundle = setup_documented_right(CLOCK)
        bundle["docket"] = open_docket(FILING_DEADLINE)
        bundle["claims"] = [
            file_claim(
                bundle["docket"]["id"], bundle["right"]["id"], RECORDED_PRIORITY, 100.00
            )
        ]
        for number in ("WR-2198-002", "WR-2198-003"):
            extra = create_water_right(
                bundle["claimant"]["id"],
                right_number=number,
                priority_date=RECORDED_PRIORITY,
            )
            bundle["claims"].append(
                file_claim(bundle["docket"]["id"], extra["id"], RECORDED_PRIORITY, 100.00)
            )
        set_clock(DEADLINE_REACHED)
        bundle["docket"] = get_success_data(
            api_client.advance_docket_phase(
                bundle["docket"]["id"], "EXAMINATION", ADJUDICATOR
            )
        )
        return bundle

    def test_equality_is_accepted_and_one_cent_above_the_claim_is_not(self):
        """PRD §3.10: "It records an `examiner_recommended_af` and an
        `examination_note`, and the recommendation must be strictly greater than zero
        and no greater than `claimed_af`, with equality accepted; a recommendation
        above the claim is `ERR_RECOMMENDATION_EXCEEDS_CLAIM` (422)."

        A recommendation of exactly 100.00 against a claim of 100.00 is admissible,
        which incidentally makes the waterfall's opening floor a no-op; 100.01 is not.

        Design: Corner/validations/val_satisfaction_and_violation_at_the_examiner_recommendation_ceiling
        """
        bundle = self._three_filed_claims()

        accepted = get_success_data(
            _examine(
                bundle["claims"][0]["id"], 100.00, "Recommendation equals the claim."
            )
        )
        rejected = _examine(
            bundle["claims"][1]["id"], 100.01, "Recommendation one cent above the claim."
        )

        assert accepted["filing_status"] == "EXAMINED"
        assert accepted["examiner_recommended_af"] == pytest.approx(100.00, abs=0.005)
        validate_error(
            rejected,
            ApiErrorId.ERR_RECOMMENDATION_EXCEEDS_CLAIM.value,
            expected_status=422,
        )
        untouched = read_claim(bundle["claims"][1]["id"])
        assert untouched["filing_status"] == "FILED"
        assert untouched["examiner_recommended_af"] is None
        docket = read_docket(bundle["docket"]["id"])
        assert docket["claim_count"] == 3
        assert docket["decreed_claim_count"] == 0

    def test_a_zero_recommendation_is_refused_at_the_bottom_of_the_bound(self):
        """PRD §3.10: "the recommendation must be strictly greater than zero and no
        greater than `claimed_af`, with equality accepted".

        The bound is two-sided, so a zero recommendation is not admissible either and
        the claim stays where it was on the procedural axis.

        PRD §3.10 names `ERR_RECOMMENDATION_EXCEEDS_CLAIM` for "a recommendation
        above the claim" only, so the identity carried by the *lower* end of the
        same bound is open: it may be read as the same domain refusal, or as a
        plain body-well-formedness refusal under PRD §2.11's "body
        well-formedness" rung. Either identity is accepted here, each at the HTTP
        status PRD §5 pins to it.

        Design: Corner/validations/val_satisfaction_and_violation_at_the_examiner_recommendation_ceiling
        """
        bundle = self._three_filed_claims()

        response = _examine(bundle["claims"][2]["id"], 0.00, "Zero recommendation.")

        error_id = validate_error_is_one_of(
            response,
            [
                ApiErrorId.ERR_RECOMMENDATION_EXCEEDS_CLAIM.value,
                ApiErrorId.ERR_INVALID_REQUEST.value,
            ],
        )
        validate_error(response, error_id, expected_status=HTTP_STATUS_CODES[
            ApiErrorId(error_id)
        ])
        claim = read_claim(bundle["claims"][2]["id"])
        assert claim["filing_status"] == "FILED"
        assert claim["examiner_recommended_af"] is None
        assert claim["version"] == bundle["claims"][2]["version"]


class TestFieldVerificationReadsEvidenceOnAnotherEntity:
    """PRD §3.10 — the evidence lives on the right, not on the claim.

    The claimed right holds a single affidavit-backed record, which is why it has
    never been activated. The evidentiary axis is driven three times on that claim.
    """

    def _claim_on_affidavit_only_right(self):
        bundle = setup_documented_right(CLOCK)
        add_use_record(
            bundle["right"]["id"],
            2025,
            reported_diversion_af=300.000,
            irrigated_acres=100.00,
            verification_source="AFFIDAVIT",
        )
        bundle["docket"] = open_docket(FILING_DEADLINE)
        bundle["claim"] = file_claim(
            bundle["docket"]["id"], bundle["right"]["id"], RECORDED_PRIORITY, 100.00
        )
        return bundle

    def test_a_dispute_needs_no_evidence_but_a_verification_does(self):
        """PRD §3.10: "Reaching `FIELD_VERIFIED` requires the claim's right to hold at
        least one beneficial-use record whose `verification_source` is `METER` or
        `AERIAL_IMAGERY` — the same physical-evidence standard that governs the first
        activation of a right in §3.1 — and the failure is
        `ERR_NO_VERIFIED_USE_EVIDENCE` (422). Recording `DISPUTED` needs no evidence
        at all."

        Design: Corner/validations/val_cross_entity_field_verification_requires_metered_or_aerial_evidence
        """
        bundle = self._claim_on_affidavit_only_right()

        disputed = get_success_data(
            _verify(
                bundle["claim"]["id"],
                "DISPUTED",
                "Records are inconsistent; disputed pending survey.",
            )
        )
        refused = _verify(bundle["claim"]["id"], "FIELD_VERIFIED", "Affidavit only.")

        assert disputed["verification_status"] == "DISPUTED"
        validate_error(
            refused, ApiErrorId.ERR_NO_VERIFIED_USE_EVIDENCE.value, expected_status=422
        )
        claim = read_claim(bundle["claim"]["id"])
        assert claim["verification_status"] == "DISPUTED"
        assert claim["version"] == disputed["version"]

    def test_one_aerial_imagery_record_makes_the_identical_call_succeed(self):
        """PRD §3.10: "Both `UNVERIFIED → FIELD_VERIFIED` and `UNVERIFIED → DISPUTED`
        are available, and `DISPUTED → FIELD_VERIFIED` is the cycle on this axis, so a
        disputed claim can later be re-verified once the evidence arrives."

        Nothing about the claim changed — the evidence arrived on the right — and the
        procedural axis is untouched throughout. PRD §3.10: "no docket counter moves
        on a verification."

        Design: Corner/validations/val_cross_entity_field_verification_requires_metered_or_aerial_evidence
        """
        bundle = self._claim_on_affidavit_only_right()
        _verify(bundle["claim"]["id"], "DISPUTED", "Disputed pending survey.")
        _verify(bundle["claim"]["id"], "FIELD_VERIFIED", "Affidavit only.")

        add_use_record(
            bundle["right"]["id"],
            2024,
            reported_diversion_af=300.000,
            irrigated_acres=100.00,
            verification_source="AERIAL_IMAGERY",
        )
        verified = get_success_data(
            _verify(
                bundle["claim"]["id"],
                "FIELD_VERIFIED",
                "Aerial imagery reconciles the claimed acreage.",
            )
        )

        assert verified["verification_status"] == "FIELD_VERIFIED"
        assert verified["filing_status"] == "FILED"
        docket = read_docket(bundle["docket"]["id"])
        assert docket["claim_count"] == 1
        assert docket["decreed_claim_count"] == 0
        assert docket["phase"] == "OPEN_FOR_CLAIMS"


class TestFilingClosesAtTheDeadlineInstant:
    """PRD §3.10 — one second either side of `claim_filing_deadline`.

    Two rights are on hand so that the duplicate-claim rule is never implicated,
    and the docket stays `OPEN_FOR_CLAIMS` throughout: only the clock moves.
    """

    ONE_SECOND_EARLY = "2026-03-31T23:59:59Z"

    def _docket_and_two_rights(self):
        bundle = setup_documented_right(CLOCK)
        bundle["second_right"] = create_water_right(
            bundle["claimant"]["id"],
            right_number="WR-2198-002",
            priority_date=RECORDED_PRIORITY,
        )
        bundle["docket"] = open_docket(FILING_DEADLINE)
        return bundle

    def test_a_claim_lodged_one_second_early_is_filed(self):
        """PRD §3.10: "Third, the logical clock must be strictly before
        `claim_filing_deadline`, so filing at exactly the deadline instant is late and
        yields `ERR_CLAIM_FILING_CLOSED` (422)."

        A second inside the window is inside the window, and the claim starts on both
        axes at once. PRD §3.10: "`filing_status` is the procedural dimension, starting
        at `FILED`" and "`verification_status` is the evidentiary dimension, starting
        at `UNVERIFIED`."

        Design: Corner/validations/val_temporal_claim_filing_closes_at_the_deadline_instant
        """
        bundle = self._docket_and_two_rights()
        set_clock(self.ONE_SECOND_EARLY)

        claim = file_claim(
            bundle["docket"]["id"], bundle["right"]["id"], RECORDED_PRIORITY, 100.00
        )

        assert claim["filing_status"] == "FILED"
        assert claim["verification_status"] == "UNVERIFIED"
        docket = read_docket(bundle["docket"]["id"])
        assert docket["claim_count"] == 1
        assert docket["phase"] == "OPEN_FOR_CLAIMS"

    def test_a_claim_lodged_at_the_deadline_instant_is_late(self):
        """PRD §3.10: "so filing at exactly the deadline instant is late and yields
        `ERR_CLAIM_FILING_CLOSED` (422)."

        The docket is still `OPEN_FOR_CLAIMS`, so the lateness is the only thing
        wrong and `ERR_DOCKET_PHASE_INVALID` has no business appearing. PRD §3.10:
        "Filing recomputes the docket's `claim_count` and bumps the docket's
        `version`" — and a rejected filing does neither.

        Design: Corner/validations/val_temporal_claim_filing_closes_at_the_deadline_instant
        """
        bundle = self._docket_and_two_rights()
        set_clock(self.ONE_SECOND_EARLY)
        file_claim(
            bundle["docket"]["id"], bundle["right"]["id"], RECORDED_PRIORITY, 100.00
        )
        before = read_docket(bundle["docket"]["id"])
        set_clock(FILING_DEADLINE)

        response = api_client.create_adjudication_claim(
            create_adjudication_claim_payload(
                bundle["docket"]["id"],
                bundle["second_right"]["id"],
                RECORDED_PRIORITY,
                100.00,
            ),
            ADJUDICATOR,
        )

        validate_error(
            response, ApiErrorId.ERR_CLAIM_FILING_CLOSED.value, expected_status=422
        )
        after = read_docket(bundle["docket"]["id"])
        assert after["claim_count"] == 1
        assert after["version"] == before["version"]
        assert after["phase"] == "OPEN_FOR_CLAIMS"


class TestTheMitigationSumCountsOnlyVolumetricConditions:
    """PRD §3.7 — one `FINALIZED` analysis at 20.00 acre-feet of net injury.

    A 100.00 AF application against a 58.00 AF return-flow credit leaves a 20.00 AF
    residual, which is far too large for the unconditional branch and exactly the
    size of the conditional branch's requirement.
    """

    DUE = "2026-06-01T00:00:00Z"

    def _ready_with_residual_injury(self):
        bundle = setup_application_ready_for_decision(
            requested_af=100.00,
            clock=CLOCK,
            deadline_reached_at=FILING_DEADLINE,
            analysis_overrides={"return_flow_credit_af": 58.00},
        )
        assert bundle["analysis"]["status"] == "FINALIZED"
        assert bundle["analysis"]["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert bundle["analysis"]["offset_af"] == pytest.approx(0.00, abs=0.01)
        assert bundle["analysis"]["net_injury_af"] == pytest.approx(20.00, abs=0.01)
        return bundle

    def _decide(self, application_id, disposition, note, conditions=None):
        overrides = {"decision_note": note}
        if conditions is not None:
            overrides["conditions"] = conditions
        return api_client.decide_transfer_application(
            application_id, decide_payload(disposition, **overrides), DECIDER
        )

    def test_a_residual_injury_blocks_the_unconditional_branch(self):
        """PRD §3.7: "**Unconditional approval** requires the `FINALIZED` analysis's
        `net_injury_af` to be strictly below the materiality threshold of 0.01
        acre-feet. A residual injury of exactly 0.01 blocks it and yields
        `ERR_UNMITIGATED_INJURY` (HTTP 422) — such an application must be carried by
        conditions instead."

        Design: Corner/validations/val_conditional_mitigation_sufficiency_counts_only_volumetric_conditions
        """
        bundle = self._ready_with_residual_injury()

        response = self._decide(
            bundle["application"]["id"], "APPROVE", "Unconditional approval attempt."
        )

        validate_error(
            response, ApiErrorId.ERR_UNMITIGATED_INJURY.value, expected_status=422
        )
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "READY_FOR_DECISION"
        assert application["decided_by_user_id"] is None
        assert application["mitigation_fee_total_usd"] == pytest.approx(0.00, abs=0.01)
        assert conditions_of(bundle["application"]["id"]) == []

    def test_a_measuring_device_contributes_nothing_to_the_mitigation_sum(self):
        """PRD §3.7: "Note that measurement-device and return-flow-maintenance
        conditions, while perfectly valid conditions, contribute nothing to that
        mitigation sum."

        A 20.00 AF measuring-device condition against a 20.00 AF residual therefore
        sums to 0.00. PRD §3.7: "Equality is sufficient; a shortfall is
        `ERR_MITIGATION_INSUFFICIENT` (HTTP 422)."

        Design: Corner/validations/val_conditional_mitigation_sufficiency_counts_only_volumetric_conditions
        """
        bundle = self._ready_with_residual_injury()

        response = self._decide(
            bundle["application"]["id"],
            "APPROVE_WITH_CONDITIONS",
            "Measuring device only.",
            conditions=[condition_entry("MEASUREMENT_DEVICE", 20.00, self.DUE)],
        )

        validate_error(
            response, ApiErrorId.ERR_MITIGATION_INSUFFICIENT.value, expected_status=422
        )
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "READY_FOR_DECISION"
        assert application["decided_by_user_id"] is None
        assert conditions_of(bundle["application"]["id"]) == []

    def test_a_dry_year_forbearance_of_the_same_size_carries_the_approval(self):
        """PRD §3.7: "**Conditional approval** requires a non-empty `conditions` array
        whose summed `required_af`, taken only over entries whose `condition_type` is
        `MITIGATION_PAYMENT` or `DRY_YEAR_FORBEARANCE`, is at least the `FINALIZED`
        analysis's `net_injury_af`."

        The device is still along for the ride and still counts for nothing; the
        forbearance alone meets the requirement at exact equality. Because neither
        condition is a `MITIGATION_PAYMENT`, PRD §3.7 leaves the fiscal axis idle:
        "each `MITIGATION_PAYMENT` condition is priced and enters `payment_status`
        `OUTSTANDING` while every other condition type enters `payment_status`
        `NOT_APPLICABLE`".

        Design: Corner/validations/val_conditional_mitigation_sufficiency_counts_only_volumetric_conditions
        """
        bundle = self._ready_with_residual_injury()

        approved = get_success_data(
            self._decide(
                bundle["application"]["id"],
                "APPROVE_WITH_CONDITIONS",
                "Device plus dry-year forbearance.",
                conditions=[
                    condition_entry("MEASUREMENT_DEVICE", 20.00, self.DUE),
                    condition_entry("DRY_YEAR_FORBEARANCE", 20.00, self.DUE),
                ],
            )
        )

        assert approved["status"] == "APPROVED_WITH_CONDITIONS"
        assert approved["mitigation_fee_total_usd"] == pytest.approx(0.00, abs=0.01)
        conditions = conditions_of(bundle["application"]["id"])
        assert len(conditions) == 2
        for condition in conditions:
            assert condition["status"] == "IMPOSED"
            assert condition["payment_status"] == "NOT_APPLICABLE"
        claimant = read_claimant(bundle["claimant"]["id"])
        assert claimant["standing_status"] == "IN_GOOD_STANDING"
        assert claimant["outstanding_fee_balance_usd"] == pytest.approx(0.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(100.00, abs=0.01)

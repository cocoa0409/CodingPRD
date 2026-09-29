"""The two money formulas whose inputs refuse to be added up independently.

The certification fee folds five stored inputs together through a discount step
and a track step with a rounding between them, so the marginal cost of one extra
declared feature depends on the member's tier. The noncompliance penalty chains
marginal bands, a half-up surcharge rounding and a hard cap in a fixed order, and
every link of that chain is observable on the filed case.
"""

from test_helpers import (
    COMPLIANCE_UNDER_INVESTIGATION,
    PENALTY_CAP_CENTS,
    SUB_DRAFT,
    advance_case,
    build_member,
    build_program,
    build_specification,
    feature,
    get_success_data,
    new_case,
    read_case,
    read_listing,
    read_member,
    set_clock,
)
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_cents,
    assert_penalty,
    assert_states,
    expected_certification_fee,
)
from test_helpers.factories import submission_payload
from test_helpers.test_users import make_member_headers

#: Five thermostat feature sets on one SB3 version: one mandatory baseline and
#: four optional extras, so a submission can declare four codes or five.
THERMOSTAT_FEATURES = [
    feature("T_CORE", "MANDATORY", 12, device_type="THERMOSTAT"),
    feature("T_SCHED", "OPTIONAL", 6, device_type="THERMOSTAT"),
    feature("T_GEO", "OPTIONAL", 4, device_type="THERMOSTAT"),
    feature("T_ECO", "OPTIONAL", 4, device_type="THERMOSTAT"),
    feature("T_REMOTE", "OPTIONAL", 8, device_type="THERMOSTAT"),
]

FOUR_CODES = ["T_CORE", "T_SCHED", "T_GEO", "T_ECO"]
FIVE_CODES = FOUR_CODES + ["T_REMOTE"]


def _draft_thermostat(member_id, specification_id, declared_codes, review_track=None):
    """One DRAFT thermostat submission whose fee is pinned at creation.

    A ``review_track`` of None leaves the field out of the payload altogether, so
    the server's own default decides the second step's multiplier.
    """
    payload = submission_payload(
        member_id, specification_id, declared_codes, device_type="THERMOSTAT"
    )
    if review_track is None:
        payload.pop("review_track")
    else:
        payload["review_track"] = review_track
    return get_success_data(
        api_client.create_submission(payload, make_member_headers(member_id)), 201
    )


def _fee_matrix_program():
    """One SB3 thermostat version, a PROMOTER and an ADOPTER member, and the
    five DRAFT submissions that walk the fee matrix."""
    set_clock()
    ctx = build_specification(THERMOSTAT_FEATURES, security_baseline_level="SB3")
    ctx.promoter_id = build_member(credit_cents=0, tier="PROMOTER").member_id
    ctx.adopter_id = build_member(credit_cents=0, tier="ADOPTER").member_id

    ctx.promoter_four = _draft_thermostat(
        ctx.promoter_id, ctx.specification_id, FOUR_CODES, "EXPEDITED"
    )
    ctx.promoter_five = _draft_thermostat(
        ctx.promoter_id, ctx.specification_id, FIVE_CODES, "EXPEDITED"
    )
    ctx.adopter_four = _draft_thermostat(
        ctx.adopter_id, ctx.specification_id, FOUR_CODES, "EXPEDITED"
    )
    ctx.adopter_five = _draft_thermostat(
        ctx.adopter_id, ctx.specification_id, FIVE_CODES, "EXPEDITED"
    )
    ctx.promoter_four_standard = _draft_thermostat(
        ctx.promoter_id, ctx.specification_id, FOUR_CODES
    )
    return ctx


class TestCertificationFeeMatrix:
    """Five inputs — device class, declared feature count, security baseline,
    member tier and review track — priced across one specification."""

    def test_01_every_cell_of_the_tier_and_feature_matrix_is_pinned_exactly(self):
        """The same SB3 thermostat specification prices four submissions at
        383250, 399000, 511000 and 532000 cents once the tier discount and the
        EXPEDITED multiplier have each rounded to whole cents in turn.

        PRD (§3.4): "The subtotal is the base fee for the device class, plus 15000
        cents — one hundred and fifty dollars — for each entry in
        `declared_feature_codes`, plus the surcharge for the specification's
        security baseline."

        Design: Difficulty/combinatorial_formula/fee_matrix_five_inputs_interact_multiplicatively_not_additively
        """
        ctx = _fee_matrix_program()

        # Thermostat base 180000 plus the SB3 surcharge 125000 plus 15000 per
        # declared code: 365000 on four codes and 380000 on five.
        assert_cents(
            ctx.promoter_four["certification_fee_cents"],
            383250,
            "PROMOTER four-code EXPEDITED certification_fee_cents",
        )
        assert_cents(
            ctx.promoter_five["certification_fee_cents"],
            399000,
            "PROMOTER five-code EXPEDITED certification_fee_cents",
        )
        assert_cents(
            ctx.adopter_four["certification_fee_cents"],
            511000,
            "ADOPTER four-code EXPEDITED certification_fee_cents",
        )
        assert_cents(
            ctx.adopter_five["certification_fee_cents"],
            532000,
            "ADOPTER five-code EXPEDITED certification_fee_cents",
        )

    def test_02_one_extra_declared_feature_costs_more_to_an_adopter_than_a_promoter(self):
        """The identical one-feature delta adds 15750 cents to the PROMOTER's fee
        and 21000 cents to the ADOPTER's, so the five inputs cannot be summed
        independently of one another.

        PRD (§3.4): "In the second step, the review-track multiplier is applied to
        the *already-rounded* result of the first step and rounded half-up to whole
        cents again: `STANDARD` multiplies by one and therefore leaves the figure
        untouched, while `EXPEDITED` multiplies it by 1.40, a forty-percent
        surcharge for jumping the queue."

        Design: Difficulty/combinatorial_formula/fee_matrix_five_inputs_interact_multiplicatively_not_additively
        """
        ctx = _fee_matrix_program()

        promoter_delta = (
            ctx.promoter_five["certification_fee_cents"]
            - ctx.promoter_four["certification_fee_cents"]
        )
        adopter_delta = (
            ctx.adopter_five["certification_fee_cents"]
            - ctx.adopter_four["certification_fee_cents"]
        )
        assert promoter_delta == 15750, (
            "the fifth declared code costs a PROMOTER 15000 * 0.75 * 1.40 cents, "
            "expected 15750, got {}".format(promoter_delta)
        )
        assert adopter_delta == 21000, (
            "the fifth declared code costs an ADOPTER 15000 * 1.00 * 1.40 cents, "
            "expected 21000, got {}".format(adopter_delta)
        )
        assert promoter_delta != adopter_delta, (
            "the marginal cost of one declared feature must depend on the member "
            "tier, got {} for both".format(promoter_delta)
        )

        # The tier discount and the track multiplier compose multiplicatively, so
        # the gap between the two tiers is 0.25 * 365000 * 1.40 and not 0.25 * 365000.
        tier_gap = (
            ctx.adopter_four["certification_fee_cents"]
            - ctx.promoter_four["certification_fee_cents"]
        )
        assert tier_gap == 127750, (
            "the quarter discount is itself multiplied by the EXPEDITED 1.40, "
            "expected a gap of 127750, got {}".format(tier_gap)
        )
        assert tier_gap != 91250, (
            "a gap of 91250 would mean the discount and the multiplier were added "
            "rather than composed, got {}".format(tier_gap)
        )

    def test_03_an_omitted_review_track_prices_the_submission_as_standard(self):
        """The fifth input defaults rather than disappearing: an omitted
        `review_track` is STANDARD, whose multiplier of one leaves the discounted
        273750 cents exactly where the first step put it.

        PRD (§3.4): "An optional `review_track` selects `STANDARD` or `EXPEDITED`
        and defaults to `STANDARD`."

        Design: Difficulty/combinatorial_formula/fee_matrix_five_inputs_interact_multiplicatively_not_additively
        """
        ctx = _fee_matrix_program()

        standard = ctx.promoter_four_standard
        assert standard["review_track"] == "STANDARD", (
            "an omitted review_track must be stored as STANDARD, got {!r}".format(
                standard["review_track"]
            )
        )
        assert_cents(
            standard["certification_fee_cents"],
            273750,
            "PROMOTER four-code STANDARD certification_fee_cents",
        )
        assert_cents(
            standard["certification_fee_cents"],
            expected_certification_fee("THERMOSTAT", 4, "SB3", "PROMOTER", "STANDARD"),
            "PROMOTER four-code STANDARD certification_fee_cents",
        )
        # The same five inputs with EXPEDITED instead of STANDARD, on the same
        # specification and the same member, differ by exactly the 1.40 multiplier.
        assert ctx.promoter_four["certification_fee_cents"] == 383250, (
            "the EXPEDITED sibling of the same declaration must be 383250, got "
            "{}".format(ctx.promoter_four["certification_fee_cents"])
        )

    def test_04_pinning_a_fee_never_moves_the_credit_ledger(self):
        """All five submissions sit in DRAFT with nothing escrowed, and the
        PROMOTER member that opened three of them still shows a zero balance.

        PRD (§3.2): "A submission's `fee_escrowed_cents` is non-zero exactly while
        its `state` is `SUBMITTED`, `IN_REVIEW` or `RETURNED_FOR_INFO`."

        Design: Difficulty/combinatorial_formula/fee_matrix_five_inputs_interact_multiplicatively_not_additively
        """
        ctx = _fee_matrix_program()

        drafts = [
            ("PROMOTER four-code EXPEDITED", ctx.promoter_four),
            ("PROMOTER five-code EXPEDITED", ctx.promoter_five),
            ("ADOPTER four-code EXPEDITED", ctx.adopter_four),
            ("ADOPTER five-code EXPEDITED", ctx.adopter_five),
            ("PROMOTER four-code STANDARD", ctx.promoter_four_standard),
        ]
        for label, submission in drafts:
            assert submission["state"] == SUB_DRAFT, (
                "{} must still be DRAFT after creation, got {}".format(
                    label, submission["state"]
                )
            )
            assert_cents(
                submission["fee_escrowed_cents"], 0, "{} fee_escrowed_cents".format(label)
            )

        promoter = read_member(ctx.promoter_id)
        assert_cents(promoter["credit_balance_cents"], 0, "PROMOTER credit_balance_cents")
        assert_cents(
            promoter["escrowed_credit_cents"], 0, "PROMOTER escrowed_credit_cents"
        )


def _walk_case_to_remediated(case_id, remediation_days=10):
    """Escalate, order remediation and confirm it, which returns the listing's
    enforcement axis to REMEDIATED so the next case may be filed."""
    advance_case(case_id, "ESCALATE")
    advance_case(case_id, "ORDER_REMEDIATION", remediation_days=remediation_days)
    return advance_case(case_id, "CONFIRM_REMEDIATION")


class TestPenaltyAssessmentRoundingOrder:
    """Marginal bands, then a half-up surcharge, then the cap — in that order."""

    def test_05_the_security_surcharge_rounds_its_half_cent_up(self):
        """1001 impacted units assess a subtotal of 320150 cents, whose SECURITY
        surcharge of exactly 112052.5 cents rounds up to 112053 and totals 432203.

        PRD (§3.9): "The `surcharge_cents` is the subtotal multiplied by the
        category's surcharge rate and rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/penalty_surcharge_rounds_a_half_cent_up_before_the_cap_is_applied
        """
        ctx = build_program(stage="listed")

        case = new_case(
            ctx.listing_id,
            category="SECURITY_DEFECT",
            evidence_summary="Attestation key reuse across units",
            claimed_impact_units=1001,
        )

        # 100 * 500 + 900 * 300 + 1 * 150 = 320150 under the marginal bands.
        assert_cents(
            case["assessment_subtotal_cents"], 320150, "assessment_subtotal_cents"
        )
        assert_cents(case["surcharge_cents"], 112053, "surcharge_cents")
        assert_cents(case["penalty_total_cents"], 432203, "penalty_total_cents")
        assert_penalty(case, 1001, "SECURITY_DEFECT")

    def test_06_the_same_subtotal_rounds_a_half_cent_up_at_the_lower_rate_too(self):
        """The identical 320150-cent subtotal under FALSE_FEATURE_DECLARATION
        produces exactly 80037.5 cents of surcharge, which rounds up to 80038 and
        totals 400188.

        PRD (§3.9): "The rates are 0.10 for `INTEROP_DEFECT`, 0.35 for
        `SECURITY_DEFECT`, 0.25 for `FALSE_FEATURE_DECLARATION` and 0.00 for
        `IP_WITHDRAWAL`, so an auto-opened intellectual-property case always
        assesses a surcharge of 0."

        Design: Difficulty/combinatorial_formula/penalty_surcharge_rounds_a_half_cent_up_before_the_cap_is_applied
        """
        ctx = build_program(stage="listed")

        case = new_case(
            ctx.listing_id,
            category="FALSE_FEATURE_DECLARATION",
            evidence_summary="Dimming feature declared but absent",
            claimed_impact_units=1001,
        )

        assert_cents(
            case["assessment_subtotal_cents"], 320150, "assessment_subtotal_cents"
        )
        assert_cents(case["surcharge_cents"], 80038, "surcharge_cents")
        assert_cents(case["penalty_total_cents"], 400188, "penalty_total_cents")
        assert case["surcharge_cents"] != 80037, (
            "truncating the half cent would store 80037, but the rounding is "
            "half-up, got {}".format(case["surcharge_cents"])
        )

    def test_07_the_cap_is_the_last_step_and_leaves_the_surcharge_uncapped(self):
        """30000 impacted units assess 4670000 cents plus an uncapped 1634500-cent
        surcharge, and only the 6304500-cent sum is then clamped to the 5000000-cent
        cap.

        PRD (§3.9): "The cap applies to the total *only*: `assessment_subtotal_cents`
        and `surcharge_cents` are both stored uncapped, so a capped case is
        recognisable by its subtotal plus surcharge exceeding its total."

        Design: Difficulty/combinatorial_formula/penalty_surcharge_rounds_a_half_cent_up_before_the_cap_is_applied
        """
        ctx = build_program(stage="listed")

        case = new_case(
            ctx.listing_id,
            category="SECURITY_DEFECT",
            evidence_summary="Fleet-wide secure boot bypass",
            claimed_impact_units=30000,
        )

        # 100 * 500 + 900 * 300 + 29000 * 150 = 4670000.
        assert_cents(
            case["assessment_subtotal_cents"], 4670000, "assessment_subtotal_cents"
        )
        assert_cents(case["surcharge_cents"], 1634500, "surcharge_cents")
        assert_cents(case["penalty_total_cents"], PENALTY_CAP_CENTS, "penalty_total_cents")
        uncapped = case["assessment_subtotal_cents"] + case["surcharge_cents"]
        assert uncapped == 6304500, (
            "the surcharge is taken on the uncapped subtotal, so the uncapped sum "
            "is 6304500, got {}".format(uncapped)
        )
        assert case["penalty_total_cents"] < uncapped, (
            "the cap must bite only on the total, so 5000000 must be strictly below "
            "the uncapped {}, got {}".format(uncapped, case["penalty_total_cents"])
        )
        # Had the cap been applied before the surcharge, 0.35 of 5000000 would have
        # been charged instead of 0.35 of 4670000.
        assert case["surcharge_cents"] != 1750000, (
            "a surcharge of 1750000 would mean the cap was applied before the rate, "
            "got {}".format(case["surcharge_cents"])
        )
        listing = read_listing(ctx.listing_id)
        assert_states(listing, compliance_status=COMPLIANCE_UNDER_INVESTIGATION)

    def test_08_a_filed_assessment_survives_every_later_disposition(self):
        """Two cases filed in turn against the same listing keep the figures they
        were priced with all the way through escalation, remediation orders and
        remediation confirmation.

        PRD (§3.9): "The **penalty assessment** is priced once at creation, pinned
        onto the case, and never recomputed — a later disposition, remediation or
        closure leaves the figures exactly as they were filed."

        Design: Difficulty/combinatorial_formula/penalty_surcharge_rounds_a_half_cent_up_before_the_cap_is_applied
        """
        ctx = build_program(stage="listed")

        security_case = new_case(
            ctx.listing_id,
            category="SECURITY_DEFECT",
            evidence_summary="Attestation key reuse across units",
            claimed_impact_units=1001,
        )
        _walk_case_to_remediated(security_case["id"])
        declaration_case = new_case(
            ctx.listing_id,
            category="FALSE_FEATURE_DECLARATION",
            evidence_summary="Dimming feature declared but absent",
            claimed_impact_units=1001,
        )
        _walk_case_to_remediated(declaration_case["id"])

        after_security = read_case(security_case["id"])
        after_declaration = read_case(declaration_case["id"])

        assert_cents(
            after_security["assessment_subtotal_cents"],
            320150,
            "SECURITY_DEFECT assessment_subtotal_cents after remediation",
        )
        assert_cents(
            after_security["surcharge_cents"],
            112053,
            "SECURITY_DEFECT surcharge_cents after remediation",
        )
        assert_cents(
            after_security["penalty_total_cents"],
            432203,
            "SECURITY_DEFECT penalty_total_cents after remediation",
        )
        assert_cents(
            after_declaration["assessment_subtotal_cents"],
            320150,
            "FALSE_FEATURE_DECLARATION assessment_subtotal_cents after remediation",
        )
        assert_cents(
            after_declaration["surcharge_cents"],
            80038,
            "FALSE_FEATURE_DECLARATION surcharge_cents after remediation",
        )
        assert_cents(
            after_declaration["penalty_total_cents"],
            400188,
            "FALSE_FEATURE_DECLARATION penalty_total_cents after remediation",
        )
        assert after_security["assessment_subtotal_cents"] == after_declaration[
            "assessment_subtotal_cents"
        ], (
            "both cases claim 1001 units, so their subtotals must agree, got {} and "
            "{}".format(
                after_security["assessment_subtotal_cents"],
                after_declaration["assessment_subtotal_cents"],
            )
        )

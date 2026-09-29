"""Score composition: the maximum-not-sum penalty, the clamp and the coverage bonus."""
from test_helpers import (
    CLOCK_START,
    OCCUPANCY_TAX_RATE_BPS,
    PUBLISHED_RESORT_PER_NIGHT_CENTS,
    SINGLE_FEE_INCLUSIONS,
    add_channel,
    add_draft_profile,
    assert_stamped_at_clock,
    create_resort_fee_payload,
    create_taxability_rule,
    deploy_profile,
    read_fee_program,
    read_property,
    setup_draft_program,
    setup_program_under_review,
    setup_published_program,
    setup_single_fee_published_program,
    validate_success,
)
from test_helpers.fixtures import COMPLIANCE

VOICE_CHANNEL = {
    "name": "Concierge Voice Desk",
    "channel_type": "VOICE",
    "supports_total_price_display": False,
    "supports_itemization": False,
}


def test_incapable_channel_scores_zero_because_the_clamp_runs_once_at_the_end(api):
    """A path worth 10 points less a 30-point penalty reads 0, never -20.

    PRD 3.3: "Finally subtract 5 points for each confirmed undisclosed charge —
    that is, 5 multiplied by the profile's `confirmed_undisclosed_count`. Only
    after every additive and subtractive term has been applied is the result
    clamped, once, into the range 0 to 100 inclusive." The worked illustration
    ends: "and a channel that can do neither, shows no total, does not itemise
    and places disclosure `ABSENT` scores 10 less 30, that is negative 20,
    clamped up to 0."

    Design: Difficulty/combinatorial_formula/disclosure_score_capability_penalty_is_max_not_sum
    """
    env = setup_single_fee_published_program()
    voice = add_channel(env, "voice_channel", **VOICE_CHANNEL)

    assert env["jurisdiction"]["first_quote_total_required"] is True
    assert env["jurisdiction"]["itemization_required_on_folio"] is True
    assert env["program"]["mandatory_fee_count"] == 1
    assert float(env["program"]["inclusion_coverage_ratio"]) == 1.0
    assert env["program"]["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_RESORT_PER_NIGHT_CENTS
    )

    profile = add_draft_profile(
        env,
        channel=voice,
        first_quote_shows_total=False,
        itemized_at_first_quote=False,
        disclosure_placement="ABSENT",
    )

    assert profile["status"] == "DRAFT"
    assert profile["disclosure_score"] == 0
    assert profile["confirmed_undisclosed_count"] == 0
    assert profile["remediation_round"] == 0
    assert profile["last_audited_at"] is None

    # A DRAFT path is outside the candidate set, so it drags nothing down.
    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] is None
    assert prop["disclosure_posture"] == "COMPLIANT"


def test_two_applicable_capability_penalties_deduct_thirty_not_fifty(api):
    """35 additive points less the maximum penalty leaves 5, not a clamped 0.

    PRD 3.3: "Then subtract the capability penalty, which is the **maximum** of
    the applicable penalties rather than their sum. A channel that cannot display
    a total in a jurisdiction whose `first_quote_total_required` is true incurs
    30; a channel that cannot itemise in a jurisdiction whose
    `itemization_required_on_folio` is true incurs 20; when both conditions hold
    the penalty is 30, not 50."

    Design: Difficulty/combinatorial_formula/disclosure_score_capability_penalty_is_max_not_sum
    """
    env = setup_single_fee_published_program()
    voice = add_channel(env, "voice_channel", **VOICE_CHANNEL)

    profile = add_draft_profile(
        env,
        channel=voice,
        first_quote_shows_total=False,
        itemized_at_first_quote=False,
        disclosure_placement="FIRST_QUOTE",
    )

    # 0 + 0 + 25 placement + 10 coverage = 35 additive; 35 - 30 = 5.
    assert profile["disclosure_score"] == 5
    # Summing the two penalties would have produced -15, clamped to 0.
    assert profile["disclosure_score"] != 0
    assert profile["status"] == "DRAFT"


NO_TOTAL_MANDATE = {"jurisdiction_overrides": {"first_quote_total_required": False}}
CAPABLE_GDS = {
    "name": "Global Distribution Desk",
    "channel_type": "GDS",
    "supports_total_price_display": True,
    "supports_itemization": True,
}


def test_minimum_score_of_exactly_sixty_is_at_risk_and_audit_leaves_it_deployed(api):
    """A path scoring exactly 60 is AT_RISK, and auditing it does not flag it.

    PRD 3.3: "the posture follows from the minimum by two strict comparisons: a
    minimum below 60 gives `NON_COMPLIANT`, a minimum below 80 gives `AT_RISK`,
    and anything else gives `COMPLIANT`. The thresholds are half-open on the low
    side, so a minimum of exactly 60 is `AT_RISK` while 59 is `NON_COMPLIANT`".
    PRD 3.3 on auditing: "When the recomputed score is at or above 60, a
    deployed profile stays `DEPLOYED` with only its score and `last_audited_at`
    refreshed."

    Design: Difficulty/boundary_precision_check/disclosure_score_exactly_at_flag_threshold_sixty_does_not_flag
    """
    env = setup_single_fee_published_program(**NO_TOTAL_MANDATE)

    at_sixty = add_draft_profile(
        env,
        first_quote_shows_total=False,
        itemized_at_first_quote=True,
        disclosure_placement="FIRST_QUOTE",
    )
    assert at_sixty["disclosure_score"] == 60

    deployed = deploy_profile(env, profile=at_sixty)
    assert deployed["status"] == "DEPLOYED"
    assert deployed["disclosure_score"] == 60

    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 60
    assert prop["disclosure_posture"] == "AT_RISK"
    assert prop["open_disclosure_obligation_count"] == 0

    audited = validate_success(api.audit_profile(at_sixty["id"], COMPLIANCE))
    assert audited["status"] == "DEPLOYED"
    assert audited["disclosure_score"] == 60
    assert_stamped_at_clock(audited["last_audited_at"], CLOCK_START, "last_audited_at")

    prop_after = read_property(env["property"]["id"])
    assert prop_after["min_channel_disclosure_score"] == 60
    assert prop_after["disclosure_posture"] == "AT_RISK"


def test_a_path_one_placement_band_lower_scores_fifty_and_audit_flags_it(api):
    """A path at 50 makes the property NON_COMPLIANT and flags on audit.

    PRD 3.3: "When the audited profile is `DEPLOYED` and the recomputed score is
    strictly below 60, the profile transitions `DEPLOYED → FLAGGED`; the
    property's `min_channel_disclosure_score` and `disclosure_posture` are
    recomputed with the newly flagged profile contributing 0, the property's
    `open_disclosure_obligation_count` is recomputed".

    Design: Difficulty/boundary_precision_check/disclosure_score_exactly_at_flag_threshold_sixty_does_not_flag
    """
    env = setup_single_fee_published_program(**NO_TOTAL_MANDATE)
    gds = add_channel(env, "gds_channel", **CAPABLE_GDS)

    at_sixty = add_draft_profile(
        env,
        first_quote_shows_total=False,
        itemized_at_first_quote=True,
        disclosure_placement="FIRST_QUOTE",
    )
    deploy_profile(env, profile=at_sixty)

    below = add_draft_profile(
        env,
        channel=gds,
        first_quote_shows_total=False,
        itemized_at_first_quote=True,
        disclosure_placement="RATE_DETAILS",
    )
    assert below["disclosure_score"] == 50
    deploy_profile(env, profile=below)

    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 50
    assert prop["disclosure_posture"] == "NON_COMPLIANT"

    flagged = validate_success(api.audit_profile(below["id"], COMPLIANCE))
    assert flagged["status"] == "FLAGGED"
    assert flagged["disclosure_score"] == 50

    prop_after = read_property(env["property"]["id"])
    # A FLAGGED path contributes 0 to the minimum regardless of its stored score.
    assert prop_after["min_channel_disclosure_score"] == 0
    assert prop_after["disclosure_posture"] == "NON_COMPLIANT"
    assert prop_after["open_disclosure_obligation_count"] == 1

    unchanged = validate_success(
        api.get_channel_disclosure_profile(at_sixty["id"], COMPLIANCE)
    )
    assert unchanged["status"] == "DEPLOYED"


OPTIONAL_ONLY_FEE = {
    "code": "SPA_CREDIT",
    "label": "Spa Credit",
    "classification": "OPTIONAL",
    "basis": "PER_STAY",
    "amount_cents": 5000,
    "disclosure_text": "An optional spa credit may be added to this stay on request.",
}


def test_coverage_ratio_of_a_program_with_no_mandatory_fee_is_zero_not_one(api):
    """An OPTIONAL-only program publishes at 0.0000, never a vacuous 1.0000.

    PRD 3.2: "`inclusion_coverage_ratio` becomes the fraction of `MANDATORY`
    fees that carry at least one inclusion with `included_value_cents` greater
    than 0, expressed as a decimal with exactly four fractional digits and
    rounded half up; when `mandatory_fee_count` is 0 the ratio is 0.0000 by
    convention, never 1.0000 and never a division by zero."

    Design: Difficulty/boundary_precision_check/inclusion_coverage_ratio_is_zero_not_one_when_no_mandatory_fee_exists
    """
    env = setup_published_program(
        fee_payloads=[OPTIONAL_ONLY_FEE], inclusion_spec={}, taxability_spec={}
    )

    program = read_fee_program(env["program"]["id"])
    assert program["status"] == "PUBLISHED"
    assert program["fee_count"] == 1
    assert program["mandatory_fee_count"] == 0
    assert program["total_mandatory_fee_cents_per_night"] == 0
    assert float(program["inclusion_coverage_ratio"]) == 0.0
    assert float(program["inclusion_coverage_ratio"]) != 1.0

    prop = read_property(env["property"]["id"])
    assert prop["published_fee_program_count"] == 1

    # A program whose single mandatory fee does carry an inclusion reaches 1.0000.
    create_taxability_rule(
        env["jurisdiction"]["id"], "RESORT", "TAXABLE", OCCUPANCY_TAX_RATE_BPS
    )
    env["property"] = prop
    setup_draft_program(
        env=env,
        fee_payloads=[create_resort_fee_payload()],
        inclusion_spec=SINGLE_FEE_INCLUSIONS,
        program_overrides={
            "version_label": "FY27-Q1",
            "effective_from": "2026-12-01T00:00:00Z",
            "effective_to": "2027-03-01T00:00:00Z",
        },
    )
    setup_program_under_review(env=env)
    setup_published_program(env=env)

    covered = read_fee_program(env["program"]["id"])
    assert covered["mandatory_fee_count"] == 1
    assert float(covered["inclusion_coverage_ratio"]) == 1.0


def test_zero_coverage_ratio_awards_no_bonus_so_the_path_scores_eighty(api):
    """A path on an uncovered program scores 40 plus 25 plus 15, that is 80.

    PRD 3.3: "Add a coverage bonus computed from the bound fee program's
    `inclusion_coverage_ratio`: multiply that ratio by 10, take the floor of the
    product, and cap the result at 10 — so a program whose mandatory fees are
    fully covered contributes the full 10 points and one covered half the time
    contributes 5."

    Design: Difficulty/boundary_precision_check/inclusion_coverage_ratio_is_zero_not_one_when_no_mandatory_fee_exists
    """
    env = setup_published_program(
        fee_payloads=[OPTIONAL_ONLY_FEE], inclusion_spec={}, taxability_spec={}
    )

    profile = add_draft_profile(
        env,
        first_quote_shows_total=True,
        itemized_at_first_quote=True,
        disclosure_placement="RATE_DETAILS",
    )

    assert profile["disclosure_score"] == 80
    # 90 is what a bonus of 10 on a vacuous 1.0000 ratio would have produced.
    assert profile["disclosure_score"] != 90

    deployed = deploy_profile(env, profile=profile)
    assert deployed["status"] == "DEPLOYED"
    assert deployed["disclosure_score"] == 80

    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 80
    assert prop["disclosure_posture"] == "COMPLIANT"

"""Showing-of-interest arithmetic, the voter-list deadline anchors, and the three
community-of-interest scoring standards.

The showing-of-interest tests exercise the two denominators the Board may pick
from the state of the scope analysis; the deadline tests contrast the decision
date anchor of a directed election with the approval instant anchor of a
stipulated one; and the scoring tests run the same stored factor set through the
traditional, overwhelming and accretion standards.
"""
import pytest

from test_helpers import (
    BOARD,
    COUNSEL,
    DIRECTOR,
    add_business_days,
    api_client,
    assert_absent,
    assert_classification,
    assert_election_agreement,
    assert_headcount_conservation,
    assert_instant_equals,
    assert_petition,
    create_election_agreement,
    read_petition,
    request_hearing,
    rounds_for_petition,
    score_and_rule,
    set_clock,
    setup_scope_analysis,
    validate_success,
)

CLOCK = "2026-08-03T09:00:00Z"

PROD_SPEC = {
    "code": "PROD", "title": "Production Operator", "headcount": 60,
    "avg_hourly_wage_cents": 2400, "shift_code": "A", "work_location": "PLANT_1",
    "supervisory_authority_count": 0, "employer_position": "INCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 88, "skills_overlap": 90,
    "functional_integration": 92, "interchange_rate": 74, "work_conditions_overlap": 95,
}
MAINT_SPEC = {
    "code": "MAINT", "title": "Maintenance Mechanic", "headcount": 30,
    "avg_hourly_wage_cents": 3200, "shift_code": "A", "work_location": "PLANT_1",
    "supervisory_authority_count": 0, "employer_position": "INCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 82, "skills_overlap": 78,
    "functional_integration": 86, "interchange_rate": 61, "work_conditions_overlap": 84,
}
QC_SPEC = {
    "code": "QC", "title": "Quality Control Inspector", "headcount": 12,
    "avg_hourly_wage_cents": 2900, "shift_code": "B", "work_location": "PLANT_1_LAB",
    "supervisory_authority_count": 0, "employer_position": "EXCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 41, "skills_overlap": 55,
    "functional_integration": 61, "interchange_rate": 21, "work_conditions_overlap": 71,
}
LEAD_SPEC = {
    "code": "LEAD", "title": "Lead Operator", "headcount": 8,
    "avg_hourly_wage_cents": 2800, "shift_code": "A", "work_location": "PLANT_1",
    "supervisory_authority_count": 4, "employer_position": "EXCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 78, "skills_overlap": 82,
    "functional_integration": 80, "interchange_rate": 66, "work_conditions_overlap": 88,
}

# 40 submitted cards less 3 duplicate, 2 undated, 2 stale and 3 non-unit cards.
THIRTY_VALID_CARDS = {
    "submitted_card_count": 40,
    "duplicate_card_count": 3,
    "undated_card_count": 2,
    "stale_card_count": 2,
    "nonunit_card_count": 3,
}

# 30 submitted cards less 1 duplicate, 1 undated and 1 stale card.
TWENTY_SEVEN_VALID_CARDS = {
    "submitted_card_count": 30,
    "duplicate_card_count": 1,
    "undated_card_count": 1,
    "stale_card_count": 1,
    "nonunit_card_count": 0,
}


def _audit_cards(petition_id, counts):
    """Record the authorization-card audit as the Board and return the case."""
    return validate_success(api_client.verify_showing(petition_id, dict(counts), BOARD))


def test_showing_of_interest_measured_against_the_petitioned_unit_while_scope_is_unresolved():
    """With every classification still awaiting a Board ruling, the card audit is
    measured against the whole classified roster, so 30 valid cards out of 110
    classified heads is an insufficient showing and the case is dismissed.

    PRD: "`valid_card_count` is the submitted count with all four struck counts subtracted from it, as exact integer arithmetic."
    PRD: "If at least one classification is still `PENDING`, or has become `MOOT`, the basis is `AS_PETITIONED` and the denominator is `total_classified_headcount`, because with scope unresolved the Board tests the showing against the unit as the petition described it — every classified head counts, including the ones the employer wants excluded."
    PRD: "`showing_of_interest_pct` is the valid card count multiplied by 100, divided by the selected denominator, rounded half-up to two decimals."
    PRD: "`showing_verdict` is `SUFFICIENT` when the rounded percentage is at least 30.00, and `INSUFFICIENT` otherwise; exactly 30.00 is sufficient, since the comparison is inclusive at the threshold."
    PRD: "Because the verdict is `INSUFFICIENT`, `case_status` becomes `DISMISSED`, which is terminal."

    Design: Difficulty/dual_variant_calc/soi_ratio_as_petitioned_denominator
    """
    ctx = setup_scope_analysis(
        clock=CLOCK,
        classification_specs=[PROD_SPEC, MAINT_SPEC, QC_SPEC, LEAD_SPEC],
    )
    petition = ctx["petition"]
    assert petition["total_classified_headcount"] == 110
    assert petition["pending_headcount"] == 110

    audited = _audit_cards(petition["id"], THIRTY_VALID_CARDS)

    assert_petition(audited)
    assert audited["valid_card_count"] == 30, (
        f"40 submitted less 3+2+2+3 struck is 30 valid cards, got {audited['valid_card_count']}"
    )
    assert audited["total_classified_headcount"] == 110
    assert audited["showing_headcount_basis"] == "AS_PETITIONED", (
        "an unruled classification forces the petitioned denominator, got "
        f"{audited['showing_headcount_basis']}"
    )
    assert audited["showing_of_interest_pct"] == pytest.approx(27.27, abs=0.005), (
        f"30 cards against 110 classified heads is 27.27, got {audited['showing_of_interest_pct']}"
    )
    assert audited["showing_verdict"] == "INSUFFICIENT"
    assert audited["case_status"] == "DISMISSED"


def test_a_single_unruled_classification_keeps_the_petitioned_denominator():
    """Ruling three of four classifications is not enough: the one classification
    still pending holds the denominator at the full classified roster of 110 rather
    than moving it to the 90 heads already ruled into the unit.

    PRD: "If at least one classification is still `PENDING`, or has become `MOOT`, the basis is `AS_PETITIONED` and the denominator is `total_classified_headcount`, because with scope unresolved the Board tests the showing against the unit as the petition described it — every classified head counts, including the ones the employer wants excluded."
    PRD: "`showing_of_interest_pct` is the valid card count multiplied by 100, divided by the selected denominator, rounded half-up to two decimals."

    Design: Difficulty/dual_variant_calc/soi_ratio_as_petitioned_denominator
    """
    ctx = setup_scope_analysis(
        clock=CLOCK,
        classification_specs=[PROD_SPEC, MAINT_SPEC, QC_SPEC, LEAD_SPEC],
    )
    prod, maint, qc, _lead = ctx["classifications"]
    score_and_rule(prod["id"], "INCLUDED")
    score_and_rule(maint["id"], "INCLUDED")
    score_and_rule(qc["id"], "EXCLUDED")

    before = read_petition(ctx["petition"]["id"])
    assert before["included_headcount"] == 90
    assert before["excluded_headcount"] == 12
    assert before["pending_headcount"] == 8, "the lead classification is still unruled"

    audited = _audit_cards(ctx["petition"]["id"], THIRTY_VALID_CARDS)

    assert_headcount_conservation(audited)
    assert audited["showing_headcount_basis"] == "AS_PETITIONED", (
        "one pending classification keeps the petitioned basis, got "
        f"{audited['showing_headcount_basis']}"
    )
    assert audited["showing_of_interest_pct"] == pytest.approx(27.27, abs=0.005), (
        "the denominator must be the 110 classified heads, not the 90 already included, "
        f"got {audited['showing_of_interest_pct']}"
    )
    assert audited["showing_verdict"] == "INSUFFICIENT"
    assert audited["case_status"] == "DISMISSED"


def _fully_ruled_case(rulings, specs=None):
    """A case in scope analysis whose every classification is scored and ruled."""
    ctx = setup_scope_analysis(
        clock=CLOCK,
        classification_specs=specs or [PROD_SPEC, MAINT_SPEC, QC_SPEC, LEAD_SPEC],
    )
    for classification, ruling in zip(ctx["classifications"], rulings):
        score_and_rule(classification["id"], ruling)
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    return ctx


def test_showing_of_interest_measured_against_the_included_headcount_once_scope_is_settled():
    """The identical 30-card audit that failed against the petitioned roster clears
    the threshold once every classification is ruled, because the denominator becomes
    the 90 heads ruled into the voting unit.

    PRD: "If every classification on the case has been ruled — that is, each one's `scope_ruling` is either `INCLUDED` or `EXCLUDED` — the basis is `AS_RULED` and the denominator is the case's `included_headcount`, because once scope is settled only the classifications actually inside the voting unit form the base."
    PRD: "`showing_of_interest_pct` is the valid card count multiplied by 100, divided by the selected denominator, rounded half-up to two decimals."
    PRD: "On a `SUFFICIENT` verdict the case advances from `SCOPE_ANALYSIS` to `SOI_VERIFIED`, writing `valid_card_count`, `showing_of_interest_pct`, `showing_headcount_basis` and `showing_verdict`."

    Design: Difficulty/dual_variant_calc/soi_ratio_as_ruled_denominator
    """
    ctx = _fully_ruled_case(["INCLUDED", "INCLUDED", "EXCLUDED", "EXCLUDED"])

    audited = _audit_cards(ctx["petition"]["id"], THIRTY_VALID_CARDS)

    assert_petition(audited)
    assert audited["included_headcount"] == 90
    assert audited["excluded_headcount"] == 20
    assert audited["pending_headcount"] == 0
    assert audited["valid_card_count"] == 30
    assert audited["showing_headcount_basis"] == "AS_RULED", (
        f"every classification is ruled, got {audited['showing_headcount_basis']}"
    )
    assert audited["showing_of_interest_pct"] == pytest.approx(33.33, abs=0.005), (
        f"30 cards against 90 included heads is 33.33, got {audited['showing_of_interest_pct']}"
    )
    assert audited["showing_verdict"] == "SUFFICIENT"
    assert audited["case_status"] == "SOI_VERIFIED"


def test_settled_scope_denominator_follows_the_included_headcount_not_the_roster_size():
    """A case whose every classification was ruled into the unit records the settled
    basis but keeps a 110-head denominator, so the same 30 cards fall short — the
    denominator tracks the included headcount rather than any fixed unit size.

    PRD: "If every classification on the case has been ruled — that is, each one's `scope_ruling` is either `INCLUDED` or `EXCLUDED` — the basis is `AS_RULED` and the denominator is the case's `included_headcount`, because once scope is settled only the classifications actually inside the voting unit form the base."
    PRD: "`showing_verdict` is `SUFFICIENT` when the rounded percentage is at least 30.00, and `INSUFFICIENT` otherwise; exactly 30.00 is sufficient, since the comparison is inclusive at the threshold."

    Design: Difficulty/dual_variant_calc/soi_ratio_as_ruled_denominator
    """
    ctx = _fully_ruled_case(["INCLUDED", "INCLUDED", "INCLUDED", "INCLUDED"])
    assert ctx["petition"]["included_headcount"] == 110
    assert ctx["petition"]["pending_headcount"] == 0

    audited = _audit_cards(ctx["petition"]["id"], THIRTY_VALID_CARDS)

    assert audited["showing_headcount_basis"] == "AS_RULED"
    assert audited["showing_of_interest_pct"] == pytest.approx(27.27, abs=0.005), (
        "30 cards against 110 included heads is 27.27, got "
        f"{audited['showing_of_interest_pct']}"
    )
    assert audited["showing_verdict"] == "INSUFFICIENT"
    assert audited["case_status"] == "DISMISSED"


def test_twenty_seven_valid_cards_against_ninety_included_heads_is_exactly_sufficient():
    """Twenty-seven valid cards measured against the 90 heads inside the voting unit
    lands exactly on the statutory threshold, and the threshold is inclusive.

    PRD: "For a case with 90 heads in the counted unit, 27 valid cards is exactly 30.00 and sufficient, while 26 valid cards is 28.89 and insufficient."
    PRD: "If every classification on the case has been ruled — that is, each one's `scope_ruling` is either `INCLUDED` or `EXCLUDED` — the basis is `AS_RULED` and the denominator is the case's `included_headcount`, because once scope is settled only the classifications actually inside the voting unit form the base."

    Design: Difficulty/dual_variant_calc/soi_ratio_as_ruled_denominator
    """
    ctx = _fully_ruled_case(["INCLUDED", "INCLUDED", "EXCLUDED", "EXCLUDED"])
    assert ctx["petition"]["included_headcount"] == 90

    audited = _audit_cards(ctx["petition"]["id"], TWENTY_SEVEN_VALID_CARDS)

    assert audited["valid_card_count"] == 27
    assert audited["showing_headcount_basis"] == "AS_RULED"
    assert audited["showing_of_interest_pct"] == pytest.approx(30.00, abs=0.005), (
        f"27 cards against 90 included heads is 30.00, got {audited['showing_of_interest_pct']}"
    )
    assert audited["showing_verdict"] == "SUFFICIENT", (
        "exactly 30.00 clears the inclusive threshold"
    )
    assert audited["case_status"] == "SOI_VERIFIED"


def _verified_case_with_arrangement():
    """A SOI_VERIFIED case carrying a proposed election arrangement."""
    ctx = _fully_ruled_case(["INCLUDED", "INCLUDED"], specs=[PROD_SPEC, MAINT_SPEC])
    ctx["petition"] = _audit_cards(ctx["petition"]["id"], THIRTY_VALID_CARDS)
    assert ctx["petition"]["case_status"] == "SOI_VERIFIED"
    ctx["agreement"] = create_election_agreement(ctx["petition"]["id"])
    return ctx


def test_directed_election_anchors_the_voter_list_deadline_on_the_decision_date():
    """A Decision and Direction of Election issued on 2026-08-27 but dated 2026-08-25
    puts the voter list due at the end of the second business day after the decision
    date, and schedules the first round of balloting.

    PRD: "Direction sets `route` to `DIRECTED` and computes `voter_list_due_at` as the end of the second business day after `decision_date`, which may be earlier or later than the instant the direction was actually recorded."
    PRD: "A decision dated Tuesday 2026-08-25 counts Wednesday the 26th and Thursday the 27th, giving `2026-08-27T23:59:59Z`."
    PRD: "As on the stipulated branch, an election round with `round_number` 1 and `status` `SCHEDULED` is created, and the case moves to `ELECTION_SET` with its `version` incremented."

    Design: Difficulty/dual_variant_calc/voter_list_deadline_directed_anchor
    """
    ctx = _verified_case_with_arrangement()
    request_hearing(ctx["agreement"]["id"], "EMPLOYER")
    set_clock("2026-08-27T10:00:00Z")

    directed = validate_success(api_client.direct_election(
        ctx["agreement"]["id"],
        {
            "decision_date": "2026-08-25",
            "approved_election_date": "2026-09-15",
            "voting_method": "MANUAL",
            "polls_open_at": "2026-09-15T06:00:00Z",
            "polls_close_at": "2026-09-15T17:00:00Z",
        },
        BOARD,
    ))

    assert_election_agreement(directed)
    assert directed["status"] == "DIRECTED"
    assert directed["route"] == "DIRECTED"
    assert_instant_equals(
        directed["voter_list_due_at"], "2026-08-27T23:59:59Z", "voter_list_due_at"
    )
    assert_instant_equals(
        directed["voter_list_due_at"],
        add_business_days("2026-08-25", 2),
        "voter_list_due_at anchored on the decision date",
    )

    petition = read_petition(ctx["petition"]["id"])
    assert petition["case_status"] == "ELECTION_SET"

    rounds = rounds_for_petition(ctx["petition"]["id"])
    assert len(rounds) == 1, f"direction schedules exactly one round, got {len(rounds)}"
    assert rounds[0]["round_number"] == 1
    assert rounds[0]["status"] == "SCHEDULED"


def test_stipulated_approval_anchors_the_voter_list_deadline_on_the_approval_instant():
    """On the same 2026-08-27 clock, a stipulated approval measures the two business
    days from the approval date itself, so the list falls due on 2026-08-31 rather
    than on the 2026-08-27 a decision dated 2026-08-25 would have produced.

    PRD: "Approval sets `route` to `STIPULATED` and computes `voter_list_due_at` as the end of the second business day after the date on which the approval itself happened — that is, the date component of the logical clock at approval, advanced by two business days, at 23:59:59Z."

    Design: Difficulty/dual_variant_calc/voter_list_deadline_directed_anchor
    """
    ctx = _verified_case_with_arrangement()
    set_clock("2026-08-27T10:00:00Z")

    approved = validate_success(api_client.stipulate_agreement(
        ctx["agreement"]["id"],
        {
            "approved_election_date": "2026-09-15",
            "voting_method": "MANUAL",
            "polls_open_at": "2026-09-15T06:00:00Z",
            "polls_close_at": "2026-09-15T17:00:00Z",
        },
        BOARD,
    ))

    assert_election_agreement(approved)
    assert approved["status"] == "STIPULATED_APPROVED"
    assert approved["route"] == "STIPULATED"
    assert_instant_equals(
        approved["voter_list_due_at"], "2026-08-31T23:59:59Z", "voter_list_due_at"
    )
    assert_instant_equals(
        approved["voter_list_due_at"],
        add_business_days("2026-08-27", 2),
        "voter_list_due_at anchored on the approval instant",
    )
    assert not approved["voter_list_due_at"].startswith("2026-08-27"), (
        "the stipulated branch must not anchor the deadline on a decision date"
    )


def test_demanding_a_hearing_defers_the_voter_list_deadline_and_schedules_no_round():
    """Refusing to stipulate records the hearing demand and stamps the request instant,
    but leaves the voter-list deadline unwritten and creates no round, because the
    deadline waits for the decision date.

    PRD: "The arrangement moves from `PROPOSED` to `HEARING_REQUESTED`, `hearing_requested_at` is stamped with the logical clock, and the party is recorded."
    PRD: "Nothing else happens: no election round is created and `voter_list_due_at` stays absent, because on this branch the deadline is deferred to the decision date rather than fixed at the approval instant."

    Design: Difficulty/dual_variant_calc/voter_list_deadline_directed_anchor
    """
    ctx = _verified_case_with_arrangement()

    requested = validate_success(api_client.request_hearing(
        ctx["agreement"]["id"], {"hearing_requested_by_party": "EMPLOYER"}, DIRECTOR
    ))

    assert_election_agreement(requested)
    assert requested["status"] == "HEARING_REQUESTED"
    assert requested["hearing_requested_by_party"] == "EMPLOYER"
    assert_instant_equals(requested["hearing_requested_at"], CLOCK, "hearing_requested_at")
    assert_absent(requested, "voter_list_due_at", "election_agreement")
    assert rounds_for_petition(ctx["petition"]["id"]) == [], (
        "the hearing branch schedules no balloting"
    )


QC_TWIN_SPEC = dict(QC_SPEC, code="QC2", title="Quality Control Inspector, Second Shift")
QC_DIVERGENT_SPEC = dict(
    QC_SPEC,
    code="QCX",
    title="Calibration Technician",
    avg_hourly_wage_cents=5000,
    skills_overlap=5,
    work_conditions_overlap=9,
)


def _scoring_case(specs=None):
    """A case in scope analysis whose classifications have not been scored yet."""
    return setup_scope_analysis(
        clock=CLOCK,
        classification_specs=specs or [PROD_SPEC, MAINT_SPEC, QC_SPEC],
    )


def _score(classification_id, standard):
    """Run the community-of-interest scoring under the named standard as counsel."""
    return validate_success(api_client.score_classification(
        classification_id, {"scoring_standard": standard}, COUNSEL
    ))


def test_traditional_standard_sums_six_individually_rounded_weighted_factors():
    """The first scoring call freezes the headcount-weighted core wage at 2667 cents,
    derives a wage proximity of 91.26 from it, and adds the six individually rounded
    weighted terms to a contested score of 50.68.

    PRD: "For that group, multiply each classification's `headcount` by its `avg_hourly_wage_cents`, sum those products, divide the sum by the total headcount of the group, and round half-up to a whole cent; the result is written to `core_avg_hourly_wage_cents` and the instant of the calculation is written to `core_wage_locked_at`."
    PRD: "Subtract the wage gap from 100.00 and floor the result at 0.00 to obtain `wage_proximity`, which therefore never goes negative even when the classification pays more than twice the core wage."
    PRD: "Under `TRADITIONAL`, each of the six factors is multiplied by its own weight — `supervision_overlap` by 0.325, `skills_overlap` by 0.225, `functional_integration` by 0.175, `interchange_rate` by 0.125, `work_conditions_overlap` by 0.100 and `wage_proximity` by 0.050 — **each product is rounded half-up to two decimals individually**, and only then are the six rounded terms added together to give `coi_score`."
    PRD: "Under `TRADITIONAL`, a score of at least 65 is `SHARED_COMMUNITY`, a score of at least 45 but below 65 is `CONTESTED_COMMUNITY`, and anything lower is `DISTINCT_COMMUNITY`."

    Design: Difficulty/combinatorial_formula/coi_mode_traditional_weighted_mean
    """
    ctx = _scoring_case()
    quality_control = ctx["classifications"][2]

    scored = _score(quality_control["id"], "TRADITIONAL")

    assert_classification(scored)
    petition = read_petition(ctx["petition"]["id"])
    assert petition["core_avg_hourly_wage_cents"] == 2667, (
        "the undisputed core group of 60 heads at 2400 and 30 heads at 3200 averages "
        f"2667 cents, got {petition['core_avg_hourly_wage_cents']}"
    )
    assert_instant_equals(petition["core_wage_locked_at"], CLOCK, "core_wage_locked_at")
    assert scored["wage_proximity"] == pytest.approx(91.26, abs=0.005), (
        f"2900 against a 2667-cent core wage is 91.26 proximate, got {scored['wage_proximity']}"
    )
    assert scored["coi_score"] == pytest.approx(50.68, abs=0.005), (
        "the six per-term-rounded weighted factors add to 50.68, got "
        f"{scored['coi_score']}"
    )
    assert scored["scoring_standard"] == "TRADITIONAL"
    assert scored["coi_recommendation"] == "CONTESTED_COMMUNITY"


def test_later_scoring_calls_reuse_the_frozen_core_wage_snapshot():
    """A second scoring call made a day later reads the core wage frozen by the first
    call rather than recomputing it, so the disputed classification still scores 50.68
    against a 91.26 wage proximity and the lock instant is untouched.

    PRD: "Every later scoring call on the case — including calls made after a scope ruling removed a classification from what would now be the core group, after a reconsideration put one back, and after a rerun was directed — reads the frozen `core_avg_hourly_wage_cents`, and `core_wage_locked_at` is never overwritten while it holds a value."
    PRD: "Take the absolute difference between the classification's own `avg_hourly_wage_cents` and the case's frozen core wage, multiply by 100, divide by the frozen core wage, and round half-up to two decimals; that is the wage gap as a percentage."

    Design: Difficulty/combinatorial_formula/coi_mode_traditional_weighted_mean
    """
    ctx = _scoring_case()
    production, _maintenance, quality_control = ctx["classifications"]

    _score(production["id"], "TRADITIONAL")
    first_lock = read_petition(ctx["petition"]["id"])
    assert first_lock["core_avg_hourly_wage_cents"] == 2667
    assert_instant_equals(first_lock["core_wage_locked_at"], CLOCK, "core_wage_locked_at")

    set_clock("2026-08-04T15:00:00Z")
    scored = _score(quality_control["id"], "TRADITIONAL")

    petition = read_petition(ctx["petition"]["id"])
    assert petition["core_avg_hourly_wage_cents"] == 2667, (
        "the frozen core wage must survive the second scoring call, got "
        f"{petition['core_avg_hourly_wage_cents']}"
    )
    assert_instant_equals(
        petition["core_wage_locked_at"], CLOCK, "core_wage_locked_at after a later call"
    )
    assert scored["wage_proximity"] == pytest.approx(91.26, abs=0.005), (
        "the wage gap is measured against the frozen 2667-cent core wage, got "
        f"{scored['wage_proximity']}"
    )
    assert scored["coi_score"] == pytest.approx(50.68, abs=0.005)
    assert scored["coi_recommendation"] == "CONTESTED_COMMUNITY"


def test_overwhelming_standard_anchors_the_score_on_the_weakest_factor():
    """Under the overwhelming standard the weighted total is averaged with the single
    smallest factor value — an interchange rate of 21 — pulling the score down to 35.84
    and the recommendation into the distinct-community band.

    PRD: "Under `OVERWHELMING`, that same weighted total is computed, then averaged with the single smallest of the six factor values: half the weighted total plus half the minimum factor value, rounded half-up to two decimals."
    PRD: "Under `OVERWHELMING` the two thresholds are 80 and 60."
    PRD: "That choice is a mode selector: it picks both the shape of the arithmetic and the bands that turn the resulting number into a recommendation, and it is echoed onto the classification so a later reader can see which standard produced the stored score."

    Design: Difficulty/combinatorial_formula/coi_mode_overwhelming_min_anchored
    """
    ctx = _scoring_case()
    quality_control = ctx["classifications"][2]

    scored = _score(quality_control["id"], "OVERWHELMING")

    assert_classification(scored)
    assert scored["wage_proximity"] == pytest.approx(91.26, abs=0.005)
    assert scored["coi_score"] == pytest.approx(35.84, abs=0.005), (
        "half the 50.68 weighted total plus half the weakest factor of 21 is 35.84, got "
        f"{scored['coi_score']}"
    )
    assert scored["scoring_standard"] == "OVERWHELMING"
    assert scored["coi_recommendation"] == "DISTINCT_COMMUNITY", (
        f"35.84 sits below the 60 band edge, got {scored['coi_recommendation']}"
    )


def test_overwhelming_and_traditional_standards_diverge_on_identical_factor_sets():
    """Two classifications carrying byte-identical factor sets and the same wage score
    50.68 as a contested community under the traditional standard but only 35.84 as a
    distinct community under the overwhelming one.

    PRD: "Under `TRADITIONAL`, each of the six factors is multiplied by its own weight — `supervision_overlap` by 0.325, `skills_overlap` by 0.225, `functional_integration` by 0.175, `interchange_rate` by 0.125, `work_conditions_overlap` by 0.100 and `wage_proximity` by 0.050 — **each product is rounded half-up to two decimals individually**, and only then are the six rounded terms added together to give `coi_score`."
    PRD: "Under `OVERWHELMING`, that same weighted total is computed, then averaged with the single smallest of the six factor values: half the weighted total plus half the minimum factor value, rounded half-up to two decimals."

    Design: Difficulty/combinatorial_formula/coi_mode_overwhelming_min_anchored
    """
    ctx = _scoring_case([PROD_SPEC, MAINT_SPEC, QC_SPEC, QC_TWIN_SPEC])
    quality_control, twin = ctx["classifications"][2], ctx["classifications"][3]

    under_overwhelming = _score(quality_control["id"], "OVERWHELMING")
    under_traditional = _score(twin["id"], "TRADITIONAL")

    assert under_overwhelming["wage_proximity"] == pytest.approx(91.26, abs=0.005)
    assert under_traditional["wage_proximity"] == pytest.approx(91.26, abs=0.005)
    assert under_overwhelming["coi_score"] == pytest.approx(35.84, abs=0.005)
    assert under_traditional["coi_score"] == pytest.approx(50.68, abs=0.005)
    assert under_overwhelming["coi_recommendation"] == "DISTINCT_COMMUNITY"
    assert under_traditional["coi_recommendation"] == "CONTESTED_COMMUNITY"
    assert under_overwhelming["coi_score"] < under_traditional["coi_score"], (
        "the weakest-link average must sit below the plain weighted total"
    )


def test_accretion_standard_scores_only_operational_integration():
    """Under the accretion standard the score is built from functional integration,
    interchange and supervision alone, giving exactly 42.00 and a contested-community
    recommendation on the accretion bands.

    PRD: "Under `ACCRETION`, wages, skills and working conditions are ignored entirely and only operational integration counts: 0.40 times `functional_integration`, plus 0.35 times `interchange_rate`, plus 0.25 times `supervision_overlap`, rounded half-up to two decimals."
    PRD: "**Step three** maps the score onto `coi_recommendation`, and the bands differ by standard."

    Design: Difficulty/combinatorial_formula/coi_mode_accretion_integration_only
    """
    ctx = _scoring_case()
    quality_control = ctx["classifications"][2]

    scored = _score(quality_control["id"], "ACCRETION")

    assert_classification(scored)
    assert scored["coi_score"] == pytest.approx(42.00, abs=0.005), (
        "0.40 of 61 plus 0.35 of 21 plus 0.25 of 41 is 42.00, got "
        f"{scored['coi_score']}"
    )
    assert scored["scoring_standard"] == "ACCRETION"
    assert scored["coi_recommendation"] == "CONTESTED_COMMUNITY", (
        f"42.00 sits at or above the 40 band edge and below 60, got {scored['coi_recommendation']}"
    )


def test_accretion_score_is_unmoved_by_skills_conditions_and_wage_proximity():
    """Two classifications sharing integration, interchange and supervision values but
    differing sharply in skills overlap, working conditions and wage both score exactly
    42.00 under the accretion standard, while each still carries its own wage proximity.

    PRD: "Under `ACCRETION`, wages, skills and working conditions are ignored entirely and only operational integration counts: 0.40 times `functional_integration`, plus 0.35 times `interchange_rate`, plus 0.25 times `supervision_overlap`, rounded half-up to two decimals."
    PRD: "Take the absolute difference between the classification's own `avg_hourly_wage_cents` and the case's frozen core wage, multiply by 100, divide by the frozen core wage, and round half-up to two decimals; that is the wage gap as a percentage."

    Design: Difficulty/combinatorial_formula/coi_mode_accretion_integration_only
    """
    ctx = _scoring_case([PROD_SPEC, MAINT_SPEC, QC_SPEC, QC_DIVERGENT_SPEC])
    quality_control, divergent = ctx["classifications"][2], ctx["classifications"][3]

    scored_qc = _score(quality_control["id"], "ACCRETION")
    scored_divergent = _score(divergent["id"], "ACCRETION")

    assert scored_qc["coi_score"] == pytest.approx(42.00, abs=0.005)
    assert scored_divergent["coi_score"] == pytest.approx(42.00, abs=0.005), (
        "skills overlap, working conditions and wage carry no weight under this standard, "
        f"got {scored_divergent['coi_score']}"
    )
    assert scored_qc["wage_proximity"] == pytest.approx(91.26, abs=0.005)
    assert scored_divergent["wage_proximity"] is not None, (
        "the derived wage factor is still computed and stored under this standard"
    )
    assert abs(scored_divergent["wage_proximity"] - scored_qc["wage_proximity"]) > 1, (
        "the two classifications must carry genuinely different wage proximities, "
        f"got {scored_divergent['wage_proximity']} and {scored_qc['wage_proximity']}"
    )
    assert scored_divergent["coi_recommendation"] == "CONTESTED_COMMUNITY"

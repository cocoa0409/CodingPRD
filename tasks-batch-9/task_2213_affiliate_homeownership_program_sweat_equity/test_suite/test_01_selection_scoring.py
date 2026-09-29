"""Applicant intake, documented screening, committee scoring, and the decision."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import ADMIN, COMMITTEE_ALICE, COMMITTEE_BRUNO, COORDINATOR


def test_screening_scores_the_self_reported_pair_on_the_preliminary_basis(api):
    """Screening scores the family's own statement, not the verified figures.

    "Screening also produces the household's first scores, computed on the
    **preliminary basis**, which reads the family's self-reported figures and
    ignores the verified ones even when they have just been written in the same
    request." With self-reported income 3,600,000 and housing 150,000 the cost
    burden ratio is 0.5000 for 40 points, overcrowding is 4 persons per bedroom
    for 30, and 3 documented deficiencies for 30, so `need_score` is 100, while
    `ami_pct` is 3,600,000 over 6,000,000, or 0.6.

    "`score_basis` is set to `PRELIMINARY`, `need_score`, `ability_to_pay_score`,
    and `ami_pct` are written, and `willingness_score` stays null — which means
    `composite_selection_score` stays null too, because the composite cannot be
    formed without a willingness figure."

    Design: Difficulty/dual_variant_calc/selection_scoring_preliminary_vs_final_income_basis
    """
    program = X.setup_program(api)
    household = X.setup_household(api, program["id"])
    X.add_member(api, household["id"])
    X.submit_household(api, household["id"])

    screened = validate_success(
        api.screen_household(household["id"], F.screen_payload(), headers=COORDINATOR)
    )

    assert screened["score_basis"] == C.BASIS_PRELIMINARY
    assert screened["need_score"] == 100
    assert screened["ability_to_pay_score"] == 100
    assert screened["ami_pct"] == 0.6
    assert screened["willingness_score"] is None
    assert screened["composite_selection_score"] is None
    # The verified pair was written by this same request but did not feed the score.
    assert screened["verified_annual_income_cents"] == 3_000_000
    assert screened["verified_housing_cost_cents"] == 100_000
    assert screened["documentation_status"] == C.DOC_VERIFIED


def test_the_selection_decision_overwrites_preliminary_scores_from_the_verified_pair(api):
    """The decision rescores on the final basis and overwrites wholesale.

    "The **final basis** is the same instrument fed from
    `verified_annual_income_cents` and `verified_housing_cost_cents` instead of
    the self-reported pair. Because verified figures routinely differ from what a
    family stated, the same row yields a different `need_score`, a different
    `ability_to_pay_score`, a different `ami_pct`, and often a different
    income-band verdict than the preliminary pass produced minutes earlier.
    Stored preliminary values are overwritten wholesale, never blended."

    On verified income 3,000,000 and housing 100,000 the cost burden ratio falls
    to 0.4000 for 30 points, so `need_score` becomes 90 and `ami_pct` becomes
    0.5. "Before branching, the household's scores are recomputed on the final
    basis and `score_basis` is set to `FINAL`, and `willingness_score` and
    `composite_selection_score` are written." The composite is 0.40 x 90 plus
    0.35 x 100 plus 0.25 x 80, or 91.0, which clears 70.00 with no veto present.

    Design: Difficulty/dual_variant_calc/selection_scoring_preliminary_vs_final_income_basis
    """
    program = X.setup_program(api)
    built = X.setup_referred_household(api, program["id"])
    household_id = built["household"]["id"]
    preliminary = validate_success(api.get_household(household_id, headers=COORDINATOR))
    assert preliminary["score_basis"] == C.BASIS_PRELIMINARY
    assert preliminary["need_score"] == 100
    assert preliminary["ami_pct"] == 0.6
    assert preliminary["composite_selection_score"] is None

    X.file_review_set(api, household_id, score=80)
    decided = validate_success(
        api.record_selection_decision(household_id, F.selection_decision_payload(), headers=ADMIN)
    )

    assert decided["score_basis"] == C.BASIS_FINAL
    assert decided["need_score"] == 90
    assert decided["ability_to_pay_score"] == 100
    assert decided["ami_pct"] == 0.5
    assert decided["willingness_score"] == 80.0
    assert decided["composite_selection_score"] == 91.0
    assert decided["selection_status"] == C.SELECTION_SELECTED


def test_a_screened_household_is_referred_only_with_verified_documentation(api):
    """Documentation completeness is checked before the income band at referral.

    "The household's `documentation_status` must be `VERIFIED`, or the referral
    is refused with `ERR_DOCUMENTATION_INCOMPLETE`." Position 13 of the rejection
    ladder is documentation completeness and position 14 is the area-median-income
    band, so a household that is both undocumented and out of band reports the
    documentation failure.

    Here `income_documents_received` is false, so documentation "remains at
    `SUBMITTED` unchanged" even though both verified figures were supplied, and
    the supplied verified income of 5,000,000 against an area median of 6,000,000
    would otherwise be an out-of-band 0.8333.

    Design: Corner/validations/documentation_gate_is_checked_before_the_ami_band_at_referral
    """
    program = X.setup_program(api)
    household = X.setup_household(api, program["id"])
    X.add_member(api, household["id"])
    X.submit_household(api, household["id"])
    screened = X.screen_household(
        api,
        household["id"],
        income_documents_received=False,
        verified_annual_income_cents=5_000_000,
        verified_housing_cost_cents=100_000,
    )
    assert screened["documentation_status"] == C.DOC_SUBMITTED

    response = api.refer_to_committee(household["id"], F.referral_payload(), headers=COORDINATOR)

    validate_error(response, E.ERR_DOCUMENTATION_INCOMPLETE, 409)
    still_screening = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert still_screening["selection_status"] == C.SELECTION_SCREENING


def test_the_income_band_accepts_both_bounds_and_refuses_one_cent_of_slack(api):
    """Both bounds of the area-median-income band are inclusive.

    "Its final-basis `ami_pct` must sit inside the affiliate's income band — at
    least 0.3000 and at most 0.8000, both bounds inclusive — or the referral is
    refused with `ERR_INCOME_OUT_OF_BAND`; a household at exactly 30% or exactly
    80% of area median income passes."

    Against an area median of 6,000,000 cents, verified income of 1,800,000 sits
    at exactly 0.3000 and 4,800,000 at exactly 0.8000, while 5,000,000 lands at
    0.8333 and is refused.

    Design: Corner/calculations/ami_band_accepts_both_boundaries_and_refuses_one_cent_of_slack
    """
    program = X.setup_program(api)

    def referred(verified_income_cents):
        household = X.setup_household(api, program["id"], household_name=f"HH-{verified_income_cents}")
        X.add_member(api, household["id"])
        X.submit_household(api, household["id"])
        X.screen_household(
            api,
            household["id"],
            verified_annual_income_cents=verified_income_cents,
            verified_housing_cost_cents=100_000,
        )
        return api.refer_to_committee(household["id"], F.referral_payload(), headers=COORDINATOR)

    at_floor = referred(1_800_000)
    floor_data = validate_success(at_floor)
    assert floor_data["selection_status"] == C.SELECTION_COMMITTEE_REVIEW

    at_ceiling = referred(4_800_000)
    ceiling_data = validate_success(at_ceiling)
    assert ceiling_data["selection_status"] == C.SELECTION_COMMITTEE_REVIEW

    over_ceiling = referred(5_000_000)
    validate_error(over_ceiling, E.ERR_INCOME_OUT_OF_BAND, 422)


def test_the_hour_requirement_freezes_from_the_adult_roster_at_referral(api):
    """The requirement is frozen at referral and does not move afterwards.

    "A successful referral freezes `sweat_equity_required_hours` for the
    remainder of the household's life: it is the program's
    `sweat_equity_base_hours_required` plus 50 hours for each adult occupant
    beyond the first (never a negative adjustment when `adult_occupant_count` is
    1), capped at 500 hours." With a 12-hour base and three adult occupants the
    frozen figure is 112.00.

    "Later changes to the program's base requirement or to the household's adult
    count do not move a frozen requirement", so adding a fourth adult afterwards
    raises `adult_occupant_count` while the requirement stays put.

    Design: Corner/entities/hour_requirement_and_adult_count_computed_from_member_roster
    """
    program = X.setup_program(api)
    built = X.setup_referred_household(
        api,
        program["id"],
        member_specs=[
            {},
            {"full_name": "Mateo Alvarez", "relationship": C.RELATIONSHIP_CO_APPLICANT,
             "birth_date": "1984-01-10T00:00:00.000Z", "is_adult_occupant": True},
            {"full_name": "Elena Alvarez", "relationship": C.RELATIONSHIP_EXTENDED_FAMILY,
             "birth_date": "1960-05-20T00:00:00.000Z", "is_adult_occupant": True},
            {"full_name": "Nico Alvarez", "relationship": C.RELATIONSHIP_DEPENDENT,
             "birth_date": "2015-02-02T00:00:00.000Z", "is_adult_occupant": False},
        ],
    )
    household = built["household"]
    assert household["adult_occupant_count"] == 3
    assert household["sweat_equity_required_hours"] == 112.0

    X.add_member(
        api,
        household["id"],
        full_name="Ruth Alvarez",
        relationship=C.RELATIONSHIP_FRIEND_OF_FAMILY,
        birth_date="1975-09-09T00:00:00.000Z",
        is_adult_occupant=True,
    )

    after = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert after["adult_occupant_count"] == 4
    assert after["sweat_equity_required_hours"] == 112.0


def test_a_documented_willingness_veto_denies_the_household_and_cascades(api):
    """A veto denies regardless of score, and denial cascades.

    "A composite strictly below 55.00, *or* the presence of any effective
    willingness veto regardless of score, sends the household to `DENIED`."
    "`denial_reason_code` is written as `WILLINGNESS_VETO` when a veto was the
    cause".

    "Denial then cascades across the household's other dimension and its
    children: `partnership_readiness` moves to `WITHDRAWN` no matter which
    readiness state it held, every `ACTIVE` member of the household flips to
    `REMOVED`, and every education enrollment of that household still in
    `ENROLLED` or `IN_PROGRESS` flips to `FAILED`."

    Design: Corner/state_machines/committee_denial_cascades_to_readiness_and_members
    """
    program = X.setup_program(api)
    built = X.setup_denied_household(
        api,
        program["id"],
        member_specs=[
            {},
            {"full_name": "Mateo Alvarez", "relationship": C.RELATIONSHIP_CO_APPLICANT,
             "birth_date": "1984-01-10T00:00:00.000Z", "is_adult_occupant": True},
            {"full_name": "Nico Alvarez", "relationship": C.RELATIONSHIP_DEPENDENT,
             "birth_date": "2015-02-02T00:00:00.000Z", "is_adult_occupant": False},
        ],
    )
    household = built["household"]

    assert household["selection_status"] == C.SELECTION_DENIED
    assert household["denial_reason_code"] == C.DENIAL_WILLINGNESS_VETO
    assert household["partnership_readiness"] == C.READINESS_WITHDRAWN

    members = validate_success(api.list_members({"household_id": household["id"]}, headers=COORDINATOR))
    assert len(members) == 3
    assert [member["status"] for member in members] == [C.MEMBER_REMOVED] * 3


def test_a_denied_household_reports_already_terminal_rather_than_illegal_transition(api):
    """A terminal selection dimension answers with the terminal error.

    Position 10 of the rejection ladder asks whether "The addressed row is in a
    state the requested transition declares as a legal origin for the dimension
    being moved" and position 11 asks whether "The dimension being moved is not
    already terminal — `ERR_ALREADY_TERMINAL` (409). The terminal values across
    the system are `DENIED`, `CLOSED`, `WITHDRAWN`, `COMPLETED`, `CANCELLED`,
    `NO_SHOW`, `SUPERSEDED`, `SATISFIED`, `RECAPTURED`, `FAILED`, and `EXPIRED`."

    "`DENIED` and `CLOSED` are the two terminal values of the selection
    dimension", so every later selection write on a denied file reports the
    terminal condition and never the illegal-origin one.

    Design: Corner/state_machines/denied_household_rejects_every_later_transition
    """
    program = X.setup_program(api)
    household = X.setup_denied_household(api, program["id"])["household"]
    household_id = household["id"]
    assert household["selection_status"] == C.SELECTION_DENIED

    validate_error(
        api.submit_household(household_id, F.submit_payload(), headers=COORDINATOR),
        E.ERR_ALREADY_TERMINAL,
        409,
    )
    validate_error(
        api.screen_household(household_id, F.screen_payload(), headers=COORDINATOR),
        E.ERR_ALREADY_TERMINAL,
        409,
    )
    validate_error(
        api.refer_to_committee(household_id, F.referral_payload(), headers=COORDINATOR),
        E.ERR_ALREADY_TERMINAL,
        409,
    )
    validate_error(
        api.return_to_screening(household_id, F.return_to_screening_payload(), headers=COORDINATOR),
        E.ERR_ALREADY_TERMINAL,
        409,
    )
    validate_error(
        api.record_selection_decision(household_id, F.selection_decision_payload(), headers=ADMIN),
        E.ERR_ALREADY_TERMINAL,
        409,
    )


def test_a_draft_household_cannot_skip_straight_to_screening_or_the_committee(api):
    """Each selection hop declares its own legal origin.

    Position 10 of the rejection ladder requires that "The addressed row is in a
    state the requested transition declares as a legal origin for the dimension
    being moved — `ERR_TRANSITION_NOT_ALLOWED` (409)."

    "Screening is the coordinator's documented verification pass and moves the
    file from `SUBMITTED` to `SCREENING`", and "Referring a screened household to
    the committee moves it from `SCREENING` to `COMMITTEE_REVIEW`", so neither is
    reachable from `DRAFT`.

    Design: Corner/state_machines/draft_household_rejects_screening_and_committee_hops
    """
    program = X.setup_program(api)
    household = X.setup_household(api, program["id"])
    X.add_member(api, household["id"])
    assert household["selection_status"] == C.SELECTION_DRAFT

    validate_error(
        api.screen_household(household["id"], F.screen_payload(), headers=COORDINATOR),
        E.ERR_TRANSITION_NOT_ALLOWED,
        409,
    )
    validate_error(
        api.refer_to_committee(household["id"], F.referral_payload(), headers=COORDINATOR),
        E.ERR_TRANSITION_NOT_ALLOWED,
        409,
    )
    validate_error(
        api.record_selection_decision(household["id"], F.selection_decision_payload(), headers=ADMIN),
        E.ERR_TRANSITION_NOT_ALLOWED,
        409,
    )
    unchanged = validate_success(api.get_household(household["id"], headers=COORDINATOR))
    assert unchanged["selection_status"] == C.SELECTION_DRAFT
    assert unchanged["documentation_status"] == C.DOC_INCOMPLETE


def test_a_second_submit_and_a_second_readiness_step_are_both_refused(api):
    """A hop that has already been taken is no longer a legal origin.

    "Submission moves the file from `DRAFT` to `SUBMITTED`", so a second
    submission has no legal origin left. On the construction side "A `step` of
    `TITLE` moves the site `RAW_LAND → TITLE_CLEAR` and sets `title_cleared`, and
    is only available while `title_cleared` is still false."

    Design: Corner/state_machines/repeated_submit_and_repeated_readiness_step_rejected
    """
    program = X.setup_program(api)
    household = X.setup_household(api, program["id"])
    X.add_member(api, household["id"])
    submitted = X.submit_household(api, household["id"])
    assert submitted["selection_status"] == C.SELECTION_SUBMITTED

    validate_error(
        api.submit_household(household["id"], F.submit_payload(), headers=COORDINATOR),
        E.ERR_TRANSITION_NOT_ALLOWED,
        409,
    )

    site = X.setup_title_clear_site(api, program["id"])
    assert site["readiness_status"] == C.SITE_TITLE_CLEAR
    assert site["title_cleared"] is True
    validate_error(
        api.advance_readiness(site["id"], F.readiness_payload(C.STEP_TITLE), headers=ADMIN),
        E.ERR_TRANSITION_NOT_ALLOWED,
        409,
    )


def test_returning_to_screening_clears_the_final_scores_but_keeps_the_reviews(api):
    """The committee does not re-score a file whose paperwork was incomplete.

    "That regression clears `composite_selection_score` and `willingness_score`
    to null and resets `score_basis` to `PRELIMINARY`, but it deliberately
    leaves every `SUBMITTED` review untouched, so quorum survives the loop and
    the committee does not have to re-score a family whose paperwork was merely
    incomplete. The `COMMITTEE_REVIEW → SCREENING → COMMITTEE_REVIEW` cycle may
    repeat without bound."

    Design: Corner/state_machines/return_to_screening_clears_final_scores_but_keeps_reviews
    """
    program = X.setup_program(api)
    built = X.setup_referred_household(api, program["id"])
    household_id = built["household"]["id"]
    X.file_review_set(api, household_id, score=80)

    regressed = validate_success(
        api.return_to_screening(household_id, F.return_to_screening_payload(), headers=COORDINATOR)
    )
    assert regressed["selection_status"] == C.SELECTION_SCREENING
    assert regressed["score_basis"] == C.BASIS_PRELIMINARY
    assert regressed["composite_selection_score"] is None
    assert regressed["willingness_score"] is None
    # The documented screening pass and the frozen requirement both survive.
    assert regressed["documentation_status"] == C.DOC_VERIFIED
    assert regressed["sweat_equity_required_hours"] == 12.0

    surviving = validate_success(
        api.list_reviews({"household_id": household_id, "status": C.REVIEW_SUBMITTED}, headers=ADMIN)
    )
    assert len(surviving) == 6

    X.refer_household(api, household_id)
    decided = X.decide_selection(api, household_id)
    assert decided["selection_status"] == C.SELECTION_SELECTED
    assert decided["score_basis"] == C.BASIS_FINAL
    assert decided["willingness_score"] == 80.0
    assert decided["composite_selection_score"] == 91.0


def test_a_reviewer_holds_one_submitted_review_per_dimension_and_a_veto_needs_its_reason(api):
    """Duplicate reviews and undocumented vetoes are both refused.

    "A reviewer may hold at most one `SUBMITTED` review per household per
    dimension; filing a second one is refused with `ERR_DUPLICATE_REVIEW`, and
    the existing one must be retracted first."

    "A `VETO_WILLINGNESS` recommendation is only meaningful on the willingness
    dimension and only with its rationale on the record: a veto whose
    `documented_reason` is missing or shorter than 10 characters, or a veto filed
    on the `NEED` or `ABILITY` dimension, is refused with
    `ERR_VETO_REASON_REQUIRED`."

    "Retraction moves a review from `SUBMITTED` to `RETRACTED`, carries a
    `retraction_reason`, and removes the row from every quorum count, every score
    aggregate, and the veto test", which is what lets the same reviewer refile.

    Design: Corner/validations/duplicate_review_and_veto_documentation_rules_on_reviews
    """
    program = X.setup_program(api)
    built = X.setup_referred_household(api, program["id"])
    household_id = built["household"]["id"]

    first = validate_success(
        api.create_review(F.review_payload(household_id, C.DIMENSION_NEED, 80), headers=COMMITTEE_ALICE), 201
    )
    validate_error(
        api.create_review(F.review_payload(household_id, C.DIMENSION_NEED, 70), headers=COMMITTEE_ALICE),
        E.ERR_DUPLICATE_REVIEW,
        409,
    )

    undocumented_veto = F.review_payload(
        household_id, C.DIMENSION_WILLINGNESS, 20, recommendation=C.RECOMMENDATION_VETO
    )
    validate_error(api.create_review(undocumented_veto, headers=COMMITTEE_BRUNO), E.ERR_VETO_REASON_REQUIRED, 422)

    misplaced_veto = F.review_payload(
        household_id,
        C.DIMENSION_NEED,
        20,
        recommendation=C.RECOMMENDATION_VETO,
        documented_reason="Documented rationale for the veto on the record",
    )
    validate_error(api.create_review(misplaced_veto, headers=COMMITTEE_BRUNO), E.ERR_VETO_REASON_REQUIRED, 422)

    retracted = validate_success(
        api.retract_review(first["id"], F.retraction_payload(), headers=COMMITTEE_ALICE)
    )
    assert retracted["status"] == C.REVIEW_RETRACTED

    refiled = validate_success(
        api.create_review(F.review_payload(household_id, C.DIMENSION_NEED, 60), headers=COMMITTEE_ALICE), 201
    )
    assert refiled["score"] == 60
    assert refiled["status"] == C.REVIEW_SUBMITTED

    need_reviews = validate_success(
        api.list_reviews({"household_id": household_id, "dimension": C.DIMENSION_NEED}, headers=ADMIN)
    )
    assert len(need_reviews) == 2

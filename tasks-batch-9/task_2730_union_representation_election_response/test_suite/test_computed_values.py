"""Derived values the case record computes for itself.

Covers the frozen core-wage snapshot behind every community-of-interest score,
the statutory supervisory override, the six ordered voter-eligibility rules and
the statutory-content grading that follows them, the additive campaign risk
score and its ceiling, the provisional and revised ballot tallies, the
business-day deadline calendar, and the two disjoint certification timelines.
"""
from test_helpers import (
    ANALYST,
    COUNSEL,
    DIRECTOR,
    ApiErrorId,
    add_business_days,
    add_classification,
    add_voter_entry,
    api_client,
    assert_absent,
    assert_ballot_conservation,
    assert_headcount_conservation,
    assert_instant_equals,
    assert_instants_equal,
    certify_petition,
    close_poll_session,
    create_campaign_communication_payload,
    create_election_agreement,
    create_petition,
    create_poll_session,
    create_trained_supervisor,
    create_voter_list,
    create_voter_list_entry_payload,
    latest_round,
    open_polls,
    open_scope_analysis,
    plus_days,
    plus_hours,
    post_tally,
    read_petition,
    read_round,
    read_voter_list,
    resolve_ballot,
    review_voter_list,
    revise_tally,
    rule_classification,
    score_classification,
    segregate_ballot,
    set_clock,
    stipulate_agreement,
    submit_voter_list,
    validate_error,
    validate_success,
    verify_showing,
)

# The logical clock instants this file drives the case through.
DOCKET_CLOCK = "2026-08-03T09:00:00Z"
APPROVAL_CLOCK = "2026-08-20T15:00:00Z"
LIST_FILED_CLOCK = "2026-08-21T10:00:00Z"
LIST_REVIEW_CLOCK = "2026-08-21T18:00:00Z"
POLLS_CLOSE_CLOCK = "2026-09-01T17:30:00Z"
TALLY_CLOCK = "2026-09-02T12:00:00Z"
CERTIFY_CLOCK = "2026-09-15T09:00:00Z"

PAYROLL_PERIOD_END = "2026-08-14"
ELECTION_DATE = "2026-09-01"
POLLS_OPEN_AT = "2026-09-01T06:00:00Z"
POLLS_CLOSE_AT = "2026-09-01T17:00:00Z"

# Two classifications nobody argues about: both parties say INCLUDE.
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
# The employer wants the lab out, so QC never joins the undisputed core.
QC_SPEC = {
    "code": "QC", "title": "Quality Inspector", "headcount": 12,
    "avg_hourly_wage_cents": 2900, "shift_code": "B", "work_location": "PLANT_1_LAB",
    "supervisory_authority_count": 0, "employer_position": "EXCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 41, "skills_overlap": 55,
    "functional_integration": 61, "interchange_rate": 21, "work_conditions_overlap": 71,
}
# Four indicia of statutory supervisory authority ride on the lead operators.
LEAD_SPEC = {
    "code": "LEAD", "title": "Lead Operator", "headcount": 8,
    "avg_hourly_wage_cents": 2800, "shift_code": "A", "work_location": "PLANT_1",
    "supervisory_authority_count": 4, "employer_position": "EXCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 78, "skills_overlap": 82,
    "functional_integration": 80, "interchange_rate": 66, "work_conditions_overlap": 88,
}

# 40 submitted cards less 3 duplicate, 2 undated, 2 stale and 3 non-unit cards.
THIRTY_VALID_CARDS = {
    "submitted_card_count": 40, "duplicate_card_count": 3, "undated_card_count": 2,
    "stale_card_count": 2, "nonunit_card_count": 3,
}
# 60 clean cards, none struck.
SIXTY_VALID_CARDS = {
    "submitted_card_count": 60, "duplicate_card_count": 0, "undated_card_count": 0,
    "stale_card_count": 0, "nonunit_card_count": 0,
}


# --------------------------------------------------------------------------
# Case-building helpers. Every test rebuilds its own case from an empty
# database, so these assemble the shared arcs the calculations sit on.
# --------------------------------------------------------------------------
def _open_case(case_number, petition_type="RC"):
    """Docket a case and move it into scope analysis at the docketing clock."""
    set_clock(DOCKET_CLOCK)
    petition = create_petition(
        case_number=case_number,
        petition_type=petition_type,
        payroll_period_end=PAYROLL_PERIOD_END,
    )
    return open_scope_analysis(petition["id"])


def _approve_stipulated_election(petition_id, card_counts):
    """Verify the showing, then have the parties stipulate to a manual election."""
    verify_showing(petition_id, **card_counts)
    agreement = create_election_agreement(petition_id, proposed_election_date=ELECTION_DATE)
    set_clock(APPROVAL_CLOCK)
    return stipulate_agreement(
        agreement["id"],
        approved_election_date=ELECTION_DATE,
        voting_method="MANUAL",
        polls_open_at=POLLS_OPEN_AT,
        polls_close_at=POLLS_CLOSE_AT,
    )


def _case_with_disputed_lab(case_number):
    """PROD and MAINT agreed on both sides; the quality lab is disputed."""
    petition = _open_case(case_number)
    rows = {}
    for spec in (PROD_SPEC, MAINT_SPEC, QC_SPEC):
        rows[spec["code"]] = add_classification(petition["id"], **spec)
    return petition, rows


def _two_included_classifications(petition_id):
    """Score and rule the production and maintenance groups into the unit."""
    prod = add_classification(petition_id, **PROD_SPEC)
    maint = add_classification(petition_id, **MAINT_SPEC)
    score_classification(prod["id"])
    score_classification(maint["id"])
    rule_classification(prod["id"], "INCLUDED", "The core production group of the plant.")
    rule_classification(maint["id"], "INCLUDED", "Mechanics are integrated with production.")
    return prod, maint


def _accepted_voter_list(petition_id, agreement_id, classification_ids):
    """A three-entry list, complete and filed on time, accepted by the agent."""
    voter_list = create_voter_list(petition_id, agreement_id)
    names = ("Dana Ruiz", "Ivo Marek", "Petra Nagy")
    entries = []
    for index, name in enumerate(names):
        entries.append(
            add_voter_entry(
                voter_list["id"],
                classification_ids[index % len(classification_ids)],
                full_name=name,
                personal_email=f"voter{index + 1}@example.com",
            )
        )
    set_clock(LIST_FILED_CLOCK)
    submit_voter_list(voter_list["id"])
    review_voter_list(voter_list["id"], "ACCEPT")
    return voter_list, entries


def _arc_to_tally_posted(case_number, petition_type="RC"):
    """Run a case all the way to a posted provisional tally with three challenges.

    Two sessions close 30/25/1 and 12/14/0 and three ballots are segregated, so
    the provisional figures are 42 for, 39 against and 1 void out of 85 ballots.
    """
    petition = _open_case(case_number, petition_type)
    prod, maint = _two_included_classifications(petition["id"])
    agreement = _approve_stipulated_election(petition["id"], THIRTY_VALID_CARDS)
    round_row = latest_round(petition["id"])
    voter_list, entries = _accepted_voter_list(
        petition["id"], agreement["id"], [prod["id"], prod["id"], maint["id"]]
    )
    session_one = create_poll_session(
        round_row["id"], location_code="PLANT_1_CAFETERIA",
        session_start_at=POLLS_OPEN_AT, session_end_at=POLLS_CLOSE_AT, method="MANUAL",
    )
    session_two = create_poll_session(
        round_row["id"], location_code="PLANT_2_BREAKROOM",
        session_start_at=POLLS_OPEN_AT, session_end_at=POLLS_CLOSE_AT, method="MANUAL",
    )
    set_clock(POLLS_OPEN_AT)
    open_polls(round_row["id"])
    ballots = [
        segregate_ballot(
            session_one["id"], voter_list_entry_id=entries[0]["id"],
            challenger_party="EMPLOYER", basis="SUPERVISOR",
        ),
        segregate_ballot(
            session_one["id"], voter_list_entry_id=entries[1]["id"],
            challenger_party="UNION", basis="NOT_ON_LIST",
        ),
        segregate_ballot(
            session_two["id"], voter_list_entry_id=entries[2]["id"],
            challenger_party="EMPLOYER", basis="OUTSIDE_UNIT",
        ),
    ]
    set_clock(POLLS_CLOSE_CLOCK)
    close_poll_session(session_one["id"], votes_for_count=30, votes_against_count=25, void_count=1)
    close_poll_session(session_two["id"], votes_for_count=12, votes_against_count=14, void_count=0)
    set_clock(TALLY_CLOCK)
    posted = post_tally(round_row["id"])
    return {
        "petition": petition,
        "agreement": agreement,
        "round": posted,
        "voter_list": voter_list,
        "entries": entries,
        "ballots": ballots,
        "sessions": [session_one, session_two],
    }


# --------------------------------------------------------------------------
# The frozen core wage behind every community-of-interest score
# --------------------------------------------------------------------------
def test_core_wage_snapshot_is_the_headcount_weighted_average_of_the_undisputed_core():
    """The first score on a case freezes the weighted average wage of the classifications
    both parties agree belong in the unit, and stamps the instant it did so.

    PRD: "The undisputed core group is the set of classifications on the case where `employer_position` and `union_position` are both `INCLUDE` — the classifications nobody is arguing about."

    PRD: "For that group, multiply each classification's `headcount` by its `avg_hourly_wage_cents`, sum those products, divide the sum by the total headcount of the group, and round half-up to a whole cent; the result is written to `core_avg_hourly_wage_cents` and the instant of the calculation is written to `core_wage_locked_at`."

    Design: Corner/calculations/core_wage_snapshot_freezes_on_the_first_score_call
    """
    petition, rows = _case_with_disputed_lab("07-RC-338101")

    score_classification(rows["PROD"]["id"], "TRADITIONAL", COUNSEL)

    frozen = read_petition(petition["id"])
    # 60 x 2400 plus 30 x 3200 over 90 heads is 2666.67, rounded half-up to 2667.
    # The disputed quality lab pays 2900 and would have lifted this to 2694.
    assert frozen["core_avg_hourly_wage_cents"] == 2667, (
        "core_avg_hourly_wage_cents must be the headcount-weighted average of the "
        f"undisputed core only, got {frozen['core_avg_hourly_wage_cents']}"
    )
    assert_instant_equals(frozen["core_wage_locked_at"], DOCKET_CLOCK, "core_wage_locked_at")


def test_core_wage_stays_frozen_when_a_later_classification_is_scored():
    """A classification added and scored after the snapshot reads the frozen wage, and the
    lock instant is not rewritten.

    PRD: "Every later scoring call on the case — including calls made after a scope ruling removed a classification from what would now be the core group, after a reconsideration put one back, and after a rerun was directed — reads the frozen `core_avg_hourly_wage_cents`, and `core_wage_locked_at` is never overwritten while it holds a value."

    PRD: "Subtract the wage gap from 100.00 and floor the result at 0.00 to obtain `wage_proximity`, which therefore never goes negative even when the classification pays more than twice the core wage."

    Design: Corner/calculations/core_wage_snapshot_freezes_on_the_first_score_call
    """
    petition, rows = _case_with_disputed_lab("07-RC-338102")
    score_classification(rows["PROD"]["id"], "TRADITIONAL", COUNSEL)
    after_first_score = read_petition(petition["id"])

    lead = add_classification(petition["id"], **LEAD_SPEC)
    scored_lead = score_classification(lead["id"], "TRADITIONAL", COUNSEL)

    frozen = read_petition(petition["id"])
    assert frozen["core_avg_hourly_wage_cents"] == 2667, (
        "the frozen core wage must survive a later scoring call, got "
        f"{frozen['core_avg_hourly_wage_cents']}"
    )
    assert_instants_equal(
        frozen["core_wage_locked_at"], after_first_score["core_wage_locked_at"],
        "core_wage_locked_at",
    )
    # |2800 - 2667| x 100 / 2667 is a 4.99% gap against the frozen wage.
    assert scored_lead["wage_proximity"] == 95.01, (
        f"wage_proximity must be derived from the frozen core wage, got {scored_lead['wage_proximity']}"
    )
    assert frozen["total_classified_headcount"] == 110
    assert frozen["pending_headcount"] == 110
    assert_headcount_conservation(frozen)


# --------------------------------------------------------------------------
# The statutory supervisory override
# --------------------------------------------------------------------------
def test_supervisory_authority_overrides_the_shared_community_band():
    """A group carrying statutory supervisory authority is recommended for exclusion however
    high its score, and the score itself is still recorded.

    PRD: "If the classification's `supervisory_authority_count` is 1 or more, `coi_recommendation` becomes `MANDATORY_EXCLUSION` regardless of which band the score fell in — a single indicium of Section 2(11) authority is enough."

    PRD: "The computed `coi_score` is still stored in that case; only the recommendation is overridden."

    Design: Corner/calculations/supervisory_authority_forces_mandatory_exclusion_after_banding
    """
    petition, rows = _case_with_disputed_lab("07-RC-338103")
    score_classification(rows["PROD"]["id"], "TRADITIONAL", COUNSEL)
    lead = add_classification(petition["id"], **LEAD_SPEC)

    scored = score_classification(lead["id"], "TRADITIONAL", COUNSEL)

    assert scored["wage_proximity"] == 95.01
    # 25.35 + 18.45 + 14.00 + 8.25 + 8.80 + 4.75, each term rounded before the sum.
    assert scored["coi_score"] == 79.60, (
        f"coi_score must still be stored under the override, got {scored['coi_score']}"
    )
    assert scored["coi_recommendation"] == "MANDATORY_EXCLUSION", (
        "four indicia of supervisory authority must force MANDATORY_EXCLUSION, got "
        f"{scored['coi_recommendation']}"
    )
    assert scored["coi_recommendation"] != "SHARED_COMMUNITY"
    assert scored["scoring_standard"] == "TRADITIONAL"
    assert scored["scope_ruling"] == "PENDING", "scoring must not decide the scope question"


def test_a_group_without_supervisory_authority_keeps_the_band_its_score_earned():
    """The same score with no supervisory indicia stays in the band the mapping produced.

    PRD: "A classification with a `supervisory_authority_count` of exactly 0 keeps whatever band mapping produced."

    PRD: "Under `TRADITIONAL`, a score of at least 65 is `SHARED_COMMUNITY`, a score of at least 45 but below 65 is `CONTESTED_COMMUNITY`, and anything lower is `DISTINCT_COMMUNITY`."

    Design: Corner/calculations/supervisory_authority_forces_mandatory_exclusion_after_banding
    """
    petition, rows = _case_with_disputed_lab("07-RC-338104")
    score_classification(rows["PROD"]["id"], "TRADITIONAL", COUNSEL)
    unsupervised_lead = dict(LEAD_SPEC, code="LEADB", supervisory_authority_count=0)
    lead = add_classification(petition["id"], **unsupervised_lead)

    scored = score_classification(lead["id"], "TRADITIONAL", COUNSEL)

    assert scored["coi_score"] == 79.60
    assert scored["coi_recommendation"] == "SHARED_COMMUNITY", (
        "with no supervisory authority the band mapping stands, got "
        f"{scored['coi_recommendation']}"
    )


def test_first_score_without_an_undisputed_core_is_refused():
    """With every classification in dispute there is no core to freeze, so the first score
    fails and nothing is written.

    PRD: "If no classification on the case has both positions set to `INCLUDE`, there is no core group, the first scoring call fails with `ERR_NO_UNDISPUTED_CORE` (HTTP 422), and nothing at all is frozen."

    PRD: "A new classification starts with `scope_ruling` `PENDING` and no `ruling_rationale`, and its `wage_proximity`, `coi_score`, `scoring_standard` and `coi_recommendation` are all absent until it is scored."

    Design: Corner/calculations/first_score_without_an_undisputed_core_is_rejected
    """
    petition = _open_case("07-RC-338105")
    disputed = add_classification(petition["id"], **QC_SPEC)

    resp = api_client.score_classification(
        disputed["id"], {"scoring_standard": "TRADITIONAL"}, COUNSEL
    )

    validate_error(resp, ApiErrorId.ERR_NO_UNDISPUTED_CORE)
    unfrozen = read_petition(petition["id"])
    assert_absent(unfrozen, "core_avg_hourly_wage_cents", "petition")
    assert_absent(unfrozen, "core_wage_locked_at", "petition")
    unscored = validate_success(api_client.get_classification(disputed["id"], DIRECTOR))
    assert_absent(unscored, "coi_score", "classification")
    assert_absent(unscored, "wage_proximity", "classification")
    assert_absent(unscored, "coi_recommendation", "classification")
    assert unscored["scope_ruling"] == "PENDING"


# --------------------------------------------------------------------------
# The six ordered voter-eligibility rules
# --------------------------------------------------------------------------
def _case_with_one_unruled_group(case_number):
    """A stipulated case whose lab is out, whose leads are still unruled, and a fresh list.

    PROD and MAINT are ruled into the unit, QC is ruled out, and the lead operators
    are added after the scoring pass so they are never scored and stay unruled.
    """
    petition = _open_case(case_number)
    rows = {}
    for spec in (PROD_SPEC, MAINT_SPEC, QC_SPEC):
        rows[spec["code"]] = add_classification(petition["id"], **spec)
    for code in ("PROD", "MAINT", "QC"):
        score_classification(rows[code]["id"], "TRADITIONAL", COUNSEL)
    rows["LEAD"] = add_classification(petition["id"], **LEAD_SPEC)
    rule_classification(rows["PROD"]["id"], "INCLUDED", "The core production group of the plant.")
    rule_classification(rows["MAINT"]["id"], "INCLUDED", "Mechanics are integrated with production.")
    rule_classification(rows["QC"]["id"], "EXCLUDED", "The lab reports outside the plant chain.")
    agreement = _approve_stipulated_election(petition["id"], SIXTY_VALID_CARDS)
    voter_list = create_voter_list(petition["id"], agreement["id"])
    return {"petition": petition, "rows": rows, "agreement": agreement, "voter_list": voter_list}


def _add_entry(voter_list_id, classification_id, **fields):
    """Put one voter on a list and confirm the create answered with a created row."""
    resp = api_client.create_voter_list_entry(
        create_voter_list_entry_payload(voter_list_id, classification_id, **fields), ANALYST
    )
    return validate_success(resp, 201)


def test_a_voter_in_an_excluded_classification_is_ineligible_as_outside_the_unit():
    """Rule one takes a voter out of the electorate when the job classification was ruled
    out of the unit.

    PRD: "First, if the voter's classification has a `scope_ruling` of `EXCLUDED`, the entry is `INELIGIBLE` with `ineligibility_reason` `OUTSIDE_UNIT`."

    Design: Corner/calculations/voter_eligibility_applies_its_six_rules_in_declared_order
    """
    ctx = _case_with_one_unruled_group("07-RC-338110")

    entry = _add_entry(
        ctx["voter_list"]["id"], ctx["rows"]["QC"]["id"],
        full_name="Lena Ortiz", hire_date="2024-05-02",
        personal_email="lena.ortiz@example.com",
    )

    assert entry["eligibility_status"] == "INELIGIBLE"
    assert entry["ineligibility_reason"] == "OUTSIDE_UNIT"


def test_an_excluded_classification_outranks_a_late_hire_date():
    """A voter who is both outside the unit and hired late reports the earlier rule.

    PRD: "Because rule one precedes rule two, a voter who sits in an `EXCLUDED` classification *and* was hired late reports `OUTSIDE_UNIT`, not `HIRED_AFTER_PAYROLL_PERIOD`."

    Design: Corner/calculations/voter_eligibility_applies_its_six_rules_in_declared_order
    """
    ctx = _case_with_one_unruled_group("07-RC-338111")

    entry = _add_entry(
        ctx["voter_list"]["id"], ctx["rows"]["QC"]["id"],
        full_name="Lena Ortiz", hire_date="2026-08-15",
        personal_email="lena.ortiz@example.com",
    )

    assert entry["eligibility_status"] == "INELIGIBLE"
    assert entry["ineligibility_reason"] == "OUTSIDE_UNIT", (
        "rule one wins over rule two, got " f"{entry['ineligibility_reason']}"
    )


def test_a_voter_hired_after_the_payroll_period_is_ineligible():
    """Rule two excludes a voter hired the day after the eligibility payroll period closed.

    PRD: "Second, if `hire_date` falls after the case's `payroll_period_end`, the entry is `INELIGIBLE` with reason `HIRED_AFTER_PAYROLL_PERIOD`."

    Design: Corner/calculations/voter_eligibility_applies_its_six_rules_in_declared_order
    """
    ctx = _case_with_one_unruled_group("07-RC-338112")

    entry = _add_entry(
        ctx["voter_list"]["id"], ctx["rows"]["PROD"]["id"],
        full_name="Nils Haugen", hire_date="2026-08-15",
        personal_email="nils.haugen@example.com",
    )

    assert entry["eligibility_status"] == "INELIGIBLE"
    assert entry["ineligibility_reason"] == "HIRED_AFTER_PAYROLL_PERIOD"


def test_a_voter_terminated_before_the_election_is_ineligible():
    """Rule three excludes a voter whose last day fell before the approved election date.

    PRD: "Third, if `termination_date` is present and falls before the arrangement's `approved_election_date`, the entry is `INELIGIBLE` with reason `TERMINATED_BEFORE_ELECTION`."

    Design: Corner/calculations/voter_eligibility_applies_its_six_rules_in_declared_order
    """
    ctx = _case_with_one_unruled_group("07-RC-338113")

    entry = _add_entry(
        ctx["voter_list"]["id"], ctx["rows"]["PROD"]["id"],
        full_name="Omar Diallo", hire_date="2023-11-06",
        termination_date="2026-08-31", personal_email="omar.diallo@example.com",
    )

    assert entry["eligibility_status"] == "INELIGIBLE"
    assert entry["ineligibility_reason"] == "TERMINATED_BEFORE_ELECTION"


def test_a_voter_on_permanent_layoff_is_ineligible():
    """Rule four excludes a voter on permanent layoff.

    PRD: "Fourth, if `on_leave_type` is `PERMANENT_LAYOFF`, the entry is `INELIGIBLE` with reason `PERMANENT_LAYOFF`."

    Design: Corner/calculations/voter_eligibility_applies_its_six_rules_in_declared_order
    """
    ctx = _case_with_one_unruled_group("07-RC-338114")

    entry = _add_entry(
        ctx["voter_list"]["id"], ctx["rows"]["PROD"]["id"],
        full_name="Priya Anand", hire_date="2022-02-14",
        on_leave_type="PERMANENT_LAYOFF", personal_email="priya.anand@example.com",
    )

    assert entry["eligibility_status"] == "INELIGIBLE"
    assert entry["ineligibility_reason"] == "PERMANENT_LAYOFF"


def test_a_voter_in_an_unruled_classification_is_challenged_without_a_reason():
    """Rule five leaves a voter from an unresolved classification challengeable at the polls,
    and a challenged entry carries no ineligibility reason.

    PRD: "Fifth, if the voter's classification is still `PENDING`, the entry is `CHALLENGED`, meaning the ballot may be cast but is subject to challenge at the polls."

    Design: Corner/calculations/voter_eligibility_applies_its_six_rules_in_declared_order
    """
    ctx = _case_with_one_unruled_group("07-RC-338115")

    entry = _add_entry(
        ctx["voter_list"]["id"], ctx["rows"]["LEAD"]["id"],
        full_name="Quinn Barros", hire_date="2021-09-20",
        personal_email="quinn.barros@example.com",
    )

    assert entry["eligibility_status"] == "CHALLENGED"
    assert_absent(entry, "ineligibility_reason", "voter_list_entry")


def test_the_date_tests_are_generous_at_both_edges():
    """A voter hired on the cut-off day and separated on election day stays eligible, and
    missing statutory content does not disturb that outcome.

    PRD: "All three date tests are plain calendar-date comparisons on `YYYY-MM-DD` values with no timezone conversion, and both edges are generous to the voter: a `hire_date` exactly equal to `payroll_period_end` is eligible, because being hired on the cut-off day places the voter inside the period, and a `termination_date` exactly equal to `approved_election_date` is eligible, because the last day worked is election day."

    PRD: "Missing statutory content is orthogonal to all of this: an entry missing only its `personal_email` has a `missing_field_count` of 1 and `is_statutory_content_complete` false, yet its eligibility outcome is unaffected."

    Design: Corner/calculations/voter_eligibility_applies_its_six_rules_in_declared_order
    """
    ctx = _case_with_one_unruled_group("07-RC-338116")

    entry = _add_entry(
        ctx["voter_list"]["id"], ctx["rows"]["PROD"]["id"],
        full_name="Ivo Marek", hire_date=PAYROLL_PERIOD_END,
        termination_date=ELECTION_DATE, personal_email="ivo.marek@example.com",
        personal_phone=None,
    )

    assert entry["eligibility_status"] == "ELIGIBLE", (
        "both date edges are generous to the voter, got " f"{entry['eligibility_status']}"
    )
    assert_absent(entry, "ineligibility_reason", "voter_list_entry")
    assert entry["missing_field_count"] == 1
    assert entry["is_statutory_content_complete"] is False


def test_sick_leave_never_defeats_eligibility():
    """A voter out on sick leave is still an eligible voter with complete statutory content.

    PRD: "Leave of type `SICK`, `FMLA` or `MILITARY` never defeats eligibility."

    PRD: "The five statutory content fields are counted: `missing_field_count` is the number of them that are absent, null or empty, so it runs from 0 to 5, and `is_statutory_content_complete` is true exactly when that count is 0."

    Design: Corner/calculations/voter_eligibility_applies_its_six_rules_in_declared_order
    """
    ctx = _case_with_one_unruled_group("07-RC-338117")

    entry = _add_entry(
        ctx["voter_list"]["id"], ctx["rows"]["PROD"]["id"],
        full_name="Sara Whitfield", hire_date="2020-06-15",
        on_leave_type="SICK", personal_email="sara.whitfield@example.com",
    )

    assert entry["eligibility_status"] == "ELIGIBLE"
    assert entry["missing_field_count"] == 0
    assert entry["is_statutory_content_complete"] is True


def test_each_entry_create_recomputes_the_list_counters():
    """Adding voters one at a time keeps the list's entry counters current, whatever each
    voter's eligibility outcome.

    PRD: "Every create and every update re-runs the eligibility rules and recomputes the parent list's counters."

    Design: Corner/calculations/voter_eligibility_applies_its_six_rules_in_declared_order
    """
    ctx = _case_with_one_unruled_group("07-RC-338118")
    voter_list_id = ctx["voter_list"]["id"]
    rows = ctx["rows"]

    _add_entry(voter_list_id, rows["QC"]["id"], full_name="Lena Ortiz",
               hire_date="2024-05-02", personal_email="lena.ortiz@example.com")
    _add_entry(voter_list_id, rows["PROD"]["id"], full_name="Nils Haugen",
               hire_date="2026-08-15", personal_email="nils.haugen@example.com")
    _add_entry(voter_list_id, rows["PROD"]["id"], full_name="Omar Diallo",
               hire_date="2023-11-06", termination_date="2026-08-31",
               personal_email="omar.diallo@example.com")
    _add_entry(voter_list_id, rows["PROD"]["id"], full_name="Priya Anand",
               hire_date="2022-02-14", on_leave_type="PERMANENT_LAYOFF",
               personal_email="priya.anand@example.com")
    _add_entry(voter_list_id, rows["LEAD"]["id"], full_name="Quinn Barros",
               hire_date="2021-09-20", personal_email="quinn.barros@example.com")
    _add_entry(voter_list_id, rows["PROD"]["id"], full_name="Ivo Marek",
               hire_date=PAYROLL_PERIOD_END, termination_date=ELECTION_DATE,
               personal_email="ivo.marek@example.com", personal_phone=None)
    _add_entry(voter_list_id, rows["PROD"]["id"], full_name="Sara Whitfield",
               hire_date="2020-06-15", on_leave_type="SICK",
               personal_email="sara.whitfield@example.com")

    listed = read_voter_list(voter_list_id)
    assert listed["total_entry_count"] == 7
    assert listed["complete_entry_count"] == 6, (
        "only the entry missing a phone number is incomplete, got "
        f"{listed['complete_entry_count']}"
    )


def test_an_unruled_classification_keeps_the_showing_on_the_petitioned_headcount():
    """With one classification still unresolved the showing is measured against every
    classified head, including the group the employer wants excluded.

    PRD: "If at least one classification is still `PENDING`, or has become `MOOT`, the basis is `AS_PETITIONED` and the denominator is `total_classified_headcount`, because with scope unresolved the Board tests the showing against the unit as the petition described it — every classified head counts, including the ones the employer wants excluded."

    Design: Corner/calculations/voter_eligibility_applies_its_six_rules_in_declared_order
    """
    ctx = _case_with_one_unruled_group("07-RC-338119")

    verified = read_petition(ctx["petition"]["id"])
    assert verified["showing_headcount_basis"] == "AS_PETITIONED"
    assert verified["total_classified_headcount"] == 110
    # 60 valid cards over 110 classified heads is 54.5454..., rounded to 54.55.
    assert verified["showing_of_interest_pct"] == 54.55, (
        f"showing_of_interest_pct expected 54.55, got {verified['showing_of_interest_pct']}"
    )


# --------------------------------------------------------------------------
# Grading a filed list and the cure window it opens
# --------------------------------------------------------------------------
def _filed_list_with_one_content_gap(case_number):
    """File a six-voter list on time where one voter has no phone number on record."""
    petition = _open_case(case_number)
    prod, maint = _two_included_classifications(petition["id"])
    agreement = _approve_stipulated_election(petition["id"], THIRTY_VALID_CARDS)
    voter_list = create_voter_list(petition["id"], agreement["id"])
    complete_names = ("Dana Ruiz", "Ivo Marek", "Petra Nagy", "Omar Diallo", "Sara Whitfield")
    for index, name in enumerate(complete_names):
        _add_entry(
            voter_list["id"], prod["id"] if index < 3 else maint["id"],
            full_name=name, hire_date="2024-03-11",
            personal_email=f"voter{index + 1}@example.com",
        )
    gap_entry = _add_entry(
        voter_list["id"], maint["id"], full_name="Tomas Iversen",
        hire_date="2023-07-24", personal_email="tomas.iversen@example.com",
        personal_phone=None,
    )
    set_clock(LIST_FILED_CLOCK)
    filed = submit_voter_list(voter_list["id"])
    return {"petition": petition, "agreement": agreement, "voter_list": filed,
            "gap_entry": gap_entry}


def test_a_list_missing_one_statutory_field_grades_as_a_material_defect():
    """Five complete voters out of six is 83.33% complete, which grades as a material defect
    even though the list was filed before its deadline.

    PRD: "`completeness_pct` is `complete_entry_count` multiplied by 100, divided by `total_entry_count`, rounded half-up to two decimals — where the complete-entry count is the number of entries whose `is_statutory_content_complete` is true."

    PRD: "The base tier follows from the rounded percentage: exactly 100.00 is `COMPLIANT`, at least 90.00 is `MINOR_DEFECT`, at least 75.00 is `MATERIAL_DEFECT`, and anything below 75.00 is `GROSSLY_DEFICIENT`."

    PRD: "`is_late` is true exactly when `submitted_at` falls after `due_at`; equality is on time, and one second later is late."

    Design: Corner/calculations/material_defect_grade_sets_a_twenty_four_hour_cure_window
    """
    ctx = _filed_list_with_one_content_gap("07-RC-338120")
    filed = ctx["voter_list"]

    assert filed["total_entry_count"] == 6
    assert filed["complete_entry_count"] == 5
    assert filed["completeness_pct"] == 83.33, (
        f"completeness_pct expected 83.33, got {filed['completeness_pct']}"
    )
    assert filed["is_late"] is False
    assert filed["list_grade"] == "MATERIAL_DEFECT", (
        f"83.33% complete grades MATERIAL_DEFECT, got {filed['list_grade']}"
    )
    assert_instant_equals(filed["due_at"], add_business_days("2026-08-20", 2), "voter_list.due_at")
    assert ctx["gap_entry"]["missing_field_count"] == 1
    # Grading counts the eligible voters: nobody on this list is excluded or late-hired.
    assert filed["eligible_voter_count"] == 6


def test_returning_a_material_defect_for_cure_opens_a_twenty_four_hour_window():
    """A material defect returned for cure gives the director exactly 24 hours by the clock,
    even when that lands on a Saturday.

    PRD: "`RETURN_FOR_CURE` moves the list to `DEFICIENT` and is only available when `list_grade` is `MINOR_DEFECT` or `MATERIAL_DEFECT`; it stamps `reviewed_at`, writes the noted defect codes, and opens a cure window whose length is set by the grade — 48 hours for a minor defect, 24 hours for a material one — with `cure_deadline_at` computed as `reviewed_at` plus that many hours by exact hour arithmetic."

    PRD: "A material defect reviewed at `2026-08-21T18:00:00Z` therefore expires at `2026-08-22T18:00:00Z`, a Saturday, because the cure clock ignores business days entirely."

    Design: Corner/calculations/material_defect_grade_sets_a_twenty_four_hour_cure_window
    """
    ctx = _filed_list_with_one_content_gap("07-RC-338121")
    set_clock(LIST_REVIEW_CLOCK)

    returned = review_voter_list(
        ctx["voter_list"]["id"], "RETURN_FOR_CURE",
        noted_defects=["Missing personal telephone number for one voter."],
    )

    assert returned["status"] == "DEFICIENT"
    assert_instant_equals(returned["reviewed_at"], LIST_REVIEW_CLOCK, "voter_list.reviewed_at")
    assert returned["cure_window_hours"] == 24, (
        f"a material defect gets a 24 hour cure window, got {returned['cure_window_hours']}"
    )
    assert_instant_equals(
        returned["cure_deadline_at"], plus_hours(LIST_REVIEW_CLOCK, 24),
        "voter_list.cure_deadline_at",
    )
    # The window runs on wall-clock hours, so it expires on a Saturday evening.
    assert_instant_equals(
        returned["cure_deadline_at"], "2026-08-22T18:00:00Z", "voter_list.cure_deadline_at"
    )


# --------------------------------------------------------------------------
# The additive campaign risk score and its ceiling
# --------------------------------------------------------------------------
def _reviewed_captive_audience_meeting(case_number):
    """Draft the worst kind of captive-audience meeting and have its accuracy reviewed."""
    petition = _open_case(case_number)
    _two_included_classifications(petition["id"])
    _approve_stipulated_election(petition["id"], THIRTY_VALID_CARDS)
    presenter = create_trained_supervisor(
        petition["id"], full_name="Nils Brandt", job_title="Shift Supervisor",
        span_of_control=18, has_hire_fire_authority=True,
    )
    draft = api_client.create_campaign_communication(
        create_campaign_communication_payload(
            petition["id"],
            channel="CAPTIVE_AUDIENCE_MEETING",
            audience_scope="UNIT_WIDE",
            planned_delivery_at="2026-08-25T13:00:00Z",
            duration_minutes=45,
            presenter_supervisor_id=presenter["id"],
            message_summary="All-hands meeting on the consequences of unionization.",
            threat_statement_count=3,
            contains_interrogation=True,
            contains_promise_of_benefit=True,
            contains_surveillance_reference=True,
        ),
        DIRECTOR,
    )
    message = validate_success(draft, 201)
    reviewed = validate_success(
        api_client.accuracy_review_communication(
            message["id"],
            {"material_claim_count": 6, "unsupported_material_claim_count": 4},
            ANALYST,
        )
    )
    return {"petition": petition, "message": message, "reviewed": reviewed}


def test_a_captive_audience_meeting_risk_score_is_clamped_at_one_hundred():
    """Every aggravating factor at once accumulates past the ceiling, and the stored score
    stops at 100.

    PRD: "`risk_score` is built additively from an exact-integer base rate determined by channel — 5 for `EMAIL`, 5 for `LETTER`, 10 for `DIGITAL_POST`, 20 for `SMALL_GROUP_MEETING` and 30 for `CAPTIVE_AUDIENCE_MEETING` — to which the following are added: 15 for each threat statement counted in `threat_statement_count`; 12 if `contains_interrogation` is true; 10 if `contains_promise_of_benefit` is true; 8 if `contains_surveillance_reference` is true; 6 for each unsupported material claim **beyond the first**, so a single unsupported claim adds nothing while two add 6 and four add 18; and 5 if `audience_scope` is `UNIT_WIDE`."

    PRD: "The accumulated total is then clamped to a maximum of 100, once, after every additive term rather than term by term."

    Design: Corner/calculations/campaign_risk_score_saturates_at_one_hundred
    """
    ctx = _reviewed_captive_audience_meeting("07-RC-338130")
    reviewed = ctx["reviewed"]

    # 30 base, 45 for three threats, 12, 10, 8, 18 for three claims beyond the first
    # and 5 for unit-wide scope accumulate 128.
    assert reviewed["risk_score"] == 100, (
        f"the accumulated 128 must be clamped to 100, got {reviewed['risk_score']}"
    )
    assert reviewed["material_claim_count"] == 6
    assert reviewed["unsupported_material_claim_count"] == 4


def test_the_accuracy_review_records_its_instant_without_advancing_the_message():
    """The review stamps the clock and settles the per-se question, and a meeting planned a
    week before the polls open is left in draft with no per-se violation.

    PRD: "The review stamps `accuracy_reviewed_at` with the logical clock and writes `risk_score` and `peerless_plywood_violation`."

    PRD: "It is true exactly when the `channel` is `CAPTIVE_AUDIENCE_MEETING` **and** `planned_delivery_at` falls inside the 24 hours immediately before the current round's `polls_open_at` — an interval that is closed at its lower edge and open at its upper, so a delivery planned exactly 24 hours before the polls open is inside the blackout while one planned exactly at the opening instant is not."

    Design: Corner/calculations/campaign_risk_score_saturates_at_one_hundred
    """
    ctx = _reviewed_captive_audience_meeting("07-RC-338131")
    reviewed = ctx["reviewed"]

    assert_instant_equals(
        reviewed["accuracy_reviewed_at"], APPROVAL_CLOCK, "campaign_communication.accuracy_reviewed_at"
    )
    assert reviewed["peerless_plywood_violation"] is False, (
        "a meeting planned a week before the polls open is outside the blackout"
    )
    assert reviewed["status"] == "DRAFT", (
        f"the accuracy review does not move the message along, got {reviewed['status']}"
    )


# --------------------------------------------------------------------------
# Provisional and revised ballot tallies
# --------------------------------------------------------------------------
def test_posting_the_tally_totals_the_closed_sessions_and_sets_the_threshold():
    """Two closed sessions add up to the provisional figures, the threshold is taken on the
    valid votes alone, and three open challenges against a margin of three are determinative.

    PRD: "As a worked case: sessions closing with 30 for, 25 against and 1 void, and 12 for, 14 against and no void, give provisional figures of 42, 39 and 1, a margin of 3, valid votes cast of 81 and a threshold of 41 — and with three challenged ballots still open, three is at least three, so the challenges are determinative."

    Design: Corner/calculations/revised_tally_reconciles_the_resolved_challenges_with_the_round_total
    """
    ctx = _arc_to_tally_posted("07-RC-338140")
    posted = ctx["round"]

    assert posted["provisional_votes_for"] == 42
    assert posted["provisional_votes_against"] == 39
    assert posted["provisional_void_count"] == 1
    assert posted["provisional_margin"] == 3
    assert posted["valid_votes_cast"] == 81, (
        f"void and challenged ballots stay outside valid_votes_cast, got {posted['valid_votes_cast']}"
    )
    assert posted["majority_threshold"] == 41
    assert posted["determinative_challenges"] is True
    assert posted["ballots_cast_total"] == 85
    assert_ballot_conservation(posted)


def test_revising_the_tally_folds_the_resolved_challenges_into_the_vote_columns():
    """Resolving the three challenges two for and one void lifts the revised figures and the
    threshold, while the ballot total, the objection window and the historical finding about
    the provisional margin all stand.

    PRD: "`revised_votes_for` is `provisional_votes_for` plus `challenged_counted_for_count`; `revised_votes_against` is `provisional_votes_against` plus `challenged_counted_against_count`; `revised_void_count` is `provisional_void_count` plus `challenged_voided_count`."

    PRD: "Continuing the worked case, resolving those three open ballots as counted-for, counted-for and voided gives revised figures of 44, 39 and 2, a margin of 5, valid votes cast of 83 and a threshold of 42 — while `ballots_cast_total` stays at 85 throughout every resolution and reopen."

    PRD: "Crucially, `objection_window_close_at` is **not** recomputed either: the objection window continues to run from the provisional posting date."

    Design: Corner/calculations/revised_tally_reconciles_the_resolved_challenges_with_the_round_total
    """
    ctx = _arc_to_tally_posted("07-RC-338141")
    ballots = ctx["ballots"]
    resolve_ballot(ballots[0]["id"], resolution="COUNTED_FOR")
    resolve_ballot(ballots[1]["id"], resolution="COUNTED_FOR")
    resolve_ballot(ballots[2]["id"], resolution="VOIDED")

    revised = revise_tally(ctx["round"]["id"])

    assert revised["status"] == "TALLY_REVISED"
    assert_instant_equals(revised["tally_revised_at"], TALLY_CLOCK, "election_round.tally_revised_at")
    assert revised["revised_votes_for"] == 44
    assert revised["revised_votes_against"] == 39
    assert revised["revised_void_count"] == 2
    assert revised["revised_margin"] == 5
    assert revised["valid_votes_cast"] == 83, (
        f"valid_votes_cast is recomputed on the revised columns, got {revised['valid_votes_cast']}"
    )
    assert revised["majority_threshold"] == 42
    assert revised["challenged_open_count"] == 0
    assert revised["challenged_counted_for_count"] == 2
    assert revised["challenged_voided_count"] == 1
    assert revised["challenged_counted_against_count"] == 0
    assert revised["challenged_withdrawn_count"] == 0
    assert revised["ballots_cast_total"] == 85
    assert_ballot_conservation(revised)
    assert_instants_equal(
        revised["objection_window_close_at"], ctx["round"]["objection_window_close_at"],
        "election_round.objection_window_close_at",
    )
    assert revised["determinative_challenges"] is True, (
        "the determinative finding is historical and keeps its provisional value"
    )


# --------------------------------------------------------------------------
# The business-day deadline calendar
# --------------------------------------------------------------------------
def test_a_stipulated_approval_on_thursday_makes_the_voter_list_due_on_monday():
    """Two business days after a Thursday approval is the following Monday, because the
    approval day is not counted and the weekend is skipped.

    PRD: "A business day is Monday through Friday, excluding a fixed holiday set of `2026-09-07`, `2026-11-26`, `2026-11-27` and `2026-12-25`."

    PRD: "A stipulated approval landing on Thursday 2026-08-20 counts Friday the 21st and Monday the 24th, so the list is due at `2026-08-24T23:59:59Z`."

    Design: Corner/calculations/deadline_schedule_skips_weekends_and_the_labor_day_holiday
    """
    petition = _open_case("07-RC-338150")
    _two_included_classifications(petition["id"])

    agreement = _approve_stipulated_election(petition["id"], THIRTY_VALID_CARDS)

    assert_instant_equals(
        agreement["voter_list_due_at"], add_business_days("2026-08-20", 2),
        "election_agreement.voter_list_due_at",
    )
    assert_instant_equals(
        agreement["voter_list_due_at"], "2026-08-24T23:59:59Z",
        "election_agreement.voter_list_due_at",
    )


def test_a_voter_list_inherits_the_deadline_and_is_on_time_when_filed_before_it():
    """The list carries the arrangement's deadline, and a Friday filing against a Monday
    deadline is not late.

    PRD: "A successful create copies `due_at` from the arrangement's `voter_list_due_at`, starts the list at `status` `DRAFT`, and — this is the point of opening a fresh list — **supersedes** any list on the same case that is still `DRAFT` or `DEFICIENT`, moving each to the terminal `SUPERSEDED` state where it keeps its entries and its `cure_deadline_at` for the record but can never be submitted again."

    PRD: "A deadline expressed this way always lands at the end of the resulting day, meaning 23:59:59Z on that date."

    Design: Corner/calculations/deadline_schedule_skips_weekends_and_the_labor_day_holiday
    """
    petition = _open_case("07-RC-338151")
    prod, maint = _two_included_classifications(petition["id"])
    agreement = _approve_stipulated_election(petition["id"], THIRTY_VALID_CARDS)

    voter_list = create_voter_list(petition["id"], agreement["id"])
    _add_entry(voter_list["id"], prod["id"], full_name="Dana Ruiz",
               personal_email="dana.ruiz@example.com")
    set_clock(LIST_FILED_CLOCK)
    filed = submit_voter_list(voter_list["id"])

    assert_instant_equals(
        voter_list["due_at"], agreement["voter_list_due_at"], "voter_list.due_at"
    )
    assert_instant_equals(filed["due_at"], "2026-08-24T23:59:59Z", "voter_list.due_at")
    assert filed["is_late"] is False, "a Friday morning filing beats the Monday night deadline"


def test_the_objection_window_skips_the_labor_day_holiday():
    """Seven business days after a Wednesday tally lands on the Monday twelve days later,
    because both weekends and the Labor Day holiday are skipped.

    PRD: "To add a number of business days to an anchor date, step forward one calendar day at a time and count only business days until the required number have been counted; **the anchor day itself is never counted, even when the anchor day is itself a business day.**"

    PRD: "A tally posted on Wednesday 2026-09-02 skips the Labor Day holiday on 2026-09-07 and closes the window at `2026-09-14T23:59:59Z`."

    Design: Corner/calculations/deadline_schedule_skips_weekends_and_the_labor_day_holiday
    """
    ctx = _arc_to_tally_posted("07-RC-338152")
    posted = ctx["round"]

    assert_instant_equals(
        posted["objection_window_close_at"], add_business_days("2026-09-02", 7),
        "election_round.objection_window_close_at",
    )
    assert_instant_equals(
        posted["objection_window_close_at"], "2026-09-14T23:59:59Z",
        "election_round.objection_window_close_at",
    )
    # The posting instant itself is the logical clock, not an end-of-day deadline.
    assert_instant_equals(posted["tally_posted_at"], TALLY_CLOCK, "election_round.tally_posted_at")


# --------------------------------------------------------------------------
# The two disjoint certification timelines
# --------------------------------------------------------------------------
def _case_with_a_revised_tally(case_number, resolutions, petition_type="RC"):
    """Take a case to a revised tally, resolving its three challenges as given."""
    ctx = _arc_to_tally_posted(case_number, petition_type)
    for ballot, resolution in zip(ctx["ballots"], resolutions):
        resolve_ballot(ballot["id"], resolution=resolution)
    ctx["round"] = revise_tally(ctx["round"]["id"])
    return ctx


def test_certifying_a_union_win_opens_the_insulated_bargaining_year():
    """A revised 44 against a threshold of 42 is a union win, so the duty to bargain starts at
    once and the certification year runs a full 365 days.

    PRD: "Which certification issues turns on one comparison: the petitioning union prevailed when the round's `revised_votes_for` is greater than or equal to its `majority_threshold`."

    PRD: "When the union prevailed, `certification_outcome` becomes `CERTIFICATION_OF_REPRESENTATIVE`; `bargaining_obligation_start_at` equals `certified_at`, because the duty to bargain begins immediately; `certification_year_end_at` is `certified_at` plus 365 days, the insulated certification year; `decert_window_open_at` equals `certification_year_end_at`, since a decertification petition may only be filed once that year closes; and `election_bar_end_at` and `bargaining_obligation_end_at` are both left absent."

    PRD: "All the 365-day arithmetic is exact day arithmetic preserving the time of day: a certification issued at `2026-09-15T09:00:00Z` produces a year-end or bar-end of `2027-09-15T09:00:00Z`."

    Design: Corner/calculations/certification_of_representative_opens_the_bargaining_year
    """
    ctx = _case_with_a_revised_tally(
        "07-RC-338160", ["COUNTED_FOR", "COUNTED_FOR", "VOIDED"]
    )
    set_clock(CERTIFY_CLOCK)

    certified = certify_petition(ctx["petition"]["id"], ctx["round"]["id"])

    assert certified["certification_outcome"] == "CERTIFICATION_OF_REPRESENTATIVE"
    assert certified["case_status"] == "CERTIFIED"
    assert_instant_equals(certified["certified_at"], CERTIFY_CLOCK, "petition.certified_at")
    assert certified["certified_round_id"] == ctx["round"]["id"]
    assert_instants_equal(
        certified["bargaining_obligation_start_at"], certified["certified_at"],
        "petition.bargaining_obligation_start_at",
    )
    assert_instant_equals(
        certified["certification_year_end_at"], plus_days(CERTIFY_CLOCK, 365),
        "petition.certification_year_end_at",
    )
    assert_instant_equals(
        certified["certification_year_end_at"], "2027-09-15T09:00:00Z",
        "petition.certification_year_end_at",
    )
    assert_instants_equal(
        certified["decert_window_open_at"], certified["certification_year_end_at"],
        "petition.decert_window_open_at",
    )


def test_a_certification_of_representative_writes_none_of_the_results_fields():
    """The winning outcome leaves the election bar and the end of the bargaining duty absent,
    and the round that carried the election is closed out.

    PRD: "The two outcomes write **disjoint** sets of timestamps, and a field belonging to the other outcome must be left absent rather than set to zero or copied across."

    PRD: "The certification itself stamps `certified_at` with the logical clock, records the named round in `certified_round_id`, moves the case to the terminal `CERTIFIED` status, and moves that round to the terminal `ROUND_CERTIFIED` status."

    Design: Corner/calculations/certification_of_representative_opens_the_bargaining_year
    """
    ctx = _case_with_a_revised_tally(
        "07-RC-338161", ["COUNTED_FOR", "COUNTED_FOR", "VOIDED"]
    )
    set_clock(CERTIFY_CLOCK)

    certified = certify_petition(ctx["petition"]["id"], ctx["round"]["id"])

    assert_absent(certified, "election_bar_end_at", "petition")
    assert_absent(certified, "bargaining_obligation_end_at", "petition")
    closed_round = read_round(ctx["round"]["id"])
    assert closed_round["status"] == "ROUND_CERTIFIED"


def test_challenges_counted_against_the_union_lift_the_threshold_out_of_reach():
    """Three challenges counted against level the revised vote at 42 apiece, and the wider
    valid-vote base raises the threshold to 43.

    PRD: "`revised_margin` is the revised votes for less the revised votes against, `valid_votes_cast` is recomputed as the revised votes for plus the revised votes against, and `majority_threshold` is recomputed from that new base by the same halve-discard-add-one rule."

    PRD: "Equality is a union win, because the threshold already embeds the halve-discard-add-one rule, so a genuine tie on the raw ballots is a loss."

    Design: Corner/calculations/certification_of_results_on_a_decert_petition_ends_the_bargaining_duty
    """
    ctx = _case_with_a_revised_tally(
        "07-RD-338162", ["COUNTED_AGAINST", "COUNTED_AGAINST", "COUNTED_AGAINST"],
        petition_type="RD",
    )
    revised = ctx["round"]

    assert revised["revised_votes_for"] == 42
    assert revised["revised_votes_against"] == 42
    assert revised["revised_void_count"] == 1
    assert revised["revised_margin"] == 0
    assert revised["valid_votes_cast"] == 84
    assert revised["majority_threshold"] == 43, (
        f"84 valid votes halve-discard-add-one to 43, got {revised['majority_threshold']}"
    )
    assert revised["challenged_counted_against_count"] == 3
    assert_ballot_conservation(revised)


def test_certification_of_results_on_a_decert_petition_ends_the_duty_to_bargain():
    """A union that falls one vote short of the threshold on a decertification petition draws
    a certification of results, which ends the existing duty to bargain and bars a further
    election for a year.

    PRD: "When the union did not prevail, `certification_outcome` becomes `CERTIFICATION_OF_RESULTS`; `election_bar_end_at` is `certified_at` plus 365 days, the 12-month bar against a further election; `bargaining_obligation_start_at`, `certification_year_end_at` and `decert_window_open_at` are all left absent; and `bargaining_obligation_end_at` equals `certified_at` only when the case's `petition_type` is `RD`, because a decertification petition that ends in a certification of results terminates the pre-existing duty to bargain, and is left absent for every other petition type."

    Design: Corner/calculations/certification_of_results_on_a_decert_petition_ends_the_bargaining_duty
    """
    ctx = _case_with_a_revised_tally(
        "07-RD-338163", ["COUNTED_AGAINST", "COUNTED_AGAINST", "COUNTED_AGAINST"],
        petition_type="RD",
    )
    set_clock(CERTIFY_CLOCK)

    certified = certify_petition(ctx["petition"]["id"], ctx["round"]["id"])

    assert certified["certification_outcome"] == "CERTIFICATION_OF_RESULTS"
    assert certified["case_status"] == "CERTIFIED"
    assert_instant_equals(certified["certified_at"], CERTIFY_CLOCK, "petition.certified_at")
    assert_instant_equals(
        certified["election_bar_end_at"], plus_days(CERTIFY_CLOCK, 365),
        "petition.election_bar_end_at",
    )
    assert_instant_equals(
        certified["election_bar_end_at"], "2027-09-15T09:00:00Z", "petition.election_bar_end_at"
    )
    assert_instants_equal(
        certified["bargaining_obligation_end_at"], certified["certified_at"],
        "petition.bargaining_obligation_end_at",
    )
    assert_absent(certified, "bargaining_obligation_start_at", "petition")
    assert_absent(certified, "certification_year_end_at", "petition")
    assert_absent(certified, "decert_window_open_at", "petition")

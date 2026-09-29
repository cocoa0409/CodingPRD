"""
Refusal and admission rules: the validation gates the requirements put in front
of every write.

Five families of gate are exercised here, all of them stated in sections 2 and 3
of the requirements document.

* Temporal windows — the appeal filing window closes on an *instant* measured
  from the contested assessment's ``assessed_at`` against the logical clock
  (§3.4), and a weigh-in's ``day_index`` must both lie inside the event's
  declared range and agree with the day the reading was actually taken (§3.8).
* Segregation of duties — the assessor who produced a result may neither review
  the appeal against it nor perform the appeal-ordered retest (§3.3, §3.4), and
  a credential must be in force, for the right method, before any assessment may
  be opened at all (§3.2, §3.3).
* Uniqueness, with two different scopes — an assessor's ``credential_number`` is
  globally unique, a team's ``school_name`` is unique only within its owning
  season, and a growth-allowance ``effective_date`` is unique per season (§3.1,
  §3.2), while ``(entry_id, day_index)`` is unique per weigh-in (§3.8).
* The weight-class ladder — a value absent from the ladder is a membership
  failure, a member below the wrestler's certified floor class is a safety
  failure, and a minimum certified weight above the top of the ladder leaves the
  finalize with no class to select at all (§2.5, §3.3, §3.5).
* The safety gates — a plan or an audit sample pointing at another entity's row
  is refused referentially (§3.5, §3.9), disqualification demands the
  wrestler's *own* escalated flag (§3.9), and an escalated flag blocks both
  competition entry and a bracket class change until a physician dismisses it
  (§3.7, §3.8, §3.9).
"""

from datetime import timedelta

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    as_instant,
    assert_all_null,
    assert_append_only_row,
    assert_instant_equals,
    assert_mutable_row,
    assert_ordered_by,
    assert_row_count,
    assert_seed_integrity_sum,
    assert_severity_ledger,
    assert_weight_equals,
    expected_minimum_certified_weight,
    implied_weekly_delta,
    linear_rate_weekly_delta,
    smallest_class_at_or_above,
)
from test_helpers.constants import (
    ASSESSED_AT,
    ASSESSMENT_DAY_INSTANT,
    ASSESSMENT_DRAFT,
    ASSESSMENT_VALIDATED,
    ASSESSOR_CERTIFIED,
    ASSESSOR_PROVISIONAL,
    APPEAL_RETEST_ORDERED,
    APPEAL_SUBMITTED,
    APPEAL_UNDER_REVIEW,
    AUDIT_OPEN,
    AUDIT_TYPE_ASSESSOR_SAMPLE,
    CANON_ALPHA_WEIGHT_LBS,
    CANON_MIN_WEIGHT_CLASS_LBS,
    CANON_TARGET_CLASS_LBS,
    CANON_USG_FAIL,
    CANCEL_REASON_DISQUALIFIED,
    DEFAULT_APPEAL_FILING_WINDOW_DAYS,
    DEFAULT_ASSESSOR_MIN_TRAINING_HOURS,
    DEFAULT_CREDENTIAL_EXPIRY,
    DEFAULT_CREDENTIAL_NUMBER,
    DEFAULT_MAX_WEEKLY_DESCENT_PCT,
    DEFAULT_MIN_BODY_FAT_PCT_MALE,
    DEFAULT_TEAM_NAME,
    DEFAULT_WEIGHT_CLASSES,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INELIGIBLE,
    ENTRY_ENTERED,
    ENTRY_SEEDED,
    ENTRY_WEIGHED_IN,
    FLAG_DISMISSED,
    FLAG_ESCALATED,
    FLAG_HYDRATION_FAIL,
    FLAG_OPEN,
    FLAG_REVIEWED,
    METHOD_BIA,
    METHOD_HYDROSTATIC,
    METHOD_SKINFOLD,
    OUTCOME_BLOCKED_ESCALATED_FLAG,
    OUTCOME_CLEARED,
    PLAN_CANCELLED,
    PLAN_CERTIFIED,
    PLAN_DRAFT,
    PLAN_START_DATE,
    SCORING_WORST_CASE,
    SECOND_TEAM_NAME,
    SEX_MALE,
    TEAM_CLEAR,
    VARIANT_LINEAR_RATE,
    WEEKLY_STEP_SCHEDULE,
    WEIGH_IN_PASS,
    WRESTLER_CERTIFIED,
    WRESTLER_DISQUALIFIED,
    WRESTLER_PROVISIONAL,
    WRESTLER_UNCERTIFIED,
)
from test_helpers.test_users import (
    MEDICAL_REVIEWER,
    STATE_OFFICE,
    WEIGH_IN_OFFICIAL,
    assessor_headers,
)

# ── Instants and dates these gates are measured against ──────────────

# The filing window closes on the contested reading's assessed_at advanced by
# the season's appeal_filing_window_days; that instant is still inside it.
APPEAL_BOUNDARY_DAYS = DEFAULT_APPEAL_FILING_WINDOW_DAYS

# The event the weigh-in gates run against, its single legal weigh-in day and
# the following day the clock is pushed onto to break the day-index agreement.
WEIGH_IN_EVENT_DATE = "2026-12-12"
WEIGH_IN_DAY_INSTANT = "2026-12-12T07:00:00Z"
NEXT_DAY_INSTANT = "2026-12-13T07:00:00Z"

# A second reading on the same wrestler, taken the same UTC calendar day as the
# first and therefore inside the assessor's daily capacity of three.
SECOND_READING_AT = "2026-11-01T09:30:00Z"
THIRD_READING_AT = "2026-11-01T09:45:00Z"
RETEST_ASSESSED_AT = "2026-11-02T09:00:00Z"

# The growth-allowance dates the per-season uniqueness rule is proven on.
FIRST_ALLOWANCE_DATE = "2026-12-01"
SECOND_ALLOWANCE_DATE = "2026-12-02"

# A second season, so the two uniqueness scopes can be told apart.
SECOND_SEASON_NAME = "2027-28 State Wrestling Season"
SECOND_SEASON_START_DATE = "2027-11-01"

# The credential numbers the second and the undertrained assessor carry.
SECOND_CREDENTIAL_NUMBER = "AS-1002"
PROVISIONAL_CREDENTIAL_NUMBER = "AS-2001"

# Half of the season's certification threshold of eight hours.
PARTIAL_TRAINING_HOURS = 4.0

# Requested-weeks figures either side of the permitted weekly delta: three weeks
# imply more than the maximum, four weeks imply exactly the maximum.
EXCESSIVE_WEEKS = 3
EXACT_WEEKS = 4

# The event the entry gates run against, and the audit's sample window.
ENTRY_EVENT_NAME = "State Qualifier"
AUDIT_WINDOW_START = "2026-11-01"

# The reason text a disqualification carries into certification_hold_reason.
DQ_REASON = "Escalated hydration failure under review."

# A class one pound above 150: numerically well formed, absent from the ladder.
NON_MEMBER_CLASS_LBS = 151
# A real ladder member that sits below the wrestler's certified floor class.
BELOW_FLOOR_CLASS_LBS = 144
# The class a seeded entry is moved up into.
HIGHER_CLASS_LBS = 157

# The heavyweight readings that bracket the top of the ladder (§3.3).
OVER_CEILING_WEIGHT_LBS = 400.0
OVER_CEILING_BODY_FAT_PCT = 20.0
UNDER_CEILING_WEIGHT_LBS = 300.0
UNDER_CEILING_BODY_FAT_PCT = 25.0

# The four figures the validated arm produces and a refused finalize must not.
CERTIFIED_FIGURE_FIELDS = (
    "hydration_passed",
    "lean_body_weight_lbs",
    "minimum_certified_weight_lbs",
    "min_weight_class_lbs",
    "alpha_weight_lbs",
)


def _shift_instant(instant: str, days: int = 0, seconds: int = 0) -> str:
    """An ISO 8601 UTC instant advanced by whole days and seconds."""
    moment = as_instant(instant) + timedelta(days=days, seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _appeals_against(api, assessment_id: str, expected: int):
    """Every appeal filed against one assessment, asserting the row count."""
    return assert_row_count(
        api.list_appeals(STATE_OFFICE, {"assessment_id": assessment_id, "limit": 100}),
        expected,
        f"appeals against assessment {assessment_id}",
    )


def _assessments_of(api, wrestler_id: str, expected: int):
    """Every assessment of one wrestler, asserting the row count."""
    return assert_row_count(
        api.list_assessments(STATE_OFFICE, {"wrestler_id": wrestler_id, "limit": 100}),
        expected,
        f"assessments of wrestler {wrestler_id}",
    )


def _plans_of(api, wrestler_id: str, expected: int):
    """Every descent plan of one wrestler, asserting the row count."""
    return assert_row_count(
        api.list_descent_plans(
            STATE_OFFICE, {"wrestler_id": wrestler_id, "limit": 100}
        ),
        expected,
        f"descent plans of wrestler {wrestler_id}",
    )


def _weigh_ins_of(api, entry_id: str, expected: int):
    """Every weigh-in recorded against one entry, asserting the row count."""
    return assert_row_count(
        api.list_weigh_ins(STATE_OFFICE, {"entry_id": entry_id, "limit": 100}),
        expected,
        f"weigh-ins of entry {entry_id}",
    )


def _second_certified_assessor(api, methods=None):
    """A second credentialed assessor, trained to the season threshold."""
    return fixtures.create_certified_assessor(
        api,
        full_name="Sam Okafor",
        credential_number=SECOND_CREDENTIAL_NUMBER,
        certified_methods=methods or [METHOD_SKINFOLD, METHOD_HYDROSTATIC],
    )


def _appeal_under_review(api):
    """A filed appeal whose reviewer is an assessor other than the original.

    The contested reading is produced by the first assessor, so §3.4 forbids that
    same assessor from reviewing the appeal; the second assessor is assigned
    instead, which drives ``SUBMITTED -> UNDER_REVIEW``.
    """
    scenario = fixtures.assessed_wrestler(api)
    scenario.reviewer = _second_certified_assessor(api)
    scenario.appeal = fixtures.file_appeal(
        api, scenario.assessment_id, scenario.team_id
    )
    return scenario


def _weigh_in_open_entry(api):
    """One entered wrestler on a single weigh-in-day event, weigh-ins open.

    The event takes the default ``weigh_in_days`` of 1, so the only legal
    ``day_index`` is zero and the only legal reading date is the event date
    itself (§3.7, §3.8).
    """
    scenario = fixtures.entered_wrestler(
        api, event_date=WEIGH_IN_EVENT_DATE, weight_class_lbs=CANON_TARGET_CLASS_LBS
    )
    assert scenario.event["weigh_in_days"] == 1
    assert scenario.entry["status"] == ENTRY_ENTERED
    fixtures.move_clock(api, WEIGH_IN_DAY_INSTANT)
    fixtures.open_weigh_ins(api, scenario.event_id)
    return scenario


def _certified_wrestler_with_open_flag(api):
    """A certified wrestler carrying one ``OPEN`` hydration-failure flag.

    A second reading on the same wrestler comes in above the season's hydration
    ceiling, so §3.3 takes the ``HYDRATION_FAILED`` arm: the certification
    dimension is left exactly where it was and a ``HYDRATION_FAIL`` flag of
    severity 1 opens on the wrestler.
    """
    scenario = fixtures.certified_wrestler(api)
    failed = fixtures.create_assessment(
        api,
        scenario.wrestler_id,
        scenario.assessor_id,
        assessed_at=SECOND_READING_AT,
        measured_weight_lbs=158.0,
        urine_specific_gravity=CANON_USG_FAIL,
    )
    fixtures.finalize_assessment(api, failed["id"], scenario.assessor_id)
    flags = fixtures.flags_of_wrestler(api, scenario.wrestler_id, FLAG_OPEN)
    assert len(flags) == 1, f"expected exactly one open flag, got {len(flags)}"
    assert flags[0]["source"] == FLAG_HYDRATION_FAIL
    scenario.flag = flags[0]
    scenario.flag_id = flags[0]["id"]
    return scenario


# ── The appeal filing window closes on an instant ─────────────────────

def test_appeal_filed_on_the_closing_instant_is_inside_the_window(api):
    """The window boundary is an instant, and landing on it is permitted.

    Section 3.4 measures timeliness against the logical clock: the appeal must
    be filed within ``appeal_filing_window_days`` of the contested assessment's
    ``assessed_at``, and the boundary instant — that stamp advanced by exactly
    that many days — is still inside the window.  Section 2.6 restates the same
    inclusivity as a general rule of the regime.

    Design: Corner/validations/appeal_filing_window_boundary_instant
    """
    scenario = fixtures.assessed_wrestler(api)
    assert (
        scenario.season["appeal_filing_window_days"]
        == DEFAULT_APPEAL_FILING_WINDOW_DAYS
    )
    assert scenario.assessment["status"] == ASSESSMENT_VALIDATED
    assert_instant_equals(
        scenario.assessment["assessed_at"], ASSESSED_AT, "assessed_at"
    )

    boundary = _shift_instant(ASSESSED_AT, days=APPEAL_BOUNDARY_DAYS)
    fixtures.move_clock(api, boundary)

    appeal = validate_success(
        api.create_appeal(
            scenario.assessment_id,
            factories.appeal_payload(scenario.team_id),
            scenario.coach,
        ),
        expected_status=201,
    )

    assert_mutable_row(appeal, "appeal")
    assert appeal["status"] == APPEAL_SUBMITTED
    assert appeal["assessment_id"] == scenario.assessment_id
    assert appeal["team_id"] == scenario.team_id
    assert appeal["retest_round_count"] == 0
    assert_all_null(
        appeal,
        ("reviewing_assessor_id", "retest_assessment_id", "decision_note"),
        "a newly filed appeal",
    )
    # filed_at is stamped from the logical clock, which is on the boundary.
    assert_instant_equals(appeal["filed_at"], boundary, "filed_at")
    _appeals_against(api, scenario.assessment_id, 1)


def test_appeal_filed_one_second_past_the_boundary_is_refused(api):
    """One second beyond the closing instant the window has expired.

    Section 3.4: past the boundary instant, filing is
    ``ERR_APPEAL_WINDOW_EXPIRED``.  Nothing else about the request is wrong, so
    the refusal must leave no appeal behind and must not disturb the contested
    result or the wrestler that carries its figures.

    Design: Corner/validations/appeal_filing_window_boundary_instant
    """
    scenario = fixtures.assessed_wrestler(api)
    past_boundary = _shift_instant(
        ASSESSED_AT, days=APPEAL_BOUNDARY_DAYS, seconds=1
    )
    fixtures.move_clock(api, past_boundary)

    validate_error(
        api.create_appeal(
            scenario.assessment_id,
            factories.appeal_payload(scenario.team_id),
            scenario.coach,
        ),
        api_errors.ERR_APPEAL_WINDOW_EXPIRED,
    )

    _appeals_against(api, scenario.assessment_id, 0)
    assessment = fixtures.read_assessment(api, scenario.assessment_id)
    assert assessment["status"] == ASSESSMENT_VALIDATED
    assert assessment["version"] == scenario.assessment["version"]
    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["source_assessment_id"] == scenario.assessment_id
    assert wrestler["certification_status"] == WRESTLER_PROVISIONAL


# ── Segregation of duties across the appeal cycle ─────────────────────

def test_appeal_reviewer_may_not_be_the_assessor_who_produced_the_result(api):
    """Reviewer assignment refuses the assessor whose result is contested.

    Section 3.4 calls this the structural heart of the segregation-of-duties
    model: the supplied ``reviewing_assessor_id`` must not be the assessor who
    produced the contested assessment, and a violation is
    ``ERR_SAME_ASSESSOR_CONFLICT``.  A different certified assessor is accepted
    and drives ``SUBMITTED -> UNDER_REVIEW``.

    Design: Corner/validations/appeal_reviewer_and_retest_exclude_original_assessor
    """
    scenario = _appeal_under_review(api)
    appeal_id = scenario.appeal["id"]
    assert scenario.appeal["status"] == APPEAL_SUBMITTED

    validate_error(
        api.assign_appeal_reviewer(
            appeal_id,
            factories.assign_reviewer_payload(scenario.assessor_id),
            STATE_OFFICE,
        ),
        api_errors.ERR_SAME_ASSESSOR_CONFLICT,
    )

    refused = fixtures.read_appeal(api, appeal_id)
    assert refused["status"] == APPEAL_SUBMITTED
    assert refused["reviewing_assessor_id"] is None
    assert refused["version"] == scenario.appeal["version"]

    assigned = validate_success(
        api.assign_appeal_reviewer(
            appeal_id,
            factories.assign_reviewer_payload(scenario.reviewer["id"]),
            STATE_OFFICE,
        )
    )
    assert assigned["status"] == APPEAL_UNDER_REVIEW
    assert assigned["reviewing_assessor_id"] == scenario.reviewer["id"]
    assert assigned["version"] == scenario.appeal["version"] + 1


def test_appeal_ordered_retest_may_not_be_stamped_by_the_original_assessor(api):
    """The retest itself is closed to the assessor who produced the result.

    Section 3.3 puts the same segregation on assessment creation: when the
    assessment is an appeal-ordered retest, the assessor who produced the
    contested result may not perform the retest, and that collision is
    ``ERR_SAME_ASSESSOR_CONFLICT``.  The reviewing assessor may, and the retest
    lands in ``DRAFT`` carrying both back-references.

    Design: Corner/validations/appeal_reviewer_and_retest_exclude_original_assessor
    """
    scenario = _appeal_under_review(api)
    appeal_id = scenario.appeal["id"]
    reviewer_id = scenario.reviewer["id"]
    fixtures.assign_reviewer(api, appeal_id, reviewer_id)
    ordered = fixtures.order_retest(api, appeal_id, reviewer_id)
    assert ordered["status"] == APPEAL_RETEST_ORDERED
    assert ordered["retest_round_count"] == 1

    retest_body = factories.assessment_payload(
        assessor_id=scenario.assessor_id,
        method=METHOD_SKINFOLD,
        assessed_at=RETEST_ASSESSED_AT,
        measured_weight_lbs=158.0,
        body_fat_pct=13.5,
        retest_of_assessment_id=scenario.assessment_id,
        appeal_id=appeal_id,
    )
    validate_error(
        api.create_assessment(
            scenario.wrestler_id, retest_body, scenario.assessor_auth
        ),
        api_errors.ERR_SAME_ASSESSOR_CONFLICT,
    )
    _assessments_of(api, scenario.wrestler_id, 1)

    retest_body["assessor_id"] = reviewer_id
    retest = validate_success(
        api.create_assessment(
            scenario.wrestler_id, retest_body, assessor_headers(reviewer_id)
        ),
        expected_status=201,
    )
    assert retest["status"] == ASSESSMENT_DRAFT
    assert retest["assessor_id"] == reviewer_id
    assert retest["retest_of_assessment_id"] == scenario.assessment_id
    assert retest["appeal_id"] == appeal_id
    assert_all_null(retest, CERTIFIED_FIGURE_FIELDS, "a draft retest")
    _assessments_of(api, scenario.wrestler_id, 2)


# ── A credential in force, for the method actually used ───────────────

def test_provisional_assessor_may_not_open_an_assessment(api):
    """Opening an assessment demands a credential that is exactly certified.

    Section 3.2 lists opening an assessment among the operations that require the
    referenced assessor's ``status`` to be exactly ``CERTIFIED``, never
    ``PROVISIONAL``, ``SUSPENDED`` or ``EXPIRED``; the guard is
    ``ERR_ASSESSOR_NOT_CERTIFIED``.  Half the training threshold is not enough.

    Design: Corner/validations/assessment_requires_certified_assessor_and_certified_method
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_assessor(
        api,
        full_name="Pat Novak",
        credential_number=PROVISIONAL_CREDENTIAL_NUMBER,
        certified_methods=[METHOD_SKINFOLD],
    )
    fixtures.log_training(api, assessor["id"], PARTIAL_TRAINING_HOURS)
    trained = fixtures.read_assessor(api, assessor["id"])
    assert trained["status"] == ASSESSOR_PROVISIONAL
    assert trained["training_hours_completed"] == PARTIAL_TRAINING_HOURS
    assert (
        scenario.season["assessor_min_training_hours"]
        == DEFAULT_ASSESSOR_MIN_TRAINING_HOURS
    )
    wrestler = fixtures.create_wrestler(api, scenario.team_id)

    # The method itself is beyond reproach: it is in this assessor's list.
    validate_error(
        api.create_assessment(
            wrestler["id"],
            factories.assessment_payload(
                assessor_id=assessor["id"], method=METHOD_SKINFOLD
            ),
            assessor_headers(assessor["id"]),
        ),
        api_errors.ERR_ASSESSOR_NOT_CERTIFIED,
    )

    _assessments_of(api, wrestler["id"], 0)
    unchanged = fixtures.read_assessor(api, assessor["id"])
    assert unchanged["status"] == ASSESSOR_PROVISIONAL
    assert unchanged["validated_assessment_count"] == 0
    assert unchanged["version"] == trained["version"]


def test_method_outside_the_certified_list_is_refused_then_a_listed_one_lands(api):
    """The chosen method must be a member of the assessor's certified list.

    Section 3.3: a credentialed skinfold assessor attempting a hydrostatic
    reading is refused with ``ERR_METHOD_NOT_CERTIFIED``.  Switching to a method
    the same assessor is credentialed for opens the draft, which proves nothing
    else about the request was at fault.

    Design: Corner/validations/assessment_requires_certified_assessor_and_certified_method
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    assert assessor["status"] == ASSESSOR_CERTIFIED
    assert METHOD_HYDROSTATIC not in assessor["certified_methods"]
    assert METHOD_BIA in assessor["certified_methods"]
    wrestler = fixtures.create_wrestler(api, scenario.team_id)

    validate_error(
        api.create_assessment(
            wrestler["id"],
            factories.assessment_payload(
                assessor_id=assessor["id"], method=METHOD_HYDROSTATIC
            ),
            assessor_headers(assessor["id"]),
        ),
        api_errors.ERR_METHOD_NOT_CERTIFIED,
    )
    _assessments_of(api, wrestler["id"], 0)

    opened = validate_success(
        api.create_assessment(
            wrestler["id"],
            factories.assessment_payload(
                assessor_id=assessor["id"], method=METHOD_BIA
            ),
            assessor_headers(assessor["id"]),
        ),
        expected_status=201,
    )
    assert opened["status"] == ASSESSMENT_DRAFT
    assert opened["method"] == METHOD_BIA
    assert_all_null(opened, CERTIFIED_FIGURE_FIELDS, "a draft assessment")
    _assessments_of(api, wrestler["id"], 1)


# ── The weigh-in day index: range, agreement, then uniqueness ─────────

def test_day_index_beyond_the_events_weigh_in_days_is_out_of_range(api):
    """A day index at the count itself is already past the last legal day.

    Section 3.8: the ``day_index`` must lie between zero and the event's
    ``weigh_in_days`` minus one inclusive.  This event declares a single weigh-in
    day, so index 1 is out of range and the refusal is
    ``ERR_WEIGH_IN_DAY_OUT_OF_RANGE``.

    Design: Corner/validations/weigh_in_day_range_then_duplicate_rejected
    """
    scenario = _weigh_in_open_entry(api)

    validate_error(
        api.create_weigh_in(
            scenario.event_id,
            factories.weigh_in_payload(scenario.entry_id, 1, 149.0),
            WEIGH_IN_OFFICIAL,
        ),
        api_errors.ERR_WEIGH_IN_DAY_OUT_OF_RANGE,
    )

    _weigh_ins_of(api, scenario.entry_id, 0)
    entry = fixtures.read_entry(api, scenario.entry_id)
    assert entry["status"] == ENTRY_ENTERED
    assert entry["latest_effective_weight_lbs"] is None
    assert fixtures.read_event(api, scenario.event_id)["weighed_in_count"] == 0


def test_weigh_in_recorded_off_the_day_its_index_names_is_out_of_range(api):
    """An in-range index still fails when the clock is on the wrong day.

    Section 3.8 imposes a second, independent condition on the same field:
    ``recorded_at``, stamped from the logical clock, must fall on the event's
    ``event_date`` advanced by ``day_index`` days.  Index 0 is perfectly in range
    here, yet the clock stands on the day after the event, and the requirements
    say either violation is ``ERR_WEIGH_IN_DAY_OUT_OF_RANGE``.

    Design: Corner/validations/weigh_in_day_range_then_duplicate_rejected
    """
    scenario = _weigh_in_open_entry(api)
    assert scenario.event["event_date"] == WEIGH_IN_EVENT_DATE
    # No weigh-in exists yet, so the day agreement is the only thing at fault.
    fixtures.move_clock(api, NEXT_DAY_INSTANT)

    validate_error(
        api.create_weigh_in(
            scenario.event_id,
            factories.weigh_in_payload(scenario.entry_id, 0, 149.0),
            WEIGH_IN_OFFICIAL,
        ),
        api_errors.ERR_WEIGH_IN_DAY_OUT_OF_RANGE,
    )

    _weigh_ins_of(api, scenario.entry_id, 0)
    assert fixtures.read_entry(api, scenario.entry_id)["status"] == ENTRY_ENTERED


def test_second_weigh_in_at_the_same_day_index_is_a_duplicate(api):
    """At most one weigh-in may exist per entry and day index.

    Section 3.8: a second is ``ERR_DUPLICATE_WEIGH_IN``.  The first reading is
    recorded on the event date at index 0, so both day conditions are satisfied
    and the only thing wrong with the repeat is that the pair already exists.

    Design: Corner/validations/weigh_in_day_range_then_duplicate_rejected
    """
    scenario = _weigh_in_open_entry(api)

    recorded = validate_success(
        api.create_weigh_in(
            scenario.event_id,
            factories.weigh_in_payload(scenario.entry_id, 0, 149.0),
            WEIGH_IN_OFFICIAL,
        ),
        expected_status=201,
    )
    assert_append_only_row(recorded, "weigh-in")
    assert recorded["day_index"] == 0
    assert recorded["wrestler_id"] == scenario.wrestler_id
    assert_instant_equals(recorded["recorded_at"], WEIGH_IN_DAY_INSTANT, "recorded_at")
    # Day zero earns no consecutive-day allowance and no growth allowance is
    # published, so the effective limit is the class limit itself.
    assert_weight_equals(recorded["allowance_lbs"], 0.0, "allowance_lbs")
    assert_weight_equals(
        recorded["effective_limit_lbs"], float(CANON_TARGET_CLASS_LBS), "limit"
    )
    assert recorded["result"] == WEIGH_IN_PASS
    assert recorded["below_minimum"] is False
    entry = fixtures.read_entry(api, scenario.entry_id)
    assert entry["status"] == ENTRY_WEIGHED_IN
    assert_weight_equals(entry["latest_effective_weight_lbs"], 149.0, "effective")

    validate_error(
        api.create_weigh_in(
            scenario.event_id,
            factories.weigh_in_payload(scenario.entry_id, 0, 148.9),
            WEIGH_IN_OFFICIAL,
        ),
        api_errors.ERR_DUPLICATE_WEIGH_IN,
    )

    rows = _weigh_ins_of(api, scenario.entry_id, 1)
    assert_weight_equals(rows[0]["recorded_weight_lbs"], 149.0, "the stored reading")
    after = fixtures.read_entry(api, scenario.entry_id)
    assert after["version"] == entry["version"]
    assert_weight_equals(after["latest_effective_weight_lbs"], 149.0, "effective")


# ── Uniqueness, and the scope each rule is enforced over ──────────────

def test_credential_number_is_unique_across_every_assessor(api):
    """Credential numbers collide globally, not per season.

    Section 3.2: ``credential_number`` must be globally unique across every
    assessor, and a duplicate is ``ERR_DUPLICATE_CREDENTIAL``.  Assessors are
    registered against the program rather than against a season, so a second
    season standing open changes nothing: the number is still taken.

    Design: Corner/validations/uniqueness_family_scoped_and_global_rejections
    """
    fixtures.create_open_season(api)
    fixtures.create_open_season(api, name=SECOND_SEASON_NAME, start_date=SECOND_SEASON_START_DATE)
    first = fixtures.create_assessor(api)
    assert first["credential_number"] == DEFAULT_CREDENTIAL_NUMBER

    validate_error(
        api.create_assessor(
            factories.assessor_payload(
                full_name="Robin Vance",
                credential_number=DEFAULT_CREDENTIAL_NUMBER,
                certified_methods=[METHOD_HYDROSTATIC],
                certification_expires_on=DEFAULT_CREDENTIAL_EXPIRY,
            ),
            STATE_OFFICE,
        ),
        api_errors.ERR_DUPLICATE_CREDENTIAL,
    )

    unchanged = fixtures.read_assessor(api, first["id"])
    assert unchanged["full_name"] == first["full_name"]
    assert unchanged["certified_methods"] == first["certified_methods"]
    assert unchanged["version"] == first["version"]

    # A different number is accepted immediately afterwards.
    second = fixtures.create_assessor(
        api,
        full_name="Robin Vance",
        credential_number=SECOND_CREDENTIAL_NUMBER,
        certified_methods=[METHOD_HYDROSTATIC],
    )
    assert second["credential_number"] == SECOND_CREDENTIAL_NUMBER
    assert second["status"] == ASSESSOR_PROVISIONAL


def test_school_name_is_unique_only_inside_the_owning_season(api):
    """The same school may register once per season, not twice in one.

    Section 3.1: school names must be unique *within the owning season*, and a
    collision is ``ERR_DUPLICATE_SCHOOL_NAME``.  The identical name in a
    different season is therefore admissible, and each season counts its own
    team.

    Design: Corner/validations/uniqueness_family_scoped_and_global_rejections
    """
    first_season = fixtures.create_open_season(api)
    second_season = fixtures.create_open_season(
        api, name=SECOND_SEASON_NAME, start_date=SECOND_SEASON_START_DATE
    )
    original = fixtures.create_team(api, first_season["id"], DEFAULT_TEAM_NAME)
    assert original["school_name"] == DEFAULT_TEAM_NAME
    assert original["compliance_status"] == TEAM_CLEAR
    assert original["roster_count"] == 0

    validate_error(
        api.create_team(
            factories.team_payload(first_season["id"], DEFAULT_TEAM_NAME),
            STATE_OFFICE,
        ),
        api_errors.ERR_DUPLICATE_SCHOOL_NAME,
    )

    twin = fixtures.create_team(api, second_season["id"], DEFAULT_TEAM_NAME)
    assert twin["school_name"] == DEFAULT_TEAM_NAME
    assert twin["season_id"] == second_season["id"]
    assert twin["id"] != original["id"]

    # A second, differently named team is fine in the first season too.
    fixtures.create_team(api, first_season["id"], SECOND_TEAM_NAME)
    assert_row_count(
        api.list_season_teams(first_season["id"], STATE_OFFICE, {"limit": 100}),
        2,
        "teams of the first season",
    )
    assert_row_count(
        api.list_season_teams(second_season["id"], STATE_OFFICE, {"limit": 100}),
        1,
        "teams of the second season",
    )
    assert validate_success(api.get_season(first_season["id"], STATE_OFFICE))[
        "team_count"
    ] == 2
    assert validate_success(api.get_season(second_season["id"], STATE_OFFICE))[
        "team_count"
    ] == 1


def test_growth_allowance_is_unique_per_season_and_effective_date(api):
    """One published allowance per season per date, and the first one stands.

    Section 3.1: at most one allowance may exist per season and effective date; a
    second publication on the same date is
    ``ERR_GROWTH_ALLOWANCE_DATE_CONFLICT``.  The refused publication must not
    overwrite the figure already on file, and the neighbouring date is
    unaffected.

    Design: Corner/validations/uniqueness_family_scoped_and_global_rejections
    """
    season = fixtures.create_open_season(api)
    published = fixtures.publish_growth_allowance(
        api, season["id"], FIRST_ALLOWANCE_DATE, 1.0
    )
    assert_append_only_row(published, "growth allowance")
    assert published["effective_date"] == FIRST_ALLOWANCE_DATE
    assert_weight_equals(published["allowance_lbs"], 1.0, "allowance_lbs")

    validate_error(
        api.create_growth_allowance(
            season["id"],
            factories.growth_allowance_payload(FIRST_ALLOWANCE_DATE, 2.0),
            STATE_OFFICE,
        ),
        api_errors.ERR_GROWTH_ALLOWANCE_DATE_CONFLICT,
    )

    fixtures.publish_growth_allowance(api, season["id"], SECOND_ALLOWANCE_DATE, 2.0)
    rows = assert_row_count(
        api.list_growth_allowances(season["id"], STATE_OFFICE, {"limit": 100}),
        2,
        "growth allowances",
    )
    assert_ordered_by(rows, "effective_date", "growth allowances")
    assert_weight_equals(rows[0]["allowance_lbs"], 1.0, "the surviving figure")
    assert_weight_equals(rows[1]["allowance_lbs"], 2.0, "the second date")


# ── The descent-rate admissibility gate ───────────────────────────────

def test_requested_weeks_implying_a_delta_above_the_maximum_is_refused(api):
    """Too few weeks for the distance is an inadmissible rate.

    Section 3.5 evaluates the gate before any milestone is generated and only
    when ``requested_weeks`` is supplied: the implied delta is the baseline minus
    the target divided by the requested weeks, rounded to one place, and the
    permitted maximum is the baseline times the rate over one hundred, likewise
    rounded.  Strictly greater is ``ERR_DESCENT_RATE_EXCEEDED``.

    Design: Corner/validations/descent_rate_gate_equality_accepted_excess_rejected
    """
    scenario = fixtures.assessed_wrestler(api)
    baseline = CANON_ALPHA_WEIGHT_LBS
    assert_weight_equals(scenario.wrestler["alpha_weight_lbs"], baseline, "baseline")
    permitted = linear_rate_weekly_delta(baseline, DEFAULT_MAX_WEEKLY_DESCENT_PCT)
    implied = implied_weekly_delta(baseline, CANON_TARGET_CLASS_LBS, EXCESSIVE_WEEKS)
    assert implied > permitted, f"{implied} should exceed {permitted}"

    validate_error(
        api.create_descent_plan(
            scenario.wrestler_id,
            factories.descent_plan_payload(
                source_assessment_id=scenario.assessment_id,
                target_class_lbs=CANON_TARGET_CLASS_LBS,
                plan_start_date=PLAN_START_DATE,
                expected_wrestler_version=fixtures.wrestler_version(
                    api, scenario.wrestler_id
                ),
                plan_variant=VARIANT_LINEAR_RATE,
                requested_weeks=EXCESSIVE_WEEKS,
            ),
            scenario.coach,
        ),
        api_errors.ERR_DESCENT_RATE_EXCEEDED,
    )

    _plans_of(api, scenario.wrestler_id, 0)
    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_PROVISIONAL


def test_requested_weeks_implying_exactly_the_maximum_delta_is_accepted(api):
    """Equality with the permitted maximum is admissible, not marginal.

    Section 3.5 says equality is accepted, and section 2.6 makes that the general
    rule of the regime.  The refused attempt that precedes it leaves the
    wrestler's ``version`` untouched, which is why the very same pinned version
    still opens the plan.

    Design: Corner/validations/descent_rate_gate_equality_accepted_excess_rejected
    """
    scenario = fixtures.assessed_wrestler(api)
    baseline = CANON_ALPHA_WEIGHT_LBS
    pinned = fixtures.wrestler_version(api, scenario.wrestler_id)
    permitted = linear_rate_weekly_delta(baseline, DEFAULT_MAX_WEEKLY_DESCENT_PCT)

    def _body(requested_weeks):
        return factories.descent_plan_payload(
            source_assessment_id=scenario.assessment_id,
            target_class_lbs=CANON_TARGET_CLASS_LBS,
            plan_start_date=PLAN_START_DATE,
            expected_wrestler_version=pinned,
            plan_variant=VARIANT_LINEAR_RATE,
            requested_weeks=requested_weeks,
        )

    validate_error(
        api.create_descent_plan(scenario.wrestler_id, _body(EXCESSIVE_WEEKS), scenario.coach),
        api_errors.ERR_DESCENT_RATE_EXCEEDED,
    )

    exact = implied_weekly_delta(baseline, CANON_TARGET_CLASS_LBS, EXACT_WEEKS)
    assert exact == permitted, f"{exact} should equal {permitted}"
    plan = validate_success(
        api.create_descent_plan(scenario.wrestler_id, _body(EXACT_WEEKS), scenario.coach),
        expected_status=201,
    )

    assert plan["status"] == PLAN_DRAFT
    assert plan["target_class_lbs"] == CANON_TARGET_CLASS_LBS
    assert_weight_equals(
        plan["weekly_rate_pct"], DEFAULT_MAX_WEEKLY_DESCENT_PCT, "weekly_rate_pct"
    )
    assert_all_null(
        plan,
        (
            "weekly_delta_lbs",
            "total_weeks",
            "projected_certification_date",
            "cancel_reason",
            "supersedes_plan_id",
        ),
        "a newly opened plan",
    )
    assert plan["milestone_count"] == 0
    assert plan["missed_milestone_count"] == 0
    assert plan["breach_count"] == 0
    assert plan["revision_count"] == 0
    assert fixtures.milestones_of(api, plan["id"]) == []
    _plans_of(api, scenario.wrestler_id, 1)


# ── The positive control: every entry gate satisfied at once ───────────

def test_eligibility_check_clears_when_every_entry_gate_is_satisfied(api):
    """The logged pre-competition check reports a clear path with no blocker.

    Section 3.7 has the check report what a real entry attempt would do, in the
    same precedence the entry operation uses, with ``blocking_error_id`` reading
    null when the outcome is ``CLEARED``.  The four pinned derivation steps give
    a floor of the last milestone that has come due, and the requested class sits
    exactly on the resulting lowest eligible class.

    Design: Corner/validations/entry_accepted_when_every_gate_is_satisfied
    """
    scenario = fixtures.certified_wrestler(api)
    event = fixtures.create_event(
        api, scenario.season_id, ENTRY_EVENT_NAME, WEIGH_IN_EVENT_DATE
    )
    assert scenario.wrestler["certification_status"] == WRESTLER_CERTIFIED
    assert scenario.wrestler["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert scenario.plan["status"] == PLAN_CERTIFIED

    check = validate_success(
        api.create_eligibility_check(
            scenario.wrestler_id,
            factories.eligibility_check_payload(
                event["id"], CANON_TARGET_CLASS_LBS
            ),
            STATE_OFFICE,
        ),
        expected_status=201,
    )

    assert_append_only_row(check, "eligibility check")
    assert check["wrestler_id"] == scenario.wrestler_id
    assert check["event_id"] == event["id"]
    assert check["as_of_date"] == WEIGH_IN_EVENT_DATE
    assert_instant_equals(check["checked_at"], ASSESSMENT_DAY_INSTANT, "checked_at")
    # No allowance has been published, and the last milestone that has come due
    # by the event date is the final one of the schedule.
    assert_weight_equals(check["growth_allowance_lbs"], 0.0, "growth allowance")
    assert_weight_equals(
        check["schedule_allowable_weight_lbs"],
        WEEKLY_STEP_SCHEDULE[-1],
        "schedule allowable weight",
    )
    assert check["lowest_eligible_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS
    assert check["outcome"] == OUTCOME_CLEARED
    assert check["blocking_error_id"] is None
    # The check also refreshes the wrestler's own copy of the figure.
    refreshed = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert refreshed["lowest_eligible_class_lbs"] == CANON_MIN_WEIGHT_CLASS_LBS


def test_entry_is_admitted_when_every_gate_is_satisfied(api):
    """With no gate tripped the entry lands in the declared initial shape.

    Section 3.7: a successful entry lands in ``ENTERED`` with ``seed_number``,
    ``latest_effective_weight_lbs`` and ``scratch_reason`` null and
    ``weight_class_change_count`` at 0, and increments the event's
    ``entry_count``.  This is the control that proves the refusals elsewhere in
    this file come from the rule under test and not from the shared setup.

    Design: Corner/validations/entry_accepted_when_every_gate_is_satisfied
    """
    scenario = fixtures.certified_wrestler(api)
    event = fixtures.create_event(
        api, scenario.season_id, ENTRY_EVENT_NAME, WEIGH_IN_EVENT_DATE
    )
    assert event["bracket_locked"] is False
    assert event["entry_count"] == 0
    team = fixtures.read_team(api, scenario.team_id)
    assert_severity_ledger(team, 0)

    entry = validate_success(
        api.create_entry(
            event["id"],
            factories.entry_payload(
                scenario.wrestler_id, CANON_TARGET_CLASS_LBS, season_win_count=3
            ),
            scenario.coach,
        ),
        expected_status=201,
    )

    assert_mutable_row(entry, "entry")
    assert entry["status"] == ENTRY_ENTERED
    assert entry["event_id"] == event["id"]
    assert entry["wrestler_id"] == scenario.wrestler_id
    assert entry["weight_class_lbs"] == CANON_TARGET_CLASS_LBS
    assert entry["season_win_count"] == 3
    assert entry["weight_class_change_count"] == 0
    assert_all_null(
        entry,
        ("seed_number", "latest_effective_weight_lbs", "scratch_reason"),
        "a newly admitted entry",
    )
    after = fixtures.read_event(api, event["id"])
    assert after["entry_count"] == 1
    assert after["weighed_in_count"] == 0
    assert after["seeded_entry_count"] == 0
    assert after["seed_integrity_sum"] == 0


# ── A plan target must be on the ladder and above the floor class ──────

def test_plan_target_outside_the_weight_class_ladder_is_refused(api):
    """A well-formed number that is not a ladder member is not a class.

    Section 2.5: any supplied ``target_class_lbs`` must be a member of the owning
    season's ``weight_classes``, and a value that is numerically well formed but
    absent from the ladder is refused with ``ERR_INVALID_WEIGHT_CLASS``.  The
    value used here sits one pound above a real class and above the wrestler's
    floor, so membership is the only thing wrong with it.

    Design: Corner/validations/plan_target_class_below_minimum_and_non_member_rejected
    """
    scenario = fixtures.assessed_wrestler(api)
    assert scenario.season["weight_classes"] == list(DEFAULT_WEIGHT_CLASSES)
    assert NON_MEMBER_CLASS_LBS not in scenario.season["weight_classes"]
    assert NON_MEMBER_CLASS_LBS > scenario.wrestler["min_weight_class_lbs"]

    validate_error(
        api.create_descent_plan(
            scenario.wrestler_id,
            factories.descent_plan_payload(
                source_assessment_id=scenario.assessment_id,
                target_class_lbs=NON_MEMBER_CLASS_LBS,
                plan_start_date=PLAN_START_DATE,
                expected_wrestler_version=fixtures.wrestler_version(
                    api, scenario.wrestler_id
                ),
            ),
            scenario.coach,
        ),
        api_errors.ERR_INVALID_WEIGHT_CLASS,
    )

    _plans_of(api, scenario.wrestler_id, 0)


def test_plan_target_below_the_certified_floor_class_is_refused(api):
    """A real class below the wrestler's hard floor is a safety refusal.

    Section 3.5: the ``target_class_lbs`` must be greater than or equal to the
    wrestler's ``min_weight_class_lbs``, and a target below that hard floor is
    ``ERR_TARGET_BELOW_MINIMUM``.  The floor class itself is accepted, which is
    the inclusivity section 2.6 promises.

    Design: Corner/validations/plan_target_class_below_minimum_and_non_member_rejected
    """
    scenario = fixtures.assessed_wrestler(api)
    floor_class = scenario.wrestler["min_weight_class_lbs"]
    assert floor_class == CANON_MIN_WEIGHT_CLASS_LBS
    assert BELOW_FLOOR_CLASS_LBS in scenario.season["weight_classes"]
    assert BELOW_FLOOR_CLASS_LBS < floor_class
    pinned = fixtures.wrestler_version(api, scenario.wrestler_id)

    validate_error(
        api.create_descent_plan(
            scenario.wrestler_id,
            factories.descent_plan_payload(
                source_assessment_id=scenario.assessment_id,
                target_class_lbs=BELOW_FLOOR_CLASS_LBS,
                plan_start_date=PLAN_START_DATE,
                expected_wrestler_version=pinned,
            ),
            scenario.coach,
        ),
        api_errors.ERR_TARGET_BELOW_MINIMUM,
    )
    _plans_of(api, scenario.wrestler_id, 0)

    plan = validate_success(
        api.create_descent_plan(
            scenario.wrestler_id,
            factories.descent_plan_payload(
                source_assessment_id=scenario.assessment_id,
                target_class_lbs=floor_class,
                plan_start_date=PLAN_START_DATE,
                expected_wrestler_version=pinned,
            ),
            scenario.coach,
        ),
        expected_status=201,
    )
    assert plan["status"] == PLAN_DRAFT
    assert plan["target_class_lbs"] == floor_class
    _plans_of(api, scenario.wrestler_id, 1)


# ── A minimum above the top of the ladder cannot be certified ──────────

def test_finalize_is_refused_when_no_class_can_hold_the_minimum(api):
    """A computed minimum above the heaviest class leaves nothing to select.

    Section 3.3 selects ``min_weight_class_lbs`` as the smallest class at or
    above the computed minimum, and: if no class in the season is greater than or
    equal to that minimum, the finalize is refused with
    ``ERR_NO_ELIGIBLE_WEIGHT_CLASS``.  The hydration reading passes, so the fork
    genuinely reaches the certified-figure arithmetic before failing.

    Design: Corner/validations/finalize_rejected_when_no_weight_class_can_hold_the_minimum
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id, "Casey Bloom", SEX_MALE, 12)
    opened = fixtures.create_assessment(
        api,
        wrestler["id"],
        assessor["id"],
        measured_weight_lbs=OVER_CEILING_WEIGHT_LBS,
        body_fat_pct=OVER_CEILING_BODY_FAT_PCT,
    )
    minimum = expected_minimum_certified_weight(
        OVER_CEILING_WEIGHT_LBS,
        OVER_CEILING_BODY_FAT_PCT,
        DEFAULT_MIN_BODY_FAT_PCT_MALE,
    )
    assert minimum > max(DEFAULT_WEIGHT_CLASSES), f"{minimum} should exceed the ladder"
    assert smallest_class_at_or_above(minimum) is None

    validate_error(
        api.finalize_assessment(opened["id"], assessor_headers(assessor["id"])),
        api_errors.ERR_NO_ELIGIBLE_WEIGHT_CLASS,
    )

    refused = fixtures.read_assessment(api, opened["id"])
    assert refused["status"] == ASSESSMENT_DRAFT
    assert refused["version"] == opened["version"]
    assert_all_null(refused, CERTIFIED_FIGURE_FIELDS, "the refused assessment")
    stalled = fixtures.read_wrestler(api, wrestler["id"])
    assert stalled["certification_status"] == WRESTLER_UNCERTIFIED
    assert stalled["source_assessment_id"] is None
    assert fixtures.read_assessor(api, assessor["id"])["validated_assessment_count"] == 0
    season = validate_success(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season["certified_wrestler_count"] == 0


def test_finalize_succeeds_when_the_top_of_the_ladder_still_holds(api):
    """The same arithmetic one class lower certifies into the heaviest class.

    Section 3.3 again, on the accepting side: the smallest class greater than or
    equal to the computed minimum is selected, which for a minimum inside the
    ladder is the heaviest class.  This is the contrast that shows the refusal
    above is about the ladder running out, not about heavy readings.

    Design: Corner/validations/finalize_rejected_when_no_weight_class_can_hold_the_minimum
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id, "Ira Delgado", SEX_MALE, 12)
    validated = fixtures.create_validated_assessment(
        api,
        wrestler["id"],
        assessor["id"],
        measured_weight_lbs=UNDER_CEILING_WEIGHT_LBS,
        body_fat_pct=UNDER_CEILING_BODY_FAT_PCT,
    )

    minimum = expected_minimum_certified_weight(
        UNDER_CEILING_WEIGHT_LBS,
        UNDER_CEILING_BODY_FAT_PCT,
        DEFAULT_MIN_BODY_FAT_PCT_MALE,
    )
    top_class = smallest_class_at_or_above(minimum)
    assert top_class == max(DEFAULT_WEIGHT_CLASSES)
    assert validated["status"] == ASSESSMENT_VALIDATED
    assert validated["hydration_passed"] is True
    assert_weight_equals(
        validated["minimum_certified_weight_lbs"], minimum, "minimum certified weight"
    )
    assert validated["min_weight_class_lbs"] == top_class
    certified = fixtures.read_wrestler(api, wrestler["id"])
    assert certified["certification_status"] == WRESTLER_PROVISIONAL
    assert certified["min_weight_class_lbs"] == top_class


# ── References must point inside the entity they claim ─────────────────

def test_plan_built_on_another_wrestlers_assessment_is_refused(api):
    """A plan may only be built on its own wrestler's validated result.

    Section 3.5: the referenced ``source_assessment_id`` must be an assessment in
    ``VALIDATED`` and must belong to the same wrestler the plan is being opened
    for, and either failure is ``ERR_ASSESSMENT_WRESTLER_MISMATCH``.  The
    borrowed assessment here is perfectly valid — it simply belongs to a
    teammate.

    Design: Corner/validations/cross_entity_reference_mismatches_rejected
    """
    scenario = fixtures.assessed_wrestler(api)
    teammate = fixtures.create_wrestler(
        api, scenario.team_id, "Bo Ramsey", SEX_MALE, 10
    )
    teammates_assessment = fixtures.create_validated_assessment(
        api,
        teammate["id"],
        scenario.assessor_id,
        assessed_at=SECOND_READING_AT,
        measured_weight_lbs=152.0,
        body_fat_pct=13.0,
    )
    assert teammates_assessment["status"] == ASSESSMENT_VALIDATED
    assert teammates_assessment["wrestler_id"] == teammate["id"]
    pinned = fixtures.wrestler_version(api, scenario.wrestler_id)

    validate_error(
        api.create_descent_plan(
            scenario.wrestler_id,
            factories.descent_plan_payload(
                source_assessment_id=teammates_assessment["id"],
                target_class_lbs=CANON_TARGET_CLASS_LBS,
                plan_start_date=PLAN_START_DATE,
                expected_wrestler_version=pinned,
            ),
            scenario.coach,
        ),
        api_errors.ERR_ASSESSMENT_WRESTLER_MISMATCH,
    )
    _plans_of(api, scenario.wrestler_id, 0)

    plan = validate_success(
        api.create_descent_plan(
            scenario.wrestler_id,
            factories.descent_plan_payload(
                source_assessment_id=scenario.assessment_id,
                target_class_lbs=CANON_TARGET_CLASS_LBS,
                plan_start_date=PLAN_START_DATE,
                expected_wrestler_version=pinned,
            ),
            scenario.coach,
        ),
        expected_status=201,
    )
    assert plan["source_assessment_id"] == scenario.assessment_id
    assert plan["wrestler_id"] == scenario.wrestler_id
    _plans_of(api, scenario.wrestler_id, 1)


def test_audit_sample_pointing_at_another_assessors_work_is_refused(api):
    """Every sampled assessment must have been produced by the audit's subject.

    Section 3.9: a sample pointing at somebody else's work is
    ``ERR_AUDIT_SAMPLE_MISMATCH``.  Re-aiming the identical sample at the
    subject's own assessment opens the audit, so the sample body and the
    remeasured figure were never the problem.

    Design: Corner/validations/cross_entity_reference_mismatches_rejected
    """
    scenario = fixtures.assessed_wrestler(api)
    other_assessor = _second_certified_assessor(api)
    foreign = fixtures.create_assessment(
        api,
        scenario.wrestler_id,
        other_assessor["id"],
        assessed_at=THIRD_READING_AT,
        measured_weight_lbs=158.4,
        body_fat_pct=13.8,
    )
    assert foreign["assessor_id"] == other_assessor["id"]

    validate_error(
        api.create_audit(
            scenario.season_id,
            factories.audit_payload(
                AUDIT_TYPE_ASSESSOR_SAMPLE,
                SCORING_WORST_CASE,
                AUDIT_WINDOW_START,
                assessor_id=scenario.assessor_id,
                samples=factories.audit_samples([(foreign["id"], 15.2)]),
            ),
            STATE_OFFICE,
        ),
        api_errors.ERR_AUDIT_SAMPLE_MISMATCH,
    )
    assert_row_count(
        api.list_audits(STATE_OFFICE, {"season_id": scenario.season_id, "limit": 100}),
        0,
        "audits of the season",
    )

    audit = validate_success(
        api.create_audit(
            scenario.season_id,
            factories.audit_payload(
                AUDIT_TYPE_ASSESSOR_SAMPLE,
                SCORING_WORST_CASE,
                AUDIT_WINDOW_START,
                assessor_id=scenario.assessor_id,
                samples=factories.audit_samples([(scenario.assessment_id, 15.2)]),
            ),
            STATE_OFFICE,
        ),
        expected_status=201,
    )
    assert audit["status"] == AUDIT_OPEN
    assert audit["assessor_id"] == scenario.assessor_id
    assert audit["sample_count"] == 1
    assert audit["voided_assessment_count"] == 0
    assert_all_null(audit, ("discrepancy_score", "outcome"), "a newly opened audit")


# ── Disqualification demands the wrestler's own escalated flag ──────────

def test_disqualification_is_refused_while_the_cited_flag_is_only_open(api):
    """An open flag is a concern, not a physician's escalation.

    Section 3.9 makes this the segregation of duties at the heart of the safety
    workflow: the state office cannot disqualify without a physician's
    escalation.  The cited flag must be in ``ESCALATED``, and a flag that is
    ``OPEN`` is refused with ``ERR_ESCALATED_FLAG_REQUIRED``.

    Design: Corner/validations/disqualification_requires_escalated_flag_of_same_wrestler
    """
    scenario = _certified_wrestler_with_open_flag(api)
    assert scenario.flag["status"] == FLAG_OPEN

    validate_error(
        api.disqualify_wrestler(
            scenario.wrestler_id,
            factories.disqualification_payload(scenario.flag_id, DQ_REASON),
            STATE_OFFICE,
        ),
        api_errors.ERR_ESCALATED_FLAG_REQUIRED,
    )

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED
    assert wrestler["eligibility_status"] == ELIGIBILITY_ELIGIBLE
    assert wrestler["disqualified_at"] is None
    assert wrestler["certification_hold_reason"] is None
    assert fixtures.read_plan(api, scenario.plan_id)["status"] == PLAN_CERTIFIED
    team = fixtures.read_team(api, scenario.team_id)
    assert team["roster_count"] == 1
    assert_severity_ledger(team, 1)
    season = validate_success(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season["certified_wrestler_count"] == 1


def test_reviewed_flag_can_never_authorise_a_disqualification(api):
    """A closed concern is terminal, so it can never become an escalation.

    Section 3.9 lists ``REVIEWED`` among the states refused with
    ``ERR_ESCALATED_FLAG_REQUIRED``, and separately makes ``REVIEWED`` terminal
    for a flag: reviewing one already in ``REVIEWED`` is
    ``ERR_HEALTH_FLAG_INVALID_STATE``, so there is no route from here to an
    escalation.

    Design: Corner/validations/disqualification_requires_escalated_flag_of_same_wrestler
    """
    scenario = _certified_wrestler_with_open_flag(api)
    reviewed = fixtures.review_flag(api, scenario.flag_id, FLAG_REVIEWED)
    assert reviewed["status"] == FLAG_REVIEWED
    # A REVIEWED outcome takes the severity back out of the team's ledger.
    assert_severity_ledger(fixtures.read_team(api, scenario.team_id), 0)

    validate_error(
        api.disqualify_wrestler(
            scenario.wrestler_id,
            factories.disqualification_payload(scenario.flag_id, DQ_REASON),
            STATE_OFFICE,
        ),
        api_errors.ERR_ESCALATED_FLAG_REQUIRED,
    )
    validate_error(
        api.review_health_flag(
            scenario.flag_id,
            factories.flag_review_payload(FLAG_ESCALATED, "Reopening the concern."),
            MEDICAL_REVIEWER,
        ),
        api_errors.ERR_HEALTH_FLAG_INVALID_STATE,
    )

    assert fixtures.read_flag(api, scenario.flag_id)["status"] == FLAG_REVIEWED
    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED
    assert wrestler["disqualified_at"] is None


def test_escalated_flag_of_another_wrestler_cannot_disqualify(api):
    """The cited flag must belong to the wrestler named in the request.

    Section 3.9: a flag belonging to somebody else is refused with
    ``ERR_ESCALATED_FLAG_REQUIRED`` even when it is properly escalated.  The
    borrowed flag is a genuine physician escalation — it simply belongs to a
    teammate.

    Design: Corner/validations/disqualification_requires_escalated_flag_of_same_wrestler
    """
    scenario = _certified_wrestler_with_open_flag(api)
    teammate = fixtures.create_wrestler(
        api, scenario.team_id, "Bo Ramsey", SEX_MALE, 10
    )
    teammates_reading = fixtures.create_assessment(
        api,
        teammate["id"],
        scenario.assessor_id,
        assessed_at=THIRD_READING_AT,
        measured_weight_lbs=157.0,
        urine_specific_gravity=CANON_USG_FAIL,
    )
    fixtures.finalize_assessment(api, teammates_reading["id"], scenario.assessor_id)
    teammates_flags = fixtures.flags_of_wrestler(api, teammate["id"], FLAG_OPEN)
    assert len(teammates_flags) == 1
    escalated = fixtures.review_flag(
        api, teammates_flags[0]["id"], FLAG_ESCALATED
    )
    assert escalated["status"] == FLAG_ESCALATED
    assert escalated["wrestler_id"] == teammate["id"]

    validate_error(
        api.disqualify_wrestler(
            scenario.wrestler_id,
            factories.disqualification_payload(escalated["id"], DQ_REASON),
            STATE_OFFICE,
        ),
        api_errors.ERR_ESCALATED_FLAG_REQUIRED,
    )

    wrestler = fixtures.read_wrestler(api, scenario.wrestler_id)
    assert wrestler["certification_status"] == WRESTLER_CERTIFIED
    assert wrestler["disqualified_at"] is None
    assert fixtures.read_flag(api, escalated["id"])["status"] == FLAG_ESCALATED
    assert (
        fixtures.read_wrestler(api, teammate["id"])["certification_status"]
        != WRESTLER_DISQUALIFIED
    )


def test_disqualification_on_the_wrestlers_own_escalated_flag_is_accepted(api):
    """The one admissible citation drives the whole safety cascade.

    Section 3.9: on success ``certification_status`` becomes ``DISQUALIFIED``,
    ``disqualified_at`` is stamped from the logical clock,
    ``certification_hold_reason`` records the supplied reason,
    ``eligibility_status`` drops to ``INELIGIBLE``, the certified plan is
    cancelled with ``cancel_reason`` ``DISQUALIFIED``, the team's
    ``roster_count`` is decremented, and — because this wrestler was
    ``CERTIFIED`` — the season's ``certified_wrestler_count`` is decremented too.

    Design: Corner/validations/disqualification_requires_escalated_flag_of_same_wrestler
    """
    scenario = _certified_wrestler_with_open_flag(api)
    escalated = fixtures.review_flag(api, scenario.flag_id, FLAG_ESCALATED)
    assert escalated["status"] == FLAG_ESCALATED
    # Escalation deliberately leaves the severity inside the ledger.
    assert_severity_ledger(fixtures.read_team(api, scenario.team_id), 1)

    wrestler = validate_success(
        api.disqualify_wrestler(
            scenario.wrestler_id,
            factories.disqualification_payload(scenario.flag_id, DQ_REASON),
            STATE_OFFICE,
        )
    )

    assert wrestler["certification_status"] == WRESTLER_DISQUALIFIED
    assert wrestler["eligibility_status"] == ELIGIBILITY_INELIGIBLE
    assert wrestler["certification_hold_reason"] == DQ_REASON
    assert_instant_equals(
        wrestler["disqualified_at"], ASSESSMENT_DAY_INSTANT, "disqualified_at"
    )
    plan = fixtures.read_plan(api, scenario.plan_id)
    assert plan["status"] == PLAN_CANCELLED
    assert plan["cancel_reason"] == CANCEL_REASON_DISQUALIFIED
    team = fixtures.read_team(api, scenario.team_id)
    assert team["roster_count"] == 0
    # A disqualified wrestler's escalated flag still counts in the ledger.
    assert_severity_ledger(team, 1)
    season = validate_success(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season["certified_wrestler_count"] == 0


# ── An escalated flag blocks competition until it is dismissed ──────────

def test_escalated_flag_blocks_a_competition_entry_until_it_is_dismissed(api):
    """The competition block is clearable, not permanent.

    Section 3.7 refuses a wrestler carrying any health flag in ``ESCALATED`` with
    ``ERR_UNHEALTHY_WEIGHT_MANAGEMENT``, and says they stay refused until a
    physician clears the escalation.  Section 3.9 supplies the exit:
    ``ESCALATED -> DISMISSED`` makes the wrestler no longer
    disqualification-eligible and stops that error blocking their entries.

    Design: Corner/validations/escalated_flag_blocks_entry_and_class_change_until_dismissed
    """
    scenario = _certified_wrestler_with_open_flag(api)
    fixtures.review_flag(api, scenario.flag_id, FLAG_ESCALATED)
    event = fixtures.create_event(
        api, scenario.season_id, ENTRY_EVENT_NAME, WEIGH_IN_EVENT_DATE
    )

    blocked = fixtures.run_eligibility_check(
        api, scenario.wrestler_id, event["id"], CANON_TARGET_CLASS_LBS
    )
    assert blocked["outcome"] == OUTCOME_BLOCKED_ESCALATED_FLAG
    assert blocked["blocking_error_id"] == api_errors.ERR_UNHEALTHY_WEIGHT_MANAGEMENT

    validate_error(
        api.create_entry(
            event["id"],
            factories.entry_payload(scenario.wrestler_id, CANON_TARGET_CLASS_LBS),
            scenario.coach,
        ),
        api_errors.ERR_UNHEALTHY_WEIGHT_MANAGEMENT,
    )
    assert_row_count(
        api.list_entries(STATE_OFFICE, {"event_id": event["id"], "limit": 100}),
        0,
        "entries of the event",
    )
    assert fixtures.read_event(api, event["id"])["entry_count"] == 0

    dismissed = fixtures.review_flag(api, scenario.flag_id, FLAG_DISMISSED)
    assert dismissed["status"] == FLAG_DISMISSED
    # Dismissal restores the ledger to its exact pre-raise value.
    assert_severity_ledger(fixtures.read_team(api, scenario.team_id), 0)

    cleared = fixtures.run_eligibility_check(
        api, scenario.wrestler_id, event["id"], CANON_TARGET_CLASS_LBS
    )
    assert cleared["outcome"] == OUTCOME_CLEARED
    assert cleared["blocking_error_id"] is None

    entry = validate_success(
        api.create_entry(
            event["id"],
            factories.entry_payload(scenario.wrestler_id, CANON_TARGET_CLASS_LBS),
            scenario.coach,
        ),
        expected_status=201,
    )
    assert entry["status"] == ENTRY_ENTERED
    assert entry["weight_class_lbs"] == CANON_TARGET_CLASS_LBS
    assert fixtures.read_event(api, event["id"])["entry_count"] == 1


def test_escalated_flag_blocks_a_seeded_class_change_until_it_is_dismissed(api):
    """A seeded competitor cannot be moved between classes while escalated.

    Section 3.8 allows the state-office class change only out of ``SEEDED`` with
    the bracket locked, and says a wrestler carrying an ``ESCALATED`` flag cannot
    be moved at all, which surfaces as ``ERR_UNHEALTHY_WEIGHT_MANAGEMENT``.  The
    refusal leaves the entry's ``version`` untouched, which is why the very same
    pinned version still drives the change once the flag is dismissed.

    Design: Corner/validations/escalated_flag_blocks_entry_and_class_change_until_dismissed
    """
    scenario = _weigh_in_open_entry(api)
    fixtures.record_weigh_in(api, scenario.event_id, scenario.entry_id, 0, 149.0)
    fixtures.close_weigh_ins(api, scenario.event_id)
    seeded_event = fixtures.seed_event(api, scenario.event_id)
    assert seeded_event["bracket_locked"] is True
    assert seeded_event["seeded_entry_count"] == 1
    assert_seed_integrity_sum(seeded_event, [1])
    seeded = fixtures.read_entry(api, scenario.entry_id)
    assert seeded["status"] == ENTRY_SEEDED
    assert seeded["seed_number"] == 1

    # A later hydration failure raises a flag the physician then escalates.
    failed = fixtures.create_assessment(
        api,
        scenario.wrestler_id,
        scenario.assessor_id,
        assessed_at=SECOND_READING_AT,
        measured_weight_lbs=158.0,
        urine_specific_gravity=CANON_USG_FAIL,
    )
    fixtures.finalize_assessment(api, failed["id"], scenario.assessor_id)
    raised = fixtures.flags_of_wrestler(api, scenario.wrestler_id, FLAG_OPEN)
    assert len(raised) == 1
    flag_id = raised[0]["id"]
    assert fixtures.review_flag(api, flag_id, FLAG_ESCALATED)["status"] == FLAG_ESCALATED

    pinned = seeded["version"]
    validate_error(
        api.change_entry_weight_class(
            scenario.entry_id,
            factories.weight_class_change_payload(HIGHER_CLASS_LBS, pinned),
            STATE_OFFICE,
        ),
        api_errors.ERR_UNHEALTHY_WEIGHT_MANAGEMENT,
    )

    frozen = fixtures.read_entry(api, scenario.entry_id)
    assert frozen["weight_class_lbs"] == CANON_TARGET_CLASS_LBS
    assert frozen["weight_class_change_count"] == 0
    assert frozen["status"] == ENTRY_SEEDED
    assert frozen["seed_number"] == 1
    assert frozen["version"] == pinned

    fixtures.review_flag(api, flag_id, FLAG_DISMISSED)

    moved = validate_success(
        api.change_entry_weight_class(
            scenario.entry_id,
            factories.weight_class_change_payload(HIGHER_CLASS_LBS, pinned),
            STATE_OFFICE,
        )
    )
    assert moved["weight_class_lbs"] == HIGHER_CLASS_LBS
    assert moved["weight_class_change_count"] == 1
    assert moved["status"] == ENTRY_SEEDED
    assert moved["seed_number"] == 1
    assert moved["version"] == pinned + 1
    after = fixtures.read_event(api, scenario.event_id)
    assert after["seeded_entry_count"] == 1
    assert_seed_integrity_sum(after, [1])

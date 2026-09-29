"""
Entity surface of the Wrestling Weight Certification API.

These tests exercise what the requirements say a stored row *is*: the declared
defaults a creation applies when the client supplies nothing, the fields a read
endpoint echoes back, the split between server-computed figures and client
input, the append-only rows that carry neither ``updated_at`` nor ``version``,
the entity-specific not-found identifier every single-row read uses, the
request-shape refusals that guard creation, parent resolution on a child POST,
and the two-sided reachability of the entry junction between events and
wrestlers.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, constants, factories, fixtures
from test_helpers.assertions import (
    assert_append_only_row,
    assert_instant_equals,
    assert_mutable_row,
    assert_row_count,
    assert_version_is,
    assert_weight_equals,
    ids_of,
    paginated_rows,
)
from test_helpers.test_users import (
    STATE_OFFICE,
    WEIGH_IN_OFFICIAL,
    assessor_headers,
    coach_headers,
)


# A syntactically valid identifier that matches no stored row of any entity.
_UNKNOWN_ID = "00000000-0000-4000-8000-0000000000a1"

# Every single-row read endpoint, paired with the not-found identifier §2.8
# assigns to the resource family its path segment names.
_SINGLE_ROW_READS = [
    ("get_season", api_errors.ERR_SEASON_NOT_FOUND),
    ("get_team", api_errors.ERR_TEAM_NOT_FOUND),
    ("get_assessor", api_errors.ERR_ASSESSOR_NOT_FOUND),
    ("get_wrestler", api_errors.ERR_WRESTLER_NOT_FOUND),
    ("get_assessment", api_errors.ERR_ASSESSMENT_NOT_FOUND),
    ("get_appeal", api_errors.ERR_APPEAL_NOT_FOUND),
    ("get_descent_plan", api_errors.ERR_PLAN_NOT_FOUND),
    ("get_event", api_errors.ERR_EVENT_NOT_FOUND),
    ("get_entry", api_errors.ERR_ENTRY_NOT_FOUND),
    ("get_weigh_in", api_errors.ERR_WEIGH_IN_NOT_FOUND),
    ("get_eligibility_check", api_errors.ERR_ELIGIBILITY_CHECK_NOT_FOUND),
    ("get_health_flag", api_errors.ERR_HEALTH_FLAG_NOT_FOUND),
    ("get_audit", api_errors.ERR_AUDIT_NOT_FOUND),
]


def _wrestler_body(**fields):
    """A roster payload built field by field, so a field can be left out."""
    return dict(fields)


# ── The season's declared regulatory constants ───────────────────────

def test_season_creation_applies_every_declared_regulatory_default(api):
    """A season created with only name and start date carries all 13 defaults.

    §2.5 gives each regulatory constant a default that applies when the season
    is created without it.

    Design: Corner/entities/season_creation_returns_all_declared_defaults_and_counters
    """
    payload = {
        "name": constants.SEASON_NAME,
        "start_date": constants.SEASON_START_DATE,
    }
    season = validate_success(api.create_season(payload, STATE_OFFICE), 201)

    assert season["name"] == constants.SEASON_NAME
    assert season["start_date"] == constants.SEASON_START_DATE
    assert season["weight_classes"] == constants.DEFAULT_WEIGHT_CLASSES
    assert season["min_body_fat_pct_male"] == pytest.approx(
        constants.DEFAULT_MIN_BODY_FAT_PCT_MALE, abs=0.01
    )
    assert season["min_body_fat_pct_female"] == pytest.approx(
        constants.DEFAULT_MIN_BODY_FAT_PCT_FEMALE, abs=0.01
    )
    assert season["hydration_max_specific_gravity"] == pytest.approx(
        constants.DEFAULT_HYDRATION_MAX_SPECIFIC_GRAVITY, abs=0.0001
    )
    assert season["max_weekly_descent_pct"] == pytest.approx(
        constants.DEFAULT_MAX_WEEKLY_DESCENT_PCT, abs=0.01
    )
    assert season["assessor_min_training_hours"] == (
        constants.DEFAULT_ASSESSOR_MIN_TRAINING_HOURS
    )
    assert season["assessor_daily_assessment_capacity"] == (
        constants.DEFAULT_ASSESSOR_DAILY_ASSESSMENT_CAPACITY
    )
    assert season["audit_fail_threshold_pct"] == pytest.approx(
        constants.DEFAULT_AUDIT_FAIL_THRESHOLD_PCT, abs=0.01
    )
    assert season["audit_min_sample_count"] == constants.DEFAULT_AUDIT_MIN_SAMPLE_COUNT
    assert season["max_consecutive_day_allowance_lbs"] == pytest.approx(
        constants.DEFAULT_MAX_CONSECUTIVE_DAY_ALLOWANCE_LBS, abs=0.01
    )
    assert season["appeal_filing_window_days"] == (
        constants.DEFAULT_APPEAL_FILING_WINDOW_DAYS
    )
    assert season["max_appeal_retest_rounds"] == (
        constants.DEFAULT_MAX_APPEAL_RETEST_ROUNDS
    )
    assert season["plan_breach_limit"] == constants.DEFAULT_PLAN_BREACH_LIMIT


def test_season_creation_starts_in_setup_with_both_counters_at_zero(api):
    """A brand new season sits in SETUP at version 1 with nothing counted yet.

    §2.5 declares the two derived counters and the starting status; §2.4
    declares the UUID identity and the version that starts at 1.

    Design: Corner/entities/season_creation_returns_all_declared_defaults_and_counters
    """
    payload = {
        "name": constants.SEASON_NAME,
        "start_date": constants.SEASON_START_DATE,
    }
    response = api.create_season(payload, STATE_OFFICE)
    assert response.status_code == 201
    season = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")

    assert season["status"] == constants.SEASON_SETUP
    assert season["team_count"] == 0
    assert season["certified_wrestler_count"] == 0
    assert_mutable_row(season, "season")
    assert_version_is(season, 1, "season")


# ── Reading a wrestler back ──────────────────────────────────────────

def test_wrestler_read_echoes_its_stored_inputs_and_both_dimensions(api):
    """A certified wrestler reads back its roster inputs and both state dimensions.

    §3.1 fixes the payload a roster addition carries and the parent team the
    row takes; §3.5 moves the certification dimension to CERTIFIED and the
    eligibility dimension to ELIGIBLE when the owning team is CLEAR.

    Design: Corner/entities/wrestler_retrieval_returns_stored_and_certified_figures
    """
    scenario = fixtures.certified_wrestler(api)

    wrestler = validate_success(api.get_wrestler(scenario.wrestler_id, STATE_OFFICE))

    assert wrestler["id"] == scenario.wrestler_id
    assert wrestler["team_id"] == scenario.team_id
    assert wrestler["full_name"] == constants.DEFAULT_WRESTLER_NAME
    assert wrestler["sex"] == constants.SEX_MALE
    assert wrestler["grade"] == constants.DEFAULT_WRESTLER_GRADE
    assert wrestler["certification_status"] == constants.WRESTLER_CERTIFIED
    assert wrestler["eligibility_status"] == constants.ELIGIBILITY_ELIGIBLE
    assert wrestler["open_health_flag_count"] == 0
    assert wrestler["disqualified_at"] is None
    assert wrestler["certification_hold_reason"] is None
    assert_mutable_row(wrestler, "wrestler")


def test_wrestler_read_returns_the_figures_copied_from_its_source_assessment(api):
    """The five certified figures on the wrestler come from the validated assessment.

    §3.3 recomputes the wrestler's alpha weight, body fat, minimum certified
    weight and minimum class from the newly validated assessment: a 159.6 pound
    measurement at 14.0 percent under the 7.0 percent male floor yields 147.6
    pounds and a 150 pound class.

    Design: Corner/entities/wrestler_retrieval_returns_stored_and_certified_figures
    """
    scenario = fixtures.certified_wrestler(api)

    wrestler = validate_success(api.get_wrestler(scenario.wrestler_id, STATE_OFFICE))

    assert wrestler["source_assessment_id"] == scenario.assessment_id
    assert_weight_equals(
        wrestler["alpha_weight_lbs"], constants.CANON_ALPHA_WEIGHT_LBS, "alpha"
    )
    assert_weight_equals(
        wrestler["body_fat_pct"], constants.CANON_BODY_FAT_PCT, "body_fat_pct"
    )
    assert_weight_equals(
        wrestler["minimum_certified_weight_lbs"],
        constants.CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
        "minimum_certified_weight_lbs",
    )
    assert wrestler["min_weight_class_lbs"] == constants.CANON_MIN_WEIGHT_CLASS_LBS


# ── The assessment listing ───────────────────────────────────────────

def _three_draft_assessments(api):
    """One wrestler with exactly three draft assessments on the same UTC day."""
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    drafts = [
        fixtures.create_assessment(
            api,
            wrestler["id"],
            assessor["id"],
            method=method,
            assessed_at=assessed_at,
            measured_weight_lbs=measured,
            body_fat_pct=body_fat,
            urine_specific_gravity=usg,
        )
        for method, assessed_at, measured, body_fat, usg in (
            (constants.METHOD_SKINFOLD, "2026-11-01T07:00:00Z", 159.6, 14.0, 1.020),
            (constants.METHOD_BIA, "2026-11-01T08:00:00Z", 159.4, 14.2, 1.019),
            (constants.METHOD_SKINFOLD, "2026-11-01T09:00:00Z", 159.2, 14.4, 1.018),
        )
    ]
    scenario.update(
        assessor_id=assessor["id"],
        wrestler_id=wrestler["id"],
        drafts=drafts,
    )
    return scenario


def test_assessment_listing_windows_three_drafts_across_two_pages(api):
    """A limit of two over three matching rows pages 2 + 1 and flips has_more.

    §2.3 makes total_count the number of rows matching the filter before the
    window is applied, and has_more true only while rows remain beyond it.

    Design: Corner/entities/assessments_listing_paginates_and_filters
    """
    scenario = _three_draft_assessments(api)
    query = {
        "wrestler_id": scenario.wrestler_id,
        "status": constants.ASSESSMENT_DRAFT,
        "limit": 2,
    }

    first = api.list_assessments(STATE_OFFICE, dict(query, offset=0))
    page_one, meta_one = paginated_rows(first)
    assert first.json()["response_type"] == "array"
    assert len(page_one) == 2
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True

    second = api.list_assessments(STATE_OFFICE, dict(query, offset=2))
    page_two, meta_two = paginated_rows(second)
    assert len(page_two) == 1
    assert meta_two["limit"] == 2
    assert meta_two["offset"] == 2
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    seen = ids_of(page_one) + ids_of(page_two)
    assert len(set(seen)) == 3
    assert set(seen) == {draft["id"] for draft in scenario.drafts}


def test_assessment_listing_narrows_by_wrestler_and_status(api):
    """Every row a filtered assessment listing returns matches both filters.

    §3.3 declares the assessment list narrowable by wrestler_id and status.

    Design: Corner/entities/assessments_listing_paginates_and_filters
    """
    scenario = _three_draft_assessments(api)

    response = api.list_assessments(
        STATE_OFFICE,
        {
            "wrestler_id": scenario.wrestler_id,
            "status": constants.ASSESSMENT_DRAFT,
            "limit": 10,
        },
    )
    rows = assert_row_count(response, 3, "draft assessments")
    for row in rows:
        assert row["status"] == constants.ASSESSMENT_DRAFT
        assert row["wrestler_id"] == scenario.wrestler_id


# ── Unknown identifiers on the single-row reads ──────────────────────

@pytest.mark.parametrize("method_name,expected_error", _SINGLE_ROW_READS)
def test_unknown_id_on_a_single_row_read_returns_its_own_not_found(
    api, method_name, expected_error
):
    """Each single-row read answers an unknown id with its entity's own 404.

    §2.8 lists one not-found identifier per resource family, all HTTP 404, and
    resolves path identifiers strictly left to right.

    Design: Corner/entities/unknown_ids_on_every_read_endpoint_return_not_found
    """
    response = getattr(api, method_name)(_UNKNOWN_ID, STATE_OFFICE)

    assert response.status_code == 404
    error = validate_error(response, expected_error, 404)
    assert error["message"].strip()


# ── The roster payload's required fields ─────────────────────────────

@pytest.mark.parametrize(
    "label,payload",
    [
        (
            "full_name omitted",
            _wrestler_body(sex=constants.SEX_MALE, grade=11),
        ),
        (
            "sex omitted",
            _wrestler_body(full_name=constants.DEFAULT_WRESTLER_NAME, grade=11),
        ),
        (
            "grade omitted",
            _wrestler_body(
                full_name=constants.DEFAULT_WRESTLER_NAME, sex=constants.SEX_MALE
            ),
        ),
    ],
)
def test_wrestler_creation_requires_each_declared_input(api, label, payload):
    """Each of the three roster inputs is individually required.

    §3.1 says the payload carries full_name, sex and grade; §2.8 refuses a
    request-body shape failure with ERR_INVALID_REQUEST.

    Design: Corner/entities/wrestler_creation_missing_required_fields_rejected
    """
    scenario = fixtures.open_season_with_team(api)

    response = api.create_wrestler(
        scenario.team_id, payload, coach_headers(scenario.team_id)
    )

    assert response.status_code == 400, label
    validate_error(response, api_errors.ERR_INVALID_REQUEST, 400)


def test_rejected_wrestler_creations_leave_the_roster_empty(api):
    """A refused roster addition creates no row, so the counters do not move.

    §3.1 says adding a wrestler increments the team's roster_count; a rejected
    call adds nobody, and §2.4 starts version at 1 and increments it only on a
    mutation of that row.

    Design: Corner/entities/wrestler_creation_missing_required_fields_rejected
    """
    scenario = fixtures.open_season_with_team(api)
    coach = coach_headers(scenario.team_id)

    for payload in (
        _wrestler_body(sex=constants.SEX_MALE, grade=11),
        _wrestler_body(full_name=constants.DEFAULT_WRESTLER_NAME, grade=11),
        _wrestler_body(
            full_name=constants.DEFAULT_WRESTLER_NAME, sex=constants.SEX_MALE
        ),
    ):
        validate_error(
            api.create_wrestler(scenario.team_id, payload, coach),
            api_errors.ERR_INVALID_REQUEST,
            400,
        )

    team = validate_success(api.get_team(scenario.team_id, STATE_OFFICE))
    assert team["roster_count"] == 0
    assert_version_is(team, 1, "team")

    listing = api.list_wrestlers(STATE_OFFICE, {"team_id": scenario.team_id})
    assert_row_count(listing, 0, "roster listing")


# ── The event's declared shape defaults ──────────────────────────────

def test_event_creation_applies_its_three_shape_defaults(api):
    """Omitting the three optional event inputs yields 1, 1 and 1.0.

    §3.7 defaults competition_days to 1, weigh_in_days to 1 and
    consecutive_day_allowance_lbs to 1.0.

    Design: Corner/entities/event_creation_applies_declared_defaults
    """
    scenario = fixtures.open_season_with_team(api)
    payload = {
        "name": "Northgate Duals",
        "event_type": constants.EVENT_TYPE_DUAL,
        "event_date": "2026-11-04",
    }

    event = validate_success(
        api.create_event(scenario.season_id, payload, STATE_OFFICE), 201
    )

    assert event["season_id"] == scenario.season_id
    assert event["name"] == "Northgate Duals"
    assert event["event_type"] == constants.EVENT_TYPE_DUAL
    assert event["event_date"] == "2026-11-04"
    assert event["competition_days"] == constants.DEFAULT_COMPETITION_DAYS
    assert event["weigh_in_days"] == constants.DEFAULT_WEIGH_IN_DAYS
    assert event["consecutive_day_allowance_lbs"] == pytest.approx(
        constants.DEFAULT_CONSECUTIVE_DAY_ALLOWANCE_LBS, abs=0.01
    )


def test_event_creation_starts_scheduled_with_a_zeroed_bracket(api):
    """A freshly scheduled event carries an unlocked, empty bracket.

    §3.7 starts an event in SCHEDULED with bracket_locked and reseed_required
    false and entry_count, weighed_in_count, seeded_entry_count and
    seed_integrity_sum all 0.

    Design: Corner/entities/event_creation_applies_declared_defaults
    """
    scenario = fixtures.open_season_with_team(api)
    payload = {
        "name": "Northgate Duals",
        "event_type": constants.EVENT_TYPE_DUAL,
        "event_date": "2026-11-04",
    }

    event = validate_success(
        api.create_event(scenario.season_id, payload, STATE_OFFICE), 201
    )

    assert event["status"] == constants.EVENT_SCHEDULED
    assert event["bracket_locked"] is False
    assert event["reseed_required"] is False
    assert event["entry_count"] == 0
    assert event["weighed_in_count"] == 0
    assert event["seeded_entry_count"] == 0
    assert event["seed_integrity_sum"] == 0
    assert_mutable_row(event, "event")
    assert_version_is(event, 1, "event")


# ── The assessment's computed figures ────────────────────────────────

def _assessment_body_with_computed_figures(assessor_id):
    """A draft assessment body that also carries the server-computed figures."""
    payload = factories.assessment_payload(
        assessor_id=assessor_id,
        method=constants.METHOD_SKINFOLD,
        assessed_at=constants.ASSESSED_AT,
        measured_weight_lbs=constants.CANON_MEASURED_WEIGHT_LBS,
        body_fat_pct=constants.CANON_BODY_FAT_PCT,
        urine_specific_gravity=constants.CANON_USG_PASS,
    )
    payload.update(
        {
            "lean_body_weight_lbs": 999.9,
            "minimum_certified_weight_lbs": 1.0,
            "min_weight_class_lbs": 106,
            "alpha_weight_lbs": 0.1,
            "status": constants.ASSESSMENT_VALIDATED,
            "hydration_passed": False,
        }
    )
    return payload


def test_assessment_creation_leaves_every_derived_figure_null(api):
    """Opening an assessment computes nothing, whatever the client sends.

    §3.3 lands the new row in DRAFT with hydration_passed,
    lean_body_weight_lbs, minimum_certified_weight_lbs, min_weight_class_lbs,
    alpha_weight_lbs and void_reason all null — no certified figure whatsoever
    is computed until finalize.

    Design: Corner/entities/assessment_computed_figures_client_input_ignored
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)

    response = api.create_assessment(
        wrestler["id"],
        _assessment_body_with_computed_figures(assessor["id"]),
        assessor_headers(assessor["id"]),
    )
    assessment = validate_success(response, 201)

    assert assessment["status"] == constants.ASSESSMENT_DRAFT
    assert assessment["hydration_passed"] is None
    assert assessment["lean_body_weight_lbs"] is None
    assert assessment["minimum_certified_weight_lbs"] is None
    assert assessment["min_weight_class_lbs"] is None
    assert assessment["alpha_weight_lbs"] is None
    assert assessment["void_reason"] is None


def test_assessment_finalize_writes_the_figures_the_formula_derives(api):
    """Finalize derives 137.3, 147.6, 150 and 159.6 from the recorded readings.

    §3.3 rounds the lean weight to one decimal place before it is divided by
    one minus the male floor, and copies the measured weight into the alpha
    weight unchanged; the minimum class is the smallest ladder member at or
    above the minimum certified weight.

    Design: Corner/entities/assessment_computed_figures_client_input_ignored
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    draft = validate_success(
        api.create_assessment(
            wrestler["id"],
            _assessment_body_with_computed_figures(assessor["id"]),
            assessor_headers(assessor["id"]),
        ),
        201,
    )

    finalized = validate_success(
        api.finalize_assessment(draft["id"], assessor_headers(assessor["id"]))
    )

    assert finalized["status"] == constants.ASSESSMENT_VALIDATED
    assert finalized["hydration_passed"] is True
    assert_weight_equals(
        finalized["lean_body_weight_lbs"],
        constants.CANON_LEAN_BODY_WEIGHT_LBS,
        "lean_body_weight_lbs",
    )
    assert_weight_equals(
        finalized["minimum_certified_weight_lbs"],
        constants.CANON_MINIMUM_CERTIFIED_WEIGHT_LBS,
        "minimum_certified_weight_lbs",
    )
    assert finalized["min_weight_class_lbs"] == constants.CANON_MIN_WEIGHT_CLASS_LBS
    assert_weight_equals(
        finalized["alpha_weight_lbs"],
        constants.CANON_ALPHA_WEIGHT_LBS,
        "alpha_weight_lbs",
    )


# ── The team's server-owned fields ───────────────────────────────────

def _team_body_with_system_fields(season_id):
    """A team registration body that also carries every server-owned field."""
    payload = factories.team_payload(season_id, constants.DEFAULT_TEAM_NAME)
    payload.update(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "created_at": "2000-01-01T00:00:00Z",
            "updated_at": "2000-01-01T00:00:00Z",
            "version": 47,
            "roster_count": 99,
            "open_flag_severity_total": 12,
            "compliance_status": constants.TEAM_PROBATION,
        }
    )
    return payload


def test_team_registration_mints_its_own_identity_and_derived_fields(api):
    """A registered team starts clear and empty at version 1, whatever is sent.

    §2.4 mints the id and the timestamps server-side and starts version at 1;
    §3.1 starts a new team with compliance_status CLEAR,
    open_flag_severity_total 0 and roster_count 0.

    Design: Corner/entities/team_system_fields_client_input_ignored
    """
    scenario = fixtures.create_open_season(api)

    team = validate_success(
        api.create_team(_team_body_with_system_fields(scenario["id"]), STATE_OFFICE),
        201,
    )

    assert team["id"] != "11111111-1111-1111-1111-111111111111"
    assert team["created_at"] != "2000-01-01T00:00:00Z"
    assert team["season_id"] == scenario["id"]
    assert team["school_name"] == constants.DEFAULT_TEAM_NAME
    assert team["roster_count"] == 0
    assert team["open_flag_severity_total"] == 0
    assert team["compliance_status"] == constants.TEAM_CLEAR
    assert_mutable_row(team, "team")
    assert_version_is(team, 1, "team")


def test_team_registration_moves_the_season_team_count_to_one(api):
    """Registering a team increments the season's derived team count.

    §3.1 says registering a team increments the season's team_count.

    Design: Corner/entities/team_system_fields_client_input_ignored
    """
    season = fixtures.create_open_season(api)
    assert season["team_count"] == 0

    validate_success(
        api.create_team(_team_body_with_system_fields(season["id"]), STATE_OFFICE), 201
    )

    reread = validate_success(api.get_season(season["id"], STATE_OFFICE))
    assert reread["team_count"] == 1


# ── Enum membership and declared numeric ranges ──────────────────────

@pytest.mark.parametrize(
    "label,sex,grade",
    [
        ("sex outside the declared pair", "X", 11),
        ("grade below the range", constants.SEX_MALE, 8),
        ("grade above the range", constants.SEX_FEMALE, 13),
    ],
)
def test_wrestler_creation_rejects_bad_enum_and_out_of_range_grade(
    api, label, sex, grade
):
    """A sex outside {M, F} and a grade outside 9 to 12 are shape failures.

    §3.1 declares sex as either M or F and grade between 9 and 12; §2.8 pins
    that range as an inclusive closed range enforced by the shape check and
    refused with ERR_INVALID_REQUEST.

    Design: Corner/entities/wrestler_creation_invalid_enum_and_range_rejected
    """
    scenario = fixtures.open_season_with_team(api)

    response = api.create_wrestler(
        scenario.team_id,
        factories.wrestler_payload("Probe Wrestler", sex, grade),
        coach_headers(scenario.team_id),
    )

    assert response.status_code == 400, label
    validate_error(response, api_errors.ERR_INVALID_REQUEST, 400)


@pytest.mark.parametrize(
    "label,overrides",
    [
        ("measured weight above 400.0", {"measured_weight_lbs": 400.1}),
        ("specific gravity above 1.060", {"urine_specific_gravity": 1.061}),
        ("method outside the declared enum", {"method": "CALIPER_PLUS"}),
    ],
)
def test_assessment_creation_rejects_out_of_range_and_unknown_enum(
    api, label, overrides
):
    """Readings outside their closed ranges and an unknown method are 400s.

    §2.8 enforces measured_weight_lbs between 60.0 and 400.0 and
    urine_specific_gravity between 1.000 and 1.060 in the shape check, and puts
    enum membership in that same step — ahead of the credentialing rule that
    would otherwise answer ERR_METHOD_NOT_CERTIFIED — so all three are
    ERR_INVALID_REQUEST.

    Design: Corner/entities/wrestler_creation_invalid_enum_and_range_rejected
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    payload = factories.assessment_payload(assessor_id=assessor["id"])
    payload.update(overrides)

    response = api.create_assessment(
        wrestler["id"], payload, assessor_headers(assessor["id"])
    )

    assert response.status_code == 400, label
    validate_error(response, api_errors.ERR_INVALID_REQUEST, 400)


def test_shape_rejected_creations_store_neither_wrestler_nor_assessment(api):
    """None of the six refused calls leaves a row behind.

    §2.8 evaluates the shape check before any domain rule runs, so a refused
    request produces no stored row at all.

    Design: Corner/entities/wrestler_creation_invalid_enum_and_range_rejected
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    coach = coach_headers(scenario.team_id)
    assessor_auth = assessor_headers(assessor["id"])

    for sex, grade in (("X", 11), (constants.SEX_MALE, 8), (constants.SEX_FEMALE, 13)):
        validate_error(
            api.create_wrestler(
                scenario.team_id,
                factories.wrestler_payload("Probe Wrestler", sex, grade),
                coach,
            ),
            api_errors.ERR_INVALID_REQUEST,
            400,
        )
    for overrides in (
        {"measured_weight_lbs": 400.1},
        {"urine_specific_gravity": 1.061},
        {"method": "CALIPER_PLUS"},
    ):
        payload = factories.assessment_payload(assessor_id=assessor["id"])
        payload.update(overrides)
        validate_error(
            api.create_assessment(wrestler["id"], payload, assessor_auth),
            api_errors.ERR_INVALID_REQUEST,
            400,
        )

    roster = api.list_wrestlers(STATE_OFFICE, {"team_id": scenario.team_id})
    rows = assert_row_count(roster, 1, "roster listing")
    assert rows[0]["id"] == wrestler["id"]

    assessments = api.list_assessments(STATE_OFFICE, {"wrestler_id": wrestler["id"]})
    assert_row_count(assessments, 0, "assessment listing")


# ── The three append-only rows ───────────────────────────────────────

def test_published_growth_allowance_is_append_only(api):
    """A published growth-allowance date carries no version and no updated_at.

    §2.4 makes GrowthAllowance one of the three deliberately append-only
    resource types: both updated_at and version are absent from the stored row
    and from every response, and §3.1 declares the fields it does carry.

    Design: Corner/entities/immutable_entities_expose_no_version_and_no_update_endpoint
    """
    season = fixtures.create_open_season(api)

    allowance = validate_success(
        api.create_growth_allowance(
            season["id"],
            factories.growth_allowance_payload(
                "2026-12-01", 1.0, "December growth date"
            ),
            STATE_OFFICE,
        ),
        201,
    )

    assert_append_only_row(allowance, "growth allowance")
    assert allowance["season_id"] == season["id"]
    assert allowance["effective_date"] == "2026-12-01"
    assert_weight_equals(allowance["allowance_lbs"], 1.0, "allowance_lbs")
    assert allowance["note"] == "December growth date"

    listing = api.list_growth_allowances(season["id"], STATE_OFFICE)
    rows = assert_row_count(listing, 1, "growth-allowance listing")
    assert rows[0]["id"] == allowance["id"]
    assert_weight_equals(rows[0]["allowance_lbs"], 1.0, "listed allowance_lbs")
    assert_append_only_row(rows[0], "listed growth allowance")


def test_logged_eligibility_check_is_append_only_and_rereads_identically(api):
    """A logged certification-database check carries no version and never changes.

    §2.4 makes EligibilityCheck append-only — a logged check is a historical
    fact the service never edits in place; §3.7 stamps checked_at from the
    logical clock and copies as_of_date from the referenced event's event_date.

    Design: Corner/entities/immutable_entities_expose_no_version_and_no_update_endpoint
    """
    scenario = fixtures.open_season_with_team(api)
    wrestler = fixtures.create_wrestler(api, scenario.team_id)
    event = fixtures.create_event(
        api, scenario.season_id, "Northgate Duals", "2026-12-12",
        constants.EVENT_TYPE_DUAL,
    )

    check = validate_success(
        api.create_eligibility_check(
            wrestler["id"],
            factories.eligibility_check_payload(event["id"], 150),
            STATE_OFFICE,
        ),
        201,
    )

    assert_append_only_row(check, "eligibility check")
    assert check["wrestler_id"] == wrestler["id"]
    assert check["event_id"] == event["id"]
    assert check["requested_class_lbs"] == 150
    assert check["as_of_date"] == "2026-12-12"
    assert_instant_equals(
        check["checked_at"], constants.ASSESSMENT_DAY_INSTANT, "checked_at"
    )

    reread = validate_success(api.get_eligibility_check(check["id"], STATE_OFFICE))
    assert reread == check


def test_recorded_weigh_in_is_append_only(api):
    """A weigh-in reading carries no version and no updated_at.

    §2.4 makes WeighIn append-only: a weigh-in reading is a historical fact, so
    both updated_at and version are absent from every response.

    Design: Corner/entities/immutable_entities_expose_no_version_and_no_update_endpoint
    """
    scenario = fixtures.entered_wrestler(api)
    fixtures.move_clock(api, "2026-12-12T09:00:00Z")
    fixtures.open_weigh_ins(api, scenario.event_id)

    weigh_in = validate_success(
        api.create_weigh_in(
            scenario.event_id,
            factories.weigh_in_payload(scenario.entry_id, 0, 149.0),
            WEIGH_IN_OFFICIAL,
        ),
        201,
    )

    assert_append_only_row(weigh_in, "weigh-in")
    assert weigh_in["entry_id"] == scenario.entry_id
    assert weigh_in["wrestler_id"] == scenario.wrestler_id
    assert weigh_in["day_index"] == 0
    assert_weight_equals(weigh_in["recorded_weight_lbs"], 149.0, "recorded_weight_lbs")

    reread = validate_success(api.get_weigh_in(weigh_in["id"], STATE_OFFICE))
    assert_append_only_row(reread, "reread weigh-in")


# ── Parent resolution on a child creation ────────────────────────────

def test_wrestler_creation_under_an_unknown_team_is_team_not_found(api):
    """A roster addition resolves its path team before anything else.

    §2.8 resolves path identifiers strictly left to right and the first
    unresolvable segment determines the error, which for a team segment is
    ERR_TEAM_NOT_FOUND.

    Design: Corner/entities/wrestler_creation_under_unknown_parent_returns_not_found
    """
    scenario = fixtures.open_season_with_team(api)

    response = api.create_wrestler(
        "00000000-0000-4000-8000-0000000000c1",
        factories.wrestler_payload("Orphan Wrestler", constants.SEX_MALE, 11),
        STATE_OFFICE,
    )

    assert response.status_code == 404
    validate_error(response, api_errors.ERR_TEAM_NOT_FOUND, 404)

    season = validate_success(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season["team_count"] == 1


def test_event_creation_under_an_unknown_season_is_season_not_found(api):
    """Scheduling an event resolves its path season before anything else.

    §2.8 answers an unresolvable season segment with ERR_SEASON_NOT_FOUND at
    HTTP 404, ahead of every body-level check.

    Design: Corner/entities/wrestler_creation_under_unknown_parent_returns_not_found
    """
    scenario = fixtures.open_season_with_team(api)

    response = api.create_event(
        "00000000-0000-4000-8000-0000000000c2",
        factories.event_payload(
            "Ghost Duals", "2026-11-04", constants.EVENT_TYPE_DUAL
        ),
        STATE_OFFICE,
    )

    assert response.status_code == 404
    validate_error(response, api_errors.ERR_SEASON_NOT_FOUND, 404)

    listing = api.list_events(STATE_OFFICE, {"season_id": scenario.season_id})
    assert_row_count(listing, 0, "event listing")


# ── The entry junction between events and wrestlers ──────────────────

def _two_wrestlers_across_two_events(api):
    """Two certified wrestlers, two disjoint one-day events, three entries.

    Both wrestlers are assessed at 159.6 pounds and 14.0 percent, so each
    carries a 147.6 pound minimum and a 150 pound hard-floor class, and both run
    a WEEKLY_STEP plan from 2026-11-02.  The two competition windows —
    [2026-11-04, 2026-11-05) and [2026-11-12, 2026-11-13) — are disjoint, so the
    same wrestler may hold an entry on both.
    """
    scenario = fixtures.open_season_with_team(api)
    assessor = fixtures.create_certified_assessor(api)

    wrestler_a = fixtures.create_wrestler(
        api, scenario.team_id, constants.DEFAULT_WRESTLER_NAME, constants.SEX_MALE, 11
    )
    wrestler_b = fixtures.create_wrestler(
        api, scenario.team_id, "Bailey Nguyen", constants.SEX_MALE, 12
    )
    assessment_a = fixtures.create_validated_assessment(
        api, wrestler_a["id"], assessor["id"], assessed_at="2026-11-01T09:00:00Z"
    )
    assessment_b = fixtures.create_validated_assessment(
        api, wrestler_b["id"], assessor["id"], assessed_at="2026-11-01T10:00:00Z"
    )
    for wrestler, assessment in (
        (wrestler_a, assessment_a),
        (wrestler_b, assessment_b),
    ):
        fixtures.create_certified_plan(
            api,
            wrestler["id"],
            scenario.team_id,
            assessment["id"],
            target_class_lbs=constants.CANON_TARGET_CLASS_LBS,
            plan_start_date=constants.PLAN_START_DATE,
            plan_variant=constants.VARIANT_WEEKLY_STEP,
        )

    event_one = fixtures.create_event(
        api, scenario.season_id, "Northgate Duals", "2026-11-04",
        constants.EVENT_TYPE_DUAL,
    )
    event_two = fixtures.create_event(
        api, scenario.season_id, "Riverside Invitational", "2026-11-12",
        constants.EVENT_TYPE_TOURNAMENT,
    )

    coach = coach_headers(scenario.team_id)
    responses = [
        api.create_entry(
            event_one["id"],
            factories.entry_payload(wrestler_a["id"], 165, 5),
            coach,
        ),
        api.create_entry(
            event_one["id"],
            factories.entry_payload(wrestler_b["id"], 165, 3),
            coach,
        ),
        api.create_entry(
            event_two["id"],
            factories.entry_payload(wrestler_a["id"], 165, 5),
            coach,
        ),
    ]
    entries = [validate_success(response, 201) for response in responses]

    scenario.update(
        wrestler_a_id=wrestler_a["id"],
        wrestler_b_id=wrestler_b["id"],
        event_one_id=event_one["id"],
        event_two_id=event_two["id"],
        entry_a1=entries[0],
        entry_b1=entries[1],
        entry_a2=entries[2],
        entries=entries,
    )
    return scenario


def test_one_wrestler_reaches_both_of_its_entries_by_wrestler_id(api):
    """A wrestler entered on two non-overlapping events has two entries.

    §3.7 permits a second entry whenever the half-open competition windows do
    not overlap, lands each entry in ENTERED with seed_number,
    latest_effective_weight_lbs and scratch_reason null and
    weight_class_change_count at 0, and declares the entry list narrowable by
    wrestler_id.

    Design: Corner/entities/junction_entries_resolve_event_and_wrestler_both_ways
    """
    scenario = _two_wrestlers_across_two_events(api)

    for entry in scenario.entries:
        assert entry["status"] == constants.ENTRY_ENTERED
        assert entry["seed_number"] is None
        assert entry["latest_effective_weight_lbs"] is None
        assert entry["scratch_reason"] is None
        assert entry["weight_class_change_count"] == 0
        assert entry["weight_class_lbs"] == 165

    listing = api.list_entries(STATE_OFFICE, {"wrestler_id": scenario.wrestler_a_id})
    rows = assert_row_count(listing, 2, "entries by wrestler")
    assert set(ids_of(rows)) == {
        scenario.entry_a1["id"],
        scenario.entry_a2["id"],
    }
    assert {row["event_id"] for row in rows} == {
        scenario.event_one_id,
        scenario.event_two_id,
    }


def test_one_event_reaches_both_of_its_entries_by_event_id(api):
    """An event holding two wrestlers reports both entries and counts them.

    §3.7 declares the entry list narrowable by event_id and increments the
    event's entry_count on each successful entry; §3.8 counts only entries in
    WEIGHED_IN or SEEDED in weighed_in_count.

    Design: Corner/entities/junction_entries_resolve_event_and_wrestler_both_ways
    """
    scenario = _two_wrestlers_across_two_events(api)

    listing = api.list_entries(STATE_OFFICE, {"event_id": scenario.event_one_id})
    rows = assert_row_count(listing, 2, "entries by event")
    assert set(ids_of(rows)) == {
        scenario.entry_a1["id"],
        scenario.entry_b1["id"],
    }
    assert {row["wrestler_id"] for row in rows} == {
        scenario.wrestler_a_id,
        scenario.wrestler_b_id,
    }

    event = validate_success(api.get_event(scenario.event_one_id, STATE_OFFICE))
    assert event["entry_count"] == 2
    assert event["weighed_in_count"] == 0

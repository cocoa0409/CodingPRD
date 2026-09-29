"""Risk stratification: the two variants, the weighting rules and the bands."""
import pytest

from test_helpers import (
    ApiErrorId, PROGRAM_ADMIN, UTILIZATION_ANALYST, assert_risk_stratification,
    create_member, enroll, identify_social_need, read_member, record_event,
    setup_program_and_managers, stratify, validate_error, validate_paginated,
    validate_success,
)

# The clock is left at its startup instant throughout this file, so every event
# age below is measured from 2026-08-01T00:00:00Z.
DIVERGENCE_EVENTS = [
    {"event_type": "INPATIENT_ADMISSION", "occurred_at": "2026-06-15T00:00:00Z",
     "facility_name": "Bay General", "episode_cost_cents": 0,
     "adjudication_status": "CLOSED"},
    {"event_type": "ED_VISIT", "occurred_at": "2026-03-01T00:00:00Z",
     "facility_name": "Bay General", "episode_cost_cents": 0,
     "adjudication_status": "CLOSED"},
    {"event_type": "ED_VISIT", "occurred_at": "2026-07-20T00:00:00Z",
     "facility_name": "Bay General", "episode_cost_cents": 0,
     "adjudication_status": "OPEN"},
    {"event_type": "SCHEDULED_ADMISSION", "occurred_at": "2026-09-10T00:00:00Z",
     "facility_name": "Bay Ortho", "episode_cost_cents": 0,
     "adjudication_status": "OPEN"},
]


def _member_with_divergence_events(external_member_id="MBR-1001"):
    member = create_member(
        external_member_id=external_member_id, full_name="Ana Vega",
        birth_date="1958-04-11", state_code="CA", chronic_condition_count=4,
        social_data_consent_status="GRANTED",
    )
    for event in DIVERGENCE_EVENTS:
        record_event(member["id"], **event)
    return member


def test_concurrent_variant_ignores_open_claims_and_booked_admissions(api):
    """PRD §3.2: "Under `CONCURRENT`, an event is included when its `event_type`
    is `INPATIENT_ADMISSION`, `ED_VISIT` or `OBSERVATION_STAY`, its
    `adjudication_status` is `CLOSED`, and its `occurred_at` falls inside the
    retrospective window; `SCHEDULED_ADMISSION` records are excluded entirely."
    PRD §3.2: "The `tier` bands the score: `HIGH` when the score is 85 or more,
    `RISING` when the score is at least 60 but below 85, `MODERATE` when the
    score is at least 35 but below 60, and `LOW` when the score is below 35."

    Design: Difficulty/dual_variant_calc/stratification_variant_divergence_on_member_utilization
    """
    member = _member_with_divergence_events()

    data = validate_success(
        api.create_stratification(member["id"], {"variant": "CONCURRENT"},
                                  UTILIZATION_ANALYST),
        201,
    )
    assert_risk_stratification(data)
    assert data["utilization_points"] == pytest.approx(24.0, abs=0.05)
    assert data["chronic_points"] == pytest.approx(24, abs=0.05)
    assert data["included_event_count"] == 2, (
        "only the two CLOSED retrospective events earn utilization points"
    )
    assert data["score"] == 48
    assert data["tier"] == "MODERATE"

    member_now = read_member(member["id"])
    assert member_now["latest_concurrent_score"] == 48
    assert member_now["latest_concurrent_tier"] == "MODERATE"


def test_prospective_variant_counts_pending_claims_and_booked_admissions(api):
    """PRD §3.2: "Under `PROSPECTIVE`, the same three retrospective event types
    are included whether their `adjudication_status` is `CLOSED` or `OPEN`, and to
    those are added every `SCHEDULED_ADMISSION` whose `occurred_at` falls inside
    the forward window."
    PRD §3.2: "The consequence is intended: a member with pending claims and a
    booked admission scores strictly lower under `CONCURRENT` than under
    `PROSPECTIVE`."

    Design: Difficulty/dual_variant_calc/stratification_variant_divergence_on_member_utilization
    """
    member = _member_with_divergence_events(external_member_id="MBR-1002")

    concurrent = validate_success(
        api.create_stratification(member["id"], {"variant": "CONCURRENT"},
                                  UTILIZATION_ANALYST),
        201,
    )
    prospective = validate_success(
        api.create_stratification(member["id"], {"variant": "PROSPECTIVE"},
                                  UTILIZATION_ANALYST),
        201,
    )

    assert prospective["utilization_points"] == pytest.approx(52.0, abs=0.05)
    assert prospective["chronic_points"] == pytest.approx(24, abs=0.05)
    assert prospective["included_event_count"] == 4
    assert prospective["score"] == 76
    assert prospective["tier"] == "RISING"
    assert prospective["score"] > concurrent["score"], (
        "the pending claim and the booked admission only score under PROSPECTIVE"
    )

    member_now = read_member(member["id"])
    assert member_now["latest_prospective_score"] == 76
    assert member_now["latest_prospective_tier"] == "RISING"
    assert member_now["latest_concurrent_score"] == 48
    assert member_now["latest_concurrent_tier"] == "MODERATE"


def _member_with_boundary_events(external_member_id, full_name, with_observation):
    member = create_member(
        external_member_id=external_member_id, full_name=full_name,
        birth_date="1951-03-03", state_code="CA", chronic_condition_count=3,
    )
    for occurred_at in ("2026-06-01T00:00:00Z", "2026-06-20T00:00:00Z",
                        "2026-07-05T00:00:00Z"):
        record_event(member["id"], event_type="INPATIENT_ADMISSION",
                     occurred_at=occurred_at, episode_cost_cents=0,
                     adjudication_status="CLOSED")
    record_event(member["id"], event_type="ED_VISIT",
                 occurred_at="2026-03-01T00:00:00Z", episode_cost_cents=0,
                 adjudication_status="CLOSED")
    if with_observation:
        record_event(member["id"], event_type="OBSERVATION_STAY",
                     occurred_at="2026-03-10T00:00:00Z", episode_cost_cents=0,
                     adjudication_status="CLOSED")
    return member


def test_raw_score_at_the_midpoint_rounds_half_up_into_high(api):
    """PRD §3.2: "The final `score` is that raw figure rounded half up to a whole
    number and then capped at 100, so a raw figure of 130.4 reports as 100."
    PRD §3.2: "The `tier` bands the score: `HIGH` when the score is 85 or more,
    `RISING` when the score is at least 60 but below 85, `MODERATE` when the
    score is at least 35 but below 60, and `LOW` when the score is below 35."

    Design: Difficulty/boundary_precision_check/risk_score_half_up_at_exactly_85_promotes_to_high
    """
    member = _member_with_boundary_events("MBR-1401", "Bea Lund", with_observation=True)

    data = validate_success(
        api.create_stratification(member["id"], {"variant": "CONCURRENT"},
                                  UTILIZATION_ANALYST),
        201,
    )
    assert data["utilization_points"] == pytest.approx(66.5, abs=0.05)
    assert data["chronic_points"] == pytest.approx(18, abs=0.05)
    assert data["raw_score"] == pytest.approx(84.5, abs=0.05)
    assert data["score"] == 85, "84.5 rounds half up to 85"
    assert data["tier"] == "HIGH"
    assert read_member(member["id"])["latest_concurrent_tier"] == "HIGH"


def test_raw_score_one_step_below_the_boundary_stays_rising(api):
    """PRD §3.2: "`raw_score` is `utilization_points` plus `chronic_points` plus
    `social_need_points`, carried to one decimal place with no intermediate
    rounding of the individual terms."
    PRD §3.2: "The `tier` bands the score: `HIGH` when the score is 85 or more,
    `RISING` when the score is at least 60 but below 85, `MODERATE` when the
    score is at least 35 but below 60, and `LOW` when the score is below 35."

    Design: Difficulty/boundary_precision_check/risk_score_half_up_at_exactly_85_promotes_to_high
    """
    member = _member_with_boundary_events("MBR-1402", "Cal Reyes",
                                          with_observation=False)

    data = validate_success(
        api.create_stratification(member["id"], {"variant": "CONCURRENT"},
                                  UTILIZATION_ANALYST),
        201,
    )
    assert data["raw_score"] == pytest.approx(82.0, abs=0.05)
    assert data["score"] == 82
    assert data["tier"] == "RISING"
    assert read_member(member["id"])["latest_concurrent_tier"] == "RISING"


def test_stratification_with_undeclared_variant_is_rejected(api):
    """PRD §2.6: "on every write endpoint, each required input field is present,
    each enum-valued field holds a declared member of its enumeration, each
    integer or number field is of the correct type and satisfies its declared
    range constraint, and any instant-valued field such as `scheduled_end_at` or
    `service_end_at` parses as an ISO 8601 instant. Otherwise
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "Plan operations or the analytics function requests a stratification
    by naming a `variant`, either `CONCURRENT` or `PROSPECTIVE`."

    Design: Corner/entities/stratification_with_undeclared_variant_returns_invalid_request
    """
    member = create_member(external_member_id="MBR-3601", full_name="Enum Probe",
                           birth_date="1979-09-09", chronic_condition_count=1)

    response = api.create_stratification(
        member["id"], {"variant": "RETROSPECTIVE"}, UTILIZATION_ANALYST
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400

    rows, meta = validate_paginated(
        api.list_stratifications(member["id"], UTILIZATION_ANALYST)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_repeated_stratification_appends_an_immutable_row(api):
    """PRD §2.4: "Three record types are append-only ledgers rather than mutable
    resources, and they therefore carry only `id` and `created_at` — they have no
    `updated_at` and no `version` field at all."
    PRD §3.2: "The result is an immutable record carrying the `member_id` it was
    computed for, the `variant` used, an `as_of_date` stamped as the calendar date
    of the logical clock at computation time, the component point totals, the
    final `score` and `tier`, and `included_event_count` — the number of
    utilization events that actually contributed utilization points under this
    variant."

    Design: Corner/entities/risk_stratification_rows_are_append_only_without_version
    """
    member = create_member(external_member_id="MBR-3701", full_name="Append Ann",
                           birth_date="1963-06-06", chronic_condition_count=5)

    first = validate_success(
        api.create_stratification(member["id"], {"variant": "CONCURRENT"},
                                  UTILIZATION_ANALYST),
        201,
    )
    second = validate_success(
        api.create_stratification(member["id"], {"variant": "CONCURRENT"},
                                  UTILIZATION_ANALYST),
        201,
    )

    assert first["id"] != second["id"], "each run appends a new row"
    assert first["score"] == 30 and second["score"] == 30
    for row in (first, second):
        assert "version" not in row, "a stratification carries no version field"
        assert "updated_at" not in row, "a stratification carries no updated_at"

    rows, meta = validate_paginated(
        api.list_stratifications(member["id"], UTILIZATION_ANALYST,
                                 params={"variant": "CONCURRENT"})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert read_member(member["id"])["latest_concurrent_tier"] == "LOW"


def test_recency_factor_is_full_at_exactly_ninety_days(api):
    """PRD §3.2: "For every other included event, compute its age as the number of
    days from `occurred_at` to the computation instant, retaining the fractional
    part rather than truncating it; when that age is 90 days or less the recency
    factor is 1.0, and when it is greater than 90 days the factor is one half."
    PRD §3.2: "An event dated exactly 90 days before the computation instant
    therefore still earns its full weight."

    Design: Corner/calculations/stratification_recency_factor_full_at_exactly_ninety_days
    """
    on_boundary = create_member(external_member_id="MBR-5201", full_name="Edge A",
                                birth_date="1970-01-01")
    past_boundary = create_member(external_member_id="MBR-5202", full_name="Edge B",
                                  birth_date="1970-01-02")
    record_event(on_boundary["id"], event_type="ED_VISIT",
                 occurred_at="2026-05-03T00:00:00Z", episode_cost_cents=0,
                 adjudication_status="CLOSED")
    record_event(past_boundary["id"], event_type="ED_VISIT",
                 occurred_at="2026-05-02T00:00:00Z", episode_cost_cents=0,
                 adjudication_status="CLOSED")

    at_ninety = stratify(on_boundary["id"], "CONCURRENT")
    past_ninety = stratify(past_boundary["id"], "CONCURRENT")

    assert at_ninety["utilization_points"] == pytest.approx(8.0, abs=0.05)
    assert at_ninety["score"] == 8
    assert past_ninety["utilization_points"] == pytest.approx(4.0, abs=0.05)
    assert past_ninety["score"] == 4
    for row in (at_ninety, past_ninety):
        assert row["tier"] == "LOW"
        assert row["included_event_count"] == 1


def test_social_need_points_are_capped_at_three_needs_worth(api):
    """PRD §3.2: "`social_need_points` counts the member's open social needs —
    every social need whose `status` is `IDENTIFIED`, `REFERRED` or
    `UNMET_ESCALATED` and whose owning enrollment belongs to this member and has
    an `enrollment_status` of `PENDING` or `ACTIVE` — multiplies that count by 4
    points per need, and then caps the product at 12 points, so no member can earn
    more than three needs' worth of social points however many are open."

    Design: Corner/calculations/stratification_social_need_points_hit_the_declared_cap
    """
    setting = setup_program_and_managers(
        program_overrides={"name": "SDOH Cap Program",
                           "required_credential_levels": ["CHW"]},
        manager_overrides={"full_name": "Sol Vega"},
        with_reviewer=False,
    )
    member = create_member(external_member_id="MBR-5301", full_name="Cap Cathy",
                           birth_date="1982-02-02", chronic_condition_count=0)
    before = stratify(member["id"], "CONCURRENT")
    assert before["score"] == 0

    enrollment = enroll(member["id"], setting["program"]["id"],
                        setting["care_manager"]["id"])
    for domain, severity in (("FOOD", "SEVERE"), ("HOUSING", "SEVERE"),
                             ("TRANSPORTATION", "MODERATE"), ("UTILITIES", "LOW")):
        identify_social_need(enrollment["id"], setting["care_manager"]["id"],
                             domain=domain, severity=severity)

    after = stratify(member["id"], "CONCURRENT")
    assert after["social_need_points"] == pytest.approx(12.0, abs=0.05), (
        "four open needs are worth 16 raw points but the cap holds them to 12"
    )
    assert after["raw_score"] == pytest.approx(12.0, abs=0.05)
    assert after["score"] == 12
    assert after["tier"] == "LOW"


def test_risk_score_is_capped_at_one_hundred(api):
    """PRD §3.2: "The final `score` is that raw figure rounded half up to a whole
    number and then capped at 100, so a raw figure of 130.4 reports as 100."
    PRD §3.2: "`chronic_points` is the member's `chronic_condition_count`
    multiplied by 6 points per condition."

    Design: Corner/calculations/stratification_score_is_capped_at_one_hundred
    """
    member = create_member(external_member_id="MBR-5401", full_name="Cap Carl",
                           birth_date="1945-05-05", chronic_condition_count=20)

    data = stratify(member["id"], "CONCURRENT")
    assert data["chronic_points"] == pytest.approx(120.0, abs=0.05)
    assert data["raw_score"] == pytest.approx(120.0, abs=0.05)
    assert data["score"] == 100, "the cap applies to score, not to raw_score"
    assert data["tier"] == "HIGH"

"""Entity creation, defaults, required-field and not-found validation, and the
matching-engine computed fields on a fresh screening (PRD §3.1, §3.3, §2.7)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_trial_payload, create_participant_payload, screen_participant_payload,
    create_criterion_payload,
    assert_trial, assert_participant, assert_screening,
    set_clock,
    create_trial, add_criterion, create_participant,
    TEST_USERS, make_sponsor_headers,
)

NON_EXISTENT_TRIAL_UUID = "00000000-0000-4000-8000-000000000000"


def test_create_trial_returns_201_with_setup_defaults(api):
    """PRD §3.1: "On creation the server records the creating operator as
    `sponsor_user_id`, sets the trial's `posture` to `SETUP`, sets its
    `irb_status` to `NONE`, and initializes `enrolled_count` and
    `active_safety_holds` to 0."
    PRD §2.4: "an integer `version` that begins at its initial value and
    increments by one on every mutation of that resource."

    Design: Corner/entities/trial_creation_returns_201_with_defaults
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_trial(
        create_trial_payload(title="Fresh", target_enrollment=10, randomization_method="SIMPLE"),
        make_sponsor_headers("sponsor-1"),
    )
    data = validate_success(res, 201)
    assert_trial(data)
    assert data["posture"] == "SETUP", f"posture must be SETUP on creation, got {data['posture']}"
    assert data["irb_status"] == "NONE", f"irb_status must be NONE on creation, got {data['irb_status']}"
    assert data["enrolled_count"] == 0, "enrolled_count initializes to 0"
    assert data["active_safety_holds"] == 0, "active_safety_holds initializes to 0"
    assert data["version"] == 1, f"version begins at 1, got {data['version']}"


def test_create_trial_missing_target_enrollment_rejected(api):
    """PRD §2.8: "structural validity of the body — required fields present
    and well-typed, enum values in range, and numbers within their declared
    bounds, such as a trial's `target_enrollment` being at least 1 or a
    visit's `draw_window_minutes` being at least 0 (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/trial_missing_required_field_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    payload = create_trial_payload(title="NoTarget", randomization_method="SIMPLE")
    del payload["target_enrollment"]
    res = api.create_trial(payload, make_sponsor_headers("sponsor-1"))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_trial_invalid_randomization_method_rejected(api):
    """PRD §3.1: "The method is one of `SIMPLE` or `PERMUTED_BLOCK`"
    PRD §2.8: "structural validity of the body — required fields present and
    well-typed, enum values in range ... (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/trial_invalid_randomization_method_enum_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_trial(
        create_trial_payload(title="BadEnum", target_enrollment=5, randomization_method="LOTTERY"),
        make_sponsor_headers("sponsor-1"),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_get_nonexistent_trial_returns_not_found(api):
    """PRD §2.7: "For any path that names more than one resource, the server
    validates the identifiers left to right and rejects the request with
    `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve."

    Design: Corner/entities/trial_get_nonexistent_returns_not_found
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.get_trial(NON_EXISTENT_TRIAL_UUID, make_sponsor_headers("sponsor-1"))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_participant_optional_fields_default(api):
    """PRD §3.3: "Two further attributes have defaults: `prior_trials_count`,
    the number of prior trials joined, defaults to 0, and `biomarker_positive`,
    whether the target biomarker is present, defaults to false."

    Design: Corner/entities/participant_defaults_applied_when_optional_omitted
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_participant(
        create_participant_payload(full_name="P Def", age_years=33, weight_kg=72, hba1c=5.5),
        TEST_USERS["coordinator_headers"],
    )
    data = validate_success(res, 201)
    assert_participant(data)
    assert data["prior_trials_count"] == 0, "prior_trials_count defaults to 0"
    assert data["biomarker_positive"] is False, "biomarker_positive defaults to false"


def test_screening_computed_fields_fully_eligible(api):
    """PRD §3.3: "The `match_result` is `ELIGIBLE` when the failure count is
    exactly 0, and `INELIGIBLE` otherwise."
    PRD §3.3: "When only the inclusion set is non-empty, the raw score is the
    inclusion pass fraction alone (the lone present category takes full
    weight)"

    Design: Corner/entities/screening_computed_fields_match_engine
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=5)
    add_criterion(trial["id"], kind="INCLUSION", attribute="age_years", comparator="GE", threshold=18)
    participant = create_participant(full_name="P One", age_years=30, weight_kg=70, hba1c=6.0)

    res = api.screen_participant(
        trial["id"], screen_participant_payload(participant["id"]),
        TEST_USERS["coordinator_headers"],
    )
    data = validate_success(res, 201)
    assert_screening(data)
    assert data["match_result"] == "ELIGIBLE"
    assert data["failed_criteria_count"] == 0
    assert data["match_score"] == 1.0, f"lone passed inclusion folds to full weight 1.0, got {data['match_score']}"


def test_list_criteria_for_trial(api):
    """PRD §4 (endpoint table): "GET `/trials/{id}/criteria` — List the
    trial's eligibility criteria".
    PRD §3.1: "Each **eligibility criterion** belongs to its trial through
    `trial_id`"

    Design: Corner/entities/criterion_listing_reverse_reach_for_trial
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=5)
    add_criterion(trial["id"], kind="INCLUSION", attribute="age_years", comparator="GE", threshold=18)
    add_criterion(trial["id"], kind="EXCLUSION", attribute="prior_trials_count", comparator="GE", threshold=3)

    res = api.list_criteria(trial["id"], TEST_USERS["coordinator_headers"])
    data = validate_success(res, 200)
    assert isinstance(data, list), "criteria listing returns an array"
    assert len(data) == 2, f"expected the trial's 2 criteria, got {len(data)}"
    for c in data:
        assert c["trial_id"] == trial["id"], "each listed criterion belongs to the trial"

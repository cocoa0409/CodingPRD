"""Registrant intake, offense tiering, and activation preconditions."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_jurisdiction_payload, create_registrant_payload, create_offense_payload,
    create_jurisdiction, create_registrant, add_offense, activate,
    setup_active_registrant, TEST_USERS,
)

ADMIN = TEST_USERS["registry_admin_headers"]
OFFICER = TEST_USERS["registration_officer_headers"]
NON_EXISTENT = "00000000-0000-0000-0000-000000000000"


def test_create_jurisdiction_applies_defaults(api):
    """PRD 3.1: "Two optional knobs may be supplied at creation:
    `verification_grace_days`, the number of days past a registrant's due date
    before the registrant is deemed overdue, which defaults to 3; and
    `est_households_per_notification`, the baseline household count that feeds the
    forward-looking community-notification estimate, which defaults to 100."
    PRD 3.1: "A newly created jurisdiction reports `active_registrant_count` and
    `active_travel_hold_count` of 0."

    Design: Corner/entities/create_jurisdiction_success_and_defaults
    """
    resp = api.create_jurisdiction(
        create_jurisdiction_payload(name="Metro", state_code="CA"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["verification_grace_days"] == 3, "verification_grace_days should default to 3"
    assert data["active_travel_hold_count"] == 0
    assert data["active_registrant_count"] == 0


def test_get_missing_registrant_returns_not_found(api):
    """PRD 2.6: "a registrant that does not exist yields `ERR_REGISTRANT_NOT_FOUND`".

    Design: Corner/entities/registrant_not_found_returns_404
    """
    resp = api.get_registrant(NON_EXISTENT, OFFICER)
    validate_error(resp, ApiErrorId.ERR_REGISTRANT_NOT_FOUND)


def test_create_registrant_missing_date_of_birth_rejected(api):
    """PRD 2.7: "a missing required field or a malformed value is rejected with
    `ERR_VALIDATION`".
    PRD 3.2: "A `RegistrationOfficer` registers a new subject by supplying the
    `jurisdiction_id` of registration, the subject's `full_name`, and `date_of_birth`."

    Design: Corner/entities/create_registrant_missing_required_field_returns_validation
    """
    jur = create_jurisdiction()
    payload = {"jurisdiction_id": jur["id"], "full_name": "No DOB"}
    resp = api.create_registrant(payload, OFFICER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_offense_with_invalid_class_rejected(api):
    """PRD 2.7: "an enum field carrying a value outside its declared set is
    rejected with `ERR_INVALID_ENUM`".
    PRD 3.2: "Each `Offense` carries a `statute_code`, an `offense_class` of
    `CLASS_A`, `CLASS_B`, or `CLASS_C`".

    Design: Corner/entities/offense_invalid_enum_class_returns_error
    """
    jur = create_jurisdiction()
    reg = create_registrant(jur["id"], full_name="Enum E")
    resp = api.create_offense(
        reg["id"],
        create_offense_payload(offense_class="CLASS_Z"),
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_new_registrant_is_pending_with_no_tier(api):
    """PRD 3.2: "A freshly registered subject begins in `PENDING` status with no
    tier, score, or verification schedule yet assigned."

    Design: Corner/entities/registrant_system_fields_generated_on_create
    """
    jur = create_jurisdiction()
    resp = api.create_registrant(create_registrant_payload(jur["id"], full_name="New N"), OFFICER)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING"
    assert data.get("tier") is None, "tier must be unset before activation"


def test_single_class_a_offense_reaches_tier_two_boundary(api):
    """PRD 3.2: "From the resulting `tier_score` the registrant's `tier` is
    derived: `TIER_3` when the score is at least 60, otherwise `TIER_2` when the
    score is at least 30, otherwise `TIER_1`. The tier fixes the periodic
    `verification_interval_days`: 365 days for `TIER_1`, 180 for `TIER_2`, and 90
    for `TIER_3`."

    Design: Corner/calculations/tier_two_at_score_boundary_thirty
    """
    jur = create_jurisdiction()
    reg = create_registrant(jur["id"], full_name="Two T")
    add_offense(reg["id"], offense_class="CLASS_A")
    resp = api.activate_registrant(reg["id"], OFFICER)
    data = validate_success(resp, expected_status=200)
    assert data["tier_score"] == 30
    assert data["tier"] == "TIER_2"
    assert data["verification_interval_days"] == 180


def test_activate_class_a_aggravated_minor_reaches_tier_three(api):
    """PRD 3.2: "Multiply the resulting sum by 1.5 when the victim was a minor, or
    by 1 otherwise, and round the product half up to a whole number; that rounded
    value is the offense's `offense_points`."
    PRD 3.2: "The registrant's `tier_score` is then the integer sum of every
    offense's `offense_points`, plus a prior-conviction bonus of 5 points for each
    offense beyond the first".

    Design: Difficulty/combinatorial_formula/tier_score_multiplier_and_tier_selection
    """
    jur = create_jurisdiction()
    reg = create_registrant(jur["id"], full_name="Max Points")
    off = add_offense(reg["id"], statute_code="P288", offense_class="CLASS_A",
                      is_aggravated=True, victim_minor=True)
    assert off["offense_points"] == 60, "round((30+10)*1.5) == 60"
    activated = activate(reg["id"])
    assert activated["tier_score"] == 60


def test_tier_three_selected_and_interval_ninety(api):
    """PRD 3.2: "From the resulting `tier_score` the registrant's `tier` is
    derived: `TIER_3` when the score is at least 60, otherwise `TIER_2` when the
    score is at least 30, otherwise `TIER_1`. The tier fixes the periodic
    `verification_interval_days`: 365 days for `TIER_1`, 180 for `TIER_2`, and 90
    for `TIER_3`."

    Design: Difficulty/combinatorial_formula/tier_score_multiplier_and_tier_selection
    """
    jur = create_jurisdiction()
    reg = create_registrant(jur["id"], full_name="Max Points")
    add_offense(reg["id"], statute_code="P288", offense_class="CLASS_A",
                is_aggravated=True, victim_minor=True)
    activated = activate(reg["id"])
    assert activated["tier"] == "TIER_3"
    assert activated["verification_interval_days"] == 90


def test_activate_already_active_registrant_rejected(api):
    """PRD 3.2: "Activation is performed by a `RegistrationOfficer` and is
    permitted only while the registrant is `PENDING`; activating a registrant in
    any other state is rejected with `ERR_REGISTRANT_NOT_PENDING`."

    Design: Corner/state_machines/activate_non_pending_returns_error
    """
    jur, reg = setup_active_registrant()
    resp = api.activate_registrant(reg["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_REGISTRANT_NOT_PENDING)


def test_activate_registrant_without_offense_rejected(api):
    """PRD 3.2: "Activation requires at least one offense on record; with none, it
    is rejected with `ERR_NO_OFFENSES`."

    Design: Corner/state_machines/activate_without_offense_returns_error
    """
    jur = create_jurisdiction()
    reg = create_registrant(jur["id"], full_name="Empty E")
    resp = api.activate_registrant(reg["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_NO_OFFENSES)

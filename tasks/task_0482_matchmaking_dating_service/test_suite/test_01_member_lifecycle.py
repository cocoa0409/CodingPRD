"""Member registration, screening lifecycle, and field validation.

Each test reconstructs its own preconditions from an empty database.
"""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_member_headers,
    ApiErrorId,
    assert_member,
    assert_membership_plan,
    fixtures as fx,
)
import test_helpers.factories as f

ADMIN = TEST_USERS["billing_admin_headers"]
SCREENING = TEST_USERS["screening_officer_headers"]
MATCHMAKER = TEST_USERS["matchmaker_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_member_minimal_returns_201_prospect(api):
    """PRD §3.2: "The new member starts in status `PROSPECT`, with `screening_decision`
    of `NONE` and `version` 1."

    Design: Corner/entities/create_member_minimal_returns_201_prospect
    """
    resp = api.create_member(
        f.create_member_payload(email="m1@x.com", gender="MALE"), SCREENING
    )
    data = validate_success(resp, 201)
    assert_member(data)
    assert data["status"] == "PROSPECT", f"expected PROSPECT, got {data['status']}"
    assert data["screening_decision"] == "NONE", f"expected NONE, got {data['screening_decision']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def test_create_member_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "request-body well-formedness — required fields present, enum values
    legal, and numeric ranges respected ... failing with ERR_INVALID_REQUEST".
    PRD §3.2: registration requires "email, full_name, birth_date ... city ... and
    gender of MALE, FEMALE, or NONBINARY."

    Design: Corner/entities/create_member_missing_required_field_returns_invalid_request
    """
    payload = {
        "email": "m2@x.com",
        "full_name": "M2",
        "birth_date": "1990-01-01T00:00:00Z",
        "city": "NYC",
    }  # gender omitted
    resp = api.create_member(payload, SCREENING)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_get_member_not_found_returns_404(api):
    """PRD §2.7: "rejects the request at the **first** identifier that does not resolve to an existing resource, returning that identifier's specific 404 error".
    PRD §5 lists ERR_MEMBER_NOT_FOUND as 404.

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT, MATCHMAKER)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, 404)


def test_create_plan_returns_active_and_defaults_applied(api):
    """PRD §3.1: "A plan may also set `priority_match_enabled`; when omitted this flag
    defaults to `false`." and "On creation a plan's `status` is `ACTIVE` and its
    `archived` flag is `false`."

    Design: Corner/entities/create_plan_returns_active_and_defaults_applied
    """
    payload = {
        "tier": "BASIC",
        "monthly_fee_cents": 9000,
        "term_months": 3,
        "guaranteed_introductions": 4,
        "included_coaching_sessions": 2,
        "coaching_value_cents": 4000,
        "background_check_addon_cents": 2000,
    }  # priority_match_enabled omitted
    resp = api.create_plan(payload, ADMIN)
    data = validate_success(resp, 201)
    assert_membership_plan(data)
    assert data["priority_match_enabled"] is False, "omitted priority flag must default to false"
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["archived"] is False, "new plan must have archived=false"


def test_system_fields_not_client_settable_on_member_create(api):
    """PRD §3.2: "The new member starts in status `PROSPECT`, with `screening_decision`
    of `NONE` and `version` 1."

    Design: Corner/entities/system_fields_ignored_on_member_create
    """
    resp = api.create_member(
        f.create_member_payload(email="m3@x.com", gender="FEMALE"), SCREENING
    )
    data = validate_success(resp, 201)
    assert data["status"] == "PROSPECT", "status is system-set to PROSPECT"
    assert data["version"] == 1, "version is system-set to 1"


def test_invalid_enum_gender_returns_invalid_request(api):
    """PRD §3.2: registration supplies "`email`, `full_name`, `birth_date` (the date of
    birth in ISO 8601 UTC, later used for age-gap eligibility against the clock), `city`
    (the home-city label used by location proximity scoring), and `gender` of `MALE`,
    `FEMALE`, or `NONBINARY`."
    PRD §2.8: bad enum values fail "request-body well-formedness — required fields
    present, enum values legal, and numeric ranges respected".

    Design: Corner/entities/invalid_enum_gender_returns_invalid_request
    """
    payload = f.create_member_payload(email="m4@x.com", gender="ROBOT")
    resp = api.create_member(payload, SCREENING)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_preference_max_age_below_min_age_returns_invalid_request(api):
    """PRD §2.8: numeric ranges include "a maximum age not less than the minimum age
    ... failing with ERR_INVALID_REQUEST".
    PRD §3.3: preferences supply "a `min_age` of at least 18, a `max_age` that must be
    at least the `min_age`".

    Design: Corner/entities/preference_max_age_below_min_age_returns_invalid_request
    """
    member = fx.register_prospect("m5@x.com", gender="MALE")
    payload = f.create_preference_payload(min_age=40, max_age=30)
    resp = api.put_preferences(member["id"], payload, make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_decide_screening_twice_returns_already_decided(api):
    """PRD §3.2: "Deciding is allowed only while the screening's `decision` is still
    `PENDING`; a second decision attempt is rejected with `ERR_SCREENING_ALREADY_DECIDED`."

    Design: Corner/state_machines/decide_screening_twice_returns_already_decided
    """
    member = fx.register_prospect("ca2@x.com", gender="MALE")
    scr = validate_success(
        api.create_screening(member["id"], f.create_screening_payload(), SCREENING), 201
    )
    validate_success(
        api.decide_screening(
            member["id"], scr["id"], f.decide_screening_payload(decision="APPROVED"), SCREENING
        ),
        200,
    )
    resp = api.decide_screening(
        member["id"], scr["id"], f.decide_screening_payload(decision="REJECTED"), SCREENING
    )
    validate_error(resp, ApiErrorId.ERR_SCREENING_ALREADY_DECIDED.value, 409)


def test_exit_already_exited_member_returns_not_exitable(api):
    """PRD §3.9: "Exit requires the member to be `ACTIVE` or `FROZEN` (else `ERR_MEMBER_NOT_EXITABLE`)."
    PRD §3.2: on REJECTED "the member's status moves directly to `EXITED".

    Design: Corner/state_machines/exit_already_exited_member_returns_not_exitable
    """
    member = fx.register_prospect("ca3@x.com", gender="MALE")
    scr = validate_success(
        api.create_screening(
            member["id"], f.create_screening_payload(questionnaire_score=20, identity_verified=False),
            SCREENING,
        ),
        201,
    )
    validate_success(
        api.decide_screening(
            member["id"], scr["id"], f.decide_screening_payload(decision="REJECTED"), SCREENING
        ),
        200,
    )
    resp = api.exit_member(member["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_EXITABLE.value, 409)

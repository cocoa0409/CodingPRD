"""Physician releases, condition policies and the admissibility ladder."""

from test_helpers import (
    ApiErrorId,
    assert_catalogue_row,
    assert_same_instant,
    book_session,
    file_assessment,
    file_release,
    make_instructor,
    make_instructor_headers,
    make_rider,
    read_rider,
    read_release,
    rider_version,
    session_payload,
    set_clock,
    setup_active_rider,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, INTAKE

CLEAR_ASD_POLICY = {
    "condition_code": "CP_MILD_ASD",
    "activity_type": "THERAPEUTIC_RIDING",
    "tier": "CLEAR",
    "min_instructor_tier": "REGISTERED",
}
SPASTIC_RIDING_PRECAUTION = {
    "condition_code": "CP_SPASTIC",
    "activity_type": "THERAPEUTIC_RIDING",
    "tier": "PRECAUTION",
    "min_instructor_tier": "ADVANCED",
}


def test_filing_a_second_release_supersedes_the_first(api):
    """PRD 3.2: "Filing a release for a rider who already has an `ACTIVE` one
    stamps the older release's `superseded_at` with the logical clock, re-points
    the rider's `active_release_id` at the new release, and increments the
    rider's `version`."
    PRD 3.2: "The server computes `expires_at` as 365 days after `signed_on`
    promoted to midnight UTC."

    Design: Corner/state_machines/filing_second_release_supersedes_the_prior_active_one
    """
    set_clock("2026-05-01T00:00:00Z")
    rider = make_rider(
        household_income_band="BAND_B", condition_codes=["CP_SPASTIC"]
    )
    first = file_release(rider["id"], expected_rider_version=rider["version"])

    second = validate_success(
        api.create_medical_release(
            rider["id"],
            {
                "signed_on": "2026-04-20",
                "physician_name": "Dr Elm",
                "cleared_condition_codes": ["CP_SPASTIC"],
                "expected_rider_version": rider_version(rider["id"]),
            },
            INTAKE,
        ),
        expected_status=201,
    )

    superseded = read_release(first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert_same_instant(superseded["superseded_at"], "2026-05-01T00:00:00.000Z")
    assert read_release(second["id"])["status"] == "ACTIVE"
    assert_same_instant(second["expires_at"], "2027-04-20T00:00:00.000Z")
    assert read_rider(rider["id"])["active_release_id"] == second["id"]

    _, meta = validate_paginated(
        api.list_medical_releases(INTAKE, params={"rider_id": rider["id"]})
    )
    assert meta["total_count"] == 2


def test_revoking_the_active_release_clears_the_pointer_and_blocks_activation(api):
    """PRD 3.2: "A `ProgramAdmin` may instead revoke a release outright with a
    supplied `reason`, which stamps `revoked_at` with the logical clock,
    re-derives `active_release_id`, and increments the release's own `version`"
    PRD 2.11: "A medical release's `status` is `REVOKED` if `revoked_at` is set;
    otherwise `SUPERSEDED` if `superseded_at` is set; otherwise `EXPIRED` if the
    logical clock has reached `expires_at`; otherwise `ACTIVE`."
    PRD 3.1: "A rider with no release at all is refused with
    `ERR_RELEASE_MISSING` and one whose newest release has lapsed with
    `ERR_RELEASE_EXPIRED`."

    Design: Corner/state_machines/revoking_the_active_release_clears_the_riders_active_release_pointer
    """
    set_clock("2026-05-01T00:00:00Z")
    instructor = make_instructor()
    rider = make_rider(household_income_band="BAND_B", condition_codes=[])
    release = file_release(rider["id"], expected_rider_version=rider["version"])
    file_assessment(rider["id"], instructor["id"])

    revoked = validate_success(
        api.revoke_medical_release(
            release["id"], {"reason": "Physician withdrew consent"}, ADMIN
        )
    )
    assert revoked["status"] == "REVOKED"
    assert_same_instant(
        read_release(release["id"])["revoked_at"], "2026-05-01T00:00:00.000Z"
    )
    assert read_rider(rider["id"])["active_release_id"] is None

    blocked = api.activate_rider(rider["id"], INTAKE)
    validate_error(blocked, ApiErrorId.ERR_RELEASE_EXPIRED.value)
    assert read_rider(rider["id"])["status"] == "INTAKE"


def test_medical_release_filing_with_a_stale_rider_version_is_rejected(api):
    """PRD 2.4: "In all three cases, if the supplied value does not equal the
    parent entity's current stored `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412) and nothing is persisted."
    PRD 2.4: "Filing a release supersedes the rider's prior active release and
    re-points which release the rider is riding under, so a stale
    `expected_rider_version` means the client's view of which condition codes are
    currently cleared is out of date."

    Design: Corner/cross_cutting_complexity_layers/medical_release_filing_with_a_stale_rider_version_returns_412
    """
    set_clock("2026-05-01T00:00:00Z")
    rider = make_rider(condition_codes=[])
    stale_version = rider["version"]
    first = file_release(rider["id"], expected_rider_version=stale_version)

    rejected = api.create_medical_release(
        rider["id"],
        {
            "signed_on": "2026-04-20",
            "physician_name": "Dr Elm",
            "cleared_condition_codes": [],
            "expected_rider_version": stale_version,
        },
        INTAKE,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_VERSION.value)

    unchanged = read_release(first["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["superseded_at"] is None

    _, meta = validate_paginated(
        api.list_medical_releases(INTAKE, params={"rider_id": rider["id"]})
    )
    assert meta["total_count"] == 1
    assert read_rider(rider["id"])["active_release_id"] == first["id"]


def test_condition_policy_is_a_catalogue_row_without_version(api):
    """PRD 2.4: "`ConditionPolicy` rows are catalogue entries that are written
    once and never mutated: they expose only `id` and `created_at`, and carry
    neither `updated_at` nor `version`."
    PRD 3.2: "A `ProgramAdmin` declares one such pair at a time as a
    **condition policy**, supplying the `condition_code`, the `activity_type` it
    governs, the `tier`, and optionally a `min_instructor_tier` that defaults to
    `REGISTERED`."

    Design: Corner/entities/condition_policy_is_immutable_configuration_without_version
    """
    set_clock("2026-05-01T00:00:00Z")

    policy = validate_success(
        api.create_condition_policy(
            {
                "condition_code": "CP_SPASTIC",
                "activity_type": "VAULTING",
                "tier": "CONTRAINDICATION",
                "min_instructor_tier": "MASTER",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert_catalogue_row(policy, "ConditionPolicy")

    rows, meta = validate_paginated(
        api.list_condition_policies(ADMIN, params={"condition_code": "CP_SPASTIC"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["tier"] == "CONTRAINDICATION"

    defaulted = validate_success(
        api.create_condition_policy(
            {
                "condition_code": "CP_ATLANTOAXIAL",
                "activity_type": "VAULTING",
                "tier": "CLEAR",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert defaulted["min_instructor_tier"] == "REGISTERED"


def test_same_code_is_a_precaution_for_riding_and_a_contraindication_for_vaulting(api):
    """PRD 3.2: "A code whose policy `tier` is `CONTRAINDICATION` stops it
    immediately at `CONTRAINDICATION`, which is the worst possible outcome and is
    reported as `ERR_CONDITION_CONTRAINDICATED`; a physician clearance never
    lifts a contraindication, which is why the cleared set is consulted only for
    precaution-tier codes."
    PRD 3.2: "Because the pair is what is governed, the same rider can be
    perfectly admissible for `THERAPEUTIC_RIDING` and barred from `VAULTING` on
    the same day."
    PRD 3.2: "Every condition-policy row for this rider and this activity whose
    `tier` is `PRECAUTION` contributes its `min_instructor_tier`, **including
    rows whose code the release has cleared** — clearing removes the
    participation bar, not the instructor-tier requirement."

    Design: Corner/calculations/one_condition_code_is_a_precaution_for_riding_and_a_contraindication_for_vaulting
    """
    scenario = setup_active_rider(
        policies=[
            SPASTIC_RIDING_PRECAUTION,
            {
                "condition_code": "CP_SPASTIC",
                "activity_type": "VAULTING",
                "tier": "CONTRAINDICATION",
                "min_instructor_tier": "MASTER",
            },
        ],
        rider={"condition_codes": ["CP_SPASTIC"]},
        release={"cleared_condition_codes": ["CP_SPASTIC"]},
    )

    riding = validate_success(
        api.create_session(
            session_payload(
                scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
            ),
            scenario["instructor_headers"],
        ),
        expected_status=201,
    )
    assert riding["precaution_tier"] == "CLEAR"
    assert riding["required_instructor_tier"] == "ADVANCED"
    assert riding["quoted_fee_cents"] == 9000

    vaulting = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            activity_type="VAULTING",
            scheduled_start="2026-05-12T10:00:00Z",
        ),
        scenario["instructor_headers"],
    )
    validate_error(vaulting, ApiErrorId.ERR_CONDITION_CONTRAINDICATED.value)

    rows, _ = validate_paginated(
        api.list_sessions(ADMIN, params={"rider_id": scenario["rider_id"]})
    )
    assert all(row["activity_type"] != "VAULTING" for row in rows)


def test_unmapped_condition_code_blocks_booking(api):
    """PRD 2.7 rung 22: "Every code in the rider's `condition_codes` has a
    condition-policy row for the session's `activity_type` — otherwise
    `ERR_CONDITION_POLICY_MISSING` (422). Applies to session creation and session
    confirmation."
    PRD 3.2: "A code with no condition-policy row for this activity stops the
    evaluation with `ERR_CONDITION_POLICY_MISSING`."

    Design: Corner/validations/booking_with_an_unmapped_condition_code_returns_condition_policy_missing
    """
    scenario = setup_active_rider(
        rider={"condition_codes": ["CP_MILD_ASD", "CP_ORPHAN"]}
    )

    response = api.create_session(
        session_payload(
            scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
        ),
        scenario["instructor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CONDITION_POLICY_MISSING.value)

    _, meta = validate_paginated(
        api.list_sessions(ADMIN, params={"rider_id": scenario["rider_id"]})
    )
    assert meta["total_count"] == 0


def test_uncleared_precaution_blocks_booking_until_the_release_lists_it(api):
    """PRD 3.2: "A code whose policy `tier` is `PRECAUTION` and which is *not* in
    the cleared set raises the running worst tier to `PRECAUTION`, reported as
    `ERR_PRECAUTION_NOT_CLEARED`."
    PRD 2.7 rung 24: "Every precaution-tier code of the rider for this activity
    appears in the active release's `cleared_condition_codes` — otherwise
    `ERR_PRECAUTION_NOT_CLEARED` (422)."

    Design: Corner/validations/uncleared_precaution_blocks_booking_until_the_release_lists_the_code
    """
    scenario = setup_active_rider(
        policies=[SPASTIC_RIDING_PRECAUTION],
        rider={"condition_codes": ["CP_SPASTIC"]},
        release={"cleared_condition_codes": []},
    )

    blocked = api.create_session(
        session_payload(
            scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
        ),
        scenario["instructor_headers"],
    )
    validate_error(blocked, ApiErrorId.ERR_PRECAUTION_NOT_CLEARED.value)

    validate_success(
        api.create_medical_release(
            scenario["rider_id"],
            {
                "signed_on": "2026-04-20",
                "physician_name": "Dr Elm",
                "cleared_condition_codes": ["CP_SPASTIC"],
                "expected_rider_version": rider_version(scenario["rider_id"]),
            },
            INTAKE,
        ),
        expected_status=201,
    )

    booked = validate_success(
        api.create_session(
            session_payload(
                scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
            ),
            scenario["instructor_headers"],
        ),
        expected_status=201,
    )
    assert booked["precaution_tier"] == "CLEAR"
    assert booked["required_instructor_tier"] == "ADVANCED"


def test_registered_instructor_cannot_run_an_advanced_precaution(api):
    """PRD 2.7 rung 26: "The effective instructor's tier ordinal is at least the
    required ordinal — otherwise `ERR_INSTRUCTOR_TIER_INSUFFICIENT` (422).
    Applies to session creation and session confirmation."
    PRD 3.2: "Tiers are compared by ordinal, where `IN_TRAINING` is 0,
    `REGISTERED` is 1, `ADVANCED` is 2 and `MASTER` is 3, and the effective
    instructor's ordinal must be at least the required ordinal — equality passes."

    Design: Corner/validations/registered_instructor_cannot_run_a_precaution_requiring_advanced
    """
    scenario = setup_active_rider(
        policies=[SPASTIC_RIDING_PRECAUTION],
        instructors=[
            {
                "full_name": "Reg Registered",
                "certification_level": "REGISTERED",
                "certification_expires_at": "2028-04-30T00:00:00Z",
            },
            {
                "full_name": "Ada Advanced",
                "certification_level": "ADVANCED",
                "certification_expires_at": "2028-04-30T00:00:00Z",
            },
        ],
        rider={"condition_codes": ["CP_SPASTIC"]},
        release={"cleared_condition_codes": ["CP_SPASTIC"]},
        assessing_instructor_index=1,
    )
    registered_id, advanced_id = scenario["instructor_ids"]

    blocked = api.create_session(
        session_payload(scenario["rider_id"], scenario["horse_id"], registered_id),
        make_instructor_headers(registered_id),
    )
    validate_error(blocked, ApiErrorId.ERR_INSTRUCTOR_TIER_INSUFFICIENT.value)

    booked = validate_success(
        api.create_session(
            session_payload(scenario["rider_id"], scenario["horse_id"], advanced_id),
            make_instructor_headers(advanced_id),
        ),
        expected_status=201,
    )
    assert booked["required_instructor_tier"] == "ADVANCED"
    assert booked["precaution_tier"] == "CLEAR"


def test_patching_condition_codes_re_derives_admissibility(api):
    """PRD 3.1: "an update accepts any of `weight_lb`, `household_income_band`,
    `condition_codes`, `funding_mode` and `payer_rate_cents`, bumps the rider's
    `version`, and — because the load and admissibility calculations read the
    rider live — silently changes what every one of that rider's live sessions
    reports for `effective_load_lb` and `precaution_tier` on the next read."
    PRD 3.6: "what is fixed is that `blocking_gate` is populated exactly when
    `admissible` is false and is null when `admissible` is true."

    Design: Corner/cross_cutting_complexity_layers/patching_condition_codes_re_derives_session_admissibility_on_the_next_read
    """
    scenario = setup_active_rider(
        policies=[
            CLEAR_ASD_POLICY,
            {
                "condition_code": "CP_ATLANTOAXIAL",
                "activity_type": "THERAPEUTIC_RIDING",
                "tier": "CONTRAINDICATION",
                "min_instructor_tier": "MASTER",
            },
        ]
    )
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )

    before = validate_success(
        api.get_session_eligibility(
            session["id"],
            scenario["instructor_headers"],
            params={"variant": "current_declared"},
        )
    )
    assert before["precaution_tier"] == "CLEAR"
    assert before["admissible"] is True
    assert before["blocking_gate"] is None

    validate_success(
        api.update_rider(
            scenario["rider_id"],
            {"condition_codes": ["CP_MILD_ASD", "CP_ATLANTOAXIAL"]},
            INTAKE,
        )
    )

    after = validate_success(
        api.get_session_eligibility(
            session["id"],
            scenario["instructor_headers"],
            params={"variant": "current_declared"},
        )
    )
    assert after["precaution_tier"] == "CONTRAINDICATION"
    assert after["admissible"] is False
    assert after["blocking_gate"] is not None

    blocked = api.confirm_session(session["id"], scenario["instructor_headers"])
    validate_error(blocked, ApiErrorId.ERR_CONDITION_CONTRAINDICATED.value)
    assert validate_success(
        api.get_session(session["id"], ADMIN)
    )["schedule_status"] == "CREW_PENDING"


def test_booking_blocked_when_reassessment_overdue_but_release_fresh(api):
    """PRD 2.7 rung 21: "The rider's `assessment_status` is neither `OVERDUE` nor
    `NEVER_ASSESSED` — otherwise `ERR_REASSESSMENT_OVERDUE` (422). Applies to
    session creation and session confirmation."
    PRD 3.1: "A rider whose `assessment_next_due_at` has been reached is
    `OVERDUE`."

    Design: Corner/validations/booking_blocked_when_reassessment_is_overdue_but_release_is_fresh
    """
    scenario = setup_active_rider()

    set_clock("2027-03-01T00:00:00Z")
    file_release(
        scenario["rider_id"],
        signed_on="2027-03-01",
        physician_name="Dr Elm",
        cleared_condition_codes=[],
    )
    set_clock("2027-04-02T00:00:00Z")

    response = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start="2027-04-12T10:00:00Z",
        ),
        scenario["instructor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_REASSESSMENT_OVERDUE.value)

    rider = read_rider(scenario["rider_id"])
    assert rider["assessment_status"] == "OVERDUE"
    assert rider["status"] == "ACTIVE"
    assert rider["active_release_id"] is not None, "The release gate at rung 18 passed"


def test_booking_blocked_when_release_expired_but_reassessment_current(api):
    """PRD 2.7 rung 18: "a rider whose most recent release is `EXPIRED`,
    `REVOKED` or `SUPERSEDED` is rejected with `ERR_RELEASE_EXPIRED` (422)."
    PRD 3.2: "Note that expiry is inclusive of the boundary: a ride at exactly
    `expires_at` is riding on an expired release."

    Design: Corner/validations/booking_blocked_when_release_expired_but_reassessment_is_current
    """
    scenario = setup_active_rider()

    set_clock("2027-03-01T00:00:00Z")
    reassessment = file_assessment(
        scenario["rider_id"],
        scenario["instructor_id"],
        assessment_type="ANNUAL_REASSESSMENT",
        performed_on="2027-03-01",
    )
    # PRD 3.1 stamps `next_due_at` at exactly 365 days after `performed_on`
    # promoted to midnight UTC -- not at the same calendar date one year on.
    # 2027-03-01T00:00:00Z + 365 days lands on 2028-02-29 because 2028 is a
    # leap year and the span therefore contains 29 February.
    assert_same_instant(reassessment["next_due_at"], "2028-02-29T00:00:00.000Z")
    set_clock("2027-04-02T00:00:00Z")

    response = api.create_session(
        session_payload(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start="2027-04-12T10:00:00Z",
        ),
        scenario["instructor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_RELEASE_EXPIRED.value)

    rider = read_rider(scenario["rider_id"])
    assert rider["assessment_status"] == "CURRENT"
    assert rider["active_release_id"] is None


def test_booking_for_a_rider_still_in_intake_returns_rider_not_active(api):
    """PRD 2.7 rung 20: "The rider's `status` is `ACTIVE` — otherwise
    `ERR_RIDER_NOT_ACTIVE` (409). Applies to session creation and session
    confirmation."

    Design: Corner/validations/booking_for_a_rider_still_in_intake_returns_rider_not_active
    """
    scenario = setup_active_rider(activate=False)
    assert read_rider(scenario["rider_id"])["status"] == "INTAKE"

    response = api.create_session(
        session_payload(
            scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
        ),
        scenario["instructor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_RIDER_NOT_ACTIVE.value)

    _, meta = validate_paginated(api.list_incidents(ADMIN))
    assert meta["total_count"] == 0, "No incident exists, so gate 1 could not have fired"

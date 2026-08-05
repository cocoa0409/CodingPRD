"""Consent: who grants it, what it covers, how long it lasts and what its
revocation drags with it."""

from test_helpers import (
    ADMIN,
    REGISTRAR,
    ApiErrorId,
    assert_consent,
    assert_same_instant,
    consent_payload,
    create_student,
    get_student,
    make_student_headers,
    revoke_consent,
    run_daily_sweep,
    school_booked_minutes,
    set_clock,
    set_financial_profile,
    setup_booked_session,
    setup_visit_scheduled,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_reconsent_after_revocation_leaves_the_revoked_row_untouched(api):
    """PRD §3.4: "Revocation moves a consent `ACTIVE → REVOKED`, is permitted only
    from `ACTIVE`, records `revoked_at` as the current logical instant and stores
    the supplied `reason` as `revocation_reason`."
    PRD §3.4: "Creating a consent also supersedes: any consent already on file for
    the same student, the same `category` and the same `school_year` whose status
    is `ACTIVE` moves `ACTIVE → SUPERSEDED`."
    PRD §3.4: "Re-consenting after a revocation is not a transition out of
    `REVOKED`; it is simply a fresh consent record created by the same grant path,
    and the revoked row stays revoked forever."

    Design: Corner/state_machines/consent_revoke_then_reconsent_leaves_revoked_row_and_supersedes_active_row
    """
    set_clock("2026-05-04T09:00:00Z")
    student = create_student()
    guardian = validate_success(
        api.add_guardian(
            student["id"],
            {
                "full_name": "Mai Nguyen",
                "relationship": "MOTHER",
                "contact_email": "mai@example.org",
                "is_primary": True,
            },
            REGISTRAR,
        ),
        201,
    )

    def grant():
        version = get_student(student["id"])["version"]
        return validate_success(
            api.create_consent(
                student["id"],
                consent_payload("GENERAL_TREATMENT", guardian["id"], version),
                REGISTRAR,
            ),
            201,
        )

    first = grant()
    revoke_consent(first["id"], "Guardian withdrew consent")
    second = grant()
    third = grant()

    rows, meta = validate_paginated(api.list_consents(student["id"], REGISTRAR))
    by_id = {row["id"]: row for row in rows}

    assert by_id[first["id"]]["status"] == "REVOKED"
    assert_same_instant(
        by_id[first["id"]]["revoked_at"], "2026-05-04T09:00:00.000Z", "Consent.revoked_at"
    )
    assert by_id[second["id"]]["status"] == "SUPERSEDED"
    assert by_id[third["id"]]["status"] == "ACTIVE"
    assert_consent(by_id[third["id"]])
    assert_same_instant(
        by_id[third["id"]]["expires_at"], "2026-07-31T23:59:59.000Z", "Consent.expires_at"
    )
    assert meta["total_count"] == 3, f"Expected three consent rows, got {meta['total_count']}"
    assert sum(1 for row in rows if row["status"] == "ACTIVE") == 1


def test_consent_expires_on_the_daily_sweep_and_blocks_starting_the_encounter(api):
    """PRD §3.4: "The daily epoch advance moves any `ACTIVE` consent whose
    `expires_at` is strictly before the current logical instant to `EXPIRED`; at
    exactly `expires_at` the consent survives the sweep."
    PRD §3.12: "It expires every `ACTIVE` consent whose `expires_at` is strictly
    before the current logical instant"
    PRD §3.5: "a consent revoked or expired between scheduling and the child
    walking in stops the encounter with `ERR_CONSENT_REQUIRED`, which is the whole
    point of re-checking."

    Design: Corner/state_machines/consent_expires_on_daily_sweep_and_blocks_visit_start
    """
    ctx = setup_visit_scheduled(scheduled_start_at="2026-05-04T10:00:00Z")
    consent = ctx["consents"]["GENERAL_TREATMENT"]

    set_clock("2026-08-01T00:00:00Z")
    sweep = run_daily_sweep()
    assert sweep["consents_expired"] == 1, (
        f"Expected the sweep to expire exactly one consent, got {sweep['consents_expired']}"
    )

    rows, _ = validate_paginated(api.list_consents(ctx["student"]["id"], REGISTRAR))
    assert {row["id"]: row["status"] for row in rows}[consent["id"]] == "EXPIRED"

    resp = api.start_visit(ctx["visit"]["id"], ctx["clinician_headers"])
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED.value, 409)

    assert validate_success(api.get_visit(ctx["visit"]["id"], REGISTRAR))[
        "clinical_status"
    ] == "SCHEDULED"


def test_self_consent_is_permitted_at_exactly_fourteen_for_a_confidential_category(api):
    """PRD §3.4: "When `granted_by` is `STUDENT_SELF`, `granted_by_user_id` is the
    student's own identifier, and the minor-consent-by-law rules apply: the
    category must be `BEHAVIORAL_HEALTH` or `CONFIDENTIAL_SERVICES`, and the
    student's age in whole completed years at the current logical clock date must
    be at least 14."
    PRD §3.4: "A student who turns 14 exactly today qualifies; a student one day
    short does not."

    Design: Corner/validations/self_consent_permitted_at_exactly_fourteen_and_only_for_confidential_categories
    """
    set_clock("2026-05-04T09:00:00Z")
    student = create_student(
        first_name="Amir", last_name="Fourteen", date_of_birth="2012-05-04"
    )

    resp = api.create_consent(
        student["id"],
        consent_payload(
            "BEHAVIORAL_HEALTH", student["id"], student["version"], granted_by="STUDENT_SELF"
        ),
        make_student_headers(student["id"]),
    )
    consent = validate_success(resp, 201)

    assert_consent(consent)
    assert consent["status"] == "ACTIVE"
    assert consent["granted_by"] == "STUDENT_SELF"
    assert consent["granted_by_user_id"] == student["id"]


def test_self_consent_refused_outside_the_category_list_and_below_the_age_floor(api):
    """PRD §3.4: "the category must be `BEHAVIORAL_HEALTH` or
    `CONFIDENTIAL_SERVICES`, and the student's age in whole completed years at the
    current logical clock date must be at least 14. A student who turns 14 exactly
    today qualifies; a student one day short does not. Either failure is refused
    with `ERR_SELF_CONSENT_NOT_PERMITTED`."

    Design: Corner/validations/self_consent_permitted_at_exactly_fourteen_and_only_for_confidential_categories
    """
    set_clock("2026-05-04T09:00:00Z")
    exactly_fourteen = create_student(
        first_name="Amir", last_name="Fourteen", date_of_birth="2012-05-04"
    )
    one_day_short = create_student(
        first_name="Bree", last_name="Thirteen", date_of_birth="2012-05-05"
    )

    wrong_category = api.create_consent(
        exactly_fourteen["id"],
        consent_payload(
            "GENERAL_TREATMENT",
            exactly_fourteen["id"],
            exactly_fourteen["version"],
            granted_by="STUDENT_SELF",
        ),
        make_student_headers(exactly_fourteen["id"]),
    )
    validate_error(wrong_category, ApiErrorId.ERR_SELF_CONSENT_NOT_PERMITTED.value, 403)

    too_young = api.create_consent(
        one_day_short["id"],
        consent_payload(
            "BEHAVIORAL_HEALTH",
            one_day_short["id"],
            one_day_short["version"],
            granted_by="STUDENT_SELF",
        ),
        make_student_headers(one_day_short["id"]),
    )
    validate_error(too_young, ApiErrorId.ERR_SELF_CONSENT_NOT_PERMITTED.value, 403)

    rows, meta = validate_paginated(api.list_consents(one_day_short["id"], REGISTRAR))
    assert meta["total_count"] == 0, "A refused self-consent must create no Consent row"
    assert rows == []


def test_student_cannot_self_consent_on_another_students_record(api):
    """PRD §2.1: "Concretely, that covers four situations — a `Student` recording a
    self-consent whose path student id is not their own; a `Guardian`
    acknowledging a notification whose target guardian is not them; a `Guardian`
    changing the notification preference of a guardian row that is not their own;
    and a `Guardian` or `Student` revoking a consent they did not themselves
    grant."
    PRD §3.4: "Separately, a principal acting in the `Student` role may only
    self-consent on their own record — a mismatch between `X-User-ID` and the
    student identifier in the path is an `ERR_OWNERSHIP_VIOLATION`."

    Design: Corner/rbac/student_cannot_self_consent_on_another_students_row
    """
    set_clock("2026-05-04T09:00:00Z")
    student_a = create_student(first_name="Ava", last_name="Nguyen", date_of_birth="2010-04-15")
    student_b = create_student(first_name="Ben", last_name="Ortiz", date_of_birth="2010-04-16")

    resp = api.create_consent(
        student_b["id"],
        consent_payload(
            "BEHAVIORAL_HEALTH", student_a["id"], student_b["version"], granted_by="STUDENT_SELF"
        ),
        make_student_headers(student_a["id"]),
    )

    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value, 403)

    rows, meta = validate_paginated(api.list_consents(student_b["id"], REGISTRAR))
    assert meta["total_count"] == 0, "An ownership violation must create no Consent row"
    assert rows == []


def test_consent_create_with_a_stale_student_version_is_rejected(api):
    """PRD §2.7: "**Granting a consent** (`POST /sbhc/students/{id}/consents`)
    requires `expected_student_version` to match the student's current `version`.
    This matters because a new consent in the same category and school year
    legitimately supersedes the prior one; a writer holding a stale view of the
    student would silently displace a consent it never saw. Mismatch yields
    `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/consent_create_with_stale_student_version_returns_stale_version
    """
    set_clock("2026-05-04T09:00:00Z")
    student = create_student()
    stale_version = student["version"]
    guardian = validate_success(
        api.add_guardian(
            student["id"],
            {
                "full_name": "Mai Nguyen",
                "relationship": "MOTHER",
                "contact_email": "mai@example.org",
                "is_primary": True,
            },
            REGISTRAR,
        ),
        201,
    )
    fresh = set_financial_profile(
        student["id"],
        household_income_annual_cents=3_000_000,
        household_size=4,
        payer_route="SELF_PAY",
    )

    stale_resp = api.create_consent(
        student["id"],
        consent_payload("GENERAL_TREATMENT", guardian["id"], stale_version),
        REGISTRAR,
    )
    validate_error(stale_resp, ApiErrorId.ERR_STALE_VERSION.value, 412)

    accepted = validate_success(
        api.create_consent(
            student["id"],
            consent_payload("GENERAL_TREATMENT", guardian["id"], fresh["version"]),
            REGISTRAR,
        ),
        201,
    )

    assert accepted["status"] == "ACTIVE"
    assert get_student(student["id"])["version"] == 3
    _rows, meta = validate_paginated(api.list_consents(student["id"], REGISTRAR))
    assert meta["total_count"] == 1, "The rejected create must not have stored a row"


def test_revoking_telehealth_consent_cancels_the_session_visit_and_booking(api):
    """PRD §3.4: "Revoking a `TELEHEALTH` consent triggers a four-link cascade, and
    each link must fire: the consent itself becomes `REVOKED`; every telehealth
    session whose encounter belongs to that student and whose own status is
    `SCHEDULED` moves to `CANCELLED`; each such cancellation decrements the
    hosting site's `telehealth_booked_minutes_total` by that session's
    `duration_minutes`; and the encounter behind each cancelled session moves its
    clinical state to `CANCELLED` when it is still `SCHEDULED` or `IN_PROGRESS`."
    PRD §3.4: "Revoking a consent in any other category cascades to nothing."

    Design: Corner/cross_cutting_complexity_layers/telehealth_consent_revoke_cascades_to_sessions_visits_and_booked_minutes
    """
    ctx = setup_booked_session()
    assert school_booked_minutes(ctx["school"]["id"]) == 30

    revoked = validate_success(
        api.revoke_consent(
            ctx["consents"]["TELEHEALTH"]["id"],
            {"reason": "Guardian withdrew telehealth permission"},
            REGISTRAR,
        )
    )

    assert revoked["status"] == "REVOKED"
    assert validate_success(api.get_telehealth_session(ctx["session"]["id"], ADMIN))[
        "status"
    ] == "CANCELLED"
    assert school_booked_minutes(ctx["school"]["id"]) == 0
    assert validate_success(api.get_visit(ctx["visit"]["id"], REGISTRAR))[
        "clinical_status"
    ] == "CANCELLED"

    rows, _ = validate_paginated(api.list_consents(ctx["student"]["id"], REGISTRAR))
    general = {row["id"]: row for row in rows}[ctx["consents"]["GENERAL_TREATMENT"]["id"]]
    assert general["status"] == "ACTIVE", "Only the telehealth consent is revoked"

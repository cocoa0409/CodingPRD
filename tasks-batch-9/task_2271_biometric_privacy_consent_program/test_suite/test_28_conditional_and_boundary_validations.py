"""Rules that fire only under a flag, and rules that are inclusive at their edge.

The same locale array is fatal in one state and harmless in another; the same
retention promise is fatal at 1200 days and permitted at exactly 1095.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    ApiErrorId,
    assert_instant_equals,
    assert_is_null,
    create_jurisdiction,
    create_notice_packet,
    create_policy,
    create_program,
    create_published_policy,
    read_notice,
    read_policy,
    submit_policy,
    validate_error,
    validate_success,
)

WASHINGTON_WITHOUT_A_TRANSLATION_MANDATE = {
    "state_code": "WA",
    "statute_name": "My Health My Data",
    "private_right_of_action": "FULL",
    "damages_model": "STATUTORY_PER_VIOLATION",
    "requires_written_release": False,
    "translation_required": False,
    "required_locales": ["en", "es"],
    "retention_max_days": 730,
    "notice_lead_days": 7,
    "per_violation_negligent_cents": 50000,
    "per_violation_reckless_cents": 200000,
    "cure_period_days": 0,
}

ILLINOIS_RETENTION_MAX_DAYS = 1095


def test_locale_coverage_is_demanded_only_where_the_statute_mandates_translation(api):
    """Two packets carry the identical `["en"]`; only the mandated state refuses.

    PRD §3.4: "When the governing state profile has `translation_required` true, the
    packet's `locales` must be a superset of that profile's `required_locales`; a
    missing locale yields `ERR_TRANSLATION_LOCALE_MISSING`."

    PRD §3.4: "Successful publication stamps `published_at` from the current logical
    clock and computes `consent_eligible_from` as `published_at` plus the governing
    state profile's `notice_lead_days`."

    Both states list `es` among their required locales and both packets omit it, so the
    only thing separating them is the flag. Washington publishes and takes its own
    seven-day lead, while the Illinois packet stays a draft; a fresh Illinois packet
    that adds `es` then publishes, isolating the locale array as the sole cause.

    Design: Corner/validations/translation_locale_coverage_is_enforced_only_where_the_state_requires_it
    """
    program = create_program(api)
    illinois = create_jurisdiction(api, program["id"])
    washington = create_jurisdiction(
        api, program["id"], **WASHINGTON_WITHOUT_A_TRANSLATION_MANDATE
    )
    assert illinois["translation_required"] is True
    assert washington["translation_required"] is False
    assert washington["required_locales"] == ["en", "es"]

    policy = create_published_policy(
        api, program["id"], [illinois["id"], washington["id"]]
    )
    illinois_packet = create_notice_packet(
        api, program["id"], illinois["id"], policy["id"], locales=["en"]
    )
    washington_packet = create_notice_packet(
        api, program["id"], washington["id"], policy["id"], locales=["en"]
    )

    refused = api.transition_notice_packet(
        illinois_packet["id"], {"to_status": "PUBLISHED"}, PRIVACY_OFFICER
    )
    validate_error(refused, ApiErrorId.TRANSLATION_LOCALE_MISSING)
    still_draft = read_notice(api, illinois_packet["id"])
    assert still_draft["status"] == "DRAFT"
    assert_is_null(still_draft["published_at"], "published_at on a refused publication")

    published = validate_success(
        api.transition_notice_packet(
            washington_packet["id"], {"to_status": "PUBLISHED"}, PRIVACY_OFFICER
        )
    )
    assert published["status"] == "PUBLISHED"
    assert published["locales"] == ["en"]
    assert_instant_equals(published["published_at"], "2026-08-01T00:00:00.000Z", "published_at")
    assert_instant_equals(
        published["consent_eligible_from"], "2026-08-08T00:00:00.000Z", "consent_eligible_from"
    )

    translated = create_notice_packet(
        api, program["id"], illinois["id"], policy["id"], locales=["en", "es"]
    )
    accepted = validate_success(
        api.transition_notice_packet(translated["id"], {"to_status": "PUBLISHED"}, PRIVACY_OFFICER)
    )
    assert accepted["status"] == "PUBLISHED"
    assert_instant_equals(
        accepted["consent_eligible_from"], "2026-08-15T00:00:00.000Z", "consent_eligible_from"
    )


def test_a_retention_promise_at_exactly_the_statutory_maximum_may_be_submitted(api):
    """1200 days is refused at submission; 1095 days is not.

    PRD §3.3: "And for every state profile in the scope, the policy's `retention_days`
    must be at most that profile's `retention_max_days`; a policy promising to keep
    templates longer than any covered statute permits is rejected with
    `ERR_RETENTION_EXCEEDS_JURISDICTION_MAX`."

    PRD §3.3: "Submission stamps `submitted_by_user_id` from the acting `X-User-ID`."

    The ceiling is inclusive, so the policy sitting exactly on the Illinois maximum
    passes the same check that stops the longer one. The refused submission leaves its
    policy a first-version draft with nothing stamped.

    Design: Corner/validations/policy_submission_with_retention_beyond_the_statutory_maximum_rejected
    """
    program = create_program(api)
    illinois = create_jurisdiction(api, program["id"])
    assert illinois["retention_max_days"] == ILLINOIS_RETENTION_MAX_DAYS

    over_the_maximum = create_policy(
        api, program["id"], [illinois["id"]], version_label="v1.0", retention_days=1200
    )
    at_the_maximum = create_policy(
        api,
        program["id"],
        [illinois["id"]],
        version_label="v2.0",
        retention_days=ILLINOIS_RETENTION_MAX_DAYS,
    )

    refused = api.transition_policy(
        over_the_maximum["id"], {"to_status": "IN_REVIEW"}, PRIVACY_OFFICER
    )

    validate_error(refused, ApiErrorId.RETENTION_EXCEEDS_JURISDICTION_MAX)
    unchanged = read_policy(api, over_the_maximum["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == 1
    assert_is_null(unchanged["submitted_by_user_id"], "submitted_by_user_id after a refused submission")

    submitted = submit_policy(api, at_the_maximum["id"])
    assert submitted["status"] == "IN_REVIEW"
    assert submitted["submitted_by_user_id"] == PRIVACY_OFFICER["X-User-ID"]

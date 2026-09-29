"""The two optimistic-concurrency pins and the one clock-driven actor.

Each pin guards a different parent with its own code, and the sweep does its whole
day's work in a single call that reports what it did.
"""

from test_helpers import (
    COMPLIANCE_APPROVER,
    HR_ADMIN,
    PRIVACY_OFFICER,
    PRIVACY_OFFICER_ALT,
    SYSTEM_OPERATOR,
    ApiErrorId,
    accommodation_payload,
    accommodations_for_consent,
    assert_asset_state,
    assert_cents,
    assert_instant_equals,
    assert_is_null,
    assert_pagination,
    assert_program_state,
    create_asset,
    create_consent,
    create_data_subject,
    create_jurisdiction,
    create_policy,
    create_program,
    create_published_notice,
    current_jurisdiction_version,
    current_program_version,
    read_accommodation,
    read_asset,
    read_consent,
    read_policy,
    read_program,
    set_clock,
    submit_policy,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_publication_pinned_to_a_superseded_reading_of_the_program_is_refused(api):
    """The approver's picture of the program is stale, and only that is wrong.

    PRD §2.8: "Its value must equal the current `version` of the `ComplianceProgram` that
    owns the policy; the canonical read of that number is the program's single-resource
    read. If any other writer has advanced the program's `version` since the approver last
    read it, the publication is rejected with `ERR_STALE_PROGRAM_VERSION` (412)."

    PRD §2.8: "Publication legitimately supersedes whatever policy was published before
    it, so a second publication of a different version would succeed on its own merits —
    the stale pin is the only signal that the approver's picture of the program (its
    posture, its currently published policy, its consent-gap counters) predates another
    writer's completed publication."

    PRD §3.3: "**Hop 1**: the program's other policy whose status is `PUBLISHED` — at most
    one such row can exist — transitions `PUBLISHED` → `SUPERSEDED`."

    PRD §3.3: "Publication also recomputes the destruction horizon for every affected
    collection point, refreshing `destruction_due_at` under the newly pinned policy's
    retention terms, increments the program's `version` by 1, and refreshes the published
    policy's own `updated_at` and `version`."

    Both versions are in review and both are publishable on the merits; the first
    publication is what invalidates the second's pin, and re-reading the program is enough
    to make the identical request succeed — at which point the first version is superseded
    exactly as the pin's rationale describes.

    Design: Corner/complexity_layers/policy_publish_with_a_stale_expected_program_version_is_refused
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    first = create_policy(api, program["id"], [jurisdiction["id"]], version_label="v1.0")
    submit_policy(api, first["id"], PRIVACY_OFFICER)
    second = create_policy(
        api, program["id"], [jurisdiction["id"]], version_label="v2.0", retention_days=45
    )
    submit_policy(api, second["id"], PRIVACY_OFFICER_ALT)

    stale_version = current_program_version(api, program["id"])
    published_first = validate_success(
        api.publish_policy(
            first["id"], {"expected_program_version": stale_version}, COMPLIANCE_APPROVER
        )
    )
    assert published_first["status"] == "PUBLISHED"

    fresh_version = current_program_version(api, program["id"])
    assert fresh_version == stale_version + 1, (
        f"expected the publication to advance the program version from {stale_version}, "
        f"got {fresh_version}"
    )

    refused = api.publish_policy(
        second["id"], {"expected_program_version": stale_version}, COMPLIANCE_APPROVER
    )

    validate_error(refused, ApiErrorId.STALE_PROGRAM_VERSION)
    unchanged = read_policy(api, second["id"])
    assert unchanged["status"] == "IN_REVIEW"
    assert_is_null(unchanged["published_at"], "published_at after a refused publication")

    published_second = validate_success(
        api.publish_policy(
            second["id"], {"expected_program_version": fresh_version}, COMPLIANCE_APPROVER
        )
    )
    assert published_second["status"] == "PUBLISHED"
    assert read_policy(api, first["id"])["status"] == "SUPERSEDED"
    assert current_program_version(api, program["id"]) == fresh_version + 1


def test_an_estimate_priced_from_withdrawn_law_is_refused_by_its_jurisdiction_pin(api):
    """The second pin guards a different parent and reports a different code.

    PRD §2.8: "Its value must equal the current `version` of the `Jurisdiction` named on
    the draft; the canonical read of that number is the state profile's single-resource
    read. A mismatch is rejected with `ERR_STALE_JURISDICTION_VERSION` (412)."

    PRD §3.1: "Every amendment increments that profile's own `version` by 1 — the number
    the exposure-assessment pin observes"

    PRD §3.9: "Drafting records the acting `X-User-ID` as `created_by_user_id`, computes
    the full estimate immediately, leaves the assessment in `DRAFT` with
    `finalized_by_user_id` and `void_reason` null, and increments that state profile's
    `version` by 1."

    The amendment raises the per-violation figure the estimate would be priced from, which
    is exactly the silent mispricing the pin exists to prevent. No consents exist anywhere,
    so the accepted estimate prices at zero and the refusal cannot be confused with a
    pricing failure; the accepted draft then advances the profile's version in its own
    right.

    Design: Corner/complexity_layers/exposure_assessment_create_with_a_stale_expected_jurisdiction_version_is_refused
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    stale_version = current_jurisdiction_version(api, jurisdiction["id"])

    amended = validate_success(
        api.update_jurisdiction(
            jurisdiction["id"], {"per_violation_negligent_cents": 150000}, SYSTEM_OPERATOR
        )
    )
    assert amended["version"] == stale_version + 1
    current_version = amended["version"]

    refused = api.create_exposure_assessment(
        {
            "program_id": program["id"],
            "jurisdiction_id": jurisdiction["id"],
            "variant": "PER_VIOLATION_STACKED",
            "expected_jurisdiction_version": stale_version,
        },
        PRIVACY_OFFICER,
    )

    validate_error(refused, ApiErrorId.STALE_JURISDICTION_VERSION)
    _rows, meta = validate_paginated(
        api.list_exposure_assessments(PRIVACY_OFFICER, {"program_id": program["id"]})
    )
    assert_pagination(meta, total_count=0, has_more=False, limit=10, offset=0)

    accepted = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": program["id"],
                "jurisdiction_id": jurisdiction["id"],
                "variant": "PER_VIOLATION_STACKED",
                "expected_jurisdiction_version": current_version,
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "DRAFT"
    assert accepted["created_by_user_id"] == PRIVACY_OFFICER["X-User-ID"]
    assert_cents(accepted["exposure_cents"], 0, "exposure_cents")
    assert current_jurisdiction_version(api, jurisdiction["id"]) == current_version + 1


def test_the_sweep_at_the_due_instant_destroys_expires_and_flags_in_one_call(api):
    """One call at the inclusive boundary does four things and reports each of them.

    PRD §3.5: "For every collection point of the program whose status is `ACTIVE` or
    `GATED`, whose `destruction_due_at` is not null, and whose `destruction_due_at` is at
    or before the current clock, the sweep stamps `templates_destroyed_at` and, when the
    point was `ACTIVE`, transitions it to `GATED`. Every consent record on those points
    whose status is `GRANTED` then transitions `GRANTED` → `EXPIRED` — and, unlike the
    vendor-termination path, the sweep auto-creates **no** accommodation for these
    expiries, because a retention-driven expiry is a scheduled destruction event rather
    than a refusal to participate. The sweep additionally sets `sla_breached` to true on
    every accommodation of the program whose status is still `REQUESTED` and whose
    `sla_due_at` has passed. Finally it recomputes `gated_asset_count`,
    `consent_gap_count` and `posture`, and increments the program's `version` by 1. The
    sweep reports what it did as `swept_asset_count`, `destroyed_template_count`,
    `expired_consent_count`, `sla_breached_accommodation_count` and the resulting
    `program_posture`."

    PRD §3.5: "First, the **effective retention** in days is the smaller of the pinned
    policy's `retention_days` and the state profile's `retention_max_days` — a policy may
    promise a shorter life than the statute allows but never a longer one. The **schedule
    horizon** is `collection_started_at` plus that many whole days."

    PRD §2.9: "`consent_gap_count` on a collection point is the count of its consent
    records whose status is `SOLICITED`, `RESOLICIT_REQUIRED` or `EXPIRED`"

    Collection begins on 2026-08-15 under a thirty-day policy against a far longer
    statutory ceiling, so the horizon is 2026-09-14 and the sweep runs at exactly that
    instant rather than after it. The second individual's manual accommodation was never
    provisioned and its five-day service deadline lapsed weeks earlier, so the same call
    that destroys templates also records that breach; the resulting expiry is a fresh gap,
    which is what moves the program off `OPEN`.

    Design: Corner/complexity_layers/destruction_sweep_at_the_due_date_destroys_expires_and_flags_sla_breaches
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    policy = create_policy(api, program["id"], [jurisdiction["id"]])
    submit_policy(api, policy["id"])
    validate_success(
        api.publish_policy(
            policy["id"],
            {"expected_program_version": current_program_version(api, program["id"])},
            COMPLIANCE_APPROVER,
        )
    )
    create_published_notice(api, program["id"], jurisdiction["id"], policy["id"])
    point = create_asset(
        api, program["id"], jurisdiction["id"], target_status="CLASSIFIED"
    )

    set_clock(api, "2026-08-15T00:00:00Z")
    activated = validate_success(
        api.transition_asset(point["id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER)
    )
    assert_instant_equals(
        activated["destruction_due_at"], "2026-09-14T00:00:00.000Z", "destruction_due_at"
    )

    enrolled = create_data_subject(api, program["id"], jurisdiction["id"], "EMP-0001")
    consent = create_consent(
        api,
        enrolled["id"],
        point["id"],
        target_status="GRANTED",
        written_release_acknowledged=True,
        signature_ref="sig-emp1",
    )
    bypassed = create_data_subject(
        api, program["id"], jurisdiction["id"], "EMP-0002", accommodation_needed=True
    )
    alternative = validate_success(
        api.create_accommodation(
            accommodation_payload(
                bypassed["id"], point["id"], "2026-08-15T00:00:00Z", "2026-11-13T00:00:00Z"
            ),
            HR_ADMIN,
        ),
        expected_status=201,
    )
    assert_instant_equals(alternative["sla_due_at"], "2026-08-20T00:00:00.000Z", "sla_due_at")

    set_clock(api, "2026-09-14T00:00:00Z")

    report = validate_success(api.run_destruction_sweep(program["id"], SYSTEM_OPERATOR))

    assert report["swept_asset_count"] == 1
    assert report["destroyed_template_count"] == 1
    assert report["expired_consent_count"] == 1
    assert report["sla_breached_accommodation_count"] == 1
    assert report["program_posture"] == "RESTRICTED"

    swept_point = read_asset(api, point["id"])
    assert_asset_state(
        swept_point, status="GATED", enrolled_subject_count=0, consent_gap_count=1
    )
    assert_instant_equals(
        swept_point["templates_destroyed_at"], "2026-09-14T00:00:00.000Z", "templates_destroyed_at"
    )

    assert read_consent(api, consent["id"])["status"] == "EXPIRED"
    assert accommodations_for_consent(api, consent["id"]) == []

    still_requested = read_accommodation(api, alternative["id"])
    assert still_requested["status"] == "REQUESTED"
    assert still_requested["sla_breached"] is True

    assert_program_state(
        read_program(api, program["id"]),
        gated_asset_count=1,
        consent_gap_count=1,
        posture="RESTRICTED",
    )

"""The concurrency token on a booking path, and the promise that writes are visible."""
from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    FULL_INCLUSION_COVERAGE_RATIO,
    PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT,
    USER_COMPLIANCE_OFFICER,
    assert_stamped_at_clock,
    create_fee_program_payload,
    create_profile_payload,
    make_channel_operator_headers,
    read_disclosure_summary,
    read_fee_program,
    read_property,
    setup_program_under_review,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import COMPLIANCE, REVENUE

ATTESTATION = "Three mandatory fees, all inclusions valued."
SUCCESSOR_WINDOW = {
    "version_label": "FY27-Q1",
    "effective_from": "2026-12-01T00:00:00Z",
    "effective_to": "2027-03-01T00:00:00Z",
}


def test_the_version_a_channel_read_before_attestation_is_already_stale(api):
    """Publishing advances the token, so the pre-publish reading buys nothing.

    PRD 2.7: "`POST /channel-disclosure-profiles` requires a non-optional
    `expected_fee_program_version` field carrying the client's last observed
    `version` of the `FeeProgram` named by `fee_program_id`. If that value does
    not equal the program's current `version`, the create is rejected with
    `ERR_STALE_FEE_PROGRAM_VERSION` (HTTP 412). A successful create increments
    `FeeProgram.version` by exactly 1."

    Design: Corner/cross_cutting_complexity_layers/stale_fee_program_version_on_profile_create_is_rejected
    """
    env = setup_program_under_review()
    property_id = env["property"]["id"]
    channel_id = env["channel"]["id"]
    operator = make_channel_operator_headers(channel_id)
    observed_before_publish = env["program"]["version"]

    published = validate_success(
        api.publish_fee_program(env["program"]["id"], ATTESTATION, COMPLIANCE)
    )
    current = published["version"]
    assert current == observed_before_publish + 1

    def create_path(expected_version, program_id=None):
        return api.create_channel_disclosure_profile(
            create_profile_payload(
                property_id, channel_id, program_id or published["id"], expected_version
            ),
            operator,
        )

    validate_error(
        create_path(observed_before_publish),
        ApiErrorId.ERR_STALE_FEE_PROGRAM_VERSION,
        412,
    )
    # The check is equality, so a version from the future fails just as hard.
    validate_error(
        create_path(current + 1), ApiErrorId.ERR_STALE_FEE_PROGRAM_VERSION, 412
    )
    _paths, meta = validate_paginated(
        api.list_channel_disclosure_profiles(REVENUE, {"limit": 100})
    )
    assert meta["total_count"] == 0
    assert read_fee_program(published["id"])["version"] == current

    # The token was the only obstacle: every business precondition already held.
    path = validate_success(create_path(current), 201)
    assert path["status"] == "DRAFT"
    assert path["disclosure_score"] == 100
    assert read_fee_program(published["id"])["version"] == current + 1

    # Replaying the accepted token now trips the same rule.
    validate_error(create_path(current), ApiErrorId.ERR_STALE_FEE_PROGRAM_VERSION, 412)

    # Rank 11 answers before the publication-status rule at rank 14.
    unpublished = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                property_id, read_property(property_id)["version"], **SUCCESSOR_WINDOW
            ),
            REVENUE,
        ),
        201,
    )
    assert unpublished["status"] == "DRAFT"
    validate_error(
        create_path(unpublished["version"] + 5, program_id=unpublished["id"]),
        ApiErrorId.ERR_STALE_FEE_PROGRAM_VERSION,
        412,
    )
    validate_error(
        create_path(unpublished["version"], program_id=unpublished["id"]),
        ApiErrorId.ERR_FEE_PROGRAM_NOT_PUBLISHED,
        409,
    )


def test_a_publication_is_fully_readable_in_its_own_response(api):
    """The four rollups arrive with the write, and the parent counter with it.

    PRD 3.2: "On success the program moves `UNDER_REVIEW → PUBLISHED`, its
    `attested_by_user_id` is set from the acting `X-User-ID` and its
    `published_at` is set to the current logical clock. This is also the single
    moment at which the two heavier rollups leave their defaults." PRD 2.9: "Every
    field it reports must equal the denormalised counterpart stored on the
    property row".

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_writing_response
    """
    env = setup_program_under_review()
    property_id = env["property"]["id"]
    before = read_property(property_id)
    assert before["published_fee_program_count"] == 0
    assert before["min_channel_disclosure_score"] is None
    assert before["disclosure_posture"] == "COMPLIANT"

    published = validate_success(
        api.publish_fee_program(env["program"]["id"], ATTESTATION, COMPLIANCE)
    )

    # Everything the publication derives is in the writing response itself.
    assert published["status"] == "PUBLISHED"
    assert_stamped_at_clock(published["published_at"], CLOCK_START, "published_at")
    assert published["attested_by_user_id"] == USER_COMPLIANCE_OFFICER
    assert published["attestation_note"] == ATTESTATION
    assert published["fee_count"] == 3
    assert published["mandatory_fee_count"] == 3
    assert published["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT
    )
    assert float(published["inclusion_coverage_ratio"]) == FULL_INCLUSION_COVERAGE_RATIO

    # The parent counter is current on the very next read, with nothing between.
    after = read_property(property_id)
    assert after["published_fee_program_count"] == 1
    assert after["version"] == before["version"] + 1

    # The computed read and the denormalised row agree at the same instant.
    summary = read_disclosure_summary(property_id, COMPLIANCE)
    assert summary["published_fee_program_count"] == 1
    assert summary["total_mandatory_fee_cents_per_night"] == (
        PUBLISHED_TOTAL_MANDATORY_FEE_CENTS_PER_NIGHT
    )
    assert summary["min_channel_disclosure_score"] is None
    assert summary["disclosure_posture"] == "COMPLIANT"

    # List projections are not deferred either.
    rows, meta = validate_paginated(
        api.list_fee_programs(
            REVENUE, {"property_id": property_id, "status": "PUBLISHED", "limit": 100}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [published["id"]]

    # The first write was committed before it answered, so it cannot repeat.
    snapshot = read_fee_program(published["id"])
    assert snapshot == published
    validate_error(
        api.publish_fee_program(published["id"], ATTESTATION, COMPLIANCE),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    # Nothing converges later: a read with no intervening write is identical.
    assert read_fee_program(published["id"]) == snapshot

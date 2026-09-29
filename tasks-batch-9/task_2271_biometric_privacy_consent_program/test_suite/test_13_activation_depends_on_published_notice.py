"""Activation waits on a row that is not the collection point.

The point itself is admissible, but collection cannot begin until the notice packet
covering its state and its population has actually been published.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    ApiErrorId,
    assert_asset_state,
    assert_instant_equals,
    assert_is_null,
    assert_program_state,
    create_asset,
    create_notice_packet,
    create_program,
    create_jurisdiction,
    create_published_policy,
    read_asset,
    read_notice,
    read_program,
    validate_error,
    validate_success,
)


def _classified_point_under_an_unpublished_notice(api):
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    policy = create_published_policy(api, program["id"], [jurisdiction["id"]])
    notice = create_notice_packet(
        api, program["id"], jurisdiction["id"], policy["id"], locales=["en", "es"]
    )
    asset = create_asset(
        api, program["id"], jurisdiction["id"], target_status="CLASSIFIED"
    )
    return {
        "program_id": program["id"],
        "jurisdiction_id": jurisdiction["id"],
        "policy_id": policy["id"],
        "notice_id": notice["id"],
        "asset_id": asset["id"],
    }


def test_activation_is_refused_while_the_covering_notice_is_still_a_draft(api):
    """The point is faultless; the packet is not published.

    PRD §3.5: "A notice packet with status `PUBLISHED` whose `jurisdiction_id`
    equals the point's and whose `audience` equals the point's `subject_class` must
    exist, else `ERR_NOTICE_NOT_PUBLISHED`."

    The point is `CLASSIFIED`, the program is `OPEN`, the policy is published and
    scoped to Illinois, and no processor operates the surface, so the only unmet
    precondition lives on the other row.

    Design: Difficulty/cross_entity_state_dependency/asset_activation_requires_notice_packet_in_published_state
    """
    ctx = _classified_point_under_an_unpublished_notice(api)
    assert read_notice(api, ctx["notice_id"])["status"] == "DRAFT"

    refused = api.transition_asset(ctx["asset_id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER)

    validate_error(refused, ApiErrorId.NOTICE_NOT_PUBLISHED)

    unchanged = read_asset(api, ctx["asset_id"])
    assert unchanged["status"] == "CLASSIFIED"
    assert_is_null(unchanged["pinned_policy_id"], "pinned_policy_id on a refused activation")
    assert_is_null(unchanged["collection_started_at"], "collection_started_at on a refused activation")


def test_publishing_the_notice_lets_the_identical_activation_succeed(api):
    """Touching only the packet unblocks the point.

    PRD §3.4: "Successful publication stamps `published_at` from the current
    logical clock and computes `consent_eligible_from` as `published_at` plus the
    governing state profile's `notice_lead_days`."

    Illinois imposes a fourteen-day lead time, so a packet published on 2026-08-01
    only becomes usable for solicitation on 2026-08-15 — yet activation itself is
    unblocked the moment the packet reaches `PUBLISHED`.

    Design: Difficulty/cross_entity_state_dependency/asset_activation_requires_notice_packet_in_published_state
    """
    ctx = _classified_point_under_an_unpublished_notice(api)

    published = validate_success(
        api.transition_notice_packet(ctx["notice_id"], {"to_status": "PUBLISHED"}, PRIVACY_OFFICER)
    )
    assert published["status"] == "PUBLISHED"
    assert_instant_equals(published["published_at"], "2026-08-01T00:00:00.000Z", "published_at")
    assert_instant_equals(
        published["consent_eligible_from"], "2026-08-15T00:00:00.000Z", "consent_eligible_from"
    )

    activated = validate_success(
        api.transition_asset(ctx["asset_id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER)
    )

    assert_asset_state(
        activated,
        status="ACTIVE",
        pinned_policy_id=ctx["policy_id"],
        collection_started_at="2026-08-01T00:00:00.000Z",
    )
    assert_program_state(
        read_program(api, ctx["program_id"]),
        inventory_completeness_pct=100.00,
        posture="OPEN",
    )

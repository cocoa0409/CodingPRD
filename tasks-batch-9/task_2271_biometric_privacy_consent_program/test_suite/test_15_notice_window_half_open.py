"""Contention for one publication slot per state and audience.

A genuinely intersecting window is refused, while a window that starts exactly
where the incumbent ends is not an intersection at all.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    ApiErrorId,
    assert_instant_equals,
    assert_is_null,
    assert_pagination,
    create_jurisdiction,
    create_notice_packet,
    create_program,
    create_published_policy,
    read_notice,
    validate_error,
    validate_paginated,
    validate_success,
)


def _one_published_month_and_two_candidates(api):
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    policy = create_published_policy(api, program["id"], [jurisdiction["id"]])

    incumbent = create_notice_packet(
        api,
        program["id"],
        jurisdiction["id"],
        policy["id"],
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    validate_success(
        api.transition_notice_packet(incumbent["id"], {"to_status": "PUBLISHED"}, PRIVACY_OFFICER)
    )
    straddling = create_notice_packet(
        api,
        program["id"],
        jurisdiction["id"],
        policy["id"],
        effective_from="2026-08-15T00:00:00Z",
        effective_to="2026-09-15T00:00:00Z",
    )
    abutting = create_notice_packet(
        api,
        program["id"],
        jurisdiction["id"],
        policy["id"],
        effective_from="2026-09-01T00:00:00Z",
    )
    return {
        "program_id": program["id"],
        "jurisdiction_id": jurisdiction["id"],
        "incumbent_id": incumbent["id"],
        "straddling_id": straddling["id"],
        "abutting_id": abutting["id"],
    }


def test_a_straddling_window_cannot_be_published(api):
    """An interval that really intersects the incumbent is refused.

    PRD §3.4: "A genuine intersection is rejected with
    `ERR_NOTICE_WINDOW_OVERLAP`."

    The candidate runs from mid-August to mid-September while the incumbent holds
    the whole of August, so the fortnight from 2026-08-15 to 2026-09-01 belongs to
    both.

    Design: Difficulty/resource_temporal_overlap/notice_windows_are_half_open_so_abutting_packets_are_allowed
    """
    ctx = _one_published_month_and_two_candidates(api)

    refused = api.transition_notice_packet(
        ctx["straddling_id"], {"to_status": "PUBLISHED"}, PRIVACY_OFFICER
    )

    validate_error(refused, ApiErrorId.NOTICE_WINDOW_OVERLAP)

    unchanged = read_notice(api, ctx["straddling_id"])
    assert unchanged["status"] == "DRAFT"
    assert_is_null(unchanged["published_at"], "published_at on a refused publication")
    assert_is_null(unchanged["consent_eligible_from"], "consent_eligible_from on a refused publication")


def test_an_abutting_window_publishes_alongside_the_incumbent(api):
    """The exclusive end means the successor may start on it.

    PRD §3.4: "Overlap is judged under **half-open** semantics on the interval from
    `effective_from` inclusive to `effective_to` exclusive, with a null
    `effective_to` treated as positive infinity; consequently two abutting windows,
    where the earlier packet's `effective_to` equals the later packet's
    `effective_from`, do **not** overlap and both may be published."

    The successor opens at 2026-09-01 with an open end, exactly where the incumbent
    closes, and publishing it leaves the incumbent published too, so the slot lists
    two published packets.

    Design: Difficulty/resource_temporal_overlap/notice_windows_are_half_open_so_abutting_packets_are_allowed
    """
    ctx = _one_published_month_and_two_candidates(api)

    published = validate_success(
        api.transition_notice_packet(ctx["abutting_id"], {"to_status": "PUBLISHED"}, PRIVACY_OFFICER)
    )

    assert published["status"] == "PUBLISHED"
    assert_instant_equals(published["published_at"], "2026-08-01T00:00:00.000Z", "published_at")
    assert_instant_equals(
        published["consent_eligible_from"], "2026-08-15T00:00:00.000Z", "consent_eligible_from"
    )
    assert read_notice(api, ctx["incumbent_id"])["status"] == "PUBLISHED", (
        "publishing an abutting packet does not withdraw the incumbent"
    )

    rows, meta = validate_paginated(
        api.list_notice_packets(
            PRIVACY_OFFICER,
            {
                "jurisdiction_id": ctx["jurisdiction_id"],
                "audience": "EMPLOYEE",
                "status": "PUBLISHED",
            },
        )
    )
    assert_pagination(meta, total_count=2, has_more=False, limit=10, offset=0)
    assert {row["id"] for row in rows} == {ctx["incumbent_id"], ctx["abutting_id"]}

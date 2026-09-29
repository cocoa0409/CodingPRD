"""Temporal window exclusivity for methodology versions and measurement batches.

Two window regimes coexist and they are deliberately different. A methodology
version's effectivity window is a half-open interval whose no-overlap rule is
scoped to a single `standard_family`, so exactly abutting windows succeed one
another legally and a window of another family may occupy the same calendar
span. A measurement batch's delivery window is a closed interval that demands
more than 60 seconds of clear air at both ends, scoped to one campaign, page
and format triple.
"""
from datetime import datetime

from test_helpers import (
    AUDITOR_AUTHOR_USER_ID,
    ApiErrorId,
    advance_clock,
    assert_measurement_batch,
    assert_methodology_version,
    factories,
    make_admin_headers,
    make_auditor_headers,
    make_operator_headers,
    setup_base_world,
    setup_methodology_version,
    setup_page,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T00:00:00Z"


def _instant(iso8601: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds.

    The PRD fixes the three-fractional-digit form for the timestamps the server
    mints itself (2.4) but says nothing about the textual form in which a
    client-supplied instant such as `effective_from` or `window_start` is echoed
    back, so these windows are compared as instants rather than as strings.
    """
    return datetime.fromisoformat(iso8601.replace("Z", "+00:00"))


VIEWABILITY_THRESHOLDS = {
    "display_in_view_seconds": 1.0,
    "display_pixel_pct": 0.5,
    "coverage_rate_floor": 0.7,
    "ivt_rate_ceiling": 0.02,
}

#: The incumbent VIEWABILITY window: [2026-01-01T00:00:00Z, 2026-06-01T00:00:00Z).
INCUMBENT_FROM = "2026-01-01T00:00:00Z"
INCUMBENT_TO = "2026-06-01T00:00:00Z"

#: The incumbent batch's closed delivery window, in the past at the test clock.
BASE_WINDOW_START = "2026-07-01T00:00:00Z"
BASE_WINDOW_END = "2026-07-01T01:00:00Z"


def _auditor_headers():
    """The authoring AccreditationAuditor: methodology versions are its work."""
    return make_auditor_headers(AUDITOR_AUTHOR_USER_ID)


def _methodology_payload(standard_family, version_code, effective_from, effective_to,
                         **overrides):
    payload = factories.create_methodology_version_payload(
        standard_family=standard_family,
        version_code=version_code,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    payload.update(overrides)
    return payload


def _setup_incumbent_viewability_version(api):
    """Move the clock and author VIEW-2026.1 over [2026-01-01, 2026-06-01)."""
    advance_clock(api, CLOCK)
    return setup_methodology_version(
        api,
        standard_family="VIEWABILITY",
        author_user_id=AUDITOR_AUTHOR_USER_ID,
        version_code="VIEW-2026.1",
        effective_from=INCUMBENT_FROM,
        effective_to=INCUMBENT_TO,
        **VIEWABILITY_THRESHOLDS,
    )


def _batch_payload(world, page_id, window_start, window_end):
    """One DISPLAY delivery of the base world's campaign on the given page."""
    return factories.create_measurement_batch_payload(
        world["campaign"]["id"],
        world["publisher"]["id"],
        page_id,
        world["viewability_version"]["id"],
        window_start=window_start,
        window_end=window_end,
        format="DISPLAY",
        measured_impressions=4000,
        measurable_impressions=3000,
        in_view_impressions=2500,
        avg_in_view_seconds=1.2,
        avg_in_view_pixel_pct=0.6,
    )


def _ingest(api, payload):
    return api.create_measurement_batch(payload, make_operator_headers())


def _setup_batch_world(api):
    """The base world plus a second page under the same publisher, and an
    incumbent batch on the first page over [07-01T00:00:00Z, 07-01T01:00:00Z].
    """
    world = setup_base_world(api, clock=CLOCK)
    second_page = setup_page(
        api, world["publisher"]["id"], url="https://beacon.example.com/page-two"
    )
    incumbent = validate_success(
        _ingest(
            api,
            _batch_payload(
                world, world["page"]["id"], BASE_WINDOW_START, BASE_WINDOW_END
            ),
        ),
        expected_status=201,
    )
    return world, second_page, incumbent


# ---------------------------------------------------------------------------
# Methodology effectivity windows: half-open and scoped to one standard family
# ---------------------------------------------------------------------------
def test_abutting_methodology_window_is_accepted(api):
    """A successor version starting exactly where the incumbent's window ends is authored.

    PRD: "Inside one `standard_family` windows may not overlap, and an attempt to author an overlapping version answers `ERR_METHODOLOGY_WINDOW_OVERLAP`; windows that abut exactly, where the earlier version's `effective_to` equals the new version's `effective_from`, are legal and are the normal way to succeed a standard."

    Design: Difficulty/resource_temporal_overlap/methodology_windows_are_half_open_and_family_scoped
    """
    incumbent = _setup_incumbent_viewability_version(api)

    response = api.create_methodology_version(
        _methodology_payload(
            "VIEWABILITY", "VIEW-2026.2", INCUMBENT_TO, "2026-09-01T00:00:00Z",
            display_in_view_seconds=1.0,
            display_pixel_pct=0.5,
            coverage_rate_floor=0.6,
            ivt_rate_ceiling=0.02,
        ),
        _auditor_headers(),
    )

    successor = validate_success(response, expected_status=201)
    assert_methodology_version(successor)
    assert _instant(successor["effective_from"]) == _instant(INCUMBENT_TO), (
        f"expected the successor to start at {INCUMBENT_TO}, "
        f"got {successor['effective_from']} after authoring VIEW-2026.2"
    )
    assert successor["accreditation_status"] == "PROVISIONAL", (
        "expected PROVISIONAL, got "
        f"{successor['accreditation_status']} for a freshly authored version"
    )

    listed, meta = validate_paginated(
        api.list_methodology_versions(
            make_admin_headers(), params={"standard_family": "VIEWABILITY"}
        )
    )
    assert meta["total_count"] == 2, (
        f"expected 2 VIEWABILITY versions, got {meta['total_count']} "
        "after an abutting window was accepted"
    )
    assert {row["id"] for row in listed} == {incumbent["id"], successor["id"]}, (
        "expected exactly the incumbent and its abutting successor, got "
        f"{[row['version_code'] for row in listed]}"
    )


def test_methodology_window_overlapping_by_one_second_is_refused(api):
    """A version starting one second before the incumbent's end instant is refused.

    PRD: "Inside one `standard_family` windows may not overlap, and an attempt to author an overlapping version answers `ERR_METHODOLOGY_WINDOW_OVERLAP`; windows that abut exactly, where the earlier version's `effective_to` equals the new version's `effective_from`, are legal and are the normal way to succeed a standard."

    Design: Difficulty/resource_temporal_overlap/methodology_windows_are_half_open_and_family_scoped
    """
    incumbent = _setup_incumbent_viewability_version(api)

    response = api.create_methodology_version(
        _methodology_payload(
            "VIEWABILITY", "VIEW-2026.3",
            "2026-05-31T23:59:59Z", "2026-07-01T00:00:00Z",
            display_in_view_seconds=1.0,
            display_pixel_pct=0.5,
            coverage_rate_floor=0.6,
            ivt_rate_ceiling=0.02,
        ),
        _auditor_headers(),
    )

    validate_error(response, ApiErrorId.ERR_METHODOLOGY_WINDOW_OVERLAP.value,
                   expected_status=409)

    listed, meta = validate_paginated(
        api.list_methodology_versions(
            make_admin_headers(), params={"standard_family": "VIEWABILITY"}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected the refused version not to be stored, got {meta['total_count']} "
        "VIEWABILITY versions"
    )
    assert listed[0]["id"] == incumbent["id"], (
        f"expected only {incumbent['version_code']} to survive, got "
        f"{listed[0]['version_code']}"
    )


def test_methodology_window_overlap_is_scoped_to_one_standard_family(api):
    """A SUITABILITY window sitting squarely inside the VIEWABILITY incumbent's is authored.

    PRD: "Inside one `standard_family` windows may not overlap, and an attempt to author an overlapping version answers `ERR_METHODOLOGY_WINDOW_OVERLAP`; windows that abut exactly, where the earlier version's `effective_to` equals the new version's `effective_from`, are legal and are the normal way to succeed a standard."

    Design: Difficulty/resource_temporal_overlap/methodology_windows_are_half_open_and_family_scoped
    """
    incumbent = _setup_incumbent_viewability_version(api)

    response = api.create_methodology_version(
        _methodology_payload(
            "SUITABILITY", "SUIT-2026.1",
            "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z",
        ),
        _auditor_headers(),
    )

    suitability = validate_success(response, expected_status=201)
    assert_methodology_version(suitability)
    assert suitability["standard_family"] == "SUITABILITY", (
        f"expected SUITABILITY, got {suitability['standard_family']}"
    )
    assert suitability["accreditation_status"] == "PROVISIONAL", (
        "expected PROVISIONAL, got "
        f"{suitability['accreditation_status']} for a freshly authored version"
    )
    assert incumbent["effective_from"] <= suitability["effective_from"], (
        "the SUITABILITY window must start inside the VIEWABILITY incumbent's window "
        f"for this case to bite, got {suitability['effective_from']}"
    )
    assert suitability["effective_to"] <= incumbent["effective_to"], (
        "the SUITABILITY window must end inside the VIEWABILITY incumbent's window "
        f"for this case to bite, got {suitability['effective_to']}"
    )

    for family, expected_id in (
        ("VIEWABILITY", incumbent["id"]),
        ("SUITABILITY", suitability["id"]),
    ):
        listed, meta = validate_paginated(
            api.list_methodology_versions(
                make_admin_headers(), params={"standard_family": family}
            )
        )
        assert meta["total_count"] == 1, (
            f"expected exactly 1 {family} version, got {meta['total_count']}"
        )
        assert listed[0]["id"] == expected_id, (
            f"expected {family} to list the version authored for it, got "
            f"{listed[0]['version_code']}"
        )


# ---------------------------------------------------------------------------
# Batch delivery windows: closed intervals plus a 60-second buffer, keyed on
# (campaign_id, page_id, format)
# ---------------------------------------------------------------------------
def test_batch_window_starting_inside_the_sixty_second_buffer_collides(api):
    """A delivery starting 45 seconds after the incumbent window's end is refused.

    PRD: "And two batches sharing the same `campaign_id`, `page_id` and `format` must be separated by more than 60 seconds of clear air at both ends, as spelled out in §2.8; an overlap or a too-close abutment answers `ERR_BATCH_WINDOW_COLLISION`."

    Design: Difficulty/resource_temporal_overlap/batch_windows_are_closed_with_a_sixty_second_buffer_per_page_and_format
    """
    world, _second_page, incumbent = _setup_batch_world(api)

    response = _ingest(
        api,
        _batch_payload(
            world, world["page"]["id"],
            "2026-07-01T01:00:45Z", "2026-07-01T02:00:00Z",
        ),
    )

    validate_error(response, ApiErrorId.ERR_BATCH_WINDOW_COLLISION.value,
                   expected_status=409)

    listed, meta = validate_paginated(
        api.list_measurement_batches(
            make_admin_headers(), params={"page_id": world["page"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected the refused batch not to be stored, got {meta['total_count']} "
        "batches on the page"
    )
    assert listed[0]["id"] == incumbent["id"], (
        "expected only the incumbent batch to survive the collision, got "
        f"{listed[0]['id']}"
    )


def test_batch_window_clear_of_the_sixty_second_buffer_is_ingested(api):
    """A delivery starting 61 seconds after the incumbent window's end is ingested.

    PRD: "And two batches sharing the same `campaign_id`, `page_id` and `format` must be separated by more than 60 seconds of clear air at both ends, as spelled out in §2.8; an overlap or a too-close abutment answers `ERR_BATCH_WINDOW_COLLISION`."

    Design: Difficulty/resource_temporal_overlap/batch_windows_are_closed_with_a_sixty_second_buffer_per_page_and_format
    """
    world, _second_page, incumbent = _setup_batch_world(api)

    response = _ingest(
        api,
        _batch_payload(
            world, world["page"]["id"],
            "2026-07-01T01:01:01Z", "2026-07-01T02:00:00Z",
        ),
    )

    cleared = validate_success(response, expected_status=201)
    assert_measurement_batch(cleared)
    assert _instant(cleared["window_start"]) == _instant("2026-07-01T01:01:01Z"), (
        f"expected window_start 2026-07-01T01:01:01Z, got {cleared['window_start']}"
    )
    assert cleared["scoring_status"] == "INGESTED", (
        f"expected INGESTED, got {cleared['scoring_status']} for a freshly ingested batch"
    )
    assert cleared["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {cleared['settlement_status']} "
        "for a freshly ingested batch"
    )

    listed, meta = validate_paginated(
        api.list_measurement_batches(
            make_admin_headers(), params={"page_id": world["page"]["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"expected 2 batches on the page, got {meta['total_count']} after 61 seconds "
        "of separation cleared the buffer"
    )
    assert {row["id"] for row in listed} == {incumbent["id"], cleared["id"]}, (
        "expected the incumbent and the newly ingested batch, got "
        f"{[row['id'] for row in listed]}"
    )
    for row in listed:
        assert row["scoring_status"] == "INGESTED", (
            f"expected INGESTED, got {row['scoring_status']} for batch {row['id']}"
        )
        assert row["settlement_status"] == "UNBILLED", (
            f"expected UNBILLED, got {row['settlement_status']} for batch {row['id']}"
        )


def test_colliding_batch_window_on_a_different_page_is_ingested(api):
    """The same too-close window is accepted on another page of the same campaign.

    PRD: "And two batches sharing the same `campaign_id`, `page_id` and `format` must be separated by more than 60 seconds of clear air at both ends, as spelled out in §2.8; an overlap or a too-close abutment answers `ERR_BATCH_WINDOW_COLLISION`."

    Design: Difficulty/resource_temporal_overlap/batch_windows_are_closed_with_a_sixty_second_buffer_per_page_and_format
    """
    world, second_page, incumbent = _setup_batch_world(api)

    response = _ingest(
        api,
        _batch_payload(
            world, second_page["id"],
            "2026-07-01T01:00:45Z", "2026-07-01T02:00:00Z",
        ),
    )

    other_page_batch = validate_success(response, expected_status=201)
    assert_measurement_batch(other_page_batch)
    assert other_page_batch["page_id"] == second_page["id"], (
        f"expected the batch on page {second_page['id']}, "
        f"got {other_page_batch['page_id']}"
    )
    assert other_page_batch["campaign_id"] == world["campaign"]["id"], (
        "the colliding window must belong to the same campaign for this case to bite, "
        f"got {other_page_batch['campaign_id']}"
    )
    assert other_page_batch["scoring_status"] == "INGESTED", (
        f"expected INGESTED, got {other_page_batch['scoring_status']}"
    )
    assert other_page_batch["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {other_page_batch['settlement_status']}"
    )

    for page_id, expected_id in (
        (world["page"]["id"], incumbent["id"]),
        (second_page["id"], other_page_batch["id"]),
    ):
        listed, meta = validate_paginated(
            api.list_measurement_batches(
                make_admin_headers(), params={"page_id": page_id}
            )
        )
        assert meta["total_count"] == 1, (
            f"expected exactly 1 batch on page {page_id}, got {meta['total_count']}"
        )
        assert listed[0]["id"] == expected_id, (
            f"expected batch {expected_id} on page {page_id}, got {listed[0]['id']}"
        )

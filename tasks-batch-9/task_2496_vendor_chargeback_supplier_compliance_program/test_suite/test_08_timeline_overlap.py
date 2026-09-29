"""Two timelines with deliberately different adjacency rules.

Routing guide editions live on half-open effectivity intervals, so a successor
that starts at the instant the incumbent is cut short is legal, while a candidate
that starts at or after the incumbent's own start instant is not.  Scorecard
periods live on closed intervals *plus* a mandatory one-day clearance, so
back-to-back periods are refused and only a genuine gap is accepted.
"""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    REQ_LBL_01,
    REQ_PKG_02,
    add_requirement,
    create_guide,
    create_scorecard,
    create_vendor,
    publish_guide,
    read_guide,
    read_requirements,
    read_scorecard,
    scorecard_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PROGRAMME_START = "2026-08-01T00:00:00Z"
SHARED_INSTANT = "2026-09-01T00:00:00Z"
NEXT_INSTANT = "2026-09-02T00:00:00Z"


def _instant(value: str) -> datetime:
    """Compare two ISO 8601 UTC instants without depending on their spelling."""
    assert value is not None, "expected a timestamp, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Routing guide effectivity: shared start collides, adjacency does not
# ---------------------------------------------------------------------------
def _guide_timeline_world():
    """A published incumbent plus two draft candidates.

    The first candidate opens at the incumbent's own start instant; the second
    opens one day later and names the incumbent as the edition it supersedes.
    """
    set_clock(PROGRAMME_START)
    incumbent = create_guide(
        guide_code="RG-APP-1",
        title="Apparel Routing Guide",
        scope_code="LABELING",
        effective_from=SHARED_INSTANT,
    )
    incumbent_requirement = add_requirement(incumbent["id"], REQ_LBL_01)
    incumbent = publish_guide(incumbent["id"])

    same_instant = create_guide(
        guide_code="RG-ALL-SAME",
        title="All-Scope Guide, Same Instant",
        scope_code="ALL",
        effective_from=SHARED_INSTANT,
    )
    add_requirement(same_instant["id"], REQ_PKG_02)

    successor = create_guide(
        guide_code="RG-ALL-NEXT",
        title="All-Scope Guide, Next Instant",
        scope_code="ALL",
        effective_from=NEXT_INSTANT,
        supersedes_guide_id=incumbent["id"],
    )
    add_requirement(
        successor["id"],
        {**REQ_PKG_02, "fixed_fee_cents": 22_000, "per_unit_recovery_cents": 27},
    )
    return {
        "incumbent": incumbent,
        "incumbent_requirement": incumbent_requirement,
        "same_instant": same_instant,
        "successor": successor,
    }


def test_guide_publication_refused_when_an_all_scope_edition_shares_the_start_instant(
    api, officer_headers
):
    """PRD §3.2: "Timeline collision is then checked: publication is refused with
    `ERR_GUIDE_EFFECTIVE_OVERLAP` when any colliding edition that is already
    `PUBLISHED` has an `effective_from` at or later than the candidate's
    `effective_from`."
    PRD §3.2: "Editions sharing a `scope_code` form a single effectivity timeline,
    and an edition scoped `ALL` shares a timeline with every other scope — two
    editions collide when their `scope_code` values are equal or when either one
    of them is `ALL`."
    PRD §3.2: "A freshly drafted edition is `DRAFT`, with `requirement_count` 0,
    `effective_until` null, and `published_at` and `published_by_user_id` both
    null."

    Design: Difficulty/resource_temporal_overlap/routing_guide_scope_timeline_half_open_adjacency_allowed
    """
    world = _guide_timeline_world()
    assert world["incumbent"]["status"] == "PUBLISHED", (
        f"the incumbent must be live, got {world['incumbent']['status']}"
    )

    validate_error(
        api.publish_routing_guide(world["same_instant"]["id"], officer_headers),
        ApiErrorId.ERR_GUIDE_EFFECTIVE_OVERLAP,
        409,
    )

    refused = read_guide(world["same_instant"]["id"])
    assert refused["status"] == "DRAFT", (
        f"a refused publication leaves the edition in DRAFT, got {refused['status']}"
    )
    assert refused["published_at"] is None, (
        f"a refused publication stamps nothing, got {refused['published_at']}"
    )


def test_guide_publication_accepted_at_the_next_instant_and_supersedes_the_incumbent(
    api, officer_headers
):
    """PRD §3.2: "Timeline collision is then checked: publication is refused with
    `ERR_GUIDE_EFFECTIVE_OVERLAP` when any colliding edition that is already
    `PUBLISHED` has an `effective_from` at or later than the candidate's
    `effective_from`."
    PRD §3.2: "Effectivity intervals are half-open, running from `effective_from`
    inclusive to `effective_until` exclusive, so adjacency at a shared instant is
    allowed: a successor edition may begin at exactly the instant its
    predecessor's window ends."
    PRD §3.2: "The second link, caused by the first, applies only when
    `supersedes_guide_id` was supplied: the named predecessor moves `PUBLISHED →
    SUPERSEDED` and its `effective_until` is stamped with the successor's
    `effective_from`, closing its half-open window at exactly the instant the new
    edition opens. The third link, caused by the second, copies that same
    `effective_until` down onto every requirement owned by the superseded
    predecessor, retiring the old fee schedule without deleting a single row — an
    assessment computed under the old schedule must remain explicable years
    later."
    PRD §3.2: "A `SUPERSEDED` edition is terminal; while an edition is `DRAFT` or
    `PUBLISHED` its `effective_until` and its requirements' `effective_until`
    remain null, meaning the window is open-ended above."

    Design: Difficulty/resource_temporal_overlap/routing_guide_scope_timeline_half_open_adjacency_allowed
    """
    world = _guide_timeline_world()
    validate_error(
        api.publish_routing_guide(world["same_instant"]["id"], officer_headers),
        ApiErrorId.ERR_GUIDE_EFFECTIVE_OVERLAP,
        409,
    )

    published = validate_success(
        api.publish_routing_guide(world["successor"]["id"], officer_headers), 200
    )
    assert published["status"] == "PUBLISHED", (
        f"expected PUBLISHED, got {published['status']}"
    )
    assert _instant(published["effective_from"]) == _instant(NEXT_INSTANT), (
        f"expected effective_from {NEXT_INSTANT}, got {published['effective_from']}"
    )
    assert published["effective_until"] is None, (
        f"the live edition has no end instant, got {published['effective_until']}"
    )

    incumbent = read_guide(world["incumbent"]["id"])
    assert incumbent["status"] == "SUPERSEDED", (
        f"expected SUPERSEDED, got {incumbent['status']}"
    )
    assert _instant(incumbent["effective_until"]) == _instant(NEXT_INSTANT), (
        "the predecessor's last instant is the successor's first, expected "
        f"{NEXT_INSTANT}, got {incumbent['effective_until']}"
    )

    requirements = read_requirements(world["incumbent"]["id"])
    closed = [
        item for item in requirements if item["id"] == world["incumbent_requirement"]["id"]
    ]
    assert len(closed) == 1, (
        f"the predecessor's requirement must still be listed, got {len(closed)} matches"
    )
    assert _instant(closed[0]["effective_until"]) == _instant(NEXT_INSTANT), (
        "the end instant is copied down onto the requirement, expected "
        f"{NEXT_INSTANT}, got {closed[0]['effective_until']}"
    )

    _, meta = validate_paginated(
        api.list_routing_guides(officer_headers, params={"status": "PUBLISHED"})
    )
    assert meta["total_count"] == 1, (
        f"only one edition may be live at a time, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Scorecard periods: closed intervals with a mandatory one-day clearance
# ---------------------------------------------------------------------------
def _scorecard_timeline_world():
    """One OPEN scorecard covering June 2026 for a single supplier."""
    set_clock(PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V1401",
        legal_name="Clearance Cutlery",
        payment_terms_days=30,
    )
    incumbent = create_scorecard(
        vendor["id"],
        period_code="2026-06",
        period_start="2026-06-01T00:00:00Z",
        period_end="2026-06-30T00:00:00Z",
    )
    return {"vendor": vendor, "incumbent": incumbent}


def test_scorecard_creation_refused_when_the_next_period_starts_without_clearance(
    api, officer_headers
):
    """PRD §3.7: "Periods of the same supplier may neither overlap nor touch, and
    must in fact clear each other by a full day. Both endpoints of a period are
    treated as occupied, and a mandatory clearance of one day is added on top, so
    a candidate period is refused with `ERR_SCORECARD_PERIOD_OVERLAP` when any
    existing scorecard of the same supplier in `OPEN`, `MEASURED` or `FINALIZED`
    satisfies both of these conditions at once: the candidate's `period_start` is
    at or before that scorecard's `period_end` plus one day, and that scorecard's
    `period_start` is at or before the candidate's `period_end` plus one day. Two
    periods whose endpoints are a single day apart therefore collide."

    Design: Difficulty/resource_temporal_overlap/scorecard_period_timeline_closed_interval_with_mandatory_clearance
    """
    world = _scorecard_timeline_world()

    validate_error(
        api.create_scorecard(
            scorecard_payload(
                world["vendor"]["id"],
                period_code="2026-07",
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-07-31T00:00:00Z",
            ),
            officer_headers,
        ),
        ApiErrorId.ERR_SCORECARD_PERIOD_OVERLAP,
        409,
    )

    incumbent = read_scorecard(world["incumbent"]["id"])
    assert _instant(incumbent["period_end"]) == _instant("2026-06-30T00:00:00Z"), (
        "the incumbent period is untouched by a refused creation, expected "
        f"2026-06-30T00:00:00Z, got {incumbent['period_end']}"
    )
    _, meta = validate_paginated(
        api.list_scorecards(officer_headers, params={"vendor_id": world["vendor"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the refused period must not have been created, got {meta['total_count']}"
    )


def test_scorecard_creation_accepted_once_the_period_clears_the_incumbent_by_a_day(
    api, officer_headers
):
    """PRD §3.7: "Periods of the same supplier may neither overlap nor touch, and
    must in fact clear each other by a full day. Both endpoints of a period are
    treated as occupied, and a mandatory clearance of one day is added on top, so
    a candidate period is refused with `ERR_SCORECARD_PERIOD_OVERLAP` when any
    existing scorecard of the same supplier in `OPEN`, `MEASURED` or `FINALIZED`
    satisfies both of these conditions at once: the candidate's `period_start` is
    at or before that scorecard's `period_end` plus one day, and that scorecard's
    `period_start` is at or before the candidate's `period_end` plus one day. Two
    periods whose endpoints are a single day apart therefore collide."
    PRD §3.7: "Three tolerance inputs are optional and default when omitted:
    `tolerance_early_days`, the number of days before the contractual deadline
    that still counts as on time, defaulting to 2 and constrained to 0 through 14;
    `tolerance_late_days`, the number of days after the deadline that still counts
    as on time, defaulting to 0 and likewise constrained to 0 through 14; and
    `fill_tolerance_pct`, the shortfall percentage tolerated before an order fails
    in full, defaulting to 2.00, constrained to 0.00 through 10.00 and carried to
    two decimals."
    PRD §3.7: "A new scorecard opens in `OPEN` with `measurement_variant` null,
    `measured_at` null, `finalized_at` null, `cap_required` false, and all
    measurement outputs — `measured_po_count`, `on_time_count`, `in_full_count`,
    `otif_count`, `on_time_pct`, `fill_rate_pct`, `otif_pct` and
    `composite_score` — at zero."

    Design: Difficulty/resource_temporal_overlap/scorecard_period_timeline_closed_interval_with_mandatory_clearance
    """
    world = _scorecard_timeline_world()
    validate_error(
        api.create_scorecard(
            scorecard_payload(
                world["vendor"]["id"],
                period_code="2026-07",
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-07-31T00:00:00Z",
            ),
            officer_headers,
        ),
        ApiErrorId.ERR_SCORECARD_PERIOD_OVERLAP,
        409,
    )

    created = validate_success(
        api.create_scorecard(
            scorecard_payload(
                world["vendor"]["id"],
                period_code="2026-07B",
                period_start="2026-07-02T00:00:00Z",
                period_end="2026-07-31T00:00:00Z",
            ),
            officer_headers,
        ),
        201,
    )
    assert _instant(created["period_start"]) == _instant("2026-07-02T00:00:00Z"), (
        f"expected period_start 2026-07-02T00:00:00Z, got {created['period_start']}"
    )
    assert _instant(created["period_end"]) == _instant("2026-07-31T00:00:00Z"), (
        f"expected period_end 2026-07-31T00:00:00Z, got {created['period_end']}"
    )
    assert created["status"] == "OPEN", (
        f"a new period opens in OPEN, got {created['status']}"
    )
    assert created["tolerance_early_days"] == 2, (
        f"expected tolerance_early_days 2, got {created['tolerance_early_days']}"
    )
    assert created["tolerance_late_days"] == 0, (
        f"expected tolerance_late_days 0, got {created['tolerance_late_days']}"
    )
    assert created["fill_tolerance_pct"] == 2.00, (
        f"expected fill_tolerance_pct 2.00, got {created['fill_tolerance_pct']}"
    )

    incumbent = read_scorecard(world["incumbent"]["id"])
    assert _instant(incumbent["period_end"]) == _instant("2026-06-30T00:00:00Z"), (
        f"expected the incumbent period_end 2026-06-30T00:00:00Z, got {incumbent['period_end']}"
    )
    _, meta = validate_paginated(
        api.list_scorecards(officer_headers, params={"vendor_id": world["vendor"]["id"]})
    )
    assert meta["total_count"] == 2, (
        f"expected two periods on the supplier's timeline, got {meta['total_count']}"
    )

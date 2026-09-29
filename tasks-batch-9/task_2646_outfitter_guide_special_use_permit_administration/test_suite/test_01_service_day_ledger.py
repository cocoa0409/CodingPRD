"""The service-day conservation ledger on a use area.

Covers area opening, the allocation summary recompute, the demand ratio and
posture constants, the screening fork at the availability boundary, and the
compensating release paths.
"""
from test_helpers import (
    assert_allocation_identity,
    assert_use_area,
    create_application,
    create_outfitter,
    create_published_assessment,
    create_screened_application,
    create_use_area,
    issue_permit,
    read_allocation_summary,
    read_application,
    read_needs_assessment_list,
    read_use_area,
    screen_application,
    set_clock,
    submit_application,
    validate_paginated,
    validate_success,
    api_client,
    TEST_USERS,
    make_outfitter_representative_headers,
)

ADMIN = TEST_USERS["program_administrator_headers"]
SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]

BETA = {"legal_name": "Beta Trails Co", "ein": "410000002",
        "contact_email": "ops@beta.example"}
CEDAR = {"legal_name": "Cedar Creek Guides", "ein": "420000003",
         "contact_email": "ops@cedar.example"}
LEGACY = {"legal_name": "Legacy Guides Inc", "ein": "410000009",
          "contact_email": "ops@legacy.example"}


def test_new_use_area_opens_with_nothing_committed_or_pending():
    """PRD §3.1: "A newly opened area is evaluated against an empty permit and
    application set, so it reports `committed_service_days` 0, `pending_service_days` 0,
    `available_service_days` equal to its allocatable total, `demand_ratio` 0.0 and
    `allocation_posture` `OPEN`."
    PRD §2.7: "An area's allocatable total is its `total_allocated_service_days` less
    its `reserved_admin_service_days`"

    Design: Corner/entities/use_area_creation_returns_computed_allocation_fields_and_version_one
    """
    set_clock()
    response = api_client.create_use_area(
        {
            "area_code": "BRW-01",
            "name": "Bear River Wilderness",
            "total_allocated_service_days": 1000,
            "reserved_admin_service_days": 100,
            "season_year": 2027,
            "season_open_date": "2027-05-15",
            "season_close_date": "2027-09-30",
            "party_size_max": 12,
            "max_clients_per_guide": 8,
            "min_liability_coverage_cents": 100_000_000,
        },
        ADMIN,
    )
    area = validate_success(response, expected_status=201)
    assert_use_area(area)
    assert area["allocatable_service_days"] == 900, (
        "allocatable is the total less the reserved administrative days"
    )
    assert area["committed_service_days"] == 0
    assert area["pending_service_days"] == 0
    assert area["available_service_days"] == 900
    assert area["demand_ratio"] == 0.0
    assert area["allocation_posture"] == "OPEN"
    assert area["version"] == 1, "a freshly created record's version starts at 1"


def test_use_area_listing_pages_newest_first_with_envelope_counters():
    """PRD §2.3: "`limit` controls page size: it defaults to 10, must be at least 1,
    and must not exceed 100."
    PRD §2.3: "Every paginated response reports its window in the `meta` object through
    `limit`, `offset`, `total_count` and `has_more`."
    PRD §2.3: "use areas are returned newest first, by `created_at` descending"

    Design: Corner/entities/use_area_listing_pages_newest_first_with_envelope_counters
    """
    set_clock()
    area_one = create_use_area()
    area_two = create_use_area(area_code="BRW-02", name="Cedar Basin",
                               total_allocated_service_days=200, season_year=2027)
    area_three = create_use_area(area_code="BRW-03", name="Granite Fork",
                                 total_allocated_service_days=500, season_year=2028)

    rows, meta = validate_paginated(
        api_client.list_use_areas(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert [row["id"] for row in rows] == [area_three["id"], area_two["id"]], (
        "the newest two areas come first"
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    rows, meta = validate_paginated(
        api_client.list_use_areas(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert [row["id"] for row in rows] == [area_one["id"]]
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_use_areas(ADMIN, params={"season_year": 2028})
    )
    assert [row["id"] for row in rows] == [area_three["id"]]
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(api_client.list_use_areas(ADMIN))
    assert len(rows) == 3
    assert meta["limit"] == 10, "the default page size is ten"
    assert meta["offset"] == 0


def _area_with_seven_hundred_committed():
    """An area of 900 allocatable days where an incumbent already holds an
    ISSUED permit for 700 days, leaving exactly 200 available."""
    set_clock()
    area = create_use_area()
    assessment = create_published_assessment(area["id"])
    incumbent = create_outfitter()
    application = create_screened_application(
        incumbent["id"], area["id"], requested_service_days=700,
        proposed_activity_type="HUNTING",
    )
    permit = issue_permit(application["id"])
    return area, assessment, incumbent, permit


def test_screening_a_request_for_exactly_the_remaining_days_routes_direct():
    """PRD §3.2: "The routing rule reads the area's `available_service_days` **before**
    this application's own hold is added, which means an application asking for exactly
    the remaining days routes directly."
    PRD §3.2: "For a `NEW` application the test is simply whether `requested_service_days`
    is less than or equal to that pre-hold remainder: if so, `routing_decision` is
    `DIRECT`; otherwise it is `PROSPECTUS`."
    PRD §3.2: "On the `DIRECT` fork the application moves `CAPACITY_SCREENED →
    DIRECT_AWARD_PENDING` and `hold_expires_at` is stamped at exactly 30 days past
    `screened_at` — a non-competitive hold, award-ready, with a deadline."

    Design: Difficulty/boundary_precision_check/screening_service_day_equality_boundary
    """
    area, assessment, _incumbent, _permit = _area_with_seven_hundred_committed()

    before = read_allocation_summary(area["id"])
    assert before["allocatable_service_days"] == 900
    assert before["committed_service_days"] == 700
    assert before["pending_service_days"] == 0
    assert before["available_service_days"] == 200
    assert before["demand_ratio"] == 0.7778
    assert before["allocation_posture"] == "OPEN"

    beta = create_outfitter(**BETA)
    challenger = create_application(
        beta["id"], area["id"], requested_service_days=200,
        proposed_activity_type="HUNTING",
    )
    submit_application(challenger["id"], beta["id"])
    screened = screen_application(challenger["id"])

    assert screened["routing_decision"] == "DIRECT", (
        "a request equal to the pre-hold remainder routes directly"
    )
    assert screened["status"] == "DIRECT_AWARD_PENDING"
    assert screened["hold_expires_at"] is not None
    assert screened["hold_expires_at"][:10] == "2027-02-04", (
        "the non-competitive hold expires thirty days past the screening instant"
    )

    after = read_allocation_summary(area["id"])
    assert after["pending_service_days"] == 200
    assert after["available_service_days"] == 0
    assert after["demand_ratio"] == 1.0
    assert after["allocation_posture"] == "EXHAUSTED", (
        "a remainder of exactly zero reports EXHAUSTED, and does not retroactively "
        "change the fork already taken"
    )

    rows, _meta = read_needs_assessment_list(area["id"], params={"assessment_year": 2027})
    governing = [row for row in rows if row["status"] == "PUBLISHED"][0]
    assert governing["allocated_service_days"] == 900
    assert governing["unallocated_service_days"] == 0
    assert governing["prospectus_required"] is True, (
        "a capacity exactly consumed already owes a solicitation, even though the "
        "application that consumed it routed directly"
    )


def test_screening_a_request_one_day_past_the_remainder_routes_to_solicitation():
    """PRD §3.2: "For a `NEW` application the test is simply whether `requested_service_days`
    is less than or equal to that pre-hold remainder: if so, `routing_decision` is
    `DIRECT`; otherwise it is `PROSPECTUS`."
    PRD §3.2: "On the `PROSPECTUS` fork the application moves `CAPACITY_SCREENED →
    PROSPECTUS_QUEUED`, `hold_expires_at` is left null, and the governing published
    assessment's `prospectus_required` is set to true, recording that a solicitation is
    now owed."
    PRD §2.7: "`available_service_days` may be exactly 0, and it may go **negative**."

    Design: Difficulty/boundary_precision_check/screening_service_day_equality_boundary
    """
    area, _assessment, _incumbent, _permit = _area_with_seven_hundred_committed()

    cedar = create_outfitter(**CEDAR)
    over_by_one = create_application(
        cedar["id"], area["id"], requested_service_days=201,
        proposed_activity_type="HUNTING",
    )
    submit_application(over_by_one["id"], cedar["id"])
    screened = screen_application(over_by_one["id"])

    assert screened["routing_decision"] == "PROSPECTUS", (
        "one day beyond the pre-hold remainder tips the fork to solicitation"
    )
    assert screened["status"] == "PROSPECTUS_QUEUED"
    assert screened["hold_expires_at"] is None, (
        "the competitive fork leaves the hold deadline null"
    )

    after = read_allocation_summary(area["id"])
    assert after["pending_service_days"] == 201, (
        "the screening hold is placed unconditionally"
    )
    assert after["available_service_days"] == -1
    assert after["demand_ratio"] == 1.0011
    assert after["allocation_posture"] == "EXHAUSTED"

    rows, _meta = read_needs_assessment_list(area["id"], params={"assessment_year": 2027})
    governing = [row for row in rows if row["status"] == "PUBLISHED"][0]
    assert governing["prospectus_required"] is True


def test_withdrawal_is_the_exact_compensating_action_for_the_screening_hold():
    """PRD §2.7: "The governing invariant is that the allocatable total always equals the
    committed sum plus the pending sum plus the available remainder, for every area at
    every observable instant."
    PRD §3.2: "Withdrawal is the exact compensating action for the screening hold: the
    area's allocatable total is unchanged and its remainder returns to precisely its
    pre-screen value."

    Design: Difficulty/compensating_invariant/service_day_conservation_across_hold_and_release
    """
    set_clock()
    area = create_use_area()
    create_published_assessment(area["id"])
    alpine = create_outfitter()

    opening = read_allocation_summary(area["id"])
    assert (opening["committed_service_days"], opening["pending_service_days"],
            opening["available_service_days"]) == (0, 0, 900)
    assert opening["demand_ratio"] == 0.0
    assert opening["allocation_posture"] == "OPEN"
    assert_allocation_identity(opening)

    incumbent = create_screened_application(
        alpine["id"], area["id"], requested_service_days=700,
        proposed_activity_type="HUNTING",
    )
    held = read_allocation_summary(area["id"])
    assert (held["committed_service_days"], held["pending_service_days"],
            held["available_service_days"]) == (0, 700, 200)
    assert held["demand_ratio"] == 0.7778
    assert held["allocation_posture"] == "OPEN"
    assert_allocation_identity(held)

    issue_permit(incumbent["id"])
    committed = read_allocation_summary(area["id"])
    assert (committed["committed_service_days"], committed["pending_service_days"],
            committed["available_service_days"]) == (700, 0, 200)
    assert committed["demand_ratio"] == 0.7778, (
        "issuance moves the same day count from pending to committed, so the ratio "
        "does not move"
    )
    assert committed["allocation_posture"] == "OPEN"
    assert_allocation_identity(committed)

    beta = create_outfitter(**BETA)
    beta_application = create_screened_application(
        beta["id"], area["id"], requested_service_days=150,
        proposed_activity_type="FISHING",
    )
    constrained = read_allocation_summary(area["id"])
    assert (constrained["committed_service_days"], constrained["pending_service_days"],
            constrained["available_service_days"]) == (700, 150, 50)
    assert constrained["demand_ratio"] == 0.9444
    assert constrained["allocation_posture"] == "CONSTRAINED"
    assert_allocation_identity(constrained)

    rows, _meta = read_needs_assessment_list(area["id"], params={"assessment_year": 2027})
    governing = [row for row in rows if row["status"] == "PUBLISHED"][0]
    assert governing["allocated_service_days"] == 850

    validate_success(
        api_client.withdraw_permit_application(
            beta_application["id"], make_outfitter_representative_headers(beta["id"])
        )
    )
    released = read_allocation_summary(area["id"])
    assert (released["committed_service_days"], released["pending_service_days"],
            released["available_service_days"]) == (700, 0, 200), (
        "the remainder returns to precisely its pre-screen value"
    )
    assert released["demand_ratio"] == 0.7778
    assert released["allocation_posture"] == "OPEN"
    assert_allocation_identity(released)

    rows, _meta = read_needs_assessment_list(area["id"], params={"assessment_year": 2027})
    governing = [row for row in rows if row["status"] == "PUBLISHED"][0]
    assert governing["allocated_service_days"] == 700


def test_denial_releases_the_hold_and_restores_the_ledger():
    """PRD §3.2: "An `AuthorizedOfficer` or `ProgramAdministrator` may deny an application
    from `SUBMITTED`, `CAPACITY_SCREENED`, `DIRECT_AWARD_PENDING`, `PROSPECTUS_QUEUED` or
    `PROSPECTUS_RESPONDED`, supplying a `denial_reason_code`; the application moves to
    `DENIED`, and if it had already been screened its `requested_service_days` come off
    the area's `pending_service_days` with the remainder, ratio and posture recomputed."
    PRD §2.7: "The governing invariant is that the allocatable total always equals the
    committed sum plus the pending sum plus the available remainder, for every area at
    every observable instant."

    Design: Difficulty/compensating_invariant/service_day_conservation_across_hold_and_release
    """
    set_clock()
    area = create_use_area()
    create_published_assessment(area["id"])
    alpine = create_outfitter()
    incumbent = create_screened_application(
        alpine["id"], area["id"], requested_service_days=700,
        proposed_activity_type="HUNTING",
    )
    issue_permit(incumbent["id"])

    cedar = create_outfitter(**CEDAR)
    cedar_application = create_screened_application(
        cedar["id"], area["id"], requested_service_days=50,
        proposed_activity_type="PACK_STOCK",
    )
    holding = read_allocation_summary(area["id"])
    assert (holding["committed_service_days"], holding["pending_service_days"],
            holding["available_service_days"]) == (700, 50, 150)
    assert holding["demand_ratio"] == 0.8333
    assert holding["allocation_posture"] == "CONSTRAINED"

    denied = validate_success(
        api_client.deny_permit_application(
            cedar_application["id"],
            {"denial_reason_code": "CAPACITY_RESERVED_FOR_PROSPECTUS"},
            OFFICER,
        )
    )
    assert denied["status"] == "DENIED"

    restored = read_allocation_summary(area["id"])
    assert (restored["committed_service_days"], restored["pending_service_days"],
            restored["available_service_days"]) == (700, 0, 200)
    assert restored["demand_ratio"] == 0.7778
    assert restored["allocation_posture"] == "OPEN"
    assert_allocation_identity(restored)

    stored = read_use_area(area["id"])
    assert stored["committed_service_days"] == restored["committed_service_days"]
    assert stored["pending_service_days"] == restored["pending_service_days"]
    assert stored["available_service_days"] == restored["available_service_days"]


def test_allocation_summary_recomputes_from_scratch_over_a_mixed_pool():
    """PRD §2.7: "`committed_service_days` is the sum of `authorized_service_days` over
    every `Permit` in the area whose `administrative_status` is `ISSUED`, `ACTIVE` or
    `SUSPENDED`; a `REVOKED`, `EXPIRED` or `CLOSED` permit releases its days."
    PRD §2.7: "`pending_service_days` is the sum of `requested_service_days` over every
    `PermitApplication` in the area whose `status` is one of the five holding statuses
    `CAPACITY_SCREENED`, `DIRECT_AWARD_PENDING`, `PROSPECTUS_QUEUED`,
    `PROSPECTUS_RESPONDED` or `AWARDED`; an application in `DRAFT` or `SUBMITTED` holds
    nothing, and one that reaches `PERMIT_ISSUED`, `DENIED` or `WITHDRAWN` releases what
    it held."
    PRD §2.7: "`demand_ratio` is the committed sum plus the pending sum, divided by the
    allocatable total, rounded half up to four decimal places."

    Design: Corner/calculations/availability_full_recompute_matches_the_pinned_aggregate_over_a_mixed_pool
    """
    set_clock()
    area = create_use_area()
    create_published_assessment(area["id"])
    alpine = create_outfitter()
    holder_headers = make_outfitter_representative_headers(alpine["id"])

    issued = create_screened_application(
        alpine["id"], area["id"], requested_service_days=200,
        proposed_activity_type="RIVER_FLOAT",
    )
    issue_permit(issued["id"])

    create_screened_application(
        alpine["id"], area["id"], requested_service_days=150,
        proposed_activity_type="FISHING",
    )

    submitted_only = create_application(
        alpine["id"], area["id"], requested_service_days=100,
        proposed_activity_type="HUNTING",
    )
    submit_application(submitted_only["id"], alpine["id"])

    withdrawn = create_screened_application(
        alpine["id"], area["id"], requested_service_days=50,
        proposed_activity_type="PACK_STOCK",
    )
    validate_success(
        api_client.withdraw_permit_application(withdrawn["id"], holder_headers)
    )

    summary = read_allocation_summary(area["id"])
    assert summary["allocatable_service_days"] == 900
    assert summary["committed_service_days"] == 200, (
        "only the issued permit's authorized days are committed"
    )
    assert summary["pending_service_days"] == 150, (
        "the submitted-only and withdrawn applications hold nothing"
    )
    assert summary["available_service_days"] == 550
    assert summary["demand_ratio"] == 0.3889
    assert summary["allocation_posture"] == "OPEN"
    assert_allocation_identity(summary)

    stored = read_use_area(area["id"])
    for field in ("allocatable_service_days", "committed_service_days",
                  "pending_service_days", "available_service_days"):
        assert stored[field] == summary[field], (
            f"the stored {field} must not drift from the from-scratch recompute"
        )

    rows, _meta = read_needs_assessment_list(area["id"], params={"assessment_year": 2027})
    governing = [row for row in rows if row["status"] == "PUBLISHED"][0]
    assert governing["allocated_service_days"] == 350
    assert governing["unallocated_service_days"] == 550
    assert governing["prospectus_required"] is False


def test_allocation_posture_flips_at_the_demand_ratio_constant():
    """PRD §2.7: "From the remainder and the ratio the system publishes
    `allocation_posture`: `EXHAUSTED` when `available_service_days` is at or below zero;
    otherwise `CONSTRAINED` when the remainder is above zero and `demand_ratio` has
    reached 0.8; otherwise `OPEN`."

    Design: Corner/calculations/allocation_posture_flips_at_the_pinned_demand_ratio_constant
    """
    set_clock()
    area = create_use_area(
        area_code="PIN-04", name="Pine Narrows", total_allocated_service_days=32,
        reserved_admin_service_days=0, party_size_max=4, max_clients_per_guide=4,
    )
    create_published_assessment(area["id"], determined_capacity_service_days=32)
    alpine = create_outfitter()

    create_screened_application(
        alpine["id"], area["id"], requested_service_days=25,
        proposed_activity_type="FISHING",
    )
    below = read_allocation_summary(area["id"])
    assert (below["pending_service_days"], below["available_service_days"]) == (25, 7)
    assert below["demand_ratio"] == 0.7813
    assert below["allocation_posture"] == "OPEN", "0.7813 has not reached 0.8"

    create_screened_application(
        alpine["id"], area["id"], requested_service_days=1,
        proposed_activity_type="FISHING",
    )
    at_or_above = read_allocation_summary(area["id"])
    assert (at_or_above["pending_service_days"],
            at_or_above["available_service_days"]) == (26, 6)
    assert at_or_above["demand_ratio"] == 0.8125
    assert at_or_above["allocation_posture"] == "CONSTRAINED"

    create_screened_application(
        alpine["id"], area["id"], requested_service_days=6,
        proposed_activity_type="FISHING",
    )
    exhausted = read_allocation_summary(area["id"])
    assert (exhausted["pending_service_days"],
            exhausted["available_service_days"]) == (32, 0)
    assert exhausted["demand_ratio"] == 1.0
    assert exhausted["allocation_posture"] == "EXHAUSTED", (
        "the at-or-below-zero remainder is evaluated first"
    )
    assert exhausted["committed_service_days"] == 0

    rows, _meta = read_needs_assessment_list(area["id"], params={"assessment_year": 2027})
    governing = [row for row in rows if row["status"] == "PUBLISHED"][0]
    assert governing["allocated_service_days"] == 32
    assert governing["unallocated_service_days"] == 0
    assert governing["prospectus_required"] is True


def test_demand_ratio_rounds_half_up_at_the_fourth_decimal():
    """PRD §2.7: "`demand_ratio` is the committed sum plus the pending sum, divided by the
    allocatable total, rounded half up to four decimal places."
    PRD §2.7: "an issuance moves the same day count from pending to committed"

    Design: Corner/calculations/demand_ratio_rounds_half_up_at_the_fourth_decimal
    """
    set_clock()
    area = create_use_area(
        area_code="TIN-03", name="Tin Cup Basin", total_allocated_service_days=32,
        reserved_admin_service_days=0, party_size_max=4, max_clients_per_guide=4,
    )
    create_published_assessment(area["id"], determined_capacity_service_days=32)
    alpine = create_outfitter()

    single_day = create_screened_application(
        alpine["id"], area["id"], requested_service_days=1,
        proposed_activity_type="FISHING",
    )
    held = read_allocation_summary(area["id"])
    assert held["demand_ratio"] == 0.0313, (
        "one day of thirty-two is 0.03125, which rounds half up to 0.0313"
    )
    assert held["allocatable_service_days"] == 32
    assert held["pending_service_days"] == 1
    assert held["available_service_days"] == 31

    issue_permit(single_day["id"])
    transferred = read_allocation_summary(area["id"])
    assert transferred["demand_ratio"] == 0.0313, (
        "the numerator is committed plus pending, so a transfer between the two "
        "cannot move the ratio"
    )
    assert transferred["committed_service_days"] == 1
    assert transferred["pending_service_days"] == 0

    create_screened_application(
        alpine["id"], area["id"], requested_service_days=3,
        proposed_activity_type="FISHING",
    )
    final = read_allocation_summary(area["id"])
    assert final["committed_service_days"] == 1
    assert final["pending_service_days"] == 3
    assert final["available_service_days"] == 28
    assert final["demand_ratio"] == 0.125


def _oversubscription_stage():
    """900 allocatable days: an incumbent holds 700, a sibling holds a
    non-competitive 120-day hold, and a 300-day request waits unscreened."""
    set_clock()
    area = create_use_area()
    assessment = create_published_assessment(area["id"])

    legacy = create_outfitter(**LEGACY)
    incumbent = create_screened_application(
        legacy["id"], area["id"], requested_service_days=700,
        proposed_activity_type="HUNTING",
    )
    incumbent_permit = issue_permit(
        incumbent["id"], term_start_date="2027-01-01", term_end_date="2031-12-31"
    )

    alpine = create_outfitter()
    sibling = create_screened_application(
        alpine["id"], area["id"], requested_service_days=120,
        proposed_activity_type="RIVER_FLOAT",
    )
    assert sibling["routing_decision"] == "DIRECT"

    midpoint = read_allocation_summary(area["id"])
    assert midpoint["available_service_days"] == 80
    assert midpoint["demand_ratio"] == 0.9111
    assert midpoint["allocation_posture"] == "CONSTRAINED"

    cedar = create_outfitter(**CEDAR)
    challenger = create_application(
        cedar["id"], area["id"], requested_service_days=300,
        proposed_activity_type="FISHING",
    )
    submit_application(challenger["id"], cedar["id"])
    return {
        "use_area": area,
        "needs_assessment": assessment,
        "incumbent_permit": incumbent_permit,
        "sibling": sibling,
        "challenger": challenger,
    }


def test_oversubscribing_screen_reroutes_the_untouched_sibling_hold():
    """PRD §3.2: "Because the hold is placed unconditionally, the recomputation can leave
    the area's `available_service_days` **below zero** — the area is now oversubscribed,
    its applications on hand claiming more days than it can allocate."
    PRD §3.2: "When that happens, every *other* application on that area sitting in
    `DIRECT_AWARD_PENDING` — never the application being screened in this request — loses
    its non-competitive standing: it moves `DIRECT_AWARD_PENDING → PROSPECTUS_QUEUED`, its
    `hold_expires_at` is cleared to null, its `routing_decision` is rewritten to
    `PROSPECTUS`, and the governing assessment's `prospectus_required` is recomputed as
    the fourth link of the chain."

    Design: Difficulty/transitive_cascade/screen_oversubscription_reroutes_sibling_depth_four
    """
    stage = _oversubscription_stage()

    screened = screen_application(stage["challenger"]["id"])
    assert screened["routing_decision"] == "PROSPECTUS"
    assert screened["status"] == "PROSPECTUS_QUEUED"

    rerouted = read_application(stage["sibling"]["id"])
    assert rerouted["status"] == "PROSPECTUS_QUEUED", (
        "the sibling was never named in the request, yet lost its non-competitive standing"
    )
    assert rerouted["routing_decision"] == "PROSPECTUS"
    assert rerouted["hold_expires_at"] is None

    replayed = read_application(stage["challenger"]["id"])
    assert replayed["status"] == "PROSPECTUS_QUEUED", (
        "the application being screened is excluded from the reroute sweep and is not "
        "processed twice"
    )
    assert replayed["routing_decision"] == "PROSPECTUS"


def test_oversubscribing_screen_drives_the_ledger_negative_and_recomputes_the_assessment():
    """PRD §2.7: "`available_service_days` may be exactly 0, and it may go **negative**.
    Screening places its service-day hold unconditionally, so successive screenings can
    oversubscribe an area, and a negative remainder is precisely the signal that fires the
    re-routing cascade described in §3.2."
    PRD §3.1: "From those the system computes `unallocated_service_days` as the determined
    capacity less the allocated days, never reported below zero, and sets
    `prospectus_required` to true when the finding is `NO_NEED` **or** when
    `unallocated_service_days` is at or below zero."

    Design: Difficulty/transitive_cascade/screen_oversubscription_reroutes_sibling_depth_four
    """
    stage = _oversubscription_stage()
    area_id = stage["use_area"]["id"]

    screen_application(stage["challenger"]["id"])

    summary = read_allocation_summary(area_id)
    assert summary["committed_service_days"] == 700
    assert summary["pending_service_days"] == 420
    assert summary["available_service_days"] == -220
    assert summary["demand_ratio"] == 1.2444
    assert summary["allocation_posture"] == "EXHAUSTED"
    assert_allocation_identity(summary)

    rows, _meta = read_needs_assessment_list(area_id, params={"assessment_year": 2027})
    governing = [row for row in rows if row["status"] == "PUBLISHED"][0]
    assert governing["allocated_service_days"] == 1120
    assert governing["unallocated_service_days"] == 0, (
        "the unallocated figure is never reported below zero"
    )
    assert governing["prospectus_required"] is True

    untouched = validate_success(
        api_client.get_permit(stage["incumbent_permit"]["id"], SPECIALIST)
    )
    assert untouched["administrative_status"] == "ISSUED", (
        "the cascade moved pending days only"
    )
    assert untouched["authorized_service_days"] == 700

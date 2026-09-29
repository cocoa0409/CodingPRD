"""Committing equipment: the selector, the manual attach, the peak lease reserve,
the pinned rate card and the half-open occupancy window."""


from test_helpers import (
    ApiErrorId,
    api_client,
    TEST_USERS,
    add_trailer,
    create_trailer,
    lease_rate_card_payload,
    list_units,
    open_agreement,
    rate_card_payload,
    read_agreement,
    read_agreement_unit,
    read_branch,
    read_trailer,
    setup_agreement_pending_allocation,
    setup_agreement_reserved,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def test_allocating_a_draft_contract_reports_the_state_error_not_the_version_error(api):
    """PRD §2.9: "Optimistic concurrency on the parent's `version`, or
    `ERR_STALE_VERSION`. This guards exactly the four write operations named in
    section 2.7: manual unit attach, allocation, rate-card publication and
    damage-assessment creation."
    PRD §3.5: "There are two ways to commit equipment, and both are available to a
    `FleetAdmin` or to the originating yard's `BranchManager`, and both demand that
    the contract be in `PENDING_ALLOCATION` — any other status is rejected with
    `ERR_AGREEMENT_NOT_PENDING_ALLOCATION`."

    Design: Corner/errors/allocate_on_draft_agreement_reports_not_pending_allocation
    """
    ctx = setup_reference_data()
    agreement = open_agreement(ctx)
    assert agreement["version"] == 1

    response = api.allocate_agreement(
        agreement["id"], {"expected_agreement_version": agreement["version"]}, ADMIN
    )
    error = validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_PENDING_ALLOCATION.value)
    assert error["error_id"] != ApiErrorId.ERR_STALE_VERSION.value, (
        "a correct version passes the concurrency gate, so the state gate answers"
    )
    assert read_trailer(ctx["trailer_id"])["availability_status"] == "AVAILABLE"


def test_a_pool_smaller_than_the_demand_reports_insufficient_availability(api):
    """PRD §3.5: "The selector then either fills or refuses. An empty pool is
    rejected with `ERR_NO_ELIGIBLE_TRAILER`. A pool that is non-empty but smaller
    than the remaining demand is rejected with `ERR_INSUFFICIENT_AVAILABILITY`."

    Design: Corner/errors/allocate_with_only_one_eligible_trailer_for_two_units_reports_insufficient_availability
    """
    scn = setup_agreement_pending_allocation(unit_count=2)

    response = api.allocate_agreement(
        scn["agreement_id"],
        {"expected_agreement_version": scn["agreement_version"]},
        ADMIN,
    )
    error = validate_error(response, ApiErrorId.ERR_INSUFFICIENT_AVAILABILITY.value)
    assert error["error_id"] != ApiErrorId.ERR_NO_ELIGIBLE_TRAILER.value

    stored = read_agreement(scn["agreement_id"])
    assert stored["allocated_unit_count"] == 0
    assert read_trailer(scn["trailer_id"])["availability_status"] == "AVAILABLE"
    assert list_units(agreement_id=scn["agreement_id"]) == []


def test_reservation_without_an_active_card_for_the_triple_is_refused(api):
    """PRD §3.5: "Allocation also requires an `ACTIVE` rate card for the contract's
    yard, equipment class and product line, failing with `ERR_RATE_CARD_NOT_FOUND`
    when there is none."
    PRD §3.3: "A `FleetAdmin` publishes a rate card that governs exactly one
    combination of yard, equipment class and product line: the card names its
    `branch_id`, its `trailer_type_id`, and a `product` that is either
    `SHORT_TERM_RENTAL` or `FULL_SERVICE_LEASE`."

    Design: Corner/errors/allocate_without_active_rate_card_returns_rate_card_not_found
    """
    scn = setup_agreement_pending_allocation(
        product="FULL_SERVICE_LEASE", term_months=24,
        start_date="2026-08-20", end_date="2026-09-10",
    )

    response = api.allocate_agreement(
        scn["agreement_id"],
        {"expected_agreement_version": scn["agreement_version"]},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_RATE_CARD_NOT_FOUND.value)

    stored = read_agreement(scn["agreement_id"])
    assert stored["status"] == "PENDING_ALLOCATION"
    assert stored["allocated_unit_count"] == 0
    assert read_trailer(scn["trailer_id"])["availability_status"] == "AVAILABLE"


def test_selector_takes_the_least_utilised_unit_first(api):
    """PRD §3.5: "The eligible units are then ranked deterministically, with no
    random input whatsoever: ascending `hub_miles` first, so the least-utilised
    unit goes out first; then descending `dot_expires_on`, so the unit with the
    most inspection runway ahead of it is preferred; and finally ascending
    `created_at` as the tie-break."

    Design: Corner/calculations/selector_ranks_candidates_by_hub_miles_ascending
    """
    ctx = setup_reference_data()
    low = add_trailer(ctx, "low", unit_number="T-LOW", hub_miles=12000)
    high = add_trailer(ctx, "high", unit_number="T-HIGH", hub_miles=55000)

    scn = setup_agreement_pending_allocation(ctx=ctx)
    agreement = validate_success(
        api.allocate_agreement(
            scn["agreement_id"],
            {"expected_agreement_version": scn["agreement_version"]},
            ADMIN,
        )
    )
    assert agreement["status"] == "RESERVED"

    units = list_units(agreement_id=scn["agreement_id"])
    assert len(units) == 1
    assert units[0]["trailer_id"] == low["id"], "12000 hub miles ranks ahead of 41000 and 55000"
    assert units[0]["trailer_id"] != ctx["trailer_id"]
    assert units[0]["trailer_id"] != high["id"]

    assert read_trailer(low["id"])["availability_status"] == "ALLOCATED"
    assert read_trailer(ctx["trailer_id"])["availability_status"] == "AVAILABLE"
    assert read_trailer(high["id"])["availability_status"] == "AVAILABLE"


def test_selector_breaks_a_full_tie_on_created_at_not_on_the_record_id(api):
    """PRD §3.5: "The eligible units are then ranked deterministically, with no
    random input whatsoever: ascending `hub_miles` first, so the least-utilised
    unit goes out first; then descending `dot_expires_on`, so the unit with the
    most inspection runway ahead of it is preferred; and finally ascending
    `created_at` as the tie-break. The record `id` is never used as a tie-break."

    Design: Corner/calculations/selector_tie_break_uses_created_at_ascending_not_id
    """
    ctx = setup_reference_data()
    first = add_trailer(ctx, "tie_a", unit_number="T-TIE-A", hub_miles=12000)
    second = add_trailer(ctx, "tie_b", unit_number="T-TIE-B", hub_miles=12000)
    assert first["created_at"] <= second["created_at"]
    assert first["dot_expires_on"] == second["dot_expires_on"]

    scn = setup_agreement_pending_allocation(ctx=ctx)
    validate_success(
        api.allocate_agreement(
            scn["agreement_id"],
            {"expected_agreement_version": scn["agreement_version"]},
            ADMIN,
        )
    )
    units = list_units(agreement_id=scn["agreement_id"])
    assert units[0]["trailer_id"] == first["id"], "the earlier-created unit wins the tie"
    assert units[0]["trailer_id"] != second["id"]
    assert read_trailer(second["id"])["availability_status"] == "AVAILABLE"


def test_manual_attach_refuses_a_unit_whose_inspection_expires_on_the_end_date(api):
    """PRD §3.5: "Its `dot_expires_on` must fall strictly after the contract's
    `end_date`, so that the federal inspection outlasts the contract; an expiry on
    or before that date is rejected with `ERR_DOT_INSPECTION_EXPIRED`."

    Design: Corner/validations/dot_expiring_exactly_on_agreement_end_date_rejected_at_manual_attach
    """
    ctx = setup_reference_data()
    edge = create_trailer(ctx["trailer_type_id"], ctx["branch_id"],
                          unit_number="T-DOT", last_dot_inspection_date="2025-09-10",
                          hub_miles=5000)
    assert edge["dot_expires_on"] == "2026-09-10"
    assert edge["service_status"] == "SERVICEABLE"

    scn = setup_agreement_pending_allocation(ctx=ctx)
    response = api.attach_agreement_unit(
        scn["agreement_id"],
        {"trailer_id": edge["id"],
         "expected_agreement_version": scn["agreement_version"]},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DOT_INSPECTION_EXPIRED.value)

    assert read_agreement(scn["agreement_id"])["allocated_unit_count"] == 0
    assert read_trailer(edge["id"])["availability_status"] == "AVAILABLE"


def test_contract_unit_lines_can_be_listed_by_the_unit_they_stand_on(api):
    """PRD §3.6: "Contract unit lines may be read individually or listed with
    optional `agreement_id`, `trailer_id`, `return_branch_id` and `status`
    filters."
    PRD §3.5: "A line records the `agreement_id` of the owning contract and the
    `trailer_id` of the unit committed to it, and it copies `planned_start_date`
    and `planned_end_date` from the contract's own `start_date` and `end_date` at
    the moment it is attached — these two dates form the half-open occupancy
    interval the trailer is booked over."

    Design: Corner/endpoints/list_agreement_units_filtered_by_trailer_id
    """
    ctx = setup_reference_data()
    second = add_trailer(ctx, "second", unit_number="T-1002", hub_miles=52000)
    scn = setup_agreement_reserved(ctx=ctx, unit_count=2)

    rows, _ = validate_paginated(
        api.list_agreement_units(ADMIN, params={"trailer_id": second["id"]})
    )
    assert len(rows) == 1
    line = rows[0]
    assert line["trailer_id"] == second["id"]
    assert line["status"] == "ALLOCATED"
    assert line["agreement_id"] == scn["agreement_id"]
    assert line["planned_start_date"] == "2026-08-20"
    assert line["planned_end_date"] == "2026-09-10"


def test_manual_attach_with_a_stale_contract_version_is_rejected(api):
    """PRD §2.7: "Manually attaching a trailer to an agreement requires
    `expected_agreement_version` in the request body, carrying the client's last
    observed `version` of the target `Agreement`."
    PRD §2.7: "Each of these four requests carries a non-optional version field
    naming the parent it targets; if the supplied value does not equal that
    parent's current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412) and nothing is written."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_agreement_version_on_unit_attach_conflicts
    """
    scn = setup_agreement_pending_allocation()
    assert scn["agreement_version"] == 3, (
        "creation, submission and insurance verification each advance the version"
    )

    stale = api.attach_agreement_unit(
        scn["agreement_id"],
        {"trailer_id": scn["trailer_id"],
         "expected_agreement_version": scn["agreement_version"] - 1},
        ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)
    assert list_units(agreement_id=scn["agreement_id"]) == []

    unit = validate_success(
        api.attach_agreement_unit(
            scn["agreement_id"],
            {"trailer_id": scn["trailer_id"],
             "expected_agreement_version": scn["agreement_version"]},
            ADMIN,
        ),
        201,
    )
    assert unit["status"] == "ALLOCATED"

    stored = read_agreement(scn["agreement_id"])
    assert stored["status"] == "RESERVED"
    assert stored["version"] == 4
    assert len(list_units(agreement_id=scn["agreement_id"])) == 1


def test_publishing_a_card_with_a_stale_yard_version_is_rejected(api):
    """PRD §3.3: "Because publication overwrites what the lessor is currently
    charging, publication is one of the four version-guarded writes: the request
    must carry `expected_branch_version` matching the target yard's current
    `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.3: "A successful publication increments the yard's `version` by exactly
    1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_branch_version_on_rate_card_publish_conflicts
    """
    ctx = setup_reference_data()
    assert ctx["branch"]["version"] == 1

    stale = api.create_rate_card(
        lease_rate_card_payload(ctx["branch_id"], ctx["trailer_type_id"], 1,
                                effective_date="2026-07-01"),
        ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

    current = read_branch(ctx["branch_id"])["version"]
    assert current == 2, "publishing the short-term card already advanced the yard"

    card = validate_success(
        api.create_rate_card(
            lease_rate_card_payload(ctx["branch_id"], ctx["trailer_type_id"], current,
                                    effective_date="2026-07-01"),
            ADMIN,
        ),
        201,
    )
    assert card["status"] == "ACTIVE"
    assert card["product"] == "FULL_SERVICE_LEASE"
    assert read_branch(ctx["branch_id"])["version"] == 3


def test_publishing_a_second_card_supersedes_the_incumbent(api):
    """PRD §3.3: "Publishing a card for a yard, equipment class and product line
    that already has an `ACTIVE` card moves that prior card from `ACTIVE` to
    `SUPERSEDED`, so at most one card is ever `ACTIVE` for a given combination."

    Design: Corner/cross_cutting_complexity_layers/publishing_a_second_rate_card_supersedes_the_prior_active_card
    """
    ctx = setup_reference_data()
    incumbent = ctx["rate_card"]
    assert incumbent["daily_rate_cents"] == 5200

    version = read_branch(ctx["branch_id"])["version"]
    replacement = validate_success(
        api.create_rate_card(
            rate_card_payload(ctx["branch_id"], ctx["trailer_type_id"], version,
                              daily_rate_cents=6100, monthly_rate_cents=128000,
                              peak_uplift_pct=0.35,
                              excess_mileage_rate_cents_per_mile=24,
                              effective_date="2026-08-15"),
            ADMIN,
        ),
        201,
    )
    assert replacement["status"] == "ACTIVE"
    assert validate_success(
        api.get_rate_card(incumbent["id"], ADMIN)
    )["status"] == "SUPERSEDED"

    rows, _ = validate_paginated(
        api.list_rate_cards(ADMIN, params={
            "branch_id": ctx["branch_id"],
            "trailer_type_id": ctx["trailer_type_id"],
            "product": "SHORT_TERM_RENTAL",
            "status": "ACTIVE",
        })
    )
    assert len(rows) == 1
    assert rows[0]["id"] == replacement["id"]
    assert read_branch(ctx["branch_id"])["version"] == 3


def test_cancelling_a_reserved_contract_releases_its_units(api):
    """PRD §3.4: "Cancelling from `PENDING_ALLOCATION` or from `RESERVED` releases
    the equipment: every contract unit line still in status `ALLOCATED` moves
    `ALLOCATED → RELEASED`, and each released line's trailer returns `ALLOCATED →
    AVAILABLE` — but only when no other contract unit line on that same trailer
    remains in status `ALLOCATED` or `OUT`; if another live booking still stands on
    the unit, the availability dimension is left where it is."

    Design: Corner/state_machines/agreement_cancel_cascades_release_to_units_and_frees_trailers
    """
    scn = setup_agreement_reserved()
    unit_id = list_units(agreement_id=scn["agreement_id"])[0]["id"]
    assert read_branch(scn["branch_id"])["serviceable_available_count"] == 0

    agreement = validate_success(
        api.cancel_agreement(
            scn["agreement_id"],
            {"reason": "shipper cancelled the season programme"},
            ADMIN,
        )
    )
    assert agreement["status"] == "CANCELLED"
    assert agreement["cancel_reason"] == "shipper cancelled the season programme"

    assert read_agreement_unit(unit_id)["status"] == "RELEASED"
    assert read_trailer(scn["trailer_id"])["availability_status"] == "AVAILABLE"

    branch = read_branch(scn["branch_id"])
    assert branch["serviceable_available_count"] == 1
    assert branch["on_hand_count"] == 1


def _peak_reserve_scenario():
    """One serviceable unit at a yard that holds a quarter of its idle pool back
    for lease demand, and a rental contract wholly inside the peak window."""
    ctx = setup_reference_data(
        branch={"code": "PKW-01", "name": "Peak West Yard", "region": "CENTRAL",
                "yard_capacity": 20, "lease_reserve_pct": 0.25},
        trailer={"unit_number": "T-5001", "hub_miles": 15000},
        customer={"legal_name": "Harvest Lines Inc", "dot_number": "DOT-555",
                  "credit_tier": "A"},
        certificate={"policy_number": "P-5"},
    )
    return setup_agreement_pending_allocation(
        ctx=ctx, start_date="2026-09-05", end_date="2026-09-12"
    )


def test_peak_reserve_of_one_unit_empties_the_candidate_pool(api):
    """PRD §3.5: "In that case the server multiplies the length of the ranked list
    by the yard's `lease_reserve_pct` and rounds the product upward to a whole
    number of units — so any non-zero reserve percentage holds back at least one
    unit — and then removes that many units *from the top of the ranking*, leaving
    the remainder as the candidate pool."
    PRD §3.5: "The selector then either fills or refuses. An empty pool is rejected
    with `ERR_NO_ELIGIBLE_TRAILER`."

    Design: Difficulty/boundary_precision_check/peak_reserve_empties_candidate_pool_at_one_unit_and_fills_at_two
    """
    scn = _peak_reserve_scenario()

    availability = validate_success(
        api.get_branch_availability(
            scn["branch_id"], ADMIN,
            params={"trailer_type_id": scn["trailer_type_id"],
                    "product": "SHORT_TERM_RENTAL",
                    "window_start_date": "2026-09-05",
                    "window_end_date": "2026-09-12"},
        )
    )
    assert availability["serviceable_available_count"] == 1
    assert availability["lease_reserved_count"] == 1, "ceil(1 * 0.25) holds back one unit"
    assert availability["rental_available_count"] == 0

    response = api.allocate_agreement(
        scn["agreement_id"],
        {"expected_agreement_version": scn["agreement_version"]},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_TRAILER.value)
    assert read_agreement(scn["agreement_id"])["status"] == "PENDING_ALLOCATION"


def test_peak_reserve_holds_back_the_top_ranked_unit_and_fills_from_the_rest(api):
    """PRD §3.5: "Holding back the top-ranked units, not the bottom-ranked ones, is
    deliberate: the best equipment is saved for full-service lease demand during
    the season."
    PRD §3.5: "A per-unit charge is then formed by multiplying the pinned card's
    `daily_rate_cents` by the off-peak day count, multiplying the peak daily rate
    by the peak day count, adding the two, and rounding that sum half-up to whole
    cents."

    Design: Difficulty/boundary_precision_check/peak_reserve_empties_candidate_pool_at_one_unit_and_fills_at_two
    """
    scn = _peak_reserve_scenario()
    low = scn["trailer"]
    validate_error(
        api.allocate_agreement(
            scn["agreement_id"],
            {"expected_agreement_version": scn["agreement_version"]},
            ADMIN,
        ),
        ApiErrorId.ERR_NO_ELIGIBLE_TRAILER.value,
    )

    high = create_trailer(scn["trailer_type_id"], scn["branch_id"],
                          unit_number="T-5002", hub_miles=25000)

    agreement = validate_success(
        api.allocate_agreement(
            scn["agreement_id"],
            {"expected_agreement_version": scn["agreement_version"]},
            ADMIN,
        )
    )
    assert agreement["status"] == "RESERVED"
    assert agreement["quoted_total_cents"] == 47320, (
        "seven peak days at a peak daily rate of 6760 cents"
    )

    units = list_units(agreement_id=scn["agreement_id"])
    assert units[0]["trailer_id"] == high["id"], (
        "the reserve holds back the top-ranked 15000-mile unit"
    )
    assert units[0]["trailer_id"] != low["id"]
    assert read_trailer(low["id"])["availability_status"] == "AVAILABLE"
    assert read_trailer(high["id"])["availability_status"] == "ALLOCATED"


def _overlapping_bookings_scenario():
    """One unit already booked 2026-09-01 through 2026-09-15, plus two contracts
    waiting for equipment: one that genuinely overlaps and one that merely abuts."""
    ctx = setup_reference_data()
    incumbent = setup_agreement_pending_allocation(
        ctx=ctx, start_date="2026-09-01", end_date="2026-09-15"
    )
    validate_success(
        api_client.attach_agreement_unit(
            incumbent["agreement_id"],
            {"trailer_id": ctx["trailer_id"],
             "expected_agreement_version": incumbent["agreement_version"]},
            ADMIN,
        ),
        201,
    )
    overlapping = setup_agreement_pending_allocation(
        ctx=ctx, start_date="2026-09-10", end_date="2026-09-20"
    )
    abutting = setup_agreement_pending_allocation(
        ctx=ctx, start_date="2026-09-15", end_date="2026-09-25"
    )
    return ctx, incumbent, overlapping, abutting


def test_a_genuinely_overlapping_booking_is_refused(api):
    """PRD §3.5: "No existing contract unit line on that same trailer whose status
    is `ALLOCATED` or `OUT` may have an occupancy interval that overlaps the
    contract's own window; an overlap is rejected with
    `ERR_TRAILER_WINDOW_CONFLICT`, and per section 2.11 two windows that merely
    touch at a shared date do not overlap."

    Design: Difficulty/resource_temporal_overlap/trailer_half_open_occupancy_rejects_overlap_and_admits_adjacency
    """
    ctx, incumbent, overlapping, _ = _overlapping_bookings_scenario()

    response = api.attach_agreement_unit(
        overlapping["agreement_id"],
        {"trailer_id": ctx["trailer_id"],
         "expected_agreement_version": overlapping["agreement_version"]},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_TRAILER_WINDOW_CONFLICT.value)

    stored = read_agreement(overlapping["agreement_id"])
    assert stored["status"] == "PENDING_ALLOCATION"
    assert stored["allocated_unit_count"] == 0
    assert read_agreement(incumbent["agreement_id"])["quoted_total_cents"] == 94640


def test_a_booking_starting_on_the_exclusive_end_date_is_admitted(api):
    """PRD §2.11: "A contract unit line occupies its trailer over the range
    beginning at `planned_start_date` inclusive and ending at `planned_end_date`
    exclusive, and an agreement's own window likewise runs from `start_date`
    inclusive to `end_date` exclusive."
    PRD §2.11: "Two such windows collide only when they genuinely overlap; a window
    whose right edge equals the next window's left edge does not collide, so a
    trailer coming off one contract on a given date may be booked onto another
    contract starting that same date."

    Design: Difficulty/resource_temporal_overlap/trailer_half_open_occupancy_rejects_overlap_and_admits_adjacency
    """
    ctx, incumbent, _, abutting = _overlapping_bookings_scenario()

    unit = validate_success(
        api.attach_agreement_unit(
            abutting["agreement_id"],
            {"trailer_id": ctx["trailer_id"],
             "expected_agreement_version": abutting["agreement_version"]},
            ADMIN,
        ),
        201,
    )
    assert unit["planned_start_date"] == "2026-09-15"

    stored = read_agreement(abutting["agreement_id"])
    assert stored["status"] == "RESERVED"
    assert stored["quoted_total_cents"] == 67600

    assert read_trailer(ctx["trailer_id"])["availability_status"] == "ALLOCATED", (
        "a unit already ALLOCATED behind an earlier booking stays ALLOCATED"
    )
    standing = [
        u for u in list_units(trailer_id=ctx["trailer_id"])
        if u["status"] == "ALLOCATED"
    ]
    assert len(standing) == 2, "the unit now carries two non-overlapping bookings"

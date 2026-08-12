"""The listing lifecycle and the cascades it drives into the project tree."""

from test_helpers import (
    COORD,
    ApiErrorId,
    assert_listing,
    assert_same_instant,
    make_listing_agent_headers,
    pickup_of,
    setup_listing_active,
    setup_vacant_project_staged,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_closing_a_listing_that_never_went_under_contract_is_refused(api):
    """PRD §2.7: "Rung 33: the listing is in `listing_state` `UNDER_CONTRACT` before a close
    may be recorded; otherwise `ERR_LISTING_NOT_UNDER_CONTRACT`, HTTP 409."
    PRD §3.9: "**Closing the sale** is taken from `UNDER_CONTRACT` only and stamps
    `closed_at` from the logical clock."

    Design: Corner/state_machines/listing_close_without_under_contract_rejected
    """
    ctx = setup_listing_active()

    resp = api.listing_close(ctx["listing_id"], make_listing_agent_headers(ctx["agent_id"]))

    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_UNDER_CONTRACT.value, 409)
    listing = validate_success(api.get_listing(ctx["listing_id"], COORD))
    assert_listing(listing)
    assert listing["listing_state"] == "ACTIVE"
    assert listing["closed_at"] is None


def test_a_terminated_listing_freezes_the_project_beneath_it(api):
    """PRD §2.7: "Rung 15: the ancestor listing is not in `listing_state` `TERMINATED`;
    otherwise `ERR_LISTING_TERMINATED`, HTTP 409."
    PRD §3.9: "`CLOSED_SOLD` and `TERMINATED` are the listing machine's terminal states, and
    both are ancestor freezes: a terminated listing blocks every mutating operation beneath
    it with `ERR_LISTING_TERMINATED`, and a sold-closed listing blocks the staging-execution
    operations with `ERR_LISTING_CLOSED`."

    Design: Corner/state_machines/terminated_listing_freezes_project_writes
    """
    ctx = setup_vacant_project_staged()
    validate_success(api.listing_terminate(
        ctx["listing_id"], "EXPIRED", make_listing_agent_headers(ctx["agent_id"])))

    resp = api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-11T10:00:00Z", "is_reshoot": False}, COORD)

    validate_error(resp, ApiErrorId.ERR_LISTING_TERMINATED.value, 409)
    listing = validate_success(api.get_listing(ctx["listing_id"], COORD))
    assert listing["listing_state"] == "TERMINATED"
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "STAGED"


def test_a_sold_closed_listing_freezes_the_staging_execution_writes(api):
    """PRD §2.7: "Rung 16: the ancestor listing is not in `listing_state` `CLOSED_SOLD` when
    the endpoint writes staging execution state; otherwise `ERR_LISTING_CLOSED`, HTTP 409."
    PRD §3.9: "**Closing the sale** is taken from `UNDER_CONTRACT` only and stamps
    `closed_at` from the logical clock."

    Design: Corner/state_machines/closed_sold_listing_freezes_staging_execution_writes
    """
    ctx = setup_vacant_project_staged()
    agent = make_listing_agent_headers(ctx["agent_id"])
    validate_success(api.listing_under_contract(ctx["listing_id"], agent))
    validate_success(api.listing_close(ctx["listing_id"], agent))

    resp = api.schedule_photo_shoot(
        ctx["proj_id"], {"scheduled_at": "2026-06-11T10:00:00Z", "is_reshoot": False}, COORD)

    validate_error(resp, ApiErrorId.ERR_LISTING_CLOSED.value, 409)
    listing = validate_success(api.get_listing(ctx["listing_id"], COORD))
    assert listing["listing_state"] == "CLOSED_SOLD"
    assert_same_instant(listing["closed_at"], "2026-06-10T09:00:00Z", "listing.closed_at")


def test_a_cascade_bumps_the_version_of_every_row_it_touches(api):
    """PRD §2.4: "When one operation mutates several rows — and in this system that is the
    normal case rather than the exception — every row that changes takes its own `version`
    increment and its own `updated_at` refresh."
    PRD §2.4: "`version` is an integer that begins at 1 when the row is created and
    increments by exactly 1 on every mutation of that row."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation_including_cascaded_ones
    """
    ctx = setup_vacant_project_staged()
    project_before = validate_success(api.get_project(ctx["proj_id"], COORD))["version"]
    lease_before = validate_success(api.get_lease(ctx["lease_id"], COORD))["version"]

    validate_success(api.listing_under_contract(
        ctx["listing_id"], make_listing_agent_headers(ctx["agent_id"])))

    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert project["version"] > project_before
    assert lease["version"] > lease_before
    pickup = pickup_of(ctx["proj_id"])
    assert pickup["version"] == 1
    assert project["workflow_state"] == "DESTAGE_PENDING"


def test_a_listing_may_go_back_under_contract_after_a_fallout(api):
    """PRD §3.9: "The cycle `UNDER_CONTRACT → BACK_ON_MARKET → UNDER_CONTRACT` may repeat."
    PRD §3.9: "**Going under contract** is taken from `ACTIVE` or from `BACK_ON_MARKET`,
    stamps `under_contract_at` from the logical clock, and fires three cascade hops."

    Design: Difficulty/non_linear_state_machine/listing_cycles_under_contract_back_on_market_under_contract
    """
    ctx = setup_listing_active()
    agent = make_listing_agent_headers(ctx["agent_id"])
    validate_success(api.listing_under_contract(ctx["listing_id"], agent))
    validate_success(api.listing_fall_out_of_escrow(ctx["listing_id"], agent))

    validate_success(api.listing_under_contract(ctx["listing_id"], agent))

    listing = validate_success(api.get_listing(ctx["listing_id"], COORD))
    assert listing["listing_state"] == "UNDER_CONTRACT"
    assert listing["fallout_count"] == 1
    assert_same_instant(listing["under_contract_at"], "2026-06-01T00:00:00Z",
                        "listing.under_contract_at")
    assert listing["closed_at"] is None


def test_a_fallout_returns_the_listing_to_the_market_and_counts_it(api):
    """PRD §3.9: "**Falling out of escrow** is the cyclic arc, taken from `UNDER_CONTRACT`
    back to `BACK_ON_MARKET`; it requires the listing to be `UNDER_CONTRACT` and increments
    `fallout_count`, which records how often the sale has collapsed."
    PRD §3.1: "A listing's `listing_state` begins at `ACTIVE` and its `fallout_count` at 0;
    `under_contract_at` and `closed_at` are both null until the corresponding transition sets
    them."

    Design: Difficulty/non_linear_state_machine/listing_cycles_under_contract_back_on_market_under_contract
    """
    ctx = setup_listing_active()
    agent = make_listing_agent_headers(ctx["agent_id"])
    validate_success(api.listing_under_contract(ctx["listing_id"], agent))

    validate_success(api.listing_fall_out_of_escrow(ctx["listing_id"], agent))

    listing = validate_success(api.get_listing(ctx["listing_id"], COORD))
    assert listing["listing_state"] == "BACK_ON_MARKET"
    assert listing["fallout_count"] == 1


def test_going_under_contract_moves_the_project_and_ends_the_lease_term(api):
    """PRD §3.9: "Hop one moves every project on that listing whose `workflow_state` is
    `STAGED` to `DESTAGE_PENDING` and sets `destage_eligible` true. Hop two moves that
    project's lease — `ACTIVE` or `EXTENDED` — to `ENDING` and re-derives both ends of the
    pickup window. Hop three auto-creates a pickup on the project in state `SCHEDULED` with
    its `scheduled_at` set to the freshly derived `pickup_window_start`."

    Design: Difficulty/transitive_cascade/under_contract_three_hop_destage_eligibility_cascade
    """
    ctx = setup_vacant_project_staged()

    validate_success(api.listing_under_contract(
        ctx["listing_id"], make_listing_agent_headers(ctx["agent_id"])))

    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "DESTAGE_PENDING"
    assert project["destage_eligible"] is True
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["state"] == "ENDING"
    assert lease["billed_cycles"] == 4


def test_an_early_destage_anchors_the_pickup_window_on_the_clock(api):
    """PRD §3.5: "The anchor is the lease's `end_date` in the ordinary case, and it is the
    logical clock instead when the lease has reached `ENDING` before its own `end_date` —
    that is, when an early de-stage has been triggered."
    PRD §3.5: "`pickup_window_start` is the anchor plus 5 days; `pickup_window_end` is
    `pickup_window_start` plus 7 days."
    PRD §3.9: "Hop three auto-creates a pickup on the project in state `SCHEDULED` with its
    `scheduled_at` set to the freshly derived `pickup_window_start`."

    Design: Difficulty/transitive_cascade/under_contract_three_hop_destage_eligibility_cascade
    """
    ctx = setup_vacant_project_staged()

    validate_success(api.listing_under_contract(
        ctx["listing_id"], make_listing_agent_headers(ctx["agent_id"])))

    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert_same_instant(lease["pickup_window_start"], "2026-06-15T09:00:00Z",
                        "lease.pickup_window_start")
    assert_same_instant(lease["pickup_window_end"], "2026-06-22T09:00:00Z",
                        "lease.pickup_window_end")
    rows, meta = validate_paginated(api.list_pickups(
        COORD, params={"project_id": ctx["proj_id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["state"] == "SCHEDULED"
    assert_same_instant(rows[0]["scheduled_at"], "2026-06-15T09:00:00Z",
                        "pickup.scheduled_at")


def test_a_fallout_reopens_the_project_for_a_restage(api):
    """PRD §3.9: "Hop one moves the linked project `DESTAGE_PENDING → RESTAGE_REQUIRED` and
    increments its `restage_count`, while `destage_eligible` returns to false."
    PRD §3.9: "**Falling out of escrow** is the cyclic arc, taken from `UNDER_CONTRACT` back
    to `BACK_ON_MARKET`; it requires the listing to be `UNDER_CONTRACT` and increments
    `fallout_count`, which records how often the sale has collapsed."

    Design: Difficulty/transitive_cascade/fall_out_of_escrow_four_hop_restage_cascade
    """
    ctx = setup_vacant_project_staged()
    agent = make_listing_agent_headers(ctx["agent_id"])
    validate_success(api.listing_under_contract(ctx["listing_id"], agent))

    validate_success(api.listing_fall_out_of_escrow(ctx["listing_id"], agent))

    listing = validate_success(api.get_listing(ctx["listing_id"], COORD))
    assert listing["listing_state"] == "BACK_ON_MARKET"
    assert listing["fallout_count"] == 1
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "RESTAGE_REQUIRED"
    assert project["restage_count"] == 1
    assert project["destage_eligible"] is False


def test_a_fallout_cancels_the_pickup_and_reactivates_the_lease(api):
    """PRD §3.9: "Hop two moves the project's `SCHEDULED` pickup to `CANCELLED`. Hop three
    moves the lease `ENDING → ACTIVE` and clears the derived pickup window."
    PRD §3.5: "The reverse arc, `ENDING → ACTIVE`, is taken when escrow falls through, and it
    clears the derived pickup window."

    Design: Difficulty/transitive_cascade/fall_out_of_escrow_four_hop_restage_cascade
    """
    ctx = setup_vacant_project_staged()
    agent = make_listing_agent_headers(ctx["agent_id"])
    validate_success(api.listing_under_contract(ctx["listing_id"], agent))
    pickup = pickup_of(ctx["proj_id"])

    validate_success(api.listing_fall_out_of_escrow(ctx["listing_id"], agent))

    assert validate_success(api.get_pickup(pickup["id"], COORD))["state"] == "CANCELLED"
    assert validate_success(api.get_lease(ctx["lease_id"], COORD))["state"] == "ACTIVE"

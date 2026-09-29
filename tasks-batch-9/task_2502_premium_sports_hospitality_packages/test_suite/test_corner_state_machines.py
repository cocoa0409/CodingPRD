"""Lifecycle probes: initial states, declared edges, replays and terminal locks.

Every entity in this domain opens in a declared initial state, advances only
along the edges the PRD names, refuses a replayed transition with a state
conflict rather than a silent success, and — once terminal — refuses both its
own triggers and the child creations gated on it. The fixture-cancellation
cascade is probed by its exclusions: the rows it must leave alone.
"""

from typing import Any, Dict

from test_helpers import (
    COMMERCIAL_DIRECTOR,
    COMMERCIAL_MANAGER,
    ERR_INVALID_BUILD_STATE,
    ERR_INVALID_DEAL_STATE,
    ERR_INVALID_EVENT_STATE,
    ERR_INVALID_PACKAGE_STATE,
    ERR_TRANCHE_NOT_PENDING,
    FINANCE_CONTROLLER,
    OPERATIONS_MANAGER,
    RIGHTS_MANAGER,
    USER_COMMERCIAL_MANAGER,
    USER_FINANCE_CONTROLLER,
    ApiClient,
    add_component,
    allocate_booking,
    approve_build,
    assert_block_position,
    assert_deal_position,
    assert_fraction_4dp,
    assert_itinerary,
    assert_package_pricing,
    assert_total_count,
    bronze_component_payload,
    bronze_package_payload,
    cancel_booking,
    confirm_tranche_payload,
    deal_version,
    get_success_data,
    hospitality_build_payload,
    installments_of,
    issue_credentials,
    make_assignment,
    make_block,
    make_booking,
    make_bronze_package,
    make_build,
    make_client,
    make_committed_deal,
    make_deal,
    make_event,
    make_host,
    make_published_bronze_package,
    make_ready_build,
    make_tranche,
    pay_installment,
    price_package,
    publish_payload,
    read_block,
    read_booking,
    read_client,
    read_event,
    read_host,
    release_deal,
    reset_clock,
    rights_deal_payload,
    set_clock,
    validate_error,
)

# The round-numbered BRONZE deal used throughout: forty contracted ticket units
# guaranteeing twenty, at eighty cents a unit.
DEAL_SPEC: Dict[str, Any] = {
    "contracted_units": 40,
    "guaranteed_minimum_units": 20,
    "unit_cost_cents": 8000,
}


def _sellable_bronze_fixture(api: ApiClient) -> Dict[str, Any]:
    """One fixture whose whole ticket contract has been released and sold on.

    The CORPORATE block is created before the release is confirmed, so the
    waterfall fills it to its full target of forty on confirmation. The deal
    ends `FULLY_RELEASED` with nothing still owing, so a booking on this
    fixture carries no guarantee surcharge.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], **DEAL_SPEC)
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=40,
                       priority_rank=1)
    tranche = release_deal(api, deal["id"], 40)
    package = make_published_bronze_package(api, event["id"])
    client = make_client(api)
    return {
        "event": event,
        "deal": deal,
        "tranche": tranche,
        "block": read_block(api, block["id"]),
        "package": package,
        "client": client,
    }


# --------------------------------------------------------------------------
# Declared initial states
# --------------------------------------------------------------------------


def test_a_fresh_fixture_deal_package_and_client_open_in_their_initial_states(
    api: ApiClient, clock: str,
) -> None:
    """Five machines are proved to start where the contract says they start.

    A registered fixture is `SCHEDULED` with no postponement history and no
    risk; a fresh acquisition is a `DRAFT` with all four exposure figures at
    zero and no audit stamp; a package skeleton is a `DRAFT` with no money on
    it and neither approval stamp set; and a registered buyer is `ACTIVE` with
    no exposure.

    PRD §3.1: "A newly registered fixture opens in `SCHEDULED` with `postponement_count` at 0, `fulfillment_risk_score` at 0, `risk_posture` at `NORMAL`, and both `original_event_date` and `rebook_deadline_at` unset."
    PRD §3.1: "A fresh acquisition opens in `DRAFT` with `released_units`, `shortfall_units`, `unallocated_units` and `minimum_liability_cents` all at 0 and with `committed_by_user_id` and `settled_at` unset."
    PRD §3.4: "A new package opens in `DRAFT` with `base_cost_cents`, `component_price_subtotal_cents`, `list_price_cents` and `margin_pct` all at 0 and with `priced_by_user_id`, `priced_at`, `published_by_user_id` and `published_at` unset."
    PRD §3.5: "A new client opens with `client_status` at `ACTIVE`, `outstanding_cents` at 0 and `overdue_installment_count` at 0."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    event = make_event(api)
    assert event["status"] == "SCHEDULED"
    assert event["postponement_count"] == 0
    assert event["fulfillment_risk_score"] == 0
    assert event["risk_posture"] == "NORMAL"
    assert event["original_event_date"] is None
    assert event["rebook_deadline_at"] is None
    assert event["version"] == 1

    deal = make_deal(api, event["id"], **DEAL_SPEC)
    assert deal["deal_status"] == "DRAFT"
    assert deal["released_units"] == 0
    assert deal["shortfall_units"] == 0
    assert deal["unallocated_units"] == 0
    assert deal["minimum_liability_cents"] == 0
    assert deal["committed_by_user_id"] is None
    assert deal["settled_at"] is None
    assert deal["version"] == 1

    package = make_bronze_package(api, event["id"])
    assert package["package_status"] == "DRAFT"
    assert_package_pricing(package, base_cost=0, subtotal=0, list_price=0,
                           margin_pct=0.0000)
    assert package["priced_by_user_id"] is None
    assert package["priced_at"] is None
    assert package["published_by_user_id"] is None
    assert package["published_at"] is None
    assert package["version"] == 1

    client = make_client(api)
    assert client["client_status"] == "ACTIVE"
    assert client["outstanding_cents"] == 0
    assert client["overdue_installment_count"] == 0
    assert client["version"] == 1


def test_a_planned_build_opens_unapproved_with_its_three_cost_lines_totalled(
    api: ApiClient, event: Dict[str, Any],
) -> None:
    """A build-out starts `PLANNED`, unapproved, and already costed.

    The three cost lines are summed at once — 120000 of build, 60000 of
    catering and 40000 of staffing — while the finance stamp is still empty,
    which is what keeps the spend out of the fixture's margin base.

    PRD §3.7: "A new build opens in `PLANNED` with `approved_by_user_id` unset, and — importantly — a `PLANNED` build does not yet enter the fixture's margin cost base."
    PRD §3.7: "The build's `total_cost_cents` is simply the sum of those three cost lines and is computed at once."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    build = make_build(api, event["id"], zone_code="ZONE_A", space_units=30,
                       catering_covers=20, staff_count=5)

    assert build["build_state"] == "PLANNED"
    assert build["approved_by_user_id"] is None
    assert build["build_cost_cents"] == 120000
    assert build["catering_cost_cents"] == 60000
    assert build["staffing_cost_cents"] == 40000
    assert build["total_cost_cents"] == 220000
    assert build["version"] == 1


def test_a_block_and_a_tranche_open_empty_on_a_deal_that_has_released_nothing(
    api: ApiClient, event: Dict[str, Any],
) -> None:
    """The two traps of the initial-state pass: an eager block and an eager tranche.

    Both children are created on a freshly committed deal that has released
    nothing, so the block cannot be flipped to `EXHAUSTED` by the waterfall and
    the promise cannot be read as already honoured. The block therefore holds
    zero of everything and the tranche is `PENDING` with nothing confirmed,
    while the deal itself still reports no released and no unallocated units.

    PRD §3.3: "A new block opens `OPEN` with `allocated_units`, `committed_units` and `released_back_units` all at 0 and `recalled_at` unset."
    PRD §3.2: "A new tranche opens in `PENDING` with `confirmed_units` at 0 and `confirmed_at` and `lapsed_at` unset."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    deal = make_committed_deal(api, event["id"], **DEAL_SPEC)

    block = make_block(api, deal["id"], channel="CORPORATE", target_units=40,
                       priority_rank=1)
    assert_block_position(block, allocated=0, committed=0, released_back=0,
                          state="OPEN")
    assert block["recalled_at"] is None
    assert block["version"] == 1

    tranche = make_tranche(api, deal["id"], promised_units=40)
    assert tranche["tranche_state"] == "PENDING"
    assert tranche["confirmed_units"] == 0
    assert tranche["confirmed_at"] is None
    assert tranche["lapsed_at"] is None
    assert tranche["version"] == 1

    after = get_success_data(api.get_rights_deal(deal["id"], RIGHTS_MANAGER))
    assert after["released_units"] == 0
    assert after["unallocated_units"] == 0


# --------------------------------------------------------------------------
# RESERVED -> ALLOCATED, and the three unit denominations
# --------------------------------------------------------------------------


def test_allocating_a_booking_debits_ticket_units_not_package_units(
    api: ApiClient,
) -> None:
    """Five packages of two tickets each draw ten units from the block.

    The booking is denominated in packages and the allocation ledger in
    rights-holder tickets, so the block's committed units move by five times the
    package's two tickets rather than by the booking's five units. The block's
    own version is the one that advances, because it is the record the writer
    pinned.

    PRD §3.5: "On success the booking moves `RESERVED → ALLOCATED`, its `allocation_block_id` is set, the block's `committed_units` increases by the booking's `units` multiplied by `tickets_per_package`, the block's `version` increases by one, and the fixture's `fulfillment_risk_score` and `risk_posture` are recomputed."

    Design: Corner/state_machines/allocate_moves_booking_reserved_to_allocated_and_commits_block_units
    """
    scenario = _sellable_bronze_fixture(api)
    booking = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                           channel="CORPORATE", units=5)
    assert booking["fulfillment_status"] == "RESERVED"
    assert booking["net_price_cents"] == 558720
    assert booking["allocation_block_id"] is None

    before = read_block(api, scenario["block"]["id"])
    assert_block_position(before, allocated=40, committed=0, released_back=0,
                          state="EXHAUSTED")

    allocated = allocate_booking(api, booking["id"], before["id"])

    assert allocated["fulfillment_status"] == "ALLOCATED"
    assert allocated["allocation_block_id"] == before["id"]

    after = read_block(api, before["id"])
    assert after["committed_units"] == 10
    assert after["version"] == before["version"] + 1


def test_committing_a_sale_leaves_the_block_state_and_the_deal_untouched(
    api: ApiClient,
) -> None:
    """The block stays `EXHAUSTED` and the deal's version does not move.

    Block state is a pure function of allocation against target, so selling ten
    of the forty allocated units cannot change it. Nor is a sale to a client a
    release from the rights holder: the deal keeps the version its tranche
    confirmation left it at, stays `FULLY_RELEASED` and reports nothing
    unallocated. The booking's money dimension is equally untouched.

    PRD §2.9: "Committing a booking against a block, or releasing one back, moves `committed_units` and `released_back_units` but never touches `block_state`."
    PRD §3.5: "The booking's `payment_status` is untouched."

    Design: Corner/state_machines/allocate_moves_booking_reserved_to_allocated_and_commits_block_units
    """
    scenario = _sellable_bronze_fixture(api)
    booking = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                           channel="CORPORATE", units=5)
    assert booking["payment_status"] == "UNPAID"
    deal_before = get_success_data(
        api.get_rights_deal(scenario["deal"]["id"], RIGHTS_MANAGER)
    )

    allocated = allocate_booking(api, booking["id"], scenario["block"]["id"])

    assert allocated["payment_status"] == "UNPAID"
    assert read_block(api, scenario["block"]["id"])["block_state"] == "EXHAUSTED"

    deal_after = get_success_data(
        api.get_rights_deal(scenario["deal"]["id"], RIGHTS_MANAGER)
    )
    assert deal_after["version"] == deal_before["version"]
    assert_deal_position(deal_after, released=40, shortfall=0, liability=320000,
                         status="FULLY_RELEASED", unallocated=0)


# --------------------------------------------------------------------------
# ALLOCATED -> CREDENTIALED
# --------------------------------------------------------------------------


def test_credentialing_mints_one_pass_per_ticket_plus_one_per_package_unit(
    api: ApiClient,
) -> None:
    """Fifteen credentials for five packages of two tickets, and a serial prefix.

    The count is five units times one more than the package's two tickets — a
    third denomination distinct from both the booking's five units and the ten
    ticket units the block gave up. The delivery dimension advances while the
    money dimension stays where it was.

    PRD §3.7: "Issuance moves the booking `ALLOCATED → CREDENTIALED`, sets `credentials_issued_count` to the booking's `units` multiplied by one more than the package's `tickets_per_package` — one credential per ticket plus one hospitality credential per package unit — and stamps a `credential_serial_prefix` on the booking."

    Design: Corner/state_machines/issue_credentials_stamps_count_prefix_and_itinerary
    """
    scenario = _sellable_bronze_fixture(api)
    booking = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                           channel="CORPORATE", units=5)
    allocate_booking(api, booking["id"], scenario["block"]["id"])
    build = make_ready_build(api, scenario["event"]["id"])
    assert build["build_state"] == "READY"

    credentialed = issue_credentials(api, booking["id"])

    assert credentialed["fulfillment_status"] == "CREDENTIALED"
    assert credentialed["payment_status"] == "UNPAID"
    assert credentialed["credentials_issued_count"] == 15
    assert isinstance(credentialed["credential_serial_prefix"], str)
    assert credentialed["credential_serial_prefix"] != ""


def test_credentialing_freezes_the_itinerary_on_the_booking_key_by_key(
    api: ApiClient,
) -> None:
    """The servicing itinerary carries exactly its seven declared keys.

    The fixture supplies the name, the kick-off and the venue; the package
    supplies the bundled hotel nights and the transport flag, which are the
    BRONZE skeleton's defaults of zero and false rather than anything the buyer
    stated; the credential count agrees with the passes just minted; and the
    host list is empty because nobody has been rostered. Reading the booking
    back returns the same object, so it is frozen on the record rather than
    rendered per request.

    PRD §3.7: "It also freezes the servicing `itinerary`, an object with a pinned set of keys: `event_name` and `event_date` and `venue_name` taken from the fixture, `hotel_nights` and `transport_included` taken from the package, `credential_count` matching the credentials just minted, and `host_names`, which lists the `full_name` of each host on this booking's assignments whose `assignment_state` is `ASSIGNED`, ordered by those assignments' `created_at` ascending."

    Design: Corner/state_machines/issue_credentials_stamps_count_prefix_and_itinerary
    """
    scenario = _sellable_bronze_fixture(api)
    booking = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                           channel="CORPORATE", units=5)
    allocate_booking(api, booking["id"], scenario["block"]["id"])
    make_ready_build(api, scenario["event"]["id"])

    credentialed = issue_credentials(api, booking["id"])

    assert_itinerary(credentialed["itinerary"],
                     event_name="Continental Cup Final",
                     event_date="2027-02-01T15:00:00.000Z",
                     venue_name="Meridian Stadium",
                     hotel_nights=0,
                     transport_included=False,
                     credential_count=15,
                     host_names=[])
    assert read_booking(api, booking["id"])["itinerary"] == credentialed["itinerary"]


# --------------------------------------------------------------------------
# A played fixture is terminal
# --------------------------------------------------------------------------


def test_a_played_fixture_refuses_postponement_cancellation_and_re_completion(
    api: ApiClient, clock: str,
) -> None:
    """All three fixture triggers are refused once the fixture has been played.

    The clock is pushed a day past kick-off so completion is legitimate, and the
    childless fixture closes. From there the two remaining lifecycle triggers
    have no edge out of a terminal state, and completion itself cannot be
    replayed. Each refusal is a state conflict, and none of them leaves a mark:
    the fixture's version is exactly where completion left it.

    PRD §3.1: "The fixture's `status` moves only through `SCHEDULED`, `POSTPONED`, `RESCHEDULED`, `CANCELLED` and `COMPLETED`, of which the last two are terminal."
    PRD §3.8: "Postponement is refused with `ERR_INVALID_EVENT_STATE` on a fixture that is already `CANCELLED` or `COMPLETED`."
    PRD §3.9: "**Cancelling a fixture** is a `RightsManager` action available from `SCHEDULED`, `POSTPONED` or `RESCHEDULED`, and it is the widest cascade in the system."
    PRD §3.9: "**Completing a fixture** is likewise a `RightsManager` action, available from `SCHEDULED` and from `RESCHEDULED` only."

    Design: Corner/state_machines/completed_event_is_locked_against_every_further_transition
    """
    event = make_event(api)
    set_clock(api, "2027-02-02T00:00:00Z")

    completed = get_success_data(api.complete_event(event["id"], RIGHTS_MANAGER))
    assert completed["status"] == "COMPLETED"
    version_at_close = completed["version"]

    validate_error(api.postpone_event(event["id"], {}, RIGHTS_MANAGER),
                   ERR_INVALID_EVENT_STATE)
    validate_error(api.cancel_event(event["id"], RIGHTS_MANAGER),
                   ERR_INVALID_EVENT_STATE)
    validate_error(api.complete_event(event["id"], RIGHTS_MANAGER),
                   ERR_INVALID_EVENT_STATE)

    after = read_event(api, event["id"])
    assert after["status"] == "COMPLETED"
    assert after["version"] == version_at_close


def test_a_played_fixture_refuses_every_child_the_workflows_hang_off_it(
    api: ApiClient, clock: str,
) -> None:
    """Nothing may be acquired, packaged or dressed against a played fixture.

    The three child creations that name a fixture directly are each gated on the
    fixture being live, so all three report the fixture's state conflict rather
    than accepting a row that could never be worked. The refusals really are
    refusals: the fixture still has no deals hanging off it.

    PRD §3.1: "Against a `SCHEDULED`, `POSTPONED` or `RESCHEDULED` fixture — and never against one that has been cancelled or played, which draws `ERR_INVALID_EVENT_STATE` — the same manager acquires inventory."
    PRD §3.4: "Skeletons may only be created while the fixture is `SCHEDULED`, `POSTPONED` or `RESCHEDULED`."
    PRD §3.7: "An `OperationsManager` plans a hospitality build-out against a fixture that is still `SCHEDULED`, `POSTPONED` or `RESCHEDULED`, naming the fixture through `event_id` and the venue zone it occupies through `zone_code`."

    Design: Corner/state_machines/completed_event_is_locked_against_every_further_transition
    """
    event = make_event(api)
    set_clock(api, "2027-02-02T00:00:00Z")
    get_success_data(api.complete_event(event["id"], RIGHTS_MANAGER))

    validate_error(
        api.create_rights_deal(rights_deal_payload(event["id"], **DEAL_SPEC),
                               RIGHTS_MANAGER),
        ERR_INVALID_EVENT_STATE,
    )
    validate_error(
        api.create_package_product(bronze_package_payload(event["id"]),
                                   COMMERCIAL_MANAGER),
        ERR_INVALID_EVENT_STATE,
    )
    validate_error(
        api.create_hospitality_build(hospitality_build_payload(event["id"]),
                                     OPERATIONS_MANAGER),
        ERR_INVALID_EVENT_STATE,
    )

    assert_total_count(
        api.list_rights_deals(RIGHTS_MANAGER, {"event_id": event["id"]}), 0
    )


# --------------------------------------------------------------------------
# The package lifecycle's declared edges
# --------------------------------------------------------------------------


def _draft_bronze_package(api: ApiClient) -> Dict[str, Any]:
    """A one-line BRONZE draft on a fixture whose ticket supply is committed.

    The committed TICKET deal is what makes a later publication legitimate, so
    the only thing standing between the draft and sale is the pricing pass.
    """
    reset_clock(api)
    event = make_event(api)
    make_committed_deal(api, event["id"], **DEAL_SPEC)
    package = make_bronze_package(api, event["id"])
    add_component(api, package["id"])
    return {"event": event, "package": package}


def test_a_draft_package_cannot_be_published_even_at_its_true_version(
    api: ApiClient,
) -> None:
    """Publication has no edge from `DRAFT`, and the pin is not the problem.

    The director supplies the version the package genuinely carries — adding a
    component line does not move it — so nothing about the request is stale. The
    refusal is therefore about the missing edge from `DRAFT` to `PUBLISHED`, and
    the package is left exactly where it was.

    PRD §3.4: "The package must be `PRICED`, or the request is `ERR_INVALID_PACKAGE_STATE`."

    Design: Corner/state_machines/package_lifecycle_rejects_transitions_outside_the_declared_edges
    """
    scenario = _draft_bronze_package(api)
    package_id = scenario["package"]["id"]
    current = get_success_data(api.get_package_product(package_id, COMMERCIAL_MANAGER))
    assert current["package_status"] == "DRAFT"
    assert current["version"] == 1

    validate_error(
        api.publish_package_product(package_id, publish_payload(current["version"]),
                                    COMMERCIAL_DIRECTOR),
        ERR_INVALID_PACKAGE_STATE,
    )

    after = get_success_data(api.get_package_product(package_id, COMMERCIAL_MANAGER))
    assert after["package_status"] == "DRAFT"
    assert after["version"] == 1
    assert after["published_by_user_id"] is None


def test_pricing_runs_from_draft_and_again_as_a_self_loop_from_priced(
    api: ApiClient,
) -> None:
    """`DRAFT → PRICED` and then `PRICED → PRICED`, each a real write.

    The first pass values the single ticket line at 120000 with a margin of
    0.1667, stamps the acting pricer and the logical clock, and leaves both
    approval stamps empty. Running the pass again is a declared self-edge rather
    than a no-op: the version moves a second time and the approval stamps are
    still empty, which is what a later publication's pin is watching.

    PRD §3.4: "Pricing is available from `DRAFT` and, as a self-loop, from `PRICED`, and may be performed by a `CommercialManager` or a `CommercialDirector`."
    PRD §3.4: "Finally the pass sets `package_status` to `PRICED`, stamps `priced_by_user_id` with the acting `X-User-ID` and `priced_at` with the logical clock, clears both `published_by_user_id` and `published_at` back to null, and increases the package's `version` by one."
    PRD §2.4: "Before the clock has ever been set, its value is exactly `2026-08-01T00:00:00Z`, and every rule that reads the clock sees that default rather than the real wall clock."

    Design: Corner/state_machines/package_lifecycle_rejects_transitions_outside_the_declared_edges
    """
    scenario = _draft_bronze_package(api)
    package_id = scenario["package"]["id"]

    priced = price_package(api, package_id)
    assert_package_pricing(priced, base_cost=100000, subtotal=120000,
                           list_price=120000, margin_pct=0.1667, status="PRICED")
    assert priced["priced_by_user_id"] == USER_COMMERCIAL_MANAGER
    assert priced["priced_at"] == "2026-08-01T00:00:00.000Z"
    assert priced["published_by_user_id"] is None
    assert priced["published_at"] is None
    assert priced["version"] == 2

    repriced = price_package(api, package_id)
    assert repriced["package_status"] == "PRICED"
    assert repriced["version"] == 3
    assert repriced["published_by_user_id"] is None
    assert repriced["published_at"] is None


def test_a_published_package_refuses_both_re_pricing_and_a_new_component_line(
    api: ApiClient,
) -> None:
    """`PUBLISHED` has no edge back to `PRICED` and no edge to a new line.

    Publication is the point at which the product is frozen for sale, so neither
    the pricing pass nor the component editor has a path out of it, and both
    report the package's state conflict. The evidence that nothing slipped
    through is the component count: still the single line the draft was built
    with.

    PRD §3.4: "Lines may only be added while the package is `DRAFT` or `PRICED`; adding to a `PUBLISHED` or `CLOSED` package is `ERR_INVALID_PACKAGE_STATE`."
    PRD §3.4: "Pricing is available from `DRAFT` and, as a self-loop, from `PRICED`, and may be performed by a `CommercialManager` or a `CommercialDirector`."

    Design: Corner/state_machines/package_lifecycle_rejects_transitions_outside_the_declared_edges
    """
    scenario = _draft_bronze_package(api)
    package_id = scenario["package"]["id"]
    priced = price_package(api, package_id)

    published = get_success_data(
        api.publish_package_product(package_id, publish_payload(priced["version"]),
                                    COMMERCIAL_DIRECTOR)
    )
    assert published["package_status"] == "PUBLISHED"
    assert published["version"] == priced["version"] + 1

    validate_error(api.price_package_product(package_id, COMMERCIAL_MANAGER),
                   ERR_INVALID_PACKAGE_STATE)
    validate_error(
        api.create_package_component(
            bronze_component_payload(package_id, sequence_no=2), COMMERCIAL_MANAGER
        ),
        ERR_INVALID_PACKAGE_STATE,
    )

    assert_total_count(
        api.list_package_components(COMMERCIAL_MANAGER,
                                    {"package_product_id": package_id}), 1
    )


# --------------------------------------------------------------------------
# A replayed transition is a conflict, never a silent success
# --------------------------------------------------------------------------


def test_replaying_a_commit_or_a_confirmation_conflicts_and_changes_nothing(
    api: ApiClient, event: Dict[str, Any],
) -> None:
    """Both replays are refused, and the deal's whole position is unmoved.

    The deal has already left `DRAFT` and the tranche has already left `PENDING`,
    so neither trigger has an edge to travel. Twenty of the forty contracted units
    are released, so the deal sits in `PARTIALLY_RELEASED` — one of the three
    statuses a confirmation accepts — and the deal's own state therefore cannot be
    what refuses the replay. The confirmation replay also pins the version the deal
    genuinely carries after the first confirmation, which is what makes the refusal
    about the tranche's terminal state rather than about a stale read. Afterwards
    the deal still shows twenty units released against a liability of 160000 at the
    version the first confirmation left, and the tranche still shows its twenty
    units confirmed.

    PRD §3.1: "Committing a deal that is anything other than `DRAFT` yields `ERR_INVALID_DEAL_STATE`; because the fixture's state is checked ahead of the deal's, a commit attempted on a cancelled fixture reports the fixture error rather than the deal error."
    PRD §3.2: "The tranche must still be `PENDING`, or the call fails with `ERR_TRANCHE_NOT_PENDING`; its deal must be `COMMITTED`, `PARTIALLY_RELEASED` or `SHORTFALL_DECLARED`; and `confirmed_units` must lie between 1 and the tranche's `promised_units` inclusive, with anything outside that range rejected as `ERR_CONFIRMED_UNITS_OUT_OF_RANGE`."
    PRD §3.2: "`CONFIRMED`, `SHORT_CONFIRMED` and `LAPSED` are all terminal tranche states."

    Design: Corner/state_machines/repeating_a_completed_transition_is_a_state_conflict_not_a_no_op
    """
    deal = make_committed_deal(api, event["id"], **DEAL_SPEC)
    tranche = release_deal(api, deal["id"], 20)
    assert tranche["tranche_state"] == "CONFIRMED"
    settled_version = deal_version(api, deal["id"])

    validate_error(api.commit_rights_deal(deal["id"], RIGHTS_MANAGER),
                   ERR_INVALID_DEAL_STATE)
    validate_error(
        api.confirm_release_tranche(
            tranche["id"], confirm_tranche_payload(settled_version, 20),
            RIGHTS_MANAGER,
        ),
        ERR_TRANCHE_NOT_PENDING,
    )

    after = get_success_data(api.get_rights_deal(deal["id"], RIGHTS_MANAGER))
    assert_deal_position(after, released=20, shortfall=0, liability=160000,
                         status="PARTIALLY_RELEASED")
    assert after["version"] == settled_version

    tranche_after = get_success_data(
        api.get_release_tranche(tranche["id"], RIGHTS_MANAGER)
    )
    assert tranche_after["tranche_state"] == "CONFIRMED"
    assert tranche_after["confirmed_units"] == 20


def test_replaying_a_build_approval_conflicts_and_keeps_the_first_signature(
    api: ApiClient, event: Dict[str, Any],
) -> None:
    """A second approval is refused rather than re-stamping the approver.

    Approval is only available from `PLANNED`, so replaying it on a build that is
    already `APPROVED` is a state conflict. The finance signature and the
    version from the first approval both survive untouched, which is what makes
    the refusal a genuine rejection rather than an idempotent repeat.

    PRD §3.7: "Finance sign-off is what pulls the spend into the margin. A `FinanceController` approves a build that is `PLANNED`, on a fixture that is `SCHEDULED`, `POSTPONED` or `RESCHEDULED`; approving a build in any other `build_state` is `ERR_INVALID_BUILD_STATE`, and because the fixture's state is checked ahead of the build's, an approval on a cancelled fixture reports `ERR_INVALID_EVENT_STATE`."

    Design: Corner/state_machines/repeating_a_completed_transition_is_a_state_conflict_not_a_no_op
    """
    build = make_build(api, event["id"], zone_code="ZONE_A")
    approved = approve_build(api, build["id"])
    assert approved["build_state"] == "APPROVED"
    assert approved["approved_by_user_id"] == USER_FINANCE_CONTROLLER

    validate_error(api.approve_hospitality_build(build["id"], FINANCE_CONTROLLER),
                   ERR_INVALID_BUILD_STATE)

    after = get_success_data(
        api.get_hospitality_build(build["id"], OPERATIONS_MANAGER)
    )
    assert after["build_state"] == "APPROVED"
    assert after["approved_by_user_id"] == USER_FINANCE_CONTROLLER
    assert after["version"] == approved["version"]


# --------------------------------------------------------------------------
# Completion's two preconditions
# --------------------------------------------------------------------------


def test_a_fixture_that_has_not_kicked_off_yet_cannot_be_completed(
    api: ApiClient,
) -> None:
    """Closing the books six months early is refused as a state conflict.

    The logical clock sits at 2026-08-01 and kick-off is 2027-02-01, so the
    fixture has not been played and the books cannot close. The fixture is left
    `SCHEDULED` at the version it already had, and the sold booking is still
    `RESERVED` rather than swept to `DELIVERED`.

    PRD §3.9: "It requires the fixture's `event_date` to be at or before the logical clock — completing a fixture that has not yet kicked off is `ERR_INVALID_EVENT_STATE` — and it requires that no booking of the fixture is still `RESERVED` or `REBOOK_PENDING`, since every sold place must have been either delivered or disposed of before the books close."

    Design: Corner/state_machines/complete_event_enforces_clock_and_live_booking_preconditions
    """
    scenario = _sellable_bronze_fixture(api)
    booking = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                           channel="CORPORATE", units=5)
    before = read_event(api, scenario["event"]["id"])
    assert before["status"] == "SCHEDULED"

    validate_error(api.complete_event(scenario["event"]["id"], RIGHTS_MANAGER),
                   ERR_INVALID_EVENT_STATE)

    after = read_event(api, scenario["event"]["id"])
    assert after["status"] == "SCHEDULED"
    assert after["version"] == before["version"]
    assert read_booking(api, booking["id"])["fulfillment_status"] == "RESERVED"


def test_a_reserved_booking_blocks_completion_until_it_is_disposed_of(
    api: ApiClient,
) -> None:
    """Kick-off has arrived, but one unallocated sale still has to be settled.

    With the clock exactly on kick-off the temporal precondition is satisfied,
    yet an unallocated sale is neither delivered nor disposed of, so the books
    stay open. Cancelling it charges the full fee, because a fixture zero days
    away sits at the bottom of the tier ladder: 558720 of fee, nothing to refund,
    a balance to settle. With the reservation gone completion succeeds, sweeping
    the allocated sale to `DELIVERED` and closing the package behind it.

    PRD §3.9: "It requires the fixture's `event_date` to be at or before the logical clock — completing a fixture that has not yet kicked off is `ERR_INVALID_EVENT_STATE` — and it requires that no booking of the fixture is still `RESERVED` or `REBOOK_PENDING`, since every sold place must have been either delivered or disposed of before the books close."
    PRD §3.9: "Completion sets `status` to `COMPLETED`; moves every booking whose `fulfillment_status` is `ALLOCATED` or `CREDENTIALED` to `DELIVERED`; moves every package whose `package_status` is not already `CLOSED` to `CLOSED`; moves every hospitality build that is `READY` to `CLOSED` and every build that is `PLANNED` or `APPROVED` to `CANCELLED`; and moves every host assignment of the fixture's bookings whose `assignment_state` is `ASSIGNED` to `RELEASED` with `released_at` stamped, recomputing each affected host's `active_assignment_count`."
    PRD §3.8: "The fee percentage is read off a days-to-event ladder in which every comparison is inclusive: 0.10 when the fixture is at least 90 days away, otherwise 0.25 when it is at least 60 days away, otherwise 0.50 when it is at least 30 days away, otherwise 0.80 when it is at least 7 days away, otherwise 1.00."

    Design: Corner/state_machines/complete_event_enforces_clock_and_live_booking_preconditions
    """
    scenario = _sellable_bronze_fixture(api)
    reserved = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                            channel="CORPORATE", units=5)
    sold = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                        channel="CORPORATE", units=5)
    allocate_booking(api, sold["id"], scenario["block"]["id"])
    set_clock(api, "2027-02-01T15:00:00Z")

    validate_error(api.complete_event(scenario["event"]["id"], RIGHTS_MANAGER),
                   ERR_INVALID_EVENT_STATE)

    settled = cancel_booking(api, reserved["id"])
    assert settled["settlement_variant"] == "TIER_SCHEDULE"
    assert settled["cancellation_fee_cents"] == 558720
    assert settled["refund_cents"] == 0
    assert settled["balance_due_cents"] == 558720
    assert settled["payment_status"] == "SETTLEMENT_DUE"

    completed = get_success_data(
        api.complete_event(scenario["event"]["id"], RIGHTS_MANAGER)
    )
    assert completed["status"] == "COMPLETED"
    assert read_booking(api, sold["id"])["fulfillment_status"] == "DELIVERED"
    assert get_success_data(
        api.get_package_product(scenario["package"]["id"], COMMERCIAL_MANAGER)
    )["package_status"] == "CLOSED"


# --------------------------------------------------------------------------
# Fixture cancellation spares whatever is already terminal
# --------------------------------------------------------------------------


def _fixture_with_one_settled_and_one_live_booking(api: ApiClient) -> Dict[str, Any]:
    """Two sales on one fixture: one already settled, one fully serviced.

    The first sale is cancelled by the client while the fixture is still
    `SCHEDULED` and 184 days away, so it settles on the top rung of the tier
    ladder at ten percent and lands in `SETTLEMENT_DUE`. The second is allocated,
    hosted and credentialed. The fixture also carries a `READY` build-out in
    ZONE_A and a `PLANNED` one in ZONE_B.
    """
    scenario = _sellable_bronze_fixture(api)
    settled = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                           channel="CORPORATE", units=5)
    scenario["settled"] = cancel_booking(api, settled["id"])

    live = make_booking(api, scenario["client"]["id"], scenario["package"]["id"],
                        channel="CORPORATE", units=5)
    allocate_booking(api, live["id"], scenario["block"]["id"])
    scenario["ready_build"] = make_ready_build(api, scenario["event"]["id"])
    scenario["host"] = make_host(api)
    scenario["assignment"] = make_assignment(api, scenario["host"]["id"], live["id"],
                                             scenario["ready_build"]["id"])
    scenario["live"] = issue_credentials(api, live["id"])
    scenario["planned_build"] = make_build(api, scenario["event"]["id"],
                                          zone_code="ZONE_B")
    return scenario


def test_a_cancelled_fixture_leaves_an_already_settled_booking_exactly_as_it_was(
    api: ApiClient,
) -> None:
    """The waived-fee cascade reaches the live sale and steps over the settled one.

    The sale the client had already cancelled keeps its ten-percent fee of 55872
    and the settlement line raised for it, because it is not one of the bookings
    this cascade cancelled. The credentialed sale is the one that moves: its fee
    is waived to zero, it is refunded, its block reference and credentials are
    cleared, and its three schedule lines are voided.

    PRD §3.9: "Every booking of the fixture whose `fulfillment_status` is neither `CANCELLED` nor `DELIVERED` moves to `CANCELLED`, and because the provider caused the cancellation the fee is waived entirely: `settlement_variant` is recorded as `TIER_SCHEDULE`, `cancellation_fee_cents` is 0, `refund_cents` equals whatever the booking had paid, `balance_due_cents` is 0, `payment_status` becomes `REFUNDED`, and `allocation_block_id` is cleared to null."
    PRD §3.9: "Because those bookings were cancelled, every one of their installments whose `installment_state` is `SCHEDULED` or `OVERDUE` moves to `VOIDED`, and because those installments were voided each affected client's `outstanding_cents` and `overdue_installment_count` are recomputed."

    Design: Corner/state_machines/cancelling_an_event_spares_children_already_in_terminal_states
    """
    scenario = _fixture_with_one_settled_and_one_live_booking(api)
    assert scenario["settled"]["cancellation_fee_cents"] == 55872
    assert scenario["settled"]["payment_status"] == "SETTLEMENT_DUE"

    get_success_data(api.cancel_event(scenario["event"]["id"], RIGHTS_MANAGER))

    spared = read_booking(api, scenario["settled"]["id"])
    assert spared["fulfillment_status"] == "CANCELLED"
    assert spared["cancellation_fee_cents"] == 55872
    assert spared["balance_due_cents"] == 55872
    assert spared["payment_status"] == "SETTLEMENT_DUE"
    settlement_lines = installments_of(api, spared["id"],
                                       installment_kind="SETTLEMENT")
    assert len(settlement_lines) == 1
    assert settlement_lines[0]["installment_state"] == "SCHEDULED"
    assert settlement_lines[0]["amount_cents"] == 55872

    swept = read_booking(api, scenario["live"]["id"])
    assert swept["fulfillment_status"] == "CANCELLED"
    assert swept["settlement_variant"] == "TIER_SCHEDULE"
    assert swept["cancellation_fee_cents"] == 0
    assert swept["refund_cents"] == 0
    assert swept["balance_due_cents"] == 0
    assert swept["payment_status"] == "REFUNDED"
    assert swept["allocation_block_id"] is None
    assert swept["credentials_issued_count"] == 0
    schedule_lines = installments_of(api, swept["id"], installment_kind="SCHEDULE")
    assert len(schedule_lines) == 3
    assert all(line["installment_state"] == "VOIDED" for line in schedule_lines)


def test_a_cancelled_fixture_terminates_the_deal_but_not_its_confirmed_tranche(
    api: ApiClient,
) -> None:
    """Only `PENDING` promises lapse, so an honoured one keeps its confirmation.

    The deal is terminated and its block recalled with a stamp at the logical
    clock, the block's allocation frozen at the forty units it held. The tranche
    is the spared child: it is already `CONFIRMED`, which is terminal, so it
    keeps its confirmation stamp and is never given a lapse stamp.

    PRD §3.9: "Every rights deal of the fixture whose `deal_status` is neither `SETTLED` nor `TERMINATED` moves to `TERMINATED`; because each of those deals terminated, its `PENDING` tranches move to `LAPSED` with `lapsed_at` stamped and its blocks whose `block_state` is `OPEN` or `EXHAUSTED` move to `RECALLED` with `recalled_at` stamped."
    PRD §2.4: "Wherever a field below is described as being stamped with the current instant — `confirmed_at`, `lapsed_at`, `recalled_at`, `settled_at`, `priced_at`, `published_at`, `paid_at`, `released_at`, `run_at` — the value written is the logical clock's value at the moment of the write."

    Design: Corner/state_machines/cancelling_an_event_spares_children_already_in_terminal_states
    """
    scenario = _fixture_with_one_settled_and_one_live_booking(api)

    get_success_data(api.cancel_event(scenario["event"]["id"], RIGHTS_MANAGER))

    deal = get_success_data(
        api.get_rights_deal(scenario["deal"]["id"], RIGHTS_MANAGER)
    )
    assert deal["deal_status"] == "TERMINATED"

    tranche = get_success_data(
        api.get_release_tranche(scenario["tranche"]["id"], RIGHTS_MANAGER)
    )
    assert tranche["tranche_state"] == "CONFIRMED"
    assert tranche["lapsed_at"] is None
    assert tranche["confirmed_at"] == "2026-08-01T00:00:00.000Z"

    block = read_block(api, scenario["block"]["id"])
    assert block["block_state"] == "RECALLED"
    assert block["recalled_at"] == "2026-08-01T00:00:00.000Z"
    assert block["allocated_units"] == 40


def test_a_cancelled_fixture_closes_a_ready_build_and_cancels_a_planned_one(
    api: ApiClient,
) -> None:
    """The two build-outs land in different terminal states, and the roster voids.

    A signed-off, dressed build-out closes because the spend was genuinely
    incurred, while one that never left the planning stage is simply cancelled.
    Because the build-outs left the active set, the host roster on the
    credentialed sale is voided with a release stamp at the logical clock and the
    host's live counter falls to zero. The package closes with the fixture, and
    the client's exposure is just the settlement still owed on the sale it had
    cancelled itself — the refunded sale contributes nothing.

    PRD §3.9: "Every hospitality build of the fixture whose `build_state` is `PLANNED` or `APPROVED` moves to `CANCELLED` while every one that is `READY` moves to `CLOSED`; because those builds left the active set, every host assignment of the fixture's bookings whose `assignment_state` is `ASSIGNED` moves to `VOIDED` and each affected host's `active_assignment_count` is recomputed."
    PRD §3.9: "Every package of the fixture whose `package_status` is not already `CLOSED` moves to `CLOSED`."
    PRD §3.7: "Voided instead — which happens automatically whenever the parent booking leaves `CREDENTIALED` through a booking cancellation, a fixture postponement or a fixture cancellation — it moves `ASSIGNED → VOIDED`, also with `released_at` stamped, and also followed by a recompute of the host's `active_assignment_count`."
    PRD §3.6: "The second is, across the client's bookings whose `fulfillment_status` is `CANCELLED` **and** whose `payment_status` is `SETTLEMENT_DUE`, that booking's `balance_due_cents`; a cancelled booking that has already settled or been refunded contributes nothing."

    Design: Corner/state_machines/cancelling_an_event_spares_children_already_in_terminal_states
    """
    scenario = _fixture_with_one_settled_and_one_live_booking(api)
    assert read_host(api, scenario["host"]["id"])["active_assignment_count"] == 1

    get_success_data(api.cancel_event(scenario["event"]["id"], RIGHTS_MANAGER))

    assert get_success_data(
        api.get_hospitality_build(scenario["ready_build"]["id"], OPERATIONS_MANAGER)
    )["build_state"] == "CLOSED"
    assert get_success_data(
        api.get_hospitality_build(scenario["planned_build"]["id"], OPERATIONS_MANAGER)
    )["build_state"] == "CANCELLED"

    assignment = get_success_data(
        api.get_host_assignment(scenario["assignment"]["id"], OPERATIONS_MANAGER)
    )
    assert assignment["assignment_state"] == "VOIDED"
    assert assignment["released_at"] == "2026-08-01T00:00:00.000Z"
    assert read_host(api, scenario["host"]["id"])["active_assignment_count"] == 0

    assert get_success_data(
        api.get_package_product(scenario["package"]["id"], COMMERCIAL_MANAGER)
    )["package_status"] == "CLOSED"
    assert read_client(api, scenario["client"]["id"])["outstanding_cents"] == 55872


# --------------------------------------------------------------------------
# Client exposure after each sale and each payment
# --------------------------------------------------------------------------


def test_client_exposure_falls_by_exactly_what_each_installment_settles(
    api: ApiClient,
) -> None:
    """Exposure walks 558720 → 391104 → 167616 as the schedule is collected.

    A fresh sale puts its whole net price on the client, because nothing has been
    paid. The 30/40/30 schedule then comes in: the first line of 167616 and the
    second of 223488 each reduce the exposure by exactly their own amount, and
    the money dimension stops at `DEPOSIT_PAID` both times because the third line
    is still outstanding.

    PRD §3.6: "The first is, across the client's bookings whose `fulfillment_status` is `RESERVED`, `ALLOCATED`, `CREDENTIALED`, `DELIVERED` or `REBOOK_PENDING`, the booking's `net_price_cents` less its `paid_cents`, floored at 0 for each booking individually."
    PRD §3.6: "Both figures are recomputed on booking creation, on cancellation, on rebooking, on installment payment, on fixture postponement, on fixture cancellation, and during the operations rollover."
    PRD §3.6: "From `UNPAID`, a payment that still leaves at least one `SCHEDULE` installment of the booking in `SCHEDULED` or `OVERDUE` moves `payment_status` to `DEPOSIT_PAID`."

    Design: Corner/state_machines/client_outstanding_reconciles_after_each_booking_and_payment
    """
    scenario = _sellable_bronze_fixture(api)
    client_id = scenario["client"]["id"]
    assert read_client(api, client_id)["outstanding_cents"] == 0

    booking = make_booking(api, client_id, scenario["package"]["id"],
                           channel="CORPORATE", units=5)
    assert booking["net_price_cents"] == 558720
    assert read_client(api, client_id)["outstanding_cents"] == 558720

    lines = installments_of(api, booking["id"])
    assert [line["amount_cents"] for line in lines] == [167616, 223488, 167616]

    pay_installment(api, lines[0]["id"], 167616)
    after_first = read_booking(api, booking["id"])
    assert after_first["paid_cents"] == 167616
    assert after_first["payment_status"] == "DEPOSIT_PAID"
    assert read_client(api, client_id)["outstanding_cents"] == 391104

    pay_installment(api, lines[1]["id"], 223488)
    after_second = read_booking(api, booking["id"])
    assert after_second["paid_cents"] == 391104
    assert after_second["payment_status"] == "DEPOSIT_PAID"
    assert read_client(api, client_id)["outstanding_cents"] == 167616


def test_a_second_sale_adds_its_whole_net_price_to_the_running_exposure(
    api: ApiClient,
) -> None:
    """Exposure is a sum over bookings, not a figure that a new sale overwrites.

    With 167616 still owing on the first sale, a second ten-unit sale at the
    larger eight-percent volume discount nets 1070880 and the client's exposure
    becomes the sum of the two remainders. Each booking contributes its own
    unpaid remainder, so the earlier collections are not lost.

    PRD §3.6: "A client's `outstanding_cents` is the sum of two parts."
    PRD §3.6: "The first is, across the client's bookings whose `fulfillment_status` is `RESERVED`, `ALLOCATED`, `CREDENTIALED`, `DELIVERED` or `REBOOK_PENDING`, the booking's `net_price_cents` less its `paid_cents`, floored at 0 for each booking individually."

    Design: Corner/state_machines/client_outstanding_reconciles_after_each_booking_and_payment
    """
    scenario = _sellable_bronze_fixture(api)
    client_id = scenario["client"]["id"]
    first = make_booking(api, client_id, scenario["package"]["id"],
                         channel="CORPORATE", units=5)
    lines = installments_of(api, first["id"])
    pay_installment(api, lines[0]["id"], 167616)
    pay_installment(api, lines[1]["id"], 223488)
    assert read_client(api, client_id)["outstanding_cents"] == 167616

    second = make_booking(api, client_id, scenario["package"]["id"],
                          channel="CORPORATE", units=10)

    assert_fraction_4dp(second["volume_discount_pct"], 0.0800)
    assert second["net_price_cents"] == 1070880
    assert read_client(api, client_id)["outstanding_cents"] == 1238496

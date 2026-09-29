"""Field-level contracts of the twelve collections that sit at the API root.

Each probe here pins what a create call answers with, what a read gives back,
how a list page counts, which omitted inputs acquire a declared default, which
values are refused before anything is written, and which creation-time values
survive the lifecycle actions that move their computed neighbours.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    CLIENT_SERVICE_AGENT,
    COMMERCIAL_MANAGER,
    ERR_BOOKING_NOT_FOUND,
    ERR_BUILD_NOT_FOUND,
    ERR_CLIENT_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_HOST_NOT_FOUND,
    ERR_INVALID_PACKAGE_STATE,
    ERR_INVALID_REQUEST,
    ERR_PACKAGE_NOT_FOUND,
    FINANCE_CONTROLLER,
    NON_EXISTENT_UUID,
    OPERATIONS_MANAGER,
    RIGHTS_MANAGER,
    USER_COMMERCIAL_DIRECTOR,
    USER_RIGHTS_MANAGER,
    ApiClient,
    CANONICAL_EVENT_DATE,
    CANONICAL_EVENT_NAME,
    CANONICAL_HOST_LANGUAGES,
    CANONICAL_HOST_NAME,
    CANONICAL_RIGHTS_HOLDER,
    CANONICAL_SPORT,
    CANONICAL_VENUE,
    CANONICAL_ZONES,
    add_component,
    allocate_booking,
    assert_bare_uuid,
    assert_common_fields,
    assert_deal_position,
    assert_fraction_4dp,
    assert_list_page,
    assert_object_envelope,
    assert_total_count,
    assert_utc_millis,
    commit_deal,
    confirm_tranche,
    event_payload,
    get_success_data,
    hospitality_build_payload,
    host_assignment_payload,
    ids_of,
    make_block,
    make_booking,
    make_bronze_package,
    make_client,
    make_deal,
    make_event,
    make_published_bronze_package,
    make_tranche,
    package_component_payload,
    read_booking,
    read_client,
    reset_clock,
    rights_deal_payload,
    set_clock,
    validate_error,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"


# --------------------------------------------------------------------------
# Local scenario builders
# --------------------------------------------------------------------------


def _twenty_unit_ticket_deal(api: ApiClient) -> Dict[str, Any]:
    """One fixture carrying a 20-unit TICKET deal that guarantees all 20 units.

    At 8000 cents a unit the guarantee is the whole contract, so the deal's
    exposure figures are short literals: nothing released, twenty short.
    """
    reset_clock(api)
    event = make_event(api)
    created = make_deal(
        api,
        event["id"],
        contracted_units=20,
        guaranteed_minimum_units=20,
        unit_cost_cents=8000,
    )
    return {"event": event, "created": created}


def _committed_twenty_unit_ticket_deal(api: ApiClient) -> Dict[str, Any]:
    scenario = _twenty_unit_ticket_deal(api)
    scenario["committed"] = commit_deal(api, scenario["created"]["id"])
    return scenario


def _deal_with_three_pending_tranches(api: ApiClient) -> Dict[str, Any]:
    """A committed 20-unit deal carrying three PENDING five-unit promises."""
    scenario = _committed_twenty_unit_ticket_deal(api)
    deal_id = scenario["created"]["id"]
    scenario["tranches"] = [
        make_tranche(api, deal_id, promised_units=5, promised_release_at=promised_at)
        for promised_at in (
            "2026-09-01T00:00:00.000Z",
            "2026-10-01T00:00:00.000Z",
            "2026-11-01T00:00:00.000Z",
        )
    ]
    return scenario


def _draft_bronze_package(api: ApiClient) -> Dict[str, Any]:
    """One fixture with one DRAFT BRONZE package and no component lines yet."""
    reset_clock(api)
    event = make_event(api)
    package = make_bronze_package(api, event["id"])
    return {"event": event, "package": package}


# ==========================================================================
# Registering a fixture
# ==========================================================================


def test_registering_a_fixture_opens_it_with_every_declared_default(
    api: ApiClient, clock: str,
) -> None:
    """The 201 body pins every field the caller did not supply.

    The fixture opens SCHEDULED with a zero postponement count, a zero risk
    score and a NORMAL posture, and both date fields stay unset —
    `original_event_date` is null rather than a copy of `event_date`, because
    only a postponement ever writes it.

    PRD §3.1: "A newly registered fixture opens in `SCHEDULED` with
    `postponement_count` at 0, `fulfillment_risk_score` at 0, `risk_posture` at
    `NORMAL`, and both `original_event_date` and `rebook_deadline_at` unset."

    Design: Corner/entities/create_event_returns_201_with_every_declared_default
    """
    response = api.create_event(event_payload(), RIGHTS_MANAGER)

    data = get_success_data(response, 201)
    assert response.status_code == 201
    assert_object_envelope(response)
    assert data["status"] == "SCHEDULED"
    assert data["postponement_count"] == 0
    assert data["fulfillment_risk_score"] == 0
    assert data["risk_posture"] == "NORMAL"
    assert data["original_event_date"] is None
    assert data["rebook_deadline_at"] is None
    assert_common_fields(data, expected_version=1)


def test_the_registered_fixture_echoes_its_inputs_and_reads_back_identically(
    api: ApiClient, clock: str,
) -> None:
    """Every supplied field comes back unchanged, zone order included.

    The five declared inputs are echoed byte-for-byte in the creation body, and
    the subsequent read of the same fixture returns the identical values rather
    than a normalised or re-ordered copy of them.

    PRD §3.1: "A `RightsManager` registers one by supplying its public `name`,
    its `sport` — one of `FOOTBALL`, `BASKETBALL`, `MOTORSPORT`, `TENNIS` or
    `RUGBY` — the `venue_name` hosting it, the `hospitality_zone_codes` inside
    that venue that may host a build-out, and the scheduled kick-off instant as
    `event_date`."

    Design: Corner/entities/create_event_returns_201_with_every_declared_default
    """
    created = get_success_data(api.create_event(event_payload(), RIGHTS_MANAGER), 201)

    assert created["name"] == CANONICAL_EVENT_NAME
    assert created["sport"] == CANONICAL_SPORT
    assert created["venue_name"] == CANONICAL_VENUE
    assert created["hospitality_zone_codes"] == CANONICAL_ZONES
    assert created["event_date"] == CANONICAL_EVENT_DATE

    stored = get_success_data(api.get_event(created["id"], RIGHTS_MANAGER), 200)
    for field in (
        "id",
        "name",
        "sport",
        "venue_name",
        "hospitality_zone_codes",
        "event_date",
        "status",
        "postponement_count",
        "fulfillment_risk_score",
        "risk_posture",
        "original_event_date",
        "rebook_deadline_at",
        "created_at",
        "version",
    ):
        assert stored[field] == created[field], f"{field} changed between write and read"


# ==========================================================================
# Reading a committed rights deal
# ==========================================================================


def test_a_committed_deal_reads_back_as_the_stored_post_commit_row(
    api: ApiClient,
) -> None:
    """The read returns the persisted commitment, not a re-derived create body.

    Commitment stamps the acting rights manager on the deal and recomputes the
    liability, so the FinanceController's later read sees deal_status COMMITTED,
    a liability of 20 * round_half_up(8000 * 0.60) == 96000 and
    committed_by_user_id naming the committing operator rather than the reader.

    PRD §3.1: "Committing the deal — permitted only from `DRAFT`, and only while
    the fixture is still `SCHEDULED`, `POSTPONED` or `RESCHEDULED` — advances
    `deal_status` to `COMMITTED`, stamps `committed_by_user_id` with the acting
    `X-User-ID`, and is the moment the provider takes on the guaranteed-minimum
    liability."

    Design: Corner/entities/get_rights_deal_returns_the_stored_committed_representation
    """
    scenario = _committed_twenty_unit_ticket_deal(api)
    deal_id = scenario["created"]["id"]

    stored = get_success_data(api.get_rights_deal(deal_id, FINANCE_CONTROLLER), 200)

    assert_deal_position(stored, released=0, shortfall=20, liability=96000,
                         status="COMMITTED", unallocated=0)
    assert stored["committed_by_user_id"] == USER_RIGHTS_MANAGER
    assert stored["settled_at"] is None
    assert_common_fields(stored, expected_version=2)


def test_the_pre_commit_deal_opens_at_zero_and_the_contract_terms_are_echoed(
    api: ApiClient,
) -> None:
    """Creation answers DRAFT with a zero liability and version 1.

    The same row read after the commit still carries the contract terms exactly
    as they were bought — fixture, holder, inventory type, contracted units,
    guarantee and unit cost — so only the exposure fields and the audit stamp
    moved.

    PRD §3.1: "A fresh acquisition opens in `DRAFT` with `released_units`,
    `shortfall_units`, `unallocated_units` and `minimum_liability_cents` all at 0
    and with `committed_by_user_id` and `settled_at` unset."

    Design: Corner/entities/get_rights_deal_returns_the_stored_committed_representation
    """
    scenario = _twenty_unit_ticket_deal(api)
    created = scenario["created"]

    assert_deal_position(created, released=0, shortfall=0, liability=0,
                         status="DRAFT", unallocated=0)
    assert created["committed_by_user_id"] is None
    assert_common_fields(created, expected_version=1)

    commit_deal(api, created["id"])
    stored = get_success_data(api.get_rights_deal(created["id"], FINANCE_CONTROLLER), 200)

    assert stored["event_id"] == scenario["event"]["id"]
    assert stored["rights_holder_name"] == CANONICAL_RIGHTS_HOLDER
    assert stored["inventory_type"] == "TICKET"
    assert stored["contracted_units"] == 20
    assert stored["guaranteed_minimum_units"] == 20
    assert stored["unit_cost_cents"] == 8000


# ==========================================================================
# Listing release tranches
# ==========================================================================


def test_release_tranche_pages_carry_the_filtered_total_and_the_has_more_flag(
    api: ApiClient,
) -> None:
    """Three tranches read back through two pages of size two.

    Both pages report total_count 3 — the count of every row matching the
    rights_deal_id filter before the window is applied — and has_more flips from
    true to false on the page that reaches the last row, so the flag is derived
    from the window's position within the total rather than from the page being
    full.

    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` counts every record
    matching the filter before the page window is applied."

    Design: Corner/entities/list_release_tranches_paginates_with_total_count_and_has_more
    """
    scenario = _deal_with_three_pending_tranches(api)
    deal_id = scenario["created"]["id"]

    first = api.list_release_tranches(
        RIGHTS_MANAGER, {"rights_deal_id": deal_id, "limit": 2, "offset": 0}
    )
    second = api.list_release_tranches(
        RIGHTS_MANAGER, {"rights_deal_id": deal_id, "limit": 2, "offset": 2}
    )

    page_one = assert_list_page(first, expected_total=3, expected_rows=2,
                                expected_limit=2, expected_offset=0,
                                expected_has_more=True)
    page_two = assert_list_page(second, expected_total=3, expected_rows=1,
                                expected_limit=2, expected_offset=2,
                                expected_has_more=False)

    returned = ids_of(page_one) + ids_of(page_two)
    assert len(set(returned)) == 3, "the two pages must not repeat a row"
    assert set(returned) == {tranche["id"] for tranche in scenario["tranches"]}
    for row in page_one + page_two:
        assert row["rights_deal_id"] == deal_id
        assert row["tranche_state"] == "PENDING"
        assert row["promised_units"] == 5
        assert row["confirmed_units"] == 0


def test_the_tranche_state_filter_composes_with_the_pagination_counters(
    api: ApiClient,
) -> None:
    """A filter that matches nothing answers total_count 0 with an empty page.

    All three promises are still PENDING, so filtering the same deal's tranches
    on CONFIRMED leaves no rows at all, while filtering on PENDING returns all
    three — the two optional filters combine conjunctively and the counter
    follows the filter rather than the collection.

    PRD §2.3: "Every filter is optional and filters combine conjunctively."

    Design: Corner/entities/list_release_tranches_paginates_with_total_count_and_has_more
    """
    scenario = _deal_with_three_pending_tranches(api)
    deal_id = scenario["created"]["id"]

    confirmed = api.list_release_tranches(
        RIGHTS_MANAGER, {"rights_deal_id": deal_id, "tranche_state": "CONFIRMED"}
    )
    pending = api.list_release_tranches(
        RIGHTS_MANAGER, {"rights_deal_id": deal_id, "tranche_state": "PENDING"}
    )

    assert assert_list_page(confirmed, expected_total=0, expected_rows=0) == []
    assert_list_page(pending, expected_total=3, expected_rows=3,
                     expected_has_more=False)


# ==========================================================================
# A component line's required fields
# ==========================================================================


def test_a_component_line_without_its_markup_is_rejected_and_writes_nothing(
    api: ApiClient,
) -> None:
    """A missing `markup_pct` is a malformed request, not a zero markup.

    The line declares its markup explicitly, so omitting it is rejected on
    request shape with a human-readable message, and the rejection leaves no
    partial row behind: the package still owns no component lines at all.

    PRD §3.4: "Each line names its package through `package_product_id`,
    declares a `component_type` of `TICKET`, `HOTEL`, `TRANSPORT`, `EXPERIENCE`
    or `CATERING`, carries a human-readable `descriptor`, a `quantity` of at
    least 1 units of that component per package unit, a `unit_cost_cents` of at
    least 0, a `markup_pct` between 0 and 5 inclusive expressed as a fraction to
    four decimal places, and a `sequence_no` of at least 1 that must be unique
    within the package."

    Design: Corner/entities/create_package_component_missing_markup_pct_returns_invalid_request
    """
    scenario = _draft_bronze_package(api)
    package_id = scenario["package"]["id"]
    payload = package_component_payload(package_id)
    payload.pop("markup_pct")

    response = api.create_package_component(payload, COMMERCIAL_MANAGER)

    body = validate_error(response, ERR_INVALID_REQUEST, 400)
    assert isinstance(body["message"], str) and body["message"]
    assert_total_count(
        api.list_package_components(COMMERCIAL_MANAGER,
                                    {"package_product_id": package_id}),
        0,
    )


def test_the_same_line_with_its_markup_present_prices_and_leaves_the_package_alone(
    api: ApiClient,
) -> None:
    """The retry with `markup_pct` 0.2000 lands on the still-free ordinal.

    The accepted line prices itself at once — 2 * 50000 == 100000 of cost and
    round_half_up(100000 * 1.2000) == 120000 of sell price — which shows the
    earlier rejection was about the field's presence and not its value, since a
    defaulted zero markup would have priced the line at 100000. The parent
    package's own money fields stay at their opening zeros.

    PRD §3.4: "When a line is created its own `line_cost_cents` and
    `line_price_cents` are computed there and then, but the parent package's
    cost, subtotal, list price and margin are deliberately *not* refreshed —
    those fields only ever move when the pricing pass runs."

    Design: Corner/entities/create_package_component_missing_markup_pct_returns_invalid_request
    """
    scenario = _draft_bronze_package(api)
    package_id = scenario["package"]["id"]
    rejected = package_component_payload(package_id)
    rejected.pop("markup_pct")
    validate_error(api.create_package_component(rejected, COMMERCIAL_MANAGER),
                   ERR_INVALID_REQUEST, 400)

    response = api.create_package_component(
        package_component_payload(package_id), COMMERCIAL_MANAGER
    )

    line = get_success_data(response, 201)
    assert response.status_code == 201
    assert line["sequence_no"] == 1
    assert line["line_cost_cents"] == 100000
    assert line["line_price_cents"] == 120000

    package = get_success_data(api.get_package_product(package_id, COMMERCIAL_MANAGER), 200)
    assert package["package_status"] == "DRAFT"
    assert package["base_cost_cents"] == 0
    assert package["component_price_subtotal_cents"] == 0
    assert package["list_price_cents"] == 0
    assert_fraction_4dp(package["margin_pct"], 0.0)


# ==========================================================================
# Omitted optional inputs
# ==========================================================================


def test_a_package_skeleton_without_its_optional_inputs_takes_the_declared_defaults(
    api: ApiClient, clock: str,
) -> None:
    """hotel_nights 0, transport_included false and a 0.25 margin floor.

    The floor is the consequential one: it defaults to 0.25 rather than 0, which
    is high enough to block publishing a package whose computed margin comes out
    at 0.1667, so a wrong default is observable rather than cosmetic.

    PRD §3.4: "Three inputs are optional: `hotel_nights`, the hotel nights
    bundled per package unit, which defaults to 0; `transport_included`, a flag
    for bundled ground transportation, which defaults to false; and
    `min_margin_pct`, the floor the package's computed margin must clear before
    it may go on sale, which defaults to 0.25."

    Design: Corner/entities/omitted_optional_inputs_apply_their_declared_defaults
    """
    event = make_event(api)

    response = api.create_package_product(
        {
            "event_id": event["id"],
            "name": "Bare Bones Package",
            "tier": "BRONZE",
            "tickets_per_package": 2,
        },
        COMMERCIAL_MANAGER,
    )

    package = get_success_data(response, 201)
    assert package["hotel_nights"] == 0
    assert package["transport_included"] is False
    assert_fraction_4dp(package["min_margin_pct"], 0.2500)
    assert package["package_status"] == "DRAFT"

    listed = assert_total_count(
        api.list_package_products(COMMERCIAL_MANAGER, {"event_id": event["id"]}), 1
    )
    assert listed[0]["id"] == package["id"]
    assert_fraction_4dp(listed[0]["min_margin_pct"], 0.2500)


def test_a_client_registered_without_a_credit_limit_carries_a_zero_limit(
    api: ApiClient, clock: str,
) -> None:
    """An omitted `credit_limit_cents` means no headroom at all, not unlimited.

    The buyer opens ACTIVE with nothing outstanding and nothing overdue, and the
    stored limit is 0, which is what later makes any priced booking for this
    client exceed the exposure the provider will carry.

    PRD §3.5: "A `ClientServiceAgent` registers the buyer, supplying a `name`, a
    `client_type` of `INDIVIDUAL`, `CORPORATE` or `TRAVEL_PARTNER`, and
    optionally a `credit_limit_cents` that defaults to 0 and caps the
    outstanding exposure the provider will carry."

    Design: Corner/entities/omitted_optional_inputs_apply_their_declared_defaults
    """
    response = api.create_client(
        {"name": "Walk-in Buyer", "client_type": "INDIVIDUAL"}, CLIENT_SERVICE_AGENT
    )

    client = get_success_data(response, 201)
    assert client["credit_limit_cents"] == 0
    assert client["client_status"] == "ACTIVE"
    assert client["outstanding_cents"] == 0
    assert client["overdue_installment_count"] == 0

    stored = read_client(api, client["id"])
    assert stored["credit_limit_cents"] == 0
    assert stored["client_type"] == "INDIVIDUAL"


def test_a_host_registered_without_a_capacity_may_hold_one_assignment(
    api: ApiClient, clock: str,
) -> None:
    """An omitted `max_concurrent_bookings` defaults to exactly one.

    One is neither zero nor unlimited, which is what makes a second overlapping
    shift on the same host a capacity violation, and the new host starts with no
    active assignments to its name.

    PRD §3.7: "An `OperationsManager` supplies the host's `full_name` as it will
    be printed on client itineraries, a `languages` array of language codes the
    host services clients in, and optionally `max_concurrent_bookings`, the
    number of assignments that may overlap on that host at any single instant,
    which defaults to 1 and must be at least 1."

    Design: Corner/entities/omitted_optional_inputs_apply_their_declared_defaults
    """
    response = api.create_on_site_host(
        {"full_name": CANONICAL_HOST_NAME, "languages": list(CANONICAL_HOST_LANGUAGES)},
        OPERATIONS_MANAGER,
    )

    host = get_success_data(response, 201)
    assert host["max_concurrent_bookings"] == 1
    assert host["active_assignment_count"] == 0

    stored = get_success_data(api.get_on_site_host(host["id"], OPERATIONS_MANAGER), 200)
    assert stored["max_concurrent_bookings"] == 1
    assert stored["full_name"] == CANONICAL_HOST_NAME
    assert stored["languages"] == list(CANONICAL_HOST_LANGUAGES)


# ==========================================================================
# The deal's four computed exposure fields
# ==========================================================================


def test_the_deals_exposure_fields_open_at_zero_and_are_priced_by_the_commitment(
    api: ApiClient,
) -> None:
    """None of the four exposure figures can be supplied by the caller.

    They open at zero on a body that could not have set them, and the commitment
    is what first prices them: with nothing released against a 20-unit
    guarantee the shortfall is the whole guarantee, and the liability is
    20 * round_half_up(8000 * 0.60) == 96000.

    PRD §3.1: "Third, the shortfall unit cost is obtained by taking sixty
    percent of `unit_cost_cents` and rounding that single per-unit figure
    half-up to a whole cent, and `minimum_liability_cents` is then
    `released_units` multiplied by `unit_cost_cents`, plus `shortfall_units`
    multiplied by that already-rounded shortfall unit cost."

    Design: Corner/entities/rights_deal_exposure_fields_are_computed_not_supplied
    """
    scenario = _twenty_unit_ticket_deal(api)

    assert_deal_position(scenario["created"], released=0, shortfall=0, liability=0,
                         status="DRAFT", unallocated=0)

    committed = commit_deal(api, scenario["created"]["id"])

    assert_deal_position(committed, released=0, shortfall=20, liability=96000,
                         status="COMMITTED", unallocated=0)


def test_a_full_confirmation_derives_the_exposure_fields_from_the_tranche_ledger(
    api: ApiClient,
) -> None:
    """Twenty released units against a 20-unit guarantee leave no shortfall.

    Confirming the whole promise fills the contract, so the deal reads
    FULLY_RELEASED with shortfall 0 at the inclusive boundary, and the liability
    collapses onto the released term: 20 * 8000 == 160000. No allocation block
    exists to absorb the release, so the whole distributable quantity is parked
    in `unallocated_units` with no error.

    PRD §3.3: "Where the candidate set is empty — a deal with released units and
    no live blocks — the entire distributable quantity is simply recorded in
    `unallocated_units` and no error is raised."

    Design: Corner/entities/rights_deal_exposure_fields_are_computed_not_supplied
    """
    scenario = _committed_twenty_unit_ticket_deal(api)
    deal_id = scenario["created"]["id"]
    tranche = make_tranche(api, deal_id, promised_units=20)

    confirmed = confirm_tranche(api, tranche["id"], deal_id, 20)

    assert confirmed["tranche_state"] == "CONFIRMED"
    assert confirmed["confirmed_units"] == 20

    deal = get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER), 200)
    assert_deal_position(deal, released=20, shortfall=0, liability=160000,
                         status="FULLY_RELEASED", unallocated=20)


# ==========================================================================
# The four system-managed properties
# ==========================================================================


def test_a_fixtures_system_fields_are_minted_by_the_server_at_the_logical_clock(
    api: ApiClient, clock: str,
) -> None:
    """A bare UUID, two millisecond timestamps in the declared format, version 1.

    The identifier carries no type prefix, so it is a plain 36-character UUID
    usable as a pure identifier, both timestamps are minted by the server in the
    ISO 8601 UTC format with three fractional digits, and the counter opens at 1.

    PRD §2.4: "`id` (string): a server-minted UUID. It carries no type prefix and
    is never supplied by the client."

    PRD §2.4: "`version` (integer): a monotonically increasing counter that begins
    at 1 on creation and increments by one on every mutation of the record."

    Design: Corner/entities/system_fields_are_server_minted_and_version_advances_on_mutation
    """
    created = get_success_data(api.create_event(event_payload(), RIGHTS_MANAGER), 201)

    assert_bare_uuid(created["id"])
    assert_utc_millis(created["created_at"])
    assert_utc_millis(created["updated_at"])
    assert created["version"] == 1


def test_a_postponement_freezes_the_identity_fields_and_refreshes_updated_at(
    api: ApiClient, clock: str,
) -> None:
    """The transition moves the mutation stamp and nothing else about identity.

    With the clock advanced to 2026-08-02T09:30:00Z the postponement leaves `id`
    and `created_at` exactly as they were minted and refreshes `updated_at`, while
    the transition itself lands: the fixture is POSTPONED, the pre-transition
    kick-off is preserved in `original_event_date`, and the rebooking window
    closes twenty-one days after the clock.

    PRD §3.8: "The fixture stamps `original_event_date` with its current
    `event_date` — but only when `original_event_date` is still unset, so the
    first-ever scheduled kick-off is preserved and never overwritten by a later
    postponement."

    PRD §2.4: "`updated_at` (string): an ISO 8601 UTC timestamp in the same
    format, refreshed on every mutation of the record — including mutations the
    client did not request directly, such as a derived aggregate being recomputed
    by a cascade."

    Design: Corner/entities/system_fields_are_server_minted_and_version_advances_on_mutation
    """
    created = get_success_data(api.create_event(event_payload(), RIGHTS_MANAGER), 201)
    set_clock(api, "2026-08-02T09:30:00Z")

    postponed = get_success_data(
        api.postpone_event(created["id"], {}, RIGHTS_MANAGER), 200
    )

    assert postponed["id"] == created["id"]
    assert postponed["created_at"] == created["created_at"]
    assert_utc_millis(postponed["updated_at"])
    assert postponed["updated_at"] >= created["updated_at"]
    assert postponed["status"] == "POSTPONED"
    assert postponed["postponement_count"] == 1
    assert postponed["original_event_date"] == CANONICAL_EVENT_DATE
    assert postponed["event_date"] == CANONICAL_EVENT_DATE
    assert postponed["rebook_deadline_at"] == "2026-08-23T09:30:00.000Z"


def test_the_whole_postponement_advances_the_fixture_version_exactly_once(
    api: ApiClient, clock: str,
) -> None:
    """One transition is one increment, cascade included.

    The postponement runs a multi-hop cascade rooted on this very row, and the
    counter still moves from 1 to 2 — it neither stays put nor advances twice —
    and the read of the same fixture reports the same figure.

    PRD §2.4: "`version` (integer): a monotonically increasing counter that
    begins at 1 on creation and increments by one on every mutation of the
    record."

    Design: Corner/entities/system_fields_are_server_minted_and_version_advances_on_mutation
    """
    created = get_success_data(api.create_event(event_payload(), RIGHTS_MANAGER), 201)
    assert created["version"] == 1
    set_clock(api, "2026-08-02T09:30:00Z")

    postponed = get_success_data(
        api.postpone_event(created["id"], {}, RIGHTS_MANAGER), 200
    )

    assert postponed["version"] == 2
    assert get_success_data(api.get_event(created["id"], RIGHTS_MANAGER), 200)["version"] == 2


# ==========================================================================
# Enumerations and integer bounds
# ==========================================================================


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"inventory_type": "SUITE"}, id="undeclared_inventory_type"),
        pytest.param({"contracted_units": 0, "guaranteed_minimum_units": 0},
                     id="contracted_units_below_one"),
        pytest.param({"unit_cost_cents": 0}, id="unit_cost_cents_below_one"),
    ],
)
def test_an_undeclared_enum_or_an_out_of_bound_quantity_is_refused_on_a_deal(
    api: ApiClient, clock: str, overrides: Dict[str, Any],
) -> None:
    """Three structurally different constraint breaches, one rejection code.

    An inventory type outside the declared set, a contracted quantity of zero
    where the floor is 1 and a zero unit cost where the floor is 1 are all
    refused on request shape, and none of them leaves a row behind.

    PRD §2.7: "Body parses, every required field is present, every value matches
    its declared type, every enumerated value is a declared member, every integer
    bound holds, `sequence_no` is unique within its parent package, a build's
    `service_window_end` is strictly after its `service_window_start`, a shift's
    `shift_end` is strictly after its `shift_start`, `hospitality_zone_codes` is
    a non-empty array of unique strings, and any supplied `limit` lies between 1
    and 100 inclusive — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/enum_and_numeric_constraints_are_rejected_before_persistence
    """
    event = make_event(api)
    payload = rights_deal_payload(event["id"], **overrides)

    response = api.create_rights_deal(payload, RIGHTS_MANAGER)

    validate_error(response, ERR_INVALID_REQUEST, 400)
    assert_total_count(
        api.list_rights_deals(RIGHTS_MANAGER, {"event_id": event["id"]}), 0
    )


def test_a_fixture_with_an_empty_zone_array_is_refused(
    api: ApiClient, clock: str,
) -> None:
    """The zone list is the definitive set of dressable places, so it cannot be
    empty.

    A fixture registered with no hospitality zone codes at all is rejected on
    request shape, and the collection stays empty afterwards.

    PRD §3.1: "The zone codes arrive as a non-empty array of unique strings and
    are the definitive list of places the operations team may later dress."

    Design: Corner/entities/enum_and_numeric_constraints_are_rejected_before_persistence
    """
    response = api.create_event(
        event_payload(name="Zoneless Fixture", sport="TENNIS",
                      venue_name="Meridian Arena", hospitality_zone_codes=[],
                      event_date="2027-03-01T12:00:00.000Z"),
        RIGHTS_MANAGER,
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)
    validate_error(api.get_event(NON_EXISTENT_UUID, RIGHTS_MANAGER),
                   ERR_EVENT_NOT_FOUND, 404)


def test_the_smallest_legal_quantities_are_accepted_and_nothing_rejected_persists(
    api: ApiClient, clock: str,
) -> None:
    """Contracted 1, guaranteed 0 and a unit cost of 1 all sit inside the bounds.

    The floors are inclusive, so the smallest legal acquisition is accepted after
    three rejected bodies on the same fixture, and the fixture then owns exactly
    one deal — proving none of the refused requests was written — while its own
    zone list is untouched.

    PRD §3.1: "It records `contracted_units`, at least 1, as the quantity the
    holder has undertaken to deliver, and `guaranteed_minimum_units`, at least 0,
    as the quantity the provider must pay for whether or not it is ever released
    or sold."

    Design: Corner/entities/enum_and_numeric_constraints_are_rejected_before_persistence
    """
    event = make_event(api)
    for overrides in (
        {"inventory_type": "SUITE"},
        {"contracted_units": 0, "guaranteed_minimum_units": 0},
        {"unit_cost_cents": 0},
    ):
        validate_error(
            api.create_rights_deal(rights_deal_payload(event["id"], **overrides),
                                   RIGHTS_MANAGER),
            ERR_INVALID_REQUEST, 400,
        )

    response = api.create_rights_deal(
        rights_deal_payload(event["id"], inventory_type="ACCESS_EXPERIENCE",
                            contracted_units=1, guaranteed_minimum_units=0,
                            unit_cost_cents=1),
        RIGHTS_MANAGER,
    )

    deal = get_success_data(response, 201)
    assert deal["inventory_type"] == "ACCESS_EXPERIENCE"
    assert deal["contracted_units"] == 1
    assert deal["guaranteed_minimum_units"] == 0
    assert deal["unit_cost_cents"] == 1

    rows = assert_total_count(
        api.list_rights_deals(RIGHTS_MANAGER, {"event_id": event["id"]}), 1
    )
    assert ids_of(rows) == [deal["id"]]
    assert get_success_data(api.get_event(event["id"], RIGHTS_MANAGER), 200)[
        "hospitality_zone_codes"
    ] == CANONICAL_ZONES


# ==========================================================================
# A build's service window
# ==========================================================================


@pytest.mark.parametrize(
    "service_window_end",
    [
        pytest.param("2027-02-01T09:00:00.000Z", id="zero_length_window"),
        pytest.param("2027-02-01T08:59:59.999Z", id="inverted_window"),
    ],
)
def test_a_service_window_that_is_not_strictly_ordered_is_refused(
    api: ApiClient, clock: str, service_window_end: str,
) -> None:
    """The window predicate is strict, so a zero-length window fails too.

    A window that ends at precisely the instant it starts is rejected exactly as
    an inverted one is, and neither attempt occupies the zone.

    PRD §3.7: "The occupancy runs from `service_window_start` to
    `service_window_end`, the latter strictly after the former, and it may not
    collide with another live occupancy of the same zone on the same fixture."

    Design: Corner/entities/hospitality_build_window_must_be_strictly_ordered
    """
    event = make_event(api)
    payload = hospitality_build_payload(
        event["id"],
        service_window_start="2027-02-01T09:00:00.000Z",
        service_window_end=service_window_end,
    )

    response = api.create_hospitality_build(payload, OPERATIONS_MANAGER)

    validate_error(response, ERR_INVALID_REQUEST, 400)
    assert_total_count(
        api.list_hospitality_builds(OPERATIONS_MANAGER, {"event_id": event["id"]}), 0
    )


def test_a_one_millisecond_window_with_zero_cost_and_headcount_lines_is_planned(
    api: ApiClient, clock: str,
) -> None:
    """The smallest strictly-ordered window is accepted on the same zone.

    Reusing the zone and the start instant of the two refused attempts proves the
    rejections were about ordering alone. The accepted build opens PLANNED with a
    total cost of 0 + 0 + 0, so a single space unit and zero catering covers,
    staff and cost lines are all legal at planning time.

    PRD §3.7: "The build's `total_cost_cents` is simply the sum of those three
    cost lines and is computed at once."

    Design: Corner/entities/hospitality_build_window_must_be_strictly_ordered
    """
    event = make_event(api)
    for bad_end in ("2027-02-01T09:00:00.000Z", "2027-02-01T08:59:59.999Z"):
        validate_error(
            api.create_hospitality_build(
                hospitality_build_payload(
                    event["id"],
                    service_window_start="2027-02-01T09:00:00.000Z",
                    service_window_end=bad_end,
                ),
                OPERATIONS_MANAGER,
            ),
            ERR_INVALID_REQUEST, 400,
        )

    response = api.create_hospitality_build(
        hospitality_build_payload(
            event["id"],
            zone_code="ZONE_A",
            service_window_start="2027-02-01T09:00:00.000Z",
            service_window_end="2027-02-01T09:00:00.001Z",
            space_units=1,
            catering_covers=0,
            staff_count=0,
            build_cost_cents=0,
            catering_cost_cents=0,
            staffing_cost_cents=0,
        ),
        OPERATIONS_MANAGER,
    )

    build = get_success_data(response, 201)
    assert build["build_state"] == "PLANNED"
    assert build["total_cost_cents"] == 0
    assert build["approved_by_user_id"] is None

    rows = assert_total_count(
        api.list_hospitality_builds(OPERATIONS_MANAGER,
                                    {"event_id": event["id"], "zone_code": "ZONE_A"}),
        1,
    )
    assert ids_of(rows) == [build["id"]]


# --------------------------------------------------------------------------
# Further scenario builders
# --------------------------------------------------------------------------


def _two_draft_packages_sharing_one_ordinal(api: ApiClient) -> Dict[str, Any]:
    """Two DRAFT packages on one fixture; the first already owns ordinal 1.

    The second package is deliberately created on the same fixture, so any
    rejection of ordinal 1 there could only come from a scope wider than the
    package it belongs to.
    """
    reset_clock(api)
    event = make_event(api)
    package_a = make_bronze_package(api, event["id"])
    package_b = make_bronze_package(api, event["id"], name="Silver Hospitality",
                                    tier="SILVER")
    first_line = add_component(api, package_a["id"])
    return {
        "event": event,
        "package_a": package_a,
        "package_b": package_b,
        "first_line": first_line,
    }


def _fixture_and_client_with_nothing_else(api: ApiClient) -> Dict[str, Any]:
    """One fixture and one client; no package, booking, build or host exists."""
    reset_clock(api)
    event = make_event(api)
    client = make_client(api)
    return {"event": event, "client": client}


def _sellable_fixture_with_a_reserved_booking(api: ApiClient) -> Dict[str, Any]:
    """A fully released 40-unit deal, a published BRONZE package and one sale.

    The deal contracts 40 units at 8000 cents and guarantees 20 of them; a
    single 40-unit tranche is confirmed in full, so the contract is met and the
    booking carries no guarantee surcharge. The 5-unit CORPORATE booking is left
    RESERVED, its money agreed at creation.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_deal(api, event["id"], contracted_units=40,
                     guaranteed_minimum_units=20, unit_cost_cents=8000)
    commit_deal(api, deal["id"])
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=40,
                       priority_rank=1)
    tranche = make_tranche(api, deal["id"], promised_units=40)
    confirm_tranche(api, tranche["id"], deal["id"], 40)
    package = make_published_bronze_package(api, event["id"])
    client = make_client(api)
    booking = make_booking(api, client["id"], package["id"], units=5)
    return {
        "event": event,
        "deal": deal,
        "block": block,
        "package": package,
        "client": client,
        "booking": booking,
    }


# ==========================================================================
# The ordinal that pins a package's rounding order
# ==========================================================================


def test_an_ordinal_already_used_inside_the_same_package_is_refused(
    api: ApiClient,
) -> None:
    """A second line at ordinal 1 on the package that already owns it is rejected.

    The ordinal has to be unique within its package because it is what makes the
    pricing order total, so the duplicate is refused on request shape and the
    package keeps its single line.

    PRD §3.4: "Each line names its package through `package_product_id`, declares
    a `component_type` of `TICKET`, `HOTEL`, `TRANSPORT`, `EXPERIENCE` or
    `CATERING`, carries a human-readable `descriptor`, a `quantity` of at least 1
    units of that component per package unit, a `unit_cost_cents` of at least 0, a
    `markup_pct` between 0 and 5 inclusive expressed as a fraction to four decimal
    places, and a `sequence_no` of at least 1 that must be unique within the
    package."

    Design: Corner/entities/duplicate_sequence_no_within_one_package_is_rejected
    """
    scenario = _two_draft_packages_sharing_one_ordinal(api)
    duplicate = package_component_payload(
        scenario["package_a"]["id"], component_type="HOTEL",
        descriptor="Five-star room night", quantity=2, unit_cost_cents=20000,
        markup_pct=0.1000, sequence_no=1,
    )

    response = api.create_package_component(duplicate, COMMERCIAL_MANAGER)

    validate_error(response, ERR_INVALID_REQUEST, 400)
    assert_total_count(
        api.list_package_components(
            COMMERCIAL_MANAGER, {"package_product_id": scenario["package_a"]["id"]}
        ),
        1,
    )


def test_the_same_ordinal_is_accepted_on_a_second_package_of_the_same_fixture(
    api: ApiClient,
) -> None:
    """Uniqueness is scoped to the package, not to the collection.

    Ordinal 1 is rejected on the package that already owns it and accepted, in
    the very next call, on a sibling package of the same fixture — the scope of
    the constraint is the parent package alone.

    PRD §2.7: "Body parses, every required field is present, every value matches
    its declared type, every enumerated value is a declared member, every integer
    bound holds, `sequence_no` is unique within its parent package, a build's
    `service_window_end` is strictly after its `service_window_start`, a shift's
    `shift_end` is strictly after its `shift_start`, `hospitality_zone_codes` is
    a non-empty array of unique strings, and any supplied `limit` lies between 1
    and 100 inclusive — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/duplicate_sequence_no_within_one_package_is_rejected
    """
    scenario = _two_draft_packages_sharing_one_ordinal(api)
    validate_error(
        api.create_package_component(
            package_component_payload(scenario["package_a"]["id"],
                                      component_type="HOTEL", sequence_no=1),
            COMMERCIAL_MANAGER,
        ),
        ERR_INVALID_REQUEST, 400,
    )

    response = api.create_package_component(
        package_component_payload(scenario["package_b"]["id"], sequence_no=1),
        COMMERCIAL_MANAGER,
    )

    sibling_line = get_success_data(response, 201)
    assert sibling_line["package_product_id"] == scenario["package_b"]["id"]
    assert sibling_line["sequence_no"] == 1
    rows = assert_total_count(
        api.list_package_components(
            COMMERCIAL_MANAGER, {"package_product_id": scenario["package_b"]["id"]}
        ),
        1,
    )
    assert ids_of(rows) == [sibling_line["id"]]


def test_the_next_free_ordinal_prices_its_own_line_and_the_refused_body_is_absent(
    api: ApiClient,
) -> None:
    """Ordinal 2 lands on the original package with its own line figures.

    The same body that was refused at ordinal 1 is accepted at ordinal 2, priced
    at once as 2 * 20000 grown by ten percent, and the original package then owns
    exactly the two accepted lines — never the refused one.

    PRD §3.4: "For each line, `line_cost_cents` is that line's `unit_cost_cents`
    multiplied by its `quantity`, and `line_price_cents` is that line cost
    multiplied by one plus the line's `markup_pct`, rounded half-up to a whole
    cent **at the line**."

    Design: Corner/entities/duplicate_sequence_no_within_one_package_is_rejected
    """
    scenario = _two_draft_packages_sharing_one_ordinal(api)
    package_a = scenario["package_a"]["id"]
    hotel_line = package_component_payload(
        package_a, component_type="HOTEL", descriptor="Five-star room night",
        quantity=2, unit_cost_cents=20000, markup_pct=0.1000, sequence_no=1,
    )
    validate_error(api.create_package_component(hotel_line, COMMERCIAL_MANAGER),
                   ERR_INVALID_REQUEST, 400)

    hotel_line["sequence_no"] = 2
    accepted = get_success_data(
        api.create_package_component(hotel_line, COMMERCIAL_MANAGER), 201
    )

    assert accepted["sequence_no"] == 2
    assert accepted["line_cost_cents"] == 40000
    assert accepted["line_price_cents"] == 44000
    rows = assert_total_count(
        api.list_package_components(COMMERCIAL_MANAGER,
                                    {"package_product_id": package_a}),
        2,
    )
    assert sorted(ids_of(rows)) == sorted(
        [scenario["first_line"]["id"], accepted["id"]]
    )


# ==========================================================================
# Foreign keys that travel in the body
# ==========================================================================


def test_an_unknown_fixture_named_in_a_deal_body_is_reported_as_a_missing_fixture(
    api: ApiClient,
) -> None:
    """The relationship is a body field and it is still resolved for existence.

    The acquisition names a fixture that does not exist, and the answer is the
    fixture's own existence code rather than a generic validation failure.

    PRD §2.8: "Relationships travel in request bodies as explicit identifiers."

    PRD §2.7: "**Existence**, resolved for path identifiers left to right and then
    for body foreign keys, in this order: fixture (`ERR_EVENT_NOT_FOUND`), rights
    deal (`ERR_RIGHTS_DEAL_NOT_FOUND`), release tranche (`ERR_TRANCHE_NOT_FOUND`),
    allocation block (`ERR_BLOCK_NOT_FOUND`), package (`ERR_PACKAGE_NOT_FOUND`),
    package component (`ERR_COMPONENT_NOT_FOUND`), client
    (`ERR_CLIENT_NOT_FOUND`), booking (`ERR_BOOKING_NOT_FOUND`), payment
    installment (`ERR_INSTALLMENT_NOT_FOUND`), hospitality build
    (`ERR_BUILD_NOT_FOUND`), on-site host (`ERR_HOST_NOT_FOUND`), host assignment
    (`ERR_ASSIGNMENT_NOT_FOUND`)."

    Design: Corner/entities/unknown_foreign_keys_in_request_bodies_are_rejected_by_priority_order
    """
    _fixture_and_client_with_nothing_else(api)
    payload = rights_deal_payload(NON_EXISTENT_UUID, contracted_units=20,
                                  guaranteed_minimum_units=20, unit_cost_cents=8000)

    response = api.create_rights_deal(payload, RIGHTS_MANAGER)

    validate_error(response, ERR_EVENT_NOT_FOUND, 404)


def test_an_unknown_package_is_reported_even_though_the_client_resolves(
    api: ApiClient,
) -> None:
    """The package sits ahead of the client in the existence order.

    The booking body carries a real client and an unknown package. The package is
    resolved first, so its code is the one returned and the client's code never
    appears.

    PRD §2.7: "**Existence**, resolved for path identifiers left to right and then
    for body foreign keys, in this order: fixture (`ERR_EVENT_NOT_FOUND`), rights
    deal (`ERR_RIGHTS_DEAL_NOT_FOUND`), release tranche (`ERR_TRANCHE_NOT_FOUND`),
    allocation block (`ERR_BLOCK_NOT_FOUND`), package (`ERR_PACKAGE_NOT_FOUND`),
    package component (`ERR_COMPONENT_NOT_FOUND`), client
    (`ERR_CLIENT_NOT_FOUND`), booking (`ERR_BOOKING_NOT_FOUND`), payment
    installment (`ERR_INSTALLMENT_NOT_FOUND`), hospitality build
    (`ERR_BUILD_NOT_FOUND`), on-site host (`ERR_HOST_NOT_FOUND`), host assignment
    (`ERR_ASSIGNMENT_NOT_FOUND`)."

    Design: Corner/entities/unknown_foreign_keys_in_request_bodies_are_rejected_by_priority_order
    """
    scenario = _fixture_and_client_with_nothing_else(api)
    payload = {
        "client_id": scenario["client"]["id"],
        "package_product_id": NON_EXISTENT_UUID,
        "channel": "CORPORATE",
        "units": 5,
    }

    response = api.create_booking(payload, CLIENT_SERVICE_AGENT)

    body = validate_error(response, ERR_PACKAGE_NOT_FOUND, 404)
    assert body["error_id"] != ERR_CLIENT_NOT_FOUND


def test_three_unknown_references_at_once_report_the_first_one_in_the_order(
    api: ApiClient,
) -> None:
    """Booking, build and host are all unknown, and the booking answers.

    The assignment body names the host first and the booking second, yet the
    declared order — booking, then build, then host — decides, so neither the
    payload order nor whichever lookup a database happens to run first can be
    what is reported.

    PRD §2.7: "**Existence**, resolved for path identifiers left to right and then
    for body foreign keys, in this order: fixture (`ERR_EVENT_NOT_FOUND`), rights
    deal (`ERR_RIGHTS_DEAL_NOT_FOUND`), release tranche (`ERR_TRANCHE_NOT_FOUND`),
    allocation block (`ERR_BLOCK_NOT_FOUND`), package (`ERR_PACKAGE_NOT_FOUND`),
    package component (`ERR_COMPONENT_NOT_FOUND`), client
    (`ERR_CLIENT_NOT_FOUND`), booking (`ERR_BOOKING_NOT_FOUND`), payment
    installment (`ERR_INSTALLMENT_NOT_FOUND`), hospitality build
    (`ERR_BUILD_NOT_FOUND`), on-site host (`ERR_HOST_NOT_FOUND`), host assignment
    (`ERR_ASSIGNMENT_NOT_FOUND`)."

    Design: Corner/entities/unknown_foreign_keys_in_request_bodies_are_rejected_by_priority_order
    """
    _fixture_and_client_with_nothing_else(api)
    payload = host_assignment_payload(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID,
        shift_start="2027-02-01T10:00:00.000Z",
        shift_end="2027-02-01T14:00:00.000Z",
    )

    response = api.create_host_assignment(payload, OPERATIONS_MANAGER)

    body = validate_error(response, ERR_BOOKING_NOT_FOUND, 404)
    assert body["error_id"] != ERR_BUILD_NOT_FOUND
    assert body["error_id"] != ERR_HOST_NOT_FOUND


def test_none_of_the_three_dangling_bodies_leaves_a_record_behind(
    api: ApiClient,
) -> None:
    """Three rejections on three collections write nothing at all.

    An unknown reference is refused before persistence, so the fixture owns no
    deal, the client owns no booking and no assignment stands.

    PRD §2.7: "**Existence**, resolved for path identifiers left to right and then
    for body foreign keys, in this order: fixture (`ERR_EVENT_NOT_FOUND`), rights
    deal (`ERR_RIGHTS_DEAL_NOT_FOUND`), release tranche (`ERR_TRANCHE_NOT_FOUND`),
    allocation block (`ERR_BLOCK_NOT_FOUND`), package (`ERR_PACKAGE_NOT_FOUND`),
    package component (`ERR_COMPONENT_NOT_FOUND`), client
    (`ERR_CLIENT_NOT_FOUND`), booking (`ERR_BOOKING_NOT_FOUND`), payment
    installment (`ERR_INSTALLMENT_NOT_FOUND`), hospitality build
    (`ERR_BUILD_NOT_FOUND`), on-site host (`ERR_HOST_NOT_FOUND`), host assignment
    (`ERR_ASSIGNMENT_NOT_FOUND`)."

    Design: Corner/entities/unknown_foreign_keys_in_request_bodies_are_rejected_by_priority_order
    """
    scenario = _fixture_and_client_with_nothing_else(api)
    event_id = scenario["event"]["id"]
    client_id = scenario["client"]["id"]

    validate_error(
        api.create_rights_deal(rights_deal_payload(NON_EXISTENT_UUID), RIGHTS_MANAGER),
        ERR_EVENT_NOT_FOUND, 404,
    )
    validate_error(
        api.create_booking(
            {"client_id": client_id, "package_product_id": NON_EXISTENT_UUID,
             "channel": "CORPORATE", "units": 5},
            CLIENT_SERVICE_AGENT,
        ),
        ERR_PACKAGE_NOT_FOUND, 404,
    )
    validate_error(
        api.create_host_assignment(
            host_assignment_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                                    NON_EXISTENT_UUID),
            OPERATIONS_MANAGER,
        ),
        ERR_BOOKING_NOT_FOUND, 404,
    )

    assert_total_count(api.list_rights_deals(RIGHTS_MANAGER, {"event_id": event_id}), 0)
    assert_total_count(api.list_bookings(CLIENT_SERVICE_AGENT, {"client_id": client_id}), 0)
    assert_total_count(
        api.list_host_assignments(OPERATIONS_MANAGER, {"assignment_state": "ASSIGNED"}), 0
    )


# ==========================================================================
# Creation-time values that no endpoint ever takes back
# ==========================================================================


def test_committing_inventory_rewrites_the_allocation_field_and_freezes_the_rest(
    api: ApiClient,
) -> None:
    """The allocation touches the same row and leaves every agreed value alone.

    Allocation writes `allocation_block_id` and moves the booking to ALLOCATED.
    Everything settled when the sale was struck — the units, the channel, the two
    parties, the gross 600000 and the agreed net 558720, and the creation stamp —
    reads back byte-identical, and only the mutation counter moves.

    PRD §3.5: "On success the booking moves `RESERVED → ALLOCATED`, its
    `allocation_block_id` is set, the block's `committed_units` increases by the
    booking's `units` multiplied by `tickets_per_package`, the block's `version`
    increases by one, and the fixture's `fulfillment_risk_score` and
    `risk_posture` are recomputed."

    Design: Corner/entities/input_fields_are_write_once_because_no_endpoint_ever_takes_them_back
    """
    scenario = _sellable_fixture_with_a_reserved_booking(api)
    created = scenario["booking"]
    assert created["fulfillment_status"] == "RESERVED"
    assert created["gross_price_cents"] == 600000
    assert created["net_price_cents"] == 558720

    allocated = allocate_booking(api, created["id"], scenario["block"]["id"])

    assert allocated["allocation_block_id"] == scenario["block"]["id"]
    assert allocated["fulfillment_status"] == "ALLOCATED"

    booking = read_booking(api, created["id"])
    assert booking["units"] == created["units"] == 5
    assert booking["channel"] == created["channel"] == "CORPORATE"
    assert booking["client_id"] == created["client_id"]
    assert booking["package_product_id"] == created["package_product_id"]
    assert booking["gross_price_cents"] == created["gross_price_cents"] == 600000
    assert booking["net_price_cents"] == created["net_price_cents"] == 558720
    assert booking["created_at"] == created["created_at"]
    assert booking["version"] == created["version"] + 1


def test_a_published_package_cannot_be_repriced_so_the_agreed_price_stands(
    api: ApiClient,
) -> None:
    """Pricing runs from DRAFT and PRICED only, so PUBLISHED has no way back.

    Re-pricing the published package is refused on its state, and the package is
    untouched afterwards: the list price the booking was struck against is still
    120000, the pricing stamp is unchanged and the approving director is still
    recorded. The agreed 558720 can therefore never be reopened by a later
    pricing decision.

    PRD §3.4: "Pricing is available from `DRAFT` and, as a self-loop, from
    `PRICED`, and may be performed by a `CommercialManager` or a
    `CommercialDirector`."

    PRD §2.7: "**State preconditions**, in the order fixture, deal, tranche,
    block, package, booking, installment, build, assignment:
    `ERR_INVALID_EVENT_STATE`, `ERR_INVALID_DEAL_STATE`, `ERR_TRANCHE_NOT_PENDING`,
    `ERR_BLOCK_NOT_OPEN`, `ERR_INVALID_PACKAGE_STATE`,
    `ERR_INVALID_BOOKING_STATE`, `ERR_INSTALLMENT_NOT_PAYABLE`,
    `ERR_INVALID_BUILD_STATE`, `ERR_INVALID_ASSIGNMENT_STATE`."

    Design: Corner/entities/input_fields_are_write_once_because_no_endpoint_ever_takes_them_back
    """
    scenario = _sellable_fixture_with_a_reserved_booking(api)
    published = scenario["package"]
    assert published["package_status"] == "PUBLISHED"
    assert published["list_price_cents"] == 120000
    assert published["published_by_user_id"] == USER_COMMERCIAL_DIRECTOR

    response = api.price_package_product(published["id"], COMMERCIAL_MANAGER)

    validate_error(response, ERR_INVALID_PACKAGE_STATE, 409)

    package = get_success_data(
        api.get_package_product(published["id"], COMMERCIAL_MANAGER), 200
    )
    assert package["package_status"] == "PUBLISHED"
    assert package["list_price_cents"] == published["list_price_cents"] == 120000
    assert package["priced_at"] == published["priced_at"]
    assert package["published_by_user_id"] == USER_COMMERCIAL_DIRECTOR
    assert read_booking(api, scenario["booking"]["id"])["net_price_cents"] == 558720


def test_the_deals_contract_terms_survive_commitment_and_a_full_release(
    api: ApiClient,
) -> None:
    """The computed neighbours move; the acquisition terms do not.

    After a commitment and a tranche that releases the whole contract, the deal
    reports 40 released units and FULLY_RELEASED, while the contracted quantity,
    the guarantee, the unit cost, the holder, the inventory type, the fixture and
    the creation stamp are all exactly what the acquisition was booked with.

    PRD §3.2: "Then: if `released_units` is greater than or equal to
    `contracted_units`, the deal is `FULLY_RELEASED`; otherwise, if
    `released_units` plus the pending quantity is strictly below
    `guaranteed_minimum_units`, the deal is `SHORTFALL_DECLARED`; otherwise, if
    `released_units` is above 0, the deal is `PARTIALLY_RELEASED`; otherwise the
    deal is `COMMITTED`."

    Design: Corner/entities/input_fields_are_write_once_because_no_endpoint_ever_takes_them_back
    """
    scenario = _sellable_fixture_with_a_reserved_booking(api)
    created = scenario["deal"]

    deal = get_success_data(api.get_rights_deal(created["id"], RIGHTS_MANAGER), 200)

    assert deal["contracted_units"] == created["contracted_units"] == 40
    assert deal["guaranteed_minimum_units"] == created["guaranteed_minimum_units"] == 20
    assert deal["unit_cost_cents"] == created["unit_cost_cents"] == 8000
    assert deal["rights_holder_name"] == created["rights_holder_name"]
    assert deal["inventory_type"] == created["inventory_type"] == "TICKET"
    assert deal["event_id"] == created["event_id"] == scenario["event"]["id"]
    assert deal["created_at"] == created["created_at"]
    assert deal["released_units"] == 40
    assert deal["deal_status"] == "FULLY_RELEASED"

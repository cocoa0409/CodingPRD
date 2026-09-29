"""
Operations whose legality is decided by a *different* row's status: a show by its
agreement, a service order by its contract, an obligation by its deal.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BoothStatus,
    DealStatus,
    FulfillmentStatus,
    ObligationStatus,
    RateVariant,
    ServiceOrderStatus,
    ShowStatus,
    SpaceContractStatus,
    VenueContractStatus,
    factories as f,
    fixtures as fx,
    make_director_headers,
    make_floor_manager_headers,
    make_sales_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)


# ── The (Show, VenueContract) pair ──────────────────────────────────────────
def _draft_agreement(client: ApiClient) -> dict:
    """One agreement that has never been countersigned."""
    fx.set_clock(client, CLOCK)
    return fx.draft_venue_contract(client)


def test_an_edition_cannot_be_booked_under_an_uncountersigned_agreement(
    client: ApiClient,
):
    """
    The identical creation body is refused, then accepted, on the parent's status alone.

    "No show may be created under an agreement that is not `EXECUTED`; an attempt
    reports `ERR_VENUE_CONTRACT_NOT_EXECUTED`."  "On success the system writes
    `executed_at` from the logical clock and increments the agreement's `version`."

    Design: Difficulty/cross_entity_state_dependency/show_creation_depends_on_the_venue_contract_being_executed
    """
    agreement = _draft_agreement(client)
    assert agreement["status"] == VenueContractStatus.DRAFT
    body = f.show_payload(agreement["id"])

    validate_error(
        client.create_show(body, fx.DIRECTOR_HEADERS),
        ApiErrorId.VENUE_CONTRACT_NOT_EXECUTED,
        409,
    )

    executed = validate_success(
        client.execute_venue_contract(agreement["id"], fx.DIRECTOR_HEADERS)
    )
    assert executed["status"] == VenueContractStatus.EXECUTED
    assert executed["executed_at"] is not None
    assert executed["executed_at"].startswith("2026-08-15T00:00:00")

    show = validate_success(client.create_show(body, fx.DIRECTOR_HEADERS), 201)
    assert show["status"] == ShowStatus.PLANNING
    assert show["venue_contract_id"] == agreement["id"]


def test_the_refused_edition_leaves_the_agreements_edition_count_at_one(
    client: ApiClient,
):
    """
    Only the accepted attempt is counted by the parent.

    "`show_count` is thereafter maintained as the number of shows whose
    `venue_contract_id` is this agreement and whose own status is anything other
    than `CANCELLED`."  "Creation increments the parent agreement's `show_count` and
    its `version`."

    Design: Difficulty/cross_entity_state_dependency/show_creation_depends_on_the_venue_contract_being_executed
    """
    agreement = _draft_agreement(client)
    body = f.show_payload(agreement["id"])

    validate_error(
        client.create_show(body, fx.DIRECTOR_HEADERS),
        ApiErrorId.VENUE_CONTRACT_NOT_EXECUTED,
        409,
    )
    validate_success(
        client.execute_venue_contract(agreement["id"], fx.DIRECTOR_HEADERS)
    )
    validate_success(client.create_show(body, fx.DIRECTOR_HEADERS), 201)

    reread = validate_success(
        client.get_venue_contract(agreement["id"], fx.DIRECTOR_HEADERS)
    )
    assert reread["show_count"] == 1

    rows, meta = validate_paginated(
        client.list_venue_contract_shows(agreement["id"], fx.DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["status"] == ShowStatus.PLANNING


# ── The (ServiceOrder, SpaceContract) pair ──────────────────────────────────
LABOR_ORDER = f.service_order_payload("LABOR", 8, CLOCK)


def _held_but_unsigned(client: ApiClient) -> dict:
    """A 400 sqft hold on A100 that has not yet been signed."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    env["exhibitor"] = exhibitor
    env["exhibitor_headers"] = fx.make_exhibitor_headers(exhibitor["id"])
    env["contract"] = fx.offered_contract(
        client, env["show"]["id"], exhibitor["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], premium_placement_requested=True,
    )
    return env


def test_labor_cannot_be_ordered_against_an_unsigned_hold(client: ApiClient):
    """
    The order body sits inside every window; only the contract's status refuses it.

    "Contract status gates every subsequent operation, and a mismatch is always
    `ERR_INVALID_CONTRACT_STATUS`: a counter and a signature require `OFFERED`, a
    re-offer requires `COUNTERED`, a cancellation accepts `OFFERED`, `COUNTERED` or
    `SIGNED`, deposits and service orders and lead scans and citations all require
    `SIGNED`, and rebooking requires `CLOSED_OUT`."

    Design: Difficulty/cross_entity_state_dependency/service_order_depends_on_its_space_contract_being_signed
    """
    env = _held_but_unsigned(client)
    assert env["contract"]["status"] == SpaceContractStatus.OFFERED
    assert env["contract"]["min_deposit_cents"] == 389070

    validate_error(
        client.create_service_order(
            env["contract"]["id"], LABOR_ORDER, env["exhibitor_headers"]
        ),
        ApiErrorId.INVALID_CONTRACT_STATUS,
        409,
    )

    assert (
        fx.read_contract(client, env["contract"]["id"])["status"]
        == SpaceContractStatus.OFFERED
    )
    rows, meta = validate_paginated(
        client.list_service_orders(env["contract"]["id"], env["exhibitor_headers"])
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_the_same_labor_order_is_accepted_once_the_hold_is_signed(client: ApiClient):
    """
    Signing the parent unlocks the child, and the child prices at the advance rate.

    "Under `ADVANCE`, `line_total_cents` is the product of `billable_quantity`,
    `unit_rate_cents` and the quantity (one hundred minus the venue agreement's
    `advance_order_discount_pct`) divided by one hundred, rounded half up to whole
    cents; no expedite fee applies."

    Design: Difficulty/cross_entity_state_dependency/service_order_depends_on_its_space_contract_being_signed
    """
    env = _held_but_unsigned(client)
    headers = env["exhibitor_headers"]
    validate_error(
        client.create_service_order(env["contract"]["id"], LABOR_ORDER, headers),
        ApiErrorId.INVALID_CONTRACT_STATUS,
        409,
    )

    signed = fx.sign_contract(client, env["contract"], 389070)
    assert signed["status"] == SpaceContractStatus.SIGNED

    order = validate_success(
        client.create_service_order(env["contract"]["id"], LABOR_ORDER, headers), 201
    )
    assert order["status"] == ServiceOrderStatus.SUBMITTED
    assert order["rate_variant"] == RateVariant.ADVANCE
    assert order["unit_rate_cents"] == 9500
    assert order["billable_quantity"] == 8
    assert order["line_total_cents"] == 60800

    booth = fx.read_booth(client, env["booth_by_number"]["A100"]["id"])
    assert booth["status"] == BoothStatus.ASSIGNED


# ── The (FulfillmentObligation, SponsorshipDeal) pair ───────────────────────
FLOOR_1 = make_floor_manager_headers("u_floor_1")
DIRECTOR_1 = make_director_headers("u_dir_1")
REP_1 = make_sales_rep_headers("u_rep_1")


def _signed_deal_env(client: ApiClient) -> dict:
    """A signed two-obligation keynote deal on an open edition."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    package = fx.sponsorship_package(
        client, env["show"]["id"], package_code="GOLD_KEYNOTE",
        list_price_cents=1000000, price_floor_cents=700000, inventory_total=2,
        exclusivity_category="NONE",
        obligation_codes=["SOCIAL_MEDIA_POST", "ONSITE_BANNER"],
        priority_point_value=40,
    )
    deal = fx.signed_deal(client, package["id"], exhibitor["id"], 850000,
                          proposer_headers=REP_1, signer_headers=DIRECTOR_1)
    obligations = fx.read_obligations(client, deal["id"])
    assert len(obligations) == 2
    env.update({"exhibitor": exhibitor, "package": package, "deal": deal,
                "obligations": obligations})
    return env


def _read_package(client: ApiClient, show_id: str, package_id: str) -> dict:
    rows, _ = validate_paginated(
        client.list_sponsorship_packages(show_id, fx.DIRECTOR_HEADERS)
    )
    return next(row for row in rows if row["id"] == package_id)


def test_the_first_obligation_is_resolvable_while_the_deal_is_still_signed(
    client: ApiClient,
):
    """
    One delivery under a `SIGNED` deal, then the commercial cancellation.

    "The deal must be `SIGNED`, or the request is refused with
    `ERR_INVALID_DEAL_STATUS`".  "`fulfillment_status` keeps whatever derived value
    it already had: a commercial cancellation does not rewind the delivery axis, so
    a deal that had already delivered two of three obligations still reports a
    partial delivery record."

    Design: Difficulty/cross_entity_state_dependency/obligation_resolution_depends_on_its_deal_still_being_signed
    """
    env = _signed_deal_env(client)
    deal_id = env["deal"]["id"]

    resolved = validate_success(
        client.resolve_obligation(
            deal_id, env["obligations"][0]["id"],
            f.resolve_obligation_payload("DELIVERED"), FLOOR_1,
        )
    )
    assert resolved["status"] == ObligationStatus.DELIVERED
    assert resolved["resolved_by_user_id"] == "u_floor_1"

    after_delivery = fx.read_deal(client, deal_id)
    assert after_delivery["resolved_obligation_count"] == 1
    assert after_delivery["fulfillment_status"] == FulfillmentStatus.PARTIAL

    cancelled = validate_success(
        client.cancel_sponsorship_deal(
            deal_id,
            f.cancel_payload("Sponsor withdrew after the keynote slot was rescheduled"),
            DIRECTOR_1,
        )
    )
    assert cancelled["deal_status"] == DealStatus.CANCELLED
    assert cancelled["fulfillment_status"] == FulfillmentStatus.PARTIAL


def test_the_second_obligation_is_refused_once_the_deal_is_cancelled(
    client: ApiClient,
):
    """
    The same endpoint, the same disposition, the same operator — refused on the
    parent's status, with the pending obligation left untouched.

    "Obligations still `PENDING` stay `PENDING`, and because their deal is no longer
    `SIGNED` they are excluded from the missed-obligation sweep that runs at show
    close."  "the held unit is released so `inventory_committed` and
    `inventory_available` return to their exact pre-proposal values"

    Design: Difficulty/cross_entity_state_dependency/obligation_resolution_depends_on_its_deal_still_being_signed
    """
    env = _signed_deal_env(client)
    deal_id = env["deal"]["id"]
    validate_success(
        client.resolve_obligation(
            deal_id, env["obligations"][0]["id"],
            f.resolve_obligation_payload("DELIVERED"), FLOOR_1,
        )
    )
    validate_success(
        client.cancel_sponsorship_deal(
            deal_id,
            f.cancel_payload("Sponsor withdrew after the keynote slot was rescheduled"),
            DIRECTOR_1,
        )
    )

    validate_error(
        client.resolve_obligation(
            deal_id, env["obligations"][1]["id"],
            f.resolve_obligation_payload("DELIVERED"), FLOOR_1,
        ),
        ApiErrorId.INVALID_DEAL_STATUS,
        409,
    )

    obligations = {row["id"]: row for row in fx.read_obligations(client, deal_id)}
    still_pending = obligations[env["obligations"][1]["id"]]
    assert still_pending["status"] == ObligationStatus.PENDING
    assert still_pending["resolved_by_user_id"] is None

    deal = fx.read_deal(client, deal_id)
    assert deal["resolved_obligation_count"] == 1
    assert deal["fulfillment_credited"] is False

    package = _read_package(client, env["show"]["id"], env["package"]["id"])
    assert package["inventory_committed"] == 0
    assert package["inventory_available"] == 2

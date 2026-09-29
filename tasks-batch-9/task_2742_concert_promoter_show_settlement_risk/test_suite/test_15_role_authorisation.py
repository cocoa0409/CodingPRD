"""Role authorisation on the show settlement service.

Every test starts from an empty database and a logical clock of
2026-08-01T00:00:00Z, and builds all of its own preconditions through the
declared endpoints.
"""

import pytest

from test_helpers import (
    ACCOUNTANT_ALICE,
    ACCOUNTANT_BOB,
    BUYER_ID,
    RISK_RITA,
    RISK_ROB,
    assert_timestamp_equals,
    factories as f,
    get_success_data,
    make_artist_rep_headers,
    make_risk_officer_headers,
    make_talent_buyer_headers,
    make_tour_accountant_headers,
    make_venue_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E

CLOCK_START = "2026-08-01T00:00:00.000Z"
EVENT_AT = "2026-12-02T02:00:00.000Z"
LOAD_IN_AT = "2026-12-01T14:00:00.000Z"
LOAD_OUT_AT = "2026-12-02T08:00:00.000Z"
SECOND_EVENT_AT = "2026-12-09T02:00:00.000Z"
SECOND_LOAD_IN_AT = "2026-12-08T14:00:00.000Z"
SECOND_LOAD_OUT_AT = "2026-12-09T08:00:00.000Z"

# A RENTAL show must carry a rental fee greater than 0 (PRD 3.1).
RENTAL_FEE_CENTS = 100_000

# An id that no row in a freshly emptied database can carry.
ABSENT_ID = "00000000-0000-4000-8000-00000000da01"

BUYER = make_talent_buyer_headers(BUYER_ID)
ALICE = make_tour_accountant_headers(ACCOUNTANT_ALICE)
BOB = make_tour_accountant_headers(ACCOUNTANT_BOB)
RITA = make_risk_officer_headers(RISK_RITA)
ROB = make_risk_officer_headers(RISK_ROB)


def _market(api, **kwargs):
    kwargs.setdefault("guarantee_exposure_limit_cents", 5_000_000)
    return get_success_data(api.create_market(f.market_payload(**kwargs), RITA))


def _artist(api, **kwargs):
    kwargs.setdefault("tier", "THEATER")
    kwargs.setdefault("historical_sellthrough_pct", 68.00)
    kwargs.setdefault("withholding_pct", 0)
    return get_success_data(api.create_artist(f.artist_payload(**kwargs), BUYER))


def _venue(api, market_id, **kwargs):
    kwargs.setdefault("gross_capacity", 1_000)
    kwargs.setdefault("facility_fee_cents_per_ticket", 0)
    kwargs.setdefault("ticket_tax_pct", 0)
    return get_success_data(api.create_venue(f.venue_payload(market_id, **kwargs), BUYER))


def _show_payload(artist_id, venue_id, **kwargs):
    kwargs.setdefault("event_at", EVENT_AT)
    kwargs.setdefault("load_in_at", LOAD_IN_AT)
    kwargs.setdefault("load_out_at", LOAD_OUT_AT)
    kwargs.setdefault("announce_at", CLOCK_START)
    kwargs.setdefault("venue_arrangement", "RENTAL")
    kwargs.setdefault("rental_fee_cents", RENTAL_FEE_CENTS)
    return f.show_payload(artist_id, venue_id, **kwargs)


def _show(api, artist_id, venue_id, **kwargs):
    return get_success_data(
        api.create_show(_show_payload(artist_id, venue_id, **kwargs), BUYER)
    )


def _world(api):
    market = _market(api)
    artist = _artist(api)
    venue = _venue(api, market["id"])
    return {"market": market, "artist": artist, "venue": venue}


def _accepted_offer(api, show, artist_id, **terms):
    """Draft, submit and accept one offer; return the raw accept response."""
    terms.setdefault("guarantee_cents", 100_000)
    terms.setdefault("deposit_cents", 0)
    terms.setdefault("expense_cap_cents", 100_000)
    offer = get_success_data(
        api.create_offer(f.offer_payload(show["id"], show["version"], **terms), BUYER)
    )
    get_success_data(api.submit_offer(offer["id"], BUYER))
    accept_response = api.accept_offer(offer["id"], make_artist_rep_headers(artist_id))
    return offer["id"], accept_response


def _walk_to_calculated(api, build, perform_headers=None, calculate_headers=None):
    """Walk one show from an empty database to a CALCULATED settlement.

    Each call is made by a role the endpoint table lists as authorised for it.
    The raw responses of the calls under test are returned so that a caller may
    assert on them directly.
    """
    world = _world(api)
    show = _show(api, world["artist"]["id"], world["venue"]["id"])
    rep = make_artist_rep_headers(world["artist"]["id"])
    offer_id, accept_response = _accepted_offer(api, show, world["artist"]["id"])
    get_success_data(accept_response)
    show_after_accept = get_success_data(api.get_show(show["id"], BUYER))
    tier = get_success_data(
        api.create_ticket_tier(
            f.ticket_tier_payload(
                show["id"], tier_name="GA", price_cents=5_000, allocation_qty=100
            ),
            BUYER,
        )
    )
    on_sale_response = api.put_show_on_sale(show["id"], BUYER)
    get_success_data(on_sale_response)
    sale_response = api.record_sales(tier["id"], BUYER, qty=10)
    get_success_data(sale_response)
    line_response = api.create_budget_line(
        f.budget_line_payload(
            show["id"],
            category="PRODUCTION",
            description="Local crew call",
            budgeted_cents=20_000,
            is_artist_deductible=True,
        ),
        ALICE,
    )
    get_success_data(line_response)
    build.set_clock(EVENT_AT)
    perform_response = api.perform_show(show["id"], perform_headers or ALICE)
    get_success_data(perform_response)
    settlement_response = api.create_settlement(f.settlement_payload(show["id"]), ALICE)
    settlement = get_success_data(settlement_response)
    calculate_response = api.calculate_settlement(
        settlement["id"], calculate_headers or make_tour_accountant_headers("u-ro-calc")
    )
    get_success_data(calculate_response)
    return {
        "world": world,
        "show_id": show["id"],
        "artist_id": world["artist"]["id"],
        "venue_id": world["venue"]["id"],
        "rep": rep,
        "show_after_accept": show_after_accept,
        "offer_id": offer_id,
        "tier_id": tier["id"],
        "settlement_id": settlement["id"],
        "accept_response": accept_response,
        "on_sale_response": on_sale_response,
        "sale_response": sale_response,
        "line_response": line_response,
        "perform_response": perform_response,
        "settlement_response": settlement_response,
        "calculate_response": calculate_response,
    }


def test_the_risk_officer_owns_the_market_and_the_exposure_override(api, build):
    """PRD §3.1: "A `RiskOfficer` opens the books on a geography by creating a **market**"

    PRD §3.3: "A `RiskOfficer` may grant a show-scoped ceiling that replaces the market limit for **that one show's** guarantee check only, supplying `exposure_override_limit_cents` and a written `exposure_override_justification`."

    PRD §3.3: "On success the show records `exposure_override_limit_cents`, `exposure_override_justification` and `exposure_override_by_user_id` (the granting officer's opaque `X-User-ID`)"

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_and_shared_operations
    """
    market = validate_success(
        api.create_market(
            f.market_payload(
                name="Role Own Market",
                region_code="RO",
                guarantee_exposure_limit_cents=5_000_000,
            ),
            RITA,
        ),
        201,
    )
    assert market["guarantee_exposure_limit_cents"] == 5_000_000

    artist = _artist(api, name="Role Own Act", agency="Own Talent")
    venue = _venue(api, market["id"], name="Role Own Hall", gross_capacity=500)
    show = _show(api, artist["id"], venue["id"])

    granted = validate_success(
        api.grant_exposure_override(
            show["id"],
            RITA,
            exposure_override_limit_cents=9_000_000,
            exposure_override_justification="Anchor date, board approved",
        )
    )
    assert granted["exposure_override_limit_cents"] == 9_000_000
    assert granted["exposure_override_justification"] == "Anchor date, board approved"
    assert granted["exposure_override_by_user_id"] == RISK_RITA


def test_the_talent_buyer_owns_booking_and_ticket_inventory(api, build):
    """PRD §3.1: "Acts are registered by a `TalentBuyer`. An **artist** record carries a `name` and an `agency` of record"

    PRD §3.1: "Buildings are registered by a `TalentBuyer` too. A **venue** names the market it reports into by `market_id`"

    PRD §3.1: "Booking a date creates a **show**, again by a `TalentBuyer`. The payload names the act by `artist_id` and the building by `venue_id`"

    PRD §3.2: "An **offer** is the promoter's written proposal against a `PLANNED` show, authored by a `TalentBuyer`."

    PRD §3.4: "A `TalentBuyer` allocates a tier onto a show by naming the show in `show_id`"

    PRD §3.4: "Going on sale is a single call by a `TalentBuyer` that advances **both** of a show's status dimensions at once"

    PRD §3.4: "Repricing a tier in response to sales pace is a `TalentBuyer` capability that supplies `new_price_cents`, a `reason`, and the `expected_show_version` demanded by §2.7. On success the tier's `last_price_cents` records the price it held immediately before the revision, its `price_cents` becomes `new_price_cents`, and its `price_revision_count` increases by 1."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_and_shared_operations
    """
    market = _market(api, name="Role Own Market", region_code="RO")
    artist = validate_success(
        api.create_artist(
            f.artist_payload(
                name="Role Own Act",
                agency="Own Talent",
                tier="THEATER",
                historical_sellthrough_pct=68.00,
                withholding_pct=0,
            ),
            BUYER,
        ),
        201,
    )
    venue = validate_success(
        api.create_venue(
            f.venue_payload(
                market["id"],
                name="Role Own Hall",
                gross_capacity=500,
                facility_fee_cents_per_ticket=0,
                ticket_tax_pct=0,
            ),
            BUYER,
        ),
        201,
    )
    show = validate_success(
        api.create_show(_show_payload(artist["id"], venue["id"]), BUYER), 201
    )
    offer = validate_success(
        api.create_offer(
            f.offer_payload(
                show["id"],
                show["version"],
                deal_structure="FLAT_GUARANTEE",
                guarantee_cents=100_000,
                deposit_cents=0,
                expense_cap_cents=100_000,
            ),
            BUYER,
        ),
        201,
    )
    submitted = validate_success(api.submit_offer(offer["id"], BUYER))
    assert submitted["status"] == "SUBMITTED"

    # The artist side confirms the date, so that the buyer's on-sale call has a
    # CONFIRMED show to advance.
    get_success_data(api.accept_offer(offer["id"], make_artist_rep_headers(artist["id"])))

    tier = validate_success(
        api.create_ticket_tier(
            f.ticket_tier_payload(
                show["id"], tier_name="GA", price_cents=5_000, allocation_qty=100
            ),
            BUYER,
        ),
        201,
    )
    on_sale = validate_success(api.put_show_on_sale(show["id"], BUYER))
    assert on_sale["show_status"] == "ON_SALE"
    assert on_sale["sales_status"] == "SELLING"

    current = get_success_data(api.get_show(show["id"], BUYER))
    revised = validate_success(
        api.adjust_tier_price(
            tier["id"],
            BUYER,
            new_price_cents=6_000,
            expected_show_version=current["version"],
            reason="Demand is ahead of plan",
        )
    )
    assert revised["price_cents"] == 6_000
    assert revised["last_price_cents"] == 5_000
    assert revised["price_revision_count"] == 1


def test_the_artist_rep_owns_acceptance_and_the_settlement_signature(api, build):
    """PRD §3.3: "An `ArtistRep` whose `X-User-ID` equals the show's `artist_id` accepts a `SUBMITTED` offer on a show that is still `PLANNED`; the offer moves `SUBMITTED → ACCEPTED` and, in the same request, the show moves `PLANNED → CONFIRMED`."

    PRD §2.1: "It is also recorded as `accepted_by_user_id` on an accepted `Offer` and as `signed_by_user_id` on a signed `Settlement`."

    PRD §3.8: "An `ArtistRep` whose `X-User-ID` equals the show's `artist_id` supplies a `response` of either `SIGN` or `DISPUTE`"

    PRD §3.8: "`SIGN` moves the settlement `CALCULATED → ARTIST_SIGNED` and records `signed_by_user_id` as the responding rep's `X-User-ID`, unlocking payment."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_and_shared_operations
    """
    walk = _walk_to_calculated(api, build)

    accepted = validate_success(walk["accept_response"])
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_by_user_id"] == walk["artist_id"]
    assert walk["show_after_accept"]["show_status"] == "CONFIRMED"

    signed = validate_success(
        api.respond_to_settlement(walk["settlement_id"], walk["rep"], response="SIGN")
    )
    assert signed["status"] == "ARTIST_SIGNED"
    assert signed["signed_by_user_id"] == walk["artist_id"]


def test_the_tour_accountant_owns_the_budget_and_the_settlement_book(api, build):
    """PRD §3.6: "A `TourAccountant` budgets a show's costs as **budget lines**."

    PRD §3.7: "Opening the settlement book is a `TourAccountant` call that names the show in `show_id`."

    PRD §3.7: "Calculating the settlement is the heaviest write in the system, and only a `TourAccountant` may run it."

    PRD §3.8: "A `TourAccountant` pays an `ARTIST_SIGNED` settlement, supplying a required `payment_method` of `WIRE`, `CHECK` or `CASH` and a required `payment_reference` capturing the wire or cheque reference."

    PRD §3.8: "Payment moves the settlement `ARTIST_SIGNED → PAID`, which is terminal, stamps `paid_at` with the current logical clock and records the `payment_method` and `payment_reference`."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_and_shared_operations
    """
    walk = _walk_to_calculated(api, build)

    line = validate_success(walk["line_response"], 201)
    assert line["budgeted_cents"] == 20_000

    book = validate_success(walk["settlement_response"], 201)
    assert book["show_id"] == walk["show_id"]

    calculated = validate_success(walk["calculate_response"])
    assert calculated["status"] == "CALCULATED"
    assert calculated["calculated_by_user_id"] == "u-ro-calc"

    get_success_data(
        api.respond_to_settlement(walk["settlement_id"], walk["rep"], response="SIGN")
    )
    paid = validate_success(
        api.pay_settlement(
            walk["settlement_id"],
            make_tour_accountant_headers("u-ro-pay"),
            payment_method="WIRE",
            payment_reference="WIRE-RO-01",
        )
    )
    assert paid["status"] == "PAID"
    assert paid["payment_reference"] == "WIRE-RO-01"
    assert_timestamp_equals(paid["paid_at"], EVENT_AT)


def test_the_shared_perform_and_sales_calls_work_for_their_second_role(api, build):
    """PRD §3.7: "A `TalentBuyer` or a `TourAccountant` records it, moving `show_status` `ON_SALE → PERFORMED`"

    PRD §3.4: "Sales themselves are recorded in blocks against a tier by a `TalentBuyer` or a `VenueOperator`, supplying `qty`, the number of paid seats sold."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_and_shared_operations
    """
    walk = _walk_to_calculated(api, build, perform_headers=ALICE)

    sold = validate_success(walk["sale_response"])
    assert sold["sold_qty"] == 10

    performed = validate_success(walk["perform_response"])
    assert performed["show_status"] == "PERFORMED"
    assert performed["sales_status"] == "CLOSED"


def _deny_world(api):
    """One CONFIRMED show with a tier, a hold and a budget line already in place."""
    market = _market(api, name="Deny Market", region_code="DN")
    venue = _venue(api, market["id"], name="Deny Hall", gross_capacity=500)
    artist = _artist(
        api,
        name="Deny Act",
        agency="Dny Talent",
        tier="CLUB",
        historical_sellthrough_pct=54.00,
    )
    show = _show(api, artist["id"], venue["id"])
    offer_id, accept_response = _accepted_offer(api, show, artist["id"])
    get_success_data(accept_response)
    tier = get_success_data(
        api.create_ticket_tier(
            f.ticket_tier_payload(
                show["id"], tier_name="GA", price_cents=5_000, allocation_qty=100
            ),
            BUYER,
        )
    )
    hold = get_success_data(
        api.create_ticket_hold(
            f.ticket_hold_payload(
                tier["id"], kind="PROMOTER_HOLD", qty=4, holder="Promoter holds"
            ),
            BUYER,
        )
    )
    line = get_success_data(
        api.create_budget_line(
            f.budget_line_payload(
                show["id"],
                category="PRODUCTION",
                description="Deny line",
                budgeted_cents=50_000,
                is_artist_deductible=True,
            ),
            ALICE,
        )
    )
    return {
        "market_id": market["id"],
        "artist_id": artist["id"],
        "venue_id": venue["id"],
        "show_id": show["id"],
        "offer_id": offer_id,
        "tier_id": tier["id"],
        "hold_id": hold["id"],
        "line_id": line["id"],
    }


# Eighteen calls made by a role the endpoint table does not list, one per family
# of exclusive operation. The last seven name ids that no row carries, to pin the
# refusal on the role gate rather than on resource lookup.
WRONG_ROLE_PROBES = [
    (
        "talent_buyer_opens_a_market",
        lambda api, ctx: api.create_market(
            f.market_payload(
                name="Buyer Market",
                region_code="BM",
                guarantee_exposure_limit_cents=1_000_000,
            ),
            BUYER,
        ),
    ),
    (
        "talent_buyer_grants_an_exposure_override",
        lambda api, ctx: api.grant_exposure_override(
            ctx["show_id"],
            BUYER,
            exposure_override_limit_cents=9_000_000,
            exposure_override_justification="I would like more room",
        ),
    ),
    (
        "tour_accountant_books_a_show",
        lambda api, ctx: api.create_show(
            _show_payload(
                ctx["artist_id"],
                ctx["venue_id"],
                event_at=SECOND_EVENT_AT,
                load_in_at=SECOND_LOAD_IN_AT,
                load_out_at=SECOND_LOAD_OUT_AT,
            ),
            ALICE,
        ),
    ),
    (
        "risk_officer_writes_an_offer",
        lambda api, ctx: api.create_offer(
            f.offer_payload(
                ctx["show_id"],
                1,
                guarantee_cents=100_000,
                deposit_cents=0,
                expense_cap_cents=100_000,
            ),
            RITA,
        ),
    ),
    (
        "talent_buyer_accepts_its_own_offer",
        lambda api, ctx: api.accept_offer(ctx["offer_id"], BUYER),
    ),
    (
        "talent_buyer_counters_its_own_offer",
        lambda api, ctx: api.counter_offer(
            ctx["offer_id"],
            BUYER,
            counter_guarantee_cents=150_000,
            counter_note="Buyer countering its own offer",
        ),
    ),
    (
        "venue_operator_builds_inventory",
        lambda api, ctx: api.create_ticket_tier(
            f.ticket_tier_payload(
                ctx["show_id"], tier_name="PIT", price_cents=9_000, allocation_qty=50
            ),
            make_venue_operator_headers(ctx["venue_id"]),
        ),
    ),
    (
        "risk_officer_puts_the_show_on_sale",
        lambda api, ctx: api.put_show_on_sale(ctx["show_id"], RITA),
    ),
    (
        "artist_rep_converts_a_hold_to_a_comp",
        lambda api, ctx: api.convert_hold_to_comp(
            ctx["hold_id"], make_artist_rep_headers(ctx["artist_id"])
        ),
    ),
    (
        "talent_buyer_adds_a_budget_line",
        lambda api, ctx: api.create_budget_line(
            f.budget_line_payload(
                ctx["show_id"],
                category="MARKETING",
                description="Buyer budget",
                budgeted_cents=10_000,
                is_artist_deductible=True,
            ),
            BUYER,
        ),
    ),
    (
        "risk_officer_verifies_an_invoice",
        lambda api, ctx: api.verify_vendor_invoice(ABSENT_ID, RITA),
    ),
    (
        "risk_officer_opens_the_settlement_book",
        lambda api, ctx: api.create_settlement(f.settlement_payload(ctx["show_id"]), RITA),
    ),
    (
        "risk_officer_calculates_a_settlement",
        lambda api, ctx: api.calculate_settlement(ABSENT_ID, RITA),
    ),
    (
        "risk_officer_pays_a_settlement",
        lambda api, ctx: api.pay_settlement(
            ABSENT_ID, RITA, payment_method="WIRE", payment_reference="WIRE-DN-01"
        ),
    ),
    (
        "tour_accountant_reopens_a_settlement",
        lambda api, ctx: api.reopen_settlement(
            ABSENT_ID,
            ALICE,
            reopen_reason="Accountant reopening its own calculation",
        ),
    ),
    (
        "tour_accountant_answers_for_the_artist",
        lambda api, ctx: api.respond_to_settlement(ABSENT_ID, ALICE, response="SIGN"),
    ),
    (
        "tour_accountant_files_an_insurance_claim",
        lambda api, ctx: api.file_claim(
            ABSENT_ID,
            ALICE,
            claim_amount_cents=100_000,
            claim_documentation_ref="CLM-DN",
        ),
    ),
    (
        "risk_officer_processes_refunds",
        lambda api, ctx: api.process_refunds(ABSENT_ID, RITA),
    ),
]


@pytest.mark.parametrize(
    "probe", [pytest.param(probe, id=name) for name, probe in WRONG_ROLE_PROBES]
)
def test_a_role_cannot_reach_another_roles_exclusive_operation(api, build, probe):
    """PRD §2.1: "If `X-User-Role` holds any other string, or holds one of the five but that role is not listed as authorised for the endpoint being called, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403). The authorised role list for each endpoint appears in §4."

    PRD §2.9: "Where several rules could reject the same call, they are evaluated in a fixed order and the **first** violated rule determines the response."
    Role authorisation is rule 2 and existence of every referenced resource is rule 4, so a wrong-role call against an id that does not exist is still 403 and never 404.

    Design: Corner/rbac/roles_cannot_reach_another_roles_exclusive_operations
    """
    ctx = _deny_world(api)
    validate_error(probe(api, ctx), E.ERR_ROLE_FORBIDDEN)


def test_the_refused_calls_left_nothing_behind(api, build):
    """PRD §2.9: "No later rule is evaluated once one has fired, and no side effect of the operation runs."

    Design: Corner/rbac/roles_cannot_reach_another_roles_exclusive_operations
    """
    ctx = _deny_world(api)
    for _name, probe in WRONG_ROLE_PROBES:
        validate_error(probe(api, ctx), E.ERR_ROLE_FORBIDDEN)

    show = get_success_data(api.get_show(ctx["show_id"], BUYER))
    assert show["show_status"] == "CONFIRMED"
    assert show["sales_status"] == "PRE_SALE"
    assert show.get("exposure_override_limit_cents") is None

    _markets, markets_meta = validate_paginated(api.list_markets(RITA))
    assert markets_meta["total_count"] == 1
    _shows, shows_meta = validate_paginated(api.list_shows(BUYER))
    assert shows_meta["total_count"] == 1
    _offers, offers_meta = validate_paginated(api.list_offers(BUYER, show_id=ctx["show_id"]))
    assert offers_meta["total_count"] == 1
    _tiers, tiers_meta = validate_paginated(
        api.list_ticket_tiers(BUYER, show_id=ctx["show_id"])
    )
    assert tiers_meta["total_count"] == 1
    _lines, lines_meta = validate_paginated(
        api.list_budget_lines(ALICE, show_id=ctx["show_id"])
    )
    assert lines_meta["total_count"] == 1
    _settlements, settlements_meta = validate_paginated(
        api.list_settlements(ALICE, show_id=ctx["show_id"])
    )
    assert settlements_meta["total_count"] == 0


def _on_sale_show(api, world=None, allocation_qty=300, price_cents=5_000, **show_kwargs):
    """One ON_SALE show with a single GA tier, built by the roles that own each call."""
    world = world or _world(api)
    show = _show(api, world["artist"]["id"], world["venue"]["id"], **show_kwargs)
    offer_id, accept_response = _accepted_offer(
        api, show, world["artist"]["id"], expense_cap_cents=300_000
    )
    get_success_data(accept_response)
    tier = get_success_data(
        api.create_ticket_tier(
            f.ticket_tier_payload(
                show["id"],
                tier_name="GA",
                price_cents=price_cents,
                allocation_qty=allocation_qty,
            ),
            BUYER,
        )
    )
    show = get_success_data(api.put_show_on_sale(show["id"], BUYER))
    return {
        "world": world,
        "show": show,
        "show_id": show["id"],
        "artist_id": world["artist"]["id"],
        "venue_id": world["venue"]["id"],
        "tier_id": tier["id"],
        "offer_id": offer_id,
    }


def test_the_venue_operator_may_record_a_sale_on_the_shared_endpoint(api, build):
    """PRD §3.4: "Sales themselves are recorded in blocks against a tier by a `TalentBuyer` or a `VenueOperator`, supplying `qty`, the number of paid seats sold."

    PRD §3.4: "On success the tier's `sold_qty` increases by `qty`, its `available_qty` decreases by `qty`"

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    ctx = _on_sale_show(api)
    sold = validate_success(
        api.record_sales(ctx["tier_id"], make_venue_operator_headers(ctx["venue_id"]), qty=20)
    )
    assert sold["sold_qty"] == 20
    assert sold["available_qty"] == 280


HOLD_ROLE_KINDS = [
    ("talent_buyer_promoter_hold", "PROMOTER_HOLD", 3, "Promoter production hold"),
    ("artist_rep_artist_hold", "ARTIST_HOLD", 4, "Artist guest list"),
    ("venue_operator_production_hold", "PRODUCTION_HOLD", 5, "Sound and light kill"),
]


def _hold_headers(ctx, kind):
    if kind == "ARTIST_HOLD":
        return make_artist_rep_headers(ctx["artist_id"])
    if kind == "PRODUCTION_HOLD":
        return make_venue_operator_headers(ctx["venue_id"])
    return BUYER


@pytest.mark.parametrize(
    "kind,qty,holder",
    [pytest.param(kind, qty, holder, id=name) for name, kind, qty, holder in HOLD_ROLE_KINDS],
)
def test_three_roles_may_each_place_the_hold_kind_they_own(api, build, kind, qty, holder):
    """PRD §3.5: "Holds may be created by a `TalentBuyer`, an `ArtistRep` or a `VenueOperator`, but the two entity-backed roles are narrowly scoped: an `ArtistRep` may only create `ARTIST_HOLD` seats, and only on shows whose `artist_id` equals its `X-User-ID`; a `VenueOperator` may only create `PRODUCTION_HOLD` seats, and only on shows whose `venue_id` equals its `X-User-ID`."

    PRD §3.5: "A hold is created in status `HELD` with `released_by_user_id` null."

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    ctx = _on_sale_show(api)
    held = validate_success(
        api.create_ticket_hold(
            f.ticket_hold_payload(ctx["tier_id"], kind=kind, qty=qty, holder=holder),
            _hold_headers(ctx, kind),
        ),
        201,
    )
    assert held["status"] == "HELD"
    assert held["kind"] == kind
    assert held["qty"] == qty
    assert held["released_by_user_id"] is None

    tier = get_success_data(api.get_ticket_tier(ctx["tier_id"], BUYER))
    assert tier["held_qty"] == qty
    assert tier["available_qty"] == 300 - qty


@pytest.mark.parametrize(
    "kind,qty,holder",
    [pytest.param(kind, qty, holder, id=name) for name, kind, qty, holder in HOLD_ROLE_KINDS],
)
def test_three_roles_may_each_release_the_hold_kind_they_own(api, build, kind, qty, holder):
    """PRD §3.5: "A `TalentBuyer` may release any hold on any show; an `ArtistRep` may release only `ARTIST_HOLD` holds on shows whose `artist_id` matches its own identity; a `VenueOperator` may release only `PRODUCTION_HOLD` holds on shows whose `venue_id` matches its own identity."

    PRD §3.5: "The hold moves `HELD → RELEASED`, its `released_by_user_id` records the acting `X-User-ID`"

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    ctx = _on_sale_show(api)
    headers = _hold_headers(ctx, kind)
    held = get_success_data(
        api.create_ticket_hold(
            f.ticket_hold_payload(ctx["tier_id"], kind=kind, qty=qty, holder=holder),
            headers,
        )
    )
    released = validate_success(api.release_ticket_hold(held["id"], headers))
    assert released["status"] == "RELEASED"
    assert released["released_by_user_id"] == headers["X-User-ID"]

    tier = get_success_data(api.get_ticket_tier(ctx["tier_id"], BUYER))
    assert tier["held_qty"] == 0
    assert tier["available_qty"] == 300


CLOCK_ROLE_IDS = [
    "talent_buyer",
    "artist_rep",
    "venue_operator",
    "tour_accountant",
    "risk_officer",
]


def _headers_for(ctx, role_id, user_id=None):
    if role_id == "talent_buyer":
        return make_talent_buyer_headers(user_id or BUYER_ID)
    if role_id == "artist_rep":
        return make_artist_rep_headers(ctx["artist_id"])
    if role_id == "venue_operator":
        return make_venue_operator_headers(ctx["venue_id"])
    if role_id == "tour_accountant":
        return make_tour_accountant_headers(user_id or ACCOUNTANT_ALICE)
    return make_risk_officer_headers(user_id or RISK_RITA)


@pytest.mark.parametrize("role_id", CLOCK_ROLE_IDS)
def test_the_logical_clock_endpoint_is_open_to_every_role(api, build, role_id):
    """PRD §4: "| POST | /_clock/set_current_utc | Set the logical clock to the supplied `current_utc` instant. | TalentBuyer, TourAccountant, RiskOfficer, ArtistRep, VenueOperator |"

    PRD §2.5: "An operator moves it by supplying a `current_utc` instant to the clock-setting endpoint; the clock then reads that instant until it is set again."

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    world = _world(api)
    ctx = {"artist_id": world["artist"]["id"], "venue_id": world["venue"]["id"]}
    validate_success(
        api.set_clock("2026-08-02T00:00:00.000Z", _headers_for(ctx, role_id))
    )


@pytest.mark.parametrize("role_id", ["talent_buyer", "tour_accountant", "risk_officer"])
def test_the_housekeeping_endpoint_is_open_to_the_three_roles_that_declare_it(
    api, build, role_id
):
    """PRD §4: "| POST | /_ops/run | Execute an internal operations batch request. | TalentBuyer, TourAccountant, RiskOfficer |"

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    validate_success(api.run_housekeeping(_headers_for({}, role_id)))


def test_housekeeping_expires_a_hold_for_one_role_and_is_idempotent_for_the_next(
    api, build
):
    """PRD §3.5: "Any hold in `HELD` whose `expires_at` is non-null and has been reached by the current logical clock moves `HELD → EXPIRED`; the tier's `held_qty` — or `comp_qty` for a comp hold — decreases by the hold's `qty` and its `available_qty` increases by the same amount"

    PRD §2.5: "expiries are applied only when the housekeeping endpoint is run, and that endpoint is idempotent — running it twice at the same clock instant changes nothing the second time."

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    ctx = _on_sale_show(api)
    hold = get_success_data(
        api.create_ticket_hold(
            f.ticket_hold_payload(
                ctx["tier_id"],
                kind="PROMOTER_HOLD",
                qty=6,
                holder="Trade and radio, expiring",
                expires_at="2026-08-02T00:00:00.000Z",
            ),
            BUYER,
        )
    )
    # The clock itself is shared by all five roles, so the artist side moves it.
    validate_success(
        api.set_clock("2026-08-02T00:00:00.000Z", make_artist_rep_headers(ctx["artist_id"]))
    )

    validate_success(api.run_housekeeping(ALICE))
    expired = get_success_data(api.get_ticket_hold(hold["id"], BUYER))
    assert expired["status"] == "EXPIRED"
    after_first = get_success_data(api.get_ticket_tier(ctx["tier_id"], BUYER))
    assert after_first["held_qty"] == 0
    assert after_first["available_qty"] == 300

    validate_success(api.run_housekeeping(BUYER))
    after_second = get_success_data(api.get_ticket_tier(ctx["tier_id"], RITA))
    assert after_second["held_qty"] == 0
    assert after_second["available_qty"] == 300


@pytest.mark.parametrize(
    "pauser_id", ["risk_officer", "talent_buyer"]
)
def test_pausing_sales_is_shared_by_the_buyer_and_the_risk_officer(api, build, pauser_id):
    """PRD §3.4: "Pausing — available to a `TalentBuyer` or a `RiskOfficer`, and requiring a `reason` — moves `sales_status` `SELLING → PAUSED` and cascades every tier in `ON_SALE` to `PAUSED`, while leaving `show_status` completely untouched at `ON_SALE`."

    PRD §3.4: "Resuming, available to a `TalentBuyer`, moves `sales_status` `PAUSED → SELLING`"

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    ctx = _on_sale_show(api)
    paused = validate_success(
        api.pause_sales(
            ctx["show_id"],
            "Risk hold pending insurance certificate",
            _headers_for(ctx, pauser_id),
        )
    )
    assert paused["sales_status"] == "PAUSED"
    assert paused["show_status"] == "ON_SALE"

    resumed = validate_success(api.resume_sales(ctx["show_id"], BUYER))
    assert resumed["sales_status"] == "SELLING"
    assert resumed["show_status"] == "ON_SALE"


def _budget_line(api, show_id, budgeted_cents=200_000, category="PRODUCTION"):
    return get_success_data(
        api.create_budget_line(
            f.budget_line_payload(
                show_id,
                category=category,
                description="Stage and crew",
                budgeted_cents=budgeted_cents,
                is_artist_deductible=True,
            ),
            ALICE,
        )
    )


def _invoice_payload(show_id, line_id, amount_cents, vendor_name="Stagehands Local"):
    return f.vendor_invoice_payload(
        show_id,
        line_id,
        amount_cents=amount_cents,
        vendor_name=vendor_name,
        invoice_date="2026-08-02",
    )


@pytest.mark.parametrize("author_id", ["tour_accountant", "venue_operator"])
def test_papering_a_vendor_invoice_is_shared_by_the_accountant_and_the_venue(
    api, build, author_id
):
    """PRD §3.6: "A `TourAccountant` or a `VenueOperator` captures one against a line, supplying `show_id`, `budget_line_id`, a `vendor_name` of 1 to 120 characters, an `amount_cents` of at least 1, an `invoice_date`, and a `documentation_ref` of 1 to 64 characters pointing at the settlement-book packet page or scan."

    PRD §3.6: "The invoice is created in status `SUBMITTED` with `resubmit_count` 0, `verified_by_user_id` and `approved_by_user_id` null, and `dispute_reason` null"

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    ctx = _on_sale_show(api)
    line = _budget_line(api, ctx["show_id"])
    invoice = validate_success(
        api.create_vendor_invoice(
            _invoice_payload(ctx["show_id"], line["id"], 210_000),
            _headers_for(ctx, author_id),
        ),
        201,
    )
    assert invoice["status"] == "SUBMITTED"
    assert invoice["resubmit_count"] == 0
    assert invoice["verified_by_user_id"] is None
    assert invoice["approved_by_user_id"] is None


@pytest.mark.parametrize(
    "approver_id,approver_user_id",
    [("tour_accountant", ACCOUNTANT_BOB), ("risk_officer", RISK_RITA)],
)
def test_approving_a_vendor_invoice_is_shared_by_the_accountant_and_the_risk_officer(
    api, build, approver_id, approver_user_id
):
    """PRD §3.6: "Approval — available to a `TourAccountant` or a `RiskOfficer` — moves it `VERIFIED → APPROVED` and records `approved_by_user_id`"

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    ctx = _on_sale_show(api)
    line = _budget_line(api, ctx["show_id"])
    invoice = get_success_data(
        api.create_vendor_invoice(_invoice_payload(ctx["show_id"], line["id"], 210_000), ALICE)
    )
    verified = get_success_data(api.verify_vendor_invoice(invoice["id"], ALICE))
    assert verified["status"] == "VERIFIED"

    approved = validate_success(
        api.approve_vendor_invoice(
            invoice["id"], _headers_for(ctx, approver_id, user_id=approver_user_id)
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == approver_user_id


@pytest.mark.parametrize("disputer_id", ["tour_accountant", "venue_operator"])
def test_disputing_a_vendor_invoice_is_shared_by_the_accountant_and_the_venue(
    api, build, disputer_id
):
    """PRD §3.6: "An invoice that has not yet been approved can be disputed by a `TourAccountant` or the `VenueOperator` that owns the venue, moving it `SUBMITTED → DISPUTED` or `VERIFIED → DISPUTED` and recording a `dispute_reason`."

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    ctx = _on_sale_show(api)
    line = _budget_line(api, ctx["show_id"])
    invoice = get_success_data(
        api.create_vendor_invoice(_invoice_payload(ctx["show_id"], line["id"], 50_000), ALICE)
    )
    disputed = validate_success(
        api.dispute_vendor_invoice(
            invoice["id"],
            _headers_for(ctx, disputer_id),
            dispute_reason="Hospitality rider does not cover this order",
        )
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "Hospitality rider does not cover this order"


def test_a_dispute_arriving_from_verified_voids_the_verification(api, build):
    """PRD §3.6: "When the dispute arrives from `VERIFIED`, the invoice's `verified_by_user_id` is cleared to null — the verification is void, so whoever verified it before may verify it again after re-papering."

    PRD §3.6: "only `APPROVED` invoices count, so `SUBMITTED`, `VERIFIED`, `DISPUTED` and `REJECTED` amounts are all excluded"

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    ctx = _on_sale_show(api)
    line = _budget_line(api, ctx["show_id"])
    invoice = get_success_data(
        api.create_vendor_invoice(
            _invoice_payload(ctx["show_id"], line["id"], 40_000, vendor_name="Forklift Rental"),
            make_venue_operator_headers(ctx["venue_id"]),
        )
    )
    verified = get_success_data(api.verify_vendor_invoice(invoice["id"], ALICE))
    assert verified["verified_by_user_id"] == ACCOUNTANT_ALICE

    disputed = validate_success(
        api.dispute_vendor_invoice(
            invoice["id"], BOB, dispute_reason="Unit was never delivered to the dock"
        )
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["verified_by_user_id"] is None

    assert get_success_data(api.get_budget_line(line["id"], ALICE))["actual_cents"] == 0


VARIANCE_BANDS = [
    ("risk_officer_decides_a_risk_officer_line", 130_000, "RISK_OFFICER", "risk_officer", RISK_ROB),
    (
        "tour_accountant_decides_a_tour_accountant_line",
        125_000,
        "TOUR_ACCOUNTANT",
        "tour_accountant",
        "u-sr-ta3",
    ),
]


@pytest.mark.parametrize(
    "amount_cents,required_role,decider_id,decider_user_id",
    [
        pytest.param(amount, role, decider, user, id=name)
        for name, amount, role, decider, user in VARIANCE_BANDS
    ],
)
def test_the_variance_decision_is_shared_but_its_authority_is_banded(
    api, build, amount_cents, required_role, decider_id, decider_user_id
):
    """PRD §3.6: "A pending variance is decided by a `TourAccountant` or a `RiskOfficer`, supplying a `decision` of `APPROVE` or `REJECT` and a `variance_justification`, and optionally an `approved_cap_cents`."

    PRD §3.6: "a `RiskOfficer` may decide any line, while a `TourAccountant` may decide only lines whose `required_approver_role` is `NONE` or `TOUR_ACCOUNTANT`"

    PRD §3.6: "sets `required_approver_role` to `TOUR_ACCOUNTANT` when the variance is at most 25.00 percent and `RISK_OFFICER` when it is above 25.00 percent"

    PRD §3.6: "On `APPROVE` the line moves `PENDING_APPROVAL → APPROVED`, records `approved_cap_cents`, `variance_justification` and `variance_decided_by_user_id`"

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    ctx = _on_sale_show(api)
    line = _budget_line(api, ctx["show_id"], budgeted_cents=100_000)
    invoice = get_success_data(
        api.create_vendor_invoice(
            _invoice_payload(ctx["show_id"], line["id"], amount_cents), ALICE
        )
    )
    get_success_data(api.verify_vendor_invoice(invoice["id"], ALICE))
    get_success_data(api.approve_vendor_invoice(invoice["id"], BOB))

    pending = get_success_data(api.get_budget_line(line["id"], ALICE))
    assert pending["variance_status"] == "PENDING_APPROVAL"
    assert pending["required_approver_role"] == required_role

    decided = validate_success(
        api.decide_variance(
            line["id"],
            _headers_for(ctx, decider_id, user_id=decider_user_id),
            decision="APPROVE",
            approved_cap_cents=amount_cents,
            variance_justification="Overage reviewed against the signed change order",
        )
    )
    assert decided["variance_status"] == "APPROVED"
    assert decided["approved_cap_cents"] == amount_cents
    assert decided["variance_decided_by_user_id"] == decider_user_id


@pytest.mark.parametrize(
    "opener_id,kind",
    [("talent_buyer", "CANCELLED"), ("risk_officer", "POSTPONED")],
)
def test_opening_a_cancellation_event_is_shared_by_the_buyer_and_the_risk_officer(
    api, build, opener_id, kind
):
    """PRD §3.9: "A `TalentBuyer` or a `RiskOfficer` opens a **cancellation event** naming the show in `show_id`, a `kind`, and a `reason` of 1 to 200 characters explaining why the date was pulled."

    PRD §3.9: "The event is created in status `OPENED` with `occurred_at` stamped from the current logical clock"

    Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
    """
    ctx = _on_sale_show(api)
    event = validate_success(
        api.create_cancellation_event(
            f.cancellation_event_payload(
                ctx["show_id"], kind=kind, reason="The date was pulled by the promoter"
            ),
            _headers_for(ctx, opener_id),
        ),
        201,
    )
    assert event["status"] == "OPENED"
    assert event["kind"] == kind
    assert_timestamp_equals(event["occurred_at"], CLOCK_START)

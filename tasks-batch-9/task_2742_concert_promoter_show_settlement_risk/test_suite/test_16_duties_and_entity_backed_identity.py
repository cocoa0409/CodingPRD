"""Segregation of duties and the two entity-backed identities.

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
    factories as f,
    get_success_data,
    make_artist_rep_headers,
    make_risk_officer_headers,
    make_talent_buyer_headers,
    make_tour_accountant_headers,
    make_venue_operator_headers,
    validate_error,
    validate_paginated,
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

BUYER = make_talent_buyer_headers(BUYER_ID)
ALICE = make_tour_accountant_headers(ACCOUNTANT_ALICE)
BOB = make_tour_accountant_headers(ACCOUNTANT_BOB)
RITA = make_risk_officer_headers(RISK_RITA)
ROB = make_risk_officer_headers(RISK_ROB)
CALCULATOR = make_tour_accountant_headers("u-sd-calc")


def _market(api, **kwargs):
    kwargs.setdefault("guarantee_exposure_limit_cents", 5_000_000)
    return get_success_data(api.create_market(f.market_payload(**kwargs), RITA))


def _artist(api, **kwargs):
    kwargs.setdefault("tier", "THEATER")
    kwargs.setdefault("historical_sellthrough_pct", 60.00)
    kwargs.setdefault("withholding_pct", 0)
    return get_success_data(api.create_artist(f.artist_payload(**kwargs), BUYER))


def _venue(api, market_id, **kwargs):
    kwargs.setdefault("gross_capacity", 500)
    kwargs.setdefault("facility_fee_cents_per_ticket", 0)
    kwargs.setdefault("ticket_tax_pct", 0)
    return get_success_data(api.create_venue(f.venue_payload(market_id, **kwargs), BUYER))


def _show(api, artist_id, venue_id, **kwargs):
    kwargs.setdefault("event_at", EVENT_AT)
    kwargs.setdefault("load_in_at", LOAD_IN_AT)
    kwargs.setdefault("load_out_at", LOAD_OUT_AT)
    kwargs.setdefault("announce_at", CLOCK_START)
    kwargs.setdefault("venue_arrangement", "RENTAL")
    kwargs.setdefault("rental_fee_cents", RENTAL_FEE_CENTS)
    return get_success_data(
        api.create_show(f.show_payload(artist_id, venue_id, **kwargs), BUYER)
    )


def _submitted_offer(api, show, **terms):
    terms.setdefault("guarantee_cents", 100_000)
    terms.setdefault("deposit_cents", 0)
    terms.setdefault("expense_cap_cents", 100_000)
    offer = get_success_data(
        api.create_offer(f.offer_payload(show["id"], show["version"], **terms), BUYER)
    )
    get_success_data(api.submit_offer(offer["id"], BUYER))
    return offer


def _on_sale_show(api, world=None, allocation_qty=200, sold_qty=100, **show_kwargs):
    """One ON_SALE show with a single GA tier and some paid seats already sold."""
    if world is None:
        market = _market(api)
        world = {
            "market": market,
            "artist": _artist(api),
            "venue": _venue(api, market["id"]),
        }
    show = _show(api, world["artist"]["id"], world["venue"]["id"], **show_kwargs)
    offer = _submitted_offer(api, show)
    get_success_data(
        api.accept_offer(offer["id"], make_artist_rep_headers(world["artist"]["id"]))
    )
    tier = get_success_data(
        api.create_ticket_tier(
            f.ticket_tier_payload(
                show["id"], tier_name="GA", price_cents=5_000, allocation_qty=allocation_qty
            ),
            BUYER,
        )
    )
    get_success_data(api.put_show_on_sale(show["id"], BUYER))
    if sold_qty:
        get_success_data(api.record_sales(tier["id"], BUYER, qty=sold_qty))
    return {
        "world": world,
        "show_id": show["id"],
        "artist_id": world["artist"]["id"],
        "venue_id": world["venue"]["id"],
        "tier_id": tier["id"],
        "offer_id": offer["id"],
    }


def _budget_line(api, show_id, budgeted_cents=100_000):
    return get_success_data(
        api.create_budget_line(
            f.budget_line_payload(
                show_id,
                category="PRODUCTION",
                description="Crew and gear",
                budgeted_cents=budgeted_cents,
                is_artist_deductible=True,
            ),
            ALICE,
        )
    )


def _invoice(api, show_id, line_id, amount_cents, headers=None, vendor_name="Stage Crew Co"):
    return get_success_data(
        api.create_vendor_invoice(
            f.vendor_invoice_payload(
                show_id,
                line_id,
                amount_cents=amount_cents,
                vendor_name=vendor_name,
                invoice_date="2026-08-01",
            ),
            headers or ALICE,
        )
    )


def _calculated_settlement(api, build, ctx, calculate_headers=None):
    """Perform the show and calculate its settlement, returning the settlement row."""
    build.set_clock(EVENT_AT)
    get_success_data(api.perform_show(ctx["show_id"], BUYER))
    book = get_success_data(api.create_settlement(f.settlement_payload(ctx["show_id"]), ALICE))
    return get_success_data(
        api.calculate_settlement(book["id"], calculate_headers or CALCULATOR)
    )


# ---------------------------------------------------------------------------
# The four two-person controls
# ---------------------------------------------------------------------------


def test_approving_an_invoice_refuses_the_user_that_verified_it(api, build):
    """A second accountant is needed to approve what the first one verified.

    PRD §2.8: "Four paired steps in this system must be performed by two different users."
    PRD §2.8: "Approving a vendor invoice requires an `X-User-ID` different from the invoice's `verified_by_user_id`."
    PRD §2.8: "These four checks are independent of role authorisation. A user may hold a role that authorises the second step and still be refused because it performed the first."
    PRD §3.6: "the line's `actual_cents` is refreshed to the total `amount_cents` of the line's invoices whose status is `APPROVED`"
    PRD §2.9: "No later rule is evaluated once one has fired, and no side effect of the operation runs."

    Design: Corner/rbac/segregation_of_duties_blocks_the_same_user_from_both_halves_of_four_pairs
    """
    ctx = _on_sale_show(api, sold_qty=0)
    line = _budget_line(api, ctx["show_id"], budgeted_cents=100_000)
    invoice = _invoice(api, ctx["show_id"], line["id"], 105_000)

    verified = get_success_data(api.verify_vendor_invoice(invoice["id"], ALICE))
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == ACCOUNTANT_ALICE

    refused = api.approve_vendor_invoice(invoice["id"], ALICE)
    validate_error(refused, E.ERR_SEGREGATION_OF_DUTIES)

    still = get_success_data(api.get_vendor_invoice(invoice["id"], ALICE))
    assert still["status"] == "VERIFIED"
    assert still["approved_by_user_id"] is None
    assert still["verified_by_user_id"] == ACCOUNTANT_ALICE
    assert still["version"] == verified["version"]
    untouched_line = get_success_data(api.get_budget_line(line["id"], ALICE))
    assert untouched_line["actual_cents"] == 0
    assert untouched_line["version"] == line["version"]

    approved = get_success_data(api.approve_vendor_invoice(invoice["id"], BOB))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == ACCOUNTANT_BOB
    assert approved["verified_by_user_id"] == ACCOUNTANT_ALICE
    recognised = get_success_data(api.get_budget_line(line["id"], ALICE))
    assert recognised["actual_cents"] == 105_000


def test_paying_a_settlement_refuses_the_user_that_signed_it(api, build):
    """The signature and the payment must come from two different identities.

    PRD §2.8: "Paying a settlement requires an `X-User-ID` different from the settlement's `signed_by_user_id`."
    PRD §3.8: "`SIGN` moves the settlement `CALCULATED → ARTIST_SIGNED` and records `signed_by_user_id` as the responding rep's `X-User-ID`, unlocking payment."
    PRD §3.8: "A `TourAccountant` pays an `ARTIST_SIGNED` settlement, supplying a required `payment_method` of `WIRE`, `CHECK` or `CASH`"
    PRD §2.9: "No later rule is evaluated once one has fired, and no side effect of the operation runs."

    Design: Corner/rbac/segregation_of_duties_blocks_the_same_user_from_both_halves_of_four_pairs
    """
    ctx = _on_sale_show(api)
    # PRD 3.7: the calculation requires the show to have at least one budget line.
    _budget_line(api, ctx["show_id"], budgeted_cents=100_000)
    settlement = _calculated_settlement(api, build, ctx)
    signed = get_success_data(
        api.respond_to_settlement(
            settlement["id"],
            make_artist_rep_headers(ctx["artist_id"]),
            response="SIGN",
        )
    )
    assert signed["status"] == "ARTIST_SIGNED"
    assert signed["signed_by_user_id"] == ctx["artist_id"]

    # The signer's identity, re-presented behind the paying role, is still the signer.
    refused = api.pay_settlement(
        settlement["id"],
        make_tour_accountant_headers(ctx["artist_id"]),
        payment_method="WIRE",
        payment_reference="WIRE-SD-0001",
    )
    validate_error(refused, E.ERR_SEGREGATION_OF_DUTIES)

    still = get_success_data(api.get_settlement(settlement["id"], ALICE))
    assert still["status"] == "ARTIST_SIGNED"
    assert still["paid_at"] is None
    assert still["payment_method"] is None
    assert still["payment_reference"] is None
    assert still["version"] == signed["version"]

    paid = get_success_data(
        api.pay_settlement(
            settlement["id"], BOB, payment_method="WIRE", payment_reference="WIRE-SD-0002"
        )
    )
    assert paid["status"] == "PAID"
    assert paid["payment_method"] == "WIRE"
    assert paid["payment_reference"] == "WIRE-SD-0002"
    assert paid["signed_by_user_id"] == ctx["artist_id"]


def test_reopening_a_settlement_refuses_the_user_that_calculated_it(api, build):
    """The accountant who ran the waterfall cannot reopen its own numbers.

    PRD §2.8: "Reopening a settlement requires an `X-User-ID` different from the settlement's `calculated_by_user_id`."
    PRD §3.7: "the settlement's `calculated_by_user_id` records the calculating accountant's opaque `X-User-ID`"
    PRD §3.8: "Reopening increases `reopen_count` by 1, records the `reopen_reason`, and clears `signed_by_user_id` to null"
    PRD §2.8: "These four checks are independent of role authorisation. A user may hold a role that authorises the second step and still be refused because it performed the first."

    Design: Corner/rbac/segregation_of_duties_blocks_the_same_user_from_both_halves_of_four_pairs
    """
    ctx = _on_sale_show(api)
    # PRD 3.7: the calculation requires the show to have at least one budget line.
    _budget_line(api, ctx["show_id"], budgeted_cents=100_000)
    settlement = _calculated_settlement(api, build, ctx, calculate_headers=CALCULATOR)
    assert settlement["status"] == "CALCULATED"
    assert settlement["calculated_by_user_id"] == "u-sd-calc"

    refused = api.reopen_settlement(
        settlement["id"],
        make_risk_officer_headers("u-sd-calc"),
        reopen_reason="the calculating accountant wants another look",
    )
    validate_error(refused, E.ERR_SEGREGATION_OF_DUTIES)

    still = get_success_data(api.get_settlement(settlement["id"], ALICE))
    assert still["status"] == "CALCULATED"
    assert still["reopen_count"] == 0
    assert still["reopen_reason"] is None
    assert still["version"] == settlement["version"]

    reopened = get_success_data(
        api.reopen_settlement(
            settlement["id"], RITA, reopen_reason="the venue produced a late rental invoice"
        )
    )
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened["reopen_reason"] == "the venue produced a late rental invoice"
    assert reopened["signed_by_user_id"] is None
    assert reopened["calculated_by_user_id"] == "u-sd-calc"


@pytest.mark.parametrize(
    "outcome,extra,end_status",
    [
        ("SETTLE", {"insurer_reference": "INS-SD-77"}, "CLAIM_SETTLED"),
        ("DENY", {"reason": "the policy excludes an artist-side cancellation"}, "CLAIM_DENIED"),
    ],
    ids=["settle", "deny"],
)
def test_settling_a_claim_refuses_the_user_that_filed_it(api, build, outcome, extra, end_status):
    """The insurer's answer must be recorded by a risk officer other than the filer.

    PRD §2.8: "Settling or denying an insurance claim requires an `X-User-ID` different from the event's `filed_by_user_id`."
    PRD §3.9: "The insurer's answer arrives as a second `RiskOfficer` call carrying an `outcome`, and the acting `X-User-ID` must differ from the event's `filed_by_user_id`."
    PRD §3.9: "A `RiskOfficer` then files an insurance claim, moving the event `REFUNDS_PROCESSED → CLAIM_FILED`, supplying a `claim_amount_cents` greater than 0 and a `claim_documentation_ref` filed with the insurer, and recording `filed_by_user_id`."
    PRD §2.9: "No later rule is evaluated once one has fired, and no side effect of the operation runs."

    Design: Corner/rbac/segregation_of_duties_blocks_the_same_user_from_both_halves_of_four_pairs
    """
    ctx = _on_sale_show(api)
    event = get_success_data(
        api.create_cancellation_event(
            f.cancellation_event_payload(ctx["show_id"], kind="CANCELLED"), RITA
        )
    )
    get_success_data(api.process_refunds(event["id"], ALICE))
    filed = get_success_data(
        api.file_claim(
            event["id"], RITA, claim_amount_cents=300_000, claim_documentation_ref="DOC-SD-9"
        )
    )
    assert filed["status"] == "CLAIM_FILED"
    assert filed["filed_by_user_id"] == RISK_RITA

    refused = api.settle_claim(event["id"], RITA, outcome=outcome, **extra)
    validate_error(refused, E.ERR_SEGREGATION_OF_DUTIES)

    still = get_success_data(api.get_cancellation_event(event["id"], RITA))
    assert still["status"] == "CLAIM_FILED"
    assert still["filed_by_user_id"] == RISK_RITA
    assert still["version"] == filed["version"]

    answered = get_success_data(api.settle_claim(event["id"], ROB, outcome=outcome, **extra))
    assert answered["status"] == end_status
    assert answered["filed_by_user_id"] == RISK_RITA


# ---------------------------------------------------------------------------
# The two entity-backed identities are peers of each other
# ---------------------------------------------------------------------------


def _peer_world(api):
    """Two acts and two rooms in one market, so every owner has a rival peer."""
    market = _market(api)
    return {
        "market": market,
        "act_one": _artist(api, historical_sellthrough_pct=61.00),
        "act_two": _artist(api, historical_sellthrough_pct=57.00),
        "hall_one": _venue(api, market["id"], name="Peer Hall One"),
        "hall_two": _venue(api, market["id"], name="Peer Hall Two"),
    }


def test_only_the_booked_act_may_accept_the_offer(api, build):
    """A rival rep holds the accepting role and still cannot say yes.

    PRD §2.1: "When `X-User-Role` is `ArtistRep`, `X-User-ID` is the `id` of the acting `Artist`; ownership checks on any resource that references an `Artist` compare the resource's foreign-key field to `X-User-ID`."
    PRD §2.1: "When an entity-backed role acts on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §3.3: "An `ArtistRep` whose `X-User-ID` equals the show's `artist_id` accepts a `SUBMITTED` offer on a show that is still `PLANNED`; the offer moves `SUBMITTED → ACCEPTED` and, in the same request, the show moves `PLANNED → CONFIRMED`."
    PRD §2.1: "It is also recorded as `accepted_by_user_id` on an accepted `Offer` and as `signed_by_user_id` on a signed `Settlement`."

    Design: Corner/rbac/entity_backed_roles_reach_only_their_own_act_or_room
    """
    world = _peer_world(api)
    show = _show(api, world["act_one"]["id"], world["hall_one"]["id"])
    offer = _submitted_offer(api, show)

    refused = api.accept_offer(offer["id"], make_artist_rep_headers(world["act_two"]["id"]))
    validate_error(refused, E.ERR_NOT_RESOURCE_OWNER)

    still = get_success_data(api.get_offer(offer["id"], BUYER))
    assert still["status"] == "SUBMITTED"
    assert still["accepted_by_user_id"] is None
    assert get_success_data(api.get_show(show["id"], BUYER))["show_status"] == "PLANNED"

    accepted = get_success_data(
        api.accept_offer(offer["id"], make_artist_rep_headers(world["act_one"]["id"]))
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_by_user_id"] == world["act_one"]["id"]
    assert get_success_data(api.get_show(show["id"], BUYER))["show_status"] == "CONFIRMED"


def test_only_the_booked_act_may_counter_the_offer(api, build):
    """The same ownership rule guards the other exclusive artist-side verb.

    PRD §2.1: "Concretely, on any offer, settlement or hold action the acting rep's `X-User-ID` must equal the `artist_id` of the show in question."
    PRD §3.2: "A counter is authored by an `ArtistRep` whose `X-User-ID` equals the show's `artist_id`, requires the show to still be `PLANNED`, and records what the artist side asked for: `counter_guarantee_cents` is required, `counter_versus_pct` and `counter_backend_split_artist_pct` are optional, and a required `counter_note` carries free text."
    PRD §3.2: "Countering also clears `expires_at` to null — the clock stops while the ball is in the promoter's court."
    PRD §2.1: "When an entity-backed role acts on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/entity_backed_roles_reach_only_their_own_act_or_room
    """
    world = _peer_world(api)
    show = _show(
        api,
        world["act_two"]["id"],
        world["hall_two"]["id"],
        event_at=SECOND_EVENT_AT,
        load_in_at=SECOND_LOAD_IN_AT,
        load_out_at=SECOND_LOAD_OUT_AT,
    )
    offer = _submitted_offer(api, show)

    refused = api.counter_offer(
        offer["id"],
        make_artist_rep_headers(world["act_one"]["id"]),
        counter_guarantee_cents=150_000,
        counter_note="Act One's rep countering Act Two's offer",
    )
    validate_error(refused, E.ERR_NOT_RESOURCE_OWNER)

    still = get_success_data(api.get_offer(offer["id"], BUYER))
    assert still["status"] == "SUBMITTED"
    assert still["counter_guarantee_cents"] is None
    assert still["counter_note"] is None

    countered = get_success_data(
        api.counter_offer(
            offer["id"],
            make_artist_rep_headers(world["act_two"]["id"]),
            counter_guarantee_cents=150_000,
            counter_note="Needs another fifteen hundred to clear the bus",
        )
    )
    assert countered["status"] == "COUNTERED"
    assert countered["counter_guarantee_cents"] == 150_000
    assert countered["counter_note"] == "Needs another fifteen hundred to clear the bus"
    assert countered["expires_at"] is None


HOLD_OWNERSHIP = [
    ("ARTIST_HOLD", 4, "act_one", "act_two", "artist", "Act One guest list"),
    ("PRODUCTION_HOLD", 5, "hall_one", "hall_two", "venue", "Front-of-house kill"),
]


@pytest.mark.parametrize(
    "kind,qty,owner_key,rival_key,identity,holder",
    HOLD_OWNERSHIP,
    ids=["artist_hold", "production_hold"],
)
def test_an_entity_backed_role_may_only_hold_seats_on_its_own_show(
    api, build, kind, qty, owner_key, rival_key, identity, holder
):
    """A rival act or a rival room cannot pull seats out of someone else's house.

    PRD §3.5: "Holds may be created by a `TalentBuyer`, an `ArtistRep` or a `VenueOperator`, but the two entity-backed roles are narrowly scoped: an `ArtistRep` may only create `ARTIST_HOLD` seats, and only on shows whose `artist_id` equals its `X-User-ID`; a `VenueOperator` may only create `PRODUCTION_HOLD` seats, and only on shows whose `venue_id` equals its `X-User-ID`. Acting outside that scope yields `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.5: "A hold is created in status `HELD` with `released_by_user_id` null."
    PRD §2.9: "No later rule is evaluated once one has fired, and no side effect of the operation runs."

    Design: Corner/rbac/entity_backed_roles_reach_only_their_own_act_or_room
    """
    world = _peer_world(api)
    ctx = _on_sale_show(
        api,
        world={
            "market": world["market"],
            "artist": world["act_one"],
            "venue": world["hall_one"],
        },
    )
    make = make_artist_rep_headers if identity == "artist" else make_venue_operator_headers

    refused = api.create_ticket_hold(
        f.ticket_hold_payload(
            ctx["tier_id"], kind=kind, qty=qty, holder="A rival peer papering this show"
        ),
        make(world[rival_key]["id"]),
    )
    validate_error(refused, E.ERR_NOT_RESOURCE_OWNER)

    empty, meta = validate_paginated(api.list_ticket_holds(BUYER, ticket_tier_id=ctx["tier_id"]))
    assert meta["total_count"] == 0
    assert empty == []

    held = get_success_data(
        api.create_ticket_hold(
            f.ticket_hold_payload(ctx["tier_id"], kind=kind, qty=qty, holder=holder),
            make(world[owner_key]["id"]),
        )
    )
    assert held["status"] == "HELD"
    assert held["kind"] == kind
    assert held["qty"] == qty
    assert held["released_by_user_id"] is None


def test_inventory_moves_only_for_the_owning_identities(api, build):
    """The two refused holds leave no seats behind, and the two owned holds reverse exactly.

    PRD §3.5: "the two entity-backed roles are narrowly scoped: an `ArtistRep` may only create `ARTIST_HOLD` seats, and only on shows whose `artist_id` equals its `X-User-ID`"
    PRD §3.5: "The hold moves `HELD → RELEASED`, its `released_by_user_id` records the acting `X-User-ID`, and the inventory movement is exactly reversed: the tier's `held_qty` — or its `comp_qty`, when the hold's kind is `COMP` — decreases by the hold's `qty` and its `available_qty` increases by the same amount."
    PRD §3.5: "an `ArtistRep` may release only `ARTIST_HOLD` holds on shows whose `artist_id` matches its own identity; a `VenueOperator` may release only `PRODUCTION_HOLD` holds on shows whose `venue_id` matches its own identity."

    Design: Corner/rbac/entity_backed_roles_reach_only_their_own_act_or_room
    """
    world = _peer_world(api)
    ctx = _on_sale_show(
        api,
        world={
            "market": world["market"],
            "artist": world["act_one"],
            "venue": world["hall_one"],
        },
    )
    rep = make_artist_rep_headers(world["act_one"]["id"])
    operator = make_venue_operator_headers(world["hall_one"]["id"])

    validate_error(
        api.create_ticket_hold(
            f.ticket_hold_payload(
                ctx["tier_id"], kind="ARTIST_HOLD", qty=4, holder="Act Two guest list"
            ),
            make_artist_rep_headers(world["act_two"]["id"]),
        ),
        E.ERR_NOT_RESOURCE_OWNER,
    )
    validate_error(
        api.create_ticket_hold(
            f.ticket_hold_payload(
                ctx["tier_id"], kind="PRODUCTION_HOLD", qty=5, holder="Hall Two kill"
            ),
            make_venue_operator_headers(world["hall_two"]["id"]),
        ),
        E.ERR_NOT_RESOURCE_OWNER,
    )

    artist_hold = get_success_data(
        api.create_ticket_hold(
            f.ticket_hold_payload(
                ctx["tier_id"], kind="ARTIST_HOLD", qty=4, holder="Act One guest list"
            ),
            rep,
        )
    )
    production_hold = get_success_data(
        api.create_ticket_hold(
            f.ticket_hold_payload(
                ctx["tier_id"], kind="PRODUCTION_HOLD", qty=5, holder="Front-of-house kill"
            ),
            operator,
        )
    )

    after_holds = get_success_data(api.get_ticket_tier(ctx["tier_id"], BUYER))
    assert after_holds["held_qty"] == 9
    assert after_holds["available_qty"] == 91

    released_production = get_success_data(api.release_ticket_hold(production_hold["id"], operator))
    assert released_production["status"] == "RELEASED"
    assert released_production["released_by_user_id"] == world["hall_one"]["id"]
    released_artist = get_success_data(api.release_ticket_hold(artist_hold["id"], rep))
    assert released_artist["status"] == "RELEASED"
    assert released_artist["released_by_user_id"] == world["act_one"]["id"]

    after_releases = get_success_data(api.get_ticket_tier(ctx["tier_id"], BUYER))
    assert after_releases["held_qty"] == 0
    assert after_releases["available_qty"] == 100


def test_a_hold_may_only_be_released_by_the_identity_that_owns_it(api, build):
    """A rival room and a rival act are both refused at the release, one rule after the role gate.

    PRD §3.5: "A `TalentBuyer` may release any hold on any show; an `ArtistRep` may release only `ARTIST_HOLD` holds on shows whose `artist_id` matches its own identity; a `VenueOperator` may release only `PRODUCTION_HOLD` holds on shows whose `venue_id` matches its own identity."
    PRD §2.1: "This ownership check guards offer acceptance, offer counters, the artist's settlement response, hold creation, hold release, vendor-invoice creation and vendor-invoice dispute."
    PRD §2.1: "When an entity-backed role acts on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/entity_backed_roles_reach_only_their_own_act_or_room
    """
    world = _peer_world(api)
    ctx = _on_sale_show(
        api,
        world={
            "market": world["market"],
            "artist": world["act_one"],
            "venue": world["hall_one"],
        },
    )
    artist_hold = get_success_data(
        api.create_ticket_hold(
            f.ticket_hold_payload(
                ctx["tier_id"], kind="ARTIST_HOLD", qty=4, holder="Act One guest list"
            ),
            make_artist_rep_headers(world["act_one"]["id"]),
        )
    )
    production_hold = get_success_data(
        api.create_ticket_hold(
            f.ticket_hold_payload(
                ctx["tier_id"], kind="PRODUCTION_HOLD", qty=5, holder="Front-of-house kill"
            ),
            make_venue_operator_headers(world["hall_one"]["id"]),
        )
    )

    validate_error(
        api.release_ticket_hold(
            production_hold["id"], make_venue_operator_headers(world["hall_two"]["id"])
        ),
        E.ERR_NOT_RESOURCE_OWNER,
    )
    validate_error(
        api.release_ticket_hold(
            artist_hold["id"], make_artist_rep_headers(world["act_two"]["id"])
        ),
        E.ERR_NOT_RESOURCE_OWNER,
    )

    for hold in (artist_hold, production_hold):
        unchanged = get_success_data(api.get_ticket_hold(hold["id"], BUYER))
        assert unchanged["status"] == "HELD"
        assert unchanged["released_by_user_id"] is None
        assert unchanged["version"] == hold["version"]
    tier = get_success_data(api.get_ticket_tier(ctx["tier_id"], BUYER))
    assert tier["held_qty"] == 9
    assert tier["available_qty"] == 91


def test_only_the_hosting_room_may_paper_or_dispute_the_invoice(api, build):
    """The venue-side identity is scoped to the room that hosted the show.

    PRD §2.1: "When `X-User-Role` is `VenueOperator`, `X-User-ID` is the `id` of the acting `Venue`; ownership checks on any resource that references a `Venue` compare the resource's foreign-key field to `X-User-ID`."
    PRD §2.1: "Concretely, the acting operator's `X-User-ID` must equal the `venue_id` of the show being invoiced, disputed or held against."
    PRD §3.6: "A `VenueOperator` may only invoice shows whose `venue_id` equals its own identity."
    PRD §3.6: "An invoice that has not yet been approved can be disputed by a `TourAccountant` or the `VenueOperator` that owns the venue, moving it `SUBMITTED → DISPUTED` or `VERIFIED → DISPUTED` and recording a `dispute_reason`."

    Design: Corner/rbac/entity_backed_roles_reach_only_their_own_act_or_room
    """
    world = _peer_world(api)
    ctx = _on_sale_show(
        api,
        world={
            "market": world["market"],
            "artist": world["act_one"],
            "venue": world["hall_one"],
        },
    )
    line = _budget_line(api, ctx["show_id"], budgeted_cents=100_000)
    hall_one = make_venue_operator_headers(world["hall_one"]["id"])
    hall_two = make_venue_operator_headers(world["hall_two"]["id"])

    refused = api.create_vendor_invoice(
        f.vendor_invoice_payload(
            ctx["show_id"],
            line["id"],
            amount_cents=60_000,
            vendor_name="Hall Two Labour",
            invoice_date="2026-08-01",
        ),
        hall_two,
    )
    validate_error(refused, E.ERR_NOT_RESOURCE_OWNER)
    _, meta = validate_paginated(api.list_vendor_invoices(ALICE, show_id=ctx["show_id"]))
    assert meta["total_count"] == 0

    invoice = _invoice(
        api, ctx["show_id"], line["id"], 60_000, headers=hall_one, vendor_name="Hall One Labour"
    )
    assert invoice["status"] == "SUBMITTED"

    refused_dispute = api.dispute_vendor_invoice(
        invoice["id"], hall_two, dispute_reason="Hall Two disputing Hall One's paperwork"
    )
    validate_error(refused_dispute, E.ERR_NOT_RESOURCE_OWNER)
    still = get_success_data(api.get_vendor_invoice(invoice["id"], ALICE))
    assert still["status"] == "SUBMITTED"
    assert still["dispute_reason"] is None
    assert still["version"] == invoice["version"]

    disputed = get_success_data(
        api.dispute_vendor_invoice(
            invoice["id"], hall_one, dispute_reason="Hours were logged against the wrong call"
        )
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "Hours were logged against the wrong call"


def test_only_the_act_that_played_may_sign_the_settlement(api, build):
    """The artist-side response is ownership-scoped exactly like acceptance.

    PRD §3.8: "An `ArtistRep` whose `X-User-ID` equals the show's `artist_id` supplies a `response` of either `SIGN` or `DISPUTE`, and the two branches leave the same state for different targets with different effects."
    PRD §2.1: "This ownership check guards offer acceptance, offer counters, the artist's settlement response, hold creation, hold release, vendor-invoice creation and vendor-invoice dispute."
    PRD §3.8: "`SIGN` moves the settlement `CALCULATED → ARTIST_SIGNED` and records `signed_by_user_id` as the responding rep's `X-User-ID`, unlocking payment."

    Design: Corner/rbac/entity_backed_roles_reach_only_their_own_act_or_room
    """
    world = _peer_world(api)
    ctx = _on_sale_show(
        api,
        world={
            "market": world["market"],
            "artist": world["act_one"],
            "venue": world["hall_one"],
        },
    )
    _budget_line(api, ctx["show_id"], budgeted_cents=100_000)
    settlement = _calculated_settlement(api, build, ctx)
    assert settlement["status"] == "CALCULATED"

    refused = api.respond_to_settlement(
        settlement["id"], make_artist_rep_headers(world["act_two"]["id"]), response="SIGN"
    )
    validate_error(refused, E.ERR_NOT_RESOURCE_OWNER)

    still = get_success_data(api.get_settlement(settlement["id"], ALICE))
    assert still["status"] == "CALCULATED"
    assert still["signed_by_user_id"] is None
    assert still["version"] == settlement["version"]

    signed = get_success_data(
        api.respond_to_settlement(
            settlement["id"], make_artist_rep_headers(world["act_one"]["id"]), response="SIGN"
        )
    )
    assert signed["status"] == "ARTIST_SIGNED"
    assert signed["signed_by_user_id"] == world["act_one"]["id"]


def test_ownership_does_not_scope_the_read_endpoints(api, build):
    """A rival act and a rival room may still read the show and its tiers.

    PRD §2.1: "This ownership check guards offer acceptance, offer counters, the artist's settlement response, hold creation, hold release, vendor-invoice creation and vendor-invoice dispute."
    PRD §4: "| GET | /shows/{show_id} | Retrieve a single show including sales counters, exposure figures and settlement projections. | TalentBuyer, TourAccountant, RiskOfficer, ArtistRep, VenueOperator |"
    PRD §4: "| GET | /ticket-tiers | List ticket tiers, optionally filtered by `show_id` and `status`. | TalentBuyer, TourAccountant, RiskOfficer, ArtistRep, VenueOperator |"

    Design: Corner/rbac/entity_backed_roles_reach_only_their_own_act_or_room
    """
    world = _peer_world(api)
    ctx = _on_sale_show(
        api,
        world={
            "market": world["market"],
            "artist": world["act_one"],
            "venue": world["hall_one"],
        },
    )

    rival_read = get_success_data(
        api.get_show(ctx["show_id"], make_artist_rep_headers(world["act_two"]["id"]))
    )
    assert rival_read["id"] == ctx["show_id"]
    assert rival_read["show_status"] == "ON_SALE"

    tiers, meta = validate_paginated(
        api.list_ticket_tiers(
            make_venue_operator_headers(world["hall_two"]["id"]), show_id=ctx["show_id"]
        )
    )
    assert meta["total_count"] == 1
    assert [tier["id"] for tier in tiers] == [ctx["tier_id"]]


@pytest.mark.parametrize(
    "identity,valuation",
    [("artist", None), ("venue", "MARK_TO_MARKET")],
    ids=["artist_rep", "venue_operator"],
)
def test_the_portfolio_read_is_closed_to_both_entity_backed_roles(api, build, identity, valuation):
    """The one GET the two entity-backed roles may not call fails at the role gate, not the owner gate.

    PRD §2.1: "If `X-User-Role` holds any other string, or holds one of the five but that role is not listed as authorised for the endpoint being called, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."
    PRD §4: "| GET | /markets/{market_id}/portfolio-risk | Compute the market's exposure book and performance index under the requested `valuation` basis without persisting anything. | TalentBuyer, TourAccountant, RiskOfficer |"

    Design: Corner/rbac/entity_backed_roles_reach_only_their_own_act_or_room
    """
    world = _peer_world(api)
    if identity == "artist":
        headers = make_artist_rep_headers(world["act_one"]["id"])
    else:
        headers = make_venue_operator_headers(world["hall_one"]["id"])

    refused = api.get_portfolio_risk(world["market"]["id"], headers, valuation=valuation)
    validate_error(refused, E.ERR_ROLE_FORBIDDEN)

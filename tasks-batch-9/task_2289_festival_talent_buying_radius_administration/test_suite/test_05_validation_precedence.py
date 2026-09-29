"""Which failure a doubly-invalid request reports, and the control that proves
the masked check is genuinely reachable.

Every test builds its own preconditions from an empty database and sets the
logical clock explicitly, because the server is restarted before each test.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    BUSINESS_AFFAIRS,
    TALENT_BUYER,
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx
from test_helpers.factories import counter_payload, revise_payload

JAZZ_WINDOW_START = "2026-11-04"
JAZZ_WINDOW_END = "2026-12-14"
ONE_CENT_OVER_CEILING_CENTS = 500001


# --------------------------------------------------------------- module helpers
def _accepted_and_countered_jazz_offers(api):
    """Two low-draw acts whose guarantee ceiling is 500000 cents apiece.

    Offer X has been accepted, so it is terminal; offer Y has been countered,
    so it is still on the promoter's side of the negotiation loop.
    """
    ctx = fx.single_tier_edition(
        api,
        tier_overrides={"max_slots": 4, "genre_focus": "MIXED"},
        artist_overrides={
            "legal_name": "Vela Trio LLC",
            "performing_name": "Vela Trio",
            "primary_genre": "JAZZ_SOUL",
            "agency": "Foghorn Agency",
            "draw_score": 20,
            "default_radius_miles": 75,
        },
    )
    artist_y = fx.create_artist(
        api,
        legal_name="Marrow Street LLC",
        performing_name="Marrow Street",
        primary_genre="JAZZ_SOUL",
        agency="Foghorn Agency",
        draw_score=20,
        default_radius_miles=75,
    )
    terms = {
        "guarantee_cents": 400000,
        "radius_miles": 75,
        "window_start_date": JAZZ_WINDOW_START,
        "window_end_date": JAZZ_WINDOW_END,
    }
    offer_x = fx.issued_offer(
        api, ctx, ctx["artist"], slot_start_utc="2026-12-04T21:00:00Z", **terms
    )
    validate_success(
        api.accept_offer(
            offer_x["id"], make_artist_rep_headers(ctx["artist"]["id"])
        ),
        201,
    )
    offer_y = fx.issued_offer(
        api, ctx, artist_y, slot_start_utc="2026-12-05T21:00:00Z", **terms
    )
    validate_success(
        api.counter_offer(
            offer_y["id"],
            counter_payload(
                counter_guarantee_cents=ONE_CENT_OVER_CEILING_CENTS,
                counter_note="Agency wants 5000.01",
            ),
            make_artist_rep_headers(artist_y["id"]),
        )
    )
    return {"ctx": ctx, "offer_x": offer_x, "offer_y": offer_y, "artist_y": artist_y}


def _two_rider_settled_bookings_one_breached(api):
    """Two RIDER_SETTLED bookings without advance packets; the first is breached."""
    ctx = fx.single_tier_edition(api)
    artist_two = fx.create_artist(
        api, legal_name="Glass Harbor Inc", performing_name="Glass Harbor"
    )
    first = fx.rider_settled_booking(
        api,
        ctx,
        ctx["artist"],
        guarantee_cents=1500000,
        slot_start_utc="2026-12-04T21:00:00Z",
    )
    second = fx.rider_settled_booking(
        api,
        ctx,
        artist_two,
        guarantee_cents=1500000,
        slot_start_utc="2026-12-05T21:00:00Z",
    )
    performance = fx.report_performance(api, ctx["artist"]["id"])
    fx.adjudicate(api, performance["id"], "VIOLATION", "Inside the radius window")
    return {
        "ctx": ctx,
        "breached_booking": first["booking"],
        "clean_booking": second["booking"],
    }


def _one_booked_slot_and_two_clashing_drafts(api):
    """A live 21:00-22:30 booking plus two drafts that both reuse billing position 1.

    The first draft also overlaps the booking's buffered interval; the second
    starts at 17:00 and clears the buffer on both sides.
    """
    ctx = fx.single_tier_edition(
        api, tier_overrides={"max_slots": 4, "genre_focus": "MIXED"}
    )
    artist_pop = fx.create_artist(
        api,
        legal_name="Pale Signal LLC",
        performing_name="Pale Signal",
        primary_genre="POP",
        agency="Foghorn Agency",
        draw_score=60,
        default_radius_miles=100,
    )
    artist_country = fx.create_artist(
        api,
        legal_name="Hollow Pines LLC",
        performing_name="Hollow Pines",
        primary_genre="COUNTRY",
        agency="Foghorn Agency",
        draw_score=60,
        default_radius_miles=100,
    )
    fx.accepted_booking(
        api,
        ctx,
        ctx["artist"],
        guarantee_cents=1500000,
        slot_start_utc="2026-12-05T21:00:00Z",
    )
    draft_terms = {
        "guarantee_cents": 1000000,
        "radius_miles": 100,
        "window_start_date": JAZZ_WINDOW_START,
        "window_end_date": JAZZ_WINDOW_END,
    }
    overlapping = fx.draft_offer(
        api, ctx, artist_pop, slot_start_utc="2026-12-05T21:30:00Z", **draft_terms
    )
    clear_of_the_buffer = fx.draft_offer(
        api, ctx, artist_country, slot_start_utc="2026-12-05T17:00:00Z", **draft_terms
    )
    return {
        "ctx": ctx,
        "overlapping": overlapping,
        "clear_of_the_buffer": clear_of_the_buffer,
    }


# ----------------------------------------- an accepted offer masks its own ceiling
def test_revising_an_accepted_offer_reports_the_terminal_state_not_the_ceiling(api):
    """The terminal offer answers with its state error and keeps its old guarantee.

    "`ACCEPTED`, `DECLINED`, `EXPIRED` and `SUPERSEDED` are all terminal: a further negotiation call against any of them is `ERR_OFFER_NOT_NEGOTIABLE`, which is also what a repeat call on an already-transitioned offer returns."
    "An offer whose `guarantee_cents` plus `production_fee_cents` exceeds that ceiling is refused with `ERR_GUARANTEE_CEILING_EXCEEDED`; equality with the ceiling passes."
    Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_on_offer_revise
    """
    world = _accepted_and_countered_jazz_offers(api)

    error = validate_error(
        api.revise_offer(
            world["offer_x"]["id"],
            revise_payload(guarantee_cents=ONE_CENT_OVER_CEILING_CENTS),
            TALENT_BUYER,
        ),
        "ERR_OFFER_NOT_NEGOTIABLE",
        409,
    )

    assert error["error_id"] != "ERR_GUARANTEE_CEILING_EXCEEDED"
    offer_x = validate_success(api.get_offer(world["offer_x"]["id"], TALENT_BUYER))
    assert offer_x["guarantee_cents"] == 400000
    assert offer_x["status"] == "ACCEPTED"


def test_revising_a_countered_offer_over_its_ceiling_reports_the_fiscal_refusal(api):
    """The same body against a live offer reaches the ceiling check and fails there.

    "An offer whose `guarantee_cents` plus `production_fee_cents` exceeds that ceiling is refused with `ERR_GUARANTEE_CEILING_EXCEEDED`; equality with the ceiling passes."
    "The promoter answers a counter by revising, which is the cycle edge: the offer returns from `COUNTERED` to `ISSUED` and one round is consumed."
    Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_on_offer_revise
    """
    world = _accepted_and_countered_jazz_offers(api)

    validate_error(
        api.revise_offer(
            world["offer_y"]["id"],
            revise_payload(guarantee_cents=ONE_CENT_OVER_CEILING_CENTS),
            TALENT_BUYER,
        ),
        "ERR_GUARANTEE_CEILING_EXCEEDED",
        422,
    )

    offer_y = validate_success(api.get_offer(world["offer_y"]["id"], TALENT_BUYER))
    assert offer_y["status"] == "COUNTERED"
    assert offer_y["round_number"] == 1
    assert offer_y["guarantee_cents"] == 400000


# --------------------------------- a breached clause masks the missing advance
def test_countersigning_a_breached_booking_reports_the_radius_breach(api):
    """The breach answers before the missing advance packet is even considered.

    "It requires the booking's `contract_status` to be `RIDER_SETTLED`, requires the booking's radius clause to be in `ACTIVE` or `WAIVED` — a `BREACHED` clause is refused with `ERR_RADIUS_BREACH_ACTIVE` — and requires the booking to have at least one advance packet in `APPROVED`, without which the answer is `ERR_ADVANCE_NOT_APPROVED`."
    Design: Difficulty/priority_pair_validation_conflict/safety_over_referential_on_countersign
    """
    world = _two_rider_settled_bookings_one_breached(api)

    validate_error(
        api.countersign_booking(world["breached_booking"]["id"], BUSINESS_AFFAIRS),
        "ERR_RADIUS_BREACH_ACTIVE",
        409,
    )

    booking = validate_success(
        api.get_booking(world["breached_booking"]["id"], TALENT_BUYER)
    )
    assert booking["contract_status"] == "RIDER_SETTLED"
    assert booking["settlement_status"] == "WITHHELD"


def test_countersigning_a_clean_booking_reports_the_missing_advance_packet(api):
    """With an ACTIVE clause the referential check is reached and refuses instead.

    "It requires the booking's `contract_status` to be `RIDER_SETTLED`, requires the booking's radius clause to be in `ACTIVE` or `WAIVED` — a `BREACHED` clause is refused with `ERR_RADIUS_BREACH_ACTIVE` — and requires the booking to have at least one advance packet in `APPROVED`, without which the answer is `ERR_ADVANCE_NOT_APPROVED`."
    Design: Difficulty/priority_pair_validation_conflict/safety_over_referential_on_countersign
    """
    world = _two_rider_settled_bookings_one_breached(api)

    validate_error(
        api.countersign_booking(world["clean_booking"]["id"], BUSINESS_AFFAIRS),
        "ERR_ADVANCE_NOT_APPROVED",
        409,
    )

    booking = validate_success(
        api.get_booking(world["clean_booking"]["id"], TALENT_BUYER)
    )
    assert booking["contract_status"] == "RIDER_SETTLED"
    assert booking["settlement_status"] == "UNFUNDED"


def test_the_two_countersign_refusals_differ_only_in_their_error_identifier(api):
    """Both refusals share their status code, so only the identifier tells them apart.

    "The `error_id` is a unique, machine-readable string that identifies the specific error."
    "It requires the booking's `contract_status` to be `RIDER_SETTLED`, requires the booking's radius clause to be in `ACTIVE` or `WAIVED` — a `BREACHED` clause is refused with `ERR_RADIUS_BREACH_ACTIVE` — and requires the booking to have at least one advance packet in `APPROVED`, without which the answer is `ERR_ADVANCE_NOT_APPROVED`."
    Design: Difficulty/priority_pair_validation_conflict/safety_over_referential_on_countersign
    """
    world = _two_rider_settled_bookings_one_breached(api)

    breached = api.countersign_booking(
        world["breached_booking"]["id"], BUSINESS_AFFAIRS
    )
    clean = api.countersign_booking(world["clean_booking"]["id"], BUSINESS_AFFAIRS)

    assert breached.status_code == 409
    assert clean.status_code == 409
    breached_error = validate_error(breached, "ERR_RADIUS_BREACH_ACTIVE", 409)
    clean_error = validate_error(clean, "ERR_ADVANCE_NOT_APPROVED", 409)
    assert breached_error["error_id"] != clean_error["error_id"]


# ------------------------ a buffered collision masks the taken billing position
def test_issuing_an_overlapping_offer_reports_the_stage_slot_conflict(api):
    """The buffered collision answers before the reused billing ordinal is examined.

    "A collision is `ERR_STAGE_SLOT_CONFLICT`."
    "A collision exists when, for some occupant, the evaluated set's start is strictly earlier than that occupant's end advanced by the buffer *and* that occupant's start is strictly earlier than the evaluated set's end advanced by the buffer."
    Design: Difficulty/priority_pair_validation_conflict/temporal_over_constraint_on_offer_issue
    """
    world = _one_booked_slot_and_two_clashing_drafts(api)

    validate_error(
        api.issue_offer(world["overlapping"]["id"], TALENT_BUYER),
        "ERR_STAGE_SLOT_CONFLICT",
        409,
    )

    offer = validate_success(api.get_offer(world["overlapping"]["id"], TALENT_BUYER))
    assert offer["status"] == "DRAFT"
    assert offer["round_number"] == 0


def test_issuing_a_non_overlapping_offer_reports_the_taken_billing_position(api):
    """Clear of the buffer, the same reused ordinal surfaces the constraint refusal.

    "This uniqueness is *not* enforced when the offer is first drafted; it is enforced at issuance, at revision and again at acceptance, and a clash is `ERR_BILLING_POSITION_TAKEN`."
    Design: Difficulty/priority_pair_validation_conflict/temporal_over_constraint_on_offer_issue
    """
    world = _one_booked_slot_and_two_clashing_drafts(api)

    validate_error(
        api.issue_offer(world["clear_of_the_buffer"]["id"], TALENT_BUYER),
        "ERR_BILLING_POSITION_TAKEN",
        409,
    )

    offer = validate_success(
        api.get_offer(world["clear_of_the_buffer"]["id"], TALENT_BUYER)
    )
    assert offer["status"] == "DRAFT"
    assert offer["round_number"] == 0


def test_neither_rejected_issuance_touches_the_stage_minutes_ledger(api):
    """A refused issuance reserves no stage time at all.

    "A draft commits no budget and reserves no stage time."
    Design: Difficulty/priority_pair_validation_conflict/temporal_over_constraint_on_offer_issue
    """
    world = _one_booked_slot_and_two_clashing_drafts(api)

    validate_error(
        api.issue_offer(world["overlapping"]["id"], TALENT_BUYER),
        "ERR_STAGE_SLOT_CONFLICT",
        409,
    )
    validate_error(
        api.issue_offer(world["clear_of_the_buffer"]["id"], TALENT_BUYER),
        "ERR_BILLING_POSITION_TAKEN",
        409,
    )

    stage = validate_success(api.get_stage(world["ctx"]["stage"]["id"], TALENT_BUYER))
    assert stage["booked_minutes"] == 90

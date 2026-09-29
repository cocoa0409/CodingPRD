"""Read-your-writes behaviour across every row an acceptance touches.

The harness restarts the API server before every individual test, so the test
below builds the whole Harbor Lights edition it needs from an empty database
through the public API only.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    FINANCE_CONTROLLER,
    PRODUCTION_MANAGER,
    TALENT_BUYER,
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx
from test_helpers.constants import DEFAULT_CLOCK_UTC

NOVA_SLOT_UTC = "2026-12-04T21:00:00Z"
GUARANTEE_CENTS = 1800000
SET_LENGTH_MINUTES = 90
DEPOSIT_CENTS = 900000
BALANCE_CENTS = 900000


# --------------------------------------------------------------- local builders
def harbor_lights_edition(api):
    """Allocated Harbor Lights edition: three tiers, one flagship stage, Nova Kade."""
    fx.set_clock(api, DEFAULT_CLOCK_UTC)
    festival = fx.create_festival(api)
    headliner = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=0.5,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.create_tier(
        api,
        festival["id"],
        tier_code="MID_CARD",
        tier_rank=2,
        allocation_pct=0.3,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.create_tier(
        api,
        festival["id"],
        tier_code="EMERGING",
        tier_rank=3,
        allocation_pct=0.2,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"])
    artist = fx.create_artist(api, default_radius_miles=100)
    return {
        "festival": validate_success(api.get_festival(festival["id"], TALENT_BUYER)),
        "tier": validate_success(api.get_budget_tier(headliner["id"], TALENT_BUYER)),
        "stage": stage,
        "artist": artist,
        "artist_headers": make_artist_rep_headers(artist["id"]),
    }


def assert_request_id(response):
    """Every envelope names the request that produced it."""
    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]


def test_an_acceptance_is_visible_to_the_very_next_read_of_every_touched_row(api):
    """One acceptance, then a single unretried read of tier, edition, stage and cash.

    "Consistency in this service is immediate."
    "When one operation changes a fact that another row's derived field depends on, that dependent field is recomputed before the response is written — never later, and never by the client."
    "The tier's `committed_cents` increases by the guarantee plus the production fee and its `slots_committed` increases by one; the stage's `booked_minutes` increases by the booking's `set_length_minutes`."
    "A festival's `committed_budget_cents` must always equal the sum of `committed_cents` across that festival's budget tiers, and must equally always equal the sum of `guarantee_cents` plus `production_fee_cents` over that festival's bookings whose `contract_status` is anything other than `CANCELLED`."
    "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/consistency model/writes_are_immediately_visible_to_the_next_read
    """
    ctx = harbor_lights_edition(api)
    offer = fx.issued_offer(
        api,
        ctx,
        guarantee_cents=GUARANTEE_CENTS,
        billing_position=1,
        set_length_minutes=SET_LENGTH_MINUTES,
        slot_start_utc=NOVA_SLOT_UTC,
    )

    # The write response itself already carries the committed booking.
    accept_response = api.accept_offer(offer["id"], ctx["artist_headers"])
    booking = validate_success(accept_response, 201)
    assert_request_id(accept_response)
    assert booking["contract_status"] == "PENDING_RIDER"
    assert booking["guarantee_cents"] == GUARANTEE_CENTS

    # First read of the tier after the write, with no delay and no retry.
    tier_response = api.get_budget_tier(ctx["tier"]["id"], FINANCE_CONTROLLER)
    tier = validate_success(tier_response)
    assert_request_id(tier_response)
    assert tier["committed_cents"] == GUARANTEE_CENTS
    assert tier["slots_committed"] == 1

    summary_response = api.get_budget_summary(ctx["festival"]["id"], FINANCE_CONTROLLER)
    summary = validate_success(summary_response)
    assert_request_id(summary_response)
    assert summary["committed_budget_cents"] == GUARANTEE_CENTS
    assert summary["tier_committed_sum_cents"] == GUARANTEE_CENTS
    assert summary["booking_committed_sum_cents"] == GUARANTEE_CENTS

    stage_response = api.get_stage(ctx["stage"]["id"], PRODUCTION_MANAGER)
    stage = validate_success(stage_response)
    assert_request_id(stage_response)
    assert stage["booked_minutes"] == SET_LENGTH_MINUTES

    installments_response = api.list_payment_installments(
        booking["id"], FINANCE_CONTROLLER
    )
    rows, meta = validate_paginated(installments_response)
    assert_request_id(installments_response)
    assert meta["total_count"] == 2
    assert [row["amount_cents"] for row in rows] == [DEPOSIT_CENTS, BALANCE_CENTS]

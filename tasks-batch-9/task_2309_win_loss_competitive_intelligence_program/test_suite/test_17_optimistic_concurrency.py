"""
The two version-guarded writes: a stale expectation is refused, a refetched one is
honoured, and the honoured write moves the guarded row's version again.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_STALE_DEAL_VERSION,
    ERR_STALE_PROGRAM_VERSION,
)
from test_helpers.assertions import (
    assert_field,
    assert_fields,
    assert_ledger,
    assert_money,
    assert_pagination_meta,
)
from test_helpers.fixtures import WinLossWorld

CLOCK = "2026-08-01T00:00:00.000Z"


def _drawn_lost_deal(world: WinLossWorld) -> WinLossWorld:
    """One consented ECONOMIC_BUYER loss drawn from a sealed frame."""
    world.set_clock(CLOCK)
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    return world


def _interviewed_deal_with_taxonomy(world: WinLossWorld):
    """An `INTERVIEWED` deal, a live leaf reason and a second competitor to repoint to."""
    _drawn_lost_deal(world)
    second = world.create_competitor(name="Initech", tier="SECONDARY")
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=4)
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    root = world.create_reason("PRICE", "Price")
    leaf = world.create_reason(
        "PRICE_DISCOUNT", "Discount depth", parent_reason_id=root["id"]
    )
    return second, leaf


def test_a_stale_deal_version_stops_an_otherwise_legal_attribution(world):
    """Nothing else can refuse this write, so only the version guard can.

    "A `POST /loss-attributions` request must carry `expected_deal_version` holding the
    `version` of the target `Deal` as the client last observed it. If that value differs
    from the deal's current `version`, the create is rejected with
    `ERR_STALE_DEAL_VERSION` (HTTP 412)."

    Design: Corner/optimistic_concurrency/attribution_create_with_a_stale_deal_version_rejected
    """
    second, leaf = _interviewed_deal_with_taxonomy(world)
    stale_version = world.get_deal()["version"]
    validate_success(
        world.api.patch_deal(
            world.deal["id"],
            f.deal_patch_payload(primary_competitor_id=second["id"]),
            world.admin,
        ),
        200,
    )

    validate_error(
        world.api.create_loss_attribution(
            f.loss_attribution_payload(world.deal["id"], leaf["id"], stale_version),
            world.analyst_headers,
        ),
        ERR_STALE_DEAL_VERSION,
        412,
    )

    _, meta = validate_paginated(world.api.list_loss_attributions(world.admin))
    assert_pagination_meta(meta, expected_total=0)
    stored = world.get_deal()
    assert_fields(
        stored,
        {
            "attribution_status": "UNATTRIBUTED",
            "primary_competitor_id": second["id"],
        },
    )
    assert stored["version"] > stale_version, (
        f"the correction must move the deal past {stale_version}, "
        f"got {stored['version']}"
    )


def test_a_refetched_deal_version_lets_the_same_write_through(world):
    """The satisfaction side: the identical payload succeeds on a fresh expectation.

    "A `POST /loss-attributions` request must carry `expected_deal_version` holding the
    `version` of the target `Deal` as the client last observed it."

    "The deal's `attribution_status` moves `UNATTRIBUTED → PROVISIONAL` and its `version`
    increments."

    Design: Corner/optimistic_concurrency/refetched_deal_version_lets_the_same_attribution_through_and_bumps_the_deal_again
    """
    second, leaf = _interviewed_deal_with_taxonomy(world)
    validate_success(
        world.api.patch_deal(
            world.deal["id"],
            f.deal_patch_payload(primary_competitor_id=second["id"]),
            world.admin,
        ),
        200,
    )
    fresh_version = world.get_deal()["version"]

    attribution = validate_success(
        world.api.create_loss_attribution(
            f.loss_attribution_payload(world.deal["id"], leaf["id"], fresh_version),
            world.analyst_headers,
        ),
        201,
    )

    assert_field(attribution, "status", "PROVISIONAL")
    assert_money(attribution["weight_secondary"], 0.00, "weight_secondary")
    stored = world.get_deal()
    assert_field(stored, "attribution_status", "PROVISIONAL")
    assert stored["version"] > fresh_version, (
        f"the accepted write must move the deal past {fresh_version}, "
        f"got {stored['version']}"
    )
    _, meta = validate_paginated(world.api.list_loss_attributions(world.admin))
    assert_pagination_meta(meta, expected_total=1)


def test_a_stale_program_version_blocks_the_budget_replacement(world):
    """A pre-commitment view of the ledger cannot overwrite the budget behind it.

    "A `PUT /programs/{program_id}/incentive-budget` request must carry
    `expected_program_version` holding the `version` of the target `Program` as the client
    last observed it. If that value differs from the program's current `version`, the
    replacement is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."

    Design: Corner/optimistic_concurrency/incentive_budget_replacement_with_a_stale_program_version_rejected
    """
    _drawn_lost_deal(world)
    stale_version = world.refresh_program()["version"]
    interview = world.schedule_interview()

    validate_error(
        world.api.replace_incentive_budget(
            world.program_id,
            f.incentive_budget_payload(400.00, stale_version),
            world.admin,
        ),
        ERR_STALE_PROGRAM_VERSION,
        412,
    )

    program = world.refresh_program()
    assert_money(program["incentive_budget_usd"], 10000.00, "incentive_budget_usd")
    assert_ledger(program, committed_usd=250.00, paid_usd=0.00, posture="OPEN")
    stored = world.get_interview(interview["id"])
    assert_field(stored, "status", "SCHEDULED")
    assert_money(
        stored["incentive_provisional_usd"], 250.00, "incentive_provisional_usd"
    )

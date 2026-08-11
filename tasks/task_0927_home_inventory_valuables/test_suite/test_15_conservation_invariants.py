"""Two conserved quantities and their compensating actions: allowance cents on a
policy, and the count of frozen item records on a household."""
from test_helpers import (
    add_cataloged_item,
    add_generated_package,
    add_policy,
    add_room,
    assert_household_freeze_invariant,
    assert_policy_ledger_invariant,
    bootstrap_household,
    open_claim,
    schedule_item,
    validate_success,
)

GENERAL_SCHEDULE = {
    "category": "GENERAL",
    "useful_life_months": 120,
    "annual_depreciation_pct": 8.0,
    "salvage_floor_pct": 20.0,
    "blanket_sublimit_cents": 900000,
    "appraisal_scope": "GENERAL",
    "serial_required": False,
}


def _setup_two_riders_on_one_policy():
    """A 1000000-cent allowance carrying two riders — 600000 and 300000 — so the
    ledger reads 900000 consumed / 100000 remaining."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[GENERAL_SCHEDULE])
    room = add_room(ctx, name="Office", floor_label="1")
    policy = add_policy(
        ctx,
        policy_number="NW-1313",
        deductible_cents=50000,
        scheduled_allowance_cents=1000000,
    )
    item_one = add_cataloged_item(
        ctx, room["id"], 600000, photo_bytes=11000, name="Rider One",
        acquired_at="2025-03-01T00:00:00Z", quantity=1,
    )
    item_two = add_cataloged_item(
        ctx, room["id"], 300000, photo_bytes=11000, name="Rider Two",
        acquired_at="2025-03-02T00:00:00Z", quantity=1,
    )
    schedule_item(ctx, item_one["id"], policy["id"], 600000)
    schedule_item(ctx, item_two["id"], policy["id"], 300000)
    ctx.update({"room": room, "policy": policy, "item_one": item_one, "item_two": item_two})
    return ctx


def test_unscheduling_releases_exactly_what_that_item_consumed(api):
    """PRD 3.5: "Unscheduling is the exact compensating action: the policy's
    `scheduled_consumed_cents` falls by the exact amount **that item** consumed and
    `scheduled_remaining_cents` rises by the same amount, while the item returns to
    `coverage_mode` `BLANKET` with `scheduled_policy_id` null and
    `scheduled_value_cents` 0."

    Design: Difficulty/compensating_invariant/schedule_unschedule_roundtrip_conserves_policy_allowance_cents
    """
    ctx = _setup_two_riders_on_one_policy()

    before = validate_success(api.get_policy(ctx["policy"]["id"], ctx["owner_headers"]))
    assert before["scheduled_consumed_cents"] == 900000
    assert before["scheduled_remaining_cents"] == 100000

    validate_success(
        api.unschedule_item(ctx["item_one"]["id"], {}, ctx["owner_headers"]), 200
    )

    policy = validate_success(api.get_policy(ctx["policy"]["id"], ctx["owner_headers"]))
    assert policy["scheduled_consumed_cents"] == 300000, (
        "only the 600000 that rider one consumed may be released; got "
        f"{policy['scheduled_consumed_cents']}"
    )
    assert policy["scheduled_remaining_cents"] == 700000
    assert_policy_ledger_invariant(policy)

    item_one = validate_success(api.get_item(ctx["item_one"]["id"], ctx["owner_headers"]))
    assert item_one["coverage_mode"] == "BLANKET"
    assert item_one["scheduled_policy_id"] is None
    assert item_one["scheduled_value_cents"] == 0


def test_schedule_unschedule_reschedule_returns_the_ledger_to_its_exact_value(api):
    """PRD 2.12: "A policy's `scheduled_consumed_cents` always equals the sum of
    `scheduled_value_cents` over the items whose `coverage_mode` is `SCHEDULED` and
    whose `scheduled_policy_id` names that policy, and its
    `scheduled_remaining_cents` always equals `scheduled_allowance_cents` minus
    `scheduled_consumed_cents`."
    PRD 2.12: "After a schedule-then-unschedule round trip on the same item both
    figures return to their exact pre-schedule values, including when other items
    were scheduled in between."

    Design: Difficulty/compensating_invariant/schedule_unschedule_roundtrip_conserves_policy_allowance_cents
    """
    ctx = _setup_two_riders_on_one_policy()

    validate_success(
        api.unschedule_item(ctx["item_one"]["id"], {}, ctx["owner_headers"]), 200
    )
    schedule_item(ctx, ctx["item_one"]["id"], ctx["policy"]["id"], 600000)

    policy = validate_success(api.get_policy(ctx["policy"]["id"], ctx["owner_headers"]))
    assert policy["scheduled_consumed_cents"] == 900000
    assert policy["scheduled_remaining_cents"] == 100000
    assert_policy_ledger_invariant(policy)
    assert (
        policy["scheduled_allowance_cents"]
        == policy["scheduled_consumed_cents"] + policy["scheduled_remaining_cents"]
    )

    item_one = validate_success(api.get_item(ctx["item_one"]["id"], ctx["owner_headers"]))
    item_two = validate_success(api.get_item(ctx["item_two"]["id"], ctx["owner_headers"]))
    assert item_one["scheduled_value_cents"] == 600000
    assert item_two["scheduled_value_cents"] == 300000


def _setup_two_rooms_of_catalogued_items():
    """Rooms A and B: two CATALOGED items in A, one in B, plus a GENERATED
    package to build a claim on."""
    ctx = bootstrap_household(tier="PLUS", activate=True, categories=[GENERAL_SCHEDULE])
    room_a = add_room(ctx, name="Room A", floor_label="1")
    room_b = add_room(ctx, name="Room B", floor_label="2")
    item_a1 = add_cataloged_item(
        ctx, room_a["id"], 100000, photo_bytes=10000, name="A One",
        acquired_at="2025-04-01T00:00:00Z", quantity=1,
    )
    item_a2 = add_cataloged_item(
        ctx, room_a["id"], 120000, photo_bytes=10000, name="A Two",
        acquired_at="2025-04-02T00:00:00Z", quantity=1,
    )
    item_b1 = add_cataloged_item(
        ctx, room_b["id"], 130000, photo_bytes=10000, name="B One",
        acquired_at="2025-04-03T00:00:00Z", quantity=1,
    )
    policy = add_policy(
        ctx, policy_number="NW-1414", deductible_cents=50000, scheduled_allowance_cents=0
    )
    package = add_generated_package(ctx, policy["id"])
    ctx.update(
        {
            "room_a": room_a,
            "room_b": room_b,
            "item_a1": item_a1,
            "item_a2": item_a2,
            "item_b1": item_b1,
            "policy": policy,
            "package": package,
        }
    )
    return ctx


def test_opening_a_claim_freezes_exactly_the_affected_rooms_items(api):
    """PRD 3.7: "Opening a claim runs the records-freeze cascade. Every item of the
    household whose `lifecycle_state` is `CATALOGED` **and** whose `room_id` appears
    in `affected_room_ids` moves `CATALOGED → FROZEN` with `frozen_by_claim_id` set
    to the new claim's id; the household's `frozen_item_count` rises by the number
    frozen, `records_freeze_active` becomes true, and the claim's own
    `frozen_item_count` records exactly how many rows it froze."

    Design: Difficulty/compensating_invariant/claim_open_withdraw_roundtrip_conserves_frozen_item_count
    """
    ctx = _setup_two_rooms_of_catalogued_items()

    before = validate_success(api.get_household(ctx["household_id"], ctx["owner_headers"]))
    assert before["frozen_item_count"] == 0
    assert before["records_freeze_active"] is False

    claim = open_claim(
        ctx,
        ctx["package"]["id"],
        ctx["policy"]["id"],
        [ctx["room_a"]["id"]],
        loss_date="2026-05-01T00:00:00Z",
        peril="WATER",
        settlement_basis="ACV",
        deductible_mode="PRO_RATA",
    )
    assert claim["frozen_item_count"] == 2

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["frozen_item_count"] == 2
    assert household["records_freeze_active"] is True
    assert_household_freeze_invariant(household)

    for key in ("item_a1", "item_a2"):
        row = validate_success(api.get_item(ctx[key]["id"], ctx["owner_headers"]))
        assert row["lifecycle_state"] == "FROZEN"

    untouched = validate_success(api.get_item(ctx["item_b1"]["id"], ctx["owner_headers"]))
    assert untouched["lifecycle_state"] == "CATALOGED", (
        "items in unaffected rooms are left alone"
    )


def test_withdrawing_the_claim_restores_the_frozen_item_count_to_zero(api):
    """PRD 2.12: "Opening a claim is the forward step; withdrawing it is the
    compensating step, and it unfreezes exactly the items whose
    `frozen_by_claim_id` names that claim — not every frozen item of the household —
    so a second claim's freeze survives the first claim's withdrawal untouched.
    After an open-then-withdraw round trip both `frozen_item_count` and
    `records_freeze_active` return to their exact pre-claim values."
    PRD 3.7: "The homeowner may withdraw a claim along `OPEN → WITHDRAWN`,
    `SUBMITTED → WITHDRAWN` or `UNDER_REVIEW → WITHDRAWN`, optionally supplying a
    `withdraw_reason`, and all three paths carry identical compensating effects:
    every item whose `frozen_by_claim_id` names this claim returns to `CATALOGED`
    with that pointer cleared"

    Design: Difficulty/compensating_invariant/claim_open_withdraw_roundtrip_conserves_frozen_item_count
    """
    ctx = _setup_two_rooms_of_catalogued_items()
    claim = open_claim(
        ctx,
        ctx["package"]["id"],
        ctx["policy"]["id"],
        [ctx["room_a"]["id"]],
        loss_date="2026-05-01T00:00:00Z",
        peril="WATER",
        settlement_basis="ACV",
        deductible_mode="PRO_RATA",
    )

    withdrawn = validate_success(
        api.withdraw_claim(
            claim["id"], {"withdraw_reason": "settled privately"}, ctx["owner_headers"]
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    household = validate_success(
        api.get_household(ctx["household_id"], ctx["owner_headers"])
    )
    assert household["frozen_item_count"] == 0
    assert household["records_freeze_active"] is False
    assert_household_freeze_invariant(household)

    for key in ("item_a1", "item_a2"):
        row = validate_success(api.get_item(ctx[key]["id"], ctx["owner_headers"]))
        assert row["lifecycle_state"] == "CATALOGED"
        assert row["frozen_by_claim_id"] is None, "no freeze residue may remain"

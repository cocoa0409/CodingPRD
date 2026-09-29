"""Pickup surcharge quoting versus settlement.

The same job carries two independently stored surcharge figures: the forward
looking quote taken from the consignor's declared access facts, and the settled
charge taken from what the crew actually did.
"""

from test_helpers import (
    GALLERY_MANAGER,
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    complete_pickup,
    create_item,
    create_truck,
    fetch_consignor,
    fetch_item,
    fetch_pickup_job,
    schedule_pickup,
    screen_item,
    setup_consignor_with_active_agreement,
    validate_paginated,
)

WINDOW_START = "2026-08-05T09:00:00Z"
WINDOW_END = "2026-08-05T11:00:00Z"


def _job_whose_variants_diverge():
    """Two attached pieces quoted at 3 movers / 2 flights, settled at 4 / 8.

    The consignor lives on floor 3 without a lift, so the job snapshots two
    declared flights; the sofa is 70 cubic feet and therefore bulky, the walnut
    dresser is not.
    """
    world = setup_consignor_with_active_agreement(
        consignor_overrides={"floor_number": 3, "has_elevator": False}
    )
    sofa = create_item(
        world["agreement"]["id"],
        title="Chesterfield sofa",
        category="SOFA",
        declared_value_cents=189_950,
        photo_count=6,
        volume_cuft=70,
        footprint_sqft=24,
    )
    screen_item(sofa["id"], scores=SCORES_GRADE_B)
    dresser = create_item(
        world["agreement"]["id"],
        title="Walnut dresser",
        category="CASEGOOD",
        declared_value_cents=60_000,
        photo_count=5,
        volume_cuft=18,
        footprint_sqft=18,
    )
    screen_item(dresser["id"], scores=SCORES_GRADE_A)
    world["truck"] = create_truck(capacity_volume_cuft=600)
    world["items"] = [sofa, dresser]
    world["pickup_job"] = schedule_pickup(
        world["consignor"]["id"],
        world["truck"]["id"],
        [sofa["id"], dresser["id"]],
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        crew_size=3,
    )
    return world


def test_quoted_and_final_surcharges_diverge_on_one_job():
    """Both surcharge figures are stored on the job and differ.

    PRD 3.4: "it reads `declared_stair_flights`, `declared_elevator` and the quoted
    `crew_size`, writes the result to `quoted_surcharge_cents`, and mints no ledger
    entry whatsoever"; "it reads what actually happened and writes
    `final_surcharge_cents`, together with `surcharge_variance_cents` computed as
    `final_surcharge_cents` minus `quoted_surcharge_cents`. `surcharge_variance_cents`
    is null until completion."

    Design: Difficulty/dual_variant_calc/pickup_surcharge_quoted_vs_final_diverges
    """
    world = _job_whose_variants_diverge()
    job_id = world["pickup_job"]["id"]

    assert world["pickup_job"]["quoted_surcharge_cents"] == 61_250, (
        "Expected 61250 quoted, got "
        f"{world['pickup_job']['quoted_surcharge_cents']}"
    )
    assert world["pickup_job"]["surcharge_variance_cents"] is None, (
        "surcharge_variance_cents must stay null until completion"
    )

    complete_pickup(
        job_id,
        actual_stair_flights=8,
        actual_elevator_used=False,
        actual_crew_size=4,
    )
    job = fetch_pickup_job(job_id)

    assert job["quoted_surcharge_cents"] == 61_250, (
        f"The quote must be preserved, got {job['quoted_surcharge_cents']}"
    )
    assert job["final_surcharge_cents"] == 87_483, (
        f"Expected 87483 settled, got {job['final_surcharge_cents']}"
    )
    assert job["surcharge_variance_cents"] == 26_233, (
        f"Expected variance 26233, got {job['surcharge_variance_cents']}"
    )
    assert job["final_surcharge_cents"] != job["quoted_surcharge_cents"], (
        "The two variants must not collapse onto one figure"
    )
    assert job["status"] == "COMPLETED", f"Expected COMPLETED, got {job['status']}"


def test_settled_surcharge_is_held_down_by_the_declared_value_cap():
    """The settled figure is the cap, not the crew-multiplied subtotal.

    PRD 3.4: "Finally the surcharge is capped at 35 hundredths of the summed
    `declared_value_cents` of every piece attached to the job, that cap being
    itself rounded half up to a whole number of cents, and the surcharge charged
    is the smaller of the two rounded integers"

    Design: Difficulty/dual_variant_calc/pickup_surcharge_quoted_vs_final_diverges
    """
    world = _job_whose_variants_diverge()

    complete_pickup(
        world["pickup_job"]["id"],
        actual_stair_flights=8,
        actual_elevator_used=False,
        actual_crew_size=4,
    )
    job = fetch_pickup_job(world["pickup_job"]["id"])

    assert job["final_surcharge_cents"] == 87_483, (
        "Expected the 35-hundredths cap on 249950 declared cents, got "
        f"{job['final_surcharge_cents']}"
    )
    assert job["final_surcharge_cents"] != 108_750, (
        "The uncapped crew-multiplied subtotal must not be billed"
    )
    assert job["quoted_surcharge_cents"] == 61_250, (
        "The quote sits below the cap and is therefore the raw computed figure"
    )


def test_completed_pickup_debits_the_settled_figure_and_suspends_the_consignor(api):
    """Completion mints one debit for the final figure and moves the balance.

    PRD 3.4: "exactly one `PICKUP_SURCHARGE_DEBIT` ledger entry is minted for the
    job's consignor, carrying `amount_cents` equal to the negation of
    `final_surcharge_cents` and an `item_id` of null, since the surcharge is a
    job-level charge rather than a piece-level one."

    Design: Difficulty/dual_variant_calc/pickup_surcharge_quoted_vs_final_diverges
    """
    world = _job_whose_variants_diverge()
    consignor_id = world["consignor"]["id"]

    complete_pickup(
        world["pickup_job"]["id"],
        actual_stair_flights=8,
        actual_elevator_used=False,
        actual_crew_size=4,
    )

    entries, meta = validate_paginated(
        api.list_consignor_ledger_entries(
            consignor_id, GALLERY_MANAGER, params={"limit": 100}
        )
    )
    assert meta["total_count"] == 1, f"Expected one entry, got {meta['total_count']}"
    entry = entries[0]
    assert entry["entry_type"] == "PICKUP_SURCHARGE_DEBIT", (
        f"Expected PICKUP_SURCHARGE_DEBIT, got {entry['entry_type']}"
    )
    assert entry["amount_cents"] == -87_483, (
        f"Expected -87483, got {entry['amount_cents']}"
    )
    assert entry["item_id"] is None, "A job-level charge carries no item_id"
    assert entry["balance_after_cents"] == -87_483, (
        f"Expected -87483 after the debit, got {entry['balance_after_cents']}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == -87_483, (
        f"Expected -87483, got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["status"] == "SUSPENDED", (
        f"A balance below -50000 suspends; got {consignor['status']}"
    )

    for piece in world["items"]:
        row = fetch_item(piece["id"])
        assert row["lifecycle_state"] == "RECEIVED", (
            f"Expected RECEIVED, got {row['lifecycle_state']}"
        )
        assert row["inventory_state"] == "IN_CUSTODY", (
            f"Expected IN_CUSTODY, got {row['inventory_state']}"
        )

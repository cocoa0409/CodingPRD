"""The month-boundary sweep: lot ordering under each expiry basis and the
empty-sweep close."""
from test_helpers import (
    ADMIN,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    validate_paginated,
)


def _two_lots_and_one_authorization(expiry_basis: str, banner_code: str, alt_id: str):
    """A member holding an August lot and a September lot, with exactly 300
    points already spent at the pump, on the eve of the September close.

    Both lots are 300 points; the August lot expires at the end of September and
    the September lot at the end of October, so which of the two the spending
    consumed is entirely decided by the banner's `expiry_basis`.
    """
    fixtures.set_clock("2026-08-05T10:00:00Z")
    banner = fixtures.create_banner(
        banner_code=banner_code,
        name=f"{banner_code} Banner",
        expiry_basis=expiry_basis,
        rollover_cap_points=0,
    )
    cycles = fixtures.create_month_cycles(
        banner["id"], ("2026-08", "2026-09", "2026-10")
    )
    grocery = fixtures.create_grocery_site(banner["id"], f"G-{banner_code[:3]}")
    fuel = fixtures.create_owned_fuel_center(banner["id"], f"F-{banner_code[:3]}")
    member = fixtures.create_member(banner["id"], alt_id=alt_id)

    fixtures.accrue_points(member["id"], grocery["id"], 300, "2026-08-05T10:00:00Z")
    fixtures.run_close(cycles["2026-08"]["id"], "2026-09-01T00:00:00Z")
    fixtures.accrue_points(member["id"], grocery["id"], 300, "2026-09-01T00:00:00Z")
    fixtures.authorize_redemption(member["id"], fuel["id"], alt_id, 300)

    return {"cycles": cycles, "member": member, "fuel": fuel}


def test_lot_fifo_spending_consumes_the_soonest_expiring_lot_so_nothing_expires():
    """Under `LOT_FIFO` the pump visit already spent the lot that was about to
    die, so the September close sweeps nobody.

    PRD: "When the banner's `expiry_basis` is `LOT_FIFO`, lots are ordered by
    `lot_expires_at` ascending and then by `created_at` ascending, with lots whose
    `lot_expires_at` is null sorted **last**; the soonest-to-expire lot is spent
    first, so spending protects the points that were about to die."

    Design: Difficulty/dual_variant_calc/expiry_sweep_lot_fifo_protects_the_soonest_expiring_lot
    """
    scenario = _two_lots_and_one_authorization("LOT_FIFO", "FIFO", "5550000001")

    closed = fixtures.run_close(
        scenario["cycles"]["2026-09"]["id"], "2026-10-01T00:00:00Z"
    )

    assert closed["status"] == "CLOSED"
    assert closed["expired_points_total"] == 0
    assert closed["swept_member_count"] == 0
    assert closed["rolled_over_points_total"] == 0
    assert fixtures.get_member(scenario["member"]["id"])["available_points"] == 300


def test_lot_fifo_close_writes_no_sweep_row_and_leaves_the_history_intact():
    """No expiry and no rollover row is written when the expiring remainder is
    zero.

    PRD: "When the whole expiring remainder is rescued, both rows are written and
    net to zero; when the expiring remainder is zero, neither row is written and
    the member is not counted as swept."

    Design: Difficulty/dual_variant_calc/expiry_sweep_lot_fifo_protects_the_soonest_expiring_lot
    """
    scenario = _two_lots_and_one_authorization("LOT_FIFO", "FIFO", "5550000001")
    member_id = scenario["member"]["id"]

    fixtures.run_close(scenario["cycles"]["2026-09"]["id"], "2026-10-01T00:00:00Z")

    for entry_type in ("EXPIRY", "ROLLOVER"):
        _rows, meta = validate_paginated(
            api_client.list_point_ledger_entries(
                ADMIN, {"member_id": member_id, "entry_type": entry_type}
            )
        )
        assert meta["total_count"] == 0, f"{entry_type} row written unexpectedly"

    rows = fixtures.ledger_entries(member_id)
    assert [row["entry_type"] for row in rows] == ["ACCRUAL", "ACCRUAL", "REDEMPTION"]
    assert [row["points_delta"] for row in rows] == [300, 300, -300]


def test_cycle_scoped_spending_drains_the_latest_lot_so_the_month_expires_in_full():
    """Under `CYCLE_SCOPED` the same spending protected nothing, and the whole
    August lot dies at the September close.

    PRD: "When the banner's `expiry_basis` is `CYCLE_SCOPED`, lots are ordered by
    `lot_expires_at` descending and then by `created_at` descending, with lots
    whose `lot_expires_at` is null sorted **first**; the latest-expiring lot is
    spent first, so spending never rescues a soon-to-expire lot and the current
    cycle's points expire in full."

    Design: Difficulty/dual_variant_calc/expiry_sweep_cycle_scoped_expires_the_current_lot_in_full
    """
    scenario = _two_lots_and_one_authorization("CYCLE_SCOPED", "SCOPED", "5550000002")

    closed = fixtures.run_close(
        scenario["cycles"]["2026-09"]["id"], "2026-10-01T00:00:00Z"
    )

    assert closed["expired_points_total"] == 300
    assert closed["swept_member_count"] == 1
    assert closed["rolled_over_points_total"] == 0
    assert fixtures.get_member(scenario["member"]["id"])["available_points"] == 0


def test_cycle_scoped_sweep_writes_one_expiry_row_and_no_rollover():
    """An unlinked member rescues nothing, so the debit stands alone.

    PRD: "A member is rollover-eligible when they hold a linkage in `ACTIVE`
    status to a household that is itself in `ACTIVE` status **and** that household
    has zero fraud signals in `OPEN` status."

    PRD: "When the expired amount is greater than zero, one `EXPIRY` row is
    appended whose `points_delta` is the negation of the **full** expiring
    remainder — not of the expired portion — with `point_cycle_id` set to the
    closing cycle and `lot_expires_at` null."

    Design: Difficulty/dual_variant_calc/expiry_sweep_cycle_scoped_expires_the_current_lot_in_full
    """
    scenario = _two_lots_and_one_authorization("CYCLE_SCOPED", "SCOPED", "5550000002")
    member_id = scenario["member"]["id"]

    fixtures.run_close(scenario["cycles"]["2026-09"]["id"], "2026-10-01T00:00:00Z")

    expiries, expiry_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "EXPIRY"}
        )
    )
    assert expiry_meta["total_count"] == 1
    assert expiries[0]["points_delta"] == -300
    assert expiries[0]["lot_expires_at"] is None

    _rollovers, rollover_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "ROLLOVER"}
        )
    )
    assert rollover_meta["total_count"] == 0


def _august_close_with_nothing_expiring():
    """A member whose only lot expires at the end of September, on the eve of the
    August close, with phase one already run."""
    fixtures.set_clock("2026-08-05T10:00:00Z")
    banner = fixtures.create_banner(banner_code="ZERO", name="Zero Sweep Banner")
    cycles = fixtures.create_month_cycles(
        banner["id"], ("2026-08", "2026-09", "2026-10")
    )
    grocery = fixtures.create_grocery_site(banner["id"], "G-013")
    member = fixtures.create_member(banner["id"], alt_id="5550000013")
    txn = fixtures.record_basket(
        member["id"],
        grocery["id"],
        [factories.purchase_line("GROCERY", 22600, 1)],
        "2026-08-05T10:00:00Z",
    )
    fixtures.post_basket(txn["id"], grocery["id"])
    fixtures.set_clock("2026-09-01T00:00:00Z")
    fixtures.begin_close(cycles["2026-08"]["id"])
    return {"cycles": cycles, "member": member}


def test_a_close_whose_expiring_lot_set_is_empty_reports_three_zeroes():
    """Phase two still completes and stamps its instant even when the sweep finds
    nothing to do.

    PRD: "The cycle's `status` becomes `CLOSED` and `closed_at` is stamped from
    the logical clock."

    PRD: "Zero-valued rows are never written."

    Design: Difficulty/boundary_precision_check/cycle_close_with_empty_expiring_lot_set_writes_zero_ledger_rows
    """
    scenario = _august_close_with_nothing_expiring()

    closed = fixtures.close_cycle(scenario["cycles"]["2026-08"]["id"])

    assert closed["status"] == "CLOSED"
    assert closed["expired_points_total"] == 0
    assert closed["rolled_over_points_total"] == 0
    assert closed["swept_member_count"] == 0
    assert_instant_equals(closed["closed_at"], "2026-09-01T00:00:00Z")


def test_an_empty_sweep_appends_no_ledger_row_against_the_closing_cycle():
    """The closing cycle carries no sweep rows at all and the member's single
    accrual is untouched.

    PRD: "The sweep runs for every member of the closing cycle's banner, in the
    members' `created_at` ascending order, writing at most one `EXPIRY` row and at
    most one `ROLLOVER` row per member."

    Design: Difficulty/boundary_precision_check/cycle_close_with_empty_expiring_lot_set_writes_zero_ledger_rows
    """
    scenario = _august_close_with_nothing_expiring()
    cycle_id = scenario["cycles"]["2026-08"]["id"]
    member_id = scenario["member"]["id"]

    fixtures.close_cycle(cycle_id)

    for entry_type in ("EXPIRY", "ROLLOVER"):
        _rows, meta = validate_paginated(
            api_client.list_point_ledger_entries(
                ADMIN, {"point_cycle_id": cycle_id, "entry_type": entry_type}
            )
        )
        assert meta["total_count"] == 0, f"{entry_type} row written unexpectedly"

    rows = fixtures.ledger_entries(member_id)
    assert len(rows) == 1
    assert rows[0]["entry_type"] == "ACCRUAL"
    assert rows[0]["points_delta"] == 226
    assert fixtures.get_member(member_id)["available_points"] == 226

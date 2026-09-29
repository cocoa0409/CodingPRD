"""Compensations that must leave no drift: the payout ledger and the stock ledger."""

import pytest

from test_helpers import (
    TEST_USERS,
    cleaner_status_payload,
    fixtures as fx,
    restock_entry,
    review_task_payload,
    same_instant,
    submit_task_payload,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def accepted_offer_world(api):
    """T1 SCHEDULED against a cleaner whose ledger was 0 before acceptance."""
    world = fx.build_world(api, supply="pair")
    world["ledger_start"] = world["cc"]["pending_payout_cents"]
    fx.offer_turnover(api, world)
    fx.accept_offer(api, world)
    return world


@pytest.fixture
def approved_restock_world(api):
    """One VERIFIED restock row that drew a unit from each of four stock lines."""
    world = fx.world_in_progress(api, supply="four")
    row = next(t for t in world["tasks"] if t["category"] == "RESTOCK")
    entries = [restock_entry(line["id"], 1) for line in world["supply_lines"]]
    validate_success(api.submit_checklist_task(
        row["id"],
        submit_task_payload(photo_uri="https://cdn.example.com/restock.jpg",
                            restock_entries=entries),
        world["cleaner_headers"]))
    world["restock_row"] = validate_success(api.review_checklist_task(
        row["id"], review_task_payload("APPROVE"), REVIEWER))
    return world


# ─── payout_ledger_conserved_across_accept_then_suspension_revocation ─────

def test_01_suspending_the_cleaner_returns_the_ledger_to_its_pre_accept_value(
        api, accepted_offer_world):
    """0 to 12554 and back to exactly 0, with no residue.

    PRD §3.10: "Each `PROVISIONAL` pay line belonging to those assignments moves
    to `VOIDED`, and the cleaner's `pending_payout_cents` decreases by each
    voided line's `net_cents`, restoring the ledger exactly." PRD §2.8: "This
    invariant is re-established after every request that creates a pay line,
    switches its variant, folds in an audit adjustment, or voids it, which means
    an accept-then-revoke pair returns the ledger to its exact pre-acceptance
    value."

    Design: Difficulty/compensating_invariant/payout_ledger_conserved_across_accept_then_suspension_revocation
    """
    world = accepted_offer_world
    assert world["ledger_start"] == 0, (
        f"an onboarded cleaner starts with an empty ledger, "
        f"got {world['ledger_start']}")
    assert world["a1"]["status"] == "ACCEPTED", (
        f"the offer must be accepted first, got {world['a1']['status']}")
    assert fx.read_cleaner(api, world)["pending_payout_cents"] == 12554, (
        "acceptance must raise the ledger to the provisional net of 12554")

    suspended = validate_success(api.set_cleaner_status(
        world["cc"]["id"],
        cleaner_status_payload("SUSPEND", reason="background check lapsed"),
        ADMIN))
    assert suspended["status"] == "SUSPENDED", (
        f"the employment change must apply, got {suspended['status']}")
    assert suspended["pending_payout_cents"] == 0, (
        f"the compensation must restore exactly the pre-accept 0, "
        f"got {suspended['pending_payout_cents']}")
    assert suspended["completed_turnover_count"] == 0, (
        f"a revocation is not a completion, "
        f"got {suspended['completed_turnover_count']}")
    assert suspended["decline_count"] == 0, (
        f"a revocation is not a refusal, got {suspended['decline_count']}")


def test_02_the_voided_row_is_retained_and_the_turnover_becomes_assignable_again(
        api, accepted_offer_world):
    """The evidence survives the compensation on all four affected rows.

    PRD §2.8: "Pay lines in `VOIDED` are excluded from the sum but are never
    deleted — the row and its money fields are retained as evidence." PRD §3.10:
    "Every assignment of that cleaner sitting in `OFFERED` or `ACCEPTED` moves to
    `REVOKED` with `revoked_at` stamped from the logical clock. For each such
    assignment whose turnover was `SCHEDULED`, that turnover returns `SCHEDULED
    → PENDING_ASSIGNMENT` and its `version` increments by 1, making it available
    for a fresh offer."

    Design: Difficulty/compensating_invariant/payout_ledger_conserved_across_accept_then_suspension_revocation
    """
    world = accepted_offer_world
    validate_success(api.set_cleaner_status(
        world["cc"]["id"],
        cleaner_status_payload("SUSPEND", reason="background check lapsed"),
        ADMIN))

    pay = fx.read_pay_lines(api, world["cc"]["id"])
    assert len(pay) == 1, f"the row must not be deleted, got {len(pay)} rows"
    assert pay[0]["status"] == "VOIDED", (
        f"the provisional line must be voided, got {pay[0]['status']}")
    assert pay[0]["variant"] == "PROVISIONAL", (
        f"voiding does not switch the variant, got {pay[0]['variant']}")
    assert pay[0]["net_cents"] == 12554, (
        f"the money fields are retained as evidence, got {pay[0]['net_cents']}")

    assignment = validate_success(
        api.get_assignment(world["a1"]["id"], COORDINATOR))
    assert assignment["status"] == "REVOKED", (
        f"the accepted offer must be revoked, got {assignment['status']}")
    assert same_instant(assignment["revoked_at"], "2026-08-01T00:00:00Z"), (
        f"revoked_at reads the logical clock, got {assignment['revoked_at']}")

    turnover = fx.read_turnover(api, world)
    assert turnover["status"] == "PENDING_ASSIGNMENT", (
        f"the work must become offerable again, got {turnover['status']}")
    assert turnover["version"] == 4, (
        f"create, offer, accept and revert are four writes, "
        f"got {turnover['version']}")


# ─── supply_on_hand_conserved_across_restock_approve_then_waive_reversal ──

def test_03_waiving_a_verified_restock_row_restores_every_drawn_line(
        api, approved_restock_world):
    """Four lines fall by one unit on approval and return on the waiver.

    PRD §3.5: "Waiving an already `VERIFIED` restock row is the compensation
    case: for every `RESTOCK_USE` movement that row booked, a movement with
    `reason` `REVERSAL` is appended carrying the opposite `delta_qty` and the
    negated `charge_cents`, in the same per-line order, so that each supply
    line's `on_hand_qty` returns exactly to its pre-approval value, `below_par`
    is recomputed and the line's `version` increments by 1; the row's
    `restock_charge_cents` returns to 0."

    Design: Difficulty/compensating_invariant/supply_on_hand_conserved_across_restock_approve_then_waive_reversal
    """
    world = approved_restock_world
    sl1, sl4 = world["supply_lines"][0], world["supply_lines"][3]
    assert world["restock_row"]["restock_charge_cents"] == 1808, (
        f"280 + 194 + 366 + 968 is 1808, "
        f"got {world['restock_row']['restock_charge_cents']}")
    assert fx.read_supply_line(api, sl1["id"])["on_hand_qty"] == 5, (
        "the approval must have drawn one set of sheets")
    drawn_wine = fx.read_supply_line(api, sl4["id"])
    assert drawn_wine["on_hand_qty"] == 0 and drawn_wine["below_par"] is True, (
        f"the single bottle must be gone and the line flagged, got "
        f"{drawn_wine['on_hand_qty']} / {drawn_wine['below_par']}")

    waived = validate_success(api.review_checklist_task(
        world["restock_row"]["id"],
        review_task_payload(
            "WAIVE",
            reject_reason="supplies were donated by the owner, do not charge"),
        REVIEWER))
    assert waived["status"] == "WAIVED", (
        f"the row must come to rest in WAIVED, got {waived['status']}")
    assert waived["restock_charge_cents"] == 0, (
        f"the charge must be undone, got {waived['restock_charge_cents']}")

    restored_sheets = fx.read_supply_line(api, sl1["id"])
    assert restored_sheets["on_hand_qty"] == 6, (
        f"the sheet line must return to its seeded 6, "
        f"got {restored_sheets['on_hand_qty']}")
    assert restored_sheets["below_par"] is False, (
        f"6 is above a reorder_point of 0, got {restored_sheets['below_par']}")
    restored_wine = fx.read_supply_line(api, sl4["id"])
    assert restored_wine["on_hand_qty"] == 1 and restored_wine["below_par"] is False, (
        f"the bottle must come back and clear the flag, got "
        f"{restored_wine['on_hand_qty']} / {restored_wine['below_par']}")


def test_04_the_append_only_ledger_sums_back_to_the_seeded_quantity(
        api, approved_restock_world):
    """Three rows survive on the drawn line and their deltas and charges cancel.

    PRD §2.9: "Because the ledger is append-only, a correction is always a new
    compensating movement rather than an edit, and the invariant that
    `on_hand_qty` equals the summed `delta_qty` holds after every single
    request." PRD §2.9: "Within one supply line, `sequence_no` is a 1-based
    monotonic counter that gives a total order even among several movements
    minted inside a single request; the four permitted values of `reason` are
    `SEED`, `REPLENISH`, `RESTOCK_USE` and `REVERSAL`."

    Design: Difficulty/compensating_invariant/supply_on_hand_conserved_across_restock_approve_then_waive_reversal
    """
    world = approved_restock_world
    sl1 = world["supply_lines"][0]
    validate_success(api.review_checklist_task(
        world["restock_row"]["id"],
        review_task_payload(
            "WAIVE",
            reject_reason="supplies were donated by the owner, do not charge"),
        REVIEWER))

    rows, meta = validate_paginated(
        api.list_stock_movements(COORDINATOR, {"supply_line_id": sl1["id"]}))
    assert meta["total_count"] == 3, (
        f"no ledger row may be deleted, got {meta['total_count']}")

    seed, use, reversal = rows
    assert (seed["delta_qty"], seed["reason"], seed["sequence_no"]) == (6, "SEED", 1), (
        f"the seeding row must be first, got {seed['delta_qty']} / "
        f"{seed['reason']} / {seed['sequence_no']}")
    assert (use["delta_qty"], use["charge_cents"], use["reason"]) == (
        -1, 280, "RESTOCK_USE"), (
        f"the consumption row must carry -1 at 280 cents, got "
        f"{use['delta_qty']} / {use['charge_cents']} / {use['reason']}")
    assert (reversal["delta_qty"], reversal["charge_cents"]) == (1, -280), (
        f"the compensation must mirror the consumption exactly, got "
        f"{reversal['delta_qty']} / {reversal['charge_cents']}")
    assert reversal["reason"] == "REVERSAL", (
        f"the compensating reason must be REVERSAL, got {reversal['reason']}")
    assert reversal["sequence_no"] == 3, (
        f"the counter must be monotonic within the line, "
        f"got {reversal['sequence_no']}")

    assert sum(row["delta_qty"] for row in rows) == 6, (
        "the summed deltas must equal the seeded quantity")
    assert sum(row["charge_cents"] for row in rows) == 0, (
        "the summed charges must cancel to zero")
    assert (fx.read_supply_line(api, sl1["id"])["on_hand_qty"]
            == sum(row["delta_qty"] for row in rows)), (
        "the projection must equal the summed deltas after every request")
    assert fx.read_turnover(api, world)["status"] == "IN_PROGRESS", (
        "three rows still PENDING keep the parent IN_PROGRESS")

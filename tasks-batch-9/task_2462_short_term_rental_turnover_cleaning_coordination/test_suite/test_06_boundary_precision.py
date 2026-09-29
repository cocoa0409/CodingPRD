"""Inclusive boundaries: a window that just fits, a closet drawn to zero, a score of 70."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_quality_audit_payload,
    create_turnover_payload,
    fixtures as fx,
    restock_entry,
    review_task_payload,
    same_instant,
    submit_task_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def twin_properties(api):
    """Two identical TWO_BR units whose arriving stays differ by one minute."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    p1b = fx.seed_property(
        api, code="AUS-103", name="Barton Loft B",
        owner_contact_email="owner3@example.com")
    b_out = fx.seed_booking(
        api, p1["id"], external_ref="OUT-1", guest_name="Guest Out",
        checkin_at="2026-08-05T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    b_in = fx.seed_booking(
        api, p1["id"], external_ref="IN-1", guest_name="Guest In",
        checkin_at="2026-08-08T19:48:00Z", checkout_at="2026-08-11T16:00:00Z")
    b_out3 = fx.seed_booking(
        api, p1b["id"], external_ref="OUT-3", guest_name="Guest Out 3",
        checkin_at="2026-08-05T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    b_in3 = fx.seed_booking(
        api, p1b["id"], external_ref="IN-3", guest_name="Guest In 3",
        checkin_at="2026-08-08T19:47:00Z", checkout_at="2026-08-11T16:00:00Z")
    return {"p1": p1, "p1b": p1b, "b_out": b_out, "b_in": b_in,
            "b_out3": b_out3, "b_in3": b_in3}


@pytest.fixture
def single_bottle_world(api):
    """A running clean whose WELCOME line holds exactly one bottle."""
    world = fx.build_world(api, supply=None)
    world["supply_lines"] = [
        fx.seed_supply_line(
            api, world["p1"]["id"], sku="LIN-SHEET-Q", name="Queen Sheet Set",
            category="LINEN", unit_cost_cents=260, par_qty=6, unit="SET",
            initial_on_hand_qty=6),
        fx.seed_supply_line(
            api, world["p1"]["id"], sku="WEL-WINE", name="Welcome Wine",
            category="WELCOME", unit_cost_cents=900, par_qty=1, unit="BOTTLE",
            initial_on_hand_qty=1),
    ]
    fx.offer_turnover(api, world)
    fx.accept_offer(api, world)
    fx.start_clean(api, world)
    world["restock_row"] = next(
        t for t in world["tasks"] if t["category"] == "RESTOCK")
    return world


@pytest.fixture
def audit_at_threshold(api):
    """A completed turn carrying a SAMPLED audit whose score is exactly 70."""
    world = fx.world_completed(api, supply="pair")
    world["audit"] = validate_success(api.create_quality_audit(
        create_quality_audit_payload(
            world["t1"]["id"], 70, findings="acceptable but marginal"),
        AUDITOR), 201)
    return world


# ─── window_minutes_exactly_equals_required_minutes_accepted ─────────────

def test_01_a_window_exactly_equal_to_the_requirement_needs_no_override(
        api, twin_properties):
    """198 against 198 is created with zero slack and is_tight true.

    PRD §3.3: "A raw window length strictly less than `required_minutes` is
    refused with `ERR_WINDOW_OVERRIDE_REQUIRED` unless an `override_reason` was
    supplied; a window exactly equal to `required_minutes` is acceptable and
    needs no override, because the comparison the guard makes is "at least"."
    PRD §3.3: "`is_tight` is true whenever `slack_minutes` is strictly below 45
    minutes — note that a comfortable window is not merely one that fits, but
    one that fits with three quarters of an hour to spare."

    Design: Difficulty/boundary_precision_check/window_minutes_exactly_equals_required_minutes_accepted
    """
    world = twin_properties
    turnover = validate_success(api.create_turnover(
        create_turnover_payload(world["b_out"]["id"], world["b_in"]["id"]),
        COORDINATOR), 201)

    assert turnover["required_minutes"] == 198, (
        f"a TWO_BR with 2 baths and 3 beds requires 150 + 24 + 24, "
        f"got {turnover['required_minutes']}")
    assert turnover["window_minutes"] == 198, (
        f"16:00Z to 19:18Z is 198 minutes, got {turnover['window_minutes']}")
    assert turnover["slack_minutes"] == 0, (
        f"slack must be exactly zero, got {turnover['slack_minutes']}")
    assert turnover["is_tight"] is True, (
        f"zero slack is strictly below 45 so the turn is tight, "
        f"got {turnover['is_tight']}")
    assert turnover["turn_type"] == "SAME_DAY"
    assert turnover["escalation_required"] is False, (
        f"a non-negative slack raises no escalation, "
        f"got {turnover['escalation_required']}")
    assert same_instant(turnover["window_start_at"], "2026-08-08T16:00:00Z")
    assert same_instant(turnover["window_end_at"], "2026-08-08T19:18:00Z"), (
        f"the arriving check-in must be pulled back by the 30-minute "
        f"inspection buffer, got {turnover['window_end_at']}")


def test_02_one_minute_short_of_the_requirement_is_refused(api, twin_properties):
    """197 against 198 draws ERR_WINDOW_OVERRIDE_REQUIRED and creates nothing.

    PRD §2.5: "**Window sufficiency at creation.** On `POST /turnovers`,
    `window_minutes` must be greater than or equal to `required_minutes` unless
    an `override_reason` is supplied. Failure yields
    `ERR_WINDOW_OVERRIDE_REQUIRED` (422)." PRD §3.3: "An optional
    `override_reason` may be supplied as justification for a window too short
    for the work."

    Design: Difficulty/boundary_precision_check/window_minutes_exactly_equals_required_minutes_accepted
    """
    world = twin_properties
    response = api.create_turnover(
        create_turnover_payload(world["b_out3"]["id"], world["b_in3"]["id"]),
        COORDINATOR)
    validate_error(response, ApiErrorId.ERR_WINDOW_OVERRIDE_REQUIRED.value, 422)

    rows, meta = validate_paginated(api.list_turnovers(
        COORDINATOR, {"property_id": world["p1b"]["id"]}))
    assert meta["total_count"] == 0, (
        f"the refused creation must leave no turnover behind, "
        f"got {meta['total_count']}")
    assert rows == []


# ─── restock_qty_used_exactly_equals_on_hand_qty_accepted ────────────────

def test_03_drawing_exactly_the_units_on_hand_is_permitted(
        api, single_bottle_world):
    """Two bottles are refused where one bottle is accepted.

    PRD §3.5: "Every entry's supply line must belong to the turnover's property
    (`ERR_PROPERTY_MISMATCH`) and its `qty_used` must not exceed that line's
    current `on_hand_qty` (`ERR_INSUFFICIENT_ON_HAND`)." PRD §3.5: "Submission
    is permitted from `PENDING` and from `REJECTED`, and requires that the
    acting cleaner owns the turnover's `ACTIVE` assignment and that the
    turnover's status is one of `IN_PROGRESS`, `AWAITING_VERIFICATION` or
    `REWORK_REQUIRED`; a task already `VERIFIED` or `WAIVED` cannot be
    submitted and draws `ERR_INVALID_TASK_STATE`."

    Design: Difficulty/boundary_precision_check/restock_qty_used_exactly_equals_on_hand_qty_accepted
    """
    world = single_bottle_world
    row, wine = world["restock_row"], world["supply_lines"][1]

    over = api.submit_checklist_task(
        row["id"],
        submit_task_payload(photo_uri="https://cdn.example.com/restock-over.jpg",
                            restock_entries=[restock_entry(wine["id"], 2)]),
        world["cleaner_headers"])
    validate_error(over, ApiErrorId.ERR_INSUFFICIENT_ON_HAND.value, 409)

    rows = validate_success(api.list_turnover_checklist_tasks(
        world["t1"]["id"], COORDINATOR))
    assert {r["id"]: r for r in rows}[row["id"]]["status"] == "PENDING", (
        "the refused submission must leave the row PENDING")

    ok = validate_success(api.submit_checklist_task(
        row["id"],
        submit_task_payload(photo_uri="https://cdn.example.com/restock-ok.jpg",
                            restock_entries=[restock_entry(wine["id"], 1)]),
        world["cleaner_headers"]))
    assert ok["status"] == "SUBMITTED", (
        f"drawing exactly the units on hand is legal, got {ok['status']}")
    assert ok["restock_line_count"] == 1, (
        f"one entry was carried, got {ok['restock_line_count']}")


def test_04_approving_the_at_boundary_draw_empties_the_line_below_par(
        api, single_bottle_world):
    """The line lands on 0 with below_par true and one version bump.

    PRD §2.9: "Immediately after that projection is refreshed, `below_par` is
    recomputed as true exactly when `on_hand_qty` is less than or equal to
    `reorder_point`." PRD §3.5: "each affected supply line then re-projects
    `on_hand_qty`, recomputes `below_par`, and has its `version` incremented by
    1."

    Design: Difficulty/boundary_precision_check/restock_qty_used_exactly_equals_on_hand_qty_accepted
    """
    world = single_bottle_world
    row, sheets, wine = (world["restock_row"], world["supply_lines"][0],
                         world["supply_lines"][1])
    validate_success(api.submit_checklist_task(
        row["id"],
        submit_task_payload(photo_uri="https://cdn.example.com/restock-ok.jpg",
                            restock_entries=[restock_entry(wine["id"], 1)]),
        world["cleaner_headers"]))

    reviewed = validate_success(api.review_checklist_task(
        row["id"], review_task_payload("APPROVE"), REVIEWER))
    assert reviewed["restock_charge_cents"] == 968, (
        f"the chargeback is 900 times 1.075 rounded half up, "
        f"got {reviewed['restock_charge_cents']}")

    line = fx.read_supply_line(api, wine["id"])
    assert line["on_hand_qty"] == 0, (
        f"the closet is drawn to exactly zero, got {line['on_hand_qty']}")
    assert line["below_par"] is True, (
        f"0 is at or below a reorder_point of 0, got {line['below_par']}")
    assert line["version"] == 2, (
        f"the consumption bumped the line's version exactly once, "
        f"got {line['version']}")
    assert fx.read_supply_line(api, sheets["id"])["on_hand_qty"] == 6, (
        "the line that was not drawn on must be untouched")


# ─── audit_score_exactly_at_penalty_threshold_yields_zero_adjustment ─────

def test_05_a_score_of_exactly_seventy_sits_in_the_neutral_band(
        api, audit_at_threshold):
    """The rolling score still falls to 85.40 while the adjustment stays 0.

    PRD §3.9: "`pay_adjustment_cents` is positive 1,000 cents when the `score`
    is greater than or equal to 95, negative 1,200 cents when the `score` is
    strictly below 70, and 0 for any score inside that neutral band." PRD §3.9:
    "From there both variants converge: `resulting_quality_score` is seventy
    percent of the cleaner's current `quality_score` plus thirty percent of
    `observed_score`, rounded half up to two decimals, and the cleaner's
    `quality_score` is then replaced by that figure."

    Design: Difficulty/boundary_precision_check/audit_score_exactly_at_penalty_threshold_yields_zero_adjustment
    """
    world = audit_at_threshold
    finalized = validate_success(
        api.finalize_quality_audit(world["audit"]["id"], {}, AUDITOR))

    assert finalized["variant_applied"] == "AUDIT_ONLY", (
        f"no rating landed on the arriving stay, "
        f"got {finalized['variant_applied']}")
    assert float(finalized["observed_score"]) == pytest.approx(70.00, abs=0.005)
    assert finalized["pay_adjustment_cents"] == 0, (
        f"a score of exactly 70 is not strictly below 70, "
        f"got {finalized['pay_adjustment_cents']}")
    assert float(finalized["resulting_quality_score"]) == pytest.approx(
        85.40, abs=0.005), (
        f"carryover must be 0.70 * 92.00 + 0.30 * 70.00, "
        f"got {finalized['resulting_quality_score']}")
    assert finalized["status"] == "FINALIZED"


def test_06_a_zero_adjustment_never_moves_the_pay_line_out_of_final(
        api, audit_at_threshold):
    """The settled money is untouched while the quality score is not.

    PRD §3.9: "When the adjustment is non-zero, the turnover's `FINAL` pay line
    folds it into `audit_adjustment_cents`, re-derives `net_cents` accordingly,
    moves `FINAL → ADJUSTED`, and the cleaner's `pending_payout_cents` moves by
    that same signed delta." PRD §3.9: "A neutral score leaves the pay line in
    `FINAL` untouched." PRD §2.8: "Its value is
    at all times the sum of `net_cents` over that cleaner's pay lines whose
    `status` is `PROVISIONAL`, `FINAL` or `ADJUSTED`."

    Design: Difficulty/boundary_precision_check/audit_score_exactly_at_penalty_threshold_yields_zero_adjustment
    """
    world = audit_at_threshold
    validate_success(api.finalize_quality_audit(world["audit"]["id"], {}, AUDITOR))

    pay = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))[0]
    assert pay["status"] == "FINAL", (
        f"a zero adjustment leaves the line in FINAL, got {pay['status']}")
    assert pay["audit_adjustment_cents"] == 0, (
        f"nothing was folded in, got {pay['audit_adjustment_cents']}")
    assert pay["net_cents"] == 11114, (
        f"the settled net is unchanged, got {pay['net_cents']}")

    cleaner = fx.read_cleaner(api, world)
    assert float(cleaner["quality_score"]) == pytest.approx(85.40, abs=0.005), (
        f"the rolling score still moves on a neutral audit, "
        f"got {cleaner['quality_score']}")
    assert cleaner["pending_payout_cents"] == 11114, (
        f"the ledger is unchanged, got {cleaner['pending_payout_cents']}")

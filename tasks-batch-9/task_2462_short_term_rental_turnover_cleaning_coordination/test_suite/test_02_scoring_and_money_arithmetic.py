"""Weighted matching, per-line chargeback rounding and the pinned late-penalty cap."""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_pay_line_arithmetic,
    cleaner_status_payload,
    fixtures as fx,
    restock_entry,
    review_task_payload,
    submit_task_payload,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def three_candidate_world(api):
    """P1 plus three eligible cleaners whose quality ranking is not the score ranking.

    `fx.build_world` also onboards the canonical Cleaner C (ZONE_A, skill 4,
    quality 92.00), which would score 0.9100 and win the selector outright, so
    it is suspended here: PRD §3.4 admits into the candidate pool only cleaners
    "whose `status` is `ACTIVE`", leaving exactly the three named candidates to
    be ranked.
    """
    world = fx.build_world(api, supply=None)
    validate_success(api.set_cleaner_status(
        world["cc"]["id"],
        cleaner_status_payload("SUSPEND", reason="not a candidate for this turn"),
        ADMIN))
    world["c_a"] = fx.seed_cleaner(
        api, name="Cleaner C_A", home_zone_code="ZONE_A", skill_level=3,
        initial_quality_score=92.00)
    world["c_b"] = fx.seed_cleaner(
        api, name="Cleaner C_B", home_zone_code="ZONE_B",
        secondary_zone_codes=["ZONE_A"], skill_level=2,
        initial_quality_score=98.00)
    world["c_c"] = fx.seed_cleaner(
        api, name="Cleaner C_C", home_zone_code="ZONE_A", skill_level=4,
        initial_quality_score=84.00)
    return world


@pytest.fixture
def submitted_restock_world(api):
    """Four supply lines and a SUBMITTED restock row consuming one unit of each."""
    world = fx.world_in_progress(api, supply="four")
    restock = next(t for t in world["tasks"] if t["category"] == "RESTOCK")
    entries = [restock_entry(line["id"], 1) for line in world["supply_lines"]]
    world["restock_task"] = validate_success(api.submit_checklist_task(
        restock["id"],
        submit_task_payload(photo_uri="https://cdn.example.com/restock.jpg",
                            restock_entries=entries),
        world["cleaner_headers"]))
    return world


@pytest.fixture
def very_late_completion_world(api):
    """Every row verified, then the clock pushed 1440 minutes past window_end_at."""
    world = fx.world_all_verified(api, supply="pair")
    fx.reset_clock(api, "2026-08-09T20:30:00Z")
    world["t1"] = validate_success(api.complete_turnover(
        world["t1"]["id"], {"completion_note": "very late finish"},
        world["cleaner_headers"]))
    return world


# ─── match_score_weighting_order_highest_quality_cleaner_loses ───────────

def test_01_selector_prefers_weighted_fit_over_the_highest_quality_cleaner(
        api, three_candidate_world):
    """The 98.00-quality secondary-zone cleaner loses to an 84.00 home-zone one.

    PRD §3.4: "The score is then the sum of three weighted terms: normalised
    quality weighted at 0.50, the zone factor weighted at 0.30, and skill
    headroom weighted at 0.20." PRD §3.4: "In selector mode the highest
    `match_score` wins, and ties are broken by a fixed chain applied in order:
    first the higher `skill_level`; then the lower count of the cleaner's
    non-terminal assignments on the same property-local date; then the earlier
    `created_at` on the cleaner record."

    Design: Difficulty/combinatorial_formula/match_score_weighting_order_highest_quality_cleaner_loses
    """
    world = three_candidate_world
    offer = validate_success(api.assign_turnover(
        world["t1"]["id"],
        {"expected_turnover_version": world["t1"]["version"]},
        COORDINATOR), 201)

    assert offer["cleaner_id"] == world["c_c"]["id"], (
        f"the 84.00-quality skill-4 home-zone cleaner must win the ranking, "
        f"got cleaner {offer['cleaner_id']}")
    assert float(offer["match_score"]) == pytest.approx(0.8700, abs=0.00005), (
        f"match_score must be 0.50*0.84 + 0.30*1.0 + 0.20*0.75, "
        f"got {offer['match_score']}")
    assert offer["selection_mode"] == "SELECTOR", (
        f"omitting cleaner_id must record SELECTOR, got {offer['selection_mode']}")
    assert float(offer["zone_match_factor"]) == pytest.approx(1.0, abs=0.00005)
    assert offer["status"] == "OFFERED" and offer["sequence_no"] == 1

    all_offers = validate_success(
        api.list_assignments(COORDINATOR, {"turnover_id": world["t1"]["id"]}))
    assert [o["cleaner_id"] for o in all_offers] == [world["c_c"]["id"]], (
        "the pool maximum on quality alone must not receive an offer")


def test_02_explicit_offers_record_the_same_three_weighted_terms(
        api, three_candidate_world):
    """Naming each candidate in turn exposes the three scores 0.8600/0.6600/0.8700.

    PRD §3.4: "The zone factor is 1.0 when the cleaner's `home_zone_code` equals
    the property's `zone_code`, 0.4 when the property's zone appears among the
    cleaner's `secondary_zone_codes`, and 0.0 otherwise, the last case being
    reachable only for a cleaner who accepts cross-zone work." PRD §3.4: "Skill
    headroom measures how far above the unit's floor the cleaner sits: take the
    cleaner's `skill_level`, subtract the property's `min_skill_level`, add 1,
    divide by 4, and cap the result at 1.0 — so a cleaner exactly at the floor
    scores 0.25 of headroom and a cleaner four tiers above it saturates."

    Design: Difficulty/combinatorial_formula/match_score_weighting_order_highest_quality_cleaner_loses
    """
    world = three_candidate_world
    expected = [
        (world["c_a"]["id"], 0.8600, 1.0),
        (world["c_b"]["id"], 0.6600, 0.4),
        (world["c_c"]["id"], 0.8700, 1.0),
    ]
    for cleaner_id, score, zone in expected:
        turnover = fx.read_turnover(api, world)
        offer = validate_success(api.assign_turnover(
            turnover["id"],
            {"expected_turnover_version": turnover["version"],
             "cleaner_id": cleaner_id}, COORDINATOR), 201)
        assert offer["selection_mode"] == "EXPLICIT", (
            f"naming a cleaner must record EXPLICIT, got {offer['selection_mode']}")
        assert float(offer["match_score"]) == pytest.approx(score, abs=0.00005), (
            f"match_score for cleaner {cleaner_id} must be {score}, "
            f"got {offer['match_score']}")
        assert float(offer["zone_match_factor"]) == pytest.approx(zone, abs=0.00005), (
            f"zone_match_factor must be {zone}, got {offer['zone_match_factor']}")

    turnover = fx.read_turnover(api, world)
    assert turnover["status"] == "PENDING_ASSIGNMENT", (
        f"an offer alone does not schedule the turnover, got {turnover['status']}")
    assert turnover["version"] == 4, (
        f"three offers must each bump the turnover version once, "
        f"got {turnover['version']}")


# ─── restock_chargeback_per_line_rounding_before_summation ───────────────

def test_03_chargeback_rounds_each_line_before_summing_the_row(
        api, submitted_restock_world):
    """Four lines that each land on a half cent sum to 1808, never 1806.

    PRD §3.6: "for each restock entry in the order supplied, multiply the supply
    line's `unit_cost_cents` by the entry's `qty_used` and then by a waste factor
    of 1.075 — a seven-and-a-half percent allowance for spoilage and partial
    packs — and round that product half up to whole cents; the row's
    `restock_charge_cents` is the sum of those already-rounded per-line charges."

    Design: Difficulty/combinatorial_formula/restock_chargeback_per_line_rounding_before_summation
    """
    world = submitted_restock_world
    assert world["restock_task"]["restock_line_count"] == 4, (
        f"the submission must record four restock entries, "
        f"got {world['restock_task']['restock_line_count']}")

    reviewed = validate_success(api.review_checklist_task(
        world["restock_task"]["id"], review_task_payload("APPROVE"), REVIEWER))

    assert reviewed["restock_charge_cents"] == 1808, (
        f"the row charge must be 280 + 194 + 366 + 968 = 1808 rather than the "
        f"1806 a pre-waste subtotal would give, got {reviewed['restock_charge_cents']}")
    assert reviewed["status"] == "VERIFIED", (
        f"approval must move the row to VERIFIED, got {reviewed['status']}")


def test_04_each_appended_movement_carries_its_own_rounded_line_charge(
        api, submitted_restock_world):
    """The ledger rows carry 280, 194, 366 and 968 cents against delta_qty -1.

    PRD §3.6: "For a `RESTOCK` row, approval is the moment stock actually leaves
    the closet: one stock movement is appended per submitted restock entry, in
    the exact order the entries were supplied, each with `reason` `RESTOCK_USE`
    and a `delta_qty` equal to the negative of that entry's `qty_used`; each
    affected supply line then re-projects `on_hand_qty`, recomputes `below_par`,
    and has its `version` incremented by 1." PRD
    §3.6: "Each appended movement carries its own per-line figure in
    `charge_cents`, so summing `charge_cents` across the ledger always
    reconciles with the surviving row charges."

    Design: Difficulty/combinatorial_formula/restock_chargeback_per_line_rounding_before_summation
    """
    world = submitted_restock_world
    validate_success(api.review_checklist_task(
        world["restock_task"]["id"], review_task_payload("APPROVE"), REVIEWER))

    expected_charges = {"LIN-SHEET-Q": 280, "LIN-TOWEL-B": 194,
                        "CON-COFFEE": 366, "WEL-WINE": 968}
    for line in world["supply_lines"]:
        movements = fx.read_movements(api, {"supply_line_id": line["id"]})
        assert len(movements) == 2, (
            f"line {line['sku']} must carry a SEED and one RESTOCK_USE movement, "
            f"got {len(movements)}")
        use = movements[1]
        assert use["reason"] == "RESTOCK_USE"
        assert use["delta_qty"] == -1, (
            f"delta_qty must negate qty_used, got {use['delta_qty']}")
        assert use["charge_cents"] == expected_charges[line["sku"]], (
            f"{line['sku']} must charge {expected_charges[line['sku']]}, "
            f"got {use['charge_cents']}")

    sl1 = fx.read_supply_line(api, world["supply_lines"][0]["id"])
    sl4 = fx.read_supply_line(api, world["supply_lines"][3]["id"])
    assert sl1["on_hand_qty"] == 5, (
        f"the sheet line must project 6 - 1, got {sl1['on_hand_qty']}")
    assert sl4["on_hand_qty"] == 0, (
        f"the wine line must project 1 - 1, got {sl4['on_hand_qty']}")
    assert sl4["below_par"] is True, (
        "a line projected to 0 against reorder_point 0 must be below_par")


# ─── late_penalty_cap_pinned_to_post_linen_gross_before_bonuses ──────────

def test_05_late_penalty_is_capped_against_the_gross_that_includes_the_linen_adder(
        api, very_late_completion_world):
    """1440 late minutes cap at 2944 cents, not 2498 off the bare base.

    PRD §3.8: "`late_penalty_cents` is the smaller of that raw charge and thirty
    percent of `gross_cents` rounded half up." PRD §3.8: "*Step four, the
    gross.* `gross_cents` is `size_base_cents` plus `rush_premium_cents` plus
    `tight_window_premium_cents` plus `cross_zone_premium_cents` plus
    `linen_adder_cents`. This figure — and not some later net — is the cap base
    for the lateness charge."

    Design: Difficulty/combinatorial_formula/late_penalty_cap_pinned_to_post_linen_gross_before_bonuses
    """
    world = very_late_completion_world
    assert world["t1"]["late_minutes"] == 1440, (
        f"finishing a day past window_end_at must record 1440 late minutes, "
        f"got {world['t1']['late_minutes']}")

    pay = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))[0]
    assert pay["gross_cents"] == 9814, (
        f"gross must be 8325 + 1249 + 0 + 0 + 240, got {pay['gross_cents']}")
    assert pay["late_penalty_cents"] == 2944, (
        f"the cap must be 30 percent of 9814 rather than of the bare base "
        f"(2498) or of a post-bonus figure (3094), "
        f"got {pay['late_penalty_cents']}")
    assert_pay_line_arithmetic(pay)


def test_06_lateness_clears_the_on_time_bonus_but_leaves_the_photo_pass_bonus(
        api, very_late_completion_world):
    """The settled net is 7370 cents with a 500-cent photo-pass bonus surviving.

    PRD §3.8: "*Step six, the bonuses.* `on_time_bonus_cents` is 800 cents when
    the pay line's `late_minutes` is 0 and 0 otherwise — which under the
    `PROVISIONAL` variant means it is always granted, because provisional
    lateness is forced to zero." PRD §3.8: "`photo_pass_bonus_cents` is 500
    cents when the turnover's `rejected_review_count` is 0 and 0 otherwise;
    photo penalties from rejections already booked apply under both variants,
    so a provisional line can carry a photo penalty and no photo-pass bonus."

    Design: Difficulty/combinatorial_formula/late_penalty_cap_pinned_to_post_linen_gross_before_bonuses
    """
    world = very_late_completion_world
    pay = validate_success(
        api.list_pay_lines(COORDINATOR, {"turnover_id": world["t1"]["id"]}))[0]

    assert pay["on_time_bonus_cents"] == 0, (
        f"a late finish forfeits the on-time bonus, got {pay['on_time_bonus_cents']}")
    assert pay["photo_pass_bonus_cents"] == 500
    assert pay["bonus_cents"] == 500, (
        f"bonus_cents must be 0 + 500, got {pay['bonus_cents']}")
    assert pay["photo_penalty_cents"] == 0, (
        f"no row was rejected so there is no photo penalty, "
        f"got {pay['photo_penalty_cents']}")
    assert pay["net_cents"] == 7370, (
        f"net must be 9814 + 500 - 2944, and neither 7816 nor 7220, "
        f"got {pay['net_cents']}")
    assert pay["variant"] == "FINAL"

    cleaner = fx.read_cleaner(api, world)
    assert cleaner["pending_payout_cents"] == 7370, (
        f"the ledger must hold exactly the settled net, "
        f"got {cleaner['pending_payout_cents']}")

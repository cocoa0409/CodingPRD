"""ID-check outcomes (age + expiry gates) and the cover-charge pricing engine.

Difficulty queue (A): dual_variant_calc, boundary_precision_check, combinatorial_formula.
Corner queue (B): calculations variants.
"""
import pytest
from test_helpers import validate_success
from test_helpers import fixtures as fx

ADMIN = fx.ADMIN
DOOR = fx.DOOR


# ── ID-check outcome: PASS vs expired-override (dual variant) ─────────────────

def test_id_check_pass_vs_expired_override(api):
    """PRD §3.3: "If the document's `id_expiry` is strictly before the clock's
    current date, the `outcome` is `REFUSED_EXPIRED_ID` with a `refusal_reason` of
    "ID expired" — and this fires even for a patron well over 21, so an expired ID
    of a 25-year-old is refused for expiry rather than passing."
    PRD §3.3: "Otherwise the `outcome` is `PASS` and the `refusal_reason` is null."

    Design: Difficulty/dual_variant_calc/id_check_outcome_pass_vs_expired_override
    """
    fx.set_clock("2026-03-15T20:00:00Z")
    venue = fx.create_venue(name="V")
    p1 = fx.create_id_check(venue["id"], patron_name="P1",
                            date_of_birth="2000-01-01", id_expiry="2027-01-01")
    p2 = fx.create_id_check(venue["id"], patron_name="P2",
                            date_of_birth="2000-01-01", id_expiry="2026-03-14")
    assert p1["outcome"] == "PASS"
    assert p2["outcome"] == "REFUSED_EXPIRED_ID"
    assert p2["computed_age_years"] == 26


def test_expired_id_refusal_outcome_triggerable(api):
    """PRD §3.3: "If the document's `id_expiry` is strictly before the clock's
    current date, the `outcome` is `REFUSED_EXPIRED_ID` with a `refusal_reason` of
    "ID expired"...."

    Design: Difficulty/dual_variant_calc/id_check_outcome_pass_vs_expired_override
    """
    fx.set_clock("2026-03-15T20:00:00Z")
    venue = fx.create_venue(name="V")
    idc = fx.create_id_check(venue["id"], patron_name="Old",
                             date_of_birth="1980-01-01", id_expiry="2026-03-14")
    assert idc["outcome"] == "REFUSED_EXPIRED_ID"
    assert idc["refusal_reason"] == "ID expired"


# ── Age boundary: exactly 21 passes (inclusive) ──────────────────────────────

def test_age_exactly_21_passes_inclusive(api):
    """PRD §3.3: "The legal drinking age is 21, and the boundary is inclusive: a
    `computed_age_years` of 21 passes, while 20 is underage."
    PRD §3.3: "A patron whose birthday falls exactly on the check date has already
    had that birthday, so the age increments that day."

    Design: Difficulty/boundary_precision_check/age_exactly_21_passes_inclusive
    """
    fx.set_clock("2026-03-15T20:00:00Z")
    venue = fx.create_venue(name="V")
    exactly21 = fx.create_id_check(venue["id"], patron_name="Exactly21",
                                   date_of_birth="2005-03-15", id_expiry="2030-01-01")
    day20 = fx.create_id_check(venue["id"], patron_name="Day20",
                               date_of_birth="2005-03-16", id_expiry="2030-01-01")
    assert exactly21["computed_age_years"] == 21
    assert exactly21["outcome"] == "PASS"
    assert day20["computed_age_years"] == 20
    assert day20["outcome"] == "REFUSED_UNDERAGE"


def test_age_one_year_under_is_refused_underage(api):
    """PRD §3.3: "Only if the document is unexpired does the age gate apply: if
    `computed_age_years` is below 21 the `outcome` is `REFUSED_UNDERAGE` with a
    `refusal_reason` of "Under legal drinking age"."

    Design: Difficulty/boundary_precision_check/age_exactly_21_passes_inclusive
    """
    fx.set_clock("2026-03-15T20:00:00Z")
    venue = fx.create_venue(name="V")
    under = fx.create_id_check(venue["id"], patron_name="Under",
                               date_of_birth="2006-03-15", id_expiry="2030-01-01")
    assert under["computed_age_years"] == 20
    assert under["outcome"] == "REFUSED_UNDERAGE"
    assert under["refusal_reason"] == "Under legal drinking age"


# NOTE: Difficulty/combinatorial_formula/cover_charge_surge_then_discount_then_comp_mode_a
# is SKIPPED. The PRD (§3.4) uniquely derives cover_paid for that scenario as
#   surged = round_half_up(2000 * 1.5) = 3000
#   after_discount = round_half_up(3000 * (1 - 0.5)) = 1500
#   cover = max(0, 1500 - comp 200) = 1300
# but the design instance asserts 800. Two PRD-only readers both arrive at 1300, never
# 800, so the instance's literal is not PRD-derivable (Core rule: unique derivability).
# The combinatorial_formula rule is still covered (>=2 tests) by its other instance,
# tab_gratuity_sum_then_round_mode_b, in test_05.


# ── Cover charge corner variants ─────────────────────────────────────────────

def test_cover_walk_up_full_no_discount(api):
    """PRD §3.4: "A walk-up admission carries no `guest_list_entry_id` at all: it
    receives neither discount nor comp, and its cover is exactly the surged figure
    (full surged base)."
    PRD §3.4: "otherwise the surged figure is simply the base."

    Design: Corner/calculations/cover_walk_up_full_no_discount
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10,
                            cover_base_cents=2000, cover_surge_pct=0.5)
    idc = fx.create_id_check(venue["id"], patron_name="A",
                             date_of_birth="1990-01-01", id_expiry="2030-01-01")
    res = api.create_entry(
        {"venue_id": venue["id"], "id_check_id": idc["id"],
         "expected_venue_version": venue["version"]},
        DOOR,
    )
    entry = validate_success(res, 201)
    assert entry["cover_paid_cents"] == 2000


def test_cover_house_list_surge_waived(api):
    """PRD §3.4: "A house-list admission carries a `guest_list_entry_id` whose
    `promoter_id` is null: here the surge is waived entirely — the base is used
    rather than the surged figure — the percentage discount is zero, but the comp
    still applies."

    Design: Corner/calculations/cover_house_list_surge_waived
    """
    venue = fx.create_venue(name="V", fire_code_capacity=10,
                            cover_base_cents=2000, cover_surge_pct=0.5)
    gle = fx.create_guest_list_entry(venue["id"], guest_name="House",
                                     party_size=1, comp_value_cents=500)
    idc = fx.create_id_check(venue["id"], patron_name="House",
                             date_of_birth="1990-01-01", id_expiry="2030-01-01")
    injected = validate_success(api.inject_occupancy(venue["id"], 9, ADMIN), 200)
    res = api.create_entry(
        {"venue_id": venue["id"], "id_check_id": idc["id"],
         "guest_list_entry_id": gle["id"], "expected_venue_version": injected["version"]},
        DOOR,
    )
    entry = validate_success(res, 201)
    # base 2000 (surge waived), disc 0, comp 500 -> 1500
    assert entry["cover_paid_cents"] == 1500

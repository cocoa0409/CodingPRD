"""Consistency of the vintage cascade: registering a successor vintage mutates
entries on an already PUBLISHED list version, and the derived counters plus the
parent's state are already correct in the first read after the response returns.

Every test in this file translates one instance of the `consistency_model`
section of SCAFFOLD_CORNER_DESIGN.yaml.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import BEVERAGE_DIRECTOR_HEADERS

CATEGORY_TARGETS = {
    "SPARKLING": 30.0,
    "WHITE": 25.0,
    "ROSE": 28.0,
    "RED": 28.0,
    "DESSERT": 32.0,
    "FORTIFIED": 35.0,
}


def _wine(**overrides):
    base = {
        "producer": "Ridge",
        "cuvee": "Monte Bello",
        "vintage_year": 2019,
        "category": "RED",
        "reference_cost_cents": 2400,
        "bottle_size_ml": 750,
        "case_pack": 6,
        "is_allocated": False,
    }
    base.update(overrides)
    return fx.create_wine(**base)


def _published_list_with_two_entries():
    """Venue HRB with a PUBLISHED version holding wine A and wine B.

    Both wines cost 2400 cents and the venue's RED target is 28.00 percent, so
    each entry's frozen bottle price is 8600 cents.
    """
    fx.set_clock("2026-09-01T12:00:00Z")
    venue = fx.create_venue(cogs_target_pct_by_category=dict(CATEGORY_TARGETS))
    wine_a = _wine(cuvee="Monte Bello")
    wine_b = _wine(cuvee="Geyserville")
    wine_list = fx.create_wine_list(venue)
    version = fx.create_draft_version(wine_list, venue)
    entry_a = fx.add_entry(version, wine_a, venue, sort_rank=1,
                           by_the_glass=False, par_bottles=6)
    entry_b = fx.add_entry(version, wine_b, venue, sort_rank=2,
                           by_the_glass=False, par_bottles=6)
    published = fx.publish_version(version, venue)
    return {"venue": venue, "wine_a": wine_a, "wine_b": wine_b,
            "wine_list": wine_list, "version": published,
            "entry_a": entry_a, "entry_b": entry_b}


def _read_version(chain):
    return validate_success(api_client.get_list_version(
        chain["version"]["id"], BEVERAGE_DIRECTOR_HEADERS))


def _read_entry(entry):
    return validate_success(api_client.get_list_entry(
        entry["id"], BEVERAGE_DIRECTOR_HEADERS))


def _successor_of(wine, cuvee):
    return _wine(cuvee=cuvee, vintage_year=2020, reference_cost_cents=2500,
                 predecessor_wine_id=wine["id"])


class TestVintageCascadeIsImmediatelyVisible:
    """Nothing in this API is deferred: the entry flags, the version's derived
    counters and the version's own state all move on the write that causes them,
    not on some later reconciliation."""

    def test_a_successor_vintage_stales_the_entry_in_the_very_next_read(self):
        """Registering a 2020 Monte Bello naming the 2019 row as its predecessor
        stales the live entry for the predecessor immediately.

        "Every list entry referencing the predecessor wine, on any version whose state is `DRAFT`, `IN_REVIEW`, `PUBLISHED` or `REPRINT_PENDING`, has `vintage_stale` set to true."

        Design: Corner/consistency_model/vintage_cascade_is_visible_in_the_same_response_and_immediate_reads
        """
        chain = _published_list_with_two_entries()
        assert _read_entry(chain["entry_a"])["vintage_stale"] is False
        successor = _successor_of(chain["wine_a"], "Monte Bello")
        assert successor["predecessor_wine_id"] == chain["wine_a"]["id"], (
            successor["predecessor_wine_id"])
        entry_a = _read_entry(chain["entry_a"])
        assert entry_a["vintage_stale"] is True, entry_a["vintage_stale"]
        predecessor = validate_success(api_client.get_wine(
            chain["wine_a"]["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert predecessor["successor_count"] == 1, predecessor["successor_count"]

    def test_one_stale_entry_leaves_the_version_below_the_reprint_threshold(self):
        """A single superseded vintage on a live list is tolerated as an errata:
        the recount is already 1 and the reprint obligation is still false.

        "Each affected version recounts its `stale_entry_count` and rewrites `reprint_required`, which is true exactly when the stale count has reached two entries and false below that."

        Design: Corner/consistency_model/vintage_cascade_is_visible_in_the_same_response_and_immediate_reads
        """
        chain = _published_list_with_two_entries()
        _successor_of(chain["wine_a"], "Monte Bello")
        version = _read_version(chain)
        assert version["stale_entry_count"] == 1, version["stale_entry_count"]
        assert version["reprint_required"] is False, version["reprint_required"]
        assert version["state"] == "PUBLISHED", version["state"]

    def test_the_second_stale_entry_flips_the_version_to_reprint_pending(self):
        """The second superseded vintage crosses the two-entry threshold, and the
        immediate read already reports the reprint obligation and the new state.

        "A version that is currently `PUBLISHED` and whose `reprint_required` has just become true moves `PUBLISHED → REPRINT_PENDING`, and that transition sets `pinned_version_stale` to true on every wine dinner event in state `PLANNED`, `PRICED` or `CONFIRMED` that pins it."

        Design: Corner/consistency_model/vintage_cascade_is_visible_in_the_same_response_and_immediate_reads
        """
        chain = _published_list_with_two_entries()
        _successor_of(chain["wine_a"], "Monte Bello")
        _successor_of(chain["wine_b"], "Geyserville")
        version = _read_version(chain)
        assert version["stale_entry_count"] == 2, version["stale_entry_count"]
        assert version["reprint_required"] is True, version["reprint_required"]
        assert version["state"] == "REPRINT_PENDING", version["state"]
        entry_b = _read_entry(chain["entry_b"])
        assert entry_b["vintage_stale"] is True, entry_b["vintage_stale"]

    def test_each_cascaded_write_bumps_the_list_version_itself(self):
        """The version is itself a mutation on each cascade, so its own version
        integer advances once per successor registration.

        "Whenever a resource changes as part of such a cascade, its own `updated_at` is refreshed and its own `version` increments by 1 — a parent whose counters move because a child was written is itself a mutation."

        Design: Corner/consistency_model/vintage_cascade_is_visible_in_the_same_response_and_immediate_reads
        """
        chain = _published_list_with_two_entries()
        before = _read_version(chain)["version"]
        _successor_of(chain["wine_a"], "Monte Bello")
        after_first = _read_version(chain)["version"]
        assert after_first == before + 1, (before, after_first)
        _successor_of(chain["wine_b"], "Geyserville")
        after_second = _read_version(chain)["version"]
        assert after_second == after_first + 1, (after_first, after_second)

    def test_the_successors_higher_reference_cost_does_not_reprice_the_list(self):
        """Both entries keep the 8600-cent price computed from the 2400-cent 2019
        catalogue rows, even though the successors cost 2500 cents.

        "The bottle price is derived from the wine's catalogue cost in a fixed sequence, and it is frozen onto the entry as `bottle_price_cents` at creation."

        Design: Corner/consistency_model/vintage_cascade_is_visible_in_the_same_response_and_immediate_reads
        """
        chain = _published_list_with_two_entries()
        assert chain["entry_a"]["bottle_price_cents"] == 8600, (
            chain["entry_a"]["bottle_price_cents"])
        assert chain["entry_b"]["bottle_price_cents"] == 8600, (
            chain["entry_b"]["bottle_price_cents"])
        _successor_of(chain["wine_a"], "Monte Bello")
        _successor_of(chain["wine_b"], "Geyserville")
        for entry in (chain["entry_a"], chain["entry_b"]):
            after = _read_entry(entry)
            assert after["bottle_price_cents"] == 8600, (
                after["bottle_price_cents"])
            assert after["price_band"] == "CORE", after["price_band"]

"""Compensating pairs: undoing a movement by appending, never by editing.

Two conserved quantities are exercised.  Reversing an approved spoilage
write-off must put the same bottles back into the same lot and the same bin, thaw
the list availability it froze, and return the venue's cost ledger to its
pre-approval value -- while the original `SPOILAGE` ledger row stays byte-for-byte
as it was written and a negating `REVERSAL` row is appended beside it.  Voiding a
wine-dinner settlement is the harder case: it unwinds a multi-lot FIFO draw in
the exact per-lot proportions it was taken and returns two independent ledgers,
cost and revenue, to zero.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_WRITE_OFF_NOT_APPROVED
from test_helpers.assertions import (
    assert_append_only_fields,
    assert_decimal_equals,
    assert_entry_unchanged,
    assert_fields_equal,
    assert_ledger_sums_to_zero,
    assert_null_fields,
    depletion_entries_for,
)
from test_helpers.test_users import BEVERAGE_DIRECTOR_HEADERS, CONTROLLER_HEADERS

_CATEGORY_TARGETS = f.cogs_targets(
    30.0, WHITE=25.0, ROSE=28.0, RED=28.0, DESSERT=32.0, FORTIFIED=35.0)


def _harbor_room(**overrides):
    fx.set_clock("2026-09-01T12:00:00Z")
    return fx.create_venue(name="Harbor Room", venue_code="HRB",
                           cogs_target_pct_by_category=_CATEGORY_TARGETS,
                           priority_rank=1, **overrides)


def _red_wine():
    return fx.create_wine(producer="Ridge", cuvee="Monte Bello", vintage_year=2019,
                          category="RED", reference_cost_cents=2400,
                          bottle_size_ml=750, case_pack=6, is_allocated=False)


def _lot(lot):
    return validate_success(api_client.get_inventory_lot(
        lot["id"], BEVERAGE_DIRECTOR_HEADERS))


def _bin(bin_):
    return validate_success(api_client.get_cellar_bin(
        bin_["id"], BEVERAGE_DIRECTOR_HEADERS))


def _entry(entry):
    return validate_success(api_client.get_list_entry(
        entry["id"], BEVERAGE_DIRECTOR_HEADERS))


def _version(version):
    return validate_success(api_client.get_list_version(
        version["id"], BEVERAGE_DIRECTOR_HEADERS))


def _ledger_row(entries, reason, lot_id=None):
    """The single ledger row with this reason (and lot, when given)."""
    matches = [row for row in entries
               if row["reason"] == reason
               and (lot_id is None or row["lot_id"] == lot_id)]
    assert len(matches) == 1, (
        "expected exactly one %s row for lot %r, got %d"
        % (reason, lot_id, len(matches)))
    return matches[0]


def _approved_whole_case_write_off():
    """A published bottle-only listing whose entire 12-bottle lot has been written off."""
    venue = _harbor_room()
    chain = fx.setup_published_entry(
        venue=venue, wine=_red_wine(), by_the_glass=False, bottles_received=12,
        unit_cost_cents=2400, received_at="2026-08-10T00:00:00Z",
        entry_overrides={"par_bottles": 6, "education_verified": False})
    write_off = fx.submit_write_off(
        venue, chain["lot"], bottles=12, reason_code="CORKED",
        narrative="Whole case corked on receipt inspection.")
    chain["write_off"] = fx.approve_write_off(write_off)
    return chain


def _assert_post_approval_state(chain):
    """The state the approval cascade must have produced before any reversal."""
    assert_fields_equal(chain["write_off"], {"state": "APPROVED",
                                             "cogs_cents": 28800},
                        name="approved write-off")
    assert_fields_equal(_lot(chain["lot"]), {"bottles_on_hand": 0,
                                             "state": "DEPLETED"},
                        name="lot after approval")
    depleted_bin = _bin(chain["bin"])
    assert depleted_bin["bottles_stored"] == 0
    assert_decimal_equals(depleted_bin["utilization_pct"], 0.00,
                          field="utilization_pct")
    assert _entry(chain["entry"])["availability_state"] == "OUT_OF_STOCK"
    assert _version(chain["version"])["out_of_stock_entry_count"] == 1
    assert fx.get_venue(chain["venue"])["cogs_ledger_cents"] == 28800


class TestWriteOffReversalConservesBottles:
    """Approving a 12-bottle `CORKED` write-off empties the lot, empties the bin
    and takes the listing out of stock; the reversal must put every one of those
    figures back exactly, and must do it by appending to the ledger."""

    def test_reversing_the_write_off_restores_bottles_bin_and_list_availability(self):
        """Every bottle, the bin occupancy and the listing's availability return exactly.

        "The lot's `bottles_on_hand` rises by the written-off count, and a lot that had gone `DEPLETED` returns `DEPLETED → ON_HAND`; the bin's `bottles_stored` rises by the same amount and its `utilization_pct` is recomputed."

        Design: Difficulty/compensating_invariant/write_off_reversal_restores_bottle_conservation_without_editing_history
        """
        chain = _approved_whole_case_write_off()
        _assert_post_approval_state(chain)

        reversed_write_off = fx.reverse_write_off(
            chain["write_off"],
            "Supplier credit denied; bottles returned to the cellar.")
        assert_fields_equal(reversed_write_off, {"state": "REVERSED",
                                                "cogs_cents": 28800},
                            name="reversed write-off")

        assert_fields_equal(_lot(chain["lot"]), {"bottles_on_hand": 12,
                                                "state": "ON_HAND"},
                            name="lot after reversal")
        restored_bin = _bin(chain["bin"])
        assert restored_bin["bottles_stored"] == 12
        assert_decimal_equals(restored_bin["utilization_pct"], 25.00,
                              field="utilization_pct")
        assert _entry(chain["entry"])["availability_state"] == "AVAILABLE"
        assert _version(chain["version"])["out_of_stock_entry_count"] == 0
        assert fx.get_venue(chain["venue"])["cogs_ledger_cents"] == 0, (
            "the cost ledger must return to its pre-approval value, not a residual")

    def test_the_original_spoilage_row_is_never_edited_and_the_pair_sums_to_zero(self):
        """History grows by a negating row; the approval row is byte-identical afterwards.

        "On success the write-off moves `APPROVED → REVERSED` and one further ledger entry is appended with reason `REVERSAL`, a negative `bottles` equal to the negation of the written-off count, a negative `cogs_cents` equal to the negation of the recognised cost, zero `revenue_cents` and the same `write_off_id`, so that the approval entry and the reversal entry sum to exactly zero."

        Design: Difficulty/compensating_invariant/write_off_reversal_restores_bottle_conservation_without_editing_history
        """
        chain = _approved_whole_case_write_off()
        write_off_id = chain["write_off"]["id"]
        before = depletion_entries_for(CONTROLLER_HEADERS,
                                      write_off_id=write_off_id)
        assert len(before) == 1, (
            "the approval writes exactly one SPOILAGE row, got %d" % (len(before),))
        spoilage_before = _ledger_row(before, "SPOILAGE")
        assert_append_only_fields(spoilage_before)
        assert_fields_equal(spoilage_before, {"bottles": 12,
                                              "cogs_cents": 28800,
                                              "revenue_cents": 0},
                            name="SPOILAGE row")

        fx.reverse_write_off(chain["write_off"],
                             "Supplier credit denied; bottles returned to the cellar.")

        after = depletion_entries_for(CONTROLLER_HEADERS,
                                     write_off_id=write_off_id)
        assert len(after) == 2, (
            "the reversal appends a second row rather than rewriting the first,"
            " got %d rows" % (len(after),))
        assert_entry_unchanged(spoilage_before,
                              _ledger_row(after, "SPOILAGE"),
                              name="SPOILAGE ledger row")
        reversal = _ledger_row(after, "REVERSAL")
        assert_append_only_fields(reversal)
        assert_fields_equal(reversal, {"bottles": -12, "cogs_cents": -28800,
                                       "revenue_cents": 0},
                            name="REVERSAL row")
        assert_ledger_sums_to_zero(after, "bottles")
        assert_ledger_sums_to_zero(after, "cogs_cents")

    def test_a_second_reversal_is_refused_and_does_not_double_credit_the_lot(self):
        """A reversed write-off is no longer approved, so the second reversal is refused.

        "It is controller-exclusive, carries a mandatory `note` stored as `resolution_note`, and requires the write-off to be in `APPROVED` (`ERR_WRITE_OFF_NOT_APPROVED`, HTTP 409) and the lot to be either `ON_HAND` or `DEPLETED` — a lot that has already gone terminally `WRITTEN_OFF` is frozen and the reversal is refused with `ERR_LOT_NOT_ON_HAND`."

        Design: Difficulty/compensating_invariant/write_off_reversal_restores_bottle_conservation_without_editing_history
        """
        chain = _approved_whole_case_write_off()
        fx.reverse_write_off(chain["write_off"],
                             "Supplier credit denied; bottles returned to the cellar.")

        validate_error(api_client.reverse_write_off(
            chain["write_off"]["id"],
            f.note_payload("Second attempt at the same credit."),
            CONTROLLER_HEADERS), ERR_WRITE_OFF_NOT_APPROVED)

        assert_fields_equal(_lot(chain["lot"]), {"bottles_on_hand": 12,
                                                "state": "ON_HAND"},
                            name="lot after the refused second reversal")
        assert len(depletion_entries_for(CONTROLLER_HEADERS,
                                        write_off_id=chain["write_off"]["id"])) == 2


def _settled_dinner_across_two_lots():
    """A FIFO settlement that drains a 6-bottle lot and bites 2 bottles into the next."""
    venue = _harbor_room(costing_method="FIFO", event_cogs_target_pct=28.0)
    wine = _red_wine()
    bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                         capacity_bottles=48, temperature_controlled=True)
    lot1 = fx.create_lot(venue, wine, bin_, bottles_received=6,
                         unit_cost_cents=3000, received_at="2026-08-10T00:00:00Z")
    lot2 = fx.create_lot(venue, wine, bin_, bottles_received=6,
                         unit_cost_cents=5000, received_at="2026-08-20T00:00:00Z")
    drafted = fx.setup_draft_version(venue)
    entry = fx.add_entry(drafted["version"], wine, venue, sort_rank=1,
                         by_the_glass=True, pour_size_ml=177, par_bottles=6,
                         education_verified=False)
    version = fx.publish_version(drafted["version"], venue)
    event = fx.create_event(venue, version, [f.pour_plan_line(entry["id"], 2)],
                            name="Ridge Vertical",
                            starts_at="2026-10-10T18:00:00Z",
                            ends_at="2026-10-10T21:00:00Z", seat_count=24)
    fx.price_event(event, venue)
    fx.confirm_event(event)
    settled = fx.settle_event(event)
    return {"venue": venue, "wine": wine, "bin": bin_, "lot1": lot1, "lot2": lot2,
            "version": version, "entry": entry, "event": settled}


class TestSettlementVoidRestoresBothLedgers:
    """The dinner needs 8 bottles at a 6-pour event yield, so FIFO takes all 6 of
    the 3000-cent lot and 2 of the 5000-cent lot.  Voiding must unwind that split
    exactly and return both the cost and the revenue ledger to zero."""

    def test_voiding_the_settlement_returns_each_bottle_to_the_lot_it_came_from(self):
        """Six bottles go back to the first lot and two to the second -- not four and four.

        "Every bottle drawn at settlement returns to the exact lot it came from, lots that had gone `DEPLETED` return `DEPLETED → ON_HAND`, and the bins re-absorb the bottles."

        Design: Difficulty/compensating_invariant/event_settlement_void_restores_monetary_and_lot_ledgers
        """
        chain = _settled_dinner_across_two_lots()
        assert_fields_equal(chain["event"], {"state": "SETTLED",
                                            "settled_cogs_cents": 28000,
                                            "settled_revenue_cents": 72000},
                            name="settled dinner")
        assert_fields_equal(_lot(chain["lot1"]), {"bottles_on_hand": 0,
                                                 "state": "DEPLETED"},
                            name="first lot after settlement")
        assert_fields_equal(_lot(chain["lot2"]), {"bottles_on_hand": 4,
                                                 "state": "ON_HAND"},
                            name="second lot after settlement")

        voided = fx.void_event_settlement(
            chain["event"], "Event postponed after settlement was posted in error.")
        assert voided["state"] == "SETTLEMENT_VOIDED"

        assert_fields_equal(_lot(chain["lot1"]), {"bottles_on_hand": 6,
                                                 "state": "ON_HAND"},
                            name="first lot after the void")
        assert_fields_equal(_lot(chain["lot2"]), {"bottles_on_hand": 6,
                                                 "state": "ON_HAND"},
                            name="second lot after the void")
        restored_bin = _bin(chain["bin"])
        assert restored_bin["bottles_stored"] == 12
        assert_decimal_equals(restored_bin["utilization_pct"], 25.00,
                              field="utilization_pct")

    def test_voiding_the_settlement_zeroes_both_ledgers_and_nulls_the_settled_figures(self):
        """Cost and revenue both return to their pre-settlement values of zero.

        "Both venue ledgers return to their pre-settlement values, and `settled_cogs_cents` and `settled_revenue_cents` are reset to null."

        Design: Difficulty/compensating_invariant/event_settlement_void_restores_monetary_and_lot_ledgers
        """
        chain = _settled_dinner_across_two_lots()
        settled_venue = fx.get_venue(chain["venue"])
        assert_fields_equal(settled_venue, {"cogs_ledger_cents": 28000,
                                            "revenue_ledger_cents": 72000},
                            name="venue after settlement")

        voided = fx.void_event_settlement(
            chain["event"], "Event postponed after settlement was posted in error.")
        assert_null_fields(voided, "settled_cogs_cents", "settled_revenue_cents")

        assert_fields_equal(fx.get_venue(chain["venue"]),
                            {"cogs_ledger_cents": 0, "revenue_ledger_cents": 0},
                            name="venue after the void")

    def test_the_settlement_rows_survive_the_void_and_the_four_rows_sum_to_zero(self):
        """Two EVENT rows are joined by two negating REVERSAL rows, not overwritten.

        "For each entry the settlement wrote, one further entry is appended with reason `REVERSAL` carrying the exact negation of that entry's `bottles`, `cogs_cents` and `revenue_cents`."

        Design: Difficulty/compensating_invariant/event_settlement_void_restores_monetary_and_lot_ledgers
        """
        chain = _settled_dinner_across_two_lots()
        event_id = chain["event"]["id"]
        lot1_id = chain["lot1"]["id"]
        lot2_id = chain["lot2"]["id"]

        before = depletion_entries_for(CONTROLLER_HEADERS, event_id=event_id)
        assert len(before) == 2, (
            "settlement writes one row per consumed lot, got %d" % (len(before),))
        first_before = _ledger_row(before, "EVENT", lot1_id)
        second_before = _ledger_row(before, "EVENT", lot2_id)
        assert_fields_equal(first_before, {"bottles": 6, "cogs_cents": 18000,
                                          "revenue_cents": 72000},
                            name="EVENT row for the first lot")
        assert_fields_equal(second_before, {"bottles": 2, "cogs_cents": 10000,
                                           "revenue_cents": 0},
                            name="EVENT row for the second lot")
        assert _entry(chain["entry"])["availability_state"] == "AVAILABLE"

        fx.void_event_settlement(
            chain["event"], "Event postponed after settlement was posted in error.")

        after = depletion_entries_for(CONTROLLER_HEADERS, event_id=event_id)
        assert len(after) == 4, (
            "the void appends one negating row per settlement row, got %d"
            % (len(after),))
        assert_entry_unchanged(first_before, _ledger_row(after, "EVENT", lot1_id),
                              name="EVENT row for the first lot")
        assert_entry_unchanged(second_before, _ledger_row(after, "EVENT", lot2_id),
                              name="EVENT row for the second lot")
        assert_fields_equal(_ledger_row(after, "REVERSAL", lot1_id),
                            {"bottles": -6, "cogs_cents": -18000,
                             "revenue_cents": -72000},
                            name="REVERSAL row for the first lot")
        assert_fields_equal(_ledger_row(after, "REVERSAL", lot2_id),
                            {"bottles": -2, "cogs_cents": -10000,
                             "revenue_cents": 0},
                            name="REVERSAL row for the second lot")
        for column in ("bottles", "cogs_cents", "revenue_cents"):
            assert_ledger_sums_to_zero(after, column)
        assert _entry(chain["entry"])["availability_state"] == "AVAILABLE"

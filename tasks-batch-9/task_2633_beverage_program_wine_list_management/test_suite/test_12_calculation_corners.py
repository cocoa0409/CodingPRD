"""Corner cases of the beverage program's arithmetic.

Every test in this file pins one derived number the PRD computes from stored
inputs: the par-level reorder quantity and its urgency flag, a list entry's
sales-contest score, a preservation slot's expiry instant, the pour-cost
report's half-open input window, and the three-way cost split a by-the-glass
closure posts to the ledger.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_decimal_equals, depletion_entries_for
from test_helpers.test_users import (
    BEVERAGE_DIRECTOR_HEADERS,
    CONTROLLER_HEADERS,
    sommelier_headers,
)

# The category cost-of-goods targets every recipe in this file uses; the RED
# target of 28.0 is what the pricing and contest arithmetic below is keyed on.
CATEGORY_TARGETS = {
    "SPARKLING": 30.0,
    "WHITE": 25.0,
    "ROSE": 28.0,
    "RED": 28.0,
    "DESSERT": 32.0,
    "FORTIFIED": 35.0,
}

LOT_RECEIVED_AT = "2026-08-10T00:00:00Z"


def _venue(**overrides):
    return fixtures.create_venue(cogs_target_pct_by_category=CATEGORY_TARGETS,
                                 **overrides)


def _wine(category="RED", reference_cost_cents=2400, **overrides):
    return fixtures.create_wine(category=category,
                                reference_cost_cents=reference_cost_cents,
                                bottle_size_ml=750, case_pack=6,
                                is_allocated=False, **overrides)


def _par_report(venue, headers=None, **params):
    response = api_client.get_par_report(
        venue["id"], headers or sommelier_headers(venue["id"]),
        params=params or None)
    return validate_success(response)


class TestParReportReorderRoundingAndUrgency:
    """Two entries at par 12 on a case pack of 6, one below the half-par
    ceiling and one exactly on it."""

    @staticmethod
    def _setup():
        fixtures.set_clock("2026-09-01T12:00:00Z")
        venue = _venue(priority_rank=1)
        bin_ = fixtures.create_bin(venue, bin_code="A1", zone="CELLAR",
                                   capacity_bottles=48,
                                   temperature_controlled=True)
        wine_a = _wine()
        wine_b = _wine()
        fixtures.create_lot(venue, wine_a, bin_, bottles_received=4,
                            unit_cost_cents=2400, received_at=LOT_RECEIVED_AT)
        fixtures.create_lot(venue, wine_b, bin_, bottles_received=6,
                            unit_cost_cents=2400, received_at=LOT_RECEIVED_AT)
        chain = fixtures.setup_draft_version(venue)
        entry_b = fixtures.add_entry(chain["version"], wine_b, venue,
                                     sort_rank=1, by_the_glass=False,
                                     par_bottles=12)
        entry_a = fixtures.add_entry(chain["version"], wine_a, venue,
                                     sort_rank=2, by_the_glass=False,
                                     par_bottles=12)
        fixtures.publish_version(chain["version"], venue)
        return venue, entry_a, entry_b

    def test_par_report_rounds_the_deficit_up_to_whole_cases(self):
        """A deficit of 8 bottles on a case pack of 6 reorders two whole cases,
        and the entry sitting exactly on the half-par ceiling is not urgent.

        "When the deficit is zero or negative, nothing is reordered; otherwise the reorder quantity is the deficit rounded up to a whole number of cases, that is, the deficit divided by the wine's `case_pack`, rounded up to a whole number of cases, and multiplied back by `case_pack`."

        Design: Corner/calculations/par_report_rounds_deficit_up_to_whole_cases_and_flags_urgent
        """
        venue, entry_a, entry_b = self._setup()

        report = _par_report(venue)
        assert report["venue_id"] == venue["id"]
        assert report["generated_at"].startswith("2026-09-01T12:00:00"), (
            "generated_at must be the logical clock, got %r"
            % (report["generated_at"],))
        assert report["line_count"] == 2, report
        assert report["urgent_line_count"] == 1, report

        lines = report["lines"]
        assert len(lines) == 2, lines
        by_entry = {line["list_entry_id"]: line for line in lines}

        line_a = by_entry[entry_a["id"]]
        assert line_a["par_bottles"] == 12
        assert line_a["bottles_on_hand"] == 4
        assert line_a["bottles_on_order"] == 0
        assert line_a["deficit_bottles"] == 8
        assert line_a["reorder_bottles"] == 12, (
            "a deficit of 8 must round UP to two cases of 6, never down to 6")
        assert line_a["is_urgent"] is True

        line_b = by_entry[entry_b["id"]]
        assert line_b["bottles_on_hand"] == 6
        assert line_b["bottles_on_order"] == 0
        assert line_b["deficit_bottles"] == 6
        assert line_b["reorder_bottles"] == 6
        assert line_b["is_urgent"] is False, (
            "6 on hand is exactly ceil(12 * 0.5), and the comparison is strict")

        assert lines[0]["list_entry_id"] == entry_a["id"], (
            "urgency descending must outrank sort_rank ascending")
        assert lines[1]["list_entry_id"] == entry_b["id"]

    def test_urgent_only_restricts_the_par_report_lines(self):
        """The urgent_only flag drops the non-urgent line from the array.

        "The optional `urgent_only` flag restricts the array to urgent lines, and `limit` and `offset` page it."

        Design: Corner/calculations/par_report_rounds_deficit_up_to_whole_cases_and_flags_urgent
        """
        venue, entry_a, entry_b = self._setup()

        report = _par_report(venue, urgent_only="true")
        lines = report["lines"]
        assert [line["list_entry_id"] for line in lines] == [entry_a["id"]], (
            "only the urgent line may survive urgent_only, got %r" % (lines,))
        assert lines[0]["is_urgent"] is True
        assert report["urgent_line_count"] == 1


class TestListEntryContestPoints:
    """The sales-contest score is a weighted sum whose margin term is clamped
    and rounded to four decimals before it is weighted."""

    @staticmethod
    def _setup(education_verified):
        fixtures.set_clock("2026-09-01T12:00:00Z")
        venue = _venue(priority_rank=1)
        bin_ = fixtures.create_bin(venue, bin_code="A1", zone="CELLAR",
                                   capacity_bottles=48,
                                   temperature_controlled=True)
        wine = _wine()
        lot = fixtures.create_lot(venue, wine, bin_, bottles_received=12,
                                  unit_cost_cents=2400,
                                  received_at=LOT_RECEIVED_AT)
        chain = fixtures.setup_draft_version(venue)
        entry = fixtures.add_entry(
            chain["version"], wine, venue, sort_rank=1, by_the_glass=True,
            pour_size_ml=177, par_bottles=6,
            education_verified=education_verified,
            tasting_note="Graphite, cassis, long finish.")
        assert entry["effective_pours"] == 3, entry
        assert entry["glass_price_cents"] == 2875, entry
        fixtures.publish_version(chain["version"], venue)
        slot = fixtures.open_slot(venue, entry, lot, slot_index=1,
                                  preservation_method="ARGON")
        return venue, entry, slot

    def test_contest_points_weight_pours_education_and_the_margin_factor(self):
        """Three glasses sold out of a 2400-cent bottle against a 28.0 target
        score 8.06 for an education-verified listing.

        "The score is then one point per pour sold, plus three points per bottle sold, plus five points when `education_verified` is true and nothing when it is false, plus ten points multiplied by the margin factor, with the total rounded half up to two decimals."

        Design: Corner/calculations/list_entry_contest_points_weighted_scoring_from_ledger
        """
        venue, entry, slot = self._setup(education_verified=True)

        before = validate_success(
            api_client.get_list_entry(entry["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_decimal_equals(before["contest_points"], 5.00,
                              "contest_points before any depletion row")

        fixtures.close_slot(slot, venue, pours_sold=3)

        rows = depletion_entries_for(BEVERAGE_DIRECTOR_HEADERS,
                                     btg_slot_id=slot["id"])
        sale = [row for row in rows if row["reason"] == "SALE_BTG"]
        assert len(sale) == 1, rows
        assert sale[0]["pours"] == 3
        assert sale[0]["cogs_cents"] == 2400
        assert sale[0]["revenue_cents"] == 8625

        after = validate_success(
            api_client.get_list_entry(entry["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_decimal_equals(after["contest_points"], 8.06, "contest_points")

    def test_the_education_term_is_a_flat_weight_not_a_multiplier(self):
        """The identical sale on a listing whose staff education is unverified
        scores exactly five points less.

        "When total revenue is greater than zero, express realised cost of goods as a percentage — total cost multiplied by 100, divided by total revenue, rounded half up to two decimals — then take the venue's category target for this wine, subtract the realised percentage from it, divide the difference by that same target, clamp the result to no less than 0.0 and no more than 1.0, and round half up to four decimals; that clamped figure is the margin factor."

        Design: Corner/calculations/list_entry_contest_points_weighted_scoring_from_ledger
        """
        venue, entry, slot = self._setup(education_verified=False)

        before = validate_success(
            api_client.get_list_entry(entry["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_decimal_equals(before["contest_points"], 0.00,
                              "contest_points before any depletion row")

        fixtures.close_slot(slot, venue, pours_sold=3)

        after = validate_success(
            api_client.get_list_entry(entry["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert_decimal_equals(after["contest_points"], 3.06, "contest_points")


class TestBtgPreservationExpiry:
    """Three bottles opened at the same instant on three rail positions expire
    at three different instants, because base hours and method factor multiply."""

    def test_preservation_expiry_multiplies_category_base_by_method_factor(self):
        """RED under vacuum lasts 96 hours, SPARKLING unprotected only 12, and
        FORTIFIED under argon 672 — below the cap, so it is not clipped.

        "Multiply base by factor, discard any fraction of an hour, and cap the result at 720 hours — thirty days — whichever is smaller."

        Design: Corner/calculations/btg_preservation_expiry_applies_category_and_method_constants
        """
        fixtures.set_clock("2026-09-01T12:00:00Z")
        venue = _venue(priority_rank=1)
        bin_ = fixtures.create_bin(venue, bin_code="A1", zone="CELLAR",
                                   capacity_bottles=48,
                                   temperature_controlled=True)
        wine_red = _wine(category="RED", reference_cost_cents=2400)
        wine_sparkling = _wine(category="SPARKLING", reference_cost_cents=4000)
        wine_fortified = _wine(category="FORTIFIED", reference_cost_cents=5000)
        lot_red = fixtures.create_lot(venue, wine_red, bin_, bottles_received=6,
                                      unit_cost_cents=2400,
                                      received_at=LOT_RECEIVED_AT)
        lot_sparkling = fixtures.create_lot(venue, wine_sparkling, bin_,
                                            bottles_received=6,
                                            unit_cost_cents=4000,
                                            received_at=LOT_RECEIVED_AT)
        lot_fortified = fixtures.create_lot(venue, wine_fortified, bin_,
                                            bottles_received=6,
                                            unit_cost_cents=5000,
                                            received_at=LOT_RECEIVED_AT)
        chain = fixtures.setup_draft_version(venue)
        entry_red = fixtures.add_entry(chain["version"], wine_red, venue,
                                       sort_rank=1, by_the_glass=True,
                                       pour_size_ml=177, par_bottles=6,
                                       education_verified=False)
        entry_sparkling = fixtures.add_entry(chain["version"], wine_sparkling,
                                             venue, sort_rank=2,
                                             by_the_glass=True,
                                             pour_size_ml=177, par_bottles=6,
                                             education_verified=False)
        entry_fortified = fixtures.add_entry(chain["version"], wine_fortified,
                                             venue, sort_rank=3,
                                             by_the_glass=True,
                                             pour_size_ml=177, par_bottles=6,
                                             education_verified=False)
        fixtures.publish_version(chain["version"], venue)

        slot_red = fixtures.open_slot(venue, entry_red, lot_red, slot_index=1,
                                      preservation_method="VACUUM")
        slot_sparkling = fixtures.open_slot(venue, entry_sparkling,
                                            lot_sparkling, slot_index=2,
                                            preservation_method="NONE")
        slot_fortified = fixtures.open_slot(venue, entry_fortified,
                                            lot_fortified, slot_index=3,
                                            preservation_method="ARGON")

        for slot in (slot_red, slot_sparkling, slot_fortified):
            assert slot["state"] == "OPEN", slot
            assert slot["opened_at"].startswith("2026-09-01T12:00:00"), slot
            assert slot["effective_pours"] == 3, (
                "effective_pours is copied from the entry and is independent of "
                "the preservation method: %r" % (slot,))

        assert slot_red["preservation_expires_at"].startswith(
            "2026-09-05T12:00:00"), slot_red
        assert slot_sparkling["preservation_expires_at"].startswith(
            "2026-09-02T00:00:00"), (
            "SPARKLING 24 h times NONE 0.5 is 12 h -- a factor below 1 must "
            "shorten the window: %r" % (slot_sparkling,))
        assert slot_fortified["preservation_expires_at"].startswith(
            "2026-09-29T12:00:00"), (
            "FORTIFIED 336 h times ARGON 2.0 is 672 h, below the 720-hour cap: "
            "%r" % (slot_fortified,))


class TestPourCostReportInputWindow:
    """The report's population is half-open on occurred_at, so one boundary
    second decides whether the second closure's rows are seen at all."""

    @staticmethod
    def _setup():
        fixtures.set_clock("2026-09-01T10:00:00Z")
        venue = _venue(priority_rank=1)
        bin_ = fixtures.create_bin(venue, bin_code="A1", zone="CELLAR",
                                   capacity_bottles=48,
                                   temperature_controlled=True)
        wine = _wine()
        lot = fixtures.create_lot(venue, wine, bin_, bottles_received=12,
                                  unit_cost_cents=2400,
                                  received_at=LOT_RECEIVED_AT)
        chain = fixtures.setup_draft_version(venue)
        entry = fixtures.add_entry(chain["version"], wine, venue, sort_rank=1,
                                   by_the_glass=True, pour_size_ml=177,
                                   par_bottles=6, education_verified=False)
        assert entry["effective_pours"] == 3, entry
        assert entry["glass_price_cents"] == 2875, entry
        fixtures.publish_version(chain["version"], venue)

        first = fixtures.open_slot(venue, entry, lot, slot_index=1,
                                   preservation_method="ARGON")
        fixtures.close_slot(first, venue, pours_sold=3)

        fixtures.set_clock("2026-09-01T14:00:00Z")
        second = fixtures.open_slot(venue, entry, lot, slot_index=2,
                                    preservation_method="ARGON")
        fixtures.close_slot(second, venue, pours_sold=2,
                            staff_education_pours=1)
        return venue

    @staticmethod
    def _report(venue, period_start, period_end):
        return validate_success(api_client.get_pour_cost_report(
            venue["id"], CONTROLLER_HEADERS,
            params={"period_start": period_start, "period_end": period_end}))

    def test_an_entry_stamped_at_period_end_is_excluded(self):
        """Reported over [10:00, 14:00) only the first closure's row counts, so
        actual and theoretical coincide and the variance is 0.00.

        "The window is half-open on the ledger's `occurred_at`: an entry counts when its `occurred_at` is at or after `period_start` and strictly before `period_end`."

        Design: Corner/calculations/pour_cost_report_input_set_honours_half_open_window_and_reason_filter
        """
        venue = self._setup()

        report = self._report(venue, "2026-09-01T10:00:00Z",
                              "2026-09-01T14:00:00Z")
        assert report["entry_count"] == 1, (
            "the rows stamped exactly at period_end must be excluded: %r"
            % (report,))
        assert report["actual_cogs_cents"] == 2400
        assert report["actual_revenue_cents"] == 8625
        assert_decimal_equals(report["actual_pour_cost_pct"], 27.83,
                              "actual_pour_cost_pct")
        assert_decimal_equals(report["theoretical_pour_cost_pct"], 27.83,
                              "theoretical_pour_cost_pct")
        assert_decimal_equals(report["variance_pct"], 0.00, "variance_pct")

    def test_one_extra_second_admits_the_education_row_to_actual_only(self):
        """Reported over [10:00, 14:00:01) the STAFF_EDUCATION row joins the
        actual population but not the theoretical one, opening a 5.56 gap.

        "The variance is then the theoretical percentage subtracted from the actual percentage and rounded half up to two decimals again — computed from the two **already-rounded** percentages, not from the raw ratios."

        Design: Corner/calculations/pour_cost_report_input_set_honours_half_open_window_and_reason_filter
        """
        venue = self._setup()

        report = self._report(venue, "2026-09-01T10:00:00Z",
                              "2026-09-01T14:00:01Z")
        assert report["entry_count"] == 3, report
        assert report["actual_cogs_cents"] == 4800
        assert report["actual_revenue_cents"] == 14375
        assert_decimal_equals(report["actual_pour_cost_pct"], 33.39,
                              "actual_pour_cost_pct")
        assert report["theoretical_cogs_cents"] == 4000, (
            "the 800-cent STAFF_EDUCATION row belongs to ACTUAL only: %r"
            % (report,))
        assert report["theoretical_revenue_cents"] == 14375
        assert_decimal_equals(report["theoretical_pour_cost_pct"], 27.83,
                              "theoretical_pour_cost_pct")
        assert_decimal_equals(report["variance_pct"], 5.56, "variance_pct")

    def test_the_report_never_writes_posture_or_variance(self):
        """Two report reads leave the venue's fiscal posture exactly as it was.

        "The same arithmetic is available as a read-only report to the director and the controller, which recomputes on demand from `period_start` and `period_end` and never touches posture, never opens an investigation and never writes anything."

        Design: Corner/calculations/pour_cost_report_input_set_honours_half_open_window_and_reason_filter
        """
        venue = self._setup()

        self._report(venue, "2026-09-01T10:00:00Z", "2026-09-01T14:00:00Z")
        self._report(venue, "2026-09-01T10:00:00Z", "2026-09-01T14:00:01Z")

        after = fixtures.get_venue(venue)
        assert after["program_posture"] == "OPEN", after
        assert_decimal_equals(after["last_variance_pct"], 0.00,
                              "last_variance_pct")
        assert after["last_pour_cost_run_at"] is None, after


class TestBtgCloseCostSplit:
    """A bottle cost that does not divide evenly by the pour count: the
    spoilage bucket has to absorb the drift."""

    def test_the_spoilage_bucket_absorbs_the_rounding_remainder(self):
        """A 2500-cent bottle over three pours posts 833 to the sale bucket and
        1667 to spoilage, so the two buckets sum to the whole bottle.

        "Rounding per pour happens first and the multiplication by the pour counts second, and the spoilage bucket absorbs the rounding drift, so the three bucket costs always sum to exactly the bottle cost."

        Design: Corner/calculations/btg_close_cost_split_spoilage_bucket_absorbs_rounding_remainder
        """
        fixtures.set_clock("2026-09-01T12:00:00Z")
        venue = _venue(priority_rank=1)
        bin_ = fixtures.create_bin(venue, bin_code="A1", zone="CELLAR",
                                   capacity_bottles=48,
                                   temperature_controlled=True)
        wine = _wine()
        lot = fixtures.create_lot(venue, wine, bin_, bottles_received=6,
                                  unit_cost_cents=2500,
                                  received_at=LOT_RECEIVED_AT)
        chain = fixtures.setup_draft_version(venue)
        entry = fixtures.add_entry(chain["version"], wine, venue, sort_rank=1,
                                   by_the_glass=True, pour_size_ml=177,
                                   par_bottles=6, education_verified=False)
        assert entry["effective_pours"] == 3, entry
        assert entry["glass_price_cents"] == 2875, entry
        fixtures.publish_version(chain["version"], venue)
        slot = fixtures.open_slot(venue, entry, lot, slot_index=1,
                                  preservation_method="ARGON")

        closed = fixtures.close_slot(slot, venue, pours_sold=1)
        assert closed["state"] == "CLOSED", closed
        assert closed["spoiled_pours"] == 2, closed
        assert closed["pours_sold"] == 1
        assert closed["staff_education_pours"] == 0

        rows = depletion_entries_for(BEVERAGE_DIRECTOR_HEADERS,
                                     btg_slot_id=slot["id"])
        assert [row["reason"] for row in rows] == ["SALE_BTG", "SPOILAGE"], (
            "the zero-count education bucket must produce no entry at all: %r"
            % (rows,))
        sale, spoilage = rows
        assert sale["bottles"] == 1
        assert sale["pours"] == 1
        assert sale["cogs_cents"] == 833, (
            "cost per pour is round_half_up(2500 / 3) == 833")
        assert sale["revenue_cents"] == 2875
        assert spoilage["bottles"] == 0
        assert spoilage["pours"] == 2
        assert spoilage["cogs_cents"] == 1667, (
            "spoilage takes the remainder 2500 - 833, not 2 * 833 == 1666")
        assert spoilage["revenue_cents"] == 0
        assert sale["cogs_cents"] + spoilage["cogs_cents"] == 2500

        after = fixtures.get_venue(venue)
        assert after["cogs_ledger_cents"] == 2500, after
        assert after["revenue_ledger_cents"] == 2875, after

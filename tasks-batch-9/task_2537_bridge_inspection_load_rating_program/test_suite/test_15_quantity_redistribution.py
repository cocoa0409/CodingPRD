"""
Redistributing an element's condition states conserves the physical quantities and
moves only the weighted scores.

PRD §3.2: "An inspector may redistribute quantities on an existing row while the
report is still `DRAFT`, resupplying `total_quantity`, the four condition-state
quantities and optionally `photo_count` and `defect_notes`; the row's four derived
values and the report's five rollups are recomputed."
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

FIELD_DAY = "2026-09-02T12:00:00Z"

# 100 units of deck area move from good to fair and 50 from poor to severe: the
# total and the poor-plus-severe subtotal are both unchanged.
REDISTRIBUTED = f.element_update_payload(
    1000,
    500,
    300,
    100,
    100,
    photo_count=7,
    defect_notes="Re-measured: half the poor deck area is full depth",
)


def _draft_report_with_a_redistributed_deck(client, roster, bridge):
    """The baseline four-row report whose deck row has been re-measured in place."""
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    before = draft["elements"]["deck"]
    after = validate_success(
        client.update_element_condition(
            before["id"], REDISTRIBUTED, roster.inspector_headers
        ),
        200,
    )
    return {"inspection": draft["inspection"], "before": before, "after": after}


def test_the_row_conserves_its_total_and_its_deficient_subtotal(client, roster, bridge):
    """
    Both conserved quantities survive the redistribution exactly: the row still
    inventories 1000 units and still reports 200 of them as poor or severe.

    PRD §3.2: "`reported_sum` is the total of the four condition-state quantities.
    `balanced` is true exactly when `reported_sum` equals `total_quantity`.
    `deficient_quantity` is the sum of the poor and severe quantities — that is,
    `cs3_qty` plus `cs4_qty`."

    Design: Difficulty/compensating_invariant/element_quantity_redistribution_preserves_total_units
    """
    setup = _draft_report_with_a_redistributed_deck(client, roster, bridge)

    a.assert_element_derived_fields(setup["before"], 1000, 600, 200, 150, 50)
    a.assert_element_derived_fields(setup["after"], 1000, 500, 300, 100, 100)

    assert setup["after"]["id"] == setup["before"]["id"]
    assert setup["after"]["total_quantity"] == setup["before"]["total_quantity"] == 1000
    assert setup["after"]["reported_sum"] == 1000
    assert setup["after"]["balanced"] is True
    assert setup["after"]["deficient_quantity"] == setup["before"]["deficient_quantity"]
    assert setup["after"]["deficient_quantity"] == 200


def test_the_weighted_index_of_the_row_falls_even_so(client, roster, bridge):
    """
    Conserving the quantities does not conserve the score, because the four
    condition states carry different weights: 100 units moved out of good and 50 out
    of poor cost the row four points.

    PRD §3.2: "`element_health_index` scores the element on a 0-to-100 scale:
    multiply the good quantity by a full weight of 1.00, the fair quantity by 0.80,
    the poor quantity by 0.40 and the severe quantity by 0.00, sum those four
    products, divide by `total_quantity`, multiply by 100, and round the result half
    up to two decimal places."
    PRD §3.2: "An element of total quantity 1000 reporting 600 good, 200 fair, 150
    poor and 50 severe therefore scores 82.00".

    Design: Difficulty/compensating_invariant/element_quantity_redistribution_preserves_total_units
    """
    setup = _draft_report_with_a_redistributed_deck(client, roster, bridge)

    assert setup["before"]["element_health_index"] == 82.00
    assert setup["after"]["element_health_index"] == 78.00
    a.assert_two_decimals(setup["after"]["element_health_index"], "element_health_index")
    assert setup["after"]["photo_count"] == 7


def test_the_report_rollups_are_byte_identical_across_the_redistribution(
    client, roster, bridge
):
    """
    Because the row's own totals were conserved, the report's inventory rollups do
    not move at all — 1308 units inventoried and 402 of them deficient, before and
    after.

    PRD §3.2: "Each element write also refreshes the parent report's rollup counters:
    `element_count` (the number of element rows), `reported_quantity_total` (the sum
    of `total_quantity` across rows), `deficient_quantity_total` (the sum of
    poor-plus-severe quantities across rows), `photo_count_total` (the sum of
    `photo_count` across rows), and `quantity_balanced`, which is true only when
    *every* row on the report is individually balanced."

    Design: Difficulty/compensating_invariant/element_quantity_redistribution_preserves_total_units
    """
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    before = fx.read_inspection(client, draft["inspection"]["id"])
    assert before["reported_quantity_total"] == 1308
    assert before["deficient_quantity_total"] == 402

    validate_success(
        client.update_element_condition(
            draft["elements"]["deck"]["id"], REDISTRIBUTED, roster.inspector_headers
        ),
        200,
    )

    after = fx.read_inspection(client, draft["inspection"]["id"])
    assert after["reported_quantity_total"] == before["reported_quantity_total"]
    assert after["deficient_quantity_total"] == before["deficient_quantity_total"]
    assert after["element_count"] == 4
    assert after["quantity_balanced"] is True
    assert after["photo_count_total"] == before["photo_count_total"] + 1


def test_submission_recomputes_the_health_index_from_the_new_distribution(
    client, roster, bridge
):
    """
    The report-level index is re-derived from the already-rounded row indices, so the
    four-point drop on the deck row moves the whole report's index and takes the deck
    component rating down one rung.

    PRD §3.3: "For a report carrying deck 82.00, girder 40.00, bearing 50.00 and
    abutment 95.00, the weights sum to 0.30 plus 0.25 plus 0.10 plus 0.10, which is
    0.75; the weighted scores sum to 24.60 plus 10.00 plus 5.00 plus 9.50, which is
    49.10; and 49.10 divided by 0.75 is 65.4666…, giving 65.47."
    PRD §3.3: "an index of at least 97 rates 9, at least 90 rates 8, at least 80
    rates 7, at least 70 rates 6, at least 60 rates 5, at least 45 rates 4, at least
    30 rates 3, at least 15 rates 2, at least 5 rates 1, and anything below 5 rates 0."

    Design: Difficulty/compensating_invariant/element_quantity_redistribution_preserves_total_units
    """
    setup = _draft_report_with_a_redistributed_deck(client, roster, bridge)
    fx.set_clock(client, FIELD_DAY)

    submitted = fx.submit_report(client, setup["inspection"]["id"], roster)

    assert submitted["deck_group_ehi"] == 78.00
    assert submitted["superstructure_group_ehi"] == 42.86
    assert submitted["substructure_group_ehi"] == 95.00
    assert submitted["bridge_health_index"] == 63.87
    assert submitted["computed_deck_rating"] == 6
    assert submitted["computed_superstructure_rating"] == 3
    assert submitted["computed_substructure_rating"] == 8
    a.assert_nbi_rating_from_index(submitted["computed_deck_rating"], 78.00)
    assert submitted["reported_quantity_total"] == 1308
    assert submitted["deficient_quantity_total"] == 402


def test_acceptance_publishes_the_changed_score_and_the_unchanged_quantities(
    client, roster, bridge
):
    """
    On the structure the two kinds of value part company: the deficiency percentage
    and the inventoried total are exactly what the original distribution would have
    published, while the health index and the deck rating are not.

    PRD §3.3: "Totals of 1000, 300, 4 and 4 against deficient quantities of 200, 200,
    2 and 0 give 100 times 402 divided by 1308, which is 30.7339…, rounded to 30.73."
    PRD §3.3: "The structure's `min_nbi_rating` is then recomputed as the smallest of
    the three component ratings, its `bridge_health_index` is copied from the
    report's, its `inventoried_quantity_total` is set to the sum of `total_quantity`
    across the report's element rows, its `deficiency_pct` is recomputed from that
    same data".

    Design: Difficulty/compensating_invariant/element_quantity_redistribution_preserves_total_units
    """
    setup = _draft_report_with_a_redistributed_deck(client, roster, bridge)
    fx.set_clock(client, FIELD_DAY)
    fx.submit_report(client, setup["inspection"]["id"], roster)
    fx.qa_claim(client, setup["inspection"]["id"], roster)
    fx.qa_decide(client, setup["inspection"]["id"], roster, "ACCEPT")

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["inventoried_quantity_total"] == 1308
    assert structure["deficiency_pct"] == 30.73
    assert structure["bridge_health_index"] == 63.87
    assert structure["deck_rating"] == 6
    assert structure["superstructure_rating"] == 3
    assert structure["substructure_rating"] == 8
    assert structure["min_nbi_rating"] == 3

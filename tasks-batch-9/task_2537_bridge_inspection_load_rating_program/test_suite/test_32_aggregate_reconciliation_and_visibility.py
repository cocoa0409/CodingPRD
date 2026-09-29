"""
Two questions about the same guarantee: no stored aggregate is allowed to drift from the
rows it summarises, before or after an edit, and no read is ever allowed to lag the write
that preceded it — including a read taken by another role.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import fhwa_reviewer_headers, permit_officer_headers

# The baseline four-row report, summed by hand: totals 1000 + 300 + 4 + 4, poor-plus-severe
# 200 + 200 + 2 + 0, photographs 6 + 8 + 4 + 1.
REPORTED_TOTAL = 1308
DEFICIENT_TOTAL = 402
PHOTO_TOTAL = 19

# The deck re-measured while the report is still DRAFT: the same 1000 units, 50 of them
# moved out of poor and into severe, so the deficient band is unchanged in size.
REMEASURED_DECK = f.element_update_payload(
    1000,
    500,
    300,
    100,
    100,
    photo_count=6,
    defect_notes="Re-measured: more CS2, more CS4",
)


def _sums_over(rows):
    """The four rollups recomputed from the element rows themselves."""
    return {
        "element_count": len(rows),
        "reported_quantity_total": sum(row["total_quantity"] for row in rows),
        "deficient_quantity_total": sum(row["deficient_quantity"] for row in rows),
        "photo_count_total": sum(row["photo_count"] for row in rows),
        "quantity_balanced": all(row["balanced"] for row in rows),
    }


def _assert_report_matches_its_rows(client, inspection_id):
    """Every rollup on the report equals the sum over the rows it summarises."""
    report = fx.read_inspection(client, inspection_id)
    listing = fx.elements_for_inspection(client, inspection_id)
    sums = _sums_over(listing["rows"])
    for field, value in sums.items():
        assert report[field] == value, (
            f"{field} drifted: report says {report[field]}, rows sum to {value}"
        )
    assert listing["meta"]["total_count"] == report["element_count"]
    return {"report": report, "rows": listing["rows"]}


def test_the_report_rollups_equal_the_sums_over_its_own_element_rows(
    client, roster, bridge
):
    """
    Four rows are written one at a time and the report's five rollups are not a separate
    story about them: each one is the arithmetic over the rows the listing returns.

    PRD §3.2: "Each element write also refreshes the parent report's rollup counters:
    `element_count` (the number of element rows), `reported_quantity_total` (the sum of
    `total_quantity` across rows), `deficient_quantity_total` (the sum of poor-plus-severe
    quantities across rows), `photo_count_total` (the sum of `photo_count` across rows),
    and `quantity_balanced`, which is true only when *every* row on the report is
    individually balanced."
    PRD §3.2: "`deficient_quantity` is the sum of the poor and severe quantities — that
    is, `cs3_qty` plus `cs4_qty`."

    Design: Corner/complexity_layers/inspection_aggregates_reconcile_with_their_element_rows
    """
    drafted = fx.draft_report_with_baseline(client, bridge["id"], roster)

    settled = _assert_report_matches_its_rows(client, drafted["inspection"]["id"])

    report = settled["report"]
    assert report["element_count"] == 4
    assert report["reported_quantity_total"] == REPORTED_TOTAL
    assert report["deficient_quantity_total"] == DEFICIENT_TOTAL
    assert report["photo_count_total"] == PHOTO_TOTAL
    assert report["quantity_balanced"] is True
    for row in settled["rows"]:
        a.assert_element_derived_fields(
            row,
            row["total_quantity"],
            row["cs1_qty"],
            row["cs2_qty"],
            row["cs3_qty"],
            row["cs4_qty"],
        )


def test_a_redistribution_inside_the_deficient_band_moves_the_index_but_no_total(
    client, roster, bridge
):
    """
    Fifty units of the deck move from poor to severe while the report is still a draft. The
    health index falls because the two states carry different weights, and every quantity
    aggregate holds still because both states are deficient — the aggregates and the index
    are reading the same rows for different purposes.

    PRD §3.2: "An inspector may redistribute quantities on an existing row while the report
    is still `DRAFT`, resupplying `total_quantity`, the four condition-state quantities and
    optionally `photo_count` and `defect_notes`; the row's four derived values and the
    report's five rollups are recomputed."
    PRD §3.2: "multiply the good quantity by a full weight of 1.00, the fair quantity by
    0.80, the poor quantity by 0.40 and the severe quantity by 0.00, sum those four
    products, divide by `total_quantity`, multiply by 100, and round the result half up to
    two decimal places."

    Design: Corner/complexity_layers/inspection_aggregates_reconcile_with_their_element_rows
    """
    drafted = fx.draft_report_with_baseline(client, bridge["id"], roster)
    inspection_id = drafted["inspection"]["id"]
    deck_id = drafted["elements"]["deck"]["id"]
    assert drafted["elements"]["deck"]["element_health_index"] == 82.00

    edited = validate_success(
        client.update_element_condition(
            deck_id, REMEASURED_DECK, roster.inspector_headers
        ),
        200,
    )

    assert edited["element_health_index"] == 78.00
    a.assert_two_decimals(edited["element_health_index"], "element_health_index")
    assert edited["deficient_quantity"] == 200
    assert edited["reported_sum"] == 1000
    assert edited["balanced"] is True

    settled = _assert_report_matches_its_rows(client, inspection_id)
    assert settled["report"]["element_count"] == 4
    assert settled["report"]["reported_quantity_total"] == REPORTED_TOTAL
    assert settled["report"]["deficient_quantity_total"] == DEFICIENT_TOTAL
    assert settled["report"]["photo_count_total"] == PHOTO_TOTAL


def test_the_inventory_the_acceptance_publishes_reconciles_with_the_edited_rows(
    client, roster, bridge
):
    """
    The structure's inventory figures are not an independent tally: they are the same row
    sums the report already carried, and the health index the structure now advertises is
    the renormalised average over the edited element indices.

    PRD §3.3: "Submission also computes the report's inventory totals in the same pass:
    `reported_quantity_total` as the sum of every row's `total_quantity`,
    `deficient_quantity_total` as the sum of every row's poor-plus-severe quantity, and the
    deficiency percentage as 100 times `deficient_quantity_total` divided by
    `reported_quantity_total`, rounded half up to two decimals, or 0.00 when the
    inventoried total is zero."
    PRD §3.3: "Totals of 1000, 300, 4 and 4 against deficient quantities of 200, 200, 2
    and 0 give 100 times 402 divided by 1308, which is 30.7339…, rounded to 30.73."
    PRD §3.3: "the report's own `bridge_health_index` is the weighted average over *all*
    element rows on the report, computed exactly the same way as a group index but with the
    weights renormalised across every reported element rather than within a group, and
    rounded half up to two decimals."

    Design: Corner/complexity_layers/inspection_aggregates_reconcile_with_their_element_rows
    """
    drafted = fx.draft_report_with_baseline(client, bridge["id"], roster)
    inspection_id = drafted["inspection"]["id"]
    validate_success(
        client.update_element_condition(
            drafted["elements"]["deck"]["id"],
            REMEASURED_DECK,
            roster.inspector_headers,
        ),
        200,
    )
    fx.set_clock(client, c.FIELD_DAY_CLOCK)
    submitted = fx.submit_report(client, inspection_id, roster)

    assert submitted["reported_quantity_total"] == REPORTED_TOTAL
    assert submitted["deficient_quantity_total"] == DEFICIENT_TOTAL
    assert submitted["quantity_balanced"] is True
    assert submitted["deck_group_ehi"] == 78.00
    assert submitted["bridge_health_index"] == 63.87

    fx.set_clock(client, c.QA_DAY_CLOCK)
    fx.qa_claim(client, inspection_id, roster)
    fx.qa_decide(client, inspection_id, roster, "ACCEPT")

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["inventoried_quantity_total"] == REPORTED_TOTAL
    assert structure["deficiency_pct"] == 30.73
    a.assert_two_decimals(structure["deficiency_pct"], "deficiency_pct")
    assert structure["bridge_health_index"] == 63.87
    assert structure["min_nbi_rating"] == 3
    _assert_report_matches_its_rows(client, inspection_id)


# ─── Nothing settles later: the next read already has it ────────────────────
def test_the_finalize_response_and_the_very_next_reads_already_agree(
    client, roster, bridge
):
    """
    A scour code of 2 is critical, and the finalisation answers with the settled record
    rather than an acknowledgement: the structure read taken immediately afterwards — by a
    role that took no part in the write — already carries the new status, the tightened
    cycle, the advanced counter and the failed compliance flag, on the first call.

    PRD §3.6: "a code of 3 or below is `SCOUR_CRITICAL`, a code from 4 through 6 is
    `LOW_RISK`, and a code of 7 or above is `STABILIZED`."
    PRD §3.6: "**Hop 2**, caused by hop 1, writes the evaluation's `derived_scour_status`
    through to the structure's `scour_status`, recomputes the structure's
    `inspection_interval_months` — where the new status is `SCOUR_CRITICAL` the scour
    ceiling applies and the interval becomes the smaller of its current value and 12
    months — and increments the structure's `version` by one."
    PRD §2.1: "Read access is broad: every retrieval and listing operation in the API is
    available to all seven roles."

    Design: Corner/consistency_model/every_write_is_visible_to_the_immediately_following_read
    """
    draft = fx.create_scour_evaluation(
        client,
        bridge["id"],
        roster,
        2,
        evaluation_method="DETAILED_HYDRAULIC",
        foundation_type="SPREAD_FOOTING",
        observed_scour_depth_m=2.8,
    )
    assert draft["status"] == "DRAFT"
    assert draft["derived_scour_status"] == "SCOUR_CRITICAL"
    assert fx.read_bridge(client, bridge["id"])["scour_status"] == "NOT_EVALUATED"

    finalized = fx.finalize_scour(client, draft["id"], roster)

    assert finalized["status"] == "FINAL"
    assert finalized["derived_scour_status"] == "SCOUR_CRITICAL"
    a.assert_instant_equals(finalized["finalized_at"], c.BASE_CLOCK, "finalized_at")

    first_read = validate_success(
        client.get_bridge(bridge["id"], fhwa_reviewer_headers()), 200
    )
    assert first_read["scour_status"] == "SCOUR_CRITICAL"
    assert first_read["inspection_interval_months"] == 12
    assert first_read["poa_compliant"] is False
    a.assert_version_advanced_by(
        first_read["version"], bridge["version"], 1, "bridge"
    )

    projection = validate_success(
        client.get_compliance_summary(bridge["id"], fhwa_reviewer_headers()), 200
    )
    assert projection["poa_compliant"] is False
    assert projection["inspection_interval_months"] == 12


def test_the_cascade_made_plan_is_listable_immediately_and_reads_identically_twice(
    client, roster, bridge
):
    """
    The plan the cascade inserted needs no settling either: the listing that is its only
    discovery channel returns it on the first call, in the state the cascade created it,
    and a second identical pair of reads — one of them by a third role — answers the same,
    because a read is never a step towards consistency here.

    PRD §3.6: "in that case a plan of action is created with `status` `REQUIRED`, its
    `bridge_id` and `scour_evaluation_id` copied from the evaluation being finalised."
    PRD §3.6: "Because plans of action are created by a cascade rather than by a client
    request, the plan list is the only way to discover that a plan now exists."
    PRD §3.6: "A plan created by the cascade starts at `REQUIRED` — the obligation exists
    but nothing has been committed."

    Design: Corner/consistency_model/every_write_is_visible_to_the_immediately_following_read
    """
    draft = fx.create_scour_evaluation(
        client,
        bridge["id"],
        roster,
        2,
        evaluation_method="DETAILED_HYDRAULIC",
        foundation_type="SPREAD_FOOTING",
        observed_scour_depth_m=2.8,
    )
    assert fx.plans_for_bridge(client, bridge["id"]) == []

    fx.finalize_scour(client, draft["id"], roster)

    plans = fx.plans_for_bridge(client, bridge["id"])
    assert len(plans) == 1, f"one plan on the first listing, got {len(plans)}"
    plan = plans[0]
    assert plan["status"] == "REQUIRED"
    assert plan["bridge_id"] == bridge["id"]
    assert plan["scour_evaluation_id"] == draft["id"]
    assert plan["monitoring_frequency_months"] is None
    assert plan["closure_trigger_stage_m"] is None
    assert plan["revision_count"] == 0
    assert plan["submitted_at"] is None
    assert plan["approved_at"] is None
    assert plan["approved_by_id"] is None

    assert fx.read_plan(client, plan["id"]) == plan
    assert fx.plans_for_bridge(client, bridge["id"]) == plans
    assert (
        validate_success(client.get_bridge(bridge["id"], permit_officer_headers()), 200)
        == validate_success(client.get_bridge(bridge["id"], fhwa_reviewer_headers()), 200)
    )
    assert fx.read_scour(client, draft["id"])["status"] == "FINAL"

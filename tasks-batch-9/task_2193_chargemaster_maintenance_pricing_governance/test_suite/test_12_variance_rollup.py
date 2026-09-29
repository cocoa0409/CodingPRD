"""Batch reconciliation roll-up: per-line rounding first, then the mean."""
from test_helpers import (
    api_client, get_success_data,
    setup_variance_batch_scenario,
    reconcile_batch, read_batch,
    ANALYST,
)


def _line(line_id):
    return get_success_data(api_client.get_captured_charge(line_id, ANALYST))


def test_each_line_variance_is_rounded_before_the_batch_mean_is_taken():
    """PRD §3.9: "Otherwise `expected_charge_cents` is computed as the resolved item's
    `gross_charge_cents` multiplied by the line's `quantity`, and `line_variance_bp` as the
    posted charge less the expected charge, multiplied by 10000, divided by the expected
    charge, rounded half up."
    PRD §3.9: "Otherwise `mean_line_variance_bp` is the sum of the scored lines'
    already-rounded `line_variance_bp` values divided by the count of scored lines, rounded
    half up to whole basis points."
    PRD §2.6: "Wherever a basis-point factor is applied, the product is divided by 10000 and
    the result is rounded to the nearest whole cent using **round half up**, meaning a value
    exactly halfway between two integers rounds away from zero."

    Design: Difficulty/combinatorial_formula/combinatorial_formula__mode_b_round_per_line_then_average_variance_rollup
    """
    s = setup_variance_batch_scenario()
    reconcile_batch(s["batch"]["id"])

    l1 = _line(s["l1"]["id"])
    assert l1["expected_charge_cents"] == 128000
    assert l1["line_variance_bp"] == 195, (
        f"2500 * 10000 / 128000 = 195.3125 rounds to 195, got {l1['line_variance_bp']}"
    )

    l2 = _line(s["l2"]["id"])
    assert l2["expected_charge_cents"] == 128000
    assert l2["line_variance_bp"] == -234, (
        f"-3000 * 10000 / 128000 = -234.375 rounds to -234, got {l2['line_variance_bp']}"
    )

    l3 = _line(s["l3"]["id"])
    assert l3["expected_charge_cents"] == 6400000, (
        "expected charge multiplies the item's gross charge by the line quantity"
    )
    assert l3["line_variance_bp"] == 0

    l4 = _line(s["l4"]["id"])
    assert l4["expected_charge_cents"] == 256000
    assert l4["line_variance_bp"] == 5

    batch = read_batch(s["batch"]["id"])
    assert batch["mean_line_variance_bp"] == -9, (
        "195 - 234 + 0 + 5 = -34 over four scored lines is -8.5, which rounds away from "
        f"zero to -9, got {batch['mean_line_variance_bp']}"
    )
    assert batch["mean_line_variance_bp"] != -1, (
        "-1 is the forbidden aggregate-then-round answer"
    )
    assert batch["total_expected_charge_cents"] == 6912000
    assert batch["total_posted_charge_cents"] == 6988628


def test_reconcile_classifies_the_unknown_code_line_and_rolls_up_the_counters():
    """PRD §3.9: "If `submitted_cdm_number` matches no `ChargeItem`'s `cdm_number` within the
    batch's facility, `charge_item_id` stays null and `match_status` becomes `UNKNOWN_CODE`."
    PRD §3.9: "The boundary is exact: an absolute variance of exactly 100 basis points is
    `MATCHED`, and 101 is `PRICE_VARIANCE`."
    PRD §3.9: "`matched_line_count` is the count of `MATCHED` lines and
    `exception_line_count` the count of lines whose `match_status` is `PRICE_VARIANCE`,
    `UNKNOWN_CODE`, `INACTIVE_ITEM` or `DUPLICATE_LINE`."
    PRD §3.9: "Both set `status` to `RECONCILING`, increase `reconcile_pass_count` by 1,
    advance the batch's `version` by 1, and re-execute the complete set of line-level and
    finding-level side effects described below."

    Design: Difficulty/combinatorial_formula/combinatorial_formula__mode_b_round_per_line_then_average_variance_rollup
    """
    s = setup_variance_batch_scenario()
    reconcile_batch(s["batch"]["id"])

    assert _line(s["l1"]["id"])["match_status"] == "PRICE_VARIANCE"
    assert _line(s["l2"]["id"])["match_status"] == "PRICE_VARIANCE"
    assert _line(s["l3"]["id"])["match_status"] == "MATCHED"
    assert _line(s["l4"]["id"])["match_status"] == "MATCHED", (
        "a variance of 5 bp is well inside the 100 bp tolerance"
    )

    l5 = _line(s["l5"]["id"])
    assert l5["match_status"] == "UNKNOWN_CODE"
    assert l5["charge_item_id"] is None
    assert l5["expected_charge_cents"] is None
    assert l5["line_variance_bp"] is None

    batch = read_batch(s["batch"]["id"])
    assert batch["status"] == "RECONCILING"
    assert batch["reconcile_pass_count"] == 1
    assert batch["line_count"] == 5
    assert batch["matched_line_count"] == 2
    assert batch["exception_line_count"] == 3
    assert batch["open_finding_count"] == 0, (
        "CDM-3000 carries no companion_required_item_id, so nothing is missing"
    )

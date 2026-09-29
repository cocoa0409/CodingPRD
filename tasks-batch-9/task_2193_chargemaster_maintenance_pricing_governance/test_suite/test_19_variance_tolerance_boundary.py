"""The +/-100 basis-point reconciliation tolerance, approached from both sides."""
from test_helpers import (
    api_client, get_success_data,
    setup_variance_tolerance_scenario,
    reconcile_batch, read_batch, read_item, read_facility,
    ANALYST,
)


def _line(line_id):
    return get_success_data(api_client.get_captured_charge(line_id, ANALYST))


def test_an_absolute_variance_of_exactly_one_hundred_basis_points_is_still_matched():
    """PRD §3.9: "Otherwise `expected_charge_cents` is computed as the resolved item's
    `gross_charge_cents` multiplied by the line's `quantity`, and `line_variance_bp` as the
    posted charge less the expected charge, multiplied by 10000, divided by the expected
    charge, rounded half up."
    PRD §3.9: "If the absolute value of `line_variance_bp` is greater than 100 basis points
    — that is, more than one percent away from expected — `match_status` becomes
    `PRICE_VARIANCE`. The boundary is exact: an absolute variance of exactly 100 basis points
    is `MATCHED`, and 101 is `PRICE_VARIANCE`."
    PRD §2.6: "Basis-point outputs — the facility's aggregate markup ratio, a change request's
    projected markup ratio, a captured line's variance, a batch's mean variance — are likewise
    whole integers produced by a round-half-up on the final division."

    Design: Difficulty/boundary_precision_check/boundary_precision_check__line_variance_bp_exactly_at_tolerance_100_on_reconcile
    """
    s = setup_variance_tolerance_scenario()
    assert read_item(s["item"]["id"])["gross_charge_cents"] == 1000000, (
        "the flat fee of 1000000 cents survives both the medicare floor of 120 and the "
        "market cap of 11000000, so every line's expected charge is exactly 1000000"
    )

    reconcile_batch(s["batch"]["id"])

    on_pos = _line(s["on_pos"]["id"])
    assert on_pos["expected_charge_cents"] == 1000000
    assert on_pos["line_variance_bp"] == 100
    assert on_pos["match_status"] == "MATCHED", (
        "exactly +100 bp sits on the tolerance and is not greater than it"
    )

    eps_below = _line(s["eps_below"]["id"])
    assert eps_below["line_variance_bp"] == 100, (
        "10049 over 1000000 is 100.49 bp, which rounds half up to 100: got "
        f"{eps_below['line_variance_bp']}"
    )
    assert eps_below["match_status"] == "MATCHED"

    eps_above = _line(s["eps_above"]["id"])
    assert eps_above["line_variance_bp"] == 101, (
        "10050 over 1000000 is 100.5 bp, and a value exactly halfway between two integers "
        f"rounds away from zero to 101: got {eps_above['line_variance_bp']}"
    )
    assert eps_above["match_status"] == "PRICE_VARIANCE"


def test_the_negative_side_of_the_tolerance_splits_at_the_same_two_points():
    """PRD §3.9: "The boundary is exact: an absolute variance of exactly 100 basis points is
    `MATCHED`, and 101 is `PRICE_VARIANCE`."
    PRD §3.9: "`matched_line_count` is the count of `MATCHED` lines and
    `exception_line_count` the count of lines whose `match_status` is `PRICE_VARIANCE`,
    `UNKNOWN_CODE`, `INACTIVE_ITEM` or `DUPLICATE_LINE`."
    PRD §3.9: "Otherwise `mean_line_variance_bp` is the sum of the scored lines'
    already-rounded `line_variance_bp` values divided by the count of scored lines, rounded
    half up to whole basis points."
    PRD §3.9: "Alongside the mean, `total_expected_charge_cents` is the sum of
    `expected_charge_cents` over every line whose `match_status` is not `UNKNOWN_CODE`, and
    `total_posted_charge_cents` is the sum of `posted_charge_cents` over **all** lines in the
    batch including the unknown-code and duplicate ones."

    Design: Difficulty/boundary_precision_check/boundary_precision_check__line_variance_bp_exactly_at_tolerance_100_on_reconcile
    """
    s = setup_variance_tolerance_scenario()
    reconcile_batch(s["batch"]["id"])

    on_neg = _line(s["on_neg"]["id"])
    assert on_neg["line_variance_bp"] == -100
    assert on_neg["match_status"] == "MATCHED", (
        "the tolerance is on the absolute value, so -100 bp is inside it just as +100 is"
    )

    eps_below_neg = _line(s["eps_below_neg"]["id"])
    assert eps_below_neg["line_variance_bp"] == -101, (
        "-10050 over 1000000 is -100.5 bp, and half rounds away from zero to -101: got "
        f"{eps_below_neg['line_variance_bp']}"
    )
    assert eps_below_neg["match_status"] == "PRICE_VARIANCE"

    batch = read_batch(s["batch"]["id"])
    assert batch["status"] == "RECONCILING"
    assert batch["line_count"] == 5
    assert batch["matched_line_count"] == 3, (
        "+100, -100 and the two roundings that land on 100 give three matched lines"
    )
    assert batch["exception_line_count"] == 2
    assert batch["mean_line_variance_bp"] == 20, (
        "100 + 100 + 101 - 100 - 101 is 100 over five scored lines: got "
        f"{batch['mean_line_variance_bp']}"
    )
    assert batch["total_expected_charge_cents"] == 5000000
    assert batch["total_posted_charge_cents"] == 5010049
    assert read_facility(s["facility"]["id"])["active_item_count"] == 1

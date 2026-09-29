"""The pinned per-line-item rounding order on a withheld claim."""
from test_helpers import (
    PROGRAM_ADMIN_1,
    PROGRAM_ADMIN_HEADERS,
    api_client,
    assert_two_decimals,
    claim_line_item,
    file_claim,
    open_claim_review,
    run_repair_cycle,
    set_clock,
    setup_accepted_report,
    setup_station,
    validate_success,
)


def _claim_of_three_equal_line_items_in_review():
    """A 96.67 % report with three line items of 1005 cents each, in REVIEW."""
    scenario = setup_station(
        clock="2026-05-01T00:00:00Z",
        site_code="HS-WH-1",
        station_code="ST-WH-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
    )
    port_id = scenario["ports"][0]["id"]

    set_clock("2026-06-05T02:00:00Z")
    run_repair_cycle(
        port_id,
        detected_at="2026-06-05T00:00:00Z",
        window_start_at="2026-06-05T01:00:00Z",
        window_end_at="2026-06-05T23:00:00Z",
        completed_at="2026-06-06T00:00:00Z",
        fault_class="MINOR",
        fault_code="OCPP-COMM-07",
    )

    set_clock("2026-07-15T00:00:00Z")
    report = setup_accepted_report(
        scenario["station"]["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
    )
    claim = file_claim(
        report["id"],
        [claim_line_item(port_id, 1005) for _ in range(3)],
        report["version"],
    )
    claim = open_claim_review(claim["id"])
    return report, claim


def test_review_snapshots_the_effective_uptime_and_the_matching_withhold_tier():
    """Entering review pins the tier the money will be computed against.

    PRD §3.8: "`withhold_rate` is selected from `effective_uptime_pct` by walking
    the tiers from the top with an inclusive comparison at each step: an
    effective figure of at least 97.00 withholds nothing (a rate of `0.00`);
    otherwise at least 95.00 withholds a tenth (`0.10`)".

    Design: Difficulty/combinatorial_formula/claim_withhold_mode_b_rounds_each_line_item_before_summing
    """
    report, claim = _claim_of_three_equal_line_items_in_review()

    assert float(report["uptime_pct"]) == 96.67, (
        "100 * (43200 - 1440) / 43200 must round to 96.67, got " f"{report['uptime_pct']}"
    )
    assert claim["state"] == "REVIEW"
    assert claim["requested_amount_cents"] == 3015, "the exact integer sum of three 1005s"
    assert_two_decimals(claim["effective_uptime_pct"], "effective_uptime_pct")
    assert float(claim["effective_uptime_pct"]) == 96.67, (
        "with no remediation credit the effective figure equals the report figure"
    )
    assert float(claim["withhold_rate"]) == 0.10, (
        "96.67 sits below 97.00 and at or above 95.00, so a tenth is withheld, got "
        f"{claim['withhold_rate']}"
    )


def test_withhold_rounds_each_line_item_before_summing_them():
    """Per-item rounding gives 303 cents where sum-then-round would give 302.

    PRD §3.8: "Rounding per item before summation is the rule; summing first and
    rounding once is explicitly *not* the rule, and the two give different cent
    totals — three line items of 1005 cents each at a tenth withhold give 303
    cents per item, where sum-then-round would give 302."

    Design: Difficulty/combinatorial_formula/claim_withhold_mode_b_rounds_each_line_item_before_summing
    """
    _, claim = _claim_of_three_equal_line_items_in_review()

    data = validate_success(
        api_client.decide_reimbursement_claim(claim["id"], "WITHHOLD", PROGRAM_ADMIN_HEADERS)
    )

    assert data["state"] == "WITHHELD"
    assert data["withheld_amount_cents"] == 303, (
        "each 1005 at 0.10 rounds half up to 101, three of them give 303, got "
        f"{data['withheld_amount_cents']}"
    )
    assert data["withheld_amount_cents"] != 302, (
        "302 is the forbidden sum-then-round result"
    )
    assert data["approved_amount_cents"] == 2712, (
        "requested 3015 less withheld 303, got " f"{data['approved_amount_cents']}"
    )
    assert data["decided_by_user_id"] == PROGRAM_ADMIN_1

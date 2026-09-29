"""The withhold ladder at its top boundary, and the credit that reaches it."""
from test_helpers import (
    PROGRAM_ADMIN_1,
    PROGRAM_ADMIN_HEADERS,
    OPERATOR_HEADERS,
    api_client,
    claim_line_item,
    file_claim,
    open_claim_review,
    read_claim,
    read_uptime_report,
    run_repair_cycle,
    set_clock,
    setup_accepted_report,
    setup_station,
    validate_success,
)


def _station_with_one_cleared_minor_fault(cleared_at: str, window_end_at: str):
    """An OPERATIONAL station whose single dispenser carries exactly one closed
    MINOR fault inside June 2026."""
    scenario = setup_station(
        clock="2026-05-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        stop_at="OPERATIONAL",
    )
    port_id = scenario["ports"][0]["id"]

    set_clock("2026-06-10T00:00:00Z")
    run_repair_cycle(
        port_id,
        detected_at="2026-06-10T00:00:00Z",
        window_start_at="2026-06-10T01:00:00Z",
        window_end_at=window_end_at,
        completed_at=cleared_at,
        fault_class="MINOR",
        fault_code="OCPP-MIN-01",
    )

    set_clock("2026-07-15T00:00:00Z")
    return scenario["station"]["id"], port_id


def test_an_uptime_of_exactly_ninety_seven_percent_withholds_nothing_and_approves():
    """An exclusive tier comparison drops to 0.10 and rejects the approval outright.

    PRD §3.8: "`withhold_rate` is selected from `effective_uptime_pct` by walking
    the tiers from the top with an inclusive comparison at each step: an effective
    figure of at least 97.00 withholds nothing (a rate of `0.00`); otherwise at
    least 95.00 withholds a tenth (`0.10`); otherwise at least 90.00 withholds a
    quarter (`0.25`); and anything below 90.00 withholds the whole claim (`1.00`)."
    And: "`APPROVE` requires the snapshotted `withhold_rate` to be exactly `0.00`,
    that is an `effective_uptime_pct` of at least 97.00.  Anything else is rejected
    with `ERR_UPTIME_BELOW_APPROVAL_THRESHOLD`.  It moves the claim `REVIEW →
    APPROVED`, sets `withheld_amount_cents` to zero and `approved_amount_cents` to
    `requested_amount_cents`."

    Design: Corner/calculations/withhold_tier_selection_is_inclusive_at_exactly_ninety_seven_percent
    """
    station_id, port_id = _station_with_one_cleared_minor_fault(
        cleared_at="2026-06-10T21:36:00Z", window_end_at="2026-06-11T00:00:00Z"
    )

    report = setup_accepted_report(
        station_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
    )
    assert report["billable_downtime_minutes"] == 1296, (
        "midnight to 21:36 is 1296 whole minutes, all of them inside June"
    )
    assert report["total_port_minutes"] == 43200
    assert report["excluded_minutes"] == 0
    assert float(report["uptime_pct"]) == 97.00
    assert report["methodology"] == "FINAL"

    claim = file_claim(
        report["id"],
        [
            claim_line_item(port_id, 1005, "OANDM"),
            claim_line_item(port_id, 1005, "NETWORK_FEES"),
            claim_line_item(port_id, 1005, "PARTS"),
        ],
        report["version"],
    )
    assert claim["requested_amount_cents"] == 3015

    reviewed = open_claim_review(claim["id"])
    assert reviewed["state"] == "REVIEW"
    assert float(reviewed["effective_uptime_pct"]) == 97.00
    assert float(reviewed["withhold_rate"]) == 0.00, "97.00 sits inside the top tier"

    data = validate_success(
        api_client.decide_reimbursement_claim(claim["id"], "APPROVE", PROGRAM_ADMIN_HEADERS)
    )

    assert data["state"] == "APPROVED"
    assert data["withheld_amount_cents"] == 0
    assert data["approved_amount_cents"] == 3015
    assert data["decided_by_user_id"] == PROGRAM_ADMIN_1


def test_a_remediation_credit_re_tiers_the_claim_without_touching_the_report():
    """Re-tiering against the report's own uptime leaves the claim stuck at 0.10.

    PRD §3.8: "`effective_uptime_pct` is the report's `uptime_pct` plus that credit,
    rounded half up to two decimal places, and then capped at 100.00 — the credit
    can never carry a station past perfect uptime."  And: "A `NetworkOperator` may
    file a remediation against it, supplying a `remediation_credit_pp` in percentage
    points of uptime credit, which moves the claim `WITHHELD → REVIEW`, writes that
    credit onto the claim, and re-runs the snapshot — recomputing
    `effective_uptime_pct` (still capped at 100.00) and re-selecting `withhold_rate`
    from the tiers."  PRD §3.8 also pins the money either side: on a withhold the
    server walks "the `line_items` in the order they were supplied at filing,
    multiplying each entry's `amount_cents` by the snapshotted `withhold_rate`,
    rounding **each product** half up to a whole cent, and summing those rounded
    per-item withholds", while `APPROVE` "sets `withheld_amount_cents` to zero and
    `approved_amount_cents` to `requested_amount_cents`".

    Design: Corner/calculations/remediation_credit_lifts_effective_uptime_across_the_ninety_seven_tier
    """
    station_id, port_id = _station_with_one_cleared_minor_fault(
        cleared_at="2026-06-11T00:00:00Z", window_end_at="2026-06-11T12:00:00Z"
    )

    report = setup_accepted_report(
        station_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
    )
    assert report["billable_downtime_minutes"] == 1440
    assert float(report["uptime_pct"]) == 96.67

    claim = file_claim(
        report["id"],
        [
            claim_line_item(port_id, 2000, "OANDM"),
            claim_line_item(port_id, 1000, "NETWORK_FEES"),
        ],
        report["version"],
    )
    open_claim_review(claim["id"])
    withheld = validate_success(
        api_client.decide_reimbursement_claim(claim["id"], "WITHHOLD", PROGRAM_ADMIN_HEADERS)
    )

    assert withheld["state"] == "WITHHELD"
    assert float(withheld["effective_uptime_pct"]) == 96.67
    assert float(withheld["withhold_rate"]) == 0.10
    assert withheld["withheld_amount_cents"] == 300
    assert withheld["approved_amount_cents"] == 2700

    remediated = validate_success(
        api_client.file_claim_remediation(claim["id"], 0.33, OPERATOR_HEADERS)
    )

    assert remediated["state"] == "REVIEW"
    assert float(remediated["remediation_credit_pp"]) == 0.33
    assert float(remediated["effective_uptime_pct"]) == 97.00, (
        "96.67 plus 0.33 percentage points lands exactly on the top tier"
    )
    assert float(remediated["withhold_rate"]) == 0.00

    approved = validate_success(
        api_client.decide_reimbursement_claim(claim["id"], "APPROVE", PROGRAM_ADMIN_HEADERS)
    )

    assert approved["state"] == "APPROVED"
    assert approved["withheld_amount_cents"] == 0
    assert approved["approved_amount_cents"] == 3000
    assert approved["requested_amount_cents"] == 3000
    assert read_claim(claim["id"])["state"] == "APPROVED"

    report_after = read_uptime_report(report["id"])
    assert float(report_after["uptime_pct"]) == 96.67, "the credit never writes back"
    assert report_after["state"] == "ACCEPTED"

"""Opening a claim for adjudication is decided by the parent report's state."""
from test_helpers import (
    PROGRAM_ADMIN_HEADERS,
    ApiErrorId,
    api_client,
    claim_line_item,
    file_claim,
    program_review,
    read_claim,
    read_uptime_report,
    set_clock,
    setup_station,
    setup_submitted_report,
    validate_error,
    validate_success,
)


def _pending_claim_against_a_merely_submitted_report():
    """A perfect 100.00 report parked in SUBMITTED, carrying one 5000-cent claim."""
    scenario = setup_station(
        clock="2026-05-01T00:00:00Z",
        site_code="HS-XD-2",
        station_code="ST-XD-2",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
    )
    set_clock("2026-07-15T00:00:00Z")
    report = setup_submitted_report(
        scenario["station"]["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
    )
    claim = file_claim(
        report["id"],
        [claim_line_item(scenario["ports"][0]["id"], 5000)],
        report["version"],
    )
    return report, claim


def test_a_submitted_report_blocks_the_claim_from_entering_review():
    """The claim may be filed against a submitted report but not adjudicated.

    PRD §3.8: "A `ProgramAdministrator` opens the claim for adjudication, moving it
    `PENDING → REVIEW` ... The report must be in `ACCEPTED`, or the request is
    rejected with `ERR_UPTIME_REPORT_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/claim_review_blocked_until_uptime_report_reaches_accepted
    """
    _report, claim = _pending_claim_against_a_merely_submitted_report()

    response = api_client.review_reimbursement_claim(claim["id"], PROGRAM_ADMIN_HEADERS)

    validate_error(response, ApiErrorId.ERR_UPTIME_REPORT_NOT_ACCEPTED, 409)

    blocked = read_claim(claim["id"])
    assert blocked["state"] == "PENDING"
    assert blocked["effective_uptime_pct"] is None, (
        "the snapshot must not be taken by a rejected review"
    )
    assert blocked["withhold_rate"] is None


def test_accepting_the_report_unblocks_review_and_snapshots_the_top_tier():
    """Only the parent report moves, and the identical review call then succeeds.

    PRD §3.8: "`effective_uptime_pct` is the report's `uptime_pct` plus that credit
    ... `withhold_rate` is selected from `effective_uptime_pct` by walking the
    tiers from the top with an inclusive comparison at each step: an effective
    figure of at least 97.00 withholds nothing (a rate of `0.00`)".

    Design: Difficulty/cross_entity_state_dependency/claim_review_blocked_until_uptime_report_reaches_accepted
    """
    report, claim = _pending_claim_against_a_merely_submitted_report()

    api_client.review_reimbursement_claim(claim["id"], PROGRAM_ADMIN_HEADERS)

    program_review(report["id"], "ACCEPT")
    accepted = read_uptime_report(report["id"])
    assert accepted["state"] == "ACCEPTED"
    assert float(accepted["uptime_pct"]) == 100.00, (
        "the station carried no outage at all across the period"
    )

    data = validate_success(
        api_client.review_reimbursement_claim(claim["id"], PROGRAM_ADMIN_HEADERS)
    )

    assert data["state"] == "REVIEW"
    assert float(data["effective_uptime_pct"]) == 100.00
    assert float(data["withhold_rate"]) == 0.00
    assert data["requested_amount_cents"] == 5000, (
        "neither review attempt may disturb the exact integer sum of the line items"
    )

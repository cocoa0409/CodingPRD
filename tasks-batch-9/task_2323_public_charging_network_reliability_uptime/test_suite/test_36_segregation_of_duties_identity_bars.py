"""Both independence bars follow the person, not the role."""
from test_helpers import (
    AUDITOR_1,
    OPERATOR_1,
    PROGRAM_ADMIN_1,
    PROGRAM_ADMIN_2,
    UNKNOWN_USER,
    ApiErrorId,
    api_client,
    claim_line_item,
    file_claim,
    make_compliance_auditor_headers,
    make_program_administrator_headers,
    open_claim_review,
    read_claim,
    read_outage_event,
    read_station,
    read_uptime_report,
    run_repair_cycle,
    set_clock,
    setup_accepted_report,
    setup_station,
    validate_error,
    validate_success,
)


def test_the_operator_who_raised_the_dispatch_cannot_verify_its_outage():
    """A role-only check lets the dispatch's own author sign off on the repair.

    PRD §2.8, SoD-1: "When a `NetworkOperator` creates a maintenance dispatch,
    their `X-User-ID` is copied onto the outage as `dispatch_created_by_user_id`.
    A `ComplianceAuditor` verifying that outage's resolution must present an
    `X-User-ID` different from that recorded value."  PRD §3.4: "An `outcome` of
    `VERIFY`, available to a `ComplianceAuditor`, closes the outage `RESOLVED →
    VERIFIED` — the terminal state of this dimension — and is subject to SoD-1:
    the reviewer's `X-User-ID` must differ from the outage's
    `dispatch_created_by_user_id`."

    Design: Corner/validations/dispatch_creator_cannot_verify_the_resolution_of_the_same_outage
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        stop_at="OPERATIONAL",
    )
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    cycle = run_repair_cycle(
        port_id,
        detected_at="2026-08-01T00:00:00Z",
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T23:00:00Z",
        completed_at="2026-08-01T06:00:00Z",
        fault_class="MINOR",
        fault_code="OCPP-MIN-01",
        operator_user_id=OPERATOR_1,
    )
    outage_id = cycle["outage"]["id"]

    resolved = read_outage_event(outage_id)
    assert resolved["state"] == "RESOLVED"
    assert resolved["dispatch_created_by_user_id"] == OPERATOR_1
    assert read_station(station_id)["billable_downtime_minutes_lifetime"] == 360

    response = api_client.submit_resolution_review(
        outage_id, {"outcome": "VERIFY"}, make_compliance_auditor_headers(OPERATOR_1)
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

    after_refusal = read_outage_event(outage_id)
    assert after_refusal["state"] == "RESOLVED", "a second reviewer must still be able to verify"
    assert after_refusal["dispatch_created_by_user_id"] == OPERATOR_1
    assert read_station(station_id)["billable_downtime_minutes_lifetime"] == 360

    data = validate_success(
        api_client.submit_resolution_review(
            outage_id, {"outcome": "VERIFY"}, make_compliance_auditor_headers(AUDITOR_1)
        )
    )

    assert data["state"] == "VERIFIED", "the same role, a different identity"
    assert read_station(station_id)["billable_downtime_minutes_lifetime"] == 360


def test_the_auditor_who_finalised_the_report_cannot_decide_its_claim():
    """Presenting a second role does not make the same human independent.

    PRD §2.8, SoD-2: "When a `ComplianceAuditor` finalises an uptime report, their
    `X-User-ID` is stored as `finalized_by_user_id`.  Whoever later decides a
    reimbursement claim drawn on that report must present an `X-User-ID`
    different from that recorded value — the bar follows the person, not the role,
    so it applies even when the same human acts as `ProgramAdministrator`."  PRD
    §3.8: "Every decision is subject to SoD-2: the deciding `X-User-ID` must
    differ from the report's `finalized_by_user_id`, or the request is rejected
    with `ERR_SEGREGATION_OF_DUTIES`."  And: `APPROVE` "moves the claim `REVIEW →
    APPROVED`, sets `withheld_amount_cents` to zero and `approved_amount_cents`
    to `requested_amount_cents`."

    Design: Corner/validations/report_finalizer_cannot_decide_the_claim_even_under_a_different_role
    """
    scenario = setup_station(
        clock="2026-05-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        stop_at="OPERATIONAL",
    )
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    set_clock("2026-06-10T00:00:00Z")
    run_repair_cycle(
        port_id,
        detected_at="2026-06-10T00:00:00Z",
        window_start_at="2026-06-10T01:00:00Z",
        window_end_at="2026-06-11T00:00:00Z",
        completed_at="2026-06-10T21:36:00Z",
        fault_class="MINOR",
        fault_code="OCPP-MIN-01",
    )

    set_clock("2026-07-15T00:00:00Z")
    report = setup_accepted_report(
        station_id,
        "2026-06-01T00:00:00Z",
        "2026-07-01T00:00:00Z",
        auditor_user_id=UNKNOWN_USER,
        program_admin_user_id=PROGRAM_ADMIN_1,
    )
    assert report["finalized_by_user_id"] == UNKNOWN_USER
    assert report["state"] == "ACCEPTED"
    assert float(report["uptime_pct"]) == 97.00, "1296 billable minutes out of 43200"

    claim = file_claim(
        report["id"], [claim_line_item(port_id, 1000, "OANDM")], report["version"]
    )
    reviewed = open_claim_review(claim["id"])
    assert reviewed["state"] == "REVIEW"
    assert float(reviewed["withhold_rate"]) == 0.00

    response = api_client.decide_reimbursement_claim(
        claim["id"], "APPROVE", make_program_administrator_headers(UNKNOWN_USER)
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

    blocked = read_claim(claim["id"])
    assert blocked["state"] == "REVIEW", "left for a genuinely independent administrator"
    assert blocked["decided_by_user_id"] is None
    assert blocked["approved_amount_cents"] is None

    data = validate_success(
        api_client.decide_reimbursement_claim(
            claim["id"], "APPROVE", make_program_administrator_headers(PROGRAM_ADMIN_2)
        )
    )

    assert data["state"] == "APPROVED"
    assert data["approved_amount_cents"] == 1000
    assert data["withheld_amount_cents"] == 0
    assert data["decided_by_user_id"] == PROGRAM_ADMIN_2
    assert read_uptime_report(report["id"])["finalized_by_user_id"] == UNKNOWN_USER

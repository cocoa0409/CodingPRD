"""Both ids exist; only the edge between them is wrong."""
from test_helpers import (
    FULLY_COMPLIANT_PORT,
    OPERATOR_HEADERS,
    SUPPORT_HEADERS,
    ApiErrorId,
    api_client,
    assert_version_unchanged,
    claim_line_item,
    create_reimbursement_claim_payload,
    create_station,
    file_claim,
    ingest_and_classify_outage,
    install_charging_port,
    intake_complaint,
    read_complaint,
    read_uptime_report,
    set_clock,
    setup_accepted_report,
    setup_station,
    triage_payload,
    validate_error,
    validate_paginated,
)


def test_a_sibling_stations_dispenser_may_not_appear_on_a_claim_or_in_a_triage_link():
    """Existence checks alone accept both of these payloads.

    PRD §3.8: "every `port_id` in it must belong to the report's station, or the
    filing is rejected with `ERR_CLAIM_LINE_PORT_MISMATCH`."  PRD §3.9 on triage:
    "`LINK_OUTAGE` attributes the complaint to a fault and advances `INTAKE →
    TRIAGED`: it requires a `linked_outage_event_id` naming an outage whose
    dispenser is the same one the complaint names, or the request is rejected with
    `ERR_COMPLAINT_OUTAGE_MISMATCH`, and it writes that identifier onto the
    complaint."  PRD §3.8 on what a filing would otherwise have moved: it "raises
    the report's `claim_count`, and increments the report's `version`".

    Design: Corner/errors/claim_line_and_triage_link_mismatches_are_rejected_by_ownership
    """
    scenario = setup_station(
        clock="2026-05-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        committed_service_capacity_kw=800.00,
        power_class="DCFC_150",
        declared_port_count=1,
        ports=[dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-1")],
        stop_at="OPERATIONAL",
    )
    reporting_station = scenario["station"]["id"]
    own_port = scenario["ports"][0]["id"]

    sibling_station = create_station(
        scenario["host_site"]["id"], "ST-2", power_class="DCFC_150", declared_port_count=1
    )
    sibling_port = install_charging_port(
        sibling_station["id"], "DS-2", connector_type="NACS", terminal_model="PT-9"
    )

    set_clock("2026-06-05T00:00:00Z")
    sibling_outage = ingest_and_classify_outage(
        sibling_port["id"],
        "2026-06-05T00:00:00Z",
        fault_class="MAJOR",
        fault_code="EVSE-MAJ-11",
    )
    complaint = intake_complaint(
        reporting_station,
        own_port,
        "2026-06-04T10:00:00Z",
        "2026-06-04T11:00:00Z",
        10.000,
        40,
        600,
        complaint_type="PRICE_MISMATCH",
    )

    set_clock("2026-07-15T00:00:00Z")
    report = setup_accepted_report(
        reporting_station, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
    )
    assert float(report["uptime_pct"]) == 100.00, "no fault ever touched DS-1"

    cross_station_claim = api_client.create_reimbursement_claim(
        create_reimbursement_claim_payload(
            report["id"],
            [
                claim_line_item(own_port, 1500, "OANDM"),
                claim_line_item(sibling_port["id"], 500, "PARTS"),
            ],
            report["version"],
        ),
        OPERATOR_HEADERS,
    )

    validate_error(cross_station_claim, ApiErrorId.ERR_CLAIM_LINE_PORT_MISMATCH, 409)

    _rows, meta = validate_paginated(
        api_client.list_report_reimbursement_claims(report["id"], OPERATOR_HEADERS)
    )
    assert meta["total_count"] == 0, "a valid first line item does not rescue the filing"
    untouched_report = read_uptime_report(report["id"])
    assert untouched_report["claim_count"] == 0
    assert_version_unchanged(untouched_report, report["version"], "UptimeReport")

    cross_port_link = api_client.triage_customer_complaint(
        complaint["id"],
        triage_payload("LINK_OUTAGE", sibling_outage["id"]),
        SUPPORT_HEADERS,
    )

    validate_error(cross_port_link, ApiErrorId.ERR_COMPLAINT_OUTAGE_MISMATCH, 409)

    still_intake = read_complaint(complaint["id"])
    assert still_intake["state"] == "INTAKE"
    assert still_intake["linked_outage_event_id"] is None

    claim = file_claim(
        report["id"], [claim_line_item(own_port, 1500, "OANDM")], report["version"]
    )

    assert claim["state"] == "PENDING", "the pinned report version was never consumed"
    assert claim["requested_amount_cents"] == 1500
    assert read_uptime_report(report["id"])["claim_count"] == 1

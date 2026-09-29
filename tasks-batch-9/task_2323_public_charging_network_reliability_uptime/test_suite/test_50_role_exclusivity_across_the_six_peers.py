"""The six roles are peers: the busiest of them still cannot do the others' work."""
from test_helpers import (
    AUDITOR_HEADERS,
    NON_EXISTENT_UUID,
    OPERATOR_HEADERS,
    SUPPORT_HEADERS,
    ApiErrorId,
    api_client,
    create_customer_complaint_payload,
    create_dispatch,
    create_host_site_payload,
    create_station,
    create_uptime_report_payload,
    ingest_and_classify_outage,
    install_charging_port,
    make_host_site_manager_headers,
    read_charging_port,
    read_dispatch,
    read_outage_event,
    read_station,
    register_commissionable_host_site,
    validate_error,
    validate_paginated,
)


def test_no_role_inherits_another_roles_exclusive_operation():
    """Treating NetworkOperator as a superuser would let it certify its own terminals.

    PRD §2.1: "When the headers are well-formed but the acting role is not
    authorised for the endpoint being called, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."  PRD §4 assigns each of these operations to a
    single role: `POST /host-sites` to `NetworkOperator`, `POST
    /charging-ports/{port_id}/terminal-certification` to `ComplianceAuditor`, `POST
    /uptime-reports` to `NetworkOperator`, `POST
    /maintenance-dispatches/{dispatch_id}/progress` to `FieldTechnician`, `POST
    /customer-complaints` to `CustomerSupportAgent`, `POST
    /reimbursement-claims/{claim_id}/decision` to `ProgramAdministrator`, and `POST
    /outage-events/{outage_event_id}/classify` to `NetworkOperator`, while `GET
    /maintenance-dispatches` is open to "Any" — and "Roles listed as "Any" mean all
    six declared roles."  PRD §2.11 puts "Role authorisation against the endpoint's
    permitted roles — `ERR_UNAUTHORIZED`" second and "Existence of every identifier"
    third.

    Design: Corner/rbac/a_role_cannot_invoke_another_roles_exclusive_operation
    """
    site = register_commissionable_host_site("HS-1", committed_service_capacity_kw=400.00)
    station = create_station(site["id"], "ST-1", declared_port_count=1)
    port = install_charging_port(station["id"], "DS-1", terminal_model="PT-9")
    outage = ingest_and_classify_outage(
        port["id"], "2026-08-01T00:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )
    dispatch = create_dispatch(
        outage["id"],
        port["id"],
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T09:00:00Z",
    )

    station_version = read_station(station["id"])["version"]
    port_version = read_charging_port(port["id"])["version"]
    outage_version = read_outage_event(outage["id"])["version"]
    dispatch_version = dispatch["version"]
    manager_headers = make_host_site_manager_headers(site["id"])

    validate_error(
        api_client.create_host_site(
            create_host_site_payload("HS-2", committed_service_capacity_kw=250.00),
            AUDITOR_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.record_terminal_certification(port["id"], "CERTIFIED", OPERATOR_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.create_uptime_report(
            create_uptime_report_payload(
                station["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
            ),
            SUPPORT_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.post_dispatch_progress(dispatch["id"], "EN_ROUTE", OPERATOR_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.create_customer_complaint(
            create_customer_complaint_payload(
                station["id"],
                port["id"],
                "2026-07-31T10:00:00Z",
                "2026-07-31T11:00:00Z",
                5.000,
                40,
                250,
                complaint_type="CHARGER_OFFLINE",
            ),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.decide_reimbursement_claim(NON_EXISTENT_UUID, "APPROVE", AUDITOR_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.classify_outage_event(
            outage["id"], {"fault_class": "CRITICAL"}, manager_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    _sites, site_meta = validate_paginated(api_client.list_host_sites(OPERATOR_HEADERS))
    assert site_meta["total_count"] == 1, "the auditor's registration never landed"

    _complaints, complaint_meta = validate_paginated(
        api_client.list_customer_complaints(SUPPORT_HEADERS)
    )
    assert complaint_meta["total_count"] == 0, "the operator's complaint never landed"

    untouched_port = read_charging_port(port["id"])
    assert untouched_port["terminal_certification_status"] == "PENDING"
    assert untouched_port["version"] == port_version

    untouched_outage = read_outage_event(outage["id"])
    assert untouched_outage["fault_class"] == "MAJOR", "the manager's reclassification was refused"
    assert untouched_outage["state"] == "DISPATCHED"
    assert untouched_outage["version"] == outage_version

    untouched_dispatch = read_dispatch(dispatch["id"])
    assert untouched_dispatch["state"] == "CREATED"
    assert untouched_dispatch["version"] == dispatch_version
    assert read_station(station["id"])["version"] == station_version

    rows, meta = validate_paginated(
        api_client.list_maintenance_dispatches(manager_headers, {"state": "CREATED"})
    )
    assert [row["id"] for row in rows] == [dispatch["id"]], "every read is a shared operation"
    assert meta["total_count"] == 1

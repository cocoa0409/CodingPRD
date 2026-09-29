"""The two version-guarded creations: a rejected write must not consume the
version the retry needs."""
from test_helpers import (
    OPERATOR_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    TECHNICIAN_1,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_spare_part_unit_conservation,
    claim_line_item,
    create_dispatch,
    create_part_reservation_payload,
    create_reimbursement_claim_payload,
    file_claim,
    ingest_and_classify_outage,
    read_claim,
    read_part_reservation,
    read_spare_part,
    read_uptime_report,
    reserve_parts,
    set_clock,
    setup_accepted_report,
    setup_operational_station,
    setup_spare_part_with_stock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_second_filer_holding_the_accept_time_version_cannot_discard_the_first_claim():
    """Filing supersedes a sibling, so a stale filer would destroy a claim it never read.

    PRD §2.7: "Filing a reimbursement claim requires a non-optional
    `expected_uptime_report_version` field carrying the client's last observed
    `version` of the `UptimeReport` named by `uptime_report_id`.  If that value does
    not equal the report's current `version`, the request is rejected with
    `ERR_STALE_PARENT_VERSION` (HTTP 412).  The guard exists because claim filing is
    a supersede pattern: a new claim drives any existing `PENDING` claim on the same
    report to `SUPERSEDED` and raises the report's `claim_count`, so a writer holding
    a stale view of the report would silently discard a claim it never saw."  PRD
    §3.8: "Filing writes `requested_amount_cents` as the exact integer sum of the
    line-item amounts, opens the claim in `PENDING` ... drives any existing `PENDING`
    claim on the same report to `SUPERSEDED` (incrementing that claim's `version`),
    raises the report's `claim_count`, and increments the report's `version`."  PRD
    §2.3: "Reimbursement claims under an uptime report are filtered by `state`" and
    these listings "include rows a creation response never returned to any client —
    ... claims driven to `SUPERSEDED` by a later filing all appear."

    Design: Corner/cross_cutting_complexity_layers/stale_uptime_report_version_blocks_claim_creation_and_its_supersede
    """
    scenario = setup_operational_station(
        clock="2026-05-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        port_count=1,
        committed_service_capacity_kw=400.00,
    )
    station_id = scenario["station"]["id"]
    port_id = scenario["ports"][0]["id"]

    set_clock("2026-07-15T00:00:00Z")
    report = setup_accepted_report(station_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    accept_version = report["version"]
    assert float(report["uptime_pct"]) == 100.00

    first_claim = file_claim(
        report["id"], [claim_line_item(port_id, 1200, "OANDM")], accept_version
    )

    assert first_claim["state"] == "PENDING"
    after_first = read_uptime_report(report["id"])
    assert after_first["claim_count"] == 1
    assert after_first["version"] == accept_version + 1

    stale = api_client.create_reimbursement_claim(
        create_reimbursement_claim_payload(
            report["id"], [claim_line_item(port_id, 800, "NETWORK_FEES")], accept_version
        ),
        OPERATOR_HEADERS,
    )

    validate_error(stale, ApiErrorId.ERR_STALE_PARENT_VERSION, 412)

    unchanged = read_uptime_report(report["id"])
    assert unchanged["claim_count"] == 1, "the rejected filing created nothing"
    assert unchanged["version"] == accept_version + 1, "and consumed no version"
    assert read_claim(first_claim["id"])["state"] == "PENDING"

    second_claim = file_claim(
        report["id"], [claim_line_item(port_id, 800, "NETWORK_FEES")], unchanged["version"]
    )

    assert second_claim["state"] == "PENDING"
    assert second_claim["requested_amount_cents"] == 800
    assert read_claim(first_claim["id"])["state"] == "SUPERSEDED", "now the supersede lands"

    after_second = read_uptime_report(report["id"])
    assert after_second["claim_count"] == 2
    assert after_second["version"] == accept_version + 2

    rows, meta = validate_paginated(
        api_client.list_report_reimbursement_claims(
            report["id"], PROGRAM_ADMIN_HEADERS, {"state": "PENDING"}
        )
    )
    assert [row["id"] for row in rows] == [second_claim["id"]]
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api_client.list_report_reimbursement_claims(report["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2, "the superseded claim is still listed"

    rows, meta = validate_paginated(
        api_client.list_station_uptime_reports(
            station_id, PROGRAM_ADMIN_HEADERS, {"state": "ACCEPTED"}
        )
    )
    assert [row["id"] for row in rows] == [report["id"]]
    assert meta["total_count"] == 1


def test_the_refreshed_reservation_retry_lands_on_the_backordered_side_of_the_stock_line():
    """Two reservations on one part are both legal, so only the version field can
    detect that the depot balance moved.

    PRD §2.7: "Earmarking depot stock requires a non-optional
    `expected_spare_part_version` field carrying the client's last observed `version`
    of the `SparePart` named by `spare_part_id`.  A value that does not equal the
    part's current `version` is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412).
    Reservation creation legitimately succeeds any number of times against the same
    part, so the state machine alone cannot detect that the depot balance the writer
    reasoned about has already moved".  PRD §3.6: "If the quantity exceeds the
    unencumbered figure, the reservation is created directly in `BACKORDERED` — the
    response already reports that state — the part's `backordered_qty` rises by that
    quantity instead, and `expected_available_at` is set to the logical clock's
    current reading advanced by the part's `lead_time_days` days.  Either way the
    part's `version` increments."  PRD §3.6 on the conserved figure: "`unencumbered_qty`
    ... is `on_hand_qty` less `reserved_qty`."

    Design: Corner/cross_cutting_complexity_layers/stale_spare_part_version_blocks_a_second_reservation_on_the_same_depot_row
    """
    scenario = setup_operational_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        port_count=1,
        committed_service_capacity_kw=400.00,
    )
    port_id = scenario["ports"][0]["id"]
    outage = ingest_and_classify_outage(
        port_id, "2026-08-01T00:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T09:00:00Z",
        technician_user_id=TECHNICIAN_1,
    )
    part = setup_spare_part_with_stock(
        part_number="SP-1", part_class="DISPENSER", lead_time_days=3, on_hand_qty=10
    )
    restock_version = part["version"]

    first = reserve_parts(dispatch["id"], part["id"], 6, restock_version)

    assert first["state"] == "RESERVED"
    after_first = read_spare_part(part["id"])
    assert after_first["on_hand_qty"] == 10
    assert after_first["reserved_qty"] == 6
    assert after_first["unencumbered_qty"] == 4
    assert after_first["backordered_qty"] == 0
    assert after_first["version"] == restock_version + 1

    stale = api_client.create_part_reservation(
        create_part_reservation_payload(dispatch["id"], part["id"], 6, restock_version),
        OPERATOR_HEADERS,
    )

    validate_error(stale, ApiErrorId.ERR_STALE_PARENT_VERSION, 412)

    unchanged = read_spare_part(part["id"])
    assert unchanged["on_hand_qty"] == 10
    assert unchanged["reserved_qty"] == 6
    assert unchanged["unencumbered_qty"] == 4
    assert unchanged["backordered_qty"] == 0
    assert unchanged["version"] == restock_version + 1, "the rejected earmark consumed nothing"

    _rows, meta = validate_paginated(
        api_client.list_part_reservations(OPERATOR_HEADERS, {"spare_part_id": part["id"]})
    )
    assert meta["total_count"] == 1, "no reservation row was created by the rejected call"

    second = validate_success(
        api_client.create_part_reservation(
            create_part_reservation_payload(
                dispatch["id"], part["id"], 6, unchanged["version"]
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )

    assert second["state"] == "BACKORDERED", "qty 6 exceeds the unencumbered 4"
    assert_instant_equals(
        second["expected_available_at"], "2026-08-04T00:00:00Z", "expected_available_at"
    )

    after_second = read_spare_part(part["id"])
    assert after_second["on_hand_qty"] == 10, "a backorder must not overdraw the shelf"
    assert after_second["reserved_qty"] == 6
    assert after_second["backordered_qty"] == 6
    assert after_second["unencumbered_qty"] == 4
    assert after_second["version"] == restock_version + 2
    assert_spare_part_unit_conservation(after_second)

    rows, meta = validate_paginated(
        api_client.list_part_reservations(
            OPERATOR_HEADERS, {"spare_part_id": part["id"], "state": "BACKORDERED"}
        )
    )
    assert [row["id"] for row in rows] == [second["id"]]
    assert meta["total_count"] == 1
    assert read_part_reservation(first["id"])["state"] == "RESERVED"

    _rows, meta = validate_paginated(
        api_client.list_part_reservations(OPERATOR_HEADERS, {"spare_part_id": part["id"]})
    )
    assert meta["total_count"] == 2

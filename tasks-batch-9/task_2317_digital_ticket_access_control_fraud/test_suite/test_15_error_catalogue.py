"""Codes that must be reachable, and reachable as themselves rather than as a cousin.

Twelve collections each owning their own 404, a repeat scan that costs a strike
while an offline upload is refused for its channel, a zone that admits only
credentials, a ceiling checked before the step is taken, and a variance that
needs signing off twice over.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    AuditAction,
    EntitlementLevel,
    EventStatus,
    FraudRiskBasis,
    GATE_OPERATOR,
    IncidentCategory,
    IncidentStatus,
    NON_EXISTENT_UUID,
    ReportStatus,
    ScanResult,
    SECURITY_INVESTIGATOR,
    SessionMode,
    VENUE_ADMIN,
    constants as C,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_one_unknown_identifier_answers_with_each_collections_own_not_found_code(api):
    """The same well-formed stranger produces twelve different identifiers.

    PRD: "Each collection raises its own not-found error: `ERR_EVENT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_GATE_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CREDENTIAL_REQUEST_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_SCAN_EVENT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND` and `ERR_REPORT_NOT_FOUND`."
    PRD: "4. Path identifiers resolve, left to right — the collection's own not-found error (404), for example `ERR_EVENT_NOT_FOUND` for an event path segment, `ERR_TICKET_NOT_FOUND` for a ticket segment, `ERR_SESSION_NOT_FOUND` for a scan-session segment and `ERR_REPORT_NOT_FOUND` for a reconciliation-report segment, as enumerated in §2.7."

    Design: Corner/errors/every_path_collection_raises_its_own_not_found_code
    """
    reads = [
        (api.get_event, ApiErrorId.EVENT_NOT_FOUND),
        (api.get_access_zone, ApiErrorId.ZONE_NOT_FOUND),
        (api.get_gate, ApiErrorId.GATE_NOT_FOUND),
        (api.get_patron, ApiErrorId.PATRON_NOT_FOUND),
        (api.get_ticket, ApiErrorId.TICKET_NOT_FOUND),
        (api.get_transfer_request, ApiErrorId.TRANSFER_NOT_FOUND),
        (api.get_resale_listing, ApiErrorId.LISTING_NOT_FOUND),
        (api.get_credential_request, ApiErrorId.CREDENTIAL_REQUEST_NOT_FOUND),
        (api.get_scan_session, ApiErrorId.SESSION_NOT_FOUND),
        (api.get_scan_event, ApiErrorId.SCAN_EVENT_NOT_FOUND),
        (api.get_denied_entry_incident, ApiErrorId.INCIDENT_NOT_FOUND),
        (api.get_reconciliation_report, ApiErrorId.REPORT_NOT_FOUND),
    ]
    # Twelve collections, twelve identifiers, one unresolvable key.
    assert len({expected for _, expected in reads}) == 12

    for read, expected in reads:
        validate_error(read(NON_EXISTENT_UUID, VENUE_ADMIN), expected, 404)


def test_a_repeat_entry_costs_a_strike_and_an_upload_is_refused_for_its_channel(api):
    """A fresh dedupe key does not legalize a second entry, and ONLINE takes no cache.

    PRD: "23. An entry scan is refused when the ticket's `admission_status` is already `INSIDE` — `ERR_DUPLICATE_SCAN` (409), on live scanning and offline batch items."
    PRD: "12. An offline batch targets a session whose `mode` is `OFFLINE_CAPABLE` — `ERR_SESSION_NOT_OFFLINE_CAPABLE` (409), on offline batch upload."
    PRD: "Failures at rules 20 through 27 are **adjudication failures on a well-formed scan**: the server persists a scan event carrying the mapped denial result and the mapped error identifier as its `denied_reason_code`, and *then* returns that error with its declared HTTP status."
    PRD: "A duplicate entry scan on a ticket that is already `INSIDE` moves it `INSIDE → DENIED_FLAGGED`, persists a scan event with `result` `DENIED_DUPLICATE` and `denied_reason_code` of `ERR_DUPLICATE_SCAN`, opens a `DUPLICATE` incident, and leaves the occupancy counters alone."
    PRD: "When a fraud-bearing denial does open an incident, the cascade runs in four links within the same request: the incident is created in `OPEN`; the holder's `strike_count` rises by one and their `fraud_risk_score` is recomputed under the provisional reading; if that recomputed score reaches 40, every `LISTED` listing of that patron is suspended; and each suspended listing reverts its ticket's `lifecycle_status` to `ISSUED`."
    PRD: "The second is the patron's denied-entry history, where each incident contributes points according to its `category`: `COUNTERFEIT` weighs 50, `DEVICE_MISMATCH` weighs 45, `UNAUTHORIZED_RESALE` weighs 30, `DUPLICATE` weighs 20 and `ZONE_VIOLATION` weighs 15."

    Design: Corner/errors/duplicate_online_scan_and_offline_upload_on_an_online_session
    """
    venue = fx.scan_ready_venue(api, device_fingerprint="DEV-ADA")
    ticket_id = venue["ticket"]["id"]
    admitted = fx.admit_ticket(api, venue["session"]["id"], ticket_id, "DEV-ADA", "K1")
    assert admitted["result"] == ScanResult.ADMITTED

    barcode = fx.current_barcode(api, ticket_id)
    validate_error(
        fx.denied_scan_response(api, venue["session"]["id"], barcode, "DEV-ADA", "K2"),
        ApiErrorId.DUPLICATE_SCAN,
        409,
    )

    # The channel check sits above every barcode rule, so nothing is adjudicated.
    seed = fx.get_barcode(api, ticket_id)["barcode_seed"]
    validate_error(
        api.upload_offline_batch(
            venue["session"]["id"],
            f.offline_batch_payload(
                [
                    f.offline_scan_item(
                        f"{seed}-{C.EPOCH_AT_18_10_00}", "DEV-ADA", "B1", C.T_18_10_00
                    )
                ]
            ),
            GATE_OPERATOR,
        ),
        ApiErrorId.SESSION_NOT_OFFLINE_CAPABLE,
        409,
    )

    recorded = fx.list_scan_events(api, scan_session_id=venue["session"]["id"])
    assert len(recorded) == 2
    assert sorted(row["result"] for row in recorded) == sorted(
        [ScanResult.ADMITTED, ScanResult.DENIED_DUPLICATE]
    )
    denied = next(row for row in recorded if row["result"] == ScanResult.DENIED_DUPLICATE)
    assert denied["denied_reason_code"] == ApiErrorId.DUPLICATE_SCAN

    incidents = fx.list_incidents(api)
    assert len(incidents) == 1
    assert incidents[0]["category"] == IncidentCategory.DUPLICATE
    assert incidents[0]["ticket_id"] == ticket_id
    assert incidents[0]["patron_id"] == venue["holder"]["id"]
    assert incidents[0]["status"] == IncidentStatus.OPEN

    holder = fx.read_patron(api, venue["holder"]["id"])
    assert holder["strike_count"] == 1
    assert holder["fraud_risk_score"] == C.CATEGORY_WEIGHTS["DUPLICATE"]
    assert holder["fraud_risk_basis"] == FraudRiskBasis.PROVISIONAL

    # The repeat is treated as evidence, so presence is flagged rather than left alone.
    assert fx.read_ticket(api, ticket_id)["admission_status"] == AdmissionStatus.DENIED_FLAGGED


def test_the_back_of_house_gate_refuses_a_foreign_zone_and_a_paid_ticket_of_its_own(api):
    """One rule, two limbs: the wrong zone and the right zone with the wrong type.

    PRD: "25. Zone entitlement: the gate's `access_zone_id` equals the ticket's `access_zone_id`, and the ticket's `ticket_type` is `CREDENTIAL` whenever the zone's `required_entitlement_level` is `BACK_OF_HOUSE` — `ERR_ZONE_NOT_ENTITLED` (403), on live scanning and offline batch items."
    PRD: "Failures at rules 20 through 27 are **adjudication failures on a well-formed scan**: the server persists a scan event carrying the mapped denial result and the mapped error identifier as its `denied_reason_code`, and *then* returns that error with its declared HTTP status."
    PRD: "`DENIED_COUNTERFEIT` maps to incident `category` `COUNTERFEIT`; `DENIED_STALE_BARCODE` also maps to `COUNTERFEIT`, because an out-of-window epoch is a replayed screenshot; `DENIED_DEVICE_MISMATCH` maps to `DEVICE_MISMATCH`; `DENIED_DUPLICATE` maps to `DUPLICATE`; and `DENIED_ZONE` maps to `ZONE_VIOLATION`."
    PRD: "A device mismatch, a zone violation or an out-of-window barcode on a ticket that has not yet entered moves it `NOT_ADMITTED → DENIED_FLAGGED`, persists the scan event with the mapped denial result and reason code, opens an incident of the mapped category, and likewise leaves the occupancy counters alone."
    PRD: "The second is the patron's denied-entry history, where each incident contributes points according to its `category`: `COUNTERFEIT` weighs 50, `DEVICE_MISMATCH` weighs 45, `UNAUTHORIZED_RESALE` weighs 30, `DUPLICATE` weighs 20 and `ZONE_VIOLATION` weighs 15."

    Design: Corner/errors/access_zone_enforcement_refuses_a_wrong_zone_and_a_non_credential_at_back_of_house
    """
    event = fx.create_event(api)
    front = fx.create_zone(api, event["id"], fire_code_capacity=150)
    crew = fx.create_zone(
        api,
        event["id"],
        zone_code="BOH1",
        required_entitlement_level=EntitlementLevel.BACK_OF_HOUSE,
        fire_code_capacity=50,
    )
    crew_gate = fx.create_gate(api, event["id"], crew["id"], gate_code="G2")
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)

    ada = fx.register_patron(api)
    bob = fx.register_patron(
        api, email="bob@example.com", display_name="Bob Stone", document_reference="DL-BOB-1"
    )
    ticket_ada = fx.issue_ticket(api, event["id"], front["id"], ada["id"])
    ticket_bob = fx.issue_ticket(api, event["id"], crew["id"], bob["id"])
    fx.bind_device(api, ticket_ada["id"], ada["id"], "DEV-ADA")
    fx.bind_device(api, ticket_bob["id"], bob["id"], "DEV-BOB")
    fx.advance_event(api, event["id"], EventStatus.DOORS_OPEN)

    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, crew_gate["id"])

    # Ada's entitlement is for the front of house; this gate serves the crew zone.
    validate_error(
        fx.denied_scan_response(
            api,
            session["id"],
            fx.current_barcode(api, ticket_ada["id"]),
            "DEV-ADA",
            "Z1",
        ),
        ApiErrorId.ZONE_NOT_ENTITLED,
        403,
    )
    # Bob's zone matches exactly, but back of house admits credentials only.
    validate_error(
        fx.denied_scan_response(
            api,
            session["id"],
            fx.current_barcode(api, ticket_bob["id"]),
            "DEV-BOB",
            "Z2",
        ),
        ApiErrorId.ZONE_NOT_ENTITLED,
        403,
    )

    recorded = fx.list_scan_events(api, scan_session_id=session["id"])
    assert len(recorded) == 2
    assert all(row["result"] == ScanResult.DENIED_ZONE for row in recorded)
    assert all(row["denied_reason_code"] == ApiErrorId.ZONE_NOT_ENTITLED for row in recorded)

    incidents = fx.list_incidents(api)
    assert len(incidents) == 2
    assert all(row["category"] == IncidentCategory.ZONE_VIOLATION for row in incidents)
    assert {row["ticket_id"] for row in incidents} == {ticket_ada["id"], ticket_bob["id"]}

    for patron in (ada, bob):
        read = fx.read_patron(api, patron["id"])
        assert read["strike_count"] == 1
        assert read["fraud_risk_score"] == C.CATEGORY_WEIGHTS["ZONE_VIOLATION"]

    # A zone denial admits nobody.
    assert fx.read_zone(api, crew["id"])["occupancy_count"] == 0
    assert fx.read_event(api, event["id"])["live_occupancy"] == 0
    for ticket in (ticket_ada, ticket_bob):
        assert (
            fx.read_ticket(api, ticket["id"])["admission_status"]
            == AdmissionStatus.DENIED_FLAGGED
        )


def test_the_venue_ceiling_counts_the_pending_admit_and_stops_the_second_person(api):
    """A capacity of one admits one, and the refusal is a safety stop rather than fraud.

    PRD: "26. Zone fire code: admitting one more person keeps the zone's `occupancy_count` at or below its `fire_code_capacity` — `ERR_ZONE_CAPACITY_FULL` (409), on live scanning only."
    PRD: "27. Event fire code: admitting one more person keeps the event's `live_occupancy` at or below its `fire_code_capacity` — `ERR_EVENT_FIRE_CODE_FULL` (409), on live scanning only."
    PRD: "The three **operational** denials — `DENIED_CAPACITY`, `DENIED_REENTRY_LOCKOUT` and `DENIED_VOIDED` — persist their scan event but open no incident, book no strike and leave the patron's `fraud_risk_score` untouched, because a full house is not the patron's fault."
    PRD: "Denials with no declared transition — capacity refusals, the re-entry lockout and the voided-ticket case — leave the ticket's `admission_status` exactly as it was."
    PRD: "Alongside it the read reports the event's `event_id`, `live_occupancy`, `peak_live_occupancy`, `reconciled_attendance`, `fire_code_capacity`, the `headroom` remaining (the event's fire-code capacity less its live occupancy), and a `zone_occupancy` array carrying, for each access zone of the event, that zone's `id`, `zone_code`, `occupancy_count` and `fire_code_capacity`."

    Design: Corner/errors/event_fire_code_ceiling_refuses_the_admit_that_would_exceed_it
    """
    event = fx.create_event(api, fire_code_capacity=1)
    zone = fx.create_zone(api, event["id"], fire_code_capacity=5)
    gate = fx.create_gate(api, event["id"], zone["id"])
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)

    ada = fx.register_patron(api)
    bob = fx.register_patron(
        api, email="bob@example.com", display_name="Bob Stone", document_reference="DL-BOB-1"
    )
    ticket_ada = fx.issue_ticket(api, event["id"], zone["id"], ada["id"])
    ticket_bob = fx.issue_ticket(api, event["id"], zone["id"], bob["id"])
    fx.bind_device(api, ticket_ada["id"], ada["id"], "DEV-ADA")
    fx.bind_device(api, ticket_bob["id"], bob["id"], "DEV-BOB")
    fx.advance_event(api, event["id"], EventStatus.DOORS_OPEN)

    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, gate["id"])

    # Nought plus one is within one.
    first = fx.admit_ticket(api, session["id"], ticket_ada["id"], "DEV-ADA", "F1")
    assert first["result"] == ScanResult.ADMITTED

    # The zone still had room for five, so it is the venue ceiling that refuses.
    validate_error(
        fx.denied_scan_response(
            api,
            session["id"],
            fx.current_barcode(api, ticket_bob["id"]),
            "DEV-BOB",
            "F2",
        ),
        ApiErrorId.EVENT_FIRE_CODE_FULL,
        409,
    )

    occupancy = fx.read_occupancy(api, event["id"])
    assert occupancy["live_occupancy"] == 1
    # Headroom reaches nought rather than going negative.
    assert occupancy["headroom"] == 0

    recorded = fx.list_scan_events(api, scan_session_id=session["id"])
    assert len(recorded) == 2
    refused = next(row for row in recorded if row["result"] == ScanResult.DENIED_CAPACITY)
    assert refused["denied_reason_code"] == ApiErrorId.EVENT_FIRE_CODE_FULL
    assert refused["ticket_id"] == ticket_bob["id"]

    # A full house is nobody's fault, so no investigation was opened.
    assert fx.list_incidents(api) == []
    assert fx.read_patron(api, bob["id"])["strike_count"] == 0
    assert fx.read_patron(api, bob["id"])["fraud_risk_score"] == 0

    assert (
        fx.read_ticket(api, ticket_bob["id"])["admission_status"] == AdmissionStatus.NOT_ADMITTED
    )
    assert fx.read_gate(api, gate["id"])["admitted_scan_count"] == 1


def test_an_unresolved_variance_blocks_finalization_and_then_locks_the_event(api):
    """Two hundred percent needs an override, and afterwards no second report may be cut.

    PRD: "**Finalization** requires the report to be `DRAFT` or `REOPENED`, and requires the absolute value of `variance_pct` to be no greater than 2.00 percent — or, failing that, a non-empty `override_reason` supplied with the request."
    PRD: "An out-of-tolerance variance with no override is refused with `ERR_ATTENDANCE_VARIANCE_UNRESOLVED`."
    PRD: "Finalization recomputes `scan_derived_attendance`, `variance_count`, `variance_pct` and `fire_code_breach` afresh rather than trusting the figures cut at creation, sets `status` to `FINAL`, stamps `finalized_by_user_id` with the admin's `X-User-ID`, drives the event's `status` to `RECONCILED`, and appends an audit entry with the action `RECONCILIATION_FINALIZED`."
    PRD: "17. The event already carries a `FINAL` reconciliation report, or its `status` is already `RECONCILED` — `ERR_EVENT_ALREADY_RECONCILED` (409), on reconciliation-report creation."
    PRD: "At creation the report's derived figures are computed: `scan_derived_attendance` from the reconciled reading of §2.9, `variance_count` as the `reported_attendance` minus `scan_derived_attendance`, `variance_pct` as that variance divided by `scan_derived_attendance`, multiplied by 100 and rounded half up to two decimal places — defined as exactly 0.00 when `scan_derived_attendance` is zero, rather than an error — and `fire_code_breach` set true when `scan_derived_attendance` exceeds the event's `fire_code_capacity`."

    Design: Corner/errors/finalization_variance_gate_then_the_event_is_locked_against_a_second_report
    """
    venue = fx.scan_ready_venue(api, device_fingerprint="DEV-ADA", mode=SessionMode.ONLINE)
    event_id = venue["event"]["id"]
    fx.admit_ticket(api, venue["session"]["id"], venue["ticket"]["id"], "DEV-ADA", "R1")
    closed = fx.close_event(api, event_id, [venue["session"]["id"]])
    assert closed["status"] == EventStatus.CLOSED

    report = fx.create_report(api, event_id, 3)
    assert report["status"] == ReportStatus.DRAFT
    assert report["scan_derived_attendance"] == 1
    assert report["variance_count"] == 2
    # Two people unaccounted for against one scanned is twice the derived figure.
    assert report["variance_pct"] == 200.00
    assert report["fire_code_breach"] is False

    validate_error(
        api.finalize_reconciliation_report(report["id"], f.finalize_payload(), VENUE_ADMIN),
        ApiErrorId.ATTENDANCE_VARIANCE_UNRESOLVED,
        409,
    )
    assert (
        validate_success(api.get_reconciliation_report(report["id"], VENUE_ADMIN))["status"]
        == ReportStatus.DRAFT
    )

    finalized = validate_success(
        api.finalize_reconciliation_report(
            report["id"],
            f.finalize_payload("Turnstile outage at G1 logged with the fire marshal"),
            VENUE_ADMIN,
        )
    )
    assert finalized["status"] == ReportStatus.FINAL
    assert finalized["finalized_by_user_id"] == C.ADMIN_USER_ID
    # The override unlocked the transition without editing the arithmetic.
    assert finalized["variance_pct"] == 200.00

    reconciled = fx.read_event(api, event_id)
    assert reconciled["status"] == EventStatus.RECONCILED

    # A fresh version guard is supplied, so it is the reconciliation rule that refuses.
    validate_error(
        api.create_reconciliation_report(
            event_id,
            f.reconciliation_report_payload(1, reconciled["version"]),
            VENUE_ADMIN,
        ),
        ApiErrorId.EVENT_ALREADY_RECONCILED,
        409,
    )

    _, meta = validate_paginated(
        api.list_reconciliation_reports(SECURITY_INVESTIGATOR, params={"event_id": event_id})
    )
    assert meta["total_count"] == 1

    finalizations = fx.list_audit_entries(
        api, event_id, action=AuditAction.RECONCILIATION_FINALIZED
    )
    assert len(finalizations) == 1

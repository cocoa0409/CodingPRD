"""Two readings of the same stream: occupancy and patron fraud risk.

The same scan stream yields a live head count and a reconciled attendance
figure, and the same incident history yields a provisional and an adjudicated
risk score. Each pair is asserted separately so a single-reading implementation
cannot satisfy both.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    EventStatus,
    FraudRiskBasis,
    GATE_OPERATOR,
    IncidentCategory,
    IncidentStatus,
    SECURITY_INVESTIGATOR,
    ScanResult,
    ScanSource,
    SessionMode,
    SessionStatus,
    constants as C,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

ADA_DEVICE = "DEV-ADA"
BEN_DEVICE = "DEV-BEN"
OFFLINE_SCANNED_AT = "2026-09-12T18:09:00Z"
OFFLINE_EPOCH = 18


def _venue_with_one_online_and_one_offline_admission(api):
    """Ada walks in through the network; Ben's admission arrives from a cache."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )
    ticket_ada = fx.issue_ticket(api, event_id, venue["zone"]["id"], ada["id"])
    ticket_ben = fx.issue_ticket(api, event_id, venue["zone"]["id"], ben["id"])
    fx.bind_device(api, ticket_ada["id"], ada["id"], ADA_DEVICE)
    fx.bind_device(api, ticket_ben["id"], ben["id"], BEN_DEVICE)
    fx.advance_event(api, event_id, EventStatus.DOORS_OPEN)
    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, venue["gate"]["id"], mode=SessionMode.OFFLINE_CAPABLE)

    fx.live_scan(
        api,
        session["id"],
        fx.current_barcode(api, ticket_ada["id"]),
        ADA_DEVICE,
        "S1-ONLINE-001",
    )
    batch = f.offline_batch_payload(
        [
            f.offline_scan_item(
                fx.barcode_at_epoch(api, ticket_ben["id"], OFFLINE_EPOCH),
                BEN_DEVICE,
                "B1",
                OFFLINE_SCANNED_AT,
            )
        ]
    )
    validate_success(api.upload_offline_batch(session["id"], batch, GATE_OPERATOR))

    venue.update(
        {
            "ada": ada,
            "ben": ben,
            "ticket_ada": ticket_ada,
            "ticket_ben": ticket_ben,
            "session": session,
        }
    )
    return venue


def test_live_occupancy_excludes_the_offline_admission_that_reconciled_attendance_counts(api):
    """One online and one offline admission make the two readings disagree by one.

    The live reading replays only `ONLINE` scan events, so the cached admission is
    invisible to it, while the reconciled reading counts admissions from either
    source. PRD: "This is the reading consulted by the capacity preconditions at the turnstile and by the occupancy read endpoint, which means an un-uploaded scanner cache is deliberately invisible to the fire-code gate."
    PRD: "The **reconciled** reading, persisted as a report's `scan_derived_attendance` and surfaced as `reconciled_attendance` on the occupancy read, counts distinct `ticket_id` values across scan events whose `result` is `ADMITTED` regardless of `source`, so offline-replayed scans are included, processed in ascending `scanned_at` order with ascending `recorded_at` as the tie-break."

    Design: Difficulty/dual_variant_calc/occupancy_gate_live_vs_reconciled_variant_divergence
    """
    venue = _venue_with_one_online_and_one_offline_admission(api)

    occupancy = validate_success(
        api.get_event_occupancy(venue["event"]["id"], SECURITY_INVESTIGATOR)
    )

    assert occupancy["live_occupancy"] == 1
    assert occupancy["reconciled_attendance"] == 2
    assert occupancy["peak_live_occupancy"] == 1
    assert occupancy["headroom"] == 199
    # Nobody is still waiting, so the projection clears in no time at all.
    assert occupancy["projected_clearance_minutes"] == 0
    assert len(occupancy["zone_occupancy"]) == 1
    assert occupancy["zone_occupancy"][0]["occupancy_count"] == 1

    session = validate_success(api.get_scan_session(venue["session"]["id"], GATE_OPERATOR))
    assert session["status"] == SessionStatus.SYNCING
    assert session["online_scan_count"] == 1
    assert session["offline_uploaded_count"] == 1

    assert fx.read_ticket(api, venue["ticket_ada"]["id"])["admission_status"] == (
        AdmissionStatus.INSIDE
    )
    assert fx.read_ticket(api, venue["ticket_ben"]["id"])["admission_status"] == (
        AdmissionStatus.INSIDE
    )
    assert fx.read_zone(api, venue["zone"]["id"])["occupancy_count"] == 1


def test_reconciliation_report_is_cut_from_the_reconciled_reading_not_the_live_one(api):
    """Operations counted two, the live figure says one, and the report agrees with two.

    PRD: "At creation the report's derived figures are computed: `scan_derived_attendance` from the reconciled reading of §2.9, `variance_count` as the `reported_attendance` minus `scan_derived_attendance`, `variance_pct` as that variance divided by `scan_derived_attendance`, multiplied by 100 and rounded half up to two decimal places — defined as exactly 0.00 when `scan_derived_attendance` is zero, rather than an error — and `fire_code_breach` set true when `scan_derived_attendance` exceeds the event's `fire_code_capacity`."

    Design: Difficulty/dual_variant_calc/occupancy_gate_live_vs_reconciled_variant_divergence
    """
    venue = _venue_with_one_online_and_one_offline_admission(api)
    event_id = venue["event"]["id"]

    fx.close_scan_session(api, venue["session"]["id"])
    fx.advance_event(api, event_id, EventStatus.IN_PROGRESS)
    fx.advance_event(api, event_id, EventStatus.CLOSED)
    report = fx.create_report(api, event_id, reported_attendance=2)

    assert report["scan_derived_attendance"] == 2
    assert report["variance_count"] == 0
    assert report["variance_pct"] == 0.00
    assert report["fire_code_breach"] is False
    # The live figure never caught up with the cached admission.
    assert fx.read_event(api, event_id)["live_occupancy"] == 1

    events = fx.list_scan_events(api, result=ScanResult.ADMITTED)
    assert len(events) == 2
    assert {row["source"] for row in events} == {ScanSource.ONLINE, ScanSource.OFFLINE_BATCH}


def _venue_with_a_device_mismatch_denial(api):
    """Ada's 14000-cent seat is presented by a device that was never bound."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )
    ticket_ada = fx.issue_ticket(
        api, event_id, venue["zone"]["id"], ada["id"], face_value_cents=14000
    )
    ticket_ben = fx.issue_ticket(
        api, event_id, venue["zone"]["id"], ben["id"], face_value_cents=12000
    )
    fx.bind_device(api, ticket_ada["id"], ada["id"], ADA_DEVICE)
    fx.advance_event(api, event_id, EventStatus.DOORS_OPEN)
    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, venue["gate"]["id"])

    response = fx.denied_scan_response(
        api,
        session["id"],
        fx.current_barcode(api, ticket_ada["id"]),
        "DEV-STOLEN",
        "S1-ONLINE-001",
    )
    validate_error(response, ApiErrorId.DEVICE_MISMATCH, 422)

    incidents = fx.list_incidents(api)
    venue.update(
        {
            "ada": ada,
            "ben": ben,
            "ticket_ada": ticket_ada,
            "ticket_ben": ticket_ben,
            "session": session,
            "incident": incidents[0],
        }
    )
    return venue


def test_provisional_reading_scores_the_open_device_mismatch_at_its_full_weight(api):
    """An unreviewed `DEVICE_MISMATCH` incident scores its whole 45 points.

    PRD: "The `PROVISIONAL` reading — written the instant an incident is created, while nobody has yet reviewed it — adds the churn points to the full weight of every incident whose `status` is `OPEN`, `UNDER_REVIEW` or `REMEDIATED`."

    Design: Difficulty/dual_variant_calc/patron_fraud_score_provisional_vs_adjudicated_variant_divergence
    """
    venue = _venue_with_a_device_mismatch_denial(api)

    ada = fx.read_patron(api, venue["ada"]["id"])
    assert ada["fraud_risk_score"] == 45
    assert ada["fraud_risk_basis"] == FraudRiskBasis.PROVISIONAL
    assert ada["strike_count"] == 1
    assert ada["device_rebind_count"] == 0

    incident = validate_success(
        api.get_denied_entry_incident(venue["incident"]["id"], SECURITY_INVESTIGATOR)
    )
    assert incident["category"] == IncidentCategory.DEVICE_MISMATCH
    assert incident["status"] == IncidentStatus.OPEN
    assert incident["remediation_credit_cents"] is None

    # The other holder's history is untouched by somebody else's denial.
    ben = fx.read_patron(api, venue["ben"]["id"])
    assert ben["strike_count"] == 0
    assert ben["fraud_risk_score"] == 0

    assert fx.read_ticket(api, venue["ticket_ada"]["id"])["admission_status"] == (
        AdmissionStatus.DENIED_FLAGGED
    )


def test_adjudicated_reading_halves_the_remediated_device_mismatch_to_twenty_three(api):
    """Remediation halves the same incident's 45 points and rounds half up to 23.

    PRD: "A single `DEVICE_MISMATCH` incident therefore scores 45 provisionally and 23 once adjudicated."

    Design: Difficulty/dual_variant_calc/patron_fraud_score_provisional_vs_adjudicated_variant_divergence
    """
    venue = _venue_with_a_device_mismatch_denial(api)
    incident_id = venue["incident"]["id"]

    validate_success(api.start_incident_review(incident_id, {}, SECURITY_INVESTIGATOR))
    incident = validate_success(
        api.remediate_incident(incident_id, f.resolution_payload(), SECURITY_INVESTIGATOR)
    )

    assert incident["status"] == IncidentStatus.REMEDIATED
    assert incident["remediation_credit_cents"] == 15600

    ada = fx.read_patron(api, venue["ada"]["id"])
    assert ada["fraud_risk_score"] == 23
    assert ada["fraud_risk_basis"] == FraudRiskBasis.ADJUDICATED
    assert ada["strike_count"] == 1
    assert ada["remediation_credit_cents"] == 15600

    assert fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"] == 10400

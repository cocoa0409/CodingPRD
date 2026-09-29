"""Declared transitions, opening states and the doors that lock behind you.

A ladder that refuses to be skipped, a gate that starts idle, a close that
cannot be replayed, two terminal decisions that will not be revisited, and one
report that legitimately cycles.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    AuditAction,
    BOX_OFFICE_AGENT,
    CredentialRequestStatus,
    DistributionType,
    EventStatus,
    GATE_OPERATOR,
    GateStatus,
    LifecycleStatus,
    ReportStatus,
    SessionStatus,
    TICKETING_APPROVER,
    TransferStatus,
    VENUE_ADMIN,
    constants as C,
    factories as f,
    fixtures as fx,
    make_patron_headers,
    validate_error,
    validate_success,
)


def test_the_event_ladder_refuses_a_skipped_stage_and_the_system_only_status(api):
    """`IN_PROGRESS` and `RECONCILED` are both refused from `DRAFT`; `ON_SALE` is not.

    PRD: "`DRAFT → ON_SALE` requires the event to have at least one access zone and at least one gate; an attempt without both is refused with `ERR_INVALID_STATE`, as is any target that is not the declared successor of the current status."
    PRD: "The final status, `RECONCILED`, is never requested directly: the system sets it when a reconciliation report for the event is finalized, and once the event is `RECONCILED` no further report may be cut, which is reported as `ERR_EVENT_ALREADY_RECONCILED`."
    PRD: "Each accepted advance increments the event's `version` by one."

    Design: Corner/state_machines/event_advance_status_rejects_a_skipped_stage
    """
    event = fx.draft_venue(api)["event"]
    before = fx.read_event(api, event["id"])
    assert before["status"] == EventStatus.DRAFT

    # A legal target later in the chain is not a legal successor now.
    validate_error(
        api.advance_event_status(
            event["id"], f.advance_status_payload(EventStatus.IN_PROGRESS), VENUE_ADMIN
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
    assert fx.read_event(api, event["id"])["status"] == EventStatus.DRAFT

    validate_error(
        api.advance_event_status(
            event["id"], f.advance_status_payload(EventStatus.RECONCILED), VENUE_ADMIN
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
    assert fx.read_event(api, event["id"])["status"] == EventStatus.DRAFT
    assert fx.read_event(api, event["id"])["version"] == before["version"]

    advanced = validate_success(
        api.advance_event_status(
            event["id"], f.advance_status_payload(EventStatus.ON_SALE), VENUE_ADMIN
        )
    )
    assert advanced["status"] == EventStatus.ON_SALE
    # Only the accepted advance moved the version.
    assert advanced["version"] == before["version"] + 1


def test_a_fresh_gate_starts_idle_and_opening_a_session_moves_it_to_scanning(api):
    """The gate's declared opening state, then the four side effects of an open.

    PRD: "Gates begin `IDLE` with `admitted_scan_count` at zero, a null `last_session_closed_at`, and `version` 1."
    PRD: "A successful open creates the session in `OPEN` with `opened_at` set to the logical clock, a null `closed_at`, and `online_scan_count`, `offline_uploaded_count` and `duplicate_suppressed_count` all at zero; the gate moves `IDLE → SCANNING` and its `version` increments."

    Design: Corner/state_machines/gate_initial_state_and_session_open_side_effects
    """
    event = fx.create_event(api)
    zone = fx.create_zone(api, event["id"])
    gate = fx.create_gate(api, event["id"], zone["id"])

    assert gate["status"] == GateStatus.IDLE
    assert gate["admitted_scan_count"] == 0
    assert gate["last_session_closed_at"] is None
    assert gate["version"] == 1

    fx.advance_event_to(api, event["id"], EventStatus.DOORS_OPEN)
    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, gate["id"])

    assert session["status"] == SessionStatus.OPEN
    assert session["opened_at"] == C.T_18_10_00
    assert session["closed_at"] is None
    assert session["online_scan_count"] == 0
    assert session["offline_uploaded_count"] == 0
    assert session["duplicate_suppressed_count"] == 0

    scanning = fx.read_gate(api, gate["id"])
    assert scanning["status"] == GateStatus.SCANNING
    # The next open must carry this new version, which is why the open bumps it.
    assert scanning["version"] == 2
    assert scanning["last_session_closed_at"] is None


def test_a_second_close_of_the_same_session_is_refused_rather_than_absorbed(api):
    """The replay is an undeclared transition, and it touches neither row.

    PRD: "Closing a session that is already `CLOSED` is not a declared transition and is refused with `ERR_INVALID_STATE`."
    PRD: "It sets the session's `status` to `CLOSED` and its `closed_at` to the logical clock, moves the gate `SCANNING → IDLE`, copies that `closed_at` onto the gate's `last_session_closed_at`, and increments the gate's `version`."

    Design: Corner/state_machines/scan_session_second_close_is_rejected_as_a_terminal_state
    """
    venue = fx.doors_open_venue(api)
    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, venue["gate"]["id"])

    fx.set_clock(api, C.T_18_12_00)
    closed = fx.close_scan_session(api, session["id"])
    assert closed["status"] == SessionStatus.CLOSED
    assert closed["closed_at"] == C.T_18_12_00

    validate_error(
        api.close_scan_session(session["id"], {}, GATE_OPERATOR),
        ApiErrorId.INVALID_STATE,
        409,
    )

    gate = fx.read_gate(api, venue["gate"]["id"])
    assert gate["status"] == GateStatus.IDLE
    assert gate["last_session_closed_at"] == C.T_18_12_00

    replayed = validate_success(api.get_scan_session(session["id"], GATE_OPERATOR))
    assert replayed["closed_at"] == C.T_18_12_00
    # A refused transition is not a mutation.
    assert replayed["version"] == closed["version"]


def test_a_declined_offer_cannot_be_accepted_afterwards(api):
    """`DECLINED` is terminal, so the recipient's change of heart is refused.

    PRD: "It requires the offer to be `PENDING`, moves it `PENDING → DECLINED`, stamps `decided_at` with the logical clock, and leaves the ticket entirely untouched: `holder_patron_id` is unchanged, `lifecycle_status` is unchanged, `transfer_count` does not move, the device binding is not released and the ticket's `version` does not increment."
    PRD: "Both `ACCEPTED` and `DECLINED` are terminal, so re-deciding an already-decided offer is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/transfer_request_decline_is_terminal_so_a_later_accept_is_rejected
    """
    venue = fx.two_patron_venue(api)
    holder = make_patron_headers(venue["holder"]["id"])
    recipient = make_patron_headers(venue["other"]["id"])

    offer = validate_success(
        api.create_transfer_request(
            f.transfer_request_payload(venue["ticket"]["id"], venue["other"]["id"]), holder
        ),
        201,
    )
    assert offer["status"] == TransferStatus.PENDING
    # The sender is derived from the ticket's holder rather than taken from the body.
    assert offer["from_patron_id"] == venue["holder"]["id"]
    assert offer["to_patron_id"] == venue["other"]["id"]

    declined = validate_success(api.decline_transfer_request(offer["id"], {}, recipient))
    assert declined["status"] == TransferStatus.DECLINED
    assert declined["decided_at"] == C.CLOCK_EPOCH_START

    validate_error(
        api.accept_transfer_request(offer["id"], {}, recipient),
        ApiErrorId.INVALID_STATE,
        409,
    )

    ticket = fx.read_ticket(api, venue["ticket"]["id"])
    assert ticket["holder_patron_id"] == venue["holder"]["id"]
    assert ticket["transfer_count"] == 0
    assert ticket["lifecycle_status"] == LifecycleStatus.ISSUED
    assert ticket["version"] == venue["ticket"]["version"]


def test_a_rejected_credential_request_can_neither_be_approved_nor_resubmitted(api):
    """Rejection is terminal, and nothing downstream of it ever minted a pass.

    PRD: "**Rejecting** it requires the request to be `SUBMITTED` and the approver's `X-User-ID` to differ from `requested_by_user_id`; it takes a `note`, moves the request to `REJECTED`, stamps `approved_by_user_id` with the approver's identifier, issues no ticket whatsoever, and appends `CREDENTIAL_REQUEST_REJECTED`."
    PRD: "9. The acted-on resource is in a state from which this operation is declared — `ERR_INVALID_STATE` (409), on every action endpoint."
    PRD: "A draft opens in `DRAFT` with `revision_count` and `issued_ticket_count` at zero, `forgone_revenue_cents` at zero, and `requested_by_user_id` and `approved_by_user_id` both null."

    Design: Corner/state_machines/credential_request_rejection_is_terminal_and_blocks_approval
    """
    venue = fx.on_sale_venue(api)
    ada = fx.register_patron(api)
    draft = fx.create_credential_draft(
        api,
        venue["event"]["id"],
        venue["zone"]["id"],
        ada["id"],
        distribution_type=DistributionType.COMP,
        quantity=2,
        valid_from="2026-09-12T18:00:00Z",
        valid_until="2026-09-12T22:00:00Z",
        justification="Sponsor hosting",
    )
    assert draft["status"] == CredentialRequestStatus.DRAFT
    assert draft["requested_by_user_id"] is None
    assert draft["revision_count"] == 0

    submitted = fx.submit_credential_request(api, draft["id"])
    assert submitted["status"] == CredentialRequestStatus.SUBMITTED

    rejected = validate_success(
        api.reject_credential_request(
            draft["id"], f.note_payload("Not a sponsored night"), TICKETING_APPROVER
        )
    )
    assert rejected["status"] == CredentialRequestStatus.REJECTED
    assert rejected["approved_by_user_id"] == C.APPROVER_USER_ID

    validate_error(
        api.approve_credential_request(
            draft["id"], f.note_payload("Reconsidered"), TICKETING_APPROVER
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.submit_credential_request(draft["id"], {}, BOX_OFFICE_AGENT),
        ApiErrorId.INVALID_STATE,
        409,
    )

    final = validate_success(api.get_credential_request(draft["id"], TICKETING_APPROVER))
    assert final["issued_ticket_count"] == 0
    assert final["forgone_revenue_cents"] == 0
    assert fx.read_zone(api, venue["zone"]["id"])["issued_entitlement_count"] == 0
    assert fx.read_event(api, venue["event"]["id"])["entitlements_outstanding"] == 0


def _closed_event_with_two_admissions(api):
    """Two patrons scanned in at 18:10:00, the session closed and the event `CLOSED`."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )
    ticket_ada = fx.issue_ticket(api, event_id, venue["zone"]["id"], ada["id"])
    ticket_ben = fx.issue_ticket(api, event_id, venue["zone"]["id"], ben["id"])
    fx.bind_device(api, ticket_ada["id"], ada["id"], "DEV-ADA")
    fx.bind_device(api, ticket_ben["id"], ben["id"], "DEV-BEN")
    fx.advance_event(api, event_id, EventStatus.DOORS_OPEN)

    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, venue["gate"]["id"])
    fx.admit_ticket(api, session["id"], ticket_ada["id"], "DEV-ADA", "S1-001")
    fx.admit_ticket(api, session["id"], ticket_ben["id"], "DEV-BEN", "S1-002")
    for ticket in (ticket_ada, ticket_ben):
        assert fx.read_ticket(api, ticket["id"])["admission_status"] == AdmissionStatus.INSIDE

    venue["event"] = fx.close_event(api, event_id, [session["id"]])
    venue.update({"ada": ada, "ben": ben, "session": session})
    return venue


def test_reopening_a_final_report_returns_the_event_to_closed_and_refinalizing_restores_it(api):
    """The report's `FINAL → REOPENED → FINAL` loop drives the event in both directions.

    PRD: "Finalization recomputes `scan_derived_attendance`, `variance_count`, `variance_pct` and `fire_code_breach` afresh rather than trusting the figures cut at creation, sets `status` to `FINAL`, stamps `finalized_by_user_id` with the admin's `X-User-ID`, drives the event's `status` to `RECONCILED`, and appends an audit entry with the action `RECONCILIATION_FINALIZED`."
    PRD: "It moves the report `FINAL → REOPENED`, takes a `reason` for the correction, clears `finalized_by_user_id` back to null, and returns the event's `status` to `CLOSED` so that the reconciliation can be re-cut."
    PRD: "A `REOPENED` report finalizes again under precisely the same tolerance rule and produces precisely the same side effects as a first finalization, including driving the event back to `RECONCILED`."

    Design: Corner/state_machines/reconciliation_reopen_then_refinalize_recycles_the_event_status
    """
    venue = _closed_event_with_two_admissions(api)
    event_id = venue["event"]["id"]
    assert venue["event"]["status"] == EventStatus.CLOSED

    report = fx.create_report(api, event_id, 2)
    assert report["status"] == ReportStatus.DRAFT
    assert report["scan_derived_attendance"] == 2
    assert report["variance_count"] == 0
    assert report["variance_pct"] == 0.00
    assert report["fire_code_breach"] is False

    finalized = validate_success(
        api.finalize_reconciliation_report(report["id"], f.finalize_payload(), VENUE_ADMIN)
    )
    assert finalized["status"] == ReportStatus.FINAL
    assert finalized["finalized_by_user_id"] == C.ADMIN_USER_ID
    assert fx.read_event(api, event_id)["status"] == EventStatus.RECONCILED

    reopened = validate_success(
        api.reopen_reconciliation_report(
            report["id"], f.reopen_payload("Turnstile log arrived late"), VENUE_ADMIN
        )
    )
    assert reopened["status"] == ReportStatus.REOPENED
    assert reopened["finalized_by_user_id"] is None
    assert fx.read_event(api, event_id)["status"] == EventStatus.CLOSED

    refinalized = validate_success(
        api.finalize_reconciliation_report(report["id"], f.finalize_payload(), VENUE_ADMIN)
    )
    assert refinalized["status"] == ReportStatus.FINAL
    assert refinalized["finalized_by_user_id"] == C.ADMIN_USER_ID
    assert fx.read_event(api, event_id)["status"] == EventStatus.RECONCILED
    # Reopening did not clear the derived figures.
    assert refinalized["scan_derived_attendance"] == 2

    finalizations = fx.list_audit_entries(
        api, event_id, subject_id=report["id"], action=AuditAction.RECONCILIATION_FINALIZED
    )
    assert len(finalizations) == 2

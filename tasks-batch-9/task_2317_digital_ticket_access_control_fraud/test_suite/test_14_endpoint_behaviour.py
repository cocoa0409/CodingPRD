"""What each endpoint answers with, and what it quietly did on the way.

A bulk upload that half succeeds and then locks its own session, four binding
writes that price a patron out slowly, a computed read taken mid-queue, a trail
nobody can write to directly, and a link validated three different ways.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    AuditAction,
    AuditSubjectType,
    DeviceBindingStatus,
    EventStatus,
    GATE_OPERATOR,
    GateStatus,
    LifecycleStatus,
    ListingStatus,
    Marketplace,
    NON_EXISTENT_UUID,
    Role,
    SECURITY_INVESTIGATOR,
    ScanDirection,
    ScanResult,
    ScanSource,
    SessionMode,
    SessionStatus,
    VENUE_ADMIN,
    ZonePosture,
    constants as C,
    factories as f,
    fixtures as fx,
    make_patron_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CACHED_AT_EPOCH_18 = C.EPOCH_AT_18_09_00


def _two_bound_tickets_and_a_session(api, mode=SessionMode.OFFLINE_CAPABLE):
    """Ada and Bob hold bound tickets; a session of ``mode`` is open at 18:10:00."""
    event = fx.create_event(api)
    zone = fx.create_zone(api, event["id"], fire_code_capacity=150)
    gate = fx.create_gate(api, event["id"], zone["id"], throughput_per_minute=20, lanes_open=2)
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)

    ada = fx.register_patron(api)
    bob = fx.register_patron(
        api, email="bob@example.com", display_name="Bob Stone", document_reference="DL-BOB-1"
    )
    ticket_ada = fx.issue_ticket(api, event["id"], zone["id"], ada["id"])
    ticket_bob = fx.issue_ticket(api, event["id"], zone["id"], bob["id"])
    fx.bind_device(api, ticket_ada["id"], ada["id"], "DEV-ADA")
    fx.bind_device(api, ticket_bob["id"], bob["id"], "DEV-BOB")
    event = fx.advance_event(api, event["id"], EventStatus.DOORS_OPEN)

    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, gate["id"], mode=mode)
    return {
        "event": event,
        "zone": zone,
        "gate": gate,
        "ada": ada,
        "bob": bob,
        "ticket_ada": ticket_ada,
        "ticket_bob": ticket_bob,
        "session": session,
    }


def _upload_three_cached_items(api, venue):
    """Upload Ada twice and Bob once, all captured a minute before the clock."""
    seed_ada = fx.get_barcode(api, venue["ticket_ada"]["id"])["barcode_seed"]
    seed_bob = fx.get_barcode(api, venue["ticket_bob"]["id"])["barcode_seed"]

    return validate_success(
        api.upload_offline_batch(
            venue["session"]["id"],
            f.offline_batch_payload(
                [
                    f.offline_scan_item(
                        f"{seed_ada}-{CACHED_AT_EPOCH_18}", "DEV-ADA", "B1", C.T_18_09_00
                    ),
                    f.offline_scan_item(
                        f"{seed_ada}-{CACHED_AT_EPOCH_18}", "DEV-ADA", "B2", C.T_18_09_10
                    ),
                    f.offline_scan_item(
                        f"{seed_bob}-{CACHED_AT_EPOCH_18}", "DEV-BOB", "B3", C.T_18_09_20
                    ),
                ]
            ),
            GATE_OPERATOR,
        )
    )


def test_an_upload_of_three_items_admits_two_suppresses_one_and_then_locks_the_session(api):
    """Two admits and a duplicate, each judged at its own instant, then no more live scans.

    PRD: "`accepted_count` counts items adjudicated `ADMITTED` or `EXIT_RECORDED`."
    PRD: "`duplicate_suppressed_count` counts items adjudicated `DENIED_DUPLICATE`."
    PRD: "`denied_count` counts *every* non-admitted item, duplicates included, so `accepted_count` plus `denied_count` always equals the number of items submitted."
    PRD: "`scan_event_ids` holds one identifier per item in adjudication order."
    PRD: "Items are adjudicated in ascending `scanned_at` order, tie-broken by their position in the array, and the upload is best-effort per item: a failing item is recorded rather than aborting the batch."
    PRD: "Unlike a live scan, `scanned_at` is mandatory on every item, and it is the instant against which that item's barcode epoch is evaluated — which is precisely why a cache recorded before the uplink came back is still accepted."
    PRD: "Each item is persisted as a scan event with `source` `OFFLINE_BATCH`, a `recorded_at` of the logical clock and a `scanned_at` of the item's own client instant."
    PRD: "A duplicate entry scan on a ticket that is already `INSIDE` moves it `INSIDE → DENIED_FLAGGED`, persists a scan event with `result` `DENIED_DUPLICATE` and `denied_reason_code` of `ERR_DUPLICATE_SCAN`, opens a `DUPLICATE` incident, and leaves the occupancy counters alone."
    PRD: "Taking an upload moves the session `OPEN → SYNCING`, after which it accepts no further live scan and reports `ERR_SESSION_NOT_OPEN`; a second upload against a `SYNCING` or `CLOSED` session is not a declared transition and is refused with `ERR_INVALID_STATE`."

    Design: Corner/endpoints/offline_batch_is_best_effort_per_item_and_then_locks_the_session
    """
    venue = _two_bound_tickets_and_a_session(api)
    receipt = _upload_three_cached_items(api, venue)

    assert receipt["accepted_count"] == 2
    assert receipt["duplicate_suppressed_count"] == 1
    # The duplicate is counted twice over, which is why the two counts sum to three.
    assert receipt["denied_count"] == 1
    assert receipt["accepted_count"] + receipt["denied_count"] == 3

    ids = receipt["scan_event_ids"]
    assert len(ids) == 3
    persisted = [
        validate_success(api.get_scan_event(event_id, SECURITY_INVESTIGATOR))
        for event_id in ids
    ]

    # Adjudication order is the ascending cache order, so the ids come back in it.
    assert [row["scanned_at"] for row in persisted] == [
        C.T_18_09_00,
        C.T_18_09_10,
        C.T_18_09_20,
    ]
    # An epoch-18 cache is judged against 18:09, not against the 18:10 clock.
    assert [row["result"] for row in persisted] == [
        ScanResult.ADMITTED,
        ScanResult.DENIED_DUPLICATE,
        ScanResult.ADMITTED,
    ]
    assert persisted[1]["denied_reason_code"] == ApiErrorId.DUPLICATE_SCAN
    assert all(row["source"] == ScanSource.OFFLINE_BATCH for row in persisted)
    # The client instants were kept; only the recording instant is the server's.
    assert all(row["recorded_at"] == C.T_18_10_00 for row in persisted)
    assert [row["ticket_id"] for row in persisted] == [
        venue["ticket_ada"]["id"],
        venue["ticket_ada"]["id"],
        venue["ticket_bob"]["id"],
    ]

    synced = validate_success(api.get_scan_session(venue["session"]["id"], GATE_OPERATOR))
    assert synced["status"] == SessionStatus.SYNCING

    # A syncing session takes no further live scan, whatever the barcode says.
    validate_error(
        fx.denied_scan_response(
            api,
            venue["session"]["id"],
            fx.current_barcode(api, venue["ticket_ada"]["id"]),
            "DEV-ADA",
            "K9",
            direction=ScanDirection.OUT,
        ),
        ApiErrorId.SESSION_NOT_OPEN,
        409,
    )


def test_an_uploaded_cache_moves_no_live_counter_and_still_flags_the_duplicate(api):
    """Two people are inside by the reconciled reading and nought by the live one.

    PRD: "Admitted items set the ticket's `admission_status` to `INSIDE` and refresh its `last_admitted_at`, but they leave the event's `live_occupancy` and the zone's `occupancy_count` untouched, because the live reading excludes offline-sourced scans — they surface only in the reconciled reading."
    PRD: "The **reconciled** reading, persisted as a report's `scan_derived_attendance` and surfaced as `reconciled_attendance` on the occupancy read, counts distinct `ticket_id` values across scan events whose `result` is `ADMITTED` regardless of `source`, so offline-replayed scans are included, processed in ascending `scanned_at` order with ascending `recorded_at` as the tie-break."
    PRD: "A duplicate entry scan on a ticket that is already `INSIDE` moves it `INSIDE → DENIED_FLAGGED`, persists a scan event with `result` `DENIED_DUPLICATE` and `denied_reason_code` of `ERR_DUPLICATE_SCAN`, opens a `DUPLICATE` incident, and leaves the occupancy counters alone."
    PRD: "When a fraud-bearing denial does open an incident, the cascade runs in four links within the same request: the incident is created in `OPEN`; the holder's `strike_count` rises by one and their `fraud_risk_score` is recomputed under the provisional reading; if that recomputed score reaches 40, every `LISTED` listing of that patron is suspended; and each suspended listing reverts its ticket's `lifecycle_status` to `ISSUED`."
    PRD: "The second is the patron's denied-entry history, where each incident contributes points according to its `category`: `COUNTERFEIT` weighs 50, `DEVICE_MISMATCH` weighs 45, `UNAUTHORIZED_RESALE` weighs 30, `DUPLICATE` weighs 20 and `ZONE_VIOLATION` weighs 15."
    PRD: "On the session itself, `offline_uploaded_count` counts every item persisted whatever its result, `online_scan_count` counts the session's scan events whose `source` is `ONLINE`, and the session's own `duplicate_suppressed_count` counts every scan event in the session whose `result` is `DENIED_DUPLICATE`."

    Design: Corner/endpoints/offline_batch_is_best_effort_per_item_and_then_locks_the_session
    """
    venue = _two_bound_tickets_and_a_session(api)
    _upload_three_cached_items(api, venue)

    occupancy = fx.read_occupancy(api, venue["event"]["id"])
    # The fire-code gate deliberately cannot see an uploaded cache.
    assert occupancy["live_occupancy"] == 0
    assert occupancy["peak_live_occupancy"] == 0
    assert occupancy["reconciled_attendance"] == 2
    assert fx.read_zone(api, venue["zone"]["id"])["occupancy_count"] == 0

    # Ada's second item found her already inside; Bob's single item stands.
    assert (
        fx.read_ticket(api, venue["ticket_ada"]["id"])["admission_status"]
        == AdmissionStatus.DENIED_FLAGGED
    )
    assert (
        fx.read_ticket(api, venue["ticket_bob"]["id"])["admission_status"]
        == AdmissionStatus.INSIDE
    )

    ada = fx.read_patron(api, venue["ada"]["id"])
    assert ada["strike_count"] == 1
    assert ada["fraud_risk_score"] == C.CATEGORY_WEIGHTS["DUPLICATE"]
    bob = fx.read_patron(api, venue["bob"]["id"])
    # Bob was admitted, so nothing was booked against him.
    assert bob["strike_count"] == 0
    assert bob["fraud_risk_score"] == 0

    session = validate_success(api.get_scan_session(venue["session"]["id"], GATE_OPERATOR))
    assert session["offline_uploaded_count"] == 3
    assert session["duplicate_suppressed_count"] == 1
    assert session["online_scan_count"] == 0


def test_the_first_binding_is_free_and_only_the_second_rebind_costs_anything(api):
    """Bind, release, bind, bind: rebinds of nought, one and two scoring 0, 0 and 4.

    PRD: "A `Patron` binds a `device_fingerprint` to a ticket they hold, which sets that ticket's `bound_device_fingerprint` and moves its `device_binding_status` from `UNBOUND` to `BOUND`."
    PRD: "A holder who changes phones releases the binding, which clears `bound_device_fingerprint` to null and sets `device_binding_status` to `RELEASED`; a released ticket is as unscannable as an unbound one until a new device is bound."
    PRD: "Binding and releasing each increment the ticket's `version`."
    PRD: "Whenever a device is bound to a ticket whose `device_binding_status` was already `BOUND` or `RELEASED` — that is, on any binding after the first on that ticket — the holder's `device_rebind_count` increases by one and their `fraud_risk_score` is immediately recomputed under the provisional reading described in §2.10."
    PRD: "The first is device churn: a patron's `device_rebind_count` counts every time they have bound a device to a ticket *after* the first binding on that ticket, and churn contributes four points for each rebind beyond the first — formally, four multiplied by the greater of zero and one less than `device_rebind_count`."

    Design: Corner/endpoints/device_binding_release_and_rebinding_accumulate_churn_points
    """
    venue = fx.on_sale_venue(api)
    ada = fx.register_patron(api)
    ticket = fx.issue_ticket(api, venue["event"]["id"], venue["zone"]["id"], ada["id"])
    assert ticket["device_binding_status"] == DeviceBindingStatus.UNBOUND
    assert ticket["version"] == 1

    first = fx.bind_device(api, ticket["id"], ada["id"], "DEV-PHONE-1")
    assert first["device_binding_status"] == DeviceBindingStatus.BOUND
    assert first["bound_device_fingerprint"] == "DEV-PHONE-1"
    assert first["version"] == 2

    after_first = fx.read_patron(api, ada["id"])
    # There was no previous binding on this ticket, so this was not a rebind.
    assert after_first["device_rebind_count"] == 0
    assert after_first["fraud_risk_score"] == 0

    released = fx.release_device(api, ticket["id"], ada["id"])
    assert released["device_binding_status"] == DeviceBindingStatus.RELEASED
    assert released["bound_device_fingerprint"] is None

    second = fx.bind_device(api, ticket["id"], ada["id"], "DEV-PHONE-2")
    assert second["device_binding_status"] == DeviceBindingStatus.BOUND
    assert second["bound_device_fingerprint"] == "DEV-PHONE-2"

    after_second = fx.read_patron(api, ada["id"])
    assert after_second["device_rebind_count"] == 1
    # Four times the greater of zero and one less than one is nothing at all.
    assert after_second["fraud_risk_score"] == 0

    third = fx.bind_device(api, ticket["id"], ada["id"], "DEV-PHONE-3")
    assert third["device_binding_status"] == DeviceBindingStatus.BOUND
    # Four writes on the ticket, each worth exactly one version.
    assert third["version"] == 5

    after_third = fx.read_patron(api, ada["id"])
    assert after_third["device_rebind_count"] == 2
    assert after_third["fraud_risk_score"] == C.DEVICE_CHURN_WEIGHT
    # Churn is not a strike; nobody was denied at a turnstile.
    assert after_third["strike_count"] == 0


def test_the_occupancy_read_measures_headroom_at_the_event_and_rounds_the_queue_up(api):
    """One of two admitted: headroom 199 against the venue and a projection of one minute.

    PRD: "Total capacity per minute is the sum, over scanning gates, of each gate's `throughput_per_minute` multiplied by its `lanes_open`."
    PRD: "The waiting population is the number of the event's tickets whose `lifecycle_status` is `ISSUED`, `LISTED`, `TRANSFERRED` or `RESOLD` and whose `admission_status` is still `NOT_ADMITTED`."
    PRD: "`projected_clearance_minutes` is the waiting population divided by the capacity per minute, rounded *up* to a whole minute; when no gate is scanning, and therefore capacity per minute is zero, `projected_clearance_minutes` is null rather than an error."
    PRD: "Alongside it the read reports the event's `event_id`, `live_occupancy`, `peak_live_occupancy`, `reconciled_attendance`, `fire_code_capacity`, the `headroom` remaining (the event's fire-code capacity less its live occupancy), and a `zone_occupancy` array carrying, for each access zone of the event, that zone's `id`, `zone_code`, `occupancy_count` and `fire_code_capacity`."
    PRD: "Admission moves the ticket `NOT_ADMITTED → INSIDE`, refreshes `last_admitted_at` and increments the ticket's `admitted_scan_count`, raises the zone's `occupancy_count` and the event's `live_occupancy` by one each, raises the event's `peak_live_occupancy` whenever the new live figure exceeds it, and increments the gate's `admitted_scan_count` and the session's `online_scan_count`."
    PRD: "The **reconciled** reading, persisted as a report's `scan_derived_attendance` and surfaced as `reconciled_attendance` on the occupancy read, counts distinct `ticket_id` values across scan events whose `result` is `ADMITTED` regardless of `source`, so offline-replayed scans are included, processed in ascending `scanned_at` order with ascending `recorded_at` as the tie-break."

    Design: Corner/endpoints/occupancy_read_reports_headroom_and_a_finite_clearance_projection
    """
    venue = _two_bound_tickets_and_a_session(api, mode=SessionMode.ONLINE)
    fx.admit_ticket(api, venue["session"]["id"], venue["ticket_ada"]["id"], "DEV-ADA", "K1")

    read = fx.read_occupancy(api, venue["event"]["id"])

    assert read["event_id"] == venue["event"]["id"]
    assert read["live_occupancy"] == 1
    assert read["peak_live_occupancy"] == 1
    assert read["reconciled_attendance"] == 1

    # The ceiling is the venue's, not the zone's.
    assert read["fire_code_capacity"] == 200
    assert read["headroom"] == 199
    # Bob is the whole queue, and one person over forty a minute rounds up to one.
    assert read["projected_clearance_minutes"] == 1

    assert len(read["zone_occupancy"]) == 1
    row = read["zone_occupancy"][0]
    assert row["id"] == venue["zone"]["id"]
    assert row["occupancy_count"] == 1
    assert row["fire_code_capacity"] == 150
    # Two entitlements against a hundred and fifty places is nowhere near the band.
    assert fx.read_zone(api, venue["zone"]["id"])["posture"] == ZonePosture.OPEN

    assert fx.read_gate(api, venue["gate"]["id"])["admitted_scan_count"] == 1
    assert (
        fx.read_ticket(api, venue["ticket_bob"]["id"])["admission_status"]
        == AdmissionStatus.NOT_ADMITTED
    )


def _listed_then_voided_a_day_later(api):
    """Ada lists at the epoch instant; a day later the investigator voids the ticket."""
    venue = fx.on_sale_venue(api)
    ada = fx.register_patron(api)
    ticket = fx.issue_ticket(
        api, venue["event"]["id"], venue["zone"]["id"], ada["id"], face_value_cents=12000
    )
    listing = validate_success(
        api.create_resale_listing(
            f.resale_listing_payload(
                ticket["id"], 12000, ticket["version"], marketplace=Marketplace.VERIFIED_PARTNER
            ),
            make_patron_headers(ada["id"]),
        ),
        201,
    )

    fx.set_clock(api, "2026-08-02T00:00:00Z")
    voided = fx.void_ticket(
        api, ticket["id"], refund_to_holder=True, reason="Chargeback confirmed"
    )
    assert voided["lifecycle_status"] == LifecycleStatus.VOIDED

    venue.update({"ada": ada, "ticket": ticket, "listing": listing})
    return venue


def test_the_trail_comes_back_newest_first_with_the_acting_role_on_every_row(api):
    """A listing, a void and the suspension the void forced, ordered by their instants.

    PRD: "An entry records the `event_id` it belongs to, a polymorphic pair of `subject_type` — one of `CREDENTIAL_REQUEST`, `TICKET`, `RESALE_LISTING`, `DENIED_ENTRY_INCIDENT` or `RECONCILIATION_REPORT` — and `subject_id` identifying the audited row, the `action` verb, the `actor_role` and `actor_user_id` of whoever acted, the `occurred_at` logical instant, and a human-readable `detail` summarizing amounts and the state transition."
    PRD: "Two endpoints override that default: the scan-event list is ordered by `recorded_at` ascending with `created_at` ascending as the tie-break, and the event audit trail is ordered newest-first by `occurred_at` descending with `created_at` descending as the tie-break."
    PRD: "Listing moves the ticket `ISSUED → LISTED` (or `TRANSFERRED → LISTED` for a ticket that has changed hands), opens the listing in `LISTED` with `platform_fee_cents`, `venue_royalty_cents`, `processing_fee_cents` and `seller_payout_cents` all null, increments the ticket's `version`, and appends an audit entry with the action `RESALE_LISTED` against `subject_type` `RESALE_LISTING`."
    PRD: "Every void appends an audit entry with `subject_type` `TICKET` and the action `TICKET_VOIDED`."
    PRD: "When a denied-entry incident is created against a patron and their recomputed `fraud_risk_score` reaches 40, or when a ticket carrying a live listing is voided, every `LISTED` listing of that seller moves `LISTED → SUSPENDED` and an audit entry with the action `RESALE_LISTING_SUSPENDED` is appended."

    Design: Corner/endpoints/audit_trail_is_append_only_newest_first_and_filterable
    """
    venue = _listed_then_voided_a_day_later(api)

    entries, meta = validate_paginated(
        api.list_audit_log_entries(venue["event"]["id"], SECURITY_INVESTIGATOR)
    )
    # One row for the listing, and two for the void and the suspension it forced.
    assert meta["total_count"] == 3

    instants = [entry["occurred_at"] for entry in entries]
    assert instants == sorted(instants, reverse=True)
    assert instants[0] == "2026-08-02T00:00:00Z"

    # The oldest row is the listing, cut a day earlier by the patron herself.
    oldest = entries[-1]
    assert oldest["occurred_at"] == C.CLOCK_EPOCH_START
    assert oldest["action"] == AuditAction.RESALE_LISTED
    assert oldest["subject_type"] == AuditSubjectType.RESALE_LISTING
    assert oldest["subject_id"] == venue["listing"]["id"]
    assert oldest["actor_role"] == Role.PATRON
    assert oldest["actor_user_id"] == venue["ada"]["id"]
    assert oldest["event_id"] == venue["event"]["id"]

    actions = {entry["action"] for entry in entries}
    assert actions == {
        AuditAction.RESALE_LISTED,
        AuditAction.TICKET_VOIDED,
        AuditAction.RESALE_LISTING_SUSPENDED,
    }

    void_row = next(
        entry for entry in entries if entry["action"] == AuditAction.TICKET_VOIDED
    )
    assert void_row["subject_type"] == AuditSubjectType.TICKET
    assert void_row["subject_id"] == venue["ticket"]["id"]
    assert void_row["actor_role"] == Role.SECURITY_INVESTIGATOR
    assert void_row["actor_user_id"] == C.INVESTIGATOR_USER_ID

    assert (
        validate_success(api.get_resale_listing(venue["listing"]["id"], VENUE_ADMIN))["status"]
        == ListingStatus.SUSPENDED
    )


def test_the_trail_narrows_by_subject_type_and_by_action_and_carries_no_version(api):
    """Two rows about the listing, one about the void, and no mutable fields anywhere.

    PRD: "The trail is readable by `SecurityInvestigator` and `VenueAdmin` and may be narrowed by `subject_type`, `subject_id` and `action`."
    PRD: "Two record types are append-only and therefore carry neither `updated_at` nor `version`: the immutable scan event, and the audit log entry."
    PRD: "Both expose only `id` and `created_at` on top of their domain fields."
    PRD: "`total_count` is the number of rows matching the supplied filters *before* `limit` and `offset` are applied, and `has_more` is true exactly when `offset` plus the number of returned rows is still less than `total_count`."

    Design: Corner/endpoints/audit_trail_is_append_only_newest_first_and_filterable
    """
    venue = _listed_then_voided_a_day_later(api)

    listing_rows, listing_meta = validate_paginated(
        api.list_audit_log_entries(
            venue["event"]["id"],
            VENUE_ADMIN,
            params={"subject_type": AuditSubjectType.RESALE_LISTING},
        )
    )
    # Both the listing and its forced suspension are audited against the listing.
    assert listing_meta["total_count"] == 2
    assert {row["subject_id"] for row in listing_rows} == {venue["listing"]["id"]}
    assert {row["action"] for row in listing_rows} == {
        AuditAction.RESALE_LISTED,
        AuditAction.RESALE_LISTING_SUSPENDED,
    }

    void_rows, void_meta = validate_paginated(
        api.list_audit_log_entries(
            venue["event"]["id"],
            VENUE_ADMIN,
            params={"action": AuditAction.TICKET_VOIDED, "limit": 1, "offset": 0},
        )
    )
    assert void_meta["total_count"] == 1
    # One row matched and one row was returned, so nothing is left behind the window.
    assert void_meta["has_more"] is False
    assert len(void_rows) == 1
    assert void_rows[0]["subject_id"] == venue["ticket"]["id"]

    for row in listing_rows + void_rows:
        assert "id" in row
        assert "created_at" in row
        assert "version" not in row
        assert "updated_at" not in row


def test_a_gate_may_only_serve_a_zone_of_its_own_event_and_only_while_drafting(api):
    """Missing, cross-event, accepted, then refused once the event went on sale.

    PRD: "5. Body identifier fields resolve — the referenced collection's own not-found error (404), for example `ERR_ZONE_NOT_FOUND` for an unresolved `access_zone_id` and `ERR_PATRON_NOT_FOUND` for an unresolved `holder_patron_id`; applies on direct ticket issuance, gate creation, transfer creation, resale listing creation, credential-request drafting and scan-session opening."
    PRD: "6. Referenced zone or gate belongs to the same event — `ERR_CROSS_EVENT_REFERENCE` (422), on direct ticket issuance, gate creation and credential-request drafting."
    PRD: "13. The event's `status` permits the operation — `ERR_EVENT_STATE_FORBIDS_OPERATION` (409). Access-zone and gate creation require `DRAFT`; direct issuance and credential submission and approval require `ON_SALE` or `DOORS_OPEN`; scanning and offline upload require `DOORS_OPEN` or `IN_PROGRESS`; cutting a reconciliation report requires `CLOSED` or `RECONCILED`."
    PRD: "It carries a `gate_code` unique within the event, an `access_zone_id` naming the zone it admits into, a rated `throughput_per_minute` of at least 1 for one open lane, and an optional `lanes_open` count of at least 1 that defaults to 1."
    PRD: "Gates filter by `event_id`, `access_zone_id` and `status`."

    Design: Corner/endpoints/gate_links_to_a_zone_of_the_same_event_only
    """
    first = fx.create_event(api)
    zone_one = fx.create_zone(api, first["id"])
    second = fx.create_event(api, name="Boreal Matinee")
    zone_two = fx.create_zone(api, second["id"])

    payload = f.gate_payload(NON_EXISTENT_UUID, gate_code="GX")
    payload.pop("lanes_open")
    validate_error(
        api.create_gate(first["id"], payload, VENUE_ADMIN),
        ApiErrorId.ZONE_NOT_FOUND,
        404,
    )

    # This one resolves perfectly well; it simply belongs to the other event.
    validate_error(
        api.create_gate(
            first["id"], f.gate_payload(zone_two["id"], gate_code="GX"), VENUE_ADMIN
        ),
        ApiErrorId.CROSS_EVENT_REFERENCE,
        422,
    )

    accepted = f.gate_payload(zone_one["id"])
    accepted.pop("lanes_open")
    gate = validate_success(api.create_gate(first["id"], accepted, VENUE_ADMIN), 201)
    assert gate["access_zone_id"] == zone_one["id"]
    # One open lane unless the client says otherwise.
    assert gate["lanes_open"] == 1
    assert gate["status"] == GateStatus.IDLE

    fx.advance_event(api, first["id"], EventStatus.ON_SALE)
    validate_error(
        api.create_gate(
            first["id"], f.gate_payload(zone_one["id"], gate_code="G2"), VENUE_ADMIN
        ),
        ApiErrorId.EVENT_STATE_FORBIDS_OPERATION,
        409,
    )

    served, served_meta = validate_paginated(
        api.list_gates(VENUE_ADMIN, params={"access_zone_id": zone_one["id"]})
    )
    assert served_meta["total_count"] == 1
    assert [row["id"] for row in served] == [gate["id"]]

    _, empty_meta = validate_paginated(
        api.list_gates(VENUE_ADMIN, params={"event_id": second["id"]})
    )
    # Nothing was ever built against the second event.
    assert empty_meta["total_count"] == 0

"""Guards that compare a number the client is holding against the number on the server.

Three optimistic-concurrency ladders — a ticket invalidated by an unrelated
binding, a gate two writes ahead after one session lifecycle, an event advanced
by the very report that was just cut — and the fraud ceiling probed from both
sides of its strict boundary.
"""

from test_helpers import (
    ApiErrorId,
    EventStatus,
    FraudRiskBasis,
    GATE_OPERATOR,
    GateStatus,
    LifecycleStatus,
    ListingStatus,
    Marketplace,
    PriceCapRegime,
    ReportStatus,
    SECURITY_INVESTIGATOR,
    SessionMode,
    SessionStatus,
    VENUE_ADMIN,
    EntitlementLevel,
    constants as C,
    factories as f,
    fixtures as fx,
    make_patron_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_device_binding_invalidates_the_version_the_listing_was_written_against(api):
    """Version 1 is refused, the re-read version 2 is accepted, and the replay of 2 is stale.

    PRD: "Creating a resale listing (`POST /resale-listings`) must carry `expected_ticket_version` matching the target ticket's current `version`. If another writer has advanced the ticket's `version` since the client last read it — a device rebind, a completed transfer, an earlier listing or delist — the create is rejected with `ERR_STALE_TICKET_VERSION` (412). A relisting legitimately supersedes a prior `DELISTED` or `SUSPENDED` listing on the same ticket, so the write itself is valid product behaviour; the stale-version guard is what stops a client from listing on top of a ticket whose holder, binding or lifecycle has moved since it was read."
    PRD: "8. Stale-version guard per §2.6 — `ERR_STALE_TICKET_VERSION`, `ERR_STALE_GATE_VERSION` or `ERR_STALE_EVENT_VERSION` (412)."
    PRD: "Binding and releasing each increment the ticket's `version`."
    PRD: "Otherwise a percentage is selected from the regime — 0.10, that is ten percent, under `STATUTORY`, and 0.30, that is thirty percent, under `VENUE_POLICY` — and the permitted markup is the ticket's `face_value_cents` multiplied by that percentage, rounded half up to a whole cent, then reduced to 2500 cents if it came out higher; the cap is the ticket's `face_value_cents` plus that markup."
    PRD: "Listing moves the ticket `ISSUED → LISTED` (or `TRANSFERRED → LISTED` for a ticket that has changed hands), opens the listing in `LISTED` with `platform_fee_cents`, `venue_royalty_cents`, `processing_fee_cents` and `seller_payout_cents` all null, increments the ticket's `version`, and appends an audit entry with the action `RESALE_LISTED` against `subject_type` `RESALE_LISTING`."

    Design: Corner/cross_cutting_complexity_layers/occ_listing_creation_rejects_a_stale_ticket_version_then_accepts_the_refreshed_one
    """
    venue = fx.ticketed_venue(api, price_cap_regime=PriceCapRegime.VENUE_POLICY)
    ada, ticket = venue["holder"], venue["ticket"]
    version_at_issuance = ticket["version"]
    assert version_at_issuance == 1

    # An unrelated write on the same ticket is what makes the held version stale.
    bound = fx.bind_device(api, ticket["id"], ada["id"], "DEV-ADA")
    assert bound["version"] == 2

    seller = make_patron_headers(ada["id"])
    body = f.resale_listing_payload(
        ticket["id"], 12000, version_at_issuance, marketplace=Marketplace.VERIFIED_PARTNER
    )
    validate_error(
        api.create_resale_listing(body, seller), ApiErrorId.STALE_TICKET_VERSION, 412
    )
    _, meta = validate_paginated(api.list_resale_listings(VENUE_ADMIN))
    assert meta["total_count"] == 0

    refreshed = fx.read_ticket(api, ticket["id"])
    assert refreshed["version"] == 2
    assert refreshed["lifecycle_status"] == LifecycleStatus.ISSUED

    accepted_body = f.resale_listing_payload(
        ticket["id"], 12000, refreshed["version"], marketplace=Marketplace.VERIFIED_PARTNER
    )
    listing = validate_success(api.create_resale_listing(accepted_body, seller), 201)
    assert listing["status"] == ListingStatus.LISTED
    # Thirty percent of 12,000 is 3,600, which is reduced to the 2,500-cent ceiling.
    assert listing["cap_price_cents"] == 14500

    after = fx.read_ticket(api, ticket["id"])
    assert after["version"] == 3
    assert after["lifecycle_status"] == LifecycleStatus.LISTED

    # The accepted body is now stale against the write it caused itself.
    validate_error(
        api.create_resale_listing(accepted_body, seller), ApiErrorId.STALE_TICKET_VERSION, 412
    )
    _, meta = validate_paginated(api.list_resale_listings(VENUE_ADMIN))
    assert meta["total_count"] == 1


def test_one_session_lifecycle_leaves_the_gate_two_writes_beyond_the_held_version(api):
    """Neither version 1 nor version 2 opens the successor session; version 3 does.

    PRD: "Opening a scan session (`POST /scan-sessions`) must carry `expected_gate_version` matching the target gate's current `version`. A mismatch is rejected with `ERR_STALE_GATE_VERSION` (412). A new session legitimately succeeds the previous closed one on the same gate, so this guard is the only thing stopping an operator from opening a session against a stale view of the gate's lane configuration and session history."
    PRD: "8. Stale-version guard per §2.6 — `ERR_STALE_TICKET_VERSION`, `ERR_STALE_GATE_VERSION` or `ERR_STALE_EVENT_VERSION` (412)."
    PRD: "A successful open creates the session in `OPEN` with `opened_at` set to the logical clock, a null `closed_at`, and `online_scan_count`, `offline_uploaded_count` and `duplicate_suppressed_count` all at zero; the gate moves `IDLE → SCANNING` and its `version` increments."
    PRD: "Closing the session is permitted from `OPEN` or from `SYNCING`. It sets the session's `status` to `CLOSED` and its `closed_at` to the logical clock, moves the gate `SCANNING → IDLE`, copies that `closed_at` onto the gate's `last_session_closed_at`, and increments the gate's `version`."
    PRD: "A new session opening at exactly a prior session's `closed_at` is accepted, because that boundary is excluded."

    Design: Corner/cross_cutting_complexity_layers/occ_session_open_rejects_a_stale_gate_version_after_the_previous_session_closed
    """
    event = fx.create_event(api)
    zone = fx.create_zone(api, event["id"], fire_code_capacity=150)
    gate = fx.create_gate(api, event["id"], zone["id"], throughput_per_minute=20, lanes_open=2)
    version_at_creation = gate["version"]
    assert version_at_creation == 1
    fx.advance_event_to(api, event["id"], EventStatus.DOORS_OPEN)

    fx.set_clock(api, C.T_18_10_00)
    first = validate_success(
        api.create_scan_session(
            f.scan_session_payload(gate["id"], version_at_creation), GATE_OPERATOR
        ),
        201,
    )
    scanning = fx.read_gate(api, gate["id"])
    assert scanning["version"] == 2
    assert scanning["status"] == GateStatus.SCANNING

    fx.set_clock(api, C.T_18_20_00)
    assert fx.close_scan_session(api, first["id"])["status"] == SessionStatus.CLOSED

    # Two writes behind.
    validate_error(
        api.create_scan_session(
            f.scan_session_payload(gate["id"], version_at_creation, operator_device_id="SCN-2"),
            GATE_OPERATOR,
        ),
        ApiErrorId.STALE_GATE_VERSION,
        412,
    )
    # One write behind is still stale, so the guard is equality and not a lower bound.
    validate_error(
        api.create_scan_session(
            f.scan_session_payload(gate["id"], 2, operator_device_id="SCN-2"), GATE_OPERATOR
        ),
        ApiErrorId.STALE_GATE_VERSION,
        412,
    )

    idle = fx.read_gate(api, gate["id"])
    assert idle["version"] == 3
    assert idle["status"] == GateStatus.IDLE
    assert idle["last_session_closed_at"] == C.T_18_20_00

    # The clock sits exactly on the prior session's closed_at, which is excluded.
    second = validate_success(
        api.create_scan_session(
            f.scan_session_payload(
                gate["id"],
                idle["version"],
                operator_device_id="SCN-2",
                mode=SessionMode.OFFLINE_CAPABLE,
            ),
            GATE_OPERATOR,
        ),
        201,
    )
    assert second["status"] == SessionStatus.OPEN
    assert second["mode"] == SessionMode.OFFLINE_CAPABLE

    _, meta = validate_paginated(
        api.list_scan_sessions(GATE_OPERATOR, params={"gate_id": gate["id"]})
    )
    assert meta["total_count"] == 2
    # Every accepted write moved the version exactly once.
    assert fx.read_gate(api, gate["id"])["version"] == 4


def test_cutting_a_report_advances_the_event_the_next_report_must_be_cut_against(api):
    """The version that carried the first draft is refused for the second, which is otherwise legal.

    PRD: "Cutting a reconciliation report (`POST /events/{id}/reconciliation-reports`) must carry `expected_event_version` matching the target event's current `version`. A mismatch is rejected with `ERR_STALE_EVENT_VERSION` (412). A later report legitimately supersedes an earlier `DRAFT` one, so the guard is what stops a report from being cut against out-of-date occupancy and settlement figures."
    PRD: "8. Stale-version guard per §2.6 — `ERR_STALE_TICKET_VERSION`, `ERR_STALE_GATE_VERSION` or `ERR_STALE_EVENT_VERSION` (412)."
    PRD: "Creation takes the `reported_attendance` (at least 0) and the `expected_event_version` guard, opens the report in `DRAFT` with a null `override_reason` and a null `finalized_by_user_id`, and increments the event's `version`."
    PRD: "At creation the report's derived figures are computed: `scan_derived_attendance` from the reconciled reading of §2.9, `variance_count` as the `reported_attendance` minus `scan_derived_attendance`, `variance_pct` as that variance divided by `scan_derived_attendance`, multiplied by 100 and rounded half up to two decimal places — defined as exactly 0.00 when `scan_derived_attendance` is zero, rather than an error — and `fire_code_breach` set true when `scan_derived_attendance` exceeds the event's `fire_code_capacity`."
    PRD: "17. The event already carries a `FINAL` reconciliation report, or its `status` is already `RECONCILED` — `ERR_EVENT_ALREADY_RECONCILED` (409), on reconciliation-report creation."

    Design: Corner/cross_cutting_complexity_layers/occ_reconciliation_report_rejects_a_stale_event_version
    """
    event = fx.create_event(api)
    zone = fx.create_zone(api, event["id"], fire_code_capacity=150)
    fx.create_gate(api, event["id"], zone["id"])
    closed = fx.advance_event_to(api, event["id"], EventStatus.CLOSED)
    version_at_close = closed["version"]

    first = validate_success(
        api.create_reconciliation_report(
            event["id"], f.reconciliation_report_payload(0, version_at_close), VENUE_ADMIN
        ),
        201,
    )
    assert first["status"] == ReportStatus.DRAFT
    assert first["scan_derived_attendance"] == 0
    # Nought derived pins the percentage rather than dividing by zero.
    assert first["variance_pct"] == 0.00

    # Neither report is FINAL, so a second draft is legal — only the version is wrong.
    validate_error(
        api.create_reconciliation_report(
            event["id"], f.reconciliation_report_payload(0, version_at_close), VENUE_ADMIN
        ),
        ApiErrorId.STALE_EVENT_VERSION,
        412,
    )

    advanced = fx.read_event(api, event["id"])
    assert advanced["version"] == version_at_close + 1
    assert advanced["status"] == EventStatus.CLOSED

    second = validate_success(
        api.create_reconciliation_report(
            event["id"], f.reconciliation_report_payload(0, advanced["version"]), VENUE_ADMIN
        ),
        201,
    )
    assert second["status"] == ReportStatus.DRAFT
    assert second["id"] != first["id"]

    _, meta = validate_paginated(
        api.list_reconciliation_reports(VENUE_ADMIN, params={"event_id": event["id"]})
    )
    assert meta["total_count"] == 2


def test_thirty_nine_points_may_still_trade_while_exactly_forty_may_not(api):
    """Ada's 20 plus 15 plus 4 of churn lists; Bob's 20 plus 20 is refused twice over.

    PRD: "The score is built from two ingredients. The first is device churn: a patron's `device_rebind_count` counts every time they have bound a device to a ticket *after* the first binding on that ticket, and churn contributes four points for each rebind beyond the first — formally, four multiplied by the greater of zero and one less than `device_rebind_count`. The second is the patron's denied-entry history, where each incident contributes points according to its `category`: `COUNTERFEIT` weighs 50, `DEVICE_MISMATCH` weighs 45, `UNAUTHORIZED_RESALE` weighs 30, `DUPLICATE` weighs 20 and `ZONE_VIOLATION` weighs 15."
    PRD: "The score gates commercial activity: creating a resale listing and creating a transfer request both require the acting patron's `fraud_risk_score` to be **strictly below 40**. A score of exactly 40 is blocked, with `ERR_PATRON_FRAUD_BLOCKED` (403)."
    PRD: "28. The acting patron's `fraud_risk_score` is strictly below 40 — `ERR_PATRON_FRAUD_BLOCKED` (403), on resale listing creation and transfer creation."
    PRD: "Whenever a device is bound to a ticket whose `device_binding_status` was already `BOUND` or `RELEASED` — that is, on any binding after the first on that ticket — the holder's `device_rebind_count` increases by one and their `fraud_risk_score` is immediately recomputed under the provisional reading described in §2.10."
    PRD: "When a fraud-bearing denial does open an incident, the cascade runs in four links within the same request: the incident is created in `OPEN`; the holder's `strike_count` rises by one and their `fraud_risk_score` is recomputed under the provisional reading; if that recomputed score reaches 40, every `LISTED` listing of that patron is suspended; and each suspended listing reverts its ticket's `lifecycle_status` to `ISSUED`."
    PRD: "23. An entry scan is refused when the ticket's `admission_status` is already `INSIDE` — `ERR_DUPLICATE_SCAN` (409), on live scanning and offline batch items."
    PRD: "25. Zone entitlement: the gate's `access_zone_id` equals the ticket's `access_zone_id`, and the ticket's `ticket_type` is `CREDENTIAL` whenever the zone's `required_entitlement_level` is `BACK_OF_HOUSE` — `ERR_ZONE_NOT_ENTITLED` (403), on live scanning and offline batch items."
    PRD: "14. Transfers require the logical clock strictly before the event's `transfer_window_closes_at` and an event `status` of `ON_SALE` or `DOORS_OPEN` — `ERR_EVENT_STATE_FORBIDS_TRANSFER` (409), on transfer creation and transfer acceptance."
    PRD: "Otherwise a percentage is selected from the regime — 0.10, that is ten percent, under `STATUTORY`, and 0.30, that is thirty percent, under `VENUE_POLICY` — and the permitted markup is the ticket's `face_value_cents` multiplied by that percentage, rounded half up to a whole cent, then reduced to 2500 cents if it came out higher; the cap is the ticket's `face_value_cents` plus that markup."

    Design: Corner/cross_cutting_complexity_layers/fraud_block_threshold_is_exclusive_at_thirty_nine_and_blocks_at_exactly_forty
    """
    event = fx.create_event(api, price_cap_regime=PriceCapRegime.VENUE_POLICY)
    general = fx.create_zone(api, event["id"], fire_code_capacity=150)
    premium = fx.create_zone(
        api,
        event["id"],
        zone_code="VIP1",
        required_entitlement_level=EntitlementLevel.PREMIUM,
        fire_code_capacity=50,
    )
    gate_general = fx.create_gate(api, event["id"], general["id"], throughput_per_minute=20)
    gate_premium = fx.create_gate(
        api, event["id"], premium["id"], gate_code="G2", throughput_per_minute=10
    )
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)

    ada = fx.register_patron(api)
    bob = fx.register_patron(
        api, email="bob@example.com", display_name="Bob Bell", document_reference="DL-BOB-1"
    )

    def general_ticket(patron_id):
        return fx.issue_ticket(
            api, event["id"], general["id"], patron_id, face_value_cents=12000
        )

    ada_scanned, ada_wrong_zone, ada_spare = (general_ticket(ada["id"]) for _ in range(3))
    bob_first, bob_second, bob_spare = (general_ticket(bob["id"]) for _ in range(3))

    # Two rebinds of one ticket: the first binding is free, the next two are churn.
    fx.bind_device(api, ada_scanned["id"], ada["id"], "DEV-A1")
    fx.release_device(api, ada_scanned["id"], ada["id"])
    fx.bind_device(api, ada_scanned["id"], ada["id"], "DEV-A2")
    fx.release_device(api, ada_scanned["id"], ada["id"])
    fx.bind_device(api, ada_scanned["id"], ada["id"], "DEV-A3")
    # A first binding on a different ticket is not a rebind.
    fx.bind_device(api, ada_wrong_zone["id"], ada["id"], "DEV-A9")
    fx.bind_device(api, bob_first["id"], bob["id"], "DEV-B1")
    fx.bind_device(api, bob_second["id"], bob["id"], "DEV-B9")

    fx.advance_event(api, event["id"], EventStatus.DOORS_OPEN)
    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, gate_general["id"])

    fx.admit_ticket(api, session["id"], ada_scanned["id"], "DEV-A3", "A1")
    validate_error(
        fx.denied_scan_response(
            api, session["id"], fx.current_barcode(api, ada_scanned["id"]), "DEV-A3", "A2"
        ),
        ApiErrorId.DUPLICATE_SCAN,
        409,
    )
    # Bob earns his two strikes on two different tickets, each entered once first.
    for ticket, device, keys in (
        (bob_first, "DEV-B1", ("B1", "B2")),
        (bob_second, "DEV-B9", ("B3", "B4")),
    ):
        fx.admit_ticket(api, session["id"], ticket["id"], device, keys[0])
        validate_error(
            fx.denied_scan_response(
                api, session["id"], fx.current_barcode(api, ticket["id"]), device, keys[1]
            ),
            ApiErrorId.DUPLICATE_SCAN,
            409,
        )

    fx.close_scan_session(api, session["id"])
    premium_session = fx.open_scan_session(api, gate_premium["id"], operator_device_id="SCN-2")
    validate_error(
        fx.denied_scan_response(
            api,
            premium_session["id"],
            fx.current_barcode(api, ada_wrong_zone["id"]),
            "DEV-A9",
            "A3",
        ),
        ApiErrorId.ZONE_NOT_ENTITLED,
        403,
    )

    scored_ada = fx.read_patron(api, ada["id"])
    assert scored_ada["device_rebind_count"] == 2
    assert scored_ada["strike_count"] == 2
    # Twenty for the duplicate, fifteen for the zone violation, four for one rebind beyond the first.
    assert scored_ada["fraud_risk_score"] == 39
    assert scored_ada["fraud_risk_basis"] == FraudRiskBasis.PROVISIONAL

    scored_bob = fx.read_patron(api, bob["id"])
    assert scored_bob["device_rebind_count"] == 0
    assert scored_bob["strike_count"] == 2
    # Two duplicates and no churn term at all.
    assert scored_bob["fraud_risk_score"] == 40

    listing = validate_success(
        api.create_resale_listing(
            f.resale_listing_payload(
                ada_spare["id"],
                12000,
                fx.read_ticket(api, ada_spare["id"])["version"],
                marketplace=Marketplace.VERIFIED_PARTNER,
            ),
            make_patron_headers(ada["id"]),
        ),
        201,
    )
    assert listing["status"] == ListingStatus.LISTED
    assert listing["cap_price_cents"] == 14500

    bob_headers = make_patron_headers(bob["id"])
    validate_error(
        api.create_resale_listing(
            f.resale_listing_payload(
                bob_spare["id"],
                12000,
                fx.read_ticket(api, bob_spare["id"])["version"],
                marketplace=Marketplace.VERIFIED_PARTNER,
            ),
            bob_headers,
        ),
        ApiErrorId.PATRON_FRAUD_BLOCKED,
        403,
    )

    # The handover window closes at 17:00, so the clock is wound inside it to leave
    # the fraud gate as the only condition a transfer could fail.
    fx.set_clock(api, C.T_16_59_59)
    validate_error(
        api.create_transfer_request(
            f.transfer_request_payload(bob_spare["id"], ada["id"]), bob_headers
        ),
        ApiErrorId.PATRON_FRAUD_BLOCKED,
        403,
    )

    _, listing_meta = validate_paginated(api.list_resale_listings(VENUE_ADMIN))
    assert listing_meta["total_count"] == 1
    _, transfer_meta = validate_paginated(api.list_transfer_requests(SECURITY_INVESTIGATOR))
    assert transfer_meta["total_count"] == 0
    # The refused calls wrote nothing.
    assert fx.read_ticket(api, bob_spare["id"])["lifecycle_status"] == LifecycleStatus.ISSUED

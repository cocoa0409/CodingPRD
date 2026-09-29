"""The declared shape of a stored row: defaults, echoes, pages and absences.

What a client omits, what the server fills in, what comes back on a read, and
which fields a record deliberately does not carry at all.
"""

from test_helpers import (
    ApiErrorId,
    BOX_OFFICE_AGENT,
    DistributionType,
    EntitlementLevel,
    EventStatus,
    NON_EXISTENT_UUID,
    PriceCapRegime,
    SECURITY_INVESTIGATOR,
    ScanResult,
    ScanSource,
    TicketType,
    VENUE_ADMIN,
    ZonePosture,
    constants as C,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_an_event_created_without_its_policy_fields_takes_the_declared_defaults(api):
    """Omitting both optional fields yields `VENUE_POLICY`, a limit of two and four zeroes.

    PRD: "Two policy fields are optional: `price_cap_regime`, which selects the resale ceiling rule and is one of `STATUTORY`, `VENUE_POLICY` or `NONE` and defaults to `VENUE_POLICY`; and `transfer_limit_per_ticket`, a non-negative integer capping how many accepted handovers any single ticket of this event may absorb, defaulting to 2."
    PRD: "A fresh event lands in `DRAFT` with `live_occupancy`, `peak_live_occupancy`, `entitlements_outstanding` and `settlement_pool_cents` all at zero."

    Design: Corner/entities/event_creation_applies_declared_defaults_and_zeroes_counters
    """
    payload = f.minimal_event_payload()
    assert "price_cap_regime" not in payload
    assert "transfer_limit_per_ticket" not in payload

    event = validate_success(api.create_event(payload, VENUE_ADMIN), 201)

    assert event["price_cap_regime"] == PriceCapRegime.VENUE_POLICY
    assert event["transfer_limit_per_ticket"] == 2
    assert event["status"] == EventStatus.DRAFT

    assert event["live_occupancy"] == 0
    assert event["peak_live_occupancy"] == 0
    assert event["entitlements_outstanding"] == 0
    assert event["settlement_pool_cents"] == 0

    # A row nobody has mutated yet sits at the opening version.
    assert event["version"] == 1
    assert event["created_at"] == event["updated_at"]


def test_a_stored_event_reads_back_exactly_as_it_was_created(api):
    """Every supplied field echoes on the read, including the non-default policy pair.

    PRD: "Creation takes the event's `name` as printed on tickets, the `venue_name` it is staged at, the venue-wide `fire_code_capacity` (at least 1), the `barcode_anchor_at` instant from which barcode epochs are counted, the advertised `doors_open_at` and `event_start_at` instants, and the `transfer_window_closes_at` instant after which no handover may be created or accepted."
    PRD: "Most resources additionally carry an `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and a `version`, an integer that starts at 1 on creation and increments by one on every mutation of that resource."

    Design: Corner/entities/event_retrieval_returns_the_stored_record_unchanged
    """
    created = validate_success(
        api.create_event(
            f.event_payload(
                name="Statutory Matinee",
                venue_name="Southgate Hall",
                price_cap_regime=PriceCapRegime.STATUTORY,
                transfer_limit_per_ticket=1,
            ),
            VENUE_ADMIN,
        ),
        201,
    )

    read = validate_success(api.get_event(created["id"], SECURITY_INVESTIGATOR))

    assert read["id"] == created["id"]
    assert read["name"] == "Statutory Matinee"
    assert read["venue_name"] == "Southgate Hall"
    assert read["fire_code_capacity"] == 200
    assert read["barcode_anchor_at"] == C.BARCODE_ANCHOR_AT
    assert read["doors_open_at"] == C.DOORS_OPEN_AT
    assert read["event_start_at"] == C.EVENT_START_AT
    assert read["transfer_window_closes_at"] == C.TRANSFER_WINDOW_CLOSES_AT

    # An explicit choice is stored rather than overwritten by the default.
    assert read["price_cap_regime"] == PriceCapRegime.STATUTORY
    assert read["transfer_limit_per_ticket"] == 1

    assert read["status"] == EventStatus.DRAFT
    assert read["version"] == 1


def test_the_event_list_pages_against_a_total_count_and_narrows_by_status(api):
    """Three events, two pages of two and one, and a status filter that keeps one row.

    PRD: "`total_count` is the number of rows matching the supplied filters *before* `limit` and `offset` are applied, and `has_more` is true exactly when `offset` plus the number of returned rows is still less than `total_count`."
    PRD: "Unless a specific endpoint says otherwise, list results are sorted by `created_at` ascending."
    PRD: "Events filter by `status`."

    Design: Corner/entities/event_listing_paginates_with_total_count_and_filters_by_status
    """
    on_sale = fx.on_sale_venue(api)["event"]
    boreal = fx.create_event(api, name="Boreal Matinee")
    comet = fx.create_event(api, name="Comet Finale")

    first_page, meta = validate_paginated(
        api.list_events(SECURITY_INVESTIGATOR, params={"limit": 2, "offset": 0})
    )
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert len(first_page) == 2

    second_page, meta = validate_paginated(
        api.list_events(SECURITY_INVESTIGATOR, params={"limit": 2, "offset": 2})
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(second_page) == 1

    # The window partitions the collection: no row is dropped and none is repeated.
    paged = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert sorted(paged) == sorted([on_sale["id"], boreal["id"], comet["id"]])

    filtered, meta = validate_paginated(
        api.list_events(SECURITY_INVESTIGATOR, params={"status": EventStatus.ON_SALE})
    )
    # The count is taken after the filter and before the window.
    assert meta["total_count"] == 1
    assert [row["id"] for row in filtered] == [on_sale["id"]]


def test_reading_a_ticket_that_was_never_issued_reports_the_tickets_own_not_found(api):
    """An unresolvable path segment answers with the collection's error, not a generic one.

    PRD: "4. Path identifiers resolve, left to right — the collection's own not-found error (404), for example `ERR_EVENT_NOT_FOUND` for an event path segment, `ERR_TICKET_NOT_FOUND` for a ticket segment, `ERR_SESSION_NOT_FOUND` for a scan-session segment and `ERR_REPORT_NOT_FOUND` for a reconciliation-report segment, as enumerated in §2.7."

    Design: Corner/entities/ticket_read_with_an_unknown_id_returns_not_found
    """
    fx.on_sale_venue(api)

    validate_error(
        api.get_ticket(NON_EXISTENT_UUID, SECURITY_INVESTIGATOR),
        ApiErrorId.TICKET_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(api.list_tickets(BOX_OFFICE_AGENT))
    assert meta["total_count"] == 0


def test_a_zone_created_without_its_fire_code_capacity_is_a_shape_error(api):
    """A missing required field is refused before any geography is written.

    PRD: "An **AccessZone** is created with a `zone_code` unique within the event, a `required_entitlement_level` of `GA`, `PREMIUM` or `BACK_OF_HOUSE`, its own `fire_code_capacity` of at least 1, and a `face_value_reference_cents` of at least 0 used to price give-aways into that zone."
    PRD: "3. Request-body shape: every required field present, enum values inside their declared sets, integers inside their declared ranges, `valid_until` strictly after `valid_from`, and ISO-8601 timestamps parseable — `ERR_INVALID_REQUEST` (400), every endpoint that takes a body."

    Design: Corner/entities/access_zone_creation_missing_required_fire_code_capacity_returns_4XX
    """
    event = fx.create_event(api)

    payload = f.minimal_access_zone_payload()
    payload.pop("fire_code_capacity")
    validate_error(
        api.create_access_zone(event["id"], payload, VENUE_ADMIN),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    _, meta = validate_paginated(
        api.list_access_zones(VENUE_ADMIN, params={"event_id": event["id"]})
    )
    assert meta["total_count"] == 0
    # A refused create is not a mutation of the parent.
    assert fx.read_event(api, event["id"])["version"] == 1


def test_a_zone_created_without_its_optional_inputs_defaults_the_budget_and_the_discount(api):
    """No credential budget and an eighty-five percent give-away discount.

    PRD: "Two further inputs are optional: `credential_capacity`, a non-negative ceiling on how many credential holders may be admissible at any single instant, defaulting to 0; and `comp_discount_pct`, a fraction between 0 and 1 inclusive applied against the reference face value when a complimentary or credential entitlement is issued into the zone, defaulting to 0.85."
    PRD: "A new zone begins with `occupancy_count` and `issued_entitlement_count` at zero, `comp_forgone_cents` at zero, and a `posture` of `OPEN`."

    Design: Corner/entities/access_zone_creation_applies_credential_capacity_and_comp_discount_defaults
    """
    event = fx.create_event(api)

    payload = f.minimal_access_zone_payload()
    assert "credential_capacity" not in payload
    assert "comp_discount_pct" not in payload

    zone = validate_success(api.create_access_zone(event["id"], payload, VENUE_ADMIN), 201)

    assert zone["event_id"] == event["id"]
    assert zone["zone_code"] == "GA1"
    assert zone["required_entitlement_level"] == EntitlementLevel.GA
    assert zone["face_value_reference_cents"] == 8750

    assert zone["credential_capacity"] == 0
    assert zone["comp_discount_pct"] == 0.85

    assert zone["occupancy_count"] == 0
    assert zone["issued_entitlement_count"] == 0
    assert zone["comp_forgone_cents"] == 0
    assert zone["posture"] == ZonePosture.OPEN
    assert zone["version"] == 1


def test_a_bad_enum_and_three_out_of_range_numbers_are_all_shape_errors(api):
    """An unknown ticket type, a quantity of zero, a quantity of 51 and an empty window.

    PRD: "3. Request-body shape: every required field present, enum values inside their declared sets, integers inside their declared ranges, `valid_until` strictly after `valid_from`, and ISO-8601 timestamps parseable — `ERR_INVALID_REQUEST` (400), every endpoint that takes a body."
    PRD: "A `BoxOfficeAgent` drafts a **CredentialRequest** naming the `event_id`, the `access_zone_id` the issued entitlements will admit into, the `recipient_patron_id` who will hold every one of them, a `distribution_type` of `COMP`, `WILL_CALL` or `CREDENTIAL`, a `quantity` between 1 and 50 inclusive, a `valid_from` instant that opens the validity window inclusively, a `valid_until` instant that closes it exclusively and must be strictly after `valid_from`, and a free-text `justification` recorded in the audit trail."

    Design: Corner/entities/enum_and_range_constraints_rejected_on_ticket_and_credential_request
    """
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    zone_id = venue["zone"]["id"]
    ada = fx.register_patron(api)

    # `VIP` is not one of PAID, COMP, WILL_CALL or CREDENTIAL.
    validate_error(
        api.create_ticket(
            f.ticket_payload(event_id, zone_id, ada["id"], ticket_type="VIP"),
            BOX_OFFICE_AGENT,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    window = {
        "distribution_type": DistributionType.COMP,
        "valid_from": "2026-09-12T18:00:00Z",
        "valid_until": "2026-09-12T22:00:00Z",
    }

    def draft(**overrides):
        fields = dict(window)
        fields.update(overrides)
        return api.create_credential_request(
            f.credential_request_payload(event_id, zone_id, ada["id"], **fields),
            BOX_OFFICE_AGENT,
        )

    # The minimum is one pass.
    validate_error(draft(quantity=0), ApiErrorId.INVALID_REQUEST, 400)
    # The maximum is fifty.
    validate_error(draft(quantity=51), ApiErrorId.INVALID_REQUEST, 400)
    # A window that closes at the instant it opens is empty rather than short.
    validate_error(
        draft(quantity=1, valid_until="2026-09-12T18:00:00Z"),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    _, ticket_meta = validate_paginated(
        api.list_tickets(BOX_OFFICE_AGENT, params={"event_id": event_id})
    )
    assert ticket_meta["total_count"] == 0
    _, request_meta = validate_paginated(
        api.list_credential_requests(BOX_OFFICE_AGENT, params={"event_id": event_id})
    )
    assert request_meta["total_count"] == 0

    assert fx.read_event(api, event_id)["entitlements_outstanding"] == 0
    assert fx.read_zone(api, zone_id)["issued_entitlement_count"] == 0


def test_a_scan_event_reads_back_without_a_version_or_an_updated_at(api):
    """The append-only record exposes only its id and creation stamp on top of its fields.

    PRD: "Two record types are append-only and therefore carry neither `updated_at` nor `version`: the immutable scan event, and the audit log entry."
    PRD: "Both expose only `id` and `created_at` on top of their domain fields."
    PRD: "The server persists a **ScanEvent** with its `scan_session_id`, the `ticket_id` the seed part resolved to (null when it resolved to nothing), a `source` of `ONLINE`, a `recorded_at` equal to the logical clock, an adjudicated `result`, and a `denied_reason_code` carrying the error identifier the denial mapped to, which is null for admitted and exit results."

    Design: Corner/entities/scan_event_is_immutable_and_exposes_no_version_field
    """
    venue = fx.scan_ready_venue(api, device_fingerprint="DEV-ADA")
    recorded = fx.admit_ticket(
        api, venue["session"]["id"], venue["ticket"]["id"], "DEV-ADA", "S1-ONLINE-001"
    )

    read = validate_success(api.get_scan_event(recorded["id"], SECURITY_INVESTIGATOR))

    assert "id" in read
    assert "created_at" in read
    assert "version" not in read
    assert "updated_at" not in read

    assert read["source"] == ScanSource.ONLINE
    assert read["result"] == ScanResult.ADMITTED
    # An online scan takes both instants from the logical clock.
    assert read["recorded_at"] == C.T_18_10_00
    assert read["scanned_at"] == C.T_18_10_00

    assert read["scan_session_id"] == venue["session"]["id"]
    assert read["ticket_id"] == venue["ticket"]["id"]
    assert read["denied_reason_code"] is None


def test_a_zone_from_another_event_is_a_cross_event_reference_not_a_missing_row(api):
    """A resolvable zone owned elsewhere is 422; an unresolvable patron is 404.

    PRD: "Beyond mere existence, a referenced access zone or gate must belong to the *same* event as the resource being created or acted on; a cross-event reference is rejected with `ERR_CROSS_EVENT_REFERENCE` (422)."
    PRD: "5. Body identifier fields resolve — the referenced collection's own not-found error (404), for example `ERR_ZONE_NOT_FOUND` for an unresolved `access_zone_id` and `ERR_PATRON_NOT_FOUND` for an unresolved `holder_patron_id`; applies on direct ticket issuance, gate creation, transfer creation, resale listing creation, credential-request drafting and scan-session opening."
    PRD: "6. Referenced zone or gate belongs to the same event — `ERR_CROSS_EVENT_REFERENCE` (422), on direct ticket issuance, gate creation and credential-request drafting."

    Design: Corner/entities/ticket_creation_with_a_zone_from_another_event_is_rejected
    """
    first = fx.on_sale_venue(api)
    second = fx.on_sale_venue(
        api,
        name="Boreal Matinee",
        barcode_anchor_at="2026-09-13T18:00:00Z",
        doors_open_at="2026-09-13T18:00:00Z",
        event_start_at="2026-09-13T19:00:00Z",
        transfer_window_closes_at="2026-09-13T17:00:00Z",
    )
    ada = fx.register_patron(api)

    # The zone exists and resolves; it simply belongs to the other event.
    validate_error(
        api.create_ticket(
            f.ticket_payload(first["event"]["id"], second["zone"]["id"], ada["id"]),
            BOX_OFFICE_AGENT,
        ),
        ApiErrorId.CROSS_EVENT_REFERENCE,
        422,
    )

    # Existence is checked one priority earlier than ownership.
    validate_error(
        api.create_ticket(
            f.ticket_payload(first["event"]["id"], first["zone"]["id"], NON_EXISTENT_UUID),
            BOX_OFFICE_AGENT,
        ),
        ApiErrorId.PATRON_NOT_FOUND,
        404,
    )

    clean = validate_success(
        api.create_ticket(
            f.ticket_payload(first["event"]["id"], first["zone"]["id"], ada["id"]),
            BOX_OFFICE_AGENT,
        ),
        201,
    )
    assert clean["event_id"] == first["event"]["id"]
    assert clean["access_zone_id"] == first["zone"]["id"]
    assert clean["ticket_type"] == TicketType.PAID

    assert fx.read_zone(api, second["zone"]["id"])["issued_entitlement_count"] == 0
    assert fx.read_event(api, second["event"]["id"])["entitlements_outstanding"] == 0
    assert fx.read_zone(api, first["zone"]["id"])["issued_entitlement_count"] == 1
    assert fx.read_event(api, first["event"]["id"])["entitlements_outstanding"] == 1

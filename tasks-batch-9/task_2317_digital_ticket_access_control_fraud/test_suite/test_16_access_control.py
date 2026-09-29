"""Who may act, who may only look, and which of the two questions is asked first.

The role ladder is peer segregation rather than rank: the administrator cannot
bind a phone or void a seat, an unrecognized role name is turned away before any
endpoint is consulted, one patron's identity does not reach another's ticket, and
read access is granted per endpoint rather than per seniority.
"""

from test_helpers import (
    BOX_OFFICE_AGENT,
    DeviceBindingStatus,
    GATE_OPERATOR,
    HEADERS_BY_ROLE,
    LifecycleStatus,
    ListingStatus,
    Marketplace,
    NON_EXISTENT_UUID,
    Role,
    SECURITY_INVESTIGATOR,
    TICKETING_APPROVER,
    VENUE_ADMIN,
    ApiErrorId,
    constants as C,
    factories as f,
    fixtures as fx,
    headers_without_role,
    headers_without_user_id,
    make_headers,
    make_patron_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_every_exclusive_operation_refuses_its_neighbour_role_including_the_admin(api):
    """Nine cross-role attempts, nine identical refusals, and no hierarchical override.

    PRD: "2. The acting role is authorized for the endpoint per §4 — `ERR_FORBIDDEN_ROLE` (403), all endpoints."
    PRD: "When several rules could reject the same request, the lowest-numbered rule below wins and no later rule is evaluated."
    PRD: "A `SecurityInvestigator` adjudicates denied-entry incidents and voids compromised entitlements."
    PRD: "| POST | `/events` | Create an Event in DRAFT | VenueAdmin |"
    PRD: "| POST | `/_clock/set_current_utc` | Set the server's logical clock | VenueAdmin |"
    PRD: "| POST | `/credential-requests/{id}/submit` | Submit a draft, or resubmit after requested changes | BoxOfficeAgent |"
    PRD: "| POST | `/credential-requests/{id}/approve` | Approve the distribution and auto-issue its entitlements | TicketingApprover |"
    PRD: "| POST | `/tickets/{id}/device-binding` | Bind the holder's device to the ticket | Patron |"
    PRD: "| POST | `/tickets/{id}/void` | Void an entitlement, optionally refunding the holder | SecurityInvestigator |"
    PRD: "| POST | `/scan-sessions/{id}/scan-events` | Adjudicate one live gate scan | GateOperator |"
    PRD: "| POST | `/reconciliation-reports/{id}/finalize` | Finalize the report and reconcile the event | VenueAdmin |"
    PRD: "Before any client has moved it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."
    PRD: "A `VenueAdmin` moves the clock through an admin-only test-driving capability that accepts a single `to_iso8601` instant and answers with the resulting `current_utc` alongside the `previous_utc` it replaced."

    Design: Corner/rbac/no_role_may_perform_another_roles_exclusive_operation_and_admin_is_not_a_superuser
    """
    trespasses = [
        # A patron cannot configure the venue.
        api.create_event(f.minimal_event_payload(), make_patron_headers(NON_EXISTENT_UUID)),
        # Only the administrator drives the clock.
        api.set_clock(f.clock_payload("2027-01-01T00:00:00Z"), BOX_OFFICE_AGENT),
        # The submitter of a distribution is not its decider, and vice versa.
        api.approve_credential_request(NON_EXISTENT_UUID, None, BOX_OFFICE_AGENT),
        api.submit_credential_request(NON_EXISTENT_UUID, None, TICKETING_APPROVER),
        # Voiding is an investigator's move, not a doorkeeper's.
        api.void_ticket(NON_EXISTENT_UUID, f.void_payload(reason="not my job"), GATE_OPERATOR),
        # Reading the incidents does not mean working the turnstile.
        api.create_scan_event(
            NON_EXISTENT_UUID,
            f.scan_event_payload("SEED-1", "DEV-X", "X1"),
            SECURITY_INVESTIGATOR,
        ),
        # The administrator is a peer, not a superuser: neither of these is theirs.
        api.bind_device(NON_EXISTENT_UUID, f.device_binding_payload("DEV-ADMIN"), VENUE_ADMIN),
        api.void_ticket(
            NON_EXISTENT_UUID, f.void_payload(reason="admin override attempt"), VENUE_ADMIN
        ),
        # Nor may the investigator sign off the attendance figures.
        api.finalize_reconciliation_report(NON_EXISTENT_UUID, None, SECURITY_INVESTIGATOR),
    ]
    assert len(trespasses) == 9
    for response in trespasses:
        # The role check outranks both the body check and the existence check, so
        # unknown path ids never surface as 404 and thin bodies never as 400.
        validate_error(response, ApiErrorId.FORBIDDEN_ROLE, 403)

    # The refused clock move left the instant where it started.
    moved = fx.set_clock(api, C.T_18_10_00)
    assert moved["previous_utc"] == C.CLOCK_EPOCH_START
    assert moved["current_utc"] == C.T_18_10_00

    _, meta = validate_paginated(api.list_events(VENUE_ADMIN))
    assert meta["total_count"] == 0


def test_a_header_problem_answers_with_authentication_rather_than_authorization(api):
    """No role, no user, an invented role and a lower-cased one all stop at priority one.

    PRD: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act."
    PRD: "Six roles exist and their spelling is exact: `Patron`, `BoxOfficeAgent`, `TicketingApprover`, `GateOperator`, `SecurityInvestigator`, and `VenueAdmin`."
    PRD: "A request missing either header, or carrying an `X-User-Role` value outside those six, is rejected with `ERR_UNAUTHENTICATED` (401)."
    PRD: "1. Authentication headers present and the role recognized — `ERR_UNAUTHENTICATED` (401), all endpoints."
    PRD: "2. The acting role is authorized for the endpoint per §4 — `ERR_FORBIDDEN_ROLE` (403), all endpoints."
    PRD: "| GET | `/events` | List Events | Any |"

    Design: Corner/rbac/missing_and_unknown_identity_headers_are_rejected_at_priority_one
    """
    # A list every role may call, so nothing here is an authorization question.
    validate_error(
        api.list_events(headers_without_role(C.ADMIN_USER_ID)),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.list_events(headers_without_user_id(Role.VENUE_ADMIN)),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.list_events(make_headers("conc-1", "Concessionaire")),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    # The spelling is exact, so a lower-cased role is unrecognized rather than unauthorized.
    validate_error(
        api.create_event(f.event_payload(), make_headers("conc-1", "concessionaire")),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )

    _, meta = validate_paginated(api.list_events(VENUE_ADMIN))
    assert meta["total_count"] == 0


def test_a_second_patron_is_a_valid_role_and_still_a_stranger_to_the_ticket(api):
    """Bob clears the role gate and is stopped at ownership; Ada's identical call lands.

    PRD: "7. Patron ownership per §2.1 — `ERR_NOT_TICKET_HOLDER` (403), on device binding, binding release, transfer creation, transfer acceptance, transfer decline, resale listing creation and delisting."
    PRD: "When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the acting `Patron` record; ownership checks compare that value to the resource's patron-bearing field — `holder_patron_id` on the ticket for device binding, transfer creation and resale listing, `to_patron_id` on the request for a transfer acceptance, either `to_patron_id` or `from_patron_id` for a decline, and `seller_patron_id` on the listing for a delist."
    PRD: "A mismatch is rejected with `ERR_NOT_TICKET_HOLDER` (403)."
    PRD: "Delisting requires the listing to be `LISTED` and the acting patron to be its `seller_patron_id`, and anyone else is refused with `ERR_NOT_TICKET_HOLDER`; it moves the listing `LISTED → DELISTED`, reverts the ticket's `lifecycle_status` to `ISSUED`, and increments the ticket's `version`."
    PRD: "Issuance mints the ticket's `barcode_seed`, the server-side secret every rotating barcode for that ticket is derived from, and opens the ticket in `lifecycle_status` `ISSUED`, `admission_status` `NOT_ADMITTED` and `device_binding_status` `UNBOUND`, with `transfer_count`, `admitted_scan_count` at zero and `bound_device_fingerprint`, `last_admitted_at`, `last_exited_at` and `credential_request_id` all null."
    PRD: "| GET | `/tickets/{id}` | Read one Ticket including both status dimensions and version | Any |"

    Design: Corner/rbac/patron_actions_are_scoped_to_the_patrons_own_entitlements
    """
    venue = fx.two_patron_venue(api)
    ada, bob = venue["holder"], venue["other"]
    ticket_id = venue["ticket"]["id"]
    listing = fx.create_listing(
        api, ticket_id, ada["id"], 12000, marketplace=Marketplace.VERIFIED_PARTNER
    )
    assert listing["status"] == ListingStatus.LISTED

    bob_headers = make_patron_headers(bob["id"])
    validate_error(
        api.bind_device(ticket_id, f.device_binding_payload("DEV-BOB"), bob_headers),
        ApiErrorId.NOT_TICKET_HOLDER,
        403,
    )
    validate_error(
        api.delist_resale_listing(listing["id"], None, bob_headers),
        ApiErrorId.NOT_TICKET_HOLDER,
        403,
    )
    # Naming himself as the recipient does not make Bob the seat's holder.
    validate_error(
        api.create_transfer_request(
            f.transfer_request_payload(ticket_id, bob["id"]), bob_headers
        ),
        ApiErrorId.NOT_TICKET_HOLDER,
        403,
    )

    # The very same call from the seller is accepted, so the refusals were ownership-scoped.
    delisted = validate_success(
        api.delist_resale_listing(listing["id"], None, make_patron_headers(ada["id"]))
    )
    assert delisted["status"] == ListingStatus.DELISTED

    # A shared read is not ownership-scoped, so Bob may still look.
    seen = validate_success(api.get_ticket(ticket_id, bob_headers))
    assert seen["holder_patron_id"] == ada["id"]
    assert seen["lifecycle_status"] == LifecycleStatus.ISSUED
    # The refused bind wrote nothing.
    assert seen["bound_device_fingerprint"] is None
    assert seen["device_binding_status"] == DeviceBindingStatus.UNBOUND


def test_read_access_is_granted_per_endpoint_rather_than_by_seniority(api):
    """All six read one ticket, yet the trail, the patron list and the occupancy each fence off a different set.

    PRD: "Where a role column lists `Any`, all six roles of §2.1 are authorized."
    PRD: "| GET | `/tickets/{id}` | Read one Ticket including both status dimensions and version | Any |"
    PRD: "| GET | `/events/{id}/audit-log-entries` | Read the event's append-only audit trail, newest first | SecurityInvestigator, VenueAdmin |"
    PRD: "| GET | `/patrons` | List Patrons | BoxOfficeAgent, SecurityInvestigator, VenueAdmin |"
    PRD: "| GET | `/patrons/{id}` | Read one Patron including risk score and credit balances | Any |"
    PRD: "| GET | `/events/{id}/occupancy` | Computed read: live occupancy, reconciled attendance and clearance projection | GateOperator, SecurityInvestigator, VenueAdmin |"
    PRD: "2. The acting role is authorized for the endpoint per §4 — `ERR_FORBIDDEN_ROLE` (403), all endpoints."

    Design: Corner/rbac/shared_reads_are_open_to_their_declared_roles_and_closed_to_the_rest
    """
    venue = fx.ticketed_venue(api)
    event_id = venue["event"]["id"]
    ada = venue["holder"]
    ticket_id = venue["ticket"]["id"]

    every_role = list(HEADERS_BY_ROLE.values()) + [make_patron_headers(ada["id"])]
    assert len(every_role) == 6
    for headers in every_role:
        assert (
            validate_success(api.get_ticket(ticket_id, headers))["lifecycle_status"]
            == LifecycleStatus.ISSUED
        )

    # The trail is evidence, and the doorkeeper is not one of its two readers.
    validate_error(
        api.list_audit_log_entries(event_id, GATE_OPERATOR),
        ApiErrorId.FORBIDDEN_ROLE,
        403,
    )

    # The roster is closed to a patron even though their own record is not.
    validate_error(
        api.list_patrons(make_patron_headers(ada["id"])), ApiErrorId.FORBIDDEN_ROLE, 403
    )
    assert (
        validate_success(api.get_patron(ada["id"], make_patron_headers(ada["id"])))[
            "identity_verified"
        ]
        is True
    )

    # Occupancy is an operational read, so the commercial roles are excluded.
    validate_error(
        api.get_event_occupancy(event_id, BOX_OFFICE_AGENT), ApiErrorId.FORBIDDEN_ROLE, 403
    )
    assert validate_success(api.get_event_occupancy(event_id, GATE_OPERATOR))["live_occupancy"] == 0

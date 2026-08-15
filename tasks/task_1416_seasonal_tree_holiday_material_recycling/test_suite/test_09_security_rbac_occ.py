"""Security and concurrency: authentication, role authorization, ownership,
segregation of duties, OCC stale-version guards, and the catalog's HTTP
status mapping."""
from test_helpers import (
    ADMIN,
    ANON,
    HAULER,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    create_active_program,
    create_confirmed_booking,
    create_site_payload,
    get_site,
    get_zone,
    make_resident_headers,
    make_site_supervisor_headers,
    make_volunteer_headers,
    open_site,
    patch_site,
    patch_zone,
    register_household,
    register_volunteer,
    report_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:

    def test_request_missing_auth_headers_unauthenticated(self):
        """PRD section 2.1: "A request whose headers are missing, or whose
        role value is not one of these six declared roles, is rejected with
        `ERR_UNAUTHENTICATED`. This requirement applies to every endpoint
        without exception".

        Design: Corner/validations/request_missing_auth_headers_unauthenticated
        """
        resp = api_client.list_programs({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:

    def test_resident_cannot_create_site_returns_forbidden(self):
        """PRD section 2.7: "Second, role authorization: the caller's role
        must appear in the endpoint's authorized list, honoring per-transition
        role splits, failing which the request is rejected with
        `ERR_FORBIDDEN`."
        PRD section 4: POST /sites is authorized to "ProgramAdmin" only.

        Design: Corner/rbac/resident_cannot_create_site_returns_forbidden
        """
        program = _create_bare_program_with_zone()
        household = register_household(program["id"], program["zone_id"])

        resp = api_client.create_site(
            create_site_payload(program["id"], name="Rogue Lot"),
            make_resident_headers(household["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        data, meta = validate_paginated(api_client.list_sites(
            ADMIN, params={"program_id": program["id"]}))
        assert all(s["name"] != "Rogue Lot" for s in data), \
            "a forbidden create must not persist the site"

    def test_anonymous_cannot_read_programs(self):
        """PRD section 2.1: "Finally, the `Anonymous` role is an opaque,
        unauthenticated registrant identity: it may only register a household
        or a volunteer".

        Design: Corner/rbac/anonymous_cannot_read_programs
        """
        resp = api_client.list_programs(ANON)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_hauler_partner_cannot_create_run(self):
        """PRD section 2.1: "the role represents the external hauling and
        processing partner's operator, who supplies scale data at
        chipping-run completion and reads program, site, run, intake, and
        report resources".
        PRD section 4: POST /chipping-runs is authorized to "ProgramAdmin"
        only.

        Design: Corner/rbac/hauler_partner_cannot_create_run
        """
        program = _create_bare_program_with_zone()
        site = _add_site(program["id"])
        resp = api_client.create_chipping_run(
            {"program_id": program["id"], "site_id": site["id"],
             "scheduled_start": "2027-01-17T08:00:00Z",
             "scheduled_end": "2027-01-17T10:00:00Z",
             "material_class": "HARDWOOD"},
            HAULER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_volunteer_reports_ticket_but_cannot_adjudicate(self):
        """PRD section 3.4: "When a crew member, gate supervisor, volunteer,
        or administrator finds a decorated tree, an attached stand, a flocked
        tree, a wreath with wire, or any other contaminant, they report it by
        creating a **ContaminationTicket**."
        PRD section 3.4: "Adjudication is performed by a `ProgramAdmin` or
        `SiteSupervisor` other than the ticket's reporter".

        Design: Corner/rbac/volunteer_reports_ticket_but_cannot_adjudicate
        """
        ctx = create_active_program(clock="2027-01-05T00:00:00Z")
        open_site(ctx["site"])
        volunteer = register_volunteer(ctx["program"]["id"])
        vol_headers = make_volunteer_headers(volunteer["id"])

        ticket = report_ticket(ctx["program"]["id"], site_id=ctx["site"]["id"],
                               category="WREATH_WITH_WIRE",
                               reporter_headers=vol_headers)
        assert ticket["status"] == "OPEN"
        assert ticket["reporter_user_id"] == volunteer["id"]

        resp = api_client.adjudicate_ticket(ticket["id"],
                                            {"verdict": "UPHELD"},
                                            vol_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert _get_ticket_status(ticket["id"]) == "OPEN"


class TestOwnership:

    def test_resident_cannot_cancel_others_booking(self):
        """PRD section 2.1: "Concretely, a resident may cancel or reschedule a
        booking, create or cancel a mulch claim, or appeal a ticket only when
        the `household_id` of the booking, claim, or ticket equals their
        `X-User-ID`; a mismatch is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/resident_cannot_cancel_others_booking
        """
        ctx = create_active_program()
        program, zone = ctx["program"], ctx["zone"]
        h1 = register_household(program["id"], zone["id"])
        h2 = register_household(program["id"], zone["id"])
        booking = create_confirmed_booking(h1, zone["id"])

        resp = api_client.cancel_booking(
            booking["id"], make_resident_headers(h2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert api_client.get_booking(
            booking["id"], ADMIN).json()["data"]["status"] == "CONFIRMED"


class TestOptimisticConcurrency:

    def test_occ_zone_patch_stale_version(self):
        """PRD section 2.6: "A zone update (`PATCH /zones/{id}` — a
        collection-date reschedule, a capacity change, or a status change)
        must carry `expected_zone_version`; a mismatch, for instance because
        another writer has already rescheduled the zone (which legitimately
        moves the date and cascades to bookings) since the client last read
        it, is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_zone_patch_stale_version
        """
        ctx = create_active_program()
        zone = ctx["zone"]
        stale_version = get_zone(zone["id"])["version"]

        first = patch_zone(zone["id"], daily_tree_capacity=8)
        assert first["daily_tree_capacity"] == 8
        assert first["version"] > stale_version

        resp = api_client.patch_zone(
            zone["id"],
            {"daily_tree_capacity": 9,
             "expected_zone_version": stale_version},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_zone(zone["id"])["daily_tree_capacity"] == 8

    def test_occ_site_patch_stale_version(self):
        """PRD section 2.6: "A site update (`PATCH /sites/{id}`, covering
        capacity, date, and slot edits as well as suspend, reopen, and closure
        transitions) must likewise carry `expected_site_version`; a mismatch
        with the site's current version, including advances caused by cascaded
        stockpile or status changes, is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/occ_site_patch_stale_version
        """
        ctx = create_active_program()
        site = open_site(ctx["site"])
        stale_version = site["version"]

        # The successful suspend advances the site's version.
        suspended = patch_site(site["id"], as_headers=SUPERVISOR,
                               status="SUSPENDED")
        assert suspended["status"] == "SUSPENDED"
        assert suspended["version"] > stale_version

        # Replaying the pre-suspend version is stale.
        resp = api_client.patch_site(
            site["id"],
            {"status": "OPEN", "expected_site_version": stale_version},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_site(site["id"])["status"] == "SUSPENDED"


class TestErrorCatalogMapping:

    def test_error_catalog_http_status_mapping(self):
        """PRD section 2.6: "a mismatch, for instance because another writer
        has already rescheduled the zone ... is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 3.4: "an adjudicator whose `X-User-ID` equals the ticket's
        `reporter_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`, and
        this segregation binds the administrator role too."
        PRD section 3.2: "a single tree over the limit is rejected with
        `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Corner/errors/error_catalog_http_status_mapping
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5})
        program, zone = ctx["program"], ctx["zone"]
        household = register_household(program["id"], zone["id"])
        booking = create_confirmed_booking(household, zone["id"],
                                           tree_count=3, size_class="SMALL")
        reporter = make_site_supervisor_headers("sup-1")
        ticket = report_ticket(program["id"], booking_id=booking["id"],
                               category="WREATH_WITH_WIRE",
                               reporter_headers=reporter)

        # 412: the successful capacity patch advances the zone version, so the
        # replayed pre-patch version is stale.
        zone_version = get_zone(zone["id"])["version"]
        patch_zone(zone["id"], daily_tree_capacity=6)
        stale = api_client.patch_zone(
            zone["id"],
            {"daily_tree_capacity": 7,
             "expected_zone_version": zone_version},
            ADMIN,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412

        # 403: the reporter may not adjudicate their own ticket.
        own = api_client.adjudicate_ticket(ticket["id"], {"verdict": "UPHELD"},
                                           reporter)
        validate_error(own, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert own.status_code == 403

        # 422: 3 reserved + 4 requested = 7 > capacity 6.
        over = api_client.create_booking(
            {"household_id": household["id"], "zone_id": zone["id"],
             "tree_count": 4, "size_class": "MEDIUM", "prep_attestation": True},
            make_resident_headers(household["id"]))
        validate_error(over, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)
        assert over.status_code == 422


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _create_bare_program_with_zone():
    """DRAFT program carrying its zone id for follow-up calls."""
    program_resp = api_client.create_program(
        {"name": "RBAC Season", "season_label": "Winter 2027",
         "window_start": "2027-01-02T00:00:00Z",
         "window_end": "2027-01-16T23:59:59Z"},
        ADMIN)
    program = validate_success(program_resp, 201)
    zone_resp = api_client.create_zone(
        {"program_id": program["id"], "zone_code": "NW-1",
         "collection_date": "2027-01-09T00:00:00Z",
         "daily_tree_capacity": 5},
        ADMIN)
    program["zone_id"] = validate_success(zone_resp, 201)["id"]
    return program


def _add_site(program_id):
    resp = api_client.create_site(create_site_payload(program_id), ADMIN)
    return validate_success(resp, 201)


def _get_ticket_status(ticket_id):
    resp = api_client.get_contamination_ticket(ticket_id, ADMIN)
    return validate_success(resp, 200)["status"]

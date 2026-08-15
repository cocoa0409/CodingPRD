"""API-wide contracts: auth, not-found errors, RBAC denials, OCC, envelope shape,
pagination, list filtering, and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_site_payload,
    create_vessel_payload,
    make_plant_operator_headers,
    make_safety_officer_headers,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_approved_ticket,
    create_draft_ticket,
    create_in_progress_ticket,
    create_scheduled_ticket,
    create_site,
    create_site_vessel_technician,
    create_site_with_vessel,
    create_technician,
    create_vessel,
)
from test_helpers.test_users import TEST_USERS

SM = TEST_USERS["service_manager_headers"]
SO = TEST_USERS["safety_officer_headers"]


class TestAuthAndNotFound:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or presents a role outside
        this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.10: "Authentication headers are validated first — a missing or
        invalid `X-User-ID` or `X-User-Role` surfaces `ERR_UNAUTHENTICATED` before
        any body parsing occurs."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        res = api.get_site(
            "00000000-0000-0000-0000-000000000000", headers={}
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_get_single_resources_not_found_return_404(self, api):
        """PRD §2.9: "A request naming a non-existent parent identifier is rejected
        immediately with the corresponding not-found error
        (`ERR_VESSEL_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, etc.) before any child
        lookup is attempted."

        Design: Corner/validations/get_single_resources_not_found_return_404
        """
        cases = [
            (api.get_site("00000000-0000-0000-0000-000000000001", SM),
             ApiErrorId.ERR_SITE_NOT_FOUND),
            (api.get_vessel("00000000-0000-0000-0000-000000000002", SM),
             ApiErrorId.ERR_VESSEL_NOT_FOUND),
            (api.get_technician("00000000-0000-0000-0000-000000000003", SM),
             ApiErrorId.ERR_TECHNICIAN_NOT_FOUND),
            (api.get_service_ticket("00000000-0000-0000-0000-000000000004", SM),
             ApiErrorId.ERR_TICKET_NOT_FOUND),
            (api.get_entry_permit("00000000-0000-0000-0000-000000000005", SM),
             ApiErrorId.ERR_PERMIT_NOT_FOUND),
            (api.get_replenishment_order("00000000-0000-0000-0000-000000000006", SM),
             ApiErrorId.ERR_ORDER_NOT_FOUND),
        ]
        for res, expected in cases:
            validate_error(res, expected, expected_status=404)

    def test_body_fk_references_not_found_return_404(self, api):
        """PRD §2.9: "The same rule applies when a request body references related
        resources — every referenced `site_id`, `vessel_id`, `technician_id`,
        `ticket_id`, `trigger_reading_id`, or `entrant_technician_id` must resolve
        to an existing entity, otherwise the request fails with the matching
        `ERR_*_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/body_fk_references_not_found_return_404
        """
        res = api.create_vessel(
            create_vessel_payload(
                "00000000-0000-0000-0000-000000000010",
                name="X", vessel_kind="BIN", capacity_tons=50,
                material_name="salt", reorder_point_pct=20,
            ),
            SM,
        )
        validate_error(res, ApiErrorId.ERR_SITE_NOT_FOUND, expected_status=404)

        res = api.create_level_reading(
            {
                "vessel_id": "00000000-0000-0000-0000-000000000011",
                "measured_at": "2026-08-02T00:00:00Z",
                "level_pct": 50.0,
            },
            make_technician_headers("00000000-0000-0000-0000-0000000000bb"),
        )
        validate_error(res, ApiErrorId.ERR_VESSEL_NOT_FOUND, expected_status=404)


class TestRbacDenials:
    def test_plant_operator_cannot_create_site_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted for the targeted
        endpoint, or that violates entity-backed ownership, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.1: "A `ServiceManager` onboards a customer site by creating a
        `CustomerSite` with a display `name` and a two-letter `state_code`."

        Design: Corner/rbac/plant_operator_cannot_create_site_forbidden
        """
        res = api.create_site(
            create_site_payload(name="Nope", state_code="IA"),
            make_plant_operator_headers("00000000-0000-0000-0000-0000000000aa"),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_technician_cannot_quote_ticket_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted for the targeted
        endpoint, or that violates entity-backed ownership, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.6: "A `ServiceManager` then finalizes the quote, transitioning the
        ticket from `DRAFT` to `QUOTED`."

        Design: Corner/rbac/technician_cannot_quote_ticket_forbidden
        """
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={"name": "RB Site", "state_code": "IA"},
            vessel_overrides={
                "name": "BIN-RB", "vessel_kind": "BIN", "capacity_tons": 50,
                "material_name": "salt", "reorder_point_pct": 30,
            },
            tech_overrides={"name": "Tech R", "weekly_capacity_hours": 40},
        )
        ticket = create_draft_ticket(
            site["id"], vessel["id"],
            job_type="INSPECTION", requires_entry=False, est_hours=2, crew_size=1,
        )
        res = api.quote_service_ticket(
            ticket["id"], make_technician_headers(tech["id"])
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        fetched = validate_success(api.get_service_ticket(ticket["id"], SM), 200)
        assert fetched["status"] == "DRAFT"

    def test_safety_officer_cannot_create_ticket_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted for the targeted
        endpoint, or that violates entity-backed ownership, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.6: "A `PlantOperator` (for its own site) or a `ServiceManager` opens
        a `ServiceTicket` by supplying `site_id`, `vessel_id`, a `job_type` of
        `DIAGNOSIS`, `CLEANOUT`, `INSPECTION`, `RETROFIT_AERATION`, or
        `RETROFIT_VIBRATOR`, a `requires_entry` flag (true when personnel will
        enter the vessel, which makes the ticket permit-gated), `est_hours` (must
        be greater than zero), `crew_size` (must be at least 1), and an optional
        free-text `description` (default empty)."

        Design: Corner/rbac/safety_officer_cannot_create_ticket_forbidden
        """
        site, vessel = create_site_with_vessel(
            site_overrides={"name": "SO Site", "state_code": "IA"},
            vessel_overrides={
                "name": "BIN-SO", "vessel_kind": "BIN", "capacity_tons": 50,
                "material_name": "salt", "reorder_point_pct": 30,
            },
        )
        res = api.create_service_ticket(
            {
                "site_id": site["id"],
                "vessel_id": vessel["id"],
                "job_type": "INSPECTION",
                "requires_entry": False,
                "est_hours": 2,
                "crew_size": 1,
            },
            SO,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_operator_cannot_read_other_site_vessel_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `PlantOperator`, `X-User-ID` is the
        `id` of the acting `CustomerSite`; ownership checks on any resource that
        references a `CustomerSite` compare the resource's `site_id` foreign-key
        field to `X-User-ID`. A `PlantOperator` may only post level readings, open
        service tickets, approve contract-service quotes, receive deliveries, or
        cancel replenishment orders against its own site."
        PRD §2.1: "A request whose role is not permitted for the targeted endpoint,
        or that violates entity-backed ownership, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/operator_cannot_read_other_site_vessel_forbidden
        """
        site_a = create_site(name="Own A", state_code="IA")
        site_b = create_site(name="Own B", state_code="IA")
        vessel_b = create_vessel(
            site_b["id"], name="SILO-B", capacity_tons=100,
            material_name="corn", reorder_point_pct=30,
        )
        res = api.create_level_reading(
            {
                "vessel_id": vessel_b["id"],
                "measured_at": "2026-08-02T00:00:00Z",
                "level_pct": 50.0,
            },
            make_plant_operator_headers(site_a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_technician_cannot_start_others_ticket_forbidden(self, api):
        """PRD §3.9: "The assigned `Technician` starts a `SCHEDULED` ticket. The
        acting technician's `X-User-ID` must equal the ticket's `technician_id`
        (otherwise `ERR_FORBIDDEN`)."

        Design: Corner/rbac/technician_cannot_start_others_ticket_forbidden
        """
        site, vessel, tech_one = create_site_vessel_technician(
            site_overrides={"name": "TO Site", "state_code": "IA"},
            vessel_overrides={
                "name": "BIN-TO", "vessel_kind": "BIN", "capacity_tons": 50,
                "material_name": "salt", "reorder_point_pct": 30,
            },
            tech_overrides={"name": "Tech One", "weekly_capacity_hours": 40},
        )
        tech_two = create_technician(name="Tech Two", weekly_capacity_hours=40)
        ticket = create_scheduled_ticket(
            site["id"], vessel["id"], tech_one["id"],
            window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T10:00:00Z",
            job_type="INSPECTION", requires_entry=False, est_hours=2, crew_size=1,
        )
        res = api.start_service_ticket(
            ticket["id"], make_technician_headers(tech_two["id"])
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        fetched = validate_success(api.get_service_ticket(ticket["id"], SM), 200)
        assert fetched["status"] == "SCHEDULED"


class TestOptimisticConcurrency:
    def test_occ_stale_vessel_version_rejected(self, api):
        """PRD §2.8: "One endpoint participates in optimistic concurrency control:
        `PATCH /vessels/{id}`. A request to update a vessel's monitoring
        configuration must include `expected_vessel_version` carrying the vessel's
        `version` as last observed by the caller. If the supplied value does not
        match the vessel's current `version` on the server, the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from silently
        overwriting a configuration change it never saw."

        Design: Corner/cross_cutting_layers/occ_stale_vessel_version_rejected
        """
        site = create_site(name="OC Site", state_code="IA")
        vessel = create_vessel(
            site["id"], name="SILO-OC", capacity_tons=100,
            material_name="corn", reorder_point_pct=30,
        )
        observed_version = vessel["version"]

        updated = validate_success(
            api.patch_vessel(
                vessel["id"],
                {
                    "expected_vessel_version": observed_version,
                    "reorder_point_pct": 35,
                },
                SM,
            ),
            200,
        )
        assert updated["reorder_point_pct"] == 35
        assert updated["version"] == observed_version + 1

        res = api.patch_vessel(
            vessel["id"],
            {
                "expected_vessel_version": observed_version,
                "reorder_point_pct": 40,
            },
            SM,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        fetched = validate_success(api.get_vessel(vessel["id"], SM), 200)
        # rejected write did not apply
        assert fetched["reorder_point_pct"] == 35


class TestEnvelopeAndPagination:
    def test_list_pagination_limit_and_has_more(self, api):
        """PRD §2.3: "List endpoints accept two pagination query parameters.
        `limit` controls the maximum number of items returned; it defaults to 10,
        with a minimum of 1 and a maximum of 100. `offset` controls how many items
        to skip and defaults to 0. Unless otherwise specified, list endpoints
        return resources sorted by `created_at` ascending. The `meta` block of
        every list response includes `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/list_pagination_limit_and_has_more
        """
        site, vessel = create_site_with_vessel(
            site_overrides={"name": "PG Site", "state_code": "IA"},
            vessel_overrides={
                "name": "BIN-PG", "vessel_kind": "BIN", "capacity_tons": 50,
                "material_name": "salt", "reorder_point_pct": 30,
            },
        )
        t1 = create_draft_ticket(
            site["id"], vessel["id"],
            job_type="INSPECTION", requires_entry=False, est_hours=2, crew_size=1,
        )
        t2 = create_draft_ticket(
            site["id"], vessel["id"],
            job_type="DIAGNOSIS", requires_entry=False, est_hours=1, crew_size=1,
        )

        page1, meta1 = validate_paginated(
            api.list_service_tickets(SM, params={"limit": 1, "offset": 0})
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_service_tickets(SM, params={"limit": 1, "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

        ids = {page1[0]["id"], page2[0]["id"]}
        assert ids == {t1["id"], t2["id"]}

    def test_list_filter_returns_only_matching(self, api):
        """PRD §2.3: "List endpoints accept two pagination query parameters.
        `limit` controls the maximum number of items returned; it defaults to 10,
        with a minimum of 1 and a maximum of 100. `offset` controls how many items
        to skip and defaults to 0."
        PRD §3.1: "A `Vessel` is registered under a site via a payload containing
        `site_id`, a vessel tag `name` (e.g. `SILO-3`), a `vessel_kind` of `SILO`,
        `BIN`, or `HOPPER`, a `capacity_tons` (must be greater than zero), and the
        `material_name` of the stored bulk solid."

        Design: Corner/endpoints/list_filter_returns_only_matching
        """
        site_1 = create_site(name="F1", state_code="IA")
        site_2 = create_site(name="F2", state_code="IA")
        v1 = create_vessel(site_1["id"], name="BIN-F1", vessel_kind="BIN",
                           capacity_tons=50, material_name="salt",
                           reorder_point_pct=30)
        v2 = create_vessel(site_2["id"], name="BIN-F2", vessel_kind="BIN",
                           capacity_tons=50, material_name="sugar",
                           reorder_point_pct=30)
        data, meta = validate_paginated(
            api.list_vessels(SM, params={"site_id": site_1["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == v1["id"]
        assert all(item["id"] != v2["id"] for item in data)

    def test_success_and_error_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error. The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/success_and_error_envelope_shape
        """
        import requests as _requests  # noqa: F401  (envelope inspection below)

        site = create_site(name="ENV Site", state_code="IA")

        success_res = api.get_site(site["id"], SM)
        body = success_res.json()
        assert success_res.status_code == 200
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "object"
        assert body["data"]["id"] == site["id"]

        error_res = api.get_site(
            "00000000-0000-0000-0000-000000000099", SM
        )
        err_body = error_res.json()
        assert error_res.status_code == 404
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_SITE_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"].strip()) > 0


class TestImmediateConsistency:
    def test_completion_invoice_immediately_visible(self, api):
        """PRD §3.9: "`invoice_labor_cents` is `actual_hours` multiplied by the
        per-crew-hour rate for the ticket's `job_type` (the same rate table as
        §3.6: 9500 / 14500 / 11000 / 22000 / 18000 cents for `DIAGNOSIS` /
        `CLEANOUT` / `INSPECTION` / `RETROFIT_AERATION` / `RETROFIT_VIBRATOR`
        respectively) multiplied by `crew_size`, rounded half up to integer cents."
        PRD §3.9: "`invoice_total_cents` is the taxable amount plus
        `invoice_tax_cents`."

        Design: Corner/consistency_model/completion_invoice_immediately_visible
        """
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={"name": "IC Site", "state_code": "IA"},
            vessel_overrides={
                "name": "BIN-IC", "vessel_kind": "BIN", "capacity_tons": 50,
                "material_name": "salt", "reorder_point_pct": 30,
            },
            tech_overrides={"name": "Tech I", "weekly_capacity_hours": 40},
        )
        ticket = create_in_progress_ticket(
            site["id"], vessel["id"], tech["id"],
            window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T10:00:00Z",
            job_type="INSPECTION", requires_entry=False, est_hours=2, crew_size=1,
        )
        completed = validate_success(
            api.complete_service_ticket(
                ticket["id"],
                {"actual_hours": 2, "mileage_miles": 0, "disposal_tons": 0},
                make_technician_headers(tech["id"]),
            ),
            200,
        )
        # labor 22000; discount 0; tax round(22000 x 0.06) = 1320
        assert completed["invoice_total_cents"] == 23320

        fetched = validate_success(api.get_service_ticket(ticket["id"], SM), 200)
        assert fetched["status"] == "COMPLETED"
        # immediate consistency: identical value on the subsequent read
        assert fetched["invoice_total_cents"] == 23320

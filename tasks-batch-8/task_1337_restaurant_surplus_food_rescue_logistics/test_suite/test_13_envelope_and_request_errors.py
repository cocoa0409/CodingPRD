"""Response envelopes, pagination, not-found codes, auth headers, and
schema-level 400s (PRD §2.1-§2.3, §2.7-§2.8)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_donor, create_agency, create_driver, add_window, create_cooler,
    create_offer, set_clock, dispatch_run, respond_run, get_offer_version,
    get_donor_version,
    make_donor_coordinator_headers, make_volunteer_driver_headers,
)
from test_helpers.factories import (
    create_donor_site_payload, create_donation_offer_payload,
)

ADMIN = TEST_USERS["admin_headers"]


class TestPaginationEnvelope:
    def test_list_pagination_fields_and_pages(self, api):
        """PRD §2.3: "List endpoints accept two query parameters. `limit`
        defaults to 10, with a minimum of 1 and a maximum of 100; `offset`
        defaults to 0. Results are always sorted by `created_at` in ascending
        order. The `meta` block of a list response carries exactly four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_envelope_fields
        """
        donor = create_donor(legal_name="Page Bistro", ein="100000018",
                             contact_email="pg@bistro.example", activate=False)
        headers = make_donor_coordinator_headers(donor["id"])
        for i, (cat, day) in enumerate(
                [("SHELF_STABLE", "02"), ("PRODUCE", "03"), ("SHELF_STABLE", "04")]):
            resp = api.create_donation_offer(
                create_donation_offer_payload(
                    donor_site_id=donor["id"], food_category=cat,
                    estimated_weight_lbs=5 + 2 * i,
                    pickup_window_start=f"2026-08-{day}T10:00:00Z",
                    pickup_window_end=f"2026-08-{day}T12:00:00Z"),
                headers)
            assert resp.status_code == 201, f"Setup failed: {resp.text}"
        page1, meta1 = validate_paginated(api.list_donor_offers(
            donor["id"], headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(api.list_donor_offers(
            donor["id"], headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestErrorEnvelope:
    def test_error_envelope_shape_on_404(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format:"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/error_envelope_shape_on_404
        """
        resp = api.get_donor_site("00000000-0000-4000-8000-0000000000d9", ADMIN)
        error_data = validate_error(resp, ApiErrorId.ERR_DONOR_NOT_FOUND)
        assert isinstance(error_data.get("message"), str) and error_data["message"]


class TestNotFoundCodes:
    def test_every_resource_family_has_its_own_404(self, api):
        """PRD §2.7: "Identifier existence is validated left to right along the
        URL path, and only after the path resolves are body-supplied foreign
        keys — `offer_id`, `driver_id`, `agency_id`, and each entry of
        `cooler_ids` — checked for existence. Each missing resource surfaces its
        own not-found error: `ERR_DONOR_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`,
        `ERR_DRIVER_NOT_FOUND`, `ERR_COOLER_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`,
        `ERR_RUN_NOT_FOUND`, or `ERR_STRIKE_REPORT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_nonexistent_resources_returns_not_found
        """
        driver = create_driver(full_name="V N", email="vnf@example.com",
                               vehicle_capacity_lbs=300, cooler_slot_count=1,
                               activate=False)
        cases = [
            ("GET agency", api.get_recipient_agency(
                "00000000-0000-4000-8000-0000000000aa", ADMIN),
             ApiErrorId.ERR_AGENCY_NOT_FOUND),
            ("GET driver", api.get_volunteer_driver(
                "00000000-0000-4000-8000-0000000000ab", ADMIN),
             ApiErrorId.ERR_DRIVER_NOT_FOUND),
            ("GET cooler", api.get_cooler(
                "00000000-0000-4000-8000-0000000000ac", ADMIN),
             ApiErrorId.ERR_COOLER_NOT_FOUND),
            ("GET offer", api.get_donation_offer(
                "00000000-0000-4000-8000-0000000000ad", ADMIN),
             ApiErrorId.ERR_OFFER_NOT_FOUND),
            ("respond run", api.respond_rescue_run(
                "00000000-0000-4000-8000-0000000000ae", "ACCEPT",
                make_volunteer_driver_headers(driver["id"])),
             ApiErrorId.ERR_RUN_NOT_FOUND),
            ("adjudicate strike", api.adjudicate_strike_report(
                "00000000-0000-4000-8000-0000000000af", "UPHELD", ADMIN),
             ApiErrorId.ERR_STRIKE_REPORT_NOT_FOUND),
        ]
        for label, resp, error_id in cases:
            validate_error(resp, error_id), label


class TestAuthHeader:
    def test_missing_auth_headers_rejected_before_anything(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID`,
        identifying the caller, and `X-User-Role`, naming the caller's role. If
        either header is missing or empty, or the role value is not one of the
        declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/missing_auth_header_returns_400
        """
        # No X-User-* headers at all: the tier-1 check outranks even 404s.
        resp = api.get_donor_site("00000000-0000-4000-8000-0000000000d8", {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestInvalidRequestVariants:
    def _setup(self, api):
        donor = create_donor(legal_name="IR Bistro", ein="100000019",
                             contact_email="ir@bistro.example")
        agency = create_agency(name="AG",
                               accepts_categories=("COLD_HELD", "SHELF_STABLE"),
                               capacity_cold_held_lbs=100,
                               capacity_shelf_stable_lbs=100)
        driver = create_driver(cold_chain_certified=True, cooler_slot_count=1)
        add_window(driver["id"])
        cooler = create_cooler(label="C1")
        os_offer = create_offer(donor["id"], food_category="SHELF_STABLE",
                                estimated_weight_lbs=5, publish=True)
        oc_offer = create_offer(donor["id"], food_category="COLD_HELD",
                                estimated_weight_lbs=10,
                                pickup_window_start="2026-08-02T13:00:00Z",
                                pickup_window_end="2026-08-02T14:00:00Z",
                                publish=True)
        set_clock("2026-08-02T09:30:00Z")
        rc = dispatch_run(oc_offer["id"], driver_id=driver["id"],
                          agency_id=agency["id"], cooler_ids=[cooler["id"]])
        respond_run(rc["id"], driver["id"], "ACCEPT")
        return {"donor": donor, "agency": agency, "driver": driver,
                "cooler": cooler, "os": os_offer, "oc": oc_offer, "rc": rc}

    def test_offer_and_donor_payload_variants(self, api):
        """PRD §2.8: "3. **Body well-formedness** — required fields present, no
        unknown fields, correct types, valid enum members, positive integers
        where noted, `window_end` after `window_start`, pickup window length
        within the permitted band"
        PRD §3.2: "The window's length must be at least 30 minutes and no more
        than 240 minutes — four hours."

        Design: Corner/errors/invalid_request_variants
        """
        s = self._setup(api)
        headers = make_donor_coordinator_headers(s["donor"]["id"])
        # Missing required field (ein).
        resp = api.create_donor_site(
            {"legal_name": "No EIN", "contact_email": "x@bistro.example"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # Enum member outside the declared food categories.
        resp = api.create_donation_offer(
            create_donation_offer_payload(
                donor_site_id=s["donor"]["id"], food_category="FROZEN",
                estimated_weight_lbs=5,
                pickup_window_start="2026-08-03T10:00:00Z",
                pickup_window_end="2026-08-03T12:00:00Z"),
            headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # window_end not after window_start.
        resp = api.create_donation_offer(
            create_donation_offer_payload(
                donor_site_id=s["donor"]["id"], food_category="SHELF_STABLE",
                estimated_weight_lbs=5,
                pickup_window_start="2026-08-03T12:00:00Z",
                pickup_window_end="2026-08-03T10:00:00Z"),
            headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # 20-minute window: below the 30-minute minimum.
        resp = api.create_donation_offer(
            create_donation_offer_payload(
                donor_site_id=s["donor"]["id"], food_category="SHELF_STABLE",
                estimated_weight_lbs=5,
                pickup_window_start="2026-08-03T10:00:00Z",
                pickup_window_end="2026-08-03T10:20:00Z"),
            headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # 300-minute window: above the 240-minute maximum.
        resp = api.create_donation_offer(
            create_donation_offer_payload(
                donor_site_id=s["donor"]["id"], food_category="SHELF_STABLE",
                estimated_weight_lbs=5,
                pickup_window_start="2026-08-03T10:00:00Z",
                pickup_window_end="2026-08-03T15:00:00Z"),
            headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_dispatch_pickup_delivery_and_period_variants(self, api):
        """PRD §3.3: "For non-cold-chain offers, `cooler_ids` must be omitted or
        empty (anything else is `ERR_INVALID_REQUEST`) and no reservation is
        created at all."
        PRD §3.8: "The period must be ordered — start strictly before end — and
        `period_end` must not lie after the current logical clock, else
        `ERR_INVALID_REQUEST`."
        PRD §3.4: "the `attestation_confirmed` flag, which must be true because
        it is the Good-Samaritan liability attestation, its absence answering
        `ERR_INVALID_REQUEST`;"
        PRD §3.4: "`arrival_time`, which must sit on or after `pickup_time` and
        on or before the current logical clock;"

        Design: Corner/errors/invalid_request_variants
        """
        s = self._setup(api)
        # cooler_ids supplied for a non-cold-chain (SHELF_STABLE) offer.
        payload = {"offer_id": s["os"]["id"],
                   "expected_offer_version": get_offer_version(s["os"]["id"]),
                   "driver_id": s["driver"]["id"], "agency_id": s["agency"]["id"],
                   "cooler_ids": [s["cooler"]["id"]]}
        resp = api.create_rescue_run(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # Inverted tax period: period_start >= period_end. The fresh donor
        # version is supplied so the inverted period is the ONLY violation.
        resp = api.issue_tax_receipt(
            s["donor"]["id"],
            {"period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-08-01T00:00:00Z",
             "expected_donor_version": get_donor_version(s["donor"]["id"])},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # The liability attestation must be affirmed.
        set_clock("2026-08-02T10:15:00Z")
        resp = api.record_pickup(
            s["rc"]["id"],
            {"pickup_time": "2026-08-02T10:15:00Z", "pickup_temp_f": 35.0,
             "attestation_confirmed": False},
            make_volunteer_driver_headers(s["driver"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # A rejected pickup mutates nothing: the affirmed retry succeeds.
        resp = api.record_pickup(
            s["rc"]["id"],
            {"pickup_time": "2026-08-02T10:15:00Z", "pickup_temp_f": 35.0,
             "attestation_confirmed": True},
            make_volunteer_driver_headers(s["driver"]["id"]))
        validate_success(resp)
        # arrival_time before pickup_time.
        set_clock("2026-08-02T11:00:00Z")
        resp = api.record_delivery(
            s["rc"]["id"],
            {"arrival_time": "2026-08-02T10:00:00Z", "arrival_temp_f": 38.0,
             "actual_weight_lbs": 10},
            make_volunteer_driver_headers(s["driver"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

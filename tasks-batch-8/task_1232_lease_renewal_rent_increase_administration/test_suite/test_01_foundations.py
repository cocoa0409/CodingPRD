"""Portfolio foundations: policies, properties, units, residents, leases (PRD §3.1–§3.2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_lease,
    assert_rent_cap_policy,
    assert_resident,
    ca_oak_policy_payload,
    create_lease,
    create_lease_payload,
    create_policy,
    create_policy_payload,
    create_property,
    create_property_payload,
    create_resident,
    create_resident_payload,
    create_unit,
    create_unit_payload,
    is_valid_uuid,
    is_iso8601_timestamp,
    setup_lease_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PM1 = TEST_USERS["pm_1_headers"]
LA1 = TEST_USERS["la_1_headers"]


class TestRentCapPolicies:
    def test_create_policy_success_computed_effective_cap(self, api):
        """PRD §2.8: "The policy's governing ceiling — its `effective_cap_bps` — is
        derived, never entered directly: it is the lesser of the base cap plus the
        CPI pass-through on one side and the absolute statutory hard ceiling on the
        other. This derivation runs at policy creation and again on every policy
        update, so the stored value always reflects the current components."

        Design: Corner/entities/create_policy_success_computed_effective_cap
        """
        resp = api.create_rent_cap_policy(ca_oak_policy_payload(), ADMIN)
        data = validate_success(resp, 201)
        assert_rent_cap_policy(data)
        assert data["effective_cap_bps"] == 550, (
            f"min(400+150, 900) must be 550, got {data['effective_cap_bps']}"
        )
        assert data["version"] == 1

    def test_create_policy_missing_required_returns_invalid_request(self, api):
        """PRD §2.9: "Required fields must be present, types correct, enum members
        valid, dates well-formed `YYYY-MM-DD`, and integer ranges honored — for
        example `term_months` must be at least 1, a property's `min_term_months` must
        not exceed its `max_term_months`, a resident response's `response_type` must
        be one of `ACCEPT`, `DECLINE`, or `COUNTER`, a `COUNTER` response must carry
        a `counter_rent_cents` greater than zero, and a notice citing
        `LEASE_VIOLATION` must carry an `evidence_ref`. Any failure returns
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_policy_missing_required_returns_invalid_request
        """
        payload = ca_oak_policy_payload()
        del payload["base_cap_bps"]
        resp = api.create_rent_cap_policy(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_jurisdiction_rejected(self, api):
        """PRD §3.1: "Each jurisdiction's rent-control ordinance becomes a
        **RentCapPolicy** carrying a unique `jurisdiction_code` — a duplicate
        submission is rejected with `ERR_DUPLICATE_JURISDICTION` — along with the
        `base_cap_bps` and `cpi_adjustment_bps` components (both non-negative integer
        basis points), the absolute `hard_ceiling_bps`, the
        `high_increase_threshold_bps` at which the long notice period engages, the two
        notice tiers `notice_days_low` and `notice_days_high`, and the
        `non_renewal_notice_days` lead time required when ending a tenancy."

        Design: Corner/entities/duplicate_jurisdiction_rejected
        """
        create_policy(ca_oak_policy_payload())
        second = ca_oak_policy_payload()
        second.update({"base_cap_bps": 300, "cpi_adjustment_bps": 100,
                       "hard_ceiling_bps": 800, "high_increase_threshold_bps": 400,
                       "notice_days_low": 30, "notice_days_high": 60,
                       "non_renewal_notice_days": 30})
        resp = api.create_rent_cap_policy(second, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_JURISDICTION)

    def test_effective_cap_ceiling_binds(self, api):
        """PRD §2.8: "The policy's governing ceiling — its `effective_cap_bps` — is
        derived, never entered directly: it is the lesser of the base cap plus the
        CPI pass-through on one side and the absolute statutory hard ceiling on the
        other."

        Design: Corner/calculations/effective_cap_ceiling_binds
        """
        payload = ca_oak_policy_payload()
        payload.update({
            "jurisdiction_code": "WA-SEA",
            "cpi_adjustment_bps": 700,   # 400 + 700 = 1100 > ceiling 900
            "notice_days_low": 30,
        })
        resp = api.create_rent_cap_policy(payload, ADMIN)
        data = validate_success(resp, 201)
        assert data["effective_cap_bps"] == 900, (
            f"hard ceiling must bind: expected 900, got {data['effective_cap_bps']}"
        )


class TestPropertiesUnitsResidents:
    def test_create_unit_duplicate_number_rejected(self, api):
        """PRD §3.1: "Each rentable **Unit** is created under a property via
        `property_id` (an unknown property id yields `ERR_PROPERTY_NOT_FOUND`) with a
        `unit_number` unique within that property — a collision is rejected with
        `ERR_DUPLICATE_UNIT_NUMBER` — a non-negative `bedrooms` count, and the unit's
        `current_market_rent_cents`, which feeds the pricing gap calculation in §3.3."

        Design: Corner/entities/create_unit_duplicate_number_rejected
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="Duplex Court")
        create_unit(prop["id"], market_rent_cents=210000, unit_number="101")
        resp = api.create_unit(
            create_unit_payload(prop["id"], unit_number="101", bedrooms=2,
                                current_market_rent_cents=220000),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER)

    def test_system_fields_server_minted_on_resident(self, api):
        """PRD §2.5: "The `id` is a server-minted unique identifier formatted as a
        bare UUID, with no type prefix. The `created_at` timestamp records creation
        as an ISO 8601 UTC instant with three fractional digits. The `updated_at`
        timestamp follows the same format and refreshes on every modification. The
        `version` is an integer that increments by one with every mutation of the
        resource, whether the mutation came from a client request or from a
        system-side cascade or clock sweep."

        Design: Corner/entities/system_fields_server_minted_on_resident
        """
        resp = api.create_resident(
            create_resident_payload(full_name="Sys Field", email="sys.field@x.com"), ADMIN)
        data = validate_success(resp, 201)
        assert_resident(data)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert data["version"] == 1
        fetched = validate_success(api.get_resident(data["id"], PM1), 200)
        assert fetched["full_name"] == "Sys Field"

    def test_resource_read_not_found_returns_404(self, api):
        """PRD §2.9: "Path resource identifiers are validated left to right — the
        request is rejected with the not-found error of the first missing identifier
        — and then body foreign keys (`unit_id`, `resident_id`, `rent_cap_policy_id`)
        are validated. The nine errors are `ERR_POLICY_NOT_FOUND`,
        `ERR_PROPERTY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`,
        `ERR_LEASE_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CONCESSION_NOT_FOUND`,
        `ERR_NOTICE_NOT_FOUND`, and `ERR_DOCUMENT_NOT_FOUND`."

        Design: Corner/entities/resource_read_not_found_returns_404
        """
        cases = [
            (api.get_lease("00000000-0000-4000-8000-0000000000aa", PM1),
             ApiErrorId.ERR_LEASE_NOT_FOUND),
            (api.get_renewal_offer("00000000-0000-4000-8000-0000000000ab", PM1),
             ApiErrorId.ERR_OFFER_NOT_FOUND),
            (api.get_non_renewal_notice("00000000-0000-4000-8000-0000000000ac", PM1),
             ApiErrorId.ERR_NOTICE_NOT_FOUND),
            (api.get_renewal_document("00000000-0000-4000-8000-0000000000ad", PM1),
             ApiErrorId.ERR_DOCUMENT_NOT_FOUND),
            (api.get_rent_cap_policy("00000000-0000-4000-8000-0000000000ae", PM1),
             ApiErrorId.ERR_POLICY_NOT_FOUND),
            (api.get_property("00000000-0000-4000-8000-0000000000af", PM1),
             ApiErrorId.ERR_PROPERTY_NOT_FOUND),
            (api.get_unit("00000000-0000-4000-8000-0000000000b0", PM1),
             ApiErrorId.ERR_UNIT_NOT_FOUND),
            (api.get_resident("00000000-0000-4000-8000-0000000000b1", PM1),
             ApiErrorId.ERR_RESIDENT_NOT_FOUND),
            (api.get_concession_approval("00000000-0000-4000-8000-0000000000b2", PM1),
             ApiErrorId.ERR_CONCESSION_NOT_FOUND),
        ]
        for resp, expected in cases:
            validate_error(resp, expected)

    def test_body_fk_existence_not_found(self, api):
        """PRD §2.9: "Path resource identifiers are validated left to right — the
        request is rejected with the not-found error of the first missing identifier
        — and then body foreign keys (`unit_id`, `resident_id`, `rent_cap_policy_id`)
        are validated."
        PRD §3.1: "A **Property** is then registered with a display `name`, the
        `rent_cap_policy_id` of its governing policy (an unknown policy id is
        rejected with `ERR_POLICY_NOT_FOUND`)"
        PRD §3.2: "Unknown unit or resident ids are rejected with
        `ERR_UNIT_NOT_FOUND` and `ERR_RESIDENT_NOT_FOUND` respectively."

        Design: Corner/entities/body_fk_existence_not_found
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="FK Court")
        unit = create_unit(prop["id"], unit_number="105")
        resident = create_resident(full_name="FK Res", email="fk.res@x.com")

        resp = api.create_property(
            create_property_payload("00000000-0000-4000-8000-0000000000c1", name="Ghost"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_FOUND)

        resp = api.create_unit(
            create_unit_payload("00000000-0000-4000-8000-0000000000c2", unit_number="106"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND)

        resp = api.create_lease(
            create_lease_payload("00000000-0000-4000-8000-0000000000c3", resident["id"]),
            PM1)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_FOUND)

        resp = api.create_lease(
            create_lease_payload(unit["id"], "00000000-0000-4000-8000-0000000000c4"),
            PM1)
        validate_error(resp, ApiErrorId.ERR_RESIDENT_NOT_FOUND)


class TestLeaseCreation:
    def test_create_lease_computed_term_end_and_denormalized_property(self, api):
        """PRD §3.2: "At creation the system derives the lease's `term_end_date` by
        adding `term_months` calendar months to the start date — preserving the day
        of month and clamping to month length — and treats the occupancy as the
        half-open interval that includes the start date and excludes the end date.
        The lease's `property_id` is denormalized from its unit at creation so that
        property-scoped queries and calculations never chase the join."
        PRD §3.2: "A lease is born in `ACTIVE` status; `ENDED` is its terminal status."

        Design: Corner/entities/create_lease_computed_term_end_and_denormalized_property
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="Compute Court")
        unit = create_unit(prop["id"], unit_number="102")
        resident = create_resident(full_name="Ana Bea", email="ana.bea@x.com")
        resp = api.create_lease(create_lease_payload(unit["id"], resident["id"]), PM1)
        data = validate_success(resp, 201)
        assert_lease(data)
        assert data["term_end_date"] == "2027-06-01", (
            f"2026-06-01 + 12 calendar months must be 2027-06-01, got {data['term_end_date']}"
        )
        assert data["property_id"] == prop["id"], (
            "property_id must be denormalized from the unit, not client-supplied"
        )
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1

    def test_unit_lease_half_open_overlap_rejected(self, api):
        """PRD §3.2: "A new lease is rejected with `ERR_LEASE_TERM_OVERLAP` when its
        half-open interval would intersect the interval of any other non-`ENDED`
        lease on the same unit."

        Design: Difficulty/resource_temporal_overlap/unit_lease_half_open_overlap_rejected
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="Overlap Court")
        unit = create_unit(prop["id"], unit_number="1101")
        ra = create_resident(full_name="Res Alpha", email="res.alpha@x.com")
        rb = create_resident(full_name="Res Beta", email="res.beta@x.com")
        create_lease(unit["id"], ra["id"])  # occupies [2026-06-01, 2027-06-01)

        resp = api.create_lease(
            create_lease_payload(unit["id"], rb["id"], term_start_date="2027-05-15",
                                 monthly_rent_cents=205000),
            PM1)
        validate_error(resp, ApiErrorId.ERR_LEASE_TERM_OVERLAP)

    def test_unit_lease_zero_gap_adjacency_accepted(self, api):
        """PRD §3.2: "At creation the system derives the lease's `term_end_date` by
        adding `term_months` calendar months to the start date — preserving the day
        of month and clamping to month length — and treats the occupancy as the
        half-open interval that includes the start date and excludes the end date."
        PRD §3.2: "A new lease is rejected with `ERR_LEASE_TERM_OVERLAP` when its
        half-open interval would intersect the interval of any other non-`ENDED`
        lease on the same unit."

        Design: Difficulty/resource_temporal_overlap/unit_lease_half_open_overlap_rejected
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="Overlap Court")
        unit = create_unit(prop["id"], unit_number="1101")
        ra = create_resident(full_name="Res Alpha", email="res.alpha@x.com")
        rb = create_resident(full_name="Res Beta", email="res.beta@x.com")
        create_lease(unit["id"], ra["id"])  # occupies [2026-06-01, 2027-06-01)

        resp = api.create_lease(
            create_lease_payload(unit["id"], rb["id"], term_start_date="2027-06-01",
                                 monthly_rent_cents=205000),
            PM1)
        data = validate_success(resp, 201)
        assert data["term_end_date"] == "2028-06-01", (
            "zero-gap adjacency at the half-open end must be accepted"
        )


class TestLeaseListing:
    def test_list_leases_pagination_and_filter(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100. The `offset` parameter skips a number of items from the
        start of the result set and defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.2: "Leases may be listed with `unit_id`, `property_id`, `resident_id`,
        or `status` filters"

        Design: Corner/endpoints/list_leases_pagination_and_filter
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="Page Court")
        for i in range(1, 4):
            unit = create_unit(prop["id"], unit_number=f"P{i}")
            resident = create_resident(full_name=f"Pag E{i}", email=f"pag.e{i}@x.com")
            create_lease(unit["id"], resident["id"])

        page1, meta1 = validate_paginated(
            api.list_leases(LA1, params={"property_id": prop["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_leases(LA1, params={"property_id": prop["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        mtm, meta3 = validate_paginated(
            api.list_leases(LA1, params={"property_id": prop["id"], "status": "MTM"}))
        assert mtm == []
        assert meta3["total_count"] == 0

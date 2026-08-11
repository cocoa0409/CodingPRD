"""Entity creation, defaults, computed fields, retrieval corners
(PRD 2.4, 3.1, 3.2, 3.6)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    TEST_USERS,
    assert_case,
    assert_instant_equal,
    assert_landlord,
    assert_unit,
    create_case_payload,
    create_landlord_payload,
    create_unit_payload,
    get_case,
    make_landlord_headers,
    set_clock,
    setup_case_draft,
    setup_case_notice_active,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


class TestLandlordCreationSystemFields:
    """Corner instance: POST /api/landlords returns 201 with server-minted
    id, created_at, version == 1."""

    def test_landlord_created_with_system_fields(self, api):
        """PRD 2.4: "id (string): a unique, server-minted identifier
        formatted as a UUID ... version (integer): a system-managed integer
        that increments with every modification". PRD 3.1: "A PlatformAdmin
        onboards each landlord by registering a record with a legal_name and
        a contact_email."

        Design: Corner/entities/landlord_creation_system_fields
        """
        resp = api.create_landlord(
            create_landlord_payload(legal_name="Acme Homes",
                                    contact_email="a@x.com"),
            TEST_USERS["admin_headers"],
        )
        data = validate_success(resp, 201)
        assert_landlord(data)
        assert data["version"] == 1
        assert data["legal_name"] == "Acme Homes"
        assert data["created_at"]


class TestUnitDefaultsToVacant:
    """Corner instance: a new RentalUnit starts VACANT without the client
    passing any status."""

    def test_new_unit_is_vacant(self, api):
        """PRD 3.1: "A new unit begins life with status VACANT."

        Design: Corner/entities/unit_defaults_to_vacant
        """
        landlord = validate_success(api.create_landlord(
            create_landlord_payload(), TEST_USERS["admin_headers"]), 201)
        ll = make_landlord_headers(landlord["id"])
        resp = api.create_unit(
            create_unit_payload(landlord["id"], "TX", street_address="5 S St",
                                unit_label="1"),
            ll,
        )
        unit = validate_success(resp, 201)
        assert_unit(unit)
        assert unit["status"] == "VACANT"


class TestNoticeComputedCureSchedule:
    """Corner instance: OH CURE_OR_QUIT computes statutory_cure_days 7 and
    cure_deadline end-of-day."""

    def test_oh_cure_or_quit_schedule(self, api):
        """PRD 3.2: "in OH it is 5, 7, and 0 days." and "The
        cure_deadline falls at 23:59:59Z on the calendar date that is
        statutory_cure_days days after served_on."

        Design: Corner/entities/notice_computed_cure_schedule
        """
        ctx = setup_case_notice_active(
            "OH", case_reason="LEASE_VIOLATION", notice_type="CURE_OR_QUIT",
            served_on="2026-05-02",
            violation_description="unauthorized pet",
        )
        notice = ctx["notice"]
        assert notice["statutory_cure_days"] == 7
        assert_instant_equal(notice["cure_deadline"], "2026-05-09T23:59:59Z")
        assert notice["status"] == "PENDING"

    def test_ca_unconditional_quit_zero_days(self, api):
        """PRD 3.2: "In CA the period is 3 days for PAY_OR_QUIT, 3 days for
        CURE_OR_QUIT, and 0 days for UNCONDITIONAL_QUIT".

        Design: Corner/entities/notice_computed_cure_schedule
        """
        ctx = setup_case_notice_active(
            "CA", case_reason="SEVERE", notice_type="UNCONDITIONAL_QUIT",
            served_on="2026-05-02",
            clock_before_notice="2026-05-02T10:00:00Z",
        )
        notice = ctx["notice"]
        assert notice["statutory_cure_days"] == 0
        assert_instant_equal(notice["cure_deadline"], "2026-05-02T23:59:59Z")


class TestJudgmentReverseListEmptyBeforeEntry:
    """Corner instance: GET /api/cases/{id}/judgment returns an empty array
    before any judgment exists."""

    def test_empty_array_before_judgment(self, api):
        """PRD 3.6: "reading the case's judgment yields an array of zero or
        one element." PRD 2.3: "The meta object of a list response carries
        the pagination fields limit, offset, total_count, and has_more."

        Design: Corner/entities/judgment_reverse_list_empty_before_entry
        """
        ctx = setup_case_draft("CA")
        resp = api.get_case_judgment(ctx["case"]["id"], CLERK_A)
        data, meta = validate_paginated(resp)
        assert data == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False


class TestUnitOccupancyDerivedAndBlocks:
    """Corner instance: tenancy flips the unit to OCCUPIED and blocks a
    second tenancy."""

    def test_second_tenancy_rejected_while_occupied(self, api):
        """PRD 3.1: "Creation is refused with ERR_UNIT_OCCUPIED (HTTP 409)
        when any other ACTIVE tenancy already exists for the unit; on success
        the unit moves from VACANT to OCCUPIED."

        Design: Corner/cross_cutting_complexity_layers/unit_occupancy_derived_and_blocks_second_tenancy
        """
        landlord = validate_success(api.create_landlord(
            create_landlord_payload(), TEST_USERS["admin_headers"]), 201)
        ll = make_landlord_headers(landlord["id"])
        unit = validate_success(api.create_unit(
            create_unit_payload(landlord["id"], "CA"), ll), 201)

        t1 = validate_success(api.create_tenancy(
            {"unit_id": unit["id"], "tenant_full_name": "T1",
             "monthly_rent_cents": 150000, "lease_start_date": "2026-01-01"},
            ll), 201)
        assert t1["status"] == "ACTIVE"
        read_unit = validate_success(api.get_unit(unit["id"], CLERK_A), 200)
        assert read_unit["status"] == "OCCUPIED"

        resp = api.create_tenancy(
            {"unit_id": unit["id"], "tenant_full_name": "T2",
             "monthly_rent_cents": 150000, "lease_start_date": "2026-02-01"},
            ll)
        validate_error(resp, ApiErrorId.ERR_UNIT_OCCUPIED, 409)

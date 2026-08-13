"""Cross-cutting API hygiene: auth-header and role/existence precedence, list
pagination defaults, and the linked hour-entry validation bundle."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, ApiErrorId,
    create_application_payload,
    set_clock, create_active_volunteer, create_department, create_role,
    create_open_request, create_published_shift, signup, signup_and_confirm,
    log_hour_entry, create_item,
    make_volunteer_headers, make_department_head_headers,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestAuthPrecedence:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the role under which
        that user acts. A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api.create_application(
            create_application_payload(full_name="No Header", email="nh@x.org"),
            headers=None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_role_denied_before_existence(self, api):
        """PRD §2.8: "Checks are evaluated in a fixed thirteen-tier order, and the
        earliest failing tier wins". Tier 3: "The caller's role appears in the
        endpoint's authorized role list — `ERR_UNAUTHORIZED_ROLE`." Tier 4:
        "Path identifiers are validated first, left to right, then body-referenced
        foreign keys in their declared order; any missing reference is
        `ERR_NOT_FOUND`."

        Design: Corner/validations/role_denied_before_existence
        """
        set_clock("2026-08-01T00:00:00Z")
        # DepartmentHead is not in POST /placements' role list; both FK ids are bogus.
        resp = api.create_placement(
            {"request_id": "11111111-2222-4333-8444-555555555555",
             "volunteer_id": "22222222-3333-4444-8555-666666666666"},
            make_department_head_headers("dh-9"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestListPagination:
    def test_pagination_defaults_and_second_page(self, api):
        """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of
        100. `offset` defaults to 0. Within a list, resources are always sorted by
        `created_at` ascending. The `meta` object of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`, so a client can page
        deterministically without re-deriving counts."

        Design: Corner/endpoints/list_pagination_defaults
        """
        set_clock("2026-08-01T00:00:00Z")
        for i in range(1, 13):
            create_item(sku=f"SKU-{i:02d}", name=f"Item {i:02d}",
                        unit_price_cents=100, unit_cost_cents=10)

        page1, meta1 = validate_paginated(api.list_items(TREASURER))
        assert len(page1) == 10, f"default limit is 10, got {len(page1)}"
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        for row in page1:
            assert isinstance(row.get("version"), int)
            assert row.get("created_at") and row.get("updated_at")

        page2, meta2 = validate_paginated(api.list_items(TREASURER, params={"offset": 10}))
        assert len(page2) == 2, f"offset=10 leaves 2 rows, got {len(page2)}"
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 12


class TestLinkedHourEntryValidation:
    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Emergency", head_user_id="dh-1")
        role = create_role(name="ED Greeter", category="PATIENT_FACING", minimum_age=18)
        request = create_open_request(dept["id"], role["id"], slots_needed=2)
        v1 = create_active_volunteer(dept, role, request, full_name="V One",
                                     email="v1@x.org", phone="555-3021")
        v2 = create_active_volunteer(dept, role, request, full_name="V Two",
                                     email="v2@x.org", phone="555-3022")
        s1 = create_published_shift(dept["id"], role["id"], "2026-08-03T08:00:00Z",
                                    "2026-08-03T12:00:00Z", capacity=2)
        s2 = create_published_shift(dept["id"], role["id"], "2026-08-04T08:00:00Z",
                                    "2026-08-04T12:00:00Z", capacity=2)
        asg1 = signup_and_confirm(s1["id"], v1["volunteer_id"])
        asg2 = signup_and_confirm(s2["id"], v2["volunteer_id"])
        # Advance past both service dates so the service-date-range gate (tier 11)
        # is satisfied and each trigger exercises exactly one failing rule.
        set_clock("2026-08-04T00:00:00Z")
        return v1, v2, asg1, asg2

    def test_hours_exceed_shift_and_ownership_mismatch(self, api):
        """PRD §3.6: "the linked assignment must belong to the same volunteer
        (`ERR_ASSIGNMENT_OWNERSHIP_MISMATCH`)"
        PRD §3.6: "`minutes` may not exceed the shift's duration in minutes
        (`ERR_HOURS_EXCEED_SHIFT`)"

        Design: Corner/errors/hour_entry_linked_validation_bundle
        """
        v1, v2, asg1, asg2 = self._setup()
        vol_id = v1["volunteer_id"]

        # 300 minutes against the 240-minute shift (own assignment).
        resp = api.create_hour_entry(
            {"volunteer_id": vol_id, "shift_assignment_id": asg1["id"],
             "service_date": "2026-08-03", "minutes": 300,
             "service_category": "PATIENT_FACING"}, make_volunteer_headers(vol_id))
        validate_error(resp, ApiErrorId.ERR_HOURS_EXCEED_SHIFT)

        # Valid minutes, but the linked assignment belongs to V2.
        resp = api.create_hour_entry(
            {"volunteer_id": vol_id, "shift_assignment_id": asg2["id"],
             "service_date": "2026-08-04", "minutes": 60,
             "service_category": "PATIENT_FACING"}, make_volunteer_headers(vol_id))
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OWNERSHIP_MISMATCH)

        entries = get_success_data(api.list_hour_entries(
            COORDINATOR, params={"volunteer_id": vol_id}))
        assert entries == [], f"no hour entry persists from either failed call, got {entries}"


class TestServiceDateRange:
    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Emergency", head_user_id="dh-1")
        role = create_role(name="ED Greeter", category="PATIENT_FACING", minimum_age=18)
        request = create_open_request(dept["id"], role["id"], slots_needed=1)
        ctx = create_active_volunteer(dept, role, request, full_name="Date Dan",
                                      email="dd2@x.org", phone="555-3023")
        shift = create_published_shift(dept["id"], role["id"], "2026-08-03T08:00:00Z",
                                       "2026-08-03T12:00:00Z", capacity=2)
        asg = signup_and_confirm(shift["id"], ctx["volunteer_id"])
        return ctx, asg

    def test_future_date_and_shift_date_mismatch_rejected(self, api):
        """PRD §3.6: "The `service_date` may not lie in the future and may not
        precede the volunteer's `joined_at` date (`ERR_SERVICE_DATE_OUT_OF_RANGE`)."
        PRD §3.6: "the entry's `service_date` must equal the linked shift's calendar
        date (also `ERR_SERVICE_DATE_OUT_OF_RANGE`)".

        Design: Corner/errors/hour_service_date_out_of_range
        """
        ctx, asg = self._setup()
        vol_id = ctx["volunteer_id"]

        resp = api.create_hour_entry(
            {"volunteer_id": vol_id, "service_date": "2026-09-01", "minutes": 60,
             "service_category": "PATIENT_FACING"}, make_volunteer_headers(vol_id))
        validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_OUT_OF_RANGE)

        # Linked entry whose date (2026-08-04) is not the shift's date (2026-08-03).
        resp = api.create_hour_entry(
            {"volunteer_id": vol_id, "shift_assignment_id": asg["id"],
             "service_date": "2026-08-04", "minutes": 60,
             "service_category": "PATIENT_FACING"}, make_volunteer_headers(vol_id))
        validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_OUT_OF_RANGE)

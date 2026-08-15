"""Global contract (envelope, pagination, auth, existence) and registry basics."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    OFFICER,
    TEST_USERS,
    ApiErrorId,
    assert_audit,
    assert_cap,
    assert_supplier,
    begin_audit,
    create_audit_payload,
    create_auditor,
    create_cap,
    create_facility,
    create_supplier,
    create_supplier_payload,
    record_finding,
    schedule_audit,
    setup_active_supplier,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["audit_coordinator_headers"]


class TestSupplierRegistration:
    def test_supplier_create_applies_system_defaults(self, api):
        """PRD §3.1: "A new supplier starts `ONBOARDING` with `provisional_score`
        and `verified_score` both at 100, `consequence_tier` at `PREFERRED`, and
        `escalation_penalty_points` at 0."
        PRD §2.4: "Every persisted resource carries `id` (a server-minted UUID
        with no type prefix) and `created_at` (an ISO 8601 UTC timestamp with
        three fractional digits, taken from the program's logical clock)."

        Design: Corner/entities/supplier_create_defaults
        """
        resp = api.create_supplier(
            create_supplier_payload(
                legal_name="Sierra Trading", country_code="VN", sector="APPAREL"
            ),
            ADMIN,
        )
        supplier = validate_success(resp, 201)
        assert_supplier(supplier)
        assert supplier["status"] == "ONBOARDING"
        assert supplier["provisional_score"] == 100
        assert supplier["verified_score"] == 100
        assert supplier["consequence_tier"] == "PREFERRED"
        assert supplier["escalation_penalty_points"] == 0
        assert isinstance(supplier["version"], int), "version is system-managed"


class TestPaginationEnvelope:
    def test_supplier_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return. If not provided, it defaults to 10, with a minimum of 1 and a
        maximum of 100."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/supplier_list_pagination_envelope
        """
        s1 = create_supplier(legal_name="Xray One", sector="FOOD")
        s2 = create_supplier(legal_name="Xray Two", sector="FOOD")

        resp1 = api.list_suppliers(OFFICER, params={"limit": 1, "offset": 0})
        assert resp1.json()["response_type"] == "array"
        assert isinstance(resp1.json()["meta"].get("api_request_id"), str)
        page1, meta1 = validate_paginated(resp1)
        assert meta1["total_count"] == 2
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        assert meta1["has_more"] is True
        assert len(page1) == 1

        page2, meta2 = validate_paginated(
            api.list_suppliers(OFFICER, params={"limit": 1, "offset": 1})
        )
        assert meta2["total_count"] == 2
        assert meta2["offset"] == 1
        assert meta2["has_more"] is False
        assert len(page2) == 1

        assert {page1[0]["id"], page2[0]["id"]} == {s1["id"], s2["id"]}

        _, meta_default = validate_paginated(api.list_suppliers(OFFICER))
        assert meta_default["limit"] == 10, "default limit is 10"
        assert meta_default["offset"] == 0, "default offset is 0"


class TestExistenceAndSchema:
    def test_audit_get_not_found_returns_404(self, api):
        """PRD §2.6: "Path identifiers and body-referenced
        identifiers (`facility_id`, `auditor_id`, `finding_id`,
        `code_version_id`, `linked_grievance_id`) must resolve to existing
        resources, validated left to right — `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/audit_get_not_found_returns_404
        """
        resp = api.get_audit(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_facility_create_missing_required_field(self, api):
        """PRD §3.2: "A `SourcingProgramAdmin` registers one under a supplier by
        providing `supplier_id`, the facility `name`, the site's ISO-2
        `country_code`, the on-site `worker_count` (at least 1), and
        `processes`, a free-form list of production processes on site."
        PRD §2.6: "Required fields present, types valid, enum values in range,
        array minimums honored"

        Design: Corner/entities/facility_create_missing_required_field
        """
        supplier = create_supplier(legal_name="Victor Supplies",
                                   sector="HARDLINES")
        payload = {
            "supplier_id": supplier["id"],
            "name": "No Workers Site",
            "country_code": "US",
            "processes": ["packing"],
        }
        resp = api.create_facility(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        listed, meta = validate_paginated(
            api.list_facilities(ADMIN, params={"supplier_id": supplier["id"]})
        )
        assert listed == [], "no facility is created when the payload is invalid"

    def test_audit_create_invalid_enum_rejected(self, api):
        """PRD §3.3: "The request names the `facility_id` and the lead
        `auditor_id`, declares an `audit_type` of `INITIAL`, `ANNUAL`,
        `RE_AUDIT`, or `FOLLOW_UP`"
        PRD §2.6: "Required fields present, types valid, enum values in range,
        array minimums honored"

        Design: Corner/entities/audit_create_invalid_enum_rejected
        """
        ctx = setup_active_supplier(legal_name="Whiskey Apparel", sector="APPAREL")
        facility = create_facility(ctx["supplier"]["id"], name="Site Q")
        auditor = create_auditor()
        payload = create_audit_payload(
            facility["id"], auditor["id"], audit_type="QUARTERLY"
        )
        resp = api.create_audit(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        listed, _ = validate_paginated(
            api.list_audits(OFFICER, params={"facility_id": facility["id"]})
        )
        assert listed == [], "no audit is created with an out-of-enum audit_type"


class TestAuthentication:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying an invalid
        one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.list_suppliers({})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
        )


class TestFilteredListReverseReachability:
    def test_filtered_list_reverse_reachability(self, api):
        """PRD §3.3: "The audit list filters by `facility_id`, `auditor_id`,
        `status`, and `audit_type`."
        PRD §3.5: "Plans can be listed with filters on `finding_id`,
        `supplier_id`, and `status`."

        Design: Corner/endpoints/filtered_list_reverse_reachability
        """
        ctx = setup_active_supplier(legal_name="Papa D", sector="FOOD")
        supplier = ctx["supplier"]
        fac1 = create_facility(supplier["id"], name="Site F1")
        fac2 = create_facility(supplier["id"], name="Site F2")
        auditor = create_auditor()
        au1 = schedule_audit(
            fac1["id"], auditor["id"],
            scheduled_start="2026-09-01T00:00:00Z",
            scheduled_end="2026-09-02T00:00:00Z",
        )
        au2 = schedule_audit(
            fac2["id"], auditor["id"],
            scheduled_start="2026-09-03T00:00:00Z",
            scheduled_end="2026-09-04T00:00:00Z",
        )
        au1 = begin_audit(au1)
        finding = record_finding(
            au1["id"], auditor["id"], classification="MAJOR", category="WAGES",
            description="Wage issue",
        )
        cap = create_cap(finding["id"], supplier["id"])

        by_facility, _ = validate_paginated(
            api.list_audits(OFFICER, params={"facility_id": fac1["id"]})
        )
        assert [a["id"] for a in by_facility] == [au1["id"]], (
            "facility filter returns only that facility's audits"
        )
        assert_audit(by_facility[0])

        by_finding, _ = validate_paginated(
            api.list_corrective_action_plans(
                OFFICER, params={"finding_id": finding["id"]}
            )
        )
        assert [c["id"] for c in by_finding] == [cap["id"]], (
            "finding filter returns exactly that finding's plan"
        )
        assert_cap(by_finding[0])
        assert by_finding[0]["supplier_id"] == supplier["id"]

        by_auditor, meta = validate_paginated(
            api.list_audits(OFFICER, params={"auditor_id": auditor["id"]})
        )
        assert meta["total_count"] == 2
        assert {a["id"] for a in by_auditor} == {au1["id"], au2["id"]}

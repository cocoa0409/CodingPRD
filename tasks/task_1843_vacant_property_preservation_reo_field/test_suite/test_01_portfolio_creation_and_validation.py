"""Portfolio onboarding, resource creation defaults, and request validation."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_user_headers,
    create_allowable,
    create_property,
    create_servicer,
    create_work_order,
    get_success_data,
    set_clock,
    setup_portfolio,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api  # noqa: F401  (ensures registration import)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_code_violation_payload,
    create_investor_allowable_payload,
    create_photo_evidence_payload,
    create_registration_payload,
    create_work_order_payload,
)
from test_helpers.fixtures import (
    create_code_violation,
    create_damage_report,
    create_registration,
)
from test_helpers.test_users import TEST_USERS, make_field_crew_headers, make_servicer_headers

ADMIN = TEST_USERS["vendor_admin_headers"]


class TestPortfolioCreation:
    def test_work_order_create_defaults_and_system_fields(self, api):
        """PRD: "Creation copies the property's `servicer_id` onto the order and
        maps the order type to the allowable `item_code`: `SECURING` maps to
        `LOCK_CHANGE`" and "New orders start in `ISSUED` status"; PRD: "its two
        fiscal parameters are snapshotted as `allowable_cap_cents` and the order's
        own `requires_bid_over_cents`"; PRD: "`version` (integer): a system-managed
        integer that begins at 1 when the resource is created and increments by one
        on every mutation".

        Design: Corner/entities/work_order_create_defaults_and_system_fields
        """
        ctx = setup_portfolio(item_code="LOCK_CHANGE", allowable_overrides={
            "max_per_occurrence_cents": 20000,
            "max_occurrences_per_calendar_year": 4,
            "aggregate_cap_cents_per_property_year": 80000,
            "requires_bid_over_cents": 999999,
        })
        resp = api.create_work_order(
            create_work_order_payload(ctx["property_id"], order_type="SECURING",
                                      due_date="2026-08-10"),
            make_servicer_headers(ctx["servicer_id"]))
        wo = validate_success(resp, expected_status=201)
        assert wo["status"] == "ISSUED", f"new order must start ISSUED, got {wo['status']}"
        assert wo["source"] == "DIRECT", f"servicer-issued order must be DIRECT, got {wo['source']}"
        assert wo["rework_count"] == 0, f"rework_count starts at 0, got {wo['rework_count']}"
        assert wo["version"] == 1, f"version begins at 1, got {wo['version']}"
        assert wo["servicer_id"] == ctx["servicer_id"], "servicer_id copied from the property"
        assert wo["item_code"] == "LOCK_CHANGE", f"SECURING maps to LOCK_CHANGE, got {wo['item_code']}"
        assert wo["allowable_cap_cents"] == 20000, (
            f"allowable_cap_cents snapshots the schedule cap 20000, got {wo['allowable_cap_cents']}")

    def test_property_computed_fields_on_create(self, api):
        """PRD: "A new property starts with `status` `ACTIVE`, `occupancy_status`
        `UNKNOWN`, a `condition_score` of 100, `compliance_posture` `CLEAR`,
        `ytd_investor_approved_cents` at zero, `ytd_calendar_year` set to the
        clock's current year, and `financial_review_required` false."

        Design: Corner/entities/property_computed_fields_on_create
        """
        set_clock("2026-08-01T00:00:00Z")
        sv = create_servicer()
        resp = api.create_property(
            {
                "servicer_id": sv["id"], "address_line1": "2 Test Ave",
                "municipality_code": "COL", "state_code": "OH", "zip": "43215",
                "investor_type": "FNMA", "lot_size_sqft": 6000,
                "heating_system": "NONE", "fixture_count": 3,
            },
            ADMIN)
        prop = validate_success(resp, expected_status=201)
        assert prop["condition_score"] == 100, f"fresh property scores 100, got {prop['condition_score']}"
        assert prop["compliance_posture"] == "CLEAR", f"fresh property is CLEAR, got {prop['compliance_posture']}"
        assert prop["occupancy_status"] == "UNKNOWN", f"fresh occupancy UNKNOWN, got {prop['occupancy_status']}"
        assert prop["status"] == "ACTIVE"
        assert prop["ytd_investor_approved_cents"] == 0
        assert prop["financial_review_required"] is False
        assert prop["ytd_calendar_year"] == 2026

    def test_servicer_get_not_found_returns_404(self, api):
        """PRD: "Every resource identifier referenced by the path or the body
        must exist, or the request fails with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/servicer_get_not_found_returns_404
        """
        resp = api.get_servicer(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_investor_allowable_missing_required_returns_invalid_request(self, api):
        """PRD: "Required fields must be present, types must be valid, enum values
        must lie within their declared domains, a `quantity` must be at least 1,
        amounts must be at least 0, photo evidence must reference exactly one
        subject, and `personal_property_value_estimate_cents` must be present
        whenever `personal_property_present` is true — violations yield
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/investor_allowable_missing_required_returns_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        payload = create_investor_allowable_payload()
        del payload["max_per_occurrence_cents"]
        resp = api.create_investor_allowable(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_photo_evidence_two_subjects_rejected(self, api):
        """PRD: "Each photo belongs to exactly one subject: precisely one of
        `work_order_id`, `inspection_id`, `bid_id`, or `damage_report_id` must be
        supplied; zero or several subjects is an `ERR_INVALID_REQUEST`."

        Design: Corner/entities/photo_evidence_two_subjects_rejected
        """
        ctx = setup_portfolio(item_code="INSPECTION", allowable_overrides={
            "max_per_occurrence_cents": 5000,
            "max_occurrences_per_calendar_year": 30,
            "aggregate_cap_cents_per_property_year": 100000,
        })
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="INSPECTION", due_date="2026-08-09")
        dr = create_damage_report(ctx["property_id"], ctx["crew_id"],
                                  damage_type="STORM", description="gutter loose")
        payload = create_photo_evidence_payload(
            work_order_id=wo["id"], damage_report_id=dr["id"], category="BEFORE")
        resp = api.create_photo_evidence(payload, make_field_crew_headers(ctx["crew_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_work_order_missing_due_date_returns_invalid_request(self, api):
        """PRD: "A `Servicer` issues a work order with a `property_id`, an
        `order_type`, and a `due_date`" and "Required fields must be present, types
        must be valid, enum values must lie within their declared domains, a
        `quantity` must be at least 1, amounts must be at least 0, photo evidence
        must reference exactly one subject, and
        `personal_property_value_estimate_cents` must be present whenever
        `personal_property_present` is true — violations yield `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/validations/create_work_order_missing_due_date_returns_invalid_request
        """
        ctx = setup_portfolio(with_allowable=False)
        payload = create_work_order_payload(ctx["property_id"], order_type="GRASS_CUT")
        del payload["due_date"]
        resp = api.create_work_order(payload, make_servicer_headers(ctx["servicer_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_work_order_without_allowable_rejected(self, api):
        """PRD: "When no row matches, work order creation fails with
        `ERR_ALLOWABLE_NOT_FOUND`."

        Design: Corner/errors/work_order_without_allowable_rejected
        """
        ctx = setup_portfolio(with_allowable=False, with_crew=False)
        resp = api.create_work_order(
            create_work_order_payload(ctx["property_id"], order_type="SNOW_REMOVAL",
                                      due_date="2026-08-10"),
            make_servicer_headers(ctx["servicer_id"]))
        validate_error(resp, ApiErrorId.ERR_ALLOWABLE_NOT_FOUND)

    def test_duplicate_citation_rejected(self, api):
        """PRD: "a `citation_number` (unique within the property's municipality —
        duplicates are rejected with `ERR_CITATION_NOT_UNIQUE`)".

        Design: Corner/errors/duplicate_citation_rejected
        """
        ctx = setup_portfolio(with_allowable=False, with_crew=False)
        create_code_violation(ctx["property_id"], citation_number="CV-500")
        resp = api.create_code_violation(
            create_code_violation_payload(ctx["property_id"], citation_number="CV-500",
                                          violation_class="MAJOR", daily_fine_cents=900),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CITATION_NOT_UNIQUE)

    def test_duplicate_registration_number_rejected(self, api):
        """PRD: "a `registration_number` (unique within its municipality —
        duplicates are rejected with `ERR_REGISTRATION_NUMBER_NOT_UNIQUE`)".

        Design: Corner/errors/duplicate_registration_number_rejected
        """
        ctx = setup_portfolio(with_allowable=False, with_crew=False)
        create_registration(ctx["property_id"], registration_number="REG-DUP")
        resp = api.create_registration(
            create_registration_payload(ctx["property_id"], registration_number="REG-DUP",
                                        valid_from="2027-02-01", valid_to="2027-08-01"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_NUMBER_NOT_UNIQUE)

    def test_request_with_undeclared_role_returns_unauthenticated(self, api):
        """PRD: "A request missing either header, or carrying a role value outside
        these five, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
        and "Every request passes through a fixed validation pipeline, and the order
        matters: a failure at an earlier stage masks every later stage, so the error
        a caller receives is always the earliest applicable one."

        Design: Corner/errors/request_missing_auth_header_returns_unauthenticated
        """
        resp = api.get_servicer(NON_EXISTENT_UUID, build_user_headers("anon-1", "Anonymous"))
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

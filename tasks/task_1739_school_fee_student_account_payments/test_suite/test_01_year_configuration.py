"""School year configuration: creation defaults, open/close gates, overlap rules."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    create_school_year_payload, create_department_payload,
    create_student_payload, create_fee_catalog_item_payload,
    create_offering_payload,
    setup_open_year, setup_year_with_fee, add_student_with_account,
    setup_account_with_assessment, setup_account_with_plan,
    setup_account_with_collections_case, current_account_version,
    make_family_headers, NON_EXISTENT_UUID,
)


class TestSchoolYearCreation:
    def test_school_year_creation_defaults_and_echo(self, bookkeeper_headers):
        """PRD §3.1: "A new year is born `DRAFT`."
        PRD §2.5: "version (integer): a system-managed integer that increments by 1
        with every modification to the resource."

        Design: Corner/entities/school_year_creation_defaults_and_echo
        """
        payload = create_school_year_payload(
            label="2026-27", start_date="2026-08-01", end_date="2027-06-30",
            refund_full_days=2, refund_partial_days=10, partial_refund_pct_bp=5000,
            payment_plan_min_cents=1000, payment_plan_max_installments=6,
            writeoff_max_cents=100000, aging_interval_days=10,
            graduation_hold_threshold_cents=5000)
        resp = api_client.create_school_year(payload, bookkeeper_headers)
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT", f"Expected DRAFT, got {data['status']}"
        assert data["version"] == 1, f"Expected version 1, got {data['version']}"
        assert data["refund_full_days"] == 2
        assert data["payment_plan_max_installments"] == 6
        assert data["label"] == "2026-27"
        assert data["graduation_hold_threshold_cents"] == 5000

    def test_school_year_overlap_shared_endpoint_collides(self, bookkeeper_headers):
        """PRD §2.7: "A shared endpoint date — the new year's start_date equal to
        an existing year's end_date — does collide, and the create is rejected with
        `ERR_YEAR_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/school_year_closed_interval_shared_endpoint_collides
        """
        first = get_success_data(api_client.create_school_year(
            create_school_year_payload(start_date="2026-08-01", end_date="2027-06-30"),
            bookkeeper_headers))
        resp = api_client.create_school_year(
            create_school_year_payload(label="2027-28", start_date="2027-06-30",
                                       end_date="2028-06-15"),
            bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_YEAR_OVERLAP)
        # Existing year unchanged
        year = get_success_data(api_client.get_school_year(first["id"], bookkeeper_headers))
        assert year["version"] == 1

    def test_school_year_overlap_disjoint_ranges_allowed(self, bookkeeper_headers):
        """PRD §2.7: "A new school year's range from `start_date` through `end_date`,
        both endpoints included, must not intersect the range of any existing year
        that is not CLOSED."

        A gap of one day between the existing year's end and the new year's start
        leaves the closed ranges disjoint, so creation succeeds.

        Design: Difficulty/resource_temporal_overlap/school_year_closed_interval_shared_endpoint_collides
        """
        get_success_data(api_client.create_school_year(
            create_school_year_payload(start_date="2026-08-01", end_date="2027-06-30"),
            bookkeeper_headers))
        resp = api_client.create_school_year(
            create_school_year_payload(label="2027-28", start_date="2027-07-01",
                                       end_date="2028-06-15"),
            bookkeeper_headers)
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"


class TestSchoolYearOpen:
    def test_year_open_without_departments_rejected(self, bookkeeper_headers):
        """PRD §3.1: "A `Bookkeeper` may move the year `DRAFT` → `OPEN` only when
        at least one department exists for it — otherwise the attempt is rejected
        with `ERR_YEAR_NOT_CONFIGURABLE` (HTTP 409)"

        Design: Corner/validations/year_open_without_departments_rejected
        """
        year = get_success_data(api_client.create_school_year(
            create_school_year_payload(), bookkeeper_headers))
        resp = api_client.open_school_year(year["id"], bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_YEAR_NOT_CONFIGURABLE)

    def test_year_open_success_sets_open_and_bumps_version(self, bookkeeper_headers):
        """PRD §3.1: "Opening sets `status` to `OPEN` and increments the year's
        version by 1."

        Design: Corner/validations/year_open_without_departments_rejected
        """
        env = setup_open_year()
        year = env["year"]
        assert year["status"] == "OPEN"
        assert year["version"] == 2, (
            f"Create (v1) then open (+1) must yield version 2, got {year['version']}")


class TestSchoolYearClose:
    def test_year_close_blocked_by_open_cases(self, bookkeeper_headers):
        """PRD §3.1: "A year may close `OPEN` → `CLOSED` only when every collections
        case under the year's accounts is terminal — `RESOLVED` or `WRITTEN_OFF` —
        otherwise `ERR_OPEN_COLLECTIONS_CASES` (HTTP 409)"

        Design: Corner/validations/year_close_blocked_by_open_cases
        """
        env = setup_account_with_collections_case(assessed_amount_cents=3000)
        year = get_success_data(api_client.get_school_year(env["year"]["id"], bookkeeper_headers))
        resp = api_client.close_school_year(
            env["year"]["id"], {"expected_year_version": year["version"]}, bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_COLLECTIONS_CASES)
        year_after = get_success_data(api_client.get_school_year(env["year"]["id"], bookkeeper_headers))
        assert year_after["status"] == "OPEN"

    def test_year_close_blocked_by_active_plan(self, bookkeeper_headers):
        """PRD §3.1: "and when no payment plan under the year's accounts is still
        `ACTIVE`, otherwise `ERR_ACTIVE_PAYMENT_PLANS` (HTTP 409)."

        Design: Corner/validations/year_close_blocked_by_active_plan
        """
        env = setup_account_with_plan(assessed_amount_cents=4000)
        year = get_success_data(api_client.get_school_year(env["year"]["id"], bookkeeper_headers))
        resp = api_client.close_school_year(
            env["year"]["id"], {"expected_year_version": year["version"]}, bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_PAYMENT_PLANS)

    def test_year_close_clean_year_succeeds(self, bookkeeper_headers):
        """PRD §3.1: "Closing sets `status` to `CLOSED`, blocks all further
        enrollment, assessment, and payment writes for the year, and increments
        the year's version by 1. `CLOSED` is terminal."

        Design: Corner/validations/year_close_blocked_by_open_cases
        """
        env = setup_open_year()
        year = get_success_data(api_client.get_school_year(env["year"]["id"], bookkeeper_headers))
        resp = api_client.close_school_year(
            env["year"]["id"], {"expected_year_version": year["version"]}, bookkeeper_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "CLOSED"
        assert data["version"] == year["version"] + 1


class TestYearOpenGating:
    def test_enroll_under_draft_year_rejected(self, bookkeeper_headers):
        """PRD §3.1: "Only an `OPEN` year accepts the operational writes:
        enrollments, assessments, purchases, payments, and plans under a `DRAFT`
        or `CLOSED` year are rejected with `ERR_YEAR_NOT_OPEN` (HTTP 409)."

        Design: Corner/validations/enroll_under_draft_year_rejected
        """
        # Build configuration under a DRAFT year (config writes are allowed pre-open)
        year = get_success_data(api_client.create_school_year(
            create_school_year_payload(), bookkeeper_headers))
        dept = get_success_data(api_client.create_department(
            year["id"], create_department_payload(), bookkeeper_headers))
        fee = get_success_data(api_client.create_fee_catalog_item(
            year["id"], create_fee_catalog_item_payload(
                amount_cents=1000, department_id=dept["id"]), bookkeeper_headers))
        offering = get_success_data(api_client.create_offering(
            year["id"], create_offering_payload(
                department_id=dept["id"], fee_item_id=fee["id"]), bookkeeper_headers))
        student = get_success_data(api_client.create_student(
            create_student_payload(), bookkeeper_headers))
        account = get_success_data(api_client.create_student_account(
            year["id"], {"student_id": student["id"]}, bookkeeper_headers))
        resp = api_client.create_enrollment(
            account["id"], {"offering_id": offering["id"]}, bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_YEAR_NOT_OPEN)

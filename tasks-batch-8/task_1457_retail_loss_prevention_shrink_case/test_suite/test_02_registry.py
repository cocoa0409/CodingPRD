"""Store and employee registry: creation defaults, uniqueness, required
fields, and not-found behavior."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_store,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_admin_headers,
    make_analyst_headers,
    make_hr_partner_headers,
    make_store,
    validate_error,
    validate_success,
)
from test_helpers.constants import ADMIN_1, ANALYST_1, HR_PARTNER_1


class TestStoreRegistry:
    def test_store_create_defaults_and_system_fields(self, api):
        """PRD §3.1: "The `store_number` is unique across the enterprise — a
        duplicate is rejected with `ERR_DUPLICATE_STORE_NUMBER` — and a new
        store starts `ACTIVE` with `total_adjudicated_loss_cents` and
        `restitution_collected_cents` both zero."
        PRD §4: "Operations that create a new resource — a store, an employee,
        an exception event, a case (manual or by conversion), an interview, an
        evidence item, a custody event, a civil demand, a restitution payment,
        an ORC group, a case link, a shrink period, or a referral packet —
        return `201 Created`."
        PRD §2.4: "Every primary resource — stores, employees, exception
        events, alerts, cases, interviews, evidence items, civil demands,
        restitution payments, ORC groups, case links, shrink periods, and
        referral packets — carries a standard system-managed quartet"

        Design: Corner/entities/store_create_defaults_and_system_fields
        """
        resp = api.create_store(
            {"store_number": "S001", "name": "Flagship", "region_code": "R1"},
            make_admin_headers(ADMIN_1),
        )
        data = validate_success(resp, expected_status=201)
        assert_store(data)
        assert data["status"] == "ACTIVE"
        assert data["total_adjudicated_loss_cents"] == 0
        assert data["restitution_collected_cents"] == 0
        assert is_valid_uuid(data["id"])
        assert data["version"] >= 1
        assert is_iso8601_timestamp(data["created_at"])

    def test_store_duplicate_number_returns_409(self, api):
        """PRD §3.1: "The `store_number` is unique across the enterprise — a
        duplicate is rejected with `ERR_DUPLICATE_STORE_NUMBER` — and a new
        store starts `ACTIVE` with `total_adjudicated_loss_cents` and
        `restitution_collected_cents` both zero."

        Design: Corner/entities/store_duplicate_number_returns_409
        """
        make_store(store_number="S001", name="Flagship")
        resp = api.create_store(
            {"store_number": "S001", "name": "Duplicate", "region_code": "R2"},
            make_admin_headers(ADMIN_1),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STORE_NUMBER)

    def test_store_get_missing_returns_not_found(self, api):
        """PRD §2.7: "5. Existence of every referenced resource
        (`ERR_NOT_FOUND`)."

        Design: Corner/entities/store_get_missing_returns_not_found
        """
        resp = api.get_store(NON_EXISTENT_UUID, make_analyst_headers(ANALYST_1))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestEmployeeRegistry:
    def test_employee_create_missing_required_returns_invalid_request(self, api):
        """PRD §3.1: "An `HRPartner` registers each associate with the
        employee's home `store_id`, an enterprise-unique `employee_ref`
        (duplicates fail with `ERR_DUPLICATE_EMPLOYEE_REF`), and a
        `full_name`."
        PRD §2.7: "4. Request well-formedness: required fields present, types
        correct, enum values within their declared domains, amounts positive
        where required, `scheduled_end` strictly after `scheduled_start`,
        `period_end` on or after `period_start`, `limit` inside its permitted
        range, `offset` at least 0 (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/employee_create_missing_required_returns_invalid_request
        """
        store = make_store(store_number="S010", name="Store Ten")
        resp = api.create_employee(
            {"store_id": store["id"], "employee_ref": "E-010"},
            make_hr_partner_headers(HR_PARTNER_1),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_employee_duplicate_ref_rejected(self, api):
        """PRD §3.1: "An `HRPartner` registers each associate with the
        employee's home `store_id`, an enterprise-unique `employee_ref`
        (duplicates fail with `ERR_DUPLICATE_EMPLOYEE_REF`), and a
        `full_name`."

        Uniqueness is enterprise-wide: the same ref at a different store still
        collides.

        Design: Corner/entities/employee_duplicate_ref_rejected
        """
        s1 = make_store(store_number="S011", name="Store 11")
        s2 = make_store(store_number="S012", name="Store 12")
        resp1 = api.create_employee(
            {"store_id": s1["id"], "employee_ref": "E-100", "full_name": "Original"},
            make_hr_partner_headers(HR_PARTNER_1),
        )
        validate_success(resp1, expected_status=201)
        resp2 = api.create_employee(
            {"store_id": s2["id"], "employee_ref": "E-100", "full_name": "Duplicate"},
            make_hr_partner_headers(HR_PARTNER_1),
        )
        validate_error(resp2, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_REF)

"""Agency onboarding, household registration, and role-based access walls."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_client_household,
    assert_partner_agency,
    create_active_grant,
    create_agency,
    create_agency_payload,
    create_draft_po,
    create_event,
    create_household_payload,
    make_agency_coordinator_headers,
    make_warehouse_manager_headers,
    purchase_line,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bank_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_manager_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
PRIVACY = TEST_USERS["privacy_officer_headers"]
VOLUNTEER_COORD = TEST_USERS["volunteer_coordinator_headers"]
VOLUNTEER = TEST_USERS["volunteer_headers"]


class TestAgencyOnboarding:
    def test_agency_creation_applies_defaults(self, api):
        """PRD §3.1: "A newly enrolled agency starts `ACTIVE`."
        PRD §2.9: "Each agency's `active_allocated_units` mirrors this from the recipient side: it is the sum of allocated-but-unfulfilled units over that agency's allocation lines whose status is `ALLOCATED` or `PARTIALLY_FULFILLED`, and it is recomputed whenever those lines move."

        Design: Corner/entities/agency_creation_applies_defaults
        """
        resp = api.create_agency(
            create_agency_payload(name="Agency N", agency_code="AG-N",
                                  contact_email="n@x.org",
                                  children_served_monthly=120,
                                  storage_capacity_units=5000),
            ADMIN,
        )
        agency = validate_success(resp, 201)
        assert_partner_agency(agency)
        assert agency["status"] == "ACTIVE", "A newly enrolled agency starts ACTIVE"
        assert agency["active_allocated_units"] == 0, (
            "No allocation lines exist for a new agency, so the sum is zero"
        )
        assert agency["children_served_monthly"] == 120
        assert agency["storage_capacity_units"] == 5000

    def test_duplicate_agency_code_rejected(self, api):
        """PRD §3.1: "A `BankAdmin` enrolls an agency by providing a display `name`, a unique short `agency_code` (a code already in use is rejected with `ERR_DUPLICATE_CODE`), a `contact_email`, and the two inputs the allocation formula consumes: `children_served_monthly`, the number of children the agency serves per month (zero or more), and `storage_capacity_units`, the agency's total on-site storage expressed in diaper units (zero or more)."

        Design: Corner/entities/duplicate_agency_code_rejected
        """
        create_agency(children_served_monthly=10, storage_capacity_units=100,
                      name="Agency D1", agency_code="AG-DUP",
                      contact_email="d1@x.org")

        resp = api.create_agency(
            create_agency_payload(name="Agency D2", agency_code="AG-DUP",
                                  contact_email="d2@x.org",
                                  children_served_monthly=20,
                                  storage_capacity_units=200),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)

    @pytest.mark.parametrize(
        "missing_field",
        ["name", "agency_code", "contact_email",
         "children_served_monthly", "storage_capacity_units"],
    )
    def test_create_agency_missing_required_field(self, api, missing_field):
        """PRD §2.6: "Tenth and last, request-body validation: malformed fields, bad enumerations, unknown size codes, an `ends_at` that does not fall after `starts_at`, empty line arrays, quantities below one, unresolvable foreign references in the body, and a second attempt to initialize the inventory are all rejected with `ERR_VALIDATION`."

        Design: Corner/validations/create_agency_missing_required_field
        """
        payload = create_agency_payload()
        del payload[missing_field]
        resp = api.create_agency(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestGrantRead:
    def test_grant_not_found_returns_404(self, api):
        """PRD §2.6: "Third, path existence: every identifier in the URL path must resolve to an existing resource, checked strictly left to right, with the first unresolvable identifier producing `ERR_NOT_FOUND` before any later segment is examined."

        Design: Corner/entities/grant_not_found_returns_404
        """
        resp = api.get_grant(NON_EXISTENT_UUID, FINANCE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_volunteer_reading_grant_forbidden_before_not_found(self, api):
        """PRD §2.6: "Second, authorization: the role must be listed for the endpoint, with the coordinator scoping and client-data walling rules of §2.1 applied. Third, path existence: every identifier in the URL path must resolve to an existing resource, checked strictly left to right, with the first unresolvable identifier producing `ERR_NOT_FOUND` before any later segment is examined."
        PRD §2.1: "A request whose role is not listed for the endpoint it targets is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/validations/volunteer_reading_grant_forbidden_before_not_found
        """
        # Volunteer is not in the grant-read role list, so authorization fires
        # before path existence even though the id does not resolve.
        resp = api.get_grant(NON_EXISTENT_UUID, VOLUNTEER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestHouseholdRegistration:
    def test_household_creation_pseudonymous_shape(self, api):
        """PRD §3.6: "A new household's `eligibility_status` is `PENDING_REVIEW` and its `eligibility_reason` is null."
        PRD §3.6: "The household's `monthly_allotment_units` is 50 units per child per month — the allotment is fifty times the number of entries in `children_sizes`."
        PRD §3.6: "two optional flags: `consent_on_file` (a signed service consent exists, defaulting to false) and `privacy_restricted` (defaulting to false)."
        PRD §2.10: "The system stores no personally identifying information about the families it serves — no name, address, or contact fields exist on any resource."

        Design: Corner/entities/household_creation_pseudonymous_shape
        """
        resp = api.create_household(
            create_household_payload(household_code="HH-NEW",
                                     children_sizes=["SIZE_1", "SIZE_3", "SIZE_5"]),
            PRIVACY,
        )
        household = validate_success(resp, 201)
        assert_client_household(household)
        assert household["eligibility_status"] == "PENDING_REVIEW"
        assert household["eligibility_reason"] is None
        assert household["consent_on_file"] is False
        assert household["privacy_restricted"] is False
        assert household["monthly_allotment_units"] == 150, (
            "50 units per child per month, three children"
        )
        for pii_field in ("name", "address", "phone", "email"):
            assert pii_field not in household, (
                f"Dignity policy: household must not expose a {pii_field!r} field"
            )


class TestRoleWalls:
    def test_bankadmin_cannot_create_household(self, api):
        """PRD §2.1: "Client data is walled off by policy, not just by convention: household registration, household reads and updates, eligibility decisions, and household issuance history are `PrivacyOfficer`-only operations, and the denial explicitly includes `BankAdmin` — an administrator who attempts to touch a household record receives `ERR_FORBIDDEN_ROLE` like anyone else."

        Design: Corner/rbac/bankadmin_cannot_create_household
        """
        resp = api.create_household(
            create_household_payload(household_code="HH-R1",
                                     children_sizes=["SIZE_1"],
                                     consent_on_file=True),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_warehouse_manager_cannot_submit_po(self, api):
        """PRD §2.11: "Submission — the act that commits grant money — belongs to a `FinanceManager`, and the submitting identity must differ from `created_by_user_id`; an attempt by the same operator to submit their own order is rejected with `ERR_SOD_VIOLATION`."
        PRD §2.1: "A request whose role is not listed for the endpoint it targets is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/warehouse_manager_cannot_submit_po
        """
        grant = create_active_grant(total_amount_cents=100000)
        po = create_draft_po(grant["id"],
                             lines=[purchase_line("SIZE_1", 1, 1000)])

        # A WarehouseManager who is NOT the creator still cannot submit: the
        # endpoint's role list excludes the role outright.
        resp = api.submit_purchase_order(
            po["id"], make_warehouse_manager_headers("wm-user-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        po_after = api.get_purchase_order(po["id"], WAREHOUSE)
        assert validate_success(po_after, 200)["status"] == "DRAFT", (
            "A role-denied submit must not move the order"
        )

    def test_volunteer_cannot_create_shift(self, api):
        """PRD §3.7: "A `VolunteerCoordinator` creates a shift with a `title`, a `starts_at` and `ends_at` (the start must precede the end), and a `capacity` of at least one volunteer."
        PRD §2.1: "A request whose role is not listed for the endpoint it targets is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/volunteer_cannot_create_shift
        """
        resp = api.create_volunteer_shift(
            {"title": "Nope", "starts_at": "2026-08-10T09:00:00Z",
             "ends_at": "2026-08-10T11:00:00Z", "capacity": 3},
            VOLUNTEER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_agency_coordinator_cannot_open_other_agency_event(self, api):
        """PRD §2.1: "When `X-User-Role` is `AgencyCoordinator`, `X-User-ID` is the `id` of the acting PartnerAgency; ownership checks on any resource that references a PartnerAgency — a distribution event through its `host_agency_id`, an allocation line through its `agency_id`, an issuance through the event that owns it — compare that foreign-key field to `X-User-ID`, and a coordinator touching another agency's resource is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/agency_coordinator_cannot_open_other_agency_event
        """
        agency_a = create_agency(name="Agency A", agency_code="AG-OA",
                                 contact_email="a@x.org",
                                 children_served_monthly=100,
                                 storage_capacity_units=10000)
        agency_b = create_agency(name="Agency B", agency_code="AG-OB",
                                 contact_email="b@x.org",
                                 children_served_monthly=100,
                                 storage_capacity_units=10000)
        event = create_event(agency_a["id"], site_name="O-Site")

        resp = api.open_distribution_event(
            event["id"], make_agency_coordinator_headers(agency_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        event_after = api.get_distribution_event(event["id"], ADMIN)
        assert validate_success(event_after, 200)["status"] == "SCHEDULED", (
            "A coordinator acting on another agency's event must not open it"
        )

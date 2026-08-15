"""Authentication, role exclusivity, ownership, and segregation of duties
(PRD §2.1, §2.9, §3.5, §3.8)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    TEST_USERS, NON_EXISTENT_UUID,
    create_instrument_payload, create_training_record_payload,
    create_grant_payload, create_rate_set_payload,
    create_subsidy_application_payload,
    make_researcher_headers, make_external_client_headers, make_finance_headers,
    setup_canonical_stack, create_booking_request, open_batch,
    enroll_and_certify, create_instrument, create_user, open_fiscal_year,
    create_draft_rate_set, run_session_to_completed, create_approved_booking,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
STAFF2 = TEST_USERS["staff2_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestAuthentication:
    def test_unauthenticated_calls_401(self, api):
        """PRD §2.1: "A request missing either header, presenting a role outside
        these five, or — for the entity-backed roles — presenting an `X-User-ID`
        that does not reference an existing `User` record, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_calls_401
        """
        i1 = validate_success(
            api.create_instrument(create_instrument_payload(), ADMIN), 201
        )
        # Branch 1: no auth headers at all.
        res = api.get_instrument(i1["id"], headers=None)
        validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
        # Branch 2: entity-backed role with an X-User-ID that is no User.id.
        res2 = api.get_instrument(
            i1["id"], headers=make_researcher_headers(NON_EXISTENT_UUID)
        )
        validate_error(res2, "ERR_UNAUTHENTICATED", expected_status=401)


class TestRoleExclusivity:
    def test_rbac_researcher_denied_grant_create(self, api):
        """PRD §2.1: "A request whose role is not authorized for the endpoint,
        or in which an entity-backed role attempts to reach a resource
        belonging to another user, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)." PRD §4: POST /grants is authorized for FinanceOfficer.

        Design: Corner/rbac/rbac_researcher_denied_grant_create
        """
        u1 = validate_success(
            api.create_user(
                {"full_name": "Rita Rao", "email": "r1@uni.edu",
                 "affiliation": "INTERNAL", "is_pi": True}, ADMIN),
            201,
        )
        res = api.create_grant(
            create_grant_payload(u1["id"], grant_code="NIH-9", title="Nope",
                                 budget_total_cents=1000),
            make_researcher_headers(u1["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)
        _, meta = validate_paginated(api.list_grants(FINANCE))
        assert meta["total_count"] == 0, "no grant may be persisted after a 403"

    def test_rbac_finance_denied_certify(self, api):
        """PRD §2.1: "A request whose role is not authorized for the endpoint,
        or in which an entity-backed role attempts to reach a resource
        belonging to another user, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)." PRD §4: POST /training-records/{id}/certify is authorized
        for CoreStaff.

        Design: Corner/rbac/rbac_finance_denied_certify
        """
        u1 = create_user()
        i1 = create_instrument()
        t1 = validate_success(
            api.create_training_record(
                create_training_record_payload(u1["id"], i1["id"]), STAFF
            ),
            201,
        )
        res = api.certify_training_record(t1["id"], FINANCE)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)
        record = validate_success(api.get_training_record(t1["id"], STAFF), 200)
        assert record["status"] == "ENROLLED", "a denied certify must not mutate"

    def test_rbac_staff_denied_batch_finalize(self, api):
        """PRD §2.1: "A request whose role is not authorized for the endpoint,
        or in which an entity-backed role attempts to reach a resource
        belonging to another user, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)." PRD §4: POST /recharge-batches/{id}/finalize is authorized
        for FinanceOfficer.

        Design: Corner/rbac/rbac_staff_denied_batch_finalize
        """
        open_fiscal_year(2026)
        batch = open_batch(2026, 9)
        res = api.finalize_recharge_batch(batch["id"], STAFF)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)
        batch_after = validate_success(api.get_recharge_batch(batch["id"], FINANCE), 200)
        assert batch_after["status"] == "OPEN", "a denied finalize must not mutate"

    def test_rbac_admin_denied_rate_approve(self, api):
        """PRD §2.1: "A request whose role is not authorized for the endpoint,
        or in which an entity-backed role attempts to reach a resource
        belonging to another user, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)." PRD §4: POST /rate-sets/{id}/approve is authorized for
        FinanceOfficer.

        Design: Corner/rbac/rbac_admin_denied_rate_approve
        """
        i1 = create_instrument()
        open_fiscal_year(2027)
        rs27 = create_draft_rate_set(
            i1["id"], fiscal_year=2027, effective_from="2027-01-01T00:00:00Z",
            line_overrides={"internal_rate_cents_per_hour": 12500,
                            "external_rate_cents_per_hour": 19000},
        )
        validate_success(api.submit_rate_set(rs27["id"], ADMIN), 200)
        res = api.approve_rate_set(rs27["id"], ADMIN)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    def test_rbac_external_denied_subsidy_apply(self, api):
        """PRD §2.1: "A request whose role is not authorized for the endpoint,
        or in which an entity-backed role attempts to reach a resource
        belonging to another user, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)." PRD §4: POST /subsidy-applications is authorized for
        Researcher.

        Design: Corner/rbac/rbac_external_denied_subsidy_apply
        """
        u3 = create_user(affiliation="EXTERNAL", full_name="Eve Ext",
                         email="eve@acme.com")
        res = api.create_subsidy_application(
            create_subsidy_application_payload(
                u3["id"], requested_amount_cents=5000,
                justification="external ask",
            ),
            make_external_client_headers(u3["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)


class TestOwnershipAndSharedOperations:
    def test_rbac_staff_shared_cancel_and_ownership_read(self, api):
        """PRD §2.1: "Entity-backed callers may only read and mutate their own
        resources and may only create resources whose `user_id` equals their
        own `X-User-ID`; list endpoints force-filter to the caller's own
        records." PRD §3.7: "On an actor-driven cancel, `cancellation_reason`
        is set to `USER` for entity-backed callers and `STAFF` for
        `CoreStaff`."

        Design: Corner/rbac/rbac_staff_shared_cancel_and_ownership_read
        """
        stack = setup_canonical_stack()
        u2 = create_user(affiliation="INTERNAL", full_name="Sam Soo",
                         email="r2@uni.edu")
        b1 = create_booking_request(stack)

        res_other = api.get_booking(b1["id"], make_researcher_headers(u2["id"]))
        validate_error(res_other, "ERR_FORBIDDEN", expected_status=403)

        own = validate_success(
            api.get_booking(b1["id"], make_researcher_headers(stack["u1"]["id"])), 200
        )
        assert own["id"] == b1["id"]

        cancelled = validate_success(
            api.cancel_booking(b1["id"], STAFF,
                               payload={"reason": "user called in sick"}),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "STAFF"


class TestSegregationOfDuties:
    def test_sod_validator_must_differ_from_logger(self, api):
        """PRD §3.8: "Validation is the fiscal point of no return and is
        guarded by segregation of duties: the validator's `X-User-ID` must
        differ from the log's `logged_by` (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/rbac/sod_validator_must_differ_from_logger
        """
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)
        open_batch(2026, 9)
        completed = run_session_to_completed(
            b1, "2026-09-01T09:00:00Z", "2026-09-01T10:30:00Z"
        )
        log = validate_success(
            api.create_usage_log(
                {"booking_id": completed["id"],
                 "actual_start_at": "2026-09-01T09:00:00Z",
                 "actual_end_at": "2026-09-01T10:30:00Z"},
                STAFF,
            ),
            201,
        )
        validate_success(api.submit_usage_log(log["id"], STAFF), 200)

        res_self = api.validate_usage_log(log["id"], STAFF)
        validate_error(res_self, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

        validated = validate_success(api.validate_usage_log(log["id"], STAFF2), 200)
        assert validated["status"] == "VALIDATED"
        assert validated["validated_by"] == "staff-2"

    def test_sod_rate_approver_must_differ_from_developer(self, api):
        """PRD §3.5: "segregation of duties forbids the approver's `X-User-ID`
        from equaling the set's `developed_by` (`ERR_SEGREGATION_OF_DUTIES`).
        Approval stamps `approved_by` with the approver's operator id."

        Design: Corner/rbac/sod_rate_approver_must_differ_from_developer
        """
        i1 = create_instrument()
        open_fiscal_year(2027)
        rs27 = create_draft_rate_set(
            i1["id"], fiscal_year=2027, effective_from="2027-01-01T00:00:00Z",
            line_overrides={"internal_rate_cents_per_hour": 12500,
                            "external_rate_cents_per_hour": 19000},
        )
        validate_success(api.submit_rate_set(rs27["id"], ADMIN), 200)

        res_same_person = api.approve_rate_set(
            rs27["id"], make_finance_headers("admin-1")
        )
        validate_error(
            res_same_person, "ERR_SEGREGATION_OF_DUTIES", expected_status=403
        )

        approved = validate_success(api.approve_rate_set(rs27["id"], FINANCE), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by"] == "fin-1"

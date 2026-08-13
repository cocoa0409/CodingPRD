"""Role-based access control, segregation of duties, and authentication."""
from test_helpers import (
    ACCOUNTANT,
    AUDITOR,
    SUPERVISOR,
    ApiErrorId,
    assert_engagement,
    assert_timecard,
    create_open_batch,
    create_timecard_payload,
    get_pay_batch,
    get_success_data,
    make_payroll_supervisor_headers,
    setup_closed_batch_with_tca,
    setup_standard,
    setup_with_approved_timecard,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:
    def test_missing_headers_returns_401(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
        `X-User-Role`. Requests missing either header, carrying an unknown role,
        or carrying an empty user identifier are rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_missing_headers_returns_401
        """
        resp = api.list_union_agreements({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleExclusiveDenial:
    def test_union_auditor_cannot_create_timecard(self, api):
        """PRD §2.1: "Requests carrying a recognized role that is not permitted
        for the target endpoint are rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4 endpoint table: POST /payroll/timecards — ProductionAccountant.

        Design: Corner/rbac/union_auditor_cannot_create_timecard
        """
        ctx = setup_standard()
        payload = create_timecard_payload(ctx["eng"]["id"])
        resp = api.create_timecard(payload, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_production_accountant_cannot_close_batch(self, api):
        """PRD §2.1: "Requests carrying a recognized role that is not permitted
        for the target endpoint are rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4 endpoint table: POST /payroll/pay-batches/{id}/close — PayrollClerk.

        Design: Corner/rbac/production_accountant_cannot_close_batch
        """
        ctx = setup_with_approved_timecard()
        batch = create_open_batch()
        resp = api.close_pay_batch(batch["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_pay_batch(batch["id"])["status"] == "OPEN"


class TestSegregationOfDuties:
    def test_batch_approve_by_creator_rejected(self, api):
        """PRD §3.11: "Segregation of duties is enforced here: the approver's
        `X-User-ID` must differ from the batch's `created_by_user_id`, and a match
        is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.11: "The batch records `created_by_user_id` from the requesting
        `X-User-ID` — this becomes the segregation-of-duties anchor."

        Design: Corner/rbac/batch_approve_by_creator_rejected_sod
        """
        ctx = setup_closed_batch_with_tca()  # created by clerk-1
        assert ctx["bat"]["created_by_user_id"] == "clerk-1"

        # A supervisor carrying the creator's X-User-ID is still blocked.
        resp = api.approve_pay_batch(ctx["bat"]["id"],
                                     make_payroll_supervisor_headers("clerk-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_pay_batch(ctx["bat"]["id"])["status"] == "CLOSED"

        # A different supervisor approves.
        approved = get_success_data(api.approve_pay_batch(ctx["bat"]["id"],
                                                          SUPERVISOR))
        assert approved["status"] == "APPROVED"


class TestSharedReadAccess:
    def test_union_auditor_read_access_shared(self, api):
        """PRD §2.1: "Read access is shared: all GET endpoints are available to
        every role."
        PRD §3.4: "Approval by a `PayrollSupervisor` moves the engagement from
        `PENDING_APPROVAL` to `ACTIVE` and increments its `version`."

        Design: Corner/rbac/union_auditor_read_access_shared
        """
        ctx = setup_with_approved_timecard()
        eng = validate_success(api.get_engagement(ctx["eng"]["id"], AUDITOR))
        assert_engagement(eng)
        assert eng["status"] == "ACTIVE"
        cards, meta = validate_paginated(api.list_timecards(AUDITOR))
        assert meta["total_count"] == 1
        assert_timecard(cards[0])

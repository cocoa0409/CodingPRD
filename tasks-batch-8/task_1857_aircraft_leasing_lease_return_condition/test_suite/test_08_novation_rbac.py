"""Sublease/novation approval chain (two stages + SoD), lessee-standing
gates, and role/ownership authorization."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_lease,
    create_aircraft_payload,
    create_credit_approved_novation,
    create_lessee,
    make_credit_officer_headers,
    make_legal_approver_headers,
    make_lessee_rep_headers,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["lessor_admin_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


class TestNovationChain:
    def test_legal_approval_requires_proposed_lessee_active(self, api):
        """PRD §3.7: "The legal stage is performed by a `LegalApprover` on a
        `CREDIT_APPROVED` request: the legal reviewer's `X-User-ID` must
        differ from `credit_reviewed_by` — the same person approving both
        stages is `ERR_SOD_VIOLATION` — and for an approval the proposed
        lessee must still have `status` `ACTIVE`, else
        `ERR_LESSEE_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/novation_legal_approval_requires_proposed_lessee_active
        """
        lease, _aircraft, lessee_a = create_active_lease()
        lessee_b = create_lessee(legal_name="Quebec2 Air")
        req = create_credit_approved_novation(
            lease["id"], lessee_a["id"], lessee_b["id"], request_type="NOVATION")
        assert req["status"] == "CREDIT_APPROVED"

        # The proposed lessee is suspended between credit and legal review.
        validate_success(
            api.set_lessee_status(lessee_b["id"], {"to": "SUSPENDED"},
                                  make_credit_officer_headers("cred_2")))
        resp = api.review_novation_request(
            req["id"], {"decision": "APPROVE"}, make_legal_approver_headers("legal_1"))
        validate_error(resp, ApiErrorId.ERR_LESSEE_NOT_ACTIVE, expected_status=409)

        # No partial transition: the request remains CREDIT_APPROVED.
        data, _meta = validate_paginated(api.list_novation_requests(lease["id"], ADMIN))
        assert data[0]["status"] == "CREDIT_APPROVED"

    def test_legal_approval_novation_reassigns_obligor(self, api):
        """PRD §3.7: "Legal approval moves the request to `APPROVED`, stamps
        `legal_reviewed_by`, and takes effect on the lease: for `NOVATION`
        the lease's `lessee_id` is reassigned to the proposed lessee, while
        for `SUBLEASE` the lease's `approved_sublessee_id` is set to the
        proposed lessee, and in both arms the lease's `version` is
        incremented."

        Design: Difficulty/cross_entity_state_dependency/novation_legal_approval_requires_proposed_lessee_active
        """
        lease, _aircraft, lessee_a = create_active_lease()
        lessee_b = create_lessee(legal_name="Quebec3 Air")
        req = create_credit_approved_novation(
            lease["id"], lessee_a["id"], lessee_b["id"], request_type="NOVATION")
        lease_version_before = validate_success(api.get_lease(lease["id"], ADMIN))["version"]

        approved = validate_success(
            api.review_novation_request(
                req["id"], {"decision": "APPROVE"}, make_legal_approver_headers("legal_1")))
        assert approved["status"] == "APPROVED"
        assert approved["legal_reviewed_by"] == "legal_1"

        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["lessee_id"] == lessee_b["id"], (
            "NOVATION reassigns the obligor")
        assert lease_now["version"] > lease_version_before

    def test_sod_same_user_credit_and_legal_rejected(self, api):
        """PRD §3.7: "The legal stage is performed by a `LegalApprover` on a
        `CREDIT_APPROVED` request: the legal reviewer's `X-User-ID` must
        differ from `credit_reviewed_by` — the same person approving both
        stages is `ERR_SOD_VIOLATION`"

        Design: Corner/validations/novation_sod_same_user_credit_and_legal
        """
        lease, _aircraft, lessee_a = create_active_lease()
        lessee_b = create_lessee(legal_name="VAL5B Air")
        req = create_credit_approved_novation(
            lease["id"], lessee_a["id"], lessee_b["id"], request_type="NOVATION",
            credit_officer="cred_1")

        # The legal review carries the same X-User-ID as the credit review.
        resp = api.review_novation_request(
            req["id"], {"decision": "APPROVE"}, make_legal_approver_headers("cred_1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=409)

        data, _meta = validate_paginated(api.list_novation_requests(lease["id"], ADMIN))
        assert data[0]["status"] == "CREDIT_APPROVED", (
            "an SoD rejection must not partially transition the request")

        approved = validate_success(
            api.review_novation_request(
                req["id"], {"decision": "APPROVE"}, make_legal_approver_headers("legal_1")))
        assert approved["status"] == "APPROVED"
        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["lessee_id"] == lessee_b["id"]

    def test_credit_officer_cannot_perform_legal_stage(self, api):
        """PRD §3.7: "The legal stage is performed by a `LegalApprover` on a
        `CREDIT_APPROVED` request"
        PRD §2.8 (5): "State preconditions — the target resource is in a
        from-state the transition allows, including terminal-state lockdown
        and the one-open-child rules (else `ERR_INVALID_STATE`, HTTP 409; ...)"
        PRD §3.7: "for `SUBLEASE` the lease's `approved_sublessee_id` is set
        to the proposed lessee"

        Design: Corner/rbac/novation_credit_officer_cannot_perform_legal_stage
        """
        lease, _aircraft, lessee_a = create_active_lease()
        lessee_b = create_lessee(legal_name="RBAC3B Air")
        req = create_credit_approved_novation(
            lease["id"], lessee_a["id"], lessee_b["id"], request_type="SUBLEASE")

        # From CREDIT_APPROVED the only review transition has actor
        # LegalApprover; a CreditOfficer attempt matches no transition. PRD
        # names both candidate rejections without pinning one: §2.8(5) yields
        # ERR_INVALID_STATE (no from-state the CreditOfficer's credit stage
        # allows), while §2.1 yields ERR_FORBIDDEN (the inferred legal stage
        # is not open to the credit role).
        resp = api.review_novation_request(
            req["id"], {"decision": "APPROVE"}, make_credit_officer_headers("cred_2"))
        validate_error_is_one_of(
            resp, ["ERR_INVALID_STATE", "ERR_FORBIDDEN"])

        approved = validate_success(
            api.review_novation_request(
                req["id"], {"decision": "APPROVE"}, make_legal_approver_headers("legal_1")))
        assert approved["status"] == "APPROVED"
        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["approved_sublessee_id"] == lessee_b["id"], (
            "SUBLEASE sets approved_sublessee_id")
        assert lease_now["lessee_id"] == lessee_a["id"], (
            "SUBLEASE leaves the obligor unchanged")

    def test_credit_stage_reject_is_terminal(self, api):
        """PRD §3.7: "a `decision` to approve moves it to `CREDIT_APPROVED`
        and a `decision` to reject moves it to `REJECTED`, and either way the
        officer's `X-User-ID` is stamped as `credit_reviewed_by`."
        PRD §3.7: "Both `APPROVED` and `REJECTED` are terminal."

        Design: Corner/validations/novation_sod_same_user_credit_and_legal
        """
        lease, _aircraft, lessee_a = create_active_lease()
        lessee_b = create_lessee(legal_name="VAL5C Air")
        req = validate_success(
            api.create_novation_request(
                lease["id"],
                {"request_type": "NOVATION", "proposed_lessee_id": lessee_b["id"]},
                make_lessee_rep_headers(lessee_a["id"])),
            expected_status=201)
        rejected = validate_success(
            api.review_novation_request(
                req["id"], {"decision": "REJECT"}, make_credit_officer_headers("cred_1")))
        assert rejected["status"] == "REJECTED"
        assert rejected["credit_reviewed_by"] == "cred_1"


class TestNovationValidation:
    def test_invalid_request_type_rejected(self, api):
        """PRD §3.7: "A lessee that wants out of — or to share — its
        obligation files a request on its own lease, selecting a
        `request_type` of `NOVATION` to reassign the obligor entirely or
        `SUBLEASE` to obtain authorization for a sublessee, and naming the
        `proposed_lessee_id`."
        PRD §2.8 (4): "Request well-formedness — required fields present,
        enum values within their declared sets, numeric ranges respected,
        `end_date` strictly after `start_date`, `window_end` on or after
        `window_start`, and a proposed novation counterparty that differs
        from the current lessee (else `ERR_INVALID_REQUEST`, HTTP 400)."

        Design: Corner/entities/create_novation_invalid_enum_returns_invalid_request
        """
        lease, _aircraft, lessee_a = create_active_lease()
        lessee_b = create_lessee(legal_name="Enum2 Air")
        resp = api.create_novation_request(
            lease["id"],
            {"request_type": "LEASEBACK", "proposed_lessee_id": lessee_b["id"]},
            make_lessee_rep_headers(lessee_a["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestRbac:
    def test_lessee_rep_cannot_create_aircraft(self, api):
        """PRD §2.1: "A request whose role is valid but not on the endpoint's
        authorized list — or that fails an entity-backed ownership check
        described below — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.1: "A `LessorAdmin` registers each airframe by supplying its
        `msn`"

        Design: Corner/rbac/rbac_lessee_rep_cannot_create_aircraft
        """
        lessee = create_lessee(legal_name="RBAC1 Air")
        resp = api.create_aircraft(
            create_aircraft_payload(msn="MSN-RBAC-1"),
            make_lessee_rep_headers(lessee["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_finance_manager_cannot_decide_claim(self, api):
        """PRD §2.1: "A request whose role is valid but not on the endpoint's
        authorized list — or that fails an entity-backed ownership check
        described below — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.4: "The `decision` rests with a `LessorAdmin`."
        PRD §2.8: "1. **Authentication** — both headers present, role
        declared (else `ERR_UNAUTHENTICATED`). 2. **Authorization and
        ownership** — the acting role is on the endpoint's list, and for
        entity-backed ownership endpoints the `X-User-ID` equals the owning
        entity's `id` (else `ERR_FORBIDDEN`). 3. **Path existence** — every
        identifier in the URL resolves, validated strictly left to right; the
        first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP
        404) and no later segment is examined."

        Design: Corner/rbac/rbac_finance_manager_cannot_decide_claim
        """
        resp = api.decide_reserve_claim(
            "00000000-0000-4000-8000-000000000000",
            {"decision": "APPROVE", "approved_amount_cents": 1000},
            FINANCE)
        # The role check (priority 2) fires before the 404 existence check.
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_lessee_rep_cannot_report_on_other_lessees_lease(self, api):
        """PRD §2.1: "When `X-User-Role` is `LesseeRep`, `X-User-ID` is the
        `id` of the acting `Lessee`; ownership checks on any resource reached
        through a lease compare the lease's `lessee_id` field to `X-User-ID`,
        and acting on another lessee's lease is `ERR_FORBIDDEN`."

        Design: Corner/rbac/rbac_lessee_rep_cannot_report_on_other_lessees_lease
        """
        lease, _aircraft, _lessee_a = create_active_lease()
        lessee_b = create_lessee(legal_name="RBAC2B Air")
        resp = api.create_utilization_report(
            lease["id"],
            {"period_month": "2026-08", "flight_hours": 10.0, "flight_cycles": 2},
            make_lessee_rep_headers(lessee_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request whose role header is missing, or names a
        value outside this set, or whose user header is missing, is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_unauthenticated
        """
        resp = api.create_aircraft(
            {"msn": "MSN-VAL-1", "model": "A320-200", "manufacture_date": "2012-01-01"},
            headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

"""Validation-ladder precedence (PRD §2.8) and role-based access (PRD §2.1, §4)."""
from datetime import datetime, timezone

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_draft_contract,
    create_payer_payload,
    create_record_outcome_payload,
    create_remittance_payload,
    create_test_payer,
    create_write_off_payload,
    get_case,
    get_contract,
    setup_case,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AUD, CA, CM, FD, RIA, RM, SA


class TestValidationLadderOrder:
    def test_missing_auth_header_beats_not_found(self, api):
        """PRD §2.8: "Every request passes through a fixed ladder of checks,
        and the rungs are evaluated in the order below: when several checks
        could fail on the same request, the failure on the earliest rung is
        the one reported, and later rungs are never reached once a failure has
        fired." Rung 1: "**Authentication context** — `X-User-ID` and
        `X-User-Role` must be present and the role must be one of the seven
        declared roles, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/val_missing_auth_header_beats_not_found
        """
        resp = api.get_payer_contract(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_role_denied_beats_not_found(self, api):
        """PRD §2.8 rung 2: "**Authorization** — the caller's role must appear
        in the endpoint's authorized-role list, else `ERR_FORBIDDEN_FOR_ROLE`.
        Applies to every endpoint." Rung 2 precedes rung 4 ("**Existence** —
        every resource id referenced in the path or body ... must exist, else
        `ERR_NOT_FOUND`").

        Design: Corner/validations/val_role_denied_beats_not_found
        """
        # Auditor is not authorized for deactivate; the missing payer id must
        # not surface because authorization is the earlier rung.
        resp = api.deactivate_payer(NON_EXISTENT_UUID, AUD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_shape_error_beats_state_error(self, api):
        """PRD §2.8 rung 3: "**Request shape** — on every write endpoint:
        required fields present, ... else `ERR_INVALID_REQUEST`" — evaluated
        before rung 6 state validity ("a case must be under review for a
        write-off or a first appeal").

        Design: Corner/validations/val_shape_error_beats_state_error
        """
        ctx = setup_case(
            paid_amount_cents=100000, claim_overrides={"claim_number": "CL-SH1"}
        )
        case = ctx["case"]
        assert case["status"] == "QUEUED"  # wrong state for write-off anyway
        resp = api.write_off_underpayment_case(
            case["id"],
            {"reason": "missing the amount"},
            FD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert get_case(case["id"])["status"] == "QUEUED"


class TestRoleAccess:
    def test_auditor_cannot_create_payer(self, api):
        """PRD §2.1: "A request whose role is valid but not among the roles
        authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_FOR_ROLE`." PRD §4 authorizes only ContractManager for
        `POST /api/payers`.

        Design: Corner/rbac/rbac_auditor_cannot_create_payer
        """
        resp = api.create_payer(
            create_payer_payload(name="Payer X"), AUD
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
        data, meta = validate_paginated(api.list_payers(AUD))
        assert data == []
        assert meta["total_count"] == 0

    def test_finance_director_cannot_post_remittance(self, api):
        """PRD §4 authorizes only RevenueIntegrityAnalyst for
        `POST /api/remittances`; PRD §2.8 rung 2 rejects other roles with
        `ERR_FORBIDDEN_FOR_ROLE` before any existence check.

        Design: Corner/rbac/rbac_finance_director_cannot_post_remittance
        """
        resp = api.create_remittance(
            create_remittance_payload(NON_EXISTENT_UUID, paid_amount_cents=100),
            FD,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_contract_analyst_cannot_activate_contract(self, api):
        """PRD §4 authorizes only ContractManager for
        `POST /api/payer-contracts/{id}/activate`; PRD §2.1 rejects other
        roles with `ERR_FORBIDDEN_FOR_ROLE`.

        Design: Corner/rbac/rbac_contract_analyst_cannot_activate_contract
        """
        payer = create_test_payer(name="Payer CA")
        contract = create_draft_contract(payer["id"], contract_code="CA-2026")
        resp = api.activate_payer_contract(contract["id"], CA)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
        assert get_contract(contract["id"])["status"] == "DRAFT"

    def test_contract_manager_cannot_record_outcome(self, api):
        """PRD §4 authorizes only RecoveryManager for
        `POST /api/appeals/{id}/record_outcome`; PRD §2.8 rung 2 rejects other
        roles with `ERR_FORBIDDEN_FOR_ROLE` before existence is considered.

        Design: Corner/rbac/rbac_contract_manager_cannot_record_outcome
        """
        resp = api.record_appeal_outcome(
            NON_EXISTENT_UUID, create_record_outcome_payload("DENIED"), CM
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_system_admin_can_set_clock_but_cannot_create_claims(self, api):
        """PRD §3.9: "The clock-setting capability itself answers with a sweep
        summary: the new `current_utc` plus the counts `escalators_applied`,
        `amendments_applied`, `appeals_expired`, `contracts_expired`, and
        `alerts_generated`." PRD §4 authorizes only RevenueIntegrityAnalyst
        for `POST /api/claims`.

        Design: Corner/rbac/rbac_system_admin_can_set_clock_but_cannot_create_claims
        """
        payer = create_test_payer(name="Payer SY")
        summary = validate_success(
            api.set_clock({"to_iso8601": "2026-08-03T00:00:00Z"}, SA)
        )
        # PRD §3.9 pins the reported instant ("the new current_utc"), not its
        # serialization; compare instants, not strings.
        reported = datetime.fromisoformat(
            summary["current_utc"].replace("Z", "+00:00")
        )
        assert reported == datetime(2026, 8, 3, tzinfo=timezone.utc)
        resp = api.create_claim(
            {
                "payer_id": payer["id"],
                "claim_number": "CL-SY1",
                "patient_account_number": "PA-SY1",
                "service_category": "LAB",
                "admission_date": "2026-06-01",
                "discharge_date": "2026-06-01",
                "total_billed_charges_cents": 100,
            },
            SA,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_auditor_can_read_any_resource(self, api):
        """PRD §4: "Read endpoints are available to every declared role; the
        table denotes this as \"All roles\"."

        Design: Corner/rbac/rbac_auditor_can_read_any_resource
        """
        payer = create_test_payer(
            name="Payer AU", payer_type="WORKERS_COMP", appeal_deadline_days=60
        )
        fetched = validate_success(api.get_payer(payer["id"], AUD))
        assert fetched["name"] == "Payer AU"
        assert fetched["payer_type"] == "WORKERS_COMP"

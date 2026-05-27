"""Corner-design coverage for validations section: each validation rule
fires its asserted error when violated.
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    set_clock,
    create_decedent,
    create_estate,
    create_designation,
    activate_designation,
    create_executor,
    accept_executor,
    create_directive,
    witness_directive,
    make_planner_headers,
    make_executor_headers,
)


class TestMissingRequiredField:
    def test_missing_date_of_birth_returns_invalid_request(self, api):
        """PRD §2.9: "Syntactic problems — a missing required body field, a
        type mismatch, an enum value outside the declared set, a
        share_basis_points value at or below zero, an amount_cents not
        strictly positive, or any other constraint failure at the body-parse
        layer — surface as ERR_INVALID_REQUEST (HTTP 400)."

        Design: Corner/validations/missing_required_field_returns_invalid_request
        """
        # PRD §3.1: "The minimum profile carries the decedent's
        # full_legal_name, their date_of_birth as an ISO 8601 UTC instant
        # interpreted as a calendar date at midnight..." → date_of_birth is
        # required.
        resp = api.create_decedent(
            {
                "full_legal_name": "Missing DOB",
                "domicile_state_code": "CA",
                "ssn_last4": "0010",
            },
            make_planner_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestShareOverallocation:
    def test_activate_pushing_total_above_10000_rejected(self, api):
        """PRD §3.1: "On any activation — whether manual or as part of the
        finalize cascade — the new sum of share_basis_points across all
        designations on the estate that are or would be ACTIVE must not
        exceed 10000; an overrun is ERR_SHARE_OVERALLOCATION."

        Design: Corner/validations/share_overallocation_on_activate
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Grace G",
            domicile_state_code="CA", ssn_last4="0011",
        )
        estate = create_estate(dec["id"])
        b1 = create_designation(estate["id"], "B1", "CHILD", 7000)
        activate_designation(b1["id"])
        b2 = create_designation(estate["id"], "B2", "CHILD", 4000)
        resp = api.activate_beneficiary_designation(
            b2["id"], make_planner_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_SHARE_OVERALLOCATION)


class TestHipaaRecipientsRequired:
    def test_hipaa_activate_with_empty_recipients_rejected(self, api):
        """PRD §3.4: "for a HIPAA_AUTHORIZATION, the hipaa_authorized_recipients
        array must be non-empty at the time of activation — an authorization
        that names no one to release PHI to is rejected with
        ERR_HIPAA_RECIPIENTS_REQUIRED."

        Design: Corner/validations/hipaa_recipients_required
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Hank H",
            domicile_state_code="NY", ssn_last4="0012",
        )
        directive = create_directive(
            dec["id"], "HIPAA_AUTHORIZATION",
            hipaa_authorized_recipients=[],
        )
        witness_directive(directive["id"])
        resp = api.activate_directive(directive["id"], make_planner_headers())
        validate_error(resp, ApiErrorId.ERR_HIPAA_RECIPIENTS_REQUIRED)


class TestDuplicateExecutorActive:
    def test_second_executor_cannot_accept_while_first_accepted(self, api):
        """PRD §3.2: "Acceptance fails with ERR_DUPLICATE_EXECUTOR_ACTIVE if
        any other executor on the same estate with role_type = EXECUTOR is
        already in ACCEPTED or COURT_CONFIRMED status — only one executor
        at a time can be live."

        Design: Corner/validations/duplicate_executor_active_blocked
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Iris I",
            domicile_state_code="FL", ssn_last4="0013",
        )
        estate = create_estate(dec["id"])
        e1 = create_executor(estate["id"], "Exec I1", "EXECUTOR", False)
        accept_executor(e1["id"])
        e2 = create_executor(estate["id"], "Exec I2", "EXECUTOR", False)
        resp = api.accept_executor(e2["id"], make_executor_headers(e2["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EXECUTOR_ACTIVE)


class TestContingentParentInvalidCrossEstate:
    def test_contingent_parent_on_different_estate_rejected(self, api):
        """PRD §3.1: "On creation or manual activation, if
        contingent_of_designation_id is set, the referenced parent must
        belong to the same estate and must currently be in ACTIVE status —
        failure is ERR_CONTINGENT_PARENT_INVALID."

        Design: Corner/validations/contingent_parent_invalid_cross_estate
        """
        set_clock("2026-01-01T00:00:00Z")
        d1 = create_decedent(
            full_legal_name="J1",
            domicile_state_code="CA", ssn_last4="0014",
        )
        e1 = create_estate(d1["id"])
        other_ben = create_designation(e1["id"], "Other B", "CHILD", 10000)
        activate_designation(other_ben["id"])

        d2 = create_decedent(
            full_legal_name="J2",
            domicile_state_code="CA", ssn_last4="0015",
        )
        e2 = create_estate(d2["id"])
        # Try to create a designation on e2 pointing at e1's designation.
        resp = api.create_beneficiary_designation(
            {
                "estate_id": e2["id"],
                "beneficiary_full_name": "Cross",
                "relationship": "CHILD",
                "share_basis_points": 5000,
                "contingent_of_designation_id": other_ben["id"],
            },
            make_planner_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_CONTINGENT_PARENT_INVALID)

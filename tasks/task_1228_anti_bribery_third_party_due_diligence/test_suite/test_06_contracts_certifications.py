"""Contracts: cross-entity approval gate, clause sets, certification gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    SPONSOR_1_ID,
    create_draft_contract,
    create_verified_certification,
    get_third_party,
    officer_headers,
    set_clock,
    setup_active_contract,
    setup_third_party_in_state,
    sponsor_headers,
    walk_to_approved,
    contract_payload,
    certification_payload,
    validate_error,
    validate_success,
)


class TestContractCreateGate:
    def test_contract_create_requires_third_party_approved(self, api, sponsor_headers):
        """PRD §3.6: "Once a third party is `APPROVED`, the owning sponsor may
        draft a contract against it by supplying `contract_value_cents` (a
        strictly positive integer of USD cents — the denominator of every
        commission ratio), a `start_date`, and an `end_date` that must be later
        than the start date (`ERR_VALIDATION` otherwise). Creating against a
        party in any other status fails with `ERR_THIRD_PARTY_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/contract_create_requires_third_party_approved
        """
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]

        resp = api.create_contract(
            tp_id,
            contract_payload(contract_value_cents=500000, start_date="2026-05-02",
                             end_date="2027-05-01"),
            sponsor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_THIRD_PARTY_NOT_APPROVED)

    def test_contract_create_succeeds_once_approved(self, api, sponsor_headers):
        """PRD §3.6: "Once a third party is `APPROVED`, the owning sponsor may
        draft a contract against it by supplying `contract_value_cents` (a
        strictly positive integer of USD cents — the denominator of every
        commission ratio), a `start_date`, and an `end_date` that must be later
        than the start date (`ERR_VALIDATION` otherwise)."
        PRD §3.6: "The contract is born in `DRAFT` with its payment ledger,
        `approved_payments_total_cents`, at zero."

        Design: Difficulty/cross_entity_state_dependency/contract_create_requires_third_party_approved
        """
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        walk_to_approved(tp_id)

        resp = api.create_contract(
            tp_id,
            contract_payload(contract_value_cents=500000, start_date="2026-05-02",
                             end_date="2027-05-01"),
            sponsor_headers,
        )
        contract = validate_success(resp, 201)
        assert contract["contract_status"] == "DRAFT"
        assert contract["approved_payments_total_cents"] == 0


class TestActivationGates:
    def test_contract_activate_incomplete_clause_set_rejected(self, api, sponsor_headers,
                                                              officer_headers):
        """PRD §3.6: "The attached `clause_codes` must cover the required set
        derived from the party's `approval_tier_snapshot`: `ABAC` alone for `LOW`
        or `MEDIUM`; `ABAC`, `AUDIT_RIGHTS`, and `ANNUAL_CERTIFICATION` for
        `HIGH`; and for `CRITICAL` those three plus `TERMINATION_FOR_CAUSE` and
        `GOVT_OFFICIAL_DISCLOSURE` — a shortfall is `ERR_CLAUSE_SET_INCOMPLETE`."

        Design: Corner/validations/contract_activate_incomplete_clause_set_rejected
        """
        # CU cpi 36 -> norm 64; CONSULTING/DIRECT -> score 70 -> HIGH snapshot.
        ctx = setup_third_party_in_state("APPROVED", "CU", 36, "CONSULTING", "DIRECT")
        tp_id = ctx["third_party"]["id"]
        assert get_third_party(tp_id)["approval_tier_snapshot"] == "HIGH"

        contract = create_draft_contract(tp_id, SPONSOR_1_ID, 500000)
        validate_success(
            api.attach_clauses(contract["id"], {"clause_codes": ["ABAC", "AUDIT_RIGHTS"]},
                               sponsor_headers), 200)
        create_verified_certification(tp_id, SPONSOR_1_ID)

        resp = api.activate_contract(contract["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_CLAUSE_SET_INCOMPLETE)
        after = validate_success(api.get_contract(contract["id"], officer_headers), 200)
        assert after["contract_status"] == "PENDING_CLAUSES"

    def test_contract_activate_without_certification_rejected(self, api, sponsor_headers,
                                                              officer_headers):
        """PRD §3.6: "The referential gates themselves require the party to be
        `APPROVED` (`ERR_THIRD_PARTY_NOT_APPROVED`), at least one certification
        in `VERIFIED` status to exist for the party (`ERR_CERTIFICATION_REQUIRED`),
        and no re-diligence cycle of the party to be `OVERDUE`
        (`ERR_REDILIGENCE_OVERDUE`)."

        Design: Corner/validations/contract_activate_without_certification_rejected
        """
        ctx = setup_third_party_in_state("APPROVED", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        contract = create_draft_contract(tp_id, SPONSOR_1_ID, 500000)
        validate_success(
            api.attach_clauses(contract["id"], {"clause_codes": ["ABAC"]},
                               sponsor_headers), 200)
        # No certification is ever issued.

        resp = api.activate_contract(contract["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED)

    def test_contract_activate_with_overdue_rediligence_rejected(self, api, sponsor_headers,
                                                                 officer_headers, admin_headers):
        """PRD §3.6: "The referential gates themselves require the party to be
        `APPROVED` (`ERR_THIRD_PARTY_NOT_APPROVED`), at least one certification
        in `VERIFIED` status to exist for the party (`ERR_CERTIFICATION_REQUIRED`),
        and no re-diligence cycle of the party to be `OVERDUE`
        (`ERR_REDILIGENCE_OVERDUE`)."
        PRD §3.9: "The clock sweep moves a `SCHEDULED` or `IN_PROGRESS` cycle to
        `OVERDUE` once the current date passes its `due_date`"

        Design: Corner/validations/contract_activate_with_overdue_rediligence_rejected
        """
        # HIGH third party: auto cycle due 2026-05-01 + 180d = 2026-10-28.
        ctx = setup_third_party_in_state("APPROVED", "CU", 36, "CONSULTING", "DIRECT")
        tp_id = ctx["third_party"]["id"]
        contract = create_draft_contract(tp_id, SPONSOR_1_ID, 500000,
                                         start_date="2026-05-02", end_date="2028-05-01")
        validate_success(
            api.attach_clauses(
                contract["id"],
                {"clause_codes": ["ABAC", "AUDIT_RIGHTS", "ANNUAL_CERTIFICATION"]},
                sponsor_headers), 200)
        create_verified_certification(tp_id, SPONSOR_1_ID)

        # One day past the due date: the sweep flips the cycle to OVERDUE; the
        # party is still inside the 30-day grace, and the certification is still
        # VERIFIED until 2027-05-01 — re-diligence is the only failing gate.
        set_clock("2026-10-29T00:00:00Z")
        cycles = validate_success(api.list_rediligence_cycles(tp_id, officer_headers), 200)
        assert cycles[0]["cycle_status"] == "OVERDUE"

        resp = api.activate_contract(contract["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_REDILIGENCE_OVERDUE)


class TestCertificationValidity:
    def test_certification_valid_until_plus_365_days(self, api, sponsor_headers,
                                                     officer_headers):
        """PRD §3.6: "An officer then verifies it, moving to `VERIFIED` and
        setting `valid_until` to the verification date plus 365 days, or rejects
        it with an optional `reason`, moving to `REJECTED` from where
        resubmission is allowed."
        PRD §2.5: "At startup, before any operator intervention, the clock reads
        exactly 2026-05-01T00:00:00Z."

        Design: Corner/calculations/certification_valid_until_plus_365_days
        """
        ctx = setup_third_party_in_state("SCREENING", "CH", 80)
        tp_id = ctx["third_party"]["id"]

        cert = validate_success(
            api.create_certification(tp_id, certification_payload(cert_type="ANNUAL_ABAC"),
                                     officer_headers), 201)
        validate_success(
            api.submit_certification(cert["id"], {"document_ref": "s3://certs/ch.pdf"},
                                     sponsor_headers), 200)
        verified = validate_success(api.verify_certification(cert["id"], officer_headers), 200)
        assert verified["cert_status"] == "VERIFIED"
        assert str(verified["valid_until"]).startswith("2027-05-01"), (
            "verification at 2026-05-01 sets valid_until to 2027-05-01 (+365 days)"
        )

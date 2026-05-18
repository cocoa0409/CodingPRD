"""End-of-life directives, HIPAA authorizations, and Powers of
Attorney — creation, execution, revocation, supersession.

Coverage targets (PRD §3.1, §3.2, §3.13):
- HIPAA scope coverage for directive execution.
- Directive DRAFT->EXECUTED requires Estate in IN_PROBATE/INVENTORIED.
- Directive SUPERSEDED->DRAFT revision loop.
- POA gate on Asset mutation while Estate is DRAFT.
- POA revocation.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    asset_state_payload,
    create_asset_payload,
    create_directive_payload,
    create_estate_with_executor,
    create_hipaa_payload,
    create_poa_payload,
    declare_asset,
    directive_state_payload,
    estate_state_payload,
    get_success_data,
    hipaa_state_payload,
    nominate_fiduciary,
    poa_state_payload,
    server_offset_iso,
    setup_active_hipaa_and_draft_directive,
    setup_directive_superseded,
    setup_in_probate,
    setup_with_active_poa_on_real_estate,
    validate_error,
    validate_success,
)


class TestDirectiveExecute:

    def test_execute_with_active_covering_hipaa(self, api):
        """PRD §3.13: "The execution precondition is HIPAA scope
        coverage: there must exist a HIPAAAuthorization whose status
        is ACTIVE and whose scope covers the directive's
        requires_hipaa_scope. ... On success, executed_at is set to
        the moment of execution and the directive moves to EXECUTED."

        Claim: directive with ALL-scope HIPAA active -> EXECUTED.
        """
        bundle = setup_active_hipaa_and_draft_directive(
            scope="ALL", requires_hipaa_scope="ALL",
        )
        estate = bundle["estate"]
        directive = bundle["directive"]
        exec_h = bundle["executor_headers"]
        resp = api_client.transition_directive(
            estate["id"], directive["id"],
            directive_state_payload("EXECUTED"),
            exec_h,
        )
        updated = validate_success(resp)
        assert updated["status"] == "EXECUTED"
        assert updated.get("executed_at"), (
            "executed_at must be set on EXECUTED"
        )

    def test_execute_without_covering_hipaa_rejected(self, api):
        """PRD §3.13: "Absent a covering active authorization, the
        execution is rejected with ERR_HIPAA_SCOPE_INSUFFICIENT and
        HTTP 403."

        Claim: directive requires_hipaa_scope=ALL but only
        MEDICAL_RECORDS HIPAA is active -> rejected.
        """
        bundle = setup_active_hipaa_and_draft_directive(
            scope="MEDICAL_RECORDS", requires_hipaa_scope="ALL",
        )
        estate = bundle["estate"]
        directive = bundle["directive"]
        exec_h = bundle["executor_headers"]
        resp = api_client.transition_directive(
            estate["id"], directive["id"],
            directive_state_payload("EXECUTED"),
            exec_h,
        )
        validate_error(resp,
                       ApiErrorId.ERR_HIPAA_SCOPE_INSUFFICIENT.value)

    def test_execute_with_matching_specific_scope(self, api):
        """PRD §3.13: "Scope coverage follows the natural enumeration
        — ALL covers any required scope, and any non-ALL scope
        covers only the matching scope (e.g., MEDICAL_RECORDS
        covers MEDICAL_RECORDS only)."

        Claim: MEDICAL_RECORDS HIPAA covers a MEDICAL_RECORDS
        directive -> 200.
        """
        bundle = setup_active_hipaa_and_draft_directive(
            scope="MEDICAL_RECORDS",
            requires_hipaa_scope="MEDICAL_RECORDS",
        )
        estate = bundle["estate"]
        directive = bundle["directive"]
        exec_h = bundle["executor_headers"]
        resp = api_client.transition_directive(
            estate["id"], directive["id"],
            directive_state_payload("EXECUTED"),
            exec_h,
        )
        updated = validate_success(resp)
        assert updated["status"] == "EXECUTED"


class TestDirectiveRevisionLoop:

    def test_supersede_chain_marks_prior_superseded(self, api):
        """PRD §3.1: "Optionally supersedes_directive_id points at an
        earlier directive; if supplied at creation, the prior
        directive (in either DRAFT or EXECUTED) auto-transitions to
        SUPERSEDED."

        Claim: a new directive with supersedes_directive_id flips
        the prior to SUPERSEDED.
        """
        bundle = setup_directive_superseded()
        d1 = bundle["directive_d1"]
        d2 = bundle["directive_d2"]
        assert d1["status"] == "SUPERSEDED"
        assert d2["status"] == "DRAFT"

    def test_superseded_back_to_draft_allowed(self, api):
        """PRD §3.1: "The revision loop is cyclic: an executor may
        move a SUPERSEDED directive back to DRAFT provided the
        estate has not yet SETTLED, allowing renewed drafting on
        the same row."

        Claim: SUPERSEDED -> DRAFT succeeds while estate is in
        IN_PROBATE.
        """
        bundle = setup_directive_superseded()
        estate = bundle["estate"]
        d1 = bundle["directive_d1"]
        exec_h = bundle["executor_headers"]
        resp = api_client.transition_directive(
            estate["id"], d1["id"],
            directive_state_payload("DRAFT"),
            exec_h,
        )
        updated = validate_success(resp)
        assert updated["status"] == "DRAFT"


class TestHipaaRevoke:

    def test_revoke_active_hipaa(self, api):
        """PRD §3.1: "The executor may also explicitly revoke an
        active authorization, moving it to REVOKED."

        Claim: ACTIVE -> REVOKED succeeds.
        """
        bundle = setup_active_hipaa_and_draft_directive(scope="ALL")
        estate = bundle["estate"]
        hipaa = bundle["hipaa"]
        exec_h = bundle["executor_headers"]
        resp = api_client.transition_hipaa(
            estate["id"], hipaa["id"],
            hipaa_state_payload("REVOKED"),
            exec_h,
        )
        updated = validate_success(resp)
        assert updated["status"] == "REVOKED"


class TestPoaGateOnAssetMutation:

    def test_patch_requires_active_poa_in_draft(self, api):
        """PRD §3.2: "when an asset is created with
        requires_poa_for_mutation set to true (the default is
        false), the executor cannot mutate it during DRAFT unless an
        ACTIVE PowerOfAttorney exists on the estate whose
        asset_class_scope covers that asset's asset_class. This
        gate applies to two operations specifically — the PATCH
        that updates description or declared_value_cents, and the
        state-transition POST that advances the asset's status. If
        the gate fires (no covering active POA), the request is
        rejected with ERR_POA_SCOPE_INSUFFICIENT and HTTP 403."

        Claim: PATCH on a requires_poa_for_mutation=true asset in
        DRAFT with no covering POA -> ERR_POA_SCOPE_INSUFFICIENT.
        """
        estate, _, exec_h = create_estate_with_executor()
        asset = declare_asset(
            estate["id"], asset_class="REAL_ESTATE",
            declared_value_cents=1000,
            requires_poa_for_mutation=True,
            exec_headers=exec_h,
        )
        resp = api_client.update_asset(
            estate["id"], asset["id"],
            {"description": "new"}, exec_h,
        )
        validate_error(resp,
                       ApiErrorId.ERR_POA_SCOPE_INSUFFICIENT.value)

    def test_patch_succeeds_with_covering_active_poa(self, api):
        """PRD §3.2: "the executor cannot mutate it during DRAFT
        unless an ACTIVE PowerOfAttorney exists on the estate whose
        asset_class_scope covers that asset's asset_class."

        Claim: with an ACTIVE POA covering REAL_ESTATE, PATCH on a
        REAL_ESTATE asset succeeds.
        """
        bundle = setup_with_active_poa_on_real_estate(
            asset_class="REAL_ESTATE",
        )
        estate = bundle["estate"]
        asset = bundle["asset"]
        exec_h = bundle["executor_headers"]
        poa = bundle["poa"]
        assert poa["status"] == "ACTIVE", (
            f"Setup must produce ACTIVE POA, got {poa['status']!r}"
        )
        resp = api_client.update_asset(
            estate["id"], asset["id"],
            {"description": "updated description"}, exec_h,
        )
        updated = validate_success(resp)
        assert updated["description"] == "updated description"


class TestPoaRevoke:

    def test_revoke_pending_poa(self, api):
        """PRD §3.1: "The executor may revoke a POA from either
        PENDING or ACTIVE at any time, which sets revoked_at to the
        moment of revocation and moves the row to REVOKED."

        Claim: PENDING -> REVOKED succeeds and sets revoked_at.
        """
        estate, _, exec_h = create_estate_with_executor()
        agent = nominate_fiduciary(estate["id"], scope_type="TRUSTEE")
        poa_resp = api_client.create_poa(
            estate["id"],
            create_poa_payload(
                agent_fiduciary_id=agent["id"],
                asset_class_scope=["FINANCIAL"],
                effective_at=server_offset_iso(days=30),
            ),
            exec_h,
        )
        poa = get_success_data(poa_resp)
        assert poa["status"] == "PENDING"
        resp = api_client.transition_poa(
            estate["id"], poa["id"],
            poa_state_payload("REVOKED"), exec_h,
        )
        updated = validate_success(resp)
        assert updated["status"] == "REVOKED"
        assert updated.get("revoked_at"), (
            "revoked_at must be set on REVOKED"
        )

"""Concurrency races — PRD §3.7 (filing-already-pending), §3.15
(duplicate executor), §3.10 (disclaim vs advance), §3.13 (HIPAA
revoke vs directive execute).

Each test exercises a PRD-pinned race whose loser-error PRD prose
names explicitly.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    beneficiary_state_payload,
    create_filing_payload,
    directive_state_payload,
    estate_state_payload,
    fiduciary_state_payload,
    hipaa_state_payload,
    make_beneficiary_headers,
    run_race,
    setup_active_hipaa_and_draft_directive,
    setup_disclaimed_beneficiary_blocks_distributing,
    setup_in_probate,
    setup_two_nominated_executors_first_confirmed,
    validate_error_is_one_of,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
)


class TestFilingAlreadyPendingRace:

    def test_two_inventory_reports_race(self, api):
        """PRD §3.7: "Two distinct filings of the same type cannot
        both sit in SUBMITTED at the same time on the same estate.
        ... the second create races against the first; the loser
        receives ERR_FILING_ALREADY_PENDING with HTTP 409.
        First-writer-wins on the tuple of (estate_id, filing_type,
        status=SUBMITTED)."

        Claim: two concurrent INVENTORY_REPORT POSTs — exactly one
        succeeds; the other gets ERR_FILING_ALREADY_PENDING.
        """
        bundle = setup_in_probate()
        estate = bundle["estate"]
        executor = bundle["executor"]
        exec_h = bundle["executor_headers"]
        payload = create_filing_payload(
            filing_type="INVENTORY_REPORT",
            filed_by_fiduciary_id=executor["id"],
        )
        results = run_race(
            lambda: api_client.create_filing(
                estate["id"], payload, exec_h,
            ),
            lambda: api_client.create_filing(
                estate["id"], payload, exec_h,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_FILING_ALREADY_PENDING.value],
        )


class TestDuplicateExecutorRace:

    def test_two_confirms_on_two_executors_race(self, api):
        """PRD §3.15: "If two clerks attempt to confirm two different
        EXECUTOR nominees simultaneously, the two requests race on
        the tuple (estate_id, scope_type=EXECUTOR, status=CONFIRMED);
        first-writer-wins, and the loser also receives
        ERR_DUPLICATE_EXECUTOR."

        Claim: two concurrent confirms on two EXECUTOR nominees ->
        exactly one succeeds; the loser gets ERR_DUPLICATE_EXECUTOR.
        """
        # Set up TWO NOMINATED executors — but no CONFIRMED one yet.
        from test_helpers import (
            create_estate_with_executor, nominate_fiduciary,
        )
        estate, f1, _ = create_estate_with_executor(
            bond_amount_cents=25_000,
        )
        f2 = nominate_fiduciary(
            estate["id"], scope_type="EXECUTOR",
            bond_amount_cents=25_000,
        )
        payload = fiduciary_state_payload("CONFIRMED")
        results = run_race(
            lambda: api_client.transition_fiduciary(
                estate["id"], f1["id"], payload,
                TEST_USERS["court_clerk_headers"],
            ),
            lambda: api_client.transition_fiduciary(
                estate["id"], f2["id"], payload,
                TEST_USERS["court_clerk_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_DUPLICATE_EXECUTOR.value],
        )


class TestHipaaRevokeVsDirectiveExecuteRace:

    def test_revoke_vs_execute_directive(self, api):
        """PRD §3.13: "When an executor revokes a HIPAA
        authorization in the same window that another request is
        executing a directive dependent on it, the two requests
        race on HIPAAAuthorization.status and first-writer-wins. If
        the revoke commits first, the directive execution sees no
        covering authorization and is rejected with
        ERR_HIPAA_SCOPE_INSUFFICIENT. If the execute commits first,
        the directive remains EXECUTED and the revocation proceeds
        normally."

        Claim: concurrent revoke + execute — at least one succeeds.
        If both succeed, the directive is EXECUTED (execute won
        first). If exactly one succeeds, either is valid; if the
        loser is the execute, error_id must be
        ERR_HIPAA_SCOPE_INSUFFICIENT.
        """
        bundle = setup_active_hipaa_and_draft_directive(
            scope="ALL", requires_hipaa_scope="ALL",
        )
        estate = bundle["estate"]
        hipaa = bundle["hipaa"]
        directive = bundle["directive"]
        exec_h = bundle["executor_headers"]
        results = run_race(
            lambda: api_client.transition_hipaa(
                estate["id"], hipaa["id"],
                hipaa_state_payload("REVOKED"),
                exec_h,
            ),
            lambda: api_client.transition_directive(
                estate["id"], directive["id"],
                directive_state_payload("EXECUTED"),
                exec_h,
            ),
        )
        # PRD does NOT guarantee mutual exclusion: if execute
        # commits before revoke completes, both can succeed. So we
        # only assert "at least one succeeds".
        outcome = assert_at_least_one_succeeds(*results)
        # If the directive-execute attempt was the failure (i.e.,
        # revoke won), it must carry ERR_HIPAA_SCOPE_INSUFFICIENT.
        # We identify the execute result by request URL — but since
        # we lack request introspection on the response object,
        # we instead inspect failure responses: if any failure
        # exists, it must be ERR_HIPAA_SCOPE_INSUFFICIENT (the
        # only loser-error PRD names).
        for f in outcome["failures"]:
            validate_error_is_one_of(
                f, [ApiErrorId.ERR_HIPAA_SCOPE_INSUFFICIENT.value],
            )


class TestDisclaimVsAdvanceRace:

    def test_disclaim_vs_distributing_advance(self, api):
        """PRD §3.10: "Suppose a beneficiary disclaims at the same
        moment the executor attempts to advance the estate from
        INVENTORIED to DISTRIBUTING. The two requests race on the
        same Estate.admin_phase row, and first-writer-wins. If the
        disclaim commits first, the subsequent state advance fails
        ... the executor receives ERR_INVALID_STATE. If the advance
        commits first, the disclaim still succeeds — disclaim has
        no precondition against admin_phase DISTRIBUTING — and the
        LOCKED → VOIDED cascade fires on the now-locked rows".

        Claim: concurrent disclaim + advance — at least one of the
        two operations succeeds. If the advance fails, its error
        must be ERR_INVALID_STATE; this is the only loser-error PRD
        names for this race.

        Note: PRD says ERR_INVALID_STATE for the advance loser,
        but the advance precondition that fires is per-asset share
        sum < 10000 (after disclaim cascade voids designations) —
        which PRD §3.11 says yields ERR_DESIGNATIONS_INCOMPLETE,
        not ERR_INVALID_STATE. PRD §3.10 prose is in tension here.
        We use validate_error_is_one_of to accept either.
        """
        bundle = setup_disclaimed_beneficiary_blocks_distributing()
        estate = bundle["estate"]
        ben = bundle["beneficiary"]
        exec_h = bundle["executor_headers"]
        h_b = make_beneficiary_headers(ben["id"])
        results = run_race(
            lambda: api_client.transition_beneficiary(
                estate["id"], ben["id"],
                beneficiary_state_payload("DISCLAIMED"), h_b,
            ),
            lambda: api_client.transition_estate(
                estate["id"], estate_state_payload("DISTRIBUTING"),
                exec_h,
            ),
        )
        outcome = assert_at_least_one_succeeds(*results)
        for f in outcome["failures"]:
            validate_error_is_one_of(f, [
                ApiErrorId.ERR_INVALID_STATE.value,
                ApiErrorId.ERR_DESIGNATIONS_INCOMPLETE.value,
            ])

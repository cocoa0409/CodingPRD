"""Optimistic concurrency and PRD-named race outcomes (PRD §2.7,
§3.5, §3.6, §3.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_and_pre_qualify,
    extend_rate_lock_payload,
    issue_disclosure_payload,
    place_rate_lock,
    run_race,
    setup_application_in_underwriting,
    setup_application_ready_for_underwriting,
    submit_underwriting_payload,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Rate-lock extension first-writer-wins — PRD §3.5
# ===========================================================================
def test_concurrent_rate_lock_extensions_one_wins(api, loan_officer_headers):
    """PRD §3.5: "The system serialises extension requests on the
    same lock: if two extension requests arrive concurrently, exactly
    one is granted and the second is rejected with
    ERR_EXTENSION_IN_FLIGHT before any fee_cents is computed
    (first-writer-wins on RateLockExtension creation per
    rate_lock_id)."

    Claim: two concurrent extend(7) calls on the same RateLock produce
    exactly one success and one failure; the failing one carries
    ERR_EXTENSION_IN_FLIGHT.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        headers=loan_officer_headers,
    )
    place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    results = run_race(
        lambda: api.extend_rate_lock(
            app["id"], extend_rate_lock_payload(extra_days=7),
            loan_officer_headers,
        ),
        lambda: api.extend_rate_lock(
            app["id"], extend_rate_lock_payload(extra_days=7),
            loan_officer_headers,
        ),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    # The loser must carry ERR_EXTENSION_IN_FLIGHT (PRD §3.5 names it).
    failure_resp = outcome["failures"][0]
    failure_id = validate_error_is_one_of(
        failure_resp,
        [ApiErrorId.ERR_EXTENSION_IN_FLIGHT.value],
    )
    assert failure_id == ApiErrorId.ERR_EXTENSION_IN_FLIGHT.value


# ===========================================================================
# Disclosure concurrent issuance first-writer-wins — PRD §3.6
# ===========================================================================
def test_concurrent_loan_estimate_issuance_one_wins(api, loan_officer_headers):
    """PRD §3.6: "Concurrent issuance of two disclosures of the same
    kind for the same application is serialised: exactly one new
    version persists; the loser receives ERR_DISCLOSURE_VERSION_CONFLICT."

    Claim: two concurrent POST /disclosures kind=LOAN_ESTIMATE calls
    on the same application -> exactly one success; the loser carries
    ERR_DISCLOSURE_VERSION_CONFLICT.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    results = run_race(
        lambda: api.issue_disclosure(
            app["id"],
            issue_disclosure_payload(
                kind="LOAN_ESTIMATE", apr_bps=650,
                total_loan_costs_cents=500_000,
                total_other_costs_cents=800_000,
            ),
            loan_officer_headers,
        ),
        lambda: api.issue_disclosure(
            app["id"],
            issue_disclosure_payload(
                kind="LOAN_ESTIMATE", apr_bps=650,
                total_loan_costs_cents=500_000,
                total_other_costs_cents=800_000,
            ),
            loan_officer_headers,
        ),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    failure_resp = outcome["failures"][0]
    failure_id = validate_error_is_one_of(
        failure_resp,
        [ApiErrorId.ERR_DISCLOSURE_VERSION_CONFLICT.value],
    )
    assert failure_id == ApiErrorId.ERR_DISCLOSURE_VERSION_CONFLICT.value


# ===========================================================================
# Concurrent compliance_reviewer assignment on submit-underwriting — PRD §3.7
# ===========================================================================
def test_concurrent_submit_underwriting_one_wins(api, loan_officer_headers):
    """PRD §3.7: "If two loan officers attempt to submit the same
    application concurrently and assign different compliance reviewers,
    exactly one assignment succeeds and the loser receives
    ERR_COMPLIANCE_REVIEWER_CONFLICT (first-writer-wins on
    compliance_reviewer_id)."

    Claim: two concurrent submit-underwriting calls assigning different
    compliance_reviewer_id values produce exactly one success; the
    loser carries ERR_COMPLIANCE_REVIEWER_CONFLICT.
    """
    _, app, _, _ = setup_application_ready_for_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
    )
    results = run_race(
        lambda: api.submit_underwriting(
            app["id"],
            submit_underwriting_payload(compliance_reviewer_id="co-001"),
            loan_officer_headers,
        ),
        lambda: api.submit_underwriting(
            app["id"],
            submit_underwriting_payload(compliance_reviewer_id="co-002"),
            loan_officer_headers,
        ),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    failure_resp = outcome["failures"][0]
    # PRD §3.7 names the specific error_id; the loser's path here is
    # exactly the named race. PRD §2.10 puts state checks before this,
    # but both calls see the same PRE_QUALIFIED source state, so only
    # the compliance-reviewer race actually differentiates them.
    failure_id = validate_error_is_one_of(
        failure_resp,
        [
            ApiErrorId.ERR_COMPLIANCE_REVIEWER_CONFLICT.value,
            # If the implementation serialises state advancement so the
            # loser sees UNDERWRITING instead of PRE_QUALIFIED, the
            # state check at priority 5 may surface first — accept
            # either as a PRD-faithful outcome.
            ApiErrorId.ERR_INVALID_STATE.value,
        ],
    )
    assert failure_id in (
        ApiErrorId.ERR_COMPLIANCE_REVIEWER_CONFLICT.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    )


# ===========================================================================
# OCC version check — PRD §2.7
# ===========================================================================
def test_stale_version_rejected_on_mutation(api, loan_officer_headers):
    """PRD §2.7: "When supplied, the value must equal the resource's
    current version; if it does not, the request is rejected with
    ERR_VERSION_CONFLICT."

    Claim: capture an application's version, mutate it (pre-qualify)
    so the version increments, then attempt another mutation supplying
    the stale version — the response is ERR_VERSION_CONFLICT.

    NOTE: PRD §2.7 says "Endpoints that mutate an existing resource
    accept an optional version integer in the request body." The
    /pre-qualify endpoint is a mutation, so its body MAY carry version.
    """
    from test_helpers import create_borrower_and_application
    _, app = create_borrower_and_application(headers=loan_officer_headers)
    stale_version = app["version"]
    # Mutate so the version moves.
    out = validate_success(api.pre_qualify(
        app["id"], None, loan_officer_headers,
    ), 200)
    assert out["version"] > stale_version, (
        "PRD §2.4: version increments by exactly one on every mutation."
    )
    # Re-attempt pre-qualify (from PRE_QUALIFIED state — this would
    # ALSO fail with ERR_INVALID_STATE due to wrong source state).
    # To isolate the OCC path we attempt withdraw with a stale
    # version — withdraw from PRE_QUALIFIED is a valid transition, so
    # the only path to error here is the stale version.
    res = api.withdraw_application(
        app["id"], {"version": stale_version}, loan_officer_headers,
    )
    # PRD §2.7: stale version -> ERR_VERSION_CONFLICT. PRD §2.10
    # places OCC at priority 20, after state-check (P5) — both
    # PRE_QUALIFIED-to-WITHDRAWN is a valid transition, so state is
    # fine; the OCC mismatch is the only failure. Accept exact match.
    validate_error_is_one_of(
        res,
        [ApiErrorId.ERR_VERSION_CONFLICT.value],
    )


def test_correct_version_accepted_on_mutation(api, loan_officer_headers):
    """PRD §2.7: "When supplied, the value must equal the resource's
    current version; if it does not, the request is rejected with
    ERR_VERSION_CONFLICT."

    Claim: a mutation that supplies the current correct version
    succeeds.
    """
    from test_helpers import create_borrower_and_application
    _, app = create_borrower_and_application(headers=loan_officer_headers)
    current = app["version"]
    out = validate_success(api.withdraw_application(
        app["id"], {"version": current}, loan_officer_headers,
    ), 200)
    assert out["status"] == "WITHDRAWN"


def test_version_omitted_processes_without_occ_check(api, loan_officer_headers):
    """PRD §2.7: "When the field is omitted, the server processes the
    mutation without an OCC check."

    Claim: omitting version on a mutation succeeds — no
    ERR_VERSION_CONFLICT is raised.
    """
    from test_helpers import create_borrower_and_application
    _, app = create_borrower_and_application(headers=loan_officer_headers)
    out = validate_success(api.withdraw_application(
        app["id"], None, loan_officer_headers,
    ), 200)
    assert out["status"] == "WITHDRAWN"

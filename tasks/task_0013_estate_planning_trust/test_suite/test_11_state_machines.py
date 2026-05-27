"""Corner-design coverage for state_machines section: terminal lockdown,
invalid transitions.
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    validate_paginated,
    ApiErrorId,
    bootstrap_estate_closed,
    set_clock,
    create_decedent,
    create_estate,
    create_executor,
    accept_executor,
    make_executor_headers,
    make_beneficiary_headers,
    make_planner_headers,
)


class TestTerminalEstateClosedLockdown:
    def test_closed_estate_rejects_contest(self, api):
        """PRD §3.8: "A CLOSED estate is terminal — no further mutations are
        accepted on it."
        PRD §3.7: "A Beneficiary may at any time while the estate is in
        PROBATE_OPEN initiate a contest. The contest action moves the estate
        from PROBATE_OPEN to CONTESTED."

        Design: Corner/state_machines/terminal_estate_closed_rejects_further_transitions
        """
        # Note: a CLOSED estate has no Beneficiary tied to it for ownership
        # purposes, so we use the fallback opaque beneficiary headers; this
        # test is independent of ownership (state check fires regardless of
        # who initiates because state precedes other checks per §2.9).
        # We need a beneficiary id; the bootstrap doesn't expose one
        # directly because designations were created inside bootstrap.
        # Use a dummy designation id for the headers; the contest fails on
        # the state check (priority 4 < ownership/auth).
        ctx = bootstrap_estate_closed(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-15T00:00:00Z",
            asset_value_cents=100000,
            domicile_state_code="CA",
        )
        est = ctx["estate"]
        assert est["status"] == "CLOSED"
        # List the designations on the estate so the Beneficiary header
        # carries a real designation id (ownership-gated call).
        list_resp = api.list_beneficiary_designations(
            make_planner_headers(),
            params={"estate_id": est["id"]},
        )
        designations, _meta = validate_paginated(list_resp)
        assert designations, "Estate should have at least one designation"
        ben_id = designations[0]["id"]
        # Try to contest — should fail with ERR_INVALID_STATE.
        resp = api.contest_estate(
            est["id"],
            expected_estate_version=est["version"],
            reason="post-close",
            headers=make_beneficiary_headers(ben_id),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestExecutorInvalidTransitions:
    def test_decline_from_accepted_rejected(self, api):
        """PRD §3.2: "The named candidate accepts or declines. Acceptance
        moves NOMINATED -> ACCEPTED and writes the accepting executor's id
        into the parent Estate.executor_user_id; the estate's version
        increments by one."
        PRD §3.2: "Declining moves NOMINATED -> DECLINED and, if that
        declining executor's id happened to be sitting in
        Estate.executor_user_id, that pointer is cleared back to null;
        declining is permitted unless the estate is already CLOSED."

        Design: Corner/state_machines/executor_decline_from_accepted_invalid_state
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Dora D",
            domicile_state_code="NY", ssn_last4="0007",
        )
        estate = create_estate(dec["id"])
        executor = create_executor(estate["id"], "Exec D", "EXECUTOR", False)
        executor = accept_executor(executor["id"])
        assert executor["status"] == "ACCEPTED"
        # Now try to decline — invalid transition (only NOMINATED can decline).
        resp = api.decline_executor(
            executor["id"], make_executor_headers(executor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

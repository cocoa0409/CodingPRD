"""Fiduciary nomination, confirmation, removal, and resignation.

Coverage targets (PRD §3.1, §3.15):
- New Fiduciary in NOMINATED.
- CONFIRMED clerk-only; sets court_confirmation_at.
- ERR_DUPLICATE_EXECUTOR — already one CONFIRMED EXECUTOR.
- ERR_NO_MINOR_BENEFICIARY — confirming GUARDIAN with no minor.
- ERR_NO_SUCCESSOR — EXECUTOR resigning mid-probate without
  NOMINATED successor.
- RESIGNED self-only ownership.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_beneficiary,
    api_client,
    assert_fiduciary,
    confirm_fiduciary,
    create_estate_with_executor,
    create_fiduciary_payload,
    fiduciary_state_payload,
    get_success_data,
    make_executor_headers,
    make_fiduciary_headers,
    nominate_fiduciary,
    setup_in_probate,
    setup_two_nominated_executors_first_confirmed,
    validate_error,
    validate_success,
)


class TestFiduciaryNomination:

    def test_nominate_fiduciary_starts_nominated(self, api):
        """PRD §3.1: "A nominated fiduciary's status is NOMINATED and
        its court_confirmation_at is null".

        Claim: POST /estates/.../fiduciaries -> 201 with
        status=NOMINATED and court_confirmation_at null.
        """
        estate, _, _ = create_estate_with_executor()
        # Nominate a TRUSTEE.
        f = nominate_fiduciary(
            estate["id"], scope_type="TRUSTEE",
        )
        assert_fiduciary(f)
        assert f["status"] == "NOMINATED"
        assert f.get("court_confirmation_at") in (None, ""), (
            f"court_confirmation_at must be null on NOMINATED, "
            f"got {f.get('court_confirmation_at')!r}"
        )


class TestFiduciaryConfirm:

    def test_confirm_sets_court_confirmation_at(self, api):
        """PRD §3.1: "the CourtClerk will later transition it to
        CONFIRMED, which writes court_confirmation_at to the moment
        of the transition."

        Claim: NOMINATED -> CONFIRMED sets court_confirmation_at.
        """
        estate, executor, _ = create_estate_with_executor(
            bond_amount_cents=25_000,
        )
        confirmed = confirm_fiduciary(estate["id"], executor["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed.get("court_confirmation_at"), (
            "court_confirmation_at must be set on CONFIRMED"
        )

    def test_confirm_executor_only_court_clerk(self, api):
        """PRD §3.1, §1.7: CONFIRMED transition on a Fiduciary is
        CourtClerk-only. PRD §4 endpoint table lists fiduciary state
        endpoint as CourtClerk-or-Fiduciary; PRD §3.1 narrative pins
        CONFIRMED specifically to CourtClerk.

        Claim: Executor attempting to confirm a NOMINATED executor
        -> ERR_FORBIDDEN.

        Note: PRD §1.7 mentions Executor and Fiduciary share the
        transition endpoint, but PRD §3.1 narrative narrowly assigns
        the CONFIRMED action to CourtClerk. The PRD-prose-pinned
        scope is the contract.
        """
        # Per PRD §1.7 the transition endpoint allows CourtClerk and
        # Fiduciary roles only — Executor is NOT in the role list
        # for that endpoint. So an Executor calling it -> ERR_FORBIDDEN.
        estate, executor, exec_h = create_estate_with_executor(
            bond_amount_cents=25_000,
        )
        resp = api_client.transition_fiduciary(
            estate["id"], executor["id"],
            fiduciary_state_payload("CONFIRMED"),
            exec_h,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_duplicate_executor_rejected(self, api):
        """PRD §3.15: "If a CourtClerk attempts to confirm a
        NOMINATED executor while another Fiduciary with scope_type
        EXECUTOR is already in CONFIRMED on the estate, the second
        confirm is rejected with ERR_DUPLICATE_EXECUTOR."

        Claim: two EXECUTOR fiduciaries — first one CONFIRMED;
        attempt to confirm the second -> ERR_DUPLICATE_EXECUTOR.
        """
        bundle = setup_two_nominated_executors_first_confirmed(
            bond_amount_cents=25_000,
        )
        resp = api_client.transition_fiduciary(
            bundle["estate"]["id"], bundle["second_executor"]["id"],
            fiduciary_state_payload("CONFIRMED"),
            TEST_USERS["court_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EXECUTOR.value)

    def test_confirm_guardian_without_minor_rejected(self, api):
        """PRD §3.1: "Confirming a nominee as GUARDIAN requires that
        at least one Beneficiary with is_minor true exists on this
        estate, otherwise the confirm fails with
        ERR_NO_MINOR_BENEFICIARY."

        Claim: GUARDIAN confirm with no is_minor=true Beneficiary ->
        ERR_NO_MINOR_BENEFICIARY.
        """
        estate, _, _ = create_estate_with_executor(
            bond_amount_cents=25_000,
        )
        guard = nominate_fiduciary(estate["id"], scope_type="GUARDIAN")
        resp = api_client.transition_fiduciary(
            estate["id"], guard["id"],
            fiduciary_state_payload("CONFIRMED"),
            TEST_USERS["court_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_MINOR_BENEFICIARY.value)


class TestExecutorResign:

    def test_resign_executor_without_successor_in_probate_rejected(
        self, api,
    ):
        """PRD §3.1: "A confirmed EXECUTOR cannot resign mid-probate
        without leaving a successor in the chair: while the estate's
        admin_phase is in IN_PROBATE, INVENTORIED, or DISTRIBUTING,
        an attempt by the EXECUTOR to transition from CONFIRMED to
        RESIGNED is rejected with ERR_NO_SUCCESSOR unless another
        Fiduciary with scope_type EXECUTOR is already NOMINATED on
        the same estate."

        Claim: confirmed EXECUTOR resigning while estate is in
        IN_PROBATE with no successor -> ERR_NO_SUCCESSOR.
        """
        bundle = setup_in_probate()
        estate = bundle["estate"]
        executor = bundle["executor"]
        # The Fiduciary's "self-only" RESIGNED transition compares
        # X-User-ID against Fiduciary.contact_user_id (PRD §2.1).
        # We use make_fiduciary_headers with the executor's
        # contact_user_id. The Fiduciary role is permitted for
        # the state endpoint per §1.7.
        resign_headers = make_fiduciary_headers(
            executor["contact_user_id"],
        )
        resp = api_client.transition_fiduciary(
            estate["id"], executor["id"],
            fiduciary_state_payload("RESIGNED"),
            resign_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_SUCCESSOR.value)

    def test_resign_executor_in_draft_allowed(self, api):
        """PRD §3.1: "Outside that band — for example while the
        estate is still in DRAFT — an executor may resign without a
        successor."

        Claim: confirmed EXECUTOR resigning while estate is DRAFT
        succeeds with no NOMINATED successor.
        """
        estate, executor, _ = create_estate_with_executor(
            bond_amount_cents=25_000,
        )
        executor = confirm_fiduciary(estate["id"], executor["id"])
        resign_headers = make_fiduciary_headers(
            executor["contact_user_id"],
        )
        resp = api_client.transition_fiduciary(
            estate["id"], executor["id"],
            fiduciary_state_payload("RESIGNED"),
            resign_headers,
        )
        updated = validate_success(resp)
        assert updated["status"] == "RESIGNED"


class TestFiduciaryRemove:

    def test_remove_nominated_fiduciary_by_clerk(self, api):
        """PRD §3.1: "A NOMINATED fiduciary may also be removed
        outright by the clerk".

        Claim: clerk transitions NOMINATED -> REMOVED.
        """
        estate, _, _ = create_estate_with_executor()
        f = nominate_fiduciary(estate["id"], scope_type="TRUSTEE")
        resp = api_client.transition_fiduciary(
            estate["id"], f["id"],
            fiduciary_state_payload("REMOVED"),
            TEST_USERS["court_clerk_headers"],
        )
        updated = validate_success(resp)
        assert updated["status"] == "REMOVED"

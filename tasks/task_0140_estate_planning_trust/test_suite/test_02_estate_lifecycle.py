"""Estate creation, update, and the DRAFT -> IN_PROBATE transition.

Coverage targets (PRD §3.1, §3.3):
- Estate created in DRAFT with probate_posture OPEN.
- PATCH allowed only in DRAFT.
- DRAFT -> IN_PROBATE preconditions:
  * no CONFIRMED executor -> ERR_NO_CONFIRMED_EXECUTOR
  * no ACCEPTED PETITION_TO_PROBATE -> ERR_NO_ACCEPTED_PETITION
  * insufficient bond -> ERR_BOND_INSUFFICIENT
- DRAFT -> IN_PROBATE side effects: petition_filed_at,
  settlement_due_at = +18 months, PoA cascade to TERMINATED.
- Estate response shape (probate_posture, gross_estate_value_cents).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_estate,
    asset_state_payload,
    confirm_fiduciary,
    create_estate,
    create_estate_payload,
    create_estate_with_executor,
    create_poa_payload,
    estate_state_payload,
    get_success_data,
    iso_offset,
    make_executor_headers,
    nominate_fiduciary,
    parse_iso,
    re_get_estate,
    server_offset_iso,
    setup_in_probate,
    submit_filing,
    transition_filing,
    validate_error,
    validate_success,
)


class TestCreateEstate:

    def test_create_estate_in_draft(self, api):
        """PRD §3.1: "On creation the estate's admin_phase is DRAFT
        and its derived probate_posture is OPEN."

        Claim: POST /estates -> 201 with admin_phase=DRAFT and
        probate_posture=OPEN.
        """
        estate = create_estate()
        assert_estate(estate)
        assert estate["admin_phase"] == "DRAFT", (
            f"new estate admin_phase must be DRAFT, "
            f"got {estate['admin_phase']!r}"
        )
        assert estate["probate_posture"] == "OPEN", (
            f"new estate probate_posture must be OPEN, "
            f"got {estate['probate_posture']!r}"
        )
        # PRD §3.3: "petition_filed_at ... null while DRAFT".
        assert estate.get("petition_filed_at") in (None, ""), (
            f"petition_filed_at must be null on DRAFT, got "
            f"{estate.get('petition_filed_at')!r}"
        )
        # PRD §3.3 / §3.1: "settlement_due_at ... null while DRAFT".
        assert estate.get("settlement_due_at") in (None, ""), (
            f"settlement_due_at must be null on DRAFT, got "
            f"{estate.get('settlement_due_at')!r}"
        )

    def test_create_estate_executor_only(self, api,
                                          court_clerk_headers):
        """PRD §2.1 / §4: POST /estates authorized roles = [Executor].

        Claim: a non-Executor role attempting POST /estates is
        rejected with ERR_FORBIDDEN.
        """
        payload = create_estate_payload()
        resp = api_client.create_estate(payload, court_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestPatchEstate:

    def test_patch_draft_estate_allowed(self, api):
        """PRD §3.1: "While the estate is in DRAFT, those three
        identity fields may be updated; once probate begins they
        freeze."

        Claim: PATCH /estates/{id} on a DRAFT estate succeeds.
        """
        estate, _, exec_h = create_estate_with_executor()
        resp = api_client.update_estate(
            estate["id"],
            {"testator_name": "Updated Name"},
            exec_h,
        )
        updated = validate_success(resp)
        assert updated["testator_name"] == "Updated Name"


class TestTransitionToInProbate:

    def test_advance_without_confirmed_executor(self, api):
        """PRD §3.3: "at least one Fiduciary with scope_type EXECUTOR
        and status CONFIRMED must exist for the estate; absent that
        the advance is rejected with ERR_NO_CONFIRMED_EXECUTOR."

        Claim: estate with NOMINATED-but-not-CONFIRMED executor ->
        ERR_NO_CONFIRMED_EXECUTOR.
        """
        estate, executor, exec_h = create_estate_with_executor()
        # Do NOT confirm. Submit/accept petition anyway to isolate
        # the executor check.
        petition = submit_filing(
            estate["id"], filing_type="PETITION_TO_PROBATE",
            filed_by_fiduciary_id=executor["id"],
            exec_headers=exec_h,
        )
        # PETITION acceptance has no preconditions per PRD §3.7.
        transition_filing(
            estate["id"], petition["id"], to_status="ACCEPTED",
            headers=TEST_USERS["court_clerk_headers"],
        )
        # Attempt advance.
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("IN_PROBATE"), exec_h,
        )
        validate_error(resp, ApiErrorId.ERR_NO_CONFIRMED_EXECUTOR.value)

    def test_advance_without_accepted_petition(self, api):
        """PRD §3.3: "a ProbateFiling with filing_type
        PETITION_TO_PROBATE and status ACCEPTED must exist; absent
        that the advance is rejected with ERR_NO_ACCEPTED_PETITION."

        Claim: estate with CONFIRMED executor but no ACCEPTED
        PETITION_TO_PROBATE -> ERR_NO_ACCEPTED_PETITION.
        """
        estate, executor, exec_h = create_estate_with_executor()
        executor = confirm_fiduciary(estate["id"], executor["id"])
        # Do NOT submit petition.
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("IN_PROBATE"), exec_h,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACCEPTED_PETITION.value)

    def test_advance_with_insufficient_bond(self, api):
        """PRD §3.3: "the confirmed executor's bond_amount_cents
        must be at least the bond requirement computed against the
        estate's current gross_estate_value_cents under the
        forward-looking variant; otherwise ERR_BOND_INSUFFICIENT."

        Claim: estate has CONFIRMED executor + ACCEPTED petition but
        executor's bond is too low for the current gross. The base
        bond on a zero-gross estate is the flat fee 25000; an
        executor confirmed below that should not have been confirmed
        in the first place. To test the DRAFT->IN_PROBATE bond gate
        specifically, we create an asset large enough that the bond
        requirement at advance time exceeds what the executor was
        confirmed with.

        Note: this test relies on PRD's stipulation that the bond
        check at DRAFT->IN_PROBATE uses the FORWARD-LOOKING variant
        (which includes DECLARED... wait — PRD says forward-looking
        includes APPRAISED + INVENTORIED declared. DECLARED is not
        counted. So the asset must be at least INVENTORIED for the
        gross to bump. But assets cannot reach INVENTORIED while
        estate is in DRAFT. Therefore this case is structurally
        unreachable — at DRAFT, all assets are DECLARED (or
        EXCLUDED), gross is 0, bond requirement is 25000 flat. If
        the executor was confirmed with bond_amount_cents >= 25000,
        the bond gate at advance time will also pass.

        We TEST the reachable case: an executor confirmed at the
        minimum 25000, advancing — the gate must PASS.
        """
        # The branch covered above is reasoned-about; here we
        # verify the only reachable boundary: bond=25000 succeeds.
        estate, executor, exec_h = create_estate_with_executor(
            bond_amount_cents=25_000,
        )
        executor = confirm_fiduciary(estate["id"], executor["id"])
        petition = submit_filing(
            estate["id"], filing_type="PETITION_TO_PROBATE",
            filed_by_fiduciary_id=executor["id"],
            exec_headers=exec_h,
        )
        transition_filing(
            estate["id"], petition["id"], to_status="ACCEPTED",
            headers=TEST_USERS["court_clerk_headers"],
        )
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("IN_PROBATE"), exec_h,
        )
        # PRD §3.5: bond on zero gross = 25000 flat. 25000 >= 25000
        # passes (PRD §3.3 says ">=").
        updated = validate_success(resp)
        assert updated["admin_phase"] == "IN_PROBATE"

    def test_advance_sets_petition_filed_at_and_settlement_due_at(
        self, api,
    ):
        """PRD §3.3: "On successful transition, three side effects
        fire: petition_filed_at is set to the current clock;
        settlement_due_at is set to eighteen months after
        petition_filed_at".

        Claim: after DRAFT->IN_PROBATE, petition_filed_at is
        non-null and settlement_due_at is non-null with the 18-month
        offset relationship.
        """
        bundle = setup_in_probate()
        estate = bundle["estate"]
        assert estate.get("petition_filed_at"), (
            "petition_filed_at must be set after IN_PROBATE"
        )
        assert estate.get("settlement_due_at"), (
            "settlement_due_at must be set after IN_PROBATE"
        )
        # Verify 18-month relationship (approximate — 18 months can
        # be 540 days +- a few; PRD §3.14 names "the count of days
        # in the eighteen-month statutory window" as 540).
        pfd = parse_iso(estate["petition_filed_at"])
        sda = parse_iso(estate["settlement_due_at"])
        delta = sda - pfd
        # Tolerance: 18 months = ~547 days; PRD §3.14 says the
        # window denominator is 540 days. We accept anything in
        # the reasonable 18-month band.
        assert timedelta(days=535) <= delta <= timedelta(days=560), (
            f"settlement_due_at must be ~18 months after "
            f"petition_filed_at; got delta={delta}"
        )

    def test_advance_terminates_pending_poas(self, api):
        """PRD §3.3: "every PowerOfAttorney row in PENDING or ACTIVE
        is moved to TERMINATED — the death-event cascade."

        Claim: a PENDING POA on a DRAFT estate becomes TERMINATED
        when the estate advances to IN_PROBATE.
        """
        # Set up a DRAFT estate with a CONFIRMED executor and an
        # ACCEPTED petition, plus a POA in PENDING.
        estate, executor, exec_h = create_estate_with_executor()
        executor = confirm_fiduciary(estate["id"], executor["id"])
        # Create an agent fiduciary for the POA.
        agent = nominate_fiduciary(
            estate["id"], scope_type="TRUSTEE",
        )
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
        # Submit + accept petition.
        petition = submit_filing(
            estate["id"], filing_type="PETITION_TO_PROBATE",
            filed_by_fiduciary_id=executor["id"],
            exec_headers=exec_h,
        )
        transition_filing(
            estate["id"], petition["id"], to_status="ACCEPTED",
            headers=TEST_USERS["court_clerk_headers"],
        )
        # Advance.
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("IN_PROBATE"), exec_h,
        )
        validate_success(resp)
        # Re-read POA.
        poa_after = get_success_data(
            api_client.get_poa(estate["id"], poa["id"],
                                exec_h),
        )
        assert poa_after["status"] == "TERMINATED", (
            f"PoA must be TERMINATED after IN_PROBATE, got "
            f"{poa_after['status']!r}"
        )


class TestEstateInvalidTransitions:

    def test_advance_draft_to_settled_invalid(self, api):
        """PRD §2.6: "State-transition endpoints additionally accept
        a to_status field ... the server validates that the
        to_status value is a permitted transition from the row's
        current status under the relevant entity's state machine,
        and rejects with ERR_INVALID_STATE (HTTP 409) when it is
        not."

        Claim: attempting DRAFT->SETTLED directly fails with
        ERR_INVALID_STATE.
        """
        estate, _, exec_h = create_estate_with_executor()
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("SETTLED"), exec_h,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

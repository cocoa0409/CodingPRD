"""Suspension, reinstatement, the termination cascade and the transfer handoff."""

from test_helpers import (
    ApiErrorId,
    assert_appointment_status,
    assert_contains_id,
    assert_posture,
    assert_total_count,
    assert_version_bumped_by,
    audit_findings,
    balance_snapshot_payload,
    clear_finding,
    create_agency,
    create_audit,
    create_escrow_account,
    create_escrow_audit_payload,
    create_policy_file,
    factories,
    issue_policy,
    onboard_agency,
    post_snapshot,
    read_agency,
    reinstate_agency,
    request_letter,
    submit_audit,
    submit_remediation,
    suspend_agency,
    terminate_agency,
    transition_transfer,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, AUDITOR, OFFICER


class TestSuspensionFanOut:
    """One suspension decision writes the agency, its posture and its accounts."""

    def test_suspension_freezes_the_posture_and_restricts_every_open_account(
        self, api, env
    ):
        """Two `OPEN` accounts both become `RESTRICTED` on a single versioned mutation.

        PRD: "Moving `APPOINTED` to `SUSPENDED` requires nothing beyond the decision
        itself, and its effects fan out: because `SUSPENDED` is one of the two freeze
        conditions, `oversight_posture` becomes `FROZEN`, and because the posture became
        `FROZEN`, every escrow account belonging to the agency whose `status` is `OPEN`
        moves to `RESTRICTED`. `Agency.version` is incremented by 1."

        Design: Corner/state_machines/side_effect_execution_suspension_restricts_accounts_and_freezes_posture
        """
        first = create_escrow_account(api, env)
        second = create_escrow_account(api, env)
        before = read_agency(api, env.agency_id)
        assert_posture(before, "OPEN")
        assert_appointment_status(before, "APPOINTED")

        suspended = suspend_agency(
            api, env.agency_id, reason="Escrow examination opened"
        )

        assert_appointment_status(suspended, "SUSPENDED")
        assert_posture(suspended, "FROZEN")
        assert_version_bumped_by(before, suspended, 1, "agency")

        rows, meta = validate_paginated(
            api.list_escrow_accounts(
                OFFICER, params={"agency_id": env.agency_id, "status": "RESTRICTED"}
            )
        )
        assert_total_count(meta, 2)
        assert_contains_id(rows, first["id"], "the restricted account list")
        assert_contains_id(rows, second["id"], "the restricted account list")
        for account in (first, second):
            reread = validate_success(api.get_escrow_account(account["id"], OFFICER))
            assert reread["status"] == "RESTRICTED", (
                f"account {reread['account_ref']} must be RESTRICTED, got "
                f"{reread['status']}"
            )


class TestReinstatementCycle:
    """The appointment dimension loops back and undoes the account restriction."""

    def test_reinstatement_returns_the_agency_and_the_account_to_their_open_state(
        self, api, env
    ):
        """After a suspend-and-reinstate round trip nothing is left restricted.

        PRD: "When reinstatement succeeds, the posture is recomputed; because it has left
        `FROZEN`, every escrow account of the agency whose `status` is `RESTRICTED` moves
        back to `OPEN`, and `Agency.version` is incremented by 1. The suspend-and-reinstate
        cycle may run any number of times."

        Design: Corner/state_machines/cyclic_agency_reinstatement_returns_to_appointed_and_reopens_accounts
        """
        account = create_escrow_account(api, env)
        suspended = suspend_agency(
            api, env.agency_id, reason="Escrow examination opened"
        )
        assert_posture(suspended, "FROZEN")
        restricted = validate_success(api.get_escrow_account(account["id"], OFFICER))
        assert restricted["status"] == "RESTRICTED", (
            f"the suspension must restrict the account, got {restricted['status']}"
        )

        reinstated = reinstate_agency(
            api, env.agency_id, reason="Examination closed with no exceptions"
        )

        assert_appointment_status(reinstated, "APPOINTED")
        assert_posture(reinstated, "OPEN")
        assert_version_bumped_by(suspended, reinstated, 1, "agency")
        reopened = validate_success(api.get_escrow_account(account["id"], OFFICER))
        assert reopened["status"] == "OPEN", (
            f"the restricted account must be reopened, got {reopened['status']}"
        )
        appointment = validate_success(
            api.get_appointment(env.appointment_id, OFFICER)
        )
        assert appointment["status"] == "ACTIVE", (
            "the appointment row is untouched by the suspend-and-reinstate loop, got "
            f"{appointment['status']}"
        )


class TestReinstatementGuard:
    """Reinstatement is guarded by escrow risk held on other entities."""

    def test_an_open_critical_finding_blocks_reinstatement_until_it_is_cleared(
        self, api, env
    ):
        """The identical `REINSTATE` call is a 409, then a 200 once the finding clears.

        PRD: "Reinstatement — `SUSPENDED` back to `APPOINTED` — is the guarded direction,
        and it is guarded by escrow risk rather than by licensing: the agency's
        `escrow_standing` must not be `DEFALCATION_RISK` and its
        `open_critical_finding_count` must be exactly 0. Either condition failing produces
        `ERR_REINSTATEMENT_BLOCKED_BY_ESCROW_STANDING` (HTTP 409)."

        Design: Corner/state_machines/guarded_transitions_reinstatement_blocked_by_open_critical_finding_returns_409
        """
        account = create_escrow_account(api, env)
        post_snapshot(api, env, account["id"], trial_balance_cents=4_000_000)
        audit = create_audit(api, env, account["id"])
        submit_audit(api, audit["id"])
        finding = audit_findings(api, audit["id"])[0]
        assert finding["severity"] == "CRITICAL", (
            f"a 6,000,000 variance exposure is CRITICAL, got {finding['severity']}"
        )
        before_suspension = read_agency(api, env.agency_id)
        assert before_suspension["open_critical_finding_count"] == 1, (
            "the uncleared critical finding must be counted on the agency, got "
            f"{before_suspension['open_critical_finding_count']}"
        )
        suspend_agency(api, env.agency_id, reason="Escrow examination opened")

        blocked = api.decide_appointment(
            env.agency_id,
            factories.appointment_decision_payload(
                "REINSTATE", reason="Premature reinstatement attempt"
            ),
            ANALYST,
        )

        validate_error(
            blocked,
            ApiErrorId.ERR_REINSTATEMENT_BLOCKED_BY_ESCROW_STANDING.value,
            409,
        )
        still_suspended = read_agency(api, env.agency_id)
        assert_appointment_status(still_suspended, "SUSPENDED")
        assert_posture(still_suspended, "FROZEN")

        submit_remediation(
            api,
            env,
            finding["id"],
            remediation_note="Shortfall funded",
            cleared_amount_cents=6_000_000,
        )
        clear_finding(
            api,
            finding["id"],
            cleared_amount_cents=6_000_000,
            disposition_note="Funding verified",
        )
        after_clearing = read_agency(api, env.agency_id)
        assert after_clearing["open_critical_finding_count"] == 0, (
            "clearing the finding must empty the critical counter, got "
            f"{after_clearing['open_critical_finding_count']}"
        )

        reinstated = reinstate_agency(
            api, env.agency_id, reason="Finding cleared"
        )

        assert_appointment_status(reinstated, "APPOINTED")
        assert_posture(reinstated, "OPEN")


class TestTerminationCascade:
    """CASCADE-B walks from the agency down to every dependent row in one request."""

    def test_termination_withdraws_declines_voids_and_closes_in_one_request(
        self, api, env
    ):
        """The appointment, the letter, the pending file and the account all move.

        PRD: "Hop 3 also fires from hop 1: every appointment of the agency whose `status`
        is `PENDING_LICENSE_VERIFICATION`, `ACTIVE` or `LAPSED` moves to `WITHDRAWN`,
        processed in ascending `created_at` order. Hop 4 fires because those appointments
        were withdrawn: every closing protection letter of the agency whose `status` is
        `REQUESTED` or `REFERRED` and whose `state_program_id` matches a withdrawn
        appointment's `state_program_id` moves to `DECLINED` with `decided_by_user_id` set
        to `SYSTEM`, again in ascending `created_at` order. Hop 5 fires because those
        letters were declined: every policy file whose `cpl_id` is one of them and whose
        `issuance_status` is `PENDING` or `PENDING_REFERRAL` moves to `VOIDED`."

        Design: Corner/state_machines/cascade_down_termination_withdraws_appointments_declines_letters_and_voids_pending_files
        """
        account = create_escrow_account(api, env)
        letter = request_letter(api, env, requested_coverage_cents=30_000_000)
        assert letter["status"] == "REQUESTED", (
            f"the letter must be outstanding at REQUESTED, got {letter['status']}"
        )
        issued_file = create_policy_file(
            api,
            env,
            closing_date="2026-07-20",
            liability_amount_cents=40_000_000,
            gross_premium_cents=500_000,
        )
        issue_policy(api, env, issued_file["id"], policy_number="POL-521")
        pending_file = create_policy_file(
            api,
            env,
            cpl_id=letter["id"],
            closing_date="2026-07-25",
            liability_amount_cents=40_000_000,
            gross_premium_cents=500_000,
        )
        assert pending_file["issuance_status"] == "PENDING", (
            "the second file must be waiting at PENDING before the cascade, got "
            f"{pending_file['issuance_status']}"
        )

        terminated = terminate_agency(
            api, env.agency_id, termination_reason="VOLUNTARY"
        )

        assert_appointment_status(terminated, "TERMINATED")
        assert_posture(terminated, "FROZEN")
        assert terminated["pending_transfer_count"] == 1, (
            "only the in-force file awaits transfer, got "
            f"{terminated['pending_transfer_count']}"
        )
        appointment = validate_success(
            api.get_appointment(env.appointment_id, OFFICER)
        )
        assert appointment["status"] == "WITHDRAWN", (
            f"hop 3 must withdraw the active appointment, got {appointment['status']}"
        )
        declined = validate_success(api.get_letter(letter["id"], OFFICER))
        assert declined["status"] == "DECLINED", (
            f"hop 4 must decline the outstanding letter, got {declined['status']}"
        )
        assert declined["decided_by_user_id"] == "SYSTEM", (
            "the cascade decides the letter, so the decider must be SYSTEM, got "
            f"{declined['decided_by_user_id']!r}"
        )
        voided = validate_success(api.get_policy_file(pending_file["id"], OFFICER))
        assert voided["issuance_status"] == "VOIDED", (
            "hop 5 must void the pending file citing the declined letter, got "
            f"{voided['issuance_status']}"
        )
        in_force = validate_success(api.get_policy_file(issued_file["id"], OFFICER))
        assert in_force["issuance_status"] == "ISSUED", (
            "an already-issued file is never voided by the cascade, got "
            f"{in_force['issuance_status']}"
        )
        assert in_force["transfer_status"] == "PENDING_TRANSFER", (
            "the issued file moves on its transfer dimension instead, got "
            f"{in_force['transfer_status']}"
        )
        closed_account = validate_success(
            api.get_escrow_account(account["id"], OFFICER)
        )
        assert closed_account["status"] == "CLOSED", (
            f"the open trust account must be CLOSED, got {closed_account['status']}"
        )


class TestTransferCompletion:
    """The handoff finishes on its own endpoint and clears the terminated ledger."""

    def test_completing_the_transfer_moves_only_the_transfer_dimension(self, api, env):
        """`PENDING_TRANSFER` to `TRANSFERRED` empties `pending_transfer_count`.

        PRD: "Completing a transfer — `PENDING_TRANSFER` to `TRANSFERRED` — requires the
        file's own `transferee_agency_id` to be non-null and that transferee agency to have
        an `appointment_status` of `APPOINTED` and an `oversight_posture` other than
        `FROZEN`, either failing being `ERR_TRANSFEREE_NOT_ELIGIBLE`; the eligibility is
        therefore re-tested at the moment of transfer, not merely at termination, so a
        transferee that has itself been frozen in the interim blocks the move. On success
        the terminated agency's `pending_transfer_count` is recomputed."

        Design: Corner/endpoints/action_endpoint_transfer_state_completes_a_terminated_agency_file_handoff
        """
        transferee_env = onboard_agency(api, state_program=env.state_program)
        transferee = read_agency(api, transferee_env.agency_id)
        assert_appointment_status(transferee, "APPOINTED")
        assert_posture(transferee, "OPEN")
        policy_file = create_policy_file(
            api,
            env,
            closing_date="2026-07-20",
            liability_amount_cents=40_000_000,
            gross_premium_cents=400_000,
        )
        issue_policy(api, env, policy_file["id"], policy_number="POL-601")

        terminated = terminate_agency(
            api,
            env.agency_id,
            termination_reason="NON_RENEWAL",
            transferee_agency_id=transferee_env.agency_id,
        )
        assert terminated["pending_transfer_count"] == 1, (
            "the in-force file must be counted as awaiting transfer, got "
            f"{terminated['pending_transfer_count']}"
        )
        assert terminated["transferee_agency_id"] == transferee_env.agency_id, (
            "the named transferee must be persisted on the agency, got "
            f"{terminated['transferee_agency_id']}"
        )
        parked = validate_success(api.get_policy_file(policy_file["id"], OFFICER))
        assert parked["transfer_status"] == "PENDING_TRANSFER", (
            f"the file must await transfer, got {parked['transfer_status']}"
        )
        assert parked["transferee_agency_id"] == transferee_env.agency_id, (
            "the transferee is copied down onto the file, got "
            f"{parked['transferee_agency_id']}"
        )

        transferred = transition_transfer(
            api,
            policy_file["id"],
            "TRANSFERRED",
            note="File delivered to Cascade Title",
        )

        assert transferred["transfer_status"] == "TRANSFERRED", (
            f"the transfer dimension must reach TRANSFERRED, got {transferred['transfer_status']}"
        )
        assert transferred["issuance_status"] == "ISSUED", (
            "the issuance dimension must not move with the transfer, got "
            f"{transferred['issuance_status']}"
        )
        after = read_agency(api, env.agency_id)
        assert after["pending_transfer_count"] == 0, (
            "the completed handoff empties the counter, got "
            f"{after['pending_transfer_count']}"
        )
        rows, meta = validate_paginated(
            api.list_policy_files(
                OFFICER, params={"transferee_agency_id": transferee_env.agency_id}
            )
        )
        assert_total_count(meta, 1)
        assert_contains_id(rows, policy_file["id"], "the transferee's file list")


class TestTerminationEligibilityAndClosedAccounts:
    """An ineligible recipient is refused, and a closed account accepts nothing."""

    def test_a_pending_review_agency_and_the_agency_itself_are_both_ineligible(
        self, api, env
    ):
        """Neither an unappointed recipient nor a self-reference may receive the book.

        PRD: "A `transferee_agency_id` is optional, but when one is supplied it must
        resolve to an existing agency — a missing reference is `ERR_AGENCY_NOT_FOUND` —
        that agency's `appointment_status` must be `APPOINTED`, its `oversight_posture`
        must not be `FROZEN`, and it must not be the terminated agency itself, any of which
        failing is `ERR_TRANSFEREE_NOT_ELIGIBLE` (HTTP 422)."

        Design: Corner/errors/terminated_agency_rejects_ineligible_transferee_and_closes_its_accounts_returns_422
        """
        account = create_escrow_account(api, env)
        unappointed = create_agency(api)
        assert unappointed["appointment_status"] == "PENDING_REVIEW", (
            "a freshly registered agency is PENDING_REVIEW, got "
            f"{unappointed['appointment_status']}"
        )

        to_unappointed = api.decide_appointment(
            env.agency_id,
            factories.appointment_decision_payload(
                "TERMINATE",
                termination_reason="VOLUNTARY",
                transferee_agency_id=unappointed["id"],
            ),
            OFFICER,
        )
        validate_error(
            to_unappointed, ApiErrorId.ERR_TRANSFEREE_NOT_ELIGIBLE.value, 422
        )

        to_itself = api.decide_appointment(
            env.agency_id,
            factories.appointment_decision_payload(
                "TERMINATE",
                termination_reason="VOLUNTARY",
                transferee_agency_id=env.agency_id,
            ),
            OFFICER,
        )
        validate_error(to_itself, ApiErrorId.ERR_TRANSFEREE_NOT_ELIGIBLE.value, 422)

        untouched = read_agency(api, env.agency_id)
        assert_appointment_status(untouched, "APPOINTED")
        assert_posture(untouched, "OPEN")
        assert untouched["transferee_agency_id"] is None, (
            "a refused termination persists no transferee, got "
            f"{untouched['transferee_agency_id']!r}"
        )
        still_open = validate_success(api.get_escrow_account(account["id"], OFFICER))
        assert still_open["status"] == "OPEN", (
            f"the account must survive the refused terminations, got {still_open['status']}"
        )

    def test_a_closed_account_refuses_further_balance_snapshots(self, api, env):
        """The same snapshot that was accepted while `OPEN` is a 409 after closure.

        PRD: "Snapshots are refused against an account whose `status` is `CLOSED`, with
        `ERR_ESCROW_ACCOUNT_CLOSED` (HTTP 409), but they are perfectly acceptable while the
        account is `RESTRICTED` — restriction gates coverage, not bookkeeping."

        Design: Corner/errors/terminated_agency_rejects_ineligible_transferee_and_closes_its_accounts_returns_422
        """
        account = create_escrow_account(api, env)
        post_snapshot(api, env, account["id"])

        terminated = terminate_agency(
            api, env.agency_id, termination_reason="VOLUNTARY"
        )

        assert_appointment_status(terminated, "TERMINATED")
        assert_posture(terminated, "FROZEN")
        closed = validate_success(api.get_escrow_account(account["id"], OFFICER))
        assert closed["status"] == "CLOSED", (
            f"the terminated agency's account must be CLOSED, got {closed['status']}"
        )

        refused = api.post_balance_snapshot(
            account["id"],
            balance_snapshot_payload(snapshot_as_of="2026-08-01"),
            env.principal,
        )

        validate_error(refused, ApiErrorId.ERR_ESCROW_ACCOUNT_CLOSED.value, 409)
        _rows, meta = validate_paginated(
            api.list_escrow_accounts(
                OFFICER, params={"agency_id": env.agency_id, "status": "CLOSED"}
            )
        )
        assert_total_count(meta, 1)

    def test_a_closed_account_cannot_be_the_target_of_a_new_audit(self, api, env):
        """Opening any audit against the closed trust account is refused.

        PRD: "The target account must not be `CLOSED`, else `ERR_ESCROW_ACCOUNT_CLOSED`."

        Design: Corner/errors/terminated_agency_rejects_ineligible_transferee_and_closes_its_accounts_returns_422
        """
        account = create_escrow_account(api, env)
        post_snapshot(api, env, account["id"])
        terminate_agency(api, env.agency_id, termination_reason="VOLUNTARY")
        closed = validate_success(api.get_escrow_account(account["id"], OFFICER))
        assert closed["status"] == "CLOSED", (
            f"the account must be CLOSED before the attempt, got {closed['status']}"
        )

        refused = api.create_escrow_audit(
            create_escrow_audit_payload(
                env.agency_id,
                account["id"],
                audit_type="SURPRISE",
                as_of_date="2026-08-01",
            ),
            AUDITOR,
        )

        validate_error(refused, ApiErrorId.ERR_ESCROW_ACCOUNT_CLOSED.value, 409)
        _rows, meta = validate_paginated(
            api.list_escrow_audits(
                AUDITOR, params={"escrow_account_id": account["id"]}
            )
        )
        assert_total_count(meta, 0)

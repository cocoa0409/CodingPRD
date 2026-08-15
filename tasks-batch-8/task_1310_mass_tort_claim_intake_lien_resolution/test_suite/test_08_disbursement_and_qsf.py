"""Disbursement waterfall, QSF ledger conservation, segregation of duties,
release cascade, and terminal-state lockdown."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_disbursement_conservation,
    create_program, create_ready_for_disbursement_claim, create_disbursed_claim,
    create_liens_resolved_claim, create_claim_in_liens_pending,
    add_lien_in_state, get_claim_version,
    make_disbursement_approver_headers,
    waive_lien_payload,
    PREPARE_USER_ID, APPROVER_USER_ID,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
LIEN_HEADERS = TEST_USERS["lien_analyst_headers"]


class TestWaterfallAllocation:
    def test_buckets_created_in_order_lien_attorney_claimant(self, api):
        """PRD §3.7: "The waterfall pays in a fixed order, and the order matters because the final bucket is the residual. First come the lien holders: one disbursement per distinct `holder_name` among the claim's `RESOLVED` liens, holders ordered by the earliest `created_at` among that holder's liens ascending, each with `payee_role` of `LIEN_HOLDER`, the holder's name as `payee_name`, and `amount_cents` equal to the sum of that holder's `final_demand_cents`. Second comes counsel: when `represented_by_counsel` is true, a disbursement with `payee_role` of `ATTORNEY`, `payee_name` of "Counsel of Record", and `amount_cents` equal to `attorney_fee_cents`. Last comes the claimant: a disbursement with `payee_role` of `CLAIMANT`, the claimant's `full_name` as `payee_name`, and `amount_cents` equal to whatever remains after the first two buckets — so the sum of all disbursement amounts for a claim always equals `net_award_cents` exactly."

        Design: Corner/calculations/waterfall_allocation_buckets_in_order
        """
        ctx = create_ready_for_disbursement_claim(
            base_award_cents=10_000_000, represented_by_counsel=True, severities=(70, 65),
            lien_action="resolve", resolve_final_demand_cents=1_000_000,
            lien_type="MEDICARE", holder_name="CMS", asserted_amount_cents=1_000_000,
        )
        ds = ctx["disbursements"]
        assert len(ds) == 3, f"Expected 3 disbursements (lien holder, attorney, claimant), got {len(ds)}"
        assert ds[0]["payee_role"] == "LIEN_HOLDER" and ds[0]["amount_cents"] == 1_000_000
        assert ds[0]["payee_name"] == "CMS"
        assert ds[1]["payee_role"] == "ATTORNEY"
        assert ds[1]["payee_name"] == "Counsel of Record"
        assert ds[2]["payee_role"] == "CLAIMANT"
        assert ds[2]["payee_name"] == ctx["claimant"]["full_name"]

    def test_disbursement_amounts_sum_to_net_award(self, api):
        """PRD §3.7: "Last comes the claimant: a disbursement with `payee_role` of `CLAIMANT`, the claimant's `full_name` as `payee_name`, and `amount_cents` equal to whatever remains after the first two buckets — so the sum of all disbursement amounts for a claim always equals `net_award_cents` exactly."

        Design: Corner/calculations/waterfall_allocation_buckets_in_order
        """
        ctx = create_ready_for_disbursement_claim(
            base_award_cents=10_000_000, represented_by_counsel=True, severities=(70, 65),
            lien_action="resolve", resolve_final_demand_cents=1_000_000,
            lien_type="MEDICARE", holder_name="CMS", asserted_amount_cents=1_000_000,
        )
        claim = validate_success(api.get_claim(ctx["program"]["id"], ctx["claim"]["id"], ADMIN))
        assert_disbursement_conservation(ctx["disbursements"], claim["net_award_cents"])


class TestQsfConservation:
    def test_prepare_debits_and_void_refunds_qsf(self, api):
        """PRD §2.10: "Preparing disbursement decrements the remaining balance by the reserved amount; voiding a pending disbursement refunds that disbursement's `amount_cents` back into the remaining balance."

        Design: Difficulty/compensating_invariant/disbursement_void_refunds_qsf
        """
        ctx = create_ready_for_disbursement_claim(
            base_award_cents=5_000_000, represented_by_counsel=False, severities=(70, 65),
            lien_action="waive", lien_type="MEDICARE", holder_name="CMS",
            asserted_amount_cents=100_000, qsf_principal_cents=100_000_000,
        )
        pid = ctx["program"]["id"]
        program_after_prepare = validate_success(api.get_program(pid, ADMIN))
        assert program_after_prepare["qsf_remaining_cents"] == 95_000_000, (
            f"prepare must debit net_award 5000000 from principal 100000000, got {program_after_prepare['qsf_remaining_cents']}"
        )
        did = ctx["disbursements"][0]["id"]
        validate_success(api.void_disbursement(
            pid, ctx["claim"]["id"], did, make_disbursement_approver_headers(PREPARE_USER_ID)))
        program_after_void = validate_success(api.get_program(pid, ADMIN))
        assert program_after_void["qsf_remaining_cents"] == 100_000_000, (
            f"void must refund the reserved amount, got {program_after_void['qsf_remaining_cents']}"
        )

    def test_qsf_reservation_equals_net_award(self, api):
        """PRD §3.7: "On success, `qsf_reservation_cents` is set equal to `net_award_cents` at reservation time, the program's `qsf_remaining_cents` is decremented by that amount, and the allocation waterfall spawns the claim's `Disbursement` rows, all in `PENDING` state — always one for the claimant, plus one for the attorney when the claimant is represented, plus one per lien-holder bucket grouped by payee."

        Design: Difficulty/compensating_invariant/disbursement_void_refunds_qsf
        """
        ctx = create_ready_for_disbursement_claim(
            base_award_cents=5_000_000, represented_by_counsel=False, severities=(70, 65),
            lien_action="waive", lien_type="MEDICARE", holder_name="CMS",
            asserted_amount_cents=100_000,
        )
        claim = validate_success(api.get_claim(ctx["program"]["id"], ctx["claim"]["id"], ADMIN))
        assert claim["status"] == "READY_FOR_DISBURSEMENT"
        assert claim["qsf_reservation_cents"] == claim["net_award_cents"] == 5_000_000
        for d in ctx["disbursements"]:
            assert d["state"] == "PENDING", f"Newly spawned disbursements must be PENDING, got {d['state']}"


class TestSegregationOfDuties:
    def test_state_error_beats_self_approval_when_both_apply(self, api):
        """PRD §2.9: "Only then does the endpoint's business logic run: the required from-state check (`ERR_CLAIM_INVALID_STATE`, `ERR_LIEN_INVALID_STATE`, `ERR_APPEAL_INVALID_STATE`, or `ERR_DISBURSEMENT_INVALID_STATE`), followed by segregation of duties on disbursement approval (`ERR_SELF_APPROVAL_FORBIDDEN`), matrix referential checks (`ERR_MATRIX_NOT_PUBLISHED`, `ERR_MATRIX_CATEGORY_MISMATCH`), severity range (`ERR_SEVERITY_OUT_OF_RANGE`), eligibility date order (`ERR_ELIGIBILITY_DATE_ORDER`), duplicate active claims (`ERR_DUPLICATE_ACTIVE_CLAIM`), medical-record sufficiency (`ERR_INSUFFICIENT_MEDICAL_RECORDS`, `ERR_NO_QUALIFYING_RECORD`), unresolved liens (`ERR_UNRESOLVED_LIENS_EXIST`), open appeals blocking finalization (`ERR_OPEN_APPEAL_BLOCKS_FINALIZE`), the holder response window (`ERR_HOLDER_WINDOW_OPEN`), negotiated demand caps (`ERR_FINAL_EXCEEDS_ASSERTED`), and finally the fiscal checks on disbursement preparation — fund sufficiency (`ERR_QSF_INSUFFICIENT_FUNDS`) and net-award non-negativity (`ERR_NEGATIVE_NET_AWARD`)."

        Design: Difficulty/priority_pair_validation_conflict/self_approval_beats_disbursement_state
        """
        ctx = create_ready_for_disbursement_claim(prepare_user_id=PREPARE_USER_ID)
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        did = ctx["disbursements"][0]["id"]
        # Another approver moves the disbursement to APPROVED.
        validate_success(api.approve_disbursement(
            pid, cid, did, make_disbursement_approver_headers(APPROVER_USER_ID)))
        # The prepare caller now attempts approval: both the from-state rule and
        # the segregation rule are violated. PRD §2.9 evaluates the from-state
        # check first ("followed by segregation of duties"), so the state error
        # is the one that surfaces.
        resp = api.approve_disbursement(pid, cid, did, make_disbursement_approver_headers(PREPARE_USER_ID))
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_INVALID_STATE)

    def test_self_approval_rejected_on_pending_disbursement(self, api):
        """PRD §2.10: "Disbursement approval is segregated from disbursement preparation: the `X-User-ID` approving a disbursement must differ from the `X-User-ID` that called prepare-disbursement on that claim, and a violation is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/self_approval_beats_disbursement_state
        """
        ctx = create_ready_for_disbursement_claim(prepare_user_id=PREPARE_USER_ID)
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        did = ctx["disbursements"][0]["id"]
        resp = api.approve_disbursement(pid, cid, did, make_disbursement_approver_headers(PREPARE_USER_ID))
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)


class TestQsfInsufficientFunds:
    def test_prepare_rejected_when_qsf_below_net_award(self, api):
        """PRD §3.7: "Preparation enforces two fiscal checks: the program's `qsf_remaining_cents` must be at least the claim's `net_award_cents`, otherwise `ERR_QSF_INSUFFICIENT_FUNDS` (HTTP 402); and `net_award_cents` itself must be at least zero, otherwise `ERR_NEGATIVE_NET_AWARD` (HTTP 422)."

        Design: Corner/validations/qsf_insufficient_blocks_prepare
        """
        ctx = create_liens_resolved_claim(
            base_award_cents=5_000_000, represented_by_counsel=False, severities=(70, 65),
            lien_action="waive", lien_type="MEDICARE", holder_name="CMS",
            asserted_amount_cents=100_000, qsf_principal_cents=1_000_000,
        )
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        resp = api.prepare_disbursement(pid, cid, make_disbursement_approver_headers(PREPARE_USER_ID))
        validate_error(resp, ApiErrorId.ERR_QSF_INSUFFICIENT_FUNDS)


class TestReleaseCascade:
    def test_release_stamps_clock_and_disburses_claim(self, api):
        """PRD §3.8: "Release moves it from `APPROVED` to `RELEASED` and stamps `released_at` with the program's `current_utc`; releasing also credits the QSF ledger, since `qsf_remaining_cents` counts only `RELEASED` outflows against principal."
        PRD §3.8: "The claim itself crosses from `READY_FOR_DISBURSEMENT` to `DISBURSED` automatically when the last of its sibling disbursements leaves the pending set — that is, when every disbursement on the claim is in `RELEASED` or `VOIDED`."

        Design: Difficulty/transitive_cascade/disbursement_release_cascade_depth2
        """
        ctx = create_ready_for_disbursement_claim(
            base_award_cents=5_000_000, represented_by_counsel=False, severities=(70, 65),
            lien_action="waive", lien_type="MEDICARE", holder_name="CMS",
            asserted_amount_cents=100_000,
        )
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        approver = make_disbursement_approver_headers(APPROVER_USER_ID)
        did = ctx["disbursements"][0]["id"]
        validate_success(api.approve_disbursement(pid, cid, did, approver))
        released = validate_success(api.release_disbursement(pid, cid, did, approver))
        assert released["state"] == "RELEASED"
        assert released["released_at"] == "2026-08-01T00:00:00Z", (
            f"released_at must be stamped from the program clock, got {released['released_at']}"
        )
        claim = validate_success(api.get_claim(pid, cid, ADMIN))
        assert claim["status"] == "DISBURSED", (
            f"last sibling release must cascade the claim to DISBURSED, got {claim['status']}"
        )

    def test_claim_stays_ready_until_last_sibling_leaves_pending(self, api):
        """PRD §3.8: "The claim itself crosses from `READY_FOR_DISBURSEMENT` to `DISBURSED` automatically when the last of its sibling disbursements leaves the pending set — that is, when every disbursement on the claim is in `RELEASED` or `VOIDED`."

        Design: Difficulty/transitive_cascade/disbursement_release_cascade_depth2
        """
        # Counsel represented -> two disbursements (ATTORNEY + CLAIMANT); releasing
        # only the first must NOT disburse the claim.
        ctx = create_ready_for_disbursement_claim(
            base_award_cents=5_000_000, represented_by_counsel=True, severities=(70, 65),
            lien_action="waive", lien_type="MEDICARE", holder_name="CMS",
            asserted_amount_cents=100_000,
        )
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        approver = make_disbursement_approver_headers(APPROVER_USER_ID)
        assert len(ctx["disbursements"]) == 2
        first = ctx["disbursements"][0]["id"]
        validate_success(api.approve_disbursement(pid, cid, first, approver))
        validate_success(api.release_disbursement(pid, cid, first, approver))
        claim_mid = validate_success(api.get_claim(pid, cid, ADMIN))
        assert claim_mid["status"] == "READY_FOR_DISBURSEMENT", (
            f"one sibling still PENDING; expected READY_FOR_DISBURSEMENT, got {claim_mid['status']}"
        )
        second = ctx["disbursements"][1]["id"]
        validate_success(api.approve_disbursement(pid, cid, second, approver))
        validate_success(api.release_disbursement(pid, cid, second, approver))
        claim_final = validate_success(api.get_claim(pid, cid, ADMIN))
        assert claim_final["status"] == "DISBURSED"


class TestDisbursementTerminalLockdown:
    def test_void_released_disbursement_rejected(self, api):
        """PRD §3.8: "Acting on a disbursement in any other state is `ERR_DISBURSEMENT_INVALID_STATE` (HTTP 409)."
        PRD §3.8: "A disbursement that should never have been created can be voided, but only from `PENDING`: voiding moves it to `VOIDED` and refunds its `amount_cents` back into the program's `qsf_remaining_cents`. A disbursement that has already been approved cannot be voided."

        Design: Corner/state_machines/disbursement_terminal_state_lockdown
        """
        ctx = create_disbursed_claim(
            base_award_cents=5_000_000, represented_by_counsel=False, severities=(70, 65),
            lien_action="waive", lien_type="MEDICARE", holder_name="CMS",
            asserted_amount_cents=100_000,
        )
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        did = ctx["disbursements"][0]["id"]
        resp = api.void_disbursement(pid, cid, did, make_disbursement_approver_headers(PREPARE_USER_ID))
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_INVALID_STATE)

    def test_approve_released_disbursement_rejected(self, api):
        """PRD §3.8: "Acting on a disbursement in any other state is `ERR_DISBURSEMENT_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/disbursement_terminal_state_lockdown
        """
        ctx = create_disbursed_claim(
            base_award_cents=5_000_000, represented_by_counsel=False, severities=(70, 65),
            lien_action="waive", lien_type="MEDICARE", holder_name="CMS",
            asserted_amount_cents=100_000,
        )
        pid, cid = ctx["program"]["id"], ctx["claim"]["id"]
        did = ctx["disbursements"][0]["id"]
        resp = api.approve_disbursement(pid, cid, did, make_disbursement_approver_headers(APPROVER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_INVALID_STATE)

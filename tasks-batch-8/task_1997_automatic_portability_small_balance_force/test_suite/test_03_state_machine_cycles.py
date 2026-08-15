"""Queue A difficulty tests: non-linear (cyclic) state machines."""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_provider_ops_headers,
    make_participant_headers,
    setup_notified_case,
    setup_transfer_ready_ira,
    setup_auto_expired_case,
    initiate_transfer,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


class TestCaseRenoticeCycleNotifiedIdentified:
    def test_returned_mail_falls_back_to_identified(self):
        """PRD §3.4: "Recording `RETURNED_MAIL` — permitted from either `SENT` or
        `DELIVERED` — also marks the participant `BAD_ADDRESS`, and if the returned notice
        was the case's `current_notice_id`, the case falls back from `NOTIFIED` to
        `IDENTIFIED` and clears `current_notice_id`; the participant must be re-addressed
        and re-noticed before any window can run again."

        Design: Difficulty/non_linear_state_machine/case_renotice_cycle_notified_identified
        """
        ctx = setup_notified_case(balance=50000)
        n1 = ctx["notice"]
        c_a = ctx["case"]["id"]
        p_a = ctx["participant"]["id"]

        # RETURNED_MAIL on the current notice flips the case back to IDENTIFIED.
        validate_success(api_client.record_notice_delivery(
            n1["id"], {"outcome": "RETURNED_MAIL"}, OPS))
        case = get_success_data(api_client.get_distribution_case(c_a, OPS))
        assert case["case_status"] == "IDENTIFIED"
        assert case["current_notice_id"] is None
        participant = get_success_data(api_client.get_participant(p_a, OPS))
        assert participant["address_quality"] == "BAD_ADDRESS"

    def test_full_renotice_cycle_with_address_repair(self):
        """PRD §3.2: "Any successful address update — touching `mailing_address_line1`,
        `mailing_city`, `mailing_state`, `mailing_zip`, or `email`, performed by a
        `PlanSponsor`, a `ProviderOps` operator, or the participant — marks
        `address_quality` `VALID`"
        PRD §3.4: "the case advances to `NOTIFIED` and adopts that notice as its
        `current_notice_id` — the window that now governs the case."
        PRD §3.4: "Recording `DELIVERED` on a `SENT` notice stamps `delivered_at` and
        computes the `response_deadline` as thirty days after delivery."

        Design: Difficulty/non_linear_state_machine/case_renotice_cycle_notified_identified
        """
        ctx = setup_notified_case(balance=50000)
        n1 = ctx["notice"]
        c_a = ctx["case"]["id"]
        p_a = ctx["participant"]["id"]

        validate_success(api_client.record_notice_delivery(
            n1["id"], {"outcome": "RETURNED_MAIL"}, OPS))
        participant = get_success_data(api_client.get_participant(p_a, OPS))
        assert participant["address_quality"] == "BAD_ADDRESS"

        # Address repair flips address_quality back to VALID.
        validate_success(api_client.patch_participant(
            p_a, {"mailing_address_line1": "9 New Ave"}, OPS))
        participant = get_success_data(api_client.get_participant(p_a, OPS))
        assert participant["address_quality"] == "VALID"

        # Fresh notice delivered: case NOTIFIED again with the new current notice.
        n2 = get_success_data(api_client.create_notice(
            c_a, {"notice_type": "FORCE_OUT_ELECTION"}, OPS))
        validate_success(api_client.record_notice_delivery(
            n2["id"], {"outcome": "DELIVERED"}, OPS))
        case = get_success_data(api_client.get_distribution_case(c_a, OPS))
        assert case["case_status"] == "NOTIFIED"
        assert case["current_notice_id"] == n2["id"]
        n2_fresh = get_success_data(api_client.get_notice(n2["id"], OPS))
        assert n2_fresh["response_deadline"] == "2026-08-31T00:00:00.000Z"


class TestIraTransferRejectReopenCycle:
    def test_rejected_transfer_reopens_ira(self):
        """PRD §3.7: "Rejection unwinds in three links: the transfer becomes `RETURNED`
        with `settled_at` stamped; the IRA is re-credited — `in_flight_cents` down by the
        amount, `balance_cents` up by the same — and returns from `TRANSFER_PENDING` to
        `OPEN` with `last_activity_at` refreshed, reopening it for a fresh match search;
        and the match falls from `EXECUTED` to `REJECTED`."

        Design: Difficulty/non_linear_state_machine/ira_transfer_reject_reopen_cycle
        """
        ctx = setup_transfer_ready_ira(balance=300000, clock="2026-09-01T00:00:00Z")
        ira = ctx["ira"]
        m1 = ctx["match"]
        transfer = initiate_transfer(ira["id"])
        tr = validate_success(api_client.record_transfer_response(
            transfer["id"], {"outcome": "REJECTED",
                             "rejection_reason": "no such account"}, OPS))

        assert tr["transfer_status"] == "RETURNED"
        ira_after = get_success_data(api_client.get_safe_harbor_ira(ira["id"], OPS))
        assert ira_after["ira_status"] == "OPEN"
        assert ira_after["balance_cents"] == 300000
        assert ira_after["in_flight_cents"] == 0
        m1_after = get_success_data(api_client.get_match_candidate(m1["id"], OPS))
        assert m1_after["match_status"] == "REJECTED"

    def test_reopened_ira_accepts_fresh_match_search(self):
        """PRD §3.7: "returns from `TRANSFER_PENDING` to `OPEN` with `last_activity_at`
        refreshed, reopening it for a fresh match search"

        Design: Difficulty/non_linear_state_machine/ira_transfer_reject_reopen_cycle
        """
        ctx = setup_transfer_ready_ira(balance=300000, clock="2026-09-01T00:00:00Z")
        ira = ctx["ira"]
        transfer = initiate_transfer(ira["id"])
        validate_success(api_client.record_transfer_response(
            transfer["id"], {"outcome": "REJECTED",
                             "rejection_reason": "no such account"}, OPS))
        # The reopened IRA accepts a fresh match probe.
        m2 = validate_success(api_client.create_match_search(
            ira["id"],
            {"new_plan_id": ctx["plan_y"]["id"],
             "new_recordkeeper_id": ctx["rk_b"]["id"],
             "employment_start_date": "2026-09-05", "ssn_exact": True,
             "name_similarity": 0.80, "dob_match": True},
            OPS,
        ), 201)
        assert m2["match_status"] in ("CANDIDATE", "CONFIRMED")


class TestBatchReconExceptionCycle:
    def _setup(self):
        """Auto cash-out case (100000), batch EXECUTED, check ISSUED."""
        ctx = setup_auto_expired_case(balance=100000)
        chk = get_success_data(api_client.create_check(
            {"distribution_case_id": ctx["case"]["id"]}, OPS))
        ctx["check"] = chk
        return ctx

    def test_reconcile_with_uncashed_check_goes_recon_exception(self):
        """PRD §3.9: "if at least one case is still `EXECUTED`, an uncashed check
        outstanding, the batch instead moves to `RECON_EXCEPTION`, touching no cases and
        recording that money movement is unsettled."

        Design: Difficulty/non_linear_state_machine/batch_recon_exception_cycle
        """
        ctx = self._setup()
        batch = validate_success(api_client.reconcile_distribution_batch(
            ctx["batch"]["id"], OPS))
        assert batch["batch_status"] == "RECON_EXCEPTION"

    def test_full_recon_exception_cycle(self):
        """PRD §3.9: "if every attached case has reached a terminal status — `SETTLED`,
        `ESCHEATED`, or `CANCELLED` — the batch moves to `RECONCILED` and stamps
        `reconciled_at`"
        PRD §3.9: "From `RECON_EXCEPTION`, resuming after remediation returns the batch to
        `EXECUTED` and recomputes the counters again, also incrementing `version`."

        Design: Difficulty/non_linear_state_machine/batch_recon_exception_cycle
        """
        ctx = self._setup()
        batch = validate_success(api_client.reconcile_distribution_batch(
            ctx["batch"]["id"], OPS))
        assert batch["batch_status"] == "RECON_EXCEPTION"

        # Cash the check: case EXECUTED -> SETTLED.
        validate_success(api_client.record_check_cashed(ctx["check"]["id"], OPS))
        case = get_success_data(
            api_client.get_distribution_case(ctx["case"]["id"], OPS))
        assert case["case_status"] == "SETTLED"

        # Resume flips RECON_EXCEPTION -> EXECUTED.
        batch = validate_success(api_client.resume_distribution_batch(
            ctx["batch"]["id"], OPS))
        assert batch["batch_status"] == "EXECUTED"

        # Second reconcile now lands RECONCILED.
        batch = validate_success(api_client.reconcile_distribution_batch(
            ctx["batch"]["id"], OPS))
        assert batch["batch_status"] == "RECONCILED"

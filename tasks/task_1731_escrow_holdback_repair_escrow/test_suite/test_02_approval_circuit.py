"""Approval circuit: submission, amendment, OCC, activation, rejection cycle."""
from test_helpers import (
    ApiErrorId,
    PARTIES,
    TEST_USERS,
    create_draft_holdback,
    decide_approval,
    find_approval,
    get_approvals,
    get_holdback,
    list_ledger,
    make_insurer_headers,
    make_lender_headers,
    set_logical_clock,
    setup_active_holdback,
    setup_escrow_file,
    setup_pending_holdback,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestSubmit:
    def test_submit_from_non_draft_rejected(self, api):
        """PRD §3.2: "Submitting moves a holdback from `DRAFT` to `PENDING_APPROVALS`; submitting from any other state is rejected with `ERR_INVALID_STATE`."
        PRD §3.2: "Submission creates the approval requests the terms demand: always one `Approval` with `approver_role` `LENDER`, and a second with `approver_role` `INSURER` when insurer approval is required."

        A second submit on a PENDING_APPROVALS holdback fails, and the first
        submit's single REQUESTED approval remains the only fan-out.

        Design: Corner/state_machines/submit_from_non_draft_rejected
        """
        ctx = setup_pending_holdback()
        hb = ctx["holdback"]
        assert hb["status"] == "PENDING_APPROVALS"

        resp = api.submit_holdback(hb["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        approvals = get_approvals(hb["id"])
        assert len(approvals) == 1, "no duplicate approval fan-out on a rejected submit"
        assert approvals[0]["status"] == "REQUESTED"
        assert approvals[0]["approver_role"] == "LENDER"


class TestAmend:
    def test_amend_from_active_rejected_with_current_version(self, api):
        """PRD §3.2: "Amendment is the agreement's edit operation, available only while the holdback is in `DRAFT` or `PENDING_APPROVALS`; attempting it in any other state is `ERR_INVALID_STATE`."

        Amending an ACTIVE holdback fails with ERR_INVALID_STATE even when the
        OCC version is current — proving the state gate, not staleness, rejects.

        Design: Corner/state_machines/amend_from_active_rejected
        """
        ctx = setup_active_holdback()
        hb = ctx["holdback"]
        assert hb["status"] == "ACTIVE"

        resp = api.amend_holdback(
            hb["id"],
            {"expected_holdback_version": hb["version"], "repair_scope": "Bigger scope"},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_amend_recomputes_amount_and_posts_funding_delta(self, api):
        """PRD §3.2: "The amendment recomputes `holdback_amount_cents` from the (possibly updated) estimate and contingency, increments the holdback's `version` by one, and posts a funding-delta ledger entry so the trust reflects the new amount: a `FUNDING` entry for the positive difference when the recomputed amount exceeds what has been funded, a `REFUND_TO_SOURCE` entry for the difference when it is lower."

        Amend up posts FUNDING +57500 (230000 -> 287500); amend down posts
        REFUND_TO_SOURCE -80500 (287500 -> 207000).

        Design: Corner/calculations/amend_recomputes_amount_and_posts_funding_delta
        """
        set_logical_clock()
        file = setup_escrow_file()
        hb = create_draft_holdback(file["id"])
        v1 = hb["version"]

        amended_up = validate_success(
            api.amend_holdback(
                hb["id"],
                {"expected_holdback_version": v1, "repair_estimate_cents": 250000},
                OFFICER),
            200,
        )
        assert amended_up["holdback_amount_cents"] == 287500, "250000 x 1.15"
        assert amended_up["version"] == v1 + 1

        amended_down = validate_success(
            api.amend_holdback(
                hb["id"],
                {"expected_holdback_version": amended_up["version"],
                 "repair_estimate_cents": 180000},
                OFFICER),
            200,
        )
        assert amended_down["holdback_amount_cents"] == 207000, "180000 x 1.15"
        assert amended_down["version"] == v1 + 2

        entries = list_ledger(hb["id"])
        assert [e["entry_type"] for e in entries] == [
            "FUNDING", "FUNDING", "REFUND_TO_SOURCE"]
        assert entries[1]["amount_cents"] == 57500
        assert entries[1]["running_balance_cents"] == 287500
        assert entries[2]["amount_cents"] == -80500
        assert entries[2]["running_balance_cents"] == 207000

        final = get_holdback(hb["id"])
        assert final["trust_balance_cents"] == 207000
        assert final["version"] == v1 + 2

    def test_amend_with_stale_version_rejected(self, api):
        """PRD §2.8: "If that value does not match the holdback's current `version` — because another writer has amended or submitted the agreement since the client last read it — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), so that the client cannot silently discard terms it never saw."
        PRD §3.2: "increments the holdback's `version` by one"

        After a first amend advances the version by exactly one, a second amend
        carrying the stale observed version is rejected and changes nothing.

        Design: Corner/complexity_layers/amend_with_stale_version_rejected
        """
        set_logical_clock()
        file = setup_escrow_file()
        hb = create_draft_holdback(file["id"])
        v1 = hb["version"]

        ok = validate_success(
            api.amend_holdback(
                hb["id"],
                {"expected_holdback_version": v1, "repair_scope": "Roof plus gutters"},
                OFFICER),
            200,
        )
        assert ok["version"] == v1 + 1, "every mutation increments version by exactly 1"

        stale = api.amend_holdback(
            hb["id"],
            {"expected_holdback_version": v1, "repair_scope": "Stale-scope attempt"},
            OFFICER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        current = get_holdback(hb["id"])
        assert current["repair_scope"] == "Roof plus gutters"
        assert current["version"] == v1 + 1
        entries = list_ledger(hb["id"])
        assert len(entries) == 1 and entries[0]["entry_type"] == "FUNDING", (
            "a rejected amend posts no delta ledger entry"
        )

    def test_amend_stales_pending_approvals(self, api):
        """PRD §3.2: "Amending a holdback that sits in `PENDING_APPROVALS` additionally stales the entire live approval set — every `REQUESTED` and every `APPROVED` approval becomes `STALE`, so re-approval is required after resubmission — and returns the holdback to `DRAFT`."

        Design: Corner/complexity_layers/amend_stales_pending_approvals
        """
        ctx = setup_pending_holdback(with_insurer=True)
        file, hb = ctx["file"], ctx["holdback"]
        insurer_ap = find_approval(ctx["approvals"], "INSURER")
        decide_approval(insurer_ap["id"],
                        make_insurer_headers(file["insurer_user_id"]), "APPROVED")

        before = get_holdback(hb["id"])
        assert before["status"] == "PENDING_APPROVALS"

        amended = validate_success(
            api.amend_holdback(
                hb["id"],
                {"expected_holdback_version": before["version"], "contingency_pct": 20},
                OFFICER),
            200,
        )
        assert amended["status"] == "DRAFT"
        assert amended["holdback_amount_cents"] == 240000, "200000 x 1.20"

        approvals = get_approvals(hb["id"])
        assert len(approvals) == 2
        statuses = sorted(a["status"] for a in approvals)
        assert statuses == ["STALE", "STALE"], (
            "the APPROVED insurer approval is invalidated along with the REQUESTED one"
        )


class TestApprovalDecisions:
    def test_double_approval_decide_rejected(self, api):
        """PRD §3.2: "Only a `REQUESTED` approval can be decided — deciding one already decided, staled, or cancelled fails with `ERR_APPROVAL_NOT_PENDING`."
        PRD §3.2: "A `decision` of `APPROVED` records the decider in `approver_user_id`, stamps `decided_at`, and pins `holdback_version_at_decision` to the holdback's current `version` at the moment of decision"

        Design: Corner/state_machines/double_approval_decide_rejected
        """
        ctx = setup_pending_holdback()
        file, hb = ctx["file"], ctx["holdback"]
        lender_ap = ctx["approvals"][0]

        version_before = get_holdback(hb["id"])["version"]
        decided = decide_approval(lender_ap["id"],
                                  make_lender_headers(file["lender_user_id"]),
                                  "APPROVED")
        assert decided["status"] == "APPROVED"
        assert decided["approver_user_id"] == PARTIES["lender"]
        assert decided["holdback_version_at_decision"] == version_before
        assert decided["decided_at"] is not None

        again = api.decide_approval(lender_ap["id"], {"decision": "APPROVED"},
                                    make_lender_headers(file["lender_user_id"]))
        validate_error(again, ApiErrorId.ERR_APPROVAL_NOT_PENDING)

        after = [a for a in get_approvals(hb["id"]) if a["id"] == lender_ap["id"]][0]
        assert after["holdback_version_at_decision"] == version_before, (
            "the earlier decision's pinned version is untouched by the rejection"
        )

    def test_immediate_visibility_after_submit_and_decide(self, api):
        """PRD §2.10: "Derived state propagates immediately across the hierarchy."
        PRD §3.2: "immediately after each decision the system re-evaluates the holdback, and when every required approval is `APPROVED` and none remain `REQUESTED`, the holdback activates — `PENDING_APPROVALS` → `ACTIVE` — without any further client action."

        Submit returns PENDING_APPROVALS in its own response; the decide that
        completes the set returns the approval carrying its version pin; the
        very next read shows the holdback ACTIVE.

        Design: Corner/consistency_model/immediate_visibility_after_submit_and_decide
        """
        set_logical_clock()
        file = setup_escrow_file()
        hb = create_draft_holdback(file["id"])

        submitted = validate_success(api.submit_holdback(hb["id"], OFFICER), 200)
        assert submitted["status"] == "PENDING_APPROVALS"

        approvals = get_approvals(hb["id"])
        assert len(approvals) == 1 and approvals[0]["status"] == "REQUESTED"

        version_before = get_holdback(hb["id"])["version"]
        decided = decide_approval(approvals[0]["id"],
                                  make_lender_headers(file["lender_user_id"]),
                                  "APPROVED")
        assert decided["status"] == "APPROVED"
        assert decided["holdback_version_at_decision"] == version_before

        after = get_holdback(hb["id"])
        assert after["status"] == "ACTIVE", "auto-transition visible immediately"


class TestApprovalRejectionCycle:
    def test_lender_rejection_cascades_holdback_to_draft(self, api):
        """PRD §3.2: "A `decision` of `REJECTED`, optionally accompanied by a `rejection_reason`, does the opposite: the approval becomes `REJECTED`, the holdback falls back from `PENDING_APPROVALS` to `DRAFT`, and every sibling approval still `REQUESTED` is cancelled — the rejection loop that sends the agreement back to the drafting table."

        On a two-approval holdback the lender's rejection moots the still
        REQUESTED insurer approval.

        Design: Difficulty/non_linear_state_machine/holdback_approval_rejection_cycle
        """
        ctx = setup_pending_holdback(with_insurer=True)
        file, hb = ctx["file"], ctx["holdback"]
        insurer_ap = find_approval(ctx["approvals"], "INSURER")
        lender_ap = find_approval(ctx["approvals"], "LENDER")

        rejected = decide_approval(
            lender_ap["id"], make_lender_headers(file["lender_user_id"]),
            "REJECTED", rejection_reason="Contingency too low")
        assert rejected["status"] == "REJECTED"

        after = get_holdback(hb["id"])
        assert after["status"] == "DRAFT"

        approvals = get_approvals(hb["id"])
        assert find_approval(approvals, "LENDER")["status"] == "REJECTED"
        assert find_approval(approvals, "INSURER")["status"] == "CANCELLED", (
            "sibling approval still REQUESTED is cancelled by the rejection"
        )

    def test_amend_and_resubmit_reaches_active_with_version_pin(self, api):
        """PRD §3.2: "Amending a holdback that sits in `PENDING_APPROVALS` additionally stales the entire live approval set — every `REQUESTED` and every `APPROVED` approval becomes `STALE`, so re-approval is required after resubmission — and returns the holdback to `DRAFT`."
        PRD §3.2: "Every submission creates a fresh set of `REQUESTED` approvals."
        PRD §3.2: "A `decision` of `APPROVED` records the decider in `approver_user_id`, stamps `decided_at`, and pins `holdback_version_at_decision` to the holdback's current `version` at the moment of decision"

        After the rejection loop, an amend (contingency 15 -> 20) and resubmit
        start a fresh approval round that reaches ACTIVE with amount 240000.

        Design: Difficulty/non_linear_state_machine/holdback_approval_rejection_cycle
        """
        ctx = setup_pending_holdback(with_insurer=True)
        file, hb = ctx["file"], ctx["holdback"]
        lender_ap = find_approval(ctx["approvals"], "LENDER")
        decide_approval(lender_ap["id"], make_lender_headers(file["lender_user_id"]),
                        "REJECTED", rejection_reason="Contingency too low")

        current = get_holdback(hb["id"])
        assert current["status"] == "DRAFT"
        amended = validate_success(
            api.amend_holdback(
                hb["id"],
                {"expected_holdback_version": current["version"], "contingency_pct": 20},
                OFFICER),
            200,
        )
        assert amended["holdback_amount_cents"] == 240000, "amended 200000 x 1.20"

        resubmitted = validate_success(api.submit_holdback(hb["id"], OFFICER), 200)
        assert resubmitted["status"] == "PENDING_APPROVALS"

        round_two = [a for a in get_approvals(hb["id"]) if a["status"] == "REQUESTED"]
        assert len(round_two) == 2, "a fresh REQUESTED set per resubmission"

        version_at_decide = get_holdback(hb["id"])["version"]
        lender2 = find_approval(round_two, "LENDER")
        insurer2 = find_approval(round_two, "INSURER")
        decided_lender = decide_approval(lender2["id"],
                                         make_lender_headers(file["lender_user_id"]),
                                         "APPROVED")
        assert decided_lender["holdback_version_at_decision"] == version_at_decide
        decide_approval(insurer2["id"],
                        make_insurer_headers(file["insurer_user_id"]), "APPROVED")

        final = get_holdback(hb["id"])
        assert final["status"] == "ACTIVE"
        assert final["holdback_amount_cents"] == 240000

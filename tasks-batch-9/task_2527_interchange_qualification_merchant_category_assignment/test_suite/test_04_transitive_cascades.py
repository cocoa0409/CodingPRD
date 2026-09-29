"""Two depth-four cascades fired by a single call each: a sustained audit that
reaches all the way to a waitlist promotion, and a finalization that reaches all
the way to a suspended reclassification request.
"""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_capacity_pool_conserved,
    assert_enrolled_count_matches,
)
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    create_acquirer,
    create_incentive_program,
    create_mcc,
    create_platform,
    enrol_merchant,
    file_reclassification,
    finalize_batch,
    open_audit,
    open_batch,
    read_batch,
    read_enrollment,
    read_incentive_program,
    read_merchant,
    read_record,
    set_clock,
    start_fieldwork,
    submit_batch,
    sustain_findings,
)
from test_helpers.test_users import TEST_USERS

AUDITOR = "CA-1"


def _closed_full_program_with_a_waitlisted_successor():
    """Merchant A holds 96000000 of a 100000000 pool, which closes the program;
    merchant B waits behind it for 20000000 with no capacity debit."""
    set_clock("2026-09-03T00:00:00Z")
    platform = create_platform()
    acquirer = create_acquirer(platform["id"])
    create_mcc(
        "5411",
        "GROCERY",
        description="Grocery Stores",
        program_eligibility=["SMALL_TICKET"],
    )
    create_mcc(
        "7995",
        "GAMBLING",
        description="Betting and Wagering",
        program_eligibility=[],
        requires_documentation=True,
        high_risk=True,
    )
    program = create_incentive_program(
        program_name="Grocery Growth 2026",
        eligible_mcc_codes=["5411"],
        total_capacity_cents=100000000,
        min_commitment_cents=5000000,
        reopen_threshold_cents=5000000,
        performance_threshold_pct=80.00,
    )
    merchant_a = board_merchant(acquirer["id"], "GROCERY", legal_name="Grocer A")
    merchant_b = board_merchant(acquirer["id"], "GROCERY", legal_name="Grocer B")
    enrollment_a = enrol_merchant(
        program["id"],
        merchant_a["id"],
        96000000,
        acquirer["id"],
        expected_incentive_program_version=program["version"],
    )
    enrollment_b = enrol_merchant(
        program["id"],
        merchant_b["id"],
        20000000,
        acquirer["id"],
        waitlist_requested=True,
    )
    audit = open_audit(merchant_a["id"], "COMPLAINT", auditor_user_id=AUDITOR)
    start_fieldwork(
        audit["id"],
        "2026-09-03T09:00:00Z",
        "2026-09-04T17:00:00Z",
        auditor_user_id=AUDITOR,
    )
    return {
        "acquirer": acquirer,
        "program": program,
        "merchant_a": merchant_a,
        "merchant_b": merchant_b,
        "enrollment_a": enrollment_a,
        "enrollment_b": enrollment_b,
        "audit": audit,
    }


class TestSustainedAuditCascadesToWaitlistPromotion:
    def test_the_penalty_and_the_merchant_restatement_are_the_first_two_hops(self):
        """A merchant with an empty ledger still attracts the fifty-dollar
        minimum, and the restatement rewrites the category and locks the merchant
        into the terminal posture.

        PRD 3.9: "The audit advances `FIELDWORK → FINDINGS_SUSTAINED` and a
        penalty is assessed: `penalty_assessed_cents` is the larger of a
        fifty-dollar minimum of 5000 cents and the merchant's
        `lifetime_net_assessed_cents` multiplied by the misrepresentation penalty
        rate of 2500 basis points — a quarter of the ledger — divided by ten
        thousand and rounded half up to whole cents."

        Design: Difficulty/transitive_cascade/cascade_audit_sustain_to_merchant_to_enrollment_to_capacity_to_waitlist_promotion
        """
        state = _closed_full_program_with_a_waitlisted_successor()
        assert read_merchant(state["merchant_a"]["id"])["lifetime_net_assessed_cents"] == 0

        sustained = sustain_findings(
            state["audit"]["id"],
            "7995",
            auditor_user_id=AUDITOR,
            findings_note="Gambling volume disguised as grocery",
        )
        assert sustained["status"] == "FINDINGS_SUSTAINED"
        assert sustained["penalty_assessed_cents"] == 5000
        assert sustained["mcc_at_audit_open"] == "5411"

        merchant_a = read_merchant(state["merchant_a"]["id"])
        assert merchant_a["assigned_mcc"] == "7995"
        assert merchant_a["mcc_status"] == "MISREPRESENTED"

    def test_the_released_capacity_reopens_the_program_and_promotes_the_head_of_line_row(
        self,
    ):
        """Terminating the now-ineligible enrollment credits 96000000 back, which
        reopens the program and promotes the single earliest waitlisted row,
        re-debiting 20000000 and leaving 80000000 free.

        PRD 3.8: "That reopening carries a cascade: the service examines the
        **single** waitlisted enrollment of the program with the smallest
        `created_at` and promotes it `WAITLISTED → ENROLLED` if and only if its
        `committed_volume_cents` fits inside the current
        `uncommitted_capacity_cents`, stamping `enrolled_at`, debiting the pool and
        raising `enrolled_count`."

        Design: Difficulty/transitive_cascade/cascade_audit_sustain_to_merchant_to_enrollment_to_capacity_to_waitlist_promotion
        """
        state = _closed_full_program_with_a_waitlisted_successor()
        before = read_incentive_program(state["program"]["id"])
        assert before["enrollment_state"] == "CLOSED_FULL"
        assert before["uncommitted_capacity_cents"] == 4000000

        sustain_findings(
            state["audit"]["id"],
            "7995",
            auditor_user_id=AUDITOR,
            findings_note="Gambling volume disguised as grocery",
        )

        enrollment_a = read_enrollment(state["enrollment_a"]["id"])
        enrollment_b = read_enrollment(state["enrollment_b"]["id"])
        assert enrollment_a["status"] == "TERMINATED_INELIGIBLE"
        assert enrollment_b["status"] == "ENROLLED"
        assert enrollment_b["enrolled_at"] is not None

        program = read_incentive_program(state["program"]["id"])
        assert program["enrollment_state"] == "OPEN"
        assert program["uncommitted_capacity_cents"] == 80000000
        assert program["enrolled_count"] == 1
        assert_capacity_pool_conserved(program, [enrollment_a, enrollment_b])
        assert_enrolled_count_matches(program, [enrollment_a, enrollment_b])


def _three_downgrades_pending_finalization():
    """A submitted batch of three 1200-cent records with no data elements at all,
    behind a merchant that already carries a live reclassification request."""
    env = canonical_environment("2026-09-03T00:00:00Z")
    create_mcc(
        "9399",
        "GOVERNMENT",
        description="Government Services",
        program_eligibility=["GOVERNMENT"],
    )
    merchant = board_merchant(
        env["acquirer"]["id"], "GROCERY", headers=env["acquirer_headers"]
    )
    request = file_reclassification(
        merchant["id"],
        "9399",
        env["acquirer"]["id"],
        expected_merchant_version=merchant["version"],
        justification="Municipal collections",
    )
    batch = open_batch(
        env["acquirer"]["id"], "2026-09-02", "USD", headers=env["acquirer_headers"]
    )
    records = []
    for auth_code in ("A00060", "A00061", "A00062"):
        records.append(
            add_record(
                batch["id"],
                merchant["id"],
                1200,
                env["acquirer"]["id"],
                headers=env["acquirer_headers"],
                auth_code=auth_code,
                auth_timestamp="2026-09-01T00:00:00Z",
                clearing_timestamp="2026-09-01T02:00:00Z",
                data_elements=[],
            )
        )
    submit_batch(batch["id"], headers=env["acquirer_headers"])
    env["merchant"] = merchant
    env["request"] = request
    env["batch"] = batch
    env["records"] = records
    return env


class TestFinalizationCascadesToAnAutomaticAudit:
    def test_the_three_downgrades_drive_the_counter_and_open_a_threshold_audit(self):
        """Three downgraded records take the merchant's quarterly count to exactly
        three, which is the at-or-above tripwire, and the system opens the audit
        by itself.

        PRD 3.6: "The audit is created in `status` `SCHEDULED` with
        `trigger_reason` `DOWNGRADE_THRESHOLD`, `auditor_user_id` null,
        `penalty_assessed_cents` 0, and `mcc_at_audit_open` snapshotting the
        merchant's current `assigned_mcc`."

        Design: Difficulty/transitive_cascade/cascade_batch_finalize_to_downgrade_counter_to_auto_audit_to_reclassification_suspension
        """
        env = _three_downgrades_pending_finalization()
        finalize_batch(env["batch"]["id"])

        for record in env["records"]:
            reread = read_record(record["id"])
            assert reread["qualification_status"] == "DOWNGRADED"
            assert reread["assessed_interchange_cents"] == 40
            assert reread["downgrade_reason"] == "MISSING_DATA_ELEMENTS"

        assert read_batch(env["batch"]["id"])["total_assessed_cents"] == 120

        merchant = read_merchant(env["merchant"]["id"])
        assert merchant["downgrade_count_current_quarter"] == 3
        assert merchant["lifetime_net_assessed_cents"] == 120
        assert merchant["mcc_status"] == "UNDER_REVIEW"
        assert merchant["mcc_status_before_review"] == "VERIFIED"

        audits, meta = validate_paginated(
            api_client.list_merchant_category_audits(
                TEST_USERS["compliance_auditor_headers"],
                params={
                    "merchant_id": env["merchant"]["id"],
                    "trigger_reason": "DOWNGRADE_THRESHOLD",
                },
            )
        )
        assert meta["total_count"] == 1
        assert len(audits) == 1
        assert audits[0]["status"] == "SCHEDULED"
        assert audits[0]["auditor_user_id"] is None
        assert audits[0]["penalty_assessed_cents"] == 0
        assert audits[0]["mcc_at_audit_open"] == "5411"

    def test_the_automatic_audit_freezes_the_live_reclassification_request(self):
        """The last hop of the chain reaches the reclassification request, which
        snapshots its own status before moving to the suspended state.

        PRD 3.6: "Finally, each such merchant's live reclassification requests —
        those in `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED` — snapshot their
        status into `prior_status_before_suspension` and move to
        `SUSPENDED_PENDING_AUDIT`, exactly as Section 3.4 describes."

        Design: Difficulty/transitive_cascade/cascade_batch_finalize_to_downgrade_counter_to_auto_audit_to_reclassification_suspension
        """
        env = _three_downgrades_pending_finalization()
        assert env["request"]["status"] == "SUBMITTED"

        finalize_batch(env["batch"]["id"])

        from prd_bench_local_runner.testing import validate_success

        reread = validate_success(
            api_client.get_reclassification_request(
                env["request"]["id"], TEST_USERS["network_admin_headers"]
            )
        )
        assert reread["status"] == "SUSPENDED_PENDING_AUDIT"
        assert reread["prior_status_before_suspension"] == "SUBMITTED"

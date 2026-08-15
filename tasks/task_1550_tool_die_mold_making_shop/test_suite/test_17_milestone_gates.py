"""Milestone gates: strict sequence ordering and the seq-5 actor rule
(PRD §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    buyoff_tryout_round,
    complete_milestones_seq,
    get_success_data,
    make_customer_headers,
    schedule_tryout_round,
    setup_booked_job,
    start_build,
    submit_tryout_round,
    validate_error,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]


def test_milestone_out_of_sequence_rejected(api):
    """PRD §3.5: "The remaining gates, in order: the job must not be
    `ON_HOLD` (`ERR_JOB_ON_HOLD`); every milestone with a lower `seq` must
    already be in `EARNED`, `INVOICED`, or `PAID`
    (`ERR_MILESTONE_SEQUENCE_BLOCKED`); sequence 4 additionally requires an
    existing tryout sample for the job in `SUBMITTED` or `BOUGHT_OFF`
    (`ERR_INVALID_STATE`); sequence 5 requires an existing `BOUGHT_OFF`
    sample; and sequence 6 requires the tool's `physical_status` to be
    `IN_PRODUCTION` (`ERR_INVALID_STATE`)."
    PRD §3.5: "Completion stamps `completed_at` from the logical clock — and
    on a `PENDING` to `EARNED` move the earned amount locks at the milestone's
    current `planned_amount_cents`; the caller may attach an optional
    `completion_note`."

    Design: Corner/state_machines/milestone_out_of_sequence_rejected
    """
    ctx = setup_booked_job(company_name="Seq Co", part_number="PN-SQ1")
    m1, m2 = ctx["milestones"][0], ctx["milestones"][1]

    res = api_client.complete_milestone(m2["id"], {}, PM)
    error = validate_error(res, ApiErrorId.ERR_MILESTONE_SEQUENCE_BLOCKED)
    assert error["error_id"] == "ERR_MILESTONE_SEQUENCE_BLOCKED"
    assert res.status_code == 409

    first = validate_success(api_client.complete_milestone(m1["id"], {}, PM), 200)
    assert first["status"] == "EARNED"
    assert first["completed_at"] is not None

    second = validate_success(api_client.complete_milestone(m2["id"], {}, PM), 200)
    assert second["status"] == "EARNED", (
        "once seq 1 is EARNED the seq-2 completion must succeed"
    )


def test_project_manager_cannot_sign_buyoff_milestone(api):
    """PRD §3.5: "Completing a milestone — moving it from `PENDING` to
    `EARNED`, or from `REOPENED` back to `EARNED` after rework — is a
    `ProjectManager` action for sequences 1 through 4 and 6, and the owning
    customer's action for sequence 5, the `BUYOFF_SIGNED` signature. The actor
    rule is enforced both ways: a customer attempting any sequence other than
    5, or anyone other than the owning customer attempting sequence 5, is
    rejected with `ERR_MILESTONE_ACTOR_MISMATCH` (HTTP 403)."

    Design: Corner/state_machines/milestone_five_actor_segregation
    """
    ctx = setup_booked_job(company_name="Actor Co", part_number="PN-AC1")
    job_id = ctx["job"]["id"]
    start_build(job_id)
    _, sample = schedule_tryout_round(job_id)
    submit_tryout_round(sample["id"], sample_qty=30, shots_used=500,
                        measured_report_ref="LAY-1")
    buyoff_tryout_round(sample["id"], "BOUGHT_OFF")
    complete_milestones_seq(ctx["milestones"], ctx["customer"]["id"], seqs=(1, 2, 3, 4))

    m5 = ctx["milestones"][4]
    res = api_client.complete_milestone(m5["id"], {}, PM)
    error = validate_error(res, ApiErrorId.ERR_MILESTONE_ACTOR_MISMATCH)
    assert error["error_id"] == "ERR_MILESTONE_ACTOR_MISMATCH"
    assert res.status_code == 403

    earned = validate_success(
        api_client.complete_milestone(
            m5["id"], {}, make_customer_headers(ctx["customer"]["id"])
        ),
        200,
    )
    assert earned["status"] == "EARNED"
    assert earned["code"] == "BUYOFF_SIGNED"


def test_customer_cannot_complete_non_signature_milestone(api):
    """PRD §3.5: "The actor rule is enforced both ways: a customer attempting
    any sequence other than 5, or anyone other than the owning customer
    attempting sequence 5, is rejected with `ERR_MILESTONE_ACTOR_MISMATCH`
    (HTTP 403)."

    Design: Corner/state_machines/milestone_five_actor_segregation
    """
    ctx = setup_booked_job(company_name="Actor Co", part_number="PN-AC1")
    m1 = ctx["milestones"][0]

    res = api_client.complete_milestone(
        m1["id"], {}, make_customer_headers(ctx["customer"]["id"])
    )
    error = validate_error(res, ApiErrorId.ERR_MILESTONE_ACTOR_MISMATCH)
    assert error["error_id"] == "ERR_MILESTONE_ACTOR_MISMATCH"
    assert res.status_code == 403

    milestone = get_success_data(api_client.get_build_milestone(m1["id"], PM))
    assert milestone["status"] == "PENDING"

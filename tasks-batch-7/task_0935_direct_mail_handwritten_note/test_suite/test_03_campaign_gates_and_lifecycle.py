"""The three campaign status axes, the derived write gate, and closing the books."""

from test_helpers import (
    ApiErrorId,
    CAMPAIGN_MANAGER,
    COMPLIANCE_OFFICER,
    add_drip_step_ok,
    assert_campaign,
    assert_write_gate_derivation,
    build_addressed_scenario,
    build_drip_scenario,
    build_eddm_scenario,
    create_account,
    create_campaign,
    ledger_rows,
    read_campaign,
    read_drip_step,
    read_mail_job,
    set_clock,
    validate_error,
    validate_success,
)


def test_pausing_a_draft_campaign_is_a_campaign_state_failure(api):
    """PRD §3.4: "Rung 15 polices this axis and the compliance axis together:
    activation demands `DRAFT` or `PAUSED`, pausing demands `ACTIVE`, closing the
    books demands `ACTIVE` or `PAUSED`, placing a hold demands
    `compliance_status` `CLEAR`, and lifting one demands `compliance_status`
    `HOLD`. Any mismatch is `ERR_CAMPAIGN_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/campaign_pause_from_draft_returns_campaign_invalid_state
    """
    set_clock()
    account = create_account(permit_number="PMT-210")
    campaign = create_campaign(account["id"])
    assert campaign["lifecycle_status"] == "DRAFT"

    response = api.pause_campaign(campaign["id"], CAMPAIGN_MANAGER)
    validate_error(response, ApiErrorId.ERR_CAMPAIGN_INVALID_STATE.value)

    assert read_campaign(campaign["id"])["lifecycle_status"] == "DRAFT"


def test_pausing_a_campaign_unschedules_its_scheduled_drip_steps(api):
    """PRD §3.4: "Pausing moves `ACTIVE → PAUSED`, again requiring an open gate,
    and carries one side effect beyond the status change: every drip step
    belonging to this campaign's schedules whose status is `SCHEDULED` is
    unscheduled back to `PENDING`, clearing the derived dates it was holding."
    PRD §3.6: "An accepted step writes `computed_mail_date`,
    `computed_in_home_date` and `shifted_days`, and takes its initial status from
    the job it drops: a step whose job is in `PROOFED` or `SCHEDULED` is admitted
    straight along `PENDING → SCHEDULED`, while a step whose job is in any other
    status rests at `PENDING` until the job catches up and the same edge is
    applied."

    Design: Corner/state_machines/campaign_pause_unschedules_scheduled_drip_steps
    """
    world = build_drip_scenario(permit_number="PMT-218", job_count=1, approve_jobs=True)
    job = world["jobs"][0]
    step = add_drip_step_ok(world["schedule"]["id"], job["id"], 1, "2026-06-15")
    assert step["status"] == "SCHEDULED", "the step's job is PROOFED"
    assert step["computed_mail_date"] == "2026-06-05"

    validate_success(api.activate_campaign(world["campaign"]["id"], CAMPAIGN_MANAGER))
    paused = validate_success(api.pause_campaign(world["campaign"]["id"], CAMPAIGN_MANAGER))
    assert_campaign(paused)
    assert paused["lifecycle_status"] == "PAUSED"

    after = read_drip_step(step["id"])
    assert after["status"] == "PENDING"
    assert after["computed_mail_date"] is None
    assert after["computed_in_home_date"] is None
    assert read_mail_job(job["id"])["status"] == "PROOFED"


def test_billing_close_freezes_the_campaign_and_closes_its_mailed_jobs(api):
    """PRD §3.9: "The close moves `billing_status` `OPEN → CLOSED` and moves
    `lifecycle_status` `ACTIVE → COMPLETED` or `PAUSED → COMPLETED` according to
    where the campaign stood, and sets `write_gate` to `FROZEN` permanently —
    this is the one freeze that admits no exemption at all, and after it no write
    against the campaign or anything reachable from it will ever succeed again."
    PRD §3.9: "**Hop 2** — every mail job on the campaign whose `status` is
    `MAILED` moves `MAILED → CLOSED`, and each such job's `version` increments."
    PRD §2.5: "A campaign whose `billing_status` is `CLOSED` rejects the write
    with `ERR_CAMPAIGN_BILLING_CLOSED` (HTTP 409), and here there is no exemption
    whatever — not even the hold-lifting endpoint, which means a campaign that is
    both held and closed can never be unfrozen."

    Design: Corner/state_machines/billing_close_freezes_campaign_and_closes_mailed_jobs
    """
    world = build_eddm_scenario(
        permit_number="PMT-220", stage="mailed", activate_campaign=True
    )
    assert world["job"]["status"] == "MAILED"

    closed = validate_success(
        api.billing_close_campaign(world["campaign"]["id"], COMPLIANCE_OFFICER)
    )
    assert_campaign(closed)
    assert closed["billing_status"] == "CLOSED"
    assert closed["lifecycle_status"] == "COMPLETED"
    assert closed["write_gate"] == "FROZEN"
    assert read_mail_job(world["job"]["id"])["status"] == "CLOSED"

    release = api.create_compliance_release(world["campaign"]["id"], COMPLIANCE_OFFICER)
    error = validate_error(release, ApiErrorId.ERR_CAMPAIGN_BILLING_CLOSED.value)
    assert error["error_id"] != ApiErrorId.ERR_CAMPAIGN_COMPLIANCE_HOLD.value


def test_compliance_hold_pre_empts_the_mail_job_state_gate_on_commit(api):
    """PRD §2.5: "A campaign whose `compliance_status` is `HOLD` rejects the write
    with `ERR_CAMPAIGN_COMPLIANCE_HOLD` (HTTP 409); exactly one write endpoint is
    exempt, namely lifting the hold itself."
    PRD §2.6: "First, the two write-gate rungs sit **above** every per-endpoint
    state gate, so a frozen campaign pre-empts state, kind, temporal, capacity and
    fiscal complaints alike — a request that is both aimed at a held campaign and
    aimed at a job in the wrong state reports the hold."

    Design: Difficulty/priority_pair_validation_conflict/compliance_hold_preempts_mail_job_state_gate
    """
    world = build_addressed_scenario(permit_number="PMT-130", stage="draft")
    validate_success(
        api.create_compliance_hold(
            world["campaign"]["id"], {"hold_reason": "suppression list audit"},
            COMPLIANCE_OFFICER,
        )
    )

    response = api.commit_mail_job(world["job"]["id"], CAMPAIGN_MANAGER)
    error = validate_error(response, ApiErrorId.ERR_CAMPAIGN_COMPLIANCE_HOLD.value)
    assert error["error_id"] != ApiErrorId.ERR_MAIL_JOB_INVALID_STATE.value


def test_a_held_campaign_freezes_its_gate_and_leaves_the_blocked_job_untouched(api):
    """PRD §2.5: "From those last two the server derives a fourth, read-only field,
    `write_gate`, which reads `FROZEN` whenever `compliance_status` is `HOLD` or
    `billing_status` is `CLOSED`, and `OPEN` only when compliance is `CLEAR` and
    billing is `OPEN` at the same time."
    PRD §3.4: "A `ComplianceOfficer` (or `PlatformAdmin`) places a hold by
    supplying a `hold_reason`, which is stored on the campaign and survives the
    hold being lifted, so the most recent reason remains readable afterwards;
    before any hold has ever been placed the field is null."

    Design: Difficulty/priority_pair_validation_conflict/compliance_hold_preempts_mail_job_state_gate
    """
    world = build_addressed_scenario(permit_number="PMT-130", stage="draft")
    held = validate_success(
        api.create_compliance_hold(
            world["campaign"]["id"], {"hold_reason": "suppression list audit"},
            COMPLIANCE_OFFICER,
        )
    )
    assert_write_gate_derivation(held)
    assert held["compliance_status"] == "HOLD"
    assert held["write_gate"] == "FROZEN"
    assert held["hold_reason"] == "suppression list audit"

    api.commit_mail_job(world["job"]["id"], CAMPAIGN_MANAGER)

    job = read_mail_job(world["job"]["id"])
    assert job["status"] == "DRAFT"
    assert job["final_postage_cents"] is None
    assert job["total_due_cents"] is None
    assert job["drawn_postage_cents"] == 0
    draws = ledger_rows(campaign_id=world["campaign"]["id"], entry_type="DRAW")
    assert draws == [], "the refused commit drew nothing from the escrow"

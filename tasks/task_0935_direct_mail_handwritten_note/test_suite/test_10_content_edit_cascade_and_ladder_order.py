"""The content-edit cascade and the ladder order between staleness and the blackout walk."""

from test_helpers import (
    ApiErrorId,
    CAMPAIGN_MANAGER,
    PRODUCTION_OPERATOR,
    SINGLE_RECORD_ROSTER,
    api_client,
    assert_same_instant,
    build_addressed_scenario,
    create_blackout_dates,
    ledger_rows,
    mail_job_version,
    production_run_payload,
    read_account,
    read_ink_lot,
    read_mail_job,
    read_production_run,
    read_proof,
    set_clock,
    validate_error,
    validate_success,
)


def _committed_job_with_a_reserved_run(permit_number="PMT-120"):
    world = build_addressed_scenario(
        permit_number=permit_number, roster=SINGLE_RECORD_ROSTER, list_name="Mini List",
        dedupe_mode="EXACT", lock=True, stage="committed", with_plant=True,
    )
    world["run"] = validate_success(
        api_client.create_production_run(
            world["job"]["id"],
            production_run_payload(world["machine"]["id"], world["ink_lot"]["id"],
                                   mail_job_version(world["job"]["id"])),
            PRODUCTION_OPERATOR,
        ),
        201,
    )
    return world


def test_editing_body_copy_bumps_the_revision_and_unwinds_the_approval_and_job(api):
    """PRD §3.2: "**Only a change to `body_text` or to `character_count` bumps
    `version_no`.**"
    PRD §3.2: "2. **Hop 2** — every `Proof` on this template whose status is
    `APPROVED` moves `APPROVED → SUPERSEDED`, and each such proof's `version`
    increments by one. Supersession applies to approved proofs regardless of what
    state their job is in."
    PRD §3.2: "3. **Hop 3** — every `MailJob` whose outstanding approval was
    superseded in hop 2 and whose `status` is `PROOFED`, `SCHEDULED` or `COMMITTED`
    reverts to `DRAFT` along `PROOFED → DRAFT`, `SCHEDULED → DRAFT` or
    `COMMITTED → DRAFT` respectively."

    Design: Difficulty/transitive_cascade/template_edit_cascade_depth_five
    """
    world = _committed_job_with_a_reserved_run()
    assert world["job"]["status"] == "COMMITTED"
    assert world["proof"]["status"] == "APPROVED"

    edited = validate_success(
        api.patch_template(world["template"]["id"],
                           {"body_text": "Thank you very kindly indeed"},
                           CAMPAIGN_MANAGER)
    )
    assert edited["version_no"] == 2

    assert read_proof(world["proof"]["id"])["status"] == "SUPERSEDED"
    assert read_mail_job(world["job"]["id"])["status"] == "DRAFT"


def test_the_same_edit_voids_the_reserved_run_and_refunds_the_escrow_draw(api):
    """PRD §3.2: "4. **Hop 4** — every `ProductionRun` on those reverting jobs
    whose status is `RESERVED` moves `RESERVED → VOIDED`."
    PRD §3.2: "5. **Hop 5** — each run voided in hop 4 returns its
    `planned_ink_ul` to its ink lot's `remaining_ul` and releases its
    `planned_slot_minutes` on its machine-day bucket, per the conservation rules of
    §2.10."
    PRD §3.2: "6. **Hop 6** — each job that left `COMMITTED` appends a `REFUND`
    ledger entry for its `drawn_postage_cents` and raises the owning account's
    `permit_balance_cents` by that same amount."

    Design: Difficulty/transitive_cascade/template_edit_cascade_depth_five
    """
    world = _committed_job_with_a_reserved_run()
    assert world["run"]["planned_ink_ul"] == 2
    assert read_ink_lot(world["ink_lot"]["id"])["remaining_ul"] == 19_998
    # A single automation piece prices at the 51.0-cent no-presort rate: postage
    # 51, handling 250 + ceil(0.08 * 51 = 4.08) = 255, subtotal 306, no credit
    # below 6 pieces, so 306 cents were drawn at commit.
    assert read_account(world["account"]["id"])["permit_balance_cents"] == 499_694

    validate_success(
        api.patch_template(world["template"]["id"],
                           {"body_text": "Thank you very kindly indeed"},
                           CAMPAIGN_MANAGER)
    )

    assert read_production_run(world["run"]["id"])["status"] == "VOIDED"
    assert read_ink_lot(world["ink_lot"]["id"])["remaining_ul"] == 20_000

    account = read_account(world["account"]["id"])
    assert account["permit_balance_cents"] == 500_000
    assert account["lifetime_refund_cents"] == 306

    refunds = ledger_rows(account_id=account["id"], entry_type="REFUND")
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == 306
    assert refunds[0]["signed_amount_cents"] == 306


def test_a_stale_approval_is_reported_before_an_unresolvable_blackout_walk(api):
    """PRD §3.5: "Rung 25 asks whether the job's most recent approval is **still
    live** — that its proof's status is `APPROVED` rather than `SUPERSEDED` or
    `EXPIRED`, that its `pinned_template_version` still equals the template's
    current `version_no`, and that the logical clock is strictly before its
    `expires_at`. If an approval exists but fails any of those, the answer is
    `ERR_PROOF_APPROVAL_STALE` (HTTP 409)."
    PRD §3.6: "If the shift counter would exceed 5, the request is refused with
    `ERR_BLACKOUT_UNRESOLVABLE` (HTTP 422) at rung 28. The cap is inclusive: a walk
    that shifts exactly 5 days is accepted; one that would need 6 is not."
    PRD §2.6: "**For any request, the first rung whose condition fails produces the
    response, and no later rung is evaluated.**"

    Design: Difficulty/priority_pair_validation_conflict/proof_stale_preempts_blackout_unresolvable
    """
    world = build_addressed_scenario(
        permit_number="PMT-132", roster=SINGLE_RECORD_ROSTER, list_name="Mini List",
        dedupe_mode=None, lock=False, stage="proofed",
        target_in_home_date="2026-07-15", topup_cents=None,
    )
    # 2026-07-15 less MARKETING_MAIL's 10 transit days is 2026-07-05; six
    # consecutive blackout days from there back to 2026-06-30 would need a
    # seventh step, one past the inclusive cap of five.
    create_blackout_dates(
        ["2026-07-05", "2026-07-04", "2026-07-03", "2026-07-02", "2026-07-01",
         "2026-06-30"]
    )
    set_clock("2026-05-31T00:00:00Z")

    response = api.schedule_mail_job(
        world["job"]["id"], {"target_in_home_date": "2026-07-15"}, CAMPAIGN_MANAGER
    )
    error = validate_error(response, ApiErrorId.ERR_PROOF_APPROVAL_STALE.value)
    assert error["error_id"] != ApiErrorId.ERR_BLACKOUT_UNRESOLVABLE.value


def test_the_gate_evaluation_materialises_the_expiry_and_leaves_the_job_proofed(api):
    """PRD §3.5: "Expiry is materialized rather than swept: reading a proof
    individually moves it `APPROVED → EXPIRED` if the window has elapsed,
    incrementing its `version`, and so does any evaluation of the approval gate."
    PRD §3.5: "On success the proof moves `SUBMITTED → APPROVED`,
    `approved_by_user_id` is set to the approver's `X-User-ID`, `approved_at` is
    set to the logical clock's current instant, and `expires_at` is set to exactly
    thirty days after `approved_at`."

    Design: Difficulty/priority_pair_validation_conflict/proof_stale_preempts_blackout_unresolvable
    """
    world = build_addressed_scenario(
        permit_number="PMT-132", roster=SINGLE_RECORD_ROSTER, list_name="Mini List",
        dedupe_mode=None, lock=False, stage="proofed",
        target_in_home_date="2026-07-15", topup_cents=None,
    )
    # Approved at the clock's default 2026-05-01T00:00:00Z, so the thirty-day
    # window closes at 2026-05-31T00:00:00Z.
    assert_same_instant(world["proof"]["expires_at"], "2026-05-31T00:00:00Z", "expires_at")

    create_blackout_dates(
        ["2026-07-05", "2026-07-04", "2026-07-03", "2026-07-02", "2026-07-01",
         "2026-06-30"]
    )
    set_clock("2026-05-31T00:00:00Z")

    api.schedule_mail_job(
        world["job"]["id"], {"target_in_home_date": "2026-07-15"}, CAMPAIGN_MANAGER
    )

    assert read_proof(world["proof"]["id"])["status"] == "EXPIRED"
    job = read_mail_job(world["job"]["id"])
    assert job["status"] == "PROOFED"
    assert job["mail_date"] is None

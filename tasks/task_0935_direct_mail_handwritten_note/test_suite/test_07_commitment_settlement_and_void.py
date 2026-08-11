"""Committing a job: final pricing, the five settlement steps, the escrow draw and the void."""

from test_helpers import (
    ApiErrorId,
    CAMPAIGN_MANAGER,
    SATURATION_ROUTES_FIVE_PIECES,
    SATURATION_ROUTES_FOUR_PIECES,
    SEVEN_RECORD_ROSTER,
    SINGLE_RECORD_ROSTER,
    assert_ledger_entry,
    assert_mail_job,
    assert_postage_money_conservation,
    build_addressed_scenario,
    build_eddm_scenario,
    ledger_rows,
    read_account,
    read_campaign,
    read_list_record,
    read_mail_job,
    validate_error,
    validate_success,
)


def _household_marketing_job(stage):
    """Seven records, HOUSEHOLD-screened and locked, on a MARKETING_MAIL job."""
    return build_addressed_scenario(
        permit_number="PMT-104", roster=SEVEN_RECORD_ROSTER, dedupe_mode="HOUSEHOLD",
        lock=True, mail_class="MARKETING_MAIL", stage=stage,
    )


def _single_piece_committed_job(permit_number="PMT-170"):
    return build_addressed_scenario(
        permit_number=permit_number, roster=SINGLE_RECORD_ROSTER, list_name="Mini List",
        dedupe_mode="EXACT", lock=True, stage="committed",
    )


def test_the_final_total_can_exceed_the_provisional_one_after_screening(api):
    """PRD §3.4: "**The provisional quote counts every record whose
    `deliverability_tier` is `AUTOMATION` or `RETAIL`, ignoring `dedupe_status`
    entirely** — it is the number a customer sees before the list has been
    screened, and it therefore includes records that later screening will
    discard."
    PRD §3.7: "A marketing job quoted with six automation pieces at the
    mixed-AADC rate and one retail piece comes to 243 cents provisionally; if
    household screening then collapses one of those six, the job falls to five
    automation pieces, misses every presort tier, and prices at 51.0 cents each —
    255 cents for the automation tier plus 52 for the retail piece, or 307 cents
    in total."

    Design: Difficulty/dual_variant_calc/postage_provisional_vs_final_diverge_on_household_collapse
    """
    world = _household_marketing_job("proofed")
    job_id = world["job"]["id"]

    quoted = validate_success(api.estimate_mail_job(job_id, CAMPAIGN_MANAGER))
    assert quoted["provisional_postage_cents"] == 243

    validate_success(
        api.schedule_mail_job(job_id, {"target_in_home_date": "2026-06-15"},
                              CAMPAIGN_MANAGER)
    )
    committed = validate_success(api.commit_mail_job(job_id, CAMPAIGN_MANAGER))

    assert committed["final_postage_cents"] == 307
    assert committed["final_postage_cents"] > quoted["provisional_postage_cents"]


def test_final_pricing_drops_the_household_duplicate_and_loses_the_presort_tier(api):
    """PRD §3.7: "**Final pricing.** Postage is recomputed with the `FINAL` reading
    of the population: a record survives only if its `deliverability_tier` is
    `AUTOMATION` or `RETAIL` **and** its `dedupe_status` is `UNSCREENED`, `UNIQUE`
    or `HOUSEHOLD_HEAD`. Duplicates found by screening are excluded."
    PRD §3.4: "Every threshold is inclusive — six automation pieces select
    `PRESORT_MIXED_AADC`, five select `NO_PRESORT`."

    Design: Difficulty/dual_variant_calc/postage_provisional_vs_final_diverge_on_household_collapse
    """
    world = _household_marketing_job("scheduled")

    committed = validate_success(api.commit_mail_job(world["job"]["id"], CAMPAIGN_MANAGER))
    assert_mail_job(committed)

    assert committed["automation_piece_count"] == 5
    assert committed["retail_piece_count"] == 1
    assert committed["billable_piece_count"] == 6
    assert committed["presort_tier"] == "NO_PRESORT"


def test_settlement_builds_handling_subtotal_credit_and_amount_due_in_order(api):
    """PRD §3.7: "The handling fee is 250 cents of base charge plus eight percent
    of postage, with that percentage component rounded **up** to the next whole
    cent. The result is written to `handling_fee_cents`."
    PRD §3.7: "The volume credit is five percent of the subtotal, rounded **down**
    to the whole cent below, but only when the job carries at least 6 billable
    pieces; a job with 5 or fewer billable pieces earns no credit and the figure is
    0. The result is written to `volume_credit_cents`."
    PRD §3.7: "The amount due is the subtotal less the volume credit, and is
    written to `total_due_cents`."

    Design: Difficulty/combinatorial_formula/commit_settlement_pinned_evaluation_order
    """
    world = _household_marketing_job("scheduled")

    committed = validate_success(api.commit_mail_job(world["job"]["id"], CAMPAIGN_MANAGER))

    # postage 307; handling 250 + ceil(0.08 * 307 = 24.56) = 250 + 25 = 275;
    # subtotal 307 + 275 = 582; credit floor(0.05 * 582 = 29.1) = 29 on 6 pieces;
    # amount due 582 - 29 = 553.
    assert committed["final_postage_cents"] == 307
    assert committed["handling_fee_cents"] == 275
    assert committed["volume_credit_cents"] == 29
    assert committed["total_due_cents"] == 553


def test_the_commit_draw_lowers_the_escrow_by_exactly_the_amount_due(api):
    """PRD §3.7: "On success the server appends a `DRAW` ledger entry for
    `total_due_cents` attributed to this job and campaign, lowers
    `permit_balance_cents` by that amount, sets the job's `drawn_postage_cents` to
    the same figure, and recomputes the campaign's `committed_postage_cents`."
    PRD §2.8: "**Conservation invariant (postage money):** an account's
    `permit_balance_cents` equals the sum of its `TOPUP` amounts plus the sum of
    its `REFUND` amounts, minus the sum of its `DRAW` amounts and minus the sum of
    its `FORFEIT` amounts, over every ledger row belonging to that account."

    Design: Difficulty/combinatorial_formula/commit_settlement_pinned_evaluation_order
    """
    world = _household_marketing_job("scheduled")

    committed = validate_success(api.commit_mail_job(world["job"]["id"], CAMPAIGN_MANAGER))
    assert committed["drawn_postage_cents"] == 553

    account = read_account(world["account"]["id"])
    # 500000 seeded less the 553 drawn at commit.
    assert account["permit_balance_cents"] == 499_447
    assert account["lifetime_draw_cents"] == 553

    rows = ledger_rows(account_id=world["account"]["id"])
    assert_postage_money_conservation(account, rows)

    draws = [row for row in rows if row["entry_type"] == "DRAW"]
    assert len(draws) == 1
    assert_ledger_entry(draws[0])
    assert draws[0]["amount_cents"] == 553
    assert draws[0]["signed_amount_cents"] == -553
    assert draws[0]["campaign_id"] == world["campaign"]["id"]
    assert draws[0]["mail_job_id"] == world["job"]["id"]
    assert read_campaign(world["campaign"]["id"])["committed_postage_cents"] == 553


def test_exactly_five_eddm_pieces_commit_at_the_inclusive_lower_bound(api):
    """PRD §3.7: "For an EDDM job, the eligibility of its declared rate variant is
    re-checked at rung 33 and its total selected pieces must fall within 5 and 50
    inclusive at rung 34 — fewer than 5 pieces is not worth entering, more than 50
    exceeds what one job-day may carry — with a violation answering
    `ERR_EDDM_PIECE_BOUNDS` (HTTP 422)."
    PRD §3.4: "Otherwise the rate is 22.3 cents per piece under `SATURATION` and
    25.6 cents per piece under `HIGH_DENSITY_PLUS`, and the postage total is P
    multiplied by that rate, rounded half up to whole cents in a single step."

    Design: Difficulty/boundary_precision_check/eddm_piece_lower_bound_five_inclusive_versus_four
    """
    world = build_eddm_scenario(
        permit_number="PMT-142", stage="scheduled",
        routes=SATURATION_ROUTES_FIVE_PIECES, eddm_rate_variant="SATURATION",
    )

    committed = validate_success(api.commit_mail_job(world["job"]["id"], CAMPAIGN_MANAGER))

    assert committed["eddm_piece_count"] == 5
    assert committed["presort_tier"] == "EDDM_ROUTE"
    # 5 * 22.3 = 111.5 -> 112;  handling 250 + ceil(0.08 * 112 = 8.96) = 259;
    # subtotal 371; five billable pieces earn no credit; amount due 371.
    assert committed["final_postage_cents"] == 112
    assert committed["handling_fee_cents"] == 259
    assert committed["volume_credit_cents"] == 0
    assert committed["total_due_cents"] == 371
    assert read_account(world["account"]["id"])["permit_balance_cents"] == 499_629


def test_four_eddm_pieces_fall_below_the_inclusive_lower_bound(api):
    """PRD §3.7: "For an EDDM job, the eligibility of its declared rate variant is
    re-checked at rung 33 and its total selected pieces must fall within 5 and 50
    inclusive at rung 34 — fewer than 5 pieces is not worth entering, more than 50
    exceeds what one job-day may carry — with a violation answering
    `ERR_EDDM_PIECE_BOUNDS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/eddm_piece_lower_bound_five_inclusive_versus_four
    """
    world = build_eddm_scenario(
        permit_number="PMT-142B", stage="scheduled",
        routes=SATURATION_ROUTES_FOUR_PIECES, eddm_rate_variant="SATURATION",
        target_in_home_date="2026-06-16",
    )
    assert world["job"]["eddm_piece_count"] == 4

    response = api.commit_mail_job(world["job"]["id"], CAMPAIGN_MANAGER)
    validate_error(response, ApiErrorId.ERR_EDDM_PIECE_BOUNDS.value)

    job = read_mail_job(world["job"]["id"])
    assert job["status"] == "SCHEDULED"
    assert job["total_due_cents"] is None
    assert read_account(world["account"]["id"])["permit_balance_cents"] == 500_000


def test_voiding_a_committed_job_restores_the_permit_balance_exactly(api):
    """PRD §3.7: "A `REFUND` ledger entry is appended for exactly the job's
    `drawn_postage_cents` and the account's `permit_balance_cents` rises by
    precisely that amount, restoring the postage-money conservation invariant of
    §2.10."
    PRD §3.7: "The job's `drawn_postage_cents` is set to 0 and its
    `refunded_postage_cents` records the amount returned."
    PRD §2.10: "Voiding a committed job appends a `REFUND` row of precisely the
    amount that was drawn — no more, no less — and raises the balance by that same
    amount, restoring it to its pre-commit value when no other activity
    intervened."

    Design: Difficulty/compensating_invariant/void_job_restores_permit_balance_exactly
    """
    world = _single_piece_committed_job()
    # One automation piece at the 51.0-cent no-presort rate gives 51 cents of
    # postage; handling 250 + ceil(0.08 * 51 = 4.08) = 255; subtotal 306; a
    # single billable piece earns no credit, so the amount due is 306.
    assert world["job"]["total_due_cents"] == 306

    voided = validate_success(
        api.void_mail_job(world["job"]["id"], {"reason": "customer pulled the drop"},
                          CAMPAIGN_MANAGER)
    )
    assert voided["status"] == "DRAFT"
    assert voided["drawn_postage_cents"] == 0
    assert voided["refunded_postage_cents"] == 306
    assert voided["total_due_cents"] is None
    assert voided["mail_date"] is None

    account = read_account(world["account"]["id"])
    assert account["permit_balance_cents"] == 500_000
    assert account["lifetime_draw_cents"] == 306
    assert account["lifetime_refund_cents"] == 306
    assert_postage_money_conservation(account, ledger_rows(account_id=account["id"]))


def test_the_void_replays_to_a_zero_net_and_unqueues_the_recipient(api):
    """PRD §3.9: "Over every `PostageLedgerEntry` attributed to the campaign, read
    in `created_at` ascending order, it reports `draw_cents` as the sum of
    `amount_cents` on `DRAW` rows, `refund_cents` as the same sum over `REFUND`
    rows, `forfeit_cents` as the same over `FORFEIT` rows, and `row_count` as the
    number of rows considered."
    PRD §3.9: "`net_postage_cents` is the draws less the refunds plus the forfeits
    — money the campaign genuinely consumed."
    PRD §3.7: "Every `QUEUED` recipient record on the job returns to `NOT_MAILED`
    with `last_mail_job_id` cleared."

    Design: Difficulty/compensating_invariant/void_job_restores_permit_balance_exactly
    """
    world = _single_piece_committed_job()
    record = world["records"][0]
    assert read_list_record(record["id"])["mail_status"] == "QUEUED"

    validate_success(
        api.void_mail_job(world["job"]["id"], {"reason": "customer pulled the drop"},
                          CAMPAIGN_MANAGER)
    )

    report = validate_success(
        api.get_postage_reconciliation(world["campaign"]["id"], CAMPAIGN_MANAGER)
    )
    assert report["draw_cents"] == 306
    assert report["refund_cents"] == 306
    assert report["forfeit_cents"] == 0
    assert report["net_postage_cents"] == 0
    assert report["row_count"] == 2

    after = read_list_record(record["id"])
    assert after["mail_status"] == "NOT_MAILED"
    assert after["last_mail_job_id"] is None


def test_committing_a_draft_job_is_refused_by_the_mail_job_state_gate(api):
    """PRD §3.7: "Committing is the moment the job stops being a plan. A
    `CampaignManager` or `PlatformAdmin` commits a job in `SCHEDULED`, moving it
    `SCHEDULED → COMMITTED`, and the operation prices the job finally, draws money
    from the permit escrow, and queues the physical pieces."
    PRD §2.6: "17. The mail job's `status` permits the operation — otherwise
    `ERR_MAIL_JOB_INVALID_STATE`."

    Design: Corner/state_machines/commit_from_draft_returns_mail_job_invalid_state
    """
    world = build_addressed_scenario(
        permit_number="PMT-213", roster=SINGLE_RECORD_ROSTER, list_name="Mini List",
        dedupe_mode="EXACT", lock=True, stage="draft", topup_cents=None,
    )

    response = api.commit_mail_job(world["job"]["id"], CAMPAIGN_MANAGER)
    validate_error(response, ApiErrorId.ERR_MAIL_JOB_INVALID_STATE.value)

    job = read_mail_job(world["job"]["id"])
    assert job["status"] == "DRAFT"
    assert job["total_due_cents"] is None


def test_an_escrow_too_thin_for_the_amount_due_reports_payment_required(api):
    """PRD §3.7: "The account's `permit_balance_cents` must be at least
    `total_due_cents`; if it is not, the commit fails at rung 41 with
    `ERR_INSUFFICIENT_PERMIT_BALANCE` (HTTP 402), the lowest rung on the ladder and
    therefore the last complaint a request can earn."

    Design: Corner/validations/commit_without_enough_permit_balance_returns_payment_required
    """
    world = build_addressed_scenario(
        permit_number="PMT-242", roster=SINGLE_RECORD_ROSTER, list_name="Mini List",
        dedupe_mode="EXACT", lock=True, stage="scheduled", topup_cents=100,
    )

    response = api.commit_mail_job(world["job"]["id"], CAMPAIGN_MANAGER)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMIT_BALANCE.value)

    account = read_account(world["account"]["id"])
    # The single piece would have cost 306 cents against a 100-cent escrow.
    assert account["permit_balance_cents"] == 100
    assert account["lifetime_draw_cents"] == 0

    job = read_mail_job(world["job"]["id"])
    assert job["status"] == "SCHEDULED"
    assert job["drawn_postage_cents"] == 0

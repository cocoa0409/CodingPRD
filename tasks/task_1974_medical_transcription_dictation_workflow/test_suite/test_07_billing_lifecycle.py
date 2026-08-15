"""Billing periods, line items, SLA credits, disputes, and billing holds."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_clinic, add_sla_policy, setup_provider, setup_editor,
    setup_dual_basis_scenario, setup_breaching_stat_period,
    setup_period_with_delivered_job, setup_unsigned_delivered_transcripts,
    create_job, claim_job, submit_job, review_job, set_clock,
    get_job, get_provider, get_clinic, get_job_transcripts,
    get_period_line_items, create_billing_period_payload,
    create_dictation_job_payload, create_submit_payload,
    make_provider_headers, make_editor_headers, TEST_USERS,
    assert_billing_rollup_identity, TEXT_65_CHARS,
)

VENDOR = TEST_USERS["vendor_admin_headers"]
CLIENT = TEST_USERS["client_admin_headers"]


def test_tat_end_to_end_breach_vs_production_window_compliant(api):
    """PRD §3.9: "Under `END_TO_END`, the item breaches when the transcript's
    `delivered_at` is strictly after the job's `due_at`; delivery exactly at
    the deadline is not a breach. Under `PRODUCTION_WINDOW`, the item breaches
    when the elapsed time from the job's `first_claimed_at` to the accepted
    transcript's `submitted_at` strictly exceeds `tat_minutes`; again, exactly
    at the target is compliant."
    PRD §3.1: "`PRODUCTION_WINDOW` measures only the span from a job's
    first-ever claim to the final accepted submission, excluding queue wait
    entirely — the very same job data can be compliant under
    `PRODUCTION_WINDOW` while breaching under `END_TO_END`."

    Design: Difficulty/dual_variant_calc/tat_measurement_basis_divergence
    """
    fx = setup_dual_basis_scenario()
    li1 = get_period_line_items(fx["bp1"]["id"])[0]
    li2 = get_period_line_items(fx["bp2"]["id"])[0]
    assert li1["sla_breach"] is True, (
        "END_TO_END: delivered at T0+150m, strictly after due_at T0+120m")
    assert li2["sla_breach"] is False, (
        "PRODUCTION_WINDOW: submitted-first_claimed == 120 min, not > 120")


def test_tat_basis_divergence_changes_credit_amounts(api):
    """PRD §3.9: "A breaching item earns the clinic a credit: `credit_cents` is
    the item's `final_amount_cents` multiplied by the policy's
    `breach_credit_pct` percent, rounded half-up; a compliant item's credit is
    zero."
    PRD §3.9: "`final_line_count` is taken from the billed transcript's own
    `line_count` — the edited text, not the recognition estimate, so the two
    amounts diverge whenever the editor's text diverges from the machine draft
    — and `final_amount_cents` is that count times the snapshotted rate."

    Design: Difficulty/dual_variant_calc/tat_measurement_basis_divergence
    """
    fx = setup_dual_basis_scenario()
    li1 = get_period_line_items(fx["bp1"]["id"])[0]
    li2 = get_period_line_items(fx["bp2"]["id"])[0]
    # Identical delivered work: 65 visible chars -> 1 line x 20c.
    assert li1["final_amount_cents"] == 20
    assert li2["final_amount_cents"] == 20
    assert li1["credit_cents"] == 5, "round_half_up(20 * 25 / 100) == 5"
    assert li2["credit_cents"] == 0, (
        "same timestamps, different measurement basis, different money")


def test_provisional_amount_uses_asr_estimate(api):
    """PRD §3.9: "Each item records its containing `billing_period_id` and
    billed `transcript_id`, snapshots the job's `priority` and the policy's
    `rate_per_line_cents` as they stand at close, and computes provisional
    figures from the speech-recognition estimate: `provisional_line_count` is
    the job's `asr_char_estimate` divided into sixty-five-character lines,
    rounded up, and `provisional_amount_cents` is that count times the
    snapshotted rate."
    PRD §3.3: "the draft size estimate `asr_char_estimate` is exactly twice the
    `audio_duration_seconds`, at two characters per second of audio"

    Design: Difficulty/dual_variant_calc/provisional_vs_final_line_amount_divergence
    """
    fx = setup_period_with_delivered_job(audio_duration_seconds=40)
    assert fx["job"]["asr_char_estimate"] == 80, "40s * 2 chars/s"
    validate_success(api.close_billing_period(fx["period"]["id"], VENDOR))
    item = get_period_line_items(fx["period"]["id"])[0]
    assert item["status"] == "PROVISIONAL"
    assert item["provisional_line_count"] == 2, "ceil(80/65) == 2"
    assert item["provisional_amount_cents"] == 20


def test_final_amount_uses_edited_line_count(api):
    """PRD §3.9: "`final_line_count` is taken from the billed transcript's own
    `line_count` — the edited text, not the recognition estimate, so the two
    amounts diverge whenever the editor's text diverges from the machine draft
    — and `final_amount_cents` is that count times the snapshotted rate."
    PRD §3.9: "`gross_amount_cents` is the sum of all items'
    `final_amount_cents`, `credit_amount_cents` is the sum of the per-item
    credits, and `net_amount_cents` is gross minus credit, preserving the
    invariant that gross equals net plus credit."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_line_amount_divergence
    """
    fx = setup_period_with_delivered_job(audio_duration_seconds=40)
    validate_success(api.close_billing_period(fx["period"]["id"], VENDOR))
    validate_success(api.finalize_billing_period(fx["period"]["id"], VENDOR))
    item = get_period_line_items(fx["period"]["id"])[0]
    assert item["final_line_count"] == 1, "ceil(65/65) == 1"
    assert item["final_amount_cents"] == 10, (
        "provisional 20c vs final 10c for identical delivered work")
    assert item["credit_cents"] == 0
    period = validate_success(api.get_billing_period(fx["period"]["id"], VENDOR))
    assert period["net_amount_cents"] == 10
    assert_billing_rollup_identity(period)


def test_close_generates_provisional_items_with_rate_snapshot(api):
    """PRD §3.9: "The item starts in `PROVISIONAL` status, and its final fields
    — `final_line_count`, `final_amount_cents`, `sla_breach`, and `credit_cents`
    — stay null until finalize."
    PRD §3.9: "Each item records its containing `billing_period_id` and billed
    `transcript_id`, snapshots the job's `priority` and the policy's
    `rate_per_line_cents` as they stand at close, and computes provisional
    figures from the speech-recognition estimate: `provisional_line_count` is
    the job's `asr_char_estimate` divided into sixty-five-character lines,
    rounded up, and `provisional_amount_cents` is that count times the
    snapshotted rate."

    Design: Corner/calculations/close_generates_provisional_items_with_rate_snapshot
    """
    fx = setup_period_with_delivered_job(audio_duration_seconds=100)
    validate_success(api.close_billing_period(fx["period"]["id"], VENDOR))
    items = get_period_line_items(fx["period"]["id"])
    assert len(items) == 1
    item = items[0]
    assert item["status"] == "PROVISIONAL"
    assert item["priority"] == "ROUTINE"
    assert item["rate_per_line_cents"] == 10, "rate snapshot from the policy"
    assert item["provisional_line_count"] == 4, "ceil(200/65) == 4"
    assert item["provisional_amount_cents"] == 40
    assert item["final_line_count"] is None
    assert item["final_amount_cents"] is None
    assert item["sla_breach"] is None
    assert item["credit_cents"] is None


def test_period_membership_closed_interval_boundaries(api):
    """PRD §3.9: "the system generates one provisional line item per qualifying
    job: for each job, the latest transcript version whose `delivered_at` falls
    within the closed bounds of the period and whose status is `DELIVERED`,
    `SIGNED`, or `AMENDED`; a job with no such transcript contributes no item.
    Items are generated in job creation order, earliest `created_at` first, so
    that list reads are deterministic."
    PRD §2.9: "A billing period, by contrast, is a closed interval: both
    `period_start` and `period_end` are members, for overlap and for membership
    of delivered work alike."

    Design: Corner/calculations/period_membership_closed_interval_boundaries
    """
    wg_clinic = setup_clinic()
    add_sla_policy(wg_clinic["id"])
    provider = setup_provider(wg_clinic["id"])
    editor = setup_editor()
    # J1 delivered exactly at period_start (T0).
    j1 = create_job(provider)
    claim_job(j1["id"], editor)
    submit_job(j1["id"], editor)
    review_job(j1["id"], 0, 0, 0)
    # J2 delivered exactly at period_end (2026-08-02T00:00:00Z).
    set_clock("2026-08-01T00:00:01Z")
    j2 = create_job(provider)
    claim_job(j2["id"], editor)
    submit_job(j2["id"], editor)
    # J3 delivered one second past period_end.
    set_clock("2026-08-01T00:00:02Z")
    j3 = create_job(provider)
    claim_job(j3["id"], editor)
    submit_job(j3["id"], editor)
    set_clock("2026-08-02T00:00:00Z")
    review_job(j2["id"], 0, 0, 0)
    set_clock("2026-08-02T00:00:01Z")
    review_job(j3["id"], 0, 0, 0)
    t1 = get_job_transcripts(j1["id"])[0]
    t2 = get_job_transcripts(j2["id"])[0]

    period = validate_success(api.create_billing_period(
        create_billing_period_payload(
            wg_clinic["id"], period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-02T00:00:00Z"),
        VENDOR), 201)
    validate_success(api.close_billing_period(period["id"], VENDOR))
    items = get_period_line_items(period["id"])
    assert len(items) == 2, (
        "closed-interval membership: start and end instants both included")
    assert items[0]["transcript_id"] == t1["id"], (
        "job created_at ASC: J1's transcript first")
    assert items[1]["transcript_id"] == t2["id"]


def test_billing_period_state_gates_and_empty_close(api):
    """PRD §3.9: "A `VendorAdmin` closes an `OPEN` period — any other state
    yields `ERR_BILLING_PERIOD_NOT_OPEN` — and the system generates one
    provisional line item per qualifying job: for each job, the latest
    transcript version whose `delivered_at` falls within the closed bounds of
    the period and whose status is `DELIVERED`, `SIGNED`, or `AMENDED`; a job
    with no such transcript contributes no item."
    PRD §3.9: "A `VendorAdmin` finalizes a `CLOSED` period
    (`ERR_BILLING_PERIOD_NOT_CLOSED` otherwise), and each item is settled
    against reality: `final_line_count` is taken from the billed transcript's
    own `line_count` — the edited text, not the recognition estimate, so the
    two amounts diverge whenever the editor's text diverges from the machine
    draft — and `final_amount_cents` is that count times the snapshotted rate."
    PRD §3.9: "A `ClientAdmin` disputes a `FINALIZED` period — anything else
    yields `ERR_BILLING_PERIOD_NOT_FINALIZED` — moving it to `DISPUTED`."
    PRD §3.9: "Finally, a `VendorAdmin` settles a `FINALIZED` period
    (`ERR_BILLING_PERIOD_NOT_FINALIZED` otherwise), moving it to `SETTLED` —
    the terminal state — and recomputing the clinic's `billing_hold`, since a
    settled period never holds."

    Design: Corner/state_machines/billing_period_state_gates_and_empty_close
    """
    clinic = setup_clinic()
    period = validate_success(api.create_billing_period(
        create_billing_period_payload(clinic["id"]), VENDOR), 201)

    early_finalize = api.finalize_billing_period(period["id"], VENDOR)
    validate_error(early_finalize, ApiErrorId.ERR_BILLING_PERIOD_NOT_CLOSED)
    early_dispute = api.dispute_billing_period(period["id"], CLIENT)
    validate_error(early_dispute, ApiErrorId.ERR_BILLING_PERIOD_NOT_FINALIZED)

    validate_success(api.close_billing_period(period["id"], VENDOR))
    second_close = api.close_billing_period(period["id"], VENDOR)
    validate_error(second_close, ApiErrorId.ERR_BILLING_PERIOD_NOT_OPEN)

    finalized = validate_success(api.finalize_billing_period(period["id"], VENDOR))
    assert finalized["gross_amount_cents"] == 0, "empty-set rollup edge"
    assert finalized["credit_amount_cents"] == 0
    assert finalized["net_amount_cents"] == 0
    assert finalized["status"] == "FINALIZED"

    settled = validate_success(api.settle_billing_period(period["id"], VENDOR))
    assert settled["status"] == "SETTLED"
    late_dispute = api.dispute_billing_period(period["id"], CLIENT)
    validate_error(late_dispute, ApiErrorId.ERR_BILLING_PERIOD_NOT_FINALIZED)


def test_per_item_credit_rounded_half_up_before_sum(api):
    """PRD §3.9: "The rounding order at finalize is pinned and non-negotiable:
    round each item's credit half-up first, then sum. Summing first and
    rounding once is forbidden — two items of 105 cents each at a 10 percent
    credit yield 11 plus 11, totaling 22 cents, not the 21 that rounding a
    pooled 210-cent base would produce."

    Design: Difficulty/combinatorial_formula/per_item_credit_rounding_then_sum
    """
    fx = setup_breaching_stat_period(num_jobs=2, rate=35, pct=10)
    items = get_period_line_items(fx["period"]["id"])
    assert len(items) == 2
    for item in items:
        assert item["final_amount_cents"] == 105, "ceil(131/65)=3 lines x 35c"
        assert item["credit_cents"] == 11, "round_half_up(105 * 10 / 100) == 11"
    period = validate_success(api.get_billing_period(fx["period"]["id"], VENDOR))
    assert period["credit_amount_cents"] == 22, (
        "11 + 11; the pooled-rounding value 21 is forbidden")


def test_period_rollup_gross_net_identity(api):
    """PRD §3.9: "`gross_amount_cents` is the sum of all items'
    `final_amount_cents`, `credit_amount_cents` is the sum of the per-item
    credits, and `net_amount_cents` is gross minus credit, preserving the
    invariant that gross equals net plus credit."

    Design: Difficulty/combinatorial_formula/per_item_credit_rounding_then_sum
    """
    fx = setup_breaching_stat_period(num_jobs=2, rate=35, pct=10)
    period = validate_success(api.get_billing_period(fx["period"]["id"], VENDOR))
    assert period["gross_amount_cents"] == 210
    assert period["credit_amount_cents"] == 22
    assert period["net_amount_cents"] == 188
    assert_billing_rollup_identity(period)


def test_finalize_credit_identity_before_dispute(api):
    """PRD §3.9: "`gross_amount_cents` is the sum of all items'
    `final_amount_cents`, `credit_amount_cents` is the sum of the per-item
    credits, and `net_amount_cents` is gross minus credit, preserving the
    invariant that gross equals net plus credit. Every item moves to `FINAL`,
    the period moves to `FINALIZED`, `finalized_at` is stamped — and from that
    stamp the clinic's payment grace clock runs for the billing-hold
    evaluation, which is recomputed on subsequent sweeps."

    Design: Difficulty/compensating_invariant/dispute_reversal_conserves_gross_equals_net_plus_credit
    """
    fx = setup_breaching_stat_period(num_jobs=1, rate=35, pct=10)
    period = validate_success(api.get_billing_period(fx["period"]["id"], VENDOR))
    assert period["gross_amount_cents"] == 105
    assert period["credit_amount_cents"] == 11
    assert period["net_amount_cents"] == 94
    assert_billing_rollup_identity(period)  # 94 + 11 == 105
    assert period["status"] == "FINALIZED"
    item = get_period_line_items(fx["period"]["id"])[0]
    assert item["status"] == "FINAL"
    assert item["sla_breach"] is True


def test_dispute_reversal_restores_gross_net_identity(api):
    """PRD §3.9: "Under `REVERSED`, every item's `credit_cents` is zeroed,
    every item moves to `CREDIT_REVERSED`, the period's `credit_amount_cents`
    becomes zero, and `net_amount_cents` is set equal to `gross_amount_cents`,
    again returning the period to `FINALIZED`."

    Design: Difficulty/compensating_invariant/dispute_reversal_conserves_gross_equals_net_plus_credit
    """
    fx = setup_breaching_stat_period(num_jobs=1, rate=35, pct=10)
    validate_success(api.dispute_billing_period(fx["period"]["id"], CLIENT))
    resolved = validate_success(api.resolve_dispute_billing_period(
        fx["period"]["id"], {"outcome": "REVERSED"}, VENDOR))
    assert resolved["status"] == "FINALIZED"
    assert resolved["credit_amount_cents"] == 0
    assert resolved["net_amount_cents"] == 105
    assert resolved["gross_amount_cents"] == 105
    assert_billing_rollup_identity(resolved)  # 105 + 0 == 105
    item = get_period_line_items(fx["period"]["id"])[0]
    assert item["credit_cents"] == 0
    assert item["status"] == "CREDIT_REVERSED"
    assert item["final_amount_cents"] == 105, (
        "reversal never rewrites the work amount")


def test_resolve_dispute_on_finalized_returns_not_disputed(api):
    """PRD §3.9: "A `VendorAdmin` then resolves a `DISPUTED` period
    (`ERR_BILLING_PERIOD_NOT_DISPUTED` otherwise) by supplying an `outcome`."

    Design: Corner/errors/resolve_dispute_on_finalized_returns_not_disputed
    """
    clinic = setup_clinic()
    period = validate_success(api.create_billing_period(
        create_billing_period_payload(clinic["id"]), VENDOR), 201)
    validate_success(api.close_billing_period(period["id"], VENDOR))
    validate_success(api.finalize_billing_period(period["id"], VENDOR))
    resp = api.resolve_dispute_billing_period(period["id"], {"outcome": "UPHELD"},
                                              VENDOR)
    validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_NOT_DISPUTED)


def test_resolve_dispute_invalid_outcome_returns_invalid_request(api):
    """PRD §2.6: "Immediately after role authorization — and before any
    existence lookup — the request body schema is validated: required fields
    must be present, types must match, enum members must be valid, and numeric
    ranges must be respected (for example, `audio_duration_seconds` must be
    greater than zero, error counts must be non-negative, `tat_minutes` must be
    greater than zero, `breach_credit_pct` must lie within zero to one hundred
    inclusive, a dispute-resolution `outcome` must be `UPHELD` or `REVERSED`,
    and interval bounds must be parseable). Any schema failure yields
    `ERR_INVALID_REQUEST`."

    Design: Corner/errors/resolve_dispute_invalid_outcome_returns_invalid_request
    """
    clinic = setup_clinic()
    period = validate_success(api.create_billing_period(
        create_billing_period_payload(clinic["id"]), VENDOR), 201)
    validate_success(api.close_billing_period(period["id"], VENDOR))
    validate_success(api.finalize_billing_period(period["id"], VENDOR))
    validate_success(api.dispute_billing_period(period["id"], CLIENT))
    resp = api.resolve_dispute_billing_period(period["id"], {"outcome": "MAYBE"},
                                              VENDOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    current = validate_success(api.get_billing_period(period["id"], VENDOR))
    assert current["status"] == "DISPUTED"


def test_billing_hold_alone_blocks_upload_fiscal(api):
    """PRD §3.9: "`billing_hold` is true exactly when the clinic has a
    `FINALIZED` period whose payment window has lapsed — the current logical
    time at or after that period's `finalized_at` plus `payment_grace_days`
    days, each day counted as 86,400 seconds, with the exact boundary counting
    as overdue. Periods in `OPEN`, `CLOSED`, `DISPUTED`, or `SETTLED` never
    contribute to a hold."
    PRD §3.3: "A clinic under billing hold is likewise closed for new
    dictations, rejected with `ERR_CLINIC_BILLING_HOLD`."

    Design: Corner/validations/billing_hold_alone_blocks_upload_fiscal
    """
    clinic = setup_clinic()
    add_sla_policy(clinic["id"])
    provider = setup_provider(clinic["id"])
    period = validate_success(api.create_billing_period(
        create_billing_period_payload(
            clinic["id"], period_start="2026-07-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z"),
        VENDOR), 201)
    validate_success(api.close_billing_period(period["id"], VENDOR))
    validate_success(api.finalize_billing_period(period["id"], VENDOR))
    # finalized_at == T0; grace 14 days -> hold from 2026-08-15T00:00:00Z.
    set_clock("2026-08-14T23:59:59Z")
    assert get_clinic(clinic["id"])["billing_hold"] is False, (
        "one second before the grace boundary")
    set_clock("2026-08-15T00:00:00Z")
    assert get_clinic(clinic["id"])["billing_hold"] is True, (
        "the exact boundary counts as overdue")
    resp = api.create_dictation_job(
        create_dictation_job_payload(provider["id"]),
        make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_CLINIC_BILLING_HOLD)


def test_suspended_provider_upload_error_beats_billing_hold(api):
    """PRD §2.6: "Resource-state preconditions follow — the job, transcript,
    editor, provider, or billing period must be in the state its action
    requires — and the relevant failures are the `ERR_JOB_NOT_QUEUED`,
    `ERR_JOB_NOT_EDITING`, `ERR_JOB_NOT_SUBMITTED`, `ERR_JOB_NOT_CANCELLABLE`,
    `ERR_TRANSCRIPT_NOT_DELIVERED`, `ERR_TRANSCRIPT_NOT_SIGNED`,
    `ERR_PROVIDER_SUSPENDED`, `ERR_EDITOR_NOT_ACTIVE`,
    `ERR_BILLING_PERIOD_NOT_OPEN`, `ERR_BILLING_PERIOD_NOT_CLOSED`,
    `ERR_BILLING_PERIOD_NOT_FINALIZED`, `ERR_BILLING_PERIOD_NOT_DISPUTED`, and
    `ERR_UNSIGNED_REPORTS_REMAIN` family."
    PRD §2.6: "The fiscal gate — a clinic under billing hold may not upload new
    dictations — is evaluated last among them and yields
    `ERR_CLINIC_BILLING_HOLD`."

    Design: Difficulty/priority_pair_validation_conflict/provider_suspended_state_beats_billing_hold_fiscal
    """
    fx = setup_unsigned_delivered_transcripts(n=3, with_billing_period=True)
    set_clock("2026-08-16T00:00:00Z")
    # Both failure conditions hold simultaneously.
    assert get_provider(fx["provider"]["id"])["status"] == "SUSPENDED"
    assert get_clinic(fx["clinic"]["id"])["billing_hold"] is True
    resp = api.create_dictation_job(
        create_dictation_job_payload(fx["provider"]["id"]),
        make_provider_headers(fx["provider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PROVIDER_SUSPENDED)


def test_dual_failure_upload_creates_no_job(api):
    """PRD §3.3: "A provider whose `status` is `SUSPENDED` cannot upload at all
    and is rejected with `ERR_PROVIDER_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/provider_suspended_state_beats_billing_hold_fiscal
    """
    fx = setup_unsigned_delivered_transcripts(n=3, with_billing_period=True)
    set_clock("2026-08-16T00:00:00Z")
    resp = api.create_dictation_job(
        create_dictation_job_payload(fx["provider"]["id"]),
        make_provider_headers(fx["provider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PROVIDER_SUSPENDED)
    jobs, meta = validate_paginated(api.list_dictation_jobs(
        VENDOR, params={"provider_id": fx["provider"]["id"]}))
    assert meta["total_count"] == 3, (
        "the rejected upload created no job — only the three originals remain")

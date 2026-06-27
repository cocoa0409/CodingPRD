"""Second-angle coverage for the depth (difficulty) instances: complementary
boundary values, complementary side-effects, and distinct jurisdictions/tiers
that re-exercise each load-bearing rule from a different observable.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_confirmed_reporter_job,
    setup_insession_realtime_job,
    setup_certified_transcript,
    setup_read_sign_open_transcript,
    setup_adjourned_reporter_job,
    setup_delivered_transcript,
    setup_issued_invoice,
    run_session,
    set_clock,
    adjourn_job,
    cancel_job,
    order_transcript,
    deliver_rough,
    certify,
    open_read_sign,
    file_errata,
    create_invoice,
    issue_invoice,
    make_attorney,
    make_case,
    make_reporter,
    make_videographer,
    make_job,
    add_assignment,
    current_job_version,
    make_schedule_coordinator_headers,
    make_billing_clerk_headers,
    make_attorney_headers,
    make_reporter_headers,
    create_transcript_order_payload,
)

COORD = make_schedule_coordinator_headers()
BILLING = make_billing_clerk_headers()


# --- combinatorial_formula / appearance_fee_nonlinear_min_ceil_surcharge_mode_a ---
def test_appearance_fee_ceil_partial_hour_with_surcharge(api):
    """PRD §3.6: "take the elapsed time in whole minutes, divide by sixty, and
    round that quotient up to the next whole hour for any partial hour, then take
    whichever is larger of that figure and a two-hour minimum." PRD §3.6: "when
    the assignment's role is `REPORTER` and the job requires real-time, the base
    is increased by twenty percent — the base multiplied by 1.20, with that
    product rounded half up to the nearest cent." A 130-min realtime session
    @15000: ceil(130/60)=3h, base 45000, *1.20=54000.

    Design: Difficulty/combinatorial_formula/appearance_fee_nonlinear_min_ceil_surcharge_mode_a
    """
    sc = setup_insession_realtime_job(
        hourly_appearance_cents=15000,
        scheduled_start="2026-08-20T09:00:00Z",
        scheduled_end="2026-08-20T13:00:00Z",
        session_start="2026-08-20T09:00:00Z")
    set_clock("2026-08-20T11:10:00Z")  # 130 minutes elapsed
    adjourn_job(sc.job_id)
    asg = validate_success(api.get_assignment(sc.assignment_id, BILLING))
    assert asg["appearance_fee_cents"] == 54000, (
        f"130-min realtime @15000 (3h*1.20) should be 54000, got "
        f"{asg['appearance_fee_cents']}")


# --- combinatorial_formula / page_charge_tiered_then_multiplier_then_flat_mode_c ---
def test_page_charge_three_tier_federal_expedite3_certified(api):
    """PRD §3.11: "The per-tier marginal rate is rounded to a whole cent **before**
    it is multiplied by that tier's page count, and the three tier products are
    then summed to form the page base." PRD §3.11: "The expedite multiplier is
    applied **after** the tier sum... Last, and only if the order is a certified
    copy, a flat certification fee of 2500 cents is **added after** the
    multiplier." FEDERAL 200 pages EXPEDITE_3 certified: 50*380 + 100*342 +
    50*304 = 19000+34200+15200 = 68400; *2.00=136800; +2500=139300.

    Design: Difficulty/combinatorial_formula/page_charge_tiered_then_multiplier_then_flat_mode_c
    """
    sc, inv = setup_issued_invoice(
        jurisdiction="FEDERAL", turnaround_tier="EXPEDITE_3",
        certified_copy=True, final_pages=200, estimated_pages=200)
    assert inv["page_subtotal_cents"] == 139300, (
        f"FEDERAL 200p EXPEDITE_3 cert page_subtotal should be 139300, got "
        f"{inv['page_subtotal_cents']}")


# --- boundary_precision_check / page_tier_boundary_50_vs_51 ---
def test_page_tier_boundary_50_pages_tier1_only_difficulty(api):
    """PRD §3.11: "The first 50 pages are charged at the full base rate." PRD
    §3.11: "the first tier covers up to 50 pages, the second tier covers the count
    of pages above 50 up to 150 (zero if there are 50 or fewer)." STATE_TX exactly
    50 STANDARD certified: 50*300=15000; *1.0; +2500=17500 (no tier-2 page),
    pairing the 51-page crossing on the same metric.

    Design: Difficulty/boundary_precision_check/page_tier_boundary_50_vs_51_on_invoice_issue
    """
    sc, inv = setup_issued_invoice(
        jurisdiction="STATE_TX", turnaround_tier="STANDARD",
        certified_copy=True, final_pages=50, estimated_pages=50)
    assert inv["page_subtotal_cents"] == 17500, (
        f"TX 50p STANDARD cert page_subtotal should be 17500 (tier-1 only), got "
        f"{inv['page_subtotal_cents']}")


# --- cross_entity_state_dependency / transcript_order_requires_job_adjourned ---
def test_transcript_order_on_adjourned_job_succeeds(api):
    """PRD §3.8: "The order is only valid when the referenced job's status is
    `ADJOURNED`." The positive side of the gate: ordering against an ADJOURNED job
    is accepted and the order starts ORDERED.

    Design: Difficulty/cross_entity_state_dependency/transcript_order_requires_job_adjourned
    """
    sc = setup_adjourned_reporter_job(
        scheduled_start="2026-06-19T09:00:00Z",
        scheduled_end="2026-06-19T11:00:00Z")
    resp = api.create_transcript_order(create_transcript_order_payload(
        job_id=sc.job_id, ordering_attorney_id=sc.attorney_id,
        turnaround_tier="STANDARD", certified_copy=True, estimated_pages=30),
        make_attorney_headers(sc.attorney_id))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ORDERED", (
        f"order on adjourned job should be ORDERED, got {data['status']}")


# --- cross_entity_state_dependency / rough_deliver_requires_reporter_completed_assignment ---
def test_deliver_rough_by_covering_reporter_succeeds(api):
    """PRD §3.8: "A `Reporter` who covered the order's job — that is, who holds a
    `COMPLETED` reporter assignment on that job — first delivers the rough draft,
    advancing the order from `ORDERED` to `ROUGH_DELIVERED`." The covering reporter
    can deliver the rough.

    Design: Difficulty/cross_entity_state_dependency/rough_deliver_requires_reporter_completed_assignment
    """
    sc = setup_adjourned_reporter_job(
        scheduled_start="2026-06-20T09:00:00Z",
        scheduled_end="2026-06-20T11:00:00Z")
    order_transcript(sc, turnaround_tier="STANDARD", certified_copy=True,
                     estimated_pages=30)
    resp = api.deliver_rough(sc.transcript_order_id, make_reporter_headers(sc.reporter_id))
    data = validate_success(resp)
    assert data["status"] == "ROUGH_DELIVERED", (
        f"covering reporter should advance to ROUGH_DELIVERED, got {data['status']}")


# --- non_linear_state_machine / transcript_read_sign_errata_cycle_multiple_rounds ---
def test_read_sign_errata_first_round_then_sign(api):
    """PRD §3.10: "Filing creates the errata sheet, stamping its `round` to the
    transcript's current `errata_round` plus one, increments the transcript's
    `errata_round` by one, and moves the order to `ERRATA_FILED`." PRD §3.10: "an
    `Attorney` who is a case party signs, advancing a `READ_SIGN_OPEN` order to
    `SIGNED`." After one errata round (errata_round 1), re-open and sign closes the
    cycle at SIGNED.

    Design: Difficulty/non_linear_state_machine/transcript_read_sign_errata_cycle_multiple_rounds
    """
    sc, _ = setup_read_sign_open_transcript(
        jurisdiction="STATE_CA", turnaround_tier="STANDARD",
        certified_copy=True, estimated_pages=30, final_pages=30)
    file_errata(sc, corrections=[{"page": 1, "line": 1, "from_text": "a", "to_text": "b"}],
                reason="round 1")
    to = validate_success(api.get_transcript_order(sc.transcript_order_id, COORD))
    assert to["errata_round"] == 1, f"after first errata, round should be 1, got {to['errata_round']}"
    open_read_sign(sc)
    signed = validate_success(api.sign_transcript(
        sc.transcript_order_id, make_attorney_headers(sc.attorney_id)))
    assert signed["status"] == "SIGNED", (
        f"re-open then sign should reach SIGNED, got {signed['status']}")


# --- transitive_cascade / adjourn_cascade_completes_assignment_then_computes_fee_depth3 ---
def test_adjourn_cascade_three_hour_session_prices_to_30000(api):
    """PRD §3.5: "first, every `ACTIVE` assignment on the job transitions to
    `COMPLETED`; second, each newly completed assignment has its
    `appearance_fee_cents` computed from the job's `actual_start` and
    `actual_end`." A 3-hour actual reporter session @10000 cascades to COMPLETED +
    30000.

    Design: Difficulty/transitive_cascade/adjourn_cascade_completes_assignment_then_computes_fee_depth3
    """
    sc = setup_confirmed_reporter_job(
        scheduled_start="2026-06-21T09:00:00Z",
        scheduled_end="2026-06-21T13:00:00Z",
        hourly_appearance_cents=10000)
    run_session(sc.job_id, "2026-06-21T09:00:00Z", "2026-06-21T12:00:00Z")
    asg = validate_success(api.get_assignment(sc.assignment_id, BILLING))
    assert asg["status"] == "COMPLETED", (
        f"3h session should complete the assignment, got {asg['status']}")
    assert asg["appearance_fee_cents"] == 30000, (
        f"3h @10000 cascade fee should be 30000, got {asg['appearance_fee_cents']}")


# --- transitive_cascade / cancel_cascade_releases_assignment_then_reverts_posture_depth2 ---
def test_cancel_cascade_from_noticed_releases_and_unstaffs(api):
    """PRD §3.5: "Cancellation moves the job to `CANCELLED`, cascades every
    `ACTIVE` assignment on the job to `RELEASED`... recomputes the staffing posture
    down to `UNSTAFFED`." Cancelling a still-NOTICED job (one ACTIVE reporter)
    releases the assignment and reverts posture to UNSTAFFED.

    Design: Difficulty/transitive_cascade/cancel_cascade_releases_assignment_then_reverts_posture_depth2
    """
    att = make_attorney()
    case = make_case(att["id"])
    rep = make_reporter(certifications=["CSR_CA"])
    job = make_job(case["id"], scheduled_start="2026-06-22T09:00:00Z",
                   scheduled_end="2026-06-22T11:00:00Z")
    asg = add_assignment(job["id"], rep["id"], "REPORTER")
    cancel_job(job["id"])
    refreshed = validate_success(api.get_job(job["id"], COORD))
    released = validate_success(api.get_assignment(asg["id"], COORD))
    assert refreshed["status"] == "CANCELLED", (
        f"job should be CANCELLED, got {refreshed['status']}")
    assert refreshed["staffing_posture"] == "UNSTAFFED", (
        f"posture should revert to UNSTAFFED, got {refreshed['staffing_posture']}")
    assert released["status"] == "RELEASED", (
        f"assignment should be RELEASED, got {released['status']}")


# --- resource_temporal_overlap / half_open_overlap_on_any_resource_kind ---
def test_touching_windows_do_not_overlap_allowed(api):
    """PRD §3.3: "Because the windows are half-open, two jobs that merely touch —
    one ending at exactly the instant the next begins — do not overlap and are
    permitted." A videographer ending 12:00 may take a job starting 12:00.

    Design: Difficulty/resource_temporal_overlap/half_open_overlap_on_any_resource_kind
    """
    att = make_attorney()
    case = make_case(att["id"])
    vid = make_videographer()
    j1 = make_job(case["id"], scheduled_start="2026-06-23T09:00:00Z",
                  scheduled_end="2026-06-23T12:00:00Z", requires_videographer=True)
    add_assignment(j1["id"], vid["id"], "VIDEOGRAPHER")
    j2 = make_job(case["id"], scheduled_start="2026-06-23T12:00:00Z",
                  scheduled_end="2026-06-23T14:00:00Z", requires_videographer=True)
    resp = api.create_assignment(j2["id"], {
        "resource_id": vid["id"], "role": "VIDEOGRAPHER",
        "expected_job_version": j2["version"]}, COORD)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE", (
        f"touching-window videographer assignment should be ACTIVE, got {data['status']}")


# --- resource_temporal_overlap / reporter_buffer_interval_semantics_distinct_from_plain_overlap ---
def test_videographer_15_min_gap_allowed_no_buffer_rule(api):
    """PRD §3.3: "This buffer applies only to reporter assignments; videographers
    and interpreters are subject only to the overlap rule." A videographer with a
    15-minute gap (no overlap) is accepted — the 30-min buffer is reporter-only,
    distinguishing the two interval semantics.

    Design: Difficulty/resource_temporal_overlap/reporter_buffer_interval_semantics_distinct_from_plain_overlap
    """
    att = make_attorney()
    case = make_case(att["id"])
    vid = make_videographer()
    j1 = make_job(case["id"], scheduled_start="2026-06-24T09:00:00Z",
                  scheduled_end="2026-06-24T12:00:00Z", requires_videographer=True)
    add_assignment(j1["id"], vid["id"], "VIDEOGRAPHER")
    j2 = make_job(case["id"], scheduled_start="2026-06-24T12:15:00Z",
                  scheduled_end="2026-06-24T14:00:00Z", requires_videographer=True)
    resp = api.create_assignment(j2["id"], {
        "resource_id": vid["id"], "role": "VIDEOGRAPHER",
        "expected_job_version": j2["version"]}, COORD)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE", (
        f"videographer 15-min gap (no buffer rule) should be ACTIVE, got {data['status']}")


# --- compensating_invariant / release_then_reassign_conserves_reporter_role_count ---
def test_release_drops_posture_then_reassign_restores_ready(api):
    """PRD §3.3: "triggers a recomputation of the parent job's staffing posture,
    which may drop the job from `READY` back to `PARTIAL`." PRD §3.4: "If no
    required role is covered at all, the posture is `UNSTAFFED`." Releasing the
    sole reporter drops the reporter-only job to UNSTAFFED; re-assigning restores
    READY — the role count returns to one.

    Design: Difficulty/compensating_invariant/release_then_reassign_conserves_reporter_role_count
    """
    att = make_attorney()
    case = make_case(att["id"])
    rep1 = make_reporter(full_name="Rep HH", certifications=["CSR_CA"])
    rep2 = make_reporter(full_name="Rep II", certifications=["CSR_CA"])
    job = make_job(case["id"], scheduled_start="2026-06-25T09:00:00Z",
                   scheduled_end="2026-06-25T11:00:00Z")
    asg1 = add_assignment(job["id"], rep1["id"], "REPORTER")
    validate_success(api.release_assignment(asg1["id"], COORD))
    dropped = validate_success(api.get_job(job["id"], COORD))
    assert dropped["staffing_posture"] == "UNSTAFFED", (
        f"after releasing sole reporter posture should be UNSTAFFED, got "
        f"{dropped['staffing_posture']}")
    add_assignment(job["id"], rep2["id"], "REPORTER")
    restored = validate_success(api.get_job(job["id"], COORD))
    assert restored["staffing_posture"] == "READY", (
        f"after re-assigning posture should be READY, got {restored['staffing_posture']}")
    rows, _ = validate_paginated(
        api.list_job_assignments(job["id"], COORD, params={"status": "ACTIVE"}))
    assert sum(1 for a in rows if a["role"] == "REPORTER") == 1, (
        "exactly one ACTIVE REPORTER should remain after the compensating reassign")


# --- compensating_invariant / void_then_recreate_conserves_invoice_total_cents ---
def test_void_recreate_reporter_only_conserves_total(api):
    """PRD §3.14: "On issue, all three subtotals and the grand total are recomputed
    and frozen from current job, transcript, and exhibit state." PRD §3.14: "An
    invoice can also be voided from either `DRAFT` or `ISSUED`." Voiding a
    reporter-only STATE_CA 30-page DAILY issued invoice and issuing a fresh one for
    the same job/transcript yields an identical total (2h@10000=20000 +
    page 31750 = 51750).

    Design: Difficulty/compensating_invariant/void_then_recreate_conserves_invoice_total_cents
    """
    sc, inv1 = setup_issued_invoice(
        jurisdiction="STATE_CA", turnaround_tier="DAILY",
        certified_copy=True, final_pages=30, estimated_pages=30,
        hourly_appearance_cents=10000)
    assert inv1["total_cents"] == 51750, (
        f"first invoice total should be 51750, got {inv1['total_cents']}")
    validate_success(api.void_invoice(inv1["id"], BILLING))
    create_invoice(sc)
    inv2 = issue_invoice(sc)
    assert inv2["total_cents"] == 51750, (
        f"recreated invoice total should match at 51750, got {inv2['total_cents']}")

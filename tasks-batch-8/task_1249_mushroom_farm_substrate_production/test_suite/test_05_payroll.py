"""Piece-rate labor: logging, approval, dispute, payout, segregation of duties."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_worker,
    create_worker_and_log_piece,
    get_success_data,
    grade_flush,
    log_piece_payload,
    make_harvest_crew_lead_headers,
    record_flush_on_cycle,
    setup_fruiting_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

FARM = TEST_USERS["farm_manager_headers"]
GRADING = TEST_USERS["grading_inspector_headers"]
PAYROLL = TEST_USERS["payroll_clerk_headers"]
ANY = TEST_USERS["any_headers"]


def test_piece_approval_requires_graded_flush(api):
    """PRD §3.4: "Approving requires the piece to be `LOGGED` or `DISPUTED`
    (otherwise `ERR_PIECE_INVALID_STATE`) and the parent flush to be `GRADED`
    (otherwise `ERR_FLUSH_NOT_GRADED`)."

    While the flush is RECORDED the approve is rejected; after grading the
    same call succeeds.

    Design: Difficulty/cross_entity_state_dependency/piece_approval_requires_graded_flush
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    worker, piece = create_worker_and_log_piece(flush, kg_picked=40.0, rate=50)

    rejected = api.approve_piece(piece["id"], PAYROLL)
    validate_error(rejected, ApiErrorId.ERR_FLUSH_NOT_GRADED)

    grade_flush(flush, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)

    ok = api.approve_piece(piece["id"], PAYROLL)
    approved = validate_success(ok, expected_status=200)
    assert approved["status"] == "APPROVED"
    assert approved["final_pay_cents"] == 2040


def test_piece_approval_blocked_until_flush_graded(api):
    """PRD §3.4: "the parent flush [must be] `GRADED` (otherwise
    `ERR_FLUSH_NOT_GRADED`)."

    Design: Difficulty/cross_entity_state_dependency/piece_approval_requires_graded_flush
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    _worker, piece = create_worker_and_log_piece(flush, kg_picked=40.0, rate=50)

    # Cross-entity gate: parent flush is RECORDED -> approve fails.
    rejected = api.approve_piece(piece["id"], PAYROLL)
    validate_error(rejected, ApiErrorId.ERR_FLUSH_NOT_GRADED)

    piece_after = get_success_data(api.get_piece(piece["id"], ANY))
    assert piece_after["status"] == "LOGGED"


def test_piece_pay_provisional_vs_final_divergence(api):
    """PRD §3.4: "The system ... computes `provisional_pay_cents` as the flat
    figure `kg_picked` times `rate_cents_per_kg` rounded half-up to whole
    cents."
    PRD §3.4: "Approval computes `final_pay_cents` using the parent flush's
    grade shares: the piece earns `kg_picked` times `rate_cents_per_kg` times
    a weighting factor of 1.20 times the grade-A share (the flush's
    `grade_a_kg` divided by its `total_kg`), plus 1.00 times the grade-B
    share, plus 0.0 times the cull share, with the whole result rounded
    half-up to whole cents at that moment. For a piece of 40.0 kg at a rate
    of 50 cents per kilogram on a flush graded 60% A, 30% B, 10% cull, the
    factor is 1.02: the provisional figure at logging was 2000 cents, and the
    final figure at approval is 2040 cents. Approval moves the piece to
    `APPROVED` and adds `final_pay_cents` to the worker's
    `accrued_unpaid_cents`."

    Design: Difficulty/dual_variant_calc/piece_pay_provisional_vs_final_divergence
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    worker, piece = create_worker_and_log_piece(flush, kg_picked=40.0, rate=50)

    # Provisional: 40.0 * 50 = 2000 (flat, no grade weighting).
    piece_mid = get_success_data(api.get_piece(piece["id"], ANY))
    assert piece_mid["provisional_pay_cents"] == 2000
    assert piece_mid["final_pay_cents"] is None

    grade_flush(flush, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)
    get_success_data(api.approve_piece(piece["id"], PAYROLL))

    piece_after = get_success_data(api.get_piece(piece["id"], ANY))
    assert piece_after["status"] == "APPROVED"
    assert piece_after["provisional_pay_cents"] == 2000
    # 40.0 * 50 * (1.20*0.6 + 1.00*0.3 + 0.0*0.1) = 2000 * 1.02 = 2040.
    assert piece_after["final_pay_cents"] == 2040
    assert piece_after["provisional_pay_cents"] != piece_after["final_pay_cents"]

    worker_after = get_success_data(api.get_worker(worker["id"], ANY))
    assert worker_after["accrued_unpaid_cents"] == 2040


def test_piece_pay_provisional_is_flat_rate(api):
    """PRD §3.4: "computes `provisional_pay_cents` as the flat figure
    `kg_picked` times `rate_cents_per_kg` rounded half-up to whole cents" —
    provisional pay applies NO grade weighting even though the flush is later
    graded.

    Design: Difficulty/dual_variant_calc/piece_pay_provisional_vs_final_divergence
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    worker, piece = create_worker_and_log_piece(flush, kg_picked=40.0, rate=50)
    assert piece["provisional_pay_cents"] == 2000
    grade_flush(flush, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)
    get_success_data(api.approve_piece(piece["id"], PAYROLL))
    after = get_success_data(api.get_piece(piece["id"], ANY))
    # Provisional remains the flat figure; final is grade-weighted.
    assert after["provisional_pay_cents"] == 2000
    assert after["final_pay_cents"] == 2040


def test_payroll_per_piece_rounding_then_sum(api):
    """PRD §2.7: "Payroll rounding is pinned per piece: each piece's pay is
    rounded to whole cents at the moment it is computed — at logging for the
    provisional figure and at approval for the final figure — and worker
    accruals and payouts sum those already-rounded per-piece cent values. The
    system never rounds after summation."

    Two 10.15 kg pieces at 33 cents/kg under factor 1.02: each rounds to
    round_half_up(341.649) = 342; the accrual is 342 + 342 = 684, not the
    sum-then-round 683.

    Design: Difficulty/combinatorial_formula/payroll_per_piece_rounding_then_sum
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    worker = create_worker(piece_rate_cents_per_kg=33)
    headers = make_harvest_crew_lead_headers(worker["id"])
    p1 = get_success_data(api.log_piece(
        flush["id"], log_piece_payload(worker_id=worker["id"], kg_picked=10.15), headers,
    ))
    p2 = get_success_data(api.log_piece(
        flush["id"], log_piece_payload(worker_id=worker["id"], kg_picked=10.15), headers,
    ))
    grade_flush(flush, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)

    get_success_data(api.approve_piece(p1["id"], PAYROLL))
    get_success_data(api.approve_piece(p2["id"], PAYROLL))

    p1_after = get_success_data(api.get_piece(p1["id"], ANY))
    p2_after = get_success_data(api.get_piece(p2["id"], ANY))
    # round_half_up(10.15 * 33 * 1.02) = round_half_up(341.649) = 342.
    assert p1_after["final_pay_cents"] == 342
    assert p2_after["final_pay_cents"] == 342

    worker_after = get_success_data(api.get_worker(worker["id"], ANY))
    assert worker_after["accrued_unpaid_cents"] == 684, (
        "accrual must sum the already-rounded per-piece values (342+342=684), "
        "never round after summation (which would yield 683)"
    )


def test_payroll_per_piece_rounding_distinct_from_sum_then_round(api):
    """PRD §2.7: "worker accruals and payouts sum those already-rounded
    per-piece cent values. The system never rounds after summation."

    Design: Difficulty/combinatorial_formula/payroll_per_piece_rounding_then_sum
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    worker = create_worker(piece_rate_cents_per_kg=33)
    headers = make_harvest_crew_lead_headers(worker["id"])
    pieces = [
        get_success_data(api.log_piece(
            flush["id"],
            log_piece_payload(worker_id=worker["id"], kg_picked=10.15),
            headers,
        ))
        for _ in range(2)
    ]
    grade_flush(flush, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)
    for p in pieces:
        get_success_data(api.approve_piece(p["id"], PAYROLL))
    for p in pieces:
        after = get_success_data(api.get_piece(p["id"], ANY))
        assert after["final_pay_cents"] == 342
    worker_after = get_success_data(api.get_worker(worker["id"], ANY))
    assert worker_after["accrued_unpaid_cents"] == 2 * 342


def test_payroll_accrual_approve_dispute_conservation(api):
    """PRD §3.4: "Disputing moves the piece to `DISPUTED` and subtracts its
    `final_pay_cents` from the worker's `accrued_unpaid_cents`, exactly
    reversing the approval; the `final_pay_cents` value itself is retained on
    the piece for audit. Approve-then-dispute therefore returns the accrual
    to its prior value exactly."

    Design: Difficulty/compensating_invariant/payroll_accrual_approve_dispute_conservation
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    # PRD §3.4: pieces are logged on a RECORDED flush; grading comes after.
    worker, piece = create_worker_and_log_piece(flush, kg_picked=40.0, rate=50)
    grade_flush(flush, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)

    get_success_data(api.approve_piece(piece["id"], PAYROLL))
    mid = get_success_data(api.get_worker(worker["id"], ANY))
    assert mid["accrued_unpaid_cents"] == 2040

    get_success_data(api.dispute_piece(piece["id"], PAYROLL))
    end = get_success_data(api.get_worker(worker["id"], ANY))
    assert end["accrued_unpaid_cents"] == 0, (
        "approve-then-dispute is a compensating pair with zero cent of drift"
    )
    assert end["lifetime_paid_cents"] == 0, "nothing was ever paid out"

    piece_after = get_success_data(api.get_piece(piece["id"], ANY))
    assert piece_after["status"] == "DISPUTED"
    assert piece_after["final_pay_cents"] == 2040, "final_pay_cents is retained for audit"


def test_payroll_accrual_conserves_across_approve_dispute(api):
    """PRD §3.4: "Approve-then-dispute therefore returns the accrual to its
    prior value exactly."

    Design: Difficulty/compensating_invariant/payroll_accrual_approve_dispute_conservation
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    # PRD §3.4: pieces are logged on a RECORDED flush; grading comes after.
    worker, piece = create_worker_and_log_piece(flush, kg_picked=40.0, rate=50)
    grade_flush(flush, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)
    initial = get_success_data(api.get_worker(worker["id"], ANY))["accrued_unpaid_cents"]

    get_success_data(api.approve_piece(piece["id"], PAYROLL))
    get_success_data(api.dispute_piece(piece["id"], PAYROLL))

    end = get_success_data(api.get_worker(worker["id"], ANY))
    assert end["accrued_unpaid_cents"] == initial


def test_piece_dispute_from_logged_rejected(api):
    """PRD §3.4: "A `PayrollClerk` may dispute an `APPROVED` piece (from any
    other state, `ERR_PIECE_INVALID_STATE`)."

    Design: Corner/state_machines/piece_dispute_from_logged_rejected
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    worker, piece = create_worker_and_log_piece(flush, kg_picked=40.0, rate=50)

    resp = api.dispute_piece(piece["id"], PAYROLL)
    validate_error(resp, ApiErrorId.ERR_PIECE_INVALID_STATE)
    piece_after = get_success_data(api.get_piece(piece["id"], ANY))
    assert piece_after["status"] == "LOGGED"
    worker_after = get_success_data(api.get_worker(worker["id"], ANY))
    assert worker_after["accrued_unpaid_cents"] == 0


def test_piece_approve_by_logger_rejected_sod(api):
    """PRD §3.4: "the clerk's `X-User-ID` must differ from the piece's
    `logged_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.1: "they may never approve or dispute a piece whose
    `logged_by_user_id` equals their own `X-User-ID`, a violation rejected
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/piece_approve_by_logger_rejected_sod
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    # PRD §3.4: pieces are logged on a RECORDED flush; grading comes after.
    worker, piece = create_worker_and_log_piece(flush, kg_picked=40.0, rate=50)
    grade_flush(flush, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)
    # The piece was logged by X-User-ID == worker.id; replaying with the same
    # X-User-ID under PayrollClerk is the SOD violation.
    from test_helpers import build_user_headers
    sod_headers = build_user_headers(worker["id"], "PayrollClerk")
    resp = api.approve_piece(piece["id"], sod_headers)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    piece_after = get_success_data(api.get_piece(piece["id"], ANY))
    assert piece_after["status"] == "LOGGED"


def test_payout_settles_flush_and_zeroes_accrual(api):
    """PRD §3.4: "When a `PayrollClerk` runs a worker's payout, every
    `APPROVED` piece of that worker moves to `PAID`; the paid total is the
    sum of the already-rounded per-piece `final_pay_cents` values; the
    worker's `accrued_unpaid_cents` returns to 0 and `lifetime_paid_cents`
    grows by the paid total. The response reports `paid_piece_count` and
    `total_paid_cents`. After each payout the system checks the affected
    flushes: if a flush now has at least one piece and every piece is `PAID`,
    the flush bubbles up from `GRADED` to `SETTLED`."

    Design: Corner/calculations/payout_settles_flush_and_zeroes_accrual
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    # PRD §3.4: pieces are logged on a RECORDED flush; grading comes after.
    worker, piece = create_worker_and_log_piece(flush, kg_picked=40.0, rate=50)
    grade_flush(flush, grade_a_kg=60.0, grade_b_kg=30.0, cull_kg=10.0)
    get_success_data(api.approve_piece(piece["id"], PAYROLL))

    payout = api.payout_worker(worker["id"], PAYROLL)
    data = validate_success(payout, expected_status=200)
    assert data["paid_piece_count"] == 1
    assert data["total_paid_cents"] == 2040

    worker_after = get_success_data(api.get_worker(worker["id"], ANY))
    assert worker_after["accrued_unpaid_cents"] == 0
    assert worker_after["lifetime_paid_cents"] == 2040

    piece_after = get_success_data(api.get_piece(piece["id"], ANY))
    assert piece_after["status"] == "PAID"

    flush_after = get_success_data(api.get_flush(flush["id"], ANY))
    assert flush_after["status"] == "SETTLED", (
        "flush with >= 1 piece and all pieces PAID bubbles up to SETTLED"
    )


def test_piece_log_for_suspended_worker_rejected(api):
    """PRD §3.4: "The worker must be `ACTIVE`, otherwise
    `ERR_WORKER_NOT_ACTIVE`."

    Design: Corner/validations/piece_log_for_suspended_worker_rejected
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    lead = create_worker(full_name="Lead Lara")
    picker = create_worker(full_name="Picker Pete")
    get_success_data(api.patch_worker(picker["id"], {"status": "SUSPENDED"}, FARM))

    headers = make_harvest_crew_lead_headers(lead["id"])
    resp = api.log_piece(
        flush["id"], log_piece_payload(worker_id=picker["id"], kg_picked=10.0), headers,
    )
    validate_error(resp, ApiErrorId.ERR_WORKER_NOT_ACTIVE)

    pieces, _meta = validate_paginated(api.list_pieces(ANY, params={"worker_id": picker["id"]}))
    assert pieces == [], "rejected log must not persist a piece"


def test_grading_by_crew_lead_forbidden(api):
    """PRD §2.1: "A `GradingInspector` grades and reopens flush harvests";
    `HarvestCrewLead` is restricted to logging piece-rate picking entries
    (PRD §4 endpoint table). A role not permitted for the attempted operation
    is rejected with `ERR_FORBIDDEN` (HTTP 403) per PRD §2.1.

    Design: Corner/rbac/grading_by_crew_lead_forbidden
    """
    _variety, _batch, _room, rc = setup_fruiting_cycle()
    flush = record_flush_on_cycle(rc, total_kg=100.0)
    worker = create_worker()
    headers = make_harvest_crew_lead_headers(worker["id"])
    resp = api.grade_flush(
        flush["id"],
        {"grade_a_kg": 60.0, "grade_b_kg": 30.0, "cull_kg": 10.0},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    flush_after = get_success_data(api.get_flush(flush["id"], ANY))
    assert flush_after["status"] == "RECORDED"

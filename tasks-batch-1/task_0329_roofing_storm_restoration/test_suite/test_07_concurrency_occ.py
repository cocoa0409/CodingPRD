"""Optimistic concurrency on the Job ledger: stale-version rejection on draw
create and on change-order apply, and the positive (correct-version) path.

Queue B (cross_cutting_complexity_layers section).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    setup_in_production_job, setup_approved_change_order,
    create_draw_payload, apply_change_order_payload, disburse_draw, current_job_version,
)

PM = TEST_USERS["production_manager_headers"]

SHINGLE_10 = [{"trade": "SHINGLE", "squares": 10, "unit_price_cents": 10000, "waste_factor_pct": 0.10}]


def test_draw_create_with_stale_job_version_rejected(api):
    """PRD §2.10: "A prior draw against the same job legitimately advances the
    billing watermark and bumps `Job.version`; a draw request that still carries
    the older `expected_job_version` is therefore working from a stale view of
    the ledger, and the system rejects it with `ERR_STALE_JOB_VERSION`
    (HTTP 412) before any ledger figure is touched."

    Design: Corner/cross_cutting_complexity_layers/occ_draw_create_stale_job_version
    """
    job_id, info = setup_in_production_job(line_items=SHINGLE_10)
    stale_version = info["job_version"]
    # First draw at 40% disburses and bumps Job.version.
    disburse_draw(job_id, 0.4, stale_version)
    # Second draw still carrying the pre-first version -> stale.
    validate_error(api.create_draw(create_draw_payload(
        job_id=job_id, cumulative_pct=0.6, expected_job_version=stale_version), PM),
        ApiErrorId.ERR_STALE_JOB_VERSION.value)


def test_change_order_apply_with_stale_job_version_rejected(api):
    """PRD §2.10: "if another ledger mutation — a draw disbursement or another
    applied change order — has advanced `Job.version` since the client last read
    it, the apply is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412), because
    it would otherwise reason from stale contract and disbursement figures."

    Design: Corner/cross_cutting_complexity_layers/occ_change_order_apply_stale_job_version
    """
    job_id, info = setup_in_production_job(line_items=SHINGLE_10)
    stale_version = info["job_version"]
    co = setup_approved_change_order(job_id, delta_cents=20_000)
    # A draw disbursement advances Job.version past the captured stale_version.
    disburse_draw(job_id, 0.4, stale_version)
    validate_error(api.apply_change_order(
        co["id"], apply_change_order_payload(expected_job_version=stale_version), PM),
        ApiErrorId.ERR_STALE_JOB_VERSION.value)


def test_draw_create_with_current_version_succeeds(api):
    """PRD §2.10: "When requesting a draw, the body must carry
    `expected_job_version` equal to the target job's current `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_draw_correct_version_succeeds
    """
    job_id, info = setup_in_production_job(line_items=SHINGLE_10)
    disburse_draw(job_id, 0.4, info["job_version"])
    # Re-read the live version, then a second draw at 70% with the fresh token.
    fresh = current_job_version(job_id)
    data = validate_success(api.create_draw(create_draw_payload(
        job_id=job_id, cumulative_pct=0.7, expected_job_version=fresh), PM),
        expected_status=201)
    assert data["status"] == "DISBURSED"
    job = get_success_data(api.get_job(job_id, PM))
    assert job["billed_pct"] == 0.7

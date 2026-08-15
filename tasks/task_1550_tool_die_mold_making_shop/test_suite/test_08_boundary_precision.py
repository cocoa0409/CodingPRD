"""Boundary precision: the warranty shot limit and the retention-lien ship
threshold are both inclusive at the exact boundary (PRD §3.8, §3.9)."""
from test_helpers import (
    AFTER_PRESS_WINDOW,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_warranty_claim,
    drive_job_to_ready_to_ship,
    file_shot_report,
    file_warranty_claim,
    get_job_version,
    get_success_data,
    record_payment_payload,
    setup_booked_job,
    setup_tool_in_production,
    ship_tool,
    ship_tool_asset_payload,
    set_clock,
    validate_error,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]
FIN_PAYER = TEST_USERS["finance_payer_headers"]


def _tool_at_exact_shot_limit():
    """CLASS_103 tool IN_PRODUCTION with lifetime_shots == 250,000, exactly
    the class shot limit (500 tryout shots + one 249,500-shot report)."""
    ctx = setup_tool_in_production(
        company_name="Boundary Co", part_number="PN-9001", tracking_number="TRK-B1"
    )
    set_clock(AFTER_PRESS_WINDOW)
    file_shot_report(
        ctx["tool"]["id"], ctx["customer"]["id"],
        report_period_end="2026-08-20T00:00:00Z", shots_in_period=249_500,
    )
    return ctx


def test_claim_at_exact_shot_limit_is_covered(api):
    """PRD §3.9: "Two eligibility gates apply, in a pinned order: the time
    gate first — filing after `warranty_expires_at` is rejected with
    `ERR_WARRANTY_TIME_EXPIRED`, and when both gates would fail the time error
    is the one returned — then the shot gate: `claimed_at_shot_count` must be
    at or below the tool's `warranty_shot_limit`, with a claim exactly at the
    limit still covered and anything above it rejected with
    `ERR_WARRANTY_SHOT_LIMIT_EXCEEDED`."
    PRD §3.9: "Filing snapshots `claimed_at_shot_count` from the tool's
    current `lifetime_shots`."

    Design: Difficulty/boundary_precision_check/warranty_claim_at_exact_shot_limit_boundary
    """
    ctx = _tool_at_exact_shot_limit()
    tool = get_success_data(api_client.get_tool_asset(ctx["tool"]["id"], PM))
    assert tool["lifetime_shots"] == 250_000 == tool["warranty_shot_limit"]

    claim = validate_success(
        file_warranty_claim(ctx["tool"]["id"], ctx["customer"]["id"],
                            estimated_repair_cost_cents=500_000),
        201,
    )
    assert_warranty_claim(claim)
    assert claim["claimed_at_shot_count"] == 250_000
    assert claim["status"] == "FILED"


def test_claim_one_shot_over_the_limit_is_rejected(api):
    """PRD §3.9: "then the shot gate: `claimed_at_shot_count` must be at or
    below the tool's `warranty_shot_limit`, with a claim exactly at the limit
    still covered and anything above it rejected with
    `ERR_WARRANTY_SHOT_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/warranty_claim_at_exact_shot_limit_boundary
    """
    ctx = _tool_at_exact_shot_limit()
    # The boundary claim itself is covered.
    validate_success(
        file_warranty_claim(ctx["tool"]["id"], ctx["customer"]["id"],
                            estimated_repair_cost_cents=500_000),
        201,
    )
    # One more reported shot pushes lifetime to 250,001 — one over the limit.
    file_shot_report(
        ctx["tool"]["id"], ctx["customer"]["id"],
        report_period_end="2026-08-21T00:00:00Z", shots_in_period=1,
    )
    tool = get_success_data(api_client.get_tool_asset(ctx["tool"]["id"], PM))
    assert tool["lifetime_shots"] == 250_001

    res = file_warranty_claim(ctx["tool"]["id"], ctx["customer"]["id"],
                              estimated_repair_cost_cents=120_000)
    error = validate_error(res, ApiErrorId.ERR_WARRANTY_SHOT_LIMIT_EXCEEDED)
    assert error["error_id"] == "ERR_WARRANTY_SHOT_LIMIT_EXCEEDED"
    assert res.status_code == 422


def _job_one_cent_over_lien_threshold():
    """READY_TO_SHIP job with outstanding_cents == 1,575,001 — one cent over
    the lien threshold floor(10,500,000 * 0.15) == 1,575,000."""
    ctx = setup_booked_job(company_name="Cent Co", part_number="PN-9002")
    drive_job_to_ready_to_ship(ctx, pay_amount=8_924_999)
    job = get_success_data(api_client.get_build_job(ctx["job"]["id"], PM))
    assert job["outstanding_cents"] == 1_575_001, (
        f"Setup step failed: outstanding {job['outstanding_cents']} != 1575001"
    )
    return ctx


def test_ship_one_cent_over_lien_threshold_is_blocked(api):
    """PRD §3.8: "Only after the state gate passes does the fiscal gate run:
    the job's `outstanding_cents` must be less than or equal to the ship
    threshold — the floor of fifteen hundredths of `contract_value_cents` — or
    the ship is refused with `ERR_RETENTION_LIEN_BLOCK` (HTTP 402). The
    boundary is inclusive: an outstanding balance exactly equal to the
    threshold ships; one cent above it does not."

    Design: Difficulty/boundary_precision_check/ship_lien_threshold_exact_cent_boundary
    """
    ctx = _job_one_cent_over_lien_threshold()

    res = api_client.ship_tool_asset(ctx["tool"]["id"], ship_tool_asset_payload(), PM)
    error = validate_error(res, ApiErrorId.ERR_RETENTION_LIEN_BLOCK)
    assert error["error_id"] == "ERR_RETENTION_LIEN_BLOCK"
    assert res.status_code == 402

    tool = get_success_data(api_client.get_tool_asset(ctx["tool"]["id"], PM))
    assert tool["physical_status"] == "AWAITING_SHIPMENT"
    job = get_success_data(api_client.get_build_job(ctx["job"]["id"], PM))
    assert job["status"] == "READY_TO_SHIP"


def test_one_cent_payment_releases_ship_at_exact_threshold(api):
    """PRD §3.8: "The boundary is inclusive: an outstanding balance exactly
    equal to the threshold ships; one cent above it does not."
    PRD §2.5: "Every persisted resource carries an `id` — a server-minted UUID
    with no type prefix — plus `created_at` and `updated_at` timestamps in ISO
    8601 UTC with three fractional digits, and a `version` integer that
    increments on every mutation of the resource."

    Design: Difficulty/boundary_precision_check/ship_lien_threshold_exact_cent_boundary
    """
    ctx = _job_one_cent_over_lien_threshold()
    job_id = ctx["job"]["id"]

    # Capture the job version, then fail a ship. A rejected request mutates
    # nothing, so the OCC payment below must still match this version.
    version_before_reject = get_job_version(job_id)
    res = api_client.ship_tool_asset(ctx["tool"]["id"], ship_tool_asset_payload(), PM)
    validate_error(res, ApiErrorId.ERR_RETENTION_LIEN_BLOCK)

    payment = api_client.record_payment(
        job_id, record_payment_payload(1, version_before_reject), FIN_PAYER
    )
    validate_success(payment, 201)

    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["outstanding_cents"] == 1_575_000, (
        f"outstanding must equal floor(10500000 * 0.15), got {job['outstanding_cents']}"
    )

    shipped = ship_tool(ctx["tool"]["id"], tracking_number="TRK-B3")
    assert shipped["physical_status"] == "IN_TRANSIT"
    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["status"] == "SHIPPED"

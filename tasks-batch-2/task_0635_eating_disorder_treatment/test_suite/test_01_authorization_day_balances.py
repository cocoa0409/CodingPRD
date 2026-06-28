"""Authorization day-balance calculations, billing, and extension-window rules.

Covers the dual-variant authorized-days calculation, the pinned per-day rounding
order for patient responsibility, the half-open overlap and contiguity rules on
concurrent-review extensions, and the day-ledger conservation invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    ADMIN,
    INTAKE,
    REVIEWER,
    assert_days_conservation,
    fixtures as fx,
)


def test_authorized_days_forward_vs_chronological_midwindow(api):
    """PRD §3.11: "`days_consumed` is the sum over every approved window of the
    elapsed whole days in that window up to the clock — for each window, the floor
    of (the earlier of the window end or the current clock, minus the window start)
    in seconds divided by 86,400, never less than zero — and `days_remaining` is
    `days_authorized` minus `days_consumed`, floored at zero."

    Design: Difficulty/dual_variant_calc/authorized_days_forward_vs_chronological
    """
    ctx = fx.setup_substrate_minimal_for_auth(los_days=7)
    auth = ctx["authorization"]
    # Clock to 2026-01-04: three whole days elapsed in the [01-01, 01-08) window.
    validate_success(api.set_clock("2026-01-04T00:00:00Z", ADMIN))
    data = validate_success(api.get_authorization(auth["id"], REVIEWER))
    assert data["days_authorized"] == 7, f"expected 7, got {data['days_authorized']}"
    assert data["days_consumed"] == 3, f"expected 3, got {data['days_consumed']}"
    assert data["days_remaining"] == 4, f"expected 4, got {data['days_remaining']}"


def test_authorized_days_clock_default_consumes_zero(api):
    """PRD §2.4: "The logical clock starts at `2026-01-01T00:00:00Z`".
    PRD §3.11: "`days_consumed` is the sum over every approved window of the
    elapsed whole days in that window up to the clock".

    Design: Difficulty/dual_variant_calc/authorized_days_forward_vs_chronological
    """
    # No clock-set call: the window [01-01, 01-08) has elapsed zero days.
    ctx = fx.setup_substrate_minimal_for_auth(los_days=7)
    data = validate_success(api.get_authorization(ctx["authorization"]["id"], REVIEWER))
    assert data["days_authorized"] == 7
    assert data["days_consumed"] == 0, f"expected 0, got {data['days_consumed']}"
    assert data["days_remaining"] == 7, f"expected 7, got {data['days_remaining']}"


def test_days_conservation_consumed_plus_remaining(api):
    """PRD §3.11: "`days_remaining` is `days_authorized` minus `days_consumed`,
    floored at zero."

    Design: Difficulty/compensating_invariant/authorization_days_conservation_consumed_plus_remaining
    """
    ctx = fx.setup_substrate_minimal_for_auth(los_days=7)
    validate_success(api.set_clock("2026-01-04T00:00:00Z", ADMIN))
    data = validate_success(api.get_authorization(ctx["authorization"]["id"], REVIEWER))
    assert data["days_authorized"] == 7
    assert data["days_consumed"] == 3
    assert data["days_remaining"] == 4
    assert_days_conservation(data)


def test_days_conservation_holds_at_clock_default(api):
    """PRD §3.11: "`days_remaining` is `days_authorized` minus `days_consumed`,
    floored at zero."

    Design: Difficulty/compensating_invariant/authorization_days_conservation_consumed_plus_remaining
    """
    ctx = fx.setup_substrate_minimal_for_auth(los_days=7)
    data = validate_success(api.get_authorization(ctx["authorization"]["id"], REVIEWER))
    assert data["days_authorized"] == 7
    assert data["days_consumed"] == 0
    assert data["days_remaining"] == 7
    assert_days_conservation(data)


def test_billing_summary_round_per_day_then_multiply(api):
    """PRD §3.12: "first compute the per-day cost share as the `daily_rate_cents`
    multiplied by the `coinsurance_pct`, rounded half-up to whole cents; then
    multiply that whole-cent per-day share by `days_consumed`."

    Design: Difficulty/combinatorial_formula/patient_responsibility_round_per_day_then_multiply
    """
    # rate 12345 * 0.205 = 2530.725 -> round_half_up = 2531; * 3 = 7593.
    ctx = fx.setup_substrate_minimal_for_auth(
        los_days=5,
        window_end_iso="2026-01-06T00:00:00Z",
        daily_rate_cents=12345,
        coinsurance_pct=0.205,
    )
    validate_success(api.set_clock("2026-01-04T00:00:00Z", ADMIN))
    summary = validate_success(api.get_billing_summary(ctx["authorization"]["id"], REVIEWER))
    assert summary["days_consumed"] == 3, f"expected 3, got {summary['days_consumed']}"
    assert summary["patient_responsibility_cents"] == 7593, (
        f"expected 7593 (2531*3), got {summary['patient_responsibility_cents']}"
    )


def test_billing_summary_whole_cent_per_day_share(api):
    """PRD §3.12: "first compute the per-day cost share as the `daily_rate_cents`
    multiplied by the `coinsurance_pct`, rounded half-up to whole cents; then
    multiply that whole-cent per-day share by `days_consumed`."

    Design: Corner/endpoints/billing_summary_computed_read_matches_formula
    """
    # rate 100000 * 0.20 = 20000 per day; * 3 = 60000.
    ctx = fx.setup_substrate_minimal_for_auth(
        los_days=5,
        window_end_iso="2026-01-06T00:00:00Z",
        daily_rate_cents=100000,
        coinsurance_pct=0.20,
    )
    validate_success(api.set_clock("2026-01-04T00:00:00Z", ADMIN))
    summary = validate_success(api.get_billing_summary(ctx["authorization"]["id"], REVIEWER))
    assert summary["days_consumed"] == 3
    assert summary["patient_responsibility_cents"] == 60000, (
        f"expected 60000 (20000*3), got {summary['patient_responsibility_cents']}"
    )


def test_extension_window_overlap_rejected(api):
    """PRD §3.11: "it must not overlap any prior approved window, else
    `ERR_AUTH_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/authorization_extension_window_overlap_rejected
    """
    ctx = fx.setup_substrate_minimal_for_auth(
        los_days=14, window_end_iso="2026-01-08T00:00:00Z"
    )
    auth_id = ctx["authorization"]["id"]
    fid = ctx["facility"]["id"]
    # Extension [01-05, 01-10) overlaps the approved [01-01, 01-08).
    resp = api.create_review(
        {
            "authorization_id": auth_id,
            "facility_id": fid,
            "decision": "APPROVE",
            "window_start_iso": "2026-01-05T00:00:00Z",
            "window_end_iso": "2026-01-10T00:00:00Z",
        },
        REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_OVERLAP.value)
    data = validate_success(api.get_authorization(auth_id, REVIEWER))
    assert data["days_authorized"] == 7, (
        f"days_authorized must stay 7, got {data['days_authorized']}"
    )


def test_extension_window_noncontiguous_rejected(api):
    """PRD §3.11: "the new window must be contiguous with prior coverage — its
    `window_start_iso` must equal the current `covered_through_iso` with no gap —
    else `ERR_AUTH_WINDOW_NONCONTIGUOUS`".

    Design: Difficulty/resource_temporal_overlap/authorization_extension_window_noncontiguous_rejected
    """
    ctx = fx.setup_substrate_minimal_for_auth(
        los_days=14, window_end_iso="2026-01-08T00:00:00Z"
    )
    auth_id = ctx["authorization"]["id"]
    fid = ctx["facility"]["id"]
    # Extension [01-10, 01-15) leaves a 2-day gap after covered_through 01-08.
    resp = api.create_review(
        {
            "authorization_id": auth_id,
            "facility_id": fid,
            "decision": "APPROVE",
            "window_start_iso": "2026-01-10T00:00:00Z",
            "window_end_iso": "2026-01-15T00:00:00Z",
        },
        REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_NONCONTIGUOUS.value)
    data = validate_success(api.get_authorization(auth_id, REVIEWER))
    assert data["days_authorized"] == 7, (
        f"days_authorized must stay 7, got {data['days_authorized']}"
    )


def test_extension_window_overlap_leaves_status_approved(api):
    """PRD §3.11: "it must not overlap any prior approved window, else
    `ERR_AUTH_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/authorization_extension_window_overlap_rejected
    """
    ctx = fx.setup_substrate_minimal_for_auth(
        los_days=14, window_end_iso="2026-01-08T00:00:00Z"
    )
    auth_id = ctx["authorization"]["id"]
    fid = ctx["facility"]["id"]
    resp = api.create_review(
        {
            "authorization_id": auth_id,
            "facility_id": fid,
            "decision": "APPROVE",
            "window_start_iso": "2026-01-05T00:00:00Z",
            "window_end_iso": "2026-01-10T00:00:00Z",
        },
        REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_OVERLAP.value)
    # The rejected extension must not advance coverage; auth stays APPROVED.
    data = validate_success(api.get_authorization(auth_id, REVIEWER))
    assert data["status"] == "APPROVED", (
        f"auth must stay APPROVED, got {data['status']}"
    )


def test_extension_contiguous_window_accepted(api):
    """PRD §3.11: "A subsequent approval on an already-`APPROVED` authorization is
    an **extension** ... the new window must be contiguous with prior coverage —
    its `window_start_iso` must equal the current `covered_through_iso` with no gap
    — else `ERR_AUTH_WINDOW_NONCONTIGUOUS` ... An accepted extension again adds its
    `approved_days` to `days_authorized`".

    Design: Difficulty/resource_temporal_overlap/authorization_extension_window_noncontiguous_rejected
    """
    ctx = fx.setup_substrate_minimal_for_auth(
        los_days=14, window_end_iso="2026-01-08T00:00:00Z"
    )
    auth_id = ctx["authorization"]["id"]
    fid = ctx["facility"]["id"]
    # A contiguous extension [01-08, 01-12) abuts covered_through 01-08 (gap=0).
    resp = api.create_review(
        {
            "authorization_id": auth_id,
            "facility_id": fid,
            "decision": "APPROVE",
            "window_start_iso": "2026-01-08T00:00:00Z",
            "window_end_iso": "2026-01-12T00:00:00Z",
        },
        REVIEWER,
    )
    validate_success(resp, expected_status=201)
    data = validate_success(api.get_authorization(auth_id, REVIEWER))
    assert data["days_authorized"] == 11, (
        f"expected 7 + 4 = 11 authorized days, got {data['days_authorized']}"
    )


def test_billing_summary_forbidden_order_total_not_used(api):
    """PRD §3.12: "The per-day rounding happens before the multiplication —
    multiplying the unrounded share by the day count and rounding once at the end
    would yield a different total and is explicitly not the method used."

    Design: Difficulty/combinatorial_formula/patient_responsibility_round_per_day_then_multiply
    """
    # rate 12345 * 0.205 = 2530.725 -> round per day = 2531; * 3 = 7593.
    # The forbidden order (12345*0.205*3 = 7592.175 -> round once = 7592) must
    # NOT be produced.
    ctx = fx.setup_substrate_minimal_for_auth(
        los_days=5,
        window_end_iso="2026-01-06T00:00:00Z",
        daily_rate_cents=12345,
        coinsurance_pct=0.205,
    )
    validate_success(api.set_clock("2026-01-04T00:00:00Z", ADMIN))
    summary = validate_success(api.get_billing_summary(ctx["authorization"]["id"], REVIEWER))
    assert summary["days_consumed"] == 3
    assert summary["patient_responsibility_cents"] == 7593, (
        f"expected 7593 (round-per-day-first), got "
        f"{summary['patient_responsibility_cents']}"
    )
    assert summary["patient_responsibility_cents"] != 7592, (
        "round-once-at-end (7592) is explicitly not the method used"
    )


def test_review_approve_inverted_window_rejected(api):
    """PRD §3.11: "requires the window to be well-formed with `window_end_iso`
    strictly after `window_start_iso`, else `ERR_INVALID_WINDOW`."

    Design: Corner/validations/review_approve_with_inverted_window_returns_invalid_window
    """
    facility, program, cohort = fx.create_substrate()
    patient = fx.create_patient(facility["id"])
    admission = fx.create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"]
    )
    auth = fx.create_authorization(admission["id"], facility["id"])
    resp = api.create_review(
        {
            "authorization_id": auth["id"],
            "facility_id": facility["id"],
            "decision": "APPROVE",
            "window_start_iso": "2026-01-08T00:00:00Z",
            "window_end_iso": "2026-01-01T00:00:00Z",
        },
        REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)
    data = validate_success(api.get_authorization(auth["id"], REVIEWER))
    assert data["status"] == "PENDING", f"auth must stay PENDING, got {data['status']}"

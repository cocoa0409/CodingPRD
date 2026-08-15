"""Pay periods and pay statements: tiered standby pay, rounding, close gates."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_pay_statement,
    complete_shift,
    create_pay_period,
    create_pay_period_payload,
    get_pay_period,
    list_period_statements,
    make_technician,
    publish_shift,
    set_clock,
    start_shift,
    validate_error,
    validate_success,
)


def _complete_shift(technician_id, start_at, end_at, start_clock, complete_clock):
    shift = publish_shift(technician_id, start_at, end_at)
    set_clock(start_clock)
    start_shift(shift["id"])
    set_clock(complete_clock)
    return complete_shift(shift["id"])


class TestStandbyPayRoundingOrderDivergence:
    def _setup_three_completed_shifts(self):
        """Three 100-minute COMPLETED shifts for one technician (4725/h, 1500bp)."""
        tech = make_technician(full_name="Pat Tech", base_hourly_rate_cents=4725,
                               on_call_differential_bp=1500)
        completed = [
            _complete_shift(
                tech["id"],
                f"2026-08-0{day}T01:00:00Z", f"2026-08-0{day}T02:40:00Z",
                start_clock=f"2026-08-0{day}T01:30:00Z",
                complete_clock=f"2026-08-0{day}T03:00:00Z",
            )
            for day in (1, 2, 3)
        ]
        return tech, completed

    def test_provisional_standby_pay_rounds_each_shift_individually(self, api):
        """PRD §2.6: "Wherever a calculation must round, it rounds **half up**
        to whole cents, and the rounding points are pinned per calculation:
        per-shift standby pay is rounded individually at shift completion;
        final period standby pay is accumulated without intermediate rounding
        and rounded once at the end..."
        PRD §3.2: "The `provisional_shift_pay_cents` is then the standby
        minutes divided by sixty, multiplied by the technician's
        `base_hourly_rate_cents`, and increased by the on-call differential —
        that is, multiplied by one plus `on_call_differential_bp` divided by
        ten thousand — with the per-shift result rounded half-up to whole
        cents."

        Design: Difficulty/dual_variant_calc/standby_pay_rounding_order_divergence
        """
        _tech, completed = self._setup_three_completed_shifts()
        for shift in completed:
            assert shift["standby_minutes"] == 100, (
                "100-minute window with no callback overlap"
            )
            assert shift["provisional_shift_pay_cents"] == 9056, (
                "round_half_up(100/60 x 4725 x 1.15) = round_half_up(9056.25)"
            )

    def test_final_standby_pay_single_rounding_diverges_from_provisional_sum(
        self, api, property_admin_headers
    ):
        """PRD §3.9: "The accumulation is exact, with no intermediate rounding,
        and `standby_pay_final_cents` is the single half-up rounding of the
        period total — which is why the final figure can legitimately differ
        from the sum of the per-shift `provisional_shift_pay_cents` values."
        PRD §3.9: "The statement's `total_pay_cents` is the standby final plus
        the callback final."

        Design: Difficulty/dual_variant_calc/standby_pay_rounding_order_divergence
        """
        _tech, completed = self._setup_three_completed_shifts()
        provisional_sum = sum(s["provisional_shift_pay_cents"] for s in completed)
        assert provisional_sum == 27168

        set_clock("2026-08-08T00:00:00Z")
        period = create_pay_period("2026-08-01T00:00:00Z", "2026-08-08T00:00:00Z")
        validate_success(api.close_pay_period(period["id"], property_admin_headers),
                         200)
        rows, meta = list_period_statements(period["id"])
        assert meta["total_count"] == 1
        statement = rows[0]
        assert_pay_statement(statement)
        assert statement["standby_minutes_total"] == 300
        assert statement["standby_pay_final_cents"] == 27169, (
            "round_half_up(3 x 9056.25) = round_half_up(27168.75) — the single "
            "final rounding diverges from the 27168 provisional sum"
        )
        assert statement["standby_pay_final_cents"] != provisional_sum
        assert statement["callback_pay_final_cents"] == 0
        assert statement["total_pay_cents"] == 27169


def test_standby_pay_soft_cap_tier_split(api, property_admin_headers):
    """PRD §3.9: "A running allowance of 2400 minutes (40 hours) of
    full-differential standby is tracked: each shift contributes its
    `standby_minutes` up to the remaining allowance at the full rate — minutes
    divided by sixty, times `base_hourly_rate_cents`, times one plus
    `on_call_differential_bp` divided by ten thousand — and any minutes beyond
    the allowance at half the differential, that is, times one plus
    `on_call_differential_bp` divided by twenty thousand. The accumulation is
    exact, with no intermediate rounding, and `standby_pay_final_cents` is the
    single half-up rounding of the period total..."

    Design: Corner/calculations/standby_pay_soft_cap_tier_split
    """
    tech = make_technician(full_name="Pat Tech", base_hourly_rate_cents=6000,
                           on_call_differential_bp=1500)
    shift1 = _complete_shift(
        tech["id"], "2026-08-01T00:00:00Z", "2026-08-01T23:20:00Z",
        start_clock="2026-08-01T12:00:00Z",
        complete_clock="2026-08-01T23:30:00Z",
    )
    shift2 = _complete_shift(
        tech["id"], "2026-08-02T00:00:00Z", "2026-08-02T18:20:00Z",
        start_clock="2026-08-02T12:00:00Z",
        complete_clock="2026-08-02T18:30:00Z",
    )
    assert shift1["provisional_shift_pay_cents"] == 161000, "1400 min full tier"
    assert shift2["provisional_shift_pay_cents"] == 126500, "1100 min full tier"

    set_clock("2026-08-08T00:00:00Z")
    period = create_pay_period("2026-08-01T00:00:00Z", "2026-08-08T00:00:00Z")
    validate_success(api.close_pay_period(period["id"], property_admin_headers),
                     200)
    rows, _meta = list_period_statements(period["id"])
    statement = rows[0]
    assert statement["standby_minutes_total"] == 2500
    # 161000 + (1000 full-tier min = 115000) + (100 half-tier min = 10750)
    assert statement["standby_pay_final_cents"] == 286750, (
        "the second shift straddles the 2400-minute allowance; its last 100 "
        "minutes earn half the differential"
    )
    assert statement["standby_pay_final_cents"] != (
        shift1["provisional_shift_pay_cents"] + shift2["provisional_shift_pay_cents"]
    ), "cap tier, not rounding, drives this divergence"


def test_paystatement_is_immutable_without_version(api, property_admin_headers):
    """PRD §2.5: "Because statements are emitted once at period close and never
    mutated thereafter, a `PayStatement` carries only `id` and `created_at`;
    both `updated_at` and `version` are absent from it."

    Design: Corner/entities/paystatement_is_immutable_without_version
    """
    tech = make_technician(full_name="Pat Tech", base_hourly_rate_cents=6000,
                           on_call_differential_bp=1500)
    _complete_shift(
        tech["id"], "2026-08-01T01:00:00Z", "2026-08-01T02:00:00Z",
        start_clock="2026-08-01T01:30:00Z",
        complete_clock="2026-08-01T03:00:00Z",
    )
    set_clock("2026-08-08T00:00:00Z")
    period = create_pay_period("2026-08-01T00:00:00Z", "2026-08-08T00:00:00Z")
    validate_success(api.close_pay_period(period["id"], property_admin_headers),
                     200)
    rows, meta = list_period_statements(period["id"])
    assert meta["total_count"] == 1
    statement = rows[0]
    assert_pay_statement(statement)
    assert "version" not in statement and "updated_at" not in statement


def test_pay_period_double_close_rejected(api, property_admin_headers):
    """PRD §3.9: "Closing a period is `PropertyAdmin`-only and gated twice
    after the state check (`ERR_PAY_PERIOD_INVALID_STATE` unless `OPEN`)..."
    PRD §3.9: "A successful close emits one `PayStatement` per technician who
    has at least one `COMPLETED` shift starting inside the period..."

    Design: Corner/state_machines/pay_period_double_close_rejected
    """
    tech = make_technician(full_name="Pat Tech", base_hourly_rate_cents=6000,
                           on_call_differential_bp=1500)
    _complete_shift(
        tech["id"], "2026-08-01T01:00:00Z", "2026-08-01T02:00:00Z",
        start_clock="2026-08-01T01:30:00Z",
        complete_clock="2026-08-01T03:00:00Z",
    )
    set_clock("2026-08-08T00:00:00Z")
    period = create_pay_period("2026-08-01T00:00:00Z", "2026-08-08T00:00:00Z")
    validate_success(api.close_pay_period(period["id"], property_admin_headers),
                     200)
    resp = api.close_pay_period(period["id"], property_admin_headers)
    validate_error(resp, ApiErrorId.ERR_PAY_PERIOD_INVALID_STATE)
    _rows, meta = list_period_statements(period["id"])
    assert meta["total_count"] == 1, "no duplicate statements on re-close"


def test_pay_period_close_with_open_shifts_rejected(api, property_admin_headers):
    """PRD §3.9: "no rotation shift whose `start_at` falls inside the period
    may remain in `PUBLISHED` or `ACTIVE` (else `ERR_OPEN_SHIFTS_IN_PERIOD`),
    so every in-period shift must first be completed or cancelled."

    Design: Corner/state_machines/pay_period_close_with_open_shifts_rejected
    """
    tech = make_technician(full_name="Pat Tech", base_hourly_rate_cents=6000,
                           on_call_differential_bp=1500)
    publish_shift(tech["id"], "2026-08-02T00:00:00Z", "2026-08-02T08:00:00Z")
    set_clock("2026-08-08T00:00:00Z")
    period = create_pay_period("2026-08-01T00:00:00Z", "2026-08-08T00:00:00Z")
    resp = api.close_pay_period(period["id"], property_admin_headers)
    validate_error(resp, ApiErrorId.ERR_OPEN_SHIFTS_IN_PERIOD)
    assert get_pay_period(period["id"])["status"] == "OPEN"


def test_pay_period_close_before_period_end_rejected(api, property_admin_headers):
    """PRD §3.9: "the period must actually have ended — `period_end` at or
    before now (else `ERR_PERIOD_NOT_ENDED`)..."
    PRD §2.4: "Before any operator intervention, the logical clock starts at
    exactly `2026-08-01T00:00:00Z`."

    Design: Corner/state_machines/pay_period_close_before_period_end_rejected
    """
    # The clock is never touched: it reads the 2026-08-01T00:00:00Z default.
    period = validate_success(
        api_client.create_pay_period(
            create_pay_period_payload(
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-08T00:00:00Z",
            ),
            property_admin_headers,
        ),
        201,
    )
    resp = api.close_pay_period(period["id"], property_admin_headers)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_ENDED)
    assert get_pay_period(period["id"])["status"] == "OPEN"

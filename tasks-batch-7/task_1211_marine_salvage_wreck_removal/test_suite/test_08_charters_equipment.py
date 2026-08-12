"""Equipment charters: booking overlap semantics, hire lifecycle, cost math."""
from test_helpers import (
    ApiErrorId,
    assert_equipment_charter,
    book_charter,
    register_asset,
    set_clock,
    setup_active_contract,
    setup_running_phase,
    setup_signed_contract,
    validate_error,
    validate_success,
)


class TestCharterWindowHalfOpen:
    """Half-open [start, end) booking: true overlaps rejected, touching allowed."""

    def _setup_signed_with_first_charter(self):
        ctx = setup_signed_contract(casualty_overrides={"vessel_name": "MV Pax"})
        asset = register_asset(max_hs_meters=3.00)
        ch1 = book_charter(
            ctx["casualty"]["id"], asset["id"],
            window_start="2026-05-10T00:00:00Z", window_end="2026-05-20T00:00:00Z",
        )
        assert ch1["status"] == "BOOKED"
        return ctx, asset, ch1

    def test_overlapping_charter_rejected(self, api, salvage_master_headers):
        """PRD 3.6: "The booked interval is half-open — it includes its start and
        excludes its end — so two charters on the same asset whose windows merely
        touch at an endpoint coexist legally, while any true overlap with another
        charter of that asset in `BOOKED`, `ON_HIRE`, `STANDBY_WEATHER`, or
        `STANDBY_ENV` is rejected with `ERR_CHARTER_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/charter_window_half_open_overlap_vs_adjacency
        """
        ctx, asset, _ = self._setup_signed_with_first_charter()
        res = api.create_charter(
            {
                "casualty_id": ctx["casualty"]["id"],
                "equipment_asset_id": asset["id"],
                "window_start": "2026-05-15T00:00:00Z",
                "window_end": "2026-05-25T00:00:00Z",
                "purpose": "SALVAGE",
            },
            salvage_master_headers,
        )
        validate_error(res, ApiErrorId.ERR_CHARTER_OVERLAP, expected_status=409)

    def test_adjacent_charter_accepted(self, api, salvage_master_headers):
        """PRD 3.6: "two charters on the same asset whose windows merely touch at
        an endpoint coexist legally"
        PRD 3.6: "A new charter opens in `BOOKED`, flips its asset to
        `CHARTERED`"

        Design: Difficulty/resource_temporal_overlap/charter_window_half_open_overlap_vs_adjacency
        """
        ctx, asset, _ = self._setup_signed_with_first_charter()
        # [05-20, 05-30) touches [05-10, 05-20) at the endpoint: not a collision.
        adjacent = validate_success(
            api.create_charter(
                {
                    "casualty_id": ctx["casualty"]["id"],
                    "equipment_asset_id": asset["id"],
                    "window_start": "2026-05-20T00:00:00Z",
                    "window_end": "2026-05-30T00:00:00Z",
                    "purpose": "SALVAGE",
                },
                salvage_master_headers,
            ),
            201,
        )
        assert adjacent["status"] == "BOOKED"
        asset_after = validate_success(
            api.get_equipment_asset(asset["id"], salvage_master_headers), 200
        )
        assert asset_after["status"] == "CHARTERED"


class TestCharterCostPerLineRounding:
    """Per-rate-line rounding is pinned: round each line, then multiply by days."""

    def _setup_and_run(self, api, salvage_master_headers):
        ctx = setup_running_phase(
            phase_duration_hours=336, day_rate_cents=1_000_001, max_hs_meters=3.00,
            forecast_hs_meters=1.00,
            casualty_overrides={
                "vessel_name": "FV Oda", "casualty_type": "GROUNDING",
                "declared_salved_value_cents": 800_000_000, "position": "70N 20E",
            },
            assessment_overrides={"estimated_cost_cents": 3_000_000},
        )
        # Weather hold for 72h (05-17 -> 05-20), then resume; off-hire at 05-24.
        set_clock("2026-05-17T00:00:00Z")
        validate_success(api.hold_weather_phase(ctx["phase"]["id"], salvage_master_headers), 200)
        set_clock("2026-05-20T00:00:00Z")
        validate_success(api.resume_phase(ctx["phase"]["id"], salvage_master_headers), 200)
        set_clock("2026-05-24T00:00:00Z")
        off = validate_success(api.off_hire_charter(ctx["charter"]["id"], salvage_master_headers), 200)
        return ctx, off

    def test_day_buckets_and_total_cost(self, api, salvage_master_headers):
        """PRD 3.6: "Demurrage hours are the excess of elapsed over booked —
        zero when elapsed does not exceed booked, because the trigger is
        strictly-greater and an exactly-on-time charter earns no demurrage."
        PRD 3.6: "the standby line is `standby_days` times half the daily rate,
        the halved rate rounded half up to integer cents before multiplication"

        Design: Difficulty/combinatorial_formula/charter_cost_per_line_rounding_order
        """
        _, off = self._setup_and_run(api, salvage_master_headers)
        assert_equipment_charter(off)
        assert off["status"] == "OFF_HIRE"
        assert off["active_days"] == 11, "264 active hours (336 elapsed - 72 standby)"
        assert off["standby_days"] == 3, "72 standby hours"
        assert off["demurrage_days"] == 0, "elapsed 336h == booked 336h: no demurrage"
        # Per-line rounding: 11 x 1,000,001 + 3 x round_half_up(1,000,001 x 0.5).
        assert off["total_cost_cents"] == 12_500_014, (
            "11 x 1,000,001 + 3 x 500,001; sum-then-round (12,500,013) is non-conformant"
        )
        assert off["total_cost_cents"] != 12_500_013

    def test_contract_cost_to_date_recomputed(self, api, salvage_master_headers):
        """PRD 3.6: "Off-hire also recomputes the contract's `cost_to_date_cents`
        as the sum of `total_cost_cents` over all of the casualty's charters in
        `OFF_HIRE`, re-evaluates the contract's `overrun_flag`, re-derives the
        asset's status"

        Design: Difficulty/combinatorial_formula/charter_cost_per_line_rounding_order
        """
        ctx, off = self._setup_and_run(api, salvage_master_headers)
        contract = validate_success(
            api.get_contract(ctx["contract"]["id"], salvage_master_headers), 200
        )
        assert contract["cost_to_date_cents"] == 12_500_014
        assert contract["cost_to_date_cents"] == off["total_cost_cents"]


def test_demurrage_strictly_greater_boundary(api, salvage_master_headers):
    """PRD 3.6: "Demurrage hours are the excess of elapsed over booked — zero
    when elapsed does not exceed booked, because the trigger is strictly-greater
    and an exactly-on-time charter earns no demurrage."
    PRD 3.6: "the demurrage line is `demurrage_days` times one and a half times
    the daily rate, the uplifted rate rounded half up to integer cents before
    multiplication."

    Design: Corner/calculations/demurrage_strictly_greater_boundary
    """
    ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
    asset = register_asset(max_hs_meters=3.00)
    set_clock("2026-05-10T00:00:00Z")
    ch_a = book_charter(
        ctx["casualty"]["id"], asset["id"],
        window_start="2026-05-10T00:00:00Z", window_end="2026-05-20T00:00:00Z",
    )
    validate_success(api.on_hire_charter(ch_a["id"], salvage_master_headers), 200)
    # Exactly on time: elapsed == booked (240h) at window end.
    set_clock("2026-05-20T00:00:00Z")
    off_a = validate_success(api.off_hire_charter(ch_a["id"], salvage_master_headers), 200)
    assert off_a["demurrage_days"] == 0, "elapsed == booked: strictly-greater trigger does not fire"
    assert off_a["active_days"] == 10
    assert off_a["total_cost_cents"] == 20_000_000

    # A second, adjacent charter kept 24h past its booked window.
    ch_b = book_charter(
        ctx["casualty"]["id"], asset["id"],
        window_start="2026-05-20T00:00:00Z", window_end="2026-05-30T00:00:00Z",
    )
    validate_success(api.on_hire_charter(ch_b["id"], salvage_master_headers), 200)
    set_clock("2026-05-31T00:00:00Z")
    off_b = validate_success(api.off_hire_charter(ch_b["id"], salvage_master_headers), 200)
    assert off_b["demurrage_days"] == 1, "24h over the booked window"
    assert off_b["active_days"] == 10
    assert off_b["total_cost_cents"] == 23_000_000, "10 active x 2,000,000 + 1 x 3,000,000"


def test_asset_status_derived_across_charter_lifecycle(api, salvage_master_headers):
    """PRD 3.6: "New assets open `AVAILABLE`; the status is derived, moving to
    `CHARTERED` the moment a charter referencing the asset enters `BOOKED`, and
    back to `AVAILABLE` when no charter of the asset remains in `BOOKED`,
    `ON_HIRE`, `STANDBY_WEATHER`, or `STANDBY_ENV`."

    Design: Corner/endpoints/asset_status_derived_across_charter_lifecycle
    """
    ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
    asset = register_asset(max_hs_meters=3.00)
    assert asset["status"] == "AVAILABLE"
    set_clock("2026-05-10T00:00:00Z")
    charter = book_charter(
        ctx["casualty"]["id"], asset["id"],
        window_start="2026-05-10T00:00:00Z", window_end="2026-05-20T00:00:00Z",
    )
    chartered = validate_success(api.get_equipment_asset(asset["id"], salvage_master_headers), 200)
    assert chartered["status"] == "CHARTERED"
    validate_success(api.on_hire_charter(charter["id"], salvage_master_headers), 200)
    set_clock("2026-05-12T00:00:00Z")
    validate_success(api.off_hire_charter(charter["id"], salvage_master_headers), 200)
    released = validate_success(api.get_equipment_asset(asset["id"], salvage_master_headers), 200)
    assert released["status"] == "AVAILABLE"


def test_charter_onhire_before_window_rejected(api, salvage_master_headers):
    """PRD 3.6: "the logical clock must sit inside the booked window — at or
    after `window_start` and strictly before `window_end` — otherwise
    `ERR_CHARTER_WINDOW_NOT_OPEN`."
    PRD 2.4: "Before any client has set it, the logical clock reads exactly
    2026-05-01T00:00:00Z, and it never falls back to wall-clock time."

    Design: Corner/validations/charter_onhire_before_window_rejected
    """
    ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
    asset = register_asset(max_hs_meters=3.00)
    charter = book_charter(
        ctx["casualty"]["id"], asset["id"],
        window_start="2026-05-10T00:00:00Z", window_end="2026-05-20T00:00:00Z",
    )
    # The clock was never set: it reads 2026-05-01T00:00:00Z, before window_start.
    res = api.on_hire_charter(charter["id"], salvage_master_headers)
    validate_error(res, ApiErrorId.ERR_CHARTER_WINDOW_NOT_OPEN, expected_status=422)


def test_charter_asset_class_not_in_plan_rejected(api, salvage_master_headers):
    """PRD 3.6: "Booking requires the casualty's contract to be in `SIGNED`,
    `ACTIVE`, or `PERFORMANCE_COMPLETE`, otherwise `ERR_CONTRACT_NOT_ACTIVE`;
    and the asset's class must appear among the contract plan's
    `required_equipment_classes`, otherwise `ERR_ASSET_CLASS_NOT_REQUIRED`."

    Design: Corner/validations/charter_asset_class_not_in_plan_rejected
    """
    ctx = setup_signed_contract(casualty_overrides={"vessel_name": "MV Pax"})
    crane = register_asset(
        asset_class="CRANE_BARGE", day_rate_cents=4_000_000, max_hs_meters=2.00
    )
    res = api.create_charter(
        {
            "casualty_id": ctx["casualty"]["id"],
            "equipment_asset_id": crane["id"],
            "window_start": "2026-05-10T00:00:00Z",
            "window_end": "2026-05-20T00:00:00Z",
            "purpose": "SALVAGE",
        },
        salvage_master_headers,
    )
    validate_error(res, ApiErrorId.ERR_ASSET_CLASS_NOT_REQUIRED, expected_status=422)


def test_offhire_response_immediate_visibility(api, salvage_master_headers):
    """PRD 3.6: "Taking a charter off hire, from `ON_HIRE`, `STANDBY_WEATHER`,
    or `STANDBY_ENV`, is the settlement point of the equipment ledger. The
    action stamps `off_hire_at` with the current logical clock, closes any open
    standby interval into `standby_hours`, and computes the day buckets and
    cost."
    PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/offhire_response_immediate_visibility
    """
    ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
    asset = register_asset(max_hs_meters=3.00)
    set_clock("2026-05-10T00:00:00Z")
    charter = book_charter(
        ctx["casualty"]["id"], asset["id"],
        window_start="2026-05-10T00:00:00Z", window_end="2026-05-20T00:00:00Z",
    )
    validate_success(api.on_hire_charter(charter["id"], salvage_master_headers), 200)
    set_clock("2026-05-12T00:00:00Z")
    off = validate_success(api.off_hire_charter(charter["id"], salvage_master_headers), 200)
    # The computed figures are visible in the off-hire response itself.
    assert off["active_days"] == 2
    assert off["standby_days"] == 0
    assert off["demurrage_days"] == 0
    assert off["total_cost_cents"] == 4_000_000, "2 days x 2,000,000"
    # A subsequent read agrees — no reconciliation lag.
    reread = validate_success(api.get_charter(charter["id"], salvage_master_headers), 200)
    assert reread["active_days"] == off["active_days"]
    assert reread["standby_days"] == off["standby_days"]
    assert reread["demurrage_days"] == off["demurrage_days"]
    assert reread["total_cost_cents"] == off["total_cost_cents"]

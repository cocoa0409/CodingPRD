"""Pass programmes and pass tiers: creation, defaults, reads and lifecycle steps."""

import pytest

from test_helpers import (
    BRONZE,
    DEFAULT_CAPACITY_LOCK_BLOCKOUT_MAX_RANK,
    DEFAULT_CAPACITY_LOCK_THRESHOLD_PCT,
    DEFAULT_CAPACITY_PEAK_THRESHOLD_PCT,
    DEFAULT_DEFAULT_THRESHOLD,
    DEFAULT_DELINQUENCY_SUSPENSION_THRESHOLD,
    DEFAULT_SHARING_CASE_AUTO_OPEN_SCORE,
    ApiErrorId,
    ParkingBenefit,
    PassStatus,
    ProgramStatus,
    TierStatus,
    advance_program,
    advance_status_payload,
    assert_audit_fields,
    assert_version,
    build_program,
    clerk_headers,
    create_park_day,
    create_passholder,
    create_program,
    create_tier,
    is_valid_uuid,
    park_day_payload,
    pass_program_payload,
    pass_tier_payload,
    program_admin_headers,
    publish_tier,
    season_pass_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPassProgrammeRecord:
    """A newly created programme carries system fields and zeroed rollups."""

    def test_creation_returns_the_envelope_and_the_system_managed_fields(self, api):
        """The programme is born in DESIGN at version 1 with every rollup at zero.

        PRD: "A programme is born in `DESIGN`, and its five computed
        money-and-population fields — `base_revenue_cents`, `recognized_revenue_cents`,
        `deferred_revenue_cents`, `forfeited_revenue_cents` and `active_pass_count` — all
        initialise to 0."

        Design: Corner/entities/pass_program_creation_returns_envelope_and_system_fields
        """
        response = api.create_pass_program(
            pass_program_payload(
                season_year=2027, park_name="Harbor Bay", early_bird_deadline="2027-11-15"
            ),
            headers=program_admin_headers(),
        )

        data = validate_success(response, 201)
        assert data["season_year"] == 2027, f"season_year should round-trip, got {data['season_year']!r}"
        assert data["park_name"] == "Harbor Bay", f"park_name should round-trip, got {data['park_name']!r}"
        assert data["early_bird_deadline"] == "2027-11-15", (
            f"early_bird_deadline should round-trip, got {data['early_bird_deadline']!r}"
        )
        assert data["status"] == ProgramStatus.DESIGN.value, (
            f"a new programme should be in DESIGN, got {data['status']!r}"
        )
        assert_audit_fields(data, "pass programme")
        assert_version(data, 1, "pass programme")
        assert is_valid_uuid(data["id"]), f"the id should be a bare UUID, got {data['id']!r}"
        for field in (
            "base_revenue_cents",
            "recognized_revenue_cents",
            "deferred_revenue_cents",
            "forfeited_revenue_cents",
            "active_pass_count",
        ):
            assert data[field] == 0, f"{field} should initialise to 0, got {data[field]!r}"

    def test_the_six_optional_knobs_fall_back_to_their_declared_defaults(self, api):
        """Omitted thresholds take the pinned defaults; supplied ones are stored.

        PRD: "Six further knobs may be supplied at creation and each has a default the
        programme falls back to when the field is omitted: `capacity_peak_threshold_pct`
        defaults to `0.85`, `capacity_lock_threshold_pct` to `0.97`,
        `capacity_lock_blockout_max_rank` to `2`, `delinquency_suspension_threshold` to
        `2`, `default_threshold` to `3`, and `sharing_case_auto_open_score` to `65`."

        Design: Corner/entities/pass_program_threshold_defaults_applied_when_omitted
        """
        defaulted = create_program(api)

        assert defaulted["capacity_peak_threshold_pct"] == pytest.approx(
            DEFAULT_CAPACITY_PEAK_THRESHOLD_PCT, abs=0.0001
        ), f"capacity_peak_threshold_pct should default to 0.85, got {defaulted['capacity_peak_threshold_pct']!r}"
        assert defaulted["capacity_lock_threshold_pct"] == pytest.approx(
            DEFAULT_CAPACITY_LOCK_THRESHOLD_PCT, abs=0.0001
        ), f"capacity_lock_threshold_pct should default to 0.97, got {defaulted['capacity_lock_threshold_pct']!r}"
        assert defaulted["capacity_lock_blockout_max_rank"] == DEFAULT_CAPACITY_LOCK_BLOCKOUT_MAX_RANK
        assert (
            defaulted["delinquency_suspension_threshold"]
            == DEFAULT_DELINQUENCY_SUSPENSION_THRESHOLD
        )
        assert defaulted["default_threshold"] == DEFAULT_DEFAULT_THRESHOLD
        assert defaulted["sharing_case_auto_open_score"] == DEFAULT_SHARING_CASE_AUTO_OPEN_SCORE

        overridden = create_program(
            api,
            season_year=2028,
            capacity_peak_threshold_pct=0.80,
            capacity_lock_threshold_pct=0.95,
            capacity_lock_blockout_max_rank=1,
            delinquency_suspension_threshold=3,
            default_threshold=4,
            sharing_case_auto_open_score=50,
        )
        assert overridden["capacity_peak_threshold_pct"] == pytest.approx(0.80, abs=0.0001)
        assert overridden["capacity_lock_threshold_pct"] == pytest.approx(0.95, abs=0.0001)
        assert overridden["capacity_lock_blockout_max_rank"] == 1
        assert overridden["delinquency_suspension_threshold"] == 3
        assert overridden["default_threshold"] == 4
        assert overridden["sharing_case_auto_open_score"] == 50


class TestPassTierRecord:
    """A tier stores exactly what the designer supplied and starts in DRAFT."""

    def test_reading_a_tier_returns_the_stored_row(self, api, design_program):
        """The three benefits and the peak-day policy pair round-trip unchanged.

        PRD: "A tier enters life in `DRAFT` and is unsellable there."

        Design: Corner/entities/pass_tier_retrieval_returns_the_stored_row
        """
        created = validate_success(
            api.create_pass_tier(
                pass_tier_payload(
                    design_program.id,
                    name="SILVER",
                    tier_rank=2,
                    base_price_cents=18000,
                    parking_benefit=ParkingBenefit.DISCOUNT.value,
                    in_park_discount_pct=0.10,
                    reservation_required_on_peak=True,
                    peak_reservation_quota=3,
                ),
                headers=program_admin_headers(),
            ),
            201,
        )

        read_back = validate_success(
            api.get_pass_tier(created["id"], headers=program_admin_headers())
        )

        assert read_back["name"] == "SILVER", f"name should round-trip, got {read_back['name']!r}"
        assert read_back["tier_rank"] == 2, f"tier_rank should round-trip, got {read_back['tier_rank']!r}"
        assert read_back["base_price_cents"] == 18000
        assert read_back["parking_benefit"] == ParkingBenefit.DISCOUNT.value
        assert read_back["in_park_discount_pct"] == pytest.approx(0.10, abs=0.0001)
        assert read_back["reservation_required_on_peak"] is True
        assert read_back["peak_reservation_quota"] == 3
        assert read_back["status"] == TierStatus.DRAFT.value, (
            f"a new tier should be in DRAFT, got {read_back['status']!r}"
        )
        assert_version(read_back, 1, "pass tier")

    @pytest.mark.parametrize(
        "overrides",
        [
            {"tier_rank": 10},
            {"in_park_discount_pct": 0.45},
            {"parking_benefit": "VALET"},
        ],
        ids=["rank-above-nine", "discount-above-thirty-percent", "benefit-outside-enum"],
    )
    def test_values_outside_the_declared_bands_are_rejected(self, api, design_program, overrides):
        """A range or enumeration breach is a schema failure, not a business one.

        PRD: "**Schema** — on write endpoints, an unknown field, a missing required
        field, a wrong JSON type, a malformed date or timestamp, a numeric value outside
        a declared range, or a value outside a declared enumeration, all yielding
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/pass_tier_rank_above_the_declared_maximum_is_rejected
        """
        response = api.create_pass_tier(
            pass_tier_payload(design_program.id, **overrides), headers=program_admin_headers()
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        _, meta = validate_paginated(
            api.list_pass_tiers(
                headers=program_admin_headers(), params={"program_id": design_program.id}
            )
        )
        assert meta["total_count"] == 0, (
            f"the rejected design must not have been stored, got {meta['total_count']!r} tiers"
        )


class TestProgrammeLifecycleSteps:
    """The lifecycle advances one sanctioned step at a time."""

    def test_design_to_sales_open_needs_a_published_tier_and_then_permits_sales(
        self, api, design_program
    ):
        """Opening sales requires a sellable tier and makes the sale legal.

        PRD: "Moving `DESIGN → SALES_OPEN` requires that at least one pass tier of this
        programme has reached `PUBLISHED`; without a sellable tier the programme cannot
        open for sales."

        Design: Corner/state_machines/program_advance_status_design_to_sales_open
        """
        tier = create_tier(api, design_program.id, publish=False)
        publish_tier(api, tier["id"])

        advanced = advance_program(api, design_program.id, ProgramStatus.SALES_OPEN.value)

        assert advanced["status"] == ProgramStatus.SALES_OPEN.value, (
            f"the programme should have reached SALES_OPEN, got {advanced['status']!r}"
        )
        assert_version(advanced, 2, "pass programme")
        _, meta = validate_paginated(
            api.list_pass_programs(
                headers=program_admin_headers(),
                params={"status": ProgramStatus.SALES_OPEN.value},
            )
        )
        assert meta["total_count"] == 1, (
            f"the filtered listing should find the open programme, got {meta['total_count']!r}"
        )
        holder = create_passholder(api)
        sold = validate_success(
            api.create_season_pass(
                season_pass_payload(design_program.id, tier["id"], holder["id"]),
                headers=clerk_headers(),
            ),
            201,
        )
        assert sold["pass_status"] == PassStatus.PENDING_PROCESSING.value, (
            f"the sale should now succeed, got {sold['pass_status']!r}"
        )

    def test_a_tier_cannot_be_designed_once_the_season_is_active(self, api):
        """Tier design is gated on the programme status, calendar writes are not.

        PRD: "Designing a pass tier requires the programme to be in `DESIGN` or
        `SALES_OPEN`."

        Design: Corner/state_machines/pass_tier_creation_after_season_active_is_rejected
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        create_park_day(api, program.id, "2026-09-01")
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)

        response = api.create_pass_tier(
            pass_tier_payload(program.id, name="GOLD", tier_rank=3, base_price_cents=30000),
            headers=program_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PROGRAM_STATUS_INVALID.value, 409)
        _, meta = validate_paginated(
            api.list_pass_tiers(headers=program_admin_headers(), params={"program_id": program.id})
        )
        assert meta["total_count"] == 1, (
            f"the refused design must not have been stored, got {meta['total_count']!r} tiers"
        )
        later_day = api.create_park_day(
            park_day_payload(program.id, "2026-09-02"), headers=program_admin_headers()
        )
        validate_success(later_day, 201)

    def test_the_lifecycle_refuses_to_skip_a_step(self, api, design_program):
        """Only the declared path and its single shortcut are permitted.

        PRD: "The permitted path is `DESIGN → SALES_OPEN → SEASON_ACTIVE → RENEWAL_OPEN
        → CLOSED`, with exactly one sanctioned shortcut: `SEASON_ACTIVE → CLOSED`."

        Design: Corner/state_machines/program_cannot_advance_from_design_to_season_active
        """
        create_tier(api, design_program.id)

        skipped = api.advance_program_status(
            design_program.id,
            advance_status_payload(ProgramStatus.SEASON_ACTIVE.value),
            headers=program_admin_headers(),
        )
        validate_error(skipped, ApiErrorId.ERR_INVALID_PROGRAM_TRANSITION.value, 409)

        straight_to_closed = api.advance_program_status(
            design_program.id,
            advance_status_payload(ProgramStatus.CLOSED.value),
            headers=program_admin_headers(),
        )
        validate_error(straight_to_closed, ApiErrorId.ERR_INVALID_PROGRAM_TRANSITION.value, 409)

        unchanged = validate_success(
            api.get_pass_program(design_program.id, headers=program_admin_headers())
        )
        assert unchanged["status"] == ProgramStatus.DESIGN.value, (
            f"the refused transitions must leave the programme in DESIGN, got {unchanged['status']!r}"
        )
        assert_version(unchanged, 1, "pass programme")
        assert (
            advance_program(api, design_program.id, ProgramStatus.SALES_OPEN.value)["status"]
            == ProgramStatus.SALES_OPEN.value
        ), "the one legal next step should still be available"

    def test_a_closed_programme_is_terminal(self, api):
        """No transition leads out of CLOSED, not even a repeat of it.

        PRD: "Any other pairing — a jump from `DESIGN` or `SALES_OPEN` straight to
        `CLOSED`, a step backwards, a move out of the terminal `CLOSED` — is rejected
        with `ERR_INVALID_PROGRAM_TRANSITION` (HTTP 409), and so is a legal pairing whose
        precondition fails."

        Design: Corner/state_machines/closed_program_cannot_advance_any_further
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        create_park_day(api, program.id, "2026-08-26")
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        closed = advance_program(api, program.id, ProgramStatus.CLOSED.value)
        assert closed["status"] == ProgramStatus.CLOSED.value, (
            f"the sanctioned shortcut should reach CLOSED, got {closed['status']!r}"
        )

        backwards = api.advance_program_status(
            program.id,
            advance_status_payload(ProgramStatus.RENEWAL_OPEN.value),
            headers=program_admin_headers(),
        )
        validate_error(backwards, ApiErrorId.ERR_INVALID_PROGRAM_TRANSITION.value, 409)

        repeat = api.advance_program_status(
            program.id,
            advance_status_payload(ProgramStatus.CLOSED.value),
            headers=program_admin_headers(),
        )
        validate_error(repeat, ApiErrorId.ERR_INVALID_PROGRAM_TRANSITION.value, 409)

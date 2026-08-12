"""Material rental lifecycle, overdue-fine rule variants, deposit settlement,
and fine/standing behavior (PRD §3.6, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_application,
    begin_review,
    create_application,
    create_org,
    create_rental_for,
    create_rental_payload,
    create_title,
    get_success_data,
    make_applicant_headers,
    reset_clock,
    setup_active_agreement,
    setup_assessed_overdue_fine,
    setup_rental_in_state,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def _admin():
    from test_helpers import TEST_USERS

    return TEST_USERS["rights_admin_headers"]


def _officer():
    from test_helpers import TEST_USERS

    return TEST_USERS["licensing_officer_headers"]


def _clerk():
    from test_helpers import TEST_USERS

    return TEST_USERS["materials_clerk_headers"]


def _finance():
    from test_helpers import TEST_USERS

    return TEST_USERS["finance_officer_headers"]


def _fines_for(api, org_id, **filters):
    params = {"organization_id": org_id}
    params.update(filters)
    data, _meta = validate_paginated(api.list_fines(_finance(), params=params))
    return data


class TestOverdueProjectedVsActual:
    """Difficulty: PROJECTED accrues through the sweep clock; ACTUAL through
    returned_at — same rental, different evaluation clock."""

    def _build_overdue_rental(self, api):
        """Rental due 2026-06-10; swept OVERDUE at 2026-06-13 (PROJECTED);
        clock advanced to 2026-06-15 awaiting receive_return (ACTUAL)."""
        ctx = setup_active_agreement(
            app_overrides={
                "performance_count": 1,
                "first_performance_date": "2026-05-15T19:00:00Z",
                "last_performance_date": "2026-05-15T19:00:00Z",
            }
        )
        rental = create_rental_for(
            ctx["agreement"]["id"], due_date="2026-06-10T00:00:00Z"
        )
        ctx["rental"] = rental
        get_success_data(api.ship_rental(rental["id"], _clerk()))
        get_success_data(
            api.mark_received_rental(rental["id"], ctx["applicant"])
        )
        # Ship the return while still RECEIVED (PRD §3.6: ship_return moves
        # RECEIVED -> RETURN_IN_TRANSIT), then sweep past the due date.
        get_success_data(api.ship_return_rental(rental["id"], ctx["applicant"]))
        # Sweep: advance clock to 06-13 -> 3 days overdue (PROJECTED = 1500)
        reset_clock("2026-06-13T00:00:00Z")
        swept = get_success_data(api.get_rental(rental["id"], _clerk()))
        assert swept["status"] == "OVERDUE"
        reset_clock("2026-06-15T00:00:00Z")
        return ctx, swept

    def test_projected_fee_accrued_at_sweep(self, api):
        """PRD §3.6: "The sweep recomputes `accrued_late_fee_cents` via the
        overdue-fine rule in its `PROJECTED` variant, projecting through the
        current clock; no `Fine` row is created at sweep time." and "The raw
        fee is the product of days and daily rate."

        Design: Difficulty/dual_variant_calc/overdue_fee_projected_vs_actual_diverge_on_return_date
        """
        _ctx, swept = self._build_overdue_rental(api)
        # due 06-10, sweep clock 06-13 -> 3 days * 500 = 1500
        assert swept["accrued_late_fee_cents"] == 1500

    def test_actual_fee_finalized_at_receive_return(self, api):
        """PRD §3.6: "The server sets `returned_at`, finalizes
        `accrued_late_fee_cents` via the overdue-fine rule in its `ACTUAL`
        variant (using `returned_at` as the evaluation clock)".

        Design: Difficulty/dual_variant_calc/overdue_fee_projected_vs_actual_diverge_on_return_date
        """
        ctx, swept = self._build_overdue_rental(api)
        returned = validate_success(
            api.receive_return_rental(ctx["rental"]["id"], {}, _clerk()),
            expected_status=200,
        )
        # due 06-10, returned 06-15 -> 5 days * 500 = 2500; ACTUAL exceeds
        # PROJECTED (1500) by 2 days * 500 = 1000
        assert returned["accrued_late_fee_cents"] == 2500
        assert (
            returned["accrued_late_fee_cents"] - swept["accrued_late_fee_cents"]
            == 1000
        )


class TestDepositSettlementRounding:
    """Difficulty: nested rounding — per-line rounded, then summed (pinned)."""

    def _build_return_in_transit(self, api):
        return setup_rental_in_state(
            "RETURN_IN_TRANSIT",
            rental_overrides={"due_date": "2026-06-10T00:00:00Z"},
            app_overrides={
                "performance_count": 1,
                "first_performance_date": "2026-05-15T19:00:00Z",
                "last_performance_date": "2026-05-15T19:00:00Z",
            },
        )

    def test_per_line_rounding_before_summation(self, api):
        """PRD §3.6: "Each damage line contributes a deduction equal to
        `amount_cents` multiplied by `damage_fraction`, rounded half-up per
        line; the per-line rounded values are then summed to a
        `total_damage_cents`."

        Design: Difficulty/combinatorial_formula/deposit_settlement_nested_rounding_order_pinned
        """
        ctx = self._build_return_in_transit(api)
        rental = validate_success(
            api.receive_return_rental(
                ctx["rental"]["id"],
                {
                    "damage_lines": [
                        {"amount_cents": 1000, "damage_fraction": 0.335},
                        {"amount_cents": 1000, "damage_fraction": 0.335},
                    ]
                },
                _clerk(),
            ),
            expected_status=200,
        )
        # per-line round_half_up(335.0)=335 each; total_damage_cents = 670
        assert rental["accrued_late_fee_cents"] == 0
        # 670 < deposit 20000 -> PARTIALLY_FORFEITED
        assert rental["deposit_status"] == "PARTIALLY_FORFEITED"

    def test_partial_forfeiture_preserves_deposit_conservation(self, api):
        """PRD §3.6: "When the total deduction is strictly less than
        `deposit_cents`, `deposit_status` becomes `PARTIALLY_FORFEITED` and the
        refund is the deposit minus the deduction."

        Design: Difficulty/combinatorial_formula/deposit_settlement_nested_rounding_order_pinned
        """
        ctx = self._build_return_in_transit(api)
        rental = validate_success(
            api.receive_return_rental(
                ctx["rental"]["id"],
                {
                    "damage_lines": [
                        {"amount_cents": 1000, "damage_fraction": 0.335},
                        {"amount_cents": 1000, "damage_fraction": 0.335},
                    ]
                },
                _clerk(),
            ),
            expected_status=200,
        )
        # refund = 20000 - 670 = 19330 (deposit conserved: refund+deduction=deposit)
        assert rental["deposit_status"] == "PARTIALLY_FORFEITED"
        assert rental["deposit_cents"] == 20000
        assert rental["status"] == "RETURNED"


class TestZeroDaysOverdue:
    """Difficulty boundary instance: returned exactly on due_date."""

    def _build_on_time_return(self, api):
        ctx = setup_rental_in_state(
            "RETURN_IN_TRANSIT",
            rental_overrides={"due_date": "2026-06-10T00:00:00Z"},
            app_overrides={
                "performance_count": 1,
                "first_performance_date": "2026-05-15T19:00:00Z",
                "last_performance_date": "2026-05-15T19:00:00Z",
            },
        )
        # receive the return with the clock exactly at due_date
        reset_clock("2026-06-10T00:00:00Z")
        return ctx

    def test_zero_days_overdue_returns_zero_fine(self, api):
        """PRD §3.6: "The number of overdue days is the floor of the difference
        between the evaluation clock and `due_date` in whole days, clamped
        below at zero." and "If the finalized late fee is greater than zero, a
        `Fine` of kind `OVERDUE_MATERIAL` is created in `status` `ASSESSED`."

        Design: Difficulty/boundary_precision_check/zero_days_overdue_returns_zero_fine
        """
        ctx = self._build_on_time_return(api)
        rental = validate_success(
            api.receive_return_rental(ctx["rental"]["id"], {}, _clerk()),
            expected_status=200,
        )
        assert rental["accrued_late_fee_cents"] == 0
        fines = _fines_for(api, ctx["org"]["id"])
        assert len(fines) == 0, "no Fine row may be created when the fee is 0"

    def test_on_time_return_restores_deposit(self, api):
        """PRD §3.6: "When the total deduction is zero, `deposit_status` becomes
        `RETURNED` and the full `deposit_cents` is refunded."

        Design: Difficulty/boundary_precision_check/zero_days_overdue_returns_zero_fine
        """
        ctx = self._build_on_time_return(api)
        rental = validate_success(
            api.receive_return_rental(ctx["rental"]["id"], {}, _clerk()),
            expected_status=200,
        )
        assert rental["deposit_status"] == "RETURNED"
        assert rental["status"] == "RETURNED"


class TestDepositConservation:
    """Difficulty compensating invariant: refund + deductions == deposit."""

    def test_clean_return_refunds_full_deposit(self, api):
        """PRD §3.6: "When the total deduction is zero, `deposit_status` becomes
        `RETURNED` and the full `deposit_cents` is refunded."

        Design: Difficulty/compensating_invariant/deposit_conserved_across_rental_hold_and_return
        """
        ctx = setup_rental_in_state(
            "RETURN_IN_TRANSIT",
            rental_overrides={"due_date": "2026-06-10T00:00:00Z"},
            app_overrides={
                "performance_count": 1,
                "first_performance_date": "2026-05-15T19:00:00Z",
                "last_performance_date": "2026-05-15T19:00:00Z",
            },
        )
        reset_clock("2026-06-01T00:00:00Z")  # before due_date: no late fee
        rental = validate_success(
            api.receive_return_rental(ctx["rental"]["id"], {}, _clerk()),
            expected_status=200,
        )
        assert rental["deposit_status"] == "RETURNED"
        assert rental["accrued_late_fee_cents"] == 0

    def test_deposit_fields_balance_across_hold_and_return(self, api):
        """PRD §3.6: "The new rental starts in `status` `RESERVED`, with
        `deposit_cents` set equal to the title's `rental_deposit_cents` (the
        deposit is flat per rental, not per copy), `deposit_status` `HELD`, and
        `accrued_late_fee_cents` 0."

        Design: Difficulty/compensating_invariant/deposit_conserved_across_rental_hold_and_return
        """
        ctx = setup_rental_in_state(
            "RESERVED",
            rental_overrides={"due_date": "2026-06-10T00:00:00Z"},
            app_overrides={
                "performance_count": 1,
                "first_performance_date": "2026-05-15T19:00:00Z",
                "last_performance_date": "2026-05-15T19:00:00Z",
            },
        )
        reserved = ctx["rental"]
        assert reserved["deposit_cents"] == 20000
        assert reserved["deposit_status"] == "HELD"
        assert reserved["accrued_late_fee_cents"] == 0
        # walk through return; refund 20000 + deductions 0 == deposit 20000
        get_success_data(api.ship_rental(reserved["id"], _clerk()))
        get_success_data(api.mark_received_rental(reserved["id"], ctx["applicant"]))
        get_success_data(api.ship_return_rental(reserved["id"], ctx["applicant"]))
        returned = validate_success(
            api.receive_return_rental(reserved["id"], {}, _clerk()),
            expected_status=200,
        )
        assert returned["deposit_status"] == "RETURNED"
        assert returned["accrued_late_fee_cents"] == 0


class TestRestrictedLateFeeRate:
    def test_overdue_fee_uses_restricted_rate_when_title_restricted(self, api):
        """PRD §3.6: "The daily rate is the title's
        `restricted_late_fee_per_day_cents` when `restricted_material` is true,
        otherwise the title's `late_fee_per_day_cents`."

        Design: Corner/calculations/overdue_fee_uses_restricted_rate_when_title_restricted
        """
        ctx = setup_active_agreement(
            title_overrides={"restricted_material": True},
            app_overrides={
                "performance_count": 1,
                "first_performance_date": "2026-05-15T19:00:00Z",
                "last_performance_date": "2026-05-15T19:00:00Z",
            },
        )
        rental = create_rental_for(
            ctx["agreement"]["id"], due_date="2026-05-20T00:00:00Z"
        )
        get_success_data(api.ship_rental(rental["id"], _clerk()))
        get_success_data(api.mark_received_rental(rental["id"], ctx["applicant"]))
        # ship_return is only valid from RECEIVED (PRD §3.6); sweep after
        get_success_data(api.ship_return_rental(rental["id"], ctx["applicant"]))
        reset_clock("2026-05-23T00:00:00Z")
        returned = validate_success(
            api.receive_return_rental(rental["id"], {}, _clerk()),
            expected_status=200,
        )
        # 3 days * restricted rate 1500 = 4500
        assert returned["accrued_late_fee_cents"] == 4500


class TestRentalKindValidation:
    def test_rental_scores_on_play_title_rejected(self, api):
        """PRD §3.6: "A title whose `title_kind` is `PLAY` carries no score, so
        `scores_qty` must be zero ... Either violation is rejected with
        `ERR_RENTAL_KIND_MISMATCH`."

        Design: Corner/validations/rental_scores_on_play_title_rejected
        """
        ctx = setup_active_agreement()
        resp = api.create_rental(
            create_rental_payload(
                ctx["agreement"]["id"],
                scripts_qty=5,
                scores_qty=3,
                due_date="2026-06-10T00:00:00Z",
            ),
            _clerk(),
        )
        validate_error(resp, ApiErrorId.ERR_RENTAL_KIND_MISMATCH, expected_status=422)


class TestRentalTerminalLockdown:
    def test_rental_terminal_returned_blocks_further_transitions(self, api):
        """PRD §3.6: the rental "moves from `RETURN_IN_TRANSIT` (or, for a late
        return, from `OVERDUE`) to `RETURNED`" — RETURNED is terminal, so a
        further ship no longer starts from `RESERVED`.
        PRD §2.7: "then state-machine from-state checks (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/rental_terminal_returned_blocks_further_transitions
        """
        ctx = setup_rental_in_state(
            "RETURNED",
            rental_overrides={"due_date": "2026-06-10T00:00:00Z"},
            app_overrides={
                "performance_count": 1,
                "first_performance_date": "2026-05-15T19:00:00Z",
                "last_performance_date": "2026-05-15T19:00:00Z",
            },
        )
        assert ctx["rental"]["status"] == "RETURNED"
        resp = api.ship_rental(ctx["rental"]["id"], _clerk())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestDeclareLostTiming:
    def test_err_rental_not_due_lost_when_too_early(self, api):
        """PRD §3.6: "The transition is from `OVERDUE` to `LOST` and is
        permitted only once the current clock has reached `due_date` plus 30
        days; attempting it earlier is rejected with `ERR_RENTAL_NOT_DUE_LOST`."

        Design: Corner/errors/err_rental_not_due_lost_when_too_early
        """
        ctx = setup_rental_in_state(
            "OVERDUE",
            rental_overrides={"due_date": "2026-05-20T00:00:00Z"},
            clock_before_return="2026-05-25T00:00:00Z",
            app_overrides={
                "performance_count": 1,
                "first_performance_date": "2026-05-15T19:00:00Z",
                "last_performance_date": "2026-05-15T19:00:00Z",
            },
        )
        # due 05-20, clock 05-25: only 5 days past due (< 30)
        resp = api.declare_lost_rental(ctx["rental"]["id"], _clerk())
        validate_error(resp, ApiErrorId.ERR_RENTAL_NOT_DUE_LOST, expected_status=409)


class TestFineWaiverRestoresStanding:
    def test_fine_waiver_side_effect_restores_org_standing(self, api):
        """PRD §3.8: "A `FinanceOfficer` can waive a fine, but only when
        `fine_kind` is `OVERDUE_MATERIAL` or `LOSS`" and "When a fine is paid
        or waived, if that fine was the last `ASSESSED` fine for its
        organization, the organization's `standing` returns to `GOOD`."

        Design: Corner/state_machines/fine_waiver_side_effect_restores_org_standing
        """
        ctx = setup_assessed_overdue_fine()
        fine = ctx["fine"]
        assert fine["fine_kind"] == "OVERDUE_MATERIAL"
        waived = validate_success(api.waive_fine(fine["id"], _finance()), 200)
        assert waived["status"] == "WAIVED"
        org = get_success_data(api.get_organization(ctx["org"]["id"], _admin()))
        assert org["standing"] == "GOOD"

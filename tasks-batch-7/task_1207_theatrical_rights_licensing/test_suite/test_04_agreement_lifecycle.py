"""Agreement lifecycle: parallel payment/license dimensions, amendments,
payments, cancellation cascades and refunds (PRD §3.4, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_application,
    begin_review,
    create_application,
    create_org,
    create_payment_payload,
    create_title,
    current_application_version,
    get_success_data,
    make_applicant_headers,
    reset_clock,
    setup_active_agreement,
    setup_pending_agreement,
    submit_application,
    validate_error,
    validate_success,
)


def _admin():
    from test_helpers import TEST_USERS

    return TEST_USERS["rights_admin_headers"]


def _finance():
    from test_helpers import TEST_USERS

    return TEST_USERS["finance_officer_headers"]


class TestParallelDimensions:
    """Difficulty: license_status and payment_status evolve independently."""

    def _pending_agreement_count2(self, api):
        return setup_pending_agreement(
            app_overrides={
                "performance_count": 2,
                "first_performance_date": "2026-06-01T19:00:00Z",
                "last_performance_date": "2026-06-02T19:00:00Z",
            }
        )

    def test_partial_payment_flips_payment_status_only(self, api):
        """PRD §3.4: "When the cumulative paid amount after a payment is still
        strictly less than the balance before the payment, `payment_status`
        moves to (or stays in) `PARTIALLY_PAID`." and "The two evolve
        independently except where a transition below pins them together."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_dimensions_payment_and_license_status
        """
        ctx = self._pending_agreement_count2(api)
        agreement = ctx["agreement"]
        quoted = agreement["quoted_royalty_total_cents"]
        # PER_PERFORMANCE base 50000, cap 100 (1.00), AMATEUR, 2 perfs
        assert quoted == 100000
        validate_success(
            api.create_payment(agreement["id"], {"amount_cents": 1000}, _finance()),
            expected_status=201,
        )
        after = get_success_data(api.get_agreement(agreement["id"], _admin()))
        assert after["payment_status"] == "PARTIALLY_PAID"
        assert after["license_status"] == "PENDING_PAYMENT"

    def test_partial_payment_decrements_balance(self, api):
        """PRD §3.4: "Each payment appends a `RoyaltyPayment` row and decrements
        `royalty_balance_cents` by `amount_cents`."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_dimensions_payment_and_license_status
        """
        ctx = self._pending_agreement_count2(api)
        agreement = ctx["agreement"]
        quoted = agreement["quoted_royalty_total_cents"]
        payment = validate_success(
            api.create_payment(agreement["id"], {"amount_cents": 1000}, _finance()),
            expected_status=201,
        )
        assert payment["amount_cents"] == 1000
        after = get_success_data(api.get_agreement(agreement["id"], _admin()))
        assert after["royalty_balance_cents"] == quoted - 1000
        assert after["license_status"] == "PENDING_PAYMENT"
        assert after["payment_status"] == "PARTIALLY_PAID"


class TestAmendments:
    def test_amendment_increments_agreement_version_and_seq(self, api):
        """PRD §3.4: "Applying the amendment increments `amendment_seq` by one
        and increments the agreement's `version` by one." and "an optional
        `new_window_end`".

        Design: Corner/endpoints/amendment_increments_agreement_version_and_seq
        """
        ctx = setup_active_agreement()
        agreement = ctx["agreement"]
        before = get_success_data(api.get_agreement(agreement["id"], _admin()))
        assert before["amendment_seq"] == 0
        amended = validate_success(
            api.create_amendment(
                agreement["id"],
                {
                    "expected_agreement_version": before["version"],
                    "new_window_end": "2026-06-05T00:00:00Z",
                    "amendment_note": "Extend window",
                },
                _admin(),
            ),
            expected_status=200,
        )
        assert amended["amendment_seq"] == 1
        assert amended["version"] == before["version"] + 1
        # Compare instants, not wire strings: PRD §2.4 mandates the 3-digit-ms
        # format only for created_at/updated_at; other datetimes are "ISO 8601
        # UTC", so both "...T00:00:00Z" and "...T00:00:00.000Z" are faithful.
        from datetime import datetime

        def _parse(s):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))

        assert _parse(amended["window_end"]) == _parse("2026-06-05T00:00:00Z")

    def test_err_amendment_on_terminal_after_cancel(self, api):
        """PRD §3.4: "Amendments are rejected with `ERR_AMENDMENT_ON_TERMINAL`
        when the target agreement is in `COMPLETED`, `CANCELLED`, or
        `BREACHED`."

        Design: Corner/errors/err_amendment_on_terminal_after_cancel
        """
        ctx = setup_active_agreement(
            app_overrides={
                "first_performance_date": "2026-07-01T19:00:00Z",
                "last_performance_date": "2026-07-01T19:00:00Z",
            }
        )
        agreement = ctx["agreement"]
        cancelled = validate_success(
            api.cancel_agreement(agreement["id"], {"reason": "c"}, _admin()),
            expected_status=200,
        )
        assert cancelled["license_status"] == "CANCELLED"
        current = get_success_data(api.get_agreement(agreement["id"], _admin()))
        resp = api.create_amendment(
            agreement["id"],
            {
                "expected_agreement_version": current["version"],
                "amendment_note": "try",
            },
            _admin(),
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_ON_TERMINAL, expected_status=409)


class TestPaymentBounds:
    def test_payment_exceeding_balance_rejected(self, api):
        """PRD §3.4: "The amount must be at least 1 cent and at most the current
        `royalty_balance_cents`; a payment violating either bound is rejected
        with `ERR_PAYMENT_AMOUNT_INVALID`."

        Design: Corner/validations/payment_exceeding_balance_rejected
        """
        ctx = setup_pending_agreement()
        agreement = ctx["agreement"]
        # quoted balance is 50000 (base 50000, tier 1.00, AMATEUR, 1 perf)
        assert agreement["royalty_balance_cents"] == 50000
        resp = api.create_payment(
            agreement["id"], {"amount_cents": 999999}, _finance()
        )
        validate_error(
            resp, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID, expected_status=422
        )


class TestCancelCascade:
    """Difficulty: depth-2 cascade from agreement cancel to performances."""

    def _active_with_two_performances(self, api):
        ctx = setup_active_agreement(
            app_overrides={
                "performance_count": 2,
                "first_performance_date": "2026-07-01T19:00:00Z",
                "last_performance_date": "2026-07-02T19:00:00Z",
            }
        )
        get_success_data(
            api.create_payment(
                ctx["agreement"]["id"], {"amount_cents": 50000}, _finance()
            )
        )
        perf1 = get_success_data(
            api.create_performance(
                ctx["agreement"]["id"],
                {"performance_at": "2026-07-01T19:00:00Z"},
                ctx["applicant"],
            )
        )
        perf2 = get_success_data(
            api.create_performance(
                ctx["agreement"]["id"],
                {"performance_at": "2026-07-02T19:00:00Z"},
                ctx["applicant"],
            )
        )
        return ctx, perf1, perf2

    def test_cancel_cascades_to_all_scheduled_performances(self, api):
        """PRD §3.5: "When it lands, every `Performance` row moves to
        `CANCELLED`."

        Design: Difficulty/transitive_cascade/cancel_cascade_two_deep_agreement_performance
        """
        ctx, perf1, perf2 = self._active_with_two_performances(api)
        cancelled = validate_success(
            api.cancel_agreement(
                ctx["agreement"]["id"], {"reason": "Producer withdrew"}, _admin()
            ),
            expected_status=200,
        )
        assert cancelled["license_status"] == "CANCELLED"
        p1 = get_success_data(api.get_performance(perf1["id"], _admin()))
        p2 = get_success_data(api.get_performance(perf2["id"], _admin()))
        assert p1["status"] == "CANCELLED"
        assert p2["status"] == "CANCELLED"

    def test_cancel_runs_cancellation_refund_rule(self, api):
        """PRD §3.5: "The cancellation-refund rule is applied across the
        agreement's payments: the rule measures `days_until_window_start` as
        the whole days between the current clock and `window_start`, applies a
        refund fraction of 1.00 when at least 30 days remain".

        Design: Difficulty/transitive_cascade/cancel_cascade_two_deep_agreement_performance
        """
        from test_helpers import validate_paginated

        ctx, _p1, _p2 = self._active_with_two_performances(api)
        # clock is 2026-05-01; window_start 2026-07-01 -> 60+ days -> fraction 1.00
        cancelled = validate_success(
            api.cancel_agreement(
                ctx["agreement"]["id"], {"reason": "Producer withdrew"}, _admin()
            ),
            expected_status=200,
        )
        assert cancelled["license_status"] == "CANCELLED"
        # all SCHEDULED performances cancelled by the cascade
        perfs, _meta = validate_paginated(
            api.list_agreement_performances(ctx["agreement"]["id"], _admin())
        )
        assert all(p["status"] == "CANCELLED" for p in perfs)
        assert len(perfs) == 2

    def test_cascade_side_effects_from_agreement_cancel(self, api):
        """PRD §3.5: "When it lands, every `Performance` row moves to
        `CANCELLED`. ... Every `RecordingGrant` in `REQUESTED` or `APPROVED`
        moves to `REVOKED`."

        Design: Corner/cross_cutting_complexity_layers/cascade_side_effects_from_agreement_cancel
        """
        from test_helpers import create_recording_grant_payload

        ctx = setup_active_agreement(
            app_overrides={
                "first_performance_date": "2026-07-01T19:00:00Z",
                "last_performance_date": "2026-07-01T19:00:00Z",
            }
        )
        perf = get_success_data(
            api.create_performance(
                ctx["agreement"]["id"],
                {"performance_at": "2026-07-01T19:00:00Z"},
                ctx["applicant"],
            )
        )
        grant = get_success_data(
            api.create_recording_grant(
                create_recording_grant_payload(ctx["agreement"]["id"]),
                ctx["applicant"],
            )
        )
        grant = get_success_data(api.approve_recording_grant(grant["id"], _admin()))
        assert grant["status"] == "APPROVED"
        cancelled = validate_success(
            api.cancel_agreement(ctx["agreement"]["id"], {"reason": "x"}, _admin()),
            expected_status=200,
        )
        assert cancelled["license_status"] == "CANCELLED"
        p = get_success_data(api.get_performance(perf["id"], _admin()))
        g = get_success_data(api.get_recording_grant(grant["id"], _admin()))
        assert p["status"] == "CANCELLED"
        assert g["status"] == "REVOKED"


class TestCancellationRefund:
    def test_cancellation_refund_fraction_full_when_far_out(self, api):
        """PRD §3.5: "applies a refund fraction of 1.00 when at least 30 days
        remain ... When the full royalty was returned, `payment_status` moves
        to `REFUNDED`."

        Design: Corner/calculations/cancellation_refund_fraction_full_when_far_out
        """
        ctx = setup_pending_agreement(
            app_overrides={
                "performance_count": 1,
                "first_performance_date": "2026-07-01T19:00:00Z",
                "last_performance_date": "2026-07-01T19:00:00Z",
            }
        )
        agreement = ctx["agreement"]
        # quoted = 50000 (base 50000, tier 1.00, AMATEUR, 1 perf); pay in full
        validate_success(
            api.create_payment(agreement["id"], {"amount_cents": 50000}, _finance()),
            expected_status=201,
        )
        get_success_data(api.activate_agreement(agreement["id"], _admin()))
        cancelled = validate_success(
            api.cancel_agreement(agreement["id"], {"reason": "early cancel"}, _admin()),
            expected_status=200,
        )
        assert cancelled["license_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "REFUNDED"

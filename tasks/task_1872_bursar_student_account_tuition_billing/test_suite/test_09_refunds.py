"""Refund tier/pro-rata computation, disposition side effects, and exit-window
claims (PRD §3.9, §2.5)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    enroll,
    get_success_data,
    make_payment,
    make_student,
    read_account,
    read_ledger,
    refund_for_enrollment,
    setup_account_with_enrollment,
    setup_calculated_refund,
    validate_error,
    validate_paginated,
    validate_success,
)

_MGR = TEST_USERS["bursar_manager_headers"]
_STAFF = TEST_USERS["bursar_staff_headers"]


class TestRefundTieredVsProRata:
    """Identical withdrawal data, divergent variants by term policy (§3.9)."""

    def test_schedule_tiered_variant_pays_mid_tier(self, api,
                                                   bursar_staff_headers):
        """PRD §3.9: "Under `SCHEDULE_TIERED`, the effective date is compared
        against the term's milestones with **inclusive** boundaries: on or
        before `full_refund_end_date` the fraction is 1.00; on or before
        `mid_refund_end_date` it is 0.50; on or before the
        `withdrawal_deadline` it is 0.25"."

        Design: Difficulty/dual_variant_calc/refund_tiered_vs_pro_rata
        """
        ctx = setup_calculated_refund(
            credit_hours=12, action="withdraw", effective_date="2026-09-21",
            term_overrides={"code": "FALL-T", "refund_policy": "SCHEDULE_TIERED"},
            external_ref="S-A",
        )
        refund = ctx["refund"]
        assert refund["policy_variant"] == "SCHEDULE_TIERED"
        assert refund["status"] == "CALCULATED"
        # 2026-09-21 is past full_refund_end (09-07) but within mid tier.
        assert refund["pct_applied"] == pytest.approx(0.5)
        assert refund["amount_cents"] == 217500

    def test_pro_rata_variant_pays_continuous_fraction(self, api,
                                                       bursar_staff_headers):
        """PRD §3.9: "Under `PRO_RATA`, the fraction is continuous: the term
        length in whole days is measured from `start_date` to `end_date`, the
        elapsed whole days from `start_date` to the effective date are counted
        (never negative), and when elapsed time exceeds sixty percent of the
        term the refund is zero; otherwise the fraction is one minus the
        elapsed-to-total day ratio, rounded half up to four decimal places."

        Design: Difficulty/dual_variant_calc/refund_tiered_vs_pro_rata
        """
        ctx = setup_calculated_refund(
            credit_hours=12, action="withdraw", effective_date="2026-09-21",
            term_overrides={"code": "FALL-P", "refund_policy": "PRO_RATA"},
            external_ref="S-B",
        )
        refund = ctx["refund"]
        assert refund["policy_variant"] == "PRO_RATA"
        # 28 elapsed of 109 days -> 1 - 0.256881 = 0.7431; 435000 x 0.7431.
        assert refund["pct_applied"] == pytest.approx(0.7431)
        assert refund["amount_cents"] == 323249


class TestRefundTierDateBoundary:
    """Inclusive milestone boundaries in the SCHEDULE_TIERED variant (§3.9)."""

    def test_effective_on_full_refund_end_date_earns_100_pct(self, api):
        """PRD §3.9: "on or before `full_refund_end_date` the fraction is 1.00"
        and "Effective dates landing exactly on a milestone earn the higher
        tier."

        Design: Difficulty/boundary_precision_check/refund_tier_date_boundary
        """
        ctx = setup_calculated_refund(
            credit_hours=12, action="withdraw", effective_date="2026-09-07",
            external_ref="S-OC",
        )
        refund = ctx["refund"]
        assert refund["pct_applied"] == pytest.approx(1.0)
        assert refund["amount_cents"] == 435000

    def test_one_day_past_full_refund_end_drops_to_50_pct(self, api):
        """PRD §3.9: "on or before `mid_refund_end_date` it is 0.50".

        Design: Difficulty/boundary_precision_check/refund_tier_date_boundary
        """
        ctx = setup_calculated_refund(
            credit_hours=12, action="withdraw", effective_date="2026-09-08",
            external_ref="S-DA",
        )
        refund = ctx["refund"]
        assert refund["pct_applied"] == pytest.approx(0.5)
        assert refund["amount_cents"] == 217500


def test_pro_rata_sixty_percent_cutoff(api, bursar_staff_headers):
    """PRD §3.9: "when elapsed time exceeds sixty percent of the term the
    refund is zero; otherwise the fraction is one minus the elapsed-to-total
    day ratio, rounded half up to four decimal places."

    Design: Corner/calculations/pro_rata_sixty_percent_cutoff
    """
    ctx = setup_account_with_enrollment(
        credit_hours=12, external_ref="S-CI",
        term_overrides={"code": "FALL-PR", "refund_policy": "PRO_RATA"},
    )
    term = ctx["term"]
    s_b = make_student("S-CO", "Cutoff Out")
    enr_b = enroll(s_b["id"], term["id"], credit_hours=12)

    # 65 of 109 days elapsed (0.5963): still refundable.
    get_success_data(api.withdraw_enrollment(
        ctx["enrollment"]["id"], {"effective_date": "2026-10-28"},
        TEST_USERS["registrar_headers"],
    ))
    # 66 of 109 days elapsed (0.6055 > 0.60): refund is zero.
    get_success_data(api.withdraw_enrollment(
        enr_b["id"], {"effective_date": "2026-10-29"},
        TEST_USERS["registrar_headers"],
    ))

    refund_a = refund_for_enrollment(ctx["enrollment"]["id"])
    assert refund_a["pct_applied"] == pytest.approx(0.4037)
    assert refund_a["amount_cents"] == 175610
    refund_b = refund_for_enrollment(enr_b["id"])
    assert refund_b["pct_applied"] == 0
    assert refund_b["amount_cents"] == 0


class TestRefundPayoutEvaluationOrder:
    """Approve posts reversal first; payout is sized from the pre-payout
    balance (PRD §3.9, §2.5)."""

    def test_approve_posts_reversal_and_payout_landing_at_zero(
        self, api, bursar_manager_headers
    ):
        """PRD §3.9: "Approving posts a `CHARGE_REVERSAL` ledger entry for the
        refund amount with `charge_kind` `TUITION` ...; the account is then
        recomputed, and if the reversal has pushed the balance negative, a
        `REFUND_PAYOUT` entry for the absolute value of that negative balance
        is posted so the account lands at exactly zero".

        Design: Difficulty/combinatorial_formula/refund_payout_evaluation_order
        """
        ctx = setup_account_with_enrollment(credit_hours=1, external_ref="S-PYO")
        acc = ctx["account_id"]
        make_payment(acc, 50000, method="ACH")
        get_success_data(api.withdraw_enrollment(
            ctx["enrollment"]["id"], {"effective_date": "2026-09-05"},
            TEST_USERS["registrar_headers"],
        ))
        refund = refund_for_enrollment(ctx["enrollment"]["id"])
        assert refund["amount_cents"] == 50000  # 100% tier (09-05 <= 09-07)

        posted = validate_success(
            api.transition_refund(refund["id"], {"action": "APPROVE"},
                                  bursar_manager_headers),
            200,
        )
        assert posted["status"] == "POSTED"
        account = read_account(acc)
        assert account["balance_cents"] == 0, "payout must zero the account"
        assert account["payments_total_cents"] == 50000
        assert account["charges_total_cents"] == 0

    def test_payout_sized_from_pre_payout_balance(self, api,
                                                  bursar_manager_headers):
        """PRD §2.5: "a `REFUND_PAYOUT` entry's amount is itself fixed at
        posting time from the balance that existed immediately before the
        payout" — the payout does not feed back into its own base.

        Design: Difficulty/combinatorial_formula/refund_payout_evaluation_order
        """
        ctx = setup_account_with_enrollment(credit_hours=1, external_ref="S-PPB")
        acc = ctx["account_id"]
        make_payment(acc, 50000, method="ACH")
        get_success_data(api.withdraw_enrollment(
            ctx["enrollment"]["id"], {"effective_date": "2026-09-05"},
            TEST_USERS["registrar_headers"],
        ))
        refund = refund_for_enrollment(ctx["enrollment"]["id"])
        validate_success(
            api.transition_refund(refund["id"], {"action": "APPROVE"},
                                  bursar_manager_headers),
            200,
        )
        ledger = read_ledger(acc)
        types = [e["entry_type"] for e in ledger]
        rev_idx = types.index("CHARGE_REVERSAL")
        pay_idx = types.index("REFUND_PAYOUT")
        assert rev_idx < pay_idx, "reversal is posted before the payout"
        reversal = ledger[rev_idx]
        assert reversal["amount_cents"] == 50000
        assert reversal["charge_kind"] == "TUITION"
        assert reversal["due_date"] == "2026-09-07", (
            "reversal copies the tuition charge's due date"
        )
        assert reversal["enrollment_id"] == ctx["enrollment"]["id"]
        assert reversal["source_ref"] == refund["id"]
        payout = ledger[pay_idx]
        # Pre-payout balance was 50000 - 50000 - 50000 = -50000.
        assert payout["amount_cents"] == 50000


def test_refund_void_then_approve_returns_state_error(
    api, bursar_manager_headers, bursar_staff_headers
):
    """PRD §3.9: "Disposition of a calculated refund belongs to a
    `BursarManager` alone, and only while the refund is `CALCULATED` — any
    other state yields `ERR_REFUND_STATE_INVALID` (HTTP 409)." and "Voiding a
    `CALCULATED` refund writes nothing to the ledger at all; the enrollment
    exit simply remains in force."

    Design: Corner/state_machines/refund_void_then_approve_returns_state_error
    """
    ctx = setup_calculated_refund(credit_hours=1, action="drop",
                                  effective_date="2026-09-01",
                                  external_ref="S-VD")
    refund = ctx["refund"]
    voided = validate_success(
        api.transition_refund(refund["id"], {"action": "VOID"},
                              bursar_manager_headers),
        200,
    )
    assert voided["status"] == "VOID"

    res = api.transition_refund(refund["id"], {"action": "APPROVE"},
                                bursar_manager_headers)
    validate_error(res, ApiErrorId.ERR_REFUND_STATE_INVALID, expected_status=409)
    ledger = read_ledger(ctx["account_id"])
    assert [e["entry_type"] for e in ledger] == ["CHARGE", "CHARGE"], (
        "voided refund writes nothing; approval of it is rejected"
    )


def test_enrollment_withdraw_twice_returns_state_error(
    api, registrar_headers, bursar_staff_headers
):
    """PRD §3.9: withdrawal "requires the enrollment still `ENROLLED`
    (otherwise `ERR_ENROLLMENT_NOT_ACTIVE`, HTTP 409)" and moves "the
    enrollment to terminal `DROPPED` or `WITHDRAWN`".

    Design: Corner/state_machines/enrollment_withdraw_twice_returns_state_error
    """
    ctx = setup_account_with_enrollment(credit_hours=3, external_ref="S-TWI")
    enr = ctx["enrollment"]
    first = validate_success(
        api.withdraw_enrollment(enr["id"], {"effective_date": "2026-09-20"},
                                registrar_headers),
        200,
    )
    assert first["status"] == "WITHDRAWN"

    res = api.withdraw_enrollment(enr["id"], {"effective_date": "2026-09-21"},
                                  registrar_headers)
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE, expected_status=409)

    refunds, _m = validate_paginated(
        api.list_refunds(bursar_staff_headers, params={"enrollment_id": enr["id"]})
    )
    assert len(refunds) == 1, "the first withdrawal's refund remains the only one"
    # 50% tier (09-20 on or before mid_refund_end 10-05) of 120000.
    assert refunds[0]["amount_cents"] == 60000


def test_withdrawal_past_deadline_returns_422(api, registrar_headers,
                                              bursar_staff_headers):
    """PRD §3.9: withdrawal "requires its mandatory `effective_date` to fall on
    or after the term's start date and on or before the `withdrawal_deadline`;
    outside that window the request is rejected with
    `ERR_WITHDRAWAL_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/validations/withdrawal_past_deadline_returns_422
    """
    ctx = setup_account_with_enrollment(credit_hours=3, external_ref="S-LWD")
    enr = ctx["enrollment"]
    res = api.withdraw_enrollment(enr["id"], {"effective_date": "2026-11-14"},
                                  registrar_headers)
    validate_error(res, ApiErrorId.ERR_WITHDRAWAL_WINDOW_CLOSED,
                   expected_status=422)
    enrollment = validate_success(
        api.get_enrollment(enr["id"], bursar_staff_headers), 200
    )
    assert enrollment["status"] == "ENROLLED"
    refunds, _m = validate_paginated(
        api.list_refunds(bursar_staff_headers, params={"enrollment_id": enr["id"]})
    )
    assert refunds == []


def test_drop_after_census_returns_422(api, registrar_headers,
                                       bursar_staff_headers):
    """PRD §3.9: "the drop's `effective_date` — optional on a drop, defaulting
    to the clock date — must fall on or before the term's `census_date`; a
    later effective date is rejected with `ERR_DROP_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/errors/drop_after_census_returns_422
    """
    ctx = setup_account_with_enrollment(credit_hours=3, external_ref="S-LD")
    enr = ctx["enrollment"]
    res = api.drop_enrollment(enr["id"], {"effective_date": "2026-09-08"},
                              registrar_headers)
    validate_error(res, ApiErrorId.ERR_DROP_WINDOW_CLOSED, expected_status=422)
    enrollment = validate_success(
        api.get_enrollment(enr["id"], bursar_staff_headers), 200
    )
    assert enrollment["status"] == "ENROLLED"


def test_staff_cannot_approve_refund(api, bursar_staff_headers):
    """PRD §3.9: "Disposition of a calculated refund belongs to a
    `BursarManager` alone".
    PRD §2.1: a recognized-but-unpermitted role "is rejected with
    `ERR_FORBIDDEN` (HTTP 403)".

    Design: Corner/rbac/staff_cannot_approve_refund
    """
    ctx = setup_calculated_refund(credit_hours=1, action="drop",
                                  effective_date="2026-09-01",
                                  external_ref="S-RFD")
    refund = ctx["refund"]
    res = api.transition_refund(refund["id"], {"action": "APPROVE"},
                                bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    current = validate_success(api.get_refund(refund["id"], _MGR), 200)
    assert current["status"] == "CALCULATED"

"""The monthly payment rhythm: scheduling, splitting, recording, curing, forfeiting,
and the provisional-vs-final credit accrual that is the spine of the product.
"""
import pytest

from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    # fixtures / helpers
    create_active_agreement,
    activate_agreement,
    create_draft_agreement,
    schedule_payment,
    record_payment,
    forfeit_payment,
    cure_payment,
    setup_agreement_with_paid_payments,
    setup_agreement_with_late_payment,
    get_agreement,
    make_landlord_headers,
    make_tenant_headers,
)


def test_rent_payment_amount_and_split_computed_on_create(api):
    """PRD §3.3: "The payment row does not accept its own amount: `amount_cents` is
    copied from the agreement's `monthly_payment_cents` at creation."
    PRD §3.3: "The credit portion, `credit_portion_cents`, is the payment amount
    multiplied by the agreement's `credit_pct`, rounded half up to whole cents. The
    rent portion, `rent_portion_cents`, is whatever remains — the payment amount
    minus the credit portion."

    Design: Corner/entities/entity_rentpayment_amount_copied_from_agreement
    """
    landlord, tenant, prop, agreement = create_active_agreement(
        monthly_payment_cents=200000, credit_pct=0.30
    )
    pay = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    assert pay["amount_cents"] == 200000, pay["amount_cents"]
    assert pay["credit_portion_cents"] == 60000, pay["credit_portion_cents"]
    assert pay["rent_portion_cents"] == 140000, pay["rent_portion_cents"]


def test_provisional_and_final_credit_differ(api):
    """PRD §3.3: "The provisional figure, `gross_credit_accrued_cents`, is optimistic:
    it is the sum of `credit_portion_cents` over every payment row whose status is
    `PENDING`, `PAID`, or `LATE` — every row that has not been forfeited — counting
    credit as if all of it will ultimately be earned. The finalized figure,
    `available_credit_cents`, is strict: it is the sum of `credit_portion_cents` over
    only those rows in `PAID` status."

    Design: Difficulty/dual_variant_calc/dvc_rent_credit_provisional_vs_final
    """
    landlord, tenant, prop, agreement = create_active_agreement(
        monthly_payment_cents=200000, credit_pct=0.30
    )
    p1 = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    p2 = schedule_payment(landlord, agreement, 2, "2026-03-01T00:00:00Z")
    p3 = schedule_payment(landlord, agreement, 3, "2026-04-01T00:00:00Z")
    schedule_payment(landlord, agreement, 4, "2026-05-01T00:00:00Z")  # left PENDING
    record_payment(tenant, p1, "2026-02-03T00:00:00Z")  # PAID
    record_payment(tenant, p2, "2026-03-04T00:00:00Z")  # PAID
    record_payment(tenant, p3, "2026-04-20T00:00:00Z")  # LATE (19 days late)
    a = get_agreement(landlord, agreement["id"])
    assert a["gross_credit_accrued_cents"] == 240000, a["gross_credit_accrued_cents"]
    assert a["available_credit_cents"] == 120000, a["available_credit_cents"]
    assert a["gross_credit_accrued_cents"] != a["available_credit_cents"]


def test_forfeited_row_excluded_from_both_accruals(api):
    """PRD §3.3: "The provisional figure, `gross_credit_accrued_cents`, is optimistic:
    it is the sum of `credit_portion_cents` over every payment row whose status is
    `PENDING`, `PAID`, or `LATE` — every row that has not been forfeited". And: "The
    finalized figure, `available_credit_cents`, is strict: it is the sum of
    `credit_portion_cents` over only those rows in `PAID` status."

    Design: Difficulty/dual_variant_calc/dvc_rent_credit_provisional_vs_final
    """
    landlord, tenant, prop, agreement = create_active_agreement(
        monthly_payment_cents=200000, credit_pct=0.30
    )
    p1 = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    p2 = schedule_payment(landlord, agreement, 2, "2026-03-01T00:00:00Z")
    record_payment(tenant, p1, "2026-02-03T00:00:00Z")  # PAID
    forfeit_payment(landlord, p2)                        # FORFEITED -> leaves both pools
    a = get_agreement(landlord, agreement["id"])
    assert a["gross_credit_accrued_cents"] == 60000, a["gross_credit_accrued_cents"]
    assert a["available_credit_cents"] == 60000, a["available_credit_cents"]


def test_credit_rounds_per_payment_then_sums(api):
    """PRD §2.5: "Purchase credit is computed **per payment first, then summed**:
    each `RentPayment` independently rounds its own credit portion to whole cents,
    and the agreement-level accruals are the sum of those already-rounded per-period
    values."
    PRD §3.3: "The credit portion, `credit_portion_cents`, is the payment amount
    multiplied by the agreement's `credit_pct`, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/cf_accrual_round_per_payment_then_sum
    """
    landlord, tenant, prop, agreement = create_active_agreement(
        monthly_payment_cents=33333, credit_pct=0.30
    )
    p1 = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    p2 = schedule_payment(landlord, agreement, 2, "2026-03-01T00:00:00Z")
    p3 = schedule_payment(landlord, agreement, 3, "2026-04-01T00:00:00Z")
    assert p1["credit_portion_cents"] == 10000, p1["credit_portion_cents"]
    record_payment(tenant, p1, "2026-02-03T00:00:00Z")
    record_payment(tenant, p2, "2026-03-03T00:00:00Z")
    record_payment(tenant, p3, "2026-04-03T00:00:00Z")
    a = get_agreement(landlord, agreement["id"])
    assert a["available_credit_cents"] == 30000, a["available_credit_cents"]


def test_each_per_payment_credit_portion_independently_rounded(api):
    """PRD §2.5: "each `RentPayment` independently rounds its own credit portion to
    whole cents, and the agreement-level accruals are the sum of those already-rounded
    per-period values."
    PRD §3.3: "The credit portion, `credit_portion_cents`, is the payment amount
    multiplied by the agreement's `credit_pct`, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/cf_accrual_round_per_payment_then_sum
    """
    landlord, tenant, prop, agreement = create_active_agreement(
        monthly_payment_cents=33333, credit_pct=0.30
    )
    for idx, due in ((1, "2026-02-01T00:00:00Z"), (2, "2026-03-01T00:00:00Z"),
                     (3, "2026-04-01T00:00:00Z")):
        pay = schedule_payment(landlord, agreement, idx, due)
        assert pay["credit_portion_cents"] == 10000, (
            f"period {idx} credit_portion must round to 10000, got {pay['credit_portion_cents']}"
        )


def test_record_on_time_earns_credit(api):
    """PRD §3.4: "the row transitions `PENDING → PAID`, its `late_fee_cents` stays
    zero, its `credit_portion_cents` is earned, and the agreement's
    `available_credit_cents` rises by that credit portion."

    Design: Corner/state_machines/sm_side_effect_record_paid_increments_available_credit
    """
    landlord, tenant, prop, agreement = create_active_agreement(
        monthly_payment_cents=200000, credit_pct=0.30
    )
    pay = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    record_payment(tenant, pay, "2026-02-03T00:00:00Z")
    a = get_agreement(landlord, agreement["id"])
    assert a["available_credit_cents"] == 60000, a["available_credit_cents"]


def test_grace_boundary_paid_vs_late(api):
    """PRD §3.4: "The boundary is exact — a payment exactly `grace_days` days late
    is still on time and becomes `PAID` with no fee, whereas a payment one day beyond
    `grace_days` becomes `LATE` with a fee."
    PRD §3.4: "The late fee, `late_fee_cents`, when assessed, is the payment amount
    multiplied by a late-fee rate of five percent, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/bpc_grace_boundary_paid_vs_late
    """
    landlord, tenant, prop, agreement = create_active_agreement(
        monthly_payment_cents=200000, credit_pct=0.30, grace_days=5
    )
    p1 = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    p2 = schedule_payment(landlord, agreement, 2, "2026-02-01T00:00:00Z")
    r1 = record_payment(tenant, p1, "2026-02-06T00:00:00Z")  # exactly +5 days
    assert r1["status"] == "PAID", r1["status"]
    assert r1["late_fee_cents"] == 0, r1["late_fee_cents"]
    r2 = record_payment(tenant, p2, "2026-02-07T00:00:00Z")  # +6 days
    assert r2["status"] == "LATE", r2["status"]
    assert r2["late_fee_cents"] == 10000, r2["late_fee_cents"]


def test_record_within_grace_is_on_time(api):
    """PRD §3.4: "If that number of days late is at most the agreement's `grace_days`,
    the payment is on time: the row transitions `PENDING → PAID`, its `late_fee_cents`
    stays zero, its `credit_portion_cents` is earned, and the agreement's
    `available_credit_cents` rises by that credit portion."

    Design: Difficulty/boundary_precision_check/bpc_grace_boundary_paid_vs_late
    """
    landlord, tenant, prop, agreement = create_active_agreement(
        monthly_payment_cents=200000, credit_pct=0.30, grace_days=5
    )
    pay = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    r = record_payment(tenant, pay, "2026-02-05T00:00:00Z")  # +4 days (< grace)
    assert r["status"] == "PAID", r["status"]
    assert r["late_fee_cents"] == 0, r["late_fee_cents"]


def test_cure_late_payment_restores_credit(api):
    """PRD §3.4: "The landlord cures a late payment, which transitions it
    `LATE → PAID` ... On cure, the period's `credit_portion_cents` is now earned and
    is added to the agreement's `available_credit_cents`, compensating for the credit
    that was withheld while the row sat in `LATE`."

    Design: Difficulty/non_linear_state_machine/nlsm_rentpayment_late_to_paid_cure_cycle
    """
    landlord, tenant, prop, agreement, pay = setup_agreement_with_late_payment(
        due_date="2026-02-01T00:00:00Z", paid_at="2026-02-20T00:00:00Z",
        monthly_payment_cents=200000, credit_pct=0.30,
    )
    assert pay["status"] == "LATE", pay["status"]
    cured = cure_payment(landlord, pay)
    assert cured["status"] == "PAID", f"cure must move LATE -> PAID, got {cured['status']}"
    a = get_agreement(landlord, agreement["id"])
    assert a["available_credit_cents"] == 60000, a["available_credit_cents"]


def test_late_leg_withholds_credit_before_cure(api):
    """PRD §3.4: "If instead the days late exceed `grace_days`, the row transitions
    `PENDING → LATE`: a late fee is assessed, the credit is not yet earned, and
    `available_credit_cents` is unchanged."

    Design: Difficulty/non_linear_state_machine/nlsm_rentpayment_late_to_paid_cure_cycle
    """
    landlord, tenant, prop, agreement, pay = setup_agreement_with_late_payment(
        due_date="2026-02-01T00:00:00Z", paid_at="2026-02-20T00:00:00Z",
        monthly_payment_cents=200000, credit_pct=0.30,
    )
    assert pay["status"] == "LATE", pay["status"]
    a = get_agreement(landlord, agreement["id"])
    assert a["available_credit_cents"] == 0, (
        f"a LATE row earns no final credit before cure, got {a['available_credit_cents']}"
    )


def test_gross_accrual_create_then_forfeit_is_conserved(api):
    """PRD §3.3: "A freshly scheduled payment is born `PENDING`, and its
    `credit_portion_cents` immediately joins the agreement's provisional credit
    pool — `gross_credit_accrued_cents` rises by that period's credit portion."
    PRD §3.4: "the agreement's `gross_credit_accrued_cents` falls by that period's
    `credit_portion_cents` as the forfeited row leaves the provisional pool."

    Design: Difficulty/compensating_invariant/ci_gross_accrual_create_then_forfeit_conserved
    """
    landlord, tenant, prop, agreement = create_active_agreement(
        monthly_payment_cents=200000, credit_pct=0.30
    )
    before = get_agreement(landlord, agreement["id"])["gross_credit_accrued_cents"]
    assert before == 0, before
    pay = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    forfeit_payment(landlord, pay)
    after = get_agreement(landlord, agreement["id"])["gross_credit_accrued_cents"]
    assert after == 0, (
        f"gross must return to 0 (60000 added on create, 60000 removed on forfeit), got {after}"
    )


def test_scheduling_payment_raises_gross_accrual(api):
    """PRD §3.3: "A freshly scheduled payment is born `PENDING`, and its
    `credit_portion_cents` immediately joins the agreement's provisional credit
    pool — `gross_credit_accrued_cents` rises by that period's credit portion."

    Design: Difficulty/compensating_invariant/ci_gross_accrual_create_then_forfeit_conserved
    """
    landlord, tenant, prop, agreement = create_active_agreement(
        monthly_payment_cents=200000, credit_pct=0.30
    )
    schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    a = get_agreement(landlord, agreement["id"])
    assert a["gross_credit_accrued_cents"] == 60000, (
        f"scheduling a payment must raise gross by its credit portion (60000), "
        f"got {a['gross_credit_accrued_cents']}"
    )


def test_forfeit_increments_missed_payment_count(api):
    """PRD §3.4: "the row moves to `FORFEITED`, its credit portion is lost, the
    agreement's `missed_payment_count` rises by one".

    Design: Corner/endpoints/ep_forfeit_increments_missed_payment_count
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    pay = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    forfeited = forfeit_payment(landlord, pay)
    assert forfeited["status"] == "FORFEITED", forfeited["status"]
    a = get_agreement(landlord, agreement["id"])
    assert a["missed_payment_count"] == 1, a["missed_payment_count"]


def test_record_already_paid_payment_rejected(api):
    """PRD §3.4: "Recording is permitted only on a `PENDING` row (otherwise
    `ERR_PAYMENT_NOT_PENDING`)".

    Design: Corner/state_machines/sm_record_on_terminal_paid_returns_invalid_state
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    pay = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    record_payment(tenant, pay, "2026-02-03T00:00:00Z")  # -> PAID
    res = api.record_rent_payment(
        pay["id"], {"paid_at": "2026-02-04T00:00:00Z"}, make_tenant_headers(tenant["id"])
    )
    validate_error(res, ApiErrorId.ERR_PAYMENT_NOT_PENDING.value)


def test_cure_non_late_payment_rejected(api):
    """PRD §3.4: "this is permitted only on a row currently in `LATE` (otherwise
    `ERR_PAYMENT_NOT_LATE`)".

    Design: Corner/state_machines/sm_cure_non_late_returns_invalid_state
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    pay = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")  # PENDING
    res = api.cure_rent_payment(pay["id"], make_landlord_headers(landlord["id"]))
    validate_error(res, ApiErrorId.ERR_PAYMENT_NOT_LATE.value)


def test_landlord_cannot_record_payment(api):
    """PRD §4: the routing table lists `POST /rent-payments/{id}/record` as authorized
    for Tenant only.
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/rbac_landlord_cannot_record_payment
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    pay = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    res = api.record_rent_payment(
        pay["id"], {"paid_at": "2026-02-03T00:00:00Z"}, make_landlord_headers(landlord["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_list_rent_payments_filtered_by_agreement(api):
    """PRD §3.4: "Payments are individually fetchable and listable, with optional
    filters on `agreement_id`, `supersedes_payment_id`, and `status`."

    Design: Corner/endpoints/ep_filtered_list_rent_payments_by_agreement
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    schedule_payment(landlord, agreement, 2, "2026-03-01T00:00:00Z")
    res = api.list_rent_payments(
        make_tenant_headers(tenant["id"]), params={"agreement_id": agreement["id"]}
    )
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, meta["total_count"]
    for row in data:
        assert row["agreement_id"] == agreement["id"], row["agreement_id"]

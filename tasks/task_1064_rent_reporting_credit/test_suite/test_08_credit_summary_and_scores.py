"""Credit summary: the two divergent on-time-rate variants, the empty-set null
boundary, latest-score-by-bureau selection, and the logical-clock monotonicity
guard.

Covers the two divergent on-time-rate variants, the empty-set null boundary,
latest-score selection, and the logical-clock monotonicity guard.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_tenant_headers,
    create_score_snapshot_payload,
    reset_clock_default, create_tenant, create_landlord,
    setup_active_tenant, create_verified_lease, record_payment, report_payment,
)

ADMIN = TEST_USERS["admin_headers"]


def _three_payments_two_reported(api):
    """Active tenant + verified lease + 3 payments (2 on-time furnished, 1 late
    unfurnished). Returns (tenant_id, tenant_headers)."""
    ctx = setup_active_tenant(api, tenant_overrides={"full_name": "Tara Tenant", "email": "tara@x.com"})
    lease = create_verified_lease(api, ctx["tenant"]["id"], ctx["landlord"]["id"],
                                  property_address="1 Main St #2", rent_amount_cents=200000)
    p1 = record_payment(api, ctx["landlord"]["id"], lease["id"], period_month="2026-04",
                        due_date="2026-04-05T00:00:00Z", paid_date="2026-04-05T00:00:00Z",
                        amount_paid_cents=200000)
    p2 = record_payment(api, ctx["landlord"]["id"], lease["id"], period_month="2026-05",
                        due_date="2026-05-05T00:00:00Z", paid_date="2026-05-05T00:00:00Z",
                        amount_paid_cents=200000)
    record_payment(api, ctx["landlord"]["id"], lease["id"], period_month="2026-06",
                   due_date="2026-06-05T00:00:00Z", paid_date="2026-06-20T00:00:00Z",
                   amount_paid_cents=200000)  # late, left unfurnished
    report_payment(api, p1["id"])
    report_payment(api, p2["id"])
    return ctx["tenant"]["id"], make_tenant_headers(ctx["tenant"]["id"])


# --------------------------------------------------------------------------
# Difficulty: dual_variant_calc / as_paid vs as_reported diverge
# --------------------------------------------------------------------------
def test_credit_summary_as_paid_rate_over_all_payments(api):
    """PRD §3.9: "otherwise it is one hundred times the number of on-time payments
    divided by the total number of payments, rounded half up to a whole percent.
    `total_payments` is that denominator — the count of all recorded payments."

    Design: Difficulty/dual_variant_calc/on_time_rate_as_paid_vs_as_reported_diverge
    """
    tenant_id, th = _three_payments_two_reported(api)
    summary = validate_success(api.get_credit_summary(th, tenant_id), 200)
    assert summary["on_time_rate_as_paid_pct"] == 67
    assert summary["total_payments"] == 3


def test_credit_summary_as_reported_rate_over_effective_items(api):
    """PRD §3.9: "The **as-reported** rate ranges only over the tenant's effective
    tradelines, those reported items whose `status` is `REPORTED` or `DISPUTED`:
    if there are none the variant is null, otherwise it is one hundred times the
    number of effective tradelines whose `on_time` snapshot is true divided by the
    count of effective tradelines, rounded half up to a whole percent."

    Design: Difficulty/dual_variant_calc/on_time_rate_as_paid_vs_as_reported_diverge
    """
    tenant_id, th = _three_payments_two_reported(api)
    summary = validate_success(api.get_credit_summary(th, tenant_id), 200)
    assert summary["on_time_rate_as_reported_pct"] == 100
    assert summary["effective_reported_items"] == 2


# --------------------------------------------------------------------------
# Difficulty: boundary_precision_check / empty effective set -> null
# --------------------------------------------------------------------------
def test_credit_summary_reported_rate_null_when_no_items(api):
    """PRD §3.9: "The **as-reported** rate ranges only over the tenant's effective
    tradelines, those reported items whose `status` is `REPORTED` or `DISPUTED`:
    if there are none the variant is null, otherwise it is one hundred times the
    number of effective tradelines whose `on_time` snapshot is true divided by the
    count of effective tradelines, rounded half up to a whole percent."

    Design: Difficulty/boundary_precision_check/empty_effective_set_rate_is_null
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Ned Empty", email="ned@x.com")
    th = make_tenant_headers(tenant["id"])
    summary = validate_success(api.get_credit_summary(th, tenant["id"]), 200)
    assert summary["on_time_rate_as_reported_pct"] is None
    assert summary["effective_reported_items"] == 0


def test_credit_summary_paid_rate_null_when_no_payments(api):
    """PRD §3.9: "if the tenant has no recorded payments the variant is null".

    Design: Difficulty/boundary_precision_check/empty_effective_set_rate_is_null
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Nora Empty", email="nora@x.com")
    th = make_tenant_headers(tenant["id"])
    summary = validate_success(api.get_credit_summary(th, tenant["id"]), 200)
    assert summary["on_time_rate_as_paid_pct"] is None
    assert summary["total_payments"] == 0


# --------------------------------------------------------------------------
# Corner: latest score by bureau picks latest as_of_month
# --------------------------------------------------------------------------
def test_latest_score_by_bureau_picks_latest_month(api):
    """PRD §3.9: ""Most recent" is decided by ranking the tenant's snapshots for
    that bureau by `as_of_month` descending and breaking ties by `created_at`
    descending — never by `id` — and taking the winning snapshot's `score`."

    Design: Corner/calculations/latest_score_by_bureau_picks_latest_as_of_month
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Lil Latest", email="lil@x.com")
    get_success_data(api.create_score_snapshot(
        ADMIN, create_score_snapshot_payload(tenant["id"], bureau="EQUIFAX", score=650, as_of_month="2026-05")))
    get_success_data(api.create_score_snapshot(
        ADMIN, create_score_snapshot_payload(tenant["id"], bureau="EQUIFAX", score=700, as_of_month="2026-06")))
    th = make_tenant_headers(tenant["id"])
    summary = validate_success(api.get_credit_summary(th, tenant["id"]), 200)
    assert summary["latest_scores"]["EQUIFAX"] == 700


# --------------------------------------------------------------------------
# Corner: logical clock cannot move backwards
# --------------------------------------------------------------------------
def test_clock_set_before_current_rejected(api):
    """PRD §2.4: "the target must not be strictly before the current clock value,
    and an attempt to move the clock backwards is rejected with
    `ERR_CLOCK_BEFORE_CURRENT`."

    Design: Corner/validations/clock_set_before_current_returns_error
    """
    validate_success(api.set_clock(ADMIN, {"to_iso8601": "2026-08-01T00:00:00Z"}), 200)
    resp = api.set_clock(ADMIN, {"to_iso8601": "2026-07-01T00:00:00Z"})
    validate_error(resp, ApiErrorId.ERR_CLOCK_BEFORE_CURRENT.value, 422)

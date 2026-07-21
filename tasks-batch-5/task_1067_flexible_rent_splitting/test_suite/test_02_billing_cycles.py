"""Billing-cycle creation, installment layout, and creation-time gates."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_property, create_renter, submit_application,
    create_enrolled_renter, create_declined_renter,
    create_scheduled_cycle, get_installments,
    create_cycle_payload, defer_cycle_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / installment_rounding_floor_then_remainder
# ---------------------------------------------------------------------------

def test_split3_amounts_floor_then_remainder(api):
    """PRD §3.4: "each of the earliest sequence numbers up to and including the remainder
    receives one extra cent on top of the base share; the later sequences receive exactly
    the base."

    Design: Difficulty/combinatorial_formula/installment_rounding_floor_then_remainder
    """
    ctx = create_scheduled_cycle(api, mode="SPLIT", split_count=3)
    insts = sorted(get_installments(ctx["cycle"]["id"], api), key=lambda i: i["sequence_no"])
    assert len(insts) == 3
    # portion 100000: base 33333, remainder 1 -> seq1 gets the extra cent
    assert insts[0]["amount_cents"] == 33334
    assert insts[1]["amount_cents"] == 33333
    assert insts[2]["amount_cents"] == 33333


def test_split3_installment_sum_conserved(api):
    """PRD §3.4: "Shares are never rounded individually, so the sum of installment
    `amount_cents` exactly equals `portion_cents`."

    Design: Difficulty/combinatorial_formula/installment_rounding_floor_then_remainder
    """
    ctx = create_scheduled_cycle(api, mode="SPLIT", split_count=3)
    insts = get_installments(ctx["cycle"]["id"], api)
    assert sum(i["amount_cents"] for i in insts) == 100000
    assert ctx["cycle"]["portion_cents"] == 100000


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / duplicate_cycle_month_bucket
# ---------------------------------------------------------------------------

def test_duplicate_cycle_same_month_rejected(api):
    """PRD §3.4: "At most one non-`CANCELLED` cycle may exist for a given renter and
    `cycle_month`; a second is rejected with `ERR_DUPLICATE_CYCLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_cycle_month_bucket
    """
    ctx = create_scheduled_cycle(api, mode="SPLIT", split_count=2)
    renter_id = ctx["renter"]["id"]
    resp = api.create_billing_cycle(create_cycle_payload(
        renter_id, cycle_month="2026-07", split_count=3), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CYCLE.value, 409)


def test_second_cycle_different_month_allowed(api):
    """PRD §3.4: "At most one non-`CANCELLED` cycle may exist for a given renter and
    `cycle_month`; a second is rejected with `ERR_DUPLICATE_CYCLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_cycle_month_bucket
    """
    ctx = create_scheduled_cycle(api, mode="SPLIT", split_count=2)
    renter_id = ctx["renter"]["id"]
    resp = api.create_billing_cycle(create_cycle_payload(
        renter_id, cycle_month="2026-08",
        cycle_start_date="2026-08-01T00:00:00Z", split_count=2), ADMIN)
    data = validate_success(resp, 201)
    assert data["cycle_month"] == "2026-08"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / cycle_create_requires_renter_enrolled
# ---------------------------------------------------------------------------

def test_prospect_renter_cannot_create_cycle(api):
    """PRD §3.4: "Cycle creation requires that the renter's `status` be `ENROLLED`;
    otherwise the request is rejected with `ERR_RENTER_NOT_ENROLLED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cycle_create_requires_renter_enrolled
    """
    prop = create_property(api, unit_label="Maple #13")
    renter = create_renter(prop["id"], api, email="r13@x.com", portion_rent_cents=100000)
    resp = api.create_billing_cycle(create_cycle_payload(renter["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_RENTER_NOT_ENROLLED.value, 409)


def test_underwriting_renter_cannot_create_cycle(api):
    """PRD §3.4: "Cycle creation requires that the renter's `status` be `ENROLLED`;
    otherwise the request is rejected with `ERR_RENTER_NOT_ENROLLED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cycle_create_requires_renter_enrolled
    """
    prop = create_property(api, unit_label="Maple #13b")
    renter = create_renter(prop["id"], api, email="r13b@x.com", portion_rent_cents=100000)
    submit_application(renter["id"], api)  # renter now UNDERWRITING, still not ENROLLED
    resp = api.create_billing_cycle(create_cycle_payload(renter["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_RENTER_NOT_ENROLLED.value, 409)


# ---------------------------------------------------------------------------
# Corner: validations
# ---------------------------------------------------------------------------

def test_invalid_split_count_returns_422(api):
    """PRD §3.4: "The split count must lie between 2 and 4 inclusive; a value outside that
    band is rejected with `ERR_INVALID_SPLIT_COUNT` (HTTP 422)."

    Design: Corner/validations/invalid_split_count_returns_422
    """
    ctx = create_enrolled_renter(api, unit_label="Oak #10")
    resp = api.create_billing_cycle(create_cycle_payload(
        ctx["renter"]["id"], split_count=5), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_SPLIT_COUNT.value, 422)


def test_defer_window_exceeded_returns_422(api):
    """PRD §3.4: "The planned defer days must lie between 1 and 25 inclusive; a value of
    zero or beyond 25 is rejected with `ERR_DEFER_WINDOW_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/defer_window_exceeded_returns_422
    """
    ctx = create_enrolled_renter(api, unit_label="Oak #9")
    resp = api.create_billing_cycle(defer_cycle_payload(
        ctx["renter"]["id"], deferred_amount_cents=60000, planned_defer_days=30), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEFER_WINDOW_EXCEEDED.value, 422)


def test_limit_exceeded_returns_402(api):
    """PRD §3.4: "if `portion_cents` is greater than the renter's `approved_limit_cents`,
    creation is rejected with `ERR_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/limit_exceeded_returns_402
    """
    # portion 200000, income 300000 -> ratio 1.5 -> score 70 MEDIUM -> limit 150000 < 200000
    ctx = create_enrolled_renter(api, unit_label="Oak #11", portion_cents=200000,
                                 income_cents=300000, full_rent_cents=200000)
    assert ctx["renter"]["approved_limit_cents"] == 150000
    resp = api.create_billing_cycle(create_cycle_payload(ctx["renter"]["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_LIMIT_EXCEEDED.value, 402)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / cycle_create_referential_beats_fiscal
# ---------------------------------------------------------------------------

def test_declined_renter_cycle_reports_not_enrolled(api):
    """PRD §3.4: "Cycle creation requires that the renter's `status` be `ENROLLED`;
    otherwise the request is rejected with `ERR_RENTER_NOT_ENROLLED` (HTTP 409)."
    PRD §2.9: "then the remaining cross-entity, temporal, domain-range, and fiscal checks
    described in §3."

    Design: Difficulty/priority_pair_validation_conflict/cycle_create_referential_beats_fiscal
    """
    # DECLINED renter is SUSPENDED with approved_limit 0, so BOTH the not-enrolled
    # (cross-entity) and the limit (fiscal) checks fail; the cross-entity check is reported.
    ctx = create_declined_renter(api, unit_label="Maple #9", portion_cents=100000)
    assert ctx["renter"]["status"] == "SUSPENDED"
    assert ctx["renter"]["approved_limit_cents"] == 0
    resp = api.create_billing_cycle(create_cycle_payload(ctx["renter"]["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_RENTER_NOT_ENROLLED.value, 409)


def test_declined_renter_cycle_not_limit_exceeded(api):
    """PRD §2.9: "When multiple checks could fail on one request, they are evaluated in a
    fixed priority order so that the reported error is deterministic."

    Design: Difficulty/priority_pair_validation_conflict/cycle_create_referential_beats_fiscal
    """
    ctx = create_declined_renter(api, unit_label="Maple #9b", portion_cents=100000)
    resp = api.create_billing_cycle(create_cycle_payload(ctx["renter"]["id"]), ADMIN)
    body = resp.json()
    # The fiscal ERR_LIMIT_EXCEEDED (priority 18) is pre-empted by the earlier check.
    assert body["data"]["error_id"] != ApiErrorId.ERR_LIMIT_EXCEEDED.value

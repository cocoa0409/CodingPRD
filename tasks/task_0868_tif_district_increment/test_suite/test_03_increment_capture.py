"""Increment capture: provisional/final variants, finalize/reopen cycle, EAV split."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_increment_record_payload, finalize_increment_payload,
    setup_certified_district, create_draft_district, capture_increment, get_fund,
    assert_eav_split_invariant,
)

ADMIN = TEST_USERS["municipal_admin_headers"]
CLERK = TEST_USERS["county_clerk_headers"]
SINGLE = [("School", "SCHOOL", 0.05)]


# ─── Corner: provisional capture correctness ───────────────────────────────

def test_provisional_capture_credits_net_increment_to_fund():
    """PRD 3.2: "The `gross_increment_cents` is the incremental value multiplied by
    the district's `aggregate_tax_rate`, rounded half up to whole cents".
    PRD 3.2: "The county withholds a collection-and-administration fee,
    `admin_fee_cents`, equal to three percent of the gross increment rounded half up
    to whole cents."
    PRD 3.2: "On creation the fund's `balance_cents` increases by the captured
    increment, its `lifetime_increment_cents` increases by the same captured amount,
    its `lifetime_admin_fee_cents` increases by the admin fee".

    Design: Corner/calculations/increment_provisional_capture_correct
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)  # aggregate 0.08
    d_id = ctx["district"]["id"]
    rec = capture_increment(d_id, 2026, 1_500_000_000)
    assert rec["incremental_eav_cents"] == 500_000_000
    assert rec["gross_increment_cents"] == 40_000_000
    assert rec["admin_fee_cents"] == 1_200_000
    assert rec["captured_increment_cents"] == 38_800_000
    fund = get_fund(d_id)
    assert fund["balance_cents"] == 38_800_000
    assert fund["lifetime_admin_fee_cents"] == 1_200_000


# ─── Difficulty: dual-variant — provisional vs final capture ───────────────

def test_finalize_recomputes_final_gross_and_captured():
    """PRD 3.2: "On finalize, the capture is recomputed in its final variant: the
    gross increment becomes the incremental value multiplied by the
    `aggregate_tax_rate` and then by the `collection_rate`, rounded half up to whole
    cents, and the admin fee and captured increment are recomputed from that smaller
    gross the same way."
    PRD 3.2: "The record's `variant_state` becomes `FINAL`".

    Design: Difficulty/dual_variant_calc/increment_provisional_vs_final_capture
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)  # aggregate 0.08
    d_id = ctx["district"]["id"]
    rec = capture_increment(d_id, 2026, 1_500_000_000)
    final = validate_success(api_client.finalize_increment(
        rec["id"], finalize_increment_payload(0.95), CLERK))
    assert final["variant_state"] == "FINAL"
    assert final["gross_increment_cents"] == 38_000_000
    assert final["captured_increment_cents"] == 36_860_000


def test_finalize_applies_delta_true_up_to_fund():
    """PRD 3.2: "The system computes the delta between the final captured increment
    and the provisional captured increment and applies exactly that delta to the
    fund — the fund's `balance_cents` and `lifetime_increment_cents` each change by
    the delta".

    Design: Difficulty/dual_variant_calc/increment_provisional_vs_final_capture
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)  # aggregate 0.08
    d_id = ctx["district"]["id"]
    rec = capture_increment(d_id, 2026, 1_500_000_000)
    api_client.finalize_increment(rec["id"], finalize_increment_payload(0.95), CLERK)
    fund = get_fund(d_id)
    assert fund["lifetime_increment_cents"] == 36_860_000
    assert fund["balance_cents"] == 36_860_000


# ─── Difficulty: non-linear state machine — finalize/reopen cycle ──────────

def test_reopen_restores_provisional_record():
    """PRD 3.2: "its `variant_state` returns to `PROVISIONAL`, its
    `captured_increment_cents` is restored to the provisional figure, its `status`
    returns to `CERTIFIED`".

    Design: Difficulty/non_linear_state_machine/increment_finalize_reopen_cycle
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)  # aggregate 0.08
    d_id = ctx["district"]["id"]
    rec = capture_increment(d_id, 2026, 1_500_000_000)
    api_client.finalize_increment(rec["id"], finalize_increment_payload(0.95), CLERK)
    reopened = validate_success(api_client.reopen_increment(rec["id"], CLERK))
    assert reopened["status"] == "CERTIFIED"
    assert reopened["variant_state"] == "PROVISIONAL"
    assert reopened["captured_increment_cents"] == 38_800_000


def test_reopen_reverses_finalize_delta_on_fund():
    """PRD 3.2: "the finalize delta is reversed out of the fund (its `balance_cents`
    and `lifetime_increment_cents` are reduced by that delta and its
    `lifetime_admin_fee_cents` is restored)".

    Design: Difficulty/non_linear_state_machine/increment_finalize_reopen_cycle
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)  # aggregate 0.08
    d_id = ctx["district"]["id"]
    rec = capture_increment(d_id, 2026, 1_500_000_000)
    api_client.finalize_increment(rec["id"], finalize_increment_payload(0.95), CLERK)
    api_client.reopen_increment(rec["id"], CLERK)
    fund = get_fund(d_id)
    assert fund["lifetime_increment_cents"] == 38_800_000
    assert fund["balance_cents"] == 38_800_000


# ─── Difficulty: boundary precision — zero increment at base boundary ──────

def test_increment_zero_when_current_equals_base():
    """PRD 3.2: "The record's `incremental_eav_cents` is the growth above the frozen
    base — the `current_eav_cents` minus the district's `base_eav_cents`, or zero if
    that difference would be negative, so a year whose value has not risen above the
    base captures nothing."

    Design: Difficulty/boundary_precision_check/increment_zero_when_current_equals_base
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    rec = capture_increment(d_id, 2026, 1_000_000_000)
    assert rec["incremental_eav_cents"] == 0
    assert rec["gross_increment_cents"] == 0
    assert rec["captured_increment_cents"] == 0


def test_increment_zero_leaves_fund_balance_unchanged():
    """PRD 3.2: "The `captured_increment_cents` is the gross increment minus that
    admin fee, and it is the net amount credited to the fund."

    Design: Difficulty/boundary_precision_check/increment_zero_when_current_equals_base
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 1_000_000_000)
    fund = get_fund(d_id)
    assert fund["balance_cents"] == 0
    assert fund["lifetime_increment_cents"] == 0


# ─── Difficulty: cross-entity dependency — increment needs CERTIFIED ───────

def test_increment_on_draft_district_rejected():
    """PRD 3.2: "Three conditions gate creation: the district must be `CERTIFIED`, or
    the request is rejected with `ERR_DISTRICT_NOT_CERTIFIED`".

    Design: Difficulty/cross_entity_state_dependency/increment_requires_certified_district
    """
    district, _ = create_draft_district(bodies=SINGLE, base_eav_cents=1_000_000_000)
    resp = api_client.create_increment_record(
        district["id"], create_increment_record_payload(2026, 1_500_000_000), CLERK)
    validate_error(resp, ApiErrorId.ERR_DISTRICT_NOT_CERTIFIED, expected_status=409)


def test_increment_allowed_once_district_certified():
    """PRD 3.2: "Once a district is `CERTIFIED`, the county measures the growth in
    taxable value each year and captures the tax revenue it generates."

    Design: Difficulty/cross_entity_state_dependency/increment_requires_certified_district
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=1_000_000_000)
    rec = validate_success(api_client.create_increment_record(
        ctx["district"]["id"], create_increment_record_payload(2026, 1_500_000_000),
        CLERK), expected_status=201)
    assert rec["status"] == "CERTIFIED"


# ─── Difficulty: temporal overlap — one record per (district, tax_year) ────

def test_duplicate_increment_year_rejected():
    """PRD 3.2: "no increment record may already exist for the same district and
    `tax_year`, a duplicate being rejected with `ERR_INCREMENT_YEAR_EXISTS` because
    each tax year holds exactly one record slot".

    Design: Difficulty/resource_temporal_overlap/increment_year_exact_slot_collision
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 1_500_000_000)
    resp = api_client.create_increment_record(
        d_id, create_increment_record_payload(2026, 1_600_000_000), CLERK)
    validate_error(resp, ApiErrorId.ERR_INCREMENT_YEAR_EXISTS, expected_status=409)


def test_distinct_increment_year_allowed():
    """PRD 3.2: "no increment record may already exist for the same district and
    `tax_year`, a duplicate being rejected with `ERR_INCREMENT_YEAR_EXISTS` because
    each tax year holds exactly one record slot".

    Design: Difficulty/resource_temporal_overlap/increment_year_exact_slot_collision
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    capture_increment(d_id, 2026, 1_500_000_000)
    rec2 = validate_success(api_client.create_increment_record(
        d_id, create_increment_record_payload(2027, 1_600_000_000), CLERK),
        expected_status=201)
    assert rec2["tax_year"] == 2027


# ─── Corner: finalize already finalized ────────────────────────────────────

def test_finalize_already_finalized_returns_invalid_state():
    """PRD 3.2: "Finalization is permitted only on a record still in `CERTIFIED`
    status; attempting it on a record that is already `FINALIZED` is rejected with
    `ERR_INCREMENT_INVALID_STATE`."

    Design: Corner/state_machines/finalize_already_finalized_returns_invalid_state
    """
    ctx = setup_certified_district(bodies=SINGLE, base_eav_cents=1_000_000_000)
    d_id = ctx["district"]["id"]
    rec = capture_increment(d_id, 2026, 1_500_000_000)
    api_client.finalize_increment(rec["id"], finalize_increment_payload(0.95), CLERK)
    resp = api_client.finalize_increment(rec["id"], finalize_increment_payload(0.90), CLERK)
    validate_error(resp, ApiErrorId.ERR_INCREMENT_INVALID_STATE, expected_status=409)


# ─── Difficulty: compensating invariant — EAV split across finalize/reopen ─

def test_eav_split_preserved_across_finalize_reopen():
    """PRD 3.2: "The `incremental_eav_cents` and `current_eav_cents` are never
    touched by finalize or reopen, so the frozen split between base and increment is
    preserved across the whole cycle."

    Design: Difficulty/compensating_invariant/eav_split_conservation_on_finalize_reopen
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)  # aggregate 0.08
    d_id = ctx["district"]["id"]
    rec = capture_increment(d_id, 2026, 1_500_000_000)
    api_client.finalize_increment(rec["id"], finalize_increment_payload(0.90), CLERK)
    reopened = validate_success(api_client.reopen_increment(rec["id"], CLERK))
    assert reopened["current_eav_cents"] == 1_500_000_000
    assert reopened["incremental_eav_cents"] == 500_000_000
    assert_eav_split_invariant(reopened, 1_000_000_000)
    assert reopened["captured_increment_cents"] == 38_800_000


def test_reopen_restores_provisional_variant_and_fund_lifetime():
    """PRD 3.2: "its `captured_increment_cents` is restored to the provisional
    figure, its `status` returns to `CERTIFIED`".

    Design: Difficulty/compensating_invariant/eav_split_conservation_on_finalize_reopen
    """
    ctx = setup_certified_district(base_eav_cents=1_000_000_000)  # aggregate 0.08
    d_id = ctx["district"]["id"]
    rec = capture_increment(d_id, 2026, 1_500_000_000)
    api_client.finalize_increment(rec["id"], finalize_increment_payload(0.90), CLERK)
    reopened = validate_success(api_client.reopen_increment(rec["id"], CLERK))
    assert reopened["variant_state"] == "PROVISIONAL"
    fund = get_fund(d_id)
    assert fund["lifetime_increment_cents"] == 38_800_000

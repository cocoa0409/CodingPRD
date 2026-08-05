"""Return creation, per-line tax rounding, late-filing penalty/interest,
operator-active gating, period-overlap and validation-priority conflicts."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_tax_return,
    TEST_USERS, make_operator_headers,
    single_line, create_return_payload,
    setup_operator_with_property, create_active_operator, create_property,
    create_draft_return, file_return, create_and_file_return, set_clock,
    create_exemption, get_operator,
)

ADMIN = TEST_USERS["taxadmin_headers"]


def _op_with_n_properties(api, n, jur_overrides=None):
    op = create_active_operator(api, jur_overrides=jur_overrides)
    props = [create_property(api, op["id"], name=f"P{i}", address=f"{i} St") for i in range(n)]
    return op, props


# ============================================================
# Difficulty: combinatorial_formula/tax_rounding_per_line_then_sum
# ============================================================
def test_tax_rounded_per_line_then_summed(api):
    """PRD 3.4: "The return's `tax_due_cents` is the sum of these per-line rounded
    taxes — each line is rounded first, and the rounded values are added, never the
    reverse."

    Design: Difficulty/combinatorial_formula/tax_rounding_per_line_then_sum
    """
    op, props = _op_with_n_properties(api, 3)
    lines = [{"property_id": p["id"], "gross_receipts_cents": 1005} for p in props]
    ret = create_draft_return(api, op["id"], lines)
    filed = validate_success(api.file_return(ret["id"], make_operator_headers(op["id"])), 200)
    assert_tax_return(filed)
    # 1005 * 0.12 = 120.6 -> 121 per line; 121*3 = 363 (not round(361.8)=362).
    assert filed["tax_due_cents"] == 363


def test_return_gross_is_sum_of_lines(api):
    """PRD 3.4: "the server computes two derived values immediately:
    `gross_receipts_cents`, the sum of `gross_receipts_cents` across all lines".

    Design: Difficulty/combinatorial_formula/tax_rounding_per_line_then_sum
    """
    op, props = _op_with_n_properties(api, 3)
    lines = [{"property_id": p["id"], "gross_receipts_cents": 1005} for p in props]
    ret = create_draft_return(api, op["id"], lines)
    assert ret["gross_receipts_cents"] == 3015


# ---- Corner: entities/return_gross_receipts_computed_from_lines ----
def test_gross_receipts_computed_and_opens_draft_unpaid(api):
    """PRD 3.4: "On creation the return starts with a filing status of `DRAFT` and a
    settlement status of `UNPAID`, and the server computes two derived values
    immediately: `gross_receipts_cents`, the sum of `gross_receipts_cents` across all
    lines, and the `due_date`, defined as the last day of the month following
    `period_end`."

    Design: Corner/entities/return_gross_receipts_computed_from_lines
    """
    op, props = _op_with_n_properties(api, 2)
    lines = [
        {"property_id": props[0]["id"], "gross_receipts_cents": 250000},
        {"property_id": props[1]["id"], "gross_receipts_cents": 750000},
    ]
    data = validate_success(api.create_return(create_return_payload(op["id"], lines), ADMIN), 201)
    assert_tax_return(data)
    assert data["gross_receipts_cents"] == 1000000
    assert data["filing_status"] == "DRAFT"
    assert data["settlement_status"] == "UNPAID"


# ============================================================
# Difficulty: combinatorial_formula/penalty_interest_time_tiered
# ============================================================
def _late_filed_return(api):
    base = setup_operator_with_property(api, jur_overrides={"interest_rate_monthly_bps": 100})
    op, prop = base["operator"], base["property"]
    ret = create_draft_return(api, op["id"], single_line(prop["id"], 1000000),
                              period_start="2026-01-01T00:00:00Z", period_end="2026-01-31T00:00:00Z")
    set_clock(api, "2026-05-30T00:00:00Z")  # 3 whole months past due 2026-02-28
    return file_return(api, ret["id"], op["id"])


def test_late_filing_tiered_penalty(api):
    """PRD 3.7: "the rate starts at a 10% floor for the first month late and rises by
    5 percentage points for each additional month, capped at 25%. Concretely, one
    month late is 10%, two months is 15%, three months is 20%, and four or more
    months is held at the 25% cap. The penalty is the base multiplied by this rate,
    rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/penalty_interest_time_tiered
    """
    filed = _late_filed_return(api)
    assert filed["tax_due_cents"] == 120000
    # 3 months late -> 20% of 120000.
    assert filed["penalty_cents"] == 24000


def test_late_filing_interest_and_total(api):
    """PRD 3.7: "The interest is the base multiplied by the jurisdiction's monthly
    delinquency rate (`interest_rate_monthly_bps` divided by 10,000) and by the
    number of months late, again rounded half-up to whole cents."
    PRD 3.4: "the return also exposes `total_due_cents`, the sum of `tax_due_cents`,
    `penalty_cents`, and `interest_cents`".

    Design: Difficulty/combinatorial_formula/penalty_interest_time_tiered
    """
    filed = _late_filed_return(api)
    # 120000 * 0.01 * 3 = 3600.
    assert filed["interest_cents"] == 3600
    assert filed["total_due_cents"] == 147600


# ============================================================
# Difficulty: cross_entity_state_dependency/file_requires_operator_active
# ============================================================
def test_file_while_suspended_rejected(api):
    """PRD 3.4: "First, the parent operator must be `ACTIVE` or `DELINQUENT` — filing
    while `PENDING`, `SUSPENDED`, `REVOKED`, or `CLOSED` is rejected with
    `ERR_OPERATOR_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/file_requires_operator_active
    """
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_draft_return(api, op["id"], single_line(prop["id"], 1000000))
    api.suspend_operator(op["id"], ADMIN)
    resp = api.file_return(ret["id"], make_operator_headers(op["id"]))
    validate_error(resp, ApiErrorId.ERR_OPERATOR_NOT_ACTIVE.value)


def test_file_while_suspended_leaves_return_draft(api):
    """PRD 3.4: "Filing is an operator-only action that advances the return from
    `DRAFT` to `FILED`. It is guarded by three preconditions. First, the parent
    operator must be `ACTIVE` or `DELINQUENT`".

    Design: Difficulty/cross_entity_state_dependency/file_requires_operator_active
    """
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_draft_return(api, op["id"], single_line(prop["id"], 1000000))
    api.suspend_operator(op["id"], ADMIN)
    api.file_return(ret["id"], make_operator_headers(op["id"]))
    after = validate_success(api.get_return(ret["id"], ADMIN), 200)
    assert after["filing_status"] == "DRAFT"


# ============================================================
# Difficulty: resource_temporal_overlap/return_period_closed_interval_overlap
# ============================================================
def _setup_jan_filed(api):
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    set_clock(api, "2026-02-10T00:00:00Z")
    create_and_file_return(api, op["id"], single_line(prop["id"], 500000),
                           period_start="2026-01-01T00:00:00Z", period_end="2026-01-31T00:00:00Z")
    return op, prop


def test_overlapping_period_file_rejected(api):
    """PRD 3.4: "Second, the return's period must not overlap any other
    non-`SUPERSEDED` return for the same operator, or the filing is rejected with
    `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/return_period_closed_interval_overlap
    """
    op, prop = _setup_jan_filed(api)
    ret2 = create_draft_return(api, op["id"], single_line(prop["id"], 500000),
                               period_start="2026-01-15T00:00:00Z", period_end="2026-02-15T00:00:00Z")
    resp = api.file_return(ret2["id"], make_operator_headers(op["id"]))
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP.value)
    assert validate_success(api.get_return(ret2["id"], ADMIN), 200)["filing_status"] == "DRAFT"


def test_adjacent_distinct_month_files_cleanly(api):
    """PRD 3.4: "a `period_start` and `period_end` bounding the inclusive reporting
    period".
    PRD 3.4: "the return's period must not overlap any other non-`SUPERSEDED` return
    for the same operator, or the filing is rejected with `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/return_period_closed_interval_overlap
    """
    op, prop = _setup_jan_filed(api)
    ret3 = create_draft_return(api, op["id"], single_line(prop["id"], 500000),
                               period_start="2026-02-01T00:00:00Z", period_end="2026-02-28T00:00:00Z")
    filed = validate_success(api.file_return(ret3["id"], make_operator_headers(op["id"])), 200)
    assert filed["filing_status"] == "FILED"


# ============================================================
# Difficulty: priority_pair_validation_conflict/temporal_beats_constraint_on_return_file
# ============================================================
def _setup_overlap_and_overclaim(api):
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    create_and_file_return(api, op["id"], single_line(prop["id"], 1000000))
    ret2 = create_draft_return(api, op["id"], single_line(prop["id"], 1000000))
    create_exemption(api, ret2["id"], "GOVERNMENT", 2000000, guest_ref="G-9")
    return op, ret2


def test_period_overlap_beats_receipts_mismatch(api):
    """PRD 2.9: "(7) temporal non-overlap checks for return periods and OTA agreement
    coverage (`ERR_PERIOD_OVERLAP` / `ERR_AGREEMENT_OVERLAP`); ... (10) the receipts
    partition guard (`ERR_RECEIPTS_MISMATCH`)".
    PRD 2.9: "A check earlier in this order takes precedence over any later one that
    might also apply to the same request."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_return_file
    """
    op, ret2 = _setup_overlap_and_overclaim(api)
    resp = api.file_return(ret2["id"], make_operator_headers(op["id"]))
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP.value)


def test_period_overlap_conflict_leaves_return_draft(api):
    """PRD 3.4: "the return's period must not overlap any other non-`SUPERSEDED`
    return for the same operator, or the filing is rejected with
    `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_return_file
    """
    op, ret2 = _setup_overlap_and_overclaim(api)
    api.file_return(ret2["id"], make_operator_headers(op["id"]))
    assert validate_success(api.get_return(ret2["id"], ADMIN), 200)["filing_status"] == "DRAFT"

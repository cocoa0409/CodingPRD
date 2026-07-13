"""Sales-line reserve reconciliation and royalty-statement issue/pay logic:
conserved reserve balance, per-line reserve rounding, provisional vs final net,
empty-sales and period-overlap and period-not-ended guards.

Translates difficulty instances
`compensating_invariant/returns_reserve_balance_conserved_on_sale_then_return`,
`combinatorial_formula/reserve_round_per_line_then_sum`,
`dual_variant_calc/statement_provisional_net_vs_final_net`,
`boundary_precision_check/statement_issue_empty_sales_set_boundary`,
`resource_temporal_overlap/statement_period_overlap_closed_touching_rejected`, and
`priority_pair_validation_conflict/temporal_beats_referential_on_statement_issue`,
plus corner instance
`state_machines/pay_statement_before_issue_returns_invalid_state`.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_publisher, create_statement, ingest_sale, issue_statement, set_clock,
    setup_priced_print_format_for_sales, setup_two_period_ledger,
)

ADMIN = TEST_USERS["admin_headers"]


# --- compensating_invariant: publisher reserve balance -----------------------

def test_sale_adds_reserve_to_publisher_balance(api):
    """PRD 3.8: "the reserve_held_cents is the magnitude multiplied by the
    channel's returns_reserve_pct, rounded half up to whole cents."
    PRD 3.8: "the owning publisher's reserve_held_cents is reconciled to the sum
    of reserve_held_cents across every sales line that belongs to that publisher
    through the sold format and its title".

    Design: Difficulty/compensating_invariant/returns_reserve_balance_conserved_on_sale_then_return
    """
    base = setup_priced_print_format_for_sales(api)
    pub, fmt, channel = base["publisher"], base["format"], base["channel"]
    sale = ingest_sale(api, fmt["id"], channel["id"], 3, "SALE", "2026-03-10T00:00:00Z")
    assert sale["reserve_held_cents"] == 259, \
        f"expected per-line reserve 259, got {sale['reserve_held_cents']}"
    pub_after = get_success_data(api.get_publisher(pub["id"], ADMIN))
    assert pub_after["reserve_held_cents"] == 259


def test_return_reverses_publisher_reserve_balance(api):
    """PRD 2.10: "A SALE line contributes a positive reserve; a RETURN line
    contributes the exact negative, so that a sale which is later fully returned -
    same royalty per unit, same units, same channel - leaves the publisher's
    reserve_held_cents unchanged."

    Design: Difficulty/compensating_invariant/returns_reserve_balance_conserved_on_sale_then_return
    """
    base = setup_priced_print_format_for_sales(api)
    pub, fmt, channel = base["publisher"], base["format"], base["channel"]
    ingest_sale(api, fmt["id"], channel["id"], 3, "SALE", "2026-03-10T00:00:00Z")
    ret = ingest_sale(api, fmt["id"], channel["id"], 3, "RETURN", "2026-03-20T00:00:00Z")
    assert ret["reserve_held_cents"] == -259, \
        f"expected return reserve -259, got {ret['reserve_held_cents']}"
    pub_after = get_success_data(api.get_publisher(pub["id"], ADMIN))
    assert pub_after["reserve_held_cents"] == 0


# --- combinatorial_formula: round per line then sum --------------------------

def test_per_line_reserve_rounds_up_at_ingest(api):
    """PRD 3.8: "the reserve_held_cents is the magnitude multiplied by the
    channel's returns_reserve_pct, rounded half up to whole cents."
    PRD 2.5: "a value exactly halfway between two integers rounds to the larger
    integer".

    Design: Difficulty/combinatorial_formula/reserve_round_per_line_then_sum
    """
    base = setup_priced_print_format_for_sales(api)
    fmt, channel = base["format"], base["channel"]
    # gross 1150 => reserve round_half_up(172.5) = 173.
    line = ingest_sale(api, fmt["id"], channel["id"], 2, "SALE", "2026-03-10T00:00:00Z")
    assert line["reserve_held_cents"] == 173, \
        f"expected per-line reserve 173, got {line['reserve_held_cents']}"


def test_statement_sums_already_rounded_per_line_reserve(api):
    """PRD 3.9: "Its reserve_held_cents is the sum of the swept lines' per-line
    reserve_held_cents; crucially, each line's reserve was already rounded when
    the line was ingested, and the statement sums those already-rounded per-line
    values rather than re-rounding a combined figure."

    Design: Difficulty/combinatorial_formula/reserve_round_per_line_then_sum
    """
    base = setup_priced_print_format_for_sales(api)
    pub, fmt, channel = base["publisher"], base["format"], base["channel"]
    stmt = create_statement(api, pub["id"], "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z")
    ingest_sale(api, fmt["id"], channel["id"], 2, "SALE", "2026-03-10T00:00:00Z")
    ingest_sale(api, fmt["id"], channel["id"], 2, "SALE", "2026-03-11T00:00:00Z")
    set_clock("2026-04-01T00:00:00Z", api)
    issued = issue_statement(api, stmt["id"])
    assert issued["gross_royalty_cents"] == 2300
    assert issued["reserve_held_cents"] == 346, \
        f"per-line sum (173+173) must be 346, not the naive round(2300*0.15)=345; got {issued['reserve_held_cents']}"
    assert issued["reserve_held_cents"] != 345


# --- dual_variant_calc: provisional vs final net -----------------------------

def test_provisional_net_while_accruing(api):
    """PRD 3.9: "While a statement is ACCRUING, the platform maintains a
    forward-looking estimate in provisional_net_cents: the sum of
    gross_royalty_cents over the sales lines that would fall in the period, minus
    the corresponding sum of reserve_held_cents, ignoring any reserve maturing
    from a prior period."

    Design: Difficulty/dual_variant_calc/statement_provisional_net_vs_final_net
    """
    ledger = setup_two_period_ledger(api)
    stmt2 = get_success_data(api.get_statement(ledger["stmt2"]["id"], ADMIN))
    assert stmt2["status"] == "ACCRUING"
    assert stmt2["provisional_net_cents"] == 977, \
        f"provisional net expected 1150-173=977, got {stmt2['provisional_net_cents']}"


def test_final_net_credits_prior_period_reserve(api):
    """PRD 3.9: "The statement's reserve_released_cents is the reserve_held_cents
    of this publisher's immediately-prior issued statement". PRD 3.9: "The final
    net_payable_cents locked at issue is the statement's gross_royalty_cents,
    minus its reserve_held_cents, plus its reserve_released_cents."

    Design: Difficulty/dual_variant_calc/statement_provisional_net_vs_final_net
    """
    ledger = setup_two_period_ledger(api)
    issued = issue_statement(api, ledger["stmt2"]["id"])
    assert issued["reserve_released_cents"] == 345, \
        f"reserve_released must be P1's reserve 345, got {issued['reserve_released_cents']}"
    assert issued["net_payable_cents"] == 1322, \
        f"net expected 1150-173+345=1322, got {issued['net_payable_cents']}"


# --- boundary_precision_check: empty sweep set -------------------------------

def test_issue_with_zero_sales_rejected(api):
    """PRD 3.9: "it requires at least one PENDING sales line to fall within the
    period, otherwise ERR_NO_SALES_IN_PERIOD (HTTP 409)."

    Design: Difficulty/boundary_precision_check/statement_issue_empty_sales_set_boundary
    """
    pub = create_publisher(api)
    stmt = create_statement(api, pub["id"], "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z")
    set_clock("2026-04-01T00:00:00Z", api)
    validate_error(api.issue_statement(stmt["id"], ADMIN), ApiErrorId.ERR_NO_SALES_IN_PERIOD)


def test_issue_with_zero_sales_leaves_statement_accruing(api):
    """PRD 3.9: "Issuing a statement moves it ACCRUING -> ISSUED and settles the
    numbers." PRD 3.9: "it requires at least one PENDING sales line to fall within
    the period, otherwise ERR_NO_SALES_IN_PERIOD (HTTP 409)."

    Design: Difficulty/boundary_precision_check/statement_issue_empty_sales_set_boundary
    """
    pub = create_publisher(api)
    stmt = create_statement(api, pub["id"], "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z")
    set_clock("2026-04-01T00:00:00Z", api)
    api.issue_statement(stmt["id"], ADMIN)
    refetched = get_success_data(api.get_statement(stmt["id"], ADMIN))
    assert refetched["status"] == "ACCRUING", "a rejected issue must leave the statement ACCRUING"


# --- resource_temporal_overlap: closed-inclusive statement periods -----------

def test_touching_statement_period_rejected(api):
    """PRD 3.9: "because periods are closed-inclusive, two periods that merely
    touch at a shared endpoint are treated as overlapping and the create is
    rejected with ERR_STATEMENT_PERIOD_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/statement_period_overlap_closed_touching_rejected
    """
    pub = create_publisher(api)
    create_statement(api, pub["id"], "2026-01-01T00:00:00Z", "2026-03-31T00:00:00Z")
    resp = api.create_statement(
        pub["id"],
        {"period_start": "2026-03-31T00:00:00Z", "period_end": "2026-06-30T00:00:00Z"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP)


def test_overlapping_statement_period_rejected(api):
    """PRD 3.9: "A new statement's period must not overlap any existing period for
    that publisher; because periods are closed-inclusive, two periods that merely
    touch at a shared endpoint are treated as overlapping and the create is
    rejected with ERR_STATEMENT_PERIOD_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/statement_period_overlap_closed_touching_rejected
    """
    pub = create_publisher(api)
    create_statement(api, pub["id"], "2026-01-01T00:00:00Z", "2026-03-31T00:00:00Z")
    resp = api.create_statement(
        pub["id"],
        {"period_start": "2026-02-01T00:00:00Z", "period_end": "2026-04-30T00:00:00Z"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP)


# --- priority_pair: temporal precedes referential at issue -------------------

def test_issue_future_period_reports_period_not_ended(api):
    """PRD 3.9: "it requires the period to have ended, meaning period_end is at or
    before the logical clock's current instant, otherwise ERR_PERIOD_NOT_ENDED
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_statement_issue
    """
    pub = create_publisher(api)
    # Period entirely in the future relative to the default clock (2026-03-01); no sales.
    stmt = create_statement(api, pub["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    validate_error(api.issue_statement(stmt["id"], ADMIN), ApiErrorId.ERR_PERIOD_NOT_ENDED)


def test_issue_future_empty_period_temporal_precedes_referential(api):
    """PRD 3.5: "then temporal-window validity, then referential business rules,
    then other business constraints ... In this ordering a lower-precedence
    failure is only reported once every higher-precedence check has passed."
    PRD 3.9: "it requires the period to have ended, meaning period_end is at or
    before the logical clock's current instant, otherwise ERR_PERIOD_NOT_ENDED
    (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_statement_issue
    """
    pub = create_publisher(api)
    # Both the temporal check (period not ended) and the referential check
    # (no sales) would fail; the temporal error must win.
    stmt = create_statement(api, pub["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    err = validate_error(api.issue_statement(stmt["id"], ADMIN), ApiErrorId.ERR_PERIOD_NOT_ENDED)
    assert err.get("error_id") != "ERR_NO_SALES_IN_PERIOD", \
        "the higher-precedence temporal error must suppress the referential one"


# --- corner: pay before issue ------------------------------------------------

def test_pay_statement_before_issue_returns_invalid_state(api):
    """PRD 3.9: "Paying a statement moves it ISSUED -> PAID; payment requires the
    statement to be ISSUED, otherwise ERR_STATEMENT_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/pay_statement_before_issue_returns_invalid_state
    """
    pub = create_publisher(api)
    stmt = create_statement(api, pub["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z")
    validate_error(api.pay_statement(stmt["id"], ADMIN), ApiErrorId.ERR_STATEMENT_INVALID_STATE)

"""1099-B totals, the wash-sale add-back, the empty-portfolio boundary, and the
tax-year finalization gate.

Queue A: dual_variant_calc/net_1099b_gain_adds_back_wash_sale_disallowance,
boundary_precision_check/empty_portfolio_1099b_zero_lines.
Queue B (errors): tax_year_not_closed_on_finalize, tax_form_finalize_succeeds_for_closed_year.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_account_payload,
    create_tax_form_payload,
    set_clock,
    get_tax_form,
    propose_harvest,
    setup_active_account_with_washsale_loss_lot,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def _build_2025_washsale_form(api, email, src_ticker, repl_ticker):
    """In 2025, harvest a 5sh/60000 loss lot in A (mkt 50000) with a 2sh in-window
    lot in A present -> one CLOSED lot (proceeds 50000, basis 60000, wash 4000).
    Move the clock to 2026, then generate a draft 1099-B for 2025."""
    s = setup_active_account_with_washsale_loss_lot(
        "2025-06-01T00:00:00.000Z", email, src_ticker=src_ticker, repl_ticker=repl_ticker, correlation=0.10
    )
    harvest = propose_harvest(
        s["account"]["id"], s["source_lot"]["id"], s["repl_sec"]["id"], s["acct_version"]
    )
    get_success_data(api.execute_harvest_event(harvest["id"], ADVISOR))
    set_clock("2026-01-05T00:00:00.000Z")
    form = get_success_data(
        api.create_tax_form(create_tax_form_payload(account_id=s["account"]["id"], tax_year=2025), ADVISOR)
    )
    return s, form


# ─── net_1099b_gain_adds_back_wash_sale_disallowance ────────────────
def test_1099b_net_gain_adds_back_disallowance(api):
    """PRD §3.9: "the `net_realized_gain_cents` is the total proceeds minus the total cost basis, plus the total wash-sale disallowed losses added back; and the `line_count` is the count of reportable lots."

    Design: Difficulty/dual_variant_calc/net_1099b_gain_adds_back_wash_sale_disallowance
    """
    _, form = _build_2025_washsale_form(api, "f1099@x.com", "T1", "T2")
    form = get_tax_form(form["id"])
    # (50000 - 60000) + 4000 add-back = -6000.
    assert form["net_realized_gain_cents"] == -6000
    assert form["line_count"] == 1


def test_1099b_proceeds_basis_and_wash_totals(api):
    """PRD §3.9: "The `total_proceeds_cents` is the sum of `proceeds_cents` over the reportable lots; the `total_cost_basis_cents` is the sum of `cost_basis_cents` over the reportable lots; the `total_wash_sale_disallowed_cents` is the sum of `wash_sale_disallowed_cents` over the reportable lots".

    Design: Difficulty/dual_variant_calc/net_1099b_gain_adds_back_wash_sale_disallowance
    """
    _, form = _build_2025_washsale_form(api, "f1099b@x.com", "T1B", "T2B")
    form = get_tax_form(form["id"])
    assert form["total_proceeds_cents"] == 50000
    assert form["total_cost_basis_cents"] == 60000
    assert form["total_wash_sale_disallowed_cents"] == 4000


# ─── empty_portfolio_1099b_zero_lines ───────────────────────────────
def test_empty_portfolio_1099b_line_count_zero(api):
    """PRD §3.9: "The reportable lots are the `CLOSED` tax lots belonging to the form's account whose `disposed_at` calendar year equals the `tax_year`, and the form reports exactly one 1099-B line per reportable lot. ... the `line_count` is the count of reportable lots."

    Design: Difficulty/boundary_precision_check/empty_portfolio_1099b_zero_lines
    """
    set_clock("2026-02-01T00:00:00.000Z")
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="empty1099@x.com"), ADVISOR)
    )
    form = get_success_data(
        api.create_tax_form(create_tax_form_payload(account_id=acct["id"], tax_year=2025), ADVISOR)
    )
    assert form["line_count"] == 0


def test_empty_portfolio_1099b_zero_net_and_proceeds(api):
    """PRD §3.9: "The `total_proceeds_cents` is the sum of `proceeds_cents` over the reportable lots ... the `net_realized_gain_cents` is the total proceeds minus the total cost basis, plus the total wash-sale disallowed losses added back".

    Design: Difficulty/boundary_precision_check/empty_portfolio_1099b_zero_lines
    """
    set_clock("2026-02-02T00:00:00.000Z")
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="empty1099b@x.com"), ADVISOR)
    )
    form = get_success_data(
        api.create_tax_form(create_tax_form_payload(account_id=acct["id"], tax_year=2025), ADVISOR)
    )
    assert form["net_realized_gain_cents"] == 0
    assert form["total_proceeds_cents"] == 0


# ─── Queue B finalize gate ──────────────────────────────────────────
def test_finalize_current_year_form_returns_tax_year_not_closed(api):
    """PRD §3.9: "A form may only be finalized once its `tax_year` is strictly before the clock's current calendar year — a year that is the current calendar year or later is not yet closed and the attempt is rejected with `ERR_TAX_YEAR_NOT_CLOSED`."

    Design: Corner/errors/tax_year_not_closed_on_finalize
    """
    set_clock("2026-09-01T00:00:00.000Z")
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="notclosed@x.com"), ADVISOR)
    )
    form = get_success_data(
        api.create_tax_form(create_tax_form_payload(account_id=acct["id"], tax_year=2026), ADVISOR)
    )
    res = api.finalize_tax_form(form["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_TAX_YEAR_NOT_CLOSED.value)
    assert get_tax_form(form["id"])["status"] == "DRAFT"


def test_finalize_closed_year_form_succeeds(api):
    """PRD §3.9: "Finalizing a form freezes its totals into an immutable snapshot and moves it from `DRAFT` to `FINALIZED`. A form may only be finalized once its `tax_year` is strictly before the clock's current calendar year".

    Design: Corner/errors/tax_form_finalize_succeeds_for_closed_year
    """
    set_clock("2026-03-01T00:00:00.000Z")
    acct = get_success_data(
        api.create_account(create_account_payload(client_email="closedyear@x.com"), ADVISOR)
    )
    form = get_success_data(
        api.create_tax_form(create_tax_form_payload(account_id=acct["id"], tax_year=2025), ADVISOR)
    )
    finalized = validate_success(api.finalize_tax_form(form["id"], COMPLIANCE), 200)
    assert finalized["status"] == "FINALIZED"

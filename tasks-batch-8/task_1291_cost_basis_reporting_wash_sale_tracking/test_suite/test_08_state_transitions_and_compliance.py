"""State-machine guards and compliance gates: invalid transitions, terminal
lockdown, close preconditions, suspension/restriction blocks, correction
replacement rows, list filtering, and read-after-write consistency.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    validate_error_is_one_of,
    ApiErrorId, TEST_USERS, make_customer_headers,
    setup_book, setup_settled_sale, setup_wash_sale_scenario,
    make_firm, make_customer, make_account, make_security, make_lot,
    make_disposition, settle, make_basis_request,
)

TAX_OPS = TEST_USERS["tax_ops_headers"]
FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Corner: state_machines / invalid transitions and terminal lockdown
# ---------------------------------------------------------------------------

def test_invalid_settle_on_settled_disposition(api):
    """PRD §3.3: "Settlement moves the disposition from `PENDING` to
    `SETTLED`."
    PRD §2.6: "State. The target entity must be in the from-state the requested
    transition requires, or the request fails with `ERR_INVALID_STATE_TRANSITION`
    (HTTP 409)."
    PRD §3.3: "Once settled, these figures are immutable except through the
    correction cycle of §3.5."

    Design: Corner/state_machines/invalid_settle_on_settled_disposition
    """
    s = setup_settled_sale(tin="TIN-SM-1", cusip="151515151")
    resp = api.settle_disposition(s["firm"]["id"], s["disposition"]["id"], TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    lot_after = validate_success(api.get_tax_lot(s["firm"]["id"], s["lot"]["id"], TAX_OPS))
    assert lot_after["quantity_remaining"] == 0, "no double-consumption on a rejected settle"


def test_settle_after_void_rejected(api):
    """PRD §3.5: "A `PENDING` disposition that should never have been booked is
    voided: since booking consumed no shares, voiding simply releases the
    reserved allocations and moves the disposition to `VOIDED`."
    PRD §2.6: "State. The target entity must be in the from-state the requested
    transition requires, or the request fails with `ERR_INVALID_STATE_TRANSITION`
    (HTTP 409)."

    Design: Corner/state_machines/void_pending_disposition_and_settle_after_void_rejected
    """
    s = setup_book(tin="TIN-SM-2", cusip="161616161")
    make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=10, basis=10000)
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=10, proceeds=15000)
    voided = validate_success(api.void_disposition(s["firm"]["id"], disp["id"], TAX_OPS))
    assert voided["status"] == "VOIDED"
    resp = api.settle_disposition(s["firm"]["id"], disp["id"], TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


# ---------------------------------------------------------------------------
# Corner: state_machines / close preconditions
# ---------------------------------------------------------------------------

def test_account_close_blocked_with_open_lots(api):
    """PRD §3.1: "Closing an account — from either `OPEN` or `RESTRICTED` —
    requires every lot under it to be finished: each lot must have no shares
    remaining, with `lot_status` `FULLY_DISPOSED` or `SUPERSEDED`; otherwise
    the close fails with `ERR_ACCOUNT_HAS_OPEN_LOTS` (HTTP 409)."

    Design: Corner/state_machines/account_close_blocked_with_open_lots
    """
    s = setup_book(tin="TIN-SM-4", cusip="181818181")
    make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=10, basis=10000)
    resp = api.close_account(s["firm"]["id"], s["account"]["id"], TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_HAS_OPEN_LOTS)


def test_customer_close_blocked_with_open_account(api):
    """PRD §3.1: "every account under the customer must already be `CLOSED`,
    otherwise the close fails with `ERR_CUSTOMER_HAS_OPEN_ACCOUNTS` (HTTP 409)."

    Design: Corner/state_machines/customer_close_blocked_with_open_account
    """
    firm = make_firm("Firm SM5")
    cust = make_customer(firm["id"], tin="TIN-SM-5", display_name="SM Five")
    make_account(firm["id"], cust["id"])
    resp = api.close_customer(firm["id"], cust["id"], FIRM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_HAS_OPEN_ACCOUNTS)


def test_customer_close_blocked_with_pending_basis_request(api):
    """PRD §3.1: "no basis change request under the customer may sit in
    `PENDING`, `UNDER_REVIEW`, or `APPROVED`, otherwise the close fails with
    `ERR_PENDING_BASIS_REQUESTS` (HTTP 409)."

    Design: Corner/validations/customer_close_blocked_with_pending_basis_request
    """
    s = setup_settled_sale(tin="TIN-V-11", cusip="545454545")
    # The lot is now fully disposed, so the account may close.
    validate_success(api.close_account(s["firm"]["id"], s["account"]["id"], TAX_OPS))
    make_basis_request(s["firm"]["id"], s["customer"]["id"], s["lot"]["id"],
                       proposed_basis_cents=11000, supporting_doc_ref="DOC-PC")
    resp = api.close_customer(s["firm"]["id"], s["customer"]["id"], FIRM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_PENDING_BASIS_REQUESTS)


# ---------------------------------------------------------------------------
# Corner: state_machines / suspension and restriction blocks
# ---------------------------------------------------------------------------

def test_suspended_customer_blocks_new_disposition(api):
    """PRD §3.1: "Suspension freezes write activity without hiding history:
    every tax lot under the customer's accounts remains readable, but new
    dispositions and new basis change requests are rejected with
    `ERR_CUSTOMER_SUSPENDED` (HTTP 409)."

    Design: Corner/state_machines/suspended_customer_blocks_new_disposition
    """
    s = setup_book(tin="TIN-SM-6", cusip="191919191")
    validate_success(api.suspend_customer(s["firm"]["id"], s["customer"]["id"], FIRM_ADMIN))
    resp = api.create_disposition(
        s["firm"]["id"], s["account"]["id"],
        {"security_id": s["security"]["id"], "trade_date": "2025-06-10T00:00:00Z",
         "settlement_date": "2025-06-11T00:00:00Z", "quantity": 5, "proceeds_cents": 7000,
         "method": "FIFO"},
        TAX_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED)


def test_restricted_account_blocks_new_disposition(api):
    """PRD §3.1: "Either `FirmAdmin` or `TaxOps` may restrict an `OPEN`
    account, moving it to `RESTRICTED`, which blocks new dispositions and new
    outbound transfer statements with `ERR_ACCOUNT_RESTRICTED` (HTTP 409) while
    leaving reads untouched."

    Design: Corner/state_machines/restricted_account_blocks_new_disposition
    """
    s = setup_book(tin="TIN-SM-7", cusip="202020202")
    validate_success(api.restrict_account(s["firm"]["id"], s["account"]["id"], TAX_OPS))
    resp = api.create_disposition(
        s["firm"]["id"], s["account"]["id"],
        {"security_id": s["security"]["id"], "trade_date": "2025-06-10T00:00:00Z",
         "settlement_date": "2025-06-11T00:00:00Z", "quantity": 5, "proceeds_cents": 7000,
         "method": "FIFO"},
        TAX_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_RESTRICTED)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency /
# disposition_settle_gated_by_account_status
# ---------------------------------------------------------------------------

def _restricted_with_pending_disp():
    s = setup_book(tin="TIN-XD-2", cusip="111111120")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=10, basis=10000)
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=10, proceeds=15000)
    validate_success(api_client.restrict_account(s["firm"]["id"], s["account"]["id"], TAX_OPS))
    return s, lot, disp


def test_settle_rejected_when_account_not_open(api):
    """PRD §3.3: "Settlement requires the account to be `OPEN` and the customer
    `ACTIVE` at that moment."
    PRD §2.6: "State. The target entity must be in the from-state the requested
    transition requires, or the request fails with `ERR_INVALID_STATE_TRANSITION`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/disposition_settle_gated_by_account_status
    """
    s, _lot, disp = _restricted_with_pending_disp()
    resp = api.settle_disposition(s["firm"]["id"], disp["id"], TAX_OPS)
    # PRD pins the account-OPEN settle gate (§3.3) but names no error for it;
    # ERR_ACCOUNT_RESTRICTED (account-standing, §2.6) and
    # ERR_INVALID_STATE_TRANSITION (stage-4 gate, §2.6) are both faithful.
    validate_error_is_one_of(resp, [ApiErrorId.ERR_ACCOUNT_RESTRICTED,
                                    ApiErrorId.ERR_INVALID_STATE_TRANSITION])


def test_settle_rejected_leaves_disposition_pending(api):
    """PRD §3.3: "Settlement requires the account to be `OPEN` and the customer
    `ACTIVE` at that moment."

    Design: Difficulty/cross_entity_state_dependency/disposition_settle_gated_by_account_status
    """
    s, lot, disp = _restricted_with_pending_disp()
    validate_error_is_one_of(api.settle_disposition(s["firm"]["id"], disp["id"], TAX_OPS),
                             [ApiErrorId.ERR_ACCOUNT_RESTRICTED,
                              ApiErrorId.ERR_INVALID_STATE_TRANSITION])
    disp_after = validate_success(api.get_disposition(s["firm"]["id"], disp["id"], TAX_OPS))
    assert disp_after["status"] == "PENDING", "rejected settle leaves the disposition unchanged"
    lot_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["quantity_remaining"] == 10


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
# settle_state_vs_business_fiscal_priority
# ---------------------------------------------------------------------------

def _restricted_short_position():
    """5-share lot, PENDING disposition for 10 shares, account RESTRICTED."""
    firm = make_firm()
    cust = make_customer(firm["id"], tin="TIN-PR-1", display_name="Priority One")
    acct = make_account(firm["id"], cust["id"])
    sec = make_security(firm["id"], cusip="111111114", ticker="PR1")
    lot = make_lot(firm["id"], acct["id"], sec["id"], quantity=5, basis=5000)
    disp = make_disposition(firm["id"], acct["id"], sec["id"], quantity=10, proceeds=9000)
    validate_success(api_client.restrict_account(firm["id"], acct["id"], TAX_OPS))
    return firm, acct, sec, lot, disp


def test_state_error_beats_insufficient_quantity(api):
    """PRD §2.6: "Every request is evaluated against a fixed, ordered cascade,
    and a rejection at any stage masks every later stage — the client always
    sees the earliest applicable failure." Stage 4 is the state check
    (`ERR_INVALID_STATE_TRANSITION`); the business rules of stage 5, including
    the quantity check, run later.
    PRD §3.3: "Settlement requires the account to be `OPEN` and the customer
    `ACTIVE` at that moment."

    Design: Difficulty/priority_pair_validation_conflict/settle_state_vs_business_fiscal_priority
    """
    firm, acct, sec, lot, disp = _restricted_short_position()
    resp = api.settle_disposition(firm["id"], disp["id"], TAX_OPS)
    # The account-standing gate (whichever error_id) masks the later
    # allocation-sufficiency business check per the §2.6 ordered cascade.
    validate_error_is_one_of(resp, [ApiErrorId.ERR_ACCOUNT_RESTRICTED,
                                    ApiErrorId.ERR_INVALID_STATE_TRANSITION])


def test_state_priority_leaves_disposition_and_lots_untouched(api):
    """PRD §2.6: "a rejection at any stage masks every later stage — the client
    always sees the earliest applicable failure."

    Design: Difficulty/priority_pair_validation_conflict/settle_state_vs_business_fiscal_priority
    """
    firm, acct, sec, lot, disp = _restricted_short_position()
    validate_error_is_one_of(api.settle_disposition(firm["id"], disp["id"], TAX_OPS),
                             [ApiErrorId.ERR_ACCOUNT_RESTRICTED,
                              ApiErrorId.ERR_INVALID_STATE_TRANSITION])
    disp_after = validate_success(api.get_disposition(firm["id"], disp["id"], TAX_OPS))
    assert disp_after["status"] == "PENDING"
    lot_after = validate_success(api.get_tax_lot(firm["id"], lot["id"], TAX_OPS))
    assert lot_after["quantity_remaining"] == 5


# ---------------------------------------------------------------------------
# Corner: validations / settle insufficient lot quantity
# ---------------------------------------------------------------------------

def test_settle_insufficient_lot_quantity_rejected(api):
    """PRD §3.3: "the selected lots together can cover the sale — otherwise the
    settle is refused with `ERR_INSUFFICIENT_LOT_QUANTITY` (HTTP 422)."

    Design: Corner/validations/settle_insufficient_lot_quantity_rejected
    """
    s = setup_book(tin="TIN-V-10", cusip="535353535")
    make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=5, basis=5000)
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=10, proceeds=9000)
    resp = api.settle_disposition(s["firm"]["id"], disp["id"], TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_QUANTITY)
    disp_after = validate_success(api.get_disposition(s["firm"]["id"], disp["id"], TAX_OPS))
    assert disp_after["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner: state_machines / correction unwinds wash-sale taint
# ---------------------------------------------------------------------------

def test_disposition_correct_reverses_wash_sale_taint(api):
    """PRD §3.5: "Second, every wash-sale event the original settlement spawned
    is unwound, stripping the deferred amounts back off each triggering lot's
    `wash_sale_taint_basis_cents` and `adjusted_cost_basis_cents`."

    Design: Corner/state_machines/disposition_correct_reverses_wash_sale_taint
    """
    s = setup_wash_sale_scenario(tin="TIN-SM-10", cusip="232323232")
    settle(s["firm"]["id"], s["disposition"]["id"])
    lot2_tainted = validate_success(api.get_tax_lot(s["firm"]["id"], s["lot2"]["id"], TAX_OPS))
    assert lot2_tainted["wash_sale_taint_basis_cents"] == 100000
    # Correct to a gain so the replacement row does not re-trigger a wash sale.
    corrected = validate_success(api.correct_disposition(
        s["firm"]["id"], s["disposition"]["id"], {"proceeds_cents": 550000}, TAX_OPS
    ))
    assert corrected["status"] == "CORRECTED"
    lot2_after = validate_success(api.get_tax_lot(s["firm"]["id"], s["lot2"]["id"], TAX_OPS))
    assert lot2_after["wash_sale_taint_basis_cents"] == 0, "wash-sale taint unwound"
    assert lot2_after["adjusted_cost_basis_cents"] == 410000, "adjusted basis restored to pre-settle value"


# ---------------------------------------------------------------------------
# Corner: endpoints / correction replacement row, list filters, FK reverse
# ---------------------------------------------------------------------------

def test_disposition_correct_creates_replacement_settled(api):
    """PRD §3.5: "Third, a brand-new disposition row is created with the
    corrected values and driven from `PENDING` to `SETTLED` within the same
    request, re-running lot selection, gain computation, and wash-sale
    detection against current lot state."

    Design: Corner/endpoints/disposition_correct_creates_replacement_settled
    """
    s = setup_settled_sale(tin="TIN-E-4", cusip="585858585")
    corrected = validate_success(api.correct_disposition(
        s["firm"]["id"], s["disposition"]["id"], {"proceeds_cents": 18000}, TAX_OPS
    ))
    assert corrected["status"] == "CORRECTED"
    settled_rows, _meta = validate_paginated(
        api.list_dispositions(s["firm"]["id"], s["account"]["id"], TAX_OPS, params={"status": "SETTLED"})
    )
    assert len(settled_rows) == 1
    replacement = settled_rows[0]
    assert replacement["id"] != s["disposition"]["id"], "a NEW disposition row carries the corrected values"
    assert replacement["proceeds_cents"] == 18000
    assert replacement["realized_gain_cents"] == 8000, "18000 - 10000 basis re-applied"


def test_list_dispositions_filtered_by_status(api):
    """PRD §3.3: "An account's disposition history is listed with
    `security_id`, `status`, and `tax_year` filters; the lifecycle vocabulary
    is `PENDING`, `SETTLED`, `CORRECTED`, and `VOIDED`."

    Design: Corner/endpoints/list_dispositions_filtered_by_status
    """
    s = setup_book(tin="TIN-E-2", cusip="565656565")
    make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=20, basis=20000)
    disp_settled = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                                    quantity=10, proceeds=15000)
    settle(s["firm"]["id"], disp_settled["id"])
    make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                     quantity=5, proceeds=8000,
                     trade_date="2025-06-12T00:00:00Z", settlement_date="2025-06-13T00:00:00Z")
    data, meta = validate_paginated(
        api.list_dispositions(s["firm"]["id"], s["account"]["id"], TAX_OPS, params={"status": "SETTLED"})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1, "the PENDING disposition is filtered out"
    assert data[0]["id"] == disp_settled["id"]


def test_fk_reverse_reachability_lots_by_account(api):
    """PRD §2.5: "Alongside the nested paths, every entity exposes a flat read
    surface — a direct fetch by identifier plus a filterable list — so that
    foreign-key relationships are reachable in reverse."
    PRD §3.2: "Lots are listed per account with `security_id`, `lot_status`,
    `covered_status`, and `acquisition_kind` filters."

    Design: Corner/endpoints/fk_reverse_reachability_lots_by_account
    """
    from test_helpers import setup_two_account_book
    s = setup_two_account_book(tin="TIN-E-3", cusip="575757575")
    lot_a1 = make_lot(s["firm"]["id"], s["account1"]["id"], s["security"]["id"],
                      acquisition_date="2025-01-05T00:00:00Z", quantity=10, basis=10000)
    make_lot(s["firm"]["id"], s["account2"]["id"], s["security"]["id"],
             acquisition_date="2025-01-06T00:00:00Z", quantity=5, basis=5000)
    make_lot(s["firm"]["id"], s["account2"]["id"], s["security"]["id"],
             acquisition_date="2025-01-07T00:00:00Z", quantity=5, basis=5000)
    data, meta = validate_paginated(api.list_tax_lots(s["firm"]["id"], s["account1"]["id"], TAX_OPS))
    assert len(data) == 1, "A2's lots must not leak into A1's sub-resource"
    assert data[0]["id"] == lot_a1["id"]


# ---------------------------------------------------------------------------
# Corner: consistency_model / immediate read-after-write
# ---------------------------------------------------------------------------

def test_immediate_visibility_of_settle_effects(api):
    """PRD §3.3: "a disposition is economically final at settlement" and "Once
    settled, these figures are immutable except through the correction cycle of
    §3.5." A read issued immediately after the settle response observes the
    persisted outcome with no reconciliation lag.

    Design: Corner/consistency_model/immediate_visibility_of_settle_effects
    """
    s = setup_book(tin="TIN-K-1", cusip="707070707")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=10, basis=10000)
    disp = make_disposition(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                            quantity=10, proceeds=15000)
    settle(s["firm"]["id"], disp["id"])
    disp_after = validate_success(api.get_disposition(s["firm"]["id"], disp["id"], AUDITOR))
    assert disp_after["realized_gain_cents"] == 5000
    assert disp_after["status"] == "SETTLED"
    lot_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot["id"], AUDITOR))
    assert lot_after["quantity_remaining"] == 0, "visible immediately, no reconciliation lag"

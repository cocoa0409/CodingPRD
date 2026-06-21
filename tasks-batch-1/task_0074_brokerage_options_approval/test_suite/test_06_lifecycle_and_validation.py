"""Account/order/transfer lifecycle, validation, RBAC, listing, and error tests."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    open_account, open_and_activate_account, accept_order, draft_order,
    request_acat, validate_acat, get_account,
    create_account_payload,
    CO_SUBMITTER, HOLDER, CUST,
    build_user_headers,
)


# ---------------------------------------------------------------------------
# Compensating invariant (queue A)
# ---------------------------------------------------------------------------

def test_order_accept_then_cancel_conserves_buying_power(api):
    """PRD §3.5: "When all checks pass, the status becomes `ACCEPTED` and the
    computed `notional_cents` is reserved against the account's buying power".
    PRD §3.5: "Cancellation moves the order to `CANCELLED` and releases its
    reserved notional back to the account's buying power: for an `ACCEPTED`
    order the full reserved `notional_cents` is released."

    accept reserves 600000 (buying_power 1000000->400000), cancel releases it
    back to 1000000.

    Design: Difficulty/compensating_invariant/order_accept_then_cancel_conserves_buying_power
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    ord_ = accept_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                        order_type="LIMIT", quantity=6, limit_price_cents=100_000)
    assert get_account(acct["id"])["buying_power_cents"] == 400_000

    resp = api.cancel_order(ord_["id"], HOLDER)
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_account(acct["id"], CO_SUBMITTER))["buying_power_cents"] == 1_000_000


def test_order_accept_reserves_notional(api):
    """PRD §3.5: "When all checks pass, the status becomes `ACCEPTED` and the
    computed `notional_cents` is reserved against the account's buying power,
    which is recomputed to reflect the reservation."

    Design: Difficulty/compensating_invariant/order_accept_then_cancel_conserves_buying_power
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    accept_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                 order_type="LIMIT", quantity=6, limit_price_cents=100_000)
    assert get_account(acct["id"])["buying_power_cents"] == 400_000


# ---------------------------------------------------------------------------
# Entities (queue B)
# ---------------------------------------------------------------------------

def test_create_account_returns_pending_kyc_defaults(api):
    """PRD §3.1: "A newly opened account is born in `PENDING_KYC` status with
    `options_level` of 0 (meaning no options trading is permitted), `margin_type`
    of `CASH`, and `pdt_flagged` false with a `day_trade_count` of 0." PRD §2.4:
    "an integer `version` that begins at its initial value and increments by one
    each time the resource is mutated."

    Design: Corner/entities/create_account_returns_pending_kyc_defaults
    """
    payload = create_account_payload(account_holder_user_id="h_a")
    del payload["cash_balance_cents"]
    resp = api.create_account(payload, HOLDER)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING_KYC"
    assert data["options_level"] == 0
    assert data["margin_type"] == "CASH"
    assert data["version"] == 1
    assert data["cash_balance_cents"] == 0


def test_get_account_not_found_returns_404(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing
    resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404)
    before any business rule is evaluated."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account(NON_EXISTENT_UUID, CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_account_missing_required_field_rejected(api):
    """PRD §2.6: "Malformed request bodies and missing required input fields
    that are not covered by a more specific business error are rejected with
    `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_account_missing_required_field_rejected
    """
    payload = create_account_payload(account_holder_user_id="h_a")
    del payload["legal_name"]
    resp = api.create_account(payload, HOLDER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_cash_balance_defaults_to_zero_when_omitted(api):
    """PRD §3.1: "and optionally an initial `cash_balance_cents` (defaulting to
    0)."

    Design: Corner/entities/cash_balance_defaults_to_zero_when_omitted
    """
    payload = create_account_payload(account_holder_user_id="h_a")
    del payload["cash_balance_cents"]
    data = validate_success(api.create_account(payload, HOLDER), expected_status=201)
    assert data["cash_balance_cents"] == 0


def test_order_create_invalid_enum_order_type_rejected(api):
    """PRD §3.5: "`order_type` (`LIMIT`, `STOP`, or `TAKE_PROFIT`)". PRD §2.6:
    "Malformed request bodies and missing required input fields that are not
    covered by a more specific business error are rejected with `ERR_VALIDATION`
    (HTTP 422)."

    Design: Corner/entities/order_create_invalid_enum_order_type_rejected
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    resp = api.create_order({
        "account_id": acct["id"], "symbol": "ACME", "instrument_type": "EQUITY",
        "side": "BUY", "order_type": "MARKET", "quantity": 1,
        "limit_price_cents": 1000, "trade_date": "2026-06-01",
    }, HOLDER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# State machine validations (queue B)
# ---------------------------------------------------------------------------

def test_activate_already_active_account_returns_invalid_state(api):
    """PRD §2.6: "any state-transition endpoint invoked on a resource that is
    not in a state from which the requested transition is defined fails with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/activate_already_active_account_returns_invalid_state
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    resp = api.activate_account(acct["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_activate_without_w9_certified_returns_error(api):
    """PRD §3.1: "the W-9 must be certified (`w9_certified` is true), otherwise
    the activation is rejected with `ERR_W9_NOT_CERTIFIED`".

    Design: Corner/state_machines/activate_without_w9_certified_returns_error
    """
    acct = open_account(holder_id="h_a", w9_certified=False, cash_balance_cents=1_000_000)
    resp = api.activate_account(acct["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_W9_NOT_CERTIFIED.value)


def test_activate_under_18_returns_kyc_age_error(api):
    """PRD §3.1: "the account holder must be at least 18 years old as of the
    account's `created_at` date, measured from `date_of_birth`, otherwise
    `ERR_KYC_AGE`".

    Design: Corner/state_machines/activate_under_18_returns_kyc_age_error
    """
    acct = open_account(holder_id="h_a", date_of_birth="2015-01-01", cash_balance_cents=1_000_000)
    resp = api.activate_account(acct["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_KYC_AGE.value)


def test_terminal_closed_account_cannot_transition(api):
    """PRD §3.2: "`CLOSED` is terminal." PRD §2.6: "any state-transition
    endpoint invoked on a resource that is not in a state from which the
    requested transition is defined fails with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/terminal_closed_account_cannot_transition
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    validate_success(api.close_account(acct["id"], CO_SUBMITTER))
    resp = api.restrict_account(acct["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_order_partial_then_full_fill_completes(api):
    """PRD §3.5: "A partial fill adds `fill_quantity` to `filled_quantity` and
    leaves (or sets) the order in `PARTIALLY_FILLED`. A completing fill sets
    `filled_quantity` equal to `quantity`, moves the order to `FILLED`".

    Filling 4 then 6 of a 10-qty order ends FILLED with filled_quantity 10.

    Design: Corner/state_machines/order_partial_then_full_fill_completes
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    ord_ = accept_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                        order_type="LIMIT", quantity=10, limit_price_cents=1000)
    validate_success(api.fill_order(ord_["id"], {"fill_quantity": 4}, CO_SUBMITTER))
    resp = api.fill_order(ord_["id"], {"fill_quantity": 6}, CO_SUBMITTER)
    data = validate_success(resp)
    assert data["status"] == "FILLED"
    assert data["filled_quantity"] == 10


def test_fill_quantity_exceeding_remainder_rejected(api):
    """PRD §3.5: "any `fill_quantity` that is non-positive or that would push the
    cumulative total above the order quantity is rejected with
    `ERR_FILL_QUANTITY`."

    A fill of 11 against a 10-qty ACCEPTED order returns ERR_FILL_QUANTITY.

    Design: Corner/state_machines/fill_quantity_exceeding_remainder_rejected
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    ord_ = accept_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                        order_type="LIMIT", quantity=10, limit_price_cents=1000)
    resp = api.fill_order(ord_["id"], {"fill_quantity": 11}, CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_FILL_QUANTITY.value)


def test_acat_reject_without_code_rejected(api):
    """PRD §3.10: "the rejection must supply a `reject_code` — one of
    `SSN_MISMATCH`, `TITLE_MISMATCH`, or `ACCT_FROZEN` — in the request body,
    otherwise it is rejected with `ERR_MISSING_REJECT_CODE`."

    Design: Corner/state_machines/acat_reject_without_code_rejected
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    t = request_acat(acct["id"], direction="IN", transfer_value_cents=100_000)
    resp = api.reject_acat_transfer(t["id"], {}, CUST)
    validate_error(resp, ApiErrorId.ERR_MISSING_REJECT_CODE.value)


def test_acat_cancel_from_validated_returns_invalid_state(api):
    """PRD §3.10: "an `AccountHolder` may cancel a transfer that is still
    `REQUESTED`, moving it to `CANCELLED`, with no preconditions." PRD §2.6:
    "any state-transition endpoint invoked on a resource that is not in a state
    from which the requested transition is defined fails with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/acat_cancel_from_validated_returns_invalid_state
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    t = validate_acat(acct["id"], direction="IN", transfer_value_cents=100_000)
    resp = api.cancel_acat_transfer(t["id"], HOLDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_order_missing_price_for_order_type_rejected(api):
    """PRD §3.8: "A `TAKE_PROFIT` order requires both `limit_price_cents` and
    `stop_price_cents` (each non-null and greater than zero). A missing required
    field for the declared order type yields `ERR_MISSING_PRICE`."

    A TAKE_PROFIT order accepted with stop but no limit price returns
    ERR_MISSING_PRICE.

    Design: Corner/state_machines/order_missing_price_for_order_type_rejected
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    ord_ = draft_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                       order_type="TAKE_PROFIT", quantity=1, stop_price_cents=5000)
    resp = api.accept_order(ord_["id"], HOLDER)
    validate_error(resp, ApiErrorId.ERR_MISSING_PRICE.value)


def test_option_order_without_options_approval_rejected(api):
    """PRD §3.5: "if the order's `instrument_type` is `OPTION`, the account's
    `options_level` must be at least 1, otherwise `ERR_OPTIONS_NOT_APPROVED`".

    Design: Corner/state_machines/option_order_without_options_approval_rejected
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    ord_ = draft_order(acct["id"], symbol="OPT", instrument_type="OPTION", side="BUY",
                       order_type="LIMIT", quantity=1, limit_price_cents=1000)
    resp = api.accept_order(ord_["id"], HOLDER)
    validate_error(resp, ApiErrorId.ERR_OPTIONS_NOT_APPROVED.value)


def test_insufficient_buying_power_on_accept(api):
    """PRD §3.5: "the order's computed `notional_cents` (the reservation rule of
    §3.8) must not exceed the account's `buying_power_cents`, otherwise
    `ERR_INSUFFICIENT_BUYING_POWER`."

    A CASH account with cash 1000000 accepting a LIMIT order with notional
    2000000 (qty 100 * limit 20000) returns ERR_INSUFFICIENT_BUYING_POWER.

    Design: Corner/state_machines/error_insufficient_buying_power_on_accept
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    ord_ = draft_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                       order_type="LIMIT", quantity=100, limit_price_cents=20_000)
    resp = api.accept_order(ord_["id"], HOLDER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BUYING_POWER.value)


# ---------------------------------------------------------------------------
# Priority-pair (queue A)
# ---------------------------------------------------------------------------

def test_invalid_state_beats_buying_power_on_accept(api):
    """PRD §2.6: "State legality comes fourth: any state-transition endpoint
    invoked on a resource that is not in a state from which the requested
    transition is defined fails with `ERR_INVALID_STATE` (HTTP 409). Only after
    these four universal gates pass does the system evaluate the
    operation-specific business rules described in §3".

    Accepting an already-ACCEPTED order returns ERR_INVALID_STATE, not the
    business-rule ERR_INSUFFICIENT_BUYING_POWER.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_buying_power_on_accept
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    ord_ = accept_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                        order_type="LIMIT", quantity=6, limit_price_cents=100_000)
    # re-accept the already-ACCEPTED order
    resp = api.accept_order(ord_["id"], HOLDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Validations (queue B)
# ---------------------------------------------------------------------------

def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    resp = api.get_account(NON_EXISTENT_UUID, {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_forbidden_role_precedes_not_found_returns_403(api):
    """PRD §2.6: "Role authorization comes second, yielding `ERR_FORBIDDEN_ROLE`.
    Resource existence comes third, yielding `ERR_NOT_FOUND`."

    A Custodian (forbidden) calling POST /accounts/{nonexistent}/restrict returns
    ERR_FORBIDDEN_ROLE before ERR_NOT_FOUND.

    Design: Corner/validations/forbidden_role_precedes_not_found_returns_403
    """
    resp = api.restrict_account(NON_EXISTENT_UUID, CUST)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ---------------------------------------------------------------------------
# RBAC (queue B)
# ---------------------------------------------------------------------------

def test_account_holder_cannot_fill_order(api):
    """PRD §4 endpoint table: "POST `/orders/{orderId}/fill` ... Apply a partial
    or full fill | ComplianceOfficer". PRD §2.1: "When both headers are present
    but the named role is not permitted to perform the requested operation, the
    request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/account_holder_cannot_fill_order
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    ord_ = accept_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                        order_type="LIMIT", quantity=10, limit_price_cents=1000)
    resp = api.fill_order(ord_["id"], {"fill_quantity": 1}, HOLDER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_custodian_cannot_activate_account(api):
    """PRD §4 endpoint table: "POST `/accounts/{accountId}/activate` ... Activate
    a PENDING_KYC account or restore a RESTRICTED one | ComplianceOfficer". PRD
    §2.1: "When both headers are present but the named role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/custodian_cannot_activate_account
    """
    acct = open_account(holder_id="h_a", cash_balance_cents=1_000_000)
    resp = api.activate_account(acct["id"], CUST)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ---------------------------------------------------------------------------
# Listing (queue B)
# ---------------------------------------------------------------------------

def test_list_orders_paginated_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope." PRD §2.2: "The
    `response_type` is either "object" for a single resource or "array" for a
    list of resources."

    GET /orders?account_id=...&limit=1 with two orders returns total_count 2 and
    has_more true.

    Design: Corner/endpoints/list_orders_paginated_envelope
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    draft_order(acct["id"], symbol="AAA", instrument_type="EQUITY", side="BUY",
                order_type="LIMIT", quantity=1, limit_price_cents=1000)
    draft_order(acct["id"], symbol="BBB", instrument_type="EQUITY", side="BUY",
                order_type="LIMIT", quantity=1, limit_price_cents=1000)
    resp = api.list_orders(HOLDER, {"account_id": acct["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True


def test_invalid_state_on_filled_order_accept(api):
    """PRD §2.6: "State legality comes fourth: any state-transition endpoint
    invoked on a resource that is not in a state from which the requested
    transition is defined fails with `ERR_INVALID_STATE` (HTTP 409). Only after
    these four universal gates pass does the system evaluate the
    operation-specific business rules described in §3".

    Accepting a FILLED order (no DRAFT->ACCEPTED transition available) returns
    ERR_INVALID_STATE, not any business-rule error.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_buying_power_on_accept
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    ord_ = accept_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                        order_type="LIMIT", quantity=10, limit_price_cents=1000)
    validate_success(api.fill_order(ord_["id"], {"fill_quantity": 10}, CO_SUBMITTER))
    resp = api.accept_order(ord_["id"], HOLDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

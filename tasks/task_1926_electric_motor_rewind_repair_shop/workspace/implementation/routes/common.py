"""Shared helpers for routes."""
from flask import request
from errors import err_invalid_input, err_not_found
from db import store


def get_json_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise err_invalid_input("Request body must be JSON")
        return {}
    if not isinstance(body, dict):
        raise err_invalid_input("Request body must be a JSON object")
    return body


def parse_int_field(body, name, required=False, min_value=None, allow_zero=False):
    if name not in body:
        if required:
            raise err_invalid_input(f"Missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_invalid_input(f"Field {name} must be an integer")
    if min_value is not None:
        if allow_zero:
            if v < min_value:
                raise err_invalid_input(f"Field {name} must be >= {min_value}")
        else:
            if v <= min_value:
                raise err_invalid_input(f"Field {name} must be > {min_value}")
    return v


def parse_number_field(body, name, required=False, min_value=None, allow_zero=False):
    if name not in body:
        if required:
            raise err_invalid_input(f"Missing required field: {name}")
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_input(f"Field {name} must be a number")
    if min_value is not None:
        if allow_zero:
            if v < min_value:
                raise err_invalid_input(f"Field {name} must be >= {min_value}")
        else:
            if v <= min_value:
                raise err_invalid_input(f"Field {name} must be > {min_value}")
    return v


def parse_str_field(body, name, required=False):
    if name not in body:
        if required:
            raise err_invalid_input(f"Missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, str):
        raise err_invalid_input(f"Field {name} must be a string")
    return v


def parse_bool_field(body, name, required=False, default=None):
    if name not in body:
        if required:
            raise err_invalid_input(f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err_invalid_input(f"Field {name} must be a boolean")
    return v


def parse_enum_field(body, name, allowed, required=False, default=None):
    if name not in body:
        if required:
            raise err_invalid_input(f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_input(f"Field {name} must be one of {sorted(allowed)}")
    return v


def get_pagination():
    """Parse limit/offset with defaults: limit=10, min=1, max=100, offset=0."""
    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """items: list already sorted. Returns (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def get_shop_or_404(shop_id):
    shop = store.shops.get(shop_id)
    if shop is None:
        raise err_not_found("Shop not found")
    return shop


def get_customer_or_404(customer_id, shop_id=None):
    c = store.customers.get(customer_id)
    if c is None:
        raise err_not_found("Customer not found")
    if shop_id is not None and c["shop_id"] != shop_id:
        raise err_not_found("Customer not found in this shop")
    return c


def get_motor_or_404(motor_id, shop_id=None):
    m = store.motors.get(motor_id)
    if m is None:
        raise err_not_found("Motor not found")
    if shop_id is not None and m["shop_id"] != shop_id:
        raise err_not_found("Motor not found in this shop")
    return m


def get_work_order_or_404(wo_id, shop_id=None):
    w = store.work_orders.get(wo_id)
    if w is None:
        raise err_not_found("WorkOrder not found")
    if shop_id is not None and w["shop_id"] != shop_id:
        raise err_not_found("WorkOrder not found in this shop")
    return w


def get_quote_or_404(quote_id, wo_id=None):
    q = store.quotes.get(quote_id)
    if q is None:
        raise err_not_found("Quote not found")
    if wo_id is not None and q["work_order_id"] != wo_id:
        raise err_not_found("Quote not found under this work order")
    return q


def get_invoice_or_404(invoice_id, shop_id=None):
    inv = store.invoices.get(invoice_id)
    if inv is None:
        raise err_not_found("Invoice not found")
    if shop_id is not None:
        wo = store.work_orders.get(inv["work_order_id"])
        if wo is None or wo["shop_id"] != shop_id:
            raise err_not_found("Invoice not found in this shop")
    return inv


def get_contract_or_404(contract_id, shop_id=None):
    c = store.pool_contracts.get(contract_id)
    if c is None:
        raise err_not_found("Pool contract not found")
    if shop_id is not None and c["shop_id"] != shop_id:
        raise err_not_found("Pool contract not found in this shop")
    return c


def get_loan_or_404(loan_id, contract_id=None):
    l = store.pool_loans.get(loan_id)
    if l is None:
        raise err_not_found("Pool loan not found")
    if contract_id is not None and l["contract_id"] != contract_id:
        raise err_not_found("Pool loan not found under this contract")
    return l


def get_claim_or_404(claim_id, shop_id=None, wo_id=None):
    c = store.warranty_claims.get(claim_id)
    if c is None:
        raise err_not_found("Warranty claim not found")
    if wo_id is not None and c["work_order_id"] != wo_id:
        raise err_not_found("Warranty claim not found under this work order")
    if shop_id is not None:
        wo = store.work_orders.get(c["work_order_id"])
        if wo is None or wo["shop_id"] != shop_id:
            raise err_not_found("Warranty claim not found in this shop")
    return c


def get_test_record_or_404(tr_id):
    t = store.test_records.get(tr_id)
    if t is None:
        raise err_not_found("TestRecord not found")
    return t


def get_coil_record_or_404(c_id):
    c = store.coil_data_records.get(c_id)
    if c is None:
        raise err_not_found("CoilDataRecord not found")
    return c

"""Payload factories — one per entity, input fields only (PRD §3)."""


# ----- Customer (PRD §3.1) -----
def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "id_type": "DRIVERS_LICENSE",
        "id_number": "DL-TEST",
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


# ----- ComplianceScreen (PRD §3.1) -----
def create_compliance_screen_payload(customer_id, ofac_list_hit=False,
                                     kyc_documents_valid=True, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "ofac_list_hit": ofac_list_hit,
        "kyc_documents_valid": kyc_documents_valid,
    }
    defaults.update(overrides)
    return defaults


# ----- FeeSchedule (PRD §3.2) -----
def create_fee_schedule_payload(**overrides) -> dict:
    defaults = {
        "check_type": "GOVERNMENT",
        "base_fee_cents": 99,
        "percent_rate_bps": 100,
        "tier_breakpoint_cents": 500000,
        "high_percent_rate_bps": 200,
        "max_fee_cents": 50000,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


# ----- CashDrawer (PRD §3.3) -----
def create_cash_drawer_payload(**overrides) -> dict:
    defaults = {
        "store_code": "S-TEST",
        "business_date": "2026-05-01",
        "opening_float_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


# ----- Transaction (PRD §3.4) -----
def create_transaction_payload(customer_id, drawer_id, txn_type,
                               face_amount_cents, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "drawer_id": drawer_id,
        "txn_type": txn_type,
        "face_amount_cents": face_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_check_cash_payload(customer_id, drawer_id, face_amount_cents,
                              fee_schedule_id, maker_account_risk="LOW", **overrides) -> dict:
    """CHECK_CASH posting: requires fee_schedule_id and maker_account_risk (PRD §3.4, §3.5)."""
    return create_transaction_payload(
        customer_id, drawer_id, "CHECK_CASH", face_amount_cents,
        fee_schedule_id=fee_schedule_id, maker_account_risk=maker_account_risk, **overrides)


def create_money_order_payload(customer_id, drawer_id, face_amount_cents,
                               payee_name="Test Payee", **overrides) -> dict:
    return create_transaction_payload(
        customer_id, drawer_id, "MONEY_ORDER", face_amount_cents,
        payee_name=payee_name, **overrides)


def create_wire_payload(customer_id, drawer_id, face_amount_cents,
                        destination_country="MX", beneficiary_name="Test Beneficiary",
                        **overrides) -> dict:
    return create_transaction_payload(
        customer_id, drawer_id, "WIRE", face_amount_cents,
        destination_country=destination_country, beneficiary_name=beneficiary_name, **overrides)


def create_bill_pay_payload(customer_id, drawer_id, face_amount_cents,
                            biller_code="ELEC", account_reference="ACC-1", **overrides) -> dict:
    return create_transaction_payload(
        customer_id, drawer_id, "BILL_PAY", face_amount_cents,
        biller_code=biller_code, account_reference=account_reference, **overrides)


def create_prepaid_load_payload(customer_id, drawer_id, face_amount_cents,
                                card_last_four="4242", **overrides) -> dict:
    return create_transaction_payload(
        customer_id, drawer_id, "PREPAID_LOAD", face_amount_cents,
        card_last_four=card_last_four, **overrides)


# ----- Return / recover (PRD §3.9) -----
def return_payload(return_reason="NSF", **overrides) -> dict:
    defaults = {"return_reason": return_reason}
    defaults.update(overrides)
    return defaults


def recover_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def close_payload(counted_cash_cents, expected_drawer_version, **overrides) -> dict:
    defaults = {
        "counted_cash_cents": counted_cash_cents,
        "expected_drawer_version": expected_drawer_version,
    }
    defaults.update(overrides)
    return defaults


# Named fee schedules used repeatedly across difficulty / corner setups.
GOVT_SCHEDULE = {
    "check_type": "GOVERNMENT", "base_fee_cents": 99, "percent_rate_bps": 100,
    "tier_breakpoint_cents": 500000, "high_percent_rate_bps": 200,
    "max_fee_cents": 50000, "active": True,
}
PAYROLL_DIVERGENT_SCHEDULE = {
    "check_type": "PAYROLL", "base_fee_cents": 199, "percent_rate_bps": 150,
    "tier_breakpoint_cents": 199999, "high_percent_rate_bps": 275,
    "max_fee_cents": 2000000, "active": True,
}

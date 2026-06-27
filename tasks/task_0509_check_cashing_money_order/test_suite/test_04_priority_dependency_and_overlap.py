"""Depth tests on validation-priority conflicts, cross-entity state dependencies,
and resource temporal-overlap (single-occupancy drawer + rolling velocity window)
(PRD §2.11, §3.3, §3.4, §3.7, §3.8)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    create_check_cash_payload, create_money_order_payload, create_cash_drawer_payload,
    create_compliance_screen_payload,
    setup_verified_customer_and_drawer, setup_verified_customer_drawer_and_schedule,
    setup_risk_held_check, setup_closed_drawer, setup_velocity_saturated_customer,
    create_customer, create_govt_schedule, open_drawer,
    make_teller_headers, make_store_manager_headers,
)

TELLER = make_teller_headers("teller-1")
MANAGER = make_store_manager_headers("manager-9")


# ===== Rule 5: validation-priority conflicts (PRD §2.11) =====

def test_sod_beats_kyc_on_release(api):
    """PRD §2.11: "then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); then the KYC
    gate (`ERR_KYC_NOT_VERIFIED`)".
    PRD §2.7: "the manager's `X-User-ID` must differ from the `X-User-ID` recorded as the
    creating Teller of the underlying transaction. If they are the same operator, the
    request is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    A release by the creating teller (SoD violation, priority 5) on a customer re-screened
    to REJECTED (KYC violation, priority 6) returns ERR_SEGREGATION_OF_DUTIES.

    Design: Difficulty/priority_pair_validation_conflict/sod_beats_kyc_on_release
    """
    cust, drawer, sched, txn, check = setup_risk_held_check(
        store_code="S9", face_amount_cents=350000, maker_account_risk="LOW",
        teller_id="teller-1", schedule="payroll")
    # Re-screen to REJECTED so kyc_status is no longer VERIFIED.
    validate_success(api.create_compliance_screen(
        create_compliance_screen_payload(cust["id"], ofac_list_hit=False,
                                         kyc_documents_valid=False), MANAGER), 201)
    # Release attempted by the SAME operator who created the txn (teller-1 acting as manager).
    res = api.release_check_item(check["id"], make_store_manager_headers("teller-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    fetched = validate_success(api.get_check_item(check["id"], MANAGER), 200)
    assert fetched["verification_state"] == "RISK_HELD"


def test_drawer_not_open_beats_daily_limit_on_post(api):
    """PRD §2.11: "then drawer-open status (`ERR_DRAWER_NOT_OPEN`); then embargoed wire
    destination (`ERR_EMBARGOED_DESTINATION`); then the per-transaction risk ceiling
    (`ERR_RISK_CEILING_EXCEEDED`); then the daily transaction-count limit
    (`ERR_VELOCITY_LIMIT_EXCEEDED`); then the daily cash-amount limit
    (`ERR_DAILY_LIMIT_EXCEEDED`)".

    Five auto-clearing CHECK_CASH of 180000 (cashed 900000) then drawer -> RECONCILING.
    A CHECK_CASH face=200000 (would project cashed 1100000 > 1000000) against the
    RECONCILING drawer returns ERR_DRAWER_NOT_OPEN (priority 9) before the fiscal limit.

    Design: Difficulty/priority_pair_validation_conflict/drawer_not_open_beats_daily_limit_on_post
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="S10", opening_float_cents=2000000)
    for _ in range(5):
        validate_success(api.create_transaction(
            create_check_cash_payload(cust["id"], drawer["id"], 180000, sched["id"], "LOW"),
            TELLER), 201)
    validate_success(api.begin_reconcile_drawer(drawer["id"], MANAGER), 200)

    res = api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 200000, sched["id"], "LOW"),
        TELLER)
    validate_error(res, ApiErrorId.ERR_DRAWER_NOT_OPEN, expected_status=409)


# ===== Rule 7: cross-entity state dependencies =====

def test_post_requires_customer_kyc_verified(api):
    """PRD §2.8: "Before any posting, the customer's `kyc_status` must be `VERIFIED`; if it
    is anything else, the posting is rejected with `ERR_KYC_NOT_VERIFIED`."

    A customer never screened (kyc_status PENDING) posting a CHECK_CASH is rejected with
    ERR_KYC_NOT_VERIFIED.

    Design: Difficulty/cross_entity_state_dependency/transaction_post_requires_customer_kyc_verified
    """
    cust = create_customer(full_name="Una Screened", id_type="PASSPORT",
                           id_number="P-13", date_of_birth="1993-03-13")
    sched = create_govt_schedule()
    drawer = open_drawer(store_code="S13", opening_float_cents=1000000)
    res = api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER)
    validate_error(res, ApiErrorId.ERR_KYC_NOT_VERIFIED, expected_status=403)


def test_post_requires_drawer_open(api):
    """PRD §3.3: "Any attempt to post a transaction, void a transaction, or release a
    risk-held check against a drawer that is `RECONCILING`, `CLOSED`, or `OVER_SHORT` is
    rejected with `ERR_DRAWER_NOT_OPEN`."

    A posting against a CLOSED drawer (opened, begin-reconciled, closed with matching count)
    is rejected with ERR_DRAWER_NOT_OPEN.

    Design: Difficulty/cross_entity_state_dependency/transaction_post_requires_drawer_open
    """
    cust = create_customer(full_name="Ned Drawer", id_type="DRIVERS_LICENSE",
                           id_number="DL-14", date_of_birth="1987-07-17")
    validate_success(api.create_compliance_screen(
        create_compliance_screen_payload(cust["id"]), MANAGER), 201)
    sched = create_govt_schedule()
    drawer = setup_closed_drawer(store_code="S14", opening_float_cents=500000)
    assert drawer["status"] == "CLOSED"
    res = api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER)
    validate_error(res, ApiErrorId.ERR_DRAWER_NOT_OPEN, expected_status=409)


# ===== Rule 8: resource temporal-overlap =====

def test_drawer_single_occupancy_same_store_date_conflict(api):
    """PRD §3.3: "Attempting to open a second drawer for the same `store_code` and
    `business_date` while one is already `OPEN` is rejected with `ERR_DRAWER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/drawer_single_occupancy_same_store_date_conflict
    """
    open_drawer(store_code="S15", business_date="2026-05-01", opening_float_cents=1000000)
    res = api.create_cash_drawer(
        create_cash_drawer_payload(store_code="S15", business_date="2026-05-01",
                                   opening_float_cents=800000), MANAGER)
    validate_error(res, ApiErrorId.ERR_DRAWER_CONFLICT, expected_status=409)


def test_velocity_rolling_window_saturated_13th_rejected(api):
    """PRD §3.8: "The projected transaction count is the current `daily_transaction_count`
    plus 1; if that projected count would exceed the daily transaction limit of 12, the
    posting is rejected with `ERR_VELOCITY_LIMIT_EXCEEDED`."

    Twelve MONEY_ORDERs inside the window saturate DAILY_TXN_LIMIT=12; a 13th posting at
    the same clock is rejected and daily_transaction_count stays 12.

    Design: Difficulty/resource_temporal_overlap/velocity_rolling_window_half_open_aggregate
    """
    cust, drawer = setup_velocity_saturated_customer(
        store_code="S16", clock="2026-05-01T08:00:00Z", n=12, face_amount_cents=1000)
    res = api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 1000, "P13"), TELLER)
    validate_error(res, ApiErrorId.ERR_VELOCITY_LIMIT_EXCEEDED, expected_status=422)
    cust_after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert cust_after["daily_transaction_count"] == 12

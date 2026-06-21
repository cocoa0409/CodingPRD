"""Role-based access control, optimistic concurrency on units, multi-target
cancellation cascades, derived-field reconciliation, and immediate consistency.

Covers the rbac, cross_cutting_complexity_layers, and consistency_model corner
instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    setup_dealership_customer_unit,
    setup_finance_requested_deal,
    setup_started_service_order,
    create_deal_on_unit,
    create_dealership,
    create_customer,
    create_unit,
    create_part_item,
    create_service_bay,
    create_recall_campaign,
    reserve_part,
    create_appointment_payload,
)

SALES = TEST_USERS["sales_agent_headers"]
MGR = TEST_USERS["dealer_manager_headers"]
SVC = TEST_USERS["service_advisor_headers"]


# ===========================================================================
# Corner: rbac / sales_agent_cannot_make_finance_decision
# ===========================================================================
def test_sales_agent_cannot_make_finance_decision(api):
    """PRD §2.1: "A `DealerManager` is the override and approval authority —
    responsible for dealership setup, the deterministic clock, financing approvals
    and declines".
    PRD §2.1: "When the headers are present and well-formed but the declared role
    is not permitted to perform the requested operation, the request is rejected
    with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/sales_agent_cannot_make_finance_decision
    """
    dealer, customer, unit, deal_id = setup_finance_requested_deal(
        credit_tier="PRIME", list_price_cents=8000000, sale_price_cents=6000000,
        term_months=60, down_payment_cents=0,
    )
    resp = api.finance_decision(deal_id, {"decision": "APPROVE"}, SALES)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Corner: rbac / customer_cannot_create_deal
# ===========================================================================
def test_customer_cannot_create_deal(api):
    """PRD §2.1: "A `Customer` has self-service read access only and may never
    mutate any resource."
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/customer_cannot_create_deal
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"list_price_cents": 7000000}
    )
    resp = api.create_deal(
        {
            "dealership_id": dealer["id"], "unit_id": unit["id"],
            "customer_id": customer["id"], "sale_price_cents": 7000000,
            "expected_unit_version": unit["version"],
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Corner: rbac / sales_agent_cannot_open_recall_campaign
# ===========================================================================
def test_sales_agent_cannot_open_recall_campaign(api):
    """PRD §3.11: "A `DealerManager` opens a **RecallCampaign** with a
    `campaign_code` unique within the dealership".
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/sales_agent_cannot_open_recall_campaign
    """
    dealer = create_dealership(name="Rb3 RV")
    resp = api.create_recall_campaign(
        {
            "dealership_id": dealer["id"], "campaign_code": "RC-FORBID-1",
            "target_class_type": "CLASS_C", "target_model_year": 2024, "severity": "ADVISORY",
        },
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Corner: rbac / missing_auth_header_returns_401
# ===========================================================================
def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "Every request to the API must be authenticated through two
    mandatory HTTP headers. ... If either header is missing or malformed, the
    request is rejected with `ERR_MISSING_AUTH`."

    Design: Corner/rbac/missing_auth_header_returns_401
    """
    dealer = create_dealership(name="Auth RV")
    resp = api.create_customer(
        {"dealership_id": dealer["id"], "full_name": "No Auth", "email": "noauth@x.com"},
        {},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


# ===========================================================================
# Corner: cross_cutting / occ_stale_unit_version_on_deal_create
# ===========================================================================
def test_deal_create_with_stale_unit_version_rejected(api):
    """PRD §2.7: "A request to create a Deal must carry an `expected_unit_version`
    field whose value equals the target unit's current `version`. If another writer
    has advanced the unit's version since the client last read it ... the create is
    rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)".

    A first deal (then cancel) bumps the unit version twice; retry with the stale
    pre-hold version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_unit_version_on_deal_create
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"list_price_cents": 7000000}
    )
    stale_version = unit["version"]
    deal1 = create_deal_on_unit(dealer, customer, unit, 7000000)
    get_success_data(api_client.cancel_deal(deal1["id"], SALES))
    resp = api.create_deal(
        {
            "dealership_id": dealer["id"], "unit_id": unit["id"],
            "customer_id": customer["id"], "sale_price_cents": 7000000,
            "expected_unit_version": stale_version,
        },
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_UNIT_VERSION.value)


# ===========================================================================
# Corner: cross_cutting / occ_correct_unit_version_storage_book_succeeds
# ===========================================================================
def test_storage_book_with_current_version_bumps_unit(api):
    """PRD §3.10: "A successful booking opens in `BOOKED` status and bumps the
    unit's `version` as part of the concurrency-guarded write."
    PRD §2.7: "A request to book a StorageSlot must likewise carry
    `expected_unit_version` matching the target unit's current `version`".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_unit_version_storage_book_succeeds
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"list_price_cents": 5000000}
    )
    v0 = unit["version"]
    slot = validate_success(
        api.create_storage_slot(
            {
                "dealership_id": dealer["id"], "unit_id": unit["id"], "customer_id": customer["id"],
                "daily_rate_cents": 5000, "start_utc": "2026-06-01T00:00:00.000Z",
                "end_utc": "2026-06-10T00:00:00.000Z", "expected_unit_version": v0,
            },
            SVC,
        ),
        expected_status=201,
    )
    assert slot["status"] == "BOOKED", slot["status"]
    unit_after = validate_success(api.get_unit(unit["id"], SVC))
    assert unit_after["version"] == v0 + 1, unit_after["version"]


# ===========================================================================
# Corner: cross_cutting / so_cancel_releases_parts_and_appointments_cascade
# ===========================================================================
def test_so_cancel_releases_parts_and_appointments(api):
    """PRD §3.7: "Cancellation moves the order to the terminal `CANCELLED` and
    triggers two cascades: every `RESERVED` reservation for the order is moved to
    `RELEASED`, returning its quantity to stock by lowering each backing part's
    `qty_reserved` and recomputing `qty_available`; and every `SCHEDULED` or
    `CHECKED_IN` appointment for the order is moved to `CANCELLED`, freeing the bay
    interval."

    Design: Corner/cross_cutting_complexity_layers/so_cancel_releases_parts_and_appointments_cascade
    """
    dealer, customer, unit, so = setup_started_service_order()
    part = create_part_item(dealer["id"], unit_price_cents=3000, qty_on_hand=8)
    bay = create_service_bay(dealer["id"], name="Repair-C", bay_kind="REPAIR")
    reserve_part(so["id"], part["id"], 3)
    appt = get_success_data(
        api_client.create_appointment(
            create_appointment_payload(
                dealer["id"], bay["id"], "REPAIR",
                "2026-06-01T09:00:00.000Z", "2026-06-01T10:00:00.000Z",
                service_order_id=so["id"],
            ),
            SVC,
        )
    )
    get_success_data(api_client.cancel_service_order(so["id"], SVC))
    part_after = validate_success(api.get_part_item(part["id"], SVC))
    assert part_after["qty_reserved"] == 0, part_after["qty_reserved"]
    assert part_after["qty_available"] == 8, part_after["qty_available"]
    appt_after = validate_success(api.get_appointment(appt["id"], SVC))
    assert appt_after["status"] == "CANCELLED", appt_after["status"]


# ===========================================================================
# Corner: cross_cutting / recall_remediation_recomputes_unit_open_recall_count
# ===========================================================================
def test_recall_remediation_clears_unit_open_recall_count(api):
    """PRD §3.11: "A remedy is cleared in the field by completing a service order
    that names the campaign as the one it remediates, which carries the remedy's
    `status` from `PENDING` to `CLEARED` and refreshes the affected unit's
    `open_recall_count`."

    A unit at open_recall_count 1 drops to 0 after the remediating completion.

    Design: Corner/cross_cutting_complexity_layers/recall_remediation_recomputes_unit_open_recall_count
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"class_type": "CLASS_A", "list_price_cents": 9000000}
    )
    rc = create_recall_campaign(
        dealer["id"], target_class_type="CLASS_A", target_model_year=2024, severity="STOP_SALE"
    )
    so = get_success_data(
        api_client.create_service_order(
            {"dealership_id": dealer["id"], "unit_id": unit["id"], "customer_id": customer["id"],
             "labor_hours": 1.0, "labor_rate_cents": 10000}, SVC
        )
    )
    get_success_data(api_client.start_service_order(so["id"], SVC))
    completed = validate_success(
        api.complete_service_order(so["id"], SVC, {"remediates_campaign_id": rc["id"]})
    )
    assert completed["status"] == "COMPLETED", completed["status"]
    unit_after = validate_success(api.get_unit(unit["id"], SVC))
    assert unit_after["open_recall_count"] == 0, unit_after["open_recall_count"]


# ===========================================================================
# Corner: consistency_model / deal_create_hold_visible_immediately
# ===========================================================================
def test_deal_hold_visible_immediately_on_unit(api):
    """PRD §3.3: "A freshly created deal opens with `sale_status` of `DRAFT` ... and
    — as a side effect — places the unit hold described in §3.2."
    PRD §3.2: "the unit transitions from `AVAILABLE` to `HELD`, its
    `active_hold_deal_id` is set to the new deal's identifier".

    Right after POST /deals, a GET on the unit shows HELD with the active hold set.

    Design: Corner/consistency_model/deal_create_hold_visible_immediately
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"list_price_cents": 7000000}
    )
    deal = create_deal_on_unit(dealer, customer, unit, 7000000)
    unit_after = validate_success(api.get_unit(unit["id"], SALES))
    assert unit_after["status"] == "HELD", unit_after["status"]
    assert unit_after["active_hold_deal_id"] == deal["id"], unit_after["active_hold_deal_id"]

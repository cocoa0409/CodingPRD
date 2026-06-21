"""Entity CRUD corner cases: creation, not-found, required fields, defaults,
system fields, immutability, listing.

Queue B (Corner) — section entities.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_traveler,
    assert_per_diem_rate,
    create_approver,
    setup_base_env,
    create_approved_trip,
    create_report,
    add_mileage_line,
    issue_card,
)


def test_create_traveler_returns_201_active(api):
    """PRD §3.1: "a traveler is created with an email (their unique login), a
    full_name, a home_office_state (the two-letter code of their home office), and a
    manager_id pointing to the approver who reviews that traveler's reports, and is
    created in ACTIVE status."

    Design: Corner/entities/create_traveler_returns_201_with_fields
    """
    approver = create_approver(approval_limit_cents=500000)
    resp = api.create_traveler(
        {
            "email": "ct1@x.com", "full_name": "CTrav1",
            "home_office_state": "CA", "manager_id": approver["id"],
        },
        get_admin_headers(),
    )
    data = validate_success(resp, expected_status=201)
    assert_traveler(data)
    assert data["status"] == "ACTIVE"
    assert data["email"] == "ct1@x.com"
    assert data["home_office_state"] == "CA"


def test_get_traveler_not_found(api):
    """PRD §2.6: "all path-referenced resources and any required foreign-key
    references in the body must resolve to existing entities, checked left-to-right,
    with the first unresolved reference yielding ERR_NOT_FOUND."

    Design: Corner/entities/get_traveler_not_found
    """
    resp = api.get_traveler(NON_EXISTENT_UUID, get_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_traveler_missing_manager_id_rejected(api):
    """PRD §2.6: "Body well-formedness is fifth: required fields present, enum values
    drawn from their permitted set, and integers non-negative — a violation yields
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_traveler_missing_required_field
    """
    resp = api.create_traveler(
        {"email": "ct2@x.com", "full_name": "CTrav2", "home_office_state": "CA"},
        get_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_expense_report_per_diem_method_defaults_to_per_diem(api):
    """PRD §3.4: "The per_diem_method selects the meal-reimbursement variant and is
    one of PER_DIEM or ITEMIZED; when omitted it defaults to PER_DIEM."

    Design: Corner/entities/expense_report_per_diem_method_default
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=50000)
    report = create_report(env, trip, title="Default Rpt")  # no per_diem_method
    fetched = get_success_data(api.get_expense_report(report["id"], env["admin_headers"]))
    assert fetched["per_diem_method"] == "PER_DIEM"


def test_virtual_card_computed_fields_on_issue(api):
    """PRD §3.3: "A successful issuance creates the card in ACTIVE status, initializes
    its computed buckets authorized_holds_cents and captured_total_cents to zero so
    that available_balance_cents equals the full load_limit_cents"

    Design: Corner/entities/virtual_card_computed_fields_ignore_input
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=100000)
    card = issue_card(env, trip, load_limit_cents=80000)
    assert card["available_balance_cents"] == 80000
    assert card["authorized_holds_cents"] == 0
    assert card["captured_total_cents"] == 0


def test_per_diem_rate_immutable_id_and_created_at_only(api):
    """PRD §2.4: "The one exception is the PerDiemRate resource, which is immutable GSA
    reference data: a PerDiemRate carries only id and created_at, and has neither an
    updated_at field nor a version field."

    Design: Corner/entities/per_diem_rate_immutable_no_version
    """
    rate = get_success_data(
        api.create_per_diem_rate(
            {"state_code": "NY", "lodging_cap_cents": 30000, "mie_cents": 9000},
            get_admin_headers(),
        )
    )
    fetched = validate_success(
        api.get_per_diem_rate(rate["id"], get_admin_headers()), expected_status=200
    )
    assert_per_diem_rate(fetched)
    assert fetched["state_code"] == "NY"
    assert fetched["lodging_cap_cents"] == 30000


def test_list_expense_lines_filtered_by_report(api):
    """PRD §2.3: "List responses surface limit, offset, total_count, and has_more
    inside the meta object so a client can page deterministically."

    Design: Corner/entities/list_expense_lines_filtered_by_report
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=100000)
    report = create_report(env, trip, title="List Rpt")
    add_mileage_line(env, report, miles=100)
    add_mileage_line(env, report, miles=50)
    resp = api.list_expense_lines(env["traveler_headers"], params={"report_id": report["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# --- local admin headers helper (opaque FinanceAdmin) ---
def get_admin_headers():
    from test_helpers import make_finance_admin_headers
    return make_finance_admin_headers()

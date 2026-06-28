"""Entity CRUD, creation, defaults, computed fields, and not-found cases.

Queue B (Corner) translations for the entities section.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_counselor_headers, make_creditor_rep_headers, make_agency_admin_headers,
    create_agency, create_counselor, create_creditor, create_client,
    open_intake_session, complete_session, add_and_accept_account, activate,
    record_deposit, create_agency_payload, create_client_payload,
    create_counselor_payload, create_debt_account_payload, deposit_payload,
    TEST_USERS, api_client,
)


def test_create_agency_returns_all_fields(api):
    """PRD §3.1: "A newly created agency starts its disbursement cycle counter,
    `current_cycle_index`, at 0; this counter advances by one each time a
    disbursement cycle is run."
    PRD §2.4: "The `version` is an integer that begins at its initial value and
    increments by one with every mutation; it underpins the optimistic
    concurrency control described below."

    Design: Corner/entities/create_agency_returns_all_fields
    """
    admin = make_agency_admin_headers()
    resp = api.create_agency(
        create_agency_payload(name="MMI", setup_fee_cents=5000, monthly_fee_cents=3500), admin
    )
    data = validate_success(resp, 201)
    assert data["current_cycle_index"] == 0
    assert data["setup_fee_cents"] == 5000
    assert data["version"] == 1


def test_get_client_not_found(api):
    """PRD §2.5: "the system validates those identifiers left to right and rejects
    the first one that does not resolve to an existing resource within the agency
    with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_client_not_found
    """
    create_agency()
    resp = api.get_client(
        "00000000-0000-4000-8000-000000000000", TEST_USERS["counselor_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_client_missing_required_field(api):
    """PRD §3.2: "A `Counselor` opens a client file by creating a `Client` with
    `agency_id`, the assigned `counselor_id`, the client's `full_name`, the
    verified `gross_monthly_income_cents` (which must be greater than zero), and
    an optional `housing_payment_cents` for monthly rent or mortgage."

    Design: Corner/entities/create_client_missing_required_field
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    cn = make_counselor_headers(counselor["id"])
    payload = {"agency_id": agency["id"], "counselor_id": counselor["id"], "full_name": "Dan"}
    resp = api.create_client(payload, cn)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_counselor_hud_certified_default_false(api):
    """PRD §3.1: "A counselor is created with a `full_name` and an optional
    `hud_certified` flag (defaulting to false) that governs whether they may
    issue HUD housing certificates."
    PRD §3.1: "A counselor's `status` is always `ACTIVE` on creation and has no
    further lifecycle."

    Design: Corner/entities/counselor_hud_certified_default_false
    """
    agency = create_agency()
    admin = make_agency_admin_headers()
    resp = api.create_counselor(create_counselor_payload(agency["id"], full_name="Cy"), admin)
    # remove hud_certified to exercise the default
    payload = create_counselor_payload(agency["id"], full_name="Cy")
    payload.pop("hud_certified")
    resp = api.create_counselor(payload, admin)
    data = validate_success(resp, 201)
    assert data["hud_certified"] is False
    assert data["status"] == "ACTIVE"


def test_client_dti_computed_no_debts(api):
    """PRD §3.2: "The `front_end_dti` is the housing payment divided by gross
    monthly income, multiplied by 100, taken to two decimal places by
    round-half-up."
    PRD §3.2: "At intake, before any debts exist, back-end DTI reflects only the
    housing component."

    Design: Corner/entities/client_dti_computed_input_ignored
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    client = create_client(
        agency["id"], counselor["id"],
        gross_monthly_income_cents=500000, housing_payment_cents=150000,
    )
    assert client["front_end_dti"] == 30.0
    assert client["back_end_dti"] == 30.0
    assert client["status"] == "INTAKE"


def test_duplicate_account_ref_rejected_valid_creditor(api):
    """PRD §3.4: "The account's `account_ref` must be unique among the client's
    accounts that are not `DROPPED`; a collision is rejected with
    `ERR_DUPLICATE_ACCOUNT_REF`."

    Design: Corner/entities/duplicate_account_ref_rejected
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])
    api.create_debt_account(
        client["id"],
        create_debt_account_payload(
            creditor["id"], account_ref="DUP", original_balance_cents=300000,
            proposed_monthly_payment_cents=30000,
        ),
        cn,
    )
    resp = api.create_debt_account(
        client["id"],
        create_debt_account_payload(
            creditor["id"], account_ref="DUP", original_balance_cents=200000,
            original_apr=0.1999, min_payment_cents=4500,
            proposed_monthly_payment_cents=15000, requested_concession_apr=0.0699,
        ),
        cn,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACCOUNT_REF.value, expected_status=409)


def test_deposit_record_has_no_version_field(api):
    """PRD §2.4: "A `DepositRecord` captures a single received deposit and is never
    modified after creation."
    PRD §2.4: "Two entities are deliberately append-only event records and carry
    only `id` and `created_at` — they have neither `updated_at` nor `version`."

    Design: Corner/entities/deposit_record_immutable_no_version
    """
    agency, counselor, creditor, client, accts = _active_single_account()
    cn = make_counselor_headers(counselor["id"])
    resp = api.record_deposit(client["id"], deposit_payload(33500), cn)
    data = validate_success(resp, 201)
    assert data["cycle_index"] == 0
    assert "version" not in data


def test_debt_account_under_missing_client_not_found(api):
    """PRD §2.5: "the system validates those identifiers left to right and rejects
    the first one that does not resolve to an existing resource within the agency
    with `ERR_NOT_FOUND`. This existence check on path-referenced resources runs
    before any body-level or business validation."

    Design: Corner/entities/debt_account_requires_valid_client_parent
    """
    agency = create_agency()
    creditor = create_creditor(agency["id"])
    counselor = create_counselor(agency["id"])
    cn = make_counselor_headers(counselor["id"])
    resp = api.create_debt_account(
        "00000000-0000-4000-8000-000000000000",
        create_debt_account_payload(
            creditor["id"], account_ref="A", original_balance_cents=300000,
            proposed_monthly_payment_cents=30000,
        ),
        cn,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def _active_single_account(monthly_fee_cents=3500):
    agency = create_agency(monthly_fee_cents=monthly_fee_cents)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    session = open_intake_session(client["id"], counselor["id"])
    acct = add_and_accept_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    complete_session(session["id"], counselor["id"])
    client = activate(client["id"], counselor["id"])
    return agency, counselor, creditor, client, {"A": acct}

"""Validation priority conflicts, cross-entity state gates, exclusive occupancy,
empty-set boundary, and body-validation corners.

Difficulty: priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap (unit exclusive occupancy), boundary_precision (empty
ACTIVE set). Corner: payment zero amount, invalid enum, mark-delinquent on PAID.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    create_resort, create_owner, create_inventory_unit, create_active_contract,
    create_contract, create_issued_invoice, setup_lien_case,
    setup_active_contract_with_unit, get_points_account,
    create_resale_transfer_payload, create_special_assessment_payload, levy_payload,
    create_invoice_payload, create_payment_payload, create_reservation_payload,
    set_clock, make_owner_headers, TEST_USERS,
)

_RM = TEST_USERS["resort_manager_headers"]
_RA = TEST_USERS["resale_agent_headers"]
_CO = TEST_USERS["compliance_officer_headers"]


def _list(response):
    body = response.json()
    return body["data"], body.get("meta", {})


# =========================================================================== #
# Difficulty: priority_pair_validation_conflict
# =========================================================================== #
def test_rescind_active_contract_after_window_returns_invalid_state(api):
    """PRD §2.7: "the target resource being in a legal from-state for the requested transition,
    yielding `ERR_INVALID_STATE`."
    PRD §2.7: "After those seven structural gates, the business gates apply, themselves ordered:
    rescission-window safety (`ERR_RESCISSION_WINDOW_OPEN` or
    `ERR_RESCISSION_WINDOW_CLOSED`)".

    Design: Difficulty/priority_pair_validation_conflict/rescind_state_vs_rescission_window_priority
    """
    # ACTIVE contract (not PENDING_RESCISSION) rescinded after the window closed:
    # state gate (priority 7) outranks the business rescission-window gate.
    resort = create_resort(rescission_days=7)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=5000)
    set_clock(resort["id"], "2026-02-01T00:00:00Z")  # window long closed
    resp = api.rescind_contract(contract["id"], make_owner_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    c = get_success_data(api.get_contract(contract["id"], _RM))
    assert c["status"] == "ACTIVE", f"status must remain ACTIVE, got {c['status']}"


def test_rescind_terminated_contract_returns_invalid_state(api):
    """PRD §2.7: "the target resource being in a legal from-state for the requested transition,
    yielding `ERR_INVALID_STATE`."
    PRD §3.2: "An `Owner` or a `ComplianceOfficer` may rescind a `PENDING_RESCISSION` contract,
    moving it to `RESCINDED".

    Design: Difficulty/priority_pair_validation_conflict/rescind_state_vs_rescission_window_priority
    """
    # A contract in a non-PENDING_RESCISSION state (TERMINATED) trips the state
    # gate (priority 7) on rescind regardless of the rescission-window gate.
    resort, owner, contract, invoice, case = setup_lien_case(
        escalations=2, resort_overrides={"foreclosure_threshold_periods": 2},
        contract_overrides={"ownership_type": "RIGHT_TO_USE", "annual_points_allotment": 8000,
                            "rtu_expiry_use_year": 2030})
    get_success_data(api.foreclose_delinquency_case(case["id"], _CO))  # contract -> TERMINATED
    c0 = get_success_data(api.get_contract(contract["id"], _RM))
    assert c0["status"] == "TERMINATED"
    resp = api.rescind_contract(contract["id"], make_owner_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_suspended_contract_unit_reserved_returns_contract_not_active(api):
    """PRD §2.7: "the owning-contract-active gate (`ERR_CONTRACT_NOT_ACTIVE`);
    inventory availability at confirm time (`ERR_UNIT_NOT_AVAILABLE`)".
    PRD §3.4: "Confirmation requires that the owning contract be `ACTIVE`; otherwise the request is
    rejected with `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_contract_not_active_vs_unit_unavailable_priority
    """
    # C2 confirms U (U -> RESERVED). C1 is SUSPENDED via its own LIEN escalation;
    # then O1 HELDs a reservation on U. Confirming it: both the contract-active
    # gate AND the unit-availability gate would fail; contract-active (higher
    # priority) wins.
    resort = create_resort(delinquency_grace_days=30)
    owner1 = create_owner(resort["id"], full_name="O1", email="o1@x.com")
    owner2 = create_owner(resort["id"], full_name="O2", email="o2@x.com")
    unit = create_inventory_unit(resort["id"], unit_label="Villa Gold", week_number=30, season="GOLD")
    c1 = create_active_contract(resort["id"], owner1["id"], annual_points_allotment=5000)
    c2 = create_active_contract(resort["id"], owner2["id"], annual_points_allotment=5000)

    # C2 confirms U.
    acct2 = get_points_account(c2["id"], 2026, owner2["id"])
    h2 = make_owner_headers(owner2["id"])
    resv2 = get_success_data(api.create_reservation(
        create_reservation_payload(c2["id"], unit["id"], 2026, acct2["version"]), h2))
    get_success_data(api.confirm_reservation(resv2["id"], h2))

    # C1 -> SUSPENDED via its own delinquency LIEN.
    inv1 = create_issued_invoice(resort, c1, use_year=2026, due_date="2026-02-01T00:00:00Z")
    set_clock(resort["id"], "2026-03-10T00:00:00Z")
    get_success_data(api.mark_invoice_delinquent(inv1["id"], _RM))
    cases, _m = _list(api.list_delinquency_cases(_CO, params={"contract_id": c1["id"]}))
    get_success_data(api.escalate_delinquency_case(cases[0]["id"], _CO))
    c1_now = get_success_data(api.get_contract(c1["id"], _RM))
    assert c1_now["status"] == "SUSPENDED"

    # O1 HELDs a reservation on U (create is not unit-availability-gated).
    acct1 = get_points_account(c1["id"], 2026, owner1["id"])
    h1 = make_owner_headers(owner1["id"])
    resv1 = get_success_data(api.create_reservation(
        create_reservation_payload(c1["id"], unit["id"], 2026, acct1["version"]), h1))

    resp = api.confirm_reservation(resv1["id"], h1)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)
    r = get_success_data(api.get_reservation(resv1["id"], h1))
    assert r["status"] == "HELD", f"reservation must stay HELD, got {r['status']}"


def test_confirm_suspended_contract_with_available_unit_returns_contract_not_active(api):
    """PRD §2.7: "the owning-contract-active gate (`ERR_CONTRACT_NOT_ACTIVE`); inventory availability
    at confirm time (`ERR_UNIT_NOT_AVAILABLE`)".
    PRD §3.4: "Confirmation requires that the owning contract be `ACTIVE`; otherwise the request is
    rejected with `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_contract_not_active_vs_unit_unavailable_priority
    """
    # The higher-priority gate (contract-active) fires even when the unit IS
    # available — confirming the gate's precedence in the absence of the lower one.
    resort = create_resort(delinquency_grace_days=30)
    owner = create_owner(resort["id"])
    unit = create_inventory_unit(resort["id"], unit_label="Villa Gold", week_number=31, season="GOLD")
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=5000)
    # Suspend the contract via LIEN.
    inv = create_issued_invoice(resort, contract, use_year=2026, due_date="2026-02-01T00:00:00Z")
    set_clock(resort["id"], "2026-03-10T00:00:00Z")
    get_success_data(api.mark_invoice_delinquent(inv["id"], _RM))
    cases, _m = _list(api.list_delinquency_cases(_CO, params={"contract_id": contract["id"]}))
    get_success_data(api.escalate_delinquency_case(cases[0]["id"], _CO))
    # Reservation created after suspension; unit is still AVAILABLE (nobody confirmed).
    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resv = get_success_data(api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers))
    unit_now = get_success_data(api.get_inventory_unit(unit["id"], headers))
    assert unit_now["status"] == "AVAILABLE"
    resp = api.confirm_reservation(resv["id"], headers)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)


# =========================================================================== #
# Difficulty: cross_entity_state_dependency
# =========================================================================== #
def test_confirm_requires_owning_contract_active(api):
    """PRD §3.4: "Confirmation requires that the owning contract be `ACTIVE`; otherwise the request is
    rejected with `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_requires_contract_active
    """
    resort = create_resort(delinquency_grace_days=30)
    owner = create_owner(resort["id"])
    unit = create_inventory_unit(resort["id"], unit_label="Villa Gold", week_number=33, season="GOLD")
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=5000)

    # Suspend the contract via its own delinquency LIEN (no HELD reservations yet).
    inv = create_issued_invoice(resort, contract, use_year=2026, due_date="2026-02-01T00:00:00Z")
    set_clock(resort["id"], "2026-03-10T00:00:00Z")
    get_success_data(api.mark_invoice_delinquent(inv["id"], _RM))
    cases, _m = _list(api.list_delinquency_cases(_CO, params={"contract_id": contract["id"]}))
    get_success_data(api.escalate_delinquency_case(cases[0]["id"], _CO))
    c_now = get_success_data(api.get_contract(contract["id"], _RM))
    assert c_now["status"] == "SUSPENDED"

    # Create a HELD reservation AFTER suspension (create is permitted), then confirm.
    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resv = get_success_data(api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers))
    assert resv["status"] == "HELD"
    resp = api.confirm_reservation(resv["id"], headers)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)


def test_confirm_succeeds_when_contract_active(api):
    """PRD §3.4: "Confirmation requires that the owning contract be `ACTIVE`; otherwise the request is
    rejected with `ERR_CONTRACT_NOT_ACTIVE`."
    PRD §3.4: "an `Owner` confirms a `HELD` reservation, advancing it from `HELD` to `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/reservation_confirm_requires_contract_active
    """
    # Positive control on the same cross-entity dependency: an ACTIVE contract
    # permits the HELD->CONFIRMED transition.
    resort, owner, contract, unit = setup_active_contract_with_unit(
        season="GOLD", week_number=34, contract_overrides={"annual_points_allotment": 5000})
    acct = get_points_account(contract["id"], 2026, owner["id"])
    headers = make_owner_headers(owner["id"])
    resv = get_success_data(api.create_reservation(
        create_reservation_payload(contract["id"], unit["id"], 2026, acct["version"]), headers))
    confirmed = validate_success(api.confirm_reservation(resv["id"], headers))
    assert confirmed["status"] == "CONFIRMED", f"expected CONFIRMED, got {confirmed['status']}"


def test_resale_complete_blocked_by_open_delinquency_case(api):
    """PRD §3.9: "the source contract must have no open delinquency case in `NOTICE` or `LIEN`,
    otherwise `ERR_CONTRACT_DELINQUENT`."

    Design: Difficulty/cross_entity_state_dependency/resale_complete_blocked_by_open_delinquency_case
    """
    resort = create_resort(rescission_days=7, delinquency_grace_days=30)
    seller = create_owner(resort["id"], full_name="Seller", email="seller@x.com")
    buyer = create_owner(resort["id"], full_name="Buyer", email="buyer@x.com")
    contract = create_active_contract(resort["id"], seller["id"], annual_points_allotment=10000)

    transfer = get_success_data(api.create_resale_transfer(
        create_resale_transfer_payload(contract["id"], buyer["id"], 2026, 120), _RA))
    # Open a delinquency case (NOTICE) on the source contract.
    inv = create_issued_invoice(resort, contract, use_year=2026, due_date="2026-02-01T00:00:00Z")
    set_clock(resort["id"], "2026-03-10T00:00:00Z")  # also elapses the rescission window
    get_success_data(api.mark_invoice_delinquent(inv["id"], _RM))

    resp = api.complete_resale_transfer(transfer["id"], _RA)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_DELINQUENT.value)
    t = get_success_data(api.get_resale_transfer(transfer["id"], _RM))
    assert t["status"] == "PENDING_RESCISSION", f"transfer must stay PENDING_RESCISSION, got {t['status']}"


def test_resale_complete_succeeds_with_no_open_delinquency_case(api):
    """PRD §3.9: "Completing a transfer is a `ResaleAgent` action gated by three conditions: the
    resort's `current_utc` must be at or after `signed_at` plus `rescission_days`
    days, otherwise `ERR_RESCISSION_WINDOW_OPEN`; the source contract must be
    `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE`; and the source contract must have
    no open delinquency case in `NOTICE` or `LIEN`, otherwise
    `ERR_CONTRACT_DELINQUENT`."
    PRD §3.9: "Completion moves the transfer to `COMPLETED`, cascades the source contract from
    `ACTIVE` to `TRANSFERRED".

    Design: Difficulty/cross_entity_state_dependency/resale_complete_blocked_by_open_delinquency_case
    """
    # Positive control: ACTIVE contract, window elapsed, NO delinquency case ->
    # completion succeeds (the delinquency gate passes).
    resort = create_resort(rescission_days=7)
    seller = create_owner(resort["id"], full_name="Seller", email="seller@x.com")
    buyer = create_owner(resort["id"], full_name="Buyer", email="buyer@x.com")
    contract = create_active_contract(resort["id"], seller["id"], annual_points_allotment=10000)
    transfer = get_success_data(api.create_resale_transfer(
        create_resale_transfer_payload(contract["id"], buyer["id"], 2026, 120), _RA))
    set_clock(resort["id"], "2026-01-20T00:00:00Z")  # window elapsed
    completed = validate_success(api.complete_resale_transfer(transfer["id"], _RA))
    assert completed["status"] == "COMPLETED", f"expected COMPLETED, got {completed['status']}"
    c = get_success_data(api.get_contract(contract["id"], _RM))
    assert c["status"] == "TRANSFERRED", f"source contract -> TRANSFERRED, got {c['status']}"


# =========================================================================== #
# Difficulty: resource_temporal_overlap — unit exclusive occupancy
# =========================================================================== #
def test_second_confirm_of_same_unit_rejected(api):
    """PRD §3.4: "It also requires the target `InventoryUnit` to be `AVAILABLE` at confirm time — many
    reservations may hold the same unit-week, but only one may confirm it, and a
    confirm against a unit that is already `RESERVED` or `DEPOSITED_TO_EXCHANGE` is
    rejected with `ERR_UNIT_NOT_AVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/unit_week_exclusive_occupancy_confirm
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner1 = create_owner(resort["id"], full_name="O1", email="o1@x.com")
    owner2 = create_owner(resort["id"], full_name="O2", email="o2@x.com")
    unit = create_inventory_unit(resort["id"], unit_label="Villa Gold", week_number=40, season="GOLD")
    c1 = create_active_contract(resort["id"], owner1["id"], annual_points_allotment=5000)
    c2 = create_active_contract(resort["id"], owner2["id"], annual_points_allotment=5000)

    acct1 = get_points_account(c1["id"], 2026, owner1["id"])
    h1 = make_owner_headers(owner1["id"])
    resv1 = get_success_data(api.create_reservation(
        create_reservation_payload(c1["id"], unit["id"], 2026, acct1["version"]), h1))
    acct2 = get_points_account(c2["id"], 2026, owner2["id"])
    h2 = make_owner_headers(owner2["id"])
    resv2 = get_success_data(api.create_reservation(
        create_reservation_payload(c2["id"], unit["id"], 2026, acct2["version"]), h2))

    get_success_data(api.confirm_reservation(resv1["id"], h1))  # U -> RESERVED
    resp = api.confirm_reservation(resv2["id"], h2)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)
    r2 = get_success_data(api.get_reservation(resv2["id"], h2))
    assert r2["status"] == "HELD", f"second reservation must stay HELD, got {r2['status']}"


def test_many_held_reservations_allowed_on_same_unit(api):
    """PRD §3.4: "many reservations may hold the same unit-week, but only one may confirm it, and a
    confirm against a unit that is already `RESERVED` or `DEPOSITED_TO_EXCHANGE` is
    rejected with `ERR_UNIT_NOT_AVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/unit_week_exclusive_occupancy_confirm
    """
    # The exclusivity is at confirm time only: two HELD reservations on the same
    # unit-week both succeed at create.
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner1 = create_owner(resort["id"], full_name="O1", email="o1@x.com")
    owner2 = create_owner(resort["id"], full_name="O2", email="o2@x.com")
    unit = create_inventory_unit(resort["id"], unit_label="Villa Gold", week_number=41, season="GOLD")
    c1 = create_active_contract(resort["id"], owner1["id"], annual_points_allotment=5000)
    c2 = create_active_contract(resort["id"], owner2["id"], annual_points_allotment=5000)

    acct1 = get_points_account(c1["id"], 2026, owner1["id"])
    h1 = make_owner_headers(owner1["id"])
    r1 = validate_success(api.create_reservation(
        create_reservation_payload(c1["id"], unit["id"], 2026, acct1["version"]), h1), 201)
    acct2 = get_points_account(c2["id"], 2026, owner2["id"])
    h2 = make_owner_headers(owner2["id"])
    r2 = validate_success(api.create_reservation(
        create_reservation_payload(c2["id"], unit["id"], 2026, acct2["version"]), h2), 201)
    assert r1["status"] == "HELD" and r2["status"] == "HELD", "both HELDs allowed on same unit"


# =========================================================================== #
# Difficulty: boundary_precision_check — levy with empty ACTIVE set
# =========================================================================== #
def test_levy_with_no_active_contracts_rejected(api):
    """PRD §3.7: "Levying it requires at least one `ACTIVE` contract at the resort, otherwise the
    request is rejected with `ERR_NO_ELIGIBLE_CONTRACTS`."

    Design: Difficulty/boundary_precision_check/levy_empty_active_set_boundary
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    # Contract created but left PENDING_RESCISSION (never activated) -> 0 ACTIVE.
    create_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    sa = get_success_data(api.create_special_assessment(
        create_special_assessment_payload(resort["id"], 100000, 2026), _RM))
    resp = api.levy_special_assessment(sa["id"], levy_payload("2026-04-01T00:00:00Z"), _RM)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CONTRACTS.value)
    sa_after = get_success_data(api.get_special_assessment(sa["id"], _RM))
    assert sa_after["status"] == "DRAFT", f"assessment must stay DRAFT, got {sa_after['status']}"
    invs, _m = _list(api.list_invoices(_RM, params={"special_assessment_id": sa["id"]}))
    assert invs == [], f"no SPECIAL_ASSESSMENT invoices should be created, got {len(invs)}"


def test_levy_with_one_active_contract_succeeds(api):
    """PRD §3.7: "Levying it requires at least one `ACTIVE` contract at the resort, otherwise the
    request is rejected with `ERR_NO_ELIGIBLE_CONTRACTS`."
    PRD §3.7: "The levy call carries a `due_date` for the invoices it spawns, moves the assessment
    to `LEVIED`, and creates one `SPECIAL_ASSESSMENT` `MaintenanceFeeInvoice` in
    `DRAFT` per `ACTIVE` contract."

    Design: Difficulty/boundary_precision_check/levy_empty_active_set_boundary
    """
    # One side of the count boundary: exactly one ACTIVE contract -> levy succeeds.
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    create_active_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    sa = get_success_data(api.create_special_assessment(
        create_special_assessment_payload(resort["id"], 100000, 2026), _RM))
    levied = validate_success(api.levy_special_assessment(sa["id"], levy_payload("2026-04-01T00:00:00Z"), _RM))
    assert levied["status"] == "LEVIED", f"assessment -> LEVIED, got {levied['status']}"
    invs, _m = _list(api.list_invoices(_RM, params={"special_assessment_id": sa["id"]}))
    assert len(invs) == 1, f"one SPECIAL_ASSESSMENT invoice for the one ACTIVE contract, got {len(invs)}"


# =========================================================================== #
# Corner: validations — body validation
# =========================================================================== #
def test_payment_zero_amount_rejected(api):
    """PRD §3.7: "creates a payment against a `contract_id` for an `amount_cents` that must be
    strictly greater than 0".
    PRD §2.7: "amounts and points being strictly greater than zero where the field requires it".

    Design: Corner/validations/payment_zero_amount_rejected
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    resp = api.create_payment(create_payment_payload(contract["id"], 0), _RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_invoice_invalid_source_type_rejected(api):
    """PRD §2.7: "enum values being drawn from their legal set".
    PRD §3.7: "A `ResortManager` creates an invoice for a `contract_id` with a `source_type` of
    `ANNUAL".

    Design: Corner/validations/invoice_invalid_enum_source_type_rejected
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    resp = api.create_invoice(
        create_invoice_payload(contract["id"], 2026, "2026-02-01T00:00:00Z", source_type="MONTHLY"), _RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_mark_delinquent_on_paid_invoice_invalid_state(api):
    """PRD §2.7: "the target resource being in a legal from-state for the requested transition,
    yielding `ERR_INVALID_STATE`."
    PRD §3.7: "A `ResortManager` may mark an `ISSUED` invoice `DELINQUENT".

    Design: Corner/validations/mark_delinquent_on_paid_invoice_invalid_state
    """
    resort = create_resort(points_per_week_base=1000, annual_fee_cents_per_1000_points=20000)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    inv = create_issued_invoice(resort, contract, use_year=2026)  # 200000
    payment = get_success_data(api.create_payment(
        create_payment_payload(contract["id"], 200000, invoice_id=inv["id"]), _RM))
    get_success_data(api.clear_payment(payment["id"], _RM))  # invoice -> PAID
    resp = api.mark_invoice_delinquent(inv["id"], _RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

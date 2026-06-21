"""Entity creation, computed/default fields, immutability, referential
integrity, and state-machine lifecycle breadth.

Translates corner queue (B) instances under sections entities and
state_machines.
"""
from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    setup_active_order,
    setup_order_with_principal,
    setup_allocation_for_order,
)

CW = TEST_USERS["case_worker_headers"]
FO = TEST_USERS["finance_officer_headers"]
SUP = TEST_USERS["supervisor_headers"]


def _parties(api, cp_assist=None, ssn="0001"):
    cp_payload = {"full_name": "CP", "state_code": "CA"}
    if cp_assist is not None:
        cp_payload["assistance_status"] = cp_assist
    cp = validate_success(api.create_custodial_party(cp_payload, CW), 201)
    ncp = validate_success(api.create_noncustodial_party(
        {"full_name": "NCP", "ssn_last4": ssn}, CW), 201)
    return cp, ncp


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------
def test_create_support_order_returns_201_with_derived_fields(api):
    """PRD §3.1: "A newly created order begins with `obligation_status` of `ESTABLISHED`
    and `enforcement_status` of `NONE`. At creation the system also derives the order's
    `arrears_distribution_rule`: if the linked custodial party's `assistance_status` is
    `NEVER_ASSISTED`, the rule is `FAMILY_FIRST`"

    Design: Corner/entities/create_support_order_returns_201_with_derived_fields
    """
    cp, ncp = _parties(api, cp_assist="NEVER_ASSISTED", ssn="0001")
    order = validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 30000}, CW), 201)
    assert order["obligation_status"] == "ESTABLISHED"
    assert order["enforcement_status"] == "NONE"
    assert order["arrears_distribution_rule"] == "FAMILY_FIRST"
    assert order["version"] == 1


def test_state_first_rule_derived_for_currently_assisted_payee(api):
    """PRD §3.1: "otherwise — that is, when the family is `FORMERLY_ASSISTED` or
    `CURRENTLY_ASSISTED` — the rule is `STATE_FIRST`."

    Design: Corner/entities/state_first_rule_derived_for_currently_assisted_payee
    """
    cp, ncp = _parties(api, cp_assist="CURRENTLY_ASSISTED", ssn="0002")
    order = validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 30000, "assigned_arrears_cents": 5000}, CW), 201)
    assert order["arrears_distribution_rule"] == "STATE_FIRST"


def test_order_defaults_applied_when_optional_fields_omitted(api):
    """PRD §3.1: "optionally supplying `frequency` (which in this version supports only the
    value `MONTHLY` and defaults to it), `interest_rate_bps` (the statutory simple-interest
    annual rate in basis points, defaulting to 1000, i.e. ten percent per year), and
    `assigned_arrears_cents` (the arrears balance assigned to the state as reimbursement,
    defaulting to zero)."

    Design: Corner/entities/order_defaults_applied_when_optional_fields_omitted
    """
    cp, ncp = _parties(api, ssn="0003")
    order = validate_success(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"],
         "current_support_cents": 30000}, CW), 201)
    assert order["interest_rate_bps"] == 1000
    assert order["frequency"] == "MONTHLY"
    assert order["assigned_arrears_cents"] == 0


def test_get_support_order_nonexistent_id_returns_404(api):
    """PRD §2.6: "the first identifier that does not correspond to an existing resource causes
    the request to be rejected with `ERR_NOT_FOUND` before any later reference or business rule
    is evaluated."

    Design: Corner/entities/get_support_order_nonexistent_id_returns_404
    """
    validate_error(api.get_support_order(NON_EXISTENT_UUID, CW),
                   ApiErrorId.ERR_NOT_FOUND.value)


def test_create_support_order_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "then the structural validity of the body — required fields present and
    well-typed, cents fields non-negative integers, enum members recognized
    (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_support_order_missing_required_field_returns_invalid_request
    """
    cp, ncp = _parties(api, ssn="0004")
    validate_error(api.create_support_order(
        {"custodial_party_id": cp["id"], "noncustodial_party_id": ncp["id"]}, CW),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_ledger_entry_is_immutable_no_version_field(api):
    """PRD §2.4: "A ledger entry is an immutable, append-only event: it carries only an `id`
    and a `created_at`, and it has neither an `updated_at` nor a `version`."

    Design: Corner/entities/ledger_entry_is_immutable_no_version_field
    """
    cp, ncp, emp, order = setup_active_order(current_support_cents=30000)
    entries = validate_success(api.list_ledger_entries(
        CW, params={"support_order_id": order["id"]}))
    le_id = entries[0]["id"]
    le = validate_success(api.get_ledger_entry(le_id, CW))
    assert le["entry_type"] == "CHARGE"
    assert "version" not in le, "append-only ledger entry must not carry a version field"
    assert "updated_at" not in le, "append-only ledger entry must not carry an updated_at field"


def test_order_fk_to_nonexistent_payee_returns_not_found(api):
    """PRD §2.6: "every request that names a resource — whether by a path identifier or by a
    foreign key in the body — must resolve those references in left-to-right order, and the
    first identifier that does not correspond to an existing resource causes the request to be
    rejected with `ERR_NOT_FOUND` before any later reference or business rule is evaluated."

    Design: Corner/entities/order_fk_to_nonexistent_payee_returns_not_found
    """
    ncp = validate_success(api.create_noncustodial_party(
        {"full_name": "NCP", "ssn_last4": "0006"}, CW), 201)
    validate_error(api.create_support_order(
        {"custodial_party_id": NON_EXISTENT_UUID, "noncustodial_party_id": ncp["id"],
         "current_support_cents": 30000}, CW),
        ApiErrorId.ERR_NOT_FOUND.value)


def test_duplicate_fein_rejected(api):
    """PRD §3.1: "The `fein` must be unique across all employers; a duplicate is rejected with
    `ERR_DUPLICATE_FEIN`."

    Design: Corner/entities/duplicate_fein_rejected
    """
    validate_success(api.create_employer({"legal_name": "Emp1", "fein": "10-1010101"}, CW), 201)
    validate_error(api.create_employer({"legal_name": "Emp2", "fein": "10-1010101"}, CW),
                   ApiErrorId.ERR_DUPLICATE_FEIN.value)


# ---------------------------------------------------------------------------
# state_machines
# ---------------------------------------------------------------------------
def test_activate_already_active_order_returns_invalid_state(api):
    """PRD §3.2: "A `CaseWorker` activates an order, which is permitted only when its
    `obligation_status` is `ESTABLISHED`, `SUSPENDED`, or `MODIFIED`; attempting it from any
    other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_order_returns_invalid_state
    """
    cp, ncp, emp, order = setup_active_order(current_support_cents=30000)
    validate_error(api.activate_support_order(order["id"], CW),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_terminate_clean_order_succeeds_and_cascades_iwo_terminated(api):
    """PRD §3.2: "When termination succeeds, the order moves to the terminal `TERMINATED`,
    every income withholding order on this order that is still `ISSUED` or `ACKNOWLEDGED`
    cascades to `TERMINATED`, and the order's `version` increments."

    Design: Corner/state_machines/terminate_clean_order_succeeds_and_cascades_iwo_terminated
    """
    cp, ncp, emp, order = setup_active_order(current_support_cents=30000)
    iwo = validate_success(api.create_iwo(
        {"support_order_id": order["id"], "employer_id": emp["id"], "ordered_amount_cents": 30000,
         "effective_start_at": "2026-01-01T00:00:00Z", "effective_end_at": "2027-01-01T00:00:00Z"}, CW), 201)
    # Only the activation current-support CHARGE exists; no arrears, no enforcement.
    terminated = validate_success(api.terminate_support_order(order["id"], CW))
    assert terminated["obligation_status"] == "TERMINATED"
    iwo_after = validate_success(api.get_iwo(iwo["id"], CW))
    assert iwo_after["status"] == "TERMINATED"


def test_modification_decide_on_draft_returns_invalid_state(api):
    """PRD §3.9: "A decision to approve is permitted only while `status` is `SUBMITTED` and
    only when the linked order's `obligation_status` is `ACTIVE`, failing otherwise with
    `ERR_INVALID_STATE` or `ERR_ORDER_NOT_ACTIVE` respectively"

    Design: Corner/state_machines/modification_decide_on_draft_returns_invalid_state
    """
    cp, ncp, emp, order = setup_active_order(current_support_cents=40000)
    mod = validate_success(api.create_modification(
        {"support_order_id": order["id"], "proposed_current_support_cents": 45000,
         "coverage_start_at": "2026-07-01T00:00:00Z", "coverage_end_at": "2026-12-31T00:00:00Z"}, CW), 201)
    # Still DRAFT (not submitted).
    validate_error(api.decide_modification(mod["id"], {"decision": "APPROVE"}, SUP),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_enforcement_certify_on_withdrawn_returns_invalid_state(api):
    """PRD §3.8: "A `CaseWorker` certifies a proposed action, which is permitted only when its
    own `status` is `PROPOSED` and the linked order's `enforcement_status` is `INTERCEPT_PENDING`;
    either condition failing yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/enforcement_certify_on_withdrawn_returns_invalid_state
    """
    cp, ncp, emp, order = setup_order_with_principal(current_support_cents=50000)
    ver = order["version"]
    enf = validate_success(api.create_enforcement_action(
        {"support_order_id": order["id"], "action_type": "TAX_INTERCEPT",
         "expected_support_order_version": ver}, CW), 201)
    validate_success(api.withdraw_enforcement_action(enf["id"], CW))  # -> WITHDRAWN
    validate_error(api.certify_enforcement_action(enf["id"], CW),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_new_disbursement_initial_state_pending(api):
    """PRD §3.7: "A new disbursement is created with `status` of `PENDING`."

    Design: Corner/state_machines/new_disbursement_initial_state_pending
    """
    cp, ncp, emp, order, allocation = setup_allocation_for_order(
        current_support_cents=20000, gross_remitted_cents=20000)
    disb = validate_success(api.create_disbursement(
        {"support_order_id": order["id"], "custodial_party_id": cp["id"],
         "allocation_id": allocation["id"]}, FO), 201)
    assert disb["status"] == "PENDING"
    # FAMILY_FIRST order, slice cs=20000 -> family_amount 20000.
    assert disb["family_amount_cents"] == 20000

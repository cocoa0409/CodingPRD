"""Cross-entity state dependencies, validation precedence, temporal overlap.

Queue A (Difficulty) translations for activation/certify cross-entity gating,
the priority-pair conflicts, the DTI boundary, and the temporal-overlap
(deposit cycle-slot and session-type window) rules.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_counselor_headers, make_creditor_rep_headers, make_agency_admin_headers,
    create_agency, create_counselor, create_creditor, create_client,
    open_intake_session, complete_session, add_debt_account,
    add_and_accept_account, activate, setup_active_client, record_deposit,
    open_session_payload, activate_payload, create_debt_account_payload,
    deposit_payload, api_client,
)


def test_activate_requires_completed_intake_session(api):
    """PRD §3.5: "There must exist a `BUDGET_INTAKE` session for the client that
    has reached `COMPLETED` or `CERTIFIED`, or the request is rejected with
    `ERR_INTAKE_NOT_COMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/cross_client_activate_requires_session_and_account_states
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    open_intake_session(client["id"], counselor["id"])  # left OPEN
    add_and_accept_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    cn = make_counselor_headers(counselor["id"])
    cur = get_success_data(api.get_client(client["id"], cn))
    resp = api.activate_client(client["id"], activate_payload(cur["version"]), cn)
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_COMPLETE.value)


def test_activate_intake_not_complete_leaves_client_intake(api):
    """PRD §3.5: "There must exist a `BUDGET_INTAKE` session for the client that
    has reached `COMPLETED` or `CERTIFIED`, or the request is rejected with
    `ERR_INTAKE_NOT_COMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/cross_client_activate_requires_session_and_account_states
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    open_intake_session(client["id"], counselor["id"])
    add_and_accept_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    cn = make_counselor_headers(counselor["id"])
    cur = get_success_data(api.get_client(client["id"], cn))
    api.activate_client(client["id"], activate_payload(cur["version"]), cn)
    after = get_success_data(api.get_client(client["id"], cn))
    assert after["status"] == "INTAKE"


def test_certify_hud_requires_certified_counselor(api):
    """PRD §3.3: "For a `HUD_HOUSING` session, the conducting counselor's
    `hud_certified` flag must be true, otherwise the attempt is rejected with
    `ERR_COUNSELOR_NOT_HUD_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/cross_certify_hud_requires_counselor_certified
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"], full_name="NonHud", hud_certified=False)
    client = create_client(agency["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])
    session = get_success_data(
        api.open_session(client["id"], open_session_payload(counselor["id"], "HUD_HOUSING"), cn)
    )
    complete_session(session["id"], counselor["id"])
    resp = api.certify_session(session["id"], cn)
    validate_error(resp, ApiErrorId.ERR_COUNSELOR_NOT_HUD_CERTIFIED.value)


def test_certify_hud_not_certified_leaves_completed(api):
    """PRD §3.3: "For a `HUD_HOUSING` session, the conducting counselor's
    `hud_certified` flag must be true, otherwise the attempt is rejected with
    `ERR_COUNSELOR_NOT_HUD_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/cross_certify_hud_requires_counselor_certified
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"], full_name="NonHud", hud_certified=False)
    client = create_client(agency["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])
    session = get_success_data(
        api.open_session(client["id"], open_session_payload(counselor["id"], "HUD_HOUSING"), cn)
    )
    complete_session(session["id"], counselor["id"])
    api.certify_session(session["id"], cn)
    after = get_success_data(api.get_session(session["id"], cn))
    assert after["status"] == "COMPLETED"


def test_deposit_on_intake_client_returns_client_not_active(api):
    """PRD §2.6: "for recording a deposit and for dropping an account, the
    requirement that the owning client is `ACTIVE` (`ERR_CLIENT_NOT_ACTIVE`) is
    part of this state tier and is evaluated before any fiscal or amount
    validation."
    PRD §3.6: "The owning client must be `ACTIVE`, checked first within the state
    tier and before the amount is examined; a deposit against a non-active client
    is rejected with `ERR_CLIENT_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_state_vs_fiscal_on_deposit
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    add_and_accept_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    cn = make_counselor_headers(counselor["id"])
    resp = api.record_deposit(client["id"], deposit_payload(99999), cn)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_ACTIVE.value, expected_status=409)


def test_deposit_state_precedence_http_status(api):
    """PRD §3.6: "The owning client must be `ACTIVE`, checked first within the
    state tier and before the amount is examined; a deposit against a non-active
    client is rejected with `ERR_CLIENT_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_state_vs_fiscal_on_deposit
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    add_and_accept_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    cn = make_counselor_headers(counselor["id"])
    resp = api.record_deposit(client["id"], deposit_payload(99999), cn)
    assert resp.status_code == 409


def test_debt_account_reference_precedes_duplicate_ref(api):
    """PRD §2.6: "Resolution of body foreign-key references comes fourth
    (`ERR_REFERENCE_NOT_FOUND`)."
    PRD §3.4: "The account's `account_ref` must be unique among the client's
    accounts that are not `DROPPED`; a collision is rejected with
    `ERR_DUPLICATE_ACCOUNT_REF`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_referential_vs_constraint_on_debt_account
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="DUP",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    cn = make_counselor_headers(counselor["id"])
    resp = api.create_debt_account(
        client["id"],
        create_debt_account_payload(
            "00000000-0000-4000-8000-000000000000", account_ref="DUP",
            original_balance_cents=200000, original_apr=0.1999,
            min_payment_cents=4500, proposed_monthly_payment_cents=15000,
            requested_concession_apr=0.0699,
        ),
        cn,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, expected_status=422)


def test_debt_account_reference_precedence_http_status(api):
    """PRD §2.5: "When a body reference does not resolve to a resource within the
    acting agency, the request is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_referential_vs_constraint_on_debt_account
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="DUP",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    cn = make_counselor_headers(counselor["id"])
    resp = api.create_debt_account(
        client["id"],
        create_debt_account_payload(
            "00000000-0000-4000-8000-000000000000", account_ref="DUP",
            original_balance_cents=200000, original_apr=0.1999,
            min_payment_cents=4500, proposed_monthly_payment_cents=15000,
            requested_concession_apr=0.0699,
        ),
        cn,
    )
    assert resp.status_code == 422


def test_back_end_dti_exactly_at_floor_completes_intake(api):
    """PRD §3.3: "for a `BUDGET_INTAKE` session specifically, completion
    additionally requires that the client's `back_end_dti` is at least the
    minimum enrollment threshold of 15.0 percent, and falling short is rejected
    with `ERR_DTI_BELOW_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/boundary_dti_exactly_at_min_enroll
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(
        agency["id"], counselor["id"],
        gross_monthly_income_cents=400000, housing_payment_cents=0,
    )
    add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
        min_payment_cents=60000,
    )
    session = open_intake_session(client["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])
    client_now = get_success_data(api.get_client(client["id"], cn))
    assert client_now["back_end_dti"] == 15.0
    completed = validate_success(api.complete_session(session["id"], cn), 200)
    assert completed["status"] == "COMPLETED"


def test_back_end_dti_value_at_boundary(api):
    """PRD §3.2: "The `back_end_dti` is the sum of the housing payment plus the
    total of the pre-DMP minimum payments across the client's debt accounts that
    are still in play — those whose status is `PROPOSED`, `COUNTERED`,
    `ACCEPTED`, or `ENROLLED` — divided by gross monthly income, multiplied by
    100, taken to two decimal places by round-half-up."

    Design: Difficulty/boundary_precision_check/boundary_dti_exactly_at_min_enroll
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(
        agency["id"], counselor["id"],
        gross_monthly_income_cents=400000, housing_payment_cents=0,
    )
    add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
        min_payment_cents=60000,
    )
    cn = make_counselor_headers(counselor["id"])
    client_now = get_success_data(api.get_client(client["id"], cn))
    assert client_now["back_end_dti"] == 15.0


def test_duplicate_cycle_deposit_rejected(api):
    """PRD §3.6: "At most one deposit may exist per client per cycle: a second
    deposit at the same `current_cycle_index` for the same client is rejected
    with `ERR_DUPLICATE_CYCLE_DEPOSIT`."

    Design: Difficulty/resource_temporal_overlap/overlap_deposit_same_cycle_slot
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 300000,
             "proposed_monthly_payment_cents": 30000},
        ],
    )
    record_deposit(client["id"], counselor["id"], 33500)
    cn = make_counselor_headers(counselor["id"])
    resp = api.record_deposit(client["id"], deposit_payload(33500), cn)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CYCLE_DEPOSIT.value, expected_status=409)


def test_duplicate_cycle_deposit_http_status(api):
    """PRD §3.6: "At most one deposit may exist per client per cycle: a second
    deposit at the same `current_cycle_index` for the same client is rejected
    with `ERR_DUPLICATE_CYCLE_DEPOSIT`."

    Design: Difficulty/resource_temporal_overlap/overlap_deposit_same_cycle_slot
    """
    agency, counselor, creditor, client, accts = setup_active_client(
        monthly_fee_cents=3500,
        accounts=[
            {"account_ref": "A", "original_balance_cents": 300000,
             "proposed_monthly_payment_cents": 30000},
        ],
    )
    record_deposit(client["id"], counselor["id"], 33500)
    cn = make_counselor_headers(counselor["id"])
    resp = api.record_deposit(client["id"], deposit_payload(33500), cn)
    assert resp.status_code == 409


def test_second_inflight_session_same_type_rejected(api):
    """PRD §3.3: "A client may not open a second session of the same
    `session_type` while an existing session of that type still occupies its
    in-flight window — that is, while one is `OPEN` or `NEEDS_REVISION`. The
    window is half-open and is freed only when the prior session reaches
    `COMPLETED` or `CERTIFIED`; opening a same-type session while the window is
    occupied is rejected with `ERR_SESSION_TYPE_IN_FLIGHT`."

    Design: Difficulty/resource_temporal_overlap/overlap_session_type_inflight_window
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])
    validate_success(
        api.open_session(client["id"], open_session_payload(counselor["id"], "BANKRUPTCY_PREFILING"), cn), 201
    )
    resp = api.open_session(
        client["id"], open_session_payload(counselor["id"], "BANKRUPTCY_PREFILING"), cn
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_TYPE_IN_FLIGHT.value, expected_status=409)


def test_second_inflight_session_http_status(api):
    """PRD §3.3: "opening a same-type session while the window is occupied is
    rejected with `ERR_SESSION_TYPE_IN_FLIGHT`."

    Design: Difficulty/resource_temporal_overlap/overlap_session_type_inflight_window
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])
    validate_success(
        api.open_session(client["id"], open_session_payload(counselor["id"], "BANKRUPTCY_PREFILING"), cn), 201
    )
    resp = api.open_session(
        client["id"], open_session_payload(counselor["id"], "BANKRUPTCY_PREFILING"), cn
    )
    assert resp.status_code == 409

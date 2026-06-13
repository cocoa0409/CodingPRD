"""Marriage record lifecycle, amendments (cycle / fee / resubmit limit / seal lock),
apostilles, and fee-waiver grant denial. Difficulty (queue A) + corner (queue B)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    create_amendment_payload,
    create_certified_copy_payload,
    create_apostille_payload,
    make_applicant_headers,
    setup_registered_record,
    setup_submitted_amendment,
    setup_issued_copy_with_apostille,
    request_fee_waiver,
    seal_record,
    find_ledger_entries,
    CLERK_1,
    REGISTRAR_1,
    REGISTRAR_2,
    WAIVER_OFFICER_1,
)


# ===========================================================================
# Amendment cycle SUBMITTED -> RETURNED_FOR_INFO -> SUBMITTED (queue A)
# ===========================================================================
def test_amendment_returned_then_resubmitted_increments_count(api):
    """PRD §3.7: "The applicant may then resubmit, advancing it from
    RETURNED_FOR_INFO back to SUBMITTED and increasing resubmit_count by one".

    Design: Difficulty/non_linear_state_machine/amendment_cycle_submitted_returned_resubmit_loop
    """
    base = setup_submitted_amendment(amendment_type="CLERICAL")
    am_id = base["amendment"]["id"]
    applicant_headers = make_applicant_headers(base["applicant_a"]["id"])
    validate_success(api.decide_amendment(am_id, {"decision": "RETURN"}, REGISTRAR_1))
    data = validate_success(api.resubmit_amendment(am_id, applicant_headers))
    assert data["status"] == "SUBMITTED"
    assert data["resubmit_count"] == 1


def test_amendment_two_cycles_reaches_resubmit_count_two(api):
    """PRD §3.7: "The resubmit_count is the number of times the amendment has cycled
    back from RETURNED_FOR_INFO to SUBMITTED."

    Design: Difficulty/non_linear_state_machine/amendment_cycle_submitted_returned_resubmit_loop
    """
    base = setup_submitted_amendment(amendment_type="CLERICAL")
    am_id = base["amendment"]["id"]
    applicant_headers = make_applicant_headers(base["applicant_a"]["id"])
    validate_success(api.decide_amendment(am_id, {"decision": "RETURN"}, REGISTRAR_1))
    validate_success(api.resubmit_amendment(am_id, applicant_headers))
    validate_success(api.decide_amendment(am_id, {"decision": "RETURN"}, REGISTRAR_1))
    data = validate_success(api.resubmit_amendment(am_id, applicant_headers))
    assert data["resubmit_count"] == 2
    assert data["status"] == "SUBMITTED"


# ===========================================================================
# Amendment fee mode (b): round-per-component-then-sum (queue A)
# ===========================================================================
def test_substantive_amendment_after_one_resubmit_fee_6250(api):
    """PRD §3.7: "an expedite component is computed as the base multiplied by 15
    percent and rounded half-up to whole cents, and a penalty component is computed
    as the base multiplied by 10 percent multiplied by the resubmit_count and rounded
    half-up to whole cents. The final fee is the base plus the expedite component plus
    the penalty component."

    Design: Difficulty/combinatorial_formula/amendment_fee_round_per_component_then_sum_mode_b
    """
    base = setup_submitted_amendment(amendment_type="SUBSTANTIVE", new_value="Gustavo Ray")
    am_id = base["amendment"]["id"]
    applicant_headers = make_applicant_headers(base["applicant_a"]["id"])
    # One resubmit cycle so resubmit_count == 1.
    validate_success(api.decide_amendment(am_id, {"decision": "RETURN"}, REGISTRAR_1))
    validate_success(api.resubmit_amendment(am_id, applicant_headers))
    # Apply by a registrar distinct from the approving clerk (clerk-1) for SUBSTANTIVE.
    data = validate_success(api.decide_amendment(am_id, {"decision": "APPLY"}, REGISTRAR_2))
    assert data["status"] == "APPLIED"
    assert data["resubmit_count"] == 1
    # base 5000 + round(5000*0.15)=750 + round(5000*0.10*1)=500 = 6250
    ledger, _ = validate_paginated(api.list_application_ledger(base["application"]["id"], CLERK_1))
    rows = find_ledger_entries(ledger, kind="CHARGE", source_entity="AMENDMENT",
                               source_entity_id=am_id, amount_cents=6250)
    assert len(rows) == 1, f"expected a 6250-cent AMENDMENT CHARGE, ledger={ledger}"


def test_substantive_amendment_apply_cascades_record_to_amended(api):
    """PRD §3.7: "On a successful application the amendment's status becomes APPLIED ...
    the record cascades to AMENDED, and amendment_count is recomputed."

    Design: Difficulty/combinatorial_formula/amendment_fee_round_per_component_then_sum_mode_b
    """
    base = setup_submitted_amendment(amendment_type="SUBSTANTIVE", new_value="Gustavo Ray")
    am_id = base["amendment"]["id"]
    applicant_headers = make_applicant_headers(base["applicant_a"]["id"])
    validate_success(api.decide_amendment(am_id, {"decision": "RETURN"}, REGISTRAR_1))
    validate_success(api.resubmit_amendment(am_id, applicant_headers))
    validate_success(api.decide_amendment(am_id, {"decision": "APPLY"}, REGISTRAR_2))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    assert rec["status"] == "AMENDED"
    assert rec["amendment_count"] == 1


# ===========================================================================
# CLERICAL base amendment fee, no resubmit (queue B: calculations)
# ===========================================================================
def test_clerical_amendment_base_fee_no_resubmit_2300(api):
    """PRD §3.7: "The base fee is 2000 cents for a CLERICAL amendment and 5000 cents
    for a SUBSTANTIVE one. From that base, an expedite component is computed as the
    base multiplied by 15 percent and rounded half-up to whole cents".

    Design: Corner/calculations/amendment_clerical_base_fee_no_resubmit
    """
    base = setup_submitted_amendment(amendment_type="CLERICAL", new_value="Cl Alpha")
    am_id = base["amendment"]["id"]
    # CLERICAL carries no segregation requirement; apply directly.
    data = validate_success(api.decide_amendment(am_id, {"decision": "APPLY"}, REGISTRAR_2))
    assert data["status"] == "APPLIED"
    # base 2000 + round(2000*0.15)=300 + 0 = 2300
    ledger, _ = validate_paginated(api.list_application_ledger(base["application"]["id"], CLERK_1))
    rows = find_ledger_entries(ledger, kind="CHARGE", source_entity="AMENDMENT",
                               source_entity_id=am_id, amount_cents=2300)
    assert len(rows) == 1, f"expected a 2300-cent AMENDMENT CHARGE, ledger={ledger}"


# ===========================================================================
# Seal terminal lockdown blocks amendment APPLY (queue B: state_machines)
# ===========================================================================
def test_amendment_apply_on_sealed_record_blocked(api):
    """PRD §3.7: "Applying an amendment advances it from SUBMITTED to APPLIED and is
    gated by two preconditions: the record must not be SEALED, or the application is
    rejected with ERR_RECORD_SEALED".

    Design: Corner/state_machines/seal_record_then_amend_blocked_terminal
    """
    base = setup_registered_record()
    amendment = get_success_data(api.create_amendment(
        create_amendment_payload(base["record"]["id"], "CLERICAL", new_value="Tl Alpha"),
        make_applicant_headers(base["applicant_a"]["id"])))
    seal_record(base["record"]["id"], REGISTRAR_1)
    resp = api.decide_amendment(amendment["id"], {"decision": "APPLY"}, REGISTRAR_2)
    validate_error(resp, ApiErrorId.ERR_RECORD_SEALED.value, expected_status=409)
    assert get_success_data(api.get_amendment(amendment["id"], CLERK_1))["status"] == "SUBMITTED"


# ===========================================================================
# Resubmit limit reached (queue B: state_machines)
# ===========================================================================
def test_amendment_resubmit_limit_reached(api):
    """PRD §3.7: "resubmission is allowed only while resubmit_count is below the limit
    of 2, and a resubmission attempt at or beyond that limit is rejected with
    ERR_RESUBMIT_LIMIT_REACHED."

    Design: Corner/state_machines/amendment_resubmit_limit_reached
    """
    base = setup_submitted_amendment(amendment_type="CLERICAL", new_value="Rl Alpha")
    am_id = base["amendment"]["id"]
    applicant_headers = make_applicant_headers(base["applicant_a"]["id"])
    # Cycle twice -> resubmit_count == 2, then RETURN a third time.
    for _ in range(2):
        validate_success(api.decide_amendment(am_id, {"decision": "RETURN"}, REGISTRAR_1))
        validate_success(api.resubmit_amendment(am_id, applicant_headers))
    validate_success(api.decide_amendment(am_id, {"decision": "RETURN"}, REGISTRAR_1))
    resp = api.resubmit_amendment(am_id, applicant_headers)
    validate_error(resp, ApiErrorId.ERR_RESUBMIT_LIMIT_REACHED.value, expected_status=409)
    after = get_success_data(api.get_amendment(am_id, CLERK_1))
    assert after["resubmit_count"] == 2
    assert after["status"] == "RETURNED_FOR_INFO"


# ===========================================================================
# Seal blocked by pending copy (queue B: validations)
# ===========================================================================
def test_seal_with_pending_copy_blocked(api):
    """PRD §3.5: "in both cases is blocked if any certified-copy request for the
    record is still PENDING, in which case the seal is rejected with
    ERR_RECORD_HAS_PENDING_COPIES."

    Design: Corner/validations/seal_with_pending_copy_blocked
    """
    base = setup_registered_record()
    get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 1), CLERK_1))
    resp = api.seal_record(base["record"]["id"], REGISTRAR_1)
    validate_error(resp, ApiErrorId.ERR_RECORD_HAS_PENDING_COPIES.value, expected_status=409)
    assert get_success_data(api.get_record(base["record"]["id"], CLERK_1))["status"] == "REGISTERED"


# ===========================================================================
# Apostille authenticate charges fixed fee (queue B: calculations)
# ===========================================================================
def test_apostille_authenticate_charges_fixed_fee(api):
    """PRD §3.7: "On authentication the apostille's fee_cents is set to the flat
    apostille fee of 4000 cents and a CHARGE ledger row for that amount is appended
    with source_entity APOSTILLE."

    Design: Corner/calculations/apostille_authenticate_charges_fixed_fee
    """
    base = setup_issued_copy_with_apostille(destination_country="France")
    data = validate_success(api.decide_apostille(
        base["apostille"]["id"], {"decision": "AUTHENTICATE"}, REGISTRAR_1))
    assert data["status"] == "AUTHENTICATED"
    assert data["fee_cents"] == 4000


# ===========================================================================
# Apostille on un-issued copy (queue B: errors)
# ===========================================================================
def test_apostille_on_unissued_copy_rejected(api):
    """PRD §3.7: "Authenticating advances it from REQUESTED to AUTHENTICATED and is
    gated by two preconditions: the referenced certified copy must be in ISSUED, or
    the request is rejected with ERR_COPY_NOT_ISSUED".

    Design: Corner/errors/apostille_on_unissued_copy_rejected
    """
    base = setup_registered_record()
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 1), CLERK_1))  # PENDING
    apostille = get_success_data(api.create_apostille(
        create_apostille_payload(copy["id"], "Spain"),
        make_applicant_headers(base["applicant_a"]["id"])))
    resp = api.decide_apostille(apostille["id"], {"decision": "AUTHENTICATE"}, REGISTRAR_1)
    validate_error(resp, ApiErrorId.ERR_COPY_NOT_ISSUED.value, expected_status=409)
    assert get_success_data(api.get_apostille(apostille["id"], CLERK_1))["status"] == "REQUESTED"


# ===========================================================================
# Fee waiver income above threshold (queue B: validations)
# ===========================================================================
def test_income_above_threshold_waiver_denied(api):
    """PRD §3.7: "A grant is permitted only when declared_monthly_income_cents is at
    or below that threshold; if income exceeds the threshold the grant is rejected
    with ERR_INCOME_ABOVE_THRESHOLD."

    Design: Corner/validations/income_above_threshold_waiver_denied
    """
    applicant = get_success_data(api.create_applicant(
        {"full_name": "It A", "date_of_birth": "1990-01-01"}, CLERK_1))
    waiver = request_fee_waiver(applicant["id"], 130001, household_size=1)  # threshold 130000
    resp = api.decide_fee_waiver(waiver["id"], {"decision": "GRANT"}, WAIVER_OFFICER_1)
    validate_error(resp, ApiErrorId.ERR_INCOME_ABOVE_THRESHOLD.value, expected_status=409)
    assert get_success_data(api.get_fee_waiver(waiver["id"], CLERK_1))["status"] == "REQUESTED"

"""Certified-copy access, tiered pricing, waiver absorption, refunds, and the
conserved-quantity invariants. Difficulty (queue A) + corner (queue B)."""
from test_helpers import (
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    create_certified_copy_payload,
    setup_registered_record,
    request_fee_waiver,
    grant_fee_waiver,
    issue_copy,
    seal_record,
    collected_balance,
    CLERK_1,
    CLERK_2,
    REGISTRAR_1,
)


# ===========================================================================
# Dual variant: GOVERNMENT exemption vs PUBLIC (queue A: dual_variant_calc)
# ===========================================================================
def test_public_requester_5_copies_fee_6300(api):
    """PRD §3.6: "the gross is 1500 cents times the lesser of the requested count and
    3, plus 900 cents times the count of copies in excess of 3 (zero if 3 or fewer are
    requested)."

    Design: Difficulty/dual_variant_calc/certified_copy_fee_government_exempt_vs_public
    """
    base = setup_registered_record()
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 5), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    data = issue_copy(copy["id"], expected_record_version=rec["version"])
    assert data["status"] == "ISSUED"
    assert data["fee_cents"] == 6300  # 1500*3 + 900*2


def test_government_requester_5_copies_fee_zero(api):
    """PRD §3.6: "the government exemption is applied after the surcharge and before
    any waiver: if the requester_kind is GOVERNMENT, the gross is set to zero."

    Design: Difficulty/dual_variant_calc/certified_copy_fee_government_exempt_vs_public
    """
    base = setup_registered_record()
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "GOVERNMENT", 5), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    data = issue_copy(copy["id"], expected_record_version=rec["version"])
    assert data["status"] == "ISSUED"
    assert data["fee_cents"] == 0


# ===========================================================================
# Dual variant: waiver full vs partial cap (queue A: dual_variant_calc)
# ===========================================================================
def test_waiver_deep_need_grants_full_cap_6000(api):
    """PRD §3.7: "If that ratio is at least 0.50 the cap is the full waiver cap of
    6000 cents; otherwise it is the partial waiver cap of 3000 cents."

    Design: Difficulty/dual_variant_calc/waiver_cap_full_vs_partial_need
    """
    applicant = get_success_data(api.create_applicant(
        {"full_name": "Cara Vance", "date_of_birth": "1992-02-02"}, CLERK_1))
    # income 50000, household 1, threshold 130000 -> ratio 0.6154 >= 0.50 -> full cap.
    waiver = request_fee_waiver(applicant["id"], 50000, household_size=1)
    data = grant_fee_waiver(waiver["id"])
    assert data["status"] == "GRANTED"
    assert data["max_waivable_cents"] == 6000


def test_waiver_shallow_need_grants_partial_cap_3000(api):
    """PRD §3.7: "If that ratio is at least 0.50 the cap is the full waiver cap of
    6000 cents; otherwise it is the partial waiver cap of 3000 cents."

    Design: Difficulty/dual_variant_calc/waiver_cap_full_vs_partial_need
    """
    applicant = get_success_data(api.create_applicant(
        {"full_name": "Cara Vance", "date_of_birth": "1992-02-02"}, CLERK_1))
    # income 100000, household 1, threshold 130000 -> ratio 0.2308 < 0.50 -> partial cap.
    waiver = request_fee_waiver(applicant["id"], 100000, household_size=1)
    data = grant_fee_waiver(waiver["id"])
    assert data["status"] == "GRANTED"
    assert data["max_waivable_cents"] == 3000


# ===========================================================================
# Combinatorial mode (a): tier + surcharge + waiver (queue A)
# ===========================================================================
def test_copy_fee_tier_plus_waiver_absorption_mode_a(api):
    """PRD §3.6: "the absorbed amount is the lesser of the remaining gross and the
    waiver's remaining capacity (its max_waivable_cents minus its consumed_cents), and
    the final fee_cents is the gross minus the absorbed amount."

    Design: Difficulty/combinatorial_formula/certified_copy_fee_tier_surcharge_waiver_mode_a
    """
    base = setup_registered_record()  # non-confidential record
    # Granted waiver with partial cap 3000 (income 100000, household 1).
    waiver = request_fee_waiver(base["applicant_a"]["id"], 100000, household_size=1)
    waiver = grant_fee_waiver(waiver["id"])
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 5,
                                       fee_waiver_id=waiver["id"]), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    wv = get_success_data(api.get_fee_waiver(waiver["id"], CLERK_1))
    data = issue_copy(copy["id"], expected_record_version=rec["version"],
                      expected_waiver_version=wv["version"])
    # gross 6300, absorbed min(6300, 3000)=3000, fee 3300.
    assert data["fee_cents"] == 3300


def test_copy_fee_waiver_consumes_cap_and_marks_consumed(api):
    """PRD §3.6: "if consumed_cents has reached or exceeded the waiver's
    max_waivable_cents the waiver moves from GRANTED to CONSUMED."

    Design: Difficulty/combinatorial_formula/certified_copy_fee_tier_surcharge_waiver_mode_a
    """
    base = setup_registered_record()
    waiver = request_fee_waiver(base["applicant_a"]["id"], 100000, household_size=1)
    waiver = grant_fee_waiver(waiver["id"])
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 5,
                                       fee_waiver_id=waiver["id"]), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    wv = get_success_data(api.get_fee_waiver(waiver["id"], CLERK_1))
    issue_copy(copy["id"], expected_record_version=rec["version"],
               expected_waiver_version=wv["version"])
    after = get_success_data(api.get_fee_waiver(waiver["id"], CLERK_1))
    assert after["consumed_cents"] == 3000
    assert after["status"] == "CONSUMED"


# ===========================================================================
# Compensating invariant: collected balance (queue A)
# ===========================================================================
def test_issue_then_refund_leaves_collected_balance_unchanged(api):
    """PRD §2.9: "The office's collected balance is therefore the sum of amount_cents
    across all CHARGE entries minus the sum of amount_cents across all REFUND entries,
    with WAIVE entries excluded entirely from that figure."

    Design: Difficulty/compensating_invariant/copy_issue_then_refund_leaves_collected_balance_unchanged
    """
    base = setup_registered_record()
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 5), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    issued = issue_copy(copy["id"], expected_record_version=rec["version"])
    assert issued["fee_cents"] == 6300
    refunded = get_success_data(api.refund_certified_copy(copy["id"], CLERK_2))
    assert refunded["status"] == "REFUNDED"
    ledger, _ = validate_paginated(api.list_application_ledger(base["application"]["id"], CLERK_1))
    # license 9000 + copy 6300 - refund 6300 == 9000 (the pre-issue collected balance).
    assert collected_balance(ledger) == 9000


def test_issue_then_refund_appends_offsetting_charge_and_refund(api):
    """PRD §3.6: "A refund appends a REFUND ledger row for the request's fee_cents
    with source_entity CERTIFIED_COPY".

    Design: Difficulty/compensating_invariant/copy_issue_then_refund_leaves_collected_balance_unchanged
    """
    base = setup_registered_record()
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 5), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    issue_copy(copy["id"], expected_record_version=rec["version"])
    get_success_data(api.refund_certified_copy(copy["id"], CLERK_2))
    ledger, _ = validate_paginated(api.list_application_ledger(base["application"]["id"], CLERK_1))
    charges = [r for r in ledger if r["kind"] == "CHARGE" and r["source_entity"] == "CERTIFIED_COPY"]
    refunds = [r for r in ledger if r["kind"] == "REFUND" and r["source_entity"] == "CERTIFIED_COPY"]
    assert any(r["amount_cents"] == 6300 for r in charges)
    assert any(r["amount_cents"] == 6300 for r in refunds)


# ===========================================================================
# Compensating invariant: certified_copies_issued count (queue A)
# ===========================================================================
def test_issue_increments_copies_issued_count(api):
    """PRD §3.6: "a CHARGE ledger row for that fee_cents is appended with source_entity
    CERTIFIED_COPY, and the record's certified_copies_issued is recomputed."

    Design: Difficulty/compensating_invariant/copy_issue_then_refund_leaves_copies_issued_count_unchanged
    """
    base = setup_registered_record()
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 2), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    issue_copy(copy["id"], expected_record_version=rec["version"])
    after_issue = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    assert after_issue["certified_copies_issued"] == 1


def test_refund_restores_copies_issued_count_to_zero(api):
    """PRD §3.6: "A refund appends a REFUND ledger row for the request's fee_cents with
    source_entity CERTIFIED_COPY, and recomputes the record's certified_copies_issued."

    Design: Difficulty/compensating_invariant/copy_issue_then_refund_leaves_copies_issued_count_unchanged
    """
    base = setup_registered_record()
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 2), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    issue_copy(copy["id"], expected_record_version=rec["version"])
    get_success_data(api.refund_certified_copy(copy["id"], CLERK_2))
    after_refund = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    assert after_refund["certified_copies_issued"] == 0


# ===========================================================================
# Cross-entity dependency: GOVERNMENT may copy a SEALED record (queue A)
# ===========================================================================
def test_government_can_issue_copy_on_sealed_record(api):
    """PRD §3.6: "A sealed record may be copied only for a GOVERNMENT requester; any
    other requester against a SEALED record is rejected with ERR_RECORD_SEALED."

    Design: Difficulty/cross_entity_state_dependency/copy_issue_blocked_when_record_sealed
    """
    base = setup_registered_record()
    # Seal first (no PENDING copies blocks the seal per PRD 3.5), then a
    # GOVERNMENT requester — the one party permitted against a SEALED record —
    # requests and is issued a copy.
    seal_record(base["record"]["id"], REGISTRAR_1)
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "GOVERNMENT", 1), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    data = issue_copy(copy["id"], expected_record_version=rec["version"])
    assert data["status"] == "ISSUED"
    assert data["fee_cents"] == 0  # GOVERNMENT exemption


def test_sealed_record_is_confidential_and_government_copy_succeeds(api):
    """PRD §3.5: "A successful seal moves the record to SEALED and forces its
    is_confidential to true."

    Design: Difficulty/cross_entity_state_dependency/copy_issue_blocked_when_record_sealed
    """
    base = setup_registered_record()
    # Seal first (no PENDING copies blocks the seal per PRD 3.5), then a
    # GOVERNMENT requester requests and is issued a copy on the sealed record.
    seal_record(base["record"]["id"], REGISTRAR_1)
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    assert rec["status"] == "SEALED"
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "GOVERNMENT", 1), CLERK_1))
    issue_copy(copy["id"], expected_record_version=rec["version"])
    assert get_success_data(api.get_certified_copy(copy["id"], CLERK_1))["status"] == "ISSUED"


# ===========================================================================
# Tier boundary: exactly 3 copies (queue B: calculations)
# ===========================================================================
def test_certified_copy_first_tier_only_three_copies(api):
    """PRD §3.6: "the first 3 copies are priced at 1500 cents each, and every copy
    beyond the third is priced at 900 cents each".

    Design: Corner/calculations/certified_copy_first_tier_only_three_copies
    """
    base = setup_registered_record()
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PUBLIC", 3), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    data = issue_copy(copy["id"], expected_record_version=rec["version"])
    assert data["fee_cents"] == 4500  # 1500*3 + 900*0


# ===========================================================================
# Confidential surcharge applied once (queue B: calculations)
# ===========================================================================
def test_certified_copy_confidential_surcharge_applied(api):
    """PRD §3.6: "if the record is confidential, a flat confidential surcharge of 2500
    cents is added once to the gross."

    Design: Corner/calculations/certified_copy_confidential_surcharge_applied
    """
    base = setup_registered_record(is_confidential=True)  # confidential record
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PARTY", 2), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    data = issue_copy(copy["id"], expected_record_version=rec["version"])
    assert data["fee_cents"] == 5500  # 1500*2 + 2500 surcharge


# ===========================================================================
# Waiver ratio exactly 0.50 -> full cap (queue B: calculations)
# ===========================================================================
def test_waiver_ratio_exactly_half_grants_full_cap(api):
    """PRD §3.7: "If that ratio is at least 0.50 the cap is the full waiver cap of
    6000 cents".

    Design: Corner/calculations/waiver_ratio_exactly_half_grants_full_cap
    """
    applicant = get_success_data(api.create_applicant(
        {"full_name": "Wr A", "date_of_birth": "1990-01-01"}, CLERK_1))
    # income 65000, household 1, threshold 130000 -> ratio exactly 0.50 -> full cap.
    waiver = request_fee_waiver(applicant["id"], 65000, household_size=1)
    data = grant_fee_waiver(waiver["id"])
    assert data["max_waivable_cents"] == 6000
    assert data["status"] == "GRANTED"


# ===========================================================================
# Waiver not granted applied to copy (queue B: validations)
# ===========================================================================
def test_waiver_not_granted_applied_to_copy_rejected(api):
    """PRD §3.6: "If a fee_waiver_id is present, the referenced waiver must be in
    GRANTED and its applicant_id must be a party of the record, or the issuance is
    rejected with ERR_WAIVER_NOT_GRANTED".

    Design: Corner/validations/waiver_not_granted_applied_to_copy
    """
    base = setup_registered_record()
    # Waiver requested but NOT granted.
    waiver = request_fee_waiver(base["applicant_a"]["id"], 50000, household_size=1)
    copy = get_success_data(api.create_certified_copy(
        create_certified_copy_payload(base["record"]["id"], "PARTY", 1,
                                       fee_waiver_id=waiver["id"]), CLERK_1))
    rec = get_success_data(api.get_record(base["record"]["id"], CLERK_1))
    wv = get_success_data(api.get_fee_waiver(waiver["id"], CLERK_1))
    resp = api.decide_certified_copy(copy["id"], {
        "decision": "ISSUE",
        "expected_record_version": rec["version"],
        "expected_waiver_version": wv["version"],
    }, CLERK_2)
    validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_GRANTED.value, expected_status=409)
    assert get_success_data(api.get_certified_copy(copy["id"], CLERK_1))["status"] == "PENDING"


# ===========================================================================
# Bad enum / out-of-range input (queue B: entities)
# ===========================================================================
def test_create_certified_copy_bad_enum_requester_kind_rejected(api):
    """PRD §2.10: "required fields present, enums valid, and integers in range ...,
    failing which the request is rejected with ERR_INVALID_REQUEST".

    Design: Corner/entities/create_certified_copy_bad_enum_requester_kind_rejected
    """
    base = setup_registered_record()
    resp = api.create_certified_copy(
        {"record_id": base["record"]["id"], "requester_kind": "STRANGER", "copies_requested": 1},
        CLERK_1)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_create_certified_copy_copies_zero_rejected(api):
    """PRD §3.6: "copies_requested, the count of copies wanted, which must be at
    least 1."

    Design: Corner/entities/create_certified_copy_copies_zero_rejected
    """
    base = setup_registered_record()
    resp = api.create_certified_copy(
        {"record_id": base["record"]["id"], "requester_kind": "PUBLIC", "copies_requested": 0},
        CLERK_1)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

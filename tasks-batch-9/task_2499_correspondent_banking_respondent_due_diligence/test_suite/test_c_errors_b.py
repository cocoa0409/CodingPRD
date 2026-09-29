"""Corner queue - section errors, part B: payment screening refusals."""
from test_helpers import (
    ApiErrorId,
    OFFICER_ID,
    add_nested,
    assert_instant_equals,
    decide_payment,
    new_jurisdiction,
    read_payment,
    read_respondent,
    sanctioned_jurisdiction,
    setup_approved_respondent,
    submit_payment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, OFFICER, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _approved():
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    return bundle["respondent"]["id"]


def test_rescreening_a_rejected_instruction_is_a_child_state_error(api):
    """Rejection is terminal, so a second decision must not overwrite the audit trail the first
    decision wrote.

    Design: Corner/errors/rescreening_a_rejected_instruction_is_a_child_state_error
    """
    rid = _approved()
    validate_success(api.amend_respondent(rid, {"payment_posture": "SCREEN_ONLY"}, RM))
    assert read_respondent(rid)["payment_posture"] == "SCREEN_ONLY"

    instruction = submit_payment(
        rid, "DE", "DE", amount_usd=1000.00, purpose_code="INTERBANK_PLACEMENT"
    )
    assert instruction["screening_state"] == "RECEIVED"
    rejected = decide_payment(instruction["id"], "REJECT", "RESPONDENT_RESTRICTED")
    assert rejected["screening_state"] == "REJECTED"

    response = api.decide_screening(
        instruction["id"], {"action": "RESCREEN", "decision_reason": "CLEARED_AFTER_REVIEW"},
        OFFICER,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_PAYMENT_STATE, expected_status=409)

    stored = read_payment(instruction["id"])
    assert stored["screening_state"] == "REJECTED"
    assert stored["decision_reason"] == "RESPONDENT_RESTRICTED"
    assert stored["decided_by_user_id"] == OFFICER_ID
    assert_instant_equals(stored["decided_at"], "2026-08-01T00:00:00Z")


def test_releasing_a_sanctions_blocked_instruction_is_forbidden(api):
    """The posture is deliberately left open so the sanctions rule cannot be masked by the
    posture rule, and rejection is shown to be the one permitted exit.

    Design: Corner/errors/releasing_a_sanctions_blocked_instruction_is_forbidden
    """
    rid = _approved()
    assert read_respondent(rid)["payment_posture"] == "OPEN"
    sanctioned_jurisdiction(
        jurisdiction_code="IR", name="Iran", basel_aml_index=8.0, corridor_risk_weight=2.0
    )

    instruction = submit_payment(
        rid, "DE", "IR", amount_usd=1000.00, purpose_code="TRADE_SETTLEMENT"
    )
    assert instruction["screening_state"] == "BLOCKED_SANCTIONS"
    assert instruction["hold_reason"] is None

    refused = api.decide_screening(
        instruction["id"], {"action": "RELEASE", "decision_reason": "CLEARED_AFTER_REVIEW"},
        OFFICER,
    )
    validate_error(
        refused, ApiErrorId.ERR_SANCTIONED_PAYMENT_RELEASE_FORBIDDEN, expected_status=403
    )
    assert read_payment(instruction["id"])["screening_state"] == "BLOCKED_SANCTIONS"

    rejected = decide_payment(instruction["id"], "REJECT", "SANCTIONS_MATCH")
    assert rejected["screening_state"] == "REJECTED"
    assert rejected["decision_reason"] == "SANCTIONS_MATCH"


def test_nested_party_payment_without_a_usable_disclosure_reference(api):
    """An absent reference and a reference to a row we found ourselves fail the same rule, and
    both are refused before any screening state can be written.

    Design: Corner/errors/nested_party_payment_without_a_usable_disclosure_reference
    """
    rid = _approved()
    row = add_nested(
        rid, "DE", ANALYST, downstream_institution_name="Hinterbank GmbH",
        discovery_source="TRANSACTION_MONITORING",
    )
    assert row["state"] == "UNDISCLOSED_DETECTED"

    without_reference = api.create_payment_instruction(
        rid,
        {"ordering_jurisdiction_code": "DE", "beneficiary_jurisdiction_code": "DE",
         "amount_usd": 1000.00, "purpose_code": "REMITTANCE", "involves_nested_party": True},
        RM,
    )
    validate_error(
        without_reference, ApiErrorId.ERR_NESTED_DISCLOSURE_MISSING, expected_status=422
    )

    undisclosed_reference = api.create_payment_instruction(
        rid,
        {"ordering_jurisdiction_code": "DE", "beneficiary_jurisdiction_code": "DE",
         "amount_usd": 1000.00, "purpose_code": "REMITTANCE", "involves_nested_party": True,
         "nested_relationship_id": row["id"]},
        RM,
    )
    validate_error(
        undisclosed_reference, ApiErrorId.ERR_NESTED_DISCLOSURE_MISSING, expected_status=422
    )

    _rows, meta = validate_paginated(
        api.list_payment_instructions(RM, params={"respondent_bank_id": rid})
    )
    assert meta["total_count"] == 0

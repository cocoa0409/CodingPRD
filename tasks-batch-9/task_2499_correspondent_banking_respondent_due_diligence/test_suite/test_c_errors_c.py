"""Corner queue - section errors, part C: the nested ladder and a revoked ownership gate."""
from test_helpers import (
    CONTROL_DOMAIN_ORDER,
    ApiErrorId,
    add_nested,
    add_verified_owner,
    all_assessed_overlays,
    assessed_questionnaire,
    licensed_respondent,
    log_media,
    make_respondent_headers,
    new_jurisdiction,
    read_media,
    read_nested,
    read_respondent,
    sanctioned_jurisdiction,
    score_respondent,
    triage_media,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, COMMITTEE


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _licensed(**overrides):
    payload = {
        "legal_name": "Nordbank AG", "swift_bic": "NORDDEFF",
        "expected_monthly_volume_usd": 500000.00, "expected_monthly_count": 100,
    }
    payload.update(overrides)
    return licensed_respondent("DE", **payload)


def test_nested_ladder_returns_the_paired_error_of_the_matching_prohibition_reason(api):
    """A respondent declaring its own network is the one caller whose unlawful configuration is
    rejected rather than stored, so three ladder rungs become three distinct errors, and the
    lawful fourth declaration proves the ladder can also yield nothing.

    Design: Corner/errors/nested_ladder_returns_the_paired_error_of_the_matching_prohibition_reason
    """
    _de()
    sanctioned_jurisdiction(
        jurisdiction_code="IR", name="Iran", basel_aml_index=8.0, corridor_risk_weight=2.0
    )
    new_jurisdiction(
        jurisdiction_code="PA", name="Panama", basel_aml_index=6.0,
        corridor_risk_weight=1.4, nested_correspondent_prohibited=True,
    )
    new_jurisdiction(
        jurisdiction_code="FR", name="France", basel_aml_index=5.0, corridor_risk_weight=1.2
    )
    respondent = _licensed()
    rid = respondent["id"]
    assert respondent["nested_activity_permitted"] is False
    contact = make_respondent_headers(rid)

    sanctioned = api.create_nested_relationship(
        rid,
        {"downstream_institution_name": "Bank Melli", "downstream_jurisdiction_code": "IR",
         "relationship_type": "DOWNSTREAM_CORRESPONDENT", "discovery_source": "QUESTIONNAIRE"},
        contact,
    )
    validate_error(
        sanctioned, ApiErrorId.ERR_NESTED_SANCTIONED_JURISDICTION, expected_status=422
    )

    prohibited = api.create_nested_relationship(
        rid,
        {"downstream_institution_name": "Banco Panama", "downstream_jurisdiction_code": "PA",
         "relationship_type": "DOWNSTREAM_CORRESPONDENT", "discovery_source": "QUESTIONNAIRE"},
        contact,
    )
    validate_error(
        prohibited, ApiErrorId.ERR_NESTED_JURISDICTION_PROHIBITS_NESTING, expected_status=422
    )

    payable_through = api.create_nested_relationship(
        rid,
        {"downstream_institution_name": "Petit Banque SA", "downstream_jurisdiction_code": "FR",
         "relationship_type": "PAYABLE_THROUGH", "discovery_source": "QUESTIONNAIRE"},
        contact,
    )
    validate_error(
        payable_through, ApiErrorId.ERR_PAYABLE_THROUGH_NOT_PERMITTED, expected_status=422
    )

    lawful = validate_success(
        api.create_nested_relationship(
            rid,
            {"downstream_institution_name": "Petit Banque SA",
             "downstream_jurisdiction_code": "FR",
             "relationship_type": "DOWNSTREAM_CORRESPONDENT",
             "discovery_source": "QUESTIONNAIRE"},
            contact,
        ),
        expected_status=201,
    )
    assert lawful["state"] == "DISCLOSED"
    assert lawful["depth"] == 1
    assert lawful["prohibition_reason"] is None

    _rows, meta = validate_paginated(
        api.list_nested_relationships(ANALYST, params={"respondent_bank_id": rid})
    )
    assert meta["total_count"] == 1
    rolled_up = read_respondent(rid)
    assert rolled_up["disclosed_nested_count"] == 1
    assert rolled_up["undisclosed_nested_count"] == 0


def test_a_declared_chain_reaching_depth_three_is_rejected(api):
    """The prohibition rung bites one level before the structural maximum, so a transitive walk
    that computes three is refused even though three is a storable depth.

    Design: Corner/errors/a_declared_chain_reaching_depth_three_is_rejected
    """
    _de()
    bank_a = _licensed(legal_name="A Bank AG", swift_bic="ABNKDEFF")
    bank_b = _licensed(legal_name="B Bank AG", swift_bic="BBNKDEFF")
    bank_c = _licensed(legal_name="C Bank AG", swift_bic="CBNKDEFF")

    leaf = add_nested(
        bank_c["id"], "DE", ANALYST, downstream_institution_name="Leaf Sparkasse",
        discovery_source="QUESTIONNAIRE",
    )
    mid = add_nested(
        bank_b["id"], "DE", ANALYST, downstream_institution_name="C Bank AG",
        discovery_source="QUESTIONNAIRE", downstream_respondent_bank_id=bank_c["id"],
    )
    assert leaf["depth"] == 1
    assert mid["depth"] == 2

    response = api.create_nested_relationship(
        bank_a["id"],
        {"downstream_institution_name": "B Bank AG", "downstream_jurisdiction_code": "DE",
         "relationship_type": "DOWNSTREAM_CORRESPONDENT", "discovery_source": "QUESTIONNAIRE",
         "downstream_respondent_bank_id": bank_b["id"]},
        make_respondent_headers(bank_a["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NESTED_DEPTH_EXCEEDED, expected_status=422)

    _rows, meta = validate_paginated(
        api.list_nested_relationships(ANALYST, params={"respondent_bank_id": bank_a["id"]})
    )
    assert meta["total_count"] == 0
    assert read_respondent(bank_a["id"])["max_nested_depth"] == 0
    assert read_respondent(bank_b["id"])["max_nested_depth"] == 2
    assert read_nested(mid["id"])["depth"] == 2


def test_approval_after_a_sanctions_evasion_confirmation_fails_the_ownership_gate(api):
    """Confirming a sanctions-evasion item revokes every verification behind the committee's
    back, so an otherwise approvable file fails on the ownership gate alone.

    Design: Corner/errors/approval_after_a_sanctions_evasion_confirmation_fails_the_ownership_gate
    """
    _de()
    respondent = _licensed()
    rid = respondent["id"]
    owner = add_verified_owner(rid, "DE", owner_name="Anna Weber", ownership_pct=80.00)
    assessed_questionnaire(
        rid, "ONBOARDING_PROVISIONAL",
        self_ratings={domain: 4 for domain in CONTROL_DOMAIN_ORDER},
        overlays=all_assessed_overlays(4),
    )
    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    assert scored["control_score"] == 80.00
    assert scored["inherent_risk_score"] == 10.00
    assert scored["residual_risk_score"] == 6.63
    assert scored["risk_rating"] == "LOW"
    assert scored["dd_state"] == "PENDING_COMMITTEE"
    assert scored["ownership_verified"] is True

    event = log_media(
        rid, headline="Sanctions evasion allegations", category="SANCTIONS_EVASION",
        severity_tier="TIER_3", source_reliability="C", event_date="2026-07-01T00:00:00Z",
    )
    triage_media(event["id"], "CONFIRM")

    assert read_media(event["id"])["uplift_points"] == 1.50
    assert validate_success(
        api.get_beneficial_owner(owner["id"], ANALYST)
    )["verification_status"] == "PENDING"
    revoked = read_respondent(rid)
    assert revoked["verified_ownership_pct"] == 0.00
    assert revoked["ownership_verified"] is False
    assert revoked["adverse_media_uplift"] == 1.50
    assert revoked["residual_risk_score"] == 8.13
    assert revoked["risk_rating"] == "LOW"

    response = api.decide_committee(
        rid, {"action": "APPROVE", "decision_note": "Committee sign-off"}, COMMITTEE
    )
    validate_error(response, ApiErrorId.ERR_OWNERSHIP_CHAIN_INCOMPLETE, expected_status=422)

    stored = read_respondent(rid)
    assert stored["dd_state"] == "PENDING_COMMITTEE"
    assert stored["approved_by_user_id"] is None
    assert stored["last_approved_at"] is None

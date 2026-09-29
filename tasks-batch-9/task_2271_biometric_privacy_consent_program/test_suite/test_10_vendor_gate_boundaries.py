"""The inclusive boundaries of the two vendor gates on activation.

A risk score of exactly 70 and a compliance score of exactly 82.50 both pass; one
point above the risk gate refuses collection.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    VENDOR_MANAGER,
    ApiErrorId,
    assert_asset_state,
    assert_is_null,
    assert_two_decimal_value,
    compliance_baseline,
    create_asset,
    create_vendor,
    create_vendor_contract,
    read_asset,
    read_contract,
    validate_error,
    validate_success,
)

GATEKEEPER = {
    "name": "GateKeeper Bio",
    "sells_biometric_data": True,
    "subprocessor_count": 4,
    "deletion_sla_days": 30,
    "subprocessor_disclosure_complete": True,
}


def _point_awaiting_its_processor(api):
    ctx = compliance_baseline(api)
    vendor = create_vendor(api, ctx["program_id"], attestation_status="REQUESTED", **GATEKEEPER)
    contract = create_vendor_contract(api, vendor["id"], target_status="APPROVED")
    asset = create_asset(
        api,
        ctx["program_id"],
        ctx["jurisdiction_id"],
        target_status="CLASSIFIED",
        vendor_id=vendor["id"],
    )
    ctx.update(
        {
            "vendor_id": vendor["id"],
            "vendor": vendor,
            "contract_id": contract["id"],
            "asset_id": asset["id"],
        }
    )
    return ctx


def test_a_risk_score_of_eighty_refuses_activation(api):
    """One point past the gate stops collection from starting.

    PRD §3.2: "The gate that matters is the one applied when a collection point is
    activated: the operating vendor's `risk_score` must be **at most 70**. A score
    of exactly 70 passes; a score of 75 fails and yields
    `ERR_VENDOR_RISK_TOO_HIGH`."

    GateKeeper Bio admits sale (30 points), discloses four subprocessors (20
    points) and is still awaiting its attestation (10 points) on top of the base
    20, so it scores 80.

    Design: Difficulty/boundary_precision_check/vendor_risk_score_exactly_at_gate_70_activates_while_80_is_refused
    """
    ctx = _point_awaiting_its_processor(api)
    assert ctx["vendor"]["risk_score"] == 80

    refused = api.transition_asset(ctx["asset_id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER)

    validate_error(refused, ApiErrorId.VENDOR_RISK_TOO_HIGH)

    unchanged = read_asset(api, ctx["asset_id"])
    assert unchanged["status"] == "CLASSIFIED"
    assert_is_null(unchanged["collection_started_at"], "collection_started_at on a refused activation")


def test_a_risk_score_of_exactly_seventy_and_a_score_of_exactly_the_floor_activate(api):
    """Receiving the attestation brings both gates to their inclusive edge.

    PRD §3.2: "The floor the score must clear, both to execute a contract and to be
    relied on when activating a collection point, is **82.50**."

    A received attestation removes the 10 attestation risk points, leaving exactly
    70, and lifts the clause factor to 1.000, so the contract scores 100 - 7.5 for
    the admitted sale - 10 for four subprocessors = 82.50, exactly the floor.

    Design: Difficulty/boundary_precision_check/vendor_risk_score_exactly_at_gate_70_activates_while_80_is_refused
    """
    ctx = _point_awaiting_its_processor(api)

    received = validate_success(
        api.record_attestation(ctx["vendor_id"], {"attestation_status": "RECEIVED"}, VENDOR_MANAGER)
    )
    assert received["risk_score"] == 70, "20 base + 30 sale + 20 subprocessors with a received attestation"
    assert_two_decimal_value(
        read_contract(api, ctx["contract_id"])["compliance_score"], 82.50, "compliance_score"
    )

    executed = validate_success(
        api.transition_vendor_contract(ctx["contract_id"], {"to_status": "EXECUTED"}, VENDOR_MANAGER)
    )
    assert executed["status"] == "EXECUTED", "a score of exactly 82.50 clears the execution floor"

    activated = validate_success(
        api.transition_asset(ctx["asset_id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER)
    )

    assert_asset_state(
        activated,
        status="ACTIVE",
        pinned_policy_id=ctx["policy_id"],
        collection_started_at="2026-08-01T00:00:00.000Z",
        destruction_due_at="2026-08-31T00:00:00.000Z",
    )

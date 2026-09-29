"""Corner queue - section state_machines, part D: beneficial-owner verification lifecycle."""
from test_helpers import (
    ApiErrorId,
    add_owner,
    new_jurisdiction,
    new_respondent,
    read_respondent,
    validate_error,
    validate_success,
    verify_owner,
)
from test_helpers.fixtures import ANALYST


def _respondent():
    new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )
    return new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )


def _read_owner(api, owner_id):
    return validate_success(api.get_beneficial_owner(owner_id, ANALYST))


def test_invalid_transition_owner_reset_from_pending_rejected(api):
    """Reset exists only to undo a rejection, so applying it to an owner that was never
    rejected is refused rather than treated as a harmless no-op.

    Design: Corner/state_machines/invalid_transition_owner_reset_from_pending_rejected
    """
    rid = _respondent()["id"]
    owner = add_owner(rid, "DE", owner_name="Anna Weber", ownership_pct=80.00)

    response = api.verify_owner(owner["id"], {"action": "RESET"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_OWNER_STATE)

    assert _read_owner(api, owner["id"])["verification_status"] == "PENDING"


def test_idempotency_second_owner_verification_rejected(api):
    """Verification is a once-only transition out of PENDING, so the repeat is refused and
    the direct-owner rollup cannot double-count the same stake.

    Design: Corner/state_machines/idempotency_second_owner_verification_rejected
    """
    rid = _respondent()["id"]
    owner = add_owner(rid, "DE", owner_name="Anna Weber", ownership_pct=80.00)
    verify_owner(owner["id"])

    response = api.verify_owner(owner["id"], {"action": "VERIFY"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_OWNER_STATE)

    assert _read_owner(api, owner["id"])["verification_status"] == "VERIFIED"
    assert read_respondent(rid)["verified_ownership_pct"] == 80.00


def test_precondition_owner_verify_requires_verified_parent_first(api):
    """The look-through chain has to be verified top-down, so a depth-2 child under a still
    pending parent cannot be verified and the rollup stays empty.

    Design: Corner/state_machines/precondition_owner_verify_requires_verified_parent_first
    """
    rid = _respondent()["id"]
    parent = add_owner(
        rid, "DE", owner_name="Holdco GmbH", owner_type="LEGAL_ENTITY", ownership_pct=60.00
    )
    child = add_owner(
        rid, "DE", owner_name="Anna Weber", ownership_pct=50.00, parent_owner_id=parent["id"]
    )

    response = api.verify_owner(child["id"], {"action": "VERIFY"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_OWNER_STATE)

    assert _read_owner(api, child["id"])["verification_status"] == "PENDING"
    assert read_respondent(rid)["verified_ownership_pct"] == 0.00


def test_owner_reject_without_rejection_reason_rejected(api):
    """The reason is mandatory for the rejection discriminator alone, so omitting it is a
    body defect and the owner keeps both its pending status and its empty reason.

    Design: Corner/state_machines/owner_reject_without_rejection_reason_rejected
    """
    rid = _respondent()["id"]
    owner = add_owner(rid, "DE", owner_name="Anna Weber", ownership_pct=80.00)

    response = api.verify_owner(owner["id"], {"action": "REJECT"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST_BODY)

    stored = _read_owner(api, owner["id"])
    assert stored["verification_status"] == "PENDING"
    assert stored["rejection_reason"] is None


def test_owner_reset_after_sanctions_hit_rejection_refused(api):
    """Reset is available from a rejection generally, but a sanctions hit is never reset, so
    the reason itself - not the state - is what blocks the request.

    Design: Corner/state_machines/owner_reset_after_sanctions_hit_rejection_refused
    """
    rid = _respondent()["id"]
    owner = add_owner(rid, "DE", owner_name="Ivan Petrov", ownership_pct=40.00)
    verify_owner(owner["id"], "REJECT", rejection_reason="SANCTIONS_HIT")

    response = api.verify_owner(owner["id"], {"action": "RESET"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_OWNER_STATE)

    stored = _read_owner(api, owner["id"])
    assert stored["verification_status"] == "REJECTED"
    assert stored["rejection_reason"] == "SANCTIONS_HIT"

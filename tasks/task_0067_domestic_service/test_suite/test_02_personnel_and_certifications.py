"""Personnel onboarding, identity verification, suspension, disqualification,
and SkillCertification lifecycle (PRD §3.1, §3.2).
"""

import pytest

from test_helpers import (
    OPERATOR_HEADERS,
    activate_personnel,
    approve_certification,
    assert_certification,
    assert_personnel,
    create_active_personnel,
    create_certification,
    create_certification_payload,
    create_pending_personnel,
    create_personnel,
    create_personnel_payload,
    drive_order_to,
    get_personnel,
    iso_in,
    setup_basic_scenario,
    validate_error,
    validate_success,
    verify_personnel_identity,
)


# =============================================================================
# Creation (PRD §3.1)
# =============================================================================


def test_create_personnel_starts_pending_verification(api):
    """PRD §3.1: "On creation, status starts at PENDING_VERIFICATION,
    identity_verified is false, rating_score is 0, rating_count is 0,
    workload_active_orders is 0, tier is BRONZE, and last_recert_at is null."

    Claim: a freshly created ServicePersonnel has status PENDING_VERIFICATION,
    identity_verified=false, tier=BRONZE, rating_count=0.
    """
    res = api.create_personnel(create_personnel_payload(), OPERATOR_HEADERS)
    body = validate_success(res, expected_status=201)
    assert_personnel(body)
    assert body["status"] == "PENDING_VERIFICATION"
    assert body["identity_verified"] is False
    assert body["tier"] == "BRONZE"
    assert body["rating_count"] == 0
    assert body["rating_score"] == 0 or body["rating_score"] == 0.0
    assert body["workload_active_orders"] == 0
    assert body.get("last_recert_at") is None


def test_create_personnel_default_service_radius_km(api):
    """PRD §3.1: "service_radius_km (defaulting to 10 if not supplied)."

    Claim: omitting service_radius_km defaults the value to 10.
    """
    payload = create_personnel_payload()
    payload.pop("service_radius_km", None)
    res = api.create_personnel(payload, OPERATOR_HEADERS)
    body = validate_success(res, expected_status=201)
    assert body["service_radius_km"] == 10


# =============================================================================
# Activation (PRD §3.1)
# =============================================================================


def test_activate_personnel_requires_identity_verified(api):
    """PRD §3.1: "Once identity_verified is true, the health certificate is
    still in date ..., and at least one ACTIVE SkillCertification exists for
    this personnel, the operator can activate the record... If any of these
    three preconditions is unmet, the transition is rejected with
    ERR_INVALID_STATE."

    Claim: activate without identity_verified → ERR_INVALID_STATE 409.
    """
    p = create_pending_personnel()
    res = api.activate_personnel(p["id"], OPERATOR_HEADERS)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_activate_personnel_requires_active_certification(api):
    """PRD §3.1: "If any of these three preconditions is unmet, the transition
    is rejected with ERR_INVALID_STATE."

    Claim: activate after identity-verify but without any ACTIVE
    SkillCertification → ERR_INVALID_STATE 409.
    """
    p = create_pending_personnel()
    verify_personnel_identity(p["id"])
    # Cert is created PENDING (not approved). Approve precondition fails.
    create_certification(p["id"])
    res = api.activate_personnel(p["id"], OPERATOR_HEADERS)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_activate_personnel_succeeds_when_prereqs_met(api):
    """PRD §3.1: "Once identity_verified is true, the health certificate is
    still in date (the current time is strictly before health_cert_expires_at),
    and at least one ACTIVE SkillCertification exists for this personnel, the
    operator can activate the record, transitioning it from
    PENDING_VERIFICATION to ACTIVE."

    Claim: with identity verified + approved cert + future health cert,
    activate moves status to ACTIVE.
    """
    p, _ = create_active_personnel()
    assert p["status"] == "ACTIVE"


# =============================================================================
# Suspension and active-assignments guard (PRD §3.1)
# =============================================================================


def test_suspend_personnel_with_no_active_orders_succeeds(api):
    """PRD §3.1: "Suspension drives ACTIVE to SUSPENDED, but only if no Order
    assigned to this personnel is currently in DISPATCHED, ACCEPTED, or
    IN_PROGRESS."

    Claim: a freshly active personnel with no orders can be suspended.
    """
    p, _ = create_active_personnel()
    res = api.suspend_personnel(p["id"], OPERATOR_HEADERS)
    body = validate_success(res)
    assert body["status"] == "SUSPENDED"


def test_suspend_personnel_with_dispatched_order_blocked(api):
    """PRD §3.1: "a suspend attempt against a personnel with active assignments
    is rejected with ERR_HAS_ACTIVE_ASSIGNMENTS."

    Claim: suspending while a DISPATCHED order is assigned → ERR_HAS_ACTIVE_ASSIGNMENTS 422.
    """
    ctx = setup_basic_scenario()
    drive_order_to(ctx, "DISPATCHED")
    res = api.suspend_personnel(ctx["personnel"]["id"], OPERATOR_HEADERS)
    validate_error(res, "ERR_HAS_ACTIVE_ASSIGNMENTS", expected_status=422)


def test_disqualify_personnel_with_dispatched_order_blocked(api):
    """PRD §3.1: "Disqualification drives ACTIVE to DISQUALIFIED under the same
    active-assignments precondition."

    Claim: disqualifying while a DISPATCHED order is assigned →
    ERR_HAS_ACTIVE_ASSIGNMENTS 422.
    """
    ctx = setup_basic_scenario()
    drive_order_to(ctx, "DISPATCHED")
    res = api.disqualify_personnel(ctx["personnel"]["id"], OPERATOR_HEADERS)
    validate_error(res, "ERR_HAS_ACTIVE_ASSIGNMENTS", expected_status=422)


def test_disqualify_revokes_all_certifications(api):
    """PRD §3.1: "Disqualification ... additionally revokes every linked
    SkillCertification that was in ACTIVE status, transitioning each one to
    REVOKED and recomputing skill_tags to the empty array."

    Claim: disqualifying a personnel revokes its ACTIVE cert and refreshes
    skill_tags to [].
    """
    p, cert = create_active_personnel(skill_tag="CLEANING")
    res = api.disqualify_personnel(p["id"], OPERATOR_HEADERS)
    body = validate_success(res)
    assert body["status"] == "DISQUALIFIED"
    assert body["skill_tags"] == []
    # Cert is REVOKED via the listing endpoint:
    list_res = api.list_personnel_certifications(p["id"], OPERATOR_HEADERS)
    data = list_res.json()["data"]
    rows = data if isinstance(data, list) else data.get("entries", [])
    assert any(c["id"] == cert["id"] and c["status"] == "REVOKED" for c in rows)


# =============================================================================
# Reinstate (PRD §3.1)
# =============================================================================


def test_reinstate_personnel_to_active(api):
    """PRD §3.1: "A suspended personnel can be reinstated to ACTIVE provided
    the health certificate is still in date and at least one ACTIVE
    SkillCertification still exists."

    Claim: a SUSPENDED personnel (still has valid cert + health) is reinstated
    to ACTIVE.
    """
    p, _ = create_active_personnel()
    api.suspend_personnel(p["id"], OPERATOR_HEADERS)
    res = api.reinstate_personnel(p["id"], OPERATOR_HEADERS)
    body = validate_success(res)
    assert body["status"] == "ACTIVE"


# =============================================================================
# SkillCertification lifecycle (PRD §3.2)
# =============================================================================


def test_approve_certification_requires_training_hours_at_least_8(api):
    """PRD §3.2: "Approval requires training_hours to be at least 8 and
    expires_at to be strictly in the future; if either precondition fails, the
    approval is rejected with ERR_CERT_REQUIREMENTS_NOT_MET."

    Claim: approve a cert with training_hours=7 → ERR_CERT_REQUIREMENTS_NOT_MET 422.
    """
    p = create_pending_personnel()
    res_create = api.create_certification(
        create_certification_payload(p["id"], training_hours=7), OPERATOR_HEADERS
    )
    cert = res_create.json()["data"]
    res = api.approve_certification(cert["id"], OPERATOR_HEADERS)
    validate_error(res, "ERR_CERT_REQUIREMENTS_NOT_MET", expected_status=422)


def test_approve_certification_requires_future_expiry(api):
    """PRD §3.2: "Approval requires training_hours to be at least 8 and
    expires_at to be strictly in the future; if either precondition fails, the
    approval is rejected with ERR_CERT_REQUIREMENTS_NOT_MET."

    Claim: approve a cert whose expires_at is in the past →
    ERR_CERT_REQUIREMENTS_NOT_MET 422.
    """
    p = create_pending_personnel()
    res_create = api.create_certification(
        create_certification_payload(p["id"], expires_at=iso_in(days=-1)),
        OPERATOR_HEADERS,
    )
    cert = res_create.json()["data"]
    res = api.approve_certification(cert["id"], OPERATOR_HEADERS)
    validate_error(res, "ERR_CERT_REQUIREMENTS_NOT_MET", expected_status=422)


def test_approve_certification_active_skill_tag_added_to_personnel(api):
    """PRD §3.2: "On approval, the server stamps certified_at to the current
    time and recomputes the personnel's skill_tags view to include this newly
    active skill tag."

    Claim: after approving a CLEANING cert for personnel P, P.skill_tags
    contains "CLEANING".
    """
    p = create_pending_personnel()
    cert = create_certification(p["id"], skill_tag="CLEANING")
    approve_certification(cert["id"])
    refreshed = get_personnel(p["id"])
    assert "CLEANING" in refreshed["skill_tags"]


def test_revoke_certification_refreshes_skill_tags(api):
    """PRD §3.2: "Revocation drives a certification from ACTIVE to REVOKED and
    likewise refreshes skill_tags on the personnel."

    Claim: revoking the only ACTIVE cert for personnel removes the skill_tag
    from skill_tags (sole cert → empty array).
    """
    p, cert = create_active_personnel(skill_tag="COOKING")
    res = api.revoke_certification(cert["id"], OPERATOR_HEADERS)
    body = validate_success(res)
    assert body["status"] == "REVOKED"
    refreshed = get_personnel(p["id"])
    assert "COOKING" not in refreshed["skill_tags"]


def test_create_personnel_age_below_18_rejected(api):
    """PRD §3.1: "age is constrained to be at least 18 and no greater than 70."

    Claim: creating a personnel with age=17 returns ERR_VALIDATION_ERROR 422.
    """
    res = api.create_personnel(create_personnel_payload(age=17), OPERATOR_HEADERS)
    validate_error(res, "ERR_VALIDATION_ERROR", expected_status=422)


def test_create_personnel_age_above_70_rejected(api):
    """PRD §3.1: "age is constrained to be at least 18 and no greater than 70."

    Claim: creating a personnel with age=71 returns ERR_VALIDATION_ERROR 422.
    """
    res = api.create_personnel(create_personnel_payload(age=71), OPERATOR_HEADERS)
    validate_error(res, "ERR_VALIDATION_ERROR", expected_status=422)


def test_certification_status_starts_pending(api):
    """PRD §3.2: "Each certification carries the foreign-key personnel_id, the
    skill_tag being certified, an integer-or-decimal training_hours count, an
    expires_at timestamp, and a status that begins at PENDING."

    Claim: a freshly created SkillCertification has status=PENDING.
    """
    p = create_pending_personnel()
    cert = create_certification(p["id"])
    assert_certification(cert)
    assert cert["status"] == "PENDING"

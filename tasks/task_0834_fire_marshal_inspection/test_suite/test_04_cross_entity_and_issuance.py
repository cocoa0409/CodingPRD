"""Cross-entity state dependencies at permit issuance and certificate reinstatement,
plus terminal-state lockdown on permit revocation.
"""
from test_helpers import (
    validate_error, validate_success,
    create_submitted_application, pay_application_fee, get_application,
    create_issued_permit_scenario,
    setup_certificate_suspended_by_imminent, get_certificate,
    api_client,
    TEST_USERS,
)

FIRE_MARSHAL = TEST_USERS["fire_marshal_headers"]


# ─── Difficulty/priority_pair_validation_conflict/issue_permit_state_beats_fiscal
def test_state_error_reported_when_both_state_and_fee_fail(api):
    """PRD §3.5: "The application's `status` must be `APPROVED`; issuance against an
    application in any other status is rejected with `ERR_APPLICATION_NOT_APPROVED`."
    PRD §2.9: "they are evaluated in a fixed order so that the returned `error_id` is
    deterministic"

    Design: Difficulty/priority_pair_validation_conflict/issue_permit_state_beats_fiscal
    """
    # Application is UNDER_REVIEW (not APPROVED) and amount_paid_cents is 0: both the
    # state gate and the fiscal gate fail; the state gate is stated first.
    _prop, app, _pr = create_submitted_application(applicant_user_id="app-5")
    res = api.create_permit({"application_id": app["id"]}, FIRE_MARSHAL)
    validate_error(res, "ERR_APPLICATION_NOT_APPROVED", expected_status=409)


def test_fee_error_not_reported_when_state_also_fails(api):
    """PRD §3.5: "the application's `amount_paid_cents` must be at least that
    `final_fee_cents`, otherwise issuance is rejected with `ERR_FEE_UNPAID`."

    Design: Difficulty/priority_pair_validation_conflict/issue_permit_state_beats_fiscal
    """
    _prop, app, _pr = create_submitted_application(applicant_user_id="app-5b")
    res = api.create_permit({"application_id": app["id"]}, FIRE_MARSHAL)
    body = res.json()
    assert body["data"]["error_id"] != "ERR_FEE_UNPAID", \
        "the state gate is checked before the fiscal gate; ERR_FEE_UNPAID must not win"


# ─── Difficulty/cross_entity_state_dependency/permit_requires_application_approved
def test_issue_permit_blocked_by_unapproved_application_even_when_paid(api):
    """PRD §3.5: "The application's `status` must be `APPROVED`; issuance against an
    application in any other status is rejected with `ERR_APPLICATION_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/permit_requires_application_approved
    """
    _prop, app, _pr = create_submitted_application(applicant_user_id="app-7")
    pay_application_fee(app["id"], "app-7", 20640)  # fully paid, isolates the state check
    res = api.create_permit({"application_id": app["id"]}, FIRE_MARSHAL)
    validate_error(res, "ERR_APPLICATION_NOT_APPROVED", expected_status=409)


def test_application_stays_under_review_after_blocked_issuance(api):
    """PRD §3.5: "Once an application reaches `APPROVED`, a `FireMarshal` issues the
    permit." PRD §3.5: "The application's `status` must be `APPROVED`; issuance against
    an application in any other status is rejected with `ERR_APPLICATION_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/permit_requires_application_approved
    """
    _prop, app, _pr = create_submitted_application(applicant_user_id="app-7b")
    pay_application_fee(app["id"], "app-7b", 20640)
    api.create_permit({"application_id": app["id"]}, FIRE_MARSHAL)
    assert get_application(app["id"])["status"] == "UNDER_REVIEW", \
        "a rejected issuance must not transition the application"
    body = api.list_permits(FIRE_MARSHAL, params={"application_id": app["id"]}).json()
    assert body["data"] == [], "no permit may exist for an application that never issued"


# ─── Difficulty/cross_entity_state_dependency/certificate_reinstate_requires_no_open_violations
def test_reinstate_blocked_by_open_violation(api):
    """PRD §3.8: "Reinstatement is permitted only when no violation on the property
    (reached through its inspections) is in `OPEN` or `ESCALATED`; otherwise it is
    rejected with `ERR_OPEN_VIOLATIONS`."

    Design: Difficulty/cross_entity_state_dependency/certificate_reinstate_requires_no_open_violations
    """
    _prop, cert, _insp, _viol = setup_certificate_suspended_by_imminent()
    res = api.reinstate_certificate(cert["id"], FIRE_MARSHAL)
    validate_error(res, "ERR_OPEN_VIOLATIONS", expected_status=409)


def test_certificate_stays_suspended_when_reinstate_blocked(api):
    """PRD §3.8: "A `FireMarshal` reinstates a suspended certificate, moving
    `occupancy_status` from `SUSPENDED` back to `VALID` and setting `placard_status`
    to `GREEN`."

    Design: Difficulty/cross_entity_state_dependency/certificate_reinstate_requires_no_open_violations
    """
    _prop, cert, _insp, _viol = setup_certificate_suspended_by_imminent(address="15 O St")
    api.reinstate_certificate(cert["id"], FIRE_MARSHAL)
    after = get_certificate(cert["id"])
    assert after["occupancy_status"] == "SUSPENDED", \
        "a blocked reinstatement must leave occupancy_status SUSPENDED"


# ─── Corner/state_machines/corner_revoke_revoked_permit_returns_409 ────────
def test_revoke_already_revoked_permit_rejected(api):
    """PRD §3.5: "Revocation is legal only while the permit is `ISSUED` and moves it
    to `REVOKED`." PRD §2.9: "the generic "illegal from current state" rejection is
    `ERR_INVALID_STATE` (409)"

    Design: Corner/state_machines/corner_revoke_revoked_permit_returns_409
    """
    _prop, _app, permit = create_issued_permit_scenario(applicant_user_id="app-10", amount_cents=20640)
    validate_success(api.revoke_permit(permit["id"], FIRE_MARSHAL), 200)
    res = api.revoke_permit(permit["id"], FIRE_MARSHAL)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

"""License lifecycle transitions and the cross-entity license gate on accept."""
from test_helpers import (
    validate_error, validate_success,
    TEST_USERS, make_field_adjuster_headers,
    create_license_payload,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["licensing_admin_headers"]
DESK = TEST_USERS["desk_examiner_headers"]


def test_activate_active_license_returns_not_pending(api):
    """PRD 3.1: "Activating a PENDING license transitions it to ACTIVE, but only if
    the license is genuinely PENDING (otherwise ERR_LICENSE_NOT_PENDING) and the
    logical clock is strictly before expires_at (otherwise ERR_LICENSE_EXPIRED)."

    Design: Corner/state_machines/activate_active_license_returns_not_pending
    """
    adj = fx.create_adjuster(api)
    lic = fx.create_active_license(api, adj["id"], state_code="FL")
    resp = api.activate_license(lic["id"], ADMIN)
    validate_error(resp, "ERR_LICENSE_NOT_PENDING")


def test_license_expired_on_activate_after_clock_advance(api):
    """PRD 3.1: "Activating a PENDING license transitions it to ACTIVE, but only if
    the license is genuinely PENDING (otherwise ERR_LICENSE_NOT_PENDING) and the
    logical clock is strictly before expires_at (otherwise ERR_LICENSE_EXPIRED)."

    Design: Corner/state_machines/license_expired_on_activate_after_clock_advance
    """
    adj = fx.create_adjuster(api)
    lic = fx.create_license(api, adj["id"], state_code="FL",
                            expires_at="2027-01-01T00:00:00Z")
    fx.set_clock(api, "2027-02-01T00:00:00Z")
    resp = api.activate_license(lic["id"], ADMIN)
    validate_error(resp, "ERR_LICENSE_EXPIRED")


def _suspended_license_offered_assignment(api):
    adj = fx.create_adjuster(api)
    lic = fx.create_active_license(api, adj["id"], state_code="FL")
    fx.get_success_data(api.suspend_license(lic["id"], ADMIN))
    claim = fx.create_claim(api, loss_state="FL", peril_type="HAIL", policy_type="ACV")
    asg = fx.create_assignment(api, claim["id"], adj["id"])
    return adj, asg


def test_accept_with_suspended_license_rejected(api):
    """PRD 3.3: "the adjuster holds a qualifying license — an AdjusterLicense in
    ACTIVE status whose state_code equals the claim's loss_state and whose expires_at
    is strictly after the current clock (otherwise ERR_NO_ACTIVE_LICENSE)."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_active_license_in_loss_state
    """
    adj, asg = _suspended_license_offered_assignment(api)
    resp = api.accept_assignment(asg["id"], make_field_adjuster_headers(adj["id"]))
    validate_error(resp, "ERR_NO_ACTIVE_LICENSE")


def test_accept_with_suspended_license_leaves_assignment_offered(api):
    """PRD 3.3: "Accepting an offer moves the assignment OFFERED -> ACCEPTED, but only
    if the assignment is OFFERED ... and the adjuster holds a qualifying license — an
    AdjusterLicense in ACTIVE status whose state_code equals the claim's loss_state and
    whose expires_at is strictly after the current clock (otherwise
    ERR_NO_ACTIVE_LICENSE)."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_active_license_in_loss_state
    """
    adj, asg = _suspended_license_offered_assignment(api)
    api.accept_assignment(asg["id"], make_field_adjuster_headers(adj["id"]))
    data = validate_success(api.get_assignment(asg["id"], DESK))
    assert data["work_status"] == "OFFERED", "rejected accept must leave work_status unchanged"

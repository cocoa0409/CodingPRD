"""Invalid state transitions and the primary-residence attestation constraint.

Covers corner queue B instances under the state_machines and validations sections.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_host_headers, TEST_USERS,
    create_zone, create_host, create_property, create_draft_permit, attest_primary,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def test_activate_draft_permit_returns_invalid_state(api):
    """PRD §3.6: "Once a permit is ISSUED, its owning host activates it for
    operation, moving it from ISSUED to ACTIVE."
    PRD §2.9: "if the requested transition is not defined from the resource's
    current state, the request is rejected with ERR_INVALID_STATE (HTTP 409)."

    Activation is defined only from ISSUED; activating a DRAFT permit is invalid.

    Design: Corner/state_machines/activate_from_draft_permit_returns_invalid_state
    """
    zone = create_zone()
    host = create_host()
    prop = create_property(host["id"], zone["id"])
    permit = create_draft_permit(prop["id"], permit_type="WHOLE_HOME")
    validate_error(
        api.activate_permit(permit["id"], make_host_headers(host["id"])),
        ApiErrorId.ERR_INVALID_STATE,
    )


def test_reject_already_rejected_permit_returns_invalid_state(api):
    """PRD §3.3: "the permit ... begins life in DRAFT status."
    PRD §2.9: "if the requested transition is not defined from the resource's
    current state, the request is rejected with ERR_INVALID_STATE (HTTP 409)."

    Reject is defined only from DRAFT; a second reject on a REJECTED permit is
    invalid.

    Design: Corner/state_machines/reject_terminal_rejected_permit_returns_invalid_state
    """
    zone = create_zone()
    host = create_host()
    prop = create_property(host["id"], zone["id"])
    permit = create_draft_permit(prop["id"], permit_type="WHOLE_HOME")
    validate_success(api.reject_permit(permit["id"], REGISTRAR))
    validate_error(api.reject_permit(permit["id"], REGISTRAR), ApiErrorId.ERR_INVALID_STATE)


def test_duplicate_primary_residence_rejected(api):
    """PRD §3.2: "A host may hold at most one primary residence; if the host
    already has a primary residence set to a different property, attempting to
    set a second is rejected with ERR_PRIMARY_RESIDENCE_CONFLICT (HTTP 409)."

    Design: Corner/validations/duplicate_primary_residence_rejected
    """
    zone = create_zone()
    host = create_host()
    prop_a = create_property(host["id"], zone["id"], street_address="PR-A St")
    prop_b = create_property(host["id"], zone["id"], street_address="PR-B St")
    attest_primary(host["id"], prop_a["id"])
    validate_error(
        api.attest_primary_residence(
            host["id"], {"property_id": prop_b["id"]}, make_host_headers(host["id"])
        ),
        ApiErrorId.ERR_PRIMARY_RESIDENCE_CONFLICT,
    )

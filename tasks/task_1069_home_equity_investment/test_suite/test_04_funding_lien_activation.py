"""Funding cascade, lien recording, and agreement activation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS,
    fixtures,
)

ANALYST = TEST_USERS["analyst_headers"]
CLOSING = TEST_USERS["closing_agent_headers"]


# --------------------------------------------------------------------------
# cross_entity_state_dependency: activate requires lien RECORDED
# --------------------------------------------------------------------------
def test_activate_with_pending_lien_rejected(api):
    """PRD §3.5: "Activation is refused with ERR_LIEN_NOT_RECORDED while the
    agreement's lien has not yet reached RECORDED."

    Design: Difficulty/cross_entity_state_dependency/agreement_activate_requires_lien_recorded
    """
    ctx = fixtures.setup_funded_agreement(api)
    validate_error(api.activate_agreement(ctx["agreement"]["id"], CLOSING), "ERR_LIEN_NOT_RECORDED", 409)


def test_activate_after_lien_recorded_succeeds(api):
    """PRD §3.5: "Once the lien is RECORDED, the closing agent activates the
    agreement, moving it from FUNDED to ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/agreement_activate_requires_lien_recorded
    """
    ctx = fixtures.setup_funded_agreement(api)
    fixtures.record_lien(api, ctx["lien"]["id"])
    activated = validate_success(api.activate_agreement(ctx["agreement"]["id"], CLOSING))
    assert activated["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Queue-B corner instances
# --------------------------------------------------------------------------
def test_record_lien_with_clouded_title_rejected(api):
    """PRD §3.5: "Recording moves the lien from `PENDING` to `RECORDED`, but
    only if the title resolves to `CLEAR`; a `CLOUDED` title is rejected with
    `ERR_TITLE_NOT_CLEAR` and the lien stays `PENDING`."

    Design: Corner/state_machines/lien_record_clouded_title_returns_error
    """
    ctx = fixtures.setup_funded_agreement(api)
    validate_error(
        api.record_lien(ctx["lien"]["id"], {"title_status": "CLOUDED", "lien_position": 2}, CLOSING),
        "ERR_TITLE_NOT_CLEAR", 409,
    )
    lien = validate_success(api.get_lien(ctx["lien"]["id"], CLOSING))
    assert lien["status"] == "PENDING"


def test_record_lien_by_analyst_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to invoke the requested endpoint per the authorization matrix in
    Section 4, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    (Recording a lien is authorized for ClosingAgent only.)

    Design: Corner/rbac/lien_record_by_analyst_unauthorized
    """
    ctx = fixtures.setup_funded_agreement(api)
    validate_error(
        api.record_lien(ctx["lien"]["id"], {"title_status": "CLEAR", "lien_position": 2}, ANALYST),
        "ERR_UNAUTHORIZED", 403,
    )

"""Incident workflow: review loop, resolution actions, and the revision loop's
single-campaign guarantee."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_credential,
    get_incident,
    get_key_node,
    get_propped_incident_for_door,
    get_success_data,
    setup_lost_credential_incident,
    setup_open_propped_alert,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["security_admin_headers"]
OFFICER = TEST_USERS["security_officer_headers"]


# ---------------------------------------------------------------------------
# Corner: incident transition guards
# ---------------------------------------------------------------------------

def test_incident_reopen_from_open_rejected(api):
    """PRD §3.4: "Resolved and dismissed incidents are not the end of the road:
    reopening moves `RESOLVED` → `UNDER_REVIEW` or `DISMISSED` → `UNDER_REVIEW`
    (from any other state, `ERR_INCIDENT_INVALID_STATE`), retaining the prior
    `resolution_action` and `resolution_note` for audit."

    Design: Corner/state_machines/incident_reopen_from_open_rejected
    """
    ctx = setup_lost_credential_incident("Reopen House")
    incident = ctx["incident"]
    assert incident["status"] == "OPEN"
    resp = api.reopen_incident(incident["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INCIDENT_INVALID_STATE)
    assert get_incident(incident["id"])["status"] == "OPEN"


def test_error_catalog_incident_dismiss_from_resolved(api):
    """PRD §3.4: "From `UNDER_REVIEW`, an operator may either dismiss the
    incident (`UNDER_REVIEW` → `DISMISSED`) or resolve it (`UNDER_REVIEW` →
    `RESOLVED`) by supplying a `resolution_action` of `NONE`, `REQUEST_REKEY`,
    or `DEACTIVATE_CREDENTIAL` plus an optional `resolution_note`."

    Design: Corner/errors/error_catalog_incident_dismiss_from_resolved
    """
    ctx = setup_lost_credential_incident("Dismiss House")
    incident = ctx["incident"]
    validate_success(api.start_incident_review(incident["id"], OFFICER))
    validate_success(api.resolve_incident(incident["id"],
                                          {"resolution_action": "NONE"}, OFFICER))
    assert get_incident(incident["id"])["status"] == "RESOLVED"

    resp = api.dismiss_incident(incident["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INCIDENT_INVALID_STATE)
    assert get_incident(incident["id"])["status"] == "RESOLVED"


def test_resolve_propped_incident_with_rekey_rejected(api):
    """PRD §3.4: "Three preconditions guard the resolve action in order:
    choosing `REQUEST_REKEY` requires the incident to be of `type`
    `LOST_CREDENTIAL` with a non-null `credential_id`, else
    `ERR_REKEY_REQUIRES_LOST_CREDENTIAL`; `REQUEST_REKEY` also requires the
    incident's `campaign_id` to still be null, else
    `ERR_CAMPAIGN_ALREADY_EXISTS`; and choosing `DEACTIVATE_CREDENTIAL` requires
    a non-null `credential_id`, else `ERR_INVALID_REQUEST`."

    Design: Corner/validations/resolve_propped_incident_with_rekey_rejected
    """
    ctx = setup_open_propped_alert("Propped Inc House", threshold=120,
                                   open_at="2026-08-01T08:00:00Z",
                                   detect_at="2026-08-01T08:03:00Z",
                                   alert_escalation_minutes=30)
    set_clock("2026-08-01T08:34:00Z")
    summary = get_success_data(api.run_ops(ctx["building"]["id"], OFFICER))
    assert summary["alerts_escalated"] == 1

    incident = get_propped_incident_for_door(ctx["door"]["id"])
    validate_success(api.start_incident_review(incident["id"], OFFICER))

    resp = api.resolve_incident(incident["id"], {"resolution_action": "REQUEST_REKEY"},
                                OFFICER)
    validate_error(resp, ApiErrorId.ERR_REKEY_REQUIRES_LOST_CREDENTIAL)
    assert get_incident(incident["id"])["status"] == "UNDER_REVIEW"


def test_second_rekey_request_on_same_incident_rejected(api):
    """PRD §3.4: "A reopened incident may be resolved again, but `REQUEST_REKEY`
    remains blocked because `campaign_id` is already set — this revision loop
    exists precisely to let operators correct or complete a resolution without
    ever spawning a duplicate campaign."
    PRD §3.4: "Resolving with `REQUEST_REKEY` creates a `RekeyCampaign` in
    `PROPOSED` status whose `key_node_id` is the lost credential's node, whose
    `incident_id` is this incident, whose `bill_to` is `PERSON` when
    `responsible_person_id` is set and `BUILDING` otherwise, whose
    `bill_person_id` mirrors `responsible_person_id`, and whose scope counts and
    estimate are computed at creation; the incident's `campaign_id` is set to
    the new campaign."

    Design: Corner/validations/second_rekey_request_on_same_incident_rejected
    """
    ctx = setup_lost_credential_incident("Double Rekey House")
    incident, change, staff = ctx["incident"], ctx["change"], ctx["person"]
    validate_success(api.start_incident_review(incident["id"], OFFICER))
    resolved = validate_success(api.resolve_incident(
        incident["id"], {"resolution_action": "REQUEST_REKEY"}, OFFICER))
    campaign_id = resolved["campaign_id"]
    assert campaign_id is not None

    campaign = validate_success(api.get_rekey_campaign(campaign_id, ADMIN))
    assert campaign["status"] == "PROPOSED"
    assert campaign["key_node_id"] == change["id"]
    assert campaign["bill_to"] == "PERSON"
    assert campaign["bill_person_id"] == staff["id"]

    validate_success(api.reopen_incident(incident["id"], OFFICER))
    resp = api.resolve_incident(incident["id"], {"resolution_action": "REQUEST_REKEY"},
                                OFFICER)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_ALREADY_EXISTS)
    assert get_incident(incident["id"])["status"] == "UNDER_REVIEW"


def test_incident_resolve_deactivate_credential_action(api):
    """PRD §3.4: "Resolving with `DEACTIVATE_CREDENTIAL` drives the linked
    credential — if it is currently `ISSUED` or `LOST` — to `DEACTIVATED` with
    `deactivated_reason` `INCIDENT`."

    Design: Corner/state_machines/incident_resolve_deactivate_credential_action
    """
    ctx = setup_lost_credential_incident("Deact House")
    incident, cred, change = ctx["incident"], ctx["credential"], ctx["change"]
    validate_success(api.start_incident_review(incident["id"], OFFICER))
    resolved = validate_success(api.resolve_incident(
        incident["id"],
        {"resolution_action": "DEACTIVATE_CREDENTIAL",
         "resolution_note": "Badge recovered and shredded"},
        OFFICER,
    ))
    assert resolved["status"] == "RESOLVED"
    assert resolved["campaign_id"] is None

    cred_after = get_credential(cred["id"])
    assert cred_after["status"] == "DEACTIVATED"
    assert cred_after["deactivated_reason"] == "INCIDENT"
    # Deactivating the credential does not un-compromise the node.
    assert get_key_node(change["id"])["status"] == "COMPROMISED"


# ---------------------------------------------------------------------------
# Difficulty: incident revision loop
# ---------------------------------------------------------------------------

def test_incident_review_resolve_reopen_dismiss_loop_states(api):
    """PRD §3.4: "Starting review moves `OPEN` → `UNDER_REVIEW` (from any other
    state, `ERR_INCIDENT_INVALID_STATE`)."
    PRD §3.4: "Resolved and dismissed incidents are not the end of the road:
    reopening moves `RESOLVED` → `UNDER_REVIEW` or `DISMISSED` → `UNDER_REVIEW`
    (from any other state, `ERR_INCIDENT_INVALID_STATE`), retaining the prior
    `resolution_action` and `resolution_note` for audit."

    Design: Difficulty/non_linear_state_machine/incident_review_resolve_reopen_dismiss_loop
    """
    ctx = setup_lost_credential_incident("Loop House")
    incident = ctx["incident"]

    reviewed = validate_success(api.start_incident_review(incident["id"], OFFICER))
    assert reviewed["status"] == "UNDER_REVIEW"

    resolved = validate_success(api.resolve_incident(
        incident["id"],
        {"resolution_action": "NONE", "resolution_note": "Key recovered by staff"},
        OFFICER,
    ))
    assert resolved["status"] == "RESOLVED"

    reopened = validate_success(api.reopen_incident(incident["id"], OFFICER))
    assert reopened["status"] == "UNDER_REVIEW"

    dismissed = validate_success(api.dismiss_incident(incident["id"], OFFICER))
    assert dismissed["status"] == "DISMISSED"


def test_incident_reopen_retains_prior_resolution_for_audit(api):
    """PRD §3.4: "Resolved and dismissed incidents are not the end of the road:
    reopening moves `RESOLVED` → `UNDER_REVIEW` or `DISMISSED` → `UNDER_REVIEW`
    (from any other state, `ERR_INCIDENT_INVALID_STATE`), retaining the prior
    `resolution_action` and `resolution_note` for audit."

    Design: Difficulty/non_linear_state_machine/incident_review_resolve_reopen_dismiss_loop
    """
    ctx = setup_lost_credential_incident("Loop House")
    incident = ctx["incident"]

    validate_success(api.start_incident_review(incident["id"], OFFICER))
    validate_success(api.resolve_incident(
        incident["id"],
        {"resolution_action": "NONE", "resolution_note": "Key recovered by staff"},
        OFFICER,
    ))
    reopened = validate_success(api.reopen_incident(incident["id"], OFFICER))
    assert reopened["status"] == "UNDER_REVIEW"
    assert reopened["resolution_action"] == "NONE"
    assert reopened["resolution_note"] == "Key recovered by staff"

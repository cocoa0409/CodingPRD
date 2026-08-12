"""Identity evidence verification, and the breach-alert triage axis."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, validate_paginated,
    ApiErrorId, assert_identity_document, assert_breach_alert, assert_same_instant,
    fixtures as fx,
)


def test_a_rejected_document_stays_invalid_and_cannot_then_be_verified(api):
    """PRD §3.5: "Rejection, a `PrivacyAgent` action, requires the document to be
    `PENDING`, records a `rejection_reason_code`, and moves it `PENDING → REJECTED`."
    PRD §3.5: "A document's `effective_status` is derived, not stored: it reads `VALID`
    when the document's status is `VERIFIED` **and** the current instant is strictly before
    `expires_at`, and `INVALID` in every other case."

    Rungs 18 and 19 are stated side by side in §2.6 without an adjudication for a row
    already sitting in a terminal state, so the follow-up verify is asserted against
    either faithful reading.

    Design: Corner/state_machines/identity_document_reject_branch_leaves_effective_status_invalid
    """
    household = fx.open_household()
    document = validate_success(api.create_identity_document(
        household["owner_id"],
        {"document_type": "DRIVERS_LICENSE", "document_reference": "DL-55231",
         "expires_at": "2026-12-01T00:00:00Z"},
        household["owner"]), 201)
    assert document["status"] == "PENDING"

    data = validate_success(api.reject_identity_document(document["id"],
                                                         "ILLEGIBLE_SCAN", fx.AGENT))

    assert_identity_document(data)
    assert data["status"] == "REJECTED"
    assert data["rejection_reason_code"] == "ILLEGIBLE_SCAN"
    assert data["verified_at"] is None
    # INVALID even though expires_at is far in the future — the status is not VERIFIED.
    assert data["effective_status"] == "INVALID"

    response = api.verify_identity_document(document["id"], fx.AGENT)
    validate_error_is_one_of(response, [ApiErrorId.ERR_ALREADY_TERMINAL.value,
                                        ApiErrorId.ERR_INVALID_STATE.value])
    assert response.status_code == 409

    _, meta = validate_paginated(api.list_member_identity_documents(
        household["owner_id"], household["owner"]))
    assert meta["total_count"] == 1


def test_a_platform_admin_can_verify_an_identity_document(api):
    """PRD §3.5: "Verification, available to a `PrivacyAgent` or `PlatformAdmin`, requires
    the document to be `PENDING` and the current instant to be **strictly before**
    `expires_at`; it stamps `verified_at` and moves the row `PENDING → VERIFIED`."

    Design: Corner/rbac/platform_admin_can_perform_the_shared_verify_operation
    """
    household = fx.open_household()
    document = validate_success(api.create_identity_document(
        household["owner_id"],
        {"document_type": "PASSPORT", "document_reference": "PASS-1",
         "expires_at": "2026-12-01T00:00:00Z"},
        fx.AGENT), 201)

    data = validate_success(api.verify_identity_document(document["id"], fx.ADMIN))

    assert data["status"] == "VERIFIED"
    assert_same_instant(data["verified_at"], "2026-05-01T00:00:00Z", "verified_at")
    assert data["effective_status"] == "VALID"

    _, meta = validate_paginated(api.list_member_identity_documents(
        household["owner_id"], household["owner"]))
    assert meta["total_count"] == 1


def test_alert_triage_runs_new_to_acknowledged_to_resolved_without_skipping(api):
    """PRD §3.6: "An alert starts `NEW`; acknowledging it — an action open to a
    `PrivacyAgent`, the `AccountOwner` or a `Member` — moves it `NEW → ACKNOWLEDGED` and
    stamps `acknowledged_at`. Resolving it, open to the `AccountOwner` or a `Member`, moves
    it `ACKNOWLEDGED → RESOLVED` and stamps `resolved_at`."
    PRD §2.6: "18. The target row is in a from-state for which a transition is declared for
    the requested trigger, otherwise `ERR_INVALID_STATE` (409). Applies to every
    state-transition endpoint."

    Design: Corner/state_machines/breach_alert_acknowledge_then_resolve_path
    """
    household = fx.open_household()
    profile = fx.draft_profile(household)
    fx.add_identifier(profile["id"], household["owner"],
                      identifier_type="EMAIL", identifier_value="dana@example.com")
    validate_success(api.activate_profile(profile["id"], household["owner"]))
    event = fx.create_breach_event(name="MailVault 2026",
                                   breach_date="2026-04-01T00:00:00Z",
                                   disclosed_at="2026-04-15T00:00:00Z",
                                   record_types=["EMAIL_ADDRESS"],
                                   base_severity_points=10)
    fx.ingest_breach(event["id"], ["dana@example.com"])
    rows, _ = fx.alerts_for_event(event["id"], household["owner"])
    alert = rows[0]
    assert_breach_alert(alert)
    # 10 base + 10 EMAIL_ADDRESS record points + 5 identifier bonus = 25, which is
    # exactly the MEDIUM floor.
    assert alert["severity_points"] == 25
    assert alert["severity"] == "MEDIUM"
    assert alert["status"] == "NEW"

    validate_error(api.resolve_alert(alert["id"], household["owner"]),
                   ApiErrorId.ERR_INVALID_STATE.value, 409)

    acknowledged = validate_success(api.acknowledge_alert(alert["id"],
                                                          household["owner"]))
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert_same_instant(acknowledged["acknowledged_at"], "2026-05-01T00:00:00Z",
                        "acknowledged_at")

    resolved = validate_success(api.resolve_alert(alert["id"], household["owner"]))
    assert resolved["status"] == "RESOLVED"
    assert_same_instant(resolved["resolved_at"], "2026-05-01T00:00:00Z", "resolved_at")
    # The triage axis never touches the severity axis.
    assert resolved["severity"] == "MEDIUM"
    assert resolved["escalation_count"] == 0

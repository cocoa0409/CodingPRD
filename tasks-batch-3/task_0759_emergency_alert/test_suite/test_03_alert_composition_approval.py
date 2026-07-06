"""Alert composition, submission preconditions, and the approval/revision workflow."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_approver_headers,
)
from test_helpers.fixtures import (
    create_group, compose_group_alert, add_localization,
)

ADMIN = TEST_USERS["contact_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
APPROVER = TEST_USERS["approver_headers"]


def test_compose_alert_invalid_severity_rejected(api):
    """PRD §3.3: "Composition supplies a `title`, a `severity` from the same four-value
    set, and a `channels` array naming the requested delivery channel types as a subset
    of `SMS`, `VOICE`, `EMAIL`, and `IPAWS`."
    PRD §2.11: "A malformed body, a missing required field, an invalid enum, or an
    out-of-range number is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/alert_invalid_severity_enum_rejected
    """
    payload = {
        "title": "X", "severity": "SEVERE", "channels": ["SMS"], "target_type": "GEO",
        "center_lat": 0.0, "center_lon": 0.0, "radius_m": 1000,
        "effective_from": "2026-03-10T00:00:00Z", "effective_until": "2026-03-11T00:00:00Z",
    }
    resp = api.create_alert(payload, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_submit_with_equal_window_rejected(api):
    """PRD §3.4: "Finally, `effective_from` must be strictly earlier than
    `effective_until`, or the submission is rejected with `ERR_INVALID_WINDOW`."

    Design: Corner/errors/invalid_window_on_submit
    """
    alert = get_success_data(api.create_alert({
        "title": "W", "severity": "WARNING", "channels": ["SMS"], "target_type": "GEO",
        "center_lat": 0.0, "center_lon": 0.0, "radius_m": 1000,
        "effective_from": "2026-03-10T00:00:00Z", "effective_until": "2026-03-10T00:00:00Z",
    }, DISPATCHER))
    add_localization(api, alert["id"], "EN", "W.")
    resp = api.submit_alert(alert["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


def test_submit_geo_alert_missing_circle_rejected(api):
    """PRD §3.4: "a geo alert must have all of `center_lat`, `center_lon`, and
    `radius_m` set; a targeting gap is rejected with `ERR_TARGET_REQUIRED`."

    Design: Corner/errors/target_required_on_submit_geo_missing_circle
    """
    alert = get_success_data(api.create_alert({
        "title": "G", "severity": "WARNING", "channels": ["SMS"], "target_type": "GEO",
        "effective_from": "2026-03-10T00:00:00Z", "effective_until": "2026-03-11T00:00:00Z",
    }, DISPATCHER))
    add_localization(api, alert["id"], "EN", "G.")
    resp = api.submit_alert(alert["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_TARGET_REQUIRED.value)


def test_approve_draft_alert_rejected_invalid_state(api):
    """PRD §3.4: "An `Approver` may approve a pending alert, advancing it
    `PENDING_APPROVAL → APPROVED`, but only if their `X-User-ID` differs from the
    alert's `author_user_id`".
    PRD §2.11: "After that comes state validity for the requested transition
    (`ERR_INVALID_STATE`, HTTP 409)".

    Design: Corner/state_machines/approve_from_draft_returns_invalid_state
    """
    alert = get_success_data(api.create_alert({
        "title": "D", "severity": "WARNING", "channels": ["SMS"], "target_type": "GEO",
        "center_lat": 0.0, "center_lon": 0.0, "radius_m": 1000,
        "effective_from": "2026-03-10T00:00:00Z", "effective_until": "2026-03-11T00:00:00Z",
    }, DISPATCHER))
    add_localization(api, alert["id"], "EN", "Draft.")
    resp = api.approve_alert(alert["id"], APPROVER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_author_cannot_approve_own_alert(api):
    """PRD §3.4: "a reviewer attempting to approve their own alert is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/author_cannot_approve_own_alert_segregation
    """
    group = create_group(api, name="G1")
    alert = compose_group_alert(api, group["id"], title="Warn")  # author_user_id = disp1
    add_localization(api, alert["id"], "EN", "Warning.")
    get_success_data(api.submit_alert(alert["id"], DISPATCHER))
    # Approver whose X-User-ID equals the author (disp1) is rejected.
    resp = api.approve_alert(alert["id"], make_approver_headers("disp1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_submit_with_draft_template_rejected(api):
    """PRD §3.4: "If the alert names a backing `template_id`, that template's `status`
    must be `PUBLISHED`, or the submission is rejected with `ERR_TEMPLATE_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/alert_submit_requires_published_template
    """
    template = get_success_data(api.create_template(
        {"name": "Tmpl", "default_severity": "WARNING", "body_by_language": {"EN": "Body."}}, ADMIN))
    group = create_group(api, name="G1")
    alert = compose_group_alert(api, group["id"], title="Warn", template_id=template["id"])
    add_localization(api, alert["id"], "EN", "Warning.")
    resp = api.submit_alert(alert["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHED.value)


def test_submit_succeeds_after_template_published(api):
    """PRD §3.3: "A template opens in `DRAFT` and may be published by a `ContactAdmin`,
    advancing it `DRAFT → PUBLISHED`; a template's `status` may also read `ARCHIVED`.
    Only a published template may back a submitted alert."
    PRD §3.4: "Once an alert is ready, its `Dispatcher` submits it for approval,
    advancing it `DRAFT → PENDING_APPROVAL`."

    Design: Difficulty/cross_entity_state_dependency/alert_submit_requires_published_template
    """
    template = get_success_data(api.create_template(
        {"name": "Tmpl", "default_severity": "WARNING", "body_by_language": {"EN": "Body."}}, ADMIN))
    group = create_group(api, name="G1")
    alert = compose_group_alert(api, group["id"], title="Warn", template_id=template["id"])
    add_localization(api, alert["id"], "EN", "Warning.")
    get_success_data(api.publish_template(template["id"], ADMIN))
    data = validate_success(api.submit_alert(alert["id"], DISPATCHER))
    assert data["status"] == "PENDING_APPROVAL", f"Expected PENDING_APPROVAL, got {data['status']}"


def test_reject_returns_alert_to_draft_and_bumps_revision(api):
    """PRD §3.4: "An `Approver` may instead reject a pending alert, advancing it
    `PENDING_APPROVAL → DRAFT` and incrementing the alert's `revision_count` by 1 so the
    dispatcher can revise and resubmit; an optional `reason` may accompany the rejection."

    Design: Difficulty/non_linear_state_machine/alert_revision_cycle_reject_to_draft
    """
    group = create_group(api, name="G1")
    alert = compose_group_alert(api, group["id"], title="Warn")
    add_localization(api, alert["id"], "EN", "Warning.")
    get_success_data(api.submit_alert(alert["id"], DISPATCHER))
    data = validate_success(api.reject_alert(alert["id"], {"reason": "Fix wording"}, APPROVER))
    assert data["status"] == "DRAFT", f"Expected DRAFT after reject, got {data['status']}"
    assert data["revision_count"] == 1, f"Expected revision_count 1, got {data['revision_count']}"


def test_resubmit_after_reject_returns_to_pending(api):
    """PRD §3.4: "This revision loop — pending back to draft and forward again — is
    exactly why a later dispatch is version-guarded."
    PRD §3.4: "Once an alert is ready, its `Dispatcher` submits it for approval,
    advancing it `DRAFT → PENDING_APPROVAL`."

    Design: Difficulty/non_linear_state_machine/alert_revision_cycle_reject_to_draft
    """
    group = create_group(api, name="G1")
    alert = compose_group_alert(api, group["id"], title="Warn")
    add_localization(api, alert["id"], "EN", "Warning.")
    get_success_data(api.submit_alert(alert["id"], DISPATCHER))
    get_success_data(api.reject_alert(alert["id"], {"reason": "Fix"}, APPROVER))
    data = validate_success(api.submit_alert(alert["id"], DISPATCHER))
    assert data["status"] == "PENDING_APPROVAL", f"Expected PENDING_APPROVAL after re-submit, got {data['status']}"

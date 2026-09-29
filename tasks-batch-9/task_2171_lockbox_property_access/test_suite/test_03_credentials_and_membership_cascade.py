"""Keyholder credentials, the membership cascade and its exact compensation."""

from test_helpers import (
    ApiErrorId,
    credential_action,
    credential_payload,
    issue_active_credential,
    issue_credential,
    member_event,
    read_credential,
    read_grant,
    read_lockbox,
    read_member,
    read_showing,
    register_association,
    enroll_member,
    setup_approved_grant,
    setup_association_with_agent,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    read_association,
    setup_confirmed_showing,
)


def test_credential_activation_is_refused_while_the_member_is_suspended(api, admin_headers):
    """PRD §3.3: "Activation moves a credential from `PENDING_ACTIVATION` to `ACTIVE`. It
    requires that the owning member's `membership_status` be `ACTIVE` or `PROBATION`,
    failing with `ERR_MEMBER_NOT_ELIGIBLE` otherwise, and that `expires_at` still be later
    than the current logical clock, failing with `ERR_INVALID_WINDOW` otherwise."

    Design: Difficulty/cross_entity_state_dependency/credential_activation_gated_by_member_membership_status
    """
    ctx = setup_association_with_agent()
    credential = issue_credential(ctx["agent_id"], credential_type="KEY_APP")
    member_event(ctx["agent_id"], "SUSPEND", reason="Ethics complaint")

    response = api.credential_state(
        credential["id"],
        {"action": "ACTIVATE", "expected_credential_version": credential["version"]},
        admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE.value)

    stored = read_credential(credential["id"])
    assert stored["status"] == "PENDING_ACTIVATION"


def test_credential_activates_once_the_member_is_reinstated(api, admin_headers):
    """PRD §3.3: "Activation moves a credential from `PENDING_ACTIVATION` to `ACTIVE`. It
    requires that the owning member's `membership_status` be `ACTIVE` or `PROBATION`,
    failing with `ERR_MEMBER_NOT_ELIGIBLE` otherwise, and that `expires_at` still be later
    than the current logical clock, failing with `ERR_INVALID_WINDOW` otherwise."
    PRD §3.3: "On success the member's `active_credential_count` rises by one."

    Design: Difficulty/cross_entity_state_dependency/credential_activation_gated_by_member_membership_status
    """
    ctx = setup_association_with_agent()
    credential = issue_credential(ctx["agent_id"], credential_type="KEY_APP")
    member_event(ctx["agent_id"], "SUSPEND", reason="Ethics complaint")
    api.credential_state(
        credential["id"],
        {"action": "ACTIVATE", "expected_credential_version": credential["version"]},
        admin_headers,
    )

    member_event(ctx["agent_id"], "REINSTATE")
    retry = api.credential_state(
        credential["id"],
        {"action": "ACTIVATE", "expected_credential_version": credential["version"]},
        admin_headers,
    )
    activated = validate_success(retry, 200)
    assert activated["status"] == "ACTIVE"

    member = read_member(ctx["agent_id"])
    assert member["membership_status"] == "ACTIVE"
    assert member["active_credential_count"] == 1


def test_member_suspension_drops_active_credential_count_to_zero(api, admin_headers):
    """PRD §3.2: "First, every credential belonging to that member that is currently
    `ACTIVE` becomes `SUSPENDED`, and each such credential is stamped `suspended_by_cascade`
    as true so the system can later tell a cascade casualty from a credential an
    administrator suspended deliberately; the member's `active_credential_count` is
    recomputed."

    Design: Difficulty/compensating_invariant/suspend_then_reinstate_conserves_active_credential_count
    """
    ctx = setup_association_with_agent()
    first = issue_active_credential(ctx["agent_id"], credential_type="KEY_APP")
    second = issue_active_credential(ctx["agent_id"], credential_type="KEY_FOB")

    before = read_member(ctx["agent_id"])
    assert before["active_credential_count"] == 2

    member_event(ctx["agent_id"], "SUSPEND", reason="Board review")

    during = read_member(ctx["agent_id"])
    assert during["membership_status"] == "SUSPENDED"
    assert during["active_credential_count"] == 0

    for credential_id in (first["id"], second["id"]):
        stored = read_credential(credential_id)
        assert stored["status"] == "SUSPENDED"
        assert stored["suspended_by_cascade"] is True


def test_member_reinstatement_restores_the_prior_active_credential_count(api, admin_headers):
    """PRD §3.2: "Every credential belonging to that member that is `SUSPENDED`, carries
    `suspended_by_cascade` as true, and whose `expires_at` is still in the future returns to
    `ACTIVE` with `suspended_by_cascade` cleared to false; the member's
    `active_credential_count` is recomputed and must land back on its pre-suspension value."

    Design: Difficulty/compensating_invariant/suspend_then_reinstate_conserves_active_credential_count
    """
    ctx = setup_association_with_agent()
    first = issue_active_credential(ctx["agent_id"], credential_type="KEY_APP")
    second = issue_active_credential(ctx["agent_id"], credential_type="KEY_FOB")
    member_event(ctx["agent_id"], "SUSPEND", reason="Board review")
    member_event(ctx["agent_id"], "REINSTATE")

    member = read_member(ctx["agent_id"])
    assert member["active_credential_count"] == 2
    assert member["membership_status"] == "ACTIVE"

    restored_first = read_credential(first["id"])
    assert restored_first["status"] == "ACTIVE"
    assert restored_first["suspended_by_cascade"] is False
    assert read_credential(second["id"])["status"] == "ACTIVE"

    rows, _ = validate_paginated(
        api.list_credentials(
            admin_headers, params={"member_id": ctx["agent_id"], "status": "ACTIVE"}
        )
    )
    assert len(rows) == 2


def test_member_suspension_revokes_credentials_and_the_grants_they_backed(api, admin_headers):
    """PRD §3.2: "First, every credential belonging to that member that is currently
    `ACTIVE` becomes `SUSPENDED`, and each such credential is stamped `suspended_by_cascade`
    as true so the system can later tell a cascade casualty from a credential an
    administrator suspended deliberately; the member's `active_credential_count` is
    recomputed. Second — precisely because those credentials have left `ACTIVE` — every
    grant the member issued that still sits in `REQUESTED` or `APPROVED` becomes `REVOKED`."

    Design: Difficulty/transitive_cascade/member_suspension_cascades_credential_to_grant_to_showing
    """
    ctx = setup_approved_grant(clock="2026-08-05T00:00:00Z", grant_type="INSPECTOR")
    credential = issue_active_credential(ctx["agent_id"], credential_type="KEY_FOB")
    setup_confirmed_showing(ctx, ctx["agent_id"])

    member_event(ctx["agent_id"], "SUSPEND", reason="Dues audit hold")

    member = read_member(ctx["agent_id"])
    assert member["membership_status"] == "SUSPENDED"
    assert member["active_credential_count"] == 0

    stored_credential = read_credential(credential["id"])
    assert stored_credential["status"] == "SUSPENDED"
    assert stored_credential["suspended_by_cascade"] is True

    assert read_grant(ctx["grant_id"])["status"] == "REVOKED"


def test_member_suspension_cancels_future_showings_without_touching_inventory(api, admin_headers):
    """PRD §3.2: "Third — precisely because those grants were revoked — every showing where
    the member is the attending agent that is still in `REQUESTED` or `CONFIRMED` and whose
    `window_start` is strictly after the current logical clock becomes `CANCELLED` with
    `cancel_reason` of `ACCESS_LOST`."
    PRD §2.9: "In each case the third hop cancels only future showings — a
    `ShowingAppointment` whose `window_start` is strictly later than the current logical
    clock — and stamps `cancel_reason` as `ACCESS_LOST` to distinguish it from a human
    cancellation, which stamps `AGENT_CANCELLED`."

    Design: Difficulty/transitive_cascade/member_suspension_cascades_credential_to_grant_to_showing
    """
    ctx = setup_approved_grant(clock="2026-08-05T00:00:00Z", grant_type="INSPECTOR")
    issue_active_credential(ctx["agent_id"], credential_type="KEY_FOB")
    setup_confirmed_showing(ctx, ctx["agent_id"])

    member_event(ctx["agent_id"], "SUSPEND", reason="Dues audit hold")

    appointment = read_showing(ctx["appointment_id"])
    assert appointment["status"] == "CANCELLED"
    assert appointment["cancel_reason"] == "ACCESS_LOST"

    lockbox = read_lockbox(ctx["lockbox_id"])
    assert lockbox["status"] == "PLACED", "the suspension cascade never touches inventory"
    assert read_association(ctx["association_id"])["posture"] == "OPEN"


def test_reinstatement_leaves_an_explicitly_suspended_credential_suspended(api, admin_headers):
    """PRD §3.2: "Credentials an administrator had suspended by hand stay `SUSPENDED`, and
    credentials whose `expires_at` has passed in the meantime stay `SUSPENDED` too."
    PRD §3.3: "An administrator may suspend an `ACTIVE` credential, which lowers
    `active_credential_count` by one and leaves `suspended_by_cascade` false because the
    suspension was deliberate."

    Design: Corner/state_machines/member_reinstate_leaves_explicitly_suspended_credential_suspended
    """
    ctx = setup_association_with_agent()
    cascade_credential = issue_active_credential(ctx["agent_id"], credential_type="KEY_APP")
    manual_credential = issue_active_credential(ctx["agent_id"], credential_type="KEY_FOB")
    credential_action(manual_credential["id"], "SUSPEND")

    member_event(ctx["agent_id"], "SUSPEND", reason="Board review")
    member_event(ctx["agent_id"], "REINSTATE")

    restored = read_credential(cascade_credential["id"])
    assert restored["status"] == "ACTIVE"
    assert restored["suspended_by_cascade"] is False

    untouched = read_credential(manual_credential["id"])
    assert untouched["status"] == "SUSPENDED"
    assert untouched["suspended_by_cascade"] is False

    member = read_member(ctx["agent_id"])
    assert member["active_credential_count"] == 1
    assert member["membership_status"] == "ACTIVE"


def test_credential_cap_supersedes_the_earliest_created_active_credential(api, admin_headers):
    """PRD §3.3: "If, at the moment of issuance, the member already holds a number of
    credentials in `ACTIVE` equal to `credential_cap_per_member`, the **earliest-created** of
    those active credentials — ordered by `created_at` ascending — is revoked to make room,
    and that revoked credential is stamped with a `supersede_reason` of
    `CREDENTIAL_CAP_SUPERSEDE`. The member's `active_credential_count` is recomputed
    accordingly."
    PRD §3.3: "It arrives in `PENDING_ACTIVATION` and does nothing until an administrator
    activates it."

    Design: Corner/cross_cutting_complexity_layers/credential_cap_supersede_revokes_earliest_active_credential
    """
    ctx = setup_association_with_agent()
    first = issue_active_credential(ctx["agent_id"], credential_type="KEY_APP")
    second = issue_active_credential(ctx["agent_id"], credential_type="KEY_FOB")

    member = read_member(ctx["agent_id"])
    response = api.create_credential(
        credential_payload(ctx["agent_id"], member["version"], credential_type="KEY_APP"),
        admin_headers,
    )
    third = validate_success(response, 201)
    assert third["status"] == "PENDING_ACTIVATION"

    superseded = read_credential(first["id"])
    assert superseded["status"] == "REVOKED"
    assert superseded["supersede_reason"] == "CREDENTIAL_CAP_SUPERSEDE"

    survivor = read_credential(second["id"])
    assert survivor["status"] == "ACTIVE"
    assert survivor.get("supersede_reason") is None

    assert read_member(ctx["agent_id"])["active_credential_count"] == 1

    rows, _ = validate_paginated(
        api.list_credentials(admin_headers, params={"member_id": ctx["agent_id"]})
    )
    assert len(rows) == 3


def test_stale_member_version_rejects_a_second_credential_issue(api, admin_headers):
    """PRD §2.5: "**Issuing an access credential.** A `POST /access-credentials` request
    must carry `expected_member_version` as a required field, holding the client's last
    observed `version` of the member named by `member_id`. If it does not equal that
    member's current `version`, the issuance is rejected with `ERR_STALE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_member_version_rejects_second_credential_issue
    """
    association = register_association()
    member = enroll_member(association["id"])
    observed_version = member["version"]

    first = validate_success(
        api.create_credential(
            credential_payload(member["id"], observed_version, credential_type="KEY_APP"),
            admin_headers,
        ),
        201,
    )

    stale = api.create_credential(
        credential_payload(member["id"], observed_version, credential_type="KEY_FOB"),
        admin_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

    rows, _ = validate_paginated(
        api.list_credentials(admin_headers, params={"member_id": member["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]

    refreshed = read_member(member["id"])
    retry = api.create_credential(
        credential_payload(member["id"], refreshed["version"], credential_type="KEY_FOB"),
        admin_headers,
    )
    validate_success(retry, 201)

    rows_after, _ = validate_paginated(
        api.list_credentials(admin_headers, params={"member_id": member["id"]})
    )
    assert len(rows_after) == 2
    assert read_member(member["id"])["active_credential_count"] == 0

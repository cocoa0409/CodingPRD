"""Where lifecycle rows begin, and which moves they refuse.

Declared initial states, an undeclared edge, a terminal row, a repeated trigger
and a precondition that a legal edge still has to satisfy.
"""

from test_helpers import (
    HR_ADMIN,
    PRIVACY_OFFICER,
    VENDOR_MANAGER,
    ApiErrorId,
    accommodations_for_consent,
    assert_asset_state,
    assert_instant_equals,
    assert_is_null,
    assert_program_state,
    baseline_with_active_asset,
    compliance_baseline,
    create_asset,
    create_consent,
    create_data_subject,
    create_jurisdiction,
    create_policy,
    create_program,
    create_vendor,
    create_vendor_contract,
    read_asset,
    read_consent,
    read_notice,
    read_policy,
    read_program,
    read_subject,
    set_clock,
    validate_error,
    validate_success,
)


def test_new_lifecycle_rows_are_born_in_their_declared_initial_states(api):
    """A policy, a collection point and a contract each start where they must.

    PRD §3.3: "A new policy sits in `DRAFT` with `published_at`,
    `submitted_by_user_id` and `published_by_user_id` null and `revision_count` at
    zero."

    PRD §3.5: "A newly inventoried point is `DISCOVERED`, with `pinned_policy_id`,
    `collection_started_at`, `purpose_satisfied_at`, `destruction_due_at` and
    `templates_destroyed_at` all null and `enrolled_subject_count` and
    `consent_gap_count` at zero."

    PRD §3.2: "Drafting records the acting `X-User-ID` as `drafted_by_user_id`,
    computes `compliance_score` immediately, and leaves the contract in `DRAFT` with
    `approved_by_user_id`, `terminated_at`, `deletion_deadline_at` and
    `deletion_certificate_ref` all null."

    PRD §3.5: "The numerator counts those points that satisfy three conditions
    simultaneously: status is `CLASSIFIED`, `ACTIVE` or `GATED`;
    `template_storage_location` is not the empty string; and either `vendor_id` is
    null or an executed contract exists for that vendor."

    The single inventoried point is still `DISCOVERED`, so it counts in the
    denominator and not in the numerator, and the program reads 0.00.

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])

    policy = create_policy(api, program["id"], [jurisdiction["id"]])
    asset = create_asset(api, program["id"], jurisdiction["id"])
    vendor = create_vendor(api, program["id"])
    contract = create_vendor_contract(api, vendor["id"])

    assert policy["status"] == "DRAFT"
    assert policy["revision_count"] == 0
    assert_is_null(policy["submitted_by_user_id"], "submitted_by_user_id on a draft policy")
    assert_is_null(policy["published_by_user_id"], "published_by_user_id on a draft policy")
    assert_is_null(policy["published_at"], "published_at on a draft policy")

    assert asset["status"] == "DISCOVERED"
    assert_asset_state(asset, enrolled_subject_count=0, consent_gap_count=0)
    assert_is_null(asset["pinned_policy_id"], "pinned_policy_id on a discovered point")
    assert_is_null(asset["collection_started_at"], "collection_started_at on a discovered point")
    assert_is_null(asset["purpose_satisfied_at"], "purpose_satisfied_at on a discovered point")
    assert_is_null(asset["destruction_due_at"], "destruction_due_at on a discovered point")
    assert_is_null(asset["templates_destroyed_at"], "templates_destroyed_at on a discovered point")

    assert contract["status"] == "DRAFT"
    assert contract["drafted_by_user_id"] == VENDOR_MANAGER["X-User-ID"]
    assert_is_null(contract["approved_by_user_id"], "approved_by_user_id on a draft contract")
    assert_is_null(contract["terminated_at"], "terminated_at on a draft contract")
    assert_is_null(contract["deletion_deadline_at"], "deletion_deadline_at on a draft contract")
    assert_is_null(
        contract["deletion_certificate_ref"], "deletion_certificate_ref on a draft contract"
    )

    assert_program_state(read_program(api, program["id"]), inventory_completeness_pct=0.00)


def test_retiring_a_draft_policy_is_not_a_declared_edge(api):
    """Retirement is reachable only from the superseded state.

    PRD §3.3: "The last edge closes the lifecycle: a `PrivacyOfficer` retires a
    superseded policy, `SUPERSEDED` → `RETIRED`, which is terminal."

    PRD §2.5: "The pair formed by the row's current status and the requested
    `to_status` must be a declared edge for that entity; and for consent lifecycle
    operations the target collection point must additionally be in a collectable
    status."

    The refused move writes nothing, so the row is still a first-version draft.

    Design: Corner/state_machines/policy_retire_from_draft_rejected
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    policy = create_policy(api, program["id"], [jurisdiction["id"]])

    refused = api.transition_policy(policy["id"], {"to_status": "RETIRED"}, PRIVACY_OFFICER)

    validate_error(refused, ApiErrorId.INVALID_TRANSITION)

    unchanged = read_policy(api, policy["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == 1


def test_a_declined_consent_record_accepts_no_further_moves(api):
    """Neither a late grant nor a re-solicitation can reopen a refusal.

    PRD §3.7: "An `HRAdministrator` moves a record `SOLICITED` → `DECLINED`, which is
    terminal for that record."

    PRD §2.5: "An undeclared edge — including a repeated trigger against an
    already-advanced or terminal row — yields `ERR_INVALID_TRANSITION`; a legal edge
    blocked only because the collection point is `DISCOVERED`, `CLASSIFIED` or
    `DECOMMISSIONED` yields `ERR_ASSET_NOT_COLLECTABLE` instead."

    The accommodation the decline handed the individual is untouched by the two
    refusals, and the individual is still recorded as having opted out.

    Design: Corner/state_machines/declined_consent_terminal_state_cannot_transition
    """
    ctx = baseline_with_active_asset(api, activation_clock="2026-08-15T00:00:00Z")
    subject = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001")
    consent = create_consent(api, subject["id"], ctx["asset_id"], target_status="DECLINED")

    late_grant = api.transition_consent_record(
        consent["id"],
        {"to_status": "GRANTED", "written_release_acknowledged": True, "signature_ref": "sig-late"},
        HR_ADMIN,
    )
    validate_error(late_grant, ApiErrorId.INVALID_TRANSITION)

    reopen = api.transition_consent_record(
        consent["id"], {"to_status": "RESOLICIT_REQUIRED"}, PRIVACY_OFFICER
    )
    validate_error(reopen, ApiErrorId.INVALID_TRANSITION)

    still_declined = read_consent(api, consent["id"])
    assert still_declined["status"] == "DECLINED"
    assert_is_null(still_declined["signed_at"], "signed_at on a declined record")

    rows = accommodations_for_consent(api, consent["id"])
    assert len(rows) == 1
    assert rows[0]["origin"] == "AUTO_DECLINE"
    assert rows[0]["status"] == "REQUESTED"
    assert rows[0]["method"] == "MANUAL_TIMESHEET"

    assert read_subject(api, subject["id"])["enrollment_status"] == "OPTED_OUT"
    assert_asset_state(read_asset(api, ctx["asset_id"]), enrolled_subject_count=0)


def test_republishing_a_notice_neither_succeeds_nor_restamps_it(api):
    """The publish trigger is not idempotent, and the second call changes nothing.

    PRD §2.5: "An undeclared edge — including a repeated trigger against an
    already-advanced or terminal row — yields `ERR_INVALID_TRANSITION`; a legal edge
    blocked only because the collection point is `DISCOVERED`, `CLASSIFIED` or
    `DECOMMISSIONED` yields `ERR_ASSET_NOT_COLLECTABLE` instead."

    PRD §3.4: "Successful publication stamps `published_at` from the current logical
    clock and computes `consent_eligible_from` as `published_at` plus the governing
    state profile's `notice_lead_days`."

    The clock is moved nineteen days on before the second attempt, so a stamp taken
    from it would be plainly visible; both instants keep the values the one real
    publication produced.

    Design: Corner/state_machines/republishing_an_already_published_notice_rejected
    """
    ctx = compliance_baseline(api)
    assert_instant_equals(ctx["notice"]["published_at"], "2026-08-01T00:00:00.000Z", "published_at")
    assert_instant_equals(
        ctx["notice"]["consent_eligible_from"], "2026-08-15T00:00:00.000Z", "consent_eligible_from"
    )

    set_clock(api, "2026-08-20T00:00:00Z")

    refused = api.transition_notice_packet(
        ctx["notice_id"], {"to_status": "PUBLISHED"}, PRIVACY_OFFICER
    )

    validate_error(refused, ApiErrorId.INVALID_TRANSITION)

    unchanged = read_notice(api, ctx["notice_id"])
    assert unchanged["status"] == "PUBLISHED"
    assert_instant_equals(unchanged["published_at"], "2026-08-01T00:00:00.000Z", "published_at")
    assert_instant_equals(
        unchanged["consent_eligible_from"], "2026-08-15T00:00:00.000Z", "consent_eligible_from"
    )


def test_granting_without_an_acknowledged_written_release_is_refused(api):
    """A signature alone does not satisfy a state that demands a release.

    PRD §3.6: "Three checks apply beyond the status itself: `signature_ref` must not
    be null, or the grant fails with `ERR_INVALID_REQUEST`; where the subject's state
    profile has `requires_written_release` true, `written_release_acknowledged` must
    be true, or the grant fails with `ERR_WRITTEN_RELEASE_REQUIRED`; and the
    collection point's status must be `ACTIVE` or `GATED`, or
    `ERR_ASSET_NOT_COLLECTABLE`."

    Re-issuing the very same move with the release acknowledged succeeds, so the
    release flag was the only thing standing in the way.

    Design: Corner/state_machines/consent_grant_without_written_release_rejected
    """
    ctx = baseline_with_active_asset(api, activation_clock="2026-08-15T00:00:00Z")
    subject = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001")
    consent = create_consent(
        api,
        subject["id"],
        ctx["asset_id"],
        written_release_acknowledged=False,
        signature_ref="sig-emp1-r1",
    )

    refused = api.transition_consent_record(consent["id"], {"to_status": "GRANTED"}, HR_ADMIN)

    validate_error(refused, ApiErrorId.WRITTEN_RELEASE_REQUIRED)

    unchanged = read_consent(api, consent["id"])
    assert unchanged["status"] == "SOLICITED"
    assert_is_null(unchanged["signed_at"], "signed_at after a refused grant")
    assert_is_null(unchanged["record_retention_until"], "record_retention_until after a refused grant")
    assert_asset_state(
        read_asset(api, ctx["asset_id"]), enrolled_subject_count=0, consent_gap_count=1
    )

    granted = validate_success(
        api.transition_consent_record(
            consent["id"], {"to_status": "GRANTED", "written_release_acknowledged": True}, HR_ADMIN
        )
    )
    assert granted["status"] == "GRANTED"

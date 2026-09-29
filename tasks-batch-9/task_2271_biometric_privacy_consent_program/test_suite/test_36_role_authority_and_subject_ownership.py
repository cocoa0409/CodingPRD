"""The role model from three angles.

An operator role's exclusive work closed to another operator, an entity-backed role
whose reach stops at its own rows, and that role's single permitted write.
"""

from test_helpers import (
    HR_ADMIN,
    PRIVACY_OFFICER,
    ApiErrorId,
    accommodations_for_consent,
    assert_asset_state,
    assert_instant_equals,
    assert_pagination,
    assert_program_state,
    baseline_with_active_asset,
    create_asset,
    create_consent,
    create_data_subject,
    create_jurisdiction,
    create_program,
    make_subject_headers,
    policy_payload,
    read_asset,
    read_program,
    read_subject,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

REVOCATION_REASON = "no longer comfortable with fingerprint clock-in"


def test_the_hr_administrator_may_neither_draft_a_policy_nor_move_a_collection_point(api):
    """Two officer-only operations, both refused on the role alone.

    PRD §2.1: "A request whose role is well-formed but not permitted for the operation is
    rejected with `ERR_FORBIDDEN_ROLE` (403)."

    PRD §2.5: "**Role authority.** The acting role is permitted for the endpoint, and on
    shared lifecycle endpoints permitted for the requested `to_status` per §2.1 —
    otherwise `ERR_FORBIDDEN_ROLE`."

    PRD §4: "| POST | `/policies` | Draft a written biometric policy version |
    PrivacyOfficer |"

    PRD §4: "| POST | `/biometric-assets/{asset_id}/transitions` | Drive the collection
    point lifecycle | PrivacyOfficer |"

    Both refused requests carry bodies that are otherwise perfectly valid — the identical
    two calls issued by the officer succeed — so the role is isolated as the only cause,
    and neither refusal leaves a trace: no policy row exists and the point has not moved.

    Design: Corner/rbac/hr_administrator_cannot_draft_a_policy_or_activate_an_asset
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    point = create_asset(api, program["id"], jurisdiction["id"])
    draft_body = policy_payload(program["id"], [jurisdiction["id"]])

    forbidden_draft = api.create_policy(draft_body, HR_ADMIN)
    forbidden_move = api.transition_asset(point["id"], {"to_status": "CLASSIFIED"}, HR_ADMIN)

    validate_error(forbidden_draft, ApiErrorId.FORBIDDEN_ROLE)
    validate_error(forbidden_move, ApiErrorId.FORBIDDEN_ROLE)

    _rows, meta = validate_paginated(
        api.list_policies(PRIVACY_OFFICER, {"program_id": program["id"]})
    )
    assert_pagination(meta, total_count=0, has_more=False, limit=10, offset=0)
    assert read_asset(api, point["id"])["status"] == "DISCOVERED"

    permitted_draft = validate_success(
        api.create_policy(draft_body, PRIVACY_OFFICER), expected_status=201
    )
    assert permitted_draft["status"] == "DRAFT"
    permitted_move = validate_success(
        api.transition_asset(point["id"], {"to_status": "CLASSIFIED"}, PRIVACY_OFFICER)
    )
    assert permitted_move["status"] == "CLASSIFIED"


def test_a_data_subject_reaches_its_own_rows_and_no_siblings(api):
    """Ownership is checked per row, so the same endpoint answers differently.

    PRD §2.1: "When `X-User-Role` is `Subject`, by contrast, `X-User-ID` is the `id` of the
    acting `DataSubject`; ownership checks on any resource that references a `DataSubject`
    compare that resource's subject reference to `X-User-ID`. A `Subject` may read its own
    subject profile, its own consent records and its own accommodations, and may revoke
    its own granted consent; when the referenced resource belongs to a different
    individual the request is rejected with `ERR_SUBJECT_MISMATCH` (403)."

    PRD §2.5: "**Subject ownership.** When the acting role is `Subject`, `X-User-ID` must
    equal the `DataSubject` `id` that owns the target row — otherwise
    `ERR_SUBJECT_MISMATCH`."

    PRD §4: "| GET | `/consent-records/{consent_id}` | Read one consent record |
    SystemOperator, PrivacyOfficer, ComplianceApprover, HRAdministrator, Subject |"

    PRD §4: "| GET | `/data-subjects/{subject_id}` | Read one data subject with derived
    enrollment status | SystemOperator, PrivacyOfficer, ComplianceApprover,
    HRAdministrator, Subject |"

    The sibling's rows genuinely exist — the officer reads both of them without trouble —
    so the refusal is an ownership judgement and not a missing row, which is why it is a
    403 rather than a 404.

    Design: Corner/rbac/subject_reading_another_subjects_consent_is_forbidden
    """
    ctx = baseline_with_active_asset(api, activation_clock=None)
    first = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001")
    second = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0002")
    set_clock(api, "2026-08-15T00:00:00Z")
    own_consent = create_consent(api, first["id"], ctx["asset_id"])
    sibling_consent = create_consent(api, second["id"], ctx["asset_id"])
    acting_as_first = make_subject_headers(first["id"])

    own = validate_success(api.get_consent_record(own_consent["id"], acting_as_first))
    assert own["id"] == own_consent["id"]
    assert own["status"] == "SOLICITED"
    assert own["data_subject_id"] == first["id"]

    sibling_row = api.get_consent_record(sibling_consent["id"], acting_as_first)
    sibling_profile = api.get_data_subject(second["id"], acting_as_first)

    validate_error(sibling_row, ApiErrorId.SUBJECT_MISMATCH)
    validate_error(sibling_profile, ApiErrorId.SUBJECT_MISMATCH)

    officer_row = validate_success(api.get_consent_record(sibling_consent["id"], PRIVACY_OFFICER))
    assert officer_row["id"] == sibling_consent["id"]
    officer_profile = validate_success(api.get_data_subject(second["id"], PRIVACY_OFFICER))
    assert officer_profile["id"] == second["id"]


def test_a_data_subject_revokes_its_own_grant_and_is_handed_an_alternative(api):
    """The role's one write, with the compensation it triggers.

    PRD §3.6: "It sets `record_retention_until` to `signed_at` plus 1,095 days — three
    years — which is the statutory floor for keeping the consent record itself, entirely
    independent of when the templates are destroyed."

    PRD §3.7: "A granted consent may be withdrawn at any time, by an `HRAdministrator` or
    by the `Subject` acting on their own record; a `Subject` whose `X-User-ID` is not the
    record's `data_subject_id` is rejected with `ERR_SUBJECT_MISMATCH`. The move `GRANTED`
    → `REVOKED` requires a `revocation_reason` in the request body, else
    `ERR_INVALID_REQUEST`. It auto-creates one accommodation with `origin` set to
    `AUTO_REVOKE`, `created_from_consent_id` set to the revoked record, status
    `REQUESTED`, `method` from the same mapping, `starts_at` at the current logical clock
    and `ends_at` ninety days later. It then decrements the point's
    `enrolled_subject_count`, recomputes its `consent_gap_count`, re-derives the subject's
    `enrollment_status` to `OPTED_OUT`, and recomputes the program's `consent_gap_count`
    and `posture`."

    PRD §3.7: "A `TIMEKEEPING` surface maps to `MANUAL_TIMESHEET`."

    PRD §2.9: "`consent_gap_count` on a collection point is the count of its consent
    records whose status is `SOLICITED`, `RESOLICIT_REQUIRED` or `EXPIRED` — a `DECLINED`
    record and a `REVOKED` record are lawful outcomes and are explicitly **not** gaps"

    The individual acts on their own record, so the ownership check passes and the write
    lands. Withdrawal is a lawful outcome rather than an unresolved one, which is why the
    program returns to `OPEN` even though the individual is no longer enrolled.

    Design: Corner/rbac/subject_revokes_own_granted_consent_and_receives_an_auto_accommodation
    """
    ctx = baseline_with_active_asset(api, activation_clock=None)
    subject = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001")
    set_clock(api, "2026-08-15T00:00:00Z")
    consent = create_consent(
        api,
        subject["id"],
        ctx["asset_id"],
        target_status="GRANTED",
        written_release_acknowledged=True,
        signature_ref="sig-emp1",
    )
    assert_instant_equals(consent["signed_at"], "2026-08-15T00:00:00.000Z", "signed_at")
    assert_instant_equals(
        consent["record_retention_until"], "2029-08-14T00:00:00.000Z", "record_retention_until"
    )
    assert_asset_state(read_asset(api, ctx["asset_id"]), enrolled_subject_count=1)

    revoked = validate_success(
        api.transition_consent_record(
            consent["id"],
            {"to_status": "REVOKED", "revocation_reason": REVOCATION_REASON},
            make_subject_headers(subject["id"]),
        )
    )

    assert revoked["status"] == "REVOKED"
    assert revoked["revocation_reason"] == REVOCATION_REASON

    spawned = accommodations_for_consent(api, consent["id"])
    assert len(spawned) == 1, f"expected exactly one spawned accommodation, got {len(spawned)}"
    alternative = spawned[0]
    assert alternative["origin"] == "AUTO_REVOKE"
    assert alternative["method"] == "MANUAL_TIMESHEET"
    assert alternative["status"] == "REQUESTED"
    assert alternative["created_from_consent_id"] == consent["id"]
    assert_instant_equals(alternative["starts_at"], "2026-08-15T00:00:00.000Z", "starts_at")
    assert_instant_equals(alternative["ends_at"], "2026-11-13T00:00:00.000Z", "ends_at")

    assert_asset_state(
        read_asset(api, ctx["asset_id"]), enrolled_subject_count=0, consent_gap_count=0
    )
    assert read_subject(api, subject["id"])["enrollment_status"] == "OPTED_OUT"
    assert_program_state(read_program(api, ctx["program_id"]), consent_gap_count=0, posture="OPEN")

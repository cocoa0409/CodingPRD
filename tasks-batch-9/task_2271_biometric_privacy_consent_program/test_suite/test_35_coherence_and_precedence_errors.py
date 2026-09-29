"""Five refusals that come from the relationships between rows, not from one row.

A point blocked by its own outstanding consent, an individual protected by the wrong
state's statute, a contract missing a clause, and two refusals that must name the
higher-priority rule when two rules are broken at once.
"""

from test_helpers import (
    COMPLIANCE_APPROVER,
    HR_ADMIN,
    PRIVACY_OFFICER,
    VENDOR_MANAGER,
    ApiErrorId,
    assert_asset_state,
    assert_instant_equals,
    assert_is_null,
    assert_pagination,
    assert_program_state,
    assert_two_decimal_value,
    baseline_with_active_asset,
    compliance_baseline,
    consent_payload,
    create_asset,
    create_consent,
    create_data_subject,
    create_jurisdiction,
    create_program,
    create_published_notice,
    create_published_policy,
    create_vendor,
    create_vendor_contract,
    read_asset,
    read_contract,
    read_program,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

WASHINGTON = {
    "state_code": "WA",
    "statute_name": "My Health My Data",
    "private_right_of_action": "LIMITED",
    "damages_model": "STATUTORY_PER_VIOLATION",
    "requires_written_release": False,
    "translation_required": False,
    "required_locales": ["en"],
    "retention_max_days": 730,
    "notice_lead_days": 0,
    "per_violation_negligent_cents": 50000,
    "per_violation_reckless_cents": 200000,
    "cure_period_days": 30,
}

WASHINGTON_DOOR_READER = {
    "system_category": "ACCESS_CONTROL",
    "modality": "HAND_GEOMETRY",
    "template_storage_location": "door-vault-wa",
}


def test_a_gated_point_is_held_shut_by_its_own_consent_gap_not_by_the_posture(api):
    """Restriction permits revival; the point's own unresolved consent does not.

    PRD §3.5: "The reverse edge, `GATED` → `ACTIVE`, is a `PrivacyOfficer` revival and is
    what makes this machine cyclic. It requires that the program's `posture` is not
    `FROZEN` (else `ERR_PROGRAM_POSTURE_BLOCKED`); that the point's own
    `consent_gap_count` is exactly zero, so that no individual is left in an unresolved
    consent state at a point about to resume collecting (else `ERR_CONSENT_GAP_OPEN`);
    and, when a vendor operates the point, that the vendor still has an `EXECUTED`
    contract whose `compliance_score` is at least 82.50 (else
    `ERR_CONTRACT_SCORE_BELOW_FLOOR`). Revival recomputes `destruction_due_at` from the
    original collection start, then `gated_asset_count` and `posture`."

    PRD §2.6: "`RESTRICTED` deliberately does **not** block the re-activation of a `GATED`
    collection point — otherwise a gated point could never recover, because gating is
    itself one of the conditions that produces `RESTRICTED`."

    PRD §3.6: "and the collection point's status must be `ACTIVE` or `GATED`, or
    `ERR_ASSET_NOT_COLLECTABLE`."

    PRD §3.5: "Because `collection_started_at` is stamped once and only once, a
    re-activation recomputes the horizon from the **original** start of collection and
    never restarts the retention clock — a point that is gated and revived does not get a
    fresh retention allowance."

    The program is `RESTRICTED` at the moment of the refusal, so the refusal cannot be the
    posture gate. Granting is still available while the point is gated, which is what lets
    the gap be closed at all; once it is closed the identical revival succeeds, and the
    horizon returns to thirty days after the 2026-08-01 start rather than thirty days
    after the 2026-08-15 revival.

    Design: Corner/errors/reactivating_a_gated_asset_with_an_open_consent_gap_rejected
    """
    ctx = baseline_with_active_asset(api, activation_clock=None)
    subject = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001")
    set_clock(api, "2026-08-15T00:00:00Z")
    consent = create_consent(
        api,
        subject["id"],
        ctx["asset_id"],
        written_release_acknowledged=True,
        signature_ref="sig-emp1",
    )
    gated = validate_success(
        api.transition_asset(ctx["asset_id"], {"to_status": "GATED"}, PRIVACY_OFFICER)
    )
    assert_asset_state(gated, status="GATED", consent_gap_count=1)

    refused = api.transition_asset(ctx["asset_id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER)

    validate_error(refused, ApiErrorId.CONSENT_GAP_OPEN)
    assert_program_state(read_program(api, ctx["program_id"]), posture="RESTRICTED")
    assert read_asset(api, ctx["asset_id"])["status"] == "GATED"

    granted = validate_success(
        api.transition_consent_record(consent["id"], {"to_status": "GRANTED"}, HR_ADMIN)
    )
    assert granted["status"] == "GRANTED"
    assert_asset_state(read_asset(api, ctx["asset_id"]), consent_gap_count=0)

    revived = validate_success(
        api.transition_asset(ctx["asset_id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER)
    )
    assert_asset_state(
        revived,
        status="ACTIVE",
        collection_started_at="2026-08-01T00:00:00.000Z",
        destruction_due_at="2026-08-31T00:00:00.000Z",
    )
    assert_program_state(
        read_program(api, ctx["program_id"]), gated_asset_count=0, consent_gap_count=0, posture="OPEN"
    )


def test_an_illinois_employee_cannot_be_enrolled_at_a_washington_reader(api):
    """One program and one policy, yet the state boundary still holds.

    PRD §3.6: "The subject's `jurisdiction_id` must equal the collection point's
    `jurisdiction_id`, else `ERR_JURISDICTION_MISMATCH`; and the subject's `subject_type`
    must equal the point's `subject_class`, else `ERR_SUBJECT_CLASS_MISMATCH`."

    PRD §2.9: "`consent_gap_count` on a collection point is the count of its consent
    records whose status is `SOLICITED`, `RESOLICIT_REQUIRED` or `EXPIRED` — a `DECLINED`
    record and a `REVOKED` record are lawful outcomes and are explicitly **not** gaps, and
    a registered data subject who has no consent record at all is likewise not a gap until
    a record is actually solicited."

    PRD §2.6: "4. Otherwise `posture` becomes `OPEN`. A program with no collection points,
    no contracts and no final assessments is therefore `OPEN`."

    The two individuals share a program, a published policy that names both states and a
    published notice apiece, so nothing upstream of the state comparison is missing:
    Washington's packet carries a zero-day lead, so even the cooling-off rule is satisfied
    at the moment of the request. The refusal writes nothing, which is why the reader
    still reports no gap and the program is still open.

    Design: Corner/errors/consent_for_a_subject_in_another_state_rejected
    """
    program = create_program(api)
    illinois = create_jurisdiction(api, program["id"])
    washington = create_jurisdiction(api, program["id"], **WASHINGTON)
    policy = create_published_policy(api, program["id"], [illinois["id"], washington["id"]])
    create_published_notice(api, program["id"], illinois["id"], policy["id"])
    create_published_notice(
        api, program["id"], washington["id"], policy["id"], locales=["en"]
    )
    washington_reader = create_asset(
        api,
        program["id"],
        washington["id"],
        target_status="ACTIVE",
        **WASHINGTON_DOOR_READER,
    )
    illinois_employee = create_data_subject(api, program["id"], illinois["id"], "EMP-0001")

    mismatch = api.create_consent_record(
        consent_payload(illinois_employee["id"], washington_reader["id"]), HR_ADMIN
    )

    validate_error(mismatch, ApiErrorId.JURISDICTION_MISMATCH)

    _rows, meta = validate_paginated(
        api.list_consent_records(HR_ADMIN, {"asset_id": washington_reader["id"]})
    )
    assert_pagination(meta, total_count=0, has_more=False, limit=10, offset=0)
    assert_asset_state(read_asset(api, washington_reader["id"]), consent_gap_count=0)
    assert_program_state(read_program(api, program["id"]), posture="OPEN")


def test_a_contract_missing_the_sale_prohibition_cannot_be_approved(api):
    """The three clauses are a conjunction checked before the score is consulted.

    PRD §3.2: "Otherwise a `ComplianceApprover` moves it `DRAFT` → `APPROVED`; that
    approval demands an `X-User-ID` different from `drafted_by_user_id` (else
    `ERR_SEGREGATION_OF_DUTIES`) and demands that all three clauses — `prohibits_sale`,
    `restricts_disclosure` and `requires_deletion_on_termination` — are true, rejecting an
    incomplete clause set with `ERR_VENDOR_CONTRACT_NONCOMPLIANT`. Approval stamps
    `approved_by_user_id` from the acting `X-User-ID` and recomputes `compliance_score`."

    PRD §3.2: "A `VendorManager` may abandon it, moving `DRAFT` → `VOID`, which is
    terminal."

    Only the sale prohibition is missing; the other two clauses are present and the
    processor's attestation is already received. Abandoning the defective draft and
    submitting a complete one succeeds against the very same processor, so the refusal
    attaches to the paperwork rather than to the vendor.

    Design: Corner/errors/contract_missing_a_required_clause_cannot_be_approved
    """
    program = create_program(api)
    vendor = create_vendor(
        api, program["id"], attestation_status="RECEIVED", name="GateWorks Access"
    )
    defective = create_vendor_contract(api, vendor["id"], prohibits_sale=False)

    refused = api.transition_vendor_contract(
        defective["id"], {"to_status": "APPROVED"}, COMPLIANCE_APPROVER
    )

    validate_error(refused, ApiErrorId.VENDOR_CONTRACT_NONCOMPLIANT)
    unchanged = read_contract(api, defective["id"])
    assert unchanged["status"] == "DRAFT"
    assert_is_null(unchanged["approved_by_user_id"], "approved_by_user_id after a refused approval")

    abandoned = validate_success(
        api.transition_vendor_contract(defective["id"], {"to_status": "VOID"}, VENDOR_MANAGER)
    )
    assert abandoned["status"] == "VOID"

    replacement = create_vendor_contract(api, vendor["id"])
    approved = validate_success(
        api.transition_vendor_contract(
            replacement["id"], {"to_status": "APPROVED"}, COMPLIANCE_APPROVER
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == COMPLIANCE_APPROVER["X-User-ID"]


def test_soliciting_at_an_undocumented_point_names_collectability_over_the_lead_time(api):
    """Two rules are broken at once and the lower-numbered one is reported.

    PRD §3.6: "The collection point must be in a collectable status — `ACTIVE` or `GATED`
    — else `ERR_ASSET_NOT_COLLECTABLE`."

    PRD §2.5: "A request that violates more than one rule always reports the violation
    with the lowest priority number below."

    PRD §2.5: "**Transition legality.** The pair formed by the row's current status and
    the requested `to_status` must be a declared edge for that entity; and for consent
    lifecycle operations the target collection point must additionally be in a collectable
    status. An undeclared edge — including a repeated trigger against an
    already-advanced or terminal row — yields `ERR_INVALID_TRANSITION`; a legal edge
    blocked only because the collection point is `DISCOVERED`, `CLASSIFIED` or
    `DECOMMISSIONED` yields `ERR_ASSET_NOT_COLLECTABLE` instead."

    PRD §2.5: "**Time-window rules**: notice lead time not yet elapsed
    (`ERR_NOTICE_LEAD_NOT_MET`), overlapping published notice windows
    (`ERR_NOTICE_WINDOW_OVERLAP`), colliding accommodation windows
    (`ERR_ACCOMMODATION_WINDOW_CONFLICT`), and close-out attempted after the deletion
    deadline (`ERR_DELETION_DEADLINE_MISSED`)."

    The clock is still at the publication instant while the packet does not open
    solicitation until fourteen days later, so the cooling-off rule at priority eleven is
    genuinely broken too — and must not be the one reported, because collectability sits
    at priority eight.

    Design: Corner/errors/consent_creation_on_a_classified_asset_is_rejected_as_not_collectable
    """
    ctx = compliance_baseline(api)
    assert_instant_equals(
        ctx["notice"]["consent_eligible_from"],
        "2026-08-15T00:00:00.000Z",
        "consent_eligible_from",
    )
    point = create_asset(
        api, ctx["program_id"], ctx["jurisdiction_id"], target_status="CLASSIFIED"
    )
    subject = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001")

    refused = api.create_consent_record(consent_payload(subject["id"], point["id"]), HR_ADMIN)

    validate_error(refused, ApiErrorId.ASSET_NOT_COLLECTABLE)

    _rows, meta = validate_paginated(
        api.list_consent_records(HR_ADMIN, {"asset_id": point["id"]})
    )
    assert_pagination(meta, total_count=0, has_more=False, limit=10, offset=0)
    assert_asset_state(read_asset(api, point["id"]), status="CLASSIFIED", consent_gap_count=0)


def test_activating_in_a_state_the_policy_never_named_reports_no_published_policy(api):
    """A published notice is not enough when the policy's scope stops at the border.

    PRD §3.5: "Exactly one policy under the point's program must have status `PUBLISHED`
    and list the point's `jurisdiction_id` in its `jurisdiction_scope`, else
    `ERR_POLICY_NOT_PUBLISHED`."

    PRD §3.5: "Activation then pins `pinned_policy_id` to that single published in-scope
    policy, stamps `collection_started_at` from the current logical clock **only when it
    is currently null** — that is, on the very first activation and never again —
    computes `destruction_due_at`, and recomputes the program's `consent_gap_count`, its
    inventory completeness and its `posture`."

    PRD §3.5: "The numerator counts those points that satisfy three conditions
    simultaneously: status is `CLASSIFIED`, `ACTIVE` or `GATED`; `template_storage_location`
    is not the empty string; and either `vendor_id` is null or an executed contract exists
    for that vendor."

    The Washington notice is genuinely published and reproduces a genuinely published
    policy — that policy simply never listed Washington in its scope, and a notice cannot
    supply the authority the policy withheld. The point stays classified and therefore
    still counts as fully documented, which is the point: completeness is not authority.

    Design: Corner/errors/activating_an_asset_in_an_unscoped_state_is_rejected_as_policy_not_published
    """
    program = create_program(api)
    illinois = create_jurisdiction(api, program["id"])
    washington = create_jurisdiction(api, program["id"], **WASHINGTON)
    illinois_only_policy = create_published_policy(api, program["id"], [illinois["id"]])
    create_published_notice(
        api, program["id"], washington["id"], illinois_only_policy["id"], locales=["en"]
    )
    washington_reader = create_asset(
        api,
        program["id"],
        washington["id"],
        target_status="CLASSIFIED",
        **WASHINGTON_DOOR_READER,
    )

    refused = api.transition_asset(
        washington_reader["id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER
    )

    validate_error(refused, ApiErrorId.POLICY_NOT_PUBLISHED)

    unchanged = read_asset(api, washington_reader["id"])
    assert unchanged["status"] == "CLASSIFIED"
    assert_is_null(unchanged["pinned_policy_id"], "pinned_policy_id after a refused activation")
    assert_is_null(unchanged["collection_started_at"], "collection_started_at after a refusal")
    assert_is_null(unchanged["destruction_due_at"], "destruction_due_at after a refusal")
    assert_two_decimal_value(
        read_program(api, program["id"])["inventory_completeness_pct"],
        100.00,
        "inventory_completeness_pct",
    )

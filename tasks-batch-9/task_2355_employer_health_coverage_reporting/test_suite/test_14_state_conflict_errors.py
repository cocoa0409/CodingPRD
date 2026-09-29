"""State-conflict rejections across the reporting season.

Each test drives one entity into a state that forbids the operation under test and
asserts the exact conflict code the PRD names for it, together with the fact that
the refused call left the world untouched.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER_2_USER_ID,
    PREPARER_2_USER_ID,
    factories,
    fixtures,
    get_success_data,
    make_benefits_admin_headers,
    make_compliance_officer_headers,
    make_employee_self_service_headers,
    make_preparer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CO = make_compliance_officer_headers()
CO_2 = make_compliance_officer_headers(COMPLIANCE_OFFICER_2_USER_ID)
BA = make_benefits_admin_headers()
PREPARER = make_preparer_headers()
PREPARER_2 = make_preparer_headers(PREPARER_2_USER_ID)

FURNISHING_WINDOW_OPEN_UTC = "2027-02-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Local compositions of the shared fixtures
# ---------------------------------------------------------------------------
def _group_with_statement(api):
    """Season, determined-ALE group, one member, one employee, one statement."""
    ctx = fixtures.determined_ale_group_with_employee(api)
    ctx["form"] = fixtures.generate_form(api, ctx["employee"]["id"])
    return ctx


def _errored_transmittal(api, severity, error_code, receipt_id):
    """Carry one statement to the agency and record a response bearing one error
    row of the given severity. Returns the context plus the error row."""
    ctx = _group_with_statement(api)
    built = fixtures.built_transmittal_with_forms(api, ctx["member"]["id"], [ctx["form"]["id"]])
    fixtures.transmit_transmittal(api, built["id"], "ELECTRONIC")
    fixtures.record_agency_response(
        api,
        built["id"],
        "ACCEPTED_WITH_ERRORS",
        receipt_id,
        errors=[
            factories.agency_error_row(
                ctx["form"]["id"], error_code=error_code, severity=severity
            )
        ],
    )
    ctx["transmittal"] = fixtures.read_transmittal(api, built["id"])
    rows = get_success_data(
        api.list_transmittal_errors(PREPARER, params={"transmittal_id": built["id"]})
    )
    assert len(rows) == 1, f"expected one agency error row, got {len(rows)}"
    ctx["error_row"] = rows[0]
    return ctx


def _locked_season_group(api):
    """The prelude with no employees and no transmittals, then a locked season so
    the cascade drives the group to LOCKED."""
    ctx = fixtures.determined_ale_group(api)
    get_success_data(api.lock_filing_season(ctx["season"]["id"], CO))
    return ctx


# ---------------------------------------------------------------------------
# Locked determination blocks structural member writes
# ---------------------------------------------------------------------------
def test_patch_group_member_after_group_locked_rejected(api):
    """PRD §2.6: "The governing controlled group is not `LOCKED` —
    `ERR_DETERMINATION_LOCKED` (409), on ale-determination, reopen, form
    generation, `POST /ale-reporting/group-members` and
    `PATCH /ale-reporting/group-members/{member_id}`."
    PRD §3.1: "Because member creation and amendment are structural rather than
    filing writes, they are not covered by the season gate; they are refused with
    `ERR_DETERMINATION_LOCKED` when the group has already reached `LOCKED`, which
    is the observable difference between that code and `ERR_SEASON_LOCKED`."
    PRD §2.10: "Locking sets `locked_at` from the logical clock and cascades:
    every controlled group of the season sitting in `DETERMINED_ALE` or
    `DETERMINED_NON_ALE` moves to `LOCKED`, after which no further determination,
    form generation or transmission is accepted for that group."

    Design: Corner/Errors/patch_group_member_after_group_locked_rejected
    """
    ctx = _locked_season_group(api)
    member_before = fixtures.read_member(api, ctx["member"]["id"])

    response = api.update_group_member(
        ctx["member"]["id"], {"member_status": "INACTIVE"}, CO
    )
    validate_error(response, ApiErrorId.ERR_DETERMINATION_LOCKED, 409)

    assert fixtures.read_season(api, ctx["season"]["id"])["status"] == "LOCKED", (
        "the season should be LOCKED after the lock call"
    )
    assert fixtures.read_group(api, ctx["group"]["id"])["determination_state"] == "LOCKED", (
        "the lock cascade should have driven the determined group to LOCKED"
    )
    member_after = fixtures.read_member(api, ctx["member"]["id"])
    assert member_after["member_status"] == "ACTIVE", (
        f"member_status should stay ACTIVE, got {member_after['member_status']}"
    )
    assert member_after["version"] == member_before["version"], (
        "a refused amendment must not advance the member's version"
    )


def test_create_group_member_after_group_locked_rejected(api):
    """PRD §2.6: "The governing controlled group is not `LOCKED` —
    `ERR_DETERMINATION_LOCKED` (409), on ale-determination, reopen, form
    generation, `POST /ale-reporting/group-members` and
    `PATCH /ale-reporting/group-members/{member_id}`."
    PRD §3.1: "Because member creation and amendment are structural rather than
    filing writes, they are not covered by the season gate; they are refused with
    `ERR_DETERMINATION_LOCKED` when the group has already reached `LOCKED`, which
    is the observable difference between that code and `ERR_SEASON_LOCKED`."

    Design: Corner/Errors/patch_group_member_after_group_locked_rejected
    """
    ctx = _locked_season_group(api)

    response = api.create_group_member(
        factories.group_member_payload(ctx["group"]["id"], "999999999"), CO
    )
    validate_error(response, ApiErrorId.ERR_DETERMINATION_LOCKED, 409)

    members, meta = validate_paginated(
        api.list_group_members(CO, params={"controlled_group_id": ctx["group"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the refused create must add no member, got total_count {meta['total_count']}"
    )
    assert [m["ein"] for m in members] == ["123456789"], (
        "only the prelude member should exist under the locked group"
    )


# ---------------------------------------------------------------------------
# Consent withdrawal from PENDING
# ---------------------------------------------------------------------------
def test_withdraw_pending_consent_rejected(api):
    """PRD §2.6: "Withdraw requires `consent_status` of `GRANTED` —
    `ERR_CONSENT_NOT_GRANTED` (409), on withdraw."
    PRD §3.7: "Withdrawing takes `GRANTED` to `WITHDRAWN`, stamps `withdrawn_at`,
    and is refused with `ERR_CONSENT_NOT_GRANTED` from any other state."
    PRD §3.7: "A new consent starts with `consent_status` of `PENDING`,
    `grant_count` of 0, and null `granted_at` and `withdrawn_at`."

    Design: Corner/Errors/withdraw_pending_consent_rejected
    """
    ctx = fixtures.determined_ale_group_with_employee(api)
    employee_id = ctx["employee"]["id"]
    consent = fixtures.create_consent(api, employee_id, electronic_address="lena@example.com")
    assert consent["consent_status"] == "PENDING", "a fresh consent starts PENDING"

    response = api.withdraw_furnishing_consent(
        consent["id"], make_employee_self_service_headers(employee_id)
    )
    validate_error(response, ApiErrorId.ERR_CONSENT_NOT_GRANTED, 409)

    after = fixtures.read_consent(api, consent["id"])
    assert after["consent_status"] == "PENDING", (
        f"PENDING is not revocable, got {after['consent_status']}"
    )
    assert after["granted_at"] is None, "granted_at must still be null"
    assert after["withdrawn_at"] is None, "a refused withdrawal must not stamp withdrawn_at"
    assert after["grant_count"] == 0, f"grant_count should stay 0, got {after['grant_count']}"


# ---------------------------------------------------------------------------
# Furnishing is once-only outside a redelivery
# ---------------------------------------------------------------------------
def test_second_furnish_of_furnished_form_rejected(api):
    """PRD §2.6: "Furnish requires `furnishing_status` of `NOT_FURNISHED` or
    `REDELIVERY_REQUIRED` — `ERR_FORM_ALREADY_FURNISHED` (409), on furnish."
    PRD §3.7: "It is accepted only from `NOT_FURNISHED` or
    `REDELIVERY_REQUIRED`, so `furnishing_status` walks `NOT_FURNISHED` →
    `FURNISHED_PAPER` or `NOT_FURNISHED` → `FURNISHED_ELECTRONIC` on first
    delivery and `REDELIVERY_REQUIRED` → `FURNISHED_PAPER` or
    `REDELIVERY_REQUIRED` → `FURNISHED_ELECTRONIC` on redelivery."
    PRD §3.7: "A statement delivered on or before the deadline date carries no
    penalty at all — the deadline date itself is not late."

    Design: Corner/Errors/second_furnish_of_furnished_form_rejected
    """
    ctx = _group_with_statement(api)
    form_id = ctx["form"]["id"]
    fixtures.set_clock(api, FURNISHING_WINDOW_OPEN_UTC, PREPARER)
    delivered = fixtures.furnish_form(api, form_id, "PAPER")
    assert delivered["furnishing_status"] == "FURNISHED_PAPER"

    response = api.furnish_form_1095c(form_id, factories.furnish_payload("PAPER"), PREPARER_2)
    validate_error(response, ApiErrorId.ERR_FORM_ALREADY_FURNISHED, 409)

    after = fixtures.read_form(api, form_id)
    assert after["furnishing_status"] == "FURNISHED_PAPER", (
        f"furnishing_status should stay FURNISHED_PAPER, got {after['furnishing_status']}"
    )
    assert after["furnished_at"] == delivered["furnished_at"], (
        "a refused second delivery must not restamp furnished_at"
    )
    assert after["late_furnishing_penalty_cents"] == 0, (
        "delivery on 2027-02-01 precedes the 2027-03-02 deadline, so no penalty applies; "
        f"got {after['late_furnishing_penalty_cents']}"
    )


# ---------------------------------------------------------------------------
# A statement sits on at most one transmittal
# ---------------------------------------------------------------------------
def test_attach_already_attached_form_rejected(api):
    """PRD §2.6: "Attach requires every named form to be `NOT_FILED` —
    `ERR_FORM_ALREADY_ATTACHED` (409), on attach-forms."
    PRD §3.8: "Each attached form moves `NOT_FILED` → `ATTACHED` and records the
    transmittal in its `transmittal_id`, the transmittal's `form_count`
    increments, and the member's `unattached_form_count` moves into
    `attached_form_count`; the member's `version` advances."

    Design: Corner/Errors/attach_already_attached_form_rejected
    """
    ctx = _group_with_statement(api)
    form_id = ctx["form"]["id"]
    member_id = ctx["member"]["id"]
    first = fixtures.open_transmittal(api, member_id)
    fixtures.attach_forms(api, first["id"], [form_id])
    second = fixtures.open_transmittal(api, member_id)

    response = api.attach_forms(second["id"], factories.attach_forms_payload([form_id]), PREPARER)
    validate_error(response, ApiErrorId.ERR_FORM_ALREADY_ATTACHED, 409)

    form_after = fixtures.read_form(api, form_id)
    assert form_after["filing_status"] == "ATTACHED", (
        f"filing_status should stay ATTACHED, got {form_after['filing_status']}"
    )
    assert form_after["transmittal_id"] == first["id"], (
        "the statement must keep pointing at the transmittal that already holds it"
    )


def test_attach_already_attached_form_leaves_second_transmittal_empty(api):
    """PRD §2.11: "Attaching statements to a submission takes a `form_ids` array;
    if any named form is not in `NOT_FILED`, the whole call is refused and no form
    is attached."
    PRD §3.8: "A new transmittal starts at `DRAFT` with `cycle_number` 1, every
    counter at zero and null `channel`, `receipt_id`, `built_at` and
    `transmitted_at`; creating it sets the member's `open_transmittal_id` and
    increments the member's `version`."

    Design: Corner/Errors/attach_already_attached_form_rejected
    """
    ctx = _group_with_statement(api)
    form_id = ctx["form"]["id"]
    member_id = ctx["member"]["id"]
    first = fixtures.open_transmittal(api, member_id)
    fixtures.attach_forms(api, first["id"], [form_id])
    second = fixtures.open_transmittal(api, member_id)

    response = api.attach_forms(second["id"], factories.attach_forms_payload([form_id]), PREPARER)
    validate_error(response, ApiErrorId.ERR_FORM_ALREADY_ATTACHED, 409)

    second_after = fixtures.read_transmittal(api, second["id"])
    assert second_after["form_count"] == 0, (
        f"the refused transmittal must keep form_count 0, got {second_after['form_count']}"
    )
    assert second_after["aggregate_return_count"] == 0, (
        "an unbuilt transmittal keeps every counter at zero, got "
        f"{second_after['aggregate_return_count']}"
    )
    assert fixtures.read_transmittal(api, first["id"])["form_count"] == 1, (
        "the holding transmittal keeps its single attached statement"
    )
    member_after = fixtures.read_member(api, member_id)
    assert member_after["attached_form_count"] == 1, (
        f"the statement is counted once, got {member_after['attached_form_count']}"
    )
    assert member_after["unattached_form_count"] == 0, (
        "the attach moved the count out of unattached_form_count and the refusal did not undo it"
    )


# ---------------------------------------------------------------------------
# Detach is checked against both halves of the link
# ---------------------------------------------------------------------------
def test_detach_form_never_attached_rejected(api):
    """PRD §2.6: "Detach requires the form to be `ATTACHED` with its
    `transmittal_id` equal to the transmittal in the path —
    `ERR_FORM_NOT_ATTACHED` (409), on detach-form."
    PRD §3.8: "A new transmittal starts at `DRAFT` with `cycle_number` 1, every
    counter at zero and null `channel`, `receipt_id`, `built_at` and
    `transmitted_at`; creating it sets the member's `open_transmittal_id` and
    increments the member's `version`."

    Design: Corner/Errors/detach_form_never_attached_rejected
    """
    ctx = _group_with_statement(api)
    form_id = ctx["form"]["id"]
    transmittal = fixtures.open_transmittal(api, ctx["member"]["id"])
    before = fixtures.read_transmittal(api, transmittal["id"])

    response = api.detach_form(
        transmittal["id"], factories.detach_form_payload(form_id), PREPARER
    )
    validate_error(response, ApiErrorId.ERR_FORM_NOT_ATTACHED, 409)

    after = fixtures.read_transmittal(api, transmittal["id"])
    assert after["status"] == "DRAFT", f"status should stay DRAFT, got {after['status']}"
    assert after["form_count"] == 0, f"form_count should stay 0, got {after['form_count']}"
    assert after["version"] == before["version"], (
        "a refused detach must not advance the transmittal's version"
    )
    form_after = fixtures.read_form(api, form_id)
    assert form_after["filing_status"] == "NOT_FILED", (
        f"filing_status should stay NOT_FILED, got {form_after['filing_status']}"
    )
    assert form_after.get("transmittal_id") is None, (
        "a statement that was never attached carries no transmittal_id"
    )


# ---------------------------------------------------------------------------
# A voided original is a dead end for regeneration
# ---------------------------------------------------------------------------
def _voided_original_with_correction(api):
    """Generate, furnish electronically against a granted consent, then regenerate
    once so the delivered original is VOIDED and a correction exists."""
    ctx = fixtures.determined_ale_group_with_employee(api)
    employee_id = ctx["employee"]["id"]
    fixtures.granted_consent(api, employee_id, electronic_address="lena@example.com")
    ctx["form"] = fixtures.generate_form(api, employee_id)
    fixtures.set_clock(api, FURNISHING_WINDOW_OPEN_UTC, PREPARER)
    fixtures.furnish_form(api, ctx["form"]["id"], "ELECTRONIC")
    fixtures.regenerate_form(api, ctx["form"]["id"], correction_reason="wrong plan start month")
    return ctx


def test_regenerate_voided_form_rejected(api):
    """PRD §2.6: "Neither status dimension of the target form is `VOIDED` —
    `ERR_FORM_VOIDED` (409), on regenerate and on the employee full-time
    recompute."
    PRD §3.6: "Regeneration is refused with `ERR_FORM_VOIDED` when either
    dimension is already `VOIDED`, and like generation it requires the group to be
    in `DETERMINED_ALE` or `CORRECTION_OPEN`."

    Design: Corner/Errors/regenerate_voided_form_rejected
    """
    ctx = _voided_original_with_correction(api)
    form_id = ctx["form"]["id"]
    assert fixtures.read_form(api, form_id)["furnishing_status"] == "VOIDED", (
        "regenerating a delivered statement voids its furnishing dimension"
    )

    response = api.regenerate_form_1095c(form_id, PREPARER, {"correction_reason": "second attempt"})
    validate_error(response, ApiErrorId.ERR_FORM_VOIDED, 409)

    after = fixtures.read_form(api, form_id)
    assert after["furnishing_status"] == "VOIDED", (
        f"furnishing_status should stay VOIDED, got {after['furnishing_status']}"
    )


def test_regenerate_voided_form_drafts_no_second_correction(api):
    """PRD §3.6: "On a statement that has already been delivered —
    `FURNISHED_PAPER` or `FURNISHED_ELECTRONIC` — or has already reached the
    agency, it does something quite different: a new statement is created with
    `form_type` of `CORRECTED` and `corrected_from_form_id` pointing at the
    original, the twelve lines are computed on the new statement, and the
    delivered original is pushed to `VOIDED` on its furnishing dimension rather
    than edited — the correction begins life at `NOT_FURNISHED` on its furnishing
    dimension and `NOT_FILED` on its filing dimension, the member's
    `generated_form_count` decrements for the voided original and increments for
    the correction, and `correction_reason` records why."
    PRD §3.6: "Regeneration is refused with `ERR_FORM_VOIDED` when either
    dimension is already `VOIDED`, and like generation it requires the group to be
    in `DETERMINED_ALE` or `CORRECTION_OPEN`."

    Design: Corner/Errors/regenerate_voided_form_rejected
    """
    ctx = _voided_original_with_correction(api)
    form_id = ctx["form"]["id"]

    response = api.regenerate_form_1095c(form_id, PREPARER, {"correction_reason": "second attempt"})
    validate_error(response, ApiErrorId.ERR_FORM_VOIDED, 409)

    corrections, meta = validate_paginated(
        api.list_forms_1095c(PREPARER, params={"corrected_from_form_id": form_id})
    )
    assert meta["total_count"] == 1, (
        f"no second correction may be chained off a void, got total_count {meta['total_count']}"
    )
    assert corrections[0]["form_type"] == "CORRECTED", (
        "the single correction drafted by the first regenerate is the CORRECTED statement"
    )


# ---------------------------------------------------------------------------
# attach-forms demands a DRAFT transmittal
# ---------------------------------------------------------------------------
def test_attach_forms_on_built_transmittal_rejected(api):
    """PRD §2.6: "The transmittal's `status` admits the operation: build from
    `DRAFT`, `REJECTED` or `CORRECTION_REQUIRED`; attach-forms from `DRAFT`;
    detach-form from `DRAFT` or `BUILT`; agency-response from `TRANSMITTED`;
    start-correction-cycle from `ACCEPTED_WITH_ERRORS` or `PARTIALLY_ACCEPTED`; a
    direct agency-error creation from `ACCEPTED_WITH_ERRORS`,
    `PARTIALLY_ACCEPTED` or `REJECTED` — `ERR_TRANSMITTAL_STATE_INVALID` (409)."
    PRD §3.8: "Statements are attached to a `DRAFT` transmittal in batches through
    `form_ids`."

    Design: Corner/Errors/attach_forms_on_built_transmittal_rejected
    """
    ctx = fixtures.determined_ale_group_with_employee(api)
    member_id = ctx["member"]["id"]
    employee_b = fixtures.create_employee(api, member_id, "Ivan Petrov", ssn_last4="8765")
    form_a = fixtures.generate_form(api, ctx["employee"]["id"])
    form_b = fixtures.generate_form(api, employee_b["id"])
    built = fixtures.built_transmittal_with_forms(api, member_id, [form_a["id"]])
    assert built["status"] == "BUILT", f"setup should reach BUILT, got {built['status']}"

    response = api.attach_forms(
        built["id"], factories.attach_forms_payload([form_b["id"]]), PREPARER
    )
    validate_error(response, ApiErrorId.ERR_TRANSMITTAL_STATE_INVALID, 409)

    after = fixtures.read_transmittal(api, built["id"])
    assert after["status"] == "BUILT", f"status should stay BUILT, got {after['status']}"
    assert after["form_count"] == 1, (
        f"the refused attach must not raise form_count, got {after['form_count']}"
    )
    form_b_after = fixtures.read_form(api, form_b["id"])
    assert form_b_after["filing_status"] == "NOT_FILED", (
        f"the unattached statement stays NOT_FILED, got {form_b_after['filing_status']}"
    )
    assert form_b_after.get("transmittal_id") is None, (
        "the refused attach must not record a transmittal on the statement"
    )


# ---------------------------------------------------------------------------
# Resolution is terminal per agency error row
# ---------------------------------------------------------------------------
def test_resolve_already_resolved_error_rejected(api):
    """PRD §2.6: "Resolve requires `resolution_status` of `OPEN`, and an
    accept-as-filed resolution requires `severity` of `WARNING` —
    `ERR_ERROR_ALREADY_RESOLVED` (409), on resolve."
    PRD §3.8: "Attempting to accept a `FATAL` or `ERROR` row as filed, or to
    resolve a row that is no longer `OPEN`, is refused with
    `ERR_ERROR_ALREADY_RESOLVED`."

    Design: Corner/Errors/resolve_already_resolved_error_rejected
    """
    ctx = _errored_transmittal(api, "WARNING", "AIRTN200", "AIR-2026-2020")
    error_id = ctx["error_row"]["id"]
    get_success_data(
        api.resolve_transmittal_error(
            error_id,
            factories.resolve_error_payload(
                "ACCEPT_AS_FILED", resolution_note="agency warning acknowledged"
            ),
            PREPARER,
        )
    )

    response = api.resolve_transmittal_error(
        error_id,
        factories.resolve_error_payload("ACCEPT_AS_FILED", resolution_note="acknowledged twice"),
        PREPARER,
    )
    validate_error(response, ApiErrorId.ERR_ERROR_ALREADY_RESOLVED, 409)

    after = get_success_data(api.get_transmittal_error(error_id, PREPARER))
    assert after["resolution_status"] == "ACCEPTED_AS_FILED", (
        f"resolution is terminal per row, got {after['resolution_status']}"
    )


def test_resolve_already_resolved_error_leaves_counters_intact(api):
    """PRD §3.8: "`ACCEPT_AS_FILED` requires the error row to be `OPEN` and its
    `severity` to be exactly `WARNING`; it moves the error `OPEN` →
    `ACCEPTED_AS_FILED`, stamps `resolved_by_user_id` and `resolution_note`, and
    decrements `open_error_count` — but creates no correction statement and
    changes no group counter at all."
    PRD §2.6: "Resolve requires `resolution_status` of `OPEN`, and an
    accept-as-filed resolution requires `severity` of `WARNING` —
    `ERR_ERROR_ALREADY_RESOLVED` (409), on resolve."

    Design: Corner/Errors/resolve_already_resolved_error_rejected
    """
    ctx = _errored_transmittal(api, "WARNING", "AIRTN200", "AIR-2026-2020")
    error_id = ctx["error_row"]["id"]
    transmittal_id = ctx["transmittal"]["id"]
    get_success_data(
        api.resolve_transmittal_error(
            error_id,
            factories.resolve_error_payload(
                "ACCEPT_AS_FILED", resolution_note="agency warning acknowledged"
            ),
            PREPARER,
        )
    )

    response = api.resolve_transmittal_error(
        error_id,
        factories.resolve_error_payload("ACCEPT_AS_FILED", resolution_note="acknowledged twice"),
        PREPARER,
    )
    validate_error(response, ApiErrorId.ERR_ERROR_ALREADY_RESOLVED, 409)

    after = fixtures.read_transmittal(api, transmittal_id)
    assert after["open_error_count"] == 0, (
        f"open_error_count must not go negative, got {after['open_error_count']}"
    )
    assert after["error_count"] == 1, (
        f"error_count still counts the single agency row, got {after['error_count']}"
    )
    _, meta = validate_paginated(
        api.list_forms_1095c(PREPARER, params={"corrected_from_form_id": ctx["form"]["id"]})
    )
    assert meta["total_count"] == 0, (
        "accepting a warning as filed creates no correction statement, got total_count "
        f"{meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# The notice must be gathering evidence before it can be recomputed
# ---------------------------------------------------------------------------
def _received_notice(api, notice_number):
    ctx = fixtures.determined_ale_group(api)
    ctx["notice"] = fixtures.create_penalty_notice(
        api,
        ctx["group"]["id"],
        notice_number,
        asserted_a_months=[1, 2],
        notice_date="2026-06-01",
        response_due_date="2026-09-30",
        proposed_amount_cents=271700,
    )
    return ctx


def test_recompute_with_zero_evidence_rejected(api):
    """PRD §2.6: "The notice's `status` admits the operation: evidence from
    `RECEIVED`, `EVIDENCE_GATHERING` or `RECOMPUTED`; recompute from
    `EVIDENCE_GATHERING` with `evidence_count` of at least 1; agency-determination
    from `RESPONSE_SUBMITTED` — `ERR_NOTICE_STATE_INVALID` (409)."
    PRD §3.9: "A new notice starts at `RECEIVED` with `evidence_count` 0,
    `allocated_total_cents` 0, `unallocated_amount_cents` 0,
    `applied_evidence_count` 0, and nulls in `a_month_penalty_cents`,
    `b_month_penalty_cents`, `recalculated_amount_cents`, `abated_amount_cents`,
    `determination`, `recomputed_at`, `last_evidence_user_id`,
    `response_submitted_by_user_id` and `response_submitted_at`."

    Design: Corner/Errors/recompute_with_zero_evidence_rejected
    """
    ctx = _received_notice(api, "226J-2026-0001")
    notice_id = ctx["notice"]["id"]

    response = api.recompute_penalty_notice(notice_id, CO)
    validate_error(response, ApiErrorId.ERR_NOTICE_STATE_INVALID, 409)

    after = fixtures.read_notice(api, notice_id)
    assert after["status"] == "RECEIVED", (
        f"a brand-new notice stays RECEIVED, got {after['status']}"
    )
    assert after["evidence_count"] == 0, (
        f"there is nothing to compute from, got evidence_count {after['evidence_count']}"
    )
    assert after["recalculated_amount_cents"] is None, (
        "a refused recomputation must not write recalculated_amount_cents"
    )


def test_submit_response_before_recompute_rejected(api):
    """PRD §2.6: "Transmit requires the transmittal to be `BUILT`, answering
    `ERR_TRANSMITTAL_NOT_BUILT`; submit-response and allocation reset require the
    notice to be `RECOMPUTED`, answering `ERR_NOTICE_NOT_RECOMPUTED` (both 409)."
    PRD §3.9: "The officer then files **PenaltyEvidence** against the notice,
    which moves it from `RECEIVED` to `EVIDENCE_GATHERING` (and is also accepted
    while already `EVIDENCE_GATHERING` or `RECOMPUTED`)."

    Design: Corner/Errors/submit_response_before_recompute_rejected
    """
    ctx = _received_notice(api, "226J-2026-0002")
    notice_id = ctx["notice"]["id"]
    fixtures.file_evidence(
        api, notice_id, "MEC_OFFER_PROOF", 1, document_ref="OFFER-LOG-JAN"
    )

    # co-2 acts, so the segregation-of-duties control on the notice's
    # last_evidence_user_id cannot be the reason for the refusal.
    response = api.submit_penalty_response(notice_id, CO_2)
    validate_error(response, ApiErrorId.ERR_NOTICE_NOT_RECOMPUTED, 409)

    after = fixtures.read_notice(api, notice_id)
    assert after["status"] == "EVIDENCE_GATHERING", (
        f"the notice stays EVIDENCE_GATHERING, got {after['status']}"
    )
    assert after["evidence_count"] == 1, (
        f"the single filed evidence row survives, got {after['evidence_count']}"
    )
    assert after["recalculated_amount_cents"] is None, (
        "no recomputation has settled, so recalculated_amount_cents is still null"
    )
    assert after["response_submitted_at"] is None, (
        "a refused submission must not stamp response_submitted_at"
    )


# ---------------------------------------------------------------------------
# Headcount completeness is all-or-nothing at twelve months
# ---------------------------------------------------------------------------
def _group_with_eleven_headcount_months(api):
    season = fixtures.create_filing_season(api)
    group = fixtures.create_controlled_group(api, season["id"])
    member = fixtures.create_group_member(api, group["id"], measurement_method="MONTHLY")
    fixtures.record_headcounts(api, member["id"], months=list(range(1, 12)))
    return {"season": season, "group": group, "member": member}


def test_determination_with_eleven_headcount_months_rejected(api):
    """PRD §2.6: "Twelve prior-year headcount months exist for every counted
    member — `ERR_HEADCOUNT_INCOMPLETE` (409), on ale-determination."
    PRD §3.2: "Before any counting happens, every counted member must have all
    twelve prior-year months on file; a single missing member-month is fatal and
    answers `ERR_HEADCOUNT_INCOMPLETE`."

    Design: Corner/Errors/determination_with_eleven_headcount_months_rejected
    """
    ctx = _group_with_eleven_headcount_months(api)
    group_id = ctx["group"]["id"]
    version_before = fixtures.current_group_version(api, group_id)

    response = api.run_ale_determination(
        group_id, factories.ale_determination_payload(version_before), CO
    )
    validate_error(response, ApiErrorId.ERR_HEADCOUNT_INCOMPLETE, 409)

    after = fixtures.read_group(api, group_id)
    assert after["determination_state"] == "NOT_DETERMINED", (
        f"eleven months cannot be averaged, got {after['determination_state']}"
    )
    assert after["version"] == version_before, (
        "a refused determination must not advance the group's version"
    )


def test_determination_succeeds_once_twelfth_headcount_month_arrives(api):
    """PRD §3.2: "The twelve stored monthly figures are then summed, divided by
    12, and rounded half up to two decimal places to give
    `annual_average_fte_raw`; truncating that value gives the whole-number
    `annual_average_fte` that is compared against the threshold of 50
    full-time-equivalent employees."
    PRD §2.8: "When that value does not equal the group's current `version`, the
    determination is rejected with `ERR_STALE_GROUP_VERSION` (HTTP 412)."

    Design: Corner/Errors/determination_with_eleven_headcount_months_rejected
    """
    ctx = _group_with_eleven_headcount_months(api)
    group_id = ctx["group"]["id"]
    version_before = fixtures.current_group_version(api, group_id)
    validate_error(
        api.run_ale_determination(
            group_id, factories.ale_determination_payload(version_before), CO
        ),
        ApiErrorId.ERR_HEADCOUNT_INCOMPLETE,
        409,
    )

    fixtures.record_headcounts(api, ctx["member"]["id"], months=[12])
    determined = validate_success(
        api.run_ale_determination(
            group_id, factories.ale_determination_payload(version_before), CO
        )
    )

    assert determined["annual_average_fte"] == 50, (
        "forty full-time employees plus 1200 part-time hours over 120 give fifty "
        f"full-time equivalents a month; got {determined['annual_average_fte']}"
    )
    assert determined["determination_state"] == "DETERMINED_ALE", (
        f"fifty meets the threshold, got {determined['determination_state']}"
    )


# ---------------------------------------------------------------------------
# A look-back employee needs a governing measurement cycle
# ---------------------------------------------------------------------------
def _look_back_employee_with_hours(api):
    ctx = fixtures.determined_ale_group_with_employee(
        api,
        member_measurement_method="LOOK_BACK",
        employee_overrides={
            "full_name": "Nadia Cruz",
            "ssn_last4": "5150",
            "employment_type": "VARIABLE_HOUR",
        },
    )
    fixtures.record_hours(api, ctx["employee"]["id"], 2026, hours_of_service=160)
    return ctx


def test_look_back_employee_without_measurement_cycle_rejected(api):
    """PRD §2.6: "A look-back employee has a governing measurement cycle —
    `ERR_MEASUREMENT_METHOD_CONFLICT` (409), on the employee full-time recompute,
    form generation and regenerate."
    PRD §3.5: "The governing cycle is the employee's own `INITIAL` cycle when one
    exists, and otherwise the `STANDARD` cycle of the employee's member; when
    neither exists the recompute is refused with
    `ERR_MEASUREMENT_METHOD_CONFLICT`."
    PRD §3.3: "A new hire starts `ACTIVE` with a null `termination_date`, a null
    `open_leave_type`, `full_time_month_count` of 0, empty `full_time_months`, a
    null `measured_average_hours` and a null `last_recomputed_at`."

    Design: Corner/Errors/look_back_employee_without_measurement_cycle_rejected
    """
    ctx = _look_back_employee_with_hours(api)
    employee_id = ctx["employee"]["id"]
    assert (
        fixtures.read_employee(api, employee_id)["effective_measurement_method"] == "LOOK_BACK"
    ), "the employee inherits the member's look-back method"

    response = api.recompute_employee_full_time(employee_id, BA)
    validate_error(response, ApiErrorId.ERR_MEASUREMENT_METHOD_CONFLICT, 409)

    after = fixtures.read_employee(api, employee_id)
    assert after["full_time_month_count"] == 0, (
        f"no verdict may be written without a cycle, got {after['full_time_month_count']}"
    )
    assert after["full_time_months"] == [], (
        f"full_time_months stays empty, got {after['full_time_months']}"
    )
    assert after["measured_average_hours"] is None, (
        "a refused recompute must not write measured_average_hours"
    )
    assert after["last_recomputed_at"] is None, (
        "a refused recompute must not stamp last_recomputed_at"
    )


def test_look_back_recompute_succeeds_under_member_standard_cycle(api):
    """PRD §3.5: "The governing cycle is the employee's own `INITIAL` cycle when
    one exists, and otherwise the `STANDARD` cycle of the employee's member; when
    neither exists the recompute is refused with
    `ERR_MEASUREMENT_METHOD_CONFLICT`."
    PRD §3.5: "Otherwise `measured_average_hours` is the sum of `counted_hours`
    across the surviving rows divided by the number of surviving rows, rounded
    half up to two decimal places, and the single stability verdict is that this
    average is at least the cycle's `hours_threshold_monthly`."

    Design: Corner/Errors/look_back_employee_without_measurement_cycle_rejected
    """
    ctx = _look_back_employee_with_hours(api)
    employee_id = ctx["employee"]["id"]
    fixtures.record_hours(api, employee_id, 2025, hours_of_service=160)
    validate_error(
        api.recompute_employee_full_time(employee_id, BA),
        ApiErrorId.ERR_MEASUREMENT_METHOD_CONFLICT,
        409,
    )

    fixtures.create_measurement_cycle(api, ctx["member"]["id"], cycle_type="STANDARD")
    recomputed = validate_success(api.recompute_employee_full_time(employee_id, BA))

    assert recomputed["measured_average_hours"] == pytest.approx(160.0, abs=0.01), (
        "one hundred and sixty counted hours in every surviving month average to 160.00; got "
        f"{recomputed['measured_average_hours']}"
    )
    assert recomputed["full_time_month_count"] == 12, (
        "the stability period covers the whole reporting year and 160 hours clears the "
        f"threshold of 130; got {recomputed['full_time_month_count']}"
    )


# ---------------------------------------------------------------------------
# Build refuses an empty submission and an unresolved correction round
# ---------------------------------------------------------------------------
def test_build_with_zero_attached_forms_rejected(api):
    """PRD §2.6: "Build requires `form_count` of at least 1 —
    `ERR_NO_FORMS_ATTACHED` (409), on build."
    PRD §3.8: "It is accepted from `DRAFT`, from `REJECTED` (a replacement round)
    and from `CORRECTION_REQUIRED` (a correction round); it requires at least one
    attached form, an `OPEN` season, and a controlled group in `DETERMINED_ALE` or
    `CORRECTION_OPEN`; and from `CORRECTION_REQUIRED` it additionally requires
    `open_error_count` of zero."

    Design: Corner/Errors/build_with_zero_attached_forms_rejected
    """
    ctx = fixtures.determined_ale_group(api)
    transmittal = fixtures.open_transmittal(api, ctx["member"]["id"])

    response = api.build_transmittal(transmittal["id"], PREPARER)
    validate_error(response, ApiErrorId.ERR_NO_FORMS_ATTACHED, 409)

    after = fixtures.read_transmittal(api, transmittal["id"])
    assert after["status"] == "DRAFT", (
        f"an empty submission stays DRAFT, got {after['status']}"
    )
    assert after["form_count"] == 0, f"form_count should stay 0, got {after['form_count']}"
    assert after["aggregate_return_count"] == 0, (
        f"no return count is computed, got {after['aggregate_return_count']}"
    )
    assert after["built_at"] is None, "a refused build must not stamp built_at"


def test_correction_build_with_open_errors_rejected(api):
    """PRD §2.6: "Build from `CORRECTION_REQUIRED` requires `open_error_count` of
    0 — `ERR_OPEN_TRANSMITTAL_ERRORS` (409), on build."
    PRD §3.8: "That move requires at least one open error and a `cycle_number`
    still below the limit of 3, and changes no counters — it simply marks the
    submission as needing another round, buildable again once every error has been
    resolved."

    Design: Corner/Errors/correction_build_with_open_errors_rejected
    """
    ctx = _errored_transmittal(api, "ERROR", "AIRTN500", "AIR-2026-3030")
    transmittal_id = ctx["transmittal"]["id"]
    get_success_data(api.start_correction_cycle(transmittal_id, PREPARER))

    response = api.build_transmittal(transmittal_id, PREPARER)
    validate_error(response, ApiErrorId.ERR_OPEN_TRANSMITTAL_ERRORS, 409)

    after = fixtures.read_transmittal(api, transmittal_id)
    assert after["status"] == "CORRECTION_REQUIRED", (
        f"the refused build leaves the round open, got {after['status']}"
    )
    assert after["cycle_number"] == 1, (
        f"starting the correction cycle changes no counters, got {after['cycle_number']}"
    )
    assert after["open_error_count"] == 1, (
        f"the agency error is still open, got {after['open_error_count']}"
    )
    assert after["form_count"] == 1, (
        "the emptiness rule is satisfied, so form_count is not the reason for the refusal; got "
        f"{after['form_count']}"
    )
    assert fixtures.read_form(api, ctx["form"]["id"])["filing_status"] == "FILED_WITH_ERRORS", (
        "the statement named by an ERROR-severity row sits at FILED_WITH_ERRORS"
    )


def test_correction_build_succeeds_once_every_error_is_resolved(api):
    """PRD §3.8: "`CORRECT_FORM` requires the error row to be `OPEN`, to name a
    form through `form_1095c_id`, and to belong to a transmittal in
    `ACCEPTED_WITH_ERRORS`, `PARTIALLY_ACCEPTED` or `CORRECTION_REQUIRED`; it
    moves the error `OPEN` → `CORRECTED`, creates a statement with `form_type` of
    `CORRECTED` whose `corrected_from_form_id` is the named form, records that new
    statement in the error's `corrected_form_id`, stamps `resolved_by_user_id` and
    `resolution_note`, moves the named statement `FILED_WITH_ERRORS` →
    `CORRECTION_DRAFTED`, decrements the transmittal's `open_error_count`, and
    increments the group's `open_correction_count`, moving a `DETERMINED_ALE`
    group to `CORRECTION_OPEN`."
    PRD §3.8: "Building from `REJECTED` or `CORRECTION_REQUIRED` increments
    `cycle_number` by one, and both of those rounds — like starting a correction
    cycle — are refused with `ERR_CORRECTION_CYCLE_LIMIT` once `cycle_number` has
    reached the limit of 3."

    Design: Corner/Errors/correction_build_with_open_errors_rejected
    """
    ctx = _errored_transmittal(api, "ERROR", "AIRTN500", "AIR-2026-3030")
    transmittal_id = ctx["transmittal"]["id"]
    get_success_data(api.start_correction_cycle(transmittal_id, PREPARER))
    validate_error(
        api.build_transmittal(transmittal_id, PREPARER),
        ApiErrorId.ERR_OPEN_TRANSMITTAL_ERRORS,
        409,
    )

    get_success_data(
        api.resolve_transmittal_error(
            ctx["error_row"]["id"],
            factories.resolve_error_payload(
                "CORRECT_FORM", resolution_note="ssn corrected on the replacement"
            ),
            PREPARER,
        )
    )
    assert fixtures.read_transmittal(api, transmittal_id)["open_error_count"] == 0, (
        "resolving the only row clears open_error_count"
    )

    built = validate_success(api.build_transmittal(transmittal_id, PREPARER))
    assert built["status"] == "BUILT", (
        f"the correction round becomes buildable again, got {built['status']}"
    )
    assert built["cycle_number"] == 2, (
        f"building from CORRECTION_REQUIRED advances cycle_number, got {built['cycle_number']}"
    )

"""Appeal pipeline: creation, letters, withdrawal, level chain (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    attach_document,
    get_denial,
    make_appeal,
    make_lettered_appeal,
    make_queued_denial,
    make_submitted_appeal,
    record_outcome,
    set_clock,
    setup_catalog,
    setup_denial_with_submitted_appeal,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_appeal_letter_generate_then_revise_clears_letter(api, specialist_headers):
    """PRD §3.4: "**Letter generation** moves an appeal `DRAFT` → `LETTER_GENERATED` (from
    any other state, `ERR_APPEAL_INVALID_STATE`). The composed `letter_body` is a
    deterministic template naming the denial's claim number, category, the appeal's level,
    and the denied amount, followed by a manifest of the appeal's `ACTIVE` attachments sorted
    by `document_type`; `generated_at` takes the logical clock's timestamp, and a
    `LETTER_GENERATED` event is appended."
    PRD §3.4: "If the evidence set or wording needs rework, revising returns the appeal
    `LETTER_GENERATED` → `DRAFT` (again, `ERR_APPEAL_INVALID_STATE` from any other state),
    clearing `letter_body` and `generated_at` back to null."

    Design: Difficulty/non_linear_state_machine/appeal_letter_revise_cycle
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-501",
    )
    appeal = make_appeal(denial["id"])
    attach_document(appeal["id"], "CLINICAL_NOTES", file_reference="doc-501-notes")
    set_clock("2026-08-05T00:00:00Z")
    generated = validate_success(api.generate_letter(appeal["id"], specialist_headers))
    assert generated["status"] == "LETTER_GENERATED"
    assert generated["letter_body"] is not None
    assert "CLM-501" in generated["letter_body"], "letter names the denial's claim number"
    assert generated["generated_at"] is not None
    revised = validate_success(api.revise_appeal(appeal["id"], specialist_headers))
    assert revised["status"] == "DRAFT", "revise loops the appeal back to DRAFT"
    assert revised["letter_body"] is None
    assert revised["generated_at"] is None


def test_appeal_letter_regenerate_and_submit(api, specialist_headers):
    """PRD §3.4: "On success `submitted_at` takes the logical timestamp, `response_due_date`
    becomes the submission date plus the effective policy's `response_window_days`, an
    `APPEAL_SUBMITTED` event is appended, and the parent denial's `version` increments by
    one."

    Design: Difficulty/non_linear_state_machine/appeal_letter_revise_cycle
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-501",
    )
    appeal = make_appeal(denial["id"])
    attach_document(appeal["id"], "CLINICAL_NOTES", file_reference="doc-501-notes")
    set_clock("2026-08-05T00:00:00Z")
    validate_success(api.generate_letter(appeal["id"], specialist_headers))
    validate_success(api.revise_appeal(appeal["id"], specialist_headers))
    regenerated = validate_success(api.generate_letter(appeal["id"], specialist_headers))
    assert regenerated["status"] == "LETTER_GENERATED"
    assert regenerated["letter_body"] is not None
    submitted = validate_success(api.submit_appeal(appeal["id"], specialist_headers))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"] is not None
    assert submitted["submitted_at"].startswith("2026-08-05"), (
        "submitted_at is read from the logical clock at 2026-08-05"
    )
    assert submitted["response_due_date"] == "2026-09-04"  # submission date + 30 days


def test_submit_from_draft_rejected(api, specialist_headers):
    """PRD §3.4: "**Submission** moves `LETTER_GENERATED` → `SUBMITTED` and enforces two
    gates in order."
    PRD §2.8: "**State preconditions.** The target resource must be in a from-state allowed
    for the attempted transition: denials report `ERR_DENIAL_INVALID_STATE`, appeals
    `ERR_APPEAL_INVALID_STATE`, root-cause tasks `ERR_TASK_INVALID_STATE`, write-off requests
    `ERR_WRITE_OFF_NOT_PENDING`, scorecards `ERR_SCORECARD_NOT_OPEN`, and payer status
    toggles or prevention-program transitions `ERR_INVALID_STATE` (all 409)."

    Design: Corner/state_machines/submit_from_draft_rejected
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2104",
    )
    appeal = make_appeal(denial["id"])
    attach_document(appeal["id"], "CLINICAL_NOTES", file_reference="doc-2104-notes")
    resp = api.submit_appeal(appeal["id"], specialist_headers)
    validate_error(resp, ApiErrorId.ERR_APPEAL_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_appeal(appeal["id"], specialist_headers))
    assert after["status"] == "DRAFT"


def test_response_due_date_uses_policy_window(api, specialist_headers):
    """PRD §3.4: "On success `submitted_at` takes the logical timestamp, `response_due_date`
    becomes the submission date plus the effective policy's `response_window_days`, an
    `APPEAL_SUBMITTED` event is appended, and the parent denial's `version` increments by
    one."

    Design: Corner/calculations/response_due_date_uses_policy_window
    """
    catalog = setup_catalog(
        levels=(1,), policy_overrides_by_level={1: {"response_window_days": 21}},
    )
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2206",
    )
    appeal = make_lettered_appeal(denial["id"])
    set_clock("2026-08-05T00:00:00Z")
    submitted = validate_success(api.submit_appeal(appeal["id"], specialist_headers))
    assert submitted["submitted_at"].startswith("2026-08-05")
    assert submitted["response_due_date"] == "2026-08-26"  # 2026-08-05 + 21 days


def test_next_level_deadline_after_upheld(api, specialist_headers):
    """PRD §3.4: "An `UPHELD` outcome recovers nothing and follows the same fork: next-level
    policy present means the denial stays `IN_APPEAL` with the recomputed deadline, otherwise
    `CLOSED_EXHAUSTED` with a null deadline."
    PRD §3.4: "sets `next_appeal_deadline` to the outcome date plus that next-level policy's
    `timely_filing_days` while the denial stays `IN_APPEAL`"

    Design: Corner/calculations/next_level_deadline_after_upheld
    """
    catalog = setup_catalog(levels=(1, 2))
    denial_id, appeal = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-2202",
    )
    set_clock("2026-09-10T00:00:00Z")
    record_outcome(appeal["id"], "UPHELD", 0)
    denial = get_denial(denial_id)
    assert denial["status"] == "IN_APPEAL"
    assert denial["next_appeal_deadline"] == "2026-10-25"  # outcome 2026-09-10 + 45 days


def test_appeal_level_chain_self_reference(api, manager_headers, specialist_headers):
    """PRD §3.4: "The new appeal's `level_number` is the denial's `current_appeal_level`
    plus one, and its `previous_appeal_id` links to the appeal one level lower for the same
    denial — null on a first appeal."
    PRD §3.4: "Appeal listings accept the foreign-key reverse lookups `denial_case_id` and
    `previous_appeal_id` plus `status` and `level_number` filters."

    Design: Corner/entities/appeal_level_chain_self_reference
    """
    catalog = setup_catalog(levels=(1, 2))
    denial_id, appeal1 = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-2007",
        denied_amount_cents=100000, billed_amount_cents=120000,
    )
    set_clock("2026-08-10T00:00:00Z")
    record_outcome(appeal1["id"], "UPHELD", 0)
    appeal2 = validate_success(
        api.create_appeal({"denial_case_id": denial_id}, specialist_headers), expected_status=201,
    )
    assert appeal2["level_number"] == 2
    assert appeal2["previous_appeal_id"] == appeal1["id"]
    rows, meta = validate_paginated(
        api.list_appeals(manager_headers, params={"previous_appeal_id": appeal1["id"]})
    )
    assert len(rows) == 1 and rows[0]["id"] == appeal2["id"]
    denial = get_denial(denial_id)
    assert denial["current_appeal_level"] == 2
    assert denial["next_appeal_deadline"] == "2026-09-24"  # outcome 2026-08-10 + 45 days


def test_appeal_already_active_conflict(api, specialist_headers):
    """PRD §3.4: "no other appeal of the same denial may currently be in `DRAFT`,
    `LETTER_GENERATED`, or `SUBMITTED` (else `ERR_APPEAL_ALREADY_ACTIVE`)"

    Design: Corner/validations/appeal_already_active_conflict
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2306",
    )
    make_appeal(denial["id"])
    resp = api.create_appeal({"denial_case_id": denial["id"]}, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_ACTIVE, expected_status=409)
    rows, meta = validate_paginated(
        api.list_appeals(specialist_headers, params={"denial_case_id": denial["id"]})
    )
    assert meta["total_count"] == 1, "exactly one appeal exists after the conflict"


def test_code_not_appealable_blocked(api, specialist_headers):
    """PRD §3.1: "A code registered with `appealable` false still appears on denials for
    analytics, but any attempt to open an appeal on such a denial is rejected with
    `ERR_CODE_NOT_APPEALABLE`."

    Design: Corner/validations/code_not_appealable_blocked
    """
    catalog = setup_catalog(
        levels=(1,),
        code_overrides={"code": "PR-96", "category": "CONTRACTUAL", "appealable": False},
    )
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2307",
    )
    assert denial["status"] == "QUEUED", "non-appealable codes are still recordable and queueable"
    resp = api.create_appeal({"denial_case_id": denial["id"]}, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_CODE_NOT_APPEALABLE, expected_status=422)
    rows, meta = validate_paginated(
        api.list_appeals(specialist_headers, params={"denial_case_id": denial["id"]})
    )
    assert meta["total_count"] == 0


def test_withdraw_returns_denial_to_queue(api, specialist_headers):
    """PRD §3.4: "from `DRAFT` or `LETTER_GENERATED` (else `ERR_APPEAL_INVALID_STATE`) the
    appeal moves to its terminal `WITHDRAWN` state. The denial's `current_appeal_level`
    recomputes as the highest `level_number` among its non-`WITHDRAWN` appeals — zero when
    none remain — and when the recomputed level is zero the denial falls back `IN_APPEAL` →
    `QUEUED` with `next_appeal_deadline` unchanged, the level-1 deadline still governing."

    Design: Corner/state_machines/withdraw_returns_denial_to_queue
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2105",
    )
    appeal = make_appeal(denial["id"])
    withdrawn = validate_success(api.withdraw_appeal(appeal["id"], specialist_headers))
    assert withdrawn["status"] == "WITHDRAWN"
    denial = get_denial(denial["id"])
    assert denial["status"] == "QUEUED"
    assert denial["current_appeal_level"] == 0
    assert denial["next_appeal_deadline"] == "2026-09-30"
    resp = api.withdraw_appeal(appeal["id"], specialist_headers)
    validate_error(resp, ApiErrorId.ERR_APPEAL_INVALID_STATE, expected_status=409)

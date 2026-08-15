"""Appeal submission gates: timely filing and attachment completeness (PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    attach_document,
    get_denial,
    make_appeal,
    make_lettered_appeal,
    make_queued_denial,
    record_outcome,
    set_clock,
    setup_catalog,
    setup_denial_with_submitted_appeal,
    validate_error,
    validate_success,
    void_attachment_payload,
)

TIMELINESS_FIRST_CITE = (
    'PRD §3.4: "**Submission** moves `LETTER_GENERATED` → `SUBMITTED` and enforces two '
    'gates in order. First, timeliness: the submission date must be on or before the '
    'denial\'s `next_appeal_deadline` at whole-day granularity, else '
    '`ERR_TIMELY_FILING_EXPIRED`."'
)


def _two_lettered_appeals_at_deadline(api, catalog):
    """Two queued denials (remit 2026-08-01 -> deadline 2026-09-30), each with a
    LETTER_GENERATED level-1 appeal carrying CLINICAL_NOTES."""
    out = []
    for claim in ("CLM-1301", "CLM-1302"):
        denial = make_queued_denial(
            catalog["payer"]["id"], catalog["code"]["id"], claim_number=claim,
        )
        appeal = make_lettered_appeal(denial["id"])
        out.append((denial["id"], appeal["id"]))
    return out


def test_submit_on_deadline_date_is_timely(api, specialist_headers):
    """PRD §2.4: "Every timeliness comparison is made at whole-day granularity: an appeal
    submitted on its deadline date itself is timely, because the comparison asks whether the
    submission date is on or before the deadline date."

    Design: Difficulty/boundary_precision_check/submit_on_deadline_date_timely
    """
    catalog = setup_catalog(levels=(1,))
    (d1, ap1), _ = _two_lettered_appeals_at_deadline(api, catalog)
    set_clock("2026-09-30T00:00:00Z")  # exactly the deadline date
    submitted = validate_success(api.submit_appeal(ap1, specialist_headers))
    assert submitted["status"] == "SUBMITTED", "date equality is timely (on or before)"
    assert submitted["response_due_date"] == "2026-10-30"  # 2026-09-30 + 30 days


def test_submit_one_day_past_deadline_rejected(api, specialist_headers):
    """PRD §3.4: "First, timeliness: the submission date must be on or before the denial's
    `next_appeal_deadline` at whole-day granularity, else `ERR_TIMELY_FILING_EXPIRED`."
    PRD §3.5: "A denial in `IN_APPEAL` expires the same way only when it additionally has no
    appeal currently in `DRAFT`, `LETTER_GENERATED`, or `SUBMITTED` — an in-flight appeal
    package shields the denial from expiry."

    Design: Difficulty/boundary_precision_check/submit_on_deadline_date_timely
    """
    catalog = setup_catalog(levels=(1,))
    (d1, ap1), (d2, ap2) = _two_lettered_appeals_at_deadline(api, catalog)
    set_clock("2026-09-30T00:00:00Z")
    validate_success(api.submit_appeal(ap1, specialist_headers))
    set_clock("2026-10-01T00:00:00Z")  # one day past the 2026-09-30 deadline
    # Both denials hold in-flight appeals (SUBMITTED / LETTER_GENERATED) and are shielded.
    assert get_denial(d1)["status"] == "IN_APPEAL"
    assert get_denial(d2)["status"] == "IN_APPEAL"
    resp = api.submit_appeal(ap2, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_TIMELY_FILING_EXPIRED, expected_status=422)
    appeal = validate_success(api.get_appeal(ap2, specialist_headers))
    assert appeal["status"] == "LETTER_GENERATED"


def test_submit_expired_with_attachments_complete_rejected(api, specialist_headers):
    """PRD §3.4: "First, timeliness: the submission date must be on or before the denial's
    `next_appeal_deadline` at whole-day granularity, else `ERR_TIMELY_FILING_EXPIRED`."

    Design: Corner/validations/submit_expired_with_attachments_complete_rejected
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2310",
    )
    appeal = make_lettered_appeal(denial["id"])  # CLINICAL_NOTES attached
    set_clock("2026-10-01T00:00:00Z")  # deadline 2026-09-30 has passed
    resp = api.submit_appeal(appeal["id"], specialist_headers)
    validate_error(resp, ApiErrorId.ERR_TIMELY_FILING_EXPIRED, expected_status=422)
    assert get_denial(denial["id"])["status"] == "IN_APPEAL", (
        "the in-flight LETTER_GENERATED appeal shields the denial from the sweep"
    )


def test_temporal_gate_beats_attachment_gate(api, specialist_headers):
    """PRD §3.4: "**Submission** moves `LETTER_GENERATED` → `SUBMITTED` and enforces two
    gates in order. First, timeliness: the submission date must be on or before the denial's
    `next_appeal_deadline` at whole-day granularity, else `ERR_TIMELY_FILING_EXPIRED`.
    Second, completeness: every document type named in the effective policy's
    `required_attachment_types` — the policy for the appeal's level whose window contains the
    submission date — must be present among the appeal's `ACTIVE` attachment types, else
    `ERR_ATTACHMENT_REQUIREMENT_UNMET`; a policy created without requirements has an empty
    list, which any attachment set satisfies."

    Design: Difficulty/priority_pair_validation_conflict/appeal_submit_temporal_beats_constraint
    """
    catalog = setup_catalog(levels=(1,))  # level 1 requires CLINICAL_NOTES
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-901",
    )
    set_clock("2026-08-20T00:00:00Z")
    appeal = make_appeal(denial["id"])  # NO attachments: completeness also fails
    validate_success(api.generate_letter(appeal["id"], specialist_headers))
    set_clock("2026-10-01T00:00:00Z")  # past deadline: timeliness also fails
    resp = api.submit_appeal(appeal["id"], specialist_headers)
    err = validate_error(resp, ApiErrorId.ERR_TIMELY_FILING_EXPIRED, expected_status=422)
    assert err["error_id"] != ApiErrorId.ERR_ATTACHMENT_REQUIREMENT_UNMET


def test_temporal_gate_failure_leaves_state_untouched(api, specialist_headers):
    """PRD §3.4: "First, timeliness: the submission date must be on or before the denial's
    `next_appeal_deadline` at whole-day granularity, else `ERR_TIMELY_FILING_EXPIRED`."
    PRD §3.5: "A denial in `IN_APPEAL` expires the same way only when it additionally has no
    appeal currently in `DRAFT`, `LETTER_GENERATED`, or `SUBMITTED` — an in-flight appeal
    package shields the denial from expiry."

    Design: Difficulty/priority_pair_validation_conflict/appeal_submit_temporal_beats_constraint
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-901",
    )
    set_clock("2026-08-20T00:00:00Z")
    appeal = make_appeal(denial["id"])
    validate_success(api.generate_letter(appeal["id"], specialist_headers))
    set_clock("2026-10-01T00:00:00Z")
    validate_error(
        api.submit_appeal(appeal["id"], specialist_headers),
        ApiErrorId.ERR_TIMELY_FILING_EXPIRED,
    )
    after_appeal = validate_success(api.get_appeal(appeal["id"], specialist_headers))
    assert after_appeal["status"] == "LETTER_GENERATED"
    assert get_denial(denial["id"])["status"] == "IN_APPEAL"


def test_attachment_void_removes_requirement_satisfaction(api, specialist_headers):
    """PRD §3.4: "An attachment begins `ACTIVE` with an empty `voided_reason`, and only
    `ACTIVE` attachments satisfy submission requirements."
    PRD §3.4: "Second, completeness: every document type named in the effective policy's
    `required_attachment_types` — the policy for the appeal's level whose window contains the
    submission date — must be present among the appeal's `ACTIVE` attachment types, else
    `ERR_ATTACHMENT_REQUIREMENT_UNMET`; a policy created without requirements has an empty
    list, which any attachment set satisfies."

    Design: Corner/state_machines/attachment_void_removes_requirement_satisfaction
    """
    catalog = setup_catalog(
        levels=(1, 2),
        policy_overrides_by_level={
            2: {"required_attachment_types": ["CLINICAL_NOTES", "PHYSICIAN_LETTER"]},
        },
    )
    denial_id, appeal1 = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-2110",
        denied_amount_cents=100000, billed_amount_cents=120000,
    )
    set_clock("2026-08-10T00:00:00Z")
    record_outcome(appeal1["id"], "UPHELD", 0)
    appeal2 = make_appeal(denial_id)
    attach_document(appeal2["id"], "CLINICAL_NOTES", file_reference="doc-2110-notes2")
    letter = attach_document(appeal2["id"], "PHYSICIAN_LETTER", file_reference="doc-2110-letter")
    voided = validate_success(
        api.void_appeal_attachment(
            letter["id"], void_attachment_payload("Wrong patient document attached"),
            specialist_headers,
        )
    )
    assert voided["status"] == "VOIDED"
    assert voided["voided_reason"] == "Wrong patient document attached"
    validate_success(api.generate_letter(appeal2["id"], specialist_headers))
    resp = api.submit_appeal(appeal2["id"], specialist_headers)
    validate_error(resp, ApiErrorId.ERR_ATTACHMENT_REQUIREMENT_UNMET, expected_status=422)
    after = validate_success(api.get_appeal(appeal2["id"], specialist_headers))
    assert after["status"] == "LETTER_GENERATED"


def test_attachment_void_on_submitted_appeal_rejected(api, specialist_headers):
    """PRD §3.4: "Voiding an attachment requires the attachment itself to be `ACTIVE` (else
    `ERR_INVALID_STATE`) and its parent appeal still in `DRAFT` or `LETTER_GENERATED` (else
    `ERR_APPEAL_INVALID_STATE`); the supplied `reason` is stored as `voided_reason`, the
    attachment moves `ACTIVE` → `VOIDED`, and any letter already generated for the parent
    appeal is left stale until regenerated."

    Design: Corner/state_machines/attachment_void_on_submitted_appeal_rejected
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2111",
    )
    appeal = make_appeal(denial["id"])
    attachment = attach_document(appeal["id"], "CLINICAL_NOTES", file_reference="doc-2111-notes")
    validate_success(api.generate_letter(appeal["id"], specialist_headers))
    validate_success(api.submit_appeal(appeal["id"], specialist_headers))
    resp = api.void_appeal_attachment(
        attachment["id"], void_attachment_payload("Late quality check"), specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_appeal_attachment(attachment["id"], specialist_headers))
    assert after["status"] == "ACTIVE"


def test_attachment_soft_void_filter_semantics(api, specialist_headers):
    """PRD §3.4: "the supplied `reason` is stored as `voided_reason`, the attachment moves
    `ACTIVE` → `VOIDED`, and any letter already generated for the parent appeal is left stale
    until regenerated. Attachment listings accept `appeal_id`, `document_type`, and `status`
    filters."

    Design: Corner/complexity_layers/attachment_soft_void_filter_semantics
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2608",
    )
    appeal = make_appeal(denial["id"])
    notes = attach_document(appeal["id"], "CLINICAL_NOTES", file_reference="doc-2608-notes")
    letter = attach_document(appeal["id"], "PHYSICIAN_LETTER", file_reference="doc-2608-letter")
    validate_success(
        api.void_appeal_attachment(
            letter["id"], void_attachment_payload("Superseded by updated letter"),
            specialist_headers,
        )
    )
    active = validate_success(
        api.list_appeal_attachments(
            specialist_headers, params={"appeal_id": appeal["id"], "status": "ACTIVE"},
        )
    )
    assert [a["id"] for a in active] == [notes["id"]]
    voided = validate_success(
        api.list_appeal_attachments(
            specialist_headers, params={"appeal_id": appeal["id"], "status": "VOIDED"},
        )
    )
    assert [a["id"] for a in voided] == [letter["id"]]
    by_id = validate_success(api.get_appeal_attachment(letter["id"], specialist_headers))
    assert by_id["status"] == "VOIDED"
    assert by_id["voided_reason"] == "Superseded by updated letter"

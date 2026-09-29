"""The evidence repository and the independence rules that guard it: the
unbounded rejection/resubmission loop, the expiry guard on validation, per-action
role gating on the shared transition endpoint, and the segregation-of-duties rule
that stops a validator from reviewing a standard they actively own."""

from test_helpers import (
    ApiErrorId,
    assign_owner,
    create_chapter,
    create_standard,
    evidence_action,
    file_evidence,
    make_evidence_validator_headers,
    make_standard_owner_headers,
    read_chapter,
    read_standard,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Private setup chains — every test rebuilds its own world from scratch.
# ---------------------------------------------------------------------------

def _setup_owned_standard(
    code="IC",
    name="Infection Control",
    weight_pct=100,
    evidence_min_count=1,
    standard_code="IC.01.01.01",
    title="Hand hygiene program",
    owner_user_id="owner-1",
):
    """Chapter + one standard mapped to a single ACTIVE PRIMARY owner."""
    chapter = create_chapter(code, name, weight_pct, evidence_min_count)
    standard = create_standard(chapter["id"], standard_code, title, "DIRECT_IMPACT")
    assignment = assign_owner(standard["id"], owner_user_id, "PRIMARY")
    return {"chapter": chapter, "standard": standard, "assignment": assignment}


def _setup_evidence_in_state(
    state,
    expires_at=None,
    evidence_min_count=1,
    weight_pct=100,
    owner_user_id="owner-1",
    validator_user_id="val-1",
    doc_title="Hand hygiene audit",
    doc_type="LOG",
):
    """An owned standard carrying one evidence item walked to `state`."""
    built = _setup_owned_standard(
        weight_pct=weight_pct,
        evidence_min_count=evidence_min_count,
        owner_user_id=owner_user_id,
    )
    evidence = file_evidence(
        built["standard"]["id"],
        title=doc_title,
        doc_type=doc_type,
        effective_date="2026-07-01T00:00:00Z",
        expires_at=expires_at,
        owner_user_id=owner_user_id,
    )
    if state in ("SUBMITTED", "REJECTED"):
        evidence = evidence_action(
            evidence["id"], "SUBMIT", make_standard_owner_headers(owner_user_id)
        )
    if state == "REJECTED":
        evidence = evidence_action(
            evidence["id"], "REJECT", make_evidence_validator_headers(validator_user_id)
        )
    built["evidence"] = evidence
    return built


# ---------------------------------------------------------------------------
# state_machines / evidence_reject_then_resubmit_cycle_increments_rejection_count
# ---------------------------------------------------------------------------

def test_evidence_reject_then_resubmit_then_validate_completes_the_standard(
    api, standard_owner_headers, evidence_validator_headers
):
    """PRD §3.2: "`REJECT` from `SUBMITTED` moves the item `SUBMITTED → REJECTED`, increments `rejection_count` by one and records `reviewed_by_user_id`; the standard's counters are untouched because the document never counted."
    PRD §3.2: "Submitting for review moves the item `DRAFT → SUBMITTED`, or `REJECTED → SUBMITTED` on a resubmission — the rejection loop is unbounded, and an owner may keep revising and resubmitting a document indefinitely."
    PRD §3.2: "When those pass, the item moves `SUBMITTED → VALIDATED`, `reviewed_by_user_id` is set to the reviewing principal and `review_note` is captured from the payload, and the standard's `validated_evidence_count` increases by one."
    PRD §3.2: "If that increase brings the count to at least the owning chapter's `evidence_min_count`, the standard transitions `MAPPED → EVIDENCE_COMPLETE` and the chapter's `evidence_complete_standard_count` increases by one."

    Design: Corner/state_machines/evidence_reject_then_resubmit_cycle_increments_rejection_count
    """
    built = _setup_evidence_in_state(
        "SUBMITTED", weight_pct=50, doc_title="Hand hygiene audit log"
    )
    evidence_id = built["evidence"]["id"]

    rejected = validate_success(
        api.transition_evidence_item(
            evidence_id,
            {"action": "REJECT", "review_note": "Sample size too small"},
            evidence_validator_headers,
        )
    )
    assert rejected["validation_state"] == "REJECTED"
    assert rejected["rejection_count"] == 1
    assert rejected["reviewed_by_user_id"] == "val-1"

    resubmitted = validate_success(
        api.transition_evidence_item(
            evidence_id, {"action": "SUBMIT"}, standard_owner_headers
        )
    )
    assert resubmitted["validation_state"] == "SUBMITTED"
    assert resubmitted["rejection_count"] == 1

    validated = validate_success(
        api.transition_evidence_item(
            evidence_id,
            {"action": "VALIDATE", "review_note": "Expanded sample accepted"},
            evidence_validator_headers,
        )
    )
    assert validated["validation_state"] == "VALIDATED"
    assert validated["rejection_count"] == 1

    standard = read_standard(built["standard"]["id"])
    assert standard["validated_evidence_count"] == 1
    assert standard["compliance_state"] == "EVIDENCE_COMPLETE"

    chapter = read_chapter(built["chapter"]["id"])
    assert chapter["evidence_complete_standard_count"] == 1


# ---------------------------------------------------------------------------
# validations / validate_expired_evidence_returns_evidence_expired
# ---------------------------------------------------------------------------

def test_validate_evidence_whose_expiry_has_passed_returns_evidence_expired(
    api, director_headers, evidence_validator_headers
):
    """PRD §3.2: "And the artefact must still be current: `expires_at` must be null or strictly after the current logical clock, or the request is rejected with `ERR_EVIDENCE_EXPIRED`."
    PRD §2.11: "34. `VALIDATE` requires `expires_at` to be null or strictly after the logical clock — `ERR_EVIDENCE_EXPIRED`, 409, on `POST /accreditation/evidence-items/{id}/transition`."
    PRD §2.4: "First, the **evidence expiry sweep**: every evidence item in `VALIDATED` whose `expires_at` is not null and is at or before the new clock value moves to `EXPIRED`."
    PRD §2.4: "`expired_evidence_count` is the number of evidence items expired by the sweep and `eligible_window_count` is the number of windows that became eligible."

    Design: Corner/validations/validate_expired_evidence_returns_evidence_expired
    """
    built = _setup_evidence_in_state(
        "SUBMITTED",
        expires_at="2026-08-05T00:00:00Z",
        doc_title="Competency roster",
        doc_type="TRAINING_RECORD",
    )
    evidence_id = built["evidence"]["id"]

    swept = validate_success(api.set_clock("2026-08-06T00:00:00Z", director_headers))
    assert swept["expired_evidence_count"] == 0

    validate_error(
        api.transition_evidence_item(
            evidence_id,
            {"action": "VALIDATE", "review_note": "Late review"},
            evidence_validator_headers,
        ),
        ApiErrorId.ERR_EVIDENCE_EXPIRED,
    )

    after = validate_success(api.get_evidence_item(evidence_id, director_headers))
    assert after["validation_state"] == "SUBMITTED"
    assert after["reviewed_by_user_id"] is None

    standard = read_standard(built["standard"]["id"])
    assert standard["validated_evidence_count"] == 0
    assert standard["compliance_state"] == "MAPPED"


# ---------------------------------------------------------------------------
# rbac / evidence_validator_cannot_submit_evidence_action_gating
# ---------------------------------------------------------------------------

def test_evidence_validator_submitting_evidence_is_unauthorized(
    api, director_headers, evidence_validator_headers
):
    """PRD §2.11: "2. Authorization: the acting role may perform this operation, and on a multi-action endpoint the role is permitted for the requested action specifically (`SUBMIT` is `StandardOwner`-only, `VALIDATE` and `REJECT` are `EvidenceValidator`-only, `VERIFY`, `FAIL_VERIFICATION` and `ESCALATE` are `SafetyOfficer`-only) — `ERR_UNAUTHORIZED`, 403, on every endpoint."
    PRD §3.2: "Three actions are declared, and the ladder at §2.11 rung 2 restricts each to one role: `SUBMIT` belongs to the `StandardOwner`, while `VALIDATE` and `REJECT` belong to the `EvidenceValidator`."
    PRD §3.2: "A newly filed item begins at `validation_state` `DRAFT`, with `submitted_by_user_id`, `reviewed_by_user_id` and `review_note` all null and `rejection_count` at zero."

    Design: Corner/rbac/evidence_validator_cannot_submit_evidence_action_gating
    """
    built = _setup_evidence_in_state("DRAFT")
    evidence_id = built["evidence"]["id"]
    assert built["evidence"]["validation_state"] == "DRAFT"
    assert built["evidence"]["expires_at"] is None

    validate_error(
        api.transition_evidence_item(
            evidence_id, {"action": "SUBMIT"}, evidence_validator_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    after = validate_success(api.get_evidence_item(evidence_id, director_headers))
    assert after["validation_state"] == "DRAFT"
    assert after["submitted_by_user_id"] is None


# ---------------------------------------------------------------------------
# rbac / standard_owner_cannot_validate_evidence_action_gating
# ---------------------------------------------------------------------------

def test_standard_owner_validating_own_evidence_is_unauthorized_before_segregation(
    api, director_headers, standard_owner_headers
):
    """PRD §2.11: "2. Authorization: the acting role may perform this operation, and on a multi-action endpoint the role is permitted for the requested action specifically (`SUBMIT` is `StandardOwner`-only, `VALIDATE` and `REJECT` are `EvidenceValidator`-only, `VERIFY`, `FAIL_VERIFICATION` and `ESCALATE` are `SafetyOfficer`-only) — `ERR_UNAUTHORIZED`, 403, on every endpoint."
    PRD §2.11: "40. Segregation of duties: the reviewing `X-User-ID` is not the `owner_user_id` of any owner assignment with `status` `ACTIVE` on the standard — `ERR_SEGREGATION_OF_DUTIES`, 403, on the `VALIDATE` and `REJECT` actions of `POST /accreditation/evidence-items/{id}/transition`."
    PRD §2.11: "The lower the number below, the earlier the check runs; the first check that fails produces the response, and no later check is evaluated."

    Design: Corner/rbac/standard_owner_cannot_validate_evidence_action_gating
    """
    built = _setup_evidence_in_state("SUBMITTED")
    evidence_id = built["evidence"]["id"]
    assert built["evidence"]["validation_state"] == "SUBMITTED"

    validate_error(
        api.transition_evidence_item(
            evidence_id,
            {"action": "VALIDATE", "review_note": "Self-approval attempt"},
            standard_owner_headers,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    after = validate_success(api.get_evidence_item(evidence_id, director_headers))
    assert after["validation_state"] == "SUBMITTED"
    assert after["reviewed_by_user_id"] is None


# ---------------------------------------------------------------------------
# rbac / segregation_of_duties_validator_owning_the_standard_rejected
# ---------------------------------------------------------------------------

def test_validator_who_actively_owns_the_standard_cannot_validate_its_evidence(api):
    """PRD §2.10: "An `EvidenceValidator` performing either the `VALIDATE` or the `REJECT` action on an evidence item must not be the `owner_user_id` of any owner assignment with `status` `ACTIVE` on that item's standard; a validator reviewing evidence for a standard they actively own is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.2: "The reviewing principal must not be the `owner_user_id` of any `ACTIVE` owner assignment on the standard, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "When those pass, the item moves `SUBMITTED → VALIDATED`, `reviewed_by_user_id` is set to the reviewing principal and `review_note` is captured from the payload, and the standard's `validated_evidence_count` increases by one."

    Design: Corner/rbac/segregation_of_duties_validator_owning_the_standard_rejected
    """
    built = _setup_evidence_in_state("SUBMITTED")
    evidence_id = built["evidence"]["id"]
    assert built["evidence"]["validation_state"] == "SUBMITTED"

    validate_error(
        api.transition_evidence_item(
            evidence_id,
            {"action": "VALIDATE", "review_note": "Reviewing my own evidence"},
            make_evidence_validator_headers("owner-1"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    validated = validate_success(
        api.transition_evidence_item(
            evidence_id,
            {"action": "VALIDATE", "review_note": "Independent review"},
            make_evidence_validator_headers("val-1"),
        )
    )
    assert validated["validation_state"] == "VALIDATED"
    assert validated["reviewed_by_user_id"] == "val-1"

    standard = read_standard(built["standard"]["id"])
    assert standard["validated_evidence_count"] == 1
    assert standard["compliance_state"] == "EVIDENCE_COMPLETE"

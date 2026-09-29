"""
Request-payload builders for the standards-development consensus API.

Each builder returns a valid payload for one endpoint and accepts keyword
overrides, so a test can express "the same request but with a 13-day window"
without restating every field. Values are ordinary standards-body data; nothing
here encodes an expected outcome.
"""

from typing import Any, Dict, Optional


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of None removes the key entirely."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None and key in payload:
            payload.pop(key)
        else:
            payload[key] = value
    return payload


# ------------------------------------------------------------------ participants
def participant_payload(
    full_name: str = "Ada Producer",
    organization: str = "Acme Steel",
    interest_category: str = "PRODUCER",
    employer_affiliation_code: Optional[str] = "ACME",
    **overrides,
) -> Dict[str, Any]:
    base = {
        "full_name": full_name,
        "organization": organization,
        "interest_category": interest_category,
    }
    if employer_affiliation_code is not None:
        base["employer_affiliation_code"] = employer_affiliation_code
    return _merge(base, overrides)


# -------------------------------------------------------------------- committees
def committee_payload(
    chair_participant_id: str,
    designation: str = "TC-14",
    scope_text: str = "Structural fasteners",
    max_concurrent_ballots: Optional[int] = 2,
    **overrides,
) -> Dict[str, Any]:
    base = {
        "designation": designation,
        "scope_text": scope_text,
        "chair_participant_id": chair_participant_id,
    }
    if max_concurrent_ballots is not None:
        base["max_concurrent_ballots"] = max_concurrent_ballots
    return _merge(base, overrides)


def membership_payload(
    participant_id: str, voting_rights: Optional[bool] = True, **overrides
) -> Dict[str, Any]:
    base = {"participant_id": participant_id}
    if voting_rights is not None:
        base["voting_rights"] = voting_rights
    return _merge(base, overrides)


def membership_patch_payload(
    status: Optional[str] = None, voting_rights: Optional[bool] = None, **overrides
) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    if status is not None:
        base["status"] = status
    if voting_rights is not None:
        base["voting_rights"] = voting_rights
    return _merge(base, overrides)


# -------------------------------------------------------------------- work items
def work_item_payload(
    proposer_participant_id: str,
    title: str = "Fastener torque spec",
    scope_text: str = "Torque limits for structural fasteners",
    work_item_type: str = "NEW_STANDARD",
    target_completion_date: str = "2027-06-30",
    **overrides,
) -> Dict[str, Any]:
    base = {
        "title": title,
        "scope_text": scope_text,
        "work_item_type": work_item_type,
        "proposer_participant_id": proposer_participant_id,
        "target_completion_date": target_completion_date,
    }
    return _merge(base, overrides)


def approve_scope_payload(
    sponsoring_committee_id: Optional[str] = None,
    designation: Optional[str] = "STD-1400",
    decision: str = "APPROVE",
    rationale: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"decision": decision}
    if sponsoring_committee_id is not None:
        base["sponsoring_committee_id"] = sponsoring_committee_id
    if designation is not None:
        base["designation"] = designation
    if rationale is not None:
        base["rationale"] = rationale
    return _merge(base, overrides)


def reject_scope_payload(
    rationale: str = "Overlaps an existing committee scope", **overrides
) -> Dict[str, Any]:
    return _merge({"decision": "REJECT", "rationale": rationale}, overrides)


def draft_payload(
    total_clause_count: int = 40,
    changed_clause_count: Optional[int] = 0,
    prior_draft_id: Optional[str] = None,
    summary: Optional[str] = "Revision 1",
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"total_clause_count": total_clause_count}
    if changed_clause_count is not None:
        base["changed_clause_count"] = changed_clause_count
    if prior_draft_id is not None:
        base["prior_draft_id"] = prior_draft_id
    if summary is not None:
        base["summary"] = summary
    return _merge(base, overrides)


def periodic_review_payload(
    action: str = "OPEN_REVIEW", rationale: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"action": action}
    if rationale is not None:
        base["rationale"] = rationale
    return _merge(base, overrides)


# ----------------------------------------------------------------------- ballots
def ballot_payload(
    draft_id: str,
    committee_id: str,
    ballot_kind: str = "SUBCOMMITTEE",
    opens_at: str = "2026-08-01T00:00:00Z",
    closes_at: str = "2026-08-15T00:00:00Z",
    predecessor_ballot_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "draft_id": draft_id,
        "committee_id": committee_id,
        "ballot_kind": ballot_kind,
        "opens_at": opens_at,
        "closes_at": closes_at,
    }
    if predecessor_ballot_id is not None:
        base["predecessor_ballot_id"] = predecessor_ballot_id
    return _merge(base, overrides)


def vote_payload(
    membership_id: str,
    position: str = "AFFIRMATIVE",
    comment_text: Optional[str] = None,
    clause_reference: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"membership_id": membership_id, "position": position}
    if comment_text is not None:
        base["comment_text"] = comment_text
    if clause_reference is not None:
        base["clause_reference"] = clause_reference
    return _merge(base, overrides)


def negative_vote_payload(
    membership_id: str,
    comment_text: str = "Clause 12 torque ceiling is unsafe",
    clause_reference: Optional[str] = "12",
    **overrides,
) -> Dict[str, Any]:
    return vote_payload(
        membership_id,
        position="NEGATIVE",
        comment_text=comment_text,
        clause_reference=clause_reference,
        **overrides,
    )


def vote_patch_payload(
    position: Optional[str] = None,
    status: Optional[str] = None,
    comment_text: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    if position is not None:
        base["position"] = position
    if status is not None:
        base["status"] = status
    if comment_text is not None:
        base["comment_text"] = comment_text
    return _merge(base, overrides)


def adjudication_payload(
    resolution: str = "NON_PERSUASIVE",
    adjudication_rationale: str = "The torque ceiling follows the fatigue annex already balloted",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {"resolution": resolution, "adjudication_rationale": adjudication_rationale},
        overrides,
    )


# ---------------------------------------------------------------- public reviews
def public_review_payload(
    draft_id: str,
    expected_draft_version: int,
    start_date: str = "2026-08-01",
    end_date: str = "2026-09-14",
    **overrides,
) -> Dict[str, Any]:
    base = {
        "draft_id": draft_id,
        "start_date": start_date,
        "end_date": end_date,
        "expected_draft_version": expected_draft_version,
    }
    return _merge(base, overrides)


# ---------------------------------------------------------------------- comments
def public_review_comment_payload(
    submitter_participant_id: str,
    draft_id: str,
    public_review_id: str,
    comment_type: str = "TECHNICAL",
    comment_text: str = "Clause 12 torque ceiling should cite the fatigue annex",
    clause_reference: Optional[str] = "12",
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "source_type": "PUBLIC_REVIEW",
        "comment_type": comment_type,
        "comment_text": comment_text,
        "submitter_participant_id": submitter_participant_id,
        "draft_id": draft_id,
        "public_review_id": public_review_id,
    }
    if clause_reference is not None:
        base["clause_reference"] = clause_reference
    return _merge(base, overrides)


def committee_comment_payload(
    submitter_participant_id: str,
    draft_id: str,
    comment_type: str = "EDITORIAL",
    comment_text: str = "Clause 4 cross-reference should read Annex B",
    clause_reference: Optional[str] = "4",
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "source_type": "COMMITTEE",
        "comment_type": comment_type,
        "comment_text": comment_text,
        "submitter_participant_id": submitter_participant_id,
        "draft_id": draft_id,
    }
    if clause_reference is not None:
        base["clause_reference"] = clause_reference
    return _merge(base, overrides)


def disposition_payload(
    disposition: str = "ACCEPTED",
    disposition_rationale: Optional[str] = "Clause 12 will cite Annex C in revision 2",
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"disposition": disposition}
    if disposition_rationale is not None:
        base["disposition_rationale"] = disposition_rationale
    return _merge(base, overrides)


# ------------------------------------------------------------ patent disclosures
def patent_disclosure_payload(
    work_item_id: str,
    disclosing_participant_id: str,
    expected_work_item_version: int,
    patent_number: str = "US-9876543-B2",
    essentiality: str = "ESSENTIAL",
    **overrides,
) -> Dict[str, Any]:
    base = {
        "work_item_id": work_item_id,
        "disclosing_participant_id": disclosing_participant_id,
        "patent_number": patent_number,
        "essentiality": essentiality,
        "expected_work_item_version": expected_work_item_version,
    }
    return _merge(base, overrides)


def commitment_payload(
    commitment: str = "RAND",
    commitment_letter_ref: Optional[str] = "LETTER-2026-014",
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"commitment": commitment}
    if commitment_letter_ref is not None:
        base["commitment_letter_ref"] = commitment_letter_ref
    return _merge(base, overrides)


# ----------------------------------------------------------------------- appeals
def appeal_payload(
    work_item_id: str,
    appellant_participant_id: str,
    grounds: str = "VOTING_PROCEDURE_DEFECT",
    statement: str = "The consensus ballot closed before the announced closing instant",
    cited_ballot_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "work_item_id": work_item_id,
        "appellant_participant_id": appellant_participant_id,
        "grounds": grounds,
        "statement": statement,
    }
    if cited_ballot_id is not None:
        base["cited_ballot_id"] = cited_ballot_id
    return _merge(base, overrides)


def appeal_decision_payload(
    decision: str = "DENY",
    decision_rationale: str = "The closing instant rule permits an early close once every seat has returned",
    remedy: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "decision": decision,
        "decision_rationale": decision_rationale,
    }
    if remedy is not None:
        base["remedy"] = remedy
    return _merge(base, overrides)


# ------------------------------------------------------------- maintenance items
def maintenance_item_payload(
    work_item_id: str,
    requester_participant_id: str,
    item_kind: str = "INTERPRETATION_REQUEST",
    question_text: str = "Does clause 12 apply to galvanised fasteners",
    clause_reference: Optional[str] = "12",
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "work_item_id": work_item_id,
        "requester_participant_id": requester_participant_id,
        "item_kind": item_kind,
        "question_text": question_text,
    }
    if clause_reference is not None:
        base["clause_reference"] = clause_reference
    return _merge(base, overrides)


def maintenance_resolution_payload(
    action: str = "ISSUE_INTERPRETATION",
    response_text: str = "Clause 12 applies to galvanised fasteners without modification",
    erratum_clause_reference: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"action": action, "response_text": response_text}
    if erratum_clause_reference is not None:
        base["erratum_clause_reference"] = erratum_clause_reference
    return _merge(base, overrides)

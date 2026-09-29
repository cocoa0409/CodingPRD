"""
Resource field inventories for the standards-development consensus API.

One entry per resource type, listing exactly the field names the PRD says the
representation carries, on top of the four common fields (id, created_at,
updated_at, version). Tests use these lists to assert representation shape
without repeating long literal lists.
"""

from .constants import COMMON_FIELDS

PARTICIPANT_FIELDS = [
    "full_name",
    "organization",
    "interest_category",
    "employer_affiliation_code",
]

COMMITTEE_FIELDS = [
    "designation",
    "scope_text",
    "chair_participant_id",
    "max_concurrent_ballots",
    "status",
    "balance_status",
    "roster_balance_status",
    "active_member_count",
    "roster_member_count",
    "dominance_pct",
    "roster_dominance_pct",
    "distinct_category_count",
    "category_counts",
    "open_ballot_count",
]

MEMBERSHIP_FIELDS = [
    "committee_id",
    "participant_id",
    "interest_category",
    "employer_affiliation_code",
    "voting_rights",
    "status",
    "appointed_at",
    "missed_ballot_streak",
]

WORK_ITEM_FIELDS = [
    "title",
    "scope_text",
    "work_item_type",
    "proposer_participant_id",
    "target_completion_date",
    "sponsoring_committee_id",
    "designation",
    "progress_status",
    "ip_status",
    "consensus_gate",
    "unresolved_negative_count",
    "scope_approved_at",
    "edition",
    "published_at",
    "periodic_review_due_date",
    "last_periodic_action_at",
    "errata_count",
    "interpretation_count",
]

DRAFT_FIELDS = [
    "work_item_id",
    "prior_draft_id",
    "revision_number",
    "total_clause_count",
    "changed_clause_count",
    "substantive_change_ratio",
    "status",
    "unresolved_negative_count",
    "carryover_unresolved_negative_count",
    "recirculation_required",
    "ballot_round_count",
    "summary",
]

BALLOT_FIELDS = [
    "draft_id",
    "committee_id",
    "predecessor_ballot_id",
    "ballot_kind",
    "effective_ballot_kind",
    "status",
    "opens_at",
    "closes_at",
    "eligible_voter_count",
    "affirmative_count",
    "negative_count",
    "abstain_count",
    "returned_count",
    "not_returned_count",
    "return_rate_pct",
    "provisional_approval_pct",
    "final_approval_pct",
    "required_return_rate_pct",
    "required_approval_pct",
    "consensus_result",
    "pending_negative_count",
    "hold_reason",
    "closed_at",
]

VOTE_FIELDS = [
    "ballot_id",
    "membership_id",
    "position",
    "status",
    "adjudication_status",
    "adjudicated_by_participant_id",
    "adjudication_rationale",
    "cast_at",
    "position_change_count",
]

COMMENT_FIELDS = [
    "draft_id",
    "ballot_id",
    "public_review_id",
    "source_vote_id",
    "submitter_participant_id",
    "source_type",
    "comment_type",
    "clause_reference",
    "comment_text",
    "status",
    "is_substantive",
    "disposition_rationale",
]

PUBLIC_REVIEW_FIELDS = [
    "draft_id",
    "start_date",
    "end_date",
    "duration_days",
    "status",
    "announced_at",
    "closed_at",
    "comment_count",
    "disposed_count",
    "unresolved_comment_count",
    "disposition_completeness_pct",
    "disposition_approved_by_participant_id",
    "disposition_approved_at",
]

PATENT_DISCLOSURE_FIELDS = [
    "work_item_id",
    "disclosing_participant_id",
    "patent_number",
    "essentiality",
    "status",
    "commitment_letter_ref",
    "disclosed_at",
    "committed_at",
    "blocks_publication",
]

APPEAL_FIELDS = [
    "work_item_id",
    "appellant_participant_id",
    "cited_ballot_id",
    "grounds",
    "statement",
    "status",
    "remedy",
    "filed_at",
    "filing_deadline_at",
    "decided_at",
    "decision_rationale",
]

MAINTENANCE_ITEM_FIELDS = [
    "work_item_id",
    "requester_participant_id",
    "item_kind",
    "question_text",
    "clause_reference",
    "status",
    "response_text",
    "erratum_clause_reference",
    "received_at",
    "resolved_at",
]

RESOURCE_FIELDS = {
    "Participant": PARTICIPANT_FIELDS,
    "TechnicalCommittee": COMMITTEE_FIELDS,
    "CommitteeMembership": MEMBERSHIP_FIELDS,
    "WorkItem": WORK_ITEM_FIELDS,
    "Draft": DRAFT_FIELDS,
    "Ballot": BALLOT_FIELDS,
    "Vote": VOTE_FIELDS,
    "Comment": COMMENT_FIELDS,
    "PublicReview": PUBLIC_REVIEW_FIELDS,
    "PatentDisclosure": PATENT_DISCLOSURE_FIELDS,
    "Appeal": APPEAL_FIELDS,
    "MaintenanceItem": MAINTENANCE_ITEM_FIELDS,
}


def all_fields(resource: str):
    """Common fields plus the resource-specific fields for one resource type."""
    assert resource in RESOURCE_FIELDS, f"Unknown resource type: {resource}"
    return list(COMMON_FIELDS) + list(RESOURCE_FIELDS[resource])

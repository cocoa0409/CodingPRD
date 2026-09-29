"""Record -> JSON projections. Computed fields are derived at read time."""
from decimal import Decimal

import db
from response import iso, iso_instant
from services import derive


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(record, out, versioned=True):
    out["created_at"] = iso(record["created_at"])
    if versioned:
        out["updated_at"] = iso(record["updated_at"])
        out["version"] = record["version"]
    return out


def code_cycle(record):
    ledger = derive.cycle_ledger(record["id"])
    out = {
        "id": record["id"],
        "cycle_year": record["cycle_year"],
        "model_code_edition": record["model_code_edition"],
        "intake_opens_at": iso_instant(record["intake_opens_at"]),
        "intake_closes_at": iso_instant(record["intake_closes_at"]),
        "status": record["status"],
        "seated_committee_count": derive.seated_committee_count(record["id"]),
        "proposal_count": len(derive.proposals_of_cycle(record["id"])),
        "approved_proposal_count": ledger["approved_proposal_count"],
        "approved_incremental_cost_cents": ledger["approved_incremental_cost_cents"],
        "approved_permit_backlog_count": ledger["approved_permit_backlog_count"],
    }
    return _common(record, out)


def discipline_committee(record):
    out = {
        "id": record["id"],
        "code_cycle_id": record["code_cycle_id"],
        "discipline": record["discipline"],
        "voting_seat_count": record["voting_seat_count"],
        "active_voting_member_count": derive.active_voting_member_count(record["id"]),
        "quorum_required": derive.committee_quorum_required(record["id"]),
        "sector_coverage_complete": derive.sector_coverage_complete(record["id"]),
        "chair_member_count": derive.chair_member_count(record["id"]),
        "status": record["status"],
    }
    return _common(record, out)


def committee_member(record):
    out = {
        "id": record["id"],
        "committee_id": record["committee_id"],
        "full_name": record["full_name"],
        "sector": record["sector"],
        "voting_seat": record["voting_seat"],
        "is_chair": record["is_chair"],
        "status": record["status"],
        "recusal_reason": record["recusal_reason"],
    }
    return _common(record, out)


def amendment_proposal(record):
    support, oppose, total = derive.comment_tallies(record)
    out = {
        "id": record["id"],
        "code_cycle_id": record["code_cycle_id"],
        "committee_id": record["committee_id"],
        "code_section": record["code_section"],
        "discipline": record["discipline"],
        "title": record["title"],
        "proposed_text": record["proposed_text"],
        "stringency_direction": record["stringency_direction"],
        "proposer_sector": record["proposer_sector"],
        "submitted_by_user_id": record["submitted_by_user_id"],
        "review_status": record["review_status"],
        "analysis_status": record["analysis_status"],
        "energy_analysis_required": derive.energy_analysis_required(record),
        "affected_permit_count": record["affected_permit_count"],
        "statewide_incremental_cost_cents": record["statewide_incremental_cost_cents"],
        "preliminary_benefit_cost_ratio": _num(record["preliminary_benefit_cost_ratio"]),
        "final_benefit_cost_ratio": _num(record["final_benefit_cost_ratio"]),
        "support_comment_count": support,
        "oppose_comment_count": oppose,
        "total_comment_count": total,
        "comment_window_status": record["comment_window_status"],
        "comment_opens_at": iso_instant(record["comment_opens_at"]),
        "comment_closes_at": iso_instant(record["comment_closes_at"]),
        "comment_extension_count": record["comment_extension_count"],
        "comment_round": record["comment_round"],
        "revision_round": record["revision_round"],
        "base_docket_score": _num(record["base_docket_score"]),
        "docket_queue_rank": record["docket_queue_rank"],
        "docket_priority_score": _num(record["docket_priority_score"]),
    }
    return _common(record, out)


def impact_analysis(record):
    out = {
        "id": record["id"],
        "proposal_id": record["proposal_id"],
        "analysis_type": record["analysis_type"],
        "prepared_by_user_id": record["prepared_by_user_id"],
        "reviewed_by_user_id": record["reviewed_by_user_id"],
        "incremental_cost_by_occupancy": record["incremental_cost_by_occupancy"],
        "affected_permit_count": record["affected_permit_count"],
        "annual_cost_savings_cents": record["annual_cost_savings_cents"],
        "measure_life_years": record["measure_life_years"],
        "annual_energy_savings_kwh": record["annual_energy_savings_kwh"],
        "energy_delta_pct": record["energy_delta_pct"],
        "statewide_incremental_cost_cents": record["statewide_incremental_cost_cents"],
        "status": record["status"],
    }
    return _common(record, out)


def public_comment(record):
    out = {
        "id": record["id"],
        "proposal_id": record["proposal_id"],
        "commenter_sector": record["commenter_sector"],
        "position": record["position"],
        "body": record["body"],
        "submitted_by_user_id": record["submitted_by_user_id"],
        "comment_round": record["comment_round"],
        "received_at": iso_instant(record["received_at"]),
    }
    return _common(record, out, versioned=False)


def hearing(record):
    out = {
        "id": record["id"],
        "committee_id": record["committee_id"],
        "scheduled_start": iso_instant(record["scheduled_start"]),
        "scheduled_end": iso_instant(record["scheduled_end"]),
        "status": record["status"],
        "agenda_proposal_ids": list(record["agenda_proposal_ids"]),
        "present_member_ids": (list(record["present_member_ids"])
                               if record["present_member_ids"] is not None else None),
        "present_voting_count": record["present_voting_count"],
        "quorum_required_at_convene": record["quorum_required_at_convene"],
        "convened_at": iso_instant(record["convened_at"]),
        "adjourned_at": iso_instant(record["adjourned_at"]),
    }
    return _common(record, out)


def vote_record(record):
    out = {
        "id": record["id"],
        "hearing_id": record["hearing_id"],
        "proposal_id": record["proposal_id"],
        "ballots": [dict(b) for b in record["ballots"]],
        "voting_seats_at_call": record["voting_seats_at_call"],
        "quorum_required": record["quorum_required"],
        "yes_count": record["yes_count"],
        "no_count": record["no_count"],
        "abstain_count": record["abstain_count"],
        "absent_count": record["absent_count"],
        "outcome": record["outcome"],
        "outcome_reason": record["outcome_reason"],
        "final_benefit_cost_ratio_at_vote": _num(record["final_benefit_cost_ratio_at_vote"]),
        "recorded_by_user_id": record["recorded_by_user_id"],
    }
    return _common(record, out, versioned=False)


def adoption_rule(record):
    out = {
        "id": record["id"],
        "code_cycle_id": record["code_cycle_id"],
        "title": record["title"],
        "base_date": iso_instant(record["base_date"]),
        "projected_permit_backlog": record["projected_permit_backlog"],
        "transition_grace_days": record["transition_grace_days"],
        "notice_days": record["notice_days"],
        "effective_date": iso_instant(record["effective_date"]),
        "transition_cutoff_date": iso_instant(record["transition_cutoff_date"]),
        "prior_code_expiry_date": iso_instant(record["prior_code_expiry_date"]),
        "approved_incremental_cost_cents_at_filing":
            record["approved_incremental_cost_cents_at_filing"],
        "pinned_amendment_versions": (dict(record["pinned_amendment_versions"])
                                      if record["pinned_amendment_versions"] is not None else None),
        "status": record["status"],
        "filed_by_user_id": record["filed_by_user_id"],
        "published_by_user_id": record["published_by_user_id"],
        "published_at": iso_instant(record["published_at"]),
        "statewide_readiness_pct_at_effective": _num(record["statewide_readiness_pct_at_effective"]),
        "withdrawal_reason": record["withdrawal_reason"],
    }
    return _common(record, out)


def jurisdiction(record):
    enrollment_pct, attendance_pct, readiness = derive.jurisdiction_compliance(record)
    out = {
        "id": record["id"],
        "name": record["name"],
        "population": record["population"],
        "local_authority_level": record["local_authority_level"],
        "host_seat_capacity": record["host_seat_capacity"],
        "official_headcount": record["official_headcount"],
        "compliance_pct_enrollment_basis": float(enrollment_pct),
        "compliance_pct_attendance_basis": float(attendance_pct),
        "enforcement_readiness": readiness,
        "effective_local_amendment_count": derive.effective_local_amendment_count(record["id"]),
    }
    return _common(record, out)


def local_amendment(record):
    out = {
        "id": record["id"],
        "jurisdiction_id": record["jurisdiction_id"],
        "adoption_rule_id": record["adoption_rule_id"],
        "code_section": record["code_section"],
        "local_text": record["local_text"],
        "stringency_direction": record["stringency_direction"],
        "justification": record["justification"],
        "filed_within_window": record["filed_within_window"],
        "revision_round": record["revision_round"],
        "reviewed_by_user_id": record["reviewed_by_user_id"],
        "status": record["status"],
    }
    return _common(record, out)


def interpretation_request(record):
    out = {
        "id": record["id"],
        "adoption_rule_id": record["adoption_rule_id"],
        "jurisdiction_id": record["jurisdiction_id"],
        "supersedes_request_id": record["supersedes_request_id"],
        "assigned_committee_id": record["assigned_committee_id"],
        "code_section": record["code_section"],
        "question": record["question"],
        "requested_by_user_id": record["requested_by_user_id"],
        "opinion_text": record["opinion_text"],
        "binding_scope": record["binding_scope"],
        "opinion_number": record["opinion_number"],
        "drafted_by_user_id": record["drafted_by_user_id"],
        "published_by_user_id": record["published_by_user_id"],
        "published_at": iso_instant(record["published_at"]),
        "appeal_round": record["appeal_round"],
        "decline_reason": record["decline_reason"],
        "status": record["status"],
    }
    return _common(record, out)


def training_session(record):
    enrolled, attended, no_show = derive.session_counts(record["id"])
    out = {
        "id": record["id"],
        "adoption_rule_id": record["adoption_rule_id"],
        "host_jurisdiction_id": record["host_jurisdiction_id"],
        "discipline": record["discipline"],
        "audience": record["audience"],
        "seat_capacity": record["seat_capacity"],
        "starts_at": iso_instant(record["starts_at"]),
        "ends_at": iso_instant(record["ends_at"]),
        "seats_available": record["seat_capacity"] - (enrolled + attended + no_show),
        "enrolled_count": enrolled,
        "attended_count": attended,
        "no_show_count": no_show,
        "cancellation_reason": record["cancellation_reason"],
        "status": record["status"],
    }
    return _common(record, out)


def training_enrollment(record):
    out = {
        "id": record["id"],
        "training_session_id": record["training_session_id"],
        "jurisdiction_id": record["jurisdiction_id"],
        "attendee_name": record["attendee_name"],
        "attendee_role": record["attendee_role"],
        "enrolled_by_user_id": record["enrolled_by_user_id"],
        "status": record["status"],
    }
    return _common(record, out)


SERIALIZERS = {
    "code_cycle": code_cycle,
    "discipline_committee": discipline_committee,
    "committee_member": committee_member,
    "amendment_proposal": amendment_proposal,
    "impact_analysis": impact_analysis,
    "public_comment": public_comment,
    "hearing": hearing,
    "vote_record": vote_record,
    "adoption_rule": adoption_rule,
    "jurisdiction": jurisdiction,
    "local_amendment": local_amendment,
    "interpretation_request": interpretation_request,
    "training_session": training_session,
    "training_enrollment": training_enrollment,
}

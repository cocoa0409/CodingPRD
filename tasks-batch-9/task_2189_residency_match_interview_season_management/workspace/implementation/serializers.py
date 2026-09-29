"""Resource -> JSON projections.

Counters that the PRD defines by extension (a count of child rows) are computed
live here so that the conserved quantities can never drift.  The four decimal
score fields are stored on the row, because the PRD requires them to be able to
go stale (a requested amendment deliberately does not recompute
Application.committee_score).
"""

import calc
from store import find


def _common(row, data):
    data["id"] = row["id"]
    data["created_at"] = row["created_at"]
    data["updated_at"] = row["updated_at"]
    data["version"] = row["version"]
    return data


def program(row, materialising=False):
    """§3.8 recomputes `soap_offer_budget` "on every read of the program".

    Registration is not a read: §3.1 pins the materialised row to
    "`soap_offer_budget` at 0", so the create response echoes that value while
    every subsequent read derives the base-vacancy-plus-reserve figure.
    """
    return _common(
        row,
        {
            "name": row["name"],
            "nrmp_program_code": row["nrmp_program_code"],
            "specialty_code": row["specialty_code"],
            "quota_positions": row["quota_positions"],
            "season_phase": row["season_phase"],
            "visa_sponsorship_allowed": row["visa_sponsorship_allowed"],
            "soap_participating": row["soap_participating"],
            "min_step2_score": row["min_step2_score"],
            "img_accepted": row["img_accepted"],
            "matched_count": calc.matched_count(row),
            "unfilled_positions": calc.unfilled_positions(row),
            "invited_count": calc.invited_count(row),
            "soap_offer_budget": 0 if materialising else calc.soap_offer_budget(row),
            "rank_list_certified_at": row["rank_list_certified_at"],
        },
    )


def applicant(row):
    return _common(
        row,
        {
            "eras_id": row["eras_id"],
            "full_name": row["full_name"],
            "medical_school_type": row["medical_school_type"],
            "visa_status": row["visa_status"],
            "step2_score": row["step2_score"],
            "pipeline_program_alum": row["pipeline_program_alum"],
            "self_identified_group": row["self_identified_group"],
        },
    )


def application(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "applicant_id": row["applicant_id"],
            "screening_status": row["screening_status"],
            "interview_status": row["interview_status"],
            "review_count": calc.review_count(row),
            "provisional_screen_score": row["provisional_screen_score"],
            "final_screen_score": row["final_screen_score"],
            "committee_score": row["committee_score"],
            "withdrawn_reason": row["withdrawn_reason"],
        },
    )


def _slot_lookup(slot_id):
    return find("interview_slots", slot_id)


def faculty_member(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "full_name": row["full_name"],
            "is_program_director": row["is_program_director"],
            "is_committee_member": row["is_committee_member"],
            "conflict_applicant_ids": list(row["conflict_applicant_ids"]),
            "scheduled_load": float(calc.scheduled_load(row, _slot_lookup)),
            "realized_load": float(calc.realized_load(row, _slot_lookup)),
        },
    )


def application_review(row):
    return _common(
        row,
        {
            "application_id": row["application_id"],
            "reviewer_id": row["reviewer_id"],
            "academic_points": row["academic_points"],
            "experience_points": row["experience_points"],
            "holistic_points": row["holistic_points"],
            "status": row["status"],
        },
    )


def interview_wave(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "wave_index": row["wave_index"],
            "invite_release_at": row["invite_release_at"],
            "response_deadline_at": row["response_deadline_at"],
            "seat_capacity": row["seat_capacity"],
            "status": row["status"],
            "issued_count": calc.issued_count(row),
        },
    )


def interview_slot(row):
    return _common(
        row,
        {
            "wave_id": row["wave_id"],
            "start_at": row["start_at"],
            "end_at": row["end_at"],
            "room_label": row["room_label"],
            "applicant_capacity": row["applicant_capacity"],
            "booked_count": calc.booked_count(row),
            "status": row["status"],
        },
    )


def interview_invitation(row):
    return _common(
        row,
        {
            "application_id": row["application_id"],
            "wave_id": row["wave_id"],
            "slot_id": row["slot_id"],
            "status": row["status"],
            "issued_at": row["issued_at"],
            "expires_at": row["expires_at"],
            "responded_at": row["responded_at"],
        },
    )


def interview_assignment(row):
    return _common(
        row,
        {
            "slot_id": row["slot_id"],
            "faculty_member_id": row["faculty_member_id"],
            "panel_role": row["panel_role"],
            "status": row["status"],
        },
    )


def score_card(row):
    return _common(
        row,
        {
            "assignment_id": row["assignment_id"],
            "application_id": row["application_id"],
            "communication_score": row["communication_score"],
            "clinical_reasoning_score": row["clinical_reasoning_score"],
            "professionalism_score": row["professionalism_score"],
            "teamwork_score": row["teamwork_score"],
            "domain_average": row["domain_average"],
            "status": row["status"],
        },
    )


def rank_list(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "status": row["status"],
            "entry_count": calc.entry_count(row),
            "review_round": row["review_round"],
            "approved_at": row["approved_at"],
            "certified_by_faculty_id": row["certified_by_faculty_id"],
        },
    )


def rank_list_entry(row):
    return _common(
        row,
        {
            "rank_list_id": row["rank_list_id"],
            "application_id": row["application_id"],
            "rank_position": row["rank_position"],
            "tie_group_anchor_entry_id": row["tie_group_anchor_entry_id"],
        },
    )


def committee_vote(row):
    return _common(
        row,
        {
            "rank_list_id": row["rank_list_id"],
            "faculty_member_id": row["faculty_member_id"],
            "review_round": row["review_round"],
            "ballot": row["ballot"],
            "comment": row["comment"],
        },
    )


def match_result(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "application_id": row["application_id"],
            "outcome": row["outcome"],
            "matched_rank_position": row["matched_rank_position"],
            "published_at": row["published_at"],
        },
    )


def soap_offer(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "application_id": row["application_id"],
            "soap_round": row["soap_round"],
            "status": row["status"],
            "offered_at": row["offered_at"],
            "expires_at": row["expires_at"],
        },
    )


def contract(row):
    return _common(
        row,
        {
            "match_result_id": row["match_result_id"],
            "salary_cents": row["salary_cents"],
            "status": row["status"],
            "issued_at": row["issued_at"],
            "signed_at": row["signed_at"],
            "mandatory_credential_count": calc.mandatory_credential_count(row),
            "verified_credential_count": calc.verified_credential_count(row),
            "reason": row.get("reason"),
        },
    )


def credential_item(row):
    return _common(
        row,
        {
            "contract_id": row["contract_id"],
            "credential_type": row["credential_type"],
            "is_mandatory": row["is_mandatory"],
            "status": row["status"],
            "reference_number": row["reference_number"],
            "verified_at": row["verified_at"],
            "reason": row.get("reason"),
        },
    )


def communication_log(row):
    return _common(
        row,
        {
            "application_id": row["application_id"],
            "author_faculty_id": row["author_faculty_id"],
            "channel": row["channel"],
            "body": row["body"],
            "contains_ranking_intent": row["contains_ranking_intent"],
            "compliance_status": row["compliance_status"],
            "sent_at": row["sent_at"],
            "resolution_note": row.get("resolution_note"),
        },
    )

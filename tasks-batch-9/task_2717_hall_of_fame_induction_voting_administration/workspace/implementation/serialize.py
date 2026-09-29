"""Resource serializers.

`EligibilityRule` and `VoterBloc` are deliberately leaner: they carry only `id`
and `created_at` -- both `updated_at` and `version` are absent entirely
(PRD 2.5).
"""
import clock


def _common(row):
    return {
        "id": row["id"],
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }


def _lean(row):
    return {"id": row["id"], "created_at": clock.fmt(row["created_at"])}


def cycle(row):
    out = _common(row)
    out.update(
        {
            "cycle_year": row["cycle_year"],
            "sport_code": row["sport_code"],
            "max_inductees": row["max_inductees"],
            "status": row["status"],
            "current_round": row["current_round"],
            "nomination_count": row["nomination_count"],
            "advanced_candidacy_count": row["advanced_candidacy_count"],
            "special_election_used": row["special_election_used"],
            "credentialed_roster_count": row["credentialed_roster_count"],
            "ceremony_date": clock.fmt(row["ceremony_date"]),
            "ceremony_venue": row["ceremony_venue"],
            "travel_budget_cents": row["travel_budget_cents"],
            "travel_committed_cents": row["travel_committed_cents"],
            "escort_pool_size": row["escort_pool_size"],
            "austerity_tier": row["austerity_tier"],
            "induction_count": row["induction_count"],
            "ceremony_ready_count": row["ceremony_ready_count"],
        }
    )
    return out


def eligibility_rule(row):
    out = _lean(row)
    out.update(
        {
            "category": row["category"],
            "pathway": row["pathway"],
            "waiting_period_years": row["waiting_period_years"],
            "min_career_seasons": row["min_career_seasons"],
            "min_career_metric": row["min_career_metric"],
            "max_ballot_appearances": row["max_ballot_appearances"],
            "election_threshold_pct": row["election_threshold_pct"],
            "carryover_min_pct": row["carryover_min_pct"],
            "runoff_floor_pct": row["runoff_floor_pct"],
        }
    )
    return out


def voter_bloc(row):
    out = _lean(row)
    out.update(
        {
            "bloc_code": row["bloc_code"],
            "name": row["name"],
            "seat_cap": row["seat_cap"],
            "min_participation_pct": row["min_participation_pct"],
            "seats_filled": row["seats_filled"],
        }
    )
    return out


def candidate(row):
    out = _common(row)
    out.update(
        {
            "full_name": row["full_name"],
            "category": row["category"],
            "retirement_year": row["retirement_year"],
            "career_seasons": row["career_seasons"],
            "career_metric_value": row["career_metric_value"],
            "is_deceased": row["is_deceased"],
            "death_year": row["death_year"],
            "hof_status": row["hof_status"],
            "permanently_ineligible_reason": row["permanently_ineligible_reason"],
            "ballot_appearances_used": row["ballot_appearances_used"],
            "veterans_eligible_from_year": row["veterans_eligible_from_year"],
        }
    )
    return out


def candidacy(row):
    out = _common(row)
    out.update(
        {
            "cycle_id": row["cycle_id"],
            "candidate_id": row["candidate_id"],
            "nominated_by_elector_id": row["nominated_by_elector_id"],
            "screened_by_elector_id": row["screened_by_elector_id"],
            "carryover_from_candidacy_id": row["carryover_from_candidacy_id"],
            "pathway": row["pathway"],
            "justification": row["justification"],
            "status": row["status"],
            "eligible_from_year": row["eligible_from_year"],
            "appearance_number": row["appearance_number"],
            "info_request_count": row["info_request_count"],
            "latest_round_votes": row["latest_round_votes"],
            "latest_round_pct": row["latest_round_pct"],
            "screening_notes": row["screening_notes"],
        }
    )
    return out


def elector(row):
    out = _common(row)
    out.update(
        {
            "full_name": row["full_name"],
            "bloc_id": row["bloc_id"],
            "is_screening_member": row["is_screening_member"],
            "credential_expires_on": clock.fmt(row["credential_expires_on"]),
            "status": row["status"],
            "consecutive_missed_cycles": row["consecutive_missed_cycles"],
            "last_participated_cycle_year": row["last_participated_cycle_year"],
            "suspension_reason": row["suspension_reason"],
        }
    )
    return out


def ballot(row):
    out = _common(row)
    out.update(
        {
            "cycle_id": row["cycle_id"],
            "round_number": row["round_number"],
            "voting_status": row["voting_status"],
            "tally_status": row["tally_status"],
            "opens_at": clock.fmt(row["opens_at"]),
            "closes_at": clock.fmt(row["closes_at"]),
            "max_votes_per_elector": row["max_votes_per_elector"],
            "slot_count": row["slot_count"],
            "ballots_cast": row["ballots_cast"],
            "total_selections_counted": row["total_selections_counted"],
            "credentialed_roster_at_close": row["credentialed_roster_at_close"],
            "threshold_votes_provisional": row["threshold_votes_provisional"],
            "threshold_votes_final": row["threshold_votes_final"],
            "elected_slot_count": row["elected_slot_count"],
            "outcome": row["outcome"],
            "tallied_by_user_id": row["tallied_by_user_id"],
            "audit_note": row["audit_note"],
        }
    )
    return out


def ballot_slot(row):
    out = _common(row)
    out.update(
        {
            "ballot_id": row["ballot_id"],
            "candidacy_id": row["candidacy_id"],
            "candidate_name_snapshot": row["candidate_name_snapshot"],
            "pathway_snapshot": row["pathway_snapshot"],
            "candidacy_version_pinned": row["candidacy_version_pinned"],
            "votes_received": row["votes_received"],
            "vote_pct": row["vote_pct"],
            "status": row["status"],
        }
    )
    return out


def vote_submission(row, reveal_selections=False):
    """Ballot secrecy (PRD 2.7): selected_slot_ids is echoed as a non-null array
    only when the acting role is IndependentAuditor."""
    out = _common(row)
    out.update(
        {
            "ballot_id": row["ballot_id"],
            "elector_id": row["elector_id"],
            "selected_slot_ids": list(row["selected_slot_ids"]) if reveal_selections else None,
            "selection_count": row["selection_count"],
            "is_abstention": row["is_abstention"],
            "status": row["status"],
            "ballot_version_after": row["ballot_version_after"],
            "cast_at": clock.fmt(row["cast_at"]),
            "invalidated_reason": row["invalidated_reason"],
        }
    )
    return out


def induction(row):
    out = _common(row)
    out.update(
        {
            "cycle_id": row["cycle_id"],
            "candidacy_id": row["candidacy_id"],
            "candidate_id": row["candidate_id"],
            "status": row["status"],
            "travel_status": row["travel_status"],
            "artifact_status": row["artifact_status"],
            "exhibit_status": row["exhibit_status"],
            "delegation_type": row["delegation_type"],
            "artifact_count": row["artifact_count"],
            "ceremony_ready": row["ceremony_ready"],
        }
    )
    return out


def travel_grant(row):
    out = _common(row)
    out.update(
        {
            "cycle_id": row["cycle_id"],
            "induction_id": row["induction_id"],
            "nights": row["nights"],
            "requested_airfare_cents": row["requested_airfare_cents"],
            "escort_from": clock.fmt(row["escort_from"]),
            "escort_to": clock.fmt(row["escort_to"]),
            "variant": row["variant"],
            "traveler_count": row["traveler_count"],
            "austerity_tier_applied": row["austerity_tier_applied"],
            "award_cents": row["award_cents"],
            "status": row["status"],
            "cycle_version_after": row["cycle_version_after"],
            "cancellation_reason": row["cancellation_reason"],
        }
    )
    return out


def exhibit_case(row):
    out = _common(row)
    out.update(
        {
            "case_code": row["case_code"],
            "capacity_artifacts": row["capacity_artifacts"],
            "changeover_buffer_days": row["changeover_buffer_days"],
            "artifacts_installed": row["artifacts_installed"],
        }
    )
    return out


def exhibit_installation(row):
    out = _common(row)
    out.update(
        {
            "induction_id": row["induction_id"],
            "exhibit_case_id": row["exhibit_case_id"],
            "display_starts_on": clock.fmt(row["display_starts_on"]),
            "display_ends_on": clock.fmt(row["display_ends_on"]),
            "artifact_count": row["artifact_count"],
            "status": row["status"],
        }
    )
    return out

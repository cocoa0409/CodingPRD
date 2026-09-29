"""Resource representations.  Read-only projections (PRD 2.9) are derived at
serialization time so they can never drift from the stored rows."""
from constants import ALLOCATED_AWARD_STATUSES, BONUS_CATEGORIES
from services import lookup


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def edition_ledger(edition):
    committed = sum(
        inv["guaranteed_commitment_cents"]
        for inv in lookup.edition_invitations(edition["id"])
        if inv["status"] == "ACCEPTED"
    )
    awards = [
        a for a in lookup.edition_awards(edition["id"])
        if a["status"] in ALLOCATED_AWARD_STATUSES
    ]
    allocated = sum(a["gross_amount_cents"] for a in awards)
    bonus = sum(a["gross_amount_cents"] for a in awards if a["category"] in BONUS_CATEGORIES)
    return {
        "appearance_committed_cents": committed,
        "appearance_uncommitted_cents": edition["appearance_budget_cents"] - committed,
        "purse_allocated_cents": allocated,
        "purse_unallocated_cents": edition["total_purse_cents"] - allocated,
        "bonus_pool_consumed_cents": bonus,
    }


def ser_edition(edition):
    out = _common(edition)
    ledger = edition_ledger(edition)
    out.update({
        "name": edition["name"],
        "city": edition["city"],
        "race_date": edition["race_date"],
        "status": edition["status"],
        "appearance_budget_cents": edition["appearance_budget_cents"],
        "appearance_committed_cents": ledger["appearance_committed_cents"],
        "appearance_uncommitted_cents": ledger["appearance_uncommitted_cents"],
        "total_purse_cents": edition["total_purse_cents"],
        "purse_allocated_cents": ledger["purse_allocated_cents"],
        "purse_unallocated_cents": ledger["purse_unallocated_cents"],
        "bonus_pool_cap_cents": edition["bonus_pool_cap_cents"],
        "bonus_pool_consumed_cents": ledger["bonus_pool_consumed_cents"],
        "course_record_male_seconds": edition["course_record_male_seconds"],
        "course_record_female_seconds": edition["course_record_female_seconds"],
        "course_record_wheelchair_male_seconds": edition["course_record_wheelchair_male_seconds"],
        "course_record_wheelchair_female_seconds": edition["course_record_wheelchair_female_seconds"],
        "offer_response_days": edition["offer_response_days"],
        "max_negotiation_rounds": edition["max_negotiation_rounds"],
        "masters_min_age": edition["masters_min_age"],
        "expired_offer_count": edition["expired_offer_count"],
    })
    return out


def ser_purse_line(line):
    out = _common(line)
    out.update({
        "race_edition_id": line["race_edition_id"],
        "category": line["category"],
        "division": line["division"],
        "gender": line["gender"],
        "place": line["place"],
        "threshold_seconds": line["threshold_seconds"],
        "amount_cents": line["amount_cents"],
    })
    return out


def ser_standard(std):
    out = _common(std)
    out.update({
        "race_edition_id": std["race_edition_id"],
        "division": std["division"],
        "gender": std["gender"],
        "max_qualifying_seconds": std["max_qualifying_seconds"],
        "window_months": std["window_months"],
        "requires_chip_timing": std["requires_chip_timing"],
        "bib_range_start": std["bib_range_start"],
        "bib_range_end": std["bib_range_end"],
    })
    return out


def ser_athlete(athlete):
    out = _common(athlete)
    out.update({
        "full_name": athlete["full_name"],
        "country_code": athlete["country_code"],
        "gender": athlete["gender"],
        "birth_date": athlete["birth_date"],
        "tax_residency_country": athlete["tax_residency_country"],
        "w8ben_on_file": athlete["w8ben_on_file"],
        "treaty_withholding_bps": athlete["treaty_withholding_bps"],
        "whereabouts_filed": athlete["whereabouts_filed"],
        "missed_test_count": athlete["missed_test_count"],
    })
    return out


def ser_agent(agent):
    out = _common(agent)
    out.update({
        "agency_name": agent["agency_name"],
        "license_code": agent["license_code"],
        "commission_bps": agent["commission_bps"],
        "status": agent["status"],
    })
    return out


def ser_performance(record):
    out = _common(record)
    out.update({
        "athlete_id": record["athlete_id"],
        "race_name": record["race_name"],
        "performance_date": record["performance_date"],
        "performance_seconds": record["performance_seconds"],
        "division": record["division"],
        "chip_timed": record["chip_timed"],
        "sanctioning_ref": record["sanctioning_ref"],
        "verification_status": record["verification_status"],
        "verified_seconds": record["verified_seconds"],
        "rejection_reason": record["rejection_reason"],
    })
    return out


def ser_invitation(inv):
    out = _common(inv)
    out.update({
        "race_edition_id": inv["race_edition_id"],
        "athlete_id": inv["athlete_id"],
        "agent_id": inv["agent_id"],
        "qualifying_performance_id": inv["qualifying_performance_id"],
        "division": inv["division"],
        "status": inv["status"],
        "current_appearance_fee_cents": inv["current_appearance_fee_cents"],
        "current_air_class": inv["current_air_class"],
        "current_hotel_nights": inv["current_hotel_nights"],
        "current_ground_transport": inv["current_ground_transport"],
        "round_count": len(lookup.invitation_rounds(inv["id"])),
        "offer_sent_at": inv["offer_sent_at"],
        "response_deadline_at": inv["response_deadline_at"],
        "guaranteed_commitment_cents": inv["guaranteed_commitment_cents"],
        "full_exposure_cents": inv["full_exposure_cents"],
        "bib_number": inv["bib_number"],
        "negotiated_by_user_id": inv["negotiated_by_user_id"],
    })
    return out


def ser_round(rnd):
    # NegotiationRound carries only id and created_at (PRD 2.5).
    return {
        "id": rnd["id"],
        "created_at": rnd["created_at"],
        "invitation_id": rnd["invitation_id"],
        "round_number": rnd["round_number"],
        "side": rnd["side"],
        "appearance_fee_cents": rnd["appearance_fee_cents"],
        "air_class": rnd["air_class"],
        "hotel_nights": rnd["hotel_nights"],
        "ground_transport": rnd["ground_transport"],
        "note": rnd["note"],
    }


def ser_pacer(pacer):
    out = _common(pacer)
    out.update({
        "race_edition_id": pacer["race_edition_id"],
        "pacer_license_code": pacer["pacer_license_code"],
        "pacer_name": pacer["pacer_name"],
        "target_pace_seconds_per_km": pacer["target_pace_seconds_per_km"],
        "start_km": pacer["start_km"],
        "end_km": pacer["end_km"],
        "assistance_rule": pacer["assistance_rule"],
    })
    return out


def ser_slot(slot):
    out = _common(slot)
    out.update({
        "invitation_id": slot["invitation_id"],
        "station_km": slot["station_km"],
        "table_position": slot["table_position"],
        "bottle_count": slot["bottle_count"],
        "occupied_from": slot["table_position"],
        "occupied_to": slot["table_position"] + slot["bottle_count"] - 1,
        "status": slot["status"],
    })
    return out


def ser_doping_test(test):
    out = _common(test)
    out.update({
        "athlete_id": test["athlete_id"],
        "race_edition_id": test["race_edition_id"],
        "test_type": test["test_type"],
        "window_start_at": test["window_start_at"],
        "window_end_at": test["window_end_at"],
        "sample_code": test["sample_code"],
        "status": test["status"],
        "collected_at": test["collected_at"],
        "collected_sample_ref": test["collected_sample_ref"],
        "outcome_notes": test["outcome_notes"],
    })
    return out


def ser_result(result):
    out = _common(result)
    out.update({
        "race_edition_id": result["race_edition_id"],
        "invitation_id": result["invitation_id"],
        "athlete_id": result["athlete_id"],
        "division": result["division"],
        "gun_seconds": result["gun_seconds"],
        "net_seconds": result["net_seconds"],
        "official_seconds": result["official_seconds"],
        "certification_status": result["certification_status"],
        "record_claim_status": result["record_claim_status"],
        "dq_reason": result["dq_reason"],
        "place_overall": result["place_overall"],
        "place_division": result["place_division"],
        "place_masters": result["place_masters"],
        "tie_group_size": result["tie_group_size"],
        "is_masters": result["is_masters"],
        "sanctioning_submission_ref": result["sanctioning_submission_ref"],
    })
    return out


def ser_award(award):
    out = _common(award)
    out.update({
        "race_edition_id": award["race_edition_id"],
        "race_result_id": award["race_result_id"],
        "athlete_id": award["athlete_id"],
        "category": award["category"],
        "place": award["place"],
        "tie_share_count": award["tie_share_count"],
        "gross_amount_cents": award["gross_amount_cents"],
        "withholding_variant": award["withholding_variant"],
        "withholding_bps": award["withholding_bps"],
        "withholding_cents": award["withholding_cents"],
        "net_amount_cents": award["net_amount_cents"],
        "status": award["status"],
        "approved_by_user_id": award["approved_by_user_id"],
        "paid_by_user_id": award["paid_by_user_id"],
        "payment_reference": award["payment_reference"],
        "paid_at": award["paid_at"],
    })
    return out

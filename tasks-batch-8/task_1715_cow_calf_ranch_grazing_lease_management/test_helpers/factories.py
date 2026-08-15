"""Payload factories — one per entity, input fields only."""
from .constants import DEFAULT_LEASE_TERMS


def create_ranch_payload(name="Test Ranch", hq_state="MT", **overrides) -> dict:
    defaults = {"name": name, "hq_state": hq_state}
    defaults.update(overrides)
    return defaults


def create_pasture_payload(ranch_id, name="Section", acreage=1000, tenure="DEEDED",
                           forage_type="NATIVE_RANGE", base_capacity_aum=100,
                           **overrides) -> dict:
    defaults = {
        "ranch_id": ranch_id,
        "name": name,
        "acreage": acreage,
        "tenure": tenure,
        "forage_type": forage_type,
        "base_capacity_aum": base_capacity_aum,
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(ranch_id, pasture_id, lessor_name="Lessor",
                         start_date="2026-01-01", end_date="2026-12-31",
                         aum_allotment=50, settlement_basis="ACTUAL_USE",
                         **overrides) -> dict:
    defaults = {
        "ranch_id": ranch_id,
        "pasture_id": pasture_id,
        "lessor_name": lessor_name,
        "start_date": start_date,
        "end_date": end_date,
        "aum_allotment": aum_allotment,
        "settlement_basis": settlement_basis,
        **DEFAULT_LEASE_TERMS,
    }
    defaults.update(overrides)
    return defaults


def create_lease_statement_payload(lease_id, ranch_id, period_year=2026) -> dict:
    return {"lease_id": lease_id, "ranch_id": ranch_id, "period_year": period_year}


def create_herd_group_payload(ranch_id, group_name="Cows", animal_class="MATURE_COW",
                              head_count=60, avg_weight_lbs=1000, **overrides) -> dict:
    defaults = {
        "ranch_id": ranch_id,
        "group_name": group_name,
        "animal_class": animal_class,
        "head_count": head_count,
        "avg_weight_lbs": avg_weight_lbs,
    }
    defaults.update(overrides)
    return defaults


def record_reduction_payload(head_count, reason, destock_order_id=None) -> dict:
    payload = {"head_count": head_count, "reason": reason}
    if destock_order_id is not None:
        payload["destock_order_id"] = destock_order_id
    return payload


def create_breeding_season_payload(ranch_id, herd_group_id, season_year=2026,
                                   planned_turnout_date="2026-04-15",
                                   planned_removal_date="2026-06-15",
                                   exposed_head_count=25, **overrides) -> dict:
    defaults = {
        "ranch_id": ranch_id,
        "herd_group_id": herd_group_id,
        "season_year": season_year,
        "planned_turnout_date": planned_turnout_date,
        "planned_removal_date": planned_removal_date,
        "exposed_head_count": exposed_head_count,
    }
    defaults.update(overrides)
    return defaults


def create_bull_payload(ranch_id, tag="B1", breed="ANGUS", birth_year=2021,
                        **overrides) -> dict:
    defaults = {
        "ranch_id": ranch_id,
        "tag": tag,
        "breed": breed,
        "birth_year": birth_year,
    }
    defaults.update(overrides)
    return defaults


def record_bse_payload(result="PASSED", exam_date="2026-03-01", scrotal_cm=35.0) -> dict:
    return {"result": result, "exam_date": exam_date, "scrotal_cm": scrotal_cm}


def create_bull_turnout_payload(bull_id, breeding_season_id, ranch_id,
                                turnout_date="2026-04-15",
                                planned_removal_date="2026-06-15") -> dict:
    return {
        "bull_id": bull_id,
        "breeding_season_id": breeding_season_id,
        "ranch_id": ranch_id,
        "turnout_date": turnout_date,
        "planned_removal_date": planned_removal_date,
    }


def create_preg_check_payload(breeding_season_id, ranch_id, check_date="2026-09-01") -> dict:
    return {
        "breeding_season_id": breeding_season_id,
        "ranch_id": ranch_id,
        "check_date": check_date,
    }


def finalize_preg_check_payload(pregnant_count, open_count, dead_count) -> dict:
    return {
        "pregnant_count": pregnant_count,
        "open_count": open_count,
        "dead_count": dead_count,
    }


def create_calf_crop_payload(breeding_season_id, ranch_id, crop_year=2026,
                             steer_head=100, heifer_head=60) -> dict:
    return {
        "breeding_season_id": breeding_season_id,
        "ranch_id": ranch_id,
        "crop_year": crop_year,
        "steer_head": steer_head,
        "heifer_head": heifer_head,
    }


def record_weaning_payload(weaning_date="2026-09-15", avg_wean_weight_lbs=560,
                           avg_wean_age_days=200, avg_birth_weight_lbs=80,
                           avg_dam_age_years=5) -> dict:
    return {
        "weaning_date": weaning_date,
        "avg_wean_weight_lbs": avg_wean_weight_lbs,
        "avg_wean_age_days": avg_wean_age_days,
        "avg_birth_weight_lbs": avg_birth_weight_lbs,
        "avg_dam_age_years": avg_dam_age_years,
    }


def record_vaccine_payload(round_number, vaccine_date) -> dict:
    return {"round_number": round_number, "vaccine_date": vaccine_date}


def create_sale_lot_payload(calf_crop_id, ranch_id, lot_class="STEER", head_count=10,
                            base_price_cents_per_cwt=23000, slide_cents_per_lb=10,
                            base_weight_lbs=520, shrink_pct=0.03,
                            precon_claim="NONE", freight_cents_per_head=3000,
                            commission_pct=0.025, **overrides) -> dict:
    defaults = {
        "calf_crop_id": calf_crop_id,
        "ranch_id": ranch_id,
        "lot_class": lot_class,
        "head_count": head_count,
        "base_price_cents_per_cwt": base_price_cents_per_cwt,
        "slide_cents_per_lb": slide_cents_per_lb,
        "base_weight_lbs": base_weight_lbs,
        "shrink_pct": shrink_pct,
        "precon_claim": precon_claim,
        "freight_cents_per_head": freight_cents_per_head,
        "commission_pct": commission_pct,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(pasture_id, herd_group_id, ranch_id,
                              start_date="2026-06-01",
                              planned_end_date="2026-07-31") -> dict:
    return {
        "pasture_id": pasture_id,
        "herd_group_id": herd_group_id,
        "ranch_id": ranch_id,
        "start_date": start_date,
        "planned_end_date": planned_end_date,
    }


def create_supplement_program_payload(herd_group_id, ranch_id, program_type="MINERAL",
                                      start_date="2026-01-01", end_date="2026-02-28",
                                      feed_rate_oz_per_head_day=4,
                                      cost_cents_per_ton=240000) -> dict:
    return {
        "herd_group_id": herd_group_id,
        "ranch_id": ranch_id,
        "program_type": program_type,
        "start_date": start_date,
        "end_date": end_date,
        "feed_rate_oz_per_head_day": feed_rate_oz_per_head_day,
        "cost_cents_per_ton": cost_cents_per_ton,
    }


def record_delivery_payload(delivered_lbs, delivery_date="2026-01-10") -> dict:
    return {"delivered_lbs": delivered_lbs, "delivery_date": delivery_date}


def create_drought_assessment_payload(ranch_id, assessment_date, pasture_measurements) -> dict:
    return {
        "ranch_id": ranch_id,
        "assessment_date": assessment_date,
        "pasture_measurements": pasture_measurements,
    }

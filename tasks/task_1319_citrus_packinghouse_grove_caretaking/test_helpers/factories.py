"""Payload factories — one per create endpoint, input fields only (PRD §3)."""

from .constants import (
    DEFAULT_SAMPLED_AT,
    DEFAULT_WEEK_START,
    PASSING_SAMPLE,
    TEST_DEFAULTS,
)


def create_grower_payload(grower_code="GR-1", display_name="Test Grower", **overrides):
    payload = {"grower_code": grower_code, "display_name": display_name}
    payload.update(overrides)
    return payload


def create_grove_payload(grower_id, block_code="B1", variety="HAMLIN", acreage=50,
                         county_code=TEST_DEFAULTS["COUNTY_CODE"],
                         caretaking_enrolled=False, **overrides):
    payload = {
        "grower_id": grower_id,
        "block_code": block_code,
        "variety": variety,
        "acreage": acreage,
        "county_code": county_code,
        "caretaking_enrolled": caretaking_enrolled,
    }
    payload.update(overrides)
    return payload


def create_maturity_test_payload(expected_grove_version, sampled_at=DEFAULT_SAMPLED_AT,
                                 brix=9.0, acid_pct=1.0, juice_pct=45.0, **overrides):
    payload = {
        "sampled_at": sampled_at,
        "brix": brix,
        "acid_pct": acid_pct,
        "juice_pct": juice_pct,
        "expected_grove_version": expected_grove_version,
    }
    payload.update(overrides)
    return payload


def passing_maturity_payload(variety, expected_grove_version,
                             sampled_at=DEFAULT_SAMPLED_AT, **overrides):
    """A measurement set that satisfies every minimum of the given variety."""
    values = dict(PASSING_SAMPLE[variety])
    values.update(overrides)
    return create_maturity_test_payload(
        expected_grove_version, sampled_at=sampled_at, **values)


def create_crew_payload(crew_code="CR-1",
                        daily_capacity_boxes=TEST_DEFAULTS["CREW_CAPACITY"],
                        **overrides):
    payload = {"crew_code": crew_code, "daily_capacity_boxes": daily_capacity_boxes}
    payload.update(overrides)
    return payload


def create_assignment_payload(crew_id, grove_id,
                              window_start=TEST_DEFAULTS["WINDOW_START"],
                              window_end=TEST_DEFAULTS["WINDOW_END"],
                              planned_boxes=100, **overrides):
    payload = {
        "crew_id": crew_id,
        "grove_id": grove_id,
        "window_start": window_start,
        "window_end": window_end,
        "planned_boxes": planned_boxes,
    }
    payload.update(overrides)
    return payload


def create_delivery_payload(grove_id, assignment_id, gross_boxes=100, tare_boxes=0,
                            **overrides):
    payload = {
        "grove_id": grove_id,
        "assignment_id": assignment_id,
        "gross_boxes": gross_boxes,
        "tare_boxes": tare_boxes,
    }
    payload.update(overrides)
    return payload


def create_room_payload(room_code="RM-1",
                        capacity_boxes=TEST_DEFAULTS["ROOM_CAPACITY"],
                        min_hours=12, max_hours=72, **overrides):
    payload = {
        "room_code": room_code,
        "capacity_boxes": capacity_boxes,
        "min_hours": min_hours,
        "max_hours": max_hours,
    }
    payload.update(overrides)
    return payload


def create_session_payload(room_id, delivery_id, boxes, planned_hours=24,
                           color_add_applied=None, **overrides):
    payload = {
        "room_id": room_id,
        "delivery_id": delivery_id,
        "boxes": boxes,
        "planned_hours": planned_hours,
    }
    if color_add_applied is not None:
        payload["color_add_applied"] = color_add_applied
    payload.update(overrides)
    return payload


def create_sort_run_payload(delivery_id, expected_delivery_version,
                            fancy_boxes=0, choice_boxes=0, standard_boxes=0,
                            juice_boxes=0, cull_boxes=0,
                            color_score=8, defect_pct=5, **overrides):
    payload = {
        "delivery_id": delivery_id,
        "fancy_boxes": fancy_boxes,
        "choice_boxes": choice_boxes,
        "standard_boxes": standard_boxes,
        "juice_boxes": juice_boxes,
        "cull_boxes": cull_boxes,
        "color_score": color_score,
        "defect_pct": defect_pct,
        "expected_delivery_version": expected_delivery_version,
    }
    payload.update(overrides)
    return payload


def create_channel_payload(channel_code, channel_type, destination_market, variety,
                           week_start=DEFAULT_WEEK_START, allocation_boxes=0,
                           price_cents_per_box=220, priority_rank=9,
                           accepts_grades=("FANCY", "CHOICE", "STANDARD", "JUICE"),
                           **overrides):
    payload = {
        "channel_code": channel_code,
        "channel_type": channel_type,
        "destination_market": destination_market,
        "variety": variety,
        "week_start": week_start,
        "allocation_boxes": allocation_boxes,
        "price_cents_per_box": price_cents_per_box,
        "priority_rank": priority_rank,
        "accepts_grades": list(accepts_grades),
    }
    payload.update(overrides)
    return payload


def create_pool_payload(variety="HAMLIN", week_start=DEFAULT_WEEK_START, **overrides):
    payload = {"variety": variety, "week_start": week_start}
    payload.update(overrides)
    return payload


def create_advance_payload(grower_id, pool_id, amount_cents, recoup_policy=None,
                           **overrides):
    payload = {"grower_id": grower_id, "pool_id": pool_id, "amount_cents": amount_cents}
    if recoup_policy is not None:
        payload["recoup_policy"] = recoup_policy
    payload.update(overrides)
    return payload


def create_caretaking_order_payload(grove_id, service_type="MOW",
                                    service_date="2026-08-01", acres_treated=1,
                                    chemical_cost_cents=None, **overrides):
    payload = {
        "grove_id": grove_id,
        "service_type": service_type,
        "service_date": service_date,
        "acres_treated": acres_treated,
    }
    if chemical_cost_cents is not None:
        payload["chemical_cost_cents"] = chemical_cost_cents
    payload.update(overrides)
    return payload


def create_caretaking_invoice_payload(grower_id, period_start="2026-08-01",
                                      period_end="2026-08-31", **overrides):
    payload = {
        "grower_id": grower_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def create_quarantine_order_payload(scope_type="GROVE", grove_id=None, county_code=None,
                                    pest_type="CANKER", **overrides):
    payload = {"scope_type": scope_type, "pest_type": pest_type}
    if grove_id is not None:
        payload["grove_id"] = grove_id
    if county_code is not None:
        payload["county_code"] = county_code
    payload.update(overrides)
    return payload


def create_export_lot_payload(destination_market, variety, grade, boxes,
                              source_channel_id, source_grove_id,
                              cold_treatment_hours=None, **overrides):
    payload = {
        "destination_market": destination_market,
        "variety": variety,
        "grade": grade,
        "boxes": boxes,
        "source_channel_id": source_channel_id,
        "source_grove_id": source_grove_id,
    }
    if cold_treatment_hours is not None:
        payload["cold_treatment_hours"] = cold_treatment_hours
    payload.update(overrides)
    return payload


def create_phyto_certificate_payload(certificate_number="PC-1", inspection_result="PASS",
                                     **overrides):
    payload = {
        "certificate_number": certificate_number,
        "inspection_result": inspection_result,
    }
    payload.update(overrides)
    return payload

"""Payload factories --- input fields only, never server-computed fields.

Each factory returns a valid creation payload for one entity and accepts
``**overrides`` so a test can vary exactly the field under examination.
Monetary, dose and hour amounts are emitted as JSON numbers, never as strings.
"""

import itertools

from .types import (
    Craft,
    HoldPointType,
    ReservationPurpose,
    SafetyFunctionCode,
    StationUnit,
    WorkOrderType,
)

_counter = itertools.count(1)


def _seq():
    return next(_counter)


def create_spent_fuel_pool_payload(**overrides):
    """PRD 3.1: cells_total > 0, 0 <= cells_baseline_occupied <= cells_total,
    full_core_offload_reserve_cells >= 0."""
    payload = {
        "station_unit": StationUnit.UNIT_1,
        "cells_total": 1200,
        "cells_baseline_occupied": 900,
        "full_core_offload_reserve_cells": 193,
    }
    payload.update(overrides)
    return payload


def create_rad_area_payload(**overrides):
    """PRD 3.1: area_code 1-32 chars unique per station_unit,
    dose_rate_mrem_per_hr > 0, occupancy_limit_workers >= 1,
    survey_buffer_hours >= 0."""
    payload = {
        "station_unit": StationUnit.UNIT_1,
        "area_code": "RA-{}".format(_seq()),
        "dose_rate_mrem_per_hr": 25,
        "occupancy_limit_workers": 12,
        "survey_buffer_hours": 2,
    }
    payload.update(overrides)
    return payload


def create_safety_function_payload(**overrides):
    """PRD 3.1: trains_total >= 1 and 0 <= min_trains_required <=
    trains_total."""
    payload = {
        "station_unit": StationUnit.UNIT_1,
        "function_code": SafetyFunctionCode.DECAY_HEAT_REMOVAL,
        "trains_total": 3,
        "min_trains_required": 2,
    }
    payload.update(overrides)
    return payload


def create_outage_payload(**overrides):
    """PRD 3.2: duration_target_hours, dose_budget_total_mrem and
    cost_budget_usd must each be greater than zero."""
    payload = {
        "station_unit": StationUnit.UNIT_1,
        "designation": "1R{}".format(_seq()),
        "duration_target_hours": 720,
        "dose_budget_total_mrem": 5000,
        "cost_budget_usd": 40000000,
        "scope_freeze_at": "2026-08-15T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(**overrides):
    """PRD 3.2: estimated_hours > 0, estimated_cost_usd >= 0,
    estimated_dose_mrem >= 0, title 1-200 characters."""
    payload = {
        "wo_type": WorkOrderType.MAINTENANCE,
        "title": "Feedwater pump overhaul",
        "estimated_hours": 10,
        "estimated_cost_usd": 1000,
        "estimated_dose_mrem": 0,
    }
    payload.update(overrides)
    return payload


def create_schedule_activity_payload(**overrides):
    """PRD 3.4: label 1-200 characters, planned_start_offset_hours >= 0 and
    planned_duration_hours > 0."""
    payload = {
        "label": "Cavity flood-up",
        "planned_start_offset_hours": 0,
        "planned_duration_hours": 100,
    }
    payload.update(overrides)
    return payload


def create_core_load_pattern_payload(**overrides):
    """PRD 3.3: cycle_length_mwd_mtu > 0, fresh_assembly_count >= 1 and
    discharge_assembly_count >= 0. Yields reactivity_margin_pcm 1586.00."""
    payload = {
        "cycle_length_mwd_mtu": 18000,
        "fresh_assembly_count": 88,
        "discharge_assembly_count": 80,
    }
    payload.update(overrides)
    return payload


def create_pool_cell_reservation_payload(**overrides):
    """PRD 3.3: cells_requested at least 1, purpose one of DISCHARGE,
    FRESH_STAGING or CONTINGENCY."""
    payload = {
        "cells_requested": 5,
        "purpose": ReservationPurpose.CONTINGENCY,
    }
    payload.update(overrides)
    return payload


def create_supplemental_worker_payload(**overrides):
    """PRD 3.5: full_name 1-120 characters, craft from the six listed
    classifications, sponsoring_contractor 1-120 characters."""
    payload = {
        "full_name": "R. Ostrander",
        "craft": Craft.PIPEFITTER,
        "sponsoring_contractor": "Bartlett Nuclear",
    }
    payload.update(overrides)
    return payload


def create_rwp_payload(**overrides):
    """PRD 3.7: worker_count >= 1, 0 <= shielding_factor <= 0.95,
    planned_start_offset_hours >= 0, planned_duration_hours > 0."""
    payload = {
        "worker_count": 2,
        "shielding_factor": 0.5,
        "planned_start_offset_hours": 0,
        "planned_duration_hours": 6,
    }
    payload.update(overrides)
    return payload


def create_emergent_item_payload(**overrides):
    """PRD 3.8: description 1-500 characters, estimated_hours > 0,
    estimated_cost_usd >= 0, estimated_dose_mrem >= 0."""
    payload = {
        "description": "Degraded valve packing found once insulation was removed",
        "estimated_hours": 90,
        "estimated_cost_usd": 400000,
        "estimated_dose_mrem": 150,
    }
    payload.update(overrides)
    return payload


def create_startup_test_payload(**overrides):
    """PRD 3.9: test_code 1-32 characters, sequence_index at least 1,
    hold_point_type one of REGULATORY, STATION or NONE."""
    payload = {
        "test_code": "STP-01",
        "sequence_index": 1,
        "hold_point_type": HoldPointType.STATION,
        "predicted_reactivity_pcm": 500,
    }
    payload.update(overrides)
    return payload


def post_outage_review_payload(**overrides):
    """PRD 3.9: actual_duration_hours > 0, actual_cost_usd >= 0, optional
    review_notes of up to 2000 characters."""
    payload = {
        "actual_duration_hours": 780,
        "actual_cost_usd": 42000000,
    }
    payload.update(overrides)
    return payload

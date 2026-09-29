"""Payload factories — one per creation endpoint, input fields only.

Every factory returns a dict carrying the fields the PRD declares as client
input for that operation, and accepts ``**overrides`` so a test can pin the one
value it cares about.  Optional fields the PRD marks optional are omitted
unless overridden.
"""

import itertools

_counter = itertools.count(1)


def _seq():
    return next(_counter)


# ---------------------------------------------------------------------------
# Trading partners (PRD §3.1)
# ---------------------------------------------------------------------------


def create_plant_payload(**overrides):
    payload = {
        "name": "Champion Chandler",
        "state_code": "AZ",
        "hud_plant_code": f"AZ-{_seq():05d}",
    }
    payload.update(overrides)
    return payload


def create_hauler_payload(**overrides):
    payload = {
        "name": "Desert Toter",
        "dot_number": f"DOT-{_seq():06d}",
        "insurance_expiry_date": "2027-01-31",
        "endorsed_states": ["AZ"],
    }
    payload.update(overrides)
    return payload


def create_escort_crew_payload(**overrides):
    payload = {
        "vendor_name": "Sonoran Escort",
        "endorsed_states": ["AZ"],
        "certified_roles": ["ESCORT"],
        "endorsement_class": "SUPERLOAD",
    }
    payload.update(overrides)
    return payload


def create_set_crew_payload(**overrides):
    payload = {
        "company_name": "Sonoran Set",
        "hud_installer_license_no": f"AZ-INST-{_seq():05d}",
        "license_state": "AZ",
        "license_expiry_date": "2027-06-30",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Orders, floors and sites (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------


def create_order_payload(plant_id, **overrides):
    payload = {
        "plant_id": plant_id,
        "dealer_name": "Valley Homes",
        "home_model": "Titan 1660",
        "section_count": 1,
        "destination_state": "AZ",
        "wind_zone": "I",
    }
    payload.update(overrides)
    return payload


def create_section_payload(order_id, **overrides):
    payload = {
        "order_id": order_id,
        "section_index": 1,
        "declared_width_in": 168,
        "declared_height_in": 150,
        "declared_length_in": 720,
        "declared_weight_lb": 22000,
    }
    payload.update(overrides)
    return payload


def measure_section_payload(**overrides):
    payload = {"measured_width_in": 168, "measured_height_in": 150}
    payload.update(overrides)
    return payload


def amend_section_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


def create_site_payload(order_id, **overrides):
    payload = {
        "order_id": order_id,
        "pad_type": "RUNNER",
        "pier_plan_ref": "PP-1660-A",
        "pier_count": 6,
        "utility_water": True,
        "utility_sewer": True,
        "utility_electric": True,
    }
    payload.update(overrides)
    return payload


def readiness_inspection_payload(**overrides):
    payload = {"pad_pass": True, "pier_plan_pass": True, "utility_pass": True}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Permits, legs and escort reservations (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------


def create_permit_payload(section_id, expected_section_version, **overrides):
    payload = {
        "section_id": section_id,
        "state_code": "AZ",
        "planned_leg_count": 1,
        "expected_section_version": expected_section_version,
    }
    payload.update(overrides)
    return payload


def pay_permit_fee_payload(amount_cents, **overrides):
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def revoke_permit_payload(**overrides):
    payload = {"reason_code": "BRIDGE_POSTING"}
    payload.update(overrides)
    return payload


def create_route_leg_payload(permit_id, hauler_id, **overrides):
    payload = {
        "permit_id": permit_id,
        "hauler_id": hauler_id,
        "sequence_no": 1,
        "corridor_id": "AZ-I10",
        "state_code": "AZ",
        "window_start": "2026-08-03T06:00:00.000Z",
        "window_end": "2026-08-03T14:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_escort_assignment_payload(route_leg_id, escort_crew_id, **overrides):
    payload = {
        "route_leg_id": route_leg_id,
        "escort_crew_id": escort_crew_id,
        "role": "ESCORT",
        "window_start": "2026-08-03T06:00:00.000Z",
        "window_end": "2026-08-03T14:00:00.000Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Set jobs, joints and anchoring (PRD §3.6, §3.7, §3.8)
# ---------------------------------------------------------------------------


def create_set_job_payload(order_id, set_crew_id, expected_order_version, **overrides):
    payload = {
        "order_id": order_id,
        "set_crew_id": set_crew_id,
        "scheduled_start_date": "2026-08-10",
        "scheduled_end_date": "2026-08-11",
        "labor_base_cents": 480000,
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def scope_split_payload(**overrides):
    payload = {
        "skirting_owner": "INSTALLER",
        "steps_owner": "INSTALLER",
        "skirting_linear_ft": 52,
        "steps_count": 1,
    }
    payload.update(overrides)
    return payload


def utility_crossover_payload(crossover_count=1, **overrides):
    payload = {"crossover_count": crossover_count}
    payload.update(overrides)
    return payload


def final_inspection_payload(punch_item_count=0, **overrides):
    payload = {"punch_item_count": punch_item_count, "notes": "final walk complete"}
    payload.update(overrides)
    return payload


def create_marriage_joint_payload(set_job_id, joint_index=1, **overrides):
    payload = {
        "set_job_id": set_job_id,
        "joint_index": joint_index,
        "gap_in": 0.25,
        "vertical_offset_in": 0.0,
        "ridge_beam_shim_in": 0.0,
    }
    payload.update(overrides)
    return payload


def create_anchor_certification_payload(set_job_id, **overrides):
    payload = {
        "set_job_id": set_job_id,
        "anchor_count": 8,
        "avg_torque_ft_lb": 180,
        "strap_count": 8,
        "pier_count": 6,
    }
    payload.update(overrides)
    return payload


def review_anchor_certification_payload(decision="CERTIFY", **overrides):
    payload = {"decision": decision, "findings": "reviewed on site"}
    payload.update(overrides)
    return payload


def resubmit_anchor_certification_payload(**overrides):
    payload = {
        "anchor_count": 8,
        "avg_torque_ft_lb": 180,
        "strap_count": 8,
        "pier_count": 6,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Damage claims (PRD §3.9)
# ---------------------------------------------------------------------------


def create_damage_claim_payload(order_id, section_id, hauler_id, set_crew_id, **overrides):
    payload = {
        "order_id": order_id,
        "section_id": section_id,
        "hauler_id": hauler_id,
        "set_crew_id": set_crew_id,
        "discovered_stage": "IN_TRANSIT",
        "claimed_amount_cents": 100000,
    }
    payload.update(overrides)
    return payload


def review_damage_claim_payload(**overrides):
    payload = {"notes": "photographs received from both ends of the haul"}
    payload.update(overrides)
    return payload


def dispute_damage_claim_payload(**overrides):
    payload = {"reason_code": "WRONG_PARTY"}
    payload.update(overrides)
    return payload


def adjudicate_damage_claim_payload(allocation_basis="STAGE", **overrides):
    payload = {"allocation_basis": allocation_basis}
    payload.update(overrides)
    return payload


def reverse_damage_claim_payload(**overrides):
    payload = {"reason_code": "NEW_EVIDENCE"}
    payload.update(overrides)
    return payload


def set_clock_payload(current_utc="2026-08-01T00:00:00Z", **overrides):
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload

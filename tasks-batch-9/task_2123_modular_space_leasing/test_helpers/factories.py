"""Payload factories — one per creatable resource, input fields only."""

# ─── Catalog defaults ────────────────────────────────────────────────────────

DALLAS_YARD = {
    "name": "Dallas Yard",
    "region_code": "TX-N",
    "yard_capacity_units": 25,
    "daily_dispatch_capacity": 2,
    "labor_rate_cents_per_hour": 9_200,
}

AUSTIN_YARD = {
    "name": "Austin Yard",
    "region_code": "TX-C",
    "yard_capacity_units": 10,
    "daily_dispatch_capacity": 3,
    "labor_rate_cents_per_hour": 8_800,
}

TX_DAL = {
    "code": "TX-DAL",
    "name": "Dallas County",
    "permit_required": True,
    "permit_lead_days": 21,
    "anchoring_standard": "PIER_FOUNDATION",
    "wind_zone": 2,
    "permit_fee_cents": 145_000,
    "ada_ramp_required": True,
    "min_ramp_run_ratio": 12.0,
}

TX_RUR = {
    "code": "TX-RUR",
    "name": "Rural County",
    "permit_required": False,
    "permit_lead_days": 0,
    "anchoring_standard": "GROUND_ANCHOR",
    "wind_zone": 1,
    "permit_fee_cents": 0,
    "ada_ramp_required": False,
    "min_ramp_run_ratio": 12.0,
}

SPEC_MOB_2460 = {
    "model_code": "MOB-2460",
    "width_ft": 24,
    "length_ft": 60,
    "sections": 2,
    "floor_height_in": 36,
    "base_monthly_rate_cents": 118_000,
    "delivery_base_cents": 240_000,
    "install_base_cents": 185_000,
    "replacement_value_cents": 9_500_000,
    "max_occupancy": 24,
}

SPEC_MOB_2048 = {
    "model_code": "MOB-2048",
    "width_ft": 20,
    "length_ft": 48,
    "sections": 1,
    "floor_height_in": 24,
    "base_monthly_rate_cents": 118_050,
    "delivery_base_cents": 165_000,
    "install_base_cents": 120_000,
    "replacement_value_cents": 6_200_000,
    "max_occupancy": 12,
}

CONFIG_2_OFFICE_ADA = {
    "name": "2-Office ADA",
    "private_offices": 2,
    "restrooms": 1,
    "partition_linear_ft": 46,
    "hvac_tons": 4.0,
}

CONFIG_OPEN_PLAN = {
    "name": "Open Plan",
    "private_offices": 2,
    "restrooms": 1,
    "partition_linear_ft": 22,
    "hvac_tons": 2.0,
}

ACME_CUSTOMER = {
    "name": "Acme Construction",
    "billing_email": "ap@acme.test",
    "credit_tier": "GOLD",
    "credit_limit_cents": 5_000_000,
}

BASIN_CUSTOMER = {
    "name": "Basin Drilling",
    "billing_email": "ap@basin.test",
    "credit_tier": "GOLD",
    "credit_limit_cents": 5_000_000,
}


# ─── Factories ───────────────────────────────────────────────────────────────

def create_branch_payload(**overrides) -> dict:
    payload = dict(DALLAS_YARD)
    payload.update(overrides)
    return payload


def create_jurisdiction_payload(**overrides) -> dict:
    payload = dict(TX_RUR)
    payload.update(overrides)
    return payload


def create_building_spec_payload(**overrides) -> dict:
    payload = dict(SPEC_MOB_2048)
    payload.update(overrides)
    return payload


def create_floorplan_configuration_payload(building_spec_id: str, **overrides) -> dict:
    payload = dict(CONFIG_OPEN_PLAN)
    payload["building_spec_id"] = building_spec_id
    payload.update(overrides)
    return payload


def create_unit_payload(building_spec_id: str, current_branch_id: str,
                        **overrides) -> dict:
    payload = {
        "serial_number": "MSU-2001",
        "building_spec_id": building_spec_id,
        "current_branch_id": current_branch_id,
        "condition_grade": "A",
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = dict(BASIN_CUSTOMER)
    payload.update(overrides)
    return payload


def create_lease_payload(customer_id: str, unit_id: str, jurisdiction_id: str,
                         floorplan_configuration_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "unit_id": unit_id,
        "jurisdiction_id": jurisdiction_id,
        "floorplan_configuration_id": floorplan_configuration_id,
        "site_address": "9 County Road 12, Rural TX",
        "start_date": "2026-10-01",
        "term_months": 12,
    }
    payload.update(overrides)
    return payload


def create_accessory_package_payload(lease_id: str, package_type: str = "STEPS",
                                     **overrides) -> dict:
    payload = {"lease_id": lease_id, "package_type": package_type}
    payload.update(overrides)
    return payload


def create_permit_application_payload(lease_id: str, jurisdiction_id: str,
                                      foundation_type: str, **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "jurisdiction_id": jurisdiction_id,
        "foundation_type": foundation_type,
    }
    payload.update(overrides)
    return payload


def create_logistics_job_payload(lease_id: str, origin_branch_id: str,
                                 job_type: str = "DELIVERY_INSTALL",
                                 scheduled_date: str = "2026-10-01",
                                 mileage_miles: float = 40,
                                 crew_hours: float = 4.0,
                                 **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "job_type": job_type,
        "origin_branch_id": origin_branch_id,
        "scheduled_date": scheduled_date,
        "mileage_miles": mileage_miles,
        "crew_hours": crew_hours,
    }
    payload.update(overrides)
    return payload


def create_damage_assessment_payload(lease_id: str, unit_id: str,
                                     logistics_job_id: str,
                                     expected_lease_version: int,
                                     **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "unit_id": unit_id,
        "logistics_job_id": logistics_job_id,
        "expected_lease_version": expected_lease_version,
    }
    payload.update(overrides)
    return payload


def create_damage_line_item_payload(component: str = "HVAC",
                                    severity: str = "MODERATE",
                                    quantity: float = 1,
                                    wear_and_tear: bool = False,
                                    **overrides) -> dict:
    payload = {
        "component": component,
        "severity": severity,
        "quantity": quantity,
        "wear_and_tear": wear_and_tear,
    }
    payload.update(overrides)
    return payload


def create_refurbishment_order_payload(unit_id: str, branch_id: str,
                                       damage_assessment_id: str,
                                       expected_unit_version: int,
                                       scope: str = "STANDARD",
                                       labor_hours: float = 12.5,
                                       parts_cost_cents: int = 143_700,
                                       target_condition_grade: str = "B",
                                       **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "branch_id": branch_id,
        "damage_assessment_id": damage_assessment_id,
        "scope": scope,
        "labor_hours": labor_hours,
        "parts_cost_cents": parts_cost_cents,
        "target_condition_grade": target_condition_grade,
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload

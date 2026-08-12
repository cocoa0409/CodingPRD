"""Payload factories -- one per entity, input fields only."""

# Canonical class specs used across the suite. Every value is an input field.
CHEF_KNIFE_SPEC = {
    "item_class": "CHEF_KNIFE",
    "bevel_angle_degrees": 20,
    "base_service_minutes": 6,
    "list_price_cents": 900,
    "required_certification": "NONE",
    "price_tier": "TIER_1",
    "min_locker_size": "SMALL",
    "loaner_eligible": True,
}
SALON_SHEAR_SPEC = {
    "item_class": "SALON_SHEAR",
    "bevel_angle_degrees": 45,
    "base_service_minutes": 18,
    "list_price_cents": 3200,
    "required_certification": "SHEAR",
    "price_tier": "TIER_3",
    "min_locker_size": "SMALL",
    "loaner_eligible": True,
}
MANDOLINE_SPEC = {
    "item_class": "MANDOLINE_BLADE",
    "bevel_angle_degrees": 15,
    "base_service_minutes": 9,
    "list_price_cents": 1666,
    "required_certification": "SLICER",
    "price_tier": "TIER_2",
    "min_locker_size": "SMALL",
    "loaner_eligible": False,
}
DELI_SLICER_SPEC = {
    "item_class": "DELI_SLICER_BLADE",
    "bevel_angle_degrees": 22,
    "base_service_minutes": 25,
    "list_price_cents": 4500,
    "required_certification": "SLICER",
    "price_tier": "TIER_3",
    "min_locker_size": "LARGE",
    "loaner_eligible": False,
}
GARDEN_PRUNER_SPEC = {
    "item_class": "GARDEN_PRUNER",
    "bevel_angle_degrees": 30,
    "base_service_minutes": 8,
    "list_price_cents": 1100,
    "required_certification": "NONE",
    "price_tier": "TIER_1",
    "min_locker_size": "MEDIUM",
    "loaner_eligible": False,
}


def item_class_spec_payload(**overrides) -> dict:
    payload = dict(CHEF_KNIFE_SPEC)
    payload.update(overrides)
    return payload


def plan_tier_payload(**overrides) -> dict:
    payload = {
        "code": "BLADE_BASIC",
        "monthly_fee_cents": 12000,
        "included_items_per_cycle": 2,
        "overage_discount_pct": 0.15,
        "allowed_cadences": ["WEEKLY", "BIWEEKLY", "MONTHLY"],
    }
    payload.update(overrides)
    return payload


def account_payload(**overrides) -> dict:
    payload = {
        "name": "Blue Fork Kitchen",
        "account_type": "RESTAURANT",
        "zone_code": "ZONE_N",
        "contact_email": "ops@bluefork.test",
    }
    payload.update(overrides)
    return payload


def technician_payload(**overrides) -> dict:
    payload = {"full_name": "Ada Grind", "certifications": []}
    payload.update(overrides)
    return payload


def van_payload(**overrides) -> dict:
    payload = {"code": "VAN-01"}
    payload.update(overrides)
    return payload


def bench_day_payload(**overrides) -> dict:
    payload = {"bench_date": "2026-05-01", "bench_minute_budget": 480}
    payload.update(overrides)
    return payload


def locker_compartment_payload(**overrides) -> dict:
    payload = {"site_code": "SITE-A", "size": "SMALL"}
    payload.update(overrides)
    return payload


def subscription_payload(account_id, plan_tier_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "plan_tier_id": plan_tier_id,
        "cadence": "MONTHLY",
        "anchor_date": "2026-06-01",
    }
    payload.update(overrides)
    return payload


def service_request_payload(account_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "channel": "VAN_ROUTE",
        "requested_date": "2026-05-01",
    }
    payload.update(overrides)
    return payload


def request_item_payload(item_class_spec_id, item_class="CHEF_KNIFE",
                         declared_damage_tier="ROUTINE_HONE", **overrides) -> dict:
    payload = {
        "item_class_spec_id": item_class_spec_id,
        "item_class": item_class,
        "declared_damage_tier": declared_damage_tier,
    }
    payload.update(overrides)
    return payload


def route_run_payload(van_id, technician_id, **overrides) -> dict:
    payload = {
        "van_id": van_id,
        "technician_id": technician_id,
        "run_date": "2026-05-01",
        "zone_code": "ZONE_N",
        "service_minute_budget": 420,
        "stop_cap": 8,
    }
    payload.update(overrides)
    return payload


def route_stop_payload(service_request_id, expected_route_run_version,
                       sequence=1, arrival_window_start="09:00", **overrides) -> dict:
    payload = {
        "service_request_id": service_request_id,
        "sequence": sequence,
        "arrival_window_start": arrival_window_start,
        "expected_route_run_version": expected_route_run_version,
    }
    payload.update(overrides)
    return payload


def loaner_unit_payload(item_class_spec_id, grade="STANDARD", **overrides) -> dict:
    payload = {"item_class_spec_id": item_class_spec_id, "grade": grade, "cycle_ceiling": 5}
    payload.update(overrides)
    return payload


def loaner_issue_payload(service_request_id, item_class_spec_id,
                         requested_grade="STANDARD", **overrides) -> dict:
    payload = {
        "service_request_id": service_request_id,
        "item_class_spec_id": item_class_spec_id,
        "requested_grade": requested_grade,
    }
    payload.update(overrides)
    return payload


def warranty_claim_payload(request_item_id, reason="Edge rolled after two days", **overrides) -> dict:
    payload = {"request_item_id": request_item_id, "reason": reason}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, expected_invoice_version, method="CARD", **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "method": method,
        "expected_invoice_version": expected_invoice_version,
    }
    payload.update(overrides)
    return payload

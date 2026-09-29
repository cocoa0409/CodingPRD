"""Request payload factories. Every default is a PRD-legal value."""

import itertools
from typing import Any, Dict

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def rule_payload(**overrides: Any) -> Dict[str, Any]:
    """An applicable rule. Codes are uppercase snake case and unique."""
    n = _seq()
    payload: Dict[str, Any] = {
        "rule_code": f"RULE_CODE_{n:04d}",
        "hazard_class": "LEAD_PAINT",
        "test_method_code": f"METHOD-{n:04d}",
        "limit_value": 90,
        "limit_unit": "PPM",
        "limit_comparator": "AT_OR_BELOW",
        "periodic_interval_months": 12,
        "base_method_fee_cents": 18700,
        "component_reliance_allowed": True,
        "severity_weight": 5,
    }
    payload.update(overrides)
    return payload


def category_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "category_code": f"CATEGORY_{n:04d}",
        "display_name": f"Juvenile Product Family {n}",
        "durable_infant_product": False,
        "intended_age_max_months": 36,
        "sampling_floor_units": 1,
    }
    payload.update(overrides)
    return payload


def mapping_payload(category_id: str, rule_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "category_id": category_id,
        "rule_id": rule_id,
        "applicability_condition": "ALWAYS",
        "effective_from": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def supplier_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "legal_name": f"Component Supplier {n} Ltd",
        "country_code": "VN",
    }
    payload.update(overrides)
    return payload


def laboratory_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "lab_name": f"Third Party Laboratory {n}",
        "accreditation_body_code": "A2LA",
        "independence_class": "INDEPENDENT",
        "concurrent_slot_capacity": 5,
    }
    payload.update(overrides)
    return payload


def accreditation_payload(rule_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rule_id": rule_id,
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_through": "2027-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def product_payload(category_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "category_id": category_id,
        "model_name": f"Model {n}",
        "manufacture_site_code": "SITE01",
        "projected_annual_units": 1000,
    }
    payload.update(overrides)
    return payload


def component_part_payload(supplier_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "supplier_id": supplier_id,
        "part_name": f"Part {n}",
        "material_class": "PAINTED_COATING",
    }
    payload.update(overrides)
    return payload


def part_certificate_payload(
    laboratory_id: str, rule_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "laboratory_id": laboratory_id,
        "rule_id": rule_id,
        "measured_value": 40,
        "coverage_from": "2026-01-01T00:00:00Z",
        "coverage_through": "2026-03-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def sampling_plan_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"plan_type": "INITIAL"}
    payload.update(overrides)
    return payload


def test_order_payload(
    product_id: str,
    sampling_plan_id: str,
    laboratory_id: str,
    rule_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "sampling_plan_id": sampling_plan_id,
        "laboratory_id": laboratory_id,
        "rule_id": rule_id,
        "sample_count": 1,
        "window_start": "2026-08-10T00:00:00Z",
        "window_end": "2026-08-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def certificate_payload(expected_product_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_product_version": expected_product_version,
        "certifier_legal_name": "Juvenile Goods Manufacturing Co",
        "certifier_contact_email": "records@juvenilegoods.example",
        "manufacture_place": "Ho Chi Minh City, Vietnam",
        "manufacture_date_month": "2026-08",
        "testing_place": "Singapore",
    }
    payload.update(overrides)
    return payload


_batch_counter = itertools.count(1)


def batch_payload(certificate_id: str, **overrides: Any) -> Dict[str, Any]:
    n = next(_batch_counter)
    payload: Dict[str, Any] = {
        "certificate_id": certificate_id,
        "batch_code": f"BATCH{n:02d}-{n:06d}",
        "produced_on": "2026-08-15T00:00:00Z",
        "quantity": 100,
        "label_on_product": True,
        "label_on_packaging": True,
        "label_batch_code_printed": True,
    }
    payload.update(overrides)
    return payload


def tracking_label_payload(
    label_on_product: bool = True,
    label_on_packaging: bool = True,
    label_batch_code_printed: bool = True,
) -> Dict[str, Any]:
    return {
        "label_on_product": label_on_product,
        "label_on_packaging": label_on_packaging,
        "label_batch_code_printed": label_batch_code_printed,
    }


def retest_payload(
    sampling_plan_id: str, laboratory_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sampling_plan_id": sampling_plan_id,
        "laboratory_id": laboratory_id,
        "sample_count": 1,
        "window_start": "2026-08-20T00:00:00Z",
        "window_end": "2026-08-25T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def material_change_payload(product_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "subject_type": "PRODUCT",
        "change_kind": "DESIGN_GEOMETRY_CHANGE",
        "description": "Geometry of the seat shell revised for the 2027 model year.",
    }
    payload.update(overrides)
    return payload

"""Payload factories — one per entity, input fields only.

Optional fields (supersedes_plan_id, buffer_days, discount_pct,
new_chamber_slot_id, the anomaly parent references) are omitted entirely
when not supplied, so tests exercise the PRD's documented defaults.
"""


def create_engagement_payload(name="E-1", client_name="Client Co",
                              fee_cap_cents=50_000_000,
                              labor_rate_cents_per_hour=15_000, **overrides):
    payload = {
        "name": name,
        "client_name": client_name,
        "fee_cap_cents": fee_cap_cents,
        "labor_rate_cents_per_hour": labor_rate_cents_per_hour,
    }
    payload.update(overrides)
    return payload


def create_assembly_payload(tag="W1", assembly_type="CURTAIN_WALL",
                            design_u_factor=1.5,
                            required_airtightness_lps_m2=1.5, **overrides):
    payload = {
        "tag": tag,
        "assembly_type": assembly_type,
        "design_u_factor": design_u_factor,
        "required_airtightness_lps_m2": required_airtightness_lps_m2,
    }
    payload.update(overrides)
    return payload


def create_design_review_payload(assembly_id, barrier_scope=None,
                                 drawing_count=2, **overrides):
    payload = {
        "assembly_id": assembly_id,
        "barrier_scope": list(barrier_scope) if barrier_scope else ["AIR"],
        "drawing_count": drawing_count,
    }
    payload.update(overrides)
    return payload


def create_chamber_slot_payload(chamber_code="CHAMBER-A",
                                start_date="2026-09-01",
                                end_date="2026-09-04",
                                daily_rate_cents=100_000, **overrides):
    payload = {
        "chamber_code": chamber_code,
        "start_date": start_date,
        "end_date": end_date,
        "daily_rate_cents": daily_rate_cents,
    }
    payload.update(overrides)
    return payload


def create_mock_up_payload(assembly_id, chamber_slot_id, specimen_count=1,
                           **overrides):
    payload = {
        "assembly_id": assembly_id,
        "chamber_slot_id": chamber_slot_id,
        "specimen_count": specimen_count,
    }
    payload.update(overrides)
    return payload


def create_field_test_payload(assembly_id, test_method="ASTM_E783",
                              test_date="2026-09-10", test_pressure_pa=150,
                              **overrides):
    payload = {
        "assembly_id": assembly_id,
        "test_method": test_method,
        "test_date": test_date,
        "test_pressure_pa": test_pressure_pa,
    }
    payload.update(overrides)
    return payload


def create_survey_payload(assembly_id, survey_type="MOISTURE",
                          survey_date="2026-09-01", ambient_delta_t_c=1.0,
                          **overrides):
    payload = {
        "assembly_id": assembly_id,
        "survey_type": survey_type,
        "survey_date": survey_date,
        "ambient_delta_t_c": ambient_delta_t_c,
    }
    payload.update(overrides)
    return payload


def create_anomaly_payload(anomaly_type="MOISTURE_TRAP", severity="MEDIUM",
                           description="finding", field_test_id=None,
                           survey_id=None, **overrides):
    payload = {
        "anomaly_type": anomaly_type,
        "severity": severity,
        "description": description,
    }
    if field_test_id is not None:
        payload["field_test_id"] = field_test_id
    if survey_id is not None:
        payload["survey_id"] = survey_id
    payload.update(overrides)
    return payload


def create_remediation_plan_payload(anomaly_ids, spec_sections,
                                    expected_engagement_version,
                                    supersedes_plan_id=None, **overrides):
    payload = {
        "anomaly_ids": list(anomaly_ids),
        "spec_sections": list(spec_sections),
        "expected_engagement_version": expected_engagement_version,
    }
    if supersedes_plan_id is not None:
        payload["supersedes_plan_id"] = supersedes_plan_id
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(anomaly_id, manufacturer_name="ACME",
                                  claimed_amount_cents=100_000, **overrides):
    payload = {
        "anomaly_id": anomaly_id,
        "manufacturer_name": manufacturer_name,
        "claimed_amount_cents": claimed_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_litigation_hold_payload(matter_reference="CASE-2026-001",
                                   **overrides):
    payload = {"matter_reference": matter_reference}
    payload.update(overrides)
    return payload


def create_maintenance_visit_payload(visit_label="AUTUMN-2026",
                                     window_start_date="2026-10-01",
                                     window_end_date="2026-10-05",
                                     buffer_days=None, **overrides):
    payload = {
        "visit_label": visit_label,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
    }
    if buffer_days is not None:
        payload["buffer_days"] = buffer_days
    payload.update(overrides)
    return payload


def create_invoice_payload(labor_hours=1, expense_cents=0, discount_pct=None,
                           **overrides):
    payload = {
        "labor_hours": labor_hours,
        "expense_cents": expense_cents,
    }
    if discount_pct is not None:
        payload["discount_pct"] = discount_pct
    payload.update(overrides)
    return payload

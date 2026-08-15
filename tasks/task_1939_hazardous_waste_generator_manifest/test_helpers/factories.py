"""Payload factories — one per entity/endpoint, input fields only."""


def create_site_payload(name="Site A", epa_id_number="EPA-SITE-A", **overrides):
    defaults = {"name": name, "epa_id_number": epa_id_number}
    defaults.update(overrides)
    return defaults


def create_stream_payload(site_id, name="spent solvent", waste_codes=("D001",),
                          physical_state="LIQUID", **overrides):
    defaults = {
        "site_id": site_id,
        "name": name,
        "waste_codes": list(waste_codes),
        "physical_state": physical_state,
    }
    defaults.update(overrides)
    return defaults


def characterize_payload(expected_waste_stream_version, is_hazardous=True,
                         waste_codes=("D001",), ldr_treatment_standard="TLV-01",
                         flash_point_c=21.5, ph=None, **overrides):
    payload = {
        "is_hazardous": is_hazardous,
        "waste_codes": list(waste_codes),
        "ldr_treatment_standard": ldr_treatment_standard,
        "expected_waste_stream_version": expected_waste_stream_version,
    }
    if is_hazardous:
        payload["flash_point_c"] = flash_point_c
    if ph is not None:
        payload["ph"] = ph
    payload.update(overrides)
    return payload


def create_area_payload(site_id, name="Central A", area_type="CENTRAL_90DAY", **overrides):
    defaults = {"site_id": site_id, "name": name, "area_type": area_type}
    defaults.update(overrides)
    return defaults


def create_container_payload(waste_stream_id, accumulation_area_id,
                             quantity_gallons=10, quantity_kg=100.0, **overrides):
    defaults = {
        "waste_stream_id": waste_stream_id,
        "accumulation_area_id": accumulation_area_id,
        "quantity_gallons": quantity_gallons,
        "quantity_kg": quantity_kg,
    }
    defaults.update(overrides)
    return defaults


def move_container_payload(target_area_id, **overrides):
    defaults = {"target_area_id": target_area_id}
    defaults.update(overrides)
    return defaults


def label_container_payload(label_text, label_accumulation_start_marked, **overrides):
    defaults = {
        "label_text": label_text,
        "label_accumulation_start_marked": label_accumulation_start_marked,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(result="PASS", deficiency_note=None, **overrides):
    payload = {"result": result}
    if deficiency_note is not None:
        payload["deficiency_note"] = deficiency_note
    payload.update(overrides)
    return payload


def create_partner_payload(partner_type, name, epa_id_number,
                           permitted_waste_codes=("D001",), **overrides):
    defaults = {
        "partner_type": partner_type,
        "name": name,
        "epa_id_number": epa_id_number,
        "permitted_waste_codes": list(permitted_waste_codes),
    }
    defaults.update(overrides)
    return defaults


def update_partner_payload(expected_waste_partner_version, name=None,
                           permitted_waste_codes=None, **overrides):
    payload = {"expected_waste_partner_version": expected_waste_partner_version}
    if name is not None:
        payload["name"] = name
    if permitted_waste_codes is not None:
        payload["permitted_waste_codes"] = list(permitted_waste_codes)
    payload.update(overrides)
    return payload


def partner_status_payload(to_status, **overrides):
    defaults = {"to_status": to_status}
    defaults.update(overrides)
    return defaults


def create_audit_payload(coverage_from, coverage_to, outcome="PASS", **overrides):
    defaults = {
        "coverage_from": coverage_from,
        "coverage_to": coverage_to,
        "outcome": outcome,
    }
    defaults.update(overrides)
    return defaults


def manifest_line_item(waste_stream_id, container_id, quantity_kg):
    return {
        "waste_stream_id": waste_stream_id,
        "container_id": container_id,
        "quantity_kg": quantity_kg,
    }


def create_manifest_payload(site_id, transporter_id, tsdf_id, manifest_tracking_number,
                            line_items, **overrides):
    defaults = {
        "site_id": site_id,
        "transporter_id": transporter_id,
        "tsdf_id": tsdf_id,
        "manifest_tracking_number": manifest_tracking_number,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults


def create_ldr_notification_payload(treatment_standard_codes=("TLV-01",),
                                    certification_statement="certified", **overrides):
    defaults = {
        "treatment_standard_codes": list(treatment_standard_codes),
        "certification_statement": certification_statement,
    }
    defaults.update(overrides)
    return defaults


def exception_report_payload(exception_note="45-day exception report", **overrides):
    defaults = {"exception_note": exception_note}
    defaults.update(overrides)
    return defaults


def create_biennial_report_payload(site_id, report_year=2027, **overrides):
    defaults = {"site_id": site_id, "report_year": report_year}
    defaults.update(overrides)
    return defaults


def review_report_payload(outcome="ACCEPT", **overrides):
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601):
    return {"to_iso8601": to_iso8601}

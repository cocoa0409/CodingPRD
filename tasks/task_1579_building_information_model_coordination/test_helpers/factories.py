"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "PROJECT_NAME": "Test Project",
    "COMPANY_NAME": "StructCo",
    "DISCIPLINE": "STRUCTURAL",
    "HOURLY_RATE_CENTS": 12000,
    "COORDINATION_BUDGET_HOURS": 100.0,
    "SOFTWARE_PLATFORM": "REVIT",
    "FILE_FORMAT": "RVT",
    "DECLARED_LOD": 300,
    "MIN_LOD": 300,
    "CLEARANCE_REQUIREMENT_MM": 25.0,
    "FED_LABEL": "F1",
    "TARGET_FORMAT": "IFC",
    "RUN_TOLERANCE_MM": 5.0,
    "ROOM_ID": "RM-1",
    "MEETING_STARTS": "2026-08-01T00:00:00Z",
    "MEETING_ENDS": "2026-08-01T01:00:00Z",
    "DUE_AT": "2026-08-11T00:00:00Z",
    "FIELD_NOTES": "field survey notes",
    "HANDOVER_LABEL": "H1",
}

# A fully compliant element-counter block (all classes 10/10).
COMPLIANT_ELEMENTS = {
    "life_safety_elements": 10,
    "life_safety_compliant": 10,
    "envelope_elements": 10,
    "envelope_compliant": 10,
    "finish_elements": 10,
    "finish_compliant": 10,
}


def create_project_payload(name=DEFAULTS["PROJECT_NAME"], **overrides):
    payload = {"name": name}
    payload.update(overrides)
    return payload


def create_lod_requirement_payload(discipline=DEFAULTS["DISCIPLINE"],
                                   phase="SCHEMATIC_DESIGN",
                                   min_lod=DEFAULTS["MIN_LOD"],
                                   clearance_requirement_mm=DEFAULTS["CLEARANCE_REQUIREMENT_MM"],
                                   **overrides):
    payload = {
        "discipline": discipline,
        "phase": phase,
        "min_lod": min_lod,
        "clearance_requirement_mm": clearance_requirement_mm,
    }
    payload.update(overrides)
    return payload


def create_trade_partner_payload(company_name=DEFAULTS["COMPANY_NAME"],
                                 discipline=DEFAULTS["DISCIPLINE"],
                                 hourly_rate_cents=DEFAULTS["HOURLY_RATE_CENTS"],
                                 coordination_budget_hours=DEFAULTS["COORDINATION_BUDGET_HOURS"],
                                 software_platform=DEFAULTS["SOFTWARE_PLATFORM"],
                                 **overrides):
    payload = {
        "company_name": company_name,
        "discipline": discipline,
        "hourly_rate_cents": hourly_rate_cents,
        "coordination_budget_hours": coordination_budget_hours,
        "software_platform": software_platform,
    }
    payload.update(overrides)
    return payload


def create_trade_model_payload(trade_partner_id,
                               file_format=DEFAULTS["FILE_FORMAT"],
                               declared_lod=DEFAULTS["DECLARED_LOD"],
                               **element_counters_and_overrides):
    payload = {
        "trade_partner_id": trade_partner_id,
        "file_format": file_format,
        "declared_lod": declared_lod,
    }
    payload.update(COMPLIANT_ELEMENTS)
    payload.update(element_counters_and_overrides)
    return payload


def create_federated_model_payload(member_trade_model_ids,
                                   expected_project_version,
                                   label=DEFAULTS["FED_LABEL"],
                                   target_format=DEFAULTS["TARGET_FORMAT"],
                                   **overrides):
    payload = {
        "label": label,
        "target_format": target_format,
        "member_trade_model_ids": list(member_trade_model_ids),
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def create_freeze_window_payload(starts_at, ends_at,
                                 purpose="COORDINATION_FREEZE", **overrides):
    payload = {"starts_at": starts_at, "ends_at": ends_at, "purpose": purpose}
    payload.update(overrides)
    return payload


def create_clash_run_payload(tolerance_mm=DEFAULTS["RUN_TOLERANCE_MM"], **overrides):
    payload = {"tolerance_mm": tolerance_mm}
    payload.update(overrides)
    return payload


def import_clash_payload(element_pair, overlap_mm, spans_disciplines=False, **overrides):
    payload = {
        "element_pair": element_pair,
        "overlap_mm": overlap_mm,
        "spans_disciplines": spans_disciplines,
    }
    payload.update(overrides)
    return payload


def assign_clash_payload(trade_partner_id, **overrides):
    payload = {"trade_partner_id": trade_partner_id}
    payload.update(overrides)
    return payload


def resolve_clash_payload(actual_labor_hours, **overrides):
    payload = {"actual_labor_hours": actual_labor_hours}
    payload.update(overrides)
    return payload


def verify_clash_payload(re_inspection_overlap_mm, **overrides):
    payload = {"re_inspection_overlap_mm": re_inspection_overlap_mm}
    payload.update(overrides)
    return payload


def create_meeting_payload(room_id=DEFAULTS["ROOM_ID"],
                           starts_at=DEFAULTS["MEETING_STARTS"],
                           ends_at=DEFAULTS["MEETING_ENDS"], **overrides):
    payload = {"room_id": room_id, "starts_at": starts_at, "ends_at": ends_at}
    payload.update(overrides)
    return payload


def create_commitment_payload(clash_issue_id, committed_by_partner_id,
                              due_at=DEFAULTS["DUE_AT"], **overrides):
    payload = {
        "clash_issue_id": clash_issue_id,
        "committed_by_partner_id": committed_by_partner_id,
        "due_at": due_at,
    }
    payload.update(overrides)
    return payload


def create_fabrication_package_payload(federated_model_id, scope_disciplines,
                                       **overrides):
    payload = {
        "federated_model_id": federated_model_id,
        "scope_disciplines": list(scope_disciplines),
    }
    payload.update(overrides)
    return payload


def create_as_built_payload(trade_model_id,
                            field_verification_notes=DEFAULTS["FIELD_NOTES"],
                            **overrides):
    payload = {
        "trade_model_id": trade_model_id,
        "field_verification_notes": field_verification_notes,
    }
    payload.update(overrides)
    return payload


def verify_as_built_payload(verification_deviation_mm, **overrides):
    payload = {"verification_deviation_mm": verification_deviation_mm}
    payload.update(overrides)
    return payload


def create_quantity_takeoff_payload(federated_model_id, extraction_mode, elements,
                                    expected_project_version,
                                    discipline_filter=None, **overrides):
    payload = {
        "federated_model_id": federated_model_id,
        "extraction_mode": extraction_mode,
        "elements": elements,
        "expected_project_version": expected_project_version,
    }
    if discipline_filter is not None:
        payload["discipline_filter"] = discipline_filter
    payload.update(overrides)
    return payload


def make_takeoff_element(element_ref, gross_qty, deduction_qty=0.0):
    return {
        "element_ref": element_ref,
        "gross_qty": gross_qty,
        "deduction_qty": deduction_qty,
    }


def create_handover_package_payload(includes_takeoff_id,
                                    label=DEFAULTS["HANDOVER_LABEL"], **overrides):
    payload = {"label": label, "includes_takeoff_id": includes_takeoff_id}
    payload.update(overrides)
    return payload


def respond_handover_payload(decision, **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601, **overrides):
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload

"""Payload factories — one per write operation, client-supplied fields only."""
from .constants import MODEL_PRESETS, PRESET_TARGET_CYCLE_COUNT, TEST_DEFAULTS


# ─── Catalogue ─────────────────────────────────────────────────────────────

def equipment_model_payload(preset: str = "T900", **overrides) -> dict:
    payload = dict(MODEL_PRESETS[preset])
    payload.update(overrides)
    return payload


def model_revision_payload(equipment_model_id, expected_equipment_model_version,
                           revision_code="T900-R1", target_cycle_count=None,
                           **overrides) -> dict:
    payload = {
        "equipment_model_id": equipment_model_id,
        "revision_code": revision_code,
        "target_cycle_count": target_cycle_count or 500_000,
        "expected_equipment_model_version": expected_equipment_model_version,
    }
    payload.update(overrides)
    return payload


def revision_payload_for_preset(preset, equipment_model_id,
                                expected_equipment_model_version, **overrides) -> dict:
    return model_revision_payload(
        equipment_model_id,
        expected_equipment_model_version,
        revision_code=overrides.pop("revision_code", f"{preset}-R1"),
        target_cycle_count=overrides.pop(
            "target_cycle_count", PRESET_TARGET_CYCLE_COUNT[preset]
        ),
        **overrides,
    )


def rework_payload(rework_note="frame weld fixture revised", **overrides) -> dict:
    payload = {"rework_note": rework_note}
    payload.update(overrides)
    return payload


def sunset_payload(sunset_reason="platform refresh announced to the dealer network",
                   **overrides) -> dict:
    payload = {"sunset_reason": sunset_reason}
    payload.update(overrides)
    return payload


# ─── Durability testing ────────────────────────────────────────────────────

def rig_payload(name=None, parallel_station_count=None,
                     supported_duty_classes=None, **overrides) -> dict:
    payload = {
        "name": name or TEST_DEFAULTS["RIG_NAME"],
        "parallel_station_count": (
            parallel_station_count
            if parallel_station_count is not None
            else TEST_DEFAULTS["RIG_STATIONS"]
        ),
        "supported_duty_classes": supported_duty_classes
        or ["LIGHT_COMMERCIAL", "FULL_COMMERCIAL", "INSTITUTIONAL"],
    }
    payload.update(overrides)
    return payload


def run_payload(model_revision_id, test_rig_id, window_start, window_end,
                     target_cycles=300_000, **overrides) -> dict:
    payload = {
        "model_revision_id": model_revision_id,
        "test_rig_id": test_rig_id,
        "window_start": window_start,
        "window_end": window_end,
        "target_cycles": target_cycles,
    }
    payload.update(overrides)
    return payload


def run_pass_payload(achieved_cycles, **overrides) -> dict:
    payload = {"outcome": "PASSED", "achieved_cycles": achieved_cycles}
    payload.update(overrides)
    return payload


def run_fail_payload(failure_cycle_count, **overrides) -> dict:
    payload = {"outcome": "FAILED", "failure_cycle_count": failure_cycle_count}
    payload.update(overrides)
    return payload


def abort_run_payload(abort_reason="specimen fixture reallocated", **overrides) -> dict:
    payload = {"abort_reason": abort_reason}
    payload.update(overrides)
    return payload


# ─── Firmware ──────────────────────────────────────────────────────────────

def firmware_release_payload(version_string="FW-2.1.0", console_platform="CONSOLE_T2",
                             **overrides) -> dict:
    payload = {"version_string": version_string, "console_platform": console_platform}
    payload.update(overrides)
    return payload


def firmware_certification_payload(firmware_release_id, model_revision_id,
                                   test_report_ref="CONN-RPT-0001", **overrides) -> dict:
    payload = {
        "firmware_release_id": firmware_release_id,
        "model_revision_id": model_revision_id,
        "test_report_ref": test_report_ref,
    }
    payload.update(overrides)
    return payload


def reject_certification_payload(rejection_note="connectivity report incomplete",
                                 **overrides) -> dict:
    payload = {"rejection_note": rejection_note}
    payload.update(overrides)
    return payload


def withdraw_release_payload(withdraw_reason="console security defect found in the field",
                            **overrides) -> dict:
    payload = {"withdraw_reason": withdraw_reason}
    payload.update(overrides)
    return payload


# ─── Commercial ────────────────────────────────────────────────────────────

def facility_payload(account_name=None, freight_zone=None, credit_limit_cents=None,
                     **overrides) -> dict:
    payload = {
        "account_name": account_name or TEST_DEFAULTS["FACILITY_ACCOUNT_NAME"],
        "freight_zone": freight_zone or TEST_DEFAULTS["FACILITY_FREIGHT_ZONE"],
        "credit_limit_cents": (
            credit_limit_cents
            if credit_limit_cents is not None
            else TEST_DEFAULTS["FACILITY_CREDIT_LIMIT_CENTS"]
        ),
    }
    payload.update(overrides)
    return payload


def suspend_facility_payload(suspend_reason="account placed on credit hold",
                            **overrides) -> dict:
    payload = {"suspend_reason": suspend_reason}
    payload.update(overrides)
    return payload


def order_payload(facility_id, requested_install_window_start=None,
                  requested_install_window_end=None, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "requested_install_window_start": requested_install_window_start
        or TEST_DEFAULTS["ORDER_WINDOW_START"],
        "requested_install_window_end": requested_install_window_end
        or TEST_DEFAULTS["ORDER_WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def order_line_payload(model_revision_id, quantity=1, finish_codes=None,
                       layout_zone_label=None, **overrides) -> dict:
    payload = {
        "model_revision_id": model_revision_id,
        "quantity": quantity,
        "finish_codes": ["GRAPHITE"] if finish_codes is None else finish_codes,
        "layout_zone_label": layout_zone_label or TEST_DEFAULTS["LAYOUT_ZONE_LABEL"],
    }
    payload.update(overrides)
    return payload


def quote_payload(expected_order_version, **overrides) -> dict:
    payload = {"expected_order_version": expected_order_version}
    payload.update(overrides)
    return payload


def apply_tradein_credit_payload(amount_cents, expected_facility_version,
                                 **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload


def settle_payload(payment_reference="WIRE-77120", **overrides) -> dict:
    payload = {"payment_reference": payment_reference}
    payload.update(overrides)
    return payload


# ─── Service network ───────────────────────────────────────────────────────

def service_partner_payload(name=None, region=None, certified_categories=None,
                            certified_technician_count=None,
                            certified_hours_capacity=None,
                            training_current_until=None, **overrides) -> dict:
    payload = {
        "name": name or TEST_DEFAULTS["PARTNER_NAME"],
        "region": region or TEST_DEFAULTS["PARTNER_REGION"],
        "certified_categories": certified_categories or ["CARDIO"],
        "certified_technician_count": (
            certified_technician_count
            if certified_technician_count is not None
            else TEST_DEFAULTS["PARTNER_TECHNICIAN_COUNT"]
        ),
        "certified_hours_capacity": (
            certified_hours_capacity
            if certified_hours_capacity is not None
            else TEST_DEFAULTS["PARTNER_HOURS_CAPACITY"]
        ),
        "training_current_until": training_current_until
        or TEST_DEFAULTS["PARTNER_TRAINING_UNTIL"],
    }
    payload.update(overrides)
    return payload


def parts_receipt_payload(units, **overrides) -> dict:
    payload = {"units": units}
    payload.update(overrides)
    return payload


def install_job_payload(order_id, service_partner_id, window_start=None,
                        window_end=None, estimated_labor_hours=None, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "service_partner_id": service_partner_id,
        "window_start": window_start or TEST_DEFAULTS["INSTALL_WINDOW_START"],
        "window_end": window_end or TEST_DEFAULTS["INSTALL_WINDOW_END"],
        "estimated_labor_hours": (
            estimated_labor_hours
            if estimated_labor_hours is not None
            else TEST_DEFAULTS["INSTALL_ESTIMATED_HOURS"]
        ),
    }
    payload.update(overrides)
    return payload


def complete_install_payload(actual_labor_hours=3.0, punch_list_open_count=0,
                             **overrides) -> dict:
    payload = {
        "actual_labor_hours": actual_labor_hours,
        "punch_list_open_count": punch_list_open_count,
    }
    payload.update(overrides)
    return payload


def resolve_punch_list_payload(resolution_note="remaining console brackets fitted",
                               **overrides) -> dict:
    payload = {"resolution_note": resolution_note}
    payload.update(overrides)
    return payload


def abort_install_payload(abort_reason="crew reassigned to a storm callout",
                          **overrides) -> dict:
    payload = {"abort_reason": abort_reason}
    payload.update(overrides)
    return payload


def pm_program_payload(facility_id, service_partner_id, tier="PRO",
                       visit_interval_days=90, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "service_partner_id": service_partner_id,
        "tier": tier,
        "visit_interval_days": visit_interval_days,
    }
    payload.update(overrides)
    return payload


def terminate_program_payload(terminate_reason="facility consolidated its service book",
                              **overrides) -> dict:
    payload = {"terminate_reason": terminate_reason}
    payload.update(overrides)
    return payload


def maintenance_visit_payload(pm_program_id, serialized_asset_id,
                              scheduled_date="2026-09-20T09:00:00Z",
                              reserved_units=0, **overrides) -> dict:
    payload = {
        "pm_program_id": pm_program_id,
        "serialized_asset_id": serialized_asset_id,
        "scheduled_date": scheduled_date,
        "reserved_units": reserved_units,
    }
    payload.update(overrides)
    return payload


def complete_visit_payload(labor_hours=2.0, **overrides) -> dict:
    payload = {"labor_hours": labor_hours}
    payload.update(overrides)
    return payload


def cancel_visit_payload(cancel_reason="facility closed for refurbishment",
                         **overrides) -> dict:
    payload = {"cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload


# ─── Assets ────────────────────────────────────────────────────────────────

def load_firmware_payload(firmware_release_id, **overrides) -> dict:
    payload = {"firmware_release_id": firmware_release_id}
    payload.update(overrides)
    return payload


def usage_report_payload(annual_usage_hours=1800.0, **overrides) -> dict:
    payload = {"annual_usage_hours": annual_usage_hours}
    payload.update(overrides)
    return payload


def trade_in_payload(declared_condition_grade="A", **overrides) -> dict:
    payload = {"declared_condition_grade": declared_condition_grade}
    payload.update(overrides)
    return payload


def reverse_trade_in_payload(reverse_reason="customer withdrew the trade-in offer",
                             **overrides) -> dict:
    payload = {"reverse_reason": reverse_reason}
    payload.update(overrides)
    return payload


def refurb_certify_payload(refurb_grade="B", **overrides) -> dict:
    payload = {"refurb_grade": refurb_grade}
    payload.update(overrides)
    return payload


def resell_payload(buyer_facility_id, **overrides) -> dict:
    payload = {"buyer_facility_id": buyer_facility_id}
    payload.update(overrides)
    return payload


def scrap_payload(scrap_reason="frame corrosion beyond economic repair",
                  **overrides) -> dict:
    payload = {"scrap_reason": scrap_reason}
    payload.update(overrides)
    return payload


# ─── Clock ─────────────────────────────────────────────────────────────────

def clock_payload(to_iso8601, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload

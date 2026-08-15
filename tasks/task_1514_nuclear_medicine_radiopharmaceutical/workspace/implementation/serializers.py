"""Entity -> public-dict serializers.

All datetime fields are stored internally as naive-UTC datetimes under a
`<field>_dt` key; the public payload exposes the ISO string under `<field>`.
"""

import db
from calc import compute_possession, container_current_activity, get_now, iso_z, public_num


def _emit(entity, key, iso8601_z=True):
    dt = entity.get(key + "_dt")
    if dt is None:
        return None
    if iso8601_z:
        return iso_z(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def isotope_product_out(e):
    return {
        "id": e["id"],
        "name": e["name"],
        "half_life_minutes": public_num(e["half_life_minutes"]),
        "decay_constant_per_minute": public_num(e["decay_constant_per_minute"]),
        "spill_major_threshold_mbq": public_num(e["spill_major_threshold_mbq"]),
        "release_activity_limit_mbq": public_num(e["release_activity_limit_mbq"]),
        "min_usable_activity_mbq": public_num(e["min_usable_activity_mbq"]),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def license_out(e):
    now = get_now()
    return {
        "id": e["id"],
        "license_number": e["license_number"],
        "max_possession_mbq": public_num(e["max_possession_mbq"]),
        "isotope_conditions": e["isotope_conditions"],
        "expires_at": _emit(e, "expires_at"),
        "status": e["status"],
        "current_possession_mbq": public_num(compute_possession(e, now)),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def authorized_user_out(e):
    return {
        "id": e["id"],
        "full_name": e["full_name"],
        "license_id": e["license_id"],
        "scope": e["scope"],
        "expires_at": _emit(e, "expires_at"),
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def patient_out(e):
    return {
        "id": e["id"],
        "full_name": e["full_name"],
        "weight_kg": public_num(e["weight_kg"]),
        "date_of_birth": e.get("date_of_birth"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def imaging_room_out(e):
    return {
        "id": e["id"],
        "name": e["name"],
        "cleanup_buffer_minutes": e["cleanup_buffer_minutes"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def isotope_delivery_out(e):
    return {
        "id": e["id"],
        "isotope_product_id": e["isotope_product_id"],
        "scheduled_arrival_at": _emit(e, "scheduled_arrival_at"),
        "reference_activity_mbq": public_num(e["reference_activity_mbq"]),
        "reference_time_at": _emit(e, "reference_time_at"),
        "received_at": _emit(e, "received_at"),
        "measured_activity_mbq": public_num(e.get("measured_activity_mbq")),
        "failure_reason": e.get("failure_reason"),
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def dose_order_out(e):
    return {
        "id": e["id"],
        "patient_id": e["patient_id"],
        "isotope_product_id": e["isotope_product_id"],
        "authorized_user_id": e["authorized_user_id"],
        "use_type": e["use_type"],
        "prescribed_activity_mbq": public_num(e["prescribed_activity_mbq"]),
        "administration_scheduled_at": _emit(e, "administration_scheduled_at"),
        "expires_at": _emit(e, "expires_at"),
        "hold_reason": e.get("hold_reason"),
        "hold_previous_status": e.get("hold_previous_status"),
        "replaces_order_id": e.get("replaces_order_id"),
        "superseded_by_order_id": e.get("superseded_by_order_id"),
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def dose_vial_out(e):
    return {
        "id": e["id"],
        "order_id": e["order_id"],
        "delivery_id": e["delivery_id"],
        "waste_container_id": e.get("waste_container_id"),
        "prepared_at": _emit(e, "prepared_at"),
        "required_activity_mbq": public_num(e.get("required_activity_mbq")),
        "measured_activity_mbq": public_num(e.get("measured_activity_mbq")),
        "calibrated_at": _emit(e, "calibrated_at"),
        "calibrated_by_user_id": e.get("calibrated_by_user_id"),
        "status": e["status"],
        "disposed_at": _emit(e, "disposed_at"),
        "residual_activity_mbq": public_num(e.get("residual_activity_mbq")),
        "decay_loss_mbq": public_num(e.get("decay_loss_mbq")),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def dose_administration_out(e):
    return {
        "id": e["id"],
        "order_id": e["order_id"],
        "vial_id": e["vial_id"],
        "administered_at": _emit(e, "administered_at"),
        "administered_by_user_id": e["administered_by_user_id"],
        "assayed_activity_exact_mbq": public_num(e["assayed_activity_exact_mbq"]),
        "assayed_activity_tabular_mbq": public_num(e["assayed_activity_tabular_mbq"]),
        "within_admin_window": e["within_admin_window"],
        "created_at": e["created_at"],
    }


def procedure_appointment_out(e):
    return {
        "id": e["id"],
        "order_id": e["order_id"],
        "room_id": e["room_id"],
        "start_at": _emit(e, "start_at"),
        "end_at": _emit(e, "end_at"),
        "status": e["status"],
        "void_reason": e.get("void_reason"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def waste_container_out(e):
    now = get_now()
    return {
        "id": e["id"],
        "isotope_product_id": e["isotope_product_id"],
        "room_id": e["room_id"],
        "status": e["status"],
        "sealed_at": _emit(e, "sealed_at"),
        "sealed_by_user_id": e.get("sealed_by_user_id"),
        "certified_at": _emit(e, "certified_at"),
        "certified_by_user_id": e.get("certified_by_user_id"),
        "intake_activity_mbq": public_num(e["intake_activity_mbq"]),
        "current_activity_mbq": public_num(container_current_activity(e, now)),
        "clearable_after_at": _emit(e, "clearable_after_at"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def radiation_survey_out(e):
    return {
        "id": e["id"],
        "room_id": e["room_id"],
        "surveyed_at": _emit(e, "surveyed_at"),
        "ambient_dose_rate_usv_h": public_num(e["ambient_dose_rate_usv_h"]),
        "result": e["result"],
        "performed_by_user_id": e["performed_by_user_id"],
        "created_at": e["created_at"],
    }


def spill_incident_out(e):
    return {
        "id": e["id"],
        "room_id": e["room_id"],
        "isotope_product_id": e["isotope_product_id"],
        "estimated_activity_mbq": public_num(e["estimated_activity_mbq"]),
        "occurred_at": _emit(e, "occurred_at"),
        "classification": e["classification"],
        "reported_by_user_id": e["reported_by_user_id"],
        "status": e["status"],
        "contained_at": _emit(e, "contained_at"),
        "decontaminated_at": _emit(e, "decontaminated_at"),
        "cleared_at": _emit(e, "cleared_at"),
        "cleared_by_user_id": e.get("cleared_by_user_id"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def patient_release_instruction_out(e):
    return {
        "id": e["id"],
        "administration_id": e["administration_id"],
        "evaluation_variant": e["evaluation_variant"],
        "measured_dose_rate_at_1m_usv_h": public_num(e.get("measured_dose_rate_at_1m_usv_h")),
        "releasable": e["releasable"],
        "status": e["status"],
        "issued_by_user_id": e["issued_by_user_id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }

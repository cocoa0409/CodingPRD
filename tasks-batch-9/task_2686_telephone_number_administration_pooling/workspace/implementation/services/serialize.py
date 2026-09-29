"""Entity serializers.  Derived counters are computed at read time (PRD 2.9)."""

from db import fmt_dt, fmt_instant
from services import constants as C
from services import core


def _num(value):
    return value


def carrier(record):
    return {
        "id": record["id"],
        "ocn": record["ocn"],
        "legal_name": record["legal_name"],
        "carrier_type": record["carrier_type"],
        "home_state_code": record["home_state_code"],
        "months_in_operation": record["months_in_operation"],
        "license_status": record["license_status"],
        "license_expires_on": fmt_instant(record["license_expires_on"]),
        "facilities_readiness_status": record["facilities_readiness_status"],
        "switch_clli": record["switch_clli"],
        "interconnection_ready": record["interconnection_ready"],
        "eligibility_status": core.eligibility_status(record),
        "blocks_held_count": core.carrier_blocks_held(record["id"]),
        "reclamation_strike_count": record["reclamation_strike_count"],
        "safety_valve_grant_count": record["safety_valve_grant_count"],
        "probation_until": fmt_instant(record["probation_until"]),
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def npa(record):
    return {
        "id": record["id"],
        "npa_code": record["npa_code"],
        "state_code": record["state_code"],
        "npa_type": record["npa_type"],
        "relief_parent_npa_id": record["relief_parent_npa_id"],
        "status": record["status"],
        "available_block_count": core.npa_available_count(record["id"]),
        "total_block_count": core.npa_total_count(record["id"]),
        "exhaust_projection_months": float(C.EXHAUST_SENTINEL_MONTHS),
        "jeopardy_declared_at": fmt_instant(record["jeopardy_declared_at"]),
        "permissive_dialing_end_at": fmt_instant(record["permissive_dialing_end_at"]),
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def rate_center(record):
    return {
        "id": record["id"],
        "npa_id": record["npa_id"],
        "name": record["name"],
        "state_code": record["state_code"],
        "lata_code": record["lata_code"],
        "pooling_status": record["pooling_status"],
        "pooling_effective_at": fmt_instant(record["pooling_effective_at"]),
        "available_block_count": core.rc_available_count(record["id"]),
        "assigned_block_count": core.rc_assigned_count(record["id"]),
        "aggregate_utilization_pct": core.aggregate_utilization_pct(record["id"]),
        "jeopardy_flag": record["jeopardy_flag"],
        "accepts_initial_requests": core.accepts_initial_requests(record),
        "pending_request_count": record["pending_request_count"],
        "last_donation_block_count": record["last_donation_block_count"],
        "donation_shortfall_count": record["donation_shortfall_count"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def block(record):
    return {
        "id": record["id"],
        "npa_id": record["npa_id"],
        "rate_center_id": record["rate_center_id"],
        "nxx_code": record["nxx_code"],
        "thousands_digit": record["thousands_digit"],
        "block_label": record["block_label"],
        "allocation_status": record["allocation_status"],
        "routing_status": record["routing_status"],
        "holder_carrier_id": record["holder_carrier_id"],
        "assigned_at": fmt_instant(record["assigned_at"]),
        "activation_due_at": fmt_instant(record["activation_due_at"]),
        "activated_at": fmt_instant(record["activated_at"]),
        "aging_release_at": fmt_instant(record["aging_release_at"]),
        "contaminated_count": record["contaminated_count"],
        "is_pooling_eligible": core.is_pooling_eligible(record),
        "current_lrn": record["current_lrn"],
        "npac_db_version": record["npac_db_version"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def allocation_request(record):
    return {
        "id": record["id"],
        "carrier_id": record["carrier_id"],
        "rate_center_id": record["rate_center_id"],
        "request_type": record["request_type"],
        "requested_block_count": record["requested_block_count"],
        "justification": record["justification"],
        "status": record["status"],
        "info_request_count": record["info_request_count"],
        "utilization_pct_at_submission": record["utilization_pct_at_submission"],
        "months_to_exhaust_at_submission": record["months_to_exhaust_at_submission"],
        "granted_block_count": record["granted_block_count"],
        "assigned_block_ids": list(record["assigned_block_ids"]),
        "reviewer_user_id": record["reviewer_user_id"],
        "approver_user_id": record["approver_user_id"],
        "decided_at": fmt_instant(record["decided_at"]),
        "denial_reason": record["denial_reason"],
        "superseded_by_request_id": record["superseded_by_request_id"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def filing(record):
    return {
        "id": record["id"],
        "carrier_id": record["carrier_id"],
        "rate_center_id": record["rate_center_id"],
        "reporting_period": record["reporting_period"],
        "numbers_assigned": record["numbers_assigned"],
        "numbers_intermediate": record["numbers_intermediate"],
        "numbers_reserved": record["numbers_reserved"],
        "numbers_aging": record["numbers_aging"],
        "numbers_administrative": record["numbers_administrative"],
        "blocks_held_at_period_end": record["blocks_held_at_period_end"],
        "forecast_quarters": list(record["forecast_quarters"]),
        "status": record["status"],
        "claimed_utilization_pct": record["claimed_utilization_pct"],
        "strict_utilization_pct": record["strict_utilization_pct"],
        "audited_utilization_pct": record["audited_utilization_pct"],
        "submitted_at": fmt_instant(record["submitted_at"]),
        "amendment_count": record["amendment_count"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def finding(record):
    return {
        "id": record["id"],
        "utilization_filing_id": record["utilization_filing_id"],
        "auditor_user_id": record["auditor_user_id"],
        "finding_type": record["finding_type"],
        "adjusted_numbers_assigned": record["adjusted_numbers_assigned"],
        "adjusted_numbers_administrative": record["adjusted_numbers_administrative"],
        "adjusted_utilization_pct": record["adjusted_utilization_pct"],
        "penalty_action": record["penalty_action"],
        "status": record["status"],
        "disposed_by_user_id": record["disposed_by_user_id"],
        "disposition_note": record["disposition_note"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def order(record):
    return {
        "id": record["id"],
        "number_block_id": record["number_block_id"],
        "carrier_id": record["carrier_id"],
        "reason": record["reason"],
        "status": record["status"],
        "issued_at": fmt_instant(record["issued_at"]),
        "response_due_at": fmt_instant(record["response_due_at"]),
        "executed_at": fmt_instant(record["executed_at"]),
        "appeal_note": record["appeal_note"],
        "strike_applied": record["strike_applied"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def window_end_at(record):
    if record["status"] == "ORDERED":
        return record["permissive_dialing_end_at"]
    if record["status"] in C.RELIEF_CONSULTING:
        return record["comment_window_close_at"]
    return None


def relief_plan(record):
    return {
        "id": record["id"],
        "npa_id": record["npa_id"],
        "planned_relief_type": record["planned_relief_type"],
        "status": record["status"],
        "comment_window_days": record["comment_window_days"],
        "comment_window_open_at": fmt_instant(record["comment_window_open_at"]),
        "comment_window_close_at": fmt_instant(record["comment_window_close_at"]),
        "recommended_relief_type": record["recommended_relief_type"],
        "support_overlay_weight": record["support_overlay_weight"],
        "support_split_weight": record["support_split_weight"],
        "comment_count": core.comment_count(record["id"]),
        "recommender_user_id": record["recommender_user_id"],
        "ordering_user_id": record["ordering_user_id"],
        "new_npa_code": record["new_npa_code"],
        "effective_at": fmt_instant(record["effective_at"]),
        "permissive_dialing_end_at": fmt_instant(record["permissive_dialing_end_at"]),
        "successor_npa_id": record["successor_npa_id"],
        "window_end_at": fmt_instant(window_end_at(record)),
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def comment(record):
    return {
        "id": record["id"],
        "relief_plan_id": record["relief_plan_id"],
        "commenter_type": record["commenter_type"],
        "position": record["position"],
        "body": record["body"],
        "weight": record["weight"],
        "submitted_at": fmt_instant(record["submitted_at"]),
        "created_at": fmt_dt(record["created_at"]),
    }


def port_request(record):
    return {
        "id": record["id"],
        "telephone_number": record["telephone_number"],
        "number_block_id": record["number_block_id"],
        "from_carrier_id": record["from_carrier_id"],
        "to_carrier_id": record["to_carrier_id"],
        "requested_lrn": record["requested_lrn"],
        "desired_due_at": fmt_instant(record["desired_due_at"]),
        "status": record["status"],
        "concurred_at": fmt_instant(record["concurred_at"]),
        "activated_at": fmt_instant(record["activated_at"]),
        "closed_at": fmt_instant(record["closed_at"]),
        "reject_reason": record["reject_reason"],
        "npac_db_version_at_activation": record["npac_db_version_at_activation"],
        "supersedes_port_request_id": record["supersedes_port_request_id"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def routing_record(record):
    return {
        "id": record["id"],
        "number_block_id": record["number_block_id"],
        "lrn": record["lrn"],
        "ocn": record["ocn"],
        "switch_clli": record["switch_clli"],
        "effective_at": fmt_instant(record["effective_at"]),
        "end_at": fmt_instant(record["end_at"]),
        "record_status": record["record_status"],
        "npac_db_version": record["npac_db_version"],
        "created_at": fmt_dt(record["created_at"]),
    }

"""Entity -> JSON projections.

Every `source: computed` counter is derived here at read time rather than being
cached on the row, so that a counter refresh never fabricates a `version` bump
on a record whose own state did not change.
"""

import calc
from store import fmt_dt


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


def jurisdiction(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "code": row["code"],
        "jurisdiction_type": row["jurisdiction_type"],
        "postal_city": row["postal_city"],
    })
    out.update(calc.jurisdiction_counters(row["id"]))
    return out


def agency(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "agency_type": row["agency_type"],
        "jurisdiction_id": row["jurisdiction_id"],
        "contact_phone": row["contact_phone"],
        "status": row["status"],
        "suspended_reason": row["suspended_reason"],
    })
    return out


def cell(row):
    out = _common(row)
    out.update({
        "cell_code": row["cell_code"],
        "jurisdiction_id": row["jurisdiction_id"],
        "centroid_lat": row["centroid_lat"],
        "centroid_lon": row["centroid_lon"],
        "active_assignment_count": calc.cell_active_assignment_count(row["id"]),
    })
    return out


def road(row):
    out = _common(row)
    out.update({
        "primary_name": row["primary_name"],
        "normalized_name": row["normalized_name"],
        "jurisdiction_id": row["jurisdiction_id"],
        "from_addr_left": row["from_addr_left"],
        "to_addr_left": row["to_addr_left"],
        "parity_left": row["parity_left"],
        "from_addr_right": row["from_addr_right"],
        "to_addr_right": row["to_addr_right"],
        "parity_right": row["parity_right"],
        "status": row["status"],
        "qc_dirty": row["qc_dirty"],
        "open_discrepancy_case_count": calc.open_discrepancy_case_count(row["id"]),
        "assignable_slot_count_left": calc.assignable_slot_count(row, "LEFT"),
        "assignable_slot_count_right": calc.assignable_slot_count(row, "RIGHT"),
        "retired_at": fmt_dt(row["retired_at"]),
        "retire_reason": row["retire_reason"],
    })
    return out


def point(row):
    out = _common(row)
    out.update({
        "house_number": row["house_number"],
        "house_number_suffix": row["house_number_suffix"],
        "road_centerline_id": row["road_centerline_id"],
        "side": row["side"],
        "unit_type": row["unit_type"],
        "unit_id": row["unit_id"],
        "parent_address_point_id": row["parent_address_point_id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "cell_id": row["cell_id"],
        "source": row["source"],
        "postal_city": row["postal_city"],
        "geometry_verified": row["geometry_verified"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "status": row["status"],
        "confidence_score": row["confidence_score"],
        "certified_confidence_score": row["certified_confidence_score"],
        "confidence_basis": row["confidence_basis"],
        "unit_child_count": calc.unit_child_count(row["id"]),
        "superseded_by_address_point_id": row["superseded_by_address_point_id"],
        "retired_at": fmt_dt(row["retired_at"]),
        "retire_reason": row["retire_reason"],
    })
    return out


def request(row):
    out = _common(row)
    out.update({
        "permit_number": row["permit_number"],
        "parcel_id": row["parcel_id"],
        "road_centerline_id": row["road_centerline_id"],
        "side": row["side"],
        "requested_unit_count": row["requested_unit_count"],
        "proposed_house_number": row["proposed_house_number"],
        "review_status": row["review_status"],
        "utility_status": row["utility_status"],
        "fulfillment_status": row["fulfillment_status"],
        "assigned_address_point_id": row["assigned_address_point_id"],
        "assigned_house_number": row["assigned_house_number"],
        "minted_point_count": row["minted_point_count"],
        "review_note": row["review_note"],
        "utility_note": row["utility_note"],
        "void_reason": row["void_reason"],
    })
    return out


def boundary(row):
    out = _common(row)
    out.update({
        "agency_id": row["agency_id"],
        "service_type": row["service_type"],
        "effective_start": fmt_dt(row["effective_start"]),
        "effective_end": fmt_dt(row["effective_end"]),
        "status": row["status"],
        "assigned_cell_count": calc.assigned_cell_count(row["id"]),
        "retired_at": fmt_dt(row["retired_at"]),
        "retire_reason": row["retire_reason"],
    })
    return out


def assignment(row):
    out = _common(row)
    out.update({
        "boundary_id": row["boundary_id"],
        "cell_id": row["cell_id"],
        "service_type": row["service_type"],
        "effective_start": fmt_dt(row["effective_start"]),
        "effective_end": fmt_dt(row["effective_end"]),
        "status": row["status"],
    })
    return out


def report(row):
    out = _common(row)
    out.update({
        "scope": row["scope"],
        "jurisdiction_id": row["jurisdiction_id"],
        "road_centerline_id": row["road_centerline_id"],
        "status": row["status"],
        "generated_by_user_id": row["generated_by_user_id"],
        "certified_by_user_id": row["certified_by_user_id"],
        "certified_at": fmt_dt(row["certified_at"]),
        "rejection_reason": row["rejection_reason"],
        "decertified_reason": row["decertified_reason"],
    })
    out.update(calc.report_scores(row["id"]))
    return out


def defect(row):
    out = _common(row)
    out.update({
        "report_id": row["report_id"],
        "defect_code": row["defect_code"],
        "severity": row["severity"],
        "defect_category": row["defect_category"],
        "entity_type": row["entity_type"],
        "entity_ref_id": row["entity_ref_id"],
        "detail": row["detail"],
        "status": row["status"],
        "waived_by_user_id": row["waived_by_user_id"],
        "waiver_reason": row["waiver_reason"],
        "waived_at": fmt_dt(row["waived_at"]),
    })
    return out


def package(row):
    out = _common(row)
    out.update({
        "channel": row["channel"],
        "jurisdiction_id": row["jurisdiction_id"],
        "qc_report_id": row["qc_report_id"],
        "status": row["status"],
        "package_version": row["package_version"],
        "sealed_at": fmt_dt(row["sealed_at"]),
        "published_at": fmt_dt(row["published_at"]),
        "sealed_by_user_id": row["sealed_by_user_id"],
        "published_by_user_id": row["published_by_user_id"],
        "invalidated_reason": row["invalidated_reason"],
        "rollback_reason": row["rollback_reason"],
    })
    out.update(calc.package_pin_counts(row["id"]))
    return out


def package_record(row):
    out = _common(row)
    out.update({
        "package_id": row["package_id"],
        "record_type": row["record_type"],
        "record_id": row["record_id"],
        "pinned_version": row["pinned_version"],
        "pin_state": row["pin_state"],
        "staled_at": fmt_dt(row["staled_at"]),
    })
    return out


def case(row):
    out = _common(row)
    current = calc.case_current_proposal(row["id"])
    out.update({
        "subject_type": row["subject_type"],
        "subject_ref_id": row["subject_ref_id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "opened_by_agency_id": row["opened_by_agency_id"],
        "counterparty_agency_id": row["counterparty_agency_id"],
        "description": row["description"],
        "status": row["status"],
        "round_count": calc.case_round_count(row["id"]),
        "current_proposal_id": current["id"] if current is not None else None,
        "concurred_by_side": row["concurred_by_side"],
        "resolved_value": row["resolved_value"],
        "escalated_at": fmt_dt(row["escalated_at"]),
        "adopted_at": fmt_dt(row["adopted_at"]),
    })
    return out


def proposal(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "case_id": row["case_id"],
        "round_number": row["round_number"],
        "proposed_by_side": row["proposed_by_side"],
        "proposed_value": row["proposed_value"],
        "rationale": row["rationale"],
        "status": calc.proposal_status(row),
    }

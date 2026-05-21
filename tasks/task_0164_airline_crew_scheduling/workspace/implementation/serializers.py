"""Serializers that copy out internal rows to API-facing dicts."""


def crew_member(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "employee_no": row["employee_no"],
        "rank": row["rank"],
        "base_airport": row["base_airport"],
        "union_seniority_number": row["union_seniority_number"],
        "union_local_id": row["union_local_id"],
        "status": row["status"],
        "cumulative_duty_minutes_7d": row.get("cumulative_duty_minutes_7d", 0),
        "cumulative_block_minutes_30d": row.get("cumulative_block_minutes_30d", 0),
        "last_duty_end_at": row.get("last_duty_end_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def pairing(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "pairing_code": row["pairing_code"],
        "base_airport": row["base_airport"],
        "start_at": row.get("start_at"),
        "end_at": row.get("end_at"),
        "required_rank_composition": row["required_rank_composition"],
        "total_block_minutes": row.get("total_block_minutes", 0),
        "total_duty_minutes": row.get("total_duty_minutes", 0),
        "status": row["status"],
        "bid_window_id": row.get("bid_window_id"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def duty_period(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "pairing_id": row["pairing_id"],
        "sequence_no": row["sequence_no"],
        "report_at": row["report_at"],
        "release_at": row["release_at"],
        "duty_minutes": row["duty_minutes"],
        "block_minutes": row.get("block_minutes", 0),
        "created_at": row["created_at"],
    }


def flight_leg(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "duty_period_id": row["duty_period_id"],
        "leg_sequence_no": row["leg_sequence_no"],
        "flight_number": row["flight_number"],
        "dep_airport": row["dep_airport"],
        "arr_airport": row["arr_airport"],
        "dep_at": row["dep_at"],
        "arr_at": row["arr_at"],
        "block_minutes": row["block_minutes"],
        "leg_type": row["leg_type"],
        "created_at": row["created_at"],
    }


def bid(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "crew_member_id": row["crew_member_id"],
        "pairing_id": row["pairing_id"],
        "preference_rank": row["preference_rank"],
        "bid_window_id": row["bid_window_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def assignment(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "pairing_id": row["pairing_id"],
        "crew_member_id": row["crew_member_id"],
        "assigned_rank_slot": row["assigned_rank_slot"],
        "source": row["source"],
        "status": row["status"],
        "scheduled_block_minutes": row.get("scheduled_block_minutes", 0),
        "actual_block_minutes": row.get("actual_block_minutes", 0),
        "pay_credit_minutes": row.get("pay_credit_minutes", 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def reserve_pool(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "crew_member_id": row["crew_member_id"],
        "reserve_date": row["reserve_date"],
        "standby_start_at": row["standby_start_at"],
        "standby_end_at": row["standby_end_at"],
        "state": row["state"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def sick_call(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "crew_member_id": row["crew_member_id"],
        "assignment_id": row.get("assignment_id"),
        "reported_at": row["reported_at"],
        "effective_from": row["effective_from"],
        "expected_return_at": row["expected_return_at"],
        "covered_by_assignment_id": row.get("covered_by_assignment_id"),
        "created_at": row["created_at"],
    }


def trade_request(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "initiator_assignment_id": row["initiator_assignment_id"],
        "counterparty_assignment_id": row["counterparty_assignment_id"],
        "initiator_id": row["initiator_id"],
        "counterparty_id": row["counterparty_id"],
        "state": row["state"],
        "revision_count": row["revision_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }

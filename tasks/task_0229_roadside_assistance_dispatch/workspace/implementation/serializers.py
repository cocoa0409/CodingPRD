"""Entity -> public JSON representation.

Each entity record is stored as a plain dict already shaped like its public
form; serializers select/order the public fields and exclude internals.
"""

_COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(record, fields):
    return {k: record[k] for k in fields if k in record}


def membership_plan(r):
    return _pick(r, [
        "id", "tier", "annual_service_limit", "per_incident_mileage_cap_miles",
        "overage_rate_cents_per_mile", "priority_weight", "covered_service_types",
        "base_service_fee_cents", "created_at", "updated_at", "version",
    ])


def member(r):
    return _pick(r, [
        "id", "plan_id", "full_name", "status", "home_lat", "home_lng",
        "annual_period_start", "services_used_this_year", "outstanding_balance_cents",
        "created_at", "updated_at", "version",
    ])


def service_provider(r):
    return _pick(r, [
        "id", "company_name", "status", "current_lat", "current_lng",
        "capabilities", "rating", "active_call_id",
        "created_at", "updated_at", "version",
    ])


def provider_shift(r):
    return _pick(r, [
        "id", "provider_id", "shift_start", "shift_end", "status",
        "created_at", "updated_at", "version",
    ])


def depot(r):
    return _pick(r, [
        "id", "name", "lat", "lng", "bay_count", "cleanup_buffer_minutes",
        "occupied_bays", "created_at", "updated_at", "version",
    ])


def bay_reservation(r):
    return _pick(r, [
        "id", "depot_id", "service_call_id", "reserved_from", "reserved_until",
        "status", "created_at", "updated_at", "version",
    ])


def service_call(r):
    return _pick(r, [
        "id", "member_id", "service_type", "breakdown_lat", "breakdown_lng",
        "dropoff_lat", "dropoff_lng", "status", "assigned_provider_id",
        "tow_distance_miles", "estimated_cost_cents", "final_cost_cents",
        "member_out_of_pocket_cents", "final_towed_miles", "dispatch_attempts",
        "created_at", "updated_at", "version",
    ])


def dispatch_offer(r):
    return _pick(r, [
        "id", "service_call_id", "provider_id", "status", "eta_minutes",
        "offer_distance_miles", "created_at", "updated_at", "version",
    ])


def reimbursement_claim(r):
    return _pick(r, [
        "id", "member_id", "service_call_id", "claimed_amount_cents", "status",
        "approved_amount_cents", "created_at", "updated_at", "version",
    ])

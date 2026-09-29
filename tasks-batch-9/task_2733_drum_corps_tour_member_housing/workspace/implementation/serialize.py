"""Resource serializers.  Field names and order follow SCAFFOLD entities."""
import derive

COMMON = ("created_at", "updated_at", "version")

SEASON_FIELDS = (
    "id", "name", "year", "tuition_base_cents", "spring_training_start_date",
    "spring_training_end_date", "tour_departure_date", "billing_epoch",
    "tuition_charged_cents", "tuition_collected_cents", "late_fee_collected_cents",
    "housing_cost_cents", "tour_revenue_cents", "ledger_status",
)

MEMBER_FIELDS = (
    "id", "season_id", "full_name", "email", "date_of_birth", "section",
    "dietary_flag", "is_minor", "audition_score", "membership_status",
    "medical_status", "tuition_charged_cents", "tuition_paid_cents",
    "tuition_balance_cents", "refund_due_cents", "withdrawal_date",
    "withdrawal_obligation_cents", "withdrawal_obligation_basis",
)

CONTRACT_FIELDS = (
    "id", "member_id", "tuition_amount_cents", "payment_plan_type", "status",
    "revision_round", "revision_note", "signature_name", "signed_at", "executed_at",
)

PLAN_FIELDS = (
    "id", "member_id", "member_contract_id", "plan_type", "first_due_date",
    "installment_count", "principal_cents", "surcharge_cents",
    "financed_total_cents", "installment_base_cents", "installment_remainder_cents",
    "principal_paid_cents", "late_fee_accrued_cents", "late_fee_paid_cents",
    "installments_due_count", "due_amount_cents", "arrears_cents",
    "outstanding_cents", "delinquency_strikes", "status",
)

PAYMENT_FIELDS = (
    "id", "payment_plan_id", "amount_cents", "received_on", "method",
    "allocated_to_late_fee_cents", "allocated_to_principal_cents", "status",
    "reversal_reason", "reversed_at",
)

SCHOOL_FIELDS = (
    "id", "name", "city", "state_code", "sleeping_space_count",
    "capacity_per_space", "rehearsal_field_count", "has_air_conditioning",
    "booked_block_count", "reserved_bed_nights",
)

AGREEMENT_FIELDS = (
    "id", "host_school_id", "season_id", "usage_type", "start_date", "end_date",
    "nightly_rate_cents", "minimum_billable_beds", "countered_nightly_rate_cents",
    "counter_round", "effective_nightly_rate_cents", "occupied_bed_nights",
    "billable_bed_nights", "billable_cents", "status", "cancel_reason",
)

HOUSING_FIELDS = (
    "id", "facility_agreement_id", "member_id", "space_index", "check_in_date",
    "check_out_date", "nights", "occupant_is_minor", "status", "released_reason",
)

STOP_FIELDS = (
    "id", "season_id", "previous_stop_id", "stop_type", "venue_name", "city",
    "state_code", "arrive_at", "depart_at", "show_start_at",
    "travel_miles_from_previous", "uniform_trunks", "instrument_cases",
    "prop_units", "truck_count", "rehearsal_minutes", "heat_index_f",
    "total_load_cuft", "total_load_lbs", "trucks_required",
    "required_travel_minutes", "roster_head_count", "minor_head_count",
    "required_chaperone_count", "required_cook_count", "meal_cost_cents",
    "status", "settlement_state", "cancel_reason",
)

BOOKING_FIELDS = (
    "id", "tour_stop_id", "host_school_id", "facility_agreement_id",
    "block_start_at", "block_end_at", "indoor", "status", "released_reason",
)

VOLUNTEER_FIELDS = (
    "id", "full_name", "email", "role_type", "cdl_number", "credential_id",
    "screening_status", "screening_decided_on", "screening_expires_on",
    "screened_by_user_id", "assignment_count",
)

STAFF_FIELDS = (
    "id", "volunteer_id", "tour_stop_id", "duty", "shift_start_at",
    "shift_end_at", "status", "approved_by_user_id", "released_reason",
)

SETTLEMENT_FIELDS = (
    "id", "tour_stop_id", "appearance_fee_cents", "prize_pool_cents",
    "projected_placement", "final_placement", "provisional_prize_cents",
    "provisional_gross_cents", "provisional_circuit_fee_cents",
    "provisional_net_cents", "final_prize_cents", "final_gross_cents",
    "final_circuit_fee_cents", "sanctions_charged_cents", "rebate_applied_cents",
    "final_net_cents", "variance_cents", "remittance_line_count",
    "prepared_by_user_id", "finalized_by_user_id", "status",
)


def _out(record, fields, overrides=None):
    body = {}
    for field in fields:
        body[field] = record.get(field)
    if overrides:
        body.update(overrides)
    for field in COMMON:
        body[field] = record.get(field)
    return body


def season(record):
    return _out(record, SEASON_FIELDS, derive.season_figures(record))


def member(record):
    return _out(record, MEMBER_FIELDS, derive.member_figures(record))


def contract(record):
    return _out(record, CONTRACT_FIELDS)


def plan(record):
    return _out(record, PLAN_FIELDS, derive.plan_figures(record))


def payment(record):
    return _out(record, PAYMENT_FIELDS)


def school(record):
    return _out(record, SCHOOL_FIELDS, derive.school_figures(record))


def agreement(record):
    return _out(record, AGREEMENT_FIELDS, derive.agreement_figures(record))


def housing(record):
    return _out(record, HOUSING_FIELDS)


def stop(record):
    return _out(record, STOP_FIELDS)


def booking(record):
    return _out(record, BOOKING_FIELDS)


def volunteer(record):
    return _out(record, VOLUNTEER_FIELDS,
                {"assignment_count": derive.volunteer_assignment_count(record)})


def staff(record):
    return _out(record, STAFF_FIELDS)


def settlement(record):
    return _out(record, SETTLEMENT_FIELDS)

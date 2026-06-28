"""Serialize internal rows into API output objects.

Each serializer emits exactly the public fields from the entity table (scaffold
1.1) plus the system common fields. Internal bookkeeping (`_seq`) is stripped.
Computed fields (child_count, makeup_credit_balance, enrolled_count) are stored
live on the rows and reconciled synchronously, so they are read directly here.
"""

_VERSIONED_COMMON = ("id", "created_at", "updated_at", "version")
_LEAN_COMMON = ("id", "created_at")


def _base(row, fields, common):
    out = {}
    for f in common:
        out[f] = row.get(f)
    for f in fields:
        out[f] = row.get(f)
    return out


def family(row):
    return _base(row, ("account_email", "primary_contact_name", "child_count"), _VERSIONED_COMMON)


def child(row):
    return _base(row, ("family_id", "full_name", "birth_date", "current_level", "status"), _VERSIONED_COMMON)


def membership(row):
    return _base(row, (
        "family_id", "tier", "status", "cycle_anchor_day", "current_cycle_start",
        "makeup_credit_balance", "monthly_base_fee_cents",
    ), _VERSIONED_COMMON)


def program(row):
    return _base(row, (
        "name", "level_index", "min_age_months", "max_age_months",
        "participation_required", "tuition_cents", "next_program_id",
    ), _VERSIONED_COMMON)


def room(row):
    return _base(row, ("name", "physical_capacity"), _VERSIONED_COMMON)


def instructor(row):
    return _base(row, (
        "full_name", "certified_level_indices", "buffer_minutes", "status",
    ), _VERSIONED_COMMON)


def session(row):
    return _base(row, (
        "program_id", "room_id", "instructor_id", "start_at", "end_at",
        "capacity", "enrolled_count", "status",
    ), _VERSIONED_COMMON)


def enrollment(row):
    return _base(row, (
        "child_id", "session_id", "membership_id", "kind", "status",
        "waitlist_seq", "redeemed_credit_id", "residual_owed_cents",
    ), _VERSIONED_COMMON)


def attendance(row):
    return _base(row, ("enrollment_id", "session_id", "outcome"), _LEAN_COMMON)


def credit(row):
    return _base(row, (
        "membership_id", "source_attendance_id", "issued_tuition_cents",
        "status", "expires_at",
    ), _LEAN_COMMON)


def booking(row):
    return _base(row, (
        "room_id", "family_id", "booking_type", "start_at", "end_at",
        "head_count", "status",
    ), _VERSIONED_COMMON)


def invoice(row):
    return _base(row, (
        "membership_id", "cycle_start", "subtotal_cents",
        "sibling_discount_cents", "total_cents", "status",
    ), _VERSIONED_COMMON)

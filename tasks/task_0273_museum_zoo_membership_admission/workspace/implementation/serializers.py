"""Per-entity field projection for API responses.

Each serializer returns a dict containing exactly the fields declared for the
entity in scaffold §1.1, in a stable key order. Internal bookkeeping keys
(leading underscore) are never exposed.
"""

COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(record, fields):
    return {f: record.get(f) for f in fields}


def patron(r):
    return _pick(r, COMMON + ["email", "full_name", "home_partner_id"])


def membership_plan(r):
    return _pick(r, COMMON + [
        "tier", "annual_fee_cents", "household_max", "guest_passes_granted",
        "member_admission_cents", "exhibit_surcharge_waived", "reciprocal_eligible",
        "term_days", "reinstatement_fee_cents",
    ])


def membership(r):
    return _pick(r, COMMON + [
        "plan_id", "primary_patron_id", "status", "auto_renew", "started_at",
        "expires_at", "grace_until", "term_count", "last_paid_fee_cents",
    ])


def household_member(r):
    return _pick(r, COMMON + ["membership_id", "full_name", "relationship", "active"])


def guest_pass(r):
    return _pick(r, COMMON + ["membership_id", "status", "reserved_order_id"])


def timed_entry_slot(r):
    return _pick(r, COMMON + [
        "starts_at", "ends_at", "capacity_total", "reserved_count", "status",
        "non_member_admission_cents",
    ])


def special_exhibit(r):
    return _pick(r, COMMON + [
        "name", "surcharge_cents", "member_surcharge_discount_pct", "buffer_minutes",
    ])


def exhibit_session(r):
    return _pick(r, COMMON + [
        "exhibit_id", "starts_at", "ends_at", "capacity_total", "reserved_count",
    ])


def admission_order(r):
    return _pick(r, COMMON + [
        "patron_id", "slot_id", "membership_id", "exhibit_session_id", "party_size",
        "status", "donation_cents", "quoted_total_cents", "final_total_cents",
    ])


def admission_ticket(r):
    return _pick(r, COMMON + [
        "order_id", "ticket_type", "person_name", "guest_pass_id",
        "reciprocal_partner_id", "price_cents", "state",
    ])


def reciprocal_partner(r):
    return _pick(r, COMMON + ["org_name", "benefit_type", "discount_pct"])


def donation(r):
    # Immutable receipt: only id, created_at, order_id, membership_id, amount_cents.
    return _pick(r, ["id", "created_at", "order_id", "membership_id", "amount_cents"])

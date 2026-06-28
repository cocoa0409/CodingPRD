"""Entity assertions and domain invariant checkers.

Built on the framework's generic validators (is_valid_uuid, is_iso8601_timestamp).
Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_ARTIST_STATES = {"ACTIVE", "SUSPENDED"}
_ARTWORK_STATES = {"CONSIGNED", "RESERVED", "SOLD", "ON_LOAN", "RETURNED"}
_EXHIBITION_STATES = {"PLANNED", "OPEN", "CLOSED", "CANCELLED"}
_WALL_SLOT_STATES = {"PLACED", "RELEASED"}
_SALE_SETTLEMENT_STATES = {"RESERVED", "INVOICED", "PARTIALLY_PAID", "SETTLED", "VOID"}
_SALE_SHIPPING_STATES = {"PENDING", "SHIPPED", "DELIVERED"}
_PLAN_STATES = {"ACTIVE", "COMPLETED", "DEFAULTED", "CANCELLED"}
_LEASE_STATES = {"ACTIVE", "CONVERTED", "RETURNED", "TERMINATED"}
_EVENT_STATES = {"SCHEDULED", "CLOSED", "CANCELLED"}
_RSVP_STATES = {"CONFIRMED", "WAITLISTED", "CANCELLED", "PROMOTED"}
_LOAN_STATES = {"OUTSTANDING", "RETURNED", "OVERDUE"}
_PAYOUT_STATES = {"PENDING", "COMPLETED", "REVERSED"}


def _assert_common(data: dict):
    """Common fields carried by every entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_gallery(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["home_state_code"], str) and len(data["home_state_code"]) == 2
    assert isinstance(data["sales_tax_rate_bps"], int)
    assert is_iso8601_timestamp(data.get("clock_utc", "")), "clock_utc must be ISO 8601"


def assert_artist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in _ARTIST_STATES, f"unexpected artist status {data['status']!r}"
    for fld in ("ledger_accrued_cents", "ledger_paid_cents", "ledger_payable_cents"):
        assert isinstance(data[fld], int) and data[fld] >= 0, f"{fld} must be a non-negative int"


def assert_artwork(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["insured_value_cents"], int) and data["insured_value_cents"] > 0
    assert data["status"] in _ARTWORK_STATES, f"unexpected artwork status {data['status']!r}"
    assert isinstance(data["provenance_count"], int) and data["provenance_count"] >= 1
    assert isinstance(data["provenance_log"], list)


def assert_exhibition(data: dict):
    _assert_common(data)
    assert isinstance(data["wall_capacity"], int) and data["wall_capacity"] > 0
    assert data["status"] in _EXHIBITION_STATES, f"unexpected exhibition status {data['status']!r}"
    assert isinstance(data["slots_occupied"], int) and data["slots_occupied"] >= 0
    assert isinstance(data["slots_available"], int) and data["slots_available"] >= 0


def assert_wall_slot(data: dict):
    _assert_common(data)
    assert data["status"] in _WALL_SLOT_STATES, f"unexpected wall slot status {data['status']!r}"
    assert isinstance(data["position_index"], int) and data["position_index"] >= 0


def assert_sale(data: dict):
    _assert_common(data)
    assert data["settlement_status"] in _SALE_SETTLEMENT_STATES
    assert data["shipping_status"] in _SALE_SHIPPING_STATES
    for fld in ("gross_amount_cents", "net_amount_cents", "tax_amount_cents",
                "buyer_total_cents", "artist_share_cents", "gallery_share_cents",
                "amount_collected_cents"):
        assert isinstance(data[fld], int), f"{fld} must be an int"


def assert_payment_plan(data: dict):
    _assert_common(data)
    assert data["status"] in _PLAN_STATES, f"unexpected plan status {data['status']!r}"
    assert isinstance(data["installment_cents"], int)
    assert isinstance(data["final_installment_cents"], int)
    assert isinstance(data["posted_installment_count"], int)
    assert isinstance(data["missed_installment_count"], int)


def assert_lease(data: dict):
    _assert_common(data)
    assert data["status"] in _LEASE_STATES, f"unexpected lease status {data['status']!r}"
    assert isinstance(data["months_accrued"], int) and data["months_accrued"] >= 0
    assert isinstance(data["rent_accrued_cents"], int) and data["rent_accrued_cents"] >= 0
    assert isinstance(data["buyout_price_cents"], int) and data["buyout_price_cents"] >= 0


def assert_opening_event(data: dict):
    _assert_common(data)
    assert data["status"] in _EVENT_STATES, f"unexpected event status {data['status']!r}"
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0
    assert isinstance(data["waitlist_count"], int) and data["waitlist_count"] >= 0


def assert_rsvp(data: dict):
    _assert_common(data)
    assert data["status"] in _RSVP_STATES, f"unexpected rsvp status {data['status']!r}"
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1


def assert_loan(data: dict):
    _assert_common(data)
    assert data["status"] in _LOAN_STATES, f"unexpected loan status {data['status']!r}"
    assert isinstance(data["coverage_value_cents"], int) and data["coverage_value_cents"] > 0


def assert_payout(data: dict):
    _assert_common(data)
    assert data["status"] in _PAYOUT_STATES, f"unexpected payout status {data['status']!r}"
    assert isinstance(data["requested_cents"], int) and data["requested_cents"] > 0
    assert isinstance(data["approved_cents"], int) and data["approved_cents"] >= 0


# ─── Domain invariant checkers ───────────────────────────────────────────────
def assert_ledger_conservation(artist: dict):
    """PRD §2.10: at every moment accrued == paid + payable, and payable is
    floored at zero."""
    assert artist["ledger_payable_cents"] >= 0, "payable must never go negative"
    assert artist["ledger_accrued_cents"] == \
        artist["ledger_paid_cents"] + artist["ledger_payable_cents"], (
        "ledger conservation violated: accrued must equal paid + payable "
        f"({artist['ledger_accrued_cents']} != {artist['ledger_paid_cents']} "
        f"+ {artist['ledger_payable_cents']})"
    )


def assert_slot_occupancy(exhibition: dict):
    """PRD §2.11: slots_available is wall_capacity minus slots_occupied, never
    negative, so occupancy + availability conserve wall_capacity."""
    assert exhibition["slots_available"] >= 0, "slots_available must never go negative"
    assert exhibition["slots_occupied"] + exhibition["slots_available"] == \
        exhibition["wall_capacity"], (
        "wall-slot occupancy not conserved: occupied + available must equal "
        f"wall_capacity ({exhibition['slots_occupied']} + "
        f"{exhibition['slots_available']} != {exhibition['wall_capacity']})"
    )

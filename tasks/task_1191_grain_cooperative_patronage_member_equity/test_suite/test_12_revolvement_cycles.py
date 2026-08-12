"""Revolvement cycle window overlap: half-open interval semantics
(PRD §3.5)."""
from test_helpers import (
    validate_success, validate_error,
    create_district, create_member, seat_delegate, set_clock,
    create_cycle, create_and_open_cycle, pass_resolution,
    TEST_USERS,
)

SECRETARY = TEST_USERS["secretary_headers"]


def _district_with_delegate():
    set_clock("2030-01-01T00:00:00Z")
    district = create_district()
    member = create_member(district["id"])
    delegate = seat_delegate(district["id"], member["id"])
    return district, member, delegate


def test_overlapping_cycle_open_rejected(api):
    """PRD §3.5: "Opening it — moving `PLANNED` → `OPEN` — requires a
    `PASSED` resolution of kind `OPEN_REVOLVEMENT` referencing the cycle,
    requires that the logical clock has reached `window_start`, and requires
    that no other `OPEN` cycle for the same equity class has a window
    overlapping this one; a conflicting cycle is rejected with
    `ERR_CYCLE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/revolvement_cycle_no_overlap_on_equity_class
    """
    _, _, delegate = _district_with_delegate()
    cyc_a = create_and_open_cycle(
        "2030-01-01T00:00:00Z", "2030-06-01T00:00:00Z", delegate["id"],
        open_clock="2030-01-01T00:00:00Z",
    )
    cyc_b = create_cycle(
        "2030-03-01T00:00:00Z", "2030-09-01T00:00:00Z",
    )
    pass_resolution("OPEN_REVOLVEMENT", cyc_b["id"], delegate["id"])
    set_clock("2030-03-01T00:00:00Z")
    res = api.open_cycle(cyc_b["id"], SECRETARY)
    validate_error(res, "ERR_CYCLE_OVERLAP", expected_status=409)
    after_b = validate_success(api.get_revolvement_cycle(cyc_b["id"], SECRETARY))
    assert after_b["status"] == "PLANNED", (
        f"Rejected cycle must stay PLANNED, got {after_b['status']}"
    )
    after_a = validate_success(api.get_revolvement_cycle(cyc_a["id"], SECRETARY))
    assert after_a["status"] == "OPEN"


def test_adjacent_cycle_open_allowed(api):
    """PRD §3.5: "The `BoardSecretary` plans a cycle by supplying a
    `cycle_code`, the `equity_class` of the certificate pool the cycle
    revolves, a `target_year_offset` (how many years after issuance the cycle
    retires), the redemption window `window_start` (inclusive) and
    `window_end` (exclusive), the `budget_cap_cents` the board authorizes the
    cycle to redeem in total, and the `board_resolution_id` of the enabling
    resolution."

    With half-open windows [window_start, window_end), a cycle starting
    exactly when the other ends shares no instant with it, so opening it is
    not a conflict under §3.5's overlap rule.

    Design: Difficulty/resource_temporal_overlap/revolvement_cycle_no_overlap_on_equity_class
    """
    _, _, delegate = _district_with_delegate()
    create_and_open_cycle(
        "2030-01-01T00:00:00Z", "2030-06-01T00:00:00Z", delegate["id"],
        open_clock="2030-01-01T00:00:00Z",
    )
    cyc_c = create_cycle(
        "2030-06-01T00:00:00Z", "2030-12-01T00:00:00Z",
    )
    pass_resolution("OPEN_REVOLVEMENT", cyc_c["id"], delegate["id"])
    set_clock("2030-06-01T00:00:00Z")
    opened = validate_success(api.open_cycle(cyc_c["id"], SECRETARY), 200)
    assert opened["status"] == "OPEN", (
        "Adjacent window (start == other's exclusive end) must not conflict"
    )

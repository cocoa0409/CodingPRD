"""Validation precedence conflicts, cross-entity state dependencies, and
temporal-overlap rules (meter assignment half-open, lease occupancy closed).

Covers queue-A priority_pair_validation_conflict, cross_entity_state_dependency,
and resource_temporal_overlap.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    make_tenant_headers, assign_meter_payload,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["property_manager_headers"]


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict / invalid_state_beats_credit_exceeds_due_on_resolve
# --------------------------------------------------------------------------- #
def test_resolve_on_open_dispute_with_excess_credit_yields_invalid_state(api):
    """PRD §3.12: "Only then is the target's state checked: a transition
    requested from a state that does not allow it yields `ERR_INVALID_STATE`.
    Finally the endpoint-specific business rules run — meter-assignment overlap,
    lease-occupancy overlap, the read high-reading band, read-lock completeness,
    vendor-bill approval, late-fee timing, dispute-credit limits, payment OCC,
    and payment-amount bounds — each in the position its workflow describes."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_credit_exceeds_due_on_resolve
    """
    # An OPEN dispute (start-review never called). credit_amount far above total.
    bundle = fx.setup_open_dispute(reason="DOUBLE_BILLED", total_cost_cents=7059, tenant_user_id="tV1")
    validate_error(
        api.resolve_dispute(bundle["dispute"]["id"], {"credit_amount_cents": 999999}, PM),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_resolve_on_open_dispute_leaves_dispute_open(api):
    """PRD §3.11: "Resolving a dispute moves it from `UNDER_REVIEW` to
    `RESOLVED` and grants a credit."
    PRD §3.12: "Only then is the target's state checked: a transition requested
    from a state that does not allow it yields `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_credit_exceeds_due_on_resolve
    """
    bundle = fx.setup_open_dispute(reason="DOUBLE_BILLED", total_cost_cents=7059, tenant_user_id="tV1b")
    validate_error(
        api.resolve_dispute(bundle["dispute"]["id"], {"credit_amount_cents": 999999}, PM),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    # the state check pre-empts the fiscal cap; the dispute is untouched
    after = get_success_data(api.get_dispute(bundle["dispute"]["id"], PM))
    assert after["status"] == "OPEN"
    stmt = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    assert stmt["credit_cents"] == 0


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict / not_statement_owner_beats_invalid_state_on_reopen
# --------------------------------------------------------------------------- #
def test_reopen_by_non_owner_on_open_dispute_yields_not_statement_owner(api):
    """PRD §3.12: "After that, for tenant-scoped actions, ownership is checked,
    yielding `ERR_NOT_STATEMENT_OWNER` when the caller does not own the lease
    behind the resource."
    PRD §3.12: "Only then is the target's state checked: a transition requested
    from a state that does not allow it yields `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/not_statement_owner_beats_invalid_state_on_reopen
    """
    # An OPEN dispute owned by tOWN; reopen requires RESOLVED, so reopen is also
    # state-invalid. A different tenant tOTHER attempts reopen.
    bundle = fx.setup_open_dispute(reason="WRONG_METER", total_cost_cents=7059, tenant_user_id="tOWN")
    other = make_tenant_headers("tOTHER")
    validate_error(
        api.reopen_dispute(bundle["dispute"]["id"], other),
        ApiErrorId.ERR_NOT_STATEMENT_OWNER.value,
    )


def test_reopen_by_non_owner_leaves_dispute_unchanged(api):
    """PRD §2.1: "any attempt by a tenant to act on a statement, dispute,
    payment, or lease that does not belong to them is rejected with
    `ERR_NOT_STATEMENT_OWNER`."
    PRD §3.12: "for tenant-scoped actions, ownership is checked, yielding
    `ERR_NOT_STATEMENT_OWNER` when the caller does not own the lease behind the
    resource."

    Design: Difficulty/priority_pair_validation_conflict/not_statement_owner_beats_invalid_state_on_reopen
    """
    bundle = fx.setup_open_dispute(reason="WRONG_METER", total_cost_cents=7059, tenant_user_id="tOWN2")
    other = make_tenant_headers("tOTHER2")
    validate_error(
        api.reopen_dispute(bundle["dispute"]["id"], other),
        ApiErrorId.ERR_NOT_STATEMENT_OWNER.value,
    )
    # ownership check pre-empts the state check; reopen_count not advanced
    after = get_success_data(api.get_dispute(bundle["dispute"]["id"], PM))
    assert after["status"] == "OPEN"
    assert after["reopen_count"] == 0


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / lease_close_blocked_by_open_statement_balance
# --------------------------------------------------------------------------- #
def test_close_lease_blocked_by_unpaid_statement(api):
    """PRD §3.3: "a `MOVED_OUT` lease may be closed, moving it to the terminal
    `CLOSED`, but only when none of the lease's statements still owe money — that
    is, when no `TenantStatement` of the lease has a `payment_status` of
    `UNPAID`, `PARTIALLY_PAID`, `DELINQUENT`, or `IN_COLLECTIONS`. A lease with
    any such open balance cannot be closed and the attempt is rejected with
    `ERR_LEASE_HAS_OPEN_BALANCE`."

    Design: Difficulty/cross_entity_state_dependency/lease_close_blocked_by_open_statement_balance
    """
    bundle = fx.setup_single_rubs_statement(total_cost_cents=20000, tenant_user_id="tL")
    lease = bundle["lease"]
    # drive the lease to MOVED_OUT
    get_success_data(api.give_notice(lease["id"], {"move_out_date": "2026-06-20T00:00:00Z"}, PM))
    fx.set_clock("2026-06-21T00:00:00Z")
    moved = validate_success(api.move_out_lease(lease["id"], PM))
    assert moved["status"] == "MOVED_OUT"
    validate_error(api.close_lease(lease["id"], PM), ApiErrorId.ERR_LEASE_HAS_OPEN_BALANCE.value)
    after = get_success_data(api.get_lease(lease["id"], PM))
    assert after["status"] == "MOVED_OUT"


def test_close_lease_succeeds_once_statement_paid(api):
    """PRD §3.3: "a `MOVED_OUT` lease may be closed, moving it to the terminal
    `CLOSED`, but only when none of the lease's statements still owe money — that
    is, when no `TenantStatement` of the lease has a `payment_status` of
    `UNPAID`, `PARTIALLY_PAID`, `DELINQUENT`, or `IN_COLLECTIONS`."

    Design: Difficulty/cross_entity_state_dependency/lease_close_blocked_by_open_statement_balance
    """
    bundle = fx.setup_single_rubs_statement(total_cost_cents=20000, tenant_user_id="tL2")
    lease = bundle["lease"]
    stmt = bundle["statement"]
    tenant = make_tenant_headers("tL2")
    # pay the full balance so the statement is PAID (no longer owing)
    validate_success(
        api.post_payment(
            stmt["id"],
            {"amount_cents": stmt["balance_due_cents"], "expected_statement_version": stmt["version"]},
            tenant,
        ),
        expected_status=201,
    )
    get_success_data(api.give_notice(lease["id"], {"move_out_date": "2026-06-20T00:00:00Z"}, PM))
    fx.set_clock("2026-06-21T00:00:00Z")
    get_success_data(api.move_out_lease(lease["id"], PM))
    data = validate_success(api.close_lease(lease["id"], PM))
    assert data["status"] == "CLOSED"


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / vendor_bill_void_blocked_by_referencing_cycle_status
# --------------------------------------------------------------------------- #
def test_void_approved_vendor_bill_allowed_while_cycle_open(api):
    """PRD §3.4: "an `APPROVED` bill may be voided only when no billing cycle
    references it in `ALLOCATED`, `STATEMENTS_ISSUED`, or `CLOSED` status; a
    referenced bill that cannot be voided is rejected with
    `ERR_VENDOR_BILL_IN_USE`."

    Design: Difficulty/cross_entity_state_dependency/vendor_bill_void_blocked_by_referencing_cycle_status
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA", common_area_pct=0.10)
    util = fx.create_utility(prop["id"], allocation_method="RUBS")
    unit = fx.create_unit(prop["id"], unit_number="VBU2")
    fx.create_active_lease(unit["id"], prop["id"], "tVB2")
    vb = fx.create_approved_vendor_bill(prop["id"], util["id"], total_cost_cents=20000)
    # cycle references the bill but is only OPEN (not ALLOCATED/STATEMENTS_ISSUED/CLOSED)
    fx.open_billing_cycle(prop["id"], util["id"], vb["id"])
    data = validate_success(api.void_vendor_bill(vb["id"], PM))
    assert data["status"] == "VOIDED"


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / meter_assignment_half_open_window_overlap
# --------------------------------------------------------------------------- #
def test_meter_assignment_overlap_half_open(api):
    """PRD §3.2: "It then checks that the requested window does not overlap any
    other assignment of the same unit for the same utility; because the window is
    half-open, two windows overlap when one starts strictly before the other ends
    and ends strictly after the other starts, and a window that begins exactly
    where another ends does not overlap. An overlap is rejected with
    `ERR_METER_ASSIGNMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/meter_assignment_half_open_window_overlap
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA", common_area_pct=0.10)
    util = fx.create_utility(prop["id"], allocation_method="CONSUMPTION")
    unit = fx.create_unit(prop["id"], unit_number="MOU")
    meter = fx.create_meter(prop["id"], util["id"], serial_number="MOS")
    get_success_data(
        api.assign_meter(
            meter["id"],
            assign_meter_payload(
                unit["id"], effective_from="2026-06-01T00:00:00Z",
                effective_to="2026-07-01T00:00:00Z",
            ),
            PM,
        )
    )
    # [06-30, 08-01) overlaps [06-01, 07-01) by one day
    validate_error(
        api.assign_meter(
            meter["id"],
            assign_meter_payload(
                unit["id"], effective_from="2026-06-30T00:00:00Z",
                effective_to="2026-08-01T00:00:00Z",
            ),
            PM,
        ),
        ApiErrorId.ERR_METER_ASSIGNMENT_OVERLAP.value,
    )


def test_meter_assignment_adjacent_window_allowed(api):
    """PRD §3.2: "a window that begins exactly where another ends does not
    overlap."
    PRD §3.2: "An already-`ASSIGNED` meter may be re-assigned to a new window
    while staying `ASSIGNED`."

    Design: Difficulty/resource_temporal_overlap/meter_assignment_half_open_window_overlap
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA", common_area_pct=0.10)
    util = fx.create_utility(prop["id"], allocation_method="CONSUMPTION")
    unit = fx.create_unit(prop["id"], unit_number="MOU2")
    meter = fx.create_meter(prop["id"], util["id"], serial_number="MOS2")
    get_success_data(
        api.assign_meter(
            meter["id"],
            assign_meter_payload(
                unit["id"], effective_from="2026-06-01T00:00:00Z",
                effective_to="2026-07-01T00:00:00Z",
            ),
            PM,
        )
    )
    # new window starting exactly at prior effective_to: adjacency allowed
    data = validate_success(
        api.assign_meter(
            meter["id"],
            assign_meter_payload(
                unit["id"], effective_from="2026-07-01T00:00:00Z",
                effective_to="2026-08-01T00:00:00Z",
            ),
            PM,
        )
    )
    assert data["status"] == "ASSIGNED"


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / lease_occupancy_closed_interval_overlap_move_out_inclusive
# --------------------------------------------------------------------------- #
def test_lease_occupancy_overlap_move_out_inclusive(api):
    """PRD §3.3: "no other lease of the same unit in `ACTIVE` or `NOTICE_GIVEN`
    status has an occupancy interval that overlaps this lease's `move_in_date`.
    An occupancy interval runs from `move_in_date` to `move_out_date` with the
    move-out day treated as inclusive, and a null `move_out_date` makes the
    interval open-ended. A conflicting occupancy is rejected with
    `ERR_LEASE_OCCUPANCY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lease_occupancy_closed_interval_overlap_move_out_inclusive
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA", common_area_pct=0.10)
    unit = fx.create_unit(prop["id"], unit_number="LOU")
    lease1 = fx.create_active_lease(unit["id"], prop["id"], "tLO1", move_in_date="2026-06-01T00:00:00Z")
    get_success_data(api.give_notice(lease1["id"], {"move_out_date": "2026-06-20T00:00:00Z"}, PM))
    lease2 = get_success_data(
        api.create_lease(
            {
                "unit_id": unit["id"], "property_id": prop["id"],
                "tenant_user_id": "tLO2", "occupant_count": 1,
                "move_in_date": "2026-06-20T00:00:00Z",
            },
            PM,
        )
    )
    # move_in 06-20 == inclusive move_out 06-20 of the NOTICE_GIVEN lease
    validate_error(api.activate_lease(lease2["id"], PM), ApiErrorId.ERR_LEASE_OCCUPANCY_OVERLAP.value)
    after = get_success_data(api.get_lease(lease2["id"], PM))
    assert after["status"] == "PENDING"


def test_lease_activation_succeeds_day_after_inclusive_move_out(api):
    """PRD §3.3: "An occupancy interval runs from `move_in_date` to
    `move_out_date` with the move-out day treated as inclusive, and a null
    `move_out_date` makes the interval open-ended. A conflicting occupancy is
    rejected with `ERR_LEASE_OCCUPANCY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lease_occupancy_closed_interval_overlap_move_out_inclusive
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA", common_area_pct=0.10)
    unit = fx.create_unit(prop["id"], unit_number="LOU2")
    lease1 = fx.create_active_lease(unit["id"], prop["id"], "tLO3", move_in_date="2026-06-01T00:00:00Z")
    get_success_data(api.give_notice(lease1["id"], {"move_out_date": "2026-06-20T00:00:00Z"}, PM))
    lease2 = get_success_data(
        api.create_lease(
            {
                "unit_id": unit["id"], "property_id": prop["id"],
                "tenant_user_id": "tLO4", "occupant_count": 1,
                # move_in one day after the inclusive move_out -> no overlap
                "move_in_date": "2026-06-21T00:00:00Z",
            },
            PM,
        )
    )
    data = validate_success(api.activate_lease(lease2["id"], PM))
    assert data["status"] == "ACTIVE"

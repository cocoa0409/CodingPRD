"""State-machine transitions: invalid transitions, precondition enforcement,
side effects, terminal-state lockdown, and the cycle close integrity recompute.

Covers queue-B section: state_machines corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    make_tenant_headers, create_meter_read_payload,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["property_manager_headers"]
TECH = TEST_USERS["meter_tech_headers"]


# --------------------------------------------------------------------------- #
# state_machines / approve_already_approved_vendor_bill_returns_invalid_state
# --------------------------------------------------------------------------- #
def test_approve_already_approved_vendor_bill_rejected(api):
    """PRD §3.4: "Approving a vendor bill moves it from `RECEIVED` to `APPROVED`"
    PRD §3.12: "Only then is the target's state checked: a transition requested
    from a state that does not allow it yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_already_approved_vendor_bill_returns_invalid_state
    """
    prop = fx.create_property(state_code="CA")
    util = fx.create_utility(prop["id"], allocation_method="RUBS")
    vb = fx.create_approved_vendor_bill(prop["id"], util["id"], total_cost_cents=20000)
    validate_error(api.approve_vendor_bill(vb["id"], PM), ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------- #
# state_machines / validate_read_still_pending_returns_invalid_state
# --------------------------------------------------------------------------- #
def test_validate_pending_read_rejected(api):
    """PRD §3.5: "A `PropertyManager` validates a submitted read, moving it from
    `SUBMITTED` to `VALIDATED`."
    PRD §3.12: "Only then is the target's state checked: a transition requested
    from a state that does not allow it yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/validate_read_still_pending_returns_invalid_state
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA")
    util = fx.create_utility(prop["id"], allocation_method="CONSUMPTION")
    unit = fx.create_unit(prop["id"], unit_number="P1")
    meter = fx.create_and_assign_meter(prop["id"], util["id"], unit["id"], "PS1")
    vb = fx.create_vendor_bill(prop["id"], util["id"], total_cost_cents=30000)
    fx.open_billing_cycle(prop["id"], util["id"], vb["id"])
    read = get_success_data(
        api.create_meter_read(create_meter_read_payload(meter["id"], prop["id"], reading_value=120), TECH)
    )
    validate_error(api.validate_meter_read(read["id"], PM), ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------- #
# state_machines / submit_read_when_cycle_not_open_returns_cycle_not_open
# --------------------------------------------------------------------------- #
def test_submit_read_when_cycle_locked_rejected(api):
    """PRD §3.5: "The matching billing cycle — the one whose property, utility,
    and period align with this read — must be `OPEN`, or the submission is
    rejected with `ERR_CYCLE_NOT_OPEN`."

    Design: Corner/state_machines/submit_read_when_cycle_not_open_returns_cycle_not_open
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA")
    util = fx.create_utility(prop["id"], allocation_method="CONSUMPTION")
    unit = fx.create_unit(prop["id"], unit_number="L1")
    meter = fx.create_and_assign_meter(prop["id"], util["id"], unit["id"], "LS1")
    vb = fx.create_vendor_bill(prop["id"], util["id"], total_cost_cents=30000)
    cycle = fx.open_billing_cycle(prop["id"], util["id"], vb["id"])
    fx.submit_and_validate_read(meter["id"], prop["id"], reading_value=100)
    get_success_data(api.lock_reads(cycle["id"], PM))  # cycle -> READS_LOCKED
    read2 = get_success_data(
        api.create_meter_read(create_meter_read_payload(meter["id"], prop["id"], reading_value=130), TECH)
    )
    validate_error(api.submit_meter_read(read2["id"], headers=TECH), ApiErrorId.ERR_CYCLE_NOT_OPEN.value)


# --------------------------------------------------------------------------- #
# state_machines / retire_meter_with_pending_reads_returns_meter_has_pending_reads
# --------------------------------------------------------------------------- #
def test_retire_meter_with_pending_reads_rejected(api):
    """PRD §3.2: "A meter that is currently `ASSIGNED` may be retired only when
    it has no meter read in `SUBMITTED` or `RE_READ_REQUESTED` status tied to an
    `OPEN` billing cycle; if such a pending read exists the retirement is
    rejected with `ERR_METER_HAS_PENDING_READS`."

    Design: Corner/state_machines/retire_meter_with_pending_reads_returns_meter_has_pending_reads
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA")
    util = fx.create_utility(prop["id"], allocation_method="CONSUMPTION")
    unit = fx.create_unit(prop["id"], unit_number="R1")
    meter = fx.create_and_assign_meter(prop["id"], util["id"], unit["id"], "RS1")
    vb = fx.create_vendor_bill(prop["id"], util["id"], total_cost_cents=30000)
    fx.open_billing_cycle(prop["id"], util["id"], vb["id"])
    read = get_success_data(
        api.create_meter_read(create_meter_read_payload(meter["id"], prop["id"], reading_value=100), TECH)
    )
    get_success_data(api.submit_meter_read(read["id"], headers=TECH))  # SUBMITTED in OPEN cycle
    validate_error(api.retire_meter(meter["id"], PM), ApiErrorId.ERR_METER_HAS_PENDING_READS.value)
    after = get_success_data(api.get_meter(meter["id"], PM))
    assert after["status"] == "ASSIGNED"


# --------------------------------------------------------------------------- #
# state_machines / activate_lease_sets_unit_occupied_side_effect
# --------------------------------------------------------------------------- #
def test_activate_lease_sets_unit_occupied(api):
    """PRD §3.3: "On success the lease becomes `ACTIVE` and the unit transitions
    to `OCCUPIED`."

    Design: Corner/state_machines/activate_lease_sets_unit_occupied_side_effect
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA")
    unit = fx.create_unit(prop["id"], unit_number="O1")
    lease = get_success_data(
        api.create_lease(
            {
                "unit_id": unit["id"], "property_id": prop["id"],
                "tenant_user_id": "tO", "occupant_count": 2,
                "move_in_date": "2026-06-01T00:00:00Z",
            },
            PM,
        )
    )
    data = validate_success(api.activate_lease(lease["id"], PM))
    assert data["status"] == "ACTIVE"
    unit_after = get_success_data(api.get_unit(unit["id"], PM))
    assert unit_after["status"] == "OCCUPIED"


# --------------------------------------------------------------------------- #
# state_machines / lock_reads_with_unvalidated_meter_returns_reads_not_validated
# --------------------------------------------------------------------------- #
def test_lock_reads_with_unvalidated_meter_rejected(api):
    """PRD §3.6: "For a utility whose allocation method is `CONSUMPTION`, every
    assigned, non-`RETIRED` meter of that property and utility must have exactly
    one `VALIDATED` read for the period, with none lingering in `SUBMITTED`,
    `FLAGGED`, or `RE_READ_REQUESTED`; if any consumption meter lacks its single
    validated read or has an unresolved read, the lock is rejected with
    `ERR_READS_NOT_VALIDATED`."

    Design: Corner/state_machines/lock_reads_with_unvalidated_meter_returns_reads_not_validated
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA")
    util = fx.create_utility(prop["id"], allocation_method="CONSUMPTION")
    unit = fx.create_unit(prop["id"], unit_number="NV1")
    meter = fx.create_and_assign_meter(prop["id"], util["id"], unit["id"], "NVS1")
    vb = fx.create_vendor_bill(prop["id"], util["id"], total_cost_cents=30000)
    cycle = fx.open_billing_cycle(prop["id"], util["id"], vb["id"])
    read = get_success_data(
        api.create_meter_read(create_meter_read_payload(meter["id"], prop["id"], reading_value=100), TECH)
    )
    get_success_data(api.submit_meter_read(read["id"], headers=TECH))  # only SUBMITTED, not VALIDATED
    validate_error(api.lock_reads(cycle["id"], PM), ApiErrorId.ERR_READS_NOT_VALIDATED.value)


# --------------------------------------------------------------------------- #
# state_machines / allocate_with_unapproved_vendor_bill_returns_vendor_bill_not_approved
# --------------------------------------------------------------------------- #
def test_allocate_with_unapproved_vendor_bill_rejected(api):
    """PRD §3.6: "Allocating a cycle moves it from `READS_LOCKED` to `ALLOCATED`
    and is where the recoverable pool is divided into per-unit shares. The
    cycle's referenced vendor bill must be `APPROVED`, or the allocation is
    rejected with `ERR_VENDOR_BILL_NOT_APPROVED`."

    Design: Corner/state_machines/allocate_with_unapproved_vendor_bill_returns_vendor_bill_not_approved
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA")
    util = fx.create_utility(prop["id"], allocation_method="RUBS")
    unit = fx.create_unit(prop["id"], unit_number="NA1")
    fx.create_active_lease(unit["id"], prop["id"], "tNA")
    vb = fx.create_vendor_bill(prop["id"], util["id"], total_cost_cents=30000)  # NOT approved
    cycle = fx.open_billing_cycle(prop["id"], util["id"], vb["id"])
    get_success_data(api.lock_reads(cycle["id"], PM))
    validate_error(api.allocate_cycle(cycle["id"], PM), ApiErrorId.ERR_VENDOR_BILL_NOT_APPROVED.value)


# --------------------------------------------------------------------------- #
# state_machines / issue_statements_no_billable_leases_returns_no_billable_leases
# --------------------------------------------------------------------------- #
def test_issue_statements_no_billable_leases_rejected(api):
    """PRD §3.6: "At least one lease in `ACTIVE`, `NOTICE_GIVEN`, or `MOVED_OUT`
    status must have occupied a billed unit during the period, or the issue is
    rejected with `ERR_NO_BILLABLE_LEASES`."

    Design: Corner/state_machines/issue_statements_no_billable_leases_returns_no_billable_leases
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA")
    util = fx.create_utility(prop["id"], allocation_method="RUBS")
    unit = fx.create_unit(prop["id"], unit_number="NB1")
    # only a PENDING lease (never activated) -> not billable
    get_success_data(
        api.create_lease(
            {
                "unit_id": unit["id"], "property_id": prop["id"],
                "tenant_user_id": "tNB", "occupant_count": 1,
                "move_in_date": "2026-06-01T00:00:00Z",
            },
            PM,
        )
    )
    vb = fx.create_approved_vendor_bill(prop["id"], util["id"], total_cost_cents=30000)
    cycle = fx.open_billing_cycle(prop["id"], util["id"], vb["id"])
    get_success_data(api.lock_reads(cycle["id"], PM))
    get_success_data(api.allocate_cycle(cycle["id"], PM))
    validate_error(api.issue_statements(cycle["id"], PM), ApiErrorId.ERR_NO_BILLABLE_LEASES.value)


# --------------------------------------------------------------------------- #
# state_machines / close_cycle_with_open_dispute_returns_cycle_has_open_disputes
# --------------------------------------------------------------------------- #
def test_close_cycle_with_open_dispute_rejected(api):
    """PRD §3.6: "Closing a cycle moves it from `STATEMENTS_ISSUED` to the
    terminal `CLOSED`, permitted only when no statement of the cycle has a
    dispute in `OPEN` or `UNDER_REVIEW` status; an open dispute blocks closure
    with `ERR_CYCLE_HAS_OPEN_DISPUTES`."

    Design: Corner/state_machines/close_cycle_with_open_dispute_returns_cycle_has_open_disputes
    """
    bundle = fx.setup_single_rubs_statement(total_cost_cents=30000, tenant_user_id="tCD")
    tenant = make_tenant_headers("tCD")
    get_success_data(api.open_dispute(bundle["statement"]["id"], {"reason": "RATIO_ERROR"}, tenant))
    validate_error(api.close_cycle(bundle["cycle"]["id"], PM), ApiErrorId.ERR_CYCLE_HAS_OPEN_DISPUTES.value)


# --------------------------------------------------------------------------- #
# state_machines / reopen_resolved_dispute_beyond_max_reopens_returns_max_reopens_reached
# --------------------------------------------------------------------------- #
def test_reopen_beyond_max_reopens_rejected(api):
    """PRD §3.11: "Reopening is allowed only while the parent billing cycle is
    not `CLOSED` (otherwise `ERR_CYCLE_CLOSED`) and only while the dispute's
    `reopen_count` is below the maximum of two reopens; exceeding that limit is
    rejected with `ERR_MAX_REOPENS_REACHED`."

    Design: Corner/state_machines/reopen_resolved_dispute_beyond_max_reopens_returns_max_reopens_reached
    """
    bundle = fx.setup_dispute_under_review(
        credit_amount_cents=1000, reason="HIGH_READING", total_cost_cents=30000, tenant_user_id="tMR"
    )
    dispute_id = bundle["dispute"]["id"]
    # resolve+reopen twice (reopen_count -> 2), then resolve once more
    get_success_data(api.resolve_dispute(dispute_id, {"credit_amount_cents": 1000}, PM))
    get_success_data(api.reopen_dispute(dispute_id, PM))
    get_success_data(api.resolve_dispute(dispute_id, {"credit_amount_cents": 1000}, PM))
    get_success_data(api.reopen_dispute(dispute_id, PM))
    get_success_data(api.resolve_dispute(dispute_id, {"credit_amount_cents": 1000}, PM))
    # third reopen exceeds MAX_REOPENS=2
    validate_error(api.reopen_dispute(dispute_id, PM), ApiErrorId.ERR_MAX_REOPENS_REACHED.value)


# --------------------------------------------------------------------------- #
# state_machines / send_to_collections_before_grace_returns_not_yet_collections
# --------------------------------------------------------------------------- #
def test_send_to_collections_before_grace_rejected(api):
    """PRD §3.10: "A `DELINQUENT` statement may be escalated to `IN_COLLECTIONS`
    by a `PropertyManager`, but only when its `balance_due_cents` is still
    greater than zero and the statement has been delinquent long enough — the
    current clock date must be at or after the `due_date` plus the collections
    window of thirty days; an attempt before that threshold is rejected with
    `ERR_NOT_YET_COLLECTIONS`."

    Design: Corner/state_machines/send_to_collections_before_grace_returns_not_yet_collections
    """
    # issued 2026-06-15 -> due 2026-07-06; delinquent at 2026-07-12;
    # collections boundary due+30 = 2026-08-05; attempt at 2026-07-20 (too early)
    bundle = fx.setup_single_rubs_statement(total_cost_cents=30000, tenant_user_id="tCOL")
    fx.set_clock("2026-07-12T00:00:00Z")
    get_success_data(api.assess_late_fee(bundle["statement"]["id"], PM))
    fx.set_clock("2026-07-20T00:00:00Z")
    validate_error(
        api.send_to_collections(bundle["statement"]["id"], PM),
        ApiErrorId.ERR_NOT_YET_COLLECTIONS.value,
    )


# --------------------------------------------------------------------------- #
# state_machines / move_out_before_due_returns_move_out_not_due
# --------------------------------------------------------------------------- #
def test_move_out_before_due_rejected(api):
    """PRD §3.3: "Finalizing move-out moves a `NOTICE_GIVEN` lease to
    `MOVED_OUT`, but only once the server clock's current date is strictly past
    the recorded `move_out_date`; attempting it earlier is rejected with
    `ERR_MOVE_OUT_NOT_DUE`."

    Design: Corner/state_machines/move_out_before_due_returns_move_out_not_due
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA")
    unit = fx.create_unit(prop["id"], unit_number="MO1")
    lease = fx.create_active_lease(unit["id"], prop["id"], "tMO")
    get_success_data(api.give_notice(lease["id"], {"move_out_date": "2026-06-25T00:00:00Z"}, PM))
    fx.set_clock("2026-06-20T00:00:00Z")  # before move_out_date
    validate_error(api.move_out_lease(lease["id"], PM), ApiErrorId.ERR_MOVE_OUT_NOT_DUE.value)
    after = get_success_data(api.get_lease(lease["id"], PM))
    assert after["status"] == "NOTICE_GIVEN"


# --------------------------------------------------------------------------- #
# state_machines / reverse_payment_in_closed_cycle_returns_cycle_closed
# --------------------------------------------------------------------------- #
def test_reverse_payment_in_closed_cycle_rejected(api):
    """PRD §3.9: "A `PropertyManager` may reverse a posted payment, but only
    while the parent billing cycle is not `CLOSED`; a reversal against a closed
    cycle is rejected with `ERR_CYCLE_CLOSED`."

    Design: Corner/state_machines/reverse_payment_in_closed_cycle_returns_cycle_closed
    """
    bundle = fx.setup_statement_with_payment(amount_cents=6000, total_cost_cents=7059, tenant_user_id="tCC")
    # statement fully paid; close the cycle
    get_success_data(api.close_cycle(bundle["cycle"]["id"], PM))
    validate_error(api.reverse_payment(bundle["payment"]["id"], PM), ApiErrorId.ERR_CYCLE_CLOSED.value)
    pay_after = get_success_data(api.get_payment(bundle["payment"]["id"], PM))
    assert pay_after["status"] == "POSTED"


# --------------------------------------------------------------------------- #
# state_machines / close_cycle_recomputes_property_integrity_status_side_effect
# --------------------------------------------------------------------------- #
def test_close_cycle_recomputes_integrity_status_ok(api):
    """PRD §3.6: "On close, the system recomputes the allocation invariant for
    the cycle and updates the property's `integrity_status` accordingly, as
    described in §2.8."
    PRD §2.8: "sets the property's `integrity_status` to `NEEDS_REVIEW` if any
    closed cycle's invariant fails to recompute, leaving it `OK` otherwise."

    Design: Corner/state_machines/close_cycle_recomputes_property_integrity_status_side_effect
    """
    bundle = fx.setup_single_rubs_statement(total_cost_cents=30000, tenant_user_id="tINT")
    data = validate_success(api.close_cycle(bundle["cycle"]["id"], PM))
    assert data["status"] == "CLOSED"
    prop_after = get_success_data(api.get_property(bundle["property"]["id"], PM))
    assert prop_after["integrity_status"] == "OK"


# --------------------------------------------------------------------------- #
# validations / give_notice_move_out_before_move_in_returns_invalid_move_out_date
# --------------------------------------------------------------------------- #
def test_give_notice_move_out_before_move_in_rejected(api):
    """PRD §3.3: "Giving notice moves an `ACTIVE` lease to `NOTICE_GIVEN`. The
    request supplies the intended `move_out_date`, which must be on or after the
    `move_in_date`; an earlier date is rejected with `ERR_INVALID_MOVE_OUT_DATE`."

    Design: Corner/validations/give_notice_move_out_before_move_in_returns_invalid_move_out_date
    """
    fx.set_clock("2026-06-15T00:00:00Z")
    prop = fx.create_property(state_code="CA")
    unit = fx.create_unit(prop["id"], unit_number="IVD1")
    lease = fx.create_active_lease(unit["id"], prop["id"], "tIVD", move_in_date="2026-06-10T00:00:00Z")
    validate_error(
        api.give_notice(lease["id"], {"move_out_date": "2026-06-05T00:00:00Z"}, PM),
        ApiErrorId.ERR_INVALID_MOVE_OUT_DATE.value,
    )
    after = get_success_data(api.get_lease(lease["id"], PM))
    assert after["status"] == "ACTIVE"

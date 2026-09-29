"""Lifecycles that loop rather than march, and the writes that ripple outward.

The programme's state machines are deliberately non-linear. A vehicle carries two
independent axes that touch at exactly two declared points; an inspection cycles
between recording and reconditioning as many times as the repairs demand; a live
certification leaves and re-enters `ACTIVE` through the audit, or branches out of
the pipeline entirely when it is rejected. And the writes that move those
machines rarely stop at one row: a wholesale disposition reaches four hops down
to a re-inspection nobody named in the request, and a second audit failure
reaches five, all the way to the dealer's pending submissions and live
advertisements.
"""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    active_certification,
    activate_many,
    adjudication_payload,
    approve_certification,
    assert_dealer_ledger_conservation,
    assert_instant_equals,
    audit_samples_of,
    complete_reconditioning,
    create_inspection_payload,
    create_listing,
    create_vehicle,
    draw_audit_run,
    file_complaint,
    history_event_payload,
    ids_of,
    listings_of,
    open_inspection_for,
    read_certification,
    read_complaint,
    read_dealer,
    read_inspection,
    read_vehicle,
    reconditioning_item_for,
    reconditioning_items,
    record_finding,
    record_history_event,
    record_results,
    reject_certification,
    result_row,
    set_clock,
    submit_inspection,
    submitted_certification,
    syndicated_listing,
    validate_error,
    validate_success,
)

# The fee every default car earns at the epoch clock with the seeded tunables.
DEFAULT_FEE_CENTS = 120400


def _attempt(api, program, walk, rows):
    """Record one attempt and close it, returning the refreshed inspection."""
    record_results(api, walk.inspection_id, program.technician_headers, rows)
    walk.inspection = submit_inspection(api, walk.inspection_id, program.dealer_headers)
    return walk.inspection


def _technician_row(api, program, technician_id):
    roster = validate_success(api.list_technicians(program.dealer_id, ADMIN))
    matches = [row for row in roster if row["id"] == technician_id]
    assert matches, "a dealer's roster must expose the technician it employs"
    return matches[0]


# ───────────────── the two independent axes of one vehicle ──────────────────

def test_retail_sale_leaves_a_pending_certification_alone_but_blocks_approval(
    api, program
):
    """A sale moves only the commercial axis, and that is the one gate it closes.

    PRD §2.7: "`inventory_state` is the **commercial standing** axis, with values
    `IN_INVENTORY`, `RETAIL_SOLD`, and `WHOLESALED`; it is driven exclusively by
    recorded vehicle history events and never by certification activity."
    PRD §3.2: "as hop 2, any certification of that vehicle in `ACTIVE` or
    `UNDER_AUDIT` moves to `DECERTIFIED` with a decertification reason of
    `RETAIL_SOLD`"
    PRD §3.7: "The vehicle's `inventory_state` must be `IN_INVENTORY`: approving a
    car already `RETAIL_SOLD` or `WHOLESALED` is rejected with
    `ERR_VEHICLE_NOT_IN_INVENTORY`, and this is the single point at which the
    commercial axis blocks the programme axis."
    PRD §3.2: "A `RETURNED_TO_INVENTORY` event is accepted from either
    `RETAIL_SOLD` or `WHOLESALED` and moves `inventory_state` back to
    `IN_INVENTORY`."

    Design: Difficulty/non_linear_state_machine/vehicle_parallel_cpo_and_inventory_dimensions
    """
    walk = submitted_certification(api, program)
    record_history_event(api, walk.vehicle_id, "RETAIL_SOLD")

    sold = read_vehicle(api, walk.vehicle_id)
    assert sold["inventory_state"] == "RETAIL_SOLD"
    # Hop 2 only reaches a live certification, and this one is merely submitted.
    assert sold["cpo_state"] == "CERTIFICATION_PENDING"
    assert sold["active_certification_count"] == 1
    assert read_certification(api, walk.certification_id)["status"] == "SUBMITTED"

    refused = api.adjudicate_certification(
        walk.certification_id, adjudication_payload("APPROVE"), ADMIN
    )
    validate_error(refused, ApiErrorId.ERR_VEHICLE_NOT_IN_INVENTORY)
    assert read_certification(api, walk.certification_id)["status"] == "SUBMITTED"

    record_history_event(api, walk.vehicle_id, "RETURNED_TO_INVENTORY")
    returned = read_vehicle(api, walk.vehicle_id)
    assert returned["inventory_state"] == "IN_INVENTORY"
    assert returned["cpo_state"] == "CERTIFICATION_PENDING"

    certification = approve_certification(api, walk.certification_id)
    assert certification["status"] == "ACTIVE"
    assert certification["fee_charged_cents"] == DEFAULT_FEE_CENTS
    assert certification["warranty_end_miles"] == 74000
    certified = read_vehicle(api, walk.vehicle_id)
    assert certified["cpo_state"] == "CERTIFIED"
    assert certified["certified_certification_id"] == walk.certification_id


def test_commercial_axis_moves_freely_on_a_car_that_was_never_certified(api, program):
    """A never-certified car can be sold and returned, and only then inspected.

    PRD §2.7: "A vehicle may be `RETAIL_SOLD` while its `cpo_state` is still
    `NOT_CERTIFIED`, and its `cpo_state` may be `CERTIFIED` while an unrelated
    complaint sits open against it."
    PRD §2.7: "Entering `CERTIFICATION_PENDING` requires `inventory_state` to be
    `IN_INVENTORY`, and approving a certification requires the same thing — the
    programme only certifies cars the dealer still holds."
    PRD §3.2: "An `event_type` that is not a declared transition out of the
    vehicle's current `inventory_state` — a retail sale on a car already
    `RETAIL_SOLD`, or a return to inventory on a car still `IN_INVENTORY` — is
    rejected with `ERR_VEHICLE_HISTORY_EVENT_INVALID`."
    PRD §3.3: "`cpo_state` goes `NOT_CERTIFIED → CERTIFICATION_PENDING`"

    Design: Difficulty/non_linear_state_machine/vehicle_parallel_cpo_and_inventory_dimensions
    """
    vehicle = create_vehicle(api)
    premature = api.create_history_event(
        vehicle["id"], history_event_payload("RETURNED_TO_INVENTORY"), ADMIN
    )
    validate_error(premature, ApiErrorId.ERR_VEHICLE_HISTORY_EVENT_INVALID)

    record_history_event(api, vehicle["id"], "RETAIL_SOLD")
    sold = read_vehicle(api, vehicle["id"])
    assert sold["inventory_state"] == "RETAIL_SOLD"
    assert sold["cpo_state"] == "NOT_CERTIFIED"
    assert sold["last_history_event_type"] == "RETAIL_SOLD"
    assert_instant_equals(
        sold["last_history_event_at"], "2026-08-01T00:00:00Z", "last_history_event_at"
    )

    blocked = api.create_inspection(
        create_inspection_payload(
            vehicle["id"],
            program.technician_id,
            program.template_id,
            started_at=program.next_start(),
        ),
        program.dealer_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_VEHICLE_NOT_IN_INVENTORY)
    assert read_vehicle(api, vehicle["id"])["cpo_state"] == "NOT_CERTIFIED"

    repeat_sale = api.create_history_event(
        vehicle["id"], history_event_payload("RETAIL_SOLD"), ADMIN
    )
    validate_error(repeat_sale, ApiErrorId.ERR_VEHICLE_HISTORY_EVENT_INVALID)

    record_history_event(api, vehicle["id"], "RETURNED_TO_INVENTORY")
    walk = open_inspection_for(api, program, vehicle=read_vehicle(api, vehicle["id"]))
    assert walk.inspection["status"] == "DRAFT"
    reopened = read_vehicle(api, walk.vehicle_id)
    assert reopened["inventory_state"] == "IN_INVENTORY"
    assert reopened["cpo_state"] == "CERTIFICATION_PENDING"


# ───────────── the recording / reconditioning cycle of an inspection ─────────

def test_three_attempts_generate_one_repair_row_per_failed_point(api, program):
    """Failing the same points twice yields two repairs, and the third attempt passes.

    PRD §3.5: "Generation is **idempotent on `item_code` across attempts**: a
    point that already has a reconditioning item for this inspection does not
    receive a second one, so a car that fails the same brake point on two
    successive attempts carries one repair row, not two."
    PRD §3.4: "it increments the inspection's `attempt_count` by exactly 1 and
    then writes one result row per supplied entry, each stamped with an
    `attempt_index` equal to the *new* `attempt_count`"
    PRD §3.5: "When the attempt is clean and every repair is closed, the
    inspection reaches `PASSED`: `submitted_at` is set to the logical clock,
    `total_recon_cost_cents` and `total_reimbursable_cents` are recomputed one
    final time, the assigned technician's `completed_inspection_count` increments
    by 1"

    Design: Difficulty/non_linear_state_machine/inspection_reconditioning_cycle_three_attempts
    """
    walk = open_inspection_for(api, program)

    first = _attempt(
        api,
        program,
        walk,
        [
            result_row("P1", "PASS"),
            result_row("S1", "FAIL"),
            result_row("B1", "FAIL", measured_value=2.0),
        ],
    )
    assert first["status"] == "RECONDITIONING_REQUIRED"
    assert first["attempt_count"] == 1
    assert first["failed_critical_count"] == 1
    assert first["failed_recon_count"] == 2
    assert sorted(row["item_code"] for row in reconditioning_items(api, walk.inspection_id)) == [
        "B1",
        "S1",
    ]

    second = _attempt(
        api,
        program,
        walk,
        [
            result_row("P1", "PASS"),
            result_row("S1", "FAIL"),
            result_row("B1", "PASS", measured_value=8.0),
        ],
    )
    assert second["status"] == "RECONDITIONING_REQUIRED"
    assert second["attempt_count"] == 2
    assert second["failed_critical_count"] == 1
    assert second["failed_recon_count"] == 1
    repairs = reconditioning_items(api, walk.inspection_id)
    assert len(repairs) == 2, "the repeated S1 failure must not mint a second repair"

    safety = complete_reconditioning(
        api,
        reconditioning_item_for(api, walk.inspection_id, "S1")["id"],
        150000,
        program.other_technician_headers,
    )
    assert safety["reimbursable_cents"] == 90000
    brakes = complete_reconditioning(
        api,
        reconditioning_item_for(api, walk.inspection_id, "B1")["id"],
        50000,
        program.other_technician_headers,
    )
    assert brakes["reimbursable_cents"] == 30000

    third = _attempt(
        api,
        program,
        walk,
        [
            result_row("P1", "PASS"),
            result_row("S1", "PASS"),
            result_row("B1", "PASS", measured_value=8.0),
        ],
    )
    assert third["status"] == "PASSED"
    assert third["attempt_count"] == 3
    assert third["failed_critical_count"] == 0
    assert third["failed_recon_count"] == 0
    assert third["total_recon_cost_cents"] == 200000
    assert third["total_reimbursable_cents"] == 120000
    assert_instant_equals(
        third["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at"
    )

    # Every attempt's evidence survives: three attempts of three points each.
    results = validate_success(
        api.list_results(walk.inspection_id, ADMIN, params={"limit": 100})
    )
    assert len(results) == 9
    assert sorted(row["attempt_index"] for row in results) == [1, 1, 1, 2, 2, 2, 3, 3, 3]

    assert _technician_row(api, program, program.technician_id)[
        "completed_inspection_count"
    ] == 1
    assert _technician_row(api, program, program.other_technician_id)[
        "completed_inspection_count"
    ] == 0
    assert read_vehicle(api, walk.vehicle_id)["cpo_state"] == "CERTIFICATION_PENDING"


def test_recording_after_repairs_reopens_the_cycle_without_checking_them(api, program):
    """The repair state is checked at closing time, never at recording time.

    PRD §3.4: "a recording after repairs moves it `RECONDITIONING_REQUIRED →
    IN_PROGRESS`, which closes the inspection's cycle — that loop may repeat any
    number of times"
    PRD §3.4: "On this third path the state of the outstanding repair rows is
    deliberately **not** checked; repairs are checked at closing time, not at
    recording time, and the repair rows generated by the previous close survive
    the new recording untouched."
    PRD §3.5: "A clean attempt still cannot pass while a repair is outstanding.
    If any reconditioning item of the inspection remains `REQUIRED`, closing is
    rejected with `ERR_RECONDITIONING_INCOMPLETE`."

    Design: Difficulty/non_linear_state_machine/inspection_reconditioning_cycle_three_attempts
    """
    walk = open_inspection_for(api, program)
    first = _attempt(
        api,
        program,
        walk,
        [
            result_row("P1", "PASS"),
            result_row("S1", "FAIL"),
            result_row("B1", "PASS", measured_value=8.0),
        ],
    )
    assert first["status"] == "RECONDITIONING_REQUIRED"
    repair = reconditioning_item_for(api, walk.inspection_id, "S1")
    assert repair["status"] == "REQUIRED"

    reopened = record_results(
        api,
        walk.inspection_id,
        program.technician_headers,
        [
            result_row("P1", "PASS"),
            result_row("S1", "PASS"),
            result_row("B1", "PASS", measured_value=8.0),
        ],
    )
    assert reopened["status"] == "IN_PROGRESS"
    assert reopened["attempt_count"] == 2
    assert reopened["failed_recon_count"] == 0
    surviving = reconditioning_item_for(api, walk.inspection_id, "S1")
    assert surviving["id"] == repair["id"]
    assert surviving["status"] == "REQUIRED"

    refused = api.submit_inspection(walk.inspection_id, program.dealer_headers)
    validate_error(refused, ApiErrorId.ERR_RECONDITIONING_INCOMPLETE)
    assert read_inspection(api, walk.inspection_id)["status"] == "IN_PROGRESS"

    complete_reconditioning(
        api, repair["id"], 100000, program.other_technician_headers
    )
    closed = submit_inspection(api, walk.inspection_id, program.dealer_headers)
    assert closed["status"] == "PASSED"
    assert closed["attempt_count"] == 2
    assert closed["total_recon_cost_cents"] == 100000
    assert closed["total_reimbursable_cents"] == 60000


# ─────────── a certification leaving and re-entering the live state ──────────

def test_a_cleared_audit_returns_the_certification_untouched_to_active(api, program):
    """`UNDER_AUDIT → ACTIVE` re-prices and re-dates nothing at all.

    PRD §3.10: "The certification itself moves `ACTIVE → UNDER_AUDIT`, its
    `audit_sampled` flag is set to true, and its `version` increments by 1.
    Because that flag is never reset, a certification is sampled at most once in
    its life."
    PRD §3.10: "The certification returns `UNDER_AUDIT → ACTIVE` with its
    `activated_at`, its fee fields, and its coverage fields **untouched** —
    clearing an audit does not re-price or re-date anything."
    PRD §3.10: "The eligible pool is every certification that is `ACTIVE`, whose
    `audit_sampled` flag is still false"
    PRD §3.10: "An empty pool is not an error: a pool size of zero yields a
    `selected_count` of 0, creates no audit samples at all, and still returns a
    successful 201 Created response."

    Design: Difficulty/non_linear_state_machine/certification_audit_cycle_and_branch
    """
    walk = active_certification(api, program)
    approved = walk.certification

    first_run = draw_audit_run(api)
    assert first_run["audit_run_id"] == "AR-1"
    assert first_run["pool_size"] == 1
    assert first_run["selected_count"] == 1
    assert first_run["selected_certification_ids"] == [walk.certification_id]

    under_audit = read_certification(api, walk.certification_id)
    assert under_audit["status"] == "UNDER_AUDIT"
    assert under_audit["audit_sampled"] is True
    assert under_audit["audit_sample_count"] == 1

    samples = audit_samples_of(api, walk.certification_id)
    assert len(samples) == 1
    assert samples[0]["status"] == "SELECTED"
    assert samples[0]["audit_run_id"] == "AR-1"
    assert samples[0]["selection_rank"] == 1
    assert samples[0]["finding_code"] is None
    assert samples[0]["reviewer_user_id"] is None

    sample = record_finding(api, samples[0]["id"], "PASS")
    assert sample["status"] == "PASSED"
    assert sample["finding_code"] == "NONE"
    assert sample["reviewer_user_id"] == "auditor-1"
    assert_instant_equals(sample["reviewed_at"], "2026-08-01T00:00:00Z", "reviewed_at")

    cleared = read_certification(api, walk.certification_id)
    assert cleared["status"] == "ACTIVE"
    assert cleared["activated_at"] == approved["activated_at"]
    assert cleared["fee_charged_cents"] == approved["fee_charged_cents"]
    assert cleared["fee_credited_cents"] == 0
    assert cleared["warranty_start_date"] == approved["warranty_start_date"]
    assert cleared["warranty_end_date"] == approved["warranty_end_date"]
    assert cleared["warranty_end_miles"] == approved["warranty_end_miles"]
    assert cleared["retention_expires_at"] == approved["retention_expires_at"]
    assert cleared["audit_sampled"] is True

    # The latch keeps the cleared certification out of every later pool.
    second_run = draw_audit_run(api)
    assert second_run["audit_run_id"] == "AR-2"
    assert second_run["pool_size"] == 0
    assert second_run["selected_count"] == 0
    assert second_run["selected_certification_ids"] == []

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["audit_sample_count"] == 1
    assert dealer["audit_fail_count"] == 0
    assert dealer["audit_fail_rate"] == 0.00
    assert dealer["risk_score"] == 0
    assert dealer["fee_billed_cents_total"] == DEFAULT_FEE_CENTS


def test_rejection_is_the_branch_that_never_reaches_the_audit(api, program):
    """A submitted certification is outside the pool, and rejection ends it.

    PRD §3.10: "Certifications that are `SUBMITTED`, `UNDER_AUDIT`, `REJECTED`,
    `SUPERSEDED`, or `DECERTIFIED` are excluded, as are those belonging to a
    `SUSPENDED` dealer."
    PRD §3.7: "The certification moves `SUBMITTED → REJECTED` with its
    `rejection_reason` set to the supplied value or defaulting to
    `ADMIN_DECISION`. No fee is billed, `activated_at` stays null, and no
    coverage is computed."
    PRD §3.7: "The vehicle's `active_certification_count` is recomputed and falls
    to 0, its `certified_certification_id` stays null, and its `cpo_state` moves
    `CERTIFICATION_PENDING → NOT_CERTIFIED`."
    PRD §3.7: "`REJECTED` is terminal."

    Design: Difficulty/non_linear_state_machine/certification_audit_cycle_and_branch
    """
    live = active_certification(api, program)
    pending = submitted_certification(api, program)

    run = draw_audit_run(api)
    assert run["pool_size"] == 1
    assert run["selected_certification_ids"] == [live.certification_id]
    assert audit_samples_of(api, pending.certification_id) == []
    assert read_certification(api, pending.certification_id)["audit_sampled"] is False

    rejected = reject_certification(api, pending.certification_id)
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "ADMIN_DECISION"
    assert rejected["activated_at"] is None
    assert rejected["fee_charged_cents"] == 0
    assert rejected["program_config_version"] is None
    assert rejected["warranty_start_date"] is None

    vehicle = read_vehicle(api, pending.vehicle_id)
    assert vehicle["cpo_state"] == "NOT_CERTIFIED"
    assert vehicle["active_certification_count"] == 0
    assert vehicle["certified_certification_id"] is None

    terminal = api.adjudicate_certification(
        pending.certification_id, adjudication_payload("APPROVE"), ADMIN
    )
    validate_error(terminal, ApiErrorId.ERR_CERTIFICATION_NOT_SUBMITTED)

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_submitted_count"] == 2
    assert dealer["lifetime_activated_count"] == 1
    assert dealer["active_certification_count"] == 1
    assert dealer["fee_billed_cents_total"] == DEFAULT_FEE_CENTS


# ──────────────── the four-hop cascade of a disposition event ────────────────

def test_wholesale_reaches_four_hops_down_to_an_in_flight_reinspection(api, program):
    """One history event decertifies, withdraws, dismisses, and voids in turn.

    PRD §3.2: "hop 2 decertifies any `ACTIVE` or `UNDER_AUDIT` certification of
    that vehicle with a decertification reason of `WHOLESALED` and
    `fee_credited_cents` again 0; hop 3, caused by that decertification, moves
    every listing of that certification in `DRAFT` or `SYNDICATED` to `WITHDRAWN`
    with a withdrawal reason of `CERTIFICATION_DECERTIFIED` and a takedown
    deadline set, moves every complaint of that certification in `OPEN` or
    `REINSPECTION_ORDERED` to `DISMISSED` with its resolution instant set to the
    logical clock, and moves the vehicle's `cpo_state` `CERTIFIED → DECERTIFIED`;
    hop 4, caused by hop 3's complaint dismissal, moves every inspection linked
    to a dismissed complaint that is still `DRAFT`, `IN_PROGRESS`, or
    `RECONDITIONING_REQUIRED` to `VOIDED` with a `failure_reason` of
    `COMPLAINT_DISMISSED`."
    PRD §3.8: "a `removal_due_at` equal to `withdrawn_at` plus the programme's
    takedown window — 48 hours (two days) by default"
    PRD §3.10: "every other reason leaves `fee_credited_cents` at 0, so a dealer
    that sells the car keeps paying for the badge it used"

    Design: Difficulty/transitive_cascade/wholesale_event_four_hop_cascade
    """
    walk = active_certification(api, program)
    listing = syndicated_listing(api, walk)
    complaint = file_complaint(api, walk.certification_id)
    assert_instant_equals(
        complaint["reinspection_deadline_at"],
        "2026-08-06T00:00:00Z",
        "reinspection_deadline_at",
    )
    reinspection = open_inspection_for(
        api,
        program,
        vehicle=walk.vehicle,
        technician_id=program.other_technician_id,
        complaint_id=complaint["id"],
    )
    assert reinspection.inspection["purpose"] == "RE_INSPECTION"
    assert read_complaint(api, complaint["id"])["status"] == "REINSPECTION_ORDERED"

    set_clock(api, "2026-09-01T00:00:00Z")
    record_history_event(api, walk.vehicle_id, "WHOLESALED")

    vehicle = read_vehicle(api, walk.vehicle_id)
    assert vehicle["inventory_state"] == "WHOLESALED"
    assert vehicle["cpo_state"] == "DECERTIFIED"
    assert vehicle["certified_certification_id"] is None
    assert vehicle["active_certification_count"] == 0
    assert_instant_equals(
        vehicle["decertified_at"], "2026-09-01T00:00:00Z", "decertified_at"
    )

    certification = read_certification(api, walk.certification_id)
    assert certification["status"] == "DECERTIFIED"
    assert certification["decertification_reason"] == "WHOLESALED"
    assert certification["fee_credited_cents"] == 0
    assert_instant_equals(
        certification["decertified_at"], "2026-09-01T00:00:00Z", "decertified_at"
    )
    assert_instant_equals(
        certification["activated_at"], "2026-08-01T00:00:00Z", "activated_at"
    )

    withdrawn = [
        row for row in listings_of(api, walk.certification_id) if row["id"] == listing["id"]
    ][0]
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawal_reason"] == "CERTIFICATION_DECERTIFIED"
    assert_instant_equals(
        withdrawn["withdrawn_at"], "2026-09-01T00:00:00Z", "withdrawn_at"
    )
    assert_instant_equals(
        withdrawn["removal_due_at"], "2026-09-03T00:00:00Z", "removal_due_at"
    )

    dismissed = read_complaint(api, complaint["id"])
    assert dismissed["status"] == "DISMISSED"
    assert_instant_equals(dismissed["resolved_at"], "2026-09-01T00:00:00Z", "resolved_at")

    voided = read_inspection(api, reinspection.inspection_id)
    assert voided["status"] == "VOIDED"
    assert voided["failure_reason"] == "COMPLAINT_DISMISSED"
    # The inspection that backed the certification keeps its verdict.
    assert read_inspection(api, walk.inspection_id)["status"] == "PASSED"

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["fee_billed_cents_total"] == DEFAULT_FEE_CENTS
    assert dealer["fee_credited_cents_total"] == 0
    assert dealer["fee_balance_cents"] == DEFAULT_FEE_CENTS
    assert_dealer_ledger_conservation(dealer)


def test_retail_sale_drives_the_same_chain_and_bills_a_draft_takedown(api, program):
    """The only difference between the two dispositions is the recorded reason.

    PRD §3.2: "The retail-sale path drives the same hop 3 and hop 4 chain; the
    only difference between the two dispositions is the recorded decertification
    reason."
    PRD §3.8: "Both the draft and the syndicated path behave identically,
    including writing `removal_due_at`: the deadline is recorded even when
    nothing was ever published, so the takedown obligation is auditable either
    way."
    PRD §3.11: "Whenever the complained-about certification is decertified for
    any reason **other than** `COMPLAINT_REINSPECTION_FAIL`, every complaint of
    that certification in `OPEN` or `REINSPECTION_ORDERED` moves to `DISMISSED`
    with `resolved_at` set to the logical clock and its `version` incremented by
    1."

    Design: Difficulty/transitive_cascade/wholesale_event_four_hop_cascade
    """
    walk = active_certification(api, program)
    draft = create_listing(api, program.dealer_headers, walk.certification_id)
    assert draft["status"] == "DRAFT"
    assert draft["syndicated_at"] is None
    complaint = file_complaint(api, walk.certification_id)
    assert complaint["status"] == "OPEN"

    record_history_event(api, walk.vehicle_id, "RETAIL_SOLD")

    certification = read_certification(api, walk.certification_id)
    assert certification["status"] == "DECERTIFIED"
    assert certification["decertification_reason"] == "RETAIL_SOLD"
    assert certification["fee_credited_cents"] == 0

    vehicle = read_vehicle(api, walk.vehicle_id)
    assert vehicle["inventory_state"] == "RETAIL_SOLD"
    assert vehicle["cpo_state"] == "DECERTIFIED"

    withdrawn = listings_of(api, walk.certification_id)[0]
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawal_reason"] == "CERTIFICATION_DECERTIFIED"
    assert withdrawn["syndicated_at"] is None
    assert_instant_equals(
        withdrawn["removal_due_at"], "2026-08-03T00:00:00Z", "removal_due_at"
    )

    assert read_complaint(api, complaint["id"])["status"] == "DISMISSED"

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["fee_credited_cents_total"] == 0
    assert dealer["fee_balance_cents"] == DEFAULT_FEE_CENTS


# ─────────────── the five-hop cascade of a second audit failure ──────────────

def _fail_next_sample(api, expected_certification_id, finding_code):
    """Draw a run, assert it picked the expected certification, and fail it."""
    run = draw_audit_run(api)
    assert run["selected_certification_ids"] == [expected_certification_id]
    samples = audit_samples_of(api, expected_certification_id)
    return run, record_finding(api, samples[-1]["id"], "FAIL", finding_code)


def test_second_audit_failure_suspends_the_dealer_and_clears_its_pipeline(api, program):
    """Two failures cross the threshold and the cascade runs all five hops.

    PRD §3.10: "Hop 4, caused by hop 1's counter crossing its threshold, applies
    only when the dealer's `audit_fail_count` has reached the programme's
    audit-failure suspension count — two failures by default: the dealer's
    `privilege_status` moves to `SUSPENDED` with `privilege_reason`
    `AUDIT_FAILURE_SUSPENSION`. Hop 5, caused by hop 4, moves every certification
    of that dealer still in `SUBMITTED` to `REJECTED` with `rejection_reason`
    `DEALER_SUSPENDED`, each releasing its vehicle's certification slot, and
    moves every listing of that dealer in `SYNDICATED` to `WITHDRAWN` with
    `withdrawal_reason` `DEALER_SUSPENDED`."
    PRD §3.10: "sets its `fee_credited_cents` equal to its `fee_charged_cents`,
    because the programme's own audit invalidated the certification and the
    dealer gets its money back"
    PRD §3.10: "The pool is ranked by three keys in order: the dealer's
    `risk_score` descending, then the certification's `activated_at` ascending,
    then the certification's `created_at` ascending as the final tie-break"

    Design: Difficulty/transitive_cascade/audit_failure_five_hop_dealer_suspension_cascade
    """
    first, second, third = activate_many(api, program, 3)
    first_listing = syndicated_listing(api, first)
    third_listing = syndicated_listing(api, third)
    pending = submitted_certification(api, program)

    run_one, _ = _fail_next_sample(api, first.certification_id, "DOCUMENTATION_MISSING")
    assert run_one["pool_size"] == 3
    assert run_one["selected_count"] == 1

    decertified = read_certification(api, first.certification_id)
    assert decertified["status"] == "DECERTIFIED"
    assert decertified["decertification_reason"] == "POST_AUDIT_FAIL"
    assert decertified["fee_credited_cents"] == DEFAULT_FEE_CENTS
    assert listings_of(api, first.certification_id)[0]["status"] == "WITHDRAWN"

    after_one = read_dealer(api, program.dealer_id)
    assert after_one["audit_fail_count"] == 1
    assert after_one["privilege_status"] == "ACTIVE", "one failure is below the threshold"
    assert read_certification(api, pending.certification_id)["status"] == "SUBMITTED"

    run_two, _ = _fail_next_sample(api, second.certification_id, "ELIGIBILITY_VIOLATION")
    assert run_two["pool_size"] == 2
    assert run_two["selected_count"] == 1
    assert read_certification(api, second.certification_id)["fee_credited_cents"] == (
        DEFAULT_FEE_CENTS
    )

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["audit_sample_count"] == 2
    assert dealer["audit_fail_count"] == 2
    assert dealer["audit_fail_rate"] == 1.00
    assert dealer["risk_score"] == 40
    assert dealer["privilege_status"] == "SUSPENDED"
    assert dealer["privilege_reason"] == "AUDIT_FAILURE_SUSPENSION"

    # Hop 5 reaches the still-pending submission and the surviving listing.
    rejected = read_certification(api, pending.certification_id)
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "DEALER_SUSPENDED"
    pending_vehicle = read_vehicle(api, pending.vehicle_id)
    assert pending_vehicle["cpo_state"] == "NOT_CERTIFIED"
    assert pending_vehicle["active_certification_count"] == 0

    survivor = [
        row
        for row in listings_of(api, third.certification_id)
        if row["id"] == third_listing["id"]
    ][0]
    assert survivor["status"] == "WITHDRAWN"
    assert survivor["withdrawal_reason"] == "DEALER_SUSPENDED"
    earlier = listings_of(api, first.certification_id)[0]
    assert earlier["id"] == first_listing["id"]
    assert earlier["withdrawal_reason"] == "CERTIFICATION_DECERTIFIED"

    # The third certification was never sampled, so it survives untouched.
    assert read_certification(api, third.certification_id)["status"] == "ACTIVE"

    assert dealer["fee_billed_cents_total"] == 3 * DEFAULT_FEE_CENTS
    assert dealer["fee_credited_cents_total"] == 2 * DEFAULT_FEE_CENTS
    assert dealer["fee_balance_cents"] == DEFAULT_FEE_CENTS
    assert_dealer_ledger_conservation(dealer)


def test_a_single_audit_failure_stops_after_three_hops(api, program):
    """Below the suspension count hops 4 and 5 are skipped without failing.

    PRD §2.7: "a hop that does not apply (because no matching row exists, or
    because a threshold has not been reached) is simply skipped without failing
    the request"
    PRD §3.10: "Hop 3, caused by hop 2, moves the vehicle's `cpo_state`
    `CERTIFIED → DECERTIFIED`, sets the vehicle's `decertified_at` to the logical
    clock, clears `certified_certification_id` to null, recomputes
    `active_certification_count` to 0"
    PRD §3.10: "Hop 1 moves the sample `SELECTED → FAILED` with the supplied
    `finding_code`, `reviewed_at`, and `reviewer_user_id`, and recomputes the
    dealer's `audit_fail_count` and `audit_fail_rate`."

    Design: Difficulty/transitive_cascade/audit_failure_five_hop_dealer_suspension_cascade
    """
    first, second = activate_many(api, program, 2)
    second_listing = syndicated_listing(api, second)
    pending = submitted_certification(api, program)

    run, sample = _fail_next_sample(api, first.certification_id, "INSPECTION_INCOMPLETE")
    assert run["pool_size"] == 2
    assert sample["status"] == "FAILED"
    assert sample["finding_code"] == "INSPECTION_INCOMPLETE"
    assert sample["reviewer_user_id"] == "auditor-1"

    vehicle = read_vehicle(api, first.vehicle_id)
    assert vehicle["cpo_state"] == "DECERTIFIED"
    assert vehicle["certified_certification_id"] is None
    assert vehicle["active_certification_count"] == 0
    assert_instant_equals(
        vehicle["decertified_at"], "2026-08-01T00:00:00Z", "decertified_at"
    )
    assert vehicle["inventory_state"] == "IN_INVENTORY", "the commercial axis is untouched"

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["audit_sample_count"] == 1
    assert dealer["audit_fail_count"] == 1
    assert dealer["audit_fail_rate"] == 1.00
    assert dealer["risk_score"] == 40
    assert dealer["privilege_status"] == "ACTIVE"
    assert dealer["privilege_reason"] is None

    # Hops 4 and 5 never ran: the pending submission and the listing both stand.
    assert read_certification(api, pending.certification_id)["status"] == "SUBMITTED"
    surviving = listings_of(api, second.certification_id)
    assert ids_of(surviving) == [second_listing["id"]]
    assert surviving[0]["status"] == "SYNDICATED"
    assert read_certification(api, second.certification_id)["status"] == "ACTIVE"

    assert dealer["fee_billed_cents_total"] == 2 * DEFAULT_FEE_CENTS
    assert dealer["fee_credited_cents_total"] == DEFAULT_FEE_CENTS
    assert dealer["fee_balance_cents"] == DEFAULT_FEE_CENTS
    assert_dealer_ledger_conservation(dealer)


def test_wholesaled_vehicle_can_be_returned_and_recertified(api, program):
    """`DECERTIFIED → CERTIFICATION_PENDING → CERTIFIED` is a legal loop.

    PRD §2.7: "Neither axis has a terminal state: `DECERTIFIED` on the programme
    axis is a resting state a returned vehicle may leave, and a wholesaled
    vehicle may come back to inventory."
    PRD §3.2: "It deliberately leaves `cpo_state` alone: a returned car stays
    `DECERTIFIED` on the programme axis until a fresh inspection is opened on it.
    That is the loop that makes `DECERTIFIED → CERTIFICATION_PENDING →
    CERTIFIED` a legal path, and the vehicle's `decertified_at` is left in place
    as the historical record of the earlier withdrawal rather than being
    cleared."

    Design: Difficulty/non_linear_state_machine/vehicle_parallel_cpo_and_inventory_dimensions
    """
    walk = active_certification(api, program)
    record_history_event(api, walk.vehicle_id, "WHOLESALED")
    withdrawn = read_vehicle(api, walk.vehicle_id)
    assert withdrawn["cpo_state"] == "DECERTIFIED"
    first_decertified_at = withdrawn["decertified_at"]

    record_history_event(api, walk.vehicle_id, "RETURNED_TO_INVENTORY")
    resting = read_vehicle(api, walk.vehicle_id)
    assert resting["inventory_state"] == "IN_INVENTORY"
    assert resting["cpo_state"] == "DECERTIFIED"
    assert resting["decertified_at"] == first_decertified_at

    reopened = open_inspection_for(api, program, vehicle=resting)
    assert read_vehicle(api, walk.vehicle_id)["cpo_state"] == "CERTIFICATION_PENDING"
    assert (
        read_vehicle(api, walk.vehicle_id)["decertified_at"] == first_decertified_at
    ), "the earlier withdrawal stays on the record"
    assert reopened.inspection["status"] == "DRAFT"

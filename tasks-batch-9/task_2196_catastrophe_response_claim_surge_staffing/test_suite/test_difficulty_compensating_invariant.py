"""Queue A — rule_id: compensating_invariant.

Do-then-undo round trips on the three conserved quantities: incurred dollars
across advance issue-then-void, physical hotel rooms across confirm-then-cancel,
and vendor concurrency slots across accept-then-complete.
"""
from test_helpers import validate_success
from test_helpers.assertions import assert_money_equals
from test_helpers.test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_deployment_coordinator_headers,
    make_vendor_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")


# ---------------------------------------------------------------------------
# Instance 1 — incurred_dollars_conserved_across_advance_issue_then_void
# ---------------------------------------------------------------------------
def _issued_advance_of_13500_on_a_standard_claim(api):
    """CAT-2026-901 DECLARED; one STANDARD claim reserved at 33750.00; one ISSUED
    advance for the full 13500.00 cap. Returns the event, claim, advance and the
    incurred_total observed before the advance existed."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-901",
                "peril_type": "HURRICANE",
                "jurisdiction_state": "FL",
                "event_start_utc": "2026-07-30T00:00:00.000Z",
                "exposure_count": 1400,
                "avg_insured_value": 240000,
                "expected_severity_index": 0.2000,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    claim = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-9101",
                "loss_state": "FL",
                "loss_date_utc": "2026-07-30T00:00:00.000Z",
                "reported_loss_amount": 60000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 200000,
                        "deductible_amount": 5000,
                        "estimated_damage_amount": 80000,
                    }
                ],
                "event_id": event["id"],
                "access_status": "ACCESSIBLE",
            },
            CE,
        ),
        201,
    )
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    incurred_before = validate_success(api.get_event(event["id"], CM))["incurred_total"]
    advance = validate_success(
        api.create_advance_payment(
            {
                "claim_id": claim["id"],
                "requested_amount": 13500,
                "basis": "STRUCTURE_PARTIAL",
            },
            CE,
        ),
        201,
    )
    return event, triaged, advance, incurred_before


def test_issue_then_void_returns_every_dollar_figure_to_its_pre_issuance_value(api):
    """PRD §2.10: "The compensating-action guarantee that follows is exact, not
    approximate: issuing an advance payment on a claim and then voiding that same advance
    leaves the event's `incurred_total`, the claim's `case_reserve` and the claim's
    `paid_amount` each exactly equal to their pre-issuance values."
    PRD §3.8: "The claim's `advance_paid_total`, `paid_amount` and `case_reserve` and the
    event's `paid_total` and `case_reserve_total` are all recomputed — but the event's
    `incurred_total` is **unchanged**, because the two movements on the entry are equal
    and opposite."
    PRD §3.8: "Link two-b, caused by link two, moves the claim `ADVANCE_ISSUED → NONE`
    on the payment axis when `advance_paid_total` returns to exactly 0.00 — and
    `advance_issuing_examiner_user_id` is **retained**, because a void does not erase the
    fact that this user once released money on the file."

    Design: Difficulty/compensating_invariant/incurred_dollars_conserved_across_advance_issue_then_void
    """
    event, claim, advance, incurred_before = _issued_advance_of_13500_on_a_standard_claim(api)
    # 100 * (60000/200000) * 1.15 HURRICANE + 20 * 0.2000 = 38.50 -> STANDARD.
    assert_money_equals(claim["severity_score"], 38.50, "severity_score")
    assert claim["triage_tier"] == "STANDARD"
    assert_money_equals(incurred_before, 33750.00, "incurred_total before issuance")
    mid_claim = validate_success(api.get_claim(claim["id"], CE))
    assert mid_claim["payment_status"] == "ADVANCE_ISSUED"
    assert_money_equals(mid_claim["case_reserve"], 20250.00, "case_reserve mid")
    assert_money_equals(mid_claim["paid_amount"], 13500.00, "paid_amount mid")
    assert_money_equals(
        validate_success(api.get_event(event["id"], CM))["incurred_total"],
        33750.00,
        "incurred_total mid",
    )

    voided = validate_success(
        api.void_advance_payment(
            advance["id"],
            {"void_reason": "Coverage question raised by SIU; advance withdrawn pending review"},
            CE,
        )
    )

    assert voided["status"] == "VOIDED"
    assert_money_equals(voided["amount"], 13500.00, "amount")
    assert voided["voided_at_utc"] == "2026-08-01T00:00:00.000Z"
    after_claim = validate_success(api.get_claim(claim["id"], CE))
    assert after_claim["payment_status"] == "NONE"
    assert_money_equals(after_claim["case_reserve"], 33750.00, "case_reserve after")
    assert_money_equals(after_claim["paid_amount"], 0.00, "paid_amount after")
    assert_money_equals(after_claim["advance_paid_total"], 0.00, "advance_paid_total after")
    assert_money_equals(after_claim["advance_cap"], 13500.00, "advance_cap after")
    after_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(after_event["incurred_total"], incurred_before, "incurred_total after")
    assert_money_equals(after_event["case_reserve_total"], 33750.00, "case_reserve_total after")
    assert_money_equals(after_event["paid_total"], 0.00, "paid_total after")


def test_the_round_trip_only_ever_appends_to_the_ledger(api):
    """PRD §2.10: "At any instant, an event's `incurred_total` equals the sum, over every
    reserve entry belonging to that event, of the entry's change to case reserve plus its
    change to paid loss, rounded to 2 decimal places."
    PRD §2.10: "The ledger has no status filter and no time window: it is append-only,
    entries are never retracted, and a reversal is itself an entry that participates in
    the sum rather than deleting its target."
    PRD §2.10: "Only the number of ledger rows and the ledger's high-water sequence
    number advance."
    PRD §3.8: "Link two, caused by link one, appends a `REVERSAL` ledger entry whose
    `reverses_entry_id` points at the advance's `reserve_entry_id`, whose paid movement is
    the negation of the issued `amount`, and whose case-reserve movement is the positive
    `amount`, taking the next per-event `sequence_no`; the event's `incurred_total` is
    therefore again unchanged."

    Design: Difficulty/compensating_invariant/incurred_dollars_conserved_across_advance_issue_then_void
    """
    event, claim, advance, _ = _issued_advance_of_13500_on_a_standard_claim(api)
    payment_entry_id = advance["reserve_entry_id"]

    validate_success(
        api.void_advance_payment(
            advance["id"],
            {"void_reason": "Coverage question raised by SIU; advance withdrawn pending review"},
            CE,
        )
    )

    rows = validate_success(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert len(rows) == 3
    by_sequence = sorted(rows, key=lambda row: row["sequence_no"])
    assert [row["sequence_no"] for row in by_sequence] == [1, 2, 3]
    assert [row["entry_type"] for row in by_sequence] == [
        "INITIAL_CASE",
        "PAYMENT",
        "REVERSAL",
    ]
    payment_row, reversal_row = by_sequence[1], by_sequence[2]
    assert payment_row["id"] == payment_entry_id
    assert reversal_row["reverses_entry_id"] == payment_entry_id
    assert_money_equals(reversal_row["delta_paid"], -13500.00, "delta_paid")
    assert_money_equals(reversal_row["delta_case_reserve"], 13500.00, "delta_case_reserve")
    ledger_sum = sum(row["delta_case_reserve"] + row["delta_paid"] for row in rows)
    assert_money_equals(ledger_sum, 33750.00, "sum of every ledger movement")
    assert_money_equals(
        validate_success(api.get_event(event["id"], CM))["incurred_total"],
        ledger_sum,
        "incurred_total",
    )


# ---------------------------------------------------------------------------
# Instance 2 — physical_rooms_conserved_across_confirm_then_cancel
# ---------------------------------------------------------------------------
def _four_room_block_exhausted_by_two_confirmations(api):
    """CAT-2026-902 DECLARED with one ACTIVE four-room block; deployment D1 draws 3 rooms
    and D2 draws the last one, taking the block ACTIVE -> EXHAUSTED. D2 funds no
    inspection assignments, so it is cancellable. Returns the pre-confirm and mid-state
    room readings alongside the rows."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-902",
                "peril_type": "FLOOD",
                "jurisdiction_state": "LA",
                "event_start_utc": "2026-07-29T00:00:00.000Z",
                "exposure_count": 700,
                "avg_insured_value": 155000,
                "expected_severity_index": 0.1100,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Delta Four Suites",
                "city": "Houma",
                "rooms_total": 4,
                "nightly_rate": 130,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-30T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    opened = validate_success(api.open_housing_block(block["id"], DC))

    def _adjuster(full_name, daily_rate, per_diem_rate):
        return validate_success(
            api.create_adjuster(
                {
                    "full_name": full_name,
                    "employment_type": "STAFF",
                    "home_state": "LA",
                    "licensed_states": ["LA"],
                    "license_expiry_utc": "2027-08-31T00:00:00.000Z",
                    "max_open_claims": 8,
                    "daily_rate": daily_rate,
                    "per_diem_rate": per_diem_rate,
                    "desk_certified": False,
                    "aerial_certified": False,
                },
                DC,
            ),
            201,
        )

    adjuster_a = _adjuster("Room A", 500, 70)
    adjuster_b = _adjuster("Room B", 450, 60)

    def _deployment(adjuster, window_start, window_end, rooms_reserved):
        return validate_success(
            api.create_deployment(
                {
                    "event_id": event["id"],
                    "role_type": "FIELD",
                    "window_start_utc": window_start,
                    "window_end_utc": window_end,
                    "adjuster_id": adjuster["id"],
                    "housing_block_id": block["id"],
                    "rooms_reserved": rooms_reserved,
                },
                DC,
            ),
            201,
        )

    d_1 = _deployment(
        adjuster_a, "2026-09-05T00:00:00.000Z", "2026-09-08T00:00:00.000Z", 3
    )
    d_2 = _deployment(
        adjuster_b, "2026-09-06T00:00:00.000Z", "2026-09-09T00:00:00.000Z", 1
    )
    before = (opened["rooms_available"], opened["status"])
    validate_success(api.confirm_deployment(d_1["id"], DC))
    d_2 = validate_success(api.confirm_deployment(d_2["id"], DC))
    mid_block = validate_success(api.get_housing_block(block["id"], DC))
    mid = (mid_block["rooms_available"], mid_block["status"])
    return event, block, (adjuster_a, adjuster_b), (d_1, d_2), before, mid


def test_confirm_then_cancel_restores_the_exact_pre_confirm_room_reading(api):
    """PRD §2.10: "The compensating-action guarantee is again exact: confirming a
    deployment and then cancelling it leaves the block's `rooms_available` and its `status`
    exactly equal to their pre-confirm values, and the same holds for confirming and then
    demobilizing."
    PRD §2.10: "For every housing block, `rooms_total` equals `rooms_available` plus
    `rooms_occupied`, and `rooms_occupied` equals the sum of `rooms_reserved` over the
    deployments drawing on that block whose status is `CONFIRMED` or `ON_SITE`."
    PRD §3.4: "When rooms come back — a confirmed deployment is cancelled or demobilized —
    and `rooms_available` rises to 1 or more, the block moves `EXHAUSTED → ACTIVE`."

    Design: Difficulty/compensating_invariant/physical_rooms_conserved_across_confirm_then_cancel
    """
    _, block, _, (d_1, d_2), before, mid = _four_room_block_exhausted_by_two_confirmations(api)
    assert before == (4, "ACTIVE")
    assert mid == (0, "EXHAUSTED")

    validate_success(api.cancel_deployment(d_2["id"], DC))

    after = validate_success(api.get_housing_block(block["id"], DC))
    assert after["rooms_total"] == 4
    assert after["rooms_occupied"] == 3
    # D1's three rooms are still drawn, so availability returns to exactly D2's one room.
    assert after["rooms_available"] == 1
    assert after["rooms_occupied"] + after["rooms_available"] == after["rooms_total"]
    assert after["status"] == "ACTIVE"
    assert validate_success(api.get_deployment(d_1["id"], DC))["status"] == "CONFIRMED"


def test_cancellation_zeroes_the_settled_cost_but_keeps_the_provisional_price(api):
    """PRD §3.5: "Its links run in order: `final_settled_cost` is set to 0.00 while
    `provisional_cost` is retained for audit; the release of the draw returns
    `rooms_reserved` to the block, restoring `rooms_available` to exactly its pre-confirm
    value; that restoration takes a block that was `EXHAUSTED` back to `ACTIVE` when
    availability reaches 1 or more; the adjuster moves `DEPLOYED → RESTING` with
    `last_demobilized_at_utc` stamped at the current instant; and the event's
    `surge_adjuster_count`, `housing_committed_cost` and posture are recomputed."
    PRD §3.5: "The **provisional** variant, stamped into `provisional_cost` at
    confirmation, uses the deployment's full requested `window_end_utc` as the settle-end
    instant and treats per-diem eligibility as 1 unconditionally, so an independent
    adjuster with a hotel room is charged per-diem *and* housing."
    PRD §3.1: "`surge_adjuster_count` is the number of deployments on the event whose
    status is `CONFIRMED` or `ON_SITE`."

    Design: Difficulty/compensating_invariant/physical_rooms_conserved_across_confirm_then_cancel
    """
    event, _, (adjuster_a, adjuster_b), (_, d_2), _, _ = (
        _four_room_block_exhausted_by_two_confirmations(api)
    )
    # 3 nights: labour 450*1.00*3 = 1350.00, per-diem 60*3*1 = 180.00,
    # housing 130*1*3 = 390.00 -> subtotal 1920.00, below 5000.00 so TIER_NONE.
    assert_money_equals(d_2["provisional_cost"], 1920.00, "provisional_cost")
    assert d_2["surge_premium_tier"] == "TIER_NONE"

    cancelled = validate_success(api.cancel_deployment(d_2["id"], DC))

    assert cancelled["status"] == "CANCELLED"
    assert_money_equals(cancelled["final_settled_cost"], 0.00, "final_settled_cost")
    assert_money_equals(cancelled["provisional_cost"], 1920.00, "provisional_cost retained")
    assert cancelled["surge_premium_tier"] == "TIER_NONE"
    released = validate_success(api.get_adjuster(adjuster_b["id"], DC))
    assert released["deployment_status"] == "RESTING"
    assert released["last_demobilized_at_utc"] == "2026-08-01T00:00:00.000Z"
    assert validate_success(api.get_adjuster(adjuster_a["id"], DC))["deployment_status"] == (
        "DEPLOYED"
    )
    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert refreshed_event["surge_adjuster_count"] == 1
    assert refreshed_event["posture"] == "OPEN"


# ---------------------------------------------------------------------------
# Instance 3 — vendor_concurrency_slots_conserved_across_accept_then_complete
# ---------------------------------------------------------------------------
def _firm_on_capacity_hold_with_two_accepted_jobs(api):
    """CAT-2026-903 DECLARED; Sierra Tarp Co ACTIVATED onto it with a ceiling of two
    concurrent jobs; three identical FAST_TRACK claims, the first two carrying ACCEPTED
    assignments that take the firm to CAPACITY_HOLD and the third untouched."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-903",
                "peril_type": "WILDFIRE",
                "jurisdiction_state": "CA",
                "event_start_utc": "2026-07-30T00:00:00.000Z",
                "exposure_count": 450,
                "avg_insured_value": 420000,
                "expected_severity_index": 0.1000,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    firm = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Sierra Tarp Co",
                "vendor_type": "TARP",
                "service_states": ["CA"],
                "max_concurrent_jobs": 2,
                "performance_score": 91.00,
            },
            make_vendor_coordinator_headers("vc_seed"),
        ),
        201,
    )
    firm_headers = make_vendor_coordinator_headers(firm["id"])
    validate_success(api.activate_vendor_firm(firm["id"], {"event_id": event["id"]}, firm_headers))

    def _triaged_claim(policy_number):
        row = validate_success(
            api.create_claim(
                {
                    "policy_number": policy_number,
                    "loss_state": "CA",
                    "loss_date_utc": "2026-07-30T00:00:00.000Z",
                    "reported_loss_amount": 9000,
                    "coverage_lines": [
                        {
                            "coverage_code": "DWELLING",
                            "limit_amount": 500000,
                            "deductible_amount": 1000,
                            "estimated_damage_amount": 10000,
                        }
                    ],
                    "event_id": event["id"],
                    "access_status": "ACCESSIBLE",
                },
                CE,
            ),
            201,
        )
        return validate_success(api.triage_claim(row["id"], CE))

    claims = [_triaged_claim(number) for number in ("POL-9301", "POL-9302", "POL-9303")]

    def _dispatch(claim):
        return validate_success(
            api.create_vendor_assignment(
                {
                    "claim_id": claim["id"],
                    "scope_amount": 6000,
                    "required_vendor_type": "TARP",
                    "vendor_firm_id": firm["id"],
                },
                CE,
            ),
            201,
        )

    va_1 = validate_success(api.accept_vendor_assignment(_dispatch(claims[0])["id"], firm_headers))
    open_after_first = validate_success(api.get_vendor_firm(firm["id"], firm_headers))
    va_2 = validate_success(api.accept_vendor_assignment(_dispatch(claims[1])["id"], firm_headers))
    on_hold = validate_success(
        api.list_vendor_firms(
            firm_headers, params={"activated_for_event_id": event["id"]}
        )
    )[0]
    return event, firm, firm_headers, claims, (va_1, va_2), open_after_first, on_hold


def test_the_second_acceptance_consumes_the_last_slot_and_holds_the_firm(api):
    """PRD §3.9: "Occupancy then drives the firm automatically: when a job acceptance
    drives `open_job_count` to exactly `max_concurrent_jobs`, the firm moves
    `ACTIVATED → CAPACITY_HOLD`; when a job leaves the open population and
    `open_job_count` falls back below the ceiling, the firm moves
    `CAPACITY_HOLD → ACTIVATED`."
    PRD §3.9: "Firms may be listed filtered by `activated_for_event_id`, `vendor_type`,
    `status` and `service_state`."
    PRD §3.9: "**Activation** moves a firm `NETWORK_INACTIVE → ACTIVATED` against a named
    `event_id`, which is stored in `activated_for_event_id`."

    Design: Difficulty/compensating_invariant/vendor_concurrency_slots_conserved_across_accept_then_complete
    """
    event, _, _, claims, (va_1, va_2), open_after_first, on_hold = (
        _firm_on_capacity_hold_with_two_accepted_jobs(api)
    )

    assert va_1["status"] == "ACCEPTED"
    assert va_2["status"] == "ACCEPTED"
    # One slot of two consumed leaves the firm working; the second consumes the last.
    assert open_after_first["open_job_count"] == 1
    assert open_after_first["status"] == "ACTIVATED"
    assert on_hold["open_job_count"] == 2
    assert on_hold["status"] == "CAPACITY_HOLD"
    assert on_hold["max_concurrent_jobs"] == 2
    assert on_hold["activated_for_event_id"] == event["id"]
    # 100 * (9000/500000) * 1.25 WILDFIRE + 20 * 0.1000 = 4.25 -> FAST_TRACK.
    assert_money_equals(claims[0]["severity_score"], 4.25, "severity_score")
    assert claims[0]["triage_tier"] == "FAST_TRACK"
    assert_money_equals(
        validate_success(api.get_event(event["id"], CM))["case_reserve_total"],
        6750.00,
        "case_reserve_total",
    )


def test_completing_one_job_hands_the_slot_straight_back_to_the_firm(api):
    """PRD §3.9: "**Completing** moves it `ACCEPTED → COMPLETED`; from any other status the
    answer is `ERR_VENDOR_ASSIGNMENT_NOT_ACCEPTED`; `open_job_count` is recomputed and the
    firm returns `CAPACITY_HOLD → ACTIVATED` when the count falls below the ceiling."
    PRD §3.9: "Occupancy then drives the firm automatically: when a job acceptance drives
    `open_job_count` to exactly `max_concurrent_jobs`, the firm moves
    `ACTIVATED → CAPACITY_HOLD`; when a job leaves the open population and
    `open_job_count` falls back below the ceiling, the firm moves
    `CAPACITY_HOLD → ACTIVATED`."
    PRD §3.9: "Vendor assignment lists may be filtered by `claim_id`, `vendor_firm_id` and
    `status`."

    Design: Difficulty/compensating_invariant/vendor_concurrency_slots_conserved_across_accept_then_complete
    """
    _, firm, firm_headers, claims, (va_1, va_2), _, on_hold = (
        _firm_on_capacity_hold_with_two_accepted_jobs(api)
    )
    assert on_hold["status"] == "CAPACITY_HOLD"

    completed = validate_success(api.complete_vendor_assignment(va_1["id"], firm_headers))

    assert completed["status"] == "COMPLETED"
    assert validate_success(api.get_vendor_assignment(va_2["id"], firm_headers))["status"] == (
        "ACCEPTED"
    )
    released = validate_success(api.get_vendor_firm(firm["id"], firm_headers))
    assert released["open_job_count"] == 1
    assert released["status"] == "ACTIVATED"

    # The freed slot is immediately usable: a third job dispatches against the ceiling,
    # and a dispatch on its own never drives the CAPACITY_HOLD edge — only an acceptance
    # does.
    va_3 = validate_success(
        api.create_vendor_assignment(
            {
                "claim_id": claims[2]["id"],
                "scope_amount": 6000,
                "required_vendor_type": "TARP",
                "vendor_firm_id": firm["id"],
            },
            CE,
        ),
        201,
    )
    assert va_3["status"] == "DISPATCHED"
    assert validate_success(api.get_vendor_firm(firm["id"], firm_headers))["status"] == "ACTIVATED"
    rows = validate_success(
        api.list_vendor_assignments(firm_headers, params={"vendor_firm_id": firm["id"]})
    )
    assert len(rows) == 3

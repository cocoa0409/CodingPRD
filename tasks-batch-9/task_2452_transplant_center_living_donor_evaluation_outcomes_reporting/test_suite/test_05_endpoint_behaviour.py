"""One representative pass over each endpoint shape the contract declares."""
from test_helpers import (
    add_operating_room,
    advance_clock,
    book_theatre,
    create_active_recipient,
    create_donor,
    create_finalized_flagged_review,
    create_improvement_plan_payload,
    file_and_approve_claim,
    file_claim,
    get_donor,
    get_room_listing,
    setup_committed_paired_loop,
    setup_donated_donor,
    setup_program_with_staff,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


def _follow_ups(env, donor_id, status):
    return validate_paginated(
        api_client.list_donor_follow_ups(
            donor_id, env["coordinator_headers"], params={"status": status}
        )
    )


def test_one_sweep_call_flips_every_overdue_follow_up_row():
    """PRD §3.1: "A compliance sweep, available to both `QualityOfficer` and
    `ProgramAdmin` principals, does four things in order: it moves every donor follow-up
    of the program that is still `DUE` or `INCOMPLETE` and whose grace period has run out
    to `DELINQUENT`; it recomputes `follow_up_compliance_pct` and `cit_breach_count`; it
    re-derives `compliance_posture` with the chain suspend-and-restore cascade described
    in §2.8; and it records the current logical clock in `last_sweep_at`, incrementing the
    program's `version`."
    PRD §3.1: "The grace period is thirty days past an interval's `due_on`: the sweep only
    declares an interval delinquent once the logical clock has reached or passed that
    thirtieth day."
    PRD §3.7: "The numerator is the count of those same rows whose `status` is
    `SUBMITTED_COMPLETE`."
    PRD §3.1: "Note that `cit_breach_count` is a count of this program's chain segments
    whose `cit_breach` flag is true."

    Design: Corner/endpoints/compliance_sweep_flips_every_overdue_row_in_one_call
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]
    assert env["program"]["last_sweep_at"] is None
    advance_clock(env, "2028-09-08T06:00:00Z")

    swept = validate_success(
        api_client.run_compliance_sweep(env["program_id"], env["admin_headers"])
    )

    assert swept["last_sweep_at"].startswith("2028-09-08T06:00:00")
    assert swept["follow_up_compliance_pct"] == 0.0, "denominator 3, numerator 0"
    assert swept["compliance_posture"] == "RESTRICTED"
    assert swept["cit_breach_count"] == 0
    assert swept["donor_fund_committed_cents"] == 0
    assert swept["donor_fund_remaining_cents"] == 5000000

    _rows, delinquent = _follow_ups(env, donor_id, "DELINQUENT")
    assert delinquent["total_count"] == 3, "all three rows moved in the one call"
    _rows, still_due = _follow_ups(env, donor_id, "DUE")
    assert still_due["total_count"] == 0


def test_filing_a_plan_links_to_its_review_and_bumps_that_review():
    """PRD §3.8: "It carries the `program_outcome_review_id`, the
    `expected_review_version` described in §2.7, a `title`, a `milestone_count` of at
    least 1, and a `target_completion_on` date in `YYYY-MM-DD` form."
    PRD §3.8: "Creation puts the new plan in `SUBMITTED` with `decision_reason_code`,
    `decided_at` and `closed_at` all null, moves any existing plan of the same review
    whose status is `SUBMITTED` or `REJECTED` to `SUPERSEDED` — which the system will only
    do while no plan of that review has already reached `ACCEPTED` or `CLOSED` — and
    increments the parent review's `version` so that a competing writer holding the old
    value is now stale."
    PRD §3.8: "A review's plans are listed through the review, filtered on `status`,
    with `limit` and `offset`."
    PRD §2.8: "A review counts as an **unanswered flagged review** when it belongs to this
    program, its `status` is `FINALIZED`, its `flag_level` is `FLAGGED`, and no improvement
    plan of that review has reached `ACCEPTED` or `CLOSED`."

    Design: Corner/endpoints/improvement_plan_creation_links_to_its_review_and_bumps_it
    """
    env = setup_program_with_staff()
    review = create_finalized_flagged_review(
        env, cohort_size=25, observed_survivor_count=16
    )
    assert review["flag_level"] == "FLAGGED"
    assert review["oe_ratio"] == 0.8
    assert review["requires_improvement_plan"] is True
    review_version = review["version"]

    plan = validate_success(
        api_client.create_improvement_plan(
            create_improvement_plan_payload(
                review["id"],
                review_version,
                title="Donor selection tightening",
                milestone_count=3,
                target_completion_on="2027-01-31",
            ),
            env["quality_headers"],
        ),
        expected_status=201,
    )

    assert plan["program_outcome_review_id"] == review["id"]
    assert plan["status"] == "SUBMITTED"
    assert plan["milestone_count"] == 3
    assert plan["decision_reason_code"] is None
    assert plan["decided_at"] is None
    assert plan["closed_at"] is None
    assert plan["version"] == 1

    rows, meta = validate_paginated(
        api_client.list_review_improvement_plans(review["id"], env["quality_headers"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["title"] == "Donor selection tightening"

    reread = validate_success(
        api_client.get_outcome_review(review["id"], env["quality_headers"])
    )
    assert reread["version"] == review_version + 1, (
        "a competing writer holding the old value is now stale"
    )

    program = validate_success(
        api_client.get_program(env["program_id"], env["admin_headers"])
    )
    assert program["compliance_posture"] == "FROZEN", "filing is not answering"


def test_the_program_read_is_the_only_window_onto_the_fund_ledger():
    """PRD §2.9: "A program's `donor_fund_committed_cents` is the sum of
    `fund_part_cents` over every donor cost claim whose donor belongs to that program and
    whose `status` is `ADJUDICATED`."
    PRD §2.9: "Committed plus remaining always equals the pool, and remaining is always
    between 0 and the pool inclusive, after every adjudication, denial and reversal."
    PRD §3.1: "A program read exposes its derived fund, compliance and posture figures."
    PRD §3.7: "When the denominator is zero the figure is 100.00 — a brand-new program
    with three future-dated rows reports the vacuous 100.00 rather than 0.00."
    PRD §3.1: "The `last_sweep_at` field is null until the first compliance sweep runs."

    Design: Corner/endpoints/program_read_exposes_the_derived_fund_ledger
    """
    env = setup_donated_donor()
    claim = file_and_approve_claim(
        env,
        env["donor_one"]["id"],
        claim_type="MEDICAL",
        coverage_source="PROGRAM_FUND",
        submitted_amount_cents=450000,
    )
    assert claim["estimated_reimbursement_cents"] == 450000
    assert claim["fund_part_cents"] == 450000

    program = validate_success(
        api_client.get_program(env["program_id"], env["finance_headers"])
    )

    assert program["donor_fund_pool_cents"] == 5000000
    assert program["donor_fund_committed_cents"] == 450000
    assert program["donor_fund_remaining_cents"] == 4550000
    assert (
        program["donor_fund_committed_cents"] + program["donor_fund_remaining_cents"]
        == program["donor_fund_pool_cents"]
    )
    assert program["follow_up_compliance_pct"] == 100.0, "nothing is due yet"
    assert program["compliance_posture"] == "OPEN"
    assert program["cit_breach_count"] == 0
    assert program["last_sweep_at"] is None


def test_a_booking_read_returns_the_duration_it_computed_itself():
    """PRD §3.6: "The booking starts in `ACTIVE`, its `duration_minutes` is the whole
    minutes between `start_at` and `end_at`, its `cancel_reason_code` is null, and the
    room's `reserved_minutes_total` is incremented by that duration."
    PRD §3.6: "Bookings are listed with optional `operating_room_id`,
    `chain_segment_id`, `surgeon_staff_id`, `booking_role` and `status` filters plus
    `limit` and `offset`, and read individually to expose `duration_minutes` and
    `cancel_reason_code`."
    PRD §2.9: "A room's `reserved_minutes_total` is the sum of `duration_minutes` over
    that room's procedure bookings whose `status` is `ACTIVE` or `COMPLETED`."

    Design: Corner/endpoints/booking_read_returns_its_computed_duration
    """
    env = setup_committed_paired_loop()
    room = add_operating_room(env, "OR-1")
    booking = book_theatre(
        env,
        room["id"],
        env["segment_one"]["id"],
        "DONOR_RECOVERY",
        "2026-08-09T06:00:00Z",
        "2026-08-09T10:00:00Z",
    )

    read = validate_success(
        api_client.get_procedure_booking(booking["id"], env["coordinator_headers"])
    )

    assert read["status"] == "ACTIVE"
    assert read["booking_role"] == "DONOR_RECOVERY"
    assert read["duration_minutes"] == 240
    assert read["cancel_reason_code"] is None
    assert read["version"] == 1
    assert read["operating_room_id"] == room["id"]
    assert read["chain_segment_id"] == env["segment_one"]["id"]
    assert read["surgeon_staff_id"] == env["surgeon"]["id"]

    rooms = [row for row in get_room_listing(env) if row["id"] == room["id"]]
    assert rooms[0]["reserved_minutes_total"] == 240


def test_denying_a_claim_records_the_reason_and_moves_no_money():
    """PRD §3.9: "**The pessimistic adjudication.** A `FinanceAdmin` decides a claim by
    supplying a `decision` and, for a denial, a `decision_reason_code`."
    PRD §3.9: "Both branches are only reachable from `SUBMITTED`, and both stamp
    `adjudicated_at` with the current logical clock, record the deciding operator's
    `X-User-ID` as `adjudicated_by_user_id`, and increment the claim's `version`."
    PRD §3.9: "A denial requires a `decision_reason_code`, moves the claim to `DENIED` —
    a terminal state — sets `adjudicated_reimbursement_cents` and all three part fields to
    0, sets `unfunded_cents` to the full `estimated_reimbursement_cents`, and leaves the
    program fund untouched."
    PRD §3.9: "For a `TRAVEL` claim the cap is 350,000 cents (three thousand five hundred
    dollars)."
    PRD §2.9: "A reversed claim leaves the sum entirely, restoring the pool exactly with
    no residue; a denied claim never entered the sum in the first place."

    Design: Corner/endpoints/claim_denial_takes_the_other_branch_of_the_same_endpoint
    """
    env = setup_donated_donor()
    claim = file_claim(
        env,
        env["donor_one"]["id"],
        claim_type="TRAVEL",
        coverage_source="NLDAC_GRANT",
        submitted_amount_cents=500000,
    )
    assert claim["estimated_reimbursement_cents"] == 350000, "the travel cap binds"

    denied = validate_success(
        api_client.adjudicate_claim(
            claim["id"],
            {"decision": "DENY", "decision_reason_code": "NOT_DONOR_RELATED"},
            env["finance_headers"],
        )
    )

    assert denied["status"] == "DENIED"
    assert denied["adjudicated_at"].startswith("2026-08-09T06:00:00")
    assert denied["adjudicated_by_user_id"] == env["finance_headers"]["X-User-ID"]
    assert denied["estimated_reimbursement_cents"] == 350000, "never revised"
    assert denied["insurance_part_cents"] == 0
    assert denied["grant_part_cents"] == 0
    assert denied["fund_part_cents"] == 0
    assert denied["adjudicated_reimbursement_cents"] == 0
    assert denied["unfunded_cents"] == 350000

    program = validate_success(
        api_client.get_program(env["program_id"], env["finance_headers"])
    )
    assert program["donor_fund_committed_cents"] == 0
    assert program["donor_fund_remaining_cents"] == 5000000


def test_the_bodiless_disclosure_action_writes_exactly_its_three_fields():
    """PRD §3.3: "Only the assigned advocate may record an informed-consent disclosure
    session, and the operation takes no body fields at all."
    PRD §3.3: "It advances `disclosure_sequence` by 1, sets `disclosure_at` to the current
    logical clock, and re-derives `cooling_off_ends_at`."
    PRD §3.3: "Finally, `cooling_off_ends_at` is `disclosure_at` plus that many whole
    days, with the time-of-day component carried over untouched."
    PRD §3.3: "Then, if `disclosure_sequence` has reached 2 or more — that is, on every
    re-consent — the effective window is the larger of two days and half the base rounded
    up to a whole day; otherwise the effective window is the base itself."
    PRD §3.4: "And `final_risk_index` stays null until the donor has both clinical
    dimensions `CLEARED` and `advocacy_status` `ATTESTED`."

    Design: Corner/endpoints/consent_disclosure_action_sets_exactly_three_fields
    """
    env = setup_program_with_staff()
    recipient = create_active_recipient(env, mrn="R-001")
    donor = create_donor(
        env, intended_recipient_id=recipient["id"], mrn="D-001", age_years=41
    )
    assert donor["advocacy_status"] == "ASSIGNED"
    assert donor["disclosure_sequence"] == 0

    disclosed = validate_success(
        api_client.record_consent_disclosure(donor["id"], env["advocate_headers"])
    )

    assert disclosed["advocacy_status"] == "DISCLOSED"
    assert disclosed["disclosure_sequence"] == 1
    assert disclosed["disclosure_at"].startswith("2026-08-01T00:00:00")
    assert disclosed["cooling_off_ends_at"].startswith("2026-08-08T00:00:00"), (
        "seven directed days with no surcharge and no halving"
    )

    after = get_donor(env, donor["id"])
    assert after["medical_status"] == "PENDING"
    assert after["psychosocial_status"] == "PENDING"
    assert after["overall_status"] == "REFERRED"
    assert after["attestation_at"] is None
    assert after["final_risk_index"] is None

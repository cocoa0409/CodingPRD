"""Consistency: the write response already carries what that write recomputed."""

from test_helpers import (
    DEFAULT_CLOCK,
    api_client,
    assert_committee_referral,
    assert_cost_estimate,
    assert_fiscal_note_request,
    assert_instant,
    assert_note_total_invariants,
    assert_session_ledger_invariants,
    create_cost_estimate_payload,
    read_bill,
    read_committee,
    read_note,
    read_session,
    refer_bill,
    report_payload,
    route_fiscal_note,
    set_clock,
    setup_introduced_bill,
    setup_world,
    validate_success,
)


def test_each_write_response_already_carries_the_derived_state_it_recomputed():
    """PRD: "A routed note opens in `status` `ROUTED` with `revision_round` at 0,
    `routed_utc` stamped from the logical clock, `submitted_utc` and `certified_utc`
    null, `late_submission` false, `reopened_by_amendment_id` null, and every
    computed money field — `direct_cost_cents`, `contingency_pct`,
    `contingency_cents`, `certified_total_cents`, `projected_revenue_total_cents`,
    `high_scenario_total_cents` and `low_scenario_total_cents` — null until the
    first submission." and "The line's `revision_round` is copied from the note's
    current `revision_round` at creation, and `included_in_certification` is set
    true." and "Under `INCREMENTAL_COST` the agency asserts that existing staff
    absorb sub-half-FTE work, so `direct_cost_cents` is the sum over those lines of
    `operating_cost_cents` plus `one_time_cost_cents` plus — only when that line's
    `fte_count` is at least 0.5 — `personnel_cost_cents`." and "At the low boundary,
    a direct subtotal of exactly 10,000,000 yields a contingency of 500,000 and a
    certified total of 10,500,000." and "On success the note moves to `SUBMITTED`,
    `submitted_utc` is stamped with the logical clock, and `late_submission` is set
    true exactly when `submitted_utc` falls strictly after `due_utc`." and "The
    ledger is maintained by exact addition when a note is certified and exact
    subtraction when a certified note is re-opened, and the incrementally
    maintained value must equal a full recomputation of that sum at every
    observable instant." and "Alongside the ledger the session maintains
    `fiscal_posture`, which is `CONSTRAINED` when `certified_fiscal_total_cents` is
    greater than or equal to `constrained_threshold_cents` and `NORMAL` otherwise."
    and "It requires the bill's `fiscal_status` to be `NOT_REQUIRED` or
    `NOTE_COMPLETE`; a bill sitting at `NOTE_PENDING` or `NOTE_STALE` cannot be
    reported favourably until a note is certified, and the refusal is
    `ERR_FISCAL_NOTE_REQUIRED`." and "On success the referral moves from
    `IN_COMMITTEE` to `REPORTED_FAVORABLE`, `reported_utc` is stamped with the
    logical clock, and the committee's `active_referral_count` drops by one." and
    "If — and only if — no referral of that bill remains `IN_COMMITTEE`, the bill
    advances from `REFERRED` to `REPORTED`; a bill with a second committee still
    holding it stays in `REFERRED`."

    Design: Corner/consistency_model/every_write_response_already_carries_the_derived_state_that_write_recomputed
    """
    world = setup_world(with_committee=True, with_agency=True)
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=4,
        requested_sections_count=4,
        appropriation_requested_cents=5_000_000,
    )
    referral = refer_bill(world, bill)
    assert referral["status"] == "IN_COMMITTEE"

    note = route_fiscal_note(world, bill, methodology="INCREMENTAL_COST")
    assert_fiscal_note_request(note)
    # Nothing is computed yet, so there is no derived value to lag behind.
    assert note["revision_round"] == 0
    assert note["direct_cost_cents"] is None
    assert note["certified_total_cents"] is None

    first_line = validate_success(
        api_client.create_cost_estimate(
            note["id"],
            create_cost_estimate_payload(
                note["version"],
                fiscal_year=2027,
                scenario="BASELINE",
                personnel_cost_cents=5_000_000,
                operating_cost_cents=1_000_000,
                one_time_cost_cents=0,
                fte_count=1.0,
                revenue_impact_cents=0,
                assumption_note="Year one.",
            ),
            world["analyst_headers"],
        ),
        201,
    )
    assert_cost_estimate(first_line)
    # The round is copied from the parent inside the create call itself.
    assert first_line["revision_round"] == 0
    assert first_line["included_in_certification"] is True

    second_line = validate_success(
        api_client.create_cost_estimate(
            note["id"],
            create_cost_estimate_payload(
                read_note(world, note["id"])["version"],
                fiscal_year=2028,
                scenario="BASELINE",
                personnel_cost_cents=3_000_000,
                operating_cost_cents=1_000_000,
                one_time_cost_cents=0,
                fte_count=1.0,
                revenue_impact_cents=0,
                assumption_note="Year two.",
            ),
            world["analyst_headers"],
        ),
        201,
    )
    assert second_line["revision_round"] == 0

    submitted = validate_success(
        api_client.submit_fiscal_note_request(
            note["id"], {"submission_note": "Both years filed."}, world["analyst_headers"]
        ),
        200,
    )
    # The submit response is the one that recomputed the totals; they are in it.
    assert submitted["status"] == "SUBMITTED"
    assert submitted["direct_cost_cents"] == 10_000_000
    assert float(submitted["contingency_pct"]) == 0.05
    assert submitted["contingency_cents"] == 500_000
    assert submitted["certified_total_cents"] == 10_500_000
    assert submitted["late_submission"] is False
    assert_note_total_invariants(submitted)

    certified = validate_success(
        api_client.certify_fiscal_note_request(
            note["id"],
            {"certification_note": "Accepted as filed."},
            world["fiscal_officer_headers"],
        ),
        200,
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_total_cents"] == 10_500_000
    assert_instant(certified["certified_utc"], DEFAULT_CLOCK)

    # First read after the certification, with no second attempt allowed.
    session_now = read_session(world)
    assert session_now["certified_fiscal_total_cents"] == 10_500_000
    assert session_now["fiscal_posture"] == "NORMAL"
    assert_session_ledger_invariants(session_now)
    assert read_bill(world, bill["id"])["fiscal_status"] == "NOTE_COMPLETE"

    set_clock("2026-10-06T00:00:00Z")
    reported = validate_success(
        api_client.report_referral(
            referral["id"], report_payload("FAVORABLE"), world["clerk_headers"]
        ),
        200,
    )
    assert_committee_referral(reported)
    # The stamp and the closure are set by the very call that returned this body.
    assert reported["status"] == "REPORTED_FAVORABLE"
    assert_instant(reported["reported_utc"], "2026-10-06T00:00:00Z")

    # Every cross-entity effect of that one action is visible on the first read.
    assert read_committee(world, world["committee"]["id"])["active_referral_count"] == 0
    assert read_bill(world, bill["id"])["legislative_status"] == "REPORTED"

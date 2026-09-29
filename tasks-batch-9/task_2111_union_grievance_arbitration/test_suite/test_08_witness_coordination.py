"""Calling witnesses: release-time pricing, slot geometry and the award-time routing."""

import pytest

from test_helpers import (
    ApiErrorId,
    add_employee,
    add_witness_employee,
    assert_cost_allocation,
    assert_witness_assignment,
    call_witness,
    confirm_witness,
    file_prep_through_briefs,
    read_grievance,
    record_award,
    schedule_hearing,
    set_clock,
    setup_selected_arbitrator_case,
    setup_split_award_case,
    validate_error,
    validate_paginated,
    validate_success,
    witness_assignment_payload,
)


def _case_with_witness():
    ctx = setup_selected_arbitrator_case()
    add_witness_employee(ctx)
    return ctx


def test_release_hours_round_up_to_the_next_quarter_on_each_assignment(api):
    """PRD §3.7: "The **release time** an assignment consumes is computed per assignment, and
    the order of the arithmetic is normative. First take the exact hours between
    `slot_start_at` and `slot_end_at`. Then add a prep allowance of one and a half hours — an
    hour and a half of preparation is granted to every witness regardless of how long they
    are on the stand. Then round that sum **up to the next quarter of an hour** and store it
    as `release_hours`. Then multiply `release_hours` by the called employee's
    `hourly_rate_cents` and round half up to whole cents, storing the result as
    `release_cost_cents`."

    Design: Difficulty/combinatorial_formula/witness_release_cost_per_assignment_rounding_order
    """
    ctx = _case_with_witness()

    first = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T09:00:00Z", "2026-10-05T12:20:00Z", headers=ctx["steward_headers"],
    )
    second = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T13:00:00Z", "2026-10-05T14:10:00Z", headers=ctx["steward_headers"],
    )
    assert_witness_assignment(first)
    assert_witness_assignment(second)

    assert first["release_hours"] == pytest.approx(5.0)
    assert first["release_cost_cents"] == 15_000
    assert second["release_hours"] == pytest.approx(2.75)
    assert second["release_cost_cents"] == 8_250


def test_year_to_date_release_hours_sum_the_per_assignment_figures(api, analyst_headers):
    """PRD §3.7: "Every one of those steps happens per assignment before any assignment is
    added to any other: summing raw hours across several assignments and rounding once at the
    end is the wrong reading and yields a smaller figure than the correct one."
    PRD §3.1: "Each person also reports the supervisor scorecard of §3.9 —
    `open_grievance_count`, `closed_grievance_count`, `sustained_against_count` and
    `adverse_rate_bps` — plus `witness_release_hours_ytd`, the release hours accumulated
    across every case where their assignment stands at `CONFIRMED` or `TESTIFIED`."

    Design: Difficulty/combinatorial_formula/witness_release_cost_per_assignment_rounding_order
    """
    ctx = _case_with_witness()
    first = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T09:00:00Z", "2026-10-05T12:20:00Z", headers=ctx["steward_headers"],
    )
    second = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T13:00:00Z", "2026-10-05T14:10:00Z", headers=ctx["steward_headers"],
    )

    confirmed_first = confirm_witness(first["id"])
    confirmed_second = confirm_witness(second["id"])
    assert confirmed_first["status"] == "CONFIRMED"
    assert confirmed_second["status"] == "CONFIRMED"

    witness = validate_success(api.get_employee(ctx["witness"]["id"], analyst_headers), 200)
    assert witness["witness_release_hours_ytd"] == pytest.approx(7.75), (
        "5.00 plus 2.75, not the 7.50 a single rounding of the raw hours would give"
    )


def test_each_confirmation_posts_its_own_release_time_charge(api, analyst_headers):
    """PRD §3.7: "Because the release was approved, a system-origin cost entry is posted
    against the grievance with `category` `RELEASE_TIME`, `bearing_party` `UNION` and
    `amount_cents` equal to the assignment's `release_cost_cents`, and that entry's identifier
    is stored on the assignment as `release_cost_entry_id`."

    Design: Difficulty/combinatorial_formula/witness_release_cost_per_assignment_rounding_order
    """
    ctx = _case_with_witness()
    first = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T09:00:00Z", "2026-10-05T12:20:00Z", headers=ctx["steward_headers"],
    )
    second = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T13:00:00Z", "2026-10-05T14:10:00Z", headers=ctx["steward_headers"],
    )
    confirmed_first = confirm_witness(first["id"])
    confirmed_second = confirm_witness(second["id"])

    rows, meta = validate_paginated(
        api.list_cost_entries(
            ctx["grievance"]["id"], analyst_headers, params={"category": "RELEASE_TIME"}
        )
    )
    assert meta["total_count"] == 2
    assert sum(row["amount_cents"] for row in rows) == 23_250, "15000 + 8250, not 22500"
    assert all(row["bearing_party"] == "UNION" for row in rows)
    assert all(row["origin"] == "SYSTEM" for row in rows)

    entry_ids = {row["id"] for row in rows}
    assert confirmed_first["release_cost_entry_id"] in entry_ids
    assert confirmed_second["release_cost_entry_id"] in entry_ids


def test_touching_slots_are_free_while_an_overlapping_slot_conflicts(api, analyst_headers):
    """PRD §3.7: "A new slot is rejected with `ERR_WITNESS_SLOT_CONFLICT` when it intersects
    any existing slot of the **same person on any demand anywhere in the system** whose
    assignment stands at `INVITED`, `CONFIRMED` or `TESTIFIED`. Because the intervals are
    half-open, slots that merely touch — one ending at the exact instant the next begins — do
    not conflict."

    Design: Difficulty/resource_temporal_overlap/witness_half_open_slot_and_daily_release_cap
    """
    ctx = _case_with_witness()
    first = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T09:00:00Z", "2026-10-05T12:20:00Z", headers=ctx["steward_headers"],
    )
    assert first["release_hours"] == pytest.approx(5.0)

    touching = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T12:20:00Z", "2026-10-05T13:00:00Z", headers=ctx["steward_headers"],
    )
    assert touching["release_hours"] == pytest.approx(2.25)
    assert touching["release_cost_cents"] == 6_750

    overlapping = api.create_witness_assignment(
        ctx["demand"]["id"],
        witness_assignment_payload(
            ctx["witness"]["id"], "2026-10-05T12:10:00Z", "2026-10-05T12:30:00Z"
        ),
        ctx["steward_headers"],
    )
    validate_error(overlapping, ApiErrorId.ERR_WITNESS_SLOT_CONFLICT.value)


def test_daily_release_cap_refuses_a_slot_that_overlaps_nothing(api):
    """PRD §3.7: "Separately, an aggregate daily release cap applies: the person's total
    release hours for the UTC calendar date of the new slot's `slot_start_at`, counting
    assignments at `INVITED`, `CONFIRMED` or `TESTIFIED` and including the new one, may not be
    strictly greater than ten hours; a breach is rejected with
    `ERR_WITNESS_RELEASE_CAP_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/witness_half_open_slot_and_daily_release_cap
    """
    ctx = _case_with_witness()
    call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T09:00:00Z", "2026-10-05T12:20:00Z", headers=ctx["steward_headers"],
    )
    call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T12:20:00Z", "2026-10-05T13:00:00Z", headers=ctx["steward_headers"],
    )

    over_cap = api.create_witness_assignment(
        ctx["demand"]["id"],
        witness_assignment_payload(
            ctx["witness"]["id"], "2026-10-05T14:00:00Z", "2026-10-05T16:15:00Z"
        ),
        ctx["steward_headers"],
    )
    validate_error(over_cap, ApiErrorId.ERR_WITNESS_RELEASE_CAP_EXCEEDED.value)


def test_a_slot_landing_exactly_on_the_daily_cap_is_accepted(api, analyst_headers):
    """PRD §3.7: "Separately, an aggregate daily release cap applies: the person's total
    release hours for the UTC calendar date of the new slot's `slot_start_at`, counting
    assignments at `INVITED`, `CONFIRMED` or `TESTIFIED` and including the new one, may not be
    strictly greater than ten hours; a breach is rejected with
    `ERR_WITNESS_RELEASE_CAP_EXCEEDED`."
    PRD §2.3: "- Testimony slots reserved for one person, and the witnesses coordinated for
    one arbitration case: ascending `slot_start_at`, then ascending `created_at`."

    Design: Difficulty/resource_temporal_overlap/witness_half_open_slot_and_daily_release_cap
    """
    ctx = _case_with_witness()
    call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T09:00:00Z", "2026-10-05T12:20:00Z", headers=ctx["steward_headers"],
    )
    call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T12:20:00Z", "2026-10-05T13:00:00Z", headers=ctx["steward_headers"],
    )

    on_the_cap = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T14:00:00Z", "2026-10-05T15:15:00Z", headers=ctx["steward_headers"],
    )
    assert on_the_cap["release_hours"] == pytest.approx(2.75), "5.00 + 2.25 + 2.75 is exactly 10.00"

    rows, meta = validate_paginated(
        api.list_employee_witness_assignments(ctx["witness"]["id"], analyst_headers)
    )
    assert meta["total_count"] == 3
    starts = [row["slot_start_at"] for row in rows]
    assert starts == sorted(starts), "ordered by slot_start_at ASC"

    witness = validate_success(api.get_employee(ctx["witness"]["id"], analyst_headers), 200)
    assert witness["witness_release_hours_ytd"] == pytest.approx(0.0), (
        "none of the three assignments has been confirmed"
    )


def test_witness_gates_refuse_the_filing_steward_and_a_terminated_employee(api, analyst_headers):
    """PRD §3.7: "Two people-level bars apply: the called employee must not have
    `employment_status` `TERMINATED`, or the call is rejected with `ERR_WITNESS_NOT_EMPLOYED`,
    and the called employee must not be the steward who filed the grievance, or it is rejected
    with `ERR_ADVOCATE_WITNESS_CONFLICT` — the union's advocate does not also become the
    union's evidence."

    Design: Corner/errors/witness_eligibility_and_award_overpayment_rejections
    """
    ctx = _case_with_witness()
    discharged = add_employee(
        ctx, "discharged",
        full_name="Owen Diaz", employee_number="EMP-4",
        hire_date="2018-01-08T00:00:00Z", seniority_date="2018-01-08T00:00:00Z",
        hourly_rate_cents=2_800, classification="MAINTENANCE",
        supervisor_id=ctx["supervisor"]["id"], employment_status="TERMINATED",
    )

    advocate = api.create_witness_assignment(
        ctx["demand"]["id"],
        witness_assignment_payload(
            ctx["steward"]["id"], "2026-10-05T09:00:00Z", "2026-10-05T10:00:00Z"
        ),
        analyst_headers,
    )
    validate_error(advocate, ApiErrorId.ERR_ADVOCATE_WITNESS_CONFLICT.value)

    terminated = api.create_witness_assignment(
        ctx["demand"]["id"],
        witness_assignment_payload(
            discharged["id"], "2026-10-05T09:00:00Z", "2026-10-05T10:00:00Z"
        ),
        analyst_headers,
    )
    validate_error(terminated, ApiErrorId.ERR_WITNESS_NOT_EMPLOYED.value)

    eligible = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"],
        "2026-10-05T09:00:00Z", "2026-10-05T10:00:00Z", headers=analyst_headers,
    )
    assert eligible["release_hours"] == pytest.approx(2.5)
    assert eligible["release_cost_cents"] == 7_500


def test_a_payment_beyond_the_remaining_net_remedy_is_refused(api, analyst_headers):
    """PRD §3.8: "A payment larger than the award's remaining net remedy, meaning
    `net_remedy_cents` less `implemented_cents`, is rejected with `ERR_OVERPAYMENT`."

    Design: Corner/errors/witness_eligibility_and_award_overpayment_rejections
    """
    ctx = setup_split_award_case()
    assert ctx["award"]["net_remedy_cents"] == 165_141

    over = api.implement_award(
        ctx["award"]["id"], {"paid_cents": 165_142}, analyst_headers
    )
    validate_error(over, ApiErrorId.ERR_OVERPAYMENT.value)

    unchanged = validate_success(api.get_award(ctx["award"]["id"], analyst_headers), 200)
    assert unchanged["implemented_cents"] == 0

    exact = validate_success(
        api.implement_award(ctx["award"]["id"], {"paid_cents": 165_141}, analyst_headers), 200
    )
    assert exact["status"] == "IMPLEMENTED"
    assert read_grievance(ctx["grievance"]["id"])["status"] == "CLOSED"


def _case_with_confirmed_witness(slot_start, slot_end):
    ctx = _case_with_witness()
    ctx["assignment"] = call_witness(
        ctx["demand"]["id"], ctx["witness"]["id"], slot_start, slot_end,
    )
    ctx["assignment"] = confirm_witness(ctx["assignment"]["id"])
    schedule_hearing(ctx["demand"]["id"])
    file_prep_through_briefs(ctx["demand"]["id"], exhibit_count=6)
    set_clock("2026-10-07T00:00:00Z")
    return ctx


def test_a_witness_inside_the_hearing_window_is_recorded_as_having_testified(api, analyst_headers):
    """PRD §3.8: "Every witness assignment on the demand standing at `CONFIRMED` whose slot
    lies inside the hearing window — that is, with `slot_start_at` at or after
    `hearing_start_at` and `slot_end_at` at or before `hearing_end_at` — moves to
    `TESTIFIED`, and its release-time cost entry stays posted."

    Design: Corner/state_machines/in_window_confirmed_witness_becomes_testified_and_keeps_its_release_cost
    """
    ctx = _case_with_confirmed_witness("2026-10-05T10:00:00Z", "2026-10-05T12:00:00Z")
    assert ctx["assignment"]["release_hours"] == pytest.approx(3.5)
    assert ctx["assignment"]["release_cost_cents"] == 10_500

    before_award = validate_success(
        api.get_arbitration_demand(ctx["demand"]["id"], analyst_headers), 200
    )
    assert before_award["readiness_score"] == 100

    record_award(ctx["demand"]["id"], outcome="DENIED")

    rows, _ = validate_paginated(
        api.list_demand_witness_assignments(ctx["demand"]["id"], analyst_headers)
    )
    assert rows[0]["status"] == "TESTIFIED"

    entries, _ = validate_paginated(
        api.list_cost_entries(
            ctx["grievance"]["id"], analyst_headers, params={"category": "RELEASE_TIME"}
        )
    )
    assert entries[0]["status"] == "POSTED"


def test_the_testified_witness_keeps_their_release_hours_and_the_case_keeps_the_cost(
    api, analyst_headers
):
    """PRD §3.9: "First, the base total is the sum of `amount_cents` over the grievance's
    `POSTED` entries only, irrespective of category or origin; voided entries contribute
    nothing to any output."
    PRD §3.1: "Each person also reports the supervisor scorecard of §3.9 —
    `open_grievance_count`, `closed_grievance_count`, `sustained_against_count` and
    `adverse_rate_bps` — plus `witness_release_hours_ytd`, the release hours accumulated
    across every case where their assignment stands at `CONFIRMED` or `TESTIFIED`."

    Design: Corner/state_machines/in_window_confirmed_witness_becomes_testified_and_keeps_its_release_cost
    """
    ctx = _case_with_confirmed_witness("2026-10-05T10:00:00Z", "2026-10-05T12:00:00Z")
    record_award(ctx["demand"]["id"], outcome="DENIED")

    grievance = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(grievance, total=426_500, union=210_500, employer=216_000)

    witness = validate_success(api.get_employee(ctx["witness"]["id"], analyst_headers), 200)
    assert witness["witness_release_hours_ytd"] == pytest.approx(3.5)


def test_a_witness_outside_the_hearing_window_becomes_a_no_show(api, analyst_headers):
    """PRD §3.8: "Every assignment standing at `CONFIRMED` whose slot lies wholly or partly
    outside that window moves to `NO_SHOW`, and because of that its release-time cost entry —
    the one identified by `release_cost_entry_id` — is transitioned from `POSTED` to `VOIDED`
    with a null `voided_by_user_id`, which re-derives the grievance's cost allocation and
    drops the witness's `witness_release_hours_ytd` back."

    Design: Corner/state_machines/confirmed_witness_outside_hearing_window_becomes_no_show_and_voids_release_cost
    """
    ctx = _case_with_confirmed_witness("2026-10-09T09:00:00Z", "2026-10-09T11:00:00Z")
    assert ctx["assignment"]["release_cost_cents"] == 10_500

    before = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(before, total=426_500, union=210_500, employer=216_000)

    record_award(ctx["demand"]["id"], outcome="DENIED")

    rows, _ = validate_paginated(
        api.list_demand_witness_assignments(ctx["demand"]["id"], analyst_headers)
    )
    assert rows[0]["status"] == "NO_SHOW"

    entries, _ = validate_paginated(
        api.list_cost_entries(
            ctx["grievance"]["id"], analyst_headers, params={"category": "RELEASE_TIME"}
        )
    )
    assert entries[0]["id"] == ctx["assignment"]["release_cost_entry_id"]
    assert entries[0]["status"] == "VOIDED"
    assert entries[0]["voided_by_user_id"] is None, "a cascade void records no operator"


def test_the_no_show_rolls_the_case_cost_and_the_release_counter_back(api, analyst_headers):
    """PRD §3.9: "A void must restore the case's cost figures to their **exact** pre-posting
    values, which is only true if voided entries are excluded from the allocation input set
    entirely rather than being offset by a compensating charge."
    PRD §3.8: "When `net_remedy_cents` is exactly 0 **and** `reinstatement_ordered` is false,
    there is nothing to implement: the award goes straight from `ISSUED` to `IMPLEMENTED` and
    the grievance is moved to `CLOSED` within that same request."

    Design: Corner/state_machines/confirmed_witness_outside_hearing_window_becomes_no_show_and_voids_release_cost
    """
    ctx = _case_with_confirmed_witness("2026-10-09T09:00:00Z", "2026-10-09T11:00:00Z")
    award = record_award(ctx["demand"]["id"], outcome="DENIED")

    grievance = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(grievance, total=416_000, union=200_000, employer=216_000)
    assert grievance["status"] == "CLOSED"

    witness = validate_success(api.get_employee(ctx["witness"]["id"], analyst_headers), 200)
    assert witness["witness_release_hours_ytd"] == pytest.approx(0.0)

    assert award["net_remedy_cents"] == 0
    assert award["status"] == "IMPLEMENTED"

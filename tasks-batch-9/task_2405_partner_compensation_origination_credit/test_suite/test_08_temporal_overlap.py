"""Contended resources over time: half-open credit windows on a matter,
discrete draw-period buckets on an award, and buffered service windows."""

from test_helpers import (
    ApiErrorId,
    adjudicate_claim_payload,
    advance_cycle,
    allocate_origination_credit,
    approx2,
    create_contribution_record_payload,
    create_credit_arbiter,
    create_cycle,
    create_matter,
    create_non_billable_record,
    create_partner,
    draw_ledger,
    draw_run_payload,
    effectuate_transition,
    file_claim,
    find_allocation,
    get_success_data,
    make_credit_arbiter_headers,
    make_cycle_admin_headers,
    matter_allocations,
    matter_version,
    notice_of_departure_payload,
    pay_draw,
    post_financials,
    read_award,
    read_claim,
    read_matter,
    read_partner,
    setup_published_discretionary_award,
    submit_claim,
    validate_error,
)


def _fully_originated_matter_with_a_rival_claim(api):
    """One matter whose whole origination capacity is held by A from
    2026-01-15 onwards, with a second partner's 30.00 claim awaiting decision."""
    cycle = create_cycle(api)
    holder = create_partner(api, full_name="Ada Origin", compensation_model="FORMULA")
    rival = create_partner(
        api,
        full_name="Ben Counter",
        compensation_model="FORMULA",
        admission_year=2011,
    )
    arbiter = create_credit_arbiter(api, full_name="Rex Arbiter", practice_group="REGULATORY")
    matter = create_matter(
        api,
        billing_attorney_id=holder["id"],
        responsible_attorney_id=holder["id"],
        client_key="CLI-W1",
        client_display_name="Window Works",
    )
    post_financials(
        api,
        matter["id"],
        billed_delta_cents=400_000,
        collected_delta_cents=400_000,
        direct_cost_delta_cents=0,
    )
    allocate_origination_credit(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=holder["id"],
        arbiter_id=arbiter["id"],
        approved_pct=100.00,
    )
    rival_claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=rival["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=30.00,
        narrative="I made the introduction that produced this client.",
    )
    submit_claim(api, rival_claim["id"], rival["id"])
    return {
        "cycle": cycle,
        "holder": holder,
        "rival": rival,
        "arbiter": arbiter,
        "matter": matter,
        "rival_claim": rival_claim,
    }


def test_a_thirty_point_award_over_an_occupied_window_is_refused(api):
    """PRD 3.4: "The 100.00 percent ceiling on origination credit is an
    interval-overlap constraint rather than a simple sum. Only allocations whose
    `credit_role` is `ORIGINATING` participate, and their `credit_pct` values are
    summed across every set of half-open validity windows that overlap in time; if
    any such overlapping set would exceed 100.00 on a matter, the write that would
    create it is refused with `ERR_CREDIT_INTERVAL_OVERSUBSCRIBED`."

    Design: Difficulty/resource_temporal_overlap/originating_credit_aggregate_capacity_over_open_ended_windows
    """
    scenario = _fully_originated_matter_with_a_rival_claim(api)
    matter_id = scenario["matter"]["id"]
    assert read_matter(api, matter_id)["origination_pct_assigned"] == approx2(100.00)

    response = api.adjudicate_credit_claim(
        scenario["rival_claim"]["id"],
        adjudicate_claim_payload("ALLOCATE", matter_version(api, matter_id), approved_pct=30.00),
        make_credit_arbiter_headers(scenario["arbiter"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CREDIT_INTERVAL_OVERSUBSCRIBED.value, 409)

    assert read_claim(api, scenario["rival_claim"]["id"])["state"] == "SUBMITTED"
    rows = matter_allocations(api, matter_id, state="ACTIVE")
    assert [
        row
        for row in rows
        if row["credit_role"] == "ORIGINATING" and row["partner_id"] == scenario["rival"]["id"]
    ] == []
    assert read_matter(api, matter_id)["origination_pct_assigned"] == approx2(100.00)


def test_two_hundred_point_allocations_coexist_when_their_windows_only_touch(api):
    """PRD 3.4: "Two windows that merely share an endpoint do not overlap, which
    is precisely why a transferred allocation ending on the successor's start date
    coexists with it."

    Design: Difficulty/resource_temporal_overlap/originating_credit_aggregate_capacity_over_open_ended_windows
    """
    scenario = _fully_originated_matter_with_a_rival_claim(api)
    matter_id = scenario["matter"]["id"]
    holder_id = scenario["holder"]["id"]
    rival_id = scenario["rival"]["id"]
    admin = make_cycle_admin_headers()
    get_success_data(
        api.notice_of_departure(holder_id, notice_of_departure_payload("2026-12-31"), admin)
    )
    transitions = get_success_data(
        api.list_credit_transitions(admin, {"departing_partner_id": holder_id})
    )
    transition = next(row for row in transitions if row["matter_id"] == matter_id)

    effective = effectuate_transition(
        api,
        transition_id=transition["id"],
        successor_partner_id=rival_id,
        effective_on="2026-09-01",
        matter_id=matter_id,
    )
    assert effective["state"] == "EFFECTIVE"

    rows = matter_allocations(api, matter_id)
    old_row = find_allocation(rows, "ORIGINATING", holder_id)
    new_row = find_allocation(rows, "ORIGINATING", rival_id)
    assert old_row["state"] == "TRANSFERRED"
    assert old_row["credit_pct"] == approx2(100.00)
    assert old_row["credit_from"] == "2026-01-15"
    assert old_row["credit_through"] == "2026-09-01"
    assert new_row["state"] == "ACTIVE"
    assert new_row["credit_pct"] == approx2(100.00)
    assert new_row["credit_from"] == "2026-09-01"
    assert new_row["credit_through"] is None
    assert old_row["credit_through"] == new_row["credit_from"]
    assert read_matter(api, matter_id)["origination_pct_assigned"] == approx2(100.00)


def test_the_same_draw_month_cannot_be_paid_twice(api):
    """PRD 3.9: "Three conditions guard it: the award's `award_state` must be
    `PUBLISHED`, and the award's cycle must be in `AWARDS_PUBLISHED` or
    `TRUE_UP_OPEN` — either failure is `ERR_AWARD_NOT_DRAWABLE` — and no
    un-reversed ledger row of kind `SCHEDULED_DRAW` may already exist on this
    award for that pairing of year and month, a collision being
    `ERR_DRAW_PERIOD_ALREADY_PAID`."

    Design: Difficulty/resource_temporal_overlap/draw_period_bucket_equality_ignores_interval_geometry
    """
    bundle = setup_published_discretionary_award(api)
    award_id = bundle["award"]["id"]
    assert bundle["award"]["draw_schedule_monthly_cents"] == 1_333_333

    first = pay_draw(api, award_id, period_year=2026, period_month=1)
    assert first["draw_paid_cents"] == 1_333_333

    response = api.draw_run(award_id, draw_run_payload(2026, 1), make_cycle_admin_headers())
    validate_error(response, ApiErrorId.ERR_DRAW_PERIOD_ALREADY_PAID.value, 409)
    assert len(draw_ledger(api, award_id)) == 1

    second = pay_draw(api, award_id, period_year=2026, period_month=2)
    assert second["draw_paid_cents"] == 2_666_666
    assert len(draw_ledger(api, award_id)) == 2


def test_a_reversed_draw_releases_its_period_bucket(api):
    """PRD 3.8: "each reversed scheduled draw has its `reversed` flag set to true,
    and a reversed draw no longer occupies its period bucket."

    Design: Difficulty/resource_temporal_overlap/draw_period_bucket_equality_ignores_interval_geometry
    """
    bundle = setup_published_discretionary_award(api)
    award_id = bundle["award"]["id"]
    cycle_id = bundle["cycle"]["id"]
    pay_draw(api, award_id, period_year=2026, period_month=1)
    pay_draw(api, award_id, period_year=2026, period_month=2)

    reopened = advance_cycle(api, cycle_id, "DELIBERATION")
    assert reopened["reopen_count"] == 1
    reversals = [row for row in draw_ledger(api, award_id) if row["kind"] == "DRAW_REVERSAL"]
    assert [row["amount_cents"] for row in reversals] == [-1_333_333, -1_333_333]
    assert all(
        row["reversed"] is True
        for row in draw_ledger(api, award_id)
        if row["kind"] == "SCHEDULED_DRAW"
    )

    advance_cycle(api, cycle_id, "AWARDS_PUBLISHED")
    reused = pay_draw(api, award_id, period_year=2026, period_month=1)

    assert reused["draw_paid_cents"] == 1_333_333
    assert len(draw_ledger(api, award_id)) == 5
    assert read_award(api, award_id)["reconsideration_count"] == 1


def _one_pro_bono_window_in_march(api):
    """A single unverified PRO_BONO record covering 2026-03-01 to 2026-03-31."""
    cycle = create_cycle(api)
    partner = create_partner(
        api,
        full_name="Pia Probono",
        practice_group="REGULATORY",
        compensation_model="FORMULA",
        admission_year=2015,
    )
    record = create_non_billable_record(
        api,
        partner_id=partner["id"],
        cycle_id=cycle["id"],
        category="PRO_BONO",
        hours=40.00,
        service_period_start="2026-03-01",
        service_period_end="2026-03-31",
    )
    return {"cycle": cycle, "partner": partner, "record": record}


def test_a_one_day_gap_between_pro_bono_windows_is_too_small(api):
    """PRD 3.3: "For any single pairing of `partner_id` and `category`, two
    non-billable closed service windows must be separated by more than one
    calendar day: a window that overlaps an existing one, merely touches it end to
    start, or leaves a gap of only one day, is rejected with
    `ERR_SERVICE_PERIOD_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/non_billable_service_windows_require_more_than_one_day_gap
    """
    scenario = _one_pro_bono_window_in_march(api)
    admin = make_cycle_admin_headers()

    response = api.create_contribution_record(
        create_contribution_record_payload(
            partner_id=scenario["partner"]["id"],
            cycle_id=scenario["cycle"]["id"],
            kind="NON_BILLABLE",
            category="PRO_BONO",
            hours=30.00,
            standard_rate_cents=0,
            service_period_start="2026-04-01",
            service_period_end="2026-04-30",
        ),
        admin,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_PERIOD_BUFFER_VIOLATION.value, 409)
    assert len(get_success_data(api.list_contribution_records(admin))) == 1

    # A window well clear of the March one is accepted. The exact first accepted
    # start date is not pinned by PRD (it says only "separated by more than one
    # calendar day"), so this asserts a separation both readings admit.
    accepted = create_non_billable_record(
        api,
        partner_id=scenario["partner"]["id"],
        cycle_id=scenario["cycle"]["id"],
        category="PRO_BONO",
        hours=30.00,
        service_period_start="2026-04-05",
        service_period_end="2026-04-30",
    )
    assert accepted["service_period_start"] == "2026-04-05"
    assert len(get_success_data(api.list_contribution_records(admin))) == 2


def test_the_buffer_is_keyed_per_category_not_per_partner(api):
    """PRD 3.3: "Non-billable records are held apart in time to stop the same
    firm-building week being booked twice under different guises."

    Design: Difficulty/resource_temporal_overlap/non_billable_service_windows_require_more_than_one_day_gap
    """
    scenario = _one_pro_bono_window_in_march(api)
    partner_id = scenario["partner"]["id"]

    recruiting = create_non_billable_record(
        api,
        partner_id=partner_id,
        cycle_id=scenario["cycle"]["id"],
        category="RECRUITING",
        hours=20.00,
        service_period_start="2026-04-01",
        service_period_end="2026-04-30",
    )
    assert recruiting["category"] == "RECRUITING"
    assert recruiting["service_period_start"] == "2026-04-01"
    assert recruiting["service_period_end"] == "2026-04-30"
    assert recruiting["standard_value_cents"] == 0
    assert scenario["record"]["standard_value_cents"] == 0
    assert scenario["record"]["verified"] is False
    assert read_partner(api, partner_id)["non_billable_points"] == approx2(0.00)

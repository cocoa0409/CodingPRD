"""Endpoint-level corners: the startup clock, the checkpoint, the reverse reads and correction.

Every test here drives one endpoint of the API described in the PRD and pins an
observable that only that endpoint produces: the instant the logical clock holds
before any client touches it, the pinned order of the nightly checkpoint's five
steps, the two idempotency windows the checkpoint keeps, the two different
orderings the two reverse-reachability reads of a waitlist entry use, the derived
columns a care-unit list computes at read time, and the target-status gate on
opening a correcting per diem claim.

The server is restarted before every test, so each test builds its own world and
starts from an empty database with the logical clock at its documented starting
instant.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLAIM_CENSUS_EMPTY,
    ERR_CLAIM_MONTH_NOT_CLOSED,
    ERR_CLAIM_STATE_INVALID,
    ERR_INVALID_REQUEST,
)
from test_helpers.assertions import assert_census_counters, assert_fields


def test_startup_clock_default_gates_claim_month_closure(api, admin_headers, bom_headers):
    """The clock's untouched startup value is what the claim-closure rule sees.

    Nothing sets the clock before the two submissions below, so a 2026-08 claim is
    still inside the open current month and dies on the closure rung, while a
    2026-07 claim clears that rung and dies one rung later on its empty census.
    Moving the clock into September then lets the August claim reach the same
    census rung, which shows the closure verdict tracked the logical clock rather
    than real time.

    Per the PRD: "Before any client sets it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Per the PRD: "The `claim_month` must be strictly earlier than the month of the
    current logical clock, because the census month must be closed, or
    `ERR_CLAIM_MONTH_NOT_CLOSED` (HTTP 409) — a claim for the current month is
    never submittable however complete it looks."

    Per the PRD: "Finally the claim must not be empty:
    `census_reported_resident_count` must be at least 1 and `billable_day_count`
    at least 1, or `ERR_CLAIM_CENSUS_EMPTY` (HTTP 409)."

    Design: Corner/endpoints/endpoint_startup_clock_default_gates_claim_month_closure
    """
    home = validate_success(
        api.create_veterans_home(
            f.veterans_home_payload(
                name="Ashfield State Veterans Home",
                recognition_effective_date="2026-06-01",
            ),
            admin_headers,
        ),
        201,
    )
    assert home["recognition_status"] == "RECOGNIZED"
    unit = validate_success(
        api.create_care_unit(
            home["id"],
            f.care_unit_payload("NURSING", 2, 0, unit_name="Nursing A"),
            admin_headers,
        ),
        201,
    )

    # The very first observation of the clock in this test: a checkpoint reports it.
    first_run = get_success_data(api.census_run(f.census_run_payload("2026-07-31"), admin_headers))
    assert first_run["current_utc"].startswith("2026-08-01T00:00:00"), (
        f"expected the startup clock at 2026-08-01T00:00:00Z, got {first_run['current_utc']!r}"
    )
    assert first_run["generated_census_day_count"] == 0

    august = validate_success(
        api.create_per_diem_claim(
            f.per_diem_claim_payload(home["id"], unit["id"], "2026-08", "AUDITED_BASIS"),
            bom_headers,
        ),
        201,
    )
    validate_error(
        api.submit_per_diem_claim(august["id"], {}, bom_headers),
        ERR_CLAIM_MONTH_NOT_CLOSED,
        409,
    )

    july = validate_success(
        api.create_per_diem_claim(
            f.per_diem_claim_payload(home["id"], unit["id"], "2026-07", "AUDITED_BASIS"),
            bom_headers,
        ),
        201,
    )
    validate_error(
        api.submit_per_diem_claim(july["id"], {}, bom_headers),
        ERR_CLAIM_CENSUS_EMPTY,
        409,
    )

    moved = get_success_data(
        api.set_clock(f.clock_payload("2026-09-15T06:00:00Z"), admin_headers)
    )
    assert moved["current_utc"].startswith("2026-09-15T06:00:00")
    validate_error(
        api.submit_per_diem_claim(august["id"], {}, bom_headers),
        ERR_CLAIM_CENSUS_EMPTY,
        409,
    )


def _single_queued_applicant(api, licensed_bed_count=1):
    """One eligible applicant holding one ACTIVE entry on one OPEN nursing unit."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api, name="Birchwood State Veterans Home")
    unit = fx.create_unit(
        api,
        home["id"],
        unit_name="Nursing A",
        care_level="NURSING",
        licensed_bed_count=licensed_bed_count,
        out_of_service_bed_count=0,
    )
    applicant = fx.create_applicant(
        api,
        home["id"],
        full_name="Greta Lindahl",
        date_of_birth="1945-02-02",
        state_residency_years=8,
        application_received_date="2026-08-01",
    )
    fx.determine_eligibility(api, applicant["id"])
    entry = fx.create_waitlist_entry(api, applicant["id"], unit["id"])
    assessment = fx.create_assessment(api, applicant["id"], assessment_date="2026-08-01")
    fx.submit_assessment(api, assessment["id"])
    return home, unit, applicant, entry


def test_census_run_offers_before_it_expires_elapsed_offers(api, coordinator_headers):
    """Within one checkpoint the offer step runs before the decline step.

    The first run offers the only bed to the only candidate. The run taken after
    the seven-day window has elapsed therefore cannot re-offer the same entry: it
    reaches the offer step while the entry is still OFFERED, offers nothing, and
    only then declines the lapsed offer, leaving the entry sitting ACTIVE with the
    decline counted. The next run finds it ACTIVE again and offers it afresh, seven
    days from the new clock.

    Per the PRD: "Priority scores are recomputed for every applicant holding an
    `ACTIVE` or `OFFERED` entry on a touched unit, so the tenure term advances with
    the clock; offers are issued to the highest-ranked `ACTIVE` entry per free bed
    on each `OPEN` unit with `offer_expires_at` set seven days ahead of the clock;
    elapsed offers are then declined and exhausted applicants expired, all as
    described in §3.3; and `waitlist_active_count` and `queue_position` are
    recomputed on every touched unit."

    Per the PRD: "When the logical clock has moved strictly past an entry's
    `offer_expires_at`, that `OFFERED` entry reverts to `ACTIVE` with
    `offer_expires_at` cleared to null, the owning applicant's
    `declined_offer_count` increases by 1, the applicant's `priority_score` is
    recomputed — picking up the additional twenty-five-point penalty, still floored
    at the class base — every `ACTIVE` or `OFFERED` entry on that unit has its
    `queue_position` recomputed, and the entry's `version` increments."

    Design: Corner/endpoints/endpoint_census_run_offers_before_expiring_offers
    """
    home, unit, applicant, entry = _single_queued_applicant(api, licensed_bed_count=1)
    assert unit["available_bed_count"] == 1
    assert unit["operational_posture"] == "OPEN"
    assert entry["status"] == "ACTIVE"

    first = fx.census_run(api, "2026-08-01", home["id"])
    assert first["offered_waitlist_entry_count"] == 1
    assert first["expired_offer_count"] == 0

    offered, offered_meta = validate_paginated(
        api.list_unit_waitlist_entries(
            unit["id"], coordinator_headers, {"status": "OFFERED", "limit": 10}
        )
    )
    assert offered_meta["total_count"] == 1
    assert offered[0]["id"] == entry["id"]
    assert offered[0]["queue_position"] == 1
    assert offered[0]["offer_expires_at"].startswith("2026-08-08T00:00:00"), (
        f"expected the offer window to close 2026-08-08, got {offered[0]['offer_expires_at']!r}"
    )

    # The clock moves strictly past the window, so this run must decline the offer.
    fx.set_clock(api, "2026-08-09T00:00:00Z")
    lapsing = fx.census_run(api, "2026-08-09", home["id"])
    assert lapsing["offered_waitlist_entry_count"] == 0, (
        "the offer step runs before the decline step, so the lapsing run offers nothing"
    )
    assert lapsing["expired_offer_count"] == 1

    rows, _meta = validate_paginated(
        api.list_applicant_waitlist_entries(applicant["id"], coordinator_headers, {"limit": 10})
    )
    assert_fields(rows[0], status="ACTIVE", offer_expires_at=None)
    after_lapse = validate_success(api.get_applicant(applicant["id"], coordinator_headers))
    assert after_lapse["declined_offer_count"] == 1

    # Only the next run re-offers the bed, from the clock as it now stands.
    fx.set_clock(api, "2026-08-10T00:00:00Z")
    reoffering = fx.census_run(api, "2026-08-10", home["id"])
    assert reoffering["offered_waitlist_entry_count"] == 1
    assert reoffering["expired_offer_count"] == 0

    rows, _meta = validate_paginated(
        api.list_applicant_waitlist_entries(applicant["id"], coordinator_headers, {"limit": 10})
    )
    assert rows[0]["status"] == "OFFERED"
    assert rows[0]["offer_expires_at"].startswith("2026-08-17T00:00:00")
    after_reoffer = validate_success(api.get_applicant(applicant["id"], coordinator_headers))
    assert after_reoffer["declined_offer_count"] == 1, (
        "a fresh offer does not retract the earlier decline"
    )


def test_census_run_keeps_daily_and_monthly_idempotency_apart(api, bom_headers):
    """Census generation is idempotent per day; the allowance credit is per month.

    Four runs are taken over one resident: two on 2026-08-01, one on 2026-08-02 and
    one on 2026-09-01. The second August-1 run generates nothing because the day
    already has its row, and credits nothing because the month already has its
    allowance. The August-2 run generates one more row but still credits nothing.
    Only the September run credits again, so the ledger holds exactly two postings
    and twice the monthly allowance.

    Per the PRD: "At most one census day may exist per resident and `service_date`,
    so a second run with the same or an earlier `through_date` creates nothing at
    all — `window_start` has moved past `window_end` and the loop does not execute."

    Per the PRD: "This is pinned to once per resident per calendar month: a resident
    who already holds a `PNA_CREDIT` row whose `effective_date` falls in the
    calendar month of `through_date` is skipped silently and is **not** counted in
    `pna_credited_resident_count`, so re-running the checkpoint on a later date in
    the same month never double-credits."

    Per the PRD: "A resident whose governing cost share is exactly zero is neither
    debited nor counted as skipped, so such a resident appears in neither counter."

    Design: Corner/endpoints/endpoint_census_run_monthly_postings_are_idempotent_per_month
    """
    scenario = fx.admitted_resident(
        api,
        admission_date="2026-08-01",
        care_level="NURSING",
        licensed_bed_count=2,
        home_overrides={"name": "Cedar Ridge State Veterans Home"},
    )
    home = fx.read_home(api, scenario.home_id)
    assert home["personal_needs_allowance_monthly_cents"] == 9000
    fresh = fx.read_resident(api, scenario.resident_id)
    assert_fields(fresh, monthly_cost_share_cents=0, trust_fund_balance_cents=0)

    first = fx.census_run(api, "2026-08-01", scenario.home_id)
    assert_census_counters(
        first,
        generated_census_day_count=1,
        pna_credited_resident_count=1,
        cost_share_debited_resident_count=0,
        skipped_cost_share_debit_count=0,
        review_due_care_plan_count=0,
    )

    repeat = fx.census_run(api, "2026-08-01", scenario.home_id)
    assert_census_counters(
        repeat,
        generated_census_day_count=0,
        pna_credited_resident_count=0,
        cost_share_debited_resident_count=0,
        skipped_cost_share_debit_count=0,
    )
    after_repeat = fx.read_resident(api, scenario.resident_id)
    assert_fields(
        after_repeat, trust_fund_balance_cents=9000, last_census_date="2026-08-01"
    )

    fx.set_clock(api, "2026-08-02T00:00:00Z")
    next_day = fx.census_run(api, "2026-08-02", scenario.home_id)
    assert next_day["generated_census_day_count"] == 1
    assert next_day["pna_credited_resident_count"] == 0, (
        "a second run in the same calendar month never credits the allowance again"
    )
    after_next_day = fx.read_resident(api, scenario.resident_id)
    assert_fields(
        after_next_day, trust_fund_balance_cents=9000, last_census_date="2026-08-02"
    )

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    new_month = fx.census_run(api, "2026-09-01", scenario.home_id)
    assert new_month["generated_census_day_count"] == 30, (
        "the window reopens the day after the last census date and closes on the through date"
    )
    assert new_month["pna_credited_resident_count"] == 1
    after_new_month = fx.read_resident(api, scenario.resident_id)
    assert_fields(
        after_new_month, trust_fund_balance_cents=18000, last_census_date="2026-09-01"
    )

    _days, day_meta = validate_paginated(
        api.list_census_days(bom_headers, {"resident_id": scenario.resident_id, "limit": 1})
    )
    assert day_meta["total_count"] == 32

    _txns, txn_meta = validate_paginated(
        api.list_trust_fund_transactions(
            bom_headers, {"resident_id": scenario.resident_id, "limit": 10}
        )
    )
    assert txn_meta["total_count"] == 2


def test_waitlist_entry_is_reachable_from_both_parents_in_different_orders(
    api, coordinator_headers
):
    """The two reverse reads of a waitlist entry use two different orderings.

    Ada queues on Nursing A and then on Nursing B; Bo has already queued on
    Nursing B before her. Read from the applicant, Ada's two entries come back in
    the order she joined the queues, so the Nursing A entry leads. Read from
    Nursing B, the same pair comes back by queue position, so Ada's entry leads
    Bo's on score even though Bo's row was created first. No offer exists on either
    unit, because only the nightly checkpoint issues offers.

    Per the PRD: "Nesting in the URL hierarchy exists in this system only as a
    reverse-reachability read channel and as a creation-in-parent-context write
    channel."

    Per the PRD: "Several collections in this system do declare their own ordering,
    because operators read them in domain order rather than in insertion order:
    veterans homes come back newest first by `created_at` descending and then by
    `name` ascending; a home's care units by `care_level` ascending then
    `unit_name` ascending; a home's applicants by `application_received_date`
    ascending then `created_at` ascending; a unit's waitlist entries by
    `queue_position` ascending; an applicant's waitlist entries by `listed_at`
    ascending then `created_at` ascending; an applicant's clinical assessments by
    `assessment_date` descending then `created_at` descending; residents by
    `admission_date` ascending then `created_at` ascending; income records by
    `effective_month` ascending then `income_type` ascending; cost-share
    determinations by `effective_month` ascending then `created_at` ascending; care
    plans by `plan_date` ascending then `revision_number` ascending; census days by
    `service_date` ascending then `created_at` ascending; per diem claims by
    `claim_month` ascending then `correction_generation` ascending then `created_at`
    ascending; and trust fund transactions by `effective_date` ascending then
    `created_at` ascending."

    Per the PRD: "The candidate set is every entry on that unit whose status is
    `ACTIVE` or `OFFERED`; those candidates are ranked by the owning applicant's
    `priority_score` descending, then by the applicant's
    `application_received_date` ascending, then by the entry's own `created_at`
    ascending, and `queue_position` is the one-based index in that ranking."

    Per the PRD: "An applicant whose VA `service_connected_disability_pct` is at
    least 70, or whose `nursing_care_for_service_connected` flag is true, is
    `CLASS_1`."

    Per the PRD: "The **class base** contributes 1,000 points for `CLASS_1`, 700 for
    `CLASS_2`, 400 for `CLASS_3` and 100 for `CLASS_4`."

    Per the PRD: "The **disability term** contributes three points for each
    percentage point of `service_connected_disability_pct`, with the percentage
    first capped at 100."

    Per the PRD: "The **residency term** contributes five points for each completed
    year of `state_residency_years`, with the year count first capped at twenty
    years — so residency stops earning after two decades, at 100 points."

    Per the PRD: "Bed offers are issued only by the nightly checkpoint, never by the
    operation that freed the bed."

    Design: Corner/endpoints/endpoint_waitlist_entry_reachable_from_both_parents
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api, name="Dunmore State Veterans Home")
    unit_a = fx.create_unit(
        api,
        home["id"],
        unit_name="Nursing A",
        care_level="NURSING",
        licensed_bed_count=2,
        out_of_service_bed_count=0,
    )
    unit_b = fx.create_unit(
        api,
        home["id"],
        unit_name="Nursing B",
        care_level="NURSING",
        licensed_bed_count=2,
        out_of_service_bed_count=0,
    )

    ada = fx.create_applicant(
        api,
        home["id"],
        full_name="Ada Sorensen",
        date_of_birth="1944-06-06",
        service_days=900,
        discharge_character="HONORABLE",
        wartime_service=True,
        service_connected_disability_pct=80,
        nursing_care_for_service_connected=False,
        state_residency_years=8,
        requested_care_level="NURSING",
        application_received_date="2026-08-01",
    )
    ada_decided = fx.determine_eligibility(api, ada["id"])
    # 1000 class base + 3 * 80 disability + 5 * 8 residency, no acuity and no tenure.
    assert_fields(ada_decided, priority_class="CLASS_1", priority_score=1280)

    bo = fx.create_applicant(
        api,
        home["id"],
        full_name="Bo Iversen",
        date_of_birth="1955-07-07",
        service_days=400,
        discharge_character="HONORABLE",
        wartime_service=False,
        service_connected_disability_pct=0,
        nursing_care_for_service_connected=False,
        state_residency_years=1,
        requested_care_level="NURSING",
        application_received_date="2026-08-01",
    )
    bo_decided = fx.determine_eligibility(api, bo["id"])
    # 100 class base + 5 * 1 residency.
    assert_fields(bo_decided, priority_class="CLASS_4", priority_score=105)

    bo_on_b = fx.create_waitlist_entry(api, bo["id"], unit_b["id"])
    ada_on_a = fx.create_waitlist_entry(api, ada["id"], unit_a["id"])
    ada_on_b = fx.create_waitlist_entry(api, ada["id"], unit_b["id"])

    ada_rows, ada_meta = validate_paginated(
        api.list_applicant_waitlist_entries(ada["id"], coordinator_headers, {"limit": 10})
    )
    assert ada_meta["total_count"] == 2
    assert [row["id"] for row in ada_rows] == [ada_on_a["id"], ada_on_b["id"]]
    assert [row["care_unit_id"] for row in ada_rows] == [unit_a["id"], unit_b["id"]]

    a_rows, a_meta = validate_paginated(
        api.list_unit_waitlist_entries(unit_a["id"], coordinator_headers, {"limit": 10})
    )
    assert a_meta["total_count"] == 1
    assert_fields(
        a_rows[0],
        id=ada_on_a["id"],
        applicant_id=ada["id"],
        queue_position=1,
        status="ACTIVE",
    )

    b_rows, b_meta = validate_paginated(
        api.list_unit_waitlist_entries(unit_b["id"], coordinator_headers, {"limit": 10})
    )
    assert b_meta["total_count"] == 2
    assert [row["id"] for row in b_rows] == [ada_on_b["id"], bo_on_b["id"]], (
        "the unit-scoped read is ordered by queue position, not by insertion order"
    )
    assert [row["queue_position"] for row in b_rows] == [1, 2]

    _offered, offered_meta = validate_paginated(
        api.list_unit_waitlist_entries(
            unit_b["id"], coordinator_headers, {"status": "OFFERED", "limit": 10}
        )
    )
    assert offered_meta["total_count"] == 0

    assert validate_success(api.get_care_unit(unit_a["id"], coordinator_headers))[
        "waitlist_active_count"
    ] == 1
    assert validate_success(api.get_care_unit(unit_b["id"], coordinator_headers))[
        "waitlist_active_count"
    ] == 2


def test_care_unit_list_is_a_computed_read_with_filters(api, bom_headers):
    """The unit list derives its bed columns and posture at read time.

    Four units are created under one home and read back through the home's unit
    list. Every row carries the availability arithmetic, the posture derived from
    it and the federal rate for its own care level; the rows arrive by unit name
    within a care level; `total_count` counts the whole filtered collection rather
    than the page; a filter that matches nothing returns an empty page rather than
    an error; and a limit above the accepted maximum is refused on request shape
    instead of being clamped.

    Per the PRD: "For a care unit, `occupied_bed_count` is the number of residents
    assigned to that unit whose `occupancy_status` is `ADMITTED`; `held_bed_count`
    is the number assigned to that unit whose `occupancy_status` is `HOSPITALIZED`
    and whose `bed_hold_days_used` is still strictly below the thirty-day bed-hold
    ceiling; and `available_bed_count` is the unit's `licensed_bed_count` less its
    `out_of_service_bed_count`, less `occupied_bed_count`, less `held_bed_count`."

    Per the PRD: "Only a certified unit with at least one free bed is `OPEN`."

    Per the PRD: "`total_count` is the number of rows matching the request's filters
    across the whole collection, not the number of rows on the returned page, and
    `has_more` is true exactly when rows matching the filters remain beyond the
    returned page."

    Per the PRD: "A `limit` outside the range 1 through 100, or a negative `offset`,
    is a request-shape violation and is rejected with `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/endpoints/endpoint_care_unit_list_is_computed_read_with_filters
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api, name="Elmhurst State Veterans Home")
    alder = fx.create_unit(
        api,
        home["id"],
        unit_name="Alder",
        care_level="NURSING",
        licensed_bed_count=4,
        out_of_service_bed_count=1,
    )
    assert_fields(
        alder, available_bed_count=3, operational_posture="OPEN", per_diem_rate_cents=11857
    )
    birch = fx.create_unit(
        api,
        home["id"],
        unit_name="Birch",
        care_level="NURSING",
        licensed_bed_count=2,
        out_of_service_bed_count=0,
    )
    cedar = fx.create_unit(
        api,
        home["id"],
        unit_name="Cedar",
        care_level="NURSING",
        licensed_bed_count=3,
        out_of_service_bed_count=0,
    )
    dover = fx.create_unit(
        api,
        home["id"],
        unit_name="Dover",
        care_level="DOMICILIARY",
        licensed_bed_count=5,
        out_of_service_bed_count=0,
    )

    page_one, page_one_meta = validate_paginated(
        api.list_home_care_units(
            home["id"], bom_headers, {"care_level": "NURSING", "limit": 2, "offset": 0}
        )
    )
    assert page_one_meta["total_count"] == 3
    assert page_one_meta["has_more"] is True
    assert [row["id"] for row in page_one] == [alder["id"], birch["id"]]
    assert_fields(page_one[0], available_bed_count=3, operational_posture="OPEN")
    assert page_one[1]["available_bed_count"] == 2

    page_two, page_two_meta = validate_paginated(
        api.list_home_care_units(
            home["id"], bom_headers, {"care_level": "NURSING", "limit": 2, "offset": 2}
        )
    )
    assert page_two_meta["total_count"] == 3
    assert page_two_meta["has_more"] is False
    assert page_two_meta["offset"] == 2
    assert page_two[0]["id"] == cedar["id"]
    assert page_two[0]["available_bed_count"] == 3

    dom_rows, dom_meta = validate_paginated(
        api.list_home_care_units(
            home["id"], bom_headers, {"care_level": "DOMICILIARY", "limit": 10, "offset": 0}
        )
    )
    assert dom_meta["total_count"] == 1
    assert_fields(
        dom_rows[0], id=dover["id"], per_diem_rate_cents=5502, available_bed_count=5
    )

    _certified, certified_meta = validate_paginated(
        api.list_home_care_units(
            home["id"], bom_headers, {"certification_status": "CERTIFIED", "limit": 10, "offset": 0}
        )
    )
    assert certified_meta["total_count"] == 4
    assert certified_meta["has_more"] is False

    decertified, decertified_meta = validate_paginated(
        api.list_home_care_units(
            home["id"],
            bom_headers,
            {"certification_status": "DECERTIFIED", "limit": 10, "offset": 0},
        )
    )
    assert decertified == []
    assert decertified_meta["total_count"] == 0
    assert decertified_meta["has_more"] is False

    validate_error(
        api.list_home_care_units(home["id"], bom_headers, {"limit": 101}),
        ERR_INVALID_REQUEST,
        422,
    )


def test_correction_is_gated_on_the_target_claim_status(api, bom_headers):
    """Only a settled claim may be corrected, and the gate is on the target.

    One July claim is carried from DRAFT through SUBMITTED to PAID and a correction
    is attempted at each stop, always with the version the target itself last
    reported, so the version pin can never be what decides the answer. The DRAFT and
    the SUBMITTED target refuse; the PAID target yields a fresh DRAFT correction
    that inherits the month, the unit's basis, the census days and therefore the
    same amount; and that new DRAFT refuses to be corrected in its turn.

    Per the PRD: "A correcting claim may be opened only against a claim whose
    `status` is `PAID` or `REJECTED` — a `DRAFT` or `SUBMITTED` target yields
    `ERR_CLAIM_STATE_INVALID`, and a `VOID` one likewise — and the request must
    carry `expected_claim_version` matching the target's current `version`, or
    `ERR_CLAIM_VERSION_STALE` (HTTP 412)."

    Per the PRD: "The correction creates a fresh `DRAFT` claim whose
    `corrects_claim_id` names the target and whose `correction_generation` is the
    target's plus one, so a chain of corrections is self-describing."

    Design: Corner/endpoints/endpoint_correct_is_conditional_on_paid_or_rejected_target
    """
    scenario = fx.admitted_resident(
        api,
        admission_date="2026-07-01",
        application_date="2026-07-01",
        care_level="NURSING",
        licensed_bed_count=2,
        home_overrides={
            "name": "Fairholm State Veterans Home",
            "recognition_effective_date": "2026-06-01",
        },
    )
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    run = fx.census_run(api, "2026-07-31", scenario.home_id)
    assert run["generated_census_day_count"] == 31

    claim = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-07", "AUDITED_BASIS"), 201
    )
    assert_fields(claim, status="DRAFT", claim_amount_cents=367567)

    validate_error(
        api.correct_per_diem_claim(
            claim["id"], f.correction_payload(claim["version"], "too early"), bom_headers
        ),
        ERR_CLAIM_STATE_INVALID,
        409,
    )

    submitted = validate_success(fx.submit_claim(api, claim["id"]), 200)
    assert submitted["status"] == "SUBMITTED"
    validate_error(
        api.correct_per_diem_claim(
            claim["id"], f.correction_payload(submitted["version"], "still too early"), bom_headers
        ),
        ERR_CLAIM_STATE_INVALID,
        409,
    )

    paid = validate_success(fx.adjudicate_claim(api, claim["id"], "PAID", note="clean audit"), 200)
    assert_fields(paid, status="PAID", paid_amount_cents=367567)

    correction = validate_success(
        api.correct_per_diem_claim(
            claim["id"], f.correction_payload(paid["version"], "rate audit rerun"), bom_headers
        ),
        201,
    )
    assert_fields(
        correction,
        status="DRAFT",
        correction_generation=1,
        corrects_claim_id=claim["id"],
        claim_month="2026-07",
        claim_amount_cents=367567,
        basis="AUDITED_BASIS",
        adjudication_note="rate audit rerun",
    )

    validate_error(
        api.correct_per_diem_claim(
            correction["id"],
            f.correction_payload(correction["version"], "correcting the correction"),
            bom_headers,
        ),
        ERR_CLAIM_STATE_INVALID,
        409,
    )

    _taken_over, taken_over_meta = validate_paginated(
        api.list_census_days(bom_headers, {"per_diem_claim_id": correction["id"], "limit": 1})
    )
    assert taken_over_meta["total_count"] == 31

    _released, released_meta = validate_paginated(
        api.list_census_days(bom_headers, {"per_diem_claim_id": claim["id"], "limit": 1})
    )
    assert released_meta["total_count"] == 0

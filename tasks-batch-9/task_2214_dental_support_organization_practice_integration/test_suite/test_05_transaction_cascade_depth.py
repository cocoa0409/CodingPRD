"""Transaction-arc depth: the bounded diligence/repricing loop, the five-hop
close cascade that reaches the payer contract, and the departure cascade that
freezes a practice and unwinds its counters."""

import pytest

from test_helpers import (
    CLOCK_CLOSE_DAY,
    COUNSEL,
    LEAD,
    ApiErrorId,
    accept_offer,
    add_doctor_with_offer,
    advance_to_diligence,
    api_client,
    assert_affiliation,
    assert_doctor_employment,
    assert_practice,
    build_closed_deal_with_contract,
    build_deal_in_draft,
    build_scheduled_batch,
    create_payer_contract,
    get_success_data,
    make_agreement_effective_at,
    read_affiliation,
    read_conversion_vendor,
    read_employment,
    read_migration_batch,
    read_payer_contract,
    read_payer_enrollment,
    read_practice,
    separate_employment,
    sign_deal,
    submit_enrollment,
    validate_error,
    validate_paginated,
)

CLOSE_DATE = "2026-09-01T00:00:00Z"
CASCADE_ENROLLMENT_EFFECTIVE = "2026-11-30T00:00:00Z"
NON_COMPETE_END = "2028-09-01T00:00:00Z"
BATCH_WINDOW = ("2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z")

SECOND_DOCTOR = {
    "full_name": "Beto Alvarez",
    "npi": "1710000002",
    "license_number": "IL-DDS-5521",
    "license_state": "IL",
    "is_seller_owner": False,
}
SECOND_EMPLOYMENT = {
    "base_salary_monthly_cents": 1_700_000,
    "collections_pct_bps": 2800,
    "comp_model": "ANNUAL_TRUE_UP",
    "legacy_annual_comp_cents": 23_000_000,
    "post_close_term_months": 36,
    "non_compete_months": 18,
    "non_compete_radius_miles": 8,
}


def _reprice(affiliation_id, purchase_price_cents, earnout_pool_cents, note):
    return api_client.reprice_affiliation(
        affiliation_id,
        {
            "purchase_price_cents": purchase_price_cents,
            "earnout_pool_cents": earnout_pool_cents,
            "reprice_note": note,
        },
        COUNSEL,
    )


@pytest.fixture
def deal_with_two_repricings():
    """A file that has consumed both of its repricing rounds and re-opened."""
    ctx = build_deal_in_draft()
    advance_to_diligence(ctx["affiliation_id"])
    ctx["round_one"] = get_success_data(
        _reprice(
            ctx["affiliation_id"], 430_000_000, 95_000_000, "quality of earnings gap"
        )
    )
    advance_to_diligence(ctx["affiliation_id"])
    ctx["round_two"] = get_success_data(
        _reprice(
            ctx["affiliation_id"], 415_000_000, 100_000_000, "hygiene attrition found"
        )
    )
    advance_to_diligence(ctx["affiliation_id"])
    return ctx


def test_each_repricing_returns_the_file_to_draft_and_resizes_the_pool(
    deal_with_two_repricings
):
    """PRD §3.2: "Diligence sometimes goes badly, and the only path back is a **reprice**, which returns the file `DILIGENCE → DRAFT`."
    PRD §3.2: "Repricing overwrites `purchase_price_cents` and `earnout_pool_cents` with new figures, accepts an optional `reprice_note`, recomputes `earnout_unallocated_cents` against the new pool, and increments `repricing_round`."

    Design: Difficulty/non_linear_state_machine/affiliation_diligence_reprice_loop_bounded_at_two_rounds
    """
    first = deal_with_two_repricings["round_one"]
    assert_affiliation(first)
    assert first["status"] == "DRAFT"
    assert first["repricing_round"] == 1
    assert first["purchase_price_cents"] == 430_000_000
    assert first["earnout_pool_cents"] == 95_000_000
    assert first["earnout_unallocated_cents"] == 95_000_000

    second = deal_with_two_repricings["round_two"]
    assert second["status"] == "DRAFT"
    assert second["repricing_round"] == 2
    assert second["purchase_price_cents"] == 415_000_000
    assert second["earnout_pool_cents"] == 100_000_000
    assert second["earnout_unallocated_cents"] == 100_000_000
    assert second["version"] > first["version"]


def test_a_third_repricing_round_is_refused_and_writes_nothing(
    deal_with_two_repricings
):
    """PRD §3.2: "The loop terminates: at most two repricing rounds may be consumed, so a third attempt — one made while `repricing_round` already stands at 2 — is refused with `ERR_REPRICING_LIMIT_REACHED`."
    PRD §2.11: "The first check whose condition is violated determines the response, no later check is evaluated, and **no state change whatsoever is written** when any check fires."

    Design: Difficulty/non_linear_state_machine/affiliation_diligence_reprice_loop_bounded_at_two_rounds
    """
    ctx = deal_with_two_repricings
    validate_error(
        _reprice(
            ctx["affiliation_id"], 400_000_000, 105_000_000, "third bite refused"
        ),
        ApiErrorId.ERR_REPRICING_LIMIT_REACHED.value,
    )

    unchanged = read_affiliation(ctx["affiliation_id"])
    assert unchanged["status"] == "DILIGENCE"
    assert unchanged["repricing_round"] == 2
    assert unchanged["purchase_price_cents"] == 415_000_000
    assert unchanged["earnout_pool_cents"] == 100_000_000
    assert unchanged["earnout_unallocated_cents"] == 100_000_000


@pytest.fixture
def closed_deal_with_two_offers():
    """A close run at a practice where one of two offers had been accepted."""
    ctx = build_deal_in_draft(clock_utc=CLOCK_CLOSE_DAY)
    add_doctor_with_offer(
        ctx,
        ctx["practice_id"],
        doctor=SECOND_DOCTOR,
        employment=SECOND_EMPLOYMENT,
    )
    advance_to_diligence(ctx["affiliation_id"])
    sign_deal(ctx["affiliation_id"])
    make_agreement_effective_at(ctx["practice_id"])
    ctx["contract"] = create_payer_contract(ctx["practice_id"])
    ctx["contract_id"] = ctx["contract"]["id"]
    accept_offer(ctx["employment_id"], ctx["doctor_id"])
    ctx["closed"] = get_success_data(
        api_client.close_affiliation(
            ctx["affiliation_id"], LEAD, {"close_note": "funds flow released"}
        )
    )
    return ctx


def test_close_opens_the_measurement_period_and_affiliates_the_practice(
    closed_deal_with_two_offers
):
    """PRD §3.3: "**Hop one** touches the affiliation: `close_date` is stamped from the logical clock, `earnout_measurement_state` moves `NOT_OPEN → OPEN`, and the affiliation's `version` increments by one."
    PRD §3.3: "**Hop two** is caused by hop one. Every practice of the affiliation has its `affiliation_status` moved `PENDING → AFFILIATED`, its `integration_posture` recomputed by the ladder of §2.6 — which takes it out of `PRE_CLOSE` and, once the next hop supplies at least one active doctor, lands it at `STABILIZING`, the transition `PRE_CLOSE` → `STABILIZING` — and its `version` incremented by one."

    Design: Difficulty/transitive_cascade/affiliation_close_five_hop_cascade_to_payer_contract
    """
    closed = closed_deal_with_two_offers["closed"]
    assert_affiliation(closed)
    assert closed["status"] == "CLOSED"
    assert closed["close_date"] == CLOSE_DATE
    assert closed["earnout_measurement_state"] == "OPEN"

    practice = read_practice(closed_deal_with_two_offers["practice_id"])
    assert_practice(practice)
    assert practice["affiliation_status"] == "AFFILIATED"
    assert practice["integration_posture"] == "STABILIZING"


def test_accepted_offer_activates_while_the_unaccepted_one_lapses(
    closed_deal_with_two_offers
):
    """PRD §3.3: "Rows with `offer_accepted` true move `OFFERED → ACTIVE`, have `comp_effective_date` set to the affiliation's `close_date`, increase that practice's `active_doctor_count` by one, and have their own `version` incremented by one. Rows with `offer_accepted` false at the moment the cascade runs move `OFFERED → LAPSED`, leave `active_doctor_count` untouched, and likewise have their `version` incremented by one."
    PRD §3.3: "Both branches are written; neither is skipped."

    Design: Difficulty/transitive_cascade/affiliation_close_five_hop_cascade_to_payer_contract
    """
    ctx = closed_deal_with_two_offers
    active = read_employment(ctx["employment_id"])
    assert_doctor_employment(active)
    assert active["employment_status"] == "ACTIVE"
    assert active["offer_accepted"] is True
    assert active["comp_effective_date"] == CLOSE_DATE

    lapsed = read_employment(ctx["other_employment_id"])
    assert lapsed["employment_status"] == "LAPSED"
    assert lapsed["offer_accepted"] is False
    assert lapsed["comp_effective_date"] is None

    practice = read_practice(ctx["practice_id"])
    assert practice["active_doctor_count"] == 1
    assert practice["clinical_coverage_gap"] is False


def test_only_the_activated_doctor_gains_an_enrollment_and_the_contract_moves(
    closed_deal_with_two_offers
):
    """PRD §3.3: "For each employment row that has just become `ACTIVE`, one credentialing enrollment is created against every payer contract of that employment's practice whose `transition_state` is still `LEGACY`, processed in the payer contracts' `created_at` ascending order. Each created enrollment opens in `NOT_STARTED`, with its `effective_date` set to the affiliation's `close_date` plus the ninety-day credentialing lead time and its `term_date` left empty, meaning open-ended."
    PRD §3.3: "**Hop five** is caused by hop four's enrollment creation. Every payer contract whose `enrollment_open_count` has just moved from zero to a positive value transitions `LEGACY → PENDING_CREDENTIALING` and has its `version` incremented by one."

    Design: Difficulty/transitive_cascade/affiliation_close_five_hop_cascade_to_payer_contract
    """
    ctx = closed_deal_with_two_offers
    rows, meta = validate_paginated(
        api_client.list_payer_enrollments(LEAD, {"payer_contract_id": ctx["contract_id"]})
    )
    assert meta["total_count"] == 1
    enrollment = rows[0]
    assert enrollment["doctor_employment_id"] == ctx["employment_id"]
    assert enrollment["status"] == "NOT_STARTED"
    assert enrollment["effective_date"] == CASCADE_ENROLLMENT_EFFECTIVE
    assert enrollment["term_date"] is None

    contract = read_payer_contract(ctx["contract_id"])
    assert contract["transition_state"] == "PENDING_CREDENTIALING"
    assert contract["enrollment_open_count"] == 1

    practice = read_practice(ctx["practice_id"])
    # PRD §2.7: pending_credentialing_count counts only the enrollments whose
    # status is SUBMITTED, and the cascade opens them in NOT_STARTED.
    assert practice["pending_credentialing_count"] == 0
    assert read_employment(ctx["employment_id"])["credentialing_status"] == "PENDING"


@pytest.fixture
def practice_frozen_by_departure():
    """The only active doctor of a closed practice departs, freezing it."""
    ctx = build_closed_deal_with_contract()
    ctx["enrollment_id"] = ctx["cascade_enrollment_id"]
    submit_enrollment(ctx["enrollment_id"])
    batch = build_scheduled_batch(
        ctx["practice_id"],
        *BATCH_WINDOW,
        batch_label="CHART-WAVE-1",
        records_total=5000,
    )
    ctx["batch_id"] = batch["id"]
    ctx["separated"] = separate_employment(ctx["employment_id"])
    return ctx


def test_departure_stamps_the_covenant_and_the_records_dimension(
    practice_frozen_by_departure
):
    """PRD §3.4: "Hop one touches the employment row: `employment_status` moves `ACTIVE → SEPARATED`, `separation_date` is stamped from the logical clock, `separation_reason` is recorded from the request, `non_compete_end_date` is set to `separation_date` advanced by `non_compete_months` calendar months, `records_custody_state` moves `HELD_BY_PRACTICE → TRANSFER_PENDING`, `non_compete_enforcement_state` moves `NOT_APPLICABLE → PENDING`, and the practice's `active_doctor_count` decreases by one."

    Design: Difficulty/transitive_cascade/doctor_separation_three_hop_freeze_cascade
    """
    separated = practice_frozen_by_departure["separated"]
    assert_doctor_employment(separated)
    assert separated["employment_status"] == "SEPARATED"
    assert separated["separation_date"] == CLOSE_DATE
    assert separated["separation_reason"] == "VOLUNTARY"
    assert separated["non_compete_end_date"] == NON_COMPETE_END
    assert separated["records_custody_state"] == "TRANSFER_PENDING"
    assert separated["non_compete_enforcement_state"] == "PENDING"


def test_the_freeze_holds_the_batch_and_suspends_the_enrollment(
    practice_frozen_by_departure
):
    """PRD §3.4: "Hop two is caused by that counter change. When `active_doctor_count` reaches zero, the posture ladder of §2.6 returns `FROZEN`, so the practice moves `STABILIZING` → `FROZEN` — or `RESTRICTED` → `FROZEN`, or `INTEGRATED` → `FROZEN`, depending on where it stood — `clinical_coverage_gap` is set to true, and the practice's `version` increments by one."
    PRD §3.4: "Hop three is caused by hop two's posture change. Every migration batch of that practice in `SCHEDULED` status moves `SCHEDULED → HELD`, keeping its reserved `cutover_start_at` and `cutover_end_at`, and every enrollment of that practice in `SUBMITTED` status moves `SUBMITTED → SUSPENDED`."

    Design: Difficulty/transitive_cascade/doctor_separation_three_hop_freeze_cascade
    """
    ctx = practice_frozen_by_departure
    practice = read_practice(ctx["practice_id"])
    assert_practice(practice)
    assert practice["active_doctor_count"] == 0
    assert practice["integration_posture"] == "FROZEN"
    assert practice["clinical_coverage_gap"] is True

    batch = read_migration_batch(ctx["batch_id"])
    assert batch["status"] == "HELD"
    assert batch["cutover_start_at"] == BATCH_WINDOW[0]
    assert batch["cutover_end_at"] == BATCH_WINDOW[1]

    enrollment = read_payer_enrollment(ctx["enrollment_id"])
    assert enrollment["status"] == "SUSPENDED"


def test_the_unwound_counters_revert_the_contract_and_suspend_measurement(
    practice_frozen_by_departure
):
    """PRD §3.4: "Hop four is caused by hop three. Each held batch reduces its practice's conversion vendor's `active_window_count` by one, and each suspended enrollment reduces the practice's `pending_credentialing_count` by one and its payer contract's `enrollment_open_count` by one."
    PRD §3.4: "Every payer contract whose `enrollment_open_count` has reached zero while its `transition_state` is `PENDING_CREDENTIALING` reverts `PENDING_CREDENTIALING → LEGACY`, provided no enrollment of that contract is `APPROVED`; each such reversion increments the contract's `version` by one."

    Design: Difficulty/transitive_cascade/doctor_separation_three_hop_freeze_cascade
    """
    ctx = practice_frozen_by_departure
    vendor = read_conversion_vendor(ctx["vendor_id"])
    assert vendor["active_window_count"] == 0

    practice = read_practice(ctx["practice_id"])
    assert practice["pending_credentialing_count"] == 0

    contract = read_payer_contract(ctx["contract_id"])
    assert contract["enrollment_open_count"] == 0
    assert contract["transition_state"] == "LEGACY"

    assert read_employment(ctx["employment_id"])["credentialing_status"] == "PENDING"
    affiliation = read_affiliation(ctx["affiliation_id"])
    assert affiliation["earnout_measurement_state"] == "SUSPENDED"

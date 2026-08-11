"""Benefit applications: the per-item resource haircut, the programme limits,
the appeal cap, and the retroactive award posting."""

from test_helpers import (
    ApiErrorId,
    api_client,
    appeal_benefit_application,
    assert_benefit_application,
    benefit_application_status_payload,
    change_period_status,
    create_account,
    create_active_authorization,
    create_active_client,
    draft_benefit_application,
    list_ledger_entries,
    open_period,
    read_account,
    read_benefit_application,
    read_period,
    record_benefit_decision,
    record_decision_payload,
    set_clock,
    setup_submitted_application,
    submit_benefit_application,
    TEST_USERS,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["fiduciary_manager_headers"]
SPECIALIST = TEST_USERS["bill_pay_specialist_headers"]

SEVEN_ITEMS = [
    {"item_type": "CASH", "value_cents": 50000},
    {"item_type": "RETIREMENT", "value_cents": 100000},
    {"item_type": "BURIAL_FUND", "value_cents": 200000},
    {"item_type": "VEHICLE", "value_cents": 900000},
    {"item_type": "HOME", "value_cents": 15000000},
    {"item_type": "LIFE_INSURANCE", "value_cents": 33333},
    {"item_type": "LIFE_INSURANCE", "value_cents": 44445},
]


def _client_with_full_agency(intake_reference="INT-9005"):
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(intake_reference=intake_reference)
    authorization = create_active_authorization(client["id"], scope_tier="FULL_AGENCY")
    return client, authorization


def test_countable_resources_round_each_item_before_summing():
    """PRD §3.8: "a `RETIREMENT` holding counts as its `value_cents` multiplied
    by 0.665, rounded half up to a whole cent;"
    PRD §3.8: "The rounding order is pinned: **round each item individually,
    then sum the rounded figures**. Summing first and rounding once produces a
    different total whenever two or more rate-bearing items are present, and
    the per-item order is the one this platform uses."
    PRD §3.8: "`countable_resources_gross_cents` is the plain sum of
    `value_cents` over every declared item, with no exclusion of any kind — the
    raw declared worth of the estate."

    Design: Difficulty/combinatorial_formula/benefit_net_resources_round_per_item_then_sum_mode_b
    """
    client, authorization = _client_with_full_agency()

    application = draft_benefit_application(
        client["id"],
        authorization["id"],
        program="MEDICAID",
        asserted_monthly_income_cents=120000,
        resource_items=SEVEN_ITEMS,
    )

    assert_benefit_application(application)
    assert application["countable_resources_gross_cents"] == 16327778
    # 50000 + 66500 + 50000 + 0 + 0 + 16667 + 22223, each item rounded first.
    assert application["countable_resources_net_cents"] == 205390
    assert application["status"] == "DRAFT"


def test_the_application_submits_within_both_medicaid_limits():
    """PRD §3.8: "Submitting is a separate act, driven by an `action` of
    `SUBMIT`. It requires the application to be in `DRAFT` and it tests both
    programme limits at once, refusing with `ERR_RESOURCE_LIMIT_EXCEEDED` at
    rung 38 if either fails."
    PRD §3.8: "On success `submitted_on` is written with the current logical
    date and the application moves `DRAFT` → `SUBMITTED`."

    Design: Difficulty/combinatorial_formula/benefit_net_resources_round_per_item_then_sum_mode_b
    """
    client, authorization = _client_with_full_agency()
    application = draft_benefit_application(
        client["id"],
        authorization["id"],
        program="MEDICAID",
        asserted_monthly_income_cents=120000,
        resource_items=SEVEN_ITEMS,
    )

    submitted = submit_benefit_application(application["id"])

    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_on"] == "2026-06-01"
    assert submitted["countable_resources_net_cents"] == 205390


def test_the_ssi_resource_limit_is_tested_against_the_net_figure():
    """PRD §3.8: "The resource ceilings are 200000 cents for `SSI`, 300000 for
    `MEDICAID`, 275000 for `SNAP` and 400000 for `LIHEAP`; the monthly income
    ceilings are 96700 cents for `SSI`, 150000 for `MEDICAID`, 182000 for
    `SNAP` and 250000 for `LIHEAP`."
    PRD §3.8: "`countable_resources_net_cents` applies the programme exclusion
    table item by item, and this is the figure the limits are tested against:"

    Design: Corner/calculations/corner_ssi_resource_limit_refuses_submission
    """
    client, authorization = _client_with_full_agency("INT-C023")
    application = draft_benefit_application(
        client["id"],
        authorization["id"],
        program="SSI",
        asserted_monthly_income_cents=50000,
        resource_items=[
            {"item_type": "CASH", "value_cents": 180000},
            {"item_type": "RETIREMENT", "value_cents": 40000},
        ],
    )
    assert application["countable_resources_gross_cents"] == 220000
    assert application["countable_resources_net_cents"] == 206600

    response = api_client.change_benefit_application_status(
        application["id"], benefit_application_status_payload("SUBMIT"), MANAGER
    )

    validate_error(response, ApiErrorId.ERR_RESOURCE_LIMIT_EXCEEDED.value, 409)
    after = read_benefit_application(application["id"])
    assert after["status"] == "DRAFT"
    assert after["submitted_on"] is None


def test_a_second_appeal_is_refused_by_the_appeal_cap():
    """PRD §3.8: "An `APPEAL` action moves the application `DENIED` →
    `APPEALED` and raises `appeal_count` by one; it requires `appeal_count` to
    still be below 1, so exactly one appeal is available and the second is
    refused with `ERR_APPEAL_LIMIT_REACHED` at rung 26."
    PRD §3.8: "`DENIED` is deliberately **not** terminal: it is the state an
    appeal departs from and the state a second denial returns to, rather than a
    separate final state."

    Design: Corner/validations/corner_second_appeal_is_refused_by_the_appeal_cap
    """
    world = setup_submitted_application()
    record_benefit_decision(
        world["application"]["id"],
        "DENIED",
        "2026-06-05",
        world["account"]["id"],
        denial_reason="Excess countable resources per the state agency.",
    )
    appeal_benefit_application(world["application"]["id"])
    record_benefit_decision(
        world["application"]["id"],
        "DENIED",
        "2026-06-20",
        world["account"]["id"],
        denial_reason="Appeal denied on the same grounds.",
    )

    response = api_client.change_benefit_application_status(
        world["application"]["id"], benefit_application_status_payload("APPEAL"), MANAGER
    )

    validate_error(response, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value, 409)
    after = read_benefit_application(world["application"]["id"])
    assert after["status"] == "DENIED"
    assert after["appeal_count"] == 1


def test_a_retroactive_award_beyond_the_lookback_is_refused():
    """PRD §2.9 rung 24: "**Retroactive lookback.** On an approved decision,
    `decision_date` minus `award_effective_date` is at most 180 days,
    inclusive, and `award_effective_date` is not after `decision_date`.
    Otherwise `ERR_RETRO_LOOKBACK_EXCEEDED` (422). Applies to recording an
    agency decision."

    Design: Corner/validations/corner_retroactive_award_beyond_the_lookback_is_rejected
    """
    world = setup_submitted_application()

    response = api_client.record_benefit_decision(
        world["application"]["id"],
        record_decision_payload(
            "APPROVED",
            "2026-06-01",
            world["account"]["id"],
            award_effective_date="2025-11-01",
            award_monthly_amount_cents=50000,
        ),
        MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_RETRO_LOOKBACK_EXCEEDED.value, 422)
    after = read_benefit_application(world["application"]["id"])
    assert after["status"] == "SUBMITTED"
    assert after["retro_award_cents"] == 0
    assert read_account(world["account"]["id"])["cleared_balance_cents"] == 5000000


def test_an_approved_award_computes_the_month_distance_and_the_arrears():
    """PRD §3.8: "Then `retro_months` is computed as the whole-calendar-month
    distance between the two dates — the decision's year multiplied by twelve
    plus the decision's month, less the effective date's year multiplied by
    twelve plus the effective date's month — which is zero when both dates fall
    in the same calendar month."
    PRD §3.8: "`retro_award_cents` is `award_monthly_amount_cents` multiplied
    by `retro_months`, and `decision_date`, `award_effective_date`,
    `award_monthly_amount_cents`, `retro_months` and `retro_award_cents` are
    all written to the application."

    Design: Difficulty/transitive_cascade/retroactive_award_posts_to_current_period_and_flags_the_frozen_month
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(intake_reference="INT-9012")
    authorization = create_active_authorization(client["id"], scope_tier="FULL_AGENCY")
    account = create_account(client["id"], opening_balance_cents=5000000)
    april = open_period(account["id"], "2026-04")
    change_period_status(april["id"], "IN_REVIEW", SPECIALIST)
    change_period_status(april["id"], "CLOSED", MANAGER)
    open_period(account["id"], "2026-06")
    application = draft_benefit_application(
        client["id"],
        authorization["id"],
        program="MEDICAID",
        asserted_monthly_income_cents=120000,
        resource_items=[{"item_type": "CASH", "value_cents": 100000}],
    )
    submit_benefit_application(application["id"])

    approved = record_benefit_decision(
        application["id"],
        "APPROVED",
        "2026-06-01",
        account["id"],
        award_effective_date="2026-04-15",
        award_monthly_amount_cents=50000,
    )

    assert approved["status"] == "APPROVED"
    assert approved["retro_months"] == 2
    assert approved["retro_award_cents"] == 100000
    assert approved["countable_resources_net_cents"] == 100000


def test_the_award_entry_lands_in_the_current_period_and_flags_the_frozen_month():
    """PRD §3.8: "**If such a period exists and its `status` is `CLOSED` or
    `LOCKED`**, the entry is dated the **current logical date** instead, its
    `period_id` is resolved from that current date in the ordinary way, and its
    `retro_period_month` records the award month it relates to. The closed
    period itself is then marked with `has_retro_adjustment` set to true — the
    single field the reconciliation freeze permits writing into a frozen
    period, and the reason this whole operation is exempt from the freeze gate."
    PRD §3.8: "Caused in turn by the entry, the account's
    `cleared_balance_cents` and `available_balance_cents` both rise by
    `retro_award_cents`, and the period that actually received the entry has
    its `unreconciled_entry_count` raised by one"

    Design: Difficulty/transitive_cascade/retroactive_award_posts_to_current_period_and_flags_the_frozen_month
    """
    set_clock("2026-06-01T09:00:00Z")
    client = create_active_client(intake_reference="INT-9012")
    authorization = create_active_authorization(client["id"], scope_tier="FULL_AGENCY")
    account = create_account(client["id"], opening_balance_cents=5000000)
    april = open_period(account["id"], "2026-04")
    change_period_status(april["id"], "IN_REVIEW", SPECIALIST)
    change_period_status(april["id"], "CLOSED", MANAGER)
    june = open_period(account["id"], "2026-06")
    application = draft_benefit_application(
        client["id"],
        authorization["id"],
        program="MEDICAID",
        asserted_monthly_income_cents=120000,
        resource_items=[{"item_type": "CASH", "value_cents": 100000}],
    )
    submit_benefit_application(application["id"])

    record_benefit_decision(
        application["id"],
        "APPROVED",
        "2026-06-01",
        account["id"],
        award_effective_date="2026-04-15",
        award_monthly_amount_cents=50000,
    )

    after = read_account(account["id"])
    assert after["cleared_balance_cents"] == 5100000
    assert after["available_balance_cents"] == 5100000

    entries = list_ledger_entries(account["id"])
    assert len(entries) == 1, f"Expected exactly one ledger entry, got {entries}"
    entry = entries[0]
    assert entry["entry_type"] == "BENEFIT_AWARD"
    assert entry["amount_cents"] == 100000
    assert entry["entry_date"] == "2026-06-01"
    assert entry["period_id"] == june["id"]
    assert entry["retro_period_month"] == "2026-04"

    assert read_period(june["id"])["unreconciled_entry_count"] == 1
    april_after = read_period(april["id"])
    assert april_after["has_retro_adjustment"] is True
    assert april_after["status"] == "CLOSED"

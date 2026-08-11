"""Pricing a period: franchise tax, late fees, waivers and the portfolio rollup."""
from test_helpers import (
    ADMIN,
    CA_RULE_PER_MONTH,
    DE_RULE_LISTING,
    DE_RULE_MIN_LATE,
    DE_RULE_TIERS,
    NY_RULE_ASSUMED_PAR,
    OFFICER,
    TX_RULE_RECEIPTS,
    new_client,
    new_entity,
    new_home_registration,
    new_obligation,
    ops_run,
    publish_rule,
    read_client,
    read_obligation,
    set_clock,
    setup_active_home_registration,
    setup_pending_home_registration,
    validate_paginated,
    validate_success,
)

NY_ROLLUP_RULE = {
    "state_code": "NY",
    "effective_from": "2026-01-01",
    "annual_report_basis": "ANNIVERSARY_MONTH_DAY",
    "franchise_tax_basis": "ASSUMED_PAR_VALUE",
    "assumed_par_value_rate_bps": 35,
    "min_franchise_tax_cents": 17500,
    "max_franchise_tax_cents": 2000000,
    "grace_days": 15,
    "grace_basis": "CALENDAR_DAYS",
    "late_fee_style": "PERCENT_CAPPED",
    "late_fee_percent_bps": 1000,
    "late_fee_cap_cents": 30000,
    "annual_report_fee_cents": 900,
    "franchise_tax_filing_fee_cents": 900,
}


def test_per_month_late_fee_charges_a_whole_ceiling_block(api):
    """PRD §3.5: "Under `PER_MONTH`, the days late are divided by 30 and rounded **up**
    to the next whole number of monthly blocks, and the fee is that number of blocks
    multiplied by the rule's `late_fee_per_month_cents`."
    PRD §3.5: "The number of days late is the assessment date — the logical clock date
    at the moment of the recomputation — minus `grace_end_date`, floored at zero, so
    that a recomputation on or before `grace_end_date` yields zero days late."

    Design: Corner/calculations/corner_per_month_late_fee_charges_a_full_ceiling_block
    """
    scene = setup_pending_home_registration(
        CA_RULE_PER_MONTH,
        entity_overrides={
            "legal_name": "Pacific Widgets LLC",
            "home_state_code": "CA",
            "formation_date": "2026-02-01",
        },
    )
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)

    set_clock("2027-05-01T00:00:00Z")
    ops_run()

    data = read_obligation(obligation["id"])
    assert data["due_date"] == "2027-02-01"
    # 58 calendar days on from 2027-02-01: 27 days to 2027-02-28, then 31 more to
    # 2027-03-31.
    assert data["grace_end_date"] == "2027-03-31"
    assert data["status"] == "DELINQUENT"
    # 2027-05-01 minus 2027-03-31 is 31 days late; 31/30 rounded up is 2 blocks;
    # 2 * 5000 = 10000.
    assert data["late_fee_cents"] == 10000
    # 2000 state + 0 franchise tax + 10000 late fee + 4900 service = 16900.
    assert data["total_due_cents"] == 16900


def test_percent_capped_late_fee_is_clamped_by_its_cap(api):
    """PRD §3.5: "Under `PERCENT_CAPPED`, the base is the obligation's own
    `state_fee_cents` plus its `franchise_tax_cents` — the late fee's own value is not
    part of its base. The raw fee is that base multiplied by the rule's
    `late_fee_percent_bps` and divided by 10000, rounded half up to a whole cent, and
    the fee is the lesser of that raw figure and the rule's `late_fee_cap_cents`."
    PRD §3.5: "Under `ASSUMED_PAR_VALUE`, the server first computes an assumed par
    capital: if the entity's `authorized_shares` is 0 the assumed par capital is 0,
    otherwise it is the entity's `total_gross_assets_cents` multiplied by its
    `issued_shares` and divided by its `authorized_shares`, **rounded half up to a whole
    cent at that point**."

    Design: Corner/calculations/corner_percent_capped_late_fee_is_clamped_by_the_cap
    """
    scene = setup_pending_home_registration(
        NY_RULE_ASSUMED_PAR,
        client_overrides={
            "legal_name": "Empire Holdings",
            "billing_email": "ap@empire.example",
        },
        entity_overrides={
            "legal_name": "Eastwind Widgets LLC",
            "entity_type": "CORP",
            "home_state_code": "NY",
            "formation_date": "2026-02-01",
            "authorized_shares": 8000,
            "issued_shares": 4000,
            "total_gross_assets_cents": 900000000,
        },
    )
    obligation = new_obligation(scene["registration"]["id"], "FRANCHISE_TAX", 2027)

    set_clock("2027-05-01T00:00:00Z")
    ops_run()

    data = read_obligation(obligation["id"])
    # assumed par capital = 900000000 * 4000 / 8000 = 450000000;
    # raw tax = 450000000 * 35 / 10000 = 1575000, inside the [17500, 2000000] clamp.
    assert data["franchise_tax_cents"] == 1575000
    assert data["state_fee_cents"] == 900
    # raw late fee = (900 + 1575000) * 1000 / 10000 = 157590, reduced to the cap 30000.
    assert data["late_fee_cents"] == 30000
    # 900 + 1575000 + 30000 + 4900 = 1610800.
    assert data["total_due_cents"] == 1610800


def test_assumed_par_value_tax_is_lifted_to_the_minimum(api):
    """PRD §3.5: "Finally the raw tax is clamped from below by the rule's
    `min_franchise_tax_cents` and from above by its `max_franchise_tax_cents`: a raw tax
    below the minimum is raised to the minimum, and one above the maximum is reduced to
    the maximum."

    Design: Corner/calculations/corner_assumed_par_value_minimum_clamp_applies
    """
    scene = setup_pending_home_registration(
        NY_RULE_ASSUMED_PAR,
        client_overrides={
            "legal_name": "Empire Holdings",
            "billing_email": "ap@empire.example",
        },
        entity_overrides={
            "legal_name": "Small Harbor Corp",
            "entity_type": "CORP",
            "home_state_code": "NY",
            "formation_date": "2026-02-01",
            "authorized_shares": 8000,
            "issued_shares": 4000,
            "total_gross_assets_cents": 1000000,
        },
    )

    data = new_obligation(scene["registration"]["id"], "FRANCHISE_TAX", 2027)

    # assumed par capital = 1000000 * 4000 / 8000 = 500000;
    # raw tax = 500000 * 35 / 10000 = 1750, lifted to the minimum 17500.
    assert data["franchise_tax_cents"] == 17500
    # 900 state + 17500 franchise tax + 0 late fee + 4900 service = 23300.
    assert data["total_due_cents"] == 23300


def test_gross_receipts_bracket_ceiling_is_inclusive(api):
    """PRD §3.5: "Under `GROSS_RECEIPTS_BRACKETS`, the rule's `gross_receipts_brackets`
    are considered in ascending order of `up_to_cents`, with any bracket whose
    `up_to_cents` is null placed last, and the server returns the `tax_cents` of the
    first bracket whose `up_to_cents` is null or is greater than or equal to the
    entity's `annual_gross_receipts_cents`."

    Design: Corner/calculations/corner_gross_receipts_bracket_upper_bound_is_inclusive
    """
    publish_rule(TX_RULE_RECEIPTS)
    client = new_client()
    at_ceiling = new_entity(
        client["id"],
        legal_name="At Ceiling LLC",
        home_state_code="TX",
        formation_date="2026-01-31",
        annual_gross_receipts_cents=123000000,
    )
    one_over = new_entity(
        client["id"],
        legal_name="One Cent Over LLC",
        home_state_code="TX",
        formation_date="2026-01-31",
        annual_gross_receipts_cents=123000001,
    )
    registration_low = new_home_registration(at_ceiling["id"])
    registration_high = new_home_registration(one_over["id"])

    obligation_low = new_obligation(registration_low["id"], "FRANCHISE_TAX", 2027)
    obligation_high = new_obligation(registration_high["id"], "FRANCHISE_TAX", 2027)

    assert obligation_low["franchise_tax_cents"] == 0
    assert obligation_high["franchise_tax_cents"] == 37500
    # 0 state + 0 tax + 0 late + 4900 service; the second obligation still pays the
    # undiscounted 4900 because the client's prior open count was only 1.
    assert obligation_low["total_due_cents"] == 4900
    # 0 state + 37500 tax + 0 late + 4900 service = 42400.
    assert obligation_high["total_due_cents"] == 42400


def test_authorized_shares_tier_ceiling_is_inclusive(api):
    """PRD §3.5: "Under `AUTHORIZED_SHARES_TIERS`, the rule's `authorized_shares_tiers`
    are considered in ascending order of `up_to_shares`, with any tier whose
    `up_to_shares` is null placed last. The server walks that ordered list and returns
    the `tax_cents` of the first tier whose `up_to_shares` is null or is greater than or
    equal to the entity's `authorized_shares`. A company holding exactly the tier's
    ceiling stays inside that tier."

    Design: Corner/calculations/corner_authorized_shares_tier_upper_bound_is_inclusive
    """
    publish_rule(DE_RULE_TIERS)
    client = new_client()
    at_ceiling = new_entity(
        client["id"],
        legal_name="Tier Edge Corp",
        entity_type="CORP",
        formation_date="2026-01-31",
        authorized_shares=5000,
        issued_shares=2500,
    )
    one_over = new_entity(
        client["id"],
        legal_name="Tier Over Corp",
        entity_type="CORP",
        formation_date="2026-01-31",
        authorized_shares=5001,
        issued_shares=2500,
    )
    registration_low = new_home_registration(at_ceiling["id"])
    registration_high = new_home_registration(one_over["id"])

    obligation_low = new_obligation(registration_low["id"], "FRANCHISE_TAX", 2027)
    obligation_high = new_obligation(registration_high["id"], "FRANCHISE_TAX", 2027)

    assert obligation_low["franchise_tax_cents"] == 17500
    assert obligation_high["franchise_tax_cents"] == 25000


def test_waiving_zeroes_the_money_and_suppresses_every_reminder(api):
    """PRD §3.5: "On success the obligation moves to `WAIVED`, `satisfied_on` is stamped
    with the current clock date, `total_due_cents` is set to 0, every reminder notice of
    the obligation still in `PENDING` is moved to `SUPPRESSED`, the obligation's
    `version` increases by 1, and the registration's `delinquency_rank`, the entity's
    `compliance_posture` and the client's rollup are all recomputed."

    Design: Corner/state_machines/corner_waive_obligation_zeroes_money_and_suppresses_reminders
    """
    scene = setup_active_home_registration(DE_RULE_MIN_LATE)
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    set_clock("2027-03-31T00:00:00Z")
    ops_run()
    assert read_obligation(obligation["id"])["status"] == "IN_GRACE"

    data = validate_success(
        api.waive_compliance_obligation(
            obligation["id"], {"waiver_reason": "State amnesty programme 2027"}, ADMIN
        )
    )

    assert data["status"] == "WAIVED"
    assert data["total_due_cents"] == 0
    assert data["satisfied_on"] == "2027-03-31"

    reminders, _meta = validate_paginated(api.list_reminders(obligation["id"], ADMIN))
    assert reminders, "the obligation's reminder ladder must exist"
    assert all(row["status"] == "SUPPRESSED" for row in reminders)

    client = read_client(scene["client"]["id"])
    assert client["portfolio_open_obligation_count"] == 0
    assert client["portfolio_outstanding_cents"] == 0
    assert client["portfolio_delinquency_status"] == "CURRENT"


def test_portfolio_summary_equals_the_sum_of_its_state_parts(api):
    """PRD §3.1: "it reports `client_id`, `entity_count` (the count of the client's
    legal entities that are not `DISSOLVED`, the same figure as
    `portfolio_entity_count`), `registration_count` (the number of registration rows the
    client holds across all of its entities, counted in every status),
    `open_obligation_count` and `outstanding_cents` (the same two figures as
    `portfolio_open_obligation_count` and `portfolio_outstanding_cents`),
    `delinquency_status` (the same reading as `portfolio_delinquency_status`),
    `worst_state_code` (the `state_code` of the registration carrying the highest
    `delinquency_rank` in the portfolio, or null when the client holds no registrations
    at all), and `credit_balance_cents`."
    PRD §2.7: "For every `Client`, `portfolio_open_obligation_count` equals the number
    of that client's obligations in an open status and `portfolio_outstanding_cents`
    equals the sum of `total_due_cents` over exactly those same rows."

    Design: Corner/calculations/corner_portfolio_summary_equals_the_sum_of_its_state_parts
    """
    publish_rule(DE_RULE_MIN_LATE)
    publish_rule(NY_ROLLUP_RULE)
    client = new_client()
    entity_de = new_entity(client["id"])
    entity_ny = new_entity(
        client["id"],
        legal_name="Eastwind Widgets LLC",
        entity_type="CORP",
        home_state_code="NY",
        formation_date="2026-01-31",
        authorized_shares=8000,
        issued_shares=4000,
        total_gross_assets_cents=12000000,
    )
    registration_de = new_home_registration(entity_de["id"])
    registration_ny = new_home_registration(entity_ny["id"])

    obligation_de = new_obligation(registration_de["id"], "ANNUAL_REPORT", 2027)
    obligation_ny = new_obligation(registration_ny["id"], "FRANCHISE_TAX", 2027)

    # DE: 5000 state + 0 tax + 0 late + 4900 service = 9900.
    assert obligation_de["total_due_cents"] == 9900
    # NY: assumed par capital 12000000 * 4000 / 8000 = 6000000; tax = 6000000 * 35 /
    # 10000 = 21000; 900 state + 21000 tax + 0 late + 4900 service = 26800.
    assert obligation_ny["total_due_cents"] == 26800

    summary = validate_success(api.get_portfolio_summary(client["id"], ADMIN))

    assert summary["client_id"] == client["id"]
    assert summary["entity_count"] == 2
    # Both registrations are still PENDING, so they are counted alike whether the
    # count is taken over every status or over occupied statuses only.
    assert summary["registration_count"] == 2
    assert summary["open_obligation_count"] == 2
    assert summary["outstanding_cents"] == 36700, "9900 + 26800 == 36700"
    assert summary["delinquency_status"] == "CURRENT"
    assert summary["credit_balance_cents"] == 0

    rolled = read_client(client["id"])
    assert rolled["portfolio_open_obligation_count"] == 2
    assert rolled["portfolio_outstanding_cents"] == 36700

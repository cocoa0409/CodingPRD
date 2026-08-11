"""The reminder ladder, calendar rebuilds and the ops-run sweep."""
from test_helpers import (
    ADMIN,
    DE_RULE_MIN_LATE,
    DE_RULE_OPS,
    OFFICER,
    TX_RULE_FISCAL_REBUILD,
    new_obligation,
    ops_run,
    read_client,
    read_obligation,
    read_registration,
    set_clock,
    setup_active_home_registration,
    setup_pending_home_registration,
    validate_paginated,
    validate_success,
)


def test_reminder_ladder_is_minted_at_creation_and_fires_idempotently(api):
    """PRD §3.6: "Creating a calendar row also mints its reminder ladder: exactly five
    notices, all in status `PENDING`, each recording the `compliance_obligation_id` it
    belongs to, an `offset_label` naming its rung, a `scheduled_for` date, a
    `due_date_snapshot` capturing the obligation's `due_date` at the moment the notice
    row was created, `sent_on` null, and its own `version`."
    PRD §3.6: "The five rungs are `T_MINUS_90`, scheduled for 90 calendar days before
    `due_date`; `T_MINUS_60`, scheduled for 60 days before; `T_MINUS_30`, scheduled for
    30 days before; `T_MINUS_7`, scheduled for 7 days before; and `OVERDUE`, scheduled
    for one calendar day after `grace_end_date`."
    PRD §3.6: "A firing notice moves `PENDING → SENT`, has `sent_on` stamped with the
    current clock date, and has its `version` increased by 1."

    Design: Corner/calculations/corner_reminder_ladder_is_minted_at_creation_and_sent_idempotently
    """
    scene = setup_pending_home_registration(DE_RULE_MIN_LATE)
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    assert obligation["due_date"] == "2027-03-01"
    assert obligation["grace_end_date"] == "2027-03-31"

    minted, meta = validate_paginated(api.list_reminders(obligation["id"], ADMIN))
    assert meta["total_count"] == 5
    assert all(row["status"] == "PENDING" for row in minted)
    assert all(row["due_date_snapshot"] == "2027-03-01" for row in minted)
    assert all(row["sent_on"] is None for row in minted)
    # 90, 60, 30 and 7 calendar days before 2027-03-01, plus one day after the
    # grace end 2027-03-31.
    assert {row["scheduled_for"] for row in minted} == {
        "2026-12-01",
        "2026-12-31",
        "2027-01-30",
        "2027-02-22",
        "2027-04-01",
    }

    set_clock("2027-03-01T00:00:00Z")
    ops_run()
    ops_run()

    after, after_meta = validate_paginated(api.list_reminders(obligation["id"], ADMIN))
    assert after_meta["total_count"] == 5, "re-running the sweep creates no extra row"
    sent = [row for row in after if row["status"] == "SENT"]
    assert len(sent) == 4
    assert all(row["sent_on"] == "2027-03-01" for row in sent)
    overdue = [row for row in after if row["offset_label"] == "OVERDUE"]
    assert len(overdue) == 1
    assert overdue[0]["status"] == "PENDING", "its scheduled_for has not yet arrived"


def test_calendar_rebuild_moves_scheduled_due_dates_and_rearms_reminders(api):
    """PRD §3.6: "Eligible rows have `due_date`, `grace_end_date` and
    `delinquency_date` re-derived — under **their own pinned** rule version, using the
    entity's **current** `formation_date` and fiscal-year-end fields."
    PRD §3.6: "The response reports `registration_id`, `rebuilt_count`,
    `preserved_count` and `reminders_rearmed`."
    PRD §3.6: "Where a `due_date` moved, every reminder notice of that obligation whose
    `due_date_snapshot` no longer matches the new `due_date` is moved to `REARMED` —
    this applies to notices in `PENDING` and to notices already in `SENT` alike — and a
    fresh ladder of five `PENDING` notices is minted against the new `due_date`, one for
    each of the four countdown rungs plus the overdue rung, each carrying the new
    `due_date_snapshot`."

    Design: Corner/calculations/corner_calendar_rebuild_moves_scheduled_due_dates_and_rearms_reminders
    """
    scene = setup_pending_home_registration(
        TX_RULE_FISCAL_REBUILD,
        entity_overrides={
            "legal_name": "Lone Star Widgets LLC",
            "home_state_code": "TX",
            "formation_date": "2026-01-31",
            "fiscal_year_end_month": 12,
            "fiscal_year_end_day": 31,
        },
    )
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    pinned_rule_id = obligation["governing_rule_id"]
    # Fiscal year end 2027-12-31 plus 135 calendar days is 2028-05-14, a Sunday, so
    # the forward roll lands on Monday 2028-05-15.
    assert obligation["due_date"] == "2028-05-15"

    validate_success(
        api.update_legal_entity(
            scene["entity"]["id"],
            {"fiscal_year_end_month": 6, "fiscal_year_end_day": 30},
            OFFICER,
        )
    )

    report = validate_success(
        api.calendar_rebuild(
            scene["registration"]["id"], {"rebuild_types": ["ANNUAL_REPORT"]}, OFFICER
        )
    )

    assert report["registration_id"] == scene["registration"]["id"]
    assert report["rebuilt_count"] == 1
    assert report["preserved_count"] == 0
    assert report["reminders_rearmed"] == 5

    rebuilt = read_obligation(obligation["id"])
    # Fiscal year end 2027-06-30 plus 135 calendar days is Friday 2027-11-12.
    assert rebuilt["due_date"] == "2027-11-12"
    # 45 calendar days on from 2027-11-12 is 2027-12-27.
    assert rebuilt["grace_end_date"] == "2027-12-27"
    assert rebuilt["governing_rule_id"] == pinned_rule_id

    rows, meta = validate_paginated(api.list_reminders(obligation["id"], ADMIN))
    assert meta["total_count"] == 10
    rearmed = [row for row in rows if row["status"] == "REARMED"]
    fresh = [row for row in rows if row["status"] == "PENDING"]
    assert len(rearmed) == 5
    assert all(row["due_date_snapshot"] == "2028-05-15" for row in rearmed)
    assert len(fresh) == 5
    assert all(row["due_date_snapshot"] == "2027-11-12" for row in fresh)


def test_one_sweep_advances_every_open_obligation_and_counts_only_the_movers(api):
    """PRD §3.13: "Advance every open compliance obligation along the monotone status
    ladder, re-pricing `late_fee_cents` and `total_due_cents` on each row that actually
    moves."
    PRD §3.13: "The response is a set of counters reporting exactly what the sweep did:
    `obligations_advanced`, `reminders_sent`, `appointments_resigned`,
    `registrations_dissolved`, `registrations_closed_permanent`, `cases_expired` and
    `boi_axes_delinquent`. Each counter reports the number of rows that actually changed
    state on this run, not the number of rows examined."

    Design: Corner/cross_cutting_complexity_layers/corner_ops_run_advances_every_open_obligation_in_one_pass
    """
    scene = setup_active_home_registration(DE_RULE_OPS)
    annual_2027 = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    franchise_2027 = new_obligation(scene["registration"]["id"], "FRANCHISE_TAX", 2027)
    annual_2028 = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2028)

    set_clock("2027-04-01T00:00:00Z")
    counters = ops_run()

    assert counters["obligations_advanced"] == 2

    first = read_obligation(annual_2027["id"])
    second = read_obligation(franchise_2027["id"])
    third = read_obligation(annual_2028["id"])
    # 5000 state + 0 tax + 20000 flat late fee + 4900 service = 29900 on each 2027 row.
    assert first["status"] == "DELINQUENT"
    assert first["late_fee_cents"] == 20000
    assert first["total_due_cents"] == 29900
    assert second["status"] == "DELINQUENT"
    assert second["late_fee_cents"] == 20000
    assert second["total_due_cents"] == 29900
    assert third["status"] == "SCHEDULED"
    assert third["late_fee_cents"] == 0
    assert third["total_due_cents"] == 9900

    registration = read_registration(scene["registration"]["id"])
    assert registration["status"] == "DELINQUENT"
    assert registration["delinquency_rank"] == 3

    client = read_client(scene["client"]["id"])
    assert client["portfolio_open_obligation_count"] == 3
    # 29900 + 29900 + 9900 = 69700.
    assert client["portfolio_outstanding_cents"] == 69700

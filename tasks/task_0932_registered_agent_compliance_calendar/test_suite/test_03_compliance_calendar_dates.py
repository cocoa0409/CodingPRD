"""Deriving the calendar: due dates, grace windows and the status ladder."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    CA_RULE_CALENDAR_GRACE,
    DE_RULE_MIN,
    DE_RULE_MIN_LATE,
    MA_RULE_FEB31,
    OFFICER,
    OR_RULE_BUSINESS_GRACE,
    TX_RULE_MIN,
    TX_RULE_RECEIPTS,
    accept_appointment,
    activate_registration,
    assert_compliance_obligation,
    assert_same_instant,
    new_certificate,
    new_clearance,
    new_client,
    new_entity,
    new_home_registration,
    new_obligation,
    ops_run,
    propose_appointment,
    publish_rule,
    qualify_foreign,
    read_client,
    read_obligation,
    read_registration,
    set_clock,
    setup_active_home_registration,
    setup_pending_home_registration,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_fixed_due_day_clamps_to_the_month_then_rolls_to_a_business_day(api):
    """PRD §3.4: "When the basis is `FIXED_CALENDAR_DATE`, the entity's `formation_date`
    is ignored entirely. The month is the rule's `fixed_due_month` and the day is the
    rule's `fixed_due_day`, again reduced to the last day of that month in `period_year`
    if it exceeds it."
    PRD §3.4: "Whichever branch produced the raw date, the final `due_date` is that raw
    date rolled forward past weekends and observed holidays."
    PRD §3.4: "A `grace_days` of 0 leaves `grace_end_date` equal to `due_date` under
    either basis."

    Design: Corner/calculations/corner_fixed_calendar_due_day_clamps_to_month_length_then_rolls
    """
    scene = setup_pending_home_registration(
        MA_RULE_FEB31,
        entity_overrides={
            "legal_name": "Bayview Trading LLC",
            "home_state_code": "MA",
            "formation_date": "2026-01-31",
        },
    )

    data = validate_success(
        api.create_compliance_obligation(
            scene["registration"]["id"],
            {"obligation_type": "ANNUAL_REPORT", "period_year": 2027},
            OFFICER,
        ),
        201,
    )

    assert_compliance_obligation(data)
    # Day 31 of February 2027 clamps to 2027-02-28, which is a Sunday, so the forward
    # roll returns the next business day, Monday 2027-03-01.
    assert data["due_date"] == "2027-03-01"
    assert data["grace_end_date"] == "2027-03-01"
    assert data["state_fee_cents"] == 5000
    # 5000 state + 0 franchise tax + 0 late fee + 4900 service = 9900.
    assert data["total_due_cents"] == 9900


def test_business_day_grace_outruns_calendar_grace_for_the_same_grace_days(api):
    """PRD §3.4: "Under `CALENDAR_DAYS`, `grace_end_date` is simply `due_date` plus the
    rule's `grace_days` calendar days. The result is **not** rolled: it may legitimately
    fall on a Saturday, a Sunday or an observed holiday."
    PRD §3.4: "Under `BUSINESS_DAYS`, the server starts at `due_date` and repeats the
    following step exactly `grace_days` times: advance the working date by one calendar
    day, then roll it forward past weekends and observed holidays."

    Design: Corner/calculations/corner_business_day_grace_outruns_calendar_grace_for_same_grace_days
    """
    publish_rule(CA_RULE_CALENDAR_GRACE)
    publish_rule(OR_RULE_BUSINESS_GRACE)
    client_ca = new_client()
    client_or = new_client(
        legal_name="Cascade Holdings", billing_email="ap@cascade.example"
    )
    entity_ca = new_entity(
        client_ca["id"],
        legal_name="Pacific Widgets LLC",
        home_state_code="CA",
        formation_date="2026-01-31",
    )
    entity_or = new_entity(
        client_or["id"],
        legal_name="Cascade Widgets LLC",
        home_state_code="OR",
        formation_date="2026-01-31",
    )
    registration_ca = new_home_registration(entity_ca["id"])
    registration_or = new_home_registration(entity_or["id"])

    obligation_ca = new_obligation(registration_ca["id"], "ANNUAL_REPORT", 2027)
    obligation_or = new_obligation(registration_or["id"], "ANNUAL_REPORT", 2027)

    # The anniversary raw date 2027-01-31 is a Sunday, so both roll to 2027-02-01.
    assert obligation_ca["due_date"] == "2027-02-01"
    assert obligation_or["due_date"] == "2027-02-01"
    # Ten calendar days on from 2027-02-01 is 2027-02-11.
    assert obligation_ca["grace_end_date"] == "2027-02-11"
    # Ten business days: 02/02, 02/03, 02/04, 02/05, then Saturday 02/06 rolls to
    # Monday 02/08, then 02/09, 02/10, 02/11, 02/12, then Saturday 02/13 rolls to
    # Monday 2027-02-15.
    assert obligation_or["grace_end_date"] == "2027-02-15"


def test_fiscal_year_end_offset_reads_the_entity_fiscal_year_end(api):
    """PRD §3.4: "When the basis is `FISCAL_YEAR_END_OFFSET`, the month is the entity's
    `fiscal_year_end_month` and the day is the entity's `fiscal_year_end_day`, reduced
    to the last day of that month in `period_year` if it exceeds it; the rule's
    `fiscal_offset_days` calendar days are then added to that date."
    PRD §3.5: "`franchise_tax_cents` is 0 for every obligation whose `obligation_type`
    is anything other than `FRANCHISE_TAX`."

    Design: Corner/calculations/corner_fiscal_year_end_offset_due_date_uses_entity_fiscal_year_end
    """
    scene = setup_pending_home_registration(
        TX_RULE_RECEIPTS,
        entity_overrides={
            "legal_name": "Lone Star Widgets LLC",
            "home_state_code": "TX",
            "formation_date": "2026-01-31",
            "fiscal_year_end_month": 6,
            "fiscal_year_end_day": 30,
            "annual_gross_receipts_cents": 500000000,
        },
    )

    data = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)

    # 2027-06-30 plus 135 calendar days: +30 to 07-30, +31 to 08-30, ... landing on
    # 2027-11-12, which is a Friday and not an observed holiday, so no roll applies.
    assert data["due_date"] == "2027-11-12"
    # 45 calendar days on from 2027-11-12 is 2027-12-27.
    assert data["grace_end_date"] == "2027-12-27"
    assert data["state_fee_cents"] == 0
    assert data["franchise_tax_cents"] == 0
    assert data["total_due_cents"] == 4900


def test_obligation_ladder_advances_monotonically_across_ops_runs(api):
    """PRD §3.4: "The target is `DELINQUENT` when the current clock date is strictly
    after `grace_end_date`; otherwise `IN_GRACE` when the clock date is strictly after
    `due_date`; otherwise `DUE_SOON` when the clock date is on or after `due_date` minus
    30 calendar days; otherwise `SCHEDULED`."
    PRD §3.4: "Concretely: on `due_date` minus exactly 30 days the row is `DUE_SOON`
    because that comparison is inclusive; on `due_date` itself the row is still
    `DUE_SOON` because the step to `IN_GRACE` is strict; on `grace_end_date` itself the
    row is `IN_GRACE` because the step to `DELINQUENT` is strict; and on the day after
    `grace_end_date` the row is `DELINQUENT`."
    PRD §3.11: "its `status` becomes `DELINQUENT`, its `delinquency_rank` is set to 3,
    its `version` increases by 1, and the entity's `compliance_posture` and then the
    client's `portfolio_delinquency_status` are recomputed."

    Design: Corner/state_machines/corner_obligation_ladder_advances_monotonically_across_ops_runs
    """
    scene = setup_active_home_registration(DE_RULE_MIN_LATE)
    obligation = new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)
    assert obligation["due_date"] == "2027-03-01"
    assert obligation["grace_end_date"] == "2027-03-31"

    set_clock("2027-01-30T00:00:00Z")
    ops_run()
    assert read_obligation(obligation["id"])["status"] == "DUE_SOON"

    set_clock("2027-03-01T00:00:00Z")
    ops_run()
    assert read_obligation(obligation["id"])["status"] == "DUE_SOON"

    set_clock("2027-03-31T00:00:00Z")
    ops_run()
    in_grace = read_obligation(obligation["id"])
    assert in_grace["status"] == "IN_GRACE"
    assert in_grace["late_fee_cents"] == 0

    set_clock("2027-04-01T00:00:00Z")
    ops_run()
    delinquent = read_obligation(obligation["id"])
    assert delinquent["status"] == "DELINQUENT"
    assert delinquent["late_fee_cents"] == 20000
    # 5000 state + 0 franchise tax + 20000 flat late fee + 4900 service = 29900.
    assert delinquent["total_due_cents"] == 29900

    registration = read_registration(scene["registration"]["id"])
    assert registration["status"] == "DELINQUENT"
    assert registration["delinquency_rank"] == 3
    assert read_client(scene["client"]["id"])["portfolio_delinquency_status"] == "DELINQUENT"


def test_second_obligation_for_the_same_triple_is_refused(api):
    """PRD §3.4: "Duplicate protection is on the triple of registration,
    `obligation_type` and `period_year`: if a row with that same triple already exists
    in any status other than `VOIDED`, the creation is rejected with
    `ERR_DUPLICATE_OBLIGATION`."

    Design: Corner/validations/corner_duplicate_obligation_for_same_period_returns_conflict
    """
    scene = setup_pending_home_registration(DE_RULE_MIN)
    new_obligation(scene["registration"]["id"], "ANNUAL_REPORT", 2027)

    response = api.create_compliance_obligation(
        scene["registration"]["id"],
        {"obligation_type": "ANNUAL_REPORT", "period_year": 2027},
        OFFICER,
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_DUPLICATE_OBLIGATION.value)

    _rows, meta = validate_paginated(
        api.list_compliance_obligations(
            ADMIN, params={"registration_id": scene["registration"]["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_beneficial_ownership_obligation_is_home_registration_only(api):
    """PRD §3.4: "Beneficial-ownership obligations are further restricted:
    `BOI_INITIAL` and `BOI_UPDATE` may only be created on a registration whose
    `registration_kind` is `HOME`, and an attempt on a `FOREIGN` registration is
    rejected with `ERR_INVALID_REQUEST`."
    PRD §3.5: "and for `BOI_INITIAL` and `BOI_UPDATE` it is 0, because the
    beneficial-ownership registry charges no state filing fee."

    Design: Corner/validations/corner_boi_obligation_on_a_foreign_registration_is_rejected
    """
    publish_rule(DE_RULE_MIN)
    publish_rule(TX_RULE_MIN)
    client = new_client()
    entity = new_entity(client["id"])
    home = new_home_registration(entity["id"])
    appointment = propose_appointment(home)
    accept_appointment(appointment["id"])
    activate_registration(home["id"])
    certificate = new_certificate(home["id"])
    clearance = new_clearance(entity["id"], result="AVAILABLE")
    foreign = qualify_foreign(entity["id"], "TX", clearance["id"], certificate["id"])

    refused = api.create_compliance_obligation(
        foreign["id"], {"obligation_type": "BOI_INITIAL", "period_year": 2026}, OFFICER
    )
    assert refused.status_code == 400
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value)

    accepted = validate_success(
        api.create_compliance_obligation(
            home["id"], {"obligation_type": "BOI_INITIAL", "period_year": 2026}, OFFICER
        ),
        201,
    )
    assert accepted["obligation_type"] == "BOI_INITIAL"
    assert accepted["state_fee_cents"] == 0
    # 0 state + 0 franchise tax + 0 late fee (the rule's late_fee_flat_cents defaults
    # to 0) + 4900 service = 4900.
    assert accepted["total_due_cents"] == 4900


def test_clock_may_stand_still_but_may_never_move_backwards(api):
    """PRD §2.5: "The clock may be set forward or left where it is, but it may never be
    moved backwards: a target instant strictly earlier than the current logical clock
    instant is rejected with `ERR_CLOCK_REGRESSION` and HTTP 409."
    PRD §2.5: "The response reports `current_utc`, the instant the clock now reads, and
    `previous_utc`, the instant it read before the call."

    Design: Corner/validations/corner_clock_regression_is_refused
    """
    set_clock("2026-06-01T00:00:00Z")

    response = api.set_clock("2026-05-01T00:00:00Z", ADMIN)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_CLOCK_REGRESSION.value)

    same = validate_success(api.set_clock("2026-06-01T00:00:00Z", ADMIN))
    assert_same_instant(
        same["current_utc"], "2026-06-01T00:00:00Z", "current_utc after a no-op set"
    )

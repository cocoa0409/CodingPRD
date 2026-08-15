"""Filing calendar claims: due-date computation (anniversary, leap clamp,
weekend roll), franchise-tax suppression, fee snapshot, posture input-set
filtering, business-day penalty counting, and the list envelope."""
from test_helpers import (
    AUD1,
    SEC1,
    activate_entity,
    create_agent,
    create_jurisdiction_ca,
    fetch_entity,
    find_filing,
    list_filings,
    prepare_filing,
    set_clock,
    setup_base_entity,
    submit_filing,
    validate_paginated,
)


def test_due_date_weekend_roll(api):
    """PRD 3.6: "For `FORMATION_ANNIVERSARY`, the due date is the anniversary of
    the entity's `formation_date` in the `period_year`... If the computed due
    date falls on a Saturday or Sunday, it rolls forward to the next Monday."
    PRD 3.2: "one `ANNUAL_REPORT` filing is always generated, and one
    `FRANCHISE_TAX` filing is generated unless the jurisdiction's
    `franchise_tax_method` is `NONE`."

    Design: Corner/calculations/due_date_weekend_roll
    """
    j2 = create_jurisdiction_ca()
    ag2 = create_agent(j2["id"], name="CA Agent Co", address="5 Agent Blvd")
    # 2026-06-14 (the 2026 anniversary of 2025-06-14) is a Sunday.
    entity = activate_entity(
        j2["id"], ag2["id"], legal_name="Weekend Corp", formation_date="2025-06-14",
        authorized_shares=None,
    )

    all_filings, meta = validate_paginated(
        api.list_filings(SEC1, params={"entity_id": entity["id"]})
    )
    assert meta["total_count"] == 1, (
        "franchise NONE suppresses the FRANCHISE_TAX row; only ANNUAL_REPORT generated"
    )
    filing = all_filings[0]
    assert filing["filing_type"] == "ANNUAL_REPORT"
    assert filing["period_year"] == 2026
    assert filing["due_date"] == "2026-06-15", (
        f"Sunday 2026-06-14 must roll to Monday 2026-06-15, got {filing['due_date']}"
    )
    assert filing["report_fee_cents"] == 2500, "fee snapshot from the jurisdiction"


def test_due_date_leap_day_clamp(api):
    """PRD 3.6: "if the formation date is February 29 and the period year is not
    a leap year, the due date clamps to February 28."
    PRD 3.2: "The first filing `period_year` is the year after `formation_date`."

    Design: Corner/calculations/due_date_leap_day_clamp
    """
    j2 = create_jurisdiction_ca()
    ag2 = create_agent(j2["id"], name="CA Agent Co", address="5 Agent Blvd")
    entity = activate_entity(
        j2["id"], ag2["id"], legal_name="Leap Corp", formation_date="2024-02-29",
        authorized_shares=None, agent_start_date="2024-02-29",
    )

    filing = find_filing(entity["id"], filing_type="ANNUAL_REPORT", period_year=2025)
    assert filing["period_year"] == 2025, "first period is year(formation_date) + 1"
    assert filing["due_date"] == "2025-02-28", (
        f"Feb 29 clamps to Feb 28 in non-leap 2025 (a Friday, no roll); got {filing['due_date']}"
    )


def test_franchise_tax_cap_constant_applied(api):
    """PRD 3.7: "For a jurisdiction with `franchise_tax_method` equal to
    `SHARES_TIERED`, the tax is computed as follows: subtract 5000 free shares
    from the share count, round up the remainder to whole blocks of 10000
    shares, multiply the block count by 8500 cents, add a base of 17500 cents,
    and cap the result at 2000000 cents."

    Design: Corner/calculations/franchise_tax_cap_constant_applied
    """
    ctx = setup_base_entity(legal_name="Megacap Corp", authorized_shares=5000000)
    entity = ctx["entity"]
    filing = find_filing(entity["id"], filing_type="FRANCHISE_TAX", period_year=2026)
    prepare_filing(filing["id"])

    submitted = submit_filing(filing["id"])
    # uncapped: 17500 + ceil(4995000/10000) * 8500 = 17500 + 500 * 8500 = 4267500
    assert submitted["tax_assessed_cents"] == 2000000, (
        f"cap clamps 4267500 to 2000000, got {submitted['tax_assessed_cents']}"
    )
    assert submitted["penalty_cents"] == 0
    assert submitted["fee_cents"] == 2005000, "5000 report fee + 2000000 tax + 0 penalty"


def test_posture_excludes_future_scheduled_filings(api):
    """PRD 3.13: "The derivation first applies lazy overdue evaluation: filings
    in `SCHEDULED` or `PREPARED` whose `due_date` is before the current logical
    date become `OVERDUE`."
    PRD 3.13: "If neither condition holds, `suspended_since` is cleared, and
    posture is `DELINQUENT` if any filing is `OVERDUE`, else `GOOD_STANDING`."

    Design: Corner/calculations/posture_excludes_future_scheduled_filings
    """
    ctx = setup_base_entity(legal_name="Clean Corp")
    entity = ctx["entity"]

    filings = list_filings(entity["id"])
    assert len(filings) == 2
    assert all(f["status"] == "SCHEDULED" for f in filings), (
        "both period-2026 filings have due_date 2026-12-31, after the 2026-08-01 clock"
    )

    current = fetch_entity(entity["id"])
    assert current["compliance_posture"] == "GOOD_STANDING"
    assert current["suspended_since"] is None


def test_business_days_variant_counting(api):
    """PRD 3.7: "When the jurisdiction's `penalty_day_counting` is
    `CALENDAR_DAYS`, every day in that interval counts. When it is
    `BUSINESS_DAYS`, only Monday through Friday count; identical submit dates
    yield a smaller `days_late` whenever the interval spans a weekend."
    PRD 3.7: "The report-fee component is `report_fee_cents` multiplied by
    0.00041 and then by `days_late`, rounded half-up to whole cents."

    Design: Corner/calculations/business_days_variant_counting
    """
    set_clock("2026-06-20T00:00:00Z")  # a Saturday
    j2 = create_jurisdiction_ca()
    ag2 = create_agent(j2["id"], name="CA Agent Co", address="5 Agent Blvd")
    entity = activate_entity(
        j2["id"], ag2["id"], legal_name="Businessday Corp", formation_date="2025-06-14",
        authorized_shares=None,
    )
    filing = find_filing(entity["id"], filing_type="ANNUAL_REPORT", period_year=2026)
    assert filing["due_date"] == "2026-06-15"
    prepare_filing(filing["id"])

    submitted = submit_filing(filing["id"])
    # Interval (2026-06-15, 2026-06-20]: business days are Tue 16 - Fri 19 = 4;
    # the Saturday submit day does not count.
    assert submitted["days_late"] == 4
    assert submitted["tax_assessed_cents"] == 0, "ANNUAL_REPORT filings assess tax 0"
    # 10000 base + round_half_up(2500 * 0.00041 * 4) = 10000 + 4
    assert submitted["penalty_cents"] == 10004
    assert submitted["fee_cents"] == 12504, "2500 report fee + 0 tax + 10004 penalty"


def test_filing_calendar_pagination_and_envelope(api):
    """PRD 2.3: "`limit` controls the maximum number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls
    how many items are skipped; it defaults to 0."
    PRD 2.3: "The `meta` object of a list response contains `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/filing_calendar_pagination_and_envelope
    """
    ctx = setup_base_entity(legal_name="Pages Corp")
    entity = ctx["entity"]

    rows, meta = validate_paginated(
        api.list_filings(AUD1, params={"entity_id": entity["id"]})
    )
    assert meta["total_count"] == 2, "the generated period-2026 calendar holds 2 rows"
    assert meta["has_more"] is False
    assert meta["limit"] == 10, "default limit is 10"
    assert meta["offset"] == 0
    assert "api_request_id" in meta and "api_request_timestamp" in meta

    page1, meta1 = validate_paginated(
        api.list_filings(AUD1, params={"entity_id": entity["id"], "limit": 1, "offset": 0})
    )
    assert len(page1) == 1 and meta1["total_count"] == 2 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_filings(AUD1, params={"entity_id": entity["id"], "limit": 1, "offset": 1})
    )
    assert len(page2) == 1 and meta2["has_more"] is False

    assert page1[0]["id"] != page2[0]["id"], "pages are disjoint"
    assert {page1[0]["id"], page2[0]["id"]} == {f["id"] for f in rows}

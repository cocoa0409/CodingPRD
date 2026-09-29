"""Endpoint semantics: the side-effect-free coverage report and the operations sweep."""

from test_helpers import fixtures, get_success_data, validate_paginated
from test_helpers.constants import DEFAULT_CLOCK_UTC, clock_stamp
from test_helpers.factories import projected_window
from test_helpers.fixtures import COMPLIANCE, OFFICER, REGULATOR
from test_helpers.test_users import make_public_unit_treasurer_headers

NOON = "2026-08-01T12:00:00Z"
PAST_CURE = "2026-08-02T01:00:00Z"
ORIGINAL_BREACH_PASSED = "2026-08-03T00:30:00Z"
REWRITTEN_BREACH_PASSED = "2026-08-03T02:00:00Z"


def test_the_coverage_report_mirrors_the_account_without_touching_it(client):
    """Half the requirement is pledged, so the report shows a coverage ratio of exactly 5000 basis
    points on a DEFICIENT account; every figure it returns is the account's own stored value, the
    determination basis is read off the depository, the timestamp is the logical clock, and neither
    the treasurer's read nor the regulator's read moves the account's version.

    PRD: "Public unit reporting is served by a per-account **coverage report**, readable by the
    account's own treasurer, by a `BankComplianceOfficer` and by a `StateRegulator`."
    PRD: "It is a point-in-time projection rather than a stored entity, and it returns exactly ten
    values: `insured_amount_cents`, `uninsured_amount_cents`, `required_collateral_pct_bps`,
    `required_collateral_cents`, `assigned_collateral_value_cents`, `coverage_ratio_bps`,
    `collateral_status`, `pledging_mode`, the depository's `insurance_determination_basis`, and
    `report_as_of`, which is the logical clock at the moment the report was produced, rendered as an
    ISO 8601 UTC timestamp."
    PRD: "Coverage is measured by `coverage_ratio_bps`. When `required_collateral_cents` is zero the
    ratio is defined as 10000; otherwise it is `assigned_collateral_value_cents` multiplied by
    10000, divided by `required_collateral_cents`, floored to whole basis points."
    PRD: "- `UNSECURED → DEFICIENT` when `assigned_collateral_value_cents` is greater than zero and
    the ratio is below 10000."

    Design: Corner/endpoints/computed_read_coverage_report_matches_stored_account_fields
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        cusip="LOC-HALF",
        asset_type="LETTER_OF_CREDIT",
        par_value_cents=39_375_000,
    )
    allocation = fixtures.create_allocation(
        client, perimeter["agreement_id"], asset["id"], 39_375_000
    )
    assert allocation["allocated_collateral_value_cents"] == 39_375_000

    treasurer = make_public_unit_treasurer_headers(perimeter["public_unit_id"])
    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], treasurer), 200
    )
    version_before = account["version"]

    report = get_success_data(
        client.get_coverage_report(perimeter["account_id"], treasurer), 200
    )
    assert report["insured_amount_cents"] == 25_000_000
    assert report["uninsured_amount_cents"] == 75_000_000
    assert report["required_collateral_pct_bps"] == 10500
    assert report["required_collateral_cents"] == 78_750_000
    assert report["assigned_collateral_value_cents"] == 39_375_000
    assert report["coverage_ratio_bps"] == 5000
    assert report["coverage_ratio_bps"] == 39_375_000 * 10000 // 78_750_000
    assert report["collateral_status"] == "DEFICIENT"
    assert report["pledging_mode"] == "DEDICATED"
    assert report["insurance_determination_basis"] == "AGGREGATED_BY_UNIT"
    assert report["report_as_of"] == clock_stamp(DEFAULT_CLOCK_UTC)

    regulator_report = get_success_data(
        client.get_coverage_report(perimeter["account_id"], REGULATOR), 200
    )
    assert regulator_report == report
    compliance_report = get_success_data(
        client.get_coverage_report(perimeter["account_id"], COMPLIANCE), 200
    )
    assert compliance_report == report

    for field in (
        "insured_amount_cents",
        "uninsured_amount_cents",
        "required_collateral_pct_bps",
        "required_collateral_cents",
        "assigned_collateral_value_cents",
        "coverage_ratio_bps",
        "collateral_status",
        "pledging_mode",
    ):
        assert report[field] == account[field]

    bank = get_success_data(
        client.get_depository(perimeter["depository_id"], OFFICER), 200
    )
    assert report["insurance_determination_basis"] == bank["insurance_determination_basis"]

    unchanged = get_success_data(
        client.get_deposit_account(perimeter["account_id"], treasurer), 200
    )
    assert unchanged["version"] == version_before


def test_escalation_moves_the_breach_deadline_and_only_the_fourth_sweep_breaches(client):
    """The sweep is quiet before the cure deadline, escalates once past it and rewrites the breach
    deadline to escalated_at plus 24 hours — so a sweep at the deadline the call was born with
    breaches nothing — and only the sweep past the rewritten deadline breaches, suspending the bank
    and driving the cascade four levels down from an empty request body.

    PRD: "A call in `ISSUED` or `PARTIALLY_CURED` status whose `cure_deadline_at` the clock has
    reached or passed, while still standing before `breach_deadline_at`, is moved to `ESCALATED`
    with `escalated_at` stamped from the clock and its `version` incremented, after which the owning
    depository's `collateral_posture` is recomputed."
    PRD: "`breach_deadline_at` is computed at issuance as `cure_deadline_at` advanced by 24 hours of
    escalation grace, and it is re-stamped as `escalated_at` plus 24 hours if and when the sweep
    actually escalates the call."
    PRD: "A call already in `ESCALATED` status whose `breach_deadline_at` the clock has reached or
    passed is moved to `BREACHED` with its `version` incremented, and a breach is the gravest event
    in the system: the owning depository's `approval_status` is set to `SUSPENDED` if it was
    `APPROVED` — which fires hops two, three and four of the suspension cascade described in §3.1,
    restricting accounts, escalating public units and staleifying their open forecasts — and the
    depository's `collateral_posture` is set to `FROZEN`."
    PRD: "The sweep responds with four counters plus the clock it ran at:
    `escalated_margin_call_count`, `breached_margin_call_count`, `suspended_depository_count`,
    `stale_priced_asset_count` and `current_utc`."
    PRD: "The last of the counters is purely informational — it reports how many collateral assets
    have a `priced_at` more than 48 hours behind the logical clock, so operations can chase the
    pricing vendor, and the sweep mutates nothing on those assets."
    PRD: "Hop two, caused by hop one, moves every deposit account of that depository whose
    `funding_status` is `PENDING_FUNDING` or `FUNDED` to `RESTRICTED`, records `restricted_reason`
    as `DEPOSITORY_SUSPENDED` on each, and increments each account's `version`; a restricted
    account's `required_collateral_cents` is *not* zeroed, because a restricted balance still has to
    be collateralised."
    PRD: "Hop three, caused by hop two, recomputes `exposure_status` for every public unit that owns
    an account which just became restricted, and each such unit becomes `ESCALATED`."
    PRD: "Hop four, caused by hop three, moves every runoff forecast in `OPEN` status whose
    `deposit_account_id` belongs to one of those escalated units to `STALE` and sets its
    `requires_reforecast` flag to true."

    Design: Corner/endpoints/ops_run_daily_cycle_escalation_moves_the_breach_deadline_then_breaches
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    forecast = fixtures.file_forecast(
        client,
        perimeter["account_id"],
        perimeter["public_unit_id"],
        DEFAULT_CLOCK_UTC,
        "2026-08-31T00:00:00Z",
        [projected_window(DEFAULT_CLOCK_UTC, "2026-08-31T00:00:00Z", 100_000_000)],
    )
    assert forecast["status"] == "OPEN"
    idle_asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        cusip="LOC-IDLE",
        asset_type="LETTER_OF_CREDIT",
        par_value_cents=1_000_000,
    )
    assert idle_asset["priced_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    run = fixtures.create_mtm_run(
        client,
        perimeter["depository_id"],
        "2026-07-31T00:00:00Z",
        DEFAULT_CLOCK_UTC,
        basis="SUPERVISORY",
    )
    assert run["outcome"] == "DEFICIENT"
    call = fixtures.latest_margin_call(client, perimeter["depository_id"])
    assert call["cure_deadline_at"] == clock_stamp("2026-08-02T00:00:00Z")
    assert call["breach_deadline_at"] == clock_stamp("2026-08-03T00:00:00Z")

    fixtures.set_clock(client, NOON)
    quiet = fixtures.run_daily_cycle(client)
    assert quiet["escalated_margin_call_count"] == 0
    assert quiet["breached_margin_call_count"] == 0
    assert quiet["suspended_depository_count"] == 0
    assert quiet["stale_priced_asset_count"] == 0
    assert quiet["current_utc"] == clock_stamp(NOON)
    untouched = get_success_data(client.get_margin_call(call["id"], OFFICER), 200)
    assert untouched["status"] == "ISSUED"

    fixtures.set_clock(client, PAST_CURE)
    escalating = fixtures.run_daily_cycle(client)
    assert escalating["escalated_margin_call_count"] == 1
    assert escalating["breached_margin_call_count"] == 0
    assert escalating["stale_priced_asset_count"] == 0
    escalated = get_success_data(client.get_margin_call(call["id"], OFFICER), 200)
    assert escalated["status"] == "ESCALATED"
    assert escalated["escalated_at"] == clock_stamp(PAST_CURE)
    assert escalated["breach_deadline_at"] == clock_stamp("2026-08-03T01:00:00Z")

    fixtures.set_clock(client, ORIGINAL_BREACH_PASSED)
    grace = fixtures.run_daily_cycle(client)
    assert grace["breached_margin_call_count"] == 0
    assert grace["escalated_margin_call_count"] == 0
    assert grace["stale_priced_asset_count"] == 1
    still_escalated = get_success_data(client.get_margin_call(call["id"], OFFICER), 200)
    assert still_escalated["status"] == "ESCALATED"
    still_eligible = get_success_data(
        client.get_collateral_asset(idle_asset["id"], OFFICER), 200
    )
    assert still_eligible["eligibility_status"] == "ELIGIBLE"
    assert still_eligible["version"] == idle_asset["version"]

    fixtures.set_clock(client, REWRITTEN_BREACH_PASSED)
    breaking = fixtures.run_daily_cycle(client)
    assert breaking["breached_margin_call_count"] == 1
    assert breaking["suspended_depository_count"] == 1
    breached = get_success_data(client.get_margin_call(call["id"], OFFICER), 200)
    assert breached["status"] == "BREACHED"

    bank = get_success_data(
        client.get_depository(perimeter["depository_id"], OFFICER), 200
    )
    assert bank["approval_status"] == "SUSPENDED"
    assert bank["collateral_posture"] == "FROZEN"
    restricted = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert restricted["funding_status"] == "RESTRICTED"
    assert restricted["restricted_reason"] == "DEPOSITORY_SUSPENDED"
    assert restricted["required_collateral_cents"] == 78_750_000
    unit = get_success_data(
        client.get_public_unit(perimeter["public_unit_id"], REGULATOR), 200
    )
    assert unit["exposure_status"] == "ESCALATED"
    stale = get_success_data(client.get_runoff_forecast(forecast["id"], REGULATOR), 200)
    assert stale["status"] == "STALE"
    assert stale["requires_reforecast"] is True

    idempotent = fixtures.run_daily_cycle(client)
    assert idempotent["escalated_margin_call_count"] == 0
    assert idempotent["breached_margin_call_count"] == 0
    assert idempotent["suspended_depository_count"] == 0
    assert idempotent["stale_priced_asset_count"] == 1

    calls, meta = validate_paginated(
        client.list_margin_calls(OFFICER, {"depository_id": perimeter["depository_id"]})
    )
    assert meta["total_count"] == 1
    assert calls[0]["status"] == "BREACHED"

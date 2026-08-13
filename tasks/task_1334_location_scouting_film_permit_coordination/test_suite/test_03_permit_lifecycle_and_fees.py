"""Permit applications: submission gates, review gates, fees, OCC, listing."""
from test_helpers import (
    FO,
    LM,
    ApiErrorId,
    assert_permit_application,
    create_draft_permit,
    create_insurance_certificate_payload,
    create_permit_application_payload,
    get_success_data,
    is_iso8601_timestamp,
    set_clock,
    setup_accepted_scout_package,
    setup_basic_scenario,
    setup_draft_agreement,
    setup_executed_agreement,
    setup_production_with_executed_agreement,
    setup_under_review_permit,
    setup_verified_insurance,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Submission gates
# ---------------------------------------------------------------------------

def test_permit_submit_without_executed_agreement_rejected(api):
    """PRD §3.4: "an `EXECUTED` owner agreement whose window covers the requested
    `shoot_start_date` through `shoot_end_date` must exist for the production and
    location (else `ERR_AGREEMENT_NOT_EXECUTED`)"

    Design: Corner/state_machines/permit_submit_without_executed_agreement_rejected
    """
    scenario = setup_basic_scenario()
    production, location = scenario["production"], scenario["location"]
    setup_accepted_scout_package(production, location)
    agreement = setup_draft_agreement(production, location)
    # Agreement only PROPOSED — never accepted.
    get_success_data(api.propose_owner_agreement(production["id"], agreement["id"], 150_000, LM))
    permit = create_draft_permit(scenario)

    resp = api.submit_permit_application(production["id"], permit["id"], LM)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED)

    current = get_success_data(api.get_permit_application(production["id"], permit["id"], LM))
    assert current["status"] == "DRAFT"


def test_permit_submit_into_suspended_jurisdiction_rejected(api):
    """PRD §3.4: "the jurisdiction must be `ACTIVE` (else
    `ERR_JURISDICTION_SUSPENDED`)"
    PRD §3.1: "the film office may later suspend it, moving it to `SUSPENDED`,
    after which new permit submissions into it are rejected with
    `ERR_JURISDICTION_SUSPENDED`"

    Design: Corner/state_machines/permit_submit_into_suspended_jurisdiction_rejected
    """
    scenario = setup_production_with_executed_agreement()
    production = scenario["production"]
    get_success_data(api.suspend_jurisdiction(scenario["jurisdiction"]["id"], FO))
    permit = create_draft_permit(scenario)

    resp = api.submit_permit_application(production["id"], permit["id"], LM)
    validate_error(resp, ApiErrorId.ERR_JURISDICTION_SUSPENDED)

    current = get_success_data(api.get_permit_application(production["id"], permit["id"], LM))
    assert current["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Review gates and the lead-time rule
# ---------------------------------------------------------------------------

def test_permit_start_review_with_short_lead_time_rejected(api):
    """PRD §3.4: "Second, `lead_time_satisfied`: true exactly when
    `business_days_available` is at least the jurisdiction's
    `lead_time_business_days`."
    PRD §3.4: "The application lands in `SUBMITTED` either way; a short lead time
    does not block submission, it blocks review."
    PRD §3.5: "review may not start unless `lead_time_satisfied` is true,
    otherwise the request fails with `ERR_LEAD_TIME_SHORT`."

    Design: Corner/state_machines/permit_start_review_with_short_lead_time_rejected
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    # Submit on 2026-08-05 (Wed) for a window starting 2026-08-10 (Mon):
    # candidates Aug 6, 7, 10 -> 3 business days < lead 5.
    set_clock("2026-08-05T09:00:00Z")
    permit = create_draft_permit(scenario)
    permit = get_success_data(api.submit_permit_application(production_id, permit["id"], LM))
    assert permit["business_days_available"] == 3, (
        f"Expected business days Aug 6, 7, 10 = 3, got {permit['business_days_available']}"
    )
    assert permit["lead_time_satisfied"] is False

    resp = api.start_review_permit_application(production_id, permit["id"], FO)
    validate_error(resp, ApiErrorId.ERR_LEAD_TIME_SHORT)

    current = get_success_data(api.get_permit_application(production_id, permit["id"], LM))
    assert current["status"] == "SUBMITTED"


def test_start_review_on_draft_reports_invalid_state_not_lead_time(api):
    """PRD §2.7: "then whether the target resource's current state permits the
    requested transition at all (`ERR_INVALID_STATE`), then the business-rule
    checks specific to the operation (insurance sufficiency, lead time,
    notification adequacy, agreement chain, interval conflicts, caps, thresholds,
    funding, signatures, and the rest)"
    PRD §3.5: "The film office opens review by moving a `SUBMITTED` application to
    `UNDER_REVIEW`"

    Design: Difficulty/priority_pair_validation_conflict/start_review_state_vs_lead_time_priority
    """
    # Jurisdiction lead 5 with a window (2026-08-05..06) that would fail the
    # lead-time business check even if the application were submitted now.
    scenario = setup_production_with_executed_agreement(
        agreement_overrides={"shoot_start_date": "2026-08-05", "shoot_end_date": "2026-08-06"},
    )
    production_id = scenario["production"]["id"]
    set_clock("2026-08-04T09:00:00Z")
    permit = create_draft_permit(
        scenario, shoot_start_date="2026-08-05", shoot_end_date="2026-08-06",
    )

    resp = api.start_review_permit_application(production_id, permit["id"], FO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    current = get_success_data(api.get_permit_application(production_id, permit["id"], LM))
    assert current["status"] == "DRAFT"


def test_start_review_on_withdrawn_application_reports_invalid_state(api):
    """PRD §3.5: "A `LocationManager` may withdraw an application while it is in
    `DRAFT` or `SUBMITTED`, moving it to `WITHDRAWN`."
    PRD §2.7: "then whether the target resource's current state permits the
    requested transition at all (`ERR_INVALID_STATE`), then the business-rule
    checks specific to the operation (insurance sufficiency, lead time,
    notification adequacy, agreement chain, interval conflicts, caps, thresholds,
    funding, signatures, and the rest)"
    PRD §3.4: "a short lead time does not block submission, it blocks review."

    Design: Difficulty/priority_pair_validation_conflict/start_review_state_vs_lead_time_priority
    """
    # Lead time already short at submit (3 < 5), then withdraw from SUBMITTED:
    # start-review on the terminal application must surface the state check, not
    # the temporal business check.
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    set_clock("2026-08-05T09:00:00Z")
    permit = create_draft_permit(scenario)
    permit = get_success_data(api.submit_permit_application(production_id, permit["id"], LM))
    assert permit["lead_time_satisfied"] is False, "Setup: lead time must be short (3 < 5)"
    permit = get_success_data(api.withdraw_permit_application(production_id, permit["id"], LM))
    assert permit["status"] == "WITHDRAWN"

    resp = api.start_review_permit_application(production_id, permit["id"], FO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    current = get_success_data(api.get_permit_application(production_id, permit["id"], LM))
    assert current["status"] == "WITHDRAWN"


def test_issue_without_verified_insurance_rejected(api):
    """PRD §3.5: "Deciding `ISSUE` directly from `UNDER_REVIEW` requires a
    `VERIFIED` insurance certificate for the production and the pinned
    jurisdiction whose inclusive coverage window from `effective_date` through
    `expiry_date` spans the entire requested shoot window; without one the
    decision is rejected with `ERR_INSURANCE_INSUFFICIENT`."

    Design: Corner/state_machines/issue_without_verified_insurance_rejected
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    set_clock("2026-08-03T09:00:00Z")
    permit = setup_under_review_permit(scenario)
    assert permit["status"] == "UNDER_REVIEW"
    # Certificate stays PRESENTED — never verified.
    get_success_data(api.create_insurance_certificate(
        production_id,
        create_insurance_certificate_payload(scenario["jurisdiction"]["id"]),
        LM,
    ))

    resp = api.decide_permit_application(production_id, permit["id"], "ISSUE", FO)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_INSUFFICIENT)

    current = get_success_data(api.get_permit_application(production_id, permit["id"], LM))
    assert current["status"] == "UNDER_REVIEW"


def test_conditional_issue_without_acked_notification_rejected(api):
    """PRD §3.5: "Deciding `ISSUE` from `CONDITIONALLY_APPROVED` requires that
    same certificate and additionally an `ACKED` notification record attached to
    this application, else `ERR_NOTIFICATION_DEFICIENT`."

    Design: Corner/state_machines/conditional_issue_without_acked_notification_rejected
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    set_clock("2026-08-03T09:00:00Z")
    permit = setup_under_review_permit(scenario)
    setup_verified_insurance(scenario)
    permit = get_success_data(
        api.decide_permit_application(production_id, permit["id"], "APPROVE_WITH_CONDITIONS", FO)
    )
    assert permit["status"] == "CONDITIONALLY_APPROVED"

    resp = api.decide_permit_application(production_id, permit["id"], "ISSUE", FO)
    validate_error(resp, ApiErrorId.ERR_NOTIFICATION_DEFICIENT)

    current = get_success_data(api.get_permit_application(production_id, permit["id"], LM))
    assert current["status"] == "CONDITIONALLY_APPROVED"


# ---------------------------------------------------------------------------
# Withdraw lifecycle and status filtering
# ---------------------------------------------------------------------------

def test_permit_withdraw_from_withdrawn_returns_invalid_state(api):
    """PRD §3.5: "A `LocationManager` may withdraw an application while it is in
    `DRAFT` or `SUBMITTED`, moving it to `WITHDRAWN`."
    PRD §2.7: "then whether the target resource's current state permits the
    requested transition at all (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/permit_withdraw_from_withdrawn_returns_invalid_state
    """
    scenario = setup_basic_scenario()
    production_id = scenario["production"]["id"]
    permit = create_draft_permit(scenario)
    permit = get_success_data(api.withdraw_permit_application(production_id, permit["id"], LM))
    assert permit["status"] == "WITHDRAWN"

    resp = api.withdraw_permit_application(production_id, permit["id"], LM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    current = get_success_data(api.get_permit_application(production_id, permit["id"], LM))
    assert current["status"] == "WITHDRAWN"


def test_permit_list_filter_by_status(api):
    """PRD §4: "List permit applications (filterable by `location_id`,
    `jurisdiction_id`, `status`, `amendment_of_id`)"
    PRD §3.5: "A `LocationManager` may withdraw an application while it is in
    `DRAFT` or `SUBMITTED`, moving it to `WITHDRAWN`."

    Design: Corner/endpoints/permit_list_filter_by_status
    """
    scenario = setup_basic_scenario()
    production_id = scenario["production"]["id"]
    first = create_draft_permit(scenario)
    second = create_draft_permit(
        scenario, shoot_start_date="2026-08-13", shoot_end_date="2026-08-14"
    )
    get_success_data(api.withdraw_permit_application(production_id, first["id"], LM))

    withdrawn, meta_w = validate_paginated(
        api.list_permit_applications(production_id, LM, params={"status": "WITHDRAWN"})
    )
    assert meta_w["total_count"] == 1
    assert [p["id"] for p in withdrawn] == [first["id"]]

    drafts, meta_d = validate_paginated(
        api.list_permit_applications(production_id, LM, params={"status": "DRAFT"})
    )
    assert meta_d["total_count"] == 1
    assert [p["id"] for p in drafts] == [second["id"]]


# ---------------------------------------------------------------------------
# Optimistic concurrency on permit create (amendments)
# ---------------------------------------------------------------------------

def test_permit_amend_stale_version_rejected(api):
    """PRD §2.6: "If that value does not match the Production's current `version`
    — because another writer has advanced the Production since the client last
    read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412): the
    client's view of which applications are live is stale."
    PRD §3.4: "On creation the application is born `DRAFT`, its `jurisdiction_id`
    is copied from the location and pinned there for the life of the application,
    and the parent Production's `version` increments by one."

    Design: Corner/errors/permit_amend_stale_version_rejected
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    stale_version = scenario["production"]["version"]
    first = create_draft_permit(scenario, expected_production_version=stale_version)
    # The first create advanced Production.version beyond the captured value.
    assert get_success_data(api.get_production(production_id, LM))["version"] != stale_version

    payload = create_permit_application_payload(
        scenario["location"]["id"], stale_version,
        shoot_start_date="2026-08-11", shoot_end_date="2026-08-12",
        amendment_of_id=first["id"],
    )
    resp = api.create_permit_application(production_id, payload, LM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    current = get_success_data(api.get_permit_application(production_id, first["id"], LM))
    assert current["status"] == "DRAFT", "No supersede may happen on a rejected create"

    amendments, meta = validate_paginated(api.list_amendments_of(first["id"], LM))
    assert meta["total_count"] == 0
    assert amendments == []


# ---------------------------------------------------------------------------
# Fee calculation: business-day model and the cast-size tier
# ---------------------------------------------------------------------------

def _setup_cast_pair(api):
    """One jurisdiction/location; two productions at cast 50 and 51, each with an
    EXECUTED agreement and a submitted permit for 2026-08-10..12, lanes 1."""
    scenario = setup_basic_scenario()
    jurisdiction, owner, location = (
        scenario["jurisdiction"], scenario["owner"], scenario["location"],
    )
    set_clock("2026-08-03T09:00:00Z")
    submitted = {}
    for key, cast in (("eq", 50), ("gt", 51)):
        production = get_success_data(api.create_production(
            {"title": f"Prod {key}", "production_company": "Co A", "cast_size": cast,
             "umbrella_liability_limit_cents": 100_000_000}, LM,
        ))
        setup_accepted_scout_package(production, location)
        setup_executed_agreement(production, location, owner, rate=150_000)
        sub_scenario = dict(scenario)
        sub_scenario["production"] = production
        permit = create_draft_permit(sub_scenario, closed_lanes=1, shoot_hours_per_day=8)
        submitted[key] = get_success_data(
            api.submit_permit_application(production["id"], permit["id"], LM)
        )
    return scenario, submitted


def test_cast_size_exactly_at_threshold_pays_unmultiplied_subtotal(api):
    """PRD §3.4: "If the production's `cast_size` is strictly greater than the
    jurisdiction's `large_cast_threshold`, the fee is the subtotal multiplied by
    `large_cast_multiplier_bps` and divided by ten thousand, with a single floor
    applied at that final multiplication and no intermediate rounding; otherwise
    the fee is the subtotal unchanged."
    PRD §3.4: "The subtotal is the jurisdiction's `base_fee_cents`, plus the day
    count times `per_day_fee_cents`, plus the day count times `closed_lanes` times
    `per_lane_fee_cents`."

    Design: Difficulty/boundary_precision_check/cast_size_exactly_at_threshold_no_multiplier
    """
    _, submitted = _setup_cast_pair(api)
    eq = submitted["eq"]
    assert_permit_application(eq)
    # cast 50 == threshold 50: not strictly greater, no multiplier.
    # Business days in 2026-08-10..12 = 3 -> 100000 + 3*50000 + 3*1*20000.
    assert eq["fee_cents"] == 310_000, (
        f"cast_size 50 at the threshold must pay the plain subtotal 310000, got {eq['fee_cents']}"
    )


def test_cast_size_one_above_threshold_pays_multiplied_fee(api):
    """PRD §3.4: "If the production's `cast_size` is strictly greater than the
    jurisdiction's `large_cast_threshold`, the fee is the subtotal multiplied by
    `large_cast_multiplier_bps` and divided by ten thousand, with a single floor
    applied at that final multiplication and no intermediate rounding"
    PRD §2.8: "Basis-point multipliers are divided by ten thousand."

    Design: Difficulty/boundary_precision_check/cast_size_exactly_at_threshold_no_multiplier
    """
    _, submitted = _setup_cast_pair(api)
    gt = submitted["gt"]
    # cast 51 > threshold 50: floor(310000 * 12500 / 10000) = 387500.
    assert gt["fee_cents"] == 387_500, (
        f"cast_size 51 over the threshold must pay floor(310000 * 12500/10000) = 387500, got {gt['fee_cents']}"
    )
    # Same inputs on the at-threshold production stay unmultiplied.
    assert submitted["eq"]["fee_cents"] == 310_000


def test_submit_persists_business_day_fee_over_weekend_window(api):
    """PRD §3.4: "The authoritative fee computed at submission uses the
    business-day model: the day count includes only dates of the same window that
    are business days under the same weekend-and-holiday rule as the lead-time
    count, so a window spanning a weekend yields a strictly smaller authoritative
    fee than the displayed calendar-day estimate for the same inputs."
    PRD §3.4: "The subtotal is the jurisdiction's `base_fee_cents`, plus the day
    count times `per_day_fee_cents`, plus the day count times `closed_lanes` times
    `per_lane_fee_cents`."

    Design: Difficulty/dual_variant_calc/permit_fee_business_vs_calendar_day_model_weekend_window
    """
    scenario = setup_production_with_executed_agreement(
        jurisdiction_overrides={"lead_time_business_days": 2},
        agreement_overrides={"shoot_start_date": "2026-08-08", "shoot_end_date": "2026-08-11"},
    )
    production_id = scenario["production"]["id"]
    set_clock("2026-08-05T09:00:00Z")
    permit = create_draft_permit(
        scenario,
        shoot_start_date="2026-08-08", shoot_end_date="2026-08-11",
        closed_lanes=2, shoot_hours_per_day=12,
    )
    submitted = get_success_data(api.submit_permit_application(production_id, permit["id"], LM))

    # Business-day model: days = Aug 10, 11 = 2 -> 100000 + 2*50000 + 2*2*20000.
    assert submitted["fee_cents"] == 280_000, (
        f"Authoritative business-day fee must be 280000, got {submitted['fee_cents']}"
    )
    # The calendar-day model over the same window would give 460000 (4 days).
    assert submitted["fee_cents"] != 460_000
    assert submitted["lead_time_satisfied"] is True
    assert submitted["status"] == "SUBMITTED"


def test_submit_counts_business_days_with_shoot_date_inclusion_rule(api):
    """PRD §3.4: "First, `business_days_available`: the count of dates strictly
    after the submission date and on or before `shoot_start_date` — the submission
    date itself is excluded, the shoot date is included if it qualifies — that
    fall on neither a Saturday nor a Sunday nor any date in the pinned
    jurisdiction's `holidays`."

    Design: Difficulty/dual_variant_calc/permit_fee_business_vs_calendar_day_model_weekend_window
    """
    scenario = setup_production_with_executed_agreement(
        jurisdiction_overrides={"lead_time_business_days": 2},
        agreement_overrides={"shoot_start_date": "2026-08-08", "shoot_end_date": "2026-08-11"},
    )
    production_id = scenario["production"]["id"]
    set_clock("2026-08-05T09:00:00Z")
    permit = create_draft_permit(
        scenario,
        shoot_start_date="2026-08-08", shoot_end_date="2026-08-11",
        closed_lanes=2, shoot_hours_per_day=12,
    )
    submitted = get_success_data(api.submit_permit_application(production_id, permit["id"], LM))

    # Submitted Wed 2026-08-05, shoot starts Sat 2026-08-08: candidates
    # Aug 6 (Thu), Aug 7 (Fri), Aug 8 (Sat) -> business days Aug 6, 7 = 2.
    assert submitted["business_days_available"] == 2
    assert is_iso8601_timestamp(submitted["submitted_at"])
    assert submitted["fee_cents"] == 100_000 + 2 * 50_000 + 2 * 2 * 20_000


def test_business_days_excludes_jurisdiction_holidays(api):
    """PRD §3.4: "First, `business_days_available`: the count of dates strictly
    after the submission date and on or before `shoot_start_date` — the submission
    date itself is excluded, the shoot date is included if it qualifies — that
    fall on neither a Saturday nor a Sunday nor any date in the pinned
    jurisdiction's `holidays`."
    PRD §3.1: "an optional `holidays` array of ISO `YYYY-MM-DD` dates that
    defaults to an empty list and is excluded from business-day counting"

    Design: Corner/calculations/business_days_excludes_jurisdiction_holidays
    """
    scenario = setup_production_with_executed_agreement(
        jurisdiction_overrides={
            "code": "PASADENA", "name": "Pasadena",
            "lead_time_business_days": 4, "notification_lead_calendar_days": 2,
            "notification_radius_ft": 300, "base_fee_cents": 80_000,
            "per_day_fee_cents": 40_000, "per_lane_fee_cents": 15_000,
            "holidays": ["2026-08-05"],
        },
        location_overrides={"name": "Loc P", "address": "50 Colorado Blvd"},
    )
    production_id = scenario["production"]["id"]
    set_clock("2026-08-03T09:00:00Z")
    permit = create_draft_permit(scenario, closed_lanes=0, shoot_hours_per_day=8)
    submitted = get_success_data(api.submit_permit_application(production_id, permit["id"], LM))

    # Candidates Aug 4, 5, 6, 7, 10 minus the Aug 5 holiday -> 4 business days.
    assert submitted["business_days_available"] == 4, (
        f"Expected Aug 4, 6, 7, 10 = 4 (holiday Aug 5 excluded), got {submitted['business_days_available']}"
    )
    assert submitted["lead_time_satisfied"] is True, "4 >= lead 4 must satisfy the gate"
    # Fee: Aug 10, 11, 12 are all business days -> 80000 + 3*40000 + 0 lanes.
    assert submitted["fee_cents"] == 200_000


def test_permit_fee_computed_field_in_submit_response_immediately(api):
    """PRD §3.4: "The submission also prices the application into `fee_cents`"
    PRD §3.4: "The subtotal is the jurisdiction's `base_fee_cents`, plus the day
    count times `per_day_fee_cents`, plus the day count times `closed_lanes` times
    `per_lane_fee_cents`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/calculations/permit_fee_computed_field_in_submit_response_immediately
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    set_clock("2026-08-03T09:00:00Z")
    permit = create_draft_permit(scenario, closed_lanes=2, shoot_hours_per_day=12)

    resp = api.submit_permit_application(production_id, permit["id"], LM)
    data = validate_success(resp)
    # Aug 10, 11, 12 are all business days: 100000 + 3*50000 + 3*2*20000 = 370000.
    assert data["fee_cents"] == 370_000, (
        f"Submit response itself must carry fee_cents 370000, got {data.get('fee_cents')}"
    )
    assert data["status"] == "SUBMITTED"
    assert data["lead_time_satisfied"] is True

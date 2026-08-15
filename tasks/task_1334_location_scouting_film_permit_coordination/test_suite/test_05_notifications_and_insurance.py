"""Neighborhood notification adequacy and insurance certificate verification."""
from test_helpers import (
    FO,
    LM,
    ApiErrorId,
    assert_insurance_certificate,
    assert_notification_record,
    create_insurance_certificate_payload,
    create_notification_payload,
    get_success_data,
    set_clock,
    setup_basic_scenario,
    setup_issued_permit,
    setup_production_with_executed_agreement,
    sweep,
    validate_error,
    validate_paginated,
    validate_success,
)


def _scenario_with_issued_permit(api):
    """EXECUTED agreement -> ISSUED permit (window 2026-08-10..12), no notification."""
    scenario = setup_production_with_executed_agreement()
    permit, certificate, _ = setup_issued_permit(
        scenario, clock="2026-08-03T09:00:00Z", with_notification=False,
    )
    scenario["permit"] = permit
    scenario["certificate"] = certificate
    return scenario


# ---------------------------------------------------------------------------
# Difficulty: notification adequacy boundary (inclusive >=)
# ---------------------------------------------------------------------------

def test_notification_exactly_lead_days_is_adequate(api):
    """PRD §3.5: "`notification_adequate`, true exactly when
    `calendar_days_before_shoot` is at least the pinned jurisdiction's
    `notification_lead_calendar_days` **and** `radius_ft_used` is at least its
    `notification_radius_ft`."
    PRD §3.5: "Both comparisons are inclusive at the boundary: a posting made
    exactly the required number of days ahead at exactly the required radius is
    adequate."
    PRD §3.5: "An adequate record is born `POSTED`"
    PRD §3.5: "The film office acknowledges a `POSTED` record, moving it to
    `ACKED`"

    Design: Difficulty/boundary_precision_check/notification_exactly_lead_days_is_adequate
    """
    scenario = _scenario_with_issued_permit(api)
    production_id = scenario["production"]["id"]
    # Post exactly 3 calendar days before the 2026-08-10 shoot start, at exactly
    # the 500 ft radius: both inclusive boundaries met.
    set_clock("2026-08-07T09:00:00Z")
    record = get_success_data(api.create_notification(
        production_id, create_notification_payload(scenario["permit"]["id"]), LM,
    ))
    assert_notification_record(record)
    assert record["calendar_days_before_shoot"] == 3
    assert record["notification_adequate"] is True
    assert record["status"] == "POSTED"

    acked = get_success_data(api.acknowledge_notification(production_id, record["id"], FO))
    assert acked["status"] == "ACKED"


def test_notification_one_day_short_and_radius_short_are_deficient(api):
    """PRD §3.5: "`notification_adequate`, true exactly when
    `calendar_days_before_shoot` is at least the pinned jurisdiction's
    `notification_lead_calendar_days` **and** `radius_ft_used` is at least its
    `notification_radius_ft`."
    PRD §3.5: "An adequate record is born `POSTED`; an inadequate one is born
    directly `DEFICIENT` with no review step."

    Design: Difficulty/boundary_precision_check/notification_exactly_lead_days_is_adequate
    """
    scenario = _scenario_with_issued_permit(api)
    production_id = scenario["production"]["id"]

    # One day short: 2 calendar days before shoot (< 3 required).
    set_clock("2026-08-08T09:00:00Z")
    short_days = get_success_data(api.create_notification(
        production_id, create_notification_payload(scenario["permit"]["id"]), LM,
    ))
    assert short_days["calendar_days_before_shoot"] == 2
    assert short_days["notification_adequate"] is False
    assert short_days["status"] == "DEFICIENT"

    # Radius short (499 < 500) with days back at the boundary: still DEFICIENT.
    set_clock("2026-08-07T09:00:00Z")
    short_radius = get_success_data(api.create_notification(
        production_id,
        create_notification_payload(scenario["permit"]["id"], radius_ft_used=499),
        LM,
    ))
    assert short_radius["calendar_days_before_shoot"] == 3
    assert short_radius["notification_adequate"] is False
    assert short_radius["status"] == "DEFICIENT"


def test_notification_acknowledge_deficient_returns_invalid_state(api):
    """PRD §3.5: "An adequate record is born `POSTED`; an inadequate one is born
    directly `DEFICIENT` with no review step. The film office acknowledges a
    `POSTED` record, moving it to `ACKED` — but only when `notification_adequate`
    is true, otherwise `ERR_NOTIFICATION_DEFICIENT`."
    PRD §2.7: "then whether the target resource's current state permits the
    requested transition at all (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/notification_acknowledge_deficient_returns_invalid_state
    """
    scenario = _scenario_with_issued_permit(api)
    production_id = scenario["production"]["id"]
    # 2026-08-09 is 1 calendar day before the 2026-08-10 shoot start (< 3).
    set_clock("2026-08-09T09:00:00Z")
    record = get_success_data(api.create_notification(
        production_id, create_notification_payload(scenario["permit"]["id"]), LM,
    ))
    assert record["status"] == "DEFICIENT", "Setup: inadequate record is born DEFICIENT"

    resp = api.acknowledge_notification(production_id, record["id"], FO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    # Re-read via the cross-scope list endpoint for a fresh state assertion.
    rows, _ = validate_paginated(api.list_notifications_of_permit(scenario["permit"]["id"], LM))
    assert rows[0]["status"] == "DEFICIENT"


# ---------------------------------------------------------------------------
# Insurance verification gates and lapse
# ---------------------------------------------------------------------------

def test_insurance_verify_below_minimum_limit_rejected(api):
    """PRD §3.5: "the limit must be at least the jurisdiction's
    `min_liability_limit_cents` (a shortfall fails with
    `ERR_INSURANCE_INSUFFICIENT`)"

    Design: Corner/state_machines/insurance_verify_below_minimum_limit_rejected
    """
    scenario = setup_basic_scenario()
    production_id = scenario["production"]["id"]
    certificate = get_success_data(api.create_insurance_certificate(
        production_id,
        create_insurance_certificate_payload(
            scenario["jurisdiction"]["id"], umbrella_limit_cents=99_999_999,
        ),
        LM,
    ))

    resp = api.verify_insurance_certificate(production_id, certificate["id"], FO)
    validate_error(resp, ApiErrorId.ERR_INSURANCE_INSUFFICIENT)

    rows, _ = validate_paginated(api.list_insurance_certificates(production_id, LM))
    assert rows[0]["status"] == "PRESENTED"


def test_insurance_verify_empty_indemnity_rejected(api):
    """PRD §3.5: "the indemnity clause reference must be non-empty (an empty one
    fails with `ERR_INDEMNITY_MISSING`)"

    Design: Corner/state_machines/insurance_verify_empty_indemnity_rejected
    """
    scenario = setup_basic_scenario()
    production_id = scenario["production"]["id"]
    certificate = get_success_data(api.create_insurance_certificate(
        production_id,
        create_insurance_certificate_payload(
            scenario["jurisdiction"]["id"], indemnity_clause_ref="",
        ),
        LM,
    ))

    resp = api.verify_insurance_certificate(production_id, certificate["id"], FO)
    validate_error(resp, ApiErrorId.ERR_INDEMNITY_MISSING)

    rows, _ = validate_paginated(api.list_insurance_certificates(production_id, LM))
    assert rows[0]["status"] == "PRESENTED"


def test_insurance_certificate_lapses_via_ops_sweep(api):
    """PRD §3.5: "When the logical clock passes a verified certificate's
    `expiry_date`, the operations sweep lapses it to `LAPSED`."
    PRD §2.5: "lapses `VERIFIED` insurance certificates whose `expiry_date` has
    passed (to `LAPSED`)"

    Design: Corner/state_machines/insurance_certificate_lapses_via_ops_sweep
    """
    set_clock("2026-08-01T09:00:00Z")
    scenario = setup_basic_scenario()
    production_id = scenario["production"]["id"]
    certificate = get_success_data(api.create_insurance_certificate(
        production_id,
        create_insurance_certificate_payload(
            scenario["jurisdiction"]["id"], expiry_date="2026-08-20",
        ),
        LM,
    ))
    verified = get_success_data(
        api.verify_insurance_certificate(production_id, certificate["id"], FO)
    )
    assert verified["status"] == "VERIFIED"

    set_clock("2026-08-21T00:00:00Z")
    sweep()

    rows, _ = validate_paginated(api.list_insurance_certificates(production_id, LM))
    assert len(rows) == 1
    assert rows[0]["status"] == "LAPSED"
    assert_insurance_certificate(rows[0])

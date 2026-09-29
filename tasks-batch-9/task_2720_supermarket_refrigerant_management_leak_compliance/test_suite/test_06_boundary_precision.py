"""
Three different boundaries on three different endpoints: a percentage against a
threshold, a zero-day citation against a money total, and a cumulative day budget
against its statutory cap.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_EXTENSION_DAY_CAP_EXCEEDED
from test_helpers.assertions import (
    assert_extension_budget,
    assert_instant,
    assert_leak_event_schedule,
    assert_mass,
    assert_money,
    assert_penalty_exposure,
    assert_store_posture,
)
from test_helpers.test_users import REGULATOR_HEADERS
from test_helpers.types import (
    DECISION_APPROVE,
    EXTENSION_APPROVED,
    EXTENSION_PENDING,
    INSPECTION_OPEN,
    POSTURE_AT_RISK,
    POSTURE_COMPLIANT,
    REASON_SUPPLY_CHAIN_DELAY,
    SEVERITY_MAJOR,
)


# ─── the leak-rate threshold is inclusive ─────────────────────────────


def _system_just_under_the_threshold(api):
    """
    A 100.0 lb commercial rack holding 80.0 lbs, topped up by 19.9 lbs so the
    rolling leak rate lands one tenth of a point below its 20.0 percent
    threshold. One more tenth of a pound puts it exactly on the boundary.
    """
    env = X.base_env(api, with_second_technician=False)
    env["record_under"] = X.file_service_record(
        api,
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        cylinder_id=env["cyl1_id"],
        refrigerant_added_lbs=19.9,
        performed_at="2026-08-01T00:00:00Z",
        duration_minutes=60,
    )
    return env


def test_leak_rate_one_tenth_below_the_threshold_opens_no_event(api):
    """
    19.9 percent on a 20.0 percent threshold is below the boundary, so no event
    exists and the store's posture is untouched.

    Design: Difficulty/boundary_precision_check/leak_rate_exactly_at_threshold_opens_event_on_service_record
    """
    env = _system_just_under_the_threshold(api)

    assert_money(env["system"]["threshold_pct"], 20.0, "threshold_pct")
    assert_mass(
        env["record_under"]["system_charge_after_lbs"], 99.9, "system_charge_after_lbs"
    )
    assert_money(env["record_under"]["leak_rate_pct_after"], 19.9, "leak_rate_pct_after")

    assert X.list_leak_events(api, system_id=env["system_id"])["meta"]["total_count"] == 0
    assert_store_posture(
        X.get_store(api, env["store_id"]), compliance_status=POSTURE_COMPLIANT
    )


def test_leak_rate_exactly_at_the_threshold_opens_the_event(api):
    """
    The equality case falls on the trigger side: reaching exactly 20.0 percent
    opens one event stamped with the boundary rate and the triggering record.

    Design: Difficulty/boundary_precision_check/leak_rate_exactly_at_threshold_opens_event_on_service_record
    """
    env = _system_just_under_the_threshold(api)

    # §2.4: `performed_at` may not lie in the future relative to the logical
    # clock, so the clock is moved to the instant of the boundary top-up.
    X.set_clock(api, "2026-08-01T03:00:00Z")
    record_at = X.file_service_record(
        api,
        env["system_id"],
        env["tech1_id"],
        env["eq1_id"],
        cylinder_id=env["cyl1_id"],
        refrigerant_added_lbs=0.1,
        performed_at="2026-08-01T03:00:00Z",
        duration_minutes=60,
    )
    assert_mass(record_at["system_charge_after_lbs"], 100.0, "system_charge_after_lbs")
    assert_money(record_at["leak_rate_pct_after"], 20.0, "leak_rate_pct_after")

    listing = X.list_leak_events(api, system_id=env["system_id"])
    assert listing["meta"]["total_count"] == 1

    event = listing["data"][0]
    assert_money(
        event["leak_rate_pct_at_detection"], 20.0, "leak_rate_pct_at_detection"
    )
    assert_money(event["threshold_pct_applied"], 20.0, "threshold_pct_applied")
    assert_instant(event["detected_at"], "2026-08-01T03:00:00Z", "detected_at")
    assert_leak_event_schedule(event, initial_repair_deadline="2026-08-31T03:00:00Z")
    assert event["triggering_service_record_id"] == record_at["id"]

    assert_mass(
        X.get_cylinder(api, env["cyl1_id"])["current_contents_lbs"],
        20.0,
        "current_contents_lbs",
    )
    assert_store_posture(
        X.get_store(api, env["store_id"]), compliance_status=POSTURE_AT_RISK
    )


# ─── a zero-day citation is enumerated but priced at nothing ──────────


def _bare_store_with_an_empty_inspection(api):
    """
    A store with no systems at all, so it is COMPLIANT and priced at the 1.00
    multiplier, carrying one inspection opened with no citations whatsoever.
    """
    X.set_clock(api, "2026-08-01T00:00:00Z")
    store = X.create_store(api)
    empty = X.open_inspection(api, store["id"], citations=[])
    return {"store_id": store["id"], "store": store, "inspection_empty": empty}


def test_inspection_with_no_citations_prices_to_zero_uncapped(api):
    """
    The empty-collection case: no citations, no money, and the cap is not
    reported as having bound anything.

    Design: Difficulty/boundary_precision_check/zero_day_citation_enumerated_but_contributes_nothing_on_inspection
    """
    env = _bare_store_with_an_empty_inspection(api)

    assert_store_posture(
        X.get_store(api, env["store_id"]), compliance_status=POSTURE_COMPLIANT
    )
    assert_penalty_exposure(
        env["inspection_empty"],
        penalty_exposure_usd=0.00,
        chronic_multiplier_applied=1.00,
        capped=False,
    )


def test_zero_day_major_citation_is_enumerated_yet_adds_no_money(api):
    """
    The highest per-day rate multiplied by zero days is zero, so the citation is
    still returned and counted while the money stays at 0.00 — the citation count
    and the exposure are independent.

    Design: Difficulty/boundary_precision_check/zero_day_citation_enumerated_but_contributes_nothing_on_inspection
    """
    env = _bare_store_with_an_empty_inspection(api)

    inspection = validate_success(
        api.create_inspection(
            F.inspection_payload(
                env["store_id"],
                citations=[
                    F.citation(
                        citation_code="608-ADMIN-OBSERVATION",
                        severity=SEVERITY_MAJOR,
                        violation_days=0,
                    )
                ],
            ),
            REGULATOR_HEADERS,
        ),
        expected_status=201,
    )
    assert_penalty_exposure(inspection, penalty_exposure_usd=0.00, capped=False)

    citations = inspection["citations"]
    assert len(citations) == 1
    assert citations[0]["severity"] == SEVERITY_MAJOR
    assert citations[0]["violation_days"] == 0

    assert inspection["status"] == INSPECTION_OPEN
    assert_instant(
        inspection["response_deadline"], "2026-08-31T00:00:00Z", "response_deadline"
    )
    assert_store_posture(
        X.get_store(api, env["store_id"]), penalty_exposure_total_usd=0.00
    )


# ─── the extension budget is an aggregate cap ─────────────────────────


def _event_with_twenty_days_granted_and_two_pending_requests(api):
    """
    A manually declared event whose 30-day budget is 20 days spent, plus a
    pending 10-day request that lands exactly on the cap and a pending one-day
    request that would breach it.
    """
    env = X.manual_event_env(api)
    er1 = X.file_extension_request(api, env["event_id"])
    X.approve_extension_request(api, er1["id"], 20)
    er2 = X.file_extension_request(
        api,
        env["event_id"],
        reason_code=REASON_SUPPLY_CHAIN_DELAY,
        requested_days=10,
        justification="replacement rack delayed at port",
    )
    er3 = X.file_extension_request(
        api,
        env["event_id"],
        reason_code=REASON_SUPPLY_CHAIN_DELAY,
        requested_days=1,
        justification="one final day for the crane crew",
    )
    env["er1_id"] = er1["id"]
    env["er2_id"] = er2["id"]
    env["er3_id"] = er3["id"]
    return env


def test_first_twenty_days_leave_ten_of_the_budget(api):
    """
    The starting position of the boundary: 20 granted, 10 remaining, and the
    repair deadline pushed out by exactly those 20 days.

    Design: Difficulty/boundary_precision_check/extension_total_exactly_at_thirty_day_cap_approves_thirty_first_day_rejected
    """
    env = _event_with_twenty_days_granted_and_two_pending_requests(api)

    event = X.get_leak_event(api, env["event_id"])
    assert_extension_budget(event, granted_total=20, remaining=10)
    assert_leak_event_schedule(
        event,
        initial_repair_deadline="2026-08-31T00:00:00Z",
        repair_deadline="2026-09-20T00:00:00Z",
    )


def test_approval_landing_exactly_on_the_cap_succeeds(api):
    """
    The cap bounds the aggregate, and 20 plus 10 is exactly 30, so the grant is
    approved and the budget is spent down to zero rather than refused.

    Design: Difficulty/boundary_precision_check/extension_total_exactly_at_thirty_day_cap_approves_thirty_first_day_rejected
    """
    env = _event_with_twenty_days_granted_and_two_pending_requests(api)

    decided = X.approve_extension_request(api, env["er2_id"], 10)
    assert decided["status"] == EXTENSION_APPROVED
    assert decided["granted_days"] == 10
    assert_instant(decided["deadline_after"], "2026-09-30T00:00:00Z", "deadline_after")

    event = X.get_leak_event(api, env["event_id"])
    assert_extension_budget(event, granted_total=30, remaining=0)


def test_one_day_past_the_cap_is_refused_and_changes_nothing(api):
    """
    A single further day takes the aggregate to 31, which the cap forbids; the
    refused decision leaves the request pending and the deadline where the
    approved grants put it.

    Design: Difficulty/boundary_precision_check/extension_total_exactly_at_thirty_day_cap_approves_thirty_first_day_rejected
    """
    env = _event_with_twenty_days_granted_and_two_pending_requests(api)
    X.approve_extension_request(api, env["er2_id"], 10)

    validate_error(
        api.decide_extension_request(
            env["er3_id"],
            F.extension_decision_payload(DECISION_APPROVE, granted_days=1),
            REGULATOR_HEADERS,
        ),
        ERR_EXTENSION_DAY_CAP_EXCEEDED,
        422,
    )

    assert X.get_extension_request(api, env["er3_id"])["status"] == EXTENSION_PENDING
    assert_leak_event_schedule(
        X.get_leak_event(api, env["event_id"]),
        initial_repair_deadline="2026-08-31T00:00:00Z",
        repair_deadline="2026-09-30T00:00:00Z",
    )

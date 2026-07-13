"""Breadth state-transition and calculation tests.

Every test translates exactly one non-stub instance from the corner design index (queue B).
"""
from test_helpers import (
    validate_success, validate_error,
    new_client, new_active_consent, new_screening,
    setup_checked_in_stay, setup_active_pooled_client, setup_completed_shelter_stay,
    new_exit_record,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_headers"]
SHELTER = TEST_USERS["shelter_manager_headers"]
ADMIN = TEST_USERS["hmis_admin_headers"]


def test_second_checkin_on_checked_in_reservation_invalid_state(api):
    """PRD §3.4: "A no-show attempt before the entry date has passed, or any of these
    transitions from a state that does not allow them, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sm_double_checkin_from_checked_in_returns_invalid_state
    """
    ctx = setup_checked_in_stay(shelter_name="Yew ES")
    res = api.check_in_reservation(ctx["reservation"]["id"], SHELTER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_activate_already_active_consent_invalid_state(api):
    """PRD §3.2: "Activating a `PENDING` consent moves it to `ACTIVE`, but only once the
    logical-clock date is on or after the `effective_date`; activating before the effective
    date, or activating a consent that is not `PENDING`, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sm_activate_already_active_consent_returns_invalid_state
    """
    client = new_client(full_name="Idem Consent", dob="1990-01-01")
    consent = new_active_consent(client["id"])
    res = api.activate_consent(consent["id"], INTAKE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_consent_revoke_cascades_pool_entry_to_removed(api):
    """PRD §3.2: "Revocation cascades: the client's `ACTIVE` `PrioritizationEntry`, if any,
    is driven to `REMOVED`, because the community may no longer act on a client who has
    withdrawn consent."

    Design: Corner/state_machines/sm_consent_revoke_removes_pool_entry
    """
    ctx = setup_active_pooled_client(self_report_points=9)
    revoked = validate_success(api.revoke_consent(ctx["consent"]["id"], INTAKE), 200)
    assert revoked["status"] == "REVOKED"

    pe = validate_success(api.get_prioritization_entry(ctx["pool_entry"]["id"], ADMIN), 200)
    assert pe["status"] == "REMOVED"


def test_screening_resolve_derives_diverted_outcome(api):
    """PRD §3.3: "Resolving an `OPEN` screening moves it `OPEN → RESOLVED` and derives its
    `outcome` by a strict priority: if the client is fleeing domestic violence, the outcome
    is `PROCEED_TO_SHELTER` regardless of any alternative; otherwise, if the client has a
    safe alternative, the outcome is `DIVERTED`; otherwise the outcome is
    `PROCEED_TO_PRIORITIZATION`."

    Design: Corner/state_machines/sm_screening_resolve_diverted_outcome
    """
    client = new_client(full_name="Div Client", dob="1990-01-01")
    screening = new_screening(client["id"], has_safe_alternative=True, is_fleeing_dv=False)
    resolved = validate_success(api.resolve_screening(screening["id"], INTAKE), 200)
    assert resolved["status"] == "RESOLVED"
    assert resolved["outcome"] == "DIVERTED"


def test_exit_to_street_is_negative_with_bed_nights(api):
    """PRD §3.8: "An exit to `EMERGENCY_SHELTER`, `STREET`, or `UNKNOWN` is `NEGATIVE`."
    PRD §3.8: "For a shelter exit, `bed_nights` is the number of nights between the
    reservation's `entry_date` and its `exit_date` counting the entry day but excluding the
    exit day (the half-open bed-night count used for HUD point-in-time counting)."

    Design: Corner/calculations/calc_exit_outcome_negative_street
    """
    ctx = setup_completed_shelter_stay(
        entry_date="2026-03-05", start_iso="2026-03-05T00:00:00Z",
        checkout_iso="2026-03-08T00:00:00Z", expected_exit_date="2026-03-20",
        shelter_name="Rowan ES")
    exit_rec = new_exit_record(ctx["client"]["id"], "STREET",
                               reservation_id=ctx["reservation"]["id"])
    assert exit_rec["outcome"] == "NEGATIVE"
    assert exit_rec["bed_nights"] == 3


def test_apr_report_aggregates_single_positive_exit(api):
    """PRD §3.8: "From that scope the report computes `total_exited` as the count of records
    in scope and `positive_exit_rate` as the count of `POSITIVE` exits divided by
    `total_exited`, multiplied by 100 and rounded to one decimal place; the division is
    performed once over summed counts."
    PRD §3.8: "It computes `avg_length_of_stay` as the sum of `bed_nights` over the scoped
    records divided by `total_exited`, rounded to two decimal places, again summing first and
    dividing once rather than averaging per-record rounded values."
    PRD §3.8: "Finally, `total_enrolled` counts the currently open enrollments: reservations
    in `RESERVED` or `CHECKED_IN` plus referrals in `ACCEPTED` or `ENROLLED`."

    Design: Corner/calculations/calc_apr_metrics_computed_read
    """
    ctx = setup_completed_shelter_stay(
        entry_date="2026-03-05", start_iso="2026-03-05T00:00:00Z",
        checkout_iso="2026-03-10T00:00:00Z", expected_exit_date="2026-03-20",
        shelter_name="Aspen ES")
    new_exit_record(ctx["client"]["id"], "PERMANENT_HOUSING",
                    reservation_id=ctx["reservation"]["id"])

    report = validate_success(api.get_apr(ADMIN), 200)
    assert report["total_exited"] == 1
    assert report["positive_exit_rate"] == 100.0
    assert report["avg_length_of_stay"] == 5.0
    assert report["total_enrolled"] == 0

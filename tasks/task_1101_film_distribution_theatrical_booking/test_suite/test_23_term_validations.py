"""Single-guard validation violations (PRD §3.3, §3.6, §3.8, §3.9)."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_distributor,
    setup_film,
    setup_distributor_film_theatre_screen,
    setup_in_play_agreement,
    run_settled_week,
    close_week,
    create_booking_agreement_payload,
    create_ancillary_window_payload,
    create_box_office_report_payload,
    ApiErrorId,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]


def test_floor_pct_above_week_one_rental_pct_rejected(api):
    """PRD §3.3: "The fiscal terms are then validated: `week_one_rental_pct` must lie
    between 0.00 and 0.95 inclusive, and `floor_pct` must not exceed
    `week_one_rental_pct`; a violation is rejected with `ERR_INVALID_RENTAL_TERMS`
    (HTTP 422)."
    floor 0.70 > week_one 0.50.

    Design: Corner/validations/invalid_rental_terms_floor_above_week_one_rejected
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    res = api.create_booking_agreement(
        did,
        create_booking_agreement_payload(
            env["film"]["id"], env["theatre"]["id"], env["screen"]["id"],
            week_one_rental_pct=0.50, floor_pct=0.70,
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_RENTAL_TERMS)


def test_week_one_rental_pct_over_max_rejected(api):
    """PRD §3.3: "`week_one_rental_pct` must lie between 0.00 and 0.95 inclusive, and
    `floor_pct` must not exceed `week_one_rental_pct`; a violation is rejected with
    `ERR_INVALID_RENTAL_TERMS` (HTTP 422)."
    week_one 0.96 exceeds the 0.95 admissible maximum.

    Design: Corner/validations/invalid_rental_pct_over_max_rejected
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    res = api.create_booking_agreement(
        did,
        create_booking_agreement_payload(
            env["film"]["id"], env["theatre"]["id"], env["screen"]["id"],
            week_one_rental_pct=0.96,
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_RENTAL_TERMS)


def test_ancillary_window_scheduled_before_window_end_rejected(api):
    """PRD §3.9: "the scheduled start must be on or after `theatrical_window_end`,
    failing with `ERR_ANCILLARY_TOO_EARLY` (HTTP 422) otherwise."
    The film opens 2026-05-01, so its theatrical window ends 2026-07-30; a
    2026-06-01 start is too early.

    Design: Corner/validations/ancillary_window_too_early_rejected
    """
    distributor = setup_distributor()
    film = setup_film(distributor["id"], target_release_date="2026-05-01T00:00:00Z")
    res = api.create_ancillary_window(
        distributor["id"], film["id"],
        create_ancillary_window_payload(
            window_kind="SVOD", scheduled_start_utc="2026-06-01T00:00:00Z"
        ),
        BOOKER,
    )
    validate_error(res, ApiErrorId.ERR_ANCILLARY_TOO_EARLY)


def test_holdover_rejected_before_min_weeks_played(api):
    """PRD §3.8: "A `Booker` may hold over an agreement standing in `IN_PLAY` whose
    `holdover_eligible` is true; attempting a holdover before `weeks_played` has
    reached `min_weeks_committed` is rejected with `ERR_HOLDOVER_NOT_ELIGIBLE`."
    min_weeks_committed=3, weeks_played=1 -> rejected.

    Design: Corner/validations/holdover_not_eligible_when_under_min_weeks
    """
    env = setup_in_play_agreement(
        booking_overrides={"min_weeks_committed": 3, "per_capita_floor_cents": 100}
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    run_settled_week(did, baid, 0)
    ba = validate_success(api.get_booking_agreement(did, baid, BOOKER), 200)
    assert ba["weeks_played"] == 1, f"Setup failed: weeks_played={ba['weeks_played']}"
    assert ba["deal_status"] == "IN_PLAY", f"Setup failed: {ba['deal_status']}"

    res = api.holdover_booking_agreement(
        did, baid, {"rationale": "Trying an early holdover"}, BOOKER
    )
    validate_error(res, ApiErrorId.ERR_HOLDOVER_NOT_ELIGIBLE)


def test_report_dated_two_epochs_back_rejected(api):
    """PRD §3.6: "The report date must fall within the distributor's current or prior
    `week_epoch`, and the same window is re-checked when the report is submitted — a
    date outside the window is rejected with `ERR_REPORT_OUTSIDE_WINDOW` (HTTP 422) at
    either step."
    With week_epoch at 2, a report dated in week 0 is outside the window.

    Design: Corner/validations/report_outside_window_rejected
    """
    env = setup_in_play_agreement(
        booking_overrides={"min_weeks_committed": 3, "per_capita_floor_cents": 100}
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    close_week(did)
    close_week(did)
    distributor = validate_success(api.get_distributor(did, BOOKER), 200)
    assert distributor["week_epoch"] == 2, (
        f"Setup failed: week_epoch={distributor['week_epoch']}"
    )

    res = api.create_box_office_report(
        did, baid,
        create_box_office_report_payload(
            report_date="2026-05-01T00:00:00Z", gross_cents=100000, admissions=500
        ),
        EXHIBITOR,
    )
    validate_error(res, ApiErrorId.ERR_REPORT_OUTSIDE_WINDOW)

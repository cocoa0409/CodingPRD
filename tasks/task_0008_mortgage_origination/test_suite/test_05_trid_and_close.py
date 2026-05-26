"""TRID timeline, clear-to-close gates, redisclose enforcement,
and the closing transition gated by the test-driven clock.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_disclosure_payload,
    create_rate_lock_payload,
    create_income_verification_payload,
    create_asset_verification_payload,
    create_appraisal_payload,
    complete_appraisal_payload,
    create_title_search_payload,
    create_udaap_check_payload,
    setup_prequalified_with_active_lock,
    set_clock,
    make_applicant_headers,
    TEST_USERS,
    ApiErrorId,
)


def _drive_to_clear_to_close(api, lo_headers, *, clock_iso="2026-06-01T00:00:00Z",
                              ssn_last4="9008", email="trid@test.com"):
    """Helper: take an application all the way to CLEAR_TO_CLOSE under a
    pinned clock and return (applicant, app_at_ctc, lock, le, cd)."""
    set_clock(clock_iso, role_headers=lo_headers)
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "R",
            "email": email,
            "ssn_last4": ssn_last4,
            "annual_income_cents": 9_000_000,
        },
        loan_overrides={
            "property_address": "TRID Way",
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 35_000_000,
            "loan_term_months": 360,
        },
        locked_rate_bps=625,
        lock_term_days=60,
    )
    app_v2 = validate_success(api.get_loan_application(app["id"], lo_headers), 200)["version"]
    le = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "LOAN_ESTIMATE", app_v2),
            lo_headers,
        ),
        201,
    )
    set_clock("2026-06-01T10:00:00Z", role_headers=lo_headers)
    le_delivered = validate_success(api.deliver_disclosure(le["id"], lo_headers), 200)

    validate_success(api.submit_for_review_loan_application(app["id"], lo_headers), 200)

    uw = TEST_USERS["underwriter_headers"]
    appr_h = TEST_USERS["appraiser_headers"]
    ta_h = TEST_USERS["title_agent_headers"]
    co_h = TEST_USERS["compliance_officer_headers"]

    iv = get_success_data(
        api.create_income_verification(
            create_income_verification_payload(
                app["id"], verified_annual_income_cents=9_000_000
            ),
            lo_headers,
        )
    )
    validate_success(api.accept_income_verification(iv["id"], uw), 200)
    av = get_success_data(
        api.create_asset_verification(
            create_asset_verification_payload(app["id"], verified_balance_cents=8_000_000),
            lo_headers,
        )
    )
    validate_success(api.accept_asset_verification(av["id"], uw), 200)
    appr = get_success_data(
        api.create_appraisal(create_appraisal_payload(app["id"]), lo_headers)
    )
    validate_success(
        api.complete_appraisal(
            appr["id"], complete_appraisal_payload(35_000_000), appr_h
        ),
        200,
    )
    ts = get_success_data(
        api.create_title_search(create_title_search_payload(app["id"]), lo_headers)
    )
    validate_success(api.mark_clear_title_search(ts["id"], ta_h), 200)
    get_success_data(
        api.create_udaap_check(
            create_udaap_check_payload(app["id"], review_outcome="CLEARED"),
            co_h,
        )
    )
    approved = validate_success(api.approve_loan_application(app["id"], uw), 200)

    cd_v = approved["version"]
    cd = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", cd_v),
            lo_headers,
        ),
        201,
    )
    set_clock("2026-06-05T10:00:00Z", role_headers=lo_headers)
    validate_success(api.deliver_disclosure(cd["id"], lo_headers), 200)
    validate_success(
        api.acknowledge_disclosure(cd["id"], make_applicant_headers(applicant["id"])),
        200,
    )

    ctc = validate_success(api.clear_to_close_loan_application(app["id"], uw), 200)
    return applicant, ctc, lock, le_delivered, cd


# =============================================================================
# Queue A — Difficulty
# =============================================================================

def test_trid_waiting_period_blocks_close_one_second_before_floor(api, lo_headers, closer_headers):
    """PRD §3.10: "A `Closer` advances the application from `CLEAR_TO_CLOSE` to
    `CLOSED` when the application is in `CLEAR_TO_CLOSE`, when the system clock
    has reached or passed the application's `earliest_consummation_at` (the
    TRID waiting period has elapsed — premature attempts are rejected with
    `ERR_TRID_WAITING_PERIOD`)"
    PRD §3.7: "the system takes a 7-calendar-day floor — the loan estimate's
    `delivered_at` plus exactly seven times 86400 seconds — and a 3-calendar-day
    floor — the closing disclosure's `delivered_at` plus exactly three times
    86400 seconds — and stores the maximum of the two as
    `earliest_consummation_at`."

    Design: Difficulty/resource_temporal_overlap/trid_max_merge_of_le_and_cd_floors_blocks_consummation
    """
    applicant, ctc, lock, le, cd = _drive_to_clear_to_close(api, lo_headers)
    assert ctc["status"] == "CLEAR_TO_CLOSE"
    assert ctc["earliest_consummation_at"] == "2026-06-08T10:00:00.000Z"

    # One second BEFORE earliest_consummation_at
    set_clock("2026-06-08T09:59:59Z", role_headers=closer_headers)
    res = api.close_loan_application(ctc["id"], closer_headers)
    validate_error(res, ApiErrorId.ERR_TRID_WAITING_PERIOD.value)

    final = validate_success(api.get_loan_application(ctc["id"], lo_headers), 200)
    assert final["status"] == "CLEAR_TO_CLOSE"


def test_clear_to_close_blocked_when_latest_cd_requires_redisclose(api, lo_headers):
    """PRD §3.7: "When `change_requires_redisclose` lands as true, the
    disclosure is still delivered, but the loan application's subsequent move
    to `CLEAR_TO_CLOSE` is gated: it will be rejected with
    `ERR_CD_REDISCLOSE_REQUIRED` until a fresh `ACKNOWLEDGED`
    `CLOSING_DISCLOSURE` exists for the application whose
    `change_requires_redisclose` is false."

    Design: Difficulty/cross_entity_state_dependency/clear_to_close_requires_acknowledged_closing_disclosure_with_redisclose_false
    """
    lo_h = lo_headers
    set_clock("2026-06-01T00:00:00Z", role_headers=lo_h)
    applicant, app, lock1 = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "Q",
            "email": "q.ctc@test.com",
            "ssn_last4": "9007",
            "annual_income_cents": 9_000_000,
        },
        loan_overrides={
            "property_address": "P8",
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 35_000_000,
            "loan_term_months": 360,
        },
        locked_rate_bps=625,
        lock_term_days=60,
    )
    v2 = validate_success(api.get_loan_application(app["id"], lo_h), 200)["version"]
    le = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "LOAN_ESTIMATE", v2),
            lo_h,
        ),
        201,
    )
    validate_success(api.deliver_disclosure(le["id"], lo_h), 200)
    validate_success(api.submit_for_review_loan_application(app["id"], lo_h), 200)

    uw = TEST_USERS["underwriter_headers"]
    iv = get_success_data(
        api.create_income_verification(
            create_income_verification_payload(app["id"], verified_annual_income_cents=9_000_000),
            lo_h,
        )
    )
    validate_success(api.accept_income_verification(iv["id"], uw), 200)
    av = get_success_data(
        api.create_asset_verification(create_asset_verification_payload(app["id"]), lo_h)
    )
    validate_success(api.accept_asset_verification(av["id"], uw), 200)
    appr = get_success_data(
        api.create_appraisal(create_appraisal_payload(app["id"]), lo_h)
    )
    validate_success(
        api.complete_appraisal(
            appr["id"], complete_appraisal_payload(35_000_000),
            TEST_USERS["appraiser_headers"],
        ),
        200,
    )
    ts = get_success_data(api.create_title_search(create_title_search_payload(app["id"]), lo_h))
    validate_success(api.mark_clear_title_search(ts["id"], TEST_USERS["title_agent_headers"]), 200)
    get_success_data(
        api.create_udaap_check(
            create_udaap_check_payload(app["id"], review_outcome="CLEARED"),
            TEST_USERS["compliance_officer_headers"],
        )
    )
    approved = validate_success(api.approve_loan_application(app["id"], uw), 200)
    v_approved = approved["version"]
    cd1 = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", v_approved),
            lo_h,
        ),
        201,
    )
    validate_success(api.deliver_disclosure(cd1["id"], lo_h), 200)
    validate_success(
        api.acknowledge_disclosure(cd1["id"], make_applicant_headers(applicant["id"])),
        200,
    )

    # Create a NEW rate-lock at much higher rate — supersedes lock1; bumps app.version.
    v_after_ack1 = validate_success(api.get_loan_application(app["id"], lo_h), 200)["version"]
    validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(
                app["id"], v_after_ack1, locked_rate_bps=700, lock_term_days=60
            ),
            lo_h,
        ),
        201,
    )
    v_after_lock2 = validate_success(api.get_loan_application(app["id"], lo_h), 200)["version"]
    cd2 = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", v_after_lock2),
            lo_h,
        ),
        201,
    )
    cd2_delivered = validate_success(api.deliver_disclosure(cd2["id"], lo_h), 200)
    assert cd2_delivered["change_requires_redisclose"] is True

    validate_success(
        api.acknowledge_disclosure(cd2["id"], make_applicant_headers(applicant["id"])),
        200,
    )

    # Attempt clear-to-close — must be rejected with ERR_CD_REDISCLOSE_REQUIRED.
    res = api.clear_to_close_loan_application(app["id"], uw)
    validate_error(res, ApiErrorId.ERR_CD_REDISCLOSE_REQUIRED.value)

    final = validate_success(api.get_loan_application(app["id"], lo_h), 200)
    assert final["status"] == "APPROVED"


def test_trid_close_succeeds_exactly_at_earliest_consummation_at(
    api, lo_headers, closer_headers
):
    """PRD §3.10: "A `Closer` advances the application from `CLEAR_TO_CLOSE`
    to `CLOSED` when the application is in `CLEAR_TO_CLOSE`, when the system
    clock has reached or passed the application's `earliest_consummation_at`
    (the TRID waiting period has elapsed — premature attempts are rejected
    with `ERR_TRID_WAITING_PERIOD`)"

    Companion to the one-second-before test — exercises the inclusive boundary
    (clock == earliest_consummation_at exactly): close succeeds.

    Design: Difficulty/resource_temporal_overlap/trid_max_merge_of_le_and_cd_floors_blocks_consummation
    """
    applicant, ctc, lock, le, cd = _drive_to_clear_to_close(
        api, lo_headers, email="exact.boundary@test.com", ssn_last4="9015"
    )
    assert ctc["earliest_consummation_at"] == "2026-06-08T10:00:00.000Z"
    set_clock("2026-06-08T10:00:00Z", role_headers=closer_headers)
    closed = validate_success(api.close_loan_application(ctc["id"], closer_headers), 200)
    assert closed["status"] == "CLOSED"


def test_clear_to_close_succeeds_after_fresh_acknowledged_cd_with_redisclose_false(
    api, lo_headers
):
    """PRD §3.7: "When `change_requires_redisclose` lands as true, the
    disclosure is still delivered, but the loan application's subsequent move
    to `CLEAR_TO_CLOSE` is gated: it will be rejected with
    `ERR_CD_REDISCLOSE_REQUIRED` until a fresh `ACKNOWLEDGED`
    `CLOSING_DISCLOSURE` exists for the application whose
    `change_requires_redisclose` is false."

    Companion to the rejected test — confirms the unlock path: when the
    redisclose-true CD is followed by a fresh ACKNOWLEDGED CD whose
    `change_requires_redisclose` is `false`, clear-to-close succeeds.

    Design: Difficulty/cross_entity_state_dependency/clear_to_close_requires_acknowledged_closing_disclosure_with_redisclose_false
    """
    lo_h = lo_headers
    set_clock("2026-06-01T00:00:00Z", role_headers=lo_h)
    applicant, app, lock1 = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "Q-OK",
            "email": "q.ok@test.com",
            "ssn_last4": "9008",
            "annual_income_cents": 9_000_000,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 35_000_000,
            "loan_term_months": 360,
        },
        locked_rate_bps=625,
        lock_term_days=60,
    )
    v2 = validate_success(api.get_loan_application(app["id"], lo_h), 200)["version"]
    le = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "LOAN_ESTIMATE", v2), lo_h
        ),
        201,
    )
    validate_success(api.deliver_disclosure(le["id"], lo_h), 200)
    validate_success(api.submit_for_review_loan_application(app["id"], lo_h), 200)

    uw = TEST_USERS["underwriter_headers"]
    iv = get_success_data(
        api.create_income_verification(
            create_income_verification_payload(app["id"], verified_annual_income_cents=9_000_000),
            lo_h,
        )
    )
    validate_success(api.accept_income_verification(iv["id"], uw), 200)
    av = get_success_data(
        api.create_asset_verification(create_asset_verification_payload(app["id"]), lo_h)
    )
    validate_success(api.accept_asset_verification(av["id"], uw), 200)
    appr = get_success_data(
        api.create_appraisal(create_appraisal_payload(app["id"]), lo_h)
    )
    validate_success(
        api.complete_appraisal(
            appr["id"], complete_appraisal_payload(35_000_000),
            TEST_USERS["appraiser_headers"],
        ),
        200,
    )
    ts = get_success_data(api.create_title_search(create_title_search_payload(app["id"]), lo_h))
    validate_success(api.mark_clear_title_search(ts["id"], TEST_USERS["title_agent_headers"]), 200)
    get_success_data(
        api.create_udaap_check(
            create_udaap_check_payload(app["id"], review_outcome="CLEARED"),
            TEST_USERS["compliance_officer_headers"],
        )
    )
    approved = validate_success(api.approve_loan_application(app["id"], uw), 200)

    # Deliver+ack a first CD at 625 bps
    cd1 = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", approved["version"]),
            lo_h,
        ),
        201,
    )
    validate_success(api.deliver_disclosure(cd1["id"], lo_h), 200)
    validate_success(
        api.acknowledge_disclosure(cd1["id"], make_applicant_headers(applicant["id"])),
        200,
    )

    # Supersede with 700 bps lock and deliver a CD that triggers redisclose
    v_after_ack = validate_success(api.get_loan_application(app["id"], lo_h), 200)["version"]
    validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(app["id"], v_after_ack, locked_rate_bps=700, lock_term_days=60),
            lo_h,
        ),
        201,
    )
    v_after_lock2 = validate_success(api.get_loan_application(app["id"], lo_h), 200)["version"]
    cd2 = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", v_after_lock2),
            lo_h,
        ),
        201,
    )
    cd2_delivered = validate_success(api.deliver_disclosure(cd2["id"], lo_h), 200)
    assert cd2_delivered["change_requires_redisclose"] is True
    validate_success(
        api.acknowledge_disclosure(cd2["id"], make_applicant_headers(applicant["id"])),
        200,
    )

    # Now relock at the SAME 700 bps so a third CD has delta 0 → redisclose=false.
    v_after_ack2 = validate_success(api.get_loan_application(app["id"], lo_h), 200)["version"]
    validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(app["id"], v_after_ack2, locked_rate_bps=700, lock_term_days=60),
            lo_h,
        ),
        201,
    )
    v_after_lock3 = validate_success(api.get_loan_application(app["id"], lo_h), 200)["version"]
    cd3 = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "CLOSING_DISCLOSURE", v_after_lock3),
            lo_h,
        ),
        201,
    )
    cd3_delivered = validate_success(api.deliver_disclosure(cd3["id"], lo_h), 200)
    assert cd3_delivered["change_requires_redisclose"] is False
    validate_success(
        api.acknowledge_disclosure(cd3["id"], make_applicant_headers(applicant["id"])),
        200,
    )

    # Now clear-to-close must succeed.
    ctc = validate_success(api.clear_to_close_loan_application(app["id"], uw), 200)
    assert ctc["status"] == "CLEAR_TO_CLOSE"


# =============================================================================
# Queue B — Corner
# =============================================================================

def test_clock_advance_past_earliest_consummation_at_enables_close(
    api, lo_headers, closer_headers
):
    """PRD §3.10: "A `Closer` advances the application from `CLEAR_TO_CLOSE` to
    `CLOSED` when the application is in `CLEAR_TO_CLOSE`, when the system clock
    has reached or passed the application's `earliest_consummation_at` (the
    TRID waiting period has elapsed — premature attempts are rejected with
    `ERR_TRID_WAITING_PERIOD`), and when the application still has an `ACTIVE`
    rate lock whose `expires_at` is at or beyond the current system clock."

    Design: Corner/cross_cutting_complexity_layers/scheduled_clock_drive_advances_consummation_eligibility
    """
    applicant, ctc, lock, le, cd = _drive_to_clear_to_close(
        api, lo_headers, email="closer.advance@test.com", ssn_last4="1420"
    )
    set_clock("2026-06-08T10:00:00Z", role_headers=closer_headers)
    closed = validate_success(api.close_loan_application(ctc["id"], closer_headers), 200)
    assert closed["status"] == "CLOSED"

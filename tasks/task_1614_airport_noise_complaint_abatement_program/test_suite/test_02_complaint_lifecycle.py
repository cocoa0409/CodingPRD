"""Complaint review loop: state legality, terminal lockdown, the info-request
round trip, reopen window and reopen limit, the full close/reopen/re-correlate
cycle, and counter conservation across close/withdraw/reopen."""
from test_helpers import (
    ApiErrorId,
    assert_complainant_cardinality,
    begin_review,
    close_complaint,
    correlate_complaint,
    create_complaint,
    create_complainant,
    create_operated_flight,
    create_operator,
    make_complainant_headers,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_success,
)

LIAISON = TEST_USERS["community_liaison_headers"]
ANALYST = TEST_USERS["noise_analyst_headers"]


def _complaint_in_under_review(api):
    complainant = create_complainant()
    complaint = create_complaint(complainant["id"], "2026-07-15T09:00:00Z")
    begin_review(complaint["id"])
    return complainant, complaint


def test_complaint_begin_review_twice_rejected(api):
    """PRD 3.4: "Any of these transitions attempted from the wrong state is rejected
    with `ERR_INVALID_COMPLAINT_STATE`".

    Design: Corner/state_machines/complaint_begin_review_twice_rejected
    """
    _complainant, complaint = _complaint_in_under_review(api)

    response = api.begin_review(complaint["id"], {}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_COMPLAINT_STATE)

    reread = validate_success(api.get_complaint(complaint["id"], ANALYST))
    assert reread["status"] == "UNDER_REVIEW"
    assert reread["version"] == complaint["version"] + 1


def test_complaint_withdraw_twice_rejected_terminal_lockdown(api):
    """PRD 3.4: "From any state other than `WITHDRAWN`, the complainant-owner or a
    `CommunityLiaison` may withdraw the complaint, moving it to the terminal
    `WITHDRAWN`."
    PRD 3.4: "Any of these transitions attempted from the wrong state is rejected
    with `ERR_INVALID_COMPLAINT_STATE`".

    Design: Corner/state_machines/complaint_withdraw_twice_rejected_terminal_lockdown
    """
    complainant = create_complainant()
    complaint = create_complaint(complainant["id"], "2026-07-15T09:00:00Z")
    owner = make_complainant_headers(complainant["id"])

    first = api.withdraw_complaint(complaint["id"], {}, owner)
    assert validate_success(first, 200)["status"] == "WITHDRAWN"

    second = api.withdraw_complaint(complaint["id"], {}, owner)
    validate_error(second, ApiErrorId.ERR_INVALID_COMPLAINT_STATE)


def test_complaint_info_request_roundtrip_stores_note(api):
    """PRD 3.4: "Requesting more information moves `UNDER_REVIEW` to
    `AWAITING_COMPLAINANT` and records the analyst's `info_request_note`. Providing
    information — by the complainant-owner or by a `CommunityLiaison` — moves the
    complaint back to `UNDER_REVIEW` with the supplied `narrative` appended to the
    record."

    Design: Corner/state_machines/complaint_info_request_roundtrip_stores_note
    """
    complainant, complaint = _complaint_in_under_review(api)

    requested = validate_success(
        api.request_info(complaint["id"], {"info_request_note": "Need exact time."}, ANALYST),
        200,
    )
    assert requested["status"] == "AWAITING_COMPLAINANT"
    assert requested["info_request_note"] == "Need exact time."

    provided = validate_success(
        api.provide_info(
            complaint["id"],
            {"narrative": "It was 03:12 local."},
            make_complainant_headers(complainant["id"]),
        ),
        200,
    )
    assert provided["status"] == "UNDER_REVIEW"


def test_complaint_reopen_after_30_days_rejected(api):
    """PRD 3.4: "The complainant-owner or a `CommunityLiaison` may reopen it, with a
    `reason`, within thirty days of `closed_at` — later is rejected with
    `ERR_REOPEN_WINDOW_EXPIRED`".

    Design: Corner/state_machines/complaint_reopen_after_30_days_rejected
    """
    complainant, complaint = _complaint_in_under_review(api)
    close_complaint(complaint["id"], "UNSUBSTANTIATED")
    set_clock("2026-09-01T00:00:00Z")

    response = api.reopen_complaint(
        complaint["id"],
        {"reason": "late plea"},
        make_complainant_headers(complainant["id"]),
    )
    validate_error(response, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED)


def test_complaint_fourth_reopen_rejected(api):
    """PRD 3.4: "The complainant-owner or a `CommunityLiaison` may reopen it, with a
    `reason`, within thirty days of `closed_at` — later is rejected with
    `ERR_REOPEN_WINDOW_EXPIRED` — and at most three times in its life; a fourth
    attempt is rejected with `ERR_REOPEN_LIMIT_REACHED`."

    Design: Corner/state_machines/complaint_fourth_reopen_rejected
    """
    complainant, complaint = _complaint_in_under_review(api)
    owner = make_complainant_headers(complainant["id"])

    for cycle in range(3):
        close_complaint(complaint["id"], "UNSUBSTANTIATED")
        reopened = validate_success(
            api.reopen_complaint(complaint["id"], {"reason": f"r{cycle + 1}"}, owner), 200
        )
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == cycle + 1
        validate_success(api.resume_review(complaint["id"], {}, ANALYST), 200)

    close_complaint(complaint["id"], "UNSUBSTANTIATED")
    fourth = api.reopen_complaint(complaint["id"], {"reason": "r4"}, owner)
    validate_error(fourth, ApiErrorId.ERR_REOPEN_LIMIT_REACHED)


def test_close_reopen_recorrelate_cycle_transitions(api):
    """PRD 3.4: "Reopening moves the complaint to `REOPENED`, increments
    `reopen_count`, clears `closed_at`".
    PRD 3.4: "An analyst then resumes review, moving `REOPENED` back to
    `UNDER_REVIEW` for another pass through the loop."
    PRD 3.4: "Closing with `outcome` `SUBSTANTIATED` requires the complaint to be
    `CORRELATED` and its `correlation_confidence` to be at least 60.0".

    Design: Difficulty/non_linear_state_machine/complaint_close_reopen_recorrelate_cycle
    """
    complainant = create_complainant(full_name="Cyc One", email="cyc1@x.com", zone_code="Z1")
    operator = create_operator(name="Air Four")
    flight = create_operated_flight(
        operator["id"], "2026-07-15T12:00:00Z", scheduled_at="2026-07-15T11:55:00Z"
    )
    complaint = create_complaint(
        complainant["id"], "2026-07-15T12:02:00Z", disturbance_type="LOUD_EVENT"
    )
    begin_review(complaint["id"])

    closed = close_complaint(complaint["id"], "UNSUBSTANTIATED")
    assert closed["status"] == "CLOSED_UNSUBSTANTIATED"

    reopened = validate_success(
        api.reopen_complaint(
            complaint["id"],
            {"reason": "new evidence"},
            make_complainant_headers(complainant["id"]),
        ),
        200,
    )
    assert reopened["status"] == "REOPENED"
    assert reopened["closed_at"] is None

    resumed = validate_success(api.resume_review(complaint["id"], {}, ANALYST), 200)
    assert resumed["status"] == "UNDER_REVIEW"

    correlated = correlate_complaint(
        complaint["id"], resumed["version"], flight_id=flight["id"]
    )
    assert correlated["status"] == "CORRELATED"

    final = close_complaint(complaint["id"], "SUBSTANTIATED")
    assert final["status"] == "CLOSED_SUBSTANTIATED"
    assert final["closure_outcome"] == "SUBSTANTIATED"
    assert final["reopen_count"] == 1


def test_close_reopen_recorrelate_cycle_counter_compensation(api):
    """PRD 3.4: "`open_count` tracks complaints in `RECEIVED`, `UNDER_REVIEW`,
    `AWAITING_COMPLAINANT`, `CORRELATED`, or `REOPENED`; `closed_count` tracks
    `CLOSED_SUBSTANTIATED` and `CLOSED_UNSUBSTANTIATED`".
    PRD 3.4: "Reopening moves the complaint to `REOPENED` ... and compensates the
    complainant's counters (`closed_count` down, `open_count` up, and
    `substantiated_count` down one when the closure had been substantiated)".

    Design: Difficulty/non_linear_state_machine/complaint_close_reopen_recorrelate_cycle
    """
    complainant = create_complainant(full_name="Cyc One", email="cyc1@x.com", zone_code="Z1")
    operator = create_operator(name="Air Four")
    flight = create_operated_flight(
        operator["id"], "2026-07-15T12:00:00Z", scheduled_at="2026-07-15T11:55:00Z"
    )
    complaint = create_complaint(
        complainant["id"], "2026-07-15T12:02:00Z", disturbance_type="LOUD_EVENT"
    )
    begin_review(complaint["id"])
    close_complaint(complaint["id"], "UNSUBSTANTIATED")

    mid = validate_success(api.get_complainant(complainant["id"], LIAISON))
    assert mid["open_count"] == 0
    assert mid["closed_count"] == 1

    validate_success(
        api.reopen_complaint(
            complaint["id"],
            {"reason": "new evidence"},
            make_complainant_headers(complainant["id"]),
        ),
        200,
    )
    resumed = validate_success(api.resume_review(complaint["id"], {}, ANALYST), 200)
    correlate_complaint(complaint["id"], resumed["version"], flight_id=flight["id"])
    close_complaint(complaint["id"], "SUBSTANTIATED")

    final = validate_success(api.get_complainant(complainant["id"], LIAISON))
    assert final["filed_total"] == 1
    assert final["open_count"] == 0
    assert final["closed_count"] == 1
    assert final["substantiated_count"] == 1
    assert final["withdrawn_count"] == 0
    assert_complainant_cardinality(final)


def test_counter_conservation_across_close_and_withdraw(api):
    """PRD 3.4: "`open_count` tracks complaints in `RECEIVED`, `UNDER_REVIEW`,
    `AWAITING_COMPLAINANT`, `CORRELATED`, or `REOPENED`; `closed_count` tracks
    `CLOSED_SUBSTANTIATED` and `CLOSED_UNSUBSTANTIATED`; `withdrawn_count` tracks
    `WITHDRAWN`; and `substantiated_count` tracks those currently
    `CLOSED_SUBSTANTIATED`."

    Design: Difficulty/compensating_invariant/complainant_counter_conservation_across_close_withdraw_reopen
    """
    complainant = create_complainant(full_name="Inv One", email="inv1@x.com")
    c1 = create_complaint(complainant["id"], "2026-07-05T08:00:00Z")
    c2 = create_complaint(complainant["id"], "2026-07-06T08:00:00Z")
    create_complaint(complainant["id"], "2026-07-07T08:00:00Z", channel="APP",
                     disturbance_type="VIBRATION")

    begin_review(c1["id"])
    close_complaint(c1["id"], "UNSUBSTANTIATED")
    validate_success(
        api.withdraw_complaint(c2["id"], {}, make_complainant_headers(complainant["id"])),
        200,
    )

    snapshot = validate_success(api.get_complainant(complainant["id"], LIAISON))
    assert snapshot["filed_total"] == 3
    assert snapshot["open_count"] == 1
    assert snapshot["closed_count"] == 1
    assert snapshot["withdrawn_count"] == 1
    assert_complainant_cardinality(snapshot)


def test_counter_conservation_reopen_compensates_close(api):
    """PRD 3.4: "Reopening moves the complaint to `REOPENED`, increments
    `reopen_count`, clears `closed_at`, and compensates the complainant's counters
    (`closed_count` down, `open_count` up, and `substantiated_count` down one when
    the closure had been substantiated), again followed by standing re-evaluation."

    Design: Difficulty/compensating_invariant/complainant_counter_conservation_across_close_withdraw_reopen
    """
    complainant = create_complainant(full_name="Inv One", email="inv1@x.com")
    c1 = create_complaint(complainant["id"], "2026-07-05T08:00:00Z")
    c2 = create_complaint(complainant["id"], "2026-07-06T08:00:00Z")
    create_complaint(complainant["id"], "2026-07-07T08:00:00Z", channel="APP",
                     disturbance_type="VIBRATION")

    begin_review(c1["id"])
    close_complaint(c1["id"], "UNSUBSTANTIATED")
    validate_success(
        api.withdraw_complaint(c2["id"], {}, make_complainant_headers(complainant["id"])),
        200,
    )

    reopened = validate_success(
        api.reopen_complaint(
            c1["id"], {"reason": "changed mind"}, make_complainant_headers(complainant["id"])
        ),
        200,
    )
    assert reopened["status"] == "REOPENED"

    after = validate_success(api.get_complainant(complainant["id"], LIAISON))
    assert after["filed_total"] == 3
    assert after["open_count"] == 2
    assert after["closed_count"] == 0
    assert after["withdrawn_count"] == 1
    assert_complainant_cardinality(after)

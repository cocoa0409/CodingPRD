"""Law-enforcement process: preservation windows, duty separation and lateness."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_subpoena_request,
    legal_review_subpoena,
    new_customer,
    new_subpoena,
    read_customer,
    read_subpoena,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

COUNSEL = TEST_USERS["counsel_headers"]
COUNSEL_2 = TEST_USERS["counsel_2_headers"]


def _customer_with_a_first_preservation_window():
    customer = new_customer(legal_name="Ephraim Costa", tin_last4="8383")
    subpoena = new_subpoena(
        customer["id"],
        issuing_agency="State Attorney General",
        docket_number="26-SAG-0091",
        response_due_at="2026-09-15T00:00:00Z",
        preservation_start_at="2026-08-05T00:00:00Z",
        preservation_end_at="2026-08-10T00:00:00Z",
    )
    return customer, subpoena


# ===========================================================================
# The three-day preservation buffer on closed windows
# ===========================================================================
def test_a_two_day_gap_between_preservation_windows_is_refused(api, analyst_headers):
    """PRD §3.9: "Preservation windows on one depositor must not crowd each other.
    A new window is accepted only when it is separated by at least three calendar
    days from the window of every other subpoena on the same depositor whose
    `status` is `RECEIVED`, `UNDER_LEGAL_REVIEW`, or `PRODUCED` — formally, the new
    window's start must be at or after the existing window's end plus three days,
    or the new window's end plus three days must be at or before the existing
    window's start. A gap of exactly three days is accepted; anything shorter,
    including windows that merely touch and windows nested inside one another, is
    refused with `ERR_PRESERVATION_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/preservation_windows_on_one_customer_use_closed_intervals_with_a_three_day_buffer
    """
    customer, _first = _customer_with_a_first_preservation_window()

    response = api.create_subpoena(
        customer["id"],
        {
            "issuing_agency": "County Sheriff",
            "docket_number": "26-CS-0210",
            "response_due_at": "2026-09-20T00:00:00Z",
            "preservation_start_at": "2026-08-12T00:00:00Z",
            "preservation_end_at": "2026-08-20T00:00:00Z",
        },
        COUNSEL,
    )
    validate_error(response, ApiErrorId.ERR_PRESERVATION_WINDOW_CONFLICT.value)

    _rows, meta = validate_paginated(api.list_customer_subpoenas(customer["id"], analyst_headers))
    assert meta["total_count"] == 1, "The refused window created nothing"


def test_a_gap_of_exactly_three_days_between_preservation_windows_is_accepted(
    api, analyst_headers
):
    """PRD §3.9: "A gap of exactly three days is accepted; anything shorter,
    including windows that merely touch and windows nested inside one another, is
    refused with `ERR_PRESERVATION_WINDOW_CONFLICT` (HTTP 409)."
    PRD §3.9: "The server stamps `received_at` from the logical clock, records
    `status` `RECEIVED`, and leaves `legal_reviewed_by_user_id`,
    `responded_by_user_id`, and `production_note` null with `is_late` false."
    PRD §3.9: "Logging the process immediately makes the depositor's
    `preservation_hold_active` true, which is what blocks case closure in §3.7."

    Design: Difficulty/resource_temporal_overlap/preservation_windows_on_one_customer_use_closed_intervals_with_a_three_day_buffer
    """
    customer, _first = _customer_with_a_first_preservation_window()

    validate_error(
        api.create_subpoena(
            customer["id"],
            {
                "issuing_agency": "County Sheriff",
                "docket_number": "26-CS-0210",
                "response_due_at": "2026-09-20T00:00:00Z",
                "preservation_start_at": "2026-08-12T00:00:00Z",
                "preservation_end_at": "2026-08-20T00:00:00Z",
            },
            COUNSEL,
        ),
        ApiErrorId.ERR_PRESERVATION_WINDOW_CONFLICT.value,
    )

    accepted = validate_success(
        api.create_subpoena(
            customer["id"],
            {
                "issuing_agency": "County Sheriff",
                "docket_number": "26-CS-0210",
                "response_due_at": "2026-09-20T00:00:00Z",
                "preservation_start_at": "2026-08-13T00:00:00Z",
                "preservation_end_at": "2026-08-20T00:00:00Z",
            },
            COUNSEL,
        ),
        201,
    )
    assert_subpoena_request(accepted)
    assert accepted["status"] == "RECEIVED"

    _rows, meta = validate_paginated(api.list_customer_subpoenas(customer["id"], analyst_headers))
    assert meta["total_count"] == 2

    assert read_customer(customer["id"], analyst_headers)["preservation_hold_active"] is True


# ===========================================================================
# Handling order and duty separation
# ===========================================================================
def test_responding_before_the_legal_review_step_is_refused(api, analyst_headers):
    """PRD §3.9: "Both steps check the subpoena's state and report
    `ERR_SUBPOENA_INVALID_STATE` (HTTP 409) on a mismatch: review requires
    `RECEIVED`, response requires `UNDER_LEGAL_REVIEW`."
    PRD §3.9: "The server stamps `received_at` from the logical clock, records
    `status` `RECEIVED`, and leaves `legal_reviewed_by_user_id`,
    `responded_by_user_id`, and `production_note` null with `is_late` false."

    Design: Corner/state_machines/subpoena_response_before_legal_review_is_rejected
    """
    customer = new_customer(legal_name="Subpoena Order Depositor", tin_last4="0013")
    subpoena = new_subpoena(
        customer["id"],
        issuing_agency="FinCEN",
        docket_number="26-FIN-0007",
        response_due_at="2026-09-30T00:00:00Z",
        preservation_start_at="2026-08-02T00:00:00Z",
        preservation_end_at="2026-10-02T00:00:00Z",
    )
    assert subpoena["status"] == "RECEIVED"

    validate_error(
        api.respond_to_subpoena(
            subpoena["id"],
            {"disposition": "PRODUCE", "production_note": "Records attached"},
            COUNSEL_2,
        ),
        ApiErrorId.ERR_SUBPOENA_INVALID_STATE.value,
    )

    reread = read_subpoena(subpoena["id"], COUNSEL)
    assert reread["status"] == "RECEIVED"
    assert reread["legal_reviewed_by_user_id"] is None
    assert reread["responded_by_user_id"] is None


def test_the_reviewing_counsel_may_not_sign_the_response(api):
    """PRD §2.1: "The operator who records a decision on an early-release review
    may not be the operator whose `X-User-ID` was captured as that review's
    `prepared_by_user_id`, and the counsel who signs a subpoena response may not be
    the counsel whose `X-User-ID` was captured as that subpoena's
    `legal_reviewed_by_user_id`. A violation of either is
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.9: "The signer's `X-User-ID` must differ from
    `legal_reviewed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "A response signed at or before the deadline needs no justification
    and records `is_late` false."

    Design: Corner/rbac/counsel_cannot_sign_the_response_to_a_subpoena_they_reviewed
    """
    customer = new_customer(legal_name="Counsel Separation Depositor", tin_last4="0042")
    subpoena = new_subpoena(
        customer["id"],
        issuing_agency="Federal Bureau of Investigation",
        docket_number="26-FBI-0333",
        response_due_at="2026-09-30T00:00:00Z",
        preservation_start_at="2026-08-01T00:00:00Z",
        preservation_end_at="2026-10-01T00:00:00Z",
    )
    reviewed = legal_review_subpoena(subpoena["id"], COUNSEL)
    assert reviewed["legal_reviewed_by_user_id"] == "counsel-1"

    validate_error(
        api.respond_to_subpoena(
            subpoena["id"],
            {"disposition": "PRODUCE", "production_note": "Self-signed attempt"},
            COUNSEL,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    produced = validate_success(
        api.respond_to_subpoena(
            subpoena["id"],
            {"disposition": "PRODUCE", "production_note": "Records produced under seal"},
            COUNSEL_2,
        )
    )
    assert produced["status"] == "PRODUCED"
    assert produced["responded_by_user_id"] == "counsel-2"
    assert produced["is_late"] is False


def test_a_late_response_needs_a_justification_and_records_is_late(api, analyst_headers):
    """PRD §3.9: "Lateness is measured at signing: `is_late` is true exactly when
    the logical clock is strictly greater than `response_due_at`. When it is, a
    non-blank `late_justification` must accompany the response; without one the
    request is refused with `ERR_LATE_JUSTIFICATION_REQUIRED` (HTTP 422)."
    PRD §3.9: "`PRODUCED` remains inside the holding set, so the depositor's
    `preservation_hold_active` stays true until the logical clock passes that
    subpoena's `preservation_end_at`."
    PRD §3.9: "First, counsel takes the process under review, the transition
    `RECEIVED → UNDER_LEGAL_REVIEW`, which records `legal_reviewed_by_user_id` from
    `X-User-ID`."

    Design: Corner/validations/late_subpoena_response_without_a_justification_is_rejected
    """
    customer = new_customer(legal_name="Late Response Depositor", tin_last4="0032")
    subpoena = new_subpoena(
        customer["id"],
        issuing_agency="District Attorney",
        docket_number="26-DA-0512",
        response_due_at="2026-08-05T00:00:00Z",
        preservation_start_at="2026-08-01T00:00:00Z",
        preservation_end_at="2026-09-01T00:00:00Z",
    )
    legal_review_subpoena(subpoena["id"], COUNSEL)
    set_clock("2026-08-06T00:00:00Z")

    validate_error(
        api.respond_to_subpoena(
            subpoena["id"],
            {"disposition": "PRODUCE", "production_note": "Statements attached"},
            COUNSEL_2,
        ),
        ApiErrorId.ERR_LATE_JUSTIFICATION_REQUIRED.value,
    )

    produced = validate_success(
        api.respond_to_subpoena(
            subpoena["id"],
            {
                "disposition": "PRODUCE",
                "production_note": "Statements attached",
                "late_justification": "Records vendor outage 2026-08-03 to 2026-08-05",
            },
            COUNSEL_2,
        )
    )
    assert produced["status"] == "PRODUCED"
    assert produced["is_late"] is True

    reread = read_subpoena(subpoena["id"], COUNSEL)
    assert reread["responded_by_user_id"] == "counsel-2"
    assert reread["legal_reviewed_by_user_id"] == "counsel-1"

    customer_after = read_customer(customer["id"], analyst_headers)
    assert customer_after["preservation_hold_active"] is True, (
        "A PRODUCED subpoena keeps the hold until the clock passes preservation_end_at"
    )

"""Service request intake, coverage triage, and the response service level."""
from test_helpers import (
    ApiErrorId,
    assess_request,
    assert_instant_equal,
    assert_service_request,
    create_approved_request,
    create_home,
    create_homeowner,
    file_service_request,
    run_sweep,
    set_clock,
    setup_home,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    assess_denial_payload,
    assess_warrantable_payload,
    create_service_request_payload,
)
from test_helpers.test_users import TEST_USERS, make_homeowner_headers

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["rep_headers"]


def test_service_request_intake_stamps_logical_clock(api):
    """PRD §3.2: "The server stamps `reported_at` from the logical clock — coverage
    is judged on this instant, and only this instant — sets the status to
    `RECEIVED`, and anchors the response service level: `response_due_at` is
    `reported_at` plus four hours for `EMERGENCY`, twenty-four hours for `URGENT`,
    or seventy-two hours for `STANDARD`."
    PRD §3.2: "The reporter's `homeowner_id` is copied from `X-User-ID`; a
    homeowner may not file against someone else's home (`ERR_NOT_RESOURCE_OWNER`)."
    PRD §2.4: "At startup the logical clock reads exactly 2026-08-01T00:00:00Z".

    Design: Corner/entities/service_request_intake_stamps_logical_clock
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    resp = api.create_service_request(
        create_service_request_payload(
            home["id"],
            item_category="HVAC",
            severity="STANDARD",
            description="AC not cooling",
        ),
        make_homeowner_headers(homeowner["id"]),
    )
    data = validate_success(resp, 201)
    assert_service_request(data)
    assert_instant_equal(data["reported_at"], "2026-08-01T00:00:00Z", "reported_at")
    assert_instant_equal(
        data["response_due_at"], "2026-08-04T00:00:00Z", "response_due_at"
    )
    assert data["status"] == "RECEIVED"
    assert data["homeowner_id"] == homeowner["id"], (
        "homeowner_id must be copied from X-User-ID"
    )


def test_excluded_category_assess_rejected(api):
    """PRD §3.2: "Three categories — `LANDSCAPING`, `APPLIANCE`, and
    `ROUTINE_MAINTENANCE` — are excluded from coverage entirely: they map to no
    tier and no term window, so assessing one of them warrantable is rejected with
    `ERR_ITEM_NOT_COVERED` before any date arithmetic is considered."

    Design: Corner/validations/excluded_category_assess_rejected
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    request = file_service_request(
        home["id"],
        homeowner["id"],
        item_category="APPLIANCE",
        description="Oven door hinge",
    )
    resp = api.assess_service_request(
        request["id"], assess_warrantable_payload(), REP
    )
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_COVERED)

    after = validate_success(api.get_service_request(request["id"], REP), 200)
    assert after["status"] == "RECEIVED", "failed assess must leave state untouched"


def test_denial_requires_education_packet(api):
    """PRD §3.2: "With a reason code present but no `education_packet_code`, the
    denial is refused with `ERR_EDUCATION_PACKET_REQUIRED`: every non-warrantable
    determination ships homeowner education, without exception."
    PRD §3.2: "A recorded denial stamps `denied_at`, sets the dispute window
    `dispute_deadline_at` thirty days later, and moves the request to `DENIED`."

    Design: Corner/state_machines/denial_requires_education_packet
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    request = file_service_request(
        home["id"],
        homeowner["id"],
        item_category="APPLIANCE",
        description="Dishwasher not draining",
    )
    resp = api.assess_service_request(
        request["id"],
        {"warrantable": False, "denial_reason_code": "EXCLUDED_CATEGORY"},
        REP,
    )
    validate_error(resp, ApiErrorId.ERR_EDUCATION_PACKET_REQUIRED)

    denied = assess_request(
        request["id"],
        assess_denial_payload(
            denial_reason_code="EXCLUDED_CATEGORY",
            education_packet_code="EDU-APPLIANCE-01",
        ),
    )
    assert denied["status"] == "DENIED"
    assert denied["denial_reason_code"] == "EXCLUDED_CATEGORY"
    assert_instant_equal(
        denied["dispute_deadline_at"], "2026-08-31T00:00:00Z", "dispute_deadline_at"
    )


def test_sla_assess_exactly_at_due_is_met(api):
    """PRD §3.2: "An assessment is late only when that instant is strictly later
    than `response_due_at` — assessing exactly at the deadline is on time."

    Design: Corner/calculations/sla_assess_exactly_at_due_is_met
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    request = file_service_request(
        home["id"], homeowner["id"], item_category="HVAC", description="AC noisy"
    )
    # Reported at the 2026-08-01T00:00:00Z startup clock, STANDARD: due 2026-08-04T00:00:00Z.
    set_clock("2026-08-04T00:00:00Z")
    assessed = assess_request(request["id"], assess_warrantable_payload())
    assert assessed["status"] == "APPROVED"
    assert assessed["response_breached"] is False, (
        "assess exactly at the due instant is MET (breach requires strictly later)"
    )
    assert assessed["escalation_level"] == 0


def test_sla_response_breach_marked_by_sweep(api):
    """PRD §3.7: "Beyond accruals, each run raises the breach flags: requests still
    in `RECEIVED` whose response deadline is strictly past are marked
    `response_breached` with escalation level 1, and requests still in `APPROVED`
    or `IN_SERVICE` whose completion deadline is strictly past are marked
    `completion_breached` with escalation level 2."
    PRD §3.2: "A late assessment sets `response_breached` true and raises
    `escalation_level` to at least 1."

    Design: Corner/state_machines/sla_response_breach_marked_by_sweep
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    request = file_service_request(
        home["id"], homeowner["id"], item_category="HVAC", description="AC out"
    )
    # Response due 2026-08-04T00:00:00Z; one second past it.
    set_clock("2026-08-04T00:00:01Z")
    sweep = run_sweep()
    assert sweep["requests_marked_response_breached"] == 1, (
        f"expected exactly 1 response breach flagged, got "
        f"{sweep['requests_marked_response_breached']}"
    )

    after_sweep = validate_success(api.get_service_request(request["id"], REP), 200)
    assert after_sweep["response_breached"] is True
    assert after_sweep["escalation_level"] == 1

    assessed = assess_request(request["id"], assess_warrantable_payload())
    assert assessed["status"] == "APPROVED"
    assert assessed["response_breached"] is True, (
        "breach stays latched after the late assessment"
    )


class TestCoverageTermEndExclusive:
    def test_reported_inside_workmanship_window_approved(self, api):
        """PRD §3.2: "Only after the category check passes does the temporal check
        run: `reported_at` must fall inside the tier's half-open window — on or
        after the `closing_date` and strictly before that tier's end date — or the
        assessment is rejected with `ERR_OUT_OF_WARRANTY`."
        PRD §3.1: "Each window is half-open: coverage runs from the closing instant
        up to but not including the tier end instant, so a defect reported exactly
        at an end date is already out of term."

        Design: Difficulty/boundary_precision_check/coverage_term_end_exclusive
        """
        homeowner, home = setup_home(closing_date="2026-08-01")
        set_clock("2027-07-31T12:00:00Z")  # 12h before the 2027-08-01 end instant
        request = file_service_request(
            home["id"],
            homeowner["id"],
            item_category="DRYWALL_PAINT",
            description="Nail pops, living room",
        )
        assessed = assess_request(request["id"], assess_warrantable_payload())
        assert assessed["status"] == "APPROVED"
        assert assessed["determined_tier"] == "WORKMANSHIP", (
            "DRYWALL_PAINT maps to WORKMANSHIP; reported 2027-07-31T12:00:00Z is "
            "strictly before the end instant"
        )

    def test_reported_exactly_at_end_instant_out_of_warranty(self, api):
        """PRD §3.1: "Each window is half-open: coverage runs from the closing
        instant up to but not including the tier end instant, so a defect reported
        exactly at an end date is already out of term."
        PRD §3.2: "`reported_at` must fall inside the tier's half-open window — on
        or after the `closing_date` and strictly before that tier's end date — or
        the assessment is rejected with `ERR_OUT_OF_WARRANTY`."

        Design: Difficulty/boundary_precision_check/coverage_term_end_exclusive
        """
        homeowner, home = setup_home(closing_date="2026-08-01")
        set_clock("2027-08-01T00:00:00Z")  # exactly the workmanship end instant
        resp = api.create_service_request(
            create_service_request_payload(
                home["id"],
                item_category="DRYWALL_PAINT",
                description="Nail pops, hallway",
            ),
            make_homeowner_headers(homeowner["id"]),
        )
        request = validate_success(resp, 201)
        assert_instant_equal(
            request["reported_at"], "2027-08-01T00:00:00Z", "reported_at"
        )

        err_resp = api.assess_service_request(
            request["id"], assess_warrantable_payload(), REP
        )
        validate_error(err_resp, ApiErrorId.ERR_OUT_OF_WARRANTY)

        after = validate_success(api.get_service_request(request["id"], REP), 200)
        assert after["status"] == "RECEIVED", (
            "rejected assess leaves the request RECEIVED"
        )

"""Role authorisation and the two identity-keyed duty gates, the optimistic-concurrency
guards on departures and operators, and the immediacy with which a cancellation reports
its own money and released seats.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import HEADERS_BY_ROLE, TEST_USERS, make_guest_headers


def test_a_guest_books_and_then_cancels_its_own_booking(api):
    """PRD §2.1: "Concretely, a `Guest` caller may only reach a `Booking` whose `guest_id` equals their own `X-User-ID`, and only a refund-ledger entry belonging to such a booking."

    PRD §3.7: "Either the `Guest` themselves or the desk on their behalf may cancel, optionally supplying a `reason_code`, and only while the departure's `status` is none of `OPERATING`, `COMPLETED`, `CANCELLED_WEATHER` and `CANCELLED_OPERATIONAL`; otherwise the request is refused with `ERR_INVALID_DEPARTURE_STATE`."

    PRD §3.7: "A booking still in `BOOKED` moves `BOOKED → CANCELLED_BY_GUEST` with `financial_status` `AUTHORIZED → VOIDED`, an `AUTH_VOID` entry of `amount_cents` 0 and `refund_pct_bps` 0 on the `GUEST_INITIATED` `basis`, `retained_cents` left at 0, and its seats returned to its channel bucket."

    Design: Corner/rbac/the_guest_role_can_book_and_cancel_its_own_booking
    """
    world = fixtures.setup_selling_departure(api)
    guest = fixtures.create_guest(api, voyage_code=world.port_call["voyage_code"])
    guest_headers = make_guest_headers(guest["id"])
    departure_version = fixtures.get_departure_version(api, world.departure["id"])

    booking = validate_success(
            api.create_booking(
                factories.create_booking_payload(
                    world.departure["id"], guest["id"], departure_version
                ),
                guest_headers,
            ),
            201,
        )
    
    assert booking["guest_id"] == guest["id"]

    cancelled = validate_success(
            api.cancel_booking(
                booking["id"], {"reason_code": "GUEST_CHANGE_OF_PLAN"}, guest_headers
            ),
            200,
        )
    
    assertions.assert_field_values(
        cancelled,
        guest_id=guest["id"],
        fulfillment_status="CANCELLED_BY_GUEST",
        financial_status="VOIDED",
        refunded_cents=0,
        retained_cents=0,
    )

    departure = fixtures.get_departure(api, world.departure["id"])
    assertions.assert_field_values(
        departure,
        precruise_sold_seats=0,
        effective_precruise_available=25,
        seats_available_total=40,
    )


def test_all_seven_roles_read_the_same_port(api):
    """PRD §2.1: "Seven roles are recognised, spelled exactly as follows: `Guest`, `ShoreExcursionDesk`, `ExcursionManager`, `OperatorVettingOfficer`, `PortAgent`, `RiskOfficer`, and `FinanceController`."

    PRD §2.1: "Once identity is resolved, the declared role must appear in the operation's authorised role list; if it does not, the request is refused with `ERR_UNAUTHORIZED` (403), and that refusal precedes any existence check so that a wrong-role caller cannot use 404s to probe which identifiers exist."

    Design: Corner/rbac/every_role_can_read_a_port
    """
    port = fixtures.create_port(api)

    assert len(HEADERS_BY_ROLE) == 7
    for role, headers in HEADERS_BY_ROLE.items():
        data = validate_success(api.get_port(port["id"], headers), 200)
        assert "error_id" not in data, f"{role} read carried an error_id: {data}"
        assertions.assert_field_values(
            data,
            id=port["id"],
            port_code="COZ",
            docking_mode="ALONGSIDE",
            risk_buffer_minutes=30,
        )


def test_a_wrong_role_is_refused_before_any_existence_check(api):
    """PRD §2.1: "Once identity is resolved, the declared role must appear in the operation's authorised role list; if it does not, the request is refused with `ERR_UNAUTHORIZED` (403), and that refusal precedes any existence check so that a wrong-role caller cannot use 404s to probe which identifiers exist."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
    """
    unknown_id = "11111111-1111-4111-8111-111111111111"

    validate_error(
        api.create_port(
            factories.create_port_payload(
                port_code="SJU", name="San Juan", country_code="PR"
            ),
            TEST_USERS["desk_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api.catalog_action(
            unknown_id, {"action": "PUBLISH"}, TEST_USERS["port_agent_headers"]
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api.create_guest(factories.create_guest_payload(), TEST_USERS["guest_headers"]),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api.claim_action(
            unknown_id, {"action": "SEND_TO_OPERATOR"}, TEST_USERS["manager_headers"]
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api.fulfillment_action(
            unknown_id, {"action": "TICKET"}, TEST_USERS["finance_headers"]
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    validate_error(
        api.record_delay(
            unknown_id,
            {"additional_delay_minutes": 30, "reason_code": "WEATHER_HOLD"},
            TEST_USERS["risk_officer_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    _, port_meta = validate_paginated(api.list_ports(TEST_USERS["manager_headers"]))
    assert port_meta["total_count"] == 0
    _, guest_meta = validate_paginated(api.list_guests(TEST_USERS["desk_headers"]))
    assert guest_meta["total_count"] == 0


def test_the_officer_who_opened_the_claim_cannot_adjudicate_it(api):
    """PRD §2.10: "The claim records `submitted_by_user_id` at creation and `adjudicated_by_user_id` when it is decided, and the two must differ; an adjudication whose `X-User-ID` equals `submitted_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` (403)."

    PRD §3.8: "The `operator_charge_cents` actually charged to the operator is `settlement_amount_cents` multiplied by `liability_share_bps`, divided by ten thousand, rounded half up, and it may not exceed the operator's `insurance_liability_limit_cents` — the limit itself is acceptable — else `ERR_CLAIM_EXCEEDS_INSURANCE_LIMIT`."

    PRD §3.2: "From that average subtract 8 points for every critical finding, counting `critical_finding_count` summed across the audits in the window only, and subtract a further 5 points for every liability claim against this operator whose `status` is `ADJUDICATED_UPHELD` or `SETTLED`."

    Design: Corner/rbac/the_claim_submitter_cannot_adjudicate_the_claim_they_filed
    """
    world = fixtures.setup_ticketed_booking(api)
    fixtures.set_clock(api, "2026-09-15T08:00:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.check_in_booking(api, world.booking["id"])

    incident = fixtures.file_incident(
        api,
        world.booking["id"],
        category="INJURY",
        severity="MODERATE",
        occurred_utc="2026-09-15T08:25:00Z",
        narrative="Guest slipped on the wet pier ramp.",
    )
    claim = fixtures.open_claim(
        api,
        incident["id"],
        claimed_amount_cents=5000000,
        basis_code="NEGLIGENCE",
    )
    fixtures.claim_action(
        api, claim["id"], "SEND_TO_OPERATOR", headers=TEST_USERS["risk_officer_headers"]
    )
    assert claim["submitted_by_user_id"] == "u_risk_1"

    upheld_body = {
        "action": "ADJUDICATE_UPHELD",
        "liability_share_bps": 4000,
        "settlement_amount_cents": 4000000,
    }
    validate_error(
        api.claim_action(claim["id"], upheld_body, TEST_USERS["risk_officer_headers"]),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    adjudicated = validate_success(
            api.claim_action(
                claim["id"], upheld_body, TEST_USERS["second_risk_officer_headers"]
            ),
            200,
        )
    
    assertions.assert_field_values(
        adjudicated,
        status="ADJUDICATED_UPHELD",
        submitted_by_user_id="u_risk_1",
        adjudicated_by_user_id="u_risk_2",
        operator_charge_cents=1600000,
    )

    operator = fixtures.get_operator(api, world.operator["id"])
    assert operator["safety_score"] == 77


def test_the_newest_auditor_cannot_approve_the_operator_they_scored(api):
    """PRD §2.10: "The operator tracks this as `latest_audit_auditor_user_id`, which holds the `auditor_user_id` of the operator's most recent audit ordered by `conducted_on` descending and then `created_at` descending, and is null while no audit exists."

    PRD §2.10: "An approval whose `X-User-ID` equals that value is refused with `ERR_AUDITOR_CANNOT_APPROVE` (403)."

    PRD §3.2: "Assign base weights of 0.5, 0.3 and 0.2 to the audits in that order, truncated to however many audits are in the window, then divide each base weight by the sum of the base weights actually used, so that with three audits the weights stay 0.5, 0.3 and 0.2, with two they become 0.625 and 0.375, and with one it becomes 1.0."

    Design: Corner/rbac/the_latest_auditor_cannot_approve_the_operator_they_scored
    """
    port = fixtures.create_port(api)
    operator = fixtures.create_operator(api, port["id"])
    fixtures.record_safety_audit(api, operator["id"], auditor_user_id="u_aud_1")
    fixtures.vetting_action(api, operator["id"], "SUBMIT")

    validate_error(
        api.vetting_action(
            operator["id"], {"action": "APPROVE"}, TEST_USERS["auditor_headers"]
        ),
        ApiErrorId.ERR_AUDITOR_CANNOT_APPROVE.value,
    )

    approved = validate_success(
            api.vetting_action(
                operator["id"],
                {"action": "APPROVE"},
                TEST_USERS["vetting_officer_headers"],
            ),
            200,
        )
    
    assertions.assert_field_values(
        approved,
        vetting_status="APPROVED",
        latest_audit_auditor_user_id="u_aud_1",
        safety_score=82,
    )


def test_a_stale_departure_version_blocks_the_rebalance_until_it_is_re_read(api):
    """PRD §2.7: "Rebalancing a departure's channel split likewise requires `expected_departure_version` matching the departure's current `version`, and a mismatch yields the same `ERR_STALE_DEPARTURE_VERSION` (412)."

    PRD §3.5: "From those, `effective_precruise_available` is the effective pre-cruise allocation less `precruise_sold_seats`, floored at 0, and `effective_onboard_available` is the effective onboard allocation less `onboard_sold_seats`, floored at 0."

    Design: Corner/complexity_layers/a_stale_expected_departure_version_blocks_the_rebalance_and_the_fresh_one_lands
    """
    world = fixtures.setup_selling_departure(api)
    stale_version = fixtures.get_departure_version(api, world.departure["id"])
    fixtures.reschedule_meeting(api, world.departure["id"], "2026-09-15T10:00:00Z")

    validate_error(
        api.rebalance_allocation(
            world.departure["id"],
            {
                "expected_departure_version": stale_version,
                "precruise_allocation": 12,
                "onboard_allocation": 28,
            },
            TEST_USERS["manager_headers"],
        ),
        ApiErrorId.ERR_STALE_DEPARTURE_VERSION.value,
    )

    fresh_version = fixtures.get_departure_version(api, world.departure["id"])
    assert fresh_version > stale_version

    rebalanced = fixtures.rebalance_allocation(
        api, world.departure["id"], fresh_version, 12, 28
    )
    assertions.assert_field_values(
        rebalanced,
        precruise_allocation=12,
        onboard_allocation=28,
        total_capacity=40,
        effective_precruise_available=12,
        effective_onboard_available=28,
    )
    assert rebalanced["meeting_time_utc"].startswith("2026-09-15T10:00:00")


def test_a_stale_operator_version_blocks_statement_creation_until_it_is_re_read(api):
    """PRD §2.7: "Creating a commission statement requires `expected_operator_version` carrying the client's last observed `version` of the `TourOperator` being settled; a mismatch is rejected with `ERR_STALE_OPERATOR_VERSION` (412)."

    PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    PRD §3.2: "Recording an audit recomputes it immediately, as does every vetting action and every upheld claim adjudication."

    PRD §3.9: "The new statement is created in `DRAFT` with `issued_at` and `settled_at` both absent, and all nine waterfall steps computed onto it."

    Design: Corner/complexity_layers/a_stale_expected_operator_version_blocks_statement_creation
    """
    world = fixtures.setup_ticketed_booking(api)
    stale_version = fixtures.get_operator_version(api, world.operator["id"])
    fixtures.record_safety_audit(
        api,
        world.operator["id"],
        auditor_user_id="u_aud_2",
        audit_type="ANNUAL",
        conducted_on="2026-07-25T00:00:00Z",
        raw_score=90,
        critical_finding_count=0,
    )

    validate_error(
        api.create_commission_statement(
            factories.create_statement_payload(
                world.operator["id"], world.port_call["id"], stale_version, "PROVISIONAL"
            ),
            TEST_USERS["finance_headers"],
        ),
        ApiErrorId.ERR_STALE_OPERATOR_VERSION.value,
    )

    operator = fixtures.get_operator(api, world.operator["id"])
    assert operator["version"] > stale_version
    assertions.assert_field_values(
        operator, safety_score=87, latest_audit_auditor_user_id="u_aud_2"
    )

    statement = fixtures.create_statement(
        api,
        world.operator["id"],
        world.port_call["id"],
        basis="PROVISIONAL",
        expected_operator_version=operator["version"],
    )
    assertions.assert_field_values(
        statement,
        status="DRAFT",
        basis="PROVISIONAL",
        operator_id=world.operator["id"],
        port_call_id=world.port_call["id"],
    )


def test_the_departure_version_advances_by_exactly_one_on_every_write(api):
    """PRD §2.4: "Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

    PRD §2.4: "Selling a seat bumps both the `Booking` and its `ExcursionDeparture`."

    PRD §3.5: "Its `party_size` seats are consumed from its own channel bucket, the relevant sold counter and `seats_available_total` are updated, and the departure's `version` is bumped alongside the new booking's own."

    Design: Corner/complexity_layers/the_departure_version_advances_by_one_on_every_write
    """
    world = fixtures.setup_selling_departure(api)

    version_after_create = fixtures.get_departure_version(api, world.departure["id"])
    assert version_after_create == 1

    fixtures.reschedule_meeting(api, world.departure["id"], "2026-09-15T10:00:00Z")
    version_after_reschedule = fixtures.get_departure_version(api, world.departure["id"])
    assert version_after_reschedule == 2

    fixtures.rebalance_allocation(
        api, world.departure["id"], version_after_reschedule, 20, 20
    )
    version_after_rebalance = fixtures.get_departure_version(api, world.departure["id"])
    assert version_after_rebalance == 3

    guest = fixtures.create_guest(api, voyage_code=world.port_call["voyage_code"])
    booking = fixtures.create_booking(
        api,
        world.departure["id"],
        guest["id"],
        expected_departure_version=version_after_rebalance,
    )
    assert booking["party_size"] == 2

    departure = fixtures.get_departure(api, world.departure["id"])
    assertions.assert_field_values(
        departure, version=4, precruise_sold_seats=2, precruise_allocation=20
    )
    assert departure["meeting_time_utc"].startswith("2026-09-15T10:00:00")


def test_the_cancellation_response_already_carries_the_refund_and_the_released_seats(api):
    """PRD §3.7: "Below that but at 1440 minutes or more, the refund is 7500 basis points of `quoted_total_cents`."

    PRD §3.7: "`financial_status` then follows from the arithmetic: add the refund to the booking's existing `refunded_cents`, and if the new total is zero the status is `RETAINED`, if it is at least `charge_total_cents` the status is `REFUNDED`, and otherwise it is `PARTIALLY_REFUNDED`, with `retained_cents` set to `charge_total_cents` less the new refunded total."

    PRD §3.5: "Whenever the number of minutes from the logical clock to `meeting_time_utc` has fallen to 2880 or below, the pre-cruise release has happened: the effective pre-cruise allocation collapses to `precruise_sold_seats` exactly, and the effective onboard allocation becomes `total_capacity` less `precruise_sold_seats`, so every unsold pre-cruise seat joins the onboard pool."

    Design: Corner/consistency_model/the_cancellation_response_already_carries_the_refund_and_the_released_seats
    """
    world = fixtures.setup_ticketed_booking(api)
    assert world.booking["charge_total_cents"] == 27007

    fixtures.set_clock(api, "2026-09-14T09:00:00Z")

    cancelled = validate_success(
            api.cancel_booking(
                world.booking["id"],
                {"reason_code": "GUEST_CHANGE_OF_PLAN"},
                TEST_USERS["desk_headers"],
            ),
            200,
        )
    
    assertions.assert_field_values(
        cancelled,
        refunded_cents=19665,
        retained_cents=7342,
        charge_total_cents=27007,
        financial_status="PARTIALLY_REFUNDED",
        fulfillment_status="CANCELLED_BY_GUEST",
    )

    departure = fixtures.get_departure(api, world.departure["id"])
    assertions.assert_field_values(
        departure,
        precruise_sold_seats=0,
        effective_precruise_available=0,
        effective_onboard_available=40,
        seats_available_total=40,
    )

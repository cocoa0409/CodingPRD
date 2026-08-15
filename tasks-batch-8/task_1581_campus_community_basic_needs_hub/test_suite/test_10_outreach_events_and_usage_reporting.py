"""Outreach events: capacity-driven OPEN/FULL cycle, re-registration,
operational error codes — plus the cross-domain usage summary report."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    checkin_visit_with_line,
    checkout,
    create_active_client,
    create_agency,
    create_bed,
    create_coordinator,
    create_counselor,
    create_disbursed_grant,
    create_event_registration_payload,
    create_fund,
    create_item,
    create_open_event,
    create_pantry_staff,
    create_referral_payload,
    create_reserved_stay,
    create_reviewer,
    create_screening_payload,
    create_shelter_coordinator,
    get_success_data,
    register_client_for_event,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import (
    make_benefits_counselor_headers,
    make_client_headers,
    make_hub_admin_headers,
    make_partner_agency_rep_headers,
)

ADMIN = TEST_USERS["hub_admin_headers"]


def _event_by_id(admin_headers, event_id, **params):
    events = validate_success(api_client.list_outreach_events(admin_headers, params=params or None), 200)
    return [e for e in events if e["id"] == event_id][0]


class TestOpenFullCapacityCycle:
    def _setup(self):
        _, coord = create_coordinator()
        c1, _, c1_headers = create_active_client(
            coord, client_overrides={"alias_name": "oak"}
        )
        c2, _, c2_headers = create_active_client(
            coord,
            assessment_overrides=dict(
                household_size=3, monthly_income_cents=200000,
                housing_status="COST_BURDENED", dependents_under_18=2,
                receives_snap=False, receives_childcare_subsidy=False,
                food_insecurity_score=2, consent_confidential=True,
            ),
            client_overrides={"alias_name": "elm", "contact_channel": "NONE"},
        )
        event = create_open_event(
            "Pantry 101", event_date="2026-08-20T17:00:00Z", capacity=1,
            stigma_theme="NORMALIZATION",
        )
        return coord, c1, c1_headers, c2, c2_headers, event

    def test_full_event_rejects_registration(self, api):
        """PRD §3.8: "when `registered_count` reaches `capacity` the event
        flips automatically from `OPEN` to `FULL` and new registrations are
        rejected with `ERR_EVENT_FULL` ..."

        Design: Difficulty/non_linear_state_machine/event_open_full_open_capacity_cycle
        """
        _, _, c1_headers, c2, _, event = self._setup()
        register_client_for_event(event["id"], c1_headers["X-User-ID"], c1_headers)
        full = _event_by_id(ADMIN, event["id"])
        assert full["status"] == "FULL"
        assert full["registered_count"] == 1

        res = api.register_for_event(
            event["id"], create_event_registration_payload(c2["id"]),
            make_client_headers(c2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_EVENT_FULL, expected_status=409)

    def test_cancel_reopens_seat_and_reregister_refills(self, api):
        """PRD §3.8: "when a cancellation drops the count back below capacity
        the event flips from `FULL` to `OPEN` and registrations are accepted
        again."
        PRD §3.8: "an optional `display_alias` — the name shown on the
        attendee list — which defaults to the client's `alias_name` ..."

        Design: Difficulty/non_linear_state_machine/event_open_full_open_capacity_cycle
        """
        _, _, c1_headers, c2, _, event = self._setup()
        r1 = register_client_for_event(event["id"], c1_headers["X-User-ID"], c1_headers)
        cancelled = validate_success(api.cancel_registration(r1["id"], c1_headers), 200)
        assert cancelled["status"] == "CANCELLED"

        reopened = _event_by_id(ADMIN, event["id"])
        assert reopened["status"] == "OPEN"
        assert reopened["registered_count"] == 0

        r2 = register_client_for_event(
            event["id"], c2["id"], make_client_headers(c2["id"]),
            display_alias="elm-alias",
        )
        assert r2["display_alias"] == "elm-alias"
        full_again = _event_by_id(ADMIN, event["id"])
        assert full_again["status"] == "FULL"
        assert full_again["registered_count"] == 1


def test_event_registration_cancel_reregister_cycle(api):
    """PRD §3.8: "Uniqueness holds per event and client among non-cancelled
    registrations: a second live registration for the same pair is rejected
    with `ERR_ALREADY_REGISTERED`, while re-registering a client whose earlier
    row was cancelled reactivates that very row from `CANCELLED` back to
    `REGISTERED` rather than creating a duplicate."

    Design: Corner/state_machines/event_registration_cancel_reregister_cycle
    """
    _, coord = create_coordinator()
    client, _, client_headers = create_active_client(
        coord, client_overrides={"alias_name": "ev"}
    )
    event = create_open_event(
        "Cooking Demo", event_date="2026-08-20T18:00:00Z", capacity=3,
        stigma_theme="PEER_LED",
    )
    r1 = register_client_for_event(event["id"], client["id"], client_headers)
    cancelled = validate_success(api.cancel_registration(r1["id"], client_headers), 200)
    assert cancelled["status"] == "CANCELLED"

    r2 = register_client_for_event(event["id"], client["id"], client_headers)
    assert r2["status"] == "REGISTERED"
    assert r2["id"] == r1["id"], "reactivates the same (event, client) row"

    res = api.register_for_event(
        event["id"], create_event_registration_payload(client["id"]), client_headers
    )
    validate_error(res, ApiErrorId.ERR_ALREADY_REGISTERED, expected_status=409)

    regs = validate_success(
        api.list_event_registrations(ADMIN, params={"event_id": event["id"]}), 200
    )
    assert len(regs) == 1, "exactly one row exists for the pair"
    event_after = _event_by_id(ADMIN, event["id"])
    assert event_after["registered_count"] == 1


def test_event_operational_errors_batch(api):
    """PRD §3.8: "the logical now strictly before `event_date` (registration
    at or after the start is `ERR_EVENT_PAST`)".
    PRD §3.8: "Marking attendance, by a `HubAdmin`, moves `REGISTERED` to
    `ATTENDED` — it requires the registration still `REGISTERED` (else
    `ERR_REGISTRATION_NOT_ACTIONABLE`) and the event already `COMPLETED`
    (else `ERR_EVENT_NOT_COMPLETED`)".
    PRD §3.8: "A `HubAdmin` opens a `PLANNED` event for registration (from any
    other state, `ERR_INVALID_STATE`) ..."
    PRD §3.8: "Cancelling a registration ... moves `REGISTERED` to `CANCELLED`
    (else `ERR_REGISTRATION_NOT_ACTIONABLE`) ..."

    Design: Corner/errors/event_operational_errors_batch
    """
    _, coord = create_coordinator()
    client, _, client_headers = create_active_client(
        coord, client_overrides={"alias_name": "eo"}
    )
    e1 = create_open_event(
        "Early Fair", event_date="2026-08-02T12:00:00Z", capacity=5,
        stigma_theme="RESOURCE_FAIR",
    )
    e2 = create_open_event(
        "Late Fair", event_date="2026-08-20T12:00:00Z", capacity=5,
        stigma_theme="PEER_LED",
    )
    reg = register_client_for_event(e2["id"], client["id"], client_headers)

    set_clock("2026-08-03T00:00:00Z")

    res = api.register_for_event(
        e1["id"], create_event_registration_payload(client["id"]), client_headers
    )
    validate_error(res, ApiErrorId.ERR_EVENT_PAST, expected_status=422)

    res = api.mark_attended(reg["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_EVENT_NOT_COMPLETED, expected_status=409)

    res = api.open_event(e2["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    validate_success(api.cancel_registration(reg["id"], client_headers), 200)
    res = api.cancel_registration(reg["id"], client_headers)
    validate_error(res, ApiErrorId.ERR_REGISTRATION_NOT_ACTIONABLE, expected_status=409)


def test_usage_summary_computed_read(api):
    """PRD §3.9: "`clients_active` counts clients currently `ACTIVE` — a
    point-in-time figure, window-agnostic. `visits_completed` counts pantry
    visits `COMPLETED` with `visit_date` in the window, and `points_redeemed`
    sums their `points_spent`. `screenings_by_program` counts screenings
    created in the window, broken out by `SNAP`, `CHILDCARE`, and `HOUSING`.
    `grants_approved_cents` sums `approved_cents` over applications whose
    `approved_at` falls in the window, and `grants_disbursed_cents` the same
    over `disbursed_at`. `referrals_by_status` counts referrals created in the
    window across all eight referral statuses. `shelter_nights_served` sums,
    over stays `CHECKED_OUT` with `actual_check_out_date` in the window, the
    nights between `check_in_date` and the actual check-out date.
    `event_attendance` counts registrations `ATTENDED` whose event's
    `event_date` falls in the window."
    PRD §3.9: "an omitted bound is open-ended."

    Design: Corner/endpoints/usage_summary_computed_read
    """
    _, coord = create_coordinator()
    _, pantry = create_pantry_staff()
    _, couns = create_counselor()
    _, reviewer = create_reviewer()
    _, shelter = create_shelter_coordinator()
    client, _, client_headers = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=2, monthly_income_cents=120000,
            housing_status="UNSTABLE", dependents_under_18=1,
            receives_snap=False, receives_childcare_subsidy=False,
            food_insecurity_score=4, consent_confidential=True,
        ),
        client_overrides={"alias_name": "sum"},
    )

    # One completed pantry visit of 20 points.
    item = create_item("Box", point_cost=20, quantity_on_hand=5,
                       reorder_threshold=0, per_visit_limit=3)
    visit, _ = checkin_visit_with_line(pantry, client["id"], item["id"], 1)
    checkout(pantry, visit["id"])

    # One SNAP screening carried through determination.
    screening = validate_success(
        api.create_screening(client["id"], create_screening_payload("SNAP"), couns), 201
    )
    couns_headers = make_benefits_counselor_headers(screening["counselor_id"])
    validate_success(api.score_screening(screening["id"], couns_headers), 200)
    validate_success(api.assist_screening(screening["id"], couns_headers), 200)
    validate_success(api.submit_screening_application(screening["id"], couns_headers), 200)
    determined = validate_success(
        api.determine_screening(screening["id"], {"outcome": "APPROVED_BY_AGENCY"},
                                couns_headers),
        200,
    )
    assert determined["status"] == "DETERMINED"

    # One grant approved and disbursed for 100000.
    fund = create_fund("FY26-r", allocated_cents=500000)
    disbursed, _ = create_disbursed_grant(
        client, fund, reviewer, admin_headers=make_hub_admin_headers("admin-9"),
        category="RENT", requested_cents=100000, hardship_statement="gap",
    )
    assert disbursed["status"] == "DISBURSED"

    # One referral carried to SERVICE_RECEIVED.
    agency = create_agency("County SNAP", service_categories=["SNAP_APPLICATION"],
                           weekly_capacity=5)
    referral = get_success_data(
        api.create_referral(client["id"], create_referral_payload(agency["id"]), coord)
    )
    validate_success(api.send_referral(referral["id"], coord), 200)
    rep = make_partner_agency_rep_headers(agency["id"])
    validate_success(api.acknowledge_referral(referral["id"], rep), 200)
    validate_success(
        api.book_appointment(referral["id"], {"appointment_date": "2026-08-02"}, rep), 200
    )
    validate_success(api.record_service(referral["id"], rep), 200)

    # One two-night stay checked in on 2026-08-01 and out on 2026-08-03.
    bed = create_bed(shelter, site="Haven", label="R1")
    stay = create_reserved_stay(client["id"], bed["id"], shelter,
                                check_in_date="2026-08-01", planned_nights=2)
    validate_success(api.shelter_stay_check_in(stay["id"], shelter), 200)

    # One event registration later marked ATTENDED.
    event = create_open_event(
        "Resource Fair", event_date="2026-08-05T12:00:00Z", capacity=10,
        stigma_theme="RESOURCE_FAIR",
    )
    reg = register_client_for_event(event["id"], client["id"], client_headers)

    set_clock("2026-08-03T09:00:00Z")
    validate_success(api.shelter_stay_check_out(stay["id"], shelter), 200)
    validate_success(api.complete_event(event["id"], ADMIN), 200)
    validate_success(api.mark_attended(reg["id"], ADMIN), 200)

    report = validate_success(api.get_usage_summary(ADMIN), 200)
    assert report["clients_active"] == 1
    assert report["visits_completed"] == 1
    assert report["points_redeemed"] == 20
    assert report["screenings_by_program"] == {"SNAP": 1, "CHILDCARE": 0, "HOUSING": 0}
    assert report["grants_approved_cents"] == 100000
    assert report["grants_disbursed_cents"] == 100000
    assert report["referrals_by_status"] == {
        "INITIATED": 0, "SENT": 0, "ACKNOWLEDGED": 0, "APPOINTMENT_BOOKED": 0,
        "SERVICE_RECEIVED": 1, "DECLINED": 0, "WITHDRAWN": 0, "EXPIRED": 0,
    }
    assert report["shelter_nights_served"] == 2
    assert report["event_attendance"] == 1

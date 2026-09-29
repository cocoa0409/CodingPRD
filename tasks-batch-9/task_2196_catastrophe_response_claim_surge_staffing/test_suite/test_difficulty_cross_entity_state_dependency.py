"""Queue A — rule_id: cross_entity_state_dependency.

A child transition is legal on its own terms and blocked solely by the state of a
different entity; moving that other entity unblocks the identical call.
"""
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money_equals
from test_helpers.test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_deployment_coordinator_headers,
    make_vendor_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")


# ---------------------------------------------------------------------------
# Instance 1 — deployment_confirm_gated_by_adjuster_resting_axis
# ---------------------------------------------------------------------------
def _resting_adjuster_with_a_clear_second_deployment(api):
    """CAT-2026-701 DECLARED; one DESK deployment confirmed then demobilized at
    2026-08-02T00:00:00Z, leaving the adjuster RESTING; a second DESK deployment for
    2026-10-01 -> 2026-10-05 sits in REQUESTED, 26 days clear of the first window.
    The clock is left six hours into the twelve-hour rest window."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-701",
                "peril_type": "HAIL",
                "jurisdiction_state": "TX",
                "event_start_utc": "2026-07-28T00:00:00.000Z",
                "exposure_count": 500,
                "avg_insured_value": 170000,
                "expected_severity_index": 0.0800,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    adjuster = validate_success(
        api.create_adjuster(
            {
                "full_name": "Rest Gate",
                "employment_type": "STAFF",
                "home_state": "TX",
                "licensed_states": ["TX"],
                "license_expiry_utc": "2027-08-31T00:00:00.000Z",
                "max_open_claims": 10,
                "daily_rate": 480,
                "per_diem_rate": 0,
                "desk_certified": True,
                "aerial_certified": False,
            },
            DC,
        ),
        201,
    )
    first = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "DESK",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-05T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    validate_success(api.confirm_deployment(first["id"], DC))
    validate_success(api.set_clock("2026-08-02T00:00:00.000Z", DC))
    validate_success(api.demobilize_deployment(first["id"], DC))
    second = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "DESK",
                "window_start_utc": "2026-10-01T00:00:00.000Z",
                "window_end_utc": "2026-10-05T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    validate_success(api.set_clock("2026-08-02T06:00:00.000Z", DC))
    return event, adjuster, first, second


def test_confirmation_is_refused_while_the_adjuster_is_still_resting(api):
    """PRD §3.5: "The adjuster's `deployment_status` must be `AVAILABLE`
    (`ERR_ADJUSTER_NOT_AVAILABLE`) and their `credential_status` must be `VALID`,
    `EXPIRING` or `WAIVED` (`ERR_ADJUSTER_CREDENTIAL_INVALID`)."
    PRD §3.3: "Demobilization of that deployment moves them `DEPLOYED → RESTING`, stamps
    `last_demobilized_at_utc` with the current logical-clock instant, and — because the
    adjuster has left `DEPLOYED` — cancels every inspection assignment of theirs still in
    `SCHEDULED` or `IN_PROGRESS`."
    PRD §3.3: "The `cumulative_deployed_hours` input is itself computed: the sum, over
    the adjuster's deployments whose status is `ON_SITE` or `DEMOBILIZED`, of the number
    of hours from that deployment's `window_start_utc` to its `window_end_utc`, to 2
    decimal places."

    Design: Difficulty/cross_entity_state_dependency/deployment_confirm_gated_by_adjuster_resting_axis
    """
    _, adjuster, first, second = _resting_adjuster_with_a_clear_second_deployment(api)

    validate_error(
        api.confirm_deployment(second["id"], DC), ApiErrorId.ERR_ADJUSTER_NOT_AVAILABLE, 409
    )

    assert validate_success(api.get_deployment(second["id"], DC))["status"] == "REQUESTED"
    assert validate_success(api.get_deployment(first["id"], DC))["status"] == "DEMOBILIZED"
    resting = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert resting["deployment_status"] == "RESTING"
    assert resting["last_demobilized_at_utc"] == "2026-08-02T00:00:00.000Z"
    # 2026-09-01 -> 2026-09-05 is 4 whole days of window.
    assert_money_equals(
        resting["cumulative_deployed_hours"], 96.00, "cumulative_deployed_hours"
    )


def test_the_identical_confirmation_succeeds_once_the_rest_buffer_elapses(api):
    """PRD §3.3: "Twelve hours of rest later, meaning once the clock reaches or passes
    `last_demobilized_at_utc` advanced by the rest buffer, they return
    `RESTING → AVAILABLE` on the next read or write with their score recomputed."
    PRD §3.5: "**Confirmation** moves the deployment `REQUESTED → CONFIRMED` and is where
    every eligibility question is asked again, in earnest."
    PRD §3.3: "On the deployment axis, confirmation of a deployment for an available
    adjuster moves them `AVAILABLE → DEPLOYED` and recomputes their score."

    Design: Difficulty/cross_entity_state_dependency/deployment_confirm_gated_by_adjuster_resting_axis
    """
    _, adjuster, _, second = _resting_adjuster_with_a_clear_second_deployment(api)
    validate_error(
        api.confirm_deployment(second["id"], DC), ApiErrorId.ERR_ADJUSTER_NOT_AVAILABLE
    )

    validate_success(api.set_clock("2026-08-02T12:00:00.000Z", DC))
    confirmed = validate_success(api.confirm_deployment(second["id"], DC))

    assert confirmed["status"] == "CONFIRMED"
    assert validate_success(api.get_adjuster(adjuster["id"], DC))["deployment_status"] == "DEPLOYED"


# ---------------------------------------------------------------------------
# Instance 2 — housing_block_open_gated_by_event_declaration
# ---------------------------------------------------------------------------
def _pending_block_on_a_monitoring_event(api):
    """CAT-2026-702 deliberately left in MONITORING, carrying one PENDING 5-room
    block for 2026-09-01 -> 2026-09-11."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-702",
                "peril_type": "WILDFIRE",
                "jurisdiction_state": "CO",
                "event_start_utc": "2026-08-05T00:00:00.000Z",
                "exposure_count": 250,
                "avg_insured_value": 340000,
                "expected_severity_index": 0.2000,
            },
            CM,
        ),
        201,
    )
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Front Range Suites",
                "city": "Boulder",
                "rooms_total": 5,
                "nightly_rate": 190,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-11T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    return event, block


def test_a_block_on_a_monitoring_event_cannot_be_opened(api):
    """PRD §3.4: "Two further conditions apply: the block must hold at least one room, so
    a block created with `rooms_total` of zero can never be opened and any attempt is
    refused with `ERR_HOUSING_BLOCK_EMPTY`; and the parent event must be `DECLARED` or
    `SURGE_ACTIVE`, otherwise `ERR_EVENT_NOT_DECLARED`."
    PRD §3.4: "A newly held block is `PENDING`, with `rooms_occupied` of zero and
    `rooms_available` equal to `rooms_total`."

    Design: Difficulty/cross_entity_state_dependency/housing_block_open_gated_by_event_declaration
    """
    event, block = _pending_block_on_a_monitoring_event(api)
    assert block["status"] == "PENDING"

    validate_error(
        api.open_housing_block(block["id"], DC), ApiErrorId.ERR_EVENT_NOT_DECLARED, 409
    )

    assert validate_success(api.get_housing_block(block["id"], DC))["status"] == "PENDING"
    assert validate_success(api.get_event(event["id"], CM))["status"] == "MONITORING"


def test_declaring_the_parent_unblocks_the_identical_open_call(api):
    """PRD §3.4: "Opening a block moves it `PENDING → ACTIVE` and is refused with
    `ERR_HOUSING_NOT_PENDING` from any other status."
    PRD §3.4: "From that span the system computes `block_night_count`, the number of whole
    days from `block_start_date` up to but not including `block_end_date`."
    PRD §3.4: "Opening recomputes the parent event's `housing_committed_cost`, because the
    block now sits in the committed population."

    Design: Difficulty/cross_entity_state_dependency/housing_block_open_gated_by_event_declaration
    """
    event, block = _pending_block_on_a_monitoring_event(api)
    validate_error(api.open_housing_block(block["id"], DC), ApiErrorId.ERR_EVENT_NOT_DECLARED)

    validate_success(api.declare_event(event["id"], CM))
    opened = validate_success(api.open_housing_block(block["id"], DC))

    assert opened["status"] == "ACTIVE"
    assert opened["rooms_total"] == 5
    assert opened["rooms_available"] == 5
    assert opened["rooms_occupied"] == 0
    assert opened["block_night_count"] == 10


# ---------------------------------------------------------------------------
# Instance 3 — vendor_assignment_accept_gated_by_firm_network_status
# ---------------------------------------------------------------------------
def _dispatched_job_at_an_inactive_firm(api):
    """CAT-2026-703 DECLARED; one NETWORK_INACTIVE MITIGATION firm licensed in NC with
    max_concurrent_jobs 2; one COMPLEX claim carrying a DISPATCHED assignment pinned to
    that firm."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-703",
                "peril_type": "WILDFIRE",
                "jurisdiction_state": "NC",
                "event_start_utc": "2026-07-27T00:00:00.000Z",
                "exposure_count": 350,
                "avg_insured_value": 280000,
                "expected_severity_index": 0.1500,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    firm = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Blue Ridge Mitigation LLC",
                "vendor_type": "MITIGATION",
                "service_states": ["NC"],
                "max_concurrent_jobs": 2,
                "performance_score": 88.00,
            },
            make_vendor_coordinator_headers("vc_seed"),
        ),
        201,
    )
    claim = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-7301",
                "loss_state": "NC",
                "loss_date_utc": "2026-07-27T00:00:00.000Z",
                "reported_loss_amount": 90000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 200000,
                        "deductible_amount": 2500,
                        "estimated_damage_amount": 110000,
                    }
                ],
                "event_id": event["id"],
                "access_status": "ACCESSIBLE",
            },
            CE,
        ),
        201,
    )
    claim = validate_success(api.triage_claim(claim["id"], CE))
    assignment = validate_success(
        api.create_vendor_assignment(
            {
                "claim_id": claim["id"],
                "scope_amount": 40000,
                "required_vendor_type": "MITIGATION",
                "vendor_firm_id": firm["id"],
            },
            CE,
        ),
        201,
    )
    return event, firm, claim, assignment


def test_an_inactive_firm_cannot_accept_its_own_dispatched_job(api):
    """PRD §3.9: "**Accepting** moves the assignment `DISPATCHED → ACCEPTED`; the
    assignment must be `DISPATCHED` (`ERR_VENDOR_ASSIGNMENT_NOT_DISPATCHED`), the firm's
    own `status` must be `ACTIVATED` and not `CAPACITY_HOLD` or `SUSPENDED`
    (`ERR_VENDOR_NOT_ACTIVATED`), and its `open_job_count` must be strictly below
    `max_concurrent_jobs` (`ERR_VENDOR_CAPACITY_EXCEEDED`); the firm's `open_job_count` is
    recomputed, taking it `ACTIVATED → CAPACITY_HOLD` when the count reaches the ceiling."
    PRD §3.9: "A registered firm sits in `NETWORK_INACTIVE` with `activated_for_event_id`
    null and `open_job_count` of zero."
    PRD §3.9: "A created assignment is `DISPATCHED`, stamps `dispatched_at_utc` at the
    current logical-clock instant, records `EXPLICIT_VENDOR` or `SELECTOR_RANKED` in
    `selection_reason`, and triggers a recompute of the firm's `open_job_count`."

    Design: Difficulty/cross_entity_state_dependency/vendor_assignment_accept_gated_by_firm_network_status
    """
    _, firm, claim, assignment = _dispatched_job_at_an_inactive_firm(api)
    firm_headers = make_vendor_coordinator_headers(firm["id"])
    assert assignment["selection_reason"] == "EXPLICIT_VENDOR"
    # base 100 * (90000/200000) = 45.00; * 1.25 WILDFIRE = 56.25; + 20 * 0.1500.
    assert_money_equals(claim["severity_score"], 59.25, "severity_score")
    assert claim["triage_tier"] == "COMPLEX"

    error = validate_error(
        api.accept_vendor_assignment(assignment["id"], firm_headers),
        ApiErrorId.ERR_VENDOR_NOT_ACTIVATED,
        409,
    )

    assert error["error_id"] != ApiErrorId.ERR_NOT_ASSIGNED_VENDOR.value
    assert error["error_id"] != ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED.value
    refreshed = validate_success(api.get_vendor_assignment(assignment["id"], firm_headers))
    assert refreshed["status"] == "DISPATCHED"
    assert validate_success(api.get_vendor_firm(firm["id"], firm_headers))["status"] == (
        "NETWORK_INACTIVE"
    )


def test_activating_the_firm_unblocks_the_identical_acceptance(api):
    """PRD §3.9: "**Activation** moves a firm `NETWORK_INACTIVE → ACTIVATED` against a
    named `event_id`, which is stored in `activated_for_event_id`."
    PRD §3.9: "Occupancy then drives the firm automatically: when a job acceptance drives
    `open_job_count` to exactly `max_concurrent_jobs`, the firm moves
    `ACTIVATED → CAPACITY_HOLD`; when a job leaves the open population and
    `open_job_count` falls back below the ceiling, the firm moves
    `CAPACITY_HOLD → ACTIVATED`."

    Design: Difficulty/cross_entity_state_dependency/vendor_assignment_accept_gated_by_firm_network_status
    """
    event, firm, _, assignment = _dispatched_job_at_an_inactive_firm(api)
    firm_headers = make_vendor_coordinator_headers(firm["id"])
    validate_error(
        api.accept_vendor_assignment(assignment["id"], firm_headers),
        ApiErrorId.ERR_VENDOR_NOT_ACTIVATED,
    )

    validate_success(
        api.activate_vendor_firm(firm["id"], {"event_id": event["id"]}, firm_headers)
    )
    accepted = validate_success(api.accept_vendor_assignment(assignment["id"], firm_headers))

    assert accepted["status"] == "ACCEPTED"
    refreshed_firm = validate_success(api.get_vendor_firm(firm["id"], firm_headers))
    # One open job against a ceiling of 2, so the firm stays off CAPACITY_HOLD.
    assert refreshed_firm["status"] == "ACTIVATED"
    assert refreshed_firm["open_job_count"] == 1
    assert refreshed_firm["activated_for_event_id"] == event["id"]

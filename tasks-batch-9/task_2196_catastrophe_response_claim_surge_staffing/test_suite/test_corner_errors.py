"""Rejection-surface corner tests: one refused request per rule, plus its no-op proof.

Each test drives a single request that the PRD requires the server to refuse,
asserts the exact `error_id` and HTTP status, and then re-reads the rows the
request touched to prove nothing was written on the way out.
"""
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money_equals
from test_helpers.constants import CLOCK_START_UTC
from test_helpers.test_users import (
    make_adjuster_headers,
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_compliance_officer_headers,
    make_deployment_coordinator_headers,
    make_vendor_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")
CO = make_compliance_officer_headers("co_1")

MISSING_UUID = "00000000-0000-4000-8000-000000000000"


# --------------------------------------------------------------------------
# local builders (the server restarts per test, so every precondition is
# built inside the test that needs it)
# --------------------------------------------------------------------------
def _event_payload(cat_code, **overrides):
    payload = {
        "cat_code": cat_code,
        "peril_type": "HURRICANE",
        "jurisdiction_state": "FL",
        "event_start_utc": "2026-07-28T00:00:00.000Z",
        "exposure_count": 1000,
        "avg_insured_value": 250000,
        "expected_severity_index": 0.0500,
    }
    payload.update(overrides)
    return payload


def _create_event(api, cat_code, **overrides):
    return validate_success(api.create_event(_event_payload(cat_code, **overrides), CM), 201)


def _declared_event(api, cat_code, **overrides):
    event = _create_event(api, cat_code, **overrides)
    return validate_success(api.declare_event(event["id"], CM))


def _block_payload(event_id, **overrides):
    payload = {
        "event_id": event_id,
        "hotel_name": "Gulfside Inn",
        "city": "Tampa",
        "rooms_total": 10,
        "nightly_rate": 200,
        "block_start_date": "2026-08-04T00:00:00.000Z",
        "block_end_date": "2026-08-09T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def _active_block(api, event_id, **overrides):
    block = validate_success(api.create_housing_block(_block_payload(event_id, **overrides), DC), 201)
    return validate_success(api.open_housing_block(block["id"], DC))


def _adjuster(api, full_name, **overrides):
    payload = {
        "full_name": full_name,
        "employment_type": "STAFF",
        "home_state": "FL",
        "licensed_states": ["FL"],
        "license_expiry_utc": "2027-12-31T00:00:00.000Z",
        "max_open_claims": 5,
        "daily_rate": 500,
        "per_diem_rate": 100,
        "desk_certified": False,
        "aerial_certified": False,
    }
    payload.update(overrides)
    return validate_success(api.create_adjuster(payload, DC), 201)


def _snapshot(api, event_id):
    event = validate_success(api.get_event(event_id, CM))
    payload = {
        "event_id": event_id,
        "method": "EXPOSURE_BASED",
        "expected_event_version": event["version"],
    }
    return validate_success(api.create_loss_estimate(payload, CM), 201)


def _line(code="DWELLING", limit=200000, deductible=1000, estimated=6000):
    return {
        "coverage_code": code,
        "limit_amount": limit,
        "deductible_amount": deductible,
        "estimated_damage_amount": estimated,
    }


def _claim(api, event_id, policy_number, reported, lines, **overrides):
    payload = {
        "event_id": event_id,
        "policy_number": policy_number,
        "loss_state": "FL",
        "loss_date_utc": "2026-07-30T00:00:00.000Z",
        "reported_loss_amount": reported,
        "coverage_lines": lines,
    }
    payload.update(overrides)
    return validate_success(api.create_claim(payload, CE), 201)


def _triaged_claim(api, event_id, policy_number, reported, lines, **overrides):
    claim = _claim(api, event_id, policy_number, reported, lines, **overrides)
    return validate_success(api.triage_claim(claim["id"], CE))


def test_event_not_found_on_housing_block_create(api):
    """A housing block naming an unknown event is a 404 and creates nothing.

    PRD 2.4: "A reference that does not resolve produces the corresponding
    not-found error at HTTP 404: `ERR_EVENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_ADJUSTER_NOT_FOUND`, `ERR_HOUSING_BLOCK_NOT_FOUND`,
    `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_ADVANCE_NOT_FOUND`, `ERR_VENDOR_FIRM_NOT_FOUND`,
    `ERR_VENDOR_ASSIGNMENT_NOT_FOUND`, `ERR_BULLETIN_NOT_FOUND`, and
    `ERR_BATCH_NOT_FOUND`."

    Design: Corner/errors/corner_err_event_not_found_on_housing_block_create
    """
    response = api.create_housing_block(_block_payload(MISSING_UUID), DC)

    validate_error(response, ApiErrorId.ERR_EVENT_NOT_FOUND, 404)

    _, meta = validate_paginated(api.list_housing_blocks(DC))
    assert meta["total_count"] == 0


def test_cat_code_taken_on_second_event(api):
    """A second event reusing a live `cat_code` is refused and never stored.

    PRD 3.1: "The registration payload carries the industry `cat_code` the
    carrier intends to use (between 3 and 24 characters, and unique across all
    events in the system, compared case-sensitively — a collision is refused
    with `ERR_CAT_CODE_TAKEN`), the `peril_type` driving the loss, which is one
    of `HURRICANE`, `WILDFIRE`, `HAIL`, `FLOOD`, `WINTER_STORM` or
    `EARTHQUAKE`; the `jurisdiction_state` whose regulator will govern the
    response, as a two-letter uppercase state code; the `event_start_utc`
    first-loss instant of the footprint; and three underwriting inputs
    describing the exposed book — `exposure_count`, the number of insured risks
    inside the footprint, which may be zero but never negative;
    `avg_insured_value`, the average total insured value per exposed risk in
    whole dollars, likewise never negative; and `expected_severity_index`, the
    damage-ratio expectation for this peril footprint, a value from 0.0 through
    1.0 inclusive carried to 4 decimal places."

    Design: Corner/errors/corner_err_cat_code_taken_on_second_event
    """
    _create_event(api, "CAT-2026-130")

    response = api.create_event(
        _event_payload(
            "CAT-2026-130",
            peril_type="WILDFIRE",
            jurisdiction_state="CA",
            event_start_utc="2026-08-01T00:00:00.000Z",
            exposure_count=500,
            avg_insured_value=300000,
            expected_severity_index=0.0900,
        ),
        CM,
    )

    validate_error(response, ApiErrorId.ERR_CAT_CODE_TAKEN, 409)

    _, meta = validate_paginated(api.list_events(CM))
    assert meta["total_count"] == 1


def test_duplicate_claim_same_policy_and_loss_date(api):
    """A second claim on the same policy and loss date is a duplicate.

    PRD 3.6: "Another claim already holding the same `policy_number` and
    `loss_date_utc` pair makes the intake a duplicate, refused with
    `ERR_DUPLICATE_CLAIM`."

    Design: Corner/errors/corner_err_duplicate_claim_same_policy_and_loss_date
    """
    event = _declared_event(api, "CAT-2026-131")
    _claim(
        api,
        event["id"],
        "POL-1001",
        8000,
        [_line()],
        loss_date_utc="2026-07-28T00:00:00.000Z",
    )

    response = api.create_claim(
        {
            "event_id": event["id"],
            "policy_number": "POL-1001",
            "loss_state": "FL",
            "loss_date_utc": "2026-07-28T00:00:00.000Z",
            "reported_loss_amount": 42000,
            "coverage_lines": [_line(code="CONTENTS", limit=100000, deductible=500, estimated=40000)],
        },
        CE,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_CLAIM, 409)

    _, meta = validate_paginated(api.list_claims(CE))
    assert meta["total_count"] == 1


def test_jurisdiction_mismatch_on_bulletin_activate(api):
    """A Texas bulletin cannot take force on a Florida event.

    PRD 3.2: "The bulletin must be in `DRAFT` (`ERR_BULLETIN_NOT_DRAFT`); its
    parent event must be in `DECLARED` or `SURGE_ACTIVE`
    (`ERR_EVENT_NOT_DECLARED`), since a bulletin cannot bind an event the
    carrier has not yet declared or has already closed out; and the bulletin's
    `jurisdiction_state` must equal the parent event's `jurisdiction_state`
    (`ERR_JURISDICTION_MISMATCH`) — a Florida bulletin does not bind a Texas
    event."
    PRD 3.2: "Activation stamps `activated_at_utc` with the current
    logical-clock instant."

    Design: Corner/errors/corner_err_jurisdiction_mismatch_on_bulletin_activate
    """
    event = _declared_event(api, "CAT-2026-132")
    bulletin = validate_success(
        api.create_bulletin(
            {
                "event_id": event["id"],
                "bulletin_number": "TX-2026-01",
                "jurisdiction_state": "TX",
                "bulletin_type": "CLAIM_DEADLINE_EXTENSION",
                "effective_from": "2026-07-30T00:00:00.000Z",
                "effective_to": "2026-09-01T00:00:00.000Z",
                "deadline_extension_days": 30,
            },
            CO,
        ),
        201,
    )
    assert bulletin["status"] == "DRAFT"

    response = api.activate_bulletin(bulletin["id"], CO)

    validate_error(response, ApiErrorId.ERR_JURISDICTION_MISMATCH, 409)

    read_bulletin = validate_success(api.get_bulletin(bulletin["id"], CO))
    assert read_bulletin["status"] == "DRAFT"
    assert read_bulletin["activated_at_utc"] is None


def test_invalid_window_zero_night_housing_block(api):
    """A block whose end date equals its start date is a malformed interval.

    PRD 2.11: "Position 16 checks interval well-formedness on bulletin
    creation, deployment creation, housing-block creation and
    inspection-assignment creation: a bulletin's `effective_to` must be
    strictly later than its `effective_from`, a deployment's or assignment's
    `window_end_utc` strictly later than its `window_start_utc`, and a block's
    `block_end_date` strictly later than its `block_start_date`, otherwise
    `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Corner/errors/corner_err_invalid_window_zero_night_housing_block
    """
    event = _declared_event(api, "CAT-2026-133")

    response = api.create_housing_block(
        _block_payload(
            event["id"],
            block_start_date="2026-08-04T00:00:00.000Z",
            block_end_date="2026-08-04T00:00:00.000Z",
        ),
        DC,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW, 422)

    read_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(read_event["housing_committed_cost"], 0.00, "housing_committed_cost")


def test_validation_rooms_total_above_declared_ceiling(api):
    """`rooms_total` of 401 is a schema violation, not an interval problem.

    PRD 2.11: "Position 15 is request-schema validation, covering required
    fields, type correctness, enum membership and numeric ranges: `rooms_total`
    from 0 through 400, `max_open_claims` from 1 through 60,
    `expected_severity_index` from 0.0 through 1.0, `mandated_advance_pct` from
    0.0 through 1.0, `deadline_extension_days` from 0 through 365,
    `coverage_lines` holding 1 through 6 entries with no repeated coverage code,
    `performance_score` from 0 through 100, and `limit` and `offset` within
    their pagination bounds; the failure is `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/errors/corner_err_validation_rooms_total_above_declared_ceiling
    """
    event = _declared_event(api, "CAT-2026-134")

    response = api.create_housing_block(_block_payload(event["id"], rooms_total=401), DC)

    error = validate_error(response, ApiErrorId.ERR_VALIDATION, 422)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_WINDOW.value

    _, meta = validate_paginated(api.list_housing_blocks(DC, params={"event_id": event["id"]}))
    assert meta["total_count"] == 0


def test_verified_amount_required_on_negative_value(api):
    """A negative verified amount is refused and appends no revision.

    PRD 3.7: "**Completing** the inspection moves it `IN_PROGRESS → COMPLETED`
    and requires a `verified_damage_amount` in the payload that is present and
    not negative; omitted or negative, the answer is
    `ERR_VERIFIED_AMOUNT_REQUIRED` (HTTP 422)."

    Design: Corner/errors/corner_err_verified_amount_required_on_negative_value
    """
    validate_success(api.set_clock(CLOCK_START_UTC, CM))
    event = _declared_event(api, "CAT-2026-135")
    adjuster = _adjuster(api, "Priya Nair", desk_certified=True)
    claim = _triaged_claim(api, event["id"], "POL-1001", 8000, [_line()])
    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "DESK",
                "window_start_utc": "2026-08-05T09:00:00.000Z",
                "window_end_utc": "2026-08-05T17:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    adjuster_headers = make_adjuster_headers(adjuster["id"])
    validate_success(api.set_clock("2026-08-05T10:00:00.000Z", CM))
    validate_success(api.start_inspection(assignment["id"], adjuster_headers))

    response = api.complete_inspection(
        assignment["id"], {"verified_damage_amount": -1}, adjuster_headers
    )

    validate_error(response, ApiErrorId.ERR_VERIFIED_AMOUNT_REQUIRED, 422)

    read_assignment = validate_success(api.get_inspection_assignment(assignment["id"], DC))
    assert read_assignment["status"] == "IN_PROGRESS"
    assert read_assignment["verified_damage_amount"] is None

    rows, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "INITIAL_CASE"


def test_stale_event_version_on_loss_estimate_post(api):
    """A snapshot minted against a superseded event version is refused.

    PRD 2.8: "A request that creates a loss-estimate snapshot must carry
    `expected_event_version` holding the client's last observed `version` of the
    target `CatastropheEvent`. If that value does not equal the event's current
    `version`, the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412)
    and nothing is created."

    Design: Corner/errors/corner_err_stale_event_version_on_loss_estimate_post
    """
    created = _create_event(api, "CAT-2026-136")
    stale_version = created["version"]
    declared = validate_success(api.declare_event(created["id"], CM))
    current_version = declared["version"]
    assert current_version != stale_version

    response = api.create_loss_estimate(
        {
            "event_id": created["id"],
            "method": "EXPOSURE_BASED",
            "expected_event_version": stale_version,
        },
        CM,
    )

    validate_error(response, ApiErrorId.ERR_STALE_EVENT_VERSION, 412)

    _, meta = validate_paginated(api.list_loss_estimates(CM, params={"event_id": created["id"]}))
    assert meta["total_count"] == 0

    read_event = validate_success(api.get_event(created["id"], CM))
    assert_money_equals(read_event["gross_loss_estimate"], 0.00, "gross_loss_estimate")
    assert read_event["version"] == current_version


def test_loss_estimate_stale_blocks_surge_activation(api):
    """A triage that stales the only snapshot blocks surge activation.

    PRD 3.1: "And at least one loss-estimate snapshot on the event must be
    non-stale, or the request fails with `ERR_LOSS_ESTIMATE_STALE`; an event
    with no snapshots at all fails this check too, since zero rows satisfy the
    requirement vacuously in the wrong direction."
    PRD 3.8: "Its `stale` flag is a computed property re-evaluated on every
    read: it reads true exactly when a ledger entry exists on the event whose
    `sequence_no` is greater than the snapshot's recorded high-water mark."

    Design: Corner/errors/corner_err_loss_estimate_stale_blocks_surge_activation
    """
    event = _declared_event(api, "CAT-2026-137")
    _active_block(api, event["id"])
    snapshot = _snapshot(api, event["id"])
    _triaged_claim(api, event["id"], "POL-1001", 8000, [_line()])

    response = api.activate_surge(event["id"], CM)

    validate_error(response, ApiErrorId.ERR_LOSS_ESTIMATE_STALE, 409)

    read_event = validate_success(api.get_event(event["id"], CM))
    assert read_event["status"] == "DECLARED"

    read_snapshot = validate_success(api.get_loss_estimate(snapshot["id"], CM))
    assert read_snapshot["stale"] is True
    assert read_snapshot["input_reserve_sequence_high_water"] == 0


def test_untriaged_claims_remain_blocks_demobilize(api):
    """One claim still in INTAKE blocks the whole event's demobilization.

    PRD 3.1: "The event must be in `SURGE_ACTIVE`
    (`ERR_EVENT_NOT_SURGE_ACTIVE`); the event's `moratorium_active` flag must be
    false (`ERR_MORATORIUM_ACTIVE`), because a carrier may not wind down its
    catastrophe operation while the regulator's cancellation moratorium is still
    in force; and no claim on the event may sit in `INTAKE` or `TRIAGED`
    (`ERR_UNTRIAGED_CLAIMS_REMAIN`), because those are files nobody has
    scheduled work on."

    Design: Corner/errors/corner_err_untriaged_claims_remain_blocks_demobilize
    """
    event = _declared_event(api, "CAT-2026-138")
    _active_block(api, event["id"])
    _snapshot(api, event["id"])
    validate_success(api.activate_surge(event["id"], CM))
    claim = _claim(api, event["id"], "POL-1001", 8000, [_line()])
    assert claim["handling_status"] == "INTAKE"

    response = api.demobilize_event(event["id"], CM)

    validate_error(response, ApiErrorId.ERR_UNTRIAGED_CLAIMS_REMAIN, 409)

    read_event = validate_success(api.get_event(event["id"], CM))
    assert read_event["status"] == "SURGE_ACTIVE"
    assert validate_success(api.get_claim(claim["id"], CE))["handling_status"] == "INTAKE"


def test_claims_still_open_blocks_event_close(api):
    """A claim on the inspection track blocks the full closure path.

    PRD 3.1: "The full path closes the event `DEMOBILIZING → CLOSED` and demands
    four things: the event is in `DEMOBILIZING` (`ERR_EVENT_NOT_DEMOBILIZING`);
    no deployment on the event remains in `REQUESTED`, `CONFIRMED` or `ON_SITE`
    (`ERR_DEPLOYMENTS_STILL_OPEN`); every claim on the event sits in `CLOSED` or
    `TRANSFERRED` (`ERR_CLAIMS_STILL_OPEN`); and every file-transfer batch on
    the event has reached `ACCEPTED` (`ERR_TRANSFER_BATCH_UNACCEPTED`)."
    PRD 3.1: "Landing it releases every housing block on the event that is
    `PENDING`, `ACTIVE` or `EXHAUSTED`, moving each to `RELEASED` — the
    deployments-still-open precondition guarantees each such block has zero
    occupied rooms — returns every vendor firm whose activation points at this
    event to `NETWORK_INACTIVE` and clears that firm's `activated_for_event_id`,
    and sets `posture` to `FROZEN`."

    Design: Corner/errors/corner_err_claims_still_open_blocks_event_close
    """
    event = _declared_event(api, "CAT-2026-139")
    block = _active_block(api, event["id"])
    adjuster = _adjuster(api, "Priya Nair", desk_certified=True)
    claim = _triaged_claim(api, event["id"], "POL-1001", 8000, [_line()])
    _snapshot(api, event["id"])
    validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "DESK",
                "window_start_utc": "2026-08-05T09:00:00.000Z",
                "window_end_utc": "2026-08-05T17:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    validate_success(api.activate_surge(event["id"], CM))
    validate_success(api.demobilize_event(event["id"], CM))

    response = api.close_event(event["id"], CM)

    validate_error(response, ApiErrorId.ERR_CLAIMS_STILL_OPEN, 409)

    read_event = validate_success(api.get_event(event["id"], CM))
    assert read_event["status"] == "DEMOBILIZING"
    assert validate_success(api.get_housing_block(block["id"], DC))["status"] == "ACTIVE"


def test_batch_empty_on_submit_of_zero_claim_batch(api):
    """A batch with no members cannot be submitted.

    PRD 3.9: "The batch must be `OPEN` (`ERR_BATCH_NOT_OPEN`); the parent event
    must be in `DEMOBILIZING` (`ERR_EVENT_NOT_DEMOBILIZING`), since file
    transfer is a wind-down activity; `claim_count` must be at least 1, so an
    empty batch is refused with `ERR_BATCH_EMPTY` (HTTP 422); and
    `blocking_claim_count` must be exactly zero, otherwise
    `ERR_BATCH_HAS_BLOCKING_CLAIMS` (HTTP 409)."
    PRD 3.9: "A new batch is `OPEN` with `claim_count` and
    `blocking_claim_count` of zero and `rejection_reason` null; batches may be
    listed filtered by `event_id` and `status`."

    Design: Corner/errors/corner_err_batch_empty_on_submit_of_zero_claim_batch
    """
    event = _declared_event(api, "CAT-2026-140")
    _active_block(api, event["id"])
    _snapshot(api, event["id"])
    validate_success(api.activate_surge(event["id"], CM))
    validate_success(api.demobilize_event(event["id"], CM))
    batch = validate_success(
        api.create_batch({"event_id": event["id"], "target_unit": "PROPERTY-EAST"}, CE), 201
    )

    response = api.submit_batch(batch["id"], CE)

    validate_error(response, ApiErrorId.ERR_BATCH_EMPTY, 422)

    read_batch = validate_success(api.get_batch(batch["id"], CE))
    assert read_batch["status"] == "OPEN"
    assert read_batch["claim_count"] == 0
    assert read_batch["submitted_at_utc"] is None


def test_housing_still_occupied_on_release(api):
    """A block holding one drawn room cannot be released.

    PRD 3.4: "In every case `rooms_occupied` must be exactly zero, otherwise the
    release is refused with `ERR_HOUSING_STILL_OCCUPIED`."

    Design: Corner/errors/corner_err_housing_still_occupied_on_release
    """
    event = _declared_event(api, "CAT-2026-141")
    block = _active_block(api, event["id"])
    adjuster = _adjuster(api, "Marcus Hale")
    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-08-05T00:00:00.000Z",
                "window_end_utc": "2026-08-08T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 1,
            },
            DC,
        ),
        201,
    )
    validate_success(api.confirm_deployment(deployment["id"], DC))

    response = api.release_housing_block(block["id"], DC)

    validate_error(response, ApiErrorId.ERR_HOUSING_STILL_OCCUPIED, 409)

    read_block = validate_success(api.get_housing_block(block["id"], DC))
    assert read_block["status"] == "ACTIVE"
    assert read_block["rooms_occupied"] == 1
    assert read_block["rooms_available"] == 9

    read_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(read_event["housing_committed_cost"], 10000.00, "housing_committed_cost")


def test_assignments_in_flight_blocks_deployment_cancel(api):
    """A deployment funding an in-progress inspection cannot be cancelled.

    PRD 3.5: "From `CONFIRMED` it is the compensating action for the
    room-conservation invariant, and it carries one extra precondition — no
    inspection assignment funded by this deployment may be in `IN_PROGRESS` or
    `COMPLETED`, otherwise `ERR_ASSIGNMENTS_IN_FLIGHT`."

    Design: Corner/errors/corner_err_assignments_in_flight_blocks_deployment_cancel
    """
    validate_success(api.set_clock(CLOCK_START_UTC, CM))
    event = _declared_event(api, "CAT-2026-142")
    block = _active_block(api, event["id"])
    adjuster = _adjuster(api, "Marcus Hale")
    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-08-05T00:00:00.000Z",
                "window_end_utc": "2026-08-08T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 1,
            },
            DC,
        ),
        201,
    )
    validate_success(api.confirm_deployment(deployment["id"], DC))
    claim = _triaged_claim(
        api,
        event["id"],
        "POL-2002",
        60000,
        [_line(limit=400000, deductible=2000, estimated=90000)],
    )
    assert claim["inspection_mode"] == "FIELD"
    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "FIELD",
                "window_start_utc": "2026-08-05T09:00:00.000Z",
                "window_end_utc": "2026-08-05T17:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "deployment_id": deployment["id"],
            },
            DC,
        ),
        201,
    )
    validate_success(api.set_clock("2026-08-05T10:00:00.000Z", CM))
    validate_success(api.start_inspection(assignment["id"], make_adjuster_headers(adjuster["id"])))

    response = api.cancel_deployment(deployment["id"], DC)

    validate_error(response, ApiErrorId.ERR_ASSIGNMENTS_IN_FLIGHT, 409)

    assert validate_success(api.get_deployment(deployment["id"], DC))["status"] == "CONFIRMED"
    assert validate_success(api.get_housing_block(block["id"], DC))["rooms_occupied"] == 1
    read_assignment = validate_success(api.get_inspection_assignment(assignment["id"], DC))
    assert read_assignment["status"] == "IN_PROGRESS"


def test_no_eligible_adjuster_on_empty_selector_pool(api):
    """With the only adjuster parked, the selector has nobody to choose.

    PRD 3.5: "Its eligibility filter admits an adjuster only when all of the
    following hold: their `deployment_status` is `AVAILABLE`; their
    `credential_status` is `VALID`, `EXPIRING` or `WAIVED`; either the event's
    `jurisdiction_state` appears in their `licensed_states` or their
    `credential_status` is `WAIVED`; their `open_assignment_count` is strictly
    below their `max_open_claims`; the requested role is not `DESK` unless
    `desk_certified` is true; the requested role is not `AERIAL` unless
    `aerial_certified` is true; and no deployment of theirs in `CONFIRMED`,
    `ON_SITE` or `DEMOBILIZED` violates the twelve-hour rest separation
    described below."
    PRD 3.5: "If the candidate set is empty, nothing is created and the request
    is rejected with `ERR_NO_ELIGIBLE_ADJUSTER` (HTTP 409)."

    Design: Corner/errors/corner_err_no_eligible_adjuster_on_empty_selector_pool
    """
    event = _declared_event(api, "CAT-2026-143")
    adjuster = _adjuster(api, "Priya Nair", desk_certified=True)
    validate_success(api.set_adjuster_unavailable(adjuster["id"], DC))

    response = api.create_deployment(
        {
            "event_id": event["id"],
            "role_type": "DESK",
            "window_start_utc": "2026-08-05T00:00:00.000Z",
            "window_end_utc": "2026-08-08T00:00:00.000Z",
            "rooms_reserved": 0,
        },
        DC,
    )

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_ADJUSTER, 409)

    _, meta = validate_paginated(api.list_deployments(DC, params={"event_id": event["id"]}))
    assert meta["total_count"] == 0
    assert validate_success(api.get_adjuster(adjuster["id"], DC))["deployment_status"] == "UNAVAILABLE"


def test_no_eligible_vendor_on_empty_selector_pool(api):
    """A firm that was never activated is invisible to the vendor selector.

    PRD 3.9: "The selector's eligibility filter admits a firm only when its
    `status` is `ACTIVATED` — `NETWORK_INACTIVE`, `CAPACITY_HOLD` and
    `SUSPENDED` firms are excluded even when they have spare capacity — and its
    `activated_for_event_id` matches the claim's event, and the claim's
    `loss_state` appears in the firm's `service_states`, and its
    `open_job_count` is strictly below its `max_concurrent_jobs`, and its
    `vendor_type` equals the requested `required_vendor_type`."
    PRD 3.9: "An empty candidate pool is `ERR_NO_ELIGIBLE_VENDOR` (HTTP 409) and
    nothing is created."

    Design: Corner/errors/corner_err_no_eligible_vendor_on_empty_selector_pool
    """
    event = _declared_event(api, "CAT-2026-144")
    firm = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Gulf Mitigation Co",
                "vendor_type": "MITIGATION",
                "service_states": ["FL"],
                "max_concurrent_jobs": 5,
                "performance_score": 90.00,
            },
            make_vendor_coordinator_headers("vc_seed"),
        ),
        201,
    )
    claim = _triaged_claim(api, event["id"], "POL-1001", 8000, [_line()])

    response = api.create_vendor_assignment(
        {
            "claim_id": claim["id"],
            "scope_amount": 5000,
            "required_vendor_type": "MITIGATION",
        },
        CE,
    )

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_VENDOR, 409)

    _, meta = validate_paginated(api.list_vendor_assignments(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 0

    read_firm = validate_success(api.get_vendor_firm(firm["id"], make_vendor_coordinator_headers(firm["id"])))
    assert read_firm["status"] == "NETWORK_INACTIVE"
    assert read_firm["open_job_count"] == 0


def test_event_posture_frozen_blocks_deployment_create(api):
    """A strain total of exactly 8 freezes the event and blocks a new deployment.

    PRD 2.9: "The strain total is the count of unassigned severe claims plus the
    stale contribution plus the moratorium contribution, and it is an exact
    integer that is never rounded."
    PRD 2.9: "**Step three bands the strain total.** A strain of 8 or more bands
    as `FROZEN`; a strain of 3 or more but below 8 bands as `RESTRICTED`; a
    strain below 3 bands as `OPEN`."
    PRD 2.9: "Seven operations are refused with `ERR_EVENT_POSTURE_FROZEN` (HTTP
    409) when the parent event's posture is `FROZEN`: triaging a claim,
    appending a manual reserve entry to a claim, requesting a deployment,
    confirming a deployment, scheduling an inspection assignment, issuing an
    advance payment, and dispatching a vendor assignment."

    Design: Corner/errors/corner_err_event_posture_frozen_blocks_deployment_create
    """
    event = _declared_event(api, "CAT-2026-145")
    adjuster = _adjuster(api, "Marcus Hale")
    _snapshot(api, event["id"])
    claim = _triaged_claim(
        api,
        event["id"],
        "POL-3003",
        200000,
        [_line(limit=200000, deductible=2000, estimated=250000)],
    )
    assert claim["triage_tier"] == "CAT_SEVERE"
    assert_money_equals(claim["severity_score"], 100.00, "severity_score")
    bulletin = validate_success(
        api.create_bulletin(
            {
                "event_id": event["id"],
                "bulletin_number": "FL-2026-09",
                "jurisdiction_state": "FL",
                "bulletin_type": "CANCELLATION_MORATORIUM",
                "effective_from": "2026-07-30T00:00:00.000Z",
                "effective_to": "2026-09-01T00:00:00.000Z",
            },
            CO,
        ),
        201,
    )
    validate_success(api.activate_bulletin(bulletin["id"], CO))

    response = api.create_deployment(
        {
            "event_id": event["id"],
            "role_type": "FIELD",
            "window_start_utc": "2026-08-05T00:00:00.000Z",
            "window_end_utc": "2026-08-08T00:00:00.000Z",
            "adjuster_id": adjuster["id"],
            "rooms_reserved": 1,
        },
        DC,
    )

    validate_error(response, ApiErrorId.ERR_EVENT_POSTURE_FROZEN, 409)

    read_event = validate_success(api.get_event(event["id"], CM))
    assert read_event["status"] == "DECLARED"
    assert read_event["posture"] == "FROZEN"
    assert read_event["moratorium_active"] is True

    _, meta = validate_paginated(api.list_deployments(DC, params={"event_id": event["id"]}))
    assert meta["total_count"] == 0


def test_no_license_waiver_in_force_on_expired_credential(api):
    """An expired licence cannot be waived without an effective waiver bulletin.

    PRD 3.3: "Three conditions guard it — the adjuster's `credential_status`
    must be `EXPIRED` (`ERR_CREDENTIAL_NOT_EXPIRED`); a bulletin of type
    `ADJUSTER_LICENSE_WAIVER` must be `EFFECTIVE`, must bind the named event's
    `jurisdiction_state`, and must cover the current instant with
    `effective_from` inclusive and `effective_to` exclusive
    (`ERR_NO_LICENSE_WAIVER_IN_FORCE`); and the adjuster's `employment_type`
    must be `INDEPENDENT`, since a staff adjuster's licence is the carrier's own
    problem (`ERR_WAIVER_NOT_ELIGIBLE`)."
    PRD 3.3: "Once the clock reaches or passes `license_expiry_utc`, they move
    `EXPIRING → EXPIRED`, their score is recomputed, and every inspection
    assignment of theirs still in `SCHEDULED` is cancelled."

    Design: Corner/errors/corner_err_no_license_waiver_in_force_on_expired_credential
    """
    validate_success(api.set_clock(CLOCK_START_UTC, CM))
    event = _declared_event(api, "CAT-2026-146")
    adjuster = _adjuster(
        api,
        "Dana Ruiz",
        employment_type="INDEPENDENT",
        license_expiry_utc="2026-08-10T00:00:00.000Z",
        max_open_claims=3,
        daily_rate=600,
        per_diem_rate=120,
        desk_certified=True,
    )
    validate_success(api.set_clock("2026-08-11T00:00:00.000Z", CM))

    response = api.apply_license_waiver(adjuster["id"], {"event_id": event["id"]}, CO)

    validate_error(response, ApiErrorId.ERR_NO_LICENSE_WAIVER_IN_FORCE, 409)

    read_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert read_adjuster["credential_status"] == "EXPIRED"

    _, meta = validate_paginated(api.list_bulletins(CO, params={"event_id": event["id"]}))
    assert meta["total_count"] == 0


def test_advance_mandate_floor_blocks_void(api):
    """Voiding the only advance would breach the regulator's advance floor.

    PRD 3.8: "Separately, find the governing advance mandate: among the
    bulletins on the claim's event with `bulletin_type` of
    `ADVANCE_PAYMENT_MANDATE`, `status` of `EFFECTIVE`, and a binding window
    containing the current instant with `effective_from` inclusive and
    `effective_to` exclusive, take the one with the greatest
    `mandated_advance_pct`, breaking ties by the earliest `created_at`; the
    mandate floor is the claim's `reported_loss_amount` multiplied by that
    percentage and rounded to 2 decimal places, or exactly 0.00 when no such
    bulletin exists."
    PRD 3.8: "Multiply the line-derived cap by the tier multiplier for the
    claim's `triage_tier` — 1.00 for `CAT_SEVERE`, 0.85 for `COMPLEX`, 0.60 for
    `STANDARD`, 0.40 for `FAST_TRACK` — and round to 2 decimal places."
    PRD 3.8: "The claim's `advance_cap` is the greater of that tiered figure and
    the mandate floor."
    PRD 3.8: "Three preconditions guard it: the advance's `status` must be
    `ISSUED` (`ERR_ADVANCE_NOT_ISSUED`); the claim's `payment_status` must not be
    `SETTLED` (`ERR_CLAIM_ALREADY_SETTLED`); and the void must not drop the
    claim's `advance_paid_total` below the mandated floor of any `EFFECTIVE`
    `ADVANCE_PAYMENT_MANDATE` bulletin covering the current instant, so the void
    is permitted either when no such mandate is in force or when the remaining
    advanced total still satisfies the floor (`ERR_ADVANCE_MANDATE_FLOOR`, HTTP
    409)."

    Design: Corner/errors/corner_err_advance_mandate_floor_blocks_void
    """
    validate_success(api.set_clock(CLOCK_START_UTC, CM))
    event = _declared_event(api, "CAT-2026-147")
    bulletin = validate_success(
        api.create_bulletin(
            {
                "event_id": event["id"],
                "bulletin_number": "FL-2026-11",
                "jurisdiction_state": "FL",
                "bulletin_type": "ADVANCE_PAYMENT_MANDATE",
                "effective_from": "2026-07-30T00:00:00.000Z",
                "effective_to": "2026-09-01T00:00:00.000Z",
                "mandated_advance_pct": 0.0500,
            },
            CO,
        ),
        201,
    )
    validate_success(api.activate_bulletin(bulletin["id"], CO))
    claim = _triaged_claim(api, event["id"], "POL-1001", 8000, [_line()])
    assert claim["triage_tier"] == "FAST_TRACK"
    advance = validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 600, "basis": "STRUCTURE_PARTIAL"},
            CE,
        ),
        201,
    )
    assert advance["status"] == "ISSUED"
    assert_money_equals(advance["amount"], 600.00, "amount")

    response = api.void_advance_payment(advance["id"], {"void_reason": "Issued in error"}, CE)

    validate_error(response, ApiErrorId.ERR_ADVANCE_MANDATE_FLOOR, 409)

    read_advance = validate_success(api.get_advance_payment(advance["id"], CE))
    assert read_advance["status"] == "ISSUED"
    assert_money_equals(read_advance["amount"], 600.00, "amount")

    read_claim = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(read_claim["advance_paid_total"], 600.00, "advance_paid_total")
    assert_money_equals(read_claim["advance_cap"], 600.00, "advance_cap")
    assert_money_equals(read_claim["paid_amount"], 600.00, "paid_amount")
    assert_money_equals(read_claim["case_reserve"], 1400.00, "case_reserve")

    _, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 2


def test_reserve_would_go_negative_on_manual_revision(api):
    """A revision that would push the case reserve below zero is refused.

    PRD 3.8: "One fiscal guard applies: the claim's `case_reserve` plus the
    submitted `delta_case_reserve`, rounded to 2 decimal places, must be at least
    0.00, otherwise the append is refused with `ERR_RESERVE_WOULD_GO_NEGATIVE`
    (HTTP 422)."

    Design: Corner/errors/corner_err_reserve_would_go_negative_on_manual_revision
    """
    event = _declared_event(api, "CAT-2026-148")
    claim = _triaged_claim(api, event["id"], "POL-1001", 8000, [_line()])
    assert_money_equals(claim["case_reserve"], 2000.00, "case_reserve")
    version_before = validate_success(api.get_claim(claim["id"], CE))["version"]

    response = api.create_reserve_entry(
        claim["id"],
        {
            "expected_claim_version": version_before,
            "entry_type": "REVISION",
            "delta_case_reserve": -2500,
            "delta_paid": 0,
        },
        CE,
    )

    validate_error(response, ApiErrorId.ERR_RESERVE_WOULD_GO_NEGATIVE, 422)

    rows, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "INITIAL_CASE"

    read_claim = validate_success(api.get_claim(claim["id"], CE))
    assert_money_equals(read_claim["case_reserve"], 2000.00, "case_reserve")
    assert read_claim["version"] == version_before

    read_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(read_event["case_reserve_total"], 2000.00, "case_reserve_total")
    assert_money_equals(read_event["incurred_total"], 2000.00, "incurred_total")


def test_not_assigned_adjuster_on_foreign_start(api):
    """Only the assigned adjuster may start the inspection.

    PRD 3.7: "The assigned `Adjuster` — and only they, since `X-User-ID` must
    equal the assignment's `adjuster_id` or the call is refused with
    `ERR_NOT_ASSIGNED_ADJUSTER` — drives the assignment from there."
    PRD 3.7: "**Starting** the inspection moves it `SCHEDULED → IN_PROGRESS`;
    the assignment must be `SCHEDULED` (`ERR_ASSIGNMENT_NOT_SCHEDULED`), the
    clock must have reached or passed `window_start_utc`
    (`ERR_ASSIGNMENT_WINDOW_NOT_STARTED`), and the adjuster's
    `credential_status` must be `VALID`, `EXPIRING` or `WAIVED`
    (`ERR_ADJUSTER_CREDENTIAL_INVALID`) — a licence that lapsed between
    scheduling and arrival stops the work at the door."

    Design: Corner/errors/corner_err_not_assigned_adjuster_on_foreign_start
    """
    validate_success(api.set_clock(CLOCK_START_UTC, CM))
    event = _declared_event(api, "CAT-2026-149")
    adjuster_a = _adjuster(api, "Priya Nair", desk_certified=True)
    adjuster_b = _adjuster(api, "Owen Blake", desk_certified=True)
    claim = _triaged_claim(api, event["id"], "POL-1001", 8000, [_line()])
    assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim["id"],
                "mode": "DESK",
                "window_start_utc": "2026-08-05T09:00:00.000Z",
                "window_end_utc": "2026-08-05T17:00:00.000Z",
                "adjuster_id": adjuster_a["id"],
            },
            DC,
        ),
        201,
    )
    validate_success(api.set_clock("2026-08-05T10:00:00.000Z", CM))

    foreign = api.start_inspection(assignment["id"], make_adjuster_headers(adjuster_b["id"]))

    validate_error(foreign, ApiErrorId.ERR_NOT_ASSIGNED_ADJUSTER, 403)
    assert validate_success(api.get_inspection_assignment(assignment["id"], DC))["status"] == "SCHEDULED"

    owned = api.start_inspection(assignment["id"], make_adjuster_headers(adjuster_a["id"]))

    started = validate_success(owned, 200)
    assert started["status"] == "IN_PROGRESS"
    assert validate_success(api.get_adjuster(adjuster_b["id"], DC))["open_assignment_count"] == 0

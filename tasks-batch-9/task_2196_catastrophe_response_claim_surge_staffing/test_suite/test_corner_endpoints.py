"""Endpoint-surface corner tests: happy-path shapes, roll-ups and bulk effects.

Each test drives one endpoint (or one endpoint pair) end to end through the
public HTTP surface and pins the response body the PRD promises: lifecycle
values, computed roll-ups, list envelopes and the cross-entity side effects a
single call is required to land.
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


def _active_block(api, event_id, **overrides):
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
    block = validate_success(api.create_housing_block(payload, DC), 201)
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


def _line(code="DWELLING", limit=200000, deductible=1000, estimated=6000):
    return {
        "coverage_code": code,
        "limit_amount": limit,
        "deductible_amount": deductible,
        "estimated_damage_amount": estimated,
    }


def test_create_event_returns_monitoring_open_version_one(api):
    """Registering a catastrophe event returns the pinned initial state.

    PRD 3.1: "A newly registered event begins with `status` of `MONITORING`, a
    `posture` of `OPEN`, a `version` of 1, and a `declared_at_utc` of null."

    Design: Corner/endpoints/corner_ep_create_event_returns_monitoring_open_version_one
    """
    response = api.create_event(
        _event_payload("CAT-2026-114"),
        CM,
    )

    event = validate_success(response, 201)
    assert event["cat_code"] == "CAT-2026-114"
    assert event["peril_type"] == "HURRICANE"
    assert event["jurisdiction_state"] == "FL"
    assert event["status"] == "MONITORING"
    assert event["posture"] == "OPEN"
    assert event["version"] == 1
    assert event["declared_at_utc"] is None


def test_read_event_returns_zeroed_rollups(api):
    """A brand-new event's computed roll-up wall reads all zeroes.

    PRD 3.1: "`case_reserve_total` and `paid_total` are the sums of the
    case-reserve and paid movements of every ledger entry belonging to the
    event, each to 2 decimal places, and `incurred_total` is their sum — the
    conserved quantity of §2.10."
    PRD 3.1: "`gross_loss_estimate` mirrors the `gross_estimate` of the event's
    latest loss-estimate snapshot — the one with the greatest
    `computed_at_utc`, with ties broken in favour of the earliest `created_at`
    — and reads 0.00 when the event has no snapshot."
    PRD 3.1: "`moratorium_active` is true exactly when at least one bulletin on
    the event has `bulletin_type` of `CANCELLATION_MORATORIUM`, `status` of
    `EFFECTIVE`, and a binding window that contains the current instant with
    `effective_from` inclusive and `effective_to` exclusive."

    Design: Corner/endpoints/corner_ep_read_event_returns_zeroed_rollups
    """
    event = _create_event(api, "CAT-2026-115", peril_type="HAIL", jurisdiction_state="TX")

    read = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(read["case_reserve_total"], 0.00, "case_reserve_total")
    assert_money_equals(read["paid_total"], 0.00, "paid_total")
    assert_money_equals(read["incurred_total"], 0.00, "incurred_total")
    assert_money_equals(read["housing_committed_cost"], 0.00, "housing_committed_cost")
    assert_money_equals(read["deployment_settled_cost"], 0.00, "deployment_settled_cost")
    assert_money_equals(read["gross_loss_estimate"], 0.00, "gross_loss_estimate")
    assert read["open_claim_count"] == 0
    assert read["surge_adjuster_count"] == 0
    assert read["moratorium_active"] is False
    assert read["posture"] == "OPEN"
    assert read["version"] == 1


def test_list_events_pagination_envelope_and_created_at_order(api):
    """The event list pages in creation order with a fully populated meta.

    PRD 2.3: "Unless a specific endpoint states otherwise, list results are
    ordered by `created_at` ascending."
    PRD 2.3: "List responses populate `limit`, `offset`, `total_count` and
    `has_more` inside `meta`, where `total_count` is the number of rows
    matching the filters before pagination is applied and `has_more` is true
    when rows remain beyond the current page."

    Design: Corner/endpoints/corner_ep_list_events_pagination_envelope_and_created_at_order
    """
    first = _create_event(api, "CAT-2026-201")
    second = _create_event(api, "CAT-2026-202", peril_type="HAIL")
    _create_event(api, "CAT-2026-203", peril_type="FLOOD")

    response = api.list_events(CM, params={"limit": 2, "offset": 0})

    rows, meta = validate_paginated(response)
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert len(rows) == 2
    assert rows[0]["id"] == first["id"]
    assert rows[0]["cat_code"] == "CAT-2026-201"
    assert rows[1]["id"] == second["id"]
    assert rows[1]["cat_code"] == "CAT-2026-202"


def test_open_housing_block_activates_and_commits_cost(api):
    """Opening a room block activates it and moves it into the committed sum.

    PRD 3.4: "From that span the system computes `block_night_count`, the
    number of whole days from `block_start_date` up to but not including
    `block_end_date`."
    PRD 3.4: "A newly held block is `PENDING`, with `rooms_occupied` of zero and
    `rooms_available` equal to `rooms_total`."
    PRD 3.4: "Opening a block moves it `PENDING → ACTIVE` and is refused with
    `ERR_HOUSING_NOT_PENDING` from any other status."
    PRD 3.1: "`housing_committed_cost` sums, over every housing block on the
    event whose `status` is `PENDING`, `ACTIVE` or `EXHAUSTED`, that block's
    `nightly_rate` multiplied by its `rooms_total` multiplied by its
    `block_night_count`, to 2 decimal places; released blocks drop out of the
    sum entirely."

    Design: Corner/endpoints/corner_ep_open_housing_block_activates_and_commits_cost
    """
    event = _declared_event(api, "CAT-2026-116")
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Gulfside Inn",
                "city": "Tampa",
                "rooms_total": 10,
                "nightly_rate": 200,
                "block_start_date": "2026-08-04T00:00:00.000Z",
                "block_end_date": "2026-08-09T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    assert block["status"] == "PENDING"

    opened = validate_success(api.open_housing_block(block["id"], DC))

    assert opened["status"] == "ACTIVE"
    assert opened["block_night_count"] == 5
    assert opened["rooms_occupied"] == 0
    assert opened["rooms_available"] == 10

    read_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(read_event["housing_committed_cost"], 10000.00, "housing_committed_cost")
    assert read_event["posture"] == "OPEN"


def test_adjuster_set_available_restores_pool_and_rescores(api):
    """Returning a parked adjuster to the pool restores AVAILABLE and rescores.

    PRD 3.3: "Separately, a coordinator may park an available adjuster out of
    the pool, moving them `AVAILABLE → UNAVAILABLE` — attempted on an adjuster
    who is not `AVAILABLE`, this is refused with `ERR_ADJUSTER_NOT_AVAILABLE` —
    and may return them `UNAVAILABLE → AVAILABLE`, which recomputes the score
    and is refused with `ERR_ADJUSTER_NOT_UNAVAILABLE` when the adjuster was
    not parked in the first place."
    PRD 3.3: "The **availability term** starts from the adjuster's
    `open_assignment_count` — the number of their inspection assignments
    currently in `SCHEDULED` or `IN_PROGRESS` — divided by their
    `max_open_claims`; that load ratio is capped at 1, subtracted from 1, and
    multiplied by 100, so an idle adjuster contributes 100 points and a fully
    loaded one contributes zero."

    Design: Corner/endpoints/corner_ep_adjuster_set_available_restores_pool_and_rescores
    """
    adjuster = _adjuster(api, "Dana Reyes")
    parked = validate_success(api.set_adjuster_unavailable(adjuster["id"], DC))
    assert parked["deployment_status"] == "UNAVAILABLE"

    restored = validate_success(api.set_adjuster_available(adjuster["id"], DC))

    assert restored["deployment_status"] == "AVAILABLE"
    assert restored["credential_status"] == "VALID"
    assert restored["open_assignment_count"] == 0
    assert_money_equals(restored["surge_capacity_score"], 100.00, "surge_capacity_score")


def test_confirm_deployment_draws_rooms_and_stamps_provisional_cost(api):
    """Confirmation prices the deployment, draws the room and deploys the adjuster.

    PRD 3.5: "Confirmation then does five things at once. It stamps
    `provisional_cost` and `surge_premium_tier` from the provisional variant of
    the cost rule. It adds the deployment's `rooms_reserved` to the block's
    `rooms_occupied` and recomputes `rooms_available`, taking the block
    `ACTIVE → EXHAUSTED` if availability lands on zero. It moves the adjuster
    `AVAILABLE → DEPLOYED` and recomputes their surge-capacity score. And it
    recomputes the parent event's `surge_adjuster_count` and posture."
    PRD 3.5: "The **provisional** variant, stamped into `provisional_cost` at
    confirmation, uses the deployment's full requested `window_end_utc` as the
    settle-end instant and treats per-diem eligibility as 1 unconditionally, so
    an independent adjuster with a hotel room is charged per-diem *and*
    housing."
    PRD 3.5: "anything below 5000.00 is `TIER_NONE` at zero"
    PRD 3.1: "`surge_adjuster_count` is the number of deployments on the event
    whose status is `CONFIRMED` or `ON_SITE`."

    Design: Corner/endpoints/corner_ep_confirm_deployment_draws_rooms_and_stamps_provisional_cost
    """
    event = _declared_event(api, "CAT-2026-117")
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
    assert deployment["status"] == "REQUESTED"

    confirmed = validate_success(api.confirm_deployment(deployment["id"], DC))

    assert confirmed["status"] == "CONFIRMED"
    assert_money_equals(confirmed["provisional_cost"], 2400.00, "provisional_cost")
    assert confirmed["surge_premium_tier"] == "TIER_NONE"
    assert_money_equals(confirmed["final_settled_cost"], 0.00, "final_settled_cost")
    assert confirmed["selection_reason"] == "EXPLICIT_ADJUSTER"

    read_block = validate_success(api.get_housing_block(block["id"], DC))
    assert read_block["rooms_occupied"] == 1
    assert read_block["rooms_available"] == 9
    assert read_block["status"] == "ACTIVE"

    read_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert read_adjuster["deployment_status"] == "DEPLOYED"

    read_event = validate_success(api.get_event(event["id"], CM))
    assert read_event["surge_adjuster_count"] == 1


def test_demobilize_event_bulk_cancels_only_requested_deployments(api):
    """Event demobilization sweeps REQUESTED deployments and leaves rooms alone.

    PRD 3.1: "When it lands, every deployment on the event still in `REQUESTED`
    is cancelled — those deployments never drew rooms, so no block's
    `rooms_occupied` changes — and posture is recomputed with a floor of
    `RESTRICTED`, meaning a demobilizing event can never read `OPEN` again."

    Design: Corner/endpoints/corner_ep_demobilize_event_bulk_cancels_only_requested_deployments
    """
    event = _declared_event(api, "CAT-2026-118")
    block = _active_block(api, event["id"])
    _snapshot(api, event["id"])
    validate_success(api.activate_surge(event["id"], CM))
    adjuster = _adjuster(api, "Marcus Hale", desk_certified=True)

    dep1 = validate_success(
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
    validate_success(api.confirm_deployment(dep1["id"], DC))
    dep2 = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-08-20T00:00:00.000Z",
                "window_end_utc": "2026-08-23T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 2,
            },
            DC,
        ),
        201,
    )
    dep3 = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "DESK",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-03T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "rooms_reserved": 0,
            },
            DC,
        ),
        201,
    )

    demobilized = validate_success(api.demobilize_event(event["id"], CM))

    assert demobilized["status"] == "DEMOBILIZING"
    assert demobilized["posture"] == "RESTRICTED"
    assert validate_success(api.get_deployment(dep2["id"], DC))["status"] == "CANCELLED"
    assert validate_success(api.get_deployment(dep3["id"], DC))["status"] == "CANCELLED"
    assert validate_success(api.get_deployment(dep1["id"], DC))["status"] == "CONFIRMED"

    _, meta = validate_paginated(
        api.list_deployments(DC, params={"event_id": event["id"], "status": "REQUESTED"})
    )
    assert meta["total_count"] == 0

    read_block = validate_success(api.get_housing_block(block["id"], DC))
    assert read_block["rooms_occupied"] == 1
    assert read_block["rooms_available"] == 9


def test_assign_cat_code_links_claim_to_event(api):
    """Cat coding attaches an intake claim to a declared event and nothing else.

    PRD 3.6: "**Cat coding** attaches an intake claim to a declared or
    surge-active catastrophe event by supplying that event's `event_id`; the
    claim's own `event_id` is set, and the event's `open_claim_count` and
    posture are recomputed."
    PRD 3.6: "A new claim is `INTAKE` on the handling axis and `NONE` on the
    payment axis, with `reported_at_utc` stamped at the current logical-clock
    instant, `severity_score` of 0.00, `reopen_count` of 0, and `triage_tier`,
    `inspection_mode`, `deadline_utc` and `verified_damage_amount` all null."
    PRD 3.1: "`open_claim_count` is the number of claims on the event whose
    `handling_status` is neither `CLOSED` nor `TRANSFERRED`."

    Design: Corner/endpoints/corner_ep_assign_cat_code_links_claim_to_event
    """
    event = _declared_event(api, "CAT-2026-122")
    claim = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-1001",
                "loss_state": "FL",
                "loss_date_utc": "2026-07-30T00:00:00.000Z",
                "reported_loss_amount": 8000,
                "coverage_lines": [_line()],
            },
            CE,
        ),
        201,
    )
    assert claim["event_id"] is None

    coded = validate_success(api.assign_cat_code(claim["id"], {"event_id": event["id"]}, CE))

    assert coded["event_id"] == event["id"]
    assert coded["handling_status"] == "INTAKE"
    assert coded["payment_status"] == "NONE"
    assert_money_equals(coded["severity_score"], 0.00, "severity_score")
    assert coded["triage_tier"] is None

    read_event = validate_success(api.get_event(event["id"], CM))
    assert read_event["open_claim_count"] == 1

    _, meta = validate_paginated(api.list_claims(CE, params={"event_id": event["id"]}))
    assert meta["total_count"] == 1


def test_schedule_assignment_joins_claim_adjuster_and_deployment(api):
    """A scheduled inspection stores all three references and pulls the claim on track.

    PRD 3.7: "A created assignment is `SCHEDULED`, records `EXPLICIT_ADJUSTER`
    or `SELECTOR_RANKED` in `selection_reason`, and starts with
    `report_submitted_at_utc` and `verified_damage_amount` both null."
    PRD 3.7: "Creation also pulls the claim onto the inspection track: a claim
    in `TRIAGED` moves `TRIAGED → INSPECTION_PENDING`, and a claim in
    `REOPENED` moves `REOPENED → INSPECTION_PENDING`; both branches are driven
    by the same event — an assignment for the claim coming into existence in
    `SCHEDULED` — and both leave no further side effects of their own."
    PRD 3.7: "The adjuster's `open_assignment_count` and
    `surge_capacity_score` are recomputed, and the event's posture is
    recomputed, since the claim has just stopped counting as unassigned."

    Design: Corner/endpoints/corner_ep_schedule_assignment_joins_claim_adjuster_and_deployment
    """
    event = _declared_event(api, "CAT-2026-123")
    block = _active_block(api, event["id"])
    adjuster = _adjuster(api, "Marcus Hale", max_open_claims=4)
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
    claim = _claim(
        api,
        event["id"],
        "POL-2001",
        50000,
        [_line(limit=200000, deductible=1000, estimated=60000)],
    )
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    assert triaged["inspection_mode"] == "FIELD"

    response = api.create_inspection_assignment(
        {
            "claim_id": claim["id"],
            "mode": "FIELD",
            "window_start_utc": "2026-08-05T09:00:00.000Z",
            "window_end_utc": "2026-08-05T17:00:00.000Z",
            "adjuster_id": adjuster["id"],
            "deployment_id": deployment["id"],
        },
        DC,
    )

    assignment = validate_success(response, 201)
    assert assignment["status"] == "SCHEDULED"
    assert assignment["selection_reason"] == "EXPLICIT_ADJUSTER"
    assert assignment["claim_id"] == claim["id"]
    assert assignment["adjuster_id"] == adjuster["id"]
    assert assignment["deployment_id"] == deployment["id"]
    assert assignment["verified_damage_amount"] is None
    assert assignment["report_submitted_at_utc"] is None

    read_claim = validate_success(api.get_claim(claim["id"], CE))
    assert read_claim["handling_status"] == "INSPECTION_PENDING"
    assert read_claim["inspection_mode"] == "FIELD"

    read_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert read_adjuster["open_assignment_count"] == 1

    _, meta = validate_paginated(
        api.list_inspection_assignments(DC, params={"deployment_id": deployment["id"]})
    )
    assert meta["total_count"] == 1


def test_event_rollups_read_matches_initial_case_reserve(api):
    """The event's money roll-ups mirror the single INITIAL_CASE ledger row.

    PRD 3.6: "Triage stamps `severity_score` and `triage_tier`, stamps
    `inspection_mode`, stamps `deadline_utc`, and appends an `INITIAL_CASE`
    entry to the reserve ledger whose case-reserve movement comes from the
    initial-reserve rule and whose paid movement is exactly 0.00, taking the
    next per-event sequence number."
    PRD 3.6: "First compute the eligible damage of each coverage line as the
    line's `estimated_damage_amount` capped at its `limit_amount`, less its
    `deductible_amount`, with a floor of zero; sum those **raw, unrounded**
    line values; take the greater of that sum and the claim's
    `reported_loss_amount` as the basis; multiply the basis by the tier reserve
    factor for the claim's `triage_tier` — 0.85 for `CAT_SEVERE`, 0.65 for
    `COMPLEX`, 0.45 for `STANDARD`, 0.25 for `FAST_TRACK` — and round half up
    to 2 decimal places **once, at the end**."
    PRD 3.1: "`case_reserve_total` and `paid_total` are the sums of the
    case-reserve and paid movements of every ledger entry belonging to the
    event, each to 2 decimal places, and `incurred_total` is their sum — the
    conserved quantity of §2.10."

    Design: Corner/endpoints/corner_ep_event_rollups_read_matches_initial_case_reserve
    """
    event = _declared_event(api, "CAT-2026-124")
    claim = _claim(api, event["id"], "POL-1001", 8000, [_line()])
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    assert triaged["triage_tier"] == "FAST_TRACK"

    read_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(read_event["case_reserve_total"], 2000.00, "case_reserve_total")
    assert_money_equals(read_event["paid_total"], 0.00, "paid_total")
    assert_money_equals(read_event["incurred_total"], 2000.00, "incurred_total")
    assert_money_equals(read_event["gross_loss_estimate"], 0.00, "gross_loss_estimate")
    assert read_event["open_claim_count"] == 1
    assert read_event["posture"] == "OPEN"

    rows, meta = validate_paginated(api.list_reserve_entries(CE, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "INITIAL_CASE"
    assert rows[0]["sequence_no"] == 1
    assert_money_equals(rows[0]["delta_case_reserve"], 2000.00, "delta_case_reserve")
    assert_money_equals(rows[0]["delta_paid"], 0.00, "delta_paid")


def test_adjuster_read_returns_surge_capacity_score_eighty(api):
    """One live desk assignment on a four-claim ceiling scores exactly 80.00.

    PRD 3.3: "The **availability term** starts from the adjuster's
    `open_assignment_count` — the number of their inspection assignments
    currently in `SCHEDULED` or `IN_PROGRESS` — divided by their
    `max_open_claims`; that load ratio is capped at 1, subtracted from 1, and
    multiplied by 100, so an idle adjuster contributes 100 points and a fully
    loaded one contributes zero."
    PRD 3.3: "Finally the **certification bonus** is added: 5 points if
    `desk_certified` is true plus a further 5 points if `aerial_certified` is
    true, for a maximum of 10."
    PRD 3.3: "The `cumulative_deployed_hours` input is itself computed: the
    sum, over the adjuster's deployments whose status is `ON_SITE` or
    `DEMOBILIZED`, of the number of hours from that deployment's
    `window_start_utc` to its `window_end_utc`, to 2 decimal places."

    Design: Corner/endpoints/corner_ep_adjuster_read_returns_surge_capacity_score_eighty
    """
    event = _declared_event(api, "CAT-2026-125")
    adjuster = _adjuster(api, "Priya Nair", max_open_claims=4, desk_certified=True)
    claim = _claim(api, event["id"], "POL-1001", 8000, [_line()])
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    assert triaged["inspection_mode"] == "DESK"
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

    read_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert read_adjuster["open_assignment_count"] == 1
    assert_money_equals(read_adjuster["surge_capacity_score"], 80.00, "surge_capacity_score")
    assert read_adjuster["credential_status"] == "VALID"
    assert read_adjuster["deployment_status"] == "AVAILABLE"
    assert_money_equals(read_adjuster["cumulative_deployed_hours"], 0.00, "cumulative_deployed_hours")


def test_loss_estimate_list_read_reevaluates_stale_flag(api):
    """The snapshot list re-evaluates `stale` against the ledger on every read.

    PRD 3.8: "Both methods share a common base: the `reported_component` is the
    event's `incurred_total`, that is its `case_reserve_total` plus its
    `paid_total`."
    PRD 3.8: "Multiply the event's `exposure_count` by its `avg_insured_value`,
    by its `expected_severity_index`, and by the peril development factor —
    1.40 for `HURRICANE`, 1.55 for `WILDFIRE`, 1.65 for `FLOOD`, 1.20 for
    `HAIL`, 1.10 for `WINTER_STORM`, 1.80 for `EARTHQUAKE` — to obtain the
    modelled ultimate."
    PRD 3.8: "Each snapshot records `input_reserve_sequence_high_water`, the
    greatest ledger `sequence_no` on the event at snapshot time, or 0 when the
    event had no entries, and `computed_at_utc` at the current logical-clock
    instant, and is born non-stale."
    PRD 3.8: "Its `stale` flag is a computed property re-evaluated on every
    read: it reads true exactly when a ledger entry exists on the event whose
    `sequence_no` is greater than the snapshot's recorded high-water mark."

    Design: Corner/endpoints/corner_ep_loss_estimate_list_read_reevaluates_stale_flag
    """
    validate_success(api.set_clock(CLOCK_START_UTC, CM))
    event = _declared_event(api, "CAT-2026-126")
    validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "EXPOSURE_BASED",
                "expected_event_version": event["version"],
            },
            CM,
        ),
        201,
    )
    claim = _claim(api, event["id"], "POL-1001", 8000, [_line()])
    validate_success(api.triage_claim(claim["id"], CE))

    rows, meta = validate_paginated(api.list_loss_estimates(CM, params={"event_id": event["id"]}))

    assert meta["total_count"] == 1
    snapshot = rows[0]
    assert snapshot["method"] == "EXPOSURE_BASED"
    assert_money_equals(snapshot["reported_component"], 0.00, "reported_component")
    assert_money_equals(snapshot["ibnr_component"], 17500000.00, "ibnr_component")
    assert_money_equals(snapshot["gross_estimate"], 17500000.00, "gross_estimate")
    assert snapshot["input_reserve_sequence_high_water"] == 0
    assert snapshot["stale"] is True
    assert snapshot["computed_at_utc"] == "2026-08-01T00:00:00.000Z"


def test_check_in_conditional_on_window_start(api):
    """Check-in is refused before `window_start_utc` and lands exactly on it.

    PRD 3.5: "**Check-in** moves the deployment `CONFIRMED → ON_SITE` once the
    adjuster physically arrives. The deployment must be `CONFIRMED`
    (`ERR_DEPLOYMENT_NOT_CONFIRMED`) and the clock must have reached or passed
    `window_start_utc` (`ERR_DEPLOYMENT_WINDOW_NOT_STARTED`)."

    Design: Corner/endpoints/corner_ep_check_in_conditional_on_window_start
    """
    validate_success(api.set_clock(CLOCK_START_UTC, CM))
    event = _declared_event(api, "CAT-2026-127")
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

    early = api.check_in_deployment(deployment["id"], DC)

    validate_error(early, ApiErrorId.ERR_DEPLOYMENT_WINDOW_NOT_STARTED, 409)
    assert validate_success(api.get_deployment(deployment["id"], DC))["status"] == "CONFIRMED"

    validate_success(api.set_clock("2026-08-05T00:00:00.000Z", CM))
    on_time = api.check_in_deployment(deployment["id"], DC)

    checked_in = validate_success(on_time, 200)
    assert checked_in["status"] == "ON_SITE"
    assert validate_success(api.get_housing_block(block["id"], DC))["rooms_occupied"] == 1


def test_activate_vendor_firm_links_firm_to_event(api):
    """Activation stores the event on the firm and leaves its job count at zero.

    PRD 3.9: "A registered firm sits in `NETWORK_INACTIVE` with
    `activated_for_event_id` null and `open_job_count` of zero."
    PRD 3.9: "**Activation** moves a firm `NETWORK_INACTIVE → ACTIVATED`
    against a named `event_id`, which is stored in `activated_for_event_id`."
    PRD 3.9: "Firms may be listed filtered by `activated_for_event_id`,
    `vendor_type`, `status` and `service_state`."

    Design: Corner/endpoints/corner_ep_activate_vendor_firm_links_firm_to_event
    """
    event = _declared_event(api, "CAT-2026-121")
    firm = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Bayline Mitigation",
                "vendor_type": "MITIGATION",
                "service_states": ["FL", "GA"],
                "max_concurrent_jobs": 3,
                "performance_score": 88.50,
            },
            make_vendor_coordinator_headers("vc_seed"),
        ),
        201,
    )
    assert firm["status"] == "NETWORK_INACTIVE"
    assert firm["activated_for_event_id"] is None

    own = make_vendor_coordinator_headers(firm["id"])
    activated = validate_success(
        api.activate_vendor_firm(firm["id"], {"event_id": event["id"]}, own)
    )

    assert activated["status"] == "ACTIVATED"
    assert activated["activated_for_event_id"] == event["id"]
    assert activated["open_job_count"] == 0

    _, meta = validate_paginated(
        api.list_vendor_firms(own, params={"activated_for_event_id": event["id"]})
    )
    assert meta["total_count"] == 1


def test_suspend_vendor_firm_bulk_cancels_dispatched_not_accepted(api):
    """Suspension cancels only the DISPATCHED jobs and keeps the ACCEPTED one.

    PRD 3.9: "From `ACTIVATED` and from `CAPACITY_HOLD` the effects are
    identical: `activated_for_event_id` is cleared and every vendor assignment
    of the firm still in `DISPATCHED` is cancelled, with `open_job_count`
    recomputed."
    PRD 3.9: "The system also cancels dispatched assignments on its own
    initiative when their firm is suspended."

    Design: Corner/endpoints/corner_ep_suspend_vendor_firm_bulk_cancels_dispatched_not_accepted
    """
    event = _declared_event(api, "CAT-2026-119")
    claim = _claim(api, event["id"], "POL-1001", 8000, [_line()])
    firm = validate_success(
        api.create_vendor_firm(
            {
                "firm_name": "Coastal Tarp Co",
                "vendor_type": "TARP",
                "service_states": ["FL"],
                "max_concurrent_jobs": 5,
                "performance_score": 90.00,
            },
            make_vendor_coordinator_headers("vc_seed"),
        ),
        201,
    )
    own = make_vendor_coordinator_headers(firm["id"])
    validate_success(api.activate_vendor_firm(firm["id"], {"event_id": event["id"]}, own))
    va1 = validate_success(
        api.create_vendor_assignment(
            {
                "claim_id": claim["id"],
                "scope_amount": 5000,
                "required_vendor_type": "TARP",
                "vendor_firm_id": firm["id"],
            },
            CE,
        ),
        201,
    )
    validate_success(api.accept_vendor_assignment(va1["id"], own))
    va2 = validate_success(
        api.create_vendor_assignment(
            {
                "claim_id": claim["id"],
                "scope_amount": 3000,
                "required_vendor_type": "TARP",
                "vendor_firm_id": firm["id"],
            },
            CE,
        ),
        201,
    )
    assert va2["status"] == "DISPATCHED"

    suspended = validate_success(api.suspend_vendor_firm(firm["id"], own))

    assert suspended["status"] == "SUSPENDED"
    assert suspended["activated_for_event_id"] is None
    assert suspended["open_job_count"] == 1

    cancelled, cancelled_meta = validate_paginated(
        api.list_vendor_assignments(CE, params={"vendor_firm_id": firm["id"], "status": "CANCELLED"})
    )
    assert cancelled_meta["total_count"] == 1
    assert cancelled[0]["id"] == va2["id"]

    accepted, accepted_meta = validate_paginated(
        api.list_vendor_assignments(CE, params={"vendor_firm_id": firm["id"], "status": "ACCEPTED"})
    )
    assert accepted_meta["total_count"] == 1
    assert accepted[0]["id"] == va1["id"]


def test_submit_batch_transfers_every_member_claim(api):
    """Submitting a batch hands every member claim over in one call.

    PRD 3.9: "Submission stamps `submitted_at_utc` at the current instant,
    records the submitting `X-User-ID` for the later segregation-of-duties
    check, moves every member claim `CLOSED → TRANSFERRED` — a member found in
    any other handling status, or whose `transfer_batch_id` no longer points at
    this batch, makes the submission fail with `ERR_CLAIM_NOT_TRANSFERABLE` —
    and recomputes the event's `open_claim_count` and posture."
    PRD 3.9: "`claim_count` is simply the number of claims pointing at the
    batch; `blocking_claim_count` is the number of those whose `payment_status`
    is `ADVANCE_ISSUED` **or** whose `case_reserve` is exactly zero — the first
    because money is still out on the file, the second because a file carrying
    no reserve at all is a bookkeeping error the receiving unit will not
    accept."
    PRD 3.1: "`open_claim_count` is the number of claims on the event whose
    `handling_status` is neither `CLOSED` nor `TRANSFERRED`."

    Design: Corner/endpoints/corner_ep_submit_batch_transfers_every_member_claim
    """
    validate_success(api.set_clock(CLOCK_START_UTC, CM))
    event = _declared_event(api, "CAT-2026-120")
    adjuster = _adjuster(api, "Priya Nair", desk_certified=True)
    adjuster_headers = make_adjuster_headers(adjuster["id"])
    _active_block(api, event["id"])
    claim_one = _claim(api, event["id"], "POL-1001", 8000, [_line()])
    validate_success(api.triage_claim(claim_one["id"], CE))
    claim_two = _claim(
        api,
        event["id"],
        "POL-1002",
        4000,
        [_line(limit=100000, deductible=500, estimated=3000)],
    )
    validate_success(api.triage_claim(claim_two["id"], CE))
    _snapshot(api, event["id"])
    validate_success(api.activate_surge(event["id"], CM))

    first_assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim_one["id"],
                "mode": "DESK",
                "window_start_utc": "2026-08-05T09:00:00.000Z",
                "window_end_utc": "2026-08-05T17:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )
    second_assignment = validate_success(
        api.create_inspection_assignment(
            {
                "claim_id": claim_two["id"],
                "mode": "DESK",
                "window_start_utc": "2026-08-05T17:00:00.000Z",
                "window_end_utc": "2026-08-06T01:00:00.000Z",
                "adjuster_id": adjuster["id"],
            },
            DC,
        ),
        201,
    )

    validate_success(api.set_clock("2026-08-05T10:00:00.000Z", CM))
    validate_success(api.start_inspection(first_assignment["id"], adjuster_headers))
    validate_success(
        api.complete_inspection(
            first_assignment["id"], {"verified_damage_amount": 6000}, adjuster_headers
        )
    )

    validate_success(api.set_clock("2026-08-05T18:00:00.000Z", CM))
    validate_success(api.start_inspection(second_assignment["id"], adjuster_headers))
    validate_success(
        api.complete_inspection(
            second_assignment["id"], {"verified_damage_amount": 5000}, adjuster_headers
        )
    )

    validate_success(api.close_claim(claim_one["id"], CE))
    validate_success(api.close_claim(claim_two["id"], CE))
    validate_success(api.demobilize_event(event["id"], CM))

    batch = validate_success(
        api.create_batch({"event_id": event["id"], "target_unit": "PROPERTY-EAST"}, CE), 201
    )
    validate_success(api.add_claim_to_batch(batch["id"], {"claim_id": claim_one["id"]}, CE))
    validate_success(api.add_claim_to_batch(batch["id"], {"claim_id": claim_two["id"]}, CE))

    submitted = validate_success(api.submit_batch(batch["id"], CE))

    assert submitted["status"] == "SUBMITTED"
    assert submitted["claim_count"] == 2
    assert submitted["blocking_claim_count"] == 0
    assert submitted["submitted_at_utc"] == "2026-08-05T18:00:00.000Z"

    for claim_id in (claim_one["id"], claim_two["id"]):
        read_claim = validate_success(api.get_claim(claim_id, CE))
        assert read_claim["handling_status"] == "TRANSFERRED"
        assert read_claim["transfer_batch_id"] == batch["id"]

    read_event = validate_success(api.get_event(event["id"], CM))
    assert read_event["open_claim_count"] == 0

"""Rejection precedence: requests engineered so two guards fire at once, and the lower
numbered check must be the one that answers."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_cycle,
    create_vetted_volunteer,
    make_program_manager_headers,
    make_volunteer_headers,
    read_engagement,
    read_request,
    read_time_logs,
    read_window,
    set_clock,
    setup_accepted_engagement,
    setup_held_milestone_engagement,
    setup_submitted_engagement,
    validate_error,
    validate_paginated,
)

HANDBOOK = [
    {
        "title": "Handbook",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "Handbook adopted",
    }
]

THIRTY_HOURS = [
    {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-13T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-14T00:00:00Z", "hours": 6.00, "activity_class": "DELIVERY"},
]

DPA_PACK = [
    {
        "title": "DPA pack",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "DPA executed",
    }
]

TWELVE_DELIVERY_HOURS = [
    {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
]

THIRTEENTH_HOUR_LOG = {
    "work_date": "2026-08-18T00:00:00Z",
    "hours": 12.00,
    "activity_class": "DELIVERY",
}

UNATTESTED_HANDOFF = {"confidentiality_attested": False, "handoff_artifact_count": 3}


# ---------------------------------------------------------------------------
# Check 23 (work state) versus check 55 (window hours)
# ---------------------------------------------------------------------------
def _tight_window_world(stage_setup):
    """A 41.00-hour window holding a 40.00-hour engagement with 30.00 hours already
    approved, leaving 11.00 hours of headroom against a 12.00-hour log."""
    return stage_setup(
        skill_code="LEGAL_CONTRACTS",
        window_hours=41.00,
        deliverables=HANDBOOK,
        time_logs=THIRTY_HOURS,
        reported_cumulative_hours=30.00,
        title="Tenant handbook",
    )


def test_submitted_engagement_answers_with_work_state_not_window_hours(api):
    """PRD §2.12: "The ordering is global: a check with a lower number always wins over a
    check with a higher number on the same endpoint."
    PRD §2.12: "The engagement's `work_status` is in the from-set of the requested
    transition — start requires `NOT_STARTED`, submit requires `IN_PROGRESS`, time logging
    and scope-change creation require `IN_PROGRESS`, opening a quality review requires
    `SUBMITTED`, handoff requires `ACCEPTED`, and terminate requires a non-terminal value —
    on `POST /engagements/{id}/start`, `POST /engagements/{id}/submit`,
    `POST /engagements/{id}/time-logs`, `POST /engagements/{id}/scope-change-requests`,
    `POST /engagements/{id}/quality-reviews`, `POST /engagements/{id}/handoff`,
    `POST /engagements/{id}/terminate`, `POST /engagements/{id}/satisfaction-surveys` and
    `POST /milestones/{id}/hold`, otherwise `ERR_INVALID_WORK_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/work_state_beats_availability_hours
    """
    world = _tight_window_world(setup_submitted_engagement)

    response = api_client.create_time_log(
        world["engagement"]["id"], THIRTEENTH_HOUR_LOG, world["volunteer_headers"]
    )

    validate_error(response, ApiErrorId.ERR_INVALID_WORK_STATE)
    body = response.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_AVAILABILITY_HOURS_EXCEEDED.value, (
        "The lower-numbered work-state check must win over the hour-custody check"
    )


def test_rejected_log_leaves_the_engagement_and_its_hour_ledger_untouched(api):
    """PRD §2.12: "When one request violates several rules at once, exactly one error is
    returned, and which one is fixed rather than incidental."
    PRD §3.7: "The engagement's `approved_hours` is the sum of `hours` over its child logs
    whose `approved` flag is true, across every activity class without exception, rounded to
    two decimals."

    Design: Difficulty/priority_pair_validation_conflict/work_state_beats_availability_hours
    """
    world = _tight_window_world(setup_submitted_engagement)

    api_client.create_time_log(
        world["engagement"]["id"], THIRTEENTH_HOUR_LOG, world["volunteer_headers"]
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "SUBMITTED", (
        f"Expected work_status still SUBMITTED, got {engagement['work_status']}"
    )
    assert engagement["approved_hours"] == pytest.approx(30.00, abs=0.01), (
        f"Expected approved_hours 30.00, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(-0.2500, abs=1e-4), (
        f"Expected scope_creep_pct -0.2500, got {engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "NONE", (
        f"Expected creep_escalation_level NONE, got {engagement['creep_escalation_level']}"
    )
    window = read_window(world)
    assert window["hours_offered"] == pytest.approx(41.00, abs=0.01), (
        f"Expected hours_offered 41.00, got {window['hours_offered']}"
    )
    assert window["hours_committed"] == pytest.approx(40.00, abs=0.01), (
        f"Expected hours_committed 40.00, got {window['hours_committed']}"
    )
    assert len(read_time_logs(world)) == 3, (
        f"Expected the three setup logs and no fourth, got {len(read_time_logs(world))}"
    )


def test_window_hour_guard_answers_once_the_work_state_guard_is_satisfied(api):
    """PRD §2.12: "The pinned availability window's `hours_remaining` is greater than or
    equal to the hours being held or logged — `reserved_hours` at match time,
    `additional_hours` at scope-change approval, and a log's `hours` measured against
    `hours_offered` less the hours already approved on that window — on
    `POST /project-requests/{id}/match`, `POST /engagements/{id}/time-logs` and
    `POST /scope-change-requests/{id}/decide`, otherwise `ERR_AVAILABILITY_HOURS_EXCEEDED`
    (422)."

    Design: Difficulty/priority_pair_validation_conflict/work_state_beats_availability_hours
    """
    world = _tight_window_world(setup_held_milestone_engagement)
    assert read_engagement(world)["work_status"] == "IN_PROGRESS", (
        "Setup expected a live engagement so only the hour guard can fire"
    )

    response = api_client.create_time_log(
        world["engagement"]["id"], THIRTEENTH_HOUR_LOG, world["volunteer_headers"]
    )

    validate_error(response, ApiErrorId.ERR_AVAILABILITY_HOURS_EXCEEDED)
    assert len(read_time_logs(world)) == 3, (
        "A refused log must not be persisted, got "
        f"{len(read_time_logs(world))} rows"
    )


# ---------------------------------------------------------------------------
# Check 23 (work state) versus check 34 (confidentiality attestation)
# ---------------------------------------------------------------------------
def test_handoff_from_submitted_answers_with_work_state_not_attestation(api):
    """PRD §2.12: "The ordering is global: a check with a lower number always wins over a
    check with a higher number on the same endpoint."
    PRD §2.12: "The handoff payload carries `confidentiality_attested` set to true and, when
    the pinned revision's `confidentiality_tier` is `RESTRICTED`, also a non-empty
    `destruction_certificate_ref` — on `POST /engagements/{id}/handoff` — otherwise
    `ERR_CONFIDENTIALITY_ATTESTATION_MISSING` (422)."

    Design: Difficulty/priority_pair_validation_conflict/work_state_beats_confidentiality_attestation
    """
    world = setup_submitted_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=DPA_PACK,
        time_logs=TWELVE_DELIVERY_HOURS,
        reported_cumulative_hours=12.00,
        title="Data sharing terms",
    )

    response = api_client.handoff_engagement(
        world["engagement"]["id"], UNATTESTED_HANDOFF, world["pm_headers"]
    )

    validate_error(response, ApiErrorId.ERR_INVALID_WORK_STATE)
    body = response.json()
    assert (
        body["data"]["error_id"]
        != ApiErrorId.ERR_CONFIDENTIALITY_ATTESTATION_MISSING.value
    ), "The work-state check at 23 must win over the attestation check at 34"


def test_refused_handoff_leaves_the_engagement_submitted_and_unattested(api):
    """PRD §3.8: "It requires the engagement to be in `ACCEPTED`, and the payload carries
    `confidentiality_attested`, which must be true, a `handoff_artifact_count` of at least
    one naming how many artifacts were transferred, and — when the pinned revision's
    `confidentiality_tier` is `RESTRICTED` — a non-empty `destruction_certificate_ref`."
    PRD §2.8: "`slots_committed` counts the engagements attributed to the cycle whose
    `work_status` is `NOT_STARTED`, `IN_PROGRESS`, `SUBMITTED` or `ACCEPTED`;
    `slots_reserved` counts the match offers still in `OFFERED` status whose project request
    belongs to the cycle; `slots_available` is `capacity_slot_total` less both of those,
    floored at 0 so it never reads negative."

    Design: Difficulty/priority_pair_validation_conflict/work_state_beats_confidentiality_attestation
    """
    world = setup_submitted_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=DPA_PACK,
        time_logs=TWELVE_DELIVERY_HOURS,
        reported_cumulative_hours=12.00,
        title="Data sharing terms",
    )

    api_client.handoff_engagement(
        world["engagement"]["id"], UNATTESTED_HANDOFF, world["pm_headers"]
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "SUBMITTED", (
        f"Expected work_status still SUBMITTED, got {engagement['work_status']}"
    )
    assert engagement["confidentiality_attested"] is False, (
        f"Expected confidentiality_attested still false, got "
        f"{engagement['confidentiality_attested']}"
    )
    assert engagement["handoff_at"] is None, (
        f"Expected a null handoff_at, got {engagement['handoff_at']}"
    )
    request = read_request(world)
    assert request["status"] == "IN_DELIVERY", (
        f"Expected the request still IN_DELIVERY, got {request['status']}"
    )


def test_attestation_guard_answers_once_the_engagement_is_accepted(api):
    """PRD §2.12: "The handoff payload carries `confidentiality_attested` set to true and,
    when the pinned revision's `confidentiality_tier` is `RESTRICTED`, also a non-empty
    `destruction_certificate_ref` — on `POST /engagements/{id}/handoff` — otherwise
    `ERR_CONFIDENTIALITY_ATTESTATION_MISSING` (422)."

    Design: Difficulty/priority_pair_validation_conflict/work_state_beats_confidentiality_attestation
    """
    world = setup_accepted_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=DPA_PACK,
        time_logs=TWELVE_DELIVERY_HOURS,
        reported_cumulative_hours=12.00,
        title="Data sharing terms",
    )
    assert read_engagement(world)["work_status"] == "ACCEPTED", (
        "Setup expected an ACCEPTED engagement so only the attestation guard can fire"
    )

    response = api_client.handoff_engagement(
        world["engagement"]["id"], UNATTESTED_HANDOFF, world["pm_headers"]
    )

    validate_error(response, ApiErrorId.ERR_CONFIDENTIALITY_ATTESTATION_MISSING)
    engagement = read_engagement(world)
    assert engagement["handoff_at"] is None, (
        f"A refused handoff must not stamp handoff_at, got {engagement['handoff_at']}"
    )


# ---------------------------------------------------------------------------
# Check 39 (window containment) versus check 43 (window overlap)
# ---------------------------------------------------------------------------
def _single_cycle_roster():
    """One cycle spanning [2026-08-01, 2026-11-01) and one vetted volunteer already
    holding a HARD window [2026-08-05, 2026-10-01)."""
    pm = make_program_manager_headers()
    cycle = create_cycle(
        pm,
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-11-01T00:00:00Z",
        capacity_slot_total=10,
    )
    volunteer, _skill, window = create_vetted_volunteer(
        skill_code="LEGAL_CONTRACTS",
        window_overrides={
            "starts_at": "2026-08-05T00:00:00Z",
            "ends_at": "2026-10-01T00:00:00Z",
            "window_kind": "HARD",
            "hours_offered": 300.00,
        },
    )
    return {
        "pm_headers": pm,
        "cycle": cycle,
        "volunteer": volunteer,
        "volunteer_headers": make_volunteer_headers(volunteer["id"]),
        "window": window,
    }


def test_window_containment_answers_before_the_overlap_guard(api):
    """PRD §2.12: "A new availability window has `ends_at` strictly after `starts_at` and its
    whole half-open interval lies inside some program cycle's half-open interval — on
    `POST /volunteers/{id}/availability-windows` — otherwise `ERR_WINDOW_OUTSIDE_CYCLE`
    (422)."
    PRD §2.12: "The ordering is global: a check with a lower number always wins over a check
    with a higher number on the same endpoint."

    Design: Difficulty/priority_pair_validation_conflict/window_temporal_beats_overlap
    """
    world = _single_cycle_roster()
    set_clock("2026-08-10T00:00:00Z", world["pm_headers"])

    response = api_client.create_availability_window(
        world["volunteer"]["id"],
        {
            "starts_at": "2026-09-01T00:00:00Z",
            "ends_at": "2026-12-01T00:00:00Z",
            "window_kind": "SOFT",
            "hours_offered": 50.00,
        },
        world["volunteer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_WINDOW_OUTSIDE_CYCLE)
    body = response.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_AVAILABILITY_WINDOW_OVERLAP.value, (
        "Containment at 39 must win over overlap at 43 even though both are violated"
    )


def test_refused_window_is_never_persisted(api):
    """PRD §2.9: "For every availability window, `hours_committed` equals the sum of
    `reserved_hours` over the match offers still in `OFFERED` status that are held against
    that window, plus the sum of `committed_hours` over the engagements held against that
    window whose `work_status` is `NOT_STARTED`, `IN_PROGRESS`, `SUBMITTED` or `ACCEPTED`,
    the total rounded to two decimals; and `hours_remaining` equals `hours_offered` less
    `hours_committed`, also to two decimals."

    Design: Difficulty/priority_pair_validation_conflict/window_temporal_beats_overlap
    """
    world = _single_cycle_roster()

    api_client.create_availability_window(
        world["volunteer"]["id"],
        {
            "starts_at": "2026-09-01T00:00:00Z",
            "ends_at": "2026-12-01T00:00:00Z",
            "window_kind": "SOFT",
            "hours_offered": 50.00,
        },
        world["volunteer_headers"],
    )

    rows, _meta = validate_paginated(
        api_client.list_availability_windows(
            world["volunteer"]["id"], world["pm_headers"]
        )
    )
    assert len(rows) == 1, f"Expected the single seeded window to survive, got {len(rows)}"
    surviving = read_window(world)
    assert surviving["ends_at"].startswith("2026-10-01T00:00:00"), (
        f"Expected the existing window untouched at 2026-10-01T00:00:00Z, got "
        f"{surviving['ends_at']}"
    )
    assert surviving["hours_offered"] == pytest.approx(300.00, abs=0.01), (
        f"Expected hours_offered 300.00, got {surviving['hours_offered']}"
    )
    assert surviving["hours_committed"] == pytest.approx(0.00, abs=0.01), (
        f"Expected hours_committed 0.00, got {surviving['hours_committed']}"
    )


def test_overlap_guard_answers_when_the_window_is_properly_contained(api):
    """PRD §2.12: "A new availability window does not overlap any existing window of the same
    volunteer whose `status` is not `EXPIRED` — on
    `POST /volunteers/{id}/availability-windows` — otherwise
    `ERR_AVAILABILITY_WINDOW_OVERLAP` (409)."

    Design: Difficulty/priority_pair_validation_conflict/window_temporal_beats_overlap
    """
    world = _single_cycle_roster()

    response = api_client.create_availability_window(
        world["volunteer"]["id"],
        {
            "starts_at": "2026-09-01T00:00:00Z",
            "ends_at": "2026-10-15T00:00:00Z",
            "window_kind": "SOFT",
            "hours_offered": 50.00,
        },
        world["volunteer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_AVAILABILITY_WINDOW_OVERLAP)

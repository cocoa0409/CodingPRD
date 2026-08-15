"""Permits, route surveys, clearance verdicts, and the clearance gate chain."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    set_clock,
    create_tx_job,
    list_job_legs,
    quote_job,
    get_job,
    get_leg,
    get_survey,
    accept_quote,
    add_permit,
    issue_permit,
    request_survey,
    submit_survey,
    submit_survey_payload,
    decide_survey,
    decide_survey_payload,
    accept_survey_with_clearance,
    obstruction_spec,
    assert_obstruction,
    make_carrier_rep_headers,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SAFETY = TEST_USERS["safety_manager_headers"]


def _booked_survey_job(carrier_name="Survey Co"):
    """Booked TX job at width 170 / height 170 (survey required, rear 1)."""
    carrier = register_carrier(10_000_000, carrier_name)
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="Tall load", height_inches=170)
    leg = list_job_legs(job["id"])[0]
    quote_job(job["id"])
    accept_quote(job["id"], carrier)
    return carrier, job, leg


def test_surveyed_fail_blocks_leg_despite_map_pass(api):
    """PRD §3.4: "The required clearance is the job's `height_inches` plus a
    six-inch buffer; the verdict is `PASS` when the accepted survey's
    `surveyed_min_clearance_inches` is at least the required clearance —
    equality passes — and `FAIL` otherwise"
    PRD §3.4: "the map-database `map_min_clearance_inches` supports only an
    advisory estimate against the same required clearance and never blocks the
    leg, so a surveyed `FAIL` can legitimately contradict the map estimate for
    identical job dimensions. A `FAIL` verdict moves the leg from `DETERMINED`
    or `CLEARED` to `BLOCKED`"

    Design: Difficulty/dual_variant_calc/map_vs_surveyed_clearance_verdict
    """
    carrier, job, leg = _booked_survey_job("Bison Freight")
    permit = add_permit(leg["id"], permit_number="TX-P-9")
    issue_permit(permit["id"])

    # Map estimate (180) passes required clearance 176, but is advisory only.
    survey = request_survey(leg["id"])
    submit_survey(survey["id"], 175)
    decide_survey(survey["id"], leg["id"], "ACCEPTED")

    leg = get_leg(leg["id"])
    assert leg["clearance_verdict"] == "FAIL", "175 < 176: surveyed variant fails what the map passes"
    assert leg["leg_status"] == "BLOCKED"
    job = get_job(job["id"])
    assert job["job_status"] == "BOOKED"


def test_second_survey_reopens_leg_and_supersedes_first(api):
    """PRD §3.4: "Requesting a survey on a `BLOCKED` leg re-opens it for
    clearance: the leg returns to `DETERMINED`, its `clearance_verdict` is reset
    to `UNKNOWN`, and its `survey_min_clearance_inches` is reset to null."
    PRD §3.4: "moves the survey to `ACCEPTED`, and immediately moves any
    previously `ACCEPTED` survey on the same leg to the terminal `SUPERSEDED`
    status"

    Design: Difficulty/dual_variant_calc/map_vs_surveyed_clearance_verdict
    """
    carrier, job, leg = _booked_survey_job("Bison Freight")
    permit = add_permit(leg["id"], permit_number="TX-P-9")
    issue_permit(permit["id"])
    survey1 = request_survey(leg["id"])
    submit_survey(survey1["id"], 175)
    decide_survey(survey1["id"], leg["id"], "ACCEPTED")
    assert get_leg(leg["id"])["leg_status"] == "BLOCKED"

    # The fresh request re-opens the blocked leg.
    survey2 = request_survey(leg["id"])
    leg = get_leg(leg["id"])
    assert leg["leg_status"] == "DETERMINED"
    assert leg["clearance_verdict"] == "UNKNOWN"
    assert leg["survey_min_clearance_inches"] is None

    submit_survey(survey2["id"], 177)
    decide_survey(survey2["id"], leg["id"], "ACCEPTED")

    assert get_survey(survey1["id"])["survey_status"] == "SUPERSEDED"
    assert get_survey(survey2["id"])["survey_status"] == "ACCEPTED"
    leg = get_leg(leg["id"])
    assert leg["clearance_verdict"] == "PASS", "177 >= 176"
    assert leg["leg_status"] == "CLEARED"
    assert get_job(job["id"])["job_status"] == "CLEARED"


def test_permit_issue_alone_leaves_job_booked(api):
    """PRD §3.4: "A job in `BOOKED` moves automatically to `CLEARED` the moment
    every one of its legs satisfies all three gates — every leg has an `ISSUED`
    permit, every leg that requires a route survey holds a `PASS` verdict from
    an accepted, non-superseded survey, and every leg that requires a police
    escort has police coordination confirmed."

    Design: Difficulty/cross_entity_state_dependency/job_cleared_gate_permit_and_survey
    """
    carrier, job, leg = _booked_survey_job("Gate Test Carriers")
    permit = add_permit(leg["id"], permit_number="TX-P-11")
    issue_permit(permit["id"])

    job_mid = get_job(job["id"])
    assert job_mid["job_status"] == "BOOKED", (
        "permit issuance alone must not clear the job while the survey gate is unmet"
    )
    assert get_leg(leg["id"])["leg_status"] == "DETERMINED"


def test_survey_accept_pass_clears_leg_and_job(api):
    """PRD §3.4: "A `PASS` verdict moves the leg from `DETERMINED` or `BLOCKED`
    to `CLEARED` — provided the leg's remaining gates hold: an `ISSUED` permit
    exists for the leg, and `police_confirmed` is true whenever the leg
    requires a police escort."
    PRD §3.4: "A job in `BOOKED` moves automatically to `CLEARED` the moment
    every one of its legs satisfies all three gates"

    Design: Difficulty/cross_entity_state_dependency/job_cleared_gate_permit_and_survey
    """
    carrier, job, leg = _booked_survey_job("Gate Test Carriers")
    permit = add_permit(leg["id"], permit_number="TX-P-11")
    issue_permit(permit["id"])
    accept_survey_with_clearance(leg["id"], 180)

    leg = get_leg(leg["id"])
    assert leg["clearance_verdict"] == "PASS"
    assert leg["leg_status"] == "CLEARED"
    assert get_job(job["id"])["job_status"] == "CLEARED"


def test_clearance_equality_passes(api):
    """PRD §3.4: "The required clearance is the job's `height_inches` plus a
    six-inch buffer; the verdict is `PASS` when the accepted survey's
    `surveyed_min_clearance_inches` is at least the required clearance —
    equality passes — and `FAIL` otherwise"

    Design: Corner/calculations/clearance_equality_passes
    """
    carrier, job, leg = _booked_survey_job("Equality Co")
    permit = add_permit(leg["id"], permit_number="TX-P-37")
    issue_permit(permit["id"])
    accept_survey_with_clearance(leg["id"], 176)

    leg = get_leg(leg["id"])
    assert leg["clearance_verdict"] == "PASS", "176 >= 176: equality passes"
    assert leg["leg_status"] == "CLEARED"
    assert get_job(job["id"])["job_status"] == "CLEARED"


def test_obstruction_rows_append_only_and_provisional_mirror(api):
    """PRD §3.4: "Submission moves the survey to `SUBMITTED`, stamps
    `submitted_at`, and creates one append-only Obstruction row per element of
    `obstructions`"
    PRD §2.5: "Obstruction rows are the single exception: an Obstruction
    carries only `id` and `created_at`."
    PRD §3.4: "The leg immediately mirrors the submitted figure: its
    `survey_min_clearance_inches` is set to the surveyed value on a provisional
    basis while the decision is pending, and the verdict stays `UNKNOWN`."

    Design: Corner/entities/obstruction_rows_append_only
    """
    carrier, job, leg = _booked_survey_job("Obstruction Co")
    survey = request_survey(leg["id"])
    obstructions = [
        obstruction_spec(12.5, "BRIDGE", 175, "REQUIRES_REROUTE"),
        obstruction_spec(20.0, "WIRE", 190, "PASSABLE_WITH_POLE"),
    ]
    submitted = submit_survey(survey["id"], 175, obstructions)
    assert submitted["survey_status"] == "SUBMITTED"
    assert submitted["surveyed_min_clearance_inches"] == 175

    rows, meta = validate_paginated(api.list_survey_obstructions(survey["id"], DISPATCHER))
    assert meta["total_count"] == 2
    assert rows[0]["milepost"] == 12.5 and rows[0]["obstruction_type"] == "BRIDGE"
    assert rows[0]["measured_clearance_inches"] == 175
    assert rows[0]["disposition"] == "REQUIRES_REROUTE"
    assert rows[1]["milepost"] == 20.0 and rows[1]["obstruction_type"] == "WIRE"
    assert rows[1]["measured_clearance_inches"] == 190
    assert rows[1]["disposition"] == "PASSABLE_WITH_POLE"
    for row in rows:
        assert_obstruction(row)

    leg = get_leg(leg["id"])
    assert leg["survey_min_clearance_inches"] == 175, "submitted figure is mirrored provisionally"
    assert leg["clearance_verdict"] == "UNKNOWN"


def test_survey_state_gates_rejected(api):
    """PRD §3.4: "The surveyor then submits field findings on a `REQUESTED`
    survey — a survey in any other status is rejected with
    `ERR_SURVEY_INVALID_STATE`"
    PRD §3.4: "Deciding a survey belongs to a `SafetyManager`, acting on a
    `SUBMITTED` survey (else `ERR_SURVEY_INVALID_STATE`)"

    Design: Corner/state_machines/survey_state_gates_rejected
    """
    carrier, job, leg = _booked_survey_job("Survey Gates Co")
    survey = request_survey(leg["id"])

    # Accept before submit is an invalid-from rejection.
    leg_now = get_leg(leg["id"])
    resp = api.decide_survey(
        survey["id"],
        decide_survey_payload(leg_now["version"], "ACCEPTED"),
        SAFETY,
    )
    validate_error(resp, ApiErrorId.ERR_SURVEY_INVALID_STATE)

    submitted = submit_survey(survey["id"], 180)
    assert submitted["survey_status"] == "SUBMITTED"

    # Double submit is likewise rejected and does not overwrite the figure.
    resp2 = api.submit_survey(survey["id"], submit_survey_payload(181), TEST_USERS["route_surveyor_headers"])
    validate_error(resp2, ApiErrorId.ERR_SURVEY_INVALID_STATE)
    assert get_survey(survey["id"])["surveyed_min_clearance_inches"] == 180


def test_occ_leg_survey_accept_stale_version(api):
    """PRD §2.9: "Deciding a route survey (accept or reject) requires the
    request to carry `expected_leg_version`, holding the leg `version` the
    client last observed. If that value does not match the leg's current
    `version` — for example because a prior decision on this leg superseded the
    previously accepted survey and recomputed the leg's clearance verdict — the
    decision is rejected with `ERR_STALE_LEG_VERSION` (HTTP 412), since it
    would be based on a stale survey set."

    Design: Corner/cross_cutting_layers/occ_leg_survey_accept_stale_version
    """
    carrier, job, leg = _booked_survey_job("OCC Leg Co")
    survey = request_survey(leg["id"])
    submit_survey(survey["id"], 180)
    leg_v = get_leg(leg["id"])["version"]

    resp = api.decide_survey(
        survey["id"], decide_survey_payload(leg_v - 1, "ACCEPTED"), SAFETY
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LEG_VERSION)
    assert get_survey(survey["id"])["survey_status"] == "SUBMITTED"

    accepted = decide_survey(survey["id"], leg["id"], "ACCEPTED")
    assert accepted["survey_status"] == "ACCEPTED"
    leg = get_leg(leg["id"])
    assert leg["version"] == leg_v + 1, "the accept decision increments the leg version"
    assert leg["clearance_verdict"] == "PASS"


def test_clock_advance_expires_permit_and_blocks_leg(api):
    """PRD §2.4: "Advancing the clock is not inert: it triggers a sweep of
    time-dependent state. Every permit in `ISSUED` status whose `valid_until`
    is earlier than the new current time transitions to `EXPIRED`, and each
    such expiry cascades — the affected leg falls from `CLEARED` to `BLOCKED`,
    and the owning job is demoted from `CLEARED` or `SCHEDULED` back to
    `BOOKED` as described in §3.4."

    Design: Difficulty/transitive_cascade/clock_permit_expiry_leg_job_demote
    """
    carrier = register_carrier(10_000_000, "Llano Logistics")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="Wide crate", width_inches=150)
    leg = list_job_legs(job["id"])[0]
    quote_job(job["id"])
    accept_quote(job["id"], carrier)
    permit = add_permit(
        leg["id"], permit_number="TX-P-8", valid_until="2026-08-11T00:00:00Z"
    )
    issue_permit(permit["id"])
    validate_success(api.schedule_job(job["id"], DISPATCHER))

    # The whole chain fires as a side effect of the clock advance.
    validate_success(api.set_clock({"to_iso8601": "2026-08-12T00:00:00Z"}, DISPATCHER))

    rows, _ = validate_paginated(api.list_leg_permits(leg["id"], DISPATCHER))
    assert rows[0]["permit_status"] == "EXPIRED", "the clock advance mutated the permit"
    leg = get_leg(leg["id"])
    assert leg["leg_status"] == "BLOCKED", "the permit expiry blocked the cleared leg"


def test_clock_permit_expiry_demotes_scheduled_job(api):
    """PRD §2.4: "each such expiry cascades — the affected leg falls from
    `CLEARED` to `BLOCKED`, and the owning job is demoted from `CLEARED` or
    `SCHEDULED` back to `BOOKED` as described in §3.4."

    Design: Difficulty/transitive_cascade/clock_permit_expiry_leg_job_demote
    """
    carrier = register_carrier(10_000_000, "Llano Logistics")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="Wide crate", width_inches=150)
    leg = list_job_legs(job["id"])[0]
    quote_job(job["id"])
    accept_quote(job["id"], carrier)
    permit = add_permit(
        leg["id"], permit_number="TX-P-8", valid_until="2026-08-11T00:00:00Z"
    )
    issue_permit(permit["id"])
    validate_success(api.schedule_job(job["id"], DISPATCHER))
    assert get_job(job["id"])["job_status"] == "SCHEDULED"

    validate_success(api.set_clock({"to_iso8601": "2026-08-12T00:00:00Z"}, DISPATCHER))

    job = get_job(job["id"])
    assert job["job_status"] == "BOOKED", (
        "the blocked leg demoted the SCHEDULED job, skipping CLEARED"
    )
    assert get_leg(leg["id"])["leg_status"] == "BLOCKED"


def test_permit_issue_twice_rejected(api):
    """PRD §3.4: "Marking the permit issued, also a `Dispatcher` action,
    requires the permit to be in `APPLIED` (else `ERR_PERMIT_INVALID_STATE`)"

    Design: Corner/state_machines/permit_issue_twice_rejected
    """
    carrier = register_carrier(10_000_000, "Permit Co")
    set_clock("2026-08-05T00:00:00Z")
    job = create_tx_job(carrier, load_description="P", width_inches=150)
    leg = list_job_legs(job["id"])[0]
    quote_job(job["id"])
    accept_quote(job["id"], carrier)
    permit = add_permit(leg["id"], permit_number="TX-P-24")
    issued = issue_permit(permit["id"])
    assert issued["permit_status"] == "ISSUED"

    resp = api.issue_permit(permit["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_PERMIT_INVALID_STATE)

    rows, _ = validate_paginated(api.list_leg_permits(leg["id"], DISPATCHER))
    row = [p for p in rows if p["id"] == permit["id"]][0]
    assert row["permit_status"] == "ISSUED"
    assert row["issued_at"] == issued["issued_at"], "a rejected re-issue must not restamp issued_at"

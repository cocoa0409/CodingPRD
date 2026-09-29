"""Leniency: the marker race, the independent disclosure dimension, the pinned
penalty arithmetic and the queue position that prices it.
"""
from test_helpers import (
    ADMIN, COUNSEL, THREE_AFFECTED_YEARS, UNKNOWN_UUID, ApiErrorId,
    assert_leniency_application, create_leniency_application_payload,
    decide_disclosure, decide_marker, disclosure_submission_payload,
    log_and_escalate_contact, open_leniency_application, read_application,
    read_business_unit, register_business_unit, register_employee,
    request_marker, run_assessment, set_clock, setup_high_band_unit,
    submit_disclosure, validate_error, validate_paginated, validate_success,
    withdrawal_payload,
)

CARTEL = "EU-RESIN-2021"


def _two_ranked_units():
    """Units X and Y, both HIGH band, whose markers are granted a day apart."""
    unit_x = setup_high_band_unit(name="Resins X", market_code="EU-RESIN")["unit"]
    unit_y = setup_high_band_unit(name="Resins Y", market_code="EU-RESIN")["unit"]
    app_x = open_leniency_application(unit_x["id"], CARTEL, THREE_AFFECTED_YEARS)
    app_y = open_leniency_application(unit_y["id"], CARTEL, THREE_AFFECTED_YEARS)

    set_clock("2026-08-02T00:00:00Z")
    request_marker(app_x["id"])
    decide_marker(app_x["id"], "GRANTED")

    set_clock("2026-08-03T00:00:00Z")
    request_marker(app_y["id"])
    decide_marker(app_y["id"], "GRANTED")
    return {"unit_x": unit_x, "unit_y": unit_y, "app_x": app_x, "app_y": app_y}


def test_penalty_rounds_each_affected_year_before_summing_them(api):
    """PRD §3.9: "**Step one** rounds each affected year on its own, in `year`
    ascending order: that year's `affected_commerce_cents` multiplied by
    `gravity_pct` and divided by 100, rounded half up to whole cents. **Step
    two** sums those already-rounded per-year figures into the base penalty."
    PRD §3.9: "As a worked contrast, affected commerce of 1,000,000,010 cents,
    2,000,000,030 cents and 3,000,000,050 cents at a gravity of 15 percent gives
    per-year figures of 150,000,002, 300,000,005 and 450,000,008 cents, summing
    to 900,000,015 cents under the required order — against 900,000,014 cents
    under the forbidden one."
    PRD §3.9: "**Step three** applies a duration uplift: one tenth is added for
    each affected year beyond the first, so the multiplier is 1 plus 0.10
    multiplied by one less than the number of entries in `affected_years`, held
    to a ceiling of 2.00 — which is reached at eleven affected years and never
    exceeded."
    PRD §3.9: "**Step four** reads the leniency reduction off the queue
    position: 100 percent for rank 1, 50 percent for rank 2, 30 percent for rank
    3, and 0 percent for any rank beyond 3 or for a null rank."

    Design: Difficulty/combinatorial_formula/leniency_penalty_round_per_year_then_sum
    """
    set_clock()
    scene = _two_ranked_units()

    data = validate_success(api.submit_disclosure(
        scene["app_y"]["id"], disclosure_submission_payload(15), COUNSEL))

    assert_leniency_application(data)
    assert data["gravity_pct"] == 15
    assert data["disclosure_status"] == "SUBMITTED"
    assert data["marker_status"] == "MARKER_GRANTED"
    assert data["estimated_penalty_cents"] == 540000009, (
        "900000015 base at the 1.20 uplift, halved by the rank-2 reduction")


def test_leniency_queue_ranks_candidates_by_marker_grant_instant(api):
    """PRD §3.9: "An application's `priority_rank` is its 1-based position among
    the candidates for its `cartel_code`. The candidate set is every application
    — **across all business units**, because the race is a race across the whole
    cartel and not within one company — whose `cartel_code` matches and whose
    `marker_status` is `MARKER_GRANTED` or `PERFECTED`. Candidates are ordered
    by `marker_granted_at` ascending, and where two grants share the same
    logical-clock instant, by `created_at` ascending."
    PRD §3.9: "Filing the request forces the unit's posture to `FROZEN` and
    increments the unit's `version` by 1; from there the freeze cascade runs as
    always, suspending the unit's `PARTIALLY_APPROVED` and `ACTIVE`
    participations and cancelling their future planned attendances."

    Design: Difficulty/combinatorial_formula/leniency_penalty_round_per_year_then_sum
    """
    set_clock()
    scene = _two_ranked_units()

    submit_disclosure(scene["app_y"]["id"], 15)

    assert read_application(scene["app_x"]["id"])["priority_rank"] == 1
    assert read_application(scene["app_y"]["id"])["priority_rank"] == 2
    assert read_business_unit(scene["unit_y"]["id"])["posture"] == "FROZEN"


def test_disclosure_submits_while_the_marker_is_only_requested(api):
    """PRD §3.9: "Submission requires `marker_status` to be `MARKER_REQUESTED`
    or `MARKER_GRANTED`, and is refused with `ERR_MARKER_NOT_GRANTED` otherwise:
    a disclosure may legitimately be filed while the marker is still merely
    requested, but never before a request and never after the marker has been
    denied or has expired. Submission leaves `marker_status` alone."
    PRD §3.9: "**Step four** reads the leniency reduction off the queue
    position: 100 percent for rank 1, 50 percent for rank 2, 30 percent for rank
    3, and 0 percent for any rank beyond 3 or for a null rank."

    Design: Difficulty/non_linear_state_machine/leniency_marker_and_disclosure_dimensions_advance_independently
    """
    set_clock()
    banded = setup_high_band_unit(name="Adhesives Z", market_code="EU-ADHES")
    application = open_leniency_application(
        banded["unit"]["id"], "EU-ADHES-2022", THREE_AFFECTED_YEARS)
    request_marker(application["id"])

    data = validate_success(api.submit_disclosure(
        application["id"], disclosure_submission_payload(12), COUNSEL))

    assert data["disclosure_status"] == "SUBMITTED"
    assert data["marker_status"] == "MARKER_REQUESTED", (
        "submission leaves the marker dimension alone")
    assert data["priority_rank"] is None
    assert data["estimated_penalty_cents"] == 864000013, (
        "720000011 base at the 1.20 uplift with no rank reduction")


def test_marker_grant_reprices_and_an_accepted_disclosure_perfects(api):
    """PRD §3.9: "A `decision` of `GRANTED` moves `MARKER_REQUESTED →
    MARKER_GRANTED`, stamps `marker_granted_at` with the current logical clock,
    computes `priority_rank`, and recomputes `estimated_penalty_cents` if
    `gravity_pct` has already been recorded."
    PRD §3.9: "The instant `disclosure_status` becomes `ACCEPTED`, if
    `marker_status` is `MARKER_GRANTED` it advances to `PERFECTED` in that same
    request, retaining both `priority_rank` and `estimated_penalty_cents`."

    Design: Difficulty/non_linear_state_machine/leniency_marker_and_disclosure_dimensions_advance_independently
    """
    set_clock()
    banded = setup_high_band_unit(name="Adhesives Z", market_code="EU-ADHES")
    application = open_leniency_application(
        banded["unit"]["id"], "EU-ADHES-2022", THREE_AFFECTED_YEARS)
    request_marker(application["id"])
    submit_disclosure(application["id"], 12)

    granted = decide_marker(application["id"], "GRANTED")
    assert granted["priority_rank"] == 1
    assert granted["estimated_penalty_cents"] == 0, "first through the door pays nothing"

    accepted = validate_success(api.decide_disclosure(
        application["id"], {"decision": "ACCEPTED"}, ADMIN))
    assert accepted["marker_status"] == "PERFECTED"
    assert accepted["disclosure_status"] == "ACCEPTED"
    assert accepted["estimated_penalty_cents"] == 0
    assert read_business_unit(banded["unit"]["id"])["posture"] == "FROZEN"


def test_marker_request_is_refused_below_the_high_band(api):
    """PRD §3.9: "It is permitted only when the unit has an `ACTIVE` risk
    assessment whose `risk_band` is `HIGH` or `SEVERE` — an absent assessment or
    a lower band is refused with `ERR_RISK_BAND_TOO_LOW`"
    PRD §3.3: "The `risk_band` follows from the index with lower edges inclusive
    and upper edges exclusive: `LOW` below 25, `MODERATE` from 25 up to but not
    including 50, `HIGH` from 50 up to but not including 75, and `SEVERE` at 75
    and above."

    Design: Difficulty/cross_entity_state_dependency/marker_request_requires_high_or_severe_risk_band
    """
    set_clock()
    unit = register_business_unit(name="Low Risk Unit", market_code="EU-COAT",
                                  market_share_bps=1200, interaction_point_count=4,
                                  competitor_overlap_pct=25)
    assessment = run_assessment(unit["id"], "BASELINE")
    assert assessment["market_risk_index"] == 27.00
    assert assessment["risk_band"] == "MODERATE"
    application = open_leniency_application(unit["id"], "EU-COAT-2024")

    resp = api.request_marker(application["id"], COUNSEL)

    validate_error(resp, ApiErrorId.ERR_RISK_BAND_TOO_LOW.value)
    assert resp.status_code == 422
    assert read_application(application["id"])["marker_status"] == "NONE"
    assert read_business_unit(unit["id"])["posture"] == "OPEN"


def test_marker_request_at_the_high_band_freezes_the_unit(api):
    """PRD §3.9: "Requesting a marker moves `marker_status` from `NONE` to
    `MARKER_REQUESTED` and stamps `marker_requested_at` with the current logical
    clock."
    PRD §3.9: "Filing the request forces the unit's posture to `FROZEN` and
    increments the unit's `version` by 1; from there the freeze cascade runs as
    always, suspending the unit's `PARTIALLY_APPROVED` and `ACTIVE`
    participations and cancelling their future planned attendances."

    Design: Difficulty/cross_entity_state_dependency/marker_request_requires_high_or_severe_risk_band
    """
    set_clock()
    unit = register_business_unit(name="High Risk Unit", market_code="EU-COAT",
                                  market_share_bps=5000, interaction_point_count=0,
                                  competitor_overlap_pct=0)
    assessment = run_assessment(unit["id"], "BASELINE")
    assert assessment["market_risk_index"] == 70.00
    assert assessment["risk_band"] == "HIGH"
    application = open_leniency_application(unit["id"], "EU-COAT-2024")

    data = validate_success(api.request_marker(application["id"], COUNSEL))

    assert data["marker_status"] == "MARKER_REQUESTED"
    assert read_business_unit(unit["id"])["posture"] == "FROZEN"


def test_second_marker_on_the_same_cartel_and_unit_is_refused(api):
    """PRD §3.9: "and only when no other application of the same unit and the
    same `cartel_code` already stands in `MARKER_REQUESTED`, `MARKER_GRANTED` or
    `PERFECTED`, which is refused with `ERR_MARKER_ALREADY_HELD`."
    PRD §2.7: "**Marker uniqueness.** No other leniency application of the same
    business unit and the same `cartel_code` has a `marker_status` of
    `MARKER_REQUESTED`, `MARKER_GRANTED` or `PERFECTED` — otherwise
    `ERR_MARKER_ALREADY_HELD`, HTTP 409."

    Design: Corner/errors/marker_already_held_for_same_cartel_and_unit_is_refused
    """
    set_clock()
    banded = setup_high_band_unit(name="Double Marker Unit", market_code="EU-DM")
    first = open_leniency_application(banded["unit"]["id"], "EU-DM-2021")
    second = open_leniency_application(banded["unit"]["id"], "EU-DM-2021")
    request_marker(first["id"])

    resp = api.request_marker(second["id"], COUNSEL)

    validate_error(resp, ApiErrorId.ERR_MARKER_ALREADY_HELD.value)
    assert resp.status_code == 409
    assert read_application(first["id"])["marker_status"] == "MARKER_REQUESTED"
    assert read_application(second["id"])["marker_status"] == "NONE"
    assert read_business_unit(banded["unit"]["id"])["posture"] == "FROZEN"


def test_withdrawal_surrenders_an_outstanding_marker_and_thaws_to_restricted(api):
    """PRD §3.9: "**Withdrawal.** Counsel may withdraw from `DRAFT` or from
    `SUBMITTED`, supplying a `reason` that lands in `withdrawal_reason` and
    moving `disclosure_status` to the terminal `WITHDRAWN`. Withdrawal is the
    one act that crosses the dimensions in the other direction: a
    `marker_status` of `MARKER_REQUESTED` or `MARKER_GRANTED` is set to
    `MARKER_DENIED` in the same request, `priority_rank` is nulled, the unit's
    posture is recomputed and its `version` increments by 1."
    PRD §2.8: "Otherwise the posture is `RESTRICTED` when `exposure_points` is
    at least 40.00, **or** when `risk_band` is `HIGH` or `SEVERE`."

    Design: Corner/state_machines/leniency_withdrawal_surrenders_an_outstanding_marker
    """
    set_clock()
    banded = setup_high_band_unit(name="Withdrawal Unit", market_code="EU-WD")
    application = open_leniency_application(banded["unit"]["id"], "EU-WD-2021")
    request_marker(application["id"])
    decide_marker(application["id"], "GRANTED")
    submit_disclosure(application["id"], 15)
    assert read_application(application["id"])["priority_rank"] == 1
    assert read_business_unit(banded["unit"]["id"])["posture"] == "FROZEN"

    data = validate_success(api.withdraw_application(
        application["id"],
        withdrawal_payload("Second-look review found no cartel conduct"), COUNSEL))

    assert data["disclosure_status"] == "WITHDRAWN"
    assert data["marker_status"] == "MARKER_DENIED"
    assert data["priority_rank"] is None
    stored_unit = read_business_unit(banded["unit"]["id"])
    assert stored_unit["posture"] == "RESTRICTED"
    assert stored_unit["risk_band"] == "HIGH"


def test_application_back_reference_to_the_contact_that_surfaced_it(api):
    """PRD §3.9: "An optional `source_contact_id` back-references the
    contact-log entry that surfaced the conduct; it is left null when the
    application originates from a minutes review or an internal audit instead."
    PRD §3.9: "The application opens with `marker_status` of `NONE` and
    `disclosure_status` of `DRAFT`, with `gravity_pct`, `priority_rank`,
    `estimated_penalty_cents`, `marker_requested_at`, `marker_granted_at` and
    `withdrawal_reason` all null."
    PRD §3.9: "Applications may be listed filtered by unit, `cartel_code`,
    `source_contact_id`, `marker_status` and `disclosure_status`."

    Design: Corner/endpoints/leniency_list_filtered_by_source_contact_id_resolves_the_back_reference
    """
    set_clock()
    unit = register_business_unit(exposure_budget_points=200)
    employee = register_employee(unit["id"], role_category="LEGAL")
    contact = log_and_escalate_contact(unit["id"], employee["id"])

    data = validate_success(api.create_leniency_application(
        create_leniency_application_payload(
            unit["id"], CARTEL, source_contact_id=contact["id"]),
        COUNSEL), 201)

    assert data["source_contact_id"] == contact["id"]
    assert data["marker_status"] == "NONE"
    assert data["disclosure_status"] == "DRAFT"
    assert data["priority_rank"] is None
    assert data["estimated_penalty_cents"] is None

    rows, meta = validate_paginated(api.list_leniency_applications(
        COUNSEL, params={"source_contact_id": contact["id"]}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [data["id"]]

    unresolved = api.create_leniency_application(
        create_leniency_application_payload(
            unit["id"], "EU-RESIN-2022", source_contact_id=UNKNOWN_UUID),
        COUNSEL)
    validate_error(unresolved, ApiErrorId.ERR_CONTACT_NOT_FOUND.value)
    assert unresolved.status_code == 404

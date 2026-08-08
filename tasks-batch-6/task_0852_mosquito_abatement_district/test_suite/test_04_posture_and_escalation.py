"""Risk posture derivation, assessment confirmation, and the positive-detection
cascade into the complaint queue."""

import test_helpers as fx
from test_helpers import (
    ECOLOGIST,
    LAB,
    ApiErrorId,
    validate_error,
    validate_success,
)


def test_confirmed_index_of_exactly_seventy_lands_on_emergency(api):
    """PRD §3.6: "Both thresholds are inclusive on the low side, so exactly `40.00`
    is `ELEVATED` and exactly `70.00` is `EMERGENCY`."
    PRD §3.6: "It is `POSITIVE_OVERRIDE` when the override reading outranks the
    index reading."

    Design: Corner/calculations/corner_posture_reaches_emergency_at_index_exactly_seventy
    """
    scenario = fx.setup_single_positive_pool_assessment(
        female_count=105, trap_nights=4, ct_value=24.0, species="CULEX_TARSALIS"
    )

    confirmed = validate_success(
        api.confirm_risk_assessment(scenario["assessment"]["id"], ECOLOGIST)
    )

    fx.assert_index(confirmed["abundance_index"], 26.25, "abundance_index")
    fx.assert_index(confirmed["vector_index_confirmed"], 70.00, "vector_index_confirmed")
    assert confirmed["posture_at_confirm"] == "EMERGENCY"

    area = fx.read_area(scenario["area"]["id"])
    assert area["risk_posture"] == "EMERGENCY"
    assert area["posture_source"] == "INDEX"
    fx.assert_index(
        area["latest_confirmed_vector_index"], 70.00, "latest_confirmed_vector_index"
    )


def test_escalation_never_lowers_an_urgent_priority(api):
    """PRD §3.6: "Every complaint of the area whose handling status is `RECEIVED`,
    `TRIAGED`, `ASSIGNED`, or `INSPECTED` — processed in ascending `created_at`
    order, though the order has no observable effect because the rows are
    independent — has its `priority` set to the higher-ranked of its current
    priority and the new floor."
    PRD §3.6: "Priority is strictly monotone: escalation never lowers a priority,
    and a *later* posture drop never lowers one either — nothing in this system
    reduces a complaint's `priority` once it has been raised, not even reopening
    it."

    Design: Corner/calculations/corner_posture_escalation_never_lowers_an_urgent_priority
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"])
    collection = fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=2, female_count=20
    )
    pool = fx.pool_in_testing(collection["id"], 20)
    request = fx.file_request(
        area["id"], category="ADULT_ACTIVITY", description="Severe biting", x_m=10, y_m=10
    )
    triaged = fx.request_action(request["id"], "TRIAGE", priority="URGENT")
    assert triaged["due_at"] == "2026-06-02T00:00:00.000Z"

    validate_success(
        api.transition_lab_pool(
            pool["id"], {"action": "RESULT", "result": "POSITIVE", "ct_value": 31.0}, LAB
        )
    )

    refreshed_area = fx.read_area(area["id"])
    assert refreshed_area["risk_posture"] == "ELEVATED"
    assert refreshed_area["posture_source"] == "POSITIVE_OVERRIDE"

    refreshed_request = fx.read_request(request["id"])
    assert refreshed_request["priority"] == "URGENT"
    assert refreshed_request["due_at"] == "2026-06-02T00:00:00.000Z"


def test_newly_confirmed_assessment_rebases_the_posture_input(api):
    """PRD §3.6: "It moves any *other* assessment of the same area whose status was
    `CONFIRMED` to `SUPERSEDED`, so an area has at most one live confirmed
    assessment."
    PRD §3.6: "It is `NO_ASSESSMENT` when no assessment of the area has ever been
    confirmed and the override did not outrank the index reading. Otherwise it is
    `INDEX`."

    Design: Corner/cross_cutting_complexity_layers/corner_rate_threshold_reset_after_new_confirmed_assessment
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator()
    site = fx.create_trap_site(area["id"])
    fx.log_and_submit_collection(
        site["id"], tech["id"], collection_date="2026-05-28", trap_nights=2, female_count=60
    )
    first = fx.open_assessment(area["id"], "2026-06-01")
    first_confirmed = fx.confirm_assessment(first["id"])
    fx.assert_index(
        first_confirmed["vector_index_confirmed"], 24.00, "vector_index_confirmed"
    )

    fx.set_clock("2026-06-20T00:00:00.000Z")
    second = fx.open_assessment(area["id"], "2026-06-20")

    second_confirmed = validate_success(
        api.confirm_risk_assessment(second["id"], ECOLOGIST)
    )

    fx.assert_index(
        second_confirmed["vector_index_confirmed"], 0.00, "vector_index_confirmed"
    )
    fx.assert_index(second_confirmed["abundance_index"], 0.00, "abundance_index")
    assert second_confirmed["status"] == "CONFIRMED"
    assert fx.read_assessment(first["id"])["status"] == "SUPERSEDED"

    refreshed_area = fx.read_area(area["id"])
    fx.assert_index(
        refreshed_area["latest_confirmed_vector_index"], 0.00,
        "latest_confirmed_vector_index",
    )
    assert refreshed_area["risk_posture"] == "NORMAL"
    assert refreshed_area["posture_source"] == "INDEX"


def test_new_assessment_supersedes_the_prior_open_assessment(api):
    """PRD §3.5: "Any *other* assessment of the same area that was still `OPEN` is
    moved to `SUPERSEDED` as a system transition, keeping its own provisional
    numbers untouched as a historical record with no recomputation. The area's
    `version` increases by 1."

    Design: Corner/state_machines/corner_new_assessment_supersedes_prior_open_assessment
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    version_before = fx.area_version(area["id"])
    first = fx.open_assessment(area["id"], "2026-06-01")
    version_after_first = fx.area_version(area["id"])

    second = validate_success(
        api.create_risk_assessment(
            area["id"],
            {"as_of_date": "2026-06-02", "expected_service_area_version": version_after_first},
            ECOLOGIST,
        ),
        201,
    )

    assert fx.read_assessment(first["id"])["status"] == "SUPERSEDED"
    assert second["status"] == "OPEN"
    assert second["as_of_date"] == "2026-06-02"
    assert version_after_first == version_before + 1
    assert fx.read_area(area["id"])["risk_posture"] == "NORMAL"


def test_confirming_an_already_confirmed_assessment_is_rejected(api):
    """PRD §3.6: "The assessment must be `OPEN`; confirming one that is already
    `CONFIRMED` or `SUPERSEDED` is refused with `ERR_ASSESSMENT_NOT_OPEN` (HTTP
    409)."
    PRD §3.6: "It stamps `confirmed_at` with the logical clock."

    Design: Corner/state_machines/corner_confirm_already_confirmed_assessment_rejected
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    assessment = fx.open_assessment(area["id"], "2026-06-01")
    fx.confirm_assessment(assessment["id"])
    fx.set_clock("2026-06-02T00:00:00.000Z")

    response = api.confirm_risk_assessment(assessment["id"], ECOLOGIST)
    validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_OPEN.value, 409)

    refreshed = fx.read_assessment(assessment["id"])
    assert refreshed["status"] == "CONFIRMED"
    assert refreshed["confirmed_at"] == "2026-06-01T00:00:00.000Z"


def test_positive_result_cascades_into_collection_trap_site_and_assessment(api):
    """PRD §3.4: "Because that pool resulted positive, the parent collection's
    `positive_pool_count` increases by 1 and its `wnv_detected` becomes true — and
    `wnv_detected` is true precisely when `positive_pool_count` is 1 or more."
    PRD §3.4: "Because that collection now shows a detection, the trap site's
    `season_positive_count` increases by 1 and its `last_positive_at` is stamped
    with the logical clock."
    PRD §3.4: "Because that trap site has just recorded a fresh positive, every
    risk assessment of the site's service area whose status is `OPEN` gets
    `is_stale` true with `stale_reason` of `LAB_RESULT`."

    Design: Difficulty/transitive_cascade/lab_positive_cascades_five_hops_to_service_request_priority
    """
    scenario = fx.setup_positive_cascade_scenario()

    pool = validate_success(
        api.transition_lab_pool(
            scenario["pool"]["id"],
            {"action": "RESULT", "result": "POSITIVE", "ct_value": 27.1},
            LAB,
        )
    )

    assert pool["status"] == "RESULT_POSITIVE"
    assert pool["result_recorded_at"] == "2026-06-01T00:00:00.000Z"

    collection = fx.read_collection(scenario["collection"]["id"])
    assert collection["positive_pool_count"] == 1
    assert collection["wnv_detected"] is True

    trap_site = fx.read_trap_site(scenario["trap_site"]["id"])
    assert trap_site["season_positive_count"] == 1
    assert trap_site["last_positive_at"] == "2026-06-01T00:00:00.000Z"

    assessment = fx.read_assessment(scenario["assessment"]["id"])
    assert assessment["is_stale"] is True
    assert assessment["stale_reason"] == "LAB_RESULT"
    assert assessment["status"] == "OPEN"
    fx.assert_index(
        assessment["vector_index_provisional"], 24.00, "vector_index_provisional"
    )


def test_positive_result_escalates_posture_and_recomputes_complaint_due_date(api):
    """PRD §3.4: "Because a laboratory positive now exists inside the area's 14-day
    escalation horizon, the area's `risk_posture` and `posture_source` are
    recomputed from scratch by the posture rule of §3.6."
    PRD §3.4: "And finally, because the area's posture may have escalated, every
    complaint of that area whose handling status is `RECEIVED`, `TRIAGED`,
    `ASSIGNED`, or `INSPECTED` has its `priority` raised to the floor the new
    posture implies, and — for any such complaint whose `triaged_at` is not null —
    its `due_at` is recomputed from that unchanged `triaged_at` against the new
    priority."
    PRD §3.10: "a `ROUTINE` complaint is due 120 hours after triage — five days — a
    `PRIORITY` complaint 48 hours after triage, and an `URGENT` complaint 24 hours
    after triage."

    Design: Difficulty/transitive_cascade/lab_positive_cascades_five_hops_to_service_request_priority
    """
    scenario = fx.setup_positive_cascade_scenario()
    assert scenario["request"]["due_at"] == "2026-06-06T00:00:00.000Z"

    validate_success(
        api.transition_lab_pool(
            scenario["pool"]["id"],
            {"action": "RESULT", "result": "POSITIVE", "ct_value": 27.1},
            LAB,
        )
    )

    area = fx.read_area(scenario["area"]["id"])
    assert area["risk_posture"] == "ELEVATED"
    assert area["posture_source"] == "POSITIVE_OVERRIDE"
    fx.assert_index(
        area["latest_confirmed_vector_index"], 0.00, "latest_confirmed_vector_index"
    )

    request = fx.read_request(scenario["request"]["id"])
    assert request["priority"] == "PRIORITY"
    assert request["triaged_at"] == "2026-06-01T00:00:00.000Z"
    assert request["due_at"] == "2026-06-03T00:00:00.000Z"
    assert request["handling_status"] == "TRIAGED"

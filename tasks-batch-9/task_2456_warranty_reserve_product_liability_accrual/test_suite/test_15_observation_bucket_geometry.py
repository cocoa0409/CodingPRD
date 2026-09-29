"""Half-open development buckets, scoped to one cohort-and-mode pair.

PRD §3.2: "the bucket spans from `months_in_service_from` inclusive to
`months_in_service_to` exclusive ... Adjacency is therefore perfectly legal."
"""

from test_helpers import (
    ANALYST_HEADERS,
    ERR_OBSERVATION_WINDOW_OVERLAP,
    create_failure_mode,
    create_family,
    create_observation,
    create_period,
    create_vintage,
    factories,
    read_family,
    success_data,
    validate_error,
    validate_paginated,
)


def _build_world(api):
    """One cohort, two failure modes, and a [0, 12) bucket already on the first mode."""
    create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-R",
        name="Range Hood Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=16000,
        reserve_cap_cents=40000000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="R-MY2024",
        units_shipped=8000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    first_mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-R-01",
        description="Blower motor seizure",
        severity="FUNCTIONAL",
        cost_per_claim_cents=16000,
    )
    second_mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-R-02",
        description="Filter latch fracture",
        severity="COSMETIC",
        cost_per_claim_cents=3000,
    )
    existing = create_observation(
        api,
        vintage["id"],
        first_mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=12,
        claim_count=40,
        paid_cost_cents=640000,
    )
    return {
        "family": family,
        "vintage": vintage,
        "first_mode": first_mode,
        "second_mode": second_mode,
        "existing": existing,
    }


def _append(api, vintage_id, mode_id, months_from, months_to, claim_count, paid_cost_cents):
    payload = factories.claim_observation_payload(
        vintage_id,
        mode_id,
        observation_period_code="2026-Q3",
        months_in_service_from=months_from,
        months_in_service_to=months_to,
        claim_count=claim_count,
        paid_cost_cents=paid_cost_cents,
    )
    return api.create_claim_observation_raw(ANALYST_HEADERS, payload)


def test_a_bucket_starting_where_the_previous_one_ends_is_accepted(api):
    """Touching at month 12 is adjacency, not intersection.

    PRD §3.2: "two buckets intersect exactly when the new bucket's lower bound is
    strictly less than the existing bucket's upper bound and the existing bucket's lower
    bound is strictly less than the new bucket's upper bound. Adjacency is therefore
    perfectly legal. Against an existing bucket running from 0 to 12, a new bucket from
    12 to 24 is accepted".

    Design: Difficulty/resource_temporal_overlap/half_open_months_in_service_buckets_touch_without_overlapping
    """
    world = _build_world(api)

    response = _append(api, world["vintage"]["id"], world["first_mode"]["id"], 12, 24, 30, 480000)
    observation = success_data(response, expected_status=201)

    assert observation["months_in_service_from"] == 12
    assert observation["months_in_service_to"] == 24


def test_a_straddling_bucket_and_an_exact_repeat_are_both_refused(api):
    """Overlapping by one month on each side, and repeating outright, both conflict.

    PRD §3.2: "while a bucket from 11 to 13 is refused and an exact repeat of 0 to 12 is
    refused, both with `ERR_OBSERVATION_WINDOW_OVERLAP`." PRD §2.9 rung 32 gives the
    status: "Development-bucket non-overlap on claim observations — guarding
    `POST /warranty/claim-observations` — otherwise `ERR_OBSERVATION_WINDOW_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/half_open_months_in_service_buckets_touch_without_overlapping
    """
    world = _build_world(api)
    _append(api, world["vintage"]["id"], world["first_mode"]["id"], 12, 24, 30, 480000)

    straddling = _append(api, world["vintage"]["id"], world["first_mode"]["id"], 11, 13, 5, 80000)
    validate_error(straddling, ERR_OBSERVATION_WINDOW_OVERLAP, expected_status=409)

    repeat = _append(api, world["vintage"]["id"], world["first_mode"]["id"], 0, 12, 40, 640000)
    validate_error(repeat, ERR_OBSERVATION_WINDOW_OVERLAP, expected_status=409)


def test_the_same_straddling_bucket_is_legal_under_a_different_failure_mode(api):
    """The non-overlap scope key is the cohort together with the failure mode.

    PRD §3.2: "A new bucket must not intersect the bucket of any existing observation
    sharing the same cohort *and* the same failure mode ... Buckets belonging to a
    different cohort, or to the same cohort but a different failure mode, never
    conflict." PRD §3.2 then reads all of them for exposure: `observed_history_months`
    "is the largest `months_in_service_to` found across all such observations", and
    "every observation row counts".

    Design: Difficulty/resource_temporal_overlap/half_open_months_in_service_buckets_touch_without_overlapping
    """
    world = _build_world(api)
    _append(api, world["vintage"]["id"], world["first_mode"]["id"], 12, 24, 30, 480000)
    _append(api, world["vintage"]["id"], world["first_mode"]["id"], 11, 13, 5, 80000)

    response = _append(api, world["vintage"]["id"], world["second_mode"]["id"], 11, 13, 5, 15000)
    observation = success_data(response, expected_status=201)
    assert observation["months_in_service_from"] == 11
    assert observation["months_in_service_to"] == 13

    _, meta = validate_paginated(
        api.list_claim_observations(ANALYST_HEADERS, vintage_id=world["vintage"]["id"])
    )
    assert meta["total_count"] == 3

    family = read_family(api, world["family"]["id"])
    assert family["observed_history_months"] == 24
    assert family["observed_exposure_units"] == 8000

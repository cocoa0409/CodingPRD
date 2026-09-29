"""Boundaries that are decided by equality: envelopes, deadlines, scores, ceilings.

Every test builds its own commission out of the endpoints the PRD declares, so
it opens against an empty database with the logical clock at its documented
default of 2026-08-01T00:00:00Z, and each figure under test is placed exactly on
its limit, one step inside it or one step outside it.
"""

import pytest

from test_helpers import (
    ACCESSIBILITY,
    CONSERVATOR,
    CURATOR,
    ERR_ACCESSIBILITY_REQUIREMENTS_UNMET,
    ERR_DEADLINE_IN_PAST,
    ERR_ENV_ENVELOPE_INFEASIBLE,
    ERR_INVALID_MATERIAL_STATE,
    ERR_OFFGASSING_LIMIT_EXCEEDED,
    ERR_ROUND_DEADLINE_PASSED,
    FABRICATION,
    OBJECTIVE_PRIMARY,
    PM,
    CaseStatus,
    MaterialDecision,
    MaterialStatus,
    OddyResult,
    PackageStage,
    PackageStatus,
    Phase,
    Posture,
    RoundStatus,
    SecurityTier,
    USER_ACCESSIBILITY,
    UsedIn,
    Verdict,
    VoteDecision,
    assert_counters,
    assert_envelope,
    assert_geometry,
    assert_index,
    assert_unchanged,
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _read_case(api, case_id, headers=PM):
    return get_success_data(api.get_artifact_case(case_id, headers), 200)


def _read_round(api, round_id, headers=PM):
    return get_success_data(api.get_review_round(round_id, headers), 200)


def _read_package(api, package_id, headers=PM):
    return get_success_data(api.get_design_package(package_id, headers), 200)


# ---------------------------------------------------------------------------
# Three inclusive equalities at once still leave the envelope feasible
# ---------------------------------------------------------------------------
def _case_and_three_objects_on_the_limit(api):
    """A case at 50 percent RH plus or minus 2 and 50 lux, and three candidates.

    The first object is generous on every axis, the second squeezes the humidity
    band to exactly the case's own excursion, and the third asks for one lux
    less than the case is designed to deliver.
    """
    fx.set_clock(api)
    project = fx.create_project(api)
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    zone = fx.create_zone(api, project_id)
    case = fx.create_case(
        api,
        project_id,
        zone["id"],
        case_code="C-01",
        objective_code=OBJECTIVE_PRIMARY,
        security_tier=SecurityTier.ENHANCED,
        target_rh_pct=50.0,
        rh_tolerance_pct=2.0,
        target_lux=50.0,
        uv_microwatt_per_lumen=20.0,
        interior_l_cm=120.0,
        interior_w_cm=60.0,
        interior_h_cm=90.0,
        air_exchanges_per_day=0.4,
    )
    wide = fx.create_artifact(
        api,
        project_id,
        accession_number="2022.3.1",
        required_rh_min_pct=45.0,
        required_rh_max_pct=55.0,
        max_lux=50.0,
        security_class=SecurityTier.ENHANCED,
    )
    exact = fx.create_artifact(
        api,
        project_id,
        accession_number="2022.3.2",
        required_rh_min_pct=48.0,
        required_rh_max_pct=52.0,
        max_lux=50.0,
        security_class=SecurityTier.ENHANCED,
    )
    one_lux_darker = fx.create_artifact(
        api,
        project_id,
        accession_number="2022.3.3",
        required_rh_min_pct=48.0,
        required_rh_max_pct=52.0,
        max_lux=49.0,
        security_class=SecurityTier.ENHANCED,
    )
    return {
        "project_id": project_id,
        "zone_id": zone["id"],
        "case": case,
        "case_id": case["id"],
        "wide_id": wide["id"],
        "exact_id": exact["id"],
        "darker_id": one_lux_darker["id"],
    }


def test_the_case_geometry_rounds_the_volume_to_four_places_and_the_silica_to_two(api):
    """A 120 by 60 by 90 centimetre interior at 0.4 air exchanges a day.

    The interior is 648,000 cubic centimetres, so the volume is 0.648 cubic
    metres, and the silica charge computed from the already-rounded volume is
    0.9072 kilograms before rounding, which lands on 0.91.

    PRD section 3.4: "`case_volume_m3` is the product of the three interior dimensions in centimetres divided by 1,000,000 — the number of cubic centimetres in a cubic metre — rounded half up to four decimal places."

    PRD section 3.4: "`silica_gel_kg` is the conditioned silica-gel charge needed to hold the setpoint: the already-rounded cubic-metre volume multiplied by `air_exchanges_per_day` multiplied by 3.5 kilograms per cubic metre per daily air exchange, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/three_simultaneous_inclusive_equalities_keep_the_case_envelope_feasible
    """
    ctx = _case_and_three_objects_on_the_limit(api)
    assert_geometry(ctx["case"], case_volume_m3=0.648, silica_gel_kg=0.91)

    stored = _read_case(api, ctx["case_id"])
    assert_geometry(stored, case_volume_m3=0.648, silica_gel_kg=0.91)


def test_three_limits_met_by_exact_equality_keep_the_envelope_feasible(api):
    """The derived band is 48 to 52 and the derived ceiling is exactly 50 lux.

    The case's setpoint less its tolerance equals the derived floor, its setpoint
    plus its tolerance equals the derived ceiling, and its designed illuminance
    equals the strictest allowance; all three comparisons are inclusive, so the
    envelope holds.

    PRD section 3.4: "When it is not empty, `required_rh_min_pct` becomes the **largest** of the objects' individual humidity floors, `required_rh_max_pct` becomes the **smallest** of their humidity ceilings, and `allowed_lux` becomes the **smallest** of their `max_lux` values."

    PRD section 3.4: "Every one of those comparisons is inclusive, so a case whose `target_lux` exactly equals the strictest `allowed_lux` passes."

    Design: Difficulty/boundary_precision_check/three_simultaneous_inclusive_equalities_keep_the_case_envelope_feasible
    """
    ctx = _case_and_three_objects_on_the_limit(api)
    fx.place_artifact(api, ctx["case_id"], ctx["wide_id"])
    fx.place_artifact(api, ctx["case_id"], ctx["exact_id"])

    case = _read_case(api, ctx["case_id"])
    assert_envelope(
        case,
        placed_artifact_count=2,
        required_rh_min_pct=48.0,
        required_rh_max_pct=52.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )


def test_one_lux_below_the_designed_illuminance_makes_the_envelope_infeasible(api):
    """A third object tolerating 49 lux against a case designed for 50 is refused.

    The envelope is recomputed with the incoming object included, which drops the
    derived ceiling one lux below the case's designed illuminance and breaks an
    otherwise satisfied envelope, so nothing is stored.

    PRD section 3.4: "The chain of admission tests is: the case's conservation status must be `DRAFT` or `REJECTED`, since a case already under review or already ruled on refuses with `ERR_INVALID_CASE_STATE`; the object must be `UNPLACED`, because an object already `RESERVED`, `PLACED` or `DEINSTALLED` answers `ERR_ARTIFACT_ALREADY_PLACED` (HTTP 409); the object's `condition_status` must not be `UNSTABLE`, since an unstable object may not be committed to a case until conservation stabilises it, and the attempt answers `ERR_ARTIFACT_CONDITION_UNSTABLE` (HTTP 422); the case's security tier must rank at or above the object's security class, so a `HIGH_VALUE` object cannot go into an `ENHANCED` or `BASIC` case and the attempt answers `ERR_SECURITY_TIER_INSUFFICIENT` (HTTP 422); and finally the envelope recomputed **with the incoming object included** must remain feasible, or the attempt answers `ERR_ENV_ENVELOPE_INFEASIBLE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/three_simultaneous_inclusive_equalities_keep_the_case_envelope_feasible
    """
    ctx = _case_and_three_objects_on_the_limit(api)
    fx.place_artifact(api, ctx["case_id"], ctx["wide_id"])
    fx.place_artifact(api, ctx["case_id"], ctx["exact_id"])
    before = _read_case(api, ctx["case_id"])

    validate_error(
        api.create_placement(
            ctx["case_id"],
            f.placement_payload(ctx["darker_id"], before["version"]),
            CURATOR,
        ),
        ERR_ENV_ENVELOPE_INFEASIBLE,
        422,
    )

    after = _read_case(api, ctx["case_id"])
    assert_unchanged(
        before,
        after,
        ["version", "placed_artifact_count", "allowed_lux", "env_feasible"],
    )
    assert_envelope(after, placed_artifact_count=2, allowed_lux=50.0, env_feasible=True)


def test_the_case_on_its_limits_goes_to_the_conservators_with_that_envelope(api):
    """Submission recomputes the envelope immediately before the transition.

    The two-object case is feasible only by equality on three axes, and it still
    reaches conservator review with exactly those derived numbers.

    PRD section 3.5: "An empty case has no envelope to review, so submission requires `placed_artifact_count` of at least 1 and otherwise fails with `ERR_CASE_HAS_NO_ARTIFACTS` (HTTP 422); the project must not be in `FROZEN_CONSERVATION`; and the envelope is recomputed immediately before the transition so the conservator rules on current numbers."

    Design: Difficulty/boundary_precision_check/three_simultaneous_inclusive_equalities_keep_the_case_envelope_feasible
    """
    ctx = _case_and_three_objects_on_the_limit(api)
    fx.place_artifact(api, ctx["case_id"], ctx["wide_id"])
    fx.place_artifact(api, ctx["case_id"], ctx["exact_id"])

    submitted = fx.submit_case(api, ctx["case_id"])
    assert submitted["status"] == CaseStatus.CONSERVATOR_REVIEW
    assert_envelope(
        submitted,
        placed_artifact_count=2,
        required_rh_min_pct=48.0,
        required_rh_max_pct=52.0,
        allowed_lux=50.0,
        env_feasible=True,
        security_ok=True,
    )


# ---------------------------------------------------------------------------
# The deadline instant belongs to the sweep, not to the voter
# ---------------------------------------------------------------------------
DEADLINE = "2026-08-15T00:00:00Z"
ONE_SECOND_BEFORE_DEADLINE = "2026-08-14T23:59:59Z"
ONE_SECOND_AFTER_DEADLINE = "2026-08-15T00:00:01Z"
PANEL_OF_THREE = ["Curator", "Conservator", "FabricationLead"]


def _package_in_review_with_one_vote_and_a_deadline(api):
    """A DESIGN_DEV package under review with one approval and a three-seat panel.

    Quorum is two votes and only the Curator has voted, so the round is still
    open and its fate rests entirely on what happens at the deadline instant.
    """
    fx.set_clock(api)
    project = fx.create_project(api)
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    package = fx.create_package(api, project_id, stage=PackageStage.DESIGN_DEV)
    review_round = fx.open_round(
        api,
        package["id"],
        panel_roles=PANEL_OF_THREE,
        decision_deadline_at=DEADLINE,
    )
    assert review_round["required_vote_count"] == 2
    fx.cast_vote(api, review_round["id"], CURATOR, VoteDecision.APPROVE)
    return {
        "project_id": project_id,
        "package_id": package["id"],
        "round_id": review_round["id"],
    }


def test_the_sweep_one_second_before_the_deadline_lapses_nothing(api):
    """At 23:59:59 the deadline has not been reached, so the round survives.

    The sweep only lapses rounds whose deadline is at or before the clock, and
    one second short of it the round is still open with its single vote and no
    decision recorded.

    PRD section 3.3: "Every round of that project that is still `OPEN` and whose `decision_deadline_at` is at or before the current logical-clock instant is lapsed, and the qualifying rounds are processed in ascending order of `decision_deadline_at` with `created_at` ascending as the tie-break, so the sweep's effects are order-deterministic."

    Design: Difficulty/boundary_precision_check/the_deadline_instant_belongs_to_the_sweep_and_not_to_the_voter
    """
    ctx = _package_in_review_with_one_vote_and_a_deadline(api)
    fx.set_clock(api, ONE_SECOND_BEFORE_DEADLINE)

    get_success_data(api.review_sweep(ctx["project_id"], PM), 200)

    review_round = _read_round(api, ctx["round_id"])
    assert review_round["status"] == RoundStatus.OPEN
    assert review_round["swept_by_deadline"] is False
    assert review_round["decided_at"] is None
    assert review_round["cast_vote_count"] == 1
    assert _read_package(api, ctx["package_id"])["status"] == PackageStatus.IN_REVIEW


def test_a_vote_arriving_exactly_at_the_deadline_instant_is_refused(api):
    """The clock must be strictly before the deadline, so equality rejects the vote.

    The Conservator is seated, has not voted, and the round is still open, yet
    the vote is refused on the temporal test alone and the tally does not move.

    PRD section 3.3: "One further test is temporal: the logical clock must be strictly before `decision_deadline_at`, so a vote arriving exactly at the deadline instant is rejected with `ERR_ROUND_DEADLINE_PASSED` — the same boundary the sweep uses from the other side."

    Design: Difficulty/boundary_precision_check/the_deadline_instant_belongs_to_the_sweep_and_not_to_the_voter
    """
    ctx = _package_in_review_with_one_vote_and_a_deadline(api)
    fx.set_clock(api, DEADLINE)
    before = _read_round(api, ctx["round_id"])

    validate_error(
        api.cast_vote(
            ctx["round_id"], f.vote_payload(VoteDecision.APPROVE), CONSERVATOR
        ),
        ERR_ROUND_DEADLINE_PASSED,
        409,
    )

    after = _read_round(api, ctx["round_id"])
    assert after["status"] == RoundStatus.OPEN
    assert after["cast_vote_count"] == 1
    assert after["approve_count"] == 1
    assert_unchanged(before, after, ["version", "cast_vote_count", "approve_count"])
    _, meta = validate_paginated(api.list_votes(ctx["round_id"], PM))
    assert meta["total_count"] == 1


def test_the_sweep_at_the_deadline_instant_lapses_the_round_into_a_revision(api):
    """The same instant the voter was refused is the instant the sweep fires.

    The lapse needs no vote at all: the round becomes a revision request marked
    as swept, its decision is stamped with the clock instant, and the package it
    reviews falls out of review and restricts the commission.

    PRD section 3.3: "Each lapsed round transitions `OPEN → REVISION_REQUESTED` with `swept_by_deadline` set to true and `decided_at` set to the clock instant — a lapse counts as a revision request, and no vote is required to produce one."

    Design: Difficulty/boundary_precision_check/the_deadline_instant_belongs_to_the_sweep_and_not_to_the_voter
    """
    ctx = _package_in_review_with_one_vote_and_a_deadline(api)
    fx.set_clock(api, DEADLINE)

    get_success_data(api.review_sweep(ctx["project_id"], PM), 200)

    review_round = _read_round(api, ctx["round_id"])
    assert review_round["status"] == RoundStatus.REVISION_REQUESTED
    assert review_round["swept_by_deadline"] is True
    assert is_iso8601_timestamp(review_round["decided_at"])
    assert review_round["decided_at"].startswith("2026-08-15T00:00:00")
    assert review_round["cast_vote_count"] == 1

    package = _read_package(api, ctx["package_id"])
    assert package["status"] == PackageStatus.REVISION_REQUESTED
    assert package["revision_count"] == 1

    project = fx.read_project(api, ctx["project_id"])
    assert project["phase"] == Phase.DESIGN_DEV
    assert_counters(project, open_revision_count=1, posture=Posture.RESTRICTED)


def test_a_replacement_round_needs_a_deadline_strictly_after_the_current_instant(api):
    """A deadline equal to the clock is refused; one second later opens round two.

    The swept package may open a fresh round, but a deadline sitting exactly on
    the current instant would be sweepable the moment it opened, so only the
    instant one second later is accepted.

    PRD section 3.3: "The deadline must fall strictly after the current logical-clock instant — a deadline equal to the current instant is rejected with `ERR_DEADLINE_IN_PAST` (HTTP 422), because such a round would be sweepable the moment it opened."

    PRD section 3.3: "The new round records the package it reviews through its `package_id` and takes a `round_number` equal to the package's `review_round_count` plus one, so rounds are numbered from 1 within each package."

    Design: Difficulty/boundary_precision_check/the_deadline_instant_belongs_to_the_sweep_and_not_to_the_voter
    """
    ctx = _package_in_review_with_one_vote_and_a_deadline(api)
    fx.set_clock(api, DEADLINE)
    get_success_data(api.review_sweep(ctx["project_id"], PM), 200)

    validate_error(
        api.create_review_round(
            ctx["package_id"],
            f.review_round_payload(
                panel_roles=PANEL_OF_THREE, decision_deadline_at=DEADLINE
            ),
            PM,
        ),
        ERR_DEADLINE_IN_PAST,
        422,
    )

    second_round = get_success_data(
        api.create_review_round(
            ctx["package_id"],
            f.review_round_payload(
                panel_roles=PANEL_OF_THREE,
                decision_deadline_at=ONE_SECOND_AFTER_DEADLINE,
            ),
            PM,
        ),
        201,
    )
    assert second_round["round_number"] == 2
    assert second_round["status"] == RoundStatus.OPEN
    assert second_round["required_vote_count"] == 2
    assert second_round["cast_vote_count"] == 0
    assert _read_package(api, ctx["package_id"])["review_round_count"] == 2


# ---------------------------------------------------------------------------
# the three accessibility minimums, each probed on its own boundary
# ---------------------------------------------------------------------------
#: A route whose four numbers sit exactly on the three published minimums:
#: 112 cm of egress, a 76 cm turning radius and 117.0 square metres against the
#: 195.0 required by 300 visitors an hour, which scores exactly 60.00.
ROUTE_ON_EVERY_MINIMUM = {
    "egress_clear_width_cm": 112.0,
    "wheelchair_turning_radius_cm": 76.0,
    "peak_visitors_per_hour": 300,
    "circulation_area_sqm": 117.0,
}


def _project_in_schematic(api):
    """Open a commission and advance it to the phase that admits packages."""
    fx.set_clock(api)
    project = fx.create_project(api)
    fx.advance(api, project["id"], Phase.SCHEMATIC)
    return project["id"]


def _issue_route(api, project_id, expected_project_version=None, **route):
    """Offer a design package describing one route, returning the raw response."""
    if expected_project_version is None:
        expected_project_version = fx.project_version(api, project_id)
    payload = dict(ROUTE_ON_EVERY_MINIMUM)
    payload.update(route)
    return api.create_design_package(
        project_id,
        f.design_package_payload(
            expected_project_version, stage=PackageStage.SCHEMATIC, **payload
        ),
        ACCESSIBILITY,
    )


def test_a_route_sitting_on_all_three_accessibility_minimums_is_accepted(api):
    """The accessibility specialist's route passes on equality alone.

    112 cm of egress, a 76 cm turning radius and a score of exactly 60.00 are
    each the published minimum, and PRD section 3.2 makes every one of the three
    comparisons inclusive.

    "`accessibility_pass` is true only when all three minimums hold together:
    `egress_clear_width_cm` is at least 112, `wheelchair_turning_radius_cm` is
    at least 76, and `flow_capacity_score` is at least 60.0. All three
    comparisons are inclusive, so a value sitting exactly on its minimum
    passes."

    "A package that passes is stored in status `DRAFT` with `review_round_count`
    and `revision_count` both 0, `submitted_by_user_id` taken from the caller's
    header, `approved_at` null and `superseded_by_package_id` null."

    Design: Difficulty/boundary_precision_check/flow_score_sixty_point_zero_passes_and_fifty_nine_point_four_nine_does_not
    """
    project_id = _project_in_schematic(api)

    package = get_success_data(_issue_route(api, project_id), 201)

    assert_index(package["flow_capacity_score"], 60.00)
    assert package["accessibility_pass"] is True
    assert package["status"] == PackageStatus.DRAFT
    assert package["stage"] == PackageStage.SCHEMATIC
    assert package["review_round_count"] == 0
    assert package["revision_count"] == 0
    assert package["submitted_by_user_id"] == USER_ACCESSIBILITY
    assert package["approved_at"] is None
    assert package["superseded_by_package_id"] is None


def test_one_square_metre_short_scores_fifty_nine_point_four_nine_and_is_refused(api):
    """116 square metres round to 59.49, and 59.49 is below the minimum.

    116.0 / 195.0 * 100 is 59.4871 to four places, which PRD section 2.8 rounds
    half up to two decimal places, so the stored figure would be 59.49 and the
    route misses the 60.0 minimum by a hundredth. The refusal stores nothing, which the
    following create proves by reusing the very same project version.

    "The circulation ratio is `circulation_area_sqm` divided by that required
    area, and `flow_capacity_score` is that ratio multiplied by 100, capped at
    100.0, then rounded half up to two decimal places — a route with exactly the
    required area therefore scores 100.00, and a route with double the required
    area also scores 100.00 because of the cap."

    "A package that fails any of the three is rejected outright with
    `ERR_ACCESSIBILITY_REQUIREMENTS_UNMET` (HTTP 422) and is not stored at all —
    which is why `accessibility_pass` is never persisted as false, and why a
    stored package always carries a `flow_capacity_score` of at least 60.00."

    Design: Difficulty/boundary_precision_check/flow_score_sixty_point_zero_passes_and_fifty_nine_point_four_nine_does_not
    """
    project_id = _project_in_schematic(api)
    version = fx.project_version(api, project_id)

    validate_error(
        _issue_route(
            api, project_id, expected_project_version=version, circulation_area_sqm=116.0
        ),
        ERR_ACCESSIBILITY_REQUIREMENTS_UNMET,
        422,
    )

    _, meta = validate_paginated(api.list_design_packages(project_id, PM))
    assert meta["total_count"] == 0

    accepted = get_success_data(
        _issue_route(api, project_id, expected_project_version=version), 201
    )
    assert_index(accepted["flow_capacity_score"], 60.00)


@pytest.mark.parametrize(
    "route",
    [
        {"egress_clear_width_cm": 111.0},
        {"wheelchair_turning_radius_cm": 75.0},
    ],
    ids=["egress_one_centimetre_narrow", "turning_radius_one_centimetre_tight"],
)
def test_a_single_dimension_one_centimetre_under_its_minimum_is_refused(api, route):
    """Either dimensional gate refuses on its own while the score still passes.

    The route keeps the 117.0 square metres that score exactly 60.00, so the
    flow gate is satisfied and the refusal can only come from the one dimension
    held a centimetre under its minimum.

    "`accessibility_pass` is true only when all three minimums hold together:
    `egress_clear_width_cm` is at least 112, `wheelchair_turning_radius_cm` is
    at least 76, and `flow_capacity_score` is at least 60.0."

    Design: Difficulty/boundary_precision_check/flow_score_sixty_point_zero_passes_and_fifty_nine_point_four_nine_does_not
    """
    project_id = _project_in_schematic(api)
    version = fx.project_version(api, project_id)

    validate_error(
        _issue_route(api, project_id, expected_project_version=version, **route),
        ERR_ACCESSIBILITY_REQUIREMENTS_UNMET,
        422,
    )

    _, meta = validate_paginated(api.list_design_packages(project_id, PM))
    assert meta["total_count"] == 0

    accepted = get_success_data(
        _issue_route(api, project_id, expected_project_version=version), 201
    )
    assert accepted["accessibility_pass"] is True


def test_a_route_far_above_the_minimum_scores_eighty_one_point_two_zero(api):
    """Away from the boundary the score still carries two decimal places.

    95.0 square metres against the 117.0 required by 180 visitors an hour is
    81.1965 percent to four places, which rounds half up to 81.20. Because the replacement names
    the same stage, PRD section 3.2 has it displace the package that scored
    exactly 60.00.

    "Every existing package of this project whose `stage` matches the new one and
    whose status is not already `SUPERSEDED` — that is, any package in `DRAFT`,
    `IN_REVIEW`, `REVISION_REQUESTED` or `APPROVED` — transitions to
    `SUPERSEDED`, processed in ascending `created_at` order, and has its
    `superseded_by_package_id` set to the new package's identifier."

    Design: Difficulty/boundary_precision_check/flow_score_sixty_point_zero_passes_and_fifty_nine_point_four_nine_does_not
    """
    project_id = _project_in_schematic(api)
    first = get_success_data(_issue_route(api, project_id), 201)

    second = get_success_data(
        _issue_route(
            api, project_id, peak_visitors_per_hour=180, circulation_area_sqm=95.0
        ),
        201,
    )

    assert_index(second["flow_capacity_score"], 81.20)
    assert second["accessibility_pass"] is True
    assert second["status"] == PackageStatus.DRAFT
    assert second["superseded_by_package_id"] is None

    displaced = _read_package(api, first["id"])
    assert displaced["status"] == PackageStatus.SUPERSEDED
    assert displaced["superseded_by_package_id"] == second["id"]
    assert displaced["version"] == first["version"] + 1
    assert_index(displaced["flow_capacity_score"], 60.00)


# ---------------------------------------------------------------------------
# the chamber numbers at the ceiling and at exactly twice the ceiling
# ---------------------------------------------------------------------------
#: A case-interior liner whose three chamber numbers sit exactly on the
#: case-interior limits: 0.05 VOC, 0.02 formaldehyde and a 21-day cure.
LINER_ON_EVERY_LIMIT = {
    "used_in": UsedIn.CASE_INTERIOR,
    "oddy_test_result": OddyResult.PASS,
    "voc_mg_per_m2_day": 0.05,
    "formaldehyde_ppm": 0.02,
    "cure_days": 21,
}

VENTING_CONDITIONS = "seal the liner and vent the case for 14 days before installation"


def _read_material(api, material_id, headers=PM):
    return get_success_data(api.get_material_spec(material_id, headers), 200)


def _submit_chamber_sample(api, material_name="Liner A at the limit", **chamber):
    """Register one material spec against a fresh commission in its first phase."""
    fx.set_clock(api)
    project = fx.create_project(api)
    payload = dict(LINER_ON_EVERY_LIMIT)
    payload.update(chamber)
    material = fx.create_material(
        api, project["id"], material_name=material_name, **payload
    )
    return project["id"], material


@pytest.mark.parametrize(
    "chamber,expected_verdict",
    [
        ({}, Verdict.CONSERVATION_SAFE),
        ({"cure_days": 20}, Verdict.CONDITIONAL_SAFE),
        ({"voc_mg_per_m2_day": 0.10}, Verdict.CONDITIONAL_SAFE),
        ({"voc_mg_per_m2_day": 0.11}, Verdict.UNSAFE),
        (
            {
                "oddy_test_result": OddyResult.UNTESTED,
                "voc_mg_per_m2_day": 0.01,
                "formaldehyde_ppm": 0.001,
                "cure_days": 60,
            },
            Verdict.UNSAFE,
        ),
        (
            {"used_in": UsedIn.GRAPHIC, "voc_mg_per_m2_day": 0.10},
            Verdict.CONSERVATION_SAFE,
        ),
    ],
    ids=[
        "on_every_case_interior_limit",
        "one_cure_day_short",
        "voc_at_exactly_twice_the_ceiling",
        "voc_just_over_twice_the_ceiling",
        "untested_but_chemically_clean",
        "the_same_numbers_on_a_graphic_panel",
    ],
)
def test_the_offgassing_verdict_turns_on_the_ceiling_and_on_twice_the_ceiling(
    api, chamber, expected_verdict
):
    """Six samples probe both thresholds the verdict places on one number.

    A VOC rate of 0.05 is exactly the case-interior ceiling and stays on the safe
    branch; 0.10 is exactly twice it and is only conditional, because the unsafe
    branch tests strictly greater; 0.11 crosses it. A cure period one day short
    of 21 drops out of the safe branch on its own, an `UNTESTED` Oddy class is
    unsafe however clean the chemistry, and the same 0.10 that is merely
    conditional inside a case is safe on a graphic panel.

    "The VOC ceiling is 0.05 milligrams per square metre per day for
    `CASE_INTERIOR` and for `MOUNT`, 0.50 for `CASE_EXTERIOR`, 0.80 for `GRAPHIC`
    and 0.60 for `INTERACTIVE_HOUSING`."

    "The material is `UNSAFE` if its Oddy class is `FAIL` or `UNTESTED`, or its
    VOC rate is strictly greater than **twice** the applicable VOC ceiling, or
    its formaldehyde concentration is strictly greater than twice the applicable
    formaldehyde ceiling."

    "Failing that, it is `CONSERVATION_SAFE` if its Oddy class is exactly `PASS`
    **and** its VOC rate is at most the ceiling **and** its formaldehyde
    concentration is at most the ceiling **and** its `cure_days` is at least the
    minimum."

    "Anything else — a `TEMPORARY` Oddy class, a VOC rate above the ceiling but
    not above double it, an under-cured but otherwise clean material — is
    `CONDITIONAL_SAFE`."

    Design: Difficulty/boundary_precision_check/offgassing_verdict_at_the_limit_and_at_exactly_twice_the_limit
    """
    _, material = _submit_chamber_sample(api, **chamber)

    assert material["verdict"] == expected_verdict
    assert material["status"] == MaterialStatus.SUBMITTED
    assert material["conditions"] is None
    assert material["decided_at"] is None


def test_an_untested_sample_may_not_be_put_in_front_of_a_conservator(api):
    """The Oddy axis gates the screening step, not just the verdict.

    The sample's chemistry is far inside every limit and its cure period is sixty
    days, but its Oddy class is `UNTESTED`, so PRD section 3.6 refuses the
    submission outright and the spec stays where it was.

    "In every case the material must not be `UNTESTED` on the Oddy axis — an
    untested sample cannot be put in front of a conservator, and the attempt
    answers `ERR_INVALID_MATERIAL_STATE` as well — and the project must not be
    frozen."

    Design: Difficulty/boundary_precision_check/offgassing_verdict_at_the_limit_and_at_exactly_twice_the_limit
    """
    _, material = _submit_chamber_sample(
        api,
        material_name="Liner E untested but clean",
        oddy_test_result=OddyResult.UNTESTED,
        voc_mg_per_m2_day=0.01,
        formaldehyde_ppm=0.001,
        cure_days=60,
    )

    validate_error(
        api.submit_material_for_conservation(material["id"], FABRICATION),
        ERR_INVALID_MATERIAL_STATE,
        409,
    )

    after = _read_material(api, material["id"])
    assert after["status"] == MaterialStatus.SUBMITTED
    assert after["verdict"] == Verdict.UNSAFE
    assert_unchanged(material, after, ["version", "status", "conditions", "decided_at"])


def test_an_unsafe_sample_refuses_both_clearances(api):
    """A hundredth over twice the ceiling closes both approving branches.

    0.11 is strictly greater than twice the 0.05 case-interior ceiling, so the
    verdict is `UNSAFE` and neither a plain approval nor an approval carrying
    conditions is available; the spec waits in review, undecided.

    "Either clearance attempted on an `UNSAFE` material is refused with
    `ERR_OFFGASSING_LIMIT_EXCEEDED` (HTTP 422): only `REJECT` is available on an
    unsafe material, so off-gassing cannot be waived by fiat."

    Design: Difficulty/boundary_precision_check/offgassing_verdict_at_the_limit_and_at_exactly_twice_the_limit
    """
    _, material = _submit_chamber_sample(
        api,
        material_name="Liner D just over twice the VOC limit",
        voc_mg_per_m2_day=0.11,
    )
    get_success_data(
        api.submit_material_for_conservation(material["id"], FABRICATION), 200
    )
    in_review = _read_material(api, material["id"])
    assert in_review["status"] == MaterialStatus.CONSERVATOR_REVIEW
    assert in_review["verdict"] == Verdict.UNSAFE

    validate_error(
        api.material_conservator_decision(
            material["id"],
            f.material_decision_payload(MaterialDecision.APPROVE),
            CONSERVATOR,
        ),
        ERR_OFFGASSING_LIMIT_EXCEEDED,
        422,
    )
    validate_error(
        api.material_conservator_decision(
            material["id"],
            f.material_decision_payload(
                MaterialDecision.APPROVE_WITH_CONDITIONS, conditions="vent for 30 days"
            ),
            CONSERVATOR,
        ),
        ERR_OFFGASSING_LIMIT_EXCEEDED,
        422,
    )

    after = _read_material(api, material["id"])
    assert after["status"] == MaterialStatus.CONSERVATOR_REVIEW
    assert_unchanged(in_review, after, ["version", "status", "conditions", "decided_at"])


def test_a_sample_at_exactly_twice_the_ceiling_clears_with_conditions(api):
    """Twice the ceiling is conditional, and the conditional branch accepts it.

    0.10 is exactly twice the case-interior VOC ceiling, which keeps the sample
    out of the unsafe branch and inside the conditional one, so the conservator
    may clear it with written conditions and the project returns to `OPEN`.

    "An `APPROVE` is permitted only when the derived verdict is
    `CONSERVATION_SAFE`; an `APPROVE_WITH_CONDITIONS` is permitted when the
    verdict is `CONSERVATION_SAFE` or `CONDITIONAL_SAFE` and requires a non-blank
    `conditions` string, without which the request is `ERR_INVALID_REQUEST`."

    "`APPROVE` lands the material in `APPROVED` with `conditions` nulled;
    `APPROVE_WITH_CONDITIONS` lands it in `CONDITIONAL` with the conservator's
    text stored."

    Design: Difficulty/boundary_precision_check/offgassing_verdict_at_the_limit_and_at_exactly_twice_the_limit
    """
    project_id, material = _submit_chamber_sample(
        api, material_name="Liner C at twice the VOC limit", voc_mg_per_m2_day=0.10
    )
    get_success_data(
        api.submit_material_for_conservation(material["id"], FABRICATION), 200
    )

    cleared = get_success_data(
        api.material_conservator_decision(
            material["id"],
            f.material_decision_payload(
                MaterialDecision.APPROVE_WITH_CONDITIONS, conditions=VENTING_CONDITIONS
            ),
            CONSERVATOR,
        ),
        200,
    )

    assert cleared["status"] == MaterialStatus.CONDITIONAL
    assert cleared["verdict"] == Verdict.CONDITIONAL_SAFE
    assert cleared["conditions"] == VENTING_CONDITIONS
    assert cleared["decided_at"].startswith("2026-08-01T00:00:00")
    project = fx.read_project(api, project_id)
    assert_counters(project, pending_material_count=0, posture=Posture.OPEN)


def test_a_sample_on_every_limit_is_approved_outright(api):
    """Three simultaneous equalities carry the sample to a plain approval.

    0.05 VOC, 0.02 formaldehyde and a 21-day cure are each exactly the
    case-interior limit, so the verdict is `CONSERVATION_SAFE` and the plain
    approval — the only branch that demands that verdict — succeeds with no
    conditions attached.

    "All comparisons are exact on the stored numbers and a value exactly equal to
    a ceiling satisfies it."

    "Both set `decided_at` to the logical-clock instant, drop the material out of
    `pending_material_count`, and recompute posture — so clearing the last
    pending material is what returns a project to `OPEN`."

    Design: Difficulty/boundary_precision_check/offgassing_verdict_at_the_limit_and_at_exactly_twice_the_limit
    """
    project_id, material = _submit_chamber_sample(api)
    assert material["verdict"] == Verdict.CONSERVATION_SAFE
    assert_counters(
        fx.read_project(api, project_id),
        pending_material_count=1,
        posture=Posture.RESTRICTED,
    )
    get_success_data(
        api.submit_material_for_conservation(material["id"], FABRICATION), 200
    )

    cleared = get_success_data(
        api.material_conservator_decision(
            material["id"],
            f.material_decision_payload(MaterialDecision.APPROVE),
            CONSERVATOR,
        ),
        200,
    )

    assert cleared["status"] == MaterialStatus.APPROVED
    assert cleared["conditions"] is None
    assert cleared["decided_at"].startswith("2026-08-01T00:00:00")
    project = fx.read_project(api, project_id)
    assert_counters(project, pending_material_count=0, posture=Posture.OPEN)

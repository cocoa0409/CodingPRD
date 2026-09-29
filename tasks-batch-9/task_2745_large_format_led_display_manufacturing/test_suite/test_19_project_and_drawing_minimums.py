"""Admission rules whose floors are derived rather than supplied.

None of the four thresholds here is a project input: the closest legal viewing
distance comes out of the pixel pitch, the structural floor out of the cabinet's
weight over its area, the wind floor out of where the wall will stand, and the
capacity line out of a ceil over the pixel budget against a floor over the
derated ports. Each is probed one hundredth either side of its boundary.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_DATA_LOAD_EXCEEDS_CAPACITY,
    ERR_OPEN_REVISION_EXISTS,
    ERR_REDUNDANCY_REQUIRED_FOR_ROADSIDE,
    ERR_STRUCTURAL_CAPACITY_INSUFFICIENT,
    ERR_VIEWING_DISTANCE_TOO_SHORT,
    ERR_WIND_LOAD_INSUFFICIENT,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_page_meta,
    assert_project_fields,
    assert_version,
    ids_of,
)
from test_helpers.constants import (
    ENGINEERING_DRAFT,
    ENGINEERING_REJECTED,
    ENGINEERING_UNDER_REVIEW,
    PRODUCTION_NOT_STARTED,
    REVISION_REJECTED,
    REVISION_SUBMITTED,
)
from test_helpers.factories import (
    FP16_STD,
    FP25_OUT,
    drawing_revision_payload,
    project_payload,
)

#: FP25-OUT publishes a 2.5 mm pitch, so its recommended minimum viewing
#: distance is 2.5 m and one tenth closer is refused.
FP25_MIN_VIEWING_DISTANCE_M = 2.5
TOO_CLOSE_VIEWING_DISTANCE_M = 2.4

#: round(20.5 / 0.2048, 2) on the FP25-OUT cabinet, and one hundredth short of it.
FP25_REQUIRED_LOAD_KG_PER_SQM = 100.10
UNDER_LOAD_KG_PER_SQM = 100.09

#: The wind floor for a ROADSIDE wall, and one kilometre per hour short of it.
ROADSIDE_WIND_FLOOR_KPH = 200
UNDER_WIND_KPH = 199

#: FP16-STD needs 150.00 kg/sqm of certified capacity.
FP16_REQUIRED_LOAD_KG_PER_SQM = 150.00

#: floor(1 x 1000 x 0.75) for RING, and floor(1 x 1000 x 1.0) for NONE.
RING_CAPACITY_MBPS = 750
UNDERATED_CAPACITY_MBPS = 1000

#: ceil(1024 x 10 x 3 x 60 / 1e6) for a 1x1 FP10-IN wall.
FP10_REQUIRED_DATA_MBPS = 2
SATURATED_LOAD_PCT = 100.00

REJECTION_REASON = "Anchor spacing does not match the steel drawing"


def _roadside_fp25_project(plant, **overrides):
    """A ROADSIDE FP25-OUT wall sited at exactly its recommended viewing distance."""
    model = plant.register_model(FP25_OUT)
    project = plant.create_project(
        model["id"],
        install_environment="ROADSIDE",
        redundancy_mode="RING",
        min_viewing_distance_m=FP25_MIN_VIEWING_DISTANCE_M,
        **overrides,
    )
    return model, project


class TestViewingDistanceFloor:
    """The floor is the pitch in millimetres read as metres, not a fixed number."""

    def test_one_tenth_closer_than_the_pitch_allows_is_refused(self, plant):
        """The surveyed `min_viewing_distance_m` must be at least the family's
        `recommended_min_viewing_distance_m`, compared at 1 decimal place; exact
        equality passes, and anything closer is refused with
        `ERR_VIEWING_DISTANCE_TOO_SHORT` because the audience would see the pixel
        grid.

        Design: Corner/validations/viewing_distance_below_the_pitch_derived_minimum_rejected
        """
        model = plant.register_model(FP25_OUT)
        assert_2dp(
            model["recommended_min_viewing_distance_m"],
            FP25_MIN_VIEWING_DISTANCE_M,
            "recommended_min_viewing_distance_m",
        )

        refused = plant.api.create_project(
            project_payload(
                model["id"], min_viewing_distance_m=TOO_CLOSE_VIEWING_DISTANCE_M
            ),
            plant.engineer,
        )
        accepted = plant.api.create_project(
            project_payload(
                model["id"], min_viewing_distance_m=FP25_MIN_VIEWING_DISTANCE_M
            ),
            plant.engineer,
        )

        validate_error(refused, ERR_VIEWING_DISTANCE_TOO_SHORT, 422)
        created = validate_success(accepted, 201)
        assert_2dp(
            created["min_viewing_distance_m"],
            FP25_MIN_VIEWING_DISTANCE_M,
            "min_viewing_distance_m",
        )
        projects, meta = validate_paginated(plant.api.list_projects(plant.engineer))
        assert ids_of(projects) == [created["id"]]
        assert_page_meta(meta, total_count=1, has_more=False)


class TestRoadsideRedundancyRule:
    """One enum value makes the same body illegal, and only that one."""

    def test_the_same_body_is_refused_roadside_and_accepted_stadium(self, plant):
        """And a `ROADSIDE` wall must carry some control-system redundancy:
        declaring `install_environment` as `ROADSIDE` together with a
        `redundancy_mode` of `NONE` is refused with
        `ERR_REDUNDANCY_REQUIRED_FOR_ROADSIDE`. Stadium and retail walls may run
        without redundancy.

        Design: Corner/validations/roadside_project_without_redundancy_rejected
        """
        model = plant.register_model()

        refused = plant.api.create_project(
            project_payload(
                model["id"], install_environment="ROADSIDE", redundancy_mode="NONE"
            ),
            plant.engineer,
        )
        accepted = plant.api.create_project(
            project_payload(
                model["id"], install_environment="STADIUM", redundancy_mode="NONE"
            ),
            plant.engineer,
        )

        validate_error(refused, ERR_REDUNDANCY_REQUIRED_FOR_ROADSIDE, 422)
        created = validate_success(accepted, 201)
        assert created["redundancy_mode"] == "NONE"
        assert created["install_environment"] == "STADIUM"
        assert created["effective_capacity_mbps"] == UNDERATED_CAPACITY_MBPS


class TestDataLoadCapacityLine:
    """The gate reads a derived percentage and the boundary itself is legal."""

    def test_a_saturated_link_is_accepted_and_a_starved_one_is_not(self, plant):
        """A load of more than 100.00 percent is refused with
        `ERR_DATA_LOAD_EXCEEDS_CAPACITY`; a load of exactly 100.00 percent is
        accepted, because a wall that saturates its links precisely is a
        legitimate — if tight — design.

        Design: Corner/validations/project_data_load_at_and_above_the_capacity_line
        """
        model = plant.register_model()

        starved = plant.api.create_project(
            project_payload(
                model["id"],
                customer_name="Starved Link Wall",
                port_bandwidth_mbps=1,
            ),
            plant.engineer,
        )
        saturated = plant.api.create_project(
            project_payload(model["id"], port_bandwidth_mbps=2), plant.engineer
        )

        validate_error(starved, ERR_DATA_LOAD_EXCEEDS_CAPACITY, 422)
        created = validate_success(saturated, 201)
        assert created["required_data_mbps"] == FP10_REQUIRED_DATA_MBPS
        assert created["effective_capacity_mbps"] == FP10_REQUIRED_DATA_MBPS
        assert_2dp(created["data_load_pct"], SATURATED_LOAD_PCT, "data_load_pct")
        projects, meta = validate_paginated(plant.api.list_projects(plant.engineer))
        assert ids_of(projects) == [created["id"]]
        assert_page_meta(meta, total_count=1, has_more=False)


class TestDrawingStructuralAndWindFloors:
    """Two adjacent rules, each derived, each named only when it alone is broken."""

    def test_a_hundredth_under_the_load_and_one_kph_under_the_wind_are_named_apart(
        self, plant
    ):
        """Second, the wind rating is checked against a floor set by where the wall
        will stand — at least 160 kph for a `STADIUM` wall, at least 200 kph for a
        `ROADSIDE` wall, and at least 100 kph for a `RETAIL` wall — with anything
        below the floor refused as `ERR_WIND_LOAD_INSUFFICIENT`. Third, the
        certified `structural_load_kg_per_sqm` must be at least the snapshotted
        `required_load_kg_per_sqm`, compared at 2 decimal places, with exact
        equality passing and anything less refused as
        `ERR_STRUCTURAL_CAPACITY_INSUFFICIENT`.

        Design: Corner/validations/drawing_below_the_structural_or_wind_minimum_rejected
        """
        model, project = _roadside_fp25_project(plant)
        assert_2dp(
            model["required_load_kg_per_sqm"],
            FP25_REQUIRED_LOAD_KG_PER_SQM,
            "required_load_kg_per_sqm",
        )

        under_load = plant.api.create_drawing_revision(
            drawing_revision_payload(
                project["id"],
                structural_load_kg_per_sqm=UNDER_LOAD_KG_PER_SQM,
                wind_load_kph=ROADSIDE_WIND_FLOOR_KPH,
            ),
            plant.engineer,
        )
        under_wind = plant.api.create_drawing_revision(
            drawing_revision_payload(
                project["id"],
                structural_load_kg_per_sqm=FP25_REQUIRED_LOAD_KG_PER_SQM,
                wind_load_kph=UNDER_WIND_KPH,
            ),
            plant.engineer,
        )

        validate_error(under_load, ERR_STRUCTURAL_CAPACITY_INSUFFICIENT, 422)
        validate_error(under_wind, ERR_WIND_LOAD_INSUFFICIENT, 422)
        rows, meta = validate_paginated(
            plant.api.list_drawing_revisions(
                plant.engineer, {"project_id": project["id"]}
            )
        )
        assert rows == []
        assert_page_meta(meta, total_count=0, has_more=False)
        assert_project_fields(
            plant.project(project["id"]),
            engineering_state=ENGINEERING_DRAFT,
            production_state=PRODUCTION_NOT_STARTED,
            approved_revision_number=None,
        )

    def test_exact_equality_clears_all_three_derived_minimums_at_once(self, plant):
        """It snapshots the family's current `required_load_kg_per_sqm` onto the
        revision's own `required_load_kg_per_sqm` field, freezing the bar the
        drawing was judged against, records `submitted_by_user_id` as the
        submitting `X-User-ID`, sets `revision_state` to `SUBMITTED`, and moves the
        project's `engineering_state` from `DRAFT` or `REJECTED` to `UNDER_REVIEW`.

        Design: Corner/validations/drawing_at_the_exact_minimums_is_accepted
        """
        _, project = _roadside_fp25_project(plant)
        assert_2dp(
            project["min_viewing_distance_m"],
            FP25_MIN_VIEWING_DISTANCE_M,
            "min_viewing_distance_m",
        )
        assert project["effective_capacity_mbps"] == RING_CAPACITY_MBPS

        response = plant.api.create_drawing_revision(
            drawing_revision_payload(
                project["id"],
                structural_load_kg_per_sqm=FP25_REQUIRED_LOAD_KG_PER_SQM,
                wind_load_kph=ROADSIDE_WIND_FLOOR_KPH,
            ),
            plant.engineer,
        )

        revision = validate_success(response, 201)
        assert revision["revision_state"] == REVISION_SUBMITTED
        assert revision["revision_number"] == 1
        assert_2dp(
            revision["required_load_kg_per_sqm"],
            FP25_REQUIRED_LOAD_KG_PER_SQM,
            "required_load_kg_per_sqm",
        )
        assert_version(revision, 1, "revision")
        assert_project_fields(
            plant.project(project["id"]),
            engineering_state=ENGINEERING_UNDER_REVIEW,
            approved_revision_number=None,
        )


class TestOpenRevisionGate:
    """The gate reads the open revision's state, not how many revisions exist."""

    def test_a_rejection_reopens_the_queue_and_the_counter_keeps_climbing(self, plant):
        """Only fourth does the service check that no other revision of the
        project is still `SUBMITTED`, refusing a concurrent submission with
        `ERR_OPEN_REVISION_EXISTS`.

        Design: Corner/validations/a_second_submitted_revision_is_refused_while_one_is_open
        """
        model = plant.register_model(FP16_STD)
        project = plant.create_project(model["id"])
        body = drawing_revision_payload(
            project["id"], structural_load_kg_per_sqm=FP16_REQUIRED_LOAD_KG_PER_SQM
        )
        first = plant.submit_revision(
            project["id"], structural_load_kg_per_sqm=FP16_REQUIRED_LOAD_KG_PER_SQM
        )

        refused = plant.api.create_drawing_revision(body, plant.engineer)

        validate_error(refused, ERR_OPEN_REVISION_EXISTS, 409)
        rejected = plant.review_revision(first["id"], "REJECT", REJECTION_REASON)
        assert rejected["revision_state"] == REVISION_REJECTED
        assert_project_fields(
            plant.project(project["id"]), engineering_state=ENGINEERING_REJECTED
        )

        second = validate_success(
            plant.api.create_drawing_revision(body, plant.engineer), 201
        )

        assert second["revision_number"] == 2
        assert second["revision_state"] == REVISION_SUBMITTED
        assert_project_fields(
            plant.project(project["id"]),
            engineering_state=ENGINEERING_UNDER_REVIEW,
            approved_revision_number=None,
        )

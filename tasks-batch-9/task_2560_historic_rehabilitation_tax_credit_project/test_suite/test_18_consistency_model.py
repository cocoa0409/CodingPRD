"""What a caller can see the moment a cascading write returns.

One approval that touches three rows, read back immediately from the two rows the
determination did not return.
"""

from test_helpers import (
    assertions,
    fixtures,
    validate_success,
)


def test_the_part_one_approval_cascade_is_visible_the_moment_it_returns(api):
    """The determination settles the property and the project before it answers.

    The determination is issued on an application in federal review, and its response
    already carries the approved status and the deciding reviewer. Reading the other two
    rows straight afterwards — with no clock movement in between, so the certification
    instant is still the one the approval stamped — shows the cascade fully applied: the
    building is certified historic and the project has advanced to PART1_CERTIFIED. The
    project has been mutated twice in all, once when the application was created against
    it and once by this approval.

    PRD: "Cascades run to completion inside the request that triggers them, and the response reflects the fully settled world: a caller reading the response of an operation sees post-cascade values, never an intermediate state."
    PRD: "The rule for all of them is uniform: **every row a cascade touches is a mutation of that row.**"
    PRD: "For a Part 1 application, the first hop sets the property's `evaluation_status` to `CERTIFIED_HISTORIC` and stamps its `certified_at` from the logical clock, bumping the property's `version`."
    PRD: "Creation increments the project's `version` by one."

    Design: Corner/consistency_model/part_one_approval_cascade_is_visible_in_the_same_response_cycle
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    opening_version = project["version"]
    application = fixtures.create_part_application(api, cast, project["id"], 1)
    fixtures.submit_part_application(api, cast, application["id"])
    fixtures.shpo_recommend(api, cast, application["id"])

    determined = api.nps_determination(
        application["id"], cast.nps_headers, determination="APPROVED"
    )

    approved = validate_success(determined, 200)
    assertions.assert_fields(
        approved,
        "the determination response",
        status="APPROVED",
        nps_reviewer_id=cast.nps_reviewer_id,
    )
    stored_project = fixtures.read_project(api, cast, project["id"])
    assertions.assert_project_state(
        stored_project, certification_status="PART1_CERTIFIED"
    )
    assertions.assert_fields(
        stored_project,
        "the project read straight after the approval",
        version=opening_version + 2,
    )
    stored_property = validate_success(
        api.get_property(cast.property_id, fixtures.ADMIN)
    )
    assertions.assert_fields(
        stored_property,
        "the building read straight after the approval",
        evaluation_status="CERTIFIED_HISTORIC",
    )
    assert stored_property["certified_at"].startswith("2026-09-01T00:00:00"), (
        "the certification instant comes from the logical clock, which has not moved"
    )

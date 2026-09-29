"""Cross-cutting envelope behaviour: the pagination bounds and the family-specific
not-found errors.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import assert_page, ids_of
from test_helpers.fixtures import make_project
from test_helpers.test_users import sponsor_headers

STD_PROJECT = ("44 Cove Lane, Bangor ME", 1968, 2)


def test_pagination_limit_below_minimum_returns_invalid_pagination(api):
    """PRD: A `limit` outside the inclusive range from 1 to 100, or a negative `offset`,
    is rejected with `ERR_INVALID_PAGINATION` and HTTP 422; neither value is silently
    clamped.

    Design: Corner/validations/pagination_limit_below_minimum_returns_invalid_pagination
    """
    project = make_project(api, *STD_PROJECT)

    validate_error(
        api.list_projects(sponsor_headers(), params={"limit": 0}),
        "ERR_INVALID_PAGINATION",
        expected_status=422,
    )
    validate_error(
        api.list_projects(sponsor_headers(), params={"limit": 101}),
        "ERR_INVALID_PAGINATION",
        expected_status=422,
    )
    validate_error(
        api.list_projects(sponsor_headers(), params={"offset": -1}),
        "ERR_INVALID_PAGINATION",
        expected_status=422,
    )

    rows, meta = validate_paginated(
        api.list_projects(sponsor_headers(), params={"limit": 100, "offset": 0})
    )
    assert_page(meta, total_count=1, limit=100, offset=0, has_more=False)
    assert ids_of(rows) == [project["id"]]

    defaulted, meta = validate_paginated(api.list_projects(sponsor_headers()))
    assert_page(meta, total_count=1, limit=10, offset=0, has_more=False)
    assert ids_of(defaulted) == [project["id"]]


def test_unknown_ids_map_to_the_family_specific_not_found_error(api):
    """PRD: Existence checks follow, in a fixed order of their own.

    Design: Corner/errors/unknown_ids_map_to_the_family_specific_not_found_error
    """
    project = make_project(api, *STD_PROJECT)
    headers = sponsor_headers()

    families = (
        (api.get_report(NON_EXISTENT_UUID, headers), "ERR_ENGINEERING_ARTIFACT_NOT_FOUND"),
        (
            api.get_component(NON_EXISTENT_UUID, headers),
            "ERR_ENGINEERING_ARTIFACT_NOT_FOUND",
        ),
        (api.get_pos(NON_EXISTENT_UUID, headers), "ERR_DISCLOSURE_ARTIFACT_NOT_FOUND"),
        (api.get_household(NON_EXISTENT_UUID, headers), "ERR_TENANT_NOT_FOUND"),
        (api.get_agreement(NON_EXISTENT_UUID, headers), "ERR_SALES_ARTIFACT_NOT_FOUND"),
        (api.get_claim(NON_EXISTENT_UUID, headers), "ERR_CLAIM_NOT_FOUND"),
    )
    for response, error_id in families:
        validate_error(response, error_id, expected_status=404)
        assert sorted(response.json()["data"]) == ["error_id", "message"]

    still_there = validate_success(api.get_project(project["id"], headers))
    assert still_there["id"] == project["id"]

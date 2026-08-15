"""Districts, guideline sets, property inventory, census, and the OCC-guarded
reclassification write (PRD §2.7, §2.9, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_district,
    assert_district_census,
    assert_guideline_set,
    assert_version_incremented,
    create_district,
    create_guideline_set,
    create_owner,
    create_property,
    get_district,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

STAFF = TEST_USERS["staff_headers"]


def test_district_creation_defaults(api):
    """PRD §3.1: "A new district starts `ACTIVE` with both census counters at
    zero and posture `STABLE`."

    Design: Corner/entities/district_creation_defaults
    """
    district = validate_success(
        api.create_district(
            {
                "name": "Old Town",
                "boundary_description": "Blocks 1-9",
                "significance_tier": "LOCAL",
            },
            STAFF,
        ),
        201,
    )
    assert_district(district)
    assert district["status"] == "ACTIVE"
    assert_district_census(district, contributing=0, total=0, posture="STABLE")


def test_guideline_set_version_no_increments_per_district(api):
    """PRD §3.1: "Staff authors a set as a `DRAFT` with a `title` and a
    `sections` array, each section carrying a `section_code` and its `text`,
    and the system assigns a `version_no` of one plus the count of prior
    guideline sets for that district, so numbering is per-district monotonic."

    Design: Corner/entities/guideline_set_version_no_increments_per_district
    """
    district = create_district(name="Old Town")
    gs1 = validate_success(
        api.create_guideline_set(
            district["id"],
            {"title": "DG-1", "sections": [{"section_code": "S1", "text": "Siding"}]},
            STAFF,
        ),
        201,
    )
    assert_guideline_set(gs1)
    assert gs1["version_no"] == 1
    assert gs1["status"] == "DRAFT"
    assert gs1.get("adopted_at") is None

    gs2 = validate_success(
        api.create_guideline_set(
            district["id"],
            {"title": "DG-2", "sections": [{"section_code": "S1", "text": "Siding revised"}]},
            STAFF,
        ),
        201,
    )
    assert gs2["version_no"] == 2


def test_guideline_adopt_supersedes_prior(api):
    """PRD §3.1: "Adoption is the pivotal act: adopting a `DRAFT` set stamps its
    `adopted_at` with the logical clock (it remains null while `DRAFT`), moves
    the set to `ADOPTED`, and flips the district's previously `ADOPTED` set, if
    one exists, to `SUPERSEDED` — at most one set per district is `ADOPTED` at
    any time."

    Design: Corner/state_machines/guideline_adopt_supersedes_prior
    """
    district = create_district(name="Old Town")
    gs1 = create_guideline_set(district["id"], title="DG-1")
    adopted1 = validate_success(api.adopt_guideline_set(gs1["id"], STAFF))
    assert adopted1["status"] == "ADOPTED"
    assert adopted1.get("adopted_at") is not None

    gs2 = create_guideline_set(district["id"], title="DG-2")
    adopted2 = validate_success(api.adopt_guideline_set(gs2["id"], STAFF))
    assert adopted2["status"] == "ADOPTED"
    assert adopted2.get("adopted_at") is not None

    sets, meta = validate_paginated(
        api.list_guideline_sets(district["id"], STAFF, params={"status": "SUPERSEDED"})
    )
    assert [s["id"] for s in sets] == [gs1["id"]], (
        "the previously ADOPTED set must be SUPERSEDED"
    )


def test_property_get_not_found_returns_404(api):
    """PRD §2.8: "Path identifiers are validated left-to-right, and the request
    is rejected with `ERR_NOT_FOUND` at the first path identifier that does not
    correspond to an existing resource."

    Design: Corner/entities/property_get_not_found_returns_404
    """
    response = api.get_property(NON_EXISTENT_UUID, STAFF)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_property_creation_visible_in_district_census_immediately(api):
    """PRD §2.9: "The counters are maintained incrementally on each triggering
    mutation — property creation into the district, property reclassification,
    and demolition completion — and are always equal to a full recount of the
    district's properties, so reads of a district reflect current values."

    Design: Corner/consistency_model/immediate_read_after_write_and_cascade_visibility
    """
    district = create_district(name="Old Town")
    owner = create_owner()
    prop = create_property(
        owner["id"], district_id=district["id"], contributing_status="CONTRIBUTING"
    )
    assert prop["district_id"] == district["id"]

    refreshed = get_district(district["id"])
    assert_district_census(refreshed, contributing=1, total=1, posture="STABLE")


def test_list_districts_pagination_envelope(api):
    """PRD §2.3: "Paginated list-based responses include the following fields
    in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return. If not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies the number of items to
    skip and defaults to 0."

    Design: Corner/endpoints/list_pagination_envelope
    """
    for name in ("D1", "D2", "D3"):
        create_district(name=name)

    page1, meta1 = validate_paginated(api.list_districts(STAFF, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_districts(STAFF, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


class TestReclassifyConservesCensus:
    def test_reclassify_forward_step_adjusts_census(self, api):
        """PRD §3.1: "A successful reclassification adjusts the district's
        contributing census by the delta of the change (moving to
        `CONTRIBUTING` raises `contributing_count` by one; moving away lowers
        it by one; the district's counters stay consistent through the change),
        recomputes the district's `preservation_posture`, and increments the
        property's `version`."
        PRD §2.9: "The `preservation_posture` is `AT_RISK` exactly when the
        inventory is non-empty and strictly fewer than half of its properties
        are contributing — that is, when `total_inventory_count` is greater
        than zero and twice `contributing_count` is strictly less than
        `total_inventory_count`; otherwise it is `STABLE`, including for an
        empty district."

        Design: Difficulty/compensating_invariant/reclassify_pair_conserves_census
        """
        district = create_district(name="Old Town")
        owner = create_owner()
        prop = create_property(
            owner["id"], district_id=district["id"], contributing_status="CONTRIBUTING"
        )
        assert_district_census(get_district(district["id"]), 1, 1, "STABLE")

        reclassified = validate_success(
            api.reclassify_property(
                prop["id"],
                {
                    "contributing_status": "NON_CONTRIBUTING",
                    "expected_property_version": prop["version"],
                },
                STAFF,
            )
        )
        assert reclassified["contributing_status"] == "NON_CONTRIBUTING"
        assert_version_incremented(reclassified["version"], prop["version"])

        mid = get_district(district["id"])
        assert_district_census(mid, contributing=0, total=1, posture="AT_RISK")

    def test_reclassify_compensating_step_restores_census(self, api):
        """PRD §3.1: "A successful reclassification adjusts the district's
        contributing census by the delta of the change (moving to
        `CONTRIBUTING` raises `contributing_count` by one; moving away lowers
        it by one; the district's counters stay consistent through the change),
        recomputes the district's `preservation_posture`, and increments the
        property's `version`."

        Design: Difficulty/compensating_invariant/reclassify_pair_conserves_census
        """
        district = create_district(name="Old Town")
        owner = create_owner()
        prop = create_property(
            owner["id"], district_id=district["id"], contributing_status="CONTRIBUTING"
        )

        forward = get_success_data(
            api.reclassify_property(
                prop["id"],
                {
                    "contributing_status": "NON_CONTRIBUTING",
                    "expected_property_version": prop["version"],
                },
                STAFF,
            )
        )
        back = validate_success(
            api.reclassify_property(
                prop["id"],
                {
                    "contributing_status": "CONTRIBUTING",
                    "expected_property_version": forward["version"],
                },
                STAFF,
            )
        )
        assert back["contributing_status"] == "CONTRIBUTING"
        assert_version_incremented(back["version"], forward["version"])

        end = get_district(district["id"])
        assert_district_census(end, contributing=1, total=1, posture="STABLE")

    def test_stale_property_version_rejected_and_census_undisturbed(self, api):
        """PRD §2.7: "If the value does not match the property's current
        `version`, the request is rejected with `ERR_STALE_PROPERTY_VERSION`
        (HTTP 412), and the version check runs before any state or business
        evaluation of the write."

        Design: Corner/validations/stale_property_version_on_reclassify_returns_412
        """
        district = create_district(name="Old Town")
        owner = create_owner()
        prop = create_property(
            owner["id"], district_id=district["id"], contributing_status="CONTRIBUTING"
        )

        first = get_success_data(
            api.reclassify_property(
                prop["id"],
                {
                    "contributing_status": "NON_CONTRIBUTING",
                    "expected_property_version": prop["version"],
                },
                STAFF,
            )
        )
        assert first["contributing_status"] == "NON_CONTRIBUTING"

        stale = api.reclassify_property(
            prop["id"],
            {
                "contributing_status": "NON_CONTRIBUTING",
                "expected_property_version": prop["version"],
            },
            STAFF,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PROPERTY_VERSION)

        district_after = get_district(district["id"])
        assert_district_census(district_after, contributing=0, total=1, posture="AT_RISK")

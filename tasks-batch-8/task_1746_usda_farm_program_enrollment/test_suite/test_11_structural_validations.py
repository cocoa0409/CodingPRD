"""Structural validations: cropland capacity, share-percent sum, line-acre
caps, membership reverse lookup, and pagination shape (PRD §3.1, §3.3, §2.3)."""
import pytest

from test_helpers import (
    SAFE_CLOCK,
    ApiErrorId,
    add_field,
    add_tract,
    assert_membership,
    create_acreage_report_line_payload,
    create_farm,
    create_farm_with_member,
    create_membership_payload,
    create_producer,
    create_producer_payload,
    make_producer_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def specialist(county_specialist_headers):
    return county_specialist_headers


class TestCroplandCapacity:
    def test_field_acres_exceed_tract_cropland_rejected(self, api, specialist):
        """PRD §3.1: "Fields are added to a tract by referencing the parent's
        `tract_id` and supplying a `field_number` and a GIS-measured `acres`;
        the sum of `acres` across all fields on a tract must not exceed that
        tract's `cropland_acres`, or the request is rejected with
        `ERR_CROPLAND_EXCEEDED`."

        Design: Corner/validations/field_acres_exceed_tract_cropland_rejected
        """
        farm = create_farm(farm_number="F15", county_code="019", program_year=2026)
        tract = add_tract(
            farm["id"], tract_number="T1", base_acres=50.00, cropland_acres=50.00
        )
        add_field(tract["id"], field_number="1", acres=50.00)
        resp = api.create_field(
            tract["id"], {"field_number": "2", "acres": 1.00}, specialist
        )
        validate_error(resp, ApiErrorId.ERR_CROPLAND_EXCEEDED.value)


class TestShareSumInvariant:
    def test_membership_share_sum_must_equal_100(self, api, specialist):
        """PRD §3.1: "The share percentages across a farm's `ACTIVE` memberships
        must sum to exactly 100.00; a membership that would break this invariant
        is rejected with `ERR_SHARE_SUM_INVALID`."

        With a 100.00% membership already ACTIVE, any additional positive share
        pushes the sum past exactly 100.00 and must be rejected.

        Design: Corner/validations/membership_share_sum_must_equal_100
        """
        farm, _producer_a, membership = create_farm_with_member(share=100.00)
        assert membership["membership_status"] == "ACTIVE"
        producer_b = create_producer(producer_name="Second Producer")
        resp = api.create_membership(
            farm["id"],
            create_membership_payload(producer_id=producer_b["id"], share_percent=25.00),
            specialist,
        )
        validate_error(resp, ApiErrorId.ERR_SHARE_SUM_INVALID.value)


class TestLineAcresCap:
    def test_report_line_acres_exceed_field_rejected(self, api, specialist):
        """PRD §3.3: "On a single line, the sum of `planted_acres` and
        `prevented_planted_acres` must not exceed the parent field's `acres`;
        violations are rejected with `ERR_LINE_ACRES_EXCEED_FIELD`."

        40.00 planted + 20.00 prevented = 60.00 against a 50.00-acre field.

        Design: Corner/validations/report_line_acres_exceed_field_rejected
        """
        set_clock(SAFE_CLOCK)
        farm, producer, _ = create_farm_with_member()
        producer_headers = make_producer_headers(producer["id"])
        tract = add_tract(
            farm["id"], tract_number="T1", base_acres=50.00, cropland_acres=50.00
        )
        field = add_field(tract["id"], field_number="1", acres=50.00)
        report = validate_success(
            api.create_acreage_report(
                farm["id"], {"program_year": 2026}, producer_headers
            ),
            201,
        )
        resp = api.add_acreage_report_line(
            report["id"],
            create_acreage_report_line_payload(
                field_id=field["id"], planted_acres=40.00, prevented_planted_acres=20.00
            ),
            producer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_ACRES_EXCEED_FIELD.value)


class TestMembershipReverseLookup:
    def test_fk_reverse_reachable_memberships_by_farm(self, api, specialist):
        """PRD §3.1: "Memberships may be listed filtered by `producer_id` or
        `farm_id`, and tracts may be listed filtered by `farm_id` or
        `reconstituted_from_tract_id`."
        PRD §4: "| GET | /fsa/farms/{id}/memberships | List memberships on a
        farm | Producer, CountySpecialist, CountyExecutiveDirector,
        CountyCommittee |"

        Design: Corner/endpoints/fk_reverse_reachable_memberships_by_farm
        """
        farm, producer, membership = create_farm_with_member()
        data, _meta = validate_paginated(
            api.list_farm_memberships(farm["id"], specialist)
        )
        assert len(data) == 1, f"exactly one membership exists, got {len(data)}"
        assert_membership(data[0])
        assert data[0]["id"] == membership["id"]
        assert data[0]["producer_id"] == producer["id"]


class TestPaginationConsistency:
    def test_pagination_limit_offset_consistency(self, api, specialist):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query
        parameters. The default `limit` is 10; the minimum is 1 and the maximum
        is 100. The default `offset` is 0. Results are sorted by `created_at`
        ascending. The `meta` block of a list response includes `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/cross_cutting_complexity_layers/pagination_limit_offset_consistency
        """
        for i in range(3):
            api_result = api.create_producer(
                create_producer_payload(
                    producer_name=f"Paginated {i}", tax_id_last4=str(i + 1)
                ),
                specialist,
            )
            validate_success(api_result, 201)
        page1, meta1 = validate_paginated(
            api.list_producers(specialist, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] >= 3
        assert meta1["has_more"] is True, "a second page must exist"
        page2, meta2 = validate_paginated(
            api.list_producers(specialist, params={"limit": 2, "offset": 2})
        )
        assert len(page2) >= 1
        assert meta2["has_more"] is False, (
            "offset 2 with limit 2 over three rows leaves no further page"
        )
        ids = {p["id"] for p in page1} | {p["id"] for p in page2}
        assert len(ids) == len(page1) + len(page2), "pages must not overlap"

"""List pagination envelope, domain filters, uniqueness and field-range rules."""
from test_helpers import (
    ApiErrorId,
    add_customer,
    add_design,
    add_science,
    add_site,
    add_staff,
    api_client,
    approve_design,
    create_site_payload,
    setup_company,
    setup_site_with_science,
    submit_design,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestListPagination:
    def test_list_endpoints_paginate_with_envelope_fields(self, api):
        """PRD section 2.3: "Every list endpoint accepts two optional query
        parameters: `limit`, the page size, defaulting to 10 with a minimum of 1
        and a maximum of 100; and `offset`, the number of records to skip,
        defaulting to 0."
        PRD section 2.3: "The `meta` object of a list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_endpoints_paginate_with_envelope_fields
        """
        ctx = setup_company()
        add_staff(ctx, designer=False, officer=False, scientist=False)
        add_customer(ctx)
        for i in (1, 2, 3):
            add_site(ctx, parcel_id=f"P-{i}", address_line=f"{i} Meadow Ln",
                     high_water_table=(i == 3))

        page1, meta1 = validate_paginated(api_client.list_sites(
            ctx.cid, ctx.cu, ctx.manager, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api_client.list_sites(
            ctx.cid, ctx.cu, ctx.manager, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False

        ids = {row["id"] for row in page1} | {row["id"] for row in page2}
        assert len(ids) == 3, "the two pages are disjoint and enumerate all 3 sites"


class TestUniquenessAndRanges:
    def test_duplicate_parcel_id_within_company_rejected(self, api):
        """PRD section 3.1: "Sites — county tax parcels — are registered beneath
        a customer with a `parcel_id` unique within the installer company".
        PRD section 2.9: "(19) field ranges and uniqueness — `ERR_INVALID_REQUEST`".

        Design: Corner/entities/duplicate_parcel_id_within_company_rejected
        """
        ctx = setup_company()
        add_staff(ctx, designer=False, officer=False, scientist=False)
        add_customer(ctx)
        add_site(ctx, parcel_id="P-1")

        dup = api_client.create_site(
            ctx.cid, ctx.cu,
            create_site_payload(parcel_id="P-1", address_line="1 Meadow Ln DUPLICATE"),
            ctx.manager)
        validate_error(dup, ApiErrorId.ERR_INVALID_REQUEST)

        other = setup_company(legal_name="Bedrock Septic Inc", license_number="BS-200")
        add_staff(other, designer=False, officer=False, scientist=False,
                  manager=True)
        # The second company's manager record differs; re-point identity headers.
        add_customer(other, full_name="Oscar Owner", email="oscar@example.com",
                     phone="555-0200")
        ok = api_client.create_site(
            other.cid, other.cu,
            create_site_payload(parcel_id="P-1"), other.manager)
        validate_success(ok, 201)

    def test_bedroom_count_out_of_range_rejected(self, api):
        """PRD section 3.3: "the payload names the `designer_id`, a
        `soil_evaluation_id`, a `percolation_test_id`, a `bedroom_count` between
        1 and 12, and a `system_type` of `GRAVITY`, `PRESSURE_DISTRIBUTION`,
        `MOUND`, or `AEROBIC` chosen within the envelope the site data allows."
        PRD section 2.9: "(19) field ranges and uniqueness — `ERR_INVALID_REQUEST`".

        Design: Corner/entities/bedroom_count_out_of_range_rejected
        """
        ctx = setup_site_with_science()
        for bad in (0, 13):
            resp = api_client.create_design(
                ctx.cid, ctx.cu, ctx.s,
                {"designer_id": ctx.d1, "soil_evaluation_id": ctx.e1,
                 "percolation_test_id": ctx.pt1, "bedroom_count": bad,
                 "system_type": "GRAVITY"},
                ctx.designer)
            validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestStatusFilter:
    def test_list_endpoints_support_status_filters(self, api):
        """PRD section 2.3: "Site, soil evaluation, percolation test, design,
        permit, installation, variance request, maintenance contract, and repair
        case lists accept a `status` filter".

        Design: Corner/endpoints/list_endpoints_support_status_filters
        """
        ctx = setup_site_with_science()
        da = add_design(ctx, bedroom_count=3)
        db = add_design(ctx, bedroom_count=4)
        submit_design(ctx, db["id"])
        approve_design(ctx, db["id"])

        drafts, meta_d = validate_paginated(api_client.list_designs(
            ctx.cid, ctx.cu, ctx.s, ctx.manager, params={"status": "DRAFT"}))
        assert len(drafts) == 1 and drafts[0]["id"] == da["id"]
        assert meta_d["total_count"] == 1

        approved, meta_a = validate_paginated(api_client.list_designs(
            ctx.cid, ctx.cu, ctx.s, ctx.manager, params={"status": "APPROVED"}))
        assert len(approved) == 1 and approved[0]["id"] == db["id"]
        assert meta_a["total_count"] == 1

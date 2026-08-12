"""Bid specification lifecycle: the addendum loop, publish guards, and
foundational record defaults (PRD §2.4, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, make_district_buyer_headers, validate_error,
    validate_success, add_spec_line, close_spec, create_district, create_spec,
    get_spec, issue_addendum, publish_spec, set_clock,
)


class TestBidSpecAddendumCycle:
    def test_addendum_cycle_two_full_loops_bump_spec_version(self, api):
        """PRD §3.2: "Publishing moves a specification from `DRAFT` to `PUBLISHED`,
        and the first publish leaves `spec_version` at 1."
        PRD §3.2: "Re-publishing from `ADDENDUM_ISSUED` returns the specification
        to `PUBLISHED` and increments `spec_version` by one"

        Design: Difficulty/non_linear_state_machine/bidspec_addendum_cycle_republishes_with_version_bumps
        """
        set_clock()
        district = create_district()
        d_id = district["id"]
        spec = create_spec(d_id)
        add_spec_line(spec["id"], d_id)

        first = validate_success(api.publish_bid_spec(spec["id"], make_district_buyer_headers(d_id)))
        assert first["status"] == "PUBLISHED" and first["spec_version"] == 1

        add1 = validate_success(api.issue_addendum(
            spec["id"], {"addendum_note": "clarify glide spec"}, make_district_buyer_headers(d_id)))
        assert add1["status"] == "ADDENDUM_ISSUED"

        second = validate_success(api.publish_bid_spec(spec["id"], make_district_buyer_headers(d_id)))
        assert second["status"] == "PUBLISHED" and second["spec_version"] == 2

        add2 = validate_success(api.issue_addendum(
            spec["id"], {"addendum_note": "extend Q&A"}, make_district_buyer_headers(d_id)))
        assert add2["status"] == "ADDENDUM_ISSUED"

        third = validate_success(api.publish_bid_spec(spec["id"], make_district_buyer_headers(d_id)))
        assert third["status"] == "PUBLISHED" and third["spec_version"] == 3

        closed = validate_success(api.close_bid_spec(spec["id"], make_district_buyer_headers(d_id)))
        assert closed["status"] == "CLOSED"

    def test_addendum_from_closed_reopens_and_republish_bumps_version(self, api):
        """PRD §3.2: "Issuing an addendum — an action carrying a free-text
        `addendum_note` — moves a specification from `PUBLISHED` to
        `ADDENDUM_ISSUED`, from `CLOSED` to `ADDENDUM_ISSUED`, or from `AWARDED`
        to `ADDENDUM_ISSUED` (the post-award amendment entry), and each issuance
        increments the specification's `version`."
        PRD §3.2: "Re-publishing from `ADDENDUM_ISSUED` returns the specification
        to `PUBLISHED` and increments `spec_version` by one"

        Design: Difficulty/non_linear_state_machine/bidspec_addendum_cycle_republishes_with_version_bumps
        """
        set_clock()
        district = create_district()
        d_id = district["id"]
        spec = create_spec(d_id)
        add_spec_line(spec["id"], d_id)
        publish_spec(spec["id"], d_id)
        closed = close_spec(spec["id"], d_id)
        assert closed["status"] == "CLOSED"

        reopened = validate_success(api.issue_addendum(
            spec["id"], {"addendum_note": "post-close clarification"}, make_district_buyer_headers(d_id)))
        assert reopened["status"] == "ADDENDUM_ISSUED"

        republished = validate_success(api.publish_bid_spec(spec["id"], make_district_buyer_headers(d_id)))
        assert republished["status"] == "PUBLISHED" and republished["spec_version"] == 2


class TestBidSpecGuards:
    def test_publish_from_published_rejected(self, api):
        """PRD §3.2: "Publishing moves a specification from `DRAFT` to `PUBLISHED`,
        and the first publish leaves `spec_version` at 1."
        PRD §2.8: "the target resource's current status permits the requested
        transition (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/bidspec_publish_from_published_returns_invalid_state
        """
        set_clock()
        district = create_district()
        d_id = district["id"]
        spec = create_spec(d_id)
        add_spec_line(spec["id"], d_id)
        first = publish_spec(spec["id"], d_id)
        assert first["spec_version"] == 1

        resp = api.publish_bid_spec(spec["id"], make_district_buyer_headers(d_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_spec(spec["id"], d_id)
        assert after["spec_version"] == 1 and after["status"] == "PUBLISHED"

    def test_spec_line_missing_qty_rejected(self, api):
        """PRD §2.8: "required fields present, types valid, enum membership honored,
        quantities, counts, capacities and costs at least 1 where applicable ...
        Violations are `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "a total `qty` of at least 1 that the district may order against the line"

        Design: Corner/entities/spec_line_missing_qty_returns_invalid_request
        """
        set_clock()
        district = create_district()
        d_id = district["id"]
        spec = create_spec(d_id)
        payload = {
            "bid_spec_id": spec["id"],
            "manufacturer": "Acme",
            "model": "Desk-100",
            "max_unit_price_cents": 13000,
        }
        resp = api.create_spec_line(payload, make_district_buyer_headers(d_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestDistrictDefaults:
    def test_district_creation_applies_enrollment_default(self, api):
        """PRD §3.1: "an `extended_warranty_enrolled` flag, defaulting to false, that
        selects the extended prorated warranty coverage variant described in §3.9"
        PRD §2.4: "Every resource in this API — districts, school sites, bid
        specifications, spec lines, cooperative price agreements, awards, purchase
        orders, PO lines, shipments, crews, install tasks, damage reports,
        backorder notices, and warranty claims — carries a standard set of
        system-managed fields"

        Design: Corner/entities/district_creation_applies_enrollment_default
        """
        set_clock()
        resp = api.create_district(
            {"name": "District D1", "annual_cap_cents": 5000000},
            TEST_USERS["admin_headers"],
        )
        data = validate_success(resp, 201)
        assert data["extended_warranty_enrolled"] is False
        assert data["version"] == 1
        assert data["created_at"]

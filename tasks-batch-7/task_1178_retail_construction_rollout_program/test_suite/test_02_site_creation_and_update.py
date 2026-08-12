"""Site creation defaults, opening-commitment cascade, listing/pagination,
envelope shape, existence checks, required fields, versioning, OCC on site
update, the grand-opening date lock, and invalid build start."""
from test_helpers import (
    ApiErrorId,
    assert_opening_commitment,
    assert_site,
    create_approved_drawing_set,
    create_site,
    read_commitment_for_site,
    read_site,
    set_clock,
    setup_program_with_market,
    setup_site_in_permitting,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_SITE_ID = "11111111-2222-4333-8444-555555555555"


class TestSiteCreation:
    def test_site_create_auto_creates_opening_commitment(self, api,
                                                         program_director_headers):
        """PRD §3.1: "A new site starts `LISTED` with `readiness_posture`
        `ROUGH` and `base_contract_cents` 0, and exactly one
        `OpeningCommitment` is auto-created alongside it, its
        `committed_open_on` mirroring `target_open_date` and its posture
        reading `PROTECTED` (§3.8)."

        Design: Corner/entities/c_site_create_auto_creates_opening_commitment
        """
        ctx = setup_program_with_market()
        resp = api.create_site(
            {
                "program_id": ctx["program"]["id"],
                "market_id": ctx["market"]["id"],
                "municipality_code": "TX-DAL",
                "address": "100 Main St",
                "square_footage": 4000,
                "phase_wave": 1,
                "budget_allocation_cents": 10_000_000,
                "target_open_date": "2026-09-01",
            },
            headers=program_director_headers)
        site = validate_success(resp, expected_status=201)
        assert_site(site)
        assert site["status"] == "LISTED"
        assert site["readiness_posture"] == "ROUGH"
        assert site["base_contract_cents"] == 0

        commitment = read_commitment_for_site(site["id"])
        assert_opening_commitment(commitment)
        assert commitment["committed_open_on"] == "2026-09-01"
        assert commitment["protection_posture"] == "PROTECTED"

    def test_site_create_missing_required_field_returns_400(self, api,
                                                            program_director_headers):
        """PRD §2.10: "Request shape — missing or malformed fields, enum
        values outside their declared range, numeric range violations such as
        an out-of-range technical score (`ERR_INVALID_REQUEST`)."
        PRD §3.1: "the director, who supplies the `program_id` and
        `market_id`, the site's `municipality_code`, its street `address`, its
        gross `square_footage` (the permit fee basis), the phased schedule
        wave number `phase_wave`, the planned budget envelope
        `budget_allocation_cents`, and the committed grand-opening date
        `target_open_date`."

        Design: Corner/entities/c_site_create_missing_required_field_returns_400
        """
        ctx = setup_program_with_market()
        resp = api.create_site(
            {
                "program_id": ctx["program"]["id"],
                "market_id": ctx["market"]["id"],
                "municipality_code": "TX-DAL",
                "address": "100 Main St",
                "square_footage": 4000,
                "phase_wave": 1,
                "target_open_date": "2026-09-01",
                # budget_allocation_cents omitted
            },
            headers=program_director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestSiteListing:
    def test_site_list_filter_and_pagination(self, api, program_director_headers):
        """PRD §3.1: "List endpoints support filtering throughout this
        subsection: programs filter by `status`; markets by `program_id` and
        `status`; sites by `program_id`, `market_id`, `status`, and
        `phase_wave`."
        PRD §2.3: "The `limit` parameter caps the number of items returned;
        when omitted it defaults to 10, and it accepts a minimum of 1 and a
        maximum of 100."

        Design: Corner/entities/c_site_list_filter_and_pagination
        """
        ctx = setup_program_with_market()
        create_site(ctx["program"]["id"], ctx["market"]["id"], address="100 Main St")
        create_site(ctx["program"]["id"], ctx["market"]["id"], address="200 Elm St",
                    square_footage=3500, phase_wave=2,
                    budget_allocation_cents=9_000_000, target_open_date="2026-10-01")

        resp = api.list_sites(headers=program_director_headers,
                              params={"market_id": ctx["market"]["id"],
                                      "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1

    def test_envelope_and_pagination_shape(self, api, program_director_headers,
                                           finance_controller_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.3: "Paginated list responses carry four fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/c_envelope_and_pagination_shape
        """
        ctx = setup_program_with_market()
        create_site(ctx["program"]["id"], ctx["market"]["id"], address="100 Main St")
        create_site(ctx["program"]["id"], ctx["market"]["id"], address="200 Elm St",
                    square_footage=3500, phase_wave=2,
                    budget_allocation_cents=9_000_000, target_open_date="2026-10-01")

        resp = api.list_sites(headers=finance_controller_headers)
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in meta
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0


class TestSiteExistence:
    def test_site_get_not_found_returns_404(self, api, program_director_headers):
        """PRD §2.9: "Where an endpoint path contains resource identifiers,
        the server validates them for existence sequentially from left to
        right, rejecting with `ERR_NOT_FOUND` at the first identifier that
        does not resolve to an existing resource."

        Design: Corner/entities/c_site_get_not_found_returns_404
        """
        set_clock()
        resp = api.get_site(UNKNOWN_SITE_ID, headers=program_director_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_existence_precedes_state_on_remove(self, api, program_director_headers):
        """PRD §2.9: "Where an endpoint path contains resource identifiers,
        the server validates them for existence sequentially from left to
        right, rejecting with `ERR_NOT_FOUND` at the first identifier that
        does not resolve to an existing resource."

        Design: Corner/validations/c_existence_precedes_state_on_remove
        """
        set_clock()
        resp = api.remove_site(UNKNOWN_SITE_ID, headers=program_director_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSiteVersioningAndUpdate:
    def test_version_increments_on_each_mutation(self, api, program_director_headers,
                                                 design_manager_headers):
        """PRD §2.4: "`version` (integer): a system-managed counter that
        increments with every mutation."
        PRD §3.2: "Both transitions increment the site's `version`."

        Design: Corner/cross_cutting_complexity_layers/c_version_increments_on_each_mutation
        """
        ctx = setup_program_with_market()
        create_approved_drawing_set(ctx["program"]["id"], jurisdiction_code="TX-DAL")
        site = create_site(ctx["program"]["id"], ctx["market"]["id"])
        v_at_creation = site["version"]

        resp = api.advance_site_design(site["id"], headers=design_manager_headers)
        v_after_advance = validate_success(resp)["version"]
        assert v_after_advance == v_at_creation + 1, (
            f"advance-design must increment version by exactly 1: "
            f"{v_at_creation} -> {v_after_advance}")

        resp = api.submit_site_design(site["id"], headers=design_manager_headers)
        v_after_submit = validate_success(resp)["version"]
        assert v_after_submit == v_after_advance + 1, (
            f"submit-design must increment version by exactly 1: "
            f"{v_after_advance} -> {v_after_submit}")

    def test_occ_site_patch_stale_version(self, api, program_director_headers):
        """PRD §2.7: "Three write operations require the client to supply
        `expected_site_version`, carrying the `version` of the target site as
        the client last observed it: the site update operation, change-order
        approval, and turnover acceptance. If the supplied value does not
        equal the site's current `version`, the request is rejected with
        `ERR_STALE_VERSION` and HTTP status 412."

        Design: Corner/cross_cutting_complexity_layers/c_occ_site_patch_stale_version
        """
        ctx = setup_program_with_market()
        site = create_site(ctx["program"]["id"], ctx["market"]["id"])
        stale_version = site["version"]

        resp = api.patch_site(site["id"],
                              {"budget_allocation_cents": 12_000_000,
                               "expected_site_version": stale_version},
                              headers=program_director_headers)
        updated = validate_success(resp)
        assert updated["version"] == stale_version + 1
        assert updated["budget_allocation_cents"] == 12_000_000

        resp = api.patch_site(site["id"],
                              {"budget_allocation_cents": 13_000_000,
                               "expected_site_version": stale_version},
                              headers=program_director_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert read_site(site["id"])["budget_allocation_cents"] == 12_000_000

    def test_open_date_lock_and_director_override(self, api, program_director_headers):
        """PRD §3.1: "The grand-opening date locks as soon as the site leaves
        `LISTED` or `DESIGN`: from `PERMITTING` onward, changing
        `target_open_date` is rejected with `ERR_OPEN_DATE_LOCKED` unless the
        request carries a `director_override_reason`. Any accepted date change
        synchronizes the commitment's `committed_open_on` and recomputes the
        forecast and protection posture, and every accepted update increments
        the site's `version`."

        Design: Corner/validations/c_open_date_lock_and_director_override
        """
        ctx = setup_site_in_permitting()
        site_id = ctx["site"]["id"]

        resp = api.patch_site(
            site_id,
            {"target_open_date": "2026-09-15",
             "expected_site_version": read_site(site_id)["version"]},
            headers=program_director_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_DATE_LOCKED)
        assert read_site(site_id)["target_open_date"] == "2026-09-01"

        resp = api.patch_site(
            site_id,
            {"target_open_date": "2026-09-15",
             "director_override_reason": "municipality backlog",
             "expected_site_version": read_site(site_id)["version"]},
            headers=program_director_headers)
        updated = validate_success(resp)
        assert updated["target_open_date"] == "2026-09-15"
        assert read_commitment_for_site(site_id)["committed_open_on"] == "2026-09-15"


class TestSiteTransitions:
    def test_site_start_build_from_listed_invalid(self, api,
                                                  site_superintendent_headers):
        """PRD §3.5: "Starting the build moves a site from `MOBILIZED` to
        `IN_BUILD` and requires the site's market to be `AWARDED`, failing
        with `ERR_MARKET_NOT_AWARDED` otherwise; the site's `version`
        increments."
        PRD §2.10: "State guards — the target resource is in a from-state that
        allows the operation, terminal states reject all further transitions,
        and domain state gates hold (`ERR_INVALID_STATE`,
        `ERR_ALREADY_TERMINAL`, `ERR_PROGRAM_NOT_ACTIVE`,
        `ERR_MARKET_NOT_BIDDING`, `ERR_MARKET_NOT_AWARDED`,
        `ERR_BID_PACKAGE_NOT_OPEN`, `ERR_CONTRACTOR_NOT_PREQUALIFIED`,
        `ERR_SITE_NOT_IN_BUILD`, `ERR_TURNOVER_ALREADY_REQUESTED`,
        `ERR_ACTIVE_SITES_REMAIN`, `ERR_TURNOVER_NOT_ACCEPTED`)."

        Design: Corner/state_machines/c_site_start_build_from_listed_invalid
        """
        ctx = setup_program_with_market()
        site = create_site(ctx["program"]["id"], ctx["market"]["id"])
        resp = api.start_site_build(site["id"], headers=site_superintendent_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert read_site(site["id"])["status"] == "LISTED"

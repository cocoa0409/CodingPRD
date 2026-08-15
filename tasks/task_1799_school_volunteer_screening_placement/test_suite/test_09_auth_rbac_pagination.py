"""Authentication, role-based access control, ownership, and pagination."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    confirm_placement,
    create_active_volunteer,
    create_lincoln_campus,
    create_open_opportunity,
    create_orient_module,
    create_volunteer_applied,
    create_volunteer_payload,
    file_incident,
    get_opportunity,
    initiate_background_check,
    log_hours,
    make_volunteer_headers,
    request_placement,
    validate_error,
    validate_paginated,
    validate_success,
)

DC = TEST_USERS["coordinator_headers"]
CA = TEST_USERS["campus_admin_headers"]


class TestAuthentication:
    def test_unauthenticated_request_rejected(self, api):
        """PRD: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the caller's
        operational capacity. The system recognizes exactly three roles:
        `DistrictCoordinator`, `CampusAdmin`, and `Volunteer`. A request with
        missing or malformed headers, or whose declared role is not one of
        these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_rejected
        """
        resp = api.list_volunteers({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

        bad_role = api.list_volunteers(
            {"X-User-ID": "mystery", "X-User-Role": "Superintendent"})
        validate_error(bad_role, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleEnforcement:
    def test_rbac_denied_exclusive_operations(self, api):
        """PRD: "A request whose role is not permitted on the targeted endpoint
        — or that fails a Volunteer-role ownership check — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD: "A `DistrictCoordinator` is district volunteer office staff and
        holds a superset of `CampusAdmin` powers, plus exclusive control over
        screening and district configuration: creating campuses, creating
        volunteer applications, initiating and adjudicating background checks
        and reading them, creating training modules, running the opportunity
        matching selector, revoking verified hour entries, adjudicating
        incident reports, granting manual recognition awards, and driving the
        logical clock."

        Design: Corner/rbac/rbac_denied_exclusive_operations
        """
        module = create_orient_module(
            required_contact_types=("SUPERVISED",))

        # v1 stuck mid-screening with a PENDING check.
        v1 = create_volunteer_applied("Screening Sam", "sam2@x.com",
                                      "SUPERVISED")
        check = initiate_background_check(v1, level="BASIC")

        # v2 fully ACTIVE with a PENDING hour entry and an OPEN incident.
        v2 = create_active_volunteer("Worker Wendy", "wendy@x.com",
                                     "SUPERVISED", module=module)["volunteer"]
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], capacity=2)
        placement = request_placement(opp["id"], v2["id"])
        confirm_placement(placement["id"])
        entry = log_hours(placement["id"], v2["id"], worked_date="2026-08-10",
                          hours=2.0)
        incident = file_incident(v2["id"], severity="LOW",
                                 description="Minor issue")

        # Volunteer attempting district configuration.
        rogue = api.create_campus(
            {"name": "Rogue Campus", "campus_code": "RGE",
             "badge_prefix": "RGE"}, make_volunteer_headers(v2["id"]))
        validate_error(rogue, ApiErrorId.ERR_FORBIDDEN)

        # CampusAdmin attempting background-check adjudication.
        ca_adjudicate = api.adjudicate_background_check(
            check["id"], {"findings": "NONE"}, CA)
        validate_error(ca_adjudicate, ApiErrorId.ERR_FORBIDDEN)

        # CampusAdmin attempting incident adjudication.
        ca_incident = api.adjudicate_incident(
            incident["id"], {"outcome": "UNFOUNDED"}, CA)
        validate_error(ca_incident, ApiErrorId.ERR_FORBIDDEN)

        # Volunteer verifying hours — even their own entry.
        vol_verify = api.verify_hour_entry(
            entry["id"], make_volunteer_headers(v2["id"]))
        validate_error(vol_verify, ApiErrorId.ERR_FORBIDDEN)

    def test_volunteer_ownership_read_rules(self, api):
        """PRD: "Volunteer-role ownership is enforced on the following
        operations, and a caller whose `X-User-ID` does not match the volunteer
        that owns the target resource is rejected with `ERR_FORBIDDEN`:
        reading a volunteer record, requesting a placement (the payload
        `volunteer_id`), reading a placement, logging hours against a placement
        (the placement must belong to the caller), reading an hour entry,
        checking out a check-in, and cancelling a placement."

        Design: Corner/rbac/volunteer_ownership_read_rules
        """
        v1 = create_volunteer_applied("Self Sue", "self@x.com", "SUPERVISED")
        v2 = create_volunteer_applied("Other Owen", "other@x.com", "SUPERVISED")

        own = validate_success(api.get_volunteer(
            v1["id"], make_volunteer_headers(v1["id"])), 200)
        assert own["email"] == "self@x.com"

        cross = api.get_volunteer(v2["id"], make_volunteer_headers(v1["id"]))
        validate_error(cross, ApiErrorId.ERR_FORBIDDEN)

    def test_coordinator_hierarchical_override_confirms(self, api):
        """PRD: "A `DistrictCoordinator` is district volunteer office staff and
        holds a superset of `CampusAdmin` powers"
        PRD: "Confirmation is the compliance chokepoint, performed by a
        `CampusAdmin` or `DistrictCoordinator`."

        Design: Corner/rbac/coordinator_hierarchical_override_confirms
        """
        recruited = create_active_volunteer("Override Oz", "oz@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], capacity=2)
        placement = request_placement(opp["id"], vid)

        confirmed = validate_success(
            api.confirm_placement(placement["id"], DC), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert get_opportunity(opp["id"])["committed_count"] == 1


class TestPagination:
    def test_pagination_limit_offset_and_has_more(self, api):
        """PRD: "The `limit` parameter caps the number of items returned; when
        omitted it defaults to 10, and it may not be less than 1 or greater
        than 100. The `offset` parameter says how many items to skip and
        defaults to 0."
        PRD: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."
        PRD: "The volunteer list — available to coordinators and campus
        administrators — can be filtered by `status`, `contact_type`, and
        `recognition_tier`"

        Design: Corner/endpoints/pagination_limit_offset_and_has_more
        """
        for name, email, ctype in (
                ("Page One", "p1@x.com", "SUPERVISED"),
                ("Page Two", "p2@x.com", "SUPERVISED"),
                ("Page Three", "p3@x.com", "UNSUPERVISED")):
            validate_success(api.create_volunteer(
                create_volunteer_payload(full_name=name, email=email,
                                         contact_type=ctype), DC), 201)

        page0, meta0 = validate_paginated(api.list_volunteers(
            DC, params={"limit": 2, "offset": 0}))
        assert len(page0) == 2
        assert meta0["total_count"] == 3
        assert meta0["has_more"] is True

        page2, meta2 = validate_paginated(api.list_volunteers(
            DC, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        filtered, meta_f = validate_paginated(api.list_volunteers(
            DC, params={"contact_type": "UNSUPERVISED"}))
        assert meta_f["total_count"] == 1
        assert len(filtered) == 1
        assert filtered[0]["email"] == "p3@x.com"

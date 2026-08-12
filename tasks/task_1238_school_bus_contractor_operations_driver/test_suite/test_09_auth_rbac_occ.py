"""Authentication and role/ownership authorization, and the three OCC-guarded
write operations."""
from test_helpers import (
    ApiErrorId,
    build_service_day,
    confirm_assignment,
    create_active_contract,
    create_active_driver,
    create_charter,
    create_contract,
    create_contract_payload,
    create_district,
    create_driver_applicant,
    create_quoted_charter,
    get_success_data,
    make_district_admin_headers,
    make_driver_headers,
    quote_charter,
    setup_ops_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OPS


class TestSchemaBeatsAuth:
    def test_create_contract_missing_header_and_bad_body_returns_400(self, api):
        """PRD section 2.8: "Every request passes through a fixed validation
        pipeline, and the order is part of the contract — when several checks
        would fail, the earliest one in this order determines the error
        returned:"
        PRD section 2.8: "1. **Schema and format.** The body parses, required
        fields are present, enum values are valid, and integers are in range;
        violations yield `ERR_INVALID_REQUEST` (HTTP 400)." — this rung precedes
        "2. **Authentication.** `X-User-Role` and `X-User-ID` are present and
        the role is recognized, else `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/create_contract_missing_header_and_bad_body_returns_400
        """
        # No X-User-Role / X-User-ID headers, and a body missing required fields.
        resp = api.create_contract({"bid_reference": "BID-BAD"}, None)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestAuthentication:
    def test_list_buses_missing_auth_headers_returns_401(self, api):
        """PRD section 2.1: "Every request must carry two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying
        the capacity in which they act."
        PRD section 2.1: "A request missing either header, or carrying an
        unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/list_buses_missing_auth_headers_returns_401
        """
        resp = api.list_buses(None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleDenials:
    def test_create_contract_forbidden_role_driver_returns_403(self, api):
        """PRD section 2.1: "A request whose role is not in the endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 4: POST /busops/contracts is authorized for ContractorOps
        only.

        Design: Corner/validations/create_contract_forbidden_role_driver_returns_403
        """
        district = create_district(name="D-VAL3")
        driver = create_driver_applicant(district["id"], full_name="D Val3",
                                         license_number="L260")
        resp = api.create_contract(
            create_contract_payload(district["id"], bid_reference="BID-V3"),
            make_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_rbac_driver_cannot_start_others_assignment_returns_forbidden(self, api):
        """PRD section 3.5: "Starting a run moves a driver's own `CONFIRMED`
        assignment to `EN_ROUTE`, permitted while the day stands `DISPATCH_OPEN`
        or `LOCKED` and only when the acting `Driver`'s identity matches the
        assignment's `driver_id`."
        PRD section 2.1: "When `X-User-Role` is `Driver`, `X-User-ID` is the
        `id` of the acting Driver; a driver may act only on assignments whose
        `driver_id` equals `X-User-ID` and may read only their own driver
        record, with the same `ERR_FORBIDDEN_OWNERSHIP` rejection on mismatch."

        Design: Corner/rbac/rbac_driver_cannot_start_others_assignment_returns_forbidden
        """
        ctx = setup_ops_scenario(district_name="D-RB3")
        driver_b = create_active_driver(ctx["district"]["id"], full_name="D B",
                                        license_number="L301")
        _day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])

        resp = api.start_assignment(assignments[0]["id"],
                                    make_driver_headers(driver_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
        fetched = validate_success(api.get_assignment(assignments[0]["id"], OPS))
        assert fetched["status"] == "CONFIRMED", "unchanged"


class TestOwnershipDenials:
    def test_award_contract_wrong_district_returns_forbidden(self, api):
        """PRD section 2.1: "When `X-User-Role` is `DistrictAdmin`, `X-User-ID`
        is the `id` of the acting District; ownership checks on any resource
        that resolves to a district — a contract, a charter under a contract, an
        invoice under a contract, an incident addressed to a district — compare
        the resource's district foreign key to `X-User-ID`, and a mismatch is
        rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/validations/award_contract_wrong_district_returns_forbidden
        """
        district_x = create_district(name="D-VAL4X")
        district_y = create_district(name="D-VAL4Y")
        contract = create_contract(district_y["id"], bid_reference="BID-V4")
        get_success_data(api.submit_contract(contract["id"], OPS))

        resp = api.award_contract(contract["id"],
                                  make_district_admin_headers(district_x["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
        fetched = validate_success(api.get_contract(contract["id"], OPS))
        assert fetched["status"] == "SUBMITTED"


class TestOptimisticConcurrency:
    def test_occ_contract_amendment_stale_returns_412(self, api):
        """PRD section 2.7: "Applying a pricing amendment to a Contract requires
        `expected_contract_version` in the request body, carrying the client's
        last observed `version` of that contract. If the contract's current
        `version` has advanced — for example because another amendment or a
        lifecycle transition landed since the client last read it — the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the amendment
        to be rebased on pricing terms the client has actually seen."
        PRD section 3.1: "A successful amendment increments the contract's
        `version` by one and bumps `amendment_seq`; a stale expected version is
        rejected with `ERR_STALE_VERSION`."

        Design: Corner/endpoints/occ_contract_amendment_stale_returns_412
        """
        district = create_district(name="D-EP1")
        contract = create_contract(district["id"], bid_reference="BID-EP1")
        get_success_data(api.submit_contract(contract["id"], OPS))
        district_headers = make_district_admin_headers(district["id"])
        get_success_data(api.award_contract(contract["id"], district_headers))
        activated = get_success_data(api.activate_contract(contract["id"], OPS))
        current_version = activated["version"]

        resp = api.amend_contract(
            contract["id"], {"expected_contract_version": current_version - 1,
                             "fuel_base_price_cents": 425},
            district_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        amended = validate_success(api.amend_contract(
            contract["id"], {"expected_contract_version": current_version,
                             "fuel_base_price_cents": 425},
            district_headers))
        assert amended["version"] == current_version + 1
        assert amended["amendment_seq"] == 1
        assert amended["fuel_base_price_cents"] == 425, "rebased amendment applied"

    def test_occ_charter_approve_version_pinning_returns_412(self, api):
        """PRD section 2.7: "Approving a CharterTrip requires
        `expected_charter_trip_version`. Because issuing a quote increments the
        trip's version, an approval carrying a pre-quote version pins a price
        the district never saw; the mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/endpoints/occ_charter_approve_version_pinning_returns_412
        """
        district = create_district(name="D-EP2")
        contract = create_active_contract(district["id"], bid_reference="BID-EP2")
        charter = create_charter(contract["id"], district["id"],
                                 purpose="Versioned trip")
        pre_quote_version = charter["version"]
        quoted = quote_charter(charter["id"])
        assert quoted["version"] > pre_quote_version, "quoting bumps the version"

        district_headers = make_district_admin_headers(district["id"])
        resp = api.approve_charter(
            charter["id"], {"expected_charter_trip_version": pre_quote_version,
                            "deposit_cents": 0},
            district_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        approved = get_success_data(api.approve_charter(
            charter["id"], {"expected_charter_trip_version": quoted["version"],
                            "deposit_cents": 0},
            district_headers))
        assert approved["status"] == "APPROVED", "post-quote pin succeeds"

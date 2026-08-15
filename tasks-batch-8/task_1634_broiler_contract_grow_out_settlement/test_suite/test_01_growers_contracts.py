"""Grower onboarding, contracts, and house identity rules (PRD §2, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_contract,
    assert_grower,
    assert_house,
    create_contract_payload,
    create_grower_payload,
    create_house_payload,
    get_success_data,
    issue_loan,
    make_grower_headers,
    renew_contract_payload,
    set_logical_clock,
    setup_growing_flock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestGrowerOnboarding:
    def test_grower_creation_applies_defaults(self, api, admin_headers):
        """PRD §3.1: "A new grower's `status` starts at `ACTIVE`, with
        `performance_rating` null (there is no settled history yet),
        `loan_outstanding_cents` at zero, and `house_count` at zero."

        Design: Corner/entities/grower_creation_success_and_defaults
        """
        created = validate_success(
            api.create_grower(
                create_grower_payload(grower_code="G-NEW", full_name="New Grower"),
                admin_headers),
            expected_status=201)
        assert_grower(created)

        data = validate_success(api.get_grower(created["id"], admin_headers))
        assert data["status"] == "ACTIVE", "grower status must default to ACTIVE"
        assert data["loan_outstanding_cents"] == 0
        assert data["house_count"] == 0
        assert data["performance_rating"] is None, \
            "performance_rating is null until the first settled flock"

    def test_grower_missing_grower_code_rejected(self, api, admin_headers):
        """PRD §3.1: "An `IntegratorAdmin` creates a `Grower` by supplying a
        `grower_code` — unique across all growers and immutable once created —
        together with the grower's legal `full_name`."
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format".

        Design: Corner/entities/grower_missing_required_field_returns_invalid_request
        """
        resp = api.create_grower({"full_name": "No Code"}, admin_headers)
        assert 400 <= resp.status_code < 500, (
            f"missing grower_code must be a client error, got {resp.status_code}")
        body = resp.json()
        assert body.get("response_type") == "error"
        error_data = body["data"]
        assert isinstance(error_data.get("error_id"), str) and error_data["error_id"]
        assert isinstance(error_data.get("message"), str) and error_data["message"]

    def test_grower_not_found_returns_404(self, api, admin_headers):
        """PRD §2.5: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not resolve to an existing
        resource, before any later identifier or any body field is examined."

        Design: Corner/entities/grower_not_found_returns_404
        """
        resp = api.get_grower(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_grower_list_pagination_envelope(self, api, admin_headers):
        """PRD §2.3: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."
        PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by their creation timestamp in ascending order."

        Design: Corner/entities/grower_list_pagination_envelope
        """
        for code, name in (("G-L1", "List One"), ("G-L2", "List Two"),
                           ("G-L3", "List Three")):
            get_success_data(
                api.create_grower(create_grower_payload(grower_code=code,
                                                        full_name=name),
                                  admin_headers))

        body = api.list_growers(admin_headers, params={"limit": 1, "offset": 0})
        page0, meta = validate_paginated(body)
        assert body.json()["response_type"] == "array"
        assert meta["total_count"] == 3
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["has_more"] is True
        assert len(page0) == 1

        page1, meta1 = validate_paginated(
            api.list_growers(admin_headers, params={"limit": 1, "offset": 1}))
        assert len(page1) == 1
        assert page1[0]["id"] != page0[0]["id"], \
            "ascending creation order makes consecutive pages disjoint"


class TestHouseIdentity:
    def test_house_no_unique_within_grower(self, api, admin_headers):
        """PRD §3.1: "Each `House` is created by an `IntegratorAdmin` under a
        grower via a payload carrying the owner `grower_id`, a grower-scoped
        `house_no` (unique within that grower, such as H1), and a positive
        `capacity_birds`."
        PRD §2.8: "12. Uniqueness — no duplicate of a unique identifier
        (`ERR_DUPLICATE`)."

        Design: Corner/entities/house_no_unique_within_grower
        """
        g1 = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-D1",
                                                    full_name="Dup One"),
                              admin_headers))
        g2 = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-D2",
                                                    full_name="Dup Two"),
                              admin_headers))
        first = get_success_data(
            api.create_house(create_house_payload(g1["id"], house_no="H1",
                                                  capacity_birds=5000),
                             admin_headers))
        assert_house(first)

        dup = api.create_house(create_house_payload(g1["id"], house_no="H1",
                                                    capacity_birds=6000),
                               admin_headers)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE)

        other = validate_success(
            api.create_house(create_house_payload(g2["id"], house_no="H1",
                                                  capacity_birds=6000),
                             admin_headers),
            expected_status=201)
        assert_house(other)


class TestContractLifecycle:
    def test_contract_activate_from_active_rejected(self, api, admin_headers):
        """PRD §3.2: "Activation moves a contract `DRAFT` → `ACTIVE` and is
        performed by an `IntegratorAdmin`."
        PRD §2.8: "5. Transition legality — the target entity is in a from-state
        of the requested transition (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/contract_activate_from_active_rejected
        """
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-S1",
                                                    full_name="State One"),
                              admin_headers))
        get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H1",
                                                  capacity_birds=5000),
                             admin_headers))
        contract = get_success_data(
            api.create_contract(create_contract_payload(grower["id"],
                                                        contract_no="C-S1"),
                                admin_headers))
        activated = validate_success(api.activate_contract(contract["id"],
                                                           admin_headers))
        assert activated["status"] == "ACTIVE"

        resp = api.activate_contract(contract["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        data = validate_success(api.get_contract(contract["id"], admin_headers))
        assert data["status"] == "ACTIVE", "rejected re-activation must not move the contract"

    def test_contract_terminate_blocked_by_flocks_in_flight(self, api,
                                                            admin_headers):
        """PRD §3.2: "It is blocked — with `ERR_FLOCKS_IN_FLIGHT` (HTTP 409) —
        while any flock grown under the contract is still in a non-terminal
        state, meaning `PLANNED`, `PLACED`, `GROWING`, `CATCH_SCHEDULED`, or
        `HARVESTED`."

        Design: Corner/validations/contract_terminate_blocked_by_flocks_in_flight
        """
        ctx = setup_growing_flock(grower_code="G-V3", full_name="Valid Three",
                                  contract_no="C-V3", group_code="WK-V3",
                                  flock_no="F-V3", placed_head=1000,
                                  feed_lbs=1000, set_clock_to=None)
        assert ctx["flock"]["status"] == "GROWING"

        resp = api.terminate_contract(ctx["contract"]["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_FLOCKS_IN_FLIGHT)

        data = validate_success(api.get_contract(ctx["contract"]["id"],
                                                 admin_headers))
        assert data["status"] == "ACTIVE", \
            "a termination blocked by in-flight flocks must not move the contract"


class TestContractRenewalDependsOnLoanPresence:
    def _setup_renewal_pending(self, api):
        admin = TEST_USERS["admin_headers"]
        set_logical_clock("2026-08-01T00:00:00Z")
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-X2",
                                                    full_name="Cross Grower 2"),
                              admin))
        get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H1",
                                                  capacity_birds=5000),
                             admin))
        get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H2",
                                                  capacity_birds=5000),
                             admin))
        contract = get_success_data(
            api.create_contract(create_contract_payload(grower["id"],
                                                        contract_no="C-X2"),
                                admin))
        contract = get_success_data(api.activate_contract(contract["id"], admin))
        contract = get_success_data(api.impose_upgrade(contract["id"], admin))
        assert contract["upgrade_required"] is True
        contract = get_success_data(
            api.request_renewal(contract["id"], make_grower_headers(grower["id"])))
        assert contract["status"] == "RENEWAL_PENDING"
        return grower, contract

    def test_renew_blocked_while_upgrade_requirement_unsatisfied(
            self, api, admin_headers):
        """PRD §3.2: "Two preconditions guard renewal completion, and their
        violation is reported as `ERR_RENEWAL_BLOCKED` (HTTP 422). First, if the
        contract's `upgrade_required` flag is true, the grower must hold a
        `GrowerLoan` whose `purpose` is `CAPITAL_UPGRADE` and whose status is
        `ISSUED` or `REPAID` — the integrator's capital-upgrade requirement is
        satisfied by financing it, not by promising to."

        Design: Difficulty/cross_entity_state_dependency/contract_renewal_depends_on_loan_presence
        """
        _grower, contract = self._setup_renewal_pending(api)

        resp = api.renew_contract(contract["id"], renew_contract_payload(),
                                  admin_headers)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_BLOCKED)

        data = validate_success(api.get_contract(contract["id"], admin_headers))
        assert data["status"] == "RENEWAL_PENDING", \
            "a blocked renewal must not move the contract"

    def test_renew_succeeds_after_capital_upgrade_loan_issued(
            self, api, admin_headers):
        """PRD §3.9: "A `CAPITAL_UPGRADE`-purpose loan is what satisfies a
        contract's `upgrade_required` flag for renewal (§3.2)."
        PRD §3.2: "Completing a renewal supplies `new_term_end_date` and
        `new_committed_house_count` in the payload; on success the contract's
        `term_end_date` and `committed_house_count` are replaced with those
        values, and the grower's `house_count` is recomputed."

        Design: Difficulty/cross_entity_state_dependency/contract_renewal_depends_on_loan_presence
        """
        grower, contract = self._setup_renewal_pending(api)
        issue_loan(grower["id"], 5000000, 20, "CAPITAL_UPGRADE")

        renewed = validate_success(
            api.renew_contract(contract["id"], renew_contract_payload(),
                               admin_headers))
        assert_contract(renewed)
        assert renewed["status"] == "RENEWED"
        assert renewed["term_end_date"] == "2029-01-01"
        assert renewed["committed_house_count"] == 2

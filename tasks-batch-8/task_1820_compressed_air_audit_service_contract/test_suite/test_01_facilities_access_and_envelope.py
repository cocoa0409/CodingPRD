"""Facility creation/lifecycle, access control, and response-envelope claims."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_facility,
    assert_iso8601_millis,
    assert_service_contract,
    create_and_activate_contract,
    create_facility,
    create_facility_payload,
    create_verified_survey,
    get_facility,
    is_valid_uuid,
    make_contract_manager_headers,
    make_dealer_admin_headers,
    make_energy_engineer_headers,
    make_facility_manager_headers,
    make_service_tech_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_dealer_admin_headers()
ENGINEER = make_energy_engineer_headers("eng-1")
TECH = make_service_tech_headers("tech-1")
CONTRACT_MGR = make_contract_manager_headers()


class TestFacilityCreationAndEnvelope:
    def test_facility_create_defaults_and_system_fields(self, api):
        """PRD §3.1: "A new facility starts in `ONBOARDING` status with `posture`
        `NORMAL` and both computed counters at zero: `repair_committed_cents`, the
        sum of `repair_quote_cents` over the facility's leak tags in
        `REPAIR_AUTHORIZED`, `REPAIRED`, or `VERIFIED_CLOSED`, and
        `rental_escrow_cents`, the sum of `deposit_cents` over the facility's
        rental reservations in `RESERVED` or `ON_RENT`."
        PRD §2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created."
        PRD §4: "Operations that create a new resource return `201 Created`"

        Design: Corner/entities/corner_facility_create_defaults_and_system_fields
        """
        resp = api.create_facility(
            create_facility_payload(
                name="F-ENT",
                utility_rate_cents_per_kwh=12,
                operating_hours_per_year=6000,
                repair_budget_cents=5000000,
            ),
            ADMIN,
        )
        facility = validate_success(resp, 201)
        assert_facility(facility)
        assert resp.json()["response_type"] == "object"
        assert facility["status"] == "ONBOARDING", "initial lifecycle state must be ONBOARDING"
        assert facility["posture"] == "NORMAL", "initial posture must be NORMAL"
        assert facility["repair_committed_cents"] == 0
        assert facility["rental_escrow_cents"] == 0
        assert is_valid_uuid(facility["id"]), "id must be a bare UUID"
        assert_iso8601_millis(facility["created_at"], "created_at")

    def test_get_nonexistent_compressor_returns_not_found(self, api):
        """PRD §2.9: "path-template resource identifiers resolve,
        validated left to right; the first identifier that does not resolve yields
        `ERR_NOT_FOUND` (HTTP 404) before any later segment is examined."

        Design: Corner/entities/corner_get_nonexistent_compressor_returns_not_found
        """
        resp = api.get_compressor(NON_EXISTENT_UUID, TECH)
        assert resp.status_code == 404
        assert resp.json()["response_type"] == "error"
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_missing_required_field_invalid_request(self, api):
        """PRD §2.9: "required fields are
        present, types are valid, enum values fall in their declared sets, dates are
        well-formed ISO values, and the domain input rules hold: `window_end_date`
        may not precede `window_start_date`, `target_pressure_psi` must be strictly
        below `baseline_pressure_psi`, and `corrected_measured_kwh` is required
        exactly when a dispute `outcome` is `UPHELD`. Failures here yield
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/corner_missing_required_field_invalid_request
        """
        resp = api.create_facility(
            {
                "name": "F-X",
                "utility_rate_cents_per_kwh": 12,
                "operating_hours_per_year": 6000,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_missing_auth_header_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value
        outside the declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/corner_missing_auth_header_unauthenticated
        """
        resp = api.list_facilities(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/endpoints/corner_list_pagination_envelope
        """
        for name in ("F-PG1", "F-PG2", "F-PG3"):
            create_facility(name=name, activate=False)

        resp1 = api.list_facilities(ADMIN, params={"limit": 2, "offset": 0})
        data1, meta1 = validate_paginated(resp1)
        assert resp1.json()["response_type"] == "array"
        assert len(data1) == 2, f"page 1 should hold 2 rows, got {len(data1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        resp2 = api.list_facilities(ADMIN, params={"limit": 2, "offset": 2})
        data2, meta2 = validate_paginated(resp2)
        assert len(data2) == 1, f"page 2 should hold 1 row, got {len(data2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestFacilityLifecycle:
    def test_offboarded_terminal_lockdown(self, api):
        """PRD §3.1: "A clean offboard lands the facility in `OFFBOARDED`, its
        terminal state."
        PRD §2.9: "An undeclared transition yields `ERR_INVALID_STATE_TRANSITION`
        (HTTP 409); named gates yield their own errors such as
        `ERR_FACILITY_NOT_ACTIVE` or `ERR_PROFILE_NOT_LOCKED`."

        Design: Corner/state_machines/corner_offboarded_terminal_lockdown
        """
        facility = create_facility(name="F-TERM")
        facility = validate_success(api.offboard_facility(facility["id"], ADMIN))
        assert facility["status"] == "OFFBOARDED"

        resp = api.suspend_facility(facility["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        facility = get_facility(facility["id"])
        assert facility["status"] == "OFFBOARDED", "OFFBOARDED must be unchanged"

    def test_offboard_blocked_then_succeeds(self, api):
        """PRD §3.1: "Offboarding is the terminal exit, reachable from `ACTIVE` or
        `SUSPENDED`, and it is guarded by an open-obligations sweep evaluated in a
        fixed order: first contracts — no ServiceContract of the facility may be in
        `DRAFT`, `ACTIVE`, or `SUSPENDED`; then rentals — no RentalReservation may
        be in `RESERVED` or `ON_RENT`; then guarantees — no GuaranteeCertificate
        may be in `AWAITING_MEASUREMENT` or `SETTLED_PAYOUT_DUE`. Any open
        obligation rejects the offboard with `ERR_FACILITY_HAS_OPEN_OBLIGATIONS`."
        PRD §3.7: "Termination, from `ACTIVE` or `SUSPENDED`, lands the contract in
        the terminal `TERMINATED` state and sets `termination_fee_cents`: zero when
        `termination_penalty_waived` is set, otherwise twice the
        `monthly_fee_cents`."

        Design: Corner/endpoints/corner_offboard_blocked_then_succeeds
        """
        facility = create_facility(name="F-OFF")
        contract = create_and_activate_contract(facility["id"], monthly_fee_cents=400000)

        resp = api.offboard_facility(facility["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FACILITY_HAS_OPEN_OBLIGATIONS, 409)

        contract = validate_success(api.terminate_service_contract(contract["id"], CONTRACT_MGR))
        assert_service_contract(contract)
        assert contract["status"] == "TERMINATED"
        assert contract["termination_fee_cents"] == 800000, (
            f"expected 2 x 400000 monthly fee, got {contract['termination_fee_cents']}"
        )

        facility = validate_success(api.offboard_facility(facility["id"], ADMIN))
        assert facility["status"] == "OFFBOARDED"


class TestRoleAccess:
    def test_rbac_engineer_cannot_manage_contracts(self, api):
        """PRD §2.1: "An attempt to perform an operation outside the caller's role
        is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403); the authoritative
        role assignment per operation is the endpoint table in §4."

        Design: Corner/rbac/corner_rbac_engineer_cannot_manage_contracts
        """
        facility = create_facility(name="F-RB1")
        resp = api.create_service_contract(
            {
                "facility_id": facility["id"],
                "tier": "STANDARD",
                "start_date": "2026-08-01",
                "term_months": 12,
                "monthly_fee_cents": 400000,
            },
            ENGINEER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

    def test_rbac_tech_cannot_set_clock(self, api):
        """PRD §2.1: "An attempt to perform an operation outside the caller's role
        is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403); the authoritative
        role assignment per operation is the endpoint table in §4."
        PRD §2.5: "A `DealerAdmin`-only test-driving capability advances the clock
        to a supplied `to_iso8601` instant and answers with the resulting
        `current_utc` value."

        Design: Corner/rbac/corner_rbac_tech_cannot_set_clock
        """
        resp = api.set_current_utc({"to_iso8601": "2026-08-02T00:00:00Z"}, TECH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

    def test_rbac_facility_manager_ownership_enforced(self, api):
        """PRD §2.1: "When `X-User-Role` is `FacilityManager`, `X-User-ID` is the
        `id` of the acting Facility; ownership checks on any resource that belongs
        to a Facility — directly, or through its parent chain such as a leak tag
        reached through its survey — compare the resource's owning facility to
        `X-User-ID`, and a mismatch is rejected with
        `ERR_FACILITY_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/corner_rbac_facility_manager_ownership_enforced
        """
        facility_a = create_facility(name="FA-OWN")
        _, tags = create_verified_survey(
            facility_a["id"],
            tags=[{"location_description": "a", "cfm_loss": 5.0, "repair_quote_cents": 100000}],
        )
        facility_b = create_facility(name="FB-OWN", activate=False)

        resp = api.authorize_repair(
            tags[0]["id"], make_facility_manager_headers(facility_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_OWNERSHIP_MISMATCH, 403)
        tag = validate_success(api.get_leak_tag(tags[0]["id"], ENGINEER))
        assert tag["status"] == "QUOTED", "rejected authorization must not move the tag"

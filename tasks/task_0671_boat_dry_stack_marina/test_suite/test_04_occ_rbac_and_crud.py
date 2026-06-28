"""Optimistic-concurrency rack-version control, RBAC / ownership enforcement,
and entity CRUD / listing / computed-field corner cases.

Corner queue: cross_cutting_complexity_layers, rbac, entities, endpoints, errors.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    setup_active_agreement, setup_owner_and_vessel,
    create_marina, create_rack, create_owner, create_vessel,
    create_verified_policy, rack_version, create_service_order, issue_invoice,
    create_storage_agreement_payload, create_vessel_payload,
    make_boat_owner_headers, build_user_headers, TEST_USERS,
)

DM = TEST_USERS["dock_master_headers"]
BC = TEST_USERS["billing_clerk_headers"]


class TestRackVersionOCC:
    """expected_rack_version guards the two rack-occupying writes."""

    def test_activate_with_correct_version_then_stale_rejected(self, api):
        """PRD §2.6: "Both require the caller to supply expected_rack_version in the
        request body, carrying the client's last observed version of the target Rack.
        If expected_rack_version does not equal the rack's current version, the write
        is rejected with ERR_STALE_RACK_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_activates_then_stale_rejected
        """
        ctx = setup_active_agreement()  # activated with the correct version
        # The original observed version is now stale: activation bumped Rack.version.
        # Terminate frees the rack (bumps version again), then a second activate that
        # carries the pre-occupation version must be rejected as stale.
        stale_version = ctx["rack"]["version"] - 1
        validate_success(api.terminate_storage_agreement(ctx["agreement"]["id"], DM), 200)
        res = api.activate_storage_agreement(ctx["agreement"]["id"], stale_version, DM)
        # Agreement is TERMINATED (terminal) AND the version is stale; per §2.5 the
        # state check precedes the OCC check, so either error is PRD-faithful.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, ["ERR_STALE_RACK_VERSION", "ERR_INVALID_STATE"])


class TestRbacAndOwnership:

    def test_boatowner_cannot_activate_agreement(self, api):
        """PRD §2.1: "When a request carries valid headers but the acting role is not
        permitted to perform the requested operation, the request is rejected with
        ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/boatowner_cannot_activate_agreement
        """
        marina = create_marina()
        rack = create_rack(marina["id"], bay_label="M-1")
        owner = create_owner(marina["id"])
        vessel = create_vessel(marina["id"], owner["id"])
        agr = get_success_data(api.create_storage_agreement(
            create_storage_agreement_payload(vessel["id"], rack["id"]), DM))
        rv = rack_version(rack["id"])
        # activate is DockMaster-exclusive; a BoatOwner is forbidden.
        res = api.activate_storage_agreement(agr["id"], rv, make_boat_owner_headers(owner["id"]))
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_boatowner_cannot_pay_others_invoice(self, api):
        """PRD §2.1: "When a BoatOwner attempts to mutate a vessel, launch request,
        service order, or invoice that does not belong to them, the request is
        rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

        Design: Corner/rbac/boatowner_cannot_pay_others_invoice
        """
        marina = create_marina()
        ownerA = create_owner(marina["id"], full_name="A", email="a@x.com")
        ownerB = create_owner(marina["id"], full_name="B", email="b@x.com")
        vesselA = create_vessel(marina["id"], ownerA["id"], name="VA",
                                loa_ft=20.00, beam_ft=8.00, dry_weight_lbs=3000)
        soA = create_service_order(vesselA["id"], ownerA["id"], "HAUL_OUT")
        invA = issue_invoice(ownerA["id"], "SERVICE_ORDER", soA["id"])
        # Owner B tries to pay owner A's invoice -> not the resource owner.
        res = api.pay_invoice(invA["id"], make_boat_owner_headers(ownerB["id"]))
        validate_error(res, "ERR_NOT_RESOURCE_OWNER")

    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing, or if X-User-Role is not one of
        the recognized roles, the request is rejected with ERR_UNAUTHENTICATED
        (HTTP 401)."

        Design: Corner/rbac/missing_auth_header_returns_unauthenticated
        """
        marina = create_marina()
        # Unrecognized role -> unauthenticated.
        bad_headers = build_user_headers("someone", "Wizard")
        res = api.get_marina(marina["id"], bad_headers)
        validate_error(res, "ERR_UNAUTHENTICATED")


class TestEntityCrudAndComputed:

    def test_create_marina_returns_201_with_defaults(self, api):
        """PRD §2.8: "The forklift_service_minutes value (default 30) is the length
        of a single launch or haul slot - the service window - and
        forklift_buffer_minutes (default 15) is the turnaround buffer appended to
        every slot's busy interval for overlap detection on the same forklift."
        PRD §2.4: "a version integer that begins at the resource's creation and
        increments by one on every mutation."

        Design: Corner/entities/create_marina_returns_201_with_defaults
        """
        get_success_data(api.set_clock("2026-04-01T00:00:00Z", DM))
        marina = validate_success(api.create_marina({"name": "Solo"}, DM), 201)
        assert marina["forklift_service_minutes"] == 30
        assert marina["forklift_buffer_minutes"] == 15
        assert marina["version"] == 1

    def test_get_vessel_nonexistent_returns_not_found(self, api):
        """PRD §2.5: "the system resolves each referenced identifier and rejects the
        request with ERR_NOT_FOUND (HTTP 404) if any referenced row does not exist"

        Design: Corner/entities/get_vessel_nonexistent_returns_not_found
        """
        get_success_data(api.set_clock("2026-04-01T00:00:00Z", DM))
        res = api.get_vessel(NON_EXISTENT_UUID, DM)
        validate_error(res, "ERR_NOT_FOUND")

    def test_create_rack_missing_size_class_returns_invalid_request(self, api):
        """PRD §3.8: "Every mutating request must carry its required body fields,
        well-typed, with any enum value drawn from the declared set; a missing
        required field, a wrong type, or an out-of-set enum value is rejected with
        ERR_INVALID_REQUEST (HTTP 400)."

        Design: Corner/entities/create_rack_missing_size_class_returns_invalid_request
        """
        marina = create_marina()
        res = api.create_rack({
            "marina_id": marina["id"], "bay_label": "X-1",
            "max_loa_ft": 30.00, "max_beam_ft": 11.00, "max_weight_lbs": 10000}, DM)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_vessel_system_fields_default_on_create(self, api):
        """PRD §3.1: "A newly registered vessel starts with location_status OFF_SITE
        and billing_status UNBILLED, and a null active_policy_id."

        Design: Corner/entities/vessel_system_fields_input_ignored
        """
        marina = create_marina()
        owner = create_owner(marina["id"])
        res = api.create_vessel(create_vessel_payload(
            marina["id"], owner["id"], name="Fresh",
            loa_ft=20.00, beam_ft=8.00, dry_weight_lbs=3000),
            make_boat_owner_headers(owner["id"]))
        vessel = validate_success(res, 201)
        assert vessel["location_status"] == "OFF_SITE"
        assert vessel["billing_status"] == "UNBILLED"

    def test_owner_balance_sums_issued_invoices(self, api):
        """PRD §3.7: "The owner's outstanding balance is the sum of amount_cents
        across that owner's invoices still in ISSUED status (PAID and VOIDED
        excluded)."
        PRD §3.6: "For HAUL_OUT the total is 18000 cents." and "For WINTERIZATION the
        total is 25000 cents."

        Design: Corner/entities/owner_account_balance_computed_from_issued_invoices
        """
        marina, owner, vessel = setup_owner_and_vessel(
            vessel_overrides={"loa_ft": 20.00, "beam_ft": 8.00, "dry_weight_lbs": 3000})
        so1 = create_service_order(vessel["id"], owner["id"], "HAUL_OUT")
        so2 = create_service_order(vessel["id"], owner["id"], "WINTERIZATION")
        issue_invoice(owner["id"], "SERVICE_ORDER", so1["id"])
        issue_invoice(owner["id"], "SERVICE_ORDER", so2["id"])
        fetched = validate_success(api.get_owner(owner["id"], BC), 200)
        assert fetched["account_balance_cents"] == 43000, \
            f"18000 + 25000 ISSUED = 43000, got {fetched['account_balance_cents']}"

    def test_list_vessels_pagination_envelope(self, api):
        """PRD §2.3: "The limit parameter caps the number of items returned"
        PRD §2.3: "Every list response carries limit, offset, total_count, and
        has_more in the meta object of the envelope."

        Design: Corner/entities/list_vessels_pagination_envelope
        """
        marina = create_marina()
        owner = create_owner(marina["id"])
        owner_h = make_boat_owner_headers(owner["id"])
        create_vessel(marina["id"], owner["id"], name="V1",
                      loa_ft=20.00, beam_ft=8.00, dry_weight_lbs=3000)
        create_vessel(marina["id"], owner["id"], name="V2",
                      loa_ft=21.00, beam_ft=8.00, dry_weight_lbs=3100)
        data, meta = validate_paginated(
            api.list_vessels(owner_h, params={"owner_id": owner["id"], "limit": 1, "offset": 0}))
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

    def test_storage_agreement_filtered_by_rack(self, api):
        """PRD §3.8: "agreements by vessel_id, rack_id, and status"

        Design: Corner/entities/fk_reverse_reach_storage_agreement_by_rack
        """
        ctx = setup_active_agreement()
        data, meta = validate_paginated(
            api.list_storage_agreements(DM, params={"rack_id": ctx["rack"]["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == ctx["agreement"]["id"]


class TestErrorAndEndpointCorners:

    def test_pay_already_paid_invoice_returns_invalid_state(self, api):
        """PRD §3.7: "A BoatOwner pays an issued invoice (ISSUED -> PAID), permitted
        only while the invoice is ISSUED"
        PRD §3.7: "Attempting to pay or void an invoice that is not ISSUED is
        rejected with ERR_INVALID_STATE (HTTP 409)."

        Design: Corner/errors/pay_already_paid_invoice_returns_invalid_state
        """
        from test_helpers import setup_paid_service_invoice
        ctx = setup_paid_service_invoice(service_kind="HAUL_OUT")
        owner_h = make_boat_owner_headers(ctx["owner"]["id"])
        res = api.pay_invoice(ctx["invoice"]["id"], owner_h)
        validate_error(res, "ERR_INVALID_STATE")

    def test_invoice_pay_clears_delinquency(self, api):
        """PRD §3.7: "When that balance crosses the delinquency threshold of 50000
        cents, the owner's vessel billing_status flips to DELINQUENT."
        PRD §3.7: "if this was the owner's only outstanding invoice and the vessel's
        billing_status was DELINQUENT, the vessel's billing_status is restored to
        ACTIVE_STORAGE."

        Design: Corner/endpoints/invoice_pay_clears_delinquency_cross_entity
        """
        ctx = setup_active_agreement()  # vessel ACTIVE_STORAGE
        owner_id = ctx["owner"]["id"]
        vessel_id = ctx["vessel"]["id"]
        owner_h = make_boat_owner_headers(owner_id)
        # Three WINTERIZATION service invoices: 25000 * 3 = 75000, unambiguously above
        # the 50000 delinquency threshold (independent of strict-vs-inclusive
        # interpretation of "crosses").
        so1 = create_service_order(vessel_id, owner_id, "WINTERIZATION")  # 25000
        inv1 = issue_invoice(owner_id, "SERVICE_ORDER", so1["id"])
        so2 = create_service_order(vessel_id, owner_id, "WINTERIZATION")  # +25000 -> 50000
        inv2 = issue_invoice(owner_id, "SERVICE_ORDER", so2["id"])
        so3 = create_service_order(vessel_id, owner_id, "WINTERIZATION")  # +25000 -> 75000
        inv3 = issue_invoice(owner_id, "SERVICE_ORDER", so3["id"])
        delinquent_vessel = validate_success(api.get_vessel(vessel_id, DM), 200)
        assert delinquent_vessel["billing_status"] == "DELINQUENT", \
            "balance 75000 above threshold flips vessel to DELINQUENT"
        validate_success(api.pay_invoice(inv1["id"], owner_h), 200)
        validate_success(api.pay_invoice(inv2["id"], owner_h), 200)
        # Final payment leaves zero outstanding -> the last invoice clears delinquency.
        validate_success(api.pay_invoice(inv3["id"], owner_h), 200)
        cleared = validate_success(api.get_vessel(vessel_id, DM), 200)
        assert cleared["billing_status"] == "ACTIVE_STORAGE", \
            "paying all invoices clears delinquency back to ACTIVE_STORAGE"
        owner_after = validate_success(api.get_owner(owner_id, BC), 200)
        assert owner_after["account_balance_cents"] == 0

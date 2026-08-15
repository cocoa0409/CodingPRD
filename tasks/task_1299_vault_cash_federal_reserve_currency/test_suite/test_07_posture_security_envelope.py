"""Vault posture boundary, RBAC / scope / auth validations, OCC site patch,
and response envelope guarantees."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_vault_site,
    build_user_headers,
    create_atm_machine_payload,
    create_cash_ledger_entry_payload,
    create_carrier_payload,
    create_fed_order_payload,
    create_seasonal_window,
    create_staff,
    create_staffed_site,
    create_vault_site_payload,
    get_success_data,
    get_site,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_atm_analyst_headers,
    make_custodian_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPostureBoundary:
    def _site_at(self, api, opening_fit, custodian=None):
        ctx = create_staffed_site(
            staff_roles=("custodian",),
            site_overrides={
                "vault_limit_cents": 10000000,
                "insurance_coverage_cents": 100000000,
                "opening_fit_cents": opening_fit,
            },
        )
        return ctx

    def test_exactly_ninety_percent_trips_elevated(self, api):
        """PRD §2.9: "Otherwise the posture is `ELEVATED` when
        `on_hand_total_cents` multiplied by 10 is greater than or equal to
        `vault_limit_cents` multiplied by 9 — meaning exactly 90.000% utilization
        trips `ELEVATED` — or when the site holds any `SEIZED` counterfeit case
        whose `seized_at` is more than 5 days before the current clock, or when
        the site has any reconciliation in `ESCALATED` status."
        PRD §2.9: "Every vault site carries a derived `posture` that summarizes
        its risk position and gates certain operations. The derivation uses
        integer cross-multiplication only — no percentage rounding anywhere"

        Design: Difficulty/boundary_precision_check/vault_posture_exactly_ninety_percent
        """
        ctx = self._site_at(api, 9000000)
        assert ctx["site"]["posture"] == "ELEVATED", (
            f"9,000,000 * 10 >= 10,000,000 * 9 must trip ELEVATED, "
            f"got {ctx['site']['posture']}"
        )

    def test_one_cent_below_ninety_percent_stays_normal(self, api):
        """PRD §2.9: "Otherwise the posture is `ELEVATED` when
        `on_hand_total_cents` multiplied by 10 is greater than or equal to
        `vault_limit_cents` multiplied by 9 — meaning exactly 90.000% utilization
        trips `ELEVATED` — or when the site holds any `SEIZED` counterfeit case
        whose `seized_at` is more than 5 days before the current clock, or when
        the site has any reconciliation in `ESCALATED` status."
        PRD §2.10: "Every physical or administrative cash movement posts a
        `CashLedgerEntry` against a site with a signed amount in cents, a `bucket`
        of `FIT` or `UNFIT`, and a value date. The ledger is append-only; there is
        no edit or delete."

        Design: Difficulty/boundary_precision_check/vault_posture_exactly_ninety_percent
        """
        ctx = self._site_at(api, 8999999)
        assert ctx["site"]["posture"] == "NORMAL", (
            f"89,999,990 < 90,000,000 cross-product must stay NORMAL, "
            f"got {ctx['site']['posture']}"
        )
        custodian = ctx["staff"]["custodian"]["headers"]
        site_id = ctx["site"]["id"]
        get_success_data(
            api.create_cash_ledger_entry(
                create_cash_ledger_entry_payload(
                    site_id=site_id,
                    business_date="2026-08-01",
                    signed_amount_cents=1,
                    bucket="FIT",
                ),
                custodian,
            )
        )
        site = get_site(site_id)
        assert site["on_hand_fit_cents"] == 9000000
        assert site["posture"] == "ELEVATED", (
            "90,000,000 >= 90,000,000 — the inclusive boundary trips ELEVATED"
        )


class TestInsuranceHeadroomEvaluationOrder:
    def _setup(self, api):
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={
                "site_type": "CENTRAL",
                "vault_limit_cents": 100000000,
                "insurance_coverage_cents": 50000000,
                "opening_fit_cents": 30000000,
            },
        )
        return ctx, ctx["staff"]["coordinator"]["headers"]

    def _order_with_line(self, api, coord, site_id, denomination_cents, strap_count):
        from test_helpers import create_draft_order_with_line

        return create_draft_order_with_line(
            site_id,
            coord,
            direction="ORDER",
            business_date="2026-08-04",
            denomination_cents=denomination_cents,
            strap_count=strap_count,
        )

    def test_exact_headroom_fit_admitted_then_overflow_rejected(self, api):
        """PRD §3.3: "The evaluation order is pinned to avoid circularity:
        committed exposure is `on_hand_total_cents` plus
        `in_transit_inbound_cents` plus `pending_inbound_order_cents`, deliberately
        excluding the candidate order or shipment under evaluation because it is
        not yet committed; headroom is `insurance_coverage_cents` minus that
        committed exposure; and the candidate is admitted when its value is less
        than or equal to headroom — an exact fit is allowed."
        PRD §3.3: "A candidate exceeding headroom is rejected with
        `ERR_INSURANCE_HEADROOM_EXCEEDED` (HTTP 402)."

        Design: Difficulty/combinatorial_formula/insurance_headroom_evaluation_order
        """
        ctx, coord = self._setup(api)
        site_id = ctx["site"]["id"]
        assert ctx["site"]["insurance_headroom_cents"] == 20000000, (
            f"coverage 50,000,000 - on-hand 30,000,000 must open at 20,000,000, "
            f"got {ctx['site']['insurance_headroom_cents']}"
        )

        o1 = self._order_with_line(api, coord, site_id, 10000, 15)  # face 15,000,000
        get_success_data(api.submit_fed_order(o1["id"], coord))

        # Remaining headroom is exactly 5,000,000; the candidate is excluded from
        # its own committed exposure, so an exact fit is admitted.
        o2 = self._order_with_line(api, coord, site_id, 10000, 5)  # face 5,000,000
        submitted = get_success_data(api.submit_fed_order(o2["id"], coord))
        assert submitted["status"] == "SUBMITTED"

        o3 = self._order_with_line(api, coord, site_id, 100, 20)  # face 200,000
        resp = api.submit_fed_order(o3["id"], coord)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_HEADROOM_EXCEEDED)
        o3_after = get_success_data(api.get_fed_order(o3["id"], coord))
        assert o3_after["status"] == "DRAFT", (
            "a rejected submit must leave the order state unchanged"
        )

    def test_candidate_above_remaining_headroom_rejected(self, api):
        """PRD §3.3: "The evaluation order is pinned to avoid circularity:
        committed exposure is `on_hand_total_cents` plus
        `in_transit_inbound_cents` plus `pending_inbound_order_cents`, deliberately
        excluding the candidate order or shipment under evaluation because it is
        not yet committed; headroom is `insurance_coverage_cents` minus that
        committed exposure; and the candidate is admitted when its value is less
        than or equal to headroom — an exact fit is allowed."
        PRD §3.3: "A candidate exceeding headroom is rejected with
        `ERR_INSURANCE_HEADROOM_EXCEEDED` (HTTP 402)."

        Design: Difficulty/combinatorial_formula/insurance_headroom_evaluation_order
        """
        ctx, coord = self._setup(api)
        site_id = ctx["site"]["id"]

        o1 = self._order_with_line(api, coord, site_id, 10000, 15)  # face 15,000,000
        get_success_data(api.submit_fed_order(o1["id"], coord))

        # 5,000,001 exceeds the 5,000,000 remaining headroom by one cent.
        o2 = get_success_data(
            api.create_fed_order(
                create_fed_order_payload(
                    site_id=site_id, direction="ORDER", business_date="2026-08-04"
                ),
                coord,
            )
        )
        # Build face 5,000,001 out of valid lines: 100-denom lines x50 straps are
        # ORDER-valid (multiple of 10): 100*100*50 = 500,000 each; 10 lines give
        # 5,000,000, plus one 1-cent… not possible — the smallest line is 100,000
        # for denom 100 x10 straps (ORDER-valid). Use face 5,100,000 instead:
        # 10000-denom x5 straps = 5,000,000 plus 100-denom x10 straps = 100,000.
        version = o2["version"]
        get_success_data(
            api.add_denomination_line(
                o2["id"],
                {
                    "denomination_cents": 10000,
                    "strap_count": 5,
                    "expected_fed_order_version": version,
                },
                coord,
            )
        )
        get_success_data(
            api.add_denomination_line(
                o2["id"],
                {
                    "denomination_cents": 100,
                    "strap_count": 10,
                    "expected_fed_order_version": version + 1,
                },
                coord,
            )
        )
        o2_current = get_success_data(api.get_fed_order(o2["id"], coord))
        assert o2_current["face_total_cents"] == 5100000

        resp = api.submit_fed_order(o2["id"], coord)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_HEADROOM_EXCEEDED)
        assert get_success_data(api.get_fed_order(o2["id"], coord))["status"] == "DRAFT"


class TestAuthValidation:
    def test_missing_auth_headers_beats_not_found(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`
        identifying the acting principal, and `X-User-Role` naming the role under
        which the principal acts. A request missing either header, naming an
        undeclared role, or presenting an entity-backed `X-User-ID` that does not
        resolve to an existing, active identity record is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.8: "When a request fails several rules at once, the server reports
        the first failure in a fixed evaluation order: authentication context
        first (missing or invalid headers, then role permission, then site-scope
        or carrier ownership), then existence of path identifiers validated
        left-to-right along the URL, then existence of body-referenced foreign
        keys (`site_id`, `atm_id`, `carrier_id`, `fed_order_id`,
        `fitness_batch_id`), then request shape and uniqueness
        (`ERR_INVALID_REQUEST` for missing or mistyped fields, invalid enum
        members, or an end date before its start date), then the target
        resource's own state machine, then cross-entity state guards, then
        segregation-of-duties checks, then business rules (insurance headroom,
        cutoff and scheduling windows, denomination mix, fiscal sufficiency)."

        Design: Corner/validations/get_site_missing_auth_header_beats_not_found
        """
        resp = api.get_vault_site(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers={}
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400, (
            f"authentication must precede existence (no 404 leak), got {resp.status_code}"
        )


class TestRbacEnforcement:
    def test_atm_analyst_cannot_create_vault_site(self, api):
        """PRD §2.1: "If authentication succeeds but the role is not listed among
        the endpoint's permitted roles, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "| POST | /vault-cash/vault-sites | Create a vault site with opening
        balances | CashOperationsAdmin |"

        Design: Corner/validations/atm_analyst_cannot_create_vault_site
        """
        admin = TEST_USERS["admin_headers"]
        ctx = create_staffed_site(staff_roles=("analyst",))
        analyst = ctx["staff"]["analyst"]["headers"]

        resp = api.create_vault_site(
            {
                "name": "Rogue",
                "site_type": "BRANCH",
                "vault_limit_cents": 1,
                "insurance_coverage_cents": 1,
                "dock_capacity": 1,
            },
            analyst,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        sites, meta = validate_paginated(api.list_vault_sites(admin))
        assert meta["total_count"] == 1, (
            f"the rejected create must persist nothing, got {meta['total_count']}"
        )

    def test_custodian_cannot_count_other_sites_reconciliation(self, api):
        """PRD §2.1: "Site-scoped staff roles — `VaultCustodian`, `FedCoordinator`,
        `AtmAnalyst`, and `ComplianceOfficer` — may act only on resources belonging
        to their home site; acting on a resource of another site is rejected with
        `ERR_SITE_SCOPE_VIOLATION` (HTTP 403). The `CashOperationsAdmin` role is
        global and has no site scope."

        Design: Corner/validations/custodian_cross_site_scope_rejected
        """
        from test_helpers import create_site, create_reconciliation_payload

        site_a = create_site(
            name="A", site_type="CENTRAL", opening_fit_cents=5000000
        )
        site_b = create_site(
            name="B", site_type="BRANCH", opening_fit_cents=3000000
        )
        staff_a = create_staff(site_a["id"], full_name="Cust A")
        staff_b = create_staff(site_b["id"], full_name="Cust B")
        cust_a = make_custodian_headers(staff_a["id"])
        cust_b = make_custodian_headers(staff_b["id"])

        recon_b = get_success_data(
            api.create_reconciliation(
                create_reconciliation_payload(
                    site_id=site_b["id"],
                    business_date="2026-08-01",
                    opening_balance_cents=3000000,
                ),
                cust_b,
            )
        )
        resp = api.count_reconciliation(
            recon_b["id"], {"counted_on_hand_cents": 3000000}, cust_a
        )
        validate_error(resp, ApiErrorId.ERR_SITE_SCOPE_VIOLATION)
        after = get_success_data(api.get_reconciliation(recon_b["id"], cust_b))
        assert after["status"] == "OPEN", (
            f"no count must be recorded by the cross-site attempt, got {after['status']}"
        )


class TestSeasonalWindowOverlap:
    def test_inclusive_end_overlap_rejected_adjacency_allowed(self, api):
        """PRD §3.1: "Windows of one site must be disjoint as closed intervals;
        adjacency — one window's start falling exactly one day after another's
        end — is allowed, but any true overlap is rejected with
        `ERR_SEASONAL_WINDOW_OVERLAP` (HTTP 409)."

        Design: Corner/validations/seasonal_window_overlap_rejected_adjacency_allowed
        """
        ctx = create_staffed_site()
        site_id = ctx["site"]["id"]
        create_seasonal_window(
            site_id,
            name="W1",
            start_date="2026-12-20",
            end_date="2026-12-26",
            multiplier_bps=12500,
        )
        # [12-26, 12-31] shares the inclusive end date 12-26 → overlap.
        resp = api.create_seasonal_window(
            {
                "site_id": site_id,
                "name": "W2",
                "start_date": "2026-12-26",
                "end_date": "2026-12-31",
                "multiplier_bps": 13000,
            },
            TEST_USERS["admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SEASONAL_WINDOW_OVERLAP)

        # 12-27 is exactly one day after W1's end — adjacency is allowed.
        w3 = get_success_data(
            api.create_seasonal_window(
                {
                    "site_id": site_id,
                    "name": "W3",
                    "start_date": "2026-12-27",
                    "end_date": "2027-01-02",
                    "multiplier_bps": 13000,
                },
                TEST_USERS["admin_headers"],
            )
        )
        assert w3["id"], "adjacent window must be created"


class TestOccSitePatch:
    def test_stale_patch_rejected_after_version_advance(self, api):
        """PRD §2.7: "Updating a vault site's limits or capacity requires
        `expected_vault_site_version` matching the site's current `version`. Any
        mutation — a previous patch, a ledger-driven recompute, a posture flip —
        advances the version, so a patch carrying an older value is rejected with
        `ERR_STALE_VAULT_SITE_VERSION` (HTTP 412)."
        PRD §3.1: "Later, the administrator may patch the site's
        `vault_limit_cents`, `insurance_coverage_cents`, `dock_capacity`, or
        `name`; each successful patch increments the site version by 1 and
        re-derives posture and `insurance_headroom_cents`, and the patch must
        carry `expected_vault_site_version` per §2.7."

        Design: Corner/cross_cutting_layers/occ_site_patch_stale_rejected
        """
        admin = TEST_USERS["admin_headers"]
        ctx = create_staffed_site(
            site_overrides={
                "vault_limit_cents": 50000000,
                "insurance_coverage_cents": 80000000,
            }
        )
        site = ctx["site"]
        stale_version = site["version"]
        patched = get_success_data(
            api.patch_vault_site(
                site["id"],
                {
                    "expected_vault_site_version": stale_version,
                    "vault_limit_cents": 60000000,
                },
                admin,
            )
        )
        assert patched["version"] == stale_version + 1
        assert patched["vault_limit_cents"] == 60000000

        resp = api.patch_vault_site(
            site["id"],
            {"expected_vault_site_version": stale_version, "name": "S-renamed"},
            admin,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VAULT_SITE_VERSION)
        after = get_site(site["id"])
        assert after["name"] == site["name"], (
            f"the stale patch must not apply, got name {after['name']!r}"
        )


class TestEnvelope:
    def test_success_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects. For 2xx responses with no data, it contains an empty
        object. Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/endpoints/success_envelope_shape
        """
        admin = TEST_USERS["admin_headers"]
        site = get_success_data(
            api.create_vault_site(
                create_vault_site_payload(
                    name="S",
                    site_type="BRANCH",
                    vault_limit_cents=50000000,
                    insurance_coverage_cents=80000000,
                ),
                admin,
            )
        )
        resp = api.get_vault_site(site["id"], admin)
        data = validate_success(resp, 200)
        body = resp.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert data["id"] == site["id"]

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.8: "Path-parameter identifiers that do not resolve produce the
        resource-specific not-found error — for example `ERR_VAULT_SITE_NOT_FOUND`,
        `ERR_FED_ORDER_NOT_FOUND`, or `ERR_SHIPMENT_NOT_FOUND` — each at HTTP 404."

        Design: Corner/endpoints/error_envelope_shape
        """
        admin = TEST_USERS["admin_headers"]
        resp = api.get_fed_order("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", admin)
        error_data = validate_error(resp, ApiErrorId.ERR_FED_ORDER_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert error_data["error_id"] == "ERR_FED_ORDER_NOT_FOUND"
        assert isinstance(error_data["message"], str) and error_data["message"].strip()


class TestPagination:
    def test_limit_offset_total_count_and_has_more(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit` and
        `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a
        maximum of 100; a `limit` outside that range is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400). The `offset` parameter defaults to 0.
        Results are always sorted by `created_at` ascending. The `meta` object of
        a list response includes the fields `limit`, `offset`, `total_count`, and
        `has_more`, where `has_more` indicates whether additional results exist
        beyond the current page."

        Design: Corner/entities/pagination_list_total_count_and_has_more
        """
        admin = TEST_USERS["admin_headers"]
        for name in ("C1", "C2", "C3"):
            get_success_data(
                api.create_carrier(
                    create_carrier_payload(name=name, liability_cap_per_truck_cents=1000000),
                    admin,
                )
            )
        page, meta = validate_paginated(
            api.list_carriers(admin, params={"limit": 2, "offset": 2})
        )
        assert len(page) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        all_rows, default_meta = validate_paginated(api.list_carriers(admin))
        assert len(all_rows) == 3
        assert default_meta["limit"] == 10, (
            f"default limit must be 10, got {default_meta['limit']}"
        )

    def test_limit_101_rejected(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit` and
        `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a
        maximum of 100; a `limit` outside that range is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/endpoints/pagination_limit_101_rejected
        """
        admin = TEST_USERS["admin_headers"]
        resp = api.list_vault_sites(admin, params={"limit": 101})
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAtmParallelStateDimensions:
    def _critical_atm_context(self, api):
        ctx = create_staffed_site(
            staff_roles=("analyst",), site_overrides={"opening_fit_cents": 50000000}
        )
        from test_helpers import create_atm

        atm = create_atm(
            ctx["site"]["id"],
            terminal_code="ATM-Z",
            cash_capacity_cents=10000000,
            opening_balance_cents=400000,
        )
        return ctx, atm

    def test_service_toggle_leaves_critical_cash_posture_unchanged(self, api):
        """PRD §3.7: "The machine carries two independent state axes:
        `service_status` toggles between `ACTIVE` and `OUT_OF_SERVICE` at the
        request of an `AtmAnalyst` (toggling from the wrong state fails with
        `ERR_ATM_INVALID_STATE`, and each toggle increments the machine's
        version), while `cash_posture` is a pure derivation — `CRITICAL` when the
        current balance multiplied by 20 is below capacity, otherwise `LOW` when
        the balance multiplied by 5 is below capacity, otherwise `NORMAL` —
        recomputed on every balance mutation and never gated by the service axis."

        Design: Difficulty/non_linear_state_machine/atm_parallel_state_dimensions
        """
        ctx, atm = self._critical_atm_context(api)
        analyst = ctx["staff"]["analyst"]["headers"]
        assert atm["cash_posture"] == "CRITICAL", (
            f"400,000 * 20 < 10,000,000 must be CRITICAL, got {atm['cash_posture']}"
        )
        assert atm["service_status"] == "ACTIVE"

        oos = get_success_data(
            api.set_atm_service_status(
                atm["id"], {"service_status": "OUT_OF_SERVICE"}, analyst
            )
        )
        assert oos["service_status"] == "OUT_OF_SERVICE"
        assert oos["cash_posture"] == "CRITICAL", (
            "the service toggle must not rewrite the cash posture axis"
        )

        back = get_success_data(
            api.set_atm_service_status(atm["id"], {"service_status": "ACTIVE"}, analyst)
        )
        assert back["service_status"] == "ACTIVE"
        assert back["cash_posture"] == "CRITICAL", (
            "the axes are independent — CRITICAL persists across both toggles"
        )

    def test_service_toggle_from_wrong_state_rejected(self, api):
        """PRD §3.7: "The machine carries two independent state axes:
        `service_status` toggles between `ACTIVE` and `OUT_OF_SERVICE` at the
        request of an `AtmAnalyst` (toggling from the wrong state fails with
        `ERR_ATM_INVALID_STATE`, and each toggle increments the machine's
        version), while `cash_posture` is a pure derivation — `CRITICAL` when the
        current balance multiplied by 20 is below capacity, otherwise `LOW` when
        the balance multiplied by 5 is below capacity, otherwise `NORMAL` —
        recomputed on every balance mutation and never gated by the service axis."

        Design: Difficulty/non_linear_state_machine/atm_parallel_state_dimensions
        """
        ctx, atm = self._critical_atm_context(api)
        analyst = ctx["staff"]["analyst"]["headers"]

        # Toggling to the CURRENT state is a wrong-state toggle.
        resp = api.set_atm_service_status(atm["id"], {"service_status": "ACTIVE"}, analyst)
        validate_error(resp, ApiErrorId.ERR_ATM_INVALID_STATE)

        get_success_data(
            api.set_atm_service_status(
                atm["id"], {"service_status": "OUT_OF_SERVICE"}, analyst
            )
        )
        resp2 = api.set_atm_service_status(
            atm["id"], {"service_status": "OUT_OF_SERVICE"}, analyst
        )
        validate_error(resp2, ApiErrorId.ERR_ATM_INVALID_STATE)
        after = get_success_data(api.get_atm_machine(atm["id"], analyst))
        assert after["service_status"] == "OUT_OF_SERVICE"
        assert after["cash_posture"] == "CRITICAL"


class TestVaultSiteCreationDefaults:
    def test_omitted_openings_default_and_posture_derived(self, api):
        """PRD §3.1: "Optional `opening_fit_cents` and `opening_unfit_cents` seed
        the vault; nonzero openings post `OPENING_BALANCE` ledger entries
        value-dated to the current logical clock date, and the site's posture is
        derived immediately. The site is created with `version` equal to 1."
        PRD §2.9: "Otherwise the posture is `NORMAL`."
        PRD §3.3: "The evaluation order is pinned to avoid circularity: committed
        exposure is `on_hand_total_cents` plus `in_transit_inbound_cents` plus
        `pending_inbound_order_cents`, deliberately excluding the candidate order
        or shipment under evaluation because it is not yet committed; headroom is
        `insurance_coverage_cents` minus that committed exposure; and the
        candidate is admitted when its value is less than or equal to headroom —
        an exact fit is allowed."

        Design: Corner/entities/create_vault_site_applies_defaults
        """
        admin = TEST_USERS["admin_headers"]
        resp = api.create_vault_site(
            {
                "name": "Main Vault",
                "site_type": "CENTRAL",
                "vault_limit_cents": 50000000,
                "insurance_coverage_cents": 80000000,
                "dock_capacity": 3,
            },
            admin,
        )
        data = validate_success(resp, 201)
        assert_vault_site(data)
        assert data["opening_fit_cents"] == 0
        assert data["opening_unfit_cents"] == 0
        assert data["on_hand_fit_cents"] == 0
        assert data["on_hand_total_cents"] == 0
        assert data["reserved_out_cents"] == 0
        assert data["insurance_headroom_cents"] == 80000000
        assert data["posture"] == "NORMAL"
        assert data["version"] == 1

    def test_client_supplied_system_fields_ignored(self, api):
        """PRD §2.5: "Every resource carries an `id` that is a server-minted UUID
        with no type prefix. Resources created with full audit fields —
        `VaultSite`, `StaffMember`, `Carrier`, `AtmMachine`, `SeasonalWindow`,
        `FedOrder`, `CashShipment`, `FitnessBatch`, `CounterfeitCase`,
        `Reconciliation`, and `AtmForecast` — additionally carry `created_at`
        (ISO 8601 UTC with three fractional digits), `updated_at` (same format,
        refreshed on every mutation), and `version`, an integer starting at 1
        that increments by 1 on every mutation of the resource, including
        system-driven mutations."
        PRD §3.1: "The site is created with `version` equal to 1."

        Design: Corner/entities/create_site_system_fields_input_ignored
        """
        admin = TEST_USERS["admin_headers"]
        supplied_id = "00000000-0000-0000-0000-000000000000"
        resp = api.create_vault_site(
            {
                "id": supplied_id,
                "version": 99,
                "name": "S",
                "site_type": "BRANCH",
                "vault_limit_cents": 50000000,
                "insurance_coverage_cents": 80000000,
                "dock_capacity": 2,
            },
            admin,
        )
        data = validate_success(resp, 201)
        assert data["id"] != supplied_id, (
            "the server must mint its own id, not echo the client-supplied one"
        )
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1, (
            f"server-minted version starts at 1, got {data['version']}"
        )


class TestAtmUnknownSite:
    def test_create_atm_with_unknown_site_rejected(self, api):
        """PRD §2.8: "When a request fails several rules at once, the server
        reports the first failure in a fixed evaluation order: authentication
        context first (missing or invalid headers, then role permission, then
        site-scope or carrier ownership), then existence of path identifiers
        validated left-to-right along the URL, then existence of body-referenced
        foreign keys (`site_id`, `atm_id`, `carrier_id`, `fed_order_id`,
        `fitness_batch_id`), then request shape and uniqueness
        (`ERR_INVALID_REQUEST` for missing or mistyped fields, invalid enum
        members, or an end date before its start date), then the target
        resource's own state machine, then cross-entity state guards, then
        segregation-of-duties checks, then business rules (insurance headroom,
        cutoff and scheduling windows, denomination mix, fiscal sufficiency).
        Path-parameter identifiers that do not resolve produce the
        resource-specific not-found error — for example `ERR_VAULT_SITE_NOT_FOUND`,
        `ERR_FED_ORDER_NOT_FOUND`, or `ERR_SHIPMENT_NOT_FOUND` — each at HTTP 404."
        PRD §3.7: "Machines are registered by an administrator with the servicing
        vault's `site_id`, a unique `terminal_code`, the physical cassette
        `cash_capacity_cents`, and an optional `opening_balance_cents` defaulting
        to zero; the machine's `current_balance_cents` starts at the opening
        balance, its `service_status` starts `ACTIVE`, and its cash posture
        derives immediately."

        Design: Corner/entities/atm_create_with_unknown_site_rejected
        """
        admin = TEST_USERS["admin_headers"]
        resp = api.create_atm_machine(
            create_atm_machine_payload(
                site_id="8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                terminal_code="ATM-9",
                cash_capacity_cents=10000000,
            ),
            admin,
        )
        validate_error(resp, ApiErrorId.ERR_VAULT_SITE_NOT_FOUND)

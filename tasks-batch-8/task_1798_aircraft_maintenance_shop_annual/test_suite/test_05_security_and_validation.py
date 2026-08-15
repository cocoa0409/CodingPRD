"""Corner coverage: validation pipeline (auth/RBAC/window/invoice-lock/
checklist/certificate), endpoint listing/reachability, OCC errors, and RBAC
role denials."""
from test_helpers import (
    SM,
    add_checklist_item,
    create_aircraft,
    create_hangar_slot_payload,
    create_logbook_entry_payload,
    create_mechanic,
    create_owner,
    create_slot,
    create_work_order,
    get_success_data,
    make_mechanic_headers,
    make_owner_headers,
    reset_clock,
    setup_shop,
    setup_wo_returned_to_service,
    start_work_order,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)


class TestAuthAndRbac:
    def test_missing_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/auth_missing_headers_returns_401
        """
        res = api.list_aircraft(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
        assert res.status_code == 401

    def test_wrong_role_returns_403(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/validations/rbac_denied_wrong_role_returns_403
        """
        owner = create_owner()
        res = api.create_owner(
            {"full_name": "Bad", "email": "bad@x.com", "phone": "555",
             "approval_cap_cents": 1},
            make_owner_headers(owner["id"]),
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
        assert res.status_code == 403


class TestSlotWindowValidity:
    def test_ends_at_not_after_starts_at_rejected(self, api):
        """PRD §3.2: "First, `ends_at` must be strictly later than `starts_at`,
        and the total duration may not exceed thirty days; a violation is
        rejected with `ERR_INVALID_WINDOW` (HTTP 422)."

        Design: Corner/validations/slot_window_invalid_returns_422
        """
        owner = create_owner()
        aircraft = create_aircraft(owner["id"])
        res = api.create_hangar_slot(
            create_hangar_slot_payload(
                aircraft["id"], hangar_code="H-WIN",
                starts_at="2026-08-10T17:00:00Z", ends_at="2026-08-10T08:00:00Z",
            ),
            SM,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_WINDOW)
        assert res.status_code == 422


class TestInvoiceLock:
    def test_labor_entry_blocked_after_invoice_issued(self, api):
        """PRD §3.8: "Issuance is the point of fiscal no-return: once an
        invoice stands `ISSUED` or `PAID`, the underlying work order is locked
        — no further labor entries may be posted, no parts may be installed,
        and no discrepancies may be rectified — and any such attempt is
        rejected with `ERR_INVOICE_LOCKED` (HTTP 409)."

        Design: Corner/validations/invoice_lock_blocks_labor_entry_after_issue
        """
        owner, aircraft, mechanic, verifier, slot, wo, invoice = setup_wo_returned_to_service()
        get_success_data(api.issue_invoice(invoice["id"], SM))
        res = api.create_labor_entry(
            wo["id"],
            {"mechanic_id": mechanic["id"], "duration_tenths": 3, "notes": "late"},
            make_mechanic_headers(mechanic["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVOICE_LOCKED)
        assert res.status_code == 409


class TestChecklistIncomplete:
    def test_pending_item_blocks_complete_inspection(self, api):
        """PRD §3.3: "The gate is strict: every checklist item must have a
        recorded `result` of `PASS`, `FAIL`, or `NA` with zero items left
        `PENDING`, and an `ANNUAL`-scope order must have at least one item
        whose result is not `NA` — an annual that inspected nothing is
        rejected. Either violation surfaces as `ERR_CHECKLIST_INCOMPLETE`
        (HTTP 422)."

        Design: Corner/validations/checklist_incomplete_blocks_complete_inspection
        """
        owner, aircraft, mechanic, slot, wo = setup_shop()
        wo = start_work_order(wo, mechanic)
        add_checklist_item(wo["id"], mechanic)  # left PENDING
        res = api.complete_inspection(wo["id"], make_mechanic_headers(mechanic["id"]))
        validate_error(res, ApiErrorId.ERR_CHECKLIST_INCOMPLETE)
        assert res.status_code == 422


class TestAnnualSignoffCertificate:
    def _setup_ready_for_rts_annual(self, api):
        """ANNUAL WO in READY_FOR_RTS with RTS_STATEMENT logged by an IA."""
        from test_helpers import setup_wo_ready_for_rts
        owner, aircraft, mechanic, verifier, slot, wo = setup_wo_ready_for_rts()
        get_success_data(
            api.create_logbook_entry(
                create_logbook_entry_payload(aircraft["id"], wo["id"], mechanic["id"]),
                make_mechanic_headers(mechanic["id"]),
            )
        )
        return owner, aircraft, mechanic, wo

    def test_ap_only_mechanic_cannot_return_annual_to_service(self, api):
        """PRD §3.7: "The returning mechanic must hold an `IA` certificate when
        the scope is `ANNUAL` — an `AP` certificate suffices otherwise, and a
        certificate shortfall is rejected with `ERR_CERTIFICATE_INSUFFICIENT`
        (HTTP 422)."

        Design: Corner/validations/annual_signoff_requires_ia_certificate
        """
        owner, aircraft, mechanic, wo = self._setup_ready_for_rts_annual(api)
        ap_only = create_mechanic(certificate_class="AP")
        res = api.return_to_service(wo["id"], make_mechanic_headers(ap_only["id"]))
        validate_error(res, ApiErrorId.ERR_CERTIFICATE_INSUFFICIENT)
        assert res.status_code == 422


class TestEndpointsListing:
    def test_list_owners_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/list_owners_pagination_envelope
        """
        for i in range(3):
            create_owner(full_name=f"Owner {i}", email=f"lo{i}@x.com", phone=str(i))
        data, meta = validate_paginated(api.list_owners(SM))
        assert len(data) == 3, f"expected 3 owners, got {len(data)}"
        assert "total_count" in meta and "has_more" in meta
        assert "limit" in meta and "offset" in meta
        assert meta["total_count"] == 3

    def test_owner_aircraft_reverse_reachability(self, api):
        """PRD §3.1: "An owner can review the fleet tied to their account
        through the owner's aircraft listing, which reaches aircraft in reverse
        through the registered `owner_id`."

        Design: Corner/endpoints/reverse_reachability_aircraft_by_owner
        """
        owner_a = create_owner(full_name="A", email="ra@x.com", phone="1")
        owner_b = create_owner(full_name="B", email="rb@x.com", phone="2")
        create_aircraft(owner_a["id"], tail_number="N-RA")
        create_aircraft(owner_b["id"], tail_number="N-RB")
        fleet = get_success_data(api.list_owner_aircraft(owner_a["id"], SM))
        tails = [a["tail_number"] for a in fleet]
        assert tails == ["N-RA"], f"owner A's fleet must contain only N-RA, got {tails}"


class TestOptimisticConcurrencyErrors:
    def test_stale_hangar_slot_version_rejected(self, api):
        """PRD §3.2: "Because intake is the moment two dispatchers most often
        collide over the same slot, this creation is one of the two
        optimistic-concurrency writes in §2.6: the request must carry
        `expected_hangar_slot_version` matching the slot's current `version`,
        and a mismatch is rejected with `ERR_STALE_VERSION`."

        Design: Corner/errors/err_stale_version_on_workorder_create
        """
        reset_clock()
        owner = create_owner()
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA")
        slot = create_slot(aircraft["id"], hangar_code="H-SV")
        stale_version = slot["version"]
        # First WO creation advances the slot version by one.
        create_work_order(aircraft["id"], slot, mechanic["id"])
        # Reusing the stale version must now be rejected.
        res = api.create_work_order(
            {
                "aircraft_id": aircraft["id"],
                "hangar_slot_id": slot["id"],
                "opened_by_mechanic_id": mechanic["id"],
                "scope_type": "ANNUAL",
                "pricing_mode": "HOURLY",
                "expected_hangar_slot_version": stale_version,
            },
            SM,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        assert res.status_code == 412

    def test_stale_discrepancy_version_rejected(self, api):
        """PRD §2.6: "Posting an owner decision on a discrepancy requires the
        client to supply `expected_discrepancy_version`, carrying the `version`
        of the discrepancy as the client last observed it. If the discrepancy's
        current `version` has advanced beyond that value, the decision is
        rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to
        re-read the discrepancy rather than decide on a finding that has
        changed underfoot."

        Design: Corner/errors/err_stale_version_on_discrepancy_decide
        """
        from test_helpers import setup_wo_with_failed_inspection
        # Low cap forces PENDING_OWNER_DECISION so a decision is applicable.
        owner, aircraft, mechanic, slot, wo, discrepancy = setup_wo_with_failed_inspection(
            owner_cap=10000
        )
        current = get_success_data(api.get_discrepancy(discrepancy["id"], SM))
        res = api.decide_discrepancy(
            discrepancy["id"],
            {"decision": "APPROVE",
             "expected_discrepancy_version": current["version"] - 1},
            make_owner_headers(owner["id"]),
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        assert res.status_code == 412


class TestRoleDenials:
    def test_mechanic_cannot_cancel_work_order(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: "POST /api/work-orders/{id}/cancel — Cancel a draft work order
        (`DRAFT` → `CANCELLED`) — ShopManager."

        Design: Corner/roles/mechanic_cannot_cancel_work_order
        """
        owner, aircraft, mechanic, slot, wo = setup_shop()
        res = api.cancel_work_order(wo["id"], make_mechanic_headers(mechanic["id"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
        assert res.status_code == 403

    def test_owner_cannot_start_work_order(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: "POST /api/work-orders/{id}/start — Start work (`SCHEDULED` →
        `IN_PROGRESS`); occupies the slot — Mechanic."

        Design: Corner/roles/owner_cannot_start_work_order
        """
        owner, aircraft, mechanic, slot, wo = setup_shop()
        get_success_data(api.schedule_work_order(wo["id"], SM))
        res = api.start_work_order(wo["id"], make_owner_headers(owner["id"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
        assert res.status_code == 403


class TestOccHappyPathAndConsistency:
    def test_correct_slot_version_succeeds_and_advances_slot(self, api):
        """PRD §3.2: "Successfully opening the work order itself advances the
        linked slot's `version` by one, so any other client holding the slot's
        old version is immediately stale."

        Design: Corner/cross_cutting_layers/optimistic_concurrency_workorder_create_happy_path
        """
        reset_clock()
        owner = create_owner()
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA")
        slot = create_slot(aircraft["id"], hangar_code="H-OCC")
        before_version = slot["version"]
        wo = validate_success(
            api.create_work_order(
                {
                    "aircraft_id": aircraft["id"],
                    "hangar_slot_id": slot["id"],
                    "opened_by_mechanic_id": mechanic["id"],
                    "scope_type": "ANNUAL",
                    "pricing_mode": "HOURLY",
                    "expected_hangar_slot_version": before_version,
                },
                SM,
            ),
            201,
        )
        slot_after = get_success_data(api.get_hangar_slot(slot["id"], SM))
        assert slot_after["version"] == before_version + 1, (
            f"slot version must advance by 1 on WO create: {before_version} -> {slot_after['version']}"
        )

    def test_posted_labor_entry_visible_immediately(self, api):
        """PRD §3.6: "An entry is `POSTED` when created and may later be
        `VOIDED`; the work order's `labor_hours_tenths` accumulates the
        `duration_tenths` of its non-voided entries only."

        Design: Corner/consistency_model/immediate_visibility_of_posted_labor_entry
        """
        owner, aircraft, mechanic, slot, wo = setup_shop()
        wo = start_work_order(wo, mechanic)
        mech_h = make_mechanic_headers(mechanic["id"])
        validate_success(
            api.create_labor_entry(
                wo["id"],
                {"mechanic_id": mechanic["id"], "duration_tenths": 3, "notes": "n"},
                mech_h,
            ),
            201,
        )
        wo_after = get_success_data(api.get_work_order(wo["id"], mech_h))
        assert wo_after["labor_hours_tenths"] == 3, (
            f"labor_hours_tenths must reflect the entry immediately, got {wo_after['labor_hours_tenths']}"
        )

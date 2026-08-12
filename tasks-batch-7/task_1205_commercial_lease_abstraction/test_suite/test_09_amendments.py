"""Amendments: approve/apply gates, OCC, per-kind direction rules, the
RENT_CHANGE cascade, the approve/reject conservation invariant, and the
EXTENSION atomic side effects."""
from test_helpers import (
    ApiErrorId,
    add_schedule_line,
    approve_amendment_on,
    apply_amendment_on,
    certify_lease,
    create_amendment_on,
    create_billing,
    create_critical_date_on,
    create_lease,
    create_pool,
    create_property,
    get_lease,
    issue_billing,
    set_clock,
    setup_active_lease,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["portfolio_manager_headers"]
PROP_MGR = TEST_USERS["property_manager_headers"]


class TestApproveRequiresActiveLease:
    def _draft_lease_with_amendment(self, api):
        set_clock()
        prop = create_property()
        lease = create_lease(prop["id"])  # stays DRAFT
        amendment = create_amendment_on(
            lease["id"], kind="RENT_CHANGE", effective_date="2027-06-01",
            new_base_rent_annual_cents=2400000,
        )
        return lease, amendment

    def test_approve_on_draft_lease_rejected(self, api):
        """PRD §3.8: "Approval is the second OCC-guarded write in the system:
        approving requires the lease to be `ACTIVE` (else
        `ERR_LEASE_NOT_ACTIVE`) and requires the request's
        `expected_lease_version` to match the lease's current `version`, else
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Difficulty/cross_entity_state_dependency/amendment_apply_requires_lease_active
        """
        lease, amendment = self._draft_lease_with_amendment(api)
        current = get_lease(lease["id"])
        resp = api.approve_amendment(
            amendment["id"], {"expected_lease_version": current["version"]}, PM,
        )
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_ACTIVE)

    def test_rejected_approve_leaves_amendment_proposed(self, api):
        """PRD §3.8: "Approval is the second OCC-guarded write in the system:
        approving requires the lease to be `ACTIVE` (else
        `ERR_LEASE_NOT_ACTIVE`) and requires the request's
        `expected_lease_version` to match the lease's current `version`, else
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.8: "A proposed amendment begins `PROPOSED`, and the amendment
        collection is filterable by `lease_id`, `kind`, or `status`."
        (A failed approval performs no transition.)

        Design: Difficulty/cross_entity_state_dependency/amendment_apply_requires_lease_active
        """
        lease, amendment = self._draft_lease_with_amendment(api)
        current = get_lease(lease["id"])
        validate_error(
            api.approve_amendment(
                amendment["id"], {"expected_lease_version": current["version"]}, PM,
            ),
            ApiErrorId.ERR_LEASE_NOT_ACTIVE,
        )
        after = validate_success(api.get_amendment(amendment["id"], PM))
        assert after["status"] == "PROPOSED", (
            f"failed approve must not transition the amendment, got {after['status']}"
        )
        lease_after = get_lease(lease["id"])
        assert lease_after["status"] == "DRAFT"


class TestAmendmentOcc:
    def test_occ_stale_version_on_amendment_approve(self, api):
        """PRD §2.10: "If the value does not match the Lease's current
        `version` — because another writer has advanced the lease since the
        client last read it, for example by approving a different amendment
        against the same lease — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a
        lease state it has not observed."
        PRD §3.8: "A successful approval moves the amendment from `PROPOSED` to
        `APPROVED` and increments the lease's `version` — which is precisely the
        advancement that invalidates any other client's stale view of the same
        lease."

        Design: Corner/validations/occ_stale_version_on_amendment_approve
        """
        ctx = setup_active_lease()
        lease = ctx["lease"]
        a1 = create_amendment_on(
            lease["id"], kind="RENT_CHANGE", effective_date="2027-06-01",
            new_base_rent_annual_cents=2400000,
        )
        a2 = create_amendment_on(lease["id"], kind="USE_CHANGE",
                                 effective_date="2027-07-01")
        observed_version = get_lease(lease["id"])["version"]
        approve_amendment_on(a1["id"], observed_version)  # advances Lease.version
        resp = api.approve_amendment(
            a2["id"], {"expected_lease_version": observed_version}, PM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestApplyDirectionRules:
    def test_amendment_extension_must_extend(self, api):
        """PRD §3.8: "An `EXTENSION` must set a `new_expiration_date` strictly
        later than the lease's current `expiration_date`, else
        `ERR_EXTENSION_MUST_EXTEND`."

        Design: Corner/validations/amendment_extension_must_extend
        """
        ctx = setup_active_lease()
        amendment = create_amendment_on(
            ctx["lease"]["id"], kind="EXTENSION", effective_date="2026-06-01",
            new_expiration_date="2026-06-01",  # earlier than 2026-12-31
        )
        approve_amendment_on(amendment["id"], ctx["lease"]["version"])
        resp = api.apply_amendment(amendment["id"], PM)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_MUST_EXTEND)

    def test_amendment_expansion_blocked_by_property_overcommit(self, api):
        """PRD §3.8: "An `EXPANSION` must set a `new_leased_sf` greater than the
        current `leased_sf`, else `ERR_EXPANSION_MUST_EXPAND`, and must not
        overcommit the property: the new square footage plus the sum of
        `leased_sf` over all other `ACTIVE` leases on the same property must
        not exceed the property's `total_rentable_sf`, else
        `ERR_PROPERTY_OVERCOMMITTED`."
        (Lease A holds 9000 SF; lease B expanding to 1500 SF would push the
        total to 10500 against a 10000 SF property.)

        Design: Corner/validations/amendment_expansion_blocked_by_property_overcommit
        """
        set_clock()
        prop = create_property()
        pool = create_pool(prop["id"])
        # Lease A: 9000 SF, ACTIVE.
        la = create_lease(prop["id"], tenant_legal_name="A", suite="100",
                          leased_sf=9000, pro_rata_share_bps=9000)
        certify_lease(la["id"])
        add_schedule_line(la["id"])
        create_billing(la["id"], pool["id"])
        validate_success(api.activate_lease(la["id"], PM))
        # Lease B: 500 SF, ACTIVE.
        lb = create_lease(prop["id"], tenant_legal_name="B", suite="200",
                          leased_sf=500, base_rent_annual_cents=120000,
                          pro_rata_share_bps=500)
        certify_lease(lb["id"])
        add_schedule_line(lb["id"], base_rent_cents=120000)
        create_billing(lb["id"], pool["id"])
        lb_active = validate_success(api.activate_lease(lb["id"], PM))
        amendment = create_amendment_on(
            lb["id"], kind="EXPANSION", effective_date="2027-06-01",
            new_leased_sf=1500,
        )
        approve_amendment_on(amendment["id"], lb_active["version"])
        resp = api.apply_amendment(amendment["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_OVERCOMMITTED)


class TestAmendmentTerminalStates:
    def test_amendment_reject_from_applied_rejected(self, api):
        """PRD §3.8: "Either a `PROPOSED` or an `APPROVED` amendment may instead
        be rejected by a `PortfolioManager`, moving it to `REJECTED`; `APPLIED`
        and `REJECTED` are terminal, so an amendment that has already been
        applied can no longer be rejected."
        PRD §2.11: "Sixth, state-machine legality on every state-transition
        endpoint, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/amendment_reject_from_applied_rejected
        """
        ctx = setup_active_lease()
        amendment = create_amendment_on(
            ctx["lease"]["id"], kind="RENT_CHANGE", effective_date="2027-06-01",
            new_base_rent_annual_cents=2400000,
        )
        approve_amendment_on(amendment["id"], ctx["lease"]["version"])
        applied = apply_amendment_on(amendment["id"])
        assert applied["status"] == "APPLIED"
        resp = api.reject_amendment(amendment["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRentChangeCascade:
    def _setup(self, api):
        """ACTIVE lease: past line [2027-01-01, 2027-07-01) at 600000 and a
        future line [2027-07-01, 2028-01-01) at 600000 carrying a 10% FIXED_PCT
        step (effective 660000); clock mid-year so both lines overlap FY2027."""
        set_clock("2027-06-01T00:00:00Z")
        prop = create_property()
        lease = create_lease(
            prop["id"], escalation_type="FIXED_PCT",
            recovery_structure="NNN", pro_rata_share_bps=0,
            commencement_date="2027-01-01", expiration_date="2027-12-31",
        )
        certify_lease(lease["id"])
        step = validate_success(
            api.create_escalation_step(
                lease["id"],
                {"step_index": 1, "kind": "FIXED_PCT", "pct_bps": 1000,
                 "effective_on": "2027-07-01"},
                PM,
            ),
            201,
        )
        line_past = add_schedule_line(
            lease["id"], period_start="2027-01-01", period_end="2027-07-01",
            base_rent_cents=600000,
        )
        line_future = add_schedule_line(
            lease["id"], period_start="2027-07-01", period_end="2028-01-01",
            base_rent_cents=600000, escalation_step_id=step["id"],
        )
        assert line_future["effective_rent_cents"] == 660000
        pool = create_pool(prop["id"], budgeted_cents=0, fiscal_year=2027)
        create_billing(lease["id"], pool["id"], fiscal_year=2027)
        lease = validate_success(api.activate_lease(lease["id"], PM))
        assert lease["cached_annual_rent_cents"] == 1260000
        amendment = create_amendment_on(
            lease["id"], kind="RENT_CHANGE", effective_date="2027-07-01",
            new_base_rent_annual_cents=2400000,
        )
        approve_amendment_on(amendment["id"], lease["version"])
        return {
            "lease": lease, "amendment": amendment,
            "line_past": line_past, "line_future": line_future,
        }

    def test_future_line_recomputed_with_new_base(self, api):
        """PRD §3.8: "An applied `RENT_CHANGE` recomputes every RentScheduleLine
        whose `period_start` falls on or after the amendment's `effective_date`
        using the new annual base rent, which cascades into escalation
        recomputation per line, and refreshes the lease's
        `cached_annual_rent_cents`."

        Design: Difficulty/transitive_cascade/amendment_rent_change_cascade
        """
        ctx = self._setup(api)
        apply_amendment_on(ctx["amendment"]["id"])
        line = validate_success(
            api.get_rent_schedule_line(ctx["line_future"]["id"], PM)
        )
        assert line["base_rent_cents"] == 2400000, (
            f"future line base must be rewritten to the new annual base rent, "
            f"got {line['base_rent_cents']}"
        )
        assert line["effective_rent_cents"] == 2640000, (
            "escalation recompute: round_half_up(2400000 * 11000 / 10000) = "
            f"2640000, got {line['effective_rent_cents']}"
        )

    def test_lease_cached_rent_refreshes_through_cascade(self, api):
        """PRD §3.8: "An applied `RENT_CHANGE` recomputes every RentScheduleLine
        whose `period_start` falls on or after the amendment's `effective_date`
        using the new annual base rent, which cascades into escalation
        recomputation per line, and refreshes the lease's
        `cached_annual_rent_cents`."
        PRD §3.3: "This cache is refreshed on line creation or deletion, on
        lease activation, and when a rent-change amendment is applied."

        Design: Difficulty/transitive_cascade/amendment_rent_change_cascade
        """
        ctx = self._setup(api)
        rent_pre = ctx["lease"]["cached_annual_rent_cents"]
        assert rent_pre == 1260000  # 600000 + 660000 before the amendment
        apply_amendment_on(ctx["amendment"]["id"])
        lease_after = get_lease(ctx["lease"]["id"])
        # Past line unchanged (600000); future line recomputed (2640000).
        assert lease_after["cached_annual_rent_cents"] == 3240000, (
            f"expected 600000 + 2640000 = 3240000, got "
            f"{lease_after['cached_annual_rent_cents']}"
        )


class TestApproveRejectInvariant:
    def _setup(self, api):
        ctx = setup_active_lease()
        amendment = create_amendment_on(
            ctx["lease"]["id"], kind="EXPANSION", effective_date="2027-06-01",
            new_leased_sf=5000,
        )
        return ctx, amendment

    def test_lease_fields_conserved_after_approve_then_reject(self, api):
        """PRD §3.8: "On a successful apply, the lease's fields are rewritten
        per kind — `expiration_date` for an extension, `leased_sf` for an
        expansion or contraction, `base_rent_annual_cents` for a rent change,
        `tenant_legal_name` for an assignment — and the lease's `version`
        increments again."
        PRD §3.8: "Either a `PROPOSED` or an `APPROVED` amendment may instead
        be rejected by a `PortfolioManager`, moving it to `REJECTED`; `APPLIED`
        and `REJECTED` are terminal, so an amendment that has already been
        applied can no longer be rejected."
        (Approval alone rewrites no lease terms; rejection abandons the
        amendment without ever applying it.)

        Design: Difficulty/compensating_invariant/amendment_apply_reject_invariant_on_lease_version
        """
        ctx, amendment = self._setup(api)
        pre = ctx["lease"]
        approve_amendment_on(amendment["id"], pre["version"])
        rejected = validate_success(api.reject_amendment(amendment["id"], PM))
        assert rejected["status"] == "REJECTED"
        post = get_lease(ctx["lease"]["id"])
        assert post["leased_sf"] == pre["leased_sf"] == 4000, (
            f"leased_sf must be conserved, got {post['leased_sf']}"
        )
        assert post["base_rent_annual_cents"] == pre["base_rent_annual_cents"] == 1200000, (
            f"base_rent_annual_cents must be conserved, got "
            f"{post['base_rent_annual_cents']}"
        )

    def test_lease_version_advances_once_for_approve_only(self, api):
        """PRD §3.8: "A successful approval moves the amendment from `PROPOSED`
        to `APPROVED` and increments the lease's `version` — which is precisely
        the advancement that invalidates any other client's stale view of the
        same lease."
        PRD §2.4: "Any mutation of a resource — including mutations driven by
        cascades from a related entity, such as a lease's cached figures being
        recomputed when a schedule line changes — refreshes that resource's
        `updated_at` and increments its `version`."
        (Rejecting the amendment mutates only the amendment, not the lease.)

        Design: Difficulty/compensating_invariant/amendment_apply_reject_invariant_on_lease_version
        """
        ctx, amendment = self._setup(api)
        v_pre = ctx["lease"]["version"]
        approve_amendment_on(amendment["id"], v_pre)
        validate_success(api.reject_amendment(amendment["id"], PM))
        v_post = get_lease(ctx["lease"]["id"])["version"]
        assert v_post == v_pre + 1, (
            f"approve bumps Lease.version once and reject does not touch the "
            f"lease: expected {v_pre + 1}, got {v_post}"
        )


class TestExtensionAtomicSideEffects:
    def test_amendment_apply_atomic_side_effects(self, api):
        """PRD §3.8: "An applied `EXTENSION` transitions any `PENDING`
        CriticalDate of kind `EXPIRATION` whose `due_date` equals the old
        expiration date to `WAIVED` and creates a fresh `EXPIRATION`
        CriticalDate at the new expiration date."
        PRD §2.8: "More broadly, when a parent resource undergoes a transition
        that ends its operational life, the system resolves dependent child
        resources in the same atomic request — there is no asynchronous
        reconciliation — and conversely, child mutations that bear on a
        parent's derived fields cause the parent to be recomputed immediately."

        Design: Corner/consistency_model/amendment_apply_atomic_side_effects
        """
        ctx = setup_active_lease()
        cd_old = create_critical_date_on(
            ctx["lease"]["id"], kind="EXPIRATION",
            due_date="2026-12-31", advance_notice_days=0,
        )
        amendment = create_amendment_on(
            ctx["lease"]["id"], kind="EXTENSION", effective_date="2027-06-01",
            new_expiration_date="2029-12-31",
        )
        approve_amendment_on(amendment["id"], ctx["lease"]["version"])
        apply_amendment_on(amendment["id"])
        # All effects are visible in immediately subsequent reads.
        lease_after = get_lease(ctx["lease"]["id"])
        assert lease_after["expiration_date"] == "2029-12-31", (
            f"extension must rewrite expiration_date, got "
            f"{lease_after['expiration_date']}"
        )
        old_after = validate_success(api.get_critical_date(cd_old["id"], PROP_MGR))
        assert old_after["status"] == "WAIVED", (
            f"old EXPIRATION date must be WAIVED, got {old_after['status']}"
        )
        dates, _meta = validate_paginated(
            api.list_critical_dates(ctx["lease"]["id"], PROP_MGR,
                                    params={"kind": "EXPIRATION"})
        )
        statuses = sorted(d["status"] for d in dates)
        assert statuses == ["PENDING", "WAIVED"], (
            f"expected the old WAIVED date plus a fresh PENDING one, got {statuses}"
        )
        due_dates = sorted(d["due_date"] for d in dates)
        assert due_dates == ["2026-12-31", "2029-12-31"]

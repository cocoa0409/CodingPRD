"""Lease lifecycle: default/cure cycle, termination cascades, remarketing,
premises occupation (half-open terms), and the clock-driven expiry sweep."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_draw,
    create_draft_lease,
    create_draw,
    create_lease_payload,
    create_tenant,
    disburse_draw,
    get_lease,
    setup_active_lease,
    validate_error,
    validate_success,
)


class TestDefaultCureCycle:
    def test_default_sets_reason_and_cure_clears_it(self, api, admin_headers):
        """PRD §3.2: "Declaring default, an `action` of `DECLARE_DEFAULT`, moves an
        `ACTIVE` lease to `DEFAULTED`. The accompanying `reason` must be one of
        `NONPAYMENT`, `HOURS_SHORTFALL`, `ACDBE_NONCOMPLIANCE`, or `OTHER` — an
        undeclared value fails enum validation with `ERR_INVALID_ENUM` — and is
        recorded on the lease as `default_reason`; the lease's `version` increments.
        Curing the default, an `action` of `CURE_DEFAULT`, moves `DEFAULTED → ACTIVE`
        and clears `default_reason` back to null, again incrementing `version`."

        Design: Difficulty/non_linear_state_machine/lease_default_cure_cycle
        """
        sc = setup_active_lease()
        lease = sc["lease"]

        defaulted = validate_success(
            api.transition_lease(
                lease["id"],
                {"action": "DECLARE_DEFAULT", "reason": "NONPAYMENT"},
                admin_headers,
            ),
            200,
        )
        assert defaulted["status"] == "DEFAULTED"
        assert defaulted["default_reason"] == "NONPAYMENT"

        cured = validate_success(
            api.transition_lease(lease["id"], {"action": "CURE_DEFAULT"}, admin_headers),
            200,
        )
        assert cured["status"] == "ACTIVE"
        assert cured["default_reason"] is None

    def test_default_cure_cycle_is_repeatable(self, api, admin_headers):
        """PRD §3.2: "The `ACTIVE ↔ DEFAULTED` cycle is repeatable across the life of
        the lease."

        Design: Difficulty/non_linear_state_machine/lease_default_cure_cycle
        """
        sc = setup_active_lease()
        lease = sc["lease"]

        for reason in ("NONPAYMENT", "HOURS_SHORTFALL"):
            defaulted = validate_success(
                api.transition_lease(
                    lease["id"],
                    {"action": "DECLARE_DEFAULT", "reason": reason},
                    admin_headers,
                ),
                200,
            )
            assert defaulted["status"] == "DEFAULTED"
            assert defaulted["default_reason"] == reason
            cured = validate_success(
                api.transition_lease(
                    lease["id"], {"action": "CURE_DEFAULT"}, admin_headers
                ),
                200,
            )
            assert cured["status"] == "ACTIVE"
            assert cured["default_reason"] is None


class TestTerminationCascade:
    def _setup_lease_with_two_draws(self):
        """ACTIVE lease (TI allowance 500,000) with draw D1 100,000 APPROVED and
        draw D2 200,000 APPROVED then DISBURSED; ti_remaining is 200,000."""
        sc = setup_active_lease(ti_allowance_cents=500_000)
        lease, tenant = sc["lease"], sc["tenant"]
        d1 = approve_draw(create_draw(lease, tenant, 100_000, milestone="DESIGN"))
        d2 = approve_draw(create_draw(lease, tenant, 200_000, milestone="CONSTRUCTION"))
        d2 = disburse_draw(d2)
        lease_now = get_lease(lease["id"])
        assert lease_now["ti_remaining_cents"] == 200_000, (
            f"Setup failed: ti_remaining should be 200,000, got {lease_now}"
        )
        return sc, d1, d2

    def test_termination_cancels_pending_draws_keeps_disbursed(
        self, api, admin_headers
    ):
        """PRD §3.2: "Termination, an `action` of `TERMINATE`, moves a lease from
        `ACTIVE` or `DEFAULTED` to `TERMINATED` and triggers a three-part cascade
        across its children. First, every buildout draw of the lease in `REQUESTED`
        or `APPROVED` moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/lease_termination_cancels_draws
        """
        sc, d1, d2 = self._setup_lease_with_two_draws()

        terminated = validate_success(
            api.transition_lease(
                sc["lease"]["id"], {"action": "TERMINATE"}, admin_headers
            ),
            200,
        )
        assert terminated["status"] == "TERMINATED"

        d1_after = validate_success(api.get_ti_draw(d1["id"], admin_headers), 200)
        d2_after = validate_success(api.get_ti_draw(d2["id"], admin_headers), 200)
        assert d1_after["status"] == "CANCELLED", (
            f"APPROVED draw must be cancelled by termination: {d1_after}"
        )
        assert d2_after["status"] == "DISBURSED", (
            f"DISBURSED (terminal) draw must be untouched by termination: {d2_after}"
        )

    def test_termination_releases_approved_reserve_into_allowance(
        self, api, admin_headers
    ):
        """PRD §3.2: "Second, `ti_remaining_cents` is recomputed, which releases the
        approved-but-undisbursed reserve back into the allowance."
        PRD §2.9: "`ti_remaining_cents` is the lease's `ti_allowance_cents` minus the
        amounts of its `DISBURSED` draws minus the amounts of its `APPROVED` draws
        still awaiting disbursement — the approved-but-undisbursed portion is a live
        reserve — while draws in `REQUESTED`, `REJECTED`, or `CANCELLED` contribute
        nothing."

        Design: Difficulty/transitive_cascade/lease_termination_cancels_draws
        """
        sc, d1, d2 = self._setup_lease_with_two_draws()

        validate_success(
            api.transition_lease(
                sc["lease"]["id"], {"action": "TERMINATE"}, admin_headers
            ),
            200,
        )
        lease_after = get_lease(sc["lease"]["id"])
        # 500,000 allowance - 200,000 disbursed (D2); D1's 100,000 reserve released.
        assert lease_after["ti_remaining_cents"] == 300_000, (
            f"ti_remaining must be 300,000 after termination, got {lease_after}"
        )


class TestPremisesOccupation:
    def _setup_incumbent_lease(self, admin_headers):
        tenant = create_tenant()
        incumbent = validate_success(
            api_client.create_lease(
                create_lease_payload(
                    tenant["id"],
                    premises_code="B2",
                    term_start_date="2026-01-01",
                    term_end_date="2030-12-31",
                ),
                admin_headers,
            ),
            201,
        )
        validate_success(
            api_client.transition_lease(
                incumbent["id"], {"action": "ACTIVATE"}, admin_headers
            ),
            200,
        )
        return tenant, incumbent

    def test_premises_overlap_one_day_before_end_rejected(self, api, admin_headers):
        """PRD §3.1: "Creation enforces the premises-occupation rule: no two leases in
        `DRAFT`, `ACTIVE`, or `DEFAULTED` may share a `premises_code` with overlapping
        half-open terms — adjacency, where one term's start equals the other's end, is
        allowed — and a violation is rejected with `ERR_PREMISES_TERM_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/premises_term_overlap_half_open
        """
        tenant, _ = self._setup_incumbent_lease(admin_headers)
        res = api.create_lease(
            create_lease_payload(
                tenant["id"],
                premises_code="B2",
                term_start_date="2030-12-30",  # one day before incumbent's end
                term_end_date="2035-12-31",
                buildout_deadline="2031-09-30",
            ),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_PREMISES_TERM_OVERLAP)

    def test_premises_adjacent_term_allowed(self, api, admin_headers):
        """PRD §3.1: "The term is a half-open interval: occupation begins on
        `term_start_date` inclusive, and `term_end_date` is the exclusive boundary
        day — the premises is free for a new lease whose `term_start_date` equals an
        existing lease's `term_end_date`."

        Design: Difficulty/resource_temporal_overlap/premises_term_overlap_half_open
        """
        tenant, _ = self._setup_incumbent_lease(admin_headers)
        res = api.create_lease(
            create_lease_payload(
                tenant["id"],
                premises_code="B2",
                term_start_date="2030-12-31",  # exactly the incumbent's end
                term_end_date="2035-12-31",
                buildout_deadline="2031-09-30",
            ),
            admin_headers,
        )
        adjacent = validate_success(res, 201)
        assert adjacent["status"] == "DRAFT"


class TestTerminalAndSweepTransitions:
    def test_terminate_draft_lease_returns_lease_state_forbids(
        self, api, admin_headers
    ):
        """PRD §3.2: "A `DRAFT` lease can be neither terminated nor expired — it must
        be activated first."
        PRD §2.8: "State-machine legality — the requested action is valid from the
        resource's current status, producing the relevant 409 state error (for example
        `ERR_LEASE_STATE_FORBIDS`, `ERR_REPORT_NOT_SUBMITTABLE`, or
        `ERR_DRAW_STATE_FORBIDS`)."

        Design: Corner/state_machines/terminate_draft_lease_returns_lease_state_forbids
        """
        tenant = create_tenant()
        lease = create_draft_lease(tenant)
        res = api.transition_lease(
            lease["id"], {"action": "TERMINATE"}, admin_headers
        )
        validate_error(res, ApiErrorId.ERR_LEASE_STATE_FORBIDS)

    def test_remarket_after_termination_frees_premises(self, api, admin_headers):
        """PRD §3.2: "From `TERMINATED`, a remarketing action — an `action` of
        `REMARKET` — moves the lease to `REMARKETING`: the premises becomes available
        again because the lease no longer participates in the premises term-overlap
        check."

        Design: Corner/state_machines/remarket_after_termination_frees_premises
        """
        tenant = create_tenant()
        lease = validate_success(
            api.create_lease(
                create_lease_payload(
                    tenant["id"],
                    premises_code="B9",
                    term_start_date="2026-01-01",
                    term_end_date="2030-12-31",
                ),
                admin_headers,
            ),
            201,
        )
        validate_success(
            api.transition_lease(lease["id"], {"action": "ACTIVATE"}, admin_headers), 200
        )
        validate_success(
            api.transition_lease(lease["id"], {"action": "TERMINATE"}, admin_headers),
            200,
        )
        remarketed = validate_success(
            api.transition_lease(lease["id"], {"action": "REMARKET"}, admin_headers),
            200,
        )
        assert remarketed["status"] == "REMARKETING"

        new_lease = validate_success(
            api.create_lease(
                create_lease_payload(
                    tenant["id"],
                    premises_code="B9",
                    term_start_date="2027-01-01",
                    term_end_date="2032-12-31",
                    buildout_deadline="2027-09-30",
                ),
                admin_headers,
            ),
            201,
        )
        assert new_lease["status"] == "DRAFT", (
            "After remarketing, the premises no longer participates in the overlap "
            "check, so an overlapping new lease must be created"
        )

    def test_lease_expired_by_clock_sweep(self, api, admin_headers):
        """PRD §3.2: "When the logical clock is advanced (§2.4) such that the new
        current date is later than a lease's `term_end_date`, every lease in `ACTIVE`
        or `DEFAULTED` sweeps to `EXPIRED`, with the same child cascades as
        termination — draws cancelled, the TI reserve released, pending waivers
        rejected."

        Design: Corner/state_machines/lease_expired_by_clock_sweep
        """
        tenant = create_tenant()
        lease = validate_success(
            api.create_lease(
                create_lease_payload(
                    tenant["id"],
                    premises_code="C3",
                    category="RETAIL",
                    term_start_date="2026-01-01",
                    term_end_date="2026-07-31",
                    mag_annual_cents=600_000,
                    ti_allowance_cents=100_000,
                    buildout_deadline="2026-03-31",
                ),
                admin_headers,
            ),
            201,
        )
        validate_success(
            api.transition_lease(lease["id"], {"action": "ACTIVATE"}, admin_headers), 200
        )
        validate_success(
            api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, admin_headers), 200
        )
        lease_after = validate_success(api.get_lease(lease["id"], admin_headers), 200)
        assert lease_after["status"] == "EXPIRED"

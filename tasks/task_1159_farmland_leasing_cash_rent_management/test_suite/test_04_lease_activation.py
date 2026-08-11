"""Lease activation: generated rent schedule, cross-entity activation gates
(tenant standing, unresolved non-compliance), half-open field-overlap
semantics, and acceptance-expiry pipeline ordering."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_iso_instant_equal,
    create_lease_payload,
    get_bid,
    get_lease,
    get_tenant,
    list_lease_installments,
    setup_active_lease,
    setup_bid,
    setup_draft_lease,
    setup_noncompliant_tenant_scenario,
    setup_offering,
    setup_second_draft_lease,
    setup_tenant,
    set_clock,
    shortlist_close_award,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]


def _second_awarded_bid_same_field(ctx: dict, years_experience: int = 9) -> dict:
    """Second tenant wins a second offering on the SAME field. Returns the
    ACCEPTED bid. Award happens at the current clock."""
    tenant2 = setup_tenant(name="T Second", years_experience=years_experience)
    offering2 = setup_offering(
        ctx["field"]["id"], term_start_date="2028-03-01T00:00:00Z"
    )
    bid2 = setup_bid(
        offering2["id"], tenant2["id"], "CASH",
        cash_bid_per_acre_cents=26000, cash_equivalent_bid_cents_per_acre=26000,
    )
    bid2 = shortlist_close_award(offering2["id"], bid2["id"], ctx["landlord"]["id"])
    ctx["tenant2"] = tenant2
    ctx["offering2"] = offering2
    ctx["bid2"] = bid2
    return bid2


class TestActivationSchedule:
    def test_lease_activation_generates_exact_installments(self, api):
        """PRD §3.5: "The annual rent is the lease's `base_rent_cents_per_acre` multiplied by the field's `acres`."
        PRD §3.5: "Under `MAR_NOV_50_50`, two installments fall due on March 1 and November 1 of the term year: the first is half the annual rent rounded half up to whole cents, and the second is the annual rent minus the first."
        PRD §3.5: "The rounding order is pinned: each installment is rounded half up first, and any remainder is allocated to the last installment of the term year."
        PRD §3.4: "A successful activation moves the lease from `DRAFT` to `ACTIVE`, moves the field from `AVAILABLE` to `LEASED`, generates the payment schedule described in §3.5"

        Design: Corner/state_machines/lease_activation_generates_exact_installments
        """
        ctx = setup_active_lease("CASH", acres=101, cash_bid_cents=25001)
        # annual = 25001 * 101 = 2525101; first = round_half_up(1262550.5) = 1262551,
        # second = 2525101 - 1262551 = 1262550.
        installments = list_lease_installments(ctx["lease"]["id"])
        assert len(installments) == 2, "MAR_NOV_50_50 generates exactly two installments"
        first, second = installments
        assert first["amount_cents"] == 1262551
        assert_iso_instant_equal(first["due_date"], "2027-03-01T00:00:00Z")
        assert first["status"] == "SCHEDULED"
        assert first["paid_cents"] == 0 and first["late_fee_cents"] == 0
        assert second["amount_cents"] == 1262550
        assert_iso_instant_equal(second["due_date"], "2027-11-01T00:00:00Z")
        assert first["amount_cents"] + second["amount_cents"] == 2525101
        assert ctx["field"]["status"] == "LEASED", "activation leases the field"
        assert ctx["lease"]["status"] == "ACTIVE"


class TestActivationGates:
    def test_lease_activation_blocked_by_suspended_tenant(self, api):
        """PRD §3.4: "Activation is the gate that puts the lease on the ground, and its three preconditions are evaluated in this order: first, the tenant must be `APPROVED`, else `ERR_TENANT_NOT_APPROVED`"
        PRD §3.1: "Approval by a manager moves an applicant from `APPLICANT` to `APPROVED`, and only `APPROVED` tenants may bid or have leases activated for them."

        Design: Difficulty/cross_entity_state_dependency/lease_activation_blocked_by_suspended_tenant
        """
        ctx = setup_active_lease("CASH", activate=False)
        assert ctx["lease"]["status"] == "DRAFT"
        validate_success(api.suspend_tenant(ctx["tenant"]["id"], MGR))
        assert get_tenant(ctx["tenant"]["id"])["status"] == "SUSPENDED"

        resp = api.activate_lease(ctx["lease"]["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_TENANT_NOT_APPROVED)
        assert get_lease(ctx["lease"]["id"])["status"] == "DRAFT", (
            "failed activation leaves the lease DRAFT"
        )

    def test_lease_activation_succeeds_after_tenant_reinstated(self, api):
        """PRD §3.1: "Reinstatement is manual: the same approval action moves `SUSPENDED` back to `APPROVED`, but bids withdrawn by the cascade stay `WITHDRAWN`."
        PRD §3.4: "first, the tenant must be `APPROVED`, else `ERR_TENANT_NOT_APPROVED`"

        Design: Difficulty/cross_entity_state_dependency/lease_activation_blocked_by_suspended_tenant
        """
        ctx = setup_active_lease("CASH", activate=False)
        validate_success(api.suspend_tenant(ctx["tenant"]["id"], MGR))
        resp = api.activate_lease(ctx["lease"]["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_TENANT_NOT_APPROVED)

        reinstated = validate_success(api.approve_tenant(ctx["tenant"]["id"], MGR))
        assert reinstated["status"] == "APPROVED"
        activated = validate_success(api.activate_lease(ctx["lease"]["id"], MGR))
        assert activated["status"] == "ACTIVE", (
            "reinstated tenant passes the activation gate"
        )

    def test_lease_activation_blocked_by_unresolved_noncompliance(self, api):
        """PRD §3.4: "second, the tenant must hold no compliance record in `NON_COMPLIANT` status on any lease, else `ERR_TENANT_NONCOMPLIANT`"
        PRD §3.7: "A `NON_COMPLIANT` record also blocks any future lease activation for that tenant, per §3.4."

        Design: Corner/validations/lease_activation_blocked_by_unresolved_noncompliance
        """
        ctx = setup_noncompliant_tenant_scenario(num_practices=1)
        tenant = get_tenant(ctx["tenant"]["id"])
        assert tenant["compliance_score"] == 85, "one event: 100 - 15"
        assert tenant["status"] == "APPROVED", "85 is not below the suspension line"
        assert ctx["records"][0]["status"] == "NON_COMPLIANT"

        lease2 = setup_second_draft_lease(ctx)
        resp = api.activate_lease(lease2["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_TENANT_NONCOMPLIANT)
        assert get_lease(lease2["id"])["status"] == "DRAFT"


class TestFieldOverlapAndAcceptanceWindow:
    def test_overlapping_term_rejected_half_open(self, api):
        """PRD §3.4: "third, no other lease on the same field may overlap the new term in `ACTIVE` or `TERMINATION_PENDING` status — overlap is judged on the half-open interval `[term_start_date, term_end_date)`, so back-to-back terms that merely touch are allowed — else `ERR_FIELD_LEASE_OVERLAP`."
        PRD §2.9: "A lease term is a half-open interval: it includes `term_start_date` and excludes `term_end_date`, written `[term_start_date, term_end_date)`."

        Design: Difficulty/resource_temporal_overlap/field_lease_half_open_adjacency
        """
        ctx = setup_active_lease("CASH")
        bid2 = _second_awarded_bid_same_field(ctx)

        resp = api.create_lease(
            create_lease_payload(
                bid2["id"],
                term_start_date="2027-06-01T00:00:00Z",
                term_end_date="2028-06-01T00:00:00Z",
            ),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_FIELD_LEASE_OVERLAP)

    def test_adjacent_term_allowed_half_open(self, api):
        """PRD §2.9: "Overlap between leases on the same field is judged under these half-open semantics, so two leases whose terms merely touch — one ending exactly when the other begins — are adjacent, not overlapping, and are allowed."

        Design: Difficulty/resource_temporal_overlap/field_lease_half_open_adjacency
        """
        ctx = setup_active_lease("CASH")  # term [2027-03-01, 2028-03-01)
        bid2 = _second_awarded_bid_same_field(ctx)

        resp = api.create_lease(
            create_lease_payload(
                bid2["id"],
                term_start_date="2028-03-01T00:00:00Z",
                term_end_date="2029-03-01T00:00:00Z",
            ),
            MGR,
        )
        lease2 = validate_success(resp, 201)
        assert lease2["status"] == "DRAFT", (
            "start == existing end is adjacent (disjoint under half-open semantics)"
        )

    def test_expired_acceptance_temporal_beats_overlap_referential(self, api):
        """PRD §2.8: "Incoming requests are validated against a fixed pipeline, and when several checks would fail, the earliest category's error is the one returned."
        PRD §2.8: "Deadline and window checks — bid creation after the offering's `bid_deadline` yields `ERR_BID_WINDOW_CLOSED` (HTTP 409); lease creation more than thirty days after the bid's `accepted_at` yields `ERR_BID_ACCEPTANCE_EXPIRED` (HTTP 409); a report whose `period_start` is later than its `period_end` yields `ERR_INVALID_PERIOD` (HTTP 422)."
        PRD §2.8: "Cross-entity referential integrity — an overlapping `ACTIVE` or `TERMINATION_PENDING` lease on the same field yields `ERR_FIELD_LEASE_OVERLAP` (HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/expired_acceptance_temporal_beats_overlap_referential
        """
        ctx = setup_active_lease("CASH")
        bid2 = _second_awarded_bid_same_field(ctx)
        assert get_bid(bid2["id"])["status"] == "ACCEPTED"

        # accepted_at is the default clock 2026-05-01; thirty days later is
        # 2026-05-31, so at 2026-06-01 the acceptance window has expired.
        set_clock("2026-06-01T00:00:00Z")
        resp = api.create_lease(
            create_lease_payload(
                bid2["id"],
                term_start_date="2027-06-01T00:00:00Z",
                term_end_date="2028-06-01T00:00:00Z",
            ),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_BID_ACCEPTANCE_EXPIRED)

    def test_expired_acceptance_fires_without_overlap(self, api):
        """PRD §2.8: "lease creation more than thirty days after the bid's `accepted_at` yields `ERR_BID_ACCEPTANCE_EXPIRED` (HTTP 409)"
        PRD §3.4: "The bid must be `ACCEPTED`, the clock must be on or before the bid's `accepted_at` plus thirty days — a later attempt fails with `ERR_BID_ACCEPTANCE_EXPIRED`"

        Design: Difficulty/priority_pair_validation_conflict/expired_acceptance_temporal_beats_overlap_referential
        """
        ctx = setup_active_lease("CASH")
        bid2 = _second_awarded_bid_same_field(ctx)
        set_clock("2026-06-01T00:00:00Z")
        # Term [2028-06-01, 2029-06-01) does NOT overlap lease1's
        # [2027-03-01, 2028-03-01): only the temporal rule can fail.
        resp = api.create_lease(
            create_lease_payload(
                bid2["id"],
                term_start_date="2028-06-01T00:00:00Z",
                term_end_date="2029-06-01T00:00:00Z",
            ),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_BID_ACCEPTANCE_EXPIRED)

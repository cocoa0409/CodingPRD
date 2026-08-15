"""Change-order cost accounting and tenant overage invoicing."""
from test_helpers import (
    ApiErrorId,
    create_approved_change_order,
    create_submitted_change_order,
    get_success_data,
    make_contractor_rep_headers,
    make_landlord_approver_headers,
    make_tenant_rep_headers,
    set_logical_clock,
    setup_project_in_construction,
    validate_error,
    validate_success,
)


def make_contractor_headers(sc):
    """Entity-backed headers for the scenario's contractor."""
    return make_contractor_rep_headers(sc["contractor"]["id"])


class TestChangeOrderMarkup:
    def test_change_order_markup_per_line_rounding(self, api, landlord_pm_headers):
        """PRD 3.5: "First the markup runs over the order's own lines: each
        line's markup is ten percent of its `amount_cents`, rounded half up to
        a whole cent per line, and only then summed — the order's
        `total_cost_cents` is the plain sum of its line amounts, its
        `markup_cents` is the sum of those per-line-rounded markups, and its
        `total_with_markup_cents` is the two added together; the per-line-first
        rounding order is normative, since rounding the aggregate instead can
        produce a different cent."

        Design: Difficulty/combinatorial_formula/change_order_markup_per_line_rounding
        """
        sc = setup_project_in_construction()
        set_logical_clock("2026-08-15T00:00:00Z")
        ctr_headers = make_contractor_headers(sc)

        co = create_approved_change_order(
            sc["project"]["id"],
            ctr_headers,
            lines=[
                {"description": "a", "amount_cents": 1005},
                {"description": "b", "amount_cents": 1005},
            ],
            approver_id="approver-2",
        )
        assert co["total_cost_cents"] == 2010
        # round_half_up(1005 * 0.10) == 101 per line, summed -> 202;
        # rounding the aggregate instead would give 201.
        assert co["markup_cents"] == 202, (
            f"per-line rounding must yield 101 + 101 = 202, got {co['markup_cents']}"
        )
        assert co["total_with_markup_cents"] == 2212
        # Headroom = 50000000 - 40000000 = 10000000; cumulative 2212 is within it.
        assert co["tenant_overage_share_cents"] == 0

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["total_cost_cents"] == 40_002_212

    def test_markup_half_up_per_line_mixed_rounding_direction(self, api, landlord_pm_headers):
        """PRD 3.5: "each line's markup is ten percent of its `amount_cents`,
        rounded half up to a whole cent per line, and only then summed".

        Design: Difficulty/combinatorial_formula/change_order_markup_per_line_rounding
        """
        sc = setup_project_in_construction()
        set_logical_clock("2026-08-15T00:00:00Z")
        ctr_headers = make_contractor_headers(sc)

        co = create_approved_change_order(
            sc["project"]["id"],
            ctr_headers,
            lines=[
                {"description": "rounds down", "amount_cents": 1004},
                {"description": "rounds up", "amount_cents": 1006},
            ],
            approver_id="approver-2",
        )
        # 1004 * 0.10 = 100.40 -> 100; 1006 * 0.10 = 100.60 -> 101.
        assert co["total_cost_cents"] == 2010
        assert co["markup_cents"] == 201, (
            f"per-line half-up must yield 100 + 101 = 201, got {co['markup_cents']}"
        )
        assert co["total_with_markup_cents"] == 2211


class TestOverageShareSweep:
    def test_change_order_overage_share_circular_order(self, api, landlord_pm_headers):
        """PRD 3.5: "The headroom is the project's `allowance_total_cents`
        minus its `base_contract_cents`." PRD 3.5: "the new order's
        `tenant_overage_share_cents` is then the excess of the cumulative total
        including this order over the headroom (floored at zero) minus the
        excess of the cumulative total excluding this order over the headroom
        (likewise floored at zero)." PRD 3.5: "recomputes the project's
        `total_cost_cents` as `base_contract_cents` plus the
        `total_with_markup_cents` of every `APPROVED` change order, its
        `overage_cents` as the amount by which `total_cost_cents` exceeds
        `allowance_total_cents` (never below zero)".

        Design: Difficulty/combinatorial_formula/change_order_overage_share_circular_order
        """
        sc = setup_project_in_construction()
        set_logical_clock("2026-08-15T00:00:00Z")
        tenant_headers = make_tenant_rep_headers(sc["tenant"]["id"])

        co1 = create_approved_change_order(
            sc["project"]["id"],
            tenant_headers,
            lines=[{"description": "x", "amount_cents": 6_000_000}],
            approver_id="approver-2",
        )
        assert co1["total_with_markup_cents"] == 6_600_000
        # Cumulative 6600000 stays under the 10000000 headroom.
        assert co1["tenant_overage_share_cents"] == 0

        co2 = create_approved_change_order(
            sc["project"]["id"],
            tenant_headers,
            lines=[{"description": "y", "amount_cents": 5_000_000}],
            approver_id="approver-2",
        )
        assert co2["total_with_markup_cents"] == 5_500_000
        # max(0, 12100000 - 10000000) - max(0, 6600000 - 10000000) = 2100000.
        assert co2["tenant_overage_share_cents"] == 2_100_000, (
            f"the marginal excess over headroom is 2100000, got "
            f"{co2['tenant_overage_share_cents']}"
        )

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["total_cost_cents"] == 52_100_000
        assert project["overage_cents"] == 2_100_000

    def test_third_order_entirely_past_headroom_carries_full_share(
        self, api, landlord_pm_headers
    ):
        """PRD 3.5: "the new order's `tenant_overage_share_cents` is then the
        excess of the cumulative total including this order over the headroom
        (floored at zero) minus the excess of the cumulative total excluding
        this order over the headroom (likewise floored at zero)."

        Design: Difficulty/combinatorial_formula/change_order_overage_share_circular_order
        """
        sc = setup_project_in_construction()
        set_logical_clock("2026-08-15T00:00:00Z")
        tenant_headers = make_tenant_rep_headers(sc["tenant"]["id"])

        create_approved_change_order(
            sc["project"]["id"], tenant_headers,
            lines=[{"description": "x", "amount_cents": 6_000_000}], approver_id="approver-2",
        )
        create_approved_change_order(
            sc["project"]["id"], tenant_headers,
            lines=[{"description": "y", "amount_cents": 5_000_000}], approver_id="approver-2",
        )
        # Cumulative now 12100000, already 2100000 past the 10000000 headroom.
        co3 = create_approved_change_order(
            sc["project"]["id"],
            tenant_headers,
            lines=[{"description": "z", "amount_cents": 1_000_000}],
            approver_id="approver-2",
        )
        assert co3["total_with_markup_cents"] == 1_100_000
        # max(0, 13200000 - 10000000) - max(0, 12100000 - 10000000) = 1100000:
        # past headroom, the order's entire with-markup total is tenant share.
        assert co3["tenant_overage_share_cents"] == 1_100_000

        project = get_success_data(api.get_project(sc["project"]["id"], landlord_pm_headers))
        assert project["total_cost_cents"] == 53_200_000
        assert project["overage_cents"] == 3_200_000


class TestChangeOrderApprovalRbac:
    def test_tenant_cannot_approve_change_order_unauthorized(
        self, api, landlord_pm_headers, tenant_rep_headers
    ):
        """PRD 3.5: "Approval belongs to the `LandlordApprover` alone". PRD
        2.1: "A request whose role is not on the endpoint's authorized list is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/roles/tenant_cannot_approve_change_order_unauthorized
        """
        sc = setup_project_in_construction()
        set_logical_clock("2026-08-15T00:00:00Z")
        tenant_headers = make_tenant_rep_headers(sc["tenant"]["id"])
        co = create_submitted_change_order(
            sc["project"]["id"],
            tenant_headers,
            lines=[{"description": "x", "amount_cents": 100_000}],
        )
        assert co["status"] == "SUBMITTED"

        resp = api.approve_change_order(co["id"], tenant_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_change_order(co["id"], landlord_pm_headers))
        assert after["status"] == "SUBMITTED"


class TestOverageInvoicing:
    def _setup_with_approved_cos(self, api, landlord_pm_headers):
        """Project in CONSTRUCTION with CO-A approved within headroom
        (share 0) and CO-B approved beyond it (share 2100000)."""
        sc = setup_project_in_construction()
        set_logical_clock("2026-08-15T00:00:00Z")
        tenant_headers = make_tenant_rep_headers(sc["tenant"]["id"])
        co_a = create_approved_change_order(
            sc["project"]["id"], tenant_headers,
            lines=[{"description": "x", "amount_cents": 6_000_000}], approver_id="approver-2",
        )
        co_b = create_approved_change_order(
            sc["project"]["id"], tenant_headers,
            lines=[{"description": "y", "amount_cents": 5_000_000}], approver_id="approver-2",
        )
        assert co_a["tenant_overage_share_cents"] == 0
        assert co_b["tenant_overage_share_cents"] == 2_100_000
        return sc, tenant_headers, co_a, co_b

    def test_overage_invoice_aggregation_excludes_zero_share_cos(self, api, landlord_pm_headers):
        """PRD 3.8: "Drafting an invoice snapshots the outstanding share: the
        server sums `tenant_overage_share_cents` across the project's
        `APPROVED` change orders that carry a share above zero and have not yet
        been included in any invoice, and that sum becomes the invoice's
        `line_total_cents`, frozen at creation; the invoice takes the next
        `invoice_number` in the project and opens in `DRAFT` with `due_date`
        still null." PRD 3.5: "Change orders in `DRAFT`, `SUBMITTED`,
        `REJECTED`, or `VOIDED` never participate in the sweep."

        Design: Corner/calculations/overage_invoice_aggregation_excludes_zero_share_cos
        """
        sc, tenant_headers, co_a, co_b = self._setup_with_approved_cos(api, landlord_pm_headers)
        # A third order is rejected: excluded from every aggregate.
        co_c = create_submitted_change_order(
            sc["project"]["id"], tenant_headers,
            lines=[{"description": "z", "amount_cents": 7_000_000}],
        )
        co_c = get_success_data(
            api.reject_change_order(co_c["id"], make_landlord_approver_headers("approver-2"))
        )
        assert co_c["status"] == "REJECTED"

        invoice = validate_success(
            api.create_overage_invoice(sc["project"]["id"], landlord_pm_headers), 201
        )
        assert invoice["line_total_cents"] == 2_100_000, (
            f"only CO-B's positive share may be invoiced, got {invoice['line_total_cents']}"
        )
        assert invoice["invoice_number"] == 1
        assert invoice["status"] == "DRAFT"

    def test_invoice_creation_without_overage_rejected(self, api, landlord_pm_headers):
        """PRD 3.8: "When nothing qualifies — no uninvoiced approved order with
        a positive share — the draft is refused with
        `ERR_NO_OVERAGE_OUTSTANDING` (HTTP 422)."

        Design: Corner/validations/invoice_creation_without_overage_rejected
        """
        sc = setup_project_in_construction()
        set_logical_clock("2026-08-15T00:00:00Z")
        tenant_headers = make_tenant_rep_headers(sc["tenant"]["id"])
        co = create_approved_change_order(
            sc["project"]["id"], tenant_headers,
            lines=[{"description": "x", "amount_cents": 100_000}], approver_id="approver-2",
        )
        assert co["tenant_overage_share_cents"] == 0  # within the headroom

        resp = api.create_overage_invoice(sc["project"]["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_NO_OVERAGE_OUTSTANDING)

    def test_change_order_void_after_invoice_issued_rejected(self, api, landlord_pm_headers):
        """PRD 3.5: "The void is refused with `ERR_INVOICE_ALREADY_ISSUED`
        (HTTP 422) once any `ISSUED` or `PAID` overage invoice of the project
        already includes the order."

        Design: Corner/validations/change_order_void_after_invoice_issued_rejected
        """
        sc, tenant_headers, co_a, co_b = self._setup_with_approved_cos(api, landlord_pm_headers)
        invoice = get_success_data(api.create_overage_invoice(sc["project"]["id"], landlord_pm_headers))
        invoice = get_success_data(api.issue_invoice(invoice["id"], landlord_pm_headers))
        assert invoice["status"] == "ISSUED"

        resp = api.void_change_order(co_b["id"], make_landlord_approver_headers("approver-2"))
        validate_error(resp, ApiErrorId.ERR_INVOICE_ALREADY_ISSUED)
        after = get_success_data(api.get_change_order(co_b["id"], landlord_pm_headers))
        assert after["status"] == "APPROVED"

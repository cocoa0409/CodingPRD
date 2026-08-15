"""Loss event reporting and pro-rata allocation with pinned rounding (PRD §3.7)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_pool_with_funded_cert, setup_loss_rounding_pool,
    make_originator_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]


class TestLossAllocationResidualRounding:
    def _report_and_allocate(self, api, ctx):
        originator = ctx["originator"]
        offering = ctx["offering"]
        loss = validate_success(api.create_loss_event(
            {"offering_id": offering["id"], "loss_amount_cents": 100,
             "defaulted_at": "2026-08-10T00:00:00Z"},
            make_originator_headers(originator["id"])), 201)
        allocated = validate_success(
            api.allocate_loss_event(loss["id"], make_originator_headers(originator["id"])),
            200)
        return allocated

    def test_residual_cent_goes_to_earliest_created_certificate(self, api):
        """PRD §3.7: "Each certificate's raw share is the loss amount multiplied by its weight and divided by the total weight; each share is then rounded half up to whole cents individually — the server does not sum first and round later."
        PRD §3.7: "If the rounded shares do not sum exactly to the loss amount, the residual is distributed one cent at a time, in the residual's sign, to certificates ordered by the fractional part of their raw share from largest to smallest, breaking ties by certificate `created_at` ascending — never by identifier."

        Design: Difficulty/combinatorial_formula/loss_allocation_residual_rounding
        """
        ctx = setup_loss_rounding_pool()
        certs = ctx["certificates"]
        allocated = self._report_and_allocate(api, ctx)
        assert allocated["status"] == "ALLOCATED"
        assert allocated["loss_basis_used"] == "OUTSTANDING"

        allocs = {a["certificate_id"]: a["allocated_cents"] for a in allocated["allocations"]}
        assert len(allocs) == 3
        assert sum(allocs.values()) == 100
        # Loss 100 over three equal 300-cent weights: raw 33.33 each rounds to 33,
        # residual +1 goes to the certificate with the earliest created_at.
        assert allocs[certs[0]["id"]] == 34
        assert allocs[certs[1]["id"]] == 33
        assert allocs[certs[2]["id"]] == 33

    def test_certificate_balances_reduced_by_allocated_amounts(self, api):
        """PRD §3.7: "Each affected certificate's `outstanding_principal_cents` is reduced by its allocated amount and its `cumulative_loss_cents` grows by the same amount."

        Design: Difficulty/combinatorial_formula/loss_allocation_residual_rounding
        """
        ctx = setup_loss_rounding_pool()
        certs = ctx["certificates"]
        self._report_and_allocate(api, ctx)

        c1 = validate_success(api.get_commitment(certs[0]["id"], ADMIN), 200)
        assert c1["outstanding_principal_cents"] == 266
        assert c1["cumulative_loss_cents"] == 34
        c2 = validate_success(api.get_commitment(certs[1]["id"], ADMIN), 200)
        assert c2["outstanding_principal_cents"] == 267
        assert c2["cumulative_loss_cents"] == 33
        c3 = validate_success(api.get_commitment(certs[2]["id"], ADMIN), 200)
        assert c3["outstanding_principal_cents"] == 267
        assert c3["cumulative_loss_cents"] == 33


class TestLossExceedsPool:
    def test_loss_exceeds_pool_rejected(self, api):
        """PRD §3.7: "Allocation by the `OriginatorUser` moves the event from `REPORTED` to `ALLOCATED`. Allocation requires at least one certificate of the offering in `ACTIVE` or `EXCEPTION` — otherwise it is rejected with `ERR_NO_ALLOCATABLE_CERTIFICATES` — and the `loss_amount_cents` must not exceed the total basis weight of those eligible certificates, else `ERR_LOSS_EXCEEDS_POOL`."

        Design: Corner/validations/loss_exceeds_pool_rejected
        """
        ctx = setup_pool_with_funded_cert()
        originator = ctx["originator"]
        # Single ACTIVE certificate with outstanding 10,000,000; loss 10,000,001 exceeds it.
        loss = validate_success(api.create_loss_event(
            {"offering_id": ctx["offering"]["id"], "loss_amount_cents": 10_000_001,
             "defaulted_at": "2026-08-10T00:00:00Z"},
            make_originator_headers(originator["id"])), 201)
        res = api.allocate_loss_event(loss["id"], make_originator_headers(originator["id"]))
        validate_error(res, ApiErrorId.ERR_LOSS_EXCEEDS_POOL)

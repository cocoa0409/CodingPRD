"""Compensating-action invariants and optimistic concurrency control.

Difficulty queue: compensating_invariant.
Corner queue: cross_cutting (OCC stale quote, version increments).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    fixtures as fx, factories as f,
    make_customer_headers,
)
from test_helpers.fixtures import (
    DESIGNER, ADMIN, MELAMINE_18_UNITS, WOOD_40_UNITS, PREMIUM_WOOD_40_UNITS,
)


# ===========================================================================
# Rule 9 — compensating-action invariants
# ===========================================================================
class TestCompensatingInvariants:
    def test_deposit_capture_then_refund_restores_balance(self, api):
        """PRD §3.5: "A captured deposit may later be refunded by a `PlatformAdmin`,
        permitted only while the deposit is `CAPTURED` and the project is `DEPOSIT_PAID`;
        refund moves the deposit to `REFUNDED`, recomputes the project's
        `balance_due_cents` (restoring the balance to its pre-deposit value), and
        increments the deposit's and the project's `version`."

        Design: Difficulty/compensating_invariant/deposit_capture_then_refund_restores_balance_due
        """
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        proj, quote = ctx["project"], ctx["quote"]
        dep = fx.create_deposit(proj["id"], quote["id"], 17820)
        fx.capture_deposit(dep["id"], quote["version"])
        refunded = get_success_data(api.refund_deposit(dep["id"], ADMIN))
        assert refunded["status"] == "REFUNDED"
        proj_after = get_success_data(api.get_project(proj["id"], DESIGNER))
        # accepted_total 71280 - 0 captured - 0 financed = 71280 (restored).
        assert proj_after["balance_due_cents"] == 71280

    def test_refunded_deposit_drops_out_of_captured_sum(self, api):
        """PRD §3.8: "The balance is the project's accepted-quote total (taken from the
        quote referenced by `accepted_quote_id`, or zero if none is set yet) minus the sum
        of the `amount_cents` of every deposit of the project whose status is `CAPTURED`,
        minus the financed amount."

        Design: Difficulty/compensating_invariant/deposit_capture_then_refund_restores_balance_due
        """
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        proj, quote = ctx["project"], ctx["quote"]
        dep = fx.create_deposit(proj["id"], quote["id"], 17820)
        fx.capture_deposit(dep["id"], quote["version"])
        # Balance reflects the captured deposit: 71280 - 17820 = 53460.
        mid = validate_success(api.get_project_balance(proj["id"], ADMIN))
        assert mid["balance_due_cents"] == 53460
        # After refund the deposit is no longer CAPTURED, so it drops from the sum.
        refunded = get_success_data(api.refund_deposit(dep["id"], ADMIN))
        assert refunded["status"] == "REFUNDED"
        after = validate_success(api.get_project_balance(proj["id"], ADMIN))
        assert after["balance_due_cents"] == 71280

    def test_change_order_apply_conserves_single_accepted_quote(self, api):
        """PRD §3.7: "the system creates a new `ACCEPTED` quote priced from the revised
        configuration, drives the base quote from `ACCEPTED` to `SUPERSEDED`, drives the
        prior `FINALIZED` configuration to `SUPERSEDED`, and sets the project's
        `accepted_quote_id` to the new quote's id."

        Design: Difficulty/compensating_invariant/change_order_apply_conserves_accepted_quote_singleton
        """
        proj, quote_a, co = self._setup_approved_config_revision(api)
        proj_state = get_success_data(api.get_project(proj["id"], DESIGNER))
        applied = get_success_data(
            api.apply_change_order(co["id"], {"expected_project_version": proj_state["version"]}, DESIGNER)
        )
        assert applied["status"] == "APPLIED"
        base_after = get_success_data(api.get_quote(quote_a["id"], DESIGNER))
        assert base_after["status"] == "SUPERSEDED"
        # exactly one ACCEPTED quote remains for the project.
        all_quotes = get_success_data(api.list_quotes(DESIGNER, params={"project_id": proj["id"]}))
        all_quotes = all_quotes["data"] if isinstance(all_quotes, dict) and "data" in all_quotes else all_quotes
        accepted = [q for q in all_quotes if q["status"] == "ACCEPTED"]
        assert len(accepted) == 1, f"exactly one ACCEPTED quote, got {len(accepted)}"
        proj_after = get_success_data(api.get_project(proj["id"], DESIGNER))
        assert proj_after["accepted_quote_id"] == accepted[0]["id"]
        assert proj_after["accepted_quote_id"] != quote_a["id"]

    def test_change_order_apply_stale_project_version_rejected(self, api):
        """PRD §2.8: "Applying an approved change order requires an
        `expected_project_version` field in the request body carrying the client's last
        observed `version` of the target `Project`. If that value does not equal the
        project's current `version`, the apply is rejected with
        `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        Design: Difficulty/compensating_invariant/change_order_apply_conserves_accepted_quote_singleton
        """
        proj, quote_a, co = self._setup_approved_config_revision(api)
        proj_state = get_success_data(api.get_project(proj["id"], DESIGNER))
        resp = api.apply_change_order(
            co["id"], {"expected_project_version": proj_state["version"] - 1}, DESIGNER
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value)

    @staticmethod
    def _setup_approved_config_revision(api):
        """Project DEPOSIT_PAID with QA ACCEPTED (WOOD 40u) + an APPROVED CONFIG_REVISION
        change order pointing at a PREMIUM_WOOD 40u revised config."""
        ctx = fx.setup_accepted_quote(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="WOOD", line_items=WOOD_40_UNITS,
        )
        proj, quote_a = ctx["project"], ctx["quote"]
        dep = fx.create_deposit(proj["id"], quote_a["id"], 141379)
        fx.capture_deposit(dep["id"], quote_a["version"])
        cfg_c, _ = fx.add_finalized_config(
            proj["id"], material_grade="PREMIUM_WOOD", line_items=PREMIUM_WOOD_40_UNITS,
        )
        co = fx.submit_change_order(proj["id"], quote_a["id"], "CONFIG_REVISION",
                                    revised_config_id=cfg_c["id"])
        co = fx.approve_change_order(co["id"])
        return proj, quote_a, co


# ===========================================================================
# Corner — optimistic concurrency
# ===========================================================================
class TestOptimisticConcurrency:
    def test_deposit_capture_stale_quote_version_rejected(self, api):
        """PRD §2.8: "Capturing a deposit requires an `expected_quote_version` field in
        the request body carrying the client's last observed `version` of the `Quote`
        being deposited against. If that value does not equal the quote's current
        `version`, the capture is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_quote_version_on_deposit_capture
        """
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        proj, quote = ctx["project"], ctx["quote"]
        dep = fx.create_deposit(proj["id"], quote["id"], 17820)
        resp = api.capture_deposit(dep["id"], {"expected_quote_version": quote["version"] - 1}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_QUOTE_VERSION.value)

    def test_project_version_increments_per_mutation(self, api):
        """PRD §2.4: "The `version` begins at its initial value when the resource is
        created and increments by one on every mutation of that resource, including
        mutations driven indirectly by a cascade rather than by a direct client request."
        PRD §3.2: "If the project was still `LEAD`, creating this first consult advances
        the project to `DESIGNING` and increments the project's `version`."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
        """
        customer = fx.create_customer(zip_code="90001")
        project = fx.create_project(customer["id"], room_type="WALK_IN_CLOSET")
        assert project["version"] == 1
        fx.add_design_consult(project["id"])
        proj = get_success_data(api.get_project(project["id"], DESIGNER))
        assert proj["version"] == 2

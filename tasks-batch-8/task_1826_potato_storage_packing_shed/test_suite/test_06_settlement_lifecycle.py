"""Settlement lifecycle: OCC create, supersede, season conflict, finalize gates,
dispute cycle with segregation of duties, and payment (PRD §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    setup_grower_shed_bin_lot, setup_grower_with_closed_lot,
    create_grower, create_settlement, refresh_grower, refresh_settlement,
    hold_and_condemn_lot, refresh_lot,
    TEST_USERS, make_grower_headers, make_clerk_headers,
)

ADMIN = TEST_USERS["admin_headers"]
CLERK = TEST_USERS["clerk_headers"]
STORAGE = TEST_USERS["storage_headers"]
QA = TEST_USERS["qa_headers"]


class TestFinalizeGate:
    def test_finalize_blocked_until_all_lots_closed(self, api):
        """PRD §3.9: "Finalization moves the settlement from `PROVISIONAL` to `FINALIZED`. It is refused when the settlement is in any other state (`ERR_SETTLEMENT_INVALID_STATE`) and refused while any of the grower's lots is not yet `CLOSED` (`ERR_SETTLEMENT_LOTS_NOT_CLOSED`)."

        Design: Difficulty/cross_entity_state_dependency/settlement_finalize_requires_all_lots_closed
        """
        from test_helpers import set_clock
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Fourteen", grower_code="G-14", shed_name="Shed N",
            lot_weight_cwt=100.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        st = create_settlement(ctx["grower"]["id"], ctx["grower"]["version"])

        resp = api.finalize_settlement(st["id"], make_clerk_headers("clerk_one"))
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_LOTS_NOT_CLOSED)

    def test_finalize_succeeds_after_lot_closes(self, api):
        """PRD §3.9: "Finalization moves the settlement from `PROVISIONAL` to `FINALIZED`. It is refused when the settlement is in any other state (`ERR_SETTLEMENT_INVALID_STATE`) and refused while any of the grower's lots is not yet `CLOSED` (`ERR_SETTLEMENT_LOTS_NOT_CLOSED`). On success the final variant is computed, the acting clerk's `X-User-ID` is recorded as `finalized_by_clerk_id`, and the settlement's `version` bumps."

        Design: Difficulty/cross_entity_state_dependency/settlement_finalize_requires_all_lots_closed
        """
        from test_helpers import set_clock
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Fourteen", grower_code="G-14", shed_name="Shed N",
            lot_weight_cwt=100.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        st = create_settlement(ctx["grower"]["id"], ctx["grower"]["version"])

        resp = api.finalize_settlement(st["id"], make_clerk_headers("clerk_one"))
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_LOTS_NOT_CLOSED)

        # Condemn the BINNED lot, which auto-closes it at zero available.
        hold_and_condemn_lot(ctx["lot"]["id"], "WASTE")

        resp = api.finalize_settlement(st["id"], make_clerk_headers("clerk_one"))
        fin = validate_success(resp, expected_status=200)
        assert fin["status"] == "FINALIZED"
        assert abs(fin["packed_cwt_basis"] - 0.00) <= 0.005
        # binned_at and closed_at both at 2026-08-02: 0 whole storage weeks.
        assert abs(fin["storage_fees_cents"] - 0.00) <= 0.005


class TestDisputeRefinalizeCycle:
    @staticmethod
    def _setup_finalized_settlement():
        ctx = setup_grower_with_closed_lot(lot_weight_cwt=100.00,
                                           close_at="2026-08-02T00:00:00Z",
                                           bin_at="2026-08-02T00:00:00Z")
        grower = ctx["grower"]
        st = create_settlement(grower["id"], grower["version"])
        resp = api_finalize(st["id"], "clerk_one")
        validate_success(resp, expected_status=200)
        return {**ctx, "settlement_id": st["id"]}

    def test_dispute_refinalize_pay_cycle(self, api):
        """PRD §3.9: "The grower may dispute a `FINALIZED` settlement — and only their own... A successful dispute moves the settlement to `DISPUTED`."
        PRD §3.9: "Re-finalizing a `DISPUTED` settlement repeats the final computation... A successful re-finalize overwrites `finalized_by_clerk_id` with the new clerk's id."
        PRD §3.9: "Payment closes the loop: a `SettlementClerk` pays a `FINALIZED` settlement, which transitions it to `PAID` and stamps `paid_at` from the logical clock."

        Design: Corner/state_machines/c_settlement_dispute_refinalize_cycle
        """
        ctx = self._setup_finalized_settlement()
        st_id = ctx["settlement_id"]
        grower_id = ctx["grower"]["id"]

        d = validate_success(
            api.dispute_settlement(st_id, {"reason": "packout dispute"},
                                   make_grower_headers(grower_id)),
            expected_status=200,
        )
        assert d["status"] == "DISPUTED"

        f = validate_success(api_finalize(st_id, "clerk_two"), expected_status=200)
        assert f["status"] == "FINALIZED"
        assert f["finalized_by_clerk_id"] == "clerk_two"  # clerk hand-off recorded

        p = validate_success(api.pay_settlement(st_id, CLERK), expected_status=200)
        assert p["status"] == "PAID"

        # Throughout the cycle the money is zero (100.00 condemned, 0 packed, 0 weeks).
        assert abs(p["net_payable_cents"] - 0.00) <= 0.005

    def test_dispute_paid_settlement_rejected(self, api):
        """PRD §3.9: "A dispute against a settlement in any other state is `ERR_SETTLEMENT_INVALID_STATE`."

        Design: Corner/state_machines/c_settlement_dispute_refinalize_cycle
        """
        ctx = self._setup_finalized_settlement()
        st_id = ctx["settlement_id"]
        grower_id = ctx["grower"]["id"]
        api.pay_settlement(st_id, CLERK)

        resp = api.dispute_settlement(st_id, {"reason": "too late"},
                                      make_grower_headers(grower_id))
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_INVALID_STATE)

    def test_same_clerk_refinalize_rejected(self, api):
        """PRD §3.9: "the clerk performing the re-finalize must not be the clerk recorded in `finalized_by_clerk_id`; the same clerk id is rejected with `ERR_SOD_REFINALIZE_CLERK` (HTTP 403)."

        Design: Corner/rbac/c_rbac_sod_same_clerk_refinalize_returns_403
        """
        ctx = self._setup_finalized_settlement()
        st_id = ctx["settlement_id"]
        grower_id = ctx["grower"]["id"]
        api.dispute_settlement(st_id, {"reason": "shrink dispute"},
                               make_grower_headers(grower_id))

        resp = api_finalize(st_id, "clerk_one")  # same clerk who finalized
        validate_error(resp, ApiErrorId.ERR_SOD_REFINALIZE_CLERK)
        st = refresh_settlement(st_id)
        assert st["status"] == "DISPUTED"

        f = validate_success(api_finalize(st_id, "clerk_two"), expected_status=200)
        assert f["status"] == "FINALIZED"
        assert f["finalized_by_clerk_id"] == "clerk_two"

    def test_grower_cannot_dispute_other_growers_settlement(self, api):
        """PRD §2.1: "A `Grower` calling for their own settlements or disputing one is therefore checked against the settlement's `grower_id`, and a request that names another grower's settlement is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §3.9: "The grower may dispute a `FINALIZED` settlement — and only their own: the grower ownership rule requires the acting `X-User-ID` to equal the settlement's `grower_id`, and a mismatch is `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/c_rbac_grower_dispute_other_grower_returns_403
        """
        ctx = self._setup_finalized_settlement()
        interloper = create_grower("Grower AR", "G-AR")

        resp = api.dispute_settlement(ctx["settlement_id"], {"reason": "not mine"},
                                      make_grower_headers(interloper["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        st = refresh_settlement(ctx["settlement_id"])
        assert st["status"] == "FINALIZED"


class TestPayGate:
    def test_pay_from_provisional_rejected(self, api):
        """PRD §3.9: "Payment closes the loop: a `SettlementClerk` pays a `FINALIZED` settlement, which transitions it to `PAID` and stamps `paid_at` from the logical clock. Payment from any other state is `ERR_SETTLEMENT_INVALID_STATE`."

        Design: Corner/state_machines/c_settlement_pay_from_provisional_returns_409
        """
        grower = create_grower("Grower L", "G-L")
        st = create_settlement(grower["id"], grower["version"])

        resp = api.pay_settlement(st["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_INVALID_STATE)
        st = refresh_settlement(st["id"])
        assert st["status"] == "PROVISIONAL"
        assert st["paid_at"] is None


class TestSeasonConflict:
    def test_finalized_settlement_blocks_same_season_create(self, api):
        """PRD §3.9: "The `season_label` must be unique per grower among settlements that are not `SUPERSEDED` — a `FINALIZED`, `DISPUTED`, or `PAID` settlement already on the books for the same season rejects the create with `ERR_SETTLEMENT_SEASON_CONFLICT`."

        Design: Corner/validations/c_settlement_season_conflict_returns_409
        """
        ctx = setup_grower_with_closed_lot(lot_weight_cwt=100.00,
                                           close_at="2026-08-02T00:00:00Z",
                                           bin_at="2026-08-02T00:00:00Z")
        grower = ctx["grower"]
        st = create_settlement(grower["id"], grower["version"])
        validate_success(api_finalize(st["id"], "clerk_one"), expected_status=200)

        grower = refresh_grower(grower["id"])
        resp = api.create_settlement(
            grower["id"],
            {"season_label": "2026-storage", "expected_grower_version": grower["version"]},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_SEASON_CONFLICT)

        settlements, _ = validate_paginated(api.list_settlements(grower["id"], CLERK))
        assert len(settlements) == 1


def api_finalize(settlement_id, clerk_id):
    from test_helpers import api_client
    return api_client.finalize_settlement(settlement_id, make_clerk_headers(clerk_id))

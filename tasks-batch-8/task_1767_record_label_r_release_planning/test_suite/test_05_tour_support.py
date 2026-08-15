"""Tour support lifecycle: approval, segregation of duties, expense caps, reconcile."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_tour_expense,
    create_artist,
    create_label,
    get_recoupment_account,
    get_success_data,
    setup_advanced_tour_support,
    setup_approved_tour_support,
    sign_artist_via_memo,
    submit_tour_expense,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_tour_expense_payload, create_tour_support_payload
from test_helpers.fixtures import ADMIN, ANR, FIN
from test_helpers.test_users import make_finance_headers, make_label_admin_headers


# ===========================================================================
# Queue A — compensating_invariant/expense_approve_void_conserves_recoupment
# ===========================================================================


class TestExpenseApproveVoidConservation:
    def test_approve_then_void_restores_bucket(self):
        """PRD §3.7: "Voiding is the compensating move: a `FinanceController` may
        void an `APPROVED` expense while the tour support is anything but `CLOSED`
        ... subtracting the amount from `tour_support_balance_cents` and from
        `approved_expense_total_cents` and recomputing `total_unrecouped_cents`."

        Design: Difficulty/compensating_invariant/expense_approve_void_conserves_recoupment
        """
        label = create_label("Label I1")
        artist = create_artist(label["id"], "Artist I1")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0,
                                              recoupment_scope="CROSS_COLLATERALIZED")
        ts = setup_advanced_tour_support(
            contract["id"], artist["id"], tour_name="Tour I1",
            requested_amount_cents=24_000, approved_budget_cents=24_000,
            advance_amount_cents=12_000)
        exp = submit_tour_expense(ts["id"], artist["id"], category="TRAVEL",
                                  amount_cents=12_000, expense_date="2026-09-15")

        base = get_recoupment_account(contract["id"])
        assert base["tour_support_balance_cents"] == 0
        assert base["total_unrecouped_cents"] == 0

        approved = approve_tour_expense(exp["id"])
        assert approved["status"] == "APPROVED"
        after_approve = get_recoupment_account(contract["id"])
        assert after_approve["tour_support_balance_cents"] == 12_000
        assert after_approve["total_unrecouped_cents"] == 12_000

        voided = get_success_data(api_client.void_tour_expense(exp["id"], FIN))
        assert voided["status"] == "VOIDED"
        after_void = get_recoupment_account(contract["id"])
        assert after_void["tour_support_balance_cents"] == 0
        assert after_void["total_unrecouped_cents"] == 0

        ts_after = get_success_data(api_client.get_tour_support(ts["id"], FIN))
        assert ts_after["approved_expense_total_cents"] == 0

    def test_approve_void_no_drift_on_total_unrecouped(self):
        """PRD §2.7: "Their sum is exposed as `total_unrecouped_cents`, recomputed
        whenever any bucket moves."
        PRD §3.7: "Approval adds the amount to the recoupment account's
        `tour_support_balance_cents`, adds it to the support's
        `approved_expense_total_cents`, and recomputes `total_unrecouped_cents`."

        Design: Difficulty/compensating_invariant/expense_approve_void_conserves_recoupment
        """
        label = create_label("Label I1b")
        artist = create_artist(label["id"], "Artist I1b")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0,
                                              recoupment_scope="CROSS_COLLATERALIZED")
        ts = setup_advanced_tour_support(
            contract["id"], artist["id"], tour_name="Tour I1b",
            requested_amount_cents=24_000, approved_budget_cents=24_000,
            advance_amount_cents=12_000)
        exp = submit_tour_expense(ts["id"], artist["id"], category="TRAVEL",
                                  amount_cents=12_000, expense_date="2026-09-15")
        before = get_recoupment_account(contract["id"])["total_unrecouped_cents"]
        approve_tour_expense(exp["id"])
        get_success_data(api_client.void_tour_expense(exp["id"], FIN))
        after = get_recoupment_account(contract["id"])["total_unrecouped_cents"]
        assert after == before


# ===========================================================================
# Queue B — tour support validations and reconcile
# ===========================================================================


class TestApprovedExceedsRequested:
    def test_approve_over_request_rejected(self):
        """PRD §3.7: "Approval moves the proposal to `APPROVED`, setting
        `approved_budget_cents` from the supplied input — which must not exceed
        `requested_amount_cents`, otherwise `ERR_APPROVED_EXCEEDS_REQUESTED`".

        Design: Corner/validations/approved_exceeds_requested_rejected
        """
        label = create_label("Label Vb8")
        artist = create_artist(label["id"], "Artist Vb8")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        ts = get_success_data(api_client.create_tour_support(
            contract["id"], create_tour_support_payload(
                tour_name="Tour Vb8", requested_amount_cents=24_000), ANR))
        r = api_client.approve_tour_support(ts["id"], {"approved_budget_cents": 30_000}, ADMIN)
        validate_error(r, ApiErrorId.ERR_APPROVED_EXCEEDS_REQUESTED)
        after = get_success_data(api_client.get_tour_support(ts["id"], FIN))
        assert after["status"] == "PROPOSED"


class TestCategoryCap:
    def test_lodging_cap_breach_rejected(self):
        """PRD §3.7: "first the category cap — the sum of `APPROVED` expense amounts
        in the same category plus this `amount_cents` must not exceed the category's
        cap, computed as the label's `tour_category_caps_bps` share for that
        category multiplied by `approved_budget_cents` and divided by 10,000 with
        integer division discarding any fraction (by default 50 percent for travel,
        30 for lodging, 40 for production, 10 for miscellaneous), with equality
        allowed and violations rejected as `ERR_CATEGORY_CAP_EXCEEDED`".

        Design: Corner/validations/category_cap_exceeded_rejected
        """
        label = create_label("Label Vb9")
        artist = create_artist(label["id"], "Artist Vb9")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0,
                                              recoupment_scope="CROSS_COLLATERALIZED")
        ts = setup_advanced_tour_support(
            contract["id"], artist["id"], tour_name="Tour Vb9",
            requested_amount_cents=24_000, approved_budget_cents=24_000,
            advance_amount_cents=24_000)
        # LODGING cap = floor(3000 * 24000 / 10000) = 7200. Approving 8000 breaches.
        exp = submit_tour_expense(ts["id"], artist["id"], category="LODGING",
                                  amount_cents=8_000, expense_date="2026-09-10")
        r = api_client.approve_tour_expense(exp["id"], FIN)
        validate_error(r, ApiErrorId.ERR_CATEGORY_CAP_EXCEEDED)
        after = get_success_data(api_client.get_tour_expense(exp["id"], FIN))
        assert after["status"] == "SUBMITTED"
        account = get_recoupment_account(contract["id"])
        assert account["tour_support_balance_cents"] == 0


class TestTourBudgetExceeded:
    def test_aggregate_cap_breach_rejected(self):
        """PRD §3.7: "then the total cap — `approved_expense_total_cents` plus this
        `amount_cents` must not exceed `approved_budget_cents`, equality allowed,
        otherwise `ERR_TOUR_BUDGET_EXCEEDED`."

        Design: Corner/validations/tour_budget_exceeded_rejected
        """
        label = create_label("Label Vb10")
        artist = create_artist(label["id"], "Artist Vb10")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0,
                                              recoupment_scope="CROSS_COLLATERALIZED")
        ts = setup_advanced_tour_support(
            contract["id"], artist["id"], tour_name="Tour Vb10",
            requested_amount_cents=24_000, approved_budget_cents=24_000,
            advance_amount_cents=24_000)
        # Three category-legal approvals totalling 21_400.
        e1 = submit_tour_expense(ts["id"], artist["id"], category="TRAVEL",
                                 amount_cents=12_000, expense_date="2026-09-10")
        approve_tour_expense(e1["id"])
        e2 = submit_tour_expense(ts["id"], artist["id"], category="LODGING",
                                 amount_cents=7_000, expense_date="2026-09-11")
        approve_tour_expense(e2["id"])
        e3 = submit_tour_expense(ts["id"], artist["id"], category="MISC",
                                 amount_cents=2_400, expense_date="2026-09-12")
        approve_tour_expense(e3["id"])
        # Fourth: PRODUCTION 3000 is within category cap 9600 but pushes total past 24000.
        e4 = submit_tour_expense(ts["id"], artist["id"], category="PRODUCTION",
                                 amount_cents=3_000, expense_date="2026-09-13")
        r = api_client.approve_tour_expense(e4["id"], FIN)
        validate_error(r, ApiErrorId.ERR_TOUR_BUDGET_EXCEEDED)
        ts_after = get_success_data(api_client.get_tour_support(ts["id"], FIN))
        assert ts_after["approved_expense_total_cents"] == 21_400


class TestSegregationOfDuties:
    def test_same_user_cannot_advance(self):
        """PRD §3.7: "the caller's `X-User-ID` must differ from the
        `approved_by_user_id` recorded at approval — the same operator may not both
        approve and fund, and a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_rejected
        """
        label = create_label("Label Vb11")
        artist = create_artist(label["id"], "Artist Vb11")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        ts = get_success_data(api_client.create_tour_support(
            contract["id"], create_tour_support_payload(
                tour_name="Tour Vb11", requested_amount_cents=24_000), ANR))
        # Approved by LabelAdmin user admin-77.
        get_success_data(api_client.approve_tour_support(
            ts["id"], {"approved_budget_cents": 24_000},
            make_label_admin_headers("admin-77")))
        # Same user id (but FinanceController role) tries to fund — rejected.
        r = api_client.advance_funds_tour_support(
            ts["id"], {"amount_cents": 12_000}, make_finance_headers("admin-77"))
        validate_error(r, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_success_data(api_client.get_tour_support(ts["id"], FIN))
        assert after["status"] == "APPROVED"
        # A different finance user succeeds.
        funded = get_success_data(api_client.advance_funds_tour_support(
            ts["id"], {"amount_cents": 12_000}, make_finance_headers("fin-1")))
        assert funded["status"] == "ADVANCED"
        assert funded["advanced_amount_cents"] == 12_000


class TestTourReconcile:
    def test_unspent_returned(self):
        """PRD §3.7: "A `FinanceController` reconciles an `ADVANCED` support,
        computing `unspent_returned_cents` as the larger of zero and
        `advanced_amount_cents` minus `approved_expense_total_cents`, and the
        support moves to `RECONCILED`. Neither advancing nor reconciling ever
        touches the recoupment bucket — it moves only on expense approval and
        void."

        Design: Corner/calculations/tour_reconcile_unspent_returned
        """
        label = create_label("Label C4")
        artist = create_artist(label["id"], "Artist C4")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0,
                                              recoupment_scope="CROSS_COLLATERALIZED")
        ts = setup_advanced_tour_support(
            contract["id"], artist["id"], tour_name="Tour C4",
            requested_amount_cents=24_000, approved_budget_cents=24_000,
            advance_amount_cents=12_000)
        exp = submit_tour_expense(ts["id"], artist["id"], category="LODGING",
                                  amount_cents=5_000, expense_date="2026-09-10")
        approve_tour_expense(exp["id"])
        done = get_success_data(api_client.reconcile_tour_support(ts["id"], FIN))
        assert done["status"] == "RECONCILED"
        assert done["unspent_returned_cents"] == 7_000
        account = get_recoupment_account(contract["id"])
        # The bucket was moved only by the approve step (+=5000), not by reconcile.
        assert account["tour_support_balance_cents"] == 5_000

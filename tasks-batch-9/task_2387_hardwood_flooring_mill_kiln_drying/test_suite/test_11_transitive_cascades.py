"""Two three-deep cascades, each set off by a request that never names the
entities it ends up changing."""

import pytest

from test_helpers import (
    adjudicate_claim_payload,
    record_stress_test_payload,
    setup_claim_with_scheduled_prefinish_run,
    setup_two_charges_on_one_chamber,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    OPERATOR,
    SCHEDULER,
    refetch_charge,
    refetch_prefinish_run,
    refetch_product_line,
    refetch_receipt,
)
from test_helpers.test_users import (
    CLAIM_ADJUDICATOR_USER_ID,
    make_warranty_adjudicator_headers,
)

# Charge B starts one hour after charge A's original block expires, so it is
# legal on creation and only the redry extension can reach it.
DOWNSTREAM_START_UTC = "2026-08-16T08:00:00.000Z"
DOWNSTREAM_RECEIPT = {
    "supplier_name": "Cedar Hollow Timber",
    "received_board_feet": 2200,
    "accepted_board_feet": 2000,
    "moisture_pct_at_receipt": 45.0,
    "receipt_grade": "NO1_COMMON",
}


def _displacement_setup(api):
    return setup_two_charges_on_one_chamber(
        api,
        second_start_utc=DOWNSTREAM_START_UTC,
        second_receipt=dict(DOWNSTREAM_RECEIPT),
    )


class TestRedryExtensionCascade:
    """A window extension re-evaluates the chamber's calendar, and every charge
    it dislodges gives its wood back."""

    def test_extension_displaces_the_downstream_charge_it_never_names(self, api):
        """PRD 3.5: "Because the charge now holds its chamber longer, the
        extension is allowed to displace others: every `SCHEDULED` charge on the
        same chamber whose occupancy interval now overlaps the extended interval
        moves to `DISPLACED` with a `displaced_reason` recorded, and each
        displaced charge gives its wood back — every `ALLOCATED` receipt on it
        returns to `ACCEPTED` with a cleared `kiln_charge_id`, and the displaced
        charge's `charged_green_bf` becomes 0 with a null
        `weighted_initial_moisture_pct`."

        PRD 2.9: "Concretely, a candidate charge conflicts with an existing charge
        on the same chamber when the candidate's `planned_start_utc` is at or
        before the existing charge's `blocked_until_utc` and the candidate's
        `blocked_until_utc` is at or after the existing charge's
        `planned_start_utc`."

        Design: Difficulty/transitive_cascade/redry_extension_displaces_downstream_charge_and_frees_its_receipts
        """
        ctx = _displacement_setup(api)
        assert ctx["charge_b"]["status"] == "SCHEDULED"
        assert ctx["charge_b"]["blocked_until_utc"] == "2026-08-27T15:00:00.000Z"

        charge_a = validate_success(
            api.record_stress_test(
                ctx["charge"]["id"], record_stress_test_payload(5.9, 8.0), OPERATOR
            ),
            expected_status=200,
        )
        assert charge_a["status"] == "REDRY"
        assert charge_a["redry_count"] == 1
        assert charge_a["planned_end_utc"] == "2026-08-18T01:00:00.000Z"
        assert charge_a["blocked_until_utc"] == "2026-08-18T07:00:00.000Z"

        charge_b = refetch_charge(api, ctx["charge_b"]["id"])
        assert charge_b["status"] == "DISPLACED"
        assert isinstance(charge_b["displaced_reason"], str)
        assert charge_b["displaced_reason"] != ""

    def test_displacement_frees_the_downstream_receipt_and_leaves_the_others_alone(
        self, api
    ):
        """PRD 2.8: "For every kiln charge in `SCHEDULED`, `DISPLACED` or `LOADED`
        status, the charge's `charged_green_bf` equals the total
        `accepted_board_feet` of the green receipts whose `kiln_charge_id` points at
        that charge and whose status is `ALLOCATED` or `CONSUMED`."

        PRD 3.4: "A successful load has two cascades. The chamber moves from
        `AVAILABLE` to `OCCUPIED`, and every receipt allocated to the charge moves
        from `ALLOCATED` to `CONSUMED`, freezing its `accepted_board_feet` and its
        `kiln_charge_id` against any further allocation change — a consumed receipt
        can no longer be deallocated."

        Design: Difficulty/transitive_cascade/redry_extension_displaces_downstream_charge_and_frees_its_receipts
        """
        ctx = _displacement_setup(api)
        validate_success(
            api.record_stress_test(
                ctx["charge"]["id"], record_stress_test_payload(5.9, 8.0), OPERATOR
            ),
            expected_status=200,
        )

        freed = refetch_receipt(api, ctx["receipt_b"]["id"])
        assert freed["status"] == "ACCEPTED"
        assert freed["kiln_charge_id"] is None

        charge_b = refetch_charge(api, ctx["charge_b"]["id"])
        assert charge_b["charged_green_bf"] == pytest.approx(0, abs=0.01)
        assert charge_b["weighted_initial_moisture_pct"] is None

        for receipt in ctx["receipts"]:
            still_held = refetch_receipt(api, receipt["id"])
            assert still_held["status"] == "CONSUMED"
            assert still_held["kiln_charge_id"] == ctx["charge"]["id"]

        rows, meta = validate_paginated(
            api.list_green_receipts(ADMIN, params={"kiln_charge_id": ctx["charge_b"]["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestClaimApprovalCascade:
    """A reserve debit re-derives the line's posture, and a restricted line stops
    the production already booked against it."""

    def test_approval_debits_the_reserve_and_restricts_the_line(self, api):
        """PRD 3.9: "A reference of 7.3 percent against a verified subfloor of
        10.5 gives a delta of 3.2 and an installer share of 40; a verified ambient
        relative humidity of 62 percent lies outside the band and lifts the
        installer share to 50, leaving the mill share at 50."

        PRD 3.9: "A line funded with 600000 cents that commits 151474 to an
        approved claim has a balance of 448526, which is under the floor and makes
        it `RESTRICTED`; funding a further 100000 cents lifts the balance to 548526
        and returns it to `OPEN`."

        Design: Difficulty/transitive_cascade/claim_approval_restricts_line_and_holds_scheduled_prefinish_runs
        """
        ctx = setup_claim_with_scheduled_prefinish_run(api)

        claim = validate_success(
            api.adjudicate_claim(
                ctx["claim"]["id"],
                adjudicate_claim_payload(),
                make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID),
            ),
            expected_status=200,
        )
        assert claim["adjudication_status"] == "APPROVED"
        assert claim["installer_share_pct"] == 50
        assert claim["mill_share_pct"] == 50
        assert claim["adjudicated_liability_cents"] == 151474

        line = refetch_product_line(api, ctx["product_line"]["id"])
        assert line["warranty_balance_cents"] == 448526
        assert line["warranty_committed_cents"] == 151474
        assert line["posture"] == "RESTRICTED"

    def test_restriction_holds_the_prefinish_run_booked_before_the_claim(self, api):
        """PRD 3.9: "When that recomputation leaves the line `RESTRICTED` or
        `FROZEN`, every `SCHEDULED` prefinish run on the line moves to `HELD` as
        described in §3.8 — this is the intended serialization point between
        warranty exposure and further production on the affected line."

        PRD 3.8: "When a product line's posture becomes `RESTRICTED` or `FROZEN`,
        every `SCHEDULED` run whose snapshotted `product_line_id` matches that line
        moves to `HELD` with a `hold_reason` recorded."

        PRD 3.8: "Pushing 5000 linear feet of 3.190-inch boards through a
        three-pass line therefore consumes 47.85 litres."

        Design: Difficulty/transitive_cascade/claim_approval_restricts_line_and_holds_scheduled_prefinish_runs
        """
        ctx = setup_claim_with_scheduled_prefinish_run(api)
        assert ctx["prefinish_run"]["status"] == "SCHEDULED"

        validate_success(
            api.adjudicate_claim(
                ctx["claim"]["id"],
                adjudicate_claim_payload(),
                make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID),
            ),
            expected_status=200,
        )

        run = refetch_prefinish_run(api, ctx["prefinish_run"]["id"])
        assert run["status"] == "HELD"
        assert isinstance(run["hold_reason"], str)
        assert run["hold_reason"] != ""
        assert run["coating_liters"] == pytest.approx(47.85, abs=0.01)

        rows, meta = validate_paginated(
            api.list_prefinish_runs(
                SCHEDULER,
                params={
                    "product_line_id": ctx["product_line"]["id"],
                    "status": "SCHEDULED",
                },
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

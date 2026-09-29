"""Requests that violate two rules at once, checked against the §2.7 ladder."""

import pytest

from test_helpers import (
    ApiErrorId,
    all_elements_passing,
    api_client,
    approved_proof,
    approved_version,
    coord,
    create_plate_order_payload,
    decide_discipline,
    element_checks_for,
    in_review_version,
    new_printer,
    patch_version,
    plate_orders_for_version,
    read_asset,
    read_version,
    revise,
    submit_payload,
    validate_error,
    verify,
)

BROKEN_ALLERGEN = {
    "allergen_statement": {"text": "Contains milk and soya.", "allergen_emphasis": False}
}


class TestVersionStateOutranksMandatoryElementFailure:
    """A submission that is both mis-stated and non-compliant."""

    def _bounced_and_broken(self):
        _brief, _asset, version = in_review_version()
        decide_discipline(version["id"], "BRAND", "REJECTED")
        bounced = read_version(version["id"])
        assert bounced["state"] == "REVISION_REQUESTED"
        assert bounced["revision_cycle_count"] == 1
        assert bounced["route_count"] == 1

        patch_version(
            version["id"],
            {"mandatory_elements": all_elements_passing(**BROKEN_ALLERGEN)},
        )
        reverified = verify(version["id"])
        assert reverified["state"] == "REVISION_REQUESTED"
        assert reverified["check_run_no"] == 2
        assert reverified["failed_element_count"] == 1
        assert reverified["compliance_score"] == pytest.approx(75.0, abs=0.01)
        return version

    def test_submit_from_revision_requested_reports_the_state_not_the_element(self):
        """The state precondition sits ahead of the compliance band in the ladder.

        PRD §3.5: "The version's `state` must be `ELEMENTS_VERIFIED` and its asset
        must not yet be `SUPERSEDED`, else `ERR_VERSION_STATE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/state_invalid_outranks_mandatory_element_failed_on_submit
        """
        version = self._bounced_and_broken()

        response = api_client.submit_artwork_version(
            version["id"], submit_payload(), coord()
        )
        validate_error(response, ApiErrorId.ERR_VERSION_STATE_INVALID.value, 409)

        after = read_version(version["id"])
        assert after["state"] == "REVISION_REQUESTED"
        assert after["route_count"] == 1

    def test_once_reopened_the_same_payload_reports_the_failed_element(self):
        """With the state obstacle cleared, the compliance band speaks.

        PRD §3.5: "No row of the version's current `check_run_no` may carry a
        `result` of `FAIL`, else `ERR_MANDATORY_ELEMENT_FAILED` — note that a waived
        row does not block submission, which is exactly what the half-weight residue
        is for."

        Design: Difficulty/priority_pair_validation_conflict/state_invalid_outranks_mandatory_element_failed_on_submit
        """
        version = self._bounced_and_broken()

        reopened = revise(version["id"])
        assert reopened["state"] == "DRAFT"

        reverified = verify(version["id"])
        assert reverified["state"] == "ELEMENTS_VERIFIED"
        assert reverified["failed_element_count"] == 1
        assert reverified["compliance_score"] == pytest.approx(75.0, abs=0.01)
        failing = [
            row
            for row in element_checks_for(version["id"])
            if row["result"] == "FAIL"
        ]
        assert [row["element_code"] for row in failing] == ["ALLERGEN_STATEMENT"]

        response = api_client.submit_artwork_version(
            version["id"], submit_payload(), coord()
        )
        validate_error(response, ApiErrorId.ERR_MANDATORY_ELEMENT_FAILED.value, 422)

        after = read_version(version["id"])
        assert after["state"] == "ELEMENTS_VERIFIED"
        assert after["route_count"] == 1


class TestProofMismatchOutranksPlateBudget:
    """A plate order that names a foreign proof and also breaks the budget."""

    def _two_vendors_one_version(self):
        _brief, asset, version = approved_version(
            asset_overrides={"plate_budget_cents": 50000}
        )
        assert asset["plate_budget_cents"] == 50000
        assert asset["committed_plate_cost_cents"] == 0

        printer_a = new_printer(name="Cascade Print Co")
        printer_b = new_printer(name="Riverside Litho")
        proof_a = approved_proof(version["id"], printer_a)
        proof_b = approved_proof(version["id"], printer_b)
        assert proof_a["proof_state"] == "PROOF_APPROVED"
        assert proof_b["proof_state"] == "PROOF_APPROVED"
        return asset, version, printer_a, proof_a, proof_b

    def test_foreign_proof_is_reported_ahead_of_the_budget_breach(self):
        """Referential coherence is checked before the fiscal ceiling.

        PRD §3.7: "The named proof must belong to the same version **and** the same
        vendor as the order itself — a proof whose own `artwork_version_id` or
        `printer_id` differs from the order's is `ERR_PROOF_VERSION_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/proof_version_mismatch_outranks_plate_budget_exceeded
        """
        asset, version, printer_a, _proof_a, proof_b = self._two_vendors_one_version()

        response = api_client.create_plate_order(
            create_plate_order_payload(
                version["id"], printer_a["id"], proof_b["id"], plate_set_count=6
            ),
            coord(),
        )
        validate_error(response, ApiErrorId.ERR_PROOF_VERSION_MISMATCH.value, 422)

        assert plate_orders_for_version(version["id"]) == []
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 0

    def test_the_vendors_own_proof_then_reports_the_budget_breach(self):
        """With the mismatch removed, the deliberately-last fiscal check speaks.

        PRD §3.7: "The asset's plate budget is checked last of all, after every
        safety and referential rule: the asset's current `committed_plate_cost_cents`
        plus the new order's `cost_cents` must not exceed the asset's
        `plate_budget_cents`, and a breach is `ERR_PLATE_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/proof_version_mismatch_outranks_plate_budget_exceeded
        """
        asset, version, printer_a, proof_a, _proof_b = self._two_vendors_one_version()

        response = api_client.create_plate_order(
            create_plate_order_payload(
                version["id"], printer_a["id"], proof_a["id"], plate_set_count=6
            ),
            coord(),
        )
        validate_error(response, ApiErrorId.ERR_PLATE_BUDGET_EXCEEDED.value, 422)

        assert plate_orders_for_version(version["id"]) == []
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 0

"""Chairside double-verification, administer, prior-auth consumption (PRD §3.8, §3.4).

Queue A: non_linear_state_machine (reject-revert loop), transitive_cascade
(administer -> consume -> exhaust), priority_pair (cert vs same-nurse),
compensating_invariant (PA units conserved).
Queue B: verify dose mismatch, prepare-twice invalid transition, administer
insufficient PA units.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    assert_prior_auth_conserved,
    factories as f,
    fixtures as fx,
    make_nurse_headers,
)
from test_helpers.test_users import TEST_USERS

PHARM = TEST_USERS["pharmacist_headers"]

FLAT_CHEMO = dict(drug_name="DrugC", role="CHEMO", dosing_method="FLAT",
                  flat_dose_mg=600, vial_size_mg=150, day_offset=1, sequence_index=1)


class TestRejectRevertLoop:
    def test_reject_returns_order_to_ordered_then_reprepare(self):
        """PRD §3.8: "Rejection advances the order from `PREPARED` back to
        `ORDERED`."
        PRD §3.8: "On rejection the `prepared_by_nurse_id` is cleared back to null
        and the order returns to `ORDERED`, ready for a fresh preparation."
        PRD §3.8: "Preparation records the acting nurse's identity in
        `prepared_by_nurse_id` and advances the order from `ORDERED` to `PREPARED`."

        A second nurse rejects (PREPARED->ORDERED), then re-prepares (ORDERED->
        PREPARED) recording the new preparer — a cyclic revision loop.

        Design: Difficulty/non_linear_state_machine/nonlinear_drug_order_prepare_reject_revert_loop
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        n1 = fx.create_nurse(full_name="N1", is_chemo_certified=True)
        n2 = fx.create_nurse(full_name="N2", is_chemo_certified=True)
        order = fx.create_drug_order(env["cycle"]["id"], env["item"]["id"])
        fx.prepare_order(order["id"], n1["id"])

        rejected = validate_success(
            api_client.reject_drug_order(order["id"], make_nurse_headers(n2["id"])), 200)
        assert rejected["status"] == "ORDERED", f"after reject expected ORDERED, got {rejected['status']}"
        assert rejected.get("prepared_by_nurse_id") in (None, ""), (
            f"prepared_by_nurse_id should be cleared, got {rejected.get('prepared_by_nurse_id')}")

        reprepared = validate_success(
            api_client.prepare_drug_order(order["id"], make_nurse_headers(n2["id"])), 200)
        assert reprepared["status"] == "PREPARED"
        assert reprepared["prepared_by_nurse_id"] == n2["id"], (
            f"re-preparer should be {n2['id']}, got {reprepared.get('prepared_by_nurse_id')}")


class TestAdministerConsumesPriorAuth:
    def test_administer_consumes_pa_and_exhausts_at_boundary(self):
        """PRD §3.8: "On success the order's `administered_dose_mg` is set to
        `ordered_dose_mg` and `status` becomes `ADMINISTERED`. If a prior
        authorization is linked, that order's ordered dose is then added to the
        authorization's `consumed_units_mg`; and if that addition makes
        `consumed_units_mg` reach or exceed `authorized_units_mg`, the
        authorization transitions from `APPROVED` to `EXHAUSTED`."

        Administer a 525 mg order against a PA authorized for exactly 525:
        consumed reaches 525 -> EXHAUSTED.

        Design: Difficulty/transitive_cascade/cascade_administer_consumes_pa_then_exhausts
        """
        env = fx.setup_verified_order_with_pa(authorized_units_mg=525)
        administered = validate_success(api_client.administer_drug_order(
            env["order"]["id"], make_nurse_headers(env["nb"]["id"])), 200)
        assert administered["status"] == "ADMINISTERED"
        assert administered["administered_dose_mg"] == 525

        pa = validate_success(api_client.get_prior_authorization(env["pa"]["id"], PHARM), 200)
        assert pa["consumed_units_mg"] == 525, f"expected consumed 525, got {pa['consumed_units_mg']}"
        assert pa["status"] == "EXHAUSTED", f"expected EXHAUSTED, got {pa['status']}"


class TestCertVsSameNursePriority:
    def test_uncertified_same_nurse_verify_returns_certification_error(self):
        """PRD §3.8: "Verification is a four-precondition gate evaluated in this
        order. First, the order must be in `PREPARED` status, or the action is
        rejected with `ERR_ORDER_NOT_PREPARED`. Second, the acting nurse must be
        chemo-certified — their `is_chemo_certified` must be true — or the action
        is rejected with `ERR_NURSE_NOT_CERTIFIED` (403). Third, the acting nurse
        must differ from the recorded `prepared_by_nurse_id`, enforcing
        segregation of duties; a self-verification is rejected with
        `ERR_SAME_NURSE_VERIFICATION` (409)."

        An uncertified preparer self-verifying violates both gates; certification
        (second) precedes same-nurse (third), so ERR_NURSE_NOT_CERTIFIED wins.

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_certified_vs_same_nurse
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        n1 = fx.create_nurse(full_name="N1u", is_chemo_certified=False)
        order = fx.create_drug_order(env["cycle"]["id"], env["item"]["id"])
        fx.prepare_order(order["id"], n1["id"])

        resp = api_client.verify_drug_order(
            order["id"], f.verify_drug_order_payload(600), make_nurse_headers(n1["id"]))
        validate_error(resp, ApiErrorId.ERR_NURSE_NOT_CERTIFIED.value)

        unchanged = validate_success(api_client.get_drug_order(order["id"], PHARM), 200)
        assert unchanged["status"] == "PREPARED", f"order should stay PREPARED, got {unchanged['status']}"


class TestPriorAuthUnitsConserved:
    def test_administer_conserves_authorized_units(self):
        """PRD §3.8: "If a prior authorization is linked, that order's ordered dose
        is then added to the authorization's `consumed_units_mg`"
        PRD §3.8: "the linked authorization must be `APPROVED` and its remaining
        headroom — `authorized_units_mg` minus `consumed_units_mg` — must be at
        least the order's `ordered_dose_mg`"

        Authorized 600, administer 525 -> consumed 525, remaining 75; the PA stays
        APPROVED (not exhausted) and authorized == remaining + consumed.

        Design: Difficulty/compensating_invariant/invariant_pa_units_conserved_on_administer
        """
        env = fx.setup_verified_order_with_pa(authorized_units_mg=600)
        validate_success(api_client.administer_drug_order(
            env["order"]["id"], make_nurse_headers(env["nb"]["id"])), 200)
        pa = validate_success(api_client.get_prior_authorization(env["pa"]["id"], PHARM), 200)
        assert pa["consumed_units_mg"] == 525
        assert pa["authorized_units_mg"] == 600
        assert pa["status"] == "APPROVED", f"PA should still be APPROVED, got {pa['status']}"
        assert (pa["authorized_units_mg"] - pa["consumed_units_mg"]) == 75
        assert_prior_auth_conserved(pa, authorized=600)


class TestVerificationGateCorners:
    def test_verify_dose_mismatch_rejected(self):
        """PRD §3.8: "Fourth, the request carries a `recomputed_dose_mg` that the
        verifying nurse independently recomputes, and it must equal the order's
        stored `ordered_dose_mg`; any mismatch is rejected with
        `ERR_DOSE_VERIFICATION_MISMATCH` (409)."

        recomputed_dose_mg=599 against stored 600 -> mismatch; order stays PREPARED.

        Design: Corner/state_machines/verify_dose_mismatch_rejected
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        n1 = fx.create_nurse(full_name="N1", is_chemo_certified=True)
        n2 = fx.create_nurse(full_name="N2", is_chemo_certified=True)
        order = fx.create_drug_order(env["cycle"]["id"], env["item"]["id"])
        fx.prepare_order(order["id"], n1["id"])

        resp = api_client.verify_drug_order(
            order["id"], f.verify_drug_order_payload(599), make_nurse_headers(n2["id"]))
        validate_error(resp, ApiErrorId.ERR_DOSE_VERIFICATION_MISMATCH.value)

        unchanged = validate_success(api_client.get_drug_order(order["id"], PHARM), 200)
        assert unchanged["status"] == "PREPARED"

    def test_prepare_already_prepared_order_rejected(self):
        """PRD §3.8: "A `Nurse` prepares (mixes) an order, which is legal only when
        the parent cycle is `ACTIVE` (otherwise `ERR_CYCLE_NOT_ACTIVE`) and the
        order is in `ORDERED` status (otherwise `ERR_ORDER_NOT_ORDERED`)."

        A second prepare on an already-PREPARED order returns ERR_ORDER_NOT_ORDERED.

        Design: Corner/state_machines/prepare_order_already_prepared_invalid_transition
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        n1 = fx.create_nurse(full_name="N1", is_chemo_certified=True)
        order = fx.create_drug_order(env["cycle"]["id"], env["item"]["id"])
        fx.prepare_order(order["id"], n1["id"])

        resp = api_client.prepare_drug_order(order["id"], make_nurse_headers(n1["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ORDERED.value)

    def test_administer_insufficient_prior_auth_units_rejected(self):
        """PRD §3.8: "the linked authorization must be `APPROVED` and its remaining
        headroom — `authorized_units_mg` minus `consumed_units_mg` — must be at
        least the order's `ordered_dose_mg`, or administration is rejected with
        `ERR_PRIOR_AUTH_INSUFFICIENT` (402)."

        A 525 mg order against a PA authorized for only 500 (consumed 0) -> 402;
        order stays VERIFIED.

        Design: Corner/validations/administer_insufficient_prior_auth_units_rejected
        """
        env = fx.setup_verified_order_with_pa(authorized_units_mg=500)
        resp = api_client.administer_drug_order(
            env["order"]["id"], make_nurse_headers(env["nb"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PRIOR_AUTH_INSUFFICIENT.value)

        unchanged = validate_success(api_client.get_drug_order(env["order"]["id"], PHARM), 200)
        assert unchanged["status"] == "VERIFIED"

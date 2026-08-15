"""Shortage substitution protocols: activation cascade, substitute, unwind (PRD §3.8).

Substitution-eligible orders must be IV (verification routes IV orders to
QUEUED; non-IV go straight to READY per PRD §3.3, and substitution requires
QUEUED or COMPOUNDING per PRD §3.8), so flagged-order setups here use IV.
"""
import pytest

from test_helpers import (
    create_drug,
    create_patient,
    fixtures,
    setup_active_protocol,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProtocolActivationCascade:
    def test_activation_flags_open_orders_of_shortage_drug(self, api, pharmacist_headers):
        """PRD §3.8: "Activation moves the protocol to `ACTIVE` and runs a two-level flagging cascade. Level one: every medication order whose `drug_product_id` is the shortage drug, whose `verification_status` is `PENDING`, `VERIFIED`, or `ON_HOLD`, and whose `fulfillment_status` is neither `DISPENSED` nor `ADMINISTERED` has its `substitution_pending` set to true, and each such order's `version` increments by 1."

        Design: Difficulty/transitive_cascade/protocol_activation_cascade
        """
        ns = setup_active_protocol(num_flagged_orders=2, route="PO",
                                   ordered_dose_mg=80.0)
        assert ns.protocol["status"] == "ACTIVE"
        for order in ns.orders:
            fetched = validate_success(
                api.get_medication_order(order["id"], pharmacist_headers), 200
            )
            assert fetched["substitution_pending"] is True
        rows, meta = validate_paginated(
            api.list_medication_orders(
                pharmacist_headers,
                params={"drug_product_id": ns.shortage_drug["id"],
                        "verification_status": "VERIFIED"},
            )
        )
        assert meta["total_count"] == 2
        assert all(r["substitution_pending"] is True for r in rows)

    def test_activation_blocks_shortage_drug_pockets(self, api, pharmacist_headers):
        """PRD §3.8: "Level two: every ADC pocket whose `drug_product_id` is the shortage drug has its `pick_blocked` set to true, and each such pocket's `version` increments by 1. The protocol's own `version` increments as well."

        Design: Difficulty/transitive_cascade/protocol_activation_cascade
        """
        ns = setup_active_protocol(num_flagged_orders=1, route="PO",
                                   ordered_dose_mg=80.0, with_pocket=True)
        pocket = validate_success(
            api.get_adc_pocket(ns.pocket_ns.pocket["id"], pharmacist_headers), 200
        )
        assert pocket["pick_blocked"] is True


class TestProtocolAutoExpiry:
    def test_clock_reaching_expires_at_expires_protocol_and_compensates(
        self, api, admin_headers, pharmacist_headers
    ):
        """PRD §2.6: "second, every substitution protocol in `ACTIVE` whose `expires_at` has been reached or passed transitions to `EXPIRED`, running the same compensation cascade as a manual revocation."
        PRD §3.8: "Revocation is the `PharmacyAdmin` unwind of an `ACTIVE` protocol, and expiry of an `ACTIVE` protocol at the clock sweep runs the identical compensation: every order this protocol flagged that still has `substitution_pending` true and has not yet been substituted (`substituted_by_protocol_id` still null) has its `substitution_pending` reset to false, and every pocket this protocol blocked has its `pick_blocked` reset to false"

        Design: Corner/state_machines/protocol_auto_expiry_on_clock_sweep
        """
        ns = setup_active_protocol(num_flagged_orders=1, route="PO",
                                   ordered_dose_mg=80.0, with_pocket=True,
                                   expires_at="2026-08-10T00:00:00Z")
        order_id = ns.orders[0]["id"]
        fixtures.set_clock("2026-08-10T00:00:00Z")
        protocol = validate_success(
            api.get_substitution_protocol(ns.protocol["id"], admin_headers), 200
        )
        assert protocol["status"] == "EXPIRED"
        order = validate_success(
            api.get_medication_order(order_id, pharmacist_headers), 200
        )
        assert order["substitution_pending"] is False
        pocket = validate_success(
            api.get_adc_pocket(ns.pocket_ns.pocket["id"], pharmacist_headers), 200
        )
        assert pocket["pick_blocked"] is False


class TestProtocolRevokeCompensation:
    def test_revoke_unflags_pending_orders_keeps_substituted_ones(self, api, pharmacist_headers):
        """PRD §3.8: "Revocation is the `PharmacyAdmin` unwind of an `ACTIVE` protocol, and expiry of an `ACTIVE` protocol at the clock sweep runs the identical compensation: every order this protocol flagged that still has `substitution_pending` true and has not yet been substituted (`substituted_by_protocol_id` still null) has its `substitution_pending` reset to false, and every pocket this protocol blocked has its `pick_blocked` reset to false; a manual revocation also increments the protocol's `version`."

        Design: Corner/cross_cutting_layers/protocol_revoke_compensates_cascade
        """
        ns = setup_active_protocol(num_flagged_orders=2, route="IV",
                                   ordered_dose_mg=80.0, with_pocket=True)
        substituted = validate_success(
            api.substitute_order(ns.orders[0]["id"],
                                 {"protocol_id": ns.protocol["id"]},
                                 ns.pharmacist_headers),
            200,
        )
        assert substituted["drug_product_id"] == ns.substitute_drug["id"]
        protocol = validate_success(
            api.revoke_substitution_protocol(ns.protocol["id"], fixtures.ADMIN), 200
        )
        assert protocol["status"] == "REVOKED"
        order1 = validate_success(
            api.get_medication_order(ns.orders[0]["id"], pharmacist_headers), 200
        )
        assert order1["drug_product_id"] == ns.substitute_drug["id"]
        assert order1["ordered_dose_mg"] == pytest.approx(40.0, abs=1e-9)
        order2 = validate_success(
            api.get_medication_order(ns.orders[1]["id"], pharmacist_headers), 200
        )
        assert order2["substitution_pending"] is False
        pocket = validate_success(
            api.get_adc_pocket(ns.pocket_ns.pocket["id"], pharmacist_headers), 200
        )
        assert pocket["pick_blocked"] is False


class TestSubstitutionEquivalentDose:
    def test_substitute_rewrites_drug_and_step_rounds_clamped_dose(self, api):
        """PRD §3.8: "A successful substitution rewrites the order: `drug_product_id` becomes the protocol's `substitute_drug_product_id`; `ordered_dose_mg` becomes the substitution-equivalent dose — the original `ordered_dose_mg` times the protocol's `conversion_factor`, that product step-rounded on the same ladder as dose volumes, then clamped to no less than the protocol's `min_dose_mg` and no more than its `max_dose_mg`; `substituted_by_protocol_id` records the protocol and `substitution_pending` flips to false; the renal adjustment and final dose are recomputed for the new drug; and the order's `version` increments by 1."

        Design: Corner/calculations/substitution_equivalent_dose_computed
        """
        ns = setup_active_protocol(num_flagged_orders=1, route="IV",
                                   ordered_dose_mg=80.0, conversion_factor=0.5,
                                   min_dose_mg=10.0, max_dose_mg=200.0)
        order = ns.orders[0]
        substituted = validate_success(
            api.substitute_order(order["id"], {"protocol_id": ns.protocol["id"]},
                                 ns.pharmacist_headers),
            200,
        )
        # 80 mg x 0.5 == 40.0 (step 1.0 keeps 40.0); clamp [10, 200] inert
        assert substituted["ordered_dose_mg"] == pytest.approx(40.0, abs=1e-9)
        assert substituted["drug_product_id"] == ns.substitute_drug["id"]
        assert substituted["substituted_by_protocol_id"] == ns.protocol["id"]
        assert substituted["substitution_pending"] is False


class TestSubstituteGuardFailures:
    def test_substitute_without_pending_flag_rejected(self, api):
        """PRD §3.8: "The guards fire in priority order: the order must be `VERIFIED`; its `substitution_pending` must be true, otherwise `ERR_SUBSTITUTION_NOT_PENDING`; the named protocol must be `ACTIVE` and its `shortage_drug_product_id` must equal the order's current `drug_product_id`, otherwise `ERR_NO_ACTIVE_PROTOCOL`"

        Design: Corner/errors/error_substitution_not_pending
        """
        # Protocol activates with zero orders in flight, so nothing is flagged.
        ns = setup_active_protocol(num_flagged_orders=0, route="IV")
        patient = create_patient()
        order = fixtures.place_order(patient, ns.shortage_drug, ns.prescriber,
                                     route="IV", ordered_dose_mg=80.0)
        order = fixtures.verify_order(order["id"], ns.pharmacist)
        resp = api.substitute_order(order["id"], {"protocol_id": ns.protocol["id"]},
                                    ns.pharmacist_headers)
        validate_error(resp, "ERR_SUBSTITUTION_NOT_PENDING", 422)

    # NOTE: Difficulty/priority_pair_validation_conflict/
    # substitute_safety_beats_protocol_referential's allergy-beats-DRAFT probe
    # was removed: PRD §2.7's global tier list orders the allergy screen
    # (business-safety) ahead of substitution preconditions
    # (business-referential), but PRD §3.8's endpoint-specific sentence — "The
    # guards fire in priority order: ... the named protocol must be `ACTIVE`
    # ... otherwise `ERR_NO_ACTIVE_PROTOCOL`; ... the substitute drug must not
    # appear in the patient's `allergy_drug_product_ids`, otherwise
    # `ERR_ALLERGY_CONFLICT`" — enumerates NO_ACTIVE_PROTOCOL ahead of
    # ALLERGY_CONFLICT. The two verbatim sentences diverge for exactly this
    # request, so the asserted outcome is not uniquely derivable from PRD.

    def test_substitute_with_draft_protocol_alone_reports_no_active_protocol(self, api):
        """PRD §3.8: "the named protocol must be `ACTIVE` and its `shortage_drug_product_id` must equal the order's current `drug_product_id`, otherwise `ERR_NO_ACTIVE_PROTOCOL`"

        Design: Difficulty/priority_pair_validation_conflict/substitute_safety_beats_protocol_referential
        """
        ns = setup_active_protocol(num_flagged_orders=1, route="IV",
                                   ordered_dose_mg=80.0)
        order = ns.orders[0]
        draft = fixtures.create_protocol(ns.shortage_drug, ns.substitute_drug,
                                         conversion_factor=0.25)
        resp = api.substitute_order(order["id"], {"protocol_id": draft["id"]},
                                    ns.pharmacist_headers)
        # No safety violation is live here, so the referential failure surfaces.
        validate_error(resp, "ERR_NO_ACTIVE_PROTOCOL", 422)
        fetched = validate_success(
            api.get_medication_order(order["id"], ns.pharmacist_headers), 200
        )
        assert fetched["drug_product_id"] == ns.shortage_drug["id"]
        assert fetched["substitution_pending"] is True


class TestProtocolActivationGuards:
    def test_activate_with_discontinued_substitute_rejected(self, api, admin_headers):
        """PRD §3.8: "Activation is the `PharmacyAdmin` action that arms a `DRAFT` protocol, and it is gated three ways: the shortage drug's `in_shortage` flag must be true, otherwise `ERR_DRUG_NOT_IN_SHORTAGE`; the substitute drug's formulary `status` must be `ACTIVE`, otherwise `ERR_NO_ELIGIBLE_SUBSTITUTE`; and the logical clock must be strictly before `expires_at` — activating at or after expiry is rejected with `ERR_PROTOCOL_EXPIRED`."

        Design: Corner/errors/error_no_eligible_substitute_empty_pool
        """
        shortage = create_drug(in_shortage=True)
        substitute = create_drug(status="DISCONTINUED")
        protocol = fixtures.create_protocol(shortage, substitute)
        resp = api.activate_substitution_protocol(protocol["id"], admin_headers)
        validate_error(resp, "ERR_NO_ELIGIBLE_SUBSTITUTE", 422)
        fetched = validate_success(
            api.get_substitution_protocol(protocol["id"], admin_headers), 200
        )
        assert fetched["status"] == "DRAFT"

    def test_activate_without_shortage_flag_rejected(self, api, admin_headers):
        """PRD §3.8: "Activation is the `PharmacyAdmin` action that arms a `DRAFT` protocol, and it is gated three ways: the shortage drug's `in_shortage` flag must be true, otherwise `ERR_DRUG_NOT_IN_SHORTAGE`; the substitute drug's formulary `status` must be `ACTIVE`, otherwise `ERR_NO_ELIGIBLE_SUBSTITUTE`; and the logical clock must be strictly before `expires_at` — activating at or after expiry is rejected with `ERR_PROTOCOL_EXPIRED`."

        Design: Corner/errors/error_drug_not_in_shortage_on_activate
        """
        shortage = create_drug(in_shortage=False)
        substitute = create_drug()
        protocol = fixtures.create_protocol(shortage, substitute,
                                            conversion_factor=1.0,
                                            max_dose_mg=500.0)
        resp = api.activate_substitution_protocol(protocol["id"], admin_headers)
        validate_error(resp, "ERR_DRUG_NOT_IN_SHORTAGE", 422)
        fetched = validate_success(
            api.get_substitution_protocol(protocol["id"], admin_headers), 200
        )
        assert fetched["status"] == "DRAFT"

    def test_activate_after_expiry_rejected(self, api, admin_headers):
        """PRD §3.8: "Activation is the `PharmacyAdmin` action that arms a `DRAFT` protocol, and it is gated three ways: the shortage drug's `in_shortage` flag must be true, otherwise `ERR_DRUG_NOT_IN_SHORTAGE`; the substitute drug's formulary `status` must be `ACTIVE`, otherwise `ERR_NO_ELIGIBLE_SUBSTITUTE`; and the logical clock must be strictly before `expires_at` — activating at or after expiry is rejected with `ERR_PROTOCOL_EXPIRED`."

        Design: Corner/errors/error_protocol_expired_on_activate
        """
        shortage = create_drug(in_shortage=True)
        substitute = create_drug()
        protocol = fixtures.create_protocol(shortage, substitute,
                                            expires_at="2026-08-03T00:00:00Z")
        fixtures.set_clock("2026-08-05T00:00:00Z")
        resp = api.activate_substitution_protocol(protocol["id"], admin_headers)
        validate_error(resp, "ERR_PROTOCOL_EXPIRED", 422)
        fetched = validate_success(
            api.get_substitution_protocol(protocol["id"], admin_headers), 200
        )
        assert fetched["status"] == "DRAFT"

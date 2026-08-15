"""Charge composition: server-computed fields at creation, initial state,
immediate consistency, and piece manifest materialization (PRD §3.5)."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_charge_payload,
    setup_shop,
    validate_paginated,
    validate_success,
)

OP = TEST_USERS["plant_operator_headers"]


class TestComputedFieldsAtComposition:
    def test_computed_target_retention_pcf_derived_from_use_category(self, api):
        """PRD §3.5: "The `target_retention_pcf` comes from a fixed lookup
        keyed by `use_category`."
        PRD §3.5: "Several properties are derived the moment the charge is
        composed."

        Design: Corner/entities/computed_target_retention_pcf_derived_from_use_category
        """
        shop = setup_shop()
        plant_id, cyl_id = shop["plant"]["id"], shop["cylinder"]["id"]

        # Two charges with the same use_category must resolve to the same
        # server-computed target; client-supplied values play no role.
        first = load_and_read(api, plant_id, cyl_id, shop, use_category="UC4A")
        shop2 = setup_shop()
        second = load_and_read(api, shop2["plant"]["id"], shop2["cylinder"]["id"],
                               shop2, use_category="UC4A")
        assert isinstance(first["target_retention_pcf"], (int, float))
        assert first["target_retention_pcf"] > 0
        assert first["target_retention_pcf"] == second["target_retention_pcf"]

    def test_computed_requires_incising_for_doug_fir_uc4b(self, api):
        """PRD §3.5: "The `requires_incising` flag is true precisely when the
        species group is `DOUGLAS_FIR` or `HEM_FIR` and the use category is
        `UC4B` or `UC4C`. The `is_custom_treat` flag mirrors whether
        `ownership_type` is `CUSTOM_TREAT`."

        Design: Corner/entities/computed_requires_incising_for_doug_fir_uc4b
        """
        shop = setup_shop()
        charge = load_and_read(api, shop["plant"]["id"], shop["cylinder"]["id"],
                               shop, species_group="DOUGLAS_FIR", use_category="UC4B")
        assert charge["requires_incising"] is True
        assert charge["is_custom_treat"] is False

    def test_initial_state_new_charge_is_in_cylinder(self, api):
        """PRD §3.5: "A successful load is atomic in effect: the charge, which
        begins `STAGED`, moves immediately to `IN_CYLINDER`, the cylinder moves
        to `LOADED`, the ChargePiece rows are auto-created from the manifest in
        `RAW` status".

        Design: Corner/state_machines/initial_state_new_charge_is_in_cylinder
        """
        shop = setup_shop()
        resp = api.load_charge(
            shop["plant"]["id"], shop["cylinder"]["id"], create_charge_payload(), OP)
        charge = validate_success(resp, 201)
        assert charge["status"] == "IN_CYLINDER"

    def test_immediate_consistency_charge_create_response(self, api):
        """PRD §3.5: "Several properties are derived the moment the charge is
        composed. The `target_retention_pcf` comes from a fixed lookup keyed by
        `use_category`. ... The `provisional_retention_pcf` and
        `final_retention_pcf` both start at 0 ... and the charge's
        `hazard_containment_flag` starts false."

        Design: Corner/consistency_model/immediate_consistency_charge_create_response
        """
        shop = setup_shop()
        resp = api.load_charge(
            shop["plant"]["id"], shop["cylinder"]["id"],
            create_charge_payload(species_group="SYP", use_category="UC4B"), OP)
        charge = validate_success(resp, 201)
        # All derived fields are visible immediately in the create response.
        assert charge["status"] == "IN_CYLINDER"
        # SYP is not in {DOUGLAS_FIR, HEM_FIR}, so incising is not required.
        assert charge["requires_incising"] is False
        assert charge["is_custom_treat"] is False
        assert charge["hazard_containment_flag"] is False
        assert charge["provisional_retention_pcf"] == 0
        assert charge["final_retention_pcf"] == 0
        assert isinstance(charge["target_retention_pcf"], (int, float))
        assert charge["target_retention_pcf"] > 0

    def test_fk_reverse_reachability_charge_pieces(self, api):
        """PRD §3.5: "the ChargePiece rows are auto-created from the manifest
        in `RAW` status".
        PRD §4: "GET /treatment-plants/{plantId}/charges/{chargeId}/pieces —
        List pieces in a charge".

        Design: Corner/entities/fk_reverse_reachability_charge_pieces
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        manifest = [
            {"piece_tag": "P1", "length_ft": 8.0, "width_in": 5.5, "thickness_in": 1.5},
            {"piece_tag": "P2", "length_ft": 10.0, "width_in": 5.5, "thickness_in": 1.5},
        ]
        charge = load_and_read(api, plant_id, shop["cylinder"]["id"], shop,
                               piece_manifest=manifest)
        pieces, meta = validate_paginated(api.list_pieces(plant_id, charge["id"], OP))
        assert meta["total_count"] == 2
        assert len(pieces) == 2
        for piece in pieces:
            assert piece["charge_id"] == charge["id"]
            assert piece["status"] == "RAW"
        assert {p["piece_tag"] for p in pieces} == {"P1", "P2"}


def load_and_read(api, plant_id, cyl_id, shop, **overrides):
    resp = api.load_charge(plant_id, cyl_id, create_charge_payload(**overrides), OP)
    return validate_success(resp, 201)

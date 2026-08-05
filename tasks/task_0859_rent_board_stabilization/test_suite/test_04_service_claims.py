"""Service-reduction claims: substantiation decrease cascade and restoration invariant.

Sources: Difficulty/transitive_cascade, Difficulty/compensating_invariant.
"""
from test_helpers import (
    validate_success,
    make_landlord_headers, make_hearing_officer_headers,
    setup_service_claim_investigating, setup_service_claim_substantiated,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/service_decrease_cascade_depth2
# ---------------------------------------------------------------------------
def test_substantiate_decreases_unit_and_tenancy(api):
    """PRD §3.6: "computes decrease_amount_cents as the snapshotted pre-decrease rent
    multiplied by that fraction and rounded half-up, subtracts that decrease amount from
    the unit's current_lawful_rent_cents ... and cascades the decreased lawful rent to the
    unit's ACTIVE tenancy." (25% of 300000 = 75000; 300000 - 75000 = 225000.)

    Design: Difficulty/transitive_cascade/service_decrease_cascade_depth2
    """
    ctx = setup_service_claim_investigating(api, claim_type="HEAT", severity="SUBSTANTIAL",
                                            base_rent_cents=300000)
    oheaders = make_hearing_officer_headers(ctx["officer_id"])
    claim = validate_success(api.decide_service_claim(
        ctx["claim_id"], {"disposition": "SUBSTANTIATE"}, oheaders))
    assert claim["decrease_amount_cents"] == 75000
    unit = validate_success(api.get_unit(ctx["unit_id"], oheaders))
    tenancy = validate_success(api.get_tenancy(ctx["tenancy_id"], make_landlord_headers(ctx["landlord_id"])))
    assert unit["current_lawful_rent_cents"] == 225000
    assert tenancy["monthly_rent_cents"] == 225000


def test_substantiate_sets_ordered_decrease_and_flag(api):
    """PRD §3.6: "sets `ordered_decrease_pct` from severity — twenty-five percent for
    `SUBSTANTIAL`, ten percent for `MINOR` ... sets the unit's `decrease_active` flag to
    true, and cascades the decreased lawful rent to the unit's `ACTIVE` tenancy".

    Design: Difficulty/transitive_cascade/service_decrease_cascade_depth2
    """
    ctx = setup_service_claim_investigating(api, claim_type="HEAT", severity="SUBSTANTIAL",
                                            base_rent_cents=300000)
    oheaders = make_hearing_officer_headers(ctx["officer_id"])
    claim = validate_success(api.decide_service_claim(
        ctx["claim_id"], {"disposition": "SUBSTANTIATE"}, oheaders))
    assert claim["status"] == "SUBSTANTIATED"
    unit = validate_success(api.get_unit(ctx["unit_id"], oheaders))
    assert unit["decrease_active"] is True


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/service_decrease_restore_conserves_lawful_rent
# ---------------------------------------------------------------------------
def test_restore_returns_lawful_rent_to_snapshot(api):
    """PRD §3.6: "Restoration is a compensating action: it sets the unit's
    current_lawful_rent_cents back to exactly the claim's pre_decrease_rent_cents, clears
    decrease_active to false ... the unit's lawful rent returns precisely to its
    pre-decrease value." (300000 → 225000 → 300000.)

    Design: Difficulty/compensating_invariant/service_decrease_restore_conserves_lawful_rent
    """
    ctx = setup_service_claim_substantiated(api, claim_type="WATER", severity="SUBSTANTIAL",
                                            base_rent_cents=300000)
    validate_success(api.restore_service_claim(ctx["claim_id"], CLERK))
    unit = validate_success(api.get_unit(ctx["unit_id"], CLERK))
    assert unit["current_lawful_rent_cents"] == 300000
    assert unit["decrease_active"] is False


def test_restore_cascades_tenancy_back_to_pre_decrease(api):
    """PRD §3.6: "and cascades the restored lawful rent to the unit's ACTIVE tenancy."
    PRD §2.6: "that tenancy's monthly_rent_cents is set to the unit's new lawful rent in
    the same operation."

    Design: Difficulty/compensating_invariant/service_decrease_restore_conserves_lawful_rent
    """
    ctx = setup_service_claim_substantiated(api, claim_type="WATER", severity="SUBSTANTIAL",
                                            base_rent_cents=300000)
    validate_success(api.restore_service_claim(ctx["claim_id"], CLERK))
    tenancy = validate_success(api.get_tenancy(ctx["tenancy_id"], make_landlord_headers(ctx["landlord_id"])))
    assert tenancy["monthly_rent_cents"] == 300000

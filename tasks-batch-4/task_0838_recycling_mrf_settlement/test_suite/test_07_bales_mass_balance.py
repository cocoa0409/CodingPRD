"""Bale creation constraints, void, and load mass conservation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    assert_load_mass_balance,
)
from test_helpers.fixtures import (
    set_clock, create_and_publish_index, create_bale, setup_audited_load,
    setup_shipped_single_bale,
)

SORT = TEST_USERS["sort_manager_headers"]


# --- Difficulty: voiding a bale conserves load tonnage ----------------------

def test_void_bale_restores_unbaled_remaining(api):
    """PRD §3.6: "Voiding also returns mass to the source load: the load's
    `baled_tons` drops by the voided bale's `net_tons` and its
    `unbaled_remaining_tons` is restored by the same amount, leaving `net_tons`
    unchanged."

    Design: Difficulty/compensating_invariant/void_bale_conserves_load_tonnage
    """
    set_clock(api, "2026-03-10T00:00:00Z")
    create_and_publish_index(api, "OCC", 8000)
    ctx = setup_audited_load(api, gross_tons=20, tare_tons=0)
    bale = create_bale(api, ctx["load_id"], "OCC", net_tons=8, moisture_pct=0,
                       quality_grade="A")
    before = validate_success(api.get_inbound_load(ctx["load_id"], SORT))
    assert before["unbaled_remaining_tons"] == 12
    api.void_bale(bale["id"], SORT)
    after = validate_success(api.get_inbound_load(ctx["load_id"], SORT))
    assert after["unbaled_remaining_tons"] == 20
    assert after["baled_tons"] == 0


def test_void_bale_keeps_net_tons_invariant(api):
    """PRD §3.5: "the three components — baled, residual, and unbaled — always sum
    back to `net_tons`."
    PRD §3.6: "Voiding moves the bale to `VOIDED` (terminal), clears its
    `shipment_id`".

    Design: Difficulty/compensating_invariant/void_bale_conserves_load_tonnage
    """
    set_clock(api, "2026-03-10T00:00:00Z")
    create_and_publish_index(api, "OCC", 8000)
    ctx = setup_audited_load(api, gross_tons=20, tare_tons=0)
    bale = create_bale(api, ctx["load_id"], "OCC", net_tons=8, moisture_pct=0,
                       quality_grade="A")
    voided = validate_success(api.void_bale(bale["id"], SORT))
    assert voided["status"] == "VOIDED"
    load = validate_success(api.get_inbound_load(ctx["load_id"], SORT))
    assert load["net_tons"] == 20
    assert_load_mass_balance(load)


# --- Difficulty: safety check pre-empts tonnage constraint on bale create ----

def test_bale_create_commodity_error_beats_tonnage_error(api):
    """PRD §2.10: "(7) safety and commodity-validity checks such as contamination
    being processable and a bale's commodity being recognized (422); ... (9)
    quantity and interval feasibility such as valid intervals, residual not
    exceeding net, bale tonnage within remaining, and a shipment being non-empty
    (422)".
    PRD §3.6: "The declared commodity must actually appear in that load's
    `audited_composition`; a commodity absent from the audit is refused with
    `ERR_COMMODITY_NOT_IN_LOAD`."

    Design: Difficulty/priority_pair_validation_conflict/bale_create_commodity_safety_beats_tonnage_constraint
    """
    ctx = setup_audited_load(api, gross_tons=5, tare_tons=0,
                             sampled_contamination_pct=3.0,
                             audited_composition=[{"commodity": "OCC", "pct": 96}])
    resp = api.create_bale(
        {"source_load_id": ctx["load_id"], "commodity": "PET", "net_tons": 999,
         "moisture_pct": 0, "quality_grade": "A"}, SORT)
    validate_error(resp, ApiErrorId.ERR_COMMODITY_NOT_IN_LOAD.value)


def test_bale_create_commodity_conflict_creates_no_bale(api):
    """PRD §3.6: "The declared commodity must actually appear in that load's
    `audited_composition`; a commodity absent from the audit is refused with
    `ERR_COMMODITY_NOT_IN_LOAD`."
    PRD §3.5: "At any moment `baled_tons` is the sum of `net_tons` over the load's
    non-`VOIDED` bales, and `unbaled_remaining_tons` equals `net_tons` minus
    `baled_tons` minus `residual_tons`".

    Design: Difficulty/priority_pair_validation_conflict/bale_create_commodity_safety_beats_tonnage_constraint
    """
    ctx = setup_audited_load(api, gross_tons=5, tare_tons=0,
                             sampled_contamination_pct=3.0,
                             audited_composition=[{"commodity": "OCC", "pct": 96}])
    api.create_bale(
        {"source_load_id": ctx["load_id"], "commodity": "PET", "net_tons": 999,
         "moisture_pct": 0, "quality_grade": "A"}, SORT)
    data, meta = validate_paginated(
        api.list_bales(SORT, params={"source_load_id": ctx["load_id"]}))
    assert len(data) == 0
    load = validate_success(api.get_inbound_load(ctx["load_id"], SORT))
    assert load["unbaled_remaining_tons"] == 5


# --- Corner: a shipped bale cannot be voided --------------------------------

def test_void_shipped_bale_rejected(api):
    """PRD §3.6: "A `SortManager` voids a bale that is still in `BALED` or
    `STAGED`; a bale already `SHIPPED` or `SETTLED` cannot be voided, and any such
    attempt is `ERR_BALE_NOT_VOIDABLE`."

    Design: Corner/errors/corner_bale_not_voidable_after_shipped
    """
    ctx = setup_shipped_single_bale(api, index_price_cents_per_ton=8000,
                                    bale_net_tons=10, moisture_pct=0,
                                    quality_grade="A", freight_cost_cents=0)
    resp = api.void_bale(ctx["bale_id"], SORT)
    validate_error(resp, ApiErrorId.ERR_BALE_NOT_VOIDABLE.value)

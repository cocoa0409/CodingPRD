"""Receiving, auditing, contamination provisional adjustment, and the re-audit loop."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_municipality, create_sort_line, create_load, audit_load,
    close_load, create_and_publish_index, create_bale, setup_received_load,
    setup_audited_load,
)

SCALE = TEST_USERS["scale_operator_headers"]
SORT = TEST_USERS["sort_manager_headers"]


def test_net_tons_computed_from_gross_minus_tare(api):
    """PRD §3.4: "The load's conserved net weight, `net_tons`, is computed as
    `gross_tons` minus `tare_tons`; this quantity is the anchor of mass balance
    and never changes thereafter."
    PRD §3.4: "A new load enters in `RECEIVED` status."

    Design: Corner/entities/corner_net_tons_computed_from_gross_minus_tare
    """
    muni = create_municipality(api)
    line = create_sort_line(api)
    load = create_load(api, muni["id"], line["id"], gross_tons=25.5, tare_tons=3.5)
    assert load["net_tons"] == 22.0
    assert load["status"] == "RECEIVED"


def test_contamination_penalty_tier_value(api):
    """PRD §3.5: "If contamination is at least the penalty threshold of 12.0
    percent, the load incurs a penalty: let the points over threshold be the
    contamination percentage minus 12.0; the adjustment is a negative amount whose
    magnitude is `net_tons` multiplied by those points-over multiplied by 150 cents
    per ton-per-point, rounded half up to whole cents."

    Design: Corner/calculations/corner_contamination_penalty_tier_value
    """
    ctx = setup_received_load(api, gross_tons=20, tare_tons=0)
    load = audit_load(api, ctx["load_id"], sampled_contamination_pct=15.0,
                      audited_composition=[{"commodity": "OCC", "pct": 85}])
    assert load["provisional_adjustment_cents"] == -9000


def test_audit_reject_threshold_unprocessable_keeps_received(api):
    """PRD §3.4: "The sampled contamination must be strictly below the reject
    threshold of 40 percent; a load at or above that contamination is
    unprocessable and the audit is refused with `ERR_CONTAMINATION_UNPROCESSABLE`."

    Design: Corner/validations/corner_contamination_reject_threshold_unprocessable
    """
    ctx = setup_received_load(api, gross_tons=20, tare_tons=0)
    resp = api.audit_inbound_load(
        ctx["load_id"],
        {"sampled_contamination_pct": 45.0,
         "audited_composition": [{"commodity": "OCC", "pct": 55}]}, SCALE)
    validate_error(resp, ApiErrorId.ERR_CONTAMINATION_UNPROCESSABLE.value)
    still = validate_success(api.get_inbound_load(ctx["load_id"], SCALE))
    assert still["status"] == "RECEIVED"


def test_audit_closed_load_not_auditable(api):
    """PRD §3.4: "An audit may only run on a load in `RECEIVED` or
    `PENDING_REAUDIT`; attempting it in any other state yields
    `ERR_LOAD_NOT_AUDITABLE`."

    Design: Corner/state_machines/corner_audit_closed_load_terminal_lockdown
    """
    ctx = setup_audited_load(api, gross_tons=10, tare_tons=0,
                             sampled_contamination_pct=2.0)
    close_load(api, ctx["load_id"], residual_tons=0)
    resp = api.audit_inbound_load(
        ctx["load_id"],
        {"sampled_contamination_pct": 3.0,
         "audited_composition": [{"commodity": "OCC", "pct": 97}]}, SCALE)
    validate_error(resp, ApiErrorId.ERR_LOAD_NOT_AUDITABLE.value)


def test_reaudit_blocked_when_bale_exists(api):
    """PRD §3.4: "Re-audit may only be requested on a load actually in `AUDITED`,
    and only while no non-`VOIDED` bales exist for that load; either violation is
    reported as `ERR_LOAD_INVALID_STATE`."

    Design: Corner/state_machines/corner_reaudit_blocked_when_bales_exist
    """
    set_clock(api, "2026-03-10T00:00:00Z")
    create_and_publish_index(api, "OCC", 8000)
    ctx = setup_audited_load(api, gross_tons=12, tare_tons=2)
    create_bale(api, ctx["load_id"], "OCC", net_tons=5, moisture_pct=0,
                quality_grade="A")
    resp = api.request_reaudit_inbound_load(
        ctx["load_id"], {"reason": "re-check"}, SORT)
    validate_error(resp, ApiErrorId.ERR_LOAD_INVALID_STATE.value)


# --- Difficulty: contamination clean threshold inclusive boundary -----------

def test_contamination_clean_threshold_exactly_five_is_rebate(api):
    """PRD §3.5: "The thresholds are inclusive on both sides: exactly 5.0 is a
    rebate, and exactly 12.0 is a penalty of zero points, which evaluates to 0."
    PRD §3.5: "the adjustment is a positive amount equal to `net_tons` multiplied
    by 300 cents per ton, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/contamination_clean_threshold_inclusive_boundary
    """
    ctx = setup_received_load(api, gross_tons=20, tare_tons=0)
    load = audit_load(api, ctx["load_id"], sampled_contamination_pct=5.0,
                      audited_composition=[{"commodity": "OCC", "pct": 95}])
    assert load["provisional_adjustment_cents"] == 6000


def test_contamination_just_over_clean_threshold_yields_zero(api):
    """PRD §3.5: "Contamination strictly between 5.0 and 12.0 yields an adjustment
    of exactly 0."

    Design: Difficulty/boundary_precision_check/contamination_clean_threshold_inclusive_boundary
    """
    ctx = setup_received_load(api, gross_tons=20, tare_tons=0)
    load = audit_load(api, ctx["load_id"], sampled_contamination_pct=5.01,
                      audited_composition=[{"commodity": "OCC", "pct": 94}])
    assert load["provisional_adjustment_cents"] == 0


# --- Difficulty: inbound load re-audit cycle --------------------------------

def test_reaudit_cycle_returns_to_audited(api):
    """PRD §3.4: "A `SortManager` may send an `AUDITED` load back for correction,
    supplying a `reason`; this drives the revision loop `AUDITED → PENDING_REAUDIT`,
    forcing a fresh audit."
    PRD §3.4: "A successful audit stores the sampled contamination and composition,
    computes and stores the load's `provisional_adjustment_cents` from the sampled
    figure (the provisional variant of the contamination calculation described in
    §3.5), and moves the load to `AUDITED`."

    Design: Difficulty/non_linear_state_machine/inbound_load_reaudit_cycle
    """
    ctx = setup_audited_load(api, gross_tons=22, tare_tons=2,
                             sampled_contamination_pct=4.0,
                             audited_composition=[{"commodity": "OCC", "pct": 98}])
    api.request_reaudit_inbound_load(ctx["load_id"], {"reason": "sampling error"}, SORT)
    load = audit_load(api, ctx["load_id"], sampled_contamination_pct=8.0,
                      audited_composition=[{"commodity": "OCC", "pct": 92}])
    assert load["status"] == "AUDITED"


def test_reaudit_recomputes_provisional_adjustment(api):
    """PRD §3.4: "Re-auditing a load that returned to `PENDING_REAUDIT` overwrites
    the stored sample and composition and recomputes `provisional_adjustment_cents`
    the same way."
    PRD §3.5: "Contamination strictly between 5.0 and 12.0 yields an adjustment of
    exactly 0."

    Design: Difficulty/non_linear_state_machine/inbound_load_reaudit_cycle
    """
    ctx = setup_audited_load(api, gross_tons=22, tare_tons=2,
                             sampled_contamination_pct=4.0,
                             audited_composition=[{"commodity": "OCC", "pct": 98}])
    first = validate_success(api.get_inbound_load(ctx["load_id"], SCALE))
    assert first["provisional_adjustment_cents"] == 6000  # clean rebate at audit
    api.request_reaudit_inbound_load(ctx["load_id"], {"reason": "sampling error"}, SORT)
    load = audit_load(api, ctx["load_id"], sampled_contamination_pct=8.0,
                      audited_composition=[{"commodity": "OCC", "pct": 92}])
    assert load["provisional_adjustment_cents"] == 0

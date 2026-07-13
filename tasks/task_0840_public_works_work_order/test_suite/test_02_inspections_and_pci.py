"""Inspections: PCI computation, condition thresholds, acceptance cascade,
the reject/resubmit revision cycle, and segregation of duties."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, make_asset, create_submitted_inspection,
    inspector_headers, supervisor_headers,
)

CLOCK = "2026-06-01T00:00:00Z"


# --- Difficulty: dual-variant PCI (CONDITION vs PREVENTIVE) --------------

def test_pci_condition_variant_full_age_penalty(api):
    """PRD §3.3: "a base index is computed as 100 minus the product of `raw_distress_index` and the severity weight. Finally, `computed_pci` is the base index minus the age penalty, rounded half up to a whole integer and then clamped into the range 0 through 100."
    PRD §3.3: "For a `CONDITION` survey the full age penalty is used; for a `PREVENTIVE` survey the age term is first multiplied by a preventive factor of 0.5 (i.e. the age-in-years times 1.5 times 0.5, still capped at 25), so a preventive survey of the same asset with the same distress reading yields a higher index."

    Design: Difficulty/dual_variant_calc/pci_condition_vs_preventive_diverge
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="ROAD", gis_segment_id="SEG-1",
                       install_date="2020-03-01T00:00:00Z", replacement_value_cents=200000)
    payload = {
        "asset_id": asset["id"], "inspection_type": "CONDITION", "raw_distress_index": 20,
        "scheduled_window_start": "2026-06-01T08:00:00Z", "scheduled_window_end": "2026-06-01T10:00:00Z",
    }
    insp = validate_success(api.create_inspection(payload, inspector_headers("insp-1")), expected_status=201)
    assert insp["computed_pci"] == 71, f"expected CONDITION computed_pci 71, got {insp['computed_pci']}"


def test_pci_preventive_variant_halves_age_penalty(api):
    """PRD §3.3: "For a `CONDITION` survey the full age penalty is used; for a `PREVENTIVE` survey the age term is first multiplied by a preventive factor of 0.5 (i.e. the age-in-years times 1.5 times 0.5, still capped at 25), so a preventive survey of the same asset with the same distress reading yields a higher index."
    PRD §3.3: "the base penalty is the age in years multiplied by 1.5 points per year, capped at a maximum of 25 points."

    Design: Difficulty/dual_variant_calc/pci_condition_vs_preventive_diverge
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="ROAD", gis_segment_id="SEG-1",
                       install_date="2020-03-01T00:00:00Z", replacement_value_cents=200000)
    base = {"asset_id": asset["id"], "raw_distress_index": 20,
            "scheduled_window_start": "2026-06-01T08:00:00Z", "scheduled_window_end": "2026-06-01T10:00:00Z"}
    cond = validate_success(api.create_inspection({**base, "inspection_type": "CONDITION"}, inspector_headers("insp-1")), expected_status=201)
    prev = validate_success(api.create_inspection({**base, "inspection_type": "PREVENTIVE"}, inspector_headers("insp-1")), expected_status=201)
    assert prev["computed_pci"] == 76, f"expected PREVENTIVE computed_pci 76, got {prev['computed_pci']}"
    assert prev["computed_pci"] - cond["computed_pci"] == 5, "preventive survey must exceed condition by 5 here"


# --- Difficulty: condition_state boundary (85 inclusive GOOD) ------------

def test_pci_score_exactly_85_promoted_on_acceptance(api):
    """PRD §3.3: "On a valid acceptance the system records the supervisor in `decided_by`, promotes the inspection's `computed_pci` onto the asset as its new `pci_score`, recomputes the asset's `condition_state` from the thresholds in §3.1, and sets the asset's `last_inspection_at` to the current clock time."

    Design: Difficulty/boundary_precision_check/pci_condition_threshold_85_inclusive_good
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="ROAD", gis_segment_id="SEG-10",
                       install_date="2026-06-01T00:00:00Z", replacement_value_cents=200000)
    insp = create_submitted_inspection(api, asset["id"], inspector_user="insp-3",
                                       inspection_type="CONDITION", raw_distress_index=15)
    assert insp["computed_pci"] == 85, f"expected computed_pci 85, got {insp['computed_pci']}"
    validate_success(api.decide_inspection(insp["id"], {"decision": "ACCEPT"}, supervisor_headers("sup-3")))
    asset = get_success_data(api.get_asset(asset["id"], supervisor_headers()))
    assert asset["pci_score"] == 85, f"expected asset pci_score 85, got {asset['pci_score']}"


def test_condition_state_good_at_score_85_inclusive(api):
    """PRD §3.1: "A score of at least 85 is `GOOD`; a score below 85 but at least 70 is `FAIR`; a score below 70 but at least 55 is `POOR`; anything below 55 is `FAILED`. All three boundaries are inclusive lower bounds."

    Design: Difficulty/boundary_precision_check/pci_condition_threshold_85_inclusive_good
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="ROAD", gis_segment_id="SEG-10",
                       install_date="2026-06-01T00:00:00Z", replacement_value_cents=200000)
    insp = create_submitted_inspection(api, asset["id"], inspector_user="insp-3",
                                       inspection_type="CONDITION", raw_distress_index=15)
    validate_success(api.decide_inspection(insp["id"], {"decision": "ACCEPT"}, supervisor_headers("sup-3")))
    asset = get_success_data(api.get_asset(asset["id"], supervisor_headers()))
    assert asset["condition_state"] == "GOOD", f"expected GOOD at score 85, got {asset['condition_state']}"


# --- Difficulty: transitive cascade (accept FAILED -> WO -> UNDER_REPAIR) -

def test_accept_failed_inspection_sets_pci_and_failed_condition(api):
    """PRD §3.1: "anything below 55 is `FAILED`."
    PRD §3.3: "On a valid acceptance the system records the supervisor in `decided_by`, promotes the inspection's `computed_pci` onto the asset as its new `pci_score`, recomputes the asset's `condition_state` from the thresholds in §3.1, and sets the asset's `last_inspection_at` to the current clock time."

    Design: Difficulty/transitive_cascade/inspection_accept_failed_cascades_workorder_and_asset_repair
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="ROAD", gis_segment_id="SEG-7",
                       install_date="2020-03-01T00:00:00Z", replacement_value_cents=500000)
    insp = create_submitted_inspection(api, asset["id"], inspector_user="insp-2",
                                       inspection_type="CONDITION", raw_distress_index=50)
    assert insp["computed_pci"] == 41, f"expected computed_pci 41, got {insp['computed_pci']}"
    validate_success(api.decide_inspection(insp["id"], {"decision": "ACCEPT"}, supervisor_headers("sup-2")))
    asset = get_success_data(api.get_asset(asset["id"], supervisor_headers()))
    assert asset["pci_score"] == 41, f"expected pci_score 41, got {asset['pci_score']}"
    assert asset["condition_state"] == "FAILED", f"expected FAILED, got {asset['condition_state']}"


def test_accept_failed_inspection_spawns_repair_workorder_and_repairs_asset(api):
    """PRD §3.3: "If the recomputed `condition_state` is `FAILED` and the asset is currently `ACTIVE`, the system auto-creates a repair work order for that asset — with `work_type` `MAINTENANCE`, `origin` `INSPECTION`, and `status` `DRAFT` — which in turn drives the asset `ACTIVE → UNDER_REPAIR`."

    Design: Difficulty/transitive_cascade/inspection_accept_failed_cascades_workorder_and_asset_repair
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="ROAD", gis_segment_id="SEG-7",
                       install_date="2020-03-01T00:00:00Z", replacement_value_cents=500000)
    insp = create_submitted_inspection(api, asset["id"], inspector_user="insp-2",
                                       inspection_type="CONDITION", raw_distress_index=50)
    validate_success(api.decide_inspection(insp["id"], {"decision": "ACCEPT"}, supervisor_headers("sup-2")))
    asset = get_success_data(api.get_asset(asset["id"], supervisor_headers()))
    assert asset["status"] == "UNDER_REPAIR", f"expected UNDER_REPAIR, got {asset['status']}"
    data, _meta = _list_work_orders_for_asset(api, asset["id"])
    assert len(data) == 1, f"expected exactly one auto work order, got {len(data)}"
    wo = data[0]
    assert wo["origin"] == "INSPECTION", f"expected origin INSPECTION, got {wo['origin']}"
    assert wo["work_type"] == "MAINTENANCE", f"expected work_type MAINTENANCE, got {wo['work_type']}"


def _list_work_orders_for_asset(api, asset_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_work_orders(supervisor_headers(), params={"asset_id": asset_id}))


# --- Difficulty: reject/resubmit revision cycle -------------------------

def test_reject_moves_inspection_to_rejected(api):
    """PRD §3.3: "A rejection moves the inspection `SUBMITTED → REJECTED`, recording the deciding supervisor's `X-User-ID` in `decided_by`; the inspector may then revise and resubmit, which moves it `REJECTED → SUBMITTED` again (this revision loop is the only way back out of `REJECTED`)."

    Design: Difficulty/non_linear_state_machine/inspection_reject_resubmit_cycle
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="SIGN", gis_segment_id="SEG-6", replacement_value_cents=40000)
    insp = create_submitted_inspection(api, asset["id"], inspector_user="insp-9",
                                       inspection_type="CONDITION", raw_distress_index=30)
    rejected = validate_success(api.decide_inspection(insp["id"], {"decision": "REJECT"}, supervisor_headers("sup-1")))
    assert rejected["status"] == "REJECTED", f"expected REJECTED, got {rejected['status']}"
    assert rejected["decided_by"] == "sup-1", f"expected decided_by sup-1, got {rejected['decided_by']}"


def test_resubmit_after_reject_returns_to_submitted(api):
    """PRD §3.3: "A rejection moves the inspection `SUBMITTED → REJECTED`, recording the deciding supervisor's `X-User-ID` in `decided_by`; the inspector may then revise and resubmit, which moves it `REJECTED → SUBMITTED` again (this revision loop is the only way back out of `REJECTED`)."

    Design: Difficulty/non_linear_state_machine/inspection_reject_resubmit_cycle
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="SIGN", gis_segment_id="SEG-6", replacement_value_cents=40000)
    insp = create_submitted_inspection(api, asset["id"], inspector_user="insp-9",
                                       inspection_type="CONDITION", raw_distress_index=30)
    validate_success(api.decide_inspection(insp["id"], {"decision": "REJECT"}, supervisor_headers("sup-1")))
    resubmitted = validate_success(api.submit_inspection(insp["id"], inspector_headers("insp-9")))
    assert resubmitted["status"] == "SUBMITTED", f"expected SUBMITTED after resubmit, got {resubmitted['status']}"


# --- Corner: validation / state / segregation ---------------------------

def test_inspection_missing_raw_distress_index_returns_validation(api):
    """PRD §2.6: "Body well-formedness — all required fields present, enum values legal, and numeric ranges satisfied ... else `ERR_VALIDATION` (400)."
    PRD §3.3: "declaring the `inspection_type` (`PREVENTIVE` or `CONDITION`), the field-measured `raw_distress_index` (a number from 0 to 100 inclusive, where higher means worse), and the planned `scheduled_window_start` and `scheduled_window_end`."

    Design: Corner/entities/inspection_missing_required_field_returns_validation
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-A2")
    payload = {
        "asset_id": asset["id"], "inspection_type": "CONDITION",
        "scheduled_window_start": "2026-03-01T08:00:00Z", "scheduled_window_end": "2026-03-01T09:00:00Z",
    }
    resp = api.create_inspection(payload, inspector_headers("insp-x"))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_inspection_decision_on_draft_returns_invalid_state(api):
    """PRD §3.3: "A `Supervisor` then adjudicates the submitted inspection by supplying a `decision` of `ACCEPT` or `REJECT`."
    PRD §2.6: "Legal state — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/inspection_decision_on_draft_returns_invalid_state
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-A7")
    payload = {
        "asset_id": asset["id"], "inspection_type": "CONDITION", "raw_distress_index": 10,
        "scheduled_window_start": "2026-03-01T08:00:00Z", "scheduled_window_end": "2026-03-01T09:00:00Z",
    }
    insp = validate_success(api.create_inspection(payload, inspector_headers("insp-x")), expected_status=201)
    resp = api.decide_inspection(insp["id"], {"decision": "ACCEPT"}, supervisor_headers("sup-x"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_supervisor_cannot_accept_own_inspection(api):
    """PRD §3.3: "The deciding supervisor's `X-User-ID` must differ from the inspection's `inspector_id`: an operator may not accept their own inspection, and a self-decision is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_of_duties_same_user_accepts_own_inspection_rejected
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-B6")
    insp = create_submitted_inspection(api, asset["id"], inspector_user="dual-1",
                                       inspection_type="CONDITION", raw_distress_index=10)
    resp = api.decide_inspection(insp["id"], {"decision": "ACCEPT"}, supervisor_headers("dual-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

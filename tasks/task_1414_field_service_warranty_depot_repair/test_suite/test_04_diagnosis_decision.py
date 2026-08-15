"""Repair-versus-replace decision threshold, routing, and manager override."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_model,
    create_customer,
    create_failure_code,
    create_part,
    create_unit,
    create_draft_rma,
    authorize_rma,
    diagnose_rma,
    make_depot_manager_headers,
    planned_part_line,
    receive_rma,
    setup_triaged_rma,
    triage_rma,
    validate_error,
    validate_success,
)


def _setup_two_triaged_rmas():
    """Two in-warranty units of the same model, both triaged with one code."""
    model = create_model()
    customer = create_customer()
    fc = create_failure_code()
    part = create_part()
    rmas = {}
    for label in ("A", "B"):
        unit = create_unit(model["id"], customer["id"], serial_number=f"SN-D-{label}")
        rma = create_draft_rma(customer["id"], unit["id"],
                               reported_issue=f"dead {label}")
        authorize_rma(rma["id"])
        receive_rma(rma["id"], unit["serial_number"])
        triage_rma(rma["id"], fc["id"])
        rmas[label] = rma
    return model, part, rmas


def test_estimate_at_threshold_decides_replace(api):
    """PRD §3.4: "The threshold is the model's `replacement_cost_cents`
    multiplied by `replace_threshold_pct` and divided by 100, with any
    fractional cent discarded."
    PRD §3.4: "Otherwise, when the `final_estimate_cents` is at or above the
    threshold — exact equality is replacement, the comparison is inclusive — the
    decision is `REPLACE`."
    PRD §3.4: "A `REPLACE` decision routes to `REPLACEMENT_PENDING` regardless
    of coverage."

    Design: Difficulty/combinatorial_formula/decision_threshold_nested_inputs
    """
    model, part, rmas = _setup_two_triaged_rmas()
    # 250 * 200 + 2 * 5000 = 60000 == floor(100000 * 60 / 100)
    diagnosed_a = diagnose_rma(
        rmas["A"]["id"], labor_minutes_est=250,
        planned_parts=[planned_part_line(part["id"], 2)])
    assert diagnosed_a["final_estimate_cents"] == 60000, (
        f"final estimate must be 60000, got {diagnosed_a['final_estimate_cents']}")
    assert diagnosed_a["decision"] == "REPLACE", (
        f"estimate at the threshold must decide REPLACE, got {diagnosed_a['decision']}")
    assert diagnosed_a["status"] == "REPLACEMENT_PENDING"


def test_estimate_below_threshold_decides_repair(api):
    """PRD §3.4: "Otherwise, when the `final_estimate_cents` is at or above the
    threshold — exact equality is replacement, the comparison is inclusive — the
    decision is `REPLACE`. In every remaining case the decision is `REPAIR`."
    PRD §3.4: "A `REPAIR` decision on an RMA whose `coverage_path` is
    `IN_WARRANTY` or `GOODWILL_FULL` routes straight to `IN_REPAIR`."

    Design: Difficulty/combinatorial_formula/decision_threshold_nested_inputs
    """
    model, part, rmas = _setup_two_triaged_rmas()
    # 249 * 200 + 2 * 5000 = 59800 < 60000
    diagnosed_b = diagnose_rma(
        rmas["B"]["id"], labor_minutes_est=249,
        planned_parts=[planned_part_line(part["id"], 2)])
    assert diagnosed_b["final_estimate_cents"] == 59800, (
        f"final estimate must be 59800, got {diagnosed_b['final_estimate_cents']}")
    assert diagnosed_b["decision"] == "REPAIR", (
        f"estimate below the threshold must decide REPAIR, got {diagnosed_b['decision']}")
    assert diagnosed_b["status"] == "IN_REPAIR"


def test_final_estimate_exactly_at_threshold_is_replace(api):
    """PRD §3.4: "Otherwise, when the `final_estimate_cents` is at or above the
    threshold — exact equality is replacement, the comparison is inclusive — the
    decision is `REPLACE`."

    Design: Difficulty/boundary_precision_check/decision_threshold_exact_equality
    """
    ctx = setup_triaged_rma()
    diagnosed = diagnose_rma(
        ctx["rma"]["id"], labor_minutes_est=250,
        planned_parts=[planned_part_line(ctx["part"]["id"], 2)])
    assert diagnosed["final_estimate_cents"] == 60000, (
        f"250*200 + 2*5000 must equal the 60000 threshold exactly, got "
        f"{diagnosed['final_estimate_cents']}")
    assert diagnosed["decision"] == "REPLACE", (
        "exact equality with the threshold is replacement (inclusive), got "
        f"{diagnosed['decision']}")


def test_threshold_equality_routes_to_replacement_pending(api):
    """PRD §3.4: "A `REPLACE` decision routes to `REPLACEMENT_PENDING`
    regardless of coverage."
    PRD §3.4: "The threshold is the model's `replacement_cost_cents` multiplied
    by `replace_threshold_pct` and divided by 100, with any fractional cent
    discarded."

    Design: Difficulty/boundary_precision_check/decision_threshold_exact_equality
    """
    ctx = setup_triaged_rma()
    diagnosed = diagnose_rma(
        ctx["rma"]["id"], labor_minutes_est=250,
        planned_parts=[planned_part_line(ctx["part"]["id"], 2)])
    assert diagnosed["status"] == "REPLACEMENT_PENDING", (
        f"REPLACE must auto-route to REPLACEMENT_PENDING, got {diagnosed['status']}")
    assert diagnosed["repairability"] == "REPAIRABLE"
    assert diagnosed["diagnosed_by"] == "tech-1"


def test_override_decision_segregation_then_success(api):
    """PRD §2.9: "A manager overriding the repair-versus-replace decision must
    not be the technician recorded in the RMA's `diagnosed_by`."
    PRD §3.4: "Overriding a `REPLACEMENT_PENDING` RMA to `REPAIR` sets
    `decision` to `REPAIR`, raises `decision_overridden` to true, and re-fires
    the auto-route: covered coverage paths proceed to `IN_REPAIR`, while
    `OUT_OF_WARRANTY` or `GOODWILL_PARTIAL` route to `AWAITING_QUOTE_APPROVAL`
    with an auto-created quote as above."

    Design: Corner/validations/override_decision_segregation_then_success
    """
    ctx = setup_triaged_rma()
    diagnosed = diagnose_rma(ctx["rma"]["id"], labor_minutes_est=30,
                             repairability="BER", planned_parts=[])
    assert diagnosed["decision"] == "REPLACE"
    assert diagnosed["status"] == "REPLACEMENT_PENDING"
    assert diagnosed["diagnosed_by"] == "tech-1"

    # The diagnosing identity may not override its own decision.
    self_override = api.override_decision(
        ctx["rma"]["id"],
        {"new_decision": "REPAIR", "reason": "self override attempt"},
        make_depot_manager_headers("tech-1"))
    validate_error(self_override, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert self_override.status_code == 403

    # A different manager overrides successfully and the RMA re-routes.
    res = api.override_decision(
        ctx["rma"]["id"],
        {"new_decision": "REPAIR", "reason": "manager review"},
        make_depot_manager_headers("mgr-9"))
    overridden = validate_success(res, 200)
    assert overridden["decision"] == "REPAIR"
    assert overridden["decision_overridden"] is True
    assert overridden["status"] == "IN_REPAIR", (
        f"in-warranty override to REPAIR must re-route to IN_REPAIR, got "
        f"{overridden['status']}")


def test_engineering_lead_cannot_diagnose(api):
    """PRD §2.1: "A request whose role is recognized but not listed among the
    roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4: POST /depot/rmas/{rmaId}/diagnose is authorized for DepotTechnician
    only.

    Design: Corner/rbac/engineering_lead_cannot_diagnose
    """
    ctx = setup_triaged_rma()
    res = api.diagnose_rma(ctx["rma"]["id"],
                           {"labor_minutes_est": 10, "repairability": "REPAIRABLE",
                            "planned_parts": []},
                           TEST_USERS["engineering_lead_headers"])
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert res.status_code == 403

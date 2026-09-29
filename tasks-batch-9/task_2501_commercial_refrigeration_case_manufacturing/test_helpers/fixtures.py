"""Composite setup helpers.

The service is a long chain — refrigerant, design, airflow model, lab test,
label, store plan, pricing, approval, plant release, fabrication, shipment,
install booking, handoff, depot stock, warranty claim — and almost every
interesting rule lives several links down that chain. The helpers below build
each link once and compose upward, so a test only has to describe the state it
needs and then assert.

Every helper accepts the same keyword bag and forwards what it does not own to
the helper beneath it, so ``setup_reserved_claim(line_overrides={"quantity": 2})``
threads a line override all the way from the top of the chain to the bottom.
The bottom-most helper asserts the bag is empty, so a misspelled keyword fails
loudly instead of silently doing nothing.

Recognised keywords
    refrigerant_overrides / standard_overrides / chamber_overrides   catalogue rows
    extra_refrigerants / extra_standards / extra_chambers            lists of overrides
    model_overrides, run_airflow                                    the case design
    test_overrides, completion_overrides                            the lab test
    label_overrides                                                 the compliance label
    plan_overrides, line_overrides, extra_lines                     the store plan
    complete_units                                                  how many units pass QA
    shipment_overrides                                              the shipment
    crew_overrides, extra_crews, booking_overrides, create_booking   install reservation
    handoff_at, received_by_name                                    the handoff
    part_overrides, claim_overrides, claim_clock                     depot stock + claim
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    complete_energy_test_payload,
    create_case_model_payload,
    create_compliance_label_payload,
    create_energy_standard_payload,
    create_energy_test_payload,
    create_install_booking_payload,
    create_install_crew_payload,
    create_part_inventory_payload,
    create_refrigerant_payload,
    create_shipment_payload,
    create_store_plan_line_payload,
    create_store_plan_payload,
    create_test_chamber_payload,
    create_warranty_claim_payload,
    engineering_change_payload,
    qa_result_payload,
)
from .test_users import TEST_USERS, make_install_contractor_headers

ADMIN = TEST_USERS["platform_admin_headers"]
ENGINEER = TEST_USERS["design_engineer_headers"]
TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
OFFICER_ALT = TEST_USERS["compliance_officer_alt_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
SALES_ALT = TEST_USERS["sales_engineer_alt_headers"]
SUPERVISOR = TEST_USERS["plant_supervisor_headers"]
COORDINATOR = TEST_USERS["logistics_coordinator_headers"]
SERVICE = TEST_USERS["service_manager_headers"]

Scenario = Dict[str, Any]


def _pop(bag: Dict[str, Any], key: str, default: Any = None) -> Any:
    value = bag.pop(key, None)
    return default if value is None else value


# ─── Single-row seeding ────────────────────────────────────────────────────


def set_logical_clock(instant: str) -> Dict:
    """Move the logical UTC clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": instant}, ADMIN))


def seed_refrigerant(**overrides) -> Dict:
    return get_success_data(
        api_client.create_refrigerant(create_refrigerant_payload(**overrides), ADMIN)
    )


def seed_low_gwp_refrigerant(**overrides) -> Dict:
    """The lower-GWP blend an engineering change transitions a design onto."""
    defaults = {
        "refrigerant_code": TEST_DEFAULTS["LOW_GWP_REFRIGERANT_CODE"],
        "trade_name": TEST_DEFAULTS["LOW_GWP_TRADE_NAME"],
        "gwp_100yr": TEST_DEFAULTS["LOW_GWP"],
        "safety_class": "A2L",
        "max_charge_grams": 8000,
    }
    defaults.update(overrides)
    return seed_refrigerant(**defaults)


def seed_energy_standard(**overrides) -> Dict:
    return get_success_data(
        api_client.create_energy_standard(
            create_energy_standard_payload(**overrides), OFFICER
        )
    )


def seed_test_chamber(**overrides) -> Dict:
    return get_success_data(
        api_client.create_test_chamber(create_test_chamber_payload(**overrides), ADMIN)
    )


def seed_install_crew(**overrides) -> Dict:
    return get_success_data(
        api_client.create_install_crew(create_install_crew_payload(**overrides), COORDINATOR)
    )


def seed_part_inventory(case_model_id: str, **overrides) -> Dict:
    return get_success_data(
        api_client.create_part_inventory(
            create_part_inventory_payload(case_model_id, **overrides), SERVICE
        )
    )


# ─── Live re-reads ────────────────────────────────────────────────────────


def refresh_case_model(ctx: Scenario) -> Dict:
    ctx["case_model"] = get_success_data(
        api_client.get_case_model(ctx["case_model"]["id"], ENGINEER)
    )
    ctx["case_model_version"] = ctx["case_model"]["version"]
    return ctx["case_model"]


def refresh_energy_test(ctx: Scenario) -> Dict:
    ctx["energy_test"] = get_success_data(
        api_client.get_energy_test(ctx["energy_test"]["id"], TECHNICIAN)
    )
    return ctx["energy_test"]


def refresh_compliance_label(ctx: Scenario) -> Dict:
    ctx["compliance_label"] = get_success_data(
        api_client.get_compliance_label(ctx["compliance_label"]["id"], OFFICER)
    )
    return ctx["compliance_label"]


def refresh_store_plan(ctx: Scenario) -> Dict:
    ctx["store_plan"] = get_success_data(
        api_client.get_store_plan(ctx["store_plan"]["id"], SALES)
    )
    ctx["store_plan_version"] = ctx["store_plan"]["version"]
    return ctx["store_plan"]


def refresh_work_orders(ctx: Scenario) -> List[Dict]:
    data = get_success_data(
        api_client.list_work_orders(
            SUPERVISOR, params={"store_plan_id": ctx["store_plan"]["id"], "limit": 100}
        )
    )
    ctx["work_orders"] = data
    return data


def refresh_shipment(ctx: Scenario) -> Dict:
    ctx["shipment"] = get_success_data(
        api_client.get_shipment(ctx["shipment"]["id"], COORDINATOR)
    )
    return ctx["shipment"]


def refresh_install_crew(ctx: Scenario) -> Dict:
    ctx["install_crew"] = get_success_data(
        api_client.get_install_crew(ctx["install_crew"]["id"], COORDINATOR)
    )
    return ctx["install_crew"]


def refresh_install_booking(ctx: Scenario) -> Dict:
    ctx["install_booking"] = get_success_data(
        api_client.get_install_booking(ctx["install_booking"]["id"], COORDINATOR)
    )
    return ctx["install_booking"]


def refresh_part_inventory(ctx: Scenario) -> Dict:
    ctx["part_inventory"] = get_success_data(
        api_client.get_part_inventory(ctx["part_inventory"]["id"], SERVICE)
    )
    return ctx["part_inventory"]


def refresh_warranty_claim(ctx: Scenario) -> Dict:
    ctx["warranty_claim"] = get_success_data(
        api_client.get_warranty_claim(ctx["warranty_claim"]["id"], SERVICE)
    )
    return ctx["warranty_claim"]


# ─── Tier 1–3: walking the chain ─────────────────────────────────────────


def setup_catalogue(**kw) -> Scenario:
    """One refrigerant blend, one energy standard and one psychrometric chamber."""
    refrigerant_overrides = _pop(kw, "refrigerant_overrides", {})
    standard_overrides = _pop(kw, "standard_overrides", {})
    chamber_overrides = _pop(kw, "chamber_overrides", {})
    extra_refrigerants = _pop(kw, "extra_refrigerants", [])
    extra_standards = _pop(kw, "extra_standards", [])
    extra_chambers = _pop(kw, "extra_chambers", [])
    assert not kw, f"Unrecognised setup keywords: {sorted(kw)}"

    ctx: Scenario = {}
    ctx["refrigerant"] = seed_refrigerant(**refrigerant_overrides)
    ctx["energy_standard"] = seed_energy_standard(**standard_overrides)
    ctx["test_chamber"] = seed_test_chamber(**chamber_overrides)
    ctx["extra_refrigerants"] = [seed_refrigerant(**o) for o in extra_refrigerants]
    ctx["extra_standards"] = [seed_energy_standard(**o) for o in extra_standards]
    ctx["extra_chambers"] = [seed_test_chamber(**o) for o in extra_chambers]
    return ctx


def setup_draft_case_model(**kw) -> Scenario:
    """A case design in DRAFT at design_revision 1."""
    model_overrides = _pop(kw, "model_overrides", {})
    ctx = setup_catalogue(**kw)
    payload = create_case_model_payload(ctx["refrigerant"]["id"], **model_overrides)
    ctx["case_model_payload"] = payload
    ctx["case_model"] = get_success_data(api_client.create_case_model(payload, ENGINEER))
    ctx["case_model_version"] = ctx["case_model"]["version"]
    return ctx


def setup_modeled_case_model(**kw) -> Scenario:
    """A case design whose airflow and charge models have been run (MODELED)."""
    ctx = setup_draft_case_model(**kw)
    ctx["case_model"] = get_success_data(
        api_client.run_airflow_model(ctx["case_model"]["id"], ENGINEER)
    )
    ctx["case_model_version"] = ctx["case_model"]["version"]
    return ctx


def setup_submitted_case_model(**kw) -> Scenario:
    """A design submitted to the lab (SUBMITTED_FOR_TEST)."""
    ctx = setup_modeled_case_model(**kw)
    ctx["case_model"] = get_success_data(
        api_client.submit_case_model_for_test(ctx["case_model"]["id"], ENGINEER)
    )
    ctx["case_model_version"] = ctx["case_model"]["version"]
    return ctx


def schedule_energy_test(ctx: Scenario, **overrides):
    """Schedule a test against the live case model version. Returns the response."""
    payload = create_energy_test_payload(
        overrides.pop("case_model_id", ctx["case_model"]["id"]),
        overrides.pop("test_chamber_id", ctx["test_chamber"]["id"]),
        overrides.pop("energy_standard_id", ctx["energy_standard"]["id"]),
        overrides.pop("expected_case_model_version", ctx["case_model_version"]),
        **overrides,
    )
    return api_client.create_energy_test(payload, TECHNICIAN)


def setup_scheduled_energy_test(**kw) -> Scenario:
    """A SCHEDULED energy test holding chamber time against a submitted design."""
    test_overrides = _pop(kw, "test_overrides", {})
    ctx = setup_submitted_case_model(**kw)
    ctx["energy_test"] = get_success_data(schedule_energy_test(ctx, **test_overrides))
    refresh_case_model(ctx)
    return ctx


def setup_running_energy_test(**kw) -> Scenario:
    """A RUNNING energy test."""
    ctx = setup_scheduled_energy_test(**kw)
    ctx["energy_test"] = get_success_data(
        api_client.start_energy_test(ctx["energy_test"]["id"], TECHNICIAN)
    )
    return ctx


def setup_completed_energy_test(**kw) -> Scenario:
    """A completed energy test; the design lands in TESTED_PASS or TESTED_FAIL."""
    completion_overrides = _pop(kw, "completion_overrides", {})
    ctx = setup_running_energy_test(**kw)
    ctx["energy_test"] = get_success_data(
        api_client.complete_energy_test(
            ctx["energy_test"]["id"],
            complete_energy_test_payload(**completion_overrides),
            TECHNICIAN,
        )
    )
    refresh_case_model(ctx)
    return ctx


def setup_certified_case_model(**kw) -> Scenario:
    """A CERTIFIED design carrying an ISSUED energy label."""
    label_overrides = _pop(kw, "label_overrides", {})
    ctx = setup_completed_energy_test(**kw)
    ctx["compliance_label"] = get_success_data(
        api_client.create_compliance_label(
            create_compliance_label_payload(
                ctx["case_model"]["id"], ctx["energy_test"]["id"], **label_overrides
            ),
            OFFICER,
        )
    )
    refresh_case_model(ctx)
    return ctx


def add_line(ctx: Scenario, **overrides):
    """Add a configured line to the scenario's plan. Returns the response."""
    payload = create_store_plan_line_payload(
        overrides.pop("case_model_id", ctx["case_model"]["id"]), **overrides
    )
    return api_client.add_store_plan_line(ctx["store_plan"]["id"], payload, SALES)


def setup_plan_with_line(**kw) -> Scenario:
    """A DRAFT store plan holding one configured line of the certified design."""
    plan_overrides = _pop(kw, "plan_overrides", {})
    line_overrides = _pop(kw, "line_overrides", {})
    extra_lines = _pop(kw, "extra_lines", [])
    ctx = setup_certified_case_model(**kw)
    ctx["store_plan"] = get_success_data(
        api_client.create_store_plan(create_store_plan_payload(**plan_overrides), SALES)
    )
    ctx["store_plan_lines"] = [get_success_data(add_line(ctx, **line_overrides))]
    for extra in extra_lines:
        ctx["store_plan_lines"].append(get_success_data(add_line(ctx, **extra)))
    ctx["store_plan_line"] = ctx["store_plan_lines"][0]
    refresh_store_plan(ctx)
    return ctx


def setup_priced_plan(**kw) -> Scenario:
    """A PRICED store plan carrying the full six-step roll-up."""
    ctx = setup_plan_with_line(**kw)
    ctx["store_plan"] = get_success_data(
        api_client.price_store_plan(ctx["store_plan"]["id"], SALES)
    )
    ctx["store_plan_version"] = ctx["store_plan"]["version"]
    ctx["store_plan_line"] = get_success_data(
        api_client.get_store_plan_line(ctx["store_plan_line"]["id"], SALES)
    )
    return ctx


def setup_approved_plan(**kw) -> Scenario:
    """An APPROVED store plan (priced by sales-001, approved by sales-002)."""
    ctx = setup_priced_plan(**kw)
    ctx["store_plan"] = get_success_data(
        api_client.approve_store_plan(ctx["store_plan"]["id"], SALES_ALT)
    )
    ctx["store_plan_version"] = ctx["store_plan"]["version"]
    return ctx


def setup_released_plan(**kw) -> Scenario:
    """A plan released to the plant, with one QUEUED work order per ordered case."""
    ctx = setup_approved_plan(**kw)
    ctx["store_plan"] = get_success_data(
        api_client.release_store_plan(ctx["store_plan"]["id"], SUPERVISOR)
    )
    ctx["store_plan_version"] = ctx["store_plan"]["version"]
    refresh_work_orders(ctx)
    return ctx


def drive_unit_to_final_qa(work_order_id: str) -> Dict:
    """Advance one case through fabrication until it reaches FINAL_QA."""
    unit = get_success_data(api_client.get_work_order(work_order_id, SUPERVISOR))
    for _ in range(5):
        if unit["status"] == "FINAL_QA":
            return unit
        unit = get_success_data(api_client.advance_work_order(work_order_id, SUPERVISOR))
    assert unit["status"] == "FINAL_QA", (
        f"work order did not reach FINAL_QA, stuck at {unit['status']}"
    )
    return unit


def complete_unit(work_order_id: str) -> Dict:
    """Advance one case to FINAL_QA and record a passing QA result."""
    drive_unit_to_final_qa(work_order_id)
    return get_success_data(
        api_client.record_qa_result(work_order_id, qa_result_payload("PASS"), SUPERVISOR)
    )


def setup_plan_with_completed_units(**kw) -> Scenario:
    """A released plan whose first `complete_units` cases have passed final QA.

    `complete_units` defaults to every unit on the plan.
    """
    complete_units: Optional[int] = kw.pop("complete_units", None)
    ctx = setup_released_plan(**kw)
    targets = ctx["work_orders"]
    if complete_units is not None:
        targets = targets[:complete_units]
    for unit in targets:
        complete_unit(unit["id"])
    refresh_work_orders(ctx)
    refresh_store_plan(ctx)
    return ctx


def create_shipment_for_plan(ctx: Scenario, **overrides):
    """Create a shipment against the live plan version. Returns the response."""
    refresh_store_plan(ctx)
    payload = create_shipment_payload(
        overrides.pop("store_plan_id", ctx["store_plan"]["id"]),
        overrides.pop("expected_store_plan_version", ctx["store_plan_version"]),
        **overrides,
    )
    return api_client.create_shipment(payload, COORDINATOR)


def setup_staged_shipment(**kw) -> Scenario:
    """A STAGED shipment loaded with every COMPLETE unit of the plan."""
    shipment_overrides = _pop(kw, "shipment_overrides", {})
    kw.setdefault("complete_units", None)
    ctx = setup_plan_with_completed_units(**kw)
    ctx["shipment"] = get_success_data(create_shipment_for_plan(ctx, **shipment_overrides))
    refresh_store_plan(ctx)
    refresh_work_orders(ctx)
    return ctx


def book_crew(ctx: Scenario, **overrides):
    """Reserve an install crew against the scenario's shipment. Returns response."""
    payload = create_install_booking_payload(
        overrides.pop("shipment_id", ctx["shipment"]["id"]),
        overrides.pop("install_crew_id", ctx["install_crew"]["id"]),
        **overrides,
    )
    return api_client.create_install_booking(payload, COORDINATOR)


def setup_booked_shipment(**kw) -> Scenario:
    """A STAGED shipment with an install crew registered and reserved."""
    crew_overrides = _pop(kw, "crew_overrides", {})
    extra_crews = _pop(kw, "extra_crews", [])
    booking_overrides = _pop(kw, "booking_overrides", {})
    create_booking = kw.pop("create_booking", True)
    ctx = setup_staged_shipment(**kw)
    ctx["install_crew"] = seed_install_crew(**crew_overrides)
    ctx["extra_crews"] = [seed_install_crew(**o) for o in extra_crews]
    if create_booking:
        ctx["install_booking"] = get_success_data(book_crew(ctx, **booking_overrides))
        refresh_install_crew(ctx)
    return ctx


def advance_shipment_to_delivered(shipment_id: str) -> Dict:
    """Walk a shipment STAGED → LOADED → IN_TRANSIT → DELIVERED."""
    data: Dict = {}
    for _ in range(3):
        data = get_success_data(api_client.advance_shipment(shipment_id, COORDINATOR))
    return data


def setup_delivered_shipment(**kw) -> Scenario:
    """A DELIVERED shipment with its crew reservation in place."""
    ctx = setup_booked_shipment(**kw)
    ctx["shipment"] = advance_shipment_to_delivered(ctx["shipment"]["id"])
    return ctx


def setup_handed_off_shipment(**kw) -> Scenario:
    """A HANDED_OFF shipment: the clock sits inside the booking window and the
    reserved crew has signed for the delivery, so every unit's warranty has started.
    """
    handoff_at = _pop(kw, "handoff_at", TEST_DEFAULTS["HANDOFF_INSTANT"])
    received_by_name = _pop(kw, "received_by_name", "Dana Ruiz")
    ctx = setup_delivered_shipment(**kw)
    set_logical_clock(handoff_at)
    ctx["handoff_at"] = handoff_at
    ctx["shipment"] = get_success_data(
        api_client.handoff_shipment(
            ctx["shipment"]["id"],
            {"received_by_name": received_by_name},
            make_install_contractor_headers(ctx["install_crew"]["id"]),
        )
    )
    refresh_work_orders(ctx)
    refresh_install_crew(ctx)
    refresh_install_booking(ctx)
    return ctx


# ─── Tier 4–5: depot stock, warranty claims, terminal states ─────────────


def open_claim(ctx: Scenario, **overrides):
    """Open a warranty claim against the scenario's first unit. Returns response."""
    payload = create_warranty_claim_payload(
        overrides.pop("work_order_id", ctx["work_orders"][0]["id"]),
        overrides.pop("part_inventory_id", ctx["part_inventory"]["id"]),
        overrides.pop("install_crew_id", ctx["install_crew"]["id"]),
        **overrides,
    )
    return api_client.create_warranty_claim(payload, SERVICE)


def setup_open_claim(**kw) -> Scenario:
    """A handed-off unit, a regional depot row for its model, and an OPEN claim."""
    part_overrides = _pop(kw, "part_overrides", {})
    claim_overrides = _pop(kw, "claim_overrides", {})
    claim_clock = kw.pop("claim_clock", None)
    ctx = setup_handed_off_shipment(**kw)
    ctx["part_inventory"] = seed_part_inventory(ctx["case_model"]["id"], **part_overrides)
    if claim_clock is not None:
        set_logical_clock(claim_clock)
        ctx["claim_clock"] = claim_clock
    ctx["warranty_claim"] = get_success_data(open_claim(ctx, **claim_overrides))
    refresh_part_inventory(ctx)
    return ctx


def setup_reserved_claim(**kw) -> Scenario:
    """A warranty claim in PARTS_RESERVED with depot stock withheld."""
    ctx = setup_open_claim(**kw)
    ctx["warranty_claim"] = get_success_data(
        api_client.reserve_claim_parts(ctx["warranty_claim"]["id"], SERVICE)
    )
    refresh_part_inventory(ctx)
    refresh_store_plan(ctx)
    return ctx


# ─── Cascade triggers used as setup by several tests ─────────────────────


def revoke_label(ctx: Scenario, revocation_reason: str = "Label withdrawn for retest"):
    """Revoke the scenario's issued label. Returns the response."""
    return api_client.revoke_compliance_label(
        ctx["compliance_label"]["id"], {"revocation_reason": revocation_reason}, OFFICER
    )


def open_engineering_change(ctx: Scenario, **overrides):
    """File an engineering change against the scenario's design. Returns response."""
    refrigerant_id = overrides.pop("refrigerant_id", None)
    if refrigerant_id is None:
        if not ctx.get("extra_refrigerants"):
            ctx.setdefault("extra_refrigerants", []).append(seed_low_gwp_refrigerant())
        refrigerant_id = ctx["extra_refrigerants"][0]["id"]
    payload = engineering_change_payload(refrigerant_id, **overrides)
    return api_client.open_engineering_change(ctx["case_model"]["id"], payload, ENGINEER)


def setup_plan_on_compliance_hold(**kw) -> Scenario:
    """An APPROVED plan pushed into HOLD_PENDING_RECERT by revoking the label of
    the model its line orders.
    """
    ctx = setup_approved_plan(**kw)
    get_success_data(revoke_label(ctx))
    refresh_compliance_label(ctx)
    refresh_case_model(ctx)
    refresh_store_plan(ctx)
    ctx["store_plan_line"] = get_success_data(
        api_client.get_store_plan_line(ctx["store_plan_line"]["id"], SALES)
    )
    return ctx

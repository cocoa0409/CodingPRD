"""
Four requests that each break two rules at once. In every case both conditions
are genuinely true, and the answer that comes back has to be the one the
validation order names — never the cheaper query, never the louder status code.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def test_a_booking_from_the_wrong_stage_into_a_humid_booth_reports_the_stage(api, chain_b):
    """
    The order never left the machine shop and the booth is genuinely too humid,
    yet the refusal names the stage, because an instrument that is not yet in
    assembly has no business asking for a booth at all.

    PRD: "**State outranks climate.** A finish-run booking whose order is in the
    wrong build stage *and* whose booth is `OUT_OF_SPEC` returns
    `ERR_BUILD_STAGE_INVALID`, never `ERR_ROOM_CLIMATE_OUT_OF_SPEC`."

    Design: Difficulty/priority_pair_validation_conflict/p1_build_stage_state_check_outranks_booth_climate_posture
    """
    booth = F.log_climate_reading(api, chain_b["fb1"], 60.0, 22.0,
                                  U.FINISH_TECH_HEADERS)
    assert booth["climate_status"] == "OUT_OF_SPEC"

    order = validate_success(
        api.get_build_order(chain_b["bo1"], U.COORDINATOR_HEADERS))
    assert order["build_stage"] == "COMPONENTS_RELEASED"

    validate_error(api.create_finish_run({
        "build_order_id": chain_b["bo1"], "booth_id": chain_b["fb1"],
        "finish_system": "NITRO", "coat_count": 8,
        "expected_build_order_version": order["version"],
    }, U.FINISH_TECH_HEADERS), E.ERR_BUILD_STAGE_INVALID, 409)


def test_the_refused_booking_leaves_no_run_and_does_not_report_the_climate(api, chain_b):
    """
    Only one error body comes back and it is not the climate one, so the losing
    rule is genuinely suppressed rather than merged in, and no run row survives
    the refusal.

    PRD: "The governing room must be `IN_SPEC`. Violation:
    `ERR_ROOM_CLIMATE_OUT_OF_SPEC` (409), or `ERR_ROOM_QUARANTINED` (409) when
    the room's posture is the stricter `QUARANTINED`."

    Design: Difficulty/priority_pair_validation_conflict/p1_build_stage_state_check_outranks_booth_climate_posture
    """
    F.log_climate_reading(api, chain_b["fb1"], 60.0, 22.0, U.FINISH_TECH_HEADERS)
    order = validate_success(
        api.get_build_order(chain_b["bo1"], U.COORDINATOR_HEADERS))

    response = api.create_finish_run({
        "build_order_id": chain_b["bo1"], "booth_id": chain_b["fb1"],
        "finish_system": "NITRO", "coat_count": 8,
        "expected_build_order_version": order["version"],
    }, U.FINISH_TECH_HEADERS)
    body = response.json()
    assert body["data"]["error_id"] != E.ERR_ROOM_CLIMATE_OUT_OF_SPEC

    runs, _ = validate_paginated(api.list_finish_runs(
        U.FINISH_TECH_HEADERS, {"build_order_id": chain_b["bo1"]}))
    assert runs == []


def a_serialized_instrument_with_a_withdrawn_permit(api, env):
    """
    Carry the thin-deposit order all the way to a minted serial number, raise a
    Japanese shipment against it with its permit attached, and only then have the
    contributing rosewood permit withdrawn.
    """
    version = F.start_assembly(api, env["bo1"])["version"]
    F.log_climate_reading(api, env["fb1"], 50.0, 21.0, U.FINISH_TECH_HEADERS)
    env["fr1"] = F.create_finish_run(api, env["bo1"], env["fb1"], version,
                                     finish_system="NITRO", coat_count=8)["id"]
    F.complete_spray(api, env["fr1"])
    F.set_clock(api, "2026-08-16T00:00:00Z")
    env["clock"] = "2026-08-16T00:00:00Z"
    F.buff_run(api, env["fr1"])
    F.complete_run(api, env["fr1"])
    F.record_fretwork(api, env["bo1"])
    F.record_setup(api, env["bo1"])
    inspection = F.open_inspection(api, env["bo1"], U.LUTHIER_HEADERS)["id"]
    F.measure_inspection(api, inspection, F.measurement_payload(
        action_mm_treble=1.70, action_mm_bass=2.10, relief_mm=0.20,
        intonation_cents_max=4.8), U.LUTHIER_HEADERS)
    F.sign_inspection(api, inspection, U.INSPECTOR_HEADERS)
    F.assign_serial(api, env["bo1"], U.COORDINATOR_HEADERS)
    env["ship1"] = F.create_shipment(api, env["bo1"], "JP",
                                     U.COMPLIANCE_3_HEADERS)["id"]
    F.attach_docs(api, env["ship1"], "CITES-RE-9002", U.COMPLIANCE_3_HEADERS)
    F.reject_lot(api, env["lot1"], "PERMIT_WITHDRAWN", U.COMPLIANCE_HEADERS)
    return env


def test_an_export_release_that_is_short_of_both_paperwork_and_money_reports_the_paperwork(api, chain_c):
    """
    The settlement threshold is missed and the permit has been withdrawn, and the
    refusal is the wildlife one at 409 rather than the payment one at 402.

    PRD: "**Compliance outranks money.** An export release whose contributing lot
    still has an unverified permit *and* whose applied deposit falls short of the
    settlement threshold returns `ERR_CITES_PERMIT_UNVERIFIED`, never
    `ERR_DEPOSIT_INSUFFICIENT`. Wildlife law outranks money."

    Design: Difficulty/priority_pair_validation_conflict/p2_cites_compliance_outranks_deposit_settlement
    """
    env = a_serialized_instrument_with_a_withdrawn_permit(api, chain_c)

    lot = validate_success(api.get_tonewood_lot(env["lot1"], U.WOOD_BUYER_HEADERS))
    assert lot["permit_status"] == "INVALID"
    order = validate_success(
        api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert order["deposit_applied_cents"] == 88619

    validate_error(api.release_export_shipment(env["ship1"], U.COMPLIANCE_2_HEADERS),
                   E.ERR_CITES_PERMIT_UNVERIFIED, 409)


def test_the_payment_status_is_never_returned_and_the_order_is_not_closed(api, chain_c):
    """
    A shortfall that would answer 402 loses to a compliance failure that answers
    409, and the refusal leaves the shipment where it stood with the order still
    invoiced rather than closed.

    PRD: "And only then is money considered: the order's `deposit_applied_cents`
    must be at least twenty percent of `binding_quote_total_cents` — multiply by
    2000 basis points, divide by 10000, round half up — otherwise
    `ERR_DEPOSIT_INSUFFICIENT` with HTTP 402."

    Design: Difficulty/priority_pair_validation_conflict/p2_cites_compliance_outranks_deposit_settlement
    """
    env = a_serialized_instrument_with_a_withdrawn_permit(api, chain_c)

    response = api.release_export_shipment(env["ship1"], U.COMPLIANCE_2_HEADERS)
    assert response.status_code != 402
    assert response.json()["data"]["error_id"] != E.ERR_DEPOSIT_INSUFFICIENT

    shipment = validate_success(
        api.get_export_shipment(env["ship1"], U.COMPLIANCE_HEADERS))
    assert shipment["status"] == "DOCS_ATTACHED"
    assert shipment["released_by_user_id"] is None

    order = validate_success(
        api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert order["commercial_status"] == "INVOICED"


def test_a_booth_that_is_both_chemically_wrong_and_full_reports_the_chemistry(api, chain_two_orders):
    """
    One slot, one nitrocellulose run already spraying, and a polyurethane body
    asking for the same window: the refusal names the overspray problem, not the
    slot count.

    PRD: "Because chemistry is checked before capacity, a booth that is
    simultaneously chemically wrong and full reports
    `ERR_BOOTH_FINISH_INCOMPATIBLE` — never the capacity error."

    Design: Difficulty/priority_pair_validation_conflict/p3_booth_finish_incompatibility_outranks_aggregate_capacity
    """
    F.set_clock(api, "2026-08-02T13:00:00Z")

    booth = validate_success(
        api.get_storage_room(chain_two_orders["fb1"], U.FINISH_TECH_HEADERS))
    assert booth["capacity_slots"] == 1
    assert booth["occupied_slots"] == 1
    assert booth["climate_status"] == "IN_SPEC"

    validate_error(api.create_finish_run({
        "build_order_id": chain_two_orders["bo2"],
        "booth_id": chain_two_orders["fb1"],
        "finish_system": "POLY", "coat_count": 3,
        "expected_build_order_version": chain_two_orders["bo2_v3"],
    }, U.FINISH_TECH_HEADERS), E.ERR_BOOTH_FINISH_INCOMPATIBLE, 409)


def test_the_capacity_error_is_suppressed_and_the_second_body_stays_in_assembly(api, chain_two_orders):
    """
    Both booth rules are armed by the same request, and the one that loses leaves
    no trace: the slot count is unchanged, the booth still holds exactly one run,
    and the rejected body is still waiting in assembly.

    PRD: "Second, capacity: the count of non-terminal runs whose closed hold
    interval overlaps the new hold, plus one for the new run, must not exceed the
    booth's `capacity_slots`."

    Design: Difficulty/priority_pair_validation_conflict/p3_booth_finish_incompatibility_outranks_aggregate_capacity
    """
    F.set_clock(api, "2026-08-02T13:00:00Z")

    response = api.create_finish_run({
        "build_order_id": chain_two_orders["bo2"],
        "booth_id": chain_two_orders["fb1"],
        "finish_system": "POLY", "coat_count": 3,
        "expected_build_order_version": chain_two_orders["bo2_v3"],
    }, U.FINISH_TECH_HEADERS)
    assert response.json()["data"]["error_id"] != E.ERR_BOOTH_CAPACITY_EXCEEDED

    runs, _ = validate_paginated(api.list_finish_runs(
        U.FINISH_TECH_HEADERS, {"booth_id": chain_two_orders["fb1"]}))
    assert len(runs) == 1

    booth = validate_success(
        api.get_storage_room(chain_two_orders["fb1"], U.FINISH_TECH_HEADERS))
    assert booth["occupied_slots"] == 1

    order2 = validate_success(
        api.get_build_order(chain_two_orders["bo2"], U.COORDINATOR_HEADERS))
    assert order2["build_stage"] == "IN_ASSEMBLY"


def an_impounded_utility_billet(api):
    """
    Thirty board feet of appendix-two rosewood sawn out at utility grade, then
    impounded when the permit behind the lot is withdrawn.
    """
    env = X.build_clock(api)
    X.build_dry_store(api, env)
    env["spec1"] = F.create_spec(api, F.spec_payload())["id"]
    lot = F.create_lot(api, F.lot_payload(
        species_code="EAST_INDIAN_ROSEWOOD", cites_appendix="APPENDIX_II",
        storage_room_id=env["dry1"]))
    env["lot1"] = lot["id"]
    F.attest_permit(api, env["lot1"], "CITES-II-4471", U.COMPLIANCE_HEADERS)
    F.log_moisture_reading(api, env["lot1"], 7.0)
    F.condition_lot(api, env["lot1"])
    env["lot_v1"] = F.release_lot(api, env["lot1"])["version"]
    env["blt1"] = F.create_billet(api, env["lot1"], env["lot_v1"],
                                  billet_code="BLT-001", board_feet=30.00,
                                  grade="UTILITY")["id"]
    F.reject_lot(api, env["lot1"], "PERMIT_WITHDRAWN", U.COMPLIANCE_HEADERS)
    return env


def test_impounded_protected_wood_outranks_a_grade_that_is_merely_too_low(api):
    """
    Utility wood against a spec demanding double-A, out of a lot whose permit has
    been withdrawn: the refusal is the compliance one, because a clerical grade
    problem is fixable and impounded protected wood is not.

    PRD: "**Compliance outranks compatibility.** Opening a component whose billet
    comes from a rejected, quarantined protected-species lot *and* whose grade is
    below the spec minimum returns `ERR_PROTECTED_SPECIES_QUARANTINED`, not
    `ERR_GRADE_BELOW_MINIMUM`."

    Design: Difficulty/priority_pair_validation_conflict/p4_protected_species_safety_outranks_grade_compatibility
    """
    env = an_impounded_utility_billet(api)

    billet = validate_success(api.get_billet(env["blt1"], U.MACHINIST_HEADERS))
    assert billet["status"] == "QUARANTINED"
    assert billet["grade"] == "UTILITY"
    lot = validate_success(api.get_tonewood_lot(env["lot1"], U.MACHINIST_HEADERS))
    assert lot["status"] == "REJECTED"

    validate_error(api.create_component({
        "spec_id": env["spec1"], "billet_id": env["blt1"],
    }, U.MACHINIST_HEADERS), E.ERR_PROTECTED_SPECIES_QUARANTINED, 409)


def test_neither_of_the_two_lower_rules_surfaces_and_no_part_is_opened(api):
    """
    Three rules are armed by the one request, so an implementation ordering its
    checks any other way has two distinct wrong answers available; neither the
    grade complaint nor the lot-status complaint may come back, and no part row
    is created.

    PRD: "A billet impounded by a lot rejection is refused earlier and with a
    different code — `ERR_PROTECTED_SPECIES_QUARANTINED` — and as §2.6 records,
    that refusal outranks both compatibility checks, so a quarantined billet
    whose grade is also too low reports the compliance failure."

    Design: Difficulty/priority_pair_validation_conflict/p4_protected_species_safety_outranks_grade_compatibility
    """
    env = an_impounded_utility_billet(api)
    assert C.SPEC_TOP_OM["min_grade"] == "AA"

    response = api.create_component({
        "spec_id": env["spec1"], "billet_id": env["blt1"],
    }, U.MACHINIST_HEADERS)
    assert response.status_code == 409
    error_id = response.json()["data"]["error_id"]
    assert error_id != E.ERR_GRADE_BELOW_MINIMUM
    assert error_id != E.ERR_LOT_NOT_RELEASED

    components, _ = validate_paginated(
        api.list_components(U.MACHINIST_HEADERS, {"billet_id": env["blt1"]}))
    assert components == []

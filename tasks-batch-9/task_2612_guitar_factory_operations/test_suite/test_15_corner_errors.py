"""
Error codes triggered where they belong: fifteen distinct not-found families, the
thickness band that only one QC verdict polices, the three refusals the machining
verbs must keep apart, the two independent component-creation guards, the booth
room type, the cure clock, the order-wide compliance hold, the inspection round
guards, the single-use review verbs, the shop cycle and the warranty duplicate.
"""

from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                           validate_success)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U

MISSING_ID = "00000000-0000-4000-8000-000000000000"
FAILING_SETUP = {
    "action_mm_treble": 1.75,
    "action_mm_bass": 2.10,
    "relief_mm": 0.20,
    "intonation_cents_max": 4.8,
}
PASSING_SETUP = {
    "action_mm_treble": 1.60,
    "action_mm_bass": 2.20,
    "relief_mm": 0.25,
    "intonation_cents_max": 4.0,
}


def test_each_path_family_answers_an_unknown_identifier_with_its_own_code(api, comp_routed):
    """
    A well-formed identifier that names nothing is refused by the family of the
    path it was presented on, so fifteen resources give fifteen different codes,
    and a real station identifier offered on the billet path is a missing billet
    rather than a hit.

    PRD: "Every entity identifier in the URL path resolves to an existing row.
    Violation: the 404 belonging to that entity — `ERR_STORAGE_ROOM_NOT_FOUND`,
    `ERR_TONEWOOD_LOT_NOT_FOUND`, `ERR_BILLET_NOT_FOUND`,
    `ERR_COMPONENT_SPEC_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`,
    `ERR_STATION_NOT_FOUND`, `ERR_STATION_RESERVATION_NOT_FOUND`,
    `ERR_OPTION_CATALOG_NOT_FOUND`, `ERR_BUILD_ORDER_NOT_FOUND`,
    `ERR_OPTION_SELECTION_NOT_FOUND`, `ERR_FINISH_RUN_NOT_FOUND`,
    `ERR_SETUP_INSPECTION_NOT_FOUND`, `ERR_REPAIR_SHOP_NOT_FOUND`,
    `ERR_WARRANTY_REGISTRATION_NOT_FOUND` or `ERR_EXPORT_SHIPMENT_NOT_FOUND`."

    Design: Corner/errors/every_entity_family_reports_its_own_not_found_code
    """
    admin = U.PLANT_ADMIN_HEADERS
    families = [
        (api.get_storage_room, E.ERR_STORAGE_ROOM_NOT_FOUND),
        (api.get_tonewood_lot, E.ERR_TONEWOOD_LOT_NOT_FOUND),
        (api.get_billet, E.ERR_BILLET_NOT_FOUND),
        (api.get_component_spec, E.ERR_COMPONENT_SPEC_NOT_FOUND),
        (api.get_component, E.ERR_COMPONENT_NOT_FOUND),
        (api.get_station, E.ERR_STATION_NOT_FOUND),
        (api.get_station_reservation, E.ERR_STATION_RESERVATION_NOT_FOUND),
        (api.get_option, E.ERR_OPTION_CATALOG_NOT_FOUND),
        (api.get_build_order, E.ERR_BUILD_ORDER_NOT_FOUND),
        (api.get_option_selection, E.ERR_OPTION_SELECTION_NOT_FOUND),
        (api.get_finish_run, E.ERR_FINISH_RUN_NOT_FOUND),
        (api.get_setup_inspection, E.ERR_SETUP_INSPECTION_NOT_FOUND),
        (api.get_repair_shop, E.ERR_REPAIR_SHOP_NOT_FOUND),
        (api.get_warranty_registration, E.ERR_WARRANTY_REGISTRATION_NOT_FOUND),
        (api.get_export_shipment, E.ERR_EXPORT_SHIPMENT_NOT_FOUND),
    ]
    for read, expected in families:
        validate_error(read(MISSING_ID, admin), expected, 404)

    validate_error(api.get_billet(comp_routed["cnc1"], admin),
                   E.ERR_BILLET_NOT_FOUND, 404)


def test_an_out_of_tolerance_thickness_is_stored_freely_and_refused_only_on_accept(api, comp_routed):
    """
    Hand-shaping records whatever the bench actually produced without judging it,
    and the dimensional band is enforced by the accepting verdict alone — the same
    call asking for a hold succeeds and parks the part with a reason.

    PRD: "An `ACCEPT` verdict requires the part's `measured_thickness_mm` to sit
    within the spec's `thickness_tolerance_mm` of its `target_thickness_mm`,
    measured as an absolute difference with the bound **inclusive**; a part exactly
    at the tolerance limit passes, and a part beyond it is refused with
    `ERR_THICKNESS_OUT_OF_TOLERANCE`."

    Design: Corner/errors/the_thickness_band_is_policed_only_by_the_qc_accept_verdict
    """
    env = comp_routed
    res = F.create_reservation(api, env["hs1"], "2026-08-03T14:00:00Z",
                               "2026-08-03T15:00:00Z",
                               component_id=env["cmp1"],
                               headers=U.LUTHIER_HEADERS)["id"]

    shaped = F.hand_shape_component(api, env["cmp1"], res, 3.05)
    assert shaped["status"] == "HAND_SHAPED"
    assert shaped["measured_thickness_mm"] == 3.05

    validate_error(api.qc_component(env["cmp1"], {"verdict": "ACCEPT"},
                                    U.INSPECTOR_HEADERS),
                   E.ERR_THICKNESS_OUT_OF_TOLERANCE, 409)
    refused = validate_success(api.get_component(env["cmp1"], U.MACHINIST_HEADERS))
    assert refused["status"] == "HAND_SHAPED"

    held = F.qc_component(api, env["cmp1"], "HOLD")
    assert held["status"] == "QC_HELD"
    assert held["qc_hold_reason"] == "DIMENSION"


def test_the_machining_verbs_keep_three_different_refusals_apart(api, comp_routed):
    """
    Re-routing a part that has already been through the router, hand-shaping
    against a router booking, and hand-shaping against a whole-instrument booking
    are three distinct refusals, and none of the three consumes the window it
    cited.

    PRD: "Both calls require the cited reservation to be `HELD` and to name this
    very part in its `component_id`, otherwise `ERR_RESERVATION_STATE_INVALID` or
    `ERR_RESERVATION_COMPONENT_MISMATCH`."

    Design: Corner/errors/the_component_advance_verbs_police_status_station_type_and_reservation_ownership
    """
    env = comp_routed
    again = F.create_reservation(api, env["cnc1"], "2026-08-03T08:00:00Z",
                                 "2026-08-03T09:00:00Z",
                                 component_id=env["cmp1"])["id"]
    validate_error(api.route_component(env["cmp1"], {
        "station_reservation_id": again, "measured_thickness_mm": 2.90,
    }, U.MACHINIST_HEADERS), E.ERR_COMPONENT_STATE_INVALID, 409)

    wrong_bench = F.create_reservation(api, env["cnc1"], "2026-08-03T11:00:00Z",
                                       "2026-08-03T12:00:00Z",
                                       component_id=env["cmp1"])["id"]
    validate_error(api.hand_shape_component(env["cmp1"], {
        "station_reservation_id": wrong_bench, "measured_thickness_mm": 2.90,
    }, U.LUTHIER_HEADERS), E.ERR_STATION_TYPE_MISMATCH, 422)

    whole_instrument = F.create_reservation(api, env["hs1"],
                                           "2026-08-03T14:00:00Z",
                                           "2026-08-03T15:00:00Z",
                                           headers=U.LUTHIER_HEADERS)["id"]
    validate_error(api.hand_shape_component(env["cmp1"], {
        "station_reservation_id": whole_instrument, "measured_thickness_mm": 2.90,
    }, U.LUTHIER_HEADERS), E.ERR_RESERVATION_COMPONENT_MISMATCH, 422)

    part = validate_success(api.get_component(env["cmp1"], U.MACHINIST_HEADERS))
    assert part["status"] == "CNC_ROUTED"
    assert part["measured_thickness_mm"] == 2.90

    cnc = validate_success(api.get_station(env["cnc1"], U.MACHINIST_HEADERS))
    A.assert_station_minutes(cnc, total=180, held=120, consumed=60, released=0)
    hs = validate_success(api.get_station(env["hs1"], U.MACHINIST_HEADERS))
    A.assert_station_minutes(hs, total=60, held=60, consumed=0, released=0)


def test_component_creation_refuses_a_taken_billet_and_a_forbidden_species_differently(api, comp_routed):
    """
    A billet already promised to another part is refused on its own status, while
    a free billet of the wrong timber is refused on the spec's species list — two
    independent guards on the same endpoint, and neither leaves a part behind.

    PRD: "The billet must be in status `AVAILABLE`, or the request is refused with
    `ERR_BILLET_STATE_INVALID`, and the lot it came from must still be `RELEASED`,
    or `ERR_LOT_NOT_RELEASED`. Two compatibility checks then join the wood to the
    spec: the species of the billet's lot must appear in the spec's
    `required_species_codes`, otherwise `ERR_SPECIES_NOT_PERMITTED`; and the
    billet's `grade` must rank at or above the spec's `min_grade` on the
    `UTILITY`-to-`AAA` ranking, otherwise `ERR_GRADE_BELOW_MINIMUM`."

    Design: Corner/errors/component_creation_policies_both_the_billet_status_and_the_spec_species_list
    """
    env = comp_routed
    validate_error(api.create_component({
        "spec_id": env["spec1"], "billet_id": env["blt1"],
    }, U.MACHINIST_HEADERS), E.ERR_BILLET_STATE_INVALID, 409)

    maple = F.create_lot(api, F.lot_payload(
        lot_code="LOT-002", species_code="HARD_MAPLE", cites_appendix="NONE",
        board_feet_received=60.00, moisture_content_pct=7.0,
        storage_room_id=env["dry1"]))["id"]
    F.log_moisture_reading(api, maple, 7.0)
    F.condition_lot(api, maple)
    maple_version = F.release_lot(api, maple)["version"]
    maple_billet = F.create_billet(api, maple, maple_version,
                                   billet_code="BLT-002", board_feet=20.00,
                                   grade="AAA")["id"]

    validate_error(api.create_component({
        "spec_id": env["spec1"], "billet_id": maple_billet,
    }, U.MACHINIST_HEADERS), E.ERR_SPECIES_NOT_PERMITTED, 422)

    _, meta = validate_paginated(api.list_components(U.MACHINIST_HEADERS))
    assert meta["total_count"] == 1
    assert validate_success(
        api.get_billet(env["blt1"], U.MACHINIST_HEADERS))["status"] == "RESERVED"
    assert validate_success(
        api.get_billet(maple_billet, U.MACHINIST_HEADERS))["status"] == "AVAILABLE"


def test_a_body_cannot_be_sprayed_in_a_room_that_is_not_a_booth(api, order_in_assembly):
    """
    The booth reference resolves to any room at all, so pointing it at the dry
    store or the build room is refused on the room's type rather than as a missing
    row, and the instrument stays in assembly until a real booth is named.

    PRD: "The booth must be a room whose `room_type` is `FINISH_BOOTH`, otherwise
    `ERR_BOOTH_ROOM_TYPE_INVALID`; a build room cannot be sprayed in."

    Design: Corner/errors/a_finish_run_must_be_sprayed_in_a_finish_booth
    """
    env = order_in_assembly
    for wrong_room in (env["dry1"], env["br1"]):
        validate_error(api.create_finish_run({
            "build_order_id": env["bo1"], "booth_id": wrong_room,
            "finish_system": "NITRO", "coat_count": 8,
            "expected_build_order_version": env["bo_v3"],
        }, U.FINISH_TECH_HEADERS), E.ERR_BOOTH_ROOM_TYPE_INVALID, 422)

    held = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert held["build_stage"] == "IN_ASSEMBLY"

    run = F.create_finish_run(api, env["bo1"], env["fb1"], env["bo_v3"],
                              finish_system="NITRO", coat_count=8)
    assert run["status"] == "SPRAYING"

    order = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert order["build_stage"] == "IN_FINISH"

    booth = validate_success(api.get_storage_room(env["fb1"], U.FINISH_TECH_HEADERS))
    assert booth["occupied_slots"] == 1
    dry = validate_success(api.get_storage_room(env["dry1"], U.FINISH_TECH_HEADERS))
    assert dry["occupied_slots"] == 0


def test_the_buffing_wheel_waits_for_the_cure_and_the_other_verbs_are_refused_outright(api, order_in_assembly):
    """
    A curing run refuses the wheel until the cure is up, one second early
    included, and accepts it at the exact instant; meanwhile completing, resuming
    and re-spraying are all refused on the run's own posture.

    PRD: "This requires the current clock instant to be at or after
    `cure_ready_at`, with the bound inclusive: an instant exactly equal to
    `cure_ready_at` is permitted, and anything earlier is `ERR_CURE_NOT_COMPLETE`."

    Design: Corner/errors/the_finish_run_verbs_police_the_cure_clock_and_their_own_from_state
    """
    env = order_in_assembly
    run = F.create_finish_run(api, env["bo1"], env["fb1"], env["bo_v3"],
                              finish_system="NITRO", coat_count=8)["id"]

    curing = F.complete_spray(api, run)
    assert curing["status"] == "CURING"
    assert curing["spray_completed_at"] == "2026-08-01T00:00:00Z"
    assert curing["cure_hours"] == 348
    assert curing["cure_ready_at"] == "2026-08-15T12:00:00Z"

    validate_error(api.buff_finish_run(run, U.FINISH_TECH_HEADERS),
                   E.ERR_CURE_NOT_COMPLETE, 409)
    validate_error(api.complete_finish_run(run, U.FINISH_TECH_HEADERS),
                   E.ERR_FINISH_RUN_STATE_INVALID, 409)
    validate_error(api.resume_cure(run, U.FINISH_TECH_HEADERS),
                   E.ERR_FINISH_RUN_STATE_INVALID, 409)
    validate_error(api.complete_spray(run, U.FINISH_TECH_HEADERS),
                   E.ERR_FINISH_RUN_STATE_INVALID, 409)

    F.set_clock(api, "2026-08-15T11:59:59Z")
    validate_error(api.buff_finish_run(run, U.FINISH_TECH_HEADERS),
                   E.ERR_CURE_NOT_COMPLETE, 409)

    F.set_clock(api, "2026-08-15T12:00:00Z")
    buffing = F.buff_run(api, run)
    assert buffing["status"] == "BUFFING"
    assert buffing["cure_ready_at"] == "2026-08-15T12:00:00Z"


def test_a_compliance_hold_stops_the_clean_sibling_part_until_the_tainted_one_is_gone(api, order_two_components_released):
    """
    The hold belongs to the order, not to the affected part, so the untouched
    sibling — itself perfectly rough-sawn — cannot be machined while the order is
    parked, and the hold only lifts once no part still carries the compliance
    reason.

    PRD: "A `ComplianceOfficer` clears the hold once no part on the order still
    carries a `qc_hold_reason` of `PROTECTED_SPECIES`; the order's `build_stage` is
    then restored to whatever `stage_before_compliance_hold` recorded and that
    field is set back to null."

    Design: Corner/errors/a_compliance_hold_blocks_a_clean_sibling_component_until_the_dirty_one_is_scrapped
    """
    env = order_two_components_released
    F.reject_lot(api, env["lot1"], "origin paperwork failed audit")

    held_order = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert held_order["build_stage"] == "COMPLIANCE_HOLD"
    assert held_order["stage_before_compliance_hold"] == "COMPONENTS_RELEASED"
    assert validate_success(
        api.get_component(env["cmp2"], U.MACHINIST_HEADERS))["status"] == "ROUGH_SAWN"

    validate_error(api.route_component(env["cmp2"], {
        "station_reservation_id": env["res2"], "measured_thickness_mm": 2.90,
    }, U.MACHINIST_HEADERS), E.ERR_COMPLIANCE_HOLD_ACTIVE, 409)
    assert validate_success(api.get_station_reservation(
        env["res2"], U.MACHINIST_HEADERS))["status"] == "HELD"

    F.disposition_component(api, env["cmp1"], "SCRAP", U.INSPECTOR_HEADERS)
    cleared = F.clear_compliance_hold(api, env["bo1"])
    assert cleared["build_stage"] == "COMPONENTS_RELEASED"
    assert cleared["stage_before_compliance_hold"] is None

    routed = F.route_component(api, env["cmp2"], env["res2"], 2.90)
    assert routed["status"] == "CNC_ROUTED"


def test_the_condemned_lot_is_impounded_once_and_not_scrapped_twice(api, order_two_components_released):
    """
    Condemning the lot moves every board foot it ever held into the scrapped
    bucket in one act, and the later scrapping of the part it fed must not move the
    same wood a second time.

    PRD: "That destruction is skipped when the billet has already been driven to
    `QUARANTINED` by a lot rejection — such a billet stays `QUARANTINED` and its
    board feet, already counted in `board_feet_scrapped`, are not scrapped a second
    time."

    Design: Corner/errors/a_compliance_hold_blocks_a_clean_sibling_component_until_the_dirty_one_is_scrapped
    """
    env = order_two_components_released
    F.reject_lot(api, env["lot1"], "origin paperwork failed audit")

    impounded = validate_success(
        api.get_tonewood_lot(env["lot1"], U.WOOD_BUYER_HEADERS))
    A.assert_lot_ledger(impounded, available=0.00, unassigned=0.00, reserved=0.00,
                        consumed=0.00, scrapped=99.10, kerf_loss=0.90)
    A.assert_wood_conserved(impounded)
    assert validate_success(
        api.get_billet(env["blt1"], U.MACHINIST_HEADERS))["status"] == "QUARANTINED"

    scrapped = F.disposition_component(api, env["cmp1"], "SCRAP",
                                       U.INSPECTOR_HEADERS)
    assert scrapped["status"] == "SCRAPPED"
    assert scrapped["qc_hold_reason"] == "NONE"

    after = validate_success(
        api.get_tonewood_lot(env["lot1"], U.WOOD_BUYER_HEADERS))
    A.assert_lot_ledger(after, available=0.00, unassigned=0.00, reserved=0.00,
                        consumed=0.00, scrapped=99.10, kerf_loss=0.90)

    untouched = validate_success(
        api.get_tonewood_lot(env["lot2"], U.WOOD_BUYER_HEADERS))
    A.assert_lot_ledger(untouched, available=69.10, unassigned=0.00, reserved=30.00,
                        consumed=0.00, scrapped=0.00, kerf_loss=0.90)


def test_a_second_round_cannot_be_opened_and_an_unmeasured_round_cannot_be_signed(api, order_at_inspection):
    """
    An order already at the inspection bench clears the state rung, so the second
    opening surfaces the concurrency rule instead of a stage error; independently
    the open round cannot be signed until it has been measured, and it cannot be
    measured twice.

    PRD: "Because `INSPECTION` is an accepted from-state, an order already under
    inspection clears the state rung of the ladder, and a second attempt therefore
    surfaces the business rule rather than a stage error: no round on the order may
    currently be in status `OPEN` or `MEASURED`, and an attempt to open a second
    concurrent round is refused with `ERR_INSPECTION_ROUND_OPEN`."

    Design: Corner/errors/a_second_inspection_round_cannot_be_opened_and_an_open_round_cannot_be_signed
    """
    env = order_at_inspection

    validate_error(api.open_setup_inspection(env["bo1"], U.LUTHIER_HEADERS),
                   E.ERR_INSPECTION_ROUND_OPEN, 409)
    _, meta = validate_paginated(api.list_setup_inspections(U.LUTHIER_HEADERS))
    assert meta["total_count"] == 1

    validate_error(api.sign_setup_inspection(env["insp1"], U.INSPECTOR_HEADERS),
                   E.ERR_INSPECTION_STATE_INVALID, 409)
    still_open = validate_success(
        api.get_setup_inspection(env["insp1"], U.LUTHIER_HEADERS))
    assert still_open["status"] == "OPEN"
    assert still_open["inspector_user_id"] is None

    measured = F.measure_inspection(api, env["insp1"], dict(PASSING_SETUP),
                                    U.LUTHIER_HEADERS)
    assert measured["status"] == "MEASURED"
    assert measured["deviation_score"] == 0.00

    validate_error(api.measure_setup_inspection(env["insp1"], dict(PASSING_SETUP),
                                                U.LUTHIER_HEADERS),
                   E.ERR_INSPECTION_STATE_INVALID, 409)


def test_the_fourth_round_is_refused_and_the_repeated_failures_escalate_the_order(api, order_at_inspection):
    """
    Three failed rounds park the instrument in setup with the rework tally at the
    ceiling, the promise pushed out twice by a fortnight each and the order lifted
    into the distressed band, and the fourth opening is refused on the ceiling
    rather than allowed or auto-scrapped.

    PRD: "A round whose score is above 10.00 moves `MEASURED → FAILED` with
    `verdict` set to `FAIL`, and that failure is the root of a three-link cascade:
    the order moves `build_stage` `INSPECTION → SETUP`, its `rework_round_count`
    increases by one, and if that count has reached two or more, the commercial
    dimension escalates — `commercial_status` moves `CONFIRMED → AT_RISK` or
    `OPTIONS_LOCKED → AT_RISK`, `promised_date` advances by fourteen days, and
    `priority_score` is recomputed, which lifts the order in the station queue
    because `AT_RISK` carries its own scheduling points."

    Design: Corner/errors/the_fourth_inspection_round_is_refused_after_three_failures
    """
    env = order_at_inspection
    expected = [
        (1, "OPTIONS_LOCKED", "2026-11-01T00:00:00Z"),
        (2, "AT_RISK", "2026-11-15T00:00:00Z"),
        (3, "AT_RISK", "2026-11-29T00:00:00Z"),
    ]
    round_id = env["insp1"]
    for round_number, commercial_status, promised_date in expected:
        signed = F.sign_inspection(api, F.measure_inspection(
            api, round_id, dict(FAILING_SETUP), U.LUTHIER_HEADERS)["id"],
            U.INSPECTOR_HEADERS)
        assert signed["verdict"] == "FAIL"
        assert signed["round_number"] == round_number

        order = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
        assert order["build_stage"] == "SETUP"
        assert order["rework_round_count"] == round_number
        assert order["commercial_status"] == commercial_status
        assert order["promised_date"] == promised_date

        if round_number < 3:
            opened = F.open_inspection(api, env["bo1"], U.LUTHIER_HEADERS)
            assert opened["round_number"] == round_number + 1
            round_id = opened["id"]

    validate_error(api.open_setup_inspection(env["bo1"], U.LUTHIER_HEADERS),
                   E.ERR_MAX_REWORK_EXCEEDED, 409)

    _, meta = validate_paginated(api.list_setup_inspections(U.LUTHIER_HEADERS))
    assert meta["total_count"] == 3
    final = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert final["build_stage"] == "SETUP"
    assert final["priority_score"] == 25.00


def test_each_review_verb_is_legal_once_and_refuses_the_repeat(api, order_two_options):
    """
    Approval is legal exactly once out of the pending state and rejection is legal
    from pending or from approved, so the second use of either verb is refused on
    the row's own state while the untouched sibling line stays pending throughout.

    PRD: "Approving or rejecting a row that is already `LOCKED` or `REJECTED`, or
    approving one that is already `SELECTED`, is
    `ERR_OPTION_SELECTION_STATE_INVALID`."

    Design: Corner/errors/the_option_review_verbs_are_single_use_per_row
    """
    env = order_two_options
    approved = F.approve_selection(api, env["selD"], U.COORDINATOR_4_HEADERS)
    assert approved["status"] == "SELECTED"

    validate_error(api.approve_option_selection(env["selD"], U.COORDINATOR_4_HEADERS),
                   E.ERR_OPTION_SELECTION_STATE_INVALID, 409)

    rejected = F.reject_selection(api, env["selD"], "customer changed the inlay",
                                  U.COORDINATOR_4_HEADERS)
    assert rejected["status"] == "REJECTED"
    assert rejected["line_total_cents"] == 16205

    validate_error(api.reject_option_selection(env["selD"], U.COORDINATOR_4_HEADERS,
                                               {"reason": "customer changed the inlay"}),
                   E.ERR_OPTION_SELECTION_STATE_INVALID, 409)

    sibling = validate_success(
        api.get_option_selection(env["selG"], U.COORDINATOR_HEADERS))
    assert sibling["status"] == "PENDING_APPROVAL"


def test_approval_leaves_the_provisional_total_alone_while_rejection_drops_the_line(api, order_two_options):
    """
    The two verbs are separated by their observable arithmetic and not merely by
    the state they land on: approving the inlay line moves no money at all, and
    rejecting the same line takes its sixteen thousand two hundred and five cents
    out of the running total.

    PRD: "Because both `PENDING_APPROVAL` and `SELECTED` sit inside the input set,
    approval does not move the provisional total at all — it only makes the row
    eligible for locking; rejection, by contrast, drops the row out of the set and
    the total falls."

    Design: Corner/errors/the_option_review_verbs_are_single_use_per_row
    """
    env = order_two_options
    F.approve_selection(api, env["selD"], U.COORDINATOR_4_HEADERS)
    after_approve = validate_success(
        api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert after_approve["provisional_quote_total_cents"] == 345910

    F.reject_selection(api, env["selD"], "customer changed the inlay",
                       U.COORDINATOR_4_HEADERS)
    after_reject = validate_success(
        api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert after_reject["provisional_quote_total_cents"] == 329705


def test_the_network_verbs_refuse_a_repeat_grant_and_a_shop_that_was_never_granted(api, two_authorized_shops):
    """
    The two network verbs guard opposite states: the grant is refused on a shop
    that already holds one and the withdrawal is refused on a shop that never held
    one, so a freshly enrolled shop cannot be suspended at all and neither refusal
    disturbs the clearance already on file.

    PRD: "Authorizing a shop that is already `AUTHORIZED`, or suspending one that
    is not `AUTHORIZED`, is `ERR_SHOP_STATE_INVALID`."

    Design: Corner/errors/the_shop_authorization_verbs_refuse_repeats_and_wrong_starting_states
    """
    env = two_authorized_shops

    validate_error(api.authorize_repair_shop(
        env["shopA"], {"authorization_level": "CUSTOM_SHOP_CERTIFIED"},
        U.SERVICE_MANAGER_HEADERS), E.ERR_SHOP_STATE_INVALID, 409)
    unchanged = validate_success(
        api.get_repair_shop(env["shopA"], U.SERVICE_MANAGER_HEADERS))
    assert unchanged["status"] == "AUTHORIZED"
    assert unchanged["authorization_level"] == "FULL_SERVICE"

    fresh = F.create_shop(api, F.shop_payload(
        shop_code="SHP-C", shop_name="Chugoku Guitar Care", country_code="JP"))
    validate_error(api.suspend_repair_shop(fresh["id"], U.SERVICE_MANAGER_HEADERS,
                                           {"reason": "never authorised"}),
                   E.ERR_SHOP_STATE_INVALID, 409)
    still_applied = validate_success(
        api.get_repair_shop(fresh["id"], U.SERVICE_MANAGER_HEADERS))
    assert still_applied["status"] == "APPLIED"
    assert still_applied["authorization_level"] == "NONE"


def test_the_withdrawal_is_itself_single_use(api, two_authorized_shops):
    """
    Withdrawing the clearance of an authorized shop succeeds and strips its level,
    and because the suspended state is not authorized the very same call is refused
    the second time.

    PRD: "Suspension moves an `AUTHORIZED` shop to `SUSPENDED` and resets
    `authorization_level` to `NONE`; registrations the shop already holds are left
    `ACTIVE`, but new registrations from it are refused."

    Design: Corner/errors/the_shop_authorization_verbs_refuse_repeats_and_wrong_starting_states
    """
    env = two_authorized_shops

    suspended = validate_success(api.suspend_repair_shop(
        env["shopA"], U.SERVICE_MANAGER_HEADERS, {"reason": "audit finding"}))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["authorization_level"] == "NONE"

    validate_error(api.suspend_repair_shop(env["shopA"], U.SERVICE_MANAGER_HEADERS,
                                           {"reason": "audit finding"}),
                   E.ERR_SHOP_STATE_INVALID, 409)
    assert validate_success(api.get_repair_shop(
        env["shopA"], U.SERVICE_MANAGER_HEADERS))["status"] == "SUSPENDED"


def a_registered_instrument(api, env):
    """
    Carry the order through a passing inspection to a minted serial, enrol one
    authorized Japanese shop, and register the instrument to its first owner.
    """
    F.measure_inspection(api, env["insp1"], dict(PASSING_SETUP), U.LUTHIER_HEADERS)
    signed = F.sign_inspection(api, env["insp1"], U.INSPECTOR_HEADERS)
    assert signed["verdict"] == "PASS"
    serial = F.assign_serial(api, env["bo1"], U.COORDINATOR_HEADERS)["serial_number"]

    shop = F.create_shop(api, F.shop_payload(
        shop_code="SHP-1", shop_name="Kanto Fret Works", country_code="JP"))["id"]
    F.authorize_shop(api, shop, "FULL_SERVICE")
    registration = F.create_registration(api, env["bo1"], shop, serial)
    return shop, serial, registration


def test_a_second_registration_is_refused_while_the_first_one_is_live(api, order_at_inspection):
    """
    The instrument may be registered to exactly one live owner, so the identical
    payload presented twice is refused the second time and the shop's live-warranty
    tally stays at one.

    PRD: "At most one registration per order may be `ACTIVE` at a time, and a
    second attempt is refused with `ERR_WARRANTY_ALREADY_REGISTERED`."

    Design: Corner/errors/a_voided_warranty_frees_the_instrument_for_a_fresh_registration
    """
    env = order_at_inspection
    shop, serial, registration = a_registered_instrument(api, env)
    assert registration["status"] == "ACTIVE"
    assert registration["coverage_months"] == 24
    assert registration["coverage_ends_at"] == "2028-08-16T00:00:00Z"
    assert validate_success(api.get_repair_shop(
        shop, U.SERVICE_MANAGER_HEADERS))["warranty_claim_count"] == 1

    validate_error(api.create_warranty_registration({
        "build_order_id": env["bo1"], "registering_shop_id": shop,
        "serial_number": serial, "owner_email": "owner@example.com",
        "purchase_date": "2026-08-16T00:00:00Z",
    }, U.SERVICE_MANAGER_HEADERS), E.ERR_WARRANTY_ALREADY_REGISTERED, 409)

    _, meta = validate_paginated(
        api.list_warranty_registrations(U.SERVICE_MANAGER_HEADERS))
    assert meta["total_count"] == 1


def test_voiding_the_registration_is_terminal_and_frees_the_instrument_again(api, order_at_inspection):
    """
    Voiding takes the row out of the live population and out of the shop's tally,
    refuses a second voiding as terminal, and leaves the instrument free for the
    very same payload to register afresh while the voided row stays on file.

    PRD: "Voiding moves it `ACTIVE → VOID`, which is terminal, and decrements the
    registering shop's `warranty_claim_count`."

    Design: Corner/errors/a_voided_warranty_frees_the_instrument_for_a_fresh_registration
    """
    env = order_at_inspection
    shop, serial, registration = a_registered_instrument(api, env)

    voided = F.void_registration(api, registration["id"],
                                 "registered to the wrong owner")
    assert voided["status"] == "VOID"
    assert validate_success(api.get_repair_shop(
        shop, U.SERVICE_MANAGER_HEADERS))["warranty_claim_count"] == 0

    validate_error(api.void_warranty_registration(
        registration["id"], U.SERVICE_MANAGER_HEADERS,
        {"reason": "registered to the wrong owner"}),
        E.ERR_WARRANTY_STATE_INVALID, 409)

    fresh = F.create_registration(api, env["bo1"], shop, serial)
    assert fresh["status"] == "ACTIVE"

    _, meta = validate_paginated(
        api.list_warranty_registrations(U.SERVICE_MANAGER_HEADERS))
    assert meta["total_count"] == 2
    assert validate_success(api.get_repair_shop(
        shop, U.SERVICE_MANAGER_HEADERS))["warranty_claim_count"] == 1

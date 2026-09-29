"""
Where the state machines refuse: an order opening on two dimensions at once,
lot transitions guarded ahead of the physical bands, terminal states that
refuse everything, and the two genuine loops in the system.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def test_an_order_opens_on_both_dimensions_at_once(api, clock):
    """
    A new instrument is born with a shop-floor stage and a commercial status set
    simultaneously, both at their earliest value, with every tally and every
    money bucket at zero and no serial or binding price yet.

    PRD: "A new order opens with `build_stage` of `DRAFT`, `commercial_status` of
    `QUOTED`, `serial_number` null, `binding_quote_total_cents` null,
    `rework_round_count` and `refinish_count` at zero, `cites_permit_required`
    false, `strictest_cites_appendix` of `NONE`, `stage_before_compliance_hold`
    null, and all five deposit figures — `deposit_paid_cents`,
    `deposit_held_cents`, `deposit_applied_cents`, `deposit_refunded_cents` and
    `deposit_forfeited_cents` — at zero."

    Design: Corner/state_machines/new_build_order_starts_in_draft_and_quoted
    """
    order = F.create_order(api, F.order_payload(
        order_code="ORD-STD", model_code="OM45", base_price_cents=300000,
        promised_date="2026-11-01T00:00:00Z", is_custom_shop=False,
        artist_tier="NONE", finish_system="NITRO"), U.COORDINATOR_HEADERS)

    A.assert_order_state(order, build_stage="DRAFT", commercial_status="QUOTED")
    assert order["rework_round_count"] == 0
    assert order["refinish_count"] == 0
    assert order["serial_number"] is None
    assert order["binding_quote_total_cents"] is None
    assert order["stage_before_compliance_hold"] is None
    A.assert_deposit_ledger(order, paid=0, applied=0, refunded=0,
                            forfeited=0, held=0)


def test_the_shop_floor_cannot_be_released_while_the_price_is_still_negotiable(api, clock):
    """
    The single interlock between the two dimensions refuses in the commercial
    direction: a brand-new order cannot be released to the machine shop, and the
    refusal names the commercial dimension rather than the build stage.

    PRD: "Attempting it while the commercial dimension is behind is
    `ERR_COMMERCIAL_STATUS_INVALID`; attempting it when the build stage is past
    `DRAFT` is `ERR_BUILD_STAGE_INVALID`."

    Design: Corner/state_machines/new_build_order_starts_in_draft_and_quoted
    """
    order = F.create_order(api, F.order_payload(
        order_code="ORD-STD", model_code="OM45", base_price_cents=300000,
        promised_date="2026-11-01T00:00:00Z"), U.COORDINATOR_HEADERS)

    validate_error(api.release_components(order["id"], U.MACHINIST_HEADERS),
                   E.ERR_COMMERCIAL_STATUS_INVALID, 409)

    after = validate_success(api.get_build_order(order["id"], U.COORDINATOR_HEADERS))
    A.assert_order_state(after, build_stage="DRAFT", commercial_status="QUOTED")


def test_release_is_refused_on_state_before_the_moisture_band_is_consulted(api, lot_received):
    """
    A delivery that was never conditioned and is also far too wet is refused on
    the state rung, not the physical band, because the ladder reaches the state
    check long before it reaches the moisture guard.

    PRD: "The last step before wood becomes cuttable is release, accepted only
    from `CONDITIONED` and requiring `permit_status` to be either `NOT_REQUIRED`
    or `VERIFIED`; a lot whose permit is still `PENDING` or has gone `INVALID`
    cannot be released."

    Design: Corner/state_machines/releasing_a_lot_that_was_never_conditioned_is_refused
    """
    validate_error(
        api.release_tonewood_lot(lot_received["lot1"], U.WOOD_BUYER_HEADERS),
        E.ERR_LOT_STATE_INVALID, 409)

    lot = validate_success(
        api.get_tonewood_lot(lot_received["lot1"], U.WOOD_BUYER_HEADERS))
    assert lot["status"] == "RECEIVED"
    assert lot["moisture_content_pct"] == 12.0


def test_a_lot_that_is_not_released_reports_a_different_code_to_the_machinist(api, lot_received):
    """
    The same un-released delivery refuses two different callers with two
    different codes: the buyer's own transition is a state refusal, while a
    machinist trying to saw from it is told the lot is not released.

    PRD: "Sawing a lot that is not in status `RELEASED` is refused with
    `ERR_LOT_NOT_RELEASED`."

    Design: Corner/state_machines/releasing_a_lot_that_was_never_conditioned_is_refused
    """
    lot = validate_success(
        api.get_tonewood_lot(lot_received["lot1"], U.MACHINIST_HEADERS))

    validate_error(api.create_billet({
        "billet_code": "BLT-001", "lot_id": lot_received["lot1"],
        "board_feet": 30.00, "grade": "AAA",
        "expected_tonewood_lot_version": lot["version"],
    }, U.MACHINIST_HEADERS), E.ERR_LOT_NOT_RELEASED, 409)


def test_the_lower_moisture_bound_is_inclusive_and_a_hair_below_it_is_not(api, lot_received):
    """
    An over-dried lot at five point nine percent is refused on the band while
    keeping its place in the kiln, and one further reading that lands exactly on
    the lower bound lets the identical call through.

    PRD: "It requires the lot's current `moisture_content_pct` to sit inside the
    band from 6.0 to 8.0 percent with **both bounds inclusive** — 6.0 passes, 8.0
    passes, 5.9 and 8.1 are refused with `ERR_MOISTURE_OUT_OF_BAND` — and it
    requires the lot's storage room to be `IN_SPEC` at that moment."

    Design: Corner/state_machines/conditioning_a_lot_below_the_moisture_band_is_refused
    """
    dried = F.log_moisture_reading(api, lot_received["lot1"], 5.9)
    assert dried["status"] == "KILN_DRYING"

    validate_error(
        api.condition_tonewood_lot(lot_received["lot1"], U.WOOD_BUYER_HEADERS),
        E.ERR_MOISTURE_OUT_OF_BAND, 409)
    held = validate_success(
        api.get_tonewood_lot(lot_received["lot1"], U.WOOD_BUYER_HEADERS))
    assert held["status"] == "KILN_DRYING"

    F.log_moisture_reading(api, lot_received["lot1"], 6.0)
    conditioned = F.condition_lot(api, lot_received["lot1"])
    assert conditioned["status"] == "CONDITIONED"
    assert conditioned["moisture_content_pct"] == 6.0


def test_attesting_the_permit_applies_all_three_side_effects_in_one_call(api, lot_permit_hold):
    """
    One attestation frees the protected wood, records the paperwork number, marks
    the permit verified and stamps the officer who signed it — the stamp the
    export release later compares against.

    PRD: "Attestation moves the lot `PERMIT_HOLD → RECEIVED`, writes the supplied
    `permit_number` onto the lot, sets `permit_status` to `VERIFIED`, and —
    importantly for §3.9 — records the attesting officer's `X-User-ID` in
    `attested_by_user_id`."

    Design: Corner/state_machines/attest_permit_applies_every_declared_side_effect
    """
    lot = F.attest_permit(api, lot_permit_hold["lotB"], "CITES-BR-2026-0099",
                          U.COMPLIANCE_HEADERS)

    assert lot["status"] == "RECEIVED"
    assert lot["permit_status"] == "VERIFIED"
    assert lot["permit_number"] == "CITES-BR-2026-0099"
    assert lot["attested_by_user_id"] == U.COMPLIANCE_HEADERS["X-User-ID"]
    assert lot["moisture_at_receipt_pct"] == 7.0


def test_protected_wood_cannot_be_conditioned_before_the_permit_is_attested(api, lot_permit_hold):
    """
    The permit hold is not a from-state for either of the drying transitions, so
    a protected delivery is frozen against conditioning and against release until
    the paperwork clears, even though its moisture already sits inside the band.

    PRD: "A lot declared `APPENDIX_II` or `APPENDIX_I` is created in status
    `PERMIT_HOLD` with `permit_status` set to `PENDING` — protected species are
    frozen before any measurement, conditioning or cutting can touch them."

    Design: Corner/state_machines/attest_permit_applies_every_declared_side_effect
    """
    validate_error(
        api.condition_tonewood_lot(lot_permit_hold["lotB"], U.WOOD_BUYER_HEADERS),
        E.ERR_LOT_STATE_INVALID, 409)
    validate_error(
        api.release_tonewood_lot(lot_permit_hold["lotB"], U.WOOD_BUYER_HEADERS),
        E.ERR_LOT_STATE_INVALID, 409)

    lot = validate_success(
        api.get_tonewood_lot(lot_permit_hold["lotB"], U.WOOD_BUYER_HEADERS))
    assert lot["status"] == "PERMIT_HOLD"
    assert lot["permit_status"] == "PENDING"


def test_a_condemned_lot_refuses_every_remaining_trigger(api, lot_received):
    """
    Condemnation is terminal for the wood: the reading self-loop, the
    conditioning declaration, the release and a second condemnation are all
    refused, and the recorded moisture never moves again.

    PRD: "Rejection is legal from every non-terminal lot state — `RECEIVED`,
    `PERMIT_HOLD`, `KILN_DRYING`, `CONDITIONED` and `RELEASED` — and is refused
    with `ERR_LOT_STATE_INVALID` only when the lot is already `DEPLETED` or
    `REJECTED`."

    Design: Corner/state_machines/a_rejected_lot_refuses_every_further_transition
    """
    lot_id = lot_received["lot1"]
    rejected = F.reject_lot(api, lot_id, "grain runout across the whole flitch",
                            U.COMPLIANCE_HEADERS)
    assert rejected["status"] == "REJECTED"
    assert rejected["permit_status"] == "INVALID"

    validate_error(api.create_moisture_reading(
        lot_id, {"moisture_content_pct": 7.0}, U.WOOD_BUYER_HEADERS),
        E.ERR_LOT_STATE_INVALID, 409)
    validate_error(api.condition_tonewood_lot(lot_id, U.WOOD_BUYER_HEADERS),
                   E.ERR_LOT_STATE_INVALID, 409)
    validate_error(api.release_tonewood_lot(lot_id, U.WOOD_BUYER_HEADERS),
                   E.ERR_LOT_STATE_INVALID, 409)
    validate_error(api.reject_tonewood_lot(
        lot_id, U.COMPLIANCE_HEADERS, {"reason": "again"}),
        E.ERR_LOT_STATE_INVALID, 409)

    lot = validate_success(api.get_tonewood_lot(lot_id, U.WOOD_BUYER_HEADERS))
    assert lot["moisture_content_pct"] == 12.0
    assert lot["status"] == "REJECTED"


def test_condemning_an_uncut_lot_resolves_its_cascade_over_empty_sets(api, lot_received):
    """
    The condemnation is the root of a four-deep cascade, but on a delivery that
    was never sawn there are no billets, parts or orders to reach, so the request
    succeeds having moved only the lot itself and the standing wood.

    PRD: "When a lot is rejected while still on permit hold, no billets,
    components or orders exist yet, all three downstream links resolve over empty
    sets, and the request succeeds having changed nothing but the lot itself."

    Design: Corner/state_machines/a_rejected_lot_refuses_every_further_transition
    """
    rejected = F.reject_lot(api, lot_received["lot1"], "documentation defect",
                            U.COMPLIANCE_HEADERS)
    assert rejected["status"] == "REJECTED"
    A.assert_lot_ledger(rejected, available=0.00, unassigned=0.00, reserved=0.00,
                        consumed=0.00, scrapped=100.00, kerf_loss=0.00)
    A.assert_wood_conserved(rejected)


def test_cancelling_twice_is_refused_and_moves_no_money_the_second_time(api, clock):
    """
    Cancellation is not idempotent: the first call closes both dimensions, and
    the second is refused on the commercial state, so the settlement waterfall
    cannot run a second time over an order that never had a deposit.

    PRD: "It is permitted from every build stage except `SERIALIZED` and from any
    `commercial_status` other than `INVOICED`, `CLOSED` or `CANCELLED` — so from
    `QUOTED`, `CONFIRMED`, `OPTIONS_LOCKED` or `AT_RISK` — and is otherwise
    refused with `ERR_COMMERCIAL_STATUS_INVALID`."

    Design: Corner/state_machines/a_second_cancel_on_a_cancelled_order_is_refused
    """
    order = F.create_order(api, F.order_payload(
        order_code="ORD-STD", model_code="OM45", base_price_cents=300000,
        promised_date="2026-11-01T00:00:00Z"), U.COORDINATOR_HEADERS)

    cancelled = F.cancel_order(api, order["id"], "customer withdrew",
                               U.COORDINATOR_HEADERS)
    A.assert_order_state(cancelled, build_stage="SCRAPPED",
                         commercial_status="CANCELLED")
    A.assert_deposit_ledger(cancelled, paid=0, applied=0, refunded=0,
                            forfeited=0, held=0)

    validate_error(api.cancel_build_order(
        order["id"], U.COORDINATOR_HEADERS, {"reason": "customer withdrew"}),
        E.ERR_COMMERCIAL_STATUS_INVALID, 409)

    after = validate_success(api.get_build_order(order["id"], U.COORDINATOR_HEADERS))
    A.assert_deposit_ledger(after, paid=0, applied=0, refunded=0,
                            forfeited=0, held=0)
    A.assert_money_conserved(after)


def test_quarantine_voids_the_acclimatised_lot_and_leaves_its_neighbour_alone(api, two_lots_one_conditioned):
    """
    Condemning the room pushes only the lot that had actually been declared
    acclimatised back to received; the untouched delivery beside it on the same
    rack keeps its status, and the voided lot keeps the measurement that earned
    the conditioning.

    PRD: "Every tonewood lot stored in that room whose status is `CONDITIONED`
    falls back `CONDITIONED → RECEIVED`, because acclimatisation achieved in a
    room that has since been condemned cannot be trusted; the lot must be
    re-measured and re-conditioned from scratch."

    Design: Corner/state_machines/room_quarantine_voids_conditioning_for_conditioned_lots_only
    """
    env = two_lots_one_conditioned
    first = F.log_climate_reading(api, env["dry1"], 60.0, 21.0)
    assert first["climate_status"] == "OUT_OF_SPEC"
    assert first["out_of_spec_since"] == "2026-08-01T00:00:00Z"

    F.set_clock(api, "2026-08-02T00:00:00Z")
    second = F.log_climate_reading(api, env["dry1"], 60.0, 21.0)
    assert second["climate_status"] == "QUARANTINED"
    assert second["latest_rh_pct"] == 60.0
    assert second["latest_temp_c"] == 21.0

    lot1 = validate_success(api.get_tonewood_lot(env["lot1"], U.WOOD_BUYER_HEADERS))
    assert lot1["status"] == "RECEIVED"
    assert lot1["moisture_content_pct"] == 7.0

    lot2 = validate_success(api.get_tonewood_lot(env["lot2"], U.WOOD_BUYER_HEADERS))
    assert lot2["status"] == "RECEIVED"


def test_reconditioning_inside_a_condemned_room_is_blocked_by_the_room(api, two_lots_one_conditioned):
    """
    The voided lot is back in a legal from-state for conditioning, so the refusal
    that follows can only come from the room, and it carries the stricter
    quarantine code rather than the ordinary out-of-specification one.

    PRD: "`QUARANTINED` is the stricter posture: it produces `ERR_ROOM_QUARANTINED`
    instead, and it additionally blocks commissioning a new station in that room
    and booking any reservation on a station that sits in it."

    Design: Corner/state_machines/room_quarantine_voids_conditioning_for_conditioned_lots_only
    """
    env = two_lots_one_conditioned
    F.log_climate_reading(api, env["dry1"], 60.0, 21.0)
    F.set_clock(api, "2026-08-02T00:00:00Z")
    F.log_climate_reading(api, env["dry1"], 60.0, 21.0)

    validate_error(api.condition_tonewood_lot(env["lot1"], U.WOOD_BUYER_HEADERS),
                   E.ERR_ROOM_QUARANTINED, 409)

    lot1 = validate_success(api.get_tonewood_lot(env["lot1"], U.WOOD_BUYER_HEADERS))
    assert lot1["status"] == "RECEIVED"


def test_a_suspended_shop_can_be_reinstated_at_a_different_level(api, clock):
    """
    The service network's two live states form a genuine loop: a shop is granted
    full service, suspended back to nothing, and then reinstated at a higher
    level, with the grant level rewritten from the request each time.

    PRD: "Suspension moves an `AUTHORIZED` shop to `SUSPENDED` and resets
    `authorization_level` to `NONE`; registrations the shop already holds are left
    `ACTIVE`, but new registrations from it are refused."

    Design: Corner/state_machines/repair_shop_authorization_cycle_closes
    """
    shop = F.create_shop(api, {"shop_code": "SHP-1",
                               "shop_name": "Kanto Fret Works",
                               "country_code": "JP"})
    assert shop["status"] == "APPLIED"
    assert shop["authorization_level"] == "NONE"
    assert shop["warranty_claim_count"] == 0

    granted = F.authorize_shop(api, shop["id"], "FULL_SERVICE")
    assert granted["status"] == "AUTHORIZED"
    assert granted["authorization_level"] == "FULL_SERVICE"

    suspended = F.suspend_shop(api, shop["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["authorization_level"] == "NONE"

    reinstated = F.authorize_shop(api, shop["id"], "CUSTOM_SHOP_CERTIFIED")
    assert reinstated["status"] == "AUTHORIZED"
    assert reinstated["authorization_level"] == "CUSTOM_SHOP_CERTIFIED"


def test_granting_authorization_twice_over_is_refused_on_the_shop_state(api, clock):
    """
    Because the loop is between the authorized and suspended states only, a
    second grant on an already-authorized shop and a suspension of a shop that
    was never granted are both refused on the shop's own state.

    PRD: "Authorizing a shop that is already `AUTHORIZED`, or suspending one that
    is not `AUTHORIZED`, is `ERR_SHOP_STATE_INVALID`."

    Design: Corner/state_machines/repair_shop_authorization_cycle_closes
    """
    shop = F.create_shop(api, {"shop_code": "SHP-1",
                               "shop_name": "Kanto Fret Works",
                               "country_code": "JP"})

    validate_error(api.suspend_repair_shop(shop["id"], U.SERVICE_MANAGER_HEADERS),
                   E.ERR_SHOP_STATE_INVALID, 409)

    F.authorize_shop(api, shop["id"], "FULL_SERVICE")
    validate_error(api.authorize_repair_shop(
        shop["id"], {"authorization_level": "WARRANTY_ONLY"},
        U.SERVICE_MANAGER_HEADERS), E.ERR_SHOP_STATE_INVALID, 409)

    after = validate_success(api.get_repair_shop(shop["id"], U.SERVICE_MANAGER_HEADERS))
    assert after["authorization_level"] == "FULL_SERVICE"


def test_certification_is_refused_from_both_of_the_other_two_postures(api, clock):
    """
    The deliberate human act is only accepted from quarantine: it is refused on a
    room that is in specification, and refused again on one that has merely
    drifted, because recovery from a drift is by measurement rather than by fiat.

    PRD: "Certification is only accepted while the room is actually `QUARANTINED`
    — otherwise `ERR_ROOM_STATE_INVALID` — and only while the room's own
    `latest_rh_pct` sits within `rh_tolerance_pct` of `target_rh_pct`, otherwise
    `ERR_ROOM_CLIMATE_OUT_OF_SPEC`."

    Design: Corner/state_machines/certifying_a_room_that_is_not_quarantined_is_refused
    """
    env = X.build_dry_store(api, clock)

    validate_error(api.certify_storage_room(env["dry1"], U.PLANT_ADMIN_HEADERS),
                   E.ERR_ROOM_STATE_INVALID, 409)

    drifted = F.log_climate_reading(api, env["dry1"], 60.0, 21.0,
                                    U.PLANT_ADMIN_HEADERS)
    assert drifted["climate_status"] == "OUT_OF_SPEC"

    validate_error(api.certify_storage_room(env["dry1"], U.INSPECTOR_HEADERS),
                   E.ERR_ROOM_STATE_INVALID, 409)


def test_a_reading_exactly_at_the_tolerance_edge_walks_the_room_back(api, clock):
    """
    The ordinary way home from a drift is a sample sitting precisely the
    tolerance away from target, which counts as inside the band and clears the
    stamp that the quarantine timer would otherwise have measured from.

    PRD: "From `OUT_OF_SPEC`, a sample whose absolute difference from
    `target_rh_pct` is less than or equal to `rh_tolerance_pct` returns the room
    `OUT_OF_SPEC → IN_SPEC` and clears `out_of_spec_since` to null — the boundary
    is inclusive, so a reading exactly the tolerance away from target counts as
    back in specification."

    Design: Corner/state_machines/certifying_a_room_that_is_not_quarantined_is_refused
    """
    env = X.build_dry_store(api, clock)
    F.log_climate_reading(api, env["dry1"], 60.0, 21.0, U.PLANT_ADMIN_HEADERS)

    recovered = F.log_climate_reading(api, env["dry1"], 48.0, 21.0,
                                      U.FINISH_TECH_HEADERS)
    assert recovered["climate_status"] == "IN_SPEC"
    assert recovered["out_of_spec_since"] is None
    assert recovered["latest_rh_pct"] == 48.0


def test_holding_a_part_then_sending_it_back_clears_the_reason_and_counts_the_round(api, comp_routed):
    """
    A part held on dimensions and then sent back around the loop advances its
    rework tally and has the reason wiped, so the next hold can record a fresh
    one, and the hand-shaping window it burned is spent rather than recycled.

    PRD: "A `Luthier` may choose a `disposition` of `REWORK`, sending the part
    back around the machining loop: the part moves `QC_HELD → REWORK`, its
    `rework_count` rises by one and its `qc_hold_reason` returns to `NONE`."

    Design: Corner/state_machines/qc_hold_then_rework_returns_the_part_to_the_router
    """
    env = comp_routed
    res2 = F.create_reservation(api, env["hs1"], "2026-08-02T10:00:00Z",
                                "2026-08-02T11:00:00Z",
                                component_id=env["cmp1"],
                                headers=U.LUTHIER_HEADERS)["id"]
    shaped = F.hand_shape_component(api, env["cmp1"], res2, 2.90)
    assert shaped["status"] == "HAND_SHAPED"

    held = F.qc_component(api, env["cmp1"], "HOLD", hold_reason="DIMENSION")
    assert held["status"] == "QC_HELD"
    assert held["qc_hold_reason"] == "DIMENSION"

    reworked = F.disposition_component(api, env["cmp1"], "REWORK",
                                       U.LUTHIER_HEADERS)
    assert reworked["status"] == "REWORK"
    assert reworked["rework_count"] == 1
    assert reworked["qc_hold_reason"] == "NONE"

    billet = validate_success(api.get_billet(env["blt1"], U.MACHINIST_HEADERS))
    assert billet["status"] == "RESERVED"

    station = validate_success(api.get_station(env["hs1"], U.MACHINIST_HEADERS))
    A.assert_station_minutes(station, total=60, held=0, consumed=60, released=0)


def test_a_reworked_part_re_enters_the_router_on_a_fresh_window(api, comp_routed):
    """
    The loop really is closed: a part sent back for rework is routed again on a
    new booking, which returns it to the routed state and leaves its rework tally
    standing at the one round it has already used.

    PRD: "A part in `REWORK` re-enters machining by being routed again, which
    closes the cycle `ROUGH_SAWN → CNC_ROUTED → HAND_SHAPED → QC_HELD → REWORK →
    CNC_ROUTED`; the second pass through routing does not re-check the owning
    order's build stage."

    Design: Corner/state_machines/qc_hold_then_rework_returns_the_part_to_the_router
    """
    env = comp_routed
    res2 = F.create_reservation(api, env["hs1"], "2026-08-02T10:00:00Z",
                                "2026-08-02T11:00:00Z",
                                component_id=env["cmp1"],
                                headers=U.LUTHIER_HEADERS)["id"]
    F.hand_shape_component(api, env["cmp1"], res2, 2.90)
    F.qc_component(api, env["cmp1"], "HOLD", hold_reason="DIMENSION")
    F.disposition_component(api, env["cmp1"], "REWORK", U.LUTHIER_HEADERS)

    res3 = F.create_reservation(api, env["cnc1"], "2026-08-02T12:00:00Z",
                                "2026-08-02T13:00:00Z",
                                component_id=env["cmp1"])["id"]
    routed = F.route_component(api, env["cmp1"], res3, 2.88)
    assert routed["status"] == "CNC_ROUTED"
    assert routed["rework_count"] == 1
    assert routed["measured_thickness_mm"] == 2.88


def test_a_failing_score_drags_the_order_backwards_without_moving_the_money(api, order_at_inspection):
    """
    Signing a round whose score is above the threshold fails the round and, in
    the same request, walks a different entity backwards to the setup bench with
    its round tally raised, while the commercial dimension and the promise stand
    still because one failure is not yet an escalation.

    PRD: "A round whose score is above 10.00 moves `MEASURED → FAILED` with
    `verdict` set to `FAIL`, and that failure is the root of a three-link cascade:
    the order moves `build_stage` `INSPECTION → SETUP`, its `rework_round_count`
    increases by one, and if that count has reached two or more, the commercial
    dimension escalates — `commercial_status` moves `CONFIRMED → AT_RISK` or
    `OPTIONS_LOCKED → AT_RISK`, `promised_date` advances by fourteen days, and
    `priority_score` is recomputed, which lifts the order in the station queue
    because `AT_RISK` carries its own scheduling points."

    Design: Corner/state_machines/a_failed_inspection_pushes_the_order_back_to_setup
    """
    env = order_at_inspection
    measured = F.measure_inspection(api, env["insp1"], {
        "action_mm_treble": 1.75, "action_mm_bass": 2.10,
        "relief_mm": 0.20, "intonation_cents_max": 4.8,
    }, U.LUTHIER_HEADERS)
    assert measured["status"] == "MEASURED"
    assert measured["deviation_score"] == 13.00

    signed = F.sign_inspection(api, env["insp1"], U.INSPECTOR_HEADERS)
    assert signed["status"] == "FAILED"
    assert signed["verdict"] == "FAIL"
    assert signed["round_number"] == 1

    order = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    A.assert_order_state(order, build_stage="SETUP",
                         commercial_status="OPTIONS_LOCKED")
    assert order["rework_round_count"] == 1
    assert order["promised_date"] == "2026-11-01T00:00:00Z"


def test_a_failed_round_is_terminal_and_refuses_a_second_signature(api, order_at_inspection):
    """
    Both outcomes of a round are terminal, so the failed round cannot be signed
    again or re-measured, which is what forces the shop to open a fresh round
    rather than re-litigating the old one.

    PRD: "`SIGNED` and `FAILED` are both terminal for a round, and any of these
    operations attempted against a round in the wrong status is
    `ERR_INSPECTION_STATE_INVALID`."

    Design: Corner/state_machines/a_failed_inspection_pushes_the_order_back_to_setup
    """
    env = order_at_inspection
    F.measure_inspection(api, env["insp1"], {
        "action_mm_treble": 1.75, "action_mm_bass": 2.10,
        "relief_mm": 0.20, "intonation_cents_max": 4.8,
    }, U.LUTHIER_HEADERS)
    F.sign_inspection(api, env["insp1"], U.INSPECTOR_HEADERS)

    validate_error(
        api.sign_setup_inspection(env["insp1"], U.INSPECTOR_2_HEADERS),
        E.ERR_INSPECTION_STATE_INVALID, 409)
    validate_error(api.measure_setup_inspection(env["insp1"], {
        "action_mm_treble": 1.60, "action_mm_bass": 2.20,
        "relief_mm": 0.25, "intonation_cents_max": 4.0,
    }, U.LUTHIER_HEADERS), E.ERR_INSPECTION_STATE_INVALID, 409)

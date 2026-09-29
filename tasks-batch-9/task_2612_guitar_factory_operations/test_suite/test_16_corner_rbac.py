"""
The permission surface at its awkward edges: two sampling endpoints whose role
sets overlap without matching, the role gate winning over the business checks it
sits above, the external shop confined to its own row, and the three identity
comparisons — one demanding difference, one demanding equality, one asymmetric
between two verbs on the same row.
"""

from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import test_users as U


def test_only_the_two_declared_roles_may_sample_a_rooms_air(api, lot_received):
    """
    The room hygrometer admits the plant administrator and the finish technician
    and turns the wood buyer away, so a sample inside the tolerance band from the
    finish technician sticks while the wood buyer's identical call changes nothing.

    PRD: "If the headers are well formed but the named role is not among the roles
    that the target endpoint permits, the rejection is `ERR_ROLE_NOT_PERMITTED`
    with HTTP 403."

    Design: Corner/rbac/the_two_shared_sampling_operations_admit_exactly_their_declared_pairs
    """
    room_id = lot_received["dry1"]
    validate_success(api.create_climate_reading(
        room_id, {"rh_pct": 45.0, "temp_c": 21.0}, U.PLANT_ADMIN_HEADERS))

    by_finish_tech = validate_success(api.create_climate_reading(
        room_id, {"rh_pct": 46.5, "temp_c": 21.0}, U.FINISH_TECH_HEADERS))
    assert by_finish_tech["latest_rh_pct"] == 46.5
    assert by_finish_tech["climate_status"] == "IN_SPEC"

    validate_error(api.create_climate_reading(
        room_id, {"rh_pct": 46.5, "temp_c": 21.0}, U.WOOD_BUYER_HEADERS),
        E.ERR_ROLE_NOT_PERMITTED, 403)

    room = validate_success(api.get_storage_room(room_id, U.PLANT_ADMIN_HEADERS))
    assert room["latest_rh_pct"] == 46.5
    assert room["climate_status"] == "IN_SPEC"


def test_the_wood_hygrometer_admits_a_different_pair_of_roles(api, lot_received):
    """
    The lot moisture reading is open to the wood buyer and the plant administrator
    and closed to the finish technician, which is the reverse asymmetry of the room
    sample and leaves the administrator as the only caller in both pairs.

    PRD: "2. **Role authorization.** The caller's role appears in the endpoint's
    permitted-role set, on every endpoint. Violation: `ERR_ROLE_NOT_PERMITTED`
    (403)."

    Design: Corner/rbac/the_two_shared_sampling_operations_admit_exactly_their_declared_pairs
    """
    lot_id = lot_received["lot1"]
    validate_success(api.create_moisture_reading(
        lot_id, {"moisture_content_pct": 9.0}, U.WOOD_BUYER_HEADERS))
    by_admin = validate_success(api.create_moisture_reading(
        lot_id, {"moisture_content_pct": 8.5}, U.PLANT_ADMIN_HEADERS))
    assert by_admin["moisture_content_pct"] == 8.5

    validate_error(api.create_moisture_reading(
        lot_id, {"moisture_content_pct": 8.5}, U.FINISH_TECH_HEADERS),
        E.ERR_ROLE_NOT_PERMITTED, 403)

    lot = validate_success(api.get_tonewood_lot(lot_id, U.WOOD_BUYER_HEADERS))
    assert lot["moisture_content_pct"] == 8.5
    assert lot["status"] == "KILN_DRYING"


def test_the_role_gate_answers_before_the_station_and_part_state_checks(api, comp_routed):
    """
    Each of these two calls would also have failed on its own merits — the router
    booking is the wrong bench for hand work and already spent, and the part has
    been through the router once — yet both come back as a permission refusal
    because the role rung is checked first and nothing later runs.

    PRD: "Requests are validated in a fixed order, and the **first** rule whose
    condition is violated short-circuits the request: its error is returned, no
    later rule is evaluated, and no state whatsoever is mutated."

    Design: Corner/rbac/the_role_gate_outranks_every_business_check_on_a_peer_s_verb
    """
    env = comp_routed
    validate_error(api.hand_shape_component(env["cmp1"], {
        "station_reservation_id": env["res1"], "measured_thickness_mm": 2.90,
    }, U.MACHINIST_HEADERS), E.ERR_ROLE_NOT_PERMITTED, 403)

    validate_error(api.route_component(env["cmp1"], {
        "station_reservation_id": env["res1"], "measured_thickness_mm": 2.90,
    }, U.LUTHIER_HEADERS), E.ERR_ROLE_NOT_PERMITTED, 403)

    part = validate_success(api.get_component(env["cmp1"], U.MACHINIST_HEADERS))
    assert part["status"] == "CNC_ROUTED"


def test_a_machinist_may_not_judge_a_part_and_a_luthier_may_not_saw_wood(api, comp_routed):
    """
    The two shop-floor peers share bookings but not a single physical verb, so the
    machinist cannot pass the part he routed and the luthier cannot open the lot,
    and the rack is untouched by either attempt.

    PRD: "A `Machinist` saws billets, opens parts and runs the routers, but cannot
    glue up, inspect or price."

    Design: Corner/rbac/the_role_gate_outranks_every_business_check_on_a_peer_s_verb
    """
    env = comp_routed
    validate_error(api.qc_component(env["cmp1"], {"verdict": "ACCEPT"},
                                    U.MACHINIST_HEADERS),
                   E.ERR_ROLE_NOT_PERMITTED, 403)

    validate_error(api.create_billet({
        "billet_code": "BLT-009", "lot_id": env["lot1"], "board_feet": 5.00,
        "grade": "AAA", "expected_tonewood_lot_version": env["lot_v1"],
    }, U.LUTHIER_HEADERS), E.ERR_ROLE_NOT_PERMITTED, 403)

    _, meta = validate_paginated(api.list_billets(U.MACHINIST_HEADERS))
    assert meta["total_count"] == 1
    lot = validate_success(api.get_tonewood_lot(env["lot1"], U.WOOD_BUYER_HEADERS))
    assert lot["board_feet_available"] == 69.10


def test_an_outside_shop_reads_its_own_row_and_its_own_registrations_only(api, two_authorized_shops):
    """
    The external caller's identifier is the shop it may speak for: its own row and
    its own registration list are open, and the same reads aimed at the other shop
    are refused on identity rather than on role.

    PRD: "An `AuthorizedShop` caller may register a warranty naming itself, read
    its own shop row, and list or read only its own registrations."

    Design: Corner/rbac/an_authorized_shop_is_confined_to_its_own_row_and_the_role_gate_precedes_the_identity_gate
    """
    env = two_authorized_shops
    caller = U.make_authorized_shop_headers(env["shopA"])

    own = validate_success(api.get_repair_shop(env["shopA"], caller))
    assert own["shop_code"] == "SHP-A"
    assert own["authorization_level"] == "FULL_SERVICE"

    validate_error(api.get_repair_shop(env["shopB"], caller),
                   E.ERR_SHOP_IDENTITY_MISMATCH, 403)

    validate_error(api.list_warranty_registrations(
        caller, {"registering_shop_id": env["shopB"]}),
        E.ERR_SHOP_IDENTITY_MISMATCH, 403)

    _, meta = validate_paginated(api.list_warranty_registrations(
        caller, {"registering_shop_id": env["shopA"]}))
    assert meta["total_count"] == 0


def test_the_role_gate_catches_the_shop_before_the_identity_gate_ever_runs(api, two_authorized_shops):
    """
    Asking for the other shop's clearance to be raised breaks both the role rule
    and the identity rule at once, and the role refusal wins; the network list stays
    closed even when filtered down to the caller's own row, and the other shop's
    clearance is left exactly as it was.

    PRD: "Everything else on the factory floor is closed to it: storage rooms,
    tonewood lots, billets, component specs, components, stations, station
    reservations, the option catalog, build orders, option selections, finish runs,
    setup inspections and export shipments all return `ERR_ROLE_NOT_PERMITTED`, as
    does the unfiltered repair-shop network list and any attempt by a shop to
    authorize itself."

    Design: Corner/rbac/an_authorized_shop_is_confined_to_its_own_row_and_the_role_gate_precedes_the_identity_gate
    """
    env = two_authorized_shops
    caller = U.make_authorized_shop_headers(env["shopA"])

    validate_error(api.list_repair_shops(caller), E.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(api.list_repair_shops(caller, {"status": "AUTHORIZED"}),
                   E.ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(api.list_build_orders(caller), E.ERR_ROLE_NOT_PERMITTED, 403)

    validate_error(api.authorize_repair_shop(
        env["shopB"], {"authorization_level": "CUSTOM_SHOP_CERTIFIED"}, caller),
        E.ERR_ROLE_NOT_PERMITTED, 403)

    other = validate_success(
        api.get_repair_shop(env["shopB"], U.SERVICE_MANAGER_HEADERS))
    assert other["authorization_level"] == "WARRANTY_ONLY"
    assert other["status"] == "AUTHORIZED"


def test_the_same_person_cannot_sign_the_round_he_measured_even_wearing_the_inspector_role(api, order_at_inspection):
    """
    The comparison is made on the identifier and not on the role, so the luthier
    who took the measurements is refused the signature while presenting himself as
    a quality inspector, and the round is left signable by a genuinely independent
    inspector.

    PRD: "Signing a playability inspection round requires the signing inspector's
    `X-User-ID` to differ from the `performed_by_user_id` recorded when the round
    was opened."

    Design: Corner/rbac/the_signature_must_come_from_a_different_user_id_than_the_measurement
    """
    env = order_at_inspection
    measured = F.measure_inspection(api, env["insp1"], {
        "action_mm_treble": 1.60, "action_mm_bass": 2.20,
        "relief_mm": 0.25, "intonation_cents_max": 4.0,
    }, U.LUTHIER_HEADERS)
    assert measured["performed_by_user_id"] == U.LUTHIER_ID
    assert measured["status"] == "MEASURED"
    assert measured["deviation_score"] == 0.00

    self_signer = U.make_headers(U.LUTHIER_ID, U.QUALITY_INSPECTOR)
    validate_error(api.sign_setup_inspection(env["insp1"], self_signer),
                   E.ERR_SEGREGATION_OF_DUTIES, 403)
    refused = validate_success(
        api.get_setup_inspection(env["insp1"], U.LUTHIER_HEADERS))
    assert refused["status"] == "MEASURED"
    assert refused["verdict"] == "PENDING"
    assert refused["inspector_user_id"] is None

    signed = F.sign_inspection(api, env["insp1"], U.INSPECTOR_HEADERS)
    assert signed["status"] == "SIGNED"
    assert signed["verdict"] == "PASS"
    assert signed["inspector_user_id"] == U.QUALITY_INSPECTOR_ID

    order = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert order["build_stage"] == "INSPECTION"
    assert order["rework_round_count"] == 0


def test_a_second_luthier_may_not_submit_another_luthiers_measurements(api, order_at_inspection):
    """
    Where signing demands two different identifiers, measuring demands the same
    one: the second luthier has the right role and the wrong identity, and the
    refusal leaves the round open, unscored and still owned by the luthier who
    opened it.

    PRD: "A related but distinct rule guards ownership rather than independence:
    only the luthier who opened an inspection round may submit that round's
    measurements, and a different luthier attempting it is refused with
    `ERR_MEASUREMENT_OWNER_MISMATCH` (403)."

    Design: Corner/rbac/only_the_luthier_who_opened_the_round_may_measure_it
    """
    env = order_at_inspection
    body = {"action_mm_treble": 1.60, "action_mm_bass": 2.20,
            "relief_mm": 0.25, "intonation_cents_max": 4.0}

    validate_error(api.measure_setup_inspection(env["insp1"], body,
                                                U.LUTHIER_2_HEADERS),
                   E.ERR_MEASUREMENT_OWNER_MISMATCH, 403)
    refused = validate_success(
        api.get_setup_inspection(env["insp1"], U.LUTHIER_HEADERS))
    assert refused["status"] == "OPEN"
    assert refused["deviation_score"] is None
    assert refused["performed_by_user_id"] == U.LUTHIER_ID

    measured = F.measure_inspection(api, env["insp1"], dict(body), U.LUTHIER_HEADERS)
    assert measured["status"] == "MEASURED"
    assert measured["deviation_score"] == 0.00
    assert measured["performed_by_user_id"] == U.LUTHIER_ID


def test_the_owner_check_never_rescues_a_caller_in_the_wrong_role(api, order_at_inspection):
    """
    Carrying the owning luthier's identifier under the machinist role does not buy
    admission, because the role rung is evaluated before the ownership comparison
    and produces the permission code rather than the ownership one.

    PRD: "2. **Role authorization.** The caller's role appears in the endpoint's
    permitted-role set, on every endpoint. Violation: `ERR_ROLE_NOT_PERMITTED`
    (403)."

    Design: Corner/rbac/only_the_luthier_who_opened_the_round_may_measure_it
    """
    env = order_at_inspection
    impostor = U.make_headers(U.LUTHIER_ID, U.MACHINIST)

    validate_error(api.measure_setup_inspection(env["insp1"], {
        "action_mm_treble": 1.60, "action_mm_bass": 2.20,
        "relief_mm": 0.25, "intonation_cents_max": 4.0,
    }, impostor), E.ERR_ROLE_NOT_PERMITTED, 403)

    still_open = validate_success(
        api.get_setup_inspection(env["insp1"], U.LUTHIER_HEADERS))
    assert still_open["status"] == "OPEN"
    assert still_open["performed_by_user_id"] == U.LUTHIER_ID


def test_a_coordinator_cannot_bless_the_option_line_she_configured_herself(api, order_two_options):
    """
    The approval must come from a second pair of eyes, so the coordinator who
    configured the inlay is refused and her colleague's identical call succeeds —
    and because approval only makes the line lockable, neither the refusal nor the
    approval moves the running total.

    PRD: "Approving an option selection requires the approving coordinator's
    `X-User-ID` to differ from the `created_by_user_id` stamped on the selection
    when it was configured."

    Design: Corner/rbac/the_coordinator_who_configured_an_option_may_not_approve_it_but_may_reject_it
    """
    env = order_two_options
    row = validate_success(api.get_option_selection(env["selD"], U.COORDINATOR_HEADERS))
    assert row["created_by_user_id"] == U.COORDINATOR_3_ID

    validate_error(api.approve_option_selection(env["selD"], U.COORDINATOR_3_HEADERS),
                   E.ERR_SEGREGATION_OF_DUTIES, 403)
    refused = validate_success(
        api.get_option_selection(env["selD"], U.COORDINATOR_HEADERS))
    assert refused["status"] == "PENDING_APPROVAL"
    assert validate_success(api.get_build_order(
        env["bo1"], U.COORDINATOR_HEADERS))["provisional_quote_total_cents"] == 345910

    approved = F.approve_selection(api, env["selD"], U.COORDINATOR_4_HEADERS)
    assert approved["status"] == "SELECTED"
    assert validate_success(api.get_build_order(
        env["bo1"], U.COORDINATOR_HEADERS))["provisional_quote_total_cents"] == 345910


def test_the_same_coordinator_may_withdraw_the_line_she_configured(api, order_two_options):
    """
    The separation is one-sided: rejection carries no independence precondition, so
    the configuring coordinator may drop her own gold-hardware line, and that
    withdrawal is the movement that actually lowers the running total.

    PRD: "A coordinator may also reject a selection, optionally supplying a
    `reason`; rejection is accepted from `PENDING_APPROVAL` or from `SELECTED`,
    again only while the order is `QUOTED` or `CONFIRMED`, and moves the row to
    `REJECTED` while leaving its `line_total_cents` in place for audit."

    Design: Corner/rbac/the_coordinator_who_configured_an_option_may_not_approve_it_but_may_reject_it
    """
    env = order_two_options
    row = validate_success(api.get_option_selection(env["selG"], U.COORDINATOR_HEADERS))
    assert row["created_by_user_id"] == U.COORDINATOR_3_ID

    rejected = F.reject_selection(api, env["selG"],
                                  "customer dropped the gold hardware",
                                  U.COORDINATOR_3_HEADERS)
    assert rejected["status"] == "REJECTED"
    assert rejected["line_total_cents"] == 29705

    order = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert order["provisional_quote_total_cents"] == 316205

"""The visit and its per-limb service lines: shape rules, roll-ups and concurrency."""

from test_helpers import *  # noqa: F401,F403


def test_appointment_initial_state_is_unrouted_and_unbilled(api, dispatcher):
    """PRD §3.5: "It is minted with `status` `UNROUTED` and `billing_status`
    `UNBILLED`; its `route_stop_id`, `origin_appointment_id`, `rate_card_id`,
    `warranty_reason`, `cycle_source` and `completed_on` are all null; its
    `visit_kind` is `ROUTINE`; and its `service_units`, `service_minutes`,
    `estimated_total_cents`, `cancellation_fee_cents` and `trip_fee_share_cents`
    all start at 0."

    Design: Corner/state_machines/corner_appointment_initial_state_is_unrouted_and_unbilled
    """
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"])

    data = validate_success(
        api.create_appointment(
            {"horse_id": horse["id"], "scheduled_date": "2026-05-06"}, dispatcher
        ),
        201,
    )

    assert_appointment(data)
    assert data["status"] == "UNROUTED"
    assert data["billing_status"] == "UNBILLED"
    assert data["visit_kind"] == "ROUTINE"
    assert data["warranty_reason"] is None
    assert data["route_stop_id"] is None
    assert data["origin_appointment_id"] is None
    assert data["rate_card_id"] is None
    assert data["cycle_source"] is None
    assert data["completed_on"] is None
    assert data["service_units"] == 0
    assert data["service_minutes"] == 0
    assert data["estimated_total_cents"] == 0
    assert data["cancellation_fee_cents"] == 0
    assert data["trip_fee_share_cents"] == 0


def test_sedated_horse_without_vet_present_is_rejected(api, dispatcher):
    """PRD §3.5: "Creation passes gate 3 and gate 4, and it also passes the sedation
    rule: if the horse's `requires_sedation` is true the appointment must carry
    `vet_present` true, else `ERR_SEDATION_VET_REQUIRED`."
    PRD §2.7: "(47) A horse that requires sedation has an appointment carrying
    `vet_present` true, else `ERR_SEDATION_VET_REQUIRED` (HTTP 422); on appointment
    creation and attachment."

    Design: Corner/validations/corner_sedated_horse_without_vet_present_is_rejected
    """
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"], name="Nervy", requires_sedation=True)

    response = api.create_appointment(
        {
            "horse_id": horse["id"],
            "scheduled_date": "2026-05-06",
            "vet_present": False,
        },
        dispatcher,
    )

    validate_error(response, ApiErrorId.ERR_SEDATION_VET_REQUIRED.value)
    assert response.status_code == 422
    rows, _meta = validate_paginated(
        api.list_appointments(dispatcher, params={"horse_id": horse["id"]})
    )
    assert rows == [], "a refused creation writes no appointment"


def test_sedated_horse_service_minutes_apply_the_handling_multiplier(api, dispatcher):
    """PRD §3.5: "For a horse whose `requires_sedation` is false, handling is a flat
    6 minutes (`HORSE_HANDLING_MINUTES`). For a horse that requires sedation, the
    handling term is multiplied by 15000 basis points
    (`SEDATION_HANDLING_MULTIPLIER_BP`), divided by 10000 and rounded half up, which
    turns 6 minutes into 9, and a further 15 minutes (`SEDATION_EXTRA_MINUTES`) of
    sedation time is added on top — 18 minutes more than the unsedated case in
    total."
    PRD §3.5: "`service_units` is the sum of a fixed per-limb load: 1 for a `TRIM`
    (`SERVICE_UNITS_TRIM`), 2 for a `RESET` (`SERVICE_UNITS_RESET`), 3 for
    `NEW_SHOES` (`SERVICE_UNITS_NEW_SHOES`), 5 for `CORRECTIVE`
    (`SERVICE_UNITS_CORRECTIVE`) and 4 for `GLUE_ON` (`SERVICE_UNITS_GLUE_ON`)."

    Design: Corner/calculations/corner_sedated_horse_service_minutes_apply_the_handling_multiplier
    """
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"], name="Nervy", requires_sedation=True)
    limbs = limb_ids(horse["id"])
    appointment = create_appointment(horse["id"], "2026-05-06", vet_present=True)

    validate_success(
        api.add_service_lines(
            appointment["id"],
            service_lines_payload(
                [service_line(limbs["LF"], "TRIM")], appointment["version"]
            ),
            dispatcher,
        ),
        201,
    )

    after = read_appointment(appointment["id"])
    # 8 chair minutes + round_half_up(6 * 15000 / 10000) = 9 + 15 sedation = 32.
    assert after["service_minutes"] == expected_service_minutes(["TRIM"], True)
    assert after["service_minutes"] == 32
    assert after["service_units"] == SERVICE_UNITS_TRIM


def test_reset_on_a_barefoot_limb_is_rejected(api, dispatcher):
    """PRD §3.5: "A `RESET` line reuses the shoe already on the hoof, so the limb's
    `shoeing_state` must be `SHOD`, `SHOD_WITH_PAD` or `GLUED`; a `RESET` on a
    `BAREFOOT` limb has nothing to reuse and is `ERR_RESET_REQUIRES_SHOD_LIMB`."

    Design: Corner/validations/corner_reset_on_a_barefoot_limb_is_rejected
    """
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"])
    limbs = limb_ids(horse["id"])
    appointment = create_appointment(horse["id"], "2026-05-06")

    response = api.add_service_lines(
        appointment["id"],
        service_lines_payload(
            [service_line(limbs["LF"], "RESET")], appointment["version"]
        ),
        dispatcher,
    )

    validate_error(response, ApiErrorId.ERR_RESET_REQUIRES_SHOD_LIMB.value)
    assert response.status_code == 422
    assert service_lines_for(appointment["id"]) == []


def test_two_lines_for_the_same_limb_are_rejected(api, dispatcher):
    """PRD §3.5: "Finally, the appointment must not already carry another `PLANNED`
    or `PERFORMED` line for the same limb, else `ERR_DUPLICATE_LIMB_LINE`; four
    hooves means at most four live lines."
    PRD §3.5: "The array is validated in index order, the first offending element's
    error is returned, and on any failure **nothing at all is written**: no partial
    line set, no roll-up change, no reservation."

    Design: Corner/validations/corner_two_lines_for_the_same_limb_are_rejected
    """
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"])
    limbs = limb_ids(horse["id"])
    appointment = create_appointment(horse["id"], "2026-05-06")

    response = api.add_service_lines(
        appointment["id"],
        service_lines_payload(
            [
                service_line(limbs["LF"], "TRIM"),
                service_line(limbs["LF"], "TRIM"),
            ],
            appointment["version"],
        ),
        dispatcher,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_LIMB_LINE.value)
    assert response.status_code == 409
    assert service_lines_for(appointment["id"]) == [], "the call is atomic"
    assert read_appointment(appointment["id"])["service_units"] == 0


def test_invalid_service_type_enum_is_rejected(api, dispatcher):
    """PRD §2.7: "(22) Every enum-valued field carries a declared member, else
    `ERR_INVALID_ENUM` (HTTP 422)."
    PRD §2.7: "**This routing list is exhaustive and closed:** `Barn.zone`,
    `ServiceLine.service_type`, `Appointment.visit_kind`,
    `Appointment.warranty_reason`, `Farrier.certification_level`,
    `ShoeSku.material`, `LimbState.limb`, the members of
    `VetPrescription.limb_scope`, the members of `Barn.served_weekdays`, the
    `reason` field of farrier deactivation, the `delivery_outcome` field of reminder
    sending and the `direction` field of stop reordering route here."

    Design: Corner/validations/corner_invalid_service_type_enum_is_rejected
    """
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"])
    limbs = limb_ids(horse["id"])
    appointment = create_appointment(horse["id"], "2026-05-06")

    response = api.add_service_lines(
        appointment["id"],
        service_lines_payload(
            [service_line(limbs["LF"], "SHOEING")], appointment["version"]
        ),
        dispatcher,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)
    assert response.status_code == 422


def test_deleting_a_service_line_recomputes_every_rollup(api, dispatcher):
    """PRD §3.5: "Removing a line moves it from `PLANNED` to `REMOVED`. Only a
    `PLANNED` line can be removed; the appointment's `service_units` and
    `service_minutes` are recomputed, and if it is attached, the stop's
    `service_minutes` and the route's committed totals follow, and the reservation
    for the affected SKU has its `pairs` recomputed with any surplus pairs returning
    to the van bucket's `available_pairs`."
    PRD §3.4: "`committed_minutes` is the sum of `travel_minutes` over the route's
    non-`VOIDED` stops plus the sum of `service_minutes` over those same qualifying
    appointments."

    Design: Corner/endpoints/corner_deleting_a_service_line_recomputes_every_rollup
    """
    world = setup_reference(with_sku=False)
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    appointment, lines = setup_scheduled_visit(
        world, service_type="TRIM", scheduled_date="2026-05-06"
    )
    assert appointment["service_units"] == 4
    assert appointment["service_minutes"] == 38

    data = validate_success(api.delete_service_line(lines[0]["id"], dispatcher))

    assert_service_line(data)
    assert data["status"] == "REMOVED"
    after = read_appointment(appointment["id"])
    # Three TRIM limbs: 3 units, 3 x 8 chair minutes + 6 handling = 30.
    assert after["service_units"] == 3
    assert after["service_minutes"] == 30
    stop = read_stop(world["stop"]["id"])
    assert stop["service_minutes"] == 30
    assert stop["end_minute"] == 510
    route = read_route(world["route"]["id"])
    assert route["committed_units"] == 3
    assert route["committed_minutes"] == 45, "15 travel minutes plus 30 service minutes"


def test_service_line_add_with_a_stale_appointment_version_is_refused(api, dispatcher):
    """PRD §2.8: "Adding service lines requires `expected_appointment_version`
    matching the current `version` of the target `Appointment`. A mismatch is
    `ERR_STALE_APPOINTMENT_VERSION` (HTTP 412)."
    PRD §2.8: "Adding a second line for a different limb is perfectly valid on its
    own, so the appointment's status precondition cannot distinguish a caller who
    has seen the first line from one who has not; the version does."

    Design: Corner/cross_cutting_layers/corner_occ_service_line_add_with_a_stale_appointment_version_returns_412
    """
    barn = create_barn()
    client = create_client(barn["id"])
    horse = create_horse(client["id"], barn["id"])
    limbs = limb_ids(horse["id"])
    appointment = create_appointment(horse["id"], "2026-05-06")
    version_at_creation = appointment["version"]
    get_success_data(
        api.add_service_lines(
            appointment["id"],
            service_lines_payload(
                [service_line(limbs["LF"], "TRIM")], version_at_creation
            ),
            dispatcher,
        )
    )

    response = api.add_service_lines(
        appointment["id"],
        service_lines_payload(
            [service_line(limbs["RF"], "TRIM")], version_at_creation
        ),
        dispatcher,
    )

    validate_error(response, ApiErrorId.ERR_STALE_APPOINTMENT_VERSION.value)
    assert response.status_code == 412
    assert len(service_lines_for(appointment["id"])) == 1
    assert read_appointment(appointment["id"])["service_units"] == 1

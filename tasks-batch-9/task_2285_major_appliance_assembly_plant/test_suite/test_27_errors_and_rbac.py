"""Who is refused, and with which of the plant's twelve refusals.

Each entity answers a miss with its own not-found code; a submitter may never
decide their own change even after a re-submission moves the right around; the
single-role operations are closed to everyone else; the shared ones take either
owner; and a supplier portal sees only its own rows.
"""

from test_helpers import (
    ENGINEERING_LEAD_HEADERS,
    LINE_OPERATOR_HEADERS,
    PLANT_ADMIN_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    ApiErrorId,
    BomLineStatus,
    BuildSlotStatus,
    ChangeDecision,
    DeliveryCallStatus,
    EngineeringChangeStatus,
    LineOperatingMode,
    LinePosture,
    ModelVariantStatus,
    Plant,
    ShiftPlanStatus,
    SupplierStatus,
    TestType,
    approx2,
    base_plant,
    build_slot_payload,
    change_under_review,
    decide_payload,
    delivery_call_payload,
    engineering_change_payload,
    line_version,
    make_engineering_lead_headers,
    make_supplier_portal_headers,
    new_bom_line,
    new_delivery_call,
    new_line,
    new_model_variant,
    new_part,
    new_station,
    new_supplier,
    quality_test_payload,
    read_change,
    read_line,
    read_slot,
    record_arrival_payload,
    release_variant,
    run_checkpoint,
    set_clock,
    shift_plan_payload,
    start_line,
    stop_line,
    validate_error,
    validate_paginated,
    validate_success,
    variant_version,
    warranty_return_payload,
)

#: Well-formed identifiers that belong to no record of any collection.
_UNKNOWN_STATION = "00000000-0000-4000-8000-0000000000aa"
_UNKNOWN_SUPPLIER = "00000000-0000-4000-8000-0000000000bb"
_UNKNOWN_BOM_LINE = "00000000-0000-4000-8000-0000000000cc"
_UNKNOWN_CALL = "00000000-0000-4000-8000-0000000000dd"
_UNKNOWN_SHIFT_PLAN = "00000000-0000-4000-8000-0000000000ee"
_UNKNOWN_SLOT = "00000000-0000-4000-8000-0000000000ff"
_UNKNOWN_CHANGE = "00000000-0000-4000-8000-000000000011"
_UNKNOWN_RETURN = "00000000-0000-4000-8000-000000000022"
_UNKNOWN_UNIT = "00000000-0000-4000-8000-000000000033"
_UNKNOWN_VARIANT = "00000000-0000-4000-8000-000000000044"
_UNKNOWN_PART = "00000000-0000-4000-8000-000000000055"
_UNKNOWN_LINE = "00000000-0000-4000-8000-000000000066"


def _empty_plant(api):
    """A plant with a logical clock and nothing else in it."""
    set_clock(api, "2026-08-03T06:00:00Z")


def _two_supplier_plant(api):
    """One station serving two suppliers, each with one part and one dock call."""
    plant = Plant()
    set_clock(api, "2026-08-03T06:00:00Z")
    plant.line = new_line(api, "L1")
    plant.stations["ST10"] = new_station(api, plant.line_id, "ST10", 10)
    plant.supplier = new_supplier(api, "SUP1", "Hinge and Module Co",
                                  sync_window_minutes=30)
    plant.suppliers["SUP1"] = plant.supplier
    plant.parts["P-DOOR-A"] = new_part(api, plant.supplier_id, "P-DOOR-A")
    own_call = new_delivery_call(api, plant.supplier_id, plant.part_id,
                                plant.st10_id, "2026-08-03T09:00:00Z",
                                "2026-08-03T10:00:00Z")
    other = new_supplier(api, "SUP2", "Hose Partners SA", sync_window_minutes=30)
    plant.suppliers["SUP2"] = other
    plant.parts["P-HOSE-B"] = new_part(api, other["id"], "P-HOSE-B",
                                       line_side_max_units=12)
    other_call = new_delivery_call(api, other["id"], plant.parts["P-HOSE-B"]["id"],
                                   plant.st10_id, "2026-08-03T11:00:00Z",
                                   "2026-08-03T12:00:00Z")
    return plant, own_call, other_call


class TestNotFoundCodesPerEntity:
    """A miss is reported in the vocabulary of the collection that was missed."""

    def test_each_collection_answers_an_unknown_identifier_in_its_own_words(self, api):
        """Eight collections, eight distinct not-found codes, all at 404.

        "The `{id}` path parameter resolves to an entity of the endpoint's own type, on
        every endpoint carrying one, and the failure carries that entity's own not-found
        code: `ERR_LINE_NOT_FOUND`, `ERR_STATION_NOT_FOUND`,
        `ERR_MODEL_VARIANT_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_PART_NOT_FOUND`,
        `ERR_BOM_LINE_NOT_FOUND`, `ERR_DELIVERY_CALL_NOT_FOUND`,
        `ERR_SHIFT_PLAN_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
        `ERR_PRODUCTION_UNIT_NOT_FOUND`, `ERR_ENGINEERING_CHANGE_NOT_FOUND` or
        `ERR_WARRANTY_RETURN_NOT_FOUND`."

        Design: Corner/errors/remaining_not_found_codes_are_each_reachable_on_their_own_endpoint
        """
        _empty_plant(api)

        validate_error(
            api.get_station(_UNKNOWN_STATION, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_STATION_NOT_FOUND, expected_status=404,
        )
        validate_error(
            api.get_supplier(_UNKNOWN_SUPPLIER, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_SUPPLIER_NOT_FOUND, expected_status=404,
        )
        validate_error(
            api.get_bom_line(_UNKNOWN_BOM_LINE, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_BOM_LINE_NOT_FOUND, expected_status=404,
        )
        validate_error(
            api.get_delivery_call(_UNKNOWN_CALL, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_DELIVERY_CALL_NOT_FOUND, expected_status=404,
        )
        validate_error(
            api.get_shift_plan(_UNKNOWN_SHIFT_PLAN, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_SHIFT_PLAN_NOT_FOUND, expected_status=404,
        )
        validate_error(
            api.get_build_slot(_UNKNOWN_SLOT, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_BUILD_SLOT_NOT_FOUND, expected_status=404,
        )
        validate_error(
            api.get_engineering_change(_UNKNOWN_CHANGE, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_ENGINEERING_CHANGE_NOT_FOUND, expected_status=404,
        )
        validate_error(
            api.get_warranty_return(_UNKNOWN_RETURN, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_WARRANTY_RETURN_NOT_FOUND, expected_status=404,
        )


class TestSegregationOfDuties:
    """The right to decide belongs to whoever did not submit, last submit winning."""

    def test_the_current_submitter_is_refused_and_the_other_lead_decides(self, api):
        """A re-submission swaps which of the two leads may approve.

        "Deciding is where segregation of duties bites. The decision request carries a
        `decision` of `APPROVE`, `REJECT` or `REQUEST_REVISION` and an optional `note`,
        requires the change to be `UNDER_REVIEW`, and requires the deciding `X-User-ID`
        to differ from the change's `submitted_by_user_id`; a submitter attempting to
        decide their own change is refused with `ERR_SEGREGATION_OF_DUTIES`."

        "Submitting takes the change `DRAFT → SUBMITTED`, or `REVISION_REQUESTED →
        SUBMITTED` on a second pass; either way `submitted_by_user_id` is set to the
        submitting `X-User-ID`, last submit winning, so a new submitter resets who is
        allowed to decide."

        Design: Corner/errors/segregation_of_duties_forbids_the_current_submitter_from_deciding
        """
        plant = base_plant(api)
        first_lead = make_engineering_lead_headers("eng-1")
        second_lead = make_engineering_lead_headers("eng-2")
        change = change_under_review(api, plant, first_lead)
        assert change["submitted_by_user_id"] == "eng-1"

        validate_error(
            api.decide_engineering_change(
                change["id"], decide_payload(ChangeDecision.APPROVE.value),
                first_lead,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )

        blocked = read_change(api, change["id"])
        assert blocked["status"] == EngineeringChangeStatus.UNDER_REVIEW.value
        assert blocked["decided_by_user_id"] is None
        assert blocked["revision_round"] == 0

        returned = validate_success(
            api.decide_engineering_change(
                change["id"],
                decide_payload(ChangeDecision.REQUEST_REVISION.value,
                               "add the tooling impact"),
                second_lead,
            )
        )

        assert returned["status"] == EngineeringChangeStatus.REVISION_REQUESTED.value
        assert returned["revision_round"] == 1
        assert returned["decided_by_user_id"] == "eng-2"

        resubmitted = validate_success(
            api.submit_engineering_change(change["id"], second_lead)
        )

        assert resubmitted["status"] == EngineeringChangeStatus.SUBMITTED.value
        assert resubmitted["submitted_by_user_id"] == "eng-2"
        validate_success(
            api.start_review_engineering_change(change["id"], second_lead)
        )

        validate_error(
            api.decide_engineering_change(
                change["id"], decide_payload(ChangeDecision.APPROVE.value),
                second_lead,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )

        approved = validate_success(
            api.decide_engineering_change(
                change["id"], decide_payload(ChangeDecision.APPROVE.value),
                first_lead,
            )
        )

        assert approved["status"] == EngineeringChangeStatus.APPROVED.value
        assert approved["decided_by_user_id"] == "eng-1"
        assert approved["revision_round"] == 1


class TestExclusiveOperations:
    """A single-role operation refuses every other role before it looks anything up."""

    def test_nine_single_role_operations_refuse_the_wrong_role_outright(self, api):
        """The role check outranks the identifiers in the path and the body.

        "`X-User-Role` is one of the seven roles and appears on the endpoint's
        authorized-role list, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/exclusive_operations_are_forbidden_to_every_other_role
        """
        _empty_plant(api)

        validate_error(
            api.sequence_build_slot(_UNKNOWN_SLOT, LINE_OPERATOR_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403,
        )
        validate_error(
            api.release_build_slot(_UNKNOWN_SLOT, PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403,
        )
        validate_error(
            api.record_quality_test(
                _UNKNOWN_UNIT,
                quality_test_payload(TestType.ELECTRICAL_SAFETY.value, 0.30),
                LINE_OPERATOR_HEADERS,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403,
        )
        validate_error(
            api.certify_unit(_UNKNOWN_UNIT, PLANT_ADMIN_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403,
        )
        validate_error(
            api.ship_unit(_UNKNOWN_UNIT, QUALITY_INSPECTOR_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403,
        )
        validate_error(
            api.create_engineering_change(
                engineering_change_payload(_UNKNOWN_VARIANT, _UNKNOWN_PART,
                                           _UNKNOWN_LINE),
                PLANT_ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403,
        )
        validate_error(
            api.create_warranty_return(warranty_return_payload(_UNKNOWN_UNIT),
                                       ENGINEERING_LEAD_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403,
        )
        validate_error(
            api.record_arrival(_UNKNOWN_CALL,
                               record_arrival_payload("2026-08-03T09:30:00Z"),
                               PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403,
        )
        validate_error(
            api.get_warranty_metrics(_UNKNOWN_PART, PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403,
        )


class TestSharedOperations:
    """Where two roles own an operation, either of them may perform it."""

    def test_the_plant_administrator_may_do_everything_the_planner_may_do(self, api):
        """Authoring, planning, booking, stopping, starting and sweeping, all as admin.

        "`X-User-Role` is one of the seven roles and appears on the endpoint's
        authorized-role list, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED`."

        "An engineering lead or a plant administrator authors a line by supplying the
        `model_variant_id` it belongs to, the `part_id` consumed, the `station_id` where
        that part is presented, the `bom_position_code` naming the stable position inside
        the variant (for instance `DOOR-ASSY`), the `qty_per_unit` pieces consumed per
        appliance (a positive quantity of at least 1), an `effective_from_sequence` of at
        least 1 that defaults to 1 and names the first build-slot `sequence_index` the
        line applies to, and the mandatory `expected_model_variant_version` of §2.7."

        Design: Corner/rbac/shared_operations_accept_either_owning_role
        """
        set_clock(api, "2026-08-03T06:00:00Z")
        line = new_line(api, "L1")
        st10 = new_station(api, line["id"], "ST10", 10,
                           presentation_slot_capacity=40, station_cycle_seconds=110)
        st20 = new_station(api, line["id"], "ST20", 20,
                          presentation_slot_capacity=40, station_cycle_seconds=110)
        supplier = new_supplier(api, "SUP1", "Hinge and Module Co",
                                sync_window_minutes=30)
        part = new_part(api, supplier["id"], "P-DOOR-A")
        variant = new_model_variant(api, "WM-X")
        new_bom_line(api, variant["id"], part["id"], st10["id"], variant["version"],
                     "POS-DOOR", headers=ENGINEERING_LEAD_HEADERS)

        second_position = new_bom_line(
            api, variant["id"], part["id"], st20["id"],
            variant_version(api, variant["id"]), "POS-LID",
            headers=PLANT_ADMIN_HEADERS, qty_per_unit=1,
        )

        assert second_position["status"] == BomLineStatus.ACTIVE.value
        assert second_position["qty_per_unit"] == 1
        assert release_variant(api, variant["id"])["status"] == \
            ModelVariantStatus.RELEASED.value

        plan = validate_success(
            api.create_shift_plan(
                shift_plan_payload(line["id"], line_version(api, line["id"])),
                PLANT_ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert plan["status"] == ShiftPlanStatus.ACTIVE.value
        assert plan["available_labor_minutes"] == 480

        slot = validate_success(
            api.create_build_slot(
                build_slot_payload(line["id"], variant["id"], 1,
                                   "2026-08-03T07:00:00Z"),
                PLANT_ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert slot["status"] == BuildSlotStatus.PLANNED.value

        call = validate_success(
            api.create_delivery_call(
                delivery_call_payload(supplier["id"], part["id"], st10["id"],
                                      "2026-08-03T09:00:00Z",
                                      "2026-08-03T10:00:00Z", sequenced_qty=4),
                PLANT_ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert call["status"] == DeliveryCallStatus.SCHEDULED.value

        stopped = stop_line(api, line["id"], "SAFETY_DRILL",
                            headers=PLANT_ADMIN_HEADERS)

        assert stopped["operating_mode"] == LineOperatingMode.STOPPED.value
        assert stopped["posture"] == LinePosture.STOPPED.value

        restarted = start_line(api, line["id"], headers=PLANT_ADMIN_HEADERS)

        assert restarted["operating_mode"] == LineOperatingMode.RUNNING.value
        assert restarted["current_family_code"] == "FAM_A"
        assert restarted["changeover_count"] == 0

        report = run_checkpoint(api, line["id"], headers=PLANT_ADMIN_HEADERS)

        assert report["checkpoint_index"] == 1
        assert read_line(api, line["id"])["checkpoint_index"] == 1
        assert read_slot(api, slot["id"])["status"] == BuildSlotStatus.PLANNED.value


class TestSupplierPortalScope:
    """The portal is a keyhole: the caller's own rows and nothing else."""

    def test_the_portal_reads_its_own_rows_and_is_refused_the_other_supplier_s(
            self, api):
        """Explicit foreign reads are refused; unfiltered lists are silently narrowed.

        "Ownership checks compare the target row's `supplier_id` foreign key to
        `X-User-ID`: recording an arrival against a delivery call belonging to another
        supplier, reading another supplier's record, listing delivery calls that are not
        the caller's own, or filtering the part catalogue by a `supplier_id` other than
        the caller's own are all rejected with `ERR_SUPPLIER_SCOPE_VIOLATION`."

        "A `SupplierPortal` caller who supplies no `supplier_id` filter on a list read
        sees only its own rows."

        Design: Corner/rbac/supplier_portal_reads_are_scoped_to_the_calling_supplier
        """
        plant, own_call, other_call = _two_supplier_plant(api)
        portal = make_supplier_portal_headers(plant.supplier_id)
        other = plant.suppliers["SUP2"]

        mine = validate_success(api.get_supplier(plant.supplier_id, portal))

        assert mine["supplier_code"] == "SUP1"
        assert float(mine["on_time_score"]) == approx2(100.00)
        assert mine["status"] == SupplierStatus.APPROVED.value

        validate_error(
            api.get_supplier(other["id"], portal),
            ApiErrorId.ERR_SUPPLIER_SCOPE_VIOLATION, expected_status=403,
        )

        own_calls, own_meta = validate_paginated(api.list_delivery_calls(portal))

        assert own_meta["total_count"] == 1
        assert own_calls[0]["id"] == own_call["id"]

        validate_error(
            api.get_delivery_call(other_call["id"], portal),
            ApiErrorId.ERR_SUPPLIER_SCOPE_VIOLATION, expected_status=403,
        )
        validate_error(
            api.list_parts(portal, {"supplier_id": other["id"]}),
            ApiErrorId.ERR_SUPPLIER_SCOPE_VIOLATION, expected_status=403,
        )

        own_parts, parts_meta = validate_paginated(api.list_parts(portal))

        assert parts_meta["total_count"] == 1
        assert own_parts[0]["part_number"] == "P-DOOR-A"

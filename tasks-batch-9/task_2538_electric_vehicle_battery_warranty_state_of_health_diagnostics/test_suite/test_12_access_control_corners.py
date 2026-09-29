"""Three separate access rungs, and the identity rule that outlives them all.

Authentication is a membership test on the role string, authorisation is
per-operation and per-role rather than per-verb, actor attribution is a third
rung of its own, and the two-person rule compares two opaque identities across
two entities.
"""

from test_helpers import (
    ADJUDICATOR_1_ID,
    ADJUDICATOR_2_ID,
    ApiErrorId,
    NO_HEADERS,
    adjudicate_payload,
    assert_lab_deviation,
    build_user_headers,
    file_dispute,
    headers_without_actor,
    make_adjudicator_headers,
    make_gateway_headers,
    make_lab_headers,
    make_liaison_headers,
    make_owner_headers,
    read_claim,
    read_dispute,
    read_program,
    read_vehicle,
    read_vehicle_version,
    record_lab_result,
    resolve_payload,
    setup_adjudicated_claim_world,
    setup_base_world,
    setup_program,
    setup_submitted_claim_world,
    snapshot_payload,
    telematics_assessment_payload,
    thermal_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
    vehicle_payload,
    ingest_snapshot,
    list_vehicles,
)


class TestUnauthenticatedOutranksEverything:
    """Rung 1 answers first, whatever else is wrong with the request."""

    def test_a_missing_role_and_a_plausible_non_member_both_answer_401(self, api):
        """A bogus path and a malformed body are never reached at all.

        PRD 2.1: "If `X-User-Role` is absent, or carries a string that is not one of the
        seven recognised roles, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        PRD 2.7: "1. Role authentication — `ERR_UNAUTHENTICATED`." / "4. Request shape
        on every write ... — `ERR_INVALID_REQUEST`." / "6. Existence of every
        path-parameter resource, left to right."

        Design: Corner/rbac/request_with_absent_or_unknown_role_returns_unauthenticated
        """
        program = setup_program(api)

        validate_error(
            api.get_warranty_program(program["id"], NO_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            expected_status=401,
        )

        # "Adjudicator" is not a member of the declared set; "WarrantyAdjudicator" is.
        validate_error(
            api.get_warranty_program(
                program["id"], build_user_headers(ADJUDICATOR_1_ID, "Adjudicator")
            ),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            expected_status=401,
        )

        # Rung 1 precedes rung 6: a bogus id still answers 401, not 404.
        validate_error(
            api.get_battery_pack("pack_missing", NO_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            expected_status=401,
        )

        # Rung 1 precedes rung 4: a structurally invalid body still answers 401.
        validate_error(
            api.create_vehicle({"vin": 12345}, NO_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            expected_status=401,
        )
        _, meta = list_vehicles(api)
        assert meta["total_count"] == 0


class TestWriteFamiliesAreSingleRole:
    """Four writes crossed pairwise, and one read that stays open."""

    def test_each_role_is_refused_on_another_family_s_write_but_not_on_the_read(
        self, api
    ):
        """The gateway writes telematics and nothing else; the technician the reverse.

        PRD 2.1: "If the role is recognised but is not among the roles authorised for the
        target operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD 4: "POST `/battery-warranty/vehicles/{id}/telematics-snapshots` ... |
        TelematicsGateway" / "POST `/battery-warranty/soh-assessments` ... |
        ServiceTechnician" / "POST `/battery-warranty/vehicles` ... | ProgramAdmin" /
        "POST `/battery-warranty/thermal-events` ... | ServiceTechnician,
        TelematicsGateway".

        PRD 4: "GET `/battery-warranty/vehicles/{id}/telematics-snapshots` ... |
        ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, TelematicsGateway,
        VehicleOwner, IndependentLab, RegulatoryLiaison".

        Design: Corner/rbac/cross_role_writes_are_unauthorized_for_every_write_family
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000561"},
            pack_overrides={"serial_number": "PK-C361"},
            snapshots=None,
        )
        version_before = read_vehicle_version(
            api, world["vehicle_id"], world["technician_id"]
        )

        # The technician cannot ingest telematics.
        validate_error(
            api.ingest_snapshot(
                world["vehicle_id"],
                snapshot_payload("2026-07-20T00:00:00Z", 71000, 56.000),
                world["tech_headers"],
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )

        # The gateway cannot author an assessment, and the refusal consumes no version.
        validate_error(
            api.create_assessment(
                telematics_assessment_payload(
                    world["vehicle_id"],
                    world["pack_id"],
                    world["technician_id"],
                    version_before,
                ),
                make_gateway_headers(),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )
        assert (
            read_vehicle_version(api, world["vehicle_id"], world["technician_id"])
            == version_before
        )

        # The adjudicator cannot register a vehicle.
        validate_error(
            api.create_vehicle(
                vehicle_payload(world["program_id"], vin="5YJ3E1EA7KF000562"),
                make_adjudicator_headers(ADJUDICATOR_1_ID),
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )
        _, meta = list_vehicles(api)
        assert meta["total_count"] == 1

        # The owner cannot report a thermal event: that route admits two roles, and
        # VehicleOwner is neither of them.
        validate_error(
            api.create_thermal_event(
                thermal_event_payload(
                    world["vehicle_id"],
                    world["pack_id"],
                    "S2",
                    "2026-07-30T00:00:00Z",
                ),
                world["owner_headers"],
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )

        # The read side of the very resource the owner may not write is open to them.
        rows, snapshot_meta = validate_paginated(
            api.list_snapshots(world["vehicle_id"], world["owner_headers"])
        )
        assert rows == []
        assert snapshot_meta["total_count"] == 0


class TestActorAttributionIsItsOwnRung:
    """The role is right and the claim is adjudicable; only the identity is missing."""

    def test_the_identity_less_adjudication_is_a_400_and_the_identified_one_settles(
        self, api
    ):
        """Rung 3 fires on a claim that would otherwise have been approved outright.

        PRD 2.1: "A third, narrower rule covers actor attribution: on the operations that
        persist who performed them — claim adjudication, claim fulfilment, dispute
        resolution, shipment tender, and the recording of an owner's consent decision — a
        missing `X-User-ID` header is rejected with `ERR_ACTOR_REQUIRED` (HTTP 400) even
        when the role itself is acceptable."

        PRD 3.5: "Whichever branch is taken, the decision writes the acting `X-User-ID`
        into `adjudicated_by_user_id`, and that value is what the dispute two-person rule
        later compares against."

        PRD 3.5: "On success the settlement fields are computed as described below, the
        resulting `oem_total_cents` is added to the program's `accrued_liability_cents`,
        and `adjudicated_by_user_id` is stamped."

        Design: Corner/rbac/adjudicate_with_missing_required_actor_header_returns_actor_required
        """
        world = setup_submitted_claim_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000571"},
            pack_overrides={"serial_number": "PK-C371"},
        )
        assert world["claim"]["adjudication_status"] == "SUBMITTED"
        assert world["claim"]["recommended_remedy"] == "MODULE_REPLACEMENT"

        decision = adjudicate_payload("MODULE_REPLACEMENT")
        validate_error(
            api.adjudicate_claim(
                world["claim_id"], decision, headers_without_actor("WarrantyAdjudicator")
            ),
            ApiErrorId.ERR_ACTOR_REQUIRED.value,
            expected_status=400,
        )

        refused = read_claim(api, world["claim_id"])
        assert refused["adjudication_status"] == "SUBMITTED"
        assert refused["approved_remedy"] is None
        assert refused["adjudicated_by_user_id"] is None
        assert refused["oem_total_cents"] is None
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 0

        # The byte-identical decision, now carrying an identity to persist.
        approved = validate_success(
            api.adjudicate_claim(
                world["claim_id"], decision, make_adjudicator_headers(ADJUDICATOR_1_ID)
            )
        )
        assert approved["adjudication_status"] == "APPROVED_MODULE"
        assert approved["adjudicated_by_user_id"] == ADJUDICATOR_1_ID
        assert approved["remedy_cost_cents"] == 363092
        assert approved["admin_fee_cents"] == 7500
        assert approved["oem_total_cents"] == 370592
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 370592


class TestTwoPersonRuleOnDisputeResolution:
    """Both actors carry the same role, so only the identity comparison can refuse."""

    def test_the_deciding_adjudicator_is_refused_and_a_second_one_resolves(self, api):
        """adj-001 cannot review adj-001; adj-002 upholds the same dispute unchanged.

        PRD 3.9: "The acting `X-User-ID` must differ from the claim's
        `adjudicated_by_user_id`, or the resolution is refused with
        `ERR_SEGREGATION_OF_DUTIES` and HTTP 403: the adjudicator who decided the claim
        may not sit in judgement on the challenge to that decision."

        PRD 3.9: "Everything in between, boundaries included, yields `RESOLVED_UPHELD` —
        so with the default tolerance of 2.00 a deviation of exactly minus 2.00 or
        exactly plus 2.00 upholds the original decision." / "`RESOLVED_UPHELD` touches
        the claim not at all: no state change, no settlement change, no ledger movement."

        PRD 3.9: "an already-resolved dispute is refused with `ERR_DISPUTE_RESOLVED`."

        Design: Corner/rbac/same_adjudicator_cannot_resolve_the_dispute_on_their_own_claim
        """
        world = setup_adjudicated_claim_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000581"},
            pack_overrides={"serial_number": "PK-C381"},
            adjudicator_id=ADJUDICATOR_1_ID,
        )
        assert world["claim"]["adjudicated_by_user_id"] == ADJUDICATOR_1_ID
        assert world["claim"]["oem_total_cents"] == 370592

        file_dispute(
            api,
            world,
            lab_name="Statewide Cell Lab",
            owner_statement="the meter reads lower than the app",
        )
        # 57.600 / 80.000 is 72.00 %, exactly two points above the frozen 70.00 %:
        # ABS(2.00) is not greater than the 2.00-point tolerance, so no retest is due.
        measured = record_lab_result(api, world, 57.600, lab_report_reference="LAB-1")
        assert measured["dispute_status"] == "LAB_RESULT_RECEIVED"
        assert measured["lab_retention_pct"] == 72.00
        assert measured["deviation_pct"] == 2.00
        assert measured["retest_count"] == 0
        assert_lab_deviation(measured)

        validate_error(
            api.resolve_dispute(
                world["dispute_id"],
                resolve_payload("self-review"),
                make_adjudicator_headers(ADJUDICATOR_1_ID),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            expected_status=403,
        )
        held = read_dispute(api, world["dispute_id"])
        assert held["dispute_status"] == "LAB_RESULT_RECEIVED"
        assert held["resolved_by_user_id"] is None

        resolved = validate_success(
            api.resolve_dispute(
                world["dispute_id"],
                resolve_payload("independent review confirms the OEM measurement"),
                make_adjudicator_headers(ADJUDICATOR_2_ID),
            )
        )
        assert resolved["dispute_status"] == "RESOLVED_UPHELD"
        assert resolved["resolved_by_user_id"] == ADJUDICATOR_2_ID

        # An upheld dispute moves no money and does not touch the claim.
        untouched = read_claim(api, world["claim_id"])
        assert untouched["adjudication_status"] == "APPROVED_MODULE"
        assert untouched["oem_total_cents"] == 370592
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 370592

        validate_error(
            api.resolve_dispute(
                world["dispute_id"],
                resolve_payload("second bite"),
                make_adjudicator_headers(ADJUDICATOR_2_ID),
            ),
            ApiErrorId.ERR_DISPUTE_RESOLVED.value,
            expected_status=409,
        )


class TestGatewayReadGrantIsNarrow:
    """The same role, two routes: authorised on one read and absent from the other."""

    def test_the_gateway_cannot_read_the_vehicle_but_can_list_its_snapshots(self, api):
        """Three other roles read the identical vehicle payload, and no read writes.

        PRD 4: "GET `/battery-warranty/vehicles/{vehicle_id}` | Read a vehicle, including
        its installed-pack mirror. | ProgramAdmin, WarrantyAdjudicator, ServiceTechnician,
        VehicleOwner, IndependentLab, RegulatoryLiaison".

        PRD 4: "GET `/battery-warranty/vehicles/{id}/telematics-snapshots` | List a
        vehicle's telematics snapshots, newest capture first, filterable by validity. |
        ProgramAdmin, WarrantyAdjudicator, ServiceTechnician, TelematicsGateway,
        VehicleOwner, IndependentLab, RegulatoryLiaison".

        PRD 3.2: "the field is thereafter derived: it holds the highest `odometer_miles`
        seen across that vehicle's snapshots whose validity flag reads `VALID`."

        Design: Corner/rbac/telematics_gateway_is_unauthorized_on_reads_the_other_six_roles_share
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000591"},
            pack_overrides={"serial_number": "PK-C391"},
            snapshots=None,
        )
        ingest_snapshot(api, world["vehicle_id"], "2026-07-20T00:00:00Z", 71000, 56.000)
        gateway = make_gateway_headers()

        validate_error(
            api.get_vehicle(world["vehicle_id"], gateway),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )

        # The same role, a different route: the one it writes it may also read.
        rows, meta = validate_paginated(
            api.list_snapshots(world["vehicle_id"], gateway)
        )
        assert meta["total_count"] == 1
        assert rows[0]["validity_flag"] == "VALID"

        baseline = read_vehicle(api, world["vehicle_id"])
        for headers in (
            make_liaison_headers(),
            make_lab_headers(),
            make_owner_headers(world["vehicle_id"]),
        ):
            vehicle = validate_success(api.get_vehicle(world["vehicle_id"], headers))
            assert vehicle["odometer_miles"] == 71000
            assert vehicle["installed_pack_id"] == world["pack_id"]
            assert vehicle["status"] == "ACTIVE"
            assert vehicle["warranty_hold"] is False
            # No read of any kind advances the optimistic-concurrency token.
            assert vehicle["version"] == baseline["version"]

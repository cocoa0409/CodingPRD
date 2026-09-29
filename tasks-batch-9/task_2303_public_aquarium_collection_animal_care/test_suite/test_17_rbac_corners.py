"""Role-boundary corners: who may call what, and with which action value.

The expectations here come from the role table of PRD §2.1, the endpoint
authorization column of PRD §4 and the identity-and-authorization ranks 3, 4 and
13 of the rejection ladder in PRD §2.8.
"""
from test_helpers import (
    AQUARIST_HEADERS,
    AQUARIST_ID,
    CURATOR_HEADERS,
    DIRECTOR_HEADERS,
    DIRECTOR_ID,
    PERMIT_OFFICER_HEADERS,
    VET_HEADERS,
    VET_ID,
    assertions,
    factories,
    is_iso8601_timestamp,
    make_director_headers,
    make_liaison_headers,
    reading_for,
    shift,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_INSTITUTION_SCOPE_VIOLATION,
    ERR_SOD_VIOLATION,
    ERR_UNAUTHORIZED,
)


def test_the_permit_officer_files_the_dossier_and_the_director_decides_it(api, build):
    """Drafting and submitting a permit belong to the officer; the decision belongs to the director.

    PRD §4: "POST `/aquarium/permits/{id}/submission` — Submit or resubmit the permit to the authority ... PermitOfficer"

    Design: Corner/rbac/rbac_permit_officer_prepares_but_never_decides_a_permit
    """
    world = build.approved_line(
        species_overrides={"wild_take_quota_annual": 6},
        entry_overrides={"sustainability_requirement": "GREEN_ONLY"},
    )
    institution = build.create_institution(welfare_audit_score=88.00)
    request = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
    )
    request = build.submit_acquisition(request["id"])
    assert request["status"] == "PENDING_PERMIT"

    permit = build.draft_permit(
        request["id"], "IMPORT", ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE"]
    )
    assertions.assert_permit(permit)
    assert permit["status"] == "DRAFT"
    assert permit["submission_round"] == 0
    assert permit["missing_document_codes"] == []

    # The officer who filed the dossier may not also decide it. Authorization is
    # rank 3, so it answers before the state machine could object to an ISSUE on
    # a DRAFT permit.
    validate_error(
        api.decide_permit(
            permit["id"],
            factories.permit_decision_payload(
                "ISSUE", valid_from=build.now, valid_until=shift(build.now, days=365)
            ),
            PERMIT_OFFICER_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    # And the director may not file on the officer's behalf.
    validate_error(api.submit_permit(permit["id"], {}, DIRECTOR_HEADERS), ERR_UNAUTHORIZED, 403)

    held = build.get_permit(permit["id"])
    assert held["status"] == "DRAFT"
    assert held["submission_round"] == 0
    # PRD §3.5 stamps `issued_at` on a permit decision (`decided_at` belongs to
    # transfer requests), so a refused decision must leave it null.
    assert held["issued_at"] is None
    assert held["decision_reason"] is None

    submitted = validate_success(api.submit_permit(permit["id"], {}, PERMIT_OFFICER_HEADERS))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_round"] == 1
    assert submitted["missing_document_codes"] == []

    issued = validate_success(
        api.decide_permit(
            permit["id"],
            factories.permit_decision_payload(
                "ISSUE", valid_from=build.now, valid_until=shift(build.now, days=365)
            ),
            DIRECTOR_HEADERS,
        )
    )
    assert issued["status"] == "ISSUED"
    assert is_iso8601_timestamp(issued["issued_at"])
    assert issued["valid_from"] is not None
    assert issued["valid_until"] is not None


def test_the_aquarist_records_water_quality_but_cannot_touch_the_plan_or_the_exhibit(api, build):
    """Floor operations belong to the aquarist; plan actions and exhibit edits to the director.

    PRD §4: "POST `/aquarium/life-support-systems/{id}/water-quality-readings` — Append an immutable water-quality reading; drives the alarm state machine. AquaristTechnician"

    Design: Corner/rbac/rbac_aquarist_owns_the_floor_but_not_the_collection_plan
    """
    world = build.approved_line()
    plant = world["plant"]
    exhibit = world["exhibit"]
    entry = world["entry"]
    assert entry["status"] == "APPROVED"
    version_before = build.exhibit_version(exhibit["id"])

    # Plan-entry status actions are the director's alone.
    validate_error(
        api.plan_entry_status_action(
            entry["id"],
            factories.plan_status_action_payload("SUSPEND", reason="ad hoc floor decision"),
            AQUARIST_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    unmoved_entry = validate_success(api.get_collection_plan_entry(entry["id"], CURATOR_HEADERS))
    assert unmoved_entry["status"] == "APPROVED"
    assert unmoved_entry["suspension_reason"] is None

    # So is the version-guarded exhibit edit — the guard token is correct here, so
    # only the role can be the reason for the refusal.
    validate_error(
        api.update_exhibit(
            exhibit["id"],
            factories.exhibit_patch_payload(version_before, bioload_capacity_units=250.0),
            AQUARIST_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    untouched_exhibit = build.get_exhibit(exhibit["id"])
    assert untouched_exhibit["version"] == version_before
    assertions.assert_scaled_equal(untouched_exhibit["bioload_capacity_units"], 100.00)

    # Conversely the director may not append a reading, even though the director
    # registered the plant.
    validate_error(
        api.create_water_quality_reading(
            plant["id"], reading_for("COLD_MARINE", "NORMAL", build.now), DIRECTOR_HEADERS
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    _, empty_meta = validate_paginated(
        api.list_water_quality_readings(plant["id"], CURATOR_HEADERS)
    )
    assert empty_meta["total_count"] == 0

    reading = validate_success(
        api.create_water_quality_reading(
            plant["id"], reading_for("COLD_MARINE", "NORMAL", build.now), AQUARIST_HEADERS
        ),
        201,
    )
    assertions.assert_water_quality_reading(reading)
    assert reading["severity"] == "NORMAL"
    _, one_meta = validate_paginated(api.list_water_quality_readings(plant["id"], CURATOR_HEADERS))
    assert one_meta["total_count"] == 1
    assert build.get_plant(plant["id"])["alarm_state"] == "NORMAL"


def test_the_transfer_decision_endpoint_splits_its_vocabulary_between_two_roles(api, build):
    """APPROVE belongs to the director and COUNTER to the liaison on one shared endpoint.

    PRD §2.8: "The caller's role is listed for the endpoint and, on the two action-driven endpoints that carry per-action restrictions, for the specific value supplied — `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/rbac_transfer_decisions_are_split_by_action_value_between_two_roles
    """
    world = build.specimen_on_exhibit()
    receiver = build.create_institution(
        accreditation_status="ACCREDITED", welfare_audit_score=88.00
    )
    liaison = make_liaison_headers(receiver["id"])

    transfer = build.draft_transfer(
        world["specimen"]["id"],
        receiver["id"],
        shift(build.now, days=30),
        welfare_conditions=["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN"],
    )
    transfer = build.submit_transfer(transfer["id"])
    assert transfer["status"] == "SUBMITTED"
    assert transfer["negotiation_round"] == 0

    # The director holds the endpoint but not the COUNTER value.
    validate_error(
        api.decide_transfer_request(
            transfer["id"],
            factories.transfer_decision_payload(
                "COUNTER", counter_conditions=["QUARANTINE_ON_ARRIVAL"]
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    # The liaison holds the endpoint but not the APPROVE value.
    validate_error(
        api.decide_transfer_request(
            transfer["id"], factories.transfer_decision_payload("APPROVE"), liaison
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    held = validate_success(api.get_transfer_request(transfer["id"], PERMIT_OFFICER_HEADERS))
    assert held["status"] == "SUBMITTED"
    assert held["negotiation_round"] == 0
    assert held["decided_by_user_id"] is None
    assert held["counter_conditions"] == []

    countered = validate_success(
        api.decide_transfer_request(
            transfer["id"],
            factories.transfer_decision_payload(
                "COUNTER", counter_conditions=["QUARANTINE_ON_ARRIVAL"]
            ),
            liaison,
        )
    )
    assertions.assert_transfer_request(countered)
    assert countered["status"] == "COUNTERED"
    assert countered["negotiation_round"] == 1
    assert countered["counter_conditions"] == ["QUARANTINE_ON_ARRIVAL"]
    # A liaison's audit anchor is the institution it speaks for (§2.1).
    assert countered["decided_by_user_id"] == receiver["id"]

    resubmitted = validate_success(
        api.submit_transfer_request(
            transfer["id"],
            {
                "welfare_conditions": [
                    "WATER_CHEMISTRY_MATCH",
                    "TRANSPORT_OXYGEN_PLAN",
                    "QUARANTINE_ON_ARRIVAL",
                ]
            },
            PERMIT_OFFICER_HEADERS,
        )
    )
    assert resubmitted["status"] == "SUBMITTED"

    approved = validate_success(
        api.decide_transfer_request(
            transfer["id"], factories.transfer_decision_payload("APPROVE"), DIRECTOR_HEADERS
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == DIRECTOR_ID
    assert build.get_specimen(world["specimen"]["id"])["disposition_status"] == "TRANSFER_PENDING"


def test_a_liaison_sees_and_decides_only_its_own_institutions_inbound_transfers(api, build):
    """A liaison's institution scope filters its list and blocks a foreign read or decision.

    PRD §2.1: "A liaison that decides on, or reads, a transfer request addressed to a different institution is rejected with `ERR_INSTITUTION_SCOPE_VIOLATION` (403), and a liaison listing transfer requests sees only the rows whose `receiving_institution_id` equals its own `X-User-ID`."

    Design: Corner/rbac/rbac_liaison_sees_only_the_transfers_addressed_to_its_own_institution
    """
    world = build.specimen_on_exhibit()
    addressee = build.create_institution(
        name="Addressed Aquarium", accreditation_status="ACCREDITED", welfare_audit_score=88.00
    )
    bystander = build.create_institution(
        name="Bystander Aquarium", accreditation_status="ACCREDITED", welfare_audit_score=88.00
    )
    own_liaison = make_liaison_headers(addressee["id"])
    foreign_liaison = make_liaison_headers(bystander["id"])

    transfer = build.draft_transfer(
        world["specimen"]["id"],
        addressee["id"],
        shift(build.now, days=30),
        welfare_conditions=["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN"],
    )
    transfer = build.submit_transfer(transfer["id"])
    assert transfer["receiving_institution_id"] == addressee["id"]
    assert transfer["status"] == "SUBMITTED"

    # A single read by the wrong liaison is a scope violation, not a 404.
    validate_error(
        api.get_transfer_request(transfer["id"], foreign_liaison),
        ERR_INSTITUTION_SCOPE_VIOLATION,
        403,
    )
    # The list endpoint does not error: it simply shows nothing.
    foreign_rows, foreign_meta = validate_paginated(api.list_transfer_requests(foreign_liaison))
    assert foreign_meta["total_count"] == 0
    assert foreign_rows == []

    own_rows, own_meta = validate_paginated(api.list_transfer_requests(own_liaison))
    assert own_meta["total_count"] == 1
    assert [row["id"] for row in own_rows] == [transfer["id"]]

    readable = validate_success(api.get_transfer_request(transfer["id"], own_liaison))
    assert readable["id"] == transfer["id"]
    assert readable["receiving_institution_id"] == addressee["id"]

    # A decision by the wrong liaison is refused on scope even though DECLINE is
    # a value its role owns.
    validate_error(
        api.decide_transfer_request(
            transfer["id"],
            factories.transfer_decision_payload("DECLINE", reason="not our animal"),
            foreign_liaison,
        ),
        ERR_INSTITUTION_SCOPE_VIOLATION,
        403,
    )
    held = validate_success(api.get_transfer_request(transfer["id"], PERMIT_OFFICER_HEADERS))
    assert held["status"] == "SUBMITTED"
    assert held["decline_reason"] is None
    assert build.get_specimen(world["specimen"]["id"])["disposition_status"] == "TRANSFER_PENDING"

    # The addressed liaison may decline, which restores the specimen (§3.8).
    declined = validate_success(
        api.decide_transfer_request(
            transfer["id"],
            factories.transfer_decision_payload("DECLINE", reason="capacity unavailable"),
            own_liaison,
        )
    )
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "LIAISON_DECLINED"
    restored = build.get_specimen(world["specimen"]["id"])
    assert restored["disposition_status"] == "ON_EXHIBIT"


def test_husbandry_records_are_written_by_the_aquarist_and_the_vet_and_by_nobody_else(api, build):
    """The husbandry log endpoint is shared by exactly two roles, and the curator is not one.

    PRD §3.7: "An aquarist or a veterinary officer appends an immutable husbandry record to a specimen with a `log_type` of `FEEDING`, `BEHAVIOR`, `TREATMENT` or `WEIGHT`"

    Design: Corner/rbac/rbac_husbandry_logging_is_shared_between_vet_and_aquarist_only
    """
    world = build.quarantined_specimen()
    specimen_id = world["specimen"]["id"]
    assert build.get_specimen(specimen_id)["welfare_score"] is None

    feeding = validate_success(
        api.create_husbandry_log(
            specimen_id,
            factories.husbandry_log_payload(
                "FEEDING", build.now, appetite_score=5, feed_grams=150.0
            ),
            AQUARIST_HEADERS,
        ),
        201,
    )
    assertions.assert_husbandry_log(feeding)
    assert feeding["log_type"] == "FEEDING"
    assert feeding["recorded_by_user_id"] == AQUARIST_ID

    treatment_note = validate_success(
        api.create_husbandry_log(
            specimen_id,
            factories.husbandry_log_payload(
                "TREATMENT", build.now, note="topical dressing renewed"
            ),
            VET_HEADERS,
        ),
        201,
    )
    assert treatment_note["log_type"] == "TREATMENT"
    assert treatment_note["recorded_by_user_id"] == VET_ID

    # The curator, who accessioned the animal, may not write on its chart.
    validate_error(
        api.create_husbandry_log(
            specimen_id,
            factories.husbandry_log_payload("FEEDING", build.now, appetite_score=5),
            CURATOR_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    # Nor may the curator's refusal have written a row: the chart still holds two.
    rows, meta = validate_paginated(api.list_husbandry_logs(specimen_id, CURATOR_HEADERS))
    assert meta["total_count"] == 2
    assert {row["recorded_by_user_id"] for row in rows} == {AQUARIST_ID, VET_ID}

    # Both appends recomputed the ROLLING welfare score; only the feeding record
    # enters the window, giving 40.0 + 5 x 8.0 with no behaviour records and no
    # open treatment case (§3.7).
    scored = build.get_specimen(specimen_id)
    assertions.assert_scaled_equal(scored["welfare_score"], 80.00)
    assert scored["welfare_score_variant"] == "ROLLING"


def test_the_director_who_approved_the_plan_line_may_not_clear_its_acquisition(api, build):
    """Clearance refuses the plan line's own approver and accepts a second director.

    PRD §2.11: "The director who approved a collection plan line may not clear an acquisition request that serves that line."

    Design: Corner/rbac/rbac_the_plan_approver_may_not_also_clear_the_acquisition
    """
    plant = build.create_plant()
    exhibit = build.create_exhibit(plant)
    species = build.create_species()
    entry = build.create_plan_entry(exhibit, species)
    approver = make_director_headers("dir-omni-1")
    entry = build.plan_action(entry["id"], "APPROVE", headers=approver)
    assert entry["status"] == "APPROVED"
    assert entry["approved_by_user_id"] == "dir-omni-1"

    request = build.create_acquisition(entry, source_type="CAPTIVE_BRED", requested_count=1)
    request = build.submit_acquisition(request["id"])
    assert request["status"] == "READY_FOR_CLEARANCE"
    assert request["permit_required"] is False

    species_version = build.species_version(species["id"])
    refused = api.clear_acquisition_request(
        request["id"], factories.clearance_payload(species_version), approver
    )
    validate_error(refused, ERR_SOD_VIOLATION, 409)

    held = build.get_acquisition(request["id"])
    assert held["status"] == "READY_FOR_CLEARANCE"
    assert held["cleared_by_user_id"] is None
    assert held["cleared_at"] is None
    assert held["sustainability_score_variant"] == "PROVISIONAL"
    assert build.get_species(species["id"])["version"] == species_version

    cleared = validate_success(
        api.clear_acquisition_request(
            request["id"],
            factories.clearance_payload(species_version),
            make_director_headers("dir-clearance-officer-2"),
        )
    )
    assert cleared["status"] == "CLEARED"
    assert cleared["cleared_by_user_id"] == "dir-clearance-officer-2"
    assert is_iso8601_timestamp(cleared["cleared_at"])
    assert cleared["sustainability_score_variant"] == "FINAL"
    # 40.0 GREEN + 35.0 CAPTIVE_BRED + 20.0 for a null source institution, with
    # no permit bonus on the READY_FOR_CLEARANCE road (§3.5).
    assertions.assert_scaled_equal(cleared["sustainability_score"], 95.00)

    # The approval anchor is untouched by the clearance.
    reread_entry = validate_success(api.get_collection_plan_entry(entry["id"], CURATOR_HEADERS))
    assert reread_entry["approved_by_user_id"] == "dir-omni-1"

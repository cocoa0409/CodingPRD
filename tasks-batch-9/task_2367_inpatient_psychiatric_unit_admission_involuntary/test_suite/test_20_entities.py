"""Envelope, defaults, computed fields and identifier resolution on the base entities.

These are the contract's flat surfaces: what a creation echoes back, what a read of
an empty unit derives, how a sub-resource listing pages, and which identifier
failure a client is told about.
"""

from test_helpers import (
    ApiErrorId,
    BedStatus,
    BedType,
    COMPLIANCE_OFFICER_HEADERS,
    DischargePlanStatus,
    GenderMixingPolicy,
    HoldStatus,
    LegalStatus,
    NON_EXISTENT_UUID,
    PlacementStatus,
    RecommendedStatus,
    SafetySearchStatus,
    SearchType,
    UnitPosture,
    assert_created,
    assert_error,
    assert_ids,
    assert_ok,
    assert_page,
    assert_page_window,
    assert_patient,
    assert_unit,
    bed_payload,
    build_ward,
    create_bed,
    create_patient,
    create_unit,
    evaluation_payload,
    hold_payload,
    patient_payload,
    read_admission,
    read_patient,
    read_unit,
    signed_evaluation,
)

SHELL_UNIT = "Ward 11 Shell"
PAGING_UNIT = "Ward 12 Paging"
DEFAULTS_UNIT = "Ward 14 Defaults"
KEYS_UNIT = "Ward 15 Keys"

PAGING_BEDS = (
    {"room_number": "421", "wing_code": "A", "bed_label": "A"},
    {"room_number": "422", "wing_code": "A", "bed_label": "A"},
    {
        "room_number": "423",
        "wing_code": "B",
        "bed_label": "S",
        "bed_type": BedType.SECLUSION.value,
    },
)
SINGLE_STANDARD_BED = ({"room_number": "431", "wing_code": "A", "bed_label": "A"},)
KEYS_BED = ({"room_number": "441", "wing_code": "A", "bed_label": "A"},)


class TestEntityEnvelopes:
    """A creation echoes its inputs; a read exposes every derived counter."""

    def test_patient_creation_derives_is_minor_from_the_age(self, api, clock, roster):
        """Eighteen is not a minor and seventeen is, with no client hint either way.

        PRD 3.2: "Registration of a patient records an `mrn` that must be unique
        across all patients, the patient's `legal_name`, their `age_years` as a whole
        number no less than 0 and no greater than 120, and a `gender_care_category`
        of `MALE`, `FEMALE` or `NONBINARY`. From the age the system derives
        `is_minor`, which is true exactly when `age_years` is below 18; minor status
        later both separates cohorts in rooms and lowers restraint duration
        ceilings. A patient's `active_hold_count` starts at 0 and is always the
        number of that patient's holds whose `status` is `ACTIVE`."

        Design: Corner/entities/patient_creation_returns_envelope_with_computed_is_minor
        """
        adult = assert_created(
            api.create_patient(
                COMPLIANCE_OFFICER_HEADERS,
                patient_payload(
                    mrn="MRN-2367-CR1",
                    legal_name="Corin Reyes",
                    age_years=18,
                    gender_care_category="NONBINARY",
                ),
            )
        )
        minor = assert_created(
            api.create_patient(
                COMPLIANCE_OFFICER_HEADERS,
                patient_payload(
                    mrn="MRN-2367-CR2",
                    legal_name="Cleo Rankin",
                    age_years=17,
                    gender_care_category="FEMALE",
                ),
            )
        )

        assert_patient(adult)
        assert adult["mrn"] == "MRN-2367-CR1"
        assert adult["legal_name"] == "Corin Reyes"
        assert adult["age_years"] == 18
        assert adult["gender_care_category"] == "NONBINARY"
        assert adult["is_minor"] is False
        assert minor["is_minor"] is True
        for record in (adult, minor):
            assert record["active_hold_count"] == 0
            assert record["version"] == 1

    def test_a_unit_with_no_beds_reads_closed_with_every_counter_at_zero(
        self, api, clock
    ):
        """The zero-bed starting state is the documented posture of a brand-new unit.

        PRD 3.1: "A brand-new unit has no beds, so the availability computation
        described below produces a `posture` of `CLOSED` at the moment of creation.
        Every unit exposes `licensed_placement_bed_count`, `raw_available_bed_count`,
        `posture`, `effective_available_bed_count`, `occupied_bed_count`,
        `active_seclusion_count` and `open_rights_violation_count`, all derived, and
        its `version` is what a placement client must echo back."

        Design: Corner/entities/unit_retrieval_returns_derived_posture_closed_with_no_beds
        """
        created = create_unit(
            api, SHELL_UNIT, GenderMixingPolicy.SEPARATE_BY_WING.value, 2
        )

        unit = read_unit(api, created["id"])

        assert_unit(unit)
        assert unit["name"] == SHELL_UNIT
        assert unit["gender_mixing_policy"] == GenderMixingPolicy.SEPARATE_BY_WING.value
        assert unit["seclusion_room_count"] == 2
        assert unit["licensed_placement_bed_count"] == 0
        assert unit["raw_available_bed_count"] == 0
        assert unit["occupied_bed_count"] == 0
        assert unit["effective_available_bed_count"] == 0
        assert unit["posture"] == UnitPosture.CLOSED.value
        assert unit["active_seclusion_count"] == 0
        assert unit["open_rights_violation_count"] == 0
        assert unit["version"] == 1

    def test_the_bed_listing_pages_and_filters_over_the_whole_set(self, api, clock):
        """total_count covers the filtered set, and has_more falls once the rows run out.

        PRD 2.3: "Every list response reports `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` is
        the size of the filtered set before pagination is applied and `has_more`
        indicates whether records remain beyond the current page."

        Design: Corner/entities/bed_listing_under_unit_paginates_with_total_count_and_has_more
        """
        ward = build_ward(
            api,
            name=PAGING_UNIT,
            gender_mixing_policy=GenderMixingPolicy.MIXED_ALLOWED.value,
            seclusion_room_count=1,
            bed_specs=PAGING_BEDS,
        )

        first_page = api.list_unit_beds(
            COMPLIANCE_OFFICER_HEADERS, ward.id, limit=2, offset=0
        )
        second_page = api.list_unit_beds(
            COMPLIANCE_OFFICER_HEADERS, ward.id, limit=2, offset=2
        )
        seclusion_only = api.list_unit_beds(
            COMPLIANCE_OFFICER_HEADERS, ward.id, bed_type=BedType.SECLUSION.value
        )

        first_items = assert_page_window(first_page, limit=2, offset=0, total=3)
        second_items = assert_page_window(second_page, limit=2, offset=2, total=3)
        assert len(first_items) == 2
        assert len(second_items) == 1

        _, first_meta = assert_page(first_page)
        _, second_meta = assert_page(second_page)
        assert first_meta["has_more"] is True
        assert second_meta["has_more"] is False
        assert_ids(
            list(first_items) + list(second_items), [bed["id"] for bed in ward.beds]
        )

        filtered, filtered_meta = assert_page(seclusion_only, 1)
        assert filtered[0]["id"] == ward.beds[2]["id"]
        assert filtered_meta["has_more"] is False

    def test_each_unknown_identifier_returns_its_own_not_found_code(self, api, clock):
        """Five reads of the same never-minted id produce five distinct error ids.

        PRD 2.9: "4. `ERR_PATIENT_NOT_FOUND` — the referenced `Patient` resolves;
        guards the patient read, evaluation creation, hold initiation and admission
        creation (the latter three through the body's `patient_id`)."

        PRD 2.9: "5. `ERR_UNIT_NOT_FOUND` — the referenced `Unit` resolves; guards
        the unit read, the unit's bed listing, bed creation, admission creation and
        admission placement."

        PRD 2.9: "6. `ERR_EVALUATION_NOT_FOUND` — the referenced
        `EmergencyEvaluation` resolves; guards the evaluation read, evaluation
        signing, hold initiation and admission creation."

        PRD 2.9: "7. `ERR_ADMISSION_NOT_FOUND` — the referenced `Admission`
        resolves; guards the admission read, every admission action (safety search,
        placement, voluntary conversion, discharge planning, discharge), restraint
        ordering, capacity determination, medication consent and discharge-request
        creation."

        PRD 2.9: "8. `ERR_HOLD_NOT_FOUND` — the referenced `HoldOrder` resolves;
        guards the hold read, certification, rescission and petition filing."

        Design: Corner/entities/unknown_ids_return_entity_specific_not_found_errors
        """
        reads = (
            (api.get_patient, ApiErrorId.PATIENT_NOT_FOUND),
            (api.get_unit, ApiErrorId.UNIT_NOT_FOUND),
            (api.get_evaluation, ApiErrorId.EVALUATION_NOT_FOUND),
            (api.get_admission, ApiErrorId.ADMISSION_NOT_FOUND),
            (api.get_hold, ApiErrorId.HOLD_NOT_FOUND),
        )

        seen = set()
        for read, error_id in reads:
            body = assert_error(
                read(COMPLIANCE_OFFICER_HEADERS, NON_EXISTENT_UUID), error_id
            )
            assert body["message"]
            seen.add(body["error_id"])

        assert len(seen) == len(reads)

    def test_a_body_missing_a_required_field_is_rejected_before_anything_is_written(
        self, api, clock
    ):
        """Three incomplete creations are all schema failures.

        PRD 2.9: "3. `ERR_INVALID_REQUEST` — on every endpoint: required body fields
        present, enum members valid, integers within their declared bounds, hearing
        `duration_minutes` equal to either 30 or 60, `hold_type` equal to
        `EMERGENCY_72H` when a hold is initiated, and `requested_hold_type` equal to
        `EXTENSION_14D` when a petition is filed."

        Design: Corner/entities/missing_required_body_fields_rejected_with_invalid_request
        """
        no_age = api.create_patient(
            COMPLIANCE_OFFICER_HEADERS,
            {
                "mrn": "MRN-2367-RQ",
                "legal_name": "Rowan Quist",
                "gender_care_category": "MALE",
            },
        )
        no_policy = api.create_unit(
            COMPLIANCE_OFFICER_HEADERS,
            {"name": "Ward 13 Incomplete", "seclusion_room_count": 1},
        )
        no_license = api.create_clinician(
            COMPLIANCE_OFFICER_HEADERS, {"full_name": "Noel License"}
        )

        for response in (no_age, no_policy, no_license):
            assert_error(response, ApiErrorId.INVALID_REQUEST)

    def test_omitted_optional_fields_take_their_declared_defaults(
        self, api, clock, roster
    ):
        """A new bed, a new admission and a bare safety search all fall back to defaults.

        PRD 3.5: "On creation the server copies `acuity_tier` from the evaluation —
        that copy, not a fresh computation, is what drives bed-type fit and
        promotion ranking for the rest of the stay — stamps `admitted_at` from the
        logical clock and `admitting_clinician_id` from the header, and initializes
        the record: `placement_status` `PENDING_PLACEMENT` on the placement axis,
        `safety_search_status` `PENDING`, `discharge_plan_status` `NOT_STARTED`,
        `rights_violation_flag` false, `observation_staff_quarter_hours` 0, and
        `bed_id`, `placed_at`, `discharged_at`,
        `search_performed_by_clinician_id`, `capacity_present`,
        `follow_up_provider_name`, `follow_up_appointment_at`,
        `follow_up_guarantee_days`, `follow_up_guarantee_deadline_at` and
        `discharge_summary` all null."

        PRD 3.5: "A `ChargeNurse` or an `IntakeClinician` records it with a
        `search_type` of `VISUAL`, `WANDED` or `FULL_BODY_WITH_CONSENT`, a
        `search_witness_clinician_id` naming the independent observer, a
        `search_items_secured_count` of belongings taken into safekeeping which
        defaults to 0, a `contraband_found` boolean which defaults to false, and an
        `outcome`."

        Design: Corner/entities/omitted_optional_search_fields_apply_declared_defaults
        """
        unit = create_unit(api, DEFAULTS_UNIT, GenderMixingPolicy.MIXED_ALLOWED.value, 0)
        bed = create_bed(api, unit["id"], **SINGLE_STANDARD_BED[0])
        assert bed["status"] == BedStatus.AVAILABLE.value

        patient = create_patient(
            api,
            mrn="MRN-2367-DF",
            legal_name="Dara Fenwick",
            age_years=29,
            gender_care_category="MALE",
        )
        evaluation = signed_evaluation(
            api,
            roster.intake_headers,
            patient["id"],
            danger_to_self=False,
            danger_to_others=True,
            grave_disability=True,
            capacity_present=True,
        )
        admission = assert_created(
            api.create_admission(
                roster.intake_headers,
                patient_id=patient["id"],
                evaluation_id=evaluation["id"],
                unit_id=unit["id"],
                requested_legal_status=LegalStatus.VOLUNTARY.value,
            )
        )

        assert admission["placement_status"] == PlacementStatus.PENDING_PLACEMENT.value
        assert admission["safety_search_status"] == SafetySearchStatus.PENDING.value
        assert admission["discharge_plan_status"] == DischargePlanStatus.NOT_STARTED.value
        assert admission["observation_staff_quarter_hours"] == 0
        assert admission["rights_violation_flag"] is False
        assert admission["bed_id"] is None
        assert admission["placed_at"] is None

        searched = assert_ok(
            api.record_safety_search(
                roster.charge_nurse_headers,
                admission["id"],
                {
                    "search_type": SearchType.VISUAL.value,
                    "search_witness_clinician_id": roster.witness_id,
                    "outcome": "COMPLETED",
                },
            )
        )

        assert searched["search_items_secured_count"] == 0
        assert searched["contraband_found"] is False
        assert searched["safety_search_status"] == SafetySearchStatus.COMPLETED.value
        assert searched["search_performed_by_clinician_id"] == roster.charge_nurse["id"]

    def test_the_acuity_figures_are_recomputed_and_supplied_values_ignored(
        self, api, clock, roster
    ):
        """A body claiming score 1 and nine prior admissions is stored as 11 and 0.

        PRD 3.2: "The `acuity_score` is then an integer sum of five contributions: 4
        points when `danger_to_self` is true, 5 points when `danger_to_others` is
        true, 3 points when `grave_disability` is true, 2 points for each recent
        prior admission counted but crediting no more than three of them, and 3
        points when `capacity_present` is false."

        PRD 3.2: "Independently of the score, the `recommended_status` follows from
        the criteria: if none of the three statutory criteria is true it is
        `NO_ADMISSION`; if at least one is true and `capacity_present` is true it is
        `VOLUNTARY`; and if at least one is true while `capacity_present` is false it
        is `INVOLUNTARY_HOLD`."

        Design: Corner/entities/computed_acuity_score_recomputed_input_ignored
        """
        patient = create_patient(
            api,
            mrn="MRN-2367-CF",
            legal_name="Corrine Falk",
            age_years=51,
            gender_care_category="FEMALE",
        )

        evaluation = assert_created(
            api.create_evaluation(
                roster.intake_headers,
                evaluation_payload(
                    patient_id=patient["id"],
                    danger_to_self=False,
                    danger_to_others=True,
                    grave_disability=True,
                    capacity_present=False,
                    acuity_score=1,
                    acuity_tier="LOW",
                    recommended_status=RecommendedStatus.NO_ADMISSION.value,
                    prior_admission_count_30d=9,
                ),
            )
        )

        assert evaluation["acuity_score"] == 11
        assert evaluation["acuity_tier"] == "MODERATE"
        assert (
            evaluation["recommended_status"] == RecommendedStatus.INVOLUNTARY_HOLD.value
        )
        assert evaluation["prior_admission_count_30d"] == 0
        assert evaluation["danger_to_self"] is False
        assert evaluation["danger_to_others"] is True
        assert evaluation["grave_disability"] is True
        assert evaluation["capacity_present"] is False

    def test_system_fields_are_minted_server_side_whatever_the_body_claims(
        self, api, clock, roster
    ):
        """A hold that asks to be born ACTIVE at version 47 is stored pending and at 1.

        PRD 3.3: "The server records `initiated_by_clinician_id` from the header,
        leaves `certifying_clinician_id`, `certified_at` and `closure_reason` null,
        leaves `predecessor_hold_id` null because an emergency hold has no
        predecessor, and sets `status` to `PENDING_CERTIFICATION`."

        PRD 2.5: "`version` (integer): begins at 1 on creation and increments by
        exactly 1 on every mutation of the row."

        Design: Corner/entities/system_fields_minted_server_side_input_ignored
        """
        patient = create_patient(
            api,
            mrn="MRN-2367-SF",
            legal_name="Saul Ferrand",
            age_years=26,
            gender_care_category="MALE",
        )
        evaluation = signed_evaluation(api, roster.intake_headers, patient["id"])
        assert evaluation["evaluation_started_at"] == "2026-09-03T08:00:00.000Z"

        hold = assert_created(
            api.create_hold(
                roster.intake_headers,
                hold_payload(
                    patient_id=patient["id"],
                    evaluation_id=evaluation["id"],
                    id=NON_EXISTENT_UUID,
                    status=HoldStatus.ACTIVE.value,
                    version=47,
                    initiated_by_clinician_id=roster.psychiatrist["id"],
                    certifying_clinician_id=roster.psychiatrist["id"],
                    certified_at="2026-09-03T07:00:00Z",
                ),
            )
        )

        assert hold["id"] != NON_EXISTENT_UUID
        assert hold["version"] == 1
        assert hold["status"] == HoldStatus.PENDING_CERTIFICATION.value
        assert hold["initiated_by_clinician_id"] == roster.intake["id"]
        assert hold["certifying_clinician_id"] is None
        assert hold["certified_at"] is None
        assert read_patient(api, patient["id"])["active_hold_count"] == 0

    def test_bad_enums_out_of_range_integers_and_pinned_literals_are_schema_failures(
        self, api, clock, roster
    ):
        """The two hold-class literal pins are enforced in the same band as the enums.

        PRD 3.3: "The `hold_type` supplied on initiation must be `EMERGENCY_72H`;
        the other class, `EXTENSION_14D`, is never client-created and exists only as
        a system-created successor to a granted court petition, which is why an
        initiation naming it fails schema validation with `ERR_INVALID_REQUEST`."

        PRD 2.9: "3. `ERR_INVALID_REQUEST` — on every endpoint: required body fields
        present, enum members valid, integers within their declared bounds, hearing
        `duration_minutes` equal to either 30 or 60, `hold_type` equal to
        `EMERGENCY_72H` when a hold is initiated, and `requested_hold_type` equal to
        `EXTENSION_14D` when a petition is filed."

        Design: Corner/entities/invalid_enum_and_out_of_range_values_rejected
        """
        patient = create_patient(
            api,
            mrn="MRN-2367-TC",
            legal_name="Tibor Cales",
            age_years=40,
            gender_care_category="MALE",
        )
        evaluation = signed_evaluation(api, roster.intake_headers, patient["id"])

        bad_enum = api.create_patient(
            COMPLIANCE_OFFICER_HEADERS,
            patient_payload(
                mrn="MRN-2367-TC2",
                legal_name="Bea Enumson",
                age_years=40,
                gender_care_category="OTHER",
            ),
        )
        out_of_range = api.create_patient(
            COMPLIANCE_OFFICER_HEADERS,
            patient_payload(
                mrn="MRN-2367-TC3",
                legal_name="Aage Rangeley",
                age_years=130,
                gender_care_category="MALE",
            ),
        )
        wrong_hold_class = api.create_hold(
            roster.intake_headers,
            hold_payload(
                patient_id=patient["id"],
                evaluation_id=evaluation["id"],
                hold_type="EXTENSION_14D",
            ),
        )

        for response in (bad_enum, out_of_range, wrong_hold_class):
            assert_error(response, ApiErrorId.INVALID_REQUEST)

        assert_page(
            api.list_holds(COMPLIANCE_OFFICER_HEADERS, patient_id=patient["id"]), 0
        )

    def test_a_body_foreign_key_is_answered_by_the_rule_that_owns_it(
        self, api, clock, roster
    ):
        """A bogus unit id is unit-specific; a bogus witness falls to the catch-all.

        PRD 2.9: "9. `ERR_REFERENCED_RESOURCE_NOT_FOUND` — every remaining
        referenced identifier resolves, namely a `Clinician` cited as search witness
        or hearing advocate, a `Bed`, a `HoldPetition`, a `CourtHearing`, a
        `RestraintEpisode`, a `CapacityDetermination` or a `DischargeRequest`. These
        are resolved left to right, path segments before body fields."

        Design: Corner/entities/bed_and_search_witness_foreign_keys_must_resolve
        """
        ward = build_ward(
            api,
            name=KEYS_UNIT,
            gender_mixing_policy=GenderMixingPolicy.MIXED_ALLOWED.value,
            seclusion_room_count=0,
            bed_specs=KEYS_BED,
        )
        patient = create_patient(
            api,
            mrn="MRN-2367-FK",
            legal_name="Fay Kessler",
            age_years=35,
            gender_care_category="FEMALE",
        )
        evaluation = signed_evaluation(
            api,
            roster.intake_headers,
            patient["id"],
            danger_to_self=False,
            danger_to_others=True,
            grave_disability=True,
            capacity_present=True,
        )
        admission = assert_created(
            api.create_admission(
                roster.intake_headers,
                patient_id=patient["id"],
                evaluation_id=evaluation["id"],
                unit_id=ward.id,
                requested_legal_status=LegalStatus.VOLUNTARY.value,
            )
        )

        orphan_bed = api.create_bed(
            COMPLIANCE_OFFICER_HEADERS,
            bed_payload(
                unit_id=NON_EXISTENT_UUID,
                room_number="999",
                wing_code="Z",
                bed_label="A",
            ),
        )
        assert_error(orphan_bed, ApiErrorId.UNIT_NOT_FOUND)

        unknown_witness = api.record_safety_search(
            roster.charge_nurse_headers,
            admission["id"],
            {
                "search_type": SearchType.VISUAL.value,
                "search_witness_clinician_id": NON_EXISTENT_UUID,
                "search_items_secured_count": 0,
                "contraband_found": False,
                "outcome": "COMPLETED",
            },
        )
        assert_error(unknown_witness, ApiErrorId.REFERENCED_RESOURCE_NOT_FOUND)

        assert_page(api.list_unit_beds(COMPLIANCE_OFFICER_HEADERS, ward.id), 1)
        untouched = read_admission(api, admission["id"])
        assert untouched["safety_search_status"] == SafetySearchStatus.PENDING.value
        assert untouched["search_witness_clinician_id"] is None
        assert untouched["version"] == admission["version"]

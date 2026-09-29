"""Two parent-version guards and the sweep's two punitive expiry branches.

An unrelated write silently advances the guarded parent version, so the honest
client is refused and only the refreshed retry lands. The sweep, meanwhile, uses a
different comparison and a different duration source in each of its two restraint
branches, and never touches an episode that was released in time.
"""

from test_helpers import (
    AcuityTier,
    ApiErrorId,
    BedStatus,
    DeterminationStatus,
    InterventionType,
    LegalStatus,
    PlacementStatus,
    RestraintStatus,
    SearchType,
    SurrogateAuthorityScope,
    SurrogateRelationship,
    UnitPosture,
    active_hold_case,
    admission_version,
    assert_created,
    assert_error,
    assert_monitoring_compliance,
    assert_ok,
    assert_page,
    assert_unit_availability,
    build_ward,
    capacity_determination_payload,
    complete_safety_search,
    create_admission,
    face_to_face_payload,
    order_restraint,
    placement_payload,
    read_admission,
    read_bed,
    read_capacity_determination,
    read_restraint,
    read_unit,
    release_restraint,
    run_sweep,
    set_bed_status,
    set_clock,
    unit_version,
    voluntary_case,
)

VERSION_UNIT = "Ward 39 Versions"
VERSION_BEDS = (
    {"room_number": "3901", "wing_code": "A", "bed_label": "3901-A"},
    {"room_number": "3902", "wing_code": "A", "bed_label": "3902-A"},
    {"room_number": "3903", "wing_code": "A", "bed_label": "3903-A"},
)
SURROGATE_NAME = "Dana Ruiz"
PLACED_AT = "2026-09-03T08:00:00.000Z"

SWEEP_UNIT = "Ward 40 Schedules"
NO_BEDS = ()
MECHANICAL_MINUTES = 30
PHYSICAL_MINUTES = 30
REVIEWED_JUSTIFICATION = "Assaultive behaviour; reviewed episode."
UNREVIEWED_JUSTIFICATION = "Assaultive behaviour; never reviewed."
HOLD_JUSTIFICATION = "Brief hold during medication administration."
AUTHORIZED_UNTIL = "2026-09-03T08:30:00.000Z"
FACE_TO_FACE_DEADLINE = "2026-09-03T09:00:00.000Z"
MECHANICAL_INTERVAL = 15
PHYSICAL_INTERVAL = 5
REVIEW_AT = "2026-09-03T08:10:00Z"
RELEASE_AT = "2026-09-03T08:20:00Z"
RELEASED_INSTANT = "2026-09-03T08:20:00.000Z"
RELEASED_MINUTES = 20
RELEASED_CHECKS = 4
AT_THE_AUTHORIZATION_END = "2026-09-03T08:30:00Z"
AT_THE_FACE_TO_FACE_DEADLINE = "2026-09-03T09:00:00Z"
ONE_MILLISECOND_LATE = "2026-09-03T09:00:00.001Z"
EXPIRED_ORDERED_MINUTES = 60
EXPIRED_ORDERED_CHECKS = 4
NO_COMPLIANCE = 0.0
QUARTER_HOURS_AFTER_RELEASE = 2
QUARTER_HOURS_AFTER_ACTIVE_EXPIRY = 4
QUARTER_HOURS_AFTER_BOTH_EXPIRIES = 8


def _sweep_counts(api, *, restraints):
    """One sweep whose restraint family is the only one with anything to do."""
    counts = run_sweep(api)
    assert counts["expired_restraint_count"] == restraints
    assert counts["expired_hold_count"] == 0
    assert counts["expired_discharge_request_count"] == 0
    assert counts["expired_consent_count"] == 0
    return counts


class TestStaleParentVersionGuards:
    """Each guard sits on a parent version that an unrelated write silently advances."""

    def test_the_bed_edit_advances_the_unit_version_and_only_the_refreshed_retry_places(
        self, api, clock, roster
    ):
        """A 412 writes nothing, and the version the retry carries is exactly one higher.

        PRD 2.7: "Placing an admission into a bed requires a non-optional
        `expected_unit_version` field carrying the client's last observed `version` of
        the target `Unit`. If that number does not equal the unit's current `version`,
        the placement is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412). Bed inventory
        edits, other placements and discharges all advance a unit's `version`, so a
        client working from an older read of the unit is refused rather than allowed to
        consume bed capacity it never observed. The unit read endpoint is the
        authoritative source of the value to send."

        PRD 2.9: "`ERR_STALE_UNIT_VERSION` — `expected_unit_version` equals the unit's
        current `version`; on placement."

        PRD 3.1: "This four-step recomputation runs on bed creation, on a bed status
        change, on an admission placement, on a system promotion, and on the bed release
        that follows a discharge; each run refreshes the unit's `updated_at` and
        increments its `version` by one."

        Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_stale_parent_versions_and_accept_refreshed_ones
        """
        ward, admission = self._searched_moderate_admission(api, roster)
        observed = unit_version(api, ward.id)

        set_bed_status(
            api,
            ward.beds[2]["id"],
            BedStatus.OUT_OF_SERVICE.value,
            headers=roster.charge_nurse_headers,
        )
        edited = read_unit(api, ward.id)
        assert edited["version"] == observed + 1
        assert_unit_availability(edited, licensed=2, raw_available=2, occupied=0)
        assert edited["posture"] == UnitPosture.OPEN.value
        assert edited["effective_available_bed_count"] == 2

        stale = api.place_admission(
            roster.charge_nurse_headers,
            admission["id"],
            placement_payload(
                unit_id=ward.id,
                expected_unit_version=observed,
                bed_id=ward.beds[0]["id"],
            ),
        )
        assert_error(stale, ApiErrorId.STALE_UNIT_VERSION)
        assert (
            read_admission(api, admission["id"])["placement_status"]
            == PlacementStatus.PENDING_PLACEMENT.value
        )
        assert (
            read_bed(api, ward.beds[0]["id"], ward.id)["status"]
            == BedStatus.AVAILABLE.value
        )
        assert unit_version(api, ward.id) == edited["version"]

        placed = assert_ok(
            api.place_admission(
                roster.charge_nurse_headers,
                admission["id"],
                placement_payload(
                    unit_id=ward.id,
                    expected_unit_version=edited["version"],
                    bed_id=ward.beds[0]["id"],
                ),
            )
        )
        assert placed["placement_status"] == PlacementStatus.PLACED.value
        assert placed["bed_id"] == ward.beds[0]["id"]
        assert placed["placed_at"] == PLACED_AT
        assert (
            read_bed(api, ward.beds[0]["id"], ward.id)["status"]
            == BedStatus.OCCUPIED.value
        )
        assert unit_version(api, ward.id) == edited["version"] + 1

    def test_a_second_search_invalidates_the_determination_version_and_the_retry_supersedes(
        self, api, clock, roster
    ):
        """The admission version moves twice before the second determination is written.

        PRD 2.7: "Recording a capacity determination requires a non-optional
        `expected_admission_version` field carrying the client's last observed `version`
        of the target `Admission`. A mismatch with the admission's current `version` is
        rejected with `ERR_STALE_ADMISSION_VERSION` (HTTP 412). Because a new
        determination supersedes the admission's prior `ACTIVE` one, the guard prevents a
        writer holding a stale view of the admission from silently displacing a
        determination it never saw."

        PRD 2.9: "`ERR_STALE_ADMISSION_VERSION` — `expected_admission_version` equals the
        admission's current `version`; on capacity determination."

        PRD 3.7: "At most one determination per admission may be `ACTIVE`, so creating a
        new one moves any prior `ACTIVE` determination for that admission to
        `SUPERSEDED`. The new finding is mirrored onto the admission's own
        `capacity_present` field, which stays null until the first determination exists,
        and `Admission.version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_stale_parent_versions_and_accept_refreshed_ones
        """
        _, admission = self._searched_moderate_admission(api, roster)
        observed = admission_version(api, admission["id"])

        first = assert_created(
            api.create_capacity_determination(
                roster.psychiatrist_headers,
                capacity_determination_payload(
                    admission_id=admission["id"],
                    expected_admission_version=observed,
                    capacity_present=True,
                ),
            )
        )
        assert first["status"] == DeterminationStatus.ACTIVE.value
        assert read_admission(api, admission["id"])["capacity_present"] is True

        complete_safety_search(
            api,
            roster,
            admission["id"],
            search_type=SearchType.FULL_BODY_WITH_CONSENT.value,
            items_secured=1,
            contraband_found=True,
        )
        refreshed = admission_version(api, admission["id"])
        assert refreshed == observed + 2

        stale = api.create_capacity_determination(
            roster.psychiatrist_headers,
            capacity_determination_payload(
                admission_id=admission["id"],
                expected_admission_version=observed,
                capacity_present=False,
                surrogate_name=SURROGATE_NAME,
                surrogate_relationship=SurrogateRelationship.SPOUSE.value,
                surrogate_authority_scope=SurrogateAuthorityScope.FULL.value,
            ),
        )
        assert_error(stale, ApiErrorId.STALE_ADMISSION_VERSION)
        assert (
            read_capacity_determination(api, first["id"])["status"]
            == DeterminationStatus.ACTIVE.value
        )
        assert read_admission(api, admission["id"])["capacity_present"] is True
        assert_page(
            api.list_capacity_determinations(
                roster.psychiatrist_headers, admission_id=admission["id"]
            ),
            1,
        )

        second = assert_created(
            api.create_capacity_determination(
                roster.psychiatrist_headers,
                capacity_determination_payload(
                    admission_id=admission["id"],
                    expected_admission_version=refreshed,
                    capacity_present=False,
                    surrogate_name=SURROGATE_NAME,
                    surrogate_relationship=SurrogateRelationship.SPOUSE.value,
                    surrogate_authority_scope=SurrogateAuthorityScope.FULL.value,
                ),
            )
        )
        assert second["status"] == DeterminationStatus.ACTIVE.value
        assert second["surrogate_name"] == SURROGATE_NAME
        assert (
            second["surrogate_authority_scope"] == SurrogateAuthorityScope.FULL.value
        )
        assert (
            read_capacity_determination(api, first["id"])["status"]
            == DeterminationStatus.SUPERSEDED.value
        )
        assert read_admission(api, admission["id"])["capacity_present"] is False

    @staticmethod
    def _searched_moderate_admission(api, roster):
        """A searched, still-unplaced involuntary admission on a three-bed ward."""
        ward = build_ward(
            api,
            name=VERSION_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=VERSION_BEDS,
        )
        case = active_hold_case(
            api,
            roster,
            mrn="MRN-2367-OC",
            legal_name="Version Case",
            age_years=52,
            gender_care_category="MALE",
        )
        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            ward.id,
            requested_legal_status=LegalStatus.INVOLUNTARY.value,
        )
        assert admission["acuity_tier"] == AcuityTier.MODERATE.value
        complete_safety_search(api, roster, admission["id"], items_secured=0)
        return ward, admission


class TestSweepExpiresOnlyDueEpisodes:
    """Three episodes, one comparison each, and only two of them ever lapse."""

    def test_the_two_branches_use_their_own_comparisons_and_the_released_episode_is_safe(
        self, api, clock, roster
    ):
        """Inclusive at the authorization end, strict at the face-to-face deadline, blind to a release.

        PRD 3.6: "An episode still in `ORDERED` when the clock has moved strictly past
        `face_to_face_deadline_at` moves `ORDERED → EXPIRED_UNAUTHORIZED`: its
        `released_at` is set to the lapsed `face_to_face_deadline_at` rather than to the
        sweep instant, its `actual_duration_minutes` is 60, both compliance percentages
        are computed, the admission's `rights_violation_flag` is set true, the unit's
        `open_rights_violation_count` is recomputed, and the admission's
        `observation_staff_quarter_hours` is recomputed. An episode in `ACTIVE` when the
        clock has reached or passed `authorized_until_at` moves `ACTIVE →
        EXPIRED_UNAUTHORIZED`: its `released_at` is set to `authorized_until_at`, its
        `actual_duration_minutes` equals the full `ordered_duration_minutes`, both
        compliance percentages are computed, the `rights_violation_flag` and
        `open_rights_violation_count` are set and recomputed as above,
        `observation_staff_quarter_hours` is recomputed, and the unit's
        `active_seclusion_count` is recomputed. `EXPIRED_UNAUTHORIZED` is terminal and
        debriefing is never reachable from it — an episode that lapsed without
        authorization cannot be closed out as if it had been managed properly."

        PRD 3.6: "`authorized_until_at` is `started_at` plus `ordered_duration_minutes`,
        and it is the right-open end of the episode's occupancy interval.
        `face_to_face_deadline_at` is `started_at` plus 60 minutes. And
        `monitoring_interval_minutes` is 5 for a `PHYSICAL_HOLD` and 15 for a
        `MECHANICAL_RESTRAINT` or a `SECLUSION` — the tighter cadence for the
        intervention where a clinician's hands are physically on the patient."

        PRD 3.6: "`observation_staff_quarter_hours` is the sum, over every episode of
        that admission whose `status` is `RELEASED`, `DEBRIEFED` or
        `EXPIRED_UNAUTHORIZED`, of that episode's `actual_duration_minutes` divided by 15
        and rounded up to the next whole number."

        PRD 2.11: "Each such flag immediately recomputes `open_rights_violation_count` on
        the owning unit, which is defined as the number of that unit's admissions
        carrying a true `rights_violation_flag` whose `placement_status` is anything
        other than `DISCHARGED`."

        Design: Corner/cross_cutting_complexity_layers/sweep_expires_only_due_episodes_and_never_a_released_one
        """
        ward = build_ward(
            api,
            name=SWEEP_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=NO_BEDS,
        )
        case = voluntary_case(
            api,
            roster,
            mrn="MRN-2367-SW",
            legal_name="Sweep Case",
            age_years=49,
            gender_care_category="FEMALE",
            danger_to_self=False,
            danger_to_others=True,
            grave_disability=True,
        )
        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            ward.id,
            requested_legal_status=LegalStatus.VOLUNTARY.value,
        )

        reviewed = order_restraint(
            api,
            roster,
            admission["id"],
            InterventionType.MECHANICAL_RESTRAINT.value,
            MECHANICAL_MINUTES,
            clinical_justification=REVIEWED_JUSTIFICATION,
        )
        unreviewed = order_restraint(
            api,
            roster,
            admission["id"],
            InterventionType.MECHANICAL_RESTRAINT.value,
            MECHANICAL_MINUTES,
            clinical_justification=UNREVIEWED_JUSTIFICATION,
        )
        hold = order_restraint(
            api,
            roster,
            admission["id"],
            InterventionType.PHYSICAL_HOLD.value,
            PHYSICAL_MINUTES,
            clinical_justification=HOLD_JUSTIFICATION,
        )
        for episode in (reviewed, unreviewed, hold):
            assert episode["status"] == RestraintStatus.ORDERED.value
            assert episode["authorized_until_at"] == AUTHORIZED_UNTIL
            assert episode["face_to_face_deadline_at"] == FACE_TO_FACE_DEADLINE
        assert reviewed["monitoring_interval_minutes"] == MECHANICAL_INTERVAL
        assert unreviewed["monitoring_interval_minutes"] == MECHANICAL_INTERVAL
        assert hold["monitoring_interval_minutes"] == PHYSICAL_INTERVAL

        set_clock(api, REVIEW_AT)
        assert_ok(
            api.record_face_to_face(
                roster.second_psychiatrist_headers,
                reviewed["id"],
                face_to_face_payload(),
            )
        )
        assert_ok(
            api.record_face_to_face(
                roster.psychiatrist_headers, hold["id"], face_to_face_payload()
            )
        )

        released = release_restraint(
            api, roster, hold["id"], release_clock=RELEASE_AT
        )
        assert released["status"] == RestraintStatus.RELEASED.value
        assert released["released_at"] == RELEASED_INSTANT
        assert released["actual_duration_minutes"] == RELEASED_MINUTES
        assert_monitoring_compliance(
            released, required=RELEASED_CHECKS, grid_satisfied=0, logged=0
        )
        assert released["grid_compliance_pct"] == NO_COMPLIANCE
        assert released["raw_compliance_pct"] == NO_COMPLIANCE
        assert (
            read_admission(api, admission["id"])["observation_staff_quarter_hours"]
            == QUARTER_HOURS_AFTER_RELEASE
        )

        set_clock(api, AT_THE_AUTHORIZATION_END)
        _sweep_counts(api, restraints=1)
        lapsed = read_restraint(api, reviewed["id"])
        assert lapsed["status"] == RestraintStatus.EXPIRED_UNAUTHORIZED.value
        assert lapsed["released_at"] == AUTHORIZED_UNTIL
        assert lapsed["actual_duration_minutes"] == MECHANICAL_MINUTES
        assert_monitoring_compliance(
            lapsed,
            required=MECHANICAL_MINUTES // MECHANICAL_INTERVAL,
            grid_satisfied=0,
            logged=0,
        )
        assert lapsed["grid_compliance_pct"] == NO_COMPLIANCE
        assert lapsed["raw_compliance_pct"] == NO_COMPLIANCE
        assert (
            read_restraint(api, unreviewed["id"])["status"]
            == RestraintStatus.ORDERED.value
        )
        assert (
            read_restraint(api, hold["id"])["status"] == RestraintStatus.RELEASED.value
        )
        flagged = read_admission(api, admission["id"])
        assert flagged["rights_violation_flag"] is True
        assert (
            flagged["observation_staff_quarter_hours"]
            == QUARTER_HOURS_AFTER_ACTIVE_EXPIRY
        )
        assert read_unit(api, ward.id)["open_rights_violation_count"] == 1

        set_clock(api, AT_THE_FACE_TO_FACE_DEADLINE)
        _sweep_counts(api, restraints=0)
        assert (
            read_restraint(api, unreviewed["id"])["status"]
            == RestraintStatus.ORDERED.value
        )

        set_clock(api, ONE_MILLISECOND_LATE)
        _sweep_counts(api, restraints=1)
        unauthorized = read_restraint(api, unreviewed["id"])
        assert unauthorized["status"] == RestraintStatus.EXPIRED_UNAUTHORIZED.value
        assert unauthorized["released_at"] == FACE_TO_FACE_DEADLINE
        assert unauthorized["actual_duration_minutes"] == EXPIRED_ORDERED_MINUTES
        assert_monitoring_compliance(
            unauthorized,
            required=EXPIRED_ORDERED_CHECKS,
            grid_satisfied=0,
            logged=0,
        )
        assert unauthorized["grid_compliance_pct"] == NO_COMPLIANCE
        assert unauthorized["raw_compliance_pct"] == NO_COMPLIANCE
        assert (
            read_admission(api, admission["id"])["observation_staff_quarter_hours"]
            == QUARTER_HOURS_AFTER_BOTH_EXPIRIES
        )
        assert read_unit(api, ward.id)["open_rights_violation_count"] == 1

        _sweep_counts(api, restraints=0)
        assert (
            read_restraint(api, reviewed["id"])["status"]
            == RestraintStatus.EXPIRED_UNAUTHORIZED.value
        )
        assert (
            read_restraint(api, unreviewed["id"])["status"]
            == RestraintStatus.EXPIRED_UNAUTHORIZED.value
        )
        assert (
            read_restraint(api, hold["id"])["status"] == RestraintStatus.RELEASED.value
        )
        assert (
            read_admission(api, admission["id"])["observation_staff_quarter_hours"]
            == QUARTER_HOURS_AFTER_BOTH_EXPIRIES
        )

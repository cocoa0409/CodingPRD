"""Room certification: grade check vs per-sample excursion rules, the OCC
guard, voiding, the cleaning gate, and lazy expiry boundaries."""
from test_helpers import (
    QA,
    ApiErrorId,
    add_sampling_point,
    assert_room_certification,
    certify_room,
    close_excursion,
    create_cleaning_program,
    create_qualified_personnel,
    create_room,
    get_room,
    get_success_data,
    record_cycle,
    record_sample,
    set_clock,
    setup_certified_room,
    setup_validated_cleaning_program,
    validate_error,
    validate_paginated,
    validate_success,
    verify_cycle,
)


class TestPerSampleVsMeanCertification:
    """One dataset, two verdicts: a single result at/above the alert limit
    trips a per-sample excursion, while the certification grade judges the
    mean of per-location means strictly below the alert limit."""

    def _setup(self, api):
        room = create_room(room_code="CR-A")
        point = add_sampling_point(room["id"], point_code="SP-A", metric="PARTICLE")
        setup_validated_cleaning_program(room["id"], required_consecutive_passes=3,
                                         method_code="MOP-1")
        sample = record_sample(point["id"], 302000,
                               sampled_at="2026-08-01T09:00:00Z")
        # Close the alert excursion so zero excursions stand open.
        close_excursion(sample["triggered_excursion_id"],
                        root_cause="HEPA diffuser seal degraded over shift",
                        product_impact="NONE", disposition="RELEASE",
                        investigator_id="qa-a1", approver_id="qa-a2")
        return room, sample

    def test_per_sample_alert_trips_excursion_while_mean_grade_passes(self, api):
        """PRD §2.6: "The same set of numbers can therefore trip a per-sample
        alert excursion while the mean-based certification grade still passes;
        conversely, a mean exactly equal to the alert limit fails certification
        even though a single sample exactly at the alert limit produces only an
        alert excursion."
        PRD §3.1: "The computed `grade_passed` flag is true exactly when the
        mean of `location_mean_values` — the sum divided by the count, computed
        at full precision — falls strictly below the room's
        `particle_alert_limit`; a mean equal to the limit fails."

        Design: Difficulty/dual_variant_calc/per_sample_alert_trips_while_mean_certification_passes
        """
        room, sample = self._setup(api)
        assert sample["classification"] == "ALERT_EXCEEDED", (
            "per-sample variant: 302000 >= alert 300000 trips ALERT")

        certification = certify_room(
            room["id"], executed_at="2026-08-01T12:00:00Z",
            location_mean_values=[302000, 290000, 295000, 296000])
        assert_room_certification(certification)
        # mean = 1183000 / 4 = 295750.0 < 300000: the mean variant passes
        assert certification["grade_passed"] is True
        assert certification["result"] == "PASS"

    def test_certification_pass_sets_certified_status_and_in_control_posture(
            self, api):
        """PRD §3.1: "On a `PASS`, the room's `certification_status` becomes
        `CERTIFIED`, `certified_at` is set to the certification's
        `executed_at`, the referenced superseded certification (if any) is
        marked superseded, the room's `version` increments by one, and the
        environmental posture is recomputed."

        Design: Difficulty/dual_variant_calc/per_sample_alert_trips_while_mean_certification_passes
        """
        room, _sample = self._setup(api)
        version_before = get_room(room["id"])["version"]

        certification = certify_room(
            room["id"], executed_at="2026-08-01T12:00:00Z",
            location_mean_values=[302000, 290000, 295000, 296000])
        assert certification["result"] == "PASS"

        room_after = get_room(room["id"])
        assert room_after["certification_status"] == "CERTIFIED"
        assert room_after["certified_at"] is not None
        assert room_after["certified_at"].startswith("2026-08-01T12:00:00"), (
            "certified_at is set to the certification's executed_at")
        assert room_after["environment_posture"] == "IN_CONTROL"
        assert room_after["version"] == version_before + 1


class TestCertificationGradeCheck:
    def test_certification_mean_exactly_at_alert_limit_fails(self, api):
        """PRD §2.6: "conversely, a mean exactly equal to the alert limit fails
        certification even though a single sample exactly at the alert limit
        produces only an alert excursion."
        PRD §3.1: "The recorded certification `result` is `PASS` only when
        three conditions hold together: the grade check passed (otherwise
        `ERR_CERTIFICATION_GRADE_FAILED`), the room has zero excursions in
        `OPEN` or `UNDER_INVESTIGATION` (otherwise
        `ERR_OPEN_EXCURSIONS_BLOCK_CERTIFICATION`), and at least one cleaning
        validation program for the room stands at `VALIDATED` (otherwise
        `ERR_CLEANING_NOT_VALIDATED`); any shortfall records the certification
        as `FAIL`."

        Design: Corner/calculations/certification_mean_exactly_at_alert_limit_fails
        """
        room = create_room(room_code="CR-C2")
        setup_validated_cleaning_program(room["id"],
                                         required_consecutive_passes=1,
                                         method_code="MOP-C2")
        version = get_room(room["id"])["version"]
        resp = api.create_certification(
            room["id"],
            {"executed_at": "2026-08-01T12:00:00Z",
             "location_mean_values": [300000, 300000],
             "expected_room_version": version},
            QA,
        )
        # mean 300000.0 is NOT strictly below the 300000 alert limit
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_GRADE_FAILED)
        assert get_room(room["id"])["certification_status"] == "UNCERTIFIED"


class TestCertificationVoid:
    def test_void_non_latest_certification_rejected_latest_void_succeeds(self, api):
        """PRD §3.1: "QA may instead void a certification outright — but only
        the room's latest passing certification, pinned precisely as the first
        row when the room's `PASS` certifications are ordered by `executed_at`
        descending with ties broken by `created_at` descending; targeting any
        other certification is rejected with `ERR_NOT_LATEST_CERTIFICATION`.
        Voiding moves the room from `CERTIFIED` to `CERTIFICATION_SUSPENDED`,
        recomputes the posture, and thereby fails every room-dependent gate
        until a fresh pass is recorded."

        Design: Corner/state_machines/certification_void_requires_latest
        """
        room = create_room(room_code="CR-S9", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        setup_validated_cleaning_program(room["id"],
                                         required_consecutive_passes=1,
                                         method_code="MOP-S9")
        cert_a = certify_room(room["id"], executed_at="2026-08-01T00:00:00Z",
                              location_mean_values=[10, 20])
        cert_b = certify_room(room["id"], executed_at="2026-08-02T00:00:00Z",
                              location_mean_values=[15, 25],
                              supersedes_certification_id=cert_a["id"])

        resp = api.void_certification(room["id"], cert_a["id"], QA)
        validate_error(resp, ApiErrorId.ERR_NOT_LATEST_CERTIFICATION)

        voided = validate_success(api.void_certification(room["id"], cert_b["id"], QA),
                                  200)
        assert voided["id"] == cert_b["id"]
        assert get_room(room["id"])["certification_status"] == (
            "CERTIFICATION_SUSPENDED")


class TestCertificationOcc:
    def test_stale_room_version_rejected_on_certification(self, api):
        """PRD §2.9: "Recording a room certification requires the request to
        carry `expected_room_version`, holding the `version` of the target
        cleanroom as the client last observed it. If the room's current
        `version` has advanced since that observation — for instance because
        another writer recorded a certification that supersedes the prior one,
        or because an excursion cascade recomputed the room's posture — the
        request is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412),
        preventing the client from certifying a room state it never observed."

        Design: Corner/validations/occ_stale_room_version_on_certification
        """
        room = create_room(room_code="CR-V4", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        setup_validated_cleaning_program(room["id"],
                                         required_consecutive_passes=1,
                                         method_code="MOP-V4")
        stale_version = room["version"]
        first = certify_room(room["id"], executed_at="2026-08-01T00:00:00Z",
                             location_mean_values=[10, 20])
        assert first["result"] == "PASS"

        resp = api.create_certification(
            room["id"],
            {"executed_at": "2026-08-02T00:00:00Z",
             "location_mean_values": [15, 25],
             "expected_room_version": stale_version},
            QA,
        )
        # The first PASS advanced the room version beyond the observed value.
        validate_error(resp, ApiErrorId.ERR_STALE_ROOM_VERSION)


class TestCertificationGates:
    def test_certification_blocked_without_validated_cleaning_program(self, api):
        """PRD §3.1: "The recorded certification `result` is `PASS` only when
        three conditions hold together: the grade check passed (otherwise
        `ERR_CERTIFICATION_GRADE_FAILED`), the room has zero excursions in
        `OPEN` or `UNDER_INVESTIGATION` (otherwise
        `ERR_OPEN_EXCURSIONS_BLOCK_CERTIFICATION`), and at least one cleaning
        validation program for the room stands at `VALIDATED` (otherwise
        `ERR_CLEANING_NOT_VALIDATED`); any shortfall records the certification
        as `FAIL`."
        PRD §3.7: "A `VALIDATED` cleaning program is a hard precondition of
        room certification (§3.1), which ties the cleaning loop directly into
        the certification cycle: a room cannot certify, recertify, or recover
        from suspension while its cleaning validation is incomplete or lapsed."

        Design: Corner/errors/error_cleaning_not_validated_blocks_certification
        """
        room = create_room(room_code="CR-ERH")
        program = create_cleaning_program(room["id"], method_code="MOP-ERH",
                                          required_consecutive_passes=2)
        get_success_data(api.activate_cleaning_program(program["id"], QA))
        cycle = record_cycle(program["id"], result="PASS")
        verify_cycle(cycle["id"])
        program = get_success_data(api.get_cleaning_program(program["id"], QA))
        assert program["status"] == "ACTIVE", "1 of 2 passes: not yet VALIDATED"

        version = get_room(room["id"])["version"]
        resp = api.create_certification(
            room["id"],
            {"executed_at": "2026-08-01T12:00:00Z",
             "location_mean_values": [10, 20],
             "expected_room_version": version},
            QA,
        )
        validate_error(resp, ApiErrorId.ERR_CLEANING_NOT_VALIDATED)
        assert get_room(room["id"])["certification_status"] == "UNCERTIFIED"

    def test_certification_on_decommissioned_room_rejected(self, api):
        """PRD §3.1: "Recording against a room that is not `ACTIVE` is refused
        with `ERR_ROOM_NOT_ACTIVE`, and a stale `expected_room_version` is
        refused with `ERR_STALE_ROOM_VERSION`."
        PRD §3.9: "Decommissioning moves the room's lifecycle `status` to
        terminal `DECOMMISSIONED`. Thereafter the room rejects all further
        operational writes — entries, samples, transfers, travelers, and
        certifications alike — with `ERR_ROOM_NOT_ACTIVE`."

        Design: Corner/errors/error_room_not_active_on_certify_decommissioned
        """
        room = create_room(room_code="CR-ERD", iso_class="ISO_8",
                           particle_alert_limit=3500000,
                           particle_action_limit=3520000,
                           viable_alert_limit=100, viable_action_limit=200)
        setup_validated_cleaning_program(room["id"],
                                         required_consecutive_passes=1,
                                         method_code="MOP-ERD")
        decommissioned = validate_success(api.decommission_room(room["id"], QA), 200)
        assert decommissioned["status"] == "DECOMMISSIONED"

        version = get_room(room["id"])["version"]
        resp = api.create_certification(
            room["id"],
            {"executed_at": "2026-08-01T12:00:00Z",
             "location_mean_values": [10, 20],
             "expected_room_version": version},
            QA,
        )
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_ACTIVE)


class TestLazyExpiryBoundaries:
    def _setup_certified_room_with_qualified_personnel(self, api):
        room = setup_certified_room(
            room_code="CR-B", iso_class="ISO_8",
            particle_alert_limit=3500000, particle_action_limit=3520000,
            viable_alert_limit=100, viable_action_limit=200,
            recert_interval_days=180, executed_at="2026-08-01T00:00:00Z",
            cert_means=[1000, 2000])
        personnel, qualification = create_qualified_personnel(
            room["id"], employee_code="EMP-B", full_name="Bee Operator")
        return room, personnel, qualification

    def test_certification_expires_at_exact_interval_boundary(self, api):
        """PRD §2.5: "First, a room whose `certification_status` is `CERTIFIED`
        transitions to `CERTIFICATION_EXPIRED` the first time any read or write
        touches the room after the logical clock has reached or passed the
        instant that is `certified_at` plus `recert_interval_days` (the day
        count applied as whole days of twenty-four hours). The boundary is
        inclusive: at the exact instant the interval elapses, the certification
        is already expired."

        Design: Difficulty/dual_variant_calc/room_certification_expiry_vs_gowning_expiry_same_boundary_operator
        """
        room, _personnel, _qual = (
            self._setup_certified_room_with_qualified_personnel(api))
        # certified_at 2026-08-01T00:00:00Z + 180 days = 2027-01-28T00:00:00Z
        set_clock("2027-01-27T23:59:59Z")
        room_pre = get_room(room["id"])
        assert room_pre["certification_status"] == "CERTIFIED", (
            "one second before certified_at + 180d the certification holds")

        set_clock("2027-01-28T00:00:00Z")
        room_post = get_room(room["id"])
        assert room_post["certification_status"] == "CERTIFICATION_EXPIRED", (
            "at the exact instant the interval elapses, already expired")
        assert room_post["environment_posture"] == "ALERT", (
            "a non-CERTIFIED certification status forces a posture floor of ALERT")

    def test_gowning_qualification_unaffected_by_certification_expiry(self, api):
        """PRD §2.5: "Second, a gowning qualification in `QUALIFIED` status
        flips to `EXPIRED` on read once the logical clock reaches or passes its
        `qualification_expires_at`, again with the boundary instant itself
        already treated as expired."
        PRD §3.2: "granting one pairs a `personnel_id` with a `cleanroom_id`,
        stamps `qualified_at` at grant time, and computes
        `qualification_expires_at` as exactly 365 days after `qualified_at`."

        Design: Difficulty/dual_variant_calc/room_certification_expiry_vs_gowning_expiry_same_boundary_operator
        """
        room, personnel, qualification = (
            self._setup_certified_room_with_qualified_personnel(api))
        # Qualification granted at the default clock 2026-08-01T00:00:00Z,
        # expiring 2027-08-01T00:00:00Z — 180 days of room certification do not
        # touch the 365-day qualification domain.
        set_clock("2027-01-28T00:00:00Z")
        room_post = get_room(room["id"])
        assert room_post["certification_status"] == "CERTIFICATION_EXPIRED"

        qual = get_success_data(
            api.get_gowning_qualification(qualification["id"], QA))
        assert qual["status"] == "QUALIFIED", (
            "2027-01-28 < 2027-08-01: the 365-day domain is unaffected by the "
            "180-day certification domain")
        listed, meta = validate_paginated(
            api.list_gowning_qualifications(QA,
                                            params={"personnel_id": personnel["id"]}))
        assert meta["total_count"] == 1
        assert listed[0]["status"] == "QUALIFIED"

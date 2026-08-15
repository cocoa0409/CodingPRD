"""Voyage lifecycle: creation, departure gating, parallel state axes, arrival."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_plan,
    arrive_voyage,
    assert_timestamp_equals,
    assert_voyage,
    create_plan,
    create_vessel,
    create_voyage,
    create_voyage_payload,
    depart_voyage,
    find_report,
    get_success_data,
    get_voyage,
    list_determinations,
    post_treatment_compliant_event_set,
    set_clock,
    setup_vessel_with_approved_plan,
    setup_voyage_in_progress,
    submit_plan,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestVoyageCreation:
    def test_voyage_created_with_initial_parallel_states(self, api, vessel_master_headers):
        """PRD section 3.2: "A new voyage starts with `compliance_status` `PENDING`
        and `reporting_status` `NOT_DUE`."
        PRD section 2.4: "a `version` integer that starts at 1 and increments by 1 on
        every mutation."

        Design: Corner/state_machines/voyage_created_with_initial_parallel_states
        """
        vessel = create_vessel(imo_number="9100017", vessel_name="MV Harlequin",
                               bwms_type="NONE", gross_tonnage=8000,
                               keel_laid_date="2016-01-01T00:00:00Z",
                               ballast_capacity_m3=4000)
        resp = api.create_voyage(
            vessel["id"],
            create_voyage_payload(voyage_number="V9301",
                                  crosses_captain_of_port_zones=False),
            vessel_master_headers,
        )
        data = validate_success(resp, 201)
        assert_voyage(data)
        assert data["compliance_status"] == "PENDING"
        assert data["reporting_status"] == "NOT_DUE"
        assert data["version"] == 1

    def test_duplicate_voyage_number_returns_409(self, api, shore_officer_headers,
                                                 vessel_master_headers):
        """PRD section 3.2: "A voyage is created against a vessel by a
        `ShoreComplianceOfficer` or `VesselMaster`, supplying `voyage_number` (unique
        per vessel; a duplicate is rejected with `ERR_DUPLICATE_VOYAGE_NUMBER`, HTTP
        409), `departure_port` and `arrival_port` as UN/LOCODEs, `departed_at`,
        optionally `arrived_at`, and the two routing flags
        `crosses_captain_of_port_zones` and `enters_us_eez`."

        Design: Corner/validations/duplicate_voyage_number_returns_409
        """
        vessel = create_vessel(imo_number="9100042", vessel_name="MV Linnet",
                               bwms_type="NONE", gross_tonnage=8000,
                               keel_laid_date="2016-01-01T00:00:00Z",
                               ballast_capacity_m3=4000)
        create_voyage(vessel["id"], voyage_number="V9503",
                      crosses_captain_of_port_zones=False, as_shore=True)

        resp = api.create_voyage(
            vessel["id"],
            create_voyage_payload(voyage_number="V9503", departure_port="USSFO",
                                  arrival_port="USSEA", departed_at="2026-07-29T00:00:00Z",
                                  crosses_captain_of_port_zones=False),
            vessel_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOYAGE_NUMBER)

    def test_voyage_under_wrong_vessel_returns_404(self, api, shore_officer_headers,
                                                   psc_officer_headers):
        """PRD section 2.5: "Path parameters are validated left to right: each
        segment's identifier must resolve to an existing entity, and each child must
        belong to the ancestor named to its left. A failure at any segment is rejected
        with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/voyage_under_wrong_vessel_returns_404
        """
        vessel_a = create_vessel(imo_number="9100014", vessel_name="MV Dunlin",
                                 bwms_type="NONE", gross_tonnage=8000,
                                 keel_laid_date="2016-01-01T00:00:00Z",
                                 ballast_capacity_m3=4000)
        vessel_b = create_vessel(imo_number="9100015", vessel_name="MV Egret",
                                 bwms_type="NONE", gross_tonnage=8200,
                                 keel_laid_date="2016-03-01T00:00:00Z",
                                 ballast_capacity_m3=4200)
        voyage = create_voyage(vessel_a["id"], voyage_number="V9202",
                               crosses_captain_of_port_zones=False, as_shore=True)

        resp = api.get_voyage(vessel_b["id"], voyage["id"], psc_officer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestVoyageDepartureGating:
    def test_depart_rejected_without_approved_plan(self, api, vessel_master_headers):
        """PRD section 3.2: "Three preconditions gate departure: the voyage must still
        be `PENDING`; the vessel's `compliance_posture` must not be `FROZEN`; and the
        vessel must have at least one plan in `APPROVED` state."
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/voyage_depart_requires_approved_plan
        """
        set_clock()
        vessel = create_vessel(imo_number="9000019", vessel_name="MV Skua")
        create_plan(vessel["id"], plan_revision=1)  # stays DRAFT, never submitted
        voyage = create_voyage(vessel["id"], voyage_number="V8001")

        resp = api.depart_voyage(vessel["id"], voyage["id"], vessel_master_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_depart_succeeds_after_plan_approval(self, api, vessel_master_headers):
        """PRD section 3.2: "Departure by the `VesselMaster` moves the voyage from
        `PENDING` to `IN_PROGRESS`."
        PRD section 3.2: "flips the voyage's `reporting_status` from `NOT_DUE` to
        `DUE`"

        Design: Difficulty/cross_entity_state_dependency/voyage_depart_requires_approved_plan
        """
        set_clock()
        vessel = create_vessel(imo_number="9000019", vessel_name="MV Skua")
        plan = create_plan(vessel["id"], plan_revision=1)
        voyage = create_voyage(vessel["id"], voyage_number="V8001")

        blocked = api.depart_voyage(vessel["id"], voyage["id"], vessel_master_headers)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        submit_plan(vessel["id"], plan["id"])
        approve_plan(vessel["id"], plan["id"])

        resp = api.depart_voyage(vessel["id"], voyage["id"], vessel_master_headers)
        data = validate_success(resp, 200)
        assert data["compliance_status"] == "IN_PROGRESS"
        assert data["reporting_status"] == "DUE"


class TestProvisionalVsFinalDetermination:
    def test_provisional_determination_at_departure_is_insufficient_data(
            self, api, flag_surveyor_headers):
        """PRD section 3.3: "`INSUFFICIENT_DATA` when there is nothing to classify
        (the provisional case at departure, before any discharge exists)."
        PRD section 3.2: "On departure the system computes a compliance determination
        with trigger reason `VOYAGE_DEPARTURE`"

        Design: Difficulty/dual_variant_calc/determination_provisional_vs_final_variant_divergence
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000001", vessel_name="MV Aurora", voyage_number="V1001",
            arrived_at="2026-08-10T00:00:00Z",
        )
        determinations = list_determinations(vessel["id"], voyage["id"])
        provisional = determinations[0]
        assert provisional["trigger_reason"] == "VOYAGE_DEPARTURE"
        assert provisional["determination_basis"] == "INSUFFICIENT_DATA", (
            f"provisional departure determination must be INSUFFICIENT_DATA, "
            f"got {provisional['determination_basis']}"
        )

    def test_final_determination_at_arrival_diverges_to_treatment_compliant(
            self, api, vessel_master_headers):
        """PRD section 3.3: "The treatment path is satisfied when a
        `TREATMENT_COMPLETE` exists on the same tank whose `occurred_at` falls between
        the source uptake's `occurred_at` and the discharge's `occurred_at`."
        PRD section 3.3: "The final `determination_basis` is `TREATMENT_COMPLIANT`
        when the noncompliant volume is zero and at least some volume is
        treatment-compliant"
        PRD section 3.3: "If the latest basis is `EXCHANGE_COMPLIANT` or
        `TREATMENT_COMPLIANT`, the voyage transitions `IN_PROGRESS` to `COMPLIANT` and
        the vessel's `version` increments."

        Design: Difficulty/dual_variant_calc/determination_provisional_vs_final_variant_divergence
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000001", vessel_name="MV Aurora", voyage_number="V1001",
            arrived_at="2026-08-10T00:00:00Z",
        )
        provisional_basis = list_determinations(vessel["id"], voyage["id"])[0]["determination_basis"]

        post_treatment_compliant_event_set(vessel["id"], voyage["id"], tank_id="T1", volume_m3=500)

        resp = api.arrive_voyage(vessel["id"], voyage["id"],
                                 {"arrived_at": "2026-08-10T00:00:00Z"}, vessel_master_headers)
        arrived = validate_success(resp, 200)
        assert arrived["compliance_status"] == "COMPLIANT"

        final = list_determinations(vessel["id"], voyage["id"])[0]
        assert final["determination_basis"] == "TREATMENT_COMPLIANT"
        assert final["determination_basis"] != provisional_basis, (
            "final_at_arrival variant must diverge from the provisional departure variant"
        )
        assert final["treatment_compliant_volume_m3"] == pytest.approx(500.0)
        assert final["exchange_compliant_volume_m3"] == pytest.approx(0.0)
        assert final["total_discharged_volume_m3"] == pytest.approx(500.0)


class TestParallelAxesDriftThenConverge:
    def _setup_voyage_with_late_report(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000006", vessel_name="MV Fulmar", voyage_number="V4001",
            arrived_at="2026-08-10T00:00:00Z",
        )
        post_treatment_compliant_event_set(vessel["id"], voyage["id"], tank_id="T1", volume_m3=500)
        return vessel, voyage

    def test_reporting_axis_drifts_overdue_while_compliance_stays_in_progress(
            self, api, vessel_master_headers):
        """PRD section 3.4: "A report in `DRAFT` whose deadline passes while still
        unsubmitted flips the voyage's `reporting_status` to `OVERDUE` and creates a
        noncompliance record with `source_type` `REPORT_OVERDUE`."
        PRD section 3.4: "The report's own `is_overdue` flag is true exactly when its
        `status` is `DRAFT` and the current UTC is past `due_at`."
        PRD section 3.4: "Each voyage carries a parallel `reporting_status` axis —
        `NOT_DUE`, `DUE`, `SUBMITTED`, `ACKNOWLEDGED`, or `OVERDUE` — independent of
        `compliance_status`."

        Design: Difficulty/non_linear_state_machine/voyage_parallel_axes_drift_then_converge
        """
        vessel, voyage = self._setup_voyage_with_late_report()
        after_depart = get_voyage(vessel["id"], voyage["id"])
        assert after_depart["compliance_status"] == "IN_PROGRESS"
        assert after_depart["reporting_status"] == "DUE"

        # PRE_ARRIVAL due_at is 2026-08-09T00:00:00Z (arrived_at minus 24h).
        set_clock("2026-08-09T00:00:01Z")

        drifted = get_voyage(vessel["id"], voyage["id"])
        assert drifted["compliance_status"] == "IN_PROGRESS", (
            "compliance axis must not move when the reporting axis flips OVERDUE"
        )
        assert drifted["reporting_status"] == "OVERDUE"

        report = find_report(vessel["id"], voyage["id"], "PRE_ARRIVAL")
        assert report["is_overdue"] is True

    def test_axes_converge_to_compliant_acknowledged_terminal_pair(
            self, api, vessel_master_headers, flag_surveyor_headers):
        """PRD section 3.4: "Submission by the `VesselMaster` — carrying the free-form
        `payload_summary` — requires the report to be in `DRAFT` and the voyage's
        `reporting_status` to be `DUE` or `OVERDUE`."
        PRD section 3.4: "A `FlagSurveyor` may then acknowledge the report, moving it
        from `SUBMITTED` to `ACKNOWLEDGED` and the voyage's `reporting_status` to
        `ACKNOWLEDGED`"

        Design: Difficulty/non_linear_state_machine/voyage_parallel_axes_drift_then_converge
        """
        vessel, voyage = self._setup_voyage_with_late_report()
        set_clock("2026-08-09T00:00:01Z")

        arrive_voyage(vessel["id"], voyage["id"])
        arrived = get_voyage(vessel["id"], voyage["id"])
        assert arrived["compliance_status"] == "COMPLIANT"
        assert arrived["reporting_status"] == "OVERDUE", (
            "arrival commits the compliance axis; the reporting axis stays OVERDUE"
        )

        report = find_report(vessel["id"], voyage["id"], "PRE_ARRIVAL")
        resp = api.submit_report(vessel["id"], voyage["id"], report["id"],
                                 {"payload_summary": {"note": "pre-arrival late filing"}},
                                 vessel_master_headers)
        submitted = validate_success(resp, 200)
        assert submitted["status"] == "SUBMITTED", "submission from OVERDUE must be accepted"

        ack = api.acknowledge_report(vessel["id"], voyage["id"], report["id"],
                                     flag_surveyor_headers)
        validate_success(ack, 200)
        converged = get_voyage(vessel["id"], voyage["id"])
        assert converged["compliance_status"] == "COMPLIANT"
        assert converged["reporting_status"] == "ACKNOWLEDGED"


class TestArrivalOutcomes:
    def test_voyage_arrive_exempt_no_us_eez(self, api, vessel_master_headers,
                                            flag_surveyor_headers):
        """PRD section 3.3: "If the voyage's `enters_us_eez` is false, the
        determination basis is `EXEMPT_NO_US_EEZ`."
        PRD section 3.3: "If the basis is `EXEMPT_SAME_COTP` or `EXEMPT_NO_US_EEZ`,
        the voyage transitions to `EXEMPT`."

        Design: Corner/state_machines/voyage_arrive_exempt_no_us_eez
        """
        from test_helpers import post_discharge, post_uptake

        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100029", vessel_name="MV Turnstone", voyage_number="V9308",
            arrived_at="2026-08-10T00:00:00Z", crosses_captain_of_port_zones=False,
            enters_us_eez=False, departure_port="MXVER", arrival_port="COCTG",
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T1", volume_m3=300,
                    salinity_ppt=34.0, source_port_locode="MXVER")
        post_discharge(vessel["id"], voyage["id"], tank_id="T1", volume_m3=300,
                       latitude=10.4, longitude=-75.6, distance_from_shore_nm=20)

        resp = api.arrive_voyage(vessel["id"], voyage["id"],
                                 {"arrived_at": "2026-08-10T00:00:00Z"}, vessel_master_headers)
        arrived = validate_success(resp, 200)
        assert arrived["compliance_status"] == "EXEMPT"

        basis = list_determinations(vessel["id"], voyage["id"])[0]["determination_basis"]
        assert basis == "EXEMPT_NO_US_EEZ"

    def test_determination_same_cotp_exempt_basis(self, api, vessel_master_headers,
                                                  flag_surveyor_headers):
        """PRD section 3.3: "If the voyage does not cross Captain of the Port zones
        and the source uptake port and discharge port are within the same zone, the
        basis is `EXEMPT_SAME_COTP`."
        PRD section 3.3: "If the basis is `EXEMPT_SAME_COTP` or `EXEMPT_NO_US_EEZ`,
        the voyage transitions to `EXEMPT`."

        Design: Corner/calculations/determination_same_cotp_exempt_basis
        """
        from test_helpers import post_discharge, post_uptake

        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100037", vessel_name="MV Fieldfare", voyage_number="V9405",
            arrived_at="2026-08-10T00:00:00Z", crosses_captain_of_port_zones=False,
            enters_us_eez=True, departure_port="USNYC", arrival_port="USNYC",
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T1", volume_m3=100,
                    salinity_ppt=30.0, source_port_locode="USNYC")
        post_discharge(vessel["id"], voyage["id"], tank_id="T1", volume_m3=100,
                       occurred_at="2026-07-29T06:00:00Z", latitude=40.6,
                       longitude=-73.9, distance_from_shore_nm=5)

        resp = api.arrive_voyage(vessel["id"], voyage["id"],
                                 {"arrived_at": "2026-08-10T00:00:00Z"}, vessel_master_headers)
        arrived = validate_success(resp, 200)
        assert arrived["compliance_status"] == "EXEMPT"

        basis = list_determinations(vessel["id"], voyage["id"])[0]["determination_basis"]
        assert basis == "EXEMPT_SAME_COTP"

    def test_voyage_arrive_noncompliant_creates_minor_record(self, api, vessel_master_headers,
                                                             flag_surveyor_headers):
        """PRD section 3.3: "If the basis is `NONCOMPLIANT_MIXED` or
        `NONCOMPLIANT_NO_METHOD`, or any `OPEN` noncompliance record for the voyage
        has severity `MAJOR` or `CRITICAL`, the voyage transitions to `NONCOMPLIANT`;
        a noncompliance record with `source_type` `DETERMINATION_NONCOMPLIANT` is
        created if one is not already present, and the vessel's `version` increments."
        PRD section 3.10: "A sampling exceedance contributes 40 points, a PSC
        deficiency 30, a noncompliant determination 25, an overdue report 10, and a
        missing method 15."
        PRD section 3.10: "A score of at least 70 yields `CRITICAL`; at least 40
        yields `MAJOR`; otherwise `MINOR`. The response deadline is 30 days from
        `detected_at` for `MINOR`, 14 days for `MAJOR`, and 72 hours for `CRITICAL`."

        Design: Corner/state_machines/voyage_arrive_noncompliant_creates_minor_record
        """
        from test_helpers import find_noncompliance, post_discharge, post_uptake

        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100030", vessel_name="MV Upland", voyage_number="V9309",
            arrived_at="2026-08-10T00:00:00Z",
        )
        post_uptake(vessel["id"], voyage["id"], tank_id="T1", volume_m3=400, salinity_ppt=32.0)
        post_discharge(vessel["id"], voyage["id"], tank_id="T1", volume_m3=400,
                       occurred_at="2026-07-29T06:00:00Z")

        resp = api.arrive_voyage(vessel["id"], voyage["id"],
                                 {"arrived_at": "2026-08-10T00:00:00Z"}, vessel_master_headers)
        arrived = validate_success(resp, 200)
        assert arrived["compliance_status"] == "NONCOMPLIANT"

        record = find_noncompliance(vessel["id"], voyage["id"],
                                    source_type="DETERMINATION_NONCOMPLIANT")
        # Score 25 (noncompliant determination), posture OPEN, no prior escalations.
        assert record["severity"] == "MINOR"
        # detected at the logical clock 2026-08-01T00:00:00Z; MINOR deadline +30 days.
        assert_timestamp_equals(record["response_due_at"], "2026-08-31T00:00:00Z",
                                label="MINOR response_due_at")

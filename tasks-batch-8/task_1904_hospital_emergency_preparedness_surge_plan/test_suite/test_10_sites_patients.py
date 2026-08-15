"""Alternate care sites and patient movement: commitment windows, activation
gates, transfer guards, census accounting, and the capacity→tier→burn cascade."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_alternate_care_site,
    assert_patient_track_record,
    commit_site,
    create_incident,
    create_patient,
    create_patient_record_payload,
    create_site,
    create_site_commitment_payload,
    create_transferred_patient,
    setup_incident_with_activated_site,
    setup_site_cascade_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["planning_chief_headers"]
LC = TEST_USERS["logistics_chief_headers"]


class TestSiteDemobilizeCascade:
    def test_demobilize_cascade_recomputes_capacity_and_tier(self, api):
        """PRD §3.7: "Demobilization clears `activated_incident_id` to null,
        advances the site's `version`, and cascades in order: the previously served
        incident's `operational_surge_capacity` is recomputed without this site's
        beds, its `current_surge_tier` is re-derived from the new capacity, and
        every supply item's `projected_daily_burn_rate`, `days_of_supply`, and
        `below_reorder_level` are recomputed under the new surge-multiplier
        context."

        Design: Difficulty/transitive_cascade/acs_demobilize_capacity_tier_burn_chain
        """
        item, assessed, site = setup_site_cascade_scenario()
        assert assessed["operational_surge_capacity"] == 240
        assert assessed["current_surge_tier"] == "GREEN", "17000 < 85*240 = 20400"

        demobilized = validate_success(api.demobilize_site(site["id"], IC))
        assert_alternate_care_site(demobilized)
        assert demobilized["status"] == "DEMOBILIZED"
        assert demobilized["activated_incident_id"] is None

        incident = validate_success(api.get_incident(assessed["id"], IC))
        assert incident["operational_surge_capacity"] == 200, "site's 40 beds removed"
        assert incident["current_surge_tier"] == "YELLOW", (
            "17000 >= 85*200 = 17000 after the cascade"
        )

    def test_demobilize_cascade_reprices_supply_projection(self, api):
        """PRD §3.7: "Demobilization clears `activated_incident_id` to null,
        advances the site's `version`, and cascades in order: the previously served
        incident's `operational_surge_capacity` is recomputed without this site's
        beds, its `current_surge_tier` is re-derived from the new capacity, and
        every supply item's `projected_daily_burn_rate`, `days_of_supply`, and
        `below_reorder_level` are recomputed under the new surge-multiplier
        context."
        PRD §3.6: "The forward-looking `projected_daily_burn_rate` then applies the
        surge multiplier keyed to the active incident's `current_surge_tier`: 1.0
        when no incident is `ACTIVATED` or the active incident's tier is null, and
        otherwise 1.0 for `GREEN`, 1.25 for `YELLOW`, 1.5 for `ORANGE`, and 2.0 for
        `RED`."

        Design: Difficulty/transitive_cascade/acs_demobilize_capacity_tier_burn_chain
        """
        item, assessed, site = setup_site_cascade_scenario()
        before = validate_success(api.get_supply_item(item["id"], LC))
        assert before["projected_daily_burn_rate"] == pytest.approx(0.4286, abs=1e-9), (
            "multiplier 1.0 under GREEN"
        )

        validate_success(api.demobilize_site(site["id"], IC))
        after = validate_success(api.get_supply_item(item["id"], LC))
        assert after["projected_daily_burn_rate"] == pytest.approx(0.5358, abs=1e-9), (
            "multiplier 1.25 under the re-derived YELLOW tier"
        )


class TestCommitWindowBuffer:
    def test_commit_with_two_hour_gap_conflicts(self, api):
        """PRD §3.7: "A proposed window conflicts — and is rejected with
        `ERR_SITE_WINDOW_CONFLICT` — whenever its start falls earlier than four
        hours after an existing window's end and, at the same time, its end falls
        later than four hours before that existing window's start."
        PRD §3.7: "Committing moves a `STANDBY` site to `COMMITTED` on its first
        reservation".

        Design: Difficulty/resource_temporal_overlap/acs_commit_buffered_window_conflict
        """
        incident = create_incident(incident_name="MCI-buffer")
        site = create_site(site_name="Arena", bed_capacity=60)

        first = commit_site(site["id"], incident["id"],
                            "2026-08-01T08:00:00Z", "2026-08-01T16:00:00Z")
        assert first["status"] == "COMMITTED"

        resp = api.commit_site_window(
            site["id"],
            create_site_commitment_payload(incident["id"], "2026-08-01T18:00:00Z",
                                           "2026-08-02T02:00:00Z"),
            IC,
        )
        validate_error(resp, ApiErrorId.ERR_SITE_WINDOW_CONFLICT)

    def test_commit_with_exactly_four_hour_gap_accepted(self, api):
        """PRD §3.7: "A proposed window conflicts — and is rejected with
        `ERR_SITE_WINDOW_CONFLICT` — whenever its start falls earlier than four
        hours after an existing window's end and, at the same time, its end falls
        later than four hours before that existing window's start."

        Design: Difficulty/resource_temporal_overlap/acs_commit_buffered_window_conflict
        """
        incident = create_incident(incident_name="MCI-buffer")
        site = create_site(site_name="Arena", bed_capacity=60)
        commit_site(site["id"], incident["id"],
                    "2026-08-01T08:00:00Z", "2026-08-01T16:00:00Z")

        # 20:00 is exactly four hours after 16:00 — the strict inequality means
        # the buffered boundary itself is not a conflict.
        third = commit_site(site["id"], incident["id"],
                            "2026-08-01T20:00:00Z", "2026-08-02T04:00:00Z")
        assert len(third["commitments"]) == 2, "both windows are reserved"


class TestTransferGuards:
    def _full_site_scenario(self, api):
        """Incident ACTIVATED; 1-bed site ACTIVATED; pA TRANSFERRED (census full);
        pB DISCHARGED."""
        incident, site = setup_incident_with_activated_site(
            bed_capacity=1, incident_overrides={"incident_name": "MCI-prio"}
        )
        pa = create_patient(incident["id"], "P-A", triage_category="IMMEDIATE")
        pb = create_patient(incident["id"], "P-B", triage_category="MINOR",
                            arrival_at="2026-08-01T00:11:00Z")
        validate_success(api.transfer_patient(pa["id"], {"site_id": site["id"]}, PC))
        validate_success(api.discharge_patient(pb["id"], PC))
        return incident, site, pa, pb

    def test_transfer_discharged_patient_to_full_site_state_beats_safety(self, api):
        """PRD §2.11: "When several validations apply to one request, the server
        evaluates them in a fixed order, and the first failure determines the
        response."
        PRD §2.11: "8. State-transition legality on the target resource — the
        generic guard that rejects any action whose target's current state does not
        permit it: `ERR_INVALID_STATE`."
        PRD §2.11: "10. Business safety checks — site capacity at transfer and
        stock sufficiency at issue: `ERR_ACS_AT_CAPACITY` or
        `ERR_INSUFFICIENT_STOCK`."

        Design: Difficulty/priority_pair_validation_conflict/transfer_discharged_patient_to_full_site_state_beats_safety
        """
        _incident, site, _pa, pb = self._full_site_scenario(api)
        resp = api.transfer_patient(pb["id"], {"site_id": site["id"]}, PC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_transfer_tracked_patient_to_full_site_rejected_capacity(self, api):
        """PRD §3.7: "the site must have a free bed, its `current_census` strictly
        below its `bed_capacity` (`ERR_ACS_AT_CAPACITY`) — a census one below
        capacity succeeds, while a census equal to capacity fails."

        Design: Difficulty/priority_pair_validation_conflict/transfer_discharged_patient_to_full_site_state_beats_safety
        """
        incident, site, _pa, _pb = self._full_site_scenario(api)
        pc_ = create_patient(incident["id"], "P-C", triage_category="DELAYED",
                             arrival_at="2026-08-01T00:12:00Z")
        resp = api.transfer_patient(pc_["id"], {"site_id": site["id"]}, PC)
        validate_error(resp, ApiErrorId.ERR_ACS_AT_CAPACITY)

    def test_transfer_to_nonactivated_site_rejected(self, api):
        """PRD §3.7: "Transfer moves a `TRACKED` patient to an alternate care site
        by naming `site_id`, under four guards: the site must exist
        (`ERR_NOT_FOUND`); the site must be `ACTIVATED` (`ERR_SITE_NOT_ACTIVATED`)".

        Design: Corner/validations/transfer_to_nonactivated_site_rejected
        """
        incident = create_incident(incident_name="MCI-sitestate")
        site = create_site(site_name="Hall-3", bed_capacity=10)
        commit_site(site["id"], incident["id"])
        patient = create_patient(incident["id"], "P-T", triage_category="DELAYED")

        resp = api.transfer_patient(patient["id"], {"site_id": site["id"]}, PC)
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_ACTIVATED)


class TestCensusAccounting:
    def test_acs_census_capacity_gate_and_release(self, api):
        """PRD §3.7: "the site must have a free bed, its `current_census` strictly
        below its `bed_capacity` (`ERR_ACS_AT_CAPACITY`) — a census one below
        capacity succeeds, while a census equal to capacity fails."
        PRD §3.7: "Discharging a `TRANSFERRED` patient lowers the site's
        `current_census` by one — a site's census is always the count of patient
        records referencing it in `transfer_site_id` that remain in `TRANSFERRED` —
        which is how beds free up for the next transfer and how a site becomes
        eligible to demobilize."

        Design: Corner/calculations/acs_census_capacity_gate_and_release
        """
        incident, site = setup_incident_with_activated_site(
            bed_capacity=2, incident_overrides={"incident_name": "MCI-census"}
        )
        p1 = create_patient(incident["id"], "P-1", triage_category="DELAYED")
        p2 = create_patient(incident["id"], "P-2", triage_category="DELAYED",
                            arrival_at="2026-08-01T00:06:00Z")
        p3 = create_patient(incident["id"], "P-3", triage_category="MINOR",
                            arrival_at="2026-08-01T00:07:00Z")
        validate_success(api.transfer_patient(p1["id"], {"site_id": site["id"]}, PC))
        validate_success(api.transfer_patient(p2["id"], {"site_id": site["id"]}, PC))

        resp = api.transfer_patient(p3["id"], {"site_id": site["id"]}, PC)
        validate_error(resp, ApiErrorId.ERR_ACS_AT_CAPACITY)

        validate_success(api.discharge_patient(p1["id"], PC))
        site_mid = validate_success(api.get_alternate_care_site(site["id"], PC))
        assert site_mid["current_census"] == 1, "discharging TRANSFERRED frees the bed"

        retried = validate_success(api.transfer_patient(p3["id"], {"site_id": site["id"]}, PC))
        assert_patient_track_record(retried)
        assert retried["status"] == "TRANSFERRED"
        site_end = validate_success(api.get_alternate_care_site(site["id"], PC))
        assert site_end["current_census"] == 2


class TestPatientLifecycle:
    def test_patient_terminal_discharge_lockdown_rejected(self, api):
        """PRD §3.7: "`DISCHARGED` is terminal."
        PRD §2.11: "8. State-transition legality on the target resource — the
        generic guard that rejects any action whose target's current state does not
        permit it: `ERR_INVALID_STATE`."

        Design: Corner/state_machines/patient_terminal_discharge_lockdown_rejected
        """
        incident = create_incident(incident_name="MCI-lock")
        patient = create_patient(incident["id"], "P-L", triage_category="MINOR")
        discharged = validate_success(api.discharge_patient(patient["id"], PC))
        first_stamp = discharged["discharged_at"]

        resp = api.discharge_patient(patient["id"], PC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        reread = validate_success(api.get_patient_record(patient["id"], PC))
        assert reread["status"] == "DISCHARGED"
        assert reread["discharged_at"] == first_stamp, "a rejected discharge moves nothing"

    def test_patient_create_invalid_enum_triage_rejected(self, api):
        """PRD §2.11: "4. Request body shape — required fields present, types and
        enum membership valid, integer ranges respected (`quantity` strictly
        positive, `bed_capacity` strictly positive, `staffed_bed_count` and
        `projected_census` non-negative, hazard `probability`, `severity`, and
        `preparedness` each between 0 and 3 inclusive, `auto_select_count` at least
        1), `occurred_at` not after the current clock time, and a call-back create
        carrying exactly one of `staff_member_id` or `auto_select_count`:
        `ERR_INVALID_REQUEST`."
        PRD §3.7: "a START `triage_category` of `IMMEDIATE`, `DELAYED`, `MINOR`, or
        `EXPECTANT`".

        Design: Corner/entities/patient_create_invalid_enum_triage_rejected
        """
        incident = create_incident(incident_name="MCI-enum", incident_type="HUMAN")
        resp = api.create_patient_record(
            create_patient_record_payload(incident["id"], "P-X",
                                          triage_category="CRITICAL"),
            PC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_patient_ref_rejected(self, api):
        """PRD §3.7: "The reference is unique within the incident — a second record
        with the same `patient_ref` on the same incident is rejected with
        `ERR_DUPLICATE_PATIENT_REF` — and the record opens `TRACKED`".

        Design: Corner/validations/duplicate_patient_ref_rejected
        """
        incident = create_incident(incident_name="MCI-dup-pat")
        create_patient(incident["id"], "P-9", triage_category="MINOR")
        resp = api.create_patient_record(
            create_patient_record_payload(incident["id"], "P-9",
                                          triage_category="DELAYED",
                                          arrival_at="2026-08-01T00:06:00Z"),
            PC,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PATIENT_REF)


class TestDemobilizePreconditions:
    def test_demobilize_blocked_with_tracked_patients(self, api):
        """PRD §3.4: "Demobilization — `ACTIVATED` → `DEACTIVATED` — is an
        `IncidentCommander` decision with two safety preconditions: no patient
        record of this incident may still be `TRACKED`
        (`ERR_PATIENTS_STILL_TRACKED`), and no patient may still be `TRANSFERRED`
        at a site serving this incident (`ERR_PATIENTS_STILL_ON_SITE`)."

        Design: Corner/validations/demobilize_blocked_with_tracked_patients
        """
        incident = create_incident(incident_name="MCI-blocked")
        create_patient(incident["id"], "P-B1", triage_category="IMMEDIATE")

        resp = api.demobilize_incident(incident["id"], IC)
        validate_error(resp, ApiErrorId.ERR_PATIENTS_STILL_TRACKED)
        reread = validate_success(api.get_incident(incident["id"], IC))
        assert reread["status"] == "ACTIVATED"

    def test_site_demobilize_blocked_with_patients_on_site(self, api):
        """PRD §3.7: "Demobilizing a site — `ACTIVATED` → `DEMOBILIZED` — requires
        the site's `current_census` to be zero, and is otherwise rejected with
        `ERR_PATIENTS_STILL_ON_SITE`."

        Design: Corner/validations/site_demobilize_blocked_with_patients_on_site
        """
        incident, site = setup_incident_with_activated_site(
            bed_capacity=5, incident_overrides={"incident_name": "MCI-siteblock"}
        )
        create_transferred_patient(incident["id"], site["id"], "P-S1",
                                   triage_category="DELAYED")

        resp = api.demobilize_site(site["id"], IC)
        validate_error(resp, ApiErrorId.ERR_PATIENTS_STILL_ON_SITE)
        reread = validate_success(api.get_alternate_care_site(site["id"], IC))
        assert reread["status"] == "ACTIVATED"
        assert reread["current_census"] == 1

    def test_acs_activate_outside_commit_window_rejected(self, api):
        """PRD §3.7: "An `IncidentCommander` activates a `COMMITTED` site when the
        current clock time falls inside one of its commitment windows, inclusive on
        both ends — when no commitment contains the current time, the activation is
        rejected with `ERR_OUTSIDE_COMMIT_WINDOW`".

        Design: Corner/validations/acs_activate_outside_commit_window_rejected
        """
        incident = create_incident(incident_name="MCI-window")
        site = create_site(site_name="Hall-5", bed_capacity=20)
        commit_site(site["id"], incident["id"],
                    "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z")

        resp = api.activate_site(site["id"], IC)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_COMMIT_WINDOW)
        reread = validate_success(api.get_alternate_care_site(site["id"], IC))
        assert reread["status"] == "COMMITTED"


class TestPatientListing:
    def test_patient_list_filters_combine(self, api):
        """PRD §3.7: "The patient list supports optional `incident_id`,
        `transfer_site_id`, `status`, and `triage_category` filters."

        Design: Corner/endpoints/patient_list_filters_combine
        """
        incident = create_incident(incident_name="MCI-filter")
        create_patient(incident["id"], "P-1", triage_category="IMMEDIATE")
        create_patient(incident["id"], "P-2", triage_category="IMMEDIATE",
                       arrival_at="2026-08-01T00:06:00Z")
        p3 = create_patient(incident["id"], "P-3", triage_category="MINOR",
                            arrival_at="2026-08-01T00:07:00Z")
        validate_success(api.discharge_patient(p3["id"], PC))

        rows_immediate, meta_immediate = validate_paginated(
            api.list_patient_records(
                PC, params={"incident_id": incident["id"], "triage_category": "IMMEDIATE"}
            )
        )
        assert meta_immediate["total_count"] == 2
        assert {r["patient_ref"] for r in rows_immediate} == {"P-1", "P-2"}

        rows_discharged, meta_discharged = validate_paginated(
            api.list_patient_records(
                PC, params={"incident_id": incident["id"], "status": "DISCHARGED"}
            )
        )
        assert meta_discharged["total_count"] == 1
        assert rows_discharged[0]["patient_ref"] == "P-3"

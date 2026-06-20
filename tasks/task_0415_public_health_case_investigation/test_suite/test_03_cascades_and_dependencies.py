"""Depth-3 cascades, cross-entity state dependencies, and conserved-counter invariants.

Queue A (Difficulty): transitive_cascade, cross_entity_state_dependency,
compensating_invariant.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_investigator_headers,
    make_tracer_headers,
    make_epi_headers,
    ApiErrorId,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Queue A — transitive_cascade
# ===========================================================================
class TestNotACaseCascade:
    """classify NOT_A_CASE -> contact VOIDED -> ACTIVE monitoring RELEASED_EARLY +
    jurisdiction active_monitoring_count decremented + case contact_count decremented."""

    def _setup(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
        j = jurisdiction["id"]
        fx.set_clock(program["id"], "2026-03-01T00:00:00.000Z")
        ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
        contact_after, mp = fx.setup_monitoring_active_contact(
            program["id"], ci["id"], j, contact_overrides={"contact_reference": "K-M"}
        )
        return j, ci["id"], contact_after["id"], mp["id"], jurisdiction["id"]

    def test_classify_not_a_case_voids_contact_and_releases_monitoring(self, api):
        """PRD §3.4: "If the requested classification is `NOT_A_CASE`, the system runs a
        depth-three cascade. Every non-`VOIDED` contact whose `source_case_id` equals this case
        is voided. For each such contact that is in `MONITORING_ACTIVE`, its `ACTIVE` monitoring
        period is first released to `RELEASED_EARLY` and the contact's `monitoring_jurisdiction`'s
        `active_monitoring_count` is decremented by one; then, for every voided contact, the
        case's `contact_count` is decremented by one."

        Design: Difficulty/transitive_cascade/not_a_case_classify_voids_contacts_releases_monitoring_depth3
        """
        j, case_id, contact_id, mp_id, _ = self._setup()
        result = validate_success(
            api.classify_case(case_id, {"classification": "NOT_A_CASE"}, make_investigator_headers(j))
        )
        assert result["classification"] == "NOT_A_CASE"
        contact = validate_success(api.get_contact(contact_id, make_tracer_headers(j)))
        assert contact["status"] == "VOIDED"
        mp = validate_success(api.get_monitoring_period(mp_id, make_tracer_headers(j)))
        assert mp["status"] == "RELEASED_EARLY"

    def test_classify_not_a_case_decrements_conserved_counters(self, api):
        """PRD §3.4: "the contact's `monitoring_jurisdiction`'s `active_monitoring_count` is
        decremented by one; then, for every voided contact, the case's `contact_count` is
        decremented by one."

        Design: Difficulty/transitive_cascade/not_a_case_classify_voids_contacts_releases_monitoring_depth3
        """
        j, case_id, contact_id, mp_id, jid = self._setup()
        validate_success(
            api.classify_case(case_id, {"classification": "NOT_A_CASE"}, make_investigator_headers(j))
        )
        jur = validate_success(api.get_jurisdiction(jid, make_investigator_headers(j)))
        assert jur["active_monitoring_count"] == 0, jur["active_monitoring_count"]
        case = validate_success(api.get_case(case_id, make_investigator_headers(j)))
        assert case["contact_count"] == 0, case["contact_count"]


class TestTransferAcceptCascade:
    """transfer accept -> case rehomed J1->J2 -> contact reassigned to J2 with its
    MONITORING_ACTIVE count moved from J1 to J2."""

    def _setup(self):
        program = fx.create_program()
        j1 = fx.create_jurisdiction(program["id"], name="County 1", fips_code="06001")
        j2 = fx.create_jurisdiction(program["id"], name="County 2", fips_code="06002")
        fx.create_condition(program["id"])
        ct = fx.open_and_interview_case(program["id"], j1["id"], case_overrides={"patient_reference": "PT-T"})
        contact_after, _ = fx.setup_monitoring_active_contact(
            program["id"], ct["id"], j1["id"], contact_overrides={"contact_reference": "K-T"}
        )
        version = fx.observe_case_version(ct["id"])
        transfer = fx.request_transfer(program["id"], ct["id"], j2["id"], version)
        return ct["id"], contact_after["id"], j1["id"], j2["id"], transfer["id"]

    def test_accept_rehomes_case_and_reassigns_contact(self, api):
        """PRD §3.12: "Accepting advances the transfer `REQUESTED → ACCEPTED` and rehomes the
        case: the case's `jurisdiction_id` becomes the transfer's `to_jurisdiction_id`, and a
        depth-three cascade follows — every non-`VOIDED` contact whose `source_case_id` equals
        the case and whose `monitoring_jurisdiction_id` equals the old jurisdiction is reassigned
        to the new `to_jurisdiction_id`".

        Design: Difficulty/transitive_cascade/transfer_accept_rehomes_case_and_monitoring_depth3
        """
        case_id, contact_id, j1, j2, transfer_id = self._setup()
        result = validate_success(
            api.resolve_transfer(transfer_id, {"status": "ACCEPTED"}, make_epi_headers())
        )
        assert result["status"] == "ACCEPTED"
        case = validate_success(api.get_case(case_id, make_epi_headers()))
        assert case["jurisdiction_id"] == j2
        assert case["status"] == "UNDER_INVESTIGATION"
        contact = validate_success(api.get_contact(contact_id, make_tracer_headers(j2)))
        assert contact["monitoring_jurisdiction_id"] == j2

    def test_accept_moves_active_monitoring_count_between_jurisdictions(self, api):
        """PRD §3.12: "for any such contact in `MONITORING_ACTIVE` its contribution to the
        active-monitoring count moves from the old jurisdiction's `active_monitoring_count` to
        the new jurisdiction's."

        Design: Difficulty/transitive_cascade/transfer_accept_rehomes_case_and_monitoring_depth3
        """
        case_id, contact_id, j1, j2, transfer_id = self._setup()
        validate_success(
            api.resolve_transfer(transfer_id, {"status": "ACCEPTED"}, make_epi_headers())
        )
        jur1 = validate_success(api.get_jurisdiction(j1, make_epi_headers()))
        jur2 = validate_success(api.get_jurisdiction(j2, make_epi_headers()))
        assert jur1["active_monitoring_count"] == 0, jur1["active_monitoring_count"]
        assert jur2["active_monitoring_count"] == 1, jur2["active_monitoring_count"]


# ===========================================================================
# Queue A — cross_entity_state_dependency
# ===========================================================================
class TestCaseCloseBlockedByActiveMonitoring:
    """A CLASSIFIED case with a MONITORING_ACTIVE contact cannot close."""

    def _setup(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
            condition_overrides={"requires_lab_confirmation": False}
        )
        j = jurisdiction["id"]
        fx.set_clock(program["id"], "2026-04-01T00:00:00.000Z")
        case = fx.open_interview_classify_case(program["id"], j, "PROBABLE", case_overrides={"patient_reference": "PT-K"})
        contact_after, _ = fx.setup_monitoring_active_contact(
            program["id"], case["id"], j, contact_overrides={"contact_reference": "K-K"}
        )
        return j, case["id"], contact_after["id"]

    def test_close_rejected_while_contact_monitoring_active(self, api):
        """PRD §3.4: "no contact whose `source_case_id` equals this case may be in
        `MONITORING_ACTIVE`, or the close is rejected with `ERR_ACTIVE_MONITORING_EXISTS`".

        Design: Difficulty/cross_entity_state_dependency/case_close_blocked_by_active_monitoring_contact
        """
        j, case_id, _ = self._setup()
        res = api.close_case(case_id, make_investigator_headers(j))
        validate_error(res, ApiErrorId.ERR_ACTIVE_MONITORING_EXISTS.value)
        case = validate_success(api.get_case(case_id, make_investigator_headers(j)))
        assert case["status"] == "CLASSIFIED"

    def test_close_succeeds_after_monitoring_completes(self, api):
        """PRD §3.8: "On success the contact advances `MONITORING_ACTIVE → MONITORING_COMPLETE`".
        PRD §3.4: "Closing is legal only from `CLASSIFIED`, rejected otherwise with
        `ERR_CASE_NOT_CLOSEABLE`."

        Design: Difficulty/cross_entity_state_dependency/case_close_blocked_by_active_monitoring_contact
        """
        j, case_id, contact_id = self._setup()
        # clock is at 2026-04-01, past quarantine_end (2026-03-29) -> complete is allowed
        validate_success(api.complete_monitoring(contact_id, make_tracer_headers(j)))
        data = validate_success(api.close_case(case_id, make_investigator_headers(j)))
        assert data["status"] == "CLOSED"


class TestNedssTransmitBlockedWhenReclassified:
    """An export snapshotted while the case was CONFIRMED cannot transmit once the case is
    reopened and reclassified PROBABLE."""

    def _setup(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
            condition_overrides={"requires_lab_confirmation": False}
        )
        j = jurisdiction["id"]
        case = fx.open_interview_classify_case(program["id"], j, "CONFIRMED", case_overrides={"patient_reference": "PT-N"})
        export = fx.generate_export(program["id"], case["id"])
        validate_success(api_client.close_case(case["id"], make_investigator_headers(j)))
        validate_success(api_client.reopen_case(case["id"], make_investigator_headers(j)))
        validate_success(api_client.interview_case(case["id"], {}, make_investigator_headers(j)))
        validate_success(
            api_client.classify_case(case["id"], {"classification": "PROBABLE"}, make_investigator_headers(j))
        )
        return export["id"]

    def test_transmit_rejected_when_snapshot_stale(self, api):
        """PRD §3.13: "the referenced case's current `classification` must still equal the
        export's `snapshot_classification`, or transmission is rejected with
        `ERR_EXPORT_SNAPSHOT_STALE`."

        Design: Difficulty/cross_entity_state_dependency/nedss_transmit_blocked_when_case_reclassified
        """
        export_id = self._setup()
        res = api.transmit_export(export_id, make_epi_headers())
        validate_error(res, ApiErrorId.ERR_EXPORT_SNAPSHOT_STALE.value)

    def test_export_remains_generated_after_failed_transmit(self, api):
        """PRD §3.13: "Transmission is legal only from `GENERATED`, rejected otherwise with
        `ERR_EXPORT_NOT_TRANSMITTABLE`."
        PRD §3.13: "On creation the export begins in `GENERATED`".

        Design: Difficulty/cross_entity_state_dependency/nedss_transmit_blocked_when_case_reclassified
        """
        export_id = self._setup()
        api.transmit_export(export_id, make_epi_headers())
        data = validate_success(api.get_export(export_id, make_epi_headers()))
        assert data["status"] == "GENERATED"


# ===========================================================================
# Queue A — compensating_invariant
# ===========================================================================
class TestContactCountConserved:
    """Case.contact_count rises on elicit and falls on void, returning to its pre-action value."""

    def _setup(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
        j = jurisdiction["id"]
        ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
        kv = fx.elicit_contact(
            program["id"], ci["id"], j, contact_reference="K-V",
            exposure_setting="SOCIAL", proximity_meters=1.5, cumulative_exposure_minutes=10,
        )
        return j, ci["id"], kv["id"]

    def test_contact_count_rises_on_elicit(self, api):
        """PRD §3.6: "Eliciting a contact increments the source case's `contact_count` by one
        and recomputes that case's completeness score."

        Design: Difficulty/compensating_invariant/contact_count_conserved_under_elicit_then_void
        """
        j, case_id, _ = self._setup()
        case = validate_success(api.get_case(case_id, make_investigator_headers(j)))
        assert case["contact_count"] == 1, case["contact_count"]

    def test_contact_count_returns_to_zero_after_void(self, api):
        """PRD §3.9: "Voiding advances the contact to `VOIDED`, decrements the source case's
        `contact_count` by one, and recomputes the source case's completeness score."

        Design: Difficulty/compensating_invariant/contact_count_conserved_under_elicit_then_void
        """
        j, case_id, contact_id = self._setup()
        data = validate_success(api.void_contact(contact_id, make_tracer_headers(j)))
        assert data["status"] == "VOIDED"
        case = validate_success(api.get_case(case_id, make_investigator_headers(j)))
        assert case["contact_count"] == 0, case["contact_count"]


class TestJurisdictionMonitoringLoadConserved:
    """Jurisdiction.active_monitoring_count rises on start-monitoring and falls on
    complete-monitoring, returning to its pre-action value."""

    def _setup(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
        j = jurisdiction["id"]
        fx.set_clock(program["id"], "2026-04-01T00:00:00.000Z")
        ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
        contact_after, _ = fx.setup_monitoring_active_contact(
            program["id"], ci["id"], j, contact_overrides={"contact_reference": "K-L"}
        )
        return j, jurisdiction["id"], contact_after["id"]

    def test_monitoring_load_rises_on_start(self, api):
        """PRD §3.8: "On success the contact advances `NOTIFIED → MONITORING_ACTIVE`, its
        scheduled monitoring period advances `SCHEDULED → ACTIVE`, and the contact's
        `monitoring_jurisdiction`'s `active_monitoring_count` is incremented by one."

        Design: Difficulty/compensating_invariant/jurisdiction_monitoring_load_conserved_under_start_then_complete
        """
        j, jid, _ = self._setup()
        jur = validate_success(api.get_jurisdiction(jid, make_investigator_headers(j)))
        assert jur["active_monitoring_count"] == 1, jur["active_monitoring_count"]

    def test_monitoring_load_returns_to_zero_after_complete(self, api):
        """PRD §3.8: "On success the contact advances `MONITORING_ACTIVE → MONITORING_COMPLETE`,
        its active monitoring period advances `ACTIVE → COMPLETED`, and the
        `monitoring_jurisdiction`'s `active_monitoring_count` is decremented by one."

        Design: Difficulty/compensating_invariant/jurisdiction_monitoring_load_conserved_under_start_then_complete
        """
        j, jid, contact_id = self._setup()
        data = validate_success(api.complete_monitoring(contact_id, make_tracer_headers(j)))
        assert data["status"] == "MONITORING_COMPLETE"
        jur = validate_success(api.get_jurisdiction(jid, make_investigator_headers(j)))
        assert jur["active_monitoring_count"] == 0, jur["active_monitoring_count"]

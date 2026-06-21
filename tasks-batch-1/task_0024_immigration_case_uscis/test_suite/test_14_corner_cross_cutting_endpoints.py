"""Corner (cross_cutting + endpoints) — OCC stale-version on both writes and
FK reverse-reachability listings."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    setup_under_review_i130,
    setup_rfe_pending_i130,
    setup_biometrics_scheduled_i485,
    make_applicant_headers,
    decide_case_payload,
    rfe_respond_payload,
    issue_rfe_payload,
    set_clock,
    register_applicant,
    create_draft_case,
    file_case,
)


class TestOccStaleCaseVersionOnDecide:

    def test_decide_with_stale_case_version_returns_412(self, api):
        """PRD §2.10: "Two write endpoints require the client to pin the version of the
        parent `Case` that the request was prepared against. Both endpoints take
        `expected_case_version` as a non-optional input field carrying the
        client's last observed `Case.version`. If the value does not equal the
        case's current `version`, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412); no state is mutated."

        PRD §2.11 (the validation-priority list) places source-state correctness
        (`ERR_INVALID_STATE`) STRICTLY ABOVE OCC stale-version (`ERR_STALE_VERSION`)
        — and explicitly says "if the same request would have failed a state
        check ..., the client sees that more specific error rather than
        ERR_STALE_VERSION". The §2.10 narrative example (RFE issued moves case
        out of UNDER_REVIEW, which is also a state change) therefore admits two
        PRD-faithful outcomes here: ERR_STALE_VERSION (per §2.10 narrative) or
        ERR_INVALID_STATE (per §2.11 priority). Both readings of PRD are
        consistent with this test path.

        Design: Corner/cross_cutting/occ_stale_case_version_on_decide_returns_412
        """
        applicant, case_ur, officer = setup_under_review_i130()
        stale_v = case_ur["version"]
        # Advance the case version legitimately: issue an RFE.
        api.issue_rfe(case_ur["id"], issue_rfe_payload(["bump_version"]), officer)
        # /decide with the stale version → either ERR_STALE_VERSION (per §2.10
        # narrative) or ERR_INVALID_STATE (per §2.11 priority list — case is
        # now RFE_PENDING and decide requires UNDER_REVIEW).
        res = api.decide_case(
            case_ur["id"],
            decide_case_payload("APPROVE", stale_v),
            officer,
        )
        validate_error_is_one_of(res, ["ERR_STALE_VERSION", "ERR_INVALID_STATE"])


class TestOccStaleCaseVersionOnRfeRespond:

    def test_respond_with_stale_case_version_returns_412(self, api):
        """PRD §2.10: "The second is the applicant's RFE-response capability... the
        applicant's `expected_case_version` no longer matches, and the response
        is rejected"
        PRD §5: "`ERR_STALE_VERSION` | 412 Precondition Failed"

        Design: Corner/cross_cutting/occ_stale_case_version_on_rfe_respond_returns_412
        """
        applicant, case_rfe, rfe, _officer = setup_rfe_pending_i130()
        # Deliberately stale: one less than the current Case.version.
        stale = case_rfe["version"] - 1
        applicant_headers = make_applicant_headers(applicant["id"])
        res = api.respond_to_rfe(
            rfe["id"],
            rfe_respond_payload(stale, "Deliberately stale version"),
            applicant_headers,
        )
        validate_error(res, "ERR_STALE_VERSION")
        # No state mutated.
        rfe_after = get_success_data(api.get_rfe(rfe["id"], applicant_headers))
        assert rfe_after["status"] == "ISSUED"
        case_after = get_success_data(api.get_case(case_rfe["id"], applicant_headers))
        assert case_after["status"] == "RFE_PENDING"


class TestListCaseEventsReturnsChronologicalLog:

    def test_filed_case_has_status_change_and_fee_assessed_events(self, api):
        """PRD §3.2: "It appends a `CaseEvent` of type `STATUS_CHANGE` with `from_status`
        `DRAFT` and `to_status` `FILED`, a `CaseEvent` of type `FEE_ASSESSED` with
        the computed fee in its `payload_json`"

        Design: Corner/endpoints/list_case_events_returns_chronological_log
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant()
        case = create_draft_case(applicant, case_type="I-130",
                                 preference_category="IR")
        file_case(case, applicant)
        headers = make_applicant_headers(applicant["id"])
        events = validate_success(api.list_case_events(case["id"], headers), 200)
        evt_types = [e.get("event_type") for e in events]
        # STATUS_CHANGE with from=DRAFT to=FILED is appended.
        status_changes = [
            e for e in events
            if e.get("event_type") == "STATUS_CHANGE"
            and e.get("from_status") == "DRAFT"
            and e.get("to_status") == "FILED"
        ]
        assert len(status_changes) >= 1, (
            f"Expected a STATUS_CHANGE event for DRAFT→FILED, got events: {evt_types!r}"
        )
        assert "FEE_ASSESSED" in evt_types


class TestListBiometricsByCaseReturnsAppointments:

    def test_list_biometrics_by_case_returns_scheduled_appointment(self, api):
        """PRD §4: "`GET /uscis/cases/{id}/biometrics` ... List biometrics appointments for a case."
        PRD §3.3: "On a successful schedule, a new `BiometricsAppointment` is created with
        `status` `SCHEDULED` and a `case_id` foreign key to its parent case"

        Design: Corner/endpoints/list_biometrics_by_case_returns_appointments
        """
        applicant, case, biom, officer = setup_biometrics_scheduled_i485(
            asc_location_code="ASC-SF-40",
        )
        listing = validate_success(
            api.list_biometrics_for_case(case["id"], officer), 200
        )
        assert isinstance(listing, list)
        assert len(listing) == 1
        assert listing[0]["id"] == biom["id"]
        assert listing[0]["case_id"] == case["id"]

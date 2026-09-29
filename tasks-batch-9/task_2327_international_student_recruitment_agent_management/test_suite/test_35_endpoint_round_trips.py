"""Round trips across the surfaces that only a read-after-write can prove.

Each group writes through one endpoint and then reads the same fact back through
another one — a detail view, a filtered list, a computed projection or the
territory occupancy view — so the stored record and the derived view must agree.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_empty_diligence_checklist,
    assert_fresh_agency_defaults,
    assert_occupancy,
    assert_projection,
    assert_risk_profile,
    assert_version,
)
from test_helpers.test_users import COMPLIANCE, FINANCE_APPROVER, OFFICER


class TestAgencyCrudRoundTrip:
    @pytest.fixture()
    def two_agencies(self, client):
        """One bare registration and one fully vetted neighbour."""
        bare = fx.register_agency(
            client,
            legal_name="CRUD Agency One",
            home_country_code="IN",
            complete_diligence=False,
        )
        vetted = fx.register_agency(
            client, legal_name="CRUD Agency Two", home_country_code="VN"
        )
        fx.clear_agency(client, vetted["id"])
        return {"bare": bare, "bare_id": bare["id"], "vetted_id": vetted["id"]}

    def test_a_bare_registration_reads_back_with_every_documented_default(
        self, client, two_agencies
    ):
        """Nothing but the two mandatory fields was supplied.

        "The four due-diligence checklist items may be supplied at registration or
        filled in later: `ownership_disclosed` and `sanctions_screen_passed` are
        booleans that both default to false, while `beneficial_owner_count` and
        `reference_check_count` are non-negative integers that both default to 0."

        "A newly registered agency begins in `DRAFT` on the due-diligence dimension
        and `GOOD_STANDING` on the integrity dimension, with `rolling_risk_score` and
        `lifetime_risk_score` both at 0.00"

        Design: Corner/endpoints/agency_crud_round_trip_read_patch_list
        """
        agency = fx.read_agency(client, two_agencies["bare_id"])

        assert agency["legal_name"] == "CRUD Agency One"
        assert agency["home_country_code"] == "IN"
        assert_fresh_agency_defaults(agency)
        assert_empty_diligence_checklist(agency)
        assert_version(agency, 1)

    def test_the_patch_writes_every_editable_field_and_bumps_the_version(
        self, client, two_agencies
    ):
        """The officer's edit is visible to the agency reading its own record.

        "A `RecruitmentOfficer`, or the agency itself acting as `AgencyOwner`, may
        revise `legal_name`, `ownership_disclosed`, `beneficial_owner_count`,
        `sanctions_screen_passed` and `reference_check_count`"

        "Editing bumps the agency's `version`."

        Design: Corner/endpoints/agency_crud_round_trip_read_patch_list
        """
        agency_id = two_agencies["bare_id"]
        before = two_agencies["bare"]["version"]

        patched = validate_success(
            client.patch_agency(
                agency_id,
                {
                    "legal_name": "CRUD Agency One Pvt Ltd",
                    "ownership_disclosed": True,
                    "beneficial_owner_count": 1,
                    "sanctions_screen_passed": True,
                    "reference_check_count": 2,
                },
                OFFICER,
            )
        )
        assert_version(patched, before + 1)

        as_owner = validate_success(
            client.get_agency(agency_id, fx.make_agency_owner_headers(agency_id))
        )
        assert as_owner["legal_name"] == "CRUD Agency One Pvt Ltd"
        assert as_owner["ownership_disclosed"] is True
        assert as_owner["beneficial_owner_count"] == 1
        assert as_owner["sanctions_screen_passed"] is True
        assert as_owner["reference_check_count"] == 2
        assert as_owner["home_country_code"] == "IN"

    def test_the_list_window_reports_the_full_set_in_registration_order(
        self, client, two_agencies
    ):
        """Two rows fit inside a ten-item window, so nothing remains beyond it.

        "Unless a specific endpoint states otherwise, list results are ordered by
        `created_at` ascending."

        "`total_count` is the size of the full filtered result set, not the size of
        the returned page, and `has_more` is true exactly when items remain beyond
        the current window."

        Design: Corner/endpoints/agency_crud_round_trip_read_patch_list
        """
        rows, meta = validate_paginated(
            client.list_agencies(OFFICER, {"limit": 10, "offset": 0})
        )

        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [
            two_agencies["bare_id"],
            two_agencies["vetted_id"],
        ]
        assert rows[0]["vetting_state"] == C.VETTING_DRAFT
        assert rows[1]["vetting_state"] == C.VETTING_CLEARED


class TestPostureWatchRoundTrip:
    @pytest.fixture()
    def cleared_agency(self, client):
        """A cleared agency with an unblemished integrity standing."""
        agency = fx.register_agency(client, legal_name="Posture Agency")
        fx.clear_agency(client, agency["id"])
        return fx.read_agency(client, agency["id"])

    def test_a_manual_watch_moves_only_the_integrity_dimension(
        self, client, cleared_agency
    ):
        """Due diligence stays cleared while posture drops to watch.

        "A `ComplianceOfficer` may also move posture by hand, supplying an `action`
        and a mandatory `reason`; every posture change, manual or automatic, records
        the reason into `last_posture_reason` and increments the agency's `version`."

        "`PLACE_ON_WATCH` moves `GOOD_STANDING → WATCH`."

        Design: Corner/endpoints/posture_action_places_agency_on_watch_and_clears_it
        """
        agency_id = cleared_agency["id"]

        watched = fx.posture_action(
            client,
            agency_id,
            C.POSTURE_PLACE_ON_WATCH,
            "Peer university reported aggressive marketing",
        )
        assert watched["compliance_posture"] == C.POSTURE_WATCH
        assert watched["vetting_state"] == C.VETTING_CLEARED
        assert (
            watched["last_posture_reason"]
            == "Peer university reported aggressive marketing"
        )

    def test_the_hand_moved_posture_leaves_the_computed_risk_bands_untouched(
        self, client, cleared_agency
    ):
        """No incident and no document was ever adjudicated, so the scores stay flat.

        "`posture_band`, the band the rolling figure currently falls in:
        `GOOD_STANDING` below 40.00, `WATCH` from 40.00, `PROBATION` from 65.00, and
        `SUSPENDED` from 85.00."

        Design: Corner/endpoints/posture_action_places_agency_on_watch_and_clears_it
        """
        agency_id = cleared_agency["id"]
        fx.posture_action(
            client,
            agency_id,
            C.POSTURE_PLACE_ON_WATCH,
            "Peer university reported aggressive marketing",
        )

        assert_risk_profile(
            fx.read_risk_profile(client, agency_id),
            rolling_risk_score=0.00,
            lifetime_risk_score=0.00,
            lifetime_minus_rolling_delta=0.00,
            confirmed_incident_count=0,
            reviewed_document_count=0,
            confirmed_fraud_document_count=0,
            posture_band=C.POSTURE_GOOD_STANDING,
        )

    def test_clearing_the_watch_returns_good_standing_and_costs_two_versions(
        self, client, cleared_agency
    ):
        """The rolling figure is 0.00, so the de-escalation precondition holds.

        "`CLEAR_WATCH` moves `WATCH → GOOD_STANDING`, and only when
        `rolling_risk_score` is strictly below 40.00."

        Design: Corner/endpoints/posture_action_places_agency_on_watch_and_clears_it
        """
        agency_id = cleared_agency["id"]
        before = cleared_agency["version"]

        fx.posture_action(
            client,
            agency_id,
            C.POSTURE_PLACE_ON_WATCH,
            "Peer university reported aggressive marketing",
        )
        restored = fx.posture_action(
            client,
            agency_id,
            C.POSTURE_CLEAR_WATCH,
            "Marketing review closed with no finding",
        )

        assert restored["compliance_posture"] == C.POSTURE_GOOD_STANDING
        assert restored["last_posture_reason"] == "Marketing review closed with no finding"
        assert_version(restored, before + 2)


class TestProjectionOnADraftFile:
    @pytest.fixture()
    def draft_application(self, client):
        """A file that has never been submitted, so nothing was ever frozen."""
        agency = fx.register_agency(client, legal_name="Projection Agency")
        fx.clear_agency(client, agency["id"])
        program = fx.create_program(client, annual_tuition_cents=2000000)
        application = fx.create_application(
            client, agency["id"], program["id"], student_ref="STU-DRAFT"
        )
        return {"application": application, "application_id": application["id"]}

    def test_the_side_by_side_view_is_all_zero_before_submission(
        self, client, draft_application
    ):
        """No projection was frozen and no entry was ever written.

        "Both figures are readable side by side on a per-application computed view,
        which reports `provisional_projection_cents` mirroring
        `projected_commission_cents`, `final_net_cents` mirroring
        `net_commission_cents`, and `variant_delta_cents` as the provisional
        projection minus the final net."

        "`projected_commission_cents` and `net_commission_cents` at 0, and
        `integrity_hold` false."

        Design: Corner/endpoints/commission_projection_on_draft_application_is_all_zero
        """
        projection = validate_success(
            client.get_commission_projection(
                draft_application["application_id"], FINANCE_APPROVER
            )
        )

        assert_projection(
            projection,
            provisional_projection_cents=0,
            final_net_cents=0,
            variant_delta_cents=0,
            accrued_entry_count=0,
            clawback_entry_count=0,
        )

    def test_the_view_echoes_the_pins_that_submission_has_not_yet_set(
        self, client, draft_application
    ):
        """Reading a computed view is not a mutation of the file it reports on.

        "The same view echoes the frozen `tier_snapshot_at_submission` and
        `pinned_schedule_id`, and reports `accrued_entry_count` and
        `clawback_entry_count` for the application."

        "`version`, an integer that starts at 1 on creation and increments by one on
        every mutation of that resource"

        Design: Corner/endpoints/commission_projection_on_draft_application_is_all_zero
        """
        application_id = draft_application["application_id"]
        before = draft_application["application"]["version"]

        projection = fx.read_projection(client, application_id)
        assert projection["tier_snapshot_at_submission"] is None
        assert projection["pinned_schedule_id"] is None

        assert_version(fx.read_application(client, application_id), before)


class TestTerritoryReleaseIsScopedToItsContract:
    @pytest.fixture()
    def assignment_under_the_first_contract(self, client):
        """One exclusive Indian assignment, and a second contract that does not own it."""
        first = fx.register_agency(
            client, legal_name="Route Scope Agency One", home_country_code="IN"
        )
        fx.clear_agency(client, first["id"])
        second = fx.register_agency(
            client, legal_name="Route Scope Agency Two", home_country_code="VN"
        )
        fx.clear_agency(client, second["id"])

        owning = fx.draft_contract(client, first["id"], contract_ref="CTR-001")
        fx.append_schedule(client, owning["id"], owning["version"])
        assignment = fx.assign_territory(
            client,
            owning["id"],
            country_code="IN",
            exclusivity=C.TERRITORY_EXCLUSIVE,
            start_date="2026-08-01",
            end_date="2027-07-31",
        )
        foreign = fx.draft_contract(
            client,
            second["id"],
            contract_ref="CTR-002",
            exclusivity_model=C.EXCLUSIVITY_NON_EXCLUSIVE_ONLY,
        )

        return {
            "owning_contract_id": owning["id"],
            "foreign_contract_id": foreign["id"],
            "assignment_id": assignment["id"],
        }

    def test_releasing_through_the_wrong_contract_resolves_to_nothing(
        self, client, assignment_under_the_first_contract
    ):
        """The identifier is real; the path it was quoted under is not its own.

        "A territory assignment identifier resolves only *under* the contract named
        earlier in the path; an assignment that exists but belongs to a different
        contract is `ERR_ASSIGNMENT_NOT_FOUND`."

        Design: Corner/endpoints/territory_release_under_wrong_contract_returns_not_found
        """
        env = assignment_under_the_first_contract

        refused = client.release_territory(
            env["foreign_contract_id"], env["assignment_id"], OFFICER
        )
        validate_error(refused, E.ERR_ASSIGNMENT_NOT_FOUND, 404)

        assignments = fx.read_assignments(client, env["owning_contract_id"])
        assert len(assignments) == 1
        assert assignments[0]["status"] == C.ASSIGNMENT_ACTIVE
        assert assignments[0]["released_on"] is None

    def test_the_same_release_under_the_owning_contract_frees_the_slot_that_day(
        self, client, assignment_under_the_first_contract
    ):
        """The exclusive slot is available the same day the release lands.

        "A `RecruitmentOfficer` or `ComplianceOfficer` may release an assignment
        early, moving `ACTIVE → RELEASED` with `released_on` set to the current
        logical-clock date."

        "Release is immediate and total: the country's exclusive-slot occupancy drops
        at once and no cool-off buffer survives a release, so the freed slot is
        available the same day."

        Design: Corner/endpoints/territory_release_under_wrong_contract_returns_not_found
        """
        env = assignment_under_the_first_contract

        released = fx.release_territory(
            client, env["owning_contract_id"], env["assignment_id"], headers=COMPLIANCE
        )
        assert released["status"] == C.ASSIGNMENT_RELEASED
        assert released["released_on"] == C.DEFAULT_CLOCK_DATE

        assert_occupancy(
            fx.read_occupancy(client, "IN", C.DEFAULT_CLOCK_DATE),
            country_code="IN",
            at_date=C.DEFAULT_CLOCK_DATE,
            exclusive_active_count=0,
            non_exclusive_active_count=0,
            exclusive_cooloff_until=None,
            exclusive_slot_available=True,
        )


class TestIncidentAttachmentIsLayered:
    @pytest.fixture()
    def incident_on_a_document(self, client):
        """An incident naming an agency, one of its files and one document on it."""
        agency = fx.register_agency(client, legal_name="Linked Incident Agency")
        fx.clear_agency(client, agency["id"])
        program = fx.create_program(client)
        application = fx.create_application(
            client, agency["id"], program["id"], student_ref="STU-001"
        )
        document = fx.upload_document(
            client,
            agency["id"],
            application["id"],
            C.DOC_TRANSCRIPT,
            "hash-link-001",
            "Delhi University",
            declared_signals=[],
        )
        incident = validate_success(
            client.file_incident(
                F.incident_payload(
                    agency["id"],
                    category=C.INCIDENT_MISREPRESENTATION,
                    severity=C.SEVERITY_MEDIUM,
                    occurred_on=C.DEFAULT_CLOCK_DATE,
                    source=C.SOURCE_STUDENT_COMPLAINT,
                    application_id=application["id"],
                    document_id=document["id"],
                ),
                OFFICER,
            ),
            201,
        )
        return {
            "agency_id": agency["id"],
            "application_id": application["id"],
            "document_id": document["id"],
            "incident": incident,
        }

    def test_all_three_links_are_stored_on_the_reported_incident(
        self, client, incident_on_a_document
    ):
        """The deepest of the three attachment shapes is accepted whole.

        "A `RecruitmentOfficer` or `ComplianceOfficer` files an integrity incident
        against an `agency_id`, optionally tying it to an `application_id` and
        further to a `document_id`"

        "The incident lands in `status` `REPORTED` and contributes nothing to risk
        until it is adjudicated."

        Design: Corner/endpoints/incident_links_agency_application_and_document
        """
        env = incident_on_a_document
        incident = env["incident"]

        assert incident["agency_id"] == env["agency_id"]
        assert incident["application_id"] == env["application_id"]
        assert incident["document_id"] == env["document_id"]
        assert incident["status"] == C.INCIDENT_REPORTED

    def test_the_incident_is_findable_by_each_link_it_carries(
        self, client, incident_on_a_document
    ):
        """Both the document filter and the application filter return the one row.

        "Incidents may be listed and filtered on `agency_id`, `application_id`,
        `document_id`, `category` and `status`."

        Design: Corner/endpoints/incident_links_agency_application_and_document
        """
        env = incident_on_a_document

        by_document, document_meta = validate_paginated(
            client.list_incidents(COMPLIANCE, {"document_id": env["document_id"]})
        )
        assert document_meta["total_count"] == 1
        assert by_document[0]["id"] == env["incident"]["id"]

        by_application, application_meta = validate_paginated(
            client.list_incidents(
                COMPLIANCE,
                {
                    "application_id": env["application_id"],
                    "status": C.INCIDENT_REPORTED,
                },
            )
        )
        assert application_meta["total_count"] == 1
        assert by_application[0]["id"] == env["incident"]["id"]

    def test_a_merely_reported_incident_scores_nothing(
        self, client, incident_on_a_document
    ):
        """Filing is not adjudicating, so the rolling figure stays at zero.

        "only incidents in `CONFIRMED` contribute — those in `REPORTED` or
        `DISMISSED` never do"

        Design: Corner/endpoints/incident_links_agency_application_and_document
        """
        env = incident_on_a_document

        agency = fx.read_agency(client, env["agency_id"])
        assert agency["confirmed_incident_count"] == 0
        assert_cents(agency["clawback_liability_cents"], 0, "clawback_liability_cents")

        assert_risk_profile(
            fx.read_risk_profile(client, env["agency_id"]),
            rolling_risk_score=0.00,
            lifetime_risk_score=0.00,
            lifetime_minus_rolling_delta=0.00,
            confirmed_incident_count=0,
            reviewed_document_count=0,
            confirmed_fraud_document_count=0,
            posture_band=C.POSTURE_GOOD_STANDING,
        )

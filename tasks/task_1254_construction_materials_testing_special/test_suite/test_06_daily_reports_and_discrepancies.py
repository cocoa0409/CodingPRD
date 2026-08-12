"""Daily inspection reports to the building official and the discrepancy
negotiation loop with contractor / engineer of record."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    certification_entry,
    complete_assignment,
    create_assignment,
    create_technician,
    dispatch_assignment,
    make_technician_headers,
    raise_discrepancy,
    record_soil_test,
    respond_to_discrepancy,
    setup_approved_project,
    setup_dispatched_assignment,
    setup_ready_for_letter,
    soil_scope_item,
    submit_daily_report,
    validate_error,
    validate_success,
    weld_scope_item,
)

PM = TEST_USERS["project_manager_headers"]
ENGINEER = TEST_USERS["engineer_of_record_headers"]
CONTRACTOR = TEST_USERS["contractor_headers"]
BUILDING_OFFICIAL = TEST_USERS["building_official_headers"]


def _completed_assignment(ctx, tech_id, start, end, work_date="2026-05-04"):
    asg = create_assignment(
        ctx["project"]["id"], ctx["scope_items"][0]["id"], tech_id, work_date, start, end
    )
    dispatch_assignment(asg["id"])
    record_soil_test(asg["id"], tech_id, 118.0)
    complete_assignment(asg["id"], tech_id)
    return asg


class TestDailyReports:
    def test_second_daily_report_for_same_triple_rejected(self, api):
        """PRD §3.7: "One report per project, technician, and date is the hard
        rule: a second submission for the same triple is rejected with
        `ERR_DUPLICATE_DAILY_REPORT`."

        Design: Corner/validations/duplicate_daily_report_rejected
        """
        ctx = setup_approved_project(
            [soil_scope_item(required_count=3)],
            project_overrides={"name": "DupDIR", "permit_number": "P-VAL-2"},
        )
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2)
        ])
        a1 = _completed_assignment(ctx, tech["id"], "09:00", "10:00")
        a2 = _completed_assignment(ctx, tech["id"], "10:00", "11:00")
        submit_daily_report(ctx["project"]["id"], tech["id"], "2026-05-04",
                            [a1["id"]], summary="morning shift")

        resp = api.create_daily_report(
            {
                "project_id": ctx["project"]["id"],
                "report_date": "2026-05-04",
                "assignment_ids": [a2["id"]],
                "summary": "afternoon shift",
            },
            make_technician_headers(tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DAILY_REPORT)

    def test_report_date_must_match_assignment_work_date(self, api):
        """PRD §3.7: "Every cited assignment must be `COMPLETED`, must belong
        to this technician and this project, must have a `work_date` equal to
        the `report_date`, and must not already be covered by another report —
        a citation violating any of these is rejected with
        `ERR_REFERENCE_MISMATCH`."

        Design: Corner/validations/dir_assignment_work_date_mismatch_rejected
        """
        ctx = setup_approved_project(
            [soil_scope_item()],
            project_overrides={"name": "DIRMismatch", "permit_number": "P-VAL-3"},
        )
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2)
        ])
        a1 = _completed_assignment(ctx, tech["id"], "09:00", "10:00")

        resp = api.create_daily_report(
            {
                "project_id": ctx["project"]["id"],
                "report_date": "2026-05-05",
                "assignment_ids": [a1["id"]],
                "summary": "wrong date",
            },
            make_technician_headers(tech["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_MISMATCH)

    def test_second_acknowledge_rejected(self, api):
        """PRD §3.7: "Receipt closes when the `BuildingOfficial` acknowledges
        the report, moving it `SUBMITTED → ACKNOWLEDGED` and recording
        `acknowledged_by`; acknowledging an already-acknowledged report is a
        state error."

        Design: Corner/state_machines/acknowledge_daily_report_twice_rejected
        """
        ctx = setup_ready_for_letter(
            project_overrides={"name": "Ack", "permit_number": "P-SM-9"}
        )
        report_id = ctx["daily_report"]["id"]
        acknowledged = validate_success(
            api.acknowledge_daily_report(report_id, BUILDING_OFFICIAL), 200
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["acknowledged_by"] == BUILDING_OFFICIAL["X-User-ID"]

        resp = api.acknowledge_daily_report(report_id, BUILDING_OFFICIAL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDiscrepancyCycle:
    def _setup_ticket(self, api):
        ctx = setup_approved_project(
            [weld_scope_item(description="moment frames")],
            project_overrides={"name": "Discrep", "permit_number": "P-DISC-1"},
        )
        tech = create_technician(certifications=[
            certification_entry("WELD_VISUAL", level=2)
        ])
        ticket = raise_discrepancy(
            ctx["project"]["id"], tech["id"], routed_to="CONTRACTOR",
            subject="embed plate mismatch",
            description="drawings show 4 studs, field has 3",
        )
        return ctx, tech, ticket

    def test_rejected_response_reopens_ticket_with_incremented_round(self, api):
        """PRD §3.8: "A response stores `response_text` and moves the ticket
        `RAISED → RESPONSE_SUBMITTED`. Resolution returns to the technician,
        who decides with an `outcome`: `ACCEPT` moves the ticket to `RESOLVED`
        — terminal — and recomputes posture as the open-discrepancy gate
        clears, while `REJECT` sends it back to `RAISED`, increments
        `round_count` by one, and clears `response_text` for another
        negotiation round."

        Design: Difficulty/non_linear_state_machine/discrepancy_response_reject_cycle
        """
        _ctx, tech, ticket = self._setup_ticket(api)
        assert ticket["status"] == "RAISED"
        assert ticket["round_count"] == 1

        responded = respond_to_discrepancy(ticket["id"], "will field-verify", CONTRACTOR)
        assert responded["status"] == "RESPONSE_SUBMITTED"

        rejected = validate_success(
            api.resolve_discrepancy(
                ticket["id"], {"outcome": "REJECT"}, make_technician_headers(tech["id"])
            ),
            200,
        )
        assert rejected["status"] == "RAISED", "rejection cycles the ticket back to RAISED"
        assert rejected["round_count"] == 2
        assert rejected["response_text"] is None, "the rejected response is cleared"

    def test_accepted_response_resolves_without_round_increment(self, api):
        """PRD §3.8: "Resolution returns to the technician, who decides with an
        `outcome`: `ACCEPT` moves the ticket to `RESOLVED` — terminal — and
        recomputes posture as the open-discrepancy gate clears, while `REJECT`
        sends it back to `RAISED`, increments `round_count` by one, and clears
        `response_text` for another negotiation round."

        Design: Difficulty/non_linear_state_machine/discrepancy_response_reject_cycle
        """
        _ctx, tech, ticket = self._setup_ticket(api)
        respond_to_discrepancy(ticket["id"], "will field-verify", CONTRACTOR)
        validate_success(
            api.resolve_discrepancy(
                ticket["id"], {"outcome": "REJECT"}, make_technician_headers(tech["id"])
            ),
            200,
        )
        respond_to_discrepancy(ticket["id"], "RFI answered, 3 studs per sketch SK-7", CONTRACTOR)
        resolved = validate_success(
            api.resolve_discrepancy(
                ticket["id"], {"outcome": "ACCEPT"}, make_technician_headers(tech["id"])
            ),
            200,
        )
        assert resolved["status"] == "RESOLVED"
        assert resolved["round_count"] == 2, "ACCEPT does not increment the round counter"

    def test_response_from_unrouted_party_rejected(self, api):
        """PRD §3.8: "Only the routed party may respond: a ticket routed to
        `CONTRACTOR` is answered by a `Contractor`, one routed to `ENGINEER` by
        the `EngineerOfRecord`, and any other role attempting to respond is
        rejected with `ERR_DISCREPANCY_ROUTING`."

        Design: Corner/rbac/discrepancy_respond_wrong_party_rejected
        """
        ctx = setup_approved_project(
            [weld_scope_item(description="frames")],
            project_overrides={"name": "Routing", "permit_number": "P-RBAC-5"},
        )
        tech = create_technician(certifications=[
            certification_entry("WELD_VISUAL", level=2)
        ])
        ticket = raise_discrepancy(
            ctx["project"]["id"], tech["id"], routed_to="CONTRACTOR",
            subject="embed mismatch", description="3 studs vs 4 per drawing",
        )
        wrong_party = api.respond_discrepancy(
            ticket["id"], {"response_text": "engineer weighs in uninvited"}, ENGINEER
        )
        validate_error(wrong_party, ApiErrorId.ERR_DISCREPANCY_ROUTING)
        assert wrong_party.status_code == 403

        responded = respond_to_discrepancy(ticket["id"], "contractor answer", CONTRACTOR)
        assert responded["status"] == "RESPONSE_SUBMITTED"

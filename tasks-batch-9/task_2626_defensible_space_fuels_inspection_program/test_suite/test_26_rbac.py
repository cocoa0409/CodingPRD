"""Role membership, ownership scoping and the separation of duties."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import (
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    add_zones,
    assert_2dp,
    assert_end_of_day,
    assert_hours,
    assert_notice_schedule,
    assert_posture,
    complete_inspection,
    complete_inspection_payload,
    complete_work_payload,
    create_inspector,
    create_parcel,
    get_contractor,
    get_inspection,
    get_notice,
    get_order,
    get_parcel,
    list_parcels,
    notice_for_parcel,
    open_certificate,
    open_cycle,
    parcel_payload,
    reason_payload,
    schedule_inspection,
    serve_notice,
    verify_completion,
    verify_completion_payload,
    work_complete_world,
)
from test_helpers.test_users import (
    FIRE_MARSHAL_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    TITLE_AGENT_HEADERS,
    make_inspector_headers,
    make_property_owner_headers,
)


def _two_cited_parcels(client):
    """Two parcels in one cycle, each carrying its own ISSUED citation.

    The single inspector takes the two visits on consecutive days so that the
    half-open occupation rule is never engaged.
    """
    cycle = open_cycle(client)
    inspector = create_inspector(client)
    cited = []
    for day in ("2026-08-20", "2026-08-21"):
        parcel = create_parcel(client)
        inspection = schedule_inspection(
            client,
            parcel["id"],
            cycle["id"],
            inspector["id"],
            scheduled_start_utc="%sT09:00:00Z" % day,
            scheduled_end_utc="%sT11:00:00Z" % day,
        )
        inspection = serve_notice(client, inspection["id"])
        add_zones(client, inspection["id"], inspector["id"])
        complete_inspection(client, inspection["id"], inspector["id"], "FAIL")
        cited.append(
            {
                "parcel": get_parcel(client, parcel["id"]),
                "notice": notice_for_parcel(client, parcel["id"]),
            }
        )
    return cited


class TestRoleMembershipPrecedesExistence:
    """A role absent from the endpoint's list never reaches the row."""

    def test_five_role_exclusive_writes_are_refused_before_anything_is_looked_up(
        self, client
    ):
        """Each exclusive verb refuses the wrong role with 403, and four of the five
        refusals name ids that do not exist at all.

        PRD: "A syntactically valid role that is simply not permitted to invoke the
        requested operation is a different failure and is rejected with
        ERR_FORBIDDEN_ROLE (HTTP 403)."

        PRD: "Role membership - the acting role appears in the target endpoint's
        authorized-role list in section 4. Applies to every endpoint. Failure:
        ERR_FORBIDDEN_ROLE (403)."

        PRD: "TitleAgent is an insurer, lender or escrow agent that is read-only apart
        from opening a certificate request."

        PRD: "FireMarshal is the statutory abatement authority - it adjudicates
        community certification, voids notices, authorizes abatement, awards and cancels
        orders - and deliberately cannot schedule, notice, complete or verify
        inspections."

        Design: Corner/rbac/title_agent_cannot_perform_program_admin_exclusive_writes
        """
        # Parcel creation lists only ProgramAdmin.
        validate_error(
            client.create_parcel(parcel_payload("APN-6201"), headers=TITLE_AGENT_HEADERS),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        _rows, meta = list_parcels(client)
        assert meta["total_count"] == 0, "the refused create wrote nothing"

        # Voiding is the fire marshal's alone, and 403 arrives before the 404.
        validate_error(
            client.void_notice(
                NON_EXISTENT_UUID,
                reason_payload("Issued in error"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        # Completion is the assigned inspector's alone.
        validate_error(
            client.complete_inspection(
                NON_EXISTENT_UUID,
                headers=FIRE_MARSHAL_HEADERS,
                payload=complete_inspection_payload("PASS"),
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        # Certification submission belongs to the community organizer.
        validate_error(
            client.submit_certification(
                NON_EXISTENT_UUID,
                headers=PROGRAM_ADMIN_HEADERS,
                payload={"parcels_outreached_count": 5},
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        # Reporting finished work belongs to the awarded contractor.
        validate_error(
            client.complete_work(
                NON_EXISTENT_UUID,
                complete_work_payload(),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )


class TestEveryRolePerformsItsOwnWork:
    """The positive half of the matrix: nobody is over-restricted."""

    def test_admin_inspector_owner_agent_and_marshal_each_reach_their_own_verbs(
        self, client
    ):
        """One enforcement chain touches five roles, and every call in it succeeds.

        PRD: "A ProgramAdmin serves the owner notice by declaring the notice_method
        used - IN_PERSON, CERTIFIED_MAIL or EMAIL - which advances the inspection
        SCHEDULED -> NOTICED and stamps notice_sent_at_utc with the logical clock."

        PRD: "Either a ProgramAdmin or the cited PropertyOwner may request the
        district's single permitted extension by supplying a reason; when the requester
        is the owner, X-User-ID must equal the notice's parcel_id."

        PRD: "A granted extension moves the notice ISSUED -> EXTENDED, adds 30 whole
        days to deadline_utc while preserving the 23:59:59 UTC end-of-day form, and
        increments extension_count by 1."

        PRD: "A FireMarshal who concludes a notice was issued in error voids it with a
        reason, which is recorded as void_reason."

        PRD: "the parcel's open_violation_count drops by 1 and its compliance_status is
        recomputed - restored to COMPLIANT when the count has reached 0 and the parcel
        has a passing inspection on record, and set back to PENDING_INSPECTION when the
        count has reached 0 but no passing inspection exists - with both the notice's and
        the parcel's version advancing by 1."

        Design: Corner/rbac/each_role_performs_its_own_declared_operations
        """
        cycle = open_cycle(client)
        inspector = create_inspector(client)
        parcel = create_parcel(client)

        # ProgramAdmin schedules and notices.
        inspection = schedule_inspection(
            client, parcel["id"], cycle["id"], inspector["id"]
        )
        inspection = serve_notice(client, inspection["id"])
        assert inspection["status"] == "NOTICED"

        # The assigned Inspector measures and closes out.
        add_zones(client, inspection["id"], inspector["id"])
        completed = complete_inspection(
            client, inspection["id"], inspector["id"], "FAIL"
        )
        assert completed["result"] == "FAIL"
        notice = notice_for_parcel(client, parcel["id"])
        assert_notice_schedule(
            notice, "MAJOR", "2026-08-06T00:00:00Z", 30, "2026-09-05", status="ISSUED"
        )

        # The cited PropertyOwner extends its own deadline.
        owner = make_property_owner_headers(parcel["id"])
        extended = validate_success(
            client.extend_notice(
                notice["id"],
                headers=owner,
                payload=reason_payload("Contractor booked for October"),
            )
        )
        assert extended["status"] == "EXTENDED"
        assert extended["extension_count"] == 1
        assert_end_of_day(extended["deadline_utc"], "2026-10-05")

        # Both the owner and the title agent may open a certificate request.
        owner_request = open_certificate(client, parcel["id"], headers=owner)
        agent_request = open_certificate(
            client, parcel["id"], headers=TITLE_AGENT_HEADERS, requester_kind="LENDER"
        )
        assert owner_request["id"] != agent_request["id"]
        assert owner_request["status"] == "REQUESTED"
        assert agent_request["status"] == "REQUESTED"

        # The FireMarshal voids the citation.
        voided = validate_success(
            client.void_notice(
                notice["id"],
                reason_payload("Issued against the wrong structure"),
                headers=FIRE_MARSHAL_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "Issued against the wrong structure"
        # No passing inspection exists, so the posture falls back to PENDING_INSPECTION.
        assert_posture(
            get_parcel(client, parcel["id"]),
            "PENDING_INSPECTION",
            open_violation_count=0,
        )


class TestOwnershipScoping:
    """A permitted role still has to own the row it reaches for."""

    def test_one_owner_cannot_extend_the_neighbours_deadline(self, client):
        """Owner B is refused with ERR_NOT_RESOURCE_OWNER rather than
        ERR_FORBIDDEN_ROLE, and owner A's identical request is granted.

        PRD: "A caller whose role is permitted on the endpoint but whose X-User-ID does
        not match the resource it is reaching for is rejected with
        ERR_NOT_RESOURCE_OWNER (HTTP 403)."

        PRD: "This check guards twelve operations: recording an access denial, recording
        a zone evaluation, recording a hardening finding, completing an inspection,
        extending a violation notice, reporting completed abatement work, recording a
        cost-recovery payment, creating a support enrollment, cancelling a support
        enrollment, opening a compliance-certificate request on a parcel, submitting a
        community certification, and reopening a community for organizing."

        PRD: "When X-User-Role is PropertyOwner, X-User-ID is the id of the acting
        Parcel; ownership checks compare the resource's parcel_id to X-User-ID, either
        directly or transitively (a violation notice's parcel_id, a support enrollment's
        parcel_id, or - for an abatement order - the parcel_id of the violation notice
        the order was raised under)."

        PRD: "Where it went by certified mail, the district takes constructive service
        to occur five days after issuance, so delivered_at_utc is issued_at_utc plus 5
        days."

        Design: Corner/rbac/property_owner_cannot_extend_another_parcels_notice
        """
        first, second = _two_cited_parcels(client)
        notice = first["notice"]
        assert_notice_schedule(
            notice, "MAJOR", "2026-08-06T00:00:00Z", 30, "2026-09-05", status="ISSUED"
        )
        assert notice["extension_count"] == 0

        # The role is listed on this endpoint, so the failure is ownership.
        validate_error(
            client.extend_notice(
                notice["id"],
                headers=make_property_owner_headers(second["parcel"]["id"]),
                payload=reason_payload("Neighbour requests more time"),
            ),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )
        held = get_notice(client, notice["id"])
        assert held["status"] == "ISSUED"
        assert held["extension_count"] == 0
        assert_end_of_day(held["deadline_utc"], "2026-09-05")

        granted = validate_success(
            client.extend_notice(
                notice["id"],
                headers=make_property_owner_headers(first["parcel"]["id"]),
                payload=reason_payload("Neighbour requests more time"),
            )
        )
        assert granted["status"] == "EXTENDED"
        assert granted["extension_count"] == 1
        assert_end_of_day(granted["deadline_utc"], "2026-10-05")
        assert get_notice(client, second["notice"]["id"])["status"] == "ISSUED"


class TestSeparationOfDuties:
    """The officer who found the violation cannot sign off on the remedy."""

    def test_the_citing_inspector_is_barred_and_a_second_inspector_is_not(self, client):
        """Self-verification answers ERR_SEGREGATION_OF_DUTIES and leaves the whole
        invoicing cascade unrun; a second inspector invoices the same order.

        PRD: "And the acting inspector's X-User-ID must differ from the inspector_id
        recorded on the inspection that substantiated this order's violation notice - the
        district will not let the officer who found the violation also sign off on the
        paid remedy."

        PRD: "Self-verification is refused with ERR_SEGREGATION_OF_DUTIES."

        PRD: "Because the order became invoiced, the reservation finally unwinds: the
        contractor's committed_crew_hours decreases by the order's crew_hours and its
        completed_crew_hours increases by the order's actual_crew_hours, restoring the
        conservation identity of section 2.10."

        PRD: "Segregation of duties - the inspector verifying an abatement order's
        completion must not be the inspector recorded on the inspection that
        substantiated that order's violation notice. Applies to abatement verification.
        Failure: ERR_SEGREGATION_OF_DUTIES (403)."

        Design: Corner/rbac/same_inspector_cannot_verify_own_inspection_abatement
        """
        world = work_complete_world(client)
        order = world["order"]
        assert order["status"] == "WORK_COMPLETE"
        assert order["verified_by_inspector_id"] is None
        citing_inspector = world["inspector"]
        assert (
            get_inspection(client, world["inspection"]["id"])["inspector_id"]
            == citing_inspector["id"]
        )

        validate_error(
            client.verify_completion(
                order["id"],
                headers=make_inspector_headers(citing_inspector["id"]),
                payload=verify_completion_payload("Self-verified"),
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        held = get_order(client, order["id"])
        assert held["status"] == "WORK_COMPLETE"
        assert held["total_recoverable_cents"] is None
        assert held["invoice_due_utc"] is None
        assert held["verified_by_inspector_id"] is None
        contractor = get_contractor(client, world["contractor"]["id"])
        assert_hours(contractor["committed_crew_hours"], 12.5)
        assert_hours(contractor["completed_crew_hours"], 0)
        assert get_notice(client, world["notice"]["id"])["status"] == (
            "ABATEMENT_AUTHORIZED"
        )
        assert_posture(get_parcel(client, world["parcel"]["id"]), "ABATEMENT_PENDING")

        second_inspector = create_inspector(client)
        invoiced = verify_completion(client, order["id"], second_inspector["id"])
        assert invoiced["status"] == "INVOICED"
        assert invoiced["verified_by_inspector_id"] == second_inspector["id"]
        assert_2dp(invoiced["total_recoverable_cents"], 152461)

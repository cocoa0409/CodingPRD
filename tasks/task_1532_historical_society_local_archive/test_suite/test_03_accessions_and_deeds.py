"""Accession intake, the deed-of-gift cycle, OCC on accession version, and
terminal-state lockdowns across accession/deed/appointment machines."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_accession,
    assert_deed,
    catalog_item,
    create_accession,
    create_accessioned,
    create_appointment,
    create_collection,
    create_deed,
    create_item,
    create_published_finding_aid,
    create_zone,
    execute_deed,
    get_accession,
    make_item_available,
    make_researcher_headers,
    set_clock,
    setup_approved_request,
    submit_accession,
    validate_error,
    validate_paginated,
    validate_success,
)

REG = {"X-User-ID": "reg-1", "X-User-Role": "Registrar", "Content-Type": "application/json"}
ARCH = {"X-User-ID": "arch-1", "X-User-Role": "Archivist", "Content-Type": "application/json"}
RRS = {"X-User-ID": "rrs-1", "X-User-Role": "ReadingRoomStaff", "Content-Type": "application/json"}


class TestAccessionHappyPath:

    def test_accession_happy_path_and_numbering(self):
        """PRD §3.1: "At creation the accession enters `DRAFT` status and is
        assigned its `accession_number`: the four-digit year of its
        `created_at`, a hyphen, and the 1-based count of accessions created in
        that calendar year, zero-padded to three digits."
        PRD §3.1: "Submitting moves the accession `DRAFT → PENDING_DEED` and
        increments its `version` by 1."
        PRD §3.1: "On execution the deed becomes `EXECUTED`; the accession's
        `version` increments by 1; the previously `EXECUTED` deed for the
        accession, if any, becomes `SUPERSEDED`; the accession moves from
        `PENDING_DEED` to `ACCESSIONED` or from `AMENDMENT_PENDING` back to
        `ACCESSIONED`; and the accession's `current_deed_id` is updated to the
        newly executed deed."

        Design: Corner/state_machines/accession_happy_path_and_numbering
        """
        created = validate_success(
            api_client.create_accession(
                {"donor_name": "E. Stone", "donor_contact": "s@example.org",
                 "accession_date": "2026-07-15", "lot_appraised_value_cents": 1000},
                REG),
            expected_status=201)
        assert_accession(created)
        assert created["status"] == "DRAFT"
        assert created["accession_number"] == "2026-001"
        assert created["current_deed_id"] is None

        submitted = validate_success(
            api_client.submit_accession(created["id"], REG))
        assert submitted["status"] == "PENDING_DEED"
        assert submitted["version"] == created["version"] + 1

        deed = validate_success(
            api_client.create_deed(
                created["id"],
                {"required_citation_text":
                 "Courtesy of the County Historical Society"},
                REG),
            expected_status=201)
        assert_deed(deed)
        assert deed["status"] == "DRAFT"
        assert deed["deed_version"] == 1

        current = get_accession(created["id"])
        executed = validate_success(api_client.execute_deed(
            deed["id"], {"expected_accession_version": current["version"]}, REG))
        assert executed["status"] == "EXECUTED"

        after = get_accession(created["id"])
        assert after["status"] == "ACCESSIONED"
        assert after["current_deed_id"] == deed["id"]


class TestAmendmentCycle:

    def test_accession_amendment_cycle_supersedes_deed(self):
        """PRD §3.1: "Once the accession is `ACCESSIONED`, the registrar may open
        an amendment cycle: amending moves the accession `ACCESSIONED →
        AMENDMENT_PENDING`, again incrementing its `version` by 1, and a newly
        executed deed closes the loop back to `ACCESSIONED`."
        PRD §3.2: "The accession must be `ACCESSIONED`
        (`ERR_ACCESSION_NOT_ACCESSIONED`) and the collection must be `ACTIVE`
        (`ERR_INVALID_STATE`)."
        PRD §3.1: "Each deed is assigned a `deed_version` at creation — the
        1-based count of deeds created for that accession up to and including
        this one."
        PRD §3.1: "the previously `EXECUTED` deed for the accession, if any,
        becomes `SUPERSEDED`"

        Design: Corner/state_machines/accession_amendment_cycle_supersedes_deed
        """
        accession, deed1 = create_accessioned(
            deed_fields={"required_citation_text": "Citation A"})
        assert accession["status"] == "ACCESSIONED"
        zone = create_zone()
        collection = create_collection(zone["id"])

        amended = validate_success(api_client.amend_accession(accession["id"], REG))
        assert amended["status"] == "AMENDMENT_PENDING"
        assert amended["version"] == accession["version"] + 1

        # Item creation is gated on ACCESSIONED — AMENDMENT_PENDING fails.
        resp = api_client.create_item(
            {"accession_id": accession["id"], "collection_id": collection["id"],
             "title": "I1"}, ARCH)
        validate_error(resp, ApiErrorId.ERR_ACCESSION_NOT_ACCESSIONED)

        deed2 = validate_success(
            api_client.create_deed(accession["id"],
                                   {"required_citation_text": "Citation B"}, REG),
            expected_status=201)
        assert deed2["deed_version"] == 2

        current = get_accession(accession["id"])
        execute_deed(deed2["id"], current["version"])

        after = get_accession(accession["id"])
        assert after["status"] == "ACCESSIONED"
        assert after["current_deed_id"] == deed2["id"]

        deeds, _meta = validate_paginated(
            api_client.list_deeds(accession["id"], REG))
        by_id = {d["id"]: d for d in deeds}
        assert by_id[deed1["id"]]["status"] == "SUPERSEDED"
        assert by_id[deed2["id"]]["status"] == "EXECUTED"
        executed_deeds = [d for d in deeds if d["status"] == "EXECUTED"]
        assert len(executed_deeds) == 1, (
            "exactly one EXECUTED deed per accession at all times")


class TestTerminalStateLockdowns:

    def test_terminal_state_lockdowns(self):
        """PRD §3.1: "The deed itself must be `DRAFT`, else `ERR_INVALID_STATE`."
        PRD §3.6: "The owner may instead cancel outright — cancellation is
        permitted from `CONFIRMED` or `NEEDS_RESCHEDULE` by the owning
        researcher (`ERR_OWNERSHIP_MISMATCH` otherwise) — which releases the
        reserved seats for the interval."
        PRD §3.1: "Before any deed has executed, the registrar may withdraw the
        accession — withdrawal is permitted from either `DRAFT` or
        `PENDING_DEED`, lands in the terminal `WITHDRAWN` state, and voids every
        deed still in `DRAFT` for that accession (each such deed becomes
        `VOIDED`)."
        PRD §3.6: "optionally `seats` (defaulting to 1 and never less than 1)"

        Design: Corner/state_machines/terminal_state_lockdowns
        """
        accession = create_accession()
        submit_accession(accession["id"])
        deed1 = create_deed(accession["id"])
        deed2 = create_deed(accession["id"])
        voided = validate_success(api_client.void_deed(deed2["id"], REG))
        assert voided["status"] == "VOIDED"
        current = get_accession(accession["id"])
        execute_deed(deed1["id"], current["version"])

        ctx_zone = create_zone()
        collection = create_collection(ctx_zone["id"])
        create_published_finding_aid(collection["id"])
        item = create_item(accession["id"], collection["id"], title="I1")
        catalog_item(item["id"])
        make_item_available(item["id"])

        researcher, request = setup_approved_request([item["id"]])
        appointment = create_appointment(
            request["id"], researcher["id"], room_code="MAP_ROOM",
            scheduled_date="2026-08-10", start_time="10:00", end_time="11:00")
        assert appointment["seats"] == 1, "omitted seats defaults to 1"
        validate_success(api_client.check_in_appointment(appointment["id"], RRS))
        completed = validate_success(
            api_client.complete_appointment(appointment["id"], RRS))
        assert completed["status"] == "COMPLETED"

        # A VOIDED deed cannot execute. The accession version is refetched so
        # only the state violation is in play.
        fresh_version = get_accession(accession["id"])["version"]
        resp1 = api_client.execute_deed(
            deed2["id"], {"expected_accession_version": fresh_version}, REG)
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)

        # A COMPLETED appointment cannot be cancelled.
        resp2 = api_client.cancel_appointment(
            appointment["id"], make_researcher_headers(researcher["id"]))
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)

        # An ACCESSIONED accession cannot be withdrawn.
        resp3 = api_client.withdraw_accession(accession["id"], REG)
        validate_error(resp3, ApiErrorId.ERR_INVALID_STATE)


class TestInvalidFromTransitions:

    def test_invalid_from_transitions_rejected(self):
        """PRD §3.3: "Publication moves `IN_REVIEW → PUBLISHED`:
        `published_revision_count` increases by 1, `published_at` records the
        logical timestamp of the publish, and the collection's
        `published_finding_aid_present` is recomputed — becoming true upon the
        first publication."
        PRD §3.6: "the appointment must be `CONFIRMED` (`ERR_INVALID_STATE`
        otherwise), and the logical clock must have reached or passed the
        appointment's end datetime — its `scheduled_date` at `end_time`, UTC —
        else `ERR_APPOINTMENT_NOT_ENDED`."
        PRD §2.8: "5. **Target state** — the target resource's own state machine
        permits the operation, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/invalid_from_transitions_rejected
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        aid = validate_success(
            api_client.create_finding_aid(
                {"collection_id": collection["id"], "title": "FA",
                 "summary": "S"}, ARCH),
            expected_status=201)
        # PRD §3.2 gates make-available on a PUBLISHED finding aid; publish a
        # second aid so the gate is satisfied while `aid` stays DRAFT for the
        # publish-from-DRAFT assertion below.
        create_published_finding_aid(collection["id"])

        accession, _deed = create_accessioned()
        item = create_item(accession["id"], collection["id"], title="I1")
        proposal = validate_success(
            api_client.create_deaccession_proposal(
                {"item_ids": [item["id"]], "justification": "dup",
                 "disposal_method": "DESTRUCTION"}, REG),
            expected_status=201)
        catalog_item(item["id"])
        make_item_available(item["id"])

        researcher, request = setup_approved_request([item["id"]])
        appointment = create_appointment(
            request["id"], researcher["id"], scheduled_date="2026-08-02",
            start_time="10:00", end_time="11:00")
        set_clock("2026-08-02T12:00:00Z")
        no_show = validate_success(
            api_client.record_no_show(appointment["id"], RRS))
        assert no_show["status"] == "NO_SHOW"

        # Publish a DRAFT finding aid (never submitted for review).
        resp1 = api_client.publish_finding_aid(aid["id"], ARCH)
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)

        # Record-no-show is not idempotent: the appointment is already NO_SHOW.
        resp2 = api_client.record_no_show(appointment["id"], RRS)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)

        # Board approve from DRAFT (submit/send-to-board skipped).
        resp3 = api_client.approve_proposal(
            proposal["id"],
            {"X-User-ID": "board_1", "X-User-Role": "BoardOfficer",
             "Content-Type": "application/json"})
        validate_error(resp3, ApiErrorId.ERR_INVALID_STATE)


class TestDeedExecuteOCC:

    def test_occ_deed_execute_stale_version_rejected(self):
        """PRD §2.7: "Executing a deed of gift — `POST /deeds/{id}/execute` —
        requires the request body to carry `expected_accession_version`, a
        non-optional field holding the caller's last-observed `version` of the
        owning accession. If the accession's current `version` does not match,
        the execution is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_deed_execute_stale_version
        """
        accession, deed1 = create_accessioned(
            deed_fields={"required_citation_text": "A"})
        deed2 = create_deed(accession["id"], required_citation_text="B")
        deed3 = create_deed(accession["id"], required_citation_text="C")
        stale = get_accession(accession["id"])["version"]

        executed2 = execute_deed(deed2["id"], stale)
        assert executed2["status"] == "EXECUTED"

        # The version captured before D2's execution is now stale.
        resp = api_client.execute_deed(
            deed3["id"], {"expected_accession_version": stale}, REG)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

        deeds, _ = validate_paginated(
            api_client.list_deeds(accession["id"], REG))
        by_id = {d["id"]: d for d in deeds}
        assert by_id[deed3["id"]]["status"] == "DRAFT", (
            "the stale execute must not transition the deed")

    def test_occ_deed_execute_refetch_retry_supersedes(self):
        """PRD §2.7: "Executing one deed legitimately supersedes the previously
        executed deed, so a second execution carrying a stale expectation cannot
        be rejected from state alone; the stale-version check is what rejects
        it."
        PRD §3.1: "the previously `EXECUTED` deed for the accession, if any,
        becomes `SUPERSEDED`; the accession moves from `PENDING_DEED` to
        `ACCESSIONED` or from `AMENDMENT_PENDING` back to `ACCESSIONED`; and the
        accession's `current_deed_id` is updated to the newly executed deed."

        Design: Corner/complexity_layers/occ_deed_execute_stale_version
        """
        accession, deed1 = create_accessioned(
            deed_fields={"required_citation_text": "A"})
        deed2 = create_deed(accession["id"], required_citation_text="B")
        deed3 = create_deed(accession["id"], required_citation_text="C")
        stale = get_accession(accession["id"])["version"]

        execute_deed(deed2["id"], stale)
        after_d2 = get_accession(accession["id"])
        assert after_d2["version"] == stale + 1
        assert after_d2["current_deed_id"] == deed2["id"]

        # Retry D3 with the refetched version: supersedes D2.
        executed3 = execute_deed(deed3["id"], after_d2["version"])
        assert executed3["status"] == "EXECUTED"

        deeds, _ = validate_paginated(
            api_client.list_deeds(accession["id"], REG))
        by_id = {d["id"]: d for d in deeds}
        assert by_id[deed1["id"]]["status"] == "SUPERSEDED"
        assert by_id[deed2["id"]]["status"] == "SUPERSEDED"
        assert by_id[deed3["id"]]["status"] == "EXECUTED"
        final = get_accession(accession["id"])
        assert final["current_deed_id"] == deed3["id"]

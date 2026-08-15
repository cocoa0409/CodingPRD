"""Trip events, request close (CANCEL / SUPERSEDE), and completion side effects."""
from test_helpers import (
    DISP,
    ApiErrorId,
    accept_offer,
    add_on_shift_transporter,
    close_request,
    create_dispatch_offer,
    create_location,
    create_offer_payload,
    create_transport_request,
    create_travel_edge,
    get_transporter,
    make_clinician_headers,
    post_trip_event,
    setup_assigned_trip,
    setup_completed_trip,
    setup_transport_site,
    validate_error,
    validate_success,
)


class TestTripEventStateMachine:
    def test_complete_from_assigned_returns_409(self, api):
        """PRD §3.5: "`COMPLETE` moves the request from `IN_TRANSIT` to
        `COMPLETED`"
        PRD §2.6: "the target resource is in a status that permits the
        operation; requests already in a terminal state answer
        `ERR_ALREADY_TERMINAL`, other state violations answer the appropriate
        `ERR_INVALID_*_STATE` error."

        Design: Corner/state_machines/complete_from_assigned_returns_409
        """
        world = setup_assigned_trip(equipment="WHEELCHAIR", patient_ref="P1")
        t1, r1 = world["transporter"], world["request"]

        resp = post_trip_event(r1["id"], "COMPLETE", transporter_id=t1["id"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST_STATE)


class TestCloseRequest:
    def test_cancel_completed_returns_409(self, api):
        """PRD §3.5: "From a terminal state it is rejected with
        `ERR_ALREADY_TERMINAL`; from `IN_TRANSIT` it is rejected with
        `ERR_INVALID_REQUEST_STATE`; from `QUEUED`, `ASSIGNED`, or `AT_PICKUP`
        it proceeds"

        Design: Corner/state_machines/cancel_completed_returns_409
        """
        world = setup_completed_trip(equipment="PORTER_ONLY", patient_ref="P1")
        r1 = world["request"]

        resp = close_request(r1["id"], "CANCEL", DISP, reason="TOO_LATE")
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_supersede_assigned_request_returns_409(self, api):
        """PRD §3.5: "The request must be `QUEUED` — a terminal request answers
        `ERR_ALREADY_TERMINAL`, any other state `ERR_INVALID_REQUEST_STATE`."

        Design: Corner/state_machines/supersede_assigned_request_returns_409
        """
        site = setup_transport_site()
        w5 = create_location("W5", "Ward 5", "WARD", "Z1")
        t1 = add_on_shift_transporter("T One", site["hub"]["id"])
        r2 = create_transport_request("PX", site["ward"]["id"], w5["id"],
                                      priority="ROUTINE",
                                      required_equipment="PORTER_ONLY")
        r1 = create_transport_request("PX", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="PORTER_ONLY")
        offer = create_dispatch_offer(r1, transporter_id=t1["id"])
        accept_offer(offer["id"], t1["id"])

        resp = close_request(r1["id"], "SUPERSEDE", DISP,
                             duplicate_of_id=r2["id"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST_STATE)

    def test_supersede_patient_mismatch_returns_409(self, api):
        """PRD §3.5: "The payload must include `duplicate_of_id` (its absence
        fails schema validation with `ERR_VALIDATION`), and the nominated
        original must exist (an unknown identifier answers `ERR_NOT_FOUND`),
        must not be the request itself, must still be `QUEUED`, and must carry
        the same `patient_ref`; a target that fails any of those conditions is
        rejected with `ERR_NOT_DUPLICATE`."

        Design: Corner/validations/supersede_patient_mismatch_returns_409
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        r1 = create_transport_request("PX", ward["id"], img["id"])
        r2 = create_transport_request("PY", ward["id"], img["id"])

        resp = close_request(r1["id"], "SUPERSEDE", DISP,
                             duplicate_of_id=r2["id"])
        validate_error(resp, ApiErrorId.ERR_NOT_DUPLICATE)

    def test_clinician_cannot_supersede_returns_403(self, api):
        """PRD §3.5: "Supersession is the dispatcher's duplicate-consolidation
        tool and is restricted to that role."
        PRD §2.1: "a `Transporter` may set only their own status and only to
        `ON_SHIFT` or `OFF_SHIFT`; suspension and reinstatement are
        `TransportSupervisor`-only; `HousekeepingStaff` may advance cleaning
        only to `IN_PROGRESS` or `AWAITING_VERIFICATION`; verification and
        rework belong to the supervisor; supersede-as-duplicate belongs to the
        dispatcher alone."

        Design: Corner/rbac/clinician_cannot_supersede_returns_403
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        w5 = create_location("W5", "Ward 5", "WARD", "Z1")
        r1 = create_transport_request("PX", ward["id"], img["id"])
        r2 = create_transport_request("PX", ward["id"], w5["id"])

        # The requester is the owner, but SUPERSEDE is dispatcher-only.
        resp = close_request(r1["id"], "SUPERSEDE",
                             make_clinician_headers("clin-1"),
                             duplicate_of_id=r2["id"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_clinician_cancel_foreign_request_returns_403(self, api):
        """PRD §3.5: "a `RequestingClinician` may cancel only their own
        requests, meaning `requested_by` must equal the caller's `X-User-ID`
        (otherwise `ERR_FORBIDDEN_ROLE`), and only while the request is still
        `QUEUED`, whereas dispatchers and supervisors may cancel any
        cancellable request."

        Design: Corner/rbac/clinician_cancel_foreign_request_returns_403
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        r1 = create_transport_request("P1", ward["id"], img["id"],
                                      clinician_id="clin-1")

        resp = close_request(r1["id"], "CANCEL",
                             make_clinician_headers("clin-2"),
                             reason="NOT_MINE_TEST")
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestCompletionSideEffects:
    def test_completion_frees_transporter_and_moves_location(self, api):
        """PRD §3.5: "`completed_at` is stamped and `assigned_transporter_id`
        cleared; the transporter's `current_location_id` is updated to the
        trip's destination"
        PRD §3.4: "The deadhead leg is zero minutes when the transporter is
        already at the pickup location — no edge required — and otherwise the
        `base_minutes` of the edge from the transporter's current location to
        the origin."

        Design: Corner/state_machines/completion_frees_transporter_and_moves_location
        """
        world = setup_completed_trip(equipment="PORTER_ONLY", patient_ref="P1")
        site, t1 = world["site"], world["transporter"]
        create_travel_edge(site["img"]["id"], site["ward"]["id"], 5, 8)

        moved = get_transporter(t1["id"])
        assert moved["current_location_id"] == site["img"]["id"], (
            "completion relocates the transporter to the trip destination")

        # Immediately eligible again: a new PORTER_ONLY trip IMG -> W4 gets an
        # offer with deadhead 0 (already at the origin) + ceil(5 x 1.0) = 5.
        r2 = create_transport_request("P2", site["img"]["id"],
                                      site["ward"]["id"], priority="ROUTINE",
                                      required_equipment="PORTER_ONLY")
        created = api.create_offer(r2["id"], create_offer_payload(
            r2["version"], transporter_id=t1["id"]), DISP)
        offer2 = validate_success(created, 201)
        assert offer2["estimated_travel_minutes"] == 5

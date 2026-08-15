"""Complaint pipeline: response window, segregation of duties, compensation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_steward,
    create_draft_box,
    create_steward_with_active_box,
    create_under_review_complaint,
    create_upheld_complaint,
    events_of_type,
    file_complaint,
    get_box,
    list_recognition_events,
    pin_clock,
    receive_allocation,
    resolve_complaint,
    setup_dispatched_run,
    triage_complaint,
    run_sweep,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]
MOD1 = TEST_USERS["mod1_headers"]
MOD2 = TEST_USERS["mod2_headers"]


class TestResponseWindow:
    def test_complaint_window_expiry_via_sweep_boundary(self, api):
        """PRD §3.6: "Triage starts the clock. A `Moderator` or `NetworkAdmin`
        triages a `FILED` complaint into `STEWARD_RESPONSE_PENDING`, which
        records the operator's identity as `triaged_by_user_id` and sets
        `response_due_at` exactly 72 hours after the triage instant."
        PRD §3.6: "Silence is not a deadlock: a map sweep that finds the
        response deadline reached advances the complaint to `UNDER_REVIEW`
        itself, leaving `response_text` null."
        PRD §3.9: "complaints sitting in `STEWARD_RESPONSE_PENDING` whose
        `response_due_at` has been reached move to `UNDER_REVIEW`".

        Design: Corner/state_machines/complaint_window_expiry_via_sweep_boundary
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Slow Responder", box_name="Ash Box"
        )
        complaint = file_complaint(box["id"], category="OTHER",
                                   description="Odd smell")
        triage_complaint(complaint["id"])  # triaged 2026-08-01T00:00:00Z

        # response_due_at == triage instant + 72h; the deadline is inclusive.
        pin_clock("2026-08-04T00:00:00Z")
        sweep = run_sweep()
        assert sweep["expired_response_count"] == 1

        after = validate_success(api.get_complaint(complaint["id"], MOD1), 200)
        assert after["status"] == "UNDER_REVIEW"
        assert after["response_text"] is None


class TestSegregationOfDuties:
    def test_complaint_resolve_segregation_triager_cannot_resolve(self, api):
        """PRD §3.6: "A `Moderator` or `NetworkAdmin` resolves an
        `UNDER_REVIEW` complaint with an `outcome` of `UPHELD` or `DISMISSED`
        and optional `resolution_notes`, but the resolver must not be the
        operator who triaged it — a match between the caller's identity and
        `triaged_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/complaint_resolve_segregation_triager_cannot_resolve
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Seg Owner", box_name="Seg Box"
        )
        complaint = create_under_review_complaint(
            box["id"], steward["id"], category="OTHER", description="Noise",
            triager_headers=MOD1,
        )

        # mod-1 triaged it; the same identity cannot resolve it.
        res = api.resolve_complaint(complaint["id"], {"outcome": "DISMISSED"},
                                    MOD1)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
                       expected_status=403)

        resolved = resolve_complaint(complaint["id"], "DISMISSED",
                                     headers=MOD2)
        assert resolved["status"] == "RESOLVED_DISMISSED"

    def test_complaint_adjudicate_segregation_excludes_triager_and_resolver(
        self, api
    ):
        """PRD §3.6: "Adjudication is final and again segregated: the
        adjudicating `NetworkAdmin` must differ from both the triager and the
        resolver, with any collision rejected as `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.6: "Both adjudicated states — `ADJUDICATED_UPHELD` and
        `ADJUDICATED_DISMISSED` — are terminal."

        Design: Corner/state_machines/complaint_adjudicate_segregation_excludes_triager_and_resolver
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Appeal Owner", box_name="Appeal Box"
        )
        # Triaged by mod-1, resolved DISMISSED by admin-1, escalated.
        complaint = create_under_review_complaint(
            box["id"], steward["id"], category="OTHER",
            description="Loose newspapers", triager_headers=MOD1,
        )
        resolve_complaint(complaint["id"], "DISMISSED", headers=ADMIN)
        get = validate_success(
            api.escalate_complaint(complaint["id"], ADMIN), 200
        )
        assert get["status"] == "ESCALATED"

        # admin-1 resolved it, so admin-1 cannot adjudicate.
        res = api.adjudicate_complaint(complaint["id"],
                                       {"outcome": "DISMISSED"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
                       expected_status=403)

        adjudicated = validate_success(
            api.adjudicate_complaint(complaint["id"], {"outcome": "DISMISSED"},
                                     ADMIN2),
            200,
        )
        assert adjudicated["status"] == "ADJUDICATED_DISMISSED"


class TestComplaintCompensation:
    def test_complaint_upheld_then_adjudicated_dismissed_compensates(self, api):
        """PRD §3.6: "Adjudicating `DISMISSED` sets the outcome and, when the
        complaint had been escalated from an upheld ruling, pays compensation:
        a `COMPLAINT_UPHELD` event worth +60 offsets the earlier penalty, the
        strike count recomputes downward as the complaint leaves the upheld
        set, every book quarantined by this complaint returns from
        `QUARANTINED` to `PLACED` keeping its `box_id` and leaving stock
        untouched, and the box's posture recalculates."
        PRD §3.6: "Escalation out of an upheld ruling immediately relieves the
        box: the complaint stops counting toward `upheld_complaints_90d` on
        entry to `ESCALATED`, and the posture recomputes."

        Design: Corner/state_machines/complaint_upheld_then_adjudicated_dismissed_compensates
        """
        pin_clock()
        # Steward (+25 ORIENTATION) with a box and one CHILDREN book PLACED.
        scenario = setup_dispatched_run(item_count=1, capacity_books=10)
        steward = scenario["steward"]
        box = scenario["box"]
        allocation = scenario["allocations"][0]
        item_id = allocation["book_item_id"]
        receive_allocation(allocation["id"], steward["id"])  # +5 placement

        # Complaint with target_category CHILDREN would only quarantine CHILDREN
        # books; the placed book here is FICTION, so use a matching category
        # scenario instead: re-file with the book's actual category.
        complaint = create_upheld_complaint(
            box["id"], steward["id"], category="INAPPROPRIATE_CONTENT",
            description="Bad book", target_category="FICTION",
            triager_headers=MOD1, resolver_headers=MOD2,
        )
        mid = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert mid["upheld_complaints_90d"] == 1
        quarantined = validate_success(api.get_book_item(item_id, ADMIN), 200)
        assert quarantined["status"] == "QUARANTINED"

        # Steward appeal: escalate, then a fresh admin adjudicates DISMISSED.
        validate_success(api.escalate_complaint(complaint["id"], ADMIN), 200)
        adjudicated = validate_success(
            api.adjudicate_complaint(complaint["id"], {"outcome": "DISMISSED"},
                                     ADMIN2),
            200,
        )
        assert adjudicated["status"] == "ADJUDICATED_DISMISSED"

        steward_after = validate_success(api.get_steward(steward["id"], ADMIN),
                                         200)
        assert steward_after["strike_count"] == 0
        # 25 orientation + 5 placement - 60 upheld + 60 compensating.
        assert steward_after["rolling_points"] == 30

        events = list_recognition_events(steward["id"])
        compensating = [
            e for e in events_of_type(events, "COMPLAINT_UPHELD")
            if e["points_delta"] == 60 and e["source_id"] == complaint["id"]
        ]
        assert len(compensating) == 1

        item_after = validate_success(api.get_book_item(item_id, ADMIN), 200)
        assert item_after["status"] == "PLACED"
        assert item_after["box_id"] == box["id"]

        box_after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert box_after["listing_posture"] == "LISTED"
        assert box_after["upheld_complaints_90d"] == 0


class TestRecognitionFloor:
    def test_recognition_floor_at_zero_after_complaint(self, api):
        """PRD §3.2: "Two running totals summarize a steward's standing, both
        derived deterministically from the recognition ledger and both floored
        independently at zero."
        PRD §3.2: "A steward's `strike_count` is the number of complaints
        currently standing in an upheld terminal status — `RESOLVED_UPHELD` or
        `ADJUDICATED_UPHELD` — against boxes owned by that steward."
        PRD §3.6: "An upheld ruling lands at `RESOLVED_UPHELD` and fires a
        heavier cascade: the outcome is set to `UPHELD`, `upheld_at` is
        stamped, the box's steward receives a `COMPLAINT_UPHELD` event worth
        −60 and their `strike_count` rises by one on recount."

        Design: Corner/calculations/recognition_floor_at_zero_after_complaint
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Floor Owner", box_name="Floor Box"
        )
        create_upheld_complaint(box["id"], steward["id"], category="OTHER",
                                description="Graffiti")

        after = validate_success(api.get_steward(steward["id"], ADMIN), 200)
        # max(0, 25 - 60) on both variants.
        assert after["rolling_points"] == 0
        assert after["lifetime_points"] == 0
        assert after["strike_count"] == 1
        assert after["recognition_tier"] == "NONE"

        box_after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert box_after["listing_posture"] == "FLAGGED"
        assert box_after["upheld_complaints_90d"] == 1


class TestPublicVisibilityGate:
    def test_complaint_and_report_rejected_for_non_public_box(self, api):
        """PRD §3.6: "Only boxes visible to the public may be complained about:
        the target must be `ACTIVE` or `SUSPENDED`, and any other charter state
        is rejected with `ERR_BOX_NOT_PUBLIC`."
        PRD §3.5: "The target box must be a real public fixture: requests
        against a `DRAFT` or `DECOMMISSIONED` box are rejected with
        `ERR_BOX_NOT_PUBLIC`, leaving `CHARTERED`, `ACTIVE`, and `SUSPENDED`
        boxes reportable."

        Design: Corner/errors/complaint_and_report_rejected_for_non_public_box
        """
        pin_clock()
        steward = create_active_steward(full_name="Draft Owner",
                                        email="draft@example.org")
        box = create_draft_box(steward, name="Draft Box")

        res1 = api.create_complaint(
            {"box_id": box["id"], "category": "OTHER",
             "description": "Not on map"},
            {},
        )
        validate_error(res1, ApiErrorId.ERR_BOX_NOT_PUBLIC.value,
                       expected_status=422)

        res2 = api.create_maintenance_request(
            {"box_id": box["id"], "category": "WEAR",
             "description": "Too early"},
            {},
        )
        validate_error(res2, ApiErrorId.ERR_BOX_NOT_PUBLIC.value,
                       expected_status=422)

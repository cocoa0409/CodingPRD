"""Finding-aid publication gate, the conservation assessment lifecycle with
its dual-variant priority score, and OCC on item version."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_request,
    create_active_project,
    create_assessment,
    create_ticket,
    get_ticket,
    make_researcher_headers,
    create_collection,
    create_finding_aid_payload,
    create_item,
    create_request,
    create_zone,
    catalog_item,
    create_accessioned,
    get_item,
    make_item_available,
    register_researcher,
    setup_approved_assessment,
    setup_available_item,
    validate_error,
    validate_paginated,
    validate_success,
)

ARCH = {"X-User-ID": "arch-1", "X-User-Role": "Archivist", "Content-Type": "application/json"}
RRS = {"X-User-ID": "rrs-1", "X-User-Role": "ReadingRoomStaff", "Content-Type": "application/json"}


class TestPublicationGate:

    def test_make_available_blocked_until_finding_aid_published(self):
        """PRD §3.2: "Making an item available moves it `CATALOGED → AVAILABLE`
        only when three further conditions hold beyond the item's own state: the
        collection has a published finding aid (`ERR_FINDING_AID_NOT_PUBLISHED`),
        the item's accession is `ACCESSIONED` (`ERR_ACCESSION_NOT_ACCESSIONED`),
        and the collection's zone posture is `OPEN` (`ERR_ZONE_RESTRICTED`)."

        Design: Difficulty/cross_entity_state_dependency/make_available_requires_published_finding_aid
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        accession, _deed = create_accessioned()
        # Finding aid exists but sits IN_REVIEW (never published).
        aid = validate_success(
            api_client.create_finding_aid(
                create_finding_aid_payload(collection_id=collection["id"]),
                ARCH),
            expected_status=201)
        validate_success(api_client.submit_finding_aid_review(aid["id"], ARCH))

        item = create_item(accession["id"], collection["id"], title="Diary")
        catalog_item(item["id"])

        resp = api_client.make_item_available(item["id"], ARCH)
        validate_error(resp, ApiErrorId.ERR_FINDING_AID_NOT_PUBLISHED)
        blocked = validate_success(api_client.get_item(item["id"], ARCH))
        assert blocked["status"] == "CATALOGED"

        validate_success(api_client.publish_finding_aid(aid["id"], ARCH))
        made = validate_success(api_client.make_item_available(item["id"], ARCH))
        assert made["status"] == "AVAILABLE"

    def test_publish_flips_collection_rollup_flag(self):
        """PRD §3.2: "`published_finding_aid_present` is true exactly when at
        least one finding aid for the collection has status `PUBLISHED`."
        PRD §3.3: "Publication moves `IN_REVIEW → PUBLISHED`:
        `published_revision_count` increases by 1, `published_at` records the
        logical timestamp of the publish, and the collection's
        `published_finding_aid_present` is recomputed — becoming true upon the
        first publication."

        Design: Difficulty/cross_entity_state_dependency/make_available_requires_published_finding_aid
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        aid = validate_success(
            api_client.create_finding_aid(
                create_finding_aid_payload(collection_id=collection["id"]),
                ARCH),
            expected_status=201)

        before = validate_success(api_client.get_collection(collection["id"], ARCH))
        assert before["published_finding_aid_present"] is False

        validate_success(api_client.submit_finding_aid_review(aid["id"], ARCH))
        published = validate_success(api_client.publish_finding_aid(aid["id"], ARCH))
        assert published["status"] == "PUBLISHED"
        assert published["published_revision_count"] == 1

        after = validate_success(api_client.get_collection(collection["id"], ARCH))
        assert after["published_finding_aid_present"] is True


class TestFindingAidRevisionCycle:

    def test_return_routes_to_stamped_review_origin(self):
        """PRD §3.3: "Submitting for review moves the aid from `DRAFT` or
        `IN_REVISION` into `IN_REVIEW` and stamps `review_origin` with the state
        it came from."
        PRD §3.3: "Returning an aid under review routes it back to its stamped
        origin: `IN_REVIEW → DRAFT` when `review_origin` is `DRAFT`, and
        `IN_REVIEW → IN_REVISION` when `review_origin` is `IN_REVISION`; either
        way `review_origin` is cleared to null on return."
        PRD §3.3: "A published aid may be reopened for revision (`PUBLISHED →
        IN_REVISION`)"

        Design: Difficulty/non_linear_state_machine/finding_aid_revision_cycle_with_return_routing
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        aid = validate_success(
            api_client.create_finding_aid(
                create_finding_aid_payload(collection_id=collection["id"]),
                ARCH),
            expected_status=201)

        first = validate_success(
            api_client.submit_finding_aid_review(aid["id"], ARCH))
        assert first["status"] == "IN_REVIEW"
        assert first["review_origin"] == "DRAFT"

        validate_success(api_client.publish_finding_aid(aid["id"], ARCH))
        revision = validate_success(
            api_client.open_finding_aid_revision(aid["id"], ARCH))
        assert revision["status"] == "IN_REVISION"

        second = validate_success(
            api_client.submit_finding_aid_review(aid["id"], ARCH))
        assert second["status"] == "IN_REVIEW"
        assert second["review_origin"] == "IN_REVISION", (
            "origin must remember the aid came from IN_REVISION, not DRAFT")

        returned = validate_success(api_client.return_finding_aid(aid["id"], ARCH))
        assert returned["status"] == "IN_REVISION", (
            f"return must route to the stamped origin IN_REVISION; got "
            f"{returned['status']}")
        assert returned["review_origin"] is None

    def test_publish_revision_count_and_rollup_across_cycle(self):
        """PRD §3.3: "Publication moves `IN_REVIEW → PUBLISHED`:
        `published_revision_count` increases by 1, `published_at` records the
        logical timestamp of the publish, and the collection's
        `published_finding_aid_present` is recomputed — becoming true upon the
        first publication."
        PRD §3.3: "A published aid may be reopened for revision (`PUBLISHED →
        IN_REVISION`), at which point the collection rollup is recomputed and
        drops to false when the reopened aid was the collection's only
        `PUBLISHED` one — which in turn blocks further make-available operations
        for that collection until publication is restored."

        Design: Difficulty/non_linear_state_machine/finding_aid_revision_cycle_with_return_routing
        """
        zone = create_zone()
        collection = create_collection(zone["id"])
        aid = validate_success(
            api_client.create_finding_aid(
                create_finding_aid_payload(collection_id=collection["id"]),
                ARCH),
            expected_status=201)

        validate_success(api_client.submit_finding_aid_review(aid["id"], ARCH))
        pub1 = validate_success(api_client.publish_finding_aid(aid["id"], ARCH))
        assert pub1["published_revision_count"] == 1
        assert pub1["published_at"] is not None

        validate_success(api_client.open_finding_aid_revision(aid["id"], ARCH))
        mid = validate_success(api_client.get_collection(collection["id"], ARCH))
        assert mid["published_finding_aid_present"] is False, (
            "rollup drops when the only PUBLISHED aid reopens for revision")

        validate_success(api_client.submit_finding_aid_review(aid["id"], ARCH))
        pub2 = validate_success(api_client.publish_finding_aid(aid["id"], ARCH))
        assert pub2["published_revision_count"] == 2

        final = validate_success(api_client.get_collection(collection["id"], ARCH))
        assert final["published_finding_aid_present"] is True


class TestConservationScoreVariants:

    def test_preliminary_vs_confirmed_fragile_multiplier(self):
        """PRD §3.4: "`preliminary_priority_score` is computed: a weighted sum in
        which urgency carries half the weight, demand three-tenths, and value
        one-fifth. The demand term is the smaller of 100 and the snapshot count
        times 25 points per open request; the value term is the smaller of 100
        and the item's `appraised_value_cents` divided by 1000 and rounded down
        to a whole number; the preliminary score combines the assessor's
        `urgency_score` as given with those two terms and rounds half up to 2
        decimal places."
        PRD §3.4: "The confirmed variant changes only the urgency term: when
        `condition_grade_observed` is `FRAGILE`, the effective urgency is the
        smaller of 100 and the raw `urgency_score` multiplied by 1.25 and
        rounded half up to a whole number; otherwise the urgency is used as
        given."

        Design: Difficulty/dual_variant_calc/conservation_priority_preliminary_vs_confirmed
        """
        ctx = setup_available_item(
            title="Quilt", condition_grade="POOR",
            appraised_value_cents=50000, item_format="ARTIFACT")
        item_id = ctx["item"]["id"]
        researcher = register_researcher()
        # Two open (SUBMITTED) requests referencing the item.
        create_request(researcher["id"], [item_id], topic="Textiles",
                       purpose="ACADEMIC")
        create_request(researcher["id"], [item_id], topic="Dyes",
                       purpose="PERSONAL")

        assessment = create_assessment(
            item_id, condition_grade_observed="FRAGILE", urgency_score=80,
            treatment_estimate_hours=12)
        # preliminary: 0.5*80 + 0.3*50 + 0.2*50 = 40 + 15 + 10
        assert assessment["preliminary_priority_score"] == 65.0, (
            f"preliminary must be 65.0; got "
            f"{assessment['preliminary_priority_score']}")
        assert assessment["open_request_count_snapshot"] == 2
        assert assessment["confirmed_priority_score"] is None

        approved = validate_success(
            api_client.approve_assessment(assessment["id"], ARCH))
        # confirmed: urgency_eff = min(100, round(80*1.25)) = 100
        #            0.5*100 + 0.3*50 + 0.2*50 = 50 + 15 + 10
        assert approved["confirmed_priority_score"] == 75.0, (
            f"confirmed must be 75.0; got {approved['confirmed_priority_score']}")
        assert approved["status"] == "APPROVED"

        item = get_item(item_id)
        assert item["conservation_priority_score"] == 75.0
        assert item["current_assessment_id"] == assessment["id"]

    def test_confirmed_score_null_until_approval(self):
        """PRD §3.4: "The result is stored as `confirmed_priority_score` (null
        until approval) and copied onto the item as its
        `conservation_priority_score`, with `current_assessment_id` confirmed at
        this assessment."
        PRD §3.4: "The same creation-time snapshots feed every other term —
        approval never re-reads request counts."

        Design: Difficulty/dual_variant_calc/conservation_priority_preliminary_vs_confirmed
        """
        ctx = setup_available_item(
            title="Quilt", condition_grade="POOR",
            appraised_value_cents=50000, item_format="ARTIFACT")
        item_id = ctx["item"]["id"]
        researcher = register_researcher()
        create_request(researcher["id"], [item_id], topic="Textiles")
        create_request(researcher["id"], [item_id], topic="Dyes")

        assessment = create_assessment(
            item_id, condition_grade_observed="FRAGILE", urgency_score=80,
            treatment_estimate_hours=12)
        assert assessment["confirmed_priority_score"] is None, (
            "confirmed variant is null until approval")

        item_mid = get_item(item_id)
        assert item_mid["conservation_priority_score"] is None, (
            "preliminary score is never published onto the item")

        validate_success(api_client.approve_assessment(assessment["id"], ARCH))
        item_after = get_item(item_id)
        assert item_after["conservation_priority_score"] == 75.0
        assert item_after["current_assessment_id"] == assessment["id"]


class TestTreatmentCycle:

    def test_treatment_cycle_returns_item_to_available(self):
        """PRD §3.4: "Beginning treatment requires the assessment to be
        `APPROVED` and its item to be `FLAGGED_CONSERVATION` (either violation
        is `ERR_INVALID_STATE`); it moves both into `IN_TREATMENT`. Completing
        treatment requires both to be `IN_TREATMENT`; it moves the assessment to
        `COMPLETED`, returns the item to `AVAILABLE`, sets the item's
        `condition_grade` to the request's `new_condition_grade`, and clears
        both `conservation_priority_score` and `current_assessment_id` on the
        item to null."

        Design: Difficulty/non_linear_state_machine/item_conservation_treatment_cycle
        """
        ctx = setup_available_item(
            title="Map", condition_grade="POOR",
            appraised_value_cents=30000, item_format="MAP")
        item_id = ctx["item"]["id"]
        assessment = create_assessment(
            item_id, condition_grade_observed="POOR", urgency_score=60,
            treatment_estimate_hours=8)
        validate_success(api_client.approve_assessment(assessment["id"], ARCH))
        validate_success(api_client.flag_item_conservation(item_id, ARCH))

        begun = validate_success(api_client.begin_treatment(assessment["id"], ARCH))
        assert begun["status"] == "IN_TREATMENT"
        item_mid = get_item(item_id)
        assert item_mid["status"] == "IN_TREATMENT"

        done = validate_success(api_client.complete_treatment(
            assessment["id"], {"new_condition_grade": "GOOD"}, ARCH))
        assert done["status"] == "COMPLETED"
        item_after = get_item(item_id)
        assert item_after["status"] == "AVAILABLE", (
            "the cycle returns the item to a prior state")
        assert item_after["condition_grade"] == "GOOD"

    def test_complete_treatment_clears_score_and_pointer(self):
        """PRD §3.4: "Completing treatment requires both to be `IN_TREATMENT`;
        it moves the assessment to `COMPLETED`, returns the item to
        `AVAILABLE`, sets the item's `condition_grade` to the request's
        `new_condition_grade`, and clears both `conservation_priority_score` and
        `current_assessment_id` on the item to null."
        PRD §3.4: "An item's `conservation_priority_score` is null whenever it
        has no `APPROVED` or `IN_TREATMENT` assessment."

        Design: Difficulty/non_linear_state_machine/item_conservation_treatment_cycle
        """
        ctx = setup_available_item(
            title="Map", condition_grade="POOR",
            appraised_value_cents=30000, item_format="MAP")
        item_id = ctx["item"]["id"]
        assessment = create_assessment(
            item_id, condition_grade_observed="POOR", urgency_score=60,
            treatment_estimate_hours=8)
        validate_success(api_client.approve_assessment(assessment["id"], ARCH))
        in_treatment_item = get_item(item_id)
        assert in_treatment_item["conservation_priority_score"] is not None
        validate_success(api_client.flag_item_conservation(item_id, ARCH))
        validate_success(api_client.begin_treatment(assessment["id"], ARCH))

        validate_success(api_client.complete_treatment(
            assessment["id"], {"new_condition_grade": "GOOD"}, ARCH))
        item_after = get_item(item_id)
        assert item_after["conservation_priority_score"] is None
        assert item_after["current_assessment_id"] is None


class TestDemandSnapshot:

    def test_demand_snapshot_excludes_closed_requests(self):
        """PRD §3.4: "The system snapshots `open_request_count_snapshot` — the
        count of research requests referencing the item whose status is
        `SUBMITTED`, `IN_REVIEW`, or `APPROVED` — taken once at creation and
        never recomputed, so later request activity never revisits an
        assessment's demand term."
        PRD §3.4: "The demand term is the smaller of 100 and the snapshot count
        times 25 points per open request; the value term is the smaller of 100
        and the item's `appraised_value_cents` divided by 1000 and rounded down
        to a whole number; the preliminary score combines the assessor's
        `urgency_score` as given with those two terms and rounds half up to 2
        decimal places."

        Design: Corner/calculations/demand_snapshot_excludes_closed_requests
        """
        ctx = setup_available_item(
            title="I1", condition_grade="FAIR", appraised_value_cents=9000,
            item_format="MANUSCRIPT")
        item_id = ctx["item"]["id"]
        researcher = register_researcher()

        # RQ1 -> APPROVED (counts)
        rq1 = create_request(researcher["id"], [item_id], topic="t1")
        approve_request(rq1["id"])
        # RQ2 -> DENIED (excluded)
        rq2 = create_request(researcher["id"], [item_id], topic="t2")
        validate_success(api_client.begin_request_review(rq2["id"], RRS))
        validate_success(api_client.deny_request(
            rq2["id"], {"decision_reason": "out of scope"}, RRS))
        # RQ3 -> CANCELLED (excluded)
        rq3 = create_request(researcher["id"], [item_id], topic="t3")
        validate_success(api_client.cancel_request(
            rq3["id"], make_researcher_headers(researcher["id"])))
        # RQ4 stays SUBMITTED (counts)
        create_request(researcher["id"], [item_id], topic="t4")

        assessment = create_assessment(
            item_id, condition_grade_observed="FAIR", urgency_score=40,
            treatment_estimate_hours=5)
        assert assessment["open_request_count_snapshot"] == 2, (
            f"APPROVED + SUBMITTED count, DENIED/CANCELLED excluded; got "
            f"{assessment['open_request_count_snapshot']}")
        # 0.5*40 + 0.3*min(100, 2*25) + 0.2*min(100, floor(9000/1000))
        # = 20 + 15 + 1.8
        assert assessment["preliminary_priority_score"] == 36.8, (
            f"preliminary must be 36.8; got "
            f"{assessment['preliminary_priority_score']}")


class TestAssessmentOCC:

    def test_occ_assessment_create_stale_version_rejected(self):
        """PRD §2.7: "Creating a conservation assessment — `POST
        /items/{id}/conservation-assessments` — likewise requires a non-optional
        `expected_item_version` carrying the caller's last-observed `version` of
        the item, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP
        412)."

        Design: Corner/complexity_layers/occ_assessment_create_stale_version
        """
        ctx = setup_available_item(
            title="I1", condition_grade="POOR",
            appraised_value_cents=50000, item_format="ARTIFACT")
        item_id = ctx["item"]["id"]
        stale = get_item(item_id)["version"]

        first = validate_success(api_client.create_conservation_assessment(
            item_id,
            {"expected_item_version": stale,
             "condition_grade_observed": "POOR", "urgency_score": 60,
             "treatment_estimate_hours": 5},
            ARCH), expected_status=201)

        resp = api_client.create_conservation_assessment(
            item_id,
            {"expected_item_version": stale,
             "condition_grade_observed": "FAIR", "urgency_score": 40,
             "treatment_estimate_hours": 2},
            ARCH)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

        item = get_item(item_id)
        assert item["version"] == stale + 1, (
            "the failed create must not bump the item version")
        assert item["current_assessment_id"] == first["id"]

    def test_occ_assessment_retry_supersedes_prior_draft(self):
        """PRD §2.7: "A newer assessment legitimately supersedes the item's
        previous draft or approved assessment, so here too the stale-version
        check is the sole guard against a writer acting on an observation it has
        not refreshed."
        PRD §3.4: "Any previous assessment for the item still in `DRAFT` or
        `APPROVED` status becomes `SUPERSEDED`."

        Design: Corner/complexity_layers/occ_assessment_create_stale_version
        """
        ctx = setup_available_item(
            title="I1", condition_grade="POOR",
            appraised_value_cents=50000, item_format="ARTIFACT")
        item_id = ctx["item"]["id"]

        first = create_assessment(item_id, condition_grade_observed="POOR",
                                  urgency_score=60, treatment_estimate_hours=5)
        second = create_assessment(item_id, condition_grade_observed="FAIR",
                                   urgency_score=40, treatment_estimate_hours=2)

        assessments, _meta = validate_paginated(
            api_client.list_conservation_assessments(item_id, ARCH))
        by_id = {a["id"]: a for a in assessments}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[second["id"]]["status"] == "DRAFT"
        item = get_item(item_id)
        assert item["current_assessment_id"] == second["id"]


class TestDigitizationPrioritySnapshot:

    def test_digitization_priority_snapshot_frozen(self):
        """PRD §3.5: "At creation the ticket's `priority_score` is computed and
        frozen for the ticket's whole life: a base of 50, plus 0.4 times the
        item's current `conservation_priority_score` (treated as zero when the
        item has none), plus 10 points per `APPROVED` research request
        referencing the item with the request contribution capped at three
        requests, the total rounded half up to 2 decimal places."
        PRD §3.4: "One supersession nuance is pinned: when a newer assessment
        supersedes an `APPROVED` one, the item's
        `conservation_priority_score` keeps the older confirmed value — the
        newer assessment's preliminary score is not applied until that newer
        assessment is itself approved — while `current_assessment_id` moves to
        the newer record immediately."

        Design: Corner/calculations/digitization_priority_snapshot_frozen
        """
        ctx = setup_available_item(
            title="Quilt", condition_grade="POOR",
            appraised_value_cents=50000, item_format="ARTIFACT")
        item_id = ctx["item"]["id"]
        researcher = register_researcher()
        rq = create_request(researcher["id"], [item_id], topic="t")
        approve_request(rq["id"])

        # Confirmed score: FRAGILE urgency 80 -> 100; demand 25; value 50.
        # 0.5*100 + 0.3*25 + 0.2*50 = 67.5
        setup_approved_assessment(
            item_id, condition_grade_observed="FRAGILE", urgency_score=80,
            treatment_estimate_hours=12)

        project = create_active_project("P1")
        ticket = create_ticket(project["id"], item_id)
        # 50 + 0.4*67.5 + 10*min(3, 1) = 50 + 27 + 10
        assert ticket["priority_score"] == 87.0, (
            f"creation-time snapshot must be 87.0; got {ticket['priority_score']}")

        # Reassess: FAIR urgency 40 -> 0.5*40 + 0.3*25 + 0.2*50 = 37.5
        second = setup_approved_assessment(
            item_id, condition_grade_observed="FAIR", urgency_score=40,
            treatment_estimate_hours=4)
        item = get_item(item_id)
        assert item["conservation_priority_score"] == 37.5
        assert item["current_assessment_id"] == second["id"]

        reread = get_ticket(ticket["id"])
        assert reread["priority_score"] == 87.0, (
            f"ticket priority is frozen at creation; got "
            f"{reread['priority_score']}")

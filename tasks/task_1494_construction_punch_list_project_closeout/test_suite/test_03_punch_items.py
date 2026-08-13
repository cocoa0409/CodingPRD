"""Punch item intake, correction/re-inspection cycle, sign-off duties, and counters."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_punch_item,
    begin_punch,
    complete_walk,
    create_item,
    create_punch_item_payload,
    get_item,
    get_project,
    get_trade,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_gc_inspector_headers,
    make_gc_pm_headers,
    make_subcontractor_headers,
    new_project,
    new_trade,
    schedule_walk,
    set_clock,
    setup_ready_item,
    setup_walked_project,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["gc_pm_headers"]
INSP = TEST_USERS["gc_inspector_headers"]


class TestItemIntake:

    def test_item_create_in_mobilized_project_rejected(self):
        """PRD §3.2: "A `GCInspector` or the `GCProjectManager` creates one — again only while the project is `PUNCH_ACTIVE` — with a short `title`, a `severity` of `LIFE_SAFETY`, `MAJOR`, or `MINOR`, a three-part location (`location_building`, `location_floor`, `location_area`), and a mandatory `photo_ref` attaching photographic evidence."
        PRD §2.10: "8. State-machine and project-phase validity (`ERR_INVALID_STATE`, or `ERR_PROJECT_NOT_CLOSED` for warranty reporting against a project that is not closed)."

        Design: Corner/state_machines/item_create_in_mobilized_project_rejected
        """
        project = new_project(name="Proj")
        trade = new_trade(project["id"])
        resp = api_client.create_punch_item(
            create_punch_item_payload(project["id"], trade["id"], title="Early"), INSP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_missing_photo_ref_returns_400(self):
        """PRD §3.2: "A `GCInspector` or the `GCProjectManager` creates one — again only while the project is `PUNCH_ACTIVE` — with a short `title`, a `severity` of `LIFE_SAFETY`, `MAJOR`, or `MINOR`, a three-part location (`location_building`, `location_floor`, `location_area`), and a mandatory `photo_ref` attaching photographic evidence."
        PRD §2.10: "5. Request schema — required fields present, enum values valid, numeric ranges satisfied (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/missing_photo_ref_returns_400
        """
        project = new_project(name="Proj")
        trade = new_trade(project["id"])
        begin_punch(project["id"])
        payload = create_punch_item_payload(project["id"], trade["id"], title="No photo")
        del payload["photo_ref"]
        resp = api_client.create_punch_item(payload, INSP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_punch_item_returns_persisted_fields(self):
        """PRD §3.2: "A new item starts `OPEN` and immediately blocks: the project's counter for that severity (`open_life_safety_count`, `open_major_count`, or `open_minor_count`) and the responsible trade's `open_item_count` each increase by one, and the eligibility flags of §2.8 are recomputed."
        PRD §2.5: "All eight resources — Project, TradePackage, PunchWalk, PunchItem, CloseoutDocument, TrainingSession, RetainageRelease, and WarrantyCase — share four system-managed fields:"

        Design: Corner/endpoints/get_punch_item_returns_persisted_fields
        """
        project = new_project(name="Proj")
        trade = new_trade(project["id"])
        begin_punch(project["id"])
        item = create_item(
            project["id"], trade["id"], title="Cracked tile", severity="MINOR",
            location_area="Lobby", photo_ref="img-77",
        )
        fetched = validate_success(
            api_client.get_punch_item(item["id"], TEST_USERS["owner_rep_headers"]), 200
        )
        assert_punch_item(fetched)
        assert fetched["title"] == "Cracked tile"
        assert fetched["severity"] == "MINOR"
        assert fetched["location_building"] == "B1"
        assert fetched["location_floor"] == "L1"
        assert fetched["location_area"] == "Lobby"
        assert fetched["photo_ref"] == "img-77"
        assert fetched["status"] == "OPEN"
        assert fetched["rejection_count"] == 0
        assert is_valid_uuid(fetched["id"])
        assert is_iso8601_timestamp(fetched["created_at"])

    def test_walk_from_other_project_on_item_create_returns_error(self):
        """PRD §3.2: "The payload's `trade_package_id` designates the responsible party, and an optional `punch_walk_id` cites the walk that found the item; the cited walk must belong to the same project, or creation fails with `ERR_WALK_NOT_IN_PROJECT`."

        Design: Corner/validations/walk_from_other_project_on_item_create_returns_error
        """
        project_a = new_project(name="Proj A")
        trade_a = new_trade(project_a["id"], trade_name="ELECTRICAL", subcontractor_org="SparkyCo")
        project_b = new_project(name="Proj B")
        trade_b = new_trade(project_b["id"], trade_name="PLUMBING", subcontractor_org="PipeCo")
        begin_punch(project_a["id"])
        begin_punch(project_b["id"])
        walk_b = schedule_walk(project_b["id"], trade_b["id"], "insp-1",
                               "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
        resp = api_client.create_punch_item(
            create_punch_item_payload(
                project_a["id"], trade_a["id"], title="Cross-walk",
                punch_walk_id=walk_b["id"],
            ),
            INSP,
        )
        validate_error(resp, ApiErrorId.ERR_WALK_NOT_IN_PROJECT)


class TestMarkReadyWalkGate:

    def test_mark_ready_blocked_until_trade_walk_completed(self):
        """PRD §3.3: "And the item's trade must already have completed its walk; without one the mark-ready fails with `ERR_WALK_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_trade_walk_completed
        """
        project = new_project(name="Proj X1")
        trade_a = new_trade(project["id"], trade_name="ELECTRICAL", subcontractor_org="SparkyCo")
        trade_b = new_trade(project["id"], trade_name="PLUMBING", subcontractor_org="PipeCo")
        begin_punch(project["id"])
        walk_a = schedule_walk(project["id"], trade_a["id"], "insp-1",
                               "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
        schedule_walk(project["id"], trade_b["id"], "insp-1",
                      "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        set_clock("2026-08-03T10:00:00Z")
        complete_walk(walk_a["id"])
        item_a = create_item(project["id"], trade_a["id"], title="IA", location_area="R1", photo_ref="ia")
        item_b = create_item(project["id"], trade_b["id"], title="IB", location_area="R2", photo_ref="ib")

        blocked = api_client.mark_punch_item_ready(
            item_b["id"], make_subcontractor_headers(trade_b["id"])
        )
        validate_error(blocked, ApiErrorId.ERR_WALK_INCOMPLETE)
        assert get_item(item_b["id"])["status"] == "OPEN"

        ready = validate_success(api_client.mark_punch_item_ready(
            item_a["id"], make_subcontractor_headers(trade_a["id"])
        ), 200)
        assert ready["status"] == "READY_FOR_REVIEW"

    def test_mark_ready_succeeds_after_walk_completes(self):
        """PRD §3.3: "And the item's trade must already have completed its walk; without one the mark-ready fails with `ERR_WALK_INCOMPLETE`."
        PRD §3.2: "Completion flips the trade package's `has_completed_walk` to true and triggers a recomputation of the project's substantial-completion eligibility."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_trade_walk_completed
        """
        project = new_project(name="Proj")
        trade = new_trade(project["id"])
        begin_punch(project["id"])
        walk = schedule_walk(project["id"], trade["id"], "insp-1",
                             "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
        item = create_item(project["id"], trade["id"], title="Leak", photo_ref="i1")

        blocked = api_client.mark_punch_item_ready(
            item["id"], make_subcontractor_headers(trade["id"])
        )
        validate_error(blocked, ApiErrorId.ERR_WALK_INCOMPLETE)

        set_clock("2026-08-03T10:00:00Z")
        complete_walk(walk["id"])
        ready = validate_success(api_client.mark_punch_item_ready(
            item["id"], make_subcontractor_headers(trade["id"])
        ), 200)
        assert ready["status"] == "READY_FOR_REVIEW"


class TestCorrectionCycle:

    def test_ready_reject_ready_verify_cycle(self):
        """PRD §3.3: "A failed re-inspection sends the item back. A `GCInspector` — and only that role — rejects a ready item with a mandatory `reason`, whose absence is an `ERR_INVALID_REQUEST`; the item returns to `OPEN`, its `rejection_count` increases by one, the reason is stored in `rejection_reason`, and `ready_by_user_id` is cleared to null so a fresh correction cycle begins under a different pair of hands."
        PRD §3.3: "Success moves the item from `OPEN` to `READY_FOR_REVIEW` and stamps `ready_by_user_id` with the caller's `X-User-ID` and `ready_at` with the logical clock."

        Design: Difficulty/non_linear_state_machine/punch_item_ready_reject_ready_cycle
        """
        ctx = setup_ready_item(name="Proj Cyc")
        trade, item = ctx["trade"], ctx["items"][0]
        assert item["status"] == "READY_FOR_REVIEW"
        assert item["ready_by_user_id"] == trade["id"]

        rejected = validate_success(api_client.reject_punch_item(
            item["id"], {"reason": "Still visible patch"}, INSP
        ), 200)
        assert rejected["status"] == "OPEN"
        assert rejected["rejection_count"] == 1
        assert rejected["ready_by_user_id"] is None

        re_ready = validate_success(api_client.mark_punch_item_ready(
            item["id"], make_subcontractor_headers(trade["id"])
        ), 200)
        assert re_ready["status"] == "READY_FOR_REVIEW"
        assert re_ready["ready_by_user_id"] == trade["id"]

        verified = validate_success(api_client.verify_punch_item(
            item["id"], make_gc_inspector_headers("insp-9")
        ), 200)
        assert verified["status"] == "VERIFIED"

    def test_reject_clears_ready_by_and_stores_reason(self):
        """PRD §3.3: "A failed re-inspection sends the item back. A `GCInspector` — and only that role — rejects a ready item with a mandatory `reason`, whose absence is an `ERR_INVALID_REQUEST`; the item returns to `OPEN`, its `rejection_count` increases by one, the reason is stored in `rejection_reason`, and `ready_by_user_id` is cleared to null so a fresh correction cycle begins under a different pair of hands."

        Design: Difficulty/non_linear_state_machine/punch_item_ready_reject_ready_cycle
        """
        ctx = setup_ready_item(name="Proj")
        trade, item = ctx["trade"], ctx["items"][0]

        missing_reason = api_client.reject_punch_item(item["id"], {}, INSP)
        validate_error(missing_reason, ApiErrorId.ERR_INVALID_REQUEST)

        rejected = validate_success(api_client.reject_punch_item(
            item["id"], {"reason": "Patch still visible"}, INSP
        ), 200)
        assert rejected["status"] == "OPEN"
        assert rejected["rejection_count"] == 1
        assert rejected["rejection_reason"] == "Patch still visible"
        assert rejected["ready_by_user_id"] is None


class TestCreatePriorityStateVsReferential:

    def test_state_error_beats_foreign_trade_referential(self):
        """PRD §2.10: "A single request can violate several rules at once, and which error comes back is not arbitrary: the server evaluates checks in a fixed priority order and reports the first failure."
        PRD §2.10: "8. State-machine and project-phase validity (`ERR_INVALID_STATE`, or `ERR_PROJECT_NOT_CLOSED` for warranty reporting against a project that is not closed)."
        PRD §2.10: "12. Cross-reference integrity (`ERR_TRADE_NOT_IN_PROJECT`, `ERR_WALK_NOT_IN_PROJECT`)."

        Design: Difficulty/priority_pair_validation_conflict/item_create_state_error_beats_foreign_trade_referential
        """
        project_a = new_project(name="Proj A")
        new_trade(project_a["id"], trade_name="ELECTRICAL", subcontractor_org="SparkyCo")
        project_b = new_project(name="Proj B")
        trade_b = new_trade(project_b["id"], trade_name="PLUMBING", subcontractor_org="PipeCo")
        # Project A is MOBILIZED (state violation) AND trade_b is foreign to it.
        resp = api_client.create_punch_item(
            create_punch_item_payload(project_a["id"], trade_b["id"], title="Leak stain"),
            INSP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_create_persists_no_item(self):
        """PRD §2.10: "A single request can violate several rules at once, and which error comes back is not arbitrary: the server evaluates checks in a fixed priority order and reports the first failure."
        PRD §2.10: "8. State-machine and project-phase validity (`ERR_INVALID_STATE`, or `ERR_PROJECT_NOT_CLOSED` for warranty reporting against a project that is not closed)."
        PRD §2.10: "12. Cross-reference integrity (`ERR_TRADE_NOT_IN_PROJECT`, `ERR_WALK_NOT_IN_PROJECT`)."

        Design: Difficulty/priority_pair_validation_conflict/item_create_state_error_beats_foreign_trade_referential
        """
        project_a = new_project(name="Proj A")
        new_trade(project_a["id"], trade_name="ELECTRICAL", subcontractor_org="SparkyCo")
        project_b = new_project(name="Proj B")
        trade_b = new_trade(project_b["id"], trade_name="PLUMBING", subcontractor_org="PipeCo")
        # GCProjectManager may also create items; the same priority outcome must hold.
        resp = api_client.create_punch_item(
            create_punch_item_payload(project_a["id"], trade_b["id"], title="Leak stain"),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data, meta = validate_paginated(
            api_client.list_punch_items(PM, params={"project_id": project_a["id"]})
        )
        assert meta["total_count"] == 0
        assert data == []


class TestVoidConservesCounts:

    def test_create_then_void_restores_major_count(self):
        """PRD §3.3: "Voiding moves the item from `OPEN` to `VOIDED`, decreases the same two counters by one each, and recomputes `sc_eligible` and `closeout_ready`."
        PRD §3.2: "A new item starts `OPEN` and immediately blocks: the project's counter for that severity (`open_life_safety_count`, `open_major_count`, or `open_minor_count`) and the responsible trade's `open_item_count` each increase by one, and the eligibility flags of §2.8 are recomputed."

        Design: Difficulty/compensating_invariant/punch_item_create_then_void_conserves_open_counts
        """
        ctx = setup_walked_project(name="Proj I2")
        project, trade = ctx["project"], ctx["trade"]
        baseline = get_project(project["id"])
        assert baseline["open_life_safety_count"] == 0
        assert baseline["open_major_count"] == 0
        assert baseline["open_minor_count"] == 0

        item = create_item(project["id"], trade["id"], title="Wrong grille", severity="MAJOR")
        mid = get_project(project["id"])
        assert mid["open_major_count"] == 1

        voided = validate_success(api_client.void_punch_item(item["id"], PM), 200)
        assert voided["status"] == "VOIDED"
        after = get_project(project["id"])
        assert after["open_life_safety_count"] == 0
        assert after["open_major_count"] == 0
        assert after["open_minor_count"] == 0
        assert get_trade(trade["id"])["open_item_count"] == 0

    def test_create_then_void_restores_life_safety_count(self):
        """PRD §3.3: "Voiding moves the item from `OPEN` to `VOIDED`, decreases the same two counters by one each, and recomputes `sc_eligible` and `closeout_ready`."
        PRD §2.8: "On a trade package, `open_item_count` applies the same predicate across all severities."

        Design: Difficulty/compensating_invariant/punch_item_create_then_void_conserves_open_counts
        """
        ctx = setup_walked_project(name="Proj")
        project, trade = ctx["project"], ctx["trade"]
        item = create_item(project["id"], trade["id"], title="Exit sign dead",
                           severity="LIFE_SAFETY")
        mid = get_project(project["id"])
        assert mid["open_life_safety_count"] == 1
        assert get_trade(trade["id"])["open_item_count"] == 1

        validate_success(api_client.void_punch_item(item["id"], PM), 200)
        after = get_project(project["id"])
        assert after["open_life_safety_count"] == 0
        assert get_trade(trade["id"])["open_item_count"] == 0
        assert get_item(item["id"])["status"] == "VOIDED"


class TestVerifyRules:

    def test_verify_from_open_returns_invalid_state(self):
        """PRD §3.3: "Verification is the inspector's sign-off, moving the item from `READY_FOR_REVIEW` to `VERIFIED` under the same five-phase gate."
        PRD §2.10: "8. State-machine and project-phase validity (`ERR_INVALID_STATE`, or `ERR_PROJECT_NOT_CLOSED` for warranty reporting against a project that is not closed)."

        Design: Corner/state_machines/verify_from_open_returns_invalid_state
        """
        ctx = setup_walked_project(name="Proj", item_severities=("MINOR",))
        project, trade, item = ctx["project"], ctx["trade"], ctx["items"][0]
        resp = api_client.verify_punch_item(item["id"], make_gc_inspector_headers("insp-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        item_after = get_item(item["id"])
        assert item_after["status"] == "OPEN"
        assert item_after["verified_by_user_id"] is None
        assert get_project(project["id"])["open_minor_count"] == 1

    def test_verify_by_subcontractor_returns_forbidden(self):
        """PRD §2.1: "A request whose role is not among the endpoint's allowed roles is rejected with `ERR_FORBIDDEN` (HTTP 403); §4 lists the authorized roles for every endpoint."

        Design: Corner/rbac/verify_by_subcontractor_returns_forbidden
        """
        ctx = setup_ready_item(name="Proj")
        trade, item = ctx["trade"], ctx["items"][0]
        resp = api_client.verify_punch_item(
            item["id"], make_subcontractor_headers(trade["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_item(item["id"])["status"] == "READY_FOR_REVIEW"

    def test_subcontractor_cannot_mark_ready_other_trade(self):
        """PRD §2.1: "On all three, a `SubcontractorRep` may act only on their own trade and only when that trade is `SUBCONTRACTOR`; a `GCProjectManager` may act as responsible party only on `SELF_PERFORMED` trades (the GC's self-performed correction work)."
        PRD §2.1: "Any other pairing is rejected with `ERR_NOT_RESPONSIBLE_PARTY` (HTTP 403)."

        Design: Corner/rbac/subcontractor_cannot_mark_ready_other_trade
        """
        project = new_project(name="Proj")
        trade_a = new_trade(project["id"], trade_name="ELECTRICAL", subcontractor_org="SparkyCo")
        trade_b = new_trade(project["id"], trade_name="PLUMBING", subcontractor_org="PipeCo")
        begin_punch(project["id"])
        walk_a = schedule_walk(project["id"], trade_a["id"], "insp-1",
                               "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
        walk_b = schedule_walk(project["id"], trade_b["id"], "insp-1",
                               "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        set_clock("2026-08-03T11:00:00Z")
        complete_walk(walk_a["id"])
        complete_walk(walk_b["id"])
        item_b = create_item(project["id"], trade_b["id"], title="Leak", photo_ref="i1")

        resp = api_client.mark_punch_item_ready(
            item_b["id"], make_subcontractor_headers(trade_a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESPONSIBLE_PARTY)
        item_after = get_item(item_b["id"])
        assert item_after["status"] == "OPEN"
        assert item_after["ready_by_user_id"] is None

    def test_sod_verify_by_same_user_forbidden_then_other_user_ok(self):
        """PRD §3.3: "First, the verifier's `X-User-ID` must differ from the recorded `ready_by_user_id` — the person who declared the work fixed may not certify it, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.3: "A successful verification stamps `verified_by_user_id` with the caller, decreases the project's severity counter and the trade's `open_item_count` by one each, and recomputes both `sc_eligible` and `closeout_ready` — including the cascade that can move a project waiting in `CLOSEOUT_IN_PROGRESS` into `FINAL_RELEASE_PENDING` (§3.5)."

        Design: Corner/rbac/sod_verify_by_same_user_forbidden_then_other_user_ok
        """
        ctx = setup_walked_project(name="Proj", trade_name="DRYWALL",
                                   responsible_type="SELF_PERFORMED",
                                   item_severities=("MINOR",))
        project, trade, item = ctx["project"], ctx["trade"], ctx["items"][0]
        # GC self-performed correction: the PM is the responsible party here.
        ready = validate_success(api_client.mark_punch_item_ready(
            item["id"], make_gc_pm_headers("pm-1")
        ), 200)
        assert ready["ready_by_user_id"] == "pm-1"

        same_user = api_client.verify_punch_item(item["id"], make_gc_pm_headers("pm-1"))
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        verified = validate_success(api_client.verify_punch_item(
            item["id"], make_gc_inspector_headers("insp-1")
        ), 200)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "insp-1"

    def test_escalated_item_verify_requires_pm(self):
        """PRD §3.3: "Second, once an item's `rejection_count` has reached two or more, the sign-off escalates: only a `GCProjectManager` may verify it, and a `GCInspector` attempt is rejected with `ERR_VERIFICATION_ESCALATED`."

        Design: Corner/rbac/escalated_item_verify_requires_pm
        """
        ctx = setup_walked_project(name="Proj", item_severities=("MINOR",))
        trade, item = ctx["trade"], ctx["items"][0]
        sub = make_subcontractor_headers(trade["id"])
        for reason in ("still wrong", "wrong again"):
            validate_success(api_client.mark_punch_item_ready(item["id"], sub), 200)
            validate_success(api_client.reject_punch_item(item["id"], {"reason": reason}, INSP), 200)
        validate_success(api_client.mark_punch_item_ready(item["id"], sub), 200)
        assert get_item(item["id"])["rejection_count"] == 2

        inspector_attempt = api_client.verify_punch_item(
            item["id"], make_gc_inspector_headers("insp-1")
        )
        validate_error(inspector_attempt, ApiErrorId.ERR_VERIFICATION_ESCALATED)

        verified = validate_success(api_client.verify_punch_item(
            item["id"], make_gc_pm_headers("pm-2")
        ), 200)
        assert verified["status"] == "VERIFIED"
        assert verified["rejection_count"] == 2


class TestOpenCountsFiltering:

    def test_open_counts_exclude_terminal_items(self):
        """PRD §2.8: "On a project, `open_life_safety_count`, `open_major_count`, and `open_minor_count` count the project's punch items of the corresponding severity whose status is `OPEN` or `READY_FOR_REVIEW`."
        PRD §2.8: "A ready-for-review item still blocks; only the terminal states `VERIFIED` and `VOIDED` release a counter."

        Design: Corner/calculations/open_counts_exclude_terminal_items
        """
        ctx = setup_walked_project(name="Proj")
        project, trade = ctx["project"], ctx["trade"]
        major = create_item(project["id"], trade["id"], title="MJ", severity="MAJOR",
                            location_area="R1", photo_ref="i1")
        create_item(project["id"], trade["id"], title="MN-open", severity="MINOR",
                    location_area="R2", photo_ref="i2")
        voidable = create_item(project["id"], trade["id"], title="MN-void", severity="MINOR",
                               location_area="R3", photo_ref="i3")

        # The READY_FOR_REVIEW major item must still count before verification.
        validate_success(api_client.mark_punch_item_ready(
            major["id"], make_subcontractor_headers(trade["id"])
        ), 200)
        mid = get_project(project["id"])
        assert mid["open_major_count"] == 1
        assert mid["open_minor_count"] == 2

        validate_success(api_client.verify_punch_item(
            major["id"], make_gc_inspector_headers("insp-1")
        ), 200)
        validate_success(api_client.void_punch_item(voidable["id"], PM), 200)

        after = get_project(project["id"])
        assert after["open_major_count"] == 0
        assert after["open_minor_count"] == 1
        assert get_item(major["id"])["status"] == "VERIFIED"
        assert get_item(voidable["id"])["status"] == "VOIDED"

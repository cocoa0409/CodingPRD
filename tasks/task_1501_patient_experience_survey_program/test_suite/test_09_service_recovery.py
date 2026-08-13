"""Service-recovery tickets: routing preconditions, the acknowledge/resolve
chain, SLA boundary, ownership enforcement, and the publish escalation cascade
(PRD §3.5, §3.6, §3.9)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_ticket,
    create_ticket_payload,
    field_and_publish_cycle,
    get_initiative,
    get_response,
    get_ticket,
    get_success_data,
    import_cases,
    import_discharges,
    import_responses,
    make_active_initiative,
    make_cycle,
    make_steward_headers,
    make_ticket,
    make_unit_manager_headers,
    record_response,
    set_clock,
    setup_cycle_in_state,
    setup_program,
    setup_published_cycle,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _commented_response_ctx(api, name, score=3, comment="long wait"):
    """Cycle FIELDING with one RESPONDED case whose ACCEPTED response carries
    `comment`. Returns (ctx, response)."""
    ctx = setup_cycle_in_state(
        setup_program(name=name), "FIELDING", discharge_count=1)
    response = record_response(
        ctx["case_ids"][0], ctx["vendor"]["id"], score=score,
        comment_text=comment)
    assert response["status"] == "ACCEPTED"
    return ctx, response


class TestTicketLifecycle:
    def test_unit_manager_happy_path_lifecycle(self, api):
        """PRD §3.9: "The ticket starts `OPEN`, its `program_id` is
        denormalized from the unit's program, and `created_at` comes from the
        logical clock."
        PRD §3.9: "Acknowledgement stamps `acknowledged_at` from the clock and
        computes `acknowledged_within_sla`: true exactly when the elapsed time
        from `created_at` to `acknowledged_at` is at most 48 hours."
        PRD §3.9: "Resolution closes the loop: a `UnitManager` resolves a
        ticket in `ACKNOWLEDGED` (otherwise `ERR_TICKET_NOT_RESOLVABLE`, and
        again only on their own unit's tickets), supplying a `resolution_note`
        that is stored on the ticket."

        Design: Corner/rbac/unit_manager_happy_path_lifecycle
        """
        ctx, response = _commented_response_ctx(
            api, "P-RB1", score=2, comment="nurse never introduced herself")
        unit_id = ctx["unit"]["id"]

        ticket = get_success_data(api.create_ticket(
            create_ticket_payload(unit_id, response["id"],
                                  domain="NURSE_COMM", priority="HIGH"),
            make_unit_manager_headers(unit_id)))
        assert ticket["status"] == "OPEN"

        acknowledged = validate_success(
            api.acknowledge_ticket(ticket["id"],
                                   make_unit_manager_headers(unit_id)),
            200)
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["acknowledged_within_sla"] is True

        resolved = validate_success(
            api.resolve_ticket(ticket["id"],
                               {"resolution_note": "bedside visit completed"},
                               make_unit_manager_headers(unit_id)),
            200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_note"] == "bedside visit completed"

    def test_full_queue_lifecycle_stamps_clock_times(self, api):
        """PRD §3.9: "Resolution closes the loop: a `UnitManager` resolves a
        ticket in `ACKNOWLEDGED` (otherwise `ERR_TICKET_NOT_RESOLVABLE`, and
        again only on their own unit's tickets), supplying a `resolution_note`
        that is stored on the ticket. `RESOLVED` is terminal."
        PRD §2.4: "At startup, before any explicit set, the logical clock reads
        exactly `2026-08-01T00:00:00Z`"; "The logical clock stamps ...
        `acknowledged_at` when a service-recovery ticket is acknowledged."

        Design: Corner/rbac/unit_manager_happy_path_lifecycle
        """
        ctx, response = _commented_response_ctx(api, "P-RB1B")
        unit_id = ctx["unit"]["id"]
        ticket = make_ticket(unit_id, response["id"], domain="NURSE_COMM",
                             priority="HIGH")
        assert_ticket(ticket)
        assert ticket["status"] == "OPEN"

        acknowledged = get_success_data(api.acknowledge_ticket(
            ticket["id"], make_unit_manager_headers(unit_id)))
        assert acknowledged["acknowledged_at"] == "2026-08-01T00:00:00Z"
        assert acknowledged["acknowledged_within_sla"] is True

        resolved = get_success_data(api.resolve_ticket(
            ticket["id"], {"resolution_note": "bedside visit completed"},
            make_unit_manager_headers(unit_id)))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_note"] == "bedside visit completed"
        assert resolved["acknowledged_at"] == "2026-08-01T00:00:00Z"


class TestTicketInvalidTransitions:
    def test_ticket_double_acknowledge_rejected(self, api):
        """PRD §3.9: "A `UnitManager` acknowledges a ticket in `OPEN` or
        `ESCALATED` (otherwise `ERR_TICKET_NOT_ACKNOWLEDGEABLE`), again only on
        their own unit's tickets (`ERR_UNIT_ACCESS_DENIED`)."

        Design: Corner/state_machines/ticket_double_acknowledge_rejected
        """
        ctx, response = _commented_response_ctx(
            api, "P-SM3", comment="Room was noisy")
        unit_id = ctx["unit"]["id"]
        ticket = make_ticket(unit_id, response["id"], domain="CLEANLINESS",
                             priority="MEDIUM")
        get_success_data(api.acknowledge_ticket(
            ticket["id"], make_unit_manager_headers(unit_id)))

        res = api.acknowledge_ticket(ticket["id"],
                                     make_unit_manager_headers(unit_id))
        validate_error(res, ApiErrorId.ERR_TICKET_NOT_ACKNOWLEDGEABLE)
        assert get_ticket(ticket["id"])["status"] == "ACKNOWLEDGED"

    def test_acknowledge_is_single_shot(self, api):
        """PRD §3.9: "A `UnitManager` acknowledges a ticket in `OPEN` or
        `ESCALATED` (otherwise `ERR_TICKET_NOT_ACKNOWLEDGEABLE`)"

        Design: Corner/state_machines/ticket_double_acknowledge_rejected
        """
        ctx, response = _commented_response_ctx(api, "P-SM3B")
        unit_id = ctx["unit"]["id"]
        ticket = make_ticket(unit_id, response["id"], domain="CLEANLINESS",
                             priority="LOW")
        first = validate_success(
            api.acknowledge_ticket(ticket["id"],
                                   make_unit_manager_headers(unit_id)),
            200)
        assert first["status"] == "ACKNOWLEDGED"
        validate_error(
            api.acknowledge_ticket(ticket["id"],
                                   make_unit_manager_headers(unit_id)),
            ApiErrorId.ERR_TICKET_NOT_ACKNOWLEDGEABLE)
        assert get_ticket(ticket["id"])["status"] == "ACKNOWLEDGED"

    def test_resolve_requires_acknowledged(self, api):
        """PRD §3.9: "Resolution closes the loop: a `UnitManager` resolves a
        ticket in `ACKNOWLEDGED` (otherwise `ERR_TICKET_NOT_RESOLVABLE`, and
        again only on their own unit's tickets), supplying a `resolution_note`
        that is stored on the ticket."

        Design: Corner/validations/resolve_requires_acknowledged
        """
        ctx, response = _commented_response_ctx(
            api, "P-V23", comment="slow call light")
        unit_id = ctx["unit"]["id"]
        ticket = make_ticket(unit_id, response["id"], domain="NURSE_COMM",
                             priority="HIGH")
        assert ticket["status"] == "OPEN"

        res = api.resolve_ticket(
            ticket["id"], {"resolution_note": "called patient"},
            make_unit_manager_headers(unit_id))
        validate_error(res, ApiErrorId.ERR_TICKET_NOT_RESOLVABLE)
        assert get_ticket(ticket["id"])["status"] == "OPEN"

    def test_open_ticket_cannot_skip_acknowledgement(self, api):
        """PRD §3.9: "Resolution closes the loop: a `UnitManager` resolves a
        ticket in `ACKNOWLEDGED` (otherwise `ERR_TICKET_NOT_RESOLVABLE`, and
        again only on their own unit's tickets), supplying a `resolution_note`
        that is stored on the ticket."
        PRD §3.9: "The ticket starts `OPEN`"

        Design: Corner/validations/resolve_requires_acknowledged
        """
        ctx, response = _commented_response_ctx(api, "P-V23B")
        unit_id = ctx["unit"]["id"]
        ticket = make_ticket(unit_id, response["id"], domain="OVERALL_RATING",
                             priority="LOW")
        validate_error(
            api.resolve_ticket(ticket["id"], {"resolution_note": "visited"},
                               make_unit_manager_headers(unit_id)),
            ApiErrorId.ERR_TICKET_NOT_RESOLVABLE)
        assert get_ticket(ticket["id"])["status"] == "OPEN"
        # The proper chain still works afterwards.
        get_success_data(api.acknowledge_ticket(
            ticket["id"], make_unit_manager_headers(unit_id)))
        resolved = validate_success(
            api.resolve_ticket(ticket["id"], {"resolution_note": "visited"},
                               make_unit_manager_headers(unit_id)),
            200)
        assert resolved["status"] == "RESOLVED"


class TestTicketRoutingPreconditions:
    def test_ticket_requires_comment(self, api):
        """PRD §3.9: "the response must carry a non-empty `comment_text`,
        because there is nothing to route without one
        (`ERR_NO_COMMENT_TO_ROUTE`)."

        Design: Corner/validations/ticket_requires_comment
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V16"), "FIELDING", discharge_count=1)
        response = record_response(ctx["case_ids"][0], ctx["vendor"]["id"])
        assert response.get("comment_text") is None
        unit_id = ctx["unit"]["id"]

        res = api.create_ticket(
            create_ticket_payload(unit_id, response["id"],
                                  domain="NURSE_COMM", priority="LOW"),
            make_unit_manager_headers(unit_id))
        validate_error(res, ApiErrorId.ERR_NO_COMMENT_TO_ROUTE)
        assert res.status_code == 422

    def test_commentless_response_has_nothing_to_route(self, api):
        """PRD §3.9: "the response must carry a non-empty `comment_text`,
        because there is nothing to route without one
        (`ERR_NO_COMMENT_TO_ROUTE`)."
        PRD §3.4: "an optional `comment_text` carries free-text patient
        feedback."

        Design: Corner/validations/ticket_requires_comment
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V16B"), "FIELDING", discharge_count=1)
        response = record_response(ctx["case_ids"][0], ctx["vendor"]["id"],
                                   score=4)
        unit_id = ctx["unit"]["id"]
        validate_error(
            api.create_ticket(
                create_ticket_payload(unit_id, response["id"],
                                      domain="OVERALL_RATING", priority="LOW"),
                make_unit_manager_headers(unit_id)),
            ApiErrorId.ERR_NO_COMMENT_TO_ROUTE)
        data = get_success_data(api.list_tickets(
            ADMIN, params={"response_id": response["id"]}))
        assert data == []

    def test_ticket_requires_final_response(self, api):
        """PRD §3.9: "the response must be in `ACCEPTED` or `INCLUDED`
        (`ERR_RESPONSE_NOT_FINAL`)"
        PRD §3.4: "when the calendar date of `received_at` falls after the
        cycle's `fielding_end_date`, the response is marked `is_late` and
        starts in `PENDING_REVIEW`"

        Design: Corner/validations/ticket_requires_final_response
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V28"), "FIELDING", discharge_count=1)
        set_clock("2026-09-05T00:00:00Z")
        late = record_response(ctx["case_ids"][0], ctx["vendor"]["id"],
                               score=2, comment="late arrival, unhappy")
        assert late["status"] == "PENDING_REVIEW"
        unit_id = ctx["unit"]["id"]

        res = api.create_ticket(
            create_ticket_payload(unit_id, late["id"],
                                  domain="OVERALL_RATING", priority="HIGH"),
            make_unit_manager_headers(unit_id))
        validate_error(res, ApiErrorId.ERR_RESPONSE_NOT_FINAL)
        assert res.status_code == 409

    def test_pending_review_response_cannot_be_routed(self, api):
        """PRD §3.9: "the response must be in `ACCEPTED` or `INCLUDED`
        (`ERR_RESPONSE_NOT_FINAL`)"
        PRD §2.7: "Adjudication of late responses requires `RECONCILIATION`"

        Design: Corner/validations/ticket_requires_final_response
        """
        ctx = setup_cycle_in_state(
            setup_program(name="P-V28B"), "FIELDING", discharge_count=1)
        set_clock("2026-09-05T00:00:00Z")
        late = record_response(ctx["case_ids"][0], ctx["vendor"]["id"],
                               score=2, comment="late arrival, unhappy")
        assert late["is_late"] is True
        unit_id = ctx["unit"]["id"]
        validate_error(
            api.create_ticket(
                create_ticket_payload(unit_id, late["id"],
                                      domain="OVERALL_RATING",
                                      priority="HIGH"),
                make_unit_manager_headers(unit_id)),
            ApiErrorId.ERR_RESPONSE_NOT_FINAL)

    def test_ticket_unit_must_match_response_unit(self, api):
        """PRD §3.9: "the response's attributed unit — the `unit_id` of its
        sample case — must equal the ticket's `unit_id`
        (`ERR_UNIT_RESPONSE_MISMATCH`)"

        Design: Corner/validations/ticket_unit_must_match_response_unit
        """
        ctx, response = _commented_response_ctx(api, "P-V17",
                                                comment="long wait")
        unit2 = get_success_data(api.create_unit(
            {"program_id": ctx["program"]["id"], "name": "Unit 2",
             "unit_code": "U2"},
            ADMIN))
        res = api.create_ticket(
            create_ticket_payload(unit2["id"], response["id"],
                                  domain="NURSE_COMM", priority="LOW"),
            make_unit_manager_headers(unit2["id"]))
        validate_error(res, ApiErrorId.ERR_UNIT_RESPONSE_MISMATCH)
        assert res.status_code == 400

    def test_routing_to_another_unit_fails_referential_check(self, api):
        """PRD §3.9: "the response's attributed unit — the `unit_id` of its
        sample case — must equal the ticket's `unit_id`
        (`ERR_UNIT_RESPONSE_MISMATCH`)"
        PRD §2.6: "9. **Referential scope.** Body-referenced resources belong
        to the same program aggregate (`ERR_CROSS_PROGRAM_REFERENCE`,
        `ERR_UNIT_RESPONSE_MISMATCH`)."

        Design: Corner/validations/ticket_unit_must_match_response_unit
        """
        ctx, response = _commented_response_ctx(api, "P-V17B")
        unit2 = get_success_data(api.create_unit(
            {"program_id": ctx["program"]["id"], "name": "Unit 2",
             "unit_code": "U2"},
            ADMIN))
        validate_error(
            api.create_ticket(
                create_ticket_payload(unit2["id"], response["id"],
                                      domain="NURSE_COMM", priority="LOW"),
                make_unit_manager_headers(unit2["id"])),
            ApiErrorId.ERR_UNIT_RESPONSE_MISMATCH)
        data = get_success_data(api.list_tickets(
            ADMIN, params={"response_id": response["id"]}))
        assert data == []


class TestUnitManagerOwnership:
    def test_unit_manager_ownership_denied(self, api):
        """PRD §2.1: "When `X-User-Role` is `UnitManager`, `X-User-ID` is the
        `id` of the acting `CareUnit`; ownership checks on service-recovery
        work compare the ticket's `unit_id` — or the requested `unit_id` at
        ticket creation — to `X-User-ID`. A unit manager operating on a ticket
        of another unit is rejected with `ERR_UNIT_ACCESS_DENIED` (HTTP 403)."

        Design: Corner/validations/unit_manager_ownership_denied
        """
        ctx, response = _commented_response_ctx(api, "P-V19",
                                                comment="cold meals")
        unit1 = ctx["unit"]
        unit2 = get_success_data(api.create_unit(
            {"program_id": ctx["program"]["id"], "name": "Unit 2",
             "unit_code": "U2"},
            ADMIN))
        ticket = make_ticket(unit1["id"], response["id"],
                             domain="OVERALL_RATING", priority="MEDIUM")

        res = api.acknowledge_ticket(ticket["id"],
                                     make_unit_manager_headers(unit2["id"]))
        validate_error(res, ApiErrorId.ERR_UNIT_ACCESS_DENIED)
        assert res.status_code == 403
        assert get_ticket(ticket["id"])["status"] == "OPEN"

    def test_foreign_unit_cannot_acknowledge(self, api):
        """PRD §2.1: "A unit manager operating on a ticket of another unit is
        rejected with `ERR_UNIT_ACCESS_DENIED` (HTTP 403)."
        PRD §3.9: "A `UnitManager` acknowledges a ticket in `OPEN` or
        `ESCALATED` (otherwise `ERR_TICKET_NOT_ACKNOWLEDGEABLE`), again only on
        their own unit's tickets (`ERR_UNIT_ACCESS_DENIED`)."

        Design: Corner/validations/unit_manager_ownership_denied
        """
        ctx, response = _commented_response_ctx(api, "P-V19B")
        unit1 = ctx["unit"]
        unit2 = get_success_data(api.create_unit(
            {"program_id": ctx["program"]["id"], "name": "Unit 2",
             "unit_code": "U2"},
            ADMIN))
        ticket = make_ticket(unit1["id"], response["id"])

        validate_error(
            api.acknowledge_ticket(ticket["id"],
                                   make_unit_manager_headers(unit2["id"])),
            ApiErrorId.ERR_UNIT_ACCESS_DENIED)
        # The owning unit manager can still acknowledge.
        acknowledged = validate_success(
            api.acknowledge_ticket(ticket["id"],
                                   make_unit_manager_headers(unit1["id"])),
            200)
        assert acknowledged["status"] == "ACKNOWLEDGED"


class TestServiceRecoverySla:
    def _two_tickets(self, api, name):
        ctx = setup_cycle_in_state(
            setup_program(name=name), "FIELDING", discharge_count=2)
        unit_id = ctx["unit"]["id"]
        r1 = record_response(ctx["case_ids"][0], ctx["vendor"]["id"], score=3,
                             comment_text="c1")
        r2 = record_response(ctx["case_ids"][1], ctx["vendor"]["id"], score=3,
                             comment_text="c2")
        t1 = make_ticket(unit_id, r1["id"], domain="OVERALL_RATING",
                         priority="LOW")
        t2 = make_ticket(unit_id, r2["id"], domain="OVERALL_RATING",
                         priority="LOW")
        return ctx, t1, t2

    def test_sla_48h_boundary_inclusive(self, api):
        """PRD §3.9: "Acknowledgement stamps `acknowledged_at` from the clock
        and computes `acknowledged_within_sla`: true exactly when the elapsed
        time from `created_at` to `acknowledged_at` is at most 48 hours. The
        boundary is inclusive — exactly 48 hours, 0 minutes, 0 seconds is
        within SLA; one second beyond is not."

        Design: Corner/calculations/sla_48h_boundary_inclusive
        """
        ctx, t1, t2 = self._two_tickets(api, "P-CA3")
        unit_id = ctx["unit"]["id"]

        set_clock("2026-08-03T00:00:00Z")  # exactly 48h after creation
        first = validate_success(
            api.acknowledge_ticket(t1["id"], make_unit_manager_headers(unit_id)),
            200)
        assert first["acknowledged_within_sla"] is True

        set_clock("2026-08-03T00:00:01Z")  # 48h + 1s
        second = validate_success(
            api.acknowledge_ticket(t2["id"], make_unit_manager_headers(unit_id)),
            200)
        assert second["acknowledged_within_sla"] is False

    def test_sla_boundary_at_48h_plus_one_second(self, api):
        """PRD §3.9: "The boundary is inclusive — exactly 48 hours, 0 minutes,
        0 seconds is within SLA; one second beyond is not."
        PRD §3.9: "Until acknowledgement, `acknowledged_within_sla` is null."

        Design: Corner/calculations/sla_48h_boundary_inclusive
        """
        ctx, t1, t2 = self._two_tickets(api, "P-CA3B")
        unit_id = ctx["unit"]["id"]
        # Before acknowledgement the SLA outcome is null.
        assert get_ticket(t1["id"])["acknowledged_within_sla"] is None
        assert get_ticket(t2["id"])["acknowledged_within_sla"] is None

        set_clock("2026-08-03T00:00:00Z")
        within = validate_success(
            api.acknowledge_ticket(t1["id"], make_unit_manager_headers(unit_id)),
            200)
        assert within["acknowledged_within_sla"] is True
        assert within["acknowledged_at"] == "2026-08-03T00:00:00Z"

        set_clock("2026-08-03T00:00:01Z")
        beyond = validate_success(
            api.acknowledge_ticket(t2["id"], make_unit_manager_headers(unit_id)),
            200)
        assert beyond["acknowledged_within_sla"] is False


def _cascade_scenario(api, name, topbox_count, low_count, target):
    """Baseline idx1 PUBLISHED (unit CLEANLINESS adjusted 80.00); ACTIVE
    initiative on (U1, CLEANLINESS) evaluating idx2; idx2 FIELDING with
    21x4 + 4x3 MAIL responses where ONE all-3 response carries a comment
    routed to an OPEN ticket on (U1, CLEANLINESS)."""
    prog_ctx = setup_program(name=name)
    c1 = setup_published_cycle(prog_ctx, 1, "Q1", 20, 5)["cycle"]
    c2 = make_cycle(prog_ctx["program"]["id"], label="Q2", cycle_index=2,
                    discharge_window_start="2026-07-01",
                    discharge_window_end="2026-07-31",
                    fielding_start_date="2026-09-01",
                    fielding_end_date="2026-09-30")
    initiative = make_active_initiative(
        prog_ctx["unit"]["id"], "CLEANLINESS", c1["id"], c2["id"], target)
    get_success_data(api.open_sampling(c2["id"], ADMIN))
    d_top = import_discharges(
        prog_ctx["program"]["id"], prog_ctx["unit"]["id"],
        prog_ctx["provider"]["id"], topbox_count, mrn_prefix="C",
        admit_date="2026-07-01", discharge_date="2026-07-03")
    d_low = import_discharges(
        prog_ctx["program"]["id"], prog_ctx["unit"]["id"],
        prog_ctx["provider"]["id"], low_count, mrn_prefix="D",
        admit_date="2026-07-01", discharge_date="2026-07-03")
    k_top = import_cases(c2["id"], d_top, mode_assigned="MAIL")
    k_low = import_cases(c2["id"], d_low, mode_assigned="MAIL")
    get_success_data(api.start_fielding(c2["id"], ADMIN))
    import_responses(k_top, prog_ctx["vendor"]["id"], mode_used="MAIL",
                     score=4)
    for case_id in k_low[:-1]:
        record_response(case_id, prog_ctx["vendor"]["id"], score=3)
    commented = record_response(
        k_low[-1], prog_ctx["vendor"]["id"], score=3,
        comment_text="Room was dirty")
    ticket = make_ticket(prog_ctx["unit"]["id"], commented["id"],
                         domain="CLEANLINESS", priority="HIGH")
    set_clock("2026-09-30T00:00:00Z")
    get_success_data(api.close_fielding(c2["id"], ADMIN))
    get_success_data(api.begin_scoring(c2["id"], ADMIN))
    return prog_ctx, initiative, c2, commented, ticket


class TestPublishEscalationCascade:
    def test_publish_to_response_flag_cascade(self, api):
        """PRD §3.6: "Publication also fires the improvement cascade, in four
        hops. First the cycle pins its star rating. Then every improvement
        initiative whose `evaluation_cycle_id` is this cycle and whose status
        is `ACTIVE` moves to `UNDER_EVALUATION` and immediately branches: when
        the unit's published adjusted percentage for the initiative's domain in
        this cycle is at least the `target_score` — the comparison inclusive,
        so exactly meeting the target succeeds — the initiative lands in
        `TARGET_MET` and stamps `achieved_at` from the clock; otherwise it
        lands in `TARGET_MISSED`. For each initiative that lands
        `TARGET_MISSED`, every service-recovery ticket on the same `unit_id`
        and `domain` that is still `OPEN` escalates to `ESCALATED`. Finally,
        for each ticket escalated that way, the response it routes is marked
        `has_escalated_recovery` true."

        Design: Difficulty/transitive_cascade/publish_to_response_flag_cascade
        """
        prog_ctx, initiative, c2, response, ticket = _cascade_scenario(
            api, "P-TC1", 21, 4, 85.0)
        assert get_ticket(ticket["id"])["status"] == "OPEN"

        published = validate_success(api.publish_cycle(c2["id"], ADMIN), 200)
        assert published["status"] == "PUBLISHED"
        assert published["published_star_rating"] == 4

        # Hop B: 84.00 < 85.00 -> TARGET_MISSED.
        assert get_initiative(initiative["id"])["status"] == "TARGET_MISSED"
        # Hop C: the OPEN ticket on the same unit+domain escalates.
        assert get_ticket(ticket["id"])["status"] == "ESCALATED"
        # Hop D: the routed response is flagged.
        assert get_response(response["id"])["has_escalated_recovery"] is True

    def test_publish_cascade_marks_ticket_and_response(self, api):
        """PRD §3.6: "For each initiative that lands `TARGET_MISSED`, every
        service-recovery ticket on the same `unit_id` and `domain` that is
        still `OPEN` escalates to `ESCALATED`. Finally, for each ticket
        escalated that way, the response it routes is marked
        `has_escalated_recovery` true."
        PRD §3.6: "On publish, `published_star_rating` is pinned from the star
        rating of the stored snapshot and `published_at` is stamped from the
        logical clock."

        Design: Difficulty/transitive_cascade/publish_to_response_flag_cascade
        """
        prog_ctx, initiative, c2, response, ticket = _cascade_scenario(
            api, "P-TC1B", 21, 4, 85.0)
        published = validate_success(api.publish_cycle(c2["id"], ADMIN), 200)
        assert published["status"] == "PUBLISHED"
        assert published["published_star_rating"] == 4
        assert published["published_at"] == "2026-09-30T00:00:00Z"

        after = get_initiative(initiative["id"])
        assert after["status"] == "TARGET_MISSED"
        assert get_ticket(ticket["id"])["status"] == "ESCALATED"
        assert get_response(response["id"])["has_escalated_recovery"] is True


class TestInitiativeMetBranch:
    def _met_scenario(self, api, name):
        """Same shape as the missed-branch scenario but idx2 carries
        22 all-4 + 3 all-3 -> adjusted 88.00 >= target 85.00 -> TARGET_MET."""
        return _cascade_scenario(api, name, 22, 3, 85.0)

    def test_initiative_met_branch_side_effects(self, api):
        """PRD §3.6: "when the unit's published adjusted percentage for the
        initiative's domain in this cycle is at least the `target_score` — the
        comparison inclusive, so exactly meeting the target succeeds — the
        initiative lands in `TARGET_MET` and stamps `achieved_at` from the
        clock; otherwise it lands in `TARGET_MISSED`. For each initiative that
        lands `TARGET_MISSED`, every service-recovery ticket on the same
        `unit_id` and `domain` that is still `OPEN` escalates to `ESCALATED`."
        PRD §3.8: "The **pinned** variant, `progress_pinned`, is the current
        value minus the frozen `baseline_score`, rounded half-up to two decimal
        places"

        Design: Corner/state_machines/initiative_met_branch_side_effects
        """
        prog_ctx, initiative, c2, response, ticket = self._met_scenario(
            api, "P-SM6")
        validate_success(api.publish_cycle(c2["id"], ADMIN), 200)

        after = get_initiative(initiative["id"])
        assert after["status"] == "TARGET_MET"
        assert after["achieved_at"] == "2026-09-30T00:00:00Z"
        assert after["progress_pinned"] == pytest.approx(8.0, abs=0.001)
        assert get_ticket(ticket["id"])["status"] == "OPEN"
        assert get_response(response["id"])["has_escalated_recovery"] is False

    def test_met_branch_does_not_escalate_tickets(self, api):
        """PRD §3.6: "when the unit's published adjusted percentage for the
        initiative's domain in this cycle is at least the `target_score` — the
        comparison inclusive, so exactly meeting the target succeeds — the
        initiative lands in `TARGET_MET` and stamps `achieved_at` from the
        clock; otherwise it lands in `TARGET_MISSED`. For each initiative that
        lands `TARGET_MISSED`, every service-recovery ticket on the same
        `unit_id` and `domain` that is still `OPEN` escalates to `ESCALATED`.
        Finally, for each ticket escalated that way, the response it routes is
        marked `has_escalated_recovery` true."

        Design: Corner/state_machines/initiative_met_branch_side_effects
        """
        prog_ctx, initiative, c2, response, ticket = self._met_scenario(
            api, "P-SM6B")
        validate_success(api.publish_cycle(c2["id"], ADMIN), 200)

        after = get_initiative(initiative["id"])
        assert after["status"] == "TARGET_MET"
        assert after["achieved_at"] is not None
        assert get_ticket(ticket["id"])["status"] == "OPEN"
        assert get_response(response["id"])["has_escalated_recovery"] is False

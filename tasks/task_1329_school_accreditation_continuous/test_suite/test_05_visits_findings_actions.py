"""Visits, findings, and required action items (PRD §3.2, §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_assignment_payload,
    create_reviewer,
    create_visit_payload,
    get_success_data,
    set_clock,
    setup_open_action_item,
    setup_self_study_term,
    validate_error,
    walk_term_to_review,
)

OFFICER = TEST_USERS["officer_headers"]


def _review_ctx_two_campuses():
    """DISTRICT with two campuses, term walked to REVIEW (PRD §3.2)."""
    ctx = setup_self_study_term(system_name="Conflict County",
                                system_type="DISTRICT",
                                campuses=[("North", 500), ("South", 400)])
    walk_term_to_review(ctx)
    return ctx


def _create_visit(ctx, campus_idx, lead, starts_on, ends_on):
    return get_success_data(api_client.create_visit(
        ctx["term"]["id"],
        create_visit_payload(lead["id"],
                             campus_id=ctx["campuses"][campus_idx]["id"],
                             starts_on=starts_on, ends_on=ends_on),
        OFFICER))


def _assign(visit_id, reviewer_id, role="CHAIR"):
    return get_success_data(api_client.create_visit_assignment(
        visit_id, create_assignment_payload(reviewer_id, role_on_team=role),
        OFFICER))


def _confirmed_visit(ctx, campus_idx, lead, starts_on, ends_on):
    """Create a visit, assign the lead as CHAIR, confirm it. Returns the visit."""
    visit = _create_visit(ctx, campus_idx, lead, starts_on, ends_on)
    _assign(visit["id"], lead["id"], "CHAIR")
    return get_success_data(api_client.confirm_visit(visit["id"], OFFICER))


class TestConfirmPriorityTemporalOverReferential:
    def test_campus_overlap_masks_unavailable_lead(self, api):
        """PRD §2.5: "the server evaluates rule families in a fixed priority
        order so the surfaced error is deterministic".
        PRD §2.5: "then temporal-window rules (`ERR_TEMPORAL_WINDOW_VIOLATION`),
        then cross-entity referential integrity (`ERR_REFERENTIAL_INTEGRITY`)".
        PRD §3.6: "no other visit for the same campus may overlap the half-open
        date interval from `starts_on` (inclusive) to `ends_on` (exclusive)
        while holding status `CONFIRMED` or `IN_FIELD`".
        PRD §3.6: "Overlap violations surface as `ERR_TEMPORAL_WINDOW_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_visit_confirm
        """
        ctx = _review_ctx_two_campuses()
        r1 = create_reviewer(full_name="Rev One", email="r1@accreditor.org")
        r2 = create_reviewer(full_name="Rev Two", email="r2@accreditor.org")
        r3 = create_reviewer(full_name="Rev Three", email="r3@accreditor.org")

        # V0 CONFIRMED on North 03-01..03-03 (R2); V1 CONFIRMED on South
        # 05-01..05-03 (R1) -> R1 now ON_ASSIGNMENT.
        _confirmed_visit(ctx, 0, r2, "2027-03-01T00:00:00Z", "2027-03-03T00:00:00Z")
        _confirmed_visit(ctx, 1, r1, "2027-05-01T00:00:00Z", "2027-05-03T00:00:00Z")

        # V2 on North, lead R1 (not AVAILABLE -> referential), dates overlap V0
        # (-> temporal). The available R3 chairs so only those two legs fail.
        v2 = _create_visit(ctx, 0, r1, "2027-03-02T00:00:00Z", "2027-03-05T00:00:00Z")
        _assign(v2["id"], r3["id"], "CHAIR")
        resp = api_client.confirm_visit(v2["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_WINDOW_VIOLATION)

    def test_reviewer_double_booking_masks_unavailable_lead(self, api):
        """PRD §3.6: "no reviewer assigned to this visit may be assigned to
        another visit whose date interval overlaps this one while that visit is
        `CONFIRMED` or `IN_FIELD`."
        PRD §3.6: "Overlap violations surface as `ERR_TEMPORAL_WINDOW_VIOLATION`."
        PRD §2.5: "the server evaluates rule families in a fixed priority order
        so the surfaced error is deterministic".
        PRD §2.5: "then temporal-window rules (`ERR_TEMPORAL_WINDOW_VIOLATION`),
        then cross-entity referential integrity (`ERR_REFERENTIAL_INTEGRITY`)".

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_referential_on_visit_confirm
        """
        ctx = _review_ctx_two_campuses()
        r1 = create_reviewer(full_name="Rev One", email="r1@accreditor.org")
        r2 = create_reviewer(full_name="Rev Two", email="r2@accreditor.org")
        r3 = create_reviewer(full_name="Rev Three", email="r3@accreditor.org")

        v0 = _create_visit(ctx, 0, r2, "2027-03-01T00:00:00Z", "2027-03-05T00:00:00Z")
        _assign(v0["id"], r2["id"], "CHAIR")
        v1 = _create_visit(ctx, 1, r1, "2027-05-01T00:00:00Z", "2027-05-03T00:00:00Z")
        _assign(v1["id"], r1["id"], "CHAIR")
        # V2 on South (no campus clash with V0/V1 at these dates), lead R1;
        # R2 joins as MEMBER while still AVAILABLE, before V0 is confirmed.
        v2 = _create_visit(ctx, 1, r1, "2027-03-02T00:00:00Z", "2027-03-04T00:00:00Z")
        _assign(v2["id"], r3["id"], "CHAIR")
        _assign(v2["id"], r2["id"], "MEMBER")

        get_success_data(api_client.confirm_visit(v0["id"], OFFICER))
        get_success_data(api_client.confirm_visit(v1["id"], OFFICER))

        # Confirming V2 trips reviewer double-booking (R2 on CONFIRMED V0 with
        # overlapping dates -> temporal) and lead-not-AVAILABLE (R1 ->
        # referential); the temporal family is evaluated first.
        resp = api_client.confirm_visit(v2["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_WINDOW_VIOLATION)


class TestConfirmRequiresLeadAvailable:
    def test_confirm_rejected_when_lead_on_assignment(self, api):
        """PRD §3.6: "the reviewer named by `lead_reviewer_id` must be
        `AVAILABLE`".
        PRD §3.6: "the reviewer must exist and be `AVAILABLE`, else
        `ERR_REFERENTIAL_INTEGRITY`."

        Design: Difficulty/cross_entity_state_dependency/visit_confirm_requires_reviewer_available
        """
        ctx = _review_ctx_two_campuses()
        r1 = create_reviewer(full_name="Busy R1", email="busy@accreditor.org")
        r2 = create_reviewer(full_name="Free R2", email="free@accreditor.org")

        _confirmed_visit(ctx, 0, r1, "2027-03-01T00:00:00Z", "2027-03-03T00:00:00Z")

        # Second visit, non-overlapping dates, led by the now-busy R1 with an
        # available R2 chairing: only the lead-availability precondition fails.
        v1 = _create_visit(ctx, 0, r1, "2027-04-01T00:00:00Z", "2027-04-03T00:00:00Z")
        _assign(v1["id"], r2["id"], "CHAIR")
        resp = api_client.confirm_visit(v1["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)

    def test_confirm_rejected_when_lead_member_of_other_confirmed_visit(self, api):
        """PRD §3.6: "the reviewer named by `lead_reviewer_id` must be
        `AVAILABLE`".
        PRD §3.6: "On confirmation, every assigned reviewer moves `AVAILABLE` →
        `ON_ASSIGNMENT`, and each assigned reviewer's `version` increments
        alongside the visit's."

        Design: Difficulty/cross_entity_state_dependency/visit_confirm_requires_reviewer_available
        """
        ctx = _review_ctx_two_campuses()
        r1 = create_reviewer(full_name="Member R1", email="member@accreditor.org")
        r2 = create_reviewer(full_name="Lead R2", email="lead2@accreditor.org")
        r3 = create_reviewer(full_name="Free R3", email="free3@accreditor.org")

        # V0 led by R2 with R1 as MEMBER; confirming flips both to ON_ASSIGNMENT.
        v0 = _create_visit(ctx, 0, r2, "2027-03-01T00:00:00Z", "2027-03-03T00:00:00Z")
        _assign(v0["id"], r2["id"], "CHAIR")
        _assign(v0["id"], r1["id"], "MEMBER")
        get_success_data(api_client.confirm_visit(v0["id"], OFFICER))

        # R1 is ON_ASSIGNMENT via a MEMBER seat; leading V1 must still fail.
        v1 = _create_visit(ctx, 1, r1, "2027-04-01T00:00:00Z", "2027-04-03T00:00:00Z")
        _assign(v1["id"], r3["id"], "CHAIR")
        resp = api_client.confirm_visit(v1["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


class TestCampusVisitOverlapHalfOpen:
    def test_adjacent_endpoints_do_not_overlap_but_intersection_does(self, api):
        """PRD §3.6: "no other visit for the same campus may overlap the
        half-open date interval from `starts_on` (inclusive) to `ends_on`
        (exclusive) while holding status `CONFIRMED` or `IN_FIELD`".
        PRD §3.6: "Overlap violations surface as `ERR_TEMPORAL_WINDOW_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/campus_visit_overlap_half_open_adjacency
        """
        ctx = _review_ctx_two_campuses()
        ra = create_reviewer(full_name="Rev A", email="reva@accreditor.org")
        rb = create_reviewer(full_name="Rev B", email="revb@accreditor.org")
        rc = create_reviewer(full_name="Rev C", email="revc@accreditor.org")

        _confirmed_visit(ctx, 0, ra, "2027-03-01T00:00:00Z", "2027-03-05T00:00:00Z")

        # Adjacent at the exclusive ends_on boundary: [03-05, 03-07) is free.
        adjacent = _confirmed_visit(ctx, 0, rb, "2027-03-05T00:00:00Z",
                                    "2027-03-07T00:00:00Z")
        assert adjacent["status"] == "CONFIRMED"

        # One-day intersection [03-04, 03-05) with the confirmed visit overlaps.
        v_over = _create_visit(ctx, 0, rc, "2027-03-04T00:00:00Z",
                               "2027-03-06T00:00:00Z")
        _assign(v_over["id"], rc["id"], "CHAIR")
        resp = api_client.confirm_visit(v_over["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_WINDOW_VIOLATION)

    def test_visit_ending_at_confirmed_start_is_adjacent(self, api):
        """PRD §3.6: "no other visit for the same campus may overlap the
        half-open date interval from `starts_on` (inclusive) to `ends_on`
        (exclusive) while holding status `CONFIRMED` or `IN_FIELD`".

        Design: Difficulty/resource_temporal_overlap/campus_visit_overlap_half_open_adjacency
        """
        ctx = _review_ctx_two_campuses()
        ra = create_reviewer(full_name="Rev A", email="reva@accreditor.org")
        rb = create_reviewer(full_name="Rev B", email="revb@accreditor.org")

        _confirmed_visit(ctx, 0, ra, "2027-03-01T00:00:00Z", "2027-03-05T00:00:00Z")

        # [02-27, 03-01) ends exactly at the confirmed visit's inclusive start.
        before = _confirmed_visit(ctx, 0, rb, "2027-02-27T00:00:00Z",
                                  "2027-03-01T00:00:00Z")
        assert before["status"] == "CONFIRMED"


class TestConfirmSideEffectOnReviewer:
    def test_confirm_flips_reviewer_on_assignment_and_cancel_frees(self, api):
        """PRD §3.6: "On confirmation, every assigned reviewer moves `AVAILABLE`
        → `ON_ASSIGNMENT`, and each assigned reviewer's `version` increments
        alongside the visit's."
        PRD §3.6: "cancelling a confirmed visit frees every assigned reviewer
        back to `AVAILABLE`."

        Design: Corner/state_machines/side_effect_visit_confirm_flips_reviewer
        """
        ctx = setup_self_study_term(system_name="SideEffect County")
        walk_term_to_review(ctx)
        reviewer = create_reviewer(full_name="Rev A", email="reva@accreditor.org")
        assert reviewer["reviewer_status"] == "AVAILABLE"

        visit = _create_visit(ctx, 0, reviewer, "2027-03-01T00:00:00Z",
                              "2027-03-03T00:00:00Z")
        _assign(visit["id"], reviewer["id"], "CHAIR")
        get_success_data(api_client.confirm_visit(visit["id"], OFFICER))
        after_confirm = get_success_data(api_client.get_reviewer(reviewer["id"],
                                                                 OFFICER))
        assert after_confirm["reviewer_status"] == "ON_ASSIGNMENT"

        # Clock (2026-08-01) is still before starts_on, so cancel is admissible.
        get_success_data(api_client.cancel_visit(visit["id"], OFFICER))
        after_cancel = get_success_data(api_client.get_reviewer(reviewer["id"],
                                                                OFFICER))
        assert after_cancel["reviewer_status"] == "AVAILABLE"


class TestActionItemLifecycle:
    def test_due_date_clamps_to_short_month(self, api):
        """PRD §3.6: "its `due_date` is computed by adding that many calendar
        months to the visit's `ends_on` — calendar-month addition preserves the
        day-of-month where possible and clamps to the last day of the target
        month when that month is shorter (so 2026-01-31 plus 1 month yields
        2026-02-28)."
        PRD §3.6: "for every finding with `severity` of `REQUIRED_ACTION` the
        server creates a `RequiredActionItem` in `OPEN` status".

        Design: Corner/calculations/action_item_due_date_month_clamp
        """
        ctx, item = setup_open_action_item()
        # visit ends_on 2026-08-31 + 6 months -> clamped to 2027-02-28 (2027 is
        # not a leap year)
        assert item["due_date"].startswith("2027-02-28"), \
            f"expected due_date 2027-02-28, got {item['due_date']!r}"
        assert item["status"] == "OPEN"
        assert item["follow_up_months"] == 6

    def test_overdue_boundary_at_due_date(self, api):
        """PRD §2.8: "an `OPEN` required action item whose `due_date` has passed
        moves to `OVERDUE`".
        PRD §3.6: "If the clock passes `due_date` with the item still `OPEN`, it
        moves automatically to `OVERDUE`."

        Design: Corner/cross_cutting_layers/rate_threshold_action_item_overdue_transition
        """
        ctx, item = setup_open_action_item()
        assert item["due_date"].startswith("2027-02-28")

        set_clock("2027-02-28T00:00:00Z")  # exactly at due_date: not yet passed
        at_due = get_success_data(api_client.get_action_item(item["id"], OFFICER))
        assert at_due["status"] == "OPEN"

        set_clock("2027-03-01T00:00:00Z")  # past due_date
        past_due = get_success_data(api_client.get_action_item(item["id"], OFFICER))
        assert past_due["status"] == "OVERDUE"

    def test_open_action_item_blocks_term_advance(self, api):
        """PRD §3.2: "The term advances `TERM_ACTIVE` → `INTERIM_MONITORING`
        only when every `RequiredActionItem` arising from the term's visit
        findings is `VERIFIED` or `WAIVED` and at least one `InterimReport`
        under the term has been `ACCEPTED`."

        Design: Corner/state_machines/bubble_up_all_action_items_resolved_allows_term_advance
        """
        ctx, item = setup_open_action_item()
        assert item["status"] == "OPEN"
        assert ctx["term"]["status"] == "TERM_ACTIVE"
        resp = api_client.advance_term(ctx["term"]["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

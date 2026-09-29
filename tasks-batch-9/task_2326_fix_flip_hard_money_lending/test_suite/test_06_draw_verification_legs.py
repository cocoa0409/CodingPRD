"""The two verification legs, the inspector calendar and the report array."""

import pytest

from test_helpers import (
    ApiErrorId,
    DrawRequestStatus,
    InspectionVisitStatus,
    VerificationMethod,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
    INSPECTOR,
    INSPECTOR_2,
    SERVICER,
)

BUFFER_CLOCK = "2026-08-25T09:00:00Z"
DRAW_CLOCK = "2026-09-01T12:00:00Z"
HELD_WINDOW = ("2026-09-01T09:00:00Z", "2026-09-01T11:00:00Z")
INSIDE_TRAILING_BUFFER = ("2026-09-01T12:29:00Z", "2026-09-01T14:29:00Z")
CLEAR_OF_TRAILING_BUFFER = ("2026-09-01T12:30:00Z", "2026-09-01T14:30:00Z")
INSIDE_LEADING_BUFFER = ("2026-09-01T05:31:00Z", "2026-09-01T07:31:00Z")
CLEAR_OF_LEADING_BUFFER = ("2026-09-01T05:30:00Z", "2026-09-01T07:30:00Z")


def _live_loan(**overrides):
    ctx = fixtures.build_closed_loan(**overrides)
    fixtures.cover_all_contractors(ctx)
    return ctx


def _order(draw_id, inspector_headers, window, headers=SERVICER):
    return api_client.create_inspection_visit(
        draw_id,
        factories.inspection_visit_payload(
            inspector_headers["X-User-ID"], window[0], window[1]
        ),
        headers,
    )


class TestVerificationLegsAreMutuallyExclusive:
    def test_the_photo_leg_reaches_inspected_in_one_hop_and_refuses_a_site_visit(self):
        """The fork is chosen at creation, so `SUBMITTED` alone does not decide legality.

        A photo request refuses inspection scheduling and then reaches `INSPECTED`
        without ever occupying `INSPECTION_ORDERED`, while the inspection request
        that supersedes it refuses photo verification and must take the two-hop
        path. The PRD states: "Verification splits into two legs, chosen by the
        request's `verification_method`, and a request may only travel the leg its
        method names — using the wrong leg is rejected with
        `ERR_VERIFICATION_METHOD_MISMATCH`."

        Design: Difficulty/non_linear_state_machine/draw_verification_branch_legs_are_mutually_exclusive
        """
        ctx = _live_loan()
        fixtures.set_clock(DRAW_CLOCK)
        electrical_id = ctx.line_by_code("ELECTRICAL")["id"]

        photo = fixtures.submit_draw(
            ctx, [(electrical_id, 0.33)], VerificationMethod.PHOTO.value
        )
        assert photo["verification_method"] == VerificationMethod.PHOTO.value
        validate_error(
            _order(photo["id"], INSPECTOR, HELD_WINDOW),
            ApiErrorId.VERIFICATION_METHOD_MISMATCH.value,
        )
        assert fixtures.read_draw_request(photo["id"])["status"] == (
            DrawRequestStatus.SUBMITTED.value
        )
        _, no_visits = validate_paginated(
            api_client.list_inspection_visits(photo["id"], SERVICER)
        )
        assert no_visits["total_count"] == 0, (
            "a refused order must not leave a visit row behind"
        )

        verified = fixtures.photo_verify(photo["id"], [(electrical_id, 0.30)], 3)
        assert verified["status"] == DrawRequestStatus.INSPECTED.value, (
            "the photo leg goes SUBMITTED to INSPECTED in one hop"
        )
        assert verified["photo_count"] == 3

        inspection = fixtures.submit_draw(
            ctx, [(electrical_id, 0.33)], VerificationMethod.INSPECTION.value
        )
        assert fixtures.read_draw_request(photo["id"])["status"] == (
            DrawRequestStatus.SUPERSEDED.value
        )
        assert inspection["sequence_number"] == 2

        validate_error(
            api_client.photo_verify_draw_request(
                inspection["id"],
                factories.photo_verification_payload(
                    [factories.line_verification(electrical_id, 0.30)], 3
                ),
                SERVICER,
            ),
            ApiErrorId.VERIFICATION_METHOD_MISMATCH.value,
        )
        stalled = fixtures.read_draw_request(inspection["id"])
        assert stalled["status"] == DrawRequestStatus.SUBMITTED.value
        assert stalled["photo_count"] is None

        ordered = validate_success(
            _order(inspection["id"], INSPECTOR, HELD_WINDOW), 201
        )
        assert ordered["status"] == InspectionVisitStatus.SCHEDULED.value
        assert fixtures.read_draw_request(inspection["id"])["status"] == (
            DrawRequestStatus.INSPECTION_ORDERED.value
        )

    def test_the_inspection_leg_must_occupy_both_hops_before_it_can_be_reviewed(self):
        """Underwriting is unreachable until the report lands, one hop after the order.

        The same request refuses review while `SUBMITTED` and again while
        `INSPECTION_ORDERED`, and only the filed report opens the door — so the
        second leg is genuinely two states long rather than a formality. The PRD
        states: "Re-reviewing a request that has already been funded, or reviewing
        one that is not `INSPECTED`, is rejected with
        `ERR_DRAW_REQUEST_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/draw_verification_branch_legs_are_mutually_exclusive
        """
        ctx = _live_loan()
        fixtures.set_clock(DRAW_CLOCK)
        electrical_id = ctx.line_by_code("ELECTRICAL")["id"]

        draw = fixtures.submit_draw(
            ctx, [(electrical_id, 0.30)], VerificationMethod.INSPECTION.value
        )
        validate_error(
            api_client.review_draw_request(
                draw["id"], factories.draw_review_payload(), SERVICER
            ),
            ApiErrorId.DRAW_REQUEST_STATE_INVALID.value,
        )
        validate_error(
            api_client.photo_verify_draw_request(
                draw["id"],
                factories.photo_verification_payload(
                    [factories.line_verification(electrical_id, 0.30)], 3
                ),
                SERVICER,
            ),
            ApiErrorId.VERIFICATION_METHOD_MISMATCH.value,
        )

        visit = fixtures.order_visit(
            draw["id"], INSPECTOR, HELD_WINDOW[0], HELD_WINDOW[1]
        )
        assert fixtures.read_draw_request(draw["id"])["status"] == (
            DrawRequestStatus.INSPECTION_ORDERED.value
        )
        validate_error(
            api_client.review_draw_request(
                draw["id"], factories.draw_review_payload(), SERVICER
            ),
            ApiErrorId.DRAW_REQUEST_STATE_INVALID.value,
        )

        fixtures.report_visit(visit["id"], [(electrical_id, 0.30)], INSPECTOR)
        assert fixtures.read_draw_request(draw["id"])["status"] == (
            DrawRequestStatus.INSPECTED.value
        )
        approved = fixtures.review_draw(draw["id"])
        assert approved["status"] == DrawRequestStatus.APPROVED.value
        assert approved["approved_release_cents"] == 675_000, (
            "the inspection leg withholds 10 percent, not 20"
        )


class TestInspectorCalendarSpansLoans:
    def test_the_travel_buffer_blocks_a_visit_on_another_loan_by_one_minute(self):
        """The contended calendar is the inspector's, not either loan's.

        A 09:00 to 11:00 visit on the first loan widens to a footprint ending at
        12:30, so a 12:29 start on a second loan is refused and a 12:30 start on
        the same boundary is accepted. The PRD states: "if that inspector already
        holds a `SCHEDULED` visit whose window, widened by a travel buffer of one
        and a half hours at both ends, overlaps the requested half-open window,
        the order is rejected with `ERR_INSPECTOR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/inspector_travel_buffer_spans_two_loans_at_the_minute
        """
        loan_a = _live_loan()
        loan_b = _live_loan(clock=None, property_overrides={"address_line": "42 Cholla Way"})
        fixtures.set_clock(BUFFER_CLOCK)

        draw_a = fixtures.submit_draw(
            loan_a, [(loan_a.line_by_code("ELECTRICAL")["id"], 0.30)]
        )
        held = fixtures.order_visit(
            draw_a["id"], INSPECTOR, HELD_WINDOW[0], HELD_WINDOW[1]
        )
        assert held["inspector_id"] == INSPECTOR["X-User-ID"]

        draw_b = fixtures.submit_draw(
            loan_b, [(loan_b.line_by_code("ELECTRICAL")["id"], 0.30)]
        )
        assert draw_b["loan_id"] != draw_a["loan_id"]

        validate_error(
            _order(draw_b["id"], INSPECTOR, INSIDE_TRAILING_BUFFER),
            ApiErrorId.INSPECTOR_WINDOW_CONFLICT.value,
        )
        assert fixtures.read_draw_request(draw_b["id"])["status"] == (
            DrawRequestStatus.SUBMITTED.value
        )
        _, none_yet = validate_paginated(
            api_client.list_inspection_visits(draw_b["id"], SERVICER)
        )
        assert none_yet["total_count"] == 0

        accepted = validate_success(
            _order(draw_b["id"], INSPECTOR, CLEAR_OF_TRAILING_BUFFER), 201
        )
        assert accepted["status"] == InspectionVisitStatus.SCHEDULED.value
        assert accepted["window_start"].startswith("2026-09-01T12:30:00")
        assert fixtures.read_draw_request(draw_b["id"])["status"] == (
            DrawRequestStatus.INSPECTION_ORDERED.value
        )
        assert fixtures.read_draw_request(draw_a["id"])["status"] == (
            DrawRequestStatus.INSPECTION_ORDERED.value
        )

    def test_the_buffer_is_applied_at_the_leading_end_as_well(self):
        """Widening happens at both ends, so an earlier visit is measured the same way.

        The held 09:00 window reaches back to 07:30, so a request ending at 07:31
        overlaps and is refused while one ending exactly at 07:30 does not,
        because the compared interval is half-open. The PRD states: "where the
        window is treated as half-open — inclusive of `window_start`, exclusive of
        `window_end` — and `window_end` must be strictly later than
        `window_start`."

        Design: Difficulty/resource_temporal_overlap/inspector_travel_buffer_spans_two_loans_at_the_minute
        """
        loan_a = _live_loan()
        loan_b = _live_loan(clock=None, property_overrides={"address_line": "42 Cholla Way"})
        fixtures.set_clock(BUFFER_CLOCK)

        draw_a = fixtures.submit_draw(
            loan_a, [(loan_a.line_by_code("ELECTRICAL")["id"], 0.30)]
        )
        fixtures.order_visit(draw_a["id"], INSPECTOR, HELD_WINDOW[0], HELD_WINDOW[1])

        draw_b = fixtures.submit_draw(
            loan_b, [(loan_b.line_by_code("ELECTRICAL")["id"], 0.30)]
        )
        validate_error(
            _order(draw_b["id"], INSPECTOR, INSIDE_LEADING_BUFFER),
            ApiErrorId.INSPECTOR_WINDOW_CONFLICT.value,
        )
        earlier = validate_success(
            _order(draw_b["id"], INSPECTOR, CLEAR_OF_LEADING_BUFFER), 201
        )
        assert earlier["status"] == InspectionVisitStatus.SCHEDULED.value
        assert earlier["window_end"].startswith("2026-09-01T07:30:00")


class TestVisitOrderPrecedence:
    def test_the_travel_buffer_rule_outranks_the_already_scheduled_rule(self):
        """One minute separates the two refusals on the very same request.

        Both attempts break the one-visit-per-request rule; only the 12:29 attempt
        also lands inside the held visit's buffered footprint, and it is the
        temporal refusal that answers. The PRD states: "A request that already has
        a `SCHEDULED` visit cannot have another ordered, and the attempt is
        rejected with `ERR_VISIT_ALREADY_SCHEDULED`."

        Design: Difficulty/priority_pair_validation_conflict/inspector_conflict_priority_18_beats_visit_already_scheduled_priority_22
        """
        ctx = _live_loan()
        fixtures.set_clock(BUFFER_CLOCK)
        draw = fixtures.submit_draw(ctx, [(ctx.line_by_code("ELECTRICAL")["id"], 0.30)])
        held = fixtures.order_visit(
            draw["id"], INSPECTOR, HELD_WINDOW[0], HELD_WINDOW[1]
        )

        validate_error(
            _order(draw["id"], INSPECTOR, INSIDE_TRAILING_BUFFER),
            ApiErrorId.INSPECTOR_WINDOW_CONFLICT.value,
        )
        validate_error(
            _order(draw["id"], INSPECTOR, CLEAR_OF_TRAILING_BUFFER),
            ApiErrorId.VISIT_ALREADY_SCHEDULED.value,
        )

        visits, meta = validate_paginated(
            api_client.list_inspection_visits(draw["id"], SERVICER)
        )
        assert meta["total_count"] == 1, (
            f"exactly one visit may exist, got {meta['total_count']}"
        )
        assert visits[0]["id"] == held["id"]
        assert visits[0]["status"] == InspectionVisitStatus.SCHEDULED.value
        assert visits[0]["window_start"].startswith("2026-09-01T09:00:00")

    def test_a_free_inspector_at_the_same_minute_reaches_the_lower_ranked_rule(self):
        """Swapping in an unbooked inspector removes the buffer breach and only.

        The 12:29 window that produced a calendar conflict for the booked
        inspector produces the already-scheduled refusal for a free one, so the
        first refusal really was the temporal rule winning a live conflict. The
        PRD states: "Ordering a visit moves the request `SUBMITTED →
        INSPECTION_ORDERED` and creates an `InspectionVisit` in `SCHEDULED` with
        `reported_at` and `site_notes` null."

        Design: Difficulty/priority_pair_validation_conflict/inspector_conflict_priority_18_beats_visit_already_scheduled_priority_22
        """
        ctx = _live_loan()
        fixtures.set_clock(BUFFER_CLOCK)
        draw = fixtures.submit_draw(ctx, [(ctx.line_by_code("ELECTRICAL")["id"], 0.30)])
        held = fixtures.order_visit(
            draw["id"], INSPECTOR, HELD_WINDOW[0], HELD_WINDOW[1]
        )
        assert held["reported_at"] is None
        assert held["site_notes"] is None

        validate_error(
            _order(draw["id"], INSPECTOR_2, INSIDE_TRAILING_BUFFER),
            ApiErrorId.VISIT_ALREADY_SCHEDULED.value,
        )
        _, meta = validate_paginated(
            api_client.list_inspection_visits(draw["id"], SERVICER)
        )
        assert meta["total_count"] == 1


class TestPhotoLegRefusals:
    def test_the_photo_leg_has_its_own_four_refusals(self):
        """Wrong leg both ways, the request ceiling, and the per-allocation photo floor.

        Intake does not police the photo ceiling, so a 4,800,000 photo request is
        created and then refused at verification; a one-line request under the
        ceiling still needs three photos, and the accepted photo release comes out
        below what the inspection leg would have paid. The PRD states: "The
        request's `requested_total_cents` may not exceed thirty thousand dollars —
        three million cents — and a larger photo draw is rejected with
        `ERR_PHOTO_REQUEST_TOO_LARGE`."

        Design: Corner/errors/the_photo_leg_has_its_own_four_refusals
        """
        ctx = _live_loan()
        fixtures.set_clock(DRAW_CLOCK)
        roof_id = ctx.line_by_code("ROOF")["id"]
        kitchen_id = ctx.line_by_code("KITCHEN")["id"]
        electrical_id = ctx.line_by_code("ELECTRICAL")["id"]
        all_three = [(roof_id, 0.60), (kitchen_id, 0.45), (electrical_id, 0.33)]

        inspection = fixtures.submit_draw(
            ctx, all_three, VerificationMethod.INSPECTION.value
        )
        validate_error(
            api_client.photo_verify_draw_request(
                inspection["id"],
                factories.photo_verification_payload(
                    [
                        factories.line_verification(line_id, pct)
                        for line_id, pct in all_three
                    ],
                    9,
                ),
                SERVICER,
            ),
            ApiErrorId.VERIFICATION_METHOD_MISMATCH.value,
        )

        oversized = fixtures.submit_draw(
            ctx, all_three, VerificationMethod.PHOTO.value
        )
        assert oversized["requested_total_cents"] == 4_800_000, (
            "intake does not police the photo ceiling"
        )
        assert fixtures.read_draw_request(inspection["id"])["status"] == (
            DrawRequestStatus.SUPERSEDED.value
        )
        validate_error(
            api_client.photo_verify_draw_request(
                oversized["id"],
                factories.photo_verification_payload(
                    [
                        factories.line_verification(line_id, pct)
                        for line_id, pct in all_three
                    ],
                    9,
                ),
                SERVICER,
            ),
            ApiErrorId.PHOTO_REQUEST_TOO_LARGE.value,
        )
        validate_error(
            _order(oversized["id"], INSPECTOR, HELD_WINDOW),
            ApiErrorId.VERIFICATION_METHOD_MISMATCH.value,
        )
        _, no_visits = validate_paginated(
            api_client.list_inspection_visits(oversized["id"], SERVICER)
        )
        assert no_visits["total_count"] == 0

        small = fixtures.submit_draw(
            ctx, [(electrical_id, 0.33)], VerificationMethod.PHOTO.value
        )
        assert small["requested_total_cents"] == 825_000
        assert fixtures.read_draw_request(oversized["id"])["status"] == (
            DrawRequestStatus.SUPERSEDED.value
        )
        validate_error(
            api_client.photo_verify_draw_request(
                small["id"],
                factories.photo_verification_payload(
                    [factories.line_verification(electrical_id, 0.30)], 2
                ),
                SERVICER,
            ),
            ApiErrorId.INSUFFICIENT_PHOTO_EVIDENCE.value,
        )
        verified = fixtures.photo_verify(small["id"], [(electrical_id, 0.30)], 3)
        assert verified["status"] == DrawRequestStatus.INSPECTED.value
        assert verified["photo_count"] == 3

        approved = fixtures.review_draw(small["id"])
        assert approved["approved_release_cents"] == 600_000, (
            "the photo leg withholds 20 percent where the inspection leg withholds 10"
        )


class TestPhotoReleaseConstants:
    def test_the_photo_leg_selects_the_photo_retainage_and_cap(self):
        """`verification_method` at intake decides which constant set the release uses.

        On the same scope line at the same percentages the photo leg releases
        600,000 against the 675,000 the inspection leg would have produced, and
        the effective completion is the smallest of claimed, verified and the 0.50
        ceiling. The PRD states: "it stores `photo_count`, sets
        `verified_percent_complete` on every allocation, and computes each
        `effective_percent_complete` as the smallest of the claimed figure, the
        verified figure and a photo ceiling of 0.50."

        Design: Corner/calculations/the_photo_leg_selects_the_photo_retainage_and_cap
        """
        ctx = _live_loan()
        electrical_id = ctx.line_by_code("ELECTRICAL")["id"]

        draw = fixtures.submit_draw(
            ctx, [(electrical_id, 0.33)], VerificationMethod.PHOTO.value
        )
        assert draw["requested_total_cents"] == 825_000
        assert draw["verification_method"] == VerificationMethod.PHOTO.value

        verified = fixtures.photo_verify(draw["id"], [(electrical_id, 0.30)], 3)
        assert verified["photo_count"] == 3
        rows, meta = validate_paginated(
            api_client.list_draw_line_items(SERVICER, {"draw_request_id": draw["id"]})
        )
        assert meta["total_count"] == 1
        allocation = rows[0]
        assert allocation["claimed_percent_complete"] == pytest.approx(0.33)
        assert allocation["verified_percent_complete"] == pytest.approx(0.30)
        assert allocation["effective_percent_complete"] == pytest.approx(0.30)

        approved = fixtures.review_draw(draw["id"])
        assert approved["approved_release_cents"] == 600_000
        assert ctx.refresh_loan()["reserved_release_cents"] == 600_000

        funded = fixtures.fund_draw(draw["id"], funding_date="2026-08-10")
        assert funded["status"] == DrawRequestStatus.FUNDED.value
        line = fixtures.read_line(electrical_id)
        assert line["released_cents"] == 600_000
        assert float(line["released_percent"]) == pytest.approx(0.24)

        loan = ctx.refresh_loan()
        assert loan["funded_principal_cents"] == 13_751_375
        assert loan["undisbursed_holdback_cents"] == 9_400_000
        assert loan["reserved_release_cents"] == 0
        assert loan["commitment_balance_check_cents"] == 0


class TestInspectionReportGate:
    def _scheduled_report(self):
        ctx = _live_loan()
        fixtures.set_clock(DRAW_CLOCK)
        lines = {
            code: ctx.line_by_code(code)["id"]
            for code in ("ROOF", "KITCHEN", "ELECTRICAL")
        }
        draw = fixtures.submit_draw(
            ctx,
            [(lines["ROOF"], 0.60), (lines["KITCHEN"], 0.45), (lines["ELECTRICAL"], 0.33)],
        )
        visit = fixtures.order_visit(
            draw["id"], INSPECTOR, HELD_WINDOW[0], HELD_WINDOW[1]
        )
        return ctx, lines, draw, visit

    def test_an_incomplete_or_unassigned_inspection_report_is_refused(self):
        """The cover is exact, and only the assigned inspector may file it.

        A different inspector is refused on identity before the payload is read;
        a two-of-three array and a three-entry array covering only two distinct
        lines are both incomplete; the exact cover then completes the visit and
        writes every effective percentage. The PRD states: "The array must cover
        every allocation of the request exactly once — no gaps and no repeats —
        and any other shape is rejected with `ERR_LINE_VERIFICATION_INCOMPLETE`".

        Design: Corner/validations/an_incomplete_or_unassigned_inspection_report_is_refused
        """
        ctx, lines, draw, visit = self._scheduled_report()
        complete = [
            factories.line_verification(lines["ROOF"], 0.50),
            factories.line_verification(lines["KITCHEN"], 0.45),
            factories.line_verification(lines["ELECTRICAL"], 0.30),
        ]

        validate_error(
            api_client.report_inspection_visit(
                visit["id"],
                factories.inspection_report_payload(complete),
                INSPECTOR_2,
            ),
            ApiErrorId.NOT_ASSIGNED_INSPECTOR.value,
            403,
        )
        validate_error(
            api_client.report_inspection_visit(
                visit["id"],
                factories.inspection_report_payload(complete[:2]),
                INSPECTOR,
            ),
            ApiErrorId.LINE_VERIFICATION_INCOMPLETE.value,
        )
        validate_error(
            api_client.report_inspection_visit(
                visit["id"],
                factories.inspection_report_payload(
                    [
                        factories.line_verification(lines["ROOF"], 0.50),
                        factories.line_verification(lines["ROOF"], 0.55),
                        factories.line_verification(lines["KITCHEN"], 0.45),
                    ]
                ),
                INSPECTOR,
            ),
            ApiErrorId.LINE_VERIFICATION_INCOMPLETE.value,
        )

        assert fixtures.read_draw_request(draw["id"])["status"] == (
            DrawRequestStatus.INSPECTION_ORDERED.value
        )
        pending, _ = validate_paginated(
            api_client.list_inspection_visits(draw["id"], SERVICER)
        )
        assert pending[0]["status"] == InspectionVisitStatus.SCHEDULED.value, (
            "a rejected report leaves no partial verification behind"
        )

        reported = validate_success(
            api_client.report_inspection_visit(
                visit["id"], factories.inspection_report_payload(complete), INSPECTOR
            ),
            200,
        )
        assert reported["status"] == InspectionVisitStatus.COMPLETED.value
        assert reported["reported_at"].startswith("2026-09-01T12:00:00")
        assert fixtures.read_draw_request(draw["id"])["status"] == (
            DrawRequestStatus.INSPECTED.value
        )

        rows, meta = validate_paginated(
            api_client.list_draw_line_items(SERVICER, {"draw_request_id": draw["id"]})
        )
        assert meta["total_count"] == 3
        by_line = {row["rehab_line_item_id"]: row for row in rows}
        assert by_line[lines["ROOF"]]["verified_percent_complete"] == pytest.approx(0.50)
        assert by_line[lines["ROOF"]]["effective_percent_complete"] == pytest.approx(0.50)
        assert by_line[lines["KITCHEN"]]["effective_percent_complete"] == pytest.approx(0.45)
        assert by_line[lines["ELECTRICAL"]]["effective_percent_complete"] == pytest.approx(0.30)

    def test_an_array_write_is_all_or_nothing_across_its_elements(self):
        """One bad element rejects the whole array; the good siblings are not written.

        A verified figure of 1.10 is out of range, so nothing at all is applied and
        the retry writes all three percentages from scratch in one atomic step. The
        PRD states: "Each entry in `line_verifications` names a
        `rehab_line_item_id` and the `verified_percent_complete` the inspector
        observed, carried to two decimals as a cumulative figure."

        Design: Corner/endpoints/an_array_write_is_all_or_nothing_across_its_elements
        """
        ctx, lines, draw, visit = self._scheduled_report()
        before, _ = validate_paginated(
            api_client.list_draw_line_items(SERVICER, {"draw_request_id": draw["id"]})
        )
        assert all(row["verified_percent_complete"] is None for row in before)

        validate_error(
            api_client.report_inspection_visit(
                visit["id"],
                factories.inspection_report_payload(
                    [
                        factories.line_verification(lines["ROOF"], 0.50),
                        factories.line_verification(lines["KITCHEN"], 1.10),
                        factories.line_verification(lines["ELECTRICAL"], 0.30),
                    ]
                ),
                INSPECTOR,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        after_failure, _ = validate_paginated(
            api_client.list_draw_line_items(SERVICER, {"draw_request_id": draw["id"]})
        )
        for row in after_failure:
            assert row["verified_percent_complete"] is None, (
                "the well-formed entries of a rejected array must not be applied"
            )
            assert row["effective_percent_complete"] is None
        pending, _ = validate_paginated(
            api_client.list_inspection_visits(draw["id"], SERVICER)
        )
        assert pending[0]["status"] == InspectionVisitStatus.SCHEDULED.value, (
            "the rejected array did not half-close the visit"
        )

        fixtures.report_visit(
            visit["id"],
            [
                (lines["ROOF"], 0.50),
                (lines["KITCHEN"], 0.45),
                (lines["ELECTRICAL"], 0.30),
            ],
            INSPECTOR,
        )
        after_retry, _ = validate_paginated(
            api_client.list_draw_line_items(SERVICER, {"draw_request_id": draw["id"]})
        )
        written = {
            row["rehab_line_item_id"]: row["verified_percent_complete"]
            for row in after_retry
        }
        assert written[lines["ROOF"]] == pytest.approx(0.50)
        assert written[lines["KITCHEN"]] == pytest.approx(0.45)
        assert written[lines["ELECTRICAL"]] == pytest.approx(0.30)
        assert fixtures.read_draw_request(draw["id"])["status"] == (
            DrawRequestStatus.INSPECTED.value
        )

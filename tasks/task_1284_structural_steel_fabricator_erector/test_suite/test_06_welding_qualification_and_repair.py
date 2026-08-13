"""Welder qualification/continuity, half-open window overlap, and the weld
repair loop with its two-repair limit."""
from test_helpers import (
    ADMIN,
    FOREMAN,
    QC,
    ApiErrorId,
    api_client,
    create_in_shop_piece,
    create_welder,
    create_weld_payload,
    fail_weld_visual,
    log_weld,
    make_welder_headers,
    pass_weld_visual,
    repair_weld,
    schedule_weld_inspection,
    set_clock,
    setup_fabrication_ready,
    submit_inspection,
    validate_error,
    validate_success,
)


class TestWelderContinuity:

    def test_welder_continuity_lapse_blocks_weld(self):
        """PRD section 3.5: "A welder is qualified for a weld exactly when all
        of the following hold: the welder is `ACTIVE`; the weld's `process`
        equals the welder's `qual_process`; the current logical date is on or
        before `qual_expires_on`; and the welder's continuity in that process
        is intact — either the welder has no prior weld in that process at all,
        or the most recent such prior weld's `weld_date` is no earlier than 183
        days before the current logical date."
        PRD section 3.5: "Qualification is checked at log time against the
        logical clock, and any failure is rejected with
        `ERR_WELDER_NOT_QUALIFIED`."

        Design: Corner/calculations/welder_continuity_lapse_blocks_weld
        """
        ctx = setup_fabrication_ready("Job CC")
        piece = create_in_shop_piece(ctx, "P1", 800)
        welder = create_welder("Weld Six")
        # Prior FCAW weld dated 2026-01-15; the default clock reads
        # 2026-08-01, which is 198 days later — beyond the 183-day window.
        log_weld(piece["id"], welder["id"], weld_date="2026-01-15",
                 window_start="2026-01-15T09:00:00Z",
                 window_end="2026-01-15T10:00:00Z")
        resp = api_client.create_weld(
            create_weld_payload(piece["id"], welder["id"]),
            make_welder_headers(welder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WELDER_NOT_QUALIFIED)


class TestWelderWindowOverlap:

    def _welder_with_morning_weld(self, job_name="Job W2"):
        ctx = setup_fabrication_ready(job_name)
        piece = create_in_shop_piece(ctx, "W2-P1", 800)
        welder = create_welder("Weld Three")
        log_weld(piece["id"], welder["id"],
                 window_start="2026-08-01T09:00:00Z",
                 window_end="2026-08-01T11:00:00Z")
        return ctx, piece, welder

    def test_overlapping_window_rejected(self):
        """PRD section 3.5: "A new weld conflicts with an existing weld of the
        same welder whenever their windows genuinely overlap — unless the new
        window ends at or before the existing window's start, or begins at or
        after the existing window's end."
        PRD section 3.5: "A genuine overlap is rejected with
        `ERR_WELDER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/welder_window_half_open_overlap
        """
        _ctx, piece, welder = self._welder_with_morning_weld()
        resp = api_client.create_weld(
            create_weld_payload(
                piece["id"], welder["id"],
                window_start="2026-08-01T10:30:00Z",
                window_end="2026-08-01T12:00:00Z",
            ),
            make_welder_headers(welder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WELDER_DOUBLE_BOOKED)

    def test_adjacent_window_allowed_half_open(self):
        """PRD section 3.5: "The arithmetic is half-open: a weld starting at
        exactly the moment another ends is allowed, as is one ending exactly
        when another begins."

        Design: Difficulty/resource_temporal_overlap/welder_window_half_open_overlap
        """
        _ctx, piece, welder = self._welder_with_morning_weld()
        resp = api_client.create_weld(
            create_weld_payload(
                piece["id"], welder["id"],
                window_start="2026-08-01T11:00:00Z",
                window_end="2026-08-01T12:00:00Z",
            ),
            make_welder_headers(welder["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "WELDED", (
            f"a weld starting exactly when another ends must be allowed, "
            f"got {data['status']}"
        )


class TestSafetyBeforeConstraint:

    def test_expired_qualification_reports_safety_error(self):
        """PRD section 2.8: "Every request walks a fixed ladder of checks, and
        the first failing rung produces the response — later rungs are never
        evaluated."
        PRD section 2.8 (rung 7): "Safety and segregation. Welder qualification
        and continuity on weld logging (`ERR_WELDER_NOT_QUALIFIED`), drawing
        self-approval on drawing decisions (`ERR_SELF_APPROVAL_FORBIDDEN`),
        weld-inspector segregation on weld inspection submission
        (`ERR_SEGREGATION_OF_DUTIES`), and the AISC audit hold on load shipment
        (`ERR_AISC_HOLD_ACTIVE`)."
        PRD section 3.5: "A welder is qualified for a weld exactly when all of
        the following hold: the welder is `ACTIVE`; the weld's `process` equals
        the welder's `qual_process`; the current logical date is on or before
        `qual_expires_on`; and the welder's continuity in that process is
        intact".

        Design: Difficulty/priority_pair_validation_conflict/weld_safety_over_double_booking
        """
        ctx = setup_fabrication_ready("Job U")
        piece = create_in_shop_piece(ctx, "U-P1", 800)
        welder = create_welder("Weld Two", qual_expires_on="2026-08-10")
        log_weld(piece["id"], welder["id"],
                 window_start="2026-08-01T09:00:00Z",
                 window_end="2026-08-01T11:00:00Z")
        # Advance the logical clock past the qualification expiry.
        set_clock("2026-08-20T00:00:00Z")
        resp = api_client.create_weld(
            create_weld_payload(
                piece["id"], welder["id"],
                weld_date="2026-08-20",
                window_start="2026-08-20T10:00:00Z",
                window_end="2026-08-20T12:00:00Z",
            ),
            make_welder_headers(welder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WELDER_NOT_QUALIFIED)

    def test_suspended_welder_reports_safety_error_even_when_double_booked(self):
        """PRD section 2.8: "Every request walks a fixed ladder of checks, and
        the first failing rung produces the response — later rungs are never
        evaluated."
        PRD section 2.8: rung 7 covers "Welder qualification and continuity on
        weld logging (`ERR_WELDER_NOT_QUALIFIED`)" while rung 9 covers
        "scheduling and capacity rules (`ERR_WELDER_DOUBLE_BOOKED`,
        `ERR_LAYDOWN_SLOT_CONFLICT`, `ERR_LOAD_OVERWEIGHT`)".
        PRD section 3.5: "A welder is qualified for a weld exactly when all of
        the following hold: the welder is `ACTIVE`".

        Design: Difficulty/priority_pair_validation_conflict/weld_safety_over_double_booking
        """
        ctx = setup_fabrication_ready("Job U2")
        piece = create_in_shop_piece(ctx, "U-P1", 800)
        welder = create_welder("Weld Two")
        log_weld(piece["id"], welder["id"],
                 window_start="2026-08-01T09:00:00Z",
                 window_end="2026-08-01T11:00:00Z")
        api_client.suspend_welder(welder["id"], ADMIN)
        # The new window genuinely overlaps 09:00-11:00, but qualification
        # (the earlier rung) must be the reported failure.
        resp = api_client.create_weld(
            create_weld_payload(
                piece["id"], welder["id"],
                window_start="2026-08-01T10:30:00Z",
                window_end="2026-08-01T12:00:00Z",
            ),
            make_welder_headers(welder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WELDER_NOT_QUALIFIED)


class TestWeldRepairLoop:

    def test_repair_returns_rejected_weld_to_welded(self):
        """PRD section 3.5: "Repairing moves a weld from `VISUAL_REJECTED` or
        `NDT_REJECTED` back to `WELDED`, ready to be re-inspected from the
        visual stage onward."
        PRD section 3.5: "Each successful repair increments `repair_count` by
        one."

        Design: Difficulty/non_linear_state_machine/weld_repair_loop
        """
        ctx = setup_fabrication_ready("Job K")
        piece = create_in_shop_piece(ctx, "K-P1", 800)
        welder = create_welder("Weld One")
        weld = log_weld(piece["id"], welder["id"])
        fail_weld_visual(ctx["job"]["id"], weld["id"])

        rejected = validate_success(api_client.get_weld(weld["id"], FOREMAN))
        assert rejected["status"] == "VISUAL_REJECTED"

        repaired = repair_weld(weld["id"], welder["id"])
        assert repaired["status"] == "WELDED", (
            f"repair must loop the weld back to WELDED, "
            f"got {repaired['status']}"
        )
        assert repaired["repair_count"] == 1, \
            f"repair_count must increment to 1, got {repaired['repair_count']}"

    def test_repaired_weld_passes_visual_on_retry(self):
        """PRD section 3.5: "Repairing moves a weld from `VISUAL_REJECTED` or
        `NDT_REJECTED` back to `WELDED`, ready to be re-inspected from the
        visual stage onward."
        PRD section 3.6: "A passed `WELD_VISUAL` inspection moves its weld from
        `WELDED` to `VISUAL_PASSED`; a failed one moves it from `WELDED` to
        `VISUAL_REJECTED`."

        Design: Difficulty/non_linear_state_machine/weld_repair_loop
        """
        ctx = setup_fabrication_ready("Job K2")
        piece = create_in_shop_piece(ctx, "K-P1", 800)
        welder = create_welder("Weld One")
        weld = log_weld(piece["id"], welder["id"])
        fail_weld_visual(ctx["job"]["id"], weld["id"])
        repair_weld(weld["id"], welder["id"])
        pass_weld_visual(ctx["job"]["id"], weld["id"])
        after = validate_success(api_client.get_weld(weld["id"], FOREMAN))
        assert after["status"] == "VISUAL_PASSED", (
            f"the repaired weld must pass visual on the second attempt, "
            f"got {after['status']}"
        )


class TestWeldRepairLimit:

    def test_weld_repair_limit_boundary(self):
        """PRD section 3.5: "Two guards apply: the repair is rejected with
        `ERR_WELD_REPAIR_LIMIT` once the weld's `repair_count` has reached 2
        (repairs at counts zero and one proceed), and only the welder who
        performed the weld may repair it — the caller's `X-User-ID` must equal
        the weld's `welder_id`, or the request fails `ERR_FORBIDDEN`."

        Design: Corner/calculations/weld_repair_limit_boundary
        """
        ctx = setup_fabrication_ready("Job CR")
        piece = create_in_shop_piece(ctx, "P1", 800)
        welder = create_welder("Weld Seven")
        weld = log_weld(piece["id"], welder["id"])

        fail_weld_visual(ctx["job"]["id"], weld["id"])
        repair_weld(weld["id"], welder["id"])  # repair_count 1
        fail_weld_visual(ctx["job"]["id"], weld["id"])
        second = repair_weld(weld["id"], welder["id"])  # repair_count 2
        assert second["repair_count"] == 2, \
            f"the second repair must leave repair_count at 2, got {second['repair_count']}"
        fail_weld_visual(ctx["job"]["id"], weld["id"])

        resp = api_client.repair_weld(weld["id"], make_welder_headers(welder["id"]))
        validate_error(resp, ApiErrorId.ERR_WELD_REPAIR_LIMIT)
        after = validate_success(api_client.get_weld(weld["id"], FOREMAN))
        assert after["status"] == "VISUAL_REJECTED", \
            "a rejected repair must leave the weld VISUAL_REJECTED"
        assert after["repair_count"] == 2

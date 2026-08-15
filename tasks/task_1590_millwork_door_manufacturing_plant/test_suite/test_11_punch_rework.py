"""Punch-list reporting, triage, rework authorization cascade, and the rework loop."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error, get_success_data,
    make_project, make_roll, make_batch, advance_batch, measure_batch,
    report_punch, triage_punch, authorize_rework, verify_punch, reject_punch,
    begin_rework, resolve_punch, accept_opening, issue_labels, apply_labels,
    verify_labels, stage_opening, set_order_status,
    get_opening, get_punch, get_roll, get_allocation,
    setup_delivered_opening, setup_rated_delivered_opening,
    setup_order_finishing, H,
    assert_roll_serial_conservation,
)

PM_H = TEST_USERS["plant_manager_headers"]
PL_H = TEST_USERS["production_lead_headers"]
ANY_H = TEST_USERS["any_headers"]

_UNRATED = dict(species="PAINT_GRADE", profile_code="PR-1", finish_system="PAINT",
                sheen_target="MATTE", hardware_prep_mode="INSTALLER_PREP",
                fire_rating_required="NONE")

_RATED = dict(species="MAPLE", profile_code="PR-7", finish_system="STAIN",
              sheen_target="SATIN", hardware_prep_mode="TEMPLATE_PREP",
              fire_rating_required="MIN_20", template_code="T-R1",
              template_fire_rated=True)


def _delivered_unrated(contract_code, order_code, machine_code, booth_code, trip_code):
    return setup_delivered_opening(
        contract_code=contract_code, order_code=order_code,
        openings=({"opening_no": "P1", "leaf_count": 1, "fire_rating": "NONE",
                   "required_on_site_date": "2026-10-05"},),
        machine_code=machine_code, machine_species=["PAINT_GRADE"],
        booth_code=booth_code, measured_gu=15, cure_start=8, cure_end=12,
        slot_start=6, slot_end=8, estimated_minutes=30,
        trip_code=trip_code, truck_capacity_leaves=4,
        departure_date="2026-10-02", site_arrival_date="2026-10-04",
        **_UNRATED,
    )


def _delivered_rated_with_label(contract_code, order_code, machine_code, booth_code,
                                trip_code, roll_capacity=2, series="UL_20MIN"):
    return setup_rated_delivered_opening(
        contract_code=contract_code, order_code=order_code,
        openings=({"opening_no": "R1", "leaf_count": 1, "fire_rating": "MIN_20",
                   "required_on_site_date": "2026-10-10"},),
        machine_code=machine_code, machine_species=["MAPLE"],
        booth_code=booth_code, measured_gu=35, cure_start=10, cure_end=16,
        slot_start=8, slot_end=10, estimated_minutes=60,
        roll_series=series, roll_capacity=roll_capacity,
        trip_code=trip_code, truck_capacity_leaves=5,
        departure_date="2026-10-08", site_arrival_date="2026-10-10",
        **_RATED,
    )


class TestPunchReporting:
    def test_punch_report_moves_opening_to_punch_listed(self, api):
        """PRD §3.8: "Reporting requires the opening's shipping axis to be
        `DELIVERED` or `PUNCH_LISTED` (`ERR_OPENING_NOT_DELIVERED`). The report
        is created in `REPORTED` status with the acting user captured as
        `reported_by`, and the first report on a `DELIVERED` opening moves that
        opening's shipping axis from `DELIVERED` to `PUNCH_LISTED`."

        Design: Corner/state_machines/punch_report_moves_opening_to_punch_listed
        """
        from test_helpers import setup_openings_staged, make_trip, assign, set_trip_status
        ctx = setup_openings_staged(
            contract_code="CS-9", order_code="O-P9",
            openings=({"opening_no": "P1", "leaf_count": 1, "fire_rating": "NONE",
                       "required_on_site_date": "2026-10-05"},),
            machine_code="M-P9", machine_species=["PAINT_GRADE"],
            booth_code="B-P9", measured_gu=15, cure_start=8, cure_end=12,
            slot_start=6, slot_end=8, estimated_minutes=30, **_UNRATED,
        )
        opening = ctx["openings"][0]
        trip = make_trip(ctx["project"]["id"], trip_code="T-P9", truck_capacity_leaves=4,
                         departure_date="2026-10-02", site_arrival_date="2026-10-04")
        assign(trip["id"], opening["id"])
        trip = set_trip_status(trip["id"], "DEPARTED")
        assert get_opening(opening["id"])["ship_status"] == "SHIPPED"

        # Reported while SHIPPED (trip DEPARTED, not yet DELIVERED).
        resp = api.create_punch_item(
            {"opening_id": opening["id"], "category": "TRANSIT_DAMAGE", "severity": "MINOR",
             "description": "early report attempt"}, H("QAInspector", "qa-1"),
        )
        validate_error(resp, ApiErrorId.ERR_OPENING_NOT_DELIVERED, 409)

        # After arrival the first report flips the axis.
        set_trip_status(trip["id"], "DELIVERED")
        punch1 = report_punch(opening["id"], category="TRANSIT_DAMAGE", severity="MINOR",
                              description="edge dent", role="Architect", user_id="arch-9")
        assert punch1["status"] == "REPORTED"
        assert punch1["reported_by"] == "arch-9"
        assert get_opening(opening["id"])["ship_status"] == "PUNCH_LISTED"

        # A second report is accepted and the axis stays PUNCH_LISTED.
        punch2 = report_punch(opening["id"], category="FINISH_DEFECT", severity="MAJOR",
                              description="drips", role="QAInspector", user_id="qa-2")
        assert punch2["status"] == "REPORTED"
        assert get_opening(opening["id"])["ship_status"] == "PUNCH_LISTED"


class TestMinorPunchPath:
    def test_minor_punch_direct_resolve_path(self, api):
        """PRD §3.8: "Resolving anything else fails with
        `ERR_PUNCH_NOT_RESOLVABLE`: the resolve capability requires either a
        triaged minor item or an in-rework item with no linked batch." and
        "a `PlantManager` moves a `TRIAGED` item to `REWORK_AUTHORIZED` only
        when its `severity` is `MAJOR`, failing otherwise with
        `ERR_PUNCH_NOT_MAJOR`." and "`VERIFIED` and `REJECTED_INVALID` are
        terminal, and undeclared punch pairs — reporting straight to
        `VERIFIED`, for instance — fail with `ERR_INVALID_PUNCH_STATUS_TRANSITION`."

        Design: Corner/state_machines/minor_punch_direct_resolve_path
        """
        ctx = _delivered_unrated("CS-10", "O-M10", "M-M10", "B-M10", "T-M10")
        opening = ctx["openings"][0]
        punch = report_punch(opening["id"], category="HARDWARE_MISALIGNMENT",
                             severity="MINOR", description="hinge screw proud",
                             role="QAInspector", user_id="qa-3")

        # REPORTED -> VERIFIED is an undeclared pair.
        resp = api.set_punch_item_status(punch["id"], {"target_status": "VERIFIED"},
                                         H("QAInspector", "qa-4"))
        validate_error(resp, ApiErrorId.ERR_INVALID_PUNCH_STATUS_TRANSITION, 409)

        triage_punch(punch["id"], user_id="qa-4")

        # Authorizing rework on a MINOR item fails.
        resp = api.set_punch_item_status(punch["id"], {"target_status": "REWORK_AUTHORIZED"}, PM_H)
        validate_error(resp, ApiErrorId.ERR_PUNCH_NOT_MAJOR, 409)

        # The MINOR direct-resolve branch from TRIAGED.
        resolved = resolve_punch(punch["id"])
        assert resolved["status"] == "RESOLVED"

        # The triage-reject branch, and terminal lockdown of REJECTED_INVALID.
        punch2 = report_punch(opening["id"], category="LABEL_MISSING", severity="MINOR",
                              description="unsubstantiated claim", role="Architect",
                              user_id="arch-9")
        triage_punch(punch2["id"], user_id="qa-4")
        rejected = reject_punch(punch2["id"], user_id="qa-4")
        assert rejected["status"] == "REJECTED_INVALID"
        resp = api.set_punch_item_status(punch2["id"], {"target_status": "TRIAGED"},
                                         H("QAInspector", "qa-4"))
        validate_error(resp, ApiErrorId.ERR_INVALID_PUNCH_STATUS_TRANSITION, 409)


class TestPunchReworkCascade:
    def _setup_authorized(self, contract_code):
        """Rated opening DELIVERED with a VERIFIED label; MAJOR punch TRIAGED."""
        ctx = _delivered_rated_with_label(contract_code, "O-5002", "M-R", "B-R", "T-R",
                                          roll_capacity=2)
        opening = ctx["openings"][0]
        punch = report_punch(opening["id"], category="FINISH_DEFECT", severity="MAJOR",
                             description="sheen burn-through at rail", role="QAInspector",
                             user_id="qa-9")
        triage_punch(punch["id"], user_id="qa-1")
        return ctx, punch

    def test_rework_authorization_reworks_opening_and_voids_label(self, api):
        """PRD §3.8: "Authorization cascades hard: the opening's fabrication
        axis falls back from `FINISHED`, `LABELED`, or `STAGED` to `REWORK`,
        and the opening's label allocations in `APPLIED` or `VERIFIED` are
        voided per §3.6, their serials passing from applied to spoiled on each
        roll with the roll's `version` bumped."

        Design: Difficulty/transitive_cascade/punch_rework_relabel_cascade
        """
        ctx, punch = self._setup_authorized("C-5002")
        opening = ctx["openings"][0]
        alloc = ctx["allocation"]
        roll = ctx["roll"]
        assert get_opening(opening["id"])["fab_status"] == "STAGED"

        authorize_rework(punch["id"])

        opening_after = get_opening(opening["id"])
        assert opening_after["fab_status"] == "REWORK"
        assert opening_after["ship_status"] == "PUNCH_LISTED"
        assert get_allocation(alloc["id"])["status"] == "VOIDED", (
            "the VERIFIED label is destroyed by the rework authorization"
        )
        _ = roll

    def test_rework_authorization_rewrites_roll_accounting(self, api):
        """PRD §2.9: "Every serial on a roll is accounted for at all times: the
        counts of issued, applied, spoiled, and available serials always sum to
        the roll's `serial_capacity`, and a spoiled serial is never returned to
        the available pool." PRD §3.8: "their serials passing from applied to
        spoiled on each roll with the roll's `version` bumped."

        Design: Difficulty/transitive_cascade/punch_rework_relabel_cascade
        """
        ctx, punch = self._setup_authorized("C-5002B")
        roll_before = get_roll(ctx["roll"]["id"])
        assert roll_before["serials_applied"] == 1
        assert roll_before["serials_spoiled"] == 0

        authorize_rework(punch["id"])

        roll_after = get_roll(ctx["roll"]["id"])
        assert roll_after["serials_applied"] == 0, "applied serials move out"
        assert roll_after["serials_spoiled"] == 1, "...into spoiled (never returned)"
        assert roll_after["serials_issued"] == 0
        assert roll_after["serials_available"] == 1
        assert_roll_serial_conservation(roll_after)
        assert roll_after["version"] == roll_before["version"] + 1, "roll version bumped"


class TestPunchReworkFullLoop:
    def test_punch_rework_full_loop_gates(self, api):
        """PRD §3.8: "Two checks run in a fixed order: when a `rework_batch_id`
        is supplied, its batch's order must equal the punch opening's order
        (`ERR_REWORK_BATCH_ORDER_MISMATCH`, checked first); and for a
        `FINISH_DEFECT` item the `rework_batch_id` is mandatory and must name a
        batch whose `is_rework_batch` is true and whose status is `MIXED`,
        `SPRAYED`, or `CURED` — a missing batch id on a finish defect, a
        non-rework batch, or a batch outside those statuses all fail with
        `ERR_REWORK_BATCH_NOT_USABLE`." PRD §3.8: "A `RESOLVED` item is
        verified by a `QAInspector` moving it to `VERIFIED`, which requires the
        verifier's `X-User-ID` to differ from `reported_by`
        (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`) and the opening's fabrication
        axis to have been driven back to `STAGED` (`ERR_OPENING_NOT_RESTAGED`)."

        Design: Corner/errors/punch_rework_full_loop_gates
        """
        ctx = _delivered_rated_with_label("CR-4", "O-P4", "M-P4", "B-P4", "T-P4",
                                          roll_capacity=3)
        order = ctx["order"]
        opening = ctx["openings"][0]
        booth = ctx["booth"]
        roll = ctx["roll"]

        # Order SHIPPED once every opening is past SHIPPED on the ship axis.
        set_order_status(order["id"], "READY_TO_SHIP")
        set_order_status(order["id"], "SHIPPED")

        punch1 = report_punch(opening["id"], category="FINISH_DEFECT", severity="MAJOR",
                              description="sheen burn-through", role="QAInspector",
                              user_id="qa-9")
        triage_punch(punch1["id"], user_id="qa-1")

        # A second (unrated) order driven to FINISHING, holding a normal batch.
        other = setup_order_finishing(
            project=ctx["project"], contract_code="CR-4", order_code="O-Q4",
            openings=({"opening_no": "Q1", "leaf_count": 1, "fire_rating": "NONE",
                       "required_on_site_date": "2026-11-01"},),
            machine_code="M-P4B", machine_species=["PAINT_GRADE"],
            slot_start=12, slot_end=13, estimated_minutes=30, **_UNRATED,
        )
        bo2 = make_batch(other["order"]["id"], booth["id"], cure_start_hour=20,
                         cure_end_hour=24)

        # Resolving a TRIAGED MAJOR item directly fails.
        resp = api.resolve_punch_item(punch1["id"], PL_H)
        validate_error(resp, ApiErrorId.ERR_PUNCH_NOT_RESOLVABLE, 409)

        authorize_rework(punch1["id"])

        # FINISH_DEFECT without a batch id fails usability.
        resp = api.begin_rework(punch1["id"], {}, PL_H)
        validate_error(resp, ApiErrorId.ERR_REWORK_BATCH_NOT_USABLE, 409)

        # A batch belonging to another order fails the match check first.
        resp = api.begin_rework(punch1["id"], {"rework_batch_id": bo2["id"]}, PL_H)
        validate_error(resp, ApiErrorId.ERR_REWORK_BATCH_ORDER_MISMATCH, 409)

        # Proper rework batch on the same order: begin, then pass it.
        rb1 = make_batch(order["id"], booth["id"], cure_start_hour=30, cure_end_hour=34,
                         is_rework_batch=True)
        in_rework = begin_rework(punch1["id"], rework_batch_id=rb1["id"])
        assert in_rework["status"] == "IN_REWORK"
        advance_batch(rb1["id"], "SPRAYED")
        advance_batch(rb1["id"], "CURED")
        passed = measure_batch(rb1["id"], 34)
        assert passed["status"] == "PASSED"
        assert get_punch(punch1["id"])["status"] == "RESOLVED", "batch-pass cascade resolves"
        assert get_opening(opening["id"])["fab_status"] == "FINISHED", (
            "batch-pass cascade re-finishes the REWORK opening"
        )

        # Second punch: accept is blocked while items remain open.
        punch2 = report_punch(opening["id"], category="FINISH_DEFECT", severity="MAJOR",
                              description="second defect at hinge", role="QAInspector",
                              user_id="qa-8")
        resp = api.accept_opening(opening["id"], H("QAInspector", "qa-1"))
        validate_error(resp, ApiErrorId.ERR_OPEN_PUNCH_ITEMS, 409)

        triage_punch(punch2["id"], user_id="qa-1")
        authorize_rework(punch2["id"])

        # An already-PASSED batch is outside the usable statuses. rb3 is
        # created while the opening is still in REWORK (the rework-batch gate),
        # before rb2's passing measurement moves it back to FINISHED.
        rb2 = make_batch(order["id"], booth["id"], cure_start_hour=36, cure_end_hour=40,
                         is_rework_batch=True)
        rb3 = make_batch(order["id"], booth["id"], cure_start_hour=42, cure_end_hour=46,
                         is_rework_batch=True)
        advance_batch(rb2["id"], "SPRAYED")
        advance_batch(rb2["id"], "CURED")
        measure_batch(rb2["id"], 35)
        resp = api.begin_rework(punch2["id"], {"rework_batch_id": rb2["id"]}, PL_H)
        validate_error(resp, ApiErrorId.ERR_REWORK_BATCH_NOT_USABLE, 409)

        begin_rework(punch2["id"], rework_batch_id=rb3["id"])
        advance_batch(rb3["id"], "SPRAYED")
        advance_batch(rb3["id"], "CURED")
        measure_batch(rb3["id"], 35)
        assert get_punch(punch2["id"])["status"] == "RESOLVED"

        # Verification requires the opening driven back to STAGED.
        resp = api.set_punch_item_status(punch1["id"], {"target_status": "VERIFIED"},
                                         H("QAInspector", "qa-1"))
        validate_error(resp, ApiErrorId.ERR_OPENING_NOT_RESTAGED, 409)

        # Relabel and re-stage the opening.
        alloc2 = issue_labels(opening["id"], roll["id"], user_id="la-2")
        apply_labels(alloc2["id"], user_id="pl-2")
        verify_labels(alloc2["id"], user_id="qa-5")
        restaged = stage_opening(opening["id"])
        assert restaged["fab_status"] == "STAGED"

        # The reporter may not verify.
        resp = api.set_punch_item_status(punch1["id"], {"target_status": "VERIFIED"},
                                         H("QAInspector", "qa-9"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403)

        verify_punch(punch1["id"], user_id="qa-1")
        verify_punch(punch2["id"], user_id="qa-1")
        accepted = accept_opening(opening["id"], user_id="qa-1")
        assert accepted["ship_status"] == "ACCEPTED"

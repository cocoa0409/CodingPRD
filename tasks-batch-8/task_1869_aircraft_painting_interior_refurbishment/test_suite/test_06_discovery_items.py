"""Discovery work: approval chain, deferral fences, program totals (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_program,
    approve_scheme,
    book_slot,
    create_aircraft,
    create_assessment,
    create_bay,
    create_discovery,
    create_engagement,
    create_estimated_discovery,
    create_invoice,
    decide_assessment,
    estimate_discovery,
    get_program,
    make_customer_rep_headers,
    set_logical_clock,
    setup_inducted_program,
    setup_in_work_program,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_discovery_item_payload,
    estimate_discovery_payload,
)

_PM = TEST_USERS["program_manager_headers"]
_ADMIN = TEST_USERS["center_admin_headers"]
_TECH = TEST_USERS["shop_technician_headers"]


class TestDiscoveryApprovalCascade:
    def test_approval_debits_program_discovery_total(self, api):
        """PRD §3.6: "Approval — presenting `expected_program_version` under
        the OCC rule of §2.6, with `ERR_FORBIDDEN_OWNERSHIP` guarding identity —
        moves the item to `APPROVED` and debits the program:
        `discovery_cost_total_cents` increases by the item's `est_cost_cents`,
        the program's `version` increments".

        Design: Difficulty/transitive_cascade/discovery_approval_depth2_cascade
        """
        ctx = setup_inducted_program()
        item = create_estimated_discovery(
            ctx["program"]["id"], description="Rivet line corrosion repair",
            est_cost_cents=250000, est_hours=40,
        )
        v_before = get_program(ctx["program"]["id"])["version"]
        approved = validate_success(
            api.approve_discovery_item(
                item["id"], {"expected_program_version": v_before},
                make_customer_rep_headers(ctx["customer"]["id"]),
            )
        )
        assert approved["status"] == "APPROVED"
        program = get_program(ctx["program"]["id"])
        assert program["discovery_cost_total_cents"] == 250000
        assert program["version"] == v_before + 1

    def test_approval_regenerates_draft_invoice_lines(self, api, finance_clerk_headers):
        """PRD §3.6: "because that program total changed, every DRAFT invoice
        of the program regenerates its computed lines and bumps its own
        `version` and `updated_at`." PRD §3.12: a FINAL invoice carries "one
        line per discovery item in `APPROVED` or `COMPLETED` status ... plus a
        per-item handling line of ten percent of that item's amount, each
        handling line individually rounded half-up".

        Design: Difficulty/transitive_cascade/discovery_approval_depth2_cascade
        """
        ctx = setup_inducted_program()
        invoice = create_invoice(ctx["program"]["id"], "FINAL")
        assert invoice["total_cents"] == 6172837, (
            "remainder-only DRAFT: 12345673 - round(base x 0.10) - round(base x 0.40)"
        )

        item = create_estimated_discovery(
            ctx["program"]["id"], description="Rivet line corrosion repair",
            est_cost_cents=250000, est_hours=40,
        )
        resp = api.approve_discovery_item(
            item["id"],
            {"expected_program_version": get_program(ctx["program"]["id"])["version"]},
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_success(resp)

        regen = validate_success(api.get_invoice(invoice["id"], finance_clerk_headers))
        # 6172837 + 250000 item line + round(250000 x 0.10) handling.
        assert regen["total_cents"] == 6447837, (
            "DRAFT invoice regenerated from the mutated program total with no "
            "direct invoice call"
        )


class TestDeferralFences:
    def test_defer_without_reason_rejected(self, api):
        """PRD §3.6: "the request must carry a non-empty `defer_reason`
        (`ERR_DEFER_REASON_REQUIRED`, HTTP 422)."

        Design: Corner/validations/defer_without_reason_rejected_422
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = setup_inducted_program()
        item = create_estimated_discovery(
            ctx["program"]["id"], description="Cabinet veneer mismatch",
            est_cost_cents=120000, est_hours=16,
        )
        resp = api.defer_discovery_item(
            item["id"], {}, make_customer_rep_headers(ctx["customer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DEFER_REASON_REQUIRED)
        item_after = validate_success(api.get_discovery_item(item["id"], _PM))
        assert item_after["status"] == "ESTIMATED"

    def test_defer_after_delivery_window_rejected(self, api):
        """PRD §3.6: "deferral is only possible while the logical clock date is
        on or before the program's `committed_delivery_date`
        (`ERR_DELIVERY_WINDOW_PASSED`)".

        Design: Corner/errors/defer_after_delivery_window_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = setup_inducted_program()
        item = create_estimated_discovery(
            ctx["program"]["id"], description="Veneer mismatch",
            est_cost_cents=120000, est_hours=16,
        )
        set_logical_clock("2026-09-02T00:00:00Z")  # past committed 2026-09-01
        resp = api.defer_discovery_item(
            item["id"], {"defer_reason": "customer reviewing options"},
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_PASSED)

    def test_safety_gate_precedes_temporal_gate_on_defer(self, api):
        """PRD §2.10: "Incoming requests are validated in a fixed priority
        order, so that the error a caller receives is always the
        highest-priority failure present rather than an arbitrary one." —
        safety gates (item 8, incl. `ERR_SAFETY_DEFERRAL_FORBIDDEN`) precede
        temporal rules (item 9, incl. `ERR_DELIVERY_WINDOW_PASSED`). PRD §3.6:
        "a `safety_linked` item may never be deferred
        (`ERR_SAFETY_DEFERRAL_FORBIDDEN`)".

        Design: Difficulty/priority_pair_validation_conflict/defer_safety_vs_temporal_conflict
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = setup_inducted_program()
        item = create_estimated_discovery(
            ctx["program"]["id"], description="HEAVY corrosion doubler repair",
            safety_linked=True, est_cost_cents=600000, est_hours=80,
        )
        set_logical_clock("2026-09-02T00:00:00Z")  # also past the delivery window
        resp = api.defer_discovery_item(
            item["id"], {"defer_reason": "awaiting customer decision"},
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SAFETY_DEFERRAL_FORBIDDEN)

    def test_safety_item_remains_estimated_after_conflict_rejection(self, api):
        """PRD §3.6: "a `safety_linked` item may never be deferred
        (`ERR_SAFETY_DEFERRAL_FORBIDDEN`)". PRD §2.7: "All mutations and their
        cascades are atomic within the request: the system never persists a
        partial application."

        Design: Difficulty/priority_pair_validation_conflict/defer_safety_vs_temporal_conflict
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = setup_inducted_program()
        item = create_estimated_discovery(
            ctx["program"]["id"], description="HEAVY corrosion doubler repair",
            safety_linked=True, est_cost_cents=600000, est_hours=80,
        )
        set_logical_clock("2026-09-02T00:00:00Z")
        resp = api.defer_discovery_item(
            item["id"], {"defer_reason": "awaiting customer decision"},
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SAFETY_DEFERRAL_FORBIDDEN)
        item_after = validate_success(api.get_discovery_item(item["id"], _PM))
        assert item_after["status"] == "ESTIMATED", "rejected deferral leaves state intact"


class TestDiscoveryReferentialIntegrity:
    def test_cross_program_assessment_reference_rejected(self, api):
        """PRD §2.8: "A discovery item's `assessment_id`, when present, must
        reference an assessment of the same program." and "Request bodies carry
        foreign keys, and these are checked for existence and cross-consistency
        with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422) on failure."

        Design: Corner/entities/discovery_item_cross_program_assessment_rejected
        """
        # Two inducted programs on two aircraft; the assessment belongs to p1.
        ctx1 = setup_inducted_program()
        ctx2 = setup_inducted_program()
        assessment1 = create_assessment(ctx1["program"]["id"])

        resp = api.create_discovery_item(
            create_discovery_item_payload(
                program_id=ctx2["program"]["id"],
                assessment_id=assessment1["id"],
                description="cross-program reference",
            ),
            _TECH,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


class TestDiscoveryPhaseGate:
    def test_discovery_create_at_quoted_rejected(self, api):
        """PRD §3.6: a discovery item is logged "while the program is
        `INDUCTED`, `SURFACE_REVIEW`, `IN_WORK`, or `IN_INSPECTION`". At QUOTED
        the create violates PRD §2.10 item 7: "**State validity** — the entity is
        in a valid from-state for the requested transition, including terminal
        lockdown (`ERR_INVALID_STATE`, 409)".

        Design: Corner/validations/discovery_create_in_quoted_phase_rejected
        """
        ctx = create_engagement()
        resp = api.create_discovery_item(
            create_discovery_item_payload(
                program_id=ctx["program"]["id"], description="premature finding"
            ),
            _TECH,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_open_discovery_items_block_inspection_phase(self, api, program_manager_headers):
        """PRD §3.5: "From `IN_WORK` to `IN_INSPECTION`: every discovery item
        of the program must be in a terminal state — `COMPLETED`, `REJECTED`,
        or `DEFERRED` (`ERR_DISCOVERY_ITEMS_OPEN`)".

        Design: Corner/errors/open_discovery_items_block_inspection_phase
        """
        # Chain manually so a discovery item can be left OPEN at INDUCTED.
        ctx = setup_inducted_program()
        create_discovery(ctx["program"]["id"], description="Unresolved finding")
        ctx["assessment"] = create_assessment(ctx["program"]["id"])
        advance_program(ctx["program"]["id"], "SURFACE_REVIEW")
        decide_assessment(ctx["assessment"]["id"], decision="STRIP",
                          corrosion_severity="NONE")
        from test_helpers import (
            book_booth_window,
            create_and_approve_scheme,
            create_booth,
        )
        create_and_approve_scheme(ctx["program"]["id"], ctx["customer"]["id"])
        ctx["booth"] = create_booth()
        ctx["booking"] = book_booth_window(ctx["booth"]["id"], ctx["program"]["id"])
        advance_program(ctx["program"]["id"], "IN_WORK")
        validate_success(
            api.complete_booth_booking(ctx["booking"]["id"], {"actual_hours": 8}, _TECH)
        )

        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "IN_INSPECTION"}, program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_DISCOVERY_ITEMS_OPEN)


class TestDiscoveryApprovalOcc:
    def test_stale_discovery_approval_rejected(self, api, program_manager_headers):
        """PRD §2.6: "If the program's current `version` no longer matches —
        because another writer has advanced it since the client last read the
        program — the request is rejected with `ERR_STALE_PROGRAM_VERSION`
        (HTTP 412)." PRD §3.6: discovery approval "moves the item to `APPROVED`
        and debits the program ... the program's `version` increments".

        Design: Corner/cross_cutting_complexity_layers/occ_discovery_approve_stale_version_rejected
        """
        ctx = setup_inducted_program()
        item_a = create_estimated_discovery(
            ctx["program"]["id"], description="Item A", est_cost_cents=100000, est_hours=10
        )
        item_b = create_estimated_discovery(
            ctx["program"]["id"], description="Item B", est_cost_cents=200000, est_hours=20
        )
        v = validate_success(
            api.get_program(ctx["program"]["id"], program_manager_headers)
        )["version"]

        approved_a = validate_success(
            api.approve_discovery_item(
                item_a["id"], {"expected_program_version": v},
                make_customer_rep_headers(ctx["customer"]["id"]),
            )
        )
        assert approved_a["status"] == "APPROVED"

        stale = api.approve_discovery_item(
            item_b["id"], {"expected_program_version": v},
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PROGRAM_VERSION)

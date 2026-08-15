"""Quality audits, AQL sampling, and the rework loop (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_audit,
    create_available_fabric_roll,
    create_line_assignment,
    create_marker_payload,
    create_operator,
    create_production_order,
    create_sewing_line,
    get_success_data,
    log_piece_work,
    plan_order,
    record_audit,
    setup_completed_bundle,
    setup_order_with_failed_audit,
    setup_rework_recorded_audit,
    setup_released_bundle_with_operator,
    setup_style_with_approved_pack,
    validate_error,
    validate_paginated,
    verify_entry,
)

QI1 = TEST_USERS["quality_inspector_headers"]
QI2 = TEST_USERS["quality_inspector2_headers"]
ANY = TEST_USERS["any_headers"]


class TestAqlSamplePlanTieredLookup:
    def test_aql_sample_plan_tiered_lookup_normal(self):
        """PRD §3.8: "The `code_letter` comes from the lot size through
        inclusive tiers: ... 91 to 150, F; 151 to 280, G". "The `sample_size`
        follows the letter: 2 pieces for A, 3 for B, 5 for C, 8 for D, 13 for
        E, 20 for F, 32 for G, 50 for H, and 80 for J."

        Design: Difficulty/combinatorial_formula/aql_sample_plan_tiered_lookup
        """
        ctx150 = setup_completed_bundle(order_qty=150)
        audit150 = create_audit(ctx150["order"]["id"], QI1)
        assert audit150["lot_size"] == 150
        assert audit150["code_letter"] == "F"
        assert audit150["sample_size"] == 20
        assert audit150["accept_max"] == 1
        assert audit150["reject_min"] == 2

        ctx151 = setup_completed_bundle(order_qty=151)
        audit151 = create_audit(ctx151["order"]["id"], QI1)
        assert audit151["lot_size"] == 151
        assert audit151["code_letter"] == "G"
        assert audit151["sample_size"] == 32
        assert audit151["accept_max"] == 2
        assert audit151["reject_min"] == 3

    def test_aql_sample_plan_tightened_bumps_letter(self):
        """PRD §3.8: "A `TIGHTENED` inspection level bumps the letter one step
        — A becomes B, and so on up to H becoming J — capped at J, which stays
        J."

        Design: Difficulty/combinatorial_formula/aql_sample_plan_tiered_lookup
        """
        ctx = setup_completed_bundle(order_qty=150)
        audit = create_audit(
            ctx["order"]["id"], QI1, inspection_level="TIGHTENED",
        )
        assert audit["lot_size"] == 150
        assert audit["code_letter"] == "G"
        assert audit["sample_size"] == 32
        assert audit["accept_max"] == 2
        assert audit["reject_min"] == 3


class TestAqlAcceptRejectBoundary:
    def test_aql_accept_at_accept_max_fail_at_reject_min(self):
        """PRD §3.8: "When `defects_found` is at most `accept_max`, the audit
        closes `PASS`" and "When `defects_found` is at least `reject_min`,
        the audit closes `FAIL`". "`reject_min` is always exactly one more
        than `accept_max`, so the verdict boundary is exact."

        Design: Difficulty/boundary_precision_check/aql_accept_at_accept_max_fail_at_reject_min
        """
        ctx_pass = setup_completed_bundle(order_qty=5)  # lot 5 -> A, Ac 0, Re 1
        audit_pass = create_audit(ctx_pass["order"]["id"], QI1)
        assert audit_pass["sample_size"] == 2
        assert audit_pass["accept_max"] == 0
        assert audit_pass["reject_min"] == 1
        audit_pass = record_audit(audit_pass["id"], 0, QI1)
        assert audit_pass["result"] == "PASS"
        assert audit_pass["status"] == "CLOSED_PASS"

        ctx_fail = setup_completed_bundle(order_qty=5)
        audit_fail = create_audit(ctx_fail["order"]["id"], QI1)
        audit_fail = record_audit(audit_fail["id"], 1, QI1)
        assert audit_fail["result"] == "FAIL"
        assert audit_fail["status"] == "CLOSED_FAIL"

    def test_aql_verdict_updates_order_quality_status(self):
        """PRD §3.8: "When `defects_found` is at most `accept_max`, the audit
        closes `PASS`: ... and the order's `quality_status` moves from
        `QC_PENDING` to `QC_PASSED`". "When `defects_found` is at least
        `reject_min`, the audit closes `FAIL` — and the failure cascades."

        Design: Difficulty/boundary_precision_check/aql_accept_at_accept_max_fail_at_reject_min
        """
        ctx_pass = setup_completed_bundle(order_qty=5)
        audit_pass = create_audit(ctx_pass["order"]["id"], QI1)
        record_audit(audit_pass["id"], 0, QI1)
        order = get_success_data(
            api_client.get_production_order(ctx_pass["order"]["id"], ANY)
        )
        assert order["quality_status"] == "QC_PASSED"

        ctx_fail = setup_completed_bundle(order_qty=5)
        audit_fail = create_audit(ctx_fail["order"]["id"], QI1)
        record_audit(audit_fail["id"], 1, QI1)
        order = get_success_data(
            api_client.get_production_order(ctx_fail["order"]["id"], ANY)
        )
        assert order["quality_status"] == "QC_FAILED"


class TestAuditCreation:
    def test_audit_created_open_with_derived_sample_plan(self):
        """PRD §3.8: "A new audit starts `OPEN` with `result` `NONE`,
        `defects_found` null, and `recorded_by_user_id` null." and "The
        `lot_size` is the order's `total_order_qty` at that moment."

        Design: Corner/state_machines/audit_created_open_with_derived_sample_plan
        """
        ctx = setup_completed_bundle(order_qty=30)  # lot 30 -> D (26-50)
        audit = create_audit(ctx["order"]["id"], QI1, aql_level="AQL_4_0")
        assert audit["status"] == "OPEN"
        assert audit["result"] == "NONE"
        assert audit["defects_found"] is None
        assert audit["lot_size"] == 30
        assert audit["code_letter"] == "D"
        assert audit["sample_size"] == 8
        # AQL_4_0 row for D: accept at most 1, reject at 2.
        assert audit["accept_max"] == 1
        assert audit["reject_min"] == 2

    def test_audit_create_requires_completed_bundle(self):
        """PRD §3.8: "third, the order must have at least one bundle in
        `COMPLETED` status (otherwise `ERR_NO_COMPLETED_BUNDLES`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/audit_create_requires_completed_bundle
        """
        ctx = setup_released_bundle_with_operator(order_qty=5)
        # Log (but do not verify) work -> bundle IN_PROGRESS, nothing COMPLETED.
        log_piece_work(
            ctx["bundle"]["id"], ctx["ops"][0]["id"], ctx["operator"]["id"], qty=2,
        )
        resp = api_client.create_quality_audit(
            {
                "production_order_id": ctx["order"]["id"],
                "inspection_level": "NORMAL",
                "aql_level": "AQL_2_5",
            },
            QI1,
        )
        validate_error(resp, ApiErrorId.ERR_NO_COMPLETED_BUNDLES)

    def test_audit_create_rejection_leaves_no_audit(self):
        """PRD §3.8: "third, the order must have at least one bundle in
        `COMPLETED` status (otherwise `ERR_NO_COMPLETED_BUNDLES`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/audit_create_requires_completed_bundle
        """
        ctx = setup_released_bundle_with_operator(order_qty=5)
        log_piece_work(
            ctx["bundle"]["id"], ctx["ops"][0]["id"], ctx["operator"]["id"], qty=2,
        )
        resp = api_client.create_quality_audit(
            {
                "production_order_id": ctx["order"]["id"],
                "inspection_level": "NORMAL",
                "aql_level": "AQL_2_5",
            },
            QI1,
        )
        validate_error(resp, ApiErrorId.ERR_NO_COMPLETED_BUNDLES)
        audits, meta = validate_paginated(
            api_client.list_quality_audits(
                ANY, params={"production_order_id": ctx["order"]["id"]},
            )
        )
        assert audits == []
        assert meta["total_count"] == 0


class TestAuditFailCascade:
    def test_audit_fail_cascade_to_logged_entry_rejection(self):
        """PRD §3.8: "every bundle of the order in `RELEASED`, `IN_PROGRESS`,
        or `COMPLETED` status drops into `REWORK_HOLD`, snapshotting its
        current status into `pre_rework_status` and incrementing its
        `version`; and that bundle flip itself auto-rejects each of the
        bundle's still-`LOGGED` piece-work entries, stamping their
        `reviewed_by_user_id` as `system`".

        Design: Difficulty/transitive_cascade/audit_fail_cascade_to_logged_entry_rejection
        """
        ctx = setup_completed_bundle(order_qty=2)
        verified_entry = ctx["entry"]
        completed_bundle = ctx["bundle"]
        assert completed_bundle["status"] == "COMPLETED"
        # Second bundle on the same order is impossible (cut qty exhausted), so
        # log an extra unverified entry is impossible too (qty gate); instead
        # cascade assertions run on the single COMPLETED bundle.
        audit = create_audit(ctx["order"]["id"], QI1)
        audit = record_audit(audit["id"], 1, QI1)
        assert audit["result"] == "FAIL"
        assert audit["status"] == "CLOSED_FAIL"
        order = get_success_data(
            api_client.get_production_order(ctx["order"]["id"], ANY)
        )
        assert order["quality_status"] == "QC_FAILED"
        bundle = get_success_data(api_client.get_bundle(completed_bundle["id"], ANY))
        assert bundle["status"] == "REWORK_HOLD"
        assert bundle["pre_rework_status"] == "COMPLETED"
        # Verified work is not erased.
        entry = get_success_data(
            api_client.get_piece_work_entry(verified_entry["id"], ANY)
        )
        assert entry["status"] == "VERIFIED"

    def test_audit_fail_cascade_rejects_logged_entry_on_multi_size_order(self):
        """PRD §3.8: "that bundle flip itself auto-rejects each of the
        bundle's still-`LOGGED` piece-work entries, stamping their
        `reviewed_by_user_id` as `system`".

        Design: Difficulty/transitive_cascade/audit_fail_cascade_to_logged_entry_rejection
        """
        _TU = TEST_USERS
        style, pack, ops = setup_style_with_approved_pack(
            style_overrides={"size_run": ["S", "M"]},
        )
        order = create_production_order(
            style["id"], _TU["production_planner_headers"],
            size_quantities=[{"size": "M", "qty": 1}, {"size": "S", "qty": 1}],
        )
        plan_order(order["id"], pack["id"], _TU["production_planner_headers"])
        roll = create_available_fabric_roll(
            _TU["materials_planner_headers"], received_yards=82.6,
        )
        marker = get_success_data(api_client.create_marker(
            create_marker_payload(
                production_order_id=order["id"], fabric_roll_id=roll["id"],
                planned_pieces=2,
            ),
            _TU["cutting_manager_headers"],
        ))
        get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]},
            _TU["cutting_manager_headers"],
        ))
        get_success_data(api_client.start_cutting(
            order["id"], _TU["production_planner_headers"],
        ))
        get_success_data(api_client.cut_marker(
            marker["id"],
            {"size_quantities": [{"size": "M", "qty": 1}, {"size": "S", "qty": 1}]},
            _TU["cutting_manager_headers"],
        ))
        bundles, _ = validate_paginated(
            api_client.list_bundles(ANY, params={"marker_id": marker["id"]})
        )
        b_m = next(b for b in bundles if b["size"] == "M")
        b_s = next(b for b in bundles if b["size"] == "S")
        for b in (b_m, b_s):
            get_success_data(api_client.release_bundle(
                b["id"], _TU["line_supervisor_headers"],
            ))
        operator = create_operator(_TU["line_supervisor_headers"])
        line = create_sewing_line(_TU["production_planner_headers"])
        create_line_assignment(
            line["id"], order["id"], ops[0]["id"], operator["id"],
            _TU["line_supervisor_headers"], assigned_pieces=2,
        )
        # M bundle: full qty logged + verified -> COMPLETED.
        e_m = log_piece_work(b_m["id"], ops[0]["id"], operator["id"], qty=1)
        verify_entry(e_m["id"], _TU["line_supervisor_headers"])
        # S bundle: qty 1 logged, left LOGGED -> IN_PROGRESS.
        e_s = log_piece_work(b_s["id"], ops[0]["id"], operator["id"], qty=1)
        audit = create_audit(order["id"], QI1)
        audit = record_audit(audit["id"], 1, QI1)
        assert audit["result"] == "FAIL"
        order_after = get_success_data(
            api_client.get_production_order(order["id"], ANY)
        )
        assert order_after["quality_status"] == "QC_FAILED"
        b_m_after = get_success_data(api_client.get_bundle(b_m["id"], ANY))
        b_s_after = get_success_data(api_client.get_bundle(b_s["id"], ANY))
        assert b_m_after["status"] == "REWORK_HOLD"
        assert b_m_after["pre_rework_status"] == "COMPLETED"
        assert b_s_after["status"] == "REWORK_HOLD"
        assert b_s_after["pre_rework_status"] == "IN_PROGRESS"
        e_s_after = get_success_data(
            api_client.get_piece_work_entry(e_s["id"], ANY)
        )
        assert e_s_after["status"] == "REJECTED"
        assert e_s_after["reviewed_by_user_id"] == "system"
        e_m_after = get_success_data(
            api_client.get_piece_work_entry(e_m["id"], ANY)
        )
        assert e_m_after["status"] == "VERIFIED"


class TestReworkLoop:
    def test_production_order_quality_rework_loop(self):
        """PRD §3.8: "creating the chained audit, as described above, returns
        the order to `QC_PENDING` and supersedes the `REWORK_RECORDED` audit,
        so the rework cycle `QC_PENDING` → `QC_FAILED` → `REWORK_IN_PROGRESS`
        → `QC_PENDING` is fully cyclic."

        Design: Difficulty/non_linear_state_machine/production_order_quality_rework_loop
        """
        ctx, audit1 = setup_rework_recorded_audit(order_qty=2, defects=1)
        order = get_success_data(
            api_client.get_production_order(ctx["order"]["id"], ANY)
        )
        assert order["quality_status"] == "REWORK_IN_PROGRESS"
        assert audit1["status"] == "REWORK_RECORDED"
        # Chain the re-audit (different inspector to satisfy SoD).
        audit2 = create_audit(
            ctx["order"]["id"], QI2, re_audit_of_audit_id=audit1["id"],
        )
        audit1_after = get_success_data(api_client.get_quality_audit(audit1["id"], ANY))
        assert audit1_after["status"] == "SUPERSEDED"
        order = get_success_data(
            api_client.get_production_order(ctx["order"]["id"], ANY)
        )
        assert order["quality_status"] == "QC_PENDING"
        audit2 = record_audit(audit2["id"], 0, QI2)
        assert audit2["result"] == "PASS"
        assert audit2["status"] == "CLOSED_PASS"
        order = get_success_data(
            api_client.get_production_order(ctx["order"]["id"], ANY)
        )
        assert order["quality_status"] == "QC_PASSED"

    def test_rework_restores_bundle_pre_rework_status(self):
        """PRD §3.8: "every bundle sitting in `REWORK_HOLD` returns to the
        status its `pre_rework_status` snapshot holds — `RELEASED`,
        `IN_PROGRESS`, or `COMPLETED` — clearing `pre_rework_status` back to
        null and leaving `completed_through_seq` untouched, because verified
        work survives rework."

        Design: Difficulty/non_linear_state_machine/production_order_quality_rework_loop
        """
        ctx, audit1 = setup_rework_recorded_audit(order_qty=2, defects=1)
        bundle = get_success_data(api_client.get_bundle(ctx["bundle"]["id"], ANY))
        assert bundle["status"] == "COMPLETED"
        assert bundle["pre_rework_status"] is None
        assert bundle["completed_through_seq"] == 1

    def test_rework_complete_on_passed_audit_rejected(self):
        """PRD §3.8: "the audit must be `CLOSED_FAIL`, or the request is
        rejected with `ERR_AUDIT_NOT_FAILED` (HTTP 409)".

        Design: Corner/errors/rework_complete_on_passed_audit_rejected
        """
        ctx = setup_completed_bundle(order_qty=2)
        audit = create_audit(ctx["order"]["id"], QI1)
        record_audit(audit["id"], 0, QI1)  # -> CLOSED_PASS
        resp = api_client.rework_complete_quality_audit(audit["id"], QI1)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_FAILED)


class TestReauditRules:
    def test_reaudit_self_recheck_rejected(self):
        """PRD §2.10: "A re-audit may not be recorded by the
        `QualityInspector` who recorded the failed audit it follows: when the
        audit carries a `re_audit_of_audit_id` link, the recorder's
        `X-User-ID` must differ from the referenced audit's
        `recorded_by_user_id`, or the record is rejected with
        `ERR_SOD_REAUDIT_SELF_RECHECK` (HTTP 403)."

        Design: Corner/validations/reaudit_self_recheck_rejected
        """
        ctx, audit1 = setup_rework_recorded_audit(order_qty=2, defects=1)
        audit2 = create_audit(
            ctx["order"]["id"], QI2, re_audit_of_audit_id=audit1["id"],
        )
        # u-qi1 recorded the failed audit; u-qi1 may not record the re-audit.
        resp = api_client.record_quality_audit(audit2["id"], {"defects_found": 0}, QI1)
        validate_error(resp, ApiErrorId.ERR_SOD_REAUDIT_SELF_RECHECK)
        audit2_after = get_success_data(api_client.get_quality_audit(audit2["id"], ANY))
        assert audit2_after["status"] == "OPEN"

    def test_reaudit_parent_not_reworked_rejected(self):
        """PRD §3.8: "second, the referenced audit must currently be
        `REWORK_RECORDED` (otherwise `ERR_REAUDIT_PARENT_NOT_REWORKED`,
        HTTP 409)".

        Design: Corner/validations/reaudit_parent_not_reworked_rejected
        """
        ctx, audit1 = setup_order_with_failed_audit(order_qty=2, defects=1)
        # audit1 is CLOSED_FAIL; no rework-complete call made.
        resp = api_client.create_quality_audit(
            {
                "production_order_id": ctx["order"]["id"],
                "inspection_level": "NORMAL",
                "aql_level": "AQL_2_5",
                "re_audit_of_audit_id": audit1["id"],
            },
            QI2,
        )
        validate_error(resp, ApiErrorId.ERR_REAUDIT_PARENT_NOT_REWORKED)

    def test_reaudit_order_mismatch_rejected(self):
        """PRD §3.8: "first, when the re-audit link is present, the referenced
        audit must belong to the same production order (otherwise
        `ERR_REAUDIT_ORDER_MISMATCH`, HTTP 422)".

        Design: Corner/errors/reaudit_order_mismatch_rejected
        """
        ctx_a, audit_a = setup_rework_recorded_audit(order_qty=2, defects=1)
        ctx_b = setup_completed_bundle(order_qty=2)
        resp = api_client.create_quality_audit(
            {
                "production_order_id": ctx_b["order"]["id"],
                "inspection_level": "NORMAL",
                "aql_level": "AQL_2_5",
                "re_audit_of_audit_id": audit_a["id"],
            },
            QI2,
        )
        validate_error(resp, ApiErrorId.ERR_REAUDIT_ORDER_MISMATCH)

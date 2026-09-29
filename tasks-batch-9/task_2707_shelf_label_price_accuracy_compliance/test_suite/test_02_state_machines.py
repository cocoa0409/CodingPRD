"""State machine behaviour: initial states, guarded transitions, terminal lockdown and sweeps."""

from test_helpers import (
    assert_instant_is,
    assert_label_serial,
    assert_money_cents,
    assert_posture,
    expected_penalty_exposure_cents,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ACTION_INVALID_STATE,
    ERR_AUDIT_SAMPLE_EMPTY,
    ERR_FILE_HAS_NO_LINES,
    ERR_FILE_INVALID_STATE,
    ERR_FINDING_INVALID_STATE,
    ERR_INSPECTION_INVALID_STATE,
    ERR_LABEL_NOT_PRINTED,
    ERR_LABEL_TASK_INVALID_STATE,
    ERR_REFUND_CLAIM_INVALID_STATE,
    ERR_SIGNAGE_INVALID_STATE,
    ERR_TRANSITION_ALREADY_APPLIED,
)
from test_helpers.constants import DEFAULT_CLOCK, ROLE_CODE_LABEL_ASSOCIATE


class TestInitialStates:
    def test_every_freshly_created_resource_sits_in_its_declared_initial_state(
        self, api, build
    ):
        """A new associate, file, line, audit, sign and task all read their birth state.

        PRD 3.1: "A newly hired associate starts `UNTRAINED` with an
        `accountability_score` of 100, an `issued_action_count` of 0 and a
        `verified_placement_count` of 0."
        PRD 3.3: "A new batch begins in `DRAFT` with `line_count` and
        `verified_line_count` both 0, and with `distributed_at` and
        `superseded_by_file_id` both null."
        PRD 3.4: "A newly created task begins with its print axis at
        `NOT_PRINTED`, its placement axis at `UNPLACED`, `printed_label_serial`,
        `placed_by_associate_id`, `verified_by_associate_id`, `placed_at`,
        `verified_at` and `observed_shelf_price_cents` all null, and
        `rejection_count` at 0."

        Design: Corner/State Machines/corner_initial_state_of_every_created_entity_matches_declaration
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        aisle_id = staff["aisle_id"]

        file_record = build.price_change_file(
            jurisdiction_id, [store_id], file_number="PCF-1001", priority="ROUTINE"
        )
        line = build.add_line(
            file_record["id"], "00000000002001", 1000, 1199, 12, "OZ",
            item_description="Cheese 12oz",
        )

        newcomer = validate_success(
            api.create_associate(
                store_id,
                {
                    "employee_number": "E-X1",
                    "full_name": "Newly Hired",
                    "role_code": ROLE_CODE_LABEL_ASSOCIATE,
                },
                build.admin,
            ),
            201,
        )
        assert newcomer["training_status"] == "UNTRAINED"
        assert newcomer["accountability_score"] == 100
        assert newcomer["issued_action_count"] == 0
        assert newcomer["verified_placement_count"] == 0

        assert build.read_file(file_record["id"])["status"] == "DRAFT"
        assert build.read_line(line["id"])["line_status"] == "PENDING"

        audit = build.scanner_audit(
            store_id,
            aisle_id,
            staff["auditor_id"],
            scan_window_start="2026-08-01T09:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        assert audit["status"] == "OPEN"
        assert audit["outcome"] == "PENDING"

        sign = build.promo_signage(
            store_id,
            aisle_id,
            [],
            sign_code="SG-001",
            promo_start_at="2026-08-02T00:00:00Z",
            promo_end_at="2026-08-09T00:00:00Z",
        )
        assert sign["status"] == "DRAFT"
        assert sign["compliance_state"] == "NOT_APPLICABLE"
        assert sign["posted_at"] is None
        assert sign["removed_at"] is None

        distributed = build.distribute(file_record["id"])
        assert distributed["status"] == "DISTRIBUTED"

        task = build.label_task(
            file_record["id"],
            store_id,
            line["id"],
            aisle_id,
            staff["label_associate_id"],
            scheduled_start_at="2026-08-02T09:00:00Z",
            scheduled_end_at="2026-08-02T10:00:00Z",
            expected_price_change_file_version=distributed["version"],
        )
        assert task["print_status"] == "NOT_PRINTED"
        assert task["placement_status"] == "UNPLACED"
        assert task["printed_label_serial"] is None
        assert task["placed_by_associate_id"] is None
        assert task["verified_by_associate_id"] is None
        assert task["placed_at"] is None
        assert task["verified_at"] is None
        assert task["observed_shelf_price_cents"] is None
        assert task["rejection_count"] == 0

        store = build.read_store(store_id)
        assert_posture(store, "OPEN")
        assert store["label_backlog_count"] == 1


class TestDistributeSideEffects:
    def test_distribution_stamps_the_clock_bumps_the_version_and_leaves_lines_pending(
        self, api, build
    ):
        """One distribute call moves the file and nothing else.

        PRD 3.3: "On success, `distributed_at` is stamped with the current
        instant, the unit-price fields of every line that is not `WITHDRAWN` are
        recomputed and re-stored, and the batch's `version` advances by one."
        PRD 3.3: "Creating the store-level execution task for a line moves it
        `PENDING → TASKED`, and that same event may auto-advance its owning batch
        `DISTRIBUTED → PARTIALLY_EXECUTED`"

        Design: Corner/State Machines/corner_distribute_transition_applies_every_declared_side_effect
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        store_id = build.store(jurisdiction_id, store_number="S001")
        draft = build.price_change_file(
            jurisdiction_id, [store_id], file_number="PCF-1001", priority="ROUTINE"
        )
        assert draft["version"] == 1
        build.add_line(
            draft["id"], "00000000002001", 1000, 1199, 12, "OZ",
            item_description="Cheese 12oz",
        )
        build.add_line(
            draft["id"], "00000000002002", 449, 499, 128, "FL_OZ",
            item_description="Milk 1gal",
        )

        distributed = build.distribute(draft["id"])
        assert distributed["status"] == "DISTRIBUTED"
        assert_instant_is(distributed["distributed_at"], DEFAULT_CLOCK)
        assert distributed["version"] == draft["version"] + 1 == 2
        assert distributed["line_count"] == 2
        assert distributed["verified_line_count"] == 0

        lines, meta = validate_paginated(
            api.list_price_change_lines(draft["id"], build.admin)
        )
        assert meta["total_count"] == 2
        assert [line["line_status"] for line in lines] == ["PENDING", "PENDING"]

        store = build.read_store(store_id)
        assert_posture(store, "OPEN")
        assert store["label_backlog_count"] == 0


class TestPreconditionEnforcement:
    def test_empty_file_and_already_distributed_file_fail_with_different_codes(
        self, api, build
    ):
        """Distributing a line-less file and appending to a distributed one are distinct failures.

        PRD 3.3: "It requires the batch to be in `DRAFT`, refusing a second
        attempt with `ERR_FILE_INVALID_STATE`; it requires at least one line,
        refusing an empty batch with `ERR_FILE_HAS_NO_LINES`"
        PRD 3.3: "Adding a line to a batch that has left `DRAFT` is refused with
        `ERR_FILE_INVALID_STATE`."

        Design: Corner/State Machines/corner_precondition_enforcement_on_distribute_and_line_append
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_id = build.store(jurisdiction_id, store_number="S001")
        empty_file = build.price_change_file(
            jurisdiction_id, [store_id], file_number="PCF-EMPTY", priority="ROUTINE"
        )
        ok_file = build.price_change_file(
            jurisdiction_id, [store_id], file_number="PCF-OK", priority="ROUTINE"
        )
        build.add_line(
            ok_file["id"], "00000000002001", 1000, 1199, 12, "OZ",
            item_description="Cheese 12oz",
        )
        build.distribute(ok_file["id"])

        validate_error(
            api.distribute_price_change_file(empty_file["id"], build.admin),
            ERR_FILE_HAS_NO_LINES,
        )
        still_draft = build.read_file(empty_file["id"])
        assert still_draft["status"] == "DRAFT"
        assert still_draft["distributed_at"] is None
        assert still_draft["line_count"] == 0

        validate_error(
            api.create_price_change_line(
                ok_file["id"],
                {
                    "item_upc": "00000000002099",
                    "item_description": "Late Addition",
                    "category_code": "DAIRY",
                    "old_retail_cents": 999,
                    "new_retail_cents": 899,
                    "net_content_qty": 16,
                    "net_content_uom": "OZ",
                },
                build.admin,
            ),
            ERR_FILE_INVALID_STATE,
        )
        lines, meta = validate_paginated(
            api.list_price_change_lines(ok_file["id"], build.admin)
        )
        assert meta["total_count"] == 1
        assert build.read_file(ok_file["id"])["line_count"] == 1


class TestInvalidTransitionsFromInitialStates:
    def test_each_undeclared_transition_carries_its_own_entity_state_code(self, api, build):
        """Closing an OPEN audit, removing a DRAFT sign, answering a SCHEDULED inspection
        and superseding a DRAFT batch each fail with their own code.

        PRD 2.9: "Because an open audit necessarily has zero scan lines, a close
        attempt against an open audit is reported by the empty-sample rule at
        priority 63 as `ERR_AUDIT_SAMPLE_EMPTY` rather than by this rule."
        PRD 3.6: "Removing a sign still in `DRAFT` is refused with
        `ERR_SIGNAGE_INVALID_STATE`, and a second removal is refused with
        `ERR_TRANSITION_ALREADY_APPLIED`."
        PRD 3.7: "A store manager submits the store's answer by supplying a
        `remediation_summary` together with the pinned
        `expected_regulatory_inspection_version`, moving the inspection to
        `RESPONSE_SUBMITTED` from either `FINDINGS_ISSUED` or
        `RESPONSE_REJECTED`; any other state is refused with
        `ERR_INSPECTION_INVALID_STATE`."
        PRD 3.3: "The batch being superseded must be `DISTRIBUTED` or
        `PARTIALLY_EXECUTED`; a `DRAFT`, already-`EXECUTED` or
        already-`SUPERSEDED` batch is refused with `ERR_FILE_INVALID_STATE`."

        Design: Corner/State Machines/corner_invalid_transitions_from_initial_states_return_entity_state_errors
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        aisle_a1 = staff["aisle_id"]
        aisle_a2 = build.aisle(store_id, aisle_code="A02", category_code="BAKERY")
        auditor_headers = build.auditor(staff["auditor_id"])
        manager_headers = build.manager(staff["manager_id"])

        draft_file = build.price_change_file(
            jurisdiction_id, [store_id], file_number="PCF-1001", priority="ROUTINE"
        )
        build.add_line(
            draft_file["id"], "00000000002001", 1000, 1199, 12, "OZ",
            item_description="Cheese 12oz",
        )

        open_audit = build.scanner_audit(
            store_id,
            aisle_a1,
            staff["auditor_id"],
            scan_window_start="2026-08-01T09:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        evidence = build.closed_audit(
            store_id,
            aisle_a2,
            staff["auditor_id"],
            [
                {
                    "item_upc": "00000000003001",
                    "shelf_price_cents": 500,
                    "register_price_cents": 500,
                }
            ],
            rate_variant="GROSS_MISMATCH",
            scan_window_start="2026-08-01T14:00:00Z",
            scan_window_end="2026-08-01T15:00:00Z",
        )
        sign = build.promo_signage(
            store_id,
            aisle_a1,
            [],
            sign_code="SG-001",
            promo_start_at="2026-08-02T00:00:00Z",
            promo_end_at="2026-08-09T00:00:00Z",
        )
        inspection = build.inspection(
            store_id, evidence["audit_id"], inspector_ref="INS-77",
            inspection_date="2026-08-01T16:00:00Z",
        )

        validate_error(
            api.close_scanner_audit(
                open_audit["id"], auditor_headers, {"rate_variant": "GROSS_MISMATCH"}
            ),
            ERR_AUDIT_SAMPLE_EMPTY,
        )
        validate_error(
            api.remove_promo_signage(sign["id"], manager_headers),
            ERR_SIGNAGE_INVALID_STATE,
        )
        validate_error(
            api.submit_inspection_response(
                inspection["id"],
                {
                    "remediation_summary": "Nothing to answer yet",
                    "expected_regulatory_inspection_version": inspection["version"],
                },
                manager_headers,
            ),
            ERR_INSPECTION_INVALID_STATE,
        )
        validate_error(
            api.supersede_price_change_file(
                draft_file["id"], {"superseded_by_file_id": draft_file["id"]}, build.admin
            ),
            ERR_FILE_INVALID_STATE,
        )

        assert build.read_audit(open_audit["id"])["status"] == "OPEN"
        assert build.read_signage(sign["id"])["status"] == "DRAFT"
        after_inspection = build.read_inspection(inspection["id"])
        assert after_inspection["status"] == "SCHEDULED"
        assert after_inspection["version"] == inspection["version"]
        assert after_inspection["response_round"] == 0
        assert build.read_file(draft_file["id"])["status"] == "DRAFT"


class TestTerminalStateLockdown:
    def test_waived_finding_voided_action_and_denied_claim_all_refuse_further_moves(
        self, api, build
    ):
        """Three terminal resources refuse three further transitions with three codes.

        PRD 3.7: "A compliance officer waives a finding, moving it
        `OPEN → WAIVED` by supplying `target_status` `WAIVED` together with a
        non-empty `waiver_reason`; a missing or empty reason is
        `ERR_REMEDIATION_EVIDENCE_REQUIRED`, a finding not in `OPEN` is
        `ERR_FINDING_INVALID_STATE`, and the owning inspection must not yet be
        `CLOSED`."
        PRD 3.2: "A void with no `void_reason`, or an empty one, is refused with
        `ERR_VOID_REASON_REQUIRED`; attempting either transition on an action
        that is already `COMPLETED` or `VOIDED` is refused with
        `ERR_ACTION_INVALID_STATE`."
        PRD 3.8: "any other disallowed settlement transition, such as approving a
        denied claim or denying a paid one, is refused with
        `ERR_REFUND_CLAIM_INVALID_STATE`"

        Design: Corner/State Machines/corner_terminal_states_refuse_every_further_transition
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            scanner_error_rate_threshold_pct=2.0,
            overcharge_refund_policy="REFUND_DIFFERENCE_ONLY",
            refund_cap_cents=5000,
            refund_budget_per_audit_cents=100000,
        )
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        manager_headers = build.manager(staff["manager_id"])
        label_id = staff["label_associate_id"]

        closed = build.closed_audit(
            store_id,
            staff["aisle_id"],
            staff["auditor_id"],
            [
                {
                    "item_upc": "00000000002001",
                    "shelf_price_cents": 1000,
                    "register_price_cents": 1199,
                }
            ],
            rate_variant="GROSS_MISMATCH",
            scan_window_start="2026-08-01T09:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        overcharge_line_id = closed["scan_line_ids"][0]

        inspection = build.inspection_with_findings(
            store_id,
            closed["audit_id"],
            [
                {
                    "finding_code": "SHELF_TAG_MISMATCH",
                    "severity": "MAJOR",
                    "affected_item_count": 4,
                },
                {
                    "finding_code": "UNIT_PRICE_FORMAT",
                    "severity": "MINOR",
                    "affected_item_count": 1,
                },
            ],
            inspector_ref="INS-77",
            inspection_date="2026-08-01T16:00:00Z",
        )
        find_1, find_2 = inspection["finding_ids"]
        build.transition_finding(
            find_2,
            "WAIVED",
            waiver_reason="Signage reprinted before the inspector left",
        )

        action = build.issue_action(
            label_id,
            "COACHING",
            trigger_code="INSPECTION_FINDING",
            source_ref=inspection["inspection_id"],
            actor_headers=manager_headers,
        )
        build.void_action(
            action["id"],
            "Issued against the wrong associate",
            actor_headers=manager_headers,
        )

        claim = build.refund_claim(
            overcharge_line_id, "CUST-1", closed["version"]
        )
        denied = build.settle_claim(
            claim["id"], "DENIED", manager_headers, denial_reason="No receipt presented"
        )
        assert denied["status"] == "DENIED"

        validate_error(
            api.transition_inspection_finding(
                find_2,
                {
                    "target_status": "REMEDIATION_PLANNED",
                    "remediation_action_code": "RELABEL",
                },
                build.officer,
            ),
            ERR_FINDING_INVALID_STATE,
        )
        validate_error(
            api.transition_accountability_action(
                action["id"],
                {"target_status": "VOIDED", "void_reason": "Voiding again"},
                manager_headers,
            ),
            ERR_ACTION_INVALID_STATE,
        )
        validate_error(
            api.settle_refund_claim(
                claim["id"], {"target_status": "APPROVED"}, manager_headers
            ),
            ERR_REFUND_CLAIM_INVALID_STATE,
        )

        waived = build.read_finding(find_2)
        assert waived["status"] == "WAIVED"
        assert waived["remediation_action_code"] is None
        voided = build.read_action(action["id"])
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "Issued against the wrong associate"
        still_denied = build.read_claim(claim["id"])
        assert still_denied["status"] == "DENIED"
        assert still_denied["denial_reason"] == "No receipt presented"
        assert build.read_associate(label_id)["accountability_score"] == 100
        assert build.read_finding(find_1)["status"] == "OPEN"


class TestAlreadyAppliedTransitions:
    def test_replaying_a_landed_transition_is_already_applied_and_moves_nothing(
        self, api, build
    ):
        """A second post, close, denial and removal each report the replay, not an illegal move.

        PRD 3.6: "The sign must be in `DRAFT` — posting a `NON_COMPLIANT` or
        `REMOVED` sign is refused with `ERR_SIGNAGE_INVALID_STATE`, and posting an
        already-`POSTED` sign is refused with `ERR_TRANSITION_ALREADY_APPLIED`."
        PRD 3.5: "Closing a second time is refused with
        `ERR_TRANSITION_ALREADY_APPLIED`."
        PRD 3.8: "and repeating a settlement that has already been applied, such
        as paying an already-`PAID` claim, is refused with
        `ERR_TRANSITION_ALREADY_APPLIED`"

        Design: Corner/State Machines/corner_repeating_an_applied_transition_is_refused_as_already_applied
        """
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            signage_disclosure_codes=[],
            overcharge_refund_policy="REFUND_DIFFERENCE_ONLY",
        )
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        manager_headers = build.manager(staff["manager_id"])
        auditor_headers = build.auditor(staff["auditor_id"])

        posted = build.posted_signage(
            store_id,
            staff["aisle_id"],
            ["UNIT_PRICE"],
            staff["manager_id"],
            sign_code="SG-001",
            promo_start_at="2026-08-01T00:00:00Z",
            promo_end_at="2026-08-09T00:00:00Z",
        )
        sign_id = posted["signage_id"]
        posted_at = posted["signage"]["posted_at"]
        assert posted["signage"]["status"] == "POSTED"

        closed = build.closed_audit(
            store_id,
            staff["aisle_id"],
            staff["auditor_id"],
            [
                {
                    "item_upc": "00000000002001",
                    "shelf_price_cents": 1000,
                    "register_price_cents": 1199,
                }
            ],
            rate_variant="GROSS_MISMATCH",
            scan_window_start="2026-08-01T09:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        closed_at = closed["audit"]["closed_at"]
        audit_version = closed["version"]

        claim = build.refund_claim(closed["scan_line_ids"][0], "CUST-1", audit_version)
        denied = build.settle_claim(
            claim["id"], "DENIED", manager_headers, denial_reason="No receipt presented"
        )
        claim_version = denied["version"]

        validate_error(
            api.post_promo_signage(sign_id, manager_headers),
            ERR_TRANSITION_ALREADY_APPLIED,
        )
        assert build.read_signage(sign_id)["posted_at"] == posted_at

        validate_error(
            api.close_scanner_audit(
                closed["audit_id"], auditor_headers, {"rate_variant": "GROSS_MISMATCH"}
            ),
            ERR_TRANSITION_ALREADY_APPLIED,
        )
        after_close = build.read_audit(closed["audit_id"])
        assert after_close["closed_at"] == closed_at
        assert after_close["version"] == audit_version

        validate_error(
            api.settle_refund_claim(
                claim["id"],
                {"target_status": "DENIED", "denial_reason": "No receipt presented"},
                manager_headers,
            ),
            ERR_TRANSITION_ALREADY_APPLIED,
        )
        assert build.read_claim(claim["id"])["version"] == claim_version

        removed = build.remove_signage(sign_id, manager_headers)
        assert removed["status"] == "REMOVED"
        assert removed["compliance_state"] == "NOT_APPLICABLE"
        assert_instant_is(removed["removed_at"], DEFAULT_CLOCK)

        validate_error(
            api.remove_promo_signage(sign_id, manager_headers),
            ERR_TRANSITION_ALREADY_APPLIED,
        )
        assert build.read_signage(sign_id)["removed_at"] == removed["removed_at"]


class TestSignageSweep:
    def test_sweep_applies_expiry_before_disclosure_and_leaves_draft_signs_alone(
        self, api, build
    ):
        """One sweep expires one sign, faults another and skips the draft.

        PRD 3.6: "A store manager or compliance officer runs the sweep against a
        store, and it walks every non-removed sign of that store against the
        current instant in a **pinned order**: the expiry test runs first, and
        only then the disclosure test."
        PRD 3.6: "Because the expiry test runs first, a sign that is both expired
        **and** missing a disclosure becomes `EXPIRED_PENDING_REMOVAL`, never
        `NON_COMPLIANT`."
        PRD 3.6: "The sweep reports what it did: a `swept_count` of signs
        examined, an `expired_count` and a `non_compliant_count` of transitions
        applied, and the store's resulting `compliance_posture`."

        Design: Corner/State Machines/corner_signage_sweep_applies_expiry_before_disclosure_and_skips_draft
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", signage_disclosure_codes=[])
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        aisle_id = staff["aisle_id"]
        manager_id = staff["manager_id"]

        expiring = build.posted_signage(
            store_id, aisle_id, [], manager_id,
            sign_code="SG-EXP",
            promo_start_at="2026-08-01T00:00:00Z",
            promo_end_at="2026-08-02T00:00:00Z",
        )
        live = build.posted_signage(
            store_id, aisle_id, [], manager_id,
            sign_code="SG-LIVE",
            promo_start_at="2026-08-01T00:00:00Z",
            promo_end_at="2026-08-20T00:00:00Z",
        )
        draft = build.promo_signage(
            store_id, aisle_id, [],
            sign_code="SG-DRAFT",
            promo_start_at="2026-08-05T00:00:00Z",
            promo_end_at="2026-08-25T00:00:00Z",
        )

        build.amend_jurisdiction(jurisdiction_id, {"signage_disclosure_codes": ["UNIT_PRICE"]})
        build.set_clock("2026-08-03T00:00:00Z")

        before = build.read_signage(live["signage_id"])
        assert before["status"] == "POSTED"
        assert before["compliance_state"] == "COMPLIANT"
        assert before["missing_disclosure_codes"] == ["UNIT_PRICE"]

        result = build.sweep(store_id)
        assert result["swept_count"] == 3
        assert result["expired_count"] == 1
        assert result["non_compliant_count"] == 1
        assert result["compliance_posture"] == "RESTRICTED"

        expired_sign = build.read_signage(expiring["signage_id"])
        assert expired_sign["status"] == "EXPIRED_PENDING_REMOVAL"
        assert expired_sign["compliance_state"] == "EXPIRED_NOT_REMOVED"
        assert expired_sign["missing_disclosure_codes"] == ["UNIT_PRICE"]

        faulted = build.read_signage(live["signage_id"])
        assert faulted["status"] == "NON_COMPLIANT"
        assert faulted["compliance_state"] == "MISSING_DISCLOSURE"

        untouched = build.read_signage(draft["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["compliance_state"] == "NOT_APPLICABLE"

        store = build.read_store(store_id)
        assert store["signage_violation_count"] == 2
        assert_posture(store, "RESTRICTED")


class TestSignageRemovalCompensates:
    def test_removing_the_only_violating_sign_restores_the_exact_prior_posture(
        self, api, build
    ):
        """Removal returns the store to OPEN, not merely to something less severe.

        PRD 3.6: "Removal stamps `removed_at` with the current instant, resets
        `compliance_state` to `NOT_APPLICABLE`, and recomputes the store's
        `signage_violation_count` and then its posture; when the sign was swept
        into a violation state, this is exactly the compensating operation that
        returns the store's violation count to where it stood before."
        PRD 2.7: "`signage_violation_count` is the number of this store's
        promotional signs whose status is either `EXPIRED_PENDING_REMOVAL` or
        `NON_COMPLIANT`."

        Design: Corner/State Machines/corner_removing_violating_signage_reverses_the_posture_side_effect
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", signage_disclosure_codes=[])
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        manager_headers = build.manager(staff["manager_id"])

        pristine = build.read_summary(store_id)
        assert pristine["compliance_posture"] == "OPEN"

        sign = build.posted_signage(
            store_id, staff["aisle_id"], [], staff["manager_id"],
            sign_code="SG-EXP",
            promo_start_at="2026-08-01T00:00:00Z",
            promo_end_at="2026-08-02T00:00:00Z",
        )
        assert sign["signage"]["missing_disclosure_codes"] == []

        build.set_clock("2026-08-03T00:00:00Z")
        swept = build.sweep(store_id)
        assert swept["compliance_posture"] == "RESTRICTED"

        removed = build.remove_signage(sign["signage_id"], manager_headers)
        assert removed["status"] == "REMOVED"
        assert removed["compliance_state"] == "NOT_APPLICABLE"
        assert_instant_is(removed["removed_at"], "2026-08-03T00:00:00Z")
        assert removed["missing_disclosure_codes"] == []

        after = build.read_summary(store_id)
        assert after["compliance_posture"] == pristine["compliance_posture"] == "OPEN"
        assert after["signage_violation_count"] == 0

        second = build.sweep(store_id)
        assert second["swept_count"] == 0
        assert second["expired_count"] == 0
        assert second["non_compliant_count"] == 0


class TestGuardedPlacement:
    def test_the_two_task_axes_guard_each_other_with_different_codes(self, api, build):
        """Placing needs a printed label; verifying needs a placed one.

        PRD 3.4: "Placement requires the print axis to read exactly `PRINTED` — a
        task that was rejected and consequently needs reprinting cannot simply be
        re-placed, and the attempt is refused with `ERR_LABEL_NOT_PRINTED`."
        PRD 3.4: "Both outcomes require the placement axis to read exactly
        `PLACED`, refusing an `UNPLACED` task with `ERR_LABEL_TASK_INVALID_STATE`
        and a second verification of an already-`VERIFIED` task with
        `ERR_TRANSITION_ALREADY_APPLIED`."

        Design: Corner/State Machines/corner_guarded_placement_requires_a_printed_label_and_a_placed_task
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        label_id = staff["label_associate_id"]
        label_headers = build.associate_headers(label_id)
        auditor_headers = build.auditor(staff["auditor_id"])

        distributed = build.distributed_file(
            jurisdiction_id,
            [store_id],
            [
                {
                    "item_upc": "00000000002001",
                    "new_retail_cents": 1000,
                    "old_retail_cents": 1199,
                    "net_content_qty": 12,
                    "net_content_uom": "OZ",
                    "item_description": "Cheese 12oz",
                }
            ],
            file_number="PCF-1001",
            priority="ROUTINE",
        )
        line_id = distributed["line_ids"][0]
        task = build.label_task(
            distributed["file_id"],
            store_id,
            line_id,
            staff["aisle_id"],
            label_id,
            scheduled_start_at="2026-08-02T09:00:00Z",
            scheduled_end_at="2026-08-02T10:00:00Z",
            expected_price_change_file_version=distributed["version"],
        )
        task_id = task["id"]
        assert build.read_store(store_id)["label_backlog_count"] == 1

        validate_error(
            api.place_label_task(
                task_id, {"observed_shelf_price_cents": 1000}, label_headers
            ),
            ERR_LABEL_NOT_PRINTED,
        )
        assert build.read_task(task_id)["placed_at"] is None

        validate_error(
            api.verify_label_task_placement(
                task_id, {"outcome": "VERIFIED"}, auditor_headers
            ),
            ERR_LABEL_TASK_INVALID_STATE,
        )
        assert build.read_task(task_id)["verified_by_associate_id"] is None

        printed = build.print_task(task_id, label_headers)
        assert printed["print_status"] == "PRINTED"
        assert_label_serial(printed["printed_label_serial"])
        assert printed["placement_status"] == "UNPLACED"
        assert build.read_line(line_id)["line_status"] == "LABELED"

        placed = build.place_task(task_id, 1000, label_headers)
        assert placed["placement_status"] == "PLACED"
        assert placed["placed_by_associate_id"] == label_id
        assert_money_cents(placed["observed_shelf_price_cents"], 1000)
        assert placed["print_status"] == "PRINTED"

        assert build.read_line(line_id)["line_status"] == "LABELED"
        assert build.read_store(store_id)["label_backlog_count"] == 0


class TestRejectedAdjudicationFork:
    def test_reject_escalates_every_non_terminal_finding_and_freezes_the_store(
        self, api, build
    ):
        """One REJECT decision escalates an OPEN and a planned finding alike.

        PRD 3.7: "A `decision` of `REJECT`, optionally accompanied by a
        `rejection_note`, moves the inspection
        `RESPONSE_SUBMITTED → RESPONSE_REJECTED`, escalates every finding still in
        `OPEN` or `REMEDIATION_PLANNED`, recomputes the store's
        `escalated_finding_count` and `open_finding_count` and then its posture —
        which any escalated finding forces to `FROZEN` — and advances the
        inspection's `version` by one."
        PRD 3.7: "The `RESPONSE_SUBMITTED → RESPONSE_REJECTED → RESPONSE_SUBMITTED`
        negotiation loop may repeat without bound, which is exactly why the
        version pin exists."

        Design: Corner/State Machines/corner_rejected_adjudication_forks_the_inspection_and_escalates_findings
        """
        penalty_per_violation_cents = 5000
        jurisdiction_id = build.jurisdiction(
            code="US-CA",
            scanner_error_rate_threshold_pct=2.0,
            penalty_per_violation_cents=penalty_per_violation_cents,
            penalty_max_cents=2000000,
        )
        staff = build.store_with_staff(jurisdiction_id, assign_label_associate=False)
        store_id = staff["store_id"]
        manager_id = staff["manager_id"]

        closed = build.closed_audit(
            store_id,
            staff["aisle_id"],
            staff["auditor_id"],
            [
                {
                    "item_upc": "00000000002001",
                    "shelf_price_cents": 1000,
                    "register_price_cents": 1199,
                }
            ],
            rate_variant="GROSS_MISMATCH",
            scan_window_start="2026-08-01T09:00:00Z",
            scan_window_end="2026-08-01T10:00:00Z",
        )
        assert closed["audit"]["outcome"] == "FAIL"

        findings = [
            {
                "finding_code": "SHELF_TAG_MISMATCH",
                "severity": "MAJOR",
                "affected_item_count": 4,
            },
            {
                "finding_code": "UNIT_PRICE_FORMAT",
                "severity": "MINOR",
                "affected_item_count": 1,
            },
        ]
        inspection = build.inspection_with_findings(
            store_id,
            closed["audit_id"],
            findings,
            inspector_ref="INS-77",
            inspection_date="2026-08-01T16:00:00Z",
        )
        expected_exposure = expected_penalty_exposure_cents(
            findings, penalty_per_violation_cents, 2000000, evidence_audit_failed=True
        )
        assert expected_exposure == 81250
        assert_money_cents(
            inspection["inspection"]["penalty_exposure_cents"], expected_exposure
        )
        find_1, find_2 = inspection["finding_ids"]
        build.transition_finding(
            find_2, "REMEDIATION_PLANNED", remediation_action_code="REPRINT_UNIT_PRICE"
        )

        submitted = build.submit_response(
            inspection["inspection_id"],
            "All tags reprinted overnight",
            build.inspection_version(inspection["inspection_id"]),
            manager_id,
        )
        assert submitted["status"] == "RESPONSE_SUBMITTED"

        rejected = build.adjudicate(
            inspection["inspection_id"], "REJECT", rejection_note="Evidence photos undated"
        )
        assert rejected["status"] == "RESPONSE_REJECTED"
        assert_money_cents(rejected["penalty_exposure_cents"], expected_exposure)
        assert rejected["version"] == submitted["version"] + 1

        assert build.read_finding(find_1)["status"] == "ESCALATED"
        escalated_two = build.read_finding(find_2)
        assert escalated_two["status"] == "ESCALATED"
        assert escalated_two["remediation_action_code"] == "REPRINT_UNIT_PRICE"

        summary = build.read_summary(store_id)
        assert summary["escalated_finding_count"] == 2
        assert summary["open_finding_count"] == 0
        assert summary["failed_audit_count_30d"] == 1
        assert summary["compliance_posture"] == "FROZEN"

        resubmitted = build.submit_response(
            inspection["inspection_id"],
            "Photos re-dated and re-uploaded",
            build.inspection_version(inspection["inspection_id"]),
            manager_id,
        )
        assert resubmitted["status"] == "RESPONSE_SUBMITTED"
        assert resubmitted["response_round"] == 2

"""Error surface behaviour: every catalogued refusal, its status class and its envelope."""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_instant_is,
    assert_money_cents,
    assert_pct,
    factories,
    make_headers_without_role,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ACTION_INVALID_STATE,
    ERR_ASSOCIATE_INVALID_STATE,
    ERR_FILE_HAS_NO_LINES,
    ERR_FILE_INVALID_STATE,
    ERR_FINDING_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_JURISDICTION_NOT_FOUND,
    ERR_PENALTY_OVERRIDE_TOO_HIGH,
    ERR_REMEDIATION_EVIDENCE_REQUIRED,
    ERR_SUPERSEDING_FILE_INVALID,
    ERR_TRAINING_SCORE_TOO_LOW,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_VOID_REASON_REQUIRED,
)
from test_helpers.constants import (
    ROLE_CODE_LABEL_ASSOCIATE,
    ROLE_CODE_PRICE_AUDITOR,
    ROLE_CODE_STORE_MANAGER,
)


class TestFindingGuardsAndPenaltyCeiling:
    def test_each_branch_demands_its_own_field_and_the_override_stops_at_the_exposure(
        self, api, build, admin_headers, officer_headers
    ):
        """The same target status is a 409, a 422 or a 200 depending only on the payload.

        PRD 2.9: "**Priority 40 — own state.** The target resource is in a state
        from which the requested transition is declared."
        PRD 3.7: "A store manager plans remediation, moving a finding to
        `REMEDIATION_PLANNED` from either `OPEN` or `ESCALATED` by supplying
        `target_status` `REMEDIATION_PLANNED` together with a
        `remediation_action_code`; omitting the action code is refused with
        `ERR_REMEDIATION_EVIDENCE_REQUIRED`, and a finding in any other state is
        refused with `ERR_FINDING_INVALID_STATE`."
        PRD 3.7: "A store manager completes remediation, moving a finding
        `REMEDIATION_PLANNED → REMEDIATED` by supplying `target_status`
        `REMEDIATED` together with a `remediation_evidence_ref`; the finding must
        already be in `REMEDIATION_PLANNED`, and the evidence reference is
        mandatory — a transition to `REMEDIATED` missing either the action code or
        the evidence reference is refused with
        `ERR_REMEDIATION_EVIDENCE_REQUIRED`."
        PRD 3.7: "A `decision` of `ACCEPT` closes the inspection, and it is refused
        unless every finding has left `OPEN`: an inspection with even one untouched
        finding yields `ERR_FINDING_INVALID_STATE`. The request may optionally
        supply an `assessed_penalty_cents` override, which may not exceed the
        freshly recomputed exposure; a higher override is refused with
        `ERR_PENALTY_OVERRIDE_TOO_HIGH`."
        PRD 3.7: "Step three computes `refund_credit_cents` as the smaller of two
        independently floored candidates: seventy-five percent of the refund
        liability, floored; and fifty percent of the penalty exposure, floored."
        PRD 3.7: "Step five raises the store's `cumulative_penalty_exposure_cents`
        by the assessed penalty."

        Design: Corner/Errors/corner_finding_evidence_guards_and_the_penalty_override_ceiling
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        manager_headers = build.manager(manager_id)

        evidence = build.closed_audit(
            store_id,
            aisle_id,
            auditor_id,
            [
                {
                    "item_upc": "00000000017001",
                    "shelf_price_cents": 100,
                    "register_price_cents": 100,
                }
            ],
            rate_variant="GROSS_MISMATCH",
            audit_type="REGULATORY",
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T09:00:00Z",
        )
        assert evidence["audit"]["outcome"] == "PASS"

        issued = build.inspection_with_findings(
            store_id,
            evidence["audit_id"],
            [
                factories.finding_input("SHELF_TAG_MISMATCH", "MINOR", 2, "A01"),
                factories.finding_input("UNIT_PRICE_FORMAT", "MAJOR", 4, "A01"),
            ],
            inspector_ref="INS-2026-15",
            inspection_date="2026-08-01T10:00:00Z",
        )
        inspection_id = issued["inspection_id"]
        assert_money_cents(issued["inspection"]["penalty_exposure_cents"], 70000)

        rows, _meta = validate_paginated(
            api.list_inspection_findings(inspection_id, officer_headers)
        )
        by_code = {row["finding_code"]: row["id"] for row in rows}
        minor_id = by_code["SHELF_TAG_MISMATCH"]
        major_id = by_code["UNIT_PRICE_FORMAT"]

        validate_error(
            api.transition_inspection_finding(
                minor_id,
                factories.finding_transition_payload(
                    "REMEDIATED", remediation_evidence_ref="PHOTO-1"
                ),
                manager_headers,
            ),
            ERR_FINDING_INVALID_STATE,
            409,
        )
        validate_error(
            api.transition_inspection_finding(
                minor_id,
                factories.finding_transition_payload("REMEDIATION_PLANNED"),
                manager_headers,
            ),
            ERR_REMEDIATION_EVIDENCE_REQUIRED,
            422,
        )
        planned = build.transition_finding(
            minor_id,
            "REMEDIATION_PLANNED",
            manager_headers,
            remediation_action_code="RELABEL_AISLE",
        )
        assert planned["status"] == "REMEDIATION_PLANNED"
        assert planned["remediation_action_code"] == "RELABEL_AISLE"
        assert planned["remediation_evidence_ref"] is None

        validate_error(
            api.transition_inspection_finding(
                minor_id,
                factories.finding_transition_payload("REMEDIATED"),
                manager_headers,
            ),
            ERR_REMEDIATION_EVIDENCE_REQUIRED,
            422,
        )
        remediated = build.transition_finding(
            minor_id,
            "REMEDIATED",
            manager_headers,
            remediation_evidence_ref="PHOTO-1",
        )
        assert remediated["status"] == "REMEDIATED"
        assert remediated["remediation_evidence_ref"] == "PHOTO-1"
        assert_money_cents(remediated["penalty_component_cents"], 10000)

        validate_error(
            api.transition_inspection_finding(
                minor_id,
                factories.finding_transition_payload(
                    "WAIVED", waiver_reason="regulator relented"
                ),
                officer_headers,
            ),
            ERR_FINDING_INVALID_STATE,
            409,
        )

        second = build.remediate_finding(
            major_id, "REPRINT_UNIT_PRICE", "PHOTO-2", manager_id
        )
        assert second["status"] == "REMEDIATED"

        before_response = build.read_inspection(inspection_id)
        assert_money_cents(before_response["penalty_exposure_cents"], 70000)
        submitted = build.submit_response(
            inspection_id,
            "Both findings relabelled and photographed.",
            before_response["version"],
            manager_id,
        )
        assert submitted["status"] == "RESPONSE_SUBMITTED"
        assert submitted["response_round"] == 1

        validate_error(
            api.adjudicate_inspection(
                inspection_id,
                factories.adjudicate_payload("ACCEPT", assessed_penalty_cents=70001),
                officer_headers,
            ),
            ERR_PENALTY_OVERRIDE_TOO_HIGH,
            422,
        )
        closed = build.adjudicate(
            inspection_id, "ACCEPT", assessed_penalty_cents=70000
        )
        assert closed["status"] == "CLOSED"
        assert_money_cents(closed["assessed_penalty_cents"], 70000)
        assert_money_cents(closed["penalty_exposure_cents"], 70000)
        assert_money_cents(closed["refund_liability_cents"], 0)
        assert_money_cents(closed["refund_credit_cents"], 0)
        assert_instant_is(closed["closed_at"], "2026-08-01T00:00:00Z")

        store = validate_success(api.get_store(store_id, admin_headers))
        assert_money_cents(store["cumulative_penalty_exposure_cents"], 70000)
        assert store["open_finding_count"] == 0


class TestRemedialTrainingScoreGate:
    def test_a_failing_score_is_only_an_error_once_the_associate_is_suspended(
        self, api, build, admin_headers
    ):
        """The same 79 is a recorded attempt before suspension and a refusal after it.

        PRD 3.2: "A failing score for an `UNTRAINED` or `IN_TRAINING` associate is
        emphatically **not** an error — the attempt is recorded and the associate
        stays in training."
        PRD 3.2: "The suspension floor is 80, and the comparison is **strict**: a
        recomputed score of exactly 80 does not suspend, a score of 79.99 does."
        PRD 3.2: "A `SUSPENDED` associate is reinstated only by completing the
        remedial module `REMEDIAL_LABEL_101` with a score of at least 80. Recording
        any other module for a suspended associate is refused with
        `ERR_ASSOCIATE_INVALID_STATE`, and recording `REMEDIAL_LABEL_101` with a
        score below 80 is refused with `ERR_TRAINING_SCORE_TOO_LOW`."
        PRD 3.2: "A qualifying remedial completion applies three compensating
        effects in order: first, every accountability action against this associate
        whose status is `ISSUED` and whose `action_type` is `SUSPENSION` or
        `RETRAINING_ASSIGNED` transitions `ISSUED → COMPLETED`; second, the
        `accountability_score` is recomputed from the actions that remain `ISSUED`;
        third, `certification_expires_at` is re-stamped at the current instant plus
        365 days."

        Design: Corner/Errors/corner_remedial_training_score_gate_binds_only_a_suspended_associate
        """
        jurisdiction_record = build.jurisdiction_record(code="US-CA")
        assert jurisdiction_record["accountability_variant"] == "OCCURRENCE_WEIGHTED"
        jurisdiction_id = jurisdiction_record["id"]
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        manager_headers = build.manager(manager_id)

        fresh = validate_success(
            api.create_associate(
                store_id,
                factories.associate_payload(
                    ROLE_CODE_LABEL_ASSOCIATE,
                    employee_number="E-LA1",
                    full_name="Lee Label",
                ),
                admin_headers,
            ),
            201,
        )
        associate_id = fresh["id"]
        assert fresh["training_status"] == "UNTRAINED"
        assert fresh["certification_expires_at"] is None
        assert_pct(fresh["accountability_score"], 100.00)

        just_short = validate_success(
            api.record_training_completion(
                associate_id, factories.training_payload("LABEL_101", 79), manager_headers
            )
        )
        assert just_short["training_status"] == "IN_TRAINING"
        assert just_short["certification_expires_at"] is None
        assert_pct(just_short["last_training_score_pct"], 79)

        far_short = validate_success(
            api.record_training_completion(
                associate_id, factories.training_payload("LABEL_101", 12), manager_headers
            )
        )
        assert far_short["training_status"] == "IN_TRAINING"
        assert_pct(far_short["last_training_score_pct"], 12)

        passed = validate_success(
            api.record_training_completion(
                associate_id, factories.training_payload("LABEL_101", 80), manager_headers
            )
        )
        assert passed["training_status"] == "CERTIFIED"
        assert_instant_is(passed["certification_expires_at"], "2027-08-01T00:00:00Z")

        action = build.issue_action(
            associate_id,
            "SUSPENSION",
            trigger_code="AUDIT_FAIL",
            source_ref="AU-manual",
            actor_headers=manager_headers,
        )
        assert action["score_weight"] == 25
        assert action["status"] == "ISSUED"
        assert action["issued_by_ref"] == manager_id

        suspended = build.read_associate(associate_id)
        assert_pct(suspended["accountability_score"], 75.00)
        assert suspended["training_status"] == "SUSPENDED"

        validate_error(
            api.record_training_completion(
                associate_id, factories.training_payload("LABEL_101", 95), manager_headers
            ),
            ERR_ASSOCIATE_INVALID_STATE,
            409,
        )
        validate_error(
            api.record_training_completion(
                associate_id,
                factories.training_payload("REMEDIAL_LABEL_101", 79),
                manager_headers,
            ),
            ERR_TRAINING_SCORE_TOO_LOW,
            422,
        )
        _rows, meta = validate_paginated(
            api.list_associate_accountability_actions(
                associate_id, manager_headers, {"status": "ISSUED"}
            )
        )
        assert meta["total_count"] == 1

        reinstated = validate_success(
            api.record_training_completion(
                associate_id,
                factories.training_payload("REMEDIAL_LABEL_101", 80),
                manager_headers,
            )
        )
        assert reinstated["training_status"] == "CERTIFIED"
        assert_pct(reinstated["accountability_score"], 100.00)
        assert_instant_is(
            reinstated["certification_expires_at"], "2027-08-01T00:00:00Z"
        )
        assert build.read_action(action["id"])["status"] == "COMPLETED"


class TestVoidRequiresAReason:
    def test_the_reason_is_conditional_on_the_target_and_the_void_never_repeats(
        self, api, build, officer_headers
    ):
        """A void with no usable reason changes nothing; the accepted void restores the score exactly.

        PRD 3.2: "Alternatively a store manager or compliance officer voids it,
        supplying `target_status` of `VOIDED` together with a `void_reason`; voiding
        is the compensating operation for the accountability-score invariant, and
        after it the score returns to **exactly** its pre-issue value."
        PRD 3.2: "A void with no `void_reason`, or an empty one, is refused with
        `ERR_VOID_REASON_REQUIRED`; attempting either transition on an action that
        is already `COMPLETED` or `VOIDED` is refused with
        `ERR_ACTION_INVALID_STATE`."
        PRD 3.2: "Voiding never changes `training_status`, so voiding the action
        that caused a suspension does not by itself reinstate the associate."
        PRD 2.4: "`version` is an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that resource, again including
        cascade-driven mutations."

        Design: Corner/Errors/corner_voiding_an_action_requires_a_reason_and_is_not_repeatable
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        associate_id = build.certified(
            store_id,
            ROLE_CODE_LABEL_ASSOCIATE,
            employee_number="E-LA1",
            full_name="Lee Label",
        )
        clean = build.read_associate(associate_id)
        assert clean["training_status"] == "CERTIFIED"
        assert_pct(clean["accountability_score"], 100.00)

        manager_headers = build.manager(manager_id)
        action = build.issue_action(
            associate_id,
            "WRITTEN_WARNING",
            trigger_code="OVERDUE_LABEL_TASK",
            actor_headers=manager_headers,
        )
        assert action["score_weight"] == 15
        assert action["source_ref"] is None
        assert action["void_reason"] is None

        warned = build.read_associate(associate_id)
        assert_pct(warned["accountability_score"], 85.00)
        assert warned["issued_action_count"] == 1
        assert warned["training_status"] == "CERTIFIED"

        validate_error(
            api.transition_accountability_action(
                action["id"],
                factories.action_transition_payload("VOIDED"),
                manager_headers,
            ),
            ERR_VOID_REASON_REQUIRED,
            422,
        )
        validate_error(
            api.transition_accountability_action(
                action["id"],
                factories.action_transition_payload("VOIDED", void_reason=""),
                officer_headers,
            ),
            ERR_VOID_REASON_REQUIRED,
            422,
        )
        untouched = build.read_action(action["id"])
        assert untouched["status"] == "ISSUED"
        assert_pct(
            build.read_associate(associate_id)["accountability_score"], 85.00
        )

        voided = build.void_action(
            action["id"],
            void_reason="issued against the wrong associate",
            actor_headers=manager_headers,
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "issued against the wrong associate"
        assert voided["version"] == untouched["version"] + 1

        restored = build.read_associate(associate_id)
        assert_pct(restored["accountability_score"], 100.00)
        assert restored["issued_action_count"] == 0
        assert restored["training_status"] == "CERTIFIED"

        validate_error(
            api.transition_accountability_action(
                action["id"],
                factories.action_transition_payload("VOIDED", void_reason="again"),
                manager_headers,
            ),
            ERR_ACTION_INVALID_STATE,
            409,
        )


class TestErrorEnvelopeUniformity:
    def test_every_status_class_comes_back_in_the_same_shape_and_writes_nothing(
        self, api, build, admin_headers, desk_headers
    ):
        """Seven failure classes, one envelope, and an entity left exactly as it was.

        PRD 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD 2.9: "**Priority 10 — authentication.** `X-User-Role` is present and
        non-empty, and `X-User-ID` is present and non-empty whenever the claimed
        role is entity-backed (`StoreManager`, `LabelAssociate`, `PriceAuditor`)."
        PRD 2.9: "**Priority 20 — authorization.** `X-User-Role` is one of the six
        declared roles and is listed among the target endpoint's authorized roles."
        PRD 3.3: "It requires the batch to be in `DRAFT`, refusing a second attempt
        with `ERR_FILE_INVALID_STATE`; it requires at least one line, refusing an
        empty batch with `ERR_FILE_HAS_NO_LINES`; and when the jurisdiction's
        `unit_price_required` is true it requires that every line of the batch can
        resolve a unit-price basis, refusing otherwise with
        `ERR_UNIT_PRICE_UNAVAILABLE`."
        PRD 3.3: "The named replacement must be a **different** batch, must share
        this batch's `jurisdiction_id`, must itself be `DRAFT` or `DISTRIBUTED`, and
        must carry an effective date at or after this batch's effective date; naming
        the batch itself, naming a batch in another jurisdiction, or naming a batch
        that is already superseded is refused with `ERR_SUPERSEDING_FILE_INVALID`,
        and naming a batch that does not exist is
        `ERR_PRICE_CHANGE_FILE_NOT_FOUND`."

        Design: Corner/Errors/corner_error_envelope_is_uniform_and_returns_4XX_across_every_status_class
        """
        jurisdiction_id = build.jurisdiction(code="US-CA")
        store_id = build.store(jurisdiction_id, store_number="S001", name="Bay Street")
        draft = validate_success(
            api.create_price_change_file(
                factories.price_change_file_payload(
                    jurisdiction_id, [store_id], file_number="PCF-1"
                ),
                admin_headers,
            ),
            201,
        )
        file_id = draft["id"]
        first_version = draft["version"]

        def assert_envelope(response, expected_error_id, expected_status):
            validate_error(response, expected_error_id, expected_status)
            body = response.json()
            assert body["response_type"] == "error"
            assert set(body["data"].keys()) == {"error_id", "message"}
            assert body["data"]["message"].strip()
            assert set(body["meta"].keys()) == {
                "api_request_id",
                "api_request_timestamp",
            }
            assert body["meta"]["api_request_id"].startswith("req_")

        assert_envelope(
            api.create_jurisdiction({"code": "US-NY"}, admin_headers),
            ERR_INVALID_REQUEST,
            400,
        )
        assert_envelope(
            api.create_jurisdiction(
                factories.jurisdiction_payload(code="US-NY", name="New York"),
                make_headers_without_role(),
            ),
            ERR_UNAUTHENTICATED,
            401,
        )
        assert_envelope(
            api.create_jurisdiction(
                factories.jurisdiction_payload(code="US-NY", name="New York"),
                desk_headers,
            ),
            ERR_UNAUTHORIZED,
            403,
        )
        assert_envelope(
            api.get_jurisdiction(NON_EXISTENT_UUID, admin_headers),
            ERR_JURISDICTION_NOT_FOUND,
            404,
        )
        assert_envelope(
            api.distribute_price_change_file(file_id, admin_headers),
            ERR_FILE_HAS_NO_LINES,
            422,
        )

        validate_success(
            api.create_price_change_line(
                file_id,
                factories.price_change_line_payload(
                    "00000000018001",
                    449,
                    499,
                    1,
                    "GAL",
                    item_description="Milk 1 GAL",
                    category_code="DAIRY",
                ),
                admin_headers,
            ),
            201,
        )
        distributed = validate_success(
            api.distribute_price_change_file(file_id, admin_headers)
        )
        assert distributed["status"] == "DISTRIBUTED"
        assert distributed["version"] == first_version + 1

        assert_envelope(
            api.distribute_price_change_file(file_id, admin_headers),
            ERR_FILE_INVALID_STATE,
            409,
        )
        assert_envelope(
            api.supersede_price_change_file(
                file_id, factories.supersede_payload(file_id), admin_headers
            ),
            ERR_SUPERSEDING_FILE_INVALID,
            422,
        )

        reread = build.read_file(file_id)
        assert reread["version"] == distributed["version"]
        assert reread["status"] == "DISTRIBUTED"

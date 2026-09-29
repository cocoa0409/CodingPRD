"""Cross-cutting layers: version pinning, rolling windows and immediate consistency."""

from test_helpers import (
    assert_instant_is,
    assert_money_cents,
    assert_pct,
    assert_posture,
    factories,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_INSPECTION_INVALID_STATE,
    ERR_STALE_INSPECTION_VERSION,
    ERR_STALE_PRICE_CHANGE_FILE_VERSION,
    ERR_STALE_SCANNER_AUDIT_VERSION,
)
from test_helpers.constants import (
    ROLE_CODE_LABEL_ASSOCIATE,
    ROLE_CODE_PRICE_AUDITOR,
    ROLE_CODE_STORE_MANAGER,
)


class TestOptimisticConcurrencyAcrossAllThreePins:
    def test_each_pin_guards_its_own_parent_and_only_a_real_write_advances_the_version(
        self, api, build, officer_headers, desk_headers
    ):
        """Three pins, three error ids, three bump patterns — and a claim that bumps nothing.

        PRD 2.5: "If the supplied value does not equal the file's current
        `version`, the create is rejected with
        `ERR_STALE_PRICE_CHANGE_FILE_VERSION` (HTTP 412)."
        PRD 3.3: "On success, `distributed_at` is stamped with the current
        instant, the unit-price fields of every line that is not `WITHDRAWN` are
        recomputed and re-stored, and the batch's `version` advances by one."
        PRD 3.3: "Creating the store-level execution task for a line moves it
        `PENDING → TASKED`, and that same event may auto-advance its owning batch
        `DISTRIBUTED → PARTIALLY_EXECUTED` — the batch itself changes nothing but
        its status, `updated_at` and `version` on that hop."
        PRD 3.7: "A store manager submits the store's answer by supplying a
        `remediation_summary` together with the pinned
        `expected_regulatory_inspection_version`, moving the inspection to
        `RESPONSE_SUBMITTED` from either `FINDINGS_ISSUED` or
        `RESPONSE_REJECTED`; any other state is refused with
        `ERR_INSPECTION_INVALID_STATE`."
        PRD 2.5: "Because issuing findings and every individual finding
        transition silently advance the inspection's `version`, this pin is the
        mechanism that forces a store manager to re-read the finding set before
        answering it."
        PRD 2.5: "A mismatch with the inspection's current `version` is rejected
        with `ERR_STALE_INSPECTION_VERSION` (HTTP 412)."
        PRD 3.7: "Each submission raises `response_round` by one, overwrites
        `remediation_summary` with the latest narrative, and advances the
        inspection's `version` by one."
        PRD 2.5: "Multiple claims against different scan lines of the same audit
        are legitimate, so the request cannot be refused on state grounds; the
        stale version is the only signal that the audit was reopened and reclosed
        under a different rate variant after the client read it."
        PRD 2.5: "A mismatch with the audit's current `version` is rejected with
        `ERR_STALE_SCANNER_AUDIT_VERSION` (HTTP 412)."
        PRD 3.5: "On success the verdict is withdrawn: `outcome` returns to
        `PENDING`, and `error_rate_pct`, `rate_variant_applied`,
        `gross_error_rate_pct`, `net_overcharge_rate_pct` and `closed_at` all
        return to null."
        PRD 3.8: "Under `REFUND_DIFFERENCE_ONLY` the gross amount is that
        variance alone."

        Design: Corner/Cross-Cutting Complexity Layers/corner_all_three_occ_rules_reject_the_stale_version_and_bump_only_on_success
        """
        jurisdiction_id = build.jurisdiction(code="US-CA", grace_period_hours=48)
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
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        manager_headers = build.manager(manager_id)
        auditor_headers = build.auditor(auditor_id)

        file_record = build.price_change_file(
            jurisdiction_id, [store_id], file_number="PCF-1"
        )
        line_one = build.add_line(
            file_record["id"],
            "00000000022001",
            449,
            499,
            1,
            "GAL",
            item_description="Milk 1 GAL",
            category_code="DAIRY",
        )
        line_two = build.add_line(
            file_record["id"],
            "00000000022002",
            549,
            599,
            8,
            "OZ",
            item_description="Cheese 8 OZ",
            category_code="DAIRY",
        )
        pre_distribute_version = build.file_version(file_record["id"])
        distributed = build.distribute(file_record["id"])
        assert distributed["status"] == "DISTRIBUTED"
        assert distributed["version"] == pre_distribute_version + 1
        distributed_version = distributed["version"]

        stale_file_probe = api.create_label_task(
            file_record["id"],
            factories.label_task_payload(
                store_id,
                line_one["id"],
                aisle_id,
                associate_id,
                "2026-08-02T08:00:00Z",
                "2026-08-02T10:00:00Z",
                pre_distribute_version,
            ),
            manager_headers,
        )
        validate_error(
            stale_file_probe, ERR_STALE_PRICE_CHANGE_FILE_VERSION, 412
        )

        first_task = validate_success(
            api.create_label_task(
                file_record["id"],
                factories.label_task_payload(
                    store_id,
                    line_one["id"],
                    aisle_id,
                    associate_id,
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T10:00:00Z",
                    distributed_version,
                ),
                manager_headers,
            ),
            201,
        )
        assert first_task["id"]

        after_first_task = build.read_file(file_record["id"])
        assert after_first_task["status"] == "PARTIALLY_EXECUTED"
        assert after_first_task["version"] == distributed_version + 1
        hopped_version = after_first_task["version"]

        validate_error(
            api.create_label_task(
                file_record["id"],
                factories.label_task_payload(
                    store_id,
                    line_two["id"],
                    aisle_id,
                    associate_id,
                    "2026-08-02T12:00:00Z",
                    "2026-08-02T14:00:00Z",
                    distributed_version,
                ),
                manager_headers,
            ),
            ERR_STALE_PRICE_CHANGE_FILE_VERSION,
            412,
        )

        second_task = validate_success(
            api.create_label_task(
                file_record["id"],
                factories.label_task_payload(
                    store_id,
                    line_two["id"],
                    aisle_id,
                    associate_id,
                    "2026-08-02T12:00:00Z",
                    "2026-08-02T14:00:00Z",
                    hopped_version,
                ),
                manager_headers,
            ),
            201,
        )
        assert second_task["id"]

        after_second_task = build.read_file(file_record["id"])
        assert after_second_task["status"] == "PARTIALLY_EXECUTED"
        assert after_second_task["version"] == hopped_version

        audit = build.scanner_audit(
            store_id,
            aisle_id,
            auditor_id,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T09:00:00Z",
            audit_type="REGULATORY",
            actor_headers=auditor_headers,
        )
        observation = build.scan_line(
            audit["id"], "00000000022001", 449, 499, auditor_headers
        )
        assert observation["classification"] == "OVERCHARGE"
        first_close = build.close_audit(audit["id"], auditor_headers, "GROSS_MISMATCH")
        assert first_close["outcome"] == "FAIL"
        assert_pct(first_close["error_rate_pct"], 100.00)
        audit_version_one = first_close["version"]

        first_claim = validate_success(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    observation["id"], "CUST-1", audit_version_one
                ),
                desk_headers,
            ),
            201,
        )
        assert first_claim["status"] == "PENDING"
        assert_money_cents(first_claim["claimed_amount_cents"], 50)

        assert build.read_audit(audit["id"])["version"] == audit_version_one

        inspection = validate_success(
            api.create_regulatory_inspection(
                factories.inspection_payload(
                    store_id,
                    audit["id"],
                    inspector_ref="INS-2026-17",
                    inspection_date="2026-08-01T10:00:00Z",
                ),
                officer_headers,
            ),
            201,
        )
        assert inspection["status"] == "SCHEDULED"
        inspection_version_zero = inspection["version"]

        validate_error(
            api.submit_inspection_response(
                inspection["id"],
                factories.inspection_response_payload(
                    "premature", inspection_version_zero
                ),
                manager_headers,
            ),
            ERR_INSPECTION_INVALID_STATE,
            409,
        )

        issued = validate_success(
            api.issue_inspection_findings(
                inspection["id"],
                factories.issue_findings_payload(
                    [factories.finding_input("SCANNER_ERROR_RATE", "MAJOR", 1, "A01")]
                ),
                officer_headers,
            )
        )
        assert issued["status"] == "FINDINGS_ISSUED"
        assert issued["version"] == inspection_version_zero + 1
        inspection_version_one = issued["version"]

        validate_error(
            api.submit_inspection_response(
                inspection["id"],
                factories.inspection_response_payload(
                    "Relabelled the aisle.", inspection_version_zero
                ),
                manager_headers,
            ),
            ERR_STALE_INSPECTION_VERSION,
            412,
        )

        responded = validate_success(
            api.submit_inspection_response(
                inspection["id"],
                factories.inspection_response_payload(
                    "Relabelled the aisle.", inspection_version_one
                ),
                manager_headers,
            )
        )
        assert responded["status"] == "RESPONSE_SUBMITTED"
        assert responded["response_round"] == 1
        assert responded["version"] == inspection_version_one + 1

        reopened = build.reopen_audit(
            audit["id"], "sample disputed", officer_headers
        )
        assert reopened["status"] == "REOPENED"
        assert reopened["outcome"] == "PENDING"
        assert reopened["closed_at"] is None
        assert reopened["error_rate_pct"] is None
        assert reopened["rate_variant_applied"] is None
        assert reopened["gross_error_rate_pct"] is None
        assert reopened["net_overcharge_rate_pct"] is None
        assert reopened["reopen_count"] == 1
        assert reopened["version"] == audit_version_one + 1
        audit_version_two = reopened["version"]

        second_close = build.close_audit(audit["id"], auditor_headers, "GROSS_MISMATCH")
        assert second_close["outcome"] == "FAIL"
        assert second_close["version"] == audit_version_two + 1
        audit_version_three = second_close["version"]

        validate_error(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    observation["id"], "CUST-2", audit_version_one
                ),
                desk_headers,
            ),
            ERR_STALE_SCANNER_AUDIT_VERSION,
            412,
        )

        second_claim = validate_success(
            api.create_refund_claim(
                factories.refund_claim_payload(
                    observation["id"], "CUST-2", audit_version_three
                ),
                desk_headers,
            ),
            201,
        )
        assert second_claim["status"] == "PENDING"
        assert_money_cents(second_claim["claimed_amount_cents"], 50)

        assert build.read_audit(audit["id"])["version"] == audit_version_three


class TestThirtyDayFailedAuditWindow:
    def test_the_window_edge_is_inclusive_and_a_reopen_withdraws_the_failing_verdict(
        self, api, build, admin_headers, officer_headers
    ):
        """One audit separates RESTRICTED from FROZEN, and the rolling edge is exact to the second.

        PRD 2.6: "`failed_audit_count_30d` is the number of this store's scanner
        audits that are `CLOSED`, carry outcome `FAIL`, and whose closing instant
        is at or after the instant thirty days before the current instant."
        PRD 2.6: "The window is measured backwards from the logical clock and its
        lower edge is inclusive."
        PRD 2.6: "The posture becomes `FROZEN` when at least one escalated
        finding exists, **or** when the open finding count is at least 3, **or**
        when the thirty-day failed-audit count is at least 2."
        PRD 2.6: "Otherwise the posture becomes `RESTRICTED` when the open
        finding count is at least 1, **or** when the thirty-day failed-audit
        count is exactly 1, **or** when the label backlog is at least 5, **or**
        when at least one signage violation exists."
        PRD 3.5: "Closing also stamps `closed_at` with the current instant and
        refreshes the audited aisle's `last_audit_closed_at` to the same instant."
        PRD 3.5: "When the aisle has no assigned associate, or the referenced
        associate is already `SUSPENDED`, **no accountability action is created at
        all**: the audit still closes with `FAIL`, the store's failed-audit count
        still rises and its posture is still recomputed, and the failure is
        simply unattributed."
        PRD 3.5: "The store's `failed_audit_count_30d` is then recomputed and its
        posture recomputed — a reopened failure leaves the posture inputs, so
        reopening can relax a frozen store back to restricted or open until the
        audit closes again."
        PRD 2.6: "A dedicated read capability exists specifically so that a
        client can reconcile every derived counter against the underlying rows:
        it recomputes the label backlog and the posture from live data before
        returning the store projection, and is therefore the authoritative way to
        observe posture drift after a sequence of cascades."

        Design: Corner/Cross-Cutting Complexity Layers/corner_thirty_day_posture_window_is_inclusive_and_a_reopen_withdraws_the_verdict
        """
        jurisdiction = build.jurisdiction_record(code="US-CA", name="California")
        assert_pct(jurisdiction["scanner_error_rate_threshold_pct"], 2.0)
        store = validate_success(
            api.create_store(
                factories.store_payload(
                    jurisdiction["id"], store_number="S001", name="Bay Street"
                ),
                admin_headers,
            ),
            201,
        )
        assert_posture(store, "OPEN")
        store_id = store["id"]
        auditor_id = build.certified(
            store_id,
            ROLE_CODE_PRICE_AUDITOR,
            module_code="AUDIT_101",
            employee_number="E-PA1",
            full_name="Pat Auditor",
        )
        auditor_headers = build.auditor(auditor_id)
        first_aisle = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")
        second_aisle = build.aisle(store_id, aisle_code="A02", category_code="BAKERY")

        first_audit = build.scanner_audit(
            store_id,
            first_aisle,
            auditor_id,
            scan_window_start="2026-08-01T08:00:00Z",
            scan_window_end="2026-08-01T09:00:00Z",
            actor_headers=auditor_headers,
        )
        build.scan_line(first_audit["id"], "00000000023001", 449, 499, auditor_headers)
        first_close = build.close_audit(first_audit["id"], auditor_headers)
        assert_pct(first_close["error_rate_pct"], 100.00)
        assert first_close["outcome"] == "FAIL"
        assert_instant_is(first_close["closed_at"], "2026-08-01T00:00:00Z")

        after_first = build.read_store(store_id)
        assert after_first["failed_audit_count_30d"] == 1
        assert_posture(after_first, "RESTRICTED")

        build.set_clock("2026-08-05T00:00:00Z")
        second_audit = build.scanner_audit(
            store_id,
            second_aisle,
            auditor_id,
            scan_window_start="2026-08-05T08:00:00Z",
            scan_window_end="2026-08-05T09:00:00Z",
            actor_headers=auditor_headers,
        )
        build.scan_line(second_audit["id"], "00000000023002", 549, 599, auditor_headers)
        second_close = build.close_audit(second_audit["id"], auditor_headers)
        assert second_close["outcome"] == "FAIL"
        assert_instant_is(second_close["closed_at"], "2026-08-05T00:00:00Z")

        after_second = build.read_store(store_id)
        assert after_second["failed_audit_count_30d"] == 2
        assert_posture(after_second, "FROZEN")

        reopened = build.reopen_audit(
            second_audit["id"], "auditor scanned the wrong shelf", officer_headers
        )
        assert reopened["status"] == "REOPENED"
        assert reopened["outcome"] == "PENDING"
        assert reopened["closed_at"] is None
        assert reopened["error_rate_pct"] is None
        assert reopened["reopen_count"] == 1

        after_reopen = build.read_store(store_id)
        assert after_reopen["failed_audit_count_30d"] == 1
        assert_posture(after_reopen, "RESTRICTED")

        third_close = build.close_audit(second_audit["id"], auditor_headers)
        assert third_close["outcome"] == "FAIL"
        assert_instant_is(third_close["closed_at"], "2026-08-05T00:00:00Z")

        after_reclose = build.read_store(store_id)
        assert after_reclose["failed_audit_count_30d"] == 2
        assert_posture(after_reclose, "FROZEN")

        build.set_clock("2026-08-31T00:00:00Z")
        on_the_edge = validate_success(
            api.get_store_compliance_summary(store_id, officer_headers)
        )
        assert_posture(on_the_edge, "FROZEN")

        build.set_clock("2026-08-31T00:00:01Z")
        one_second_past = validate_success(
            api.get_store_compliance_summary(store_id, officer_headers)
        )
        assert_posture(one_second_past, "RESTRICTED")

        stored_after_the_clock_moved = build.read_store(store_id)
        assert stored_after_the_clock_moved["failed_audit_count_30d"] == 2
        assert_posture(stored_after_the_clock_moved, "FROZEN")


class TestDerivedFieldsSettleOnTheFirstRead:
    def test_the_projection_the_sweep_and_the_compensation_all_land_inside_their_own_request(
        self, build
    ):
        """Nothing lags: the amendment re-projects, the sweep reports, the removal restores.

        PRD 2.8: "Cascades in this service are **immediate and synchronous**: by
        the time a response is returned, every derived counter, every propagated
        state and every cascade-created record already reflects the operation."
        PRD 2.4: "`version` is an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that resource, again
        including cascade-driven mutations."
        PRD 3.6: "`missing_disclosure_codes` is the set difference between the
        jurisdiction's `signage_disclosure_codes` and the sign's own
        `disclosure_codes`, compared by exact string equality and **ordered as
        the jurisdiction declares them** rather than sorted — if the jurisdiction
        lists `UNIT_PRICE` before `END_DATE` and the sign carries neither, the
        missing list reads `UNIT_PRICE` then `END_DATE`."
        PRD 3.6: "On success `posted_at` is stamped with the current instant and
        `compliance_state` becomes `COMPLIANT`."
        PRD 3.1: "The most consequential amendment is to
        `signage_disclosure_codes`: because a sign's missing-disclosure set is
        derived rather than copied, adding a required code re-derives
        `missing_disclosure_codes` and the compliance verdict for every
        non-removed sign in the jurisdiction and then recomputes the posture of
        every store affected."
        PRD 2.6: "`signage_violation_count` is the number of this store's
        promotional signs whose status is either `EXPIRED_PENDING_REMOVAL` or
        `NON_COMPLIANT`."
        PRD 3.6: "A `POSTED` sign whose promotion is still running but whose
        `missing_disclosure_codes` is non-empty transitions `POSTED →
        NON_COMPLIANT` and its `compliance_state` becomes `MISSING_DISCLOSURE`."
        PRD 3.6: "The sweep reports what it did: a `swept_count` of signs
        examined, an `expired_count` and a `non_compliant_count` of transitions
        applied, and the store's resulting `compliance_posture`."
        PRD 3.6: "Removal stamps `removed_at` with the current instant, resets
        `compliance_state` to `NOT_APPLICABLE`, and recomputes the store's
        `signage_violation_count` and then its posture; when the sign was swept
        into a violation state, this is exactly the compensating operation that
        returns the store's violation count to where it stood before."

        Design: Corner/Consistency Model/corner_every_derived_field_is_final_on_the_first_read_after_the_write
        """
        jurisdiction = build.jurisdiction_record(
            code="US-CA", name="California", signage_disclosure_codes=[]
        )
        assert jurisdiction["signage_disclosure_codes"] == []
        jurisdiction_version = jurisdiction["version"]
        store_id = build.store(
            jurisdiction["id"], store_number="S001", name="Bay Street"
        )
        manager_id = build.certified(
            store_id,
            ROLE_CODE_STORE_MANAGER,
            employee_number="E-SM1",
            full_name="Sam Manager",
        )
        manager_headers = build.manager(manager_id)
        aisle_id = build.aisle(store_id, aisle_code="A01", category_code="DAIRY")

        sign = build.promo_signage(
            store_id,
            aisle_id,
            ["UNIT_PRICE_SHOWN"],
            actor_headers=manager_headers,
            sign_code="SG-1",
            promo_start_at="2026-08-01T00:00:00Z",
            promo_end_at="2026-08-20T00:00:00Z",
        )
        assert sign["missing_disclosure_codes"] == []
        posted = build.post_signage(sign["id"], manager_headers)
        assert posted["status"] == "POSTED"
        assert posted["compliance_state"] == "COMPLIANT"

        amended = build.amend_jurisdiction(
            jurisdiction["id"],
            {"signage_disclosure_codes": ["EXPIRY_DATE", "UNIT_PRICE_SHOWN"]},
        )
        assert amended["signage_disclosure_codes"] == [
            "EXPIRY_DATE",
            "UNIT_PRICE_SHOWN",
        ]
        assert amended["version"] == jurisdiction_version + 1

        reprojected = build.read_signage(sign["id"])
        assert reprojected["missing_disclosure_codes"] == ["EXPIRY_DATE"]
        assert reprojected["status"] == "POSTED"
        assert reprojected["compliance_state"] == "COMPLIANT"

        before_the_sweep = build.read_store(store_id)
        assert before_the_sweep["signage_violation_count"] == 0
        assert_posture(before_the_sweep, "OPEN")

        swept = build.sweep(store_id, manager_headers)
        assert swept["swept_count"] == 1
        assert swept["expired_count"] == 0
        assert swept["non_compliant_count"] == 1
        assert swept["compliance_posture"] == "RESTRICTED"

        after_the_sweep = build.read_signage(sign["id"])
        assert after_the_sweep["status"] == "NON_COMPLIANT"
        assert after_the_sweep["compliance_state"] == "MISSING_DISCLOSURE"
        assert after_the_sweep["missing_disclosure_codes"] == ["EXPIRY_DATE"]

        store_after_the_sweep = build.read_store(store_id)
        assert store_after_the_sweep["signage_violation_count"] == 1
        assert_posture(store_after_the_sweep, "RESTRICTED")

        removed = build.remove_signage(sign["id"], manager_headers)
        assert removed["status"] == "REMOVED"
        assert removed["compliance_state"] == "NOT_APPLICABLE"
        assert_instant_is(removed["removed_at"], "2026-08-01T00:00:00Z")

        compensated = build.read_store(store_id)
        assert compensated["signage_violation_count"] == 0
        assert_posture(compensated, "OPEN")

        recomputed = build.read_summary(store_id)
        assert recomputed["signage_violation_count"] == 0
        assert_posture(recomputed, "OPEN")

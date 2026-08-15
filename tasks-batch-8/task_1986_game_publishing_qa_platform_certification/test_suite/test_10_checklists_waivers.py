"""Compliance checklist verification, waiver protocol with OCC and
segregation of duties, and the dual readiness readings (PRD §3.6, §2.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_checklist,
    get_package,
    make_certification_lead_headers,
    make_compliance_manager_headers,
    setup_submittable_package,
    verify_item,
    waive_item,
    validate_error,
    validate_success,
)

CM_HEADERS = TEST_USERS["compliance_manager_headers"]


def _item(checklist, requirement_code):
    for item in checklist["items"]:
        if item["requirement_code"] == requirement_code:
            return item
    raise AssertionError(f"item {requirement_code} not found")


def _package_with_failed_item():
    """ASSEMBLING package whose checklist has TRC-PS-02 FAILED."""
    ctx = setup_submittable_package(title_code="SM-WVR",
                                    cert_budget_total_cents=500000,
                                    verify_checklist=False)
    verify_item(ctx["checklist_id"], "TRC-PS-02", "FAILED")
    return ctx


class TestDualReadiness:
    def _setup_partial_checklist(self):
        """TRC-PS-02 PASSED and TRC-PS-04 NA; TRC-PS-01 (REQUIRED,
        auto-verifiable) and TRC-PS-03 (REQUIRED, manual) left UNVERIFIED."""
        ctx = setup_submittable_package(title_code="DUAL-R",
                                        cert_budget_total_cents=1_000_000,
                                        verify_checklist=False)
        verify_item(ctx["checklist_id"], "TRC-PS-02", "PASSED")
        verify_item(ctx["checklist_id"], "TRC-PS-04", "NA")
        return ctx

    def test_optimistic_reading_counts_auto_verifiable_unverified(self, api):
        """PRD §3.6: "The optimistic reading, `readiness_optimistic_pct`,
        additionally counts `UNVERIFIED` items whose `auto_verifiable` flag is
        true as if they had passed — the planning reading used during
        assembly."
        PRD §3.6: "For `PS5` the catalog seeds four items: `TRC-PS-01`
        (`REQUIRED`, auto-verifiable), `TRC-PS-02` (`REQUIRED`, manual),
        `TRC-PS-03` (`REQUIRED`, manual), and `TRC-PS-04` (`RECOMMENDED`,
        manual)."

        Design: Difficulty/dual_variant_calc/cert_readiness_optimistic_vs_strict_diverge
        """
        ctx = self._setup_partial_checklist()
        package = get_package(ctx["package"]["id"])
        # (1 PASSED + 1 NA + 1 auto-UNVERIFIED) / 4
        assert package["readiness_optimistic_pct"] == 75.00

    def test_strict_reading_counts_terminal_states_only(self, api):
        """PRD §3.6: "The strict reading, `readiness_strict_pct`, is one
        hundred times the number of items in `PASSED`, `WAIVED`, or `NA`,
        divided by the total item count — the compliance-final reading
        enforced at submission."

        Design: Difficulty/dual_variant_calc/cert_readiness_optimistic_vs_strict_diverge
        """
        ctx = self._setup_partial_checklist()
        package = get_package(ctx["package"]["id"])
        # (1 PASSED + 1 NA) / 4
        assert package["readiness_strict_pct"] == 50.00
        assert package["readiness_strict_pct"] != package["readiness_optimistic_pct"]

    def test_readiness_recomputed_on_every_item_edit(self, api):
        """PRD §3.6: "Every item edit recomputes the checklist counters and
        the owning package's readiness fields, and increments the checklist's
        `version`."

        Design: Corner/calculations/readiness_recomputed_per_verification
        """
        ctx = setup_submittable_package(title_code="CL-RDY",
                                        cert_budget_total_cents=500000,
                                        verify_checklist=False)
        verify_item(ctx["checklist_id"], "TRC-PS-02", "PASSED")
        package = get_package(ctx["package"]["id"])
        # Strict counts only the PASSED item; optimistic also counts the
        # auto-verifiable TRC-PS-01 still UNVERIFIED.
        assert package["readiness_strict_pct"] == 25.00
        assert package["readiness_optimistic_pct"] == 50.00
        verify_item(ctx["checklist_id"], "TRC-PS-01", "PASSED")
        package = get_package(ctx["package"]["id"])
        assert package["readiness_strict_pct"] == 50.00
        assert package["readiness_optimistic_pct"] == 50.00


class TestVerificationRules:
    def test_na_result_on_required_item_rejected(self, api):
        """PRD §3.6: "A result of `NA` is accepted only for `RECOMMENDED`
        items — marking a `REQUIRED` item not-applicable is rejected with
        `ERR_NA_NOT_ALLOWED_FOR_REQUIRED` (HTTP 400)."

        Design: Corner/validations/na_result_on_required_item_rejected
        """
        ctx = setup_submittable_package(title_code="VAL-NA",
                                        cert_budget_total_cents=500000,
                                        verify_checklist=False)
        resp = api.verify_checklist_item(
            ctx["checklist_id"],
            {"requirement_code": "TRC-PS-01", "result": "NA"},
            CM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_NA_NOT_ALLOWED_FOR_REQUIRED)
        assert get_checklist(ctx["checklist_id"])["unverified_count"] == 4

    def test_reverification_voids_pending_waiver(self, api):
        """PRD §3.6: "Re-verifying a `FAILED` item to `PASSED` has an extra
        effect: if the item had a `PENDING` waiver, that waiver is voided to
        `SUPERSEDED`."
        PRD §3.6: "The decision requires the item's `waiver_status` to be
        `PENDING` (`ERR_WAIVER_NOT_PENDING`)"

        Design: Corner/state_machines/waiver_pending_voided_by_reverification
        """
        ctx = _package_with_failed_item()
        waive_item(
            ctx["checklist_id"], "TRC-PS-02", "crash only on devkit wifi",
            headers=make_certification_lead_headers("u-7"),
        )
        checklist = verify_item(ctx["checklist_id"], "TRC-PS-02", "PASSED")
        item = _item(checklist, "TRC-PS-02")
        assert item["status"] == "PASSED"
        assert item["waiver_status"] == "SUPERSEDED"
        assert checklist["passed_count"] == 1
        resp = api.decide_waiver(
            ctx["checklist_id"],
            {"requirement_code": "TRC-PS-02", "decision": "APPROVED"},
            make_compliance_manager_headers("u-9"),
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_PENDING)


class TestWaiverProtocol:
    def test_waiver_approval_moves_item_to_waived(self, api):
        """PRD §3.6: "Approving moves the item to `WAIVED` with
        `waiver_status` `APPROVED`; rejecting leaves the item `FAILED` with
        `waiver_status` `REJECTED`. Either decision recomputes counters and
        readiness and increments the checklist `version`."
        PRD §3.6: "The strict reading, `readiness_strict_pct`, is one hundred
        times the number of items in `PASSED`, `WAIVED`, or `NA`, divided by
        the total item count"

        Design: Corner/state_machines/waiver_approval_marks_item_waived
        """
        ctx = _package_with_failed_item()
        waive_item(
            ctx["checklist_id"], "TRC-PS-02", "devkit-only audio dropout",
            headers=make_certification_lead_headers("u-7"),
        )
        checklist = validate_success(
            api.decide_waiver(
                ctx["checklist_id"],
                {"requirement_code": "TRC-PS-02", "decision": "APPROVED"},
                make_compliance_manager_headers("u-9"),
            )
        )
        item = _item(checklist, "TRC-PS-02")
        assert item["status"] == "WAIVED"
        assert item["waiver_status"] == "APPROVED"
        assert checklist["waived_count"] == 1
        assert checklist["failed_count"] == 0
        # One of four items pass-equivalent.
        assert get_package(ctx["package"]["id"])["readiness_strict_pct"] == 25.00

    def test_waiver_request_requires_failed_item(self, api):
        """PRD §3.6: "Requesting a waiver for an item in any state other than
        `FAILED` is rejected with `ERR_WAIVER_REQUIRES_FAILED_ITEM`."

        Design: Corner/state_machines/waiver_requires_failed_item
        """
        ctx = setup_submittable_package(title_code="SM2-WVR",
                                        cert_budget_total_cents=500000,
                                        verify_checklist=False)
        checklist = get_checklist(ctx["checklist_id"])
        resp = api.waive_checklist_item(
            ctx["checklist_id"],
            {
                "requirement_code": "TRC-PS-01",
                "justification": "cannot waive an unverified item",
                "expected_checklist_version": checklist["version"],
            },
            TEST_USERS["certification_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_REQUIRES_FAILED_ITEM)
        assert get_checklist(ctx["checklist_id"])["version"] == checklist["version"]

    def test_waiver_decider_must_not_be_requester(self, api):
        """PRD §3.6: "The decision requires the item's `waiver_status` to be
        `PENDING` (`ERR_WAIVER_NOT_PENDING`), and segregation of duties binds
        here too: the decider's `X-User-ID` must differ from
        `waiver_requested_by_user_id` (`ERR_SELF_WAIVER_DECISION`, HTTP 403)."

        Design: Corner/rbac/waiver_decision_same_user_rejected
        """
        ctx = setup_submittable_package(title_code="RB-SOW",
                                        cert_budget_total_cents=500000,
                                        verify_checklist=False)
        verify_item(ctx["checklist_id"], "TRC-PS-02", "FAILED")
        waive_item(
            ctx["checklist_id"], "TRC-PS-02",
            "devkit-only issue, retail unaffected",
            headers=make_certification_lead_headers("u-7"),
        )
        resp = api.decide_waiver(
            ctx["checklist_id"],
            {"requirement_code": "TRC-PS-02", "decision": "APPROVED"},
            make_compliance_manager_headers("u-7"),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_WAIVER_DECISION)
        item = _item(get_checklist(ctx["checklist_id"]), "TRC-PS-02")
        assert item["status"] == "FAILED"
        assert item["waiver_status"] == "PENDING"
        checklist = validate_success(
            api.decide_waiver(
                ctx["checklist_id"],
                {"requirement_code": "TRC-PS-02", "decision": "APPROVED"},
                make_compliance_manager_headers("u-8"),
            )
        )
        assert checklist["waived_count"] == 1


class TestWaiverOcc:
    def test_stale_checklist_version_rejected_on_waive(self, api):
        """PRD §2.6: "Second, requesting a waiver for a checklist item
        requires the request to carry `expected_checklist_version`, the
        caller's last-observed `version` of the compliance checklist. A
        mismatch with the checklist's current `version` — the checklist has
        been mutated by item verifications or by a superseding waiver since
        the caller read it — is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.6: "Every item edit recomputes the checklist counters and the
        owning package's readiness fields, and increments the checklist's
        `version`."

        Design: Corner/cross_cutting_layers/occ_waiver_stale_checklist_version
        """
        ctx = setup_submittable_package(title_code="LYR-OCCW",
                                        cert_budget_total_cents=500000,
                                        verify_checklist=False)
        observed = get_checklist(ctx["checklist_id"])["version"]
        assert observed == 1  # freshly seeded
        # A verification mutates the checklist and bumps its version to 2.
        verify_item(ctx["checklist_id"], "TRC-PS-02", "FAILED")
        resp = api.waive_checklist_item(
            ctx["checklist_id"],
            {
                "requirement_code": "TRC-PS-02",
                "justification": "stale attempt",
                "expected_checklist_version": observed,
            },
            TEST_USERS["certification_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh = get_checklist(ctx["checklist_id"])["version"]
        checklist = validate_success(
            api.waive_checklist_item(
                ctx["checklist_id"],
                {
                    "requirement_code": "TRC-PS-02",
                    "justification": "fresh attempt after re-read",
                    "expected_checklist_version": fresh,
                },
                TEST_USERS["certification_lead_headers"],
            )
        )
        assert checklist["version"] == fresh + 1
        item = _item(checklist, "TRC-PS-02")
        assert item["waiver_status"] == "PENDING"

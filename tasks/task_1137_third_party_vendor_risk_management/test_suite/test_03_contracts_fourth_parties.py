"""Contract execution gates (clause completeness, fourth-party acknowledgement,
OCC), fourth-party parent and tier rules, temporal ordering, immediate
consistency, and clock-driven contract expiry."""
from test_helpers import (
    ApiErrorId,
    create_engagement,
    create_fourth_party_payload,
    create_vendor,
    get_engagement,
    reset_clock,
    setup_active_engagement,
    setup_engagement_with_approved_dd,
    tier_change_vendor,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import VRM, RO, ADMIN

CLOCK = "2026-05-01T00:00:00Z"


def _contract_payload(**overrides):
    payload = {
        "contract_reference": "C-001",
        "effective_date": "2026-05-01T00:00:00Z",
        "expiry_date": "2027-05-01T00:00:00Z",
        "has_right_to_audit_clause": False,
        "has_sla_terms": True,
        "has_exit_plan_section": False,
        "sla_uptime_pct": 99.5,
        "breach_cure_window_days": 30,
        "renewal_notice_days": 60,
    }
    payload.update(overrides)
    return payload


class TestContractClauseGates:
    def test_execute_rejected_without_sla_terms(self, api):
        """PRD §3.4: "`has_sla_terms` must be true on every tier (otherwise
        `ERR_MISSING_SLA_TERMS`, HTTP 422)"

        Design: Corner/validations/contract_clause_missing_sla
        """
        ctx = setup_engagement_with_approved_dd(vendor_name="SlaMiss")
        contract = validate_success(
            api.create_contract(ctx["engagement"]["id"], _contract_payload(has_sla_terms=False), VRM),
            201,
        )
        current = get_engagement(ctx["engagement"]["id"])
        res = api.execute_contract(
            contract["id"], {"expected_engagement_version": current["version"]}, RO
        )
        validate_error(res, ApiErrorId.ERR_MISSING_SLA_TERMS.value)

    def test_execute_rejected_without_audit_clause_on_tier1(self, api):
        """PRD §3.4: "if the vendor's `criticality_tier` is `TIER_1_CRITICAL` or
        `TIER_2_HIGH` then `has_right_to_audit_clause` must be true (otherwise
        `ERR_MISSING_AUDIT_CLAUSE`, HTTP 422)"

        Design: Corner/validations/contract_clause_missing_audit_tier1
        """
        ctx = setup_engagement_with_approved_dd(
            vendor_name="AudMiss", category="CLOUD_INFRA", sensitivity="REGULATED"
        )
        tier_change_vendor(ctx["vendor"]["id"], "TIER_1_CRITICAL", reason="crit")
        contract = validate_success(
            api.create_contract(
                ctx["engagement"]["id"],
                _contract_payload(
                    contract_reference="AM-C1",
                    has_right_to_audit_clause=False,
                    has_exit_plan_section=True,
                    sla_uptime_pct=99.99,
                ),
                VRM,
            ),
            201,
        )
        current = get_engagement(ctx["engagement"]["id"])
        res = api.execute_contract(
            contract["id"], {"expected_engagement_version": current["version"]}, RO
        )
        validate_error(res, ApiErrorId.ERR_MISSING_AUDIT_CLAUSE.value)

    def test_execute_rejected_without_exit_plan_on_tier1(self, api):
        """PRD §3.4: "if the vendor is `TIER_1_CRITICAL` then
        `has_exit_plan_section` must be true (otherwise
        `ERR_MISSING_EXIT_PLAN`, HTTP 422)"

        Design: Corner/validations/contract_clause_missing_exit_plan_tier1
        """
        ctx = setup_engagement_with_approved_dd(
            vendor_name="ExitMiss", category="CLOUD_INFRA", sensitivity="REGULATED"
        )
        tier_change_vendor(ctx["vendor"]["id"], "TIER_1_CRITICAL", reason="crit")
        contract = validate_success(
            api.create_contract(
                ctx["engagement"]["id"],
                _contract_payload(
                    contract_reference="EM-C1",
                    has_right_to_audit_clause=True,
                    has_exit_plan_section=False,
                    sla_uptime_pct=99.99,
                ),
                VRM,
            ),
            201,
        )
        current = get_engagement(ctx["engagement"]["id"])
        res = api.execute_contract(
            contract["id"], {"expected_engagement_version": current["version"]}, RO
        )
        validate_error(res, ApiErrorId.ERR_MISSING_EXIT_PLAN.value)

    def test_execute_blocked_by_pending_fourth_party(self, api):
        """PRD §3.4: "and finally every `FourthParty` on the engagement must
        have `acknowledgement_status` equal to `ACKNOWLEDGED` (otherwise
        `ERR_FOURTH_PARTY_PENDING`, HTTP 422)."
        PRD §3.5: "Contract execution is blocked while any fourth party remains
        in `PENDING`."

        Design: Corner/validations/contract_execute_blocked_by_pending_fourth_party
        """
        ctx = setup_engagement_with_approved_dd(vendor_name="FPBlock")
        contract = validate_success(
            api.create_contract(ctx["engagement"]["id"], _contract_payload(contract_reference="FPB-C1"), VRM),
            201,
        )
        validate_success(
            api.create_fourth_party(
                ctx["engagement"]["id"],
                create_fourth_party_payload(name="PendingSub", service_provided="sub"),
                VRM,
            ),
            201,
        )
        current = get_engagement(ctx["engagement"]["id"])
        res = api.execute_contract(
            contract["id"], {"expected_engagement_version": current["version"]}, RO
        )
        validate_error(res, ApiErrorId.ERR_FOURTH_PARTY_PENDING.value)


class TestFourthPartyRules:
    def test_regulated_pii_acknowledge_requires_high_tier(self, api):
        """PRD §3.5: "Acknowledgement is additionally tier-gated: if the fourth
        party's `data_access_level` is `REGULATED_PII`, the vendor's
        `criticality_tier` must be `TIER_1_CRITICAL` or `TIER_2_HIGH`;
        otherwise the acknowledgement is rejected with
        `ERR_FP_PII_TIER_TOO_LOW` (HTTP 422)."

        Design: Corner/validations/fourth_party_regulated_pii_requires_high_tier
        """
        reset_clock()
        vendor = create_vendor(name="PII")  # default tier TIER_3_STANDARD
        engagement = create_engagement(vendor["id"], code="PII-E1", sensitivity="REGULATED", spend=100)
        fp = validate_success(
            api.create_fourth_party(
                engagement["id"],
                create_fourth_party_payload(name="PII Sub", service_provided="proc", data_access_level="REGULATED_PII"),
                VRM,
            ),
            201,
        )
        res = api.acknowledge_fourth_party(fp["id"], RO)
        validate_error(res, ApiErrorId.ERR_FP_PII_TIER_TOO_LOW.value)

    def test_parent_fourth_party_cross_engagement_rejected(self, api):
        """PRD §3.5: "When `parent_fourth_party_id` is provided it must
        reference an existing `FourthParty` on the same engagement, and the
        resulting chain must be cycle-free (a fourth party cannot be its own
        ancestor); violations are rejected with `ERR_FP_PARENT_INVALID`
        (HTTP 422)."

        Design: Corner/validations/fourth_party_parent_cross_engagement_rejected
        """
        reset_clock()
        vendor = create_vendor(name="CrossRef")
        e1 = create_engagement(vendor["id"], code="CR-E1", sensitivity="PUBLIC", spend=100)
        e2 = create_engagement(vendor["id"], code="CR-E2", sensitivity="PUBLIC", spend=200)
        fp_a = validate_success(
            api.create_fourth_party(
                e1["id"], create_fourth_party_payload(name="FP-A", service_provided="x"), VRM
            ),
            201,
        )
        res = api.create_fourth_party(
            e2["id"],
            create_fourth_party_payload(
                name="FP-B", service_provided="y", parent_fourth_party_id=fp_a["id"]
            ),
            VRM,
        )
        validate_error(res, ApiErrorId.ERR_FP_PARENT_INVALID.value)


class TestContractTemporalAndOcc:
    def test_contract_expiry_before_effective_rejected(self, api):
        """PRD §3.4: "The expiry must be strictly later than the effective
        date, otherwise `ERR_TEMPORAL_ORDER` (HTTP 422)."

        Design: Corner/validations/contract_temporal_order_expiry_before_effective
        """
        ctx = setup_engagement_with_approved_dd(vendor_name="TempV")
        res = api.create_contract(
            ctx["engagement"]["id"],
            _contract_payload(
                contract_reference="TMP-C1",
                effective_date="2027-01-01T00:00:00Z",
                expiry_date="2026-01-01T00:00:00Z",
            ),
            VRM,
        )
        validate_error(res, ApiErrorId.ERR_TEMPORAL_ORDER.value)

    def test_stale_engagement_version_rejected_on_execute(self, api):
        """PRD §3.4: "the OCC check on the engagement's `version` is applied
        via `expected_engagement_version` (mismatch yields `ERR_STALE_VERSION`,
        HTTP 412)"
        PRD §2.7: "If the value does not match the parent entity's current
        `version`, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), protecting the client from overwriting changes it has not
        observed."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_contract_execute
        """
        ctx = setup_engagement_with_approved_dd(vendor_name="OccC")
        contract = validate_success(
            api.create_contract(ctx["engagement"]["id"], _contract_payload(contract_reference="OC-C1"), VRM),
            201,
        )
        observed = get_engagement(ctx["engagement"]["id"])
        res = api.execute_contract(
            contract["id"], {"expected_engagement_version": observed["version"] - 1}, RO
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)

    def test_execute_response_reflects_all_side_effects(self, api):
        """PRD §2.11: "All side effects triggered by a transition — tier
        recompute, posture recompute, monitoring-cycle scheduling, cascade into
        parent or sibling entities, audit-log writes — commit atomically within
        the triggering request."
        PRD §3.4: "On success the contract transitions `DRAFT → EXECUTED`,
        `version_pin_dd_package_id` is set to the id of the most recently
        approved `DueDiligencePackage` on the engagement (this pin is permanent
        for the life of the contract — subsequent modifications to that DD
        package do not revalidate the contract, only a new execution would),
        the engagement transitions `CONTRACTING → ACTIVE`, and the vendor's
        `composite_risk_score` is recomputed."

        Design: Corner/consistency_model/immediate_consistency_on_contract_execute_response
        """
        ctx = setup_engagement_with_approved_dd(vendor_name="ImmV")
        contract = validate_success(
            api.create_contract(ctx["engagement"]["id"], _contract_payload(contract_reference="IM-C1"), VRM),
            201,
        )
        current = get_engagement(ctx["engagement"]["id"])
        executed = validate_success(
            api.execute_contract(
                contract["id"], {"expected_engagement_version": current["version"]}, RO
            ),
            200,
        )
        assert executed["status"] == "EXECUTED"
        assert executed["version_pin_dd_package_id"] == ctx["package"]["id"]

        engagement_after = get_engagement(ctx["engagement"]["id"])
        assert engagement_after["lifecycle_status"] == "ACTIVE"


class TestContractScheduledExpiry:
    def test_contract_expires_when_clock_passes_expiry_after_engagement_exit(self, api):
        """PRD §3.4: "A contract in `EXECUTED` later transitions to `EXPIRED`
        automatically when the logical clock reaches or passes `expiry_date`
        and the engagement is no longer `ACTIVE` (that is, when
        `lifecycle_status` is `EXITING`, `EXITED`, or `TERMINATED_FOR_CAUSE`)."
        PRD §2.8: "any `Contract` in `EXECUTED` whose `expiry_date` is at or
        earlier than the new clock value transitions to `EXPIRED` provided its
        engagement is no longer `ACTIVE`."

        Design: Corner/cross_cutting_complexity_layers/scheduled_actions_clock_driven_contract_expiry
        """
        ctx = setup_active_engagement(
            vendor_name="SchedV",
            contract_overrides={"expiry_date": "2027-01-01T00:00:00Z"},
        )
        e_id = ctx["engagement"]["id"]
        c_id = ctx["contract"]["id"]
        validate_success(api.activate_vendor(ctx["vendor"]["id"], RO), 200)
        validate_success(api.initiate_exit(e_id, VRM), 200)
        validate_success(api.finalize_exit(e_id, RO), 200)
        engagement = get_engagement(e_id)
        assert engagement["lifecycle_status"] == "EXITED"

        validate_success(api.set_clock({"to_iso8601": "2027-06-01T00:00:00Z"}, ADMIN), 200)

        contract = validate_success(api.get_contract(c_id, RO), 200)
        assert contract["status"] == "EXPIRED"

"""Remediation workflow, defense-assembly gating, packet completeness, and the
campaign-level segregation of duties."""
from test_helpers import (
    ApiErrorId,
    USER_IDS,
    assert_defense_packet,
    begin_remediation,
    create_manual_remediation,
    get_campaign_version,
    resolve_remediation,
    setup_campaign_with_failed_sample,
    setup_delivered_packet_campaign,
    setup_mixed_outcome_campaign,
    TEST_USERS,
    validate_error,
    validate_success,
)

AUD1 = TEST_USERS["auditor_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]


class TestDefenseAssemblyGate:
    def test_defense_assembly_blocked_by_unremediated_failure(self, api, auditor_headers):
        """PRD §3.9: "Otherwise the `Auditor` begins defense assembly, moving the campaign `REMEDIATION` → `DEFENSE_ASSEMBLY`, which is permitted only when every `FAILED` sample in the campaign has at least one `RESOLVED` remediation action; otherwise the request is rejected with `ERR_UNREMEDIATED_FAILURES` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/campaign_defense_assembly_blocked_by_sample_state
        """
        bundle = setup_campaign_with_failed_sample()
        tid = bundle["tenant"]["id"]
        camp_id = bundle["campaign"]["id"]
        res = api.begin_defense_assembly(tid, camp_id, auditor_headers)
        validate_error(res, ApiErrorId.ERR_UNREMEDIATED_FAILURES, expected_status=409)
        camp = validate_success(api.get_audit_campaign(tid, camp_id, auditor_headers), 200)
        assert camp["status"] == "REMEDIATION", (
            "rejected defense assembly must leave the campaign in REMEDIATION")

    def test_defense_assembly_permitted_after_remediation_resolved(self, api, auditor_headers):
        """PRD §3.9: "Otherwise the `Auditor` begins defense assembly, moving the campaign `REMEDIATION` → `DEFENSE_ASSEMBLY`, which is permitted only when every `FAILED` sample in the campaign has at least one `RESOLVED` remediation action; otherwise the request is rejected with `ERR_UNREMEDIATED_FAILURES` (HTTP 409). The transition moves the tenant's `audit_posture` to `DEFENSE_ASSEMBLY` and creates the campaign's `AuditDefensePacket` in `DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/campaign_defense_assembly_blocked_by_sample_state
        """
        bundle = setup_campaign_with_failed_sample()
        tid = bundle["tenant"]["id"]
        camp_id = bundle["campaign"]["id"]
        sample_id = bundle["sample"]["id"]

        action = create_manual_remediation(tid, sample_id, action_type="WAIVE_SAMPLE",
                                           assigned_to_user_id=USER_IDS["COMPLIANCE_OFFICER"])
        begin_remediation(tid, action["id"], CO1)
        resolve_remediation(tid, camp_id, action["id"], CO1)

        camp = validate_success(api.begin_defense_assembly(tid, camp_id, auditor_headers), 200)
        assert camp["status"] == "DEFENSE_ASSEMBLY"
        packets = validate_success(api.get_defense_packet(tid, camp_id, auditor_headers), 200)
        assert len(packets) == 1, "defense assembly must create exactly one packet"
        assert packets[0]["status"] == "DRAFT"
        tenant = validate_success(api.get_tenant(tid, auditor_headers), 200)
        assert tenant["audit_posture"] == "DEFENSE_ASSEMBLY"


class TestDefensePacketCompleteness:
    def test_completeness_100_when_all_failures_remediated(self, api, auditor_headers):
        """PRD §3.9: "The `included_certificate_ids` list holds the certificates referenced by samples whose outcome is `PASSED` or `WAIVED`, sorted by certificate `created_at` ascending. The `missing_certificate_ids` list holds the certificates referenced by `FAILED` samples that still lack a `RESOLVED` remediation, sorted by certificate `created_at` ascending as well. The `completeness_score_pct` is one hundred times the number of included certificates divided by the combined count of included plus missing certificates, rounded half-up to a whole percent; when both lists are empty the score is 0."

        Design: Difficulty/combinatorial_formula/defense_packet_completeness_conditional_divisor
        """
        bundle = setup_mixed_outcome_campaign()
        tid = bundle["tenant"]["id"]
        samples = bundle["samples"]

        assembled = validate_success(
            api.assemble_defense_packet(tid, bundle["packet_id"], auditor_headers), 200)
        assert_defense_packet(assembled)
        assert assembled["status"] == "ASSEMBLED"
        # 2 PASSED + 1 WAIVED are included; the FAILED sample carries a RESOLVED
        # remediation, so it is missing from neither list requirement -> missing == [].
        expected_included = {samples[0]["certificate_id"], samples[1]["certificate_id"],
                             samples[2]["certificate_id"]}
        assert set(assembled["included_certificate_ids"]) == expected_included
        assert len(assembled["included_certificate_ids"]) == 3
        assert assembled["missing_certificate_ids"] == []
        # 100 * 3 / (3 + 0) = 100
        assert assembled["completeness_score_pct"] == 100

    def test_packet_at_completeness_100_delivers(self, api, auditor_headers):
        """PRD §3.9: "Delivery moves the packet `ASSEMBLED` → `DELIVERED` and demands a complete file: a packet whose `completeness_score_pct` is anything short of exactly 100 is rejected with `ERR_PACKET_INCOMPLETE` (HTTP 409)."

        Design: Difficulty/combinatorial_formula/defense_packet_completeness_conditional_divisor
        """
        bundle = setup_mixed_outcome_campaign()
        tid = bundle["tenant"]["id"]
        assembled = validate_success(
            api.assemble_defense_packet(tid, bundle["packet_id"], auditor_headers), 200)
        assert assembled["completeness_score_pct"] == 100
        delivered = validate_success(
            api.deliver_defense_packet(tid, bundle["packet_id"], auditor_headers), 200)
        assert delivered["status"] == "DELIVERED"


class TestRemediationResolveRestoresStanding:
    def test_resolve_restores_customer_audit_standing(self, api, auditor_headers):
        """PRD §3.9: "When the resolution leaves every `FAILED` sample for the customer with at least one `RESOLVED` action, the customer's audit standing moves `FAILED_SAMPLING` → `REMEDIATED` and the tenant's `audit_posture` is recomputed."

        Design: Difficulty/compensating_invariant/remediation_resolve_restores_customer_audit_standing
        """
        bundle = setup_campaign_with_failed_sample()
        tid = bundle["tenant"]["id"]
        cust_id = bundle["customer"]["id"]
        camp_id = bundle["campaign"]["id"]
        mid = validate_success(api.get_customer(tid, cust_id, auditor_headers), 200)
        assert mid["audit_standing"] == "FAILED_SAMPLING"

        action = create_manual_remediation(tid, bundle["sample"]["id"],
                                           action_type="WAIVE_SAMPLE",
                                           assigned_to_user_id=USER_IDS["COMPLIANCE_OFFICER"])
        begin_remediation(tid, action["id"], CO1)
        resolve_remediation(tid, camp_id, action["id"], CO1)

        post = validate_success(api.get_customer(tid, cust_id, auditor_headers), 200)
        assert post["audit_standing"] == "REMEDIATED", (
            "resolving the FAILED sample's remediation must clear FAILED_SAMPLING")

    def test_resolve_records_resolver_and_bumps_versions(self, api, auditor_headers):
        """PRD §3.9: "A successful resolution records the actor as `resolved_by_user_id` and increments the versions of both the action and the parent campaign."

        Design: Difficulty/compensating_invariant/remediation_resolve_restores_customer_audit_standing
        """
        bundle = setup_campaign_with_failed_sample()
        tid = bundle["tenant"]["id"]
        camp_id = bundle["campaign"]["id"]

        action = create_manual_remediation(tid, bundle["sample"]["id"],
                                           action_type="WAIVE_SAMPLE",
                                           assigned_to_user_id=USER_IDS["COMPLIANCE_OFFICER"])
        begun = begin_remediation(tid, action["id"], CO1)
        action_v_before = begun["version"]
        camp_v_before = get_campaign_version(tid, camp_id)

        resolved = resolve_remediation(tid, camp_id, action["id"], CO1)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_by_user_id"] == USER_IDS["COMPLIANCE_OFFICER"]
        assert resolved["version"] == action_v_before + 1, (
            "resolve must increment the action's version by exactly one")
        camp_after = validate_success(api.get_audit_campaign(tid, camp_id, auditor_headers), 200)
        assert camp_after["version"] == camp_v_before + 1, (
            "resolve must increment the parent campaign's version by exactly one")


class TestRemediationAndClosureSoD:
    def test_sod_assessor_is_resolver(self, api, compliance_officer_headers):
        """PRD §3.9: "For an `ASSESS_TAX` action, the segregation rule fires first: the resolver must differ from `assigned_to_user_id`, else `ERR_SOD_ASSESSOR_IS_RESOLVER` (HTTP 409) — an assessor may never close their own assessment."
        PRD §2.9: "A remediation action of type `ASSESS_TAX` may not be resolved by the officer to whom it is assigned; the acting `X-User-ID` is compared to the action's `assigned_to_user_id`."

        Design: Corner/errors/sod_assessor_is_resolver
        """
        bundle = setup_campaign_with_failed_sample()
        tid = bundle["tenant"]["id"]
        camp_id = bundle["campaign"]["id"]

        action = create_manual_remediation(tid, bundle["sample"]["id"],
                                           action_type="ASSESS_TAX",
                                           assigned_to_user_id=USER_IDS["COMPLIANCE_OFFICER"],
                                           assessment_amount_cents=1000)
        begin_remediation(tid, action["id"], CO1)
        # Fresh campaign version so the OCC check (§2.8) passes and the
        # segregation rule is the first failing check.
        camp_v = get_campaign_version(tid, camp_id)
        res = api.resolve_remediation_action(
            tid, action["id"], {"expected_campaign_version": camp_v}, compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_SOD_ASSESSOR_IS_RESOLVER, expected_status=409)

    def test_sod_closer_is_opener(self, api, auditor_headers):
        """PRD §3.9: "Closing the campaign moves it `DEFENSE_ASSEMBLY` → `CLOSED`. The defense packet must already be `DELIVERED` — closing with an undelivered packet fails as an invalid transition — and the segregation rule of §2.9 applies: the acting auditor's `X-User-ID` must differ from the campaign's `opened_by_user_id`, else `ERR_SOD_CLOSER_IS_OPENER` (HTTP 409)."
        PRD §2.9: "The auditor who closes an audit campaign must not be the auditor who opened it; the acting `X-User-ID` is compared to the campaign's `opened_by_user_id`."

        Design: Corner/errors/sod_closer_is_opener
        """
        bundle = setup_delivered_packet_campaign()  # opened by u_aud1; packet DELIVERED
        tid = bundle["tenant"]["id"]
        res = api.close_audit_campaign(tid, bundle["campaign"]["id"], auditor_headers)
        validate_error(res, ApiErrorId.ERR_SOD_CLOSER_IS_OPENER, expected_status=409)

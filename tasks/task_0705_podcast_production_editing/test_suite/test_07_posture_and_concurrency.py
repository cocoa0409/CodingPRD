"""Production-posture gating of publish, the state-vs-safety priority pair on
approve-edit, optimistic-concurrency on terminate/reconcile, and posture
reconciliation on invoice mutation. Covers difficulty rules
cross_entity_state_dependency (publish/posture), priority_pair_validation_conflict
(state vs safety), plus cross_cutting OCC + derived-field corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_show_owner_headers,
    make_producer_eng_headers,
    make_platform_admin_headers,
    make_ad_ops_headers,
    ApiErrorId,
    create_show_with_active_contract,
    create_engineer,
    drive_episode_to_scheduled,
    drive_episode_to_published,
    publish_one_episode,
    setup_episode_in_editing,
    setup_approved_campaign_with_slots,
    get_episode_invoice,
    create_ad_campaign_payload,
    create_ad_slot_payload,
    set_clock,
)

ADMIN = make_platform_admin_headers()
ADOPS = make_ad_ops_headers()


class TestPublishDependsOnPosture:
    def test_publish_blocked_on_suspended_show(self, api):
        """PRD §2.5: "Publishing an episode requires the owning show to be either ACTIVE
        or ON_HOLD ... and a publish attempt while the show is SUSPENDED is rejected with
        ERR_SHOW_SUSPENDED."
        PRD §2.5: "if any invoice belonging to this show is in DISPUTED status, the
        posture is SUSPENDED"

        Design: Difficulty/cross_entity_state_dependency/episode_publish_depends_on_show_posture
        """
        set_clock("2026-03-02T00:00:00Z")
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE", title="Posture S")
        engineer = create_engineer(name="Eng Po")
        eng = make_producer_eng_headers(engineer["id"])
        owner = make_show_owner_headers(show["id"])

        first = drive_episode_to_published(
            show, contract, engineer, record_start="2026-03-02T08:00:00Z",
            record_end="2026-03-02T09:00:00Z", title="First")
        second = drive_episode_to_scheduled(
            show, contract, engineer, record_start="2026-03-03T08:00:00Z",
            record_end="2026-03-03T09:00:00Z", title="Second")

        # Dispute the first invoice -> show SUSPENDED.
        inv1 = get_episode_invoice(first["id"])
        get_success_data(api_client.dispute_invoice(inv1["id"], owner))
        suspended = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert suspended["production_posture"] == "SUSPENDED", (
            f"DISPUTED invoice forces SUSPENDED, got {suspended['production_posture']}")

        resp = api_client.publish_episode(second["id"], eng)
        validate_error(resp, ApiErrorId.ERR_SHOW_SUSPENDED.value)

    def test_publish_allowed_on_active_show(self, api):
        """PRD §2.5: "Publishing an episode requires the owning show to be either ACTIVE
        or ON_HOLD — ON_HOLD deliberately lets in-flight work finish even though it blocks
        new intake"

        Design: Difficulty/cross_entity_state_dependency/episode_publish_depends_on_show_posture
        """
        show, contract, engineer, episode = publish_one_episode(tier="STANDARD")
        assert episode["status"] == "PUBLISHED", (
            "publish succeeds while show is ACTIVE")


class TestStateVsSafetyPriority:
    def test_approve_edit_wrong_state_returns_invalid_state(self, api):
        """PRD §3.4: "Approval has preconditions: the episode must be in REVIEW; the
        MASTER_AUDIO deliverable for the episode must be READY ... When these hold in this
        order — state legality first, then master readiness, then the loudness conformance
        check"
        PRD §2.8: "a transition endpoint first confirms the target resource is in a state
        from which the requested transition is legal — otherwise ERR_INVALID_STATE"

        approve-edit on an EDITING (not REVIEW) episode returns ERR_INVALID_STATE, the
        state precondition winning over the loudness safety check.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve_edit
        """
        show, contract, engineer, episode = setup_episode_in_editing(
            target_loudness_lufs=-16.0)
        owner = make_show_owner_headers(show["id"])
        resp = api_client.approve_edit(episode["id"], owner)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_approve_edit_in_editing_not_loudness_error(self, api):
        """PRD §2.8: "transition legality is checked before concurrency and before the
        domain-specific business gates."
        PRD §3.4: "When these hold in this order — state legality first, then master
        readiness, then the loudness conformance check"

        Confirms the state check pre-empts the loudness check: the EDITING-state episode
        does not surface ERR_LOUDNESS_OUT_OF_SPEC.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve_edit
        """
        show, contract, engineer, episode = setup_episode_in_editing(
            target_loudness_lufs=-16.0)
        owner = make_show_owner_headers(show["id"])
        resp = api_client.approve_edit(episode["id"], owner)
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_INVALID_STATE", (
            f"state check wins over safety, got {body['data']['error_id']}")


class TestOptimisticConcurrency:
    def test_terminate_with_stale_version_rejected(self, api):
        """PRD §2.11: "Terminating an engagement contract requires the request body to
        carry expected_engagementcontract_version, holding the client's last-observed
        version of the target contract. If that value does not equal the contract's
        current version — because, for instance, an activation or a posture-driven
        recompute has advanced the contract since the client last read it — the
        termination is rejected with ERR_STALE_VERSION at HTTP 412"

        Design: Corner/cross_cutting/occ_stale_version_contract_terminate
        """
        show = get_success_data(api_client.create_show(
            {"title": "Occ S", "format": "SOLO", "billing_model": "PER_EPISODE"}, ADMIN))
        draft = get_success_data(api_client.create_contract(
            {"show_id": show["id"], "tier": "STANDARD", "engagement_type": "PER_EPISODE"},
            ADMIN))
        draft_v = draft["version"]
        get_success_data(api_client.activate_contract(draft["id"], ADMIN))  # bumps version

        resp = api_client.terminate_contract(
            draft["id"], {"expected_engagementcontract_version": draft_v}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_reconcile_with_stale_version_rejected(self, api):
        """PRD §2.11: "Reconciling an ad campaign requires the request body to carry
        expected_adcampaign_version, holding the client's last-observed version of the
        target campaign. If that value does not equal the campaign's current version —
        because, for instance, a slot was added or the campaign was approved since the
        client last read it — the reconciliation is rejected with ERR_STALE_VERSION at
        HTTP 412"

        Design: Corner/cross_cutting/occ_stale_version_campaign_reconcile_after_slot_add
        """
        set_clock("2026-03-02T00:00:00Z")
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng OcC")
        episode = drive_episode_to_published(
            show, contract, engineer, record_start="2026-03-02T08:00:00Z",
            record_end="2026-03-02T09:00:00Z")

        campaign = get_success_data(api_client.create_ad_campaign(
            create_ad_campaign_payload(show["id"], sponsor_name="Stale Co",
                                       platform_fee_pct=0.30), ADOPS))
        camp_v0 = campaign["version"]  # stale: slot-add + approve will bump it
        get_success_data(api_client.create_ad_slot(
            create_ad_slot_payload(campaign["id"], episode["id"], 1000), ADOPS))
        get_success_data(api_client.approve_ad_campaign(campaign["id"], ADOPS))

        resp = api_client.reconcile_ad_campaign(
            campaign["id"], {"expected_adcampaign_version": camp_v0}, ADOPS)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


class TestPostureReconciliation:
    def test_posture_cycles_active_onhold_active_on_invoice_mutation(self, api):
        """PRD §3.9: "marking an invoice overdue typically drops a show to ON_HOLD;
        disputing one drops it to SUSPENDED; paying or resolving the last problem invoice
        can lift it back to ACTIVE."
        PRD §2.5: "if any invoice belonging to this show is in OVERDUE status, the posture
        is ON_HOLD; otherwise, the posture is ACTIVE."

        Design: Corner/cross_cutting/derived_field_posture_reconciled_on_invoice_mutation
        """
        show, contract, engineer, episode = publish_one_episode(tier="STANDARD")
        owner = make_show_owner_headers(show["id"])
        invoice = get_episode_invoice(episode["id"])

        p0 = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert p0["production_posture"] == "ACTIVE", (
            f"ISSUED invoice, active contract -> ACTIVE, got {p0['production_posture']}")

        get_success_data(api_client.mark_invoice_overdue(invoice["id"], ADMIN))
        p1 = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert p1["production_posture"] == "ON_HOLD", (
            f"OVERDUE invoice -> ON_HOLD, got {p1['production_posture']}")

        get_success_data(api_client.pay_invoice(invoice["id"], owner))
        p2 = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert p2["production_posture"] == "ACTIVE", (
            f"PAID invoice -> back to ACTIVE, got {p2['production_posture']}")

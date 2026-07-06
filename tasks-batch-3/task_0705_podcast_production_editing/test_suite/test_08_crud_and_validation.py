"""Breadth corner coverage: Show CRUD + validation, listing/pagination, enum
checks, asset supersession, invalid transitions, conditional/business validations,
the error catalogue, RBAC isolation, and the lock-assets endpoint.
All instances here are queue-B (corner) translations.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    NON_EXISTENT_UUID,
    make_show_owner_headers,
    make_producer_eng_headers,
    make_platform_admin_headers,
    make_ad_ops_headers,
    build_user_headers,
    ApiErrorId,
    create_show,
    create_show_with_active_contract,
    create_contract,
    create_engineer,
    create_episode,
    create_show_payload,
    create_contract_payload,
    create_retainer_cycle_payload,
    create_deliverable_payload,
    create_asset_version_payload,
    create_ad_campaign_payload,
    record_session_to_completion,
    lock_assets,
    setup_episode_in_review,
    set_clock,
)

ADMIN = make_platform_admin_headers()
ADOPS = make_ad_ops_headers()


class TestShowCrud:
    def test_create_show_returns_computed_defaults(self, api):
        """PRD §3.1: "At creation the show's lifetime_billed_cents is zero, its
        open_episode_count is zero, and its production_posture is SUSPENDED."
        PRD §2.4: "The id is a server-minted UUID with no type prefix ... The version
        field is an integer that begins at its initial value"

        Design: Corner/entities/create_show_returns_201_with_computed_defaults
        """
        show = validate_success(api_client.create_show(
            {"title": "Brand New", "format": "INTERVIEW", "billing_model": "PER_EPISODE"},
            ADMIN), expected_status=201)
        assert show["production_posture"] == "SUSPENDED"
        assert show["lifetime_billed_cents"] == 0
        assert show["open_episode_count"] == 0
        assert is_valid_uuid(show["id"])
        assert show["version"] == 1

    def test_create_show_missing_billing_model_rejected(self, api):
        """PRD §3.1: "a billing_model of either PER_EPISODE or RETAINER"
        PRD §2.8: "then request well-formedness — body parses, required fields present,
        types valid (ERR_INVALID_REQUEST)"

        Design: Corner/entities/create_show_missing_billing_model_returns_invalid_request
        """
        resp = api_client.create_show({"title": "No Billing", "format": "SOLO"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_show_default_target_loudness(self, api):
        """PRD §2.10: "Each Show declares a target_loudness_lufs between -23.0 and -12.0
        inclusive, defaulting to -16.0 if not supplied at creation."

        Design: Corner/entities/create_show_default_target_loudness_applied
        """
        show = validate_success(api_client.create_show(
            {"title": "Default Loud", "format": "SOLO", "billing_model": "PER_EPISODE"},
            ADMIN), expected_status=201)
        assert show["target_loudness_lufs"] == -16.0

    def test_create_show_invalid_format_enum(self, api):
        """PRD §2.8: "then enum membership, where any enum-typed field whose value is not
        a declared member is rejected with ERR_INVALID_ENUM"
        PRD §3.1: "a format drawn from INTERVIEW, SOLO, PANEL, or NARRATIVE"

        Design: Corner/entities/create_show_invalid_format_enum_returns_invalid_enum
        """
        resp = api_client.create_show(
            {"title": "Bad Fmt", "format": "VLOG", "billing_model": "PER_EPISODE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)

    def test_get_show_nonexistent_returns_not_found(self, api):
        """PRD §2.7: "the first identifier that does not resolve to an existing resource
        causes the request to be rejected with ERR_NOT_FOUND before any business rule is
        evaluated."

        Design: Corner/entities/get_show_nonexistent_id_returns_not_found
        """
        resp = api_client.get_show(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_show_returns_stored_entity(self, api):
        """PRD §2.2: "The data field contains the resource object ... operations that
        create or modify a resource will return the created or updated resource object in
        the data field."

        Design: Corner/entities/get_show_returns_stored_entity
        """
        created = get_success_data(api_client.create_show(
            {"title": "Readable", "format": "PANEL", "billing_model": "PER_EPISODE"},
            ADMIN))
        owner = make_show_owner_headers(created["id"])
        fetched = validate_success(api_client.get_show(created["id"], owner))
        assert fetched["title"] == "Readable"
        assert fetched["id"] == created["id"]


class TestListingPagination:
    def test_list_shows_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in the meta
        object of the response envelope: limit, offset, total_count, and has_more."

        Design: Corner/entities/list_shows_pagination_envelope_fields
        """
        get_success_data(api_client.create_show(
            {"title": "S1", "format": "SOLO", "billing_model": "PER_EPISODE"}, ADMIN))
        get_success_data(api_client.create_show(
            {"title": "S2", "format": "SOLO", "billing_model": "RETAINER"}, ADMIN))
        data, meta = validate_paginated(api_client.list_shows(ADMIN, params={"limit": 1, "offset": 0}))
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1

    def test_list_shows_invalid_pagination_limit(self, api):
        """PRD §2.3: "A limit outside the inclusive range of 1 to 100, or an offset below
        0, is rejected with ERR_INVALID_PAGINATION."

        Design: Corner/entities/list_shows_invalid_pagination_limit_returns_error
        """
        resp = api_client.list_shows(ADMIN, params={"limit": 101})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)


class TestAssetSupersession:
    def test_supersede_submitted_version_rejected(self, api):
        """PRD §3.4: "when supersession is claimed, the referenced version must be an
        ACCEPTED version of the same deliverable, failing otherwise with
        ERR_INVALID_SUPERSEDE."

        Design: Corner/entities/asset_version_supersede_invalid_target_returns_invalid_supersede
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng Sup")
        eng = make_producer_eng_headers(engineer["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)
        record_session_to_completion(episode["id"], engineer["id"],
                                     "2026-03-02T08:00:00Z", "2026-03-02T09:00:00Z")
        deliverable = get_success_data(api_client.create_deliverable(
            create_deliverable_payload(episode["id"], "MASTER_AUDIO"), eng))
        v1 = get_success_data(api_client.create_asset_version(
            create_asset_version_payload(deliverable["id"], integrated_loudness_lufs=-16.0),
            eng))  # SUBMITTED, not ACCEPTED

        resp = api_client.create_asset_version(
            create_asset_version_payload(deliverable["id"], supersedes_version_id=v1["id"],
                                         integrated_loudness_lufs=-16.0), eng)
        validate_error(resp, ApiErrorId.ERR_INVALID_SUPERSEDE.value)


class TestInvalidTransitions:
    def test_cancel_completed_session_invalid_state(self, api):
        """PRD §3.3: "a booked session may be cancelled (BOOKED → CANCELLED) when it is
        currently BOOKED. Any session transition attempted from the wrong state is
        rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/cancel_session_from_completed_returns_invalid_state
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng SC")
        eng = make_producer_eng_headers(engineer["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)
        completed = record_session_to_completion(
            episode["id"], engineer["id"],
            "2026-03-02T08:00:00Z", "2026-03-02T09:00:00Z",
            complete_at="2026-03-02T10:00:00Z")
        resp = api_client.cancel_session(completed["id"], eng)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_activate_active_contract_invalid_state(self, api):
        """PRD §3.1: "A platform operator activates it, moving DRAFT → ACTIVE, only when
        it is currently DRAFT ... A transition attempted from a state other than the one
        each requires is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/activate_contract_twice_returns_invalid_state
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        resp = api_client.activate_contract(contract["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_terminate_terminated_contract_invalid_state(self, api):
        """PRD §3.1: "EXPIRED and TERMINATED are terminal."
        PRD §3.1: "A transition attempted from a state other than the one each requires is
        rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/terminate_terminated_contract_locked_down
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        terminated = get_success_data(api_client.terminate_contract(
            contract["id"], {"expected_engagementcontract_version": contract["version"]},
            ADMIN))
        resp = api_client.terminate_contract(
            contract["id"],
            {"expected_engagementcontract_version": terminated["version"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestBusinessValidations:
    def test_create_episode_with_draft_contract_rejected(self, api):
        """PRD §3.2: "the named contract must itself be ACTIVE and must belong to the same
        show, failing otherwise with ERR_CONTRACT_NOT_ACTIVE."

        Design: Corner/validations/create_episode_with_draft_contract_returns_contract_not_active
        """
        show, active = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")  # posture ACTIVE
        owner = make_show_owner_headers(show["id"])
        draft = create_contract(show["id"], tier="PRIORITY", engagement_type="PER_EPISODE")
        resp = api_client.create_episode(
            {"show_id": show["id"], "contract_id": draft["id"], "title": "Ep CNA",
             "planned_track_count": 1}, owner)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)

    def test_schedule_with_transcript_not_ready_rejected(self, api):
        """PRD §3.5: "if the episode was commissioned with transcript_requested set to
        true, scheduling additionally requires the TRANSCRIPT deliverable to be READY,
        failing otherwise with ERR_TRANSCRIPT_NOT_READY."

        Design: Corner/validations/schedule_with_transcript_requested_but_transcript_not_ready
        """
        show, contract, engineer, episode = setup_episode_in_review(
            with_master_audio=True, transcript_requested=True, target_loudness_lufs=-16.0)
        owner = make_show_owner_headers(show["id"])
        eng = make_producer_eng_headers(engineer["id"])
        get_success_data(api_client.approve_edit(episode["id"], owner))  # -> MASTERED
        resp = api_client.schedule_episode(episode["id"], eng)
        validate_error(resp, ApiErrorId.ERR_TRANSCRIPT_NOT_READY.value)


class TestErrorCatalogue:
    def test_loudness_out_of_spec_on_accept_master(self, api):
        """PRD §3.4: "for a MASTER_AUDIO version, acceptance enforces loudness conformance
        (§2.10) — the version's integrated_loudness_lufs must lie within the loudness
        tolerance of the show's target_loudness_lufs, failing with ERR_LOUDNESS_OUT_OF_SPEC."

        Design: Corner/errors/error_loudness_out_of_spec_on_accept_master_audio
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE", target_loudness_lufs=-16.0)
        engineer = create_engineer(name="Eng Ld")
        eng = make_producer_eng_headers(engineer["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)
        record_session_to_completion(episode["id"], engineer["id"],
                                     "2026-03-02T08:00:00Z", "2026-03-02T09:00:00Z")
        deliverable = get_success_data(api_client.create_deliverable(
            create_deliverable_payload(episode["id"], "MASTER_AUDIO"), eng))
        version = get_success_data(api_client.create_asset_version(
            create_asset_version_payload(deliverable["id"], integrated_loudness_lufs=-10.0),
            eng))
        resp = api_client.accept_asset_version(version["id"], eng)
        validate_error(resp, ApiErrorId.ERR_LOUDNESS_OUT_OF_SPEC.value)

    def test_not_retainer_on_cycle_close(self, api):
        """PRD §3.8: "Closing a cycle is a platform-operator action permitted when the
        cycle is currently OPEN and the owning contract's engagement_type is RETAINER
        (closing a cycle whose contract is not a retainer is rejected with
        ERR_NOT_RETAINER)"

        Design: Corner/errors/error_not_retainer_on_cycle_close
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        cycle = get_success_data(api_client.create_retainer_cycle(
            create_retainer_cycle_payload(contract["id"],
                                          "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"),
            ADMIN))
        resp = api_client.close_retainer_cycle(cycle["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_RETAINER.value)

    def test_assets_not_locked_on_submit_edit(self, api):
        """PRD §3.4: "From EDITING, a ProducerEng submits the edit (EDITING → REVIEW) — but
        only after the episode's assets have been locked, i.e. assets_complete_at is set;
        submitting before assets are locked is rejected with ERR_ASSETS_NOT_LOCKED."

        Design: Corner/errors/error_assets_not_locked_on_submit_edit
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng Lk2")
        eng = make_producer_eng_headers(engineer["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)
        record_session_to_completion(episode["id"], engineer["id"],
                                     "2026-03-02T08:00:00Z", "2026-03-02T09:00:00Z")
        resp = api_client.submit_edit(episode["id"], eng)  # assets not locked
        validate_error(resp, ApiErrorId.ERR_ASSETS_NOT_LOCKED.value)

    def test_master_not_ready_on_approve_edit(self, api):
        """PRD §3.4: "the MASTER_AUDIO deliverable for the episode must be READY, failing
        otherwise with ERR_MASTER_NOT_READY"

        Design: Corner/errors/error_master_not_ready_on_approve_edit
        """
        show, contract, engineer, episode = setup_episode_in_review(with_master_audio=False)
        owner = make_show_owner_headers(show["id"])
        resp = api_client.approve_edit(episode["id"], owner)  # in REVIEW, no READY master
        validate_error(resp, ApiErrorId.ERR_MASTER_NOT_READY.value)

    def test_unauthenticated_unknown_role(self, api):
        """PRD §2.1: "A request that omits either header, or that supplies an X-User-Role
        value that is not one of the recognized roles, is rejected with
        ERR_UNAUTHENTICATED."

        Design: Corner/errors/error_unauthenticated_unknown_role
        """
        ghost = build_user_headers("ghost-1", "Ghost")
        resp = api_client.list_shows(ghost)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_invalid_window_retainer_cycle(self, api):
        """PRD §2.8: "a retainer cycle's window must have its cycle_end_utc strictly after
        its cycle_start_utc; either violation is rejected with ERR_INVALID_WINDOW."

        Design: Corner/errors/error_invalid_window_retainer_cycle_end_not_after_start
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="RETAINER", billing_model="RETAINER",
            monthly_included_episodes=1)
        resp = api_client.create_retainer_cycle(
            create_retainer_cycle_payload(contract["id"],
                                          "2026-04-01T00:00:00Z", "2026-03-01T00:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


class TestRbac:
    def test_adops_cannot_create_contract(self, api):
        """PRD §2.1: "A request whose role is recognized but is not permitted to perform
        the requested operation (per the authorization column of the endpoint table in §4)
        is rejected with ERR_FORBIDDEN_ROLE."

        Design: Corner/rbac/rbac_adops_cannot_create_contract_forbidden
        """
        show = create_show(billing_model="PER_EPISODE")
        resp = api_client.create_contract(
            create_contract_payload(show["id"], tier="STANDARD",
                                    engagement_type="PER_EPISODE"), ADOPS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_producereng_cannot_create_ad_campaign(self, api):
        """PRD §2.1: "A request whose role is recognized but is not permitted to perform
        the requested operation (per the authorization column of the endpoint table in §4)
        is rejected with ERR_FORBIDDEN_ROLE."

        Design: Corner/rbac/rbac_producereng_cannot_create_ad_campaign_forbidden
        """
        show = create_show(billing_model="PER_EPISODE")
        eng = build_user_headers(NON_EXISTENT_UUID, "ProducerEng")
        resp = api_client.create_ad_campaign(
            create_ad_campaign_payload(show["id"], sponsor_name="X"), eng)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_showowner_not_owner_of_other_show_episode(self, api):
        """PRD §2.1: "A ShowOwner acting on an episode, a deliverable, an invoice, or a
        retainer cycle that does not chain back to their own show is rejected with
        ERR_NOT_RESOURCE_OWNER."

        Design: Corner/rbac/rbac_showowner_not_owner_of_other_show_episode
        """
        show_a = create_show(billing_model="PER_EPISODE", title="Owner A")
        show_b, contract_b = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE", title="Owner B")
        episode_b = create_episode(show_b["id"], contract_b["id"], planned_track_count=1)
        # ShowOwner whose X-User-ID is Show A acting on Show B's episode.
        owner_a = make_show_owner_headers(show_a["id"])
        resp = api_client.cancel_episode(episode_b["id"], owner_a)
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


class TestEndpoints:
    def test_lock_assets_freezes_track_count_and_stamps_complete(self, api):
        """PRD §3.4: "a ProducerEng locks the episode's raw assets, supplying the actual
        raw_track_count. Locking stamps assets_complete_at from the clock and records
        raw_track_count on the episode"

        Design: Corner/endpoints/lock_assets_freezes_raw_track_count_and_stamps_complete
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng Lk")
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)
        record_session_to_completion(episode["id"], engineer["id"],
                                     "2026-03-01T08:00:00Z", "2026-03-01T09:00:00Z")
        locked = lock_assets(episode["id"], engineer["id"], raw_track_count=4,
                             lock_at="2026-03-02T06:00:00Z")
        assert locked["raw_track_count"] == 4, (
            f"raw_track_count frozen from request, got {locked['raw_track_count']}")
        assert locked["assets_complete_at"] == "2026-03-02T06:00:00.000Z", (
            f"assets_complete_at == clock now, got {locked['assets_complete_at']}")

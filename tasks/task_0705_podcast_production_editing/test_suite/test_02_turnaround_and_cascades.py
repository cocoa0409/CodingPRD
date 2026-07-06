"""Turnaround deadline (provisional vs final), and the publish/session-complete
cascade chains. Covers difficulty rules dual_variant_calc (turnaround),
transitive_cascade.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_show_owner_headers,
    make_producer_eng_headers,
    make_platform_admin_headers,
    create_show_with_active_contract,
    create_engineer,
    create_episode,
    record_session_to_completion,
    lock_assets,
    add_accepted_master_audio,
    submit_and_approve_edit,
    drive_episode_to_scheduled,
    get_episode_invoice,
    set_clock,
)

ADMIN = make_platform_admin_headers()


class TestTurnaroundDualVariant:
    def test_provisional_then_final_turnaround_diverge(self, api):
        """PRD §3.6: "The provisional deadline is computed when the recording session
        completes and the episode bubbles into editing: it is the episode's
        recording_ended_at plus the SLA hours computed from the intake estimate
        planned_track_count. The final deadline is computed when the show owner approves
        the edit: it is the episode's assets_complete_at plus the SLA hours computed from
        the frozen actual raw_track_count."
        PRD §3.6: "the tier base is 72 hours for STANDARD, 48 hours for PRIORITY, and 24
        hours for RUSH; the surcharge is 6 hours for each track beyond a multitrack floor
        of 2 tracks, i.e. the track count reduced by 2 (never below zero) multiplied by 6
        hours."

        Design: Difficulty/dual_variant_calc/turnaround_provisional_vs_final_diverge_on_episode
        """
        show, contract = create_show_with_active_contract(
            tier="PRIORITY", engagement_type="PER_EPISODE", target_loudness_lufs=-16.0,
            fmt="INTERVIEW", title="Pod S")
        engineer = create_engineer(name="Eng A")
        eng = make_producer_eng_headers(engineer["id"])

        episode = create_episode(show["id"], contract["id"], planned_track_count=2,
                                 transcript_requested=False, title="Ep E")
        # Recording window before the completion clock; complete at 2026-03-02T00:00Z.
        record_session_to_completion(
            episode["id"], engineer["id"],
            "2026-03-01T08:00:00Z", "2026-03-01T10:00:00Z",
            complete_at="2026-03-02T00:00:00Z")

        # Provisional: recording_ended_at 2026-03-02 + PRIORITY 48h (planned=2) -> 03-04.
        prov = get_success_data(api_client.get_episode(episode["id"], eng))
        assert prov["turnaround_due_utc"] == "2026-03-04T00:00:00.000Z", (
            f"provisional PRIORITY 48h from 2026-03-02, got {prov['turnaround_due_utc']}")

        # Lock assets at 2026-03-02T06:00 with raw=5; accept master; approve.
        lock_assets(episode["id"], engineer["id"], raw_track_count=5,
                    lock_at="2026-03-02T06:00:00Z")
        add_accepted_master_audio(episode["id"], engineer["id"])
        approved = submit_and_approve_edit(episode["id"], show["id"], engineer["id"])

        # Final: assets_complete_at 2026-03-02T06:00 + 48 + (5-2)*6 = 66h -> 03-05T00:00.
        assert approved["turnaround_due_utc"] == "2026-03-05T00:00:00.000Z", (
            f"final raw=5 -> 66h from 2026-03-02T06:00, "
            f"got {approved['turnaround_due_utc']}")
        assert prov["turnaround_due_utc"] != approved["turnaround_due_utc"], (
            "provisional and final must diverge for this episode")

    def test_provisional_turnaround_standard_one_track(self, api):
        """PRD §3.6: "The provisional deadline is computed when the recording session
        completes and the episode bubbles into editing: it is the episode's
        recording_ended_at plus the SLA hours computed from the intake estimate
        planned_track_count."
        PRD §3.6: "the tier base is 72 hours for STANDARD, 48 hours for PRIORITY, and 24
        hours for RUSH"

        Design: Difficulty/dual_variant_calc/turnaround_provisional_vs_final_diverge_on_episode
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE", title="Bub S")
        engineer = create_engineer(name="Eng B")
        eng = make_producer_eng_headers(engineer["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1,
                                 title="Ep B")
        record_session_to_completion(
            episode["id"], engineer["id"],
            "2026-03-01T08:00:00Z", "2026-03-01T09:00:00Z",
            complete_at="2026-03-02T00:00:00Z")
        ep = get_success_data(api_client.get_episode(episode["id"], eng))
        assert ep["turnaround_due_utc"] == "2026-03-05T00:00:00.000Z", (
            f"STANDARD 72h from 2026-03-02 (planned=1), got {ep['turnaround_due_utc']}")


class TestSessionCompleteCascade:
    def test_session_complete_bubbles_episode_to_editing(self, api):
        """PRD §3.3: "The engineer completes a live session (LIVE → COMPLETED) when it is
        currently LIVE; completion stamps the session's completed_at from the clock, and
        bubbles the episode RECORDING → EDITING, stamping the episode's recording_ended_at
        from the session's completed_at and computing the provisional turnaround deadline."

        Design: Difficulty/transitive_cascade/session_complete_bubbles_episode_to_editing_depth2
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE", title="Bub S")
        engineer = create_engineer(name="Eng B")
        eng = make_producer_eng_headers(engineer["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1,
                                 title="Ep B")
        completed = record_session_to_completion(
            episode["id"], engineer["id"],
            "2026-03-01T08:00:00Z", "2026-03-01T09:00:00Z",
            complete_at="2026-03-02T00:00:00Z")

        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] == "2026-03-02T00:00:00.000Z", (
            f"completed_at from clock, got {completed['completed_at']}")

        ep = get_success_data(api_client.get_episode(episode["id"], eng))
        assert ep["status"] == "EDITING", (
            f"episode bubbled RECORDING->EDITING, got {ep['status']}")
        assert ep["recording_ended_at"] == "2026-03-02T00:00:00.000Z", (
            f"recording_ended_at == session.completed_at, got {ep['recording_ended_at']}")
        assert ep["turnaround_due_utc"] == "2026-03-05T00:00:00.000Z", (
            f"provisional STANDARD 72h, got {ep['turnaround_due_utc']}")

    def test_session_complete_sets_recording_ended_at(self, api):
        """PRD §3.3: "completion stamps the session's completed_at from the clock, and
        bubbles the episode RECORDING → EDITING, stamping the episode's recording_ended_at
        from the session's completed_at and computing the provisional turnaround deadline."

        Design: Difficulty/transitive_cascade/session_complete_bubbles_episode_to_editing_depth2
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng Bub2")
        eng = make_producer_eng_headers(engineer["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)
        record_session_to_completion(
            episode["id"], engineer["id"],
            "2026-03-01T08:00:00Z", "2026-03-01T09:00:00Z",
            complete_at="2026-03-02T00:00:00Z")
        ep = get_success_data(api_client.get_episode(episode["id"], eng))
        assert ep["status"] == "EDITING"
        assert ep["recording_ended_at"] == "2026-03-02T00:00:00.000Z"


class TestPublishCascade:
    def test_publish_issues_invoice_and_bumps_lifetime(self, api):
        """PRD §3.5: "For an episode billed under a per-episode contract, publishing also
        creates and issues an invoice."
        PRD §3.5: "the show's lifetime_billed_cents is increased by the invoice's
        total_cents, observing the snapshot ordering of §2.9."

        Design: Difficulty/transitive_cascade/publish_issues_invoice_then_bumps_show_lifetime_depth3
        """
        set_clock("2026-03-02T00:00:00Z")
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE", title="Casc S")
        engineer = create_engineer(name="Eng C")
        eng = make_producer_eng_headers(engineer["id"])
        scheduled = drive_episode_to_scheduled(
            show, contract, engineer, planned_track_count=1, raw_track_count=1,
            record_start="2026-03-02T08:00:00Z", record_end="2026-03-02T09:00:00Z",
            title="Ep C")

        published = validate_success(api_client.publish_episode(scheduled["id"], eng))
        assert published["status"] == "PUBLISHED"

        invoice = get_episode_invoice(scheduled["id"])
        assert invoice is not None, "publish must create exactly one invoice"
        assert invoice["status"] == "ISSUED"
        assert invoice["total_cents"] == 15000, (
            f"STANDARD base on time, got {invoice['total_cents']}")

        show_after = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert show_after["lifetime_billed_cents"] == 15000, (
            f"lifetime bumped by invoice total, got {show_after['lifetime_billed_cents']}")

    def test_publish_invoice_records_episode_and_kind(self, api):
        """PRD §3.5: "The invoice records show_id and episode_id (its retainer_cycle_id
        is null), with kind PER_EPISODE"

        Design: Difficulty/transitive_cascade/publish_issues_invoice_then_bumps_show_lifetime_depth3
        """
        show, contract, engineer, episode = None, None, None, None
        set_clock("2026-03-02T00:00:00Z")
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng C2")
        eng = make_producer_eng_headers(engineer["id"])
        scheduled = drive_episode_to_scheduled(
            show, contract, engineer, record_start="2026-03-02T08:00:00Z",
            record_end="2026-03-02T09:00:00Z")
        validate_success(api_client.publish_episode(scheduled["id"], eng))
        invoice = get_episode_invoice(scheduled["id"])
        assert invoice["kind"] == "PER_EPISODE"
        assert invoice["episode_id"] == scheduled["id"]
        assert invoice["retainer_cycle_id"] is None

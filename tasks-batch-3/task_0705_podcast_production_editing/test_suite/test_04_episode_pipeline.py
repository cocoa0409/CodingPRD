"""Episode pipeline state machine: revision loop, initial state, cancel cascade,
open-episode-count, plus the invoice dispute branching (PAID arm) and
immediate-consistency posture flip.
Covers difficulty rules non_linear_state_machine, and several corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_show_owner_headers,
    make_producer_eng_headers,
    make_platform_admin_headers,
    create_show,
    create_show_with_active_contract,
    create_contract,
    create_engineer,
    create_episode,
    book_session,
    setup_episode_in_review,
    publish_one_episode,
    get_episode_invoice,
    set_clock,
)

ADMIN = make_platform_admin_headers()


class TestRevisionLoop:
    def test_two_revision_rounds_loop_back_to_review(self, api):
        """PRD §3.4: "From REVIEW, the ShowOwner either requests a revision
        (REVIEW → EDITING), which increments the episode's revision_count by one and
        re-opens editing — this revision loop may repeat — or approves the edit
        (REVIEW → MASTERED)."

        Design: Difficulty/non_linear_state_machine/episode_review_editing_revision_cycle
        """
        show, contract, engineer, episode = setup_episode_in_review(with_master_audio=False)
        owner = make_show_owner_headers(show["id"])
        eng = make_producer_eng_headers(engineer["id"])

        # REVIEW -> EDITING (revision 1) -> REVIEW
        get_success_data(api_client.request_revision(episode["id"], owner))
        get_success_data(api_client.submit_edit(episode["id"], eng))
        # REVIEW -> EDITING (revision 2) -> REVIEW
        get_success_data(api_client.request_revision(episode["id"], owner))
        final = validate_success(api_client.submit_edit(episode["id"], eng))

        assert final["status"] == "REVIEW", (
            f"looped back into REVIEW, got {final['status']}")
        assert final["revision_count"] == 2, (
            f"one increment per REVIEW->EDITING hop, got {final['revision_count']}")

    def test_request_revision_increments_count_each_hop(self, api):
        """PRD §3.4: "a ProducerEng submits the edit (EDITING → REVIEW) ... From REVIEW,
        the ShowOwner either requests a revision (REVIEW → EDITING), which increments the
        episode's revision_count by one and re-opens editing"

        Design: Difficulty/non_linear_state_machine/episode_review_editing_revision_cycle
        """
        show, contract, engineer, episode = setup_episode_in_review(with_master_audio=False)
        owner = make_show_owner_headers(show["id"])
        eng = make_producer_eng_headers(engineer["id"])

        revised = validate_success(api_client.request_revision(episode["id"], owner))
        assert revised["status"] == "EDITING", (
            f"REVIEW->EDITING, got {revised['status']}")
        assert revised["revision_count"] == 1, (
            f"revision_count == 1 after first hop, got {revised['revision_count']}")


class TestInvoiceDisputeBranchPaid:
    def test_disputed_invoice_can_be_paid(self, api):
        """PRD §3.9: "a DISPUTED invoice may later go to PAID or VOID ... A ShowOwner pays
        an invoice that is ISSUED, OVERDUE, or DISPUTED, moving it to PAID."
        PRD §2.9: "it is decreased by an invoice's total_cents when that invoice is
        voided, reversing the original billing."

        Design: Difficulty/non_linear_state_machine/invoice_disputed_branching_pay_or_void
        """
        show, contract, engineer, episode = publish_one_episode(tier="STANDARD")
        owner = make_show_owner_headers(show["id"])
        invoice = get_episode_invoice(episode["id"])
        get_success_data(api_client.dispute_invoice(invoice["id"], owner))

        paid = validate_success(api_client.pay_invoice(invoice["id"], owner))
        assert paid["status"] == "PAID", (
            f"DISPUTED->PAID branch chosen, got {paid['status']}")
        # PAID branch does NOT reverse lifetime (only VOID does).
        after = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert after["lifetime_billed_cents"] == 15000, (
            f"PAID branch leaves lifetime intact, got {after['lifetime_billed_cents']}")


class TestEpisodeInitialAndCancel:
    def test_new_episode_starts_in_intake(self, api):
        """PRD §3.2: "A new episode enters the pipeline in INTAKE"
        PRD §3.2: "revision_count (how many times review sent the edit back)"

        Design: Corner/state_machines/episode_initial_state_is_intake
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        owner = make_show_owner_headers(show["id"])
        episode = validate_success(
            api_client.create_episode(
                {"show_id": show["id"], "contract_id": contract["id"],
                 "title": "Fresh", "planned_track_count": 1}, owner),
            expected_status=201)
        assert episode["status"] == "INTAKE"
        assert episode["revision_count"] == 0
        assert episode["turnaround_due_utc"] is None

    def test_cancel_episode_cascades_booked_session(self, api):
        """PRD §3.2: "Cancellation moves the episode to CANCELLED, cascades any of the
        episode's still-live sessions (those in BOOKED or LIVE) to CANCELLED, and
        recomputes the show's open_episode_count."

        Design: Corner/state_machines/cancel_episode_cascades_booked_session_to_cancelled
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        owner = make_show_owner_headers(show["id"])
        engineer = create_engineer(name="Eng Cd")
        eng = make_producer_eng_headers(engineer["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)
        session = book_session(episode["id"], engineer["id"],
                               "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z")

        cancelled = validate_success(api_client.cancel_episode(episode["id"], owner))
        assert cancelled["status"] == "CANCELLED"
        sess = get_success_data(api_client.get_session(session["id"], eng))
        assert sess["status"] == "CANCELLED", (
            f"booked session cascaded to CANCELLED, got {sess['status']}")

    def test_open_episode_count_tracks_open_episodes(self, api):
        """PRD §2.5: "The show also tracks open_episode_count, the number of its episodes
        whose status is none of PUBLISHED, ARCHIVED, or CANCELLED. This count is
        recomputed whenever an episode is created, cancelled, published, or archived."

        Design: Corner/entities/episode_open_count_computed_field_tracks_open_episodes
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        owner = make_show_owner_headers(show["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)

        before = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert before["open_episode_count"] == 1, (
            f"one INTAKE episode, got {before['open_episode_count']}")

        get_success_data(api_client.cancel_episode(episode["id"], owner))
        after = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert after["open_episode_count"] == 0, (
            f"cancelled episode no longer counted, got {after['open_episode_count']}")


class TestImmediateConsistency:
    def test_activation_flips_posture_on_next_get(self, api):
        """PRD §2.5: "A newly created show starts SUSPENDED, because no contract has yet
        been activated for it."
        PRD §3.1: "Activation stamps activated_at from the logical clock and, because a
        newly active contract can lift the show out of SUSPENDED, recomputes the owning
        show's posture."

        Design: Corner/consistency_model/immediate_consistency_posture_visible_in_same_response
        """
        show = create_show(billing_model="PER_EPISODE")
        contract = create_contract(show["id"], tier="STANDARD",
                                   engagement_type="PER_EPISODE")

        before = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert before["production_posture"] == "SUSPENDED", (
            f"no ACTIVE contract -> SUSPENDED, got {before['production_posture']}")

        get_success_data(api_client.activate_contract(contract["id"], ADMIN))
        after = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert after["production_posture"] == "ACTIVE", (
            f"posture ACTIVE immediately after activate, got {after['production_posture']}")

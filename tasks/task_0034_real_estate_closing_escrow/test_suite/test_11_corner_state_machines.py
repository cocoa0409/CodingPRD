"""Corner section: state_machines — initial state, terminal-state
lockdown, invalid transitions, and the side-effect-not-fired branch when
a confirm doesn't reach the funding threshold.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_actors,
    setup_active_agreement,
    create_deposit,
    confirm_deposit,
    create_purchase_agreement_payload,
    create_title_search,
    complete_title_search,
    resolve_title_search,
    create_title_search_payload,
    complete_title_search_payload,
    resolve_title_search_payload,
)


class TestPurchaseAgreementInitialState:
    def test_freshly_created_agreement_is_in_draft(self, api):
        """PRD §3.1: "The new agreement lands in ``DRAFT`` with ``version`` 1, ``status`` ``DRAFT``, ``earnest_money_received_cents`` of zero, and ``terminated_reason`` null."

        Design: Corner/state_machines/agreement_initial_state_is_draft
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        res = api.create_purchase_agreement(
            create_purchase_agreement_payload(property_address="1 IS St"),
            actors["eo"],
        )
        agr = validate_success(res, expected_status=201)
        assert agr["status"] == "DRAFT", \
            f"newly-created agreement must be in DRAFT, got {agr['status']}"


class TestCloseFromDraftRejected:
    def test_close_on_draft_returns_409_invalid_state(self, api):
        """PRD §2.10: "When a single request would fail multiple validations, the system evaluates them in a fixed priority order and surfaces the highest-ranking failure."
        PRD §2.10: "State preconditions are next: the from-state check against the relevant state machine (raising ``ERR_INVALID_STATE``), then the optimistic-concurrency checks of §2.7 (raising ``ERR_STALE_AGREEMENT_VERSION`` or ``ERR_STALE_TITLE_SEARCH_VERSION``), then the three-day disclosure wait (raising ``ERR_CD_THREE_DAY_NOT_ELAPSED``), then the wire segregation-of-duties check (raising ``ERR_WIRE_SOD_VIOLATION``)."

        Design: Corner/state_machines/agreement_close_from_draft_rejected_invalid_state
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        res = api.create_purchase_agreement(
            create_purchase_agreement_payload(property_address="1 IT St"),
            actors["eo"],
        )
        agr = validate_success(res, expected_status=201)
        # Close on DRAFT — only CLEARED_TO_CLOSE → CLOSED is valid per PRD §3.5.
        close_res = api.close_purchase_agreement(agr["id"], actors["eo"])
        validate_error(close_res, "ERR_INVALID_STATE", expected_status=409)


class TestTitleSearchResolvedIsTerminal:
    def test_resolve_a_second_time_on_resolved_search_rejected(self, api):
        """PRD §3.2: "Resolution moves the search from ``COMPLETED`` to ``RESOLVED``, and ``RESOLVED`` is terminal — a subsequent retitle requires a new search row."

        Design: Corner/state_machines/title_search_resolved_is_terminal_re_resolve_rejected
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(actors=actors)
        search = create_title_search(actors, base["agreement"]["id"])
        complete_title_search(actors, search["id"], defects=[])
        resolve_title_search(actors, search["id"])
        # Second attempt to resolve a RESOLVED (terminal) search.
        res = api.resolve_title_search(
            search["id"], resolve_title_search_payload(), actors["ta"]
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestEmdConfirmDoesNotPromoteWhenBelowThreshold:
    def test_confirm_below_threshold_leaves_agreement_active_and_escrow_open(self, api):
        """PRD §3.1: "Confirmation is the trigger for the agreement's funding event. The system recomputes ``earnest_money_received_cents`` as the sum of ``amount_cents`` across every ``CONFIRMED`` deposit on the agreement; if that sum reaches or exceeds ``earnest_money_required_cents`` while the agreement is in ``ACTIVE``, the agreement transitions to ``UNDER_CONTRACT``, the escrow account transitions from ``OPEN`` to ``FUNDED``, and both rows have their ``version`` bumped by one (see §2.9 for the full cascade)."

        Design: Corner/state_machines/emd_confirm_does_not_promote_when_threshold_not_met
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(
            actors=actors, earnest_money_required_cents=1_000_000
        )
        agreement = base["agreement"]
        escrow = base["escrow"]
        # 600000 < 1000000 required, so the cascade should NOT fire.
        deposit = create_deposit(actors, escrow["id"], amount_cents=600_000)
        confirm_deposit(actors, deposit["id"], confirmation_reference="PARTIAL")

        agr_after = validate_success(
            api.get_purchase_agreement(agreement["id"], actors["eo"]),
            expected_status=200,
        )
        esc_after = validate_success(
            api.get_escrow_account(escrow["id"], actors["eo"]),
            expected_status=200,
        )
        assert agr_after["status"] == "ACTIVE", \
            f"agreement must stay ACTIVE when sum < required, got {agr_after['status']}"
        assert esc_after["status"] == "OPEN", \
            f"escrow must stay OPEN when sum < required, got {esc_after['status']}"

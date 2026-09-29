"""Parallel subscription dimensions, the bounded roaming revision loop, and the
two four-hop cascades the PRD names explicitly.

Every test builds its own world from an empty database through PRD-declared
endpoints, then drives exactly one trigger and reads the observable outcome back.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    authorize_payload,
    create_roaming_authorization_payload,
    deliver_terminal,
    disclosure_acknowledgement_payload,
    enforcement_action_payload,
    get_beam,
    get_cell,
    get_subscriber,
    get_subscription,
    get_terminal,
    install_terminal,
    is_iso8601_timestamp,
    make_subscriber_headers,
    request_roaming,
    scan_terminal,
    setup_active_subscription,
    setup_approved_roaming_window,
    setup_pending_activation_subscription,
    setup_reserved_order,
    setup_rma_in_flight,
    suspend_payload,
    usage_record_payload,
    validate_error,
    validate_success,
    warranty_replacement_payload,
)

# The four state dimensions a subscription carries on one row.
DIMENSIONS = (
    "service_state",
    "authorization_state",
    "priority_state",
    "disclosure_ack_state",
)


def _dimensions(subscription: dict) -> dict:
    """The four-dimension tuple as a dict, for readable assertion messages."""
    return {name: subscription[name] for name in DIMENSIONS}


# ═══════════════════════════════════════════════════════════════════════════
# Subscription: four parallel dimensions that advance independently
# ═══════════════════════════════════════════════════════════════════════════


class TestSubscriptionParallelDimensions:
    """One row, four dimensions, one trigger moving only its own dimension(s)."""

    def test_activation_lands_all_four_dimensions_and_ack_moves_only_disclosure(
        self, api
    ):
        """A fresh subscription lands on all four dimensions at once, and
        acknowledging the disclosure moves the disclosure dimension alone.

        PRD §3.5: "On success a subscription record is created and lands in four independent state dimensions at once: `service_state` `PENDING_ACTIVATION`, `authorization_state` `UNAUTHORIZED`, `priority_state` `PRIORITY` and `disclosure_ack_state` `PENDING_ACK`."
        PRD §3.5: "These four dimensions live on the same row and evolve independently — a subscription can be `ACTIVE` and `DEAUTHORIZED` and `DEPRIORITIZED` simultaneously, and none of the three facts implies the others."
        PRD §3.5: "On success the disclosure dimension moves `PENDING_ACK → ACKNOWLEDGED` and nothing else changes."

        Design: Difficulty/non_linear_state_machine/subscription_four_parallel_dimensions_advance_independently
        """
        env = setup_pending_activation_subscription()
        subscription = env["subscription"]

        assert _dimensions(subscription) == {
            "service_state": "PENDING_ACTIVATION",
            "authorization_state": "UNAUTHORIZED",
            "priority_state": "PRIORITY",
            "disclosure_ack_state": "PENDING_ACK",
        }, f"activation must land on all four dimensions at once, got {_dimensions(subscription)}"

        response = api.acknowledge_disclosure(
            subscription["id"],
            disclosure_acknowledgement_payload(env["license"]["consumer_disclosure_version"]),
            make_subscriber_headers(env["subscriber"]["id"]),
        )
        acknowledged = validate_success(response, 200)

        assert _dimensions(acknowledged) == {
            "service_state": "PENDING_ACTIVATION",
            "authorization_state": "UNAUTHORIZED",
            "priority_state": "PRIORITY",
            "disclosure_ack_state": "ACKNOWLEDGED",
        }, (
            "acknowledgement must move the disclosure dimension and nothing else, got "
            f"{_dimensions(acknowledged)}"
        )

    def test_fixed_authorization_moves_service_and_authorization_dimensions_only(
        self, api, agent_headers
    ):
        """A FIXED authorisation advances two dimensions and leaves the fair-use
        and disclosure dimensions exactly where they were.

        PRD §3.5: "A `FIXED` authorisation moves the authorisation dimension `UNAUTHORIZED → AUTHORIZED_FIXED` and simultaneously advances the provisioning dimension `PENDING_ACTIVATION → ACTIVE`, because first authorisation is what makes a provisioned account a live one."
        PRD §3.5: "These four dimensions live on the same row and evolve independently — a subscription can be `ACTIVE` and `DEAUTHORIZED` and `DEPRIORITIZED` simultaneously, and none of the three facts implies the others."

        Design: Difficulty/non_linear_state_machine/subscription_four_parallel_dimensions_advance_independently
        """
        env = setup_pending_activation_subscription()
        subscription_id = env["subscription"]["id"]
        api.acknowledge_disclosure(
            subscription_id,
            disclosure_acknowledgement_payload(env["license"]["consumer_disclosure_version"]),
            make_subscriber_headers(env["subscriber"]["id"]),
        )

        response = api.authorize_subscription(
            subscription_id, authorize_payload("FIXED"), agent_headers
        )
        authorized = validate_success(response, 200)

        assert _dimensions(authorized) == {
            "service_state": "ACTIVE",
            "authorization_state": "AUTHORIZED_FIXED",
            "priority_state": "PRIORITY",
            "disclosure_ack_state": "ACKNOWLEDGED",
        }, (
            "a FIXED authorisation moves only the authorisation and provisioning "
            f"dimensions, got {_dimensions(authorized)}"
        )

    def test_fair_use_crossing_moves_only_the_priority_dimension(self, api, netops_headers):
        """Crossing the effective fair-use threshold flips priority_state and
        leaves the other three dimensions untouched.

        PRD §3.6: "It is the plan's `priority_data_gb` plus the governing beam's `deprioritization_grace_gb` — the beam-level generosity described in §3.2."
        PRD §3.6: "If the subscription's `priority_state` is `PRIORITY` and its `cycle_priority_gb_used` is greater than or equal to the effective threshold, the fair-use dimension flips `PRIORITY → DEPRIORITIZED`."
        PRD §3.6: "On the flip, `deprioritized_at` is stamped with the logical clock's current instant and `effective_rate_mbps` is replaced by the plan's `deprioritized_rate_mbps` — this is the field a subscriber-facing portal reads to explain the slowdown, and it holds the plan's `committed_rate_mbps` whenever `priority_state` is `PRIORITY` and the plan's `deprioritized_rate_mbps` whenever it is `DEPRIORITIZED`."
        PRD §3.6: "A reading whose `counted` is true adds its `gb_used` to `cycle_priority_gb_used` and the sum is rounded half up to 3 decimal places."

        Design: Difficulty/non_linear_state_machine/subscription_four_parallel_dimensions_advance_independently
        """
        # Plan allowance 100 GB, beam grace 0 GB, so the effective threshold is 100 GB.
        env = setup_active_subscription()
        subscription_id = env["subscription"]["id"]

        response = api.create_usage_record(
            subscription_id, usage_record_payload(120.0, 0), netops_headers
        )
        validate_success(response, 201)

        subscription = get_subscription(subscription_id)
        assert _dimensions(subscription) == {
            "service_state": "ACTIVE",
            "authorization_state": "AUTHORIZED_FIXED",
            "priority_state": "DEPRIORITIZED",
            "disclosure_ack_state": "ACKNOWLEDGED",
        }, (
            "a fair-use crossing moves only the fair-use dimension, got "
            f"{_dimensions(subscription)}"
        )
        assert subscription["cycle_priority_gb_used"] == pytest.approx(120.0, abs=0.001), (
            "a counted reading of 120 GB must land on cycle_priority_gb_used, got "
            f"{subscription['cycle_priority_gb_used']}"
        )
        assert subscription["effective_rate_mbps"] == pytest.approx(20.0, abs=0.001), (
            "a DEPRIORITIZED subscription reports the plan's deprioritized_rate_mbps of 20, got "
            f"{subscription['effective_rate_mbps']}"
        )
        assert is_iso8601_timestamp(subscription["deprioritized_at"] or ""), (
            f"deprioritized_at must be stamped on the flip, got {subscription.get('deprioritized_at')!r}"
        )

    def test_suspension_moves_only_service_state_and_keeps_the_cell_slot(
        self, api, agent_headers, netops_headers
    ):
        """Suspending a throttled, authorised subscription moves the provisioning
        dimension alone: the authorisation and fair-use dimensions survive, the
        beam megabits are released and the cell slot is retained.

        PRD §3.9: "A `ProvisioningAgent` supplies a `suspend_reason`, and a subscription whose `service_state` is `PENDING_ACTIVATION` or `ACTIVE` moves to `SUSPENDED` with that text recorded in `suspension_reason`; any other `service_state` is refused with `ERR_SUBSCRIPTION_STATE_INVALID`."
        PRD §3.9: "What does **not** move is the cell's `committed_terminal_count` — a suspended subscription keeps its slot, so suspending a customer frees megabits but does not free a seat, and no waitlist promotion runs."
        PRD §3.9: "Finally, the owning subscriber's `account_state` moves to `SUSPENDED` when every one of that subscriber's non-terminal subscriptions is `SUSPENDED`."
        PRD §3.6: "A subsequent reading of zero, or any other reading at all, never restores `PRIORITY`; only the fair-use reset inside a cycle close does."
        PRD §2.8: "`SUSPENDED` and `TERMINATED` subscriptions contribute nothing — which is the asymmetry worth internalising: **a suspended subscription keeps its cell slot but releases its beam megabits.**"

        Design: Difficulty/non_linear_state_machine/subscription_four_parallel_dimensions_advance_independently
        """
        env = setup_active_subscription()
        subscription_id = env["subscription"]["id"]
        api.create_usage_record(
            subscription_id, usage_record_payload(120.0, 0), netops_headers
        )

        response = api.suspend_subscription(
            subscription_id, suspend_payload(suspend_reason="customer request"), agent_headers
        )
        suspended = validate_success(response, 200)

        assert _dimensions(suspended) == {
            "service_state": "SUSPENDED",
            "authorization_state": "AUTHORIZED_FIXED",
            "priority_state": "DEPRIORITIZED",
            "disclosure_ack_state": "ACKNOWLEDGED",
        }, (
            "suspension moves only the provisioning dimension, got "
            f"{_dimensions(suspended)}"
        )
        assert suspended["suspension_reason"] == "customer request", (
            f"suspend_reason must be recorded, got {suspended.get('suspension_reason')!r}"
        )

        beam = get_beam(env["beam"]["id"])
        assert beam["weighted_sold_mbps"] == pytest.approx(0.0, abs=0.001), (
            "a suspended subscription releases its beam megabits, got "
            f"{beam['weighted_sold_mbps']}"
        )
        assert beam["oversubscription_ratio"] == pytest.approx(0.0, abs=0.001), (
            f"an empty sold set gives a ratio of 0, got {beam['oversubscription_ratio']}"
        )
        assert beam["capacity_state"] == "NORMAL", (
            f"a beam selling nothing bands as NORMAL, got {beam['capacity_state']}"
        )

        cell = get_cell(env["cell"]["id"])
        assert cell["committed_terminal_count"] == 1, (
            "a suspended subscription keeps its cell slot, got "
            f"{cell['committed_terminal_count']}"
        )

        subscriber = get_subscriber(env["subscriber"]["id"])
        assert subscriber["account_state"] == "SUSPENDED", (
            "the account follows when every non-terminal subscription is SUSPENDED, got "
            f"{subscriber['account_state']}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Roaming authorisation: the bounded REQUESTED -> NEEDS_INFO -> REQUESTED loop
# ═══════════════════════════════════════════════════════════════════════════


class TestRoamingRevisionLoopBoundedAtThreeRounds:
    """The review conversation cycles, counts its rounds, and stops at three."""

    @staticmethod
    def _roaming_request(subscription_id: str, subscriber_id: str) -> dict:
        return request_roaming(
            subscription_id,
            subscriber_id=subscriber_id,
            mode="ROAM_TEMPORARY",
            target_jurisdiction_code="US-CA",
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2026-09-10T00:00:00Z",
        )

    def test_three_revision_rounds_cycle_the_state_and_accrue_the_round_count(
        self, api, compliance_headers
    ):
        """Each information round moves REQUESTED -> NEEDS_INFO and increments the
        counter; each resubmission moves NEEDS_INFO -> REQUESTED and replaces the
        stored window, leaving the counter where the round left it.

        PRD §3.7: "A newly raised request is born in `auth_state` `REQUESTED` with `info_round_count` at 0, and with `governing_license_id`, `decision_note` and `revoked_reason` all empty."
        PRD §3.7: "A `ComplianceOfficer` who needs more evidence sends the request back with an `info_request_note`, moving it `REQUESTED → NEEDS_INFO`, increasing `info_round_count` by 1, and storing the note in `decision_note`."
        PRD §3.7: "The requester (the owning `Subscriber` or a `ProvisioningAgent`) closes the round by resubmitting a corrected window, supplying a fresh `effective_from` and `effective_until` that replace the stored pair; the resubmission moves the record `NEEDS_INFO → REQUESTED`, requires `effective_until` strictly later than `effective_from`, and re-runs exactly the same overlap and cooldown checks the original request faced, with the same `ERR_ROAMING_WINDOW_CONFLICT` on failure."
        PRD §3.7: "The cycle `REQUESTED → NEEDS_INFO → REQUESTED` can therefore run at most three times."

        Design: Difficulty/non_linear_state_machine/roaming_authorization_needs_info_revision_cycle_bounded_at_three_rounds
        """
        env = setup_active_subscription()
        subscriber_headers = make_subscriber_headers(env["subscriber"]["id"])
        authorization = self._roaming_request(
            env["subscription"]["id"], env["subscriber"]["id"]
        )

        assert authorization["auth_state"] == "REQUESTED", (
            f"a new request is born REQUESTED, got {authorization['auth_state']}"
        )
        assert authorization["info_round_count"] == 0, (
            f"a new request is born with info_round_count 0, got {authorization['info_round_count']}"
        )

        rounds = [
            ("round 1: confirm travel itinerary", "2026-09-02T00:00:00Z", "2026-09-11T00:00:00Z"),
            ("round 2: confirm vessel registration", "2026-09-03T00:00:00Z", "2026-09-12T00:00:00Z"),
            ("round 3: confirm operating jurisdiction", "2026-09-04T00:00:00Z", "2026-09-13T00:00:00Z"),
        ]
        for index, (note, new_from, new_until) in enumerate(rounds, start=1):
            sent_back = validate_success(
                api.request_roaming_info(
                    authorization["id"], {"info_request_note": note}, compliance_headers
                ),
                200,
            )
            assert sent_back["auth_state"] == "NEEDS_INFO", (
                f"round {index} must move the record to NEEDS_INFO, got {sent_back['auth_state']}"
            )
            assert sent_back["info_round_count"] == index, (
                f"round {index} must leave info_round_count at {index}, got "
                f"{sent_back['info_round_count']}"
            )
            assert sent_back["decision_note"] == note, (
                f"round {index} stores the note in decision_note, got {sent_back.get('decision_note')!r}"
            )

            resubmitted = validate_success(
                api.resubmit_roaming_authorization(
                    authorization["id"],
                    {"effective_from": new_from, "effective_until": new_until},
                    subscriber_headers,
                ),
                200,
            )
            assert resubmitted["auth_state"] == "REQUESTED", (
                f"resubmission {index} closes the round back to REQUESTED, got "
                f"{resubmitted['auth_state']}"
            )
            assert resubmitted["info_round_count"] == index, (
                f"resubmission {index} does not change the round count, got "
                f"{resubmitted['info_round_count']}"
            )

        final = validate_success(
            api.get_roaming_authorization(authorization["id"], compliance_headers), 200
        )
        assert final["effective_from"] == "2026-09-04T00:00:00.000Z", (
            f"the last resubmission's effective_from must be stored, got {final['effective_from']}"
        )
        assert final["effective_until"] == "2026-09-13T00:00:00.000Z", (
            f"the last resubmission's effective_until must be stored, got {final['effective_until']}"
        )

    def test_fourth_information_round_is_refused_and_leaves_the_record_untouched(
        self, api, compliance_headers
    ):
        """With info_round_count standing at 3 the loop is closed: a fourth
        request-info is refused and the record keeps its state, count and window.

        PRD §3.7: "This is legal only from `REQUESTED` — anything else is refused with `ERR_ROAMING_STATE_INVALID` — and only while `info_round_count` is strictly below 3."
        PRD §3.7: "Attempting to open a fourth round when `info_round_count` already stands at 3 is refused with `ERR_ROAMING_ROUND_LIMIT`."
        PRD §3.7: "The cycle `REQUESTED → NEEDS_INFO → REQUESTED` can therefore run at most three times."

        Design: Difficulty/non_linear_state_machine/roaming_authorization_needs_info_revision_cycle_bounded_at_three_rounds
        """
        env = setup_active_subscription()
        subscriber_headers = make_subscriber_headers(env["subscriber"]["id"])
        authorization = self._roaming_request(
            env["subscription"]["id"], env["subscriber"]["id"]
        )

        rounds = [
            ("round 1: confirm travel itinerary", "2026-09-02T00:00:00Z", "2026-09-11T00:00:00Z"),
            ("round 2: confirm vessel registration", "2026-09-03T00:00:00Z", "2026-09-12T00:00:00Z"),
            ("round 3: confirm operating jurisdiction", "2026-09-04T00:00:00Z", "2026-09-13T00:00:00Z"),
        ]
        for note, new_from, new_until in rounds:
            validate_success(
                api.request_roaming_info(
                    authorization["id"], {"info_request_note": note}, compliance_headers
                ),
                200,
            )
            validate_success(
                api.resubmit_roaming_authorization(
                    authorization["id"],
                    {"effective_from": new_from, "effective_until": new_until},
                    subscriber_headers,
                ),
                200,
            )

        response = api.request_roaming_info(
            authorization["id"],
            {"info_request_note": "round 4: one more clarification"},
            compliance_headers,
        )
        validate_error(response, ApiErrorId.ERR_ROAMING_ROUND_LIMIT, 422)

        unchanged = validate_success(
            api.get_roaming_authorization(authorization["id"], compliance_headers), 200
        )
        assert unchanged["info_round_count"] == 3, (
            f"a refused fourth round leaves info_round_count at 3, got {unchanged['info_round_count']}"
        )
        assert unchanged["auth_state"] == "REQUESTED", (
            f"a refused fourth round leaves auth_state REQUESTED, got {unchanged['auth_state']}"
        )
        assert unchanged["effective_from"] == "2026-09-04T00:00:00.000Z", (
            f"the stored window must survive the refusal, got {unchanged['effective_from']}"
        )
        assert unchanged["effective_until"] == "2026-09-13T00:00:00.000Z", (
            f"the stored window must survive the refusal, got {unchanged['effective_until']}"
        )

    def test_each_half_of_the_loop_rejects_the_other_half_s_state(
        self, api, compliance_headers
    ):
        """The loop only turns one way: resubmission is legal solely from
        NEEDS_INFO and an information round solely from REQUESTED.

        PRD §3.7: "Resubmitting from any state other than `NEEDS_INFO` is refused with `ERR_ROAMING_STATE_INVALID`."
        PRD §3.7: "This is legal only from `REQUESTED` — anything else is refused with `ERR_ROAMING_STATE_INVALID` — and only while `info_round_count` is strictly below 3."

        Design: Difficulty/non_linear_state_machine/roaming_authorization_needs_info_revision_cycle_bounded_at_three_rounds
        """
        env = setup_active_subscription()
        subscriber_headers = make_subscriber_headers(env["subscriber"]["id"])
        authorization = self._roaming_request(
            env["subscription"]["id"], env["subscriber"]["id"]
        )

        # Half one: the record is REQUESTED, so a resubmission has nothing to close.
        early_resubmit = api.resubmit_roaming_authorization(
            authorization["id"],
            {"effective_from": "2026-09-02T00:00:00Z", "effective_until": "2026-09-11T00:00:00Z"},
            subscriber_headers,
        )
        validate_error(early_resubmit, ApiErrorId.ERR_ROAMING_STATE_INVALID, 409)

        # Half two: once it is NEEDS_INFO, a further information round is illegal.
        sent_back = validate_success(
            api.request_roaming_info(
                authorization["id"],
                {"info_request_note": "round 1: confirm travel itinerary"},
                compliance_headers,
            ),
            200,
        )
        assert sent_back["auth_state"] == "NEEDS_INFO", (
            f"the first round must reach NEEDS_INFO, got {sent_back['auth_state']}"
        )

        second_round = api.request_roaming_info(
            authorization["id"],
            {"info_request_note": "round 1 again: still waiting"},
            compliance_headers,
        )
        validate_error(second_round, ApiErrorId.ERR_ROAMING_STATE_INVALID, 409)

        unchanged = validate_success(
            api.get_roaming_authorization(authorization["id"], compliance_headers), 200
        )
        assert unchanged["auth_state"] == "NEEDS_INFO", (
            f"the refused round leaves the record NEEDS_INFO, got {unchanged['auth_state']}"
        )
        assert unchanged["info_round_count"] == 1, (
            f"the refused round does not advance the counter, got {unchanged['info_round_count']}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Cascade A: licence suspension -> beam -> subscription -> roaming -> cell
# ═══════════════════════════════════════════════════════════════════════════


class TestLicenceSuspensionFourHopCascade:
    """One compliance write, four ordered hops, three downstream entity types."""

    def test_suspension_walks_beam_then_subscription_then_roaming_then_cell(
        self, api, compliance_headers
    ):
        """Suspending the licence suspends its beam, deauthorises the beam's
        authorised subscriptions with the licence stamped on them, revokes their
        approved roaming grants, and closes the beam's cells.

        PRD §3.1: "Enforcement is the second regulatory lever, and it carries an `action` of either `SUSPEND` or `REINSTATE` together with a mandatory `reason` that is stored in `enforcement_reason`."
        PRD §3.1: "Suspending a licence moves `license_state` from `ACTIVE` to `SUSPENDED` and runs a four-hop cascade in this order."
        PRD §3.1: "Hop one: every beam whose `spectrum_license_id` names this licence and whose `beam_state` is `ACTIVE` moves to `beam_state` `SUSPENDED`."
        PRD §3.1: "Hop two, caused by hop one: for every beam so suspended, every subscription sitting on one of that beam's cells whose `authorization_state` is `AUTHORIZED_FIXED` or `AUTHORIZED_IN_MOTION` moves to `authorization_state` `DEAUTHORIZED`, and that subscription's `deauthorized_by_license_id` is stamped with this licence's id so that a later reinstatement can find it."
        PRD §3.1: "Hop three, caused by hop two: for every subscription deauthorised in hop two, every roaming authorisation naming that subscription whose `auth_state` is `APPROVED` moves to `auth_state` `REVOKED` with `revoked_reason` set to `LICENSE_SUSPENDED`."
        PRD §3.1: "Hop four, also caused by hop one: every coverage cell belonging to a suspended beam recomputes its `availability_state`, which lands on `CLOSED` because the governing beam is out of service."
        PRD §3.9: "What does **not** move is the cell's `committed_terminal_count` — a suspended subscription keeps its slot, so suspending a customer frees megabits but does not free a seat, and no waitlist promotion runs."

        Design: Difficulty/transitive_cascade/license_suspension_cascades_beam_then_subscription_then_roaming_then_cell
        """
        env = setup_approved_roaming_window(target_jurisdiction_code="US-CA")
        license_id = env["license"]["id"]

        response = api.enforcement_action(
            license_id,
            enforcement_action_payload("SUSPEND", reason="regulator enforcement order 2026-114"),
            compliance_headers,
        )
        suspended_license = validate_success(response, 200)

        assert suspended_license["license_state"] == "SUSPENDED", (
            f"the licence must move ACTIVE -> SUSPENDED, got {suspended_license['license_state']}"
        )
        assert suspended_license["enforcement_reason"] == "regulator enforcement order 2026-114", (
            f"the reason must be stored in enforcement_reason, got {suspended_license.get('enforcement_reason')!r}"
        )

        beam = get_beam(env["beam"]["id"])
        assert beam["beam_state"] == "SUSPENDED", (
            f"hop one must put the beam out of service, got {beam['beam_state']}"
        )

        subscription = get_subscription(env["subscription"]["id"])
        assert subscription["authorization_state"] == "DEAUTHORIZED", (
            f"hop two must deauthorise the subscription, got {subscription['authorization_state']}"
        )
        assert subscription["deauthorized_by_license_id"] == license_id, (
            "hop two must stamp deauthorized_by_license_id with the suspended licence, got "
            f"{subscription.get('deauthorized_by_license_id')!r}"
        )
        assert subscription["service_state"] == "ACTIVE", (
            "the provisioning dimension is untouched by the authorisation hop, got "
            f"{subscription['service_state']}"
        )

        roaming = validate_success(
            api.get_roaming_authorization(env["roaming"]["id"], compliance_headers), 200
        )
        assert roaming["auth_state"] == "REVOKED", (
            f"hop three must revoke the approved grant, got {roaming['auth_state']}"
        )
        assert roaming["revoked_reason"] == "LICENSE_SUSPENDED", (
            f"hop three must write revoked_reason LICENSE_SUSPENDED, got {roaming.get('revoked_reason')!r}"
        )

        cell = get_cell(env["cell"]["id"])
        assert cell["availability_state"] == "CLOSED", (
            f"hop four must close the cell of a suspended beam, got {cell['availability_state']}"
        )
        assert cell["committed_terminal_count"] == 1, (
            "the cascade does not release the committed slot, got "
            f"{cell['committed_terminal_count']}"
        )

    def test_hop_three_revokes_only_the_approved_grant(self, api, compliance_headers):
        """Hop three is selective: an APPROVED grant on the deauthorised
        subscription is revoked while a grant still under review is not.

        PRD §3.1: "Hop three, caused by hop two: for every subscription deauthorised in hop two, every roaming authorisation naming that subscription whose `auth_state` is `APPROVED` moves to `auth_state` `REVOKED` with `revoked_reason` set to `LICENSE_SUSPENDED`."
        PRD §3.7: "An `effective_from` landing exactly at the end of the cooldown is accepted; the buffer is exclusive at its far edge."

        Design: Difficulty/transitive_cascade/license_suspension_cascades_beam_then_subscription_then_roaming_then_cell
        """
        env = setup_approved_roaming_window(target_jurisdiction_code="US-CA")
        subscriber_headers = make_subscriber_headers(env["subscriber"]["id"])

        # The approved window closes at 2026-09-10T00:00:00Z, so a window opening
        # exactly 24 hours later clears the cooldown and stays under review.
        pending = validate_success(
            api.create_roaming_authorization(
                create_roaming_authorization_payload(
                    subscription_id=env["subscription"]["id"],
                    mode="ROAM_TEMPORARY",
                    target_jurisdiction_code="US-CA",
                    effective_from="2026-09-11T00:00:00Z",
                    effective_until="2026-09-20T00:00:00Z",
                ),
                subscriber_headers,
            ),
            201,
        )
        assert pending["auth_state"] == "REQUESTED", (
            f"the second grant must sit in REQUESTED, got {pending['auth_state']}"
        )

        validate_success(
            api.enforcement_action(
                env["license"]["id"],
                enforcement_action_payload("SUSPEND", reason="regulator enforcement order 2026-114"),
                compliance_headers,
            ),
            200,
        )

        revoked = validate_success(
            api.get_roaming_authorization(env["roaming"]["id"], compliance_headers), 200
        )
        assert revoked["auth_state"] == "REVOKED", (
            f"the APPROVED grant must be revoked, got {revoked['auth_state']}"
        )
        assert revoked["revoked_reason"] == "LICENSE_SUSPENDED", (
            f"the revoked grant must carry LICENSE_SUSPENDED, got {revoked.get('revoked_reason')!r}"
        )

        untouched = validate_success(
            api.get_roaming_authorization(pending["id"], compliance_headers), 200
        )
        assert untouched["auth_state"] == "REQUESTED", (
            "hop three names only APPROVED grants, so the REQUESTED one must survive, got "
            f"{untouched['auth_state']}"
        )
        assert not untouched.get("revoked_reason"), (
            f"an unrevoked grant carries no revoked_reason, got {untouched.get('revoked_reason')!r}"
        )

    def test_reinstatement_compensates_beam_and_subscription_but_not_roaming(
        self, api, compliance_headers
    ):
        """The stamp hop two wrote is what reinstatement reads: the beam and the
        subscription come back, while hop three's revocation is permanent.

        PRD §3.1: "Moving `license_state` from `SUSPENDED` back to `ACTIVE` returns every beam under the licence whose `beam_state` is `SUSPENDED` to `ACTIVE`, and returns every subscription whose `deauthorized_by_license_id` equals this licence and whose `service_state` is anything other than `TERMINATED` to `authorization_state` `AUTHORIZED_FIXED`, clearing `deauthorized_by_license_id` back to empty in the process."
        PRD §3.1: "Roaming authorisations revoked by the suspension are **not** restored — they stay `REVOKED` and must be requested again."

        Design: Difficulty/transitive_cascade/license_suspension_cascades_beam_then_subscription_then_roaming_then_cell
        """
        env = setup_approved_roaming_window(target_jurisdiction_code="US-CA")
        license_id = env["license"]["id"]

        validate_success(
            api.enforcement_action(
                license_id,
                enforcement_action_payload("SUSPEND", reason="regulator enforcement order 2026-114"),
                compliance_headers,
            ),
            200,
        )
        reinstated = validate_success(
            api.enforcement_action(
                license_id,
                enforcement_action_payload("REINSTATE", reason="investigation closed"),
                compliance_headers,
            ),
            200,
        )
        assert reinstated["license_state"] == "ACTIVE", (
            f"reinstatement must move SUSPENDED -> ACTIVE, got {reinstated['license_state']}"
        )

        beam = get_beam(env["beam"]["id"])
        assert beam["beam_state"] == "ACTIVE", (
            f"the beam must return to service, got {beam['beam_state']}"
        )

        subscription = get_subscription(env["subscription"]["id"])
        assert subscription["authorization_state"] == "AUTHORIZED_FIXED", (
            "a subscription stamped by this licence returns to AUTHORIZED_FIXED, got "
            f"{subscription['authorization_state']}"
        )
        assert not subscription.get("deauthorized_by_license_id"), (
            "the stamp must be cleared back to empty, got "
            f"{subscription.get('deauthorized_by_license_id')!r}"
        )

        roaming = validate_success(
            api.get_roaming_authorization(env["roaming"]["id"], compliance_headers), 200
        )
        assert roaming["auth_state"] == "REVOKED", (
            f"a revoked roaming grant is never restored, got {roaming['auth_state']}"
        )
        assert roaming["revoked_reason"] == "LICENSE_SUSPENDED", (
            f"the revocation reason survives reinstatement, got {roaming.get('revoked_reason')!r}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Cascade B: replacement install -> replaced unit -> subscription -> beam -> cell
# ═══════════════════════════════════════════════════════════════════════════


class TestWarrantyReplacementInstallFourHopCascade:
    """A logistics install four hops away from a beam's congestion figures."""

    def test_replacement_install_retires_the_unit_resumes_service_and_reprices_the_beam(
        self, api
    ):
        """Installing the replacement retires the faulty unit, resumes the
        RMA-suspended subscription on the new hardware, re-absorbs its megabits
        and recomputes the cell's advertised availability.

        PRD §3.4: "Installing from `DELIVERED` can, however, be the last step of a warranty replacement, and when it is, a four-hop cascade fires."
        PRD §3.4: "Hop one applies only when this terminal's `replaces_terminal_id` names another terminal and that other terminal's `terminal_state` is `RMA_PENDING`: the replaced unit moves `RMA_PENDING → REPLACED`, which is terminal for it."
        PRD §3.4: "Hop two, caused by hop one: the subscription whose `terminal_id` is the replaced unit and whose `service_state` is `SUSPENDED` has its `terminal_id` re-pointed at this newly installed terminal, moves `SUSPENDED → ACTIVE`, and has its `suspension_reason` cleared to empty; the owning subscriber's `account_state` moves from `SUSPENDED` back to `ACTIVE`."
        PRD §3.4: "Hop three, caused by hop two: that subscription's beam recomputes `weighted_sold_mbps`, `oversubscription_ratio` and `capacity_state`, because a subscription returning to `ACTIVE` re-enters the sold set."
        PRD §3.4: "Hop four, caused by hop three: every coverage cell of that beam recomputes `availability_state`."
        PRD §3.3: "Otherwise, with no free slots, it is `WAITLIST_ONLY` when the cell's `waitlist_depth` is strictly below 3, and `CLOSED` when `waitlist_depth` has reached 3 or more."

        Design: Difficulty/transitive_cascade/warranty_replacement_install_replaces_terminal_resumes_service_and_reprices_beam
        """
        env = setup_rma_in_flight()
        faulty_id = env["terminal"]["id"]
        replacement_id = env["replacement_terminal"]["id"]
        subscriber_id = env["subscriber"]["id"]

        deliver_terminal(replacement_id)
        scan_terminal(replacement_id, subscriber_id, obstructed_sample_count=1, total_sample_count=200)

        response = api.install_terminal(replacement_id, make_subscriber_headers(subscriber_id))
        installed = validate_success(response, 200)

        assert installed["terminal_state"] == "INSTALLED", (
            f"the replacement must reach INSTALLED, got {installed['terminal_state']}"
        )
        assert installed["replaces_terminal_id"] == faulty_id, (
            "the replacement must point at the faulty unit, got "
            f"{installed.get('replaces_terminal_id')!r}"
        )

        faulty = get_terminal(faulty_id)
        assert faulty["terminal_state"] == "REPLACED", (
            f"hop one must retire the faulty unit as REPLACED, got {faulty['terminal_state']}"
        )

        subscription = get_subscription(env["subscription"]["id"])
        assert subscription["service_state"] == "ACTIVE", (
            f"hop two must resume the subscription SUSPENDED -> ACTIVE, got {subscription['service_state']}"
        )
        assert subscription["terminal_id"] == replacement_id, (
            "hop two must re-point terminal_id at the newly installed unit, got "
            f"{subscription['terminal_id']}"
        )
        assert not subscription.get("suspension_reason"), (
            f"hop two must clear suspension_reason, got {subscription.get('suspension_reason')!r}"
        )

        beam = get_beam(env["beam"]["id"])
        assert beam["weighted_sold_mbps"] == pytest.approx(200.0, abs=0.001), (
            "hop three must re-absorb the resumed subscription's megabits, got "
            f"{beam['weighted_sold_mbps']}"
        )
        assert beam["oversubscription_ratio"] == pytest.approx(2.0, abs=0.001), (
            f"200 sold megabits over 100 Mbps of capacity is a ratio of 2.0, got {beam['oversubscription_ratio']}"
        )
        assert beam["capacity_state"] == "NORMAL", (
            f"a ratio of 2.0 against a limit of 4.0 bands as NORMAL, got {beam['capacity_state']}"
        )

        cell = get_cell(env["cell"]["id"])
        assert cell["availability_state"] == "WAITLIST_ONLY", (
            "hop four recomputes the cell: no free slot and an empty waitlist reads "
            f"WAITLIST_ONLY, got {cell['availability_state']}"
        )
        assert cell["committed_terminal_count"] == 1, (
            f"the resumed subscription still holds its slot, got {cell['committed_terminal_count']}"
        )
        assert cell["free_slot_count"] == 0, (
            f"the only slot on the cell is committed, got {cell['free_slot_count']}"
        )

        subscriber = get_subscriber(subscriber_id)
        assert subscriber["account_state"] == "ACTIVE", (
            f"hop two returns the account to ACTIVE, got {subscriber['account_state']}"
        )

    def test_beam_megabits_drop_on_the_rma_and_return_on_the_replacement_install(
        self, api, logistics_headers
    ):
        """The round trip: raising the RMA suspends the service and empties the
        beam's sold set, and installing the replacement puts it back exactly.

        PRD §3.4: "From `INSTALLED`, a three-hop cascade fires: hop one moves the subscription whose `terminal_id` is the faulty unit and whose `service_state` is `PENDING_ACTIVATION` or `ACTIVE` to `SUSPENDED` with `suspension_reason` set to `RMA_IN_FLIGHT`; hop two, caused by hop one, recomputes that subscription's beam, whose `weighted_sold_mbps` falls because a suspended subscription leaves the sold set; hop three, caused by hop two, recomputes `availability_state` on every cell of that beam — and the cell **keeps** the committed slot, because a suspended subscription still counts inside `committed_terminal_count`."
        PRD §3.4: "A new terminal record is created in `terminal_state` `SHIPPED`, carrying the faulty unit's `subscriber_id`, a `replaces_terminal_id` pointing at the faulty unit, and `warranty_expires_at` taken from `replacement_warranty_expires_at`."
        PRD §3.4: "Hop three, caused by hop two: that subscription's beam recomputes `weighted_sold_mbps`, `oversubscription_ratio` and `capacity_state`, because a subscription returning to `ACTIVE` re-enters the sold set."

        Design: Difficulty/transitive_cascade/warranty_replacement_install_replaces_terminal_resumes_service_and_reprices_beam
        """
        env = setup_active_subscription()
        beam_id = env["beam"]["id"]
        subscriber_id = env["subscriber"]["id"]

        before = get_beam(beam_id)
        assert before["weighted_sold_mbps"] == pytest.approx(200.0, abs=0.001), (
            f"a PRIORITY_1 subscription on a 200 Mbps plan sells 200 megabits, got {before['weighted_sold_mbps']}"
        )

        replacement = validate_success(
            api.warranty_replacement(
                env["terminal"]["id"],
                warranty_replacement_payload(
                    replacement_serial_number="TRM-0001R",
                    replacement_warranty_expires_at="2029-08-01T00:00:00Z",
                ),
                logistics_headers,
            ),
            201,
        )
        assert replacement["terminal_state"] == "SHIPPED", (
            f"the replacement unit is born SHIPPED, got {replacement['terminal_state']}"
        )
        assert replacement["replaces_terminal_id"] == env["terminal"]["id"], (
            "the replacement must point at the faulty unit, got "
            f"{replacement.get('replaces_terminal_id')!r}"
        )

        suspended = get_subscription(env["subscription"]["id"])
        assert suspended["service_state"] == "SUSPENDED", (
            f"the RMA must suspend the bound subscription, got {suspended['service_state']}"
        )
        assert suspended["suspension_reason"] == "RMA_IN_FLIGHT", (
            f"the RMA writes suspension_reason RMA_IN_FLIGHT, got {suspended.get('suspension_reason')!r}"
        )

        during = get_beam(beam_id)
        assert during["weighted_sold_mbps"] == pytest.approx(0.0, abs=0.001), (
            f"a suspended subscription leaves the sold set, got {during['weighted_sold_mbps']}"
        )
        assert during["oversubscription_ratio"] == pytest.approx(0.0, abs=0.001), (
            f"an empty sold set gives a ratio of 0, got {during['oversubscription_ratio']}"
        )
        assert get_cell(env["cell"]["id"])["committed_terminal_count"] == 1, (
            "the cell keeps the committed slot across the RMA"
        )

        deliver_terminal(replacement["id"])
        scan_terminal(replacement["id"], subscriber_id, obstructed_sample_count=1, total_sample_count=200)
        install_terminal(replacement["id"], subscriber_id)

        after = get_beam(beam_id)
        assert after["weighted_sold_mbps"] == pytest.approx(200.0, abs=0.001), (
            f"the resumed subscription re-enters the sold set, got {after['weighted_sold_mbps']}"
        )
        assert after["oversubscription_ratio"] == pytest.approx(2.0, abs=0.001), (
            f"200 megabits over 100 Mbps is a ratio of 2.0, got {after['oversubscription_ratio']}"
        )
        assert after["capacity_state"] == "NORMAL", (
            f"a ratio of 2.0 against a limit of 4.0 bands as NORMAL, got {after['capacity_state']}"
        )

    def test_hop_two_finds_nobody_when_the_rma_was_raised_before_activation(
        self, api, logistics_headers
    ):
        """A replacement raised from DELIVERED has no bound service, so its
        install still retires the faulty unit at hop one and stops there.

        PRD §3.4: "From `DELIVERED`, no subscription is bound yet, so the replacement record is created and the faulty unit moves `DELIVERED → RMA_PENDING` with no further cascade at all."
        PRD §3.4: "Hop one applies only when this terminal's `replaces_terminal_id` names another terminal and that other terminal's `terminal_state` is `RMA_PENDING`: the replaced unit moves `RMA_PENDING → REPLACED`, which is terminal for it."
        PRD §3.4: "Hop two, caused by hop one: the subscription whose `terminal_id` is the replaced unit and whose `service_state` is `SUSPENDED` has its `terminal_id` re-pointed at this newly installed terminal, moves `SUSPENDED → ACTIVE`, and has its `suspension_reason` cleared to empty; the owning subscriber's `account_state` moves from `SUSPENDED` back to `ACTIVE`."

        Design: Difficulty/transitive_cascade/warranty_replacement_install_replaces_terminal_resumes_service_and_reprices_beam
        """
        env = setup_reserved_order(install_terminal_too=False)
        faulty_id = env["terminal"]["id"]
        subscriber_id = env["subscriber"]["id"]
        deliver_terminal(faulty_id)

        replacement = validate_success(
            api.warranty_replacement(
                faulty_id,
                warranty_replacement_payload(
                    replacement_serial_number="TRM-0001R",
                    replacement_warranty_expires_at="2029-08-01T00:00:00Z",
                ),
                logistics_headers,
            ),
            201,
        )
        assert get_terminal(faulty_id)["terminal_state"] == "RMA_PENDING", (
            "a replacement raised from DELIVERED moves the faulty unit to RMA_PENDING"
        )

        deliver_terminal(replacement["id"])
        scan_terminal(replacement["id"], subscriber_id, obstructed_sample_count=1, total_sample_count=200)
        installed = validate_success(
            api.install_terminal(replacement["id"], make_subscriber_headers(subscriber_id)), 200
        )

        assert installed["terminal_state"] == "INSTALLED", (
            f"the replacement must reach INSTALLED, got {installed['terminal_state']}"
        )
        faulty = get_terminal(faulty_id)
        assert faulty["terminal_state"] == "REPLACED", (
            f"hop one still fires against an RMA_PENDING predecessor, got {faulty['terminal_state']}"
        )

        beam = get_beam(env["beam"]["id"])
        assert beam["weighted_sold_mbps"] == pytest.approx(0.0, abs=0.001), (
            "with no subscription to resume the beam sells nothing, got "
            f"{beam['weighted_sold_mbps']}"
        )
        cell = get_cell(env["cell"]["id"])
        assert cell["committed_terminal_count"] == 0, (
            f"no subscription was ever created on this cell, got {cell['committed_terminal_count']}"
        )
        assert cell["reserved_slot_count"] == 1, (
            f"the order's reservation is still the only hold, got {cell['reserved_slot_count']}"
        )

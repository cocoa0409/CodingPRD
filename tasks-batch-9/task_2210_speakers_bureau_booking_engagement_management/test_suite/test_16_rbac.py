"""Role authority, the order the role gate is evaluated in, and peer isolation.

The workflow is deliberately split across four roles, so the happy path is only
reachable when each of them performs its own operations.  The refusals then
distinguish the two 403 codes: a role that is simply not listed for an endpoint
is unauthorised, while a listed role acting on someone else's row is not the
resource owner.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    AGENT_USER_ID,
    ApiErrorId,
    create_second_speaker,
    find_holds_for_speaker,
    make_speaker_headers,
    minimal_speaker_payload,
    payment_payload,
    proposal_option_payload,
    qualify_payload,
    read_contract,
    read_engagement,
    read_inquiry,
    read_invoice,
    read_proposal,
    read_remittance,
    read_speaker,
    remittance_payout_payload,
    set_clock,
    setup_contracted_engagement,
    setup_draft_proposal,
    setup_offered_engagement,
    validate_error,
    validate_paginated,
    validate_success,
)

DELIVERY_CLOCK_UTC = "2026-10-15T20:00:00Z"
INVOICE_TOTAL_CENTS = 1_297_313
NET_PAYABLE_CENTS = 956_250
BUFFERED_DAY_SPAN = 3


def _deliver_and_settle(api, bundle: dict) -> dict:
    """Agent delivers, then the client pays its own invoice in full."""
    set_clock(api, DELIVERY_CLOCK_UTC)
    delivered = validate_success(
        api.deliver_engagement(bundle["engagement"]["id"], AGENT_HEADERS)
    )
    rows, _meta = validate_paginated(
        api.list_invoices(
            ADMIN_HEADERS, params={"engagement_id": bundle["engagement"]["id"]}
        )
    )
    invoice = rows[0]
    paid = validate_success(
        api.create_invoice_payment(
            invoice["id"],
            payment_payload(invoice["amount_due_cents"]),
            bundle["client_headers"],
        )
    )
    remittances, _rmeta = validate_paginated(
        api.list_remittances(
            ADMIN_HEADERS, params={"engagement_id": bundle["engagement"]["id"]}
        )
    )
    return {
        "delivered": delivered,
        "invoice": paid,
        "remittance": remittances[0],
    }


class TestEveryRoleExecutesItsOwnOperations:
    def test_the_four_roles_interlock_to_reach_an_executed_agreement(self, api):
        """Admin rosters, agent quotes, client selects, speaker confirms, and both parties sign their own leg.

        PRD: At the join, the party who has not yet signed drives `PARTIALLY_SIGNED → EXECUTED`, and that second signature must still satisfy its own guard — the speaker's `roster_status` for the speaker leg, the client's `credit_status` for the client leg.
        Design: Corner/rbac/each_role_executes_its_own_exclusive_operations_end_to_end
        """
        bundle = setup_contracted_engagement(api)

        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "WON"
        assert (
            read_inquiry(api, bundle["inquiry"]["id"])["owning_agent_user_id"]
            == AGENT_USER_ID
        )
        assert read_proposal(api, bundle["proposal"]["id"])["status"] == "CLOSED"

        contract = read_contract(api, bundle["contract"]["id"])
        assert contract["status"] == "EXECUTED"
        assert contract["speaker_signed_at_utc"] is not None
        assert contract["client_signed_at_utc"] is not None
        assert contract["executed_at_utc"] is not None

        assert (
            read_engagement(api, bundle["engagement"]["id"])["booking_status"]
            == "CONTRACTED"
        )

    def test_the_booking_agent_delivers_and_the_client_settles_the_invoice(self, api):
        """Delivery belongs to the deal desk and payment to the paying party, and both are accepted.

        PRD: A payment exactly equal to the remaining balance drives the invoice to `PAID` — `ISSUED → PAID` when this single payment settles the whole invoice, or `PARTIALLY_PAID → PAID` when earlier partial payments had already landed — drives the settlement dimension to `COLLECTED` by the matching leg, `INVOICED → COLLECTED` in the first case and `PARTIALLY_COLLECTED → COLLECTED` in the second, and, as a cascade, moves that engagement's remittance `PENDING → APPROVED`.
        Design: Corner/rbac/each_role_executes_its_own_exclusive_operations_end_to_end
        """
        bundle = setup_contracted_engagement(api)

        result = _deliver_and_settle(api, bundle)

        assert result["delivered"]["booking_status"] == "DELIVERED"
        assert result["invoice"]["status"] == "PAID"
        assert result["invoice"]["amount_paid_cents"] == INVOICE_TOTAL_CENTS
        assert result["remittance"]["status"] == "APPROVED"
        assert (
            read_engagement(api, bundle["engagement"]["id"])["settlement_status"]
            == "COLLECTED"
        )

    def test_the_bureau_admin_closes_the_chain_with_the_payout(self, api):
        """The last money movement is back-office only, and it completes the settlement lane.

        PRD: The payout drives the remittance `APPROVED → PAID`, stamps `paid_at_utc` with the logical clock, decreases the speaker's `pending_remittance_cents` by `net_payable_cents`, drives the engagement's settlement dimension `COLLECTED → REMITTED`, and moves every travel expense of that engagement sitting in `APPROVED` to `REIMBURSED`.
        Design: Corner/rbac/each_role_executes_its_own_exclusive_operations_end_to_end
        """
        bundle = setup_contracted_engagement(api)
        result = _deliver_and_settle(api, bundle)

        paid_out = validate_success(
            api.pay_remittance(
                result["remittance"]["id"], remittance_payout_payload(), ADMIN_HEADERS
            )
        )
        assert paid_out["status"] == "PAID"
        assert paid_out["paid_at_utc"] is not None
        assert paid_out["net_payable_cents"] == NET_PAYABLE_CENTS

        assert read_invoice(api, result["invoice"]["id"])["status"] == "PAID"
        assert read_remittance(api, result["remittance"]["id"])["status"] == "PAID"
        assert (
            read_engagement(api, bundle["engagement"]["id"])["settlement_status"]
            == "REMITTED"
        )
        assert (
            read_speaker(api, bundle["speaker"]["id"])["pending_remittance_cents"] == 0
        )


class TestClientHasNoDeskOrBackOfficeAuthority:
    def test_the_client_may_not_qualify_the_inquiry_it_owns(self, api):
        """Owning the inquiry does not put the client on the deal desk.

        PRD: If the role is well-formed but is not among the roles listed for the target endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).
        Design: Corner/rbac/client_cannot_perform_agent_or_admin_exclusive_operations
        """
        bundle = setup_draft_proposal(api)
        before = read_inquiry(api, bundle["inquiry"]["id"])

        validate_error(
            api.qualify_inquiry(
                bundle["inquiry"]["id"], qualify_payload(), bundle["client_headers"]
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )

        after = read_inquiry(api, bundle["inquiry"]["id"])
        assert after["status"] == "QUALIFIED"
        assert after["version"] == before["version"]

    def test_the_client_may_neither_quote_an_option_nor_register_a_speaker(self, api):
        """Quoting and roster maintenance are refused, and nothing is created by the attempts.

        PRD: The supplied role appears in the target endpoint's role list — otherwise `ERR_UNAUTHORIZED` (403). Same scope as above.
        Design: Corner/rbac/client_cannot_perform_agent_or_admin_exclusive_operations
        """
        bundle = setup_draft_proposal(api)
        options_before = read_proposal(api, bundle["proposal"]["id"])["options_count"]

        validate_error(
            api.create_proposal_option(
                proposal_option_payload(
                    bundle["proposal"]["id"], bundle["speaker"]["id"], rank_no=2
                ),
                bundle["client_headers"],
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )
        validate_error(
            api.create_speaker(
                minimal_speaker_payload(full_name="Self Serve"),
                bundle["client_headers"],
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )

        assert (
            read_proposal(api, bundle["proposal"]["id"])["options_count"]
            == options_before
        )
        _rows, meta = validate_paginated(api.list_speakers(ADMIN_HEADERS))
        assert meta["total_count"] == 1

    def test_the_role_gate_is_reported_ahead_of_the_state_check(self, api):
        """An already-qualified inquiry would also fail its transition check, but authorisation is reported first.

        PRD: When more than one rule would fail, the server reports the failure that comes first in the following ladder.
        Design: Corner/rbac/client_cannot_perform_agent_or_admin_exclusive_operations
        """
        bundle = setup_draft_proposal(api)
        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "QUALIFIED"

        validate_error(
            api.qualify_inquiry(
                bundle["inquiry"]["id"], qualify_payload(), bundle["client_headers"]
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )

        validate_error(
            api.qualify_inquiry(
                bundle["inquiry"]["id"], qualify_payload(), AGENT_HEADERS
            ),
            ApiErrorId.ERR_INQUIRY_STATE_INVALID.value,
            expected_status=409,
        )


class TestPeerIsolationInsideTheSpeakerRole:
    def test_another_rostered_speaker_is_refused_on_ownership(self, api):
        """The role gate and the path both pass, so the refusal has to be the ownership code.

        PRD: A caller who passes authentication and authorisation but fails the ownership test above is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
        Design: Corner/rbac/speaker_cannot_confirm_another_speakers_engagement
        """
        bundle = setup_offered_engagement(api)
        other_speaker = create_second_speaker(api)

        validate_error(
            api.confirm_engagement(
                bundle["engagement"]["id"],
                make_speaker_headers(other_speaker["id"]),
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            expected_status=403,
        )

        assert (
            read_engagement(api, bundle["engagement"]["id"])["booking_status"]
            == "OFFERED"
        )
        assert read_speaker(api, other_speaker["id"])["held_days_count"] == 0
        assert find_holds_for_speaker(api, other_speaker["id"]) == []

    def test_the_assigned_speaker_then_confirms_and_takes_the_hold(self, api):
        """The refused peer changed nothing, so the engagement's own speaker still confirms cleanly.

        PRD: When all of that passes, the engagement moves `OFFERED → CONFIRMED`, the server mints a hold of `kind` `ENGAGEMENT` and `status` `ACTIVE` spanning exactly that buffered closed interval — so `hold_start_utc` is `event_start_utc` minus the buffer and `hold_end_utc` is `event_end_utc` plus the buffer — and the speaker's `held_days_count` grows by the new hold's `day_span`.
        Design: Corner/rbac/speaker_cannot_confirm_another_speakers_engagement
        """
        bundle = setup_offered_engagement(api)
        other_speaker = create_second_speaker(api)

        validate_error(
            api.confirm_engagement(
                bundle["engagement"]["id"], make_speaker_headers(other_speaker["id"])
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        )

        confirmed = validate_success(
            api.confirm_engagement(
                bundle["engagement"]["id"], bundle["speaker_headers"]
            )
        )
        assert confirmed["booking_status"] == "CONFIRMED"

        assigned = read_speaker(api, bundle["speaker"]["id"])
        assert assigned["held_days_count"] == BUFFERED_DAY_SPAN
        holds = find_holds_for_speaker(api, bundle["speaker"]["id"])
        assert len(holds) == 1
        assert holds[0]["kind"] == "ENGAGEMENT"
        assert holds[0]["status"] == "ACTIVE"
        assert read_speaker(api, other_speaker["id"])["held_days_count"] == 0

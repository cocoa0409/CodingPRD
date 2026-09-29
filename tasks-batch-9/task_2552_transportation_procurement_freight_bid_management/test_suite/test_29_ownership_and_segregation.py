"""Two 403s that are not about the role, plus the 401 that outranks both.

`CarrierRep` is entity-backed, so an identical payload is accepted for its own
carrier and refused with `ERR_NOT_RESOURCE_OWNER` for a peer's — a different
identifier from the role refusal, because the rep is a listed role on each of
those endpoints. Segregation of duties then bars one opaque operator identity
from countersigning exactly the contracts whose allocations it approved. Above
both sits header integrity, which answers 401 before any other rule is consulted.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    api_client,
    commit_award,
    create_qualified_carrier,
    get_success_data,
    invitation_response_payload,
    invite_carrier,
    lane_bid_payload,
    list_contracts,
    make_carrier_rep_headers,
    make_category_manager_headers,
    make_contract_admin_headers,
    publish_scorecard,
    rate_record_payload,
    read_allocation,
    read_contract,
    read_event,
    scorecard_dispute_payload,
    second_carrier_overrides,
    set_clock,
    setup_awarded_event,
    setup_open_round_with_bidder,
    setup_published_routing_guide,
    sign_as_carrier,
    validate_error,
    validate_success,
)

# The operator who approves the allocation, and the colleague who does not.
APPROVER_ID = "op-777"
COLLEAGUE_ID = "op-888"
APPROVER_AS_MANAGER = make_category_manager_headers(APPROVER_ID)
APPROVER_AS_ADMIN = make_contract_admin_headers(APPROVER_ID)
COLLEAGUE_AS_ADMIN = make_contract_admin_headers(COLLEAGUE_ID)

# Malformed header sets: no role, no principal, and a role that does not exist.
NO_ROLE_HEADERS = {"X-User-ID": "pa-001", "Content-Type": "application/json"}
NO_PRINCIPAL_HEADERS = {
    "X-User-Role": "ProcurementAnalyst",
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": "pa-001",
    "X-User-Role": "SuperUser",
    "Content-Type": "application/json",
}
REP_WITHOUT_PRINCIPAL_HEADERS = {
    "X-User-Role": "CarrierRep",
    "Content-Type": "application/json",
}


def _respond(invitation_id, headers, **overrides):
    return api_client.respond_to_invitation(
        invitation_id, invitation_response_payload(**overrides), headers
    )


def _read_invitation(invitation_id):
    return get_success_data(api_client.get_invitation(invitation_id, ANALYST))


def _bid_for(round_id, lane_id, named_carrier_id, headers):
    """Submits a bid whose body names `named_carrier_id`, acting as `headers`."""
    return api_client.create_lane_bid(
        round_id, lane_bid_payload(lane_id, named_carrier_id), headers
    )


def _sign_as_carrier(contract_id, headers):
    return api_client.sign_contract_as_carrier(contract_id, headers)


def _sign_as_shipper(contract_id, headers):
    return api_client.sign_contract_as_shipper(contract_id, headers)


def _dispute(scorecard_id, headers):
    return api_client.dispute_scorecard(
        scorecard_id, scorecard_dispute_payload(), headers
    )


def _stage(contract, lane, carrier, allocation, headers):
    return api_client.create_rate_record(
        contract["id"],
        rate_record_payload(lane["id"], carrier["id"], allocation["id"]),
        headers,
    )


def _barred_contract():
    """An executed award whose allocation was approved by `APPROVER_ID`."""
    ctx = setup_published_routing_guide()
    ctx["allocation"] = validate_success(
        api_client.approve_award_allocation(
            ctx["allocation"]["id"], APPROVER_AS_MANAGER
        )
    )
    commit_award(ctx["event"]["id"])
    contracts = list_contracts(bid_event_id=ctx["event"]["id"])
    assert len(contracts) == 1
    ctx["contract"] = sign_as_carrier(contracts[0]["id"], ctx["carrier"]["id"])
    ctx["allocation"] = read_allocation(ctx["allocation"]["id"])
    return ctx


def _read_scorecard(carrier_id, scorecard_id):
    body = get_success_data(
        api_client.list_carrier_scorecards(carrier_id, CATEGORY_MANAGER)
    )
    rows = body["data"] if isinstance(body, dict) and "data" in body else body
    matches = [row for row in rows if row["id"] == scorecard_id]
    assert len(matches) == 1
    return matches[0]


class TestACarrierRepIsScopedToItsOwnCarrier:
    """A listed role, so the refusal is ownership rather than role."""

    def test_a_peer_may_not_answer_an_invitation_or_bid_in_another_name(self):
        """The check reads the path row and the request body alike.

        PRD §2.1: "may respond to an invitation only when the invitation's `carrier_id`
        equals `X-User-ID`; may apply the carrier signature only when the contract's
        `carrier_id` equals `X-User-ID`; may dispute a scorecard only when the
        scorecard's `carrier_id` equals `X-User-ID`; and may submit a mini-bid proposal
        or a lane bid only when the `carrier_id` in the request payload equals
        `X-User-ID`. A mismatch on any of those six operations produces
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §2.2: "**Resource ownership.** When the acting role is `CarrierRep`,
        `X-User-ID` must equal the carrier that owns the target, as enumerated in §2.1,
        otherwise `ERR_NOT_RESOURCE_OWNER` (403). This applies to lane-bid withdrawal,
        invitation response, carrier signature, scorecard dispute, mini-bid proposal and
        lane-bid submission."

        Design: Corner/rbac/carrier_rep_cannot_act_on_another_carriers_records
        """
        ctx = setup_open_round_with_bidder()
        first_rep = make_carrier_rep_headers(ctx["carrier"]["id"])
        peer = create_qualified_carrier(carrier_overrides=second_carrier_overrides())
        peer_rep = make_carrier_rep_headers(peer["id"])
        peer_invitation = invite_carrier(ctx["event"]["id"], peer["id"])
        assert peer_invitation["status"] == "SENT"

        validate_error(
            _respond(peer_invitation["id"], first_rep, accept=True, nda_signed=True),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        assert _read_invitation(peer_invitation["id"])["status"] == "SENT"
        assert read_event(ctx["event"]["id"])["accepted_invitation_count"] == 1

        accepted = validate_success(
            _respond(peer_invitation["id"], peer_rep, accept=True, nda_signed=True)
        )
        assert accepted["status"] == "ACCEPTED"
        assert read_event(ctx["event"]["id"])["accepted_invitation_count"] == 2

        validate_error(
            _bid_for(ctx["bid_round"]["id"], ctx["lane"]["id"], peer["id"], first_rep),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        own_bid = validate_success(
            _bid_for(
                ctx["bid_round"]["id"],
                ctx["lane"]["id"],
                ctx["carrier"]["id"],
                first_rep,
            ),
            201,
        )
        assert own_bid["carrier_id"] == ctx["carrier"]["id"]

    def test_a_peer_may_neither_sign_the_contract_nor_dispute_the_scorecard(self):
        """Both rows reference a carrier, so both are ownership-scoped.

        PRD §3.2: "**Disputing a scorecard.** A carrier representative may dispute a
        scorecard belonging to its own carrier, supplying a `disputed_reason`. The
        scorecard must be `PUBLISHED`; a scorecard still in `DRAFT` cannot be disputed
        and the attempt is rejected with `ERR_SCORECARD_NOT_PUBLISHED` (409)."
        PRD §2.11: "The carrier-side signature carries no equivalent restriction; it is
        gated only by the ownership rule of §2.1."
        PRD §3.8: "A carrier representative signs on behalf of its own carrier: from
        `PENDING_BOTH` the `signature_status` becomes `PENDING_SHIPPER`, and from
        `PENDING_CARRIER` it becomes `FULLY_SIGNED` and the contract's `status` moves
        from `DRAFT` to `EXECUTED`."

        Design: Corner/rbac/carrier_rep_cannot_act_on_another_carriers_records
        """
        ctx = setup_awarded_event()
        owner_rep = make_carrier_rep_headers(ctx["carrier"]["id"])
        peer = create_qualified_carrier(carrier_overrides=second_carrier_overrides())
        peer_rep = make_carrier_rep_headers(peer["id"])
        assert ctx["contract"]["signature_status"] == "PENDING_BOTH"

        validate_error(
            _sign_as_carrier(ctx["contract"]["id"], peer_rep),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )
        untouched = read_contract(ctx["contract"]["id"])
        assert untouched["signature_status"] == "PENDING_BOTH"
        assert untouched["status"] == "DRAFT"

        signed = validate_success(_sign_as_carrier(ctx["contract"]["id"], owner_rep))
        assert signed["signature_status"] == "PENDING_SHIPPER"

        scorecard = publish_scorecard(ctx["carrier"]["id"])
        assert scorecard["status"] == "PUBLISHED"
        validate_error(
            _dispute(scorecard["id"], peer_rep), "ERR_NOT_RESOURCE_OWNER", 403
        )
        assert _read_scorecard(ctx["carrier"]["id"], scorecard["id"])["status"] == (
            "PUBLISHED"
        )

        disputed = validate_success(_dispute(scorecard["id"], owner_rep))
        assert disputed["status"] == "DISPUTED"


class TestTheApproverMayNeverCountersign:
    """The bar follows the operator identifier, and no state change lifts it."""

    def test_the_approving_operator_is_barred_while_a_colleague_is_not(self):
        """Same human, two role labels, one refusal keyed on the identifier.

        PRD §2.11: "when a shipper signature is applied to a contract, the acting
        `X-User-ID` must not appear as `approved_by_user_id` on **any** award allocation
        whose pairing of `bid_event_id` and `carrier_id` matches that contract's own
        pairing."
        PRD §2.11: "It does not matter that the approval was performed under the
        `CategoryManager` label and the signature under the `ContractAdmin` label;
        because both are opaque operator identities, the same person can hold both, and
        it is the identifier — not the role — that is compared."
        PRD §3.8: "A contract administrator countersigns on the shipper's behalf: from
        `PENDING_BOTH` the `signature_status` becomes `PENDING_CARRIER`, and from
        `PENDING_SHIPPER` it becomes `FULLY_SIGNED` and `status` moves from `DRAFT` to
        `EXECUTED`."

        Design: Corner/rbac/the_approver_of_an_allocation_cannot_countersign_its_contract
        """
        ctx = _barred_contract()
        assert ctx["allocation"]["approved_by_user_id"] == APPROVER_ID
        assert ctx["contract"]["signature_status"] == "PENDING_SHIPPER"
        assert ctx["contract"]["status"] == "DRAFT"

        validate_error(
            _sign_as_shipper(ctx["contract"]["id"], APPROVER_AS_ADMIN),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        unchanged = read_contract(ctx["contract"]["id"])
        assert unchanged["signature_status"] == "PENDING_SHIPPER"
        assert unchanged["status"] == "DRAFT"
        assert unchanged["shipper_signed_by_user_id"] is None

        countersigned = validate_success(
            _sign_as_shipper(ctx["contract"]["id"], COLLEAGUE_AS_ADMIN)
        )
        assert countersigned["signature_status"] == "FULLY_SIGNED"
        assert countersigned["status"] == "EXECUTED"
        assert countersigned["shipper_signed_by_user_id"] == COLLEAGUE_ID

    def test_the_bar_outranks_the_state_check_and_withholds_only_the_signature(self):
        """A permanent 403, and the same operator still runs the rate desk.

        PRD §2.11: "A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403),
        and the bar is permanent: no later state change lifts it."
        PRD §2.9: "Checks are evaluated in a single fixed ascending order, and **the
        first violated check decides the response** — no later check is evaluated and no
        partial write is retained."
        PRD §3.8: "The record is created with `status` `STAGED`; `acceptance_pct`
        `100.00` and `rejection_pct` `0.00`, the neutral starting position of a lane that
        has never been tendered; `tender_count` `0`"

        Design: Corner/rbac/the_approver_of_an_allocation_cannot_countersign_its_contract
        """
        ctx = _barred_contract()
        validate_error(
            _sign_as_shipper(ctx["contract"]["id"], APPROVER_AS_ADMIN),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )
        validate_success(_sign_as_shipper(ctx["contract"]["id"], COLLEAGUE_AS_ADMIN))

        retried = _sign_as_shipper(ctx["contract"]["id"], APPROVER_AS_ADMIN)
        validate_error(retried, "ERR_SEGREGATION_OF_DUTIES", 403)
        assert retried.status_code == 403, (
            "the segregation check runs before the state check, so this is not a 409"
        )

        staged = validate_success(
            _stage(
                ctx["contract"],
                ctx["lane"],
                ctx["carrier"],
                ctx["allocation"],
                APPROVER_AS_ADMIN,
            ),
            201,
        )
        assert staged["status"] == "STAGED"
        loaded = validate_success(
            api_client.load_rate_record(staged["id"], APPROVER_AS_ADMIN)
        )
        assert loaded["status"] == "LOADED", (
            "only the countersignature is withheld from the barred operator"
        )


class TestHeaderIntegrityOutranksEveryOtherRule:
    """Priority 1 answers first, even on an open read and a wrong path id."""

    def test_missing_and_unrecognised_headers_all_answer_unauthenticated(self):
        """Four malformed header sets, one identifier, no leakage of existence.

        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of those
        five strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.2: "**Header integrity.** Both `X-User-ID` and `X-User-Role` are present
        and the role is one of the five declared names, otherwise `ERR_UNAUTHENTICATED`
        (401). This applies to every endpoint except the logical-clock endpoint."
        PRD §2.1: "`CarrierRep` is different: it is **entity-backed**. When
        `X-User-Role` is `CarrierRep`, `X-User-ID` is the `id` of the acting `Carrier`"

        Design: Corner/rbac/an_unauthenticated_request_is_refused_before_anything_else
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()

        blind_read = api_client.get_carrier(carrier["id"], NO_ROLE_HEADERS)
        validate_error(blind_read, "ERR_UNAUTHENTICATED", 401)

        wrong_everything = api_client.lock_lanes(NON_EXISTENT_UUID, NO_ROLE_HEADERS)
        validate_error(wrong_everything, "ERR_UNAUTHENTICATED", 401)
        assert wrong_everything.json()["data"]["error_id"] not in (
            "ERR_BID_EVENT_NOT_FOUND",
            "ERR_FORBIDDEN_ROLE",
        ), "priority 1 decides before the role check and before the path lookup"

        validate_error(
            api_client.get_carrier(carrier["id"], UNKNOWN_ROLE_HEADERS),
            "ERR_UNAUTHENTICATED",
            401,
        )
        validate_error(
            api_client.get_carrier(carrier["id"], NO_PRINCIPAL_HEADERS),
            "ERR_UNAUTHENTICATED",
            401,
        )
        validate_error(
            _sign_as_carrier(NON_EXISTENT_UUID, REP_WITHOUT_PRINCIPAL_HEADERS),
            "ERR_UNAUTHENTICATED",
            401,
        )

        readable = validate_success(api_client.get_carrier(carrier["id"], ANALYST))
        assert readable["id"] == carrier["id"]
        assert readable["status"] == "QUALIFIED"

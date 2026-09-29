"""Composite state builders.

The harness restarts the server before every test, so every test begins against
an empty database and each of these builders drives the public API from scratch.
They are layered: each one calls the one below it and adds a single step, so a
test can enter the pipeline at exactly the state its behaviour needs and no
later.

The canonical pipeline runs

    tournament -> hotel -> contract (DRAFT) -> block -> SUBMIT -> COUNTERSIGN
    -> team -> registration -> booking -> rooming list -> confirm
    -> close-booking -> actualization -> invoice -> ISSUE -> remit
    -> revenue distribution

because PRD §3.7 requires the window to be closed before a hotel may report:
"The governing tournament's `posture` must be `BOOKING_CLOSED` or
`RECONCILING`, or the request is rejected with
`ERR_TOURNAMENT_NOT_RECONCILING`."
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    HOUSING_MANAGER_HEADERS,
    EXCEPTION_REVIEWER_HEADERS,
    RIGHTS_HOLDER_HEADERS,
    make_hotel_rep_headers,
    make_team_manager_headers,
)
from .types import (
    DistributionAction,
    InvoiceLifecycleAction,
    NegotiationAction,
    ReviewAction,
)

Record = Dict[str, Any]

HM = HOUSING_MANAGER_HEADERS
REVIEWER = EXCEPTION_REVIEWER_HEADERS
RIGHTS = RIGHTS_HOLDER_HEADERS


# ---------------------------------------------------------------------------
# The pipeline carrier
# ---------------------------------------------------------------------------


@dataclass
class Env:
    """Everything a layered setup has built so far, plus refresh helpers."""

    client: ApiClient
    tournament: Optional[Record] = None
    hotel: Optional[Record] = None
    contract: Optional[Record] = None
    block: Optional[Record] = None
    blocks: List[Record] = field(default_factory=list)
    team: Optional[Record] = None
    registration: Optional[Record] = None
    booking: Optional[Record] = None
    bookings: List[Record] = field(default_factory=list)
    exception_request: Optional[Record] = None
    complaint: Optional[Record] = None
    invoice: Optional[Record] = None
    distribution: Optional[Record] = None

    # -- identifiers ------------------------------------------------------

    @property
    def tournament_id(self) -> str:
        return self.tournament["id"]

    @property
    def hotel_id(self) -> str:
        return self.hotel["id"]

    @property
    def contract_id(self) -> str:
        return self.contract["id"]

    @property
    def block_id(self) -> str:
        return self.block["id"]

    @property
    def team_id(self) -> str:
        return self.team["id"]

    @property
    def registration_id(self) -> str:
        return self.registration["id"]

    @property
    def booking_id(self) -> str:
        return self.booking["id"]

    @property
    def invoice_id(self) -> str:
        return self.invoice["id"]

    @property
    def distribution_id(self) -> str:
        return self.distribution["id"]

    # -- headers for the entity-backed roles (PRD §2.1) --------------------

    @property
    def hotel_headers(self) -> Dict[str, str]:
        return make_hotel_rep_headers(self.hotel_id)

    @property
    def team_headers(self) -> Dict[str, str]:
        return make_team_manager_headers(self.team_id)

    # -- re-reads ---------------------------------------------------------

    def refresh_tournament(self) -> Record:
        self.tournament = get_success_data(
            self.client.get_tournament(self.tournament_id, HM)
        )
        return self.tournament

    def refresh_contract(self) -> Record:
        self.contract = get_success_data(
            self.client.get_hotel_contract(self.contract_id, HM)
        )
        return self.contract

    def refresh_block(self, block: Optional[Record] = None) -> Record:
        target = block if block is not None else self.block
        blocks, _ = _paginated(
            self.client.list_contract_room_blocks(target["contract_id"], HM)
        )
        fresh = next(row for row in blocks if row["id"] == target["id"])
        if block is None:
            self.block = fresh
        return fresh

    def refresh_registration(self) -> Record:
        self.registration = get_success_data(
            self.client.get_team_registration(self.registration_id, HM)
        )
        return self.registration

    def refresh_booking(self, booking: Optional[Record] = None) -> Record:
        target = booking if booking is not None else self.booking
        fresh = get_success_data(self.client.get_booking(target["id"], HM))
        if booking is None:
            self.booking = fresh
        return fresh

    def refresh_exception_request(self) -> Record:
        self.exception_request = get_success_data(
            self.client.get_exception_request(self.exception_request["id"], HM)
        )
        return self.exception_request

    def refresh_complaint(self) -> Record:
        self.complaint = get_success_data(
            self.client.get_complaint(self.complaint["id"], HM)
        )
        return self.complaint

    def refresh_invoice(self) -> Record:
        self.invoice = get_success_data(
            self.client.get_rebate_invoice(self.invoice_id, HM)
        )
        return self.invoice

    def refresh_distribution(self) -> Record:
        self.distribution = get_success_data(
            self.client.get_revenue_distribution(self.distribution_id, HM)
        )
        return self.distribution


def _paginated(response):
    """Local import shim so ``validate_paginated`` stays one call away."""
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Layer 0: the clock
# ---------------------------------------------------------------------------


def set_clock(client: ApiClient, to_iso8601: str) -> Record:
    """Move the logical clock (PRD §2.5)."""
    return get_success_data(client.set_clock(f.clock_payload(to_iso8601), HM))


# ---------------------------------------------------------------------------
# Layer 1: root entities
# ---------------------------------------------------------------------------


def create_tournament(client: ApiClient, **overrides: Any) -> Record:
    return get_success_data(client.create_tournament(f.tournament_payload(**overrides), HM))


def create_hotel(client: ApiClient, **overrides: Any) -> Record:
    return get_success_data(client.create_hotel(f.hotel_payload(**overrides), HM))


def create_team(client: ApiClient, **overrides: Any) -> Record:
    return get_success_data(client.create_team(f.team_payload(**overrides), HM))


def create_local_team(client: ApiClient, **overrides: Any) -> Record:
    return get_success_data(client.create_team(f.local_team_payload(**overrides), HM))


# ---------------------------------------------------------------------------
# Layer 2: a DRAFT contract with one block
# ---------------------------------------------------------------------------


def draft_contract_env(
    client: ApiClient,
    tournament_overrides: Optional[Dict[str, Any]] = None,
    hotel_overrides: Optional[Dict[str, Any]] = None,
    contract_overrides: Optional[Dict[str, Any]] = None,
) -> Env:
    """A tournament, a hotel and a ``DRAFT`` contract between them."""
    env = Env(client=client)
    env.tournament = create_tournament(client, **(tournament_overrides or {}))
    env.hotel = create_hotel(client, **(hotel_overrides or {}))
    env.contract = get_success_data(
        client.create_hotel_contract(
            f.hotel_contract_payload(
                env.tournament_id, env.hotel_id, **(contract_overrides or {})
            ),
            HM,
        )
    )
    return env


def add_block(env: Env, **overrides: Any) -> Record:
    """Hold another room block under the environment's contract."""
    block = get_success_data(
        env.client.create_room_block(
            f.room_block_payload(env.contract_id, **overrides), HM
        )
    )
    env.blocks.append(block)
    env.block = block
    return block


def negotiating_contract_env(
    client: ApiClient,
    block_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Env:
    """A contract at ``NEGOTIATING`` with one block held under it.

    PRD §3.2 requires the block first: ``SUBMIT`` needs at least one room block
    on the contract.
    """
    env = draft_contract_env(client, **kwargs)
    add_block(env, **(block_overrides or {}))
    env.contract = get_success_data(
        client.negotiate_contract(
            env.contract_id, f.negotiation_payload(NegotiationAction.SUBMIT.value), HM
        )
    )
    return env


def executed_contract_env(client: ApiClient, **kwargs: Any) -> Env:
    """A contract countersigned by its own hotel, so bookings are admissible."""
    env = negotiating_contract_env(client, **kwargs)
    env.contract = get_success_data(
        client.negotiate_contract(
            env.contract_id,
            f.negotiation_payload(NegotiationAction.COUNTERSIGN.value),
            env.hotel_headers,
        )
    )
    return env


# ---------------------------------------------------------------------------
# Layer 3: a registered team
# ---------------------------------------------------------------------------


def add_team(env: Env, **overrides: Any) -> Record:
    env.team = create_team(env.client, **overrides)
    return env.team


def add_registration(env: Env, team: Optional[Record] = None, **overrides: Any) -> Record:
    """Register a team for the environment's tournament."""
    target = team if team is not None else env.team
    registration = get_success_data(
        env.client.create_team_registration(
            f.team_registration_payload(env.tournament_id, target["id"], **overrides),
            HM,
        )
    )
    if team is None:
        env.registration = registration
    return registration


def registered_team_env(
    client: ApiClient,
    team_overrides: Optional[Dict[str, Any]] = None,
    registration_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Env:
    """An executed contract plus one team registered for the event."""
    env = executed_contract_env(client, **kwargs)
    add_team(env, **(team_overrides or {}))
    add_registration(env, **(registration_overrides or {}))
    return env


# ---------------------------------------------------------------------------
# Layer 4: bookings
# ---------------------------------------------------------------------------


def add_booking(
    env: Env,
    registration: Optional[Record] = None,
    block: Optional[Record] = None,
    **overrides: Any,
) -> Record:
    """Book rooms, guarding on the registration's current ``version``.

    PRD §2.8 requires the guard, so the current version is read back rather than
    assumed.
    """
    reg = registration if registration is not None else env.refresh_registration()
    blk = block if block is not None else env.block
    booking = get_success_data(
        env.client.create_booking(
            f.booking_payload(reg["id"], blk["id"], reg["version"], **overrides), HM
        )
    )
    env.bookings.append(booking)
    if registration is None and block is None:
        env.booking = booking
    return booking


def draft_booking_env(
    client: ApiClient, booking_overrides: Optional[Dict[str, Any]] = None, **kwargs: Any
) -> Env:
    """A booking sitting at ``DRAFT``, with no rooming list yet."""
    env = registered_team_env(client, **kwargs)
    add_booking(env, **(booking_overrides or {}))
    return env


def submit_rooming_list(
    env: Env, booking: Optional[Record] = None, **overrides: Any
) -> Record:
    """Submit a rooming list sized to the booking's ``rooms_requested``."""
    target = booking if booking is not None else env.booking
    if "entries" not in overrides and "rooms" not in overrides:
        overrides["rooms"] = target["rooms_requested"]
    return get_success_data(
        env.client.submit_rooming_list(
            target["id"], f.rooming_list_payload(**overrides), HM
        )
    )


def rooming_list_env(client: ApiClient, **kwargs: Any) -> Env:
    """A booking at ``ROOMING_LIST_SUBMITTED``."""
    env = draft_booking_env(client, **kwargs)
    env.booking = submit_rooming_list(env)
    return env


def confirm_booking(env: Env, booking: Optional[Record] = None) -> Record:
    target = booking if booking is not None else env.booking
    return get_success_data(env.client.confirm_booking(target["id"], HM))


def confirmed_booking_env(client: ApiClient, **kwargs: Any) -> Env:
    """A booking at ``CONFIRMED``, so the block now counts its rooms."""
    env = rooming_list_env(client, **kwargs)
    env.booking = confirm_booking(env)
    return env


# ---------------------------------------------------------------------------
# Layer 5: closing the window and actualizing
# ---------------------------------------------------------------------------


def close_booking_window(env: Env) -> Record:
    env.tournament = get_success_data(env.client.close_booking(env.tournament_id, HM))
    return env.tournament


def actualize(
    env: Env, reported_room_nights: int, booking: Optional[Record] = None, **overrides: Any
) -> Record:
    """File one hotel actualization report against a booking."""
    target = booking if booking is not None else env.booking
    return get_success_data(
        env.client.create_actualization(
            target["id"],
            f.actualization_payload(reported_room_nights, **overrides),
            env.hotel_headers,
        )
    )


def closed_window_env(client: ApiClient, **kwargs: Any) -> Env:
    """A confirmed booking on an event whose housing window has been closed."""
    env = confirmed_booking_env(client, **kwargs)
    close_booking_window(env)
    return env


def checked_out_booking_env(
    client: ApiClient, reported_room_nights: int = 12, **kwargs: Any
) -> Env:
    """A booking at ``CHECKED_OUT`` with its rebate ``ACCRUED``."""
    env = closed_window_env(client, **kwargs)
    actualize(env, reported_room_nights)
    env.refresh_booking()
    return env


# ---------------------------------------------------------------------------
# Layer 6: invoicing and collection
# ---------------------------------------------------------------------------


def create_invoice(env: Env, **overrides: Any) -> Record:
    env.invoice = get_success_data(
        env.client.create_rebate_invoice(
            f.rebate_invoice_payload(env.contract_id, **overrides), HM
        )
    )
    return env.invoice


def invoiced_env(client: ApiClient, **kwargs: Any) -> Env:
    """A ``DRAFT`` rebate invoice covering one checked-out booking."""
    env = checked_out_booking_env(client, **kwargs)
    create_invoice(env)
    return env


def issue_invoice(env: Env) -> Record:
    env.invoice = get_success_data(
        env.client.invoice_lifecycle(
            env.invoice_id, f.lifecycle_payload(InvoiceLifecycleAction.ISSUE.value), HM
        )
    )
    return env.invoice


def issued_invoice_env(client: ApiClient, **kwargs: Any) -> Env:
    """An ``ISSUED`` invoice; the event has tipped into ``RECONCILING``."""
    env = invoiced_env(client, **kwargs)
    issue_invoice(env)
    return env


def remit(env: Env, amount_cents: int) -> Record:
    env.invoice = get_success_data(
        env.client.remit_invoice(
            env.invoice_id, f.remit_payload(amount_cents), env.hotel_headers
        )
    )
    return env.invoice


def paid_invoice_env(client: ApiClient, **kwargs: Any) -> Env:
    """A fully cleared invoice, which fires the four-link remit chain."""
    env = issued_invoice_env(client, **kwargs)
    remit(env, env.invoice["outstanding_cents"])
    return env


def partially_paid_invoice_env(
    client: ApiClient, amount_cents: Optional[int] = None, **kwargs: Any
) -> Env:
    """An invoice at ``PARTIALLY_PAID`` with some cents still outstanding."""
    env = issued_invoice_env(client, **kwargs)
    outstanding = env.invoice["outstanding_cents"]
    remit(env, amount_cents if amount_cents is not None else outstanding - 1)
    return env


# ---------------------------------------------------------------------------
# Layer 7: revenue distribution
# ---------------------------------------------------------------------------


def create_distribution(env: Env, **overrides: Any) -> Record:
    """Split collected revenue, guarding on the invoice's current ``version``."""
    invoice = env.refresh_invoice()
    env.distribution = get_success_data(
        env.client.create_revenue_distribution(
            f.revenue_distribution_payload(
                env.tournament_id, invoice["id"], invoice["version"], **overrides
            ),
            HM,
        )
    )
    return env.distribution


def calculated_distribution_env(client: ApiClient, **kwargs: Any) -> Env:
    """A distribution at ``CALCULATED`` over a fully collected invoice."""
    env = paid_invoice_env(client, **kwargs)
    create_distribution(env)
    return env


def approve_distribution(env: Env, headers: Optional[Dict[str, str]] = None) -> Record:
    env.distribution = get_success_data(
        env.client.advance_distribution(
            env.distribution_id,
            f.advance_payload(DistributionAction.APPROVE.value),
            headers if headers is not None else RIGHTS,
        )
    )
    return env.distribution


def approved_distribution_env(client: ApiClient, **kwargs: Any) -> Env:
    env = calculated_distribution_env(client, **kwargs)
    approve_distribution(env)
    return env


def pay_distribution(env: Env) -> Record:
    env.distribution = get_success_data(
        env.client.advance_distribution(
            env.distribution_id, f.advance_payload(DistributionAction.PAY.value), HM
        )
    )
    return env.distribution


# ---------------------------------------------------------------------------
# Exception requests
# ---------------------------------------------------------------------------


def add_exception_request(
    env: Env, registration: Optional[Record] = None, **overrides: Any
) -> Record:
    reg = registration if registration is not None else env.registration
    request = get_success_data(
        env.client.create_exception_request(
            f.exception_request_payload(reg["id"], **overrides), HM
        )
    )
    if registration is None:
        env.exception_request = request
    return request


def review_exception(
    env: Env,
    action: str,
    request: Optional[Record] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Record:
    target = request if request is not None else env.exception_request
    result = get_success_data(
        env.client.review_exception_request(
            target["id"],
            f.review_payload(action, **overrides),
            headers if headers is not None else REVIEWER,
        )
    )
    if request is None:
        env.exception_request = result
    return result


def exception_request_env(client: ApiClient, **kwargs: Any) -> Env:
    """A registered team with one exception request at ``SUBMITTED``."""
    env = registered_team_env(client, **kwargs)
    add_exception_request(env)
    return env


def under_review_exception_env(client: ApiClient, **kwargs: Any) -> Env:
    """An exception request a reviewer has picked up (``UNDER_REVIEW``)."""
    env = exception_request_env(client, **kwargs)
    review_exception(env, ReviewAction.START_REVIEW.value)
    return env


def denied_exception_env(client: ApiClient, **kwargs: Any) -> Env:
    """An exception request at ``DENIED``, one appeal still unspent."""
    env = under_review_exception_env(client, **kwargs)
    review_exception(
        env, ReviewAction.DENY.value, decision_note="insufficient documentation"
    )
    return env


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------


def add_complaint(env: Env, **overrides: Any) -> Record:
    env.complaint = get_success_data(
        env.client.create_complaint(f.complaint_payload(env.tournament_id, **overrides), HM)
    )
    return env.complaint


def triage_complaint(env: Env, route: str, headers: Optional[Dict[str, str]] = None) -> Record:
    env.complaint = get_success_data(
        env.client.triage_complaint(
            env.complaint["id"],
            f.triage_payload(route),
            headers if headers is not None else HM,
        )
    )
    return env.complaint


def adjudicate_complaint(
    env: Env,
    outcome: str,
    remedy_type: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Record:
    env.complaint = get_success_data(
        env.client.adjudicate_complaint(
            env.complaint["id"],
            f.adjudicate_payload(outcome, remedy_type, **overrides),
            headers if headers is not None else RIGHTS,
        )
    )
    return env.complaint

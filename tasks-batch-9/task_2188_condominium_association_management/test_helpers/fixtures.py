"""Composite state builders and pytest fixtures.

The server is restarted with an empty store before every test, so every fixture
builds its world from scratch through the public API.  Builders are plain
functions first (so a test can vary any parameter) with pytest fixtures layered
on top for the shapes that recur.

Naming convention for actors inside a built association:

* ``"d1"``  -- seated PRESIDENT
* ``"d2"``  -- seated DIRECTOR
* ``"tr"``  -- seated TREASURER
* ``"oa"``, ``"ob"``, ... -- unseated owners of record

Unit labels are used as the keys of :attr:`AssociationContext.units`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import ApiClient, api_client
from .constants import CLOCK_EPOCH
from .factories import (
    association_payload,
    board_meeting_payload,
    board_vote_payload,
    budget_payload,
    charge_payload,
    common_element_payload,
    insurance_claim_payload,
    owner_ballot_payload,
    owner_payload,
    resale_certificate_payload,
    special_assessment_payload,
    unit_payload,
    vendor_contract_payload,
    violation_case_payload,
    work_order_payload,
)
from .test_users import (
    ADJUSTER_HEADERS,
    ATTORNEY_HEADERS,
    MANAGER_HEADERS,
    TITLE_AGENT_HEADERS,
    make_director_headers,
    make_owner_headers,
    make_treasurer_headers,
)


# ======================================================================
# Context object
# ======================================================================
@dataclass
class AssociationContext:
    """Everything a test needs to keep addressing a built association."""

    api: ApiClient
    association_id: str
    owners: dict[str, str] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    elements: dict[str, str] = field(default_factory=dict)
    contracts: dict[str, str] = field(default_factory=dict)
    meetings: dict[str, str] = field(default_factory=dict)

    # -- actor headers -------------------------------------------------
    def director(self, label: str = "d1") -> dict[str, str]:
        return make_director_headers(self.owners[label])

    def treasurer(self, label: str = "tr") -> dict[str, str]:
        return make_treasurer_headers(self.owners[label])

    def owner(self, label: str) -> dict[str, str]:
        return make_owner_headers(self.owners[label])

    # -- read-through helpers -----------------------------------------
    def association(self) -> dict[str, Any]:
        return get_success_data(self.api.get_association(self.association_id, MANAGER_HEADERS))

    def association_version(self) -> int:
        return int(self.association()["version"])

    def unit(self, label: str) -> dict[str, Any]:
        return get_success_data(self.api.get_unit(self.units[label], MANAGER_HEADERS))

    def unit_version(self, label: str) -> int:
        return int(self.unit(label)["version"])

    def contract_version(self, label: str = "ct1") -> int:
        rows, _ = validate_paginated(
            self.api.list_vendor_contracts(
                MANAGER_HEADERS, params={"association_id": self.association_id, "limit": 100}
            )
        )
        match = next(r for r in rows if r["id"] == self.contracts[label])
        return int(match["version"])

    def ledger(self, label: str) -> list[dict[str, Any]]:
        rows, _ = validate_paginated(
            self.api.list_ledger_entries(
                MANAGER_HEADERS, params={"unit_id": self.units[label], "limit": 100}
            )
        )
        return list(rows)


# ======================================================================
# Tier 0 -- clock
# ======================================================================
def set_clock(api: ApiClient, current_utc: str) -> None:
    """Move the logical clock; every deadline rule measures against it."""
    get_success_data(api.set_clock(current_utc, MANAGER_HEADERS))


# ======================================================================
# Tier 1 -- association, roster, state progression
# ======================================================================
def create_association(api: ApiClient, **overrides: Any) -> AssociationContext:
    """Register an association at the clock epoch and return its context."""
    set_clock(api, CLOCK_EPOCH)
    data = get_success_data(
        api.create_association(association_payload(**overrides), MANAGER_HEADERS)
    )
    return AssociationContext(api=api, association_id=data["id"])


def patch_association(ctx: AssociationContext, **fields: Any) -> dict[str, Any]:
    """Adjust by-law tunables or cash on hand."""
    return get_success_data(
        ctx.api.update_association(ctx.association_id, dict(fields), MANAGER_HEADERS)
    )


def add_owner(
    ctx: AssociationContext, label: str, **overrides: Any
) -> str:
    """Create a unit owner of record and remember it under ``label``."""
    data = get_success_data(
        ctx.api.create_owner(
            ctx.association_id, owner_payload(**overrides), MANAGER_HEADERS
        )
    )
    ctx.owners[label] = data["id"]
    return data["id"]


def add_unit(
    ctx: AssociationContext,
    label: str,
    owner_label: str,
    interest_bp: int,
    heated_sqft: int = 1000,
    **overrides: Any,
) -> str:
    """Add a unit with its undivided interest and heated area."""
    payload = unit_payload(
        ctx.owners[owner_label],
        unit_label=label,
        interest_bp=interest_bp,
        heated_sqft=heated_sqft,
        **overrides,
    )
    data = get_success_data(
        ctx.api.create_unit(ctx.association_id, payload, MANAGER_HEADERS)
    )
    ctx.units[label] = data["id"]
    return data["id"]


def build_board(
    ctx: AssociationContext,
    *,
    unit_interests: Sequence[int] = (3400, 3300, 3300),
    heated_sqfts: Sequence[int] = (1400, 1300, 1300),
) -> AssociationContext:
    """Seat a president, a director and a treasurer, each holding one unit.

    Three seated members is the default board_quorum_seats, so the resulting
    board can convene and reach quorum on its own.
    """
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "d2", full_name="Elliot Shaw", board_role="DIRECTOR", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    for label, owner_label, interest, sqft in zip(
        ("101", "102", "103"), ("d1", "d2", "tr"), unit_interests, heated_sqfts
    ):
        add_unit(ctx, label, owner_label, interest, sqft)
    return ctx


def build_two_owner_board(
    ctx: AssociationContext,
    *,
    interest_a: int = 6000,
    interest_b: int = 4000,
    sqft_a: int = 1500,
    sqft_b: int = 1000,
) -> AssociationContext:
    """Seat a president and a treasurer, plus two unseated owners holding units.

    The two owner-held units carry the whole undivided interest, so owner
    balloting weights are exactly ``interest_a`` and ``interest_b``.
    """
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    add_owner(ctx, "oa", full_name="Owner A")
    add_owner(ctx, "ob", full_name="Owner B")
    add_unit(ctx, "A", "oa", interest_a, sqft_a)
    add_unit(ctx, "B", "ob", interest_b, sqft_b)
    return ctx


# ======================================================================
# Tier 2 -- meetings, elements, contracts (entity hierarchy)
# ======================================================================
def schedule_meeting(
    ctx: AssociationContext,
    label: str,
    agenda_kinds: Sequence[str],
    scheduled_start: str,
    scheduled_end: str,
) -> str:
    """Schedule a board meeting and remember it under ``label``."""
    data = get_success_data(
        ctx.api.create_board_meeting(
            ctx.association_id,
            board_meeting_payload(
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
                agenda_kinds=list(agenda_kinds),
            ),
            MANAGER_HEADERS,
        )
    )
    ctx.meetings[label] = data["id"]
    return data["id"]


def notice_meeting(ctx: AssociationContext, label: str) -> dict[str, Any]:
    return get_success_data(
        ctx.api.send_meeting_notice(ctx.meetings[label], MANAGER_HEADERS)
    )


def convene(
    ctx: AssociationContext,
    label: str,
    attending: Iterable[str] = ("d1", "d2", "tr"),
) -> dict[str, Any]:
    """Convene a meeting, recording the seated directors present for quorum."""
    return get_success_data(
        ctx.api.convene_meeting(
            ctx.meetings[label],
            {"attending_owner_ids": [ctx.owners[a] for a in attending]},
            MANAGER_HEADERS,
        )
    )


def open_meeting(
    ctx: AssociationContext,
    label: str,
    agenda_kinds: Sequence[str],
    scheduled_start: str,
    scheduled_end: str,
    attending: Iterable[str] = ("d1", "d2", "tr"),
) -> str:
    """Schedule, notice, advance the clock to the start, and convene."""
    meeting_id = schedule_meeting(
        ctx, label, agenda_kinds, scheduled_start, scheduled_end
    )
    notice_meeting(ctx, label)
    set_clock(ctx.api, scheduled_start)
    convene(ctx, label, attending)
    return meeting_id


def add_element(
    ctx: AssociationContext, label: str, **overrides: Any
) -> str:
    """Register a common element / reserve component."""
    data = get_success_data(
        ctx.api.create_common_element(
            ctx.association_id, common_element_payload(**overrides), MANAGER_HEADERS
        )
    )
    ctx.elements[label] = data["id"]
    return data["id"]


def add_contract(
    ctx: AssociationContext, label: str, element_label: str, **overrides: Any
) -> str:
    """Draft a vendor contract covering one common element."""
    data = get_success_data(
        ctx.api.create_vendor_contract(
            ctx.association_id,
            vendor_contract_payload(ctx.elements[element_label], **overrides),
            MANAGER_HEADERS,
        )
    )
    ctx.contracts[label] = data["id"]
    return data["id"]


def board_vote_yes(
    ctx: AssociationContext,
    subject_type: str,
    subject_id: str,
    meeting_label: str,
    voters: Sequence[tuple[str, str]] = (("d1", "101"), ("d2", "102"), ("tr", "103")),
) -> None:
    """Cast a YES board vote from each named seated director.

    A board vote carries ``meeting_id`` and no ``unit_id``: exactly one of the
    two discriminators may be supplied, and the one that is present is what
    makes the vote a board vote rather than a weighted owner ballot.  The unit
    label in each ``voters`` entry therefore only identifies the seat holder.
    """
    for owner_label, _unit_label in voters:
        headers = (
            ctx.treasurer(owner_label)
            if owner_label == "tr"
            else ctx.director(owner_label)
        )
        get_success_data(
            ctx.api.cast_vote(
                board_vote_payload(
                    ctx.association_id,
                    subject_type,
                    subject_id,
                    ctx.owners[owner_label],
                    ctx.meetings[meeting_label],
                ),
                headers,
            )
        )


def award_and_activate_contract(
    ctx: AssociationContext,
    contract_label: str,
    meeting_label: str,
    voters: Sequence[tuple[str, str]] = (("d1", "101"), ("d2", "102"), ("tr", "103")),
) -> dict[str, Any]:
    """Submit, board-award and activate a drafted contract.

    Approval pins the element version the award was based on, so callers that
    later revise the element see the pin go stale.
    """
    contract_id = ctx.contracts[contract_label]
    get_success_data(ctx.api.submit_contract(contract_id, MANAGER_HEADERS))
    board_vote_yes(ctx, "VENDOR_CONTRACT", contract_id, meeting_label, voters)
    get_success_data(ctx.api.approve_contract(contract_id, ctx.director("d1")))
    return get_success_data(ctx.api.activate_contract(contract_id, MANAGER_HEADERS))


def add_work_order(
    ctx: AssociationContext,
    contract_label: str,
    element_label: str,
    **overrides: Any,
) -> dict[str, Any]:
    """Schedule maintenance work, encumbering the contract cap.

    ``expected_contract_version`` is read fresh, because every accepted work
    order bumps the contract's version.
    """
    payload = work_order_payload(
        ctx.contracts[contract_label],
        ctx.elements[element_label],
        ctx.contract_version(contract_label),
        **overrides,
    )
    return get_success_data(ctx.api.create_work_order(payload, MANAGER_HEADERS))


# ======================================================================
# Tier 3 -- full lifecycle shortcuts
# ======================================================================
def draft_budget(
    ctx: AssociationContext,
    *,
    fiscal_year: int = 2026,
    operating_total_cents: int = 12_000_000,
    reserve_contribution_cents: int = 1_200_000,
    **overrides: Any,
) -> dict[str, Any]:
    """Draft a budget for a fiscal year using a freshly read association version."""
    payload = budget_payload(
        ctx.association_version(),
        fiscal_year=fiscal_year,
        operating_total_cents=operating_total_cents,
        reserve_contribution_cents=reserve_contribution_cents,
        **overrides,
    )
    return get_success_data(
        ctx.api.create_budget(ctx.association_id, payload, MANAGER_HEADERS)
    )


def adopt_budget(
    ctx: AssociationContext,
    *,
    fiscal_year: int = 2026,
    operating_total_cents: int = 12_000_000,
    reserve_contribution_cents: int = 1_200_000,
    meeting_label: str = "mtg_budget",
    notice_at: str = CLOCK_EPOCH,
    meeting_start: str = "2026-09-10T18:00:00Z",
    meeting_end: str = "2026-09-10T21:00:00Z",
    attending: Iterable[str] = ("d1", "d2", "tr"),
    veto_ballots: Sequence[tuple[str, str, str]] = (),
) -> dict[str, Any]:
    """Walk a budget DRAFT -> PROPOSED -> NOTICED -> ADOPTED.

    ``veto_ballots`` is a sequence of ``(owner_label, unit_label, choice)``
    owner ballots cast against ratification before the tally; with none cast the
    no-weight is zero and the budget is adopted.
    """
    budget = draft_budget(
        ctx,
        fiscal_year=fiscal_year,
        operating_total_cents=operating_total_cents,
        reserve_contribution_cents=reserve_contribution_cents,
    )
    budget_id = budget["id"]
    meeting_id = schedule_meeting(
        ctx, meeting_label, ["BUDGET_RATIFICATION"], meeting_start, meeting_end
    )
    get_success_data(
        ctx.api.propose_budget(
            budget_id, MANAGER_HEADERS, payload={"ratification_meeting_id": meeting_id}
        )
    )
    set_clock(ctx.api, notice_at)
    get_success_data(ctx.api.send_budget_notice(budget_id, MANAGER_HEADERS))
    for owner_label, unit_label, choice in veto_ballots:
        get_success_data(
            ctx.api.cast_vote(
                owner_ballot_payload(
                    ctx.association_id,
                    "BUDGET",
                    budget_id,
                    ctx.owners[owner_label],
                    ctx.units[unit_label],
                    choice=choice,
                ),
                ctx.owner(owner_label),
            )
        )
    # Mailing the budget notice promotes the ratification meeting to NOTICED,
    # so the meeting needs no separate notice before it can be convened.
    set_clock(ctx.api, meeting_start)
    convene(ctx, meeting_label, attending)
    return get_success_data(ctx.api.ratify_budget(budget_id, ctx.director("d1")))


def open_special_assessment(
    ctx: AssociationContext,
    *,
    total_amount_cents: int = 1_000_000,
    installment_count: int = 2,
    purpose: str = "Reserve top-up",
    funding_claim_id: str | None = None,
) -> dict[str, Any]:
    """Draft a special assessment and open owner balloting on it."""
    payload = special_assessment_payload(
        ctx.association_version(),
        purpose=purpose,
        total_amount_cents=total_amount_cents,
        installment_count=installment_count,
    )
    if funding_claim_id is not None:
        payload["funding_claim_id"] = funding_claim_id
    assessment = get_success_data(
        ctx.api.create_special_assessment(ctx.association_id, payload, ctx.treasurer())
    )
    # Return the ballot-opening response, not the DRAFT creation response, so
    # callers observe approval_status BALLOTING and ballot_opened_at as stamped.
    return get_success_data(ctx.api.open_ballot(assessment["id"], ctx.director("d1")))


def cast_owner_ballots(
    ctx: AssociationContext,
    subject_type: str,
    subject_id: str,
    ballots: Sequence[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    """Cast weighted owner ballots as ``(owner_label, unit_label, choice)``."""
    cast: list[dict[str, Any]] = []
    for owner_label, unit_label, choice in ballots:
        cast.append(
            get_success_data(
                ctx.api.cast_vote(
                    owner_ballot_payload(
                        ctx.association_id,
                        subject_type,
                        subject_id,
                        ctx.owners[owner_label],
                        ctx.units[unit_label],
                        choice=choice,
                    ),
                    ctx.owner(owner_label),
                )
            )
        )
    return cast


def approve_special_assessment(
    ctx: AssociationContext,
    *,
    total_amount_cents: int = 1_000_000,
    installment_count: int = 2,
    purpose: str = "Reserve top-up",
    funding_claim_id: str | None = None,
    ballots: Sequence[tuple[str, str, str]] = (("oa", "A", "YES"), ("ob", "B", "YES")),
) -> dict[str, Any]:
    """Draft, ballot and tally a special assessment through to APPROVED."""
    assessment = open_special_assessment(
        ctx,
        total_amount_cents=total_amount_cents,
        installment_count=installment_count,
        purpose=purpose,
        funding_claim_id=funding_claim_id,
    )
    cast_owner_ballots(ctx, "SPECIAL_ASSESSMENT", assessment["id"], ballots)
    return get_success_data(ctx.api.close_ballot(assessment["id"], ctx.director("d1")))


def report_claim(
    ctx: AssociationContext,
    unit_label: str,
    element_label: str,
    **overrides: Any,
) -> dict[str, Any]:
    """Report a loss under the master policy."""
    payload = insurance_claim_payload(
        ctx.association_id,
        ctx.units[unit_label],
        ctx.elements[element_label],
        **overrides,
    )
    return get_success_data(ctx.api.create_insurance_claim(payload, MANAGER_HEADERS))


def adjust_claim(
    ctx: AssociationContext,
    claim_id: str,
    responsibility: str = "ASSOCIATION",
) -> dict[str, Any]:
    """Take the claim under review and delineate responsibility."""
    get_success_data(ctx.api.assign_adjuster(claim_id, ADJUSTER_HEADERS))
    return get_success_data(
        ctx.api.adjust_claim(claim_id, {"responsibility": responsibility}, ADJUSTER_HEADERS)
    )


def tender_claim(ctx: AssociationContext, claim_id: str) -> dict[str, Any]:
    """Advance a construction-defect matter's litigation dimension to TENDERED."""
    return get_success_data(
        ctx.api.set_litigation_stage(claim_id, {"stage": "TENDERED"}, ATTORNEY_HEADERS)
    )


def request_certificate(
    ctx: AssociationContext,
    unit_label: str,
    *,
    closing_date: str = "2026-09-15T00:00:00Z",
    payoff_basis: str = "LEDGER_BALANCE",
    requesting_agent_id: str = "TA-0001",
) -> dict[str, Any]:
    """Request a resale certificate for a unit, pinned on its current version."""
    payload = resale_certificate_payload(
        requesting_agent_id,
        ctx.unit_version(unit_label),
        closing_date=closing_date,
        payoff_basis=payoff_basis,
    )
    return get_success_data(
        ctx.api.request_resale_certificate(
            ctx.units[unit_label], payload, TITLE_AGENT_HEADERS
        )
    )


def issue_certificate(
    ctx: AssociationContext,
    unit_label: str,
    *,
    closing_date: str = "2026-09-15T00:00:00Z",
    payoff_basis: str = "LEDGER_BALANCE",
    requesting_agent_id: str = "TA-0001",
) -> dict[str, Any]:
    """Request then issue a certificate: fee posts, payoff computes, snapshot pins."""
    certificate = request_certificate(
        ctx,
        unit_label,
        closing_date=closing_date,
        payoff_basis=payoff_basis,
        requesting_agent_id=requesting_agent_id,
    )
    return get_success_data(
        ctx.api.issue_resale_certificate(certificate["id"], MANAGER_HEADERS)
    )


def open_violation_case(
    ctx: AssociationContext,
    unit_label: str,
    *,
    rule_code: str = "PARKING",
    reporter_label: str = "tr",
    **overrides: Any,
) -> dict[str, Any]:
    """Open a rules-enforcement case against a unit."""
    payload = violation_case_payload(
        ctx.association_id,
        ctx.units[unit_label],
        ctx.owners[reporter_label],
        rule_code=rule_code,
        **overrides,
    )
    return get_success_data(ctx.api.create_violation_case(payload, MANAGER_HEADERS))


def notice_violation_case(
    ctx: AssociationContext,
    unit_label: str,
    *,
    rule_code: str = "PARKING",
    reporter_label: str = "tr",
    **overrides: Any,
) -> dict[str, Any]:
    """Open a case and mail its notice, starting the cure period."""
    case = open_violation_case(
        ctx, unit_label, rule_code=rule_code, reporter_label=reporter_label, **overrides
    )
    return get_success_data(ctx.api.send_case_notice(case["id"], MANAGER_HEADERS))


def docket_hearing(
    ctx: AssociationContext,
    case_id: str,
    meeting_label: str,
    slot_start: str,
    decider_label: str = "d1",
) -> dict[str, Any]:
    """Docket a case into a half-open 30-minute hearing slot."""
    return get_success_data(
        ctx.api.schedule_hearing(
            case_id,
            {
                "hearing_meeting_id": ctx.meetings[meeting_label],
                "hearing_slot_start": slot_start,
            },
            ctx.director(decider_label),
        )
    )


# ======================================================================
# Tier 4 -- accumulation and threshold targeting
# ======================================================================
def post_charge(
    ctx: AssociationContext,
    unit_label: str,
    *,
    entry_type: str = "COLLECTION_COST",
    amount_cents: int = 8_000,
    due_on: str = "2026-04-01T00:00:00Z",
    effective_period: str = "2026-04",
    memo: str = "Collection cost",
) -> dict[str, Any]:
    """Post a manual charge to a unit ledger."""
    return get_success_data(
        ctx.api.create_charge(
            ctx.units[unit_label],
            charge_payload(
                entry_type=entry_type,
                amount_cents=amount_cents,
                due_on=due_on,
                effective_period=effective_period,
                memo=memo,
            ),
            ctx.treasurer(),
        )
    )


def age_unit_into_stage(
    ctx: AssociationContext,
    unit_label: str,
    *,
    amount_cents: int,
    due_on: str,
    now: str,
) -> dict[str, Any]:
    """Post an aged charge and move the clock, driving the delinquency ladder.

    The ladder measures the age of the oldest unpaid charge against the logical
    clock, so a charge dated in the past plus a clock advance is enough to reach
    any stage without inventing an escalation endpoint.
    """
    post_charge(
        ctx,
        unit_label,
        amount_cents=amount_cents,
        due_on=due_on,
        effective_period=due_on[:7],
    )
    set_clock(ctx.api, now)
    return ctx.unit(unit_label)


# ======================================================================
# Tier 5 -- finalization / terminal states
# ======================================================================
def complete_and_invoice(
    ctx: AssociationContext,
    work_order_id: str,
    *,
    start_at: str,
    complete_at: str,
    final_cost_cents: int,
    resets_component: bool = False,
) -> dict[str, Any]:
    """Start, complete and invoice a scheduled order, releasing its encumbrance."""
    set_clock(ctx.api, start_at)
    get_success_data(ctx.api.start_work_order(work_order_id, MANAGER_HEADERS))
    set_clock(ctx.api, complete_at)
    get_success_data(
        ctx.api.complete_work_order(
            work_order_id, MANAGER_HEADERS, payload={"resets_component": resets_component}
        )
    )
    return get_success_data(
        ctx.api.invoice_work_order(
            work_order_id, {"final_cost_cents": final_cost_cents}, MANAGER_HEADERS
        )
    )


# ======================================================================
# pytest fixtures
# ======================================================================
@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def manager_headers() -> dict[str, str]:
    return MANAGER_HEADERS


@pytest.fixture
def adjuster_headers() -> dict[str, str]:
    return ADJUSTER_HEADERS


@pytest.fixture
def attorney_headers() -> dict[str, str]:
    return ATTORNEY_HEADERS


@pytest.fixture
def title_agent_headers() -> dict[str, str]:
    return TITLE_AGENT_HEADERS


@pytest.fixture
def bare_association(api: ApiClient) -> AssociationContext:
    """An association at the clock epoch with no roster yet."""
    return create_association(api)


@pytest.fixture
def board_association(api: ApiClient) -> AssociationContext:
    """Three seated board members, each holding one unit (3400/3300/3300 bp)."""
    return build_board(create_association(api))


@pytest.fixture
def two_owner_association(api: ApiClient) -> AssociationContext:
    """A seated president and treasurer plus owners A (6000 bp) and B (4000 bp)."""
    return build_two_owner_board(create_association(api))


@pytest.fixture
def roofed_board_association(api: ApiClient) -> AssociationContext:
    """A quorum-capable board plus one ROOF common element."""
    ctx = build_board(create_association(api))
    add_element(ctx, "el1", name="Main Roof Membrane", element_class="ROOF")
    return ctx


@pytest.fixture
def active_contract_association(api: ApiClient) -> AssociationContext:
    """A ROOF element with an ACTIVE vendor contract awarded by the board."""
    ctx = build_board(create_association(api))
    patch_association(ctx, operating_cash_cents=3_000_000)
    add_element(ctx, "el1", name="Main Roof Membrane", element_class="ROOF")
    add_contract(ctx, "ct1", "el1", contract_cap_cents=5_000_000)
    open_meeting(
        ctx,
        "mtg_ca",
        ["CONTRACT_AWARD"],
        "2026-09-10T18:00:00Z",
        "2026-09-10T21:00:00Z",
    )
    award_and_activate_contract(ctx, "ct1", "mtg_ca")
    return ctx

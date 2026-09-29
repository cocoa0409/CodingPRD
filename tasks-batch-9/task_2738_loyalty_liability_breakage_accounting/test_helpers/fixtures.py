"""
Composite setup builders.

Every function here drives the real API through the same endpoints a client would
use, and every call is checked with ``get_success_data`` so a broken precondition
surfaces as a setup error naming the endpoint that refused, not as a mysterious
assertion twenty lines later.

The builders are layered: a programme, then a cohort, then a member and a period,
then a lot, then a redemption or an estimate. Higher layers call lower ones, so a
test asks for exactly the depth of state it needs.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories
from test_helpers.constants import (
    CLOCK_EPOCH,
    PERIOD_AUG_END,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_2_HEADERS,
    CONTROLLER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    make_member_headers,
    make_partner_operator_headers,
)


# ─── The logical clock ───────────────────────────────────────────────────────
def set_clock(api, to: str = CLOCK_EPOCH) -> None:
    """Move the server's logical clock to a named instant."""
    get_success_data(api.set_clock(to, CONTROLLER_HEADERS))


# ─── Programme and its configuration ─────────────────────────────────────────
def new_program(api, **overrides: Any) -> Dict[str, Any]:
    """A programme in DRAFT, fully configured."""
    return get_success_data(
        api.create_program(factories.program_payload(**overrides), PROGRAM_ADMIN_HEADERS)
    )


def new_cohort(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """An enrolment vintage under one programme."""
    return get_success_data(
        api.create_cohort(
            factories.cohort_payload(program_id, **overrides), PROGRAM_ADMIN_HEADERS
        )
    )


def new_state_expiry_rule(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """A state expiry rule under one programme."""
    return get_success_data(
        api.create_state_expiry_rule(
            factories.state_expiry_rule_payload(program_id, **overrides),
            PROGRAM_ADMIN_HEADERS,
        )
    )


def activate(api, program_id: str) -> Dict[str, Any]:
    """Drive a programme DRAFT → ACTIVE, seeding its breakage rate."""
    return get_success_data(api.activate_program(program_id, None, PROGRAM_ADMIN_HEADERS))


def configured_program(
    api,
    program_overrides: Optional[Dict[str, Any]] = None,
    cohort_overrides: Optional[Dict[str, Any]] = None,
    rule_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A DRAFT programme carrying the one state expiry rule and the one cohort that
    a first activation requires, returned as ``{"program", "rule", "cohort"}``.
    """
    program = new_program(api, **(program_overrides or {}))
    rule = new_state_expiry_rule(api, program["id"], **(rule_overrides or {}))
    cohort = new_cohort(api, program["id"], **(cohort_overrides or {}))
    return {"program": program, "rule": rule, "cohort": cohort}


def active_program(
    api,
    program_overrides: Optional[Dict[str, Any]] = None,
    cohort_overrides: Optional[Dict[str, Any]] = None,
    rule_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A programme configured with one state expiry rule and one cohort and then
    activated, returned as ``{"program", "rule", "cohort"}`` with the programme
    read back after activation so its seeded rate and version are current.
    """
    bundle = configured_program(
        api, program_overrides, cohort_overrides, rule_overrides
    )
    bundle["program"] = activate(api, bundle["program"]["id"])
    return bundle


def program_version(api, program_id: str) -> int:
    """The programme's current version, for an optimistic-concurrency payload."""
    return get_success_data(api.get_program(program_id, CONTROLLER_HEADERS))["version"]


def agreement_version(api, agreement_id: str) -> int:
    """The agreement's current version, for an optimistic-concurrency payload."""
    return get_success_data(api.get_agreement(agreement_id, ACCOUNTANT_HEADERS))["version"]


# ─── Members, periods and agreements ─────────────────────────────────────────
def new_member(api, program_id: str, cohort_id: str, **overrides: Any) -> Dict[str, Any]:
    """A member of one programme and vintage."""
    return get_success_data(
        api.create_member(
            factories.member_payload(program_id, cohort_id, **overrides),
            ACCOUNTANT_HEADERS,
        )
    )


def new_period(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """An OPEN accounting period over a half-open window."""
    return get_success_data(
        api.create_period(
            factories.period_payload(program_id, **overrides), CONTROLLER_HEADERS
        )
    )


def new_agreement(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """An ACTIVE partner agreement over a closed effective window."""
    return get_success_data(
        api.create_agreement(
            factories.agreement_payload(program_id, **overrides), PROGRAM_ADMIN_HEADERS
        )
    )


# ─── The ledger ──────────────────────────────────────────────────────────────
def issue_lot(
    api, member_id: str, period_id: str, base_points: int = 1000, **overrides: Any
) -> Dict[str, Any]:
    """One point lot issued to a member inside a period."""
    return get_success_data(
        api.create_point_lot(
            factories.point_lot_payload(member_id, period_id, base_points, **overrides),
            ACCOUNTANT_HEADERS,
        )
    )


def request_redemption(
    api, member_id: str, period_id: str, points_requested: int = 500, **overrides: Any
) -> Dict[str, Any]:
    """A redemption request in state REQUESTED."""
    return get_success_data(
        api.create_redemption(
            factories.redemption_payload(
                member_id, period_id, points_requested, **overrides
            ),
            ACCOUNTANT_HEADERS,
        )
    )


def allocated_redemption(
    api, member_id: str, period_id: str, points_requested: int = 500, **overrides: Any
) -> Dict[str, Any]:
    """A redemption request driven through allocation, consuming lots first-in-first-out."""
    event = request_redemption(api, member_id, period_id, points_requested, **overrides)
    return get_success_data(api.allocate_redemption(event["id"], None, ACCOUNTANT_HEADERS))


def fulfilled_redemption(
    api, member_id: str, period_id: str, points_requested: int = 500, **overrides: Any
) -> Dict[str, Any]:
    """A redemption driven all the way to FULFILLED, so the final release is measured."""
    event = allocated_redemption(api, member_id, period_id, points_requested, **overrides)
    return get_success_data(api.fulfill_redemption(event["id"], None, ACCOUNTANT_HEADERS))


# ─── Breakage estimates ──────────────────────────────────────────────────────
def draft_estimate(api, program_id: str, period_id: str, **overrides: Any) -> Dict[str, Any]:
    """A DRAFT estimate measured against the programme's current outstanding points."""
    return get_success_data(
        api.create_estimate(
            program_id, factories.estimate_payload(period_id, **overrides), ACCOUNTANT_HEADERS
        )
    )


def submitted_estimate(
    api, program_id: str, period_id: str, **overrides: Any
) -> Dict[str, Any]:
    """An estimate prepared and submitted for approval."""
    estimate = draft_estimate(api, program_id, period_id, **overrides)
    return get_success_data(api.submit_estimate(estimate["id"], None, ACCOUNTANT_HEADERS))


def approved_estimate(
    api,
    program_id: str,
    period_id: str,
    approver_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    An estimate prepared, submitted and approved by a Controller who is not the
    preparer, which also overwrites the programme's current breakage rate.
    """
    estimate = submitted_estimate(api, program_id, period_id, **overrides)
    return get_success_data(
        api.approve_estimate(
            estimate["id"],
            factories.approval_payload(program_version(api, program_id)),
            approver_headers or CONTROLLER_HEADERS,
        )
    )


# ─── Settlement ──────────────────────────────────────────────────────────────
def draft_statement(api, agreement_id: str, period_id: str) -> Dict[str, Any]:
    """A DRAFT settlement statement measured against the agreement's economics."""
    return get_success_data(
        api.create_statement(
            factories.statement_payload(
                agreement_id, period_id, agreement_version(api, agreement_id)
            ),
            ACCOUNTANT_HEADERS,
        )
    )


def issued_statement(api, agreement_id: str, period_id: str) -> Dict[str, Any]:
    """A statement issued to the partner, and therefore disputable."""
    statement = draft_statement(api, agreement_id, period_id)
    return get_success_data(api.issue_statement(statement["id"], None, ACCOUNTANT_HEADERS))


def paid_statement(api, agreement_id: str, period_id: str) -> Dict[str, Any]:
    """A statement issued and then paid, clearing the agreement's obligation."""
    statement = issued_statement(api, agreement_id, period_id)
    return get_success_data(api.pay_statement(statement["id"], None, CONTROLLER_HEADERS))


# ─── Period closing ──────────────────────────────────────────────────────────
def soft_close(api, period_id: str) -> Dict[str, Any]:
    """Drive a period OPEN → SOFT_CLOSED, running the eight close steps."""
    return get_success_data(api.soft_close_period(period_id, None, CONTROLLER_HEADERS))


def soft_closed_period(
    api,
    program_id: str,
    period_id: str,
    clock_at_or_after_end: str = PERIOD_AUG_END,
    **estimate_overrides: Any,
) -> Dict[str, Any]:
    """
    A period taken all the way to SOFT_CLOSED: an approved estimate exists, the
    clock has reached the period's end, and the close has run.
    """
    approved_estimate(api, program_id, period_id, **estimate_overrides)
    set_clock(api, clock_at_or_after_end)
    return soft_close(api, period_id)


# ─── Change orders ───────────────────────────────────────────────────────────
def modeled_change_order(api, program_id: str, effective_at: str, **overrides: Any) -> Dict[str, Any]:
    """A MODELED change order carrying its projection."""
    return get_success_data(
        api.create_change_order(
            factories.change_order_payload(program_id, effective_at, **overrides),
            PROGRAM_ADMIN_HEADERS,
        )
    )


def approved_change_order(api, program_id: str, effective_at: str, **overrides: Any) -> Dict[str, Any]:
    """A change order approved and therefore applicable once its instant arrives."""
    order = modeled_change_order(api, program_id, effective_at, **overrides)
    return get_success_data(api.approve_change_order(order["id"], None, CONTROLLER_HEADERS))


# ─── Whole-chain convenience ─────────────────────────────────────────────────
def issuance_ready(
    api,
    program_overrides: Optional[Dict[str, Any]] = None,
    cohort_overrides: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
    period_overrides: Optional[Dict[str, Any]] = None,
    clock: str = CLOCK_EPOCH,
    rule_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    The minimum state an issuance needs: the clock placed, an ACTIVE programme
    with one state expiry rule and one cohort, one member, and one OPEN period.
    Returns ``{"program", "rule", "cohort", "member", "period"}``.
    """
    set_clock(api, clock)
    bundle = active_program(api, program_overrides, cohort_overrides, rule_overrides)
    program_id = bundle["program"]["id"]
    bundle["member"] = new_member(
        api, program_id, bundle["cohort"]["id"], **(member_overrides or {})
    )
    bundle["period"] = new_period(api, program_id, **(period_overrides or {}))
    return bundle


def partner_issuance_ready(
    api,
    agreement_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """:func:`issuance_ready` plus one ACTIVE partner agreement."""
    bundle = issuance_ready(api, **kwargs)
    bundle["agreement"] = new_agreement(
        api, bundle["program"]["id"], **(agreement_overrides or {})
    )
    return bundle


def member_headers_for(bundle: Dict[str, Any]) -> Dict[str, str]:
    """The acting headers of the member in a bundle."""
    return make_member_headers(bundle["member"]["id"])


def partner_headers_for(bundle: Dict[str, Any]) -> Dict[str, str]:
    """The acting headers of the partner agreement in a bundle."""
    return make_partner_operator_headers(bundle["agreement"]["id"])


# Re-exported so a test that only imports fixtures still has the second approver.
SECOND_CONTROLLER_HEADERS = CONTROLLER_2_HEADERS

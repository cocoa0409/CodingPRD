"""Fixtures and seeding helpers.

The API under test starts from an empty database for every single test, so
nothing here may assume a pre-existing row: every precondition is built from
scratch through the endpoints the PRD declares.

Layering:

1. ``api`` and the role-header fixtures — the bare essentials.
2. ``seed_*`` / ``do_*`` helper functions — one PRD call each, with the setup
   response unwrapped leniently so a broken precondition fails loudly.
3. ``build_*`` helper functions — multi-call recipes (a conveyed component, an
   adopted reserve study, a case standing in ``AUDIT_IN_PROGRESS``).
4. Composite pytest fixtures for the shapes many tests share.
5. ``fresh_association_version`` — the OCC read every assessment-schedule
   creation has to make.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    CLAIM_ACTION_ACCEPT,
    CLAIM_ACTION_NOTICE,
    CLAIM_ACTION_REINVESTIGATE,
    CLAIM_ACTION_REJECT,
    CLAIM_ACTION_RESERVE,
    CLAIM_ACTION_WITHDRAW,
    CONTRACT_ACTION_CANCEL,
    CONTRACT_ACTION_CONSENT,
    CONTRACT_ACTION_REFUSE_CONSENT,
    CONTRACT_ACTION_REQUEST_ASSIGNMENT,
    DIMENSION_FINANCIAL,
    DIMENSION_GOVERNANCE,
    FUNDING_METHOD_CASH_FLOW,
    FUNDING_METHOD_COMPONENT_FULL_FUNDING,
    MILESTONE_BUILD_COMPLETE,
    MILESTONE_CONVEYANCE_ACCEPTED,
    MILESTONE_DEED_TENDERED,
    RECORDS_ACTION_ACCEPT,
    RECORDS_ACTION_DELIVER,
    RECORDS_ACTION_REJECT,
    SEAT_TYPE_DECLARANT_APPOINTED,
    SEAT_TYPE_OWNER_ELECTED,
    STUDY_ACTION_ADOPT,
    STUDY_ACTION_RECOMPUTE,
    TRIGGER_BASIS_FIXED_DATE,
    TRIGGER_BASIS_PERCENT_SOLD,
)
from .factories import (
    advance_payload,
    assessment_schedule_payload,
    association_payload,
    audit_engagement_payload,
    certify_trigger_payload,
    claim_action_payload,
    close_sale_payload,
    component_payload,
    contract_action_payload,
    defect_claim_payload,
    director_payload,
    lot_payload,
    milestone_payload,
    records_item_payload,
    records_transition_payload,
    reserve_study_payload,
    reversal_payload,
    study_action_payload,
    subsidy_entry_payload,
    turnover_case_payload,
    vendor_contract_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    DECLARANT_HEADERS,
    INSPECTOR_HEADERS,
    make_transition_committee_headers,
)
from .types import Headers, Payload

# ═══════════════════════════════════════════════════════
# 1. Client and role headers
# ═══════════════════════════════════════════════════════


@pytest.fixture
def api() -> ApiClient:
    """A client pointed at the API under test."""
    return ApiClient()


@pytest.fixture
def admin_headers() -> Headers:
    return dict(ADMIN_HEADERS)


@pytest.fixture
def declarant_headers() -> Headers:
    return dict(DECLARANT_HEADERS)


@pytest.fixture
def auditor_headers() -> Headers:
    return dict(AUDITOR_HEADERS)


@pytest.fixture
def inspector_headers() -> Headers:
    return dict(INSPECTOR_HEADERS)


# ═══════════════════════════════════════════════════════
# 2. Single-call seeding helpers
# ═══════════════════════════════════════════════════════


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the server-held logical clock. Performs no business transition."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN_HEADERS))


def seed_association(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_association(association_payload(**overrides), ADMIN_HEADERS)
    )


def read_association(api: ApiClient, association_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_association(association_id, ADMIN_HEADERS))


def seed_turnover_case(
    api: ApiClient, association_id: str, total_seats: int = 5, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_turnover_case(
            turnover_case_payload(association_id, total_seats=total_seats, **overrides),
            ADMIN_HEADERS,
        )
    )


def read_turnover_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_turnover_case(case_id, ADMIN_HEADERS))


def seed_lot(
    api: ApiClient, association_id: str, lot_number: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_lot(lot_payload(association_id, lot_number, **overrides), DECLARANT_HEADERS)
    )


def do_close_sale(api: ApiClient, lot_id: str, closing_date: str) -> Dict[str, Any]:
    return get_success_data(
        api.close_lot_sale(lot_id, close_sale_payload(closing_date), DECLARANT_HEADERS)
    )


def seed_component(api: ApiClient, association_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_component(component_payload(association_id, **overrides), DECLARANT_HEADERS)
    )


def do_build_complete(
    api: ApiClient, component_id: str, effective_date: str
) -> Dict[str, Any]:
    return get_success_data(
        api.record_milestone(
            component_id,
            milestone_payload(MILESTONE_BUILD_COMPLETE, effective_date=effective_date),
            DECLARANT_HEADERS,
        )
    )


def do_deed_tendered(api: ApiClient, component_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.record_milestone(
            component_id, milestone_payload(MILESTONE_DEED_TENDERED), DECLARANT_HEADERS
        )
    )


def do_conveyance_accepted(
    api: ApiClient, component_id: str, association_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.record_milestone(
            component_id,
            milestone_payload(MILESTONE_CONVEYANCE_ACCEPTED),
            make_transition_committee_headers(association_id),
        )
    )


def seed_records_item(
    api: ApiClient, case_id: str, category: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_records_item(
            records_item_payload(case_id, category, **overrides), DECLARANT_HEADERS
        )
    )


def do_deliver_item(api: ApiClient, item_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.records_item_transition(
            item_id, records_transition_payload(RECORDS_ACTION_DELIVER), DECLARANT_HEADERS
        )
    )


def do_accept_item(api: ApiClient, item_id: str, association_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.records_item_transition(
            item_id,
            records_transition_payload(RECORDS_ACTION_ACCEPT),
            make_transition_committee_headers(association_id),
        )
    )


def do_reject_item(
    api: ApiClient, item_id: str, association_id: str, rejection_reason: str = "Illegible scan"
) -> Dict[str, Any]:
    return get_success_data(
        api.records_item_transition(
            item_id,
            records_transition_payload(
                RECORDS_ACTION_REJECT, rejection_reason=rejection_reason
            ),
            make_transition_committee_headers(association_id),
        )
    )


def seed_subsidy_entry(
    api: ApiClient,
    association_id: str,
    direction: str,
    amount_cents: int,
    period_month: str,
    headers: Optional[Headers] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_subsidy_entry(
            subsidy_entry_payload(association_id, direction, amount_cents, period_month),
            headers or DECLARANT_HEADERS,
        )
    )


def do_reverse_entry(
    api: ApiClient, entry_id: str, reason: str = "Posted against the wrong period"
) -> Dict[str, Any]:
    return get_success_data(
        api.reverse_subsidy_entry(entry_id, reversal_payload(reason), DECLARANT_HEADERS)
    )


def seed_audit_engagement(
    api: ApiClient,
    association_id: str,
    period_start: str,
    period_end: str,
    headers: Optional[Headers] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_audit_engagement(
            audit_engagement_payload(association_id, period_start, period_end),
            headers or AUDITOR_HEADERS,
        )
    )


def do_issue_engagement(
    api: ApiClient, engagement_id: str, headers: Optional[Headers] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.issue_audit_engagement(engagement_id, headers or AUDITOR_HEADERS)
    )


def seed_reserve_study(
    api: ApiClient,
    association_id: str,
    funding_method: str = FUNDING_METHOD_COMPONENT_FULL_FUNDING,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_reserve_study(
            reserve_study_payload(association_id, funding_method, **overrides),
            make_transition_committee_headers(association_id),
        )
    )


def do_recompute_study(
    api: ApiClient, study_id: str, association_id: str, method: str
) -> Dict[str, Any]:
    return get_success_data(
        api.reserve_study_action(
            study_id,
            study_action_payload(STUDY_ACTION_RECOMPUTE, method=method),
            make_transition_committee_headers(association_id),
        )
    )


def do_adopt_study(api: ApiClient, study_id: str, association_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.reserve_study_action(
            study_id,
            study_action_payload(STUDY_ACTION_ADOPT, method=None),
            make_transition_committee_headers(association_id),
        )
    )


def seed_defect_claim(
    api: ApiClient, association_id: str, component_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_defect_claim(
            defect_claim_payload(association_id, component_id, **overrides),
            make_transition_committee_headers(association_id),
        )
    )


def do_claim_notice(api: ApiClient, claim_id: str, association_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.defect_claim_action(
            claim_id,
            claim_action_payload(CLAIM_ACTION_NOTICE),
            make_transition_committee_headers(association_id),
        )
    )


def do_claim_developer_reject(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    """The declarant answers a noticed claim, moving it to REJECTED_BY_DEVELOPER."""
    return get_success_data(
        api.defect_claim_action(
            claim_id, claim_action_payload(CLAIM_ACTION_REJECT), DECLARANT_HEADERS
        )
    )


def do_claim_reinvestigate(
    api: ApiClient, claim_id: str, association_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.defect_claim_action(
            claim_id,
            claim_action_payload(CLAIM_ACTION_REINVESTIGATE),
            make_transition_committee_headers(association_id),
        )
    )


def do_claim_reserve(
    api: ApiClient, claim_id: str, association_id: str, valuation_basis: str
) -> Dict[str, Any]:
    return get_success_data(
        api.defect_claim_action(
            claim_id,
            claim_action_payload(CLAIM_ACTION_RESERVE, valuation_basis=valuation_basis),
            make_transition_committee_headers(association_id),
        )
    )


def do_claim_accept(
    api: ApiClient, claim_id: str, settlement_amount_cents: int
) -> Dict[str, Any]:
    return get_success_data(
        api.defect_claim_action(
            claim_id,
            claim_action_payload(
                CLAIM_ACTION_ACCEPT, settlement_amount_cents=settlement_amount_cents
            ),
            DECLARANT_HEADERS,
        )
    )


def do_claim_withdraw(api: ApiClient, claim_id: str, association_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.defect_claim_action(
            claim_id,
            claim_action_payload(CLAIM_ACTION_WITHDRAW),
            make_transition_committee_headers(association_id),
        )
    )


def do_repose_sweep(api: ApiClient, association_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.repose_sweep(association_id, make_transition_committee_headers(association_id))
    )


def seed_vendor_contract(
    api: ApiClient, association_id: str, component_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_vendor_contract(
            vendor_contract_payload(association_id, component_id, **overrides),
            DECLARANT_HEADERS,
        )
    )


def do_request_assignment(api: ApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.vendor_contract_action(
            contract_id,
            contract_action_payload(CONTRACT_ACTION_REQUEST_ASSIGNMENT),
            DECLARANT_HEADERS,
        )
    )


def do_consent(api: ApiClient, contract_id: str, association_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.vendor_contract_action(
            contract_id,
            contract_action_payload(CONTRACT_ACTION_CONSENT),
            make_transition_committee_headers(association_id),
        )
    )


def do_refuse_consent(
    api: ApiClient, contract_id: str, association_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.vendor_contract_action(
            contract_id,
            contract_action_payload(CONTRACT_ACTION_REFUSE_CONSENT),
            make_transition_committee_headers(association_id),
        )
    )


def do_cancel_contract(
    api: ApiClient, contract_id: str, association_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.vendor_contract_action(
            contract_id,
            contract_action_payload(CONTRACT_ACTION_CANCEL),
            make_transition_committee_headers(association_id),
        )
    )


def seed_director(
    api: ApiClient,
    case_id: str,
    seat_type: str,
    headers: Headers,
    full_name: str = "Dana Whitfield",
) -> Dict[str, Any]:
    return get_success_data(
        api.seat_director(
            director_payload(case_id, seat_type, full_name=full_name), headers
        )
    )


def seed_declarant_appointed_director(
    api: ApiClient, case_id: str, full_name: str = "Avery Doyle"
) -> Dict[str, Any]:
    return seed_director(
        api, case_id, SEAT_TYPE_DECLARANT_APPOINTED, DECLARANT_HEADERS, full_name
    )


def seed_owner_elected_director(
    api: ApiClient,
    case_id: str,
    full_name: str = "Rowan Pike",
    headers: Optional[Headers] = None,
) -> Dict[str, Any]:
    return seed_director(
        api, case_id, SEAT_TYPE_OWNER_ELECTED, headers or INSPECTOR_HEADERS, full_name
    )


def do_rescind_director(
    api: ApiClient, director_id: str, headers: Optional[Headers] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.rescind_director(director_id, headers or INSPECTOR_HEADERS)
    )


def do_certify_trigger(
    api: ApiClient,
    case_id: str,
    association_id: str,
    trigger_basis: str = TRIGGER_BASIS_PERCENT_SOLD,
    headers: Optional[Headers] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.certify_trigger(
            case_id,
            certify_trigger_payload(trigger_basis=trigger_basis),
            headers or make_transition_committee_headers(association_id),
        )
    )


def do_advance_financial(
    api: ApiClient,
    case_id: str,
    association_id: str,
    subsidy_end_date: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Payload = advance_payload(DIMENSION_FINANCIAL)
    if subsidy_end_date is not None:
        payload["subsidy_end_date"] = subsidy_end_date
    return get_success_data(
        api.advance_case(
            case_id, payload, make_transition_committee_headers(association_id)
        )
    )


def do_advance_governance(
    api: ApiClient, case_id: str, association_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.advance_case(
            case_id,
            advance_payload(DIMENSION_GOVERNANCE),
            make_transition_committee_headers(association_id),
        )
    )


# ═══════════════════════════════════════════════════════
# 3. Multi-call recipes
# ═══════════════════════════════════════════════════════


def build_conveyed_component(
    api: ApiClient,
    association_id: str,
    effective_date: str = "2026-01-15T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Walk a component all the way to CONVEYED, the state a defect notice needs."""
    component = seed_component(api, association_id, **overrides)
    do_build_complete(api, component["id"], effective_date)
    do_deed_tendered(api, component["id"])
    return do_conveyance_accepted(api, component["id"], association_id)


def build_completed_component(
    api: ApiClient,
    association_id: str,
    effective_date: str = "2026-01-15T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A component that is COMPLETE but never accepted by the association."""
    component = seed_component(api, association_id, **overrides)
    return do_build_complete(api, component["id"], effective_date)


def build_adopted_reserve_study(
    api: ApiClient,
    association_id: str,
    method: str = FUNDING_METHOD_CASH_FLOW,
    funding_method: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a study, evaluate it under ``method`` and adopt it."""
    study = seed_reserve_study(
        api, association_id, funding_method or method, **overrides
    )
    do_recompute_study(api, study["id"], association_id, method)
    return do_adopt_study(api, study["id"], association_id)


def build_closed_lots(
    api: ApiClient,
    association_id: str,
    lot_numbers: List[str],
    closing_date: str = "2026-06-15",
) -> List[Dict[str, Any]]:
    """Record each lot and close its sale, oldest first."""
    closed = []
    for lot_number in lot_numbers:
        lot = seed_lot(api, association_id, lot_number)
        closed.append(do_close_sale(api, lot["id"], closing_date))
    return closed


def build_case_in_audit_in_progress(
    api: ApiClient,
    association_id: str,
    case_id: str,
    subsidy_end_date: str = "2026-08-31",
    period_start: str = "2026-01-01",
    period_end: str = "2026-03-31",
) -> Dict[str, Any]:
    """Certify the trigger on the fixed date, engage an auditor, end the subsidy.

    Leaves ``financial_status`` at ``AUDIT_IN_PROGRESS`` — the only state from
    which an assessment schedule may be created.
    """
    do_certify_trigger(api, case_id, association_id, TRIGGER_BASIS_FIXED_DATE)
    seed_audit_engagement(api, association_id, period_start, period_end)
    return do_advance_financial(api, case_id, association_id, subsidy_end_date)


def build_owner_controlled_board(
    api: ApiClient, association_id: str, case_id: str, seats_to_fill: int
) -> List[Dict[str, Any]]:
    """Seat ``seats_to_fill`` owner-elected directors after the election is called."""
    seated = []
    for index in range(seats_to_fill):
        seated.append(
            seed_owner_elected_director(api, case_id, full_name=f"Owner Director {index + 1}")
        )
    return seated


# ═══════════════════════════════════════════════════════
# 4. Composite fixtures
# ═══════════════════════════════════════════════════════


@pytest.fixture
def association(api: ApiClient) -> Dict[str, Any]:
    """A registered association with no turnover case, so §2.8 never gates it."""
    return seed_association(api)


@pytest.fixture
def committee_headers(association: Dict[str, Any]) -> Headers:
    """Committee headers bound to the ``association`` fixture's own id."""
    return make_transition_committee_headers(association["id"])


@pytest.fixture
def association_with_case(api: ApiClient) -> Dict[str, Any]:
    """An association plus its freshly opened turnover case.

    Returns ``{"association": ..., "case": ..., "committee_headers": ...}``.
    """
    assoc = seed_association(api)
    case = seed_turnover_case(api, assoc["id"], total_seats=5)
    return {
        "association": assoc,
        "case": case,
        "committee_headers": make_transition_committee_headers(assoc["id"]),
    }


@pytest.fixture
def conveyed_component(api: ApiClient, association: Dict[str, Any]) -> Dict[str, Any]:
    """A component that has been built, tendered and accepted."""
    return build_conveyed_component(api, association["id"])


# ═══════════════════════════════════════════════════════
# 5. Optimistic concurrency read (§2.10)
# ═══════════════════════════════════════════════════════


def fresh_association_version(api: ApiClient, association_id: str) -> int:
    """Read the association's current ``version`` for ``expected_association_version``.

    Almost every write in this system advances the association's version, so
    this must be called immediately before each assessment-schedule creation
    rather than cached from an earlier response.
    """
    return read_association(api, association_id)["version"]


def create_schedule_with_fresh_version(
    api: ApiClient,
    association_id: str,
    fiscal_year: int,
    projected_operating_cost_cents: int,
):
    """POST an assessment schedule using a just-read association version."""
    version = fresh_association_version(api, association_id)
    return api.create_assessment_schedule(
        assessment_schedule_payload(
            association_id,
            version,
            fiscal_year=fiscal_year,
            projected_operating_cost_cents=projected_operating_cost_cents,
        ),
        make_transition_committee_headers(association_id),
    )


def seed_assessment_schedule(
    api: ApiClient,
    association_id: str,
    fiscal_year: int,
    projected_operating_cost_cents: int,
) -> Dict[str, Any]:
    return get_success_data(
        create_schedule_with_fresh_version(
            api, association_id, fiscal_year, projected_operating_cost_cents
        )
    )


def do_adopt_schedule(
    api: ApiClient,
    schedule_id: str,
    association_id: str,
    owner_vote_ratified: Optional[bool] = None,
) -> Dict[str, Any]:
    payload: Payload = {}
    if owner_vote_ratified is not None:
        payload["owner_vote_ratified"] = owner_vote_ratified
    return get_success_data(
        api.adopt_assessment_schedule(
            schedule_id, make_transition_committee_headers(association_id), payload
        )
    )

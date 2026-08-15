"""Composite setup helpers (PRD §2-§3).

Every helper builds its preconditions from scratch via PRD-declared endpoints,
using get_success_data so setup failures surface as clear setup errors.
Identity threading: Physician-role calls always use make_physician_headers()
with the actual physician id (the Physician role is entity-backed, PRD §2.1).
"""
from typing import Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from .api_client import api_client
from .factories import (
    add_member_payload,
    appoint_seat_payload,
    appraise_payload,
    buyout_approval_payload,
    capital_call_payload,
    charter_amendment_payload,
    comp_policy_payload,
    create_board_seat_payload,
    create_buy_in_offer_payload,
    create_coi_disclosure_payload,
    create_committee_payload,
    create_exit_valuation_payload,
    create_merger_proposal_payload,
    create_motion_payload,
    create_physician_payload,
    create_policy_payload,
    distribution_payload,
    finalize_payload,
    merger_motion_payload,
    pay_assessment_payload,
    pay_installment_payload,
    respond_offer_payload,
    review_coi_payload,
    set_standing_payload,
    vote_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_physician_headers,
)

ADMIN = TEST_USERS["board_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

DEFAULT_DUE_DATE = "2026-08-20T00:00:00Z"


# --- Logical clock (PRD §2.4) ------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


# --- Governance policy (PRD §2.8) --------------------------------------------


def create_policy(**overrides) -> dict:
    resp = api_client.create_policy(create_policy_payload(**overrides), ADMIN)
    return get_success_data(resp)


def get_policy() -> dict:
    resp = api_client.get_policy(ADMIN)
    return get_success_data(resp)


def update_policy(payload: dict) -> dict:
    resp = api_client.update_policy(payload, ADMIN)
    return get_success_data(resp)


# --- Physicians (PRD §3.1) ---------------------------------------------------


def create_physician(**overrides) -> dict:
    resp = api_client.create_physician(create_physician_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_shareholder(full_name: str, initial_shares: int, hire_date: str) -> dict:
    """Onboard a founding shareholder (PRD §3.1)."""
    return create_physician(
        full_name=full_name,
        hire_date=hire_date,
        founding_shareholder=True,
        initial_shares=initial_shares,
    )


def get_physician(physician_id: str) -> dict:
    resp = api_client.get_physician(physician_id, ADMIN)
    return get_success_data(resp)


def list_physicians(params: Optional[dict] = None, headers: Optional[dict] = None):
    resp = api_client.list_physicians(headers or ADMIN, params=params)
    return validate_paginated(resp)


def set_standing(physician_id: str, standing: str) -> dict:
    resp = api_client.set_physician_standing(
        physician_id, set_standing_payload(standing), ADMIN
    )
    return get_success_data(resp)


def physician_headers(physician: dict) -> dict:
    """Entity-backed Physician headers for ownership-gated calls (PRD §2.1)."""
    return make_physician_headers(physician["id"])


# --- Board seats (PRD §3.3) --------------------------------------------------


def create_board_seat(seat_label: str = "SEAT-1", seat_class: str = "AT_LARGE") -> dict:
    resp = api_client.create_board_seat(
        create_board_seat_payload(seat_label=seat_label, seat_class=seat_class), ADMIN
    )
    return get_success_data(resp)


def get_board_seat(seat_id: str) -> dict:
    resp = api_client.get_board_seat(seat_id, ADMIN)
    return get_success_data(resp)


def appoint_seat(seat_id: str, physician_id: str, term_start: str, term_end: str) -> dict:
    resp = api_client.appoint_board_seat(
        seat_id,
        appoint_seat_payload(physician_id, term_start=term_start, term_end=term_end),
        ADMIN,
    )
    return get_success_data(resp)


# --- Committees (PRD §3.3) ---------------------------------------------------


def create_committee(
    name: str = "Quality Committee",
    committee_type: str = "QUALITY",
    quorum_count: int = 1,
    approval_threshold: str = "SIMPLE_MAJORITY",
) -> dict:
    resp = api_client.create_committee(
        create_committee_payload(
            name=name,
            committee_type=committee_type,
            quorum_count=quorum_count,
            approval_threshold=approval_threshold,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def get_committee(committee_id: str) -> dict:
    resp = api_client.get_committee(committee_id, ADMIN)
    return get_success_data(resp)


def add_member(committee_id: str, physician_id: str, committee_role: str = "MEMBER") -> dict:
    resp = api_client.add_committee_member(
        committee_id, add_member_payload(physician_id, committee_role), ADMIN
    )
    return get_success_data(resp)


def remove_member(committee_id: str, physician_id: str) -> dict:
    resp = api_client.remove_committee_member(committee_id, physician_id, ADMIN)
    return get_success_data(resp)


def dissolve_committee(committee_id: str) -> dict:
    resp = api_client.dissolve_committee(committee_id, ADMIN)
    return get_success_data(resp)


def setup_active_committee(chair_or_member_id: str, **kwargs) -> dict:
    """Committee with one member at quorum 1 -> ACTIVE (PRD §3.3)."""
    committee = create_committee(quorum_count=1, **kwargs)
    add_member(committee["id"], chair_or_member_id, kwargs.pop("role", "MEMBER"))
    return get_committee(committee["id"])


# --- Buy-in offers (PRD §3.2) -------------------------------------------------


def create_buy_in_offer(
    physician_id: str,
    target_tier: str = "PARTNER_TRACK",
    share_grant: int = 0,
    installment_count: int = 1,
) -> dict:
    resp = api_client.create_buy_in_offer(
        create_buy_in_offer_payload(
            physician_id,
            target_tier=target_tier,
            share_grant=share_grant,
            installment_count=installment_count,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def get_buy_in_offer(offer_id: str) -> dict:
    resp = api_client.get_buy_in_offer(offer_id, ADMIN)
    return get_success_data(resp)


def respond_offer(offer_id: str, physician: dict, decision: str) -> dict:
    resp = api_client.respond_buy_in_offer(
        offer_id, respond_offer_payload(decision), physician_headers(physician)
    )
    return get_success_data(resp)


def pay_installment(offer_id: str, amount_cents: int, physician: Optional[dict] = None) -> dict:
    headers = physician_headers(physician) if physician is not None else ADMIN
    resp = api_client.pay_installment(offer_id, pay_installment_payload(amount_cents), headers)
    return get_success_data(resp)


# --- Motions and votes (PRD §3.4) --------------------------------------------


def create_motion(
    motion_type: str,
    sponsor: dict,
    payload: dict,
    committee_id: Optional[str] = None,
    supersedes_motion_id: Optional[str] = None,
) -> dict:
    """Sponsor a motion as the given physician (Physician role, own sponsorship)."""
    resp = api_client.create_motion(
        create_motion_payload(
            motion_type,
            sponsor["id"],
            payload,
            committee_id=committee_id,
            supersedes_motion_id=supersedes_motion_id,
        ),
        physician_headers(sponsor),
    )
    return get_success_data(resp)


def get_motion(motion_id: str) -> dict:
    resp = api_client.get_motion(motion_id, ADMIN)
    return get_success_data(resp)


def list_motions(params: Optional[dict] = None):
    resp = api_client.list_motions(ADMIN, params=params)
    return validate_paginated(resp)


def propose_motion(motion_id: str, sponsor: dict) -> dict:
    resp = api_client.propose_motion(motion_id, physician_headers(sponsor))
    return get_success_data(resp)


def open_motion(motion_id: str, sponsor: dict) -> dict:
    resp = api_client.open_motion(motion_id, physician_headers(sponsor))
    return get_success_data(resp)


def table_motion(motion_id: str, sponsor: dict) -> dict:
    resp = api_client.table_motion(motion_id, physician_headers(sponsor))
    return get_success_data(resp)


def resume_motion(motion_id: str, sponsor: dict) -> dict:
    resp = api_client.resume_motion(motion_id, physician_headers(sponsor))
    return get_success_data(resp)


def withdraw_motion(motion_id: str, sponsor: dict) -> dict:
    resp = api_client.withdraw_motion(motion_id, physician_headers(sponsor))
    return get_success_data(resp)


def close_motion(motion_id: str) -> dict:
    """Close is a BoardAdmin act (PRD §3.4)."""
    resp = api_client.close_motion(motion_id, ADMIN)
    return get_success_data(resp)


def cast_vote(motion_id: str, voter: dict, vote_choice: str) -> dict:
    resp = api_client.cast_vote(
        motion_id, vote_payload(vote_choice), physician_headers(voter)
    )
    return validate_success(resp, 201)


def list_motion_votes(motion_id: str, headers: Optional[dict] = None):
    resp = api_client.list_motion_votes(motion_id, headers or ADMIN)
    return validate_paginated(resp)


def list_physician_votes(physician_id: str, headers: Optional[dict] = None):
    resp = api_client.list_physician_votes(physician_id, headers or ADMIN)
    return validate_paginated(resp)


def create_and_open_motion(
    motion_type: str,
    sponsor: dict,
    payload: dict,
    committee_id: Optional[str] = None,
) -> dict:
    """DRAFT -> PROPOSED -> OPEN (PRD §3.4). Returns the OPEN motion."""
    motion = create_motion(motion_type, sponsor, payload, committee_id=committee_id)
    propose_motion(motion["id"], sponsor)
    return open_motion(motion["id"], sponsor)


def adopt_motion(motion_id: str, voters: list, vote_choice: str = "FOR") -> dict:
    """Cast FOR ballots for the given voters, then close. Returns closed motion."""
    for voter in voters:
        cast_vote(motion_id, voter, vote_choice)
    return close_motion(motion_id)


def adopt_motion_full(
    motion_type: str,
    sponsor: dict,
    payload: dict,
    voters: list,
    committee_id: Optional[str] = None,
    vote_choice: str = "FOR",
) -> dict:
    """create -> propose -> open -> votes -> close. Returns the closed motion."""
    motion = create_and_open_motion(motion_type, sponsor, payload, committee_id=committee_id)
    return adopt_motion(motion["id"], voters or [sponsor], vote_choice)


# --- Capital calls (PRD §3.5) ------------------------------------------------


def get_capital_call(call_id: str) -> dict:
    resp = api_client.get_capital_call(call_id, ADMIN)
    return get_success_data(resp)


def capital_call_for_motion(motion_id: str) -> dict:
    resp = api_client.list_capital_calls(ADMIN, params={"motion_id": motion_id})
    calls, _ = validate_paginated(resp)
    assert len(calls) == 1, f"Setup failed: expected 1 capital call for motion, got {len(calls)}"
    return calls[0]


def adopted_capital_call(
    sponsor: dict,
    amount_cents: int,
    due_date: str = DEFAULT_DUE_DATE,
    purpose: str = "General purposes",
    voters: Optional[list] = None,
):
    """Adopted CAPITAL_CALL motion + its APPROVED CapitalCall (PRD §3.4/§3.5)."""
    motion = adopt_motion_full(
        "CAPITAL_CALL",
        sponsor,
        capital_call_payload(amount_cents, due_date=due_date, purpose=purpose),
        voters or [sponsor],
    )
    assert motion["status"] == "ADOPTED", (
        f"Setup failed: CAPITAL_CALL motion closed as {motion['status']}"
    )
    return motion, capital_call_for_motion(motion["id"])


def bill_call(call_id: str) -> dict:
    resp = api_client.bill_capital_call(call_id, ADMIN)
    return get_success_data(resp)


def list_call_assessments(call_id: str):
    resp = api_client.list_call_assessments(call_id, ADMIN)
    return validate_paginated(resp)


def list_physician_assessments(physician_id: str):
    resp = api_client.list_physician_assessments(physician_id, ADMIN)
    return validate_paginated(resp)


def pay_assessment(assessment_id: str, amount_cents: int, physician: Optional[dict] = None) -> dict:
    headers = physician_headers(physician) if physician is not None else ADMIN
    resp = api_client.pay_assessment(assessment_id, pay_assessment_payload(amount_cents), headers)
    return get_success_data(resp)


def adopted_and_billed_call(
    sponsor: dict,
    amount_cents: int,
    due_date: str = DEFAULT_DUE_DATE,
    purpose: str = "General purposes",
    voters: Optional[list] = None,
):
    """Adopted CAPITAL_CALL motion + BILLED call + its assessments."""
    motion, call = adopted_capital_call(sponsor, amount_cents, due_date, purpose, voters)
    call = bill_call(call["id"])
    assessments, _ = list_call_assessments(call["id"])
    return motion, call, assessments


# --- Distributions (PRD §3.5) -------------------------------------------------


def get_distribution(distribution_id: str) -> dict:
    resp = api_client.get_distribution(distribution_id, ADMIN)
    return get_success_data(resp)


def distribution_for_motion(motion_id: str) -> dict:
    resp = api_client.list_distributions(ADMIN, params={"motion_id": motion_id})
    distributions, _ = validate_paginated(resp)
    assert len(distributions) == 1, (
        f"Setup failed: expected 1 distribution for motion, got {len(distributions)}"
    )
    return distributions[0]


def list_distributions(params: Optional[dict] = None):
    resp = api_client.list_distributions(ADMIN, params=params)
    return validate_paginated(resp)


def adopted_distribution(
    sponsor: dict,
    amount_cents: int,
    method: str = "PRO_RATA",
    fiscal_net_income_before_bonus_cents: int = 800000000,
    voters: Optional[list] = None,
):
    """Adopted DISTRIBUTION motion + its APPROVED Distribution (PRD §3.4/§3.5)."""
    motion = adopt_motion_full(
        "DISTRIBUTION",
        sponsor,
        distribution_payload(
            amount_cents,
            method=method,
            fiscal_net_income_before_bonus_cents=fiscal_net_income_before_bonus_cents,
        ),
        voters or [sponsor],
    )
    assert motion["status"] == "ADOPTED", (
        f"Setup failed: DISTRIBUTION motion closed as {motion['status']}"
    )
    return motion, distribution_for_motion(motion["id"])


def pay_allocation(distribution_id: str, physician_id: str) -> dict:
    resp = api_client.pay_allocation(distribution_id, physician_id, ADMIN)
    return get_success_data(resp)


def void_distribution(distribution_id: str) -> dict:
    resp = api_client.void_distribution(distribution_id, ADMIN)
    return get_success_data(resp)


# --- Exit valuations (PRD §3.6) -----------------------------------------------


def initiate_exit(physician_id: str, trigger_type: str = "VOLUNTARY") -> dict:
    resp = api_client.create_exit_valuation(
        create_exit_valuation_payload(physician_id, trigger_type), ADMIN
    )
    return get_success_data(resp)


def get_exit_valuation(valuation_id: str) -> dict:
    resp = api_client.get_exit_valuation(valuation_id, ADMIN)
    return get_success_data(resp)


def appraise_valuation(valuation: dict, appraised_practice_value_cents: int) -> dict:
    """Record an appraisal with OCC against the valuation's current version."""
    resp = api_client.appraise_exit_valuation(
        valuation["id"],
        appraise_payload(appraised_practice_value_cents, valuation["version"]),
        ADMIN,
    )
    return get_success_data(resp)


def dispute_valuation(valuation_id: str, physician: dict) -> dict:
    resp = api_client.dispute_exit_valuation(valuation_id, physician_headers(physician))
    return get_success_data(resp)


def arbitrate_valuation(valuation_id: str) -> dict:
    resp = api_client.arbitrate_exit_valuation(valuation_id, ADMIN)
    return get_success_data(resp)


def finalize_exit(valuation_id: str, motion_id: str) -> dict:
    resp = api_client.finalize_exit_valuation(
        valuation_id, finalize_payload(motion_id), ADMIN
    )
    return get_success_data(resp)


def adopt_buyout_approval(sponsor: dict, valuation_id: str, voters: Optional[list] = None) -> dict:
    """Adopted BUYOUT_APPROVAL motion naming the valuation (PRD §3.6)."""
    motion = adopt_motion_full(
        "BUYOUT_APPROVAL",
        sponsor,
        buyout_approval_payload(valuation_id),
        voters or [sponsor],
    )
    assert motion["status"] == "ADOPTED", (
        f"Setup failed: BUYOUT_APPROVAL motion closed as {motion['status']}"
    )
    return motion


def setup_appraised_valuation(
    exiting: dict,
    trigger_type: str = "VOLUNTARY",
    appraised_value_cents: int = 90000000,
) -> dict:
    """Exit initiated (SHAREHOLDER -> EXITING) then appraised to APPRAISED."""
    valuation = initiate_exit(exiting["id"], trigger_type)
    return appraise_valuation(valuation, appraised_value_cents)


def setup_finalized_exit(
    exiting: dict,
    sponsor: dict,
    trigger_type: str = "VOLUNTARY",
    appraised_value_cents: int = 90000000,
):
    """Full exit lifecycle: APPRAISED valuation + adopted BUYOUT_APPROVAL + finalize.
    Returns (valuation, approval_motion)."""
    valuation = setup_appraised_valuation(exiting, trigger_type, appraised_value_cents)
    motion = adopt_buyout_approval(sponsor, valuation["id"])
    finalized = finalize_exit(valuation["id"], motion["id"])
    return finalized, motion


# --- COI disclosures (PRD §3.7) -----------------------------------------------


def file_coi_disclosure(
    filer: dict, description: str = "Conflict disclosure", related_motion_id: Optional[str] = None
) -> dict:
    resp = api_client.create_coi_disclosure(
        create_coi_disclosure_payload(description, related_motion_id=related_motion_id),
        physician_headers(filer),
    )
    return get_success_data(resp)


def review_coi_disclosure(disclosure_id: str, outcome: str, review_note: Optional[str] = None) -> dict:
    """Review is exclusively a ComplianceOfficer act (PRD §3.7)."""
    resp = api_client.review_coi_disclosure(
        disclosure_id, review_coi_payload(outcome, review_note=review_note), COMPLIANCE
    )
    return get_success_data(resp)


def get_coi_disclosure(disclosure_id: str) -> dict:
    resp = api_client.get_coi_disclosure(disclosure_id, ADMIN)
    return get_success_data(resp)


# --- Merger proposals (PRD §3.8) ----------------------------------------------


def create_merger_proposal(**overrides) -> dict:
    resp = api_client.create_merger_proposal(create_merger_proposal_payload(**overrides), ADMIN)
    return get_success_data(resp)


def get_merger_proposal(proposal_id: str) -> dict:
    resp = api_client.get_merger_proposal(proposal_id, ADMIN)
    return get_success_data(resp)


def advance_merger(proposal_id: str, diligence_note: Optional[str] = None) -> dict:
    payload = {"diligence_note": diligence_note} if diligence_note is not None else {}
    resp = api_client.advance_merger_proposal(proposal_id, payload, ADMIN)
    return get_success_data(resp)


def decide_merger(proposal_id: str, outcome: str, motion_id: Optional[str] = None) -> dict:
    payload = {"outcome": outcome}
    if motion_id is not None:
        payload["motion_id"] = motion_id
    resp = api_client.decide_merger_proposal(proposal_id, payload, ADMIN)
    return get_success_data(resp)

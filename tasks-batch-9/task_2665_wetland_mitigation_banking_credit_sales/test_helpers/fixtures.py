"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: each test runs against an empty database.

The shared world these helpers build is a DEPRESSIONAL bank on site watershed
03130002 with a service area of ["03130002", "03130003"] and an annual
stewardship cost of 4,200,000 cents, whose approved work plan carries three
credit strata yielding 98.77 planned credits and four performance standards.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_EPOCH,
    RESERVATION_HOLD_DAYS,
    TEST_DEFAULTS,
)
from .factories import (
    CANONICAL_CREDIT_STRATA,
    CANONICAL_PERFORMANCE_STANDARDS,
    approve_release_payload,
    cancel_sale_payload,
    create_bank_payload,
    create_credit_sale_payload,
    create_deposit_payload,
    create_easement_payload,
    create_irt_member_payload,
    create_milestone_payload,
    create_monitoring_report_payload,
    create_permittee_payload,
    create_prospectus_payload,
    create_sponsor_payload,
    create_stewardship_contribution_payload,
    create_vote_payload,
    create_work_plan_payload,
    decide_work_plan_payload,
    inspect_payload,
    review_report_payload,
)
from .test_users import (
    make_irt_chair_headers,
    make_irt_member_headers,
    make_permittee_headers,
    make_program_admin_headers,
    make_sponsor_headers,
)

# Agencies seated in order: the USACE seat holds veto authority, the other two
# do not (PRD §3.1).
DEFAULT_AGENCIES = ["USACE", "EPA", "STATE_DEQ"]


# ─── Logical clock ────────────────────────────────────

def set_clock(to_iso8601: str) -> str:
    """Move the injectable logical clock. Returns the resulting current_utc."""
    data = get_success_data(
        api_client.set_clock(to_iso8601, make_program_admin_headers())
    )
    return data.get("current_utc", to_iso8601)


def reset_clock() -> str:
    """Return the clock to the instant it reads at process start."""
    return set_clock(CLOCK_EPOCH)


# ─── Tier 1: party registration ───────────────────────

def register_sponsor(**overrides) -> dict:
    """Register a sponsor. Returns the Sponsor resource."""
    return get_success_data(
        api_client.create_sponsor(
            create_sponsor_payload(**overrides), make_program_admin_headers()
        )
    )


def register_permittee(**overrides) -> dict:
    """Register a permit holder. Returns the Permittee resource."""
    return get_success_data(
        api_client.create_permittee(
            create_permittee_payload(**overrides), make_program_admin_headers()
        )
    )


def register_irt_member(agency: str = "USACE", **overrides) -> dict:
    """Seat one review-team member. Returns the IRTMember resource."""
    payload = create_irt_member_payload(
        agency=agency, member_name=f"{agency} Reviewer", **overrides
    )
    return get_success_data(
        api_client.create_irt_member(payload, make_program_admin_headers())
    )


def seat_review_team(agencies: Optional[List[str]] = None) -> List[dict]:
    """Seat one member per agency in the supplied order."""
    return [register_irt_member(agency=a) for a in (agencies or DEFAULT_AGENCIES)]


def deposit_escrow(permittee: dict, amount_cents: int) -> dict:
    """Lodge an escrow deposit as the permit holder itself."""
    return get_success_data(
        api_client.create_deposit(
            permittee["id"],
            create_deposit_payload(amount_cents),
            make_permittee_headers(permittee["id"]),
        )
    )


# ─── World accessors ──────────────────────────────────

def bank_state(world: dict) -> dict:
    """Re-read the bank through the single-resource read (the concurrency read)."""
    return get_success_data(
        api_client.get_bank(world["bank"]["id"], world["sponsor_headers"])
    )


def bank_version(world: dict) -> int:
    """The bank's current version, as the concurrency token requires it."""
    return bank_state(world)["version"]


def ledger_rows(world: dict, entry_type: Optional[str] = None) -> List[dict]:
    """The bank's append-only ledger ordered by sequence_number ascending."""
    params = {"limit": 100}
    if entry_type is not None:
        params["entry_type"] = entry_type
    body = api_client.list_bank_ledger(
        world["bank"]["id"], world["sponsor_headers"], params=params
    )
    return get_success_data(body)


def credit_forecast(world: dict) -> dict:
    return get_success_data(
        api_client.get_credit_forecast(world["bank"]["id"], world["sponsor_headers"])
    )


def permittee_state(world: dict, permittee_id: Optional[str] = None) -> dict:
    pid = permittee_id or world["permittee"]["id"]
    return get_success_data(
        api_client.get_permittee(pid, make_permittee_headers(pid))
    )


def milestone_state(milestone_id: str, world: dict) -> dict:
    return get_success_data(
        api_client.get_milestone(milestone_id, world["sponsor_headers"])
    )


def report_state(report_id: str, world: dict) -> dict:
    return get_success_data(
        api_client.get_monitoring_report(report_id, world["sponsor_headers"])
    )


def remedial_action_state(action_id: str, world: dict) -> dict:
    return get_success_data(
        api_client.get_remedial_action(action_id, world["sponsor_headers"])
    )


def sale_state(sale_id: str, world: dict) -> dict:
    return get_success_data(
        api_client.get_credit_sale(sale_id, world["sponsor_headers"])
    )


def remedial_actions_for_report(world: dict, report_id: str) -> List[dict]:
    return get_success_data(
        api_client.list_remedial_actions(
            world["sponsor_headers"], params={"monitoring_report_id": report_id, "limit": 100}
        )
    )


# ─── Tier 2: a bank site in DRAFT ─────────────────────

def setup_draft_bank(
    site_huc8_code: str = TEST_DEFAULTS["SITE_HUC8"],
    service_area_huc8_codes: Optional[List[str]] = None,
    hgm_class: str = TEST_DEFAULTS["HGM_CLASS"],
    annual_stewardship_cost_cents: int = TEST_DEFAULTS["ANNUAL_STEWARDSHIP_COST_CENTS"],
    sponsor_bond_cents: int = TEST_DEFAULTS["SPONSOR_BOND_CENTS"],
    agencies: Optional[List[str]] = None,
    permittee_required_credits: float = 12.00,
    permittee_impact_huc8_code: str = TEST_DEFAULTS["SITE_HUC8"],
    permittee_deposit_cents: Optional[int] = None,
    **bank_overrides,
) -> dict:
    """A registered sponsor, a seated review team, a permit holder and one bank
    site sitting in DRAFT. Returns the shared world dict every other helper
    threads through."""
    sponsor = register_sponsor(performance_bond_cents=sponsor_bond_cents)
    sponsor_headers = make_sponsor_headers(sponsor["id"])
    members = seat_review_team(agencies)
    permittee = register_permittee(
        required_credits=permittee_required_credits,
        impact_huc8_code=permittee_impact_huc8_code,
    )
    if permittee_deposit_cents:
        deposit_escrow(permittee, permittee_deposit_cents)
        permittee = get_success_data(
            api_client.get_permittee(
                permittee["id"], make_permittee_headers(permittee["id"])
            )
        )

    bank = get_success_data(
        api_client.create_bank(
            create_bank_payload(
                sponsor["id"],
                site_huc8_code=site_huc8_code,
                service_area_huc8_codes=list(
                    service_area_huc8_codes or TEST_DEFAULTS["SERVICE_AREA"]
                ),
                hgm_class=hgm_class,
                annual_stewardship_cost_cents=annual_stewardship_cost_cents,
                **bank_overrides,
            ),
            sponsor_headers,
        )
    )

    return {
        "sponsor": sponsor,
        "sponsor_headers": sponsor_headers,
        "permittee": permittee,
        "permittee_headers": make_permittee_headers(permittee["id"]),
        "members": members,
        "member_headers": [make_irt_member_headers(m["id"]) for m in members],
        "chair_headers": make_irt_chair_headers(),
        "admin_headers": make_program_admin_headers(),
        "bank": bank,
        "milestones": {},
        "reports": {},
    }


# ─── Tier 3: prospectus review and work plan approval ──

def draft_prospectus(world: dict, **overrides) -> dict:
    prospectus = get_success_data(
        api_client.create_prospectus(
            create_prospectus_payload(world["bank"]["id"], **overrides),
            world["sponsor_headers"],
        )
    )
    world["prospectus"] = prospectus
    return prospectus


def submit_prospectus(world: dict) -> dict:
    prospectus = get_success_data(
        api_client.submit_prospectus(
            world["prospectus"]["id"], world["sponsor_headers"]
        )
    )
    world["prospectus"] = prospectus
    return prospectus


def cast_votes(world: dict, positions: Optional[List[str]] = None) -> List[dict]:
    """Record one position per seated member, in roster order."""
    positions = positions or ["CONCUR", "CONCUR", "CONCUR"]
    votes = []
    for index, position in enumerate(positions):
        votes.append(
            get_success_data(
                api_client.create_prospectus_vote(
                    world["prospectus"]["id"],
                    create_vote_payload(position),
                    world["member_headers"][index],
                )
            )
        )
    return votes


def finalize_prospectus(world: dict) -> dict:
    prospectus = get_success_data(
        api_client.finalize_prospectus_review(
            world["prospectus"]["id"], world["chair_headers"]
        )
    )
    world["prospectus"] = prospectus
    return prospectus


def draft_work_plan(world: dict, **overrides) -> dict:
    work_plan = get_success_data(
        api_client.create_work_plan(
            create_work_plan_payload(world["bank"]["id"], **overrides),
            world["sponsor_headers"],
        )
    )
    world["work_plan"] = work_plan
    return work_plan


def submit_work_plan(world: dict) -> dict:
    work_plan = get_success_data(
        api_client.submit_work_plan(world["work_plan"]["id"], world["sponsor_headers"])
    )
    world["work_plan"] = work_plan
    return work_plan


def decide_work_plan(world: dict, decision: str = "APPROVE", **overrides) -> dict:
    work_plan = get_success_data(
        api_client.decide_work_plan(
            world["work_plan"]["id"],
            decide_work_plan_payload(decision, **overrides),
            world["chair_headers"],
        )
    )
    world["work_plan"] = work_plan
    return work_plan


def setup_bank_under_review(
    work_plan_state: str = "SUBMITTED",
    vote_positions: Optional[List[str]] = None,
    work_plan_overrides: Optional[dict] = None,
    **bank_kwargs,
) -> dict:
    """A bank dragged to PROSPECTUS_REVIEW by prospectus submission, with the
    prospectus UNDER_REVIEW once votes are cast and a work plan in the requested
    state. `work_plan_state` is one of "NONE", "DRAFT" or "SUBMITTED"."""
    world = setup_draft_bank(**bank_kwargs)
    draft_prospectus(world)
    submit_prospectus(world)
    if work_plan_state != "NONE":
        draft_work_plan(world, **(work_plan_overrides or {}))
        if work_plan_state == "SUBMITTED":
            submit_work_plan(world)
    if vote_positions is not None:
        cast_votes(world, vote_positions)
    return world


def setup_approved_prospectus_and_work_plan(
    work_plan_overrides: Optional[dict] = None, **bank_kwargs
) -> dict:
    """Carry a bank all the way to an APPROVED prospectus and an APPROVED work
    plan, so the four performance standards are materialised on the bank and the
    banking instrument may be executed."""
    world = setup_bank_under_review(
        work_plan_state="SUBMITTED", work_plan_overrides=work_plan_overrides, **bank_kwargs
    )
    cast_votes(world)
    finalize_prospectus(world)
    decide_work_plan(world, "APPROVE")
    return world


def setup_executed_bank(
    record_easement: bool = False,
    stewardship_funded_cents: int = 0,
    work_plan_overrides: Optional[dict] = None,
    **bank_kwargs,
) -> dict:
    """A bank in INSTRUMENT_EXECUTED, its authorised credit total copied from
    the approved work plan and its GENERATED ledger entry appended. Optionally
    records the conservation easement and funds the stewardship endowment."""
    world = setup_approved_prospectus_and_work_plan(
        work_plan_overrides=work_plan_overrides, **bank_kwargs
    )
    world["bank"] = get_success_data(
        api_client.execute_instrument(world["bank"]["id"], world["chair_headers"])
    )
    if record_easement:
        record_easement_on_bank(world)
    if stewardship_funded_cents:
        fund_stewardship(world, stewardship_funded_cents)
    return world


def record_easement_on_bank(world: dict, deed_reference: str = "BK 4821 PG 116") -> dict:
    world["bank"] = get_success_data(
        api_client.record_conservation_easement(
            world["bank"]["id"],
            create_easement_payload(deed_reference),
            world["sponsor_headers"],
        )
    )
    return world["bank"]


def fund_stewardship(world: dict, amount_cents: int) -> dict:
    world["bank"] = get_success_data(
        api_client.create_stewardship_contribution(
            world["bank"]["id"],
            create_stewardship_contribution_payload(amount_cents),
            world["sponsor_headers"],
        )
    )
    return world["bank"]


# ─── Tier 4: the release schedule ─────────────────────

def add_milestone(
    world: dict,
    milestone_code: str = "INSTRUMENT_EXECUTION",
    release_pct: float = 0.150,
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-09-01T00:00:00Z",
    predecessor_milestone_id: Optional[str] = None,
) -> dict:
    """Add one milestone to the bank's release schedule and record it in the
    world under its milestone_code."""
    milestone = get_success_data(
        api_client.create_milestone(
            create_milestone_payload(
                world["bank"]["id"],
                milestone_code=milestone_code,
                release_pct=release_pct,
                window_start=window_start,
                window_end=window_end,
                predecessor_milestone_id=predecessor_milestone_id,
            ),
            world["sponsor_headers"],
        )
    )
    world["milestones"][milestone_code] = milestone
    return milestone


def claim_milestone(world: dict, milestone_id: str) -> dict:
    milestone = get_success_data(
        api_client.claim_milestone(milestone_id, world["sponsor_headers"])
    )
    world["milestones"][milestone["milestone_code"]] = milestone
    return milestone


def approve_release(world: dict, milestone_id: str, member_index: int = 0) -> dict:
    """Approve a claimed milestone's release under the concurrency token read
    fresh from the bank."""
    milestone = get_success_data(
        api_client.approve_milestone_release(
            milestone_id,
            approve_release_payload(bank_version(world)),
            world["member_headers"][member_index],
        )
    )
    world["milestones"][milestone["milestone_code"]] = milestone
    world["bank"] = bank_state(world)
    return milestone


def release_milestone_fully(
    world: dict,
    milestone_code: str = "INSTRUMENT_EXECUTION",
    release_pct: float = 0.150,
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-09-01T00:00:00Z",
    predecessor_milestone_id: Optional[str] = None,
    member_index: int = 0,
) -> dict:
    """Add, claim and approve one milestone so its tranche of credits reaches
    the bank's available pool."""
    milestone = add_milestone(
        world,
        milestone_code=milestone_code,
        release_pct=release_pct,
        window_start=window_start,
        window_end=window_end,
        predecessor_milestone_id=predecessor_milestone_id,
    )
    claim_milestone(world, milestone["id"])
    return approve_release(world, milestone["id"], member_index=member_index)


# ─── Tier 4: monitoring ───────────────────────────────

def open_monitoring_report(
    world: dict,
    monitoring_year: int = 1,
    window_start: str = "2027-03-01T00:00:00Z",
    window_end: str = "2027-06-01T00:00:00Z",
    measurements_array: Optional[List[dict]] = None,
) -> dict:
    report = get_success_data(
        api_client.create_monitoring_report(
            create_monitoring_report_payload(
                world["bank"]["id"],
                monitoring_year=monitoring_year,
                window_start=window_start,
                window_end=window_end,
                measurements_array=measurements_array,
            ),
            world["sponsor_headers"],
        )
    )
    world["reports"][monitoring_year] = report
    return report


def submit_monitoring_report(world: dict, report_id: str) -> dict:
    report = get_success_data(
        api_client.submit_monitoring_report(report_id, world["sponsor_headers"])
    )
    world["reports"][report["monitoring_year"]] = report
    return report


def review_monitoring_report(
    world: dict,
    report_id: str,
    decision: str = "ACCEPT",
    member_index: int = 1,
    return_reason: Optional[str] = None,
) -> dict:
    payload = review_report_payload(decision)
    if return_reason is not None:
        payload["return_reason"] = return_reason
    report = get_success_data(
        api_client.review_monitoring_report(
            report_id, payload, world["member_headers"][member_index]
        )
    )
    world["reports"][report["monitoring_year"]] = report
    world["bank"] = bank_state(world)
    return report


def file_and_accept_monitoring_report(
    world: dict,
    monitoring_year: int = 1,
    window_start: str = "2027-03-01T00:00:00Z",
    window_end: str = "2027-06-01T00:00:00Z",
    measurements_array: Optional[List[dict]] = None,
    member_index: int = 1,
) -> dict:
    """Open, submit and accept one monitoring report, so it is scored."""
    report = open_monitoring_report(
        world,
        monitoring_year=monitoring_year,
        window_start=window_start,
        window_end=window_end,
        measurements_array=measurements_array,
    )
    submit_monitoring_report(world, report["id"])
    return review_monitoring_report(
        world, report["id"], "ACCEPT", member_index=member_index
    )


def submit_remedial_work(world: dict, action_id: str) -> dict:
    return get_success_data(
        api_client.submit_remedial_work(action_id, world["sponsor_headers"])
    )


def inspect_remedial_action(
    world: dict, action_id: str, outcome: str = "CLEARED", member_index: int = 2
) -> dict:
    action = get_success_data(
        api_client.inspect_remedial_action(
            action_id, inspect_payload(outcome), world["member_headers"][member_index]
        )
    )
    world["bank"] = bank_state(world)
    return action


# ─── Tier 5: the commercial layer ─────────────────────

def quote_credits(
    world: dict,
    credits_requested: float,
    impact_huc8_code: Optional[str] = None,
    permittee_id: Optional[str] = None,
    expected_bank_version: Optional[int] = None,
    as_sponsor: bool = False,
) -> dict:
    """Open a credit quote against the bank, pricing it from a fresh read of the
    bank's version."""
    pid = permittee_id or world["permittee"]["id"]
    payload = create_credit_sale_payload(
        world["bank"]["id"],
        pid,
        credits_requested,
        expected_bank_version if expected_bank_version is not None else bank_version(world),
        impact_huc8_code=impact_huc8_code or world["bank"]["site_huc8_code"],
    )
    headers = world["sponsor_headers"] if as_sponsor else make_permittee_headers(pid)
    sale = get_success_data(api_client.create_credit_sale(payload, headers))
    world["bank"] = bank_state(world)
    return sale


def reserve_sale(world: dict, sale_id: str, permittee_id: Optional[str] = None) -> dict:
    pid = permittee_id or world["permittee"]["id"]
    sale = get_success_data(
        api_client.reserve_credit_sale(sale_id, make_permittee_headers(pid))
    )
    world["bank"] = bank_state(world)
    return sale


def execute_sale(world: dict, sale_id: str) -> dict:
    sale = get_success_data(
        api_client.execute_credit_sale(sale_id, world["sponsor_headers"])
    )
    world["bank"] = bank_state(world)
    return sale


def assign_sale(world: dict, sale_id: str) -> dict:
    sale = get_success_data(
        api_client.assign_credit_sale(sale_id, world["sponsor_headers"])
    )
    world["bank"] = bank_state(world)
    return sale


def cancel_sale(
    world: dict,
    sale_id: str,
    cancelled_reason: str = "BUYER_WITHDREW",
    permittee_id: Optional[str] = None,
) -> dict:
    pid = permittee_id or world["permittee"]["id"]
    sale = get_success_data(
        api_client.cancel_credit_sale(
            sale_id, cancel_sale_payload(cancelled_reason), make_permittee_headers(pid)
        )
    )
    world["bank"] = bank_state(world)
    return sale


def reverse_sale(world: dict, sale_id: str) -> dict:
    sale = get_success_data(
        api_client.reverse_credit_sale(sale_id, world["chair_headers"])
    )
    world["bank"] = bank_state(world)
    return sale


def sell_credits_end_to_end(
    world: dict,
    credits_requested: float,
    impact_huc8_code: Optional[str] = None,
) -> dict:
    """Quote, reserve and settle one sale. Returns the EXECUTED sale."""
    sale = quote_credits(
        world, credits_requested, impact_huc8_code=impact_huc8_code
    )
    reserve_sale(world, sale["id"])
    return execute_sale(world, sale["id"])


# ─── Tier 5: the canonical sellable bank ──────────────

def setup_sellable_bank(
    stewardship_funded_cents: int = TEST_DEFAULTS["STEWARDSHIP_INTERIM_GATE_CENTS"],
    record_easement: bool = True,
    first_release_pct: float = 0.150,
    release_first_milestone: bool = True,
    permittee_deposit_cents: Optional[int] = None,
    permittee_required_credits: float = 12.00,
    **bank_kwargs,
) -> dict:
    """The shared world every commercial test starts from: a bank in
    INSTRUMENT_EXECUTED with its easement recorded, its stewardship endowment at
    the interim gate, its authorised total at 98.77 credits and its
    INSTRUMENT_EXECUTION milestone released so 14.82 credits sit available and
    the sales posture reads OPEN."""
    world = setup_executed_bank(
        record_easement=record_easement,
        stewardship_funded_cents=stewardship_funded_cents,
        permittee_deposit_cents=permittee_deposit_cents,
        permittee_required_credits=permittee_required_credits,
        **bank_kwargs,
    )
    if release_first_milestone:
        release_milestone_fully(
            world,
            milestone_code="INSTRUMENT_EXECUTION",
            release_pct=first_release_pct,
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-09-01T00:00:00Z",
        )
    world["bank"] = bank_state(world)
    return world


def setup_sellable_bank_with_second_milestone(
    second_release_pct: float = 0.200,
    claim_second: bool = True,
    clock: str = "2027-09-15T00:00:00Z",
    **kwargs,
) -> dict:
    """A sellable bank whose CONSTRUCTION_COMPLETE milestone is chained behind
    the released INSTRUMENT_EXECUTION milestone, with the clock advanced far
    enough for its window to be open."""
    world = setup_sellable_bank(**kwargs)
    predecessor = world["milestones"].get("INSTRUMENT_EXECUTION")
    add_milestone(
        world,
        milestone_code="CONSTRUCTION_COMPLETE",
        release_pct=second_release_pct,
        window_start="2027-09-01T00:00:00Z",
        window_end="2027-10-01T00:00:00Z",
        predecessor_milestone_id=predecessor["id"] if predecessor else None,
    )
    set_clock(clock)
    if claim_second:
        claim_milestone(world, world["milestones"]["CONSTRUCTION_COMPLETE"]["id"])
    world["bank"] = bank_state(world)
    return world


def setup_monitoring_ready_bank(
    record_easement: bool = True,
    stewardship_funded_cents: int = TEST_DEFAULTS["STEWARDSHIP_INTERIM_GATE_CENTS"],
    **bank_kwargs,
) -> dict:
    """A bank in INSTRUMENT_EXECUTED whose four performance standards have been
    materialised from the approved work plan, with no milestone on its schedule
    at all — the starting point for monitoring-window and scoring tests."""
    return setup_executed_bank(
        record_easement=record_easement,
        stewardship_funded_cents=stewardship_funded_cents,
        **bank_kwargs,
    )


def performance_standards(world: dict) -> List[dict]:
    """The materialised standards of the bank, ordered by effective year then
    standard code."""
    return get_success_data(
        api_client.list_bank_performance_standards(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 100}
        )
    )


__all__ = [name for name in dir() if not name.startswith("_")]

"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked through 5-15 API calls to
reach the testable state (open program -> policy -> election -> unit -> acreage
report -> claim -> submit -> ...). These helpers encapsulate those chains so tests
focus on assertions.

Identity threading is mandatory: the selling Agent and the LossAdjuster are both
entity_backed:Agent. Every ownership / assignment / segregation-gated call uses
make_agent_headers(sa_id) or make_lossadjuster_headers(adj_id) with the real Agent
id, never the shared TEST_USERS fallback.

Setup uses get_success_data() (lenient) so a setup misstep surfaces as a clear
"setup failed" rather than a confusing downstream assertion.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_agent_payload, create_producer_payload, create_commodity_program_payload,
    create_policy_payload, create_coverage_election_payload, create_unit_payload,
    create_acreage_report_payload, create_loss_claim_payload, create_pp_claim_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS, make_rma_admin_headers, make_agent_headers, make_lossadjuster_headers,
)

ADMIN = TEST_USERS["rma_admin_headers"]


# ─── Tier 0: identity + program setup ─────────────────────────────────────

def register_selling_agent(name="Sales Agent", license_number="SA-1"):
    res = api_client.create_agent(
        create_agent_payload(role_kind="SELLING", name=name, license_number=license_number),
        ADMIN)
    return get_success_data(res)


def register_adjuster(name="Adjuster", license_number="ADJ-1"):
    res = api_client.create_agent(
        create_agent_payload(role_kind="ADJUSTING", name=name, license_number=license_number),
        ADMIN)
    return get_success_data(res)


def register_producer(name="Producer", tax_id="TX-1"):
    res = api_client.create_producer(create_producer_payload(name=name, tax_id=tax_id), ADMIN)
    return get_success_data(res)


def set_clock(iso8601):
    return api_client.set_clock(set_clock_payload(iso8601), ADMIN)


def create_program(status="OPEN", publish_harvest=None, **program_overrides):
    """Create a CommodityProgram, optionally OPEN/CLOSED, optionally publishing harvest.

    status: 'DRAFT' (just created), 'OPEN' (opened), or 'CLOSED' (opened then closed).
    publish_harvest: if not None, publish that harvest price (program must be opened).
    Returns the program dict (final state read back).
    """
    prog = get_success_data(api_client.create_commodity_program(
        create_commodity_program_payload(**program_overrides), ADMIN))
    if status in ("OPEN", "CLOSED"):
        api_client.open_commodity_program(prog["id"], ADMIN)
    if publish_harvest is not None:
        api_client.publish_harvest_price(prog["id"], {"harvest_price": publish_harvest}, ADMIN)
    if status == "CLOSED":
        api_client.close_commodity_program(prog["id"], ADMIN)
    return get_success_data(api_client.get_commodity_program(prog["id"], ADMIN))


# ─── Tier 1: policy + election (DRAFT policy, ELECTED election) ────────────

def setup_program_and_parties(publish_harvest=None, clock=None, **program_overrides):
    """Register selling agent, adjuster, producer; create an OPEN program.

    Returns dict with keys: sa, adj, producer, program, sa_headers, adj_headers.
    """
    sa = register_selling_agent()
    adj = register_adjuster()
    producer = register_producer()
    program = create_program(status="OPEN", publish_harvest=publish_harvest, **program_overrides)
    if clock is not None:
        set_clock(clock)
    return {
        "sa": sa,
        "adj": adj,
        "producer": producer,
        "program": program,
        "sa_headers": make_agent_headers(sa["id"]),
        "adj_headers": make_lossadjuster_headers(adj["id"]),
    }


def create_policy(producer_id, agent_id, sa_headers, crop_year=2026):
    res = api_client.create_policy(
        create_policy_payload(producer_id, agent_id, crop_year=crop_year), sa_headers)
    return get_success_data(res)


def create_election(policy_id, program_id, sa_headers, plan_type="YP",
                    aph_yield=180, coverage_level=0.75):
    res = api_client.create_coverage_election(
        create_coverage_election_payload(
            policy_id, program_id, plan_type=plan_type,
            aph_yield=aph_yield, coverage_level=coverage_level),
        sa_headers)
    return get_success_data(res)


def add_unit(election_id, sa_headers, unit_number="0001-0001", acres=100, share=1):
    res = api_client.create_unit(
        create_unit_payload(election_id, unit_number=unit_number, acres=acres, share=share),
        sa_headers)
    return get_success_data(res)


def setup_policy_with_election(plan_type="YP", aph_yield=180, coverage_level=0.75,
                              publish_harvest=None, clock=None, **program_overrides):
    """OPEN program + DRAFT policy + one ELECTED election (no units yet).

    Returns dict adding: policy, election (to the setup_program_and_parties keys).
    """
    ctx = setup_program_and_parties(publish_harvest=publish_harvest, clock=clock,
                                    **program_overrides)
    ctx["policy"] = create_policy(ctx["producer"]["id"], ctx["sa"]["id"], ctx["sa_headers"])
    ctx["election"] = create_election(
        ctx["policy"]["id"], ctx["program"]["id"], ctx["sa_headers"],
        plan_type=plan_type, aph_yield=aph_yield, coverage_level=coverage_level)
    return ctx


def setup_election_with_unit(plan_type="YP", aph_yield=180, coverage_level=0.75,
                             acres=100, share=1, publish_harvest=None, clock=None,
                             **program_overrides):
    """OPEN program + DRAFT policy + ELECTED election + one PENDING unit.

    Returns dict adding: unit (to setup_policy_with_election keys).
    """
    ctx = setup_policy_with_election(
        plan_type=plan_type, aph_yield=aph_yield, coverage_level=coverage_level,
        publish_harvest=publish_harvest, clock=clock, **program_overrides)
    ctx["unit"] = add_unit(ctx["election"]["id"], ctx["sa_headers"], acres=acres, share=share)
    return ctx


# ─── Tier 2: acreage report -> REPORTED unit ──────────────────────────────

def file_acreage_report(unit_id, sa_headers, expected_unit_version,
                        planted_acres=100, prevented_acres=0,
                        planting_date="2026-05-10T00:00:00Z"):
    res = api_client.create_acreage_report(
        create_acreage_report_payload(
            unit_id, expected_unit_version,
            planted_acres=planted_acres, prevented_acres=prevented_acres,
            planting_date=planting_date),
        sa_headers)
    return get_success_data(res)


def setup_reported_unit(plan_type="YP", aph_yield=180, coverage_level=0.75,
                        acres=100, share=1, planted_acres=100, prevented_acres=0,
                        publish_harvest=None, clock="2026-06-01T00:00:00Z",
                        **program_overrides):
    """OPEN program + policy + election + unit walked through to REPORTED.

    The acreage report is filed with the unit's freshly-minted version (1) and a
    clock set before the deadline. Returns dict adding: report (REPORTED unit, with
    the election bubbled to REPORTED since this is its only unit).
    """
    ctx = setup_election_with_unit(
        plan_type=plan_type, aph_yield=aph_yield, coverage_level=coverage_level,
        acres=acres, share=share, publish_harvest=publish_harvest, clock=clock,
        **program_overrides)
    ctx["report"] = file_acreage_report(
        ctx["unit"]["id"], ctx["sa_headers"], ctx["unit"]["version"],
        planted_acres=planted_acres, prevented_acres=prevented_acres)
    ctx["unit"] = get_success_data(api_client.get_unit(ctx["unit"]["id"], ctx["sa_headers"]))
    ctx["election"] = get_success_data(
        api_client.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    return ctx


# ─── Tier 3: loss-claim lifecycle ─────────────────────────────────────────

def file_loss_claim(unit_id, adjuster_id, sa_headers, production_to_count_bu=10000):
    res = api_client.create_loss_claim(
        create_loss_claim_payload(unit_id, adjuster_id,
                                  production_to_count_bu=production_to_count_bu),
        sa_headers)
    return get_success_data(res)


def setup_submitted_loss_claim(plan_type="YP", aph_yield=180, coverage_level=0.75,
                               acres=100, share=1, production_to_count_bu=10000,
                               publish_harvest=5.20, clock="2026-06-01T00:00:00Z",
                               **program_overrides):
    """Full chain through a LossClaim in UNDER_REVIEW (submitted to the adjuster).

    Returns dict adding: claim (UNDER_REVIEW) to setup_reported_unit keys.
    """
    ctx = setup_reported_unit(
        plan_type=plan_type, aph_yield=aph_yield, coverage_level=coverage_level,
        acres=acres, share=share, publish_harvest=publish_harvest, clock=clock,
        **program_overrides)
    claim = file_loss_claim(ctx["unit"]["id"], ctx["adj"]["id"], ctx["sa_headers"],
                            production_to_count_bu=production_to_count_bu)
    api_client.submit_loss_claim(claim["id"], ctx["sa_headers"])
    ctx["claim"] = get_success_data(api_client.get_loss_claim(claim["id"], ctx["sa_headers"]))
    return ctx


def setup_approved_loss_claim(plan_type="YP", production_to_count_bu=10000,
                              publish_harvest=5.20, **kwargs):
    """LossClaim walked through to APPROVED by the assigned adjuster.

    Returns dict adding: approve_response (the approve call's data).
    """
    ctx = setup_submitted_loss_claim(
        plan_type=plan_type, production_to_count_bu=production_to_count_bu,
        publish_harvest=publish_harvest, **kwargs)
    res = api_client.approve_loss_claim(ctx["claim"]["id"], ctx["adj_headers"])
    ctx["approve_response"] = get_success_data(res)
    ctx["claim"] = get_success_data(
        api_client.get_loss_claim(ctx["claim"]["id"], ctx["sa_headers"]))
    return ctx


# ─── Tier 4: prevented-planting claim lifecycle ───────────────────────────

def file_pp_claim(unit_id, sa_headers, claimed_prevented_acres, cause="EXCESS_MOISTURE"):
    res = api_client.create_pp_claim(
        create_pp_claim_payload(unit_id, claimed_prevented_acres, cause=cause), sa_headers)
    return get_success_data(res)


def setup_submitted_pp_claim(coverage_level=0.75, acres=100, share=1,
                             planted_acres=0, prevented_acres=30,
                             claimed_prevented_acres=30, cause="FLOOD",
                             clock="2026-06-01T00:00:00Z", **program_overrides):
    """Chain to a PreventedPlantingClaim in UNDER_REVIEW.

    The acreage report records `prevented_acres`; the PP claim claims
    `claimed_prevented_acres` and is submitted. Returns dict adding: pp_claim.
    """
    ctx = setup_reported_unit(
        plan_type="YP", coverage_level=coverage_level, acres=acres, share=share,
        planted_acres=planted_acres, prevented_acres=prevented_acres,
        clock=clock, **program_overrides)
    pp = file_pp_claim(ctx["unit"]["id"], ctx["sa_headers"], claimed_prevented_acres, cause=cause)
    api_client.submit_pp_claim(pp["id"], ctx["sa_headers"])
    ctx["pp_claim"] = get_success_data(api_client.get_pp_claim(pp["id"], ctx["sa_headers"]))
    return ctx


# ─── Tier 5: activated policy / commission ────────────────────────────────

def setup_activated_policy(plan_type="RP", aph_yield=180, coverage_level=0.75,
                           acres=100, share=1, base_premium_rate=0.085,
                           **program_overrides):
    """OPEN program + policy + election + unit, then policy ACTIVE (commission EARNED).

    Returns dict adding: activate_response, commission (the election's commission).
    No acreage report is filed, so the unit remains PENDING.
    """
    ctx = setup_election_with_unit(
        plan_type=plan_type, aph_yield=aph_yield, coverage_level=coverage_level,
        acres=acres, share=share, base_premium_rate=base_premium_rate, **program_overrides)
    res = api_client.activate_policy(ctx["policy"]["id"], ctx["sa_headers"])
    ctx["activate_response"] = get_success_data(res)
    ctx["policy"] = get_success_data(api_client.get_policy(ctx["policy"]["id"], ctx["sa_headers"]))
    ctx["election"] = get_success_data(
        api_client.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    comms = get_success_data(api_client.list_agent_commissions(
        ctx["sa_headers"], params={"coverage_election_id": ctx["election"]["id"]}))
    ctx["commission"] = comms[0] if comms else None
    return ctx

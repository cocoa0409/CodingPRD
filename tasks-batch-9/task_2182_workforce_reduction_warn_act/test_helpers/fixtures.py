"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD declares.  Setup calls
use the lenient validator so a broken precondition reports as "Setup failed"
rather than as a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    ALICE,
    BEN,
    BEN_CLASS_B,
    FEDERAL_NOTICE_CONTENT,
    NY_NOTICE_CONTENT,
    STANDARD_SCORES,
    create_employee_payload,
    create_reduction_plan_payload,
    create_selection_payload,
    create_site_payload,
    federal_rule_payload,
    ny_state_rule_payload,
    roster_import_payload,
    selection_batch_payload,
    warn_notice_payload,
)
from .test_users import (
    TEST_USERS,
    USER_IDS,
    make_benefits_headers,
    make_counsel_headers,
    make_lead_headers,
    make_separating_employee_headers,
)

LEAD = TEST_USERS["lead_headers"]
LEAD_2 = TEST_USERS["lead_2_headers"]
COUNSEL = TEST_USERS["counsel_headers"]
COUNSEL_2 = TEST_USERS["counsel_2_headers"]
BENEFITS = TEST_USERS["benefits_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-step wrappers around one endpoint each
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock and return the reported current_utc payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def configure_federal_rule(**overrides) -> dict:
    return get_success_data(
        api_client.create_warn_rule(federal_rule_payload(**overrides), ADMIN)
    )


def configure_ny_state_rule(**overrides) -> dict:
    return get_success_data(
        api_client.create_warn_rule(ny_state_rule_payload(**overrides), ADMIN)
    )


def configure_rule(payload: dict) -> dict:
    return get_success_data(api_client.create_warn_rule(payload, ADMIN))


def create_site(**overrides) -> dict:
    return get_success_data(
        api_client.create_site(create_site_payload(**overrides), LEAD)
    )


def hire(site_id: str, template: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_employee(
            create_employee_payload(site_id, template, **overrides), LEAD
        )
    )


def import_roster(site_id: str, templates) -> list:
    """Bulk-load a roster and return the created Employee records in the order
    the entries were supplied."""
    data = get_success_data(
        api_client.roster_import(site_id, roster_import_payload(templates), LEAD)
    )
    return [read_employee(eid) for eid in data["employee_ids"]]


def create_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_reduction_plan(
            create_reduction_plan_payload(**overrides), LEAD
        )
    )


def lock_criteria(plan_id: str) -> dict:
    return get_success_data(api_client.lock_criteria(plan_id, LEAD))


def create_locked_plan(**overrides) -> dict:
    """Open a plan and freeze its documented criteria."""
    plan = create_plan(**overrides)
    return lock_criteria(plan["id"])


def propose(plan_id: str, employee_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_selection(
            create_selection_payload(plan_id, employee_id, **overrides), LEAD
        )
    )


def propose_batch(plan_id: str, employee_ids, **overrides) -> dict:
    return get_success_data(
        api_client.selection_batch(
            plan_id, selection_batch_payload(employee_ids, **overrides), LEAD
        )
    )


def decide(selection_id: str, decision: str, exemption_reason: str = None) -> dict:
    payload = {"decision": decision}
    if exemption_reason is not None:
        payload["exemption_reason"] = exemption_reason
    return get_success_data(
        api_client.decide_selection(selection_id, payload, LEAD)
    )


def decide_many(
    plan_id: str, selection_ids, decision: str, exemption_reason: str = None
) -> dict:
    payload = {"selection_ids": list(selection_ids), "decision": decision}
    if exemption_reason is not None:
        payload["exemption_reason"] = exemption_reason
    return get_success_data(api_client.decide_batch(plan_id, payload, LEAD))


def rescind(selection_id: str, reason: str) -> dict:
    return get_success_data(
        api_client.rescind_selection(selection_id, {"rescind_reason": reason}, LEAD)
    )


def deliver_notice(
    selection_id: str, script_code: str = "MANAGER_SCRIPT_STANDARD", ack: bool = None
) -> dict:
    payload = {"script_code": script_code}
    if ack is not None:
        payload["acknowledge_short_notice"] = ack
    return get_success_data(api_client.deliver_notice(selection_id, payload, LEAD))


def run_analysis(plan_id: str, method: str = "IMPACT_RATIO") -> dict:
    """Create an analysis, reading the plan's current version for the guard."""
    plan = read_plan(plan_id)
    return get_success_data(
        api_client.create_analysis(
            {
                "plan_id": plan_id,
                "method": method,
                "expected_plan_version": plan["version"],
            },
            COUNSEL,
        )
    )


def clear_analysis(
    analysis_id: str,
    justification: str = "Documented business necessity.",
    counsel_id: str = USER_IDS["COUNSEL"],
) -> dict:
    return get_success_data(
        api_client.clear_analysis(
            analysis_id,
            {"justification": justification},
            make_counsel_headers(counsel_id),
        )
    )


def run_and_clear_analysis(
    plan_id: str,
    method: str = "IMPACT_RATIO",
    justification: str = "Documented business necessity.",
) -> dict:
    analysis = run_analysis(plan_id, method)
    return clear_analysis(analysis["id"], justification)


def submit_for_review(plan_id: str, lead_id: str = USER_IDS["LEAD"]) -> dict:
    return get_success_data(
        api_client.submit_legal_review(plan_id, make_lead_headers(lead_id))
    )


def render_legal_decision(
    plan_id: str,
    decision: str = "APPROVE",
    counsel_id: str = USER_IDS["COUNSEL"],
    comment: str = None,
) -> dict:
    payload = {"decision": decision}
    if comment is not None:
        payload["comment"] = comment
    return get_success_data(
        api_client.legal_decision(plan_id, payload, make_counsel_headers(counsel_id))
    )


def generate_disclosure(plan_id: str) -> dict:
    return get_success_data(
        api_client.create_disclosure({"plan_id": plan_id}, COUNSEL)
    )


def draft_warn_notice(plan_id, site_id, jurisdiction, content_codes) -> dict:
    return get_success_data(
        api_client.create_warn_notice(
            warn_notice_payload(plan_id, site_id, jurisdiction, content_codes),
            COUNSEL,
        )
    )


def issue_warn_notice(notice_id: str) -> dict:
    return get_success_data(api_client.issue_warn_notice(notice_id, COUNSEL))


def price_offer(selection_id: str, variant: str = "STANDARD") -> dict:
    """Price a severance offer, reading the selection's current version for the
    optimistic-concurrency guard."""
    selection = read_selection(selection_id)
    return get_success_data(
        api_client.create_severance_offer(
            {
                "selection_id": selection_id,
                "variant": variant,
                "expected_selection_version": selection["version"],
            },
            BENEFITS,
        )
    )


def issue_offer(offer_id: str) -> dict:
    return get_success_data(api_client.issue_severance_offer(offer_id, BENEFITS))


def sign_offer(offer_id: str, employee_id: str) -> dict:
    return get_success_data(
        api_client.sign_severance_offer(
            offer_id, make_separating_employee_headers(employee_id)
        )
    )


def revoke_offer(offer_id: str, employee_id: str, reason: str = "Reconsidered the release.") -> dict:
    return get_success_data(
        api_client.revoke_severance_offer(
            offer_id,
            {"revocation_reason": reason},
            make_separating_employee_headers(employee_id),
        )
    )


def execute_plan(plan_id: str) -> dict:
    return get_success_data(api_client.execute_plan(plan_id, LEAD))


def waive_restriction(
    restriction_id: str, reason: str, counsel_id: str = USER_IDS["COUNSEL"]
) -> dict:
    return get_success_data(
        api_client.waive_position_restriction(
            restriction_id, {"waiver_reason": reason}, make_counsel_headers(counsel_id)
        )
    )


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------
def read_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_reduction_plan(plan_id, LEAD))


def read_site(site_id: str) -> dict:
    return get_success_data(api_client.get_site(site_id, LEAD))


def read_employee(employee_id: str) -> dict:
    return get_success_data(api_client.get_employee(employee_id, LEAD))


def read_selection(selection_id: str) -> dict:
    return get_success_data(api_client.get_selection(selection_id, LEAD))


def read_analysis(analysis_id: str) -> dict:
    return get_success_data(api_client.get_analysis(analysis_id, COUNSEL))


def read_disclosure(disclosure_id: str) -> dict:
    return get_success_data(api_client.get_disclosure(disclosure_id, COUNSEL))


def read_warn_notice(notice_id: str) -> dict:
    return get_success_data(api_client.get_warn_notice(notice_id, COUNSEL))


def read_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_severance_offer(offer_id, BENEFITS))


def read_restriction(restriction_id: str) -> dict:
    return get_success_data(
        api_client.get_position_restriction(restriction_id, COUNSEL)
    )


def list_restrictions(**params) -> list:
    return get_success_data(
        api_client.list_position_restrictions(COUNSEL, params=params or None)
    )


def list_offers(**params) -> list:
    return get_success_data(
        api_client.list_severance_offers(BENEFITS, params=params or None)
    )


def list_selections(**params) -> list:
    return get_success_data(api_client.list_selections(LEAD, params=params or None))


def list_analyses(**params) -> list:
    return get_success_data(api_client.list_analyses(COUNSEL, params=params or None))


def list_warn_notices(**params) -> list:
    return get_success_data(
        api_client.list_warn_notices(COUNSEL, params=params or None)
    )


# ---------------------------------------------------------------------------
# Tier 1: site + roster + a plan whose criteria are frozen
# ---------------------------------------------------------------------------
def setup_site_with_roster(people=(ALICE, BEN), state_code="TX", site_name=None):
    """Register one site of employment and bulk-load its roster."""
    if site_name is None:
        site_name = "NY HQ" if state_code == "NY" else "Austin Campus"
    site = create_site(name=site_name, state_code=state_code)
    employees = import_roster(site["id"], people)
    return site, employees


def setup_scenario(
    people=(ALICE, BEN),
    state_code="TX",
    site_name=None,
    rules=(),
    budget=20000000,
    plan_name="Austin Reduction",
    decisional_unit_name="Austin Operations",
    propose_indexes=(0,),
    separation_date="2026-12-01",
    via_batch=False,
    criterion_scores=None,
):
    """A site of employment, its roster, a plan with LOCKED criteria and one
    PROPOSED selection per listed roster index.

    Returns a dict with keys: site, employees, plan, selections (in the order
    the indexes were supplied) and rules.
    """
    created_rules = [configure_rule(dict(r)) for r in rules]
    site, employees = setup_site_with_roster(people, state_code, site_name)
    plan = create_locked_plan(
        name=plan_name,
        decisional_unit_name=decisional_unit_name,
        severance_budget_cents=budget,
    )
    scores = criterion_scores if criterion_scores is not None else STANDARD_SCORES
    selections = []
    if propose_indexes:
        if via_batch:
            batch = propose_batch(
                plan["id"],
                [employees[i]["id"] for i in propose_indexes],
                proposed_separation_date=separation_date,
                criterion_scores=scores,
            )
            selections = [read_selection(sid) for sid in batch["selection_ids"]]
        else:
            for i in propose_indexes:
                selections.append(
                    propose(
                        plan["id"],
                        employees[i]["id"],
                        proposed_separation_date=separation_date,
                        criterion_scores=scores,
                    )
                )
    return {
        "site": site,
        "employees": employees,
        "plan": read_plan(plan["id"]),
        "selections": selections,
        "rules": created_rules,
    }


# ---------------------------------------------------------------------------
# Tier 2: resolve the selection fork
# ---------------------------------------------------------------------------
def setup_selected_scenario(
    people=(ALICE, BEN),
    state_code="TX",
    rules=(),
    budget=20000000,
    separation_date="2026-12-01",
    select_indexes=(0,),
    exempt_indexes=(),
    propose_only_indexes=(),
    via_batch=False,
    exemption_reason="Retained for critical skills.",
    **scenario_kwargs,
):
    """Everything setup_scenario builds, with the listed proposals resolved to
    the selected branch (and optionally others to the exempted branch).

    ``propose_only_indexes`` names proposals that are created and then left
    PROPOSED.  They join the plan's analysis pool without moving any employee,
    any site counter or the plan's selected_count.
    """
    propose_indexes = (
        tuple(select_indexes) + tuple(exempt_indexes) + tuple(propose_only_indexes)
    )
    scn = setup_scenario(
        people=people,
        state_code=state_code,
        rules=rules,
        budget=budget,
        propose_indexes=propose_indexes,
        separation_date=separation_date,
        via_batch=via_batch,
        **scenario_kwargs,
    )
    # selections[] came back in the order propose_indexes listed them.
    by_index = dict(zip(propose_indexes, scn["selections"]))
    if select_indexes:
        ids = [by_index[i]["id"] for i in select_indexes]
        if via_batch:
            decide_many(scn["plan"]["id"], ids, "SELECT")
        else:
            for sid in ids:
                decide(sid, "SELECT")
    if exempt_indexes:
        ids = [by_index[i]["id"] for i in exempt_indexes]
        if via_batch:
            decide_many(scn["plan"]["id"], ids, "EXEMPT", exemption_reason)
        else:
            for sid in ids:
                decide(sid, "EXEMPT", exemption_reason)
    scn["selection_by_index"] = {i: read_selection(s["id"]) for i, s in by_index.items()}
    scn["selections"] = [scn["selection_by_index"][i] for i in propose_indexes]
    scn["plan"] = read_plan(scn["plan"]["id"])
    scn["site"] = read_site(scn["site"]["id"])
    return scn


# ---------------------------------------------------------------------------
# Tier 3: legal clearance and governance approval
# ---------------------------------------------------------------------------
def setup_approved_scenario(
    method="IMPACT_RATIO",
    justification="Documented business necessity.",
    lead_id=USER_IDS["LEAD"],
    counsel_id=USER_IDS["COUNSEL"],
    **selected_kwargs,
):
    """A selected scenario carried through a CLEARED analysis, legal submission
    and counsel's approval.

    The default roster pairs one CLASS_A person, who is selected, with one
    CLASS_B person whose proposal stays PROPOSED, because an analysis over a
    single-class pool leaves no reference group and is refused outright.
    """
    selected_kwargs.setdefault("people", (ALICE, BEN_CLASS_B))
    selected_kwargs.setdefault("propose_only_indexes", (1,))
    scn = setup_selected_scenario(**selected_kwargs)
    scn["analysis"] = run_and_clear_analysis(
        scn["plan"]["id"], method=method, justification=justification
    )
    submit_for_review(scn["plan"]["id"], lead_id)
    render_legal_decision(scn["plan"]["id"], "APPROVE", counsel_id)
    scn["plan"] = read_plan(scn["plan"]["id"])
    return scn


# ---------------------------------------------------------------------------
# Tier 4: the five gates that precede pricing
# ---------------------------------------------------------------------------
def setup_offer_ready_scenario(
    notify_indexes=(0,),
    script_code="MANAGER_SCRIPT_STANDARD",
    acknowledge_short_notice=None,
    with_disclosure=True,
    **approved_kwargs,
):
    """An APPROVED plan with an ATTACHED disclosure and the individual notice
    delivered, i.e. every gate that precedes severance pricing satisfied."""
    scn = setup_approved_scenario(**approved_kwargs)
    if with_disclosure:
        scn["disclosure"] = generate_disclosure(scn["plan"]["id"])
    for i in notify_indexes:
        deliver_notice(
            scn["selection_by_index"][i]["id"], script_code, acknowledge_short_notice
        )
    scn["selection_by_index"] = {
        i: read_selection(s["id"]) for i, s in scn["selection_by_index"].items()
    }
    scn["plan"] = read_plan(scn["plan"]["id"])
    scn["site"] = read_site(scn["site"]["id"])
    return scn


def setup_priced_offer_scenario(
    offer_index=0, variant="STANDARD", **offer_ready_kwargs
):
    """An offer-ready scenario with one severance offer priced and sitting in
    DRAFT."""
    scn = setup_offer_ready_scenario(**offer_ready_kwargs)
    scn["offer"] = price_offer(
        scn["selection_by_index"][offer_index]["id"], variant
    )
    scn["plan"] = read_plan(scn["plan"]["id"])
    return scn


def setup_issued_offer_scenario(**priced_kwargs):
    """A priced offer that has been issued, so its cost is reserved against the
    plan budget."""
    scn = setup_priced_offer_scenario(**priced_kwargs)
    scn["offer"] = issue_offer(scn["offer"]["id"])
    scn["plan"] = read_plan(scn["plan"]["id"])
    return scn


# ---------------------------------------------------------------------------
# Tier 5: WARN-triggered sites, execution and the vacated-seat freeze
# ---------------------------------------------------------------------------
def setup_ny_triggered_scenario(
    people=None,
    select_indexes=(0, 2),
    separation_date="2026-12-01",
    budget=20000000,
):
    """A New York site carrying two selected losses, which crosses the NY
    mini-WARN threshold while leaving the federal one unmet."""
    from .factories import CARLA

    if people is None:
        people = (ALICE, BEN, CARLA)
    return setup_selected_scenario(
        people=people,
        state_code="NY",
        rules=(federal_rule_payload(), ny_state_rule_payload()),
        budget=budget,
        separation_date=separation_date,
        select_indexes=select_indexes,
        via_batch=True,
        plan_name="2026 Q4 NY Restructuring",
        decisional_unit_name="NY HQ Operations",
    )


def setup_executed_scenario(
    people=(ALICE, BEN_CLASS_B),
    script_code="MANAGER_SCRIPT_STANDARD",
    select_indexes=(0,),
    propose_only_indexes=(1,),
    **kwargs,
):
    """A TX plan carried all the way through execution, so the cascade has
    minted a rehire restriction for every separated incumbent."""
    scn = setup_offer_ready_scenario(
        people=people,
        select_indexes=select_indexes,
        propose_only_indexes=propose_only_indexes,
        notify_indexes=select_indexes,
        script_code=script_code,
        with_disclosure=False,
        **kwargs,
    )
    execute_plan(scn["plan"]["id"])
    scn["plan"] = read_plan(scn["plan"]["id"])
    scn["site"] = read_site(scn["site"]["id"])
    scn["restrictions"] = list_restrictions(site_id=scn["site"]["id"])
    return scn


def setup_eight_person_analysis_pool():
    """Eight people across three demographic classes, four of them selected and
    four exempted, giving the focal class three pooled and one selected."""
    from .factories import CARLA, DAN, ELENA, FARID, GRACE_CLASS_C, HIRO

    people = (ALICE, BEN, HIRO, CARLA, DAN, ELENA, FARID, GRACE_CLASS_C)
    site, employees = setup_site_with_roster(people, "TX")
    plan = create_locked_plan()
    order = [0, 3, 5, 6, 1, 2, 4, 7]  # alice, carla, elena, farid, ben, hiro, dan, grace
    batch = propose_batch(
        plan["id"], [employees[i]["id"] for i in order]
    )
    selection_ids = batch["selection_ids"]
    decide_many(plan["id"], selection_ids[:4], "SELECT")
    decide_many(
        plan["id"], selection_ids[4:], "EXEMPT", "Retained for critical skills."
    )
    return {
        "site": read_site(site["id"]),
        "employees": employees,
        "plan": read_plan(plan["id"]),
        "selection_ids": selection_ids,
    }


def setup_dual_jurisdiction_roster():
    """A New York site of five whose four selected losses sit below the federal
    count test but above the New York one, with both statute rows configured."""
    from .factories import CARLA, ELENA, FARID

    configure_federal_rule()
    configure_ny_state_rule()
    site, employees = setup_site_with_roster((ALICE, CARLA, ELENA, FARID, BEN), "NY")
    plan = create_locked_plan(
        name="2026 Q4 NY Restructuring", decisional_unit_name="NY HQ Operations"
    )
    batch = propose_batch(
        plan["id"], [employees[i]["id"] for i in (0, 1, 2, 3)]
    )
    decide_many(plan["id"], batch["selection_ids"], "SELECT")
    return {
        "site": read_site(site["id"]),
        "employees": employees,
        "plan": read_plan(plan["id"]),
        "selection_ids": batch["selection_ids"],
    }


def setup_ny_single_selection_with_paperwork():
    """A New York site of three where only the first person is selected, with a
    CLEARED analysis and an ATTACHED disclosure snapshotted at those counts."""
    from .factories import CARLA

    configure_federal_rule()
    configure_ny_state_rule()
    site, employees = setup_site_with_roster((ALICE, BEN, CARLA), "NY")
    plan = create_locked_plan(
        name="2026 Q4 NY Restructuring", decisional_unit_name="NY HQ Operations"
    )
    batch = propose_batch(plan["id"], [employees[0]["id"], employees[2]["id"]])
    sel_alice, sel_carla = batch["selection_ids"]
    decide(sel_alice, "SELECT")
    analysis = run_and_clear_analysis(plan["id"], justification="Initial single-selection review.")
    disclosure = generate_disclosure(plan["id"])
    return {
        "site": read_site(site["id"]),
        "employees": employees,
        "plan": read_plan(plan["id"]),
        "sel_alice": sel_alice,
        "sel_carla": sel_carla,
        "analysis": analysis,
        "disclosure": disclosure,
    }


def setup_tx_percent_boundary_scenario():
    """A four-person Texas site under a state rule whose percent test sits at
    exactly 50.00, with one of two proposals already selected."""
    from .factories import CARLA, DAN, tx_state_rule_payload

    configure_rule(tx_state_rule_payload())
    site, employees = setup_site_with_roster((ALICE, BEN, CARLA, DAN), "TX")
    plan = create_locked_plan()
    batch = propose_batch(plan["id"], [employees[0]["id"], employees[1]["id"]])
    decide(batch["selection_ids"][0], "SELECT")
    return {
        "site": read_site(site["id"]),
        "employees": employees,
        "plan": read_plan(plan["id"]),
        "sel_alice": batch["selection_ids"][0],
        "sel_ben": batch["selection_ids"][1],
    }


def setup_ny_scenario_with_issued_state_notice():
    """A triggered New York site whose STATE notice has been issued, freezing the
    site's aggregation window."""
    scn = setup_ny_triggered_scenario()
    notice = draft_warn_notice(
        scn["plan"]["id"], scn["site"]["id"], "STATE", NY_NOTICE_CONTENT
    )
    scn["notice"] = issue_warn_notice(notice["id"])
    scn["plan"] = read_plan(scn["plan"]["id"])
    scn["site"] = read_site(scn["site"]["id"])
    return scn

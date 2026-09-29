"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because each test starts against an empty database. Setup calls go through the
lenient `get_success_data` so a broken precondition reports as a setup failure.

Identity threading: a `MemberOrgDelegate`'s `X-User-ID` is the member organization's
own `id`, so every pledge and rescission below uses
`make_member_org_delegate_headers(member_org["id"])`.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_TEST_UTC
from .factories import (
    assessment_payload,
    assistance_record_payload,
    case_presentation_payload,
    construction_project_payload,
    damage_item_payload,
    disbursement_payload,
    follow_up_payload,
    funding_commitment_payload,
    funding_source_payload,
    housing_assignment_payload,
    lodging_site_payload,
    member_organization_payload,
    recovery_case_payload,
    survivor_payload,
    table_session_payload,
    verification_payload,
    volunteer_deployment_payload,
    volunteer_group_payload,
)
from .test_users import TEST_USERS, make_member_org_delegate_headers

ADMIN = TEST_USERS["ltrg_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
CASE_MANAGER = TEST_USERS["case_manager_headers"]
CHAIR = TEST_USERS["unmet_needs_chair_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]
BUILDER = TEST_USERS["construction_manager_headers"]
COORDINATOR = TEST_USERS["volunteer_coordinator_headers"]


# ------------------------------------------------------------------ primitives


def set_clock(to_iso8601: str = CLOCK_TEST_UTC) -> Dict[str, Any]:
    """Drive the logical clock to a known instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_survivor(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_survivor(survivor_payload(**overrides), INTAKE))


def create_case(survivor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_recovery_case(recovery_case_payload(survivor_id, **overrides), INTAKE)
    )


def read_case(case_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_recovery_case(case_id, OFFICER))


def case_version(case_id: str) -> int:
    return read_case(case_id)["version"]


def read_presentation(presentation_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_case_presentation(presentation_id, CHAIR))


def presentation_version(presentation_id: str) -> int:
    return read_presentation(presentation_id)["version"]


def document_damage(case_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_damage_item(case_id, damage_item_payload(**overrides), CASE_MANAGER)
    )


def verify_damage(damage_item_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.verify_damage_item(damage_item_id, verification_payload(**overrides), BUILDER)
    )


def document_and_verify_damage(
    case_id: str, category: str, cents: int, description: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Document one item at `cents` and verify it at the same figure."""
    item = document_damage(
        case_id,
        category=category,
        documented_cost_cents=cents,
        item_description=description or f"{category.title()} damage",
        **overrides,
    )
    verify_damage(item["id"], verification_status="VERIFIED", verified_cost_cents=cents)
    return item


def record_assistance(case_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_assistance_record(
            case_id, assistance_record_payload(**overrides), CASE_MANAGER
        )
    )


def run_assessment(case_id: str, variant: str = "PURPOSE_MATCHED") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_assessment(case_id, assessment_payload(variant=variant), CASE_MANAGER)
    )


def seat_member_org(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_member_organization(member_organization_payload(**overrides), ADMIN)
    )


def read_member_org(member_org_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_member_organization(member_org_id, ADMIN))


def create_funding_source(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_funding_source(funding_source_payload(**overrides), ADMIN)
    )


def read_funding_source(funding_source_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_funding_source(funding_source_id, OFFICER))


def schedule_session(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_table_session(table_session_payload(**overrides), CHAIR)
    )


def open_session(session_id: str, attending_member_org_ids: Sequence[str]) -> Dict[str, Any]:
    return get_success_data(
        api_client.open_table_session(
            session_id, {"attending_member_org_ids": list(attending_member_org_ids)}, CHAIR
        )
    )


def queue_presentation(
    case_id: str, session_id: str, assessment_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_case_presentation(
            case_presentation_payload(case_id, session_id, assessment_id, **overrides),
            CASE_MANAGER,
        )
    )


def present(presentation_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.present_case_presentation(presentation_id, {}, CHAIR))


def deliberate(presentation_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.deliberate_case_presentation(presentation_id, {}, CHAIR))


def present_and_deliberate(presentation_id: str) -> Dict[str, Any]:
    present(presentation_id)
    return deliberate(presentation_id)


def pledge(
    presentation_id: str,
    member_org_id: str,
    pledged_cents: int,
    purpose_code: str = "STRUCTURE_REPAIR",
    expected_presentation_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Record a pledge as the delegate of `member_org_id`, reading the live version."""
    version = (
        presentation_version(presentation_id)
        if expected_presentation_version is None
        else expected_presentation_version
    )
    return get_success_data(
        api_client.create_funding_commitment(
            funding_commitment_payload(
                presentation_id, member_org_id, pledged_cents, version, purpose_code=purpose_code
            ),
            make_member_org_delegate_headers(member_org_id),
        )
    )


def decide(presentation_id: str, decision: str, decision_note: str = "Recorded at the table") -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_case_presentation(
            presentation_id, {"decision": decision, "decision_note": decision_note}, CHAIR
        )
    )


def create_project(case_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_construction_project(
            construction_project_payload(case_id, **overrides), BUILDER
        )
    )


def transition_project(project_id: str, action: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.transition_construction_project(project_id, payload, BUILDER)
    )


def permit_project(project_id: str, permit_number: str = "PB-3300") -> Dict[str, Any]:
    return transition_project(project_id, "PERMIT", permit_number=permit_number)


def create_group(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_volunteer_group(volunteer_group_payload(**overrides), COORDINATOR)
    )


def create_deployment(
    group_id: str, project_id: str, arrival_date: str, departure_date: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_volunteer_deployment(
            volunteer_deployment_payload(
                group_id, project_id, arrival_date, departure_date, **overrides
            ),
            COORDINATOR,
        )
    )


def transition_deployment(deployment_id: str, action: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.transition_volunteer_deployment(deployment_id, payload, COORDINATOR)
    )


def create_lodging_site(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_lodging_site(lodging_site_payload(**overrides), COORDINATOR)
    )


def create_housing_assignment(
    group_id: str, lodging_site_id: str, check_in_date: str, check_out_date: str
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_housing_assignment(
            housing_assignment_payload(group_id, lodging_site_id, check_in_date, check_out_date),
            COORDINATOR,
        )
    )


def request_disbursement(
    case_id: str,
    purpose_code: str,
    requested_cents: int,
    payee_name: str = "Ridgeline Builders LLC",
    expected_case_version: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Request a payment, reading the live case version unless one is supplied."""
    version = case_version(case_id) if expected_case_version is None else expected_case_version
    payload = disbursement_payload(
        case_id,
        requested_cents,
        version,
        purpose_code=purpose_code,
        payee_name=payee_name,
        **extra,
    )
    return get_success_data(api_client.create_disbursement(payload, OFFICER))


def approve_disbursement(disbursement_id: str, approval_note: str = "Approved") -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_disbursement(disbursement_id, {"approval_note": approval_note}, ADMIN)
    )


def pay_disbursement(disbursement_id: str, payment_reference: str = "CHK-1001") -> Dict[str, Any]:
    return get_success_data(
        api_client.pay_disbursement(disbursement_id, {"payment_reference": payment_reference}, OFFICER)
    )


def log_follow_up(case_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_follow_up(case_id, follow_up_payload(**overrides), CASE_MANAGER)
    )


# --------------------------------------------------------- Tier 1: case runways

DamageSpec = Tuple[str, int]


def setup_case_with_verified_damage(
    damage: Optional[Sequence[DamageSpec]] = None,
    assistance: Optional[Sequence[Dict[str, Any]]] = None,
    survivor_overrides: Optional[Dict[str, Any]] = None,
    case_overrides: Optional[Dict[str, Any]] = None,
    clock: Optional[str] = CLOCK_TEST_UTC,
) -> Dict[str, Any]:
    """Survivor + case + verified damage items (+ optional assistance records).

    `damage` is a sequence of `(category, cents)` pairs; each item is documented at
    that figure and verified at the same figure. Returns a dict carrying
    `survivor`, `case`, `damage_items` and `assistance_records`.
    """
    if clock:
        set_clock(clock)
    survivor = create_survivor(**(survivor_overrides or {}))
    case = create_case(survivor["id"], **(case_overrides or {}))
    items: List[Dict[str, Any]] = []
    for category, cents in damage or [("STRUCTURE", 900_000)]:
        items.append(document_and_verify_damage(case["id"], category, cents))
    records: List[Dict[str, Any]] = []
    for spec in assistance or []:
        records.append(record_assistance(case["id"], **spec))
    return {
        "survivor": survivor,
        "case": read_case(case["id"]),
        "damage_items": items,
        "assistance_records": records,
    }


def setup_assessed_case(
    variant: str = "PURPOSE_MATCHED", **kwargs: Any
) -> Dict[str, Any]:
    """A case with verified damage and one pinned determination snapshot."""
    scenario = setup_case_with_verified_damage(**kwargs)
    scenario["assessment"] = run_assessment(scenario["case"]["id"], variant)
    scenario["case"] = read_case(scenario["case"]["id"])
    return scenario


# ------------------------------------------------- Tier 2: the table's runways

OrgSpec = Dict[str, Any]


def setup_deliberating_presentation(
    orgs: Optional[Sequence[OrgSpec]] = None,
    quorum_min_member_orgs: int = 1,
    session_overrides: Optional[Dict[str, Any]] = None,
    funding_sources: Optional[Sequence[Dict[str, Any]]] = None,
    **case_kwargs: Any,
) -> Dict[str, Any]:
    """Assessed case queued onto an open session, called, and open for pledges.

    Returns the assessed-case dict plus `member_orgs`, `session` and `presentation`
    (and `funding_sources`, created before any decision so they count toward the
    bridge pool).
    """
    scenario = setup_assessed_case(**case_kwargs)
    member_orgs = [seat_member_org(**(spec or {})) for spec in (orgs or [{}])]
    scenario["member_orgs"] = member_orgs
    scenario["funding_sources"] = [create_funding_source(**spec) for spec in (funding_sources or [])]
    session = schedule_session(
        quorum_min_member_orgs=quorum_min_member_orgs, **(session_overrides or {})
    )
    open_session(session["id"], [org["id"] for org in member_orgs])
    presentation = queue_presentation(
        scenario["case"]["id"], session["id"], scenario["assessment"]["id"]
    )
    present_and_deliberate(presentation["id"])
    scenario["session"] = get_success_data(api_client.get_table_session(session["id"], CHAIR))
    scenario["presentation"] = read_presentation(presentation["id"])
    scenario["case"] = read_case(scenario["case"]["id"])
    return scenario


PledgeSpec = Tuple[int, int, str]  # (org index, pledged_cents, purpose_code)


def setup_awarded_case(
    pledges: Optional[Sequence[PledgeSpec]] = None,
    decision_note: str = "Award recorded at the table",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Full award chain: deliberating presentation, pledges recorded, AWARD decided.

    Returns the deliberating-presentation dict plus `commitments` and `decision`
    (the AWARD response body), with `case` and `presentation` re-read afterwards.
    """
    scenario = setup_deliberating_presentation(**kwargs)
    commitments: List[Dict[str, Any]] = []
    for org_index, cents, purpose_code in pledges or []:
        commitments.append(
            pledge(
                scenario["presentation"]["id"],
                scenario["member_orgs"][org_index]["id"],
                cents,
                purpose_code,
            )
        )
    scenario["commitments"] = commitments
    scenario["decision"] = decide(scenario["presentation"]["id"], "AWARD", decision_note)
    scenario["presentation"] = read_presentation(scenario["presentation"]["id"])
    scenario["case"] = read_case(scenario["case"]["id"])
    scenario["member_orgs"] = [read_member_org(org["id"]) for org in scenario["member_orgs"]]
    return scenario


def setup_fully_pledged_structure_case(
    unmet_cents: int = 2_000_000,
    pledge_cents: Optional[int] = None,
    org_cap_cents: int = 5_000_000,
    **kwargs: Any,
) -> Dict[str, Any]:
    """One STRUCTURE case whose whole determined need is pledged by one organization.

    The gap is zero, so no bridge is authorized and the case lands FULLY_COMMITTED
    in ACTIVE_RECOVERY — the state from which disbursement approval is reachable.
    """
    return setup_awarded_case(
        damage=[("STRUCTURE", unmet_cents)],
        orgs=[{"annual_pledge_cap_cents": org_cap_cents}],
        pledges=[(0, pledge_cents or unmet_cents, "STRUCTURE_REPAIR")],
        **kwargs,
    )


# ------------------------------------------- Tier 3: the till's runways

def setup_approved_structure_disbursement(
    requested_cents: int = 1_000_000,
    source_overrides: Optional[Dict[str, Any]] = None,
    unmet_cents: int = 2_000_000,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Awarded structure case + permitted project + restricted source + APPROVED row.

    Returns the awarded-case dict plus `project`, `structure_source` and
    `disbursement` (the approve response body).
    """
    scenario = setup_fully_pledged_structure_case(unmet_cents=unmet_cents, **kwargs)
    source = create_funding_source(
        **{
            "label": "Structure grant",
            "source_type": "FOUNDATION_GRANT",
            "restriction_code": "STRUCTURE_REPAIR_ONLY",
            "total_cents": 2_000_000,
            "expires_on": "2026-12-31",
            "admin_retention_allowed": True,
            **(source_overrides or {}),
        }
    )
    project = create_project(scenario["case"]["id"], required_trade_hours={"GENERAL_LABOR": 200})
    permit_project(project["id"], "PB-3301")
    row = request_disbursement(
        scenario["case"]["id"],
        "STRUCTURE_REPAIR",
        requested_cents,
        project_id=project["id"],
    )
    scenario["structure_source"] = source
    scenario["project"] = get_success_data(api_client.get_construction_project(project["id"], BUILDER))
    scenario["disbursement"] = approve_disbursement(row["id"], "Approved for payment")
    return scenario


def setup_paid_structure_disbursement(**kwargs: Any) -> Dict[str, Any]:
    """As above, then paid. `disbursement` is the PAID row."""
    scenario = setup_approved_structure_disbursement(**kwargs)
    scenario["disbursement"] = pay_disbursement(scenario["disbursement"]["id"], "CHK-2001")
    scenario["case"] = read_case(scenario["case"]["id"])
    scenario["structure_source"] = read_funding_source(scenario["structure_source"]["id"])
    return scenario


# --------------------------------------- Tier 4: volunteer and lodging runways


def setup_permitted_project_with_group(
    project_overrides: Optional[Dict[str, Any]] = None,
    group_overrides: Optional[Dict[str, Any]] = None,
    permit_number: str = "PB-3310",
    **case_kwargs: Any,
) -> Dict[str, Any]:
    """Case + PERMITTED project + registered volunteer group.

    Returns `survivor`, `case`, `project` and `group`. No damage is documented by
    default because project scoping and deployment need none.
    """
    if case_kwargs.pop("_set_clock", True):
        set_clock(case_kwargs.pop("clock", CLOCK_TEST_UTC))
    survivor = create_survivor(**(case_kwargs.pop("survivor_overrides", None) or {}))
    case = create_case(survivor["id"], **(case_kwargs.pop("case_overrides", None) or {}))
    project = create_project(
        case["id"],
        **(
            project_overrides
            or {
                "required_trade_hours": {"FRAMING": 300, "ROOFING": 150, "GENERAL_LABOR": 300},
                "estimated_material_cents": 900_000,
                "critical_trades": ["FRAMING"],
            }
        ),
    )
    permit_project(project["id"], permit_number)
    group = create_group(**(group_overrides or {}))
    return {
        "survivor": survivor,
        "case": read_case(case["id"]),
        "project": get_success_data(api_client.get_construction_project(project["id"], BUILDER)),
        "group": group,
    }


def setup_lodging_site_with_groups(
    bed_capacity: int = 20,
    group_specs: Optional[Sequence[Dict[str, Any]]] = None,
    clock: Optional[str] = CLOCK_TEST_UTC,
) -> Dict[str, Any]:
    """A lodging site plus a list of volunteer groups sized for bed-night tests."""
    if clock:
        set_clock(clock)
    site = create_lodging_site(bed_capacity=bed_capacity)
    groups = [create_group(**spec) for spec in (group_specs or [{}])]
    return {"site": get_success_data(api_client.get_lodging_site(site["id"], COORDINATOR)), "groups": groups}


# ------------------------------------------------- Tier 5: closure runway


def setup_closure_ready_case(**kwargs: Any) -> Dict[str, Any]:
    """A case whose funding_status is SATISFIED with every project wound down.

    One organization pledges the whole determined need, the award confirms it, a
    single disbursement for the whole committed total is approved and paid, the
    project is closed out, and one follow-up contact is logged — the three closure
    review criteria.
    """
    unmet = kwargs.pop("unmet_cents", 2_000_000)
    scenario = setup_fully_pledged_structure_case(unmet_cents=unmet, **kwargs)
    source = create_funding_source(
        label="Structure grant for closure",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=unmet * 2,
        admin_retention_allowed=False,
    )
    project = create_project(scenario["case"]["id"], required_trade_hours={"GENERAL_LABOR": 40})
    permit_project(project["id"], "PB-3390")
    transition_project(project["id"], "START")
    row = request_disbursement(
        scenario["case"]["id"], "STRUCTURE_REPAIR", unmet, project_id=project["id"]
    )
    approve_disbursement(row["id"], "Approved for closure runway")
    pay_disbursement(row["id"], "CHK-3390")
    transition_project(project["id"], "PUNCHLIST")
    transition_project(project["id"], "CLOSE_OUT")
    follow_up = log_follow_up(scenario["case"]["id"], contact_type="CLOSURE_REVIEW")
    scenario["structure_source"] = read_funding_source(source["id"])
    scenario["project"] = get_success_data(api_client.get_construction_project(project["id"], BUILDER))
    scenario["disbursement"] = get_success_data(api_client.get_disbursement(row["id"], OFFICER))
    scenario["follow_ups"] = [follow_up]
    scenario["case"] = read_case(scenario["case"]["id"])
    return scenario

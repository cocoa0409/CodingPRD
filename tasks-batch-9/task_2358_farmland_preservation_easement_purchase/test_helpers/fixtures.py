"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: each test runs against an empty database.

The canonical spine assembled by `setup_recorded_easement()` is:

    program (+ local / state / federal appropriations)
      -> landowner -> 160-acre Lancaster parcel
      -> open funding round -> application
      -> certified appraisal (easement value 175,550,000)
      -> ranking on RECEIPT_BASIS (composite 73.40)
      -> BARGAIN_SALE offer 175,550,000 at donation_pct 0.10
         (total program cost 160,364,925)
      -> funding plan (56,127,723 local / 64,145,970 state / 40,091,232 federal)
      -> acceptance -> three satisfied closing requirements
      -> recorded easement (impervious allowance 139,392 sqft,
         next monitoring due 2027-12-15)
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    APPRAISER_USER_ID,
    APPRAISER_USER_ID_ALT,
    CLOCK_2026_08_10,
    CLOCK_2026_08_20,
    CLOCK_2026_10_01,
    CLOCK_2026_10_05,
    CLOCK_2026_10_12,
    CLOCK_2026_12_15,
    MONITOR_USER_ID,
    OFFICER_USER_ID,
    REVIEWER_USER_ID,
)
from .factories import (
    cancel_closing_payload,
    complete_visit_payload,
    counter_payload,
    create_application_payload,
    create_funding_round_payload,
    create_funding_source_payload,
    create_landowner_payload,
    create_parcel_payload,
    create_program_payload,
    create_small_parcel_payload,
    cure_plan_payload,
    decide_amendment_payload,
    draft_amendment_payload,
    engage_appraisal_payload,
    funding_plan_payload,
    impervious_request_payload,
    issue_offer_payload,
    open_violation_payload,
    rank_payload,
    record_closing_payload,
    review_appraisal_payload,
    review_requirement_payload,
    schedule_visit_payload,
    submit_appraisal_payload,
    submit_subordination_payload,
    submit_survey_payload,
    submit_title_payload,
)
from .test_users import TEST_USERS, make_appraiser_headers, make_landowner_headers

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]
REVIEWER = TEST_USERS["appraisal_reviewer_headers"]
MONITOR = TEST_USERS["stewardship_monitor_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock, sweep and single-entity creation
# ---------------------------------------------------------------------------


def set_clock(current_utc: str) -> dict:
    """Move the server's logical UTC clock."""
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def run_sweep(headers: Optional[dict] = None) -> dict:
    """Run the time-driven stewardship sweep."""
    return get_success_data(api_client.run_stewardship_sweep(headers or ADMIN))


def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), ADMIN)
    )


def create_landowner(**overrides) -> dict:
    return get_success_data(
        api_client.create_landowner(create_landowner_payload(**overrides), ADMIN)
    )


def create_parcel(landowner_id: str, **overrides) -> dict:
    """Register the canonical 160-acre parcel as its own landowner."""
    return get_success_data(
        api_client.create_parcel(
            create_parcel_payload(landowner_id, **overrides),
            make_landowner_headers(landowner_id),
        )
    )


def create_small_parcel(landowner_id: str, **overrides) -> dict:
    """Register the 40-acre all-prime parcel that carries no lienholder."""
    return get_success_data(
        api_client.create_parcel(
            create_small_parcel_payload(landowner_id, **overrides),
            make_landowner_headers(landowner_id),
        )
    )


def create_funding_source(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_funding_source(
            create_funding_source_payload(program_id, **overrides), ADMIN
        )
    )


def create_standard_sources(
    program_id: str, local_overrides: Optional[dict] = None
) -> Dict[str, dict]:
    """The three appropriations the canonical spine funds against.

    LOCAL 60,000,000 (share 0.35, priority 1), STATE 120,000,000 (share 0.40,
    priority 2) and FEDERAL 200,000,000 (share 0.25, priority 3) which requires
    a one-to-one non-federal match.
    """
    local = create_funding_source(
        program_id,
        source_name="County Open Space Fund",
        level="LOCAL",
        authorized_cents=60_000_000,
        max_share_pct=0.35,
        priority_order=1,
        requires_match=False,
        **(local_overrides or {}),
    )
    state = create_funding_source(
        program_id,
        source_name="State Farmland Trust",
        level="STATE",
        authorized_cents=120_000_000,
        max_share_pct=0.40,
        priority_order=2,
        requires_match=False,
    )
    federal = create_funding_source(
        program_id,
        source_name="Federal ACEP-ALE",
        level="FEDERAL",
        authorized_cents=200_000_000,
        max_share_pct=0.25,
        priority_order=3,
        requires_match=True,
        match_ratio=1.0,
    )
    return {"local": local, "state": state, "federal": federal}


def create_draft_round(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_funding_round(
            create_funding_round_payload(program_id, **overrides), ADMIN
        )
    )


def open_round(round_id: str) -> dict:
    return get_success_data(api_client.open_funding_round(round_id, ADMIN))


def create_open_round(program_id: str, **overrides) -> dict:
    """Create a round and move it DRAFT -> OPEN.

    The program must already carry at least one ACTIVE funding source.
    """
    funding_round = create_draft_round(program_id, **overrides)
    open_round(funding_round["id"])
    return get_success_data(api_client.get_funding_round(funding_round["id"], ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: state progression readers
# ---------------------------------------------------------------------------


def read_application(application_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_application(application_id, headers or ADMIN))


def read_parcel(parcel_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_parcel(parcel_id, headers or ADMIN))


def read_easement(easement_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_easement(easement_id, headers or ADMIN))


def read_source(source_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_funding_source(source_id, headers or ADMIN))


def read_appraisal(appraisal_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_appraisal(appraisal_id, headers or ADMIN))


def read_amendment(amendment_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_amendment(amendment_id, headers or ADMIN))


def read_violation(violation_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_violation(violation_id, headers or ADMIN))


def list_negotiation_log(application_id: str, params: Optional[dict] = None) -> List[dict]:
    return get_success_data(
        api_client.list_negotiation_rounds(application_id, ADMIN, params)
    )


def list_commitments(params: Optional[dict] = None) -> List[dict]:
    return get_success_data(api_client.list_funding_commitments(ADMIN, params))


def commitments_of(application_id: str) -> List[dict]:
    return list_commitments({"application_id": application_id, "limit": 100})


def commitment_on(application_id: str, funding_source_id: str) -> Optional[dict]:
    for row in commitments_of(application_id):
        if row["funding_source_id"] == funding_source_id:
            return row
    return None


def application_version(application_id: str) -> int:
    return read_application(application_id)["version"]


def easement_version(easement_id: str) -> int:
    return read_easement(easement_id)["version"]


def parcel_version(parcel_id: str) -> int:
    return read_parcel(parcel_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2: the entity hierarchy up to a filed application
# ---------------------------------------------------------------------------


def setup_program_with_round(
    program_overrides: Optional[dict] = None,
    round_overrides: Optional[dict] = None,
    clock: str = CLOCK_2026_08_10,
) -> dict:
    """Program + three appropriations + an OPEN round, clock inside intake."""
    program = create_program(**(program_overrides or {}))
    landowner = create_landowner()
    set_clock(clock)
    sources = create_standard_sources(program["id"])
    funding_round = create_open_round(program["id"], **(round_overrides or {}))
    return {
        "program": program,
        "landowner": landowner,
        "landowner_headers": make_landowner_headers(landowner["id"]),
        "sources": sources,
        "round": funding_round,
    }


def file_application(
    round_id: str,
    parcel_id: str,
    landowner_id: str,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_application(
            create_application_payload(round_id, parcel_id, landowner_id, **overrides),
            make_landowner_headers(landowner_id),
        )
    )


def setup_filed_application(
    program_overrides: Optional[dict] = None,
    round_overrides: Optional[dict] = None,
    parcel_overrides: Optional[dict] = None,
    application_overrides: Optional[dict] = None,
) -> dict:
    """The canonical spine through a RECEIVED application."""
    scenario = setup_program_with_round(program_overrides, round_overrides)
    parcel = create_parcel(scenario["landowner"]["id"], **(parcel_overrides or {}))
    application = file_application(
        scenario["round"]["id"],
        parcel["id"],
        scenario["landowner"]["id"],
        **(application_overrides or {}),
    )
    scenario["parcel"] = parcel
    scenario["application"] = application
    return scenario


# ---------------------------------------------------------------------------
# Tier 3: appraisal, ranking, negotiation and funding shortcuts
# ---------------------------------------------------------------------------


def engage_appraisal(application_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.engage_appraisal(
            application_id, engage_appraisal_payload(**overrides), OFFICER
        )
    )


def submit_appraisal(
    appraisal_id: str,
    appraiser_user_id: str = APPRAISER_USER_ID,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.submit_appraisal(
            appraisal_id,
            submit_appraisal_payload(**overrides),
            make_appraiser_headers(appraiser_user_id),
        )
    )


def certify_appraisal(appraisal_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.review_appraisal(
            appraisal_id, review_appraisal_payload("CERTIFY"), headers or REVIEWER
        )
    )


def setup_certified_appraisal(
    application_id: str,
    appraiser_user_id: str = APPRAISER_USER_ID,
    submission_clock: str = CLOCK_2026_08_20,
    engagement_overrides: Optional[dict] = None,
    submission_overrides: Optional[dict] = None,
) -> dict:
    """Engage -> submit -> certify, so the application carries
    `certified_easement_value_cents`."""
    appraisal = engage_appraisal(
        application_id,
        appraiser_user_id=appraiser_user_id,
        **(engagement_overrides or {}),
    )
    set_clock(submission_clock)
    submit_appraisal(
        appraisal["id"], appraiser_user_id, **(submission_overrides or {})
    )
    return certify_appraisal(appraisal["id"])


def rank_round(
    round_id: str, score_basis: str = "RECEIPT_BASIS", clock: str = CLOCK_2026_10_01
) -> dict:
    """Advance the clock past the intake window and run the single-shot ranking."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(
        api_client.rank_funding_round(round_id, rank_payload(score_basis), ADMIN)
    )


def issue_offer(
    application_id: str,
    offer_cents: int,
    structure: str = "FULL_PURCHASE",
    expected_application_version: Optional[int] = None,
    **overrides,
) -> dict:
    """Issue an offer, reading the application's current version when the caller
    does not pin one."""
    version = (
        expected_application_version
        if expected_application_version is not None
        else application_version(application_id)
    )
    return get_success_data(
        api_client.issue_offer(
            application_id,
            issue_offer_payload(version, offer_cents, structure, **overrides),
            OFFICER,
        )
    )


def file_counter(application_id: str, landowner_id: str, counter_cents: int, **overrides) -> dict:
    return get_success_data(
        api_client.file_counter(
            application_id,
            counter_payload(counter_cents, **overrides),
            make_landowner_headers(landowner_id),
        )
    )


def assemble_funding_plan(
    application_id: str,
    expected_application_version: Optional[int] = None,
    **overrides,
) -> dict:
    version = (
        expected_application_version
        if expected_application_version is not None
        else application_version(application_id)
    )
    return get_success_data(
        api_client.assemble_funding_plan(
            application_id, funding_plan_payload(version, **overrides), ADMIN
        )
    )


def accept_as_landowner(application_id: str, landowner_id: str) -> dict:
    return get_success_data(
        api_client.accept_application(
            application_id, make_landowner_headers(landowner_id)
        )
    )


def accept_as_officer(application_id: str) -> dict:
    return get_success_data(api_client.accept_application(application_id, OFFICER))


def setup_ranked_application(**kwargs) -> dict:
    """Spine through a RANKED application carrying a certified easement value."""
    scenario = setup_filed_application(**kwargs)
    setup_certified_appraisal(scenario["application"]["id"])
    scenario["rank_result"] = rank_round(scenario["round"]["id"])
    scenario["application"] = read_application(scenario["application"]["id"])
    return scenario


def setup_offered_application(
    offer_cents: int = 175_550_000,
    structure: str = "BARGAIN_SALE",
    offer_overrides: Optional[dict] = None,
    offer_clock: str = CLOCK_2026_10_05,
    **kwargs,
) -> dict:
    """Spine through an OFFER_ISSUED application.

    The default offer is the canonical BARGAIN_SALE at donation_pct 0.10, which
    builds a total program cost of 160,364,925.
    """
    scenario = setup_ranked_application(**kwargs)
    set_clock(offer_clock)
    overrides = {"donation_pct": 0.10} if structure == "BARGAIN_SALE" else {}
    overrides.update(offer_overrides or {})
    scenario["application"] = issue_offer(
        scenario["application"]["id"], offer_cents, structure, **overrides
    )
    return scenario


def setup_funded_application(
    plan_overrides: Optional[dict] = None, **kwargs
) -> dict:
    """Spine through a FUNDED application with a full reserved commitment set."""
    scenario = setup_offered_application(**kwargs)
    scenario["plan_result"] = assemble_funding_plan(
        scenario["application"]["id"], **(plan_overrides or {})
    )
    scenario["application"] = read_application(scenario["application"]["id"])
    return scenario


def setup_accepted_application(
    acceptance_clock: str = CLOCK_2026_10_12, **kwargs
) -> dict:
    """Spine through an ACCEPTED application with its pre-closing file open."""
    scenario = setup_funded_application(**kwargs)
    set_clock(acceptance_clock)
    scenario["application"] = accept_as_landowner(
        scenario["application"]["id"], scenario["landowner"]["id"]
    )
    scenario["requirements"] = list_requirements(scenario["application"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: closing requirements and recording
# ---------------------------------------------------------------------------


def list_requirements(application_id: str, params: Optional[dict] = None) -> List[dict]:
    return get_success_data(
        api_client.list_closing_requirements(application_id, ADMIN, params)
    )


def requirement_of_type(application_id: str, requirement_type: str) -> dict:
    rows = list_requirements(application_id, {"requirement_type": requirement_type})
    assert rows, f"no {requirement_type} requirement on application {application_id}"
    return rows[0]


def submit_and_accept_requirement(requirement_id: str, payload: dict) -> dict:
    """An officer submits and a program admin accepts, so the two identifiers
    differ and the segregation-of-duties gate is satisfied."""
    get_success_data(
        api_client.submit_closing_requirement(requirement_id, payload, OFFICER)
    )
    return get_success_data(
        api_client.review_closing_requirement(
            requirement_id, review_requirement_payload("ACCEPT"), ADMIN
        )
    )


def satisfy_all_requirements(
    application_id: str,
    surveyed_acres: float = 160.00,
    lienholder_name: str = "Midstate Farm Credit",
) -> Dict[str, dict]:
    """Submit and accept every closing requirement the acceptance created."""
    satisfied: Dict[str, dict] = {}
    for row in list_requirements(application_id):
        kind = row["requirement_type"]
        if kind == "TITLE_COMMITMENT":
            payload = submit_title_payload(0)
        elif kind == "MORTGAGE_SUBORDINATION":
            payload = submit_subordination_payload(lienholder_name)
        else:
            payload = submit_survey_payload(surveyed_acres)
        satisfied[kind] = submit_and_accept_requirement(row["id"], payload)
    return satisfied


def setup_cleared_application(
    surveyed_acres: float = 160.00, **kwargs
) -> dict:
    """Spine through `closing_status` CLEARED, ready for recording."""
    scenario = setup_accepted_application(**kwargs)
    scenario["satisfied_requirements"] = satisfy_all_requirements(
        scenario["application"]["id"], surveyed_acres=surveyed_acres
    )
    scenario["application"] = read_application(scenario["application"]["id"])
    return scenario


def record_closing(application_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.record_closing(application_id, record_closing_payload(**overrides), ADMIN)
    )


def setup_recorded_easement(
    closing_clock: str = CLOCK_2026_12_15,
    closing_overrides: Optional[dict] = None,
    **kwargs
) -> dict:
    """The full canonical spine through a RECORDED easement.

    The recorded easement carries an impervious allowance of 139,392 sqft and a
    next monitoring due date of 2027-12-15.
    """
    scenario = setup_cleared_application(**kwargs)
    set_clock(closing_clock)
    overrides = {"recorded_on": closing_clock}
    overrides.update(closing_overrides or {})
    scenario["easement"] = record_closing(scenario["application"]["id"], **overrides)
    scenario["application"] = read_application(scenario["application"]["id"])
    return scenario


def setup_small_recorded_easement(
    closing_clock: str = CLOCK_2026_12_15,
) -> dict:
    """A 40-acre easement on a parcel with no lienholder.

    The parcel is all prime soil (soil score 100.00), carries two baseline
    dwelling rights and closes as a FULL_PURCHASE, giving an impervious
    allowance of 34,848 sqft.
    """
    scenario = setup_program_with_round()
    parcel = create_small_parcel(scenario["landowner"]["id"])
    application = file_application(
        scenario["round"]["id"],
        parcel["id"],
        scenario["landowner"]["id"],
        requested_price_cents=24_000_000,
    )
    setup_certified_appraisal(
        application["id"],
        appraiser_user_id=APPRAISER_USER_ID_ALT,
        engagement_overrides={"appraiser_firm": "Octoraro Valuation"},
        submission_overrides={
            "unrestricted_value_cents": 60_000_000,
            "restricted_value_cents": 35_000_000,
        },
    )
    rank_round(scenario["round"]["id"])
    set_clock(CLOCK_2026_10_05)
    issue_offer(application["id"], 25_000_000, "FULL_PURCHASE")
    assemble_funding_plan(application["id"])
    set_clock(CLOCK_2026_10_12)
    accept_as_landowner(application["id"], scenario["landowner"]["id"])
    satisfy_all_requirements(application["id"], surveyed_acres=40.00)
    set_clock(closing_clock)
    easement = record_closing(
        application["id"],
        recorded_on=closing_clock,
        protected_acres=40.00,
        residential_rights_retained=1,
        permitted_uses=["CROP_PRODUCTION"],
    )
    scenario["parcel"] = parcel
    scenario["application"] = read_application(application["id"])
    scenario["easement"] = easement
    return scenario


def cancel_closing(application_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_closing(
            application_id, cancel_closing_payload(**overrides), ADMIN
        )
    )


# ---------------------------------------------------------------------------
# Tier 5: stewardship, violations and amendments
# ---------------------------------------------------------------------------


def schedule_visit(easement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.schedule_monitoring_visit(
            schedule_visit_payload(easement_id, **overrides), MONITOR
        )
    )


def complete_visit(visit_id: str, observed_impervious_sqft: int, **overrides) -> dict:
    return get_success_data(
        api_client.complete_monitoring_visit(
            visit_id,
            complete_visit_payload(observed_impervious_sqft, **overrides),
            MONITOR,
        )
    )


def cancel_visit(visit_id: str, reason: str = "weather closed the access lane") -> dict:
    return get_success_data(
        api_client.cancel_monitoring_visit(visit_id, {"reason": reason}, MONITOR)
    )


def open_violation(easement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.open_violation(open_violation_payload(easement_id, **overrides), MONITOR)
    )


def record_impervious(easement_id: str, added_impervious_sqft: int, **overrides) -> dict:
    return get_success_data(
        api_client.record_impervious_request(
            easement_id,
            impervious_request_payload(added_impervious_sqft, **overrides),
            MONITOR,
        )
    )


def accept_cure_plan(violation_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.accept_cure_plan(violation_id, cure_plan_payload(**overrides), MONITOR)
    )


def verify_cure(violation_id: str, **overrides) -> dict:
    return get_success_data(api_client.verify_cure(violation_id, overrides or {}, MONITOR))


def draft_amendment(easement_id: str, expected_easement_version: Optional[int] = None, **overrides) -> dict:
    version = (
        expected_easement_version
        if expected_easement_version is not None
        else easement_version(easement_id)
    )
    return get_success_data(
        api_client.draft_amendment(
            easement_id, draft_amendment_payload(version, **overrides), ADMIN
        )
    )


def submit_amendment(amendment_id: str) -> dict:
    return get_success_data(api_client.submit_amendment(amendment_id, ADMIN))


def decide_amendment(amendment_id: str, decision: str = "APPROVE", **overrides) -> dict:
    return get_success_data(
        api_client.decide_amendment(
            amendment_id, decide_amendment_payload(decision, **overrides), ADMIN
        )
    )


def reinstate_amendment(amendment_id: str) -> dict:
    return get_success_data(api_client.reinstate_amendment(amendment_id, ADMIN))


def rescind_amendment(amendment_id: str, reason: str = "landowner reversed the request") -> dict:
    return get_success_data(
        api_client.rescind_amendment(amendment_id, {"reason": reason}, ADMIN)
    )


def setup_easement_with_amendment_under_review(
    amendment_type: str = "BOUNDARY_ADJUSTMENT",
    amendment_overrides: Optional[dict] = None,
    **kwargs
) -> dict:
    """Recorded easement carrying one amendment in UNDER_REVIEW."""
    scenario = setup_recorded_easement(**kwargs)
    amendment = draft_amendment(
        scenario["easement"]["id"],
        amendment_type=amendment_type,
        **(amendment_overrides or {}),
    )
    scenario["amendment"] = submit_amendment(amendment["id"])
    scenario["easement"] = read_easement(scenario["easement"]["id"])
    return scenario


def setup_easement_with_open_violation(
    violation_type: str = "UNAUTHORIZED_SUBDIVISION",
    violation_overrides: Optional[dict] = None,
    **kwargs
) -> dict:
    """Recorded easement whose compliance dimension sits at VIOLATION_OPEN."""
    scenario = setup_recorded_easement(**kwargs)
    scenario["violation"] = open_violation(
        scenario["easement"]["id"],
        violation_type=violation_type,
        **(violation_overrides or {}),
    )
    scenario["easement"] = read_easement(scenario["easement"]["id"])
    return scenario


def setup_easement_with_approved_rights_amendment(
    residential_rights_delta: int = -2,
    net_conservation_benefit_cents: int = 500_000,
    **kwargs
) -> dict:
    """Recorded easement with an APPROVED residential-right relocation applied."""
    scenario = setup_recorded_easement(**kwargs)
    amendment = draft_amendment(
        scenario["easement"]["id"],
        amendment_type="RESIDENTIAL_RIGHT_RELOCATION",
        net_conservation_benefit_cents=net_conservation_benefit_cents,
        residential_rights_delta=residential_rights_delta,
    )
    submit_amendment(amendment["id"])
    scenario["amendment"] = decide_amendment(amendment["id"], "APPROVE")
    scenario["easement"] = read_easement(scenario["easement"]["id"])
    return scenario


def setup_easement_with_approved_impervious_amendment(
    requested_impervious_sqft: int = 160_000,
    net_conservation_benefit_cents: int = 500_000,
    **kwargs
) -> dict:
    """Recorded easement with an APPROVED impervious increase applied."""
    scenario = setup_recorded_easement(**kwargs)
    amendment = draft_amendment(
        scenario["easement"]["id"],
        amendment_type="IMPERVIOUS_INCREASE",
        net_conservation_benefit_cents=net_conservation_benefit_cents,
        requested_impervious_sqft=requested_impervious_sqft,
    )
    submit_amendment(amendment["id"])
    scenario["amendment"] = decide_amendment(amendment["id"], "APPROVE")
    scenario["easement"] = read_easement(scenario["easement"]["id"])
    return scenario


def setup_priced_application(
    parcel_overrides: Optional[dict] = None,
    requested_price_cents: int = 170_000_000,
    program_overrides: Optional[dict] = None,
    round_overrides: Optional[dict] = None,
    parcel_factory=None,
    appraisal_unrestricted_cents: Optional[int] = None,
    appraisal_restricted_cents: Optional[int] = None,
    rank: bool = True,
    score_basis: str = "RECEIPT_BASIS",
) -> dict:
    """A spine over an arbitrary parcel, certified at the parcel's own figures.

    Used by the valuation and scoring boundary tests, which each need their own
    acreage and valuation pair rather than the canonical 160-acre parcel.
    """
    scenario = setup_program_with_round(program_overrides, round_overrides)
    factory = parcel_factory or create_parcel
    parcel = factory(scenario["landowner"]["id"], **(parcel_overrides or {}))
    application = file_application(
        scenario["round"]["id"],
        parcel["id"],
        scenario["landowner"]["id"],
        requested_price_cents=requested_price_cents,
    )
    unrestricted = (
        appraisal_unrestricted_cents
        if appraisal_unrestricted_cents is not None
        else parcel["unrestricted_value_cents"]
    )
    restricted = (
        appraisal_restricted_cents
        if appraisal_restricted_cents is not None
        else parcel["restricted_value_cents"]
    )
    scenario["appraisal"] = setup_certified_appraisal(
        application["id"],
        submission_overrides={
            "unrestricted_value_cents": unrestricted,
            "restricted_value_cents": restricted,
        },
    )
    if rank:
        scenario["rank_result"] = rank_round(
            scenario["round"]["id"], score_basis=score_basis
        )
    scenario["parcel"] = read_parcel(parcel["id"])
    scenario["application"] = read_application(application["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 6: purpose-built funding topologies
# ---------------------------------------------------------------------------


def setup_aggregate_guard_scenario() -> dict:
    """A program whose six appropriations let the four funding guards be
    isolated one at a time.

    Every source shares one obligation window: FEDERAL 0.45 (priority 1,
    requiring a two-to-one non-federal match), FEDERAL 0.45 (priority 2),
    LOCAL 0.35 (priority 3), STATE 0.40 (priority 4), LOCAL 0.05 (priority 5)
    and STATE 0.40 (priority 6). All are authorised at 100,000,000 except the
    priority-5 LOCAL appropriation, which is deliberately thin at 2,000,000 so
    that suspending everything above it starves the walk outright. The
    application under test carries a FULL_PURCHASE offer of 25,000,000, giving
    a total program cost of 25,500,000.
    """
    program = create_program(name="Aggregate Guard Program")
    landowner = create_landowner(legal_name="Tulpehocken Grain Co", tax_id_last4="3310")
    set_clock(CLOCK_2026_08_10)
    common = {
        "authorized_cents": 100_000_000,
        "obligation_window_start": "2026-01-01T00:00:00Z",
        "obligation_window_end": "2027-12-31T00:00:00Z",
    }
    sources = {
        "fed_a": create_funding_source(
            program["id"],
            source_name="Federal Guard A",
            level="FEDERAL",
            max_share_pct=0.45,
            priority_order=1,
            requires_match=True,
            match_ratio=2.0,
            **common,
        ),
        "fed_b": create_funding_source(
            program["id"],
            source_name="Federal Guard B",
            level="FEDERAL",
            max_share_pct=0.45,
            priority_order=2,
            requires_match=True,
            match_ratio=2.0,
            **common,
        ),
        "loc_a": create_funding_source(
            program["id"],
            source_name="Local Guard A",
            level="LOCAL",
            max_share_pct=0.35,
            priority_order=3,
            requires_match=False,
            **common,
        ),
        "state_a": create_funding_source(
            program["id"],
            source_name="State Guard A",
            level="STATE",
            max_share_pct=0.40,
            priority_order=4,
            requires_match=False,
            **common,
        ),
        "loc_b": create_funding_source(
            program["id"],
            source_name="Local Guard B",
            level="LOCAL",
            max_share_pct=0.05,
            priority_order=5,
            requires_match=False,
            **{**common, "authorized_cents": 2_000_000},
        ),
        "state_b": create_funding_source(
            program["id"],
            source_name="State Guard B",
            level="STATE",
            max_share_pct=0.40,
            priority_order=6,
            requires_match=False,
            **common,
        ),
    }
    funding_round = create_open_round(
        program["id"], round_label="2026 Guard Cycle", pool_cents=100_000_000
    )
    parcel = create_small_parcel(landowner["id"])
    application = file_application(
        funding_round["id"], parcel["id"], landowner["id"], requested_price_cents=24_000_000
    )
    setup_certified_appraisal(
        application["id"],
        appraiser_user_id=APPRAISER_USER_ID_ALT,
        engagement_overrides={"appraiser_firm": "Octoraro Valuation"},
        submission_overrides={
            "unrestricted_value_cents": 60_000_000,
            "restricted_value_cents": 35_000_000,
        },
    )
    rank_round(funding_round["id"])
    set_clock(CLOCK_2026_10_05)
    application = issue_offer(application["id"], 25_000_000, "FULL_PURCHASE")
    return {
        "program": program,
        "landowner": landowner,
        "landowner_headers": make_landowner_headers(landowner["id"]),
        "sources": sources,
        "round": funding_round,
        "parcel": parcel,
        "application": application,
    }


def setup_two_applications_competing_for_headroom(
    local_threshold_pct: float = 0.95,
) -> dict:
    """Two FUNDED applications reserved against the same un-netted headroom.

    Both plans reserve 56,127,723 from the 60,000,000 LOCAL appropriation,
    because a reserved hold is not netted out of `available_cents`. With the
    default threshold the LOCAL source stays ACTIVE after the first acceptance,
    so the second acceptance runs the ledger past `authorized_cents`. Lowering
    `local_threshold_pct` instead drives LOCAL to FULLY_OBLIGATED on the first
    acceptance, which lapses the second plan's LOCAL reservation.
    """
    program = create_program()
    landowner_a = create_landowner(legal_name="Harlan Family Trust", tax_id_last4="4417")
    landowner_b = create_landowner(legal_name="Vireo Ridge LLC", tax_id_last4="8802")
    set_clock(CLOCK_2026_08_10)
    sources = create_standard_sources(
        program["id"], local_overrides={"fully_obligated_threshold_pct": local_threshold_pct}
    )
    funding_round = create_open_round(program["id"])
    parcel_a = create_parcel(landowner_a["id"])
    parcel_b = create_parcel(landowner_b["id"], county="Berks")
    application_a = file_application(funding_round["id"], parcel_a["id"], landowner_a["id"])
    application_b = file_application(funding_round["id"], parcel_b["id"], landowner_b["id"])
    for application in (application_a, application_b):
        setup_certified_appraisal(application["id"])
    rank_round(funding_round["id"])
    set_clock(CLOCK_2026_10_05)
    application_a = issue_offer(
        application_a["id"], 175_550_000, "BARGAIN_SALE", donation_pct=0.10
    )
    application_b = issue_offer(
        application_b["id"], 175_550_000, "BARGAIN_SALE", donation_pct=0.10
    )
    assemble_funding_plan(application_a["id"])
    assemble_funding_plan(application_b["id"])
    return {
        "program": program,
        "landowner_a": landowner_a,
        "landowner_b": landowner_b,
        "sources": sources,
        "round": funding_round,
        "parcel_a": parcel_a,
        "parcel_b": parcel_b,
        "application_a": read_application(application_a["id"]),
        "application_b": read_application(application_b["id"]),
    }

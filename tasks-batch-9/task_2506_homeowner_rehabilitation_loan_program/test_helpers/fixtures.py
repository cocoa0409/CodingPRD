"""Composite state builders and pytest fixtures.

The harness restarts the API server before every individual test, so each test
begins against an empty database. Everything here therefore builds its
preconditions from scratch through the endpoints the PRD declares — there is no
direct database seeding anywhere.

Builders are plain callables so that a test can compose them freely; the pytest
fixtures at the bottom of the file wrap the compositions that more than one test
needs.
"""

import itertools
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import validate_success

from .api_client import api_client
from .factories import (
    close_out_payload,
    contractor_status_payload,
    create_applicant_payload,
    create_application_payload,
    create_bid_payload,
    create_bid_solicitation_payload,
    create_contractor_payload,
    create_draw_request_payload,
    create_inspection_payload,
    create_loan_payload,
    create_program_year_payload,
    create_work_item_payload,
    create_write_up_payload,
    historic_clearance_payload,
    lead_clearance_payload,
    record_inspection_result_payload,
    record_lien_payload,
    verify_ownership_payload,
)
from .test_users import TEST_USERS, make_contractor_headers, make_applicant_headers

# ---------------------------------------------------------------------------
# Role header shorthands
# ---------------------------------------------------------------------------

INTAKE = TEST_USERS["intake_specialist_headers"]
REHAB = TEST_USERS["rehab_specialist_headers"]
REHAB_2 = TEST_USERS["second_rehab_specialist_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
INSPECTOR_2 = TEST_USERS["second_inspector_headers"]
LOAN_OFFICER = TEST_USERS["loan_officer_headers"]
PROGRAM_MANAGER = TEST_USERS["program_manager_headers"]


# ---------------------------------------------------------------------------
# Inspection window allocation
# ---------------------------------------------------------------------------
#
# An inspection window collides only with another window on the *same*
# property, so windows need to be distinct per application id. Initial
# standards windows walk forward from 2026-08-03 and draw windows from
# 2026-09-20, both at 13:00-15:00Z, which keeps the two families far apart.

_INITIAL_WINDOW_BASE = date(2026, 8, 3)
_DRAW_WINDOW_BASE = date(2026, 9, 20)
_window_counters: Dict[str, itertools.count] = {}


def _next_window(application_id: str, base: date) -> Dict[str, str]:
    key = f"{application_id}:{base.isoformat()}"
    counter = _window_counters.setdefault(key, itertools.count(0))
    day = base + timedelta(days=next(counter))
    return {
        "scheduled_start_at": f"{day.isoformat()}T13:00:00Z",
        "scheduled_end_at": f"{day.isoformat()}T15:00:00Z",
    }


def next_initial_inspection_window(application_id: str) -> Dict[str, str]:
    """A fresh, non-colliding initial standards window for one property."""
    return _next_window(application_id, _INITIAL_WINDOW_BASE)


def next_draw_inspection_window(application_id: str) -> Dict[str, str]:
    """A fresh, non-colliding draw inspection window for one property."""
    return _next_window(application_id, _DRAW_WINDOW_BASE)


# ---------------------------------------------------------------------------
# Tier 1-2 builders: single resources
# ---------------------------------------------------------------------------


def build_program_year(**overrides) -> Dict[str, Any]:
    response = api_client.create_program_year(
        create_program_year_payload(**overrides), PROGRAM_MANAGER
    )
    return validate_success(response, 201)


def build_contractor(**overrides) -> Dict[str, Any]:
    response = api_client.create_contractor(
        create_contractor_payload(**overrides), PROGRAM_MANAGER
    )
    return validate_success(response, 201)


def build_applicant(program_year_id: str, **overrides) -> Dict[str, Any]:
    response = api_client.create_applicant(
        create_applicant_payload(program_year_id, **overrides), INTAKE
    )
    return validate_success(response, 201)


def build_verified_applicant(program_year_id: str, **overrides) -> Dict[str, Any]:
    """A household whose income certification has already been run."""
    applicant = build_applicant(program_year_id, **overrides)
    response = api_client.verify_income(applicant["id"], INTAKE)
    return validate_success(response, 200)


def build_application(applicant_id: str, **overrides) -> Dict[str, Any]:
    response = api_client.create_application(
        create_application_payload(applicant_id, **overrides), INTAKE
    )
    return validate_success(response, 201)


def verify_application_ownership(application_id: str, **overrides) -> Dict[str, Any]:
    response = api_client.verify_ownership(
        application_id, verify_ownership_payload(**overrides), INTAKE
    )
    return validate_success(response, 200)


def build_ownership_verified_application(applicant_id: str, **overrides):
    """Return the application row after ownership verification has succeeded."""
    deed_recorded_date = overrides.pop("deed_recorded_date", "2015-04-12")
    title_report_clear = overrides.pop("title_report_clear", True)
    application = build_application(applicant_id, **overrides)
    verify_application_ownership(
        application["id"],
        deed_recorded_date=deed_recorded_date,
        title_report_clear=title_report_clear,
    )
    return validate_success(
        api_client.get_application(application["id"], INTAKE), 200
    )


def schedule_inspection(
    application_id: str,
    *,
    inspection_type: str = "INITIAL_STANDARDS",
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    if "scheduled_start_at" not in overrides:
        if inspection_type == "INITIAL_STANDARDS":
            overrides.update(next_initial_inspection_window(application_id))
        else:
            overrides.update(next_draw_inspection_window(application_id))
    response = api_client.create_inspection(
        create_inspection_payload(
            application_id, inspection_type=inspection_type, **overrides
        ),
        headers or INSPECTOR,
    )
    return validate_success(response, 201)


def record_result(
    inspection_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    response = api_client.record_inspection_result(
        inspection_id, record_inspection_result_payload(**overrides), headers or INSPECTOR
    )
    return validate_success(response, 200)


def complete_initial_inspection(
    application_id: str,
    *,
    result: str = "FAIL",
    deficiency_count: int = 3,
    xrf_reading_mg_cm2: Optional[float] = 0.2,
    headers: Optional[Dict[str, str]] = None,
    **schedule_overrides,
) -> Dict[str, Any]:
    """Schedule and record one initial standards inspection on a property."""
    inspection = schedule_inspection(
        application_id,
        inspection_type="INITIAL_STANDARDS",
        headers=headers,
        **schedule_overrides,
    )
    result_overrides: Dict[str, Any] = {
        "result": result,
        "deficiency_count": deficiency_count,
    }
    if xrf_reading_mg_cm2 is not None:
        result_overrides["xrf_reading_mg_cm2"] = xrf_reading_mg_cm2
    return record_result(inspection["id"], headers=headers, **result_overrides)


def build_write_up(
    application_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Open a DRAFT write-up, reading the application version it must match."""
    application = validate_success(
        api_client.get_application(application_id, REHAB), 200
    )
    expected_version = overrides.pop(
        "expected_application_version", application["version"]
    )
    response = api_client.create_write_up(
        create_write_up_payload(application_id, expected_version, **overrides),
        headers or REHAB,
    )
    return validate_success(response, 201)


def add_work_item(
    write_up_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    response = api_client.create_work_item(
        create_work_item_payload(write_up_id, **overrides), headers or REHAB
    )
    return validate_success(response, 201)


def submit_write_up(
    write_up_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return validate_success(
        api_client.submit_write_up(write_up_id, headers or REHAB), 200
    )


def approve_write_up(
    write_up_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return validate_success(
        api_client.approve_write_up(write_up_id, headers or PROGRAM_MANAGER), 200
    )


def build_write_up_with_lines(
    application_id: str,
    lines: Optional[List[Dict[str, Any]]] = None,
    *,
    prepared_by: Optional[Dict[str, str]] = None,
):
    """Open a DRAFT write-up and add every requested repair line to it."""
    write_up = build_write_up(application_id, headers=prepared_by)
    work_items = [
        add_work_item(write_up["id"], headers=prepared_by, **line)
        for line in (lines if lines is not None else [{}])
    ]
    return write_up, work_items


def open_solicitation(
    application_id: str, write_up_id: str, **overrides
) -> Dict[str, Any]:
    response = api_client.create_bid_solicitation(
        create_bid_solicitation_payload(application_id, write_up_id, **overrides),
        REHAB,
    )
    return validate_success(response, 201)


def place_bid(solicitation_id: str, contractor_id: str, **overrides) -> Dict[str, Any]:
    response = api_client.create_bid(
        create_bid_payload(solicitation_id, contractor_id, **overrides),
        make_contractor_headers(contractor_id),
    )
    return validate_success(response, 201)


def tabulate(solicitation_id: str) -> Dict[str, Any]:
    return validate_success(
        api_client.tabulate_solicitation(solicitation_id, REHAB), 200
    )


def award(solicitation_id: str, bid_id: str) -> Dict[str, Any]:
    return validate_success(
        api_client.award_solicitation(
            solicitation_id, {"bid_id": bid_id}, PROGRAM_MANAGER
        ),
        200,
    )


def structure_loan(application_id: str, **overrides) -> Dict[str, Any]:
    response = api_client.create_loan(
        create_loan_payload(application_id, **overrides), LOAN_OFFICER
    )
    return validate_success(response, 201)


def record_lien(loan_id: str, **overrides) -> Dict[str, Any]:
    return validate_success(
        api_client.record_lien(loan_id, record_lien_payload(**overrides), LOAN_OFFICER),
        200,
    )


def clear_lead_review(application_id: str, **overrides) -> Dict[str, Any]:
    return validate_success(
        api_client.record_lead_clearance(
            application_id, lead_clearance_payload(**overrides), INSPECTOR
        ),
        200,
    )


def clear_historic_review(application_id: str, **overrides) -> Dict[str, Any]:
    return validate_success(
        api_client.record_historic_clearance(
            application_id, historic_clearance_payload(**overrides), PROGRAM_MANAGER
        ),
        200,
    )


def clear_all_compliance_holds(application_id: str) -> Dict[str, Any]:
    """Record whichever clearances the application's posture is still waiting on."""
    application = validate_success(
        api_client.get_application(application_id, PROGRAM_MANAGER), 200
    )
    posture = application["compliance_posture"]
    if posture in ("LEAD_HOLD", "DUAL_HOLD"):
        application = clear_lead_review(application_id)
        posture = application["compliance_posture"]
    if posture in ("HISTORIC_HOLD", "DUAL_HOLD"):
        application = clear_historic_review(application_id)
    return application


def build_draw_request(
    loan_id: str, contractor_id: str, **overrides
) -> Dict[str, Any]:
    response = api_client.create_draw_request(
        create_draw_request_payload(loan_id, contractor_id, **overrides),
        make_contractor_headers(contractor_id),
    )
    return validate_success(response, 201)


def complete_draw_inspection(
    application_id: str,
    draw_request_id: str,
    *,
    result: str = "PASS",
    deficiency_count: int = 0,
    headers: Optional[Dict[str, str]] = None,
    **schedule_overrides,
) -> Dict[str, Any]:
    """Schedule and record the draw inspection that gates a draw approval."""
    inspection = schedule_inspection(
        application_id,
        inspection_type="DRAW",
        headers=headers,
        draw_request_id=draw_request_id,
        **schedule_overrides,
    )
    return record_result(
        inspection["id"],
        headers=headers,
        result=result,
        deficiency_count=deficiency_count,
    )


def approve_draw(draw_request_id: str) -> Dict[str, Any]:
    return validate_success(
        api_client.approve_draw_request(draw_request_id, LOAN_OFFICER), 200
    )


def pay_draw(draw_request_id: str) -> Dict[str, Any]:
    return validate_success(
        api_client.pay_draw_request(draw_request_id, LOAN_OFFICER), 200
    )


def run_paid_draw(
    *,
    application_id: str,
    loan_id: str,
    contractor_id: str,
    requested_amount_cents: int,
    is_final_draw: bool,
    **schedule_overrides,
) -> Dict[str, Any]:
    """Walk one draw from request through inspection, approval and payment."""
    draw = build_draw_request(
        loan_id,
        contractor_id,
        requested_amount_cents=requested_amount_cents,
        is_final_draw=is_final_draw,
    )
    complete_draw_inspection(application_id, draw["id"], **schedule_overrides)
    approve_draw(draw["id"])
    return pay_draw(draw["id"])


def close_out_loan(loan_id: str, **overrides) -> Dict[str, Any]:
    return validate_success(
        api_client.close_out_loan(loan_id, close_out_payload(**overrides), LOAN_OFFICER),
        200,
    )


def set_contractor_status(contractor_id: str, status: str, reason: str) -> Dict[str, Any]:
    return validate_success(
        api_client.set_contractor_status(
            contractor_id,
            contractor_status_payload(status, reason=reason),
            PROGRAM_MANAGER,
        ),
        200,
    )


def set_clock(now: str) -> None:
    validate_success(api_client.set_clock(now, PROGRAM_MANAGER), 200)


def refresh_application(application_id: str) -> Dict[str, Any]:
    return validate_success(
        api_client.get_application(application_id, PROGRAM_MANAGER), 200
    )


def refresh_program_year(program_year_id: str) -> Dict[str, Any]:
    return validate_success(
        api_client.get_program_year(program_year_id, PROGRAM_MANAGER), 200
    )


def refresh_loan(loan_id: str) -> Dict[str, Any]:
    return validate_success(api_client.get_loan(loan_id, LOAN_OFFICER), 200)


def refresh_write_up(write_up_id: str) -> Dict[str, Any]:
    return validate_success(api_client.get_write_up(write_up_id, REHAB), 200)


def refresh_solicitation(solicitation_id: str) -> Dict[str, Any]:
    return validate_success(api_client.get_solicitation(solicitation_id, REHAB), 200)


def refresh_bid(bid_id: str) -> Dict[str, Any]:
    return validate_success(api_client.get_bid(bid_id, REHAB), 200)


def refresh_contractor(contractor_id: str) -> Dict[str, Any]:
    return validate_success(
        api_client.get_contractor(contractor_id, PROGRAM_MANAGER), 200
    )


def refresh_inspection(inspection_id: str) -> Dict[str, Any]:
    return validate_success(api_client.get_inspection(inspection_id, INSPECTOR), 200)


def refresh_draw(draw_request_id: str) -> Dict[str, Any]:
    return validate_success(
        api_client.get_draw_request(draw_request_id, LOAN_OFFICER), 200
    )


def refresh_applicant(applicant_id: str) -> Dict[str, Any]:
    return validate_success(api_client.get_applicant(applicant_id, INTAKE), 200)


# ---------------------------------------------------------------------------
# Tier 3-5: the staged master builder
# ---------------------------------------------------------------------------

STAGES = (
    "intake",
    "ownership_verified",
    "inspected",
    "writeup_submitted",
    "writeup_approved",
    "bid_open",
    "bids_placed",
    "tabulated",
    "awarded",
    "structured",
    "lien_recorded",
)

DEFAULT_LINE = {
    "description": "Full roof replacement",
    "category": "ROOF",
    "priority_class": "HEALTH_SAFETY",
    "estimated_cost_cents": 2_000_000,
    "is_lead_hazard_reduction": False,
    "is_historic_sensitive": False,
}


def setup_case(
    *,
    stage: str = "lien_recorded",
    program_year: Optional[Dict[str, Any]] = None,
    contractor: Optional[Dict[str, Any]] = None,
    applicant: Optional[Dict[str, Any]] = None,
    program_year_overrides: Optional[Dict[str, Any]] = None,
    contractor_overrides: Optional[Dict[str, Any]] = None,
    applicant_overrides: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    deed_recorded_date: str = "2015-04-12",
    inspection_result: str = "FAIL",
    deficiency_count: int = 3,
    xrf_reading_mg_cm2: Optional[float] = 0.2,
    lines: Optional[List[Dict[str, Any]]] = None,
    prepared_by: Optional[Dict[str, str]] = None,
    solicitation_overrides: Optional[Dict[str, Any]] = None,
    bid_amount_cents: int = 2_000_000,
    bid_overrides: Optional[Dict[str, Any]] = None,
    loan_overrides: Optional[Dict[str, Any]] = None,
    lien_overrides: Optional[Dict[str, Any]] = None,
    clear_compliance: bool = True,
) -> Dict[str, Any]:
    """Walk one rehabilitation case forward to `stage` and return every row.

    The walk follows the order the PRD imposes: income certification precedes
    intake, ownership verification precedes inspection scheduling, an approved
    write-up precedes a solicitation, a tabulation precedes an award, an award
    precedes loan structuring and every compliance hold is cleared before the
    lien is recorded.
    """
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}; expected one of {STAGES}")
    target = STAGES.index(stage)

    case: Dict[str, Any] = {}

    case["program_year"] = program_year or build_program_year(
        **(program_year_overrides or {})
    )
    case["contractor"] = contractor or build_contractor(**(contractor_overrides or {}))
    case["contractor_headers"] = make_contractor_headers(case["contractor"]["id"])

    case["applicant"] = applicant or build_verified_applicant(
        case["program_year"]["id"], **(applicant_overrides or {})
    )
    case["applicant_headers"] = make_applicant_headers(case["applicant"]["id"])

    case["application"] = build_application(
        case["applicant"]["id"], **(application_overrides or {})
    )
    application_id = case["application"]["id"]

    if target >= STAGES.index("ownership_verified"):
        verify_application_ownership(
            application_id, deed_recorded_date=deed_recorded_date
        )

    if target >= STAGES.index("inspected"):
        case["inspection"] = complete_initial_inspection(
            application_id,
            result=inspection_result,
            deficiency_count=deficiency_count,
            xrf_reading_mg_cm2=xrf_reading_mg_cm2,
        )

    if target >= STAGES.index("writeup_submitted"):
        write_up, work_items = build_write_up_with_lines(
            application_id,
            lines if lines is not None else [dict(DEFAULT_LINE)],
            prepared_by=prepared_by,
        )
        case["write_up"] = write_up
        case["work_items"] = work_items
        case["write_up"] = submit_write_up(write_up["id"], headers=prepared_by)

    if target >= STAGES.index("writeup_approved"):
        case["write_up"] = approve_write_up(case["write_up"]["id"])

    if target >= STAGES.index("bid_open"):
        case["solicitation"] = open_solicitation(
            application_id,
            case["write_up"]["id"],
            **(solicitation_overrides or {}),
        )

    if target >= STAGES.index("bids_placed"):
        case["bid"] = place_bid(
            case["solicitation"]["id"],
            case["contractor"]["id"],
            amount_cents=bid_amount_cents,
            **(bid_overrides or {}),
        )

    if target >= STAGES.index("tabulated"):
        case["solicitation"] = tabulate(case["solicitation"]["id"])

    if target >= STAGES.index("awarded"):
        case["solicitation"] = award(case["solicitation"]["id"], case["bid"]["id"])

    if clear_compliance and target >= STAGES.index("inspected"):
        clear_all_compliance_holds(application_id)

    if target >= STAGES.index("structured"):
        case["loan"] = structure_loan(application_id, **(loan_overrides or {}))

    if target >= STAGES.index("lien_recorded"):
        case["loan"] = record_lien(case["loan"]["id"], **(lien_overrides or {}))

    case["application"] = refresh_application(application_id)
    case["program_year"] = refresh_program_year(case["program_year"]["id"])
    if "solicitation" in case:
        # Placing a bid increases the parent solicitation's `bid_count`, so the
        # snapshot taken when the solicitation was opened is stale by then.
        case["solicitation"] = refresh_solicitation(case["solicitation"]["id"])
    return case


def setup_historic_case(**kwargs) -> Dict[str, Any]:
    """A 1962 property inside a historic district, so both reviews are required."""
    application_overrides = {
        "address_line1": "9 Canal Row",
        "year_built": 1962,
        "assessed_value_cents": 14_000_000,
        "senior_lien_balance_cents": 9_000_000,
        "historic_district": True,
    }
    application_overrides.update(kwargs.pop("application_overrides", None) or {})
    kwargs.setdefault("deed_recorded_date", "2009-07-01")
    kwargs.setdefault("deficiency_count", 5)
    kwargs.setdefault("xrf_reading_mg_cm2", 1.4)
    kwargs.setdefault("applicant_overrides", {"full_name": "Junie Abbott"})
    return setup_case(application_overrides=application_overrides, **kwargs)


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """The shared API client."""
    return api_client


@pytest.fixture
def program_year():
    """One 2026 program year with a 50,000,000 allocation."""
    return build_program_year()


@pytest.fixture
def contractor():
    """One contractor, which the PRD places on the approved list on creation."""
    return build_contractor()


@pytest.fixture
def second_contractor():
    """A second contractor that is lead safe certified but not historic qualified."""
    return build_contractor(
        legal_name="Borough Builders Inc",
        lead_safe_certified=True,
        historic_qualified=False,
    )


@pytest.fixture
def applicant(program_year):
    """One household at intake, before income certification."""
    return build_applicant(program_year["id"])


@pytest.fixture
def verified_applicant(program_year):
    """One household whose income certification has already been recorded."""
    return build_verified_applicant(program_year["id"])


@pytest.fixture
def application(verified_applicant):
    """One application at INTAKE on a 1995 non-historic property."""
    return build_application(verified_applicant["id"])


@pytest.fixture
def ownership_verified_application(verified_applicant):
    """One application whose ownership verification has succeeded."""
    return build_ownership_verified_application(verified_applicant["id"])


@pytest.fixture
def inspected_case():
    """A case walked as far as the recorded initial standards inspection."""
    return setup_case(stage="inspected")


@pytest.fixture
def approved_write_up_case():
    """A case with an APPROVED single-line 2,000,000 write-up."""
    return setup_case(stage="writeup_approved")


@pytest.fixture
def bid_open_case():
    """A case whose solicitation is OPEN and accepting bids."""
    return setup_case(stage="bid_open")


@pytest.fixture
def tabulated_case():
    """A case whose solicitation has been tabulated but not yet awarded."""
    return setup_case(stage="tabulated")


@pytest.fixture
def awarded_case():
    """A case whose winning bid has been awarded, with no loan yet."""
    return setup_case(stage="awarded")


@pytest.fixture
def structured_loan_case():
    """A case with a STRUCTURED DEFERRED loan whose lien is not yet recorded."""
    return setup_case(stage="structured")


@pytest.fixture
def lien_recorded_case():
    """The canonical construction-ready case: lien recorded, work may begin."""
    return setup_case(stage="lien_recorded")


@pytest.fixture
def historic_inspected_case():
    """A 1962 historic-district case at INSPECTED with both holds outstanding."""
    return setup_historic_case(stage="inspected", clear_compliance=False)


@pytest.fixture
def complaint_ready_case():
    """A closed-out case, so a warranty exists and a complaint may be filed."""
    case = setup_case(stage="lien_recorded")
    run_paid_draw(
        application_id=case["application"]["id"],
        loan_id=case["loan"]["id"],
        contractor_id=case["contractor"]["id"],
        requested_amount_cents=2_000_000,
        is_final_draw=True,
    )
    case["loan"] = close_out_loan(case["loan"]["id"], completion_date="2026-10-30")
    case["application"] = refresh_application(case["application"]["id"])
    case["contractor"] = refresh_contractor(case["contractor"]["id"])
    case["program_year"] = refresh_program_year(case["program_year"]["id"])
    return case


__all__ = [
    "INTAKE",
    "REHAB",
    "REHAB_2",
    "INSPECTOR",
    "INSPECTOR_2",
    "LOAN_OFFICER",
    "PROGRAM_MANAGER",
    "STAGES",
    "DEFAULT_LINE",
    "next_initial_inspection_window",
    "next_draw_inspection_window",
    "build_program_year",
    "build_contractor",
    "build_applicant",
    "build_verified_applicant",
    "build_application",
    "verify_application_ownership",
    "build_ownership_verified_application",
    "schedule_inspection",
    "record_result",
    "complete_initial_inspection",
    "build_write_up",
    "add_work_item",
    "submit_write_up",
    "approve_write_up",
    "build_write_up_with_lines",
    "open_solicitation",
    "place_bid",
    "tabulate",
    "award",
    "structure_loan",
    "record_lien",
    "clear_lead_review",
    "clear_historic_review",
    "clear_all_compliance_holds",
    "build_draw_request",
    "complete_draw_inspection",
    "approve_draw",
    "pay_draw",
    "run_paid_draw",
    "close_out_loan",
    "set_contractor_status",
    "set_clock",
    "refresh_application",
    "refresh_program_year",
    "refresh_loan",
    "refresh_write_up",
    "refresh_solicitation",
    "refresh_bid",
    "refresh_contractor",
    "refresh_inspection",
    "refresh_draw",
    "refresh_applicant",
    "setup_case",
    "setup_historic_case",
]

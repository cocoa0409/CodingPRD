"""Composite setup helpers for the Hazmat Tier II API.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty before every test. Setup calls
use get_success_data() (lenient) so setup failures surface as clear errors.

Identity threading: FacilityOperator is ownership-gated (X-User-ID must equal
the acting Facility.id), so every operator call passes
make_facility_operator_headers(facility_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_regulator_headers,
    make_facility_operator_headers,
    make_lepc_coordinator_headers,
)
from .factories import (
    create_facility_payload,
    create_chemical_payload,
    create_ehs_chemical_payload,
    create_chemical_inventory_payload,
    create_tier_ii_filing_payload,
    create_sds_payload,
    create_release_notification_payload,
    create_lepc_notice_payload,
    create_permit_payload,
    create_inspection_payload,
    create_compliance_case_payload,
    create_risk_management_plan_payload,
)


# --------------------------------------------------------------------------
# Clock control
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, make_regulator_headers()))


# --------------------------------------------------------------------------
# Low-level single-entity builders
# --------------------------------------------------------------------------
def register_facility(**overrides) -> dict:
    resp = api_client.create_facility(create_facility_payload(**overrides), make_regulator_headers())
    return get_success_data(resp)


def create_chemical(**overrides) -> dict:
    resp = api_client.create_chemical(create_chemical_payload(**overrides), make_regulator_headers())
    return get_success_data(resp)


def create_ehs_chemical(**overrides) -> dict:
    resp = api_client.create_chemical(create_ehs_chemical_payload(**overrides), make_regulator_headers())
    return get_success_data(resp)


def get_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, make_regulator_headers()))


def declare_inventory(facility_id: str, chemical_id: str, **overrides) -> dict:
    resp = api_client.create_chemical_inventory(
        create_chemical_inventory_payload(facility_id, chemical_id, **overrides),
        make_facility_operator_headers(facility_id),
    )
    return get_success_data(resp)


def upload_sds(facility_id: str, chemical_id: str, expected_facility_version: int, **overrides) -> dict:
    resp = api_client.create_sds(
        create_sds_payload(facility_id, chemical_id, expected_facility_version, **overrides),
        make_facility_operator_headers(facility_id),
    )
    return get_success_data(resp)


def create_draft_filing(facility_id: str, reporting_year: int = 2025, **overrides) -> dict:
    resp = api_client.create_tier_ii_filing(
        create_tier_ii_filing_payload(facility_id, reporting_year=reporting_year, **overrides),
        make_facility_operator_headers(facility_id),
    )
    return get_success_data(resp)


def report_release(facility_id: str, chemical_id: str, **overrides) -> dict:
    resp = api_client.create_release_notification(
        create_release_notification_payload(facility_id, chemical_id, **overrides),
        make_facility_operator_headers(facility_id),
    )
    return get_success_data(resp)


def issue_permit(facility_id: str, **overrides) -> dict:
    resp = api_client.create_permit(
        create_permit_payload(facility_id, **overrides), make_regulator_headers()
    )
    return get_success_data(resp)


def schedule_inspection(facility_id: str, **overrides) -> dict:
    resp = api_client.create_inspection(
        create_inspection_payload(facility_id, **overrides), make_regulator_headers()
    )
    return get_success_data(resp)


def open_manual_case(facility_id: str, severity: str = None) -> dict:
    overrides = {"severity": severity} if severity is not None else {}
    resp = api_client.create_compliance_case(
        create_compliance_case_payload(facility_id, **overrides), make_regulator_headers()
    )
    return get_success_data(resp)


def submit_rmp(facility_id: str, **overrides) -> dict:
    resp = api_client.create_risk_management_plan(
        create_risk_management_plan_payload(facility_id, **overrides),
        make_facility_operator_headers(facility_id),
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Inspection lifecycle shortcuts
# --------------------------------------------------------------------------
def create_started_inspection(facility_id: str, **overrides) -> dict:
    """Schedule then start; returns the IN_PROGRESS inspection."""
    insp = schedule_inspection(facility_id, **overrides)
    return get_success_data(api_client.start_inspection(insp["id"], make_regulator_headers()))


def create_completed_inspection(facility_id: str, result: str = "PASS",
                                findings_count: int = 0, **overrides) -> dict:
    """Schedule -> start -> complete with the given result. Returns terminal inspection."""
    insp = create_started_inspection(facility_id, **overrides)
    payload = {"result": result}
    if result == "FAIL":
        payload["findings_count"] = findings_count
    return get_success_data(
        api_client.complete_inspection(insp["id"], payload, make_regulator_headers())
    )


# --------------------------------------------------------------------------
# Compliance-case lifecycle shortcuts
# --------------------------------------------------------------------------
def open_case_in_review(facility_id: str, severity: str = None) -> dict:
    """Open a manual case and move it to UNDER_REVIEW. Returns the case (OPEN snapshot)."""
    case = open_manual_case(facility_id, severity)
    get_success_data(api_client.review_compliance_case(case["id"], make_regulator_headers()))
    return case


# --------------------------------------------------------------------------
# Tier II filing composites (the most reused multi-step preamble)
# --------------------------------------------------------------------------
def setup_facility_with_draft_filing(
    with_sds: bool = True,
    rq_lbs: int = 5000,
    tpq_lbs: int = 100,
    max_daily_amount_lbs: float = 200,
    average_daily_amount_lbs: float = 150,
    reporting_year: int = 2025,
) -> dict:
    """Facility + one reportable EHS chemical inventory (+ optional ACTIVE SDS) + a DRAFT filing.

    Defaults yield exactly one reportable EHS chemical -> assessed fee 10000
    (base 5000 + per=0 + EHS surcharge 5000), provisional fee 7000 (base + 1 row).
    Facility version stays 1 until the SDS upload bumps it to 2.
    """
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_ehs_chemical(tpq_lbs=tpq_lbs, rq_lbs=rq_lbs)
    inventory = declare_inventory(
        fac_id, chemical["id"], reporting_year=reporting_year,
        max_daily_amount_lbs=max_daily_amount_lbs,
        average_daily_amount_lbs=average_daily_amount_lbs,
    )
    sds = None
    if with_sds:
        sds = upload_sds(fac_id, chemical["id"], facility["version"])
    filing = create_draft_filing(fac_id, reporting_year=reporting_year)
    return {
        "facility": facility,
        "chemical": chemical,
        "inventory": inventory,
        "sds": sds,
        "filing": filing,
        "operator_headers": make_facility_operator_headers(fac_id),
    }


def setup_submitted_filing(**overrides) -> dict:
    """As setup_facility_with_draft_filing, then submit the filing.
    Returns the same dict with 'filing' replaced by the SUBMITTED filing."""
    ctx = setup_facility_with_draft_filing(**overrides)
    fac_id = ctx["facility"]["id"]
    submitted = get_success_data(
        api_client.submit_tier_ii_filing(ctx["filing"]["id"], make_facility_operator_headers(fac_id))
    )
    ctx["filing"] = submitted
    return ctx


def setup_under_review_filing(**overrides) -> dict:
    """setup_submitted_filing, then Regulator BEGIN review -> UNDER_REVIEW."""
    ctx = setup_submitted_filing(**overrides)
    reviewed = get_success_data(
        api_client.review_tier_ii_filing(ctx["filing"]["id"], {"decision": "BEGIN"}, make_regulator_headers())
    )
    ctx["filing"] = reviewed
    return ctx


# --------------------------------------------------------------------------
# Enforcement / cascade composites
# --------------------------------------------------------------------------
def setup_facility_in_enforcement(rq_lbs: int = 50, quantity_released_lbs: float = 100,
                                  release_datetime: str = "2026-02-20T00:00:00Z") -> dict:
    """Facility pushed to ENFORCEMENT by an RQ-exceeding release (opens a HIGH case)."""
    facility = register_facility()
    chemical = create_ehs_chemical(rq_lbs=rq_lbs, tpq_lbs=500)
    release = report_release(
        facility["id"], chemical["id"],
        release_datetime=release_datetime,
        quantity_released_lbs=quantity_released_lbs, medium="AIR",
    )
    return {"facility": facility, "chemical": chemical, "release": release}


def setup_release_with_lepc_notice(recipient: str = "LEPC", notice_type: str = "VERBAL",
                                   rq_lbs: int = 5000, quantity_released_lbs: float = 10) -> dict:
    """Facility + non-EHS chemical + below-RQ release + one LEPC notice (unacknowledged)."""
    facility = register_facility()
    fac_id = facility["id"]
    chemical = create_chemical(rq_lbs=rq_lbs)
    release = report_release(
        fac_id, chemical["id"], release_datetime="2026-02-14T00:00:00Z",
        quantity_released_lbs=quantity_released_lbs, medium="AIR",
    )
    notice = get_success_data(
        api_client.create_lepc_notice(
            create_lepc_notice_payload(release["id"], notice_type=notice_type, recipient=recipient),
            make_facility_operator_headers(fac_id),
        )
    )
    return {"facility": facility, "chemical": chemical, "release": release, "notice": notice}


def find_facility_cases(facility_id: str) -> list:
    """Reverse-discovery of cascade-created cases via the facility sub-collection."""
    resp = api_client.list_facility_compliance_cases(facility_id, make_regulator_headers())
    return get_success_data(resp)


def find_facility_permits(facility_id: str) -> list:
    resp = api_client.list_facility_permits(facility_id, make_regulator_headers())
    return get_success_data(resp)

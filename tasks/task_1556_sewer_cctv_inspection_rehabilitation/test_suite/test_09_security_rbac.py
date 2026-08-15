"""Authentication and role-based access denials."""
from test_helpers import (
    ApiErrorId,
    add_defects,
    create_district,
    create_open_cycle,
    create_segment,
    create_technician,
    drive_inspection_to_coding,
    make_crew_lead_headers,
    schedule_inspection,
    set_clock,
    setup_notice_ctx,
    submit_for_qa,
    validate_error,
    TEST_USERS,
)

ENGINEER = TEST_USERS["engineer_headers"]
CSR = TEST_USERS["csr_headers"]


def test_error_unauthenticated_missing_headers(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside this
    catalog, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_missing_headers
    """
    resp = api.list_districts(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_crew_lead_cannot_certify_inspection(api):
    """PRD §2.1: "A properly identified caller who attempts an operation their role
    is not permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the
    per-endpoint role assignments are enumerated in §4."
    Certification is a QaReviewer operation (§4).

    Design: Corner/rbac/crew_lead_cannot_certify_inspection
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-B2", ii_reduction_target_pct=20, budget_cents=1000000)
    coder = create_technician(["CODER"])
    crew = create_technician(["CREW_LEAD"])
    cycle = create_open_cycle(district["id"])
    segment = create_segment(district["id"], segment_ref="MH-1->MH-2")
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])
    drive_inspection_to_coding(inspection["id"], coder["id"])
    add_defects(inspection["id"], coder["id"],
                [{"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
                  "distance_m": 10, "clock_position": 6}])
    submit_for_qa(inspection["id"], coder["id"])

    resp = api.certify_inspection(inspection["id"], make_crew_lead_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_csr_cannot_create_defect(api):
    """PRD §2.1: "A properly identified caller who attempts an operation their role
    is not permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the
    per-endpoint role assignments are enumerated in §4."
    Defect coding is a Coder operation (§4).

    Design: Corner/rbac/csr_cannot_create_defect
    """
    set_clock("2026-08-10T00:00:00Z")
    district = create_district(name="D-B3", ii_reduction_target_pct=20, budget_cents=1000000)
    coder = create_technician(["CODER"])
    cycle = create_open_cycle(district["id"])
    segment = create_segment(district["id"], segment_ref="MH-1->MH-2")
    inspection = schedule_inspection(segment["id"], cycle["id"], coder["id"])
    drive_inspection_to_coding(inspection["id"], coder["id"])

    resp = api.create_defect(
        inspection["id"],
        {"pacp_code": "CRK", "family": "STRUCTURAL", "grade": 2,
         "distance_m": 10, "clock_position": 6},
        CSR,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_engineer_cannot_send_notice(api):
    """PRD §2.1: "A properly identified caller who attempts an operation their role
    is not permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the
    per-endpoint role assignments are enumerated in §4."
    Notice sending is a CustomerServiceRep operation (§4); the district engineer is
    denied even with the lead time satisfied.

    Design: Corner/rbac/engineer_cannot_send_notice
    """
    ctx = setup_notice_ctx(event_start="2026-08-20T00:00:00Z", address="9 Elm St",
                           channel="MAIL")
    resp = api.send_notice(ctx["notice"]["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

"""Composite setup helpers.

Most interesting claims about this API need the plan to be in a state that takes
between five and twenty-five calls to reach: carriers enrolled, a producer
appointed, a quota period open, an applicant with a vehicle, an application with
its declinations documented and its driving record verified, a deposit recorded,
an eligibility certification, a scheduled cycle, a run, an acceptance and finally
an issued policy. These helpers encapsulate those chains.

Every helper uses the lenient ``get_success_data`` validator so that a broken
preamble surfaces as a setup failure rather than as a confusing assertion.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_applicant_payload,
    create_application_payload,
    create_assignment_cycle_payload,
    create_carrier_payload,
    create_certification_payload,
    create_claim_payload,
    create_clock_payload,
    create_complaint_payload,
    create_deposit_payload,
    create_findings_payload,
    create_market_rejection_payload,
    create_mvr_verification_payload,
    create_plan_period_payload,
    create_policy_payload,
    create_producer_payload,
    create_resolution_payload,
    create_resubmission_payload,
    create_vehicle_payload,
)
from .factories import create_cure_return_payload
from .test_users import (
    EXAMINER_ONE_USER_ID,
    EXAMINER_TWO_USER_ID,
    TEST_USERS,
    make_compliance_examiner_headers,
    make_producer_agent_headers,
    make_servicing_carrier_headers,
)

ADMIN = TEST_USERS["plan_administrator_headers"]

# The two carriers used by almost every scenario. Atlas holds the larger
# voluntary share, so largest-remainder apportionment gives it the first unit.
ATLAS = {"name": "Atlas Mutual", "naic_code": "11111",
         "voluntary_market_share_bps": 6000, "licensed_territories": ["T02"]}
BEACON = {"name": "Beacon Casualty", "naic_code": "22222",
          "voluntary_market_share_bps": 4000, "licensed_territories": ["T02"]}

# Risk profiles whose rating figures the suite pins. The driver class supplies
# the points adder, so the applicant overrides and the violation record must be
# used together.
YOUTHFUL_APPLICANT = {"driver_class": "YOUTHFUL_OPERATOR",
                      "first_licensed_date": "2024-06-01T00:00:00Z"}
SENIOR_APPLICANT = {"driver_class": "SENIOR",
                    "first_licensed_date": "1978-04-01T00:00:00Z"}


# --------------------------------------------------------------------------
# Tier 0: primitives
# --------------------------------------------------------------------------
def set_clock(current_utc: str) -> None:
    """Move the logical plan clock. Mutates no entity row."""
    get_success_data(api_client.set_current_utc(create_clock_payload(current_utc), ADMIN))


def enrol_carrier(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_carrier(create_carrier_payload(**overrides), ADMIN))


def register_producer(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_producer(create_producer_payload(**overrides), ADMIN))


def open_plan_period(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_plan_period(create_plan_period_payload(**overrides), ADMIN))


def create_applicant(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_applicant(create_applicant_payload(**overrides), ADMIN))


def create_vehicle(applicant_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_vehicle(applicant_id, create_vehicle_payload(**overrides), ADMIN))


def create_applicant_with_vehicle(applicant_overrides: Optional[Dict[str, Any]] = None,
                                  vehicle_overrides: Optional[Dict[str, Any]] = None
                                  ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create one applicant and one vehicle garaged in the applicant's territory."""
    applicant_overrides = dict(applicant_overrides or {})
    vehicle_overrides = dict(vehicle_overrides or {})
    applicant = create_applicant(**applicant_overrides)
    vehicle_overrides.setdefault("garaging_territory_code", applicant["territory_code"])
    vehicle = create_vehicle(applicant["id"], **vehicle_overrides)
    return applicant, vehicle


def read_carrier(carrier_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_carrier(carrier_id, ADMIN))


def read_producer(producer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_producer(producer_id, ADMIN))


def read_applicant(applicant_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_applicant(applicant_id, ADMIN))


def read_application(application_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_application(application_id, ADMIN))


def read_plan_period(plan_period_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_plan_period(plan_period_id, ADMIN))


def read_assignment_cycle(cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_assignment_cycle(cycle_id, ADMIN))


def read_assignment(assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_assignment(assignment_id, ADMIN))


def read_policy(policy_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_policy(policy_id, ADMIN))


def read_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_claim(claim_id, ADMIN))


def read_complaint(complaint_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_complaint(complaint_id, ADMIN))


def read_quota_reconciliation(reconciliation_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_quota_reconciliation(reconciliation_id, ADMIN))


# --------------------------------------------------------------------------
# Tier 1: the plan itself
# --------------------------------------------------------------------------
def bootstrap_plan(clock: str = "2026-09-01T00:00:00Z",
                   carriers: Optional[List[Dict[str, Any]]] = None,
                   producer_overrides: Optional[Dict[str, Any]] = None,
                   period_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Set the clock, enrol the carriers, register the producer and open a period.

    Returns ``{"carriers": [...], "carrier": <first>, "producer": ..., "plan_period": ...}``.
    """
    set_clock(clock)
    specs = carriers if carriers is not None else [ATLAS, BEACON]
    enrolled = [enrol_carrier(**spec) for spec in specs]
    producer = register_producer(**(producer_overrides or {}))
    plan_period = open_plan_period(**(period_overrides or {}))
    return {
        "carriers": enrolled,
        "carrier": enrolled[0] if enrolled else None,
        "producer": producer,
        "plan_period": plan_period,
    }


# --------------------------------------------------------------------------
# Tier 2: the application pipeline
# --------------------------------------------------------------------------
def submit_application(producer_id: str, applicant_id: str, vehicle_id: str,
                       **overrides) -> Dict[str, Any]:
    """Submit an application as the producer of record."""
    payload = create_application_payload(applicant_id, producer_id, vehicle_id, **overrides)
    return get_success_data(
        api_client.create_application(payload, make_producer_agent_headers(producer_id)))


def file_market_rejection(application_id: str, producer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_market_rejection(
        application_id, create_market_rejection_payload(**overrides),
        make_producer_agent_headers(producer_id)))


def file_two_market_rejections(application_id: str, producer_id: str,
                               document_prefix: str = "DEC",
                               first_naic: str = "11111", second_naic: str = "22222",
                               first_date: str = "2026-08-10T00:00:00Z",
                               second_date: str = "2026-08-12T00:00:00Z"
                               ) -> List[Dict[str, Any]]:
    """File the two distinct documented declinations the plan requires."""
    return [
        file_market_rejection(application_id, producer_id,
                              rejecting_carrier_naic_code=first_naic,
                              rejection_date=first_date,
                              reason_code="UNACCEPTABLE_DRIVING_RECORD",
                              document_reference=f"{document_prefix}-1"),
        file_market_rejection(application_id, producer_id,
                              rejecting_carrier_naic_code=second_naic,
                              rejection_date=second_date,
                              reason_code="UNDERWRITING_GUIDELINES",
                              document_reference=f"{document_prefix}-2"),
    ]


def verify_mvr(application_id: str, verified_violations: Optional[List[Dict[str, Any]]] = None,
               examiner_user_id: str = EXAMINER_ONE_USER_ID) -> Dict[str, Any]:
    return get_success_data(api_client.record_mvr_verification(
        application_id, create_mvr_verification_payload(verified_violations),
        make_compliance_examiner_headers(examiner_user_id)))


def record_deposit(application_id: str, producer_id: str, amount_cents: int) -> Dict[str, Any]:
    return get_success_data(api_client.record_deposit(
        application_id, create_deposit_payload(amount_cents),
        make_producer_agent_headers(producer_id)))


def certify_application(application_id: str, decision: str = "CERTIFY",
                        examiner_user_id: str = EXAMINER_ONE_USER_ID,
                        **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.decide_certification(
        application_id, create_certification_payload(decision, **overrides),
        make_compliance_examiner_headers(examiner_user_id)))


def return_for_cure(application_id: str, cure_note: str = "Declination documentation is incomplete.",
                    examiner_user_id: str = EXAMINER_ONE_USER_ID) -> Dict[str, Any]:
    return get_success_data(api_client.return_application_for_cure(
        application_id, create_cure_return_payload(cure_note),
        make_compliance_examiner_headers(examiner_user_id)))


def resubmit(application_id: str, producer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.resubmit_application(
        application_id, create_resubmission_payload(**overrides),
        make_producer_agent_headers(producer_id)))


def bring_application_to_certified(env: Dict[str, Any],
                                   applicant_overrides: Optional[Dict[str, Any]] = None,
                                   vehicle_overrides: Optional[Dict[str, Any]] = None,
                                   application_overrides: Optional[Dict[str, Any]] = None,
                                   verified_violations: Optional[List[Dict[str, Any]]] = None,
                                   deposit_cents: Optional[int] = None,
                                   document_prefix: str = "DEC",
                                   rejection_naic_codes: Tuple[str, str] = ("11111", "22222"),
                                   ) -> Dict[str, Any]:
    """Walk one risk from intake to ``CERTIFIED_AWAITING_ASSIGNMENT``.

    Two documented declinations are filed, the driving record is verified with
    ``verified_violations`` (defaulting to the declared list), the exact
    ``required_deposit_cents`` is paid unless ``deposit_cents`` overrides it, and
    the examiner certifies. Returns
    ``{"applicant": ..., "vehicle": ..., "application": ...}`` with the
    application re-read after certification.
    """
    applicant, vehicle = create_applicant_with_vehicle(applicant_overrides, vehicle_overrides)
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"],
                                     **(application_overrides or {}))
    file_two_market_rejections(application["id"], env["producer"]["id"],
                               document_prefix=document_prefix,
                               first_naic=rejection_naic_codes[0],
                               second_naic=rejection_naic_codes[1])
    if verified_violations is None:
        verified_violations = application.get("declared_violations") or []
    verify_mvr(application["id"], verified_violations)
    application = read_application(application["id"])
    amount = deposit_cents if deposit_cents is not None else application["required_deposit_cents"]
    if amount:
        record_deposit(application["id"], env["producer"]["id"], amount)
    certify_application(application["id"])
    return {"applicant": applicant, "vehicle": vehicle,
            "application": read_application(application["id"])}


# --------------------------------------------------------------------------
# Tier 3: cycles, placement and acceptance
# --------------------------------------------------------------------------
def schedule_cycle(plan_period_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_assignment_cycle(
        create_assignment_cycle_payload(plan_period_id, **overrides), ADMIN))


def run_cycle(cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.run_assignment_cycle(cycle_id, ADMIN))


def assignments_for_application(application_id: str) -> List[Dict[str, Any]]:
    data = get_success_data(
        api_client.list_assignments(ADMIN, params={"application_id": application_id}))
    return data if isinstance(data, list) else data.get("data", [])


def assignment_for_application(application_id: str) -> Dict[str, Any]:
    rows = assignments_for_application(application_id)
    assert rows, f"Setup failed: no assignment exists for application {application_id}"
    return rows[0]


def accept_assignment(assignment_id: str, carrier_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.accept_assignment(
        assignment_id, make_servicing_carrier_headers(carrier_id)))


def place_and_accept(env: Dict[str, Any], application_id: str, carrier_id: str,
                     cycle_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Schedule a cycle, run it, then have ``carrier_id`` accept the designation.

    Returns ``{"cycle": ..., "assignment": ...}``.
    """
    cycle = schedule_cycle(env["plan_period"]["id"], **(cycle_overrides or {}))
    run_cycle(cycle["id"])
    assignment = assignment_for_application(application_id)
    accept_assignment(assignment["id"], carrier_id)
    return {"cycle": read_assignment_cycle(cycle["id"]),
            "assignment": read_assignment(assignment["id"])}


# --------------------------------------------------------------------------
# Tier 4: policy issuance
# --------------------------------------------------------------------------
def issue_policy(assignment_id: str, carrier_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_policy(
        create_policy_payload(assignment_id, **overrides),
        make_servicing_carrier_headers(carrier_id)))


def setup_policy_in_force(clock: str = "2026-09-01T00:00:00Z",
                          carriers: Optional[List[Dict[str, Any]]] = None,
                          applicant_overrides: Optional[Dict[str, Any]] = None,
                          vehicle_overrides: Optional[Dict[str, Any]] = None,
                          application_overrides: Optional[Dict[str, Any]] = None,
                          verified_violations: Optional[List[Dict[str, Any]]] = None,
                          deposit_cents: Optional[int] = None,
                          period_overrides: Optional[Dict[str, Any]] = None,
                          cycle_overrides: Optional[Dict[str, Any]] = None,
                          issuance_clock: str = "2026-09-15T00:00:00Z",
                          policy_number: str = "AR-100001",
                          effective_date: str = "2026-09-15T00:00:00Z",
                          expiration_date: str = "2027-09-15T00:00:00Z",
                          document_prefix: str = "DEC",
                          ) -> Dict[str, Any]:
    """The full happy path: plan, certified risk, placement, acceptance, issuance.

    Returns every row the tests need:
    ``{"carriers", "carrier", "producer", "plan_period", "applicant", "vehicle",
       "application", "cycle", "assignment", "policy"}``.
    """
    env = bootstrap_plan(clock=clock, carriers=carriers, period_overrides=period_overrides)
    risk = bring_application_to_certified(
        env,
        applicant_overrides=applicant_overrides,
        vehicle_overrides=vehicle_overrides,
        application_overrides=application_overrides,
        verified_violations=verified_violations,
        deposit_cents=deposit_cents,
        document_prefix=document_prefix,
    )
    placed = place_and_accept(env, risk["application"]["id"], env["carriers"][0]["id"],
                              cycle_overrides=cycle_overrides)
    set_clock(issuance_clock)
    policy = issue_policy(placed["assignment"]["id"], env["carriers"][0]["id"],
                          policy_number=policy_number,
                          effective_date=effective_date,
                          expiration_date=expiration_date)
    env.update(risk)
    env.update(placed)
    env["policy"] = policy
    return env


# --------------------------------------------------------------------------
# Tier 5: claims, complaints and carrier standing
# --------------------------------------------------------------------------
def report_claim(policy_id: str, carrier_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_claim(
        create_claim_payload(policy_id, **overrides), make_servicing_carrier_headers(carrier_id)))


def acknowledge_claim(claim_id: str, carrier_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.acknowledge_claim(
        claim_id, make_servicing_carrier_headers(carrier_id)))


def docket_complaint(policy_id: str, carrier_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_complaint(
        create_complaint_payload(policy_id, carrier_id, **overrides), ADMIN))


def record_findings(complaint_id: str, examiner_user_id: str = EXAMINER_ONE_USER_ID,
                    **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.record_complaint_findings(
        complaint_id, create_findings_payload(**overrides),
        make_compliance_examiner_headers(examiner_user_id)))


def resolve_complaint(complaint_id: str, disposition: str,
                      examiner_user_id: str = EXAMINER_TWO_USER_ID, **overrides) -> Dict[str, Any]:
    return get_success_data(api_client.resolve_complaint(
        complaint_id, create_resolution_payload(disposition, **overrides),
        make_compliance_examiner_headers(examiner_user_id)))


def uphold_one_complaint(policy_id: str, carrier_id: str,
                         complaint_type: str = "CLAIM_HANDLING_DELAY",
                         narrative: str = "Acknowledgement and contact standards not met.",
                         first_examiner: str = EXAMINER_ONE_USER_ID,
                         second_examiner: str = EXAMINER_TWO_USER_ID) -> Dict[str, Any]:
    """Docket a complaint, record findings and uphold it — a 20-point deduction."""
    complaint = docket_complaint(policy_id, carrier_id, complaint_type=complaint_type,
                                narrative=narrative)
    record_findings(complaint["id"], first_examiner)
    resolve_complaint(complaint["id"], "UPHELD", second_examiner)
    return read_complaint(complaint["id"])


def drive_carrier_to_suspension(policy_id: str, carrier_id: str) -> Dict[str, Any]:
    """Two upheld complaints move a fresh carrier 100 to 80 to 60, so its posture
    lands on SUSPENDED. Returns the carrier as re-read afterwards."""
    uphold_one_complaint(policy_id, carrier_id, complaint_type="CLAIM_HANDLING_DELAY",
                         narrative="Acknowledgement and contact standards not met.")
    uphold_one_complaint(policy_id, carrier_id, complaint_type="SERVICE_STANDARD",
                         narrative="Second substantiated servicing failure.")
    return read_carrier(carrier_id)

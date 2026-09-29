"""Composite setup helpers.

Most claims worth testing in this API need the fund office in a state that
takes ten or more calls to reach: a fund has to be chartered, a board seated,
an employer registered, participants enrolled, a report filed and posted, the
clock advanced past a due date, a collections run swept, a motion moved,
voted and tallied.  These helpers build those preambles once.

Every helper reads its responses with the lenient success reader so a broken
preamble surfaces as a setup failure rather than as a confusing assertion
failure deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS as D
from .factories import (
    audit_finding_payload,
    contribution_line_payload,
    create_board_motion_payload,
    create_contribution_report_payload,
    create_employer_payload,
    create_fund_payload,
    create_motion_vote_payload,
    create_participant_payload,
    create_payroll_audit_payload,
    create_reciprocity_transfer_payload,
    create_sister_fund_payload,
    create_trustee_payload,
    create_withdrawal_assessment_payload,
)
from .test_users import (
    ACTUARY_USER_ID,
    ADMIN_USER_ID,
    AUDITOR_USER_ID,
    TEST_USERS,
    make_employer_headers,
    make_trustee_headers,
)

ADMIN = TEST_USERS["fund_administrator_headers"]
AUDITOR = TEST_USERS["payroll_auditor_headers"]
ACTUARY = TEST_USERS["actuary_headers"]

# ------------------------------------------------------------------ clock ---


def set_clock(to_iso8601: str = None) -> str:
    """Move the logical clock and return the instant it now reads."""
    to_iso8601 = to_iso8601 or D["CLOCK"]
    data = get_success_data(api_client.set_clock(to_iso8601, ADMIN))
    return data.get("current_utc", to_iso8601)


# ------------------------------------------------------- registry primitives ---


def create_fund(**overrides) -> dict:
    return get_success_data(api_client.create_fund(create_fund_payload(**overrides), ADMIN))


def create_sister_fund(**overrides) -> dict:
    return get_success_data(
        api_client.create_fund(create_sister_fund_payload(**overrides), ADMIN)
    )


def create_employer(fund_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_employer(create_employer_payload(fund_id, **overrides), ADMIN)
    )


def create_participant(fund_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_participant(
            create_participant_payload(fund_id, **overrides), ADMIN
        )
    )


def create_trustee(fund_id: str, appointing_party: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_trustee(
            create_trustee_payload(fund_id, appointing_party, **overrides), ADMIN
        )
    )


def seat_board(fund_id: str, union: int = 3, employer: int = 3) -> dict:
    """Seat `union` UNION and `employer` EMPLOYER trustees on one fund's board.

    Returns {"union": [ids], "employer": [ids]}.  Two of each is the floor for
    an OPEN posture; three of each leaves a mover plus two voters per party.
    """
    union_ids = [
        create_trustee(fund_id, "UNION", full_name=f"Union Trustee {n + 1}")["id"]
        for n in range(union)
    ]
    employer_ids = [
        create_trustee(fund_id, "EMPLOYER", full_name=f"Employer Trustee {n + 1}")["id"]
        for n in range(employer)
    ]
    return {"union": union_ids, "employer": employer_ids}


# ------------------------------------------------------------------ reads ---


def read_fund(fund_id: str) -> dict:
    return get_success_data(api_client.get_fund(fund_id, ADMIN))


def read_employer(employer_id: str) -> dict:
    return get_success_data(api_client.get_employer(employer_id, ADMIN))


def read_participant(participant_id: str) -> dict:
    return get_success_data(api_client.get_participant(participant_id, ADMIN))


def read_report(report_id: str) -> dict:
    return get_success_data(api_client.get_contribution_report(report_id, ADMIN))


def read_audit(audit_id: str) -> dict:
    return get_success_data(api_client.get_payroll_audit(audit_id, ADMIN))


def read_withdrawal(assessment_id: str) -> dict:
    return get_success_data(api_client.get_withdrawal_assessment(assessment_id, ADMIN))


def read_motion(motion_id: str) -> dict:
    return get_success_data(api_client.get_board_motion(motion_id, ADMIN))


def read_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.get_reciprocity_transfer(transfer_id, ADMIN))


def employer_version(employer_id: str) -> int:
    return read_employer(employer_id)["version"]


def fund_version(fund_id: str) -> int:
    return read_fund(fund_id)["version"]


def list_coverage_months(**params) -> list:
    return get_success_data(api_client.list_coverage_months(ADMIN, params=params))


def granted_coverage_months(participant_id: str) -> list:
    return list_coverage_months(participant_id=participant_id, status="GRANTED", limit=100)


def revoked_coverage_months(participant_id: str) -> list:
    return list_coverage_months(participant_id=participant_id, status="REVOKED", limit=100)


def coverage_month_keys(rows: list) -> list:
    return [row["coverage_month"] for row in rows]


def list_report_lines(report_id: str) -> list:
    return get_success_data(
        api_client.list_report_lines(report_id, ADMIN, params={"limit": 100})
    )


def line_for_participant(report_id: str, participant_id: str) -> dict:
    for line in list_report_lines(report_id):
        if line["participant_id"] == participant_id:
            return line
    raise AssertionError(
        f"Setup failed: no contribution line for participant {participant_id} "
        f"on report {report_id}"
    )


def list_pension_accruals(participant_id: str, **params) -> list:
    params.setdefault("limit", 100)
    return get_success_data(
        api_client.list_pension_accruals(participant_id, ADMIN, params=params)
    )


def accrual_for(participant_id: str, plan_year: int) -> dict:
    for row in list_pension_accruals(participant_id):
        if row["plan_year"] == plan_year:
            return row
    raise AssertionError(
        f"Setup failed: participant {participant_id} has no accrual row for "
        f"plan year {plan_year}"
    )


def list_installments(assessment_id: str, **params) -> list:
    params.setdefault("limit", 100)
    return get_success_data(
        api_client.list_installments(assessment_id, ADMIN, params=params)
    )


def list_reports(**params) -> list:
    params.setdefault("limit", 100)
    return get_success_data(api_client.list_contribution_reports(ADMIN, params=params))


def list_report_assessments(report_id: str, **params) -> list:
    params.setdefault("limit", 100)
    return get_success_data(
        api_client.list_report_delinquency_assessments(report_id, ADMIN, params=params)
    )


# -------------------------------------------------------- report primitives ---


def file_report(
    employer_id: str,
    work_period: str,
    lines: list,
    headers: dict = None,
    expected_employer_version: int = None,
    **overrides,
) -> dict:
    """File one contribution report, reading the employer's live version first."""
    if expected_employer_version is None:
        expected_employer_version = employer_version(employer_id)
    payload = create_contribution_report_payload(
        employer_id, work_period, expected_employer_version, lines, **overrides
    )
    return get_success_data(
        api_client.create_contribution_report(payload, headers or ADMIN)
    )


def file_single_line_report(
    employer_id: str,
    participant_id: str,
    work_period: str,
    hours: float,
    gross_wages_cents: int = 400_000,
    work_classification: str = "JOURNEYMAN",
    headers: dict = None,
    **overrides,
) -> dict:
    return file_report(
        employer_id,
        work_period,
        [
            contribution_line_payload(
                participant_id, hours, gross_wages_cents, work_classification
            )
        ],
        headers=headers,
        **overrides,
    )


def post_report(report_id: str) -> dict:
    return get_success_data(api_client.post_contribution_report(report_id, ADMIN))


def file_and_post_single_line_report(
    employer_id: str,
    participant_id: str,
    work_period: str,
    hours: float,
    **overrides,
) -> dict:
    report = file_single_line_report(
        employer_id, participant_id, work_period, hours, **overrides
    )
    return post_report(report["id"])


def remit(report_id: str, amount_cents: int, headers: dict = None) -> dict:
    return get_success_data(
        api_client.remit_contribution_report(
            report_id, {"amount_cents": amount_cents}, headers or ADMIN
        )
    )


def assess_delinquency(report_id: str, basis: str) -> dict:
    return get_success_data(
        api_client.create_delinquency_assessment(report_id, {"basis": basis}, ADMIN)
    )


def settle_assessment(assessment_id: str, settlement_amount_cents: int) -> dict:
    return get_success_data(
        api_client.settle_delinquency_assessment(
            assessment_id, {"settlement_amount_cents": settlement_amount_cents}, ADMIN
        )
    )


def run_collections(fund_id: str) -> dict:
    return get_success_data(api_client.run_collections(fund_id, ADMIN))


# --------------------------------------------------------- audit primitives ---


def open_audit(
    employer_id: str,
    period_start_month: str,
    period_end_month: str,
    headers: dict = None,
) -> dict:
    return get_success_data(
        api_client.create_payroll_audit(
            create_payroll_audit_payload(
                employer_id, period_start_month, period_end_month
            ),
            headers or AUDITOR,
        )
    )


def issue_findings(audit_id: str, findings: list, headers: dict = None) -> dict:
    return get_success_data(
        api_client.issue_audit_findings(audit_id, {"findings": findings}, headers or AUDITOR)
    )


def respond_to_audit(
    audit_id: str, employer_id: str, response: str, dispute_note: str = None
) -> dict:
    payload = {"response": response}
    if dispute_note is not None:
        payload["dispute_note"] = dispute_note
    return get_success_data(
        api_client.respond_to_audit(audit_id, payload, make_employer_headers(employer_id))
    )


def finalize_audit(audit_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.finalize_payroll_audit(audit_id, headers or ADMIN)
    )


# ---------------------------------------------------- withdrawal primitives ---


def open_withdrawal(
    fund_id: str,
    employer_id: str,
    method: str = "PRESUMPTIVE",
    withdrawal_date: str = "2026-03-31",
    **overrides,
) -> dict:
    payload = create_withdrawal_assessment_payload(
        employer_id, fund_version(fund_id), method, withdrawal_date, **overrides
    )
    return get_success_data(api_client.create_withdrawal_assessment(payload, ADMIN))


def certify_withdrawal(assessment_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.certify_withdrawal_assessment(assessment_id, headers or ACTUARY)
    )


def demand_withdrawal(assessment_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.demand_withdrawal_assessment(assessment_id, headers or ADMIN)
    )


def request_withdrawal_review(assessment_id: str, employer_id: str, grounds: str) -> dict:
    return get_success_data(
        api_client.request_withdrawal_review(
            assessment_id, {"grounds": grounds}, make_employer_headers(employer_id)
        )
    )


def pay_installment(installment_id: str, amount_cents: int, employer_id: str) -> dict:
    return get_success_data(
        api_client.pay_installment(
            installment_id,
            {"amount_cents": amount_cents},
            make_employer_headers(employer_id),
        )
    )


# ------------------------------------------------------ governance primitives ---


def move_motion(
    fund_id: str, subject_type: str, subject_ref_id: str, trustee_id: str
) -> dict:
    return get_success_data(
        api_client.create_board_motion(
            create_board_motion_payload(fund_id, subject_type, subject_ref_id),
            make_trustee_headers(trustee_id),
        )
    )


def cast_vote(motion_id: str, trustee_id: str, position: str) -> dict:
    return get_success_data(
        api_client.create_motion_vote(
            create_motion_vote_payload(motion_id, position),
            make_trustee_headers(trustee_id),
        )
    )


def tally_motion(motion_id: str, arbitration_award: str = None) -> dict:
    payload = {} if arbitration_award is None else {"arbitration_award": arbitration_award}
    return get_success_data(api_client.tally_board_motion(motion_id, payload, ADMIN))


def carry_motion(
    fund_id: str, subject_type: str, subject_ref_id: str, board: dict
) -> dict:
    """Move a motion on the first union seat, vote it FOR on both blocs, tally it.

    The mover is barred from voting, so the union bloc is carried by seats 2 and
    3 and the employer bloc by seats 1 and 2 — two counting votes per party,
    which is exactly the quorum floor.
    """
    motion = move_motion(fund_id, subject_type, subject_ref_id, board["union"][0])
    cast_vote(motion["id"], board["union"][1], "FOR")
    cast_vote(motion["id"], board["union"][2], "FOR")
    cast_vote(motion["id"], board["employer"][0], "FOR")
    cast_vote(motion["id"], board["employer"][1], "FOR")
    return tally_motion(motion["id"])


# ---------------------------------------------------- reciprocity primitives ---


def create_transfer(
    participant_id: str,
    sister_fund_id: str,
    transfer_type: str,
    work_period: str,
    hours: float,
    amount_cents: int,
) -> dict:
    return get_success_data(
        api_client.create_reciprocity_transfer(
            create_reciprocity_transfer_payload(
                participant_id,
                sister_fund_id,
                transfer_type,
                work_period,
                hours,
                amount_cents,
            ),
            ADMIN,
        )
    )


def decide_transfer(transfer_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_reciprocity_transfer(transfer_id, {"decision": decision}, ADMIN)
    )


def execute_reciprocity_agreement(fund_id: str, sister_fund_id: str, board: dict) -> dict:
    """Carry a reciprocity-agreement motion so the sister fund reads EXECUTED."""
    return carry_motion(fund_id, "RECIPROCITY_AGREEMENT", sister_fund_id, board)


# =====================================================================
# Composite scenarios.  Each builds the whole preamble a family of
# claims needs, stopping immediately before the act under test.
# =====================================================================


def setup_employer_with_three_participants(**fund_overrides) -> dict:
    """Clock at 2026-04-01, one fund, one employer at 825500 millicents, three workers."""
    set_clock()
    fund = create_fund(**fund_overrides)
    employer = create_employer(fund["id"])
    participants = [
        create_participant(fund["id"], full_name="Ada Kowalski", ssn_last4="4417"),
        create_participant(fund["id"], full_name="Bo Ferreira", ssn_last4="2290"),
        create_participant(fund["id"], full_name="Cy Nakamura", ssn_last4="8813"),
    ]
    return {"fund": fund, "employer": employer, "participants": participants}


def setup_employer_with_one_participant(clock: str = None, **fund_overrides) -> dict:
    """Clock, one fund, one employer and one enrolled worker."""
    set_clock(clock)
    fund = create_fund(**fund_overrides)
    employer = create_employer(fund["id"])
    participant = create_participant(fund["id"])
    return {"fund": fund, "employer": employer, "participant": participant}


THREE_LINE_FILING = [
    ("151.30", "JOURNEYMAN", 600_000),
    ("148.70", "APPRENTICE", 520_000),
    ("166.10", "FOREMAN", 710_000),
]


def three_line_payload(participants: list) -> list:
    """The 151.30 JOURNEYMAN / 148.70 APPRENTICE / 166.10 FOREMAN filing."""
    return [
        contribution_line_payload(
            participants[0]["id"], 151.30, 600_000, "JOURNEYMAN"
        ),
        contribution_line_payload(
            participants[1]["id"], 148.70, 520_000, "APPRENTICE"
        ),
        contribution_line_payload(participants[2]["id"], 166.10, 710_000, "FOREMAN"),
    ]


def setup_three_line_report_sixty_days_late() -> dict:
    """The 357668-cent 2026-03 filing, unpaid, with the clock at 2026-06-19.

    Its due date is 2026-04-20, so the report is exactly 60 days late — the
    top of the middle liquidated-damages tier.
    """
    base = setup_employer_with_three_participants()
    report = file_report(
        base["employer"]["id"],
        "2026-03",
        three_line_payload(base["participants"]),
        headers=make_employer_headers(base["employer"]["id"]),
    )
    set_clock("2026-06-19T00:00:00Z")
    base["report"] = report
    return base


def setup_two_funds_differing_accrual_method() -> dict:
    """Two funds identical but for accrual_method, each with one 151.30-hour filing."""
    set_clock()
    fund_hours = create_fund(
        name="Hours Based Fund", ein="36-1000001", accrual_method="HOURS_BASED"
    )
    fund_elapsed = create_fund(
        name="Elapsed Time Fund", ein="36-1000002", accrual_method="ELAPSED_TIME"
    )
    employer_hours = create_employer(
        fund_hours["id"], legal_name="Hours Employer", ein="36-2000001"
    )
    employer_elapsed = create_employer(
        fund_elapsed["id"], legal_name="Elapsed Employer", ein="36-2000002"
    )
    participant_hours = create_participant(
        fund_hours["id"], full_name="Hana Ito", ssn_last4="1001"
    )
    participant_elapsed = create_participant(
        fund_elapsed["id"], full_name="Emil Novak", ssn_last4="1002"
    )
    report_hours = file_single_line_report(
        employer_hours["id"], participant_hours["id"], "2026-03", 151.30, 600_000
    )
    report_elapsed = file_single_line_report(
        employer_elapsed["id"], participant_elapsed["id"], "2026-03", 151.30, 600_000
    )
    return {
        "fund_hours": fund_hours,
        "fund_elapsed": fund_elapsed,
        "employer_hours": employer_hours,
        "employer_elapsed": employer_elapsed,
        "participant_hours": participant_hours,
        "participant_elapsed": participant_elapsed,
        "report_hours": report_hours,
        "report_elapsed": report_elapsed,
    }


def setup_tiny_base_unit_employer() -> dict:
    """A fund untouched at 100000000 cents and an employer with 60% of the pool
    but only 100 base units a year, so the annual payment is tiny."""
    set_clock()
    fund = create_fund(name="Cap Test Fund", ein="36-1200001")
    employer = create_employer(
        fund["id"],
        legal_name="Capstone Erectors",
        ein="36-9000001",
        prior_year_contributions_cents=[12_000_000] * 5,
        prior_year_base_units=[100] * 5,
    )
    return {"fund": fund, "employer": employer}


def setup_filed_single_line_report(hours: float = 151.30, work_period: str = "2026-03") -> dict:
    """A SUBMITTED, UNPAID report filed by the employer itself."""
    base = setup_employer_with_one_participant()
    base["report"] = file_single_line_report(
        base["employer"]["id"],
        base["participant"]["id"],
        work_period,
        hours,
        600_000,
        headers=make_employer_headers(base["employer"]["id"]),
    )
    return base


def setup_audit_in_fieldwork(
    clock: str = "2026-07-01T00:00:00Z",
    period_start_month: str = "2026-01",
    period_end_month: str = "2026-06",
) -> dict:
    """One employer, one worker and an audit sitting in IN_FIELDWORK at round 1."""
    base = setup_employer_with_one_participant(clock=clock)
    base["audit"] = open_audit(
        base["employer"]["id"], period_start_month, period_end_month
    )
    return base


def setup_audit_accepted_without_board_approval() -> dict:
    """An audit whose 100.00-hour finding the employer has ACCEPTED, with no motion."""
    base = setup_audit_in_fieldwork()
    issue_findings(
        base["audit"]["id"],
        [audit_finding_payload(base["participant"]["id"], "2026-04", 100.00)],
    )
    respond_to_audit(base["audit"]["id"], base["employer"]["id"], "ACCEPT")
    base["audit"] = read_audit(base["audit"]["id"])
    return base


def setup_audit_ready_to_finalize() -> dict:
    """Everything the four-hop finalize cascade needs, stopping before finalize.

    A 2026-03 filing of 151.30 hours was posted at 2026-04-01, leaving the
    worker with one GRANTED coverage month for 2026-05 and 31.30 banked hours.
    The clock then moved to 2026-07-01, which makes that worker NOT_ELIGIBLE.
    An audit over 2026-01..2026-06 has a 100.00-hour finding the employer has
    accepted, and the joint board has carried the settlement motion.
    """
    set_clock()
    fund = create_fund(name="Cascade Fund", ein="36-1500001")
    employer = create_employer(fund["id"])
    participant = create_participant(fund["id"])
    board = seat_board(fund["id"], union=3, employer=3)
    report = file_single_line_report(
        employer["id"],
        participant["id"],
        "2026-03",
        151.30,
        600_000,
        headers=make_employer_headers(employer["id"]),
    )
    post_report(report["id"])
    set_clock("2026-07-01T00:00:00Z")
    audit = open_audit(employer["id"], "2026-01", "2026-06")
    issue_findings(
        audit["id"], [audit_finding_payload(participant["id"], "2026-04", 100.00)]
    )
    respond_to_audit(audit["id"], employer["id"], "ACCEPT")
    motion = carry_motion(fund["id"], "AUDIT_SETTLEMENT", audit["id"], board)
    return {
        "fund": fund,
        "employer": employer,
        "participant": participant,
        "board": board,
        "report": report,
        "audit": audit,
        "motion": motion,
    }


def setup_three_reports_past_grace() -> dict:
    """Three 82550-cent reports for 2026-01/02/03, all unpaid, clock at 2026-06-19.

    Their due dates are 2026-02-20, 2026-03-20 and 2026-04-20, so every one of
    them sits past its due date plus the fund's 15 grace days.
    """
    set_clock()
    fund = create_fund(name="Collections Fund", ein="36-1600001")
    employer = create_employer(fund["id"])
    participant = create_participant(fund["id"])
    reports = []
    for work_period in ("2026-01", "2026-02", "2026-03"):
        reports.append(
            file_single_line_report(
                employer["id"],
                participant["id"],
                work_period,
                100.00,
                400_000,
                headers=make_employer_headers(employer["id"]),
            )
        )
    set_clock("2026-06-19T00:00:00Z")
    return {
        "fund": fund,
        "employer": employer,
        "participant": participant,
        "reports": reports,
    }


def setup_amendment_pair_ready_to_post() -> dict:
    """A POSTED 151.30-hour 2026-03 report and a SUBMITTED 100.00-hour amendment."""
    base = setup_employer_with_one_participant()
    original = file_single_line_report(
        base["employer"]["id"],
        base["participant"]["id"],
        "2026-03",
        151.30,
        600_000,
        headers=make_employer_headers(base["employer"]["id"]),
    )
    post_report(original["id"])
    amendment = file_single_line_report(
        base["employer"]["id"],
        base["participant"]["id"],
        "2026-03",
        100.00,
        400_000,
        headers=make_employer_headers(base["employer"]["id"]),
        amends_report_id=original["id"],
    )
    base["original"] = original
    base["amendment"] = amendment
    return base


def setup_superseded_report_pair() -> dict:
    """The amendment above, posted, so the original now reads SUPERSEDED."""
    base = setup_amendment_pair_ready_to_post()
    post_report(base["amendment"]["id"])
    base["original"] = read_report(base["original"]["id"])
    base["amendment"] = read_report(base["amendment"]["id"])
    return base


def setup_withdrawn_employer_holding_a_live_report() -> dict:
    """An employer holding one SUBMITTED 2026-03 report, then driven to WITHDRAWN."""
    base = setup_employer_with_one_participant()
    base["report"] = file_single_line_report(
        base["employer"]["id"],
        base["participant"]["id"],
        "2026-03",
        151.30,
        600_000,
        headers=make_employer_headers(base["employer"]["id"]),
    )
    base["assessment"] = open_withdrawal(base["fund"]["id"], base["employer"]["id"])
    base["employer"] = read_employer(base["employer"]["id"])
    return base


def setup_withdrawn_employer_after_a_successful_filing() -> dict:
    """Clock at 2026-05-01: a 2026-03 filing succeeded while ACTIVE, then the
    employer withdrew, leaving a fresh 2026-04 work period entirely unoccupied."""
    base = setup_employer_with_one_participant(clock="2026-05-01T00:00:00Z")
    base["march_report"] = file_single_line_report(
        base["employer"]["id"],
        base["participant"]["id"],
        "2026-03",
        100.00,
        400_000,
        headers=make_employer_headers(base["employer"]["id"]),
    )
    base["assessment"] = open_withdrawal(
        base["fund"]["id"], base["employer"]["id"], withdrawal_date="2026-04-30"
    )
    base["employer"] = read_employer(base["employer"]["id"])
    return base


def setup_de_minimis_boundary_employers() -> dict:
    """Two employers whose five-year contributions total 10000000 and 10000001."""
    set_clock()
    fund = create_fund(name="De Minimis Fund", ein="36-1900001")
    at_boundary = create_employer(
        fund["id"],
        legal_name="Boundary Steel",
        ein="36-9100001",
        prior_year_contributions_cents=[2_000_000] * 5,
        prior_year_base_units=[1000] * 5,
    )
    over_boundary = create_employer(
        fund["id"],
        legal_name="Crossline Steel",
        ein="36-9100002",
        prior_year_contributions_cents=[2_000_000, 2_000_000, 2_000_000, 2_000_000, 2_000_001],
        prior_year_base_units=[1000] * 5,
    )
    return {"fund": fund, "at_boundary": at_boundary, "over_boundary": over_boundary}


def setup_vesting_boundary_report() -> dict:
    """One 2026-03 filing whose two JOURNEYMAN lines carry 870.00 and 869.99 hours."""
    set_clock()
    fund = create_fund(name="Vesting Boundary Fund", ein="36-2000001")
    employer = create_employer(fund["id"])
    at_threshold = create_participant(
        fund["id"], full_name="Vera Exact", ssn_last4="8700"
    )
    under_threshold = create_participant(
        fund["id"], full_name="Una Short", ssn_last4="8699"
    )
    report = file_report(
        employer["id"],
        "2026-03",
        [
            contribution_line_payload(at_threshold["id"], 870.00, 3_500_000, "JOURNEYMAN"),
            contribution_line_payload(
                under_threshold["id"], 869.99, 3_499_960, "JOURNEYMAN"
            ),
        ],
        headers=make_employer_headers(employer["id"]),
    )
    return {
        "fund": fund,
        "employer": employer,
        "at_threshold": at_threshold,
        "under_threshold": under_threshold,
        "report": report,
    }


def setup_frozen_board_with_certified_assessment() -> dict:
    """A fund with no trustees at all — posture FROZEN — holding a CERTIFIED assessment."""
    set_clock()
    fund = create_fund(name="Frozen Board Fund", ein="36-2200001")
    employer = create_employer(fund["id"])
    assessment = open_withdrawal(fund["id"], employer["id"])
    certify_withdrawal(assessment["id"])
    return {
        "fund": fund,
        "employer": employer,
        "assessment": read_withdrawal(assessment["id"]),
    }


def setup_employer_with_first_audit_window() -> dict:
    """Clock at 2027-01-01 with one IN_FIELDWORK audit covering 2026-01..2026-06."""
    set_clock("2027-01-01T00:00:00Z")
    fund = create_fund(name="Audit Interval Fund", ein="36-2300001")
    employer = create_employer(fund["id"])
    audit = open_audit(employer["id"], "2026-01", "2026-06")
    return {"fund": fund, "employer": employer, "audit": audit}


def setup_reciprocity_horizon_scenario() -> dict:
    """A worker holding 12 coverage months, 11 of them beyond the 2026-05 clock.

    A 1560.00-hour 2026-03 filing bought 2026-05 through 2027-04 and banked
    120.00 hours, so the advance allowance is exactly one further month.  Two
    transfers wait on a decision: 240.00 hours (three months' worth) and 60.00
    hours (one month's worth).
    """
    set_clock("2026-05-01T00:00:00Z")
    fund = create_fund(name="Horizon Home Fund", ein="36-2400001")
    sister = create_sister_fund()
    board = seat_board(fund["id"], union=3, employer=3)
    execute_reciprocity_agreement(fund["id"], sister["id"], board)
    employer = create_employer(fund["id"])
    participant = create_participant(fund["id"])
    report = file_single_line_report(
        employer["id"],
        participant["id"],
        "2026-03",
        1560.00,
        6_300_000,
        headers=make_employer_headers(employer["id"]),
    )
    post_report(report["id"])
    oversized = create_transfer(
        participant["id"], sister["id"], "MONEY_FOLLOWS_MAN", "2026-04", 240.00, 198_120
    )
    fitting = create_transfer(
        participant["id"], sister["id"], "MONEY_FOLLOWS_MAN", "2026-04", 60.00, 49_530
    )
    return {
        "fund": fund,
        "sister": sister,
        "board": board,
        "employer": employer,
        "participant": participant,
        "report": report,
        "oversized_transfer": oversized,
        "fitting_transfer": fitting,
    }


def setup_ld_waiver_ready_to_tally() -> dict:
    """A SUSPENDED employer whose only remaining debt is one 100281-cent assessment.

    Three 82550-cent reports were swept DELINQUENT by a collections run, taking
    delinquency_strikes to three and the employer to SUSPENDED.  A STATUTORY
    assessment worth 100281 cents was raised on the March report, and all three
    reports were then remitted in full — so the ledger stands at exactly the
    assessment.  An LD_WAIVER motion is open with two FOR votes from each bloc.
    """
    set_clock()
    fund = create_fund(name="Waiver Ledger Fund", ein="36-2600001")
    board = seat_board(fund["id"], union=3, employer=3)
    employer = create_employer(fund["id"])
    participant = create_participant(fund["id"])
    reports = []
    for work_period in ("2026-01", "2026-02", "2026-03"):
        reports.append(
            file_single_line_report(
                employer["id"],
                participant["id"],
                work_period,
                100.00,
                400_000,
                headers=make_employer_headers(employer["id"]),
            )
        )
    set_clock("2026-06-19T00:00:00Z")
    run_collections(fund["id"])
    assessment = assess_delinquency(reports[2]["id"], "STATUTORY")
    for report in reports:
        remit(report["id"], 82_550, make_employer_headers(employer["id"]))
    motion = move_motion(fund["id"], "LD_WAIVER", assessment["id"], board["union"][0])
    cast_vote(motion["id"], board["union"][1], "FOR")
    cast_vote(motion["id"], board["union"][2], "FOR")
    cast_vote(motion["id"], board["employer"][0], "FOR")
    cast_vote(motion["id"], board["employer"][1], "FOR")
    return {
        "fund": fund,
        "board": board,
        "employer": employer,
        "participant": participant,
        "reports": reports,
        "assessment": assessment,
        "motion": motion,
    }


def setup_assessed_report(clock_at_assessment: str = "2026-06-19T00:00:00Z") -> dict:
    """One 82550-cent 2026-03 report, unpaid, with one ASSESSED STATUTORY charge.

    The assessment is raised 60 days after the 2026-04-20 due date and is worth
    100281 cents, so the employer ledger reads 182831.
    """
    base = setup_employer_with_one_participant()
    report = file_single_line_report(
        base["employer"]["id"],
        base["participant"]["id"],
        "2026-03",
        100.00,
        400_000,
    )
    set_clock(clock_at_assessment)
    base["report"] = report
    base["assessment"] = assess_delinquency(report["id"], "STATUTORY")
    return base


def setup_ld_waiver_motion_voted_against() -> dict:
    """An LD_WAIVER motion carrying two AGAINST votes from each bargaining party."""
    set_clock()
    fund = create_fund(name="Failed Motion Fund", ein="36-4000009")
    board = seat_board(fund["id"], union=3, employer=3)
    employer = create_employer(fund["id"])
    participant = create_participant(fund["id"])
    report = file_single_line_report(employer["id"], participant["id"], "2026-03", 100.00)
    set_clock("2026-06-19T00:00:00Z")
    assessment = assess_delinquency(report["id"], "STATUTORY")
    motion = move_motion(fund["id"], "LD_WAIVER", assessment["id"], board["union"][0])
    cast_vote(motion["id"], board["union"][1], "AGAINST")
    cast_vote(motion["id"], board["union"][2], "AGAINST")
    cast_vote(motion["id"], board["employer"][0], "AGAINST")
    cast_vote(motion["id"], board["employer"][1], "AGAINST")
    return {
        "fund": fund,
        "board": board,
        "employer": employer,
        "report": report,
        "assessment": assessment,
        "motion": motion,
    }


def setup_demanded_assessment(
    fund_name: str = "Installment Fund",
    fund_ein: str = "36-6000007",
    employer_overrides: dict = None,
    union_seats: int = 1,
    employer_seats: int = 1,
) -> dict:
    """A certified and demanded assessment with its installment schedule minted.

    The board is seated one-and-one, which reads RESTRICTED rather than FROZEN,
    so a demand may issue.  The demand is made by admin-001, an identity
    distinct from the certifying actuary.
    """
    set_clock()
    fund = create_fund(name=fund_name, ein=fund_ein)
    seat_board(fund["id"], union=union_seats, employer=employer_seats)
    employer = create_employer(fund["id"], **(employer_overrides or {}))
    assessment = open_withdrawal(fund["id"], employer["id"])
    certify_withdrawal(assessment["id"])
    demand_withdrawal(assessment["id"])
    return {
        "fund": fund,
        "employer": employer,
        "assessment": read_withdrawal(assessment["id"]),
        "installments": list_installments(assessment["id"]),
    }


def setup_boundary_steel_demanded() -> dict:
    """Employer B's 9250000-cent liability over 12 installments, demanded 2026-04-01."""
    return setup_demanded_assessment(
        fund_name="Default Cascade Fund",
        fund_ein="36-4000011",
        employer_overrides={
            "legal_name": "Boundary Steel",
            "ein": "36-9100001",
            "prior_year_contributions_cents": [2_000_000] * 5,
            "prior_year_base_units": [1000] * 5,
        },
    )


def setup_single_installment_demanded() -> dict:
    """A small employer whose 250000-cent liability fits inside one installment."""
    return setup_demanded_assessment(
        fund_name="Single Installment Fund",
        fund_ein="36-4000012",
        employer_overrides={
            "legal_name": "Small Shop Mechanical",
            "ein": "36-9200001",
            "prior_year_contributions_cents": [200_000] * 5,
            "prior_year_base_units": [1000] * 5,
        },
    )


def setup_assessment_under_review() -> dict:
    """A demanded 25000000-cent assessment whose employer has requested review."""
    base = setup_demanded_assessment(
        fund_name="Review Revision Fund", fund_ein="36-4000010"
    )
    request_withdrawal_review(
        base["assessment"]["id"],
        base["employer"]["id"],
        "the fund overstated the unfunded vested benefit pool",
    )
    base["assessment"] = read_withdrawal(base["assessment"]["id"])
    return base


def setup_open_board_with_sister_fund(union: int = 3, employer: int = 3) -> dict:
    """A HOME fund with a seated board plus a registered SISTER counterparty."""
    set_clock("2026-05-01T00:00:00Z")
    fund = create_fund(name="Board Fund", ein="36-4000007")
    sister = create_sister_fund(name="Board Sister Fund", ein="36-4000008")
    board = seat_board(fund["id"], union=union, employer=employer)
    return {"fund": fund, "sister": sister, "board": board}


def setup_two_employers_one_filed_report() -> dict:
    """Two employers in one fund; the first holds an 82550-cent 2026-03 report."""
    set_clock()
    fund = create_fund(name="Ownership Fund", ein="36-7000004")
    owner = create_employer(fund["id"])
    rival = create_employer(fund["id"], legal_name="Rival Piping", ein="36-7654399")
    participant = create_participant(fund["id"])
    report = file_single_line_report(
        owner["id"],
        participant["id"],
        "2026-03",
        100.00,
        400_000,
        headers=make_employer_headers(owner["id"]),
    )
    return {
        "fund": fund,
        "owner": owner,
        "rival": rival,
        "participant": participant,
        "report": report,
    }


def setup_intake_guard_scenario() -> dict:
    """Two funds, one filing employer, its own worker, a worker of the other fund,
    and one SUBMITTED 2026-03 report already occupying that work period."""
    set_clock()
    fund_a = create_fund(name="Intake Guard Fund A", ein="36-6000001")
    fund_b = create_fund(name="Intake Guard Fund B", ein="36-6000002")
    employer = create_employer(fund_a["id"])
    participant = create_participant(fund_a["id"])
    foreign_participant = create_participant(
        fund_b["id"], full_name="Foreign Fund Worker", ssn_last4="9999"
    )
    report = file_single_line_report(employer["id"], participant["id"], "2026-03", 100.00)
    return {
        "fund_a": fund_a,
        "fund_b": fund_b,
        "employer": employer,
        "participant": participant,
        "foreign_participant": foreign_participant,
        "report": report,
    }


def setup_pending_transfer_without_agreement() -> dict:
    """A HOME fund, a worker, and a genuine SISTER fund still at agreement NONE."""
    set_clock("2026-05-01T00:00:00Z")
    fund = create_fund(name="Reciprocity Guard Home", ein="36-6000008")
    sister = create_sister_fund(name="Reciprocity Guard Sister", ein="36-6000009")
    participant = create_participant(fund["id"])
    transfer = create_transfer(
        participant["id"], sister["id"], "PRO_RATA", "2026-03", 120.00, 99_060
    )
    return {
        "fund": fund,
        "sister": sister,
        "participant": participant,
        "transfer": transfer,
    }

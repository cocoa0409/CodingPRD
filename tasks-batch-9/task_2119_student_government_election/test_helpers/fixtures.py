"""Composite setup helpers.

Almost nothing interesting in an election cycle is reachable in one request: a
share percentage needs a calendar, a seat, an electorate, filings, signatures,
a ballot, a lock, a publication, a window and a handful of cast ballots before
a single number can be asserted. These helpers encapsulate those preambles so
the tests carry assertions rather than plumbing.

Setup calls use the lenient validator so a broken preamble reports "Setup step
failed" instead of surfacing as a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ADVISOR_ID,
    AFTER_TERM_START,
    AFTER_VOTING_WINDOW,
    CLOCK_EPOCH,
    INSIDE_VOTING_WINDOW,
    PETITION_DEADLINE,
    SECOND_ADVISOR_ID,
    TEST_DEFAULTS,
    VOTING_CLOSES_AT,
    VOTING_OPENS_AT,
)
from .factories import (
    adjudicate_signature_payload,
    candidate_line_payload,
    candidate_mark,
    create_appeal_payload,
    create_ballot_payload,
    create_campaign_expense_payload,
    create_candidacy_payload,
    create_compliance_case_payload,
    create_election_payload,
    create_office_payload,
    create_petition_signature_payload,
    create_referendum_payload,
    create_student_payload,
    create_vote_payload,
    dismiss_case_payload,
    open_voting_payload,
    record_training_payload,
    referendum_line_payload,
    referendum_mark,
    resolve_appeal_payload,
    return_petition_payload,
    reverse_expense_payload,
    review_referendum_payload,
    set_clock_payload,
    slate_membership_payload,
    update_student_payload,
    void_signature_payload,
    void_vote_payload,
    withdraw_candidacy_payload,
)
from .test_users import (
    TEST_USERS,
    make_advisor_headers,
    make_candidate_headers,
    make_student_voter_headers,
)

COMMISSIONER = TEST_USERS["commissioner_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
ADVISOR = TEST_USERS["advisor_headers"]
SECOND_ADVISOR = TEST_USERS["second_advisor_headers"]


# ─── Tier 0: single-call primitives ───────────────────────────────────────────

def set_clock(to_iso8601: str) -> str:
    """Reposition the logical election clock and return the resulting instant."""
    data = get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), COMMISSIONER)
    )
    return data["current_utc"]


def declare_election(**overrides) -> dict:
    return get_success_data(
        api_client.create_election(create_election_payload(**overrides), COMMISSIONER)
    )


def declare_office(election_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_office(
            create_office_payload(election_id, **overrides), COMMISSIONER
        )
    )


def register_student(**overrides) -> dict:
    return get_success_data(
        api_client.create_student(create_student_payload(**overrides), REGISTRAR)
    )


def sync_student(student_id: str, **fields) -> dict:
    return get_success_data(
        api_client.update_student(student_id, update_student_payload(**fields), REGISTRAR)
    )


def open_petitioning(election_id: str) -> dict:
    return get_success_data(api_client.open_petitioning(election_id, COMMISSIONER))


def file_candidacy(election_id: str, office_id: str, student_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_candidacy(
            create_candidacy_payload(election_id, office_id, student_id, **overrides),
            make_candidate_headers(student_id),
        )
    )


def submit_petition(candidacy: dict) -> dict:
    return get_success_data(
        api_client.submit_petition(
            candidacy["id"], make_candidate_headers(candidacy["student_id"])
        )
    )


def return_petition(candidacy: dict, reason: str = None) -> dict:
    payload = return_petition_payload() if reason is None else return_petition_payload(reason)
    return get_success_data(
        api_client.return_petition(candidacy["id"], payload, COMMISSIONER)
    )


def approve_candidacy(candidacy: dict) -> dict:
    return get_success_data(api_client.approve_candidacy(candidacy["id"], COMMISSIONER))


def withdraw_candidacy(candidacy: dict, reason: str = None) -> dict:
    return get_success_data(
        api_client.withdraw_candidacy(
            candidacy["id"],
            make_candidate_headers(candidacy["student_id"]),
            withdraw_candidacy_payload(reason),
        )
    )


def change_slate_membership(candidacy: dict, leader_id: str,
                            expected_version: int = None) -> dict:
    version = (
        expected_version
        if expected_version is not None
        else read_candidacy(candidacy["id"])["version"]
    )
    return get_success_data(
        api_client.change_slate_membership(
            candidacy["id"],
            slate_membership_payload(leader_id, version),
            make_candidate_headers(candidacy["student_id"]),
        )
    )


def sign_petition(candidacy: dict, signer: dict,
                  signed_at: str = "2026-08-05T00:00:00Z") -> dict:
    return get_success_data(
        api_client.create_petition_signature(
            create_petition_signature_payload(candidacy["id"], signer["id"], signed_at),
            make_student_voter_headers(signer["id"]),
        )
    )


def adjudicate_signature(signature: dict, outcome: str = "VERIFIED",
                         reject_reason: str = None) -> dict:
    return get_success_data(
        api_client.adjudicate_signature(
            signature["id"],
            adjudicate_signature_payload(outcome, reject_reason),
            COMMISSIONER,
        )
    )


def void_signature(signature: dict, reason: str = None) -> dict:
    return get_success_data(
        api_client.void_signature(
            signature["id"], COMMISSIONER, void_signature_payload(reason)
        )
    )


def report_expense(candidacy: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_campaign_expense(
            create_campaign_expense_payload(candidacy["id"], **overrides),
            make_candidate_headers(candidacy["student_id"]),
        )
    )


def approve_expense(expense: dict) -> dict:
    return get_success_data(api_client.approve_expense(expense["id"], COMMISSIONER))


def reverse_expense(expense: dict, reason: str = None) -> dict:
    return get_success_data(
        api_client.reverse_expense(
            expense["id"], COMMISSIONER, reverse_expense_payload(reason)
        )
    )


def file_compliance_case(election_id: str, candidacy: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_compliance_case(
            create_compliance_case_payload(election_id, candidacy["id"], **overrides),
            COMMISSIONER,
        )
    )


def uphold_case(case: dict, advisor_id: str = ADVISOR_ID) -> dict:
    return get_success_data(
        api_client.uphold_case(case["id"], make_advisor_headers(advisor_id))
    )


def dismiss_case(case: dict, advisor_id: str = ADVISOR_ID, reason: str = None) -> dict:
    return get_success_data(
        api_client.dismiss_case(
            case["id"], make_advisor_headers(advisor_id), dismiss_case_payload(reason)
        )
    )


def draft_referendum(election_id: str, drafter: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_referendum(
            create_referendum_payload(election_id, **overrides),
            make_student_voter_headers(drafter["id"]),
        )
    )


def submit_referendum(referendum: dict, drafter: dict) -> dict:
    return get_success_data(
        api_client.submit_referendum(
            referendum["id"], make_student_voter_headers(drafter["id"])
        )
    )


def review_referendum(referendum: dict, outcome: str = "APPROVE",
                      return_reason: str = None) -> dict:
    return get_success_data(
        api_client.review_referendum(
            referendum["id"],
            review_referendum_payload(outcome, return_reason),
            COMMISSIONER,
        )
    )


def create_ballot(election_id: str, round_number: int = 1,
                  expected_election_version: int = None) -> dict:
    version = (
        expected_election_version
        if expected_election_version is not None
        else read_election(election_id)["version"]
    )
    return get_success_data(
        api_client.create_ballot(
            create_ballot_payload(election_id, version, round_number), COMMISSIONER
        )
    )


def add_candidate_line(ballot: dict, office_id: str, candidacy_id: str) -> dict:
    return get_success_data(
        api_client.create_ballot_line(
            ballot["id"], candidate_line_payload(office_id, candidacy_id), COMMISSIONER
        )
    )


def add_referendum_line(ballot: dict, referendum_id: str) -> dict:
    return get_success_data(
        api_client.create_ballot_line(
            ballot["id"], referendum_line_payload(referendum_id), COMMISSIONER
        )
    )


def lock_ballot(ballot: dict) -> dict:
    return get_success_data(api_client.lock_ballot(ballot["id"], COMMISSIONER))


def publish_ballot(ballot: dict) -> dict:
    return get_success_data(api_client.publish_ballot(ballot["id"], COMMISSIONER))


def open_voting(election_id: str, voting_opens_at: str = VOTING_OPENS_AT,
                voting_closes_at: str = VOTING_CLOSES_AT, round_number: int = 1) -> dict:
    return get_success_data(
        api_client.open_voting(
            election_id,
            open_voting_payload(voting_opens_at, voting_closes_at, round_number),
            COMMISSIONER,
        )
    )


def close_voting(election_id: str) -> dict:
    return get_success_data(api_client.close_voting(election_id, COMMISSIONER))


def run_tally(election_id: str) -> dict:
    return get_success_data(api_client.tally(election_id, COMMISSIONER))


def certify_election(election_id: str, advisor_id: str = ADVISOR_ID) -> dict:
    return get_success_data(
        api_client.certify(election_id, make_advisor_headers(advisor_id))
    )


def run_transition_checkpoint(election_id: str) -> dict:
    return get_success_data(
        api_client.run_transition_checkpoint(election_id, COMMISSIONER)
    )


def record_training(candidacy: dict, modules_completed: int) -> dict:
    return get_success_data(
        api_client.record_training(
            candidacy["id"],
            record_training_payload(modules_completed),
            make_candidate_headers(candidacy["student_id"]),
        )
    )


def activate_officer(candidacy: dict, advisor_id: str = ADVISOR_ID) -> dict:
    return get_success_data(
        api_client.activate_officer(candidacy["id"], make_advisor_headers(advisor_id))
    )


def cast_ballot(ballot: dict, voter: dict, selections: list) -> dict:
    return get_success_data(
        api_client.create_vote(
            create_vote_payload(ballot["id"], selections),
            make_student_voter_headers(voter["id"]),
        )
    )


def void_vote(vote: dict, advisor_id: str = ADVISOR_ID,
              void_reason: str = "Machine misread the paper ballot") -> dict:
    return get_success_data(
        api_client.void_vote(
            vote["id"], void_vote_payload(void_reason), make_advisor_headers(advisor_id)
        )
    )


def file_appeal(election_id: str, candidacy: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_appeal(
            create_appeal_payload(election_id, candidacy["id"], **overrides),
            make_candidate_headers(candidacy["student_id"]),
        )
    )


def sustain_appeal(appeal: dict, advisor_id: str = SECOND_ADVISOR_ID,
                   resolution_note: str = None) -> dict:
    return get_success_data(
        api_client.sustain_appeal(
            appeal["id"],
            make_advisor_headers(advisor_id),
            resolve_appeal_payload(resolution_note),
        )
    )


def deny_appeal(appeal: dict, advisor_id: str = SECOND_ADVISOR_ID,
                resolution_note: str = None) -> dict:
    return get_success_data(
        api_client.deny_appeal(
            appeal["id"],
            make_advisor_headers(advisor_id),
            resolve_appeal_payload(resolution_note),
        )
    )


# ─── Tier 0b: reads ───────────────────────────────────────────────────────────

def read_election(election_id: str) -> dict:
    return get_success_data(api_client.get_election(election_id, COMMISSIONER))


def read_office(office_id: str) -> dict:
    return get_success_data(api_client.get_office(office_id, COMMISSIONER))


def read_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, REGISTRAR))


def read_candidacy(candidacy_id: str) -> dict:
    return get_success_data(api_client.get_candidacy(candidacy_id, COMMISSIONER))


def read_signature(signature_id: str) -> dict:
    return get_success_data(api_client.get_petition_signature(signature_id, COMMISSIONER))


def read_expense(expense_id: str) -> dict:
    return get_success_data(api_client.get_campaign_expense(expense_id, COMMISSIONER))


def read_case(case_id: str) -> dict:
    return get_success_data(api_client.get_compliance_case(case_id, COMMISSIONER))


def read_referendum(referendum_id: str) -> dict:
    return get_success_data(api_client.get_referendum(referendum_id, COMMISSIONER))


def read_ballot(ballot_id: str) -> dict:
    return get_success_data(api_client.get_ballot(ballot_id, COMMISSIONER))


def read_ballot_line(ballot_line_id: str) -> dict:
    return get_success_data(api_client.get_ballot_line(ballot_line_id, COMMISSIONER))


def read_vote(vote_id: str) -> dict:
    return get_success_data(api_client.get_vote(vote_id, COMMISSIONER))


def read_appeal(appeal_id: str) -> dict:
    return get_success_data(api_client.get_appeal(appeal_id, COMMISSIONER))


# ─── Tier 1: an election in PETITIONING with seats, an electorate and filings ──

DEFAULT_CANDIDATE_STUDENTS = [
    {"full_name": "Ava Stone", "class_year": "SENIOR", "gpa": 3.50, "credits_completed": 95},
    {"full_name": "Ben Lu", "class_year": "JUNIOR", "gpa": 3.20, "credits_completed": 70},
    {"full_name": "Dara Idris", "class_year": "JUNIOR", "gpa": 3.00, "credits_completed": 66},
]


def setup_petitioning_election(*, election_overrides=None, offices=None,
                               candidates=None, voters=None, approve=True,
                               clock_start=CLOCK_EPOCH) -> dict:
    """Open a cycle, declare its seats, register the electorate and file the
    candidacies, leaving the election in PETITIONING.

    `offices` is a list of office payload overrides, `candidates` a list of
    dicts shaped {office: <index>, student: {...}, payload: {...},
    slate_leader: <candidate index>} and `voters` a list of student overrides.
    When `approve` is true every candidacy is submitted and approved, which the
    default zero signature requirement permits.
    """
    if clock_start is not None:
        set_clock(clock_start)

    election = declare_election(**(election_overrides or {}))
    office_rows = [declare_office(election["id"], **spec) for spec in (offices or [{}])]

    candidate_specs = candidates if candidates is not None else []
    candidate_students = []
    for index, spec in enumerate(candidate_specs):
        base = (
            DEFAULT_CANDIDATE_STUDENTS[index]
            if index < len(DEFAULT_CANDIDATE_STUDENTS)
            else DEFAULT_CANDIDATE_STUDENTS[0]
        )
        student_overrides = {**base, **(spec.get("student") or {})}
        candidate_students.append(register_student(**student_overrides))

    voter_rows = [register_student(**(spec or {})) for spec in (voters or [])]

    open_petitioning(election["id"])

    candidacies = []
    for index, spec in enumerate(candidate_specs):
        office = office_rows[spec.get("office", 0)]
        payload = dict(spec.get("payload") or {})
        leader_index = spec.get("slate_leader")
        if leader_index is not None:
            payload["slate_leader_candidacy_id"] = candidacies[leader_index]["id"]
        candidacies.append(
            file_candidacy(
                election["id"], office["id"], candidate_students[index]["id"], **payload
            )
        )

    if approve:
        for candidacy in candidacies:
            submit_petition(candidacy)
        for candidacy in candidacies:
            approve_candidacy(candidacy)

    return {
        "election": election,
        "offices": office_rows,
        "office": office_rows[0],
        "candidate_students": candidate_students,
        "candidacies": candidacies,
        "voters": voter_rows,
    }


def setup_single_candidate_election(*, election_overrides=None, office_overrides=None,
                                    voters=None, approve=True) -> dict:
    """One seat, one filing and an optional electorate — the most common preamble."""
    return setup_petitioning_election(
        election_overrides=election_overrides,
        offices=[office_overrides or {}],
        candidates=[{"office": 0}],
        voters=voters,
        approve=approve,
    )


# ─── Tier 2: ballot construction and publication ──────────────────────────────

def build_round_one_ballot(scenario: dict, *, candidacy_indexes=None,
                           referendum_ids=(), clock_to=PETITION_DEADLINE) -> dict:
    """Move the clock to the petition deadline, create the round-1 ballot and
    draw one line per candidacy (and per referendum)."""
    if clock_to is not None:
        set_clock(clock_to)
    ballot = create_ballot(scenario["election"]["id"], 1)
    indexes = (
        range(len(scenario["candidacies"]))
        if candidacy_indexes is None
        else candidacy_indexes
    )
    lines = []
    for index in indexes:
        candidacy = scenario["candidacies"][index]
        lines.append(add_candidate_line(ballot, candidacy["office_id"], candidacy["id"]))
    referendum_lines = [add_referendum_line(ballot, rid) for rid in referendum_ids]
    scenario["ballot"] = ballot
    scenario["candidate_lines"] = lines
    scenario["referendum_lines"] = referendum_lines
    return scenario


def publish_round_one_ballot(scenario: dict, **kwargs) -> dict:
    """Build the round-1 ballot, lock it and publish it to voters."""
    build_round_one_ballot(scenario, **kwargs)
    lock_ballot(scenario["ballot"])
    publish_ballot(scenario["ballot"])
    scenario["ballot"] = read_ballot(scenario["ballot"]["id"])
    return scenario


def open_polls(scenario: dict, *, voting_opens_at=VOTING_OPENS_AT,
               voting_closes_at=VOTING_CLOSES_AT, clock_to=INSIDE_VOTING_WINDOW,
               round_number: int = 1) -> dict:
    """Open the voting window and park the clock inside it."""
    open_voting(scenario["election"]["id"], voting_opens_at, voting_closes_at, round_number)
    if clock_to is not None:
        set_clock(clock_to)
    return scenario


def vote_for_candidacy(scenario: dict, voter: dict, candidacy: dict = None,
                       office: dict = None) -> dict:
    """Cast one ballot carrying a single candidate mark; `candidacy=None`
    records a deliberate abstention on the seat."""
    target_office = office or scenario["office"]
    selections = [
        candidate_mark(target_office["id"], candidacy["id"] if candidacy else None)
    ]
    return cast_ballot(scenario["ballot"], voter, selections)


def vote_on_referendum(scenario: dict, voter: dict, referendum_id: str,
                       choice: str) -> dict:
    return cast_ballot(
        scenario["ballot"], voter, [referendum_mark(referendum_id, choice)]
    )


def close_polls(scenario: dict, *, clock_to=AFTER_VOTING_WINDOW) -> dict:
    if clock_to is not None:
        set_clock(clock_to)
    close_voting(scenario["election"]["id"])
    return scenario


def tally_and_certify(scenario: dict, advisor_id: str = ADVISOR_ID) -> dict:
    run_tally(scenario["election"]["id"])
    certify_election(scenario["election"]["id"], advisor_id)
    return scenario


# ─── Tier 3: petition-ledger scenarios ────────────────────────────────────────

def setup_petition_under_review(*, required_signature_count: int = 2,
                                signer_count: int = 2) -> dict:
    """A candidacy in UNDER_REVIEW with `signer_count` submitted signatures on a
    seat that requires `required_signature_count` valid ones."""
    scenario = setup_petitioning_election(
        offices=[
            {
                "eligible_class_years": ["JUNIOR", "SENIOR"],
                "required_signature_count": required_signature_count,
            }
        ],
        candidates=[{"office": 0}],
        approve=False,
    )
    candidacy = scenario["candidacies"][0]
    submit_petition(candidacy)

    signers, signatures = [], []
    for index in range(signer_count):
        signer = register_student(
            full_name=f"Signer {index + 1}",
            class_year="JUNIOR" if index % 2 == 0 else "SENIOR",
            gpa=3.00,
            credits_completed=60,
        )
        signers.append(signer)
        signatures.append(
            sign_petition(candidacy, signer, f"2026-08-0{5 + index}T00:00:00Z")
        )

    scenario["candidacy"] = candidacy
    scenario["signers"] = signers
    scenario["signatures"] = signatures
    return scenario


def setup_eligible_slate_with_one_signature_each() -> dict:
    """A leader and one slate member, both ELIGIBLE on one verified signature,
    plus an unrelated ELIGIBLE candidacy that shares the signer."""
    scenario = setup_petitioning_election(
        election_overrides={
            "spending_cap_cents": TEST_DEFAULTS["LARGE_SPENDING_CAP_CENTS"],
            "poster_cap": TEST_DEFAULTS["LARGE_POSTER_CAP"],
        },
        offices=[
            {
                "name": TEST_DEFAULTS["SENATE_OFFICE_NAME"],
                "eligible_class_years": ["JUNIOR", "SENIOR"],
                "required_signature_count": 1,
                "seat_count": 3,
            }
        ],
        candidates=[
            {"student": {"full_name": "Lena Ortiz", "class_year": "SENIOR",
                         "gpa": 3.40, "credits_completed": 90}},
            {"student": {"full_name": "Marco Reyes", "class_year": "JUNIOR",
                         "gpa": 3.10, "credits_completed": 62},
             "slate_leader": 0},
            {"student": {"full_name": "Ines Vega", "class_year": "JUNIOR",
                         "gpa": 3.20, "credits_completed": 64}},
        ],
        approve=False,
    )
    leader, member, independent = scenario["candidacies"]
    for candidacy in (leader, member, independent):
        submit_petition(candidacy)

    signer = register_student(
        full_name="Signer One", class_year="SENIOR", gpa=3.00, credits_completed=92
    )
    signatures = {
        "leader": sign_petition(leader, signer),
        "member": sign_petition(member, signer),
        "independent": sign_petition(independent, signer),
    }
    for signature in signatures.values():
        adjudicate_signature(signature)
    for candidacy in (leader, member, independent):
        approve_candidacy(candidacy)

    scenario["leader"] = leader
    scenario["member"] = member
    scenario["independent"] = independent
    scenario["signer"] = signer
    scenario["signatures"] = signatures
    return scenario


def setup_suspended_slate_member_awaiting_reapproval() -> dict:
    """The leader has been knocked to PETITION_DEFICIENT by a voided signature,
    its member is SLATE_SUSPENDED, and the leader has since collected a fresh
    verified signature and resubmitted its petition."""
    scenario = setup_petitioning_election(
        election_overrides={
            "spending_cap_cents": TEST_DEFAULTS["LARGE_SPENDING_CAP_CENTS"],
            "poster_cap": TEST_DEFAULTS["LARGE_POSTER_CAP"],
        },
        offices=[
            {
                "name": TEST_DEFAULTS["SENATE_OFFICE_NAME"],
                "eligible_class_years": ["JUNIOR", "SENIOR"],
                "required_signature_count": 1,
                "seat_count": 3,
            }
        ],
        candidates=[
            {"student": {"full_name": "Lena Ortiz", "class_year": "SENIOR",
                         "gpa": 3.40, "credits_completed": 90}},
            {"student": {"full_name": "Marco Reyes", "class_year": "JUNIOR",
                         "gpa": 3.10, "credits_completed": 62},
             "slate_leader": 0},
        ],
        approve=False,
    )
    leader, member = scenario["candidacies"]
    submit_petition(leader)
    submit_petition(member)

    first_signer = register_student(
        full_name="Signer One", class_year="SENIOR", gpa=3.00, credits_completed=92
    )
    second_signer = register_student(
        full_name="Signer Two", class_year="JUNIOR", gpa=3.00, credits_completed=61
    )
    leader_signature = sign_petition(leader, first_signer)
    member_signature = sign_petition(member, first_signer)
    adjudicate_signature(leader_signature)
    adjudicate_signature(member_signature)
    approve_candidacy(leader)
    approve_candidacy(member)

    void_signature(leader_signature, "Signer never signed the sheet")
    replacement = sign_petition(leader, second_signer, "2026-08-08T00:00:00Z")
    adjudicate_signature(replacement)
    submit_petition(leader)

    scenario["leader"] = leader
    scenario["member"] = member
    scenario["voided_signature"] = leader_signature
    scenario["replacement_signature"] = replacement
    return scenario


def setup_deficient_candidacy_after_revision_cycle() -> dict:
    """One candidacy walked through submit, return, resubmit, sign, verify,
    approve and then a void that knocked it back to PETITION_DEFICIENT."""
    scenario = setup_petitioning_election(
        offices=[{"eligible_class_years": ["JUNIOR", "SENIOR"],
                  "required_signature_count": 1}],
        candidates=[{"office": 0}],
        approve=False,
    )
    candidacy = scenario["candidacies"][0]
    signer = register_student(
        full_name="Signer One", class_year="JUNIOR", gpa=3.00, credits_completed=60
    )

    submit_petition(candidacy)
    return_petition(candidacy, "Signature sheet is missing the office header")
    submit_petition(candidacy)
    signature = sign_petition(candidacy, signer)
    adjudicate_signature(signature)
    approve_candidacy(candidacy)
    void_signature(signature, "Signer withdrew consent")

    scenario["candidacy"] = candidacy
    scenario["signer"] = signer
    scenario["signature"] = signature
    return scenario


def setup_eligible_candidacy_with_verified_signature() -> dict:
    """An ELIGIBLE candidacy resting on exactly one verified signature, so any
    later re-scoring of that signer flips the valid count to zero."""
    scenario = setup_petitioning_election(
        offices=[{"eligible_class_years": ["JUNIOR", "SENIOR"],
                  "required_signature_count": 1}],
        candidates=[{"office": 0}],
        approve=False,
    )
    candidacy = scenario["candidacies"][0]
    signer = register_student(
        full_name="Signer One", class_year="JUNIOR", gpa=3.00, credits_completed=60
    )
    submit_petition(candidacy)
    signature = sign_petition(candidacy, signer)
    adjudicate_signature(signature)
    approve_candidacy(candidacy)

    scenario["candidacy"] = candidacy
    scenario["signer"] = signer
    scenario["signature"] = signature
    return scenario


# ─── Tier 4: campaign-finance scenarios ───────────────────────────────────────

SLATE_OFFICE = {
    "name": TEST_DEFAULTS["SENATE_OFFICE_NAME"],
    "eligible_class_years": ["JUNIOR", "SENIOR"],
    "required_signature_count": 0,
    "seat_count": 3,
}

SLATE_STUDENTS = [
    {"full_name": "Lena Ortiz", "class_year": "SENIOR", "gpa": 3.40, "credits_completed": 90},
    {"full_name": "Marco Reyes", "class_year": "JUNIOR", "gpa": 3.10, "credits_completed": 62},
    {"full_name": "Nia Kwan", "class_year": "JUNIOR", "gpa": 3.00, "credits_completed": 60},
]


def setup_three_member_slate(*, election_overrides=None) -> dict:
    """A leader created first — and therefore the earliest-created member — plus
    two candidacies pointing at it, all approved to ELIGIBLE."""
    overrides = {
        "spending_cap_cents": TEST_DEFAULTS["LARGE_SPENDING_CAP_CENTS"],
        "poster_cap": TEST_DEFAULTS["LARGE_POSTER_CAP"],
    }
    overrides.update(election_overrides or {})
    scenario = setup_petitioning_election(
        election_overrides=overrides,
        offices=[dict(SLATE_OFFICE)],
        candidates=[
            {"student": dict(SLATE_STUDENTS[0])},
            {"student": dict(SLATE_STUDENTS[1]), "slate_leader": 0},
            {"student": dict(SLATE_STUDENTS[2]), "slate_leader": 0},
        ],
        approve=True,
    )
    scenario["leader"], scenario["member_one"], scenario["member_two"] = scenario["candidacies"]
    return scenario


def setup_slate_spend_dual_variant_scenario() -> dict:
    """A three-member slate holding five expense lines — two shared and three
    solo, one of them left unapproved — with the polls closed and no vote cast,
    so the tally can be triggered as the test's own act."""
    scenario = setup_three_member_slate()
    leader, member_one, member_two = (
        scenario["leader"], scenario["member_one"], scenario["member_two"]
    )

    shared_poster = report_expense(
        leader, category="POSTER", amount_cents=10_000,
        incurred_at="2026-08-10T00:00:00Z", quantity=40, shared_with_slate=True,
    )
    shared_digital = report_expense(
        leader, category="DIGITAL", amount_cents=10_000,
        incurred_at="2026-08-11T00:00:00Z", shared_with_slate=True,
    )
    leader_solo = report_expense(
        leader, category="MERCH", amount_cents=2_500,
        incurred_at="2026-08-12T00:00:00Z",
    )
    member_one_solo = report_expense(
        member_one, category="MERCH", amount_cents=4_000,
        incurred_at="2026-08-13T00:00:00Z",
    )
    member_two_solo = report_expense(
        member_two, category="DIGITAL", amount_cents=1_000,
        incurred_at="2026-08-14T00:00:00Z",
    )
    for expense in (shared_poster, shared_digital, leader_solo, member_two_solo):
        approve_expense(expense)

    publish_round_one_ballot(scenario)
    open_polls(scenario, clock_to=None)
    close_polls(scenario)

    scenario["expenses"] = {
        "shared_poster": shared_poster,
        "shared_digital": shared_digital,
        "leader_solo": leader_solo,
        "member_one_solo": member_one_solo,
        "member_two_solo": member_two_solo,
    }
    return scenario


def setup_slate_rounding_scenario() -> dict:
    """Two shared 10 000-cent lines and no solo spending at all, so the final
    figure of each member is purely the allocation result."""
    scenario = setup_three_member_slate()
    leader = scenario["leader"]

    first = report_expense(
        leader, category="POSTER", amount_cents=10_000,
        incurred_at="2026-08-10T00:00:00Z", quantity=40, shared_with_slate=True,
    )
    second = report_expense(
        leader, category="DIGITAL", amount_cents=10_000,
        incurred_at="2026-08-11T00:00:00Z", shared_with_slate=True,
    )
    approve_expense(first)
    approve_expense(second)

    publish_round_one_ballot(scenario)
    open_polls(scenario, clock_to=None)
    close_polls(scenario)

    scenario["shared_expenses"] = [first, second]
    return scenario


def setup_frozen_membership_scenario() -> dict:
    """A three-member slate with one shared 10 000-cent approved line whose
    third member is already DISQUALIFIED by two upheld SEVERE cases before the
    tally runs, so the snapshot still has to hold three members."""
    scenario = setup_three_member_slate()
    leader, _, member_two = (
        scenario["leader"], scenario["member_one"], scenario["member_two"]
    )

    shared = report_expense(
        leader, category="DIGITAL", amount_cents=10_000,
        incurred_at="2026-08-10T00:00:00Z", shared_with_slate=True,
    )
    approve_expense(shared)

    publish_round_one_ballot(scenario)
    open_polls(scenario, clock_to=None)
    close_polls(scenario)

    first_case = file_compliance_case(
        scenario["election"]["id"], member_two, severity="SEVERE",
        rule_code="C-9.1", description="Coercion at the polling place",
    )
    uphold_case(first_case)
    second_case = file_compliance_case(
        scenario["election"]["id"], member_two, severity="SEVERE",
        rule_code="C-9.4", description="Falsified petition sheets",
    )
    uphold_case(second_case)

    scenario["shared_expense"] = shared
    scenario["cases"] = [first_case, second_case]
    return scenario


def setup_two_reported_expenses() -> dict:
    """A DRAFT candidacy holding a 12 500-cent poster line and a 7 000-cent
    merchandise line, both still REPORTED."""
    scenario = setup_single_candidate_election(
        election_overrides={
            "spending_cap_cents": TEST_DEFAULTS["LARGE_SPENDING_CAP_CENTS"],
            "poster_cap": TEST_DEFAULTS["LARGE_POSTER_CAP"],
        },
        office_overrides={"eligible_class_years": ["JUNIOR", "SENIOR"]},
        approve=False,
    )
    candidacy = scenario["candidacies"][0]
    poster = report_expense(
        candidacy, category="POSTER", amount_cents=12_500,
        incurred_at="2026-08-05T00:00:00Z", quantity=30,
    )
    merch = report_expense(
        candidacy, category="MERCH", amount_cents=7_000,
        incurred_at="2026-08-06T00:00:00Z",
    )
    scenario["candidacy"] = candidacy
    scenario["poster_expense"] = poster
    scenario["merch_expense"] = merch
    return scenario


def setup_venue_booking_scenario() -> dict:
    """Two independent candidacies; the first already occupies QUAD-A from
    18:00 to 20:00 on 2026-08-20."""
    scenario = setup_petitioning_election(
        election_overrides={
            "spending_cap_cents": TEST_DEFAULTS["LARGE_SPENDING_CAP_CENTS"],
            "poster_cap": TEST_DEFAULTS["LARGE_POSTER_CAP"],
        },
        offices=[{"eligible_class_years": ["JUNIOR", "SENIOR"]}],
        candidates=[
            {"student": {"full_name": "Ava Stone", "class_year": "SENIOR",
                         "gpa": 3.50, "credits_completed": 95}},
            {"student": {"full_name": "Ben Lu", "class_year": "JUNIOR",
                         "gpa": 3.20, "credits_completed": 70}},
        ],
        approve=False,
    )
    first, second = scenario["candidacies"]
    booking = report_expense(
        first, category="EVENT", amount_cents=5_000,
        incurred_at="2026-08-10T00:00:00Z", venue_code="QUAD-A",
        event_starts_at="2026-08-20T18:00:00Z", event_ends_at="2026-08-20T20:00:00Z",
    )
    scenario["first_candidacy"] = first
    scenario["second_candidacy"] = second
    scenario["existing_booking"] = booking
    return scenario


def setup_slate_pool_over_cap(*, leader_cents: int, member_cents: int,
                              spending_cap_cents: int = None) -> dict:
    """Two candidacies, each individually under the cap, whose joint-and-several
    pool exceeds it once the second joins the first's slate."""
    scenario = setup_petitioning_election(
        election_overrides={
            "spending_cap_cents": (
                spending_cap_cents
                if spending_cap_cents is not None
                else TEST_DEFAULTS["SPENDING_CAP_CENTS"]
            )
        },
        offices=[
            {
                "name": TEST_DEFAULTS["SENATE_OFFICE_NAME"],
                "eligible_class_years": ["JUNIOR", "SENIOR"],
                "seat_count": 2,
            }
        ],
        candidates=[
            {"student": {"full_name": "Lena Ortiz", "class_year": "SENIOR",
                         "gpa": 3.40, "credits_completed": 90}},
            {"student": {"full_name": "Xu Chen", "class_year": "JUNIOR",
                         "gpa": 3.10, "credits_completed": 64}},
        ],
        approve=False,
    )
    leader, joiner = scenario["candidacies"]
    report_expense(leader, category="DIGITAL", amount_cents=leader_cents,
                   incurred_at="2026-08-05T00:00:00Z")
    report_expense(joiner, category="DIGITAL", amount_cents=member_cents,
                   incurred_at="2026-08-06T00:00:00Z")
    change_slate_membership(joiner, leader["id"])

    scenario["leader"] = leader
    scenario["joiner"] = joiner
    return scenario


# ─── Tier 5: compliance, cascade and results scenarios ────────────────────────

def setup_published_two_candidate_ballot(*, election_overrides=None,
                                         office_overrides=None, voters=None) -> dict:
    """Two approved candidacies on one published round-1 ballot."""
    office = {"eligible_class_years": ["JUNIOR", "SENIOR"]}
    office.update(office_overrides or {})
    scenario = setup_petitioning_election(
        election_overrides=election_overrides,
        offices=[office],
        candidates=[{"office": 0}, {"office": 0}],
        voters=voters,
        approve=True,
    )
    publish_round_one_ballot(scenario)
    scenario["first_candidacy"], scenario["second_candidacy"] = scenario["candidacies"]
    scenario["first_line"], scenario["second_line"] = scenario["candidate_lines"]
    return scenario


def setup_repeat_offender_before_final_case() -> dict:
    """A published ballot whose second candidacy already carries one upheld
    MAJOR case and a second SEVERE case still in FILED, with the polls never
    opened so the timing factor stays 1.0."""
    scenario = setup_published_two_candidate_ballot()
    respondent = scenario["second_candidacy"]
    first_case = file_compliance_case(
        scenario["election"]["id"], respondent, severity="MAJOR",
        rule_code="C-2.1", description="Unreported flyering",
    )
    uphold_case(first_case)
    pending_case = file_compliance_case(
        scenario["election"]["id"], respondent, severity="SEVERE",
        rule_code="C-9.4", description="Falsified petition sheets",
    )
    scenario["respondent"] = respondent
    scenario["upheld_case"] = first_case
    scenario["pending_case"] = pending_case
    return scenario


def setup_severe_case_inside_voting_window(**ballot_kwargs) -> dict:
    """A published ballot with the polls open, the clock inside the window and
    one SEVERE case against the second candidacy still FILED."""
    scenario = setup_published_two_candidate_ballot(**ballot_kwargs)
    open_polls(scenario)
    respondent = scenario["second_candidacy"]
    case = file_compliance_case(
        scenario["election"]["id"], respondent, severity="SEVERE",
        rule_code="C-9.2", description="Distributing pre-marked ballots",
    )
    scenario["respondent"] = respondent
    scenario["pending_case"] = case
    return scenario


def setup_disqualified_candidacy_on_published_ballot() -> dict:
    """The second candidacy has been disqualified by two upheld cases while its
    line was printed on a published ballot."""
    scenario = setup_published_two_candidate_ballot()
    respondent = scenario["second_candidacy"]
    first_case = file_compliance_case(
        scenario["election"]["id"], respondent, severity="MAJOR",
        rule_code="C-2.1", description="Unreported flyering",
    )
    uphold_case(first_case)
    second_case = file_compliance_case(
        scenario["election"]["id"], respondent, severity="SEVERE",
        rule_code="C-9.4", description="Falsified petition sheets",
    )
    uphold_case(second_case)
    scenario["respondent"] = respondent
    scenario["cases"] = [first_case, second_case]
    return scenario


def setup_repeat_offender_inside_open_window() -> dict:
    """A two-candidacy race whose second runner already carries one upheld MINOR
    case scored before any slate existed, has since joined the leader's slate so
    the joint-and-several pool stands 20 000 cents over the 50 000-cent cap, and
    faces a fresh MAJOR case filed while the polls are open."""
    scenario = setup_petitioning_election(
        offices=[{"eligible_class_years": ["JUNIOR", "SENIOR"]}],
        candidates=[
            {"student": {"full_name": "Lena Ortiz", "class_year": "SENIOR",
                         "gpa": 3.40, "credits_completed": 90}},
            {"student": {"full_name": "Xu Chen", "class_year": "JUNIOR",
                         "gpa": 3.10, "credits_completed": 64}},
        ],
        approve=True,
    )
    leader, joiner = scenario["candidacies"]
    report_expense(leader, category="DIGITAL", amount_cents=45_000,
                   incurred_at="2026-08-05T00:00:00Z")
    report_expense(joiner, category="DIGITAL", amount_cents=25_000,
                   incurred_at="2026-08-06T00:00:00Z")

    minor_case = file_compliance_case(
        scenario["election"]["id"], joiner, severity="MINOR",
        rule_code="C-1.1", description="Chalking outside the approved zone",
    )
    uphold_case(minor_case)

    publish_round_one_ballot(scenario)
    open_polls(scenario)
    change_slate_membership(joiner, leader["id"])

    pending_case = file_compliance_case(
        scenario["election"]["id"], joiner, severity="MAJOR",
        rule_code="C-4.2", description="Electioneering inside the polling place",
    )

    scenario["leader"] = leader
    scenario["respondent"] = joiner
    scenario["minor_case"] = minor_case
    scenario["pending_case"] = pending_case
    return scenario


def setup_disqualified_candidacy_with_reported_spend() -> dict:
    """The respondent already holds a 45 000-cent reported line before the two
    upheld cases disqualify it, so a further line breaches both the state gate
    and the 50 000-cent spending cap."""
    scenario = setup_petitioning_election(
        offices=[{"eligible_class_years": ["JUNIOR", "SENIOR"]}],
        candidates=[{"office": 0}, {"office": 0}],
        approve=True,
    )
    respondent = scenario["candidacies"][1]
    report_expense(respondent, category="DIGITAL", amount_cents=45_000,
                   incurred_at="2026-08-05T00:00:00Z")
    publish_round_one_ballot(scenario)

    first_case = file_compliance_case(
        scenario["election"]["id"], respondent, severity="MAJOR",
        rule_code="C-2.1", description="Unreported flyering",
    )
    uphold_case(first_case)
    second_case = file_compliance_case(
        scenario["election"]["id"], respondent, severity="SEVERE",
        rule_code="C-9.4", description="Falsified petition sheets",
    )
    uphold_case(second_case)

    scenario["respondent"] = respondent
    scenario["cases"] = [first_case, second_case]
    return scenario


def setup_office_share_scenario() -> dict:
    """Three candidacies, eight enrolled students, five cast ballots — two for
    the leader, one each for the runner-up and the respondent and one explicit
    abstention — and the respondent disqualified after the polls closed."""
    scenario = setup_petitioning_election(
        offices=[{"eligible_class_years": ["FRESHMAN", "SOPHOMORE", "JUNIOR", "SENIOR"],
                  "seat_count": 1}],
        candidates=[
            {"student": {"full_name": "Ava Stone", "class_year": "SENIOR",
                         "gpa": 3.50, "credits_completed": 95}},
            {"student": {"full_name": "Ben Lu", "class_year": "JUNIOR",
                         "gpa": 3.20, "credits_completed": 70}},
            {"student": {"full_name": "Dara Idris", "class_year": "JUNIOR",
                         "gpa": 3.00, "credits_completed": 66}},
        ],
        voters=[
            {"full_name": "Voter One", "class_year": "FRESHMAN", "gpa": 3.00,
             "credits_completed": 12},
            {"full_name": "Voter Two", "class_year": "FRESHMAN", "gpa": 3.00,
             "credits_completed": 12},
            {"full_name": "Voter Three", "class_year": "SOPHOMORE", "gpa": 3.00,
             "credits_completed": 30},
            {"full_name": "Voter Four", "class_year": "SOPHOMORE", "gpa": 3.00,
             "credits_completed": 30},
            {"full_name": "Voter Five", "class_year": "SENIOR", "gpa": 3.00,
             "credits_completed": 92},
        ],
        approve=True,
    )
    leader, runner_up, respondent = scenario["candidacies"]
    publish_round_one_ballot(scenario)
    open_polls(scenario)

    voters = scenario["voters"]
    vote_for_candidacy(scenario, voters[0], leader)
    vote_for_candidacy(scenario, voters[1], leader)
    vote_for_candidacy(scenario, voters[2], runner_up)
    vote_for_candidacy(scenario, voters[3], respondent)
    vote_for_candidacy(scenario, voters[4], None)
    close_polls(scenario)

    first_case = file_compliance_case(
        scenario["election"]["id"], respondent, severity="MAJOR",
        rule_code="C-2.1", description="Unreported flyering",
    )
    uphold_case(first_case)
    second_case = file_compliance_case(
        scenario["election"]["id"], respondent, severity="SEVERE",
        rule_code="C-9.4", description="Ballot tampering",
    )
    uphold_case(second_case)

    scenario["leader"] = leader
    scenario["runner_up"] = runner_up
    scenario["respondent"] = respondent
    scenario["cases"] = [first_case, second_case]
    return scenario


def setup_referendum_on_closed_ballot(*, election_overrides=None,
                                      office_overrides=None,
                                      approval_threshold_pct: float = None,
                                      voter_choices=("YES", "YES", "YES", "NO"),
                                      redraft: bool = False,
                                      voter_count: int = None,
                                      voter_class_years=None) -> dict:
    """One approved candidacy and one referendum printed on a published ballot,
    with the listed choices cast and the polls closed."""
    count = voter_count if voter_count is not None else len(voter_choices)
    class_years = voter_class_years or ["FRESHMAN", "SOPHOMORE", "JUNIOR", "SENIOR"]
    voters = [
        {"full_name": f"Voter {index + 1}",
         "class_year": class_years[index % len(class_years)],
         "gpa": 3.00, "credits_completed": 30}
        for index in range(count)
    ]
    office = {"eligible_class_years": ["FRESHMAN", "SOPHOMORE", "JUNIOR", "SENIOR"]}
    office.update(office_overrides or {})
    scenario = setup_petitioning_election(
        election_overrides=election_overrides,
        offices=[office],
        candidates=[{"office": 0}],
        voters=voters,
        approve=True,
    )
    drafter = scenario["voters"][0]
    overrides = {}
    if approval_threshold_pct is not None:
        overrides["approval_threshold_pct"] = approval_threshold_pct
    referendum = draft_referendum(scenario["election"]["id"], drafter, **overrides)
    submit_referendum(referendum, drafter)
    if redraft:
        review_referendum(referendum, "RETURN", "Cite the current quorum clause")
        submit_referendum(referendum, drafter)
    review_referendum(referendum, "APPROVE")

    publish_round_one_ballot(scenario, referendum_ids=[referendum["id"]])
    open_polls(scenario)
    for index, choice in enumerate(voter_choices):
        vote_on_referendum(scenario, scenario["voters"][index], referendum["id"], choice)
    close_polls(scenario)

    scenario["referendum"] = referendum
    scenario["drafter"] = drafter
    return scenario


def setup_tallied_two_candidate_race(*, election_overrides=None,
                                     office_overrides=None,
                                     candidate_students=None,
                                     voter_class_years=None,
                                     first_votes: int = 2,
                                     second_votes: int = 1) -> dict:
    """A two-candidate race carried through close-voting and the tally, ready
    for the certification fork."""
    class_years = voter_class_years or ["FRESHMAN", "SOPHOMORE", "SENIOR", "JUNIOR"]
    voters = [
        {"full_name": f"Voter {index + 1}",
         "class_year": class_years[index % len(class_years)],
         "gpa": 3.00, "credits_completed": 30}
        for index in range(first_votes + second_votes)
    ]
    office = {"eligible_class_years": ["FRESHMAN", "SOPHOMORE", "JUNIOR", "SENIOR"]}
    office.update(office_overrides or {})
    students = candidate_students or [None, None]
    scenario = setup_petitioning_election(
        election_overrides=election_overrides,
        offices=[office],
        candidates=[
            {"office": 0, "student": students[0]},
            {"office": 0, "student": students[1]},
        ],
        voters=voters,
        approve=True,
    )
    first, second = scenario["candidacies"]
    publish_round_one_ballot(scenario)
    open_polls(scenario)
    for index in range(first_votes):
        vote_for_candidacy(scenario, scenario["voters"][index], first)
    for index in range(second_votes):
        vote_for_candidacy(scenario, scenario["voters"][first_votes + index], second)
    close_polls(scenario)
    run_tally(scenario["election"]["id"])

    scenario["first_candidacy"] = first
    scenario["second_candidacy"] = second
    return scenario


def setup_certified_election_with_runner_up(*, required_training_modules: int = 3) -> dict:
    """A certified election: the leader is ELECTED with its officer transition
    open at PENDING and the runner-up is ELIMINATED."""
    scenario = setup_tallied_two_candidate_race(
        office_overrides={"required_training_modules": required_training_modules}
    )
    certify_election(scenario["election"]["id"])
    scenario["winner"] = scenario["first_candidacy"]
    scenario["runner_up"] = scenario["second_candidacy"]
    return scenario


def setup_disqualified_candidacy_with_appeal(*, remedy="REINSTATEMENT") -> dict:
    """A published ballot on which the second candidacy was disqualified inside
    the voting window by a single upheld SEVERE case, with the candidate's
    appeal already filed against that case."""
    scenario = setup_severe_case_inside_voting_window()
    respondent = scenario["respondent"]
    case = scenario["pending_case"]
    uphold_case(case)
    appeal = file_appeal(
        scenario["election"]["id"], respondent,
        remedy_requested=remedy,
        grounds="The pre-marked ballots were a rival's plant",
        compliance_case_id=case["id"],
    )
    scenario["appeal"] = appeal
    scenario["upheld_case"] = case
    scenario["voided_line"] = scenario["second_line"]
    return scenario


def setup_certified_election_with_results_appeal() -> dict:
    """A certified election with a RECOUNT appeal filed by the winner, so the
    certifying advisor is barred from resolving it."""
    scenario = setup_certified_election_with_runner_up()
    appeal = file_appeal(
        scenario["election"]["id"], scenario["winner"],
        remedy_requested="RECOUNT",
        grounds="Request a manual recount of the paper ballots",
    )
    scenario["appeal"] = appeal
    return scenario


def setup_two_elections_sharing_academic_year() -> dict:
    """Two elections of the same academic year, each with a published round-1
    ballot; the first already holds the window [09-15T09:00, 09-16T17:00)."""
    set_clock(CLOCK_EPOCH)
    first_election = declare_election(title="Fall 2026 SGA General")
    second_election = declare_election(title="Fall 2026 Class Council")
    first_office = declare_office(
        first_election["id"], eligible_class_years=["JUNIOR", "SENIOR"]
    )
    second_office = declare_office(
        second_election["id"], name="Junior Class Chair",
        eligible_class_years=["JUNIOR"],
    )
    student = register_student(
        full_name="Ava Stone", class_year="JUNIOR", gpa=3.50, credits_completed=70
    )
    open_petitioning(first_election["id"])
    open_petitioning(second_election["id"])
    first_candidacy = file_candidacy(
        first_election["id"], first_office["id"], student["id"]
    )
    second_candidacy = file_candidacy(
        second_election["id"], second_office["id"], student["id"]
    )
    for candidacy in (first_candidacy, second_candidacy):
        submit_petition(candidacy)
        approve_candidacy(candidacy)

    set_clock(PETITION_DEADLINE)
    first_ballot = create_ballot(first_election["id"], 1)
    add_candidate_line(first_ballot, first_office["id"], first_candidacy["id"])
    lock_ballot(first_ballot)
    publish_ballot(first_ballot)
    open_voting(first_election["id"], VOTING_OPENS_AT, VOTING_CLOSES_AT, 1)

    second_ballot = create_ballot(second_election["id"], 1)
    add_candidate_line(second_ballot, second_office["id"], second_candidacy["id"])
    lock_ballot(second_ballot)
    publish_ballot(second_ballot)

    return {
        "first_election": first_election,
        "second_election": second_election,
        "first_office": first_office,
        "second_office": second_office,
        "student": student,
        "first_candidacy": first_candidacy,
        "second_candidacy": second_candidacy,
        "first_ballot": first_ballot,
        "second_ballot": second_ballot,
    }


def setup_open_polls_with_one_cast_ballot(*, office_overrides=None) -> dict:
    """One approved candidacy, one enrolled voter who has already cast, and the
    polls still open."""
    office = {"eligible_class_years": ["FRESHMAN", "SENIOR"]}
    office.update(office_overrides or {})
    scenario = setup_petitioning_election(
        offices=[office],
        candidates=[{"office": 0}],
        voters=[{"full_name": "Voter One", "class_year": "FRESHMAN", "gpa": 3.00,
                 "credits_completed": 12}],
        approve=True,
    )
    publish_round_one_ballot(scenario)
    open_polls(scenario)
    scenario["candidacy"] = scenario["candidacies"][0]
    scenario["voter"] = scenario["voters"][0]
    scenario["vote"] = vote_for_candidacy(
        scenario, scenario["voter"], scenario["candidacy"]
    )
    return scenario


def setup_ballot_building_with_pending_review() -> dict:
    """The petition window has closed and the round-1 ballot exists, so the
    election is BALLOT_BUILDING while the second candidacy is still
    UNDER_REVIEW on a seat that requires no signatures."""
    scenario = setup_petitioning_election(
        offices=[{"eligible_class_years": ["JUNIOR", "SENIOR"]}],
        candidates=[{"office": 0}, {"office": 0}],
        approve=False,
    )
    approved, pending = scenario["candidacies"]
    submit_petition(approved)
    submit_petition(pending)
    approve_candidacy(approved)

    set_clock(PETITION_DEADLINE)
    ballot = create_ballot(scenario["election"]["id"], 1)

    scenario["approved_candidacy"] = approved
    scenario["pending_candidacy"] = pending
    scenario["ballot"] = ballot
    return scenario


def setup_ballot_missing_a_second_office_line() -> dict:
    """Two seats but only one candidate line: the Treasurer seat carries none."""
    scenario = setup_petitioning_election(
        offices=[
            {"name": "President", "eligible_class_years": ["JUNIOR", "SENIOR"]},
            {"name": "Treasurer", "eligible_class_years": ["JUNIOR", "SENIOR"]},
        ],
        candidates=[{"office": 0}],
        approve=True,
    )
    build_round_one_ballot(scenario)
    scenario["president_office"], scenario["treasurer_office"] = scenario["offices"]
    scenario["candidacy"] = scenario["candidacies"][0]
    return scenario


def setup_locked_unpublished_ballot() -> dict:
    """A locked but unpublished round-1 ballot and one enrolled voter."""
    scenario = setup_petitioning_election(
        offices=[{"eligible_class_years": ["FRESHMAN", "SOPHOMORE", "JUNIOR", "SENIOR"]}],
        candidates=[{"office": 0}],
        voters=[{"full_name": "Voter One", "class_year": "FRESHMAN", "gpa": 3.00,
                 "credits_completed": 12}],
        approve=True,
    )
    build_round_one_ballot(scenario)
    lock_ballot(scenario["ballot"])
    scenario["ballot"] = read_ballot(scenario["ballot"]["id"])
    scenario["candidacy"] = scenario["candidacies"][0]
    scenario["voter"] = scenario["voters"][0]
    return scenario


def setup_lapsed_officer_checkpoint() -> dict:
    """A certified election whose winner has recorded no training at all, with
    the clock advanced one day past the term start."""
    scenario = setup_certified_election_with_runner_up()
    set_clock(AFTER_TERM_START)
    return scenario

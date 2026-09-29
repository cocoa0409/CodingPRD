"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because the database is empty at the start of every test. Setup calls go through
get_success_data() so a broken precondition surfaces as a setup failure rather than
as a confusing assertion failure inside the test body.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_EPOCH,
    COURSE_EXT_050,
    COURSE_EXT_101,
    COURSE_EXT_150,
    DEFAULT_VOUCHER_EXPIRY,
)
from .factories import (
    create_citation_payload,
    create_corporate_account_payload,
    create_course_payload,
    create_deposit_payload,
    create_instructor_contract_payload,
    create_instructor_payload,
    create_learner_payload,
    create_offering_payload,
    create_petition_payload,
    create_refund_transfer_payload,
    create_registration_payload,
    issue_voucher_payload,
    pay_payload,
)
from .test_users import (
    ADMIN,
    ANON,
    REGISTRAR,
    make_instructor_headers,
    make_learner_headers,
    make_sponsor_headers,
)

# ---------------------------------------------------------------------------
# Tier 0: single-call primitives
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str, headers=ADMIN) -> dict:
    """Reposition the server's logical UTC clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, headers))


def reset_clock() -> dict:
    """Return the logical clock to the server's declared starting instant."""
    return set_clock(CLOCK_EPOCH)


def new_course(**overrides) -> dict:
    return get_success_data(
        api_client.create_course(create_course_payload(**overrides), ADMIN)
    )


def new_offering(course_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_offering(create_offering_payload(course_id, **overrides), ADMIN)
    )


def new_instructor(**overrides) -> dict:
    return get_success_data(
        api_client.create_instructor(create_instructor_payload(**overrides), ADMIN)
    )


def offer_contract(offering_id: str, instructor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_instructor_contract(
            create_instructor_contract_payload(offering_id, instructor_id, **overrides),
            ADMIN,
        )
    )


def sign_contract(contract_id: str, instructor_id: str, decision: str = "ACCEPT") -> dict:
    return get_success_data(
        api_client.sign_instructor_contract(
            contract_id, {"decision": decision}, make_instructor_headers(instructor_id)
        )
    )


def publish_offering(offering_id: str) -> dict:
    return get_success_data(api_client.open_offering(offering_id, ADMIN))


def read_offering(offering_id: str) -> dict:
    return get_success_data(api_client.get_offering(offering_id, ADMIN))


def offering_version(offering_id: str) -> int:
    return read_offering(offering_id)["version"]


def new_learner(**overrides) -> dict:
    return get_success_data(
        api_client.create_learner(create_learner_payload(**overrides), ANON)
    )


def register_learner(offering_id: str, learner_id: str, expected_version=None, as_registrar=False) -> dict:
    """Create a PENDING registration. Uses the offering's live version unless one
    is supplied explicitly."""
    if expected_version is None:
        expected_version = offering_version(offering_id)
    headers = REGISTRAR if as_registrar else make_learner_headers(learner_id)
    return get_success_data(
        api_client.create_registration(
            offering_id,
            create_registration_payload(learner_id, expected_version),
            headers,
        )
    )


def pay_self(registration_id: str, learner_id: str = None) -> dict:
    headers = REGISTRAR if learner_id is None else make_learner_headers(learner_id)
    return get_success_data(
        api_client.pay_registration(registration_id, pay_payload("SELF_PAY"), headers)
    )


def pay_with_voucher(registration_id: str, voucher_id: str, learner_id: str) -> dict:
    return get_success_data(
        api_client.pay_registration(
            registration_id,
            pay_payload("VOUCHER", voucher_id),
            make_learner_headers(learner_id),
        )
    )


def new_account(**overrides) -> dict:
    return get_success_data(
        api_client.create_corporate_account(
            create_corporate_account_payload(**overrides), ADMIN
        )
    )


def deposit(account_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.create_deposit(
            account_id, create_deposit_payload(amount_cents), make_sponsor_headers(account_id)
        )
    )


def issue_voucher(account_id: str, face_value_cents: int, expected_version: int,
                  expires_at: str = DEFAULT_VOUCHER_EXPIRY) -> dict:
    return get_success_data(
        api_client.issue_voucher(
            account_id,
            issue_voucher_payload(face_value_cents, expected_version, expires_at=expires_at),
            make_sponsor_headers(account_id),
        )
    )


def assign_voucher(voucher_id: str, account_id: str, learner_id: str) -> dict:
    return get_success_data(
        api_client.assign_voucher(
            voucher_id, {"learner_id": learner_id}, make_sponsor_headers(account_id)
        )
    )


def take_census(offering_id: str) -> dict:
    return get_success_data(api_client.census_offering(offering_id, ADMIN))


def activate_contract(contract_id: str) -> dict:
    return get_success_data(api_client.activate_instructor_contract(contract_id, ADMIN))


def settle_contract(contract_id: str) -> dict:
    return get_success_data(api_client.settle_instructor_contract(contract_id, ADMIN))


def close_offering(offering_id: str) -> dict:
    return get_success_data(api_client.complete_offering(offering_id, ADMIN))


def record_attendance(registration_id: str, sessions_attended: int, instructor_id: str) -> dict:
    return get_success_data(
        api_client.record_attendance(
            registration_id,
            {"sessions_attended": sessions_attended},
            make_instructor_headers(instructor_id),
        )
    )


def award_completion(registration_id: str, instructor_id: str) -> dict:
    return get_success_data(
        api_client.award_completion(registration_id, make_instructor_headers(instructor_id))
    )


def revoke_record(record_id: str) -> dict:
    return get_success_data(api_client.revoke_completion_record(record_id, REGISTRAR))


def open_refund_request(registration_id: str, learner_id: str = None, **overrides) -> dict:
    headers = REGISTRAR if learner_id is None else make_learner_headers(learner_id)
    return get_success_data(
        api_client.create_refund_transfer_request(
            create_refund_transfer_payload(registration_id, **overrides), headers
        )
    )


def decide_request(request_id: str, decision: str = "APPROVE", refund_basis: str = None) -> dict:
    payload = {"decision": decision}
    if refund_basis is not None:
        payload["refund_basis"] = refund_basis
    return get_success_data(
        api_client.decide_refund_transfer_request(request_id, payload, REGISTRAR)
    )


def settle_request(request_id: str) -> dict:
    return get_success_data(api_client.settle_refund_transfer_request(request_id, REGISTRAR))


def new_petition(learner_id: str, target_course_id: str) -> dict:
    return get_success_data(
        api_client.create_petition(
            create_petition_payload(learner_id, target_course_id),
            make_learner_headers(learner_id),
        )
    )


def cite_record(petition_id: str, record_id: str, learner_id: str, weight: float = 1.0) -> dict:
    return get_success_data(
        api_client.create_citation(
            petition_id, create_citation_payload(record_id, weight),
            make_learner_headers(learner_id),
        )
    )


def submit_petition(petition_id: str, learner_id: str) -> dict:
    return get_success_data(
        api_client.submit_petition(petition_id, make_learner_headers(learner_id))
    )


def review_petition(petition_id: str, headers=ADMIN) -> dict:
    return get_success_data(api_client.review_petition(petition_id, headers))


def list_memberships(learner_id: str) -> list:
    body = api_client.list_marketing_memberships(learner_id, REGISTRAR).json()
    return body["data"]


# ---------------------------------------------------------------------------
# Tier 1: named learner identities
# ---------------------------------------------------------------------------

LEARNER_SPECS = [
    {"email": "ada@x.com", "full_name": "Ada Ito"},
    {"email": "ben@x.com", "full_name": "Ben Osei"},
    {"email": "cai@x.com", "full_name": "Cai Ruiz"},
    {"email": "dee@x.com", "full_name": "Dee Marsh"},
    {"email": "eli@x.com", "full_name": "Eli Novak"},
    {"email": "fay@x.com", "full_name": "Fay Oduya"},
    {"email": "gus@x.com", "full_name": "Gus Petrov"},
    {"email": "hal@x.com", "full_name": "Hal Quinn"},
]

INSTRUCTOR_SPECS = [
    {"email": "dana@ext.edu", "full_name": "Dana Reyes", "credential_level": "SENIOR"},
    {"email": "bo@ext.edu", "full_name": "Bo Lang", "credential_level": "SENIOR"},
    {"email": "cass@ext.edu", "full_name": "Cass Vega", "credential_level": "SENIOR"},
]


def learner_spec(index: int) -> dict:
    return dict(LEARNER_SPECS[index])


def instructor_spec(index: int) -> dict:
    return dict(INSTRUCTOR_SPECS[index])


# ---------------------------------------------------------------------------
# Tier 2: an OPEN section with a signed instructor behind it
# ---------------------------------------------------------------------------


def setup_open_offering(
    course_spec: dict = None,
    offering_overrides: dict = None,
    instructor_index: int = 0,
    instructor_overrides: dict = None,
    contract_overrides: dict = None,
    course_id: str = None,
    course: dict = None,
) -> dict:
    """Publish one section for business.

    Creates the catalog course (unless one is supplied), the section, an instructor,
    an offered contract, signs it, and opens the section. Returns a scene dict with
    the course, the opened offering, the instructor, the contract and the offering's
    live version.
    """
    if course is None:
        if course_id is None:
            course = new_course(**(course_spec or COURSE_EXT_101))
            course_id = course["id"]
        else:
            course = get_success_data(api_client.get_course(course_id, ADMIN))
    else:
        course_id = course["id"]

    offering = new_offering(course_id, **(offering_overrides or {}))
    ins_payload = instructor_spec(instructor_index)
    ins_payload.update(instructor_overrides or {})
    instructor = new_instructor(**ins_payload)
    contract = offer_contract(
        offering["id"], instructor["id"], **(contract_overrides or {})
    )
    sign_contract(contract["id"], instructor["id"])
    opened = publish_offering(offering["id"])
    return {
        "course": course,
        "course_id": course_id,
        "offering": opened,
        "offering_id": opened["id"],
        "instructor": instructor,
        "instructor_id": instructor["id"],
        "contract": contract,
        "contract_id": contract["id"],
        "version": opened["version"],
    }


def setup_draft_offering(
    course_spec: dict = None,
    offering_overrides: dict = None,
    instructor_index: int = 0,
    contract_overrides: dict = None,
    sign: bool = True,
    course: dict = None,
) -> dict:
    """A DRAFT section with a contract that is signed by default and merely offered
    when sign is False."""
    if course is None:
        course = new_course(**(course_spec or COURSE_EXT_101))
    offering = new_offering(course["id"], **(offering_overrides or {}))
    instructor = new_instructor(**instructor_spec(instructor_index))
    contract = offer_contract(
        offering["id"], instructor["id"], **(contract_overrides or {})
    )
    if sign:
        sign_contract(contract["id"], instructor["id"])
    return {
        "course": course,
        "course_id": course["id"],
        "offering": offering,
        "offering_id": offering["id"],
        "instructor": instructor,
        "instructor_id": instructor["id"],
        "contract": contract,
        "contract_id": contract["id"],
    }


# ---------------------------------------------------------------------------
# Tier 3: seated learners
# ---------------------------------------------------------------------------


def add_pending_registration(offering_id: str, learner_index: int = 0, learner: dict = None) -> dict:
    """Create a learner (unless one is supplied) and a PENDING x UNPAID registration."""
    if learner is None:
        learner = new_learner(**learner_spec(learner_index))
    registration = register_learner(offering_id, learner["id"], as_registrar=True)
    return {"learner": learner, "learner_id": learner["id"],
            "registration": registration, "registration_id": registration["id"]}


def add_paid_registration(offering_id: str, learner_index: int = 0, learner: dict = None) -> dict:
    """Create a learner, register, and settle by SELF_PAY so seat resolution runs."""
    seat = add_pending_registration(offering_id, learner_index, learner)
    seat["registration"] = pay_self(seat["registration_id"])
    return seat


def setup_offering_with_paid_learners(
    num_learners: int = 1,
    course_spec: dict = None,
    offering_overrides: dict = None,
    contract_overrides: dict = None,
    instructor_index: int = 0,
) -> dict:
    """An OPEN section carrying num_learners SELF_PAY registrations."""
    scene = setup_open_offering(
        course_spec=course_spec,
        offering_overrides=offering_overrides,
        contract_overrides=contract_overrides,
        instructor_index=instructor_index,
    )
    scene["seats"] = [
        add_paid_registration(scene["offering_id"], learner_index=i)
        for i in range(num_learners)
    ]
    return scene


# ---------------------------------------------------------------------------
# Tier 4: past the census fork
# ---------------------------------------------------------------------------


def setup_census_locked_offering(
    num_learners: int = 1,
    census_clock: str = "2026-09-01T00:00:00Z",
    course_spec: dict = None,
    offering_overrides: dict = None,
    contract_overrides: dict = None,
    instructor_index: int = 0,
    activate: bool = True,
) -> dict:
    """Drive a section all the way to CENSUS_LOCKED with an ACTIVE contract.

    Creates the course, section, instructor and signed contract; opens the section;
    registers and pays num_learners; advances the logical clock to census_clock;
    takes the census decision; and activates the contract so the instructor may
    award completions.
    """
    scene = setup_offering_with_paid_learners(
        num_learners=num_learners,
        course_spec=course_spec,
        offering_overrides=offering_overrides,
        contract_overrides=contract_overrides,
        instructor_index=instructor_index,
    )
    set_clock(census_clock)
    scene["offering"] = take_census(scene["offering_id"])
    if activate:
        scene["contract"] = activate_contract(scene["contract_id"])
    return scene


def setup_issued_completion(
    census_clock: str = "2026-09-01T00:00:00Z",
    course_spec: dict = None,
    offering_overrides: dict = None,
    sessions_attended: int = None,
) -> dict:
    """One learner carried through to an ISSUED completion record.

    Reaches CENSUS_LOCKED with an ACTIVE contract, records full attendance and
    awards the completion, so the scene exposes the completion record the CPL
    pathway needs to cite.
    """
    scene = setup_census_locked_offering(
        num_learners=1,
        census_clock=census_clock,
        course_spec=course_spec,
        offering_overrides=offering_overrides,
    )
    seat = scene["seats"][0]
    sessions = (
        sessions_attended
        if sessions_attended is not None
        else scene["offering"]["session_count"]
    )
    record_attendance(seat["registration_id"], sessions, scene["instructor_id"])
    scene["record"] = award_completion(seat["registration_id"], scene["instructor_id"])
    scene["record_id"] = scene["record"]["id"]
    scene["learner"] = seat["learner"]
    scene["learner_id"] = seat["learner_id"]
    scene["registration_id"] = seat["registration_id"]
    return scene


# ---------------------------------------------------------------------------
# Tier 5: credit-for-prior-learning petitions
# ---------------------------------------------------------------------------


def setup_petition_under_review(
    target_course_spec: dict,
    census_clock: str = "2026-09-01T00:00:00Z",
    course_spec: dict = None,
    offering_overrides: dict = None,
    weight: float = 1.0,
    reviewer_headers=ADMIN,
) -> dict:
    """A petition sitting in UNDER_REVIEW with one citation of an issued record.

    Builds the completion record first, opens the target course, then files the
    petition, cites the record, submits it and takes it under review.
    """
    scene = setup_issued_completion(
        census_clock=census_clock,
        course_spec=course_spec,
        offering_overrides=offering_overrides,
    )
    target_course = new_course(**target_course_spec)
    petition = new_petition(scene["learner_id"], target_course["id"])
    citation = cite_record(
        petition["id"], scene["record_id"], scene["learner_id"], weight
    )
    submit_petition(petition["id"], scene["learner_id"])
    scene["petition"] = review_petition(petition["id"], reviewer_headers)
    scene["petition_id"] = petition["id"]
    scene["citation"] = citation
    scene["citation_id"] = citation["id"]
    scene["target_course"] = target_course
    scene["target_course_id"] = target_course["id"]
    return scene


# ---------------------------------------------------------------------------
# Tier 6: sponsor money
# ---------------------------------------------------------------------------


def setup_funded_sponsor(funded_cents: int, org_name: str = "ACME Industrial",
                         billing_email: str = "ap@acme.example") -> dict:
    """A sponsor account with a single deposit posted."""
    account = new_account(org_name=org_name, billing_email=billing_email)
    account = deposit(account["id"], funded_cents)
    return {"account": account, "account_id": account["id"], "version": account["version"]}


def setup_assigned_voucher(
    learner_id: str,
    funded_cents: int,
    face_value_cents: int,
    expires_at: str = DEFAULT_VOUCHER_EXPIRY,
) -> dict:
    """A sponsor account funded, a voucher issued against it, and the voucher bound
    to the given learner."""
    sponsor = setup_funded_sponsor(funded_cents)
    voucher = issue_voucher(
        sponsor["account_id"], face_value_cents, sponsor["version"], expires_at
    )
    voucher = assign_voucher(voucher["id"], sponsor["account_id"], learner_id)
    return {
        "account": sponsor["account"],
        "account_id": sponsor["account_id"],
        "voucher": voucher,
        "voucher_id": voucher["id"],
    }


def read_account(account_id: str) -> dict:
    return get_success_data(
        api_client.get_corporate_account(account_id, make_sponsor_headers(account_id))
    )


def read_voucher(voucher_id: str, account_id: str = None) -> dict:
    headers = make_sponsor_headers(account_id) if account_id else REGISTRAR
    return get_success_data(api_client.get_voucher(voucher_id, headers))


def read_registration(registration_id: str) -> dict:
    return get_success_data(api_client.get_registration(registration_id, REGISTRAR))


def read_learner(learner_id: str) -> dict:
    return get_success_data(api_client.get_learner(learner_id, REGISTRAR))


def read_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_instructor_contract(contract_id, ADMIN))


def read_petition(petition_id: str) -> dict:
    return get_success_data(api_client.get_petition(petition_id, REGISTRAR))


def read_record(record_id: str) -> dict:
    return get_success_data(api_client.get_completion_record(record_id, REGISTRAR))


def read_request(request_id: str) -> dict:
    return get_success_data(api_client.get_refund_transfer_request(request_id, REGISTRAR))


def read_course(course_id: str) -> dict:
    return get_success_data(api_client.get_course(course_id, ADMIN))


def read_instructor(instructor_id: str) -> dict:
    return get_success_data(api_client.get_instructor(instructor_id, ADMIN))


def count_rows(response) -> int:
    """total_count from a list response envelope."""
    return response.json()["meta"]["total_count"]


# ---------------------------------------------------------------------------
# Tier 7: multi-section scenes used by the boundary and overlap scenarios
# ---------------------------------------------------------------------------


def setup_fee_tier_boundary_scene() -> dict:
    """Two concurrently running sections priced one cent apart across the 25,000-cent
    processing-fee band floor, each staffed by its own instructor because the two
    teaching windows intersect."""
    course = new_course(**COURSE_EXT_050)
    at = new_offering(
        course["id"], session_count=4, min_enrollment=1, max_enrollment=10,
        tuition_cents=25000,
    )
    below = new_offering(
        course["id"], session_count=4, min_enrollment=1, max_enrollment=10,
        tuition_cents=24999,
    )
    ins_a = new_instructor(**instructor_spec(0))
    ins_b = new_instructor(**instructor_spec(1))
    k_at = offer_contract(at["id"], ins_a["id"])
    k_below = offer_contract(below["id"], ins_b["id"])
    sign_contract(k_at["id"], ins_a["id"])
    sign_contract(k_below["id"], ins_b["id"])
    at = publish_offering(at["id"])
    below = publish_offering(below["id"])
    learner = new_learner(**learner_spec(0))
    return {
        "course": course,
        "at": at,
        "at_id": at["id"],
        "at_version": at["version"],
        "below": below,
        "below_id": below["id"],
        "below_version": below["version"],
        "learner": learner,
        "learner_id": learner["id"],
    }


def setup_learner_load_scene() -> dict:
    """Three OPEN sections whose windows chain across 2026-11-15.

    FALL runs 2026-09-15 to 2026-11-15 on a 1.2-CEU course, LAB runs 2026-10-01 to
    2026-12-01 on a 1.5-CEU course, and LATE runs 2026-11-15 to 2026-12-15 on the same
    1.5-CEU course. FALL and LATE merely touch at 2026-11-15 so one instructor may
    staff both; LAB gets its own instructor. The learner already holds PENDING
    registrations on FALL and LAB.
    """
    base = new_course(**COURSE_EXT_101)
    lab_course = new_course(**COURSE_EXT_150)
    fall = new_offering(
        base["id"], term_code="2026FA", start_date="2026-09-15T00:00:00Z",
        end_date="2026-11-15T00:00:00Z", census_at="2026-09-01T00:00:00Z",
        tuition_cents=60000,
    )
    lab = new_offering(
        lab_course["id"], term_code="2026FB", start_date="2026-10-01T00:00:00Z",
        end_date="2026-12-01T00:00:00Z", census_at="2026-09-20T00:00:00Z",
        tuition_cents=45000,
    )
    late = new_offering(
        lab_course["id"], term_code="2026WI", start_date="2026-11-15T00:00:00Z",
        end_date="2026-12-15T00:00:00Z", census_at="2026-11-01T00:00:00Z",
        tuition_cents=45000,
    )
    ins_a = new_instructor(**instructor_spec(0))
    ins_b = new_instructor(**instructor_spec(1))
    k_fall = offer_contract(fall["id"], ins_a["id"])
    k_late = offer_contract(late["id"], ins_a["id"])
    k_lab = offer_contract(lab["id"], ins_b["id"])
    sign_contract(k_fall["id"], ins_a["id"])
    sign_contract(k_late["id"], ins_a["id"])
    sign_contract(k_lab["id"], ins_b["id"])
    fall = publish_offering(fall["id"])
    lab = publish_offering(lab["id"])
    late = publish_offering(late["id"])
    learner = new_learner(**learner_spec(0))
    reg_fall = register_learner(fall["id"], learner["id"], fall["version"])
    reg_lab = register_learner(lab["id"], learner["id"], lab["version"])
    return {
        "fall": fall, "lab": lab, "late": late,
        "late_id": late["id"], "late_version": late["version"],
        "learner": learner, "learner_id": learner["id"],
        "reg_fall_id": reg_fall["id"], "reg_lab_id": reg_lab["id"],
    }


def setup_instructor_window_scene() -> dict:
    """One instructor holding three offered contracts across FALL, WINTER and LAB.

    FALL runs 2026-09-15 to 2026-11-15 and is already signed. WINTER runs
    2026-11-15 to 2027-01-15 and merely touches FALL. LAB runs 2026-10-01 to
    2026-12-01 and genuinely intersects FALL.
    """
    course = new_course(**COURSE_EXT_101)
    fall = new_offering(
        course["id"], term_code="2026FA", start_date="2026-09-15T00:00:00Z",
        end_date="2026-11-15T00:00:00Z", census_at="2026-09-01T00:00:00Z",
    )
    winter = new_offering(
        course["id"], term_code="2026WI", start_date="2026-11-15T00:00:00Z",
        end_date="2027-01-15T00:00:00Z", census_at="2026-11-01T00:00:00Z",
    )
    lab = new_offering(
        course["id"], term_code="2026FB", start_date="2026-10-01T00:00:00Z",
        end_date="2026-12-01T00:00:00Z", census_at="2026-09-20T00:00:00Z",
    )
    instructor = new_instructor(**instructor_spec(0))
    k_fall = offer_contract(fall["id"], instructor["id"])
    k_winter = offer_contract(winter["id"], instructor["id"])
    k_lab = offer_contract(lab["id"], instructor["id"])
    sign_contract(k_fall["id"], instructor["id"])
    return {
        "instructor": instructor, "instructor_id": instructor["id"],
        "fall_contract_id": k_fall["id"],
        "winter_contract_id": k_winter["id"],
        "lab_contract_id": k_lab["id"],
    }


def setup_census_headcount_boundary_scene() -> dict:
    """Two identically scheduled sections that both require three paid learners.

    The AT section carries three SELF_PAY enrollments and the UNDER section carries
    two, so the census fork lands on opposite sides of the same comparison. The clock
    is advanced to the shared census_at.
    """
    course = new_course(**COURSE_EXT_101)
    at = new_offering(course["id"], min_enrollment=3, max_enrollment=10, tuition_cents=60000)
    under = new_offering(course["id"], min_enrollment=3, max_enrollment=10, tuition_cents=60000)
    ins_a = new_instructor(**instructor_spec(0))
    ins_b = new_instructor(**instructor_spec(1))
    k_at = offer_contract(at["id"], ins_a["id"])
    k_under = offer_contract(under["id"], ins_b["id"])
    sign_contract(k_at["id"], ins_a["id"])
    sign_contract(k_under["id"], ins_b["id"])
    at = publish_offering(at["id"])
    under = publish_offering(under["id"])

    learners = [new_learner(**learner_spec(i)) for i in range(3)]
    at_regs = []
    for lr in learners:
        reg = register_learner(at["id"], lr["id"], as_registrar=True)
        pay_self(reg["id"])
        at_regs.append(reg)
    under_regs = []
    for lr in learners[:2]:
        reg = register_learner(under["id"], lr["id"], as_registrar=True)
        pay_self(reg["id"])
        under_regs.append(reg)

    set_clock("2026-09-01T00:00:00Z")
    return {
        "at_id": at["id"], "under_id": under["id"],
        "at_contract_id": k_at["id"], "under_contract_id": k_under["id"],
        "at_instructor_id": ins_a["id"], "under_instructor_id": ins_b["id"],
        "at_registration_ids": [r["id"] for r in at_regs],
        "under_registration_ids": [r["id"] for r in under_regs],
        "learners": learners,
    }


def setup_transfer_scene(
    destination_tuition_cents: int = 50000,
    destination_course_spec: dict = None,
    destination_overrides: dict = None,
) -> dict:
    """A paid enrollment on a fall section plus an OPEN spring destination section.

    One instructor staffs both because the two teaching windows do not intersect.
    When destination_course_spec is given the destination sits on a second course, so
    the CEU-compatibility rule can be exercised.
    """
    from .constants import SPRING_CENSUS, SPRING_END, SPRING_START, SPRING_TERM

    base = new_course(**COURSE_EXT_101)
    dest_course = base if destination_course_spec is None else new_course(**destination_course_spec)
    source = new_offering(base["id"], tuition_cents=60000)
    dest_kwargs = {
        "term_code": SPRING_TERM,
        "start_date": SPRING_START,
        "end_date": SPRING_END,
        "census_at": SPRING_CENSUS,
        "tuition_cents": destination_tuition_cents,
    }
    dest_kwargs.update(destination_overrides or {})
    dest = new_offering(dest_course["id"], **dest_kwargs)

    instructor = new_instructor(**instructor_spec(0))
    k_src = offer_contract(source["id"], instructor["id"])
    k_dst = offer_contract(dest["id"], instructor["id"])
    sign_contract(k_src["id"], instructor["id"])
    sign_contract(k_dst["id"], instructor["id"])
    source = publish_offering(source["id"])
    dest = publish_offering(dest["id"])

    learner = new_learner(**learner_spec(0))
    registration = register_learner(source["id"], learner["id"], source["version"])
    registration = pay_self(registration["id"], learner["id"])
    return {
        "base_course": base, "dest_course": dest_course,
        "source": source, "source_id": source["id"],
        "dest": dest, "dest_id": dest["id"],
        "instructor_id": instructor["id"],
        "learner": learner, "learner_id": learner["id"],
        "registration": registration, "registration_id": registration["id"],
    }


def setup_voucher_funded_enrollment(
    funded_cents: int = 500000,
    face_value_cents: int = 200000,
    offering_overrides: dict = None,
    expires_at: str = DEFAULT_VOUCHER_EXPIRY,
) -> dict:
    """A single learner seated on a section and paid out of a corporate voucher.

    The section defaults to one that requires three paid learners and censuses on
    2026-09-05, so a later census call cancels it and unwinds the voucher commitment.
    """
    overrides = {
        "min_enrollment": 3,
        "max_enrollment": 10,
        "tuition_cents": 60000,
        "start_date": "2026-09-20T00:00:00Z",
        "end_date": "2026-11-20T00:00:00Z",
        "census_at": "2026-09-05T00:00:00Z",
    }
    overrides.update(offering_overrides or {})
    scene = setup_open_offering(offering_overrides=overrides)
    learner = new_learner(**learner_spec(0))
    money = setup_assigned_voucher(
        learner["id"], funded_cents, face_value_cents, expires_at
    )
    registration = register_learner(scene["offering_id"], learner["id"], scene["version"])
    scene.update(money)
    scene["learner"] = learner
    scene["learner_id"] = learner["id"]
    scene["registration"] = registration
    scene["registration_id"] = registration["id"]
    return scene


def setup_single_seat_offering_with_waitlist(waitlisted: int = 1) -> dict:
    """A one-seat section that has already flipped to WAITLIST_ONLY.

    The first learner takes the only seat; the remaining learners register and pay
    and therefore land WAITLISTED. Returns the seated registration, the waitlisted
    registrations and the section as last read.
    """
    scene = setup_open_offering(
        offering_overrides={"min_enrollment": 1, "max_enrollment": 1, "tuition_cents": 60000}
    )
    seated = add_paid_registration(scene["offering_id"], learner_index=0)
    waiting = [
        add_paid_registration(scene["offering_id"], learner_index=i + 1)
        for i in range(waitlisted)
    ]
    scene["seated"] = seated
    scene["waiting"] = waiting
    scene["offering"] = read_offering(scene["offering_id"])
    return scene


def setup_locked_offering_with_underfunded_voucher() -> dict:
    """A CENSUS_LOCKED section carrying one still-unpaid registration whose learner
    holds a voucher far too small to cover the amount due.

    Paying that registration violates both the section-openness rule and the voucher
    balance rule at once.
    """
    scene = setup_open_offering(
        offering_overrides={"min_enrollment": 1, "max_enrollment": 10, "tuition_cents": 60000}
    )
    ben = new_learner(**learner_spec(1))
    ben_reg = register_learner(scene["offering_id"], ben["id"], as_registrar=True)
    pay_self(ben_reg["id"])

    ada = new_learner(**learner_spec(0))
    ada_reg = register_learner(scene["offering_id"], ada["id"], as_registrar=True)

    money = setup_assigned_voucher(ada["id"], 1000, 1000)

    set_clock("2026-09-01T00:00:00Z")
    scene["offering"] = take_census(scene["offering_id"])
    scene.update(money)
    scene["learner_id"] = ada["id"]
    scene["registration_id"] = ada_reg["id"]
    scene["paid_registration_id"] = ben_reg["id"]
    return scene


def setup_completed_offering_for_settlement(
    num_learners: int = 1,
    completions: int = 0,
    contract_overrides: dict = None,
    offering_overrides: dict = None,
    end_clock: str = "2026-11-15T00:00:00Z",
) -> dict:
    """A section carried through census, optional completions and closeout.

    Leaves the contract ACTIVE on a COMPLETED section, which is exactly the state
    instructor pay settles from.
    """
    scene = setup_census_locked_offering(
        num_learners=num_learners,
        contract_overrides=contract_overrides,
        offering_overrides=offering_overrides,
    )
    sessions = scene["offering"]["session_count"]
    for seat in scene["seats"][:completions]:
        record_attendance(seat["registration_id"], sessions, scene["instructor_id"])
        award_completion(seat["registration_id"], scene["instructor_id"])
    set_clock(end_clock)
    scene["offering"] = close_offering(scene["offering_id"])
    return scene


def setup_dual_pay_basis_scene() -> dict:
    """One section staffed by two instructors on opposite pay bases.

    Three learners pay before census so the frozen census headcount is 3; two of them
    attend in full and are completed, so the final-completion headcount is 2 when the
    section closes.
    """
    course = new_course(**COURSE_EXT_101)
    offering = new_offering(
        course["id"], min_enrollment=3, max_enrollment=10, tuition_cents=60000
    )
    ins_a = new_instructor(**instructor_spec(0))
    ins_b = new_instructor(**instructor_spec(1))
    k_a = offer_contract(offering["id"], ins_a["id"], pay_basis="CENSUS_LOCKED")
    k_b = offer_contract(offering["id"], ins_b["id"], pay_basis="FINAL_COMPLETION")
    sign_contract(k_a["id"], ins_a["id"])
    sign_contract(k_b["id"], ins_b["id"])
    offering = publish_offering(offering["id"])

    seats = []
    for i in range(3):
        learner = new_learner(**learner_spec(i))
        reg = register_learner(offering["id"], learner["id"], as_registrar=True)
        pay_self(reg["id"])
        seats.append({"learner_id": learner["id"], "registration_id": reg["id"]})

    set_clock("2026-09-01T00:00:00Z")
    take_census(offering["id"])
    activate_contract(k_a["id"])
    activate_contract(k_b["id"])

    record_attendance(seats[0]["registration_id"], 10, ins_a["id"])
    record_attendance(seats[1]["registration_id"], 10, ins_a["id"])
    record_attendance(seats[2]["registration_id"], 5, ins_a["id"])
    award_completion(seats[0]["registration_id"], ins_a["id"])
    award_completion(seats[1]["registration_id"], ins_a["id"])

    set_clock("2026-11-15T00:00:00Z")
    close_offering(offering["id"])
    return {
        "offering_id": offering["id"],
        "census_contract_id": k_a["id"],
        "final_contract_id": k_b["id"],
        "instructor_a_id": ins_a["id"],
        "instructor_b_id": ins_b["id"],
        "seats": seats,
    }


def setup_draft_petition_with_citation(
    target_course_spec: dict,
    census_clock: str = "2026-09-01T00:00:00Z",
    course_spec: dict = None,
    offering_overrides: dict = None,
    weight: float = 1.0,
) -> dict:
    """A DRAFT petition that already cites one issued completion record."""
    scene = setup_issued_completion(
        census_clock=census_clock,
        course_spec=course_spec,
        offering_overrides=offering_overrides,
    )
    target_course = new_course(**target_course_spec)
    petition = new_petition(scene["learner_id"], target_course["id"])
    citation = cite_record(
        petition["id"], scene["record_id"], scene["learner_id"], weight
    )
    scene["petition"] = petition
    scene["petition_id"] = petition["id"]
    scene["citation"] = citation
    scene["citation_id"] = citation["id"]
    scene["target_course"] = target_course
    scene["target_course_id"] = target_course["id"]
    return scene

"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data() so a
setup failure surfaces as a clear setup error rather than a confusing
assertion failure deep inside a test.

Identity threading: after creating a Family, any ownership-gated call
(enroll, withdraw, conference request by a family, ...) uses
make_family_headers(family["id"]); likewise make_guide_headers(guide["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    EXEMPTION_MAX_SEAT_CAPACITY,
    EXEMPTION_ZONING_CLASSES,
    TEST_DEFAULTS,
)
from .factories import (
    create_curriculum_plan_payload,
    create_facility_site_payload,
    create_family_payload,
    create_guide_assignment_payload,
    create_guide_payload,
    create_invoice_payload,
    create_licensing_determination_payload,
    create_pod_payload,
    create_progress_conference_payload,
    create_safety_policy_payload,
    create_seat_payload,
    create_student_payload,
    create_voucher_account_payload,
)
from .test_users import (
    TEST_USERS,
    make_family_headers,
    make_guide_headers,
    make_registrar_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
TERM_START = TEST_DEFAULTS["TERM_START_DATE"]
TERM_END = TEST_DEFAULTS["TERM_END_DATE"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Advance the server logical clock (PlatformAdmin-only capability)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_site(**overrides):
    payload = create_facility_site_payload(**overrides)
    return get_success_data(api_client.create_facility_site(payload, ADMIN))


def create_pod(site_id: str, **overrides):
    payload = create_pod_payload(site_id, **overrides)
    return get_success_data(api_client.create_pod(payload, OPERATOR))


def create_family(**overrides):
    payload = create_family_payload(**overrides)
    return get_success_data(api_client.create_family(payload, REGISTRAR))


def create_student(family_id: str, **overrides):
    payload = create_student_payload(**overrides)
    return get_success_data(api_client.create_student(family_id, payload, REGISTRAR))


def create_voucher_account(student_id: str, **overrides):
    payload = create_voucher_account_payload(**overrides)
    return get_success_data(api_client.create_voucher_account(student_id, payload, REGISTRAR))


def create_guide(tier: str = "CERTIFIED", activate: bool = True, **overrides):
    payload = create_guide_payload(certification_tier=tier, **overrides)
    guide = get_success_data(api_client.create_guide(payload, ADMIN))
    if activate:
        guide = get_success_data(api_client.activate_guide(guide["id"], ADMIN))
    return guide


def create_guide_assignment(pod_id: str, guide_id: str, **overrides):
    payload = create_guide_assignment_payload(guide_id, **overrides)
    return get_success_data(api_client.create_guide_assignment(pod_id, payload, OPERATOR))


def get_pod(pod_id: str):
    return get_success_data(api_client.get_pod(pod_id, OPERATOR))


def get_pod_version(pod_id: str) -> int:
    return get_pod(pod_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: pod state progression
# ---------------------------------------------------------------------------

def setup_pod_with_approved_policy_and_plan(site_id=None, pod_overrides=None,
                                            plan_overrides=None):
    """DRAFT pod + APPROVED safety policy + APPROVED curriculum plan.

    Returns (pod, site, policy, plan).
    """
    site = create_site() if site_id is None else get_success_data(
        api_client.get_facility_site(site_id, ADMIN)
    )
    pod = create_pod(site["id"], **(pod_overrides or {}))
    policy = get_success_data(api_client.create_safety_policy(
        pod["id"], create_safety_policy_payload(), OPERATOR
    ))
    policy = get_success_data(
        api_client.approve_safety_policy(pod["id"], policy["id"], ADMIN)
    )
    plan = get_success_data(api_client.create_curriculum_plan(
        pod["id"], create_curriculum_plan_payload(**(plan_overrides or {})), OPERATOR
    ))
    plan = get_success_data(
        api_client.submit_curriculum_plan(pod["id"], plan["id"], OPERATOR)
    )
    plan = get_success_data(
        api_client.approve_curriculum_plan(pod["id"], plan["id"], ADMIN)
    )
    pod = get_pod(pod["id"])
    return pod, site, policy, plan


def setup_pod_forming(**kwargs):
    """Pod advanced DRAFT -> FORMING via open-enrollment.

    Returns (pod, site, policy, plan).
    """
    pod, site, policy, plan = setup_pod_with_approved_policy_and_plan(**kwargs)
    pod = get_success_data(api_client.open_enrollment(pod["id"], OPERATOR))
    return pod, site, policy, plan


def setup_pod_licensing_review(guide=None, **kwargs):
    """Pod in LICENSING_REVIEW with a determination in SUBMITTED, plus one
    SCHEDULED guide assignment covering the whole term (so the later grant
    cascade can activate the pod).

    Returns (pod, site, policy, plan, determination, guide, assignment).
    """
    pod, site, policy, plan = setup_pod_forming(**kwargs)
    if guide is None:
        guide = create_guide()
    assignment = create_guide_assignment(pod["id"], guide["id"])
    det = get_success_data(api_client.create_licensing_determination(
        pod["id"], create_licensing_determination_payload(), OPERATOR
    ))
    pod = get_pod(pod["id"])
    return pod, site, policy, plan, det, guide, assignment


def setup_pod_active(guide_tier: str = "CERTIFIED",
                     decision: str = None,
                     weekly_hours: int = 30,
                     **kwargs):
    """Pod fully walked to ACTIVE via a licensing grant.

    Path: DRAFT -> (policy + plan approved) -> FORMING -> (guide assignment
    covering term) -> LICENSING_REVIEW -> begin-review -> decide(grant).

    The grant pathway is chosen to match the pod's exemption eligibility
    (PRD 3.3): EXEMPT_GRANTED requires seat_capacity <= 10 and an
    exemption-eligible zoning class, so pods outside those bounds are walked
    through FULL_LICENSE / LICENSE_GRANTED instead.

    Returns (pod, site, policy, plan, determination, guide, assignment).
    """
    pod, site, policy, plan = setup_pod_forming(**kwargs)
    guide = create_guide(tier=guide_tier)
    assignment = create_guide_assignment(
        pod["id"], guide["id"], weekly_hours=weekly_hours
    )
    if decision is None:
        if (pod["seat_capacity"] <= EXEMPTION_MAX_SEAT_CAPACITY
                and site["zoning_class"] in EXEMPTION_ZONING_CLASSES):
            decision = "EXEMPT_GRANTED"
        else:
            decision = "LICENSE_GRANTED"
    det_overrides = {}
    if decision == "LICENSE_GRANTED":
        # PRD 3.3: "Deciding LICENSE_GRANTED requires the determination's
        # submission_kind to be FULL_LICENSE."
        det_overrides["submission_kind"] = "FULL_LICENSE"
    det = get_success_data(api_client.create_licensing_determination(
        pod["id"], create_licensing_determination_payload(**det_overrides), OPERATOR
    ))
    det = get_success_data(
        api_client.begin_review_licensing_determination(pod["id"], det["id"], OFFICER)
    )
    det = get_success_data(api_client.decide_licensing_determination(
        pod["id"], det["id"], {"decision": decision}, OFFICER
    ))
    pod = get_pod(pod["id"])
    return pod, site, policy, plan, det, guide, assignment


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy (family/student/seat)
# ---------------------------------------------------------------------------

def setup_family_student_seat(pod, enrolled_on: str = TERM_START,
                              student_overrides=None):
    """Registrar-backed family + student + RESERVED seat on the given pod.

    Returns (family, student, seat).
    """
    family = create_family()
    student = create_student(family["id"], **(student_overrides or {}))
    seat = get_success_data(api_client.create_seat(
        pod["id"], create_seat_payload(student["id"], enrolled_on=enrolled_on),
        REGISTRAR,
    ))
    return family, student, seat


def enroll_seat(pod_id: str, seat, family_id: str):
    """Enroll a RESERVED seat, fetching the current pod version for OCC."""
    pod_v = get_pod_version(pod_id)
    return get_success_data(api_client.enroll_seat(
        pod_id, seat["id"], {"expected_pod_version": pod_v},
        make_family_headers(family_id),
    ))


def setup_enrolled_seat(pod, enrolled_on: str = TERM_START, student_overrides=None):
    """Family + student + seat walked all the way to ENROLLED.

    Returns (family, student, seat_enrolled).
    """
    family, student, seat = setup_family_student_seat(
        pod, enrolled_on=enrolled_on, student_overrides=student_overrides
    )
    seat = enroll_seat(pod["id"], seat, family["id"])
    return family, student, seat


# ---------------------------------------------------------------------------
# Tier 3: invoicing and payments
# ---------------------------------------------------------------------------

def create_issued_invoice(pod_id: str, seat_id: str, **overrides):
    """DRAFT invoice -> ISSUED (computes subtotal/admin fee/total)."""
    inv = get_success_data(api_client.create_invoice(
        pod_id, seat_id, create_invoice_payload(**overrides), OPERATOR
    ))
    return get_success_data(api_client.issue_invoice(pod_id, seat_id, inv["id"], OPERATOR))


def post_and_clear_payment(pod_id: str, seat_id: str, invoice_id: str,
                           amount_cents: int, source_kind: str = "FAMILY",
                           voucher_account_id=None, as_headers=None):
    """Post a payment and clear it. Returns the cleared payment."""
    payload = {"source_kind": source_kind, "amount_cents": amount_cents}
    if voucher_account_id is not None:
        payload["voucher_account_id"] = voucher_account_id
    payment = get_success_data(api_client.create_payment(
        pod_id, seat_id, invoice_id, payload, as_headers or REGISTRAR
    ))
    return get_success_data(api_client.clear_payment(payment["id"], OPERATOR))


# ---------------------------------------------------------------------------
# Tier 4: accumulation / multi-seat scenarios
# ---------------------------------------------------------------------------

def setup_active_pod_with_enrolled_seats(num_seats: int, seat_capacity: int = 12,
                                         guide_tier: str = "CERTIFIED",
                                         weekly_hours: int = 30,
                                         clock: str = DEFAULT_CLOCK,
                                         enrolled_on: str = TERM_START):
    """ACTIVE pod with exactly num_seats ENROLLED seats (each its own
    family/student) and one ACTIVE/SCHEDULED guide assignment covering the
    term.

    Returns dict with keys: pod, site, policy, plan, det, guide, assignment,
    seats (list of (family, student, seat) triples).
    """
    set_clock(clock)
    pod, site, policy, plan, det, guide, assignment = setup_pod_active(
        guide_tier=guide_tier,
        weekly_hours=weekly_hours,
        pod_overrides={"seat_capacity": seat_capacity},
    )
    triples = []
    for _ in range(num_seats):
        triples.append(setup_enrolled_seat(pod, enrolled_on=enrolled_on))
    pod = get_pod(pod["id"])
    return {
        "pod": pod, "site": site, "policy": policy, "plan": plan,
        "det": det, "guide": guide, "assignment": assignment,
        "seats": triples,
    }


# ---------------------------------------------------------------------------
# Tier 5: withdrawal / refund / dissolution
# ---------------------------------------------------------------------------

def withdraw_seat(pod_id: str, seat_id: str, family_id: str, withdrawn_on: str):
    return get_success_data(api_client.withdraw_seat(
        pod_id, seat_id, {"withdrawn_on": withdrawn_on},
        make_family_headers(family_id),
    ))


def list_dissolution_claims(pod_id: str):
    data, _meta = _list_claims(pod_id, {"claim_kind": "DISSOLUTION"})
    return data


def _list_claims(pod_id: str, params=None):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_refund_claims_for_pod(pod_id, REGISTRAR, params=params)
    return validate_paginated(resp)


def setup_dissolving_pod(num_seats: int = 1, clock: str = "2026-09-01T00:00:00Z",
                         with_payment: bool = False):
    """ACTIVE pod with num_seats ENROLLED seats, walked into DISSOLVING.

    Returns dict with pod (DISSOLVING), seats (post-cascade triples),
    claims (dissolution RefundClaims), and context entities.
    """
    ctx = setup_active_pod_with_enrolled_seats(num_seats=num_seats, clock=clock)
    pod = ctx["pod"]
    if with_payment:
        for (family, student, seat) in ctx["seats"]:
            inv = create_issued_invoice(pod["id"], seat["id"])
            post_and_clear_payment(
                pod["id"], seat["id"], inv["id"],
                amount_cents=inv["total_cents"],
            )
        pod = get_pod(pod["id"])
    pod_v = pod["version"]
    pod = get_success_data(api_client.dissolve_pod(
        pod["id"],
        {"expected_pod_version": pod_v, "dissolution_reason": "operator choice"},
        OPERATOR,
    ))
    claims = list_dissolution_claims(pod["id"])
    refreshed = []
    for (family, student, seat) in ctx["seats"]:
        seat_now = get_success_data(api_client.get_seat(seat["id"], REGISTRAR))
        student_now = get_success_data(api_client.get_student(student["id"], REGISTRAR))
        family_now = get_success_data(api_client.get_family(
            family["id"], make_family_headers(family["id"])
        ))
        refreshed.append((family_now, student_now, seat_now))
    ctx.update({"pod": pod, "seats": refreshed, "claims": claims})
    return ctx


def decide_all_claims(pod_id: str, claims, decision: str = "APPROVED",
                      filer_user_id: str = "test-registrar-1"):
    """Walk each claim FILED -> UNDER_REVIEW -> decided, respecting
    segregation of duties (reviewer differs from filer)."""
    reviewer = make_registrar_headers("test-registrar-reviewer-1")
    decided = []
    for claim in claims:
        get_success_data(
            api_client.begin_review_refund_claim(pod_id, claim["id"], reviewer)
        )
        payload = {"decision": decision}
        if decision == "APPROVED":
            payload["approved_amount_cents"] = claim["claimed_amount_cents"]
        decided.append(get_success_data(
            api_client.decide_refund_claim(pod_id, claim["id"], payload, reviewer)
        ))
    return decided


def setup_dissolved_pod(num_seats: int = 1, clock: str = "2026-09-01T00:00:00Z"):
    """Full lifecycle to terminal DISSOLVED: dissolve, decide every
    dissolution claim, finalize.

    Returns the context dict from setup_dissolving_pod plus finalized pod.
    """
    ctx = setup_dissolving_pod(num_seats=num_seats, clock=clock)
    pod = ctx["pod"]
    decide_all_claims(pod["id"], ctx["claims"])
    pod = get_success_data(api_client.finalize_dissolution(pod["id"], ADMIN))
    refreshed = []
    for (family, student, seat) in ctx["seats"]:
        seat_now = get_success_data(api_client.get_seat(seat["id"], REGISTRAR))
        student_now = get_success_data(api_client.get_student(student["id"], REGISTRAR))
        family_now = get_success_data(api_client.get_family(
            family["id"], make_family_headers(family["id"])
        ))
        refreshed.append((family_now, student_now, seat_now))
    ctx.update({"pod": pod, "seats": refreshed})
    return ctx

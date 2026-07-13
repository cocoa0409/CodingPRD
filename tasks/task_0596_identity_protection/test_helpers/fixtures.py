"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its preconditions
from scratch using only PRD-declared endpoints. Setup calls use the lenient validator so a
broken precondition surfaces as "Setup step failed" rather than a confusing assertion.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_alert_payload,
    create_claim_payload,
    create_engagement_payload,
    create_family_member_payload,
    create_plan_payload,
    create_specialist_payload,
    create_thaw_window_payload,
    create_wallet_item_payload,
    enroll_subscriber_payload,
    expense,
)
from .test_users import (
    TEST_USERS,
    make_adjuster_headers,
    make_admin_headers,
    make_specialist_headers,
    make_subscriber_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]

# Default engagement window — comfortably after the 2026-05-01T00:00:00Z startup clock.
DEFAULT_WINDOW_START = "2026-06-10T09:00:00Z"
DEFAULT_WINDOW_END = "2026-06-10T11:00:00Z"


# ─── Tier 0: primitives ───────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_plan(**overrides) -> dict:
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), ADMIN))


def enroll_subscriber(plan_id: str, **overrides) -> dict:
    """Enroll (PENDING_VERIFICATION / NOT_ENROLLED). Response carries verification_token."""
    return get_success_data(
        api_client.enroll_subscriber(enroll_subscriber_payload(plan_id, **overrides), ANON)
    )


def verify_subscriber(subscriber: dict) -> dict:
    """Consume the token: enrollment ACTIVE, monitoring PENDING_DATA, bureau profiles created."""
    return get_success_data(
        api_client.verify_subscriber(
            subscriber["id"], {"verification_token": subscriber["verification_token"]}, ANON
        )
    )


def create_verified_subscriber(plan: dict = None, plan_overrides: dict = None, **sub_overrides):
    """Plan + enrolled + verified subscriber. Returns (plan, verified_subscriber)."""
    if plan is None:
        plan = create_plan(**(plan_overrides or {}))
    enrolled = enroll_subscriber(plan["id"], **sub_overrides)
    verified = verify_subscriber(enrolled)
    # The verify response omits nothing we need, but the token only exists on the enrol body.
    verified["verification_token"] = enrolled.get("verification_token")
    return plan, verified


def get_subscriber(subscriber_id: str) -> dict:
    return get_success_data(api_client.get_subscriber(subscriber_id, ADMIN))


def get_credit_summary(subscriber_id: str) -> dict:
    return get_success_data(api_client.get_credit_summary(subscriber_id, ADMIN))


def get_bureau_profiles(subscriber_id: str) -> list:
    """Bureau profiles ordered by created_at ASC (EQUIFAX, EXPERIAN, TRANSUNION)."""
    return get_success_data(api_client.list_bureau_profiles(subscriber_id, ADMIN))


def score_refresh(profile_id: str, credit_score: int) -> dict:
    return get_success_data(
        api_client.score_refresh(profile_id, {"credit_score": credit_score}, ADMIN)
    )


def create_specialist(**overrides) -> dict:
    return get_success_data(
        api_client.create_specialist(create_specialist_payload(**overrides), ADMIN)
    )


def get_specialist(specialist_id: str) -> dict:
    return get_success_data(api_client.get_specialist(specialist_id, ADMIN))


def create_family_member(subscriber_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_family_member(
            subscriber_id,
            create_family_member_payload(**overrides),
            make_subscriber_headers(subscriber_id),
        )
    )


def create_wallet_item(subscriber_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_wallet_item(
            subscriber_id,
            create_wallet_item_payload(**overrides),
            make_subscriber_headers(subscriber_id),
        )
    )


def create_alert(subscriber_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_alert(create_alert_payload(subscriber_id, **overrides), ADMIN)
    )


def get_alert(alert_id: str) -> dict:
    return get_success_data(api_client.get_alert(alert_id, ADMIN))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_restoration_case(case_id, ADMIN))


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, ADMIN))


def list_cases(**params) -> list:
    return get_success_data(api_client.list_restoration_cases(ADMIN, params=params or None))


def list_claims(**params) -> list:
    return get_success_data(api_client.list_claims(ADMIN, params=params or None))


def list_engagements(**params) -> list:
    return get_success_data(api_client.list_engagements(ADMIN, params=params or None))


# ─── Tier 1: state progression ────────────────────────────────────────────────

def acknowledge_alert(alert_id: str) -> dict:
    return get_success_data(api_client.acknowledge_alert(alert_id, ADMIN))


def confirm_fraud(alert_id: str) -> dict:
    return get_success_data(api_client.confirm_fraud_alert(alert_id, ADMIN))


def case_for_alert(alert_id: str) -> dict:
    """The RestorationCase opened by an alert's confirm-fraud transition."""
    cases = list_cases(origin_alert_id=alert_id)
    assert cases, f"Setup step failed: no restoration case for origin alert {alert_id}"
    return cases[0]


def create_confirmed_fraud_alert(subscriber_id: str, **alert_overrides):
    """Ingest -> acknowledge -> confirm-fraud. Returns (alert, case)."""
    alert = create_alert(subscriber_id, **alert_overrides)
    acknowledge_alert(alert["id"])
    confirm_fraud(alert["id"])
    return get_alert(alert["id"]), case_for_alert(alert["id"])


def assign_case(case_id: str, specialist_id: str = None) -> dict:
    """Assign explicitly, or omit specialist_id to invoke the selection policy."""
    payload = {} if specialist_id is None else {"specialist_id": specialist_id}
    return get_success_data(api_client.assign_case(case_id, payload, ADMIN))


def book_engagement(
    specialist_id: str,
    case_id: str,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    headers: dict = None,
) -> dict:
    """Book a work window, echoing the specialist's freshly-read version (PRD §2.6)."""
    version = get_specialist(specialist_id)["version"]
    payload = create_engagement_payload(
        specialist_id, case_id, window_start, window_end, version
    )
    return get_success_data(api_client.create_engagement(payload, headers or ADMIN))


def resolve_case(case_id: str, specialist_id: str, summary: str = "Restoration complete.") -> dict:
    return get_success_data(
        api_client.resolve_case(
            case_id, {"resolution_summary": summary}, make_specialist_headers(specialist_id)
        )
    )


def freeze_profile(profile_id: str, subscriber_id: str) -> dict:
    """Drive a bureau file UNFROZEN -> FREEZE_PENDING -> FROZEN."""
    get_success_data(
        api_client.freeze_request(
            profile_id, {"action": "FREEZE"}, make_subscriber_headers(subscriber_id)
        )
    )
    return get_success_data(api_client.confirm_bureau_profile(profile_id, ADMIN))


def create_thaw_window(
    profile_id: str, subscriber_id: str, window_start: str, window_end: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_thaw_window(
            profile_id,
            create_thaw_window_payload(window_start, window_end, **overrides),
            make_subscriber_headers(subscriber_id),
        )
    )


# ─── Tier 2: entity hierarchy ─────────────────────────────────────────────────

def setup_frozen_equifax_profile(plan_overrides: dict = None) -> dict:
    """Verified subscriber whose EQUIFAX bureau file has been driven to FROZEN."""
    plan, subscriber = create_verified_subscriber(plan_overrides=plan_overrides)
    profiles = get_bureau_profiles(subscriber["id"])
    equifax = profiles[0]
    freeze_profile(equifax["id"], subscriber["id"])
    return {
        "plan": plan,
        "subscriber": subscriber,
        "profiles": profiles,
        "equifax": get_success_data(api_client.get_bureau_profile(equifax["id"], ADMIN)),
    }


def setup_open_case(
    plan_overrides: dict = None,
    specialist_overrides: dict = None,
    alert_overrides: dict = None,
) -> dict:
    """Verified subscriber + one specialist + one confirmed-fraud alert holding an OPEN case."""
    plan, subscriber = create_verified_subscriber(plan_overrides=plan_overrides)
    specialist = create_specialist(**(specialist_overrides or {}))
    alert, case = create_confirmed_fraud_alert(subscriber["id"], **(alert_overrides or {}))
    return {
        "plan": plan,
        "subscriber": subscriber,
        "specialist": specialist,
        "alert": alert,
        "case": case,
    }


# ─── Tier 3: full lifecycle shortcuts ─────────────────────────────────────────

def setup_in_progress_case(
    plan_overrides: dict = None,
    specialist_overrides: dict = None,
    alert_overrides: dict = None,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
) -> dict:
    """Case walked OPEN -> ASSIGNED -> IN_PROGRESS (first engagement booked)."""
    ctx = setup_open_case(plan_overrides, specialist_overrides, alert_overrides)
    assign_case(ctx["case"]["id"], ctx["specialist"]["id"])
    engagement = book_engagement(
        ctx["specialist"]["id"], ctx["case"]["id"], window_start, window_end
    )
    ctx["engagement"] = engagement
    ctx["case"] = get_case(ctx["case"]["id"])
    ctx["specialist"] = get_specialist(ctx["specialist"]["id"])
    return ctx


def setup_resolved_case(
    plan_overrides: dict = None,
    specialist_overrides: dict = None,
    alert_overrides: dict = None,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    resolution_summary: str = "Restoration complete.",
) -> dict:
    """Case walked all the way to RESOLVED — the precondition for opening a claim."""
    ctx = setup_in_progress_case(
        plan_overrides, specialist_overrides, alert_overrides, window_start, window_end
    )
    resolve_case(ctx["case"]["id"], ctx["specialist"]["id"], resolution_summary)
    ctx["case"] = get_case(ctx["case"]["id"])
    ctx["specialist"] = get_specialist(ctx["specialist"]["id"])
    ctx["alert"] = get_alert(ctx["alert"]["id"])
    ctx["subscriber"] = get_subscriber(ctx["subscriber"]["id"])
    return ctx


# ─── Tier 4: claims ───────────────────────────────────────────────────────────

def create_claim(case_id: str, subscriber_id: str, expenses: list) -> dict:
    """Open a DRAFT claim, echoing the case's freshly-read version (PRD §2.6)."""
    case_version = get_case(case_id)["version"]
    payload = create_claim_payload(case_id, case_version, expenses)
    return get_success_data(
        api_client.create_claim(payload, make_subscriber_headers(subscriber_id))
    )


def submit_claim(claim_id: str, subscriber_id: str) -> dict:
    return get_success_data(
        api_client.submit_claim(claim_id, make_subscriber_headers(subscriber_id))
    )


def approve_claim(claim_id: str, adjuster_user_id: str = "adjuster-001") -> dict:
    return get_success_data(
        api_client.approve_claim(claim_id, make_adjuster_headers(adjuster_user_id))
    )


def pay_claim(claim_id: str, admin_user_id: str = "admin-009") -> dict:
    return get_success_data(api_client.pay_claim(claim_id, make_admin_headers(admin_user_id)))


def setup_draft_claim(
    expenses: list = None,
    plan_overrides: dict = None,
    specialist_overrides: dict = None,
    alert_overrides: dict = None,
) -> dict:
    """Resolved case + a DRAFT claim on it."""
    ctx = setup_resolved_case(plan_overrides, specialist_overrides, alert_overrides)
    lines = expenses if expenses is not None else [expense("LEGAL_FEES", 50000, True)]
    ctx["claim"] = create_claim(ctx["case"]["id"], ctx["subscriber"]["id"], lines)
    return ctx


def setup_submitted_claim(
    expenses: list = None,
    plan_overrides: dict = None,
    specialist_overrides: dict = None,
    alert_overrides: dict = None,
) -> dict:
    """Resolved case + a SUBMITTED claim (provisional_amount_cents written)."""
    ctx = setup_draft_claim(expenses, plan_overrides, specialist_overrides, alert_overrides)
    submit_claim(ctx["claim"]["id"], ctx["subscriber"]["id"])
    ctx["claim"] = get_claim(ctx["claim"]["id"])
    return ctx


def setup_approved_claim(
    expenses: list = None,
    plan_overrides: dict = None,
    specialist_overrides: dict = None,
    alert_overrides: dict = None,
    adjuster_user_id: str = "adjuster-001",
) -> dict:
    """Resolved case + an APPROVED claim (approved_cents and approved_by_user_id written)."""
    ctx = setup_submitted_claim(expenses, plan_overrides, specialist_overrides, alert_overrides)
    approve_claim(ctx["claim"]["id"], adjuster_user_id)
    ctx["claim"] = get_claim(ctx["claim"]["id"])
    ctx["adjuster_user_id"] = adjuster_user_id
    return ctx


def setup_paid_claim(
    expenses: list = None,
    plan_overrides: dict = None,
    specialist_overrides: dict = None,
    alert_overrides: dict = None,
    adjuster_user_id: str = "adjuster-001",
    admin_user_id: str = "admin-009",
) -> dict:
    """Resolved case + a PAID claim; the subscriber's budget cascade has fired."""
    ctx = setup_approved_claim(
        expenses, plan_overrides, specialist_overrides, alert_overrides, adjuster_user_id
    )
    pay_claim(ctx["claim"]["id"], admin_user_id)
    ctx["claim"] = get_claim(ctx["claim"]["id"])
    ctx["subscriber"] = get_subscriber(ctx["subscriber"]["id"])
    ctx["admin_user_id"] = admin_user_id
    return ctx


# ─── Tier 5: threshold targeting ──────────────────────────────────────────────

def setup_exhausting_paid_claim() -> dict:
    """A 100000-limit plan whose single PAID claim consumes the entire lifetime budget.

    A documented LEGAL_FEES expense of 102500 cents nets 100000 after the 2500 deductible,
    which is exactly the remaining budget — so the subscriber lands on EXHAUSTED.
    """
    return setup_paid_claim(
        expenses=[expense("LEGAL_FEES", 102500, True)],
        plan_overrides={
            "tier": "STANDARD",
            "monthly_fee_cents": 999,
            "insurance_limit_cents": 100000,
            "max_family_members": 1,
            "child_monitoring_included": False,
        },
        alert_overrides={"alert_type": "SSN_TRACE", "severity": "MEDIUM"},
    )


def setup_three_open_cases(specialist_overrides: dict = None) -> dict:
    """One specialist + three OPEN cases on one verified subscriber (all requiring TIER1)."""
    plan, subscriber = create_verified_subscriber(
        plan_overrides={
            "tier": "ADVANTAGE",
            "monthly_fee_cents": 1999,
            "max_family_members": 2,
            "child_monitoring_included": False,
            "min_specialist_tier": "TIER1",
        }
    )
    specialist = create_specialist(**(specialist_overrides or {}))
    cases = []
    for detail in ("breach A", "breach B", "breach C"):
        _, case = create_confirmed_fraud_alert(
            subscriber["id"],
            alert_type="DARK_WEB",
            severity="LOW",
            source_detail=detail,
        )
        cases.append(case)
    return {"plan": plan, "subscriber": subscriber, "specialist": specialist, "cases": cases}


def setup_two_specialists_two_open_cases() -> dict:
    """Ada (created first, max_caseload 1) and Bo (created second, max_caseload 5), both TIER2 and
    AVAILABLE, plus two OPEN TIER1 cases on one verified subscriber."""
    plan, subscriber = create_verified_subscriber(
        plan_overrides={
            "tier": "ADVANTAGE",
            "monthly_fee_cents": 1999,
            "max_family_members": 2,
            "child_monitoring_included": False,
            "min_specialist_tier": "TIER1",
        },
        full_name="Lena Ford",
        ssn_last4="5150",
    )
    ada = create_specialist(full_name="Ada Reyes", tier="TIER2", max_caseload=1)
    bo = create_specialist(full_name="Bo Tan", tier="TIER2", max_caseload=5)
    _, case1 = create_confirmed_fraud_alert(
        subscriber["id"],
        alert_type="DARK_WEB",
        severity="LOW",
        source_detail="credentials in Combo-A dump",
    )
    _, case2 = create_confirmed_fraud_alert(
        subscriber["id"],
        alert_type="CREDIT_INQUIRY",
        severity="LOW",
        source_detail="hard pull by Nova Cards",
    )
    return {
        "plan": plan,
        "subscriber": subscriber,
        "ada": ada,
        "bo": bo,
        "case1": case1,
        "case2": case2,
    }


def setup_tier1_specialist_at_capacity_and_critical_case() -> dict:
    """A TIER1 specialist saturated at max_caseload 1, plus a second OPEN case whose CRITICAL
    origin alert requires TIER3 — so an assign naming that specialist violates both the competency
    rule and the caseload rule."""
    plan, subscriber = create_verified_subscriber(
        plan_overrides={
            "tier": "ADVANTAGE",
            "monthly_fee_cents": 1999,
            "max_family_members": 2,
            "child_monitoring_included": False,
            "min_specialist_tier": "TIER1",
        },
        full_name="Gil Moreau",
        ssn_last4="4004",
    )
    junior = create_specialist(full_name="Lo Tier-One", tier="TIER1", max_caseload=1)
    _, low_case = create_confirmed_fraud_alert(
        subscriber["id"],
        alert_type="CREDIT_INQUIRY",
        severity="LOW",
        source_detail="soft inquiry escalated",
    )
    assign_case(low_case["id"], junior["id"])
    _, critical_case = create_confirmed_fraud_alert(
        subscriber["id"],
        alert_type="ACCOUNT_TAKEOVER",
        severity="CRITICAL",
        source_detail="brokerage account drained",
    )
    return {
        "plan": plan,
        "subscriber": subscriber,
        "specialist": get_specialist(junior["id"]),
        "low_case": get_case(low_case["id"]),
        "critical_case": critical_case,
    }


def setup_mixed_alert_set() -> dict:
    """Verified subscriber carrying three alerts that the two risk variants count differently.

    SSN_TRACE confirmed as fraud (both variants count it), DARK_WEB merely acknowledged (LIVE
    only), CREDIT_INQUIRY still NEW (LIVE only). No bureau has reported, so no score-drop term;
    no family members exist, so no multiplier.
    """
    plan, subscriber = create_verified_subscriber(full_name="Dana Vale", ssn_last4="4321")
    ssn_alert, _case = create_confirmed_fraud_alert(
        subscriber["id"],
        alert_type="SSN_TRACE",
        severity="MEDIUM",
        source_detail="SSN seen in ACME breach dump",
    )
    dark_web = create_alert(
        subscriber["id"],
        alert_type="DARK_WEB",
        severity="LOW",
        source_detail="email+password pair on paste site",
    )
    acknowledge_alert(dark_web["id"])
    credit_inquiry = create_alert(
        subscriber["id"],
        alert_type="CREDIT_INQUIRY",
        severity="LOW",
        source_detail="hard pull by Zenith Auto",
    )
    return {
        "plan": plan,
        "subscriber": get_subscriber(subscriber["id"]),
        "ssn_alert": ssn_alert,
        "dark_web_alert": get_alert(dark_web["id"]),
        "credit_inquiry_alert": credit_inquiry,
    }


def setup_escalation_ready(clock: str = "2026-06-01T00:00:00Z") -> dict:
    """Subscriber whose persisted risk_score is exactly 63 before an escalation is attempted.

    10 base + 25 (confirmed SSN_TRACE) + 20 (confirmed ACCOUNT_TAKEOVER) + 8 (a NEW
    CREDIT_INQUIRY, which the LIVE variant counts from ingestion) == 63.
    """
    set_clock(clock)
    plan, subscriber = create_verified_subscriber(
        plan_overrides={
            "tier": "ADVANTAGE",
            "monthly_fee_cents": 1999,
            "max_family_members": 2,
            "child_monitoring_included": False,
            "min_specialist_tier": "TIER1",
        },
        full_name="Omar Diaz",
        ssn_last4="6060",
    )
    ssn_alert, ssn_case = create_confirmed_fraud_alert(
        subscriber["id"],
        alert_type="SSN_TRACE",
        severity="MEDIUM",
        source_detail="SSN used on new utility account",
    )
    create_confirmed_fraud_alert(
        subscriber["id"],
        alert_type="ACCOUNT_TAKEOVER",
        severity="MEDIUM",
        source_detail="password reset from unknown device",
    )
    create_alert(
        subscriber["id"],
        alert_type="CREDIT_INQUIRY",
        severity="LOW",
        source_detail="hard pull by Meridian Bank",
    )
    return {
        "plan": plan,
        "subscriber": get_subscriber(subscriber["id"]),
        "ssn_alert": ssn_alert,
        "ssn_case": ssn_case,
        "clock": clock,
    }


def raise_underwriting_risk(subscriber_id: str, specs: list) -> None:
    """Push the underwriting number up by confirming extra alerts as fraud.

    `specs` is a list of (alert_type, severity, source_detail) triples; each becomes an alert
    that is acknowledged and confirmed, so it counts in both risk variants.
    """
    for alert_type, severity, source_detail in specs:
        create_confirmed_fraud_alert(
            subscriber_id,
            alert_type=alert_type,
            severity=severity,
            source_detail=source_detail,
        )
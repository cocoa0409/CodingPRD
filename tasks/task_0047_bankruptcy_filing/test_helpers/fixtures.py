"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system in a specific state reached through
5-15 API calls (register parties -> open case -> means test -> schedules ->
debts -> petition -> meeting -> hold -> plan -> confirm -> payments). These
helpers encapsulate those preambles so tests focus on assertions.

Identity threading: Debtor/Creditor/Trustee are entity-backed roles (PRD §2.1).
Every ownership-gated call uses make_*_headers(entity_id) with the real id, never
the shared fallback constant.

Setup uses get_success_data() (lenient) so a broken precondition surfaces as a
clear "setup failed" rather than a confusing assertion deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_debtor_payload, create_creditor_payload, create_trustee_payload,
    create_case_payload, create_means_test_payload, create_schedule_payload,
    create_debt_payload, create_meeting_payload, create_claim_payload,
    create_plan_payload, create_plan_payment_payload,
    create_stay_relief_motion_payload,
)
from .test_users import make_debtor_headers, make_creditor_headers, make_trustee_headers


# ─── Tier 0: party registration ──────────────────────────────────────────

def register_debtor(**overrides):
    """Register a Debtor. Returns the debtor dict."""
    res = api_client.create_debtor(
        create_debtor_payload(**overrides), make_debtor_headers("bootstrap"))
    return get_success_data(res)


def register_creditor(**overrides):
    """Register a Creditor. Returns the creditor dict."""
    res = api_client.create_creditor(
        create_creditor_payload(**overrides), make_creditor_headers("bootstrap"))
    return get_success_data(res)


def register_trustee(**overrides):
    """Register a Trustee. Returns the trustee dict."""
    res = api_client.create_trustee(
        create_trustee_payload(**overrides), make_trustee_headers("bootstrap"))
    return get_success_data(res)


# ─── Tier 1: case opening + means test ────────────────────────────────────

def open_case(debtor, **case_overrides):
    """Open a DRAFT case for an existing debtor. Returns the case dict."""
    headers = make_debtor_headers(debtor["id"])
    res = api_client.create_case(
        create_case_payload(debtor["id"], **case_overrides), headers)
    return get_success_data(res)


def submit_means_test(debtor, case, **mt_overrides):
    """Submit/compute the means test for a case. Returns the means-test dict."""
    headers = make_debtor_headers(debtor["id"])
    res = api_client.create_means_test(
        create_means_test_payload(case["id"], **mt_overrides), headers)
    return get_success_data(res)


def add_schedule(debtor, case, schedule_letter, **sched_overrides):
    """Add a Schedule A-J line to a case. Returns the schedule dict."""
    headers = make_debtor_headers(debtor["id"])
    res = api_client.create_schedule(
        create_schedule_payload(case["id"], schedule_letter, **sched_overrides), headers)
    return get_success_data(res)


def add_income_and_expense_schedules(debtor, case):
    """Add one Schedule I and one Schedule J (the petition precondition)."""
    add_schedule(debtor, case, "I", description="wages")
    add_schedule(debtor, case, "J", description="rent")


def add_debt(debtor, case, creditor, debt_class, scheduled_amount_cents):
    """Schedule a debt under a case. Returns the debt dict."""
    headers = make_debtor_headers(debtor["id"])
    res = api_client.create_debt(
        create_debt_payload(case["id"], creditor["id"],
                            debt_class=debt_class,
                            scheduled_amount_cents=scheduled_amount_cents), headers)
    return get_success_data(res)


# ─── Tier 2: reach a filed / drafted case ─────────────────────────────────

def setup_draft_case_ready_to_petition(filed_chapter="CHAPTER_13",
                                       prior_discharge_within_8y=False,
                                       mt_overrides=None, **case_overrides):
    """A DRAFT case with means test (PRESUMPTION_OK by default) and Schedules I+J,
    ready for the petition. Returns (debtor, case)."""
    debtor = register_debtor(prior_discharge_within_8y=prior_discharge_within_8y)
    case = open_case(debtor, filed_chapter=filed_chapter, **case_overrides)
    submit_means_test(debtor, case, **(mt_overrides or {}))
    add_income_and_expense_schedules(debtor, case)
    return debtor, case


def petition(debtor, case):
    """File the petition (DRAFT->FILED). Returns the updated case dict."""
    headers = make_debtor_headers(debtor["id"])
    return get_success_data(api_client.petition_case(case["id"], headers))


def setup_filed_case(filed_chapter="CHAPTER_13", prior_discharge_within_8y=False,
                     mt_overrides=None, **case_overrides):
    """A FILED case (stay ACTIVE). Returns (debtor, case_after_petition)."""
    debtor, case = setup_draft_case_ready_to_petition(
        filed_chapter=filed_chapter,
        prior_discharge_within_8y=prior_discharge_within_8y,
        mt_overrides=mt_overrides, **case_overrides)
    case = petition(debtor, case)
    return debtor, case


def current_case_version(debtor, case):
    """Read the case's current version (for the plan OCC token)."""
    headers = make_debtor_headers(debtor["id"])
    fresh = get_success_data(api_client.get_case(case["id"], headers))
    return fresh["version"]


# ─── Tier 3: meeting scheduling + holding ─────────────────────────────────

def schedule_meeting(trustee, case, **meeting_overrides):
    """Schedule the 341 meeting on a trustee. Returns the meeting dict."""
    headers = make_trustee_headers(trustee["id"])
    res = api_client.create_meeting(
        create_meeting_payload(case["id"], trustee["id"], **meeting_overrides), headers)
    return get_success_data(res)


def hold_meeting(trustee, meeting):
    """Conduct the meeting (SCHEDULED->HELD), bubbling the case to MEETING_HELD.
    Returns the updated meeting dict."""
    headers = make_trustee_headers(trustee["id"])
    return get_success_data(api_client.hold_meeting(meeting["id"], headers))


def setup_case_at_meeting_held(filed_chapter="CHAPTER_13",
                               prior_discharge_within_8y=False,
                               mt_overrides=None,
                               room_code="ROOM-MH",
                               scheduled_start="2026-07-10T09:00:00Z",
                               scheduled_end="2026-07-10T10:00:00Z",
                               **case_overrides):
    """A case advanced to MEETING_HELD (petition -> schedule meeting -> hold).
    Returns (debtor, trustee, case_at_meeting_held)."""
    debtor, case = setup_filed_case(
        filed_chapter=filed_chapter,
        prior_discharge_within_8y=prior_discharge_within_8y,
        mt_overrides=mt_overrides, **case_overrides)
    trustee = register_trustee()
    meeting = schedule_meeting(trustee, case, room_code=room_code,
                               scheduled_start=scheduled_start,
                               scheduled_end=scheduled_end)
    hold_meeting(trustee, meeting)
    case = get_success_data(api_client.get_case(case["id"], make_debtor_headers(debtor["id"])))
    return debtor, trustee, case


# ─── Tier 4: claims ────────────────────────────────────────────────────────

def file_claim(creditor, case, debt, claimed_amount_cents, filed_by_creditor=None):
    """File a proof of claim. Returns the claim dict. By default the movant
    creditor matches the debt's creditor (filing on its own debt)."""
    movant = filed_by_creditor or creditor
    headers = make_creditor_headers(movant["id"])
    res = api_client.create_claim(
        create_claim_payload(case["id"], debt["id"], movant["id"],
                             claimed_amount_cents=claimed_amount_cents), headers)
    return get_success_data(res)


def allow_claim(trustee, claim):
    """Allow a filed claim (FILED->ALLOWED), syncing the debt ledger. Returns the claim."""
    headers = make_trustee_headers(trustee["id"])
    return get_success_data(api_client.allow_claim(claim["id"], headers))


# ─── Tier 5: plans + payments ──────────────────────────────────────────────

def create_plan(debtor, case, monthly_payment_cents, plan_duration_months,
                expected_case_version=None):
    """Create a Chapter 13 plan (DRAFT). Returns the plan dict.
    If expected_case_version is None, reads the live case version first."""
    headers = make_debtor_headers(debtor["id"])
    if expected_case_version is None:
        expected_case_version = current_case_version(debtor, case)
    res = api_client.create_plan(
        create_plan_payload(case["id"], expected_case_version,
                            monthly_payment_cents=monthly_payment_cents,
                            plan_duration_months=plan_duration_months), headers)
    return get_success_data(res)


def file_plan(debtor, plan):
    """File the plan (DRAFT->FILED). Returns the updated plan dict."""
    headers = make_debtor_headers(debtor["id"])
    return get_success_data(api_client.file_plan(plan["id"], headers))


def confirm_plan(trustee, plan):
    """Confirm a filed plan (FILED->CONFIRMED). Returns the updated plan dict."""
    headers = make_trustee_headers(trustee["id"])
    return get_success_data(api_client.confirm_plan(plan["id"], headers))


def record_payment(trustee, plan, amount_cents):
    """Record a monthly trustee payment. Returns the payment dict."""
    headers = make_trustee_headers(trustee["id"])
    res = api_client.create_plan_payment(
        create_plan_payment_payload(plan["id"], amount_cents=amount_cents), headers)
    return get_success_data(res)


def setup_confirmed_plan_with_debts(debts, monthly_payment_cents, plan_duration_months,
                                    allow_claims=False, claim_amounts=None):
    """A Chapter 13 case with a CONFIRMED plan and scheduled debts.

    `debts` is a list of (debt_class, scheduled_amount_cents) tuples. Returns
    (debtor, trustee, creditor, case, plan, debt_records) where debt_records is
    the list of created debt dicts in the order supplied.

    Sequence: register parties -> open Ch13 case -> means test -> Schedules I+J
    -> create debts -> petition -> (optionally file+allow claims) -> create plan
    -> file plan -> schedule+hold meeting -> (optionally allow claims if not yet)
    -> confirm plan.

    For feasibility, claims may need to be allowed before confirm so the priority
    floor uses allowed amounts; set allow_claims=True with claim_amounts aligned
    to `debts` (None entries skip a claim for that debt).
    """
    debtor = register_debtor()
    creditor = register_creditor()
    trustee = register_trustee()
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)

    debt_records = []
    for debt_class, amount in debts:
        debt_records.append(add_debt(debtor, case, creditor, debt_class, amount))

    case = petition(debtor, case)

    claim_records = []
    if allow_claims and claim_amounts:
        for debt, amount in zip(debt_records, claim_amounts):
            if amount is None:
                claim_records.append(None)
                continue
            claim_records.append(file_claim(creditor, case, debt, amount))

    plan = create_plan(debtor, case, monthly_payment_cents, plan_duration_months)
    plan = file_plan(debtor, plan)

    meeting = schedule_meeting(trustee, case, room_code="ROOM-CP",
                               scheduled_start="2026-07-11T09:00:00Z",
                               scheduled_end="2026-07-11T10:00:00Z")
    hold_meeting(trustee, meeting)

    if allow_claims:
        for claim in claim_records:
            if claim is not None:
                allow_claim(trustee, claim)

    plan = confirm_plan(trustee, plan)
    return debtor, trustee, creditor, case, plan, debt_records


# ─── Tier 6: stay relief ───────────────────────────────────────────────────

def file_stay_relief_motion(creditor, case, debt):
    """File a stay-relief motion against a debt. Returns the motion dict."""
    headers = make_creditor_headers(creditor["id"])
    res = api_client.create_stay_relief_motion(
        create_stay_relief_motion_payload(case["id"], creditor["id"], debt["id"]), headers)
    return get_success_data(res)

"""Composite setup helpers for multi-step test prerequisites (Private Adoption Agency API).

Every fixture builds its preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server with an empty database before each test). Setup uses
get_success_data() (lenient validator) so setup failures surface clearly.

All five roles are opaque, so the shared role-header constants are the canonical form.
Where a flow must use two DISTINCT operators (segregation of duties on home-study
approve/return and on expense approve), the default constants already use distinct
ids per role (cw-1 / sup-1 / fo-1) and that separation is preserved.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_agency_payload, set_clock_payload, create_case_payload,
    create_family_payload, create_home_study_payload, create_birth_parent_payload,
    create_match_payload, create_consent_payload, create_icpc_payload,
    create_placement_payload, create_visit_payload, create_expense_payload,
    create_escrow_payload, create_invoice_payload, create_counseling_session_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["agency_admin_headers"]
SUP = TEST_USERS["supervisor_headers"]
CW = TEST_USERS["caseworker_headers"]
FO = TEST_USERS["finance_officer_headers"]
CA = TEST_USERS["compact_admin_headers"]


# ─── Primitive builders ──────────────────────────────────────────────────
def create_agency(fee_schedule_cents=3_000_000, **overrides):
    """Create an agency. Returns the agency entity."""
    res = api_client.create_agency(
        create_agency_payload(fee_schedule_cents=fee_schedule_cents, **overrides), ADMIN)
    return get_success_data(res)


def set_clock(agency_id, to_iso8601):
    """Advance the agency clock to to_iso8601. Returns the agency entity."""
    res = api_client.set_clock(set_clock_payload(agency_id, to_iso8601), ADMIN)
    return get_success_data(res)


def create_case(agency_id, child_state="CA", family_state="CA", **overrides):
    """Open a case. Returns the case entity (carries version)."""
    res = api_client.create_case(
        create_case_payload(agency_id, child_state=child_state,
                            family_state=family_state, **overrides), SUP)
    return get_success_data(res)


def create_family(case_id, annual_income_cents=8_000_000, **overrides):
    """Register an adoptive family on a case. Returns the family entity."""
    res = api_client.create_family(
        create_family_payload(case_id, annual_income_cents=annual_income_cents, **overrides), CW)
    return get_success_data(res)


def create_birth_parent(agency_id, birth_state="CA", **overrides):
    """Register a birth parent. Returns the birth parent entity."""
    res = api_client.create_birth_parent(
        create_birth_parent_payload(agency_id, birth_state=birth_state, **overrides), CW)
    return get_success_data(res)


def current_case_version(case_id, headers=SUP):
    """GET the case and return its current version (for OCC-guarded creates)."""
    res = api_client.get_case(case_id, headers)
    return get_success_data(res)["version"]


# ─── Tier 1: State Progression ───────────────────────────────────────────
def create_agency_with_clock(to_iso8601="2026-06-04T08:00:00.000Z", fee_schedule_cents=3_000_000):
    """Create an agency and set its clock. Returns the agency id."""
    agency = create_agency(fee_schedule_cents=fee_schedule_cents)
    set_clock(agency["id"], to_iso8601)
    return agency["id"]


def create_approved_home_study(case_id, family_id, author_id="cw-1", supervisor_id="sup-1"):
    """Create a home study, submit it (author), and approve it (supervisor != author).
    Returns the approved home study entity."""
    from .test_users import make_caseworker_headers, make_supervisor_headers
    cw = make_caseworker_headers(author_id)
    sup = make_supervisor_headers(supervisor_id)
    hs = get_success_data(api_client.create_home_study(
        create_home_study_payload(case_id, family_id), cw))
    api_client.submit_home_study(hs["id"], cw)
    res = api_client.approve_home_study(hs["id"], sup)
    return get_success_data(res)


def create_under_review_home_study(case_id, family_id, author_id="cw-1"):
    """Create a home study and submit it to UNDER_REVIEW. Returns the home study entity."""
    from .test_users import make_caseworker_headers
    cw = make_caseworker_headers(author_id)
    hs = get_success_data(api_client.create_home_study(
        create_home_study_payload(case_id, family_id), cw))
    res = api_client.submit_home_study(hs["id"], cw)
    return get_success_data(res)


def create_deficient_home_study(case_id, family_id, author_id="cw-1", supervisor_id="sup-1"):
    """Create -> submit -> return (DEFICIENT, revision_count=1). Returns the home study entity."""
    from .test_users import make_caseworker_headers, make_supervisor_headers
    cw = make_caseworker_headers(author_id)
    sup = make_supervisor_headers(supervisor_id)
    hs = get_success_data(api_client.create_home_study(
        create_home_study_payload(case_id, family_id), cw))
    api_client.submit_home_study(hs["id"], cw)
    res = api_client.return_home_study(hs["id"], sup)
    return get_success_data(res)


# ─── Tier 2/3: Case advanced through matching / consent ──────────────────
def setup_case_with_accepted_match(child_state="CA", family_state="CA",
                                   to_iso8601="2026-06-04T08:00:00.000Z",
                                   fee_schedule_cents=3_000_000,
                                   annual_income_cents=8_000_000,
                                   birth_state=None):
    """Full chain to an ACCEPTED match on a case with an APPROVED non-expired home study.

    Returns dict: agency_id, case_id, family_id, hs_id, bp_id, match_id, case_version.
    """
    if birth_state is None:
        birth_state = child_state
    agency_id = create_agency_with_clock(to_iso8601, fee_schedule_cents)
    case = create_case(agency_id, child_state=child_state, family_state=family_state)
    family = create_family(case["id"], annual_income_cents=annual_income_cents)
    hs = create_approved_home_study(case["id"], family["id"])
    bp = create_birth_parent(agency_id, birth_state=birth_state)
    match = get_success_data(api_client.create_match(
        create_match_payload(case["id"], family["id"], bp["id"]), CW))
    api_client.accept_match(match["id"], SUP)
    return {
        "agency_id": agency_id,
        "case_id": case["id"],
        "family_id": family["id"],
        "hs_id": hs["id"],
        "bp_id": bp["id"],
        "match_id": match["id"],
        "case_version": current_case_version(case["id"]),
    }


def create_signed_consent(case_id, birth_parent_id, expected_case_version,
                          revocation_basis="BUSINESS_DAYS",
                          child_dob="2026-06-01T08:00:00.000Z", **overrides):
    """Create a consent record (OCC-guarded) and sign it. Returns the signed consent entity."""
    consent = get_success_data(api_client.create_consent_record(
        create_consent_payload(case_id, birth_parent_id, expected_case_version,
                               revocation_basis=revocation_basis, child_dob=child_dob,
                               **overrides), CW))
    res = api_client.sign_consent(consent["id"], CW)
    return get_success_data(res)


def _advance_clock_past_deadline(agency_id, deadline_iso):
    """Advance the agency clock to strictly after deadline_iso (deadline + 1 second).

    Making a consent IRREVOCABLE requires the agency clock to be strictly after the
    consent's revocation_deadline (PRD §3.4). The deadline lands at 23:59:59.000Z, so
    one second later is the smallest representable instant past it.
    """
    from datetime import datetime, timedelta, timezone
    s = deadline_iso.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc) + timedelta(seconds=1)
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    set_clock(agency_id, iso)


def create_irrevocable_consent(agency_id, case_id, birth_parent_id, expected_case_version,
                               revocation_basis="BUSINESS_DAYS",
                               child_dob="2026-06-01T08:00:00.000Z"):
    """Create -> sign -> advance clock past revocation deadline -> finalize-consent
    (IRREVOCABLE). Returns the consent entity.

    The clock is advanced to one second after the signed consent's revocation_deadline
    because finalize-consent requires the agency clock strictly after that deadline.
    """
    consent = create_signed_consent(case_id, birth_parent_id, expected_case_version,
                                    revocation_basis=revocation_basis, child_dob=child_dob)
    _advance_clock_past_deadline(agency_id, consent["revocation_deadline"])
    res = api_client.finalize_consent(consent["id"], ADMIN)
    return get_success_data(res)


def setup_case_with_irrevocable_consent(child_state="CA", family_state="CA",
                                        to_iso8601="2026-06-04T08:00:00.000Z",
                                        annual_income_cents=8_000_000):
    """Chain through to an IRREVOCABLE consent (case at CONSENTED, in-state).

    Returns dict: agency_id, case_id, family_id, hs_id, bp_id, match_id, consent_id.
    """
    base = setup_case_with_accepted_match(child_state=child_state, family_state=family_state,
                                          to_iso8601=to_iso8601,
                                          annual_income_cents=annual_income_cents)
    cv = current_case_version(base["case_id"])
    consent = create_irrevocable_consent(base["agency_id"], base["case_id"], base["bp_id"], cv)
    base["consent_id"] = consent["id"]
    return base


# ─── ICPC progression (interstate) ───────────────────────────────────────
def create_icpc_receiving_approved(case_id):
    """For an interstate case with an ACCEPTED match: create -> submit -> approve-sending
    -> approve-receiving. Returns the RECEIVING_APPROVED clearance entity."""
    icpc = get_success_data(api_client.create_icpc_clearance(create_icpc_payload(case_id), CW))
    api_client.submit_icpc(icpc["id"], CW)
    api_client.approve_sending_icpc(icpc["id"], CA)
    res = api_client.approve_receiving_icpc(icpc["id"], CA)
    return get_success_data(res)


# ─── Placement progression ───────────────────────────────────────────────
def setup_pending_placement(child_state="NV", family_state="CA",
                            to_iso8601="2026-06-04T08:00:00.000Z",
                            annual_income_cents=8_000_000):
    """Interstate case advanced to a PENDING placement with IRREVOCABLE consent and
    RECEIVING_APPROVED ICPC.

    Returns dict: agency_id, case_id, family_id, hs_id, bp_id, match_id, consent_id,
    icpc_id, placement_id.
    """
    base = setup_case_with_accepted_match(child_state=child_state, family_state=family_state,
                                          to_iso8601=to_iso8601,
                                          annual_income_cents=annual_income_cents,
                                          birth_state=child_state)
    cv = current_case_version(base["case_id"])
    consent = create_irrevocable_consent(base["agency_id"], base["case_id"], base["bp_id"], cv)
    base["consent_id"] = consent["id"]
    icpc = create_icpc_receiving_approved(base["case_id"])
    base["icpc_id"] = icpc["id"]
    placement = get_success_data(api_client.create_placement(
        create_placement_payload(base["case_id"], base["family_id"]), SUP))
    base["placement_id"] = placement["id"]
    return base


def setup_active_placement(child_state="NV", family_state="CA",
                           to_iso8601="2026-06-04T08:00:00.000Z"):
    """Interstate case advanced to an ACTIVE placement. Returns the same dict as
    setup_pending_placement (placement now ACTIVE)."""
    base = setup_pending_placement(child_state=child_state, family_state=family_state,
                                   to_iso8601=to_iso8601)
    api_client.activate_placement(base["placement_id"], SUP)
    return base


def setup_active_placement_in_state(to_iso8601="2026-06-04T08:00:00.000Z"):
    """In-state case advanced to an ACTIVE placement (no ICPC; required_visits=3).

    Returns dict: agency_id, case_id, family_id, hs_id, bp_id, match_id, consent_id,
    placement_id.
    """
    base = setup_case_with_accepted_match(child_state="CA", family_state="CA",
                                          to_iso8601=to_iso8601, birth_state="CA")
    cv = current_case_version(base["case_id"])
    consent = create_irrevocable_consent(base["agency_id"], base["case_id"], base["bp_id"], cv)
    base["consent_id"] = consent["id"]
    placement = get_success_data(api_client.create_placement(
        create_placement_payload(base["case_id"], base["family_id"]), SUP))
    base["placement_id"] = placement["id"]
    api_client.activate_placement(base["placement_id"], SUP)
    return base


# ─── Escrow / expense helpers ────────────────────────────────────────────
def create_case_with_deposit(deposit_cents=1_000_000, child_state="CA", family_state="CA"):
    """Create an agency + case + one DEPOSIT escrow transaction.

    Returns dict: agency_id, case_id, deposit_id.
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state=child_state, family_state=family_state)
    cv = case["version"]
    dep = get_success_data(api_client.create_escrow_transaction(
        create_escrow_payload(case["id"], cv, txn_type="DEPOSIT", amount_cents=deposit_cents), FO))
    return {"agency_id": agency["id"], "case_id": case["id"], "deposit_id": dep["id"]}


def create_approved_expense(case_id, amount_cents=300_000, category="MEDICAL",
                            logger_id="cw-1", approver_id="fo-1"):
    """Log an expense (logger) and approve it (approver != logger). Returns the expense entity."""
    from .test_users import make_caseworker_headers, make_finance_officer_headers
    cw = make_caseworker_headers(logger_id)
    fo = make_finance_officer_headers(approver_id)
    exp = get_success_data(api_client.create_expense(
        create_expense_payload(case_id, amount_cents=amount_cents, category=category), cw))
    res = api_client.approve_expense(exp["id"], fo)
    return get_success_data(res)


def create_logged_expense(case_id, amount_cents=300_000, category="MEDICAL", logger_id="cw-1"):
    """Log an expense (LOGGED, not approved). Returns the expense entity."""
    from .test_users import make_caseworker_headers
    cw = make_caseworker_headers(logger_id)
    res = api_client.create_expense(
        create_expense_payload(case_id, amount_cents=amount_cents, category=category), cw)
    return get_success_data(res)


# ─── Invoice helper ──────────────────────────────────────────────────────
def create_case_with_family_and_invoice(fee_schedule_cents=3_000_000,
                                        annual_income_cents=8_000_000,
                                        child_state="CA", family_state="CA"):
    """Agency + case + family + ISSUED invoice. Returns dict: agency_id, case_id,
    family_id, invoice_id."""
    agency = create_agency(fee_schedule_cents=fee_schedule_cents)
    case = create_case(agency["id"], child_state=child_state, family_state=family_state)
    family = create_family(case["id"], annual_income_cents=annual_income_cents)
    inv = get_success_data(api_client.create_invoice(create_invoice_payload(case["id"]), FO))
    return {"agency_id": agency["id"], "case_id": case["id"],
            "family_id": family["id"], "invoice_id": inv["id"]}


# ─── Visit scheduling / completion helper ────────────────────────────────
def schedule_visit(case_id, placement_id, window_start, window_end):
    """Schedule a post-placement visit. Returns the visit entity."""
    res = api_client.create_visit(
        create_visit_payload(case_id, placement_id, window_start, window_end), CW)
    return get_success_data(res)


def complete_visit_at(agency_id, visit_id, clock_iso):
    """Advance clock to clock_iso then complete the visit. Returns the visit entity."""
    set_clock(agency_id, clock_iso)
    res = api_client.complete_visit(visit_id, CW)
    return get_success_data(res)


def setup_finalizable_in_state_placement(to_iso8601="2026-06-04T08:00:00.000Z"):
    """In-state case with ACTIVE placement (required_visits=3), 3 COMPLETED visits, and an
    ISSUED invoice — ready for finalize.

    Returns dict from setup_active_placement_in_state plus v1/v2/v3 and invoice_id.
    """
    base = setup_active_placement_in_state(to_iso8601=to_iso8601)
    v1 = schedule_visit(base["case_id"], base["placement_id"],
                        "2026-06-05T09:00:00.000Z", "2026-06-05T17:00:00.000Z")
    v2 = schedule_visit(base["case_id"], base["placement_id"],
                        "2026-06-06T09:00:00.000Z", "2026-06-06T17:00:00.000Z")
    v3 = schedule_visit(base["case_id"], base["placement_id"],
                        "2026-06-07T09:00:00.000Z", "2026-06-07T17:00:00.000Z")
    complete_visit_at(base["agency_id"], v1["id"], "2026-06-05T10:00:00.000Z")
    complete_visit_at(base["agency_id"], v2["id"], "2026-06-06T10:00:00.000Z")
    complete_visit_at(base["agency_id"], v3["id"], "2026-06-07T10:00:00.000Z")
    inv = get_success_data(api_client.create_invoice(create_invoice_payload(base["case_id"]), FO))
    base["v1"], base["v2"], base["v3"] = v1["id"], v2["id"], v3["id"]
    base["invoice_id"] = inv["id"]
    return base

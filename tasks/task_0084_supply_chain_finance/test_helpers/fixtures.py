"""Composite setup helpers for multi-step test prerequisites.

All fixtures use ``get_success_data()`` from the framework — the lenient
validator — so setup failures surface as a clear "Setup failed" message
instead of misleading assertion errors inside the test body.

PRD §2.1 identity discipline (mandatory):

  * ``CoreEnterpriseUser`` and ``SupplierUser`` are ENTITY-BACKED. Every
    ownership-gated call inside a fixture builds its headers via
    ``make_core_enterprise_headers(core_enterprise['id'])`` or
    ``make_supplier_headers(supplier['id'])`` — never the shared
    ``TEST_USERS`` fallback. Failing to thread the actual entity id
    through means EVERY ownership check rejects the request and
    cascades "Setup failed" across the suite.

  * The seven opaque roles use the shared constants from ``TEST_USERS``
    (or per-instance opaque builders for tests that need to distinguish
    specific opaque actors, e.g., segregation-of-duties scenarios).

Fixture tiers:
  * Tier 1 — single-entity state progression
  * Tier 2 — entity-hierarchy assembly (CE + Supplier + Confirmation + Receivable)
  * Tier 3 — full-lifecycle shortcuts (drive to UNDER_REVIEW, APPROVED, DISBURSED)
  * Tier 4 — accumulation / threshold targeting (credit-line headroom,
    revision_round walk, prepayment_count walk)
  * Tier 5 — terminal / finalization paths (SETTLED, REVOKED, WRITTEN_OFF)
"""
from __future__ import annotations
import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    PLATFORM_FEE_BPS,
    SECONDS_PER_DAY,
    TEST_DEFAULTS,
)
from .factories import (
    approve_core_enterprise_payload,
    approve_financing_application_payload,
    central_registry_file_payload,
    clock_advance_payload,
    create_core_enterprise_payload,
    create_disbursement_payload,
    create_financing_application_payload,
    create_payable_confirmation_payload,
    create_receivable_payload,
    create_supplier_payload,
    create_verification_payload,
    kyc_supplier_payload,
    repay_repayment_schedule_payload,
    return_financing_application_payload,
    revoke_payable_confirmation_payload,
    suspend_core_enterprise_payload,
)
from .test_users import (
    TEST_USERS,
    make_core_enterprise_headers,
    make_supplier_headers,
)


PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CREDIT_OFFICER = TEST_USERS["credit_officer_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]
RISK_REVIEWER = TEST_USERS["risk_reviewer_headers"]
RISK_REVIEWER_ALT = TEST_USERS["risk_reviewer_headers_alt"]
CREDIT_APPROVER = TEST_USERS["credit_approver_headers"]
CREDIT_APPROVER_ALT = TEST_USERS["credit_approver_headers_alt"]
FUNDER = TEST_USERS["funder_headers"]
COLLECTION_MANAGER = TEST_USERS["collection_manager_headers"]


# ===========================================================================
# Clock helpers
# PRD §3.10: "the clock-advance capability advances the logical clock
# to a supplied `to` instant and triggers any time-gated transitions
# including the overdue sweep."
# ===========================================================================
def _parse_iso(ts: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _format_iso(t: _dt.datetime) -> str:
    """PRD §2.4: ISO 8601 UTC with three fractional digits."""
    t_utc = t.astimezone(_dt.timezone.utc)
    return t_utc.strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{t_utc.microsecond // 1000:03d}Z"
    )


# Test-side mirror of the server clock. PRD §3.10's clock-advance
# capability advances the logical clock on the server, but the PRD
# does not expose a "read current clock" endpoint. So we mirror the
# server clock here: any test-driven advance also updates this anchor,
# and all date math is anchored to it. If the test has never advanced
# the clock, we fall back to the test-runner's wall-clock now, which
# coincides with the server's initial value at startup.
_SERVER_CLOCK_ANCHOR: Optional[_dt.datetime] = None


def _server_now() -> _dt.datetime:
    if _SERVER_CLOCK_ANCHOR is not None:
        return _SERVER_CLOCK_ANCHOR
    return _dt.datetime.now(_dt.timezone.utc)


def iso_in_days(days_from_now: int,
                anchor: Optional[_dt.datetime] = None) -> str:
    """Return an ISO 8601 timestamp ``days_from_now`` days from the
    given anchor (default: the server clock as last set by
    ``advance_clock_to`` / ``advance_clock_by_days``, or test-runner
    wall-clock now if the clock has not been advanced)."""
    base = anchor or _server_now()
    return _format_iso(base + _dt.timedelta(days=days_from_now))


def advance_clock_to(to_iso: str) -> None:
    """PRD §3.10: 'the clock-advance capability advances the logical
    clock to a supplied to instant.' Also updates the test-side
    mirror so subsequent ``iso_in_days`` calls anchor to the new
    server time."""
    global _SERVER_CLOCK_ANCHOR
    res = api_client.advance_clock(
        clock_advance_payload(to_iso=to_iso), PLATFORM_ADMIN,
    )
    get_success_data(res)
    _SERVER_CLOCK_ANCHOR = _parse_iso(to_iso)


def advance_clock_by_days(base_iso: str, days: int) -> str:
    """Advance the server clock to ``base_iso + days``; return the new
    ISO timestamp."""
    new_ts = _parse_iso(base_iso) + _dt.timedelta(days=days)
    new_iso = _format_iso(new_ts)
    advance_clock_to(new_iso)
    return new_iso


def run_sweep() -> None:
    """PRD §3.10: 'the run-sweep capability runs the overdue/aging
    sweep immediately at the current clock and is idempotent within
    that clock instant.'"""
    res = api_client.run_sweep(PLATFORM_ADMIN)
    get_success_data(res)


# ===========================================================================
# Tier 1 — Single-entity state progression
# ===========================================================================

def register_core_enterprise(*, risk_rating: str = "AAA",
                             joint_liability_flag: bool = True,
                             **overrides: Any) -> Dict[str, Any]:
    """Onboard a CoreEnterprise (status PENDING)."""
    payload = create_core_enterprise_payload(
        risk_rating=risk_rating,
        joint_liability_flag=joint_liability_flag,
        **overrides,
    )
    res = api_client.create_core_enterprise(payload, CREDIT_OFFICER)
    return get_success_data(res)


def approve_core_enterprise(ce: Dict[str, Any],
                            credit_line_total_cents: int = TEST_DEFAULTS["CE_CREDIT_LINE"],
                            ) -> Dict[str, Any]:
    """PRD §3.1: PENDING → APPROVED with credit_line_total_cents."""
    res = api_client.approve_core_enterprise(
        ce["id"],
        approve_core_enterprise_payload(
            credit_line_total_cents=credit_line_total_cents,
        ),
        CREDIT_OFFICER,
    )
    return get_success_data(res)


def setup_approved_core_enterprise(*, risk_rating: str = "AAA",
                                   joint_liability_flag: bool = True,
                                   credit_line_total_cents: int = TEST_DEFAULTS["CE_CREDIT_LINE"],
                                   ) -> Dict[str, Any]:
    """Create + approve a CoreEnterprise; return the APPROVED row."""
    ce = register_core_enterprise(
        risk_rating=risk_rating,
        joint_liability_flag=joint_liability_flag,
    )
    return approve_core_enterprise(
        ce, credit_line_total_cents=credit_line_total_cents,
    )


def suspend_core_enterprise(ce: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.1: APPROVED → SUSPENDED."""
    res = api_client.suspend_core_enterprise(
        ce["id"],
        suspend_core_enterprise_payload(),
        COMPLIANCE_OFFICER,
    )
    return get_success_data(res)


def register_supplier(*, tier_to_core: int = 1,
                      parent_supplier_id: Optional[str] = None,
                      **overrides: Any) -> Dict[str, Any]:
    """Onboard a Supplier in ACTIVE / NOT_RUN."""
    payload = create_supplier_payload(
        tier_to_core=tier_to_core,
        parent_supplier_id=parent_supplier_id,
        **overrides,
    )
    res = api_client.create_supplier(payload, PLATFORM_ADMIN)
    return get_success_data(res)


def kyc_pass_supplier(supplier: Dict[str, Any],
                      *, aml_risk_score: float = 0.10) -> Dict[str, Any]:
    """PRD §3.2: record KYC PASSED with the given aml_risk_score."""
    res = api_client.kyc_supplier(
        supplier["id"],
        kyc_supplier_payload(
            kyc_status="PASSED", aml_risk_score=aml_risk_score,
        ),
        COMPLIANCE_OFFICER,
    )
    return get_success_data(res)


def setup_active_supplier(*, tier_to_core: int = 1,
                          parent_supplier_id: Optional[str] = None,
                          aml_risk_score: float = 0.10,
                          ) -> Dict[str, Any]:
    """Onboard a supplier and run KYC PASS. Returns the post-KYC row
    with kyc_status=PASSED and kyc_completed_at populated."""
    s = register_supplier(
        tier_to_core=tier_to_core, parent_supplier_id=parent_supplier_id,
    )
    return kyc_pass_supplier(s, aml_risk_score=aml_risk_score)


# ===========================================================================
# Tier 2 — Entity-hierarchy assembly
# ===========================================================================

def create_payable_confirmation(ce: Dict[str, Any],
                                supplier: Dict[str, Any],
                                *, amount_cents: int = TEST_DEFAULTS["PC_AMOUNT_CENTS"],
                                due_date: Optional[str] = None,
                                **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: upload one PayableConfirmation row (DRAFT →
    PENDING_CONFIRM via the upload endpoint). The acting CoreEnterprise
    is identity-threaded — its id becomes X-User-ID."""
    due = due_date if due_date is not None else iso_in_days(90)
    payload = create_payable_confirmation_payload(
        core_enterprise_id=ce["id"], supplier_id=supplier["id"],
        amount_cents=amount_cents, due_date=due, **overrides,
    )
    res = api_client.create_payable_confirmation(
        payload, make_core_enterprise_headers(ce["id"]),
    )
    return get_success_data(res)


def confirm_payable_confirmation(ce: Dict[str, Any],
                                 confirmation: Dict[str, Any],
                                 ) -> Dict[str, Any]:
    """PRD §3.3: PENDING_CONFIRM → CONFIRMED via /confirm."""
    res = api_client.confirm_payable_confirmation(
        confirmation["id"], make_core_enterprise_headers(ce["id"]),
    )
    return get_success_data(res)


def setup_confirmed_payable_confirmation(*,
                                         ce: Optional[Dict[str, Any]] = None,
                                         supplier: Optional[Dict[str, Any]] = None,
                                         amount_cents: int = TEST_DEFAULTS["PC_AMOUNT_CENTS"],
                                         due_date: Optional[str] = None,
                                         credit_line_total_cents: int = TEST_DEFAULTS["CE_CREDIT_LINE"],
                                         core_risk_rating: str = "AAA",
                                         joint_liability_flag: bool = True,
                                         ) -> Dict[str, Any]:
    """Build a fresh CE + supplier + CONFIRMED PayableConfirmation.

    Returns ``{"ce", "supplier", "confirmation"}`` — the freshly fetched
    confirmation in CONFIRMED state plus its hosting entities.

    PRD §3.3: confirmation requires available headroom at least equal
    to ``amount_cents``. When the test caller passes a large
    ``amount_cents`` (e.g., to flip CENTRAL_REGISTRY_REQUIRED or
    ON_SITE_REQUIRED — thresholds PRD names but does not pin), the
    fixture auto-scales ``credit_line_total_cents`` so the
    confirmation step actually succeeds. The auto-scale only kicks
    in when the caller has not explicitly overridden
    ``credit_line_total_cents``.
    """
    # Auto-scale the credit line when the caller did not override it
    # and the requested amount would exhaust the default headroom.
    if (
        credit_line_total_cents == TEST_DEFAULTS["CE_CREDIT_LINE"]
        and amount_cents > credit_line_total_cents
    ):
        # Headroom must be ≥ amount; give a 10x cushion so subsequent
        # in-fixture moves (e.g., approvals) keep working.
        credit_line_total_cents = max(
            amount_cents * 10,
            TEST_DEFAULTS["CE_CREDIT_LINE"],
        )
    if ce is None:
        ce = setup_approved_core_enterprise(
            risk_rating=core_risk_rating,
            joint_liability_flag=joint_liability_flag,
            credit_line_total_cents=credit_line_total_cents,
        )
    if supplier is None:
        supplier = setup_active_supplier(tier_to_core=1, aml_risk_score=0.10)
    confirmation = create_payable_confirmation(
        ce, supplier, amount_cents=amount_cents, due_date=due_date,
    )
    confirmation = confirm_payable_confirmation(ce, confirmation)
    return {"ce": ce, "supplier": supplier, "confirmation": confirmation}


def register_receivable(supplier: Dict[str, Any],
                        confirmation: Dict[str, Any],
                        **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: register a Receivable against a CONFIRMED confirmation
    (acting supplier is identity-threaded)."""
    payload = create_receivable_payload(
        confirmation_id=confirmation["id"], **overrides,
    )
    res = api_client.create_receivable(
        payload, make_supplier_headers(supplier["id"]),
    )
    return get_success_data(res)


def setup_registered_receivable(*,
                                amount_cents: int = TEST_DEFAULTS["PC_AMOUNT_CENTS"],
                                due_date: Optional[str] = None,
                                supplier_aml: float = 0.10,
                                core_risk_rating: str = "AAA",
                                ) -> Dict[str, Any]:
    """Full chain: approved CE + active supplier + CONFIRMED
    confirmation + REGISTERED receivable."""
    bundle = setup_confirmed_payable_confirmation(
        amount_cents=amount_cents, due_date=due_date,
        core_risk_rating=core_risk_rating,
    )
    # Re-run KYC at requested score if different than default.
    if supplier_aml != 0.10:
        bundle["supplier"] = kyc_pass_supplier(
            bundle["supplier"], aml_risk_score=supplier_aml,
        )
    receivable = register_receivable(bundle["supplier"], bundle["confirmation"])
    bundle["receivable"] = receivable
    return bundle


# ===========================================================================
# Verification helpers (PRD §3.9)
# ===========================================================================

def open_and_pass_verification(receivable: Dict[str, Any],
                               *, third_party_score: float = 0.90,
                               waybill_doc_id: Optional[str] = None,
                               include_customs: bool = False,
                               on_site_required_expected: Optional[bool] = None,
                               reviewer_headers: Dict[str, str] = RISK_REVIEWER,
                               ) -> Dict[str, Any]:
    """PRD §3.9: open verification, mark on-site complete if required,
    finalize PASS. Returns the finalized verification record."""
    payload_kwargs: Dict[str, Any] = {
        "third_party_score": third_party_score,
    }
    if waybill_doc_id is not None:
        payload_kwargs["waybill_doc_id"] = waybill_doc_id
    else:
        payload_kwargs["waybill_doc_id"] = TEST_DEFAULTS["WAYBILL_DOC_ID"]
    if include_customs:
        payload_kwargs["customs_declaration_doc_id"] = TEST_DEFAULTS["CUSTOMS_DOC_ID"]
    res = api_client.create_verification(
        create_verification_payload(
            receivable_id=receivable["id"], **payload_kwargs,
        ),
        reviewer_headers,
    )
    verification = get_success_data(res)
    if verification.get("on_site_required"):
        on_site_res = api_client.verification_on_site(
            verification["id"], reviewer_headers,
        )
        verification = get_success_data(on_site_res)
    fin_res = api_client.finalize_verification(
        verification["id"], reviewer_headers,
    )
    return get_success_data(fin_res)


# ===========================================================================
# Tier 3 — Full-lifecycle shortcuts for FinancingApplication
# ===========================================================================

def setup_draft_financing_application(*,
                                      mode: str = "FACTORING",
                                      requested_amount_cents: int = TEST_DEFAULTS["REQUESTED_AMOUNT_CENTS"],
                                      term_days: int = TEST_DEFAULTS["TERM_DAYS"],
                                      amount_cents: int = TEST_DEFAULTS["PC_AMOUNT_CENTS"],
                                      supplier_aml: float = 0.10,
                                      core_risk_rating: str = "AAA",
                                      due_date: Optional[str] = None,
                                      ) -> Dict[str, Any]:
    """Build full chain through DRAFT FinancingApplication. Sets
    ``due_date`` so that term_days matches the receivable due window."""
    if due_date is None:
        due_date = iso_in_days(term_days)
    bundle = setup_registered_receivable(
        amount_cents=amount_cents, due_date=due_date,
        supplier_aml=supplier_aml, core_risk_rating=core_risk_rating,
    )
    payload = create_financing_application_payload(
        receivable_id=bundle["receivable"]["id"], mode=mode,
        requested_amount_cents=requested_amount_cents, term_days=term_days,
    )
    res = api_client.create_financing_application(
        payload, make_supplier_headers(bundle["supplier"]["id"]),
    )
    bundle["application"] = get_success_data(res)
    return bundle


def submit_financing_application(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.5: DRAFT → SUBMITTED via /submit."""
    res = api_client.submit_financing_application(
        bundle["application"]["id"],
        make_supplier_headers(bundle["supplier"]["id"]),
    )
    bundle["application"] = get_success_data(res)
    return bundle


def setup_submitted_application(**kwargs: Any) -> Dict[str, Any]:
    """Build through SUBMITTED (DRAFT → SUBMITTED). Returns bundle with
    application in SUBMITTED."""
    bundle = setup_draft_financing_application(**kwargs)
    return submit_financing_application(bundle)


def start_review(bundle: Dict[str, Any],
                 *, reviewer_headers: Dict[str, str] = RISK_REVIEWER,
                 ) -> Dict[str, Any]:
    """PRD §3.5: SUBMITTED → UNDER_REVIEW.

    Requires a finalized PASS verification (PRD §3.5). If the bundle
    does not already carry one, this helper builds and finalizes a
    standard PASS verification on the receivable first.
    """
    if "verification" not in bundle:
        bundle["verification"] = open_and_pass_verification(
            bundle["receivable"], reviewer_headers=reviewer_headers,
        )
    res = api_client.start_review_financing_application(
        bundle["application"]["id"], reviewer_headers,
    )
    bundle["application"] = get_success_data(res)
    return bundle


def setup_under_review_application(*,
                                   reviewer_headers: Dict[str, str] = RISK_REVIEWER,
                                   **kwargs: Any) -> Dict[str, Any]:
    """Build through UNDER_REVIEW (SUBMITTED → UNDER_REVIEW)."""
    bundle = setup_submitted_application(**kwargs)
    return start_review(bundle, reviewer_headers=reviewer_headers)


def approve_application(bundle: Dict[str, Any],
                        *, approved_amount_cents: Optional[int] = None,
                        approver_headers: Dict[str, str] = CREDIT_APPROVER,
                        ) -> Dict[str, Any]:
    """PRD §3.5: UNDER_REVIEW → APPROVED. approver_headers MUST differ
    from the reviewer (segregation of duties)."""
    app = bundle["application"]
    if approved_amount_cents is None:
        approved_amount_cents = app["requested_amount_cents"]
    res = api_client.approve_financing_application(
        app["id"],
        approve_financing_application_payload(
            approved_amount_cents=approved_amount_cents,
        ),
        approver_headers,
    )
    bundle["application"] = get_success_data(res)
    return bundle


def setup_approved_application(*,
                               reviewer_headers: Dict[str, str] = RISK_REVIEWER,
                               approver_headers: Dict[str, str] = CREDIT_APPROVER,
                               approved_amount_cents: Optional[int] = None,
                               **kwargs: Any) -> Dict[str, Any]:
    """Build through APPROVED (UNDER_REVIEW → APPROVED)."""
    bundle = setup_under_review_application(
        reviewer_headers=reviewer_headers, **kwargs,
    )
    return approve_application(
        bundle,
        approved_amount_cents=approved_amount_cents,
        approver_headers=approver_headers,
    )


def disburse_application(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.6: APPROVED → DISBURSED via Funder. Returns the bundle
    with ``disbursement`` and ``schedule`` populated and ``application``
    refetched."""
    res = api_client.create_disbursement(
        create_disbursement_payload(
            application_id=bundle["application"]["id"],
        ),
        FUNDER,
    )
    bundle["disbursement"] = get_success_data(res)
    # PRD §3.6: a RepaymentSchedule is created; fetch via list-by-app.
    apps_res = api_client.get_financing_application(
        bundle["application"]["id"], FUNDER,
    )
    bundle["application"] = get_success_data(apps_res)
    return bundle


def setup_disbursed_application(*,
                                approved_amount_cents: Optional[int] = None,
                                **kwargs: Any) -> Dict[str, Any]:
    """Build all the way through DISBURSED. The returned bundle carries
    ``ce``, ``supplier``, ``confirmation``, ``receivable``,
    ``verification``, ``application``, ``disbursement``, and an
    additional ``schedule`` fetched from the RepaymentSchedule endpoint
    when discoverable from the bundle.

    PRD §3.6 mints a RepaymentSchedule at disbursement; the test layer
    fetches it via the application context.
    """
    bundle = setup_approved_application(
        approved_amount_cents=approved_amount_cents, **kwargs,
    )
    bundle = disburse_application(bundle)
    # Best-effort schedule pull: the disbursement does not carry the
    # schedule id directly, but the application or receivable may. We
    # leave the lookup to the caller; for tests that need the schedule
    # synchronously, build it via setup_scheduled_repayment().
    return bundle


def fetch_repayment_schedule(schedule_id: str) -> Dict[str, Any]:
    """Look up a RepaymentSchedule by id (read with PlatformAdmin so
    role-RBAC narrowing doesn't bite test plumbing)."""
    res = api_client.get_repayment_schedule(schedule_id, PLATFORM_ADMIN)
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Schedule-from-disbursed convenience: try the most common surface
# (application body includes schedule_id) and fall back to fetching by
# listing audit-log entries for the DISBURSE action and walking from
# there. The schedule_id surface is PRD-silent on its routing in the
# response shape, so we expose helper that the test layer can call only
# after asserting the application is DISBURSED.
# ---------------------------------------------------------------------------
def setup_scheduled_repayment(*,
                              approved_amount_cents: int = TEST_DEFAULTS["REQUESTED_AMOUNT_CENTS"],
                              amount_cents: int = TEST_DEFAULTS["PC_AMOUNT_CENTS"],
                              term_days: int = TEST_DEFAULTS["TERM_DAYS"],
                              mode: str = "FACTORING",
                              core_risk_rating: str = "AAA",
                              supplier_aml: float = 0.10,
                              due_date: Optional[str] = None,
                              ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive the system to a DISBURSED application and return
    ``(bundle, schedule)`` where the schedule is freshly fetched and in
    SCHEDULED state. The schedule id is discovered by listing all
    repayment-schedule resources for the bundle's supplier via the
    audit-log entry minted at DISBURSE.
    """
    bundle = setup_disbursed_application(
        approved_amount_cents=approved_amount_cents,
        amount_cents=amount_cents,
        term_days=term_days,
        mode=mode,
        core_risk_rating=core_risk_rating,
        supplier_aml=supplier_aml,
        due_date=due_date,
    )
    schedule = _resolve_schedule_for_application(bundle["application"]["id"])
    return bundle, schedule


def _resolve_schedule_for_application(application_id: str) -> Dict[str, Any]:
    """Resolve the RepaymentSchedule for a DISBURSED application.

    PRD §3.6 promises a schedule is created at disbursement but does
    not promise a specific surface (no list endpoint exists per PRD
    §4). We try, in order of preference:

      1. The application body — perhaps the implementation surfaces a
         ``schedule_id`` or ``repayment_schedule_id`` field there.
      2. The disbursement body — the same.
      3. The audit log for an entity_type=RepaymentSchedule entry — if
         the implementation appends one (PRD §3.10 lists
         RepaymentSchedule in the entity_type enum so this surface is
         plausible).

    All three are PRD-permissible discovery paths. If none yields a
    match we raise a clear "Setup failed" error.
    """
    # Path 1: the application body.
    try:
        app = get_financing_application(application_id)
        for key in ("schedule_id", "repayment_schedule_id"):
            sid = app.get(key)
            if isinstance(sid, str) and sid:
                try:
                    sched = fetch_repayment_schedule(sid)
                except Exception:
                    sched = None
                if sched and sched.get("application_id") == application_id:
                    return sched
    except Exception:
        pass

    # Path 3: audit log scan.
    candidate_ids: List[str] = []
    try:
        audits_res = api_client.list_audit_logs(
            PLATFORM_ADMIN,
            params={"entity_type": "RepaymentSchedule", "limit": 100},
        )
        audits_data = get_success_data(audits_res)
        if isinstance(audits_data, list):
            rows = audits_data
        elif isinstance(audits_data, dict):
            rows = audits_data.get("items", []) or []
        else:
            rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("entity_type") == "RepaymentSchedule":
                eid = row.get("entity_id")
                if isinstance(eid, str):
                    candidate_ids.append(eid)
    except Exception:
        pass

    seen: set = set()
    for sid in reversed(candidate_ids):
        if sid in seen:
            continue
        seen.add(sid)
        try:
            sched = fetch_repayment_schedule(sid)
        except Exception:
            continue
        if sched.get("application_id") == application_id:
            return sched
    raise AssertionError(
        f"Setup failed: could not resolve RepaymentSchedule for "
        f"application_id={application_id!r}. Looked in the application "
        f"body and in audit-log entries for entity_type=RepaymentSchedule."
    )


# ===========================================================================
# Tier 2 — Multi-tier supplier chains
# ===========================================================================

def setup_tier2_chain(*,
                      core_risk_rating: str = "AAA",
                      credit_line_total_cents: int = TEST_DEFAULTS["CE_CREDIT_LINE"],
                      ) -> Dict[str, Any]:
    """Build a CE + tier-1 supplier + tier-2 supplier chain.

    Returns:
        {"ce", "supplier_t1", "supplier_t2", "confirmation_t1"}

    The tier-1 confirmation is left in CONFIRMED so the tier-2 upload
    can succeed per PRD §3.3 "upstream parent confirmation chain ...
    in CONFIRMED or SETTLED".
    """
    ce = setup_approved_core_enterprise(
        risk_rating=core_risk_rating,
        credit_line_total_cents=credit_line_total_cents,
    )
    s_t1 = setup_active_supplier(tier_to_core=1)
    s_t2_raw = register_supplier(
        tier_to_core=2, parent_supplier_id=s_t1["id"],
    )
    s_t2 = kyc_pass_supplier(s_t2_raw, aml_risk_score=0.10)
    # Need a CONFIRMED tier-1 confirmation as the parent.
    pc_t1 = create_payable_confirmation(
        ce, s_t1, amount_cents=TEST_DEFAULTS["PC_AMOUNT_CENTS"],
    )
    pc_t1 = confirm_payable_confirmation(ce, pc_t1)
    return {
        "ce": ce, "supplier_t1": s_t1, "supplier_t2": s_t2,
        "confirmation_t1": pc_t1,
    }


def setup_tier_n_supplier(tier_to_core: int,
                          ce: Dict[str, Any],
                          *,
                          aml_risk_score: float = 0.05,
                          ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Build a chain of suppliers up to the requested tier, with each
    intermediate supplier holding a CONFIRMED parent confirmation. Used
    by tier-penalty and tier-depth tests.

    Returns ``(target_supplier, parents_chain)`` where ``parents_chain``
    is the list of intermediate suppliers tier-1 → tier-(n-1).
    """
    parents: List[Dict[str, Any]] = []
    last_supplier: Optional[Dict[str, Any]] = None
    for t in range(1, tier_to_core + 1):
        parent_id = parents[-1]["id"] if parents else None
        raw = register_supplier(
            tier_to_core=t,
            parent_supplier_id=parent_id if t >= 2 else None,
        )
        s = kyc_pass_supplier(raw, aml_risk_score=aml_risk_score)
        if t < tier_to_core:
            # Mint a CONFIRMED upstream confirmation so the next-level
            # supplier's confirmation can reference it.
            pc = create_payable_confirmation(
                ce, s,
                amount_cents=TEST_DEFAULTS["PC_AMOUNT_CENTS"],
            )
            confirm_payable_confirmation(ce, pc)
            parents.append(s)
        else:
            last_supplier = s
    assert last_supplier is not None
    return last_supplier, parents


# ===========================================================================
# Tier 4 — Accumulation / threshold targeting
# ===========================================================================

def walk_revision_rounds_until_capped(bundle: Dict[str, Any],
                                      *,
                                      reviewer_headers: Dict[str, str] = RISK_REVIEWER,
                                      max_rounds: int = 10,
                                      ) -> Tuple[Dict[str, Any], int]:
    """PRD §3.5: "Each return-and-resubmit pair therefore burns one
    revision slot." Loop return → submit → start-review until the
    return endpoint refuses with ERR_MAX_REVISIONS_EXCEEDED (PRD §3.5).
    The acting Supplier and RiskReviewer are identity-threaded.

    Returns ``(bundle_at_cap, last_successful_revision_round)``. The
    bundle's application is left in UNDER_REVIEW with revision_round at
    the cap, ready for the test to issue a final ``return`` and assert
    the rejection.
    """
    rounds = 0
    supplier_headers = make_supplier_headers(bundle["supplier"]["id"])
    for _ in range(max_rounds):
        res_return = api_client.return_financing_application(
            bundle["application"]["id"],
            return_financing_application_payload(),
            reviewer_headers,
        )
        # If the server rejects this return, we have hit the cap.
        try:
            ret = get_success_data(res_return)
        except Exception:
            break
        bundle["application"] = ret
        # Now resubmit and restart review for the next iteration.
        submit_res = api_client.submit_financing_application(
            bundle["application"]["id"], supplier_headers,
        )
        bundle["application"] = get_success_data(submit_res)
        sr_res = api_client.start_review_financing_application(
            bundle["application"]["id"], reviewer_headers,
        )
        bundle["application"] = get_success_data(sr_res)
        rounds += 1
    return bundle, rounds


def setup_application_at_revision_round(round_index: int,
                                        *,
                                        reviewer_headers: Dict[str, str] = RISK_REVIEWER,
                                        **kwargs: Any) -> Dict[str, Any]:
    """Build an application in UNDER_REVIEW whose revision_round equals
    ``round_index``. Used by MAX_REVISION_ROUNDS boundary tests.
    """
    bundle = setup_under_review_application(
        reviewer_headers=reviewer_headers, **kwargs,
    )
    supplier_headers = make_supplier_headers(bundle["supplier"]["id"])
    for _ in range(round_index):
        ret_res = api_client.return_financing_application(
            bundle["application"]["id"],
            return_financing_application_payload(),
            reviewer_headers,
        )
        bundle["application"] = get_success_data(ret_res)
        sub_res = api_client.submit_financing_application(
            bundle["application"]["id"], supplier_headers,
        )
        bundle["application"] = get_success_data(sub_res)
        sr_res = api_client.start_review_financing_application(
            bundle["application"]["id"], reviewer_headers,
        )
        bundle["application"] = get_success_data(sr_res)
    return bundle


# ===========================================================================
# Tier 5 — Terminal / finalization paths
# ===========================================================================

def revoke_confirmation(ce: Dict[str, Any],
                        confirmation: Dict[str, Any],
                        *, reason: str = "trade-dispute",
                        ) -> Dict[str, Any]:
    """PRD §3.3: CONFIRMED → REVOKED via /revoke. The acting
    CoreEnterprise id is identity-threaded."""
    res = api_client.revoke_payable_confirmation(
        confirmation["id"],
        revoke_payable_confirmation_payload(revoke_reason=reason),
        make_core_enterprise_headers(ce["id"]),
    )
    return get_success_data(res)


def file_central_registry(receivable: Dict[str, Any],
                          filing_no: Optional[str] = None,
                          ) -> Dict[str, Any]:
    """PRD §3.4: PlatformAdmin records the registry filing number."""
    res = api_client.central_registry_file(
        receivable["id"],
        central_registry_file_payload(filing_no=filing_no),
        PLATFORM_ADMIN,
    )
    return get_success_data(res)


def repay_in_full(schedule: Dict[str, Any],
                  *, repay_amount_cents: Optional[int] = None,
                  early_settle: bool = False,
                  actor_headers: Optional[Dict[str, str]] = None,
                  ce: Optional[Dict[str, Any]] = None,
                  ) -> Dict[str, Any]:
    """PRD §3.7: full-balance repayment. By default the CoreEnterprise's
    own headers act as payer (on-due-date deduction). Pass
    ``actor_headers`` to use a SupplierUser instead.

    If ``repay_amount_cents`` is omitted the helper pays the exact
    outstanding (``total_due_cents - paid_cents``). Callers requesting
    an early-settle pass ``early_settle=True`` and an
    ``repay_amount_cents`` that already accounts for the expected rebate.
    """
    if actor_headers is None:
        if ce is None:
            raise ValueError(
                "repay_in_full needs either actor_headers or ce so that "
                "X-User-ID can be identity-threaded for the on-due-date "
                "deduction path."
            )
        actor_headers = make_core_enterprise_headers(ce["id"])
    if repay_amount_cents is None:
        repay_amount_cents = schedule["total_due_cents"] - schedule["paid_cents"]
    payload = repay_repayment_schedule_payload(
        repay_amount_cents=repay_amount_cents,
        early_settle=early_settle if early_settle else None,
    )
    res = api_client.repay_repayment_schedule(
        schedule["id"], payload, actor_headers,
    )
    return get_success_data(res)


def partial_repay(schedule: Dict[str, Any],
                  repay_amount_cents: int,
                  *,
                  actor_headers: Optional[Dict[str, str]] = None,
                  supplier: Optional[Dict[str, Any]] = None,
                  ) -> Dict[str, Any]:
    """PRD §3.7: partial prepayment with ``partial=true``. By default
    the acting supplier id is identity-threaded.
    """
    if actor_headers is None:
        if supplier is None:
            raise ValueError(
                "partial_repay needs either actor_headers or supplier so "
                "that X-User-ID can be identity-threaded for the "
                "supplier-side prepay path."
            )
        actor_headers = make_supplier_headers(supplier["id"])
    res = api_client.repay_repayment_schedule(
        schedule["id"],
        repay_repayment_schedule_payload(
            repay_amount_cents=repay_amount_cents, partial=True,
        ),
        actor_headers,
    )
    return get_success_data(res)


def drive_to_overdue(schedule: Dict[str, Any], *,
                     days_past_due: int = 5) -> Dict[str, Any]:
    """PRD §3.8: advance the clock past the schedule's
    ``scheduled_repayment_date`` and run the sweep. Returns the
    refreshed schedule (in OVERDUE) after sweep."""
    target_iso = advance_clock_by_days(
        schedule["scheduled_repayment_date"], days_past_due,
    )
    _ = target_iso  # noqa: F841 — advanced clock is implicit
    run_sweep()
    return fetch_repayment_schedule(schedule["id"])


def find_collection_case_for_schedule(schedule_id: str) -> Optional[Dict[str, Any]]:
    """Discover the open CollectionCase for a schedule.

    PRD §3.8: "at most one open case is permitted per schedule, so
    schedule_id is unique across non-terminal cases." PRD §3.10
    catalogues ``CollectionCase`` in the AuditLogEntry entity_type
    enum, so the case-open event is a plausible audit-log surface.

    We try the audit-log scan first; if no matching candidate is found
    we also inspect the repayment-schedule body in case the
    implementation surfaces ``collection_case_id`` directly.
    """
    candidate_ids: List[str] = []
    try:
        audits_res = api_client.list_audit_logs(
            PLATFORM_ADMIN,
            params={"entity_type": "CollectionCase", "limit": 100},
        )
        audits_data = get_success_data(audits_res)
        if isinstance(audits_data, list):
            rows = audits_data
        elif isinstance(audits_data, dict):
            rows = audits_data.get("items", []) or []
        else:
            rows = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if r.get("entity_type") == "CollectionCase":
                eid = r.get("entity_id")
                if isinstance(eid, str):
                    candidate_ids.append(eid)
    except Exception:
        pass
    seen: set = set()
    for cid in reversed(candidate_ids):
        if cid in seen:
            continue
        seen.add(cid)
        try:
            case = get_success_data(
                api_client.get_collection_case(cid, COLLECTION_MANAGER),
            )
        except Exception:
            continue
        if case.get("schedule_id") == schedule_id:
            return case

    # Fallback: try the schedule body for a collection_case_id surface.
    try:
        sched = fetch_repayment_schedule(schedule_id)
        for key in ("collection_case_id", "case_id"):
            cid = sched.get(key)
            if isinstance(cid, str) and cid:
                try:
                    case = get_success_data(
                        api_client.get_collection_case(cid, COLLECTION_MANAGER),
                    )
                except Exception:
                    continue
                if case.get("schedule_id") == schedule_id:
                    return case
    except Exception:
        pass
    return None


def list_audit_for_entity(entity_id: str,
                          *, entity_type: Optional[str] = None,
                          action: Optional[str] = None,
                          ) -> List[Dict[str, Any]]:
    """Fetch audit-log entries filtered to a specific entity id (PRD
    §3.10 supports ``entity_type``, ``entity_id``, ``action``
    filters)."""
    params: Dict[str, Any] = {"entity_id": entity_id, "limit": 100}
    if entity_type is not None:
        params["entity_type"] = entity_type
    if action is not None:
        params["action"] = action
    res = api_client.list_audit_logs(PLATFORM_ADMIN, params=params)
    data = get_success_data(res)
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        items = data.get("items", [])
        return [r for r in items if isinstance(r, dict)]
    return []


# ===========================================================================
# Helpers for credit-line invariant tests
# ===========================================================================

def get_core_enterprise(ce_id: str) -> Dict[str, Any]:
    """Refetch a CoreEnterprise (helper for assertions that compare
    pre- and post-action snapshots of credit_line counters)."""
    res = api_client.get_core_enterprise(ce_id, PLATFORM_ADMIN)
    return get_success_data(res)


def get_payable_confirmation(conf_id: str) -> Dict[str, Any]:
    res = api_client.get_payable_confirmation(conf_id, PLATFORM_ADMIN)
    return get_success_data(res)


def get_receivable(receivable_id: str) -> Dict[str, Any]:
    res = api_client.get_receivable(receivable_id, PLATFORM_ADMIN)
    return get_success_data(res)


def get_supplier(supplier_id: str) -> Dict[str, Any]:
    res = api_client.get_supplier(supplier_id, PLATFORM_ADMIN)
    return get_success_data(res)


def get_financing_application(app_id: str) -> Dict[str, Any]:
    res = api_client.get_financing_application(app_id, PLATFORM_ADMIN)
    return get_success_data(res)


__all__ = [
    # Clock
    "advance_clock_by_days",
    "advance_clock_to",
    "iso_in_days",
    "run_sweep",
    # Tier 1
    "approve_core_enterprise",
    "kyc_pass_supplier",
    "register_core_enterprise",
    "register_supplier",
    "setup_active_supplier",
    "setup_approved_core_enterprise",
    "suspend_core_enterprise",
    # Tier 2
    "confirm_payable_confirmation",
    "create_payable_confirmation",
    "open_and_pass_verification",
    "register_receivable",
    "setup_confirmed_payable_confirmation",
    "setup_registered_receivable",
    "setup_tier2_chain",
    "setup_tier_n_supplier",
    # Tier 3
    "approve_application",
    "disburse_application",
    "setup_approved_application",
    "setup_disbursed_application",
    "setup_draft_financing_application",
    "setup_scheduled_repayment",
    "setup_submitted_application",
    "setup_under_review_application",
    "start_review",
    "submit_financing_application",
    # Tier 4
    "setup_application_at_revision_round",
    "walk_revision_rounds_until_capped",
    # Tier 5
    "drive_to_overdue",
    "file_central_registry",
    "partial_repay",
    "repay_in_full",
    "revoke_confirmation",
    # Re-fetchers
    "fetch_repayment_schedule",
    "find_collection_case_for_schedule",
    "get_core_enterprise",
    "get_financing_application",
    "get_payable_confirmation",
    "get_receivable",
    "get_supplier",
    "list_audit_for_entity",
]

"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Provider calls are entity-backed (X-User-ID is the
Provider.id), so every provider-side call in these helpers is made with
make_provider_headers(provider_id). Opaque roles use make_*_headers with
explicit operator ids so segregation-of-duties walls can be exercised.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    assign_task_payload,
    create_claim_line_payload,
    create_claim_payload,
    create_dispute_payload,
    create_edit_rule_payload,
    create_edit_version_payload,
    create_provider_payload,
    create_savings_period_payload,
    decide_dispute_payload,
    decide_inpatient_payload,
    decide_task_payload,
    record_findings_payload,
)
from .test_users import (
    TEST_USERS,
    make_adjudicator_headers,
    make_approver_headers,
    make_librarian_headers,
    make_provider_headers,
    make_reviewer_headers,
    make_senior_reviewer_headers,
)

ADMIN = TEST_USERS["plan_admin_headers"]
ANY_READER = TEST_USERS["plan_admin_headers"]

DEFAULT_WINDOW_START = "2026-01-01T00:00:00Z"
DEFAULT_SERVICE_DATE = "2026-07-10T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_provider(npi="NPI-0001", name="Test Provider"):
    """Create a provider (born ACTIVE). Returns the provider."""
    payload = create_provider_payload(npi=npi, name=name)
    return get_success_data(api_client.create_provider(payload, ADMIN))


def create_edit_rule(edit_code="EDIT-01", category="CODING", source="INTERNAL",
                     librarian_id="librarian-1"):
    """Create an edit rule (active_version_count 0). Returns the rule."""
    payload = create_edit_rule_payload(edit_code=edit_code, category=category,
                                       source=source)
    return get_success_data(
        api_client.create_edit_rule(payload, make_librarian_headers(librarian_id)))


def create_edit_version(rule_id, severity="DENY", claim_types=("PROFESSIONAL",),
                        logic_expression="deny line",
                        effective_from=DEFAULT_WINDOW_START, effective_to=None,
                        librarian_id="librarian-1"):
    """Create a DRAFT edit version under the rule. Returns the version."""
    payload = create_edit_version_payload(
        severity=severity, applies_to_claim_types=list(claim_types),
        logic_expression=logic_expression, effective_from=effective_from)
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return get_success_data(
        api_client.create_edit_version(rule_id, payload,
                                       make_librarian_headers(librarian_id)))


def submit_version(version_id, librarian_id="librarian-1"):
    return get_success_data(
        api_client.submit_edit_version(version_id,
                                       make_librarian_headers(librarian_id)))


def approve_version(version_id, expected_edit_rule_version, approver_id="approver-1",
                    attestation=None):
    payload = {"expected_edit_rule_version": expected_edit_rule_version}
    if attestation is not None:
        payload["clinical_review_attestation"] = attestation
    return get_success_data(
        api_client.approve_edit_version(version_id, payload,
                                        make_approver_headers(approver_id)))


def create_active_edit(edit_code="EDIT-01", category="CODING", source="INTERNAL",
                       severity="DENY", claim_types=("PROFESSIONAL",),
                       logic_expression="deny line",
                       effective_from=DEFAULT_WINDOW_START, effective_to=None,
                       librarian_id="librarian-1", approver_id="approver-1",
                       attestation=None):
    """Rule + version walked to ACTIVE. Returns (rule, active_version)."""
    rule = create_edit_rule(edit_code, category, source, librarian_id)
    version = create_edit_version(rule["id"], severity, claim_types,
                                  logic_expression, effective_from, effective_to,
                                  librarian_id)
    submit_version(version["id"], librarian_id)
    version = approve_version(version["id"], rule["version"], approver_id,
                              attestation=attestation)
    return rule, version


def get_rule(rule_id):
    return get_success_data(api_client.get_edit_rule(rule_id, ANY_READER))


def get_version(version_id):
    return get_success_data(api_client.get_edit_version(version_id, ANY_READER))


def get_claim(claim_id):
    return get_success_data(api_client.get_claim(claim_id, ANY_READER))


# ---------------------------------------------------------------------------
# Tier 2: claims
# ---------------------------------------------------------------------------

def create_claim_with_lines(provider_id, lines=((1, "99213", 30000),),
                            claim_number="C1", member_id="M-1",
                            claim_type="PROFESSIONAL",
                            total_billed_cents=None,
                            service_from=DEFAULT_SERVICE_DATE,
                            service_to=DEFAULT_SERVICE_DATE,
                            admission_date=None, discharge_date=None,
                            drg_code=None, discharge_disposition=None):
    """Create a claim as its owning provider and add the given lines
    ((line_number, procedure_code, billed_cents), ...). Returns the claim."""
    if total_billed_cents is None:
        total_billed_cents = sum(line[2] for line in lines)
    payload = create_claim_payload(
        provider_id, claim_number=claim_number, member_id=member_id,
        claim_type=claim_type, total_billed_cents=total_billed_cents,
        service_from=service_from, service_to=service_to)
    if admission_date is not None:
        payload["admission_date"] = admission_date
    if discharge_date is not None:
        payload["discharge_date"] = discharge_date
    if drg_code is not None:
        payload["drg_code"] = drg_code
    if discharge_disposition is not None:
        payload["discharge_disposition"] = discharge_disposition
    claim = get_success_data(
        api_client.create_claim(payload, make_provider_headers(provider_id)))
    for line_number, procedure_code, billed_cents in lines:
        get_success_data(api_client.add_claim_line(
            claim["id"],
            create_claim_line_payload(line_number, procedure_code, billed_cents),
            make_provider_headers(provider_id)))
    return claim


def create_inpatient_claim(provider_id, member_id, drg_code, admission_date,
                           discharge_date, total_billed_cents,
                           discharge_disposition="HOME", claim_number="IP1"):
    """Inpatient claim with one revenue line covering the full billed total."""
    return create_claim_with_lines(
        provider_id,
        lines=((1, "REV-010", total_billed_cents),),
        claim_number=claim_number, member_id=member_id,
        claim_type="INSTITUTIONAL_INPATIENT",
        total_billed_cents=total_billed_cents,
        service_from=admission_date, service_to=discharge_date,
        admission_date=admission_date, discharge_date=discharge_date,
        drg_code=drg_code, discharge_disposition=discharge_disposition)


def run_claim_edits(claim_id):
    """Screen the claim (PlanAdmin). Returns the post-screening claim."""
    return get_success_data(api_client.run_edits(claim_id, ADMIN))


def list_claim_tasks(claim_id, status=None):
    params = {"claim_id": claim_id}
    if status is not None:
        params["status"] = status
    data, _meta = validate_paginated(
        api_client.list_review_tasks(ANY_READER, params=params))
    return data


def list_claim_hits(claim_id):
    data, _meta = validate_paginated(
        api_client.list_claim_edit_hits(claim_id, ANY_READER))
    return data


def get_hit(hit_id):
    return get_success_data(api_client.get_edit_hit(hit_id, ANY_READER))


def get_abrasion_profile(provider_id):
    """The provider's 1:1 abrasion profile."""
    data, _meta = validate_paginated(
        api_client.list_abrasion_profiles(ANY_READER,
                                          params={"provider_id": provider_id}))
    assert len(data) == 1, f"expected exactly one abrasion profile, got {len(data)}"
    return data[0]


def get_claim_ibr(claim_id, index=0):
    data, _meta = validate_paginated(
        api_client.list_ibrs(ANY_READER, params={"claim_id": claim_id}))
    assert len(data) > index, f"expected IBR[{index}] for claim {claim_id}"
    return data[index]


def list_inpatient_reviews(claim_id, review_type=None):
    params = {"claim_id": claim_id}
    if review_type is not None:
        params["review_type"] = review_type
    data, _meta = validate_paginated(
        api_client.list_inpatient_reviews(ANY_READER, params=params))
    return data


def get_inpatient_review_by_type(claim_id, review_type):
    rows = list_inpatient_reviews(claim_id, review_type=review_type)
    assert len(rows) == 1, (
        f"expected exactly one {review_type} review for claim {claim_id}, "
        f"got {len(rows)}")
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 3: screening / review workflow
# ---------------------------------------------------------------------------

def setup_provider_with_active_edit(npi="NPI-1000", edit_code="DENY-01",
                                    severity="DENY",
                                    claim_types=("PROFESSIONAL",), **edit_kw):
    """Provider + INTERNAL edit walked to ACTIVE.
    Returns (provider, rule, active_version)."""
    provider = create_provider(npi=npi)
    rule, version = create_active_edit(edit_code=edit_code, severity=severity,
                                       claim_types=claim_types, **edit_kw)
    return provider, rule, version


def screen_one_line_claim(provider_id, billed=30000, claim_number="C1",
                          member_id="M-1", procedure_code="99213"):
    """One-line PROFESSIONAL claim created and screened.
    Returns the post-screening claim."""
    claim = create_claim_with_lines(
        provider_id, lines=((1, procedure_code, billed),),
        claim_number=claim_number, member_id=member_id)
    return run_claim_edits(claim["id"])


def assign_task(task_id, reviewer_user_id, assignee_role=None,
                senior_id="senior-1"):
    payload = assign_task_payload(reviewer_user_id)
    if assignee_role is not None:
        payload["assignee_role"] = assignee_role
    return get_success_data(
        api_client.assign_review_task(task_id, payload,
                                      make_senior_reviewer_headers(senior_id)))


def decide_task(task_id, outcome, user_id, role="Reviewer"):
    headers = (make_senior_reviewer_headers(user_id) if role == "SeniorReviewer"
               else make_reviewer_headers(user_id))
    return get_success_data(
        api_client.decide_review_task(task_id, decide_task_payload(outcome), headers))


def assign_and_decide(task_id, reviewer_id="rev-1", outcome="UPHOLD",
                      role="Reviewer", senior_id="senior-1"):
    """Assign then decide a PENDING task. Returns the DECIDED task."""
    assign_task(task_id, reviewer_id, senior_id=senior_id)
    return decide_task(task_id, outcome, reviewer_id, role=role)


def open_dispute(provider_id, claim_id, hit_id, reason="contest denial"):
    """Create a dispute as the owning provider, threading the claim's current
    version (OCC). Returns the SUBMITTED dispute."""
    claim = get_claim(claim_id)
    payload = create_dispute_payload(hit_id, claim["version"], reason=reason)
    return get_success_data(
        api_client.create_dispute(claim_id, payload,
                                  make_provider_headers(provider_id)))


def open_dispute_under_review(provider_id, claim_id, hit_id,
                              adjudicator_id="adj-1", reason="contest denial"):
    """Dispute created and moved to UNDER_REVIEW. Returns the dispute."""
    dispute = open_dispute(provider_id, claim_id, hit_id, reason=reason)
    return get_success_data(
        api_client.start_dispute_review(dispute["id"],
                                        make_adjudicator_headers(adjudicator_id)))


def drive_hit_resolution(provider_id, billed, claim_number, member_id,
                         resolution, reviewer_id="rev-1", adjudicator_id="adj-1",
                         senior_id="senior-1"):
    """Screen a one-line claim and resolve its single hit along `resolution`:

    - "fired"    — leave the hit FIRED and its task PENDING
    - "uphold"   — task decided UPHOLD (hit CONFIRMED)
    - "override" — task decided OVERRIDE (hit OVERRIDDEN, full release)
    - "overturn" — uphold, then dispute decided OVERTURNED (false positive)
    - ("partial", cents) — uphold, then dispute decided PARTIAL releasing cents

    Returns dict(claim, task, hit, dispute). `claim` is re-read at the end;
    `dispute` is None unless a dispute was opened.
    """
    claim = screen_one_line_claim(provider_id, billed=billed,
                                  claim_number=claim_number, member_id=member_id)
    tasks = list_claim_tasks(claim["id"])
    assert len(tasks) == 1, f"expected one review task, got {len(tasks)}"
    task = tasks[0]
    hit = list_claim_hits(claim["id"])[0]
    dispute = None
    if resolution != "fired":
        outcome = "OVERRIDE" if resolution == "override" else "UPHOLD"
        task = assign_and_decide(task["id"], reviewer_id=reviewer_id,
                                 outcome=outcome, senior_id=senior_id)
        if resolution == "overturn":
            dispute = open_dispute_under_review(provider_id, claim["id"], hit["id"],
                                                adjudicator_id=adjudicator_id)
            dispute = get_success_data(api_client.decide_dispute(
                dispute["id"], decide_dispute_payload("OVERTURNED"),
                make_adjudicator_headers(adjudicator_id)))
        elif isinstance(resolution, tuple) and resolution[0] == "partial":
            dispute = open_dispute_under_review(provider_id, claim["id"], hit["id"],
                                                adjudicator_id=adjudicator_id)
            dispute = get_success_data(api_client.decide_dispute(
                dispute["id"],
                decide_dispute_payload("PARTIAL", released_cents=resolution[1]),
                make_adjudicator_headers(adjudicator_id)))
    return {
        "claim": get_claim(claim["id"]),
        "task": get_success_data(api_client.get_review_task(task["id"], ANY_READER)),
        "hit": get_hit(hit["id"]),
        "dispute": dispute,
    }


def create_upheld_claim(npi="NPI-2000", edit_code="DENY-UP", billed=30000,
                        claim_number="CU1", member_id="M-U1",
                        reviewer_id="rev-1"):
    """Provider + ACTIVE INTERNAL DENY edit + claim screened and upheld.
    Returns the resolution dict plus provider/rule/version."""
    provider, rule, version = setup_provider_with_active_edit(
        npi=npi, edit_code=edit_code)
    ctx = drive_hit_resolution(provider["id"], billed, claim_number, member_id,
                               "uphold", reviewer_id=reviewer_id)
    ctx.update({"provider": provider, "rule": rule, "version": version})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: inpatient reviews
# ---------------------------------------------------------------------------

def record_findings(review_id, audited_drg_code=None, senior_id="senior-1"):
    payload = record_findings_payload()
    if audited_drg_code is not None:
        payload["audited_drg_code"] = audited_drg_code
    return get_success_data(
        api_client.record_inpatient_findings(review_id, payload,
                                             make_senior_reviewer_headers(senior_id)))


def decide_inpatient(review_id, outcome, senior_id="senior-1"):
    return get_success_data(
        api_client.decide_inpatient_review(
            review_id, decide_inpatient_payload(outcome),
            make_senior_reviewer_headers(senior_id)))


def close_drg_validation(claim_id, senior_id="senior-1"):
    """Decide the claim's DRG_VALIDATION review NO_CHANGE. Returns the review."""
    review = get_inpatient_review_by_type(claim_id, "DRG_VALIDATION")
    record_findings(review["id"], senior_id=senior_id)
    return decide_inpatient(review["id"], "NO_CHANGE", senior_id=senior_id)


# ---------------------------------------------------------------------------
# Tier 4: itemized bill reviews
# ---------------------------------------------------------------------------

def create_manual_ibr(claim_id, senior_id="senior-1"):
    return get_success_data(
        api_client.create_ibr(claim_id, make_senior_reviewer_headers(senior_id)))


def complete_ibr_review(ibr_id, provider_id, findings_cents=0,
                        senior_id="senior-1"):
    """Walk an IBR REQUESTED -> COMPLETED (documents, audit, complete).
    Returns the COMPLETED review."""
    get_success_data(
        api_client.receive_ibr_documents(ibr_id, make_provider_headers(provider_id)))
    get_success_data(
        api_client.start_ibr_audit(ibr_id, make_senior_reviewer_headers(senior_id)))
    return get_success_data(
        api_client.complete_ibr(ibr_id, {"findings_cents": findings_cents},
                                make_senior_reviewer_headers(senior_id)))


# ---------------------------------------------------------------------------
# Tier 5: savings periods and the clock
# ---------------------------------------------------------------------------

def create_savings_period(period_key="2026-08"):
    return get_success_data(
        api_client.create_savings_period(create_savings_period_payload(period_key),
                                         ADMIN))


def finalize_period(period_id):
    """OPEN -> RECONCILING -> FINALIZED. Returns the FINALIZED period."""
    get_success_data(api_client.begin_reconciliation(period_id, ADMIN))
    return get_success_data(api_client.finalize_savings_period(period_id, ADMIN))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def setup_savings_scenario(npi="NPI-9000", edit_code="SAV-DENY",
                           period_key="2026-08"):
    """The three-claim savings population, all under the default clock:

    - claim A: 50000 line, hit upheld (CONFIRMED, attributed 50000)
    - claim B: 70000 line, hit left FIRED (task PENDING)
    - claim C: 60000 line, hit upheld then dispute PARTIAL releasing 20000
      (hit OVERRIDDEN, released_cents 20000)

    The period is created and left OPEN, ready for `finalize_period` to walk
    it OPEN -> RECONCILING -> FINALIZED (PRD 3.9 state gates).
    Returns dict(provider, rule, version, period, a, b, c)."""
    provider, rule, version = setup_provider_with_active_edit(
        npi=npi, edit_code=edit_code)
    ctx_a = drive_hit_resolution(provider["id"], 50000, "SA", "M-SA", "uphold")
    ctx_b = drive_hit_resolution(provider["id"], 70000, "SB", "M-SB", "fired")
    ctx_c = drive_hit_resolution(provider["id"], 60000, "SC", "M-SC",
                                 ("partial", 20000))
    period = create_savings_period(period_key)
    return {
        "provider": provider, "rule": rule, "version": version,
        "period": period, "a": ctx_a, "b": ctx_b, "c": ctx_c,
    }

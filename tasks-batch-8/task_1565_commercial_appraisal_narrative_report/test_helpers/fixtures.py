"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Setup calls use get_success_data() so a broken precondition surfaces as a
clear "Setup failed" error naming the failing step, not a confusing assertion
deep inside a test.

Bundle convention: most helpers take and return a plain dict carrying the
created parties (client, author, reviewer, signer), their per-instance
headers (client_headers, author_headers, reviewer_headers, signer_headers),
and the engagement once it exists. Entity-backed role headers are always
built from the real entity ids (PRD §2.1 identity rules).

Cap-rate support note: PRD §3.4 computes the supported rate as the mean of
the adjusted rates over selected comparables and §3.5 requires the income
approach's rate to sit within 25 bps of it. The canonical two-comparable set
(200 Oak Ave unadjusted; 300 Elm St at -4.00%) supports 685 bps, so the
canonical 700 bps approach passes the tolerance gate. Tests that exercise the
tolerance boundary itself build their own comparable sets instead of using
add_support_comparables().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_approach_payload,
    create_appraiser_payload,
    create_client_payload,
    create_comparable_payload,
    create_data_submission_payload,
    create_engagement_payload,
    create_revision_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_mai_signer_headers,
    make_review_appraiser_headers,
    make_staff_appraiser_headers,
)

EM_HEADERS = TEST_USERS["engagement_manager_headers"]
RM_HEADERS = TEST_USERS["records_manager_headers"]
LC_HEADERS = TEST_USERS["legal_counsel_headers"]

# Canonical evidence set: supported cap rate = round(mean(650, 720)) = 685 bps.
COMP_OAK = {
    "address": "200 Oak Ave",
    "sale_date": "2026-03-01T00:00:00Z",
    "sale_price_cents": 10000000,
    "noi_at_sale_cents": 650000,
    "size_sf": 5000,
    "adjustment_pct": 0,
    "selected_for_support": True,
}
COMP_ELM = {
    "address": "300 Elm St",
    "sale_date": "2026-05-01T00:00:00Z",
    "sale_price_cents": 8000000,
    "noi_at_sale_cents": 600000,
    "size_sf": 4000,
    "adjustment_pct": -4.00,
    "selected_for_support": True,
}


# ─── Tier 2: entity hierarchy ─────────────────────────

def create_parties(with_signer=False, author_designation="CERTIFIED_GENERAL",
                   reviewer_designation="CERTIFIED_GENERAL",
                   signer_designation="MAI", extra_appraisers=None):
    """Register client + author + reviewer (+ optional MAI signer).

    extra_appraisers: optional list of (name, designation) tuples for
    additional registered appraisers, returned under bundle["extras"].
    Returns the parties bundle with per-instance headers.
    """
    client = get_success_data(
        api_client.create_client(create_client_payload(), EM_HEADERS))
    author = get_success_data(api_client.create_appraiser(
        create_appraiser_payload(full_name="Ann Author",
                                 designation=author_designation), EM_HEADERS))
    reviewer = get_success_data(api_client.create_appraiser(
        create_appraiser_payload(full_name="Rob Reviewer",
                                 designation=reviewer_designation), EM_HEADERS))
    signer = None
    if with_signer:
        signer = get_success_data(api_client.create_appraiser(
            create_appraiser_payload(full_name="Mary Mai",
                                     designation=signer_designation), EM_HEADERS))
    extras = []
    for name, designation in (extra_appraisers or []):
        extras.append(get_success_data(api_client.create_appraiser(
            create_appraiser_payload(full_name=name, designation=designation),
            EM_HEADERS)))
    return {
        "client": client,
        "author": author,
        "reviewer": reviewer,
        "signer": signer,
        "extras": extras,
        "client_headers": make_client_headers(client["id"]),
        "author_headers": make_staff_appraiser_headers(author["id"]),
        "reviewer_headers": make_review_appraiser_headers(reviewer["id"]),
        "signer_headers": (make_mai_signer_headers(signer["id"])
                           if signer else None),
    }


def create_engagement(parties, **overrides):
    """Create an engagement letter in DRAFT (PRD §3.2)."""
    payload = create_engagement_payload(
        parties["client"]["id"], parties["author"]["id"],
        parties["reviewer"]["id"], **overrides)
    return get_success_data(api_client.create_engagement(payload, EM_HEADERS))


def create_submitted_engagement(parties, **overrides):
    """Create + submit. Returns the engagement in PENDING_ACCEPTANCE."""
    eng = create_engagement(parties, **overrides)
    return get_success_data(api_client.submit_engagement(eng["id"], EM_HEADERS))


def create_in_progress_engagement(parties=None, **overrides):
    """Create + submit + client-accept. Bundle includes the IN_PROGRESS engagement."""
    parties = parties or create_parties()
    eng = create_submitted_engagement(parties, **overrides)
    eng = get_success_data(
        api_client.accept_engagement(eng["id"], parties["client_headers"]))
    return {**parties, "engagement": eng}


# ─── Evidence: data submissions and comparables ───────

def add_data_submission(bundle, accept=False, reject_note=None, **overrides):
    """Client files a submission; optionally the author accepts/rejects it."""
    eng_id = bundle["engagement"]["id"]
    sub = get_success_data(api_client.create_data_submission(
        eng_id, create_data_submission_payload(**overrides),
        bundle["client_headers"]))
    if accept:
        sub = get_success_data(
            api_client.accept_data_submission(sub["id"], bundle["author_headers"]))
    elif reject_note is not None:
        sub = get_success_data(api_client.reject_data_submission(
            sub["id"], {"review_note": reject_note}, bundle["author_headers"]))
    return sub


def add_comparable(bundle, **overrides):
    """Author adds a comparable sale to the engagement."""
    return get_success_data(api_client.create_comparable(
        bundle["engagement"]["id"], create_comparable_payload(**overrides),
        bundle["author_headers"]))


def add_support_comparables(bundle):
    """The canonical two-comparable set (supported cap rate 685 bps)."""
    oak = add_comparable(bundle, **COMP_OAK)
    elm = add_comparable(bundle, **COMP_ELM)
    return [oak, elm]


# ─── Valuation approaches ─────────────────────────────

def add_approach(bundle, complete=False, **overrides):
    """Author selects an approach; optionally completes it."""
    ap = get_success_data(api_client.create_approach(
        bundle["engagement"]["id"], create_approach_payload(**overrides),
        bundle["author_headers"]))
    if complete:
        ap = get_success_data(
            api_client.complete_approach(ap["id"], bundle["author_headers"]))
    return ap


def add_income_approach(bundle, complete=True, weight_pct=100.00,
                        cap_rate_bps=700, dcf=None):
    """Select (+ complete) the canonical INCOME approach (cap 700 bps)."""
    overrides = {"approach_type": "INCOME", "weight_pct": weight_pct,
                 "cap_rate_bps": cap_rate_bps}
    if dcf:
        overrides.update(dcf)
    return add_approach(bundle, complete=complete, **overrides)


def setup_income_engagement(parties=None, complete=True, **engagement_overrides):
    """IN_PROGRESS engagement + ACCEPTED operating statement + the canonical
    comparable set + (optionally) a COMPLETE INCOME approach at weight 100."""
    bundle = create_in_progress_engagement(parties, **engagement_overrides)
    bundle["statement"] = add_data_submission(bundle, accept=True)
    bundle["comparables"] = add_support_comparables(bundle)
    if complete:
        bundle["approach"] = add_income_approach(bundle, complete=True)
    return bundle


# ─── Tier 3/5: report lifecycle shortcuts ─────────────

def fresh_engagement(bundle):
    """Re-read the engagement (fresh version for OCC-guarded writes)."""
    eng = get_success_data(
        api_client.get_engagement(bundle["engagement"]["id"], EM_HEADERS))
    bundle["engagement"] = eng
    return eng


def fresh_report(bundle, report_id):
    return get_success_data(api_client.get_report(report_id, EM_HEADERS))


def create_draft_report(bundle):
    """Create a new report version in DRAFTING (OCC on engagement version)."""
    eng = fresh_engagement(bundle)
    report = get_success_data(api_client.create_report(
        eng["id"], {"expected_engagement_version": eng["version"]},
        bundle["author_headers"]))
    bundle["report"] = report
    return report


def _ensure_bundle(bundle_or_parties, **engagement_overrides):
    """Coerce a parties-only dict into a full bundle via setup_income_engagement.

    A `parties` dict (created by create_parties) lacks `engagement`; a bundle
    produced by setup_income_engagement or a later helper has it. When handed
    parties, build the engagement chain with those parties so per-test
    appraiser designations are honored.
    """
    if bundle_or_parties is None:
        return setup_income_engagement(**engagement_overrides)
    if "engagement" not in bundle_or_parties:
        return setup_income_engagement(
            parties=bundle_or_parties, **engagement_overrides)
    return bundle_or_parties


def setup_report_internal_review(bundle=None, **engagement_overrides):
    """IN_PROGRESS engagement + COMPLETE INCOME approach + report in INTERNAL_REVIEW."""
    bundle = _ensure_bundle(bundle, **engagement_overrides)
    report = bundle.get("report") or create_draft_report(bundle)
    report = get_success_data(
        api_client.submit_review(report["id"], bundle["author_headers"]))
    bundle["report"] = report
    return bundle


def setup_report_client_review(bundle=None, **engagement_overrides):
    """Report advanced to CLIENT_REVIEW (approved and issued to the client)."""
    bundle = _ensure_bundle(bundle, **engagement_overrides)
    if "report" not in bundle:
        bundle = setup_report_internal_review(bundle, **engagement_overrides)
    report = bundle["report"]
    report = get_success_data(
        api_client.review_approve(report["id"], bundle["reviewer_headers"]))
    report = get_success_data(
        api_client.issue_to_client(report["id"], bundle["author_headers"]))
    bundle["report"] = report
    return bundle


def add_revision_request(bundle, **overrides):
    """Client files a revision request; the report auto-moves to REVISION_REQUESTED."""
    req = get_success_data(api_client.create_revision_request(
        bundle["report"]["id"], create_revision_request_payload(**overrides),
        bundle["client_headers"]))
    bundle["request"] = req
    bundle["report"] = fresh_report(bundle, bundle["report"]["id"])
    return req


def setup_report_revision_requested(bundle=None, **request_overrides):
    """Report in REVISION_REQUESTED with one OPEN request. Returns the bundle."""
    bundle = bundle or setup_report_client_review()
    add_revision_request(bundle, **request_overrides)
    return bundle


def setup_report_final(bundle=None, **engagement_overrides):
    """Report advanced CLIENT_REVIEW -> FINAL (no open/escalated requests)."""
    bundle = _ensure_bundle(bundle, **engagement_overrides)
    if "report" not in bundle:
        bundle = setup_report_client_review(bundle, **engagement_overrides)
    report = get_success_data(
        api_client.finalize_report(bundle["report"]["id"], bundle["author_headers"]))
    bundle["report"] = report
    return bundle


def setup_report_signed(parties=None, **engagement_overrides):
    """Report advanced FINAL -> SIGNED by the MAI signer."""
    if parties is None:
        parties = create_parties(with_signer=True)
    if parties.get("signer") is None:
        raise AssertionError("Setup failed: signing requires a signer party")
    bundle = setup_report_final(parties, **engagement_overrides)
    report = get_success_data(
        api_client.sign_report(bundle["report"]["id"], bundle["signer_headers"]))
    bundle["report"] = report
    return bundle


def setup_delivered_engagement(extra_submission=False, **engagement_overrides):
    """Full lifecycle through DELIVERED: engagement COMPLETED, client billed,
    retention record created, workfile frozen (PRD §3.8).

    When extra_submission is true, a second submission (a RENT_ROLL left in
    SUBMITTED) is filed just before delivery so the workfile freeze can be
    observed on both the ACCEPTED and the SUBMITTED submission.

    Returns the bundle with keys: parties fields, engagement, statement,
    comparables, approach, report, retention_record (+ pending_submission).
    """
    bundle = setup_report_signed(**engagement_overrides)
    if extra_submission:
        bundle["pending_submission"] = add_data_submission(
            bundle,
            submission_type="RENT_ROLL",
            period_start="2026-07-01T00:00:00Z",
            period_end="2026-07-31T00:00:00Z",
            scheduled_gross_rent_cents=1000000,
            vacancy_loss_cents=50000,
            expense_reimbursements_cents=0,
            operating_expenses_cents=0)
    report = get_success_data(
        api_client.deliver_report(bundle["report"]["id"], bundle["author_headers"]))
    bundle["report"] = report
    bundle["engagement"] = fresh_engagement(bundle)
    records, _meta = _list_retention_records(bundle["engagement"]["id"])
    bundle["retention_record"] = records[0]
    return bundle


def _list_retention_records(engagement_id):
    res = api_client.list_retention_records(
        RM_HEADERS, params={"engagement_id": engagement_id})
    body = res.json()
    if res.status_code != 200:
        raise AssertionError(
            f"Setup step failed with HTTP {res.status_code}: {body}")
    return body["data"], body["meta"]


# ─── Litigation hold helpers ──────────────────────────

def place_hold(bundle, matter_reference="Case 26-CV-1042"):
    """LegalCounsel places a litigation hold on the bundle's engagement."""
    return get_success_data(api_client.place_litigation_hold(
        bundle["engagement"]["id"], {"matter_reference": matter_reference},
        LC_HEADERS))


def release_hold(bundle):
    """LegalCounsel releases the litigation hold."""
    return get_success_data(api_client.release_litigation_hold(
        bundle["engagement"]["id"], LC_HEADERS))

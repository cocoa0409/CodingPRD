"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of every test. Setup calls use the
lenient get_success_data validator so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion later.

Identity threading (PRD §2.1): ownership-gated Advertiser calls pass the acting
Account.id as X-User-ID; Publisher calls pass the acting Newspaper.id.
"""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    platform_admin_headers,
    compliance_officer_headers,
    make_advertiser_headers,
    make_publisher_headers,
)
from . import factories


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _advertiser(account):
    return make_advertiser_headers(account["id"])


def _publisher(newspaper):
    return make_publisher_headers(newspaper["id"])


def weekly_dates(first_iso: str, count: int) -> list:
    """Consecutive weekly dates first, first+7, ... (PRD §3.4)."""
    start = date.fromisoformat(first_iso)
    return [(start + timedelta(days=7 * k)).isoformat() for k in range(count)]


def set_clock(api, iso: str):
    return get_success_data(api.set_clock(iso, platform_admin_headers()))


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

def create_newspaper(api, **overrides):
    return get_success_data(
        api.create_newspaper(factories.create_newspaper_payload(**overrides),
                             platform_admin_headers())
    )


def create_account(api, **overrides):
    return get_success_data(
        api.create_account(factories.create_account_payload(**overrides),
                          platform_admin_headers())
    )


def create_statutory_requirement(api, **overrides):
    return get_success_data(
        api.create_statutory_requirement(
            factories.create_statutory_requirement_payload(**overrides),
            platform_admin_headers())
    )


def provision_reference(api, newspaper_overrides=None, account_overrides=None,
                        statutory_overrides=None):
    """Create one newspaper, one account, and one statutory requirement.

    Returns dict {newspaper, account, statutory}.
    """
    newspaper = create_newspaper(api, **(newspaper_overrides or {}))
    account = create_account(api, **(account_overrides or {}))
    statutory = create_statutory_requirement(api, **(statutory_overrides or {}))
    return {"newspaper": newspaper, "account": account, "statutory": statutory}


# ---------------------------------------------------------------------------
# Notice lifecycle building blocks
# ---------------------------------------------------------------------------

def create_draft_notice(api, account, newspaper, **overrides):
    return get_success_data(
        api.create_notice(
            factories.create_notice_payload(account["id"], newspaper["id"], **overrides),
            _advertiser(account))
    )


def submit_notice(api, notice, account):
    return get_success_data(api.submit_notice(notice["id"], _advertiser(account)))


def get_pending_proof(api, notice, account):
    proofs = get_success_data(api.list_notice_proofs(notice["id"], _advertiser(account)))
    # Latest proof is the live one after (re)submission; take the last row.
    return proofs[-1]


def approve_proof(api, proof, account, reviewer_note=None):
    payload = {} if reviewer_note is None else {"reviewer_note": reviewer_note}
    return get_success_data(api.approve_proof(proof["id"], payload, _advertiser(account)))


def reject_proof(api, proof, account, reviewer_note=None):
    payload = {} if reviewer_note is None else {"reviewer_note": reviewer_note}
    return get_success_data(api.reject_proof(proof["id"], payload, _advertiser(account)))


def get_notice(api, notice_id, account):
    return get_success_data(api.get_notice(notice_id, _advertiser(account)))


def schedule_run(api, notice, account, first_publication_date="2026-03-01", version=None):
    if version is None:
        version = get_notice(api, notice["id"], account)["version"]
    return get_success_data(
        api.schedule_notice(
            notice["id"],
            factories.schedule_notice_payload(first_publication_date, version),
            _advertiser(account))
    )


def list_insertions(api, notice, account):
    return get_success_data(api.list_notice_insertions(notice["id"], _advertiser(account)))


def publish_insertion(api, insertion, newspaper, clock_iso, line_count_actual=2):
    set_clock(api, clock_iso)
    return get_success_data(
        api.publish_insertion(
            insertion["id"],
            factories.publish_insertion_payload(line_count_actual),
            _publisher(newspaper))
    )


# ---------------------------------------------------------------------------
# Tier: state progression scenarios
# ---------------------------------------------------------------------------

def setup_proof_approved_notice(api, newspaper_overrides=None, account_overrides=None,
                                statutory_overrides=None, notice_overrides=None,
                                clock_iso="2026-02-01T00:00:00Z"):
    """Reference data + a notice driven to PROOF_APPROVED (submitted, proof approved).

    Returns dict {newspaper, account, statutory, notice, proof}.
    """
    if clock_iso is not None:
        set_clock(api, clock_iso)
    ref = provision_reference(api, newspaper_overrides, account_overrides, statutory_overrides)
    notice = create_draft_notice(api, ref["account"], ref["newspaper"],
                                 **(notice_overrides or {}))
    submit_notice(api, notice, ref["account"])
    proof = get_pending_proof(api, notice, ref["account"])
    approve_proof(api, proof, ref["account"])
    notice = get_notice(api, notice["id"], ref["account"])
    ref.update({"notice": notice, "proof": proof})
    return ref


def setup_submitted_notice(api, newspaper_overrides=None, account_overrides=None,
                           statutory_overrides=None, notice_overrides=None,
                           clock_iso="2026-02-01T00:00:00Z"):
    """Reference data + a notice in SUBMITTED with one PENDING proof.

    Returns dict {newspaper, account, statutory, notice, proof}.
    """
    if clock_iso is not None:
        set_clock(api, clock_iso)
    ref = provision_reference(api, newspaper_overrides, account_overrides, statutory_overrides)
    notice = create_draft_notice(api, ref["account"], ref["newspaper"],
                                 **(notice_overrides or {}))
    submit_notice(api, notice, ref["account"])
    proof = get_pending_proof(api, notice, ref["account"])
    notice = get_notice(api, notice["id"], ref["account"])
    ref.update({"notice": notice, "proof": proof})
    return ref


def setup_scheduled_notice(api, first_publication_date="2026-03-01",
                           newspaper_overrides=None, account_overrides=None,
                           statutory_overrides=None, notice_overrides=None,
                           clock_iso="2026-02-01T00:00:00Z"):
    """Notice driven to SCHEDULED with its generated insertions.

    Returns dict {newspaper, account, statutory, notice, proof, insertions}.
    """
    ref = setup_proof_approved_notice(api, newspaper_overrides, account_overrides,
                                      statutory_overrides, notice_overrides, clock_iso)
    notice = schedule_run(api, ref["notice"], ref["account"], first_publication_date)
    insertions = list_insertions(api, notice, ref["account"])
    ref.update({"notice": notice, "insertions": insertions})
    return ref


def setup_running_notice(api, first_publication_date="2026-03-01",
                         line_count_actual=2, **kwargs):
    """Multi-insertion notice with the FIRST insertion published (notice RUNNING).

    Returns dict adding {insertions, published_dates}. Requires required_insertions >= 2.
    """
    ref = setup_scheduled_notice(api, first_publication_date=first_publication_date, **kwargs)
    insertions = ref["insertions"]
    dates = weekly_dates(first_publication_date, len(insertions))
    publish_insertion(api, insertions[0], ref["newspaper"],
                      dates[0] + "T00:00:00Z", line_count_actual)
    ref["notice"] = get_notice(api, ref["notice"]["id"], ref["account"])
    ref["insertions"] = list_insertions(api, ref["notice"], ref["account"])
    ref["published_dates"] = dates
    return ref


def setup_published_notice(api, first_publication_date="2026-03-01",
                           line_count_actual=2, **kwargs):
    """Notice with ALL required insertions published (notice PUBLISHED).

    Publishes each generated insertion in sequence, advancing the clock to each
    scheduled date. Returns dict adding {invoice, affidavit, insertions}.
    """
    ref = setup_scheduled_notice(api, first_publication_date=first_publication_date, **kwargs)
    account = ref["account"]
    newspaper = ref["newspaper"]
    insertions = ref["insertions"]
    dates = weekly_dates(first_publication_date, len(insertions))
    for ins, d in zip(insertions, dates):
        publish_insertion(api, ins, newspaper, d + "T00:00:00Z", line_count_actual)
    ref["notice"] = get_notice(api, ref["notice"]["id"], account)
    ref["insertions"] = list_insertions(api, ref["notice"], account)
    affidavits = get_success_data(
        api.list_notice_affidavits(ref["notice"]["id"], _advertiser(account)))
    ref["affidavit"] = affidavits[0] if affidavits else None
    invoices = get_success_data(
        api.list_invoices(_advertiser(account), params={"notice_id": ref["notice"]["id"]}))
    ref["invoice"] = invoices[0] if invoices else None
    ref["published_dates"] = dates
    return ref


def issue_affidavit(api, ref, sworn_by="Pat Publisher"):
    """Issue the notice's PENDING affidavit (notice PUBLISHED -> AFFIDAVIT_ISSUED)."""
    account = ref["account"]
    aff = get_success_data(
        api.issue_affidavit(ref["affidavit"]["id"],
                           factories.issue_affidavit_payload(sworn_by),
                           _publisher(ref["newspaper"])))
    ref["affidavit"] = aff
    ref["notice"] = get_notice(api, ref["notice"]["id"], account)
    invoices = get_success_data(
        api.list_invoices(_advertiser(account), params={"notice_id": ref["notice"]["id"]}))
    ref["invoice"] = invoices[0] if invoices else ref.get("invoice")
    return ref


def setup_affidavit_issued(api, **kwargs):
    """Notice fully published, affidavit ISSUED, invoice ISSUED.

    Returns dict {newspaper, account, notice, insertions, affidavit, invoice}.
    """
    ref = setup_published_notice(api, **kwargs)
    return issue_affidavit(api, ref)


def setup_invoice_paid(api, amount_cents=None, **kwargs):
    """Notice fully published, affidavit ISSUED, invoice PAID in full."""
    ref = setup_affidavit_issued(api, **kwargs)
    account = ref["account"]
    pay_amt = amount_cents if amount_cents is not None else ref["invoice"]["total_cents"]
    get_success_data(
        api.create_payment(factories.payment_payload(ref["invoice"]["id"], pay_amt),
                          _advertiser(account)))
    ref["invoice"] = get_success_data(api.get_invoice(ref["invoice"]["id"], _advertiser(account)))
    ref["notice"] = get_notice(api, ref["notice"]["id"], account)
    return ref


# ---------------------------------------------------------------------------
# Tier: skip / make-good scenarios
# ---------------------------------------------------------------------------

def skip_insertion(api, insertion, newspaper):
    return get_success_data(api.skip_insertion(insertion["id"], _publisher(newspaper)))


def get_make_good_for(api, skipped_insertion, newspaper):
    rows = get_success_data(
        api.list_insertions(_publisher(newspaper),
                          params={"makes_good_insertion_id": skipped_insertion["id"]}))
    return rows[0] if rows else None

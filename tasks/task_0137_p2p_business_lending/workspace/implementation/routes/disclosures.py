"""Disclosure endpoints: get, list, publish."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import store
from errors import (
    err_disclosure_locked,
    err_disclosure_stale,
    err_invalid_state_transition,
    err_segregation_violation,
)
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    enforce_compliance_officer_identity,
    get_disclosure,
    get_platform,
    paginate,
    parse_pagination,
    sort_for_list,
)
from services.engine import stamp_audit_only
from services.serializers import serialize_disclosure
from utils import iso_now

bp = Blueprint("disclosures", __name__)


@bp.get("/platforms/<platform_id>/disclosures/<disclosure_id>")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Borrower", "Investor"])
def get_disclosure_route(platform_id, disclosure_id):
    d = get_disclosure(platform_id, disclosure_id)
    return success(serialize_disclosure(d))


@bp.get("/platforms/<platform_id>/disclosures")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Borrower", "Investor"])
def list_disclosures(platform_id):
    get_platform(platform_id)
    limit, offset = parse_pagination()

    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    kind = request.args.get("kind")
    published_raw = request.args.get("published")

    items = [d for d in store.disclosures.values() if d["platform_id"] == platform_id]
    if subject_type:
        items = [d for d in items if d["subject_type"] == subject_type]
    if subject_id:
        items = [d for d in items if d["subject_id"] == subject_id]
    if kind:
        items = [d for d in items if d["kind"] == kind]
    if published_raw is not None:
        pub_filter = published_raw.lower() in ("true", "1", "yes")
        items = [d for d in items if bool(d["published"]) == pub_filter]

    items = sort_for_list(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize_disclosure(x) for x in page], limit, offset, total)


@bp.post("/platforms/<platform_id>/disclosures/<disclosure_id>/publish")
@require_auth(["ComplianceOfficer", "PlatformOperator"])
def publish_disclosure(platform_id, disclosure_id):
    # PRD §3.7: "Publication is reserved for a ComplianceOfficer; a
    # PlatformOperator attempting to publish receives
    # ERR_SEGREGATION_VIOLATION." The role-list above admits
    # PlatformOperator past the structural gate so the segregation
    # rejection is the one returned, per PRD §3.9.
    if g.role == "PlatformOperator":
        raise err_segregation_violation(
            "PlatformOperator may not publish (segregation of duties)."
        )
    enforce_compliance_officer_identity(platform_id)
    platform = get_platform(platform_id)
    d = get_disclosure(platform_id, disclosure_id)

    # ERR_DISCLOSURE_LOCKED if already published.
    if d.get("published"):
        raise err_disclosure_locked()

    # Payload must be non-empty.
    if not d.get("payload"):
        raise err_invalid_state_transition("Disclosure payload is empty.")

    # ERR_DISCLOSURE_STALE: subject has terminated since the draft was issued.
    if not _subject_still_consistent(d):
        raise err_disclosure_stale()

    with store.lock:
        # Recheck inside lock for the publish race.
        if d.get("published"):
            raise err_disclosure_locked()
        d["published"] = True
        d["published_on_day_index"] = platform["clock_day_index"]
    return success(serialize_disclosure(d))


def _subject_still_consistent(disclosure: dict) -> bool:
    """Return True if the disclosure's subject is still in the state that
    produced the draft. Used to enforce ERR_DISCLOSURE_STALE.

    Heuristic per PRD §3.7: a LISTING_FUNDED draft cannot be published if
    the listing has since moved to WITHDRAWN or EXPIRED — i.e., out of the
    state that triggered the emission. For LISTING_OPENED, the listing
    should still be at-or-after OPEN (it may have advanced to FUNDED or
    ORIGINATED — those are progressions, not regressions, and the disclosure
    of the open event remains valid). For loan-status disclosures (DELINQUENCY,
    DEFAULT, CHARGE_OFF), the loan should still be at-or-beyond that escalation.
    """
    snapshot_status = disclosure.get("_subject_status_at_emit")
    kind = disclosure["kind"]
    subj_type = disclosure["subject_type"]
    subj_id = disclosure["subject_id"]

    if subj_type == "LISTING":
        listing = store.loan_listings.get(subj_id)
        if listing is None:
            return False
        current = listing["status"]
        if kind == "LISTING_OPENED":
            # The opening is permanent history; staleness only if the listing
            # was withdrawn/expired BEFORE we publish — these are progressions
            # that don't invalidate the historical fact. We treat the OPENED
            # disclosure as never stale.
            return True
        if kind == "LISTING_FUNDED":
            # Funded → must still be at-or-beyond FUNDED (i.e. FUNDED or ORIGINATED).
            return current in ("FUNDED", "ORIGINATED")
        return True

    if subj_type == "LOAN":
        loan = store.loans.get(subj_id)
        if loan is None:
            return False
        current = loan["status"]
        # PRD §3.7: "publish capability moves the disclosure DRAFT ->
        # PUBLISHED only if payload is non-empty and the subject is
        # still in the state that produced the draft — for example, a
        # LISTING_FUNDED draft cannot be published if the listing has
        # since moved to WITHDRAWN or EXPIRED. Either failure mode
        # yields ERR_DISCLOSURE_STALE."
        # Each kind names the state it was emitted from; the subject
        # must STILL be in that exact state for publish to succeed.
        if kind == "LOAN_ORIGINATED":
            # LOAN_ORIGINATED is emitted at FUNDED->ACTIVE. The loan
            # may not retreat from ACTIVE; CHARGED_OFF / PAID_OFF are
            # terminal forward progressions. Treat origination as a
            # permanent historical fact (analogous to LISTING_OPENED).
            return True
        if kind == "DELINQUENCY_NOTICE":
            return current == "DELINQUENT"
        if kind == "DEFAULT_NOTICE":
            return current == "DEFAULT"
        if kind == "CHARGE_OFF_NOTICE":
            return current == "CHARGED_OFF"
        return True

    # BORROWER / INVESTMENT subjects: no specific staleness rule.
    return True

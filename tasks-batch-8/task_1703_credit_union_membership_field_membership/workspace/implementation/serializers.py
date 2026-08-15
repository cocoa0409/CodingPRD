"""Entity serializers: strip internal keys, add computed fields."""
from datetime import date

import db
from services import calc

_COMMON = ("id", "created_at", "updated_at", "version")


def _clean(entity, fields):
    out = {k: entity.get(k) for k in fields}
    for k in _COMMON:
        if k in entity:
            out[k] = entity[k]
    return out


def serialize_charter(c):
    return _clean(c, ["bond_type", "par_value_cents", "status", "note"])


def serialize_segment(s):
    return _clean(s, ["charter_id", "segment_type", "descriptor",
                      "required_documents", "status", "retired_at"])


def serialize_amendment(a):
    return _clean(a, ["charter_id", "amendment_type", "proposed_segment_type",
                      "proposed_segment_descriptor", "proposed_segment_required_documents",
                      "retire_segment_ids", "effective_date", "baseline_charter_version",
                      "status", "submitted_by_user_id", "decided_by_user_id",
                      "denial_reason", "applied_segment_id"])


def serialize_application(a):
    return _clean(a, ["applicant_full_name", "date_of_birth", "basis", "segment_id",
                      "sponsor_member_id", "relationship_to_sponsor", "documents_provided",
                      "required_documents", "docs_complete", "requested_document_codes",
                      "status", "filed_by_user_id", "decided_by_user_id",
                      "denial_reason", "resulting_member_id"])


def serialize_member(m):
    out = _clean(m, ["application_id", "full_name", "date_of_birth", "eligibility_basis",
                     "segment_id", "sponsor_member_id", "relationship_to_sponsor",
                     "membership_effective_date", "status", "grace_end_date", "tier",
                     "last_tier_review_at", "mailing_address", "email", "phone"])
    eff = date.fromisoformat(m["membership_effective_date"])
    out["tenure_months"] = calc.tenure_months(eff, db.clock.current_date())
    out["qualifying_balance_cents"] = calc.qualifying_balance_cents(m["id"])
    return out


def serialize_account(a):
    return _clean(a, ["member_id", "account_type", "balance_cents", "opened_date",
                      "status", "closed_date", "closure_reason"])


def serialize_transaction(t):
    return {k: t[k] for k in
            ("id", "share_account_id", "kind", "amount_cents", "posted_date",
             "running_balance_cents", "origin", "created_at")}


def serialize_enrollment(e):
    return _clean(e, ["member_id", "product_code", "funding_share_account_id",
                      "required_tier", "tier_at_enrollment", "status", "closure_reason"])


def serialize_declaration(d):
    return _clean(d, ["period_start", "period_end", "rate_bps", "method", "payable_date",
                      "status", "declared_pool_cents", "paid_total_cents",
                      "declared_by_user_id", "paid_by_user_id"])


def serialize_payment(p):
    return _clean(p, ["declaration_id", "share_account_id", "accrued_amount_cents",
                      "credited_amount_cents", "accrual_delta_cents",
                      "tier_bonus_bps_applied", "status"])


def serialize_meeting(m):
    return _clean(m, ["meeting_date", "record_date", "voting_open_date",
                      "quorum_threshold", "status", "reconvened_from_id", "quorum_met",
                      "ballots_counted", "votes_for_slate_a", "votes_for_slate_b",
                      "votes_abstain"])


def serialize_ballot(b):
    return {k: b[k] for k in ("id", "meeting_id", "member_id", "choice",
                              "cast_date", "created_at")}


def serialize_review(r):
    return _clean(r, ["member_id", "reason", "status", "flagged_by_user_id",
                      "decided_by_user_id", "resolution_note"])

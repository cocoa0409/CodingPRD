"""Entity serializers: stored fields plus computed fields, datetimes formatted."""
from datetime import timedelta

import db
from db import store
from services import calcs, certs

REQUIRED_DOCUMENTS = {"PHOTO_ID", "SSN_CARD", "W2"}
OUT_OF_SCOPE_MFS = "FILING_STATUS_MFS"
ACCEPTED_LIKE = ("ACCEPTED", "COMPLETED")


def _public(entity, fields, datetimes=()):
    out = {}
    for f in fields:
        v = entity.get(f)
        if f in datetimes and v is not None:
            v = db.fmt_ts(v)
        out[f] = v
    return out


# --- Site ---------------------------------------------------------------------

SITE_FIELDS = ["id", "name", "sponsor_org", "station_capacity", "season_start",
               "season_end", "daily_open_hour", "daily_close_hour", "goal_returns",
               "status", "created_at", "updated_at", "version"]


def site_json(site):
    out = _public(site, SITE_FIELDS, datetimes=("season_start", "season_end"))
    accepted = sum(1 for r in store.tax_returns.values()
                   if r["site_id"] == site["id"] and r["status"] in ACCEPTED_LIKE)
    out["accepted_count"] = accepted
    out["goal_met"] = accepted >= site["goal_returns"]
    return out


# --- Volunteer ----------------------------------------------------------------

VOLUNTEER_FIELDS = ["id", "site_id", "full_name", "email", "is_coordinator",
                    "status", "created_at", "updated_at", "version"]


def volunteer_json(vol):
    out = _public(vol, VOLUNTEER_FIELDS)
    out["certified_test_types"] = certs.certified_test_types(vol["id"])
    out["active_case_count"] = sum(
        1 for r in store.tax_returns.values()
        if r["preparer_id"] == vol["id"] and r["status"] == "IN_PREPARATION")
    return out


# --- Certification ------------------------------------------------------------

CERT_FIELDS = ["id", "volunteer_id", "test_type", "score", "tax_season", "passed",
               "status", "attempt_number", "created_at", "updated_at", "version"]


def certification_json(cert):
    return _public(cert, CERT_FIELDS)


# --- Taxpayer -----------------------------------------------------------------

TAXPAYER_FIELDS = ["id", "full_name", "ssn_token", "phone", "email",
                   "preferred_language", "identity_status", "id_document_type",
                   "created_at", "updated_at", "version"]


def taxpayer_json(tp):
    return _public(tp, TAXPAYER_FIELDS)


# --- Appointment --------------------------------------------------------------

APPOINTMENT_FIELDS = ["id", "site_id", "taxpayer_id", "volunteer_id", "purpose",
                      "start_at", "end_at", "status", "created_at", "updated_at",
                      "version"]


def appointment_json(appt):
    return _public(appt, APPOINTMENT_FIELDS, datetimes=("start_at", "end_at"))


# --- TaxReturn ----------------------------------------------------------------

RETURN_FIELDS = ["id", "appointment_id", "taxpayer_id", "site_id", "preparer_id",
                 "reviewer_id", "tax_year", "filing_status",
                 "has_advanced_scope_items", "out_of_scope_flags", "status",
                 "documents_received", "interview_confirmed", "wages_cents",
                 "other_income_cents", "earned_income_cents",
                 "withholding_reported_cents", "withholding_verified_cents",
                 "qualifying_children", "refund_method", "final_refund_cents",
                 "submission_count", "first_ack_outcome", "qr_failure_count",
                 "reached_preparation", "transmitted_at", "referral_reason",
                 "referral_destination", "withdrawal_reason", "created_at",
                 "updated_at", "version"]


def documents_complete(ret):
    docs = set(ret["documents_received"])
    if not REQUIRED_DOCUMENTS.issubset(docs):
        return False
    if ret["refund_method"] == "DIRECT_DEPOSIT" and "BANK_INFO" not in docs:
        return False
    return True


def out_of_scope_reasons(ret):
    reasons = list(ret["out_of_scope_flags"])
    if ret["filing_status"] == "MARRIED_SEPARATE":
        reasons.append(OUT_OF_SCOPE_MFS)
    return reasons


def return_json(ret):
    out = _public(ret, RETURN_FIELDS, datetimes=("transmitted_at",))
    reasons = out_of_scope_reasons(ret)
    out["documents_complete"] = documents_complete(ret)
    out["out_of_scope"] = bool(reasons)
    out["out_of_scope_reasons"] = reasons
    out["estimated_refund_cents"] = calcs.estimated_refund_cents(ret)
    out["savings_match_cents"] = calcs.savings_match_cents(ret["id"])
    return out


# --- RefundAllocation ---------------------------------------------------------

ALLOCATION_FIELDS = ["id", "tax_return_id", "account_type", "routing_number",
                     "account_number_mask", "amount_cents", "created_at",
                     "updated_at", "version"]


def allocation_json(alloc):
    return _public(alloc, ALLOCATION_FIELDS)


# --- EfileRejection -----------------------------------------------------------

REJECTION_FIELDS = ["id", "tax_return_id", "rejection_code", "rejection_text",
                    "submission_number", "follow_up_status", "follow_up_due_at",
                    "contacted_at", "resolved_at", "resolution_note", "created_at",
                    "updated_at", "version"]

FOLLOW_UP_DUE_DAYS = 5


def rejection_json(rej):
    out = _public(rej, REJECTION_FIELDS,
                  datetimes=("follow_up_due_at", "contacted_at", "resolved_at"))
    out["follow_up_overdue"] = (rej["follow_up_status"] != "RESOLVED"
                                and db.LOGICAL_CLOCK > rej["follow_up_due_at"])
    return out


# --- SiteReport ---------------------------------------------------------------

REPORT_FIELDS = ["id", "site_id", "period_start", "period_end", "status",
                 "generated_at", "returns_prepared_count",
                 "returns_transmitted_count", "returns_accepted_count",
                 "returns_rejected_open_count", "returns_referred_count",
                 "returns_withdrawn_count", "qr_rework_total",
                 "first_pass_accepted_count", "first_pass_acceptance_rate_bp",
                 "final_resolution_rate_bp", "financial_referrals_accepted_count",
                 "savings_match_total_cents", "created_at", "updated_at", "version"]


def report_json(rep):
    return _public(rep, REPORT_FIELDS,
                   datetimes=("period_start", "period_end", "generated_at"))


# --- FinancialServiceReferral ---------------------------------------------------

REFERRAL_FIELDS = ["id", "tax_return_id", "service_type", "status", "offered_by",
                   "source", "created_at", "updated_at", "version"]


def referral_json(ref):
    return _public(ref, REFERRAL_FIELDS)

"""Entity serializers.

Every row is stored as a plain dict holding exactly the declared fields (plus a
private `_seq` used only as a deterministic tie-break, since the logical clock
is static).  Purely derived read-only fields are projected here so a read can
never disagree with the underlying rows.
"""

from clockutil import fmt
from db import db

_COMMON = ("id", "created_at", "updated_at", "version")

_DATETIME_FIELDS = frozenset([
    "created_at", "updated_at", "measurement_window_start",
    "measurement_window_end", "certified_at", "cessation_date", "determined_at",
    "issued_at", "review_deadline_at", "first_due_date",
    "default_notice_issued_at", "cure_deadline_at", "due_date", "delinquent_on",
    "paid_at", "filed_at", "plan_response_deadline_at", "arbitration_deadline_at",
    "decided_at", "initiated_at", "closed_at", "closing_date", "adjudicated_at",
])


def _project(row, fields):
    out = {}
    for name in fields:
        value = row.get(name)
        if name in _DATETIME_FIELDS:
            value = fmt(value)
        out[name] = value
    return out


# --------------------------------------------------------------------------
# derived projections
# --------------------------------------------------------------------------

def plan_counters(plan):
    employer_count = sum(1 for e in db.employers.values()
                         if e["plan_id"] == plan["id"])
    issued = 0
    for assessment in db.assessments.values():
        if assessment["lifecycle_status"] not in ("ISSUED", "FINAL"):
            continue
        event = db.withdrawal_events.get(assessment["withdrawal_event_id"])
        if not event:
            continue
        employer = db.employers.get(event["employer_id"])
        if employer and employer["plan_id"] == plan["id"]:
            issued += 1
    return employer_count, issued


def valuation_allocation(valuation):
    allocated = sum(a["net_assessed_cents"] for a in db.assessments.values()
                    if a.get("valuation_id") == valuation["id"]
                    and a["lifecycle_status"] in ("ISSUED", "FINAL"))
    return allocated, valuation["uvb_total_cents"] - allocated


# --------------------------------------------------------------------------
# serializers
# --------------------------------------------------------------------------

PLAN_FIELDS = ("id", "name", "industry", "allocation_method", "de_minimis_variant",
               "interest_rate_bps", "unattributable_uvb_cents",
               "mass_withdrawal_declared", "employer_count",
               "issued_assessment_count", "created_at", "updated_at", "version")


def plan(row):
    employer_count, issued = plan_counters(row)
    data = _project(row, PLAN_FIELDS)
    data["employer_count"] = employer_count
    data["issued_assessment_count"] = issued
    return data


GROUP_FIELDS = ("id", "name", "common_control_basis", "bond_posture",
                "joint_exposure_cents", "contingent_exposure_cents",
                "exposure_score", "created_at", "updated_at", "version")


def controlled_group(row):
    import services
    data = _project(row, GROUP_FIELDS)
    data.update(services.group_derived(row))
    return data


EMPLOYER_FIELDS = ("id", "plan_id", "controlled_group_id", "legal_name", "ein",
                   "obligation_start_year", "obligation_end_year",
                   "covered_work_status", "cba_count", "ceased_cba_count",
                   "directly_attributed_vested_benefits_cents",
                   "directly_attributed_assets_cents", "status",
                   "outstanding_liability_cents", "credit_watch",
                   "delinquency_strikes", "created_at", "updated_at", "version")


def employer(row):
    return _project(row, EMPLOYER_FIELDS)


VALUATION_FIELDS = ("id", "plan_id", "plan_year", "measurement_window_start",
                    "measurement_window_end", "uvb_total_cents", "uvb_pool_cents",
                    "all_employer_contributions_cents", "all_employer_cbu",
                    "interest_rate_bps", "certify_on_create_used", "status",
                    "certified_by_user_id", "certified_at",
                    "allocated_uvb_cents", "unallocated_uvb_cents",
                    "created_at", "updated_at", "version")


def valuation(row):
    data = _project(row, VALUATION_FIELDS)
    allocated, unallocated = valuation_allocation(row)
    data["allocated_uvb_cents"] = allocated
    data["unallocated_uvb_cents"] = unallocated
    return data


RECORD_FIELDS = ("id", "employer_id", "supersedes_record_id", "plan_year_start",
                 "plan_year_end", "contribution_base_units",
                 "contribution_amount_cents", "contribution_rate_cents_per_cbu",
                 "status", "employer_version_at_apply", "created_at",
                 "updated_at", "version")


def contribution_record(row):
    return _project(row, RECORD_FIELDS)


EVENT_FIELDS = ("id", "employer_id", "cessation_date", "withdrawal_plan_year",
                "reported_cause", "ceased_cba_count", "rules_variant",
                "determined_type", "high_base_year_average_cbu",
                "testing_period_average_cbu", "decline_ratio", "base_year_one",
                "base_year_two", "partial_withdrawal_fraction", "status",
                "determined_at", "created_at", "updated_at", "version")


def withdrawal_event(row):
    return _project(row, EVENT_FIELDS)


ASSESSMENT_FIELDS = ("id", "withdrawal_event_id", "valuation_id",
                     "allocation_method_applied", "de_minimis_variant_applied",
                     "interest_rate_bps_applied", "gross_allocated_cents",
                     "pool_term_breakdown", "de_minimis_reduction_cents",
                     "award_adjustment_cents", "net_assessed_cents",
                     "high_3yr_average_cbu", "high_3yr_window_start_year",
                     "peak_contribution_rate_cents_per_cbu",
                     "peak_rate_plan_year", "annual_payment_cents",
                     "lifecycle_status", "review_status", "collection_status",
                     "issued_at", "issued_by_user_id", "review_deadline_at",
                     "active_schedule_generation", "created_at", "updated_at",
                     "version")


def assessment(row):
    data = _project(row, ASSESSMENT_FIELDS)
    data["pool_term_breakdown"] = [dict(item) for item in row["pool_term_breakdown"]]
    return data


SCHEDULE_FIELDS = ("id", "liability_assessment_id", "generation_seq", "source",
                   "interest_rate_bps", "annual_payment_cents",
                   "applied_credit_cents", "amortization_basis_cents",
                   "forgiven_by_cap_cents", "capped_basis_cents",
                   "amortization_years", "installment_count",
                   "quarterly_installment_cents", "final_installment_cents",
                   "first_due_date", "consecutive_delinquent_count",
                   "default_notice_issued_at", "cure_deadline_at",
                   "accelerated_balance_cents", "refund_due_cents", "status",
                   "created_at", "updated_at", "version")


def payment_schedule(row):
    return _project(row, SCHEDULE_FIELDS)


INSTALLMENT_FIELDS = ("id", "payment_schedule_id", "sequence_number", "due_date",
                      "principal_cents", "amount_due_cents", "amount_paid_cents",
                      "delinquent_on", "paid_at", "status", "created_at",
                      "updated_at", "version")


def installment(row):
    return _project(row, INSTALLMENT_FIELDS)


REVIEW_FIELDS = ("id", "liability_assessment_id", "grounds_summary",
                 "challenged_assumption", "proposed_interest_rate_bps",
                 "filed_at", "filed_by_user_id", "plan_response_deadline_at",
                 "arbitration_deadline_at", "status", "decision",
                 "assumption_ruling", "recomputed_net_assessed_cents",
                 "decided_at", "decided_by_user_id", "created_at", "updated_at",
                 "version")


def review_request(row):
    return _project(row, REVIEW_FIELDS)


ARBITRATION_FIELDS = ("id", "liability_assessment_id", "review_request_id",
                      "initiated_at", "round_number", "status", "award_outcome",
                      "assumption_ruling", "awarded_net_assessed_cents",
                      "closed_at", "created_at", "updated_at", "version")


def arbitration(row):
    return _project(row, ARBITRATION_FIELDS)


TRANSACTION_FIELDS = ("id", "seller_employer_id", "buyer_controlled_group_id",
                      "closing_date", "closing_plan_year",
                      "purchase_price_cents", "bond_amount_cents",
                      "buyer_assumes_contribution_obligation",
                      "workforce_continuity_pct", "asset_continuity_pct",
                      "customer_continuity_pct", "required_bond_cents",
                      "substantial_continuity_score",
                      "bond_period_end_plan_year", "exemption_status",
                      "successor_determination", "status", "adjudicated_at",
                      "created_at", "updated_at", "version")


def transaction(row):
    return _project(row, TRANSACTION_FIELDS)

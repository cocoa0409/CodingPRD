"""Effective-dated jurisdiction rule versions (PRD 2.6)."""

import envelope
import listing
import serializers
from constants import ANNUAL_REPORT_BASES, FRANCHISE_TAX_BASES, GRACE_BASES, LATE_FEE_STYLES
from dispatch import endpoint, query_filter
from errors import ApiError
from services import rules
from store import DB, new_row, touch


@endpoint("POST", "/state-rules", roles=["PlatformAdmin"], success_code=201)
def publish_rule(context):
    body = context.body
    # ---- rung 13 ----------------------------------------------------------
    state_code = body.state_code("state_code", required=True)
    effective_from = body.date("effective_from", required=True)
    annual_report_basis = body.enum("annual_report_basis", ANNUAL_REPORT_BASES, required=True)
    franchise_tax_basis = body.enum("franchise_tax_basis", FRANCHISE_TAX_BASES, required=True)
    fixed_due_month = body.integer("fixed_due_month", default=1, minimum=1, maximum=12)
    fixed_due_day = body.integer("fixed_due_day", default=1, minimum=1, maximum=31)
    fiscal_offset_days = body.integer("fiscal_offset_days", default=0, minimum=0, maximum=365)
    flat_franchise_tax_cents = body.integer("flat_franchise_tax_cents", default=0, minimum=0)
    authorized_shares_tiers = body.bracket_list("authorized_shares_tiers", "up_to_shares", [])
    assumed_par_value_rate_bps = body.integer("assumed_par_value_rate_bps", default=0, minimum=0)
    min_franchise_tax_cents = body.integer("min_franchise_tax_cents", default=0, minimum=0)
    max_franchise_tax_cents = body.integer(
        "max_franchise_tax_cents", default=100000000, minimum=min_franchise_tax_cents
    )
    gross_receipts_brackets = body.bracket_list("gross_receipts_brackets", "up_to_cents", [])
    grace_days = body.integer("grace_days", default=0, minimum=0, maximum=120)
    grace_basis = body.enum("grace_basis", GRACE_BASES, default="CALENDAR_DAYS")
    late_fee_style = body.enum("late_fee_style", LATE_FEE_STYLES, default="FLAT")
    late_fee_flat_cents = body.integer("late_fee_flat_cents", default=0, minimum=0)
    late_fee_per_month_cents = body.integer("late_fee_per_month_cents", default=0, minimum=0)
    late_fee_percent_bps = body.integer("late_fee_percent_bps", default=0, minimum=0)
    late_fee_cap_cents = body.integer("late_fee_cap_cents", default=0, minimum=0)
    delinquency_to_dissolution_days = body.integer(
        "delinquency_to_dissolution_days", default=60, minimum=1, maximum=1095
    )
    reinstatement_window_days = body.integer(
        "reinstatement_window_days", default=365, minimum=1, maximum=3650
    )
    annual_report_fee_cents = body.integer("annual_report_fee_cents", default=0, minimum=0)
    franchise_tax_filing_fee_cents = body.integer(
        "franchise_tax_filing_fee_cents", default=0, minimum=0
    )
    foreign_qualification_fee_cents = body.integer(
        "foreign_qualification_fee_cents", default=0, minimum=0
    )
    withdrawal_fee_cents = body.integer("withdrawal_fee_cents", default=0, minimum=0)
    dissolution_fee_cents = body.integer("dissolution_fee_cents", default=0, minimum=0)
    reinstatement_fee_cents = body.integer("reinstatement_fee_cents", default=0, minimum=0)
    expedite_surcharge_cents = body.integer("expedite_surcharge_cents", default=0, minimum=0)
    good_standing_freshness_days = body.integer(
        "good_standing_freshness_days", default=30, minimum=1, maximum=365
    )
    requires_tax_clearance = body.boolean("requires_tax_clearance", default=False)

    # ---- rung 14 ----------------------------------------------------------
    body.check_enums()

    # ---- rung 19 ----------------------------------------------------------
    incumbent = rules.open_row(state_code)
    if incumbent is not None and effective_from <= incumbent["effective_from"]:
        raise ApiError("ERR_EFFECTIVE_DATE_OVERLAP")

    row = new_row(
        DB.state_rules,
        {
            "state_code": state_code,
            "effective_from": effective_from,
            "effective_to": None,
            "annual_report_basis": annual_report_basis,
            "fixed_due_month": fixed_due_month,
            "fixed_due_day": fixed_due_day,
            "fiscal_offset_days": fiscal_offset_days,
            "franchise_tax_basis": franchise_tax_basis,
            "flat_franchise_tax_cents": flat_franchise_tax_cents,
            "authorized_shares_tiers": authorized_shares_tiers,
            "assumed_par_value_rate_bps": assumed_par_value_rate_bps,
            "min_franchise_tax_cents": min_franchise_tax_cents,
            "max_franchise_tax_cents": max_franchise_tax_cents,
            "gross_receipts_brackets": gross_receipts_brackets,
            "grace_days": grace_days,
            "grace_basis": grace_basis,
            "late_fee_style": late_fee_style,
            "late_fee_flat_cents": late_fee_flat_cents,
            "late_fee_per_month_cents": late_fee_per_month_cents,
            "late_fee_percent_bps": late_fee_percent_bps,
            "late_fee_cap_cents": late_fee_cap_cents,
            "delinquency_to_dissolution_days": delinquency_to_dissolution_days,
            "reinstatement_window_days": reinstatement_window_days,
            "annual_report_fee_cents": annual_report_fee_cents,
            "franchise_tax_filing_fee_cents": franchise_tax_filing_fee_cents,
            "foreign_qualification_fee_cents": foreign_qualification_fee_cents,
            "withdrawal_fee_cents": withdrawal_fee_cents,
            "dissolution_fee_cents": dissolution_fee_cents,
            "reinstatement_fee_cents": reinstatement_fee_cents,
            "expedite_surcharge_cents": expedite_surcharge_cents,
            "good_standing_freshness_days": good_standing_freshness_days,
            "requires_tax_clearance": requires_tax_clearance,
        },
    )
    if incumbent is not None:
        incumbent["effective_to"] = effective_from
        touch(incumbent)
    return envelope.object_response(serializers.state_rule(row), 201)


@endpoint(
    "GET",
    "/state-rules",
    roles=["PlatformAdmin", "ComplianceOfficer", "FilingAgent"],
    success_code=200,
)
def list_rules(context):
    rows = list(DB.state_rules.values())
    state_code = query_filter("state_code")
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    # newest effective_from first; the more recently created row wins a tie
    rows.sort(key=lambda r: (r["effective_from"], r["_seq"]), reverse=True)
    return listing.respond(rows, serializers.state_rule, presorted=rows)

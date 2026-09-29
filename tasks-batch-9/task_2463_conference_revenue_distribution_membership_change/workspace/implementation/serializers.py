"""Entity representations.

Every field list below is the field list PRD section 1.1 declares for that
entity plus the housekeeping fields of PRD section 2.5.  Timestamps are rendered
as ISO 8601 UTC with three fractional digits.
"""

import clock

_INSTANT_FIELDS = frozenset(
    [
        "created_at",
        "updated_at",
        "withdrawal_notice_at",
        "posted_at",
        "game_date",
        "window_start",
        "window_end",
    ]
)

CONFERENCE_FIELDS = [
    "id",
    "name",
    "fiscal_year_start_month",
    "current_fiscal_year",
    "unit_value_cents",
    "phase_schedule_years",
    "governance_status",
    "approved_operating_expense_cents",
    "approved_governance_expense_cents",
    "reserve_target_cents",
    "reserve_balance_cents",
    "reserve_posture",
    "funded_ratio_bps",
    "escrow_balance_cents",
    "governance_fee_revenue_cents",
    "validated_postseason_unit_count",
    "created_at",
    "updated_at",
    "version",
]

MEMBER_FIELDS = [
    "id",
    "conference_id",
    "name",
    "institution_code",
    "admission_path",
    "status",
    "home_venue_id",
    "travel_partner_member_id",
    "primary_contact_email",
    "grant_of_rights_through_fiscal_year",
    "entry_fee_cents",
    "entry_fee_paid_cents",
    "phase_year",
    "distribution_phase_bps",
    "voting_weight_bps",
    "withdrawal_notice_at",
    "withdrawal_effective_fiscal_year",
    "notice_days",
    "last_full_annual_distribution_cents",
    "exit_settlement_total_cents",
    "exit_settlement_paid_cents",
    "schedule_compliance_score",
    "created_at",
    "updated_at",
    "version",
]

VENUE_FIELDS = [
    "id",
    "name",
    "city",
    "seating_capacity",
    "concurrent_event_capacity",
    "created_at",
    "updated_at",
    "version",
]

REVENUE_POOL_FIELDS = [
    "id",
    "conference_id",
    "fiscal_year",
    "pool_type",
    "allocation_method",
    "gross_revenue_cents",
    "estimated_expense_cents",
    "audited_expense_cents",
    "status",
    "created_at",
    "updated_at",
    "version",
]

DISTRIBUTION_RUN_FIELDS = [
    "id",
    "revenue_pool_id",
    "variant",
    "status",
    "net_pool_cents",
    "reserve_draw_cents",
    "distributable_cents",
    "total_weight_bps",
    "computed_by_user_id",
    "posted_by_user_id",
    "posted_at",
    "superseded_by_run_id",
    "created_at",
    "updated_at",
    "version",
]

DISTRIBUTION_LINE_FIELDS = [
    "id",
    "distribution_run_id",
    "member_id",
    "weight_bps",
    "gross_share_cents",
    "remainder_cent_awarded",
    "withheld_cents",
    "governance_fee_cents",
    "gor_offset_cents",
    "net_payable_cents",
    "status",
    "created_at",
]

BOWL_APPEARANCE_FIELDS = [
    "id",
    "member_id",
    "fiscal_year",
    "event_name",
    "event_tier",
    "payout_cents",
    "submitted_expense_cents",
    "travel_miles",
    "units_claimed",
    "allowable_expense_cents",
    "travel_allowance_cents",
    "reimbursement_ceiling_cents",
    "reimbursed_cents",
    "residual_to_pool_cents",
    "status",
    "revision_round",
    "created_at",
    "updated_at",
    "version",
]

POSTSEASON_UNIT_FIELDS = [
    "id",
    "bowl_appearance_id",
    "member_id",
    "fiscal_year",
    "unit_index",
    "status",
    "created_at",
]

MEMBERSHIP_ACTION_FIELDS = [
    "id",
    "conference_id",
    "member_id",
    "action_type",
    "effective_fiscal_year",
    "entry_fee_cents",
    "rationale",
    "status",
    "required_approval_bps",
    "quorum_weight_bps",
    "eligible_weight_bps",
    "cast_weight_bps",
    "for_weight_bps",
    "against_weight_bps",
    "quorum_met",
    "approval_ratio_bps",
    "proposed_by_user_id",
    "closed_by_user_id",
    "amend_count",
    "created_at",
    "updated_at",
    "version",
]

BALLOT_FIELDS = [
    "id",
    "membership_action_id",
    "budget_proposal_id",
    "member_id",
    "choice",
    "weight_bps",
    "status",
    "cast_by_user_id",
    "created_at",
]

BUDGET_PROPOSAL_FIELDS = [
    "id",
    "conference_id",
    "fiscal_year",
    "proposed_operating_expense_cents",
    "proposed_governance_expense_cents",
    "status",
    "required_approval_bps",
    "eligible_weight_bps",
    "cast_weight_bps",
    "for_weight_bps",
    "against_weight_bps",
    "quorum_met",
    "approval_ratio_bps",
    "prepared_by_user_id",
    "approved_by_user_id",
    "created_at",
    "updated_at",
    "version",
]

PROTECTED_RIVALRY_FIELDS = [
    "id",
    "conference_id",
    "member_a_id",
    "member_b_id",
    "required_annual_meetings",
    "label",
    "status",
    "created_at",
    "updated_at",
    "version",
]

SCHEDULE_GAME_FIELDS = [
    "id",
    "conference_id",
    "fiscal_year",
    "home_member_id",
    "away_member_id",
    "venue_id",
    "protected_rivalry_id",
    "game_date",
    "media_designated",
    "status",
    "created_at",
    "updated_at",
    "version",
]

CHAMPIONSHIP_EVENT_FIELDS = [
    "id",
    "conference_id",
    "venue_id",
    "host_member_id",
    "revenue_pool_id",
    "sport",
    "fiscal_year",
    "window_start",
    "window_end",
    "host_compliance_score_at_award",
    "ticket_revenue_cents",
    "sponsorship_revenue_cents",
    "event_expense_cents",
    "net_event_revenue_cents",
    "host_share_cents",
    "participant_pool_cents",
    "status",
    "created_at",
    "updated_at",
    "version",
]

AUDIT_REPORT_FIELDS = [
    "id",
    "conference_id",
    "distribution_run_id",
    "fiscal_year",
    "opinion",
    "note",
    "reconciliation_delta_cents",
    "status",
    "issued_by_user_id",
    "accepted_by_user_id",
    "created_at",
    "updated_at",
    "version",
]


def _project(record, fields):
    out = {}
    for field in fields:
        value = record.get(field)
        if field in _INSTANT_FIELDS and value is not None:
            value = clock.iso(value)
        out[field] = value
    return out


def conference(record):
    return _project(record, CONFERENCE_FIELDS)


def member(record):
    from services import compliance

    view = _project(record, MEMBER_FIELDS)
    # PRD section 3.4: the compliance score is a derived figure recomputed
    # whenever it is read.
    view["schedule_compliance_score"] = compliance.score(record)
    return view


def venue(record):
    return _project(record, VENUE_FIELDS)


def revenue_pool(record):
    return _project(record, REVENUE_POOL_FIELDS)


def distribution_run(record):
    return _project(record, DISTRIBUTION_RUN_FIELDS)


def distribution_line(record):
    return _project(record, DISTRIBUTION_LINE_FIELDS)


def bowl_appearance(record):
    return _project(record, BOWL_APPEARANCE_FIELDS)


def postseason_unit(record):
    return _project(record, POSTSEASON_UNIT_FIELDS)


def membership_action(record):
    return _project(record, MEMBERSHIP_ACTION_FIELDS)


def ballot(record):
    return _project(record, BALLOT_FIELDS)


def budget_proposal(record):
    return _project(record, BUDGET_PROPOSAL_FIELDS)


def protected_rivalry(record):
    return _project(record, PROTECTED_RIVALRY_FIELDS)


def schedule_game(record):
    return _project(record, SCHEDULE_GAME_FIELDS)


def championship_event(record):
    return _project(record, CHAMPIONSHIP_EVENT_FIELDS)


def audit_report(record):
    return _project(record, AUDIT_REPORT_FIELDS)

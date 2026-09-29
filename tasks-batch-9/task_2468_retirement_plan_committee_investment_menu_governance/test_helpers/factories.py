"""Endpoint paths and request-payload builders.

Each builder returns a plain dict with the PRD's field names, valid by default,
so a test can override exactly the one field it is exercising and leave the rest
alone.
"""

from typing import Any, Dict, List

from .constants import (
    DEFAULT_BLACKOUT_BUFFER_DAYS,
    DEFAULT_NOTICE_LEAD_DAYS_REQUIRED,
    DEFAULT_QUORUM_MIN_VOTING_MEMBERS,
    DEFAULT_VOTING_THRESHOLD_PCT,
)
from .types import (
    AssetClass,
    Construction,
    GlidepathType,
    JsonDict,
    LevelizationMethod,
    MappingStrategy,
    PlanType,
    ProviderRole,
    ScoringVariant,
    SeatClass,
    ShareClass,
    SlotDesignation,
    TallyBasis,
    TrainingModule,
)


class Paths:
    """Every endpoint path, so no test hard-codes a URL twice."""

    CLOCK = "/_clock/set_current_utc"

    PLANS = "/governance/plans"
    SEATS = "/governance/committee-seats"
    MEMBERS = "/governance/committee-members"
    TRAINING_RECORDS = "/governance/training-records"
    IPS = "/governance/investment-policy-statements"
    SLOTS = "/governance/asset-class-slots"
    FUNDS = "/governance/funds"
    REVIEWS = "/governance/quarterly-reviews"
    SCORECARDS = "/governance/fund-scorecards"
    MEETINGS = "/governance/committee-meetings"
    MOTIONS = "/governance/motions"
    REPLACEMENTS = "/governance/fund-replacements"
    LEVELIZATION_RUNS = "/governance/fee-levelization-runs"
    ENGAGEMENTS = "/governance/service-provider-engagements"

    # -- plan sub-resources ------------------------------------------------

    @staticmethod
    def plan(plan_id: str) -> str:
        return f"/governance/plans/{plan_id}"

    @staticmethod
    def charter_adopt(plan_id: str) -> str:
        return f"/governance/plans/{plan_id}/charter/adopt"

    @staticmethod
    def advance_quarter(plan_id: str) -> str:
        return f"/governance/plans/{plan_id}/advance-quarter"

    @staticmethod
    def recompute_posture(plan_id: str) -> str:
        return f"/governance/plans/{plan_id}/menu-posture/recompute"

    # -- committee ---------------------------------------------------------

    @staticmethod
    def seat(seat_id: str) -> str:
        return f"/governance/committee-seats/{seat_id}"

    @staticmethod
    def seat_status(seat_id: str) -> str:
        return f"/governance/committee-seats/{seat_id}/status"

    @staticmethod
    def member(member_id: str) -> str:
        return f"/governance/committee-members/{member_id}"

    @staticmethod
    def acceptance(member_id: str) -> str:
        return f"/governance/committee-members/{member_id}/acceptance"

    @staticmethod
    def activate(member_id: str) -> str:
        return f"/governance/committee-members/{member_id}/activate"

    @staticmethod
    def end_term(member_id: str) -> str:
        return f"/governance/committee-members/{member_id}/end-term"

    @staticmethod
    def training_record(record_id: str) -> str:
        return f"/governance/training-records/{record_id}"

    @staticmethod
    def training_complete(record_id: str) -> str:
        return f"/governance/training-records/{record_id}/complete"

    # -- policy statement, slots, funds ------------------------------------

    @staticmethod
    def ips(ips_id: str) -> str:
        return f"/governance/investment-policy-statements/{ips_id}"

    @staticmethod
    def ips_adopt(ips_id: str) -> str:
        return f"/governance/investment-policy-statements/{ips_id}/adopt"

    @staticmethod
    def slot(slot_id: str) -> str:
        return f"/governance/asset-class-slots/{slot_id}"

    @staticmethod
    def seat_fund(slot_id: str) -> str:
        return f"/governance/asset-class-slots/{slot_id}/seat-fund"

    @staticmethod
    def slot_retire(slot_id: str) -> str:
        return f"/governance/asset-class-slots/{slot_id}/retire"

    @staticmethod
    def fund(fund_id: str) -> str:
        return f"/governance/funds/{fund_id}"

    @staticmethod
    def share_class_change(fund_id: str) -> str:
        return f"/governance/funds/{fund_id}/share-class-change"

    @staticmethod
    def target_date_selection(fund_id: str) -> str:
        return f"/governance/funds/{fund_id}/target-date-selection"

    # -- reviews and scorecards --------------------------------------------

    @staticmethod
    def review(review_id: str) -> str:
        return f"/governance/quarterly-reviews/{review_id}"

    @staticmethod
    def review_present(review_id: str) -> str:
        return f"/governance/quarterly-reviews/{review_id}/present"

    @staticmethod
    def review_finalize(review_id: str) -> str:
        return f"/governance/quarterly-reviews/{review_id}/finalize"

    @staticmethod
    def review_reopen(review_id: str) -> str:
        return f"/governance/quarterly-reviews/{review_id}/reopen"

    @staticmethod
    def scorecard(scorecard_id: str) -> str:
        return f"/governance/fund-scorecards/{scorecard_id}"

    # -- meetings, motions, votes ------------------------------------------

    @staticmethod
    def meeting(meeting_id: str) -> str:
        return f"/governance/committee-meetings/{meeting_id}"

    @staticmethod
    def convene(meeting_id: str) -> str:
        return f"/governance/committee-meetings/{meeting_id}/convene"

    @staticmethod
    def adjourn(meeting_id: str) -> str:
        return f"/governance/committee-meetings/{meeting_id}/adjourn"

    @staticmethod
    def minutes_approve(meeting_id: str) -> str:
        return f"/governance/committee-meetings/{meeting_id}/minutes-approve"

    @staticmethod
    def motion(motion_id: str) -> str:
        return f"/governance/motions/{motion_id}"

    @staticmethod
    def votes(motion_id: str) -> str:
        return f"/governance/motions/{motion_id}/votes"

    @staticmethod
    def motion_close(motion_id: str) -> str:
        return f"/governance/motions/{motion_id}/close"

    # -- replacement proposals ---------------------------------------------

    @staticmethod
    def proposal(proposal_id: str) -> str:
        return f"/governance/fund-replacements/{proposal_id}"

    @staticmethod
    def proposal_submit(proposal_id: str) -> str:
        return f"/governance/fund-replacements/{proposal_id}/submit"

    @staticmethod
    def proposal_request_revision(proposal_id: str) -> str:
        return f"/governance/fund-replacements/{proposal_id}/request-revision"

    @staticmethod
    def proposal_revise(proposal_id: str) -> str:
        return f"/governance/fund-replacements/{proposal_id}/revise"

    @staticmethod
    def proposal_approve(proposal_id: str) -> str:
        return f"/governance/fund-replacements/{proposal_id}/approve"

    @staticmethod
    def proposal_rescind(proposal_id: str) -> str:
        return f"/governance/fund-replacements/{proposal_id}/rescind-approval"

    @staticmethod
    def proposal_notice_issue(proposal_id: str) -> str:
        return f"/governance/fund-replacements/{proposal_id}/notice-issue"

    @staticmethod
    def proposal_execute(proposal_id: str) -> str:
        return f"/governance/fund-replacements/{proposal_id}/execute"

    @staticmethod
    def proposal_unwind(proposal_id: str) -> str:
        return f"/governance/fund-replacements/{proposal_id}/unwind"

    # -- levelization ------------------------------------------------------

    @staticmethod
    def run(run_id: str) -> str:
        return f"/governance/fee-levelization-runs/{run_id}"

    @staticmethod
    def run_approve(run_id: str) -> str:
        return f"/governance/fee-levelization-runs/{run_id}/approve"

    @staticmethod
    def run_post(run_id: str) -> str:
        return f"/governance/fee-levelization-runs/{run_id}/post"

    @staticmethod
    def run_reverse(run_id: str) -> str:
        return f"/governance/fee-levelization-runs/{run_id}/reverse"

    @staticmethod
    def run_recompute(run_id: str) -> str:
        return f"/governance/fee-levelization-runs/{run_id}/recompute"

    # -- provider engagements ----------------------------------------------

    @staticmethod
    def engagement(engagement_id: str) -> str:
        return f"/governance/service-provider-engagements/{engagement_id}"

    @staticmethod
    def engagement_benchmark(engagement_id: str) -> str:
        return f"/governance/service-provider-engagements/{engagement_id}/benchmark"

    @staticmethod
    def engagement_rfp_award(engagement_id: str) -> str:
        return f"/governance/service-provider-engagements/{engagement_id}/rfp-award"

    @staticmethod
    def engagement_terminate(engagement_id: str) -> str:
        return f"/governance/service-provider-engagements/{engagement_id}/terminate"


def without(payload: JsonDict, *keys: str) -> JsonDict:
    """A copy of ``payload`` with ``keys`` removed, for tests that omit a field
    so the server's default — or its required-field check — is exercised."""
    return {k: v for k, v in payload.items() if k not in keys}


def _merge(payload: JsonDict, overrides: Dict[str, Any]) -> JsonDict:
    """Overrides win outright, including an explicit ``None`` meaning JSON null.
    Use :func:`without` to drop a key entirely."""
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Plan and charter
# --------------------------------------------------------------------------


def plan_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "plan_name": "Ridgeline Manufacturing 401(k) Plan",
            "plan_sponsor_name": "Ridgeline Manufacturing Inc.",
            "plan_type": PlanType.FOUR_01K,
            "erisa_covered": True,
            "participant_account_count": 1200,
            "menu_slot_capacity": 6,
            "quorum_min_voting_members": DEFAULT_QUORUM_MIN_VOTING_MEMBERS,
            "voting_threshold_pct": DEFAULT_VOTING_THRESHOLD_PCT,
            "max_voting_seats": 5,
            "notice_lead_days_required": DEFAULT_NOTICE_LEAD_DAYS_REQUIRED,
            "blackout_buffer_days": DEFAULT_BLACKOUT_BUFFER_DAYS,
        },
        overrides,
    )


def charter_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "quorum_min_voting_members": DEFAULT_QUORUM_MIN_VOTING_MEMBERS,
            "voting_threshold_pct": DEFAULT_VOTING_THRESHOLD_PCT,
            "max_voting_seats": 5,
            "charter_doc_ref": "CHARTER-2026-A",
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Seats, members, training
# --------------------------------------------------------------------------


def seat_payload(plan_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "plan_id": plan_id,
            "seat_code": "S-CHAIR",
            "seat_class": SeatClass.CHAIR,
            "voting": True,
            "seat_index": 1,
        },
        overrides,
    )


def member_payload(seat_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "seat_id": seat_id,
            "member_name": "Dana Okonjo",
            "person_email": "dana.okonjo@example.com",
            "term_start_date": "2026-01-01",
            "term_end_date": "2027-12-31",
            "affiliated_provider_role": ProviderRole.NONE,
        },
        overrides,
    )


def acceptance_payload(**overrides: Any) -> JsonDict:
    return _merge({"acceptance_doc_ref": "ACC-2026-001"}, overrides)


def training_payload(member_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "member_id": member_id,
            "module_code": TrainingModule.FIDUCIARY_DUTIES,
            "validity_quarters": 8,
        },
        overrides,
    )


def waived_training_payload(member_id: str, module_code: str, **overrides: Any) -> JsonDict:
    """A record created straight into ``WAIVED``; the basis must clear the
    12-character floor."""
    return _merge(
        {
            "member_id": member_id,
            "module_code": module_code,
            "status": "WAIVED",
            "waiver_basis": "Prior equivalent counsel training on file",
            "validity_quarters": 8,
        },
        overrides,
    )


def training_completion_payload(score_pct: Any = 95.00, **overrides: Any) -> JsonDict:
    return _merge({"action": "COMPLETED", "score_pct": score_pct}, overrides)


def training_waiver_payload(**overrides: Any) -> JsonDict:
    return _merge(
        {
            "action": "WAIVED",
            "waiver_basis": "Prior equivalent counsel training on file",
        },
        overrides,
    )


def end_term_payload(reason: str = "RESIGNATION", **overrides: Any) -> JsonDict:
    return _merge({"end_term_reason": reason}, overrides)


def seat_status_payload(action: str, **overrides: Any) -> JsonDict:
    return _merge({"action": action}, overrides)


# --------------------------------------------------------------------------
# Investment policy statement
# --------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "performance": 0.40,
    "peer": 0.20,
    "expense": 0.20,
    "style": 0.10,
    "manager": 0.10,
}

DEFAULT_BENCHMARK_MAP = {
    AssetClass.US_LARGE_CAP: "RUSSELL_1000_GROWTH",
    AssetClass.CORE_BOND: "BLOOMBERG_AGG",
    AssetClass.US_SMALL_CAP: "RUSSELL_2000_VALUE",
    AssetClass.INTL_DEVELOPED: "MSCI_EAFE",
    AssetClass.TIPS: "BLOOMBERG_US_TIPS",
    AssetClass.TARGET_DATE: "SP_TARGET_DATE_THROUGH",
}


def ips_payload(plan_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "plan_id": plan_id,
            "version_label": "IPS-2026-A",
            "effective_date": "2026-08-01",
            "scoring_variant": ScoringVariant.TRAILING_PERIOD,
            "watch_trigger_score_max": 40.00,
            "remediation_trigger_score_max": 25.00,
            "cure_margin_points": 10.00,
            "expense_peer_multiple": 1.25,
            "min_track_record_quarters": 12,
            "style_drift_r2_floor": 0.8000,
            "watch_grace_quarters": 2,
            "weights": dict(DEFAULT_WEIGHTS),
            "benchmark_map": dict(DEFAULT_BENCHMARK_MAP),
        },
        overrides,
    )


def ips_adopt_payload(approving_motion_id: str, **overrides: Any) -> JsonDict:
    return _merge({"approving_motion_id": approving_motion_id}, overrides)


# --------------------------------------------------------------------------
# Slots and funds
# --------------------------------------------------------------------------


def slot_payload(plan_id: str, ips_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "plan_id": plan_id,
            "ips_id": ips_id,
            "asset_class_code": AssetClass.US_LARGE_CAP,
            "designation": SlotDesignation.CORE,
            "slot_index": 1,
        },
        overrides,
    )


def fund_payload(plan_id: str, **overrides: Any) -> JsonDict:
    """A candidate fund that satisfies every default selection criterion."""
    return _merge(
        {
            "plan_id": plan_id,
            "ticker": "LCGRA",
            "fund_name": "Ridgeline Large Cap Growth R6",
            "asset_class_code": AssetClass.US_LARGE_CAP,
            "share_class_code": ShareClass.R6,
            "gross_expense_ratio_bps": 45,
            "net_expense_ratio_bps": 45,
            "revenue_share_bps": 10,
            "peer_median_expense_bps": 40,
            "track_record_quarters": 40,
            "manager_tenure_quarters": 20,
            "manager_change_flag": False,
            "style_drift_r2": 0.9200,
            "plan_assets_cents": 800000000,
        },
        overrides,
    )


def target_date_fund_payload(plan_id: str, **overrides: Any) -> JsonDict:
    """A target-date suite fund, carrying the four glidepath fields."""
    return _merge(
        fund_payload(
            plan_id,
            ticker="TDTHR",
            fund_name="Ridgeline Target Retirement Suite",
            asset_class_code=AssetClass.TARGET_DATE,
            net_expense_ratio_bps=45,
            gross_expense_ratio_bps=45,
            revenue_share_bps=0,
            peer_median_expense_bps=40,
            track_record_quarters=40,
            manager_tenure_quarters=24,
            style_drift_r2=0.9000,
            plan_assets_cents=0,
        ),
        _merge(
            {
                "is_target_date_suite": True,
                "glidepath_type": GlidepathType.THROUGH_RETIREMENT,
                "construction": Construction.CUSTOM,
                "equity_at_65_pct": 50.00,
                "landing_point_age": 80,
            },
            overrides,
        ),
    )


def seat_fund_payload(fund_id: str, **overrides: Any) -> JsonDict:
    return _merge({"fund_id": fund_id}, overrides)


def share_class_change_payload(
    share_class_code: str, net_expense_ratio_bps: int, revenue_share_bps: int, **overrides: Any
) -> JsonDict:
    return _merge(
        {
            "share_class_code": share_class_code,
            "net_expense_ratio_bps": net_expense_ratio_bps,
            "revenue_share_bps": revenue_share_bps,
        },
        overrides,
    )


def target_date_selection_payload(
    approving_motion_id: str,
    glidepath_type: str = GlidepathType.THROUGH_RETIREMENT,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {"approving_motion_id": approving_motion_id, "glidepath_type": glidepath_type},
        overrides,
    )


# --------------------------------------------------------------------------
# Meetings, motions and votes
# --------------------------------------------------------------------------


def meeting_payload(plan_id: str, meeting_date: str, quarter_index: int = 0, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "plan_id": plan_id,
            "meeting_date": meeting_date,
            "quarter_index": quarter_index,
        },
        overrides,
    )


def convene_payload(attendee_member_ids: List[str], **overrides: Any) -> JsonDict:
    return _merge({"attendee_member_ids": list(attendee_member_ids)}, overrides)


def minutes_payload(minutes_doc_ref: str = "MIN-2026-Q0-001", **overrides: Any) -> JsonDict:
    return _merge({"minutes_doc_ref": minutes_doc_ref}, overrides)


def motion_payload(
    meeting_id: str,
    subject_type: str,
    subject_id: str,
    tally_basis: str = TallyBasis.VOTES_CAST,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "meeting_id": meeting_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "tally_basis": tally_basis,
        },
        overrides,
    )


def vote_payload(member_id: str, vote: str = "FOR", **overrides: Any) -> JsonDict:
    return _merge({"member_id": member_id, "vote": vote}, overrides)


# --------------------------------------------------------------------------
# Reviews and scorecards
# --------------------------------------------------------------------------


def review_payload(plan_id: str, quarter_index: int = 0, **overrides: Any) -> JsonDict:
    return _merge({"plan_id": plan_id, "quarter_index": quarter_index}, overrides)


def scorecard_payload(
    review_id: str, fund_id: str, expected_review_version: int, **overrides: Any
) -> JsonDict:
    """A clean scorecard: 80 basis points of excess return, a top-quartile peer
    rank, expense at the peer median and no manager change."""
    return _merge(
        {
            "review_id": review_id,
            "fund_id": fund_id,
            "expected_review_version": expected_review_version,
            "trailing_return_3y_bps": 900,
            "trailing_return_5y_bps": 800,
            "benchmark_return_3y_bps": 820,
            "benchmark_return_5y_bps": 720,
            "peer_rank_pct": 25,
            "style_drift_r2": 0.9200,
            "net_expense_ratio_bps": 45,
            "peer_median_expense_bps": 40,
            "manager_tenure_quarters": 20,
            "manager_change_flag": False,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Fund replacement proposals
# --------------------------------------------------------------------------

#: Long enough to clear the 40-character floor submission imposes.
DEFAULT_RATIONALE = (
    "Cheaper share class with a materially better peer rank and a longer "
    "manager tenure than the incumbent."
)


def proposal_payload(
    plan_id: str,
    slot_id: str,
    outgoing_fund_id: str,
    incoming_fund_id: str,
    expected_plan_version: int,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {
            "plan_id": plan_id,
            "slot_id": slot_id,
            "outgoing_fund_id": outgoing_fund_id,
            "incoming_fund_id": incoming_fund_id,
            "rationale": DEFAULT_RATIONALE,
            "mapping_strategy": MappingStrategy.DIRECT_MAP,
            "expected_plan_version": expected_plan_version,
        },
        overrides,
    )


def revise_payload(**overrides: Any) -> JsonDict:
    """A revision may optionally change the incoming fund or the strategy."""
    return _merge({}, overrides)


def approve_proposal_payload(approving_motion_id: str, **overrides: Any) -> JsonDict:
    return _merge({"approving_motion_id": approving_motion_id}, overrides)


def notice_issue_payload(
    blackout_start_at: str = "2026-09-01T00:00:00Z",
    blackout_end_at: str = "2026-09-15T00:00:00Z",
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {"blackout_start_at": blackout_start_at, "blackout_end_at": blackout_end_at},
        overrides,
    )


# --------------------------------------------------------------------------
# Fee levelization
# --------------------------------------------------------------------------


def levelization_payload(
    plan_id: str,
    quarter_index: int = 0,
    method: str = LevelizationMethod.PER_CAPITA,
    **overrides: Any,
) -> JsonDict:
    return _merge(
        {"plan_id": plan_id, "quarter_index": quarter_index, "method": method},
        overrides,
    )


def approve_run_payload(approving_motion_id: str, **overrides: Any) -> JsonDict:
    return _merge({"approving_motion_id": approving_motion_id}, overrides)


# --------------------------------------------------------------------------
# Provider engagements
# --------------------------------------------------------------------------


def engagement_payload(plan_id: str, **overrides: Any) -> JsonDict:
    return _merge(
        {
            "plan_id": plan_id,
            "provider_name": "Northwind Recordkeeping LLC",
            "provider_role": ProviderRole.RECORDKEEPER,
            "term_start_date": "2026-01-01",
            "term_end_date": "2027-12-31",
            "per_head_fee_cents": 4200,
            "asset_based_bps": 8,
            "benchmark_percentile": 50,
            "last_rfp_quarter_index": 0,
        },
        overrides,
    )


def rfp_award_payload(
    approving_motion_id: str, successor_engagement_id: str, **overrides: Any
) -> JsonDict:
    return _merge(
        {
            "approving_motion_id": approving_motion_id,
            "successor_engagement_id": successor_engagement_id,
        },
        overrides,
    )


__all__ = [
    "Paths",
    "without",
    "DEFAULT_WEIGHTS",
    "DEFAULT_BENCHMARK_MAP",
    "DEFAULT_RATIONALE",
    "plan_payload",
    "charter_payload",
    "seat_payload",
    "member_payload",
    "acceptance_payload",
    "training_payload",
    "waived_training_payload",
    "training_completion_payload",
    "training_waiver_payload",
    "end_term_payload",
    "seat_status_payload",
    "ips_payload",
    "ips_adopt_payload",
    "slot_payload",
    "fund_payload",
    "target_date_fund_payload",
    "seat_fund_payload",
    "share_class_change_payload",
    "target_date_selection_payload",
    "meeting_payload",
    "convene_payload",
    "minutes_payload",
    "motion_payload",
    "vote_payload",
    "review_payload",
    "scorecard_payload",
    "proposal_payload",
    "revise_payload",
    "approve_proposal_payload",
    "notice_issue_payload",
    "levelization_payload",
    "approve_run_payload",
    "engagement_payload",
    "rfp_award_payload",
]

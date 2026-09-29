"""Scenario builders.

Every test starts against an empty database, so every precondition has to be
built through the documented endpoints.  The builders below are layered: each
one calls the layer beneath it and returns a :class:`Ctx` carrying the
identifiers a test needs.

Nothing here asserts behaviour under test — a failure inside a builder means the
precondition could not be established, which surfaces as a plain
``AssertionError`` from ``get_success_data``.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .factories import (
    Paths,
    acceptance_payload,
    charter_payload,
    convene_payload,
    engagement_payload,
    fund_payload,
    ips_adopt_payload,
    ips_payload,
    levelization_payload,
    meeting_payload,
    member_payload,
    minutes_payload,
    motion_payload,
    notice_issue_payload,
    plan_payload,
    proposal_payload,
    review_payload,
    scorecard_payload,
    seat_fund_payload,
    seat_payload,
    slot_payload,
    target_date_fund_payload,
    training_completion_payload,
    training_payload,
    vote_payload,
)
from .test_users import (
    chair_headers,
    consultant_headers,
    member_headers,
    recordkeeper_headers,
    sponsor_headers,
)
from .types import (
    AssetClass,
    JsonDict,
    MotionSubjectType,
    SeatClass,
    SlotDesignation,
    TallyBasis,
    TrainingModule,
    Vote,
)


class Ctx:
    """A mutable bag of identifiers produced by the builders."""

    def __init__(self, client: ApiClient) -> None:
        self.client = client
        self.plan: JsonDict = {}
        self.seats: Dict[str, JsonDict] = {}
        self.members: Dict[str, JsonDict] = {}
        self.ips: JsonDict = {}
        self.slots: Dict[str, JsonDict] = {}
        self.funds: Dict[str, JsonDict] = {}
        self.meetings: Dict[str, JsonDict] = {}
        self.motions: Dict[str, JsonDict] = {}
        self.review: JsonDict = {}
        self.scorecards: Dict[str, JsonDict] = {}
        self.proposals: Dict[str, JsonDict] = {}
        self.runs: Dict[str, JsonDict] = {}
        self.engagements: Dict[str, JsonDict] = {}

    # -- shorthands --------------------------------------------------------

    @property
    def plan_id(self) -> str:
        return self.plan["id"]

    @property
    def ips_id(self) -> str:
        return self.ips["id"]

    @property
    def chair_id(self) -> str:
        return self.members["chair"]["id"]

    @property
    def chair(self) -> Dict[str, str]:
        return chair_headers(self.chair_id)

    @property
    def member_ids(self) -> List[str]:
        return [self.members[key]["id"] for key in ("chair", "finance", "hr")]

    def fund(self, key: str) -> JsonDict:
        return self.funds[key]

    def slot(self, key: str) -> JsonDict:
        return self.slots[key]

    def refresh_plan(self) -> JsonDict:
        self.plan = read_plan(self.client, self.plan_id)
        return self.plan

    @property
    def plan_version(self) -> int:
        return self.refresh_plan()["version"]


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def read_plan(client: ApiClient, plan_id: str) -> JsonDict:
    return get_success_data(client.get(Paths.plan(plan_id), sponsor_headers()))


def read_slot(client: ApiClient, slot_id: str) -> JsonDict:
    return get_success_data(client.get(Paths.slot(slot_id), sponsor_headers()))


def read_fund(client: ApiClient, fund_id: str) -> JsonDict:
    return get_success_data(client.get(Paths.fund(fund_id), sponsor_headers()))


def read_member(client: ApiClient, member_id: str) -> JsonDict:
    return get_success_data(client.get(Paths.member(member_id), sponsor_headers()))


def read_review(client: ApiClient, review_id: str) -> JsonDict:
    return get_success_data(client.get(Paths.review(review_id), sponsor_headers()))


def read_motion(client: ApiClient, motion_id: str) -> JsonDict:
    return get_success_data(client.get(Paths.motion(motion_id), sponsor_headers()))


def read_meeting(client: ApiClient, meeting_id: str) -> JsonDict:
    return get_success_data(client.get(Paths.meeting(meeting_id), sponsor_headers()))


def read_proposal(client: ApiClient, proposal_id: str) -> JsonDict:
    return get_success_data(client.get(Paths.proposal(proposal_id), sponsor_headers()))


def read_run(client: ApiClient, run_id: str) -> JsonDict:
    return get_success_data(client.get(Paths.run(run_id), sponsor_headers()))


def read_engagement(client: ApiClient, engagement_id: str) -> JsonDict:
    return get_success_data(client.get(Paths.engagement(engagement_id), sponsor_headers()))


def review_version(client: ApiClient, review_id: str) -> int:
    return read_review(client, review_id)["version"]


def plan_version(client: ApiClient, plan_id: str) -> int:
    return read_plan(client, plan_id)["version"]


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------


def register_plan(client: ApiClient, **overrides: Any) -> JsonDict:
    return get_success_data(
        client.post(Paths.PLANS, plan_payload(**overrides), sponsor_headers()), 201
    )


def create_seat(client: ApiClient, plan_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        client.post(Paths.SEATS, seat_payload(plan_id, **overrides), sponsor_headers()), 201
    )


def appoint_member(client: ApiClient, seat_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        client.post(Paths.MEMBERS, member_payload(seat_id, **overrides), sponsor_headers()),
        201,
    )


def assign_training(client: ApiClient, member_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        client.post(
            Paths.TRAINING_RECORDS, training_payload(member_id, **overrides), sponsor_headers()
        ),
        201,
    )


def complete_training(
    client: ApiClient, record_id: str, member_id: str, score_pct: Any = 95.00
) -> JsonDict:
    """A completion is the member's own act, so it is signed with the member's
    identity."""
    return get_success_data(
        client.post(
            Paths.training_complete(record_id),
            training_completion_payload(score_pct),
            member_headers(member_id),
        )
    )


def sign_acceptance(client: ApiClient, member_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        client.post(
            Paths.acceptance(member_id),
            acceptance_payload(**overrides),
            member_headers(member_id),
        )
    )


def activate_member(client: ApiClient, member_id: str) -> JsonDict:
    return get_success_data(
        client.post(Paths.activate(member_id), {}, sponsor_headers())
    )


def make_member_ready(
    client: ApiClient, member_id: str, score_pct: Any = 95.00
) -> JsonDict:
    """Clear both required training modules and sign the acceptance, leaving the
    member one call away from ``ACTIVE``."""
    for module in TrainingModule.REQUIRED:
        record = assign_training(client, member_id, module_code=module)
        complete_training(client, record["id"], member_id, score_pct)
    sign_acceptance(client, member_id)
    return read_member(client, member_id)


def make_member_active(
    client: ApiClient, member_id: str, score_pct: Any = 95.00
) -> JsonDict:
    make_member_ready(client, member_id, score_pct)
    return activate_member(client, member_id)


# --------------------------------------------------------------------------
# Layer 1: a plan with three activated committee members
# --------------------------------------------------------------------------

#: The three seats every scenario uses: a voting chair, finance and HR seat.
SEAT_SPECS = (
    ("chair", {"seat_code": "S-CHAIR", "seat_class": SeatClass.CHAIR, "seat_index": 1}),
    ("finance", {"seat_code": "S-FIN", "seat_class": SeatClass.FINANCE, "seat_index": 2}),
    ("hr", {"seat_code": "S-HR", "seat_class": SeatClass.HR, "seat_index": 3}),
)

#: The HR member is affiliated with the plan's recordkeeper, so their
#: ``independence_flag`` is false and they must recuse on fee levelization.
MEMBER_SPECS = {
    "chair": {
        "member_name": "Dana Okonjo",
        "person_email": "dana.okonjo@example.com",
        "score_pct": 95.00,
    },
    "finance": {
        "member_name": "Ivan Serrano",
        "person_email": "ivan.serrano@example.com",
        "score_pct": 91.00,
    },
    "hr": {
        "member_name": "Rosa Lindqvist",
        "person_email": "rosa.lindqvist@example.com",
        "affiliated_provider_role": "RECORDKEEPER",
        "score_pct": 88.00,
    },
}


def setup_committee(client: ApiClient, **plan_overrides: Any) -> Ctx:
    """A registered plan with three filled, voting, activated seats."""
    ctx = Ctx(client)
    ctx.plan = register_plan(client, **plan_overrides)
    for key, seat_spec in SEAT_SPECS:
        ctx.seats[key] = create_seat(client, ctx.plan_id, voting=True, **seat_spec)
        spec = dict(MEMBER_SPECS[key])
        score = spec.pop("score_pct")
        ctx.members[key] = appoint_member(client, ctx.seats[key]["id"], **spec)
        make_member_active(client, ctx.members[key]["id"], score)
    ctx.refresh_plan()
    return ctx


def adopt_charter(client: ApiClient, plan_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        client.post(Paths.charter_adopt(plan_id), charter_payload(**overrides), sponsor_headers())
    )


def setup_governed_plan(client: ApiClient, **plan_overrides: Any) -> Ctx:
    """A plan whose charter is ADOPTED, with a quorate committee in place."""
    ctx = setup_committee(client, **plan_overrides)
    ctx.plan = adopt_charter(client, ctx.plan_id)
    return ctx


# --------------------------------------------------------------------------
# Meetings, motions and the documentation gate
# --------------------------------------------------------------------------


def schedule_meeting(
    ctx: Ctx, meeting_date: str, quarter_index: int = 0, key: Optional[str] = None
) -> JsonDict:
    meeting = get_success_data(
        ctx.client.post(
            Paths.MEETINGS,
            meeting_payload(ctx.plan_id, meeting_date, quarter_index),
            sponsor_headers(),
        ),
        201,
    )
    if key:
        ctx.meetings[key] = meeting
    return meeting


def convene(ctx: Ctx, meeting_id: str, attendees: Optional[List[str]] = None) -> JsonDict:
    return get_success_data(
        ctx.client.post(
            Paths.convene(meeting_id),
            convene_payload(attendees if attendees is not None else ctx.member_ids),
            ctx.chair,
        )
    )


def open_meeting(
    ctx: Ctx,
    meeting_date: str,
    quarter_index: int = 0,
    key: Optional[str] = None,
    attendees: Optional[List[str]] = None,
) -> JsonDict:
    """Schedule and convene in one step, returning the convened meeting."""
    meeting = schedule_meeting(ctx, meeting_date, quarter_index, key)
    convened = convene(ctx, meeting["id"], attendees)
    if key:
        ctx.meetings[key] = convened
    return convened


def move_motion(
    ctx: Ctx,
    meeting_id: str,
    subject_type: str,
    subject_id: str,
    tally_basis: str = TallyBasis.VOTES_CAST,
    key: Optional[str] = None,
) -> JsonDict:
    motion = get_success_data(
        ctx.client.post(
            Paths.MOTIONS,
            motion_payload(meeting_id, subject_type, subject_id, tally_basis),
            ctx.chair,
        ),
        201,
    )
    if key:
        ctx.motions[key] = motion
    return motion


def cast_vote(ctx: Ctx, motion_id: str, member_id: str, vote: str = Vote.FOR, **extra: Any) -> JsonDict:
    role_headers = ctx.chair if member_id == ctx.chair_id else member_headers(member_id)
    return get_success_data(
        ctx.client.post(
            Paths.votes(motion_id), vote_payload(member_id, vote, **extra), role_headers
        )
    )


def close_motion(ctx: Ctx, motion_id: str) -> JsonDict:
    return get_success_data(ctx.client.post(Paths.motion_close(motion_id), {}, ctx.chair))


def adjourn(ctx: Ctx, meeting_id: str) -> JsonDict:
    return get_success_data(ctx.client.post(Paths.adjourn(meeting_id), {}, ctx.chair))


def approve_minutes(ctx: Ctx, meeting_id: str, minutes_doc_ref: str) -> JsonDict:
    return get_success_data(
        ctx.client.post(
            Paths.minutes_approve(meeting_id), minutes_payload(minutes_doc_ref), ctx.chair
        )
    )


def carry_motion_unanimously(
    ctx: Ctx,
    meeting_id: str,
    subject_type: str,
    subject_id: str,
    voters: Optional[List[str]] = None,
    tally_basis: str = TallyBasis.VOTES_CAST,
    key: Optional[str] = None,
) -> JsonDict:
    """Move a motion, vote it FOR by every listed member, and close it.  Every
    vote FOR puts ``support_pct`` at 100.0000, which carries under either
    tally basis."""
    motion = move_motion(ctx, meeting_id, subject_type, subject_id, tally_basis, key)
    for member_id in voters if voters is not None else ctx.member_ids:
        cast_vote(ctx, motion["id"], member_id, Vote.FOR)
    closed = close_motion(ctx, motion["id"])
    if key:
        ctx.motions[key] = closed
    return closed


def hold_meeting_and_carry_motion(
    ctx: Ctx,
    subject_type: str,
    subject_id: str,
    meeting_date: str,
    minutes_doc_ref: str,
    quarter_index: int = 0,
    voters: Optional[List[str]] = None,
    tally_basis: str = TallyBasis.VOTES_CAST,
    key: Optional[str] = None,
) -> JsonDict:
    """A whole authorising cycle: schedule, convene, move, vote FOR, close,
    adjourn and approve the minutes.  Returns the carried motion."""
    meeting = open_meeting(ctx, meeting_date, quarter_index, key=f"{key}_meeting" if key else None)
    motion = carry_motion_unanimously(
        ctx, meeting["id"], subject_type, subject_id, voters, tally_basis, key
    )
    adjourn(ctx, meeting["id"])
    approve_minutes(ctx, meeting["id"], minutes_doc_ref)
    return motion


# --------------------------------------------------------------------------
# Layer 2: an adopted policy statement
# --------------------------------------------------------------------------


def draft_ips(client: ApiClient, plan_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        client.post(Paths.IPS, ips_payload(plan_id, **overrides), consultant_headers()), 201
    )


def recompute_posture(ctx: Ctx) -> JsonDict:
    ctx.plan = get_success_data(
        ctx.client.post(Paths.recompute_posture(ctx.plan_id), {}, sponsor_headers())
    )
    return ctx.plan


def adopt_ips(ctx: Ctx, ips_id: str, approving_motion_id: str) -> JsonDict:
    return get_success_data(
        ctx.client.post(
            Paths.ips_adopt(ips_id), ips_adopt_payload(approving_motion_id), ctx.chair
        )
    )


def setup_adopted_ips(client: ApiClient, ips_overrides: Optional[Dict[str, Any]] = None, **plan_overrides: Any) -> Ctx:
    """A governed plan carrying one ADOPTED statement, IPS-2026-A, and an OPEN
    menu posture."""
    ctx = setup_governed_plan(client, **plan_overrides)
    ctx.ips = draft_ips(client, ctx.plan_id, **(ips_overrides or {}))
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.IPS_ADOPTION,
        ctx.ips_id,
        meeting_date="2026-08-03",
        minutes_doc_ref="MIN-2026-Q0-001",
        key="ips",
    )
    ctx.ips = adopt_ips(ctx, ctx.ips_id, motion["id"])
    recompute_posture(ctx)
    return ctx


# --------------------------------------------------------------------------
# Layer 3: the fund universe and the seated menu
# --------------------------------------------------------------------------

#: The candidate universe every menu scenario draws on.  Each entry satisfies
#: the default selection criteria unless a test overrides it.
FUND_SPECS: Dict[str, Dict[str, Any]] = {
    "lc_a": {
        "ticker": "LCGRA",
        "fund_name": "Anchor Large Cap Growth R6",
        "asset_class_code": AssetClass.US_LARGE_CAP,
        "share_class_code": "R6",
        "gross_expense_ratio_bps": 45,
        "net_expense_ratio_bps": 45,
        "revenue_share_bps": 10,
        "peer_median_expense_bps": 40,
        "track_record_quarters": 40,
        "manager_tenure_quarters": 20,
        "style_drift_r2": 0.9200,
        "plan_assets_cents": 800000000,
    },
    "bond": {
        "ticker": "BNDIX",
        "fund_name": "Beacon Core Bond Institutional",
        "asset_class_code": AssetClass.CORE_BOND,
        "share_class_code": "INSTITUTIONAL",
        "gross_expense_ratio_bps": 25,
        "net_expense_ratio_bps": 25,
        "revenue_share_bps": 5,
        "peer_median_expense_bps": 30,
        "track_record_quarters": 60,
        "manager_tenure_quarters": 30,
        "style_drift_r2": 0.9500,
        "plan_assets_cents": 400000000,
    },
    "small": {
        "ticker": "SMLVX",
        "fund_name": "Summit Small Cap Value R6",
        "asset_class_code": AssetClass.US_SMALL_CAP,
        "share_class_code": "R6",
        "gross_expense_ratio_bps": 60,
        "net_expense_ratio_bps": 60,
        "revenue_share_bps": 10,
        "peer_median_expense_bps": 55,
        "track_record_quarters": 28,
        "manager_tenure_quarters": 14,
        "style_drift_r2": 0.8800,
        "plan_assets_cents": 0,
    },
    "intl": {
        "ticker": "INTDX",
        "fund_name": "Iris International Developed Institutional",
        "asset_class_code": AssetClass.INTL_DEVELOPED,
        "share_class_code": "INSTITUTIONAL",
        "gross_expense_ratio_bps": 32,
        "net_expense_ratio_bps": 32,
        "revenue_share_bps": 0,
        "peer_median_expense_bps": 35,
        "track_record_quarters": 44,
        "manager_tenure_quarters": 26,
        "style_drift_r2": 0.9100,
        "plan_assets_cents": 0,
    },
    "tips": {
        "ticker": "TIPSX",
        "fund_name": "Terrace Inflation Protected Institutional",
        "asset_class_code": AssetClass.TIPS,
        "share_class_code": "INSTITUTIONAL",
        "gross_expense_ratio_bps": 12,
        "net_expense_ratio_bps": 12,
        "revenue_share_bps": 0,
        "peer_median_expense_bps": 15,
        "track_record_quarters": 52,
        "manager_tenure_quarters": 36,
        "style_drift_r2": 0.9600,
        "plan_assets_cents": 0,
    },
    "lc_b": {
        "ticker": "LCGRB",
        "fund_name": "Bluff Large Cap Growth R6",
        "asset_class_code": AssetClass.US_LARGE_CAP,
        "share_class_code": "R6",
        "gross_expense_ratio_bps": 38,
        "net_expense_ratio_bps": 38,
        "revenue_share_bps": 8,
        "peer_median_expense_bps": 40,
        "track_record_quarters": 32,
        "manager_tenure_quarters": 16,
        "style_drift_r2": 0.9400,
        "plan_assets_cents": 0,
    },
}

#: A perfect-fit THROUGH_RETIREMENT suite: 100.00 on the glidepath scale.
TARGET_DATE_SPECS: Dict[str, Dict[str, Any]] = {
    "td_thru": {"ticker": "TDTHR", "fund_name": "Trellis Target Retirement Suite"},
    "td_tie": {"ticker": "TDTIE", "fund_name": "Tiebreak Custom Through 2065 Suite"},
    "td_cheap": {
        "ticker": "TDCHP",
        "fund_name": "Newborn Cheap Through 2065 Suite",
        "gross_expense_ratio_bps": 20,
        "net_expense_ratio_bps": 20,
        "track_record_quarters": 11,
        "manager_tenure_quarters": 8,
    },
    "td_off_shelf": {
        "ticker": "TDLOW",
        "fund_name": "Offshelf Through 2065 Suite",
        "construction": "OFF_THE_SHELF",
    },
}

#: The five CORE slots, in menu order.
SLOT_SPECS = (
    ("lc", AssetClass.US_LARGE_CAP, 1),
    ("bond", AssetClass.CORE_BOND, 2),
    ("small", AssetClass.US_SMALL_CAP, 3),
    ("intl", AssetClass.INTL_DEVELOPED, 4),
    ("tips", AssetClass.TIPS, 5),
)

#: Which fund sits in which slot once the menu is seated.
SLOT_TO_FUND = {"lc": "lc_a", "bond": "bond", "small": "small", "intl": "intl", "tips": "tips"}


def create_fund(ctx: Ctx, key: str, **overrides: Any) -> JsonDict:
    """Create the named catalogue fund, or a fresh one from ``overrides``."""
    spec = dict(FUND_SPECS.get(key, {}))
    spec.update(overrides)
    fund = get_success_data(
        ctx.client.post(Paths.FUNDS, fund_payload(ctx.plan_id, **spec), consultant_headers()),
        201,
    )
    ctx.funds[key] = fund
    return fund


def create_target_date_fund(ctx: Ctx, key: str, **overrides: Any) -> JsonDict:
    spec = dict(TARGET_DATE_SPECS.get(key, {}))
    spec.update(overrides)
    fund = get_success_data(
        ctx.client.post(
            Paths.FUNDS, target_date_fund_payload(ctx.plan_id, **spec), consultant_headers()
        ),
        201,
    )
    ctx.funds[key] = fund
    return fund


def create_slot(
    ctx: Ctx,
    key: str,
    asset_class_code: str,
    slot_index: int,
    designation: str = SlotDesignation.CORE,
    **overrides: Any,
) -> JsonDict:
    slot = get_success_data(
        ctx.client.post(
            Paths.SLOTS,
            slot_payload(
                ctx.plan_id,
                ctx.ips_id,
                asset_class_code=asset_class_code,
                designation=designation,
                slot_index=slot_index,
                **overrides,
            ),
            consultant_headers(),
        ),
        201,
    )
    ctx.slots[key] = slot
    return slot


def seat_fund(ctx: Ctx, slot_key: str, fund_key: str) -> JsonDict:
    slot = get_success_data(
        ctx.client.post(
            Paths.seat_fund(ctx.slots[slot_key]["id"]),
            seat_fund_payload(ctx.funds[fund_key]["id"]),
            consultant_headers(),
        )
    )
    ctx.slots[slot_key] = slot
    return slot


def setup_full_menu(client: ApiClient, **kwargs: Any) -> Ctx:
    """Five seated CORE slots on a six-slot menu: occupied 5, reserved 0,
    available 1, with 12,000,000.00 in plan assets."""
    ctx = setup_adopted_ips(client, **kwargs)
    for key in ("lc_a", "bond", "small", "intl", "tips", "lc_b"):
        create_fund(ctx, key)
    create_target_date_fund(ctx, "td_thru")
    for key, asset_class, index in SLOT_SPECS:
        create_slot(ctx, key, asset_class, index)
    for slot_key, fund_key in SLOT_TO_FUND.items():
        seat_fund(ctx, slot_key, fund_key)
    ctx.refresh_plan()
    return ctx


# --------------------------------------------------------------------------
# Layer 4: the quarterly review
# --------------------------------------------------------------------------

#: Clean quarter-0 measurements, one per seated fund.  The composite scores they
#: produce are 76.20, 75.52, 59.88, 72.00 and 70.00 — every one clear of the
#: 40.00 watch trigger.
CLEAN_SCORECARDS: Dict[str, Dict[str, Any]] = {
    "lc_a": {
        "trailing_return_3y_bps": 900,
        "trailing_return_5y_bps": 850,
        "benchmark_return_3y_bps": 800,
        "benchmark_return_5y_bps": 800,
        "peer_rank_pct": 25,
        "style_drift_r2": 0.9200,
        "net_expense_ratio_bps": 45,
        "peer_median_expense_bps": 40,
        "manager_tenure_quarters": 20,
        "manager_change_flag": False,
    },
    "bond": {
        "trailing_return_3y_bps": 850,
        "trailing_return_5y_bps": 820,
        "benchmark_return_3y_bps": 800,
        "benchmark_return_5y_bps": 800,
        "peer_rank_pct": 30,
        "style_drift_r2": 0.9500,
        "net_expense_ratio_bps": 25,
        "peer_median_expense_bps": 30,
        "manager_tenure_quarters": 30,
        "manager_change_flag": False,
    },
    "small": {
        "trailing_return_3y_bps": 500,
        "trailing_return_5y_bps": 480,
        "benchmark_return_3y_bps": 600,
        "benchmark_return_5y_bps": 600,
        "peer_rank_pct": 60,
        "style_drift_r2": 0.8800,
        "net_expense_ratio_bps": 60,
        "peer_median_expense_bps": 55,
        "manager_tenure_quarters": 14,
        "manager_change_flag": False,
    },
    "intl": {
        "trailing_return_3y_bps": 700,
        "trailing_return_5y_bps": 700,
        "benchmark_return_3y_bps": 700,
        "benchmark_return_5y_bps": 700,
        "peer_rank_pct": 40,
        "style_drift_r2": 0.9100,
        "net_expense_ratio_bps": 32,
        "peer_median_expense_bps": 35,
        "manager_tenure_quarters": 26,
        "manager_change_flag": False,
    },
    "tips": {
        "trailing_return_3y_bps": 300,
        "trailing_return_5y_bps": 300,
        "benchmark_return_3y_bps": 300,
        "benchmark_return_5y_bps": 300,
        "peer_rank_pct": 50,
        "style_drift_r2": 0.9600,
        "net_expense_ratio_bps": 12,
        "peer_median_expense_bps": 15,
        "manager_tenure_quarters": 36,
        "manager_change_flag": False,
    },
}

#: Two breaching measurements: the small-cap fund lands on exactly 40.00, which
#: is watch-grade because the comparison is inclusive, and the international fund
#: lands on exactly 25.00, which is remediation-grade.
BREACH_SCORECARDS: Dict[str, Dict[str, Any]] = {
    "small": {
        "trailing_return_3y_bps": 200,
        "trailing_return_5y_bps": 200,
        "benchmark_return_3y_bps": 500,
        "benchmark_return_5y_bps": 500,
        "peer_rank_pct": 91,
        "style_drift_r2": 0.8800,
        "net_expense_ratio_bps": 75,
        "peer_median_expense_bps": 55,
        "manager_tenure_quarters": 14,
        "manager_change_flag": False,
    },
    "intl": {
        "trailing_return_3y_bps": 0,
        "trailing_return_5y_bps": 0,
        "benchmark_return_3y_bps": 700,
        "benchmark_return_5y_bps": 700,
        "peer_rank_pct": 100,
        "style_drift_r2": 0.9100,
        "net_expense_ratio_bps": 50,
        "peer_median_expense_bps": 35,
        "manager_tenure_quarters": 5,
        "manager_change_flag": True,
    },
}


def open_review(ctx: Ctx, quarter_index: int = 0, **overrides: Any) -> JsonDict:
    ctx.review = get_success_data(
        ctx.client.post(
            Paths.REVIEWS,
            review_payload(ctx.plan_id, quarter_index, **overrides),
            consultant_headers(),
        ),
        201,
    )
    return ctx.review


def submit_scorecard(ctx: Ctx, fund_key: str, inputs: Dict[str, Any], key: Optional[str] = None) -> JsonDict:
    """Submit one scorecard, reading the review's current version first because
    every accepted submission increments it."""
    review_id = ctx.review["id"]
    payload = scorecard_payload(
        review_id,
        ctx.funds[fund_key]["id"],
        review_version(ctx.client, review_id),
        **inputs,
    )
    scorecard = get_success_data(
        ctx.client.post(Paths.SCORECARDS, payload, consultant_headers()), 201
    )
    ctx.scorecards[key or fund_key] = scorecard
    return scorecard


def submit_quarter_scorecards(
    ctx: Ctx, overrides: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, JsonDict]:
    """One scorecard per seated fund, in menu order, with any per-fund override
    replacing that fund's clean measurement."""
    overrides = overrides or {}
    for slot_key, _asset_class, _index in SLOT_SPECS:
        fund_key = SLOT_TO_FUND[slot_key]
        inputs = dict(overrides.get(fund_key, CLEAN_SCORECARDS[fund_key]))
        submit_scorecard(ctx, fund_key, inputs)
    return ctx.scorecards


def present_review(ctx: Ctx, meeting_id: str) -> JsonDict:
    ctx.review = get_success_data(
        ctx.client.post(
            Paths.review_present(ctx.review["id"]),
            {"meeting_id": meeting_id},
            consultant_headers(),
        )
    )
    return ctx.review


def finalize_review(ctx: Ctx) -> JsonDict:
    ctx.review = get_success_data(
        ctx.client.post(Paths.review_finalize(ctx.review["id"]), {}, ctx.chair)
    )
    return ctx.review


def present_and_document(
    ctx: Ctx,
    meeting_date: str = "2026-08-10",
    minutes_doc_ref: str = "MIN-2026-Q0-002",
    quarter_index: int = 0,
) -> JsonDict:
    """Convene a meeting, present the review into it, then adjourn and approve
    the minutes so the review is one call away from finalization."""
    meeting = open_meeting(ctx, meeting_date, quarter_index, key="review")
    present_review(ctx, meeting["id"])
    adjourn(ctx, meeting["id"])
    approve_minutes(ctx, meeting["id"], minutes_doc_ref)
    return ctx.meetings["review"]


def setup_scored_quarter(
    client: ApiClient,
    scorecard_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    finalize: bool = True,
    **kwargs: Any,
) -> Ctx:
    """A seated menu with a fully scored quarter-0 review whose presenting
    meeting has approved minutes; finalized unless the caller says otherwise."""
    ctx = setup_full_menu(client, **kwargs)
    open_review(ctx, 0)
    submit_quarter_scorecards(ctx, scorecard_overrides)
    present_and_document(ctx)
    if finalize:
        finalize_review(ctx)
    ctx.refresh_plan()
    return ctx


def setup_finalized_quarter(client: ApiClient, **kwargs: Any) -> Ctx:
    """Quarter 0 finalized with every fund CLEAR and the posture OPEN."""
    return setup_scored_quarter(client, finalize=True, **kwargs)


def setup_breach_quarter(client: ApiClient, finalize: bool = False, **kwargs: Any) -> Ctx:
    """Quarter 0 scored with the small-cap fund at exactly 40.00 and the
    international fund at exactly 25.00, so finalization puts two of five slots
    at risk — a ratio of 0.4000 and a RESTRICTED posture."""
    return setup_scored_quarter(
        client, scorecard_overrides=BREACH_SCORECARDS, finalize=finalize, **kwargs
    )


# --------------------------------------------------------------------------
# Layer 5: fund replacement
# --------------------------------------------------------------------------


def set_clock(client: ApiClient, current_utc: str) -> None:
    get_success_data(client.set_clock(current_utc))


def draft_proposal(
    ctx: Ctx,
    slot_key: str,
    outgoing_key: str,
    incoming_key: str,
    key: str = "proposal",
    **overrides: Any,
) -> JsonDict:
    payload = proposal_payload(
        ctx.plan_id,
        ctx.slots[slot_key]["id"],
        ctx.funds[outgoing_key]["id"],
        ctx.funds[incoming_key]["id"],
        plan_version(ctx.client, ctx.plan_id),
        **overrides,
    )
    proposal = get_success_data(
        ctx.client.post(Paths.REPLACEMENTS, payload, consultant_headers()), 201
    )
    ctx.proposals[key] = proposal
    return proposal


def submit_proposal(ctx: Ctx, proposal_id: str, key: str = "proposal") -> JsonDict:
    proposal = get_success_data(
        ctx.client.post(Paths.proposal_submit(proposal_id), {}, consultant_headers())
    )
    ctx.proposals[key] = proposal
    return proposal


def approve_proposal(
    ctx: Ctx, proposal_id: str, approving_motion_id: str, key: str = "proposal"
) -> JsonDict:
    proposal = get_success_data(
        ctx.client.post(
            Paths.proposal_approve(proposal_id),
            {"approving_motion_id": approving_motion_id},
            ctx.chair,
        )
    )
    ctx.proposals[key] = proposal
    return proposal


def issue_notice(ctx: Ctx, proposal_id: str, key: str = "proposal", **overrides: Any) -> JsonDict:
    proposal = get_success_data(
        ctx.client.post(
            Paths.proposal_notice_issue(proposal_id),
            notice_issue_payload(**overrides),
            recordkeeper_headers(),
        )
    )
    ctx.proposals[key] = proposal
    return proposal


def execute_proposal(ctx: Ctx, proposal_id: str, key: str = "proposal") -> JsonDict:
    proposal = get_success_data(
        ctx.client.post(Paths.proposal_execute(proposal_id), {}, recordkeeper_headers())
    )
    ctx.proposals[key] = proposal
    return proposal


def setup_submitted_replacement(
    client: ApiClient,
    slot_key: str = "lc",
    outgoing_key: str = "lc_a",
    incoming_key: str = "lc_b",
    **kwargs: Any,
) -> Ctx:
    """A seated menu with one proposal sitting in UNDER_REVIEW."""
    ctx = setup_full_menu(client, **kwargs)
    proposal = draft_proposal(ctx, slot_key, outgoing_key, incoming_key)
    submit_proposal(ctx, proposal["id"])
    return ctx


def setup_approved_replacement(client: ApiClient, **kwargs: Any) -> Ctx:
    """A proposal carried by motion, minuted and APPROVED, holding one reserved
    menu position."""
    ctx = setup_submitted_replacement(client, **kwargs)
    motion = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.FUND_REPLACEMENT,
        ctx.proposals["proposal"]["id"],
        meeting_date="2026-08-17",
        minutes_doc_ref="MIN-2026-Q0-003",
        key="replacement",
    )
    approve_proposal(ctx, ctx.proposals["proposal"]["id"], motion["id"])
    ctx.refresh_plan()
    return ctx


def setup_noticed_replacement(client: ApiClient, **kwargs: Any) -> Ctx:
    """The participant notice is out and a 2026-09-01 to 2026-09-15 blackout
    window is reserved; the 30-day notice period expires 2026-08-31."""
    ctx = setup_approved_replacement(client, **kwargs)
    issue_notice(ctx, ctx.proposals["proposal"]["id"])
    ctx.refresh_plan()
    return ctx


def setup_executed_replacement(client: ApiClient, **kwargs: Any) -> Ctx:
    """The mapping has run inside the blackout window with the clock at
    2026-09-02, moving the outgoing fund's assets to the incoming fund."""
    ctx = setup_noticed_replacement(client, **kwargs)
    set_clock(ctx.client, "2026-09-02T00:00:00Z")
    execute_proposal(ctx, ctx.proposals["proposal"]["id"])
    ctx.refresh_plan()
    return ctx


# --------------------------------------------------------------------------
# Layer 5b: the qualified-default slot and its candidate suites
# --------------------------------------------------------------------------


def setup_qdia_candidates(client: ApiClient, **kwargs: Any) -> Ctx:
    """A seated menu plus an empty QDIA slot and four THROUGH_RETIREMENT suites:
    TDTHR and TDTIE tie on fit 100.00 and 45 basis points, TDLOW fits at 92.50,
    and TDCHP is cheapest but has only 11 quarters of track record."""
    ctx = setup_full_menu(client, **kwargs)
    create_slot(ctx, "qdia", AssetClass.TARGET_DATE, 6, designation=SlotDesignation.QDIA)
    for key in ("td_tie", "td_cheap", "td_off_shelf"):
        create_target_date_fund(ctx, key)
    ctx.refresh_plan()
    return ctx


def select_target_date_suite(
    ctx: Ctx, fund_key: str, approving_motion_id: str, glidepath_type: str = "THROUGH_RETIREMENT"
) -> JsonDict:
    return get_success_data(
        ctx.client.post(
            Paths.target_date_selection(ctx.funds[fund_key]["id"]),
            {"approving_motion_id": approving_motion_id, "glidepath_type": glidepath_type},
            ctx.chair,
        )
    )


# --------------------------------------------------------------------------
# Layer 6: fee levelization and provider engagements
# --------------------------------------------------------------------------


def create_levelization_run(
    ctx: Ctx, quarter_index: int = 0, method: str = "PER_CAPITA", key: str = "run", **overrides: Any
) -> JsonDict:
    run = get_success_data(
        ctx.client.post(
            Paths.LEVELIZATION_RUNS,
            levelization_payload(ctx.plan_id, quarter_index, method, **overrides),
            consultant_headers(),
        ),
        201,
    )
    ctx.runs[key] = run
    return run


def approve_levelization_run(
    ctx: Ctx, run_id: str, approving_motion_id: str, key: str = "run"
) -> JsonDict:
    run = get_success_data(
        ctx.client.post(
            Paths.run_approve(run_id), {"approving_motion_id": approving_motion_id}, ctx.chair
        )
    )
    ctx.runs[key] = run
    return run


def approve_run_with_motion(
    ctx: Ctx,
    run_id: str,
    meeting_date: str = "2026-08-11",
    minutes_doc_ref: str = "MIN-2026-Q0-LEV",
    quarter_index: int = 0,
    key: str = "run",
) -> JsonDict:
    """Carry the FEE_LEVELIZATION motion naming a DRAFT run and approve it.

    PRD 3.8 puts the three allocation passes behind this act: a created run
    "starts DRAFT with allocation_lines empty, allocated_total_cents and
    remainder_cents at 0, and per_account_cents ... null", and it is approval that
    "freezes allocation_lines, per_account_cents, allocated_total_cents and
    remainder_cents".  Any test reading the allocation therefore has to come
    through here first.

    PRD 2.12 priority 52 makes "a member whose ``independence_flag`` is false ...
    vote ``RECUSE`` on any ``FEE_LEVELIZATION`` motion", so the affiliated seat
    recuses instead of voting FOR.  Recusals never enter the ``VOTES_CAST``
    denominator, so the remaining unanimous FOR votes still put ``support_pct`` at
    100.0000 and the motion carries.
    """
    meeting = open_meeting(
        ctx, meeting_date, quarter_index=quarter_index, key=f"{key}_levelization_meeting"
    )
    motion = move_motion(
        ctx,
        meeting["id"],
        MotionSubjectType.FEE_LEVELIZATION,
        run_id,
        key=f"{key}_levelization",
    )
    for member_id in ctx.member_ids:
        if read_member(ctx.client, member_id)["independence_flag"]:
            cast_vote(ctx, motion["id"], member_id, Vote.FOR)
        else:
            cast_vote(
                ctx,
                motion["id"],
                member_id,
                Vote.RECUSE,
                recusal_basis="affiliated with a plan service provider",
            )
    motion = close_motion(ctx, motion["id"])
    ctx.motions[f"{key}_levelization"] = motion
    adjourn(ctx, meeting["id"])
    approve_minutes(ctx, meeting["id"], minutes_doc_ref)
    return approve_levelization_run(ctx, run_id, motion["id"], key=key)


def post_levelization_run(ctx: Ctx, run_id: str, key: str = "run") -> JsonDict:
    run = get_success_data(
        ctx.client.post(Paths.run_post(run_id), {}, recordkeeper_headers())
    )
    ctx.runs[key] = run
    return run


def create_engagement(ctx: Ctx, key: str = "recordkeeper", **overrides: Any) -> JsonDict:
    engagement = get_success_data(
        ctx.client.post(
            Paths.ENGAGEMENTS, engagement_payload(ctx.plan_id, **overrides), sponsor_headers()
        ),
        201,
    )
    ctx.engagements[key] = engagement
    return engagement


def benchmark_engagement(ctx: Ctx, engagement_id: str, key: str = "recordkeeper") -> JsonDict:
    engagement = get_success_data(
        ctx.client.post(Paths.engagement_benchmark(engagement_id), {}, consultant_headers())
    )
    ctx.engagements[key] = engagement
    return engagement


def advance_quarter(ctx: Ctx) -> JsonDict:
    ctx.plan = get_success_data(
        ctx.client.post(Paths.advance_quarter(ctx.plan_id), {}, sponsor_headers())
    )
    return ctx.plan

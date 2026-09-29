"""
Composite state builders and pytest fixtures.

Every test starts against an empty database, so all preconditions are built here
from scratch through declared endpoints only. Setup calls go through
`get_success_data`, which is lenient about the exact 2xx code, because the code a
setup step returns is the subject of other tests rather than of the setup.

The builder follows the pipeline the PRD describes: a program is stood up and
activated, a competitor and analysts are registered against it, deals are
imported, buyer contacts are added and consented, a sampling frame is defined and
sealed, deals are drawn, interviews are scheduled, answered and completed, and
the recorded answers then feed battlecard claims, loss attributions and product
gaps.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import WinLossApiClient
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    ENABLEMENT_MANAGER_USER_ID,
    LEGAL_REVIEWER_USER_ID,
    PRODUCT_MANAGER_USER_ID,
    SALES_REP_USER_ID,
    make_enablement_manager_headers,
    make_legal_reviewer_headers,
    make_product_manager_headers,
    make_program_admin_headers,
    make_research_analyst_headers,
    make_sales_rep_headers,
)


def _data(response) -> Any:
    """Unwrap a setup response's `data` payload, tolerating either 2xx code."""
    return get_success_data(response)


class WinLossWorld:
    """Progressive builder over the declared endpoints."""

    def __init__(self, api: WinLossApiClient) -> None:
        self.api = api
        self.admin = make_program_admin_headers()
        self.legal = make_legal_reviewer_headers()
        self.enablement = make_enablement_manager_headers()
        self.product = make_product_manager_headers()
        self.rep = make_sales_rep_headers()
        self.program: Dict[str, Any] = {}
        self.competitor: Dict[str, Any] = {}
        self.analyst: Dict[str, Any] = {}
        self.analyst2: Dict[str, Any] = {}
        self.deal: Dict[str, Any] = {}
        self.contact: Dict[str, Any] = {}
        self.frame: Dict[str, Any] = {}
        self.interview: Dict[str, Any] = {}
        self.responses: List[Dict[str, Any]] = []
        self.battlecard: Dict[str, Any] = {}
        self.claim: Dict[str, Any] = {}
        self.assignment: Dict[str, Any] = {}
        self.attribution: Dict[str, Any] = {}
        self.reasons: Dict[str, Dict[str, Any]] = {}
        self.gap: Dict[str, Any] = {}

    # -- identifiers ----------------------------------------------------

    @property
    def program_id(self) -> str:
        return self.program["id"]

    @property
    def analyst_headers(self) -> Dict[str, str]:
        return make_research_analyst_headers(self.analyst["id"])

    @property
    def analyst2_headers(self) -> Dict[str, str]:
        return make_research_analyst_headers(self.analyst2["id"])

    def headers_for(self, analyst: Dict[str, Any]) -> Dict[str, str]:
        return make_research_analyst_headers(analyst["id"])

    # -- clock ----------------------------------------------------------

    def set_clock(self, current_utc: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
        return _data(self.api.set_clock(f.clock_payload(current_utc), self.admin))

    # -- program --------------------------------------------------------

    def create_program(self, **overrides: Any) -> Dict[str, Any]:
        self.program = _data(
            self.api.create_program(f.program_payload(**overrides), self.admin)
        )
        return self.program

    def activate_program(self) -> Dict[str, Any]:
        self.program = _data(self.api.activate_program(self.program_id, self.admin))
        return self.program

    def refresh_program(self) -> Dict[str, Any]:
        self.program = _data(self.api.get_program(self.program_id, self.admin))
        return self.program

    def begin_closing(self) -> Dict[str, Any]:
        self.program = _data(self.api.begin_closing_program(self.program_id, self.admin))
        return self.program

    def close_program(self) -> Dict[str, Any]:
        self.program = _data(self.api.close_program(self.program_id, self.admin))
        return self.program

    def set_budget(self, incentive_budget_usd) -> Dict[str, Any]:
        current = self.refresh_program()
        self.program = _data(
            self.api.replace_incentive_budget(
                self.program_id,
                f.incentive_budget_payload(incentive_budget_usd, current["version"]),
                self.admin,
            )
        )
        return self.program

    def set_guide(self, required_question_keys: List[str]) -> Dict[str, Any]:
        self.program = _data(
            self.api.replace_interview_guide(
                self.program_id,
                f.interview_guide_payload(required_question_keys),
                self.admin,
            )
        )
        return self.program

    def active_program(self, **overrides: Any) -> Dict[str, Any]:
        self.create_program(**overrides)
        return self.activate_program()

    # -- competitor -----------------------------------------------------

    def create_competitor(self, **overrides: Any) -> Dict[str, Any]:
        competitor = _data(
            self.api.create_competitor(
                f.competitor_payload(self.program_id, **overrides), self.admin
            )
        )
        if not self.competitor:
            self.competitor = competitor
        return competitor

    def get_competitor(self, competitor_id: Optional[str] = None) -> Dict[str, Any]:
        return _data(
            self.api.get_competitor(competitor_id or self.competitor["id"], self.admin)
        )

    # -- analysts -------------------------------------------------------

    def create_analyst(self, **overrides: Any) -> Dict[str, Any]:
        analyst = _data(
            self.api.create_analyst(
                f.analyst_payload(self.program_id, **overrides), self.admin
            )
        )
        if not self.analyst:
            self.analyst = analyst
        elif not self.analyst2:
            self.analyst2 = analyst
        return analyst

    def create_two_analysts(self) -> Dict[str, Any]:
        self.create_analyst(full_name="Ana One", linked_user_ref="u-ana-1")
        self.create_analyst(full_name="Ana Two", linked_user_ref="u-ana-2")
        return self.analyst

    def get_analyst(self, analyst_id: Optional[str] = None) -> Dict[str, Any]:
        return _data(self.api.get_analyst(analyst_id or self.analyst["id"], self.admin))

    # -- deals ----------------------------------------------------------

    def create_deal(self, **overrides: Any) -> Dict[str, Any]:
        deal = _data(
            self.api.create_deal(f.deal_payload(self.program_id, **overrides), self.admin)
        )
        if not self.deal:
            self.deal = deal
        return deal

    def get_deal(self, deal_id: Optional[str] = None) -> Dict[str, Any]:
        return _data(self.api.get_deal(deal_id or self.deal["id"], self.admin))

    # -- buyer contacts -------------------------------------------------

    def create_contact(
        self, deal_id: Optional[str] = None, **overrides: Any
    ) -> Dict[str, Any]:
        contact = _data(
            self.api.create_buyer_contact(
                deal_id or self.deal["id"],
                f.buyer_contact_payload(**overrides),
                self.analyst_headers,
            )
        )
        if not self.contact:
            self.contact = contact
        return contact

    def record_consent(
        self,
        consent_status: str = "GRANTED",
        deal_id: Optional[str] = None,
        contact_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return _data(
            self.api.record_consent(
                deal_id or self.deal["id"],
                contact_id or self.contact["id"],
                f.consent_payload(consent_status),
                self.analyst_headers,
            )
        )

    def consented_contact(
        self, deal_id: Optional[str] = None, **overrides: Any
    ) -> Dict[str, Any]:
        contact = self.create_contact(deal_id=deal_id, **overrides)
        self.record_consent(
            "GRANTED", deal_id=deal_id or self.deal["id"], contact_id=contact["id"]
        )
        return contact

    def get_contact(self, contact_id: Optional[str] = None) -> Dict[str, Any]:
        return _data(
            self.api.get_buyer_contact(contact_id or self.contact["id"], self.admin)
        )

    # -- sampling frames ------------------------------------------------

    def create_frame(self, **overrides: Any) -> Dict[str, Any]:
        frame = _data(
            self.api.create_sampling_frame(
                f.sampling_frame_payload(self.program_id, **overrides),
                self.analyst_headers,
            )
        )
        if not self.frame:
            self.frame = frame
        return frame

    def seal_frame(self, frame_id: Optional[str] = None) -> Dict[str, Any]:
        frame = _data(
            self.api.seal_frame(frame_id or self.frame["id"], self.analyst_headers)
        )
        if frame_id in (None, self.frame.get("id")):
            self.frame = frame
        return frame

    def draw(
        self, stratum: str = "LOST", frame_id: Optional[str] = None, **overrides: Any
    ) -> List[Dict[str, Any]]:
        return _data(
            self.api.draw_frame(
                frame_id or self.frame["id"],
                f.draw_payload(stratum, **overrides),
                self.analyst_headers,
            )
        )

    def close_frame(self, frame_id: Optional[str] = None) -> Dict[str, Any]:
        frame = _data(
            self.api.close_frame(frame_id or self.frame["id"], self.analyst_headers)
        )
        if frame_id in (None, self.frame.get("id")):
            self.frame = frame
        return frame

    def get_frame(self, frame_id: Optional[str] = None) -> Dict[str, Any]:
        return _data(
            self.api.get_sampling_frame(frame_id or self.frame["id"], self.admin)
        )

    # -- interviews -----------------------------------------------------

    def schedule_interview(
        self,
        deal_id: Optional[str] = None,
        buyer_contact_id: Optional[str] = None,
        analyst: Optional[Dict[str, Any]] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        interviewer = analyst or self.analyst
        interview = _data(
            self.api.create_interview(
                f.interview_payload(
                    deal_id or self.deal["id"],
                    buyer_contact_id or self.contact["id"],
                    interviewer["id"],
                    **overrides,
                ),
                self.headers_for(interviewer),
            )
        )
        if not self.interview:
            self.interview = interview
        return interview

    def get_interview(self, interview_id: Optional[str] = None) -> Dict[str, Any]:
        return _data(
            self.api.get_interview(interview_id or self.interview["id"], self.admin)
        )

    def record_response(
        self,
        interview_id: Optional[str] = None,
        analyst: Optional[Dict[str, Any]] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        interviewer = analyst or self.analyst
        response = _data(
            self.api.create_interview_response(
                interview_id or self.interview["id"],
                f.interview_response_payload(**overrides),
                self.headers_for(interviewer),
            )
        )
        self.responses.append(response)
        return response

    def cover_guide(
        self,
        interview_id: Optional[str] = None,
        analyst: Optional[Dict[str, Any]] = None,
        recorded_at: str = "2026-08-10T14:10:00.000Z",
        rating: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Record one answer for each of the three default guide topics."""
        recorded = []
        for question_key in (
            "EVALUATION_CRITERIA",
            "COMPETITOR_POSITIONING",
            "PRICING_PERCEPTION",
        ):
            recorded.append(
                self.record_response(
                    interview_id=interview_id,
                    analyst=analyst,
                    question_key=question_key,
                    verbatim_text=f"Buyer commentary on {question_key}.",
                    recorded_at=recorded_at,
                    **({"rating": rating} if rating is not None else {}),
                )
            )
        return recorded

    def complete_interview(
        self,
        interview_id: Optional[str] = None,
        analyst: Optional[Dict[str, Any]] = None,
        actual_start_at: str = "2026-08-10T14:05:00.000Z",
        actual_end_at: str = "2026-08-10T14:35:00.000Z",
    ) -> Dict[str, Any]:
        interviewer = analyst or self.analyst
        interview = _data(
            self.api.complete_interview(
                interview_id or self.interview["id"],
                f.complete_interview_payload(actual_start_at, actual_end_at),
                self.headers_for(interviewer),
            )
        )
        if interview_id in (None, self.interview.get("id")):
            self.interview = interview
        return interview

    def no_show(
        self, interview_id: Optional[str] = None, analyst: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        interviewer = analyst or self.analyst
        return _data(
            self.api.no_show_interview(
                interview_id or self.interview["id"], self.headers_for(interviewer)
            )
        )

    def cancel_interview(
        self, interview_id: Optional[str] = None, analyst: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        interviewer = analyst or self.analyst
        return _data(
            self.api.cancel_interview(
                interview_id or self.interview["id"], self.headers_for(interviewer)
            )
        )

    # -- taxonomy and attribution ---------------------------------------

    def create_reason(
        self, code: str = "PRICE", label: Optional[str] = None, **overrides: Any
    ) -> Dict[str, Any]:
        reason = _data(
            self.api.create_loss_reason(
                f.loss_reason_payload(
                    self.program_id, code=code, label=label or code.title(), **overrides
                ),
                self.admin,
            )
        )
        self.reasons[code] = reason
        return reason

    def create_attribution(
        self,
        primary_reason_id: str,
        deal_id: Optional[str] = None,
        analyst: Optional[Dict[str, Any]] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        author = analyst or self.analyst
        target_deal_id = deal_id or self.deal["id"]
        current = self.get_deal(target_deal_id)
        attribution = _data(
            self.api.create_loss_attribution(
                f.loss_attribution_payload(
                    target_deal_id,
                    primary_reason_id,
                    current["version"],
                    **overrides,
                ),
                self.headers_for(author),
            )
        )
        if not self.attribution:
            self.attribution = attribution
        return attribution

    def ratify_attribution(
        self,
        attribution_id: Optional[str] = None,
        analyst: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ratifier = analyst or self.analyst2
        return _data(
            self.api.ratify_loss_attribution(
                attribution_id or self.attribution["id"], self.headers_for(ratifier)
            )
        )

    def get_reason(self, reason_id: str) -> Dict[str, Any]:
        return _data(self.api.get_loss_reason(reason_id, self.admin))

    def get_attribution(self, attribution_id: Optional[str] = None) -> Dict[str, Any]:
        return _data(
            self.api.get_loss_attribution(
                attribution_id or self.attribution["id"], self.admin
            )
        )

    def loss_trends(self, **params: Any) -> Dict[str, Any]:
        return _data(
            self.api.get_loss_trends(
                self.program_id, self.admin, f.loss_trends_params(**params)
            )
        )

    # -- battlecards ----------------------------------------------------

    def create_battlecard(
        self, competitor_id: Optional[str] = None, **overrides: Any
    ) -> Dict[str, Any]:
        card = _data(
            self.api.create_battlecard(
                f.battlecard_payload(
                    competitor_id or self.competitor["id"], **overrides
                ),
                self.analyst_headers,
            )
        )
        if not self.battlecard:
            self.battlecard = card
        return card

    def add_claim(
        self,
        evidence_response_ids: List[str],
        battlecard_id: Optional[str] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        claim = _data(
            self.api.create_claim(
                battlecard_id or self.battlecard["id"],
                f.claim_payload(evidence_response_ids, **overrides),
                self.analyst_headers,
            )
        )
        if not self.claim:
            self.claim = claim
        return claim

    def submit_legal(self, battlecard_id: Optional[str] = None) -> Dict[str, Any]:
        card = _data(
            self.api.submit_legal(
                battlecard_id or self.battlecard["id"], self.analyst_headers
            )
        )
        if battlecard_id in (None, self.battlecard.get("id")):
            self.battlecard = card
        return card

    def decide_claim(
        self,
        decision: str = "APPROVE",
        claim_id: Optional[str] = None,
        battlecard_id: Optional[str] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        return _data(
            self.api.legal_decision(
                battlecard_id or self.battlecard["id"],
                claim_id or self.claim["id"],
                f.legal_decision_payload(decision, **overrides),
                self.legal,
            )
        )

    def publish_battlecard(self, battlecard_id: Optional[str] = None) -> Dict[str, Any]:
        card = _data(
            self.api.publish_battlecard(
                battlecard_id or self.battlecard["id"], self.enablement
            )
        )
        if battlecard_id in (None, self.battlecard.get("id")):
            self.battlecard = card
        return card

    def reopen_battlecard(self, battlecard_id: Optional[str] = None) -> Dict[str, Any]:
        card = _data(
            self.api.reopen_battlecard(
                battlecard_id or self.battlecard["id"], self.analyst_headers
            )
        )
        if battlecard_id in (None, self.battlecard.get("id")):
            self.battlecard = card
        return card

    def get_battlecard(self, battlecard_id: Optional[str] = None) -> Dict[str, Any]:
        return _data(
            self.api.get_battlecard(battlecard_id or self.battlecard["id"], self.admin)
        )

    def get_claim(self, claim_id: Optional[str] = None) -> Dict[str, Any]:
        return _data(
            self.api.get_battlecard_claim(claim_id or self.claim["id"], self.admin)
        )

    # -- enablement -----------------------------------------------------

    def assign(
        self,
        sales_rep_user_ref: str = SALES_REP_USER_ID,
        due_at: str = "2026-09-30T00:00:00.000Z",
        battlecard_id: Optional[str] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        assignment = _data(
            self.api.create_enablement_assignment(
                f.enablement_assignment_payload(
                    battlecard_id or self.battlecard["id"],
                    sales_rep_user_ref,
                    due_at,
                    **overrides,
                ),
                self.enablement,
            )
        )
        if not self.assignment:
            self.assignment = assignment
        return assignment

    def complete_assignment(
        self,
        quiz_score: int = 90,
        assignment_id: Optional[str] = None,
        sales_rep_user_ref: str = SALES_REP_USER_ID,
    ) -> Dict[str, Any]:
        return _data(
            self.api.complete_assignment(
                assignment_id or self.assignment["id"],
                f.assignment_complete_payload(quiz_score),
                make_sales_rep_headers(sales_rep_user_ref),
            )
        )

    def get_assignment(self, assignment_id: Optional[str] = None) -> Dict[str, Any]:
        return _data(
            self.api.get_enablement_assignment(
                assignment_id or self.assignment["id"], self.admin
            )
        )

    def sweep(self) -> Dict[str, Any]:
        return _data(self.api.run_enablement_sweep(self.program_id, self.enablement))

    # -- product gaps ---------------------------------------------------

    def create_gap(self, source_response_id: str, **overrides: Any) -> Dict[str, Any]:
        gap = _data(
            self.api.create_product_gap(
                f.product_gap_payload(self.program_id, source_response_id, **overrides),
                self.product,
            )
        )
        if not self.gap:
            self.gap = gap
        return gap

    def triage_gap(
        self, decision: str = "ACCEPT", gap_id: Optional[str] = None, **overrides: Any
    ) -> Dict[str, Any]:
        gap = _data(
            self.api.triage_product_gap(
                gap_id or self.gap["id"], f.triage_payload(decision, **overrides), self.product
            )
        )
        if gap_id in (None, self.gap.get("id")):
            self.gap = gap
        return gap

    def promote_gap(
        self, roadmap_epic_ref: str = "EPIC-4210", gap_id: Optional[str] = None
    ) -> Dict[str, Any]:
        gap = _data(
            self.api.promote_product_gap(
                gap_id or self.gap["id"], f.promote_payload(roadmap_epic_ref), self.product
            )
        )
        if gap_id in (None, self.gap.get("id")):
            self.gap = gap
        return gap

    def get_gap(self, gap_id: Optional[str] = None) -> Dict[str, Any]:
        return _data(self.api.get_product_gap(gap_id or self.gap["id"], self.admin))

    # ------------------------------------------------------------------
    # Composite pipelines
    # ------------------------------------------------------------------

    def build_registry(self, **program_overrides: Any) -> "WinLossWorld":
        """Active program, one PRIMARY competitor and two analysts."""
        self.active_program(**program_overrides)
        self.create_competitor()
        self.create_two_analysts()
        return self

    def build_selected_deal(self, **program_overrides: Any) -> "WinLossWorld":
        """A LOST deal drawn into a sealed frame, with a consented buyer contact."""
        self.build_registry(**program_overrides)
        self.create_deal(primary_competitor_id=self.competitor["id"])
        self.consented_contact()
        self.create_frame()
        self.seal_frame()
        self.draw("LOST")
        return self

    def build_scheduled_interview(self, **program_overrides: Any) -> "WinLossWorld":
        """A SCHEDULED interview on a drawn deal."""
        self.build_selected_deal(**program_overrides)
        self.schedule_interview()
        return self

    def build_completed_interview(
        self,
        recorded_at: str = "2026-08-10T14:10:00.000Z",
        clock_after: str = "2026-08-10T15:30:00.000Z",
        rating: Optional[int] = None,
        **program_overrides: Any,
    ) -> "WinLossWorld":
        """A COMPLETED interview whose three guide topics are all answered."""
        self.build_scheduled_interview(**program_overrides)
        self.cover_guide(recorded_at=recorded_at, rating=rating)
        self.set_clock(clock_after)
        self.complete_interview()
        return self

    def build_draft_battlecard(
        self, claim_type: str = "REFERENCE", rating: Optional[int] = 4, **kwargs: Any
    ) -> "WinLossWorld":
        """A DRAFT card carrying one claim cited from a completed interview."""
        self.build_completed_interview(rating=rating, **kwargs)
        self.create_battlecard()
        positioning = self.response_of("COMPETITOR_POSITIONING")
        self.add_claim([positioning["id"]], claim_type=claim_type)
        return self

    def build_published_battlecard(self, **kwargs: Any) -> "WinLossWorld":
        """An approved-then-published card on the program's competitor."""
        self.build_draft_battlecard(**kwargs)
        self.submit_legal()
        self.decide_claim("APPROVE")
        self.publish_battlecard()
        return self

    def build_assigned_battlecard(
        self, due_at: str = "2026-09-30T00:00:00.000Z", **kwargs: Any
    ) -> "WinLossWorld":
        """A published card distributed to one sales rep."""
        self.build_published_battlecard(**kwargs)
        self.assign(due_at=due_at)
        return self

    def build_ratified_attribution(self, **kwargs: Any) -> "WinLossWorld":
        """A ratified single-reason attribution on an interviewed deal."""
        self.build_completed_interview(**kwargs)
        self.create_reason("PRICE", "Price")
        self.create_attribution(self.reasons["PRICE"]["id"])
        self.ratify_attribution()
        return self

    def build_product_gap(
        self,
        recorded_at: str = "2026-08-10T14:10:00.000Z",
        clock_after: str = "2026-08-10T15:30:00.000Z",
        **program_overrides: Any,
    ) -> "WinLossWorld":
        """A NEW product gap seeded from a PRODUCT_GAP verbatim.

        Answers are append-only evidence recorded while the interview is still
        SCHEDULED, so the seeding verbatim is captured before completion.
        """
        self.build_scheduled_interview(**program_overrides)
        self.cover_guide(recorded_at=recorded_at)
        seed = self.record_response(
            question_key="PRODUCT_GAP",
            verbatim_text="No customer-managed key support for the export pipeline.",
            recorded_at=recorded_at,
        )
        self.set_clock(clock_after)
        self.complete_interview()
        self.create_gap(seed["id"])
        return self

    # -- lookups --------------------------------------------------------

    def response_of(self, question_key: str) -> Dict[str, Any]:
        for response in self.responses:
            if response.get("question_key") == question_key:
                return response
        raise AssertionError(
            f"no recorded answer for {question_key!r}; have "
            f"{[r.get('question_key') for r in self.responses]}"
        )


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> WinLossApiClient:
    """A client pointed at the server under test."""
    return WinLossApiClient()


@pytest.fixture
def world(api: WinLossApiClient) -> WinLossWorld:
    """An empty builder over a freshly started server."""
    return WinLossWorld(api)


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    return make_program_admin_headers()


@pytest.fixture
def legal_headers() -> Dict[str, str]:
    return make_legal_reviewer_headers()


@pytest.fixture
def enablement_headers() -> Dict[str, str]:
    return make_enablement_manager_headers()


@pytest.fixture
def product_headers() -> Dict[str, str]:
    return make_product_manager_headers()


@pytest.fixture
def rep_headers() -> Dict[str, str]:
    return make_sales_rep_headers()


@pytest.fixture
def draft_program(world: WinLossWorld) -> WinLossWorld:
    world.create_program()
    return world


@pytest.fixture
def active_program(world: WinLossWorld) -> WinLossWorld:
    world.active_program()
    return world


@pytest.fixture
def registry(world: WinLossWorld) -> WinLossWorld:
    return world.build_registry()


@pytest.fixture
def selected_deal(world: WinLossWorld) -> WinLossWorld:
    return world.build_selected_deal()


@pytest.fixture
def scheduled_interview(world: WinLossWorld) -> WinLossWorld:
    return world.build_scheduled_interview()


@pytest.fixture
def completed_interview(world: WinLossWorld) -> WinLossWorld:
    return world.build_completed_interview()


@pytest.fixture
def draft_battlecard(world: WinLossWorld) -> WinLossWorld:
    return world.build_draft_battlecard()


@pytest.fixture
def published_battlecard(world: WinLossWorld) -> WinLossWorld:
    return world.build_published_battlecard()


@pytest.fixture
def assigned_battlecard(world: WinLossWorld) -> WinLossWorld:
    return world.build_assigned_battlecard()


@pytest.fixture
def ratified_attribution(world: WinLossWorld) -> WinLossWorld:
    return world.build_ratified_attribution()


@pytest.fixture
def product_gap(world: WinLossWorld) -> WinLossWorld:
    return world.build_product_gap()


USER_IDS = {
    "legal": LEGAL_REVIEWER_USER_ID,
    "enablement": ENABLEMENT_MANAGER_USER_ID,
    "product": PRODUCT_MANAGER_USER_ID,
    "rep": SALES_REP_USER_ID,
}

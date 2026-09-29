"""
Composite fixtures for the Individual Artist Fellowship Grants API.

The API server is restarted with an empty database before every individual
test, so nothing here may assume pre-existing rows: each builder walks the
declared endpoints from scratch and returns a context object carrying every id
it created.

Three fixture families are provided, each a cumulative chain whose later
builders call the earlier ones:

  * ``cyclemain_*``  — a five-seat LITERARY_ARTS panel with one application and
    five reviews whose weighted scores are 8.00, 6.60, 7.30, 6.00 and 8.50.
    This is the chain the PRD's worked composite-score, assessment-tier and
    withholding examples are stated against.
  * ``cornermain_*`` — a three-seat panel with one application and three
    reviews (8.00, 6.60, 7.30), whose artist has a TIN on file so withholding
    is zero.
  * ``twoslot_*``    — a two-application slate on an 1,800,000-cent discipline
    allocation, so rank 1 takes the full base award and rank 2 falls under the
    prorated floor.

Every builder returns a ``Ctx``: a dict that also supports attribute access.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import ACCEPT_AGREEMENT_VERSION
from .test_users import (
    BOARD_MEMBER,
    FISCAL_OFFICER,
    PROGRAM_OFFICER,
    make_artist_headers,
    make_panelist_headers,
)


class Ctx(dict):
    """A dict whose keys are also readable as attributes."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the logical clock and return the checkpoint response payload."""
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or PROGRAM_OFFICER)
    )


def cycle_version(cycle_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    return get_success_data(api_client.get_cycle(cycle_id, headers or PROGRAM_OFFICER))[
        "version"
    ]


def panel_version(panel_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    return get_success_data(api_client.get_panel(panel_id, headers or PROGRAM_OFFICER))[
        "version"
    ]


def read_cycle(cycle_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_cycle(cycle_id, headers or PROGRAM_OFFICER))


def read_application(
    application_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_application(application_id, headers or PROGRAM_OFFICER)
    )


def read_panel(panel_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_panel(panel_id, headers or PROGRAM_OFFICER))


def read_award(award_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_award(award_id, headers or FISCAL_OFFICER))


def read_discipline(
    discipline_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_discipline(discipline_id, headers or PROGRAM_OFFICER)
    )


def read_artist(artist_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_artist(artist_id, headers or PROGRAM_OFFICER))


def list_installments_of(award_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_installments(FISCAL_OFFICER, {"award_id": award_id, "limit": 100})
    )


def list_reviews_of(application_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_reviews(
            PROGRAM_OFFICER, {"application_id": application_id, "limit": 100}
        )
    )


def _register_artist(
    legal_name: str,
    email: str,
    residency_start_date: str,
    residency_county: str,
    region: str,
    tin_status: str = "MISSING",
    is_enrolled_student: bool = False,
) -> str:
    return get_success_data(
        api_client.create_artist(
            {
                "legal_name": legal_name,
                "email": email,
                "residency_start_date": residency_start_date,
                "residency_county": residency_county,
                "region": region,
                "is_enrolled_student": is_enrolled_student,
                "tin_status": tin_status,
            },
            PROGRAM_OFFICER,
        )
    )["id"]


def _nominate(
    panel_id: str,
    person_email: str,
    full_name: str,
    region: str,
    expertise_codes: Optional[List[str]] = None,
    is_chair: bool = False,
) -> str:
    return get_success_data(
        api_client.create_panelist(
            {
                "panel_id": panel_id,
                "person_email": person_email,
                "full_name": full_name,
                "region": region,
                "expertise_codes": expertise_codes or ["LITERARY_ARTS"],
                "is_chair": is_chair,
            },
            PROGRAM_OFFICER,
        )
    )["id"]


def _seat(panelist_id: str) -> None:
    get_success_data(api_client.seat_panelist(panelist_id, PROGRAM_OFFICER))


def _draft_and_submit_review(
    application_id: str,
    panelist_id: str,
    scores: Tuple[int, int, int, int],
    comments: str,
) -> str:
    review_id = get_success_data(
        api_client.create_review(
            {
                "application_id": application_id,
                "panelist_id": panelist_id,
                "artistic_excellence": scores[0],
                "work_sample_quality": scores[1],
                "career_impact": scores[2],
                "public_value": scores[3],
                "comments": comments,
            },
            make_panelist_headers(panelist_id),
        )
    )["id"]
    get_success_data(
        api_client.submit_review(review_id, make_panelist_headers(panelist_id))
    )
    return review_id


def slot_id_for_application(application_id: str) -> str:
    rows = get_success_data(
        api_client.list_slots(PROGRAM_OFFICER, {"application_id": application_id})
    )
    assert rows, f"no recommendation slot exists for application {application_id}"
    return rows[0]["id"]


def award_id_for_application(application_id: str) -> str:
    rows = get_success_data(
        api_client.list_awards(PROGRAM_OFFICER, {"application_id": application_id})
    )
    assert rows, f"no award exists for application {application_id}"
    return rows[0]["id"]


# ===========================================================================
# Family A — CycleMain: five-seat panel, one application, five reviews
# ===========================================================================
CYCLEMAIN_CYCLE = {
    "name": "FY2027 Individual Artist Fellowships",
    "fiscal_year": 2027,
    "application_open_at": "2026-08-15T00:00:00Z",
    "application_deadline_at": "2026-10-15T23:59:59Z",
    "grant_period_start": "2027-01-01T00:00:00Z",
    "grant_period_end": "2027-12-31T00:00:00Z",
    "total_budget_cents": 6_000_000,
    "base_award_cents": 1_500_000,
    "min_prorated_award_cents": 500_000,
    "residency_min_months": 24,
    "award_blackout_years": 3,
    "proration_policy": "PRORATE",
    "max_review_rounds": 2,
    "acceptance_window_days": 14,
    "appeal_window_days": 30,
    "final_report_due_offset_days": 60,
}

CYCLEMAIN_DISCIPLINE = {
    "code": "LITERARY_ARTS",
    "alias_prefix": "LIT",
    "allocation_cents": 2_000_000,
    "required_work_sample_count": 2,
    "allowed_media": ["MANUSCRIPT_PAGES", "AUDIO"],
    "required_panel_seats": 5,
    "required_regions": ["NORTH", "CENTRAL", "SOUTH"],
    "max_total_duration_seconds": 600,
    "max_concurrent_panels": 1,
}

# Criterion scores and the weighted score each set produces.
REVIEW_SCORES_800 = (9, 8, 7, 6)
REVIEW_SCORES_660 = (7, 7, 6, 5)
REVIEW_SCORES_730 = (8, 6, 8, 7)
REVIEW_SCORES_600 = (6, 6, 6, 6)
REVIEW_SCORES_850 = (9, 8, 9, 7)
REVIEW_SCORES_860 = (9, 9, 8, 7)
REVIEW_SCORES_700 = (7, 7, 7, 7)
REVIEW_SCORES_800_FLAT = (8, 8, 8, 8)


def cyclemain_cycle_draft(clock: str = "2026-09-01T00:00:00Z") -> Ctx:
    """Logical clock advanced, a DRAFT cycle and its LITERARY_ARTS discipline."""
    ctx = Ctx()
    set_clock(clock)
    ctx.clock = clock
    cycle = get_success_data(api_client.create_cycle(dict(CYCLEMAIN_CYCLE), PROGRAM_OFFICER))
    ctx.cyc = cycle["id"]
    ctx.cycle = cycle
    discipline = get_success_data(
        api_client.create_discipline(
            {"cycle_id": ctx.cyc, **CYCLEMAIN_DISCIPLINE}, PROGRAM_OFFICER
        )
    )
    ctx.disc = discipline["id"]
    ctx.discipline = discipline
    return ctx


def cyclemain_cycle_open(clock: str = "2026-09-01T00:00:00Z") -> Ctx:
    ctx = cyclemain_cycle_draft(clock)
    get_success_data(api_client.set_cycle_status(ctx.cyc, "OPEN", PROGRAM_OFFICER))
    return ctx


def cyclemain_application_draft(clock: str = "2026-09-01T00:00:00Z") -> Ctx:
    """An OPEN cycle plus Ada Rivers' DRAFT application with two work samples."""
    ctx = cyclemain_cycle_open(clock)
    ctx.art1 = _register_artist(
        "Ada Rivers", "ada.rivers@example.org", "2023-01-10", "Lakeshore", "NORTH", "MISSING"
    )
    ctx.art1_headers = make_artist_headers(ctx.art1)
    ctx.app1 = get_success_data(
        api_client.create_application(
            {
                "cycle_id": ctx.cyc,
                "discipline_category_id": ctx.disc,
                "artist_id": ctx.art1,
                "artist_statement": (
                    "I write short fiction about lake towns and the people who leave them."
                ),
                "career_narrative": (
                    "Fifteen years of small-press publication, two chapbooks and a "
                    "residency at the county library."
                ),
            },
            ctx.art1_headers,
        )
    )["id"]
    ctx.ws1a = get_success_data(
        api_client.create_work_sample(
            {
                "application_id": ctx.app1,
                "medium": "MANUSCRIPT_PAGES",
                "ordinal": 1,
                "page_count": 12,
                "contains_identifying_metadata": False,
            },
            ctx.art1_headers,
        )
    )["id"]
    ctx.ws1b = get_success_data(
        api_client.create_work_sample(
            {
                "application_id": ctx.app1,
                "medium": "MANUSCRIPT_PAGES",
                "ordinal": 2,
                "page_count": 9,
                "contains_identifying_metadata": False,
            },
            ctx.art1_headers,
        )
    )["id"]
    return ctx


def cyclemain_application_submitted(clock: str = "2026-09-01T00:00:00Z") -> Ctx:
    ctx = cyclemain_application_draft(clock)
    get_success_data(api_client.submit_application(ctx.app1, ctx.art1_headers))
    return ctx


def add_second_application(ctx: Ctx, submit: bool = True) -> Ctx:
    """Bo Nakamura (SOUTH, TIN on file) files a second application on the same cycle."""
    ctx.art2 = _register_artist(
        "Bo Nakamura", "bo.nakamura@example.org", "2022-05-01", "Rivermouth", "SOUTH", "ON_FILE"
    )
    ctx.art2_headers = make_artist_headers(ctx.art2)
    ctx.app2 = get_success_data(
        api_client.create_application(
            {
                "cycle_id": ctx.cyc,
                "discipline_category_id": ctx.disc,
                "artist_id": ctx.art2,
                "artist_statement": "Prose poems assembled from harbour radio transcripts.",
                "career_narrative": (
                    "Two decades of docklands oral history collected into three "
                    "self-published volumes."
                ),
            },
            ctx.art2_headers,
        )
    )["id"]
    ctx.ws2a = get_success_data(
        api_client.create_work_sample(
            {
                "application_id": ctx.app2,
                "medium": "MANUSCRIPT_PAGES",
                "ordinal": 1,
                "page_count": 11,
                "contains_identifying_metadata": False,
            },
            ctx.art2_headers,
        )
    )["id"]
    ctx.ws2b = get_success_data(
        api_client.create_work_sample(
            {
                "application_id": ctx.app2,
                "medium": "MANUSCRIPT_PAGES",
                "ordinal": 2,
                "page_count": 7,
                "contains_identifying_metadata": False,
            },
            ctx.art2_headers,
        )
    )["id"]
    if submit:
        get_success_data(api_client.submit_application(ctx.app2, ctx.art2_headers))
    return ctx


def cyclemain_cycle_closed(second_application: bool = False) -> Ctx:
    """Clock past the deadline and the cycle CLOSED, with its submissions in place."""
    ctx = cyclemain_application_submitted()
    if second_application:
        add_second_application(ctx, submit=True)
    set_clock("2026-10-16T00:00:00Z")
    ctx.clock = "2026-10-16T00:00:00Z"
    get_success_data(api_client.set_cycle_status(ctx.cyc, "CLOSED", PROGRAM_OFFICER))
    return ctx


def cyclemain_application_eligible(second_application: bool = False) -> Ctx:
    ctx = cyclemain_cycle_closed(second_application=second_application)
    get_success_data(
        api_client.determine_eligibility(
            ctx.app1, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
        )
    )
    if second_application:
        get_success_data(
            api_client.determine_eligibility(
                ctx.app2, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
            )
        )
    return ctx


def cyclemain_cycle_panel_review(second_application: bool = False) -> Ctx:
    ctx = cyclemain_application_eligible(second_application=second_application)
    get_success_data(api_client.set_cycle_status(ctx.cyc, "PANEL_REVIEW", PROGRAM_OFFICER))
    return ctx


def cyclemain_panel_seated(second_application: bool = False) -> Ctx:
    """A five-seat panel with all five readers seated across NORTH, CENTRAL and SOUTH."""
    ctx = cyclemain_cycle_panel_review(second_application=second_application)
    ctx.pan = get_success_data(
        api_client.create_panel(
            {
                "cycle_id": ctx.cyc,
                "discipline_category_id": ctx.disc,
                "required_seats": 5,
                "required_regions": ["NORTH", "CENTRAL", "SOUTH"],
                "deliberation_window_start": "2026-11-01T00:00:00Z",
                "deliberation_window_end": "2026-12-01T00:00:00Z",
            },
            PROGRAM_OFFICER,
        )
    )["id"]
    ctx.pl1 = _nominate(
        ctx.pan, "chair.north@example.org", "Iris Vance", "NORTH", is_chair=True
    )
    ctx.pl2 = _nominate(ctx.pan, "reader.central@example.org", "Omar Diaz", "CENTRAL")
    ctx.pl3 = _nominate(ctx.pan, "reader.south@example.org", "Neve Okoro", "SOUTH")
    ctx.pl4 = _nominate(ctx.pan, "reader.north2@example.org", "Piet Halvorsen", "NORTH")
    ctx.pl5 = _nominate(ctx.pan, "reader.coastal@example.org", "Lena Marsh", "COASTAL")
    for panelist_id in (ctx.pl1, ctx.pl2, ctx.pl3, ctx.pl4, ctx.pl5):
        _seat(panelist_id)
    ctx.pl1_headers = make_panelist_headers(ctx.pl1)
    ctx.pl2_headers = make_panelist_headers(ctx.pl2)
    ctx.pl3_headers = make_panelist_headers(ctx.pl3)
    ctx.pl4_headers = make_panelist_headers(ctx.pl4)
    ctx.pl5_headers = make_panelist_headers(ctx.pl5)
    return ctx


def cyclemain_panel_chartered(second_application: bool = False) -> Ctx:
    ctx = cyclemain_panel_seated(second_application=second_application)
    get_success_data(api_client.charter_panel(ctx.pan, PROGRAM_OFFICER))
    return ctx


def cyclemain_round_open(second_application: bool = False) -> Ctx:
    ctx = cyclemain_panel_chartered(second_application=second_application)
    get_success_data(api_client.open_round(ctx.pan, PROGRAM_OFFICER))
    return ctx


def cyclemain_reviews_submitted(
    fifth_scores: Tuple[int, int, int, int] = REVIEW_SCORES_850,
    second_application: bool = False,
) -> Ctx:
    """
    Five submitted reviews on app1 with weighted scores 8.00, 6.60, 7.30, 6.00 and
    whatever ``fifth_scores`` produces (8.50 by default).
    """
    ctx = cyclemain_round_open(second_application=second_application)
    ctx.rv1 = _draft_and_submit_review(
        ctx.app1, ctx.pl1, REVIEW_SCORES_800, "Assured voice, uneven middle section."
    )
    ctx.rv2 = _draft_and_submit_review(
        ctx.app1, ctx.pl2, REVIEW_SCORES_660, "Competent but conventional."
    )
    ctx.rv3 = _draft_and_submit_review(
        ctx.app1, ctx.pl3, REVIEW_SCORES_730, "Strong career trajectory."
    )
    ctx.rv4 = _draft_and_submit_review(
        ctx.app1, ctx.pl4, REVIEW_SCORES_600, "Solid across the board."
    )
    ctx.rv5 = _draft_and_submit_review(
        ctx.app1, ctx.pl5, fifth_scores, "The strongest manuscript in the pool."
    )
    if second_application:
        ctx.rv2a = _draft_and_submit_review(
            ctx.app2, ctx.pl1, REVIEW_SCORES_800, "Documentary instinct, thin lyric surface."
        )
        ctx.rv2b = _draft_and_submit_review(
            ctx.app2, ctx.pl2, REVIEW_SCORES_660, "Worthy but repetitive."
        )
        ctx.rv2c = _draft_and_submit_review(
            ctx.app2, ctx.pl3, REVIEW_SCORES_600, "Even, unremarkable."
        )
    return ctx


def cyclemain_round_closed(
    fifth_scores: Tuple[int, int, int, int] = REVIEW_SCORES_850,
    second_application: bool = False,
) -> Ctx:
    ctx = cyclemain_reviews_submitted(
        fifth_scores=fifth_scores, second_application=second_application
    )
    get_success_data(api_client.close_round(ctx.pan, PROGRAM_OFFICER))
    return ctx


def cyclemain_board_review(second_application: bool = False) -> Ctx:
    ctx = cyclemain_round_closed(second_application=second_application)
    get_success_data(api_client.set_cycle_status(ctx.cyc, "BOARD_REVIEW", PROGRAM_OFFICER))
    return ctx


def cyclemain_slate_submitted(second_application: bool = False) -> Ctx:
    """The chair transmits the ranked slate, minting one PROPOSED slot per application."""
    ctx = cyclemain_board_review(second_application=second_application)
    ranked = [ctx.app1, ctx.app2] if second_application else [ctx.app1]
    ctx.pan_v = panel_version(ctx.pan)
    get_success_data(
        api_client.submit_slate(
            ctx.pan,
            {"ranked_application_ids": ranked, "expected_panel_version": ctx.pan_v},
            ctx.pl1_headers,
        )
    )
    ctx.slot1 = slot_id_for_application(ctx.app1)
    if second_application:
        ctx.slot2 = slot_id_for_application(ctx.app2)
    return ctx


def cyclemain_slot_approved() -> Ctx:
    """The board approves rank 1, which mints the OFFERED award."""
    ctx = cyclemain_slate_submitted()
    ctx.cyc_v = cycle_version(ctx.cyc, BOARD_MEMBER)
    get_success_data(
        api_client.board_action(
            ctx.slot1,
            {"action": "APPROVE", "expected_cycle_version": ctx.cyc_v},
            BOARD_MEMBER,
        )
    )
    ctx.aw1 = award_id_for_application(ctx.app1)
    return ctx


def cyclemain_award_accepted() -> Ctx:
    """
    The artist signs the agreement, which generates the three-installment schedule.
    The cycle is still BOARD_REVIEW at this point.
    """
    ctx = cyclemain_slot_approved()
    get_success_data(
        api_client.accept_award(
            ctx.aw1,
            {
                "accept_agreement_version": ACCEPT_AGREEMENT_VERSION,
                "tax_certification_signed": True,
            },
            ctx.art1_headers,
        )
    )
    rows = list_installments_of(ctx.aw1)
    ctx.installments = rows
    ctx.inst1, ctx.inst2, ctx.inst3 = (row["id"] for row in rows[:3])
    return ctx


def cyclemain_cycle_awarded() -> Ctx:
    """Award accepted and the cycle advanced to AWARDED, which releases the reserve."""
    ctx = cyclemain_award_accepted()
    get_success_data(api_client.set_cycle_status(ctx.cyc, "AWARDED", PROGRAM_OFFICER))
    return ctx


def cyclemain_installment_one_released() -> Ctx:
    ctx = cyclemain_cycle_awarded()
    set_clock("2027-01-01T00:00:00Z")
    ctx.clock = "2027-01-01T00:00:00Z"
    get_success_data(api_client.release_installment(ctx.inst1, FISCAL_OFFICER))
    return ctx


def cyclemain_installment_one_paid() -> Ctx:
    ctx = cyclemain_installment_one_released()
    get_success_data(api_client.pay_installment(ctx.inst1, FISCAL_OFFICER))
    return ctx


def cyclemain_two_applications_slated() -> Ctx:
    """
    Both applications scored and slated as rank 1 (app1) and rank 2 (app2), with the
    cycle in BOARD_REVIEW and no board action taken yet.
    """
    return cyclemain_slate_submitted(second_application=True)


# ===========================================================================
# Family B — CornerMain: three-seat panel, one application, TIN on file
# ===========================================================================
CORNERMAIN_CYCLE = {
    "name": "FY2027 Fellowships (corner fixture)",
    "fiscal_year": 2027,
    "application_open_at": "2026-08-15T00:00:00Z",
    "application_deadline_at": "2026-10-15T23:59:59Z",
    "grant_period_start": "2027-01-01T00:00:00Z",
    "grant_period_end": "2027-12-31T00:00:00Z",
    "total_budget_cents": 6_000_000,
    "base_award_cents": 1_500_000,
    "min_prorated_award_cents": 500_000,
    "residency_min_months": 24,
    "award_blackout_years": 3,
    "proration_policy": "PRORATE",
    "max_review_rounds": 2,
    "acceptance_window_days": 14,
    "appeal_window_days": 30,
    "final_report_due_offset_days": 60,
}

CORNERMAIN_DISCIPLINE = {
    "code": "LITERARY_ARTS",
    "alias_prefix": "LIT",
    "allocation_cents": 2_000_000,
    "required_work_sample_count": 2,
    "allowed_media": ["MANUSCRIPT_PAGES", "AUDIO"],
    "required_panel_seats": 3,
    "required_regions": ["NORTH", "CENTRAL", "SOUTH"],
    "max_total_duration_seconds": 600,
    "max_concurrent_panels": 1,
}


def cornermain_cycle_draft(clock: str = "2026-09-01T00:00:00Z") -> Ctx:
    ctx = Ctx()
    set_clock(clock)
    ctx.clock = clock
    cycle = get_success_data(
        api_client.create_cycle(dict(CORNERMAIN_CYCLE), PROGRAM_OFFICER)
    )
    ctx.cyc = cycle["id"]
    ctx.cycle = cycle
    discipline = get_success_data(
        api_client.create_discipline(
            {"cycle_id": ctx.cyc, **CORNERMAIN_DISCIPLINE}, PROGRAM_OFFICER
        )
    )
    ctx.disc = discipline["id"]
    ctx.discipline = discipline
    return ctx


def cornermain_cycle_open(clock: str = "2026-09-01T00:00:00Z") -> Ctx:
    ctx = cornermain_cycle_draft(clock)
    get_success_data(api_client.set_cycle_status(ctx.cyc, "OPEN", PROGRAM_OFFICER))
    return ctx


def cornermain_application_draft(clock: str = "2026-09-01T00:00:00Z") -> Ctx:
    ctx = cornermain_cycle_open(clock)
    ctx.art = _register_artist(
        "Cleo Amari", "cleo.amari@example.org", "2023-01-10", "Harbor", "NORTH", "ON_FILE"
    )
    ctx.art_headers = make_artist_headers(ctx.art)
    ctx.app = get_success_data(
        api_client.create_application(
            {
                "cycle_id": ctx.cyc,
                "discipline_category_id": ctx.disc,
                "artist_id": ctx.art,
                "artist_statement": (
                    "Prose poems about harbour towns and the ferries that no longer run."
                ),
                "career_narrative": (
                    "Twelve years of small-press publication and two library residencies."
                ),
            },
            ctx.art_headers,
        )
    )["id"]
    ctx.ws1 = get_success_data(
        api_client.create_work_sample(
            {
                "application_id": ctx.app,
                "medium": "MANUSCRIPT_PAGES",
                "ordinal": 1,
                "page_count": 11,
                "contains_identifying_metadata": False,
            },
            ctx.art_headers,
        )
    )["id"]
    ctx.ws2 = get_success_data(
        api_client.create_work_sample(
            {
                "application_id": ctx.app,
                "medium": "MANUSCRIPT_PAGES",
                "ordinal": 2,
                "page_count": 8,
                "contains_identifying_metadata": False,
            },
            ctx.art_headers,
        )
    )["id"]
    return ctx


def cornermain_application_submitted(clock: str = "2026-09-01T00:00:00Z") -> Ctx:
    ctx = cornermain_application_draft(clock)
    get_success_data(api_client.submit_application(ctx.app, ctx.art_headers))
    return ctx


def cornermain_cycle_closed() -> Ctx:
    ctx = cornermain_application_submitted()
    set_clock("2026-10-16T00:00:00Z")
    ctx.clock = "2026-10-16T00:00:00Z"
    get_success_data(api_client.set_cycle_status(ctx.cyc, "CLOSED", PROGRAM_OFFICER))
    return ctx


def cornermain_application_eligible() -> Ctx:
    ctx = cornermain_cycle_closed()
    get_success_data(
        api_client.determine_eligibility(
            ctx.app, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
        )
    )
    return ctx


def cornermain_cycle_panel_review() -> Ctx:
    ctx = cornermain_application_eligible()
    get_success_data(api_client.set_cycle_status(ctx.cyc, "PANEL_REVIEW", PROGRAM_OFFICER))
    return ctx


def cornermain_panel_seated() -> Ctx:
    ctx = cornermain_cycle_panel_review()
    ctx.pan = get_success_data(
        api_client.create_panel(
            {
                "cycle_id": ctx.cyc,
                "discipline_category_id": ctx.disc,
                "required_seats": 3,
                "required_regions": ["NORTH", "CENTRAL", "SOUTH"],
                "deliberation_window_start": "2026-11-01T00:00:00Z",
                "deliberation_window_end": "2026-12-01T00:00:00Z",
            },
            PROGRAM_OFFICER,
        )
    )["id"]
    ctx.pl1 = _nominate(
        ctx.pan, "chair.north@example.org", "Kira Vale", "NORTH", is_chair=True
    )
    ctx.pl2 = _nominate(ctx.pan, "reader.central@example.org", "Lev Ostrom", "CENTRAL")
    ctx.pl3 = _nominate(ctx.pan, "reader.south@example.org", "Mira Sol", "SOUTH")
    for panelist_id in (ctx.pl1, ctx.pl2, ctx.pl3):
        _seat(panelist_id)
    ctx.pl1_headers = make_panelist_headers(ctx.pl1)
    ctx.pl2_headers = make_panelist_headers(ctx.pl2)
    ctx.pl3_headers = make_panelist_headers(ctx.pl3)
    return ctx


def cornermain_panel_chartered() -> Ctx:
    ctx = cornermain_panel_seated()
    get_success_data(api_client.charter_panel(ctx.pan, PROGRAM_OFFICER))
    return ctx


def cornermain_round_open() -> Ctx:
    ctx = cornermain_panel_chartered()
    get_success_data(api_client.open_round(ctx.pan, PROGRAM_OFFICER))
    return ctx


def cornermain_reviews_submitted() -> Ctx:
    """Three submitted reviews with weighted scores 8.00, 6.60 and 7.30."""
    ctx = cornermain_round_open()
    ctx.rv1 = _draft_and_submit_review(
        ctx.app, ctx.pl1, REVIEW_SCORES_800, "Assured voice, uneven middle section."
    )
    ctx.rv2 = _draft_and_submit_review(
        ctx.app, ctx.pl2, REVIEW_SCORES_660, "Competent but conventional."
    )
    ctx.rv3 = _draft_and_submit_review(
        ctx.app, ctx.pl3, REVIEW_SCORES_730, "Strong career trajectory."
    )
    return ctx


def cornermain_round_closed() -> Ctx:
    ctx = cornermain_reviews_submitted()
    get_success_data(api_client.close_round(ctx.pan, PROGRAM_OFFICER))
    return ctx


def cornermain_board_review() -> Ctx:
    ctx = cornermain_round_closed()
    get_success_data(api_client.set_cycle_status(ctx.cyc, "BOARD_REVIEW", PROGRAM_OFFICER))
    return ctx


def cornermain_slate_submitted() -> Ctx:
    ctx = cornermain_board_review()
    ctx.pan_v = panel_version(ctx.pan)
    get_success_data(
        api_client.submit_slate(
            ctx.pan,
            {"ranked_application_ids": [ctx.app], "expected_panel_version": ctx.pan_v},
            ctx.pl1_headers,
        )
    )
    ctx.slot = slot_id_for_application(ctx.app)
    return ctx


def cornermain_slot_approved() -> Ctx:
    ctx = cornermain_slate_submitted()
    ctx.cyc_v = cycle_version(ctx.cyc)
    get_success_data(
        api_client.board_action(
            ctx.slot,
            {"action": "APPROVE", "expected_cycle_version": ctx.cyc_v},
            BOARD_MEMBER,
        )
    )
    ctx.aw = award_id_for_application(ctx.app)
    return ctx


def cornermain_award_accepted() -> Ctx:
    ctx = cornermain_slot_approved()
    get_success_data(
        api_client.accept_award(
            ctx.aw,
            {
                "accept_agreement_version": ACCEPT_AGREEMENT_VERSION,
                "tax_certification_signed": True,
            },
            ctx.art_headers,
        )
    )
    return ctx


def cornermain_cycle_awarded() -> Ctx:
    ctx = cornermain_award_accepted()
    get_success_data(api_client.set_cycle_status(ctx.cyc, "AWARDED", PROGRAM_OFFICER))
    rows = list_installments_of(ctx.aw)
    ctx.installments = rows
    ctx.i1, ctx.i2, ctx.i3 = (row["id"] for row in rows[:3])
    return ctx


def cornermain_installment_one_paid() -> Ctx:
    ctx = cornermain_cycle_awarded()
    set_clock("2027-01-01T00:00:00Z")
    ctx.clock = "2027-01-01T00:00:00Z"
    get_success_data(api_client.release_installment(ctx.i1, FISCAL_OFFICER))
    get_success_data(api_client.pay_installment(ctx.i1, FISCAL_OFFICER))
    return ctx


# ===========================================================================
# Family C — TwoSlot: two slated applications on an 1,800,000-cent allocation
# ===========================================================================
TWOSLOT_CYCLE = {
    **CYCLEMAIN_CYCLE,
    "name": "FY2027 Fellowships (two-slot fixture)",
}

TWOSLOT_DISCIPLINE = {
    "code": "LITERARY_ARTS",
    "alias_prefix": "LIT",
    "allocation_cents": 1_800_000,
    "required_work_sample_count": 2,
    "allowed_media": ["MANUSCRIPT_PAGES", "AUDIO"],
    "required_panel_seats": 3,
    "required_regions": ["NORTH", "CENTRAL", "SOUTH"],
    "max_total_duration_seconds": 600,
    "max_concurrent_panels": 1,
}


def twoslot_cycle_open(clock: str = "2026-09-01T00:00:00Z") -> Ctx:
    ctx = Ctx()
    set_clock(clock)
    ctx.clock = clock
    ctx.tcyc = get_success_data(
        api_client.create_cycle(dict(TWOSLOT_CYCLE), PROGRAM_OFFICER)
    )["id"]
    ctx.tdisc = get_success_data(
        api_client.create_discipline(
            {"cycle_id": ctx.tcyc, **TWOSLOT_DISCIPLINE}, PROGRAM_OFFICER
        )
    )["id"]
    get_success_data(api_client.set_cycle_status(ctx.tcyc, "OPEN", PROGRAM_OFFICER))
    return ctx


def _twoslot_application(
    ctx: Ctx,
    artist_id: str,
    headers: Dict[str, str],
    statement: str,
    narrative: str,
    page_counts: Optional[Tuple[int, int]] = None,
    submit: bool = True,
) -> str:
    application_id = get_success_data(
        api_client.create_application(
            {
                "cycle_id": ctx.tcyc,
                "discipline_category_id": ctx.tdisc,
                "artist_id": artist_id,
                "artist_statement": statement,
                "career_narrative": narrative,
            },
            headers,
        )
    )["id"]
    if page_counts:
        for ordinal, pages in enumerate(page_counts, start=1):
            get_success_data(
                api_client.create_work_sample(
                    {
                        "application_id": application_id,
                        "medium": "MANUSCRIPT_PAGES",
                        "ordinal": ordinal,
                        "page_count": pages,
                        "contains_identifying_metadata": False,
                    },
                    headers,
                )
            )
    if submit:
        get_success_data(api_client.submit_application(application_id, headers))
    return application_id


def twoslot_applications_submitted() -> Ctx:
    """
    Four artists: A and B submit complete applications, C leaves a DRAFT with no
    samples, and D submits with a residency one day short of the 24-month minimum.
    """
    ctx = twoslot_cycle_open()

    ctx.artA = _register_artist(
        "Dara Holt", "dara.holt@example.org", "2023-01-10", "Harbor", "NORTH", "ON_FILE"
    )
    ctx.artA_headers = make_artist_headers(ctx.artA)
    ctx.appA = _twoslot_application(
        ctx,
        ctx.artA,
        ctx.artA_headers,
        "Linked stories about a drowned valley.",
        "Fourteen years of small-press publication.",
        page_counts=(10, 12),
    )

    ctx.artB = _register_artist(
        "Emil Roux", "emil.roux@example.org", "2022-06-05", "Ridge", "SOUTH", "ON_FILE"
    )
    ctx.artB_headers = make_artist_headers(ctx.artB)
    ctx.appB = _twoslot_application(
        ctx,
        ctx.artB,
        ctx.artB_headers,
        "A long poem on transhumance routes.",
        "Eleven years of translation and two chapbooks.",
        page_counts=(9, 7),
    )

    ctx.artC = _register_artist(
        "Fay Ling", "fay.ling@example.org", "2021-09-09", "Harbor", "NORTH", "ON_FILE"
    )
    ctx.artC_headers = make_artist_headers(ctx.artC)
    ctx.appC = _twoslot_application(
        ctx,
        ctx.artC,
        ctx.artC_headers,
        "A libretto in progress.",
        "Eight years of stage writing.",
        page_counts=None,
        submit=False,
    )

    ctx.artD = _register_artist(
        "Gus Pran", "gus.pran@example.org", "2024-10-16", "Ridge", "SOUTH", "ON_FILE"
    )
    ctx.artD_headers = make_artist_headers(ctx.artD)
    ctx.appD = _twoslot_application(
        ctx,
        ctx.artD,
        ctx.artD_headers,
        "Essays on river towns.",
        "Recent arrival; five years of journalism.",
        page_counts=(8, 6),
    )
    return ctx


def twoslot_determinations() -> Ctx:
    """Cycle CLOSED, A and B ELIGIBLE, D INELIGIBLE for residency duration."""
    ctx = twoslot_applications_submitted()
    set_clock("2026-10-16T00:00:00Z")
    ctx.clock = "2026-10-16T00:00:00Z"
    get_success_data(api_client.set_cycle_status(ctx.tcyc, "CLOSED", PROGRAM_OFFICER))
    get_success_data(
        api_client.determine_eligibility(
            ctx.appA, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
        )
    )
    get_success_data(
        api_client.determine_eligibility(
            ctx.appB, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
        )
    )
    get_success_data(
        api_client.determine_eligibility(
            ctx.appD,
            {"determination": "INELIGIBLE", "ineligibility_reason_code": "RESIDENCY_DURATION"},
            PROGRAM_OFFICER,
        )
    )
    return ctx


def twoslot_cycle_panel_review() -> Ctx:
    ctx = twoslot_determinations()
    get_success_data(api_client.set_cycle_status(ctx.tcyc, "PANEL_REVIEW", PROGRAM_OFFICER))
    return ctx


def twoslot_panel_chartered() -> Ctx:
    ctx = twoslot_cycle_panel_review()
    ctx.tpan = get_success_data(
        api_client.create_panel(
            {
                "cycle_id": ctx.tcyc,
                "discipline_category_id": ctx.tdisc,
                "required_seats": 3,
                "required_regions": ["NORTH", "CENTRAL", "SOUTH"],
                "deliberation_window_start": "2026-11-01T00:00:00Z",
                "deliberation_window_end": "2026-12-01T00:00:00Z",
            },
            PROGRAM_OFFICER,
        )
    )["id"]
    ctx.tpl1 = _nominate(
        ctx.tpan, "chair.north@example.org", "Nia Brandt", "NORTH", is_chair=True
    )
    ctx.tpl2 = _nominate(ctx.tpan, "reader.central@example.org", "Otto Lind", "CENTRAL")
    ctx.tpl3 = _nominate(ctx.tpan, "reader.south@example.org", "Pia Novak", "SOUTH")
    for panelist_id in (ctx.tpl1, ctx.tpl2, ctx.tpl3):
        _seat(panelist_id)
    ctx.tpl1_headers = make_panelist_headers(ctx.tpl1)
    ctx.tpl2_headers = make_panelist_headers(ctx.tpl2)
    ctx.tpl3_headers = make_panelist_headers(ctx.tpl3)
    get_success_data(api_client.charter_panel(ctx.tpan, PROGRAM_OFFICER))
    get_success_data(api_client.open_round(ctx.tpan, PROGRAM_OFFICER))
    return ctx


def twoslot_reviews_submitted() -> Ctx:
    """appA scores 8.00 / 6.60 / 7.30 and appB scores 7.00 / 6.00 / 8.00."""
    ctx = twoslot_panel_chartered()
    ctx.rvA1 = _draft_and_submit_review(
        ctx.appA, ctx.tpl1, REVIEW_SCORES_800, "Assured voice."
    )
    ctx.rvA2 = _draft_and_submit_review(
        ctx.appA, ctx.tpl2, REVIEW_SCORES_660, "Conventional but competent."
    )
    ctx.rvA3 = _draft_and_submit_review(
        ctx.appA, ctx.tpl3, REVIEW_SCORES_730, "Strong trajectory."
    )
    ctx.rvB1 = _draft_and_submit_review(
        ctx.appB, ctx.tpl1, REVIEW_SCORES_700, "Even throughout."
    )
    ctx.rvB2 = _draft_and_submit_review(
        ctx.appB, ctx.tpl2, REVIEW_SCORES_600, "Serviceable."
    )
    ctx.rvB3 = _draft_and_submit_review(
        ctx.appB, ctx.tpl3, REVIEW_SCORES_800_FLAT, "The most ambitious sequence here."
    )
    return ctx


def twoslot_round_closed() -> Ctx:
    ctx = twoslot_reviews_submitted()
    get_success_data(api_client.close_round(ctx.tpan, PROGRAM_OFFICER))
    return ctx


def twoslot_board_review() -> Ctx:
    ctx = twoslot_round_closed()
    get_success_data(api_client.set_cycle_status(ctx.tcyc, "BOARD_REVIEW", PROGRAM_OFFICER))
    return ctx


def twoslot_slate_submitted() -> Ctx:
    """Slate ranked [appA, appB]; both slots PROPOSED and no board action taken."""
    ctx = twoslot_board_review()
    ctx.tpan_v = panel_version(ctx.tpan)
    get_success_data(
        api_client.submit_slate(
            ctx.tpan,
            {
                "ranked_application_ids": [ctx.appA, ctx.appB],
                "expected_panel_version": ctx.tpan_v,
            },
            ctx.tpl1_headers,
        )
    )
    ctx.slotA = slot_id_for_application(ctx.appA)
    ctx.slotB = slot_id_for_application(ctx.appB)
    ctx.tcyc_v = cycle_version(ctx.tcyc)
    return ctx


def twoslot_first_slot_approved() -> Ctx:
    """Rank 1 approved, committing 1,500,000 of the 1,800,000 allocation."""
    ctx = twoslot_slate_submitted()
    get_success_data(
        api_client.board_action(
            ctx.slotA,
            {"action": "APPROVE", "expected_cycle_version": ctx.tcyc_v},
            BOARD_MEMBER,
        )
    )
    return ctx

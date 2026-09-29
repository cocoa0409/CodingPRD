"""Composite state builders.

Every test starts against an empty database, so any scenario deeper than a single
POST has to be assembled from the endpoints the contract publishes. The builders
here are layered:

* **Tier 1 - single steps.** ``seed_state``, ``seed_standard``, ``seed_cycle``,
  ``seed_title`` and the clock helper.
* **Tier 2 - hierarchies.** ``seed_open_cycle`` walks the calendar to OPEN;
  ``seed_draft_submission`` hangs a submission with correlation evidence off it.
* **Tier 3 - lifecycle shortcuts.** ``seed_filed_submission``,
  ``seed_priced_submission``, ``seed_scheduled_submission`` and
  ``seed_presented_slot`` carry a submission as far down the review workflow as a
  test needs.
* **Tier 4 - accumulation targeting.** ``stack_public_comments`` and
  ``ship_sampling_copies_to`` push counters to the thresholds the compliance
  score and the sampling status turn on.
* **Tier 5 - terminal states.** ``seed_adopted_submission``,
  ``seed_confirmed_order`` and ``seed_applied_content_edit`` land the workflow in
  a finalized state.

All setup calls go through ``get_success_data``, so a broken setup step fails
loudly with the server's own error identifier instead of surfacing later as a
confusing assertion.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    ADOPTION_MODEL_OPEN_TERRITORY,
    DEPTH_MASTERY,
    REVISION_PLAN_PLAN,
    REVISION_PLAN_SUNSET,
    VOTE_RECOMMEND,
)
from .test_users import (
    COMMITTEE_MEMBER_HEADERS,
    PUBLIC_COMMENTER_HEADERS,
    make_editorial_director_headers,
    make_platform_admin_headers,
    make_pricing_manager_headers,
    make_publisher_editor_headers,
    make_review_committee_member_headers,
    make_sales_rep_headers,
    make_state_adoption_officer_headers,
)

Headers = Dict[str, str]

# Instants the builders walk the logical clock through.
CLOCK_INSIDE_SUBMISSION_WINDOW = "2026-09-15T00:00:00Z"
CLOCK_AT_SUBMISSION_DEADLINE = "2026-10-01T00:00:00Z"
CLOCK_AFTER_COMMITTEE_REVIEW = "2026-10-16T00:00:00Z"
CLOCK_AT_PANEL_SESSION_START = "2026-10-20T14:00:00Z"

ADMIN = make_platform_admin_headers()
EDITOR = make_publisher_editor_headers("ed-1")
DIRECTOR = make_editorial_director_headers("dir-1")
PRICING = make_pricing_manager_headers("pm-1")
QUOTING_REP = make_sales_rep_headers("rep-1")
CONFIRMING_REP = make_sales_rep_headers("rep-2")


# ---------------------------------------------------------------------------
# The world under test
# ---------------------------------------------------------------------------


@dataclass
class AdoptionWorld:
    """Identifiers of everything a builder has created so far."""

    state_id: str
    officer: Headers
    standard_codes: List[str] = field(default_factory=list)
    cycle_id: Optional[str] = None
    title_id: Optional[str] = None
    bundle_id: Optional[str] = None
    submission_id: Optional[str] = None
    correlation_ids: List[str] = field(default_factory=list)
    comment_ids: List[str] = field(default_factory=list)
    panel_id: Optional[str] = None
    slot_id: Optional[str] = None
    slot_ids: List[str] = field(default_factory=list)
    proposal_id: Optional[str] = None
    order_id: Optional[str] = None
    content_edit_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Tier 1 - single steps
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, instant: str) -> str:
    """Move the logical clock and return the instant the server reports."""
    data = get_success_data(api.set_clock_to(instant, ADMIN))
    return data["current_utc"]


def seed_state(api: ApiClient, state_code: str = "TX", **overrides: Any) -> AdoptionWorld:
    """Register a state profile and return a world rooted at it."""
    data = get_success_data(
        api.create_state_profile(f.state_profile_payload(state_code, **overrides), ADMIN)
    )
    state_id = data["id"]
    return AdoptionWorld(state_id=state_id,
                         officer=make_state_adoption_officer_headers(state_id))


def seed_standard(
    api: ApiClient,
    world: AdoptionWorld,
    standard_code: str,
    subject: str = "MATH",
    grade_low: int = 5,
    grade_high: int = 5,
    weight: int = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    """Add one standard to the state's framework."""
    data = get_success_data(
        api.add_state_standard(
            world.state_id,
            f.state_standard_payload(
                standard_code,
                subject=subject,
                grade_low=grade_low,
                grade_high=grade_high,
                weight=weight,
                **overrides,
            ),
            world.officer,
        )
    )
    world.standard_codes.append(standard_code)
    return data


def seed_cycle(
    api: ApiClient,
    world: AdoptionWorld,
    subject: str = "MATH",
    cycle_year: int = 2027,
    **overrides: Any,
) -> str:
    """Open an adoption cycle on the standard calendar."""
    data = get_success_data(
        api.create_adoption_cycle(
            f.adoption_cycle_payload(
                world.state_id, subject=subject, cycle_year=cycle_year, **overrides
            ),
            world.officer,
        )
    )
    world.cycle_id = data["id"]
    return world.cycle_id


def seed_title(
    api: ApiClient,
    world: AdoptionWorld,
    release: bool = True,
    receipt_units: int = 0,
    **overrides: Any,
) -> str:
    """Create a print edition, optionally releasing it and receiving stock."""
    data = get_success_data(api.create_title(f.title_payload(**overrides), EDITOR))
    title_id = data["id"]
    if release:
        get_success_data(api.release_title(title_id, EDITOR))
    if receipt_units:
        get_success_data(
            api.adjust_inventory(
                title_id, f.inventory_receipt_payload(receipt_units), ADMIN
            )
        )
    world.title_id = title_id
    return title_id


def seed_bundle(api: ApiClient, world: AdoptionWorld, **overrides: Any) -> str:
    """Define an ancillary bundle on the world's title."""
    data = get_success_data(
        api.create_ancillary_bundle(
            world.title_id, f.ancillary_bundle_payload(**overrides), PRICING
        )
    )
    world.bundle_id = data["id"]
    return world.bundle_id


# ---------------------------------------------------------------------------
# Tier 2 - hierarchies
# ---------------------------------------------------------------------------


def advance_phase(api: ApiClient, world: AdoptionWorld, times: int = 1) -> Dict[str, Any]:
    """Advance the cycle one phase at a time and return its final state."""
    data: Dict[str, Any] = {}
    for _ in range(times):
        data = get_success_data(api.advance_cycle_phase(world.cycle_id, world.officer))
    return data


def seed_open_cycle(
    api: ApiClient,
    state_code: str = "TX",
    subject: str = "MATH",
    grade: int = 5,
    standard_code: Optional[str] = None,
    standard_weight: int = 3,
    cycle_year: int = 2027,
    state_overrides: Optional[Dict[str, Any]] = None,
    cycle_overrides: Optional[Dict[str, Any]] = None,
    title_overrides: Optional[Dict[str, Any]] = None,
    receipt_units: int = 0,
    clock: str = CLOCK_INSIDE_SUBMISSION_WINDOW,
) -> AdoptionWorld:
    """A state with one framework standard, an OPEN cycle and an ACTIVE title.

    The clock is moved inside the submission window and the cycle is advanced
    once, which is what carries it from SCHEDULED to OPEN.
    """
    world = seed_state(api, state_code, **(state_overrides or {}))
    code = standard_code or f"{state_code}.{subject[0]}.{grade}.1"
    seed_standard(
        api,
        world,
        code,
        subject=subject,
        grade_low=grade,
        grade_high=grade,
        weight=standard_weight,
    )
    seed_cycle(
        api,
        world,
        subject=subject,
        cycle_year=cycle_year,
        **(cycle_overrides or {}),
    )
    title_defaults: Dict[str, Any] = {
        "subject": subject,
        "grade_low": grade,
        "grade_high": grade,
    }
    title_defaults.update(title_overrides or {})
    seed_title(api, world, receipt_units=receipt_units, **title_defaults)
    set_clock(api, clock)
    advance_phase(api, world)
    return world


def seed_draft_submission(
    api: ApiClient,
    world: AdoptionWorld,
    title_id: Optional[str] = None,
    depth_levels: Sequence[str] = (DEPTH_MASTERY,),
    standard_codes: Optional[Sequence[str]] = None,
) -> str:
    """Start a draft submission and document one correlation entry per depth."""
    data = get_success_data(
        api.create_submission(
            f.submission_payload(world.cycle_id, title_id or world.title_id), EDITOR
        )
    )
    submission_id = data["id"]
    codes = list(standard_codes or world.standard_codes)
    for index, depth in enumerate(depth_levels):
        code = codes[index] if index < len(codes) else codes[0]
        entry = get_success_data(
            api.create_correlation(
                submission_id, f.correlation_payload(code, depth_level=depth), EDITOR
            )
        )
        world.correlation_ids.append(entry["id"])
    world.submission_id = submission_id
    return submission_id


# ---------------------------------------------------------------------------
# Tier 3 - lifecycle shortcuts
# ---------------------------------------------------------------------------


def file_submission(
    api: ApiClient, world: AdoptionWorld, submission_id: Optional[str] = None
) -> Dict[str, Any]:
    """File the submission with the state."""
    return get_success_data(
        api.file_submission(submission_id or world.submission_id, EDITOR)
    )


def seed_filed_submission(
    api: ApiClient,
    state_code: str = "TX",
    subject: str = "MATH",
    grade: int = 5,
    **kwargs: Any,
) -> AdoptionWorld:
    """A world whose single submission has been filed with the state."""
    world = seed_open_cycle(api, state_code, subject=subject, grade=grade, **kwargs)
    seed_draft_submission(api, world)
    file_submission(api, world)
    return world


def seed_companion_filed_submission(
    api: ApiClient,
    world: AdoptionWorld,
    isbn_base: str,
    subject: str = "MATH",
    grade: int = 5,
) -> Dict[str, str]:
    """A second released edition in the same cycle, filed, leaving `world` pinned.

    Returns the new title and submission ids; `world.submission_id` keeps pointing
    at the world's own submission so the caller can drive both independently.
    """
    title = get_success_data(
        api.create_title(
            f.title_payload(
                subject=subject,
                grade_low=grade,
                grade_high=grade,
                isbn_base=isbn_base,
            ),
            EDITOR,
        )
    )
    get_success_data(api.release_title(title["id"], EDITOR))
    primary = world.submission_id
    submission_id = seed_draft_submission(api, world, title_id=title["id"])
    file_submission(api, world, submission_id)
    world.submission_id = primary
    return {"title_id": title["id"], "submission_id": submission_id}


def accept_correlations(
    api: ApiClient,
    world: AdoptionWorld,
    entry_ids: Optional[Sequence[str]] = None,
    member: Optional[Headers] = None,
) -> None:
    """Record an ACCEPT verdict on the named correlation entries."""
    reviewer = member or make_review_committee_member_headers("cm-1")
    for entry_id in entry_ids or world.correlation_ids:
        get_success_data(
            api.record_correlation_verdict(
                world.submission_id, entry_id, {"verdict": "ACCEPT"}, reviewer
            )
        )


def file_price_proposal(
    api: ApiClient,
    world: AdoptionWorld,
    submission_id: Optional[str] = None,
    **overrides: Any,
) -> str:
    """File a price proposal against the submission's current record version."""
    target = submission_id or world.submission_id
    version = api.read_submission_version(target, PRICING)
    data = get_success_data(
        api.create_pricing_proposal(
            f.pricing_proposal_payload(target, version, **overrides), PRICING
        )
    )
    world.proposal_id = data["id"]
    return world.proposal_id


def approve_price_proposal(
    api: ApiClient, world: AdoptionWorld, proposal_id: Optional[str] = None
) -> Dict[str, Any]:
    """Record the state's approval of a filed price proposal."""
    return get_success_data(
        api.decide_pricing_proposal(
            proposal_id or world.proposal_id, {"verdict": "APPROVE"}, world.officer
        )
    )


def seed_priced_submission(
    api: ApiClient,
    state_code: str = "TX",
    subject: str = "MATH",
    grade: int = 5,
    proposal_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> AdoptionWorld:
    """A filed submission with an accepted correlation and an approved price.

    PRD 2.6 rule 20 admits ``recording entry verdicts`` only while the submission
    is ``DRAFT``, so the committee verdicts are registered before the filing and
    not after it.
    """
    world = seed_open_cycle(api, state_code, subject=subject, grade=grade, **kwargs)
    seed_draft_submission(api, world)
    accept_correlations(api, world)
    file_submission(api, world)
    file_price_proposal(api, world, **(proposal_overrides or {}))
    approve_price_proposal(api, world)
    return world


def seed_panel(
    api: ApiClient, world: AdoptionWorld, panel_label: str = "Panel A", **overrides: Any
) -> str:
    """Seat a review committee panel for the world's cycle."""
    data = get_success_data(
        api.create_committee_panel(
            f.committee_panel_payload(world.cycle_id, panel_label=panel_label, **overrides),
            world.officer,
        )
    )
    world.panel_id = data["id"]
    return world.panel_id


def reserve_slot(
    api: ApiClient,
    world: AdoptionWorld,
    submission_id: Optional[str] = None,
    start_at: str = "2026-10-20T14:00:00Z",
    end_at: str = "2026-10-20T14:30:00Z",
    panel_id: Optional[str] = None,
) -> str:
    """Reserve a presentation slot, reading the panel's live record version."""
    panel = panel_id or world.panel_id
    version = api.read_panel_version(panel, world.officer)
    data = get_success_data(
        api.reserve_slot(
            panel,
            f.slot_payload(
                submission_id or world.submission_id,
                version,
                start_at=start_at,
                end_at=end_at,
            ),
            world.officer,
        )
    )
    world.slot_id = data["id"]
    world.slot_ids.append(data["id"])
    return data["id"]


def seed_scheduled_submission(
    api: ApiClient,
    state_code: str = "TX",
    subject: str = "MATH",
    grade: int = 5,
    panel_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> AdoptionWorld:
    """A filed submission holding a RESERVED slot on a seated panel."""
    world = seed_filed_submission(api, state_code, subject=subject, grade=grade, **kwargs)
    seed_panel(api, world, **(panel_overrides or {}))
    reserve_slot(api, world)
    return world


def advance_to_in_review(
    api: ApiClient, world: AdoptionWorld, clock: str = CLOCK_AFTER_COMMITTEE_REVIEW
) -> Dict[str, Any]:
    """Move the clock past the committee review date and advance twice."""
    set_clock(api, clock)
    return advance_phase(api, world, times=2)


def open_session(api: ApiClient, world: AdoptionWorld, panel_id: Optional[str] = None):
    """Open the panel's session."""
    return get_success_data(
        api.open_panel_session(panel_id or world.panel_id, world.officer)
    )


def present_slot(api: ApiClient, world: AdoptionWorld, slot_id: Optional[str] = None):
    """Mark the slot's submission as presented to the seated committee."""
    return get_success_data(
        api.present_slot(slot_id or world.slot_id, world.officer)
    )


def seed_presented_slot(
    api: ApiClient,
    state_code: str = "TX",
    subject: str = "MATH",
    grade: int = 5,
    priced: bool = True,
    panel_overrides: Optional[Dict[str, Any]] = None,
    proposal_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> AdoptionWorld:
    """A submission standing at its slot in front of an open panel session.

    With ``priced`` left true the correlation is accepted and a price proposal is
    approved first, which is what the four adoption gates need.
    """
    if priced:
        world = seed_priced_submission(
            api,
            state_code,
            subject=subject,
            grade=grade,
            proposal_overrides=proposal_overrides,
            **kwargs,
        )
    else:
        world = seed_filed_submission(api, state_code, subject=subject, grade=grade, **kwargs)
    seed_panel(api, world, **(panel_overrides or {}))
    reserve_slot(api, world)
    advance_to_in_review(api, world)
    set_clock(api, CLOCK_AT_PANEL_SESSION_START)
    open_session(api, world)
    present_slot(api, world)
    return world


def cast_ballots(
    api: ApiClient,
    slot_id: str,
    votes: Sequence[str],
    members: Optional[Sequence[Headers]] = None,
) -> None:
    """Cast one ballot per named vote, each from a different committee member."""
    seats = members or COMMITTEE_MEMBER_HEADERS
    for index, vote in enumerate(votes):
        get_success_data(
            api.cast_vote(slot_id, f.vote_payload(vote), seats[index])
        )


def tally_slot(api: ApiClient, world: AdoptionWorld, slot_id: Optional[str] = None):
    """Tally the slot's ballot log."""
    return get_success_data(api.tally_slot(slot_id or world.slot_id, world.officer))


# ---------------------------------------------------------------------------
# Tier 4 - accumulation and threshold targeting
# ---------------------------------------------------------------------------


def stack_public_comments(
    api: ApiClient,
    world: AdoptionWorld,
    severities: Sequence[str],
    categories: Optional[Sequence[str]] = None,
) -> List[str]:
    """File one public comment per named severity, each from a different commenter."""
    ids: List[str] = []
    for index, severity in enumerate(severities):
        payload = f.public_comment_payload(
            commenter_ref=f"parent-{index + 1:02d}", severity=severity
        )
        if categories is not None:
            payload["category"] = categories[index]
        data = get_success_data(
            api.create_public_comment(
                world.submission_id, payload, PUBLIC_COMMENTER_HEADERS[index]
            )
        )
        ids.append(data["id"])
    world.comment_ids.extend(ids)
    return ids


def respond_to_comment(api: ApiClient, comment_id: str) -> Dict[str, Any]:
    """Publish the publisher's response to one public comment."""
    return get_success_data(
        api.respond_to_public_comment(comment_id, f.comment_response_payload(), EDITOR)
    )


def ship_sampling_copies_to(
    api: ApiClient, world: AdoptionWorld, units: int
) -> Dict[str, Any]:
    """Ship print sample copies toward the state's sampling requirement."""
    return get_success_data(
        api.ship_sampling_copies(
            world.submission_id, f.sampling_shipment_payload(units), EDITOR
        )
    )


# ---------------------------------------------------------------------------
# Tier 5 - terminal states
# ---------------------------------------------------------------------------


def seed_adopted_submission(
    api: ApiClient,
    state_code: str = "CA",
    subject: str = "MATH",
    grade: int = 5,
    **kwargs: Any,
) -> AdoptionWorld:
    """A submission carried all the way to ADOPTED by a unanimous panel."""
    world = seed_presented_slot(api, state_code, subject=subject, grade=grade, **kwargs)
    cast_ballots(api, world.slot_id, [VOTE_RECOMMEND] * 3)
    tally_slot(api, world)
    return world


def quote_order(
    api: ApiClient,
    world: AdoptionWorld,
    print_units: int = 100,
    digital_seats: int = 0,
    with_proposal: bool = False,
    title_id: Optional[str] = None,
    **overrides: Any,
) -> str:
    """Quote a district order against the world's title."""
    payload = f.district_order_payload(
        world.state_id,
        title_id or world.title_id,
        print_units=print_units,
        digital_seats=digital_seats,
        **overrides,
    )
    if with_proposal and world.proposal_id:
        payload["pricing_proposal_id"] = world.proposal_id
    data = get_success_data(api.create_district_order(payload, QUOTING_REP))
    world.order_id = data["id"]
    return world.order_id


def confirm_order(
    api: ApiClient, world: AdoptionWorld, order_id: Optional[str] = None
) -> Dict[str, Any]:
    """Confirm a quoted order as the representative who did not quote it."""
    return get_success_data(
        api.confirm_district_order(order_id or world.order_id, CONFIRMING_REP)
    )


def seed_confirmed_order(
    api: ApiClient,
    state_code: str = "NE",
    print_units: int = 100,
    digital_seats: int = 0,
    receipt_units: int = 500,
    title_overrides: Optional[Dict[str, Any]] = None,
) -> AdoptionWorld:
    """An open-territory district order that has been quoted and confirmed."""
    world = seed_state(
        api, state_code, adoption_model=ADOPTION_MODEL_OPEN_TERRITORY,
        sampling_copies_required=0,
    )
    seed_title(api, world, receipt_units=receipt_units, **(title_overrides or {}))
    quote_order(api, world, print_units=print_units, digital_seats=digital_seats)
    confirm_order(api, world)
    return world


def propose_content_edit(
    api: ApiClient,
    world: AdoptionWorld,
    topic_code: str = "DATA_LITERACY",
    pages_delta: int = 24,
    proposer: Optional[Headers] = None,
    **overrides: Any,
) -> str:
    """Propose a state-specific content edit on the world's title."""
    data = get_success_data(
        api.create_content_edit(
            f.content_edit_payload(
                world.title_id,
                world.state_id,
                topic_code=topic_code,
                pages_delta=pages_delta,
                **overrides,
            ),
            proposer or EDITOR,
        )
    )
    world.content_edit_id = data["id"]
    return world.content_edit_id


def approve_content_edit(
    api: ApiClient, world: AdoptionWorld, edit_id: Optional[str] = None
) -> Dict[str, Any]:
    """Record the editorial director's approval of a proposed edit."""
    return get_success_data(
        api.review_content_edit(
            edit_id or world.content_edit_id, {"verdict": "APPROVE"}, DIRECTOR
        )
    )


def reject_content_edit(
    api: ApiClient,
    world: AdoptionWorld,
    reason: str = "The lesson sequence conflicts with the pacing guide.",
    edit_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Record the editorial director's rejection of a proposed edit."""
    return get_success_data(
        api.review_content_edit(
            edit_id or world.content_edit_id,
            {"verdict": "REJECT", "rejection_reason": reason},
            DIRECTOR,
        )
    )


def resubmit_content_edit(
    api: ApiClient,
    world: AdoptionWorld,
    rationale: str = "Re-sequenced the inserted lessons after the previous unit.",
    edit_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Resubmit a rejected edit for another review round."""
    payload: Dict[str, Any] = {"rationale": rationale}
    payload.update(overrides)
    return get_success_data(
        api.resubmit_content_edit(edit_id or world.content_edit_id, payload, EDITOR)
    )


def seed_applied_content_edit(
    api: ApiClient,
    world: AdoptionWorld,
    topic_code: str = "DATA_LITERACY",
    pages_delta: int = 40,
) -> str:
    """Propose, approve and apply one content edit to the world's title."""
    edit_id = propose_content_edit(
        api, world, topic_code=topic_code, pages_delta=pages_delta
    )
    approve_content_edit(api, world, edit_id)
    get_success_data(api.apply_content_edit(edit_id, DIRECTOR))
    return edit_id


def sunset_title(api: ApiClient, title_id: str, target_year: int = 2029) -> None:
    """Plan and then execute the revision that retires an edition."""
    get_success_data(
        api.revision_plan(
            title_id,
            {"action": REVISION_PLAN_PLAN, "revision_target_cycle_year": target_year},
            DIRECTOR,
        )
    )
    get_success_data(api.revision_plan(title_id, {"action": REVISION_PLAN_SUNSET}, DIRECTOR))

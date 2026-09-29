"""Composite setup helpers.

Every helper builds its state from scratch through PRD-declared endpoints, so
each test starts from an empty database. All setup calls go through the lenient
``get_success_data`` validator so a broken precondition reports itself as a
setup failure rather than as a confusing assertion failure.

The helpers are organised as tiers:

* tier 1 — single-entity state progression (conference lifecycle, member
  activation);
* tier 2 — entity hierarchy (conference + category + authors + committee);
* tier 3 — full-lifecycle shortcuts (submitted -> scored -> decided ->
  confirmed -> scheduled);
* tier 4 — accumulation / threshold targeting (reviewer load, format capacity,
  CME minute pool, session packing);
* tier 5 — finalisation (published program, validated accreditation, applied
  change request).
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_BEFORE_DEADLINES
from .factories import (
    accreditation_validation_payload,
    assign_arbiter_payload,
    change_request_adjudication_payload,
    create_abstract_payload,
    create_accreditation_payload,
    create_author_payload,
    create_category_payload,
    create_committee_member_payload,
    create_conference_payload,
    create_conflict_declaration_payload,
    create_disclosure_statement_payload,
    create_program_change_request_payload,
    create_session_payload,
    create_session_slot_payload,
    decision_payload,
    decline_review_payload,
    disclosure_adjudication_payload,
    press_action_payload,
    register_author_payload,
    resolution_payload,
    review_assignment_payload,
    revise_abstract_payload,
    set_clock_payload,
    status_transition_payload,
    submit_review_payload,
)
from .test_users import (
    ADMIN,
    PRESS,
    make_author_headers,
    make_program_chair_headers,
    make_reviewer_headers,
)

CONFERENCE_PHASES = [
    "DRAFT",
    "CFA_OPEN",
    "CFA_CLOSED",
    "REVIEW_OPEN",
    "REVIEW_CLOSED",
    "DECISIONS_RELEASED",
    "PROGRAM_PUBLISHED",
]


# ─── Tier 1: single-entity state progression ─────────────────────────────


def set_clock(current_utc: str = CLOCK_BEFORE_DEADLINES) -> dict:
    """Pin the logical clock. Every fixture calls this first."""
    return get_success_data(api_client.set_clock(set_clock_payload(current_utc), ADMIN))


def create_conference(**overrides) -> dict:
    """Create one conference in DRAFT."""
    return get_success_data(
        api_client.create_conference(create_conference_payload(**overrides), ADMIN)
    )


def transition_conference(conference_id: str, to_status: str, **extra) -> dict:
    return get_success_data(
        api_client.transition_conference(
            conference_id, status_transition_payload(to_status, **extra), ADMIN
        )
    )


def advance_conference_to(conference_id: str, target_status: str) -> dict:
    """Walk the conference lifecycle forward one phase at a time."""
    current = get_success_data(api_client.get_conference(conference_id, ADMIN))
    start = CONFERENCE_PHASES.index(current["status"])
    end = CONFERENCE_PHASES.index(target_status)
    latest = current
    for phase in CONFERENCE_PHASES[start + 1 : end + 1]:
        latest = transition_conference(conference_id, phase)
    return latest


def create_category(conference_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_category(
            create_category_payload(conference_id, **overrides), ADMIN
        )
    )


def create_author(
    full_name: str = "Ada Rivera",
    email: str = "ada@lab.example",
    affiliation: str = "Northline University",
) -> dict:
    return get_success_data(
        api_client.create_author(
            create_author_payload(
                full_name=full_name, email=email, affiliation=affiliation
            ),
            ADMIN,
        )
    )


def register_author(author_id: str, is_registered: bool = True) -> dict:
    return get_success_data(
        api_client.register_author(
            author_id, register_author_payload(is_registered), ADMIN
        )
    )


def create_active_member(
    conference_id: str,
    full_name: str,
    email: str,
    member_role: str = "REVIEWER",
    expertise_keywords: Optional[List[str]] = None,
    max_review_load: int = 4,
    calibration_bias: float = 0.00,
    conflict_overrides: Optional[dict] = None,
) -> dict:
    """Create a committee member, file its conflict declaration, activate it."""
    payload = create_committee_member_payload(
        conference_id,
        member_role=member_role,
        full_name=full_name,
        email=email,
        max_review_load=max_review_load,
        calibration_bias=calibration_bias,
    )
    if expertise_keywords is not None:
        payload["expertise_keywords"] = list(expertise_keywords)
    member = get_success_data(api_client.create_committee_member(payload, ADMIN))
    declare_conflict(member["id"], **(conflict_overrides or {}))
    return get_success_data(
        api_client.transition_committee_member(
            member["id"], status_transition_payload("ACTIVE"), ADMIN
        )
    )


def declare_conflict(member_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_conflict_declaration(
            create_conflict_declaration_payload(member_id, **overrides), ADMIN
        )
    )


def get_conference_version(conference_id: str, headers=None) -> int:
    """Read the live conference version for an optimistic-concurrency payload."""
    conference = get_success_data(
        api_client.get_conference(conference_id, headers or ADMIN)
    )
    return conference["version"]


# ─── Tier 2: entity hierarchy ────────────────────────────────────────────


def setup_conference_with_committee(
    conference_overrides: Optional[dict] = None,
    category_overrides: Optional[dict] = None,
    clock: str = CLOCK_BEFORE_DEADLINES,
    reviewer_load: int = 4,
    reviewer_keywords: Optional[List[str]] = None,
    second_reviewer_keywords: Optional[List[str]] = None,
    calibration_bias: float = 0.00,
) -> dict:
    """Clock + conference in DRAFT + one category + two authors + two chairs +
    two active reviewers. Returns the shared world dictionary that every other
    fixture threads through.
    """
    set_clock(clock)
    conference = create_conference(**(conference_overrides or {}))
    category = create_category(conference["id"], **(category_overrides or {}))
    ada = create_author("Ada Rivera", "ada@lab.example")
    ben = create_author("Ben Okafor", "ben@lab.example")
    cho = create_active_member(
        conference["id"],
        "Cho Bekele",
        "cho@panel.example",
        member_role="CHAIR",
        expertise_keywords=["oncology", "immunotherapy"],
    )
    dana = create_active_member(
        conference["id"],
        "Dana Petit",
        "dana@panel.example",
        member_role="CHAIR",
        expertise_keywords=["oncology", "ethics"],
    )
    rui = create_active_member(
        conference["id"],
        "Rui Alvarez",
        "rui@panel.example",
        member_role="REVIEWER",
        expertise_keywords=reviewer_keywords or ["oncology", "imaging"],
        max_review_load=reviewer_load,
        calibration_bias=calibration_bias,
    )
    mei = create_active_member(
        conference["id"],
        "Mei Osei",
        "mei@panel.example",
        member_role="REVIEWER",
        expertise_keywords=second_reviewer_keywords or ["oncology", "immunotherapy"],
        max_review_load=reviewer_load,
    )
    return {
        "conference": conference,
        "category": category,
        "authors": {"ada": ada, "ben": ben},
        "members": {"cho": cho, "dana": dana, "rui": rui, "mei": mei},
        "abstracts": [],
        "reviews": {},
        "sessions": [],
        "slots": [],
        "chair_headers": make_program_chair_headers(cho["id"]),
        "second_chair_headers": make_program_chair_headers(dana["id"]),
        "reviewer_headers": make_reviewer_headers(rui["id"]),
        "second_reviewer_headers": make_reviewer_headers(mei["id"]),
        "author_headers": make_author_headers(ada["id"]),
        "coauthor_headers": make_author_headers(ben["id"]),
        "admin_headers": ADMIN,
        "press_headers": PRESS,
    }


def refresh_conference(world: dict) -> dict:
    world["conference"] = get_success_data(
        api_client.get_conference(world["conference"]["id"], ADMIN)
    )
    return world["conference"]


def open_call_for_abstracts(world: dict) -> dict:
    world["conference"] = transition_conference(world["conference"]["id"], "CFA_OPEN")
    return world["conference"]


def submit_abstract(world: dict, author_key: str = "ada", **overrides) -> dict:
    """Submit one abstract as the named author and record it on the world."""
    author = world["authors"][author_key]
    payload = create_abstract_payload(
        world["conference"]["id"],
        overrides.pop("category_id", world["category"]["id"]),
        author["id"],
        **overrides,
    )
    abstract = get_success_data(
        api_client.create_abstract(payload, make_author_headers(author["id"]))
    )
    world["abstracts"].append(abstract)
    return abstract


def open_review_phase(world: dict) -> dict:
    """CFA_CLOSED then REVIEW_OPEN."""
    world["conference"] = advance_conference_to(world["conference"]["id"], "REVIEW_OPEN")
    return world["conference"]


def assign_review(
    world: dict, abstract_id: str, reviewer_member_id: Optional[str] = None, **overrides
) -> dict:
    """Assign one review as the first chair; omit reviewer_member_id to let the
    server run its own reviewer selection."""
    payload = review_assignment_payload(**overrides)
    if reviewer_member_id is not None:
        payload["reviewer_member_id"] = reviewer_member_id
    review = get_success_data(
        api_client.create_review_assignment(
            abstract_id, payload, world["chair_headers"]
        )
    )
    world["reviews"].setdefault(abstract_id, []).append(review)
    return review


def submit_review_as(world: dict, review: dict, reviewer_key: str, **score_overrides) -> dict:
    """Submit a review with the reviewing member's own identity."""
    member = world["members"][reviewer_key]
    headers = (
        make_program_chair_headers(member["id"])
        if member["member_role"] == "CHAIR"
        else make_reviewer_headers(member["id"])
    )
    return get_success_data(
        api_client.submit_review(
            review["id"], submit_review_payload(**score_overrides), headers
        )
    )


def decline_review_as(world: dict, review: dict, reviewer_key: str, **overrides) -> dict:
    member = world["members"][reviewer_key]
    headers = (
        make_program_chair_headers(member["id"])
        if member["member_role"] == "CHAIR"
        else make_reviewer_headers(member["id"])
    )
    return get_success_data(
        api_client.decline_review(
            review["id"], decline_review_payload(**overrides), headers
        )
    )


# ─── Tier 3: full-lifecycle shortcuts ────────────────────────────────────

HIGH_REVIEW = {
    "score_originality": 4,
    "score_methodology": 4,
    "score_relevance": 4,
    "score_clarity": 4,
    "confidence": "HIGH",
    "recommended_format": "ORAL",
}
MEDIUM_REVIEW = {
    "score_originality": 3,
    "score_methodology": 3,
    "score_relevance": 3,
    "score_clarity": 3,
    "confidence": "MEDIUM",
    "recommended_format": "ORAL",
}


def setup_abstract_under_review(
    conference_overrides: Optional[dict] = None,
    category_overrides: Optional[dict] = None,
    abstract_overrides: Optional[dict] = None,
    **world_overrides,
) -> dict:
    """World with one abstract and two ASSIGNED reviews, conference REVIEW_OPEN."""
    world = setup_conference_with_committee(
        conference_overrides=conference_overrides,
        category_overrides=category_overrides,
        **world_overrides,
    )
    open_call_for_abstracts(world)
    abstract = submit_abstract(world, **(abstract_overrides or {}))
    open_review_phase(world)
    assign_review(world, abstract["id"], world["members"]["rui"]["id"])
    assign_review(world, abstract["id"], world["members"]["mei"]["id"])
    return world


def setup_scored_abstract(
    conference_overrides: Optional[dict] = None,
    category_overrides: Optional[dict] = None,
    abstract_overrides: Optional[dict] = None,
    first_review: Optional[dict] = None,
    second_review: Optional[dict] = None,
    **world_overrides,
) -> dict:
    """One abstract with two SUBMITTED reviews; conference still REVIEW_OPEN."""
    world = setup_abstract_under_review(
        conference_overrides=conference_overrides,
        category_overrides=category_overrides,
        abstract_overrides=abstract_overrides,
        **world_overrides,
    )
    abstract = world["abstracts"][0]
    reviews = world["reviews"][abstract["id"]]
    submit_review_as(world, reviews[0], "rui", **(first_review or HIGH_REVIEW))
    submit_review_as(world, reviews[1], "mei", **(second_review or MEDIUM_REVIEW))
    world["abstracts"][0] = get_success_data(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    return world


def setup_scored_abstracts(
    count: int,
    conference_overrides: Optional[dict] = None,
    category_overrides: Optional[dict] = None,
    abstract_overrides: Optional[List[dict]] = None,
    reviewer_load: int = 8,
    **world_overrides,
) -> dict:
    """``count`` abstracts each carrying two SUBMITTED reviews (4/4/4/4 HIGH and
    3/3/3/3 MEDIUM), conference still REVIEW_OPEN."""
    world = setup_conference_with_committee(
        conference_overrides=conference_overrides,
        category_overrides=category_overrides,
        reviewer_load=reviewer_load,
        **world_overrides,
    )
    open_call_for_abstracts(world)
    titles = [
        "Immunotherapy response imaging",
        "Adaptive radiotherapy curriculum",
        "Survivorship clinic redesign",
        "Palliative pathway audit",
    ]
    for index in range(count):
        extra = (abstract_overrides or [{}] * count)[index]
        payload = {"title": titles[index % len(titles)]}
        payload.update(extra)
        submit_abstract(world, **payload)
    open_review_phase(world)
    for abstract in world["abstracts"]:
        first = assign_review(world, abstract["id"], world["members"]["rui"]["id"])
        second = assign_review(world, abstract["id"], world["members"]["mei"]["id"])
        submit_review_as(world, first, "rui", **HIGH_REVIEW)
        submit_review_as(world, second, "mei", **MEDIUM_REVIEW)
    world["abstracts"] = [
        get_success_data(api_client.get_abstract(a["id"], world["chair_headers"]))
        for a in world["abstracts"]
    ]
    return world


def close_review_phase(world: dict) -> dict:
    world["conference"] = transition_conference(world["conference"]["id"], "REVIEW_CLOSED")
    return world["conference"]


def decide_abstract(world: dict, abstract_id: str, decision: str, **overrides) -> dict:
    """Read the live conference version, then commit the decision as the chair."""
    version = get_conference_version(world["conference"]["id"], world["chair_headers"])
    return get_success_data(
        api_client.decide_abstract(
            abstract_id,
            decision_payload(decision, version, **overrides),
            world["chair_headers"],
        )
    )


def setup_decided_abstract(
    decision: str = "ORAL",
    conference_overrides: Optional[dict] = None,
    category_overrides: Optional[dict] = None,
    abstract_overrides: Optional[dict] = None,
    **world_overrides,
) -> dict:
    """One abstract carried through to a committed decision; conference
    REVIEW_CLOSED."""
    world = setup_scored_abstract(
        conference_overrides=conference_overrides,
        category_overrides=category_overrides,
        abstract_overrides=abstract_overrides,
        **world_overrides,
    )
    close_review_phase(world)
    world["abstracts"][0] = decide_abstract(
        world, world["abstracts"][0]["id"], decision
    )
    return world


def release_decisions(world: dict) -> dict:
    world["conference"] = transition_conference(
        world["conference"]["id"], "DECISIONS_RELEASED"
    )
    return world["conference"]


def confirm_abstract(world: dict, abstract_id: str, author_key: str = "ada") -> dict:
    """Register the author, then confirm the accepted abstract as that author."""
    author = world["authors"][author_key]
    register_author(author["id"], True)
    return get_success_data(
        api_client.transition_abstract(
            abstract_id,
            status_transition_payload("CONFIRMED"),
            make_author_headers(author["id"]),
        )
    )


def setup_confirmed_abstract(
    decision: str = "ORAL",
    conference_overrides: Optional[dict] = None,
    category_overrides: Optional[dict] = None,
    abstract_overrides: Optional[dict] = None,
    **world_overrides,
) -> dict:
    """Decision released and the abstract CONFIRMED by its author."""
    world = setup_decided_abstract(
        decision=decision,
        conference_overrides=conference_overrides,
        category_overrides=category_overrides,
        abstract_overrides=abstract_overrides,
        **world_overrides,
    )
    release_decisions(world)
    world["abstracts"][0] = confirm_abstract(world, world["abstracts"][0]["id"])
    return world


def create_session(world: dict, chair_key: str = "cho", **overrides) -> dict:
    chair = world["members"][chair_key]
    session = get_success_data(
        api_client.create_session(
            create_session_payload(world["conference"]["id"], chair["id"], **overrides),
            make_program_chair_headers(chair["id"]),
        )
    )
    world["sessions"].append(session)
    return session


def add_slot(
    world: dict,
    session: dict,
    abstract_id: str,
    presenter_author_id: str,
    position: int = 1,
    duration_minutes: int = 25,
    chair_key: str = "cho",
    expected_session_version: Optional[int] = None,
) -> dict:
    """Add one slot, reading the live session version unless one is pinned."""
    chair = world["members"][chair_key]
    if expected_session_version is None:
        live = get_success_data(
            api_client.get_session(session["id"], make_program_chair_headers(chair["id"]))
        )
        expected_session_version = live["version"]
    slot = get_success_data(
        api_client.create_session_slot(
            session["id"],
            create_session_slot_payload(
                abstract_id,
                presenter_author_id,
                position,
                duration_minutes,
                expected_session_version,
            ),
            make_program_chair_headers(chair["id"]),
        )
    )
    world["slots"].append(slot)
    return slot


def setup_scheduled_slot(
    conference_overrides: Optional[dict] = None,
    category_overrides: Optional[dict] = None,
    abstract_overrides: Optional[dict] = None,
    session_overrides: Optional[dict] = None,
    duration_minutes: int = 25,
    **world_overrides,
) -> dict:
    """Full lifecycle to one SCHEDULED slot holding a CONFIRMED abstract."""
    world = setup_confirmed_abstract(
        conference_overrides=conference_overrides,
        category_overrides=category_overrides,
        abstract_overrides=abstract_overrides,
        **world_overrides,
    )
    session = create_session(world, **(session_overrides or {}))
    add_slot(
        world,
        session,
        world["abstracts"][0]["id"],
        world["authors"]["ada"]["id"],
        duration_minutes=duration_minutes,
    )
    return world


# ─── Tier 4: accumulation / threshold targeting ──────────────────────────


def setup_reviewer_at_load_ceiling(
    max_review_load: int = 1, abstract_count: int = 2, **world_overrides
) -> dict:
    """Drive one reviewer's current_review_load up to max_review_load by
    assigning it that many live reviews across separate abstracts."""
    world = setup_conference_with_committee(
        reviewer_load=max_review_load, **world_overrides
    )
    open_call_for_abstracts(world)
    titles = [
        "Immunotherapy response imaging",
        "Adaptive radiotherapy curriculum",
        "Survivorship clinic redesign",
    ]
    for index in range(abstract_count):
        submit_abstract(world, title=titles[index % len(titles)])
    open_review_phase(world)
    for index in range(max_review_load):
        assign_review(
            world,
            world["abstracts"][index]["id"],
            world["members"]["rui"]["id"],
        )
    world["members"]["rui"] = get_success_data(
        api_client.get_committee_member(
            world["members"]["rui"]["id"], world["chair_headers"]
        )
    )
    return world


def setup_capacity_exhausted_conference(
    oral_slot_capacity: int = 1,
    poster_slot_capacity: int = 0,
    workshop_slot_capacity: int = 0,
    abstract_count: int = 2,
    **world_overrides,
) -> dict:
    """Conference at REVIEW_CLOSED whose ORAL capacity is already consumed by a
    committed decision, with a further SCORED abstract still undecided."""
    world = setup_scored_abstracts(
        abstract_count,
        conference_overrides={
            "oral_slot_capacity": oral_slot_capacity,
            "poster_slot_capacity": poster_slot_capacity,
            "workshop_slot_capacity": workshop_slot_capacity,
        },
        **world_overrides,
    )
    close_review_phase(world)
    for index in range(oral_slot_capacity):
        world["abstracts"][index] = decide_abstract(
            world, world["abstracts"][index]["id"], "ORAL"
        )
    refresh_conference(world)
    return world


def setup_session_with_packed_slots(
    slot_durations: Optional[List[int]] = None,
    session_overrides: Optional[dict] = None,
    **world_overrides,
) -> dict:
    """A session holding one SCHEDULED slot per entry in ``slot_durations``, each
    presented by its own registered author, so packing boundaries are reachable.
    """
    slot_durations = slot_durations or [25, 25]
    world = setup_scored_abstracts(
        len(slot_durations),
        conference_overrides={
            "oral_slot_capacity": max(3, len(slot_durations)),
            "poster_slot_capacity": 2,
            "workshop_slot_capacity": 1,
        },
        **world_overrides,
    )
    close_review_phase(world)
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = decide_abstract(world, abstract["id"], "ORAL")
    release_decisions(world)
    register_author(world["authors"]["ada"]["id"], True)
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = get_success_data(
            api_client.transition_abstract(
                abstract["id"],
                status_transition_payload("CONFIRMED"),
                world["author_headers"],
            )
        )
    session = create_session(world, **(session_overrides or {}))
    for index, duration in enumerate(slot_durations):
        add_slot(
            world,
            session,
            world["abstracts"][index]["id"],
            world["authors"]["ada"]["id"],
            position=index + 1,
            duration_minutes=duration,
        )
    world["sessions"][-1] = get_success_data(
        api_client.get_session(session["id"], world["chair_headers"])
    )
    return world


def setup_discrepancy_case(
    discrepancy_threshold: float = 1.50,
    first_review: Optional[dict] = None,
    second_review: Optional[dict] = None,
    **world_overrides,
) -> dict:
    """Two submitted reviews whose spread reaches the category threshold, so a
    discrepancy case exists. ``world["case"]`` holds it when one was opened."""
    world = setup_scored_abstract(
        category_overrides={
            "discrepancy_threshold": discrepancy_threshold,
            "min_reviews_required": 2,
        },
        first_review=first_review
        or {
            "score_originality": 5,
            "score_methodology": 4,
            "score_relevance": 4,
            "score_clarity": 4,
            "confidence": "HIGH",
            "recommended_format": "ORAL",
        },
        second_review=second_review
        or {
            "score_originality": 3,
            "score_methodology": 2,
            "score_relevance": 3,
            "score_clarity": 2,
            "confidence": "MEDIUM",
            "recommended_format": "POSTER",
        },
        **world_overrides,
    )
    cases, _ = _list(
        api_client.list_discrepancy_cases(
            world["chair_headers"], params={"abstract_id": world["abstracts"][0]["id"]}
        )
    )
    world["case"] = cases[0] if cases else None
    return world


def _list(response):
    body = response.json()
    return body["data"], body["meta"]


# ─── Tier 5: finalisation and terminal states ────────────────────────────


def setup_validated_accreditation(
    content_minutes: int = 20,
    has_financial_relationship: bool = False,
    validate: bool = True,
    **world_overrides,
) -> dict:
    """A decided abstract carrying one accreditation and one adjudicated
    disclosure; the accreditation is validated by the second chair so the
    validator is never the deciding chair."""
    world = setup_decided_abstract(
        category_overrides={"cme_eligible": True, "min_reviews_required": 2},
        **world_overrides,
    )
    abstract = world["abstracts"][0]
    accreditation = get_success_data(
        api_client.create_accreditation(
            create_accreditation_payload(abstract["id"], content_minutes), ADMIN
        )
    )
    disclosure = get_success_data(
        api_client.create_disclosure_statement(
            create_disclosure_statement_payload(
                abstract["id"],
                accreditation["id"],
                world["authors"]["ada"]["id"],
                has_financial_relationship=has_financial_relationship,
                **(
                    {"relationship_entity": "Helix Biopharma"}
                    if has_financial_relationship
                    else {}
                ),
            ),
            world["author_headers"],
        )
    )
    disclosure = get_success_data(
        api_client.adjudicate_disclosure_statement(
            disclosure["id"],
            disclosure_adjudication_payload("VALIDATED"),
            world["second_chair_headers"],
        )
    )
    if validate:
        accreditation = get_success_data(
            api_client.validate_accreditation(
                accreditation["id"],
                accreditation_validation_payload("VALIDATE"),
                world["second_chair_headers"],
            )
        )
    world["accreditation"] = accreditation
    world["disclosure"] = disclosure
    return world


def setup_change_request(
    change_type: str = "SUBSTITUTE_PRESENTER",
    clock_at_submission: str = "2026-08-27T08:00:00Z",
    request_overrides: Optional[dict] = None,
    **world_overrides,
) -> dict:
    """A scheduled slot plus one PENDING change request created after the clock
    has been advanced to ``clock_at_submission``."""
    world = setup_scheduled_slot(**world_overrides)
    set_clock(clock_at_submission)
    overrides = dict(request_overrides or {})
    overrides.setdefault("requested_by_author_id", world["authors"]["ada"]["id"])
    if change_type == "SUBSTITUTE_PRESENTER":
        overrides.setdefault(
            "substitute_presenter_author_id", world["authors"]["ben"]["id"]
        )
    request = get_success_data(
        api_client.create_program_change_request(
            create_program_change_request_payload(
                world["slots"][0]["id"], change_type, **overrides
            ),
            world["chair_headers"],
        )
    )
    world["change_request"] = request
    return world


def approve_change_request(world: dict, request_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.adjudicate_program_change_request(
            request_id,
            change_request_adjudication_payload("APPROVED", **overrides),
            world["chair_headers"],
        )
    )


def publish_program(world: dict) -> dict:
    """Publish every planned session and move the conference to
    PROGRAM_PUBLISHED."""
    for index, session in enumerate(world["sessions"]):
        world["sessions"][index] = get_success_data(
            api_client.transition_session(
                session["id"], status_transition_payload("PUBLISHED"), world["chair_headers"]
            )
        )
    world["conference"] = transition_conference(
        world["conference"]["id"], "PROGRAM_PUBLISHED"
    )
    return world["conference"]


def setup_published_program(**world_overrides) -> dict:
    """A published program holding one SCHEDULED slot."""
    world = setup_scheduled_slot(**world_overrides)
    publish_program(world)
    return world


def setup_embargoed_abstract(
    embargo_until_utc: str = "2026-09-02T12:00:00Z", **world_overrides
) -> dict:
    """A newsworthy decided abstract carrying an EMBARGOED embargo dimension."""
    world = setup_decided_abstract(
        abstract_overrides={"is_newsworthy": True}, **world_overrides
    )
    world["abstracts"][0] = get_success_data(
        api_client.press_action(
            world["abstracts"][0]["id"],
            press_action_payload("SET_EMBARGO", embargo_until_utc=embargo_until_utc),
            PRESS,
        )
    )
    return world


def assign_arbiter(world: dict, case_id: str, arbiter_member_id: str) -> dict:
    return get_success_data(
        api_client.assign_arbiter(
            case_id, assign_arbiter_payload(arbiter_member_id), world["chair_headers"]
        )
    )


def resolve_case(world: dict, case_id: str, resolution_method: str, **overrides) -> dict:
    return get_success_data(
        api_client.resolve_discrepancy_case(
            case_id,
            resolution_payload(resolution_method, **overrides),
            world["chair_headers"],
        )
    )


def revise_abstract(world: dict, abstract_id: str, body_word_count: int, **overrides) -> dict:
    return get_success_data(
        api_client.revise_abstract(
            abstract_id,
            revise_abstract_payload(body_word_count, **overrides),
            world["author_headers"],
        )
    )


def reviews_of(world: dict, abstract_id: str, headers=None) -> List[dict]:
    """Live review rows of one abstract, ordered as the API returns them."""
    data, _ = _list(
        api_client.list_reviews(
            headers or world["chair_headers"], params={"abstract_id": abstract_id}
        )
    )
    return data


def member_of(world: dict, member_key: str, headers=None) -> Dict:
    return get_success_data(
        api_client.get_committee_member(
            world["members"][member_key]["id"], headers or world["chair_headers"]
        )
    )

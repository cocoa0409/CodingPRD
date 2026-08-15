"""Composite setup helpers (PRD §3 workflows).

Tiered builders:
  Tier 1 (stage helpers `st_*`): one logical workflow step each.
  Tier 2 (composite `fx_*`): multi-film festival pipelines reaching a given
         edition phase, returning a ctx dict with every captured entity.

Every setup call goes through get_success_data so failures surface as clear
"Setup step failed" messages with the server's error_id attached.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import DEFAULT_ASSIGNMENT_DUE
from .factories import (
    create_edition_payload, create_category_config_payload,
    create_submitter_payload, create_programmer_payload,
    create_submission_payload, create_score_payload, create_slate_payload,
    create_venue_payload, create_slot_payload, submit_travel_payload,
    issue_agreement_payload, create_juror_payload, create_award_payload,
)
from .test_users import (
    TEST_USERS, make_filmmaker_headers, make_programmer_headers,
    make_juror_headers,
)

ADMIN = TEST_USERS["admin_headers"]
CHAIR = TEST_USERS["chair_headers"]
DIRECTOR = TEST_USERS["director_headers"]
OPS = TEST_USERS["ops_headers"]
TRAVEL = TEST_USERS["travel_headers"]
AWARDS = TEST_USERS["awards_headers"]
PUBLIC = TEST_USERS["public_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-step stage helpers
# ---------------------------------------------------------------------------

def set_clock(iso: str) -> dict:
    """Advance the logical clock (triggers the deferred sweeps of PRD §2.4)."""
    return get_success_data(api.set_clock(iso, ADMIN))


def st_edition(edition_over=None, with_config=True, config_over=None,
               category="SHORT_FILM") -> dict:
    """Create an edition (SETUP) and optionally its category config."""
    edition = get_success_data(
        api.create_edition(create_edition_payload(**(edition_over or {})), ADMIN)
    )
    ctx = {"edition": edition}
    if with_config:
        ctx["config"] = get_success_data(api.create_category_config(
            create_category_config_payload(
                edition["id"], category=category, **(config_over or {})
            ), ADMIN,
        ))
    return ctx


def st_advance(ctx: dict, to_status: str) -> dict:
    """Advance the edition posture; stores the fresh edition back in ctx."""
    ctx["edition"] = get_success_data(
        api.advance_edition(ctx["edition"]["id"], to_status, ADMIN)
    )
    return ctx["edition"]


def st_submitter(overrides=None) -> dict:
    return get_success_data(
        api.create_submitter(create_submitter_payload(**(overrides or {})), PUBLIC)
    )


def st_film(ctx: dict, submitter: dict, overrides=None, pay=True) -> dict:
    """Create a DRAFT submission for the submitter; pay=True drives it to
    SUBMITTED/PAID through checkout + simulated success."""
    film = get_success_data(api.create_submission(
        create_submission_payload(ctx["edition"]["id"], **(overrides or {})),
        make_filmmaker_headers(submitter["id"]),
    ))
    if pay:
        payment = get_success_data(
            api.checkout_submission(film["id"], make_filmmaker_headers(submitter["id"]))
        )
        get_success_data(api.simulate_payment(payment["id"], "SUCCEEDED", ADMIN))
        film = get_success_data(
            api.get_submission(film["id"], make_filmmaker_headers(submitter["id"]))
        )
        ctx.setdefault("payments", {})[film["id"]] = payment
    ctx.setdefault("films_by_id", {})[film["id"]] = film
    return film


def st_rule(ctx: dict, film_id: str, decision: str, reason=None) -> dict:
    return get_success_data(
        api.decide_eligibility(film_id, decision, ADMIN, reason=reason)
    )


def st_programmer(overrides=None) -> dict:
    return get_success_data(
        api.create_programmer(create_programmer_payload(**(overrides or {})), ADMIN)
    )


def st_assign(film_id: str, programmer_id: str, due_at=DEFAULT_ASSIGNMENT_DUE) -> dict:
    return get_success_data(api.create_screener_assignment(
        {
            "submission_id": film_id,
            "programmer_id": programmer_id,
            "due_at": due_at,
        },
        CHAIR,
    ))


def st_score(assignment_id: str, programmer_id: str, overall=8, **score_over) -> dict:
    return get_success_data(api.create_score(
        assignment_id,
        create_score_payload(overall=overall, **score_over),
        make_programmer_headers(programmer_id),
    ))


def st_slate(ctx: dict, section="SHORTS", capacity_slots=1) -> dict:
    return get_success_data(api.create_slate(
        create_slate_payload(
            ctx["edition"]["id"], section=section, capacity_slots=capacity_slots,
        ),
        CHAIR,
    ))


def st_deliberate(slate_id: str) -> dict:
    return get_success_data(api.deliberate_slate(slate_id, CHAIR))


def st_add_entry(slate_id: str, film_id: str, chair_headers=None) -> dict:
    """OCC-correct entry add: re-read the slate's current version first."""
    slate = get_success_data(api.get_slate(slate_id, CHAIR))
    return get_success_data(api.add_slate_entry(
        slate_id,
        {"submission_id": film_id, "expected_slate_version": slate["version"]},
        chair_headers or CHAIR,
    ))


def st_lock(slate_id: str, director_headers=None) -> dict:
    return get_success_data(
        api.lock_slate(slate_id, director_headers or DIRECTOR)
    )


def st_issue_invitations(ctx: dict) -> dict:
    return get_success_data(
        api.issue_invitations(ctx["edition"]["id"], DIRECTOR)
    )


def st_respond(entry_id: str, submitter_id: str, accept: bool) -> dict:
    return get_success_data(
        api.respond_to_entry(entry_id, accept, make_filmmaker_headers(submitter_id))
    )


def st_agreement_for(film_id: str) -> dict:
    """The single agreement auto-created for a confirmed film (PRD §3.7)."""
    data = get_success_data(
        api.list_exhibition_agreements(DIRECTOR, params={"submission_id": film_id})
    )
    assert len(data) == 1, f"Expected exactly one agreement for {film_id}"
    return data[0]


def st_issue_and_sign(agreement_id: str, submitter_id: str, overrides=None) -> dict:
    get_success_data(api.issue_agreement(
        agreement_id, issue_agreement_payload(**(overrides or {})), DIRECTOR,
    ))
    return get_success_data(
        api.sign_agreement(agreement_id, make_filmmaker_headers(submitter_id))
    )


def st_package_for(film_id: str) -> dict:
    """The single travel package auto-created for a confirmed film (§3.7)."""
    data = get_success_data(
        api.list_travel_packages(TRAVEL, params={"submission_id": film_id})
    )
    assert len(data) == 1, f"Expected exactly one travel package for {film_id}"
    return data[0]


def st_submit_package(package_id: str, submitter_id: str, overrides=None) -> dict:
    return get_success_data(api.submit_travel_package(
        package_id,
        submit_travel_payload(**(overrides or {})),
        make_filmmaker_headers(submitter_id),
    ))


def st_approve_package(package_id: str, edition_id: str) -> dict:
    """OCC-correct approval: re-read the edition's current version first."""
    edition = get_success_data(api.get_edition(edition_id, TRAVEL))
    return get_success_data(
        api.approve_travel_package(package_id, edition["version"], TRAVEL)
    )


def st_venue(ctx: dict, overrides=None) -> dict:
    venue = get_success_data(api.create_venue(
        create_venue_payload(ctx["edition"]["id"], **(overrides or {})), ADMIN,
    ))
    ctx.setdefault("venues", []).append(venue)
    return venue


def st_slot(venue_id: str, overrides=None) -> dict:
    """OCC-correct slot create: re-read the venue's current version first."""
    venue = get_success_data(api.get_venue(venue_id, OPS))
    return get_success_data(api.create_screening_slot(
        create_slot_payload(venue_id, venue["version"], **(overrides or {})), OPS,
    ))


def st_hold(slot_id: str, entry_id: str) -> dict:
    return get_success_data(api.hold_slot(slot_id, entry_id, OPS))


def st_confirm_slot(slot_id: str) -> dict:
    return get_success_data(api.confirm_slot(slot_id, OPS))


def st_juror(edition_id: str, overrides=None) -> dict:
    return get_success_data(api.create_juror(
        create_juror_payload(edition_id, **(overrides or {})), AWARDS,
    ))


def st_award(edition_id: str, juror_ids, overrides=None) -> dict:
    return get_success_data(api.create_award(
        create_award_payload(edition_id, juror_ids, **(overrides or {})), AWARDS,
    ))


def st_ballot(award_id: str, juror_id: str, ranked_ids) -> dict:
    return get_success_data(
        api.cast_ballot(award_id, ranked_ids, make_juror_headers(juror_id))
    )


# ---------------------------------------------------------------------------
# Tier 2: composite pipelines
# ---------------------------------------------------------------------------

def _normalize_films(films, default_category, default_scores):
    """films: int or list of per-film spec dicts."""
    if isinstance(films, int):
        films = [{"title": f"Film {i + 1}", "scores": list(default_scores)}
                 for i in range(films)]
    normalized = []
    for i, spec in enumerate(films):
        spec = dict(spec)
        spec.setdefault("title", f"Film {i + 1}")
        spec.setdefault("scores", list(default_scores))
        spec.setdefault("submission_over", {})
        spec.setdefault("submitter_over", None)
        spec["submission_over"].setdefault("category", default_category)
        normalized.append(spec)
    return normalized


DEFAULT_SCORE_SLOTS = (("STAFF", 8), ("STAFF", 9))


def fx_screening(*, films=1, scores=DEFAULT_SCORE_SLOTS, edition_over=None,
                 config_over=None, category="SHORT_FILM",
                 due_at=DEFAULT_ASSIGNMENT_DUE) -> dict:
    """Edition walked to SCREENING; each film paid, ELIGIBLE, IN_SCREENING and
    carrying its full set of SCORED assignments.

    films: int or list of {"title", "scores": [(seniority, overall), ...],
                           "submission_over", "submitter_over"}.
    A fresh programmer is created per score slot (no pair can repeat for a
    film; PRD §3.4 duplicate-open-pair rule).
    Returns ctx: {edition, config, films: [spec...], programmers, ...}
    """
    specs = _normalize_films(films, category, scores)
    ctx = st_edition(edition_over, with_config=True,
                     config_over=config_over, category=category)
    st_advance(ctx, "INTAKE_OPEN")

    for spec in specs:
        spec["submitter"] = st_submitter(spec["submitter_over"])
        over = dict(spec["submission_over"])
        over["title"] = spec["title"]
        spec["film"] = st_film(ctx, spec["submitter"], over, pay=True)
        st_rule(ctx, spec["film"]["id"], "ELIGIBLE")

    st_advance(ctx, "INTAKE_CLOSED")
    st_advance(ctx, "SCREENING")

    all_programmers: list = []
    for spec in specs:
        spec["assignments"] = []
        spec["scorers"] = []
        for seniority, overall in spec["scores"]:
            programmer = st_programmer(
                {"seniority": seniority, "categories_covered": [category]}
            )
            all_programmers.append(programmer)
            assignment = st_assign(
                spec["film"]["id"], programmer["id"], due_at,
            )
            st_score(assignment["id"], programmer["id"], overall)
            spec["assignments"].append(assignment)
            spec["scorers"].append(programmer)

    ctx["films"] = specs
    ctx["programmers"] = all_programmers
    return ctx


def fx_invited(*, films=1, scores=DEFAULT_SCORE_SLOTS, edition_over=None, config_over=None,
               category="SHORT_FILM", section="SHORTS", capacity_slots=1,
               entry_order=None, due_at=DEFAULT_ASSIGNMENT_DUE) -> dict:
    """fx_screening + DELIBERATION slate build + lock + SLATE_LOCKED +
    NOTIFICATION + issue-invitations.

    entry_order: indices of the films to place on the slate (default: the
    first `capacity_slots` films... all films listed in given order).
    Returns ctx with slate + entries {film_index: entry} + invitations data.
    """
    ctx = fx_screening(
        films=films, scores=scores, edition_over=edition_over,
        config_over=config_over, category=category, due_at=due_at,
    )
    st_advance(ctx, "DELIBERATION")
    slate = st_slate(ctx, section=section, capacity_slots=capacity_slots)
    st_deliberate(slate["id"])
    if entry_order is None:
        entry_order = list(range(len(ctx["films"])))
    entries = {}
    for idx in entry_order:
        entries[idx] = st_add_entry(slate["id"], ctx["films"][idx]["film"]["id"])
    st_lock(slate["id"])
    st_advance(ctx, "SLATE_LOCKED")
    st_advance(ctx, "NOTIFICATION")
    invitations = st_issue_invitations(ctx)
    ctx.update({"slate": slate, "entries": entries, "invitations": invitations})
    return ctx


def fx_responded(*, films=1, scores=DEFAULT_SCORE_SLOTS, edition_over=None,
                 config_over=None, category="SHORT_FILM", section="SHORTS",
                 capacity_slots=1, entry_order=None, accept=None,
                 sign_agreements=True, agreement_over=None,
                 due_at=DEFAULT_ASSIGNMENT_DUE) -> dict:
    """fx_invited + every invited entry answered (accept per film index, default
    accept=True) + agreements issued and signed for accepted films.

    The edition is left in NOTIFICATION (travel actions need no later phase).
    Returns ctx with agreements {film_index: agreement} and packages
    {film_index: package}.
    """
    ctx = fx_invited(
        films=films, scores=scores, edition_over=edition_over,
        config_over=config_over, category=category, section=section,
        capacity_slots=capacity_slots, entry_order=entry_order, due_at=due_at,
    )
    accept = accept or {}
    ctx["agreements"] = {}
    ctx["packages"] = {}
    for idx, entry in ctx["entries"].items():
        film = ctx["films"][idx]
        decision = accept.get(idx, True)
        # Only MAIN-lane entries became INVITED; WAITLIST-lane entries stay
        # NOMINATED and cannot be answered.
        if entry["status"] == "NOMINATED":
            fresh = get_success_data(api.get_slate_entry(entry["id"], DIRECTOR))
            if fresh["status"] != "INVITED":
                continue
        st_respond(entry["id"], film["submitter"]["id"], decision)
        if decision:
            agreement = st_agreement_for(film["film"]["id"])
            if sign_agreements:
                agreement = st_issue_and_sign(
                    agreement["id"], film["submitter"]["id"],
                    overrides=agreement_over,
                )
            ctx["agreements"][idx] = agreement
            ctx["packages"][idx] = st_package_for(film["film"]["id"])
    return ctx


def fx_scheduling(*, films=1, scores=DEFAULT_SCORE_SLOTS, edition_over=None,
                  config_over=None, category="SHORT_FILM", section="SHORTS",
                  capacity_slots=1, entry_order=None, agreement_over=None,
                  sign_agreements=True, due_at=DEFAULT_ASSIGNMENT_DUE) -> dict:
    """fx_responded (all invited entries accepted) + advance to SCHEDULING."""
    ctx = fx_responded(
        films=films, scores=scores, edition_over=edition_over,
        config_over=config_over, category=category, section=section,
        capacity_slots=capacity_slots, entry_order=entry_order,
        accept=None, sign_agreements=sign_agreements,
        agreement_over=agreement_over, due_at=due_at,
    )
    st_advance(ctx, "SCHEDULING")
    return ctx


def fx_programmed(*, films=1, scores=DEFAULT_SCORE_SLOTS, edition_over=None,
                  config_over=None, category="SHORT_FILM", section="SHORTS",
                  capacity_slots=1, venue_over=None,
                  slot_times=None, due_at=DEFAULT_ASSIGNMENT_DUE) -> dict:
    """fx_scheduling + one venue + one PREMIERE slot per confirmed entry, each
    held and confirmed (entry and submission reach PROGRAMMED).

    slot_times: list of (start_at, end_at) per programmed film.
    Returns ctx with venue + slots {film_index: slot}.
    """
    ctx = fx_scheduling(
        films=films, scores=scores, edition_over=edition_over,
        config_over=config_over, category=category, section=section,
        capacity_slots=capacity_slots, due_at=due_at,
    )
    venue = st_venue(ctx, venue_over)
    n = len(ctx["agreements"])
    default_times = [
        ("2027-01-22T17:00:00Z", "2027-01-22T18:00:00Z"),
        ("2027-01-22T19:00:00Z", "2027-01-22T20:00:00Z"),
        ("2027-01-22T21:00:00Z", "2027-01-22T22:00:00Z"),
    ]
    times = slot_times or default_times[:n]
    ctx["slots"] = {}
    # Hold must name the slate ENTRY id (PRD §3.8); ctx["agreements"] maps
    # film index -> agreement, so resolve the entry via ctx["entries"][idx].
    accepted_entries = [(idx, ctx["entries"][idx]) for idx in ctx["agreements"]]
    for (idx, entry), (start, end) in zip(accepted_entries, times):
        slot = st_slot(venue["id"], {"start_at": start, "end_at": end})
        st_hold(slot["id"], entry["id"])
        ctx["slots"][idx] = st_confirm_slot(slot["id"])
    ctx["venue"] = venue
    return ctx


def fx_festival_live(*, films=1, scores=DEFAULT_SCORE_SLOTS, edition_over=None,
                     config_over=None, category="SHORT_FILM", section="SHORTS",
                     capacity_slots=1, clock_to="2027-01-21T00:00:00Z",
                     due_at=DEFAULT_ASSIGNMENT_DUE) -> dict:
    """fx_programmed + logical clock at festival_start_at + FESTIVAL_LIVE."""
    ctx = fx_programmed(
        films=films, scores=scores, edition_over=edition_over,
        config_over=config_over, category=category, section=section,
        capacity_slots=capacity_slots, due_at=due_at,
    )
    set_clock(clock_to)
    st_advance(ctx, "FESTIVAL_LIVE")
    return ctx


def fx_voting_open(*, films=1, scores=DEFAULT_SCORE_SLOTS, num_jurors=1,
                   juror_overrides=None, award_over=None, edition_over=None,
                   config_over=None, category="SHORT_FILM", section="SHORTS",
                   capacity_slots=1, due_at=DEFAULT_ASSIGNMENT_DUE) -> dict:
    """fx_festival_live + empaneled jurors + award created + voting opened."""
    ctx = fx_festival_live(
        films=films, scores=scores, edition_over=edition_over,
        config_over=config_over, category=category, section=section,
        capacity_slots=capacity_slots, due_at=due_at,
    )
    juror_overrides = juror_overrides or [{}] * num_jurors
    jurors = [st_juror(ctx["edition"]["id"], over) for over in juror_overrides]
    award = st_award(
        ctx["edition"]["id"], [j["id"] for j in jurors], award_over or {},
    )
    get_success_data(api.open_voting(award["id"], AWARDS))
    ctx.update({"jurors": jurors, "award": award})
    return ctx

"""Composite setup helpers.

Most interesting claims in this PRD need the system driven a long way down the
induction pipeline before the operation under test can even be attempted:
eligibility rules, a voter bloc, credentialed electors, candidates, an open
cycle, nominations, screening decisions, a printed and certified ballot, cast
submissions, a closed and audited tally, a certified election, a planned
ceremony. ``build_election_world`` walks exactly that pipeline and stops at the
requested ``stage``; every other fixture in this module is a thin wrapper over
it.

Every helper returns plain dicts read back from the API, so tests assert on
PRD field names only.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .factories import (
    OMIT,
    create_artifact_intake_payload,
    create_ballot_payload,
    create_candidacy_payload,
    create_candidate_payload,
    create_ceremony_payload,
    create_eligibility_rule_payload,
    create_elector_payload,
    create_exhibit_case_payload,
    create_exhibit_installation_payload,
    create_induction_cycle_payload,
    create_travel_grant_payload,
    create_vote_submission_payload,
    create_voter_bloc_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CURATOR_HEADERS,
    make_elector_headers,
    make_screening_member_headers,
)

STAGES: List[str] = [
    "setup",
    "nominations_open",
    "nominated",
    "screened",
    "ballot_draft",
    "ballot_open",
    "voted",
    "voting_closed",
    "tallied",
    "audited",
    "certified",
    "ceremony",
]

DEFAULT_ELECTOR_NAMES = [
    "Elector One",
    "Screener Two",
    "Elector Three",
    "Elector Four",
    "Elector Five",
    "Elector Six",
    "Elector Seven",
    "Elector Eight",
]

DEFAULT_CANDIDATE_SPECS: List[Dict[str, Any]] = [
    {
        "full_name": "Player One",
        "retirement_year": 2018,
        "career_seasons": 15,
        "career_metric_value": 3000,
    },
    {
        "full_name": "Player Two",
        "retirement_year": 2017,
        "career_seasons": 14,
        "career_metric_value": 2800,
    },
    {
        "full_name": "Player Three",
        "retirement_year": 2016,
        "career_seasons": 13,
        "career_metric_value": 2600,
    },
    {
        "full_name": "Player Four",
        "retirement_year": 2015,
        "career_seasons": 12,
        "career_metric_value": 2400,
    },
    {
        "full_name": "Player Five",
        "retirement_year": 2014,
        "career_seasons": 11,
        "career_metric_value": 2200,
    },
    {
        "full_name": "Player Six",
        "retirement_year": 2013,
        "career_seasons": 11,
        "career_metric_value": 2100,
    },
]


def _stage_index(stage: str) -> int:
    assert stage in STAGES, f"unknown stage {stage!r}; expected one of {STAGES}"
    return STAGES.index(stage)


# --------------------------------------------------------------------------
# Tiny single-call helpers
# --------------------------------------------------------------------------
def set_clock(api: ApiClient, instant: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock. Every role may call this endpoint."""
    return get_success_data(
        api.set_clock({"current_utc": instant}, headers or ADMIN_HEADERS)
    )


def setup_eligibility_rule(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_eligibility_rule(create_eligibility_rule_payload(**overrides), ADMIN_HEADERS)
    )


def setup_voter_bloc(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_voter_bloc(create_voter_bloc_payload(**overrides), ADMIN_HEADERS)
    )


def setup_candidate(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_candidate(create_candidate_payload(**overrides), ADMIN_HEADERS)
    )


def setup_cycle(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_induction_cycle(create_induction_cycle_payload(**overrides), ADMIN_HEADERS)
    )


def setup_elector(api: ApiClient, bloc_id: str, credential: bool = True, **overrides) -> dict:
    elector = get_success_data(
        api.create_elector(create_elector_payload(bloc_id, **overrides), ADMIN_HEADERS)
    )
    if credential:
        elector = get_success_data(api.credential_elector(elector["id"], ADMIN_HEADERS))
    return elector


def setup_exhibit_case(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_exhibit_case(create_exhibit_case_payload(**overrides), CURATOR_HEADERS)
    )


def setup_artifact_intake(api: ApiClient, induction_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_artifact_intake(
            induction_id, create_artifact_intake_payload(**overrides), CURATOR_HEADERS
        )
    )


def setup_exhibit_installation(
    api: ApiClient, induction_id: str, exhibit_case_id: str, **overrides
) -> dict:
    return get_success_data(
        api.create_exhibit_installation(
            create_exhibit_installation_payload(induction_id, exhibit_case_id, **overrides),
            CURATOR_HEADERS,
        )
    )


# --------------------------------------------------------------------------
# Read-back helpers
# --------------------------------------------------------------------------
def read_cycle(api: ApiClient, cycle_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_induction_cycle(cycle_id, headers or ADMIN_HEADERS))


def read_candidate(api: ApiClient, candidate_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_candidate(candidate_id, headers or ADMIN_HEADERS))


def read_candidacy(api: ApiClient, candidacy_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_candidacy(candidacy_id, headers or ADMIN_HEADERS))


def read_elector(api: ApiClient, elector_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_elector(elector_id, headers or ADMIN_HEADERS))


def read_bloc(api: ApiClient, bloc_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_voter_bloc(bloc_id, headers or ADMIN_HEADERS))


def read_ballot(api: ApiClient, ballot_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_ballot(ballot_id, headers or ADMIN_HEADERS))


def read_slot(api: ApiClient, slot_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_ballot_slot(slot_id, headers or ADMIN_HEADERS))


def read_submission(api: ApiClient, submission_id: str, headers: Optional[dict] = None) -> dict:
    """Reads a submission as the auditor by default, so selections are visible."""
    return get_success_data(api.get_vote_submission(submission_id, headers or AUDITOR_HEADERS))


def read_induction(api: ApiClient, induction_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_induction(induction_id, headers or ADMIN_HEADERS))


def read_grant(api: ApiClient, grant_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_travel_grant(grant_id, headers or ADMIN_HEADERS))


def read_case(api: ApiClient, case_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_exhibit_case(case_id, headers or CURATOR_HEADERS))


def read_installation(api: ApiClient, installation_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.get_exhibit_installation(installation_id, headers or CURATOR_HEADERS)
    )


# --------------------------------------------------------------------------
# The pipeline builder
# --------------------------------------------------------------------------
def build_election_world(
    api: ApiClient,
    *,
    stage: str = "screened",
    rules: Optional[Sequence[Dict[str, Any]]] = None,
    elector_count: int = 3,
    elector_specs: Optional[Sequence[Dict[str, Any]]] = None,
    credential: bool = True,
    screening_index: int = 1,
    candidate_specs: Optional[Sequence[Dict[str, Any]]] = None,
    candidate_count: Optional[int] = None,
    nominations: Optional[Sequence[Dict[str, Any]]] = None,
    advance: Optional[Sequence[int]] = None,
    nominator_index: int = 0,
    cycle_overrides: Optional[Dict[str, Any]] = None,
    ballot_overrides: Optional[Dict[str, Any]] = None,
    votes: Optional[Sequence[Any]] = None,
    audit_decision: str = "CERTIFY",
    audit_note: str = "Clean count",
    ceremony_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Drive the induction pipeline to ``stage`` and return every created row.

    The returned dict carries: ``rules``, ``bloc``, ``electors``, ``candidates``,
    ``cycle``, ``cycle_version``, ``candidacies``, ``ballot``, ``ballot_version``,
    ``slots`` (keyed by candidacy id), ``slot_list``, ``submissions`` and
    ``inductions`` (keyed by candidacy id).
    """
    target = _stage_index(stage)
    world: Dict[str, Any] = {
        "api": api,
        "rules": [],
        "electors": [],
        "candidates": [],
        "candidacies": [],
        "submissions": [],
        "slots": {},
        "slot_list": [],
        "inductions": {},
        "ballot": None,
        "ballot_version": None,
        "cycle_version": None,
    }

    # --- eligibility rules -------------------------------------------------
    for rule_overrides in rules if rules is not None else [{}]:
        world["rules"].append(setup_eligibility_rule(api, **rule_overrides))

    # --- voter bloc and electors ------------------------------------------
    world["bloc"] = setup_voter_bloc(api)
    if elector_specs is None:
        elector_specs = [
            {
                "full_name": DEFAULT_ELECTOR_NAMES[i % len(DEFAULT_ELECTOR_NAMES)],
                "is_screening_member": (i == screening_index),
            }
            for i in range(elector_count)
        ]
    for spec in elector_specs:
        world["electors"].append(
            setup_elector(api, world["bloc"]["id"], credential=credential, **spec)
        )

    # --- candidates --------------------------------------------------------
    if candidate_specs is None:
        wanted = candidate_count
        if wanted is None:
            wanted = len(nominations) if nominations is not None else 2
        candidate_specs = DEFAULT_CANDIDATE_SPECS[:wanted]
    for spec in candidate_specs:
        world["candidates"].append(setup_candidate(api, **spec))

    # --- cycle -------------------------------------------------------------
    world["cycle"] = setup_cycle(api, **(cycle_overrides or {}))
    cycle_id = world["cycle"]["id"]
    world["cycle_version"] = world["cycle"]["version"]
    if target == _stage_index("setup"):
        return world

    # --- nominations open --------------------------------------------------
    world["cycle"] = get_success_data(api.open_nominations(cycle_id, ADMIN_HEADERS))
    world["cycle_version"] = world["cycle"]["version"]
    if target == _stage_index("nominations_open"):
        return world

    # --- nominations -------------------------------------------------------
    if nominations is None:
        nominations = [
            {"candidate_index": i, "pathway": "MODERN"}
            for i in range(len(world["candidates"]))
        ]
    for spec in nominations:
        spec = dict(spec)
        candidate_index = spec.pop("candidate_index")
        nominator = spec.pop("nominator_index", nominator_index)
        payload = create_candidacy_payload(
            cycle_id,
            world["candidates"][candidate_index]["id"],
            world["electors"][nominator]["id"],
            **spec,
        )
        world["candidacies"].append(
            get_success_data(api.create_candidacy(payload, ADMIN_HEADERS))
        )
    if target == _stage_index("nominated"):
        world["cycle"] = read_cycle(api, cycle_id)
        world["cycle_version"] = world["cycle"]["version"]
        return world

    # --- screening ---------------------------------------------------------
    get_success_data(api.close_nominations(cycle_id, ADMIN_HEADERS))
    screener_headers = make_screening_member_headers(world["electors"][screening_index]["id"])
    to_advance = range(len(world["candidacies"])) if advance is None else advance
    for index in to_advance:
        get_success_data(
            api.create_screening_decision(
                world["candidacies"][index]["id"], {"decision": "ADVANCE"}, screener_headers
            )
        )
    world["cycle"] = read_cycle(api, cycle_id)
    world["cycle_version"] = world["cycle"]["version"]
    if target == _stage_index("screened"):
        return world

    # --- ballot construction ----------------------------------------------
    ballot_payload = create_ballot_payload(
        cycle_id, world["cycle_version"], **(ballot_overrides or {})
    )
    world["ballot"] = get_success_data(api.create_ballot(ballot_payload, ADMIN_HEADERS))
    world["ballot_version"] = world["ballot"]["version"]
    slots, _ = _paginated(api.list_ballot_slots(ADMIN_HEADERS, {"ballot_id": world["ballot"]["id"], "limit": 100}))
    world["slot_list"] = slots
    world["slots"] = {slot["candidacy_id"]: slot for slot in slots}
    world["cycle"] = read_cycle(api, cycle_id)
    world["cycle_version"] = world["cycle"]["version"]
    if target == _stage_index("ballot_draft"):
        return world

    # --- certify the slate, opening the ballot ----------------------------
    world["ballot"] = get_success_data(api.certify_ballot(world["ballot"]["id"], ADMIN_HEADERS))
    world["ballot_version"] = world["ballot"]["version"]
    if target == _stage_index("ballot_open"):
        return world

    # --- cast votes --------------------------------------------------------
    if votes is None:
        votes = [(i, [0]) for i in range(len(world["electors"]))]
    for vote in votes:
        cast_vote(world, vote)
    if target == _stage_index("voted"):
        world["ballot"] = read_ballot(api, world["ballot"]["id"])
        world["ballot_version"] = world["ballot"]["version"]
        return world

    # --- close voting ------------------------------------------------------
    world["ballot"] = get_success_data(api.close_ballot(world["ballot"]["id"], ADMIN_HEADERS))
    world["ballot_version"] = world["ballot"]["version"]
    if target == _stage_index("voting_closed"):
        return world

    # --- draft tally -------------------------------------------------------
    world["ballot"] = get_success_data(api.tally_ballot(world["ballot"]["id"], ADMIN_HEADERS))
    world["ballot_version"] = world["ballot"]["version"]
    if target == _stage_index("tallied"):
        return world

    # --- audit decision ----------------------------------------------------
    world["ballot"] = get_success_data(
        api.create_audit_decision(
            world["ballot"]["id"],
            {"decision": audit_decision, "audit_note": audit_note},
            AUDITOR_HEADERS,
        )
    )
    world["ballot_version"] = world["ballot"]["version"]
    world["cycle"] = read_cycle(api, cycle_id)
    world["cycle_version"] = world["cycle"]["version"]
    if target == _stage_index("audited"):
        return world

    # --- certify the election ---------------------------------------------
    world["cycle"] = get_success_data(api.certify_election(cycle_id, ADMIN_HEADERS))
    world["cycle_version"] = world["cycle"]["version"]
    inductions, _ = _paginated(
        api.list_inductions(ADMIN_HEADERS, {"cycle_id": cycle_id, "limit": 100})
    )
    world["inductions"] = {row["candidacy_id"]: row for row in inductions}
    if target == _stage_index("certified"):
        return world

    # --- plan the ceremony -------------------------------------------------
    world["cycle"] = get_success_data(
        api.patch_ceremony(
            cycle_id, create_ceremony_payload(**(ceremony_overrides or {})), ADMIN_HEADERS
        )
    )
    world["cycle_version"] = world["cycle"]["version"]
    return world


def _paginated(response) -> Tuple[List[dict], dict]:
    body = get_success_data(response)
    if isinstance(body, list):
        return body, {}
    return body, {}


def cast_vote(world: Dict[str, Any], vote: Any) -> dict:
    """Cast one submission, threading the ballot OCC token automatically.

    ``vote`` is either ``(elector_index, [candidacy_index, ...])`` or a dict with
    ``elector`` plus either ``candidacies`` or ``is_abstention``.
    """
    api: ApiClient = world["api"]
    if isinstance(vote, tuple):
        elector_index, candidacy_indexes = vote
        payload_extra: Dict[str, Any] = {}
    else:
        vote = dict(vote)
        elector_index = vote.pop("elector")
        candidacy_indexes = vote.pop("candidacies", [])
        payload_extra = vote
    slot_ids = [slot_of(world, index)["id"] for index in candidacy_indexes]
    elector = world["electors"][elector_index]
    headers = (
        make_screening_member_headers(elector["id"])
        if elector.get("is_screening_member")
        else make_elector_headers(elector["id"])
    )
    payload = create_vote_submission_payload(
        world["ballot"]["id"], slot_ids, world["ballot_version"], **payload_extra
    )
    submission = get_success_data(api.create_vote_submission(payload, headers))
    world["ballot_version"] = submission["ballot_version_after"]
    world["submissions"].append(submission)
    return submission


# --------------------------------------------------------------------------
# Accessors
# --------------------------------------------------------------------------
def elector_headers(world: Dict[str, Any], index: int) -> dict:
    return make_elector_headers(world["electors"][index]["id"])


def screening_headers(world: Dict[str, Any], index: int = 1) -> dict:
    return make_screening_member_headers(world["electors"][index]["id"])


def candidacy_of(world: Dict[str, Any], index: int) -> dict:
    return world["candidacies"][index]


def slot_of(world: Dict[str, Any], candidacy_index: int) -> dict:
    """The printed slot for a candidacy, addressed by nomination order."""
    candidacy_id = world["candidacies"][candidacy_index]["id"]
    assert candidacy_id in world["slots"], (
        f"candidacy {candidacy_index} has no printed slot on this ballot"
    )
    return world["slots"][candidacy_id]


def induction_of(world: Dict[str, Any], candidacy_index: int) -> dict:
    candidacy_id = world["candidacies"][candidacy_index]["id"]
    assert candidacy_id in world["inductions"], (
        f"candidacy {candidacy_index} produced no induction"
    )
    return world["inductions"][candidacy_id]


def refresh_cycle(world: Dict[str, Any]) -> dict:
    world["cycle"] = read_cycle(world["api"], world["cycle"]["id"])
    world["cycle_version"] = world["cycle"]["version"]
    return world["cycle"]


def refresh_ballot(world: Dict[str, Any]) -> dict:
    world["ballot"] = read_ballot(world["api"], world["ballot"]["id"])
    world["ballot_version"] = world["ballot"]["version"]
    return world["ballot"]


# --------------------------------------------------------------------------
# Ceremony-logistics helpers
# --------------------------------------------------------------------------
def request_travel_grant(world: Dict[str, Any], induction_id: str, **overrides) -> dict:
    """Request a grant, threading the cycle OCC token from the world."""
    api: ApiClient = world["api"]
    payload = create_travel_grant_payload(
        induction_id, world["cycle_version"], **overrides
    )
    grant = get_success_data(api.create_travel_grant(payload, ADMIN_HEADERS))
    world["cycle_version"] = grant["cycle_version_after"]
    return grant


def approve_travel_grant(world: Dict[str, Any], grant_id: str) -> dict:
    api: ApiClient = world["api"]
    grant = get_success_data(api.approve_travel_grant(grant_id, ADMIN_HEADERS))
    refresh_cycle(world)
    return grant


def setup_ceremony_ready_world(
    api: ApiClient,
    *,
    exempt_artifacts: bool = True,
    nights: int = 1,
    **kwargs,
) -> Dict[str, Any]:
    """A CEREMONY_PLANNED cycle whose single induction is ceremony-ready.

    Travel is approved and artifacts are either exempt or received and installed,
    which is what the PRD's readiness rule requires.
    """
    world = build_election_world(api, stage="ceremony", **kwargs)
    for candidacy_id, induction in list(world["inductions"].items()):
        if exempt_artifacts:
            setup_artifact_intake(api, induction["id"], artifact_count=OMIT, is_exempt=True)
        else:
            setup_artifact_intake(api, induction["id"], artifact_count=2)
        grant = request_travel_grant(
            world, induction["id"], nights=nights, requested_airfare_cents=0
        )
        approve_travel_grant(world, grant["id"])
        world["inductions"][candidacy_id] = read_induction(api, induction["id"])
    refresh_cycle(world)
    return world


# --------------------------------------------------------------------------
# Named wrappers used by many tests
# --------------------------------------------------------------------------
def setup_screened_slate(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A cycle in SCREENING whose nominated candidacies are all ADVANCED."""
    return build_election_world(api, stage="screened", **kwargs)


def setup_draft_ballot(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A printed but uncertified ballot (voting_status DRAFT)."""
    return build_election_world(api, stage="ballot_draft", **kwargs)


def setup_open_ballot(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A certified ballot open for voting."""
    return build_election_world(api, stage="ballot_open", **kwargs)


def setup_voted_ballot(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """An open ballot with submissions already cast."""
    return build_election_world(api, stage="voted", **kwargs)


def setup_closed_ballot(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A ballot whose voting window has been closed."""
    return build_election_world(api, stage="voting_closed", **kwargs)


def setup_tallied_ballot(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A closed ballot carrying a draft tally awaiting audit."""
    return build_election_world(api, stage="tallied", **kwargs)


def setup_audited_ballot(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A closed ballot whose tally has been audited."""
    return build_election_world(api, stage="audited", **kwargs)


def setup_certified_election(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A CERTIFIED cycle whose inductions exist."""
    return build_election_world(api, stage="certified", **kwargs)


def setup_ceremony_planned(api: ApiClient, **kwargs) -> Dict[str, Any]:
    """A CEREMONY_PLANNED cycle ready for travel and exhibit work."""
    return build_election_world(api, stage="ceremony", **kwargs)

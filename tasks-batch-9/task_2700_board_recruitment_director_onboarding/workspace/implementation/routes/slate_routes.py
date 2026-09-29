"""Nomination slates, nominees, committee ballots, decisions and the election."""

from flask import Blueprint

from authz import (
    COMMITTEE_CHAIR,
    COMMITTEE_MEMBER,
    CORPORATE_SECRETARY,
    GOVERNANCE_STAFF,
    SEATED_DIRECTOR,
    require,
    require_director_owner,
)
from calc import (
    candidate_board_set,
    dec,
    director_board_set,
    governing_policy,
    interlock_evaluation,
    overboarding_limit,
    parse_iso_date,
    require_policy,
    whole_years,
)
from derive import (
    _apply,
    counted_nominees,
    end_active_assignments,
    nominee_fee_preview,
    recompute_slate,
    recompute_slate_tally,
    return_slate_to_draft,
    seed_onboarding_items,
    settle_nominee_change,
    slate_nominees,
    slate_votes,
    sourcing_firm,
    void_cast_ballots,
    void_nominee_row,
)
from errors import fail
from payload import body, check_enum, check_min, optional, required
from store import clock_date, clock_instant, db, new_row, touch, wall_now
from vocab import BALLOT, SLATE_DECISION

from routes.common import apply_filters, by_created_at, by_field, emit, emit_list, need

bp = Blueprint("slate", __name__)

READ_ALL = (GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER,
            SEATED_DIRECTOR)
VOTE_READ = (GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER)
STAFF = (GOVERNANCE_STAFF, CORPORATE_SECRETARY)

OPEN_SLATE = ("DRAFT", "COMMITTEE_REVIEW")
LIVE_NOMINEE = ("PROPOSED", "CONFIRMED")
RENOMINABLE = ("SEATED", "RETIREMENT_NOTICED")
DEFAULT_FEE_BUDGET = 10000000000


@bp.post("/slates")
def open_slate():
    require(CORPORATE_SECRETARY)
    b = body()
    cycle_year = required(b, "cycle_year", "integer")
    seat_count = required(b, "seat_count", "integer")
    budget = optional(b, "search_fee_budget_cents", "integer", DEFAULT_FEE_BUDGET)
    check_min("cycle_year", cycle_year, 2000)
    check_min("seat_count", seat_count, 1)
    check_min("search_fee_budget_cents", budget, 0)
    for row in db.slates.values():
        if row["status"] != "ABANDONED" and row["cycle_year"] == cycle_year:
            fail("ERR_DUPLICATE_RESOURCE",
                 "A live slate already holds cycle year %s." % cycle_year)
    policy = governing_policy()
    if policy is not None and cycle_year < policy["cycle_year"]:
        fail("ERR_CYCLE_YEAR_NOT_ADVANCED",
             "cycle_year %s precedes the governing policy cycle year %s."
             % (cycle_year, policy["cycle_year"]))
    row = new_row({
        "cycle_year": cycle_year,
        "seat_count": seat_count,
        "search_fee_budget_cents": budget,
        "nominee_count": 0,
        "independent_nominee_count": 0,
        "independent_nominee_pct": 0.00,
        "independence_shortfall": False,
        "committed_search_fee_cents": 0,
        "contested": False,
        "universal_proxy_applicable": False,
        "revision_count": 0,
        "votes_for": 0,
        "votes_against": 0,
        "votes_abstain": 0,
        "votes_recused": 0,
        "approval_pct": 0.00,
        "quorum_met": False,
        "status": "DRAFT",
        "filed_at": None,
        "election_recorded_at": None,
    })
    db.slates[row["id"]] = row
    return emit(row, 201)


@bp.get("/slates/<slate_id>")
def read_slate(slate_id):
    require(*READ_ALL)
    return emit(need("slate", slate_id))


@bp.get("/slates")
def list_slates():
    require(*READ_ALL)
    rows = apply_filters(list(db.slates.values()), {
        "status": ("status", "str"),
        "cycle_year": ("cycle_year", "int"),
    })
    return emit_list(by_field(rows, "cycle_year", reverse=True))


# ------------------------------------------------------------------- nominees
def _nominee_safety(policy, candidate, director):
    """Step 17 for a nominee add: tenure, retirement age, interlock, overboarding."""
    today = clock_date()
    if director is not None:
        tenure = whole_years(parse_iso_date(director["appointed_on"]), today)
        if tenure >= policy["max_tenure_years"]:
            fail("ERR_TENURE_LIMIT_EXCEEDED",
                 "The director has served %s whole years against a cap of %s."
                 % (tenure, policy["max_tenure_years"]))
        born = parse_iso_date(director["birth_date"])
        board_set = director_board_set(director["id"])
        shared, competitor = interlock_evaluation(board_set, director["id"])
        sitting_ceo = director["is_sitting_ceo_elsewhere"]
    else:
        born = parse_iso_date(candidate["birth_date"])
        board_set = candidate_board_set(candidate["id"])
        shared, competitor = interlock_evaluation(board_set)
        sitting_ceo = candidate["is_sitting_ceo"]

    age = whole_years(born, today)
    if age >= policy["mandatory_retirement_age"]:
        fail("ERR_RETIREMENT_AGE_EXCEEDED",
             "The nominee is %s years old against a retirement age of %s."
             % (age, policy["mandatory_retirement_age"]))
    if shared >= policy["interlock_max_shared_boards"] or competitor:
        fail("ERR_INTERLOCK_LIMIT_EXCEEDED",
             "The nominee shares %s outside board(s) with a sitting director." % shared)
    limit = overboarding_limit(policy, sitting_ceo)
    if len(board_set) + 1 > limit:
        fail("ERR_OVERBOARDING_LIMIT_EXCEEDED",
             "The nominee already holds %s outside public boards against a limit of %s."
             % (len(board_set), limit))
    return shared, len(board_set)


@bp.post("/slates/<slate_id>/nominees")
def add_nominee(slate_id):
    require(*STAFF)
    b = body()
    ballot_order = required(b, "ballot_order", "integer")
    expected_version = required(b, "expected_slate_version", "integer")
    candidate_id = optional(b, "candidate_id", "string")
    director_id = optional(b, "incumbent_director_id", "string")
    check_min("ballot_order", ballot_order, 1)
    if (candidate_id is None) == (director_id is None):
        fail("ERR_SOURCE_CHANNEL_MISMATCH",
             "Exactly one of candidate_id or incumbent_director_id must be supplied.")
    slate = need("slate", slate_id)
    candidate = need("candidate", candidate_id) if candidate_id is not None else None
    director = need("director", director_id) if director_id is not None else None
    policy = require_policy()
    if expected_version != slate["version"]:
        fail("ERR_STALE_SLATE_VERSION",
             "expected_slate_version %s does not match the slate version %s."
             % (expected_version, slate["version"]))
    if slate["status"] not in OPEN_SLATE:
        fail("ERR_SLATE_STATE_INVALID",
             "A nominee may only be added while the slate is DRAFT or COMMITTEE_REVIEW; "
             "this slate is %s." % slate["status"])
    if candidate is not None and candidate["status"] != "SLATE_ELIGIBLE":
        fail("ERR_CANDIDATE_STATE_INVALID",
             "Only a SLATE_ELIGIBLE candidate may be nominated; this one is %s."
             % candidate["status"])
    if director is not None and director["service_status"] not in RENOMINABLE:
        fail("ERR_DIRECTOR_NOT_SEATABLE",
             "A director whose service_status is %s may not be renominated."
             % director["service_status"])

    shared, board_count = _nominee_safety(policy, candidate, director)

    live = [n for n in slate_nominees(slate_id) if n["status"] != "VOIDED"]
    for row in live:
        if candidate_id is not None and row.get("candidate_id") == candidate_id:
            fail("ERR_DUPLICATE_RESOURCE", "That candidate already sits on this slate.")
        if director_id is not None and row.get("incumbent_director_id") == director_id:
            fail("ERR_DUPLICATE_RESOURCE", "That director already sits on this slate.")
    for row in live:
        if row["ballot_order"] == ballot_order:
            fail("ERR_DUPLICATE_RESOURCE",
                 "Ballot order %s is already taken on this slate." % ballot_order)

    if candidate is not None:
        if dec(candidate["readiness_score"]) < dec(policy["readiness_min_score"]):
            fail("ERR_READINESS_BELOW_THRESHOLD",
                 "Readiness %s is below the floor of %s."
                 % (candidate["readiness_score"], policy["readiness_min_score"]))
    if len(live) + 1 > policy["authorized_seats"]:
        fail("ERR_SEAT_COUNT_EXCEEDED",
             "The slate already carries %s of %s authorized seats."
             % (len(live), policy["authorized_seats"]))

    firm = None
    ordinal, tier, fee = 0, None, 0
    if candidate is not None and candidate.get("search_firm_id") is not None:
        firm = db.search_firms.get(candidate["search_firm_id"])
    if firm is not None:
        ordinal, tier, fee = nominee_fee_preview(firm, candidate, wall_now(), ballot_order)
    committed = sum(n["placement_fee_cents"] for n in counted_nominees(slate_id))
    if committed + fee > slate["search_fee_budget_cents"]:
        fail("ERR_SEARCH_FEE_BUDGET_EXCEEDED",
             "Committing %s cents would exceed the slate budget of %s cents."
             % (committed + fee, slate["search_fee_budget_cents"]))

    if director is not None:
        is_independent = bool(director["is_independent"])
    else:
        is_independent = candidate["independence_result"] == "INDEPENDENT"
    row = new_row({
        "slate_id": slate_id,
        "candidate_id": candidate_id,
        "incumbent_director_id": director_id,
        "ballot_order": ballot_order,
        "is_independent": is_independent,
        "placement_fee_cents": fee,
        "fee_tier_applied": tier,
        "nominee_ordinal": ordinal,
        "status": "PROPOSED",
        "voided_at": None,
    })
    db.nominees[row["id"]] = row
    if candidate is not None:
        _apply(candidate, {
            "status": "NOMINATED",
            "interlock_shared_board_count": shared,
            "external_public_board_count": board_count,
        })
    if firm is not None:
        settle_nominee_change({slate_id}, [firm], policy, revise_reviews=False)
    else:
        recompute_slate(slate, policy)
    touch(slate)
    return emit(row, 201)


@bp.get("/slate-nominees/<nominee_id>")
def read_nominee(nominee_id):
    require(*READ_ALL)
    return emit(need("nominee", nominee_id))


@bp.get("/slate-nominees")
def list_nominees():
    require(*READ_ALL)
    rows = apply_filters(list(db.nominees.values()), {
        "slate_id": ("slate_id", "str"),
        "candidate_id": ("candidate_id", "str"),
        "incumbent_director_id": ("incumbent_director_id", "str"),
        "status": ("status", "str"),
    })
    return emit_list(by_field(rows, "ballot_order"))


@bp.post("/slate-nominees/<nominee_id>/void")
def void_nominee(nominee_id):
    require(*STAFF)
    nominee = need("nominee", nominee_id)
    slate = db.slates.get(nominee["slate_id"])
    if nominee["status"] not in LIVE_NOMINEE:
        fail("ERR_NOMINEE_STATE_INVALID",
             "Only a PROPOSED or CONFIRMED nominee may be voided; this one is %s."
             % nominee["status"])
    if slate is None or slate["status"] not in OPEN_SLATE:
        fail("ERR_NOMINEE_STATE_INVALID",
             "A nominee may only be voided while its slate is DRAFT or COMMITTEE_REVIEW.")
    policy = governing_policy()
    firm = void_nominee_row(nominee, defer_candidate=True)
    settle_nominee_change({slate["id"]}, [firm] if firm is not None else [], policy)
    touch(slate)
    return emit(nominee)


# ------------------------------------------------------- review and balloting
@bp.post("/slates/<slate_id>/submit-for-review")
def submit_for_review(slate_id):
    require(*STAFF)
    slate = need("slate", slate_id)
    policy = require_policy()
    if slate["status"] != "DRAFT":
        fail("ERR_SLATE_STATE_INVALID",
             "Only a DRAFT slate may be submitted for review; this one is %s."
             % slate["status"])
    recompute_slate(slate, policy)
    if slate["nominee_count"] < 1 \
            or dec(slate["independent_nominee_pct"]) < dec(policy["independence_min_pct"]):
        fail("ERR_INDEPENDENCE_SHORTFALL",
             "The slate carries %s nominee(s) at %s%% independence against a floor of %s%%."
             % (slate["nominee_count"], slate["independent_nominee_pct"],
                policy["independence_min_pct"]))
    if slate["universal_proxy_applicable"] \
            and slate["nominee_count"] < policy["authorized_seats"] - 1:
        fail("ERR_UNIVERSAL_PROXY_MINIMUM",
             "A contested slate must carry at least %s nominees."
             % (policy["authorized_seats"] - 1))
    if slate["committed_search_fee_cents"] > slate["search_fee_budget_cents"]:
        fail("ERR_SEARCH_FEE_BUDGET_EXCEEDED",
             "Committed fees of %s cents exceed the budget of %s cents."
             % (slate["committed_search_fee_cents"], slate["search_fee_budget_cents"]))
    slate["status"] = "COMMITTEE_REVIEW"
    touch(slate)
    return emit(slate)


def _referred_or_nominated(slate_id, director_id):
    """recusal_required: the voter referred a counted nominee, or is one themselves."""
    for nominee in counted_nominees(slate_id):
        if nominee.get("incumbent_director_id") == director_id:
            return True
        candidate = db.candidates.get(nominee.get("candidate_id"))
        if candidate is not None and candidate.get("referring_director_id") == director_id:
            return True
    return False


def _interviewed_on_slate(slate_id, director_id):
    subjects = set()
    for nominee in counted_nominees(slate_id):
        if nominee.get("candidate_id") is not None:
            subjects.add(nominee["candidate_id"])
    if not subjects:
        return False
    for session in db.interviews.values():
        if session["interviewer_director_id"] != director_id:
            continue
        if session["candidate_id"] in subjects \
                and session["status"] in ("SCHEDULED", "COMPLETED"):
            return True
    return False


@bp.post("/slates/<slate_id>/votes")
def cast_ballot(slate_id):
    actor = require(COMMITTEE_CHAIR, COMMITTEE_MEMBER)
    b = body()
    claimed = optional(b, "voting_director_id", "string")
    if claimed is not None:
        require_director_owner(actor, claimed)
    director_id = required(b, "voting_director_id", "string")
    ballot = required(b, "ballot", "string")
    rationale = optional(b, "rationale", "string", "")
    check_enum("ballot", ballot, BALLOT)
    slate = need("slate", slate_id)
    need("director", director_id)
    if slate["status"] != "COMMITTEE_REVIEW":
        fail("ERR_SLATE_STATE_INVALID",
             "Ballots may only be cast on a slate in COMMITTEE_REVIEW; this one is %s."
             % slate["status"])
    recusal_required = _referred_or_nominated(slate_id, director_id)
    if recusal_required and ballot != "RECUSED":
        fail("ERR_SEGREGATION_OF_DUTIES",
             "This director must ballot RECUSED on this slate.")
    if _interviewed_on_slate(slate_id, director_id):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "A director who interviewed a candidate on this slate may not ballot on it.")
    for vote in slate_votes(slate_id):
        if vote["status"] == "CAST" and vote["voting_director_id"] == director_id:
            fail("ERR_DUPLICATE_RESOURCE", "This director has already balloted on the slate.")
    row = new_row({
        "slate_id": slate_id,
        "voting_director_id": director_id,
        "ballot": ballot,
        "rationale": rationale,
        "recusal_required": recusal_required,
        "status": "CAST",
        "cast_at": clock_instant(),
    })
    db.votes[row["id"]] = row
    recompute_slate_tally(slate)
    return emit(row, 201)


@bp.get("/votes/<vote_id>")
def read_vote(vote_id):
    require(*VOTE_READ)
    return emit(need("vote", vote_id))


@bp.get("/votes")
def list_votes():
    require(*VOTE_READ)
    rows = apply_filters(list(db.votes.values()), {
        "slate_id": ("slate_id", "str"),
        "voting_director_id": ("voting_director_id", "str"),
        "status": ("status", "str"),
    })
    return emit_list(by_created_at(rows))


# ------------------------------------------- decision, filing and the election
@bp.post("/slates/<slate_id>/decide")
def decide_slate(slate_id):
    require(COMMITTEE_CHAIR)
    b = body()
    decision = required(b, "decision", "string")
    optional(b, "rationale", "string", "")
    check_enum("decision", decision, SLATE_DECISION)
    slate = need("slate", slate_id)
    policy = require_policy()
    allowed = OPEN_SLATE if decision == "ABANDON" else ("COMMITTEE_REVIEW",)
    if slate["status"] not in allowed:
        fail("ERR_SLATE_STATE_INVALID",
             "A slate in %s may not receive the decision %s." % (slate["status"], decision))
    recompute_slate(slate, policy)
    recompute_slate_tally(slate, policy)

    if decision == "APPROVE":
        if not slate["quorum_met"]:
            fail("ERR_QUORUM_NOT_MET",
                 "The ballot count has not reached the quorum of %s." % policy["quorum_size"])
        if dec(slate["approval_pct"]) < dec(policy["approval_threshold_pct"]):
            fail("ERR_APPROVAL_THRESHOLD_NOT_MET",
                 "Approval of %s%% is below the threshold of %s%%."
                 % (slate["approval_pct"], policy["approval_threshold_pct"]))
        if slate["independence_shortfall"]:
            fail("ERR_INDEPENDENCE_SHORTFALL",
                 "The slate is %s%% independent, below the floor of %s%%."
                 % (slate["independent_nominee_pct"], policy["independence_min_pct"]))
        for nominee in slate_nominees(slate_id):
            if nominee["status"] == "PROPOSED":
                _apply(nominee, {"status": "CONFIRMED"})
        slate["status"] = "APPROVED"
        touch(slate)
    elif decision == "REJECT":
        if not slate["quorum_met"]:
            fail("ERR_QUORUM_NOT_MET",
                 "The ballot count has not reached the quorum of %s." % policy["quorum_size"])
        return_slate_to_draft(slate, policy)
    else:
        firms = {}
        for nominee in slate_nominees(slate_id):
            if nominee["status"] not in LIVE_NOMINEE:
                continue
            firm = void_nominee_row(nominee, defer_candidate=True)
            if firm is not None:
                firms[firm["id"]] = firm
        void_cast_ballots(slate)
        slate["status"] = "ABANDONED"
        touch(slate)
        settle_nominee_change({slate_id}, list(firms.values()), policy, revise_reviews=False)
        recompute_slate_tally(slate, policy)
    touch(slate)
    return emit(slate)


@bp.post("/slates/<slate_id>/file")
def file_slate(slate_id):
    require(CORPORATE_SECRETARY)
    slate = need("slate", slate_id)
    if slate["status"] != "APPROVED":
        fail("ERR_SLATE_STATE_INVALID",
             "Only an APPROVED slate may be filed; this one is %s." % slate["status"])
    if slate["universal_proxy_applicable"] and slate["nominee_count"] < slate["seat_count"]:
        fail("ERR_UNIVERSAL_PROXY_MINIMUM",
             "A contested card needs at least %s nominees; the slate carries %s."
             % (slate["seat_count"], slate["nominee_count"]))
    slate["status"] = "FILED"
    slate["filed_at"] = clock_instant()
    touch(slate)
    return emit(slate)


def _mint_director(nominee, candidate):
    """Hop 3 of the election cascade: a new board member enters ONBOARDING."""
    today = clock_date()
    row = new_row({
        "full_name": candidate["full_name"],
        "email": candidate["email"],
        "birth_date": candidate["birth_date"],
        "appointed_on": today.isoformat(),
        "source_candidate_id": candidate["id"],
        "is_management": False,
        "is_sitting_ceo_elsewhere": bool(candidate["is_sitting_ceo"]),
        "is_independent": bool(nominee["is_independent"]),
        "shares_held": 0,
        "service_status": "ONBOARDING",
        "compliance_status": "COMPLIANT",
        "onboarding_status": "NOT_STARTED",
        "onboarding_completion_pct": 0.00,
        "age_years": whole_years(parse_iso_date(candidate["birth_date"]), today),
        "tenure_years": 0,
        "external_public_board_count": len(candidate_board_set(candidate["id"])),
        "education_hours_cycle": 0.0,
        "retirement_notice_at": None,
    })
    db.directors[row["id"]] = row
    seed_onboarding_items(row)
    return row


@bp.post("/slates/<slate_id>/record-election")
def record_election(slate_id):
    require(CORPORATE_SECRETARY)
    b = body()
    ids = required(b, "elected_nominee_ids", "array")
    for value in ids:
        if not isinstance(value, str):
            fail("ERR_INVALID_REQUEST",
                 "Field 'elected_nominee_ids' must contain nominee id strings.")
    slate = need("slate", slate_id)
    chosen = []
    for nominee_id in ids:
        row = db.nominees.get(nominee_id)
        if row is None or row["slate_id"] != slate_id:
            fail("ERR_NOMINEE_NOT_FOUND",
                 "No slate nominee of this slate exists with id %s." % nominee_id)
        chosen.append(row)
    if slate["status"] != "FILED":
        fail("ERR_SLATE_STATE_INVALID",
             "Only a FILED slate may record an election; this one is %s." % slate["status"])
    for row in chosen:
        if row["status"] != "CONFIRMED":
            fail("ERR_NOMINEE_STATE_INVALID",
                 "Nominee %s is %s, not CONFIRMED." % (row["id"], row["status"]))
    if len(ids) > slate["seat_count"]:
        fail("ERR_SEAT_COUNT_EXCEEDED",
             "%s elected nominees exceed the %s seats standing for election."
             % (len(ids), slate["seat_count"]))

    policy = governing_policy()
    elected_ids = set(ids)
    slate["status"] = "ELECTION_RECORDED"
    slate["election_recorded_at"] = clock_instant()
    touch(slate)

    departing = {}
    ordered = sorted(slate_nominees(slate_id), key=lambda n: (n["ballot_order"], n["id"]))
    for nominee in ordered:
        if nominee["status"] != "CONFIRMED":
            continue
        candidate = db.candidates.get(nominee.get("candidate_id"))
        incumbent = db.directors.get(nominee.get("incumbent_director_id"))
        if nominee["id"] in elected_ids:
            _apply(nominee, {"status": "ELECTED"})
            if candidate is not None:
                _apply(candidate, {"status": "ELECTED"})
            if incumbent is None and candidate is not None:
                _mint_director(nominee, candidate)
        else:
            _apply(nominee, {"status": "NOT_ELECTED"})
            if candidate is not None:
                _apply(candidate, {"status": "NOT_ELECTED"})
            if incumbent is not None and incumbent["service_status"] == "SEATED":
                _apply(incumbent, {"service_status": "NOT_RENOMINATED"})
                departing[incumbent["id"]] = incumbent

    for director in list(db.directors.values()):
        if director["service_status"] == "RETIREMENT_NOTICED":
            _apply(director, {"service_status": "RETIRED"})
            departing[director["id"]] = director
    for director in departing.values():
        end_active_assignments(director)

    firms = {}
    for nominee in slate_nominees(slate_id):
        firm = sourcing_firm(nominee)
        if firm is not None:
            firms[firm["id"]] = firm
    settle_nominee_change({slate_id}, list(firms.values()), policy, revise_reviews=False)
    return emit(slate)

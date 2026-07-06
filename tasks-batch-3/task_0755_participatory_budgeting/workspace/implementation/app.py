"""Participatory Budgeting & Civic Engagement API (Flask, in-memory)."""
import os

from flask import Flask, request

from store import store, lock
from util import (
    ApiError, err, authenticate, body, require_fields, as_int, respond,
    error_body, pub, pub_resident, paginate, sorted_by_seq, set_common, touch,
    parse_iso, clock_now, fmt_iso, LANGUAGES, PHASE_ORDER,
)
import domain
from domain import (
    get_cycle, get_category, get_resident, get_proposal, get_ballot,
    get_milestone, categories_of, proposals_of_cycle, line_items_of,
    entries_of_ballot, milestones_of, recompute_provisional,
    compute_final_estimate, recompute_vote_score, recompute_ledger,
    entry_points, COMMITTED_STATUSES,
)

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling & request serialization
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_body(e)


@app.errorhandler(404)
def handle_404(e):
    return error_body(ApiError("ERR_VALIDATION", 404, "Not found."))


@app.errorhandler(405)
def handle_405(e):
    return error_body(ApiError("ERR_VALIDATION", 405, "Method not allowed."))


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return error_body(e)
    return error_body(ApiError("ERR_INTERNAL", 500, str(e)))


@app.before_request
def _acquire():
    lock.acquire()


@app.teardown_request
def _release(exc):
    try:
        lock.release()
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Validation helpers shared by routes
# ---------------------------------------------------------------------------
def check_enum(value, allowed, field):
    if value not in allowed:
        err("ERR_VALIDATION", 400, "Field %s has an invalid value." % field)


def require_phase(cycle, expected):
    if isinstance(expected, (set, list, tuple)):
        if cycle["phase"] not in expected:
            err("ERR_WRONG_PHASE", 409, "Cycle is not in the required phase.")
    else:
        if cycle["phase"] != expected:
            err("ERR_WRONG_PHASE", 409, "Cycle is not in the required phase.")


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["BudgetAdmin"])
    data = body()
    require_fields(data, ["to_iso8601"])
    try:
        dt = parse_iso(data["to_iso8601"])
    except Exception:
        err("ERR_VALIDATION", 400, "to_iso8601 is not a valid ISO 8601 instant.")
    store.clock = dt
    return respond({}, "object", 200)


# ===========================================================================
# BudgetCycle
# ===========================================================================
@app.route("/budget-cycles", methods=["POST"])
def create_cycle():
    authenticate(["BudgetAdmin"])
    data = body()
    require_fields(data, [
        "name", "fiscal_year", "total_budget_cents", "voting_method",
        "per_project_cap_cents", "per_voter_allocation_cap_cents",
        "submission_start", "submission_end", "voting_start", "voting_end",
    ])
    as_int(data["fiscal_year"], "fiscal_year")
    tb = as_int(data["total_budget_cents"], "total_budget_cents")
    if tb <= 0:
        err("ERR_VALIDATION", 400, "total_budget_cents must be > 0.")
    check_enum(data["voting_method"], {"RANKED", "ALLOCATION"}, "voting_method")
    ppc = as_int(data["per_project_cap_cents"], "per_project_cap_cents")
    if ppc <= 0:
        err("ERR_VALIDATION", 400, "per_project_cap_cents must be > 0.")
    pvac = as_int(data["per_voter_allocation_cap_cents"], "per_voter_allocation_cap_cents")
    if pvac < 0:
        err("ERR_VALIDATION", 400, "per_voter_allocation_cap_cents must be >= 0.")
    min_age = data.get("min_voter_age", 16)
    if min_age is None:
        min_age = 16
    min_age = as_int(min_age, "min_voter_age")
    if min_age < 0:
        err("ERR_VALIDATION", 400, "min_voter_age must be >= 0.")
    lang = data.get("default_language", "en") or "en"
    check_enum(lang, LANGUAGES, "default_language")

    try:
        ss = parse_iso(data["submission_start"])
        se = parse_iso(data["submission_end"])
        vs = parse_iso(data["voting_start"])
        ve = parse_iso(data["voting_end"])
    except Exception:
        err("ERR_VALIDATION", 400, "Window fields must be valid ISO 8601 instants.")

    # Window validation: each start strictly before its own end; the two
    # half-open windows must not overlap; submission_end <= voting_start
    # (adjacency allowed).
    if not (ss < se) or not (vs < ve) or not (se <= vs):
        err("ERR_PHASE_WINDOW_OVERLAP", 422, "Cycle phase windows are invalid or overlap.")

    cycle = {
        "name": data["name"],
        "fiscal_year": data["fiscal_year"],
        "total_budget_cents": tb,
        "voting_method": data["voting_method"],
        "per_project_cap_cents": ppc,
        "per_voter_allocation_cap_cents": pvac,
        "min_voter_age": min_age,
        "default_language": lang,
        "submission_start": data["submission_start"],
        "submission_end": data["submission_end"],
        "voting_start": data["voting_start"],
        "voting_end": data["voting_end"],
        "phase": "DRAFT",
        "total_committed_cents": 0,
        "uncommitted_cents": tb,
        "completed_project_count": 0,
    }
    set_common(cycle)
    store.budget_cycles[cycle["id"]] = cycle
    return respond(pub(cycle), "object", 201)


@app.route("/budget-cycles/<cid>", methods=["GET"])
def read_cycle(cid):
    authenticate(["Anonymous", "Resident", "Reviewer", "BudgetAdmin"])
    cycle = get_cycle(cid)
    return respond(pub(cycle), "object", 200)


@app.route("/budget-cycles/<cid>/phase-transitions", methods=["POST"])
def phase_transition(cid):
    authenticate(["BudgetAdmin"])
    data = body()
    require_fields(data, ["target_phase"])
    target = data["target_phase"]
    check_enum(target, set(PHASE_ORDER), "target_phase")
    cycle = get_cycle(cid)

    current = cycle["phase"]
    idx = PHASE_ORDER.index(current)
    next_phase = PHASE_ORDER[idx + 1] if idx + 1 < len(PHASE_ORDER) else None
    if target != next_phase:
        err("ERR_INVALID_PHASE_TRANSITION", 409,
            "target_phase is not the single next phase in the pipeline.")

    # Extra preconditions on specific advances.
    if current == "DRAFT":  # -> SUBMISSION
        if not categories_of(cid):
            err("ERR_INVALID_STATE", 409,
                "At least one Category must exist before leaving DRAFT.")
    if current == "SELECTION":  # -> IMPLEMENTATION
        has_current_run = any(
            r["budget_cycle_id"] == cid and r["is_current"]
            for r in store.selection_runs.values()
        )
        if not has_current_run:
            err("ERR_INVALID_STATE", 409,
                "A current SelectionRun must exist before leaving SELECTION.")

    cycle["phase"] = target
    touch(cycle)

    # Cascade: entering VOTING moves every COSTED proposal to ON_BALLOT.
    if target == "VOTING":
        for p in proposals_of_cycle(cid):
            if p["status"] == "COSTED":
                p["status"] = "ON_BALLOT"
                touch(p)

    return respond(pub(cycle), "object", 200)


@app.route("/budget-cycles/<cid>/categories", methods=["POST"])
def create_category(cid):
    authenticate(["BudgetAdmin"])
    data = body()
    require_fields(data, ["name", "category_budget_cap_cents"])
    cap = as_int(data["category_budget_cap_cents"], "category_budget_cap_cents")
    if cap <= 0:
        err("ERR_VALIDATION", 400, "category_budget_cap_cents must be > 0.")
    display_order = data.get("display_order", 0)
    if display_order is None:
        display_order = 0
    as_int(display_order, "display_order")
    cycle = get_cycle(cid)

    cat = {
        "budget_cycle_id": cid,
        "name": data["name"],
        "description": data.get("description", "") or "",
        "category_budget_cap_cents": cap,
        "display_order": display_order,
        "committed_cents": 0,
        "remaining_cap_cents": cap,
    }
    set_common(cat)
    store.categories[cat["id"]] = cat
    return respond(pub(cat), "object", 201)


@app.route("/budget-cycles/<cid>/categories", methods=["GET"])
def list_categories(cid):
    authenticate(["Anonymous", "Resident", "Reviewer", "BudgetAdmin"])
    get_cycle(cid)
    items = sorted_by_seq(categories_of(cid))
    page, meta = paginate(items)
    return respond([pub(c) for c in page], "array", 200, meta)


@app.route("/budget-cycles/<cid>/proposals", methods=["GET"])
def list_cycle_proposals(cid):
    authenticate(["Anonymous", "Resident", "Reviewer", "BudgetAdmin"])
    get_cycle(cid)
    items = proposals_of_cycle(cid)
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = sorted_by_seq(items)
    page, meta = paginate(items)
    return respond([pub(p) for p in page], "array", 200, meta)


@app.route("/budget-cycles/<cid>/selection-runs", methods=["GET"])
def list_selection_runs(cid):
    authenticate(["Anonymous", "Resident", "Reviewer", "BudgetAdmin"])
    get_cycle(cid)
    items = [r for r in store.selection_runs.values() if r["budget_cycle_id"] == cid]
    items = sorted_by_seq(items)
    page, meta = paginate(items)
    return respond([pub(r) for r in page], "array", 200, meta)


@app.route("/budget-cycles/<cid>/selection-runs", methods=["POST"])
def create_selection_run(cid):
    authenticate(["BudgetAdmin"])
    data = body()
    require_fields(data, ["expected_budgetcycle_version"])
    expected = as_int(data["expected_budgetcycle_version"], "expected_budgetcycle_version")
    cycle = get_cycle(cid)
    require_phase(cycle, "SELECTION")
    if expected != cycle["version"]:
        err("ERR_STALE_CYCLE_VERSION", 412, "expected_budgetcycle_version is stale.")

    # Funding selection (waterfall allocation over the ON_BALLOT slate).
    slate = [p for p in proposals_of_cycle(cid) if p["status"] == "ON_BALLOT"]
    slate.sort(key=lambda p: (-p["vote_score"], p["_seq"]))

    remaining_total = cycle["total_budget_cents"]
    remaining_cat = {c["id"]: c["category_budget_cap_cents"] for c in categories_of(cid)}

    selected_count = 0
    total_awarded = 0
    for p in slate:
        cost = p["estimated_cost_cents"]
        if cost > cycle["per_project_cap_cents"]:
            p["status"] = "NOT_SELECTED"
            touch(p)
            continue
        cat_pool = remaining_cat.get(p["category_id"], 0)
        if cost <= min(remaining_total, cat_pool):
            p["status"] = "SELECTED"
            p["awarded_cents"] = cost
            remaining_total -= cost
            remaining_cat[p["category_id"]] = cat_pool - cost
            selected_count += 1
            total_awarded += cost
            touch(p)
        else:
            p["status"] = "NOT_SELECTED"
            touch(p)

    # Supersede prior current runs.
    for r in store.selection_runs.values():
        if r["budget_cycle_id"] == cid and r["is_current"]:
            r["is_current"] = False
            touch(r)

    run = {
        "budget_cycle_id": cid,
        "selected_count": selected_count,
        "total_awarded_cents": total_awarded,
        "is_current": True,
    }
    set_common(run)
    store.selection_runs[run["id"]] = run

    # Ledger cascade + the run's own cycle-version bump.
    recompute_ledger(cycle)
    touch(cycle)

    return respond(pub(run), "object", 201)


# ===========================================================================
# Resident
# ===========================================================================
@app.route("/residents", methods=["POST"])
def create_resident():
    authenticate(["Anonymous", "BudgetAdmin"])
    data = body()
    require_fields(data, [
        "full_name", "date_of_birth", "residency_document_ref", "residency_address",
    ])
    lang = data.get("preferred_language", "en") or "en"
    check_enum(lang, LANGUAGES, "preferred_language")
    needs = data.get("accessibility_needs", [])
    if needs is None:
        needs = []
    if not isinstance(needs, list):
        err("ERR_VALIDATION", 400, "accessibility_needs must be a list.")

    r = {
        "full_name": data["full_name"],
        "date_of_birth": data["date_of_birth"],
        "residency_document_ref": data["residency_document_ref"],
        "residency_address": data["residency_address"],
        "preferred_language": lang,
        "accessibility_needs": needs,
        "eligibility_status": "UNVERIFIED",
        "rejection_reason": None,
    }
    set_common(r)
    store.residents[r["id"]] = r
    return respond(pub_resident(r), "object", 201)


@app.route("/residents/<rid>", methods=["GET"])
def read_resident(rid):
    authenticate(["Resident", "Reviewer", "BudgetAdmin"])
    r = get_resident(rid)
    return respond(pub_resident(r), "object", 200)


@app.route("/residents/<rid>/verification-requests", methods=["POST"])
def verification_request(rid):
    authenticate(["Anonymous", "Resident"])
    data = body()
    r = get_resident(rid)
    if r["eligibility_status"] not in ("UNVERIFIED", "REJECTED"):
        err("ERR_INVALID_STATE", 409, "Resident is not in a state that can request verification.")
    if data.get("residency_document_ref") is not None:
        r["residency_document_ref"] = data["residency_document_ref"]
    if r["eligibility_status"] == "REJECTED":
        r["rejection_reason"] = None
    r["eligibility_status"] = "PENDING_VERIFICATION"
    touch(r)
    return respond(pub_resident(r), "object", 200)


@app.route("/residents/<rid>/verification-decisions", methods=["POST"])
def verification_decision(rid):
    authenticate(["Reviewer"])
    data = body()
    require_fields(data, ["decision"])
    check_enum(data["decision"], {"APPROVE", "REJECT"}, "decision")
    r = get_resident(rid)
    if r["eligibility_status"] != "PENDING_VERIFICATION":
        err("ERR_INVALID_STATE", 409, "Resident is not pending verification.")
    if data["decision"] == "APPROVE":
        r["eligibility_status"] = "VERIFIED"
    else:
        r["eligibility_status"] = "REJECTED"
        r["rejection_reason"] = data.get("rejection_reason")
    touch(r)
    return respond(pub_resident(r), "object", 200)


# ===========================================================================
# Proposal
# ===========================================================================
@app.route("/budget-cycles/<cid>/proposals", methods=["POST"])
def create_proposal(cid):
    uid, role = authenticate(["Resident"])
    data = body()
    require_fields(data, ["category_id", "title", "summary"])
    translations = data.get("translations", {})
    if translations is None:
        translations = {}
    if not isinstance(translations, dict):
        err("ERR_VALIDATION", 400, "translations must be an object.")
    cycle = get_cycle(cid)
    category = get_category(data["category_id"])
    require_phase(cycle, "SUBMISSION")
    if category["budget_cycle_id"] != cid:
        err("ERR_CATEGORY_CYCLE_MISMATCH", 422,
            "category_id belongs to a different cycle.")

    p = {
        "budget_cycle_id": cid,
        "category_id": data["category_id"],
        "submitter_id": uid,
        "title": data["title"],
        "summary": data["summary"],
        "translations": translations,
        "status": "DRAFT",
        "provisional_estimate_cents": 0,
        "estimated_cost_cents": 0,
        "vote_score": 0,
        "awarded_cents": 0,
        "rejection_reason": None,
    }
    set_common(p)
    store.proposals[p["id"]] = p
    return respond(pub(p), "object", 201)


@app.route("/proposals/<pid>", methods=["GET"])
def read_proposal(pid):
    authenticate(["Anonymous", "Resident", "Reviewer", "BudgetAdmin"])
    p = get_proposal(pid)
    return respond(pub(p), "object", 200)


@app.route("/proposals", methods=["GET"])
def list_proposals():
    authenticate(["Anonymous", "Resident", "Reviewer", "BudgetAdmin"])
    items = list(store.proposals.values())
    for field in ("budget_cycle_id", "category_id", "submitter_id", "status"):
        val = request.args.get(field)
        if val:
            items = [p for p in items if p[field] == val]
    items = sorted_by_seq(items)
    page, meta = paginate(items)
    return respond([pub(p) for p in page], "array", 200, meta)


@app.route("/proposals/<pid>/submit", methods=["POST"])
def submit_proposal(pid):
    uid, role = authenticate(["Resident"])
    body()
    p = get_proposal(pid)
    cycle = get_cycle(p["budget_cycle_id"])
    require_phase(cycle, "SUBMISSION")
    if p["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Proposal is not in DRAFT.")
    if p["submitter_id"] != uid:
        err("ERR_NOT_OWNER", 403, "Acting resident is not the proposal submitter.")
    p["status"] = "SUBMITTED"
    touch(p)
    return respond(pub(p), "object", 200)


@app.route("/proposals/<pid>/review-decisions", methods=["POST"])
def review_decision(pid):
    authenticate(["Reviewer"])
    data = body()
    require_fields(data, ["decision"])
    check_enum(data["decision"], {"APPROVE", "REJECT"}, "decision")
    p = get_proposal(pid)
    cycle = get_cycle(p["budget_cycle_id"])
    require_phase(cycle, "DEVELOPMENT")
    if p["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Proposal is not in SUBMITTED.")
    if data["decision"] == "APPROVE":
        p["status"] = "DEVELOPING"
    else:
        p["status"] = "REJECTED"
        p["rejection_reason"] = data.get("rejection_reason")
    touch(p)
    return respond(pub(p), "object", 200)


@app.route("/proposals/<pid>/cost-line-items", methods=["POST"])
def add_cost_line_item(pid):
    uid, role = authenticate(["Resident", "Reviewer"])
    data = body()
    require_fields(data, ["label", "unit_cost_cents", "quantity"])
    unit_cost = as_int(data["unit_cost_cents"], "unit_cost_cents")
    if unit_cost < 0:
        err("ERR_VALIDATION", 400, "unit_cost_cents must be >= 0.")
    quantity = as_int(data["quantity"], "quantity")
    if quantity < 1:
        err("ERR_VALIDATION", 400, "quantity must be >= 1.")
    contingency = data.get("contingency_pct", 0)
    if contingency is None:
        contingency = 0
    if isinstance(contingency, bool) or not isinstance(contingency, (int, float)):
        err("ERR_VALIDATION", 400, "contingency_pct must be a number.")
    if contingency < 0:
        err("ERR_VALIDATION", 400, "contingency_pct must be >= 0.")

    p = get_proposal(pid)
    cycle = get_cycle(p["budget_cycle_id"])
    require_phase(cycle, "DEVELOPMENT")
    if p["status"] != "DEVELOPING":
        err("ERR_INVALID_STATE", 409, "Proposal is not in DEVELOPING.")
    if role == "Resident" and p["submitter_id"] != uid:
        err("ERR_NOT_OWNER", 403, "Acting resident is not the proposal submitter.")

    line = {
        "proposal_id": pid,
        "label": data["label"],
        "unit_cost_cents": unit_cost,
        "quantity": quantity,
        "contingency_pct": contingency,
        "line_provisional_cents": 0,
    }
    set_common(line)
    store.cost_line_items[line["id"]] = line
    line["line_provisional_cents"] = domain.line_provisional(line)
    recompute_provisional(p)
    touch(p)
    return respond(pub(line), "object", 201)


@app.route("/proposals/<pid>/cost-line-items", methods=["GET"])
def list_cost_line_items(pid):
    authenticate(["Anonymous", "Resident", "Reviewer", "BudgetAdmin"])
    get_proposal(pid)
    items = sorted_by_seq(line_items_of(pid))
    page, meta = paginate(items)
    return respond([pub(li) for li in page], "array", 200, meta)


@app.route("/proposals/<pid>/finalize-cost", methods=["POST"])
def finalize_cost(pid):
    authenticate(["Reviewer"])
    body()
    p = get_proposal(pid)
    cycle = get_cycle(p["budget_cycle_id"])
    require_phase(cycle, "DEVELOPMENT")
    if p["status"] != "DEVELOPING":
        err("ERR_INVALID_STATE", 409, "Proposal is not in DEVELOPING.")
    if not line_items_of(pid):
        err("ERR_NO_LINE_ITEMS", 422, "Proposal has no cost line items.")
    p["estimated_cost_cents"] = compute_final_estimate(p)
    p["status"] = "COSTED"
    touch(p)
    return respond(pub(p), "object", 200)


@app.route("/proposals/<pid>/release-funding", methods=["POST"])
def release_funding(pid):
    authenticate(["BudgetAdmin"])
    body()
    p = get_proposal(pid)
    cycle = get_cycle(p["budget_cycle_id"])
    require_phase(cycle, "IMPLEMENTATION")
    if p["status"] != "SELECTED":
        err("ERR_INVALID_STATE", 409, "Proposal is not SELECTED.")
    p["status"] = "IN_IMPLEMENTATION"
    touch(p)
    return respond(pub(p), "object", 200)


@app.route("/proposals/<pid>/cancel-funding", methods=["POST"])
def cancel_funding(pid):
    authenticate(["BudgetAdmin"])
    body()
    p = get_proposal(pid)
    cycle = get_cycle(p["budget_cycle_id"])
    if p["status"] == "SELECTED":
        require_phase(cycle, {"SELECTION", "IMPLEMENTATION"})
    elif p["status"] == "IN_IMPLEMENTATION":
        require_phase(cycle, "IMPLEMENTATION")
    else:
        err("ERR_INVALID_STATE", 409, "Proposal is not in a cancellable state.")
    p["status"] = "CANCELLED"
    p["awarded_cents"] = 0
    touch(p)
    recompute_ledger(cycle)
    return respond(pub(p), "object", 200)


@app.route("/proposals/<pid>/ballot-entries", methods=["GET"])
def list_proposal_ballot_entries(pid):
    authenticate(["Anonymous", "Resident", "Reviewer", "BudgetAdmin"])
    get_proposal(pid)
    items = [e for e in store.ballot_entries.values() if e["proposal_id"] == pid]
    items = sorted_by_seq(items)
    page, meta = paginate(items)
    return respond([pub(e) for e in page], "array", 200, meta)


@app.route("/proposals/<pid>/milestones", methods=["GET"])
def list_proposal_milestones(pid):
    authenticate(["Anonymous", "Resident", "Reviewer", "BudgetAdmin"])
    get_proposal(pid)
    items = sorted_by_seq(milestones_of(pid))
    page, meta = paginate(items)
    return respond([pub(m) for m in page], "array", 200, meta)


@app.route("/proposals/<pid>/report-backs", methods=["GET"])
def list_proposal_report_backs(pid):
    authenticate(["Anonymous", "Resident", "Reviewer", "BudgetAdmin"])
    get_proposal(pid)
    items = [rb for rb in store.report_backs.values() if rb["proposal_id"] == pid]
    items = sorted_by_seq(items)
    page, meta = paginate(items)
    return respond([pub(rb) for rb in page], "array", 200, meta)


# ===========================================================================
# Ballot
# ===========================================================================
@app.route("/budget-cycles/<cid>/ballots", methods=["POST"])
def create_ballot(cid):
    uid, role = authenticate(["Resident"])
    body()
    cycle = get_cycle(cid)
    resident = get_resident(uid)
    require_phase(cycle, "VOTING")
    if resident["eligibility_status"] != "VERIFIED":
        err("ERR_RESIDENT_NOT_ELIGIBLE", 403, "Voter is not VERIFIED.")
    from util import compute_age
    voter_age = compute_age(resident["date_of_birth"], clock_now())
    if voter_age < cycle["min_voter_age"]:
        err("ERR_UNDER_AGE", 422, "Voter does not meet the minimum voting age.")
    for b in store.ballots.values():
        if b["budget_cycle_id"] == cid and b["voter_id"] == uid and b["status"] in ("DRAFT", "CAST"):
            err("ERR_DUPLICATE_BALLOT", 409, "Resident already holds an active ballot in this cycle.")

    ballot = {
        "budget_cycle_id": cid,
        "voter_id": uid,
        "status": "DRAFT",
        "method": cycle["voting_method"],
        "total_allocated_cents": 0,
        "cast_at": None,
    }
    set_common(ballot)
    store.ballots[ballot["id"]] = ballot
    return respond(pub(ballot), "object", 201)


@app.route("/ballots/<bid>", methods=["GET"])
def read_ballot(bid):
    authenticate(["Resident", "Reviewer", "BudgetAdmin"])
    b = get_ballot(bid)
    return respond(pub(b), "object", 200)


@app.route("/ballots", methods=["GET"])
def list_ballots():
    authenticate(["Reviewer", "BudgetAdmin"])
    items = list(store.ballots.values())
    for field in ("voter_id", "budget_cycle_id", "status"):
        val = request.args.get(field)
        if val:
            items = [b for b in items if b[field] == val]
    items = sorted_by_seq(items)
    page, meta = paginate(items)
    return respond([pub(b) for b in page], "array", 200, meta)


@app.route("/ballots/<bid>/entries", methods=["POST"])
def add_ballot_entry(bid):
    uid, role = authenticate(["Resident"])
    data = body()
    require_fields(data, ["proposal_id"])
    rank = data.get("rank")
    allocated = data.get("allocated_cents")
    if rank is not None:
        as_int(rank, "rank")
        if rank < 1 or rank > 10:
            err("ERR_VALIDATION", 400, "rank must be between 1 and 10.")
    if allocated is not None:
        as_int(allocated, "allocated_cents")
        if allocated < 0:
            err("ERR_VALIDATION", 400, "allocated_cents must be >= 0.")

    ballot = get_ballot(bid)
    proposal = get_proposal(data["proposal_id"])

    if ballot["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Entries may only be added to a DRAFT ballot.")

    # Method-specific shape validation.
    if ballot["method"] == "RANKED":
        if rank is None or allocated is not None:
            err("ERR_VALIDATION", 400, "RANKED entries must carry rank and not allocated_cents.")
    else:  # ALLOCATION
        if allocated is None or rank is not None:
            err("ERR_VALIDATION", 400, "ALLOCATION entries must carry allocated_cents and not rank.")

    if proposal["status"] != "ON_BALLOT":
        err("ERR_PROPOSAL_NOT_ON_BALLOT", 409, "Referenced proposal is not ON_BALLOT.")
    if ballot["voter_id"] != uid:
        err("ERR_NOT_OWNER", 403, "Acting resident is not the ballot voter.")

    entry = {
        "ballot_id": bid,
        "proposal_id": data["proposal_id"],
        "rank": rank,
        "allocated_cents": allocated,
        "points": entry_points(rank) if ballot["method"] == "RANKED" else 0,
        "active": True,
    }
    set_common(entry)
    store.ballot_entries[entry["id"]] = entry
    _recompute_total_allocated(ballot)
    touch(ballot)
    return respond(pub(entry), "object", 201)


def _recompute_total_allocated(ballot):
    if ballot["method"] != "ALLOCATION":
        ballot["total_allocated_cents"] = 0
        return
    total = 0
    for e in entries_of_ballot(ballot["id"]):
        if e.get("active"):
            total += e.get("allocated_cents") or 0
    ballot["total_allocated_cents"] = total


@app.route("/ballots/<bid>/cast", methods=["POST"])
def cast_ballot(bid):
    uid, role = authenticate(["Resident"])
    body()
    ballot = get_ballot(bid)
    cycle = get_cycle(ballot["budget_cycle_id"])
    require_phase(cycle, "VOTING")
    if ballot["status"] not in ("DRAFT", "WITHDRAWN"):
        err("ERR_INVALID_STATE", 409, "Ballot cannot be cast from its current state.")
    if ballot["voter_id"] != uid:
        err("ERR_NOT_OWNER", 403, "Acting resident is not the ballot voter.")

    entries = entries_of_ballot(bid)
    active_entries = [e for e in entries if e.get("active")]
    if ballot["method"] == "RANKED":
        seen = set()
        for e in active_entries:
            r = e.get("rank")
            if r in seen:
                err("ERR_DUPLICATE_RANK", 422, "Two active entries share the same rank.")
            seen.add(r)
    else:  # ALLOCATION
        total = sum((e.get("allocated_cents") or 0) for e in active_entries)
        if total > cycle["per_voter_allocation_cap_cents"]:
            err("ERR_ALLOCATION_CAP_EXCEEDED", 422, "Total allocation exceeds the per-voter cap.")

    # Re-activate entries (relevant on re-cast from WITHDRAWN).
    for e in entries:
        e["active"] = True
    ballot["status"] = "CAST"
    ballot["cast_at"] = fmt_iso(clock_now())
    _recompute_total_allocated(ballot)
    touch(ballot)

    # Recompute vote scores for referenced proposals.
    for pid in {e["proposal_id"] for e in entries}:
        p = store.proposals.get(pid)
        if p:
            recompute_vote_score(p)

    return respond(pub(ballot), "object", 200)


@app.route("/ballots/<bid>/withdraw", methods=["POST"])
def withdraw_ballot(bid):
    uid, role = authenticate(["Resident"])
    body()
    ballot = get_ballot(bid)
    cycle = get_cycle(ballot["budget_cycle_id"])
    require_phase(cycle, "VOTING")
    if ballot["status"] != "CAST":
        err("ERR_INVALID_STATE", 409, "Only a CAST ballot can be withdrawn.")
    if ballot["voter_id"] != uid:
        err("ERR_NOT_OWNER", 403, "Acting resident is not the ballot voter.")

    entries = entries_of_ballot(bid)
    for e in entries:
        e["active"] = False
    ballot["status"] = "WITHDRAWN"
    ballot["total_allocated_cents"] = 0
    touch(ballot)

    for pid in {e["proposal_id"] for e in entries}:
        p = store.proposals.get(pid)
        if p:
            recompute_vote_score(p)

    return respond(pub(ballot), "object", 200)


@app.route("/ballots/<bid>/entries", methods=["GET"])
def list_ballot_entries(bid):
    authenticate(["Resident", "Reviewer", "BudgetAdmin"])
    get_ballot(bid)
    items = sorted_by_seq(entries_of_ballot(bid))
    page, meta = paginate(items)
    return respond([pub(e) for e in page], "array", 200, meta)


# ===========================================================================
# Milestone & ReportBack
# ===========================================================================
@app.route("/proposals/<pid>/milestones", methods=["POST"])
def create_milestone(pid):
    authenticate(["Reviewer"])
    data = body()
    require_fields(data, ["title", "scheduled_start", "scheduled_end"])
    try:
        new_start = parse_iso(data["scheduled_start"])
        new_end = parse_iso(data["scheduled_end"])
    except Exception:
        err("ERR_VALIDATION", 400, "Milestone schedule fields must be ISO 8601 instants.")
    p = get_proposal(pid)

    # Milestones must keep a >= 1-day buffer from every sibling.
    from datetime import timedelta
    one_day = timedelta(days=1)
    for m in milestones_of(pid):
        s = parse_iso(m["scheduled_start"])
        e = parse_iso(m["scheduled_end"])
        if new_start >= e:
            gap_ok = (new_start - e) >= one_day
        elif s >= new_end:
            gap_ok = (s - new_end) >= one_day
        else:
            gap_ok = False
        if not gap_ok:
            err("ERR_MILESTONE_OVERLAP", 409,
                "Milestone schedule overlaps or violates the 1-day buffer.")

    m = {
        "proposal_id": pid,
        "title": data["title"],
        "scheduled_start": data["scheduled_start"],
        "scheduled_end": data["scheduled_end"],
        "status": "PLANNED",
        "blocked_reason": None,
    }
    set_common(m)
    store.milestones[m["id"]] = m
    return respond(pub(m), "object", 201)


@app.route("/milestones/<mid>/transitions", methods=["POST"])
def milestone_transition(mid):
    authenticate(["Reviewer"])
    data = body()
    require_fields(data, ["target_status"])
    target = data["target_status"]
    check_enum(target, {"PLANNED", "IN_PROGRESS", "BLOCKED", "COMPLETED"}, "target_status")
    m = get_milestone(mid)
    current = m["status"]
    proposal = store.proposals.get(m["proposal_id"])

    if current == "PLANNED" and target == "IN_PROGRESS":
        if not proposal or proposal["status"] != "IN_IMPLEMENTATION":
            err("ERR_INVALID_STATE", 409, "Owning proposal is not IN_IMPLEMENTATION.")
        m["status"] = "IN_PROGRESS"
    elif current == "IN_PROGRESS" and target == "BLOCKED":
        m["status"] = "BLOCKED"
        m["blocked_reason"] = data.get("blocked_reason")
    elif current == "BLOCKED" and target == "IN_PROGRESS":
        m["status"] = "IN_PROGRESS"
        m["blocked_reason"] = None
    elif current == "IN_PROGRESS" and target == "COMPLETED":
        m["status"] = "COMPLETED"
        _maybe_complete_proposal(proposal)
    else:
        err("ERR_INVALID_STATE", 409, "Requested milestone transition is not defined.")

    touch(m)
    return respond(pub(m), "object", 200)


def _maybe_complete_proposal(proposal):
    if not proposal or proposal["status"] != "IN_IMPLEMENTATION":
        return
    sibs = milestones_of(proposal["id"])
    if not sibs:
        return
    if all(s["status"] == "COMPLETED" for s in sibs):
        proposal["status"] = "COMPLETED"
        touch(proposal)
        cycle = store.budget_cycles.get(proposal["budget_cycle_id"])
        if cycle:
            cycle["completed_project_count"] = cycle.get("completed_project_count", 0) + 1
            touch(cycle)


@app.route("/proposals/<pid>/report-backs", methods=["POST"])
def create_report_back(pid):
    authenticate(["Reviewer"])
    data = body()
    require_fields(data, ["period_label", "narrative", "spent_cents"])
    spent = as_int(data["spent_cents"], "spent_cents")
    if spent < 0:
        err("ERR_VALIDATION", 400, "spent_cents must be >= 0.")
    translations = data.get("translations", {})
    if translations is None:
        translations = {}
    if not isinstance(translations, dict):
        err("ERR_VALIDATION", 400, "translations must be an object.")
    get_proposal(pid)

    rb = {
        "id": None,
        "proposal_id": pid,
        "period_label": data["period_label"],
        "narrative": data["narrative"],
        "translations": translations,
        "spent_cents": spent,
        "published_at": fmt_iso(clock_now()),
    }
    # Report-backs are append-only: only id and created_at (no version/updated_at).
    from util import new_id, wall_now
    rb["id"] = new_id()
    rb["created_at"] = fmt_iso(wall_now())
    rb["_seq"] = store.next_seq()
    store.report_backs[rb["id"]] = rb
    return respond(pub(rb), "object", 201)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

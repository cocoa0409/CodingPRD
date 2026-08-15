"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the server is restarted before each test, so nothing carries over). Setup
calls use get_success_data() so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Identity threading (PRD §2.1): Entrant and Judge are entity-backed roles, so
every ownership-gated call builds headers with the acting entity's id via
make_entrant_headers / make_judge_headers — never the shared constants.

Canonical timeline (PRD §2.6 logical clock):
  T_GENESIS (server default) -> configure season/category -> T_SUBMISSION_OPEN
  (open season, submit entries) -> T_AFTER_CLOSE (close submissions) -> judging
  -> lock finalists -> embargo (lifts at T_EMBARGO_LIFT) -> T_CEREMONY go-live.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    R3_WINDOW,
    T_AFTER_CLOSE,
    T_CEREMONY,
    T_CEREMONY_END,
    T_EMBARGO_LIFT,
    T_SUBMISSION_OPEN,
    WORK_COMPLETED,
)
from .factories import (
    create_announcement_payload,
    create_appeal_payload,
    create_category_payload,
    create_ceremony_payload,
    create_conflict_payload,
    create_entry_payload,
    create_entrant_payload,
    create_judge_payload,
    create_material_payload,
    create_round_payload,
    create_season_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_entrant_headers, make_judge_headers

ADMIN = TEST_USERS["program_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
VENDOR = TEST_USERS["vendor_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


# ---------------------------------------------------------------------------
# Seasons & categories
# ---------------------------------------------------------------------------

def create_season(code: str = "GALA-2026", include_optional: bool = True, **overrides):
    """Create a season (born DRAFT, PRD §3.1). Returns the season."""
    payload = create_season_payload(include_optional=include_optional, code=code, **overrides)
    return get_success_data(api_client.create_season(payload, ADMIN))


def create_category(season_id: str, **overrides):
    payload = create_category_payload(**overrides)
    return get_success_data(api_client.create_category(season_id, payload, ADMIN))


def create_published_category(season_id: str, **overrides):
    category = create_category(season_id, **overrides)
    return get_success_data(api_client.publish_category(category["id"], ADMIN))


def open_season(season_id: str, at: str = T_SUBMISSION_OPEN):
    """Move the clock into the submission window and open the season."""
    set_clock(at)
    return get_success_data(api_client.open_season(season_id, ADMIN))


def setup_open_season_with_category(
    code: str = "GALA-2026",
    category_overrides: dict | None = None,
    season_overrides: dict | None = None,
):
    """Season OPEN with one PUBLISHED category. Returns (season, category)."""
    season = create_season(code, **(season_overrides or {}))
    category = create_published_category(season["id"], **(category_overrides or {}))
    season = open_season(season["id"])
    return season, category


# ---------------------------------------------------------------------------
# Entrants, entries, materials, invoices
# ---------------------------------------------------------------------------

def register_entrant(email: str, legal_name: str | None = None):
    payload = create_entrant_payload(
        contact_email=email, legal_name=legal_name or email.split("@")[0]
    )
    return get_success_data(api_client.create_entrant(payload, ADMIN))


def create_draft_entry(
    category_id: str,
    entrant_id: str,
    title: str = "Work 1",
    work_completed_at: str = WORK_COMPLETED,
):
    payload = create_entry_payload(
        entrant_id=entrant_id, title=title, work_completed_at=work_completed_at
    )
    return get_success_data(
        api_client.create_entry(category_id, payload, make_entrant_headers(entrant_id))
    )


def attach_material(entry_id: str, entrant_id: str, ordinal: int = 1):
    """Attach a PENDING material to a draft entry. Returns the material."""
    payload = create_material_payload(
        uri=f"s3://material-{ordinal}.pdf",
        checksum_sha256=f"{ordinal:064x}",
    )
    return get_success_data(
        api_client.create_material(entry_id, payload, make_entrant_headers(entrant_id))
    )


def attach_accepted_material(entry_id: str, entrant_id: str, ordinal: int = 1):
    material = attach_material(entry_id, entrant_id, ordinal)
    return get_success_data(api_client.accept_material(material["id"], ADMIN))


def submit_entry(entry_id: str, entrant_id: str):
    return get_success_data(
        api_client.submit_entry(entry_id, make_entrant_headers(entrant_id))
    )


def list_entry_invoices(entry_id: str, headers=None):
    data = get_success_data(
        api_client.list_entry_invoices(entry_id, headers or ADMIN, params={"limit": 100})
    )
    return data if isinstance(data, list) else data.get("data", data)


def get_only_invoice(entry_id: str):
    invoices = list_entry_invoices(entry_id)
    assert len(invoices) == 1, f"expected exactly one invoice, got {len(invoices)}"
    return invoices[0]


def pay_invoice(invoice_id: str, entrant_id: str):
    return get_success_data(
        api_client.pay_invoice(invoice_id, make_entrant_headers(entrant_id))
    )


def mark_eligible(entry_id: str):
    return get_success_data(api_client.mark_eligible(entry_id, ADMIN))


def mark_ineligible(entry_id: str):
    return get_success_data(api_client.mark_ineligible(entry_id, ADMIN))


def get_entry(entry_id: str, headers=None):
    return get_success_data(api_client.get_entry(entry_id, headers or ADMIN))


def get_season(season_id: str):
    return get_success_data(api_client.get_season(season_id, ADMIN))


def get_invoice(invoice_id: str):
    return get_success_data(api_client.get_invoice(invoice_id, ADMIN))


def setup_submitted_entry(
    code: str = "GALA-SUB",
    category_overrides: dict | None = None,
    season_overrides: dict | None = None,
    submit: bool = True,
):
    """Season OPEN + PUBLISHED category + entrant + entry with one ACCEPTED
    material; when submit=True the entry is SUBMITTED with an ISSUED invoice.
    Returns a bundle dict."""
    season, category = setup_open_season_with_category(
        code, category_overrides=category_overrides, season_overrides=season_overrides
    )
    entrant = register_entrant("e1@x.com", "Entrant 1")
    entry = create_draft_entry(category["id"], entrant["id"])
    attach_accepted_material(entry["id"], entrant["id"])
    invoice = None
    if submit:
        entry = submit_entry(entry["id"], entrant["id"])
        invoice = get_only_invoice(entry["id"])
    return {
        "season": season,
        "category": category,
        "entrant": entrant,
        "entry": entry,
        "invoice": invoice,
    }


def setup_under_review_entry(code: str = "GALA-UR", **kwargs):
    """Entry UNDER_REVIEW with a PAID invoice."""
    bundle = setup_submitted_entry(code, **kwargs)
    bundle["invoice"] = pay_invoice(
        bundle["invoice"]["id"], bundle["entrant"]["id"]
    )
    bundle["entry"] = get_entry(bundle["entry"]["id"])
    return bundle


def setup_eligible_entry(code: str = "GALA-ELG", **kwargs):
    """Entry ELIGIBLE (season still OPEN)."""
    bundle = setup_under_review_entry(code, **kwargs)
    bundle["entry"] = mark_eligible(bundle["entry"]["id"])
    return bundle


def close_season_submissions(season_id: str, at: str = T_AFTER_CLOSE):
    set_clock(at)
    return get_success_data(api_client.close_submissions(season_id, ADMIN))


def setup_season_closed_with_eligible_entries(
    num_entries: int = 1,
    code: str = "GALA-CLO",
    finalist_slots: int = 1,
    panel_size: int = 3,
    season_overrides: dict | None = None,
    category_overrides: dict | None = None,
):
    """Season SUBMISSION_CLOSED with ``num_entries`` ELIGIBLE entries, each
    owned by its own entrant, each with a PAID invoice. Returns a bundle."""
    merged_category_overrides = {"finalist_slots": finalist_slots, "panel_size": panel_size}
    merged_category_overrides.update(category_overrides or {})
    season, category = setup_open_season_with_category(
        code,
        category_overrides=merged_category_overrides,
        season_overrides=season_overrides,
    )
    entrants, entries, invoices = [], [], []
    for i in range(num_entries):
        entrant = register_entrant(f"e{i + 1}@x.com", f"Entrant {i + 1}")
        entry = create_draft_entry(
            category["id"], entrant["id"], title=f"Work {i + 1}"
        )
        attach_accepted_material(entry["id"], entrant["id"], ordinal=i + 1)
        submit_entry(entry["id"], entrant["id"])
        invoice = get_only_invoice(entry["id"])
        pay_invoice(invoice["id"], entrant["id"])
        mark_eligible(entry["id"])
        entrants.append(entrant)
        entries.append(get_entry(entry["id"]))
        invoices.append(invoice)
    season = close_season_submissions(season["id"])
    return {
        "season": season,
        "category": category,
        "entrants": entrants,
        "entries": entries,
        "invoices": invoices,
    }


# ---------------------------------------------------------------------------
# Judges & panels
# ---------------------------------------------------------------------------

def create_active_judge(email: str, full_name: str | None = None):
    """Judge walked INVITED -> ACCEPTED -> ACTIVE (PRD §3.5). Empty affiliation
    list satisfies the activation precondition."""
    judge = get_success_data(
        api_client.create_judge(
            create_judge_payload(email=email, full_name=full_name or email.split("@")[0]),
            ADMIN,
        )
    )
    get_success_data(api_client.accept_judge(judge["id"], make_judge_headers(judge["id"])))
    return get_success_data(api_client.activate_judge(judge["id"], ADMIN))


def create_active_judges(n: int = 3):
    return [create_active_judge(f"j{i + 1}@x.com", f"Judge {i + 1}") for i in range(n)]


def current_round_version(round_id: str) -> int:
    return get_success_data(api_client.get_round(round_id, ADMIN))["version"]


def current_judge_version(judge_id: str) -> int:
    return get_success_data(api_client.get_judge(judge_id, ADMIN))["version"]


def propose_assignment(round_id: str, judge_id: str, role: str = "MEMBER"):
    """Propose a panel assignment; OCC-guarded on the round's version
    (PRD §2.9), re-read immediately before the write."""
    payload = {
        "judge_id": judge_id,
        "role": role,
        "expected_scoring_round_version": current_round_version(round_id),
    }
    return get_success_data(api_client.create_panel_assignment(round_id, payload, ADMIN))


def confirm_assignment(assignment_id: str, judge_id: str):
    return get_success_data(
        api_client.confirm_assignment(assignment_id, make_judge_headers(judge_id))
    )


def setup_locked_round(
    category_id: str,
    round_index: int = 1,
    scoring_mode: str = "RAW_RANK",
    window=R3_WINDOW,
    advance_count: int | None = 1,
    judges=None,
    num_judges: int = 3,
):
    """Round CONFIGURING -> PANEL_LOCKED with a fully confirmed panel (first
    judge is CHAIR). Caller must already have the season SUBMISSION_CLOSED.
    Returns (round, judges, assignments)."""
    payload = create_round_payload(
        round_index=round_index,
        scoring_mode=scoring_mode,
        scheduled_window_start=window[0],
        scheduled_window_end=window[1],
    )
    if advance_count is None:
        payload.pop("advance_count", None)
    else:
        payload["advance_count"] = advance_count
    round_ = get_success_data(api_client.create_round(category_id, payload, ADMIN))
    if judges is None:
        judges = create_active_judges(num_judges)
    assignments = []
    for position, judge in enumerate(judges):
        role = "CHAIR" if position == 0 else "MEMBER"
        assignment = propose_assignment(round_["id"], judge["id"], role)
        assignments.append(confirm_assignment(assignment["id"], judge["id"]))
    round_ = get_success_data(api_client.lock_panel(round_["id"], ADMIN))
    return round_, judges, assignments


def begin_judging(season_id: str):
    return get_success_data(api_client.begin_judging(season_id, ADMIN))


def open_round(round_id: str):
    return get_success_data(api_client.open_round(round_id, ADMIN))


def post_score(round_id: str, entry_id: str, judge_id: str, criterion_scores: dict):
    """Create a DRAFT ballot; OCC-guarded on the round's version (PRD §2.9),
    re-read immediately before the write."""
    payload = {
        "entry_id": entry_id,
        "judge_id": judge_id,
        "criterion_scores": criterion_scores,
        "expected_scoring_round_version": current_round_version(round_id),
    }
    return get_success_data(
        api_client.create_score(round_id, payload, make_judge_headers(judge_id))
    )


def submit_score(score_id: str, judge_id: str):
    return get_success_data(
        api_client.submit_score(score_id, make_judge_headers(judge_id))
    )


def score_entries(round_id: str, entries, judges, matrix=None):
    """Post + submit a complete ballot: every judge scores every entry.

    ``matrix`` maps (judge_position, entry_position) -> criterion_scores; the
    default awards entry i CRAFT = 10 - 2*i and IMPACT = 5 - i from every
    judge, which ranks entry order strictly descending under either scoring
    mode.
    Returns the list of submitted Score payloads in creation order.
    """
    submitted = []
    for j_pos, judge in enumerate(judges):
        for e_pos, entry in enumerate(entries):
            criterion_scores = (
                matrix.get((j_pos, e_pos))
                if matrix
                else {"CRAFT": 10 - 2 * e_pos, "IMPACT": 5 - e_pos}
            )
            score = post_score(round_id, entry["id"], judge["id"], criterion_scores)
            submitted.append(submit_score(score["id"], judge["id"]))
    return submitted


def close_round(round_id: str):
    return get_success_data(api_client.close_round(round_id, ADMIN))


def normalize_round(round_id: str):
    return get_success_data(api_client.normalize_round(round_id, ADMIN))


def list_round_scores(round_id: str):
    data = get_success_data(
        api_client.list_round_scores(round_id, ADMIN, params={"limit": 100})
    )
    return data if isinstance(data, list) else data.get("data", data)


def list_entry_scores(entry_id: str, headers=None):
    data = get_success_data(
        api_client.list_entry_scores(entry_id, headers or ADMIN, params={"limit": 100})
    )
    return data if isinstance(data, list) else data.get("data", data)


# ---------------------------------------------------------------------------
# Full judging pipeline (FINAL-only category)
# ---------------------------------------------------------------------------

def setup_normalized_final_round(
    num_entries: int = 2,
    finalist_slots: int = 1,
    code: str = "GALA-FIN",
    matrix=None,
    scoring_mode: str = "RAW_RANK",
):
    """Drive a single-category season to a NORMALIZED FINAL round:
    eligible entries -> close -> round 3 panel locked -> judging -> open ->
    complete ballots -> close -> normalize. Returns a bundle."""
    bundle = setup_season_closed_with_eligible_entries(
        num_entries=num_entries, code=code, finalist_slots=finalist_slots
    )
    round_, judges, assignments = setup_locked_round(
        bundle["category"]["id"],
        round_index=3,
        scoring_mode=scoring_mode,
        window=R3_WINDOW,
        advance_count=None,
    )
    bundle["season"] = begin_judging(bundle["season"]["id"])
    round_ = open_round(round_["id"])
    bundle["scores"] = score_entries(round_["id"], bundle["entries"], judges, matrix)
    close_round(round_["id"])
    bundle["round"] = normalize_round(round_["id"])
    bundle["judges"] = judges
    bundle["assignments"] = assignments
    bundle["entries"] = [get_entry(e["id"]) for e in bundle["entries"]]
    return bundle


def lock_finalists(season_id: str):
    return get_success_data(api_client.lock_finalists(season_id, ADMIN))


def get_finalist_record(entry_id: str):
    """The finalist record of an entry is an array of zero or one (PRD §3.7)."""
    data = get_success_data(api_client.get_entry_finalist_record(entry_id, ADMIN))
    records = data if isinstance(data, list) else data.get("data", data)
    assert len(records) <= 1, f"expected 0..1 finalist records, got {len(records)}"
    return records[0] if records else None


def setup_finalists_locked(
    num_entries: int = 2,
    finalist_slots: int = 1,
    code: str = "GALA-FLK",
    matrix=None,
):
    """Season JUDGING -> FINALISTS_LOCKED; finalist records created. Returns
    the bundle augmented with per-entry finalist records."""
    bundle = setup_normalized_final_round(
        num_entries=num_entries, finalist_slots=finalist_slots, code=code, matrix=matrix
    )
    bundle["season"] = lock_finalists(bundle["season"]["id"])
    bundle["finalist_records"] = {
        e["id"]: get_finalist_record(e["id"]) for e in bundle["entries"]
    }
    bundle["entries"] = [get_entry(e["id"]) for e in bundle["entries"]]
    return bundle


def setup_embargoed_season(
    num_entries: int = 1,
    finalist_slots: int = 1,
    code: str = "GALA-EMB",
    matrix=None,
):
    """Season EMBARGOED: all finalist records notified and acknowledged first.
    Returns the bundle."""
    bundle = setup_finalists_locked(
        num_entries=num_entries, finalist_slots=finalist_slots, code=code, matrix=matrix
    )
    for entry in bundle["entries"]:
        record = bundle["finalist_records"][entry["id"]]
        if record is None:
            continue
        record = get_success_data(api_client.notify_finalist(record["id"], ADMIN))
        get_success_data(
            api_client.acknowledge_finalist(
                record["id"], make_entrant_headers(entry["entrant_id"])
            )
        )
    bundle["season"] = get_success_data(
        api_client.embargo_season(
            bundle["season"]["id"], {"embargo_lifts_at": T_EMBARGO_LIFT}, ADMIN
        )
    )
    return bundle


def create_ceremony_for_season(season_id: str, category_ids, venue: str = "Grand Hall"):
    rundown = [
        {"segment_no": i + 1, "category_id": cid, "duration_seconds": 600}
        for i, cid in enumerate(category_ids)
    ]
    payload = create_ceremony_payload(
        venue_name=venue, starts_at=T_CEREMONY, ends_at=T_CEREMONY_END, rundown=rundown
    )
    return get_success_data(api_client.create_ceremony(season_id, payload, ADMIN))


def setup_ceremony_live(
    num_entries: int = 1,
    finalist_slots: int = 1,
    code: str = "GALA-LIV",
    matrix=None,
):
    """Season CEREMONY_LIVE with the ceremony LIVE. Returns the bundle with
    the ceremony attached."""
    bundle = setup_embargoed_season(
        num_entries=num_entries, finalist_slots=finalist_slots, code=code, matrix=matrix
    )
    ceremony = create_ceremony_for_season(
        bundle["season"]["id"], [bundle["category"]["id"]]
    )
    get_success_data(api_client.rehearse_ceremony(ceremony["id"], ADMIN))
    set_clock(T_CEREMONY)
    bundle["season"] = get_success_data(api_client.go_live(bundle["season"]["id"], ADMIN))
    bundle["ceremony"] = get_success_data(api_client.get_ceremony(ceremony["id"], ADMIN))
    return bundle


def setup_announced_winner(
    num_entries: int = 3,
    finalist_slots: int = 2,
    code: str = "GALA-ANN",
    matrix=None,
):
    """Full pipeline through the winner announcement: season CEREMONY_LIVE,
    announcement ANNOUNCED, rank-1 entry WINNER, other finalists NON_WINNER,
    fulfillment orders created (PRD §3.7). Returns the bundle."""
    bundle = setup_ceremony_live(
        num_entries=num_entries, finalist_slots=finalist_slots, code=code, matrix=matrix
    )
    announcement = get_success_data(
        api_client.create_announcement(
            bundle["category"]["id"],
            create_announcement_payload(ceremony_id=bundle["ceremony"]["id"]),
            ADMIN,
        )
    )
    bundle["announcement"] = get_success_data(api_client.announce(announcement["id"], ADMIN))
    bundle["entries"] = [get_entry(e["id"]) for e in bundle["entries"]]
    return bundle


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

def file_appeal(entry_id: str, filed_by_entrant_id: str, grounds: str = "SCORING_ERROR", narrative: str = "n"):
    payload = create_appeal_payload(
        filed_by_entrant_id=filed_by_entrant_id, grounds=grounds, narrative=narrative
    )
    return api_client.create_appeal(
        entry_id, payload, make_entrant_headers(filed_by_entrant_id)
    )


def file_conflict(
    judge_id: str,
    season_id: str,
    entrant_id: str,
    severity: str = "HARD",
    conflict_type: str = "FINANCIAL",
):
    """File a judge's own conflict declaration; OCC-guarded on the judge's
    version (PRD §2.9), re-read immediately before the write."""
    payload = create_conflict_payload(
        season_id=season_id,
        entrant_id=entrant_id,
        severity=severity,
        conflict_type=conflict_type,
        expected_judge_version=current_judge_version(judge_id),
    )
    return get_success_data(
        api_client.create_conflict_declaration(
            judge_id, payload, make_judge_headers(judge_id)
        )
    )


# ---------------------------------------------------------------------------
# Dual-mode normalization scenario (PRD §3.6)
# ---------------------------------------------------------------------------

# Ballot matrices shared by the two scoring-mode rounds: identical raw inputs
# must produce different normalized values under Z_SCORE and RAW_RANK.
DUAL_MODE_MATRIX = {
    (0, 0): {"CRAFT": 8, "IMPACT": 4},
    (0, 1): {"CRAFT": 6, "IMPACT": 3},
    (0, 2): {"CRAFT": 9, "IMPACT": 5},
    (1, 0): {"CRAFT": 7, "IMPACT": 3},
    (1, 1): {"CRAFT": 9, "IMPACT": 4},
    (1, 2): {"CRAFT": 5, "IMPACT": 2},
    (2, 0): {"CRAFT": 6, "IMPACT": 4},
    (2, 1): {"CRAFT": 5, "IMPACT": 3},
    (2, 2): {"CRAFT": 7, "IMPACT": 4},
}

# Appeal-cascade ballots: judge-varied rows that still rank E1 > E2 > E3 for
# every judge (rank-1 winner is E1 under RAW_RANK).
APPEAL_MATRIX = {
    (0, 0): {"CRAFT": 10, "IMPACT": 5},
    (0, 1): {"CRAFT": 8, "IMPACT": 4},
    (0, 2): {"CRAFT": 6, "IMPACT": 3},
    (1, 0): {"CRAFT": 9, "IMPACT": 5},
    (1, 1): {"CRAFT": 7, "IMPACT": 4},
    (1, 2): {"CRAFT": 5, "IMPACT": 3},
    (2, 0): {"CRAFT": 10, "IMPACT": 4},
    (2, 1): {"CRAFT": 8, "IMPACT": 3},
    (2, 2): {"CRAFT": 6, "IMPACT": 2},
}


def setup_dual_mode_normalized(code: str = "GALA-DUAL"):
    """Two categories in one season, the same three entrants filing into both,
    a round-1 Z_SCORE round in category Z and a round-1 RAW_RANK round in
    category R, identical ballots (DUAL_MODE_MATRIX), both rounds NORMALIZED.
    Returns a bundle."""
    season = create_season(code)
    cat_z = create_published_category(
        season["id"], code="CAT_Z", name="CAT_Z", finalist_slots=2
    )
    cat_r = create_published_category(
        season["id"], code="CAT_R", name="CAT_R", finalist_slots=2
    )
    season = open_season(season["id"])

    entrants = [register_entrant(f"e{i + 1}@x.com", f"Entrant {i + 1}") for i in range(3)]
    entries_z, entries_r = [], []
    for i, entrant in enumerate(entrants):
        for category, bucket in ((cat_z, entries_z), (cat_r, entries_r)):
            entry = create_draft_entry(
                category["id"], entrant["id"], title=f"Work {i + 1}"
            )
            attach_accepted_material(entry["id"], entrant["id"], ordinal=i + 1)
            submit_entry(entry["id"], entrant["id"])
            pay_invoice(get_only_invoice(entry["id"])["id"], entrant["id"])
            mark_eligible(entry["id"])
            bucket.append(get_entry(entry["id"]))

    season = close_season_submissions(season["id"])

    judges = create_active_judges(3)
    round_z, _, _ = setup_locked_round(
        cat_z["id"], round_index=1, scoring_mode="Z_SCORE",
        window=("2026-09-05T00:00:00Z", "2026-09-07T00:00:00Z"),
        advance_count=2, judges=judges,
    )
    round_r, _, _ = setup_locked_round(
        cat_r["id"], round_index=1, scoring_mode="RAW_RANK",
        window=("2026-09-05T00:00:00Z", "2026-09-07T00:00:00Z"),
        advance_count=2, judges=judges,
    )
    season = begin_judging(season["id"])
    open_round(round_z["id"])
    open_round(round_r["id"])
    score_entries(round_z["id"], entries_z, judges, DUAL_MODE_MATRIX)
    close_round(round_z["id"])
    round_z = normalize_round(round_z["id"])
    score_entries(round_r["id"], entries_r, judges, DUAL_MODE_MATRIX)
    close_round(round_r["id"])
    round_r = normalize_round(round_r["id"])
    return {
        "season": season,
        "cat_z": cat_z,
        "cat_r": cat_r,
        "entrants": entrants,
        "entries_z": entries_z,
        "entries_r": entries_r,
        "judges": judges,
        "round_z": round_z,
        "round_r": round_r,
    }

"""Composite setup helpers.

The harness restarts the API server before every test, so each test begins
against an empty database. These helpers build complete precondition chains
(program -> standards -> items -> committee review -> field testing ->
statistics -> operational approval -> blueprints/forms/slots/assembly ->
equating -> dossiers/publication) using only PRD-declared endpoints.

Access grants (PRD secure-bank section): sensitive operations require scoped
AccessGrants. The helpers issue covering grants on a best-effort basis before
grant-gated operations, so setups succeed whether or not the server enforces
the grant layer for a given operation. Tests that assert the grant gate
itself do so on the negative path (no grant held) which needs no issuance.

Identity threading: item-author checks compare the caller's X-User-ID string
against the item's recorded author_user_id, and segregation-of-duties
compares reviewer user ids across committee kinds, so all helpers thread the
canonical fixture user ids below.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    ADVANCE_INTO_WINDOW,
    ADVANCE_PAST_WINDOW,
    INTENDED_ADMIN_DATE,
    TARGET_SAMPLE_SIZE,
    WINDOW_END,
    WINDOW_START,
)
from .factories import (
    create_access_grant_payload,
    create_blueprint_payload,
    create_committee_payload,
    create_dossier_payload,
    create_equating_link_payload,
    create_form_payload,
    create_item_payload,
    create_program_payload,
    create_response_payload,
    create_session_payload,
    create_slot_payload,
    create_standard_payload,
    create_verdict_payload,
    create_window_payload,
)
from .test_users import (
    make_bias_reviewer_headers,
    make_content_reviewer_headers,
    make_item_writer_headers,
    make_program_director_headers,
    make_psychometrician_headers,
    make_security_officer_headers,
    make_test_assembler_headers,
    make_translation_specialist_headers,
)

# Canonical fixture user identities.
DIRECTOR = "director-1"
WRITER = "writer-1"
PSYCH = "psych-1"
ASSEMBLER = "assembler-1"
OFFICER = "officer-1"
TRANSLATOR = "translator-1"
CONTENT_REVIEWERS = ("cr-1", "cr-2")
BIAS_REVIEWERS = ("br-1", "br-2")

PD_H = make_program_director_headers(DIRECTOR)
WRITER_H = make_item_writer_headers(WRITER)
PSYCH_H = make_psychometrician_headers(PSYCH)
ASSEMBLER_H = make_test_assembler_headers(ASSEMBLER)
OFFICER_H = make_security_officer_headers(OFFICER)
TRANSLATOR_H = make_translation_specialist_headers(TRANSLATOR)

# In-window response timestamp used by default (window bounds below).
RESP_TS = "2026-08-06T12:00:00Z"


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _fmt_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _program_clock_dt(program_id) -> datetime:
    """Read the program's current logical clock position."""
    prog = get_success_data(api_client.get_assessment_program(program_id, PD_H))
    return _parse_iso(prog["current_period_utc"])


# ---------------------------------------------------------------------------
# Tier 0: access-grant helper (best-effort; tolerant of rejection)
# ---------------------------------------------------------------------------

_admin_bootstrapped = set()


def ensure_grant(program_id, grantee_user_id, scope):
    """Issue a covering grant best-effort. The first call per program also
    attempts to self-issue GRANT_ADMIN to the security officer so subsequent
    issuances are covered. All responses are ignored by design: fixtures use
    this only so that grant-gated operations succeed when the grant layer is
    enforced."""
    if program_id not in _admin_bootstrapped:
        _admin_bootstrapped.add(program_id)
        api_client.create_access_grant(
            create_access_grant_payload(program_id, OFFICER, "GRANT_ADMIN"),
            OFFICER_H,
        )
    api_client.create_access_grant(
        create_access_grant_payload(program_id, grantee_user_id, scope),
        OFFICER_H,
    )


def create_grant_strict(program_id, grantee_user_id, scope,
                        valid_from="2026-01-01T00:00:00Z",
                        valid_until="2027-12-31T23:59:59Z"):
    """Issue a grant and require success (used by grant-behavior tests)."""
    ensure_grant(program_id, OFFICER, "GRANT_ADMIN")
    resp = api_client.create_access_grant(
        create_access_grant_payload(
            program_id, grantee_user_id, scope,
            valid_from=valid_from, valid_until=valid_until,
        ),
        OFFICER_H,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: program / standard / item creation
# ---------------------------------------------------------------------------

def create_program(**overrides):
    return get_success_data(
        api_client.create_assessment_program(create_program_payload(**overrides), PD_H)
    )


def create_standard(program_id, depth_of_knowledge=2, **overrides):
    return get_success_data(api_client.create_content_standard(
        create_standard_payload(program_id, depth_of_knowledge=depth_of_knowledge,
                                **overrides),
        PD_H,
    ))


def create_draft_item(program_id, standard_id, author=WRITER, **overrides):
    """Create an item (born DRAFT / UNSECURED). Returns the item."""
    ensure_grant(program_id, author, "ITEM_WRITE")
    return get_success_data(api_client.create_item(
        create_item_payload(program_id, standard_id, **overrides),
        make_item_writer_headers(author),
    ))


def submit_item(item, author=WRITER):
    """Submit a DRAFT item (OCC-guarded; uses the item's current version).
    Returns the submitted (CONTENT_REVIEW) item."""
    ensure_grant(item["program_id"], author, "ITEM_WRITE")
    resp = api_client.submit_item(item["id"], item["version"],
                                  make_item_writer_headers(author))
    return get_success_data(resp)


def read_item(program_id, item_id):
    """GET an item with an ITEM_READ grant covering SECURED items."""
    ensure_grant(program_id, PSYCH, "ITEM_READ")
    return get_success_data(api_client.get_item(item_id, PSYCH_H))


def mark_compromised(program_id, item_id):
    """Mark an EXPOSED OPERATIONAL item COMPROMISED (SecurityOfficer), with a
    covering ITEM_WRITE grant in place for the officer."""
    ensure_grant(program_id, OFFICER, "ITEM_WRITE")
    return api_client.mark_item_compromised(item_id, OFFICER_H)


# ---------------------------------------------------------------------------
# Tier 2: committee review engine
# ---------------------------------------------------------------------------

def create_committee(program_id, committee_kind="CONTENT", quorum_size=2):
    return get_success_data(api_client.create_review_committee(
        create_committee_payload(program_id, committee_kind=committee_kind,
                                 quorum_size=quorum_size),
        PD_H,
    ))


def run_review_session(program_id, item_id, committee_kind="CONTENT",
                       verdicts=("ACCEPT", "ACCEPT"), reviewers=None,
                       quorum_size=2):
    """Create committee+session for one item, open it, cast the given
    verdicts, and close it. Returns the closed session."""
    committee = create_committee(program_id, committee_kind, quorum_size)
    session = get_success_data(api_client.create_review_session(
        create_session_payload(committee["id"], [item_id]), PD_H))
    get_success_data(api_client.open_review_session(session["id"], PD_H))
    if reviewers is None:
        reviewers = (CONTENT_REVIEWERS if committee_kind == "CONTENT"
                     else BIAS_REVIEWERS)
    for reviewer, verdict in zip(reviewers, verdicts):
        headers = (make_content_reviewer_headers(reviewer)
                   if committee_kind == "CONTENT"
                   else make_bias_reviewer_headers(reviewer))
        payload = create_verdict_payload(item_id, verdict)
        if verdict != "ACCEPT":
            payload["rationale"] = "Detailed rationale explaining the decision."
        get_success_data(api_client.submit_verdict(session["id"], payload, headers))
    return get_success_data(api_client.close_review_session(session["id"], PD_H))


def drive_item_to_field_test_eligible(program_id, item, author=WRITER):
    """Submit + content ACCEPT quorum + bias ACCEPT quorum. The item ends in
    FIELD_TEST_ELIGIBLE with security_posture SECURED."""
    submit_item(item, author)
    run_review_session(program_id, item["id"], "CONTENT")
    run_review_session(program_id, item["id"], "BIAS_SENSITIVITY")
    return read_item(program_id, item["id"])


# ---------------------------------------------------------------------------
# Tier 3: field testing and statistics engine
# ---------------------------------------------------------------------------

def create_window(program_id, target_sample_size=TARGET_SAMPLE_SIZE,
                  start_utc=WINDOW_START, end_utc=WINDOW_END, **overrides):
    return get_success_data(api_client.create_field_test_window(
        create_window_payload(program_id, target_sample_size=target_sample_size,
                              start_utc=start_utc, end_utc=end_utc, **overrides),
        PD_H,
    ))


def open_window(program_id, window_id):
    """Advance the program clock into the window's bounds and open it."""
    get_success_data(api_client.advance_clock(program_id, ADVANCE_INTO_WINDOW, PD_H))
    return get_success_data(api_client.open_field_test_window(window_id, PD_H))


def ingest_response(window_id, item_id, student_anon_id, raw_score,
                    response_timestamp=RESP_TS, attempt_duration_seconds=60):
    return get_success_data(api_client.ingest_item_response(
        window_id,
        create_response_payload(
            item_id, student_anon_id, raw_score,
            response_timestamp=response_timestamp,
            attempt_duration_seconds=attempt_duration_seconds,
        ),
        PSYCH_H,
    ))


def ingest_score_matrix(window_id, item_scores, response_timestamp=RESP_TS):
    """Ingest a score matrix: {item_id: [score_per_student]}. Each item's
    list is ingested in full, with student s_i the i-th respondent for that
    item; lists may be ragged (a shorter list simply means fewer respondents
    for that item), so each item's difficulty is mean(scores) and
    discrimination correlates across the items each student answered."""
    for item_id, scores in item_scores.items():
        for i, score in enumerate(scores):
            ingest_response(window_id, item_id, f"s{i}", score,
                            response_timestamp=response_timestamp)


def close_window(program_id, window_id):
    """Advance the clock past end_utc and close the window (computes stats)."""
    get_success_data(api_client.advance_clock(program_id, ADVANCE_PAST_WINDOW, PD_H))
    return get_success_data(api_client.close_field_test_window(window_id, PD_H))


def list_statistics(program_id, item_id=None, window_id=None, stats_kind=None):
    """List ItemStatistic rows with a STATS_READ grant held by the reader."""
    ensure_grant(program_id, PSYCH, "STATS_READ")
    params = {}
    if item_id is not None:
        params["item_id"] = item_id
    if window_id is not None:
        params["window_id"] = window_id
    if stats_kind is not None:
        params["stats_kind"] = stats_kind
    data, _meta = validate_paginated(api_client.list_item_statistics(PSYCH_H, params=params))
    return data


def field_test_and_close(program_id, item_scores, target_sample_size=TARGET_SAMPLE_SIZE):
    """Open a window, ingest the score matrix, close the window. Returns the
    closed window. item_scores maps item_id -> per-student score list.

    Window bounds are derived from the program's CURRENT logical clock: the
    clock only moves forward, so fixed bounds would lie behind it (and the
    window could never open) on any program that has already completed a
    field-test cycle. Responses are timestamped one hour after the window's
    start so they fall inside the closed [start_utc, end_utc] interval the
    FINAL statistics computation filters on."""
    clock = _program_clock_dt(program_id)
    window = create_window(
        program_id,
        target_sample_size=target_sample_size,
        start_utc=_fmt_iso(clock),
        end_utc=_fmt_iso(clock + timedelta(days=6)),
    )
    open_window(program_id, window["id"])
    ensure_grant(program_id, PSYCH, "STATS_READ")
    ingest_score_matrix(window["id"], item_scores,
                        response_timestamp=_fmt_iso(clock + timedelta(hours=1)))
    return close_window(program_id, window["id"]), window


def make_operational_items(program_id, standard_id, ones_list, exposure_cap=None,
                           author=WRITER):
    """Create len(ones_list) items plus one filler, drive all to
    FIELD_TEST_ELIGIBLE, field-test them in one shared window with nested
    score patterns (item j is scored 1 by the first ones_list[j] of 50
    students; the filler mirrors the median pattern so discrimination is
    well-defined and every FINAL pass_flag is PASS), then approve each item
    to OPERATIONAL. Returns the list of fresh OPERATIONAL item dicts."""
    n_students = TARGET_SAMPLE_SIZE
    items = []
    for _ in ones_list:
        item = create_draft_item(program_id, standard_id, author=author,
                                 exposure_cap=exposure_cap or 3)
        items.append(item)
    filler = create_draft_item(program_id, standard_id, author=author)
    for item in items + [filler]:
        drive_item_to_field_test_eligible(program_id, item, author=author)

    median_ones = sorted(ones_list)[len(ones_list) // 2]
    scores = {}
    for item, ones in zip(items, ones_list):
        scores[item["id"]] = [1 if i < ones else 0 for i in range(n_students)]
    scores[filler["id"]] = [1 if i < median_ones else 0 for i in range(n_students)]

    field_test_and_close(program_id, scores, target_sample_size=n_students)

    operational = []
    for item in items:
        ensure_grant(program_id, PSYCH, "ITEM_WRITE")
        approved = get_success_data(
            api_client.approve_operational_item(item["id"], PSYCH_H))
        operational.append(approved)
    return operational


# ---------------------------------------------------------------------------
# Tier 4: blueprints, forms, slots, assembly
# ---------------------------------------------------------------------------

def create_locked_blueprint(program_id, item_count, dok_min=1, dok_max=100):
    payload = create_blueprint_payload(program_id, item_count=item_count)
    payload["sections"] = [{"strand": "S", "item_count": item_count,
                            "dok_min": dok_min, "dok_max": dok_max}]
    bp = get_success_data(api_client.create_test_blueprint(payload, ASSEMBLER_H))
    get_success_data(api_client.lock_test_blueprint(bp["id"], PD_H))
    return get_success_data(api_client.get_test_blueprint(bp["id"], ASSEMBLER_H))


def create_form(program_id, blueprint_id, admin_date=INTENDED_ADMIN_DATE):
    return get_success_data(api_client.create_test_form(
        create_form_payload(blueprint_id, intended_admin_date=admin_date),
        ASSEMBLER_H,
    ))


def add_slot(program_id, form_id, item_id, section_index=0, position_in_section=1,
             is_anchor=False):
    ensure_grant(program_id, ASSEMBLER, "FORM_ASSEMBLE")
    return get_success_data(api_client.add_form_item_slot(
        form_id,
        create_slot_payload(item_id, section_index, position_in_section, is_anchor),
        ASSEMBLER_H,
    ))


def assemble_form(form_id):
    """Assemble a form, threading its current version for the OCC guard."""
    form = get_success_data(api_client.get_test_form(form_id, ASSEMBLER_H))
    return get_success_data(
        api_client.assemble_test_form(form_id, form["version"], ASSEMBLER_H))


def build_assembled_form(program_id, items, anchor_ids=(),
                         admin_date=INTENDED_ADMIN_DATE, dok_min=1, dok_max=100):
    """Blueprint (LOCKED) + form + one slot per item + assemble.
    Returns the ASSEMBLED form."""
    bp = create_locked_blueprint(program_id, len(items), dok_min=dok_min,
                                 dok_max=dok_max)
    form = create_form(program_id, bp["id"], admin_date=admin_date)
    for pos, item in enumerate(items, start=1):
        add_slot(program_id, form["id"], item["id"], position_in_section=pos,
                 is_anchor=(item["id"] in set(anchor_ids)))
    return assemble_form(form["id"])


def list_slots(form_id):
    data, _meta = validate_paginated(
        api_client.list_form_item_slots(ASSEMBLER_H, params={"form_id": form_id}))
    return data


# ---------------------------------------------------------------------------
# Tier 5: equating, dossiers, publication
# ---------------------------------------------------------------------------

def create_equated_form(program_id, standard_id, extra_target_items=(),
                        anchor_ones=(25, 30, 35)):
    """Build 3 anchor items (distinct FINAL p_values 0.5/0.6/0.7), a source
    form and a target form both carrying them as anchor slots, then create
    the equating link so the target form advances to EQUATED.
    Returns (link, source_form, target_form, anchors, extras)."""
    operational = make_operational_items(
        program_id, standard_id,
        list(anchor_ones) + [30] * len(extra_target_items),
        exposure_cap=10,
    )
    anchors = operational[:len(anchor_ones)]
    extras = operational[len(anchor_ones):]
    anchor_ids = [a["id"] for a in anchors]

    source_form = build_assembled_form(program_id, anchors, anchor_ids=anchor_ids)
    target_form = build_assembled_form(program_id, anchors + extras,
                                       anchor_ids=anchor_ids)

    ensure_grant(program_id, PSYCH, "ITEM_READ")
    link = get_success_data(api_client.create_equating_link(
        create_equating_link_payload(program_id, source_form["id"],
                                     target_form["id"], anchor_ids),
        PSYCH_H,
    ))
    target_form = get_success_data(api_client.get_test_form(target_form["id"], ASSEMBLER_H))
    return link, source_form, target_form, anchors, extras


def create_dossier(program_id, form_id, **overrides):
    return get_success_data(api_client.create_validity_dossier(
        create_dossier_payload(program_id, form_id, **overrides), PSYCH_H))


def publish_dossier(dossier_id):
    return get_success_data(api_client.publish_validity_dossier(dossier_id, PSYCH_H))


def publish_form(form_id):
    return get_success_data(api_client.publish_test_form(form_id, PD_H))


def setup_published_form(program_id, standard_id, admin_date=INTENDED_ADMIN_DATE):
    """Full chain: anchors + target form EQUATED + published dossier +
    publish. Returns the PUBLISHED form."""
    link, source_form, target_form, anchors, _extras = create_equated_form(
        program_id, standard_id)
    dossier = create_dossier(program_id, target_form["id"])
    publish_dossier(dossier["id"])
    return publish_form(target_form["id"])

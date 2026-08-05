"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient) internally so setup failures surface as clear
"setup failed" errors rather than confusing assertion failures. Every helper builds
its preconditions from scratch — the server database is empty before each test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_jurisdiction_payload, create_filer_payload, create_filing_period_payload,
    create_statement_payload, create_gift_report_payload, create_recusal_payload,
    create_complaint_payload, create_training_record_payload,
)
from .test_users import TEST_USERS, make_filer_headers, make_investigator_headers


REGISTRAR = TEST_USERS["registrar_headers"]
OFFICER = TEST_USERS["ethics_officer_headers"]


# ─── Primitive builders ──────────────────────────────────────────────────────

def register_jurisdiction(**overrides) -> dict:
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), REGISTRAR))


def register_filer(jurisdiction_id, filer_category="APPOINTED", **overrides) -> dict:
    return get_success_data(api_client.create_filer(
        create_filer_payload(jurisdiction_id, filer_category=filer_category, **overrides),
        REGISTRAR))


def set_clock(iso: str) -> None:
    api_client.set_clock({"to_iso8601": iso}, REGISTRAR)


def make_training_current(filer_id: str) -> dict:
    """Enroll + complete an ethics course so training_status becomes CURRENT.

    Completion stamps completed_at/expires_at from the CURRENT logical clock, so
    set the clock BEFORE calling this when a specific completion instant matters.
    """
    fh = make_filer_headers(filer_id)
    tr = get_success_data(api_client.create_training_record(
        create_training_record_payload(filer_id), fh))
    return get_success_data(api_client.complete_training_record(tr["id"], {}, fh))


def open_filing_period(jurisdiction_id, **overrides) -> dict:
    return get_success_data(api_client.create_filing_period(
        create_filing_period_payload(jurisdiction_id, **overrides), REGISTRAR))


def create_draft_statement(filer_id, filing_period_id, **overrides) -> dict:
    return get_success_data(api_client.create_statement(
        create_statement_payload(filer_id, filing_period_id, **overrides),
        make_filer_headers(filer_id)))


def report_gift(filer_id, **overrides):
    """Raw POST /gift-reports response (caller decides success/error)."""
    return api_client.create_gift_report(
        create_gift_report_payload(filer_id, **overrides), make_filer_headers(filer_id))


def declare_recusal(filer_id, **overrides):
    """Raw POST /recusals response."""
    return api_client.create_recusal(
        create_recusal_payload(filer_id, **overrides), make_filer_headers(filer_id))


def get_filer(filer_id) -> dict:
    return get_success_data(api_client.get_filer(filer_id, REGISTRAR))


def get_statement(statement_id) -> dict:
    return get_success_data(api_client.get_statement(statement_id, REGISTRAR))


def get_penalty(penalty_id) -> dict:
    return get_success_data(api_client.get_penalty(penalty_id, REGISTRAR))


def latest_penalty_for(filer_id, **params) -> dict:
    """Return the first penalty row for a filer (optionally filtered)."""
    p = dict(params)
    p["filer_id"] = filer_id
    res = api_client.list_penalties(REGISTRAR, params=p)
    data, _ = _paginated(res)
    assert data, f"expected at least one penalty for filer {filer_id}"
    return data[0]


def _paginated(res):
    body = res.json()
    return body["data"], body["meta"]


# ─── Tier 2/3: Statement submission scenarios ───────────────────────────────

def setup_submitted_statement(category="ELECTED", clock=None,
                              due_at="2026-04-15T00:00:00Z",
                              coverage_start="2025-01-01T00:00:00Z",
                              coverage_end="2025-12-31T00:00:00Z",
                              jur_overrides=None):
    """Jurisdiction + CURRENT-training filer + ANNUAL period + submitted statement.

    Sets the clock (if given) BEFORE completing training, so training is CURRENT and
    lateness is measured against the clock at submit time. Returns a dict with the
    jurisdiction, filer, period and the submitted statement.
    """
    jur = register_jurisdiction(**(jur_overrides or {}))
    filer = register_filer(jur["id"], filer_category=category)
    if clock:
        set_clock(clock)
    make_training_current(filer["id"])
    period = open_filing_period(jur["id"], due_at=due_at,
                                coverage_start=coverage_start, coverage_end=coverage_end)
    stmt = create_draft_statement(filer["id"], period["id"])
    stmt = get_success_data(
        api_client.submit_statement(stmt["id"], {}, make_filer_headers(filer["id"])))
    return {"jurisdiction": jur, "filer": filer, "period": period, "statement": stmt}


def setup_accepted_late_statement(category="ELECTED", clock="2026-05-25T00:00:00Z",
                                  due_at="2026-04-15T00:00:00Z", jur_overrides=None):
    """Submit a late statement then accept it, finalizing the LATE_FILING penalty.

    Returns dict with jurisdiction, filer, period, statement, penalty (ASSESSED).
    """
    ctx = setup_submitted_statement(category=category, clock=clock, due_at=due_at,
                                    jur_overrides=jur_overrides)
    stmt = ctx["statement"]
    ctx["statement"] = get_success_data(
        api_client.accept_statement(stmt["id"], {}, OFFICER))
    ctx["penalty"] = latest_penalty_for(ctx["filer"]["id"], statement_id=stmt["id"])
    return ctx


def setup_returned_statement(category="SENIOR_STAFF", clock="2026-05-01T00:00:00Z",
                             due_at="2026-06-01T00:00:00Z"):
    """On-time submitted statement that an EthicsOfficer has RETURNED for correction.

    Returns dict with filer, period and the RETURNED_FOR_CORRECTION statement
    (correction_round == 1).
    """
    ctx = setup_submitted_statement(category=category, clock=clock, due_at=due_at)
    stmt = ctx["statement"]
    ctx["statement"] = get_success_data(
        api_client.return_statement(stmt["id"], {"correction_note": "fix schedule C"}, OFFICER))
    return ctx


# ─── Delinquency / withhold cascade ─────────────────────────────────────────

def setup_delinquent_filer_with_withheld_statement():
    """Full depth-3 cascade fixture.

    An ELECTED filer files an on-time CY2024 statement, it is accepted and PUBLISHED.
    Later a CY2025 statement is filed 40 days late; accepting it assesses a 45000
    penalty which flips the filer to DELINQUENT and withholds the CY2024 statement.
    Returns dict: jurisdiction, filer, stmtA (withheld), stmtB, penaltyB (ASSESSED).
    """
    jur = register_jurisdiction(penalty_base_fee_cents=5000, penalty_daily_rate_cents=250,
                                penalty_cap_cents=50000)
    filer = register_filer(jur["id"], filer_category="ELECTED")
    set_clock("2026-01-10T00:00:00Z")
    make_training_current(filer["id"])

    periodA = open_filing_period(jur["id"], statement_type="ANNUAL",
                                 coverage_start="2024-01-01T00:00:00Z",
                                 coverage_end="2024-12-31T00:00:00Z",
                                 due_at="2026-01-15T00:00:00Z", label="CY2024")
    stmtA = create_draft_statement(filer["id"], periodA["id"])
    fh = make_filer_headers(filer["id"])
    get_success_data(api_client.submit_statement(stmtA["id"], {}, fh))
    get_success_data(api_client.accept_statement(stmtA["id"], {}, OFFICER))
    vA = get_statement(stmtA["id"])["version"]
    get_success_data(api_client.publish_statement(
        stmtA["id"], {"expected_statement_version": vA, "redaction_level": "REDACTED"}, REGISTRAR))

    periodB = open_filing_period(jur["id"], statement_type="ANNUAL",
                                 coverage_start="2025-01-01T00:00:00Z",
                                 coverage_end="2025-12-31T00:00:00Z",
                                 due_at="2026-04-15T00:00:00Z", label="CY2025")
    set_clock("2026-05-25T00:00:00Z")
    stmtB = create_draft_statement(filer["id"], periodB["id"])
    get_success_data(api_client.submit_statement(stmtB["id"], {}, fh))
    stmtB = get_success_data(api_client.accept_statement(stmtB["id"], {}, OFFICER))
    penB = latest_penalty_for(filer["id"], statement_id=stmtB["id"])
    return {"jurisdiction": jur, "filer": filer, "stmtA": get_statement(stmtA["id"]),
            "stmtB": stmtB, "penaltyB": penB}


# ─── Gift-report scenarios ──────────────────────────────────────────────────

def setup_trained_filer(category="APPOINTED", jur_overrides=None, clock=None):
    """Jurisdiction + filer whose training_status is CURRENT. Returns (jur, filer)."""
    jur = register_jurisdiction(**(jur_overrides or {}))
    filer = register_filer(jur["id"], filer_category=category)
    if clock:
        set_clock(clock)
    make_training_current(filer["id"])
    return jur, filer


def setup_untrained_filer(jur_overrides=None):
    """Jurisdiction + filer with NO completed training (training_status NONE)."""
    jur = register_jurisdiction(**(jur_overrides or {}))
    filer = register_filer(jur["id"], filer_category="APPOINTED")
    return jur, filer


# ─── Recusal scenarios ──────────────────────────────────────────────────────

def setup_filer_with_recusal(matter_id="M1", effective_start="2026-06-01T00:00:00Z",
                             effective_end="2026-06-10T00:00:00Z"):
    """Filer with one DECLARED recusal on the given matter/interval. Returns (filer, recusal)."""
    jur = register_jurisdiction()
    filer = register_filer(jur["id"], filer_category="ELECTED")
    rec = get_success_data(declare_recusal(
        filer["id"], matter_id=matter_id,
        effective_start=effective_start, effective_end=effective_end, reason="family interest"))
    return filer, rec


# ─── Complaint / investigation scenarios ────────────────────────────────────

def setup_filed_complaint(jur_overrides=None, statement_id=None):
    """A FILED complaint against a filer. Returns dict: jurisdiction, filer, complaint."""
    jur = register_jurisdiction(**(jur_overrides or {}))
    filer = register_filer(jur["id"], filer_category="ELECTED")
    payload = create_complaint_payload(filer["id"], allegation="conflict", complainant_ref="cx-2")
    if statement_id:
        payload["statement_id"] = statement_id
    complaint = get_success_data(api_client.create_complaint(payload, OFFICER))
    return {"jurisdiction": jur, "filer": filer, "complaint": complaint}


def setup_screened_complaint(jur_overrides=None, statement_id=None):
    """A SCREENED complaint. Returns dict: jurisdiction, filer, complaint."""
    ctx = setup_filed_complaint(jur_overrides=jur_overrides, statement_id=statement_id)
    ctx["complaint"] = get_success_data(
        api_client.screen_complaint(ctx["complaint"]["id"], {"decision": "SCREENED"}, OFFICER))
    return ctx


def setup_open_investigation(investigator_id="inv-1", jur_overrides=None, statement_id=None):
    """SCREENED complaint with an OPEN investigation opened by `investigator_id`.

    Returns dict: jurisdiction, filer, complaint, investigation.
    """
    ctx = setup_screened_complaint(jur_overrides=jur_overrides, statement_id=statement_id)
    inv = get_success_data(api_client.open_investigation(
        ctx["complaint"]["id"], {"scope_note": "review"}, make_investigator_headers(investigator_id)))
    ctx["investigation"] = inv
    return ctx


def setup_accepted_statement_under_investigation(investigator_id="inv-1"):
    """ELECTED filer with an on-time ACCEPTED statement, a complaint about that statement
    (SCREENED), and an OPEN investigation opened by `investigator_id`.

    Returns dict: jurisdiction, filer, statement, complaint, investigation.
    """
    jur = register_jurisdiction(penalty_cap_cents=50000)
    filer = register_filer(jur["id"], filer_category="ELECTED")
    set_clock("2026-01-10T00:00:00Z")
    make_training_current(filer["id"])
    period = open_filing_period(jur["id"], statement_type="ANNUAL",
                                coverage_start="2025-01-01T00:00:00Z",
                                coverage_end="2025-12-31T00:00:00Z",
                                due_at="2026-01-15T00:00:00Z")
    stmt = create_draft_statement(filer["id"], period["id"])
    fh = make_filer_headers(filer["id"])
    get_success_data(api_client.submit_statement(stmt["id"], {}, fh))
    stmt = get_success_data(api_client.accept_statement(stmt["id"], {}, OFFICER))

    complaint = get_success_data(api_client.create_complaint(
        create_complaint_payload(filer["id"], allegation="omitted asset",
                                 statement_id=stmt["id"], complainant_ref="cx-1"), OFFICER))
    complaint = get_success_data(api_client.screen_complaint(
        complaint["id"], {"decision": "SCREENED"}, OFFICER))
    inv = get_success_data(api_client.open_investigation(
        complaint["id"], {"scope_note": "review"}, make_investigator_headers(investigator_id)))
    return {"jurisdiction": jur, "filer": filer, "statement": stmt,
            "complaint": complaint, "investigation": inv}


# ─── Publication (OCC) scenario ─────────────────────────────────────────────

def setup_published_statement(category="SENIOR_STAFF"):
    """An ACCEPTED statement published once (version already bumped by publish).

    Returns dict: filer, statement (published), pre_publish_version (now stale).
    """
    ctx = setup_submitted_statement(category=category, clock="2026-05-01T00:00:00Z",
                                    due_at="2026-06-01T00:00:00Z")
    stmt = get_success_data(api_client.accept_statement(ctx["statement"]["id"], {}, OFFICER))
    pre = get_statement(stmt["id"])["version"]
    get_success_data(api_client.publish_statement(
        stmt["id"], {"expected_statement_version": pre}, REGISTRAR))
    return {"filer": ctx["filer"], "statement": get_statement(stmt["id"]),
            "pre_publish_version": pre}

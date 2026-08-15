"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: the Writer role is entity-backed — split-line confirm and
reject calls on WRITER lines always use make_writer_headers(line.writer_id),
never the shared TEST_USERS constant. Opaque roles use the shared constants.

OCC threading: creating a SplitSet requires the Work's current version, and
creating an Advance requires the Writer's current version. Both creates bump
the parent's version by 1, so these helpers re-read the parent immediately
before each guarded create.
"""
import itertools

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    create_advance_payload,
    create_distribution_run_payload,
    create_licensee_audit_payload,
    create_licensee_payload,
    create_royalty_statement_payload,
    create_society_payload,
    create_society_registration_payload,
    create_split_set_payload,
    create_sub_publisher_payload,
    create_sub_publishing_agreement_payload,
    create_termination_claim_payload,
    create_work_payload,
    create_writer_payload,
    publisher_split_line,
    statement_line_payload,
    writer_split_line,
)
from .test_users import TEST_USERS, make_writer_headers

ADMIN = TEST_USERS["publisher_admin_headers"]
COPYRIGHT = TEST_USERS["copyright_specialist_headers"]
ANALYST = TEST_USERS["royalty_analyst_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

DEFAULT_GRANT_DATE = "1990-06-15T00:00:00Z"
Q1_2026 = ("2026-01-01T00:00:00Z", "2026-03-31T23:59:59Z")
Q2_2026 = ("2026-04-01T00:00:00Z", "2026-06-30T23:59:59Z")

_ipi_counter = itertools.count(100_000_001)


def _next_ipi() -> str:
    """Unique 11-character IPI/CAE identifier per call."""
    return str(next(_ipi_counter))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Set the logical clock. Returns the clock payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_writer(legal_name="Test Writer", pro_affiliation="ASCAP",
                  ipi_number=None):
    """Create a writer (born ACTIVE, version 1, zero balances)."""
    payload = create_writer_payload(
        legal_name=legal_name, pro_affiliation=pro_affiliation,
        ipi_number=ipi_number or _next_ipi())
    return get_success_data(api_client.create_writer(payload, ADMIN))


def get_writer(writer_id):
    return get_success_data(api_client.get_writer(writer_id, ADMIN))


def suspend_writer(writer_id):
    return get_success_data(api_client.suspend_writer(writer_id, ADMIN))


def reactivate_writer(writer_id):
    return get_success_data(api_client.reactivate_writer(writer_id, ADMIN))


def create_work(title="Test Song", grant_date=DEFAULT_GRANT_DATE,
                parent_work_id=None, alternate_titles=None):
    """Create a work (UNREGISTERED / UNFILED, version 1)."""
    payload = create_work_payload(title=title, grant_date=grant_date)
    if parent_work_id is not None:
        payload["parent_work_id"] = parent_work_id
    if alternate_titles is not None:
        payload["alternate_titles"] = alternate_titles
    return get_success_data(api_client.create_work(payload, ADMIN))


def get_work(work_id):
    return get_success_data(api_client.get_work(work_id, ADMIN))


def create_society(name="ASCAP", code="ASCAP", society_type="PRO",
                   territory_code="US"):
    payload = create_society_payload(name=name, code=code,
                                     society_type=society_type,
                                     territory_code=territory_code)
    return get_success_data(api_client.create_society(payload, ADMIN))


def create_licensee(name="StreamCo", licensee_type="STREAMING"):
    payload = create_licensee_payload(name=name, licensee_type=licensee_type)
    return get_success_data(api_client.create_licensee(payload, ADMIN))


def create_sub_publisher(name="DE Sub", home_territory_code="DE"):
    payload = create_sub_publisher_payload(
        name=name, home_territory_code=home_territory_code)
    return get_success_data(api_client.create_sub_publisher(payload, ADMIN))


def create_sub_publishing_agreement(sub_publisher_id, territory_codes=None,
                                    income_types=None, retention_bp=2000,
                                    effective_from="2026-01-01T00:00:00Z",
                                    effective_to="2027-01-01T00:00:00Z"):
    payload = create_sub_publishing_agreement_payload(
        sub_publisher_id,
        territory_codes=territory_codes or ["DE"],
        income_types=income_types or ["PERFORMANCE"],
        retention_bp=retention_bp,
        effective_from=effective_from,
        effective_to=effective_to)
    return get_success_data(
        api_client.create_sub_publishing_agreement(payload, ADMIN))


def activate_sub_publishing_agreement(agreement_id):
    return get_success_data(
        api_client.activate_sub_publishing_agreement(agreement_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: split negotiation helpers
# ---------------------------------------------------------------------------

def create_split_set(work_id, writer_shares, publisher_name="OurPub",
                     publisher_share_bp=10000):
    """Create a DRAFT split set, threading the work's CURRENT version (OCC).

    writer_shares: list of (writer_id, share_bp) tuples, in array order.
    Returns the created split set.
    """
    work = get_work(work_id)
    lines = [writer_split_line(wid, bp) for wid, bp in writer_shares]
    lines.append(publisher_split_line(publisher_name, publisher_share_bp))
    payload = create_split_set_payload(work_id, work["version"], lines)
    return get_success_data(api_client.create_split_set(payload, ADMIN))


def list_split_lines(split_set_id):
    """Split lines of a set in array order (created_at is strictly increasing
    in array order within one create/revise request)."""
    data, _meta = validate_paginated(
        api_client.list_split_lines(ADMIN, params={"split_set_id": split_set_id}))
    return data


def submit_split_set(split_set_id):
    return get_success_data(api_client.submit_split_set(split_set_id, ADMIN))


def confirm_all_split_lines(split_set_id):
    """Confirm every line of a PENDING_CONFIRMATIONS set with the correct
    caller identity: WRITER lines by their owning writer, PUBLISHER lines by
    the PublisherAdmin. Returns the final line list."""
    lines = list_split_lines(split_set_id)
    for line in lines:
        if line["participant_type"] == "WRITER":
            headers = make_writer_headers(line["writer_id"])
        else:
            headers = ADMIN
        get_success_data(api_client.confirm_split_line(line["id"], headers))
    return list_split_lines(split_set_id)


def setup_confirmed_split_set(work_id, writer_shares, publisher_name="OurPub"):
    """Create + submit + fully confirm a split set. Returns (split_set, lines)."""
    split_set = create_split_set(work_id, writer_shares, publisher_name)
    submit_split_set(split_set["id"])
    lines = confirm_all_split_lines(split_set["id"])
    confirmed = get_success_data(api_client.get_split_set(split_set["id"], ADMIN))
    assert confirmed["status"] == "CONFIRMED", (
        f"Setup failed: split set not CONFIRMED, got {confirmed['status']}")
    return confirmed, lines


# ---------------------------------------------------------------------------
# Tier 3: society registration
# ---------------------------------------------------------------------------

def register_work_via_pro_society(work_id, iswc="T-900000001-1",
                                  society_name="ASCAP", society_code="ASCAP",
                                  society_work_number="880000001"):
    """Create a PRO society + registration and walk it to REGISTERED, which
    also lifts the work's registration_status to REGISTERED and assigns the
    work's iswc. Requires the work to already have a CONFIRMED split set.
    Returns the registration."""
    society = create_society(name=society_name, code=society_code,
                             society_type="PRO")
    registration = get_success_data(api_client.create_society_registration(
        create_society_registration_payload(work_id, society["id"]), COPYRIGHT))
    get_success_data(
        api_client.submit_society_registration(registration["id"], COPYRIGHT))
    get_success_data(api_client.acknowledge_society_registration(
        registration["id"], society_work_number, COPYRIGHT))
    registration = get_success_data(api_client.register_society_registration(
        registration["id"], COPYRIGHT, iswc=iswc))
    assert registration["status"] == "REGISTERED", (
        f"Setup failed: registration not REGISTERED, got {registration['status']}")
    return registration


def setup_registered_work(writer_specs=None, title="Test Song",
                          grant_date=DEFAULT_GRANT_DATE,
                          iswc="T-900000001-1", society_code="ASCAP"):
    """Full catalog unit: writers + work + CONFIRMED split set + REGISTERED
    registration via a PRO society.

    writer_specs: list of (legal_name, share_bp) tuples; defaults to a single
    10000bp writer. Returns a dict with work (refreshed), writers, split_set,
    lines, registration.
    """
    if writer_specs is None:
        writer_specs = [("Writer One", 10000)]
    writers = [create_writer(legal_name=name) for name, _bp in writer_specs]
    work = create_work(title=title, grant_date=grant_date)
    split_set, lines = setup_confirmed_split_set(
        work["id"], [(w["id"], bp) for w, (_n, bp) in zip(writers, writer_specs)])
    registration = register_work_via_pro_society(
        work["id"], iswc=iswc, society_code=society_code)
    work = get_work(work["id"])
    assert work["registration_status"] == "REGISTERED", (
        "Setup failed: work not REGISTERED after registration chain")
    return {
        "work": work,
        "writers": writers,
        "split_set": split_set,
        "lines": lines,
        "registration": registration,
    }


# ---------------------------------------------------------------------------
# Tier 4: royalty statement pipeline
# ---------------------------------------------------------------------------

def create_statement(source_id, lines, gross_amount_cents,
                     source_type="LICENSEE", income_type="PERFORMANCE",
                     territory_code="US", period=Q1_2026,
                     amends_statement_id=None):
    """Create a statement (RECEIVED) with inline lines."""
    payload = create_royalty_statement_payload(
        source_type, source_id, income_type, territory_code,
        period[0], period[1], gross_amount_cents, lines=lines)
    if amends_statement_id is not None:
        payload["amends_statement_id"] = amends_statement_id
    return get_success_data(api_client.create_royalty_statement(payload, ANALYST))


def statement_line(line_number, title, gross_cents, work_code=None,
                   iswc=None):
    return statement_line_payload(line_number, title, gross_cents,
                                  reported_iswc=iswc,
                                  reported_work_code=work_code)


def list_statement_lines(statement_id):
    data, _meta = validate_paginated(
        api_client.list_statement_lines(ANALYST,
                                        params={"statement_id": statement_id}))
    return data


def run_statement_pipeline(statement_id, through="FINALIZED"):
    """Walk a statement through match -> allocate -> finalize, stopping at the
    named stage. `through` is one of MATCHING_REVIEW, ALLOCATED, FINALIZED.

    The statement may enter this helper at any point along the lifecycle
    (PRD §3.5: RECEIVED -> MATCHING_REVIEW -> ALLOCATED -> FINALIZED): steps
    the statement has already passed are skipped, so a statement the test has
    already matched manually can still be walked to ALLOCATED/FINALIZED."""
    assert through in ("MATCHING_REVIEW", "ALLOCATED", "FINALIZED"), (
        f"unknown pipeline target {through}")
    statement = get_success_data(
        api_client.get_royalty_statement(statement_id, ANALYST))
    if statement["status"] == "RECEIVED":
        statement = get_success_data(
            api_client.match_royalty_statement(statement_id, ANALYST))
        assert statement["status"] == "MATCHING_REVIEW", (
            f"Setup failed: match left statement {statement['status']}")
    if through == "MATCHING_REVIEW":
        return statement
    if statement["status"] == "MATCHING_REVIEW":
        statement = get_success_data(
            api_client.allocate_royalty_statement(statement_id, ANALYST))
        assert statement["status"] == "ALLOCATED", (
            f"Setup failed: allocate left statement {statement['status']}")
    if through == "ALLOCATED":
        return statement
    if statement["status"] == "ALLOCATED":
        statement = get_success_data(
            api_client.finalize_royalty_statement(statement_id, ANALYST))
        assert statement["status"] == "FINALIZED", (
            f"Setup failed: finalize left statement {statement['status']}")
    return statement


def list_allocation_lines(statement_id=None, writer_id=None, split_line_id=None,
                          statement_line_id=None):
    params = {}
    if statement_id is not None:
        params["statement_id"] = statement_id
    if writer_id is not None:
        params["writer_id"] = writer_id
    if split_line_id is not None:
        params["split_line_id"] = split_line_id
    if statement_line_id is not None:
        params["statement_line_id"] = statement_line_id
    data, _meta = validate_paginated(
        api_client.list_allocation_lines(ANALYST, params=params))
    return data


# ---------------------------------------------------------------------------
# Tier 5: advances and the recoupment chain
# ---------------------------------------------------------------------------

def create_advance(writer_id, amount_cents, recoup_rate_bp=None,
                   agreement_ref="ADV-1"):
    """Create a DRAFT advance, threading the writer's CURRENT version (OCC)."""
    writer = get_writer(writer_id)
    payload = create_advance_payload(writer_id, writer["version"], amount_cents,
                                     agreement_ref=agreement_ref)
    if recoup_rate_bp is not None:
        payload["recoup_rate_bp"] = recoup_rate_bp
    return get_success_data(api_client.create_advance(payload, ADMIN))


def create_paid_advance(writer_id, amount_cents, recoup_rate_bp=None,
                        agreement_ref="ADV-1"):
    """Create + approve + pay an advance. Returns the PAID advance."""
    advance = create_advance(writer_id, amount_cents,
                             recoup_rate_bp=recoup_rate_bp,
                             agreement_ref=agreement_ref)
    get_success_data(api_client.approve_advance(advance["id"], FINANCE))
    advance = get_success_data(api_client.pay_advance(advance["id"], FINANCE))
    assert advance["status"] == "PAID", (
        f"Setup failed: advance not PAID, got {advance['status']}")
    return advance


def setup_finalized_statement(writer_specs=None, line_grosses=(2000,),
                              title="Test Song", advances=(),
                              period=Q1_2026, iswc="T-900000001-1"):
    """Full royalty chain: registered work with one writer (or more), one
    licensee statement whose lines all carry the work_code hint, walked to
    FINALIZED.

    line_grosses: tuple of gross cents per line, all matched to the work.
    advances: tuple of (amount_cents, recoup_rate_bp) paid to the FIRST writer
    before the statement is finalized.
    Returns a dict with work, writers, licensee, statement, allocations.
    """
    ctx = setup_registered_work(writer_specs=writer_specs, title=title,
                                iswc=iswc)
    paid_advances = [
        create_paid_advance(ctx["writers"][0]["id"], amount,
                            recoup_rate_bp=rate,
                            agreement_ref=f"ADV-{idx}")
        for idx, (amount, rate) in enumerate(advances)
    ]
    licensee = create_licensee()
    lines = [
        statement_line(i + 1, f"{title} #{i + 1}", gross,
                       work_code=ctx["work"]["work_code"])
        for i, gross in enumerate(line_grosses)
    ]
    statement = create_statement(licensee["id"], lines, sum(line_grosses),
                                 period=period)
    statement = run_statement_pipeline(statement["id"], through="FINALIZED")
    ctx["licensee"] = licensee
    ctx["statement"] = statement
    ctx["advances"] = paid_advances
    ctx["allocations"] = list_allocation_lines(statement_id=statement["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 6: distribution runs, audits, termination claims
# ---------------------------------------------------------------------------

def create_distribution_run(period_label="2026Q2"):
    payload = create_distribution_run_payload(period_label=period_label)
    return get_success_data(api_client.create_distribution_run(payload, ANALYST))


def create_licensee_audit(licensee_id, valuation_method="ACTUAL_SHORTFALL",
                          period=("2025-01-01T00:00:00Z",
                                  "2025-12-31T23:59:59Z")):
    payload = create_licensee_audit_payload(
        licensee_id, valuation_method=valuation_method,
        period_start=period[0], period_end=period[1])
    return get_success_data(api_client.create_licensee_audit(payload, AUDITOR))


def create_termination_claim(work_id,
                             intended_effective_date="2028-06-15T00:00:00Z",
                             statute_basis="SEC_203"):
    payload = create_termination_claim_payload(work_id, statute_basis,
                                               intended_effective_date)
    return get_success_data(
        api_client.create_termination_claim(payload, COPYRIGHT))


def effectuate_termination(work_id,
                           intended_effective_date="2028-06-15T00:00:00Z",
                           notice_clock="2026-01-01T00:00:00Z",
                           effective_clock=None):
    """Drive a work's copyright to TERMINATED through the full claim chain:
    claim create -> clock into the notice window -> file-notice -> clock to
    the intended effective date -> make-effective. Returns the claim."""
    claim = create_termination_claim(work_id, intended_effective_date)
    set_clock(notice_clock)
    get_success_data(api_client.file_notice(claim["id"], "N-1", COPYRIGHT))
    set_clock(effective_clock or intended_effective_date)
    claim = get_success_data(api_client.make_effective(claim["id"], COPYRIGHT))
    assert claim["status"] == "EFFECTIVE", (
        f"Setup failed: claim not EFFECTIVE, got {claim['status']}")
    return claim

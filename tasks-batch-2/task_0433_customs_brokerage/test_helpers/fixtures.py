"""Composite setup helpers.

These encapsulate the multi-step preambles that nearly every interesting test
needs: provisioning an importer + active bond + filed ISF, then walking a
customs entry through DRAFT -> FILED -> RELEASED -> LIQUIDATED, optionally with
PGA reviews, exam holds, and post-summary corrections.

The test harness restarts the server (empty DB) before every test, so each
fixture builds its preconditions from scratch using only PRD-declared endpoints.
All setup calls go through get_success_data() so a setup failure surfaces as a
clear "Setup failed" error rather than a confusing assertion deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_importer_payload,
    create_bond_payload,
    create_isf_payload,
    create_entry_payload,
    create_line_payload,
    create_pga_review_payload,
    create_exam_slot_payload,
    create_psc_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_broker_headers,
    make_officer_headers,
    make_importer_user_headers,
)

# Default clock used throughout the design indices.
DEFAULT_CLOCK = "2026-06-05T00:00:00Z"

ADMIN = TEST_USERS["admin_headers"]
BROKER = TEST_USERS["broker_headers"]
OFFICER = TEST_USERS["officer_headers"]


# ---------------------------------------------------------------------------
# Primitive provisioning
# ---------------------------------------------------------------------------
def set_clock(api, iso, headers=None):
    """Advance the server logical clock (AccountAdmin only)."""
    return get_success_data(api.set_clock(iso, headers or ADMIN))


def create_importer(api, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_importer(create_importer_payload(**overrides), headers or ADMIN)
    )


def create_active_bond(api, importer_id, headers=None, **overrides) -> dict:
    """Create a bond and activate it. Returns the ACTIVE bond."""
    h = headers or ADMIN
    bond = get_success_data(
        api.create_bond(create_bond_payload(importer_id, **overrides), h)
    )
    return get_success_data(api.activate_bond(bond["id"], h))


def create_filed_isf(api, importer_id, broker_headers=None, **overrides) -> dict:
    """Create an ISF and file it (DRAFT -> FILED). Returns the FILED ISF."""
    bh = broker_headers or BROKER
    isf = get_success_data(api.create_isf(create_isf_payload(importer_id, **overrides), bh))
    return get_success_data(api.file_isf(isf["id"], bh))


# ---------------------------------------------------------------------------
# Tier 1/2: base scenario — importer + active bond + filed ISF
# ---------------------------------------------------------------------------
def setup_base(
    api,
    clock=DEFAULT_CLOCK,
    bond_limit_cents=100_000_000,
    owner_user_id="imp-user-1",
    broker_user_id="broker-1",
    ior_number=None,
    bill_of_lading=None,
    vessel_eta="2026-06-10T00:00:00Z",
):
    """Importer (ACTIVE) + ACTIVE CONTINUOUS bond + FILED ISF.

    Returns dict: importer, bond, isf, plus header bundles for the broker and
    officer to use downstream.
    """
    if clock is not None:
        set_clock(api, clock)
    imp_over = {"owner_user_id": owner_user_id}
    if ior_number is not None:
        imp_over["ior_number"] = ior_number
    importer = create_importer(api, **imp_over)
    bond = create_active_bond(api, importer["id"], limit_cents=bond_limit_cents)
    broker = make_broker_headers(broker_user_id)
    isf_over = {"vessel_eta": vessel_eta}
    if bill_of_lading is not None:
        isf_over["bill_of_lading"] = bill_of_lading
    isf = create_filed_isf(api, importer["id"], broker_headers=broker, **isf_over)
    return {
        "importer": importer,
        "bond": bond,
        "isf": isf,
        "broker": broker,
        "broker_user_id": broker_user_id,
    }


# ---------------------------------------------------------------------------
# Tier 1/3: a DRAFT entry with one or more lines, ready to file
# ---------------------------------------------------------------------------
def create_draft_entry_with_lines(
    api,
    base,
    lines,
    entry_type="CONSUMPTION_01",
    country_of_origin="CN",
    entry_date="2026-06-10T00:00:00Z",
    broker_headers=None,
    attach_isf=True,
):
    """Create a DRAFT entry on the given base and add the supplied lines.

    `lines` is a list of dicts merged into create_line_payload. Returns
    (entry, [line, ...]). The entry references base['isf'] unless attach_isf
    is False (used to test ISF-not-filed precondition with a fresh DRAFT ISF).
    """
    bh = broker_headers or base["broker"]
    over = {
        "entry_type": entry_type,
        "country_of_origin": country_of_origin,
        "entry_date": entry_date,
    }
    if attach_isf:
        over["isf_filing_id"] = base["isf"]["id"]
    entry = get_success_data(
        api.create_entry(
            create_entry_payload(base["importer"]["id"], base["bond"]["id"], **over),
            bh,
        )
    )
    created_lines = []
    for line in lines:
        created_lines.append(
            get_success_data(
                api.create_line(entry["id"], create_line_payload(**line), bh)
            )
        )
    return entry, created_lines


def add_pga_review(api, entry_id, agency="FDA", headers=None) -> dict:
    """Open a PGAReview (decision=PENDING)."""
    return get_success_data(
        api.create_pga_review(
            create_pga_review_payload(entry_id, agency), headers or BROKER
        )
    )


def decide_pga(api, pga_id, decision, officer_headers=None) -> dict:
    return get_success_data(
        api.decide_pga_review(pga_id, decision, officer_headers or OFFICER)
    )


# ---------------------------------------------------------------------------
# Tier 3: file / release / liquidate shortcuts
# ---------------------------------------------------------------------------
def file_entry(api, entry_id, broker_headers=None) -> dict:
    return get_success_data(api.file_entry(entry_id, broker_headers or BROKER))


def review_entry(api, entry_id, action, officer_headers=None) -> dict:
    return get_success_data(
        api.review_entry(entry_id, action, officer_headers or OFFICER)
    )


def liquidate_entry(api, entry_id, officer_headers=None) -> dict:
    return get_success_data(
        api.liquidate_entry(entry_id, officer_headers or OFFICER)
    )


def setup_filed_entry(
    api,
    lines=None,
    clock=DEFAULT_CLOCK,
    bond_limit_cents=100_000_000,
    entry_type="CONSUMPTION_01",
    country_of_origin="CN",
    entry_date="2026-06-10T00:00:00Z",
):
    """Base + a single-line FILED entry (no PGA). Returns dict with base, entry,
    lines (after filing), and the filed entry object."""
    base = setup_base(api, clock=clock, bond_limit_cents=bond_limit_cents)
    if lines is None:
        lines = [{}]  # one default general ch94 cv=1_000_000 line
    entry, created = create_draft_entry_with_lines(
        api,
        base,
        lines,
        entry_type=entry_type,
        country_of_origin=country_of_origin,
        entry_date=entry_date,
    )
    filed = file_entry(api, entry["id"], base["broker"])
    return {"base": base, "entry": filed, "lines": created}


def setup_released_entry(
    api,
    lines=None,
    clock=DEFAULT_CLOCK,
    bond_limit_cents=100_000_000,
    entry_type="CONSUMPTION_01",
    country_of_origin="CN",
    officer_headers=None,
):
    """Base + a single-line entry walked through to RELEASED (no PGA).

    Returns dict with base, entry (released), and statement_id from the release.
    """
    ctx = setup_filed_entry(
        api,
        lines=lines,
        clock=clock,
        bond_limit_cents=bond_limit_cents,
        entry_type=entry_type,
        country_of_origin=country_of_origin,
    )
    released = review_entry(
        api, ctx["entry"]["id"], "RELEASE", officer_headers or OFFICER
    )
    ctx["entry"] = released
    ctx["statement_id"] = released.get("statement_id")
    return ctx


def setup_liquidated_entry(
    api,
    lines=None,
    clock=DEFAULT_CLOCK,
    bond_limit_cents=100_000_000,
    entry_type="CONSUMPTION_01",
    country_of_origin="CN",
    officer_headers=None,
):
    """Base + a single-line entry walked through to LIQUIDATED (no PGA).

    Returns dict with base, entry (liquidated), statement_id, and the entry's
    current version (needed for OCC on post-summary corrections).
    """
    ctx = setup_released_entry(
        api,
        lines=lines,
        clock=clock,
        bond_limit_cents=bond_limit_cents,
        entry_type=entry_type,
        country_of_origin=country_of_origin,
        officer_headers=officer_headers,
    )
    liquidated = liquidate_entry(api, ctx["entry"]["id"], officer_headers or OFFICER)
    ctx["entry"] = liquidated
    ctx["entry_version"] = liquidated["version"]
    ctx["statement_id"] = liquidated.get("statement_id", ctx.get("statement_id"))
    return ctx


# ---------------------------------------------------------------------------
# Tier 1/2/3: PGA + HOLD_EXAM + exam-slot scenarios
# ---------------------------------------------------------------------------
def setup_filed_entry_with_pending_pga(
    api,
    clock=DEFAULT_CLOCK,
    bond_limit_cents=100_000_000,
    fda_line_value=200_000,
    broker_user_id="broker-1",
):
    """Base + a FILED entry carrying one FDA-flagged line and a PENDING FDA
    PGAReview. Returns dict with base, entry (filed), line, pga.

    The PGA review is opened BEFORE filing (filing requires a PGAReview to exist
    for every PGA-flagged line).
    """
    base = setup_base(api, clock=clock, bond_limit_cents=bond_limit_cents,
                      broker_user_id=broker_user_id)
    entry, lines = create_draft_entry_with_lines(
        api,
        base,
        [{"hts_code": "2106909998", "customs_value_cents": fda_line_value,
          "quantity": 1, "pga_flag": "FDA"}],
    )
    pga = add_pga_review(api, entry["id"], "FDA", base["broker"])
    filed = file_entry(api, entry["id"], base["broker"])
    return {"base": base, "entry": filed, "line": lines[0], "pga": pga}


def setup_hold_exam_entry(
    api,
    clock=DEFAULT_CLOCK,
    bond_limit_cents=100_000_000,
    officer_headers=None,
):
    """Base + a FILED FDA entry routed to HOLD_EXAM, with its PGAReview upgraded
    HOLD -> MAY_PROCEED so the entry can later be released.

    Returns dict with base, entry (HOLD_EXAM), line, pga (MAY_PROCEED).
    """
    oh = officer_headers or OFFICER
    ctx = setup_filed_entry_with_pending_pga(
        api, clock=clock, bond_limit_cents=bond_limit_cents
    )
    held = review_entry(api, ctx["entry"]["id"], "HOLD", oh)
    ctx["entry"] = held
    # Clear the PGA so a later release is permitted.
    ctx["pga"] = decide_pga(api, ctx["pga"]["id"], "MAY_PROCEED", oh)
    return ctx


def book_exam_slot(api, entry_id, officer_headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_exam_slot(
            create_exam_slot_payload(entry_id, **overrides), officer_headers or OFFICER
        )
    )


# ---------------------------------------------------------------------------
# Tier 5: post-summary correction submission against a liquidated entry
# ---------------------------------------------------------------------------
def submit_psc(
    api,
    entry_id,
    expected_entry_version,
    broker_headers=None,
    **overrides,
) -> dict:
    """Submit a PSC/PROTEST (status=SUBMITTED) on a LIQUIDATED entry."""
    return get_success_data(
        api.create_psc(
            create_psc_payload(entry_id, expected_entry_version, **overrides),
            broker_headers or BROKER,
        )
    )


def setup_liquidated_entry_with_psc(
    api,
    corrected_value_delta_cents=200_000,
    filing_kind="PSC",
    lines=None,
    bond_limit_cents=100_000_000,
    country_of_origin="CN",
    clock=DEFAULT_CLOCK,
):
    """Base + LIQUIDATED entry + a SUBMITTED PSC carrying the entry's current
    version. Returns dict with base, entry (liquidated), statement_id, psc."""
    ctx = setup_liquidated_entry(
        api,
        lines=lines,
        clock=clock,
        bond_limit_cents=bond_limit_cents,
        country_of_origin=country_of_origin,
    )
    psc = submit_psc(
        api,
        ctx["entry"]["id"],
        ctx["entry_version"],
        broker_headers=ctx["base"]["broker"],
        filing_kind=filing_kind,
        corrected_value_delta_cents=corrected_value_delta_cents,
    )
    ctx["psc"] = psc
    return ctx

"""Composite setup helpers.

Encapsulates the multi-step preambles that the design instances share, so tests
focus on the trigger + assertions. All setup calls go through get_success_data()
(lenient 2xx validator) so a broken precondition surfaces as a clear "Setup
step failed" error rather than a confusing downstream assertion.

Identity threading: the Stakeholder role is entity-backed; any ownership-gated
call uses make_stakeholder_headers(shareholder_id). Grant approval is driven by
a BoardApprover whose X-User-ID differs from the drafting Administrator
(segregation of duties), so fixtures approve via make_board_approver_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_board_approver_headers,
)

ADMIN = TEST_USERS["administrator_headers"]
APPROVER = TEST_USERS["board_approver_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

# A distinct approver id, guaranteed different from the default admin id
# ("admin-1") so the segregation-of-duties gate passes in fixtures.
APPROVER_2 = make_board_approver_headers("approver-2")


# --------------------------------------------------------------------------
# Tier 0: low-level single-entity setup (used by everything above)
# --------------------------------------------------------------------------

def set_clock(instant: str):
    """Pin the server clock for vesting / temporal computations."""
    get_success_data(api_client.set_clock(instant, ADMIN))


def create_cap_table(company_name="Test Co", authorized_shares=10_000_000) -> dict:
    return get_success_data(
        api_client.create_cap_table(
            {"company_name": company_name, "authorized_shares": authorized_shares}, ADMIN
        )
    )


def create_security_class(cap_table_id, name="Common", class_type="COMMON",
                          original_issue_price_cents=0, **overrides) -> dict:
    payload = {
        "cap_table_id": cap_table_id,
        "name": name,
        "class_type": class_type,
        "original_issue_price_cents": original_issue_price_cents,
    }
    if class_type == "COMMON" and "liquidation_pref_multiple" not in overrides:
        payload["liquidation_pref_multiple"] = 0
    payload.update(overrides)
    return get_success_data(api_client.create_security_class(payload, ADMIN))


def create_shareholder(cap_table_id, legal_name="Emp", holder_type="EMPLOYEE",
                       email=None, **overrides) -> dict:
    payload = {
        "cap_table_id": cap_table_id,
        "legal_name": legal_name,
        "holder_type": holder_type,
        "email": email or f"{legal_name.replace(' ', '').lower()}@test.com",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_shareholder(payload, ADMIN))


def create_option_pool(cap_table_id, authorized_shares=100_000) -> dict:
    return get_success_data(
        api_client.create_option_pool(
            {"cap_table_id": cap_table_id, "authorized_shares": authorized_shares}, ADMIN
        )
    )


def create_effective_valuation(cap_table_id, fmv_per_share_cents=100,
                               valuation_date="2020-01-01T00:00:00Z",
                               expires_at="2030-12-31T00:00:00Z") -> dict:
    """Create a DRAFT valuation and approve it to EFFECTIVE. Default window is
    wide so it does not collide with realistic grant_dates."""
    val = get_success_data(api_client.create_valuation({
        "cap_table_id": cap_table_id,
        "fmv_per_share_cents": fmv_per_share_cents,
        "valuation_date": valuation_date,
        "expires_at": expires_at,
    }, ADMIN))
    get_success_data(api_client.approve_valuation(val["id"], APPROVER))
    return val


def issue_shares(cap_table_id, security_class_id, shareholder_id, share_count,
                 price_paid_cents=0) -> dict:
    return get_success_data(api_client.create_share_issuance({
        "cap_table_id": cap_table_id,
        "security_class_id": security_class_id,
        "shareholder_id": shareholder_id,
        "share_count": share_count,
        "price_paid_cents": price_paid_cents,
    }, ADMIN))


def lock_cap_table(cap_table_id) -> dict:
    """Read the current version, then lock with a fresh expected version."""
    ct = get_success_data(api_client.get_cap_table(cap_table_id, APPROVER))
    return get_success_data(
        api_client.lock_cap_table(
            cap_table_id, {"expected_cap_table_version": ct["version"]}, APPROVER
        )
    )


# --------------------------------------------------------------------------
# Tier 1 / Tier 3: grant lifecycle shortcuts
# --------------------------------------------------------------------------

def create_grant(cap_table_id, pool_id, shareholder_id, class_id, valuation_id,
                 share_count=1000, strike_price_cents=100,
                 grant_date="2020-01-01T00:00:00Z", vesting_months=48,
                 cliff_months=12, drafter_headers=ADMIN, **overrides) -> dict:
    """Draft a grant (DRAFT). drafter_headers controls the Administrator
    X-User-ID for segregation-of-duties scenarios."""
    payload = {
        "cap_table_id": cap_table_id,
        "option_pool_id": pool_id,
        "shareholder_id": shareholder_id,
        "security_class_id": class_id,
        "valuation_id": valuation_id,
        "share_count": share_count,
        "strike_price_cents": strike_price_cents,
        "grant_date": grant_date,
        "vesting_months": vesting_months,
        "cliff_months": cliff_months,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_option_grant(payload, drafter_headers))


def create_active_grant(cap_table_id, pool_id, shareholder_id, class_id, valuation_id,
                        approver_headers=APPROVER, **grant_overrides) -> dict:
    """Draft + approve a grant → ACTIVE. Returns the approved grant object."""
    grant = create_grant(cap_table_id, pool_id, shareholder_id, class_id, valuation_id,
                          **grant_overrides)
    return get_success_data(api_client.approve_option_grant(grant["id"], approver_headers))


def setup_active_vested_grant(fmv_per_share_cents=100, strike_price_cents=100,
                              share_count=1000, pool_shares=100_000,
                              early_exercise_allowed=False,
                              clock="2026-06-01T00:00:00Z",
                              grant_date="2020-01-01T00:00:00Z") -> dict:
    """Full preamble to a single ACTIVE, fully-vested grant on an OPEN cap table.

    Pipeline: cap table → clock → COMMON class → shareholder (US taxpayer) →
    EFFECTIVE valuation → pool → drafted grant → approved grant.

    Returns a dict of all created entities keyed by role:
      {ct, common, shareholder, valuation, pool, grant}
    """
    set_clock(clock)
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON",
                                   original_issue_price_cents=0)
    sh = create_shareholder(ct["id"], legal_name="Emp One", holder_type="EMPLOYEE",
                            email="emp1@test.com", is_us_taxpayer=True)
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=fmv_per_share_cents,
                                     valuation_date="2020-01-01T00:00:00Z",
                                     expires_at="2030-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=pool_shares)
    grant = create_active_grant(
        ct["id"], pool["id"], sh["id"], common["id"], val["id"],
        share_count=share_count, strike_price_cents=strike_price_cents,
        grant_date=grant_date, vesting_months=48, cliff_months=12,
        early_exercise_allowed=early_exercise_allowed,
    )
    return {"ct": ct, "common": common, "shareholder": sh, "valuation": val,
            "pool": pool, "grant": grant}


def setup_settled_exercise(share_count=1000, exercise_count=None,
                           fmv_per_share_cents=100, strike_price_cents=100,
                           early_exercise_allowed=False,
                           clock="2026-06-01T00:00:00Z") -> dict:
    """Active vested grant + one PENDING→SETTLED exercise.

    Returns {ct, common, shareholder, valuation, pool, grant, exercise}.
    exercise_count defaults to the grant share_count (full exercise).
    """
    env = setup_active_vested_grant(
        fmv_per_share_cents=fmv_per_share_cents, strike_price_cents=strike_price_cents,
        share_count=share_count, early_exercise_allowed=early_exercise_allowed, clock=clock,
    )
    ex_n = exercise_count if exercise_count is not None else share_count
    ex = get_success_data(api_client.create_exercise({
        "cap_table_id": env["ct"]["id"],
        "option_grant_id": env["grant"]["id"],
        "share_count": ex_n,
    }, ADMIN))
    ex = get_success_data(api_client.settle_exercise(ex["id"], ADMIN))
    env["exercise"] = ex
    return env


# --------------------------------------------------------------------------
# Tier 5: SafeNote lifecycle shortcuts
# --------------------------------------------------------------------------

def create_safe_note(cap_table_id, shareholder_id, instrument_type="SAFE",
                     principal_cents=1_000_000, issue_date="2025-01-01T00:00:00Z",
                     **overrides) -> dict:
    payload = {
        "cap_table_id": cap_table_id,
        "shareholder_id": shareholder_id,
        "instrument_type": instrument_type,
        "principal_cents": principal_cents,
        "issue_date": issue_date,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_safe_note(payload, ADMIN))


def create_outstanding_note(cap_table_id, shareholder_id, instrument_type="SAFE",
                            principal_cents=1_000_000, **overrides) -> dict:
    """Draft → submit-terms → execute → OUTSTANDING. Returns the executed note."""
    note = create_safe_note(cap_table_id, shareholder_id, instrument_type=instrument_type,
                            principal_cents=principal_cents, **overrides)
    get_success_data(api_client.submit_terms_safe_note(note["id"], ADMIN))
    return get_success_data(api_client.execute_safe_note(note["id"], APPROVER))


def setup_outstanding_safe_with_target(principal_cents=2_000_000, discount_pct=0.20,
                                       valuation_cap_cents=0,
                                       target_pps_cents=1000,
                                       issued_common=0,
                                       common_oip_cents=100) -> dict:
    """OPEN cap table; optional issued common to set fully_diluted base; one
    OUTSTANDING SAFE; a PREFERRED target class. Returns
    {ct, common, pref, shareholder, note, note_version}.
    note_version is the current note version (for the convert OCC field)."""
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON",
                                   original_issue_price_cents=common_oip_cents)
    founder = create_shareholder(ct["id"], legal_name="Founder", holder_type="FOUNDER",
                                 email="founder@conv.com")
    if issued_common > 0:
        issue_shares(ct["id"], common["id"], founder["id"], issued_common,
                     price_paid_cents=common_oip_cents * issued_common)
    pref = create_security_class(ct["id"], name="Series Seed", class_type="PREFERRED",
                                 original_issue_price_cents=target_pps_cents,
                                 liquidation_pref_multiple=1.0, participating=False)
    angel = create_shareholder(ct["id"], legal_name="Angel", holder_type="INVESTOR",
                               email="angel@conv.com")
    note = create_outstanding_note(
        ct["id"], angel["id"], instrument_type="SAFE", principal_cents=principal_cents,
        valuation_cap_cents=valuation_cap_cents, discount_pct=discount_pct,
    )
    return {"ct": ct, "common": common, "pref": pref, "shareholder": angel,
            "note": note, "note_version": note["version"]}


# --------------------------------------------------------------------------
# Tier 4 / waterfall: liquidation setup
# --------------------------------------------------------------------------

def setup_computed_waterfall(classes, proceeds_cents, email_suffix="wf") -> dict:
    """Build a cap table, create the given PREFERRED/COMMON classes with their
    issuances, create a liquidation event, and COMPUTE it.

    `classes` is an ordered list of dicts:
      {key, name, class_type, oip, pref_multiple, participating, cap_multiple,
       senior_to (key of the class above this one, or None), shares}
    Returns {ct, event, classes: {key: class_obj}}.
    """
    ct = create_cap_table(authorized_shares=10_000_000)
    inv = create_shareholder(ct["id"], legal_name="Inv", holder_type="INVESTOR",
                             email=f"inv@{email_suffix}.com")
    fnd = create_shareholder(ct["id"], legal_name="Founder", holder_type="FOUNDER",
                             email=f"f@{email_suffix}.com")
    created = {}
    for spec in classes:
        payload = {
            "name": spec["name"],
            "class_type": spec["class_type"],
            "original_issue_price_cents": spec.get("oip", 0),
            "liquidation_pref_multiple": spec.get("pref_multiple", 0),
        }
        if spec["class_type"] == "PREFERRED":
            payload["participating"] = spec.get("participating", False)
            payload["participation_cap_multiple"] = spec.get("cap_multiple", 0)
        senior_key = spec.get("senior_to")
        extra = {}
        if senior_key is not None:
            extra["seniority_below_class_id"] = created[senior_key]["id"]
        cls = create_security_class(ct["id"], **payload, **extra)
        created[spec["key"]] = cls
        if spec.get("shares", 0) > 0:
            recipient = inv["id"] if spec["class_type"] == "PREFERRED" else fnd["id"]
            issue_shares(ct["id"], cls["id"], recipient, spec["shares"],
                         price_paid_cents=spec.get("oip", 0) * spec["shares"])
    event = get_success_data(api_client.create_liquidation_event({
        "cap_table_id": ct["id"], "total_proceeds_cents": proceeds_cents,
    }, ADMIN))
    event = get_success_data(api_client.compute_liquidation_event(event["id"], APPROVER))
    return {"ct": ct, "event": event, "classes": created}


def get_distribution_for_class(event_id, security_class_id) -> dict:
    """Read the waterfall distribution row for a given class within an event."""
    rows = get_success_data(
        api_client.list_event_distributions(event_id, AUDITOR, params={"limit": 100})
    )
    for row in rows:
        if row["security_class_id"] == security_class_id:
            return row
    raise AssertionError(f"No distribution row for class {security_class_id} in event {event_id}")

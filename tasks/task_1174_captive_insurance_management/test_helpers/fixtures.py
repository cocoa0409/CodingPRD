"""Composite setup helpers (multi-step API preconditions).

Every fixture builds its preconditions from scratch via PRD-declared endpoints:
the harness restarts the server before every test, so nothing carries over.
Setup calls use the lenient get_success_data() validator so failures surface as
clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_actuary_headers,
    make_board_director_headers,
)

CM = TEST_USERS["captive_manager_headers"]
REG = TEST_USERS["domicile_regulator_headers"]
UW = TEST_USERS["underwriter_headers"]
ACT = TEST_USERS["actuary_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
DIR = TEST_USERS["board_director_headers"]
TAX = TEST_USERS["tax_advisor_headers"]


def _ok(resp, step: str):
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed at {step}: expected object payload, got {data!r}"
    return data


# ---------------------------------------------------------------------------
# Tier 1: Captive state progression
# ---------------------------------------------------------------------------

def create_captive(**overrides) -> dict:
    """Create a CaptiveEntity (FORMATION_PENDING). Returns the captive."""
    resp = api_client.create_captive(factories.create_captive_payload(**overrides), CM)
    return _ok(resp, "create captive")


def get_captive(captive_id: str) -> dict:
    return _ok(api_client.get_captive(captive_id, CM), "get captive")


def get_captive_version(captive_id: str) -> int:
    return int(get_captive(captive_id)["version"])


def create_domicile_filing(captive_id: str, **overrides) -> dict:
    payload = factories.create_domicile_filing_payload(**overrides)
    resp = api_client.create_domicile_filing(captive_id, payload, CM)
    return _ok(resp, "create domicile filing")


def setup_captive_with_draft_filing(**captive_overrides):
    """Captive in FORMATION_PENDING + one DRAFT filing. Returns (captive, filing)."""
    captive = create_captive(**captive_overrides)
    filing = create_domicile_filing(captive["id"])
    return captive, filing


def setup_domicile_filed_captive(**captive_overrides):
    """Captive in DOMICILE_FILED + filing in SUBMITTED. Returns (captive, filing)."""
    captive, filing = setup_captive_with_draft_filing(**captive_overrides)
    _ok(api_client.submit_filing(captive["id"], filing["id"], CM), "submit filing")
    return get_captive(captive["id"]), filing


def setup_capitalized_captive(**captive_overrides) -> dict:
    """Full filing chain to CAPITALIZED. Returns refreshed captive."""
    captive, filing = setup_domicile_filed_captive(**captive_overrides)
    _ok(api_client.acknowledge_filing(captive["id"], filing["id"], REG), "acknowledge filing")
    _ok(api_client.approve_filing(captive["id"], filing["id"], REG), "approve filing")
    return get_captive(captive["id"])


def activate_captive(captive_id: str) -> dict:
    return _ok(api_client.activate_captive(captive_id, CM), "activate captive")


# ---------------------------------------------------------------------------
# Tier 2/3: Programs, fronting, collateral
# ---------------------------------------------------------------------------

def create_program(captive_id: str, expected_captive_version=None, **overrides) -> dict:
    """Create a program with the OCC field set to the captive's current version
    unless an explicit expected_captive_version override is supplied."""
    payload = factories.create_program_payload(**overrides)
    if "expected_captive_version" not in payload:
        version = expected_captive_version
        if version is None:
            version = get_captive_version(captive_id)
        payload["expected_captive_version"] = version
    resp = api_client.create_program(captive_id, payload, UW)
    return _ok(resp, "create program")


def setup_quoted_program(captive_id: str, **overrides) -> dict:
    program = create_program(captive_id, **overrides)
    _ok(api_client.quote_program(captive_id, program["id"], UW), "quote program")
    return _ok(api_client.get_program(captive_id, program["id"], UW), "get quoted program")


def create_fronting(captive_id: str, program_id: str, **overrides) -> dict:
    payload = factories.create_fronting_payload(**overrides)
    resp = api_client.create_fronting(captive_id, program_id, payload, UW)
    return _ok(resp, "create fronting arrangement")


def setup_fronting_terms_agreed(captive_id: str, program_id: str, **overrides) -> dict:
    fronting = create_fronting(captive_id, program_id, **overrides)
    _ok(api_client.agree_fronting_terms(captive_id, program_id, fronting["id"], UW), "agree terms")
    return _ok(api_client.get_fronting(captive_id, program_id, fronting["id"], UW), "get fronting")


def create_collateral(captive_id: str, program_id: str, fronting_id: str, **overrides) -> dict:
    payload = factories.create_collateral_payload(**overrides)
    resp = api_client.create_collateral(captive_id, program_id, fronting_id, payload, CM)
    return _ok(resp, "create collateral posting")


def setup_fronting_collateral_posted(captive_id: str, program_id: str,
                                     collateral_amount: int = 1000000,
                                     collateral_type: str = "CASH_ESCROW",
                                     **fronting_overrides):
    """Fronting at COLLATERAL_POSTED with one VERIFIED collateral posting.
    Returns (fronting, collateral)."""
    fronting = setup_fronting_terms_agreed(captive_id, program_id, **fronting_overrides)
    collateral = create_collateral(
        captive_id, program_id, fronting["id"],
        collateral_type=collateral_type, amount_cents=collateral_amount,
    )
    _ok(api_client.verify_collateral(captive_id, program_id, fronting["id"], collateral["id"], CM),
        "verify collateral")
    _ok(api_client.post_fronting_collateral(captive_id, program_id, fronting["id"], CM),
        "post-collateral transition")
    fronting = _ok(api_client.get_fronting(captive_id, program_id, fronting["id"], UW), "get fronting")
    collateral = _ok(
        api_client.get_collateral(captive_id, program_id, fronting["id"], collateral["id"], CM),
        "get collateral",
    )
    return fronting, collateral


def setup_bound_program(captive_id: str, fronting_required: bool = False, **overrides):
    """Program walked DRAFT -> QUOTED -> BOUND (fronting chain first when required).
    Returns (program, fronting_or_None)."""
    if "fronting_required" not in overrides:
        overrides["fronting_required"] = fronting_required
    program = setup_quoted_program(captive_id, **overrides)
    fronting = None
    if overrides.get("fronting_required"):
        fronting, _collateral = setup_fronting_collateral_posted(captive_id, program["id"])
    _ok(api_client.bind_program(captive_id, program["id"], UW), "bind program")
    program = _ok(api_client.get_program(captive_id, program["id"], UW), "get bound program")
    return program, fronting


def set_logical_clock(to_iso8601: str = C.ACTIVATION_CLOCK_TIME):
    _ok(api_client.set_clock(to_iso8601, CM), "set logical clock")


def setup_in_force_program(captive_id: str, fronting_required: bool = False, **overrides):
    """Program walked to IN_FORCE on an ACTIVE captive (captive is activated here).
    Returns (captive, program, fronting_or_None)."""
    program, fronting = setup_bound_program(captive_id, fronting_required, **overrides)
    captive = activate_captive(captive_id)
    if fronting is not None:
        _ok(api_client.activate_fronting(captive_id, program["id"], fronting["id"], UW),
            "activate fronting")
        fronting = _ok(api_client.get_fronting(captive_id, program["id"], fronting["id"], UW),
                       "get active fronting")
    set_logical_clock(C.ACTIVATION_CLOCK_TIME)
    _ok(api_client.activate_program(captive_id, program["id"], UW), "activate program")
    program = _ok(api_client.get_program(captive_id, program["id"], UW), "get in-force program")
    return captive, program, fronting


def setup_active_captive_with_program(captive_overrides=None, fronting_required: bool = False,
                                      **program_overrides):
    """Full chain: captive CAPITALIZED -> ACTIVE, program -> IN_FORCE.
    Returns (captive, program, fronting_or_None)."""
    captive = setup_capitalized_captive(**(captive_overrides or {}))
    return setup_in_force_program(captive["id"], fronting_required, **program_overrides)


# ---------------------------------------------------------------------------
# Tier 2: Operating units and allocations
# ---------------------------------------------------------------------------

def create_operating_unit(captive_id: str, **overrides) -> dict:
    payload = factories.create_operating_unit_payload(**overrides)
    resp = api_client.create_operating_unit(captive_id, payload, CM)
    return _ok(resp, "create operating unit")


def create_allocation(captive_id: str, program_id: str, unit_id: str, **overrides) -> dict:
    payload = factories.create_allocation_payload(operating_unit_id=unit_id, **overrides)
    resp = api_client.create_allocation(captive_id, program_id, payload, UW)
    return _ok(resp, "create allocation")


def setup_provisional_allocation(captive_overrides=None, program_overrides=None,
                                 unit_overrides=None, allocation_overrides=None):
    """ACTIVE captive + IN_FORCE program + ACTIVE units + one PROVISIONAL
    allocation. Returns dict with captive/program/unit/allocation.

    A second ACTIVE unit with triple the target unit's exposure keeps the
    target unit's EXPOSURE_PRO_RATA share at 25% of the premium budget, inside
    PRD §3.5's "No unit may receive more than 50% of the program's
    `premium_budget_cents`" concentration cap.
    """
    captive, program, _fronting = setup_active_captive_with_program(
        captive_overrides=captive_overrides, **(program_overrides or {}),
    )
    unit = create_operating_unit(captive["id"], **(unit_overrides or {}))
    create_operating_unit(captive["id"], exposure_amount=3000)
    allocation = create_allocation(captive["id"], program["id"], unit["id"],
                                   **(allocation_overrides or {}))
    return {"captive": captive, "program": program, "unit": unit, "allocation": allocation}


# ---------------------------------------------------------------------------
# Tier 3/5: Claims lifecycle
# ---------------------------------------------------------------------------

def create_claim(captive_id: str, program_id: str, unit_id: str, **overrides) -> dict:
    payload = factories.create_claim_payload(operating_unit_id=unit_id, **overrides)
    resp = api_client.create_claim(captive_id, program_id, payload, ADJ)
    return _ok(resp, "create claim")


def setup_reserved_claim(reserve_amount_cents: int = 45000, claimed_amount_cents: int = 50000,
                         per_occurrence_limit_cents: int = None,
                         captive_overrides=None, program_overrides=None):
    """ACTIVE captive + IN_FORCE program + unit + claim walked to RESERVED.
    Returns dict with captive/program/unit/claim (claim refreshed)."""
    program_overrides = dict(program_overrides or {})
    if per_occurrence_limit_cents is not None:
        program_overrides["per_occurrence_limit_cents"] = per_occurrence_limit_cents
    captive, program, _fronting = setup_active_captive_with_program(
        captive_overrides=captive_overrides, **program_overrides,
    )
    unit = create_operating_unit(captive["id"])
    claim = create_claim(captive["id"], program["id"], unit["id"],
                         claimed_amount_cents=claimed_amount_cents)
    _ok(api_client.acknowledge_claim(captive["id"], program["id"], claim["id"], ADJ),
        "acknowledge claim")
    _ok(api_client.investigate_claim(captive["id"], program["id"], claim["id"], ADJ),
        "investigate claim")
    _ok(api_client.set_claim_reserve(captive["id"], program["id"], claim["id"],
                                     {"reserve_amount_cents": reserve_amount_cents}, ACT),
        "set claim reserve")
    claim = _ok(api_client.get_claim(captive["id"], program["id"], claim["id"], ADJ), "get claim")
    return {"captive": captive, "program": program, "unit": unit, "claim": claim}


def settle_claim(ctx: dict, settlement_amount_cents: int, expected_captive_version=None,
                 headers=None):
    """Settle the reserved claim in ctx; OCC version defaults to the captive's
    current version, re-read immediately before the call."""
    captive_id = ctx["captive"]["id"]
    if expected_captive_version is None:
        expected_captive_version = get_captive_version(captive_id)
    payload = {
        "settlement_amount_cents": settlement_amount_cents,
        "expected_captive_version": expected_captive_version,
    }
    return api_client.settle_claim(captive_id, ctx["program"]["id"], ctx["claim"]["id"],
                                   payload, headers or ADJ)


# ---------------------------------------------------------------------------
# Tier 3: Actuarial reserves
# ---------------------------------------------------------------------------

def create_reserve(captive_id: str, program_id: str, creator_headers=None, **overrides) -> dict:
    payload = factories.create_reserve_payload(**overrides)
    resp = api_client.create_reserve(captive_id, program_id, payload, creator_headers or ACT)
    return _ok(resp, "create reserve")


def setup_reviewed_reserve(captive_id: str, program_id: str, creator_headers=None, **overrides) -> dict:
    reserve = create_reserve(captive_id, program_id, creator_headers=creator_headers, **overrides)
    _ok(api_client.review_reserve(captive_id, program_id, reserve["id"], ACT), "review reserve")
    return _ok(api_client.get_reserve(captive_id, program_id, reserve["id"], ACT),
               "get reviewed reserve")


def setup_certified_reserve(captive_id: str, program_id: str, creator_headers=None,
                            certifier_headers=None, **overrides) -> dict:
    """Reserve walked to CERTIFIED. Segregation of duties (PRD §2.7): the
    certifier's X-User-ID differs from the creator's. carried_reserve_cents is
    read back from the reviewed reserve's low estimate (inclusive boundary)."""
    creator_headers = creator_headers or make_actuary_headers("actuary-creator-1")
    certifier_headers = certifier_headers or make_actuary_headers("actuary-certifier-1")
    reserve = setup_reviewed_reserve(captive_id, program_id, creator_headers=creator_headers,
                                     **overrides)
    carried = reserve["low_estimate_cents"]
    _ok(api_client.certify_reserve(captive_id, program_id, reserve["id"],
                                   {"carried_reserve_cents": carried}, certifier_headers),
        "certify reserve")
    return _ok(api_client.get_reserve(captive_id, program_id, reserve["id"], ACT),
               "get certified reserve")


# ---------------------------------------------------------------------------
# Tier 5: Annual statements and board meetings
# ---------------------------------------------------------------------------

def create_annual_statement(captive_id: str, **overrides) -> dict:
    payload = factories.create_annual_statement_payload(**overrides)
    resp = api_client.create_annual_statement(captive_id, payload, CM)
    return _ok(resp, "create annual statement")


def setup_actuarial_review_statement(captive_id: str, **overrides) -> dict:
    statement = create_annual_statement(captive_id, **overrides)
    _ok(api_client.submit_statement_for_review(captive_id, statement["id"], CM),
        "submit statement for review")
    return _ok(api_client.get_annual_statement(captive_id, statement["id"], CM),
               "get in-review statement")


def setup_minutes_approved_meeting(captive_id: str, drafter_headers=None, approver_headers=None,
                                   **overrides) -> dict:
    """BoardMeeting walked to MINUTES_APPROVED. Segregation of duties (PRD §2.7):
    approver's X-User-ID differs from the drafter's."""
    drafter_headers = drafter_headers or make_board_director_headers("board-director-drafter-1")
    approver_headers = approver_headers or make_board_director_headers("board-director-approver-1")
    payload = factories.create_board_meeting_payload(**overrides)
    meeting = _ok(api_client.create_board_meeting(captive_id, payload, drafter_headers),
                  "create board meeting")
    assert meeting.get("quorum_met") is True, (
        f"Setup failed: quorum not met for meeting {meeting.get('id')} "
        f"(directors_present={meeting.get('directors_present')}, "
        f"quorum_required={meeting.get('quorum_required')})"
    )
    _ok(api_client.convene_meeting(captive_id, meeting["id"], drafter_headers), "convene meeting")
    _ok(api_client.draft_minutes(captive_id, meeting["id"],
                                 factories.create_draft_minutes_payload(), drafter_headers),
        "draft minutes")
    _ok(api_client.approve_minutes(captive_id, meeting["id"], approver_headers), "approve minutes")
    return _ok(api_client.get_board_meeting(captive_id, meeting["id"], drafter_headers),
               "get approved meeting")


# ---------------------------------------------------------------------------
# Tier 4: Governance score targeting (tax-position challenge chain)
# ---------------------------------------------------------------------------

_TAX_POSITION_TYPES = [
    "PREMIUM_DEDUCTIBILITY", "RISK_DISTRIBUTION", "MICRO_CAPTIVE_ELECTION",
    "ARM_LENGTH_PRICING", "EXCISE_TAX_EXEMPTION",
]


def challenge_one_tax_position(captive_id: str, position_type: str = "RISK_DISTRIBUTION",
                               tax_year: int = 2026) -> dict:
    """Create -> analyze -> issue-opinion -> file -> challenge one tax position.
    Each completed cycle decrements governance_score by 15 (PRD §2.9/§3.10).
    Returns the CHALLENGED position."""
    position = _ok(
        api_client.create_tax_position(
            captive_id,
            factories.create_tax_position_payload(tax_year=tax_year, position_type=position_type),
            TAX,
        ),
        "create tax position",
    )
    _ok(api_client.analyze_tax_position(captive_id, position["id"], TAX), "analyze tax position")
    _ok(api_client.issue_opinion(captive_id, position["id"],
                                 {"reporting_position": "MORE_LIKELY_THAN_NOT"}, TAX),
        "issue opinion")
    _ok(api_client.file_tax_position(captive_id, position["id"], CM), "file tax position")
    return _ok(api_client.challenge_tax_position(captive_id, position["id"], TAX),
               "challenge tax position")


def drive_governance_below_suspension_threshold(captive_id: str) -> dict:
    """Run five challenge cycles (5 x -15) so governance_score falls to 25, below
    the suspension threshold of 40 (PRD §2.9). Returns refreshed captive."""
    for position_type in _TAX_POSITION_TYPES:
        challenge_one_tax_position(captive_id, position_type=position_type)
    return get_captive(captive_id)


# ---------------------------------------------------------------------------
# Tier 5: Suspension and dissolution terminal scenarios
# ---------------------------------------------------------------------------

def setup_suspendable_captive_with_active_program(fronting_required: bool = True):
    """ACTIVE captive + IN_FORCE program + ACTIVE fronting, with governance_score
    driven below 40 so the regulator has suspension grounds (PRD §3.2).
    Returns dict with captive/program/fronting (captive refreshed)."""
    captive, program, fronting = setup_active_captive_with_program(fronting_required=fronting_required)
    captive = drive_governance_below_suspension_threshold(captive["id"])
    assert captive["governance_score"] < C.GOVERNANCE_SUSPENSION_THRESHOLD, (
        f"Setup failed: governance_score {captive['governance_score']} not below "
        f"{C.GOVERNANCE_SUSPENSION_THRESHOLD}"
    )
    return {"captive": captive, "program": program, "fronting": fronting}


def setup_dissolved_captive() -> dict:
    """Full lifecycle to DISSOLVED: capitalized -> program BOUND -> captive ACTIVE
    -> program IN_FORCE -> RUN_OFF -> CLOSED -> dissolve. Returns dissolved captive."""
    captive, program, _fronting = setup_active_captive_with_program()
    _ok(api_client.enter_runoff_program(captive["id"], program["id"], UW), "enter run-off")
    _ok(api_client.close_program(captive["id"], program["id"], UW), "close program")
    return _ok(api_client.dissolve_captive(captive["id"], CM), "dissolve captive")

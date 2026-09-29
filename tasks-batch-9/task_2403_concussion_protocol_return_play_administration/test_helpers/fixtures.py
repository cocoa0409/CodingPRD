"""
Composite fixtures for the Concussion Protocol & Return-to-Play Administration API.

The database is empty at the start of every test, so each test builds the exact
protocol state it needs from scratch.  The functions here are the shared
progressions along the protocol timeline, in increasing depth:

* ``setup_reference_data``  — clubs, clinicians, a player with a valid baseline
  and a scheduled week-1 game (the logical clock is still at its default).
* ``setup_live_game``       — the same, with kickoff reached and the game live.
* ``setup_screened_evaluation`` — an observer-initiated evaluation screened with a
  no-go sign, so the player is under mandatory removal.
* ``setup_locker_room_exam``  — the consultant-attended examination under way.
* ``setup_diagnosed_case``    — the concussion documented and the case open.
* ``setup_case_through_stage`` — the graduated return walked to a chosen stage on
  the earliest legal instants.
* ``setup_case_pending_clearance`` — all five stages passed, the post-diagnosis
  baseline retest filed and a consultant clearance requested.
* ``setup_case_with_approved_clearance`` — the clearance approved, the clock moved
  to the case's earliest return instant.

Audit helpers (``open_audit``, ``issue_findings``, ``close_audit``,
``setup_audit_with_findings``, ``sanction_club``) drive the compliance side.

Every setup call is validated leniently, so a broken setup fails loudly with the
server's own error id rather than surfacing as a mysterious assertion later.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ADMIN,
    AUDITOR_A,
    AUDITOR_B,
    AUDITOR_C,
    make_club_physician_headers,
    make_compliance_officer_headers,
    make_consultant_headers,
    make_observer_headers,
)

# ─── Canonical instants along the protocol timeline ──────────────────────────

KICKOFF_AT = "2026-09-13T17:00:00Z"
EVALUATION_INITIATED_AT = "2026-09-13T18:05:00Z"
EXAM_STARTED_AT = "2026-09-13T18:10:00Z"
DIAGNOSIS_AT = "2026-09-13T18:19:00Z"

# The exam block is thirty minutes long, treated as a closed interval.
EXAM_BLOCK_ENDS_AT = "2026-09-13T18:40:00.000Z"

DIAGNOSIS_AT_MS = "2026-09-13T18:19:00.000Z"

# Stamped at diagnosis and never revised.
CANONICAL_PROJECTED_RETURN_AT = "2026-09-23T18:19:00.000Z"
# Derived from the stage-five sign-off.
CANONICAL_EARLIEST_RETURN_AT = "2026-09-28T12:00:00.000Z"
CANONICAL_SEVERITY_INDEX = 82
CANONICAL_BASELINE_DEVIATION_POINTS = 18

# (stage_index, start instant, sign-off instant, symptom score at sign-off).
# Each start is the stage's own min_start_at and each sign-off is the stage's own
# dwell_complete_at, so the whole chain runs on the earliest legal instants.
CANONICAL_STAGE_TIMELINE = [
    (1, "2026-09-15T12:00:00Z", "2026-09-16T12:00:00Z", 0),
    (2, "2026-09-17T12:00:00Z", "2026-09-18T12:00:00Z", 0),
    (3, "2026-09-19T12:00:00Z", "2026-09-20T12:00:00Z", 1),
    (4, "2026-09-21T12:00:00Z", "2026-09-23T12:00:00Z", 0),
    (5, "2026-09-25T12:00:00Z", "2026-09-27T12:00:00Z", 0),
]

STAGE_FIVE_SIGNOFF_AT = "2026-09-27T12:00:00Z"

CREDENTIAL_EXPIRES_AT = "2027-12-31T00:00:00Z"


# ─── Primitive helpers ───────────────────────────────────────────────────────

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock; the only way clock-driven state becomes reachable."""
    return get_success_data(api.set_clock(current_utc, ADMIN))


def create_club(
    api: ApiClient,
    name: str = "Harbor City Kraken",
    market_code: str = "HCK",
    exemption_slots_total: Any = 3,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_club(
            f.club_payload(
                name=name,
                market_code=market_code,
                exemption_slots_total=exemption_slots_total,
            ),
            ADMIN,
        )
    )


def create_clinician(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_clinician(payload, ADMIN))


def create_club_physician(
    api: ApiClient,
    club_id: str,
    full_name: str = "Dr Vance",
    license_number: str = "LIC-1001",
    credential_expires_at: str = CREDENTIAL_EXPIRES_AT,
) -> Dict[str, Any]:
    return create_clinician(
        api,
        f.club_physician_payload(
            club_id=club_id,
            full_name=full_name,
            license_number=license_number,
            credential_expires_at=credential_expires_at,
        ),
    )


def create_observer(
    api: ApiClient,
    full_name: str = "Dr Osei",
    license_number: str = "LIC-2001",
    credential_expires_at: str = CREDENTIAL_EXPIRES_AT,
) -> Dict[str, Any]:
    return create_clinician(
        api,
        f.observer_payload(
            full_name=full_name,
            license_number=license_number,
            credential_expires_at=credential_expires_at,
        ),
    )


def create_consultant(
    api: ApiClient,
    full_name: str = "Dr Iyer",
    license_number: str = "LIC-3001",
    credential_expires_at: str = CREDENTIAL_EXPIRES_AT,
) -> Dict[str, Any]:
    return create_clinician(
        api,
        f.consultant_payload(
            full_name=full_name,
            license_number=license_number,
            credential_expires_at=credential_expires_at,
        ),
    )


def create_player(
    api: ApiClient,
    club_id: str,
    full_name: str = "K Mbeki",
    jersey_number: int = 24,
    position: str = "WR",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_player(
            f.player_payload(
                club_id=club_id,
                full_name=full_name,
                jersey_number=jersey_number,
                position=position,
            ),
            headers or ADMIN,
        )
    )


def file_baseline(
    api: ApiClient,
    player_id: str,
    physician_id: str,
    season_year: int = 2026,
    composite_score: int = 88,
    reaction_time_ms: int = 520,
    symptom_score: int = 0,
    expected_player_version: Optional[int] = None,
) -> Dict[str, Any]:
    """File a baseline test, re-reading the player's version when not supplied."""
    if expected_player_version is None:
        player = get_success_data(api.get_player(player_id, ADMIN))
        expected_player_version = player["version"]
    return get_success_data(
        api.create_baseline_test(
            f.baseline_payload(
                player_id=player_id,
                expected_player_version=expected_player_version,
                season_year=season_year,
                composite_score=composite_score,
                reaction_time_ms=reaction_time_ms,
                symptom_score=symptom_score,
            ),
            make_club_physician_headers(physician_id),
        )
    )


def create_game(
    api: ApiClient,
    home_club_id: str,
    away_club_id: str,
    season_year: int = 2026,
    week_index: int = 1,
    kickoff_at: str = KICKOFF_AT,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_game(
            f.game_payload(
                home_club_id=home_club_id,
                away_club_id=away_club_id,
                season_year=season_year,
                week_index=week_index,
                kickoff_at=kickoff_at,
            ),
            ADMIN,
        )
    )


def advance_game(api: ApiClient, game_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.advance_game_status(game_id, f.advance_status_payload(to_status), ADMIN)
    )


# ─── Convenience reads ───────────────────────────────────────────────────────

def read_club(api: ApiClient, club_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_club(club_id, ADMIN))


def read_clinician(api: ApiClient, clinician_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_clinician(clinician_id, ADMIN))


def read_player(api: ApiClient, player_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_player(player_id, ADMIN))


def read_game(api: ApiClient, game_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_game(game_id, ADMIN))


def read_baseline(api: ApiClient, baseline_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_baseline_test(baseline_id, ADMIN))


def read_evaluation(api: ApiClient, evaluation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_sideline_evaluation(evaluation_id, ADMIN))


def read_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_concussion_case(case_id, ADMIN))


def read_step(api: ApiClient, step_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_return_step(step_id, ADMIN))


def read_clearance(api: ApiClient, clearance_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_inc_clearance(clearance_id, ADMIN))


def read_audit(api: ApiClient, audit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_protocol_audit(audit_id, ADMIN))


def read_injury_report(api: ApiClient, entry_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_injury_report_entry(entry_id, ADMIN))


def read_compliance_summary(api: ApiClient, club_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_compliance_summary(club_id, ADMIN))


def case_version(api: ApiClient, case_id: str) -> int:
    return read_case(api, case_id)["version"]


def player_version(api: ApiClient, player_id: str) -> int:
    return read_player(api, player_id)["version"]


# ─── Tier 1: league reference data ───────────────────────────────────────────

def setup_reference_data(api: ApiClient) -> Dict[str, Any]:
    """
    Two clubs, the three authority classes of clinician, one player with a valid
    pre-season baseline and a scheduled week-1 game between the two clubs.

    The logical clock is pinned to the default instant, so every credential is
    live and the baseline has 365 days of validity ahead of it.
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    club_h = create_club(api, "Harbor City Kraken", "HCK", 3)
    club_r = create_club(api, "Ridgeway Sentinels", "RWS", 3)

    doc_h = create_club_physician(api, club_h["id"], "Dr Vance", "LIC-1001")
    observer = create_observer(api)
    consultant = create_consultant(api)

    player = create_player(api, club_h["id"], "K Mbeki", 24, "WR")
    baseline = file_baseline(
        api,
        player["id"],
        doc_h["id"],
        composite_score=88,
        reaction_time_ms=520,
        symptom_score=0,
        expected_player_version=player["version"],
    )

    game = create_game(api, club_h["id"], club_r["id"])

    return {
        "club_h_id": club_h["id"],
        "club_r_id": club_r["id"],
        "doc_h_id": doc_h["id"],
        "obs_id": observer["id"],
        "inc_id": consultant["id"],
        "player_id": player["id"],
        "player_v1": player["version"],
        "baseline_id": baseline["id"],
        "game_id": game["id"],
        "doc_h_headers": make_club_physician_headers(doc_h["id"]),
        "obs_headers": make_observer_headers(observer["id"]),
        "inc_headers": make_consultant_headers(consultant["id"]),
        "club_h_headers": make_compliance_officer_headers(club_h["id"]),
        "club_r_headers": make_compliance_officer_headers(club_r["id"]),
    }


# ─── Tier 2: game day ────────────────────────────────────────────────────────

def setup_live_game(api: ApiClient) -> Dict[str, Any]:
    """Reference data with the clock at kickoff and the game IN_PROGRESS."""
    ctx = setup_reference_data(api)
    set_clock(api, KICKOFF_AT)
    advance_game(api, ctx["game_id"], "IN_PROGRESS")
    return ctx


def setup_screened_evaluation(api: ApiClient) -> Dict[str, Any]:
    """
    An observer-initiated evaluation screened with an ATAXIA no-go sign and a
    symptom score of 9, so mandatory removal is in force.
    """
    ctx = setup_live_game(api)
    set_clock(api, EVALUATION_INITIATED_AT)

    evaluation = get_success_data(
        api.create_sideline_evaluation(
            f.evaluation_payload(
                ctx["player_id"], ctx["game_id"], trigger_source="UNAFFILIATED_OBSERVER"
            ),
            ctx["obs_headers"],
        )
    )
    get_success_data(
        api.screen_evaluation(
            evaluation["id"],
            f.screen_payload(no_go_signs=["ATAXIA"], symptom_score=9),
            ctx["doc_h_headers"],
        )
    )
    ctx["eval_id"] = evaluation["id"]
    return ctx


def setup_locker_room_exam(api: ApiClient) -> Dict[str, Any]:
    """The screened evaluation moved into the consultant-attended examination."""
    ctx = setup_screened_evaluation(api)
    set_clock(api, EXAM_STARTED_AT)
    get_success_data(
        api.start_locker_room_exam(
            ctx["eval_id"], f.locker_room_exam_payload(ctx["obs_id"]), ctx["doc_h_headers"]
        )
    )
    return ctx


# ─── Tier 3: the diagnosed case ──────────────────────────────────────────────

def setup_diagnosed_case(api: ApiClient) -> Dict[str, Any]:
    """
    The concussion documented nine whole minutes into the examination, with a
    symptom score of 9 against a composite of 70.
    """
    ctx = setup_locker_room_exam(api)
    set_clock(api, DIAGNOSIS_AT)
    case = get_success_data(
        api.diagnose_concussion(
            ctx["eval_id"],
            f.diagnose_payload(symptom_score=9, composite_score=70),
            ctx["doc_h_headers"],
        )
    )
    ctx["case_id"] = case["id"]
    ctx["case"] = case
    ctx["projected_return_at"] = case.get("projected_return_at")
    return ctx


# ─── Tier 4: the graduated return ────────────────────────────────────────────

def start_stage(
    api: ApiClient, ctx: Dict[str, Any], stage_index: int, at: Optional[str] = None
) -> Dict[str, Any]:
    """Open one graduated-return stage, optionally moving the clock first."""
    if at is not None:
        set_clock(api, at)
    step = get_success_data(
        api.create_return_step(
            ctx["case_id"], f.return_step_payload(stage_index), ctx["doc_h_headers"]
        )
    )
    ctx.setdefault("step_ids", {})[stage_index] = step["id"]
    return step


def sign_off_stage(
    api: ApiClient,
    ctx: Dict[str, Any],
    stage_index: int,
    at: Optional[str] = None,
    symptom_score: int = 0,
    outcome: str = "PASS",
) -> Dict[str, Any]:
    """Evaluate one graduated-return stage, optionally moving the clock first."""
    if at is not None:
        set_clock(api, at)
    return get_success_data(
        api.evaluate_return_step(
            ctx["step_ids"][stage_index],
            f.evaluate_step_payload(outcome=outcome, symptom_score=symptom_score),
            ctx["doc_h_headers"],
        )
    )


def setup_case_through_stage(api: ApiClient, through_stage: int) -> Dict[str, Any]:
    """
    The diagnosed case with stages 1..``through_stage`` started and passed on the
    earliest legal instants.  Stage five's sign-off lands on
    2026-09-27T12:00:00Z, giving an earliest return instant of
    2026-09-28T12:00:00.000Z.
    """
    ctx = setup_diagnosed_case(api)
    for stage_index, start_at, signoff_at, symptom_score in CANONICAL_STAGE_TIMELINE:
        if stage_index > through_stage:
            break
        start_stage(api, ctx, stage_index, at=start_at)
        sign_off_stage(api, ctx, stage_index, at=signoff_at, symptom_score=symptom_score)
    return ctx


def setup_case_with_stage_open(api: ApiClient, stage_index: int) -> Dict[str, Any]:
    """
    The diagnosed case walked to ``stage_index - 1`` passed, with ``stage_index``
    started but not yet signed off.
    """
    ctx = setup_case_through_stage(api, stage_index - 1)
    start_at = CANONICAL_STAGE_TIMELINE[stage_index - 1][1]
    start_stage(api, ctx, stage_index, at=start_at)
    return ctx


def setup_case_all_stages_passed(api: ApiClient) -> Dict[str, Any]:
    """All five stages passed; the clock rests on the stage-five sign-off."""
    return setup_case_through_stage(api, 5)


# ─── Tier 5: final clearance and return to contact ───────────────────────────

def file_baseline_retest(
    api: ApiClient, ctx: Dict[str, Any], composite_score: int = 87, reaction_time_ms: int = 515
) -> Dict[str, Any]:
    """
    File the post-diagnosis baseline retest the player owes, proving the caller
    read the player's current version.
    """
    retest = file_baseline(
        api,
        ctx["player_id"],
        ctx["doc_h_id"],
        composite_score=composite_score,
        reaction_time_ms=reaction_time_ms,
        symptom_score=0,
    )
    ctx["retest_id"] = retest["id"]
    return retest


def request_clearance(
    api: ApiClient,
    ctx: Dict[str, Any],
    inc_clinician_id: Optional[str] = None,
    expected_case_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Request final consultant clearance against the case's current version."""
    if expected_case_version is None:
        expected_case_version = case_version(api, ctx["case_id"])
    clearance = get_success_data(
        api.request_inc_clearance(
            ctx["case_id"],
            f.clearance_request_payload(
                inc_clinician_id or ctx["inc_id"], expected_case_version
            ),
            ctx["doc_h_headers"],
        )
    )
    ctx["clearance_id"] = clearance["id"]
    return clearance


def setup_case_pending_clearance(api: ApiClient) -> Dict[str, Any]:
    """
    All five stages passed, the baseline retest on file and a PENDING consultant
    clearance assigned to the independent consultant.
    """
    ctx = setup_case_all_stages_passed(api)
    file_baseline_retest(api, ctx)
    request_clearance(api, ctx)
    return ctx


def decide_clearance(
    api: ApiClient,
    ctx: Dict[str, Any],
    decision: str = "APPROVED",
    decision_notes: str = "asymptomatic, neurocognitive scores back to baseline",
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_inc_clearance(
            ctx["clearance_id"],
            f.clearance_decision_payload(decision=decision, decision_notes=decision_notes),
            ctx["inc_headers"],
        )
    )


def setup_case_with_approved_clearance(api: ApiClient) -> Dict[str, Any]:
    """
    The case cleared by the consultant, with the clock moved to the case's own
    earliest return instant so return to contact is legal.
    """
    ctx = setup_case_pending_clearance(api)
    decide_clearance(api, ctx, "APPROVED")
    set_clock(api, "2026-09-28T12:00:00Z")
    return ctx


# ─── Compliance auditing ─────────────────────────────────────────────────────

def open_audit(
    api: ApiClient,
    club_id: str,
    case_id: Optional[str] = None,
    sideline_evaluation_id: Optional[str] = None,
    opener_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"club_id": club_id}
    if case_id is not None:
        payload["case_id"] = case_id
    if sideline_evaluation_id is not None:
        payload["sideline_evaluation_id"] = sideline_evaluation_id
    return get_success_data(
        api.create_protocol_audit(payload, opener_headers or AUDITOR_A)
    )


def issue_findings(
    api: ApiClient,
    audit_id: str,
    violation_codes: List[str],
    exposure_days: int = 0,
    issuer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Issue findings as an auditor other than the one who opened the audit."""
    return get_success_data(
        api.issue_findings(
            audit_id,
            f.findings_payload(violation_codes=violation_codes, exposure_days=exposure_days),
            issuer_headers or AUDITOR_B,
        )
    )


def respond_to_audit(
    api: ApiClient,
    audit_id: str,
    club_id: str,
    response_note: str = "the filing delay was caused by a league portal outage",
) -> Dict[str, Any]:
    return get_success_data(
        api.respond_to_audit(
            audit_id,
            f.audit_response_payload(response_note),
            make_compliance_officer_headers(club_id),
        )
    )


def close_audit(
    api: ApiClient,
    audit_id: str,
    disposition: str = "UPHELD",
    closing_note: str = "violation upheld on review",
    closer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Close an audit as a third auditor, distinct from opener and issuer."""
    return get_success_data(
        api.close_audit(
            audit_id,
            f.audit_close_payload(disposition=disposition, closing_note=closing_note),
            closer_headers or AUDITOR_C,
        )
    )


def setup_audit_with_findings(
    api: ApiClient,
    club_id: str,
    violation_codes: List[str],
    exposure_days: int = 0,
    case_id: Optional[str] = None,
    sideline_evaluation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Open an audit and issue findings on it, honouring segregation of duties."""
    audit = open_audit(
        api, club_id, case_id=case_id, sideline_evaluation_id=sideline_evaluation_id
    )
    return issue_findings(api, audit["id"], violation_codes, exposure_days)


def sanction_club(api: ApiClient, club_id: str) -> Dict[str, Any]:
    """
    Drive a clean club to SANCTIONED posture through a single findings issuance
    carrying the two heaviest violation codes, which takes compliance_score to 55.
    """
    return setup_audit_with_findings(
        api,
        club_id,
        ["UNAUTHORIZED_SAME_GAME_RETURN", "MISSING_INC_CLEARANCE"],
        exposure_days=0,
    )


def run_sweep(api: ApiClient) -> Dict[str, Any]:
    """Run the operational sweep, the only way clock-driven state moves."""
    return get_success_data(api.run_protocol_sweep(ADMIN))


# ─── Secondary actors ────────────────────────────────────────────────────────

def add_second_player(
    api: ApiClient,
    ctx: Dict[str, Any],
    full_name: str = "T Ruiz",
    jersey_number: int = 31,
    position: str = "DB",
) -> Dict[str, Any]:
    """A second player on the same club, for cross-case and conflict scenarios."""
    player = create_player(api, ctx["club_h_id"], full_name, jersey_number, position)
    ctx["player2_id"] = player["id"]
    return player


def add_second_physician(
    api: ApiClient,
    ctx: Dict[str, Any],
    full_name: str = "Dr Nakamura",
    license_number: str = "LIC-1002",
) -> Dict[str, Any]:
    """A second club-affiliated physician, for heightened-review sign-off."""
    clinician = create_club_physician(api, ctx["club_h_id"], full_name, license_number)
    ctx["doc_h2_id"] = clinician["id"]
    ctx["doc_h2_headers"] = make_club_physician_headers(clinician["id"])
    return clinician


def add_second_consultant(
    api: ApiClient,
    ctx: Dict[str, Any],
    full_name: str = "Dr Almeida",
    license_number: str = "LIC-3002",
) -> Dict[str, Any]:
    """A second independent consultant, for assignment-mismatch scenarios."""
    clinician = create_consultant(api, full_name, license_number)
    ctx["inc2_id"] = clinician["id"]
    ctx["inc2_headers"] = make_consultant_headers(clinician["id"])
    return clinician


def suspend_clinician(
    api: ApiClient, clinician_id: str, reason: str = "license board inquiry opened"
) -> Dict[str, Any]:
    return get_success_data(
        api.suspend_clinician(clinician_id, f.suspend_payload(reason), ADMIN)
    )

"""Clock, board configurations, education programs, nurses."""
from decimal import Decimal

from flask import Blueprint

import domain
import guards as G
import store
from envelope import created, listing, mark_new, ok, touch
from errors import fail
from timeutil import parse_dt

bp = Blueprint("core", __name__)

EVIDENCE_TYPES = ("DRIVER_LICENSE", "TAX_RETURN", "VOTER_REGISTRATION")
DEGREE_LEVELS = ("PN", "ADN", "BSN", "MSN")
APPROVAL_STATUSES = ("APPROVED", "PROVISIONAL", "PROBATION", "WITHDRAWN")

_BOARD_INT_FIELDS = (
    ("practice_hours_required", 0, None),
    ("practice_lookback_months", 0, None),
    ("renewal_period_months", 0, None),
    ("renewal_grace_period_days", 0, None),
    ("lapse_after_grace_days", 0, None),
    ("audit_sample_rate_bp", 0, 10000),
    ("criminal_lookback_years", 0, None),
    ("renewal_base_fee_cents", 0, None),
    ("late_fee_tier1_cents", 0, None),
    ("late_fee_tier2_cents", 0, None),
    ("reinstatement_fee_cents", 0, None),
    ("failed_audit_surcharge_cents", 0, None),
    ("max_concurrent_custodian_holds", 0, None),
    ("monitoring_clearance_gap_days", 0, None),
    ("revocation_vote_threshold_bp", 0, 10000),
    ("majority_vote_threshold_bp", 0, 10000),
)

BOARD_DEFAULTS = {
    "compact_member": False,
    "ce_hours_required": Decimal("30.00"),
    "ce_self_study_cap_hours": Decimal("12.00"),
    "ce_in_service_cap_hours": Decimal("4.00"),
    "ce_carry_over_cap_hours": Decimal("5.00"),
    "practice_hours_required": 960,
    "practice_lookback_months": 60,
    "renewal_period_months": 24,
    "renewal_grace_period_days": 60,
    "lapse_after_grace_days": 90,
    "audit_sample_rate_bp": 500,
    "criminal_lookback_years": 7,
    "disqualifying_offense_codes": ["FEL-A", "SEX-1"],
    "renewal_base_fee_cents": 12000,
    "late_fee_tier1_cents": 5000,
    "late_fee_tier2_cents": 12000,
    "reinstatement_fee_cents": 25000,
    "failed_audit_surcharge_cents": 2500,
    "phi_authorization_required": True,
    "max_concurrent_custodian_holds": 2,
    "monitoring_clearance_gap_days": 90,
    "revocation_vote_threshold_bp": 6667,
    "majority_vote_threshold_bp": 5001,
}


def _parse_residency_evidence(raw):
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "residency_evidence entries must be objects.")
        etype = entry.get("evidence_type")
        if etype not in EVIDENCE_TYPES:
            fail("ERR_INVALID_REQUEST", "residency_evidence.evidence_type must be one of %s."
                 % ", ".join(EVIDENCE_TYPES))
        code = entry.get("state_code")
        G.state_code(code, "residency_evidence.state_code")
        raw_date = entry.get("effective_date")
        try:
            parse_dt(raw_date)
        except Exception:
            fail("ERR_INVALID_REQUEST", "residency_evidence.effective_date must be an ISO 8601 instant.")
        # The client's own declaration is stored verbatim; PRD 3.1 gives the
        # server no licence to rewrite the entries it echoes back.
        out.append({"evidence_type": etype, "state_code": code, "effective_date": raw_date})
    return out


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    G.auth("SystemAdmin")
    b = G.body()
    current = G.req_datetime(b, "current_utc")
    result = domain.run_clock_sweeps(current)
    return ok(result)


# ---------------------------------------------------------------------------
# StateBoardConfig
# ---------------------------------------------------------------------------
@bp.post("/state-board-configs")
def create_board():
    G.auth("SystemAdmin")
    b = G.body()
    code = G.state_code(G.req_string(b, "state_code"), "state_code")
    name = G.req_string(b, "board_name")

    rec = store.base_fields()
    rec["state_code"] = code
    rec["board_name"] = name
    rec["compact_member"] = G.opt_bool(b, "compact_member", BOARD_DEFAULTS["compact_member"])
    rec["ce_hours_required"] = G.opt_number(
        b, "ce_hours_required", BOARD_DEFAULTS["ce_hours_required"], exclusive_minimum=Decimal("0"))
    rec["ce_self_study_cap_hours"] = G.opt_number(
        b, "ce_self_study_cap_hours", BOARD_DEFAULTS["ce_self_study_cap_hours"], minimum=Decimal("0"))
    rec["ce_in_service_cap_hours"] = G.opt_number(
        b, "ce_in_service_cap_hours", BOARD_DEFAULTS["ce_in_service_cap_hours"], minimum=Decimal("0"))
    rec["ce_carry_over_cap_hours"] = G.opt_number(
        b, "ce_carry_over_cap_hours", BOARD_DEFAULTS["ce_carry_over_cap_hours"], minimum=Decimal("0"))
    for field, lo, hi in _BOARD_INT_FIELDS:
        rec[field] = G.opt_int(b, field, BOARD_DEFAULTS[field], minimum=lo, maximum=hi)
    rec["disqualifying_offense_codes"] = G.opt_str_array(
        b, "disqualifying_offense_codes", BOARD_DEFAULTS["disqualifying_offense_codes"])
    rec["phi_authorization_required"] = G.opt_bool(
        b, "phi_authorization_required", BOARD_DEFAULTS["phi_authorization_required"])
    rec["status"] = "ACTIVE"

    for existing in store.STORE.boards.values():
        if existing["state_code"] == code:
            fail("ERR_STATE_CODE_EXISTS")

    store.STORE.boards[rec["id"]] = rec
    mark_new(rec)
    return created(rec)


@bp.get("/state-board-configs/<bid>")
def get_board(bid):
    G.auth(*G.ALL_STAFF)
    return ok(G.find("board", bid))


@bp.patch("/state-board-configs/<bid>")
def patch_board(bid):
    G.auth("SystemAdmin")
    board = G.find("board", bid)
    b = G.body()

    if G.present(b, "compact_member"):
        board["compact_member"] = G.req_bool(b, "compact_member")
    if G.present(b, "ce_hours_required"):
        board["ce_hours_required"] = G.opt_number(b, "ce_hours_required",
                                                 exclusive_minimum=Decimal("0"))
    for field in ("ce_self_study_cap_hours", "ce_in_service_cap_hours", "ce_carry_over_cap_hours"):
        if G.present(b, field):
            board[field] = G.opt_number(b, field, minimum=Decimal("0"))
    for field, lo, hi in _BOARD_INT_FIELDS:
        if G.present(b, field):
            board[field] = G.opt_int(b, field, minimum=lo, maximum=hi)
    if G.present(b, "disqualifying_offense_codes"):
        board["disqualifying_offense_codes"] = G.req_str_array(b, "disqualifying_offense_codes")
    if G.present(b, "phi_authorization_required"):
        board["phi_authorization_required"] = G.req_bool(b, "phi_authorization_required")
    if G.present(b, "board_name"):
        board["board_name"] = G.req_string(b, "board_name")
    if G.present(b, "status"):
        board["status"] = G.req_enum(b, "status", ("ACTIVE", "ARCHIVED"))

    touch(board)
    return ok(board)


@bp.get("/state-board-configs/<bid>/education-programs")
def list_board_programs(bid):
    G.auth(*G.ALL_STAFF)
    board = G.find("board", bid)
    limit, offset = G.pagination()
    rows = [p for p in store.STORE.programs.values()
            if p["state_board_config_id"] == board["id"]]
    rows = G.filter_rows(rows, {"approval_status": "approval_status",
                               "degree_level": "degree_level"})
    page, total = G.paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


@bp.get("/state-board-configs/<bid>/nurses")
def list_board_nurses(bid):
    G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember")
    board = G.find("board", bid)
    limit, offset = G.pagination()
    rows = [n for n in store.STORE.nurses.values()
            if n["home_board_config_id"] == board["id"]]
    rows = G.filter_rows(rows, {"status": "status"})
    page, total = G.paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------------------
# EducationProgram
# ---------------------------------------------------------------------------
@bp.post("/education-programs")
def create_program():
    G.auth("SystemAdmin")
    b = G.body()
    board = G.find_opt("board", b.get("state_board_config_id"))
    if board is None:
        G.req_string(b, "state_board_config_id")
    code = G.req_string(b, "program_code")
    name = G.req_string(b, "program_name")
    degree = G.req_enum(b, "degree_level", DEGREE_LEVELS)
    rate = G.req_int(b, "nclex_first_time_pass_rate_bp", minimum=0, maximum=10000)
    expires = G.req_datetime(b, "approval_expires_on")

    for existing in store.STORE.programs.values():
        if existing["state_board_config_id"] == board["id"] and existing["program_code"] == code:
            fail("ERR_PROGRAM_CODE_EXISTS")

    rec = store.base_fields()
    rec.update({
        "state_board_config_id": board["id"],
        "program_code": code,
        "program_name": name,
        "degree_level": degree,
        "nclex_first_time_pass_rate_bp": rate,
        "approval_expires_on": expires,
        "approval_status": "APPROVED",
    })
    store.STORE.programs[rec["id"]] = rec
    mark_new(rec)
    return created(rec)


@bp.get("/education-programs/<pid>")
def get_program(pid):
    G.auth(*G.ALL_STAFF)
    return ok(G.find("program", pid))


@bp.patch("/education-programs/<pid>")
def patch_program(pid):
    G.auth("SystemAdmin")
    program = G.find("program", pid)
    b = G.body()
    if G.present(b, "approval_status"):
        program["approval_status"] = G.req_enum(b, "approval_status", APPROVAL_STATUSES)
    if G.present(b, "approval_expires_on"):
        program["approval_expires_on"] = G.req_datetime(b, "approval_expires_on")
    if G.present(b, "nclex_first_time_pass_rate_bp"):
        program["nclex_first_time_pass_rate_bp"] = G.req_int(
            b, "nclex_first_time_pass_rate_bp", minimum=0, maximum=10000)
    if G.present(b, "program_name"):
        program["program_name"] = G.req_string(b, "program_name")
    touch(program)
    return ok(program)


# ---------------------------------------------------------------------------
# Nurse
# ---------------------------------------------------------------------------
@bp.post("/nurses")
def create_nurse():
    G.auth("LicensureAnalyst")
    b = G.body()
    board = G.find_opt("board", b.get("home_board_config_id"))
    if board is None:
        G.req_string(b, "home_board_config_id")
    full_name = G.req_string(b, "full_name")
    birth_year = G.req_int(b, "birth_year")
    ssn_last4 = G.req_string(b, "ssn_last4")
    declared = G.state_code(G.req_string(b, "declared_primary_state"), "declared_primary_state")
    evidence = _parse_residency_evidence(G.opt_obj_array(b, "residency_evidence", []) or [])

    rec = store.base_fields()
    rec.update({
        "home_board_config_id": board["id"],
        "full_name": full_name,
        "birth_year": birth_year,
        "ssn_last4": ssn_last4,
        "declared_primary_state": declared,
        "residency_evidence": evidence,
        "fee_credit_cents": 0,
        "fee_paid_total_cents": 0,
        "prior_discipline_count": 0,
        "atd_participation_count": 0,
        "status": "ACTIVE",
    })
    store.STORE.nurses[rec["id"]] = rec
    mark_new(rec)
    return created(rec)


@bp.get("/nurses/<nid>")
def get_nurse(nid):
    user_id, role = G.auth(*G.ROLES)
    nurse = G.find("nurse", nid)
    G.own_nurse(role, user_id, nurse["id"])
    return ok(nurse)


@bp.patch("/nurses/<nid>")
def patch_nurse(nid):
    user_id, role = G.auth("LicensureAnalyst", "Applicant")
    nurse = G.find("nurse", nid)
    b = G.body()
    board = G.find_opt("board", b.get("home_board_config_id"))
    G.own_nurse(role, user_id, nurse["id"])

    if G.present(b, "declared_primary_state"):
        nurse["declared_primary_state"] = G.state_code(
            G.req_string(b, "declared_primary_state"), "declared_primary_state")
    if G.present(b, "residency_evidence"):
        nurse["residency_evidence"] = _parse_residency_evidence(
            G.req_obj_array(b, "residency_evidence"))
    if G.present(b, "full_name"):
        nurse["full_name"] = G.req_string(b, "full_name")
    if board is not None:
        nurse["home_board_config_id"] = board["id"]

    touch(nurse)
    return ok(nurse)

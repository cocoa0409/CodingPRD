"""Shared helpers: datetime parsing, posture ledger, scorecards, cycle tallies."""
import math
import re
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from db import store, new_id, now_iso
from errors import ApiError, invalid_request, not_found

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso(value, field):
    """Parse an ISO 8601 timestamp into an aware datetime (UTC assumed when naive)."""
    if not isinstance(value, str):
        raise invalid_request(f"Field {field} must be an ISO 8601 timestamp string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise invalid_request(f"Field {field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    """Parse a YYYY-MM-DD date."""
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        raise invalid_request(f"Field {field} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise invalid_request(f"Field {field} is not a valid date")


def round4(value):
    """Round a Decimal to 4 decimal places, half up. Returns float for JSON."""
    q = Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def round0(value):
    """Round a Decimal to integer cents, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


# ---------------------------------------------------------------- posture ---

def recompute_program_posture(program):
    """Recompute penalties_outstanding_cents and posture from the penalty ledger."""
    total = 0
    for p in store.penalties.values():
        if p["program_id"] != program["id"]:
            continue
        if p["status"] in ("ASSESSED", "APPEALED", "UPHELD"):
            total += p["amount_cents"]
        elif p["status"] == "REDUCED":
            total += p["reduced_amount_cents"] if p["reduced_amount_cents"] is not None else 0
    program["penalties_outstanding_cents"] = total
    posture = "RESTRICTED" if total >= program["penalty_threshold_cents"] else "OPEN"
    if program["posture"] != posture:
        program["posture"] = posture
    touch(program)


# --------------------------------------------------------------- scorecard ---

def get_scorecard(provider_id, cycle_id):
    for sc in store.scorecards.values():
        if sc["provider_id"] == provider_id and sc["cycle_id"] == cycle_id:
            return sc
    return None


def ensure_scorecard(provider_id, cycle_id):
    sc = get_scorecard(provider_id, cycle_id)
    if sc is None:
        provider = store.providers.get(provider_id)
        program_id = provider["program_id"] if provider else None
        sc = {
            "id": new_id(),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "version": 1,
            "program_id": program_id,
            "cycle_id": cycle_id,
            "provider_id": provider_id,
            "run_count": 0,
            "fatal_finding_count": 0,
            "error_rate": 0.0,
            "tier": "GREEN",
            "status": "OPEN",
        }
        store.scorecards[sc["id"]] = sc
    return sc


def recompute_scorecard(sc):
    provider = store.providers.get(sc["provider_id"])
    program = store.programs.get(provider["program_id"]) if provider else None
    denom = max(sc["run_count"], 1)
    sc["error_rate"] = round4(Decimal(sc["fatal_finding_count"]) / Decimal(denom))
    if program is not None:
        rate = Decimal(str(sc["error_rate"]))
        if rate >= Decimal(str(program["provider_red_threshold"])):
            sc["tier"] = "RED"
        elif rate >= Decimal(str(program["provider_yellow_threshold"])):
            sc["tier"] = "YELLOW"
        else:
            sc["tier"] = "GREEN"
    touch(sc)
    # Provider.quality_tier mirrors the most recently updated scorecard
    if provider is not None:
        provider["quality_tier"] = sc["tier"]
        touch(provider)


# ------------------------------------------------------------- cycle talies ---

def recompute_cycle_tallies(cycle):
    """Refresh derived tallies. The cycle's OCC `version` pins extension-request
    serialization, so silent tally recomputation must NOT advance it — only the
    explicit cycle mutations (extension lifecycle, close, compute-risk-scores) do."""
    intake = 0
    net_count = 0
    net_paid = 0
    for e in store.encounters.values():
        if e.get("attributed_cycle_id") != cycle["id"]:
            continue
        if e["status"] != "SUPERSEDED":
            intake += 1
        if e["status"] == "ACKNOWLEDGED":
            net_count += 1
            net_paid += e["paid_amount_cents"]
    cycle["intake_encounter_count"] = intake
    cycle["net_accepted_encounter_count"] = net_count
    cycle["net_accepted_paid_cents"] = net_paid
    cycle["updated_at"] = now_iso()


def enrolled_overlapping_members(program_id, window_start_dt, window_end_dt):
    """Members whose [enrolled_from, enrolled_to] overlaps [window_start, window_end) by >= 1 day."""
    ws = window_start_dt.date()
    we = window_end_dt.date()
    result = []
    for m in store.members.values():
        if m["program_id"] != program_id:
            continue
        start = m["_enrolled_from"]
        end = m["_enrolled_to"]  # None => open-ended
        # overlap: start < we and (end is None or end >= ws)
        if start < we and (end is None or end >= ws):
            result.append(m)
    return result


# ------------------------------------------------------------- validations ---

DIAG_RE = re.compile(r"^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$")
PROC_RE = re.compile(r"^[A-Z0-9]{5}$")


def validate_lines(lines):
    """Stage-3 structural validation of line payloads (types, presence, non-negative)."""
    if not isinstance(lines, list):
        raise invalid_request("Field lines must be an array")
    seen_numbers = set()
    for line in lines:
        if not isinstance(line, dict):
            raise invalid_request("Each line must be an object")
        for f in ("line_number", "procedure_code", "units", "billed_amount_cents", "paid_amount_cents"):
            if f not in line or line[f] is None:
                raise invalid_request(f"Line missing required field: {f}")
        ln = line["line_number"]
        if isinstance(ln, bool) or not isinstance(ln, int) or ln < 1:
            raise invalid_request("line_number must be a positive integer")
        if ln in seen_numbers:
            raise invalid_request("line_number must be unique within the encounter")
        seen_numbers.add(ln)
        pc = line["procedure_code"]
        if not isinstance(pc, str):
            raise invalid_request("procedure_code must be a string")
        modifiers = line.get("modifiers", [])
        if modifiers is None:
            modifiers = []
        if not isinstance(modifiers, list) or len(modifiers) > 4:
            raise invalid_request("modifiers must be an array of at most 4 entries")
        for num_field in ("units", "billed_amount_cents", "paid_amount_cents"):
            v = line[num_field]
            if isinstance(v, bool) or not isinstance(v, int):
                raise invalid_request(f"Line {num_field} must be an integer")
            if v < 0:
                raise invalid_request(f"Line {num_field} must not be negative")


def validate_line_sanity(lines):
    """Stage-17 fiscal line sanity: units >= 1 and 0 <= paid <= billed."""
    for line in lines:
        if line["units"] < 1 or line["paid_amount_cents"] > line["billed_amount_cents"]:
            raise ApiError(
                "ERR_PAID_EXCEEDS_BILLED",
                "A line has paid_amount_cents > billed_amount_cents, or units < 1",
                422,
            )


def validate_header_lines(paid_amount_cents, lines):
    # Fires when the header exceeds the sum of the lines' paid amounts.
    total = sum(l["paid_amount_cents"] for l in lines)
    if paid_amount_cents > total:
        raise ApiError(
            "ERR_HEADER_LINES_PAID_MISMATCH",
            "Header paid_amount_cents != sum of lines' paid_amount_cents",
            422,
        )


def attribute_cycle(program_id, service_from_date):
    """Find the OPEN cycle of program whose half-open window contains service_from_date."""
    for c in store.cycles.values():
        if c["program_id"] != program_id:
            continue
        if c["status"] != "OPEN":
            continue
        ws = c["_window_start_at"]
        we = c["_window_end_at"]
        d = datetime(service_from_date.year, service_from_date.month, service_from_date.day, tzinfo=timezone.utc)
        if ws <= d < we:
            return c
    raise ApiError(
        "ERR_NO_CYCLE_FOR_SERVICE_DATE",
        "No OPEN cycle window of the program contains service_from_date",
        422,
    )


def check_ref_unique(program_id, submitter_id, encounter_ref, exclude_id=None):
    """encounter_ref unique per (program_id, submitter scope) among non-SUPERSEDED/VOIDED."""
    for e in store.encounters.values():
        if exclude_id is not None and e["id"] == exclude_id:
            continue
        if e["program_id"] != program_id:
            continue
        if e.get("submitter_id") != submitter_id:
            continue
        if e["status"] in ("SUPERSEDED", "VOIDED"):
            continue
        if e["encounter_ref"] == encounter_ref:
            raise ApiError(
                "ERR_DUPLICATE_ENCOUNTER_REF",
                "encounter_ref already used within (program, submitter scope)",
                409,
            )


def run_edits(encounter):
    """Run companion-guide edits over an encounter. Returns list of (edit_code, tier, severity, field_path, message)."""
    findings = []
    sfd = encounter["_service_from_date"]
    std = encounter["_service_to_date"]

    # Syntax tier
    if std < sfd:
        findings.append(("E101_SERVICE_DATE_ORDER", "SYNTAX", "FATAL", "service_to_date",
                         "service_to_date precedes service_from_date"))
    for code in encounter["diagnosis_codes"]:
        if not isinstance(code, str) or not DIAG_RE.match(code):
            findings.append(("E102_DIAG_FORMAT", "SYNTAX", "FATAL", "diagnosis_codes",
                             f"Diagnosis code {code!r} is not a valid ICD-10 format"))
            break

    # Referential tier
    member = store.members.get(encounter["member_id"])
    if member is not None:
        enrolled_from = member["_enrolled_from"]
        enrolled_to = member["_enrolled_to"]
        sd = sfd
        if sd < enrolled_from or (enrolled_to is not None and sd > enrolled_to):
            findings.append(("E201_MEMBER_NOT_ELIGIBLE", "REFERENTIAL", "FATAL", "service_from_date",
                             "Member not eligible on the service date"))
    provider = store.providers.get(encounter["provider_id"])
    if provider is not None and provider["contract_status"] != "ACTIVE":
        findings.append(("E202_PROVIDER_INACTIVE", "REFERENTIAL", "FATAL", "provider_id",
                         "Rendering provider contract is not active"))

    # Business tier
    # E301: a corrected encounter (one that has already been through at least one
    # prior edit run) is a duplicate suspect of its own earlier submission; also
    # flag true cross-encounter duplicates on member/provider/service date.
    dup_suspect = encounter["validation_run_seq"] > 1
    if not dup_suspect:
        for other in store.encounters.values():
            if other["id"] == encounter["id"]:
                continue
            if other["program_id"] != encounter["program_id"]:
                continue
            if other["status"] in ("SUPERSEDED", "VOIDED"):
                continue
            if other["id"] == encounter.get("replaces_encounter_id"):
                continue
            if (other["member_id"] == encounter["member_id"]
                    and other["provider_id"] == encounter["provider_id"]
                    and other["_service_from_date"] == encounter["_service_from_date"]):
                dup_suspect = True
                break
    if dup_suspect:
        findings.append(("E301_DUPLICATE_SUSPECT", "BUSINESS", "WARN", "service_from_date",
                         "Possible duplicate encounter for same member/provider/date"))

    if any(l["units"] > 90 for l in encounter["_lines"]):
        findings.append(("E302_UNITS_HIGH", "BUSINESS", "WARN", "lines.units",
                         "Line units unusually high"))

    return findings


def persist_findings(encounter, run_seq, edit_results):
    for (code, tier, severity, path, msg) in edit_results:
        fid = new_id()
        store.findings[fid] = {
            "id": fid,
            "created_at": now_iso(),
            "encounter_id": encounter["id"],
            "run_seq": run_seq,
            "edit_code": code,
            "tier": tier,
            "severity": severity,
            "origin": "MCO_EDIT",
            "field_path": path,
            "message": msg,
        }


def run_validation(encounter):
    """Increment run_seq, persist findings, update scorecard. Returns fatal count."""
    encounter["validation_run_seq"] += 1
    run_seq = encounter["validation_run_seq"]
    results = run_edits(encounter)
    persist_findings(encounter, run_seq, results)
    fatal_count = sum(1 for r in results if r[2] == "FATAL")
    sc = ensure_scorecard(encounter["provider_id"], encounter["attributed_cycle_id"])
    sc["run_count"] += 1
    sc["fatal_finding_count"] += fatal_count
    recompute_scorecard(sc)
    return fatal_count


def encounter_view(e, include_lines=False):
    out = {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "program_id": e["program_id"],
        "member_id": e["member_id"],
        "provider_id": e["provider_id"],
        "submitter_id": e.get("submitter_id"),
        "attributed_cycle_id": e.get("attributed_cycle_id"),
        "batch_id": e.get("batch_id"),
        "replaces_encounter_id": e.get("replaces_encounter_id"),
        "encounter_ref": e["encounter_ref"],
        "service_from_date": e["service_from_date"],
        "service_to_date": e["service_to_date"],
        "place_of_service": e["place_of_service"],
        "diagnosis_codes": list(e["diagnosis_codes"]),
        "paid_amount_cents": e["paid_amount_cents"],
        "correction_sequence": e["correction_sequence"],
        "validation_run_seq": e["validation_run_seq"],
        "status": e["status"],
        "lines": [line_view(l) for l in e["_lines"]],
    }
    return out


def line_view(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "encounter_id": l["encounter_id"],
        "line_number": l["line_number"],
        "procedure_code": l["procedure_code"],
        "modifiers": list(l["modifiers"]),
        "units": l["units"],
        "billed_amount_cents": l["billed_amount_cents"],
        "paid_amount_cents": l["paid_amount_cents"],
    }


def finding_view(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "encounter_id": f["encounter_id"],
        "run_seq": f["run_seq"],
        "edit_code": f["edit_code"],
        "tier": f["tier"],
        "severity": f["severity"],
        "origin": f["origin"],
        "field_path": f["field_path"],
        "message": f["message"],
    }

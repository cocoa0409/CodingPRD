"""PRD 3.3 to 3.5 and 3.7 - the artwork version lifecycle."""
from flask import Blueprint, request

import calc
from cascade import current_run_checks, recompute_compliance
from core import db, new_row, now, now_iso, parse_dt, rows, touch
from errors import fail, invalid
from http_util import (
    ALL_ROLES,
    auth,
    body_fields,
    created,
    filter_exists,
    load,
    need_array,
    need_enum,
    need_int,
    need_object,
    need_string,
    ok,
    paginate,
    raw_body,
)
from serialize import version_json

bp = Blueprint("versions", __name__)


def _resolve_claim_ids(raw):
    """Existence resolution for a body claim array (PRD 2.5)."""
    values = raw.get("claim_ids")
    if not isinstance(values, list):
        return
    for entry in values:
        if isinstance(entry, str) and entry:
            load("claims", entry)


def _validate_claim_ids(body):
    if "claim_ids" not in body or body["claim_ids"] is None:
        return []
    values = need_array(body, "claim_ids", 0, 8, unique=True)
    for entry in values:
        if not isinstance(entry, str) or not entry.strip():
            invalid("claim_ids entries must be non-empty strings")
    return list(values)


def _asset_of(version):
    return db.assets[version["artwork_asset_id"]]


def _brief_of(version):
    return db.briefs[_asset_of(version)["brief_id"]]


@bp.route("/artwork-assets/<asset_id>/versions", methods=["POST"])
def create_version(asset_id):
    user_id, _role = auth(["PackagingCoordinator"])
    asset = load("assets", asset_id)
    raw = raw_body()
    _resolve_claim_ids(raw)
    supersedes_ref = raw.get("supersedes_version_id")
    predecessor = None
    if isinstance(supersedes_ref, str) and supersedes_ref:
        predecessor = load("versions", supersedes_ref)

    body = body_fields(
        [
            "expected_artwork_asset_version",
            "reason_for_change_code",
            "change_description",
            "mandatory_elements",
        ],
        ["claim_ids", "supersedes_version_id"],
    )
    expected = need_int(body, "expected_artwork_asset_version", 0)
    reason = need_enum(body, "reason_for_change_code", calc.REASON_FOR_CHANGE_CODES)
    description = need_string(body, "change_description", 10, 500)
    elements = need_object(body, "mandatory_elements")
    claim_ids = _validate_claim_ids(body)
    if "supersedes_version_id" in body and body["supersedes_version_id"] is not None:
        if not isinstance(body["supersedes_version_id"], str):
            invalid("supersedes_version_id must be a string")

    if expected != asset["version"]:
        fail(
            "ERR_STALE_ASSET_VERSION",
            "expected_artwork_asset_version %s does not match the asset version %s"
            % (expected, asset["version"]),
        )

    if predecessor is not None and predecessor["artwork_asset_id"] != asset["id"]:
        fail(
            "ERR_SUPERSEDES_VERSION_MISMATCH",
            "supersedes_version_id names a version of another asset",
        )

    asset["version_counter"] = asset["version_counter"] + 1
    version_no = asset["version_counter"]
    touch(asset)

    row = new_row(
        "versions",
        {
            "artwork_asset_id": asset["id"],
            "version_no": version_no,
            "state": "DRAFT",
            "reason_for_change_code": reason,
            "change_description": description,
            "mandatory_elements": elements,
            "claim_ids": claim_ids,
            "supersedes_version_id": predecessor["id"] if predecessor is not None else None,
            "author_user_id": user_id,
            "check_run_no": 0,
            "revision_cycle_count": 0,
            "route_count": 0,
            "requires_reverification": False,
            "open_condition_codes": [],
            "pinned_claim_snapshot": [],
            "compliance_score": None,
            "failed_element_count": 0,
            "waived_element_count": 0,
            "approved_at": None,
            "released_at": None,
            "obsoleted_at": None,
        },
    )
    return created(version_json(row))


@bp.route("/artwork-versions/<version_id>", methods=["GET"])
def get_version(version_id):
    auth(ALL_ROLES)
    return ok(version_json(load("versions", version_id)))


@bp.route("/artwork-versions", methods=["GET"])
def list_versions():
    auth(ALL_ROLES)
    asset_id = filter_exists("assets", "artwork_asset_id")
    supersedes_id = filter_exists("versions", "supersedes_version_id")
    items = rows("versions")
    if asset_id:
        items = [v for v in items if v["artwork_asset_id"] == asset_id]
    if supersedes_id:
        items = [v for v in items if v.get("supersedes_version_id") == supersedes_id]
    state = request.args.get("state")
    if state:
        items = [v for v in items if v["state"] == state]
    items = sorted(items, key=lambda v: (v["version_no"], v["created_at"], v["_seq"]))
    return paginate(items, version_json)


@bp.route("/artwork-versions/<version_id>", methods=["PATCH"])
def patch_version(version_id):
    auth(["PackagingCoordinator"])
    version = load("versions", version_id)
    raw = raw_body()
    _resolve_claim_ids(raw)
    body = body_fields(
        [], ["mandatory_elements", "claim_ids", "reason_for_change_code", "change_description"]
    )
    updates = {}
    if "mandatory_elements" in body:
        updates["mandatory_elements"] = need_object(body, "mandatory_elements")
    if "claim_ids" in body:
        updates["claim_ids"] = _validate_claim_ids(body)
    if "reason_for_change_code" in body:
        updates["reason_for_change_code"] = need_enum(
            body, "reason_for_change_code", calc.REASON_FOR_CHANGE_CODES
        )
    if "change_description" in body:
        updates["change_description"] = need_string(body, "change_description", 10, 500)

    asset = _asset_of(version)
    if version["state"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail("ERR_VERSION_STATE_INVALID", "only a DRAFT or REVISION_REQUESTED version may be edited")
    if asset["obsolescence_state"] == "SUPERSEDED":
        fail("ERR_VERSION_STATE_INVALID", "the owning asset is already SUPERSEDED")

    # Editing is deliberately inert with respect to compliance (PRD 3.3).
    version.update(updates)
    touch(version)
    return ok(version_json(version))


@bp.route("/artwork-versions/<version_id>/verify-elements", methods=["POST"])
def verify_elements(version_id):
    auth(["PackagingCoordinator"])
    version = load("versions", version_id)
    body = body_fields([], ["verification_note"])
    note = body.get("verification_note")
    if note is not None and not isinstance(note, str):
        invalid("verification_note must be a string")

    asset = _asset_of(version)
    brief = _brief_of(version)
    state = version["state"]
    if asset["obsolescence_state"] == "SUPERSEDED":
        fail("ERR_VERSION_STATE_INVALID", "the owning asset is already SUPERSEDED")
    if state == "APPROVED":
        if not version["requires_reverification"]:
            fail(
                "ERR_VERSION_STATE_INVALID",
                "an APPROVED version may only be re-verified while requires_reverification is true",
            )
    elif state not in ("DRAFT", "ELEMENTS_VERIFIED", "REVISION_REQUESTED"):
        fail("ERR_VERSION_STATE_INVALID", "verification is not admissible from %s" % state)

    # Every run is a clean slate (PRD 3.4).
    for row in [r for r in rows("element_checks") if r["artwork_version_id"] == version["id"]]:
        db.element_checks.pop(row["id"], None)

    version["check_run_no"] = version["check_run_no"] + 1
    run_no = version["check_run_no"]
    required = brief["required_element_codes"]
    for code in calc.ELEMENT_ORDER:
        if code not in required:
            continue
        result, detail, deduction = calc.evaluate_element(
            code, version["mandatory_elements"], brief["regulatory_scheme"]
        )
        new_row(
            "element_checks",
            {
                "artwork_version_id": version["id"],
                "check_run_no": run_no,
                "element_code": code,
                "severity": calc.ELEMENT_SEVERITY[code],
                "result": result,
                "detail": detail,
                "deduction_points": deduction,
                "waived_by_user_id": None,
                "waiver_justification": None,
            },
        )

    recompute_compliance(version)
    version["verification_note"] = note
    if state == "DRAFT":
        version["state"] = "ELEMENTS_VERIFIED"
    elif state == "APPROVED":
        version["requires_reverification"] = False
    touch(version)
    return ok(version_json(version))


@bp.route("/artwork-versions/<version_id>/revise", methods=["POST"])
def revise_version(version_id):
    auth(["PackagingCoordinator"])
    version = load("versions", version_id)
    body = body_fields([], ["revise_note"])
    note = body.get("revise_note")
    if note is not None and not isinstance(note, str):
        invalid("revise_note must be a string")

    if version["state"] != "REVISION_REQUESTED":
        fail("ERR_VERSION_STATE_INVALID", "only a REVISION_REQUESTED version may be re-opened")
    if version["revision_cycle_count"] >= calc.REVISION_CYCLE_CAP:
        fail(
            "ERR_REVISION_CYCLE_CAP_EXCEEDED",
            "the version has already been bounced back from review %d times"
            % calc.REVISION_CYCLE_CAP,
        )

    # Existing element verdict rows survive until the next verification run (PRD 3.3).
    version["state"] = "DRAFT"
    version["revise_note"] = note
    touch(version)
    return ok(version_json(version))


@bp.route("/artwork-versions/<version_id>/submit", methods=["POST"])
def submit_version(version_id):
    auth(["PackagingCoordinator"])
    version = load("versions", version_id)
    body = body_fields([], ["submit_note"])
    note = body.get("submit_note")
    if note is not None and not isinstance(note, str):
        invalid("submit_note must be a string")

    asset = _asset_of(version)
    brief = _brief_of(version)

    if version["state"] != "ELEMENTS_VERIFIED":
        fail("ERR_VERSION_STATE_INVALID", "only an ELEMENTS_VERIFIED version may be submitted")
    if asset["obsolescence_state"] == "SUPERSEDED":
        fail("ERR_VERSION_STATE_INVALID", "the owning asset is already SUPERSEDED")
    if brief["status"] != "APPROVED":
        fail("ERR_BRIEF_NOT_APPROVED", "the owning brief is not APPROVED")

    for row in current_run_checks(version):
        if row["result"] == "FAIL":
            fail(
                "ERR_MANDATORY_ELEMENT_FAILED",
                "element %s of the current run carries a FAIL" % row["element_code"],
            )

    score = version.get("compliance_score")
    if score is None or score < calc.COMPLIANCE_SCORE_FLOOR:
        fail(
            "ERR_COMPLIANCE_SCORE_BELOW_THRESHOLD",
            "compliance_score must be at least %s" % calc.COMPLIANCE_SCORE_FLOOR,
        )

    claims = [db.claims[claim_id] for claim_id in version["claim_ids"]]
    for claim in claims:
        if claim["legal_status"] != "CLEARED":
            fail("ERR_CLAIM_NOT_CLEARED", "claim %s is not CLEARED" % claim["claim_code"])
    clock = now()
    for claim in claims:
        cleared_from = parse_dt(claim["cleared_from_utc"])
        cleared_until = parse_dt(claim["cleared_until_utc"])
        if cleared_from is None or cleared_until is None:
            fail("ERR_CLAIM_CLEARANCE_EXPIRED", "claim %s has no clearance window" % claim["id"])
        if not (clock >= cleared_from and clock < cleared_until):
            fail(
                "ERR_CLAIM_CLEARANCE_EXPIRED",
                "claim %s is outside its clearance window" % claim["claim_code"],
            )

    if version["revision_cycle_count"] >= calc.REVISION_CYCLE_CAP:
        fail(
            "ERR_REVISION_CYCLE_CAP_EXCEEDED",
            "the revision cycle cap of %d has been reached" % calc.REVISION_CYCLE_CAP,
        )

    for claim in claims:
        if claim["market_code"] != asset["market_code"]:
            fail(
                "ERR_CLAIM_MARKET_MISMATCH",
                "claim %s serves market %s, not %s"
                % (claim["claim_code"], claim["market_code"], asset["market_code"]),
            )

    version["route_count"] = version["route_count"] + 1
    route = new_row(
        "routes",
        {
            "artwork_version_id": version["id"],
            "route_no": version["route_count"],
            "status": "IN_PROGRESS",
            "current_stage_no": 1,
            "stage_plan": [dict(stage) for stage in calc.STAGE_PLAN],
            "conditional_count": 0,
            "submit_note": note,
            "completed_at": None,
        },
    )
    for stage in calc.STAGE_PLAN:
        for discipline in stage["disciplines"]:
            new_row(
                "tasks",
                {
                    "review_route_id": route["id"],
                    "artwork_version_id": version["id"],
                    "discipline": discipline,
                    "mode": stage["mode"],
                    "stage_no": stage["stage_no"],
                    "is_active": stage["stage_no"] == 1,
                    "decision": "PENDING",
                    "comment": None,
                    "condition_code": None,
                    "decided_by_user_id": None,
                    "decided_at": None,
                },
            )

    version["state"] = "IN_REVIEW"
    version["submit_note"] = note
    touch(version)
    return ok(version_json(version))


@bp.route("/artwork-versions/<version_id>/release-to-print", methods=["POST"])
def release_version(version_id):
    auth(["PackagingCoordinator"])
    version = load("versions", version_id)
    body = body_fields([], ["release_note"])
    note = body.get("release_note")
    if note is not None and not isinstance(note, str):
        invalid("release_note must be a string")

    if version["state"] != "APPROVED":
        fail("ERR_VERSION_STATE_INVALID", "only an APPROVED version may be released to print")

    clock = now()
    for entry in version["pinned_claim_snapshot"]:
        cleared_until = parse_dt(entry.get("cleared_until_utc"))
        if cleared_until is None or not cleared_until > clock:
            fail(
                "ERR_CLAIM_CLEARANCE_EXPIRED",
                "pinned claim %s has lapsed since approval" % entry.get("claim_code"),
            )

    if version["requires_reverification"]:
        fail("ERR_REVERIFICATION_REQUIRED", "a fresh verification run is required before release")

    approved_proofs = [
        p
        for p in rows("proofs")
        if p["artwork_version_id"] == version["id"] and p["proof_state"] == "PROOF_APPROVED"
    ]
    if not approved_proofs:
        fail("ERR_PROOF_NOT_APPROVED", "no PROOF_APPROVED proof exists for this version")

    version["state"] = "RELEASED_TO_PRINT"
    version["released_at"] = now_iso()
    version["release_note"] = note
    touch(version)
    return ok(version_json(version))

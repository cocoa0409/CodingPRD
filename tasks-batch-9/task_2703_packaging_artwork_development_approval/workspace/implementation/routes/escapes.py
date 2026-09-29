"""PRD 3.9 - error escape investigation, cost recovery and vendor standing."""
from flask import Blueprint, request

import calc
from cascade import apply_settlement_penalty
from core import db, dec, new_row, now_iso, rows, touch
from errors import fail, invalid
from http_util import (
    ALL_ROLES,
    auth,
    body_fields,
    created,
    filter_exists,
    load,
    need_enum,
    need_int,
    need_nonempty,
    need_number,
    ok,
    paginate,
    raw_body,
)
from serialize import escape_json

bp = Blueprint("escapes", __name__)


def _asset_of(escape):
    version = db.versions[escape["artwork_version_id"]]
    return db.assets[version["artwork_asset_id"]]


@bp.route("/error-escapes", methods=["POST"])
def create_escape():
    auth(["QualityReviewer"])
    raw = raw_body()
    version_ref = raw.get("artwork_version_id")
    if isinstance(version_ref, str) and version_ref:
        load("versions", version_ref)
    printer_ref = raw.get("printer_id")
    if isinstance(printer_ref, str) and printer_ref:
        load("printers", printer_ref)

    body = body_fields(
        ["artwork_version_id", "printer_id", "defect_code", "discovered_stage", "units_affected"],
        ["discovery_note"],
    )
    need_nonempty(body, "artwork_version_id")
    need_nonempty(body, "printer_id")
    defect_code = need_enum(body, "defect_code", calc.DEFECT_CODES)
    discovered_stage = need_enum(body, "discovered_stage", calc.DISCOVERED_STAGES)
    units_affected = need_int(body, "units_affected", 1)
    note = body.get("discovery_note")
    if note is not None and not isinstance(note, str):
        invalid("discovery_note must be a string")

    version = load("versions", body["artwork_version_id"])
    printer = load("printers", body["printer_id"])

    if version["state"] not in ("RELEASED_TO_PRINT", "OBSOLETE_PENDING", "OBSOLETE"):
        fail(
            "ERR_VERSION_STATE_INVALID",
            "only a version that reached print may carry an escape",
        )

    row = new_row(
        "escapes",
        {
            "artwork_version_id": version["id"],
            "printer_id": printer["id"],
            "defect_code": defect_code,
            "discovered_stage": discovered_stage,
            "units_affected": units_affected,
            "discovery_note": note,
            "state": "OPEN",
            "investigation_fee_cents": calc.investigation_fee(discovered_stage),
            "root_cause_party": None,
            "printer_share_pct": None,
            "investigation_note": None,
            "provisional_recovery_cents": None,
            "liability_cap_applied": False,
            "dispute_reason": None,
            "dispute_count": 0,
            "actual_reprint_cost_cents": None,
            "actual_scrap_cost_cents": None,
            "actual_expedite_freight_cents": None,
            "final_recovery_cents": None,
            "recovery_variance_cents": None,
            "resolution": None,
            "settlement_note": None,
            "settled_at": None,
        },
    )
    touch(printer)
    return created(escape_json(row))


@bp.route("/error-escapes/<escape_id>", methods=["GET"])
def get_escape(escape_id):
    auth(ALL_ROLES)
    return ok(escape_json(load("escapes", escape_id)))


@bp.route("/error-escapes", methods=["GET"])
def list_escapes():
    auth(ALL_ROLES)
    version_id = filter_exists("versions", "artwork_version_id")
    printer_id = filter_exists("printers", "printer_id")
    items = rows("escapes")
    if version_id:
        items = [e for e in items if e["artwork_version_id"] == version_id]
    if printer_id:
        items = [e for e in items if e["printer_id"] == printer_id]
    state = request.args.get("state")
    if state:
        items = [e for e in items if e["state"] == state]
    party = request.args.get("root_cause_party")
    if party:
        items = [e for e in items if e.get("root_cause_party") == party]
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    return paginate(items, escape_json)


@bp.route("/error-escapes/<escape_id>/root-cause", methods=["POST"])
def assign_root_cause(escape_id):
    auth(["QualityReviewer"])
    escape = load("escapes", escape_id)
    body = body_fields(["root_cause_party", "printer_share_pct", "investigation_note"])
    party = need_enum(body, "root_cause_party", calc.ROOT_CAUSE_PARTIES)
    share = need_number(body, "printer_share_pct", 0, 1)
    note = body.get("investigation_note")
    if not isinstance(note, str) or not note.strip():
        invalid("investigation_note is required and must be non-empty")

    if escape["state"] not in ("OPEN", "DISPUTED"):
        fail("ERR_ESCAPE_STATE_INVALID", "apportionment is admissible from OPEN or DISPUTED only")

    share = dec(share)
    if party == "PRINTER" and share != dec("1.00"):
        fail("ERR_SHARE_INCONSISTENT_WITH_PARTY", "a PRINTER root cause requires a share of 1.00")
    if party in ("BRAND", "AGENCY") and share != dec("0.00"):
        fail(
            "ERR_SHARE_INCONSISTENT_WITH_PARTY",
            "a %s root cause requires a share of 0.00" % party,
        )
    if party == "SHARED" and not (dec("0.00") < share < dec("1.00")):
        fail(
            "ERR_SHARE_INCONSISTENT_WITH_PARTY",
            "a SHARED root cause requires a share strictly between 0.00 and 1.00",
        )

    revising = escape["state"] == "DISPUTED"
    escape["root_cause_party"] = party
    escape["printer_share_pct"] = share
    escape["investigation_note"] = note
    if revising:
        # The prior claim basis has been withdrawn (PRD 3.9).
        escape["provisional_recovery_cents"] = None
        escape["liability_cap_applied"] = False
    escape["state"] = "ROOT_CAUSE_ASSIGNED"
    touch(escape)
    return ok(escape_json(escape))


@bp.route("/error-escapes/<escape_id>/recovery-claim", methods=["POST"])
def recovery_claim(escape_id):
    auth(["QualityReviewer"])
    escape = load("escapes", escape_id)
    body = body_fields(["expected_error_escape_version"])
    expected = need_int(body, "expected_error_escape_version", 0)

    if expected != escape["version"]:
        fail(
            "ERR_STALE_ESCAPE_VERSION",
            "expected_error_escape_version %s does not match the escape version %s"
            % (expected, escape["version"]),
        )
    if escape["state"] != "ROOT_CAUSE_ASSIGNED":
        fail("ERR_ESCAPE_STATE_INVALID", "a recovery claim requires the ROOT_CAUSE_ASSIGNED state")

    asset = _asset_of(escape)
    printer = db.printers[escape["printer_id"]]
    units = escape["units_affected"]
    lines = [
        units * asset["standard_unit_cost_cents"],
        units * calc.SCRAP_HANDLING_CENTS,
        0,
        escape["investigation_fee_cents"],
    ]
    gross = calc.recovery_sum(lines, escape["printer_share_pct"])
    cap = printer["recovery_liability_cap_cents"]
    escape["provisional_recovery_cents"] = min(gross, cap)
    escape["liability_cap_applied"] = gross > cap
    escape["state"] = "RECOVERY_CLAIMED"
    touch(escape)
    return ok(escape_json(escape))


@bp.route("/error-escapes/<escape_id>/dispute", methods=["POST"])
def dispute_escape(escape_id):
    user_id, _role = auth(["PrinterRep"])
    escape = load("escapes", escape_id)
    if escape["printer_id"] != user_id:
        fail(
            "ERR_PRINTER_IDENTITY_MISMATCH",
            "only the printer named on the escape may dispute the claim",
        )
    body = body_fields(["dispute_reason"])
    reason = body.get("dispute_reason")
    if not isinstance(reason, str) or not reason.strip():
        invalid("dispute_reason is required and must be non-empty")

    if escape["state"] != "RECOVERY_CLAIMED":
        fail("ERR_ESCAPE_STATE_INVALID", "only a RECOVERY_CLAIMED escape may be disputed")

    escape["dispute_reason"] = reason
    escape["dispute_count"] = escape["dispute_count"] + 1
    escape["state"] = "DISPUTED"
    touch(escape)
    return ok(escape_json(escape))


@bp.route("/error-escapes/<escape_id>/settle", methods=["POST"])
def settle_escape(escape_id):
    auth(["PlatformAdmin"])
    escape = load("escapes", escape_id)
    body = body_fields(
        ["resolution"],
        [
            "actual_reprint_cost_cents",
            "actual_scrap_cost_cents",
            "actual_expedite_freight_cents",
            "settlement_note",
        ],
    )
    resolution = need_enum(body, "resolution", calc.RESOLUTIONS)
    note = body.get("settlement_note")
    if note is not None and not isinstance(note, str):
        invalid("settlement_note must be a string")
    actuals = None
    if resolution == "SETTLED":
        for key in (
            "actual_reprint_cost_cents",
            "actual_scrap_cost_cents",
            "actual_expedite_freight_cents",
        ):
            if body.get(key) is None:
                invalid("a SETTLED resolution requires %s" % key)
        actuals = [
            need_int(body, "actual_reprint_cost_cents", 0),
            need_int(body, "actual_scrap_cost_cents", 0),
            need_int(body, "actual_expedite_freight_cents", 0),
        ]

    if resolution == "SETTLED":
        if escape["state"] != "RECOVERY_CLAIMED":
            fail("ERR_ESCAPE_STATE_INVALID", "a settlement requires the RECOVERY_CLAIMED state")
    else:
        if escape["state"] not in ("RECOVERY_CLAIMED", "DISPUTED"):
            fail(
                "ERR_ESCAPE_STATE_INVALID",
                "a write-off requires the RECOVERY_CLAIMED or DISPUTED state",
            )

    printer = db.printers[escape["printer_id"]]
    provisional = escape.get("provisional_recovery_cents") or 0
    if resolution == "SETTLED":
        lines = [actuals[0], actuals[1], actuals[2], escape["investigation_fee_cents"]]
        gross = calc.recovery_sum(lines, escape["printer_share_pct"])
        if gross > printer["recovery_liability_cap_cents"]:
            fail(
                "ERR_RECOVERY_EXCEEDS_LIABILITY_CAP",
                "the settled recovery exceeds the vendor's contractual liability cap",
            )
        escape["actual_reprint_cost_cents"] = actuals[0]
        escape["actual_scrap_cost_cents"] = actuals[1]
        escape["actual_expedite_freight_cents"] = actuals[2]
        escape["final_recovery_cents"] = gross
        escape["recovery_variance_cents"] = gross - provisional
        escape["resolution"] = "SETTLED"
        escape["state"] = "SETTLED"
    else:
        escape["final_recovery_cents"] = 0
        escape["recovery_variance_cents"] = 0 - provisional
        escape["resolution"] = "WRITTEN_OFF"
        escape["state"] = "WRITTEN_OFF"
    escape["settlement_note"] = note
    escape["settled_at"] = now_iso()
    touch(escape)

    if resolution == "SETTLED":
        # The probation cascade: ledger credit, scorecard, probation, proof re-checks.
        apply_settlement_penalty(printer, escape)

    return ok(escape_json(escape))

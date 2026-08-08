"""Superbills: drafting and the void / reissue / denial lifecycle."""

from flask import Blueprint

import config
import ladder
from clock import clock
from errors import ApiError
from store import db, bump, make_row, ordered, touch
from services import serializers

bp = Blueprint("superbills", __name__)

ACTION_SOURCE_STATES = {
    "ISSUE": ("DRAFT",),
    "VOID": ("ISSUED",),
    "REISSUE": ("VOIDED",),
    "REPORT_DENIAL": ("ISSUED",),
    "APPEAL": ("DENIED",),
    "CLOSE": ("ISSUED",),
}


def _partitions(encounter):
    """billable / membership-absorbed / never-billable supplement value."""
    billable = encounter["cash_charged_cents"]
    membership_absorbed = (
        encounter["base_fee_cents"] if encounter["entitlement_consumed"] else 0
    )
    supplements = sum(
        d["total_price_cents"]
        for d in db.dispenses.values()
        if d["patient_id"] == encounter["patient_id"] and d["status"] == "DISPENSED"
    )
    return billable, membership_absorbed, supplements


def _copy_from_encounter(superbill, encounter):
    practitioner = db.practitioners.get(encounter["practitioner_id"])
    superbill["diagnosis_codes"] = list(encounter["diagnosis_codes"] or [])
    superbill["service_code"] = encounter["service_code"]
    superbill["rendering_practitioner_npi"] = (
        practitioner["npi"] if practitioner else None
    )
    billable, membership_absorbed, supplements = _partitions(encounter)
    superbill["billable_total_cents"] = billable
    superbill["non_billable_membership_cents"] = membership_absorbed
    superbill["excluded_supplement_cents"] = supplements


@bp.route("/superbills", methods=["POST"])
def create_superbill():
    def handler(ctx):
        encounter = ctx.fk["encounter_id"]
        row = make_row(
            patient_id=ctx.fk["patient_id"]["id"],
            encounter_id=encounter["id"],
            revision_no=1,
            status="DRAFT",
            diagnosis_codes=[],
            service_code=None,
            rendering_practitioner_npi=None,
            billable_total_cents=0,
            non_billable_membership_cents=0,
            excluded_supplement_cents=0,
            denial_code=None,
            denial_reason=None,
            appeal_narrative=None,
            void_reason=None,
            issued_at=None,
        )
        _copy_from_encounter(row, encounter)
        db.superbills[row["id"]] = row
        return serializers.superbill(row)

    return ladder.run(
        {
            "roles": [config.ROLE_BILLING],
            "body_fks": ["patient_id", "encounter_id"],
            "shape": [
                ("patient_id", "string", True),
                ("encounter_id", "string", True),
            ],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/superbills/<sid>", methods=["GET"])
def get_superbill(sid):
    return ladder.run(
        {
            "roles": [config.ROLE_BILLING, config.ROLE_PRACTICE_ADMIN, config.ROLE_PATIENT],
            "path": [("superbill", sid)],
            "owner": lambda ctx: ctx.path["superbill"]["patient_id"],
            "handler": lambda ctx: serializers.superbill(ctx.path["superbill"]),
        }
    )


@bp.route("/superbills", methods=["GET"])
def list_superbills():
    def handler(ctx):
        rows = ordered(db.superbills.values())
        for field in ("patient_id", "encounter_id", "status"):
            value = ctx.args_get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        return ladder.list_result(ctx, rows, serializers.superbill)

    return ladder.run(
        {
            "roles": [config.ROLE_BILLING, config.ROLE_PRACTICE_ADMIN],
            "paginated": True,
            "handler": handler,
        }
    )


@bp.route("/superbills/<sid>/transitions", methods=["POST"])
def superbill_transition(sid):
    def role_action(ctx):
        # REPORT_DENIAL is the only action the Patient role may take.
        if ctx.role != config.ROLE_PATIENT:
            return
        action = ctx.body.get("action")
        if action in config.SUPERBILL_ACTIONS and action != "REPORT_DENIAL":
            raise ApiError("ERR_ROLE_NOT_PERMITTED")

    def own_state(ctx):
        action = ctx.body.get("action")
        if action not in ACTION_SOURCE_STATES:
            return
        superbill = ctx.path["superbill"]
        if superbill["status"] not in ACTION_SOURCE_STATES[action]:
            raise ApiError("ERR_INVALID_STATE")
        if action == "REISSUE" and superbill["revision_no"] >= config.SUPERBILL_MAX_REVISIONS:
            raise ApiError("ERR_INVALID_STATE")

    def dependent_state(ctx):
        if ctx.body.get("action") != "ISSUE":
            return
        encounter = db.encounters.get(ctx.path["superbill"]["encounter_id"])
        if encounter is None or encounter["scheduling_status"] != "COMPLETED":
            raise ApiError("ERR_DEPENDENT_STATE_INVALID")

    def billability(ctx):
        if ctx.body["action"] != "ISSUE":
            return
        superbill = ctx.path["superbill"]
        if (
            superbill["billable_total_cents"] <= 0
            or not superbill["diagnosis_codes"]
            or superbill["rendering_practitioner_npi"] is None
        ):
            raise ApiError("ERR_SUPERBILL_NOT_BILLABLE")

    def handler(ctx):
        superbill = ctx.path["superbill"]
        encounter = db.encounters.get(superbill["encounter_id"])
        action = ctx.body["action"]

        if action == "ISSUE":
            superbill["status"] = "ISSUED"
            superbill["issued_at"] = clock.stamp()
            if encounter is not None and encounter["billing_status"] in (
                "ENTITLEMENT_CONSUMED",
                "CASH_CHARGED",
            ):
                encounter["billing_status"] = "SUPERBILLED"
                touch(encounter)
        elif action == "VOID":
            superbill["status"] = "VOIDED"
            superbill["void_reason"] = ctx.body.get("void_reason")
            if encounter is not None and encounter["billing_status"] == "SUPERBILLED":
                encounter["billing_status"] = (
                    "ENTITLEMENT_CONSUMED"
                    if encounter["entitlement_consumed"]
                    else "CASH_CHARGED"
                )
                touch(encounter)
        elif action == "REISSUE":
            superbill["status"] = "DRAFT"
            superbill["revision_no"] += 1
            if encounter is not None:
                _copy_from_encounter(superbill, encounter)
        elif action == "REPORT_DENIAL":
            superbill["status"] = "DENIED"
            superbill["denial_code"] = ctx.body.get("denial_code")
            superbill["denial_reason"] = ctx.body.get("denial_reason")
        elif action == "APPEAL":
            superbill["status"] = "APPEALED"
            superbill["appeal_narrative"] = ctx.body.get("appeal_narrative")
        else:
            superbill["status"] = "CLOSED"
        bump(superbill)
        return serializers.superbill(superbill)

    return ladder.run(
        {
            "roles": [config.ROLE_BILLING, config.ROLE_PATIENT],
            "path": [("superbill", sid)],
            "role_action": role_action,
            "owner": lambda ctx: ctx.path["superbill"]["patient_id"],
            "own_state": own_state,
            "dependent_state": dependent_state,
            "shape": [
                ("action", "string", True),
                ("void_reason", "string", False),
                ("denial_code", "string", False),
                ("denial_reason", "string", False),
                ("appeal_narrative", "string", False),
            ],
            "enums": {"action": config.SUPERBILL_ACTIONS},
            "business": [billability],
            "handler": handler,
        }
    )

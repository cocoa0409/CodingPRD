"""Compliance notices, the monitoring sweep and the logical clock."""
from flask import Blueprint

import calc
import enums
from authz import (
    ROLE_BORROWER,
    ROLE_LENDER,
    ROLE_PROVIDER_ANALYST,
    ALL_ROLES,
    authorize,
)
from db import all_rows, db, touch
from errors import fail
from response import created, ok
from services import (
    adopt_determination,
    build_determination,
    create_notice,
    folio_community,
    must,
    notices_for,
    recompute_folio,
    retire_determination,
    touch_folio,
)
from shape import Field, no_body, read_body, read_query

bp = Blueprint("notices", __name__)

NOTICE_SENDERS = [ROLE_LENDER, ROLE_PROVIDER_ANALYST]
ACKNOWLEDGERS = [ROLE_LENDER, ROLE_BORROWER]
ANALYST = [ROLE_PROVIDER_ANALYST]


@bp.post("/compliance-notices")
def send_notice():
    actor = authorize(NOTICE_SENDERS)
    body = read_body(
        [
            Field("loan_folio_id"),
            Field("determination_id"),
            Field("notice_type", "enum", enum=enums.CLIENT_NOTICE_TYPES),
            Field("annual_premium_rate_cents", "int", min_value=0),
        ]
    )
    folio = must("loan_folios", body["loan_folio_id"])
    determination = must("determinations", body["determination_id"])

    # priority 7: a Lender may only notice its own borrowers
    if actor.is_lender and actor.user_id != folio["lender_id"]:
        fail(
            "ERR_FOLIO_NOT_OWNED",
            "The acting lender does not own loan folio '%s'." % folio["id"],
        )

    # priority 11: a retired determination may not be cited
    if determination["status"] == "SUPERSEDED":
        fail(
            "ERR_INVALID_DETERMINATION_STATE",
            "A superseded determination may not be cited by a notice.",
        )

    # priority 12: nothing may be noticed where coverage cannot be written
    community = folio_community(folio)
    if community["coverage_availability"] == "UNAVAILABLE":
        fail(
            "ERR_COVERAGE_UNAVAILABLE",
            "Federal flood insurance cannot be written in this community.",
        )

    # priority 15: a mandatory-purchase notice needs a live obligation
    current = db.determinations.get(folio["current_determination_id"])
    if body["notice_type"] == "MANDATORY_PURCHASE" and (
        current is None or not current["mandatory_purchase_flag"]
    ):
        fail(
            "ERR_MANDATORY_PURCHASE_NOT_TRIGGERED",
            "The folio's current determination does not require flood insurance.",
        )

    # priority 17: the notice must cite the folio's current determination
    if determination["id"] != folio["current_determination_id"]:
        fail(
            "ERR_STRUCTURE_FOLIO_MISMATCH",
            "The cited determination is not the folio's current determination.",
        )

    # priority 24: one live notice of a type per folio, plus a five-day cooldown
    now = db.now()
    for notice in notices_for(folio):
        if notice["notice_type"] != body["notice_type"] or notice["status"] != "SENT":
            continue
        window_end = notice["response_deadline_at"] + calc_days(
            calc.NOTICE_COOLDOWN_DAYS
        )
        if notice["sent_at"] <= now <= window_end:
            fail(
                "ERR_NOTICE_WINDOW_ACTIVE",
                "A %s notice is already active on this folio." % body["notice_type"],
            )

    # the obligation is re-derived first so that the notice can snapshot it
    recompute_folio(folio)
    notice = create_notice(
        folio, determination, body["notice_type"], body["annual_premium_rate_cents"]
    )
    touch_folio(folio)
    return created(notice)


def calc_days(count):
    from datetime import timedelta

    return timedelta(days=count)


@bp.post("/compliance-notices/<compliance_notice_id>/acknowledgement")
def acknowledge_notice(compliance_notice_id):
    actor = authorize(ACKNOWLEDGERS)
    no_body()
    notice = must("compliance_notices", compliance_notice_id)
    folio = db.loan_folios[notice["loan_folio_id"]]

    # priority 7 and 8: only the two parties to the loan may acknowledge
    if actor.is_lender and actor.user_id != folio["lender_id"]:
        fail(
            "ERR_FOLIO_NOT_OWNED",
            "The acting lender does not own loan folio '%s'." % folio["id"],
        )
    if actor.is_borrower and actor.user_id != folio["borrower_user_id"]:
        fail(
            "ERR_BORROWER_NOT_ON_LOAN",
            "The acting borrower is not the borrower of record on this loan.",
        )

    if notice["status"] != "SENT":
        fail(
            "ERR_INVALID_NOTICE_STATE",
            "Only a SENT notice may be acknowledged (status is %s)." % notice["status"],
        )
    now = db.now()
    if now > notice["response_deadline_at"]:
        fail(
            "ERR_INVALID_NOTICE_STATE",
            "The response deadline has passed; the notice can no longer be "
            "acknowledged.",
        )

    notice["status"] = "ACKNOWLEDGED"
    notice["acknowledged_at"] = now
    notice["acknowledged_by_role"] = actor.role
    notice["closed_at"] = now
    touch(notice)
    touch_folio(folio)
    return ok(notice)


@bp.post("/monitoring-runs")
def monitoring_run():
    authorize(ANALYST)
    fields = [
        Field("community_id", required=False, default=None, nullable=True),
        Field("map_panel_id", required=False, default=None, nullable=True),
    ]
    body = read_body(fields)
    query = read_query(fields)
    community_id = body.get("community_id") or query.get("community_id")
    map_panel_id = body.get("map_panel_id") or query.get("map_panel_id")
    if community_id is not None:
        must("communities", community_id)
    if map_panel_id is not None:
        must("map_panels", map_panel_id)

    now = db.now()
    scanned = 0
    cleared = 0
    issued = 0
    notices_sent = 0
    notices_expired = 0

    # --- phase one: work the flagged re-determination queue -----------------
    for det in [
        d for d in all_rows("determinations") if d["status"] == "FLAGGED_FOR_REVIEW"
    ]:
        structure = db.structures.get(det["structure_id"])
        folio = db.loan_folios.get(det["loan_folio_id"])
        if structure is None or folio is None:
            continue
        prop = db.properties[structure["property_id"]]
        if community_id is not None and prop["community_id"] != community_id:
            continue
        if map_panel_id is not None and det["map_panel_id"] != map_panel_id:
            continue
        panel = calc.effective_panel(prop)
        if panel is None:
            continue
        scanned += 1
        community = db.communities[prop["community_id"]]
        outcome = calc.classify(structure, prop, panel, "life_of_loan_lenient", det)
        if (
            outcome["zone_code"] == det["zone_code"]
            and outcome["sfha_flag"] == det["sfha_flag"]
        ):
            # nothing moved: the flag clears and the determination goes live again
            det["status"] = "ISSUED"
            det["flagged_reason"] = None
            det["map_panel_id"] = panel["id"]
            touch(det)
            touch_folio(folio)
            cleared += 1
            continue

        retire_determination(det)
        revision = build_determination(
            folio,
            structure,
            prop,
            community,
            panel,
            "LIFE_OF_LOAN_REVIEW",
            "system",
            det,
        )
        adopt_determination(folio, revision)
        touch(folio)
        issued += 1
        if revision["mandatory_purchase_flag"] and folio["insurance_status"] in (
            "NONE",
            "NOT_REQUIRED",
        ):
            create_notice(folio, revision, "RE_DETERMINATION", 0)
            touch_folio(folio)
            notices_sent += 1

    # --- phase two: sweep every lapsed notice in the system -----------------
    lapsed_folio_ids = []
    for notice in all_rows("compliance_notices"):
        if notice["status"] != "SENT" or notice["response_deadline_at"] >= now:
            continue
        notice["status"] = "EXPIRED"
        notice["closed_at"] = now
        touch(notice)
        notices_expired += 1
        if notice["loan_folio_id"] not in lapsed_folio_ids:
            lapsed_folio_ids.append(notice["loan_folio_id"])
    for folio_id in lapsed_folio_ids:
        folio = db.loan_folios.get(folio_id)
        if folio is not None:
            touch_folio(folio)

    return ok(
        {
            "community_id": community_id,
            "map_panel_id": map_panel_id,
            "determinations_scanned": scanned,
            "redeterminations_cleared": cleared,
            "redeterminations_issued": issued,
            "notices_sent": notices_sent,
            "notices_expired": notices_expired,
            "run_at": now,
        }
    )


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(ALL_ROLES)
    body = read_body([Field("current_utc", "datetime")])
    db.set_clock(body["current_utc"])
    return ok({"current_utc": db.now()})

"""ExitValuation + COIDisclosure + MergerProposal routes."""
from flask import Blueprint, request

import db
from db import clock, _format_iso
from middleware import get_auth, require_roles, check_ownership
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_EXIT_ALREADY_IN_PROGRESS,
    ERR_VALUATION_NOT_APPRAISED, ERR_BUYOUT_NOT_APPROVED,
    ERR_DISPUTE_LIMIT_REACHED, ERR_MERGER_NOT_APPROVED,
    ERR_MERGER_ALREADY_ACTIVE,
)
from services.core import (
    get_body, check_unknown_fields, req_enum, req_str, req_int, opt_str,
    dec, round_half_up_cents, new_entity, touch, get_or_404,
    pagination_params, paginate, serialize_valuation, serialize_coi,
    serialize_merger, recalc_ownership, total_shares_outstanding,
    committee_status, recompute_motion_counts, motion_tallies,
)

bp = Blueprint("exits_coi_mergers", __name__)
ALL_ROLES = ("BoardAdmin", "Physician", "ComplianceOfficer")


# ---------------- ExitValuation ----------------

def _provisional_value(physician, ownership_fraction):
    pol = db.policy
    ebitda = pol["trailing_ebitda_cents"] if pol else 0
    multiple = pol["ebitda_multiple"] if pol else 6
    return (physician["capital_account_balance_cents"]
            + round_half_up_cents(ownership_fraction * dec(ebitda) * dec(multiple)))


def _final_value(trigger_type, appraised, ownership_fraction):
    pol = db.policy
    if trigger_type in ("VOLUNTARY", "RETIREMENT"):
        discount = pol["minority_discount_pct"] if pol else 0.15
        return round_half_up_cents(
            dec(appraised) * ownership_fraction * (dec(1) - dec(discount)))
    return round_half_up_cents(dec(appraised) * ownership_fraction)


@bp.post("/governance/exit-valuations")
def create_valuation():
    role, user_id = get_auth()
    body = get_body()
    check_unknown_fields(body, ["physician_id", "trigger_type"])
    physician_id = body.get("physician_id")
    if not isinstance(physician_id, str) or not physician_id:
        raise_err(ERR_INVALID_REQUEST, "physician_id is required")
    trigger = req_enum(body, "trigger_type",
                       ("VOLUNTARY", "RETIREMENT", "TERMINATION", "DEATH"))
    require_roles(role, ("Physician", "BoardAdmin"))
    check_ownership(role, user_id, physician_id)

    phys = db.physicians.get(physician_id)
    if phys is None:
        raise_err(ERR_NOT_FOUND, "Physician not found")

    # PRD §3.6: "a second initiation while one is in flight is rejected with
    # ERR_EXIT_ALREADY_IN_PROGRESS" — the in-flight rule is the named rejection
    # for a physician with a non-terminal valuation (who is always EXITING),
    # so it is checked before the generic SHAREHOLDER-only state gate.
    for v in db.exit_valuations.values():
        if v["physician_id"] == physician_id and v["status"] != "FINALIZED":
            raise_err(ERR_EXIT_ALREADY_IN_PROGRESS,
                      "Physician already has a non-terminal exit valuation")

    if phys["partnership_status"] != "SHAREHOLDER":
        raise_err(ERR_INVALID_STATE,
                  "Only a SHAREHOLDER may initiate an exit valuation")

    # ownership snapshot: exact fraction internally, 6dp display
    total = total_shares_outstanding()
    fraction = (dec(phys["shares_held"]) / dec(total)) if total > 0 else dec(0)
    ownership_display = float(fraction.quantize(dec("0.000001"),
                                                rounding="ROUND_HALF_UP"))
    provisional = _provisional_value(phys, fraction)

    v = new_entity(db.exit_valuations, {
        "physician_id": physician_id,
        "trigger_type": trigger,
        "ownership_pct_snapshot": ownership_display,
        "_ownership_fraction": fraction,  # exact internal
        "provisional_value_cents": provisional,
        "appraised_practice_value_cents": None,
        "final_value_cents": None,
        "appraisal_final": False,
        "dispute_rounds": 0,
        "approving_motion_id": None,
        "payment_schedule_cents": None,
        "status": "INITIATED",
    })
    phys["partnership_status"] = "EXITING"
    touch(phys)
    recalc_ownership()
    return success_object(serialize_valuation(v), 201)


@bp.get("/governance/exit-valuations")
def list_valuations():
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    items = list(db.exit_valuations.values())
    f_pid = request.args.get("physician_id")
    f_motion = request.args.get("approving_motion_id")
    f_status = request.args.get("status")
    if f_pid is not None:
        items = [v for v in items if v["physician_id"] == f_pid]
    if f_motion is not None:
        items = [v for v in items if v.get("approving_motion_id") == f_motion]
    if f_status is not None:
        items = [v for v in items if v["status"] == f_status]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_valuation(v) for v in page], limit, offset, total)


@bp.get("/governance/exit-valuations/<vid>")
def get_valuation(vid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    v = get_or_404(db.exit_valuations, vid, "ExitValuation")
    return success_object(serialize_valuation(v))


@bp.post("/governance/exit-valuations/<vid>/appraise")
def appraise_valuation(vid):
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["appraised_practice_value_cents",
                                "expected_valuation_version"])
    require_roles(role, ("BoardAdmin",))
    v = get_or_404(db.exit_valuations, vid, "ExitValuation")

    appraised = body.get("appraised_practice_value_cents")
    if (appraised is None or isinstance(appraised, bool)
            or not isinstance(appraised, int) or appraised < 0):
        raise_err(ERR_INVALID_REQUEST,
                  "appraised_practice_value_cents must be a non-negative integer")
    if "expected_valuation_version" not in body:
        raise_err(ERR_INVALID_REQUEST, "expected_valuation_version is required")
    expected = body["expected_valuation_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_valuation_version must be integer")

    if v["status"] not in ("INITIATED", "APPRAISED", "DISPUTED", "ARBITRATION"):
        raise_err(ERR_INVALID_STATE, "Valuation cannot be appraised in this state")
    if expected != v["version"]:
        raise_err(ERR_STALE_VERSION, "Valuation version mismatch")

    v["appraised_practice_value_cents"] = appraised
    v["final_value_cents"] = _final_value(v["trigger_type"], appraised,
                                          v["_ownership_fraction"])
    if v["status"] == "ARBITRATION":
        v["appraisal_final"] = True
    v["status"] = "APPRAISED"
    touch(v)
    return success_object(serialize_valuation(v))


@bp.post("/governance/exit-valuations/<vid>/dispute")
def dispute_valuation(vid):
    role, user_id = get_auth()
    require_roles(role, ("Physician",))
    v = get_or_404(db.exit_valuations, vid, "ExitValuation")
    check_ownership(role, user_id, v["physician_id"])
    if v["status"] != "APPRAISED":
        raise_err(ERR_INVALID_STATE, "Valuation is not APPRAISED")
    if v["appraisal_final"]:
        raise_err(ERR_INVALID_STATE, "Appraisal is final; disputes blocked")
    max_rounds = db.policy["max_dispute_rounds"] if db.policy else 2
    if v["dispute_rounds"] >= max_rounds:
        raise_err(ERR_DISPUTE_LIMIT_REACHED, "Dispute limit reached")
    v["dispute_rounds"] += 1
    v["status"] = "DISPUTED"
    touch(v)
    return success_object(serialize_valuation(v))


@bp.post("/governance/exit-valuations/<vid>/arbitrate")
def arbitrate_valuation(vid):
    role, _ = get_auth()
    require_roles(role, ("BoardAdmin",))
    v = get_or_404(db.exit_valuations, vid, "ExitValuation")
    if v["status"] != "DISPUTED":
        raise_err(ERR_INVALID_STATE, "Valuation is not DISPUTED")
    v["status"] = "ARBITRATION"
    touch(v)
    return success_object(serialize_valuation(v))


@bp.post("/governance/exit-valuations/<vid>/finalize")
def finalize_valuation(vid):
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["motion_id"])
    require_roles(role, ("BoardAdmin",))
    v = get_or_404(db.exit_valuations, vid, "ExitValuation")

    motion_id = body.get("motion_id")
    if not isinstance(motion_id, str) or not motion_id:
        raise_err(ERR_INVALID_REQUEST, "motion_id is required")

    # state gate: valuation must be APPRAISED
    if v["status"] != "APPRAISED":
        raise_err(ERR_VALUATION_NOT_APPRAISED, "Valuation is not APPRAISED")

    # motion linkage gate
    motion = db.motions.get(motion_id)
    if (motion is None or motion["motion_type"] != "BUYOUT_APPROVAL"
            or motion["status"] != "ADOPTED"
            or motion["payload"].get("exit_valuation_id") != vid):
        raise_err(ERR_BUYOUT_NOT_APPROVED,
                  "No adopted BUYOUT_APPROVAL motion links this valuation")
    # motion must not already be consumed by another finalize
    for other in db.exit_valuations.values():
        if (other["id"] != vid and other.get("approving_motion_id") == motion_id):
            raise_err(ERR_BUYOUT_NOT_APPROVED,
                      "Motion already consumed by another finalize")

    # payment schedule: 40/30/30, first two round_half_up, last absorbs residue
    final = v["final_value_cents"]
    first = round_half_up_cents(dec(final) * dec("0.40"))
    second = round_half_up_cents(dec(final) * dec("0.30"))
    third = final - first - second
    v["payment_schedule_cents"] = [first, second, third]
    v["approving_motion_id"] = motion_id
    v["status"] = "FINALIZED"
    touch(v)

    # ---- exit cascade ----
    phys = db.physicians.get(v["physician_id"])
    if phys is not None:
        phys["partnership_status"] = "EXITED"
        phys["shares_held"] = 0
        touch(phys)

        # board seat cascade: vacate held seat or promote successor
        for s in db.board_seats.values():
            if s.get("current_holder_physician_id") == phys["id"] and s["status"] == "FILLED":
                if s.get("next_holder_physician_id"):
                    s["current_holder_physician_id"] = s["next_holder_physician_id"]
                    s["current_term_start"] = s["next_term_start"]
                    s["current_term_end"] = s["next_term_end"]
                    s["next_holder_physician_id"] = None
                    s["next_term_start"] = None
                    s["next_term_end"] = None
                else:
                    s["current_holder_physician_id"] = None
                    s["current_term_start"] = None
                    s["current_term_end"] = None
                    s["status"] = "VACANT"
                touch(s)
            # also clear booked successor if the exiting physician was the successor
            if s.get("next_holder_physician_id") == phys["id"]:
                s["next_holder_physician_id"] = None
                s["next_term_start"] = None
                s["next_term_end"] = None
                touch(s)

        # committee cascade: remove memberships, impairment re-check
        for c in db.committees.values():
            before = len(c["members"])
            c["members"] = [m for m in c["members"]
                            if m["physician_id"] != phys["id"]]
            if len(c["members"]) != before:
                c["status"] = committee_status(len(c["members"]),
                                               c["quorum_count"], c["status"])
                touch(c)

    recalc_ownership()
    return success_object(serialize_valuation(v))


# ---------------- COIDisclosure ----------------

@bp.post("/governance/coi-disclosures")
def create_coi():
    role, user_id = get_auth()
    body = get_body()
    check_unknown_fields(body, ["related_motion_id", "description"])
    require_roles(role, ("Physician",))
    description = req_str(body, "description")
    related_motion_id = opt_str(body, "related_motion_id")

    # filer is the X-User-ID physician; must exist
    if user_id not in db.physicians:
        raise_err(ERR_NOT_FOUND, "Physician not found")
    if related_motion_id is not None and related_motion_id not in db.motions:
        raise_err(ERR_NOT_FOUND, "related_motion_id not found")

    c = new_entity(db.coi_disclosures, {
        "physician_id": user_id,
        "related_motion_id": related_motion_id,
        "description": description,
        "status": "FILED",
        "reviewed_by": None,
        "review_note": None,
    })
    return success_object(serialize_coi(c), 201)


@bp.get("/governance/coi-disclosures")
def list_coi():
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    items = list(db.coi_disclosures.values())
    f_pid = request.args.get("physician_id")
    f_motion = request.args.get("related_motion_id")
    f_status = request.args.get("status")
    if f_pid is not None:
        items = [c for c in items if c["physician_id"] == f_pid]
    if f_motion is not None:
        items = [c for c in items if c.get("related_motion_id") == f_motion]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_coi(c) for c in page], limit, offset, total)


@bp.get("/governance/coi-disclosures/<cid>")
def get_coi(cid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    c = get_or_404(db.coi_disclosures, cid, "COIDisclosure")
    return success_object(serialize_coi(c))


@bp.post("/governance/coi-disclosures/<cid>/review")
def review_coi(cid):
    role, user_id = get_auth()
    body = get_body()
    check_unknown_fields(body, ["outcome", "review_note"])
    require_roles(role, ("ComplianceOfficer",))
    c = get_or_404(db.coi_disclosures, cid, "COIDisclosure")
    outcome = body.get("outcome")
    if outcome not in ("CLEARED", "FLAGGED"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be CLEARED or FLAGGED")
    review_note = opt_str(body, "review_note")

    if c["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, "Disclosure already reviewed")

    c["status"] = outcome
    c["reviewed_by"] = user_id
    c["review_note"] = review_note
    touch(c)

    # FLAGGED cascade
    if outcome == "FLAGGED" and c.get("related_motion_id"):
        motion = db.motions.get(c["related_motion_id"])
        if motion is not None and motion["status"] in ("OPEN", "TABLED"):
            pid = c["physician_id"]
            if pid not in motion["recused_physician_ids"]:
                motion["recused_physician_ids"].append(pid)
            # void any CAST vote by this physician on this motion
            for v in db.votes.values():
                if (v["motion_id"] == motion["id"] and v["physician_id"] == pid
                        and v["status"] == "CAST"):
                    v["status"] = "VOIDED"
                    v["void_reason"] = "COI_RECUSAL"
                    touch(v)
            recompute_motion_counts(motion)
            touch(motion)

    return success_object(serialize_coi(c))


# ---------------- MergerProposal ----------------

@bp.post("/governance/merger-proposals")
def create_merger():
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["counterparty_name", "exchange_ratio_x1000",
                                "cash_consideration_cents"])
    require_roles(role, ("BoardAdmin",))
    name = req_str(body, "counterparty_name")
    ratio = req_int(body, "exchange_ratio_x1000", min_val=0)
    cash = req_int(body, "cash_consideration_cents", min_val=0)

    for m in db.merger_proposals.values():
        if m["status"] in ("PROPOSED", "DUE_DILIGENCE", "NEGOTIATION"):
            raise_err(ERR_MERGER_ALREADY_ACTIVE,
                      "Another merger proposal is non-terminal")

    m = new_entity(db.merger_proposals, {
        "counterparty_name": name,
        "exchange_ratio_x1000": ratio,
        "cash_consideration_cents": cash,
        "diligence_note": None,
        "deciding_motion_id": None,
        "status": "PROPOSED",
    })
    return success_object(serialize_merger(m), 201)


@bp.get("/governance/merger-proposals")
def list_mergers():
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    items = list(db.merger_proposals.values())
    f_motion = request.args.get("deciding_motion_id")
    f_status = request.args.get("status")
    if f_motion is not None:
        items = [m for m in items if m.get("deciding_motion_id") == f_motion]
    if f_status is not None:
        items = [m for m in items if m["status"] == f_status]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_merger(m) for m in page], limit, offset, total)


@bp.get("/governance/merger-proposals/<mid>")
def get_merger(mid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    m = get_or_404(db.merger_proposals, mid, "MergerProposal")
    return success_object(serialize_merger(m))


@bp.post("/governance/merger-proposals/<mid>/advance")
def advance_merger(mid):
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["diligence_note"])
    require_roles(role, ("BoardAdmin",))
    m = get_or_404(db.merger_proposals, mid, "MergerProposal")
    note = opt_str(body, "diligence_note")
    if m["status"] == "PROPOSED":
        m["status"] = "DUE_DILIGENCE"
        if note is not None:
            m["diligence_note"] = note
    elif m["status"] == "DUE_DILIGENCE":
        m["status"] = "NEGOTIATION"
        if note is not None:
            m["diligence_note"] = note
    else:
        raise_err(ERR_INVALID_STATE, "Proposal cannot be advanced")
    touch(m)
    return success_object(serialize_merger(m))


@bp.post("/governance/merger-proposals/<mid>/decide")
def decide_merger(mid):
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["outcome", "motion_id"])
    require_roles(role, ("BoardAdmin",))
    m = get_or_404(db.merger_proposals, mid, "MergerProposal")
    outcome = body.get("outcome")
    if outcome not in ("APPROVED", "REJECTED", "TERMINATE"):
        raise_err(ERR_INVALID_REQUEST,
                  "outcome must be APPROVED, REJECTED, or TERMINATE")
    motion_id = opt_str(body, "motion_id")

    if outcome == "TERMINATE":
        if m["status"] not in ("PROPOSED", "DUE_DILIGENCE", "NEGOTIATION"):
            raise_err(ERR_INVALID_STATE, "Proposal cannot be terminated")
        m["status"] = "TERMINATED"
        touch(m)
        return success_object(serialize_merger(m))

    # APPROVED / REJECTED require NEGOTIATION status + matching terminal motion
    if m["status"] != "NEGOTIATION":
        raise_err(ERR_INVALID_STATE, "Proposal is not in NEGOTIATION")
    if not motion_id:
        raise_err(ERR_INVALID_REQUEST, "motion_id is required for this outcome")
    motion = db.motions.get(motion_id)
    if motion is None or motion["motion_type"] != "MERGER":
        raise_err(ERR_MERGER_NOT_APPROVED, "No matching MERGER motion")
    if motion["payload"].get("merger_proposal_id") != mid:
        raise_err(ERR_MERGER_NOT_APPROVED,
                  "Motion does not name this proposal")
    if outcome == "APPROVED" and motion["status"] != "ADOPTED":
        raise_err(ERR_MERGER_NOT_APPROVED,
                  "Approval requires an ADOPTED MERGER motion")
    if outcome == "REJECTED" and motion["status"] != "REJECTED":
        raise_err(ERR_MERGER_NOT_APPROVED,
                  "Rejection requires a REJECTED MERGER motion")

    m["deciding_motion_id"] = motion_id
    m["status"] = outcome
    touch(m)
    return success_object(serialize_merger(m))

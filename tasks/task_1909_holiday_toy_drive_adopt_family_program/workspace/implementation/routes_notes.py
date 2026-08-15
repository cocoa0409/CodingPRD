"""Thank-you notes: generation (template selector) and lifecycle."""

import hashlib

from flask import Blueprint, request

import clock
import db
from domain import make_row, touch, sort_rows, get_settings, ser_note
from errors import (
    err_not_found, err_invalid_state, err_campaign_not_closed, err_donor_opted_out,
)
from middleware import require_roles
from response import success_object, success_list
from util import get_body

bp = Blueprint("notes", __name__)

GAVE_STATUSES = ("RECEIVED", "DELIVERED")


def _donor_gifts_by_campaign(donor_id):
    """Map campaign_id -> list of gifts in {RECEIVED, DELIVERED} for this donor."""
    out = {}
    for g in db.gifts.values():
        if g["status"] not in GAVE_STATUSES:
            continue
        a = db.adoptions.get(g["adoption_id"])
        if a is None or a["donor_id"] != donor_id:
            continue
        out.setdefault(a["campaign_id"], []).append(g)
    return out


def _personalization_token(donor_id, campaign_id, template):
    raw = donor_id + campaign_id + template
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@bp.route("/campaigns/<cid>/thank-you-notes/generate", methods=["POST"])
@require_roles("PlatformAdmin")
def generate_notes(actor, cid):
    campaign = db.campaigns.get(cid)
    if campaign is None:
        raise err_not_found("Campaign not found")
    get_body()
    if campaign["status"] not in ("RECONCILIATION", "CLOSED"):
        raise err_campaign_not_closed()
    settings = get_settings()

    created = []
    for donor in sort_rows(list(db.donors.values())):
        if not donor["thank_you_opt_in"]:
            continue
        by_campaign = _donor_gifts_by_campaign(donor["id"])
        this_campaign_gifts = by_campaign.get(cid, [])
        if sum(g["declared_value_cents"] for g in this_campaign_gifts) <= 0:
            continue
        # strike suppression: a LATE_CANCELLED adoption in this campaign
        # suppresses the donor's thank-you note (PRD §3.6)
        late_strike = any(
            a["donor_id"] == donor["id"] and a["campaign_id"] == cid
            and a["status"] == "LATE_CANCELLED"
            for a in db.adoptions.values()
        )
        if late_strike:
            continue

        if donor["giving_history_cents"] >= settings["major_donor_threshold_cents"]:
            template = "MAJOR_DONOR"
        else:
            prior_years = set()
            for other_cid, gifts in by_campaign.items():
                if other_cid == cid:
                    continue
                other = db.campaigns.get(other_cid)
                if other is not None and other["season_year"] < campaign["season_year"]:
                    prior_years.add(other["season_year"])
            if not prior_years:
                template = "FIRST_TIME"
            elif campaign["season_year"] - max(prior_years) >= 2:
                template = "LAPSED_RETURNING"
            else:
                template = "STANDARD"

        row = make_row()
        row.update(
            campaign_id=cid,
            donor_id=donor["id"],
            template=template,
            status="QUEUED",
            sent_at=None,
            personalization_token=_personalization_token(donor["id"], cid, template),
        )
        db.thank_you_notes[row["id"]] = row
        created.append(row)

    from response import _meta
    from flask import jsonify
    return jsonify({
        "meta": _meta(),
        "response_type": "array",
        "data": [ser_note(n) for n in created],
    }), 201


@bp.route("/thank-you-notes", methods=["GET"])
@require_roles("PlatformAdmin")
def list_notes(actor):
    rows = list(db.thank_you_notes.values())
    for param in ("campaign_id", "donor_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [n for n in rows if str(n.get(param)) == val]
    return success_list(sort_rows(rows), ser_note)


def _get_note(nid):
    row = db.thank_you_notes.get(nid)
    if row is None:
        raise err_not_found("ThankYouNote not found")
    return row


@bp.route("/thank-you-notes/<nid>", methods=["GET"])
@require_roles("PlatformAdmin")
def get_note(actor, nid):
    return success_object(ser_note(_get_note(nid)))


@bp.route("/thank-you-notes/<nid>/send", methods=["POST"])
@require_roles("PlatformAdmin")
def send_note(actor, nid):
    note = _get_note(nid)
    get_body()
    if note["status"] != "QUEUED":
        raise err_invalid_state("send requires note in QUEUED")
    donor = db.donors.get(note["donor_id"])
    if donor is None or not donor["thank_you_opt_in"]:
        raise err_donor_opted_out()
    campaign = db.campaigns.get(note["campaign_id"])
    if campaign is None or campaign["status"] not in ("RECONCILIATION", "CLOSED"):
        raise err_campaign_not_closed()
    note["status"] = "SENT"
    note["sent_at"] = clock.now()
    touch(note)
    return success_object(ser_note(note))


@bp.route("/thank-you-notes/<nid>/cancel", methods=["POST"])
@require_roles("PlatformAdmin")
def cancel_note(actor, nid):
    note = _get_note(nid)
    get_body()
    if note["status"] != "QUEUED":
        raise err_invalid_state("cancel requires note in QUEUED")
    note["status"] = "CANCELLED"
    touch(note)
    return success_object(ser_note(note))


@bp.route("/thank-you-notes/<nid>/mark-bounced", methods=["POST"])
@require_roles("PlatformAdmin")
def bounce_note(actor, nid):
    note = _get_note(nid)
    get_body()
    if note["status"] != "SENT":
        raise err_invalid_state("mark-bounced requires note in SENT")
    note["status"] = "BOUNCED"
    touch(note)
    return success_object(ser_note(note))

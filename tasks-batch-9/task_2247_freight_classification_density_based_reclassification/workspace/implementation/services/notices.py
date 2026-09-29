"""Correction-notice pricing, the evidence bundle and the shipment ledger (PRD 2.9, 3.7)."""
import db
from constants import LEDGER_STATUSES, OPEN_NOTICE_STATUSES
from services import rating


def notices_of(shipment_id):
    return db.all_rows("correction_notices", lambda n: n.get("shipment_id") == shipment_id)


def open_notices(shipment_id):
    return [n for n in notices_of(shipment_id) if n.get("status") in OPEN_NOTICE_STATUSES]


def memos_of(notice_id):
    return db.all_rows("credit_memos", lambda m: m.get("correction_notice_id") == notice_id)


def recompute_open_notice_count(shipment):
    count = len(open_notices(shipment["id"]))
    if shipment.get("open_notice_count") != count:
        shipment["open_notice_count"] = count
        db.touch(shipment)
    return count


def recompute_credited_total(notice):
    total = sum(int(m.get("amount_cents") or 0) for m in memos_of(notice["id"]))
    if notice.get("credited_total_cents") != total:
        notice["credited_total_cents"] = total
        db.touch(notice)
    return total


def recompute_assessed_total(shipment):
    """PRD 2.9 ledger identity; the interest bucket is deliberately excluded."""
    total = int(shipment.get("original_charge_cents") or 0)
    for notice in notices_of(shipment["id"]):
        if notice.get("status") not in LEDGER_STATUSES:
            continue
        total += int(notice.get("applied_delta_cents") or 0)
        total += int(notice.get("inspection_fee_cents") or 0)
        for memo in memos_of(notice["id"]):
            total -= int(memo.get("freight_credit_cents") or 0)
            total -= int(memo.get("fee_credit_cents") or 0)
    if shipment.get("assessed_total_cents") != total:
        shipment["assessed_total_cents"] = total
        db.touch(shipment)
    return total


def evidence_bundle(shipment, basis_capture_event_id):
    """PRD 3.7: cited capture (2 for COMBINED, else 1, 0 when absent) plus accepted findings."""
    count = 0
    if basis_capture_event_id:
        capture = db.get("capture_events", basis_capture_event_id)
        if capture is not None:
            count += 2 if capture.get("device_type") == "COMBINED" else 1
    findings = rating.accepted_findings_of_shipment(shipment)
    for finding in findings:
        count += 1 + int(finding.get("evidence_photo_count") or 0)
    return count, bool(findings)


def refresh_notice_figures(shipment, notice):
    program = rating.program_of(shipment)
    lines = rating.lines_of(shipment["id"])
    provisional = rating.provisional_delta(shipment, program=program, lines=lines)
    final = rating.final_delta(shipment, program=program, lines=lines)
    bundle, uses = evidence_bundle(shipment, notice.get("basis_capture_event_id"))
    changed = (
        notice.get("provisional_delta_cents") != provisional
        or notice.get("final_delta_cents") != final
        or notice.get("evidence_bundle_count") != bundle
        or notice.get("uses_inspection_findings") != uses
    )
    notice["provisional_delta_cents"] = provisional
    notice["final_delta_cents"] = final
    notice["evidence_bundle_count"] = bundle
    notice["uses_inspection_findings"] = uses
    if changed:
        db.touch(notice)
    return notice


def refresh_draft_notices(shipment):
    """Both delta variants are refreshed on any line change while a notice is DRAFT."""
    for notice in notices_of(shipment["id"]):
        if notice.get("status") == "DRAFT":
            refresh_notice_figures(shipment, notice)


def new_notice_row(shipment, notice_type, origin, basis_capture_event_id=None,
                   supersedes_notice_id=None):
    program = rating.program_of(shipment)
    lines = rating.lines_of(shipment["id"])
    bundle, uses = evidence_bundle(shipment, basis_capture_event_id)
    return db.insert(
        "correction_notices",
        {
            "shipment_id": shipment["id"],
            "basis_capture_event_id": basis_capture_event_id,
            "supersedes_notice_id": supersedes_notice_id,
            "notice_type": notice_type,
            "origin": origin,
            "issued_by_user_id": None,
            "provisional_delta_cents": rating.provisional_delta(shipment, program=program, lines=lines),
            "final_delta_cents": rating.final_delta(shipment, program=program, lines=lines),
            "applied_delta_cents": 0,
            "inspection_fee_cents": 0,
            "evidence_bundle_count": bundle,
            "uses_inspection_findings": uses,
            "status": "DRAFT",
            "issued_at": None,
            "dispute_deadline_at": None,
            "dispute_round_count": 0,
            "supplement_request_count": 0,
            "resolved_at": None,
            "credited_total_cents": 0,
        },
    )

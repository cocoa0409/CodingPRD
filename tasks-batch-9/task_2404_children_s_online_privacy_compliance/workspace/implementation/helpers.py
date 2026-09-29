"""Shared resolution / cascade helpers used by the route modules."""
import calculations as calc
from db import db, now, touch
from errors import fail
from middleware import req_int

def base_row(with_version=True):
    """Common fields (PRD §2.4): id, created_at and — except for evidence —
    updated_at plus version starting at 1."""
    stamp = now()
    row = {"id": db.new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


# ---------------------------------------------------------------------------
# identifier resolution (PRD §2.8, precedence steps 4 and 5)
# ---------------------------------------------------------------------------
_COLLECTIONS = {
    "service": ("online_services", "ERR_SERVICE_NOT_FOUND"),
    "age_screen": ("age_screens", "ERR_AGE_SCREEN_NOT_FOUND"),
    "notice": ("parental_notices", "ERR_NOTICE_NOT_FOUND"),
    "activity": ("activities", "ERR_ACTIVITY_NOT_FOUND"),
    "consent": ("consent_requests", "ERR_CONSENT_NOT_FOUND"),
    "record": ("child_data_records", "ERR_RECORD_NOT_FOUND"),
    "rights_request": ("parental_rights_requests", "ERR_RIGHTS_REQUEST_NOT_FOUND"),
    "integration": ("third_party_integrations", "ERR_INTEGRATION_NOT_FOUND"),
    "program": ("safe_harbor_programs", "ERR_PROGRAM_NOT_FOUND"),
    "assessment": ("safe_harbor_assessments", "ERR_ASSESSMENT_NOT_FOUND"),
}


def lookup(kind, identifier):
    collection_name, _ = _COLLECTIONS[kind]
    return getattr(db, collection_name).get(identifier)


def resolve(kind, identifier):
    collection_name, error_id = _COLLECTIONS[kind]
    row = getattr(db, collection_name).get(identifier)
    if row is None:
        fail(error_id)
    return row


def resolve_body_fk(kind, data, key):
    """Body foreign keys resolve in declaration order (PRD §2.8).

    A field that is absent or not a string cannot identify anything, so it is a
    body-shape problem and reported as ERR_INVALID_REQUEST.
    """
    value = data.get(key)
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % key)
    return resolve(kind, value)


# ---------------------------------------------------------------------------
# optimistic concurrency on OnlineService.version (PRD §2.6, step 7)
# ---------------------------------------------------------------------------
def check_service_version(data, service):
    expected = req_int(data, "expected_service_version")
    if expected != service["version"]:
        fail("ERR_STALE_SERVICE_VERSION")


def bump_service(service):
    """An accepted request advances OnlineService.version by EXACTLY one, applied
    after every cascade triggered by that request has settled (PRD §2.6)."""
    touch(service)


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------
def force_reaudit_on_escalation(service):
    """Determination escalation cascade LINK 2 (PRD §3.2)."""
    for integration in db.third_party_integrations.values():
        if (
            integration["service_id"] == service["id"]
            and integration["status"] == "APPROVED"
            and integration["placement_area"] == "CHILD_DIRECTED_AREA"
        ):
            integration["status"] = "AUDIT_PENDING"
            integration["audit_note"] = "re-audit forced by child-directed determination"
            touch(integration)


def disclosure_loss_cascade(service):
    """When granted_disclosure_consent_count reaches 0, every APPROVED integration
    in a CHILD_DIRECTED_AREA collecting a persistent identifier goes back into
    audit (PRD §3.5 revocation, §3.8 deletion LINK 5)."""
    if calc.granted_disclosure_consent_count(service["id"]) != 0:
        return
    for integration in db.third_party_integrations.values():
        if (
            integration["service_id"] == service["id"]
            and integration["status"] == "APPROVED"
            and integration["placement_area"] == "CHILD_DIRECTED_AREA"
            and integration["collects_persistent_identifier"] is True
        ):
            integration["status"] = "AUDIT_PENDING"
            touch(integration)


def revoke_consent(consent, reason):
    consent["status"] = "REVOKED"
    consent["revoked_at"] = now()
    consent["revocation_reason"] = reason
    touch(consent)


def supersede_consent(consent):
    consent["status"] = "SUPERSEDED"
    consent["revocation_reason"] = "SUPERSEDED_BY_NEW_CONSENT"
    touch(consent)


# ---------------------------------------------------------------------------
# common filtering
# ---------------------------------------------------------------------------
def apply_filters(rows, spec):
    """spec maps query-string parameter -> row field name."""
    from flask import request

    result = rows
    for param, field in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if field == "assessment_year":
            try:
                wanted = int(raw)
            except (TypeError, ValueError):
                result = []
                continue
            result = [r for r in result if r.get(field) == wanted]
        else:
            result = [r for r in result if r.get(field) == raw]
    return result

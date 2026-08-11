"""Time-driven lifecycle transitions (PRD section 2.5).

Fired as a side effect of setting the logical clock, and also after
mutations that can enable condition-based automatic transitions (e.g. the
last DRAFT endorsement resolving on an ENDORSED_PENDING policy). The sweep
is idempotent and runs to a fixpoint.
"""

from db import db
from services.posture import recompute_all_postures
from util import now, touch


def _expire_policy_certs(policy):
    """ACTIVE policy expiry takes ISSUED certificates on its line to EXPIRED."""
    for cert in db.certificates.values():
        if (cert["production_id"] == policy["production_id"]
                and cert["status"] == "ISSUED"
                and policy["coverage_line"] in cert["coverage_lines"]):
            cert["status"] = "EXPIRED"
            touch(cert)


def sweep():
    """Apply every automatic transition whose threshold has been crossed."""
    changed_any = False
    for _ in range(10):  # fixpoint with a safety bound
        changed = False
        ts = now()

        # BOUND -> ACTIVE once effective_date reached
        for pol in db.policies.values():
            if pol["status"] == "BOUND" and ts >= pol["effective_date"]:
                pol["status"] = "ACTIVE"
                touch(pol)
                changed = True

        # ENDORSED_PENDING -> ACTIVE once no DRAFT endorsement remains and
        # the effective date has been reached
        for pol in db.policies.values():
            if pol["status"] != "ENDORSED_PENDING" or ts < pol["effective_date"]:
                continue
            has_draft = any(
                e["policy_id"] == pol["id"] and e["status"] == "DRAFT"
                for e in db.cast_endorsements.values()
            )
            if not has_draft:
                pol["status"] = "ACTIVE"
                touch(pol)
                changed = True

        # ACTIVE -> EXPIRED once expiry reached and no renewal offer open
        for pol in db.policies.values():
            if pol["status"] != "ACTIVE" or ts < pol["expiry_date"]:
                continue
            offer_open = any(
                ro["policy_id"] == pol["id"] and ro["status"] in ("OFFERED", "ACCEPTED")
                for ro in db.renewal_offers.values()
            )
            if not offer_open:
                pol["status"] = "EXPIRED"
                touch(pol)
                _expire_policy_certs(pol)
                changed = True

        # CLEARED/CONDITIONAL exams -> EXPIRED; issued PHYSICAL_CLEARANCE
        # endorsements on the member are revoked in the same tick
        for cm in db.cast_members.values():
            exp = cm["physical_exam_expires_at"]
            if (cm["physical_exam_status"] in ("CLEARED", "CONDITIONAL")
                    and exp is not None and ts >= exp):
                cm["physical_exam_status"] = "EXPIRED"
                cm["physical_exam_expires_at"] = None
                touch(cm)
                for e in db.cast_endorsements.values():
                    if (e["cast_member_id"] == cm["id"]
                            and e["endorsement_type"] == "PHYSICAL_CLEARANCE"
                            and e["status"] == "ISSUED"):
                        e["status"] = "REVOKED"
                        e["revoked_at"] = ts
                        touch(e)
                changed = True

        # ISSUED certificates expire once the clock passes location_end
        for cert in db.certificates.values():
            if cert["status"] == "ISSUED" and ts > cert["location_end"]:
                cert["status"] = "EXPIRED"
                touch(cert)
                changed = True

        # Approved travel extensions activate / expire on their windows
        for ext in db.travel_extensions.values():
            if ext["status"] == "APPROVED" and ts >= ext["travel_window_start"]:
                ext["status"] = "ACTIVE"
                touch(ext)
                changed = True
            elif ext["status"] == "ACTIVE" and ts > ext["travel_window_end"]:
                ext["status"] = "EXPIRED"
                touch(ext)
                changed = True

        # Unanswered renewal offers expire at offer_expires_at
        for ro in db.renewal_offers.values():
            if ro["status"] == "OFFERED" and ts >= ro["offer_expires_at"]:
                ro["status"] = "EXPIRED"
                touch(ro)
                changed = True

        changed_any = changed_any or changed
        if not changed:
            break

    if changed_any:
        recompute_all_postures()

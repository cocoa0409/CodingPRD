"""Regulatory governance and the four-hop enforcement cascade (PRD 2.10, 3.1)."""

from capacity import cells_of_beam, subscriptions_of_beam
from constants import AUTHORIZED_STATES
from db import db, ordered, touch


def beams_of_license(license_record):
    return ordered(
        [
            b
            for b in db.beams.values()
            if b["spectrum_license_id"] == license_record["id"]
        ]
    )


def suspend_beams_of_license(license_record):
    """Put every live beam under the licence out of service; returns those beams."""
    suspended = []
    for beam in beams_of_license(license_record):
        if beam["beam_state"] == "ACTIVE":
            beam["beam_state"] = "SUSPENDED"
            touch(beam)
            suspended.append(beam)
    return suspended


def enforcement_cascade(license_record):
    """The shared cascade of a licence SUSPEND and of a licence EXPIRY.

    Hop 1 beams out of service; hop 2 their subscriptions deauthorised and
    stamped; hop 3 those subscriptions' approved roaming revoked; hop 4 the
    affected cells recompute (landing on CLOSED because the beam is down).
    """
    suspended_beams = suspend_beams_of_license(license_record)

    for beam in suspended_beams:
        for subscription in subscriptions_of_beam(beam):
            if subscription["authorization_state"] in AUTHORIZED_STATES:
                subscription["authorization_state"] = "DEAUTHORIZED"
                subscription["deauthorized_by_license_id"] = license_record["id"]
                touch(subscription)
                for roaming in ordered(
                    [
                        r
                        for r in db.roaming.values()
                        if r["subscription_id"] == subscription["id"]
                    ]
                ):
                    if roaming["auth_state"] == "APPROVED":
                        roaming["auth_state"] = "REVOKED"
                        roaming["revoked_reason"] = "LICENSE_SUSPENDED"
                        touch(roaming)

    for beam in suspended_beams:
        for cell in cells_of_beam(beam):
            touch(cell)

    return suspended_beams


def reinstate_cascade(license_record):
    """The compensating transition; roaming grants are deliberately not restored."""
    restored_beams = []
    for beam in beams_of_license(license_record):
        if beam["beam_state"] == "SUSPENDED":
            beam["beam_state"] = "ACTIVE"
            touch(beam)
            restored_beams.append(beam)

    for subscription in ordered(list(db.subscriptions.values())):
        if (
            subscription["deauthorized_by_license_id"] == license_record["id"]
            and subscription["service_state"] != "TERMINATED"
        ):
            subscription["authorization_state"] = "AUTHORIZED_FIXED"
            subscription["deauthorized_by_license_id"] = None
            touch(subscription)

    for beam in restored_beams:
        for cell in cells_of_beam(beam):
            touch(cell)

    return restored_beams


def expire_license(license_record):
    """ACTIVE -> EXPIRED with the same four hops a suspension runs."""
    license_record["license_state"] = "EXPIRED"
    touch(license_record)
    enforcement_cascade(license_record)


def select_governing_license(jurisdiction_code):
    """Roaming approval: longest-lived live-and-coordinated licence wins."""
    candidates = [
        l
        for l in db.licenses.values()
        if l["jurisdiction_code"] == jurisdiction_code
        and l["license_state"] == "ACTIVE"
        and l["coordination_state"] == "COORDINATED"
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda l: (-l["expires_at"].timestamp(), l["created_at"], l["_seq"])
    )
    return candidates[0]

"""Derived-field reconciliation and cascades (PRD 2.6, 2.7, 3.x)."""

from core import db, dec, now, new_record, touch, q2, sort_rows

LIVE_LIFECYCLE = ("ISSUED", "PARTIALLY_REDEEMED")
OPEN_REDEMPTION = ("ALLOCATED", "HELD_PENDING_COMPLIANCE")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def municipal_bank():
    for party in db.parties.values():
        if party["kind"] == "MUNICIPAL_BANK":
            return party
    return None


def certificates_of_easement(easement_id):
    return [c for c in db.certificates.values() if c["conservation_easement_id"] == easement_id]


def easement_of_parcel(parcel_id):
    rows = [e for e in db.conservation_easements.values() if e["sending_parcel_id"] == parcel_id]
    return sort_rows(rows)[0] if rows else None


def transactions_of_certificate(certificate_id):
    return sort_rows([t for t in db.market_transactions.values() if t["certificate_id"] == certificate_id])


def redemptions_of_certificate(certificate_id):
    return sort_rows([r for r in db.certificate_redemptions.values() if r["certificate_id"] == certificate_id])


def redemptions_of_application(application_id):
    return sort_rows(
        [r for r in db.certificate_redemptions.values() if r["receiving_site_application_id"] == application_id]
    )


def redemptions_of_area(area_id):
    result = []
    for red in db.certificate_redemptions.values():
        app = db.receiving_site_applications.get(red["receiving_site_application_id"])
        if app is not None and app["receiving_area_id"] == area_id:
            result.append(red)
    return sort_rows(result)


def parcels_of_area(area_id):
    return [p for p in db.sending_parcels.values() if p["sending_area_id"] == area_id]


def certificate_easement(cert):
    return db.conservation_easements.get(cert["conservation_easement_id"])


def easement_compliance_ok(easement):
    return easement is None or easement["compliance_status"] in ("COMPLIANT", "CURED")


def available_units(cert):
    return int(cert["units_remaining"]) - int(cert["units_encumbered"])


# ---------------------------------------------------------------------------
# Chain of title
# ---------------------------------------------------------------------------
def append_transfer(cert, transfer_type, from_party_id, to_party_id, units,
                    price_cents=None, market_transaction_id=None):
    rows = [t for t in db.certificate_transfers.values() if t["certificate_id"] == cert["id"]]
    seq_no = len(rows) + 1
    row = new_record(
        {
            "certificate_id": cert["id"],
            "from_party_id": from_party_id,
            "to_party_id": to_party_id,
            "market_transaction_id": market_transaction_id,
            "seq_no": seq_no,
            "transfer_type": transfer_type,
            "units": int(units),
            "price_cents": price_cents,
            "recorded_at": now(),
        },
        common=False,
    )
    db.certificate_transfers[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# Derived recomputation
# ---------------------------------------------------------------------------
def recompute_certificate_units(cert):
    cert["units_remaining"] = (
        int(cert["units_face"]) - int(cert["units_split_out"]) - int(cert["units_redeemed"]) - int(cert["units_retired"])
    )
    return cert


def recompute_party_holdings(party):
    """Holding recomputes never touch Party.version (PRD 2.4)."""
    if party is None:
        return
    units = 0
    count = 0
    for cert in db.certificates.values():
        if cert["holder_party_id"] != party["id"]:
            continue
        if cert["lifecycle_status"] in LIVE_LIFECYCLE:
            units += int(cert["units_remaining"])
            count += 1
    party["units_held"] = units
    party["certificates_held_count"] = count


def recompute_sending_area_severed(area):
    total = 0
    parcel_ids = {p["id"] for p in parcels_of_area(area["id"])}
    for app in db.severance_applications.values():
        if app["sending_parcel_id"] in parcel_ids and app["status"] == "CERTIFIED":
            total += int(app["allocated_units"] or 0)
    area["severed_units_total"] = total
    return total


def recompute_receiving_area_units(area):
    absorbed = 0
    reserved = 0
    for red in redemptions_of_area(area["id"]):
        if red["status"] == "CONFIRMED":
            absorbed += int(red["units"])
        elif red["status"] in OPEN_REDEMPTION:
            reserved += int(red["units"])
    area["absorbed_units"] = absorbed
    area["reserved_units"] = reserved


def recompute_application_backing(app):
    backed = 0
    pending = 0
    for red in redemptions_of_application(app["id"]):
        if red["status"] == "CONFIRMED":
            backed += int(red["units"])
        elif red["status"] == "ALLOCATED":
            pending += int(red["units"])
    app["backed_units"] = backed
    app["pending_backed_units"] = pending


def recompute_easement_units(easement):
    if easement is None:
        return
    confirmed = 0
    for red in db.certificate_redemptions.values():
        if red["source_easement_id"] == easement["id"] and red["status"] == "CONFIRMED":
            confirmed += int(red["units"])
    retired = 0
    for cert in certificates_of_easement(easement["id"]):
        retired += int(cert["units_retired"])
    easement["units_redeemed_confirmed"] = confirmed
    easement["units_retired"] = retired
    easement["units_outstanding"] = int(easement["units_issued_total"]) - confirmed - retired


def apply_backing_state(app):
    """DESIGN_APPROVED <-> BACKING_DEFICIENT depends on backed + pending vs required."""
    total = int(app["backed_units"]) + int(app["pending_backed_units"])
    required = int(app["required_backing_units"])
    if app["status"] == "DESIGN_APPROVED" and total < required:
        app["status"] = "BACKING_DEFICIENT"
    elif app["status"] == "BACKING_DEFICIENT" and total >= required:
        app["status"] = "DESIGN_APPROVED"


# ---------------------------------------------------------------------------
# Sending area closure cascade (PRD 3.2)
# ---------------------------------------------------------------------------
def close_sending_area(area):
    area["status"] = "CLOSED"
    touch(area)
    parcel_ids = {p["id"] for p in parcels_of_area(area["id"])}
    for app in sort_rows(list(db.severance_applications.values())):
        if app["sending_parcel_id"] in parcel_ids and app["status"] in (
            "SUBMITTED",
            "UNDER_REVIEW",
            "REVISION_REQUESTED",
        ):
            app["status"] = "SUSPENDED"
            app["denial_reason"] = "SENDING_AREA_CLOSED"
            touch(app)


# ---------------------------------------------------------------------------
# Compliance freeze cascade (PRD 3.9)
# ---------------------------------------------------------------------------
def freeze_cascade(easement, cure_deadline):
    easement["compliance_status"] = "VIOLATION_NOTICED"
    easement["cure_deadline"] = cure_deadline
    easement["prior_violation_count"] = int(easement["prior_violation_count"]) + 1
    touch(easement)

    frozen_ids = []
    for cert in sort_rows(certificates_of_easement(easement["id"])):
        if cert["market_status"] not in ("HELD", "UNDER_CONTRACT"):
            continue
        was_under_contract = cert["market_status"] == "UNDER_CONTRACT"
        cert["market_status"] = "FROZEN"
        touch(cert)
        frozen_ids.append(cert["id"])
        if was_under_contract:
            for txn in transactions_of_certificate(cert["id"]):
                if txn["status"] != "PROPOSED":
                    continue
                txn["status"] = "CANCELLED"
                txn["reversal_reason"] = "EASEMENT_NONCOMPLIANT"
                touch(txn)
                cert["units_encumbered"] = max(0, int(cert["units_encumbered"]) - int(txn["units"]))

    touched_apps = {}
    for red in sort_rows(list(db.certificate_redemptions.values())):
        if red["certificate_id"] not in frozen_ids or red["status"] != "ALLOCATED":
            continue
        red["status"] = "HELD_PENDING_COMPLIANCE"
        touch(red)
        app = db.receiving_site_applications.get(red["receiving_site_application_id"])
        if app is not None:
            touched_apps[app["id"]] = app

    for app in sort_rows(list(touched_apps.values())):
        recompute_application_backing(app)
        if app["status"] == "DESIGN_APPROVED" and (
            int(app["backed_units"]) + int(app["pending_backed_units"]) < int(app["required_backing_units"])
        ):
            app["status"] = "BACKING_DEFICIENT"
        touch(app)
        area = db.receiving_areas.get(app["receiving_area_id"])
        if area is not None:
            recompute_receiving_area_units(area)


# ---------------------------------------------------------------------------
# Compensating cascade on a verified cure (PRD 3.9)
# ---------------------------------------------------------------------------
def cure_cascade(easement):
    easement["compliance_status"] = "CURED"
    easement["cure_deadline"] = None
    touch(easement)

    thawed_ids = []
    for cert in sort_rows(certificates_of_easement(easement["id"])):
        if cert["market_status"] == "FROZEN":
            cert["market_status"] = "HELD"
            touch(cert)
            thawed_ids.append(cert["id"])

    touched_apps = {}
    for red in sort_rows(list(db.certificate_redemptions.values())):
        if red["certificate_id"] not in thawed_ids or red["status"] != "HELD_PENDING_COMPLIANCE":
            continue
        red["status"] = "ALLOCATED"
        touch(red)
        app = db.receiving_site_applications.get(red["receiving_site_application_id"])
        if app is not None:
            touched_apps[app["id"]] = app

    for app in sort_rows(list(touched_apps.values())):
        recompute_application_backing(app)
        if app["status"] == "BACKING_DEFICIENT" and (
            int(app["backed_units"]) + int(app["pending_backed_units"]) >= int(app["required_backing_units"])
        ):
            app["status"] = "DESIGN_APPROVED"
        touch(app)
        area = db.receiving_areas.get(app["receiving_area_id"])
        if area is not None:
            recompute_receiving_area_units(area)

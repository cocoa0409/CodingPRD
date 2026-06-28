"""Entity constructors and serializers.

Common audit fields (PRD section 2.4):
  - Full-audit entities carry id, created_at, updated_at, version.
    (Clinic, PetOwner, Cooler, Retort, CremationBatch, Case, TransportLeg,
     KeepsakeOrder, ReturnRoute, MemorialAddon, Invoice)
  - Append-only minimal entities carry only id, created_at.
    (CustodyEvent, CertificateRecord)

Derived (source: computed) fields are always recomputed by the server and
reflected at serialization time; they are never client-supplied.
"""

from db import store


# --- constants for pricing / catalogs --------------------------------------
PRIVATE_RATE = {"SMALL": 12000, "MEDIUM": 18000, "LARGE": 26000, "XLARGE": 38000}
EXPEDITE_SURCHARGE = 5000
COMMUNAL_FIRING_TOTAL_CENTS = 30000

KEEPSAKE_CATALOG_CENTS = {
    "PAW_PRINT": 4500,
    "CLAY_IMPRESSION": 5500,
    "FUR_CLIPPING": 2000,
    "URN": 8000,
    "PENDANT": 9500,
}
MEMORIAL_CATALOG_CENTS = {
    "ONLINE_MEMORIAL": 3000,
    "VIEWING_SESSION": 12000,
    "TRIBUTE_VIDEO": 7000,
}

VIEWING_BUFFER_MINUTES = 15
DEFAULT_CREDIT_LIMIT_CENTS = 500000


def _audit_create():
    now = store.clock.now_iso()
    return {
        "id": store.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version (a mutation)."""
    entity["updated_at"] = store.clock.now_iso()
    entity["version"] = entity["version"] + 1


# ===========================================================================
# weight tier
# ===========================================================================
def compute_weight_tier(weight_lbs):
    if weight_lbs <= 25:
        return "SMALL"
    elif weight_lbs <= 75:
        return "MEDIUM"
    elif weight_lbs <= 150:
        return "LARGE"
    return "XLARGE"


# ===========================================================================
# Clinic
# ===========================================================================
def make_clinic(name, account_code, credit_limit_cents):
    c = _audit_create()
    c.update({
        "name": name,
        "account_code": account_code,
        "credit_limit_cents": credit_limit_cents,
        "outstanding_balance_cents": 0,
        "account_status": "CURRENT",
    })
    store.clinics[c["id"]] = c
    return c


def serialize_clinic(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "account_code": c["account_code"],
        "credit_limit_cents": c["credit_limit_cents"],
        "outstanding_balance_cents": c["outstanding_balance_cents"],
        "account_status": c["account_status"],
    }


# ===========================================================================
# PetOwner
# ===========================================================================
def make_petowner(full_name, email, phone):
    p = _audit_create()
    p.update({"full_name": full_name, "email": email, "phone": phone})
    store.petowners[p["id"]] = p
    return p


def serialize_petowner(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "full_name": p["full_name"],
        "email": p["email"],
        "phone": p["phone"],
    }


# ===========================================================================
# Cooler
# ===========================================================================
def make_cooler(label, total_capacity):
    c = _audit_create()
    c.update({"label": label, "total_capacity": total_capacity})
    store.coolers[c["id"]] = c
    return c


def cooler_occupied_count(cooler):
    return sum(
        1 for case in store.cases.values()
        if case.get("cooler_id") == cooler["id"] and case["custody_status"] == "IN_COOLER"
    )


def serialize_cooler(c):
    occupied = cooler_occupied_count(c)
    available = max(0, c["total_capacity"] - occupied)
    status = "FULL" if occupied >= c["total_capacity"] else "AVAILABLE"
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "label": c["label"],
        "total_capacity": c["total_capacity"],
        "occupied_count": occupied,
        "available_capacity": available,
        "status": status,
    }


# ===========================================================================
# Retort
# ===========================================================================
def make_retort(label, max_load_lbs):
    r = _audit_create()
    r.update({"label": label, "max_load_lbs": max_load_lbs})
    store.retorts[r["id"]] = r
    return r


def serialize_retort(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "label": r["label"],
        "max_load_lbs": r["max_load_lbs"],
    }


# ===========================================================================
# CremationBatch
# ===========================================================================
def make_batch(retort_id, service_type, scheduled_start, scheduled_end):
    b = _audit_create()
    b.update({
        "retort_id": retort_id,
        "service_type": service_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "OPEN",
        "communal_firing_total_cents": 0,
    })
    store.batches[b["id"]] = b
    return b


def batch_members(batch):
    """Member cases of a batch with custody_status NOT IN {CANCELLED}."""
    return [
        case for case in store.cases.values()
        if case.get("batch_id") == batch["id"] and case["custody_status"] != "CANCELLED"
    ]


def batch_member_count(batch):
    return len(batch_members(batch))


def batch_loaded_weight(batch):
    return sum(c["weight_lbs"] for c in batch_members(batch))


def serialize_batch(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "retort_id": b["retort_id"],
        "service_type": b["service_type"],
        "scheduled_start": b["scheduled_start"],
        "scheduled_end": b["scheduled_end"],
        "status": b["status"],
        "member_count": batch_member_count(b),
        "loaded_weight_lbs": batch_loaded_weight(b),
        "communal_firing_total_cents": b["communal_firing_total_cents"],
    }


# ===========================================================================
# Case
# ===========================================================================
def make_case(clinic_id, owner_id, pet_name, species, weight_lbs, service_type,
              expedited, pickup_kind, bill_to):
    c = _audit_create()
    c.update({
        "clinic_id": clinic_id,
        "owner_id": owner_id,
        "batch_id": None,
        "cooler_id": None,
        "pet_name": pet_name,
        "species": species,
        "weight_lbs": weight_lbs,
        "service_type": service_type,
        "expedited": expedited,
        "pickup_kind": pickup_kind,
        "bill_to": bill_to,
        "custody_status": "INTAKE_PENDING",
        "billing_status": "NOT_BILLABLE",
        "cremation_charge_cents": 0,
        "custody_chain_open": True,
        "_custody_seq": 0,
    })
    store.cases[c["id"]] = c
    return c


def serialize_case(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "clinic_id": c["clinic_id"],
        "owner_id": c["owner_id"],
        "batch_id": c["batch_id"],
        "cooler_id": c["cooler_id"],
        "pet_name": c["pet_name"],
        "species": c["species"],
        "weight_lbs": c["weight_lbs"],
        "weight_tier": compute_weight_tier(c["weight_lbs"]),
        "service_type": c["service_type"],
        "expedited": c["expedited"],
        "pickup_kind": c["pickup_kind"],
        "bill_to": c["bill_to"],
        "custody_status": c["custody_status"],
        "billing_status": c["billing_status"],
        "cremation_charge_cents": c["cremation_charge_cents"],
        "custody_chain_open": c["custody_chain_open"],
    }


# ===========================================================================
# TransportLeg
# ===========================================================================
def make_transport_leg(case_id, origin_kind, origin_label, driver_name):
    t = _audit_create()
    t.update({
        "case_id": case_id,
        "origin_kind": origin_kind,
        "origin_label": origin_label,
        "driver_name": driver_name,
        "status": "ASSIGNED",
    })
    store.transport_legs[t["id"]] = t
    return t


def serialize_transport_leg(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "case_id": t["case_id"],
        "origin_kind": t["origin_kind"],
        "origin_label": t["origin_label"],
        "driver_name": t["driver_name"],
        "status": t["status"],
    }


# ===========================================================================
# CustodyEvent (append-only, minimal)
# ===========================================================================
def append_custody_event(case, event_type, custodian):
    seq = case.get("_custody_seq", 0) + 1
    case["_custody_seq"] = seq
    now = store.clock.now_iso()
    ev = {
        "id": store.new_id(),
        "created_at": now,
        "_seq": store.next_seq(),
        "case_id": case["id"],
        "seq": seq,
        "event_type": event_type,
        "custodian": custodian,
        "occurred_at": now,
    }
    store.custody_events[ev["id"]] = ev
    return ev


def serialize_custody_event(ev):
    return {
        "id": ev["id"],
        "created_at": ev["created_at"],
        "case_id": ev["case_id"],
        "seq": ev["seq"],
        "event_type": ev["event_type"],
        "custodian": ev["custodian"],
        "occurred_at": ev["occurred_at"],
    }


# ===========================================================================
# KeepsakeOrder
# ===========================================================================
def make_keepsake_order(case_id, item_type):
    k = _audit_create()
    k.update({
        "case_id": case_id,
        "item_type": item_type,
        "unit_price_cents": KEEPSAKE_CATALOG_CENTS[item_type],
        "status": "ORDERED",
    })
    store.keepsake_orders[k["id"]] = k
    return k


def serialize_keepsake_order(k):
    return {
        "id": k["id"],
        "created_at": k["created_at"],
        "updated_at": k["updated_at"],
        "version": k["version"],
        "case_id": k["case_id"],
        "item_type": k["item_type"],
        "unit_price_cents": k["unit_price_cents"],
        "status": k["status"],
    }


# ===========================================================================
# CertificateRecord (append-only, minimal)
# ===========================================================================
def issue_certificate(case):
    now = store.clock.now_iso()
    cert = {
        "id": store.new_id(),
        "created_at": now,
        "_seq": store.next_seq(),
        "case_id": case["id"],
        "certificate_number": store.next_certificate_number(),
        "pet_name": case["pet_name"],
        "service_type": case["service_type"],
        "cremated_at": now,
        "status": "ISSUED",
    }
    store.certificates[cert["id"]] = cert
    return cert


def serialize_certificate(cert):
    return {
        "id": cert["id"],
        "created_at": cert["created_at"],
        "case_id": cert["case_id"],
        "certificate_number": cert["certificate_number"],
        "pet_name": cert["pet_name"],
        "service_type": cert["service_type"],
        "cremated_at": cert["cremated_at"],
        "status": cert["status"],
    }


# ===========================================================================
# ReturnRoute
# ===========================================================================
def make_return_route(case_id, return_method, destination_label):
    r = _audit_create()
    r.update({
        "case_id": case_id,
        "return_method": return_method,
        "destination_label": destination_label,
        "status": "PLANNED",
    })
    store.return_routes[r["id"]] = r
    return r


def serialize_return_route(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "case_id": r["case_id"],
        "return_method": r["return_method"],
        "destination_label": r["destination_label"],
        "status": r["status"],
    }


# ===========================================================================
# MemorialAddon
# ===========================================================================
def make_memorial_addon(case_id, addon_type, viewing_room_code, viewing_start, viewing_end):
    m = _audit_create()
    m.update({
        "case_id": case_id,
        "addon_type": addon_type,
        "price_cents": MEMORIAL_CATALOG_CENTS[addon_type],
        "viewing_room_code": viewing_room_code,
        "viewing_start": viewing_start,
        "viewing_end": viewing_end,
        "status": "BOOKED",
    })
    store.memorial_addons[m["id"]] = m
    return m


def serialize_memorial_addon(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "case_id": m["case_id"],
        "addon_type": m["addon_type"],
        "price_cents": m["price_cents"],
        "viewing_room_code": m["viewing_room_code"],
        "viewing_start": m["viewing_start"],
        "viewing_end": m["viewing_end"],
        "status": m["status"],
    }


# ===========================================================================
# Invoice
# ===========================================================================
def make_invoice(case_id, clinic_id, bill_to, subtotal_cents, handling_fee_cents, total_cents):
    inv = _audit_create()
    inv.update({
        "case_id": case_id,
        "clinic_id": clinic_id,
        "bill_to": bill_to,
        "subtotal_cents": subtotal_cents,
        "handling_fee_cents": handling_fee_cents,
        "total_cents": total_cents,
        "status": "ISSUED",
    })
    store.invoices[inv["id"]] = inv
    return inv


def serialize_invoice(inv):
    return {
        "id": inv["id"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
        "case_id": inv["case_id"],
        "clinic_id": inv["clinic_id"],
        "bill_to": inv["bill_to"],
        "subtotal_cents": inv["subtotal_cents"],
        "handling_fee_cents": inv["handling_fee_cents"],
        "total_cents": inv["total_cents"],
        "status": inv["status"],
    }

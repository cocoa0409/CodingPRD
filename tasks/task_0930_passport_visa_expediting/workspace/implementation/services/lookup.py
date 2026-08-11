"""Parent/child navigation helpers over the in-memory store."""
import store


def catalog_of(order):
    return store.get("catalog_items", order["catalog_item_id"])


def consulate_of(order):
    if not order.get("consulate_id"):
        return None
    return store.get("consulates", order["consulate_id"])


def applicants_of(order):
    return store.sort_default(
        [a for a in store.all_rows("applicants") if a["order_id"] == order["id"]]
    )


def counted_applicants(order):
    return [a for a in applicants_of(order) if a["readiness_status"] in ("PENDING", "COMPLETE")]


def documents_of(applicant):
    return store.sort_default(
        [d for d in store.all_rows("documents") if d["applicant_id"] == applicant["id"]]
    )


def photos_of(applicant):
    return store.sort_default(
        [p for p in store.all_rows("photos") if p["applicant_id"] == applicant["id"]]
    )


def prepared_forms_of(applicant):
    return store.sort_default(
        [f for f in store.all_rows("prepared_forms") if f["applicant_id"] == applicant["id"]]
    )


def appointments_of(applicant):
    return store.sort_default(
        [a for a in store.all_rows("appointments") if a["applicant_id"] == applicant["id"]]
    )


def legs_of(order):
    return store.sort_by(
        [l for l in store.all_rows("courier_legs") if l["order_id"] == order["id"]],
        "leg_index",
    )


def custody_events_of(order):
    return store.sort_by(
        [c for c in store.all_rows("custody_events") if c["order_id"] == order["id"]],
        "acquired_at",
    )


def sla_segments_of(order):
    return store.sort_by(
        [s for s in store.all_rows("sla_segments") if s["order_id"] == order["id"]],
        "started_at",
    )


def rfes_of(order):
    return store.sort_default([r for r in store.all_rows("rfes") if r["order_id"] == order["id"]])


def ledger_of(order):
    return store.sort_default(
        [e for e in store.all_rows("ledger_entries") if e["order_id"] == order["id"]]
    )


def shipments_of(order):
    return store.sort_default(
        [s for s in store.all_rows("shipments") if s["order_id"] == order["id"]]
    )


def requirements_of(catalog_item_id):
    return store.sort_default(
        [r for r in store.all_rows("document_requirements")
         if r["catalog_item_id"] == catalog_item_id]
    )


def order_of_applicant(applicant):
    return store.get("orders", applicant["order_id"])


def order_of_document(document):
    applicant = store.get("applicants", document["applicant_id"])
    return order_of_applicant(applicant) if applicant else None


def order_of_photo(photo):
    applicant = store.get("applicants", photo["applicant_id"])
    return order_of_applicant(applicant) if applicant else None


def order_of_prepared_form(form):
    applicant = store.get("applicants", form["applicant_id"])
    return order_of_applicant(applicant) if applicant else None


def order_of_appointment(appointment):
    applicant = store.get("applicants", appointment["applicant_id"])
    return order_of_applicant(applicant) if applicant else None


def order_of_leg(leg):
    return store.get("orders", leg["order_id"])


def order_of_rfe(rfe):
    return store.get("orders", rfe["order_id"])


def order_of_shipment(shipment):
    return store.get("orders", shipment["order_id"])


def active_form(form_code):
    for row in store.all_rows("agency_forms"):
        if row["form_code"] == form_code and row["status"] == "ACTIVE":
            return row
    return None


def slots_of_consulate(consulate):
    return store.sort_default(
        [s for s in store.all_rows("slots") if s["consulate_id"] == consulate["id"]]
    )


def appointments_on_slot(slot):
    return [a for a in store.all_rows("appointments") if a["slot_id"] == slot["id"]]

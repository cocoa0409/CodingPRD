"""Chain walks: any resource up through Registration / LegalEntity to Client."""

from store import DB


def entity_of_registration(registration):
    if registration is None:
        return None
    return DB.legal_entities.get(registration.get("legal_entity_id"))


def client_of_entity(entity):
    if entity is None:
        return None
    return DB.clients.get(entity.get("client_id"))


def client_of_registration(registration):
    return client_of_entity(entity_of_registration(registration))


def client_id_of_registration(registration):
    entity = entity_of_registration(registration)
    return entity.get("client_id") if entity else None


def registrations_of_entity(entity_id):
    return [r for r in DB.registrations.values() if r["legal_entity_id"] == entity_id]


def entities_of_client(client_id):
    return [e for e in DB.legal_entities.values() if e["client_id"] == client_id]


def registrations_of_client(client_id):
    result = []
    for entity in entities_of_client(client_id):
        result.extend(registrations_of_entity(entity["id"]))
    return result


def obligations_of_registration(registration_id):
    return [o for o in DB.obligations.values() if o["registration_id"] == registration_id]


def obligations_of_client(client_id):
    result = []
    for registration in registrations_of_client(client_id):
        result.extend(obligations_of_registration(registration["id"]))
    return result


def filings_of_client(client_id):
    ids = {r["id"] for r in registrations_of_client(client_id)}
    return [f for f in DB.filings.values() if f["registration_id"] in ids]


def appointments_of_registration(registration_id):
    return [a for a in DB.appointments.values() if a["registration_id"] == registration_id]


def reminders_of_obligation(obligation_id):
    return [n for n in DB.reminders.values() if n["compliance_obligation_id"] == obligation_id]


def sop_documents_of_registration(registration_id):
    return [d for d in DB.sop_documents.values() if d["registration_id"] == registration_id]


def cases_of_registration(registration_id):
    return [c for c in DB.reinstatement_cases.values() if c["registration_id"] == registration_id]


def allocations_of_filing(filing_id):
    return [a for a in DB.allocations.values() if a["filing_id"] == filing_id]


def allocations_of_payment(payment_id):
    return [a for a in DB.allocations.values() if a["payment_id"] == payment_id]


# --- owning-client resolution used by the cross-client rung ----------------
def owning_client_id(collection_name, row):
    if row is None:
        return None
    if collection_name == "clients":
        return row["id"]
    if collection_name in ("legal_entities",):
        return row.get("client_id")
    if collection_name in ("beneficial_owners", "name_clearances", "boi_reports"):
        entity = DB.legal_entities.get(row.get("legal_entity_id"))
        return entity.get("client_id") if entity else None
    if collection_name == "registrations":
        return client_id_of_registration(row)
    if collection_name in (
        "obligations",
        "filings",
        "sop_documents",
        "appointments",
        "reinstatement_cases",
        "certificates",
    ):
        registration = DB.registrations.get(row.get("registration_id"))
        return client_id_of_registration(registration)
    if collection_name == "payments":
        return row.get("client_id")
    if collection_name == "reminders":
        obligation = DB.obligations.get(row.get("compliance_obligation_id"))
        if not obligation:
            return None
        registration = DB.registrations.get(obligation.get("registration_id"))
        return client_id_of_registration(registration)
    if collection_name == "sop_events":
        document = DB.sop_documents.get(row.get("sop_document_id"))
        if not document:
            return None
        registration = DB.registrations.get(document.get("registration_id"))
        return client_id_of_registration(registration)
    if collection_name == "allocations":
        payment = DB.payments.get(row.get("payment_id"))
        return payment.get("client_id") if payment else None
    return None

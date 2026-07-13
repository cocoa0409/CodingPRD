"""Payload factories — one per entity, input fields only.

Optional fields are omitted unless supplied so the server can apply its own
declared defaults. Emails are made unique per call because they must be unique
across the (per-test, freshly-reset) database.
"""
import uuid


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def create_client_payload(name: str = "Test Client", email: str = None,
                          tier: str = None, **overrides) -> dict:
    payload = {"name": name, "email": email or _unique_email("client")}
    if tier is not None:
        payload["tier"] = tier
    payload.update(overrides)
    return payload


def create_researcher_payload(name: str = "Test Researcher", email: str = None,
                              hourly_rate_cents: int = 9000,
                              specialties: list = None, **overrides) -> dict:
    payload = {
        "name": name,
        "email": email or _unique_email("researcher"),
        "hourly_rate_cents": hourly_rate_cents,
    }
    if specialties is not None:
        payload["specialties"] = specialties
    payload.update(overrides)
    return payload


def create_repository_payload(name: str = "Test Repository", location: str = "London",
                              concurrent_capacity: int = None, **overrides) -> dict:
    payload = {"name": name, "location": location}
    if concurrent_capacity is not None:
        payload["concurrent_capacity"] = concurrent_capacity
    payload.update(overrides)
    return payload


def create_project_payload(client_id: str, lead_researcher_id: str,
                           title: str = "Research Request",
                           objective: str = "Trace the family line",
                           package_type: str = "BASIC_PACKAGE",
                           package_price_cents: int = 100000,
                           budget_hours: float = 10,
                           scope_note: str = None,
                           priority: str = None,
                           target_person_count: int = None,
                           **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "lead_researcher_id": lead_researcher_id,
        "title": title,
        "objective": objective,
        "package_type": package_type,
        "package_price_cents": package_price_cents,
        "budget_hours": budget_hours,
    }
    if scope_note is not None:
        payload["scope_note"] = scope_note
    if priority is not None:
        payload["priority"] = priority
    if target_person_count is not None:
        payload["target_person_count"] = target_person_count
    payload.update(overrides)
    return payload


def create_record_search_payload(project_id: str, repository_name: str = "State Archive",
                                 search_terms: str = "surname 1880",
                                 estimated_hours: float = 1, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "repository_name": repository_name,
        "search_terms": search_terms,
        "estimated_hours": estimated_hours,
    }
    payload.update(overrides)
    return payload


def create_citation_payload(record_search_id: str, person_id: str,
                            citation_text: str = "Formatted citation",
                            source_type: str = "VITAL_RECORD",
                            quality: str = "PRIMARY", **overrides) -> dict:
    payload = {
        "record_search_id": record_search_id,
        "person_id": person_id,
        "citation_text": citation_text,
        "source_type": source_type,
        "quality": quality,
    }
    payload.update(overrides)
    return payload


def create_person_payload(project_id: str, full_name: str = "John Smith",
                          birth_year: int = None, death_year: int = None,
                          father_id: str = None, mother_id: str = None,
                          **overrides) -> dict:
    payload = {"project_id": project_id, "full_name": full_name}
    if birth_year is not None:
        payload["birth_year"] = birth_year
    if death_year is not None:
        payload["death_year"] = death_year
    if father_id is not None:
        payload["father_id"] = father_id
    if mother_id is not None:
        payload["mother_id"] = mother_id
    payload.update(overrides)
    return payload


def create_dna_payload(project_id: str, subject_person_id: str,
                       test_provider: str = "AncestryDNA",
                       match_person_id: str = None,
                       addon_fee_cents: int = None, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "subject_person_id": subject_person_id,
        "test_provider": test_provider,
    }
    if match_person_id is not None:
        payload["match_person_id"] = match_person_id
    if addon_fee_cents is not None:
        payload["addon_fee_cents"] = addon_fee_cents
    payload.update(overrides)
    return payload


def create_document_request_payload(project_id: str, repository_id: str,
                                    document_type: str = "Birth certificate",
                                    source_language: str = "German",
                                    needs_translation: bool = None,
                                    pages: int = None, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "repository_id": repository_id,
        "document_type": document_type,
        "source_language": source_language,
    }
    if needs_translation is not None:
        payload["needs_translation"] = needs_translation
    if pages is not None:
        payload["pages"] = pages
    payload.update(overrides)
    return payload


def create_heirloom_payload(project_id: str, description: str = "Family bible",
                            category: str = "DOCUMENT",
                            related_person_id: str = None,
                            storage_location: str = None, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "description": description,
        "category": category,
    }
    if related_person_id is not None:
        payload["related_person_id"] = related_person_id
    if storage_location is not None:
        payload["storage_location"] = storage_location
    payload.update(overrides)
    return payload


def create_deliverable_payload(project_id: str,
                               deliverable_type: str = "RESEARCH_REPORT",
                               milestone_id: str = None,
                               page_count: int = None, **overrides) -> dict:
    payload = {"project_id": project_id, "deliverable_type": deliverable_type}
    if milestone_id is not None:
        payload["milestone_id"] = milestone_id
    if page_count is not None:
        payload["page_count"] = page_count
    payload.update(overrides)
    return payload


def create_milestone_payload(project_id: str, title: str = "Milestone",
                             amount_cents: int = 40000, sequence_no: int = 1,
                             deliverable_id: str = None, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "title": title,
        "amount_cents": amount_cents,
        "sequence_no": sequence_no,
    }
    if deliverable_id is not None:
        payload["deliverable_id"] = deliverable_id
    payload.update(overrides)
    return payload


def create_time_entry_payload(project_id: str, hours: float = 1.0,
                              activity_type: str = "RESEARCH",
                              record_search_id: str = None,
                              billable: bool = None, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "hours": hours,
        "activity_type": activity_type,
    }
    if record_search_id is not None:
        payload["record_search_id"] = record_search_id
    if billable is not None:
        payload["billable"] = billable
    payload.update(overrides)
    return payload


def create_appointment_payload(repository_id: str, project_id: str, researcher_id: str,
                               start_utc: str = "2026-04-01T09:00:00Z",
                               end_utc: str = "2026-04-01T10:00:00Z",
                               purpose: str = None, **overrides) -> dict:
    payload = {
        "repository_id": repository_id,
        "project_id": project_id,
        "researcher_id": researcher_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    if purpose is not None:
        payload["purpose"] = purpose
    payload.update(overrides)
    return payload

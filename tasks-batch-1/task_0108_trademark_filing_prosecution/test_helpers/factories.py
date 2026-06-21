"""Payload factories — one per creatable entity, input fields only.

Each factory provides sensible defaults and accepts **overrides so tests can
control the values they assert on.
"""

DEFAULTS = {
    "APPLICANT_NAME": "Acme US",
    "ATTORNEY_NAME": "A. Counsel",
    "MARK_TEXT": "TESTMARK",
    "GS_DESCRIPTION": "downloadable software",
    "SPECIMEN_URL": "https://example.com/spec.png",
    "FIRST_USE_DATE": "2025-12-01T00:00:00Z",
    "ARGUMENT_TEXT": "substantive remarks",
}


def create_applicant_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["APPLICANT_NAME"],
        "entity_type": "CORPORATION",
        "country_code": "US",
    }
    payload.update(overrides)
    return payload


def create_attorney_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["ATTORNEY_NAME"],
        "bar_number": "BAR-DEFAULT",
        "bar_state": "NY",
    }
    payload.update(overrides)
    return payload


def create_nice_class_payload(class_number, title="Software", **overrides) -> dict:
    payload = {"class_number": class_number, "title": title}
    payload.update(overrides)
    return payload


def create_application_payload(applicant_id, mark_text=None, filing_basis="USE",
                               filing_tier="TEAS_STANDARD", attorney_id=None,
                               **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "mark_text": mark_text or DEFAULTS["MARK_TEXT"],
        "filing_basis": filing_basis,
        "filing_tier": filing_tier,
    }
    if attorney_id is not None:
        payload["attorney_id"] = attorney_id
    payload.update(overrides)
    return payload


def create_goods_services_payload(nice_class_id, description=None,
                                  pre_approved=None, **overrides) -> dict:
    payload = {
        "nice_class_id": nice_class_id,
        "description": description or DEFAULTS["GS_DESCRIPTION"],
    }
    if pre_approved is not None:
        payload["pre_approved"] = pre_approved
    payload.update(overrides)
    return payload


def create_office_action_payload(application_id, ground="MERELY_DESCRIPTIVE",
                                 is_final=None, **overrides) -> dict:
    payload = {"application_id": application_id, "ground": ground}
    if is_final is not None:
        payload["is_final"] = is_final
    payload.update(overrides)
    return payload


def create_office_action_response_payload(office_action_id, argument_text=None,
                                         amends_identification=None, **overrides) -> dict:
    payload = {
        "office_action_id": office_action_id,
        "argument_text": argument_text or DEFAULTS["ARGUMENT_TEXT"],
    }
    if amends_identification is not None:
        payload["amends_identification"] = amends_identification
    payload.update(overrides)
    return payload


def create_statement_of_use_payload(application_id, expected_application_version,
                                    specimen_url=None, first_use_date=None,
                                    extension_number=None, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "specimen_url": specimen_url or DEFAULTS["SPECIMEN_URL"],
        "first_use_date": first_use_date or DEFAULTS["FIRST_USE_DATE"],
        "expected_application_version": expected_application_version,
    }
    if extension_number is not None:
        payload["extension_number"] = extension_number
    payload.update(overrides)
    return payload


def create_ttab_proceeding_payload(proceeding_type, petitioner_applicant_id,
                                   target_application_id=None,
                                   target_registration_id=None, **overrides) -> dict:
    payload = {
        "proceeding_type": proceeding_type,
        "petitioner_applicant_id": petitioner_applicant_id,
    }
    if target_application_id is not None:
        payload["target_application_id"] = target_application_id
    if target_registration_id is not None:
        payload["target_registration_id"] = target_registration_id
    payload.update(overrides)
    return payload


def create_maintenance_filing_payload(registration_id, filing_type,
                                     expected_registration_version, **overrides) -> dict:
    payload = {
        "registration_id": registration_id,
        "filing_type": filing_type,
        "expected_registration_version": expected_registration_version,
    }
    payload.update(overrides)
    return payload


def create_madrid_application_payload(basic_application_id, designated_countries,
                                     **overrides) -> dict:
    payload = {
        "basic_application_id": basic_application_id,
        "designated_countries": designated_countries,
    }
    payload.update(overrides)
    return payload


def decide_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload

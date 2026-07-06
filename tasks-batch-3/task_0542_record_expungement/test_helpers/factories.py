"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "PETITIONER_NAME": "Test Petitioner",
    "DOB": "1990-01-01T00:00:00Z",
    "INCOME_CENTS": 9_000_000,
    "HOUSEHOLD_SIZE": 1,
    "JURISDICTION": "CA-01",
    "OFFENSE_CODE": "PC-1",
    "DISPOSITION_DATE": "2019-06-01T00:00:00Z",
    "SENTENCE_COMPLETION_DATE": "2020-01-01T00:00:00Z",
}


def create_petitioner_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["PETITIONER_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
        "annual_income_cents": DEFAULTS["INCOME_CENTS"],
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
    }
    payload.update(overrides)
    return payload


def create_criminal_record_payload(petitioner_id, **overrides) -> dict:
    """Default is a MISDEMEANOR / CONVICTED record (eligible_on 2022-01-01).

    ``sentence_completion_date`` is only included for a CONVICTED disposition
    (the PRD says it is supplied "only when the disposition is CONVICTED"),
    unless the caller passes it explicitly in ``overrides``.
    """
    disposition = overrides.get("disposition", "CONVICTED")
    payload = {
        "petitioner_id": petitioner_id,
        "offense_code": DEFAULTS["OFFENSE_CODE"],
        "offense_class": "MISDEMEANOR",
        "disposition": "CONVICTED",
        "disposition_date": DEFAULTS["DISPOSITION_DATE"],
    }
    if disposition == "CONVICTED":
        payload["sentence_completion_date"] = DEFAULTS["SENTENCE_COMPLETION_DATE"]
    payload.update(overrides)
    return payload


def create_courtroom_payload(**overrides) -> dict:
    payload = {"name": "Test Courtroom", "jurisdiction_code": DEFAULTS["JURISDICTION"]}
    payload.update(overrides)
    return payload


def create_judge_payload(**overrides) -> dict:
    payload = {"name": "Test Judge", "jurisdiction_code": DEFAULTS["JURISDICTION"]}
    payload.update(overrides)
    return payload


def create_background_vendor_payload(**overrides) -> dict:
    payload = {"name": "Test Vendor", "api_endpoint": "https://vendor.example/hook"}
    payload.update(overrides)
    return payload


def create_petition_payload(petitioner_id, record_ids, **overrides) -> dict:
    payload = {
        "petitioner_id": petitioner_id,
        "jurisdiction_code": DEFAULTS["JURISDICTION"],
        "record_ids": record_ids,
    }
    payload.update(overrides)
    return payload

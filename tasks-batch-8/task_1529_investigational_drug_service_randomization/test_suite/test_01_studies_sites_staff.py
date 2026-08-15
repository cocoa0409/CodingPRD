"""Study, site, and staff onboarding: schema validation, envelope shape,
lifecycle guards, and suspension cascade (PRD §2.2, §2.3, §2.6, §3.1, §3.2)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID, ApiErrorId,
    create_study, create_site, create_fee_schedule, create_staff_member,
    transition_site, transition_study, setup_active_study,
    create_study_payload, create_site_payload, create_shipment_payload, create_lot,
)
from test_helpers import TEST_USERS

SPONSOR = TEST_USERS["sponsor_admin_headers"]


def test_study_missing_required_protocol_number_returns_invalid_request():
    """PRD §2.6: "Request-schema conformance: required fields present, types
    correct, enum values within their declared sets, datetime strings parseable,
    and window fields satisfying a start strictly before their end
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/study_missing_required_protocol_number_returns_invalid_request
    """
    payload = create_study_payload(protocol_number="P-COR-X", title="No Protocol")
    del payload["protocol_number"]
    resp = api_client.create_study(payload, SPONSOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_study_invalid_phase_enum_returns_invalid_request():
    """PRD §3.1: "the trial `phase` (one of `PHASE_I`, `PHASE_II`, `PHASE_III`,
    `PHASE_IV`)". PRD §2.6: "enum values within their declared sets ...
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/study_invalid_phase_enum_returns_invalid_request
    """
    payload = create_study_payload(protocol_number="P-COR-3", title="Bad Enum",
                                   phase="PHASE_V")
    resp = api_client.create_study(payload, SPONSOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_study_get_returns_exactly_created_fields():
    """PRD §3.1: "A new study begins in `DRAFT` status with `version` 1".
    PRD §2.2: "operations that create or modify a resource will return the
    created or updated resource object in the data field."

    Design: Corner/endpoints/study_get_returns_exactly_created_fields
    """
    study = create_study(protocol_number="P-EP-2", title="Roundtrip", phase="PHASE_III",
                         blinding_model="SINGLE_BLIND", max_dose_per_visit_mg=300,
                         unblinding_suspension_threshold_pct=20)
    resp = api_client.get_study(study["id"], SPONSOR)
    data = validate_success(resp)
    assert data["protocol_number"] == "P-EP-2"
    assert data["title"] == "Roundtrip"
    assert data["phase"] == "PHASE_III"
    assert data["blinding_model"] == "SINGLE_BLIND"
    assert data["max_dose_per_visit_mg"] == 300
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["unblinding_suspension_threshold_pct"] == 20


def test_duplicate_protocol_number_returns_409():
    """PRD §3.1: "The protocol number is unique across all studies; creating a
    study with an already-registered `protocol_number` is rejected with
    `ERR_DUPLICATE_PROTOCOL_NUMBER` (HTTP 409)."

    Design: Corner/validations/duplicate_protocol_number_returns_409
    """
    create_study(protocol_number="P-DUP", title="First", phase="PHASE_I",
                 blinding_model="OPEN_LABEL", max_dose_per_visit_mg=100)
    resp = api_client.create_study(
        create_study_payload(protocol_number="P-DUP", title="Second"), SPONSOR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROTOCOL_NUMBER.value, expected_status=409)


def test_study_activate_without_approved_fee_schedule_rejected():
    """PRD §3.1: "Transitioning a study from `DRAFT` to `ACTIVE` — and likewise
    resuming it from `SUSPENDED` to `ACTIVE` — requires at least one fee
    schedule of the study to be in `APPROVED` status; without one the
    transition is rejected with `ERR_NO_APPROVED_FEE_SCHEDULE`."

    Design: Corner/validations/study_activate_without_approved_fee_schedule_rejected
    """
    study = create_study(protocol_number="P-VAL-12", title="Val")
    create_fee_schedule(study["id"])  # stays DRAFT, never approved
    resp = api_client.transition_study(study["id"], {"to": "ACTIVE"}, SPONSOR)
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_FEE_SCHEDULE.value, expected_status=422)
    assert get_success_data(api_client.get_study(study["id"], SPONSOR))["status"] == "DRAFT"


def test_manual_study_suspend_cascades_active_sites_on_hold():
    """PRD §3.1: "An `ACTIVE` study may be suspended manually by a
    `SponsorAdmin`, and it may also suspend itself automatically under the
    blinding-integrity rule of §3.8; either path moves it `ACTIVE` → `SUSPENDED`
    and cascades every `ACTIVE` site of the study to `ON_HOLD`."

    Design: Corner/state_machines/manual_study_suspend_cascades_active_sites_on_hold
    """
    ctx = setup_active_study(protocol_number="P-SM-6")
    s1 = transition_site(create_site(ctx["study"]["id"], site_number="S1")["id"], "ACTIVE")
    s2 = create_site(ctx["study"]["id"], site_number="S2", name="Site 2")  # left INITIATED
    resp = api_client.transition_study(ctx["study"]["id"], {"to": "SUSPENDED"}, SPONSOR)
    assert validate_success(resp)["status"] == "SUSPENDED"
    assert get_success_data(api_client.get_site(s1["id"], SPONSOR))["status"] == "ON_HOLD"
    assert get_success_data(api_client.get_site(s2["id"], SPONSOR))["status"] == "INITIATED"


def test_site_activate_requires_study_active():
    """PRD §3.2: "Its first activation — `INITIATED` → `ACTIVE` — requires the
    owning study to be `ACTIVE` (otherwise `ERR_STUDY_NOT_ACTIVE`) and stamps
    `activated_at` from the logical clock; that stamp is written on the first
    activation only, and later `ON_HOLD` → `ACTIVE` resumes never overwrite it."

    Design: Corner/state_machines/site_activate_requires_study_active
    """
    study = create_study(protocol_number="P-SM-9", title="SM")  # stays DRAFT
    site = create_site(study["id"])
    resp = api_client.transition_site(site["id"], {"to": "ACTIVE"}, SPONSOR)
    validate_error(resp, ApiErrorId.ERR_STUDY_NOT_ACTIVE.value, expected_status=409)
    site_after = get_success_data(api_client.get_site(site["id"], SPONSOR))
    assert site_after["status"] == "INITIATED"
    assert site_after["activated_at"] is None


def test_site_creation_with_unknown_study_returns_study_not_found():
    """PRD §2.6: "Path identifiers and body foreign-key references are validated
    left to right; the first unresolvable reference fails the request. Study,
    site, kit, and subject references yield `ERR_STUDY_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, and `ERR_SUBJECT_NOT_FOUND`
    respectively".

    Design: Corner/entities/site_creation_with_unknown_study_returns_study_not_found
    """
    resp = api_client.create_site(create_site_payload(NON_EXISTENT_UUID), SPONSOR)
    validate_error(resp, ApiErrorId.ERR_STUDY_NOT_FOUND.value, expected_status=404)


def test_staff_is_unblinded_defaults_to_false():
    """PRD §3.2: "staff records carrying `site_id`, `full_name`, a
    `license_number` unique across all staff, and an optional `is_unblinded`
    flag that defaults to `false` — blinded — unless explicitly set."

    Design: Corner/entities/staff_is_unblinded_defaults_to_false
    """
    study = create_study(protocol_number="P-COR-1", phase="PHASE_I",
                       blinding_model="OPEN_LABEL", max_dose_per_visit_mg=100)
    site = create_site(study["id"])
    staff = create_staff_member(site["id"], license_number="L-COR-1",
                                full_name="Default Flag", is_unblinded=None)
    assert staff["is_unblinded"] is False


def test_kit_get_with_unknown_id_returns_kit_not_found():
    """PRD §2.6: "Study, site, kit, and subject references yield
    `ERR_STUDY_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, and
    `ERR_SUBJECT_NOT_FOUND` respectively". PRD §2.2: "The `message` provides a
    human-readable explanation of what went wrong."

    Design: Corner/entities/kit_get_with_unknown_id_returns_kit_not_found
    """
    resp = api_client.get_kit(NON_EXISTENT_UUID, SPONSOR)
    error = validate_error(resp, ApiErrorId.ERR_KIT_NOT_FOUND.value, expected_status=404)
    assert isinstance(error["message"], str) and error["message"].strip()


def test_lot_get_with_unknown_id_returns_generic_not_found():
    """PRD §2.6: "any other referenced entity — a lot, staff member, dispensing
    record, return, excursion, monitor visit, fee schedule, or randomization
    slot — yields `ERR_NOT_FOUND`."

    Design: Corner/errors/lot_get_with_unknown_id_returns_generic_not_found
    """
    resp = api_client.get_lot(NON_EXISTENT_UUID, SPONSOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_kits_list_pagination_envelope_and_defaults():
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items from the beginning of the result set and
    defaults to 0." and "The `meta` object of a list response carries four
    pagination fields: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.2: "The server creates one kit per entry of `kit_numbers`, each
    beginning in `IN_TRANSIT` at the destination site".

    Design: Corner/entities/kits_list_pagination_envelope_and_defaults
    """
    study = create_study(protocol_number="P-COR-4", phase="PHASE_I",
                       blinding_model="OPEN_LABEL", max_dose_per_visit_mg=100)
    site = create_site(study["id"])
    lot = create_lot(study["id"], lot_number="LOT-COR-4")
    get_success_data(api_client.create_shipment(
        create_shipment_payload(lot["id"], site["id"], ["K-PG"]), SPONSOR))
    resp = api_client.list_kits(SPONSOR, params={"site_id": site["id"]})
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert data[0]["status"] == "IN_TRANSIT"

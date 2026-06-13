"""Election lifecycle: creation and period-1 materialization, reads/listing, revoke, discharge,
expiry, the 90/90/60 sequencing constants, and bereavement eligibility. PRD §3.2, §3.3, §3.9,
§3.10, §3.12.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    assert_election,
    assert_benefit_period,
    setup_provider_and_election,
    setup_revoked_election,
    setup_death_discharged_election,
    setup_open_bereavement_case,
    create_provider,
    create_election,
    revoke_election,
    discharge_election,
    open_bereavement_case,
    set_clock,
    create_election_payload,
    create_bereavement_case_payload,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_headers"]
CLINICAL = TEST_USERS["clinical_headers"]
BILLING = TEST_USERS["billing_headers"]


# ─── Cross-entity state dependency: bereavement needs death discharge ─

def test_bereavement_on_revoked_election_rejected(api):
    """PRD §3.10: "A bereavement case may be opened only when the referenced election is
    DISCHARGED with bereavement_required true — that is, only death discharges qualify ... a
    request against an election that is not a death discharge ... is rejected with
    ERR_BEREAVEMENT_NOT_ELIGIBLE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/bereavement_requires_election_discharged_by_death
    """
    provider, election = setup_revoked_election(election_date="2026-01-01T00:00:00Z",
                                                revocation_date="2026-01-10T00:00:00Z")
    payload = create_bereavement_case_payload(election["id"], "2026-01-11T00:00:00Z")
    res = api.create_bereavement_case(payload, CLINICAL)
    validate_error(res, "ERR_BEREAVEMENT_NOT_ELIGIBLE")


def test_bereavement_on_death_discharged_election_opens(api):
    """PRD §3.10: "A bereavement case may be opened only when the referenced election is
    DISCHARGED with bereavement_required true — that is, only death discharges qualify..."

    Design: Difficulty/cross_entity_state_dependency/bereavement_requires_election_discharged_by_death
    """
    provider, election = setup_death_discharged_election(election_date="2026-01-01T00:00:00Z",
                                                         discharge_date="2026-01-05T00:00:00Z")
    payload = create_bereavement_case_payload(election["id"], "2026-01-06T00:00:00Z")
    bc = validate_success(api.create_bereavement_case(payload, CLINICAL), 201)
    assert bc["status"] == "OPEN"


# ─── Corner: create election materializes period 1 ───────────────────

def test_create_election_returns_201_with_period1(api):
    """PRD §3.2: "A new election begins in ELECTED status. Creation immediately materializes the
    first benefit period: a BenefitPeriod with sequence equal to 1, length_days equal to 90,
    start_offset_days equal to 0, and cert_status equal to PENDING_CERT. The election's
    current_period_number is set to 1 and days_used_in_period to 0."

    Design: Corner/entities/create_election_returns_201_with_period1_materialized
    """
    provider = create_provider()
    set_clock("2026-01-01T00:00:00Z")
    res = api.create_election(
        create_election_payload(provider["id"], patient_name="New Pt",
                                election_date="2026-01-01T00:00:00Z",
                                attending_physician_id="ext-att-new"),
        INTAKE)
    election = validate_success(res, 201)
    assert_election(election)
    assert election["status"] == "ELECTED"
    assert election["current_period_number"] == 1
    assert election["days_used_in_period"] == 0
    assert election["version"] == 1


# ─── Corner: get election returns stored entity ──────────────────────

def test_get_election_returns_stored_fields(api):
    """PRD §2.4: "Every persisted resource in this system carries a server-minted id..."
    PRD §3.2: "An IntakeCoordinator elects the hospice benefit for a beneficiary by submitting
    the owning provider_id, the beneficiary's patient_name (which must be non-empty), the
    election_date, and the attending_physician_id."

    Design: Corner/entities/get_election_by_id_returns_stored_entity
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z",
                                                     patient_name="Stored Pt")
    got = validate_success(api.get_election(election["id"], CLINICAL), 200)
    assert got["patient_name"] == "Stored Pt"
    assert got["provider_id"] == provider["id"]


# ─── Corner: list provider elections paginated ───────────────────────

def test_list_provider_elections_array_envelope(api):
    """PRD §2.3: "Every list response carries limit, offset, total_count, and has_more in the
    meta object of the envelope."
    PRD §4 (endpoint): "GET /hospice/providers/{id}/elections — List elections under a provider."

    Design: Corner/entities/list_provider_elections_paginated
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z",
                                                     patient_name="List Pt")
    data, meta = validate_paginated(api.list_provider_elections(
        provider["id"], BILLING, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert len(data) == 1


# ─── Corner: election id is a server-minted bare UUID ────────────────

def test_election_id_is_bare_uuid_version_starts_at_1(api):
    """PRD §2.4: "Every persisted resource in this system carries a server-minted id formatted as
    a UUID with no type prefix ... and a version integer that begins at its initial value and
    increments by one on every mutation of that resource."

    Design: Corner/entities/election_id_is_server_minted_uuid
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z",
                                                     patient_name="Sys Pt")
    assert is_valid_uuid(election["id"]), "id must be a bare UUID with no type prefix"
    assert election["version"] == 1


# ─── Corner: new election initial state ──────────────────────────────

def test_new_election_starts_in_elected(api):
    """PRD §3.2: "A new election begins in ELECTED status."

    Design: Corner/state_machines/new_election_starts_in_elected
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z",
                                                     patient_name="Init Pt")
    assert election["status"] == "ELECTED"


# ─── Corner: revoke already-revoked election rejected ────────────────

def test_revoke_already_revoked_rejected(api):
    """PRD §3.9: "Three operations terminate an active election, each guarded by the requirement
    that the election currently be ELECTED; attempting any of them ... against an election that
    is already REVOKED, DISCHARGED, or EXPIRED is rejected with ERR_ELECTION_NOT_ELECTED
    (HTTP 409)."

    Design: Corner/state_machines/revoke_already_revoked_election_rejected
    """
    provider, election = setup_revoked_election(election_date="2026-01-01T00:00:00Z",
                                                revocation_date="2026-01-05T00:00:00Z")
    res = api.revoke_election(election["id"], {"revocation_date": "2026-01-06T00:00:00Z"}, INTAKE)
    validate_error(res, "ERR_ELECTION_NOT_ELECTED")


# ─── Corner: discharge terminal election locked ──────────────────────

def test_discharge_already_discharged_rejected(api):
    """PRD §3.9: "attempting any of them ... against an election that is already REVOKED,
    DISCHARGED, or EXPIRED is rejected with ERR_ELECTION_NOT_ELECTED (HTTP 409)."

    Design: Corner/state_machines/discharge_terminal_election_locked
    """
    provider, election = setup_death_discharged_election(election_date="2026-01-01T00:00:00Z",
                                                         discharge_date="2026-01-05T00:00:00Z")
    res = api.discharge_election(
        election["id"], {"discharge_date": "2026-01-06T00:00:00Z", "discharge_reason": "DEATH"},
        CLINICAL)
    validate_error(res, "ERR_ELECTION_NOT_ELECTED")


# ─── Corner: discharge by death sets bereavement_required ────────────

def test_discharge_by_death_sets_bereavement_required(api):
    """PRD §3.9: "Discharge sets status to DISCHARGED and records the discharge date as the
    election's revocation_date. Only a DEATH discharge sets bereavement_required to true and
    thereby opens bereavement eligibility..."

    Design: Corner/state_machines/discharge_by_death_sets_bereavement_required
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z",
                                                     patient_name="Se Pt")
    set_clock("2026-01-05T00:00:00Z")
    discharged = discharge_election(election["id"], "2026-01-05T00:00:00Z", "DEATH")
    assert discharged["status"] == "DISCHARGED"
    assert discharged["bereavement_required"] is True


# ─── Corner: revoke does not set bereavement_required ────────────────

def test_revoke_leaves_bereavement_required_false(api):
    """PRD §3.9: "Revocation sets status to REVOKED, records the revocation_date, and forfeits
    the remainder of the current benefit period with no compensation for already-paid care days;
    because revocation is not a death, bereavement_required stays false."

    Design: Corner/state_machines/revoke_does_not_set_bereavement_required
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z",
                                                     patient_name="Rev Pt")
    revoked = revoke_election(election["id"], "2026-01-05T00:00:00Z")
    assert revoked["status"] == "REVOKED"
    assert revoked["bereavement_required"] is False


# ─── Corner: benefit-period sequencing constants ─────────────────────

def test_period1_length_90_offset_0(api):
    """PRD §3.3: "Accordingly a period's nominal length_days is 90 when its sequence is 1 or 2,
    and 60 otherwise. Each period's start_offset_days is the sum of the nominal lengths of all
    earlier periods: period 1 starts at offset 0..."

    Design: Corner/calculations/benefit_period_sequencing_constants_applied
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z",
                                                     patient_name="Seq Pt")
    data, meta = validate_paginated(api.list_election_benefit_periods(election["id"], CLINICAL))
    assert len(data) == 1
    p1 = data[0]
    assert_benefit_period(p1)
    assert p1["sequence"] == 1
    assert p1["length_days"] == 90
    assert p1["start_offset_days"] == 0


# ─── Corner: bereavement close action endpoint ───────────────────────

def test_close_bereavement_case_transitions_to_closed(api):
    """PRD §3.10: "A clinical manager later closes a case, transitioning an OPEN case to CLOSED."

    Design: Corner/endpoints/bereavement_close_action_endpoint
    """
    provider, election, bc = setup_open_bereavement_case(election_date="2026-01-01T00:00:00Z",
                                                         discharge_date="2026-01-05T00:00:00Z",
                                                         enrolled_date="2026-01-06T00:00:00Z")
    closed = validate_success(api.close_bereavement_case(bc["id"], CLINICAL), 200)
    assert closed["status"] == "CLOSED"

"""Provider credentialing: the lapse sweep, renewal, deactivation and rung 15."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_provider,
    book,
    new_provider,
    new_site,
    new_employer,
    read_site,
    set_clock,
    setup_clinic,
    site_version,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["clinic_manager_headers"]


def _lapsing_clinic(employer_code, employer_name, capacity=8):
    """Employer + site + contract + a clinician whose licence expires 2026-06-05."""
    return setup_clinic(
        employer={"legal_name": employer_name, "employer_code": employer_code},
        site={"site_name": f"{employer_code} On-Site Clinic", "daily_slot_capacity": capacity},
        contract={"quota_visits_total": 20},
        provider={"full_name": "Dr Expiring", "license_expiry_date": "2026-06-05"},
        eligibility={"subscriber_external_id": "S-1601", "member_external_id": "M-1601"},
        participant={"display_name": "Cred Tester"},
    )


def test_booking_refused_while_provider_credential_lapsed():
    """PRD §3.2: "When a clock advance crosses that line the provider moves
    `CREDENTIALED → LAPSED`, and from that moment on any booking, reschedule,
    check-in or staffing-shift creation naming that provider is refused with
    `ERR_PROVIDER_CREDENTIAL_LAPSED`."
    PRD §2.5: "**First**, every `Provider` whose `credential_status` is
    `CREDENTIALED` and whose `license_expiry_date` falls strictly before the new
    clock date moves to `LAPSED`; a provider is still credentialed on the expiry date
    itself, because the expiry bound is closed at the top."

    Design: Difficulty/cross_entity_state_dependency/appointment_booking_depends_on_provider_credential_state
    """
    world = _lapsing_clinic("CRD", "Credential Co")

    sweep = set_clock("2026-06-06T00:00:00Z")
    assert world.clinician_id in sweep["lapsed_provider_ids"]

    provider = validate_success(
        api_client.get_provider(world.clinician_id, world.manager_headers)
    )
    assert_provider(provider)
    assert provider["credential_status"] == "LAPSED"

    response = api_client.create_appointment(
        {
            "participant_id": world.participant_id,
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-08T09:00:00Z",
            "expected_site_version": site_version(world.site_id, world.participant_headers),
        },
        world.participant_headers,
    )
    validate_error(response, ApiErrorId.ERR_PROVIDER_CREDENTIAL_LAPSED.value, 422)
    assert read_site(world.site_id)["slots_requested_total"] == 0


def test_booking_accepted_immediately_after_credential_renewal():
    """PRD §3.2: "A `ClinicManager` restores the provider by recording a renewal with
    a fresh `license_expiry_date`, moving the provider `LAPSED → CREDENTIALED`,
    replacing the stored expiry date and incrementing `renewal_count` by one."
    PRD §2.6: "**Provider credentialed.** The named `Provider` carries
    `credential_status` of `CREDENTIALED` at the moment of the write; both `LAPSED`
    and `DEACTIVATED` fail. Otherwise `ERR_PROVIDER_CREDENTIAL_LAPSED`, HTTP 422."

    Design: Difficulty/cross_entity_state_dependency/appointment_booking_depends_on_provider_credential_state
    """
    world = _lapsing_clinic("CRD", "Credential Co")
    set_clock("2026-06-06T00:00:00Z")

    renewed = validate_success(
        api_client.renew_provider_credential(
            world.clinician_id, {"license_expiry_date": "2027-06-30"}, MANAGER
        )
    )
    assert renewed["credential_status"] == "CREDENTIALED"
    assert renewed["renewal_count"] == 1
    assert renewed["license_expiry_date"] == "2027-06-30"

    appointment = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z"
    )
    assert appointment["status"] == "BOOKED"
    assert read_site(world.site_id)["slots_held_count"] == 1


def test_lapsed_credential_preempts_exhausted_day_capacity():
    """PRD §2.6: "Every request, whatever handler it is ultimately bound for, walks
    the same twenty-five rungs in ascending order and returns the **first** failure
    it encounters; no later rung is evaluated once an earlier one has failed, and no
    later rung can mask or override an earlier one."
    PRD §2.6: "**Provider credentialed.** The named `Provider` carries
    `credential_status` of `CREDENTIALED` at the moment of the write; both `LAPSED`
    and `DEACTIVATED` fail. Otherwise `ERR_PROVIDER_CREDENTIAL_LAPSED`, HTTP 422."
    PRD §2.6: "**Site day capacity.** The site's non-cancelled appointment count on
    that `service_date` is strictly less than the site's `daily_slot_capacity` before
    the write. Otherwise `ERR_SLOT_CAPACITY_EXHAUSTED`, HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/lapsed_credential_preempts_site_capacity_exhaustion_on_booking
    """
    world = setup_clinic(
        employer={"legal_name": "Ladder Co", "employer_code": "LAD"},
        site={"site_name": "LAD On-Site Clinic", "daily_slot_capacity": 1},
        contract={"quota_visits_total": 20},
        provider={"full_name": "Dr Short-Licence", "license_expiry_date": "2026-06-05"},
        eligibility={"subscriber_external_id": "S-1301", "member_external_id": "M-1301"},
        participant={"display_name": "Zed Kaur"},
    )
    book(world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z")

    set_clock("2026-06-06T00:00:00Z")
    provider = validate_success(
        api_client.get_provider(world.clinician_id, world.manager_headers)
    )
    assert provider["credential_status"] == "LAPSED"

    response = api_client.create_appointment(
        {
            "participant_id": world.participant_id,
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-08T10:00:00Z",
            "expected_site_version": site_version(world.site_id, world.participant_headers),
        },
        world.participant_headers,
    )
    error = validate_error(
        response, ApiErrorId.ERR_PROVIDER_CREDENTIAL_LAPSED.value, 422
    )
    assert error["error_id"] != ApiErrorId.ERR_SLOT_CAPACITY_EXHAUSTED.value


def test_booking_rejected_at_a_full_site_writes_no_slot():
    """PRD §2.4: "A request that is rejected by any rung of the validation ladder
    writes nothing at all — no counters move, no cascade fires, no `version`
    advances, and no partial state survives the rejection."
    PRD §2.6: "**Provider credentialed.** The named `Provider` carries
    `credential_status` of `CREDENTIALED` at the moment of the write; both `LAPSED`
    and `DEACTIVATED` fail. Otherwise `ERR_PROVIDER_CREDENTIAL_LAPSED`, HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/lapsed_credential_preempts_site_capacity_exhaustion_on_booking
    """
    world = setup_clinic(
        employer={"legal_name": "Ladder Co", "employer_code": "LAD"},
        site={"site_name": "LAD On-Site Clinic", "daily_slot_capacity": 1},
        contract={"quota_visits_total": 20},
        provider={"full_name": "Dr Short-Licence", "license_expiry_date": "2026-06-05"},
        eligibility={"subscriber_external_id": "S-1301", "member_external_id": "M-1301"},
        participant={"display_name": "Zed Kaur"},
    )
    book(world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z")
    set_clock("2026-06-06T00:00:00Z")

    before = read_site(world.site_id)
    response = api_client.create_appointment(
        {
            "participant_id": world.participant_id,
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-08T10:00:00Z",
            "expected_site_version": before["version"],
        },
        world.participant_headers,
    )
    validate_error(response, ApiErrorId.ERR_PROVIDER_CREDENTIAL_LAPSED.value, 422)

    after = read_site(world.site_id)
    assert after["slots_requested_total"] == 1
    assert after["slots_held_count"] == 1
    assert after["version"] == before["version"], "a rejected booking advances nothing"


def test_deactivated_provider_cannot_be_renewed():
    """PRD §3.2: "A `ClinicManager` may deactivate a provider from either
    `CREDENTIALED` or `LAPSED`, moving it to `DEACTIVATED`, after which the provider
    can no longer be named on a booking and can no longer be renewed. `DEACTIVATED`
    is terminal: a renewal attempt against a deactivated provider, or against one
    that is already `CREDENTIALED`, finds no declared transition and is refused with
    `ERR_INVALID_STATE`, as is a second deactivation."

    Design: Corner/state_machines/deactivated_provider_cannot_be_renewed
    """
    set_clock("2026-06-01T00:00:00Z")
    employer = new_employer(legal_name="Deactivate Co", employer_code="DAC")
    site = new_site(site_name="DAC Clinic", host_employer_id=employer["id"])
    provider = new_provider(
        site["id"], full_name="Dr Leaving", license_expiry_date="2027-12-31"
    )

    deactivated = validate_success(
        api_client.deactivate_provider(provider["id"], MANAGER)
    )
    assert deactivated["credential_status"] == "DEACTIVATED"

    validate_error(
        api_client.renew_provider_credential(
            provider["id"], {"license_expiry_date": "2028-12-31"}, MANAGER
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    unchanged = validate_success(api_client.get_provider(provider["id"], MANAGER))
    assert unchanged["renewal_count"] == 0
    assert unchanged["license_expiry_date"] == "2027-12-31"

"""Whose quota a booking drained, and how slots and quota conserve."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_contract_quota_conservation,
    assert_site_slot_conservation,
    book,
    check_in,
    enroll,
    make_navigator_headers,
    make_participant_headers,
    new_contract,
    new_eligibility,
    new_employer,
    new_provider,
    new_shift,
    new_site,
    read_site,
    set_clock,
    setup_clinic,
    site_version,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


def test_near_site_quota_drains_only_the_participants_own_contract():
    """PRD §3.4: "First the eligible set: vendor contracts whose `site_id` equals the
    appointment's site, whose `employer_id` equals the *participant's* employer, whose
    `status` is `ACTIVE` or `TRUED_UP`, and whose `quota_visits_consumed` is strictly
    less than `quota_visits_total` — a contract sitting at exactly its quota is not
    eligible."
    PRD §3.4: "And finally the empty case: when no contract qualifies the booking is
    refused with `ERR_EMPLOYER_QUOTA_EXHAUSTED`, a single error that covers both
    "this employer has no contract at this site at all" and "its quota is used up"."
    PRD §3.4: "At a near-site clinic each employer drains only its own contract, so
    two employers booking the same site consume different quotas while competing for
    one shared `daily_slot_capacity`."

    Design: Corner/calculations/near_site_quota_selector_drains_only_the_participants_own_employer_contract
    """
    set_clock("2026-06-01T00:00:00Z")
    employer_a = new_employer(legal_name="Quota A Co", employer_code="QTA")
    employer_b = new_employer(legal_name="Quota B Co", employer_code="QTB")
    site = new_site(
        site_name="Shared Near-Site", site_type="NEAR_SITE", daily_slot_capacity=8
    )
    contract_a = new_contract(
        site["id"], employer_a["id"], vendor_name="CareNearSite LLC", quota_visits_total=1
    )
    contract_b = new_contract(
        site["id"], employer_b["id"], vendor_name="CareNearSite LLC", quota_visits_total=5
    )
    clinician = new_provider(site["id"])
    new_shift(site["id"], clinician["id"])

    elig_a1 = new_eligibility(
        employer_a["id"], subscriber_external_id="S-A1", member_external_id="M-A1"
    )
    p_a1 = enroll(employer_a["id"], elig_a1["id"], display_name="A One")
    elig_a2 = new_eligibility(
        employer_a["id"], subscriber_external_id="S-A2", member_external_id="M-A2"
    )
    p_a2 = enroll(employer_a["id"], elig_a2["id"], display_name="A Two")
    elig_b1 = new_eligibility(
        employer_b["id"], subscriber_external_id="S-B1", member_external_id="M-B1"
    )
    p_b1 = enroll(employer_b["id"], elig_b1["id"], display_name="B One")

    first = book(p_a1["id"], site["id"], clinician["id"], "2026-06-08T09:00:00Z")
    assert first["quota_contract_id"] == contract_a["id"]

    exhausted = api_client.create_appointment(
        {
            "participant_id": p_a2["id"],
            "site_id": site["id"],
            "provider_id": clinician["id"],
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-08T09:30:00Z",
            "expected_site_version": site_version(
                site["id"], make_participant_headers(p_a2["id"])
            ),
        },
        make_participant_headers(p_a2["id"]),
    )
    validate_error(exhausted, ApiErrorId.ERR_EMPLOYER_QUOTA_EXHAUSTED.value, 409)

    other_employer = book(p_b1["id"], site["id"], clinician["id"], "2026-06-08T10:00:00Z")
    assert other_employer["quota_contract_id"] == contract_b["id"]

    reread_a = validate_success(api_client.get_vendor_contract(contract_a["id"], ADMIN))
    assert reread_a["quota_visits_consumed"] == 1
    assert reread_a["quota_visits_remaining"] == 0
    reread_b = validate_success(api_client.get_vendor_contract(contract_b["id"], ADMIN))
    assert reread_b["quota_visits_consumed"] == 1
    assert reread_b["quota_visits_remaining"] == 4

    site_now = read_site(site["id"])
    assert site_now["slots_held_count"] == 2, (
        "the shared daily capacity was never the binding constraint"
    )


def test_site_slot_buckets_partition_after_cancel_no_show_and_check_in():
    """PRD §2.12: "**Slots conserve within a site.** A site's `slots_requested_total`
    always equals the sum of its `slots_held_count`, `slots_consumed_count`,
    `slots_no_show_count` and `slots_released_count`. Every appointment ever created
    at that site sits in exactly one of those four buckets — held while `BOOKED`,
    consumed once checked in, no-show when marked so, released when cancelled."

    Design: Difficulty/compensating_invariant/book_cancel_noshow_and_checkin_conserve_the_site_slot_partition
    """
    world = setup_clinic(
        employer={"legal_name": "Slot Co", "employer_code": "SLT"},
        site={"site_name": "SLT On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        eligibility={"subscriber_external_id": "S-2301", "member_external_id": "M-2301"},
        participant={"display_name": "Slot Tester"},
    )
    first = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z"
    )
    second = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:30:00Z"
    )
    third = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T10:00:00Z"
    )
    set_clock("2026-06-08T11:00:00Z")

    validate_success(
        api_client.cancel_appointment(
            first["id"], {"cancellation_reason": "PARTICIPANT_REQUEST"},
            world.participant_headers,
        )
    )
    no_show = validate_success(
        api_client.cancel_appointment(
            second["id"], {"cancellation_reason": "NO_SHOW"}, world.clinician_headers
        )
    )
    check_in(third["id"], world.clinician_id)

    assert no_show["status"] == "NO_SHOW"
    assert no_show["cancellation_reason"] == "NO_SHOW"

    site = read_site(world.site_id)
    assert site["slots_requested_total"] == 3
    assert site["slots_held_count"] == 0
    assert site["slots_released_count"] == 1
    assert site["slots_no_show_count"] == 1
    assert site["slots_consumed_count"] == 1
    assert_site_slot_conservation(site)


def test_cancellation_returns_quota_while_no_show_keeps_it():
    """PRD §2.12: "**Employer quota conserves within a vendor contract.** A contract's
    `quota_visits_requested_total` always equals the sum of its `quota_visits_consumed`
    and `quota_visits_released`, and its `quota_visits_remaining` always equals
    `quota_visits_total` minus `quota_visits_consumed`. A cancelled appointment
    releases the employer's quota back; a no-show does not, because the employer
    still paid for the reserved capacity."
    PRD §3.4: "`NO_SHOW` moves the appointment `BOOKED → NO_SHOW` instead, may be
    supplied only by a `Clinician`, and treats the quota very differently: the site's
    `slots_held_count` falls by one, its `slots_no_show_count` rises by one and its
    `version` rises by one, but **the vendor contract's quota counters are not touched
    at all**, because a member who fails to turn up has still consumed the employer's
    reserved capacity."

    Design: Difficulty/compensating_invariant/book_cancel_noshow_and_checkin_conserve_the_site_slot_partition
    """
    world = setup_clinic(
        employer={"legal_name": "Slot Co", "employer_code": "SLT"},
        site={"site_name": "SLT On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        eligibility={"subscriber_external_id": "S-2301", "member_external_id": "M-2301"},
        participant={"display_name": "Slot Tester"},
    )
    first = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z"
    )
    second = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:30:00Z"
    )
    third = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T10:00:00Z"
    )
    set_clock("2026-06-08T11:00:00Z")

    api_client.cancel_appointment(
        first["id"], {"cancellation_reason": "PARTICIPANT_REQUEST"}, world.participant_headers
    )
    api_client.cancel_appointment(
        second["id"], {"cancellation_reason": "NO_SHOW"}, world.clinician_headers
    )
    check_in(third["id"], world.clinician_id)

    contract = validate_success(api_client.get_vendor_contract(world.contract_id, ADMIN))
    assert contract["quota_visits_requested_total"] == 3
    assert contract["quota_visits_consumed"] == 2, (
        "the no-show and the checked-in visit both still consume quota"
    )
    assert contract["quota_visits_released"] == 1
    assert contract["quota_visits_remaining"] == 18
    assert_contract_quota_conservation(contract)


def test_cancellation_counters_are_readable_on_the_next_request():
    """PRD §3.4: "**Cancellation** takes a `cancellation_reason` and forks on it.
    `PARTICIPANT_REQUEST` and `CLINIC_REQUEST` both move the appointment
    `BOOKED → CANCELLED`: the site's `slots_held_count` falls by one, its
    `slots_released_count` rises by one and its `version` rises by one, and on the
    pinned contract `quota_visits_consumed` falls by one, `quota_visits_released`
    rises by one and `quota_visits_remaining` is recomputed — the employer gets its
    reserved capacity back."

    Design: Corner/consistency_model/cancellation_cascade_is_visible_immediately_in_the_same_request
    """
    world = setup_clinic(
        employer={"legal_name": "Immediate Co", "employer_code": "IMM"},
        site={"site_name": "IMM Clinic"},
        with_navigator=True,
        eligibility={"subscriber_external_id": "S-5701", "member_external_id": "M-5701"},
        participant={"display_name": "Imm Tester"},
    )
    appointment = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z"
    )

    cancelled = validate_success(
        api_client.cancel_appointment(
            appointment["id"],
            {"cancellation_reason": "CLINIC_REQUEST"},
            make_navigator_headers(world.navigator_id),
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "CLINIC_REQUEST"

    site = read_site(world.site_id)
    assert site["slots_held_count"] == 0
    assert site["slots_released_count"] == 1
    assert site["slots_requested_total"] == 1

    contract = validate_success(api_client.get_vendor_contract(world.contract_id, ADMIN))
    assert contract["quota_visits_consumed"] == 0
    assert contract["quota_visits_released"] == 1
    assert contract["quota_visits_remaining"] == 10

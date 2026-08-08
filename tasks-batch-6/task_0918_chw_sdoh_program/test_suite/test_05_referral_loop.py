"""The closed referral loop: holding units, responding, delivering, closing,
and the inventory conservation those movements must preserve."""

from test_helpers import (
    ApiErrorId,
    assert_offering_conservation,
    assert_offering_counters,
    assert_same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.constants import UNKNOWN_UUID
from test_helpers.factories import create_referral_payload
from test_helpers.test_users import make_partner_headers


def test_declining_a_two_unit_hold_returns_every_unit_to_availability(api):
    """PRD §3.4: "`DECLINED` moves the referral to `DECLINED`, records the
    supplied reason in `decline_reason`, and releases the hold:
    `allocated_units` falls by `units_requested`, `available_units` rises by the
    same amount, `released_units` rises by the same amount, and the offering's
    `version` increments by 1."
    PRD §3.4: "simultaneously the hold is placed on the offering, raising
    `allocated_units` by `units_requested`, lowering `available_units` by the
    same amount, raising `lifetime_allocated_units` by the same amount, and
    incrementing the offering's `version` by 1."

    Design: Difficulty/compensating_invariant/referral_hold_then_decline_conserves_offering_units
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="W-023", mrn="MRN-210", full_name="Ledger Case",
        household_size=4, monthly_income_cents=95_000,
    )
    org, offering, partner_headers = fx.org_with_offering(capacity_total=3)

    referral = fx.send_referral(
        chw_headers, patient["id"], offering["id"], worker["id"], units_requested=2
    )
    held = fx.read_offering(offering["id"])
    assert_offering_counters(held, available=1, allocated=2, released=0, lifetime=2)

    declined = validate_success(
        api.respond_referral(
            referral["id"],
            {
                "decision": "DECLINED",
                "decline_reason": "Household already served this month",
            },
            partner_headers,
        )
    )
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "Household already served this month"

    after = fx.read_offering(offering["id"])
    assert_offering_counters(
        after, available=3, allocated=0, delivered=0, released=2, expired=0, lifetime=2,
        availability_state="AVAILABLE",
    )


def test_the_hold_and_decline_pair_conserves_both_offering_partitions(api):
    """PRD §2.10: "**Offering units.** An offering's `capacity_total` always
    equals the sum of its `available_units`, its `allocated_units` and its
    `delivered_units`. Released and expired holds return their units to
    `available_units` and never leave that three-way partition; `released_units`
    and `expired_units` are cumulative counters that sit outside it."
    PRD §2.10: "**The hold ledger.** An offering's `lifetime_allocated_units`
    always equals the sum of its `allocated_units`, `delivered_units`,
    `released_units` and `expired_units`. Every unit ever placed on hold ends in
    exactly one of those four buckets. `lifetime_allocated_units` only ever
    increases — it rises when a hold is placed and never falls."
    PRD §3.4: "Finally, a decline increments the patient's
    `unfulfilled_referral_count` by 1; when that count reaches exactly 2, an
    escalation opens with `source_flag` of `REFERRAL_UNFULFILLED`,
    `source_referral_id` naming this referral, `opened_by_user_id` of `SYSTEM`
    and `status` of `OPEN_TIER_1`."

    Design: Difficulty/compensating_invariant/referral_hold_then_decline_conserves_offering_units
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="W-023B", mrn="MRN-210B", full_name="Ledger Case",
        household_size=4, monthly_income_cents=95_000,
    )
    org, offering, partner_headers = fx.org_with_offering(capacity_total=3)

    referral = fx.send_referral(
        chw_headers, patient["id"], offering["id"], worker["id"], units_requested=2
    )
    fx.respond_to_referral(
        partner_headers, referral["id"], "DECLINED",
        "Household already served this month",
    )

    after = fx.read_offering(offering["id"])
    assert_offering_conservation(after)
    assert after["capacity_total"] == (
        after["available_units"] + after["allocated_units"] + after["delivered_units"]
    ), "capacity_total must still partition into available, allocated and delivered"
    assert after["lifetime_allocated_units"] == 2, (
        "lifetime_allocated_units only ever rises and stays at the 2 units ever held"
    )

    reread = fx.read_patient(patient["id"])
    assert reread["unfulfilled_referral_count"] == 1, (
        "a single decline charges the counter once, short of the threshold of 2"
    )
    _rows, meta = validate_paginated(
        api.list_escalations(chw_headers, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0, (
        "the escalation opens only when the count reaches exactly 2"
    )


def test_delivery_from_sent_is_refused(api):
    """PRD §3.4: "**Delivery and closure.** A `ResourcePartner` owning the
    offering records delivery on an `ACCEPTED` referral, which moves it to
    `SERVICE_DELIVERED`, stamps `delivered_at` with the current logical clock,
    and consumes the hold: `allocated_units` falls by `units_requested` and
    `delivered_units` rises by the same amount, with the offering's `version`
    incrementing by 1."
    PRD §2.5: "**Target-entity state precondition** — the target row is in a
    state that permits the requested transition (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/referral_deliver_from_sent_is_rejected
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="C-009", mrn="MRN-C09", full_name="State Case",
    )
    org, offering, partner_headers = fx.org_with_offering(capacity_total=3)
    referral = fx.send_referral(
        chw_headers, patient["id"], offering["id"], worker["id"]
    )

    response = api.deliver_referral(referral["id"], partner_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    unchanged = fx.read_referral(referral["id"])
    assert unchanged["status"] == "SENT"
    assert unchanged["delivered_at"] is None

    assert_offering_counters(
        fx.read_offering(offering["id"]), allocated=1, delivered=0
    )


def test_closing_a_referral_twice_is_refused(api):
    """PRD §3.4: "A `CHW` or a `Supervisor` then closes the loop by supplying an
    `outcome_note`, which moves a referral from `SERVICE_DELIVERED` to `CLOSED`
    or from `DECLINED` to `CLOSED`, stamping `closed_at` with the current
    logical clock and storing the note."
    PRD §2.5: "**Target-entity state precondition** — the target row is in a
    state that permits the requested transition (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/referral_close_twice_second_call_rejected
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="C-010", mrn="MRN-C10", full_name="Loop Case",
    )
    org, offering, partner_headers = fx.org_with_offering(capacity_total=3)
    referral = fx.delivered_referral(
        chw_headers, partner_headers, patient["id"], offering["id"], worker["id"]
    )
    fx.close_referral(chw_headers, referral["id"], "Food box delivered and confirmed")

    response = api.close_referral(
        referral["id"], {"outcome_note": "Duplicate closure attempt"}, chw_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    reread = fx.read_referral(referral["id"])
    assert reread["status"] == "CLOSED"
    assert reread["outcome_note"] == "Food box delivered and confirmed", (
        "the refused second closure must not overwrite the stored note"
    )

    after = fx.read_offering(offering["id"])
    assert_offering_counters(after, available=2, allocated=0, delivered=1)


def test_requesting_one_unit_beyond_availability_is_refused(api):
    """PRD §3.4: "The offering's `available_units` must be greater than or equal
    to `units_requested` at rung 16, or the request fails with
    `ERR_INSUFFICIENT_UNITS`; requesting exactly the remaining units succeeds
    and drives the offering to `EXHAUSTED`, while requesting one unit more
    fails."
    PRD §3.3: "`availability_state` is `AVAILABLE` for as long as
    `available_units` is greater than 0, and flips to `EXHAUSTED` the moment
    `available_units` reaches 0, at which point `exhausted_since` is stamped
    with the current logical clock; when units return and `available_units`
    rises above 0 again, the state flips back to `AVAILABLE` and
    `exhausted_since` returns to null."

    Design: Corner/validations/referral_units_exceeding_availability_rejected
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-040",
        mrn="MRN-C40", full_name="Capacity Case",
    )
    org, offering, _partner = fx.org_with_offering(capacity_total=2)

    exact = fx.send_referral(
        chw_headers, patient["id"], offering["id"], worker["id"], units_requested=2
    )
    assert exact["status"] == "SENT"
    assert exact["units_requested"] == 2

    response = api.create_referral(
        create_referral_payload(
            patient["id"], offering["id"], worker["id"],
            fx.offering_version(offering["id"]), units_requested=1,
        ),
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_UNITS.value, 409)

    after = fx.read_offering(offering["id"])
    assert_offering_counters(
        after, available=0, allocated=2, lifetime=2, availability_state="EXHAUSTED"
    )
    assert_same_instant(
        after["exhausted_since"], "2026-06-01T00:00:00Z", "offering.exhausted_since"
    )


def test_referral_carrying_a_stale_offering_version_is_rejected(api):
    """PRD §2.7: "Sending a referral requires `expected_offering_version`,
    carrying the client's last observed `version` of the `ResourceOffering`
    named by `offering_id`."
    PRD §2.7: "A mismatch is rejected with `ERR_STALE_OFFERING_VERSION` (HTTP
    412)."

    Design: Corner/validations/stale_offering_version_on_referral_create_rejected
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="C-033", mrn="MRN-C33", full_name="OCC Case",
    )
    org, offering, _partner = fx.org_with_offering(capacity_total=5)
    observed_version = offering["version"]

    fx.send_referral(
        chw_headers, patient["id"], offering["id"], worker["id"],
        expected_offering_version=observed_version,
    )

    response = api.create_referral(
        create_referral_payload(
            patient["id"], offering["id"], worker["id"], observed_version
        ),
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_OFFERING_VERSION.value, 412)

    after = fx.read_offering(offering["id"])
    assert_offering_counters(after, available=4, allocated=1, lifetime=1)

    _rows, meta = validate_paginated(
        api.list_referrals(chw_headers, params={"offering_id": offering["id"]})
    )
    assert meta["total_count"] == 1, "the stale request created no second referral"


def test_referral_naming_an_unknown_offering_returns_resource_not_found(api):
    """PRD §2.5: "**Body-referenced existence** — every foreign key supplied in
    the request body resolves. A `patient_id` that does not resolve yields
    `ERR_PATIENT_NOT_FOUND` (404); every other body-supplied reference
    (`instrument_id`, `offering_id`, `opened_by_chw_id`, `assigned_chw_id`,
    `second_chw_id`, `chw_id`, `home_visit_id`, `resource_org_id`,
    `grant_award_id`, `encounter_id`) yields `ERR_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/validations/body_offering_reference_unknown_returns_not_found
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="C-032", mrn="MRN-C32", full_name="Dangling Case",
    )

    response = api.create_referral(
        create_referral_payload(
            patient["id"], UNKNOWN_UUID, worker["id"], patient["version"]
        ),
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

    _rows, meta = validate_paginated(
        api.list_referrals(chw_headers, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0


def test_a_partner_cannot_respond_to_another_organizations_referral(api):
    """PRD §3.4: "A `ResourcePartner` whose `X-User-ID` equals the offering's
    `resource_org_id` responds to a `SENT` referral with a `decision` of either
    `ACCEPTED` or `DECLINED`, optionally supplying a `decline_reason`; a partner
    acting on someone else's referral is rejected at rung 10 with
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.4: "`ACCEPTED` moves the referral to `ACCEPTED` and retains the hold
    on the offering exactly as it stood, incrementing only the referral's
    `version` by 1."

    Design: Corner/validations/partner_cannot_respond_to_another_orgs_referral
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="C-047", mrn="MRN-C47", full_name="Owner Case",
    )
    org_a, offering, partner_a = fx.org_with_offering(capacity_total=3)
    org_b, _partner_b = fx.register_org(
        name="Southside Pantry", contact_email="ops@southside.example"
    )
    referral = fx.send_referral(
        chw_headers, patient["id"], offering["id"], worker["id"]
    )

    intruder = api.respond_referral(
        referral["id"], {"decision": "ACCEPTED"}, make_partner_headers(org_b["id"])
    )
    validate_error(intruder, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    owner = validate_success(
        api.respond_referral(referral["id"], {"decision": "ACCEPTED"}, partner_a)
    )
    assert owner["status"] == "ACCEPTED"

    after = fx.read_offering(offering["id"])
    assert_offering_counters(after, available=2, allocated=1)
    assert after["allocated_units"] == 1, (
        "acceptance retains the hold on the offering exactly as it stood"
    )


def test_referral_with_an_undeclared_urgency_is_a_payload_failure(api):
    """PRD §3.4: "Only a `CHW` may originate one, supplying the `patient_id`,
    the `offering_id` of the offering whose units are being claimed, the
    `opened_by_chw_id` of the worker sending it, an `urgency`, a
    `units_requested` count of at least 1, and the mandatory
    `expected_offering_version`."
    PRD §3.4: "**Acknowledgement deadlines.** The `urgency` selects how long the
    partner has to respond: `ROUTINE` allows 72 hours, `URGENT` allows 24 hours,
    and `EMERGENT` allows just 4 hours."
    PRD §2.5: "**Payload shape and domain rules** — required fields present,
    correct JSON types, declared enum members, scalar range and cross-field
    rules, and uniqueness (`ERR_VALIDATION`, 400)."

    Design: Corner/entities/referral_urgency_invalid_enum_rejected
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="C-005", mrn="MRN-C05", full_name="Enum Case",
    )
    org, offering, _partner = fx.org_with_offering(capacity_total=5)

    response = api.create_referral(
        create_referral_payload(
            patient["id"], offering["id"], worker["id"], offering["version"],
            urgency="IMMEDIATE",
        ),
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    after = fx.read_offering(offering["id"])
    assert_offering_counters(after, available=5, allocated=0, lifetime=0)

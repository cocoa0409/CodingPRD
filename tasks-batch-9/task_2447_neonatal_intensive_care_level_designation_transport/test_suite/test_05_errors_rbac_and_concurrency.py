"""Refusals, role authorization and stale-version writes for the Neonatal Network API.

Covers the PRD areas that govern who may call what and what happens when a
caller is wrong: the role table and the unit-scoped identity convention (§2.1,
§4), the fixed rejection precedence (§2.10), optimistic concurrency on the unit
and on the admission with its two distinct conflict identifiers (§2.6), the
segregation-of-duties chains and the immediacy of cascades (§2.11), and the
milk, surge-authorization and follow-up refusals of §3.5, §3.7 and §3.9.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_admission,
    assert_bed_reservation,
    assert_designation_review,
    assert_milk_batch,
    assert_milk_ledger_balanced,
    assert_referral,
    assert_unit_counts,
    assert_version_incremented,
    factories,
    fixtures,
    make_network_admin_headers,
    make_unit_director_headers,
    make_unit_scoped_user_id,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_START

# ---------------------------------------------------------------------------
# Milk label and status gates
# ---------------------------------------------------------------------------


def test_administering_an_unverified_batch_is_refused(api, network):
    """PRD §3.7: "The batch must be in `VERIFIED` or `PARTIALLY_ADMINISTERED`; a batch still `RECEIVED` and therefore unverified, or `QUARANTINED`, `DISCARDED` or already fully `ADMINISTERED`, is refused with `ERR_MILK_NOT_ADMINISTRABLE`."

    Design: Corner/errors/milk_label_and_status_gates_are_each_triggerable
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N2")
    batch = fixtures.receive_milk_batch(network, admission["id"], label_code="LBL-1")
    assert batch["status"] == "RECEIVED"

    refused = api.administer_milk(
        batch["id"], factories.milk_volume_payload(10.0), network["nurse_2"]
    )
    validate_error(refused, ApiErrorId.MILK_NOT_ADMINISTRABLE)

    unchanged = validate_success(api.get_milk_batch(batch["id"], network["admin"]))
    assert unchanged["status"] == "RECEIVED"
    assert unchanged["administered_ml"] == 0.0
    assert_milk_ledger_balanced(unchanged)


def test_verifying_a_batch_with_the_wrong_label_is_refused(api, network):
    """PRD §3.7: "If the presented code differs from the stored one the verification is refused with `ERR_MILK_LABEL_MISMATCH`; if the verifying `X-User-ID` equals `received_by_user_id` it is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/milk_label_and_status_gates_are_each_triggerable
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N2")
    batch = fixtures.receive_milk_batch(network, admission["id"], label_code="LBL-1")

    refused = api.verify_milk_batch(
        batch["id"], factories.verify_milk_payload("LBL-9"), network["nurse_2"]
    )
    validate_error(refused, ApiErrorId.MILK_LABEL_MISMATCH)

    unchanged = validate_success(api.get_milk_batch(batch["id"], network["admin"]))
    assert unchanged["status"] == "RECEIVED"
    assert unchanged["verified_by_user_id"] is None


def test_a_discarded_batch_is_no_longer_administrable(api, network):
    """PRD §3.7: "Discarding takes a `reason` of `EXPIRED`, `LABEL_MISMATCH`, `QUARANTINE_DISPOSAL` or `FAMILY_REQUEST`, moves the whole `remaining_ml` into `discarded_ml`, leaves `remaining_ml` at zero, and lands the batch at `DISCARDED`."

    PRD §3.7: "The batch must be in `VERIFIED` or `PARTIALLY_ADMINISTERED`; a batch still `RECEIVED` and therefore unverified, or `QUARANTINED`, `DISCARDED` or already fully `ADMINISTERED`, is refused with `ERR_MILK_NOT_ADMINISTRABLE`."

    Design: Corner/errors/milk_label_and_status_gates_are_each_triggerable
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N2")
    batch = fixtures.receive_milk_batch(network, admission["id"], label_code="LBL-1")

    verified = validate_success(
        api.verify_milk_batch(
            batch["id"], factories.verify_milk_payload("LBL-1"), network["nurse_2"]
        )
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == "nurse-2"

    discarded = validate_success(
        api.discard_milk_batch(
            batch["id"], factories.discard_milk_payload("FAMILY_REQUEST"), network["nurse_2"]
        )
    )
    assert_milk_batch(discarded)
    assert discarded["status"] == "DISCARDED"
    assert discarded["discarded_ml"] == 120.0
    assert discarded["administered_ml"] == 0.0
    assert discarded["remaining_ml"] == 0.0

    refused = api.administer_milk(
        batch["id"], factories.milk_volume_payload(10.0), network["nurse_2"]
    )
    validate_error(refused, ApiErrorId.MILK_NOT_ADMINISTRABLE)

    closed = fixtures.read_admission(network, admission["id"])
    assert closed["milk_administered_ml"] == 0.0


# ---------------------------------------------------------------------------
# Surge authorization without staffed capacity
# ---------------------------------------------------------------------------


def _unit_with_half_an_rn_and_one_occupied_bed():
    """A LEVEL_III unit holding 0.5 RN_NICU_CORE FTE, a target of one bed and that
    one bed occupied, so the census gate passes but no staffing headroom is left."""
    env = fixtures.setup_network(
        credentials=(("NEO_BOARD", "neo-1", 1.0), ("RN_NICU_CORE", "rn-half", 0.5)),
    )
    fixtures.patch_unit(env, staffed_bed_target=1, headers=env["dir_a"])
    fixtures.admit_case(env, case_reference="CASE-N1")
    return env


def test_surge_authorization_without_staffed_capacity_is_refused(api):
    """PRD §3.5: "From that staffing capacity the unit's currently committed beds — its `occupied_bed_count` plus its `held_bed_count` — are subtracted."

    PRD §3.5: "When `authorized_beds` comes out as zero the authorization is refused with `ERR_SURGE_NO_STAFFED_CAPACITY`."

    Design: Corner/errors/surge_authorization_without_staffed_capacity_is_refused
    """
    env = _unit_with_half_an_rn_and_one_occupied_bed()
    escalation = fixtures.request_surge(env, requested_beds=2)
    assert escalation["status"] == "REQUESTED"

    refused = api.authorize_surge_escalation(escalation["id"], {}, env["admin"])
    validate_error(refused, ApiErrorId.SURGE_NO_STAFFED_CAPACITY)

    unchanged = validate_success(api.get_surge_escalation(escalation["id"], env["admin"]))
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["authorized_by_user_id"] is None

    unit = fixtures.read_unit(env)
    assert_unit_counts(unit, occupied=1, held=0, available=0, escalation=0, posture="CLOSED")


def test_a_surge_request_with_no_staffing_behind_it_can_be_denied(api):
    """PRD §3.5: "The network may instead refuse the request outright, moving it `REQUESTED → DENIED` and recording the supplied `denial_reason` free text."

    Design: Corner/errors/surge_authorization_without_staffed_capacity_is_refused
    """
    env = _unit_with_half_an_rn_and_one_occupied_bed()
    escalation = fixtures.request_surge(env, requested_beds=2)
    validate_error(
        api.authorize_surge_escalation(escalation["id"], {}, env["admin"]),
        ApiErrorId.SURGE_NO_STAFFED_CAPACITY,
    )

    denied = validate_success(
        api.deny_surge_escalation(
            escalation["id"],
            factories.deny_surge_payload("No staffed capacity behind the request"),
            env["admin"],
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "No staffed capacity behind the request"
    assert denied["authorized_by_user_id"] is None

    unit = fixtures.read_unit(env)
    assert_unit_counts(unit, escalation=0, available=0, posture="CLOSED")


# ---------------------------------------------------------------------------
# Follow-up enrollment of an ineligible graduate
# ---------------------------------------------------------------------------


def _discharged_term_graduate(api, env):
    """Admit a 36.0-week, 2400 g infant in room air, post one care day that omits
    the ventilator flag entirely, and send it home."""
    referral = fixtures.create_referral(
        env,
        case_reference="CASE-TERM1",
        gestational_age_weeks=36.0,
        birth_weight_grams=2400,
        support_modality="ROOM_AIR",
    )
    fixtures.accept_referral(env, referral["id"])
    admission = fixtures.admit(env, referral["id"])

    care = factories.care_update_payload(
        current_weight_grams=2500, support_modality="ROOM_AIR"
    )
    del care["ventilated"]
    stabilized = validate_success(
        api.create_care_update(admission["id"], care, env["nurse"])
    )
    assert stabilized["care_status"] == "STABILIZED"

    return validate_success(
        api.discharge_admission(
            admission["id"], factories.discharge_payload("HOME"), env["intake_a"]
        )
    )


def test_a_term_graduate_is_not_flagged_high_risk(api, network):
    """PRD §3.9: "`high_risk_graduate` on the admission is true exactly when `eligibility_basis` is anything other than `NOT_ELIGIBLE`."

    PRD §3.7: "Each posting increments `patient_days` by one; it increments `central_line_days` by one when `central_line_present` was posted true, and `ventilator_days` by one when `ventilated` was posted true."

    Design: Corner/errors/ineligible_graduate_cannot_be_enrolled
    """
    discharged = _discharged_term_graduate(api, network)
    assert_admission(discharged)
    assert discharged["ventilator_days"] == 0
    assert discharged["patient_days"] == 1
    assert discharged["care_status"] == "DISCHARGED"
    assert discharged["high_risk_graduate"] is False


def test_enrolling_an_ineligible_graduate_is_refused(api, network):
    """PRD §3.9: "An admission whose `eligibility_basis` is `NOT_ELIGIBLE` is refused with `ERR_NOT_ELIGIBLE_FOR_FOLLOWUP`."

    Design: Corner/errors/ineligible_graduate_cannot_be_enrolled
    """
    discharged = _discharged_term_graduate(api, network)

    refused = api.create_follow_up_enrollment(
        factories.follow_up_enrollment_payload(discharged["id"], network["unit_a_id"]),
        network["fu"],
    )
    validate_error(refused, ApiErrorId.NOT_ELIGIBLE_FOR_FOLLOWUP)

    _rows, meta = validate_paginated(api.list_follow_up_enrollments(network["fu"]))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Role-exclusive operations
# ---------------------------------------------------------------------------


def test_a_network_admin_may_not_submit_a_designation_review(api, network):
    """PRD §2.1: "If both headers are present but the value of `X-User-Role` is not one of the roles listed against the endpoint in §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    review = fixtures.open_review(network)

    refused = api.submit_designation_review(review["id"], {}, network["admin"])
    validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED)

    unchanged = validate_success(api.get_designation_review(review["id"], network["admin"]))
    assert_designation_review(unchanged)
    assert unchanged["status"] == "DRAFT"


def test_a_network_admin_may_not_accept_a_referral(api, network):
    """PRD §2.1: "If both headers are present but the value of `X-User-Role` is not one of the roles listed against the endpoint in §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    referral = fixtures.create_referral(network, case_reference="CASE-N1")
    unit_version = fixtures.read_unit_version(network, headers=network["intake_a"])

    refused = api.accept_referral(
        referral["id"],
        factories.accept_referral_payload(unit_version),
        network["admin"],
    )
    validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED)

    unchanged = validate_success(api.get_referral(referral["id"], network["admin"]))
    assert unchanged["status"] == "PENDING"
    assert_unit_counts(fixtures.read_unit(network), occupied=0, held=0, available=4)


def test_a_referring_clinician_may_not_accept_a_referral(api, network):
    """PRD §2.1: "If both headers are present but the value of `X-User-Role` is not one of the roles listed against the endpoint in §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §2.10: "Checks are evaluated in the following fixed order, and the first failure is returned immediately."

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    referral = fixtures.create_referral(network, case_reference="CASE-N1")
    unit_version = fixtures.read_unit_version(network, headers=network["intake_a"])

    refused = api.accept_referral(
        referral["id"],
        factories.accept_referral_payload(unit_version),
        network["ref_b"],
    )
    validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED)

    unchanged = validate_success(api.get_referral(referral["id"], network["admin"]))
    assert unchanged["status"] == "PENDING"
    assert unchanged["reservation_id"] is None


def test_an_intake_neonatologist_may_not_create_a_referral(api, network):
    """PRD §2.1: "If both headers are present but the value of `X-User-Role` is not one of the roles listed against the endpoint in §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    fixtures.create_referral(network, case_reference="CASE-N1")

    refused = api.create_referral(
        factories.referral_payload(
            network["unit_b_id"], network["unit_a_id"], case_reference="CASE-X1"
        ),
        network["intake_b"],
    )
    validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED)

    _rows, meta = validate_paginated(api.list_referrals(network["admin"]))
    assert meta["total_count"] == 1


def test_a_transport_coordinator_may_not_receive_milk(api, network):
    """PRD §2.1: "If both headers are present but the value of `X-User-Role` is not one of the roles listed against the endpoint in §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §2.10: "Checks are evaluated in the following fixed order, and the first failure is returned immediately."

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    refused = api.create_milk_batch(
        factories.milk_batch_payload(NON_EXISTENT_UUID, volume_ml=10.0, label_code="LBL-X"),
        network["coord"],
    )
    validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED)

    _rows, meta = validate_paginated(api.list_milk_batches(network["admin"]))
    assert meta["total_count"] == 0


def test_a_bedside_nurse_may_not_enrol_a_graduate(api, network):
    """PRD §2.1: "If both headers are present but the value of `X-User-Role` is not one of the roles listed against the endpoint in §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    refused = api.create_follow_up_enrollment(
        factories.follow_up_enrollment_payload(NON_EXISTENT_UUID, network["unit_a_id"]),
        network["nurse"],
    )
    validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED)

    _rows, meta = validate_paginated(api.list_follow_up_enrollments(network["admin"]))
    assert meta["total_count"] == 0


def test_a_followup_coordinator_may_not_run_the_capacity_sweep(api, network):
    """PRD §2.1: "If both headers are present but the value of `X-User-Role` is not one of the roles listed against the endpoint in §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    refused = api.run_capacity_sweep(factories.capacity_sweep_payload(), network["fu"])
    validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED)


# ---------------------------------------------------------------------------
# Shared operations
# ---------------------------------------------------------------------------


def test_the_capacity_edit_is_shared_by_the_admin_and_the_unit_director(api, network):
    """PRD §3.1: "A `NetworkAdmin` or the unit's own `UnitDirector` may revise `staffed_bed_target`, `followup_clinic_daily_capacity`, `annual_admission_volume` and `transport_capable`, each optionally, but the request must carry `expected_unit_version` as described in §2.6."

    Design: Corner/rbac/shared_operations_work_for_each_listed_role
    """
    unit_id = network["unit_a_id"]
    first_version = fixtures.read_unit_version(network)

    by_admin = validate_success(
        api.patch_nicu_unit(
            unit_id,
            factories.unit_patch_payload(first_version, annual_admission_volume=450),
            network["admin"],
        )
    )
    assert by_admin["annual_admission_volume"] == 450
    assert_version_incremented(by_admin["version"], first_version)

    by_director = validate_success(
        api.patch_nicu_unit(
            unit_id,
            factories.unit_patch_payload(by_admin["version"], annual_admission_volume=500),
            network["dir_a"],
        )
    )
    assert by_director["annual_admission_volume"] == 500
    assert_version_incremented(by_director["version"], by_admin["version"])


def test_a_bedside_nurse_may_post_an_infection_event(api, network):
    """PRD §3.7: "The infection dimension advances on an `event` supplied as `SUSPECT`, `CONFIRM_CLABSI` or `RESOLVE`, and may be posted by a `BedsideNurse` or by the unit's `UnitDirector`."

    PRD §3.7: "Any value of one dimension may coexist with any value of the other, and a transition on one dimension never moves the other."

    Design: Corner/rbac/shared_operations_work_for_each_listed_role
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N2")

    suspected = validate_success(
        api.create_infection_event(
            admission["id"], factories.infection_event_payload("SUSPECT"), network["nurse"]
        )
    )
    assert_admission(suspected)
    assert suspected["infection_status"] == "SUSPECTED"
    assert suspected["care_status"] == "ADMITTED"


def test_a_unit_director_may_post_an_infection_event(api, network):
    """PRD §3.7: "The infection dimension advances on an `event` supplied as `SUSPECT`, `CONFIRM_CLABSI` or `RESOLVE`, and may be posted by a `BedsideNurse` or by the unit's `UnitDirector`."

    PRD §3.7: "`RESOLVE` moves the admission `SUSPECTED → RESOLVED` or `CONFIRMED_CLABSI → RESOLVED` and replays the quarantine: every `QUARANTINED` batch returns to the status recorded in its `pre_quarantine_status`, and `pre_quarantine_status` is then cleared back to null."

    Design: Corner/rbac/shared_operations_work_for_each_listed_role
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N2")
    fixtures.infection_event(network, admission["id"], "SUSPECT")

    resolved = validate_success(
        api.create_infection_event(
            admission["id"], factories.infection_event_payload("RESOLVE"), network["dir_a"]
        )
    )
    assert resolved["infection_status"] == "RESOLVED"
    assert resolved["care_status"] == "ADMITTED"


def test_every_role_listed_on_the_unit_read_may_call_it(api, network):
    """PRD §2.1: "Read operations are broadly shared; §4 is authoritative on which roles may call which endpoint."

    Design: Corner/rbac/shared_operations_work_for_each_listed_role
    """
    unit_id = network["unit_a_id"]
    for headers in (
        network["admin"],
        network["dir_a"],
        network["intake_a"],
        network["ref_a"],
        network["coord"],
        network["nurse"],
        network["fu"],
    ):
        unit = validate_success(api.get_nicu_unit(unit_id, headers))
        assert unit["id"] == unit_id


# ---------------------------------------------------------------------------
# Segregation of duties
# ---------------------------------------------------------------------------


def test_the_submitter_may_not_return_its_own_review(api, network):
    """PRD §2.11: "Segregation of duties is enforced on three chains, and in each case the comparison is between person identities, not between roles."

    PRD §3.2: "Returning a submission moves it `SUBMITTED → RETURNED` and records the supplied `return_reason` free text; the caller's `X-User-ID` must differ from `submitted_by_user_id`."

    Design: Corner/rbac/two_step_operations_require_two_different_people
    """
    review = fixtures.open_review(network)
    submitted = fixtures.submit_review(network, review["id"], headers=network["dir_a"])
    assert submitted["status"] == "SUBMITTED"

    submitter_as_admin = make_network_admin_headers(
        make_unit_scoped_user_id(network["unit_a_id"], "dir-1")
    )
    refused = api.return_designation_review(
        review["id"],
        factories.review_return_payload("Returning my own submission"),
        submitter_as_admin,
    )
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES)

    unchanged = validate_success(api.get_designation_review(review["id"], network["admin"]))
    assert unchanged["status"] == "SUBMITTED"


def test_the_verifier_may_not_certify_the_review_it_verified(api, network):
    """PRD §2.11: "On a designation review, the user recorded in `submitted_by_user_id` may not be the user who returns it and may not be the user who verifies it, and the user recorded in `verified_by_user_id` may not be the user who certifies it — the certifier is recorded as `certified_by_user_id`."

    PRD §2.11: "Every violation on any of these chains is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/rbac/two_step_operations_require_two_different_people
    """
    review = fixtures.open_review(network)
    fixtures.submit_review(network, review["id"], headers=network["dir_a"])
    verified = fixtures.verify_review(network, review["id"], headers=network["admin"])
    assert verified["status"] == "VERIFIED"

    refused = api.certify_designation_review(review["id"], {}, network["admin"])
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES)

    unchanged = validate_success(api.get_designation_review(review["id"], network["admin"]))
    assert unchanged["status"] == "VERIFIED"
    assert unchanged["certified_by_user_id"] is None


def test_a_second_administrator_certifies_the_verified_review(api, network):
    """PRD §3.2: "From `VERIFIED`, certification moves the review `VERIFIED → CERTIFIED` and records the caller as `certified_by_user_id`, which must differ from `verified_by_user_id`."

    Design: Corner/rbac/two_step_operations_require_two_different_people
    """
    review = fixtures.open_review(network)
    fixtures.submit_review(network, review["id"], headers=network["dir_a"])
    fixtures.verify_review(network, review["id"], headers=network["admin"])

    certified = validate_success(
        api.certify_designation_review(review["id"], {}, network["admin_2"])
    )
    assert_designation_review(certified)
    assert certified["status"] == "CERTIFIED"
    assert certified["verified_by_user_id"] == "net-1"
    assert certified["certified_by_user_id"] == "net-2"


def test_the_receiving_nurse_may_not_verify_her_own_batch(api, network):
    """PRD §2.11: "On a milk batch, the user in `received_by_user_id` may not be the user who verifies the label; the verifier is recorded as `verified_by_user_id`."

    Design: Corner/rbac/two_step_operations_require_two_different_people
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N2")
    batch = fixtures.receive_milk_batch(network, admission["id"], label_code="LBL-1")
    assert batch["received_by_user_id"] == "nurse-1"

    refused = api.verify_milk_batch(
        batch["id"], factories.verify_milk_payload("LBL-1"), network["nurse"]
    )
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES)

    unchanged = validate_success(api.get_milk_batch(batch["id"], network["admin"]))
    assert unchanged["status"] == "RECEIVED"
    assert unchanged["verified_by_user_id"] is None


def test_a_second_nurse_verifies_the_same_batch(api, network):
    """PRD §2.11: "Segregation of duties is enforced on three chains, and in each case the comparison is between person identities, not between roles."

    PRD §3.7: "A successful verification records the caller as `verified_by_user_id` and moves the batch `RECEIVED → VERIFIED`."

    Design: Corner/rbac/two_step_operations_require_two_different_people
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N2")
    batch = fixtures.receive_milk_batch(network, admission["id"], label_code="LBL-1")

    verified = validate_success(
        api.verify_milk_batch(
            batch["id"], factories.verify_milk_payload("LBL-1"), network["nurse_2"]
        )
    )
    assert_milk_batch(verified)
    assert verified["status"] == "VERIFIED"
    assert verified["received_by_user_id"] == "nurse-1"
    assert verified["verified_by_user_id"] == "nurse-2"


# ---------------------------------------------------------------------------
# Optimistic concurrency on the receiving unit
# ---------------------------------------------------------------------------


def test_a_stale_unit_version_on_acceptance_is_refused(api, network):
    """PRD §2.6: "If any other writer has advanced that unit's `version` since the client read it, the acceptance is rejected with `ERR_UNIT_VERSION_CONFLICT` (HTTP 412) and no reservation is created."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_on_acceptance_is_rejected
    """
    first = fixtures.create_referral(network, case_reference="CASE-N1")
    second = fixtures.create_referral(network, case_reference="CASE-N2")

    stale_version = fixtures.read_unit_version(network, headers=network["intake_a"])
    assert stale_version == 1
    fixtures.accept_referral(network, first["id"], expected_unit_version=stale_version)

    refused = api.accept_referral(
        second["id"],
        factories.accept_referral_payload(stale_version),
        network["intake_a"],
    )
    validate_error(refused, ApiErrorId.UNIT_VERSION_CONFLICT)

    unchanged = validate_success(api.get_referral(second["id"], network["admin"]))
    assert unchanged["status"] == "PENDING"
    assert unchanged["reservation_id"] is None

    _rows, meta = validate_paginated(
        api.list_bed_reservations(network["admin"], {"referral_id": second["id"]})
    )
    assert meta["total_count"] == 0

    unit = fixtures.read_unit(network)
    assert unit["version"] == 2
    assert_unit_counts(unit, occupied=0, held=1, available=3)


def test_acceptance_succeeds_once_the_fresh_unit_version_is_quoted(api, network):
    """PRD §2.6: "The acceptance request must carry `expected_unit_version` equal to the receiving unit's current `version`."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_on_acceptance_is_rejected
    """
    first = fixtures.create_referral(network, case_reference="CASE-N1")
    second = fixtures.create_referral(network, case_reference="CASE-N2")

    stale_version = fixtures.read_unit_version(network, headers=network["intake_a"])
    fixtures.accept_referral(network, first["id"], expected_unit_version=stale_version)
    validate_error(
        api.accept_referral(
            second["id"],
            factories.accept_referral_payload(stale_version),
            network["intake_a"],
        ),
        ApiErrorId.UNIT_VERSION_CONFLICT,
    )

    fresh_version = fixtures.read_unit_version(network, headers=network["intake_a"])
    assert fresh_version == 2

    accepted = validate_success(
        api.accept_referral(
            second["id"],
            factories.accept_referral_payload(fresh_version),
            network["intake_a"],
        )
    )
    assert_referral(accepted)
    assert accepted["status"] == "ACCEPTED"

    unit = fixtures.read_unit(network)
    assert unit["version"] == 3
    assert_unit_counts(unit, occupied=0, held=2, available=2)


def test_a_stale_unit_version_on_the_capacity_patch_is_refused(api):
    """PRD §2.6: "That edit likewise requires `expected_unit_version` matching the unit's current `version`, and a mismatch is rejected with `ERR_UNIT_VERSION_CONFLICT` (HTTP 412) with no field written."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_on_capacity_patch_is_rejected
    """
    env = fixtures.setup_network(with_unit_b=False, credentials=(), equipment=())
    unit_id = env["unit_a_id"]
    other_director = make_unit_director_headers(unit_id, "dir-2")

    stale_version = fixtures.read_unit_version(env, headers=env["dir_a"])
    assert stale_version == 1

    widened = validate_success(
        api.patch_nicu_unit(
            unit_id,
            factories.unit_patch_payload(stale_version, staffed_bed_target=6),
            env["dir_a"],
        )
    )
    assert widened["staffed_bed_target"] == 6
    assert widened["version"] == 2

    refused = api.patch_nicu_unit(
        unit_id,
        factories.unit_patch_payload(stale_version, followup_clinic_daily_capacity=9),
        other_director,
    )
    validate_error(refused, ApiErrorId.UNIT_VERSION_CONFLICT)

    unchanged = fixtures.read_unit(env, headers=env["dir_a"])
    assert unchanged["followup_clinic_daily_capacity"] == 2
    assert unchanged["staffed_bed_target"] == 6
    assert unchanged["version"] == 2


def test_the_capacity_patch_succeeds_on_the_fresh_unit_version(api):
    """PRD §2.6: "Each declares a non-optional version field in its request body, carrying the client's last observed `version` of a parent resource; if the stored `version` differs, the write is refused and nothing at all is persisted."

    Design: Corner/cross_cutting_complexity_layers/stale_unit_version_on_capacity_patch_is_rejected
    """
    env = fixtures.setup_network(with_unit_b=False, credentials=(), equipment=())
    unit_id = env["unit_a_id"]
    other_director = make_unit_director_headers(unit_id, "dir-2")

    stale_version = fixtures.read_unit_version(env, headers=env["dir_a"])
    widened = validate_success(
        api.patch_nicu_unit(
            unit_id,
            factories.unit_patch_payload(stale_version, staffed_bed_target=6),
            env["dir_a"],
        )
    )
    validate_error(
        api.patch_nicu_unit(
            unit_id,
            factories.unit_patch_payload(stale_version, followup_clinic_daily_capacity=9),
            other_director,
        ),
        ApiErrorId.UNIT_VERSION_CONFLICT,
    )

    retried = validate_success(
        api.patch_nicu_unit(
            unit_id,
            factories.unit_patch_payload(widened["version"], followup_clinic_daily_capacity=9),
            other_director,
        )
    )
    assert retried["staffed_bed_target"] == 6
    assert retried["followup_clinic_daily_capacity"] == 9
    assert retried["version"] == 3
    assert_unit_counts(retried, occupied=0, held=0, available=6, posture="OPEN")


# ---------------------------------------------------------------------------
# Optimistic concurrency on the admission
# ---------------------------------------------------------------------------


def _admission_ready_for_back_transfer(env):
    """Admit a 1200 g infant, walk it to room air with two compliant developmental
    rounds and attest back-transfer readiness; returns (admission, stale_version)."""
    admission = fixtures.admit_case(env, case_reference="CASE-N1")
    stale_version = admission["version"]
    fixtures.care_update(env, admission["id"], current_weight_grams=1900, support_modality="ROOM_AIR")
    fixtures.developmental_rounds(env, admission["id"], count=2, light_cycling_compliant=False)
    fixtures.attest_back_transfer_ready(env, admission["id"])
    return admission, stale_version


def test_a_stale_admission_version_on_the_back_transfer_referral_is_refused(api, network):
    """PRD §2.6: "Because a back-transfer referral encodes the infant's weight, support and readiness at the instant it is written, a care update or an infection event that has advanced the admission since the client's read invalidates the decision: the write is rejected with `ERR_ADMISSION_VERSION_CONFLICT` (HTTP 412) and no referral is created."

    Design: Corner/cross_cutting_complexity_layers/stale_admission_version_on_back_transfer_referral_is_rejected
    """
    admission, stale_version = _admission_ready_for_back_transfer(network)
    assert stale_version == 1

    refused = api.create_back_transfer_referral(
        admission["id"],
        factories.back_transfer_referral_payload(
            stale_version, network["unit_b_id"], "CASE-BT-STALE"
        ),
        network["intake_a"],
    )
    validate_error(refused, ApiErrorId.ADMISSION_VERSION_CONFLICT)

    _rows, meta = validate_paginated(
        api.list_referrals(network["admin"], {"source_admission_id": admission["id"]})
    )
    assert meta["total_count"] == 0

    fresh = fixtures.read_admission(network, admission["id"])
    assert fresh["version"] > stale_version
    assert fresh["care_status"] == "BACK_TRANSFER_READY"


def test_the_back_transfer_referral_succeeds_on_the_fresh_admission_version(api, network):
    """PRD §2.6: "That request must carry `expected_admission_version` equal to the admission's current `version`."

    Design: Corner/cross_cutting_complexity_layers/stale_admission_version_on_back_transfer_referral_is_rejected
    """
    admission, stale_version = _admission_ready_for_back_transfer(network)
    validate_error(
        api.create_back_transfer_referral(
            admission["id"],
            factories.back_transfer_referral_payload(
                stale_version, network["unit_b_id"], "CASE-BT-STALE"
            ),
            network["intake_a"],
        ),
        ApiErrorId.ADMISSION_VERSION_CONFLICT,
    )

    fresh_version = fixtures.read_admission(network, admission["id"])["version"]
    created = validate_success(
        api.create_back_transfer_referral(
            admission["id"],
            factories.back_transfer_referral_payload(
                fresh_version, network["unit_b_id"], "CASE-BT-FRESH"
            ),
            network["intake_a"],
        ),
        201,
    )
    assert_referral(created)
    assert created["referral_kind"] == "BACK_TRANSFER"
    assert created["source_admission_id"] == admission["id"]
    assert created["referring_unit_id"] == network["unit_a_id"]
    assert created["required_level"] == "LEVEL_I"

    source = fixtures.read_admission(network, admission["id"])
    assert source["care_status"] == "BACK_TRANSFER_READY"


# ---------------------------------------------------------------------------
# Cascades are visible in the response that caused them
# ---------------------------------------------------------------------------


def test_the_acceptance_response_names_the_hold_it_created(api, network):
    """PRD §2.11: "Cascades are immediate: by the time a response is returned, every consequence described in §3 has already been applied and every derived figure on every touched unit reflects it."

    PRD §3.4: "Exposing it on the acceptance response saves the caller a second read."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    referral = fixtures.create_referral(network, case_reference="CASE-N1")
    unit_version = fixtures.read_unit_version(network, headers=network["intake_a"])

    accepted = validate_success(
        api.accept_referral(
            referral["id"],
            factories.accept_referral_payload(unit_version),
            network["intake_a"],
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["reservation_id"] is not None

    reservation = validate_success(
        api.get_bed_reservation(accepted["reservation_id"], network["admin"])
    )
    assert_bed_reservation(reservation)
    assert reservation["referral_id"] == referral["id"]
    assert reservation["unit_id"] == network["unit_a_id"]
    assert reservation["status"] == "HELD"
    assert reservation["bed_class"] == "STAFFED"


def test_the_admission_response_already_carries_the_derived_care_level(api, network):
    """PRD §3.7: "`current_care_level` is re-derived from the bedside record as the higher-ranking of the weight term applied to `current_weight_grams` and the support term applied to `support_modality`, using exactly the weight and support mappings of §3.3."

    PRD §2.11: "Cascades are immediate: by the time a response is returned, every consequence described in §3 has already been applied and every derived figure on every touched unit reflects it."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    referral, _accepted = fixtures.hold_bed(network, case_reference="CASE-N1")

    created = validate_success(
        api.create_admission(
            factories.admission_payload(referral["id"]), network["intake_a"]
        ),
        201,
    )
    assert_admission(created)
    assert created["current_care_level"] == "LEVEL_III"
    assert created["care_status"] == "ADMITTED"
    assert created["unit_id"] == network["unit_a_id"]


def test_the_discharge_response_already_reports_the_graduate_flag(api, network):
    """PRD §3.8: "The discharge stamps `discharged_at` with the current clock instant, sets `discharge_disposition` to `HOME`, re-derives `high_risk_graduate` from the eligibility rules of §3.9, then re-derives the unit's counters, promotes its deferral queue, and advances its `version` by one."

    PRD §2.11: "Cascades are immediate: by the time a response is returned, every consequence described in §3 has already been applied and every derived figure on every touched unit reflects it."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    admission = fixtures.admit_case(network, case_reference="CASE-N1")
    fixtures.care_update(
        network, admission["id"], current_weight_grams=2200, support_modality="ROOM_AIR"
    )

    discharged = validate_success(
        api.discharge_admission(
            admission["id"], factories.discharge_payload("HOME"), network["intake_a"]
        )
    )
    assert discharged["care_status"] == "DISCHARGED"
    assert discharged["high_risk_graduate"] is True
    assert discharged["discharge_disposition"] == "HOME"
    assert discharged["discharged_at"].startswith(CLOCK_START[:-1])

    unit = fixtures.read_unit(network)
    assert_unit_counts(unit, occupied=0, held=0, available=4, posture="OPEN")

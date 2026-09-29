"""Stale views, clock-derived totals, and a list that has to filter and page at once.

Three of these tests are about a writer proving it saw current state; the fourth is about
a total that changes with nothing but the clock; the fifth is about a list read composing
its filters with its window.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_defect_count, assert_posture, assert_total_count
from test_helpers.factories import (
    make_facility_update_payload,
    make_publish_payload,
    make_transfer_order_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    OFFICER,
    PHYSICIAN,
    SECOND_ADMIN,
    acknowledge_disclosure,
    attest_signage,
    begin_mse,
    complete_mse,
    create_ambulance_mou,
    create_facility,
    create_transfer_agreement,
    create_transfer_order,
    draft_template,
    open_facility,
    patch_facility,
    publish_template,
    read_ambulance_mou,
    read_encounter,
    read_facility,
    refuse_disclosure,
    register_encounter,
    set_clock,
)

WORKING_INSTANT = "2026-08-01T08:00:00Z"
FIRST_EXPIRY_INSTANT = "2026-09-01T00:00:00Z"
SECOND_EXPIRY_INSTANT = "2027-01-01T00:00:00Z"
NARROW_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}
WIDER_BED_COUNT = 6
SECOND_CARRIER = "Colorado River Critical Transport"


def test_a_publisher_who_missed_the_signage_attestation_must_read_the_facility_again():
    """The attestation moved the facility under the publisher's feet.

    PRD 2.5: "`POST /disclosure-templates/{id}/publish` requires `expected_facility_version`,
    carrying the client's last observed `version` of the `Facility` that owns the template. If
    that value does not equal the facility's current `version`, publication is rejected with
    `ERR_STALE_FACILITY_VERSION` (HTTP 412)." and "These are stale-version rejections,
    evaluated against stored state at the moment the request is processed."  The attestation is
    what invalidated the captured value, because PRD 3.1 says it "appends a ledger entry with
    `event_type` `SIGNAGE_ATTESTED`, `severity` `INFO` and `defect_counted` false, recomputes
    the posture and `restricted_service_codes` with the same cascade behaviour as a
    configuration update, and increments the facility's `version` by 1."

    Design: Corner/cross-cutting complexity layers/stale_facility_version_on_template_publish_returns_precondition_failed
    """
    set_clock(WORKING_INSTANT)
    facility = create_facility(ADMIN, **NARROW_FACILITY)
    template = draft_template(facility["id"], ADMIN)
    version_at_creation = facility["version"]

    attest_signage(facility["id"], OFFICER)
    version_after_attestation = read_facility(facility["id"])["version"]
    assert version_after_attestation != version_at_creation

    validate_error(
        api_client.publish_disclosure_template(
            template["id"], make_publish_payload(version_at_creation), ADMIN
        ),
        ApiErrorId.ERR_STALE_FACILITY_VERSION.value,
        412,
    )

    refused = validate_success(
        api_client.get_disclosure_template(template["id"], ADMIN)
    )
    assert refused["status"] == "DRAFT"
    assert read_facility(facility["id"])["current_published_template_id"] is None

    published = publish_template(template["id"], version_after_attestation, ADMIN)
    assert published["status"] == "PUBLISHED"

    opened = read_facility(facility["id"])
    assert_posture(opened, "OPEN")
    assert opened["version"] > version_after_attestation


def test_a_transfer_order_written_from_a_pre_screening_view_of_the_encounter_is_refused():
    """Completing the screening bumped the encounter, so the captured token is spent.

    PRD 2.5: "`POST /encounters/{id}/transfer-orders` requires `expected_encounter_version`,
    carrying the client's last observed `version` of the target `Encounter`. If that value does
    not equal the encounter's current `version`, the create is rejected with
    `ERR_STALE_ENCOUNTER_VERSION` (HTTP 412). A new order legitimately cancels an existing
    requested or accepted order on the same encounter and releases its ambulance unit, so the
    create must prove the caller saw the encounter's current version."  A successful create is
    what PRD 3.8 describes: "A created order is `REQUESTED`, with `requested_at` stamped,
    `certifying_physician_user_id` set to the acting physician, and `reserved_unit_count` of
    1." and "The encounter's `clinical_state` becomes `TRANSFER_PENDING`".  Until then nothing
    is held, because PRD 2.10 counts only live orders: "`units_reserved` equals the number of
    transfer orders referencing that memorandum whose status is `REQUESTED` or `ACCEPTED`".

    Design: Corner/cross-cutting complexity layers/stale_encounter_version_on_transfer_order_creation_returns_precondition_failed
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    agreement = create_transfer_agreement(
        context["facility_id"], ADMIN, service_line="CARDIAC", capability_tier=3
    )
    mou = create_ambulance_mou(context["facility_id"], ADMIN)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-3901",
        acuity_level=4,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    mid_screening = begin_mse(encounter["id"])
    stale_version = mid_screening["version"]

    screened = complete_mse(encounter["id"], "STABLE")
    fresh_version = screened["version"]
    assert fresh_version != stale_version

    validate_error(
        api_client.create_transfer_order(
            encounter["id"],
            make_transfer_order_payload(agreement["id"], mou["id"], stale_version),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_STALE_ENCOUNTER_VERSION.value,
        412,
    )

    assert read_encounter(encounter["id"])["clinical_state"] == "MSE_COMPLETE"
    assert read_ambulance_mou(mou["id"])["units_reserved"] == 0

    order = create_transfer_order(
        encounter["id"], agreement["id"], mou["id"], fresh_version
    )
    assert order["status"] == "REQUESTED"
    assert order["reserved_unit_count"] == 1

    pending = read_encounter(encounter["id"])
    assert pending["clinical_state"] == "TRANSFER_PENDING"
    assert pending["version"] > fresh_version


def test_two_administrators_holding_the_same_version_cannot_both_write():
    """The loser's scope edit is discarded whole, not merged.

    PRD 2.5: "`PATCH /facilities/{id}` requires `expected_facility_version`, carrying the
    client's last observed `version` of the target `Facility`. If that value does not equal the
    facility's current `version`, the update is rejected with `ERR_STALE_FACILITY_VERSION`
    (HTTP 412). Licensure and scope edits are last-writer-visible overwrites of the same
    fields, so the writer must prove its view of the facility is current."  PRD 3.1 says what a
    surviving update does: "Declared fields are replaced wholesale; omitted fields are left
    untouched."  The posture is unmoved by a bed-count edit, and PRD 2.8 fixes what that
    implies for the gate list: "When the posture is `OPEN` the list is empty."

    Design: Corner/cross-cutting complexity layers/stale_facility_version_on_configuration_patch_returns_precondition_failed
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]
    shared_version = read_facility(facility_id)["version"]

    widened = patch_facility(
        facility_id, shared_version, ADMIN, observation_bed_count=WIDER_BED_COUNT
    )
    assert widened["observation_bed_count"] == WIDER_BED_COUNT
    assert widened["version"] > shared_version

    validate_error(
        api_client.update_facility(
            facility_id,
            make_facility_update_payload(
                shared_version, imaging_scope=["XRAY", "CT", "MRI"]
            ),
            SECOND_ADMIN,
        ),
        ApiErrorId.ERR_STALE_FACILITY_VERSION.value,
        412,
    )

    unchanged = read_facility(facility_id)
    assert unchanged["imaging_scope"] == ["XRAY", "CT"]
    assert_posture(unchanged, "OPEN")
    assert unchanged["restricted_service_codes"] == []


def test_the_facilitys_ambulance_totals_shrink_as_memoranda_expire_with_the_clock():
    """Nobody writes anything; the clock alone empties the ledger.

    PRD 3.5: "Four fields are derived and never supplied: `units_reserved` starts at 0,
    `units_available` starts equal to `units_committed`, `saturation_state` is `SATURATED` at
    creation when `units_committed` is 0 and `AVAILABLE` otherwise, and `status` is `ACTIVE`
    while the logical clock is before `coverage_end_at` and `EXPIRED` from that instant onward,
    re-evaluated on every read and validation."  The facility totals are drawn from the live
    memoranda only, per PRD 2.10: "At the facility level, `ambulance_units_committed_total` is
    the sum of `units_committed` over the facility's memoranda whose `status` is `ACTIVE`,
    `ambulance_units_reserved_total` is the corresponding sum of `units_reserved`, and
    `transfer_capacity_state` is `AVAILABLE` when committed total minus reserved total is
    greater than 0 and `SATURATED` otherwise."

    Design: Corner/cross-cutting complexity layers/ambulance_totals_reconcile_when_a_mou_expires_with_the_clock
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]

    critical_care = create_ambulance_mou(
        facility_id,
        ADMIN,
        level_of_care="CRITICAL_CARE",
        units_committed=2,
        coverage_start_at="2026-07-01T00:00:00Z",
        coverage_end_at=FIRST_EXPIRY_INSTANT,
    )
    advanced_life_support = create_ambulance_mou(
        facility_id,
        ADMIN,
        carrier_name=SECOND_CARRIER,
        level_of_care="ALS",
        units_committed=1,
        coverage_start_at="2026-07-01T00:00:00Z",
        coverage_end_at="2026-12-31T00:00:00Z",
    )

    while_both_live = read_facility(facility_id)
    assert while_both_live["ambulance_units_committed_total"] == 3
    assert while_both_live["ambulance_units_reserved_total"] == 0
    assert while_both_live["transfer_capacity_state"] == "AVAILABLE"

    set_clock(FIRST_EXPIRY_INSTANT)

    assert read_ambulance_mou(critical_care["id"])["status"] == "EXPIRED"
    assert read_ambulance_mou(advanced_life_support["id"])["status"] == "ACTIVE"
    assert read_facility(facility_id)["ambulance_units_committed_total"] == 1

    set_clock(SECOND_EXPIRY_INSTANT)

    first_after = read_ambulance_mou(critical_care["id"])
    second_after = read_ambulance_mou(advanced_life_support["id"])
    assert first_after["status"] == "EXPIRED"
    assert second_after["status"] == "EXPIRED"
    assert first_after["units_committed"] == 2
    assert second_after["units_committed"] == 1

    emptied = read_facility(facility_id)
    assert emptied["ambulance_units_committed_total"] == 0
    assert emptied["transfer_capacity_state"] == "SATURATED"


def test_the_encounter_list_filters_on_either_dimension_and_pages_the_result():
    """Three patients, four reads, and a last page that reports no more rows.

    PRD 3.6: "Encounters are readable individually and as a filtered list; the list accepts
    `facility_id`, `pinned_disclosure_template_id`, `clinical_state` and `disclosure_state`
    filters alongside pagination, which is how a compliance officer finds, for instance, every
    encounter still sitting in `DISCLOSURE_PRESENTED`."  The template every one of them pins is
    fixed at registration: "`pinned_disclosure_template_id` is set to the facility's
    `current_published_template_id` and never changes again for the life of the encounter, no
    matter how many later templates are published or retired."  PRD 2.3 pins the window
    arithmetic: "`total_count` as the number of rows matching the filters before the window was
    applied, and `has_more` as a boolean that is true when rows remain beyond the current
    window."  Only the refusal is a counted defect, per PRD 2.8: "Exactly four kinds of finding
    are defect-counted, and they are the four that can push a facility into `RESTRICTED`: a
    refused disclosure, a disclosure defect discovered at disposition, a late medical screening
    examination, and a transfer declined for insurance reasons."

    Design: Corner/cross-cutting complexity layers/encounter_list_filters_and_pagination_stay_consistent_together
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]
    template_id = context["template_id"]

    screening = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-4001",
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(screening["id"])
    begin_mse(screening["id"])

    refusing = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-4002",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )
    refuse_disclosure(refusing["id"])

    untouched = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-4003",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )

    in_progress, in_progress_meta = validate_paginated(
        api_client.list_encounters(
            OFFICER,
            params={"facility_id": facility_id, "clinical_state": "MSE_IN_PROGRESS"},
        )
    )
    assert_total_count(in_progress_meta, 1)
    assert in_progress[0]["id"] == screening["id"]

    refused, refused_meta = validate_paginated(
        api_client.list_encounters(
            OFFICER,
            params={
                "facility_id": facility_id,
                "disclosure_state": "DISCLOSURE_REFUSED",
            },
        )
    )
    assert_total_count(refused_meta, 1)
    assert refused[0]["id"] == refusing["id"]

    pinned, pinned_meta = validate_paginated(
        api_client.list_encounters(
            OFFICER, params={"pinned_disclosure_template_id": template_id}
        )
    )
    assert_total_count(pinned_meta, 3)
    assert {row["id"] for row in pinned} == {
        screening["id"],
        refusing["id"],
        untouched["id"],
    }

    last_page, last_page_meta = validate_paginated(
        api_client.list_encounters(
            OFFICER,
            params={
                "pinned_disclosure_template_id": template_id,
                "limit": 1,
                "offset": 2,
            },
        )
    )
    assert len(last_page) == 1
    assert_total_count(last_page_meta, 3)
    assert last_page_meta["has_more"] is False

    assert_defect_count(read_facility(facility_id), 1)

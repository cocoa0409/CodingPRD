"""AUC attestation segregation of duties, validation priority, and OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_version_incremented,
    auc_attestation_payload,
    cancel_case,
    create_cardiologist,
    create_device_lot,
    create_recovery_bed,
    create_room,
    document_auc,
    get_bed,
    get_lot,
    post_case,
    restock_payload,
    schedule_case_payload,
    make_interventional_cardiologist_headers,
    validate_error,
    validate_success,
)

SCHEDULER = TEST_USERS["scheduler_headers"]
TECHNOLOGIST = TEST_USERS["technologist_headers"]


class TestStateBeatsSafety:
    def _setup_cancelled_elective(self, api):
        physician = create_cardiologist()
        room = create_room(room_name="Lab 1")
        bed = create_recovery_bed("Bed 1")
        case = post_case(physician["id"], priority="ELECTIVE")
        assert case["auc_status"] == "NOT_DOCUMENTED"
        cancel_case(case["id"])
        return room, bed, case

    def test_schedule_cancelled_case_state_error_beats_auc(self, api):
        """PRD §2.10: "Rejection checks run in a fixed priority order, so a request
        that would fail several checks always reports the earliest applicable one."
        PRD §2.10: "Fifth, state gates on the target and parent resources
        (`ERR_CASE_INVALID_STATE`, `ERR_USAGE_INVALID_STATE`,
        `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_BED_INVALID_STATE`,
        `ERR_SUBMISSION_INVALID_STATE`, `ERR_DOSE_RECORD_ALREADY_VOIDED`). Sixth,
        clinical safety and compliance: the elective AUC gate, the attestation
        segregation of duties, and the contrast ceiling (`ERR_AUC_REQUIRED`,
        `ERR_AUC_ORDERING_CONFLICT`, `ERR_CONTRAST_LIMIT_EXCEEDED`)."
        PRD §3.3: "Scheduling from any other case status is rejected with
        `ERR_CASE_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_cancelled_case_with_missing_auc_state_beats_safety
        """
        room, _, case = self._setup_cancelled_elective(api)
        # The request fails the state gate (CANCELLED) and would also fail the
        # elective AUC gate (NOT_DOCUMENTED); the state gate is earlier.
        resp = api.schedule_case(
            case["id"],
            schedule_case_payload(room["id"], "2026-08-10T09:00:00Z"),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE, expected_status=409)

    def test_schedule_cancelled_case_leaves_no_trace(self, api):
        """PRD §3.3: "Scheduling from any other case status is rejected with
        `ERR_CASE_INVALID_STATE`."
        PRD §3.7: "A scheduler can cancel a case from `POSTED`, `SCHEDULED`, or
        `BUMPED`, moving it to `CANCELLED`; attempts from `IN_PROGRESS`,
        `COMPLETED`, or an already-`CANCELLED` case are refused with
        `ERR_CASE_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_cancelled_case_with_missing_auc_state_beats_safety
        """
        room, bed, case = self._setup_cancelled_elective(api)
        resp = api.schedule_case(
            case["id"],
            schedule_case_payload(room["id"], "2026-08-10T09:00:00Z"),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE, expected_status=409)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["status"] == "CANCELLED"
        assert get_bed(bed["id"])["status"] == "AVAILABLE", \
            "a rejected schedule secures no bed"


class TestAucSegregationOfDuties:
    def test_auc_self_attestation_returns_ordering_conflict(self, api):
        """PRD §3.8: "Segregation of duties is enforced in two directions, both
        under `ERR_AUC_ORDERING_CONFLICT`: the `ordering_physician_id` must differ
        from the case's `performing_physician_id` — no physician may attest as the
        ordering physician on their own case — and the acting `X-User-ID` must
        equal the `ordering_physician_id` being recorded."

        Design: Corner/validations/auc_self_attestation_returns_ordering_conflict
        """
        physician = create_cardiologist()
        case = post_case(physician["id"], priority="ELECTIVE")
        resp = api.attest_auc(
            case["id"],
            auc_attestation_payload(physician["id"], case["version"]),
            make_interventional_cardiologist_headers(physician["id"]))
        validate_error(resp, ApiErrorId.ERR_AUC_ORDERING_CONFLICT,
                       expected_status=403)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["auc_status"] == "NOT_DOCUMENTED"
        assert current["version"] == case["version"], "the refused write is not applied"

    def test_auc_actor_must_be_the_ordering_physician(self, api):
        """PRD §3.8: "Segregation of duties is enforced in two directions, both
        under `ERR_AUC_ORDERING_CONFLICT`: the `ordering_physician_id` must differ
        from the case's `performing_physician_id` — no physician may attest as the
        ordering physician on their own case — and the acting `X-User-ID` must
        equal the `ordering_physician_id` being recorded."

        Design: Corner/validations/auc_actor_must_be_the_ordering_physician
        """
        performing = create_cardiologist(full_name="Dr Perform")
        ordering = create_cardiologist(full_name="Dr Order")
        third = create_cardiologist(full_name="Dr Third")
        case = post_case(performing["id"], priority="ELECTIVE")
        # Signed by the ordering physician but sent by a third cardiologist.
        resp = api.attest_auc(
            case["id"],
            auc_attestation_payload(ordering["id"], case["version"]),
            make_interventional_cardiologist_headers(third["id"]))
        validate_error(resp, ApiErrorId.ERR_AUC_ORDERING_CONFLICT,
                       expected_status=403)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["auc_status"] == "NOT_DOCUMENTED"


class TestOptimisticConcurrency:
    def test_occ_auc_stale_case_version_returns_412(self, api):
        """PRD §2.7: "An attestation legitimately overwrites the case's current AUC
        documentation, so a request whose `expected_case_version` no longer matches
        the case's current `version` — because an earlier attestation, a scheduling
        action, or a dose-recording side effect has advanced it in the meantime —
        is operating on a stale view and must be refused. The rejection carries
        `ERR_STALE_CASE_VERSION` and HTTP status 412."
        PRD §3.8: "A later attestation overwrites an earlier one wholesale, and
        each attestation increments the case `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_auc_stale_case_version_returns_412
        """
        performing = create_cardiologist(full_name="Dr Perform")
        ordering = create_cardiologist(full_name="Dr Order")
        case = post_case(performing["id"], priority="ELECTIVE")
        observed_version = case["version"]
        updated = document_auc(case, ordering)
        assert_version_incremented(updated["version"], observed_version)
        assert updated["auc_status"] == "DOCUMENTED"

        # Replay the attestation with the pre-write version.
        resp = api.attest_auc(
            case["id"],
            auc_attestation_payload(ordering["id"], observed_version,
                                    auc_score="RARELY_APPROPRIATE",
                                    criterion_code="AUC-88.2"),
            make_interventional_cardiologist_headers(ordering["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION, expected_status=412)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["auc_score"] == "APPROPRIATE", \
            "the stale write does not overwrite observed documentation"
        assert current["version"] == updated["version"]

    def test_occ_restock_stale_lot_version_returns_412(self, api):
        """PRD §2.7: "Restocking a device lot (the
        `POST /cath-lab/device-lots/{id}/restock` endpoint) requires the request to
        carry `expected_lot_version`. A restock is valid from any lot state, so the
        version check is the only way to detect that the client's quantity basis is
        stale — for example after an intervening restock, or after an implant that
        decremented `quantity_on_hand`. A mismatch with the lot's current `version`
        is refused with `ERR_STALE_LOT_VERSION` and HTTP status 412."
        PRD §3.5: "Restocking adds `quantity` units to `quantity_on_hand`,
        increments the lot's `version` by one, and recomputes the derived status;
        it is valid from any lot state."

        Design: Corner/cross_cutting_complexity_layers/occ_restock_stale_lot_version_returns_412
        """
        lot = create_device_lot(lot_number="LOT-J", quantity_on_hand=2,
                                reorder_threshold=4)
        assert lot["status"] == "LOW_STOCK", "available 2 < threshold 4"
        observed_version = lot["version"]

        restocked = validate_success(api.restock_device_lot(
            lot["id"], restock_payload(3, observed_version), TECHNOLOGIST))
        assert restocked["quantity_on_hand"] == 5
        assert_version_incremented(restocked["version"], observed_version)
        assert restocked["status"] == "ACTIVE", "available 5 >= threshold 4"

        # Replay the same restock basis: the version has moved on.
        resp = api.restock_device_lot(
            lot["id"], restock_payload(1, observed_version), TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION, expected_status=412)
        current = get_lot(lot["id"])
        assert current["quantity_on_hand"] == 5, "the stale write is not applied"
        assert current["version"] == restocked["version"]

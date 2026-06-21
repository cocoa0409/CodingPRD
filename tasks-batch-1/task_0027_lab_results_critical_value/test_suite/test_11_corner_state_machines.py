"""Corner — state_machines section: invalid transitions, terminal lockdown,
initial state.
"""
from test_helpers import (
    accession_specimen,
    api_client,
    ApiErrorId,
    bootstrap_actors,
    collect_specimen,
    create_lab_order_payload,
    create_order,
    create_specimen,
    get_success_data,
    make_ordering_provider_headers,
    register_patient,
    setup_released_result,
    transit_specimen,
    validate_error,
    validate_success,
)


class TestCancelAlreadyCancelledOrder:
    def test_cancel_already_cancelled_order_returns_invalid_state(self, api):
        """PRD §3.2: "Cancellation is only valid while the order is in `DRAFT` with no
        specimen yet accessioned; once any specimen has been accessioned, the order
        has crossed into `ACCESSIONED` and the cancel pathway is no longer available
        to the ordering provider. Such an attempt is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_order_already_cancelled_returns_invalid_state
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", with_instrument=False)
        patient = register_patient(actors.lt_id, mrn="MRN-CC0100")
        order = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")

        # First cancel — succeeds (DRAFT → CANCELLED).
        res1 = api_client.cancel_lab_order(order["id"], actors.op_headers)
        data1 = validate_success(res1)
        assert data1["status"] == "CANCELLED"

        # Second cancel — order is CANCELLED, not DRAFT. → ERR_INVALID_STATE.
        res2 = api_client.cancel_lab_order(order["id"], actors.op_headers)
        validate_error(res2, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api_client.get_lab_order(order["id"], actors.lt_headers))
        assert after["status"] == "CANCELLED", (
            f"order MUST remain CANCELLED after rejected duplicate cancel; "
            f"got {after['status']!r}"
        )


class TestCollectFromInTransitSpecimen:
    def test_collect_specimen_in_transit_returns_invalid_state(self, api):
        """PRD §3.3: "Custody then moves through four ordered events: collection at the patient's side (transitioning `DRAFT → COLLECTED`), hand-off to a courier (transitioning `COLLECTED → IN_TRANSIT`), arrival and accessioning at the lab (transitioning `IN_TRANSIT → ACCESSIONED`), and — at any later point if the specimen is found to be non-viable — rejection (transitioning to `REJECTED` from `COLLECTED`, `IN_TRANSIT`, or `ACCESSIONED`)."
        PRD §2.10: "and only then state-validity of the targeted entity against §3's state machines."

        Design: Corner/state_machines/collect_specimen_from_in_transit_returns_invalid_state
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", with_instrument=False)
        patient = register_patient(actors.lt_id, mrn="MRN-CI0100")
        order = create_order(actors, patient["id"], panel_code="CMP", priority="ROUTINE")
        sp = create_specimen(actors, order["id"], container_code="GREEN")
        collect_specimen(actors, sp["id"])
        transit_specimen(actors, sp["id"])

        # sp is now IN_TRANSIT. Re-collect must fail.
        res = api_client.collect_specimen(sp["id"], actors.phleb_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api_client.get_specimen(sp["id"], actors.lt_headers))
        assert after["status"] == "IN_TRANSIT", (
            f"specimen MUST remain IN_TRANSIT; got {after['status']!r}"
        )


class TestNewLabOrderStartsInDraft:
    def test_new_lab_order_starts_in_draft_with_zero_counters_and_version_one(self, api):
        """PRD §3.2: "A lab order begins life in `DRAFT` status when an
        `OrderingProvider` places it."
        PRD §2.4: "an integer `version` field that begins at 1 on creation"
        PRD §2.8: "`LabOrder.specimens_count` is the number of specimens of that order
        whose `status` is not `REJECTED`."

        Design: Corner/state_machines/new_lab_order_starts_in_draft
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", with_instrument=False)
        patient = register_patient(actors.lt_id, mrn="MRN-IS0100")
        res = api_client.create_lab_order(
            patient["id"],
            create_lab_order_payload(
                ordering_clinician_id=actors.op_id,
                panel_code="CMP",
                priority="STAT",
            ),
            actors.op_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["specimens_count"] == 0
        assert data["accessioned_count"] == 0
        assert data["version"] == 1


class TestCancelAfterResultedReturnsInvalidState:
    def test_cancel_resulted_order_returns_invalid_state(self, api):
        """PRD §3.2: "`RESULTED` and `CANCELLED` are terminal for `LabOrder`."
        PRD §3.2: "Cancellation is only valid while the order is in `DRAFT` with no specimen yet accessioned; once any specimen has been accessioned, the order has crossed into `ACCESSIONED` and the cancel pathway is no longer available to the ordering provider. Such an attempt is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_order_after_resulted_returns_invalid_state
        """
        actors = bootstrap_actors(clock="2026-05-28T08:00:00Z", panels=["CMP"])
        patient = register_patient(actors.lt_id, mrn="MRN-TL0100")
        bundle = setup_released_result(
            actors, patient,
            analyte_code="K", numeric_value=4.20, unit="mmol/L",
            reference_low=3.50, reference_high=5.10,
            critical_low=2.50, critical_high=6.00,
        )
        # Order is now RESULTED.
        res = api_client.cancel_lab_order(bundle["order"]["id"], actors.op_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(
            api_client.get_lab_order(bundle["order"]["id"], actors.lt_headers)
        )
        assert after["status"] == "RESULTED", (
            f"RESULTED order MUST remain RESULTED; got {after['status']!r}"
        )

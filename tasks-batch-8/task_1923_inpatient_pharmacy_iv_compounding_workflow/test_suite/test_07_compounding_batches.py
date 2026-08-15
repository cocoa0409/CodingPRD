"""Batch lifecycle gates: inclusion, hood session, HD gating, QA, rework (PRD §3.5)."""
from datetime import datetime, timezone

from test_helpers import (
    complete_batch_payload,
    create_drug,
    create_patient,
    fixtures,
    place_order,
    setup_batch,
    setup_verified_order,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBatchInclusionRequiresVerified:
    def test_unverified_order_rejected_from_batch(self, api, pharmacist_headers):
        """PRD §3.5: "Every order named must be `VERIFIED` — including a non-verified order fails the whole create with `ERR_ORDER_NOT_VERIFIED` — and must be an `IV` order awaiting compounding."

        Design: Corner/errors/error_order_not_verified_on_batch_inclusion
        """
        prescriber, _ = fixtures.make_prescriber()
        patient = create_patient()
        drug = create_drug()
        order = place_order(patient, drug, prescriber, route="IV",
                            ordered_dose_mg=100.0)  # stays PENDING
        sess_ns = fixtures.setup_session(start=False)
        resp = api.create_batch(
            {
                "hood_session_id": sess_ns.session["id"],
                "order_ids": [order["id"]],
                "usp_risk_level": "LOW",
            },
            sess_ns.technician_headers,
        )
        validate_error(resp, "ERR_ORDER_NOT_VERIFIED", 422)
        rows, meta = validate_paginated(
            api.list_batches(
                pharmacist_headers,
                params={"hood_session_id": sess_ns.session["id"]},
            )
        )
        assert meta["total_count"] == 0


class TestBatchStartRequiresSessionInUse:
    def _setup_draft_with_scheduled_session(self, api):
        ns = setup_verified_order(route="IV", ordered_dose_mg=100.0)
        batch_ns = setup_batch([ns.order["id"]], start_session=False)
        return batch_ns

    def test_start_with_scheduled_session_rejected(self, api):
        """PRD §3.5: "Its hood session must be `IN_USE` — starting against a session in any other state is rejected with `ERR_HOOD_SESSION_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/batch_start_requires_hood_session_in_use
        """
        batch_ns = self._setup_draft_with_scheduled_session(api)
        resp = api.start_batch(batch_ns.batch["id"], batch_ns.technician_headers)
        validate_error(resp, "ERR_HOOD_SESSION_NOT_ACTIVE", 409)

    def test_start_succeeds_after_session_in_use(self, api):
        """PRD §3.5: "The batch must be in `DRAFT`. Its hood session must be `IN_USE` — starting against a session in any other state is rejected with `ERR_HOOD_SESSION_NOT_ACTIVE`."
        PRD §3.5: "A successful start moves the batch to `IN_PROGRESS` and increments its `version`."

        Design: Difficulty/cross_entity_state_dependency/batch_start_requires_hood_session_in_use
        """
        batch_ns = self._setup_draft_with_scheduled_session(api)
        validate_error(
            api.start_batch(batch_ns.batch["id"], batch_ns.technician_headers),
            "ERR_HOOD_SESSION_NOT_ACTIVE", 409,
        )
        session = validate_success(
            api.start_hood_session(
                batch_ns.session["id"], batch_ns.session_technician_headers
            ),
            200,
        )
        assert session["status"] == "IN_USE"
        started = validate_success(
            api.start_batch(batch_ns.batch["id"], batch_ns.technician_headers), 200
        )
        assert started["status"] == "IN_PROGRESS"


class TestHazardousBatchGates:
    def _setup_hd_batch(self, api, compounder_certified: bool, hood_hd_rated: bool):
        prescriber, _ = fixtures.make_prescriber()
        pharmacist, _ = fixtures.make_pharmacist()
        t_cert, t_cert_headers = fixtures.make_technician(
            hd_compounding_certified=True,
            hd_cert_expires_at="2027-01-01T00:00:00Z",
        )
        t_plain, t_plain_headers = fixtures.make_technician(
            hd_compounding_certified=False
        )
        patient = create_patient()
        drug = create_drug(is_hazardous=True)
        order = place_order(patient, drug, prescriber, route="IV",
                            ordered_dose_mg=100.0)
        order = fixtures.verify_order(order["id"], pharmacist)
        hood = fixtures.create_hood(is_hd_rated=hood_hd_rated)
        session = fixtures.create_hood_session(hood, t_cert, start=True)
        creator, creator_headers = (
            (t_cert, t_cert_headers) if compounder_certified
            else (t_plain, t_plain_headers)
        )
        batch = validate_success(
            api.create_batch(
                {
                    "hood_session_id": session["id"],
                    "order_ids": [order["id"]],
                    "usp_risk_level": "MEDIUM",
                },
                creator_headers,
            ),
            201,
        )
        return batch, creator_headers

    def test_uncertified_compounder_rejected(self, api):
        """PRD §3.5: "When any preparation's drug is hazardous, two further gates apply: the session's hood must have `is_hd_rated` true, otherwise `ERR_HOOD_NOT_HD_RATED`; and the compounder must hold current certification — `hd_compounding_certified` true with `hd_cert_expires_at` later than the logical clock — otherwise `ERR_HD_CERTIFICATION_REQUIRED`."

        Design: Corner/validations/hd_certification_required_at_batch_start
        """
        batch, creator_headers = self._setup_hd_batch(
            api, compounder_certified=False, hood_hd_rated=True
        )
        resp = api.start_batch(batch["id"], creator_headers)
        validate_error(resp, "ERR_HD_CERTIFICATION_REQUIRED", 422)
        fetched = validate_success(api.get_batch(batch["id"], creator_headers), 200)
        assert fetched["status"] == "DRAFT"

    def test_non_hd_rated_hood_rejected(self, api):
        """PRD §3.5: "When any preparation's drug is hazardous, two further gates apply: the session's hood must have `is_hd_rated` true, otherwise `ERR_HOOD_NOT_HD_RATED`; and the compounder must hold current certification — `hd_compounding_certified` true with `hd_cert_expires_at` later than the logical clock — otherwise `ERR_HD_CERTIFICATION_REQUIRED`."

        Design: Corner/validations/hood_not_hd_rated_rejected
        """
        batch, creator_headers = self._setup_hd_batch(
            api, compounder_certified=True, hood_hd_rated=False
        )
        resp = api.start_batch(batch["id"], creator_headers)
        validate_error(resp, "ERR_HOOD_NOT_HD_RATED", 422)
        fetched = validate_success(api.get_batch(batch["id"], creator_headers), 200)
        assert fetched["status"] == "DRAFT"


class TestQaReleaseFromDraftRejected:
    def test_release_on_draft_batch_rejected(self, api, pharmacist_headers):
        """PRD §3.5: "Quality review belongs to a `Pharmacist`, with segregation of duties enforced on both branches: the reviewing pharmacist's `X-User-ID` must differ from the batch's `compounder_staff_id`, and a self-review is rejected with `ERR_SOD_VIOLATION`."

        Design: Corner/state_machines/batch_qa_release_from_draft_rejected
        """
        ns = setup_verified_order(route="IV", ordered_dose_mg=100.0)
        batch_ns = setup_batch([ns.order["id"]], start_session=False)
        resp = api.qa_release_batch(batch_ns.batch["id"], pharmacist_headers)
        validate_error(resp, "ERR_INVALID_STATE", 409)
        fetched = validate_success(
            api.get_batch(batch_ns.batch["id"], pharmacist_headers), 200
        )
        assert fetched["status"] == "DRAFT"


class TestBatchReworkCycle:
    def _setup_rejectable_batch(self, api):
        ns = setup_verified_order(route="IV", ordered_dose_mg=100.0)
        batch_ns = setup_batch([ns.order["id"]], start_session=True)
        fixtures.start_batch(batch_ns)
        fixtures.complete_batch(batch_ns, [10.0], waste_ml=0.0,
                                storage_condition="ROOM")
        return batch_ns, ns.pharmacist_headers

    def _reject_and_rework_once(self, api, batch_ns, pharmacist_headers, reason):
        validate_success(
            api.qa_reject_batch(batch_ns.batch["id"], {"reason": reason},
                                pharmacist_headers),
            200,
        )
        return validate_success(
            api.rework_batch(batch_ns.batch["id"], batch_ns.technician_headers), 200
        )

    def test_first_and_second_rework_cycle_back_to_draft(self, api):
        """PRD §3.5: "Calling rework on a `REJECTED` batch whose `rework_count` is below 2 increments `rework_count` by 1, creates fresh `PLANNED` preparations for linked orders still `VERIFIED` (preparations of discontinued or superseded orders stay `CANCELLED` or `WASTED`), and returns the batch to `DRAFT` with its `version` incremented."

        Design: Difficulty/non_linear_state_machine/batch_rework_cycle
        """
        batch_ns, pharmacist_headers = self._setup_rejectable_batch(api)
        after1 = self._reject_and_rework_once(api, batch_ns, pharmacist_headers, "r1")
        assert after1["status"] == "DRAFT"
        assert after1["rework_count"] == 1
        fixtures.start_batch(batch_ns)
        fixtures.complete_batch(batch_ns, [10.0], waste_ml=0.0,
                                storage_condition="ROOM")
        after2 = self._reject_and_rework_once(api, batch_ns, pharmacist_headers, "r2")
        assert after2["status"] == "DRAFT"
        assert after2["rework_count"] == 2

    def test_third_rework_terminates_failed_with_200(self, api, pharmacist_headers):
        """PRD §3.5: "Calling rework when `rework_count` is already 2 does not cycle again: the same call instead moves the batch to the terminal `FAILED` state, returned with a 200 status — the rework cap of 2 has been reached."
        PRD §4: "The rework endpoint returns `200` on both its cycle and its terminal `FAILED` outcome."

        Design: Difficulty/non_linear_state_machine/batch_rework_cycle
        """
        batch_ns, pharm_headers = self._setup_rejectable_batch(api)
        for reason in ("r1", "r2", "r3"):
            if reason != "r1":
                fixtures.start_batch(batch_ns)
                fixtures.complete_batch(batch_ns, [10.0], waste_ml=0.0,
                                        storage_condition="ROOM")
            validate_success(
                api.qa_reject_batch(batch_ns.batch["id"], {"reason": reason},
                                    pharm_headers),
                200,
            )
            outcome = validate_success(
                api.rework_batch(batch_ns.batch["id"], batch_ns.technician_headers),
                200,
            )
        assert outcome["status"] == "FAILED"
        assert outcome["rework_count"] == 2
        fetched = validate_success(
            api.get_batch(batch_ns.batch["id"], pharmacist_headers), 200
        )
        assert fetched["status"] == "FAILED"


class TestQaSegregationOfDuties:
    def test_release_with_compounder_id_rejected_then_distinct_pharmacist_releases(
        self, api
    ):
        """PRD §3.5: "Quality review belongs to a `Pharmacist`, with segregation of duties enforced on both branches: the reviewing pharmacist's `X-User-ID` must differ from the batch's `compounder_staff_id`, and a self-review is rejected with `ERR_SOD_VIOLATION`."
        PRD §2.1: "The server resolves the `StaffMember` row with that `id`; the row must exist, its `active` flag must be true, and its `staff_role` must equal the `X-User-Role` header value — so a call made as `Pharmacist` must present the `id` of a staff member whose `staff_role` is `PHARMACIST`."

        Design: Corner/validations/qa_release_same_as_compounder_forbidden
        """
        ns = setup_verified_order(route="IV", ordered_dose_mg=100.0)
        batch_ns = fixtures.setup_batch_qa_review([ns.order["id"]], [10.0])
        # Presenting the technician compounder's id under the Pharmacist header
        # fails the entity-backed staff resolution (his staff_role is TECHNICIAN).
        resp = api.qa_release_batch(
            batch_ns.batch["id"],
            {"X-User-ID": batch_ns.technician["id"], "X-User-Role": "Pharmacist",
             "Content-Type": "application/json"},
        )
        validate_error(resp, "ERR_ROLE_MISMATCH", 403)
        released = validate_success(
            api.qa_release_batch(batch_ns.batch["id"], ns.pharmacist_headers), 200
        )
        assert released["status"] == "RELEASED"
        assert released["qa_pharmacist_staff_id"] == ns.pharmacist["id"]


class TestPreparationAutoExpiry:
    def test_clock_reaching_bud_expiry_marks_preparation_expired(self, api, admin_headers, pharmacist_headers):
        """PRD §2.6: "Setting the clock runs two expiry sweeps before the response is returned, and the same sweeps are evaluated before any dispense is processed: first, every compounded preparation whose `bud_expiry` has been reached or passed — that is, the logical clock is at or after `bud_expiry`, the boundary itself counts as expired — and whose status is `COMPOUNDED` or `QA_PASSED` transitions to `EXPIRED`, with a waste record appended for each expired preparation carrying the reason `EXPIRED`"

        Design: Corner/state_machines/preparation_auto_expiry_on_clock_sweep
        """
        ns = setup_verified_order(route="IV", ordered_dose_mg=100.0)
        batch_ns = fixtures.setup_batch_qa_review(
            [ns.order["id"]], [10.0], usp_risk_level="HIGH",
            storage_condition="ROOM",
        )
        preps, _ = validate_paginated(
            api.list_preparations(pharmacist_headers,
                                  params={"order_id": ns.order["id"]})
        )
        prep = preps[0]
        assert prep["status"] == "COMPOUNDED"
        # HIGH/ROOM = 24h from the 2026-08-01T00:00:00Z completion; compare as
        # parsed instants (PRD §2.4 pins the 3-fractional-digit wire format).
        assert datetime.fromisoformat(
            prep["bud_expiry"].replace("Z", "+00:00")
        ) == datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)
        fixtures.set_clock("2026-08-02T00:00:00Z")
        preps, _ = validate_paginated(
            api.list_preparations(pharmacist_headers,
                                  params={"order_id": ns.order["id"]})
        )
        assert preps[0]["status"] == "EXPIRED"
        waste_rows, _ = validate_paginated(
            api.list_batch_waste_records(batch_ns.batch["id"], pharmacist_headers)
        )
        assert any(r["reason"] == "EXPIRED" for r in waste_rows)

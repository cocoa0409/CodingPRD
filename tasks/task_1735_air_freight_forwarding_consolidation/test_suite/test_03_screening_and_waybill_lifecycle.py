"""House waybill lifecycle: creation, screening records, demerit ledger (PRD §3.1, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_house_waybill,
    assert_shipper,
    clear_hwb,
    create_hwb,
    create_known_shipper,
    create_shipper,
    drive_shipper_to_suspended,
    get_hwb,
    list_screening_records,
    make_forwarder_ops_headers,
    resolve_screening,
    submit_hwb,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCreationDefaults:
    def test_shipper_creation_defaults_and_system_fields(
        self, api, forwarder_ops_headers
    ):
        """PRD §3.1: "A new shipper starts with `known_shipper_status` of `UNVERIFIED`
        and a `screening_rejection_count` of zero."
        PRD §2.4: "Every primary resource — shipper, flight booking, master waybill,
        house waybill, screening record, customs entry, rate agreement, and claim —
        carries a standard set of system-managed fields"

        Design: Corner/entities/shipper_creation_defaults_and_system_fields
        """
        resp = api.create_shipper(
            {"name": "Acme Exports", "account_code": "ACME"}, forwarder_ops_headers
        )
        data = validate_success(resp, expected_status=201)
        assert_shipper(data)
        assert data["known_shipper_status"] == "UNVERIFIED"
        assert data["screening_rejection_count"] == 0

    def test_house_waybill_initial_state_draft(self, api, forwarder_ops_headers):
        """PRD §3.3: "A new waybill is `DRAFT`, its computed charge fields are zero,
        its `weight_basis` is `UNRATED`, and its `mawb_id` is null."
        PRD §3.6: "Recording it sets `measured_volume_m3` and recomputes
        `effective_volume_m3`, which always reads the measured volume when set and
        falls back to `declared_volume_m3` otherwise."

        Design: Corner/state_machines/house_waybill_initial_state_draft
        """
        shipper = create_shipper()
        resp = api.create_house_waybill(
            {
                "shipper_id": shipper["id"],
                "hwb_number": "HWB-INIT",
                "origin_code": "SFO",
                "destination_code": "NRT",
                "pieces": 1,
                "gross_weight_kg": 10.0,
                "declared_volume_m3": 0.05,
            },
            forwarder_ops_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_house_waybill(data)
        assert data["status"] == "DRAFT"
        assert data["weight_basis"] == "UNRATED"
        assert data["mawb_id"] is None
        assert data["chargeable_weight_kg"] == 0
        assert data["total_charge_amount"] == 0
        assert data["effective_volume_m3"] == pytest.approx(0.05, abs=1e-9), (
            "unmeasured waybill's effective volume falls back to the declared volume"
        )

    def test_house_waybill_missing_required_field_returns_invalid_request(
        self, api, forwarder_ops_headers
    ):
        """PRD §3.3: "A `ForwarderOps` agent issues a house waybill for a customer by
        supplying the `shipper_id`, a `hwb_number` unique across all house waybills,
        the lane endpoints `origin_code` and `destination_code`, the `pieces` count,
        the actual `gross_weight_kg`, and the shipper-declared `declared_volume_m3`."
        PRD §2.6: "8. Structural and aggregate guards — waybill number and account code
        uniqueness (`ERR_DUPLICATE_WAYBILL_NUMBER`), tender-window buffering
        (`ERR_TENDER_WINDOW_CONFLICT`), rate agreement overlap
        (`ERR_RATE_AGREEMENT_OVERLAP`), tender requires a consolidated waybill
        (`ERR_NO_CONSOLIDATED_HOUSE_WAYBILLS`), close blocked by open claims
        (`ERR_OPEN_CLAIMS_EXIST`), one open claim per waybill
        (`ERR_DUPLICATE_OPEN_CLAIM`), and other malformed-input rejections
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/house_waybill_missing_required_field_returns_invalid_request
        """
        shipper = create_shipper()
        resp = api.create_house_waybill(
            {
                "shipper_id": shipper["id"],
                "hwb_number": "HWB-NOPIECES",
                "origin_code": "SFO",
                "destination_code": "NRT",
                "gross_weight_kg": 10.0,
                "declared_volume_m3": 0.05,
            },
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _rows, meta = validate_paginated(
            api.list_house_waybills(
                forwarder_ops_headers, params={"shipper_id": shipper["id"]}
            )
        )
        assert meta["total_count"] == 0, "a rejected creation must persist nothing"

    def test_duplicate_hwb_number_rejected(self, api, forwarder_ops_headers):
        """PRD §3.3: "A `ForwarderOps` agent issues a house waybill for a customer by
        supplying the `shipper_id`, a `hwb_number` unique across all house waybills"
        PRD §2.6: "Structural and aggregate guards — waybill number and account code
        uniqueness (`ERR_DUPLICATE_WAYBILL_NUMBER`)"

        Design: Corner/validations/duplicate_hwb_number_rejected
        """
        shipper1 = create_shipper()
        shipper2 = create_shipper(name="Beta Freight", account_code="BETA")
        create_hwb(
            shipper1["id"], "HWB-DUP", pieces=1, gross_weight_kg=10.0,
            declared_volume_m3=0.05,
        )
        resp = api.create_house_waybill(
            {
                "shipper_id": shipper2["id"],
                "hwb_number": "HWB-DUP",
                "origin_code": "LAX",
                "destination_code": "JFK",
                "pieces": 2,
                "gross_weight_kg": 20.0,
                "declared_volume_m3": 0.10,
            },
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_WAYBILL_NUMBER)
        _rows, meta = validate_paginated(
            api.list_house_waybills(
                forwarder_ops_headers, params={"shipper_id": shipper2["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestTerminalLockdown:
    def test_cancel_already_cancelled_hwb_returns_invalid_state(
        self, api, forwarder_ops_headers
    ):
        """PRD §3.3: "a waybill in `DRAFT`, `SCREENING`, `SCREENING_REJECTED`, or
        `CLEARED` may be cancelled by `ForwarderOps`, landing in terminal `CANCELLED`;
        from any other state the request is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_already_cancelled_hwb_returns_invalid_state
        """
        shipper = create_shipper()
        hwb = create_hwb(
            shipper["id"], "HWB-X1", pieces=1, gross_weight_kg=10.0,
            declared_volume_m3=0.05,
        )
        first = validate_success(api.cancel_house_waybill(hwb["id"], forwarder_ops_headers))
        assert first["status"] == "CANCELLED"

        second = api.cancel_house_waybill(hwb["id"], forwarder_ops_headers)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

        after = get_hwb(hwb["id"])
        assert after["status"] == "CANCELLED"
        assert after["version"] == first["version"], (
            "a rejected transition must not mutate the waybill"
        )


class TestScreeningRecords:
    def test_submit_creates_required_screening_records(self, api):
        """PRD §3.3: "Submitting a `DRAFT` waybill to screening moves it to
        `SCREENING`, stamps `submitted_by_user_id` with the caller's `X-User-ID`, and
        auto-creates the required screening records: always one of `screening_type`
        `SECURITY`, and additionally one of type `DANGEROUS_GOODS` exactly when the
        waybill's `dg_flag` is true. Within a single submit the security record is
        created first and the dangerous-goods record second, with strictly increasing
        `created_at`. Each new record starts with `result` `PENDING`."

        Design: Corner/state_machines/submit_creates_required_screening_records
        """
        shipper = create_known_shipper()
        hwb_dg = create_hwb(
            shipper["id"], "HWB-DG", pieces=2, gross_weight_kg=20.0,
            declared_volume_m3=0.10, dg_flag=True,
        )
        hwb_gen = create_hwb(
            shipper["id"], "HWB-GEN", pieces=1, gross_weight_kg=10.0,
            declared_volume_m3=0.05, dg_flag=False,
        )

        submitted = submit_hwb(hwb_dg["id"], user_id="ops-1")
        assert submitted["status"] == "SCREENING"
        assert submitted["submitted_by_user_id"] == "ops-1"
        dg_records = list_screening_records(hwb_dg["id"])
        assert [r["screening_type"] for r in dg_records] == [
            "SECURITY",
            "DANGEROUS_GOODS",
        ], "SECURITY record must precede the DANGEROUS_GOODS record within one submit"
        assert all(r["result"] == "PENDING" for r in dg_records)
        assert all(r.get("resolved_by_user_id") is None for r in dg_records)

        submit_hwb(hwb_gen["id"], user_id="ops-1")
        gen_records = list_screening_records(hwb_gen["id"])
        assert [r["screening_type"] for r in gen_records] == ["SECURITY"]

    def test_latest_record_per_type_gates_clearance(self, api):
        """PRD §3.3: "the existing screening records are retained for audit, and a
        later re-submission creates fresh records, with clearance always judged on the
        latest record per type."
        PRD §3.3: "when the latest record of every required type — `SECURITY` always,
        `DANGEROUS_GOODS` exactly when `dg_flag` is set — is `CLEARED`, the waybill
        moves from `SCREENING` to `CLEARED`."

        Design: Corner/state_machines/latest_record_per_type_gates_clearance
        """
        shipper = create_known_shipper()
        hwb = create_hwb(
            shipper["id"], "HWB-DG2", pieces=2, gross_weight_kg=20.0,
            declared_volume_m3=0.10, dg_flag=True,
        )
        submit_hwb(hwb["id"], user_id="ops-1")
        first_pair = list_screening_records(hwb["id"])
        resolve_screening(
            first_pair[1]["id"], "REJECTED", rejection_reason="bad DG declaration"
        )
        assert get_hwb(hwb["id"])["status"] == "SCREENING_REJECTED"

        recalled = validate_success(
            api.recall_house_waybill(hwb["id"], make_forwarder_ops_headers("ops-1"))
        )
        assert recalled["status"] == "DRAFT"

        submit_hwb(hwb["id"], user_id="ops-1")
        records = list_screening_records(hwb["id"])
        assert len(records) == 4, "the rejected first pair is retained for audit"

        resolve_screening(records[2]["id"], "CLEARED")
        assert get_hwb(hwb["id"])["status"] == "SCREENING", (
            "latest DANGEROUS_GOODS record still PENDING — clearance gate unmet"
        )

        resolve_screening(records[3]["id"], "CLEARED")
        assert get_hwb(hwb["id"])["status"] == "CLEARED", (
            "latest record per type is CLEARED despite the older REJECTED record"
        )

        final_records = list_screening_records(hwb["id"])
        assert [(r["screening_type"], r["result"]) for r in final_records] == [
            ("SECURITY", "PENDING"),
            ("DANGEROUS_GOODS", "REJECTED"),
            ("SECURITY", "CLEARED"),
            ("DANGEROUS_GOODS", "CLEARED"),
        ]


class TestScreeningRevisionCycle:
    def test_rejection_moves_waybill_to_screening_rejected_and_recall_returns_draft(
        self, api, forwarder_ops_headers
    ):
        """PRD §3.3: "When the latest record of any required type is `REJECTED`, the
        waybill moves from `SCREENING` to `SCREENING_REJECTED` and the demerit cascade
        of §2.10 runs: the owning shipper's `screening_rejection_count` increments by
        one"
        PRD §3.3: "A `ForwarderOps` agent may recall a waybill from `SCREENING` or
        `SCREENING_REJECTED` back to `DRAFT` for correction"

        Design: Difficulty/non_linear_state_machine/house_waybill_screening_revision_cycle
        """
        shipper = create_known_shipper()
        hwb = create_hwb(
            shipper["id"], "HWB-DG1", pieces=2, gross_weight_kg=20.0,
            declared_volume_m3=0.10, dg_flag=True,
        )
        submit_hwb(hwb["id"], user_id="ops-1")
        sec_record, dg_record = list_screening_records(hwb["id"])

        resolve_screening(
            dg_record["id"], "REJECTED",
            rejection_reason="DG declaration missing packing instruction",
        )
        assert get_hwb(hwb["id"])["status"] == "SCREENING_REJECTED"
        shipper_after = validate_success(
            api.get_shipper(shipper["id"], forwarder_ops_headers)
        )
        assert shipper_after["screening_rejection_count"] == 1

        recalled = validate_success(
            api.recall_house_waybill(hwb["id"], forwarder_ops_headers)
        )
        assert recalled["status"] == "DRAFT"

    def test_resubmission_creates_fresh_records_and_full_cycle_clears(self, api):
        """PRD §3.3: "the existing screening records are retained for audit, and a
        later re-submission creates fresh records, with clearance always judged on the
        latest record per type."
        PRD §3.3: "when the latest record of every required type — `SECURITY` always,
        `DANGEROUS_GOODS` exactly when `dg_flag` is set — is `CLEARED`, the waybill
        moves from `SCREENING` to `CLEARED`."

        Design: Difficulty/non_linear_state_machine/house_waybill_screening_revision_cycle
        """
        shipper = create_known_shipper()
        hwb = create_hwb(
            shipper["id"], "HWB-DG1", pieces=2, gross_weight_kg=20.0,
            declared_volume_m3=0.10, dg_flag=True,
        )
        submit_hwb(hwb["id"], user_id="ops-1")
        first_pair = list_screening_records(hwb["id"])
        resolve_screening(
            first_pair[1]["id"], "REJECTED", rejection_reason="missing packing instruction"
        )
        validate_success(api.recall_house_waybill(hwb["id"], make_forwarder_ops_headers("ops-1")))

        submit_hwb(hwb["id"], user_id="ops-1")
        records = list_screening_records(hwb["id"])
        assert len(records) == 4, "resubmission appends a fresh SECURITY + DG pair"
        assert records[2]["screening_type"] == "SECURITY"
        assert records[2]["result"] == "PENDING"
        assert records[3]["screening_type"] == "DANGEROUS_GOODS"
        assert records[3]["result"] == "PENDING"

        resolve_screening(records[2]["id"], "CLEARED")
        assert get_hwb(hwb["id"])["status"] == "SCREENING", (
            "DANGEROUS_GOODS gate unmet — waybill must not clear on SECURITY alone"
        )

        resolve_screening(records[3]["id"], "CLEARED")
        assert get_hwb(hwb["id"])["status"] == "CLEARED", (
            "cycle DRAFT->SCREENING->SCREENING_REJECTED->DRAFT->SCREENING->CLEARED completed"
        )


class TestDemeritSuspension:
    def test_third_rejection_suspends_known_shipper(self, api, forwarder_ops_headers):
        """PRD §3.3: "the owning shipper's `screening_rejection_count` increments by
        one, and when the count after increment reaches three while the shipper is
        `KNOWN`, the shipper's `known_shipper_status` becomes `SUSPENDED`
        automatically. The boundary is inclusive — the third rejection suspends, the
        second does not"

        Design: Difficulty/transitive_cascade/screening_rejection_demerit_suspension_depth3
        """
        shipper = create_known_shipper()
        rejected = drive_shipper_to_suspended(shipper["id"])

        after_1 = validate_success(api.get_shipper(shipper["id"], forwarder_ops_headers))
        # All three rejections already applied; walk the counter states explicitly:
        assert after_1["screening_rejection_count"] == 3
        assert after_1["known_shipper_status"] == "SUSPENDED"
        for hwb_id in rejected:
            assert get_hwb(hwb_id)["status"] == "SCREENING_REJECTED"

    def test_counter_increments_and_suspension_gates_dg_submission(
        self, api, forwarder_ops_headers
    ):
        """PRD §3.3: "a suspended shipper's future dangerous-goods submissions and
        consolidations are gated by `ERR_SHIPPER_NOT_KNOWN`."
        PRD §3.3: "If the waybill is dangerous goods and the shipper is not `KNOWN`,
        submission is refused with `ERR_SHIPPER_NOT_KNOWN`"

        Design: Difficulty/transitive_cascade/screening_rejection_demerit_suspension_depth3
        """
        shipper = create_known_shipper()

        # Drive the demerit counter one rejection at a time, observing each step.
        counts = []
        for i in (1, 2, 3):
            hwb = create_hwb(
                shipper["id"], f"HWB-R{i}", pieces=1, gross_weight_kg=10.0,
                declared_volume_m3=0.05, dg_flag=False,
            )
            submit_hwb(hwb["id"])
            record = list_screening_records(hwb["id"])[0]
            resolve_screening(record["id"], "REJECTED", rejection_reason="untraceable box")
            snap = validate_success(api.get_shipper(shipper["id"], forwarder_ops_headers))
            counts.append((snap["screening_rejection_count"], snap["known_shipper_status"]))
        assert counts[0] == (1, "KNOWN"), "first rejection must not suspend"
        assert counts[1] == (2, "KNOWN"), "second rejection must not suspend"
        assert counts[2] == (3, "SUSPENDED"), "third rejection suspends (inclusive boundary)"

        dg_hwb = create_hwb(
            shipper["id"], "HWB-DG4", pieces=1, gross_weight_kg=10.0,
            declared_volume_m3=0.05, dg_flag=True,
        )
        resp = api.submit_house_waybill(dg_hwb["id"], forwarder_ops_headers)
        validate_error(resp, ApiErrorId.ERR_SHIPPER_NOT_KNOWN)

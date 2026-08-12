"""Tray reprocessing pipeline: off-machine transition rejections, the
count-sheet exact-match boundary, and the immutable audit record.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_assembly_verification,
    make_supervisor_headers,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["facility_admin_headers"]


def test_tray_invalid_from_transitions_rejected(api):
    """PRD §3.2: "Completing decontamination requires `IN_DECONTAMINATION`
    (else `ERR_TRAY_NOT_IN_DECONTAMINATION`)". "Beginning assembly requires
    `DECONTAMINATED` (else `ERR_TRAY_NOT_DECONTAMINATED`)". "The submission is
    rejected with `ERR_TRAY_NOT_IN_ASSEMBLY` if the tray is anywhere else in
    the pipeline." "the tray must be `QUARANTINED`, else
    `ERR_TRAY_NOT_QUARANTINED`".

    Design: Corner/state_machines/tray_invalid_from_transitions_rejected
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    sup = fx.create_technician(api, name="Sup S", certification_level=3)
    tray = fx.create_tray(api, tpl["id"], tech["id"], label="TA")
    h = make_technician_headers(tech["id"])

    e1 = api.complete_decontamination(tray["id"], h)
    validate_error(e1, ApiErrorId.ERR_TRAY_NOT_IN_DECONTAMINATION)
    e2 = api.start_assembly(tray["id"], h)
    validate_error(e2, ApiErrorId.ERR_TRAY_NOT_DECONTAMINATED)
    e3 = api.submit_assembly_verification(
        tray["id"], f.assembly_verification_payload(), h
    )
    validate_error(e3, ApiErrorId.ERR_TRAY_NOT_IN_ASSEMBLY)
    e4 = api.discard_tray(tray["id"], make_supervisor_headers(sup["id"]))
    validate_error(e4, ApiErrorId.ERR_TRAY_NOT_QUARANTINED)

    after = validate_success(api.get_tray(tray["id"], ADMIN))
    assert after["status"] == "AWAITING_DECONTAMINATION", (
        "no rejected call may mutate tray state"
    )


def test_decontamination_restart_from_decontaminated_rejected(api):
    """PRD §3.2: "it is permitted from either `AWAITING_DECONTAMINATION` or
    `QUARANTINED` (any other status is rejected with
    `ERR_TRAY_NOT_READY_FOR_DECONTAMINATION`)".

    Design: Corner/errors/error_tray_not_ready_for_decontamination_trigger
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    tray = fx.create_decontaminated_tray(api, tpl["id"], tech["id"], label="TD")
    resp = api.start_decontamination(tray["id"], make_technician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_TRAY_NOT_READY_FOR_DECONTAMINATION)


def test_assembly_verification_is_immutable_record(api):
    """PRD §2.5: "Assembly verification records are immutable audit entries
    and carry only `id` and `created_at`; both `updated_at` and `version` are
    absent from them." PRD §3.2: "Each verification record carries the
    `tray_id` verified and the acting `technician_id` taken from `X-User-ID`".

    Design: Corner/entities/assembly_verification_is_immutable_record
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    tray = fx.create_tray(api, tpl["id"], tech["id"], label="V1")
    fx.decontaminate(api, tray["id"], tech["id"])
    h = make_technician_headers(tech["id"])
    validate_success(api.start_assembly(tray["id"], h))

    resp = api.submit_assembly_verification(
        tray["id"],
        f.assembly_verification_payload(
            lines=[{"instrument_type": "SCALPEL", "counted_qty": 1}]
        ),
        h,
    )
    record = validate_success(resp, 201)
    assert record["result"] == "FAIL"
    assert record["mismatch_count"] == 1

    fetched = validate_success(api.get_assembly_verification(record["id"], ADMIN))
    assert_assembly_verification(fetched)
    assert fetched["technician_id"] == tech["id"]
    assert fetched["tray_id"] == tray["id"]


def test_immediate_read_after_write_visibility(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §3.2: "Trays can be listed with filters on `template_id`,
    `current_load_id`, and `status`".

    Design: Corner/consistency_model/immediate_read_after_write_visibility
    """
    tpl = fx.create_template(api)
    tech = fx.create_technician(api)
    h = make_technician_headers(tech["id"])

    created = validate_success(
        api.create_tray(f.create_tray_payload(tpl["id"], label="IW"), h), 201
    )
    assert created["status"] == "AWAITING_DECONTAMINATION"

    moved = validate_success(api.start_decontamination(created["id"], h), 200)
    assert moved["status"] == "IN_DECONTAMINATION"

    reread = validate_success(api.get_tray(created["id"], ADMIN))
    assert reread["status"] == "IN_DECONTAMINATION"

    rows, meta = validate_paginated(
        api.list_trays(ADMIN, params={"status": "IN_DECONTAMINATION"})
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == created["id"]


class TestCountSheetExactMatch:
    """The zero-tolerance count-sheet boundary (two tests, one design
    instance)."""

    def test_count_sheet_exact_match_passes_and_assembles(self, api):
        """PRD §3.2: "the `result` is `PASS` when every requirement line's
        `counted_qty` matches the required `quantity` exactly and no extra
        `instrument_type` appears; otherwise the `result` is `FAIL`." "A
        `PASS` verification persists the record (with `mismatch_count` 0) and
        advances the tray to `ASSEMBLED`."

        Design: Difficulty/boundary_precision_check/count_sheet_exact_match_vs_off_by_one
        """
        s = fx.setup_count_sheet_scenario(api)
        h = make_technician_headers(s.tech_a["id"])
        resp = api.submit_assembly_verification(
            s.ta["id"],
            f.assembly_verification_payload(lines=[
                {"instrument_type": "SCALPEL", "counted_qty": 2},
                {"instrument_type": "FORCEPS", "counted_qty": 1},
            ]),
            h,
        )
        record = validate_success(resp, 201)
        assert record["result"] == "PASS"
        assert record["mismatch_count"] == 0
        tray = validate_success(api.get_tray(s.ta["id"], ADMIN))
        assert tray["status"] == "ASSEMBLED"

    def test_count_sheet_off_by_one_fails_and_holds_assembly(self, api):
        """PRD §3.2: "The computed `mismatch_count` tallies every requirement
        line whose counted quantity differs from the requirement — missing
        types count as a counted quantity of 0, and unexpected extra types each
        count as a mismatch." "A `FAIL` verification leaves the tray
        `IN_ASSEMBLY`, persists the record with its non-zero `mismatch_count`,
        and attributes a 2-point competency demerit to the acting technician
        (§3.8) — re-verification is allowed afterward."

        Design: Difficulty/boundary_precision_check/count_sheet_exact_match_vs_off_by_one
        """
        s = fx.setup_count_sheet_scenario(api)
        h = make_technician_headers(s.tech_a["id"])
        resp = api.submit_assembly_verification(
            s.tb["id"],
            f.assembly_verification_payload(lines=[
                {"instrument_type": "SCALPEL", "counted_qty": 1},
                {"instrument_type": "FORCEPS", "counted_qty": 1},
            ]),
            h,
        )
        record = validate_success(resp, 201)
        assert record["result"] == "FAIL"
        assert record["mismatch_count"] == 1
        tray = validate_success(api.get_tray(s.tb["id"], ADMIN))
        assert tray["status"] == "IN_ASSEMBLY", (
            "a FAIL verification leaves the tray IN_ASSEMBLY"
        )

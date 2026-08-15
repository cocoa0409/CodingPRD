"""Annual inspections: certification decisions, quarantine cascades, and
segregation of duties."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_customer, create_equipment_class, create_equipment_unit,
    create_contract, add_line, activate_contract, set_clock,
    setup_draft_contract_with_line, setup_active_rental,
    create_inspection_record, certify_inspection, reject_inspection,
    get_line, get_unit, get_contract,
    make_branch_manager_headers, assert_inspection_record,
)


class TestFailCertificationCascade:
    def test_fail_certification_quarantines_unit_and_cancels_reserved_line(
            self, api, branch_manager_headers):
        """PRD §3.6: "When the unit is `AVAILABLE`, it moves to `QUARANTINED`,
        and every `RESERVED` line booked against that unit is cancelled by
        cascade — each such line moves from `RESERVED` to `CANCELLED` with its
        `version` incrementing, its contract's `rental_subtotal_cents` is
        recomputed with the contract's `version` incrementing, and the
        affected customer's balance is recomputed — while lines already
        `OUT_ON_RENT` or `OFF_RENT` are unaffected."

        Design: Difficulty/transitive_cascade/fail_inspection_quarantines_unit_cancels_line
        """
        ctx = setup_draft_contract_with_line(
            class_kwargs={"class_code": "S19F"},
            requested_start_date="2026-09-01", requested_end_date="2026-09-10")
        record = create_inspection_record(ctx["unit"]["id"], "2026-08-20",
                                          result="FAIL", inspector_id="yt-1")

        decided = certify_inspection(record["id"], manager_id="bm-1")
        assert_inspection_record(decided)
        assert decided["status"] == "CERTIFIED"
        assert decided["certified_by"] == "bm-1"

        assert get_unit(ctx["unit"]["id"])["status"] == "QUARANTINED"
        assert get_line(ctx["line"]["id"])["status"] == "CANCELLED", (
            "the cascade caused by the quarantine cancels the RESERVED line")
        assert get_contract(ctx["contract"]["id"])["rental_subtotal_cents"] == 0, (
            "a CANCELLED line contributes zero")

    def test_rejected_fail_record_leaves_unit_untouched(self, api):
        """PRD §3.6: "A rejected record has no effect on the unit at all; the
        inspection simply needs to be redone."

        Design: Difficulty/transitive_cascade/fail_inspection_quarantines_unit_cancels_line
        """
        ctx = setup_draft_contract_with_line(
            class_kwargs={"class_code": "S19RJ"},
            requested_start_date="2026-09-01", requested_end_date="2026-09-10")
        record = create_inspection_record(ctx["unit"]["id"], "2026-08-20",
                                          result="FAIL", inspector_id="yt-1")

        decided = reject_inspection(record["id"], manager_id="bm-1")
        assert decided["status"] == "REJECTED"
        assert decided["certified_by"] == "bm-1"

        assert get_unit(ctx["unit"]["id"])["status"] == "AVAILABLE"
        assert get_line(ctx["line"]["id"])["status"] == "RESERVED"

    def test_fail_cancels_only_reserved_lines_on_on_rent_unit(self, api):
        """PRD §3.6: "When the unit is `ON_RENT`, its status is unchanged —
        the current renter keeps the machine — but the same cancellation
        cascade still clears the unit's `RESERVED` lines."

        Design: Corner/state_machines/fail_inspection_cancels_only_reserved_lines
        """
        ctx = setup_active_rental(
            class_kwargs={"class_code": "S19X"},
            requested_start_date="2026-08-05", requested_end_date="2026-08-15",
            planned_start_utc="2026-08-05T08:00:00Z",
            planned_end_utc="2026-08-05T10:00:00Z",
            deliver_at="2026-08-05T09:00:00Z")
        contract_b = create_contract(ctx["customer"]["id"], "2 Second St")
        future = add_line(contract_b["id"], ctx["unit"]["id"],
                          "2026-08-20", "2026-08-25", 20)
        record = create_inspection_record(ctx["unit"]["id"], "2026-08-06",
                                          result="FAIL", inspector_id="yt-1")

        certify_inspection(record["id"], manager_id="bm-1")

        assert get_unit(ctx["unit"]["id"])["status"] == "ON_RENT", (
            "FAIL while ON_RENT does not quarantine the deployed unit")
        assert get_line(ctx["line"]["id"])["status"] == "OUT_ON_RENT", (
            "the OUT_ON_RENT line is unaffected")
        assert get_line(future["id"])["status"] == "CANCELLED", (
            "the conditional cascade clears only the RESERVED line")


class TestPassCertification:
    def test_pass_inspection_extends_due_date(self, api, branch_manager_headers):
        """PRD §3.6: "A certified `PASS` rewrites the unit's inspection
        calendar: `last_annual_inspection_date` is set to the record's
        `inspection_date` and `next_inspection_due_date` is recomputed three
        hundred sixty-five days out from it."

        Design: Corner/calculations/pass_inspection_extends_due_date
        """
        set_clock("2026-08-01T09:00:00Z")
        cls = create_equipment_class(class_code="S19PI")
        unit = create_equipment_unit(cls["id"], "S19PI-001")
        assert unit["last_annual_inspection_date"] == "2026-08-01"
        assert unit["next_inspection_due_date"] == "2027-08-01"

        record = create_inspection_record(unit["id"], "2026-08-20",
                                          result="PASS", inspector_id="yt-1")
        decided = certify_inspection(record["id"], manager_id="bm-1")
        assert decided["status"] == "CERTIFIED"

        refreshed = get_unit(unit["id"])
        assert refreshed["last_annual_inspection_date"] == "2026-08-20"
        assert refreshed["next_inspection_due_date"] == "2027-08-20"


class TestSegregationOfDuties:
    def test_segregation_of_duties_certify_rejected(self, api,
                                                    branch_manager_headers):
        """PRD §3.6: "the manager who certifies or rejects a record must not
        be the technician who submitted it — a caller whose identity equals
        the record's `inspector_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) on either action."

        Design: Corner/validations/segregation_of_duties_certify_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        cls = create_equipment_class(class_code="S19SD")
        unit = create_equipment_unit(cls["id"], "S19SD-001")
        record = create_inspection_record(unit["id"], "2026-08-15",
                                          result="PASS", inspector_id="yt-1")

        res = api.certify_inspection_record(
            record["id"], make_branch_manager_headers("yt-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        decided = validate_success(api.certify_inspection_record(
            record["id"], make_branch_manager_headers("bm-9")))
        assert decided["status"] == "CERTIFIED"
        assert decided["certified_by"] == "bm-9"

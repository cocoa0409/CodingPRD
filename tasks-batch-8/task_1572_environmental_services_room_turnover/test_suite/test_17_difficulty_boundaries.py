"""Difficulty queue A — boundary_precision_check instances (ATP threshold;
STAT eligibility at exactly 80.00)."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    create_placement_demand_payload,
    get_success_data,
    make_technician_headers,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    complete_request,
    create_all_standards,
    create_bed,
    create_request,
    create_staff,
    create_technician,
    create_unit,
    seed_supplies,
    start_request,
    submit_audit,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


class TestAtpExactThresholdPassesOneAboveFails:
    def test_rlu_exactly_at_threshold_passes(self, api):
        """PRD §3.6: "For `ATP_SWAB`, `threshold_used` is that row's
        `atp_rlu_threshold`, and the result is `PASS` exactly when the
        `rlu_reading` is less than or equal to it — a reading precisely at the
        threshold passes."

        Design: Difficulty/boundary_precision_check/atp_exact_threshold_passes_one_above_fails
        """
        ctx = _two_terminal_pending_qa(api)
        au = submit_audit(ctx["r1"]["id"], ctx["auditor"]["id"], rlu_reading=100)
        assert au["result"] == "PASS"
        assert au["threshold_used"] == 100

        req = get_success_data(api.get_clean_request(ctx["r1"]["id"], ANY))
        assert req["status"] == "VERIFIED"
        bed = get_success_data(api.get_bed(ctx["b1"]["id"], ANY))
        assert bed["bed_status"] == "READY"

    def test_rlu_one_above_threshold_fails(self, api):
        """PRD §3.6: "For `ATP_SWAB`, `threshold_used` is that row's
        `atp_rlu_threshold`, and the result is `PASS` exactly when the
        `rlu_reading` is less than or equal to it — a reading precisely at the
        threshold passes."
        PRD §3.6: "A **FAIL** cascade opens a reclean loop instead. The request
        moves `PENDING_QA → NEEDS_RECLEAN` and its `reclean_count` rises by
        one."

        Design: Difficulty/boundary_precision_check/atp_exact_threshold_passes_one_above_fails
        """
        ctx = _two_terminal_pending_qa(api)
        au = submit_audit(ctx["r2"]["id"], ctx["auditor"]["id"], rlu_reading=101)
        assert au["result"] == "FAIL"

        req = get_success_data(api.get_clean_request(ctx["r2"]["id"], ANY))
        assert req["status"] == "NEEDS_RECLEAN"
        assert req["reclean_count"] == 1
        bed = get_success_data(api.get_bed(ctx["b2"]["id"], ANY))
        assert bed["bed_status"] == "VACANT_DIRTY"


class TestStatEligibilityExactly80Boundary:
    def test_score_exactly_80_is_stat_eligible(self, api):
        """PRD §3.6: "Finally, `stat_eligible` holds when the technician has no
        verified cleans yet (`completed_clean_count` is zero) or when
        `productivity_score` has reached at least 80.00 — the gate that §3.4's
        STAT assignments consult."

        Design: Difficulty/boundary_precision_check/stat_eligibility_exactly_80_boundary
        """
        ctx = _stat_boundary_setup(api)
        tg = ctx["tg"]
        staff = get_success_data(api.get_staff(tg["id"], ANY))
        assert staff["productivity_score"] == pytest.approx(80.0, abs=0.01)
        assert staff["stat_eligible"] is True

    def test_score_75_excluded_from_stat_pull_while_80_admitted(self, api):
        """PRD §3.4: "Eligibility then filters the queue: the request's
        `clean_type` must be covered by the puller's certifications, a
        `STAT`-tier request is invisible to a puller whose `stat_eligible` is
        false ... When no request is eligible, the pull is rejected with
        `ERR_QUEUE_EMPTY`."
        PRD §3.6: "`stat_eligible` holds when the technician has no verified
        cleans yet (`completed_clean_count` is zero) or when
        `productivity_score` has reached at least 80.00."

        Design: Difficulty/boundary_precision_check/stat_eligibility_exactly_80_boundary
        """
        ctx = _stat_boundary_setup(api)
        tm, tg, rs = ctx["tm"], ctx["tg"], ctx["rs"]

        staff_tm = get_success_data(api.get_staff(tm["id"], ANY))
        assert staff_tm["productivity_score"] == pytest.approx(75.0, abs=0.01)
        assert staff_tm["stat_eligible"] is False

        r_miss = api.pull_clean_request(make_technician_headers(tm["id"]))
        validate_error(r_miss, ApiErrorId.ERR_QUEUE_EMPTY)

        pulled = get_success_data(api.pull_clean_request(make_technician_headers(tg["id"])))
        assert pulled["id"] == rs["id"]
        assert pulled["assigned_staff_id"] == tg["id"]
        assert pulled["status"] == "ASSIGNED"


# ---------------------------------------------------------------------------
# Local composite setups
# ---------------------------------------------------------------------------

def _two_terminal_pending_qa(api):
    """Unit + all standards + all supplies; two TERMINAL requests on STANDARD
    beds, each assigned to a TERMINAL_CERT tech and driven to PENDING_QA."""
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_all_standards()
    seed_supplies()
    tech = create_technician("T1", certifications=["TERMINAL_CERT"])
    get_success_data(api.clock_in_staff(tech["id"], make_technician_headers(tech["id"])))
    auditor = create_staff("A1", capabilities=("AUDIT",), display_name="Auditor One")
    b1 = create_bed(unit["id"], "B1", "STANDARD")
    b2 = create_bed(unit["id"], "B2", "STANDARD")

    r1 = create_request(b1["id"], "TERMINAL")
    assign_request(r1["id"], tech["id"])
    start_request(r1["id"], tech["id"])
    set_clock("2026-08-01T09:30:00Z")
    complete_request(r1["id"], tech["id"])

    r2 = create_request(b2["id"], "TERMINAL")
    assign_request(r2["id"], tech["id"])
    start_request(r2["id"], tech["id"])
    set_clock("2026-08-01T11:00:00Z")
    complete_request(r2["id"], tech["id"])

    return {
        "unit": unit,
        "tech": tech,
        "auditor": auditor,
        "b1": b1,
        "b2": b2,
        "r1": r1,
        "r2": r2,
    }


def _stat_boundary_setup(api):
    """Build the STAT-eligibility boundary scenario:
    - T_GOOD: two TERMINAL cleans, each exactly 90 minutes (ef 1.0 -> credit
      2.00 each, total 4.00), over a closed 5h shift -> score exactly 80.00.
    - T_MISS: same two passes plus one FAIL audit (penalty 5.00) over a closed
      5h shift -> score 75.00.
    - A STAT demand for STANDARD beds plus a fresh QUEUED ROUTINE request ->
      that request is STAT-tier.
    Both techs clocked back in afterwards so both may pull.
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_all_standards()
    seed_supplies()
    tg = create_technician("TG", certifications=["TERMINAL_CERT"], display_name="Tech Good")
    tm = create_technician("TM", certifications=["TERMINAL_CERT"], display_name="Tech Miss")
    auditor = create_staff("A1", capabilities=("AUDIT",), display_name="Auditor One")

    beds = {
        code: create_bed(unit["id"], code, "STANDARD")
        for code in ("G1", "G2", "M1", "M2", "M3", "S1")
    }

    def terminal_clean(bed_code, tech, start_ts, end_ts):
        req = create_request(beds[bed_code]["id"], "TERMINAL")
        assign_request(req["id"], tech["id"])
        start_request(req["id"], tech["id"])
        set_clock(end_ts)
        complete_request(req["id"], tech["id"])
        return req

    # T_GOOD: clock-in 08:00; G1 08:00-09:30; G2 09:40-11:10; out 13:00 = 5h.
    get_success_data(api.clock_in_staff(tg["id"], make_technician_headers(tg["id"])))
    rg1 = terminal_clean("G1", tg, CLOCK_T0800, "2026-08-01T09:30:00Z")
    submit_audit(rg1["id"], auditor["id"], rlu_reading=50)
    set_clock("2026-08-01T09:40:00Z")
    rg2 = terminal_clean("G2", tg, "2026-08-01T09:40:00Z", "2026-08-01T11:10:00Z")
    submit_audit(rg2["id"], auditor["id"], rlu_reading=50)

    # T_MISS: in 11:10; M1 11:20-12:50 PASS; M2 13:00-14:30 PASS; M3 14:40-16:10 FAIL.
    get_success_data(api.clock_in_staff(tm["id"], make_technician_headers(tm["id"])))
    set_clock("2026-08-01T11:20:00Z")
    rm1 = terminal_clean("M1", tm, "2026-08-01T11:20:00Z", "2026-08-01T12:50:00Z")
    submit_audit(rm1["id"], auditor["id"], rlu_reading=50)
    set_clock("2026-08-01T13:00:00Z")
    # T_GOOD's shift closes at 13:00, exactly 5h after the 08:00 clock-in.
    get_success_data(api.clock_out_staff(tg["id"], make_technician_headers(tg["id"])))
    rm2 = terminal_clean("M2", tm, "2026-08-01T13:00:00Z", "2026-08-01T14:30:00Z")
    submit_audit(rm2["id"], auditor["id"], rlu_reading=50)
    set_clock("2026-08-01T14:40:00Z")
    rm3 = terminal_clean("M3", tm, "2026-08-01T14:40:00Z", "2026-08-01T16:10:00Z")
    submit_audit(rm3["id"], auditor["id"], rlu_reading=400)

    # T_MISS's shift closes at 16:10, exactly 5h after the 11:10 clock-in.
    get_success_data(api.clock_out_staff(tm["id"], make_technician_headers(tm["id"])))

    # STAT queue: STAT demand for STANDARD + fresh QUEUED ROUTINE request.
    get_success_data(
        api.create_placement_demand(
            create_placement_demand_payload(
                unit_id=unit["id"],
                required_bed_kind="STANDARD",
                urgency_tier="STAT",
                needed_by="2026-08-01T20:00:00Z",
            ),
            COORDINATOR,
        )
    )
    rs = create_request(beds["S1"]["id"], "ROUTINE")

    # Clock both techs back in so both may pull.
    get_success_data(api.clock_in_staff(tg["id"], make_technician_headers(tg["id"])))
    get_success_data(api.clock_in_staff(tm["id"], make_technician_headers(tm["id"])))

    return {"unit": unit, "tg": tg, "tm": tm, "auditor": auditor, "rs": rs}

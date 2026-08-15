"""Rate-schedule lifecycle: publication, supersession, the consultation
window, consultation comments, reverse listing, and OCC on schedule creation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adopt_rates,
    assert_consultation_comment,
    create_airline,
    create_comment_payload,
    create_rates_setting,
    get_success_data,
    make_signatory_airline_headers,
    publish_rates,
    set_clock,
    setup_open_year,
    validate_error,
    validate_paginated,
    validate_success,
)

FINANCE = TEST_USERS["finance_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestSupersession:
    def test_adopt_on_superseded_schedule_rejected(self, api):
        """PRD §3.2: "Publication is also the airport's mechanism for replacing
        a schedule mid-year: if another schedule on the same fiscal year
        currently stands `ADOPTED`, that schedule automatically transitions to
        `SUPERSEDED`, its `version` increments, and the active agreements keyed
        to it become supersession-eligible."
        PRD §3.2: "`SUPERSEDED` and `EXPIRED` are the terminal states of a rate
        schedule."

        Design: Corner/state_machines/rates_setting_invalid_from_terminal_superseded
        """
        ws = setup_open_year("FY_INV_TR")
        rs_old = create_rates_setting(ws["fy"]["id"])
        publish_rates(rs_old["id"])
        set_clock("2026-09-01T00:00:00Z")
        adopt_rates(rs_old["id"])

        rs_new = create_rates_setting(ws["fy"]["id"])
        publish_rates(rs_new["id"])

        old = validate_success(api.get_rates_setting(rs_old["id"], FINANCE))
        assert old["status"] == "SUPERSEDED", (
            "Publishing the new schedule supersedes the adopted one")

        resp = api.adopt_rates_setting(rs_old["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_double_publish_rejected(self, api):
        """PRD §3.2: "When `AirportFinance` publishes a schedule, it moves from
        `DRAFT` to `CONSULTATION`; the parent fiscal year must stand `OPEN`,
        and the computed rate fields must be populated."
        PRD §2.8: "Only after the request is well-formed does the server ask
        whether the target resource's current state admits the requested
        transition (`ERR_INVALID_STATE`)"

        Design: Corner/errors/error_invalid_state_on_double_publish
        """
        ws = setup_open_year("FY_EP")
        rs = create_rates_setting(ws["fy"]["id"])
        publish_rates(rs["id"])

        resp = api.publish_rates_setting(rs["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_rates_setting(rs["id"], FINANCE))
        assert after["status"] == "CONSULTATION"


class TestConsultationWindow:
    def _setup_consultation(self, api):
        ws = setup_open_year("FY_OVL1")
        rs = create_rates_setting(ws["fy"]["id"])
        publish_rates(rs["id"])
        return ws, rs

    def test_adopt_before_thirty_days_rejected(self, api):
        """PRD §3.2: "A schedule in `CONSULTATION` may be adopted only once the
        logical clock has reached at least thirty days past the schedule's
        `created_at` — the minimum consultation period — and only while the
        parent fiscal year still stands `OPEN`; an adoption attempted before
        the window has elapsed is rejected with `ERR_TEMPORAL_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/consultation_window_vs_adopt_time
        """
        ws, rs = self._setup_consultation(api)
        # The schedule was created at the initial clock reading of 2026-08-01;
        # twenty-nine days later the minimum consultation period has not run.
        set_clock("2026-08-30T00:00:00Z")
        resp = api.adopt_rates_setting(rs["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_VIOLATION)

        after = validate_success(api.get_rates_setting(rs["id"], FINANCE))
        assert after["status"] == "CONSULTATION", (
            "The rejected adoption leaves the schedule in CONSULTATION")

    def test_adopt_at_exactly_thirty_days_succeeds(self, api):
        """PRD §3.2: "A schedule in `CONSULTATION` may be adopted only once the
        logical clock has reached at least thirty days past the schedule's
        `created_at` — the minimum consultation period — and only while the
        parent fiscal year still stands `OPEN`; an adoption attempted before
        the window has elapsed is rejected with `ERR_TEMPORAL_VIOLATION`."
        PRD §3.2: "Adoption stamps `adopted_at` with the current logical time,
        sets the schedule's status to `ADOPTED`, increments its `version`"

        Design: Difficulty/resource_temporal_overlap/consultation_window_vs_adopt_time
        """
        ws, rs = self._setup_consultation(api)
        set_clock("2026-08-31T00:00:00Z")
        adopted = validate_success(api.adopt_rates_setting(rs["id"], DIRECTOR))
        assert adopted["status"] == "ADOPTED", (
            "Adoption at exactly the thirty-day boundary is permitted")
        assert adopted["adopted_at"].startswith("2026-08-31"), (
            "adopted_at is stamped with the current logical time")


class TestConsultationComments:
    def test_comment_is_immutable_event_record_and_counted(self, api):
        """PRD §2.5: "A `ConsultationComment`, an `ActivityRecord`, and an
        `MIIVote` each receive only `id` and `created_at` among the common
        properties; both `updated_at` and `version` are absent on these three
        types, because their content never changes after creation."
        PRD §3.2: "each comment is stamped with `submitted_at`, carries its
        `rates_setting_id` back-reference, and increments the schedule's
        `consultation_comment_count` by one."

        Design: Corner/entities/consultation_comment_immutable_no_version
        """
        ws = setup_open_year("FY_CCM")
        rs = create_rates_setting(ws["fy"]["id"])
        publish_rates(rs["id"])
        airline = create_airline("CM", legal_name="Commenter Air")

        comment = validate_success(
            api.create_comment(rs["id"],
                               create_comment_payload(
                                   airline["id"], "concern about landing fee"),
                               make_signatory_airline_headers(airline["id"])),
            201,
        )
        assert_consultation_comment(comment)
        assert comment["rates_setting_id"] == rs["id"]

        after = validate_success(api.get_rates_setting(rs["id"], FINANCE))
        assert after["consultation_comment_count"] == 1, (
            "Each comment increments consultation_comment_count by one")


class TestRatesListingAndOcc:
    def test_rates_settings_reverse_reachable_from_year(self, api):
        """PRD §4 endpoint table: "List the rate schedules of one fiscal year"
        (GET /airport/fiscal_years/{id}/rates_settings).
        PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by their creation timestamp in ascending order."

        Design: Corner/endpoints/reverse_reachability_rates_settings_by_fy
        """
        ws = setup_open_year("FY_RR")
        rs_a = create_rates_setting(ws["fy"]["id"])
        rs_b = create_rates_setting(ws["fy"]["id"])

        data, meta = validate_paginated(
            api.list_rates_settings(ws["fy"]["id"], FINANCE))
        ids = [row["id"] for row in data]
        assert len(data) == 2, f"Expected 2 rate schedules, got {len(data)}"
        assert rs_a["id"] in ids and rs_b["id"] in ids

    def test_stale_fiscal_year_version_rejected(self, api):
        """PRD §2.10: "Creating a rate schedule for a fiscal year requires the
        request to carry `expected_fiscal_year_version`, set to the `version`
        of the parent fiscal year as the client last observed it. If the year's
        current `version` no longer matches — for example because another
        writer has advanced the year since the client last read it — the create
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/occ_stale_version_on_rates_setting_create
        """
        ws = setup_open_year("FY_OCC")
        observed = get_success_data(api.get_fiscal_year(ws["fy"]["id"], FINANCE))
        # First creation succeeds and advances the year's version.
        first = validate_success(
            api.create_rates_setting(
                ws["fy"]["id"],
                {"expected_fiscal_year_version": observed["version"]},
                FINANCE),
            201,
        )
        assert first["fiscal_year_id"] == ws["fy"]["id"]

        # Replaying the stale observed version is rejected.
        stale = api.create_rates_setting(
            ws["fy"]["id"],
            {"expected_fiscal_year_version": observed["version"]},
            FINANCE,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

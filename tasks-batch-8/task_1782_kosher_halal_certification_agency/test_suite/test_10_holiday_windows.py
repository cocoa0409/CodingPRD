"""Holiday production windows: overlap, confirmation gates, completion."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_window,
    create_certificate_payload,
    create_facility_for,
    create_prospect_client,
    get_success_data,
    make_client_contact_headers,
    make_officer_headers,
    make_supervisor_headers,
    request_holiday_window,
    set_clock,
    setup_certified_client,
    validate_error,
    validate_success,
)


class TestWindowOverlap:
    def test_holiday_window_half_open_adjacency_allowed_overlap_rejected(
            self, api):
        """PRD section 3.9: "Requests are half-open intervals — the start
        instant is included, the end instant excluded — and a new request is
        rejected with `ERR_WINDOW_OVERLAP` when its half-open interval
        intersects any `REQUESTED` or `CONFIRMED` window at the same facility;
        touching endpoints, where one window's end equals the other's start, do
        not intersect and are allowed."

        Design: Difficulty/resource_temporal_overlap/holiday_window_half_open_adjacency_allowed_overlap_rejected
        """
        client = create_prospect_client(legal_name="Overlap Co")
        cc = make_client_contact_headers(client["id"])
        facility = create_facility_for(client["id"], name="O Plant")
        w1 = request_holiday_window(client["id"], facility["id"],
                                    window_start="2026-09-20T00:00:00Z",
                                    window_end="2026-09-30T00:00:00Z")
        assert w1["status"] == "REQUESTED"

        adjacent = validate_success(api.create_holiday_window(
            {"facility_id": facility["id"], "holiday_code": "PASSOVER",
             "window_start": "2026-09-30T00:00:00Z",
             "window_end": "2026-10-10T00:00:00Z"}, cc), 201)
        assert adjacent["status"] == "REQUESTED", (
            "start == previous end is an empty half-open intersection")

        resp = api.create_holiday_window(
            {"facility_id": facility["id"], "holiday_code": "ROSH_HASHANAH",
             "window_start": "2026-09-29T00:00:00Z",
             "window_end": "2026-10-05T00:00:00Z"}, cc)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)

    def test_holiday_window_leading_adjacency_allowed(self, api):
        """PRD section 3.9: "touching endpoints, where one window's end equals
        the other's start, do not intersect and are allowed."

        Design: Difficulty/resource_temporal_overlap/holiday_window_half_open_adjacency_allowed_overlap_rejected
        """
        client = create_prospect_client(legal_name="Overlap Co 2")
        cc = make_client_contact_headers(client["id"])
        facility = create_facility_for(client["id"], name="O2 Plant")
        w1 = request_holiday_window(client["id"], facility["id"],
                                    window_start="2026-09-20T00:00:00Z",
                                    window_end="2026-09-30T00:00:00Z")
        assert w1["status"] == "REQUESTED"

        leading = validate_success(api.create_holiday_window(
            {"facility_id": facility["id"], "holiday_code": "PASSOVER",
             "window_start": "2026-09-10T00:00:00Z",
             "window_end": "2026-09-20T00:00:00Z"}, cc), 201)
        assert leading["status"] == "REQUESTED", (
            "end == next window's start is also a touching, empty intersection")

        resp = api.create_holiday_window(
            {"facility_id": facility["id"], "holiday_code": "ROSH_HASHANAH",
             "window_start": "2026-09-19T00:00:00Z",
             "window_end": "2026-09-25T00:00:00Z"}, cc)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


class TestWindowConfirmGates:
    def test_holiday_window_confirm_gated_on_covering_certificate(
            self, api, reviewer_headers):
        """PRD section 3.9: "Confirmation requires the hosting facility
        `APPROVED` (`ERR_FACILITY_NOT_APPROVED`); a covering certificate — some
        `ACTIVE` certificate whose `facility_ids` contains this facility and
        whose scheme covers the holiday code (`ERR_NO_COVERING_CERTIFICATE`)".

        Design: Difficulty/cross_entity_state_dependency/holiday_window_confirm_gated_on_covering_certificate
        """
        ctx = setup_certified_client(legal_name="Win Co")
        cid = ctx["client"]["id"]
        window = request_holiday_window(cid, ctx["facility"]["id"])
        # Remove coverage: suspend the only ACTIVE certificate.
        validate_success(api.suspend_certificate(ctx["certificate"]["id"],
                                                 make_officer_headers("co-1")))
        resp = api.confirm_holiday_window(window["id"], "sup-9",
                                          reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_NO_COVERING_CERTIFICATE)

        validate_success(api.reinstate_certificate(ctx["certificate"]["id"],
                                                   make_officer_headers("co-1")))
        confirmed = validate_success(api.confirm_holiday_window(
            window["id"], "sup-9", reviewer_headers))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["assigned_supervisor_id"] == "sup-9"

    def test_holiday_window_confirm_scheme_coverage_direction(self, api,
                                                              reviewer_headers):
        """PRD section 3.9: "the first two require scheme coverage by a `KOSHER`
        or `DUAL` certificate, the latter two by `HALAL` or `DUAL`"
        (PASSOVER/ROSH_HASHANAH vs RAMADAN/EID_AL_FITR).

        Design: Difficulty/cross_entity_state_dependency/holiday_window_confirm_gated_on_covering_certificate
        """
        # A HALAL-scheme client holds a HALAL certificate: it covers RAMADAN
        # but not PASSOVER.
        ctx = setup_certified_client(legal_name="Win Co 2",
                                     scheme="HALAL")
        cid = ctx["client"]["id"]
        passover = request_holiday_window(cid, ctx["facility"]["id"],
                                          holiday_code="PASSOVER")
        resp = api.confirm_holiday_window(passover["id"], "sup-9",
                                          reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_NO_COVERING_CERTIFICATE)

        ramadan = request_holiday_window(cid, ctx["facility"]["id"],
                                         holiday_code="RAMADAN",
                                         window_start="2027-03-01T00:00:00Z",
                                         window_end="2027-03-10T00:00:00Z")
        confirmed = validate_success(api.confirm_holiday_window(
            ramadan["id"], "sup-9", reviewer_headers))
        assert confirmed["status"] == "CONFIRMED"

    def test_window_confirm_state_beats_supervisor_temporal_conflict(
            self, api, reviewer_headers):
        """PRD section 2.8: "Only then are entity-state gates evaluated (the
        family of `ERR_*_INVALID_STATE` errors), then business-safety compliance
        gates (documentation, open findings, equipment, segregation, risk), then
        cross-entity referential integrity, then temporal-window rules".

        Design: Difficulty/priority_pair_validation_conflict/window_confirm_state_beats_supervisor_temporal_conflict
        """
        ctx = setup_certified_client(legal_name="Prio3 Co")
        cid = ctx["client"]["id"]
        fid = ctx["facility"]["id"]
        w1 = request_holiday_window(cid, fid,
                                    window_start="2026-09-20T00:00:00Z",
                                    window_end="2026-09-30T00:00:00Z")
        confirm_window(w1["id"], "sup-9")
        w2 = request_holiday_window(cid, fid,
                                    window_start="2026-09-30T12:00:00Z",
                                    window_end="2026-10-05T00:00:00Z")
        cc = make_client_contact_headers(cid)
        cancelled = validate_success(api.cancel_holiday_window(w2["id"], cc))
        assert cancelled["status"] == "CANCELLED"

        # sup-9's w1 buffer reaches 2026-10-01T00:00Z > w2 start: the temporal
        # conflict is genuinely armed, but the state gate answers first.
        resp = api.confirm_holiday_window(w2["id"], "sup-9", reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID_STATE)
        reread = validate_success(api.get_holiday_window(w2["id"],
                                                         reviewer_headers))
        assert reread["status"] == "CANCELLED"

    def test_window_confirm_temporal_conflict_when_state_is_legal(
            self, api, reviewer_headers):
        """PRD section 3.9: "the assignment is rejected with
        `ERR_SUPERVISOR_WINDOW_CONFLICT` when this window, expanded by 24 hours
        on both sides, would intersect any other `CONFIRMED` window of the same
        supervisor at any facility". PRD section 3.9: "Either the owning client
        or a reviewer may cancel a window in `REQUESTED` or `CONFIRMED`".

        Design: Difficulty/priority_pair_validation_conflict/window_confirm_state_beats_supervisor_temporal_conflict
        """
        ctx = setup_certified_client(legal_name="Prio3 Co B")
        cid = ctx["client"]["id"]
        fid = ctx["facility"]["id"]
        w1 = request_holiday_window(cid, fid,
                                    window_start="2026-09-20T00:00:00Z",
                                    window_end="2026-09-30T00:00:00Z")
        confirm_window(w1["id"], "sup-9")
        w2 = request_holiday_window(cid, fid,
                                    window_start="2026-09-30T12:00:00Z",
                                    window_end="2026-10-05T00:00:00Z")
        resp = api.confirm_holiday_window(w2["id"], "sup-9", reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_SUPERVISOR_WINDOW_CONFLICT)

        # Removing the conflicting CONFIRMED window clears the temporal gate.
        validate_success(api.cancel_holiday_window(
            w1["id"], make_client_contact_headers(cid)))
        confirmed = validate_success(api.confirm_holiday_window(
            w2["id"], "sup-9", reviewer_headers))
        assert confirmed["status"] == "CONFIRMED"

    def test_supervisor_window_conflict_pure_temporal(self, api,
                                                      reviewer_headers):
        """PRD section 3.9: "Both inequalities are strict, so a window starting
        exactly at another's end plus 24 hours is allowed." PRD section 3.9:
        "the assignment is rejected with `ERR_SUPERVISOR_WINDOW_CONFLICT` when
        this window, expanded by 24 hours on both sides, would intersect any
        other `CONFIRMED` window of the same supervisor at any facility".

        Design: Corner/validations/supervisor_window_conflict_pure_temporal
        """
        ctx = setup_certified_client(legal_name="SCo Co")
        cid = ctx["client"]["id"]
        fid = ctx["facility"]["id"]
        w1 = request_holiday_window(cid, fid,
                                    window_start="2026-09-20T00:00:00Z",
                                    window_end="2026-09-30T00:00:00Z")
        confirm_window(w1["id"], "sup-9")
        # w1 end + 24h = 2026-10-01T00:00Z > w2 start 2026-09-30T12:00Z.
        w2 = request_holiday_window(cid, fid,
                                    window_start="2026-09-30T12:00:00Z",
                                    window_end="2026-10-05T00:00:00Z")
        resp = api.confirm_holiday_window(w2["id"], "sup-9", reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_SUPERVISOR_WINDOW_CONFLICT)

        confirmed = validate_success(api.confirm_holiday_window(
            w2["id"], "sup-10", reviewer_headers))
        assert confirmed["status"] == "CONFIRMED", (
            "the conflict is per-supervisor; sup-10 has no windows")


class TestWindowCompletionAndCancel:
    def test_window_complete_before_window_end_rejected(self, api):
        """PRD section 3.9: "The assigned supervisor — and only that supervisor
        — completes the window (`CONFIRMED` → `COMPLETED`), and not before
        `window_end`; earlier completion yields `ERR_VISIT_WINDOW_NOT_ACTIVE`".

        Design: Corner/state_machines/window_complete_before_window_end_rejected
        """
        ctx = setup_certified_client(legal_name="SM9 Co")
        window = request_holiday_window(ctx["client"]["id"],
                                        ctx["facility"]["id"])
        confirm_window(window["id"], "sup-9")

        set_clock("2026-09-29T23:59:59Z")
        resp = api.complete_holiday_window(window["id"],
                                           make_supervisor_headers("sup-9"))
        validate_error(resp, ApiErrorId.ERR_VISIT_WINDOW_NOT_ACTIVE)

        set_clock("2026-09-30T00:00:00Z")
        done = validate_success(api.complete_holiday_window(
            window["id"], make_supervisor_headers("sup-9")))
        assert done["status"] == "COMPLETED", "at exactly window_end it completes"

    def test_window_cancel_referenced_by_certificate_rejected(self, api):
        """PRD section 3.9: "Either the owning client or a reviewer may cancel a
        window in `REQUESTED` or `CONFIRMED`, moving it to `CANCELLED`, except
        while a certificate in `DRAFT`, `ACTIVE`, or `SUSPENDED` references it
        via `holiday_window_id`, which blocks cancellation with
        `ERR_WINDOW_REFERENCED_BY_CERTIFICATE`."

        Design: Corner/validations/window_cancel_referenced_by_certificate_rejected
        """
        ctx = setup_certified_client(legal_name="WR Co")
        cid = ctx["client"]["id"]
        window = request_holiday_window(cid, ctx["facility"]["id"])
        confirm_window(window["id"], "sup-9")
        # DRAFT seasonal certificate referencing the window (never issued).
        get_success_data(api.create_certificate(
            create_certificate_payload(
                cid, [ctx["facility"]["id"]],
                [p["id"] for p in ctx["products"]],
                term_type="SEASONAL", holiday_window_id=window["id"]),
            make_officer_headers("co-1")))

        resp = api.cancel_holiday_window(
            window["id"], make_client_contact_headers(cid))
        validate_error(resp, ApiErrorId.ERR_WINDOW_REFERENCED_BY_CERTIFICATE)
        reread = validate_success(api.get_holiday_window(
            window["id"], TEST_USERS["reviewer_headers"]))
        assert reread["status"] == "CONFIRMED", "window unchanged"

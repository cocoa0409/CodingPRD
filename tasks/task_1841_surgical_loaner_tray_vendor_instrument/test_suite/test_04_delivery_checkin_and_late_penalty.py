"""Delivery check-ins, count-sheet verification, and the late-delivery
penalty cascade (verify -> PenaltyAssessment -> request exposure rollup)."""
from test_helpers import (
    ApiErrorId,
    add_tray,
    approve_request,
    assert_check_in_event,
    assert_penalty_assessment,
    assert_same_instant,
    check_in,
    coordinator,
    create_credentialed_rep,
    create_request,
    create_vendor,
    deliver_and_verify,
    get_success_data,
    list_escalations_of_request,
    list_penalties_of_request,
    rep_headers,
    set_clock,
    setup_approved_request,
    submit_request,
    validate_error,
    validate_paginated,
    validate_success,
    verify,
)
from test_helpers.factories import (
    check_in_line,
    create_check_in_payload,
    line_disposition,
    verify_check_in_payload,
)


class TestCheckInRecord:
    def test_checkin_event_is_immutable(self, api):
        """PRD: "A `CaseDelayEvent` and a `CheckInEvent` are event records:
        each carries `id` and `created_at` only, and both `updated_at` and
        `version` are absent from them."
        PRD: "The system stamps the check-in with the rep's identity
        (`rep_id` from the caller's `X-User-ID`) and `delivered_at` from the
        clock, and the record begins `SUBMITTED`."

        Design: Corner/entities/checkin_event_is_immutable
        """
        world = setup_approved_request()
        rep = world["rep"]
        set_clock("2026-08-02T08:00:00Z")
        ci = validate_success(
            api.create_check_in(
                world["request"]["id"],
                create_check_in_payload(
                    [check_in_line(world["trays"][0]["id"], 50)]),
                rep_headers(rep)), 201)
        assert_check_in_event(ci)
        assert ci["status"] == "SUBMITTED"
        assert ci["rep_id"] == rep["id"]
        assert_same_instant(ci["delivered_at"], "2026-08-02T08:00:00Z",
                            "checkin.delivered_at")
        assert_same_instant(ci["created_at"], "2026-08-02T08:00:00Z",
                            "checkin.created_at")
        assert "version" not in ci and "updated_at" not in ci


class TestVerify:
    def test_checkin_verify_twice_rejected(self, api):
        """PRD: "The check-in must still be `SUBMITTED`, else
        `ERR_CHECKIN_INVALID_STATE` (409)."
        PRD: "Link one: if the computed `late_minutes` exceeds the vendor's
        `late_grace_minutes` — equivalently, whenever the time charge works
        out to more than zero — and no penalty assessment yet exists for the
        request, verification creates a `PenaltyAssessment` in `ACCRUING`."

        Design: Corner/state_machines/checkin_verify_twice_rejected
        """
        world = setup_approved_request()
        ci = deliver_and_verify(world, at="2026-08-02T10:15:00Z")
        assert ci["status"] == "VERIFIED"
        assert len(list_penalties_of_request(world["request"]["id"])) == 1

        resp = api.verify_check_in(
            ci["id"],
            verify_check_in_payload(
                [line_disposition(world["trays"][0]["id"], "ACCEPT")]),
            coordinator())
        validate_error(resp, ApiErrorId.ERR_CHECKIN_INVALID_STATE)
        assert len(list_penalties_of_request(world["request"]["id"])) == 1, \
            "a rejected re-verify must not duplicate the penalty"

    def test_checkin_partial_verify_mixed_dispositions(self, api):
        """PRD: "A `QUARANTINE` moves the tray from `DELIVERY_PENDING` to
        `QUARANTINED` and auto-creates an `OPEN` escalation of type
        `DOCUMENTATION`."
        PRD: "When every line was accepted the check-in ends `VERIFIED`; when
        any line — including all of them — was quarantined, it ends
        `PARTIALLY_VERIFIED`."

        Design: Corner/state_machines/checkin_partial_verify_mixed_dispositions
        """
        world = setup_approved_request(
            priority_class="STANDARD",
            case_start="2026-08-05T09:00:00Z",
            case_end="2026-08-05T12:00:00Z",
            tray_specs=[
                dict(tray_code="TK-1", declared_instrument_count=50,
                     replacement_value_cents=300000),
                dict(tray_code="TK-2", declared_instrument_count=20,
                     replacement_value_cents=80000),
            ])
        t1, t2 = world["trays"]
        ci = check_in(world)  # both trays, full counts, at default clock
        verified = validate_success(
            api.verify_check_in(
                ci["id"],
                verify_check_in_payload([
                    line_disposition(t1["id"], "ACCEPT"),
                    line_disposition(t2["id"], "QUARANTINE"),
                ]),
                coordinator()))
        assert verified["status"] == "PARTIALLY_VERIFIED"

        t1_after = validate_success(api.get_tray(t1["id"], coordinator()))
        assert t1_after["status"] == "CHECKED_IN"
        assert t1_after["delivered_instrument_count"] == 50
        t2_after = validate_success(api.get_tray(t2["id"], coordinator()))
        assert t2_after["status"] == "QUARANTINED"

        escalations = list_escalations_of_request(world["request"]["id"])
        assert len(escalations) == 1
        assert escalations[0]["type"] == "DOCUMENTATION"
        assert escalations[0]["status"] == "OPEN"

    def test_checkin_short_count_creates_incomplete_escalation(self, api):
        """PRD: "An `ACCEPT` requires a delivered count of at least one; the
        tray moves from `DELIVERY_PENDING` to `CHECKED_IN`, its
        `delivered_instrument_count` is set from the line, and when that count
        falls short of the tray's `declared_instrument_count` the system
        auto-creates an `OPEN` escalation of type `INCOMPLETE_COUNT`."

        Design: Corner/state_machines/checkin_short_count_creates_incomplete_escalation
        """
        world = setup_approved_request(
            priority_class="STANDARD",
            case_start="2026-08-05T09:00:00Z",
            case_end="2026-08-05T12:00:00Z")
        tray = world["trays"][0]
        ci = check_in(world,
                      lines=[check_in_line(tray["id"], 45)])
        verified = validate_success(
            api.verify_check_in(
                ci["id"],
                verify_check_in_payload(
                    [line_disposition(tray["id"], "ACCEPT")]),
                coordinator()))
        assert verified["status"] == "VERIFIED"

        tray_after = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_after["status"] == "CHECKED_IN"
        assert tray_after["delivered_instrument_count"] == 45, \
            "45 delivered against 50 declared"

        escalations = list_escalations_of_request(world["request"]["id"])
        assert len(escalations) == 1
        assert escalations[0]["type"] == "INCOMPLETE_COUNT"
        assert escalations[0]["status"] == "OPEN"


class TestCheckInGuards:
    def test_duplicate_tray_line_in_checkin_rejected(self, api):
        """PRD: "Every line's tray must belong to the path request — a
        foreign tray is rejected with `ERR_TRAY_NOT_IN_REQUEST` (422) — must
        still be `EXPECTED` or `MISSING` (any other state fails with
        `ERR_TRAY_INVALID_STATE` at 409, and a `MISSING` tray covered here is
        simply a backfill delivery), and may appear at most once across the
        lines (a repeated `tray_id` fails with `ERR_DUPLICATE_TRAY_LINE` at
        409)."

        Design: Corner/validations/duplicate_tray_line_in_checkin_rejected
        """
        world = setup_approved_request()
        tray = world["trays"][0]
        resp = api.create_check_in(
            world["request"]["id"],
            create_check_in_payload([
                check_in_line(tray["id"], 25),
                check_in_line(tray["id"], 25),
            ]),
            rep_headers(world["rep"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRAY_LINE)
        tray_after = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_after["status"] == "EXPECTED"
        _rows, meta = validate_paginated(
            api.list_check_ins(coordinator(),
                               params={"request_id": world["request"]["id"]}))
        assert meta["total_count"] == 0

    def test_tray_from_other_request_rejected(self, api):
        """PRD: "Every line's tray must belong to the path request — a
        foreign tray is rejected with `ERR_TRAY_NOT_IN_REQUEST` (422)"

        Design: Corner/validations/tray_from_other_request_rejected
        """
        world = setup_approved_request(
            priority_class="STANDARD", case_start="2026-08-10T09:00:00Z",
            case_end="2026-08-10T12:00:00Z",
            tray_specs=[dict(tray_code="T-1", declared_instrument_count=5,
                             replacement_value_cents=1000)])
        # A second, sibling request of the same vendor and case.
        rq2 = create_request(world["case"]["id"], world["vendor"]["id"],
                             "STANDARD")
        tray_b = add_tray(rq2["id"], tray_code="T-2",
                          declared_instrument_count=5,
                          replacement_value_cents=1000)
        submit_request(rq2["id"])
        approve_request(rq2["id"])

        resp = api.create_check_in(
            rq2["id"],
            create_check_in_payload(
                [check_in_line(world["trays"][0]["id"], 5)]),
            rep_headers(world["rep"]))
        validate_error(resp, ApiErrorId.ERR_TRAY_NOT_IN_REQUEST)
        for tray_id in (world["trays"][0]["id"], tray_b["id"]):
            assert validate_success(
                api.get_tray(tray_id, coordinator()))["status"] == "EXPECTED"
        _rows, meta = validate_paginated(
            api.list_check_ins(coordinator(), params={"request_id": rq2["id"]}))
        assert meta["total_count"] == 0

    def test_implant_tray_without_implant_log_rejected(self, api):
        """PRD: "When any line's tray carries `implant_flag`,
        `implant_log_provided` must be true, else the entire check-in is
        rejected with `ERR_IMPLANT_LOG_REQUIRED` (422)."

        Design: Corner/validations/implant_tray_without_implant_log_rejected
        """
        world = setup_approved_request(
            tray_specs=[dict(tray_code="TK-IMP", declared_instrument_count=12,
                             implant_flag=True,
                             replacement_value_cents=500000)])
        tray = world["trays"][0]
        resp = api.create_check_in(
            world["request"]["id"],
            create_check_in_payload(
                [check_in_line(tray["id"], 12)],
                implant_log_provided=False),
            rep_headers(world["rep"]))
        validate_error(resp, ApiErrorId.ERR_IMPLANT_LOG_REQUIRED)
        tray_after = validate_success(api.get_tray(tray["id"], coordinator()))
        assert tray_after["status"] == "EXPECTED"
        _rows, meta = validate_paginated(
            api.list_check_ins(coordinator(),
                               params={"request_id": world["request"]["id"]}))
        assert meta["total_count"] == 0

    def test_rep_of_other_vendor_checkin_rejected(self, api):
        """PRD: "The caller's credential must be `ACTIVE`
        (`ERR_REP_CREDENTIAL_NOT_ACTIVE`) and the caller must belong to the
        request's vendor (`ERR_REP_VENDOR_MISMATCH`)."
        PRD: "a rep acting for a vendor other than their own employer fails
        with `ERR_REP_VENDOR_MISMATCH` (403)."

        Design: Corner/validations/rep_of_other_vendor_checkin_rejected
        """
        world = setup_approved_request(
            priority_class="STANDARD", case_start="2026-08-10T09:00:00Z",
            case_end="2026-08-10T12:00:00Z",
            tray_specs=[dict(tray_code="T-1", declared_instrument_count=5,
                             replacement_value_cents=1000)])
        other_vendor = create_vendor(vendor_name="Beta", vendor_code="BETA")
        rep_b = create_credentialed_rep(other_vendor["id"],
                                        full_name="Bob Beta",
                                        rep_email="b@beta.com",
                                        credential_doc_ref="DOC-B")

        resp = api.create_check_in(
            world["request"]["id"],
            create_check_in_payload(
                [check_in_line(world["trays"][0]["id"], 5)]),
            rep_headers(rep_b))
        validate_error(resp, ApiErrorId.ERR_REP_VENDOR_MISMATCH)
        tray_after = validate_success(
            api.get_tray(world["trays"][0]["id"], coordinator()))
        assert tray_after["status"] == "EXPECTED"


class TestLateDeliveryBoundary:
    """Difficulty instance: delivery exactly at the deadline is not late."""

    def test_delivery_exactly_at_deadline_computes_zero_late(self, api):
        """PRD: "Verification stamps `verified_by_user_id` with the
        coordinator's `X-User-ID` — the segregation-of-duties anchor of §2.11
        — and computes `late_minutes` as the whole minutes from
        `required_delivery_by` to `delivered_at`, floored at zero."

        Design: Difficulty/boundary_precision_check/delivery_exactly_at_deadline_is_not_late
        """
        # URGENT request on the 2026-08-03 09:00 case: required_delivery_by
        # is 2026-08-02T09:00:00Z; the rep checks in at exactly that instant.
        world = setup_approved_request()
        ci = deliver_and_verify(world, at="2026-08-02T09:00:00Z")
        assert ci["status"] == "VERIFIED"
        assert ci["late_minutes"] == 0, \
            "delivery at exactly the deadline floors to zero late minutes"

    def test_delivery_exactly_at_deadline_creates_no_penalty(self, api):
        """PRD: "an on-time or within-grace delivery yields a zero charge and
        no penalty row at all."

        Design: Difficulty/boundary_precision_check/delivery_exactly_at_deadline_is_not_late
        """
        world = setup_approved_request()
        ci = deliver_and_verify(world, at="2026-08-02T09:00:00Z")
        assert ci["late_minutes"] == 0
        penalties, meta = validate_paginated(
            api.list_penalties(coordinator(),
                               params={"request_id": world["request"]["id"]}))
        assert meta["total_count"] == 0, \
            "zero billable minutes means no PenaltyAssessment row at all"
        request = validate_success(
            api.get_request(world["request"]["id"], coordinator()))
        assert request["penalty_exposure_cents"] == 0


class TestVerifyLateCascade:
    """Difficulty instance: verify -> ACCRUING penalty -> request exposure."""

    def test_verify_late_creates_accruing_penalty(self, api):
        """PRD: "Link one: if the computed `late_minutes` exceeds the vendor's
        `late_grace_minutes` — equivalently, whenever the time charge works
        out to more than zero — and no penalty assessment yet exists for the
        request, verification creates a `PenaltyAssessment` in `ACCRUING`."
        PRD: "The new penalty snapshots `late_minutes` from the check-in,
        links back through `check_in_id` and `request_id`, and computes
        `billable_minutes` as the late minutes minus the grace minutes,
        floored at zero, and `time_charge_cents` as the vendor's
        `late_rate_per_hour_cents` multiplied by the billable hours — billable
        minutes divided by sixty, rounded up to a whole hour — with the result
        capped at the vendor's `late_penalty_cap_cents`"

        Design: Difficulty/transitive_cascade/verify_late_cascade_checkin_to_penalty_to_request_rollup
        """
        # Deadline 2026-08-02T09:00; delivery at 10:15 is 75 minutes late.
        world = setup_approved_request()
        ci = deliver_and_verify(world, at="2026-08-02T10:15:00Z")
        assert ci["status"] == "VERIFIED"
        assert ci["late_minutes"] == 75

        penalties = list_penalties_of_request(world["request"]["id"])
        assert len(penalties) == 1, "exactly one penalty is created at verify"
        penalty = penalties[0]
        assert_penalty_assessment(penalty)
        assert penalty["status"] == "ACCRUING"
        assert penalty["late_minutes"] == 75
        assert penalty["billable_minutes"] == 60, "75 late minus 15 grace"
        # ceil(60/60) = 1 billable hour at 5000/hr, under the 20000 cap.
        assert penalty["time_charge_cents"] == 5000
        assert penalty["delay_surcharge_cents"] == 0
        assert penalty["assessed_cents"] == 5000

    def test_verify_late_cascade_request_exposure_and_vendor_rollup(self, api):
        """PRD: "Link two: the penalty's creation immediately recomputes the
        request's `penalty_exposure_cents`, the running sum of
        `time_charge_cents` plus `delay_surcharge_cents` over the request's
        penalties in `ACCRUING` or `ASSESSED`."
        PRD: "`outstanding_penalty_cents` is the sum of `outstanding_cents`
        over exactly that vendor's penalty assessments whose status is
        `ASSESSED`. Penalties still `ACCRUING`, already `SETTLED`, closed as
        `WAIVED_CLOSED`, or annulled as `VOID` contribute nothing."

        Design: Difficulty/transitive_cascade/verify_late_cascade_checkin_to_penalty_to_request_rollup
        """
        world = setup_approved_request()
        deliver_and_verify(world, at="2026-08-02T10:15:00Z")

        request = validate_success(
            api.get_request(world["request"]["id"], coordinator()))
        assert request["penalty_exposure_cents"] == 5000, \
            "exposure includes the ACCRUING penalty's time charge"

        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_penalty_cents"] == 0, \
            "ACCRUING penalties are excluded from the vendor rollup"


class TestGraceThreshold:
    def test_grace_threshold_boundary(self, api):
        """PRD: "Link one: if the computed `late_minutes` exceeds the vendor's
        `late_grace_minutes` — equivalently, whenever the time charge works
        out to more than zero — and no penalty assessment yet exists for the
        request, verification creates a `PenaltyAssessment` in `ACCRUING`."
        PRD: "Billable penalty time uses ceiling semantics: the number of
        billable hours in a penalty is the billable minutes divided by sixty,
        rounded up to the next whole hour, so that one billable minute already
        bills a full hour."

        Design: Corner/complexity_layers/grace_threshold_boundary
        """
        # Two URGENT requests on the same case share the 2026-08-02T09:00
        # deadline; deliveries land at 09:15 (== grace) and 09:16.
        world = setup_approved_request(
            tray_specs=[dict(tray_code="T-A", declared_instrument_count=5,
                             replacement_value_cents=1000)])
        rq_b = create_request(world["case"]["id"], world["vendor"]["id"],
                              "URGENT")
        tray_b = add_tray(rq_b["id"], tray_code="T-B",
                          declared_instrument_count=5,
                          replacement_value_cents=1000)
        submit_request(rq_b["id"])
        approve_request(rq_b["id"])

        ci_a = check_in(world, at="2026-08-02T09:15:00Z")
        ci_b = check_in({**world, "request": rq_b, "trays": [tray_b]},
                        at="2026-08-02T09:16:00Z")

        verified_a = verify(world, ci_a)
        assert verified_a["late_minutes"] == 15, "exactly the grace minutes"
        assert list_penalties_of_request(world["request"]["id"]) == [], \
            "late == grace bills zero hours: no penalty row"

        verified_b = verify(world, ci_b)
        assert verified_b["late_minutes"] == 16
        penalties_b = list_penalties_of_request(rq_b["id"])
        assert len(penalties_b) == 1
        assert penalties_b[0]["status"] == "ACCRUING"
        assert penalties_b[0]["billable_minutes"] == 1
        assert penalties_b[0]["time_charge_cents"] == 5000, \
            "one billable minute already bills a full hour"

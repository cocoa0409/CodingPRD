"""Acreage reporting: filing deadlines, late window, state gates, late-filed
payment factor (PRD §3.3, §3.8)."""
import pytest

from test_helpers import (
    ACREAGE_DEADLINE,
    LATE_FILE_CLOCK,
    PAST_LATE_WINDOW_CLOCK,
    SAFE_CLOCK,
    ApiErrorId,
    add_field,
    add_tract,
    assert_acreage_report,
    create_acreage_report_line_payload,
    create_farm_with_member,
    make_producer_headers,
    set_clock,
    setup_payment_computed_enrollment,
    validate_error,
    validate_success,
)


@pytest.fixture
def specialist(county_specialist_headers):
    return county_specialist_headers


@pytest.fixture
def ced(county_executive_director_headers):
    return county_executive_director_headers


def _draft_report(api, specialist, planted=100.00, with_line=True):
    """Farm + member producer + tract/field + DRAFT acreage report."""
    farm, producer, _ = create_farm_with_member()
    producer_headers = make_producer_headers(producer["id"])
    tract = add_tract(farm["id"], base_acres=100.00, cropland_acres=100.00)
    field = add_field(tract["id"], acres=100.00)
    resp = api.create_acreage_report(
        farm["id"], {"program_year": 2026}, producer_headers
    )
    report = validate_success(resp, 201)
    if with_line:
        line_resp = api.add_acreage_report_line(
            report["id"],
            create_acreage_report_line_payload(
                field_id=field["id"], planted_acres=planted
            ),
            producer_headers,
        )
        validate_success(line_resp, 201)
    return farm, producer, producer_headers, field, report


class TestAcreageReportStateGate:
    def test_certify_draft_acreage_report_returns_invalid_state(self, api, specialist):
        """PRD §3.3: "A county specialist certifies a `FILED` or `LATE_FILED`
        report, moving it to `CERTIFIED`" and "attempting a transition that the
        report's current state does not define is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/certify_draft_acreage_report_returns_invalid_state
        """
        set_clock(SAFE_CLOCK)
        _farm, _producer, _ph, _field, report = _draft_report(
            api, specialist, with_line=False
        )
        resp = api.certify_acreage_report(report["id"], specialist)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestAcreageDeadlineWindow:
    def test_file_exactly_at_deadline_is_filed(self, api, specialist):
        """PRD §3.3: "For the 2026 crop year the reporting deadline is
        `2026-07-15T23:59:59Z`. A producer who holds an `ACTIVE` membership on
        the report's farm may file while the logical clock is at or before the
        deadline, provided every line's field belongs to the report's farm and
        `reported_acres` is greater than zero; filing stamps `filed_at` and moves
        the report from `DRAFT` to `FILED`."

        Design: Difficulty/resource_temporal_overlap/acreage_report_deadline_half_open_window
        """
        _farm, _producer, producer_headers, _field, report = _draft_report(
            api, specialist
        )
        set_clock(ACREAGE_DEADLINE)
        resp = api.file_acreage_report(report["id"], producer_headers)
        filed = validate_success(resp, 200)
        assert_acreage_report(filed)
        assert filed["report_status"] == "FILED", (
            f"filing at exactly the deadline must be on time, got "
            f"{filed['report_status']}"
        )
        assert filed["filed_at"] is not None, "filing stamps filed_at"

    def test_file_beyond_late_window_rejected(self, api, specialist):
        """PRD §3.3: "Once the clock is beyond the deadline plus the 30-day late
        window, filing is rejected outright with `ERR_ACREAGE_DEADLINE_PASSED`."

        Design: Difficulty/resource_temporal_overlap/acreage_report_deadline_half_open_window
        """
        _farm, _producer, producer_headers, _field, report = _draft_report(
            api, specialist
        )
        set_clock(PAST_LATE_WINDOW_CLOCK)
        resp = api.file_acreage_report(report["id"], producer_headers)
        validate_error(resp, ApiErrorId.ERR_ACREAGE_DEADLINE_PASSED.value)


class TestStateBeforeTemporalOnCertify:
    def test_certify_rejected_report_after_deadline_returns_invalid_state(
        self, api, specialist
    ):
        """PRD §2.8: "When multiple validations could fire on the same request,
        they are evaluated in a fixed order."
        PRD §2.8: "then the state-machine check that the target resource is in a
        state from which the requested transition is defined, then the OCC
        stale-farm-version check where applicable, then temporal gates (acreage
        reporting deadline, election window)"
        PRD §3.3: "A specialist may also reject a filed report outright by
        supplying a `reason`, moving it to `REJECTED` (a terminal state)." and
        "attempting a transition that the report's current state does not define
        is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_late_certify
        """
        _farm, _producer, producer_headers, _field, report = _draft_report(
            api, specialist
        )
        validate_success(api.file_acreage_report(report["id"], producer_headers), 200)
        validate_success(
            api.reject_acreage_report(report["id"], {"reason": "Incomplete"}, specialist),
            200,
        )
        set_clock("2026-09-01T00:00:00Z")  # past every temporal gate
        resp = api.certify_acreage_report(report["id"], specialist)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_certify_already_certified_report_after_deadline_returns_invalid_state(
        self, api, specialist
    ):
        """PRD §2.8: "then the state-machine check that the target resource is in
        a state from which the requested transition is defined, then the OCC
        stale-farm-version check where applicable, then temporal gates (acreage
        reporting deadline, election window)"
        PRD §3.3: "A county specialist certifies a `FILED` or `LATE_FILED`
        report, moving it to `CERTIFIED`" — a `CERTIFIED` report defines no
        certify transition, so a second certify is a state violation regardless
        of the clock.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_late_certify
        """
        _farm, _producer, producer_headers, _field, report = _draft_report(
            api, specialist
        )
        validate_success(api.file_acreage_report(report["id"], producer_headers), 200)
        certified = validate_success(
            api.certify_acreage_report(report["id"], specialist), 200
        )
        assert certified["report_status"] == "CERTIFIED"
        set_clock("2026-09-01T00:00:00Z")
        resp = api.certify_acreage_report(report["id"], specialist)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestLateFiledPaymentReduction:
    def test_late_filed_report_applies_90_percent_factor(self, api, specialist):
        """PRD §3.8: "If the farm's acreage report for the year is `LATE_FILED`
        rather than having been filed on time and certified, the base payment is
        then reduced by a factor of 0.90 — a ten percent reduction for late
        filing. This reduction applies before payment limitation."
        PRD §3.3: "When the clock has passed the deadline but remains within 30
        days after it, filing instead moves the report to `LATE_FILED`, stamps
        `filed_at`, and accepts a late fee — a `LATE_FILED` report carries a
        downstream payment reduction of ten percent."

        PLC derivation: rate 0.60 x APH 180.0 x base 100 x 0.85 = 9180.00;
        late factor -> 8262.00; sequestration round(8262 x 0.057, 2) = 470.93;
        net 7791.07 -> 779107 cents.

        Design: Corner/calculations/late_filed_report_applies_90_percent_factor
        """
        ctx = setup_payment_computed_enrollment(
            file_clock=LATE_FILE_CLOCK,
            compute_inputs={"national_my_price": 3.50},
        )
        # Filing inside the late window moves the report to LATE_FILED
        # (PRD §3.3); the pipeline then certifies it (LATE_FILED ->
        # CERTIFIED, also PRD §3.3), so the status is probed on the
        # filing-time snapshot. The ten-percent reduction carries
        # downstream into the computed payment.
        assert ctx["acreage_report_at_filing"]["report_status"] == "LATE_FILED", (
            f"report filed at {LATE_FILE_CLOCK} must be LATE_FILED, got "
            f"{ctx['acreage_report_at_filing']['report_status']}"
        )
        enrollment = ctx["enrollment"]
        assert enrollment["enrollment_status"] == "PAYMENT_COMPUTED"
        assert enrollment["computed_payment_cents"] == 779107, (
            f"late-filed net payment must be 779107 cents, got "
            f"{enrollment['computed_payment_cents']}"
        )
        assert enrollment["sequestration_cents"] == 47093

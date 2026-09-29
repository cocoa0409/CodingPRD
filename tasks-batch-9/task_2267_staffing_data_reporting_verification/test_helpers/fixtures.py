"""Composite state builders and pytest fixtures.

Every builder here reaches the state it advertises purely through the public
endpoints, so a test that asks for an accepted quarter gets one that walked the
real reporting lifecycle: register the facility, open the period, define the job
categories, register the workers, open the draft quarter, capture hours against
a payroll document, report and reconcile the census, have the auditor verify the
support, run the validation pass, attest, and accept.

The database is empty at the start of every test, so nothing is shared and no
builder assumes any prior row exists.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient, api_client
from .constants import (
    ACCEPTING_AUDITOR_USER_ID,
    CASE_AUDITOR_USER_ID,
    PUBLISHER_USER_ID,
    REVIEWER_USER_ID,
    VERIFYING_AUDITOR_USER_ID,
)
from .factories import (
    allocation_line,
    create_census_day_payload,
    create_discrepancy_case_payload,
    create_facility_payload,
    create_hour_entry_payload,
    create_job_category_payload,
    create_payroll_record_payload,
    create_rating_appeal_payload,
    create_reporting_period_payload,
    create_staffing_measure_payload,
    create_submission_payload,
    create_vendor_payload,
    create_vendor_submission_payload,
    create_worker_payload,
    replace_allocations_payload,
    vendor_batch_line,
    verify_hour_entry_payload,
)
from .test_users import (
    make_appeals_reviewer_headers,
    make_cms_publisher_headers,
    make_facility_administrator_headers,
    make_platform_admin_headers,
    make_staffing_coordinator_headers,
    make_state_auditor_headers,
    make_vendor_representative_headers,
)
from .types import (
    AppealGrounds,
    AuthorizedRole,
    CaseTriggerReason,
    DirectCareClass,
    NurseGroup,
    SupportType,
    VerificationOutcome,
    WorkerType,
)


def _data(response) -> Dict[str, Any]:
    """Unwrap a setup response, failing loudly with the server's own error."""
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 1 — the reference universe every scenario starts from
# ---------------------------------------------------------------------------


class ReportingUniverse:
    """One facility, one open period, the three job categories the direct-care
    arithmetic needs, and the three workers who act in the reporting cycle."""

    def __init__(self, client: ApiClient):
        self.client = client
        self.admin_headers = make_platform_admin_headers()

        self.facility = _data(
            client.create_facility(create_facility_payload(), self.admin_headers)
        )
        self.period = _data(
            client.create_reporting_period(
                create_reporting_period_payload(), self.admin_headers
            )
        )

        # RN credits every allocated minute; RN_ADMIN is a split role crediting
        # 0.60; ADMIN credits nothing and is not weekend countable.
        self.jc_rn = _data(
            client.create_job_category(
                create_job_category_payload(
                    code="RN",
                    cms_job_code=5,
                    direct_care_class=DirectCareClass.DIRECT_CARE.value,
                    nurse_group=NurseGroup.RN.value,
                    direct_care_credit_pct=1.00,
                    weekend_countable=True,
                ),
                self.admin_headers,
            )
        )
        self.jc_split = _data(
            client.create_job_category(
                create_job_category_payload(
                    code="RN_ADMIN",
                    cms_job_code=3,
                    direct_care_class=DirectCareClass.DIRECT_CARE_SPLIT.value,
                    nurse_group=NurseGroup.RN.value,
                    direct_care_credit_pct=0.60,
                    weekend_countable=True,
                ),
                self.admin_headers,
            )
        )
        self.jc_admin = _data(
            client.create_job_category(
                create_job_category_payload(
                    code="ADMIN",
                    cms_job_code=1,
                    direct_care_class=DirectCareClass.ADMINISTRATIVE.value,
                    nurse_group=NurseGroup.NONE.value,
                    direct_care_credit_pct=0.00,
                    weekend_countable=False,
                ),
                self.admin_headers,
            )
        )

        self.w_coord = _data(
            client.create_worker(
                create_worker_payload(
                    self.facility["id"],
                    self.jc_admin["id"],
                    full_name="Dana Coordinator",
                    authorized_roles=[AuthorizedRole.STAFFING_COORDINATOR.value],
                ),
                self.admin_headers,
            )
        )
        self.w_admin = _data(
            client.create_worker(
                create_worker_payload(
                    self.facility["id"],
                    self.jc_admin["id"],
                    full_name="Avery Administrator",
                    authorized_roles=[AuthorizedRole.FACILITY_ADMINISTRATOR.value],
                ),
                self.admin_headers,
            )
        )
        self.w_rn = _data(
            client.create_worker(
                create_worker_payload(
                    self.facility["id"],
                    self.jc_rn["id"],
                    full_name="Riley Nurse",
                    authorized_roles=[],
                ),
                self.admin_headers,
            )
        )

    # -- ids ---------------------------------------------------------------

    @property
    def facility_id(self) -> str:
        return self.facility["id"]

    @property
    def period_id(self) -> str:
        return self.period["id"]

    # -- identity-threaded headers ----------------------------------------

    @property
    def coord_headers(self) -> Dict[str, str]:
        """The staffing coordinator acts as the `Worker` authorized for it."""
        return make_staffing_coordinator_headers(self.w_coord["id"])

    @property
    def fac_admin_headers(self) -> Dict[str, str]:
        """The facility administrator acts as the `Worker` authorized for it."""
        return make_facility_administrator_headers(self.w_admin["id"])

    def set_clock(self, to_iso8601: str) -> Dict[str, Any]:
        return _data(self.client.set_clock(to_iso8601, self.admin_headers))

    def register_facility(self, **overrides) -> Dict[str, Any]:
        return _data(
            self.client.create_facility(
                create_facility_payload(**overrides), self.admin_headers
            )
        )

    def open_period(self, **overrides) -> Dict[str, Any]:
        return _data(
            self.client.create_reporting_period(
                create_reporting_period_payload(**overrides), self.admin_headers
            )
        )

    def register_worker(
        self, facility_id: str, job_category_id: str, **overrides
    ) -> Dict[str, Any]:
        return _data(
            self.client.create_worker(
                create_worker_payload(facility_id, job_category_id, **overrides),
                self.admin_headers,
            )
        )


# ---------------------------------------------------------------------------
# Tier 2 — a quarter under construction
# ---------------------------------------------------------------------------


class SubmissionScenario:
    """A draft quarter plus every act that moves it, with the optimistic
    concurrency token read fresh from the server before each guarded write."""

    def __init__(
        self,
        universe: ReportingUniverse,
        facility_id: Optional[str] = None,
        reporting_period_id: Optional[str] = None,
    ):
        self.universe = universe
        self.client = universe.client
        self.facility_id = facility_id or universe.facility_id
        self.reporting_period_id = reporting_period_id or universe.period_id
        self.submission = _data(
            self.client.create_submission(
                create_submission_payload(self.facility_id, self.reporting_period_id),
                universe.coord_headers,
            )
        )
        self.entries: List[Dict[str, Any]] = []
        self.census_days: List[Dict[str, Any]] = []
        self.payroll_records: List[Dict[str, Any]] = []

    # -- state -------------------------------------------------------------

    @property
    def id(self) -> str:
        return self.submission["id"]

    @property
    def version(self) -> int:
        """Read the live version so the next guarded write carries a fresh
        token."""
        return self.refresh()["version"]

    def refresh(self) -> Dict[str, Any]:
        self.submission = _data(
            self.client.get_submission(self.id, self.universe.coord_headers)
        )
        return self.submission

    def findings(self) -> List[Dict[str, Any]]:
        return _data(
            self.client.list_submission_findings(
                self.id, self.universe.coord_headers, {"limit": 100}
            )
        )

    # -- building blocks ---------------------------------------------------

    def file_payroll(
        self,
        worker_id: Optional[str] = None,
        pay_period_start: str = "2026-04-01",
        pay_period_end: str = "2026-04-01",
        paid_hours: float = 8.00,
        document_ref: str = "TC-B0401",
        support_type: str = SupportType.TIMECARD.value,
    ) -> Dict[str, Any]:
        record = _data(
            self.client.create_payroll_record(
                create_payroll_record_payload(
                    self.facility_id,
                    worker_id or self.universe.w_rn["id"],
                    pay_period_start=pay_period_start,
                    pay_period_end=pay_period_end,
                    paid_hours=paid_hours,
                    support_type=support_type,
                    document_ref=document_ref,
                ),
                self.universe.coord_headers,
            )
        )
        self.payroll_records.append(record)
        return record

    def capture_hours(
        self,
        work_date: str = "2026-04-01",
        shift_start: str = "07:00",
        shift_end: str = "15:00",
        worker_id: Optional[str] = None,
        job_category_id: Optional[str] = None,
        allocations: Optional[List[Dict[str, Any]]] = None,
        payroll_record_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        entry = _data(
            self.client.create_hour_entry(
                create_hour_entry_payload(
                    self.id,
                    worker_id or self.universe.w_rn["id"],
                    job_category_id or self.universe.jc_rn["id"],
                    self.version,
                    work_date=work_date,
                    shift_start=shift_start,
                    shift_end=shift_end,
                    allocations=allocations,
                    payroll_record_id=payroll_record_id,
                ),
                self.universe.coord_headers,
            )
        )
        self.entries.append(entry)
        return entry

    def capture_supported_hours(
        self,
        work_date: str = "2026-04-01",
        shift_start: str = "07:00",
        shift_end: str = "15:00",
        paid_hours: float = 8.00,
        document_ref: Optional[str] = None,
        worker_id: Optional[str] = None,
        job_category_id: Optional[str] = None,
        allocations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """File a payroll document covering the shift's date and capture the
        shift against it, so the hour is eligible for verification."""
        record = self.file_payroll(
            worker_id=worker_id,
            pay_period_start=work_date,
            pay_period_end=work_date,
            paid_hours=paid_hours,
            document_ref=document_ref or f"TC-{work_date.replace('-', '')}",
        )
        return self.capture_hours(
            work_date=work_date,
            shift_start=shift_start,
            shift_end=shift_end,
            worker_id=worker_id,
            job_category_id=job_category_id,
            allocations=allocations,
            payroll_record_id=record["id"],
        )

    def replace_allocations(
        self, hour_entry_id: str, allocations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return _data(
            self.client.replace_hour_entry_allocations(
                hour_entry_id,
                replace_allocations_payload(allocations, self.version),
                self.universe.coord_headers,
            )
        )

    def void_hours(self, hour_entry_id: str) -> Dict[str, Any]:
        return _data(
            self.client.void_hour_entry(hour_entry_id, self.universe.coord_headers)
        )

    def verify_hours(
        self,
        hour_entry_id: str,
        outcome: str = VerificationOutcome.SUPPORTED.value,
        user_id: str = VERIFYING_AUDITOR_USER_ID,
    ) -> Dict[str, Any]:
        return _data(
            self.client.verify_hour_entry(
                hour_entry_id,
                verify_hour_entry_payload(outcome),
                make_state_auditor_headers(user_id),
            )
        )

    def report_census(
        self,
        census_date: str = "2026-04-01",
        resident_count: int = 5,
        mds_resident_count: Optional[int] = 5,
    ) -> Dict[str, Any]:
        day = _data(
            self.client.create_census_day(
                create_census_day_payload(
                    self.id,
                    census_date=census_date,
                    resident_count=resident_count,
                    mds_resident_count=mds_resident_count,
                ),
                self.universe.coord_headers,
            )
        )
        self.census_days.append(day)
        return day

    def reconcile_census(self, census_day_id: str) -> Dict[str, Any]:
        return _data(
            self.client.reconcile_census_day(
                census_day_id, self.universe.coord_headers
            )
        )

    def report_reconciled_census(
        self,
        census_date: str = "2026-04-01",
        resident_count: int = 5,
        mds_resident_count: int = 5,
    ) -> Dict[str, Any]:
        day = self.report_census(census_date, resident_count, mds_resident_count)
        return self.reconcile_census(day["id"])

    # -- lifecycle transitions --------------------------------------------

    def validate(self) -> Dict[str, Any]:
        self.submission = _data(
            self.client.validate_submission(self.id, self.universe.coord_headers)
        )
        return self.submission

    def submit(self) -> Dict[str, Any]:
        self.submission = _data(
            self.client.submit_submission(self.id, self.universe.fac_admin_headers)
        )
        return self.submission

    def accept(self, user_id: str = ACCEPTING_AUDITOR_USER_ID) -> Dict[str, Any]:
        self.submission = _data(
            self.client.accept_submission(
                self.id, make_state_auditor_headers(user_id)
            )
        )
        return self.submission

    def reject(
        self,
        rejection_reason: str = "The census set is incomplete for the quarter.",
        user_id: str = ACCEPTING_AUDITOR_USER_ID,
    ) -> Dict[str, Any]:
        self.submission = _data(
            self.client.reject_submission(
                self.id,
                {"rejection_reason": rejection_reason},
                make_state_auditor_headers(user_id),
            )
        )
        return self.submission

    def reopen(self) -> Dict[str, Any]:
        self.submission = _data(
            self.client.reopen_submission(self.id, self.universe.coord_headers)
        )
        return self.submission

    def waive(
        self,
        finding_id: str,
        waiver_note: str = "Reviewed against the source timecards and accepted.",
        user_id: str = CASE_AUDITOR_USER_ID,
    ) -> Dict[str, Any]:
        return _data(
            self.client.waive_finding(
                self.id,
                finding_id,
                {"waiver_note": waiver_note},
                make_state_auditor_headers(user_id),
            )
        )


# ---------------------------------------------------------------------------
# Tier 3 — full-lifecycle shortcuts
# ---------------------------------------------------------------------------


def build_universe(client: ApiClient = api_client) -> ReportingUniverse:
    return ReportingUniverse(client)


def build_draft_submission(
    client: ApiClient = api_client,
) -> SubmissionScenario:
    """A DRAFT quarter with zeroed rollups and nothing captured against it."""
    return SubmissionScenario(build_universe(client))


def build_supported_quarter(client: ApiClient = api_client) -> SubmissionScenario:
    """A DRAFT quarter holding one 8.00-hour RN shift that a payroll document
    supports and an auditor has verified as SUPPORTED, plus one reconciled
    census day."""
    scenario = build_draft_submission(client)
    entry = scenario.capture_supported_hours(document_ref="TC-B0401")
    scenario.report_reconciled_census("2026-04-01", 5, 5)
    scenario.verify_hours(entry["id"])
    return scenario


def build_validated_quarter(client: ApiClient = api_client) -> SubmissionScenario:
    """The supported quarter after a clean validation pass."""
    scenario = build_supported_quarter(client)
    scenario.validate()
    return scenario


def build_submitted_quarter(client: ApiClient = api_client) -> SubmissionScenario:
    """The validated quarter after the administrator's attestation."""
    scenario = build_validated_quarter(client)
    scenario.submit()
    return scenario


def build_accepted_quarter(client: ApiClient = api_client) -> SubmissionScenario:
    """The attested quarter accepted by an auditor other than the one who
    verified its hours, so segregation of duties is satisfied and the sampled
    audit-readiness score clears the risk floor."""
    scenario = build_submitted_quarter(client)
    scenario.accept()
    return scenario


# ---------------------------------------------------------------------------
# Tier 4 — measure, investigation, and appeal chains
# ---------------------------------------------------------------------------


class MeasureScenario:
    """An accepted quarter plus the computed public measure."""

    def __init__(self, scenario: SubmissionScenario):
        self.scenario = scenario
        self.universe = scenario.universe
        self.client = scenario.client
        self.publisher_headers = make_cms_publisher_headers(PUBLISHER_USER_ID)
        self.measure = _data(
            self.client.create_staffing_measure(
                create_staffing_measure_payload(scenario.id), self.publisher_headers
            )
        )

    @property
    def id(self) -> str:
        return self.measure["id"]

    @property
    def version(self) -> int:
        return self.refresh()["version"]

    def refresh(self) -> Dict[str, Any]:
        self.measure = _data(
            self.client.get_staffing_measure(self.id, self.publisher_headers)
        )
        return self.measure

    def publish(self) -> Dict[str, Any]:
        self.measure = _data(
            self.client.publish_staffing_measure(self.id, self.publisher_headers)
        )
        return self.measure


def build_provisional_measure(client: ApiClient = api_client) -> MeasureScenario:
    """A PROVISIONAL, NOT_AUDITED measure over an accepted quarter."""
    return MeasureScenario(build_accepted_quarter(client))


def build_published_measure(client: ApiClient = api_client) -> MeasureScenario:
    """A PUBLISHED measure whose appeal window is open."""
    measure = build_provisional_measure(client)
    measure.publish()
    return measure


class CaseScenario:
    """A discrepancy investigation and the acts that move it."""

    def __init__(
        self,
        scenario: SubmissionScenario,
        trigger_reason: str = CaseTriggerReason.CENSUS_MISMATCH.value,
        detail: str = "Reported census conflicts with the state register.",
        staffing_measure_id: Optional[str] = None,
        user_id: str = CASE_AUDITOR_USER_ID,
    ):
        self.scenario = scenario
        self.universe = scenario.universe
        self.client = scenario.client
        self.auditor_headers = make_state_auditor_headers(user_id)
        self.case = _data(
            self.client.create_discrepancy_case(
                create_discrepancy_case_payload(
                    scenario.facility_id,
                    scenario.id,
                    trigger_reason=trigger_reason,
                    detail=detail,
                    staffing_measure_id=staffing_measure_id,
                ),
                self.auditor_headers,
            )
        )

    @property
    def id(self) -> str:
        return self.case["id"]

    def refresh(self) -> Dict[str, Any]:
        self.case = _data(
            self.client.get_discrepancy_case(self.id, self.auditor_headers)
        )
        return self.case

    def request_info(
        self, request_note: str = "Provide the source timecards for the quarter."
    ) -> Dict[str, Any]:
        self.case = _data(
            self.client.request_case_info(
                self.id, {"request_note": request_note}, self.auditor_headers
            )
        )
        return self.case

    def respond(
        self, response_note: str = "Timecards for every reported shift are attached."
    ) -> Dict[str, Any]:
        self.case = _data(
            self.client.respond_to_case(
                self.id,
                {"response_note": response_note},
                self.universe.fac_admin_headers,
            )
        )
        return self.case

    def substantiate(
        self, resolution_note: str = "The reported hours are not supported."
    ) -> Dict[str, Any]:
        self.case = _data(
            self.client.substantiate_case(
                self.id, {"resolution_note": resolution_note}, self.auditor_headers
            )
        )
        return self.case

    def dismiss(
        self, resolution_note: str = "The census figures reconcile after review."
    ) -> Dict[str, Any]:
        self.case = _data(
            self.client.dismiss_case(
                self.id, {"resolution_note": resolution_note}, self.auditor_headers
            )
        )
        return self.case

    def drive_to_under_review(self) -> Dict[str, Any]:
        """Run one evidence round so the case has been heard once, which is what
        substantiation and dismissal both need."""
        self.request_info()
        return self.respond()


class AppealScenario:
    """A filed rating appeal and the reviewer's two possible decisions."""

    def __init__(
        self,
        measure: MeasureScenario,
        grounds: str = AppealGrounds.DATA_ENTRY_ERROR.value,
        narrative: str = (
            "Two RN shifts were keyed against the wrong reporting period."
        ),
        discrepancy_case_id: Optional[str] = None,
    ):
        self.measure = measure
        self.universe = measure.universe
        self.client = measure.client
        self.reviewer_headers = make_appeals_reviewer_headers(REVIEWER_USER_ID)
        self.appeal = _data(
            self.client.create_rating_appeal(
                create_rating_appeal_payload(
                    measure.id,
                    measure.version,
                    grounds=grounds,
                    narrative=narrative,
                    discrepancy_case_id=discrepancy_case_id,
                ),
                self.universe.fac_admin_headers,
            )
        )

    @property
    def id(self) -> str:
        return self.appeal["id"]

    def refresh(self) -> Dict[str, Any]:
        self.appeal = _data(
            self.client.get_rating_appeal(self.id, self.reviewer_headers)
        )
        return self.appeal

    def grant(
        self, decision_note: str = "The facility's correction is accepted in full."
    ) -> Dict[str, Any]:
        self.appeal = _data(
            self.client.grant_rating_appeal(
                self.id, {"decision_note": decision_note}, self.reviewer_headers
            )
        )
        return self.appeal

    def deny(
        self, decision_note: str = "The measure was computed from the filed data."
    ) -> Dict[str, Any]:
        self.appeal = _data(
            self.client.deny_rating_appeal(
                self.id, {"decision_note": decision_note}, self.reviewer_headers
            )
        )
        return self.appeal


# ---------------------------------------------------------------------------
# Tier 4 — agency batch chains
# ---------------------------------------------------------------------------


class VendorScenario:
    """A staffing agency, one of its contractors at the facility, and its
    batches."""

    def __init__(self, universe: ReportingUniverse):
        self.universe = universe
        self.client = universe.client
        self.vendor = _data(
            self.client.create_vendor(
                create_vendor_payload(universe.facility_id), universe.admin_headers
            )
        )
        self.contractor = _data(
            self.client.create_worker(
                create_worker_payload(
                    universe.facility_id,
                    universe.jc_rn["id"],
                    full_name="Casey Agency",
                    worker_type=WorkerType.AGENCY_CONTRACTOR.value,
                    vendor_id=self.vendor["id"],
                    authorized_roles=[],
                ),
                universe.admin_headers,
            )
        )
        self.batch: Optional[Dict[str, Any]] = None

    @property
    def vendor_id(self) -> str:
        return self.vendor["id"]

    @property
    def vendor_headers(self) -> Dict[str, str]:
        """The vendor representative acts as the `StaffingVendor` itself."""
        return make_vendor_representative_headers(self.vendor_id)

    def batch_line(
        self,
        work_date: str,
        shift_start: str = "07:00",
        shift_end: str = "15:00",
        job_category_id: Optional[str] = None,
        allocations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return vendor_batch_line(
            self.contractor["id"],
            job_category_id or self.universe.jc_rn["id"],
            work_date,
            shift_start=shift_start,
            shift_end=shift_end,
            allocations=allocations,
        )

    def file_batch(
        self,
        lines: List[Dict[str, Any]],
        reporting_period_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.batch = _data(
            self.client.create_vendor_submission(
                create_vendor_submission_payload(
                    self.vendor_id,
                    self.universe.facility_id,
                    reporting_period_id or self.universe.period_id,
                    lines,
                ),
                self.vendor_headers,
            )
        )
        return self.batch

    def refresh(self) -> Dict[str, Any]:
        self.batch = _data(
            self.client.get_vendor_submission(self.batch["id"], self.vendor_headers)
        )
        return self.batch

    def submit_batch(self) -> Dict[str, Any]:
        self.batch = _data(
            self.client.submit_vendor_submission(
                self.batch["id"], self.vendor_headers
            )
        )
        return self.batch

    def accept_batch(self, submission_id: str) -> Dict[str, Any]:
        self.batch = _data(
            self.client.accept_vendor_submission(
                self.batch["id"],
                {"submission_id": submission_id},
                self.universe.coord_headers,
            )
        )
        return self.batch

    def reject_batch(
        self, rejection_reason: str = "Line two names a shift we did not request."
    ) -> Dict[str, Any]:
        self.batch = _data(
            self.client.reject_vendor_submission(
                self.batch["id"],
                {"rejection_reason": rejection_reason},
                self.universe.coord_headers,
            )
        )
        return self.batch

    def revoke_batch(self) -> Dict[str, Any]:
        self.batch = _data(
            self.client.revoke_vendor_submission(
                self.batch["id"], self.vendor_headers
            )
        )
        return self.batch


def build_submitted_vendor_batch(
    client: ApiClient = api_client,
    work_dates: Optional[List[str]] = None,
):
    """A DRAFT quarter holding one 12.00-hour RN shift, plus a SUBMITTED agency
    batch of 12.00-hour RN lines awaiting the facility's acceptance."""
    scenario = build_draft_submission(client)
    vendor = VendorScenario(scenario.universe)
    lines = [
        vendor.batch_line(work_date, "07:00", "19:00")
        for work_date in (work_dates or ["2026-04-02", "2026-04-03"])
    ]
    vendor.file_batch(lines)
    vendor.submit_batch()
    return scenario, vendor


# ---------------------------------------------------------------------------
# Tier 5 — scenarios built for a specific arithmetic or cascade
# ---------------------------------------------------------------------------


def build_split_allocation_quarter(
    client: ApiClient = api_client,
) -> SubmissionScenario:
    """A DRAFT quarter holding the pinned 7.50-hour shift split 45.00 / 27.50 /
    27.50 across the 1.00, 0.60, and 0.00 credit categories."""
    scenario = build_draft_submission(client)
    universe = scenario.universe
    scenario.capture_hours(
        work_date="2026-04-01",
        shift_start="07:00",
        shift_end="14:30",
        allocations=[
            allocation_line(universe.jc_rn["id"], 45.00),
            allocation_line(universe.jc_split["id"], 27.50),
            allocation_line(universe.jc_admin["id"], 27.50),
        ],
    )
    return scenario


def build_dual_variant_quarter(client: ApiClient = api_client) -> SubmissionScenario:
    """Four 15.00-hour RN shifts across 2026-04-01 to 2026-04-04, only the first
    two supported by payroll and verified, with census days in three different
    reconciliation states so the as-submitted and audit-adjusted readings of the
    same quarter diverge."""
    scenario = build_draft_submission(client)

    supported_dates = ["2026-04-01", "2026-04-02"]
    unsupported_dates = ["2026-04-03", "2026-04-04"]
    verified: List[str] = []
    for work_date in supported_dates:
        entry = scenario.capture_supported_hours(
            work_date=work_date,
            shift_start="07:00",
            shift_end="22:00",
            paid_hours=15.00,
        )
        verified.append(entry["id"])
    for work_date in unsupported_dates:
        scenario.capture_hours(
            work_date=work_date, shift_start="07:00", shift_end="22:00"
        )

    # One reconciled day, one merely reported day whose MDS count is absent, and
    # one disputed day.
    scenario.report_reconciled_census("2026-04-01", 5, 5)
    scenario.report_census("2026-04-02", 5, None)
    disputed = scenario.report_census("2026-04-04", 5, 6)
    scenario.reconcile_census(disputed["id"])

    for entry_id in verified:
        scenario.verify_hours(entry_id)
    return scenario


def build_audit_sample_quarter(client: ApiClient = api_client) -> SubmissionScenario:
    """Six RN shifts on consecutive dates with the first, second, and sixth
    supported and verified, so the sampled reading (the first five active
    entries by work date) and the full-population reading disagree."""
    scenario = build_draft_submission(client)
    shifts = [
        ("2026-04-01", "07:00", "15:00", 8.00, True),
        ("2026-04-02", "07:00", "19:00", 12.00, True),
        ("2026-04-03", "07:00", "19:00", 12.00, False),
        ("2026-04-04", "07:00", "15:00", 8.00, False),
        ("2026-04-05", "07:00", "15:00", 8.00, False),
        ("2026-04-06", "07:00", "19:00", 12.00, True),
    ]
    verified: List[str] = []
    for work_date, start, end, hours, supported in shifts:
        if supported:
            entry = scenario.capture_supported_hours(
                work_date=work_date,
                shift_start=start,
                shift_end=end,
                paid_hours=hours,
            )
            verified.append(entry["id"])
        else:
            scenario.capture_hours(
                work_date=work_date, shift_start=start, shift_end=end
            )

    scenario.report_reconciled_census("2026-04-01", 5, 5)
    scenario.report_reconciled_census("2026-04-02", 5, 5)
    disputed = scenario.report_census("2026-04-03", 5, 6)
    scenario.reconcile_census(disputed["id"])

    for entry_id in verified:
        scenario.verify_hours(entry_id)
    return scenario


def build_case_under_review(
    client: ApiClient = api_client,
    trigger_reason: str = CaseTriggerReason.CENSUS_MISMATCH.value,
):
    """A VALIDATED quarter whose facility sits under an investigation that has
    already heard the facility once, so the case can be closed either way."""
    scenario = build_validated_quarter(client)
    case = CaseScenario(scenario, trigger_reason=trigger_reason)
    return scenario, case


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> ApiClient:
    return api_client


@pytest.fixture
def universe(client: ApiClient) -> ReportingUniverse:
    return build_universe(client)


@pytest.fixture
def draft_submission(client: ApiClient) -> SubmissionScenario:
    return build_draft_submission(client)


@pytest.fixture
def supported_quarter(client: ApiClient) -> SubmissionScenario:
    return build_supported_quarter(client)


@pytest.fixture
def validated_quarter(client: ApiClient) -> SubmissionScenario:
    return build_validated_quarter(client)


@pytest.fixture
def submitted_quarter(client: ApiClient) -> SubmissionScenario:
    return build_submitted_quarter(client)


@pytest.fixture
def accepted_quarter(client: ApiClient) -> SubmissionScenario:
    return build_accepted_quarter(client)


@pytest.fixture
def provisional_measure(client: ApiClient) -> MeasureScenario:
    return build_provisional_measure(client)


@pytest.fixture
def published_measure(client: ApiClient) -> MeasureScenario:
    return build_published_measure(client)


@pytest.fixture
def split_allocation_quarter(client: ApiClient) -> SubmissionScenario:
    return build_split_allocation_quarter(client)


@pytest.fixture
def dual_variant_quarter(client: ApiClient) -> SubmissionScenario:
    return build_dual_variant_quarter(client)


@pytest.fixture
def audit_sample_quarter(client: ApiClient) -> SubmissionScenario:
    return build_audit_sample_quarter(client)

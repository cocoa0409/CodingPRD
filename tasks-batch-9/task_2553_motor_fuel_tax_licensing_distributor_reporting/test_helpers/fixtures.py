"""Composite builders and pytest fixtures.

Every builder reaches its target state only through endpoints the PRD declares,
because the API under test starts each test from an empty database.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import (
    ApiClient,
    make_audit_manager_headers,
    make_field_inspector_headers,
    make_licensee_agent_headers,
    make_licensing_officer_headers,
    make_returns_examiner_headers,
    make_tax_supervisor_headers,
)
from .constants import NEW_LICENSEE_REQUIRED_BOND_CENTS
from .factories import (
    amendment_payload,
    assessment_payload,
    audit_case_payload,
    bond_payload,
    certificate_payload,
    cross_match_run_payload,
    decide_payload,
    inspection_payload,
    inquiry_payload,
    licensee_payload,
    line_payload,
    pay_payload,
    payment_payload,
    refund_claim_payload,
    response_payload,
    resolve_payload,
    return_payload,
    review_payload,
    schedule_payload,
    terminal_payload,
)
from .test_users import (
    AUDIT_MANAGER_ALT_ID,
    AUDIT_MANAGER_ID,
    FIELD_INSPECTOR_ID,
    LICENSING_OFFICER_ID,
    RETURNS_EXAMINER_ALT_ID,
    RETURNS_EXAMINER_ID,
    TAX_SUPERVISOR_ALT_ID,
    TAX_SUPERVISOR_ID,
)

Json = Dict[str, Any]


class MftWorld:
    """Builders that drive the API from an empty database to a wanted state."""

    def __init__(self, api: ApiClient):
        self.api = api
        self.officer = make_licensing_officer_headers(LICENSING_OFFICER_ID)
        self.examiner = make_returns_examiner_headers(RETURNS_EXAMINER_ID)
        self.examiner_alt = make_returns_examiner_headers(RETURNS_EXAMINER_ALT_ID)
        self.supervisor = make_tax_supervisor_headers(TAX_SUPERVISOR_ID)
        self.supervisor_alt = make_tax_supervisor_headers(TAX_SUPERVISOR_ALT_ID)
        self.manager = make_audit_manager_headers(AUDIT_MANAGER_ID)
        self.manager_alt = make_audit_manager_headers(AUDIT_MANAGER_ALT_ID)
        self.inspector = make_field_inspector_headers(FIELD_INSPECTOR_ID)
        self._supplier_counterparty: Optional[Json] = None

    # ------------------------------------------------------------------
    # identities and the logical clock
    # ------------------------------------------------------------------

    def agent(self, licensee_id: str) -> Json:
        """Headers for the `LicenseeAgent` of the given licensee."""
        return make_licensee_agent_headers(licensee_id)

    def set_clock(self, to_iso8601: str) -> Json:
        """Move the logical clock, which mutates no persisted entity."""
        response = self.api.set_clock(to_iso8601, self.examiner)
        return validate_success(response)

    # ------------------------------------------------------------------
    # tier 1: licensee state progression
    # ------------------------------------------------------------------

    def new_licensee(self, license_type: str = "DISTRIBUTOR", **overrides: Any) -> Json:
        """A registered licensee sitting in PENDING_BOND."""
        response = self.api.create_licensee(
            licensee_payload(license_type, **overrides), self.officer
        )
        return get_success_data(response)

    def licensee(self, licensee_id: str) -> Json:
        """Re-read a licensee, so a caller always has its current version."""
        return get_success_data(self.api.get_licensee(licensee_id, self.officer))

    def bond_status(self, licensee_id: str) -> Json:
        """The computed bond position of a licensee."""
        return get_success_data(self.api.get_bond_status(licensee_id, self.officer))

    def post_bond(self, licensee_id: str, amount_cents: int, **overrides: Any) -> Json:
        """Post a bond carrying the licensee's current version."""
        current = self.licensee(licensee_id)
        response = self.api.post_bond(
            licensee_id,
            bond_payload(amount_cents, current["version"], **overrides),
            self.officer,
        )
        return get_success_data(response)

    def activate(self, licensee_id: str) -> Json:
        return get_success_data(self.api.activate_licensee(licensee_id, self.officer))

    def suspend(self, licensee_id: str, reason: str = "Compliance review") -> Json:
        return get_success_data(
            self.api.suspend_licensee(licensee_id, reason, self.officer)
        )

    def revoke(self, licensee_id: str, reason: str = "Statutory revocation") -> Json:
        return get_success_data(self.api.revoke_licensee(licensee_id, reason, self.officer))

    def active_licensee(
        self,
        license_type: str = "DISTRIBUTOR",
        bond_cents: Optional[int] = None,
        **overrides: Any,
    ) -> Json:
        """A licensee bonded to its requirement and driven to ACTIVE."""
        licensee = self.new_licensee(license_type, **overrides)
        amount = (
            bond_cents
            if bond_cents is not None
            else NEW_LICENSEE_REQUIRED_BOND_CENTS[license_type]
        )
        self.post_bond(licensee["id"], amount)
        return self.activate(licensee["id"])

    def suspended_licensee(self, license_type: str = "DISTRIBUTOR", **overrides: Any) -> Json:
        licensee = self.active_licensee(license_type, **overrides)
        return self.suspend(licensee["id"])

    def revoked_licensee(self, license_type: str = "DISTRIBUTOR", **overrides: Any) -> Json:
        licensee = self.active_licensee(license_type, **overrides)
        return self.revoke(licensee["id"])

    def active_supplier(self, **overrides: Any) -> Json:
        return self.active_licensee("SUPPLIER", **overrides)

    def active_distributor(self, **overrides: Any) -> Json:
        return self.active_licensee("DISTRIBUTOR", **overrides)

    def supplier_counterparty(self) -> Json:
        """A shared ACTIVE supplier usable as the upstream side of a purchase line."""
        if self._supplier_counterparty is None:
            self._supplier_counterparty = self.active_licensee("SUPPLIER")
        return self._supplier_counterparty

    def ledger(self, licensee_id: str, entry_type: Optional[str] = None) -> List[Json]:
        params = {"limit": 100}
        if entry_type is not None:
            params["entry_type"] = entry_type
        response = self.api.list_ledger_entries(licensee_id, self.officer, params=params)
        return get_success_data(response)

    # ------------------------------------------------------------------
    # tier 2: entity hierarchy
    # ------------------------------------------------------------------

    def terminal(self, **overrides: Any) -> Json:
        return get_success_data(
            self.api.create_terminal(terminal_payload(**overrides), self.officer)
        )

    def certificate(self, purchaser_licensee_id: str, **overrides: Any) -> Json:
        return get_success_data(
            self.api.create_certificate(
                certificate_payload(purchaser_licensee_id, **overrides), self.officer
            )
        )

    def draft_return(
        self, licensee_id: str, period_month: str = "2026-07", as_headers: Optional[Json] = None
    ) -> Json:
        return get_success_data(
            self.api.create_return(
                return_payload(licensee_id, period_month), as_headers or self.examiner
            )
        )

    def schedule(
        self,
        return_id: str,
        schedule_code: str,
        product_code: str,
        total_gallons: float,
        as_headers: Optional[Json] = None,
    ) -> Json:
        return get_success_data(
            self.api.create_schedule(
                return_id,
                schedule_payload(schedule_code, product_code, total_gallons),
                as_headers or self.examiner,
            )
        )

    def line(
        self,
        schedule_id: str,
        counterparty_licensee_id: str,
        gallons: float,
        document_date: str = "2026-07-15",
        as_headers: Optional[Json] = None,
        **overrides: Any,
    ) -> Json:
        return get_success_data(
            self.api.create_line(
                schedule_id,
                line_payload(
                    counterparty_licensee_id, gallons, document_date, **overrides
                ),
                as_headers or self.examiner,
            )
        )

    # ------------------------------------------------------------------
    # tier 3: lifecycle shortcuts
    # ------------------------------------------------------------------

    def build_return(
        self,
        licensee_id: str,
        period_month: str = "2026-07",
        schedules: Optional[List[Json]] = None,
        file: bool = False,
        attest_name: str = "Dana Meyer",
        as_headers: Optional[Json] = None,
        return_id: Optional[str] = None,
    ) -> "BuiltReturn":
        """Open a return, add the described schedules and lines, and optionally file it.

        Each entry of ``schedules`` is a mapping with ``code``, ``product``, an
        optional declared ``total`` (defaulting to the exact sum of its lines)
        and an optional ``lines`` list of mappings with ``counterparty``,
        ``gallons``, an optional ``date`` and any extra line fields.
        """
        row = (
            {"id": return_id}
            if return_id is not None
            else self.draft_return(licensee_id, period_month, as_headers=as_headers)
        )
        built_schedules: List[Json] = []
        built_lines: List[List[Json]] = []
        for spec in schedules or []:
            lines = spec.get("lines", [])
            declared = spec.get("total")
            if declared is None:
                declared = float(sum(float(line["gallons"]) for line in lines))
            schedule = self.schedule(
                row["id"], spec["code"], spec["product"], declared, as_headers=as_headers
            )
            built_schedules.append(schedule)
            these_lines = []
            for line in lines:
                extras = {
                    key: value
                    for key, value in line.items()
                    if key not in ("counterparty", "gallons", "date")
                }
                these_lines.append(
                    self.line(
                        schedule["id"],
                        line["counterparty"],
                        line["gallons"],
                        line.get("date", f"{period_month}-15"),
                        as_headers=as_headers,
                        **extras,
                    )
                )
            built_lines.append(these_lines)
        if file:
            row = self.file_return(row["id"], attest_name, as_headers=as_headers)
        elif return_id is not None:
            row = get_success_data(self.api.get_return(row["id"], self.examiner))
        return BuiltReturn(row, built_schedules, built_lines)

    def file_return(
        self,
        return_id: str,
        attest_name: str = "Dana Meyer",
        as_headers: Optional[Json] = None,
    ) -> Json:
        return get_success_data(
            self.api.file_return(return_id, attest_name, as_headers or self.examiner)
        )

    def filed_return(
        self,
        licensee_id: str,
        period_month: str = "2026-07",
        schedules: Optional[List[Json]] = None,
        **kwargs: Any,
    ) -> "BuiltReturn":
        return self.build_return(
            licensee_id, period_month, schedules, file=True, **kwargs
        )

    def taxable_return(
        self,
        licensee_id: str,
        period_month: str = "2026-07",
        gallons: float = 1000.00,
        product_code: str = "UNDYED_DIESEL",
        counterparty_id: Optional[str] = None,
        file: bool = True,
    ) -> "BuiltReturn":
        """A return whose only schedule is a tax-unpaid receipt of the given gallons."""
        counterparty = counterparty_id or self.supplier_counterparty()["id"]
        return self.build_return(
            licensee_id,
            period_month,
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": product_code,
                    "lines": [{"counterparty": counterparty, "gallons": gallons}],
                }
            ],
            file=file,
        )

    def tax_paid_pool(
        self,
        licensee_id: str,
        period_month: str = "2026-07",
        gallons: float = 1000.00,
        counterparty_id: Optional[str] = None,
    ) -> "BuiltReturn":
        """A filed return carrying tax-paid UNDYED_DIESEL receipts, the refund pool."""
        counterparty = counterparty_id or self.supplier_counterparty()["id"]
        return self.build_return(
            licensee_id,
            period_month,
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "lines": [{"counterparty": counterparty, "gallons": gallons}],
                }
            ],
            file=True,
        )

    def amendment(
        self,
        return_id: str,
        expected_return_version: Optional[int] = None,
        reason: str = "Corrected receipts schedule",
        as_headers: Optional[Json] = None,
    ) -> Json:
        if expected_return_version is None:
            expected_return_version = get_success_data(
                self.api.get_return(return_id, self.examiner)
            )["version"]
        return get_success_data(
            self.api.create_amendment(
                return_id,
                amendment_payload(expected_return_version, reason),
                as_headers or self.examiner,
            )
        )

    # ------------------------------------------------------------------
    # cross-matching
    # ------------------------------------------------------------------

    def run_cross_match(
        self,
        period_month: str = "2026-07",
        tolerance_gallons: Optional[float] = None,
        as_headers: Optional[Json] = None,
    ) -> Json:
        return get_success_data(
            self.api.create_cross_match_run(
                cross_match_run_payload(period_month, tolerance_gallons),
                as_headers or self.examiner,
            )
        )

    def discrepancies(self, **params: Any) -> List[Json]:
        params.setdefault("limit", 100)
        return get_success_data(self.api.list_discrepancies(self.examiner, params=params))

    def only_discrepancy(self, run_id: str) -> Json:
        rows = self.discrepancies(run_id=run_id)
        assert len(rows) == 1, f"expected exactly one discrepancy for the run, got {len(rows)}"
        return rows[0]

    def send_inquiry(self, discrepancy_id: str, **overrides: Any) -> Json:
        return get_success_data(
            self.api.send_inquiry(discrepancy_id, inquiry_payload(**overrides), self.examiner)
        )

    def answer_inquiry(
        self, discrepancy_id: str, distributor_licensee_id: str, **overrides: Any
    ) -> Json:
        return get_success_data(
            self.api.post_response(
                discrepancy_id,
                response_payload(**overrides),
                self.agent(distributor_licensee_id),
            )
        )

    def walk_to_response_received(
        self, discrepancy_id: str, distributor_licensee_id: str
    ) -> Json:
        """Drive a discrepancy OPEN -> INQUIRY_SENT -> RESPONSE_RECEIVED."""
        self.send_inquiry(discrepancy_id)
        return self.answer_inquiry(discrepancy_id, distributor_licensee_id)

    def resolve(
        self, discrepancy_id: str, resolution: str, write_off_reason: Optional[str] = None
    ) -> Json:
        return get_success_data(
            self.api.resolve_discrepancy(
                discrepancy_id, resolve_payload(resolution, write_off_reason), self.examiner
            )
        )

    def unreported_cell(
        self,
        supplier_gallons: float,
        distributor_gallons: Optional[float],
        period_month: str = "2026-07",
        product_code: str = "UNDYED_DIESEL",
        run: bool = True,
    ) -> Json:
        """A supplier/distributor pair whose cell carries the given gallons figures.

        Returns a mapping of the pieces: the two licensees, their filed returns
        and, when ``run`` is set, the completed run and its single discrepancy.
        """
        supplier = self.active_licensee("SUPPLIER")
        distributor = self.active_licensee("DISTRIBUTOR")
        supplier_return = self.build_return(
            supplier["id"],
            period_month,
            [
                {
                    "code": "SCH_5_DELIVERED_TAX_COLLECTED",
                    "product": product_code,
                    "lines": [
                        {"counterparty": distributor["id"], "gallons": supplier_gallons}
                    ],
                }
            ],
            file=True,
        )
        distributor_return = None
        if distributor_gallons is not None:
            distributor_return = self.build_return(
                distributor["id"],
                period_month,
                [
                    {
                        "code": "SCH_1_RECEIVED_TAX_PAID",
                        "product": product_code,
                        "lines": [
                            {"counterparty": supplier["id"], "gallons": distributor_gallons}
                        ],
                    }
                ],
                file=True,
            )
        cell: Json = {
            "supplier": supplier,
            "distributor": distributor,
            "supplier_return": supplier_return,
            "distributor_return": distributor_return,
        }
        if run:
            cell["run"] = self.run_cross_match(period_month)
            rows = self.discrepancies(run_id=cell["run"]["id"])
            cell["discrepancies"] = rows
            cell["discrepancy"] = rows[0] if rows else None
        return cell

    # ------------------------------------------------------------------
    # refund claims
    # ------------------------------------------------------------------

    def refund_claim(
        self,
        licensee_id: str,
        period_month: str = "2026-07",
        claimed_gallons: float = 100.00,
        claim_type: str = "OFF_ROAD",
        equipment_class: Optional[str] = None,
        as_headers: Optional[Json] = None,
    ) -> Json:
        return get_success_data(
            self.api.create_refund_claim(
                refund_claim_payload(
                    licensee_id, period_month, claimed_gallons, claim_type, equipment_class
                ),
                as_headers or self.examiner,
            )
        )

    def review_claim(
        self,
        claim_id: str,
        recommendation: str = "APPROVE",
        recommended_gallons: Optional[float] = None,
        as_headers: Optional[Json] = None,
    ) -> Json:
        return get_success_data(
            self.api.review_claim(
                claim_id,
                review_payload(recommendation, recommended_gallons),
                as_headers or self.examiner,
            )
        )

    def decide_claim(
        self, claim_id: str, decision: str = "APPROVED", as_headers: Optional[Json] = None
    ) -> Json:
        return get_success_data(
            self.api.decide_claim(
                claim_id, decide_payload(decision), as_headers or self.supervisor
            )
        )

    def pay_claim(
        self,
        claim_id: str,
        payment_reference: str = "WARRANT-000123",
        as_headers: Optional[Json] = None,
    ) -> Json:
        return get_success_data(
            self.api.pay_claim(
                claim_id, pay_payload(payment_reference), as_headers or self.supervisor_alt
            )
        )

    def submitted_claim_with_pool(
        self,
        pool_gallons: float = 1000.00,
        claimed_gallons: float = 100.00,
        period_month: str = "2026-07",
        claim_type: str = "OFF_ROAD",
        license_type: str = "DISTRIBUTOR",
    ) -> Json:
        """An ACTIVE licensee with a filed tax-paid return and one SUBMITTED claim."""
        licensee = self.active_licensee(license_type)
        filed = self.tax_paid_pool(licensee["id"], period_month, pool_gallons)
        claim = self.refund_claim(
            licensee["id"], period_month, claimed_gallons, claim_type
        )
        return {"licensee": licensee, "return": filed, "claim": claim}

    # ------------------------------------------------------------------
    # roadside enforcement
    # ------------------------------------------------------------------

    def inspection(
        self,
        inspected_licensee_id: str,
        dye_test_result: str = "POSITIVE",
        gallons_in_tank: float = 150.00,
        inspection_date: str = "2026-07-20",
        **overrides: Any,
    ) -> Json:
        return get_success_data(
            self.api.create_inspection(
                inspection_payload(
                    inspected_licensee_id,
                    dye_test_result,
                    gallons_in_tank,
                    inspection_date,
                    **overrides,
                ),
                self.inspector,
            )
        )

    def dismiss_inspection(
        self, inspection_id: str, dismissal_reason: str = "Sample re-tested clean"
    ) -> Json:
        return get_success_data(
            self.api.dismiss_inspection(inspection_id, dismissal_reason, self.supervisor)
        )

    # ------------------------------------------------------------------
    # audit cases, assessments and collection
    # ------------------------------------------------------------------

    def audit_case(
        self,
        subject_licensee_id: str,
        period_start_month: str = "2026-07",
        period_end_month: str = "2026-07",
        as_headers: Optional[Json] = None,
        **overrides: Any,
    ) -> Json:
        return get_success_data(
            self.api.create_audit_case(
                audit_case_payload(
                    subject_licensee_id, period_start_month, period_end_month, **overrides
                ),
                as_headers or self.manager,
            )
        )

    def advance(self, case_id: str, to_status: str, as_headers: Optional[Json] = None) -> Json:
        return get_success_data(
            self.api.advance_case(case_id, to_status, as_headers or self.manager)
        )

    def case_at(
        self,
        subject_licensee_id: str,
        case_status: str = "PRELIM_FINDINGS",
        period_start_month: str = "2026-07",
        period_end_month: str = "2026-07",
        **overrides: Any,
    ) -> Json:
        """Open a case and walk the case dimension to the wanted status."""
        case = self.audit_case(
            subject_licensee_id, period_start_month, period_end_month, **overrides
        )
        ladder = ["FIELDWORK", "PRELIM_FINDINGS", "TAXPAYER_RESPONSE"]
        if case_status == "OPEN":
            return case
        for step in ladder:
            case = self.advance(case["id"], step)
            if step == case_status:
                return case
        if case_status == "CLOSED":
            return self.advance(case["id"], "CLOSED")
        return case

    def issue_assessment(
        self,
        case_id: str,
        additional_tax_cents: int,
        evasion_indicator: bool = False,
        as_headers: Optional[Json] = None,
    ) -> Json:
        return get_success_data(
            self.api.issue_assessment(
                case_id,
                assessment_payload(additional_tax_cents, evasion_indicator),
                as_headers or self.supervisor,
            )
        )

    def abate(
        self,
        case_id: str,
        abatement_reason: str = "Findings withdrawn on review",
        as_headers: Optional[Json] = None,
    ) -> Json:
        return get_success_data(
            self.api.abate_assessment(
                case_id, abatement_reason, as_headers or self.supervisor_alt
            )
        )

    def finalize(self, case_id: str, as_headers: Optional[Json] = None) -> Json:
        return get_success_data(
            self.api.finalize_assessment(case_id, as_headers or self.supervisor)
        )

    def protest(
        self, case_id: str, licensee_id: str, protest_grounds: str = "The gallons were exported"
    ) -> Json:
        return get_success_data(
            self.api.protest_assessment(case_id, protest_grounds, self.agent(licensee_id))
        )

    def payment(
        self,
        licensee_id: str,
        amount_cents: int,
        effective_date: str = "2026-08-01",
        memo: Optional[str] = None,
    ) -> Json:
        return get_success_data(
            self.api.create_payment(
                licensee_id, payment_payload(amount_cents, effective_date, memo), self.supervisor
            )
        )

    def risk_profile(self, licensee_id: str) -> Json:
        return get_success_data(self.api.get_risk_profile(licensee_id, self.manager))


class BuiltReturn:
    """A monthly return together with the schedules and lines built under it."""

    def __init__(self, row: Json, schedules: List[Json], lines: List[List[Json]]):
        self.row = row
        self.id = row["id"]
        self.schedules = schedules
        self.lines = lines

    @property
    def schedule(self) -> Json:
        return self.schedules[0]

    @property
    def line(self) -> Json:
        return self.lines[0][0]


# --------------------------------------------------------------------------
# pytest fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def world(api):
    """Builders bound to the client under test."""
    return MftWorld(api)


@pytest.fixture
def clock_default(world):
    """The mandated startup reading of the logical clock, restated explicitly."""
    from .constants import DEFAULT_CLOCK_UTC

    return DEFAULT_CLOCK_UTC


__all__ = ["MftWorld", "BuiltReturn", "world", "clock_default"]

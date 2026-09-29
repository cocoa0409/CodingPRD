"""Composite setup builders.

The test harness restarts the API server before every test, so each test starts
against an empty database. Everything here therefore builds state from scratch
using only the endpoints the PRD declares — there is no back door into storage.

The canonical chain is: move the logical clock, register and approve a sponsor,
register the subject property and the trades, open an application, add and
approve scope lines, size, decide, close.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import validate_success

from . import factories as f
from .api_client import api_client
from .test_users import (
    CREDIT_COMMITTEE,
    INSPECTOR,
    LOAN_OFFICER,
    PLATFORM_ADMIN,
    SERVICER,
    SERVICER_2,
    make_borrower_headers,
)

Json = Dict[str, Any]
Headers = Dict[str, str]

DEFAULT_CLOCK = "2026-08-10T09:00:00Z"
DEFAULT_CLOSING_DATE = "2026-08-10"


@dataclass
class ScopeSpec:
    """One rehab scope line: what the borrower proposes and what gets approved."""

    scope_code: str
    cost_cents: int
    contractor: int = 0
    description: str = "Trade scope of work"
    approved_cost_cents: Optional[int] = None


# The three-line budget totals 10,000,000 of approved rehab.
THREE_LINE_SCOPE: List[ScopeSpec] = [
    ScopeSpec("ROOF", 4_000_000, 0, "Tear-off and re-deck"),
    ScopeSpec("KITCHEN", 3_500_000, 0, "Cabinets and counters"),
    ScopeSpec("ELECTRICAL", 2_500_000, 1, "Full rewire and panel"),
]

# The two-line budget totals 5,000,000 of approved rehab.
TWO_LINE_SCOPE: List[ScopeSpec] = [
    ScopeSpec("ROOF", 2_500_000, 0, "Tear-off and re-deck"),
    ScopeSpec("ELECTRICAL", 2_500_000, 1, "Full rewire and panel"),
]

CONTRACTOR_ONE = {"business_name": "Vega Roofing", "license_number": "LIC-4471"}
CONTRACTOR_TWO = {"business_name": "Ortiz Electric", "license_number": "LIC-8820"}


@dataclass
class LendingContext:
    """Everything a test needs to keep addressing the rows it just built."""

    borrower: Json
    property: Json
    contractors: List[Json] = field(default_factory=list)
    application: Optional[Json] = None
    lines: List[Json] = field(default_factory=list)
    loan: Optional[Json] = None

    # ---------------------------------------------------------------- ids
    @property
    def borrower_id(self) -> str:
        return self.borrower["id"]

    @property
    def property_id(self) -> str:
        return self.property["id"]

    @property
    def application_id(self) -> str:
        assert self.application is not None
        return self.application["id"]

    @property
    def loan_id(self) -> str:
        assert self.loan is not None
        return self.loan["id"]

    @property
    def loan_version(self) -> int:
        assert self.loan is not None
        return self.loan["version"]

    @property
    def borrower_headers(self) -> Headers:
        return make_borrower_headers(self.borrower_id)

    def contractor_id(self, index: int = 0) -> str:
        return self.contractors[index]["id"]

    def line_id(self, index: int = 0) -> str:
        return self.lines[index]["id"]

    def line_by_code(self, scope_code: str) -> Json:
        for line in self.lines:
            if line["scope_code"] == scope_code:
                return line
        raise KeyError(f"no scope line with code {scope_code}")

    # ---------------------------------------------------------------- refresh
    def refresh_loan(self, headers: Headers = SERVICER) -> Json:
        self.loan = read_loan(self.loan_id, headers)
        return self.loan

    def refresh_application(self, headers: Headers = LOAN_OFFICER) -> Json:
        self.application = read_application(self.application_id, headers)
        return self.application

    def refresh_lines(self, headers: Headers = LOAN_OFFICER) -> List[Json]:
        self.lines = [read_line(line["id"], headers) for line in self.lines]
        return self.lines


# ---------------------------------------------------------------- primitives
def set_clock(to_iso8601: str, headers: Headers = PLATFORM_ADMIN) -> str:
    """PRD §2.4: a `PlatformAdmin` moves the clock by supplying `to_iso8601`."""
    data = validate_success(
        api_client.set_clock(f.clock_payload(to_iso8601), headers), 200
    )
    return data["current_utc"]


def register_borrower(headers: Headers = LOAN_OFFICER, **overrides) -> Json:
    return validate_success(
        api_client.create_borrower(f.borrower_payload(**overrides), headers), 201
    )


def execute_guarantee(
    borrower_id: str, headers: Headers = LOAN_OFFICER, **overrides
) -> Json:
    return validate_success(
        api_client.record_guarantee(
            borrower_id, f.guarantee_payload(**overrides), headers
        ),
        200,
    )


def approve_sponsor(
    borrower_id: str, headers: Headers = CREDIT_COMMITTEE, **overrides
) -> Json:
    return validate_success(
        api_client.borrower_status_action(
            borrower_id, f.approve_sponsor_payload(**overrides), headers
        ),
        200,
    )


def build_approved_sponsor(**overrides) -> Json:
    """Register a sponsor, execute the guarantee and approve it."""
    borrower = register_borrower(**overrides)
    execute_guarantee(borrower["id"])
    return approve_sponsor(borrower["id"])


def register_property(headers: Headers = LOAN_OFFICER, **overrides) -> Json:
    return validate_success(
        api_client.create_property(f.property_payload(**overrides), headers), 201
    )


def register_contractor(headers: Headers = LOAN_OFFICER, **overrides) -> Json:
    return validate_success(
        api_client.create_contractor(f.contractor_payload(**overrides), headers), 201
    )


def open_application(
    borrower_id: str,
    property_id: str,
    headers: Headers = LOAN_OFFICER,
    **overrides,
) -> Json:
    return validate_success(
        api_client.create_application(
            f.application_payload(borrower_id, property_id, **overrides), headers
        ),
        201,
    )


def add_scope_line(
    application_id: str,
    spec: ScopeSpec,
    contractor_id: str,
    headers: Optional[Headers] = None,
    borrower_headers: Optional[Headers] = None,
) -> Json:
    payload = f.rehab_line_payload(
        scope_code=spec.scope_code,
        cost_cents=spec.cost_cents,
        contractor_id=contractor_id,
        description=spec.description,
    )
    return validate_success(
        api_client.create_rehab_line_item(
            application_id, payload, headers or borrower_headers or LOAN_OFFICER
        ),
        201,
    )


def approve_scope_line(
    line_id: str, approved_cost_cents: Optional[int] = None, headers: Headers = LOAN_OFFICER
) -> Json:
    return validate_success(
        api_client.review_rehab_line_item(
            line_id, f.scope_approve_payload(approved_cost_cents), headers
        ),
        200,
    )


def read_application(application_id: str, headers: Headers = LOAN_OFFICER) -> Json:
    return validate_success(api_client.get_application(application_id, headers), 200)


def read_line(line_id: str, headers: Headers = LOAN_OFFICER) -> Json:
    return validate_success(api_client.get_rehab_line_item(line_id, headers), 200)


def read_loan(loan_id: str, headers: Headers = SERVICER) -> Json:
    return validate_success(api_client.get_loan(loan_id, headers), 200)


def read_contractor(contractor_id: str, headers: Headers = LOAN_OFFICER) -> Json:
    return validate_success(api_client.get_contractor(contractor_id, headers), 200)


def read_draw_request(draw_id: str, headers: Headers = SERVICER) -> Json:
    return validate_success(api_client.get_draw_request(draw_id, headers), 200)


def read_foreclosure_case(case_id: str, headers: Headers = SERVICER) -> Json:
    return validate_success(api_client.get_foreclosure_case(case_id, headers), 200)


def read_property(property_id: str, headers: Headers = LOAN_OFFICER) -> Json:
    return validate_success(api_client.get_property(property_id, headers), 200)


# ---------------------------------------------------------------- origination
def build_origination(
    *,
    clock: Optional[str] = DEFAULT_CLOCK,
    scope: Sequence[ScopeSpec] = tuple(THREE_LINE_SCOPE),
    approve_scope: bool = True,
    borrower_overrides: Optional[Json] = None,
    property_overrides: Optional[Json] = None,
    application_overrides: Optional[Json] = None,
    contractor_overrides: Optional[Sequence[Json]] = None,
) -> LendingContext:
    """Sponsor + property + trades + application + scope lines."""
    if clock is not None:
        set_clock(clock)

    borrower = build_approved_sponsor(**(borrower_overrides or {}))
    subject = register_property(**(property_overrides or {}))

    specs = list(contractor_overrides or [CONTRACTOR_ONE, CONTRACTOR_TWO])
    contractors = [register_contractor(**spec) for spec in specs]

    application = open_application(
        borrower["id"], subject["id"], **(application_overrides or {})
    )

    lines: List[Json] = []
    for spec in scope:
        lines.append(
            add_scope_line(
                application["id"], spec, contractors[spec.contractor]["id"]
            )
        )

    ctx = LendingContext(
        borrower=borrower,
        property=subject,
        contractors=contractors,
        application=application,
        lines=lines,
    )

    if approve_scope:
        approved: List[Json] = []
        for spec, line in zip(scope, lines):
            approved.append(approve_scope_line(line["id"], spec.approved_cost_cents))
        ctx.lines = approved
        ctx.refresh_application()

    return ctx


def size_application(
    ctx: LendingContext, headers: Headers = LOAN_OFFICER
) -> LendingContext:
    """PRD §3.3: a `LoanOfficer` runs the sizing pass."""
    ctx.application = validate_success(
        api_client.size_application(ctx.application_id, f.size_payload(), headers), 200
    )
    return ctx


def decide_application(
    ctx: LendingContext,
    headers: Headers = CREDIT_COMMITTEE,
    **overrides,
) -> LendingContext:
    """PRD §3.4: a `CreditCommittee` operator decides — never the sizer."""
    ctx.application = validate_success(
        api_client.decide_application(
            ctx.application_id, f.decision_payload(**overrides), headers
        ),
        200,
    )
    return ctx


def close_application(
    ctx: LendingContext,
    headers: Headers = SERVICER,
    closing_date: str = DEFAULT_CLOSING_DATE,
) -> LendingContext:
    """PRD §3.4: closing mints the `Loan` with its money buckets."""
    ctx.loan = validate_success(
        api_client.close_application(
            ctx.application_id, f.close_payload(closing_date), headers
        ),
        201,
    )
    ctx.refresh_application()
    ctx.refresh_lines()
    return ctx


def build_sized_application(**kwargs) -> LendingContext:
    return size_application(build_origination(**kwargs))


def build_approved_application(**kwargs) -> LendingContext:
    decision_overrides = kwargs.pop("decision_overrides", {}) or {}
    ctx = build_sized_application(**kwargs)
    return decide_application(ctx, **decision_overrides)


def build_closed_loan(**kwargs) -> LendingContext:
    """The full origination chain through to a live `Loan`.

    With the three-line budget this yields committed 23,953,713, funded
    principal 13,151,375, an interest reserve of 802,338 and a rehab holdback
    of 10,000,000.
    """
    closing_date = kwargs.pop("closing_date", DEFAULT_CLOSING_DATE)
    ctx = build_approved_application(**kwargs)
    return close_application(ctx, closing_date=closing_date)


# ---------------------------------------------------------------- draws
def submit_draw(
    ctx: LendingContext,
    allocations: Sequence[Tuple[str, float]],
    verification_method: str = "INSPECTION",
    expected_loan_version: Optional[int] = None,
    headers: Optional[Headers] = None,
) -> Json:
    """PRD §3.5: only the sponsor submits a draw, carrying the loan version."""
    if expected_loan_version is None:
        expected_loan_version = read_loan(ctx.loan_id)["version"]
    payload = f.draw_request_payload(
        [f.line_allocation(line_id, pct) for line_id, pct in allocations],
        expected_loan_version,
        verification_method,
    )
    return validate_success(
        api_client.create_draw_request(
            ctx.loan_id, payload, headers or ctx.borrower_headers
        ),
        201,
    )


def order_visit(
    draw_id: str,
    inspector_headers: Headers = INSPECTOR,
    window_start: str = "2026-09-15T09:00:00Z",
    window_end: str = "2026-09-15T11:00:00Z",
    headers: Headers = SERVICER,
) -> Json:
    """PRD §3.5: a `LoanServicer` orders the visit into an inspector's window."""
    payload = f.inspection_visit_payload(
        inspector_headers["X-User-ID"], window_start, window_end
    )
    return validate_success(
        api_client.create_inspection_visit(draw_id, payload, headers), 201
    )


def report_visit(
    visit_id: str,
    verifications: Sequence[Tuple[str, float]],
    headers: Headers = INSPECTOR,
) -> Json:
    """PRD §3.5: the assigned `DrawInspector` files the verified percentages."""
    payload = f.inspection_report_payload(
        [f.line_verification(line_id, pct) for line_id, pct in verifications]
    )
    return validate_success(
        api_client.report_inspection_visit(visit_id, payload, headers), 200
    )


def photo_verify(
    draw_id: str,
    verifications: Sequence[Tuple[str, float]],
    photo_count: int,
    headers: Headers = SERVICER,
) -> Json:
    """PRD §3.5: the photo leg verifies without a visit."""
    payload = f.photo_verification_payload(
        [f.line_verification(line_id, pct) for line_id, pct in verifications],
        photo_count,
    )
    return validate_success(
        api_client.photo_verify_draw_request(draw_id, payload, headers), 200
    )


def review_draw(
    draw_id: str, headers: Headers = SERVICER, **overrides
) -> Json:
    """PRD §3.6: a `LoanServicer` underwrites the verified draw."""
    return validate_success(
        api_client.review_draw_request(draw_id, f.draw_review_payload(**overrides), headers),
        200,
    )


def fund_draw(
    draw_id: str,
    headers: Headers = SERVICER_2,
    funding_date: str = "2026-09-15",
    **overrides,
) -> Json:
    """PRD §3.6: funding is the other half of the servicing split-duty pair."""
    return validate_success(
        api_client.fund_draw_request(
            draw_id, f.draw_fund_payload(funding_date, **overrides), headers
        ),
        200,
    )


def build_inspected_draw(
    ctx: LendingContext,
    allocations: Sequence[Tuple[str, float]],
    verifications: Optional[Sequence[Tuple[str, float]]] = None,
    inspector_headers: Headers = INSPECTOR,
    window_start: str = "2026-09-15T09:00:00Z",
    window_end: str = "2026-09-15T11:00:00Z",
) -> Tuple[Json, Json]:
    """Submit a draw, order the visit and file the inspection report."""
    draw = submit_draw(ctx, allocations, "INSPECTION")
    visit = order_visit(
        draw["id"], inspector_headers, window_start, window_end
    )
    report_visit(visit["id"], verifications or allocations, inspector_headers)
    return read_draw_request(draw["id"]), visit


def build_photo_verified_draw(
    ctx: LendingContext,
    allocations: Sequence[Tuple[str, float]],
    verifications: Optional[Sequence[Tuple[str, float]]] = None,
    photo_count: Optional[int] = None,
) -> Json:
    draw = submit_draw(ctx, allocations, "PHOTO")
    photo_verify(
        draw["id"],
        verifications or allocations,
        photo_count if photo_count is not None else 3 * len(allocations),
    )
    return read_draw_request(draw["id"])


# ---------------------------------------------------------------- lien waivers
def file_waiver(
    loan_id: str,
    contractor_id: str,
    amount_covered_cents: int,
    waiver_type: str = "PARTIAL_UNCONDITIONAL",
    headers: Optional[Headers] = None,
    **overrides,
) -> Json:
    payload = f.lien_waiver_payload(
        loan_id, contractor_id, amount_covered_cents, waiver_type, **overrides
    )
    from .test_users import make_contractor_headers

    return validate_success(
        api_client.create_lien_waiver(
            payload, headers or make_contractor_headers(contractor_id)
        ),
        201,
    )


def cover_all_contractors(
    ctx: LendingContext, amount_covered_cents: int = 10_000_000
) -> List[Json]:
    """Give every trade on the scope enough unconditional coverage to be paid."""
    return [
        file_waiver(ctx.loan_id, contractor["id"], amount_covered_cents)
        for contractor in ctx.contractors
    ]


# ---------------------------------------------------------------- servicing
def accrue(
    loan_id: str, period_start: str, period_end: str, headers: Headers = SERVICER
) -> Json:
    return validate_success(
        api_client.create_interest_accrual(
            loan_id, f.accrual_payload(period_start, period_end), headers
        ),
        201,
    )


def pay(
    loan_id: str,
    amount_cents: int,
    payment_date: str,
    intent: str = "REGULAR",
    headers: Headers = SERVICER,
) -> Json:
    return validate_success(
        api_client.create_payment(
            loan_id, f.payment_payload(amount_cents, payment_date, intent), headers
        ),
        200,
    )


def extend(
    loan_id: str, months: int = 1, headers: Headers = SERVICER
) -> Json:
    return validate_success(
        api_client.create_extension(loan_id, f.extension_payload(months), headers), 200
    )


def file_milestone(
    loan_id: str,
    milestone_type: str,
    effective_date: str,
    headers: Headers = SERVICER,
    **overrides,
) -> Json:
    return validate_success(
        api_client.create_exit_milestone(
            loan_id, f.milestone_payload(milestone_type, effective_date, **overrides), headers
        ),
        201,
    )


# ---------------------------------------------------------------- default path
def declare_default(loan_id: str, headers: Headers = SERVICER, **overrides) -> Json:
    return validate_success(
        api_client.declare_default(
            loan_id, f.default_declaration_payload(**overrides), headers
        ),
        200,
    )


def open_foreclosure_case(
    loan_id: str, notice_date: str, headers: Headers = SERVICER, **overrides
) -> Json:
    return validate_success(
        api_client.create_foreclosure_case(
            loan_id, f.foreclosure_case_payload(notice_date, **overrides), headers
        ),
        201,
    )


def take_over(case_id: str, takeover_date: str, headers: Headers = SERVICER) -> Json:
    return validate_success(
        api_client.takeover_foreclosure_case(
            case_id, f.takeover_payload(takeover_date), headers
        ),
        200,
    )


def set_completion_budget(
    case_id: str,
    budget_cents: int,
    expected_version: int,
    headers: Headers = SERVICER,
) -> Json:
    return validate_success(
        api_client.set_completion_budget(
            case_id,
            f.completion_budget_payload(budget_cents, expected_version),
            headers,
        ),
        200,
    )


def build_delinquent_loan(
    *, period_start: str, period_end: str, clock: str, **kwargs
) -> Tuple[LendingContext, Json]:
    """Close a loan, move the clock forward and accrue until the reserve runs dry."""
    ctx = build_closed_loan(**kwargs)
    set_clock(clock)
    period = accrue(ctx.loan_id, period_start, period_end)
    ctx.refresh_loan()
    return ctx, period


def build_defaulted_loan(
    *,
    accruals: Sequence[Tuple[str, str, str]],
    default_clock: str,
    **kwargs,
) -> LendingContext:
    """Drive a loan to `DEFAULT` through delinquency aging.

    `accruals` is a sequence of `(clock, period_start, period_end)` triples.
    """
    ctx = build_closed_loan(**kwargs)
    for clock, start, end in accruals:
        set_clock(clock)
        accrue(ctx.loan_id, start, end)
    set_clock(default_clock)
    declare_default(ctx.loan_id)
    ctx.refresh_loan()
    return ctx

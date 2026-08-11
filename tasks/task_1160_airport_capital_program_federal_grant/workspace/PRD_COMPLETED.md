# Airport AIP Grants API — Product Requirements Document

## 1. Introduction

Airports in the United States fund their capital development through the federal Airport Improvement Program, a reimbursement-based grant program in which a sponsor — typically a city, county, or airport authority — plans a multi-year capital improvement program, competes for federal discretionary and entitlement dollars, and then administers each awarded grant under strict federal oversight. The administrative burden is considerable: projects must be scored and ranked before funds are requested, sponsor assurances must be certified before an application can move, the federal, state, and local funding shares must be computed exactly, Disadvantaged Business Enterprise participation must be tracked and enforced during construction, every reimbursement request must pass a segregation-of-duties gauntlet, and the whole engagement terminates in a formal closeout audit with asset-disposal restrictions that can outlive the grant itself.

This API is the system of record for that entire lifecycle. It serves two broad communities: sponsor-side staff who plan programs, file applications, award contracts, and prepare drawdowns; and federal reviewers, compliance officers, finance officers, and auditors who accept, offer, certify, approve, and close. The business surface is mounted under the `/aip` path prefix, while two FAAManager-only operational capabilities outside that prefix govern the server's logical clock and a fiscal checkpoint batch; together they let the platform express statutory deadlines — a capital program expires if it is still unaccepted past the end of the calendar year preceding its fiscal year, and a grant application expires if it is still unsubmitted or in review past its May submission deadline — in fully deterministic, testable terms.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six roles, spelled exactly as follows: `FAAManager`, `SponsorStaff`, `ComplianceOfficer`, `FinanceOfficer`, `Auditor`, and `Contractor`. A request that omits either header, or presents a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Authentication is always evaluated before anything else; only after the caller is authenticated does the system check whether the role is permitted to invoke the requested endpoint, rejecting impermissible combinations with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `FAAManager`, `SponsorStaff`, `ComplianceOfficer`, `FinanceOfficer`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `created_by_user_id` on a GrantApplication, as `certified_by_user_id` on a SponsorAssurance, or as `prepared_by_user_id` and `certified_by_user_id` on a ReimbursementRequest — but it does not compare it to any entity's `id` for ownership purposes. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting Contractor entity; ownership checks on any resource that references a Contractor compare the resource's foreign-key field to `X-User-ID`. Concretely, a contractor may file an invoice or a DBE participation report only against a contract whose `contractor_id` equals the presented `X-User-ID`; acting on another contractor's contract is rejected with `ERR_FORBIDDEN` (HTTP 403). Because the comparison requires the referenced contract, the ownership check is evaluated only after that contract reference has resolved; an unresolvable reference yields `ERR_NOT_FOUND` (HTTP 404) before any ownership comparison.

Role capabilities in brief: a `FAAManager` is the federal program manager — registering sponsors, accepting capital programs, returning and offering applications, waiving assurances, approving amendments, approving and returning drawdowns, approving closeouts and disposals, and driving the logical clock and checkpoint batch. A `SponsorStaff` member builds the capital program, applies for grants, registers facilities and contractors, awards contracts, verifies invoices, plans construction phases, and requests closeouts and disposals. A `ComplianceOfficer` certifies assurances and drawdowns, adjudicates DBE reports, and resolves audit findings. A `FinanceOfficer` prepares and submits reimbursement requests. An `Auditor` opens closeout audits and records findings. A `Contractor` files invoices and DBE reports against its own contracts. All six roles may invoke every read endpoint.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

Requests to undefined paths, or to defined paths with an unsupported method, are answered through the same error envelope with `error_id` `ERR_NOT_FOUND`. A malformed or non-JSON request body is treated as an empty object, so any required-field failures surface as `ERR_VALIDATION`. An unexpected internal failure is answered with `error_id` `ERR_INTERNAL` and HTTP 500.

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-numeric `limit` or `offset` is ignored and the corresponding default applies; numeric values outside the permitted range are clamped rather than rejected — `limit` is clamped into [1, 100] and a negative `offset` is clamped to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Federal Fiscal Calendar

The server maintains a logical clock that governs every time-sensitive rule in the system: submission deadlines, program and application expiry, phase activation windows, and asset service-credit accrual all read this clock and never the wall clock. Before it is ever set, the clock reads exactly 2026-05-01T00:00:00Z. A `FAAManager` may advance it through a test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`, which echoes the supplied `to_iso8601` string verbatim; once set, the clock holds the supplied value and never falls back to wall-clock time.

The federal fiscal calendar is anchored on each CapitalProgram's `fiscal_year`. A grant application drawing on a program for a given fiscal year carries a `submission_deadline` of May 15 at 23:59:59 UTC of the preceding year; an application still in `DRAFT`, `UNDER_REVIEW`, or `RETURNED` once the clock passes that instant is moved to `EXPIRED`. A capital program still in `DRAFT`, `SUBMITTED`, or `AMENDMENT_DRAFT` once the clock passes December 31 at 23:59:59 UTC of the year preceding its `fiscal_year` is likewise moved to `EXPIRED`, and every child project still in `PROPOSED`, `SELECTED`, or `DEFERRED` is dropped with it. Neither expiry happens lazily on read: both are executed by a checkpoint batch capability, invoked by a `FAAManager`, which also recomputes the service credits of in-service grant assets against the current clock and reports the counts `applications_expired`, `programs_expired`, and `assets_recomputed`.

### 2.5. Common Resource Properties and Identifiers

All primary resources in the system — Sponsors, AirfieldFacilities, CapitalPrograms, CIPProjects, GrantApplications, Grants, GrantAmendments, Contractors, Contracts, Invoices, ReimbursementRequests, GrantAssets, and ConstructionPhases — share a standard set of system-managed fields:

- **`id` (string):** a unique, server-generated identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-05-01T00:00:00.000Z`) recording when the resource was created. Resource timestamps are drawn from the server's logical clock through a monotonic generator that never issues a value earlier than one already issued (advancing by one millisecond when necessary), so `created_at` and `updated_at` order consistently with the logical clock rather than the wall clock.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource, including mutations that only recompute derived fields.
- **`version` (integer):** a system-managed integer that starts at 1 when the resource is created and increments by one with every modification to the resource, serving as the basis for optimistic concurrency control.

Three subordinate record types are deliberately leaner. A SponsorAssurance, a DBEReport, and an AuditFinding each carry only `id` and `created_at`; both `updated_at` and `version` are absent from these resources, since each is written once and then transitioned to a terminal outcome.

Business identifiers are distinct from resource `id` values. A Grant additionally carries a system-minted `grant_number` of the form AIP-<loc_id>-<fiscal_year>-<seq>, composed from the sponsor's location identifier, the program's fiscal year, and a sequence number.

### 2.6. Monetary Precision and Rounding Discipline

Every dollar amount in the system — budgets, obligations, drawdowns, invoice amounts, retainage, payback figures, share estimates — is handled with fixed precision to prevent floating-point drift.

- **Internal calculations** involving monetary values are performed using decimal arithmetic.
- **Final stored values** are rounded to exactly 2 decimal places using the round-half-up method, and this applies equally to intermediate per-line amounts where a calculation pins line-level rounding (as the drawdown federal-share calculation does).
- **API representation:** monetary values in response bodies are standard JSON numbers, not strings, with at most 2 decimal places.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and exactly two. Creating a grant amendment against a grant requires the request to carry `expected_grant_version`, a non-optional field holding the `version` of the grant the client last observed; if that value does not equal the grant's current `version` — for instance because another writer has since created an amendment or otherwise advanced the grant — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Applying project selection to a capital program likewise requires a non-optional `expected_program_version` matching the program's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). A selection apply is exactly the kind of operation this guard exists for: it recomputes every project's scores and rank and legitimately supersedes the prior selection outcome, so a client holding a stale view of the program must be refused rather than allowed to overwrite decisions it has not observed. No other endpoint accepts a version field; clients must not send one elsewhere.

### 2.8. Cascading State Reconciliation Across the Program Hierarchy

State changes in this system rarely stay on the resource that received the request. When a capital program expires, every child project still in a live status is dropped with it. When a selection sweep runs, every non-dropped project's scores and rank are recomputed and child statuses are rewritten across the program. When a project falls out of selection or is dropped, draft applications that referenced it are scrubbed and their totals recomputed. When a new grant amendment is created, any still-pending predecessor amendment is superseded. When a DBE report is adjudicated, the ruling cascades from the report to the contract's posture and then to every affected invoice and the contract's invoice ledger. When a grant closeout is approved, the settlement cascades from the grant to its contracts, then to those contracts' invoices, releasing retainage and crediting the sponsor's entitlement ledger. Each of these cascades is atomic with its triggering operation, and every entity mutated along the way — parent or child — has its `updated_at` refreshed and its `version` incremented where it carries one.

### 2.9. Nested Resource Retrieval and Validation Order

For any request whose path or payload references other resources, the system resolves references in a fixed order. Path identifiers are validated left to right: the first identifier that does not correspond to an existing resource aborts the request with `ERR_NOT_FOUND` (HTTP 404), and the error message names the entity type that failed to resolve. Foreign-key references supplied in a request body are then resolved the same way; an unresolvable body reference is likewise `ERR_NOT_FOUND`.

Across the whole request lifecycle, checks are evaluated in a strict priority order, and an earlier failure always masks later ones. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of path and body references (`ERR_NOT_FOUND`), then state preconditions for the requested transition (generic failures carry `ERR_INVALID_STATE`, HTTP 409, while specific ones carry their dedicated codes), then field-level and business rules — range checks, uniqueness checks, and missing-required-field failures on creation endpoints surface as `ERR_VALIDATION` (HTTP 422) — and finally, on the two concurrency-guarded writes named in §2.7, the stale-version check (`ERR_STALE_VERSION`) is evaluated last. The subsections of §3 state the exact in-endpoint ordering wherever several business rules guard the same operation.

### 2.10. Segregation of Duties

Two certification steps in the lifecycle are protected by segregation of duties, compared on the `X-User-ID` header value. The compliance officer who certifies a sponsor assurance must not be the sponsor staff member who created the parent application: the certifier's `X-User-ID` is compared against the application's `created_by_user_id`, and a match is rejected with `ERR_SOD_VIOLATION` (HTTP 403). The compliance officer who certifies a reimbursement request must not be the finance officer who prepared it: the certifier's `X-User-ID` is compared against the request's `prepared_by_user_id`, and a match is likewise `ERR_SOD_VIOLATION` (HTTP 403). Because the comparison is on operator identifiers, the same individual must never occupy both sides of either control, regardless of role.

## 3. Business Logic & Workflows

### 3.1. Sponsors, Airfield Facilities, and the Capital Improvement Program

Everything begins with sponsor registration, a `FAAManager` operation. A sponsor is registered with its legal `sponsor_name`, a `loc_id` that must be exactly three uppercase letters drawn from A through Z and unique across all sponsors, an `airport_size_tier` of `LARGE_HUB`, `MEDIUM_HUB`, `SMALL_HUB`, or `NONHUB` — the tier that later drives the federal share percentage on every grant — and an `npe_entitlement_total` recording the sponsor's total non-primary entitlement apportionment in dollars, which must be zero or greater. Violations of these field constraints are rejected with `ERR_VALIDATION` (HTTP 422). A sponsor's `status` is always `ACTIVE`; sponsors are never deactivated. Alongside the entitlement total, the sponsor record continuously exposes `npe_entitlement_available`, maintained as a running ledger that starts equal to `npe_entitlement_total`: obligations consume the balance as grants are accepted (debited by the grant's `entitlement_portion`) and amended (debited by the amendment's `federal_delta`), and closeout credits back only the entitlement share of the released obligation — the smaller of the released amount and the grant's `entitlement_portion`, as pinned in §3.9 — so entitlement-funded dollars actually drawn by a closed grant remain consumed. For any sponsor whose grants are all non-`CLOSED`, this equals `npe_entitlement_total` minus the sum of `entitlement_portion` over those grants.

Sponsor staff then register the airfield facilities their programs will touch. Each facility is created with the owning `sponsor_id`, a `facility_name` such as "Runway 09/27" or "Taxiway B", and a `facility_type` of `RUNWAY`, `TAXIWAY`, or `APRON`.

With a sponsor in place, a `SponsorStaff` member opens a capital improvement program for a given federal fiscal year by supplying `sponsor_id` and `fiscal_year`. The fiscal year must fall within 2026 through 2035 and be unique per sponsor; violations are `ERR_VALIDATION`. A new program starts in `DRAFT` with its `selection_budget` at 0, where it remains until the first selection sweep stores a real budget ceiling, and its `selected_total_cost` — the sum of `estimated_cost` over its child projects currently in `SELECTED` — starts at zero as well.

The program lifecycle is cyclic. Submitting a program moves it from `DRAFT` to `SUBMITTED` and is performed by `SponsorStaff`; the submission is refused with `ERR_PROGRAM_EMPTY` (HTTP 422) when the program has no child project in `PROPOSED`, `SELECTED`, or `DEFERRED`. A `FAAManager` then accepts a submitted program, moving `SUBMITTED` to `ACCEPTED`. Only an `ACCEPTED` program supports selection sweeps and grant applications. When the sponsor needs to revise an accepted program, beginning an amendment moves `ACCEPTED` to `AMENDMENT_DRAFT`; projects may be added to a program only while it is in `DRAFT` or `AMENDMENT_DRAFT`, and attempts against a program in any other status are rejected as an invalid state (`ERR_INVALID_STATE`, HTTP 409). Resubmitting from `AMENDMENT_DRAFT` returns the program to `SUBMITTED` under the same non-empty precondition — `ERR_PROGRAM_EMPTY` applies identically — and the accept step may then take it to `ACCEPTED` again. Every one of these transitions increments the program's `version` by exactly one. Finally, the checkpoint batch described in §2.4 expires a program that has lingered in `DRAFT`, `SUBMITTED`, or `AMENDMENT_DRAFT` past its statutory boundary, moving it to the terminal `EXPIRED` status and cascading every child project still in `PROPOSED`, `SELECTED`, or `DEFERRED` to `DROPPED`.

### 3.2. Project Scoring and the Selection Sweep

Within a program that is still in `DRAFT` or `AMENDMENT_DRAFT`, sponsor staff add candidate projects. Each project carries the parent `program_id`, a `title`, a `project_type` of `RUNWAY_SAFETY`, `CAPACITY`, `PRESERVATION`, `SECURITY`, `ENVIRONMENTAL`, or `NOISE`, an `estimated_cost` in dollars that must be greater than zero, and five sponsor-scored component scores — `safety_score`, `capacity_score`, `preservation_score`, `security_score`, and `environmental_score` — each an integer between 0 and 20 inclusive. Two boolean flags refine scoring: `runway_safety_noncompliant` marks a project that addresses a runway safety area noncompliance, and `multi_airport_system` marks one benefiting a multi-airport system; both default to false when omitted. Field-level violations are rejected with `ERR_VALIDATION`. A new project starts in `PROPOSED`, and its three computed scores — `priority_score_sponsor`, `priority_score_federal`, and `selection_rank` — remain null until the first selection sweep runs.

The selection sweep is the heart of capital planning, and it is guarded by optimistic concurrency: the applying request must carry both the new `selection_budget` and an `expected_program_version` equal to the program's current `version`, with a stale view refused as described in §2.7. The sweep requires the program to be `ACCEPTED`. It recomputes both priority-score variants for every child project not in `DROPPED`, then ranks and selects.

The sponsor variant rewards local priorities. Its base score is a weighted sum of the five components — thirty percent of the effective safety component, twenty percent of `preservation_score`, twenty percent of `capacity_score`, fifteen percent of `security_score`, and fifteen percent of `environmental_score`, the five weights summing to one — where the effective safety component is the raw `safety_score` doubled when `runway_safety_noncompliant` is true and taken as-is otherwise. A flat five-point bonus is added when `multi_airport_system` is true. The result is rounded half-up to two decimal places and then capped at 100: a project whose raw total exceeds the cap records exactly 100 as its `priority_score_sponsor`.

The federal variant reflects national review priorities and is reported on the project record for federal evaluation. Its base uses a different weighting — forty percent of `safety_score`, twenty-five percent of `capacity_score`, fifteen percent of `preservation_score`, ten percent of `security_score`, and ten percent of `environmental_score` — grants no multi-airport bonus, and instead subtracts a ten-point penalty when `runway_safety_noncompliant` is true. The result is rounded half-up to two decimal places and floored at zero: a penalized score below zero records exactly 0 as its `priority_score_federal`.

Ranking follows the sponsor variant only: projects are ordered by `priority_score_sponsor` descending, with ties broken by `created_at` ascending — never by identifier — producing each project's `selection_rank`. Selection then proceeds as a prefix sweep over that ranking: a project becomes `SELECTED` exactly when its own `estimated_cost`, added to the cumulative `estimated_cost` of all projects ranked above it, does not exceed `selection_budget`; a project that would breach the ceiling becomes `DEFERRED`, as does everything ranked below the first breach. The sweep stores the applied `selection_budget` on the program, recomputes `selected_total_cost`, rewrites every affected project's status, and increments the program's `version` by one. Because the sweep is repeatable, a later application with a larger budget moves formerly `DEFERRED` projects back to `SELECTED`, while a smaller budget moves `SELECTED` projects to `DEFERRED`; in the latter case, any grant application still in `DRAFT` whose `project_ids` contained a project that fell out of selection has that project removed from its list and its `total_eligible_cost` recomputed.

A project may also be dropped outright by `SponsorStaff`. Dropping from `PROPOSED` carries no side effects; dropping from `DEFERRED` recomputes the program's `selected_total_cost`. Dropping from `SELECTED` is guarded, and the guards are evaluated in order: first, if any Contract references the project, the drop is rejected with `ERR_PROJECT_UNDER_CONTRACT` (HTTP 422); second, if any grant application in `UNDER_REVIEW` or `OFFERED` references the project, the drop is rejected with `ERR_PROJECT_IN_ACTIVE_APPLICATION` (HTTP 422). When the drop succeeds, every application in `DRAFT` or `RETURNED` that referenced the project has it removed from `project_ids` with `total_eligible_cost` recomputed, and the program's `selected_total_cost` is recomputed. `DROPPED` is terminal, and dropped projects are excluded from all future scoring sweeps.

### 3.3. From Application to Award: Assurances, Review, and the Grant Offer

Once a program is accepted and projects are selected, a `SponsorStaff` member files a grant application by naming the `sponsor_id`, the `program_id` it draws from, and a `project_ids` array. The array must contain at least one element and no duplicates — an empty or duplicate-bearing list is rejected with `ERR_EMPTY_SELECTION` (HTTP 422) — and every project named must belong to the referenced program. Whether each project's status is `SELECTED` is not examined at creation; that gate falls at submit time. Creation computes `total_eligible_cost` as the sum of `estimated_cost` over the listed projects, records the caller's `X-User-ID` as `created_by_user_id` (the segregation-of-duties anchor), and derives `submission_deadline` as May 15 at 23:59:59 UTC of the year preceding the referenced program's `fiscal_year`.

Creation also auto-generates the federal assurance checklist: exactly six SponsorAssurance children, one per `assurance_code` — `TITLE_VI`, `BUY_AMERICAN`, `DBE_PROGRAM`, `ENVIRONMENTAL_REVIEW`, `PREVAILING_WAGE`, and `AIRPORT_FEES` — each linked back through its `application_id` and each starting in `PENDING`. The application exposes `assurances_total`, always 6, and `assurances_cleared`, the count of its child assurances currently in `CERTIFIED` or `WAIVED`. A `ComplianceOfficer` certifies an assurance, moving it from `PENDING` to `CERTIFIED` with `certified_by_user_id` set — subject to the segregation-of-duties rule of §2.10, so an officer whose `X-User-ID` equals the application's `created_by_user_id` is refused with `ERR_SOD_VIOLATION` — and a `FAAManager` may instead waive one, moving it to `WAIVED`; either outcome triggers recomputation of the application's `assurances_cleared`.

Submitting the application — from `DRAFT`, or resubmitting from `RETURNED` — moves it to `UNDER_REVIEW` and enforces five checks, evaluated in this order: the referenced program must be `ACCEPTED` (otherwise `ERR_PROGRAM_NOT_ACCEPTED`, HTTP 409); the logical clock must not be past `submission_deadline` (otherwise `ERR_APPLICATION_DEADLINE_PASSED`, HTTP 422); `project_ids` must still be non-empty — every referenced project may have been dropped since creation — (otherwise `ERR_APPLICATION_EMPTY`, HTTP 422); every project in `project_ids` must currently be `SELECTED` (otherwise `ERR_PROJECT_NOT_SELECTED`, HTTP 422); and `assurances_cleared` must equal `assurances_total` (otherwise `ERR_ASSURANCES_INCOMPLETE`, HTTP 422). Both the initial submit and the resubmit apply the identical five-check sequence, and each successful submission increments the application's `version` by one. A `FAAManager` who finds an application deficient returns it, moving `UNDER_REVIEW` to `RETURNED` and incrementing `version`, which reopens the sponsor's correction loop.

When review succeeds, the `FAAManager` issues an offer. The offer computes the federal obligation as the sponsor's tier percentage of `total_eligible_cost`, rounded half-up to two decimal places, and it must fit the sponsor's purse: the obligation may not exceed `npe_entitlement_available` plus an optional `discretionary_amount` supplied with the offer, and a breach is rejected with `ERR_ENTITLEMENT_INSUFFICIENT` (HTTP 402). When supplied, `discretionary_amount` must be a number greater than or equal to zero; otherwise the offer is rejected with `ERR_VALIDATION` (HTTP 422). On success the application moves to `OFFERED`, carrying `offered_federal_obligated` at the computed obligation and `offered_entitlement_portion` at the smaller of that obligation and the sponsor's current `npe_entitlement_available` — the entitlement-funded share, with any remainder being discretionary.

The sponsor's answer is final. Accepting the offer re-verifies affordability at acceptance time: if the offered entitlement portion now exceeds the sponsor's `npe_entitlement_available` — because other grants have consumed it since the offer — acceptance is rejected with `ERR_ENTITLEMENT_INSUFFICIENT`. On success the application moves to the terminal `ACCEPTED` state, the Grant itself is created as described in §3.4, and the application's `created_grant_id` is set to the new grant's identifier; the endpoint responds `200 OK` with the updated application object (the created grant is retrievable via `created_grant_id`). Declining the offer instead moves the application to the terminal `DECLINED` state with no further effect. Independently of sponsor action, an application still in `DRAFT`, `UNDER_REVIEW`, or `RETURNED` when the checkpoint batch finds the clock past `submission_deadline` is moved to the terminal `EXPIRED` state.

### 3.4. The Grant Ledger: Funding Splits, Entitlements, and Amendments

Acceptance of an offer creates the Grant in `ACTIVE` status with `version` 1. The grant copies `sponsor_id` and `application_id` from the application, mints its `grant_number` in the AIP-<loc_id>-<fiscal_year>-<seq> format — where `<seq>` is a per-(`loc_id`, `fiscal_year`) counter starting at 1 for the first grant minted under that pair and incrementing by one for each subsequent grant — and fixes its `federal_share_pct` from the sponsor's tier: seventy-five percent for `LARGE_HUB`, eighty percent for `MEDIUM_HUB`, ninety percent for `SMALL_HUB`, and ninety-five percent for `NONHUB`. In API responses `federal_share_pct` is represented as a JSON-number fraction of 1 (that is, 0.75, 0.80, 0.90, or 0.95), the same representation used wherever the percentage enters a calculation. Its `total_budget` is set to the application's `total_eligible_cost`, and `federal_obligated` and `entitlement_portion` are carried over from the offer's computed values. Creation immediately debits the sponsor: `npe_entitlement_available` is reduced by `entitlement_portion`.

The grant's estimated non-federal funding comes from a strict waterfall evaluated in pinned order against `total_budget`. First, the federal share is the tier percentage of `total_budget`, rounded half-up to two decimal places — the same figure already obligated. Second, `state_share_estimated` is one half of the non-federal remainder — `total_budget` minus the federal share — rounded half-up to two decimal places. Third, `local_share_estimated` is whatever remains: `total_budget` minus the federal share minus the state estimate, an exact subtraction requiring no further rounding. The grant also tracks `federal_drawn`, beginning at 0, and `federal_available`, always the obligated amount minus the drawn amount.

Scope growth happens through grant amendments. A `SponsorStaff` member creates one against an `ACTIVE` grant by supplying `added_scope_cost` — strictly greater than zero — a free-text `reason`, and the concurrency guard `expected_grant_version` per §2.7. Creation runs the contingency-release calculation in its pinned order: the base is the grant's current `total_budget` plus `added_scope_cost`; the `new_total_budget` is that base divided by nine-tenths — that is, one minus the ten-percent contingency rate, so that the contingency lands at exactly ten percent of the new total — rounded half-up to two decimal places; the `contingency_amount` is then the new total minus the base; and the `federal_delta` is the grant's `federal_share_pct` applied to the increase of `new_total_budget` over the prior `total_budget`, rounded half-up to two decimal places. The new amendment starts in `PENDING`; if a prior amendment of the same grant is still `PENDING`, it is immediately moved to `SUPERSEDED`, and creating the amendment increments the grant's `version` by one.

A `FAAManager` then adjudicates the amendment. Approval is guarded by two checks in order: the grant must be `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`, HTTP 409), and the `federal_delta` must not exceed the sponsor's current `npe_entitlement_available` (otherwise `ERR_ENTITLEMENT_INSUFFICIENT`, HTTP 402). Approval sets the grant's `total_budget` to the amendment's `new_total_budget`, adds `federal_delta` to both `federal_obligated` and `entitlement_portion`, debits the sponsor's `npe_entitlement_available` by `federal_delta`, recomputes `state_share_estimated` and `local_share_estimated` through the same waterfall against the new total, and increments the grant's `version` by one. Rejection moves the amendment to `REJECTED` with no ledger effect. Both outcomes are terminal for the amendment.

### 3.5. Contractors, Contract Award, and Invoicing

Sponsor staff maintain the contractor roster. Registration records the owning `sponsor_id`, the legal `contractor_name`, and an optional `dbe_certified` flag, defaulting to false, that marks the contractor itself as a certified disadvantaged business. A contractor begins `REGISTERED`; suspension by `SponsorStaff` moves it to the terminal `SUSPENDED` status, and suspension blocks new awards — awarding a contract to a `SUSPENDED` contractor is rejected with `ERR_CONTRACTOR_SUSPENDED` (HTTP 422).

Awarding a contract is a `SponsorStaff` operation that binds a grant to a project and an awardee through `grant_id`, `cip_project_id`, and `contractor_id`, with commercial terms `awarded_value` (strictly greater than zero), `dbe_goal_pct` (a participation goal between 0 and 100 inclusive, expressed with two decimal places), and `retainage_pct` (the fraction withheld from each invoice, between 0 and 0.20 inclusive). Field violations are `ERR_VALIDATION`. Referential checks follow the field checks: the referenced contractor and project must belong to the same sponsor as the grant, and the project must be one of the source application's `project_ids` — a breach of either rule is `ERR_CROSS_SPONSOR_REFERENCE` (HTTP 422) — and then the contractor must be `REGISTERED`, with the suspension check last. A new contract starts in `AWARDED` with its `dbe_posture` at `UNEVALUATED`.

Three computed ledger fields track the contract's consumption. `invoiced_total` is the sum of `gross_amount` over the contract's invoices in `VERIFIED`, `INCLUDED`, or `PAID` status — submitted, rejected, and withheld invoices are all excluded, so a freshly filed invoice does not consume contract value until it is verified — and begins at 0. `remaining_value` is always `awarded_value` minus `invoiced_total`. `retainage_held` is the sum of `retainage_withheld` over invoices in `VERIFIED`, `INCLUDED`, or `PAID`, likewise beginning at 0 and released back to 0 when the contract closes.

Invoices are filed by the contractor itself: per §2.1, the caller's `X-User-ID` must equal the contract's `contractor_id`, and filing against another contractor's contract is `ERR_FORBIDDEN`. Each invoice names its `contract_id`, an `invoice_number` that must be unique within that contract, a free-form billing `period` label such as 2026-05, and a `gross_amount` strictly greater than zero; violations are `ERR_VALIDATION`. At filing, the retainage split is computed: `retainage_withheld` is the `gross_amount` multiplied by the contract's `retainage_pct`, rounded half-up to two decimal places, and `net_payable` is the exact remainder of `gross_amount` minus `retainage_withheld`. The invoice starts in `SUBMITTED`, and its `drawdown_id` stays null until a reimbursement request includes it.

Verification by `SponsorStaff` enforces three checks in order: the contract must still be `AWARDED` (a `CLOSED` contract yields `ERR_CONTRACT_CLOSED`, HTTP 409); the contract's grant must be `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`, HTTP 409); and the contract's current `invoiced_total` plus the invoice's `gross_amount` must not exceed `awarded_value`, with exact equality allowed (otherwise `ERR_INVOICE_EXCEEDS_CONTRACT_VALUE`, HTTP 402). A verified invoice moves from `SUBMITTED` to `VERIFIED`, its gross amount is confirmed into `invoiced_total` with `remaining_value` recomputed, and its `retainage_withheld` is added to `retainage_held`. Sponsor staff may instead reject a submitted invoice, moving it to the terminal `REJECTED` status with no ledger effect.

### 3.6. DBE Participation: Reporting, Adjudication, and Payment Withholding

Federal DBE goals are enforced contract by contract through periodic reporting. The contractor files each report against its own contract — again, `X-User-ID` must equal the contract's `contractor_id` — supplying the `contract_id`, a `reporting_period` label such as 2026-Q2 that must be unique per contract, the `dbe_paid_amount` actually paid to DBE subcontractors in the period (zero or greater), and the `total_paid_amount` paid to all subcontractors (strictly greater than zero and at least the DBE amount); violations are `ERR_VALIDATION`. Filing computes `achieved_dbe_pct` as `dbe_paid_amount` divided by `total_paid_amount`, multiplied by one hundred, and rounded half-up to two decimal places, and the report rests in `PENDING` awaiting adjudication.

A `ComplianceOfficer` adjudicates the report, but only while the contract is `AWARDED`; adjudicating against a `CLOSED` contract is rejected with `ERR_CONTRACT_CLOSED` (HTTP 409). The report's own state precondition comes first: only a `PENDING` report can be adjudicated at all (otherwise `ERR_INVALID_STATE`, HTTP 409), and only then is the contract's `AWARDED` gate evaluated. The decision compares the rounded `achieved_dbe_pct` against the contract's `dbe_goal_pct` on an inclusive boundary: meeting the goal exactly counts as attainment. When the rounded achievement is at least the goal, the report becomes `COMPLIANT`, the contract's `dbe_posture` is set to `COMPLIANT`, and the release cascade runs — every invoice of the contract currently in `WITHHELD` returns to `VERIFIED`, with `invoiced_total` and `remaining_value` recomputed accordingly. When the rounded achievement falls below the goal, the report becomes `SHORTFALL` and the withholding cascade runs in three steps: the contract's `dbe_posture` is set to `NON_COMPLIANT`; every invoice of the contract currently in `VERIFIED` is moved to `WITHHELD`; and for each withheld invoice the contract's `invoiced_total` decreases by that invoice's gross amount while `remaining_value` increases correspondingly. A withheld invoice is thereby fenced out of new drawdowns until a later compliant report releases it — the submission gate in §3.7 refuses drawdowns touching a `NON_COMPLIANT` contract.

### 3.7. Reimbursement Drawdowns

Drawdowns are how obligated federal dollars actually move. A `FinanceOfficer` prepares a reimbursement request by naming the `grant_id` and an `invoice_ids` array that must contain at least one element and no duplicates — an empty or duplicate-bearing list is `ERR_EMPTY_SELECTION` — and every listed invoice must currently be `VERIFIED` and belong to a contract of the named grant, otherwise the creation is rejected with `ERR_INVOICE_NOT_VERIFIABLE` (HTTP 422). On creation, each listed invoice moves from `VERIFIED` to `INCLUDED` and has its `drawdown_id` set to the new request's identifier; the request records the preparer's `X-User-ID` as `prepared_by_user_id` and starts in `DRAFT`.

Two totals are computed at creation. `total_net` is the plain sum of `net_payable` over the included invoices, already at two-decimal precision. `federal_amount` instead uses a pinned per-line rounding order: for each invoice, `net_payable` is multiplied by the grant's `federal_share_pct` and rounded half-up to two decimal places, and those rounded line amounts are then summed exactly. The alternative order — summing the nets first and rounding once — is explicitly rejected because it produces different cents; for example, three invoices with a net of 33333.33 each under a ninety-percent share yield 90000.00 under the pinned per-line order but 89999.99 under the rejected sum-first order.

Certification is the segregation-of-duties checkpoint of §2.10: a `ComplianceOfficer` certifies the draft request, moving it from `DRAFT` to `CERTIFIED` with `certified_by_user_id` recorded, and an officer whose `X-User-ID` equals `prepared_by_user_id` is refused with `ERR_SOD_VIOLATION` (HTTP 403). Submission is then the `FinanceOfficer`'s action, moving `CERTIFIED` to `SUBMITTED` under three checks evaluated in order: the grant must be `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`); every included invoice must still be `INCLUDED` and no included invoice's contract may carry a `dbe_posture` of `NON_COMPLIANT` (otherwise `ERR_PAYMENTS_WITHHELD_DBE`, HTTP 422); and the request's `federal_amount` must not exceed the grant's `federal_available`, with exact equality allowed (otherwise `ERR_FEDERAL_FUNDS_INSUFFICIENT`, HTTP 402).

Approval rests with the `FAAManager`, who re-applies the same two fiscal gates in order — grant `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`) and `federal_amount` within `federal_available` (otherwise `ERR_FEDERAL_FUNDS_INSUFFICIENT`) — before funds move. On approval the request reaches its terminal `APPROVED` status, the grant's `federal_drawn` increases by `federal_amount` with `federal_available` recomputed, every included invoice moves from `INCLUDED` to `PAID`, and the grant's `version` increments by one. Alternatively, the `FAAManager` may return a submitted request for correction: the request moves back from `SUBMITTED` to `DRAFT`, and its `certified_by_user_id` is cleared to null, forcing re-certification before it can be submitted again.

### 3.8. Construction Phasing and Operations Continuity

Grant-funded construction must be phased so the airfield keeps operating. A `SponsorStaff` member plans a construction phase by supplying `grant_id`, `cip_project_id`, `facility_id`, `contractor_id`, a `closure_type` of `FULL_CLOSURE` or `NIGHT_ONLY`, and the half-open window bounds `start_utc` and `end_utc`, where the start is inclusive and the end exclusive. Creation enforces its checks in a fixed order after reference existence: the closure-duration safety limits — a `FULL_CLOSURE` phase may span at most 72 hours and a `NIGHT_ONLY` phase at most 8 hours, with longer windows rejected as `ERR_CLOSURE_DURATION_EXCEEDED` (HTTP 422); window validity — `end_utc` must be strictly after `start_utc`, otherwise `ERR_PHASE_WINDOW_INVALID` (HTTP 422); facility overlap — a `FULL_CLOSURE` phase must not overlap any other `FULL_CLOSURE` phase on the same facility that is in `PLANNED` or `ACTIVE`, compared under half-open interval semantics so that pure adjacency, one phase's `end_utc` equaling another's `start_utc`, is allowed, with a true overlap rejected as `ERR_FACILITY_OVERLAP` (HTTP 409); contractor rest buffer — any two phases sharing the same `contractor_id` must leave at least a 24-hour buffer between their windows in either direction, with a gap of exactly 24 hours permitted and anything shorter rejected as `ERR_CONTRACTOR_BUFFER_CONFLICT` (HTTP 409); like the overlap check, this buffer is evaluated only against existing phases in `PLANNED` or `ACTIVE`, so completed and cancelled phases impose no buffer; and finally cross-sponsor integrity — the referenced facility, contractor, and project must all belong to the same sponsor as the grant, otherwise `ERR_CROSS_SPONSOR_REFERENCE` (HTTP 422).

A planned phase begins `PLANNED`. Activation by `SponsorStaff` moves `PLANNED` to `ACTIVE` under two checks: the funding grant must be `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`) and the logical clock must sit inside the window — at or after `start_utc` and strictly before `end_utc` — otherwise `ERR_PHASE_OUTSIDE_WINDOW` (HTTP 422). Completion moves `ACTIVE` to the terminal `COMPLETED`, and cancellation moves a phase from either `PLANNED` or `ACTIVE` to the terminal `CANCELLED`. Open phases gate closeout: any phase still `PLANNED` or `ACTIVE` blocks the closeout request described in §3.9.

### 3.9. Closeout, Audit, and Asset Disposition

Closeout unwinds the grant in three acts. A `SponsorStaff` member first requests closeout, moving the grant from `ACTIVE` to `CLOSEOUT_REQUESTED` and incrementing its `version`, but only when two ledgers are quiet — no reimbursement request of the grant may remain in `DRAFT`, `CERTIFIED`, or `SUBMITTED`, and no construction phase of the grant may remain in `PLANNED` or `ACTIVE` — with either blockage rejected as `ERR_CLOSEOUT_BLOCKED` (HTTP 422). An `Auditor` then opens the audit, moving `CLOSEOUT_REQUESTED` to `UNDER_AUDIT` and incrementing `version` again.

During the audit, the `Auditor` records findings against the audited grant, each carrying `grant_id`, a `finding_code` of `INELIGIBLE_COST`, `MISSING_DOCUMENTATION`, `DBE_SHORTFALL`, `PROCUREMENT`, or `OTHER`, a `severity` of `LOW`, `MEDIUM`, or `HIGH`, and a narrative `description`; findings may only be recorded while the grant is `UNDER_AUDIT`. Each finding starts `OPEN`, and a `ComplianceOfficer` resolves findings — again only while the grant is `UNDER_AUDIT`, with attempts against a grant in any other status rejected as `ERR_INVALID_STATE` (HTTP 409) — moving them to the terminal `RESOLVED`.

Approval of the closeout is the `FAAManager`'s final fiscal act on the grant, guarded by two checks: zero audit findings may remain `OPEN` and zero grant assets may remain in `DISPOSAL_REQUESTED`, with either blockage rejected as `ERR_CLOSEOUT_BLOCKED`. Approval runs the final settlement, which replays the grant's federal ledger in the chronological order of its approved drawdowns (approval order, ties broken by creation time): the final federal figure is exactly `federal_drawn`; the released amount is `federal_obligated` minus `federal_drawn`, never negative by construction; `federal_obligated` is then reduced to `federal_drawn`, de-obligating the unused balance; and the sponsor's `npe_entitlement_available` is credited with the entitlement portion of the release — the smaller of the released amount and the grant's `entitlement_portion`. The closeout cascade then runs three levels deep: every child contract still `AWARDED` moves to `CLOSED` with its `retainage_held` released to 0; every invoice of those contracts still in `VERIFIED` or `WITHHELD` moves to `PAID`, with those payments treated as sponsor-local obligations — they are not added to `federal_drawn`; and every grant asset still `IN_SERVICE` has its service credit and restricted value recomputed against the current clock. The grant's `version` increments, the grant reaches the terminal `CLOSED` status, and because `npe_entitlement_available` counts only non-`CLOSED` grants, the closed grant's remaining `entitlement_portion` stops burdening the sponsor's entitlement ledger from that moment.

Assets acquired with grant funds carry federal restrictions throughout their useful life. Sponsor staff register each asset with its `grant_id`, an `asset_kind` of `EQUIPMENT` or `LAND` that selects the disposal-payback variant, a `description`, the `acquisition_federal_share` in federal dollars embedded in the acquisition (strictly greater than zero), the `useful_life_years` federal useful life (an integer from 1 to 50), and the `in_service_date` on which the asset entered service; field violations are `ERR_VALIDATION`. Two computed values track the restriction and are refreshed against the logical clock at registration, at every checkpoint, at disposal request, and at closeout: elapsed service is the whole days between `in_service_date` and the clock, divided by 365 and rounded down to whole years, capped at `useful_life_years` and floored at zero (an `in_service_date` at or after the clock yields elapsed service of 0); `service_credit_value` is `acquisition_federal_share` prorated by elapsed years over `useful_life_years`, rounded half-up to two decimal places; and `remaining_restricted_value` is the exact remainder of `acquisition_federal_share` minus `service_credit_value`.

Disposal begins when `SponsorStaff` request it, moving the asset from `IN_SERVICE` to `DISPOSAL_REQUESTED` and recomputing both credit values at the clock. A `FAAManager` then approves the disposal, with one payload rule: for a `LAND` asset the request must carry a `fair_market_value`, and its absence is rejected with `ERR_FMV_REQUIRED` (HTTP 422). Whenever `fair_market_value` is supplied — for either asset kind — it must be a number greater than or equal to zero, otherwise `ERR_VALIDATION` (HTTP 422); for an `EQUIPMENT` asset a supplied value is validated but ignored by the payback calculation. Approval fixes `payback_due` by variant and zeroes `remaining_restricted_value` as the asset moves to the terminal `DISPOSED`. For `EQUIPMENT`, the straight-line variant sets `payback_due` to `acquisition_federal_share` prorated by the remaining years over `useful_life_years`, rounded half-up to two decimal places — book-value amortization of the original federal share. For `LAND`, the fair-market variant sets `payback_due` to the supplied `fair_market_value` multiplied by the grant's current `federal_share_pct` and prorated by the remaining years over `useful_life_years`, rounded half-up to two decimal places — so the payback tracks current market value rather than original cost whenever the two diverge. In both variants the remaining years are `useful_life_years` minus the capped elapsed years, and once no useful life remains the payback is exactly 0.00. A sponsor that thinks better of a pending disposal instead returns the asset to service, moving `DISPOSAL_REQUESTED` back to `IN_SERVICE`; `payback_due` stays 0 and the federal restriction simply continues to run.

## 4. Endpoint Definitions

Operations that create new resources — a sponsor, facility, program, project, application, amendment, contractor, contract, DBE report, invoice, reimbursement request, audit finding, asset, or construction phase — return a `201 Created` status code. Operations that modify an existing resource's state, and the two operational endpoints, return a `200 OK` status code. All list endpoints accept the `limit` and `offset` pagination parameters of §2.3, plus the optional filters named in their descriptions.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a supplied `to_iso8601` instant | FAAManager |
| POST | `/_ops/run_checkpoint` | Run the fiscal checkpoint batch: expire applications and programs past their deadlines, recompute asset service credits | FAAManager |
| POST | `/aip/sponsors` | Register an airport sponsor | FAAManager |
| GET | `/aip/sponsors` | List sponsors | All roles |
| GET | `/aip/sponsors/{sponsorId}` | Get one sponsor, including computed `npe_entitlement_available` | All roles |
| POST | `/aip/facilities` | Register an airfield facility for a sponsor | SponsorStaff |
| GET | `/aip/facilities` | List facilities; optional filters `sponsor_id`, `facility_type` | All roles |
| GET | `/aip/facilities/{facilityId}` | Get one facility | All roles |
| POST | `/aip/capital-programs` | Create a capital improvement program for a sponsor and fiscal year | SponsorStaff |
| GET | `/aip/capital-programs` | List programs; optional filters `sponsor_id`, `status` | All roles |
| GET | `/aip/capital-programs/{programId}` | Get one program | All roles |
| POST | `/aip/capital-programs/{programId}/submit` | Submit a program (from `DRAFT` or `AMENDMENT_DRAFT`) for federal acceptance | SponsorStaff |
| POST | `/aip/capital-programs/{programId}/accept` | FAA accepts a submitted program | FAAManager |
| POST | `/aip/capital-programs/{programId}/begin-amendment` | Open an amendment cycle on an accepted program | SponsorStaff |
| POST | `/aip/capital-programs/{programId}/apply-selection` | Recompute both score variants, rank projects, and sweep selection against a budget (OCC-guarded) | SponsorStaff |
| POST | `/aip/cip-projects` | Add a project to a program in `DRAFT` or `AMENDMENT_DRAFT` | SponsorStaff |
| GET | `/aip/cip-projects` | List projects; optional filters `program_id`, `status` | All roles |
| GET | `/aip/cip-projects/{projectId}` | Get one project, including both score variants and rank | All roles |
| POST | `/aip/cip-projects/{projectId}/drop` | Drop a project from the program | SponsorStaff |
| POST | `/aip/grant-applications` | Create a grant application from CIP projects; auto-creates the six assurances | SponsorStaff |
| GET | `/aip/grant-applications` | List applications; optional filters `sponsor_id`, `program_id`, `status` | All roles |
| GET | `/aip/grant-applications/{applicationId}` | Get one application | All roles |
| GET | `/aip/grant-applications/{id}/assurances` | List the application's assurance checklist | All roles |
| POST | `/aip/grant-applications/{applicationId}/submit` | Submit (or resubmit from `RETURNED`) an application for federal review | SponsorStaff |
| POST | `/aip/grant-applications/{applicationId}/return` | FAA returns an application for correction | FAAManager |
| POST | `/aip/grant-applications/{applicationId}/offer` | FAA issues a grant offer with computed obligation and entitlement split | FAAManager |
| POST | `/aip/grant-applications/{applicationId}/accept-offer` | Sponsor accepts the offer; creates the grant in `ACTIVE` | SponsorStaff |
| POST | `/aip/grant-applications/{applicationId}/decline-offer` | Sponsor declines the offer | SponsorStaff |
| POST | `/aip/sponsor-assurances/{assuranceId}/certify` | Compliance officer certifies an assurance (cannot certify own application) | ComplianceOfficer |
| POST | `/aip/sponsor-assurances/{assuranceId}/waive` | FAA waives an assurance | FAAManager |
| GET | `/aip/grants` | List grants; optional filters `sponsor_id`, `application_id`, `status` | All roles |
| GET | `/aip/grants/{grantId}` | Get one grant, including drawn and available balances | All roles |
| POST | `/aip/grants/{grantId}/request-closeout` | Sponsor initiates grant closeout | SponsorStaff |
| POST | `/aip/grants/{grantId}/begin-audit` | Auditor opens the closeout audit | Auditor |
| POST | `/aip/grants/{grantId}/approve-closeout` | FAA approves closeout: final settlement, contract and invoice cascade, entitlement release | FAAManager |
| POST | `/aip/grants/{grantId}/amendments` | Create a grant amendment (OCC-guarded; supersedes any pending amendment) | SponsorStaff |
| GET | `/aip/grants/{id}/amendments` | List amendments of a grant | All roles |
| POST | `/aip/grant-amendments/{amendmentId}/approve` | FAA approves an amendment: budget and obligation grow | FAAManager |
| POST | `/aip/grant-amendments/{amendmentId}/reject` | FAA rejects an amendment | FAAManager |
| POST | `/aip/contractors` | Register a contractor under a sponsor | SponsorStaff |
| GET | `/aip/contractors` | List contractors; optional filter `sponsor_id` | All roles |
| GET | `/aip/contractors/{contractorId}` | Get one contractor | All roles |
| POST | `/aip/contractors/{contractorId}/suspend` | Suspend a contractor, blocking new awards | SponsorStaff |
| POST | `/aip/contracts` | Award a contract under a grant for a project to a contractor | SponsorStaff |
| GET | `/aip/contracts` | List contracts; optional filters `grant_id`, `contractor_id`, `cip_project_id` | All roles |
| GET | `/aip/contracts/{contractId}` | Get one contract, including invoiced, remaining, retainage, and DBE posture | All roles |
| POST | `/aip/dbe-reports` | Contractor files a DBE participation report for its own contract | Contractor |
| GET | `/aip/contracts/{id}/dbe-reports` | List DBE reports of a contract | All roles |
| POST | `/aip/dbe-reports/{reportId}/adjudicate` | Compliance officer adjudicates: attainment releases, shortfall withholds | ComplianceOfficer |
| POST | `/aip/invoices` | Contractor submits an invoice against its own contract | Contractor |
| GET | `/aip/invoices` | List invoices; optional filters `contract_id`, `drawdown_id`, `status` | All roles |
| GET | `/aip/invoices/{invoiceId}` | Get one invoice | All roles |
| POST | `/aip/invoices/{invoiceId}/verify` | Sponsor staff verifies a submitted invoice (contract-value cap enforced) | SponsorStaff |
| POST | `/aip/invoices/{invoiceId}/reject` | Sponsor staff rejects a submitted invoice | SponsorStaff |
| POST | `/aip/reimbursement-requests` | Finance officer prepares a drawdown over verified invoices (per-line federal rounding) | FinanceOfficer |
| GET | `/aip/reimbursement-requests` | List drawdowns; optional filters `grant_id`, `status` | All roles |
| GET | `/aip/reimbursement-requests/{requestId}` | Get one drawdown | All roles |
| POST | `/aip/reimbursement-requests/{requestId}/certify` | Compliance officer certifies the drawdown (certifier differs from preparer) | ComplianceOfficer |
| POST | `/aip/reimbursement-requests/{requestId}/submit` | Finance officer submits a certified drawdown to the FAA | FinanceOfficer |
| POST | `/aip/reimbursement-requests/{requestId}/approve` | FAA approves: federal funds move, invoices become paid | FAAManager |
| POST | `/aip/reimbursement-requests/{requestId}/return` | FAA returns a submitted drawdown for correction, back to `DRAFT` | FAAManager |
| POST | `/aip/audit-findings` | Auditor records a finding against a grant under audit | Auditor |
| GET | `/aip/grants/{id}/audit-findings` | List findings of a grant; optional filter `status` | All roles |
| POST | `/aip/audit-findings/{findingId}/resolve` | Compliance officer resolves an open finding | ComplianceOfficer |
| POST | `/aip/grant-assets` | Register an asset acquired with grant funds | SponsorStaff |
| GET | `/aip/grants/{id}/assets` | List assets of a grant; optional filter `status` | All roles |
| POST | `/aip/grant-assets/{assetId}/request-disposal` | Sponsor requests disposal of an asset | SponsorStaff |
| POST | `/aip/grant-assets/{assetId}/approve-disposal` | FAA approves disposal and fixes payback per the asset-kind variant | FAAManager |
| POST | `/aip/grant-assets/{assetId}/return-to-service` | Cancel a disposal request and keep the asset in service | SponsorStaff |
| POST | `/aip/construction-phases` | Plan a construction phase with closure-type, overlap, and contractor-buffer checks | SponsorStaff |
| GET | `/aip/construction-phases` | List phases; optional filters `grant_id`, `facility_id`, `contractor_id`, `cip_project_id`, `closure_type` | All roles |
| GET | `/aip/construction-phases/{phaseId}` | Get one phase | All roles |
| POST | `/aip/construction-phases/{phaseId}/activate` | Activate a planned phase (grant active, clock inside the window) | SponsorStaff |
| POST | `/aip/construction-phases/{phaseId}/complete` | Complete an active phase | SponsorStaff |
| POST | `/aip/construction-phases/{phaseId}/cancel` | Cancel a planned or active phase | SponsorStaff |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROGRAM_EMPTY` | 422 Unprocessable Entity |
| `ERR_PROGRAM_NOT_ACCEPTED` | 409 Conflict |
| `ERR_APPLICATION_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_APPLICATION_EMPTY` | 422 Unprocessable Entity |
| `ERR_PROJECT_NOT_SELECTED` | 422 Unprocessable Entity |
| `ERR_ASSURANCES_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_ENTITLEMENT_INSUFFICIENT` | 402 Payment Required |
| `ERR_CLOSURE_DURATION_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PHASE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_PHASE_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_FACILITY_OVERLAP` | 409 Conflict |
| `ERR_CONTRACTOR_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_CROSS_SPONSOR_REFERENCE` | 422 Unprocessable Entity |
| `ERR_CONTRACTOR_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_VERIFIABLE` | 422 Unprocessable Entity |
| `ERR_INVOICE_EXCEEDS_CONTRACT_VALUE` | 402 Payment Required |
| `ERR_CONTRACT_CLOSED` | 409 Conflict |
| `ERR_GRANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PAYMENTS_WITHHELD_DBE` | 422 Unprocessable Entity |
| `ERR_FEDERAL_FUNDS_INSUFFICIENT` | 402 Payment Required |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_CLOSEOUT_BLOCKED` | 422 Unprocessable Entity |
| `ERR_FMV_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PROJECT_UNDER_CONTRACT` | 422 Unprocessable Entity |
| `ERR_PROJECT_IN_ACTIVE_APPLICATION` | 422 Unprocessable Entity |
| `ERR_EMPTY_SELECTION` | 422 Unprocessable Entity |

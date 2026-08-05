# Lead & Healthy-Homes Program API — Product Requirements Document

## 1. Introduction

Childhood lead poisoning is preventable, yet it remains one of the most persistent environmental-health burdens in older housing stock. This API backs a public-health program that connects the clinical thread — a child's blood-lead screening result — to the environmental thread — the investigation, hazard-control order, remediation, and clearance of the dwelling where the exposure occurred. The program's operators need a single system of record that opens a case from a qualifying blood-lead test, dispatches an environmental investigation, issues an enforceable hazard-control order when hazards are found, funds the remediation through income-tiered grants, temporarily relocates families while interim controls are underway, and finally confirms with an independent clearance test that the dwelling is safe before the case is closed.

The domain is deliberately cross-disciplinary. A single case advances along two independent tracks at once: an environmental track that moves from intake through investigation and enforcement to closure, and a medical track that follows the child's blood-lead level as follow-up tests either de-escalate or rebound. Money is scarce and must be conserved: grant funds are reserved when a project is approved and reconciled when it completes, and every compensating cancellation must return the fund to exactly the balance it held before. Hazards are likewise conserved: a clearance pass moves a hazard from open to controlled, and an administrative void moves it back, but the total never changes. Because clearance is a life-safety determination, the program enforces a four-eyes rule — the inspector who found the hazards may never be the inspector who signs off that they are gone.

This document specifies the complete contract: the resources and their fields, the state machines that govern their lifecycles, the calculations that size subsidies and reimbursements, the validation rules and their precedence, and the REST endpoints that expose all of it. It is written for the engineers who will implement the service and the reviewers who will test it against a fixed suite; where a rule could be read two ways, the intent is stated explicitly so that every reader arrives at the same behavior.

## 2. Global Specifications & System-Wide Principles

All resources are mounted under the `/api/v1` prefix. The system is a set of flat, peer collections linked by foreign keys that travel in request bodies rather than in nested resource paths; relationships are discovered through filtered list endpoints and dedicated sub-resource reads.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is missing, or if `X-User-Role` is not one of the roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to invoke the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system defines exactly five roles, spelled precisely as follows:

- `IntakeCoordinator` — program staff who register children and dwellings, record blood-lead tests, and open cases.
- `CaseManager` — the owner of the case lifecycle: schedules investigations, issues and voids hazard-control orders, manages relocation, and proposes, approves, and cancels remediation projects.
- `Inspector` — the field risk-assessor who conducts investigations and signs independent clearance tests.
- `Contractor` — the RRP-certified firm that performs remediation and requests clearance.
- `ProgramAdmin` — the operator who manages inspectors, contractors, relocation units, and grant funds, produces reports, and drives the logical clock.

Two of these roles are **entity-backed**, meaning their `X-User-ID` is the `id` of a persisted record and is compared against ownership foreign keys. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector`; any operation whose target references an inspector compares that reference to `X-User-ID` — specifically, recording findings on and completing an investigation both require the acting inspector's `X-User-ID` to equal the investigation's `inspector_id`. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `Contractor`; requesting clearance on an order, and starting or completing a remediation project, all require the acting contractor's `X-User-ID` to equal the project's `contractor_id`. In both cases an ownership mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The remaining three roles — `IntakeCoordinator`, `CaseManager`, and `ProgramAdmin` — are **opaque**: their `X-User-ID` is an operator identifier not tied to any persisted entity. The server does not compare an opaque identifier to any record's `id`. One opaque identifier is nonetheless recorded: when an `Inspector` signs a clearance test the server copies that inspector's `X-User-ID` into `cleared_by_inspector_id`, but that field exists to enforce the four-eyes rule described in §2.9 and §3.5, not as a navigational foreign key.

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

### 2.3. Pagination

All list endpoints are paginated through two query parameters. The `limit` parameter controls the page size; it defaults to `10`, must be at least `1`, and may not exceed `100`. The `offset` parameter controls how many records are skipped before the page begins; it defaults to `0` and must be at least `0`. A `limit` outside the inclusive range from 1 to 100, or a negative `offset`, is a malformed request and is rejected with `ERR_VALIDATION` (HTTP 422).

List results are always returned in ascending order of `created_at` — that is, oldest first. The pagination fields `limit`, `offset`, `total_count`, and `has_more` are reported in the `meta` object of every list response: `total_count` is the number of records matching the query before pagination is applied, and `has_more` is true exactly when records remain beyond the current page.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id`, which is a UUID with no type prefix; clients never supply it. Most resources additionally carry three system-managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 on creation and increments by 1 on every mutation of the resource. `created_at` is fixed at creation and never changes; `updated_at` is refreshed on every mutation.

Two resources are exceptions that carry only `id` and `created_at` — they have neither an `updated_at` nor a `version`, because they are immutable audit records once written: `BloodLeadTest` and `ClearanceTest`. A recorded blood-lead test and a signed clearance test are never edited in place; their downstream effects live on the case and the order they touch, not on the test record itself.

### 2.5. Optimistic Concurrency Control on Grant Funds

Grant funds are a contended resource: many projects compete for a finite budget, and a client's view of a fund's `available_cents` can become stale the moment another project reserves against it. To prevent a client from overwriting a reservation it never observed, approving a remediation project is guarded by optimistic concurrency control on the `GrantFund`. The approve request must include `expected_grant_fund_version`, a non-optional field carrying the `version` of the target grant fund as the client last read it. If that value does not equal the fund's current `version`, the approval is rejected with `ERR_STALE_GRANT_VERSION` (HTTP 412), signaling that the fund has been mutated — another project has reserved against it, or a completion has finalized against it — since the client last read it, and that the client must re-read the fund and retry. A successful approval increments the fund's `version` by 1. No other endpoint accepts or requires a version field.

### 2.6. Precision, Rounding, and the Grant Ledger

All monetary quantities are stored and computed in integer **cents**; the fields `total_budget_cents`, `reserved_cents`, `spent_cents`, `available_cents`, `estimated_cost_cents`, `final_cost_cents`, `reimbursement_cents`, and each line item's `amount_cents` are whole numbers of cents with no sub-cent component. Where a calculation produces a fractional cent before it is stored (the subsidy and the relocation per-diem), the intermediate value is rounded half up to the nearest whole cent, as detailed in §3. Blood-lead levels are carried to one decimal place; hazard and dust-wipe measurements are compared exactly as submitted.

Each `GrantFund` maintains a three-way ledger. Its `available_cents` is always its `total_budget_cents` minus its `reserved_cents` minus its `spent_cents`. This partition is a conserved invariant: at every instant the sum of `available_cents`, `reserved_cents`, and `spent_cents` equals `total_budget_cents`. A forward reservation made at project approval and its compensating release made at cancellation must return `reserved_cents` and `available_cents` to exactly their pre-approval values, with no drift. Because approval is refused whenever the estimated subsidy would exceed `available_cents`, the available balance never needs to be floored and never goes negative.

### 2.7. The Logical Clock

Time in this system is a logical clock, not wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and it holds that value — never falling back to real time — until an operator advances it. A `ProgramAdmin` advances the clock by supplying a `to_iso8601` instant; the new value governs every time-dependent behavior: compliance deadlines, contractor certification expiry, and the `completed_at` and `issued_at` stamps written during investigation completion and order issuance. All server-stamped instants are drawn from this logical clock.

### 2.8. Validation Ordering and Error Precedence

When a single request could fail more than one check, the checks are evaluated in a fixed priority order and the first failure determines the response. The order is:

1. **Authentication** — headers present and `X-User-Role` a known role, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role is permitted for the endpoint, else `ERR_UNAUTHORIZED` (403).
3. **Body validity** — required fields present, enum values legal, numeric fields at least 0, `occupant_count` at least 1, and pagination bounds in range, else `ERR_VALIDATION` (422).
4. **Existence** — every path `id` and every foreign-key target in the body resolves to an existing resource, checked left to right in the order they appear; the first unresolved reference yields the matching `ERR_<RESOURCE>_NOT_FOUND` (404).
5. **Resource ownership** — for entity-backed actors, `X-User-ID` matches the target's ownership foreign key, else `ERR_NOT_RESOURCE_OWNER` (403).
6. **Four-eyes segregation** — on clearance, the signing inspector differs from the source investigation's inspector, else `ERR_SOD_CONFLICT` (409).
7. **State** — the target is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409).
8. **Grant-fund concurrency** — `expected_grant_fund_version` matches the fund's current `version`, else `ERR_STALE_GRANT_VERSION` (412).

Beyond this backbone, several domain checks carry their own priority relative to one another and to the checks above. Two orderings matter especially. First, on project approval a **state** failure (order not `ISSUED`, priority 7) takes precedence over an **insufficient-funds** failure (`ERR_GRANT_INSUFFICIENT`, priority 16): when both would fail, the state error wins. Second, on relocation placement a **case-not-active** failure (`ERR_CASE_NOT_ACTIVE`, priority 12) takes precedence over a **temporal-overlap** failure (`ERR_RELOCATION_OVERLAP`, priority 14): when both would fail, the case-not-active error wins. The remaining domain checks — qualifying-test and threshold checks on case opening, contractor-certification on project start, unit-availability and inspector-double-booking, and case-resolvability on close — are described alongside the workflows they guard in §3.

### 2.9. Cascades, Conservation, and the Four-Eyes Rule

Mutations in this system frequently touch more than one resource, and every such cascade resolves synchronously inside the triggering request — derived counters and ledgers are reconciled before the response returns. Two conserved quantities anchor the design.

The first is the **hazard count**. Each `Case` maintains `open_hazard_count` (the number of its hazard findings whose `control_status` is `OPEN`), `controlled_hazard_count` (those that are `CONTROLLED`), and `total_hazard_count`, which is always the sum of the two. Recording a new hazard finding is the only event that raises `total_hazard_count`. A clearance pass moves findings from open to controlled — decrementing `open_hazard_count` and incrementing `controlled_hazard_count` by the same number — and an order void moves them back, but neither changes `total_hazard_count`.

The second is the **grant money** partition described in §2.6: reservations and releases move value between `available_cents` and `reserved_cents`, and completion moves value into `spent_cents`, but the three always sum to `total_budget_cents`.

Whenever a resource is mutated, its `updated_at` is refreshed and its `version` increments by 1; this applies to a parent whose derived counters change as much as to the entity directly acted upon. For example, when a clearance pass reclassifies hazards, the affected `Case` is itself mutated because its counts change.

Clearance is a life-safety sign-off and is therefore subject to a **four-eyes** segregation-of-duties rule: the inspector who signs a clearance test (recorded as `cleared_by_inspector_id` from `X-User-ID`) must not be the same inspector who conducted the source investigation (its `inspector_id`). A violation is rejected with `ERR_SOD_CONFLICT` (HTTP 409). This is the one place where the identity of the acting inspector is captured on a record rather than merely checked.

### 2.10. Nested Resource Retrieval

A handful of reads are expressed as sub-resource paths — a child's blood-lead tests, an investigation's hazard findings, an order's clearance tests. For any path that contains more than one identifier, the identifiers are validated left to right: the parent must exist before the child collection is considered, and the first identifier that fails to resolve produces that resource's own not-found error. A read of a child's blood-lead tests, for instance, first resolves the child (else `ERR_CHILD_NOT_FOUND`) before returning the list. These sub-resource reads are the reverse-reachability path for foreign keys that are otherwise only discoverable through filtered list queries.

## 3. Business Logic & Workflows

### 3.1. Intake: Children, Dwellings, and Blood-Lead Screening

Everything begins with the people and places the program serves. An `IntakeCoordinator` (or a `ProgramAdmin`) registers a screened child by supplying the child's `full_name`, `date_of_birth` as an ISO 8601 calendar date, the `guardian_name`, the `primary_dwelling_id` naming the child's current residence, and the household `income_tier` — one of `EXTREMELY_LOW`, `VERY_LOW`, `LOW`, or `MODERATE`. A `medicaid_enrolled` flag may be supplied; when omitted it defaults to false, and it drives eligibility reporting.

Dwellings are registered by the same two roles. A dwelling records its `street_address`, an optional `unit_designation` (an apartment or unit label that defaults to null for single-family homes), the `year_built`, the `owner_name` of record, and the health `jurisdiction` or county code responsible for it. From the construction year the system derives `pre_1978`, a boolean lead-paint presumption that is true exactly when `year_built` is earlier than 1978; any client-supplied value for this field is ignored.

Blood-lead tests are recorded exclusively by an `IntakeCoordinator`. A test names its `child_id`, the measured `bll_ug_dl` (blood-lead level in micrograms per deciliter, which may not be negative), the `specimen_type` — `VENOUS` (confirmatory) or `CAPILLARY` (a screen) — the `test_kind` (`SCREENING`, `DIAGNOSTIC`, or `FOLLOWUP`), and the `collected_at` instant the specimen was drawn. The system computes `result_class` for the test by comparing `bll_ug_dl` against the same reference thresholds that classify a case (see §3.2): the result is `CLASS_I` when the level is at least 45, `CLASS_II` when it is at least 20 but below 45, `CLASS_III` when it is at least the case threshold of 3.5 but below 20, and `BELOW_THRESHOLD` when it is below 3.5. Any client-supplied `result_class` is ignored. Recording a test can also carry two downstream consequences on an existing case, described in §3.2 and §3.3. Blood-lead tests are immutable audit records; they carry only `id` and `created_at`.

### 3.2. Opening a Case and Reference-BLL Classification

A `Case` ties a poisoned child to the residence under investigation. An `IntakeCoordinator` opens a case by supplying the `child_id`, the `dwelling_id`, and a `qualifying_test_id` — the blood-lead test whose result justifies opening the case. Two gate checks apply, evaluated together at the highest domain priority for this endpoint, and in this internal order: first, the qualifying test must belong to the same child, meaning its recorded child must equal the supplied `child_id`; a mismatch is rejected with `ERR_QUALIFYING_TEST_MISMATCH` (HTTP 422). Only then is the level checked: the qualifying test's `bll_ug_dl` must be at least the case-opening threshold of 3.5 micrograms per deciliter, and a level below that is rejected with `ERR_BLL_BELOW_THRESHOLD` (HTTP 422).

On success the case is created with `case_status` set to `OPEN` and `medical_status` set to `ELEVATED`. Its `income_tier` is a snapshot copied from the child at creation and thereafter drives subsidy sizing independently of any later change to the child. The governing blood-lead level, `reference_bll_ug_dl`, is a dual-variant quantity. At case open it takes the **provisional** basis: `reference_bll_ug_dl` is set verbatim to the qualifying test's `bll_ug_dl` — even if that qualifying test is a capillary screen — and `reference_basis` is set to `PROVISIONAL`. The reference level is carried to one decimal place.

Later, whenever a `VENOUS` test of kind `SCREENING` or `DIAGNOSTIC` is recorded for a child who has a non-terminal case, the reference switches to the **confirmed** basis: the system considers all of that child's blood-lead tests whose `specimen_type` is `VENOUS` and whose `test_kind` is either `SCREENING` or `DIAGNOSTIC`, takes the maximum `bll_ug_dl` among them, sets `reference_bll_ug_dl` to that maximum, and sets `reference_basis` to `CONFIRMED`. Follow-up tests are deliberately excluded from this set; they drive the medical track instead (§3.3). Because a venous confirmation can be lower than the provisional capillary value, a confirmed reference can pull both the level and the derived priority below where they started.

Every time `reference_bll_ug_dl` is recomputed, the response-priority band `priority_class` is recomputed from it: `CLASS_I` when the reference is at least 45, otherwise `CLASS_II` when it is at least 20, otherwise `CLASS_III`. Because the case can only exist when the reference is at least the 3.5 threshold, the `CLASS_III` band is the floor. The comparison is made on the one-decimal reference value, and each boundary is an inclusive lower bound.

A case can be fetched individually or listed. The list endpoint accepts filters that provide reverse reachability for its foreign keys — `child_id`, `dwelling_id`, and `qualifying_test_id` — as well as a `case_status` filter, alongside the standard `limit` and `offset`.

### 3.3. The Medical Track: Follow-up Testing

The medical track lives on `medical_status` and evolves independently of the environmental `case_status`. It responds only to `VENOUS` `FOLLOWUP` tests recorded for a child whose case is not in a terminal state (`case_status` neither `CLOSED` nor `WITHDRAWN`), and it turns on whether the follow-up level is below the case threshold of 3.5 micrograms per deciliter.

Consider a case that opens at `ELEVATED`. When a venous follow-up comes back below 3.5 for a case currently `ELEVATED`, `medical_status` advances to `MONITORING` — the first sub-threshold reading. A second consecutive venous follow-up below 3.5 while the case is `MONITORING` advances it to `RESOLVED`. But if, while `MONITORING`, a venous follow-up comes back at or above 3.5, the level has rebounded: `medical_status` regresses to `ELEVATED`, resetting the monitoring streak. These transitions are driven by the `IntakeCoordinator` who records the test. A follow-up test never changes `reference_bll_ug_dl`, and a resolved medical track is one of the preconditions for closing a case (§3.9).

### 3.4. Environmental Investigation and Hazard Findings

Inspectors themselves are registered by a `ProgramAdmin`, who supplies the inspector's `full_name`, the state lead risk-assessor `certification_id_number`, and an optional `active` flag indicating whether the inspector may be assigned work; when omitted, `active` defaults to true.

Once a case is open, a `CaseManager` schedules an environmental investigation, supplying the `case_id`, the `dwelling_id`, the `inspector_id` of the assigned inspector, and the on-site window as `scheduled_start` (inclusive) and `scheduled_end` (exclusive), both ISO 8601 UTC instants. Scheduling is permitted only when the case's `case_status` is `OPEN` or `INVESTIGATION`; the first investigation scheduled for an `OPEN` case advances its `case_status` to `INVESTIGATION`. An investigation is created in `SCHEDULED`.

Scheduling also guards the inspector's calendar: the request is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED` (HTTP 409) if the assigned inspector already has another investigation in `SCHEDULED` or `IN_PROGRESS` whose window overlaps this one. The windows are treated as half-open intervals from `scheduled_start` up to but not including `scheduled_end`, so two windows that merely touch at an endpoint do not overlap.

Findings are recorded by the assigned `Inspector` — and only that inspector, whose `X-User-ID` must equal the investigation's `inspector_id`. Each finding supplies its `hazard_type` (`PAINT`, `DUST`, `SOIL`, or `WATER`), a free-text `location`, a `measurement_value` in the medium's native unit (never negative), and an assessor-assigned `severity` (`LOW`, `MODERATE`, or `HIGH`). A new finding is created with `control_status` `OPEN`. Recording the first finding moves the investigation from `SCHEDULED` to `IN_PROGRESS`; each subsequent finding is a self-transition that keeps it `IN_PROGRESS`. Every finding increments the investigation's `hazard_finding_count` and, on the finding's case, raises both `open_hazard_count` and `total_hazard_count` by one.

Completing an investigation is likewise restricted to the assigned inspector. Completion is allowed from either `SCHEDULED` or `IN_PROGRESS`; it sets `status` to `COMPLETED` and stamps `completed_at` from the logical clock. The empty-versus-nonempty boundary decides what happens next. If the completed investigation recorded at least one hazard — `hazard_finding_count` of one or more — the system issues a `HazardControlOrder` in `ISSUED`, snapshots its `hazard_count` from the investigation's finding count, and advances the case's `case_status` from `INVESTIGATION` to `ENFORCEMENT`. If instead the investigation recorded zero findings, no order is issued; the case advances from `INVESTIGATION` to `CLOSED` only if its `medical_status` is already `RESOLVED`, and otherwise it remains `INVESTIGATION` with no order. An investigation exposes `hazard_finding_count` and `completed_at` (null until completion), and its findings are readable as a sub-resource. The list endpoint filters by `case_id`, `dwelling_id`, `inspector_id`, and `status`.

### 3.5. Hazard-Control Orders and Independent Clearance

A `HazardControlOrder` is the enforcement instrument. It is not created directly; it is issued automatically when an investigation with hazards completes (§3.4), carrying the `case_id`, `dwelling_id`, and `investigation_id` of that source investigation, an `issued_at` stamped from the logical clock, and a `hazard_count` snapshot. Its `compliance_deadline` is computed as the issuance instant plus 30 days. An order begins in `ISSUED` and its lifecycle is cyclic: it can bounce between remediation and clearance until the dwelling passes.

The order moves from `ISSUED` to `IN_REMEDIATION` as a side effect of a contractor starting the linked remediation project (§3.6) — it is never advanced into remediation on its own. Once the physical work is done, the assigned `Contractor` declares the order ready for clearance, moving it from `IN_REMEDIATION` to `CLEARANCE_PENDING`; this is permitted only while the order is `IN_REMEDIATION` and only for the contractor whose `X-User-ID` matches the `contractor_id` of that order's in-progress project.

Clearance itself is signed by an `Inspector` who submits a dust-wipe clearance test naming the `order_id` and three post-remediation measurements: `floor_result_ug_ft2`, `sill_result_ug_ft2`, and `trough_result_ug_ft2`, each in micrograms per square foot and never negative. The signing inspector's `X-User-ID` is captured as `cleared_by_inspector_id`, and the four-eyes rule applies: if it equals the source investigation's `inspector_id`, the test is rejected with `ERR_SOD_CONFLICT` (HTTP 409). A clearance test may be signed only while the order is in `CLEARANCE_PENDING`. The system computes `evaluated_result`, ignoring any client-supplied value: the result is `PASS` only when all three measurements are within their federal limits — the floor result at most 10, the sill result at most 100, and the trough result at most 400 micrograms per square foot — where a result exactly at a limit passes; otherwise the result is `FAIL`. Clearance tests are immutable audit records carrying only `id` and `created_at`, and an order's clearance tests are readable as a sub-resource.

A `PASS` moves the order from `CLEARANCE_PENDING` to `CLEARED` and triggers the clearance cascade: every `OPEN` hazard finding of the source investigation transitions to `CONTROLLED`, the case's `open_hazard_count` is decremented and its `controlled_hazard_count` incremented by the number reclassified, and its `total_hazard_count` is unchanged. A `FAIL` sends the order back from `CLEARANCE_PENDING` to `IN_REMEDIATION` — the cyclic back edge — so that the contractor can re-work and request clearance again.

A `CaseManager` can void an order at any point in its life — from `ISSUED`, `IN_REMEDIATION`, `CLEARANCE_PENDING`, or even `CLEARED` — and void is also reached as a cascade when the case is withdrawn (§3.9). `VOID` is the sole hard-terminal state; `CLEARED` is the stable success state and is left only by this administrative void. Voiding an order sets its `status` to `VOID` and performs the compensating reversion: every `CONTROLLED` hazard finding of the source investigation reverts to `OPEN`, the case's `controlled_hazard_count` is decremented and its `open_hazard_count` incremented by the number reverted (again conserving `total_hazard_count`), and every remediation project of the order that is still in `PROPOSED`, `APPROVED`, or `IN_PROGRESS` transitions to `CANCELLED`, which releases any grant reservation those projects held. Orders can be fetched individually or listed with filters for `case_id`, `dwelling_id`, `investigation_id`, and `status`.

### 3.6. Grant-Funded Remediation Projects

Remediation is organized as a project that crosses three aggregates. Before projects can be funded, a `ProgramAdmin` creates a `GrantFund` with a `fund_name`, a `fiscal_year`, and a `total_budget_cents`; the fund starts with `reserved_cents` and `spent_cents` at zero and `available_cents` equal to the full budget. A fund can be fetched to read its `version` and ledger before an approval.

A `CaseManager` proposes a project by supplying the `order_id` it will remediate, the `contractor_id` of the RRP firm that will perform the work, and the `grant_fund_id` that will subsidize it. A project may be proposed only against an order in `ISSUED`, and it is created in `PROPOSED` with `estimated_cost_cents` of 0, `final_cost_cents` null, and an empty `line_items` array.

**Approval** is performed by a `CaseManager` and requires the order to still be in `ISSUED`. It is guarded by optimistic concurrency: the request carries `expected_grant_fund_version`, which must match the fund's current `version` or the approval is rejected with `ERR_STALE_GRANT_VERSION` (HTTP 412). On approval the system computes the income-tiered subsidy and sets `estimated_cost_cents` to it. The subsidy is computed from the order's `hazard_count` and the case's snapshot `income_tier`: a base unit subsidy of 250000 cents (2,500 dollars) is multiplied by the hazard count and by the income multiplier for the tier — 1.5 for `EXTREMELY_LOW`, 1.25 for `VERY_LOW`, 1.0 for `LOW`, and 0.75 for `MODERATE`. That raw product is rounded half up to whole cents, and then the result is capped at a maximum subsidy of 1500000 cents (15,000 dollars); the smaller of the rounded amount and the cap becomes `estimated_cost_cents`. Approval requires that this estimated subsidy not exceed the fund's `available_cents`; if it does, the approval is rejected with `ERR_GRANT_INSUFFICIENT` (HTTP 402). Recall from §2.8 that when the order is not in `ISSUED`, the state failure (`ERR_INVALID_STATE`) is reported ahead of any insufficient-funds failure. A successful approval moves the project `PROPOSED → APPROVED`, increases the fund's `reserved_cents` by `estimated_cost_cents`, recomputes `available_cents`, and increments the fund's `version` by 1.

**Starting** work is performed by the assigned `Contractor`, whose `X-User-ID` must equal the project's `contractor_id`. Starting requires the project to be `APPROVED`, the linked order still in `ISSUED`, and the contractor to be certified and current — its `certification_status` must be `ACTIVE` and its `certification_expires_at` must be strictly after the current logical clock; otherwise the start is rejected with `ERR_CONTRACTOR_NOT_CERTIFIED` (HTTP 409). A successful start moves the project `APPROVED → IN_PROGRESS` and, as a cross-entity side effect, moves the linked order `ISSUED → IN_REMEDIATION`.

**Completion** is performed by the same assigned `Contractor` and requires the project to be `IN_PROGRESS` and the linked order to have reached `CLEARED`. The contractor submits `line_items`, an array of entries recording actual costs, each carrying a `description` and an `amount_cents` value. Completion moves the project `IN_PROGRESS → COMPLETED` and finalizes cost: `final_cost_cents` is set to the sum of the submitted line items' `amount_cents`. The fund is then reconciled — its `reserved_cents` is decreased by the project's `estimated_cost_cents`, and its `spent_cents` is increased by the smaller of `estimated_cost_cents` and `final_cost_cents`, so the grant never pays out more than the reserved subsidy and any overrun falls on the owner. `available_cents` is recomputed.

**Cancellation** is performed by a `CaseManager`, and is also reached as a cascade from an order void. A project may be cancelled from `PROPOSED`, `APPROVED`, or `IN_PROGRESS`. Cancellation sets `status` to `CANCELLED`; if the project had reserved funds — that is, it had reached `APPROVED` or `IN_PROGRESS` — the fund's `reserved_cents` is decreased by `estimated_cost_cents` and `available_cents` recomputed, the compensating release that returns the fund to its pre-approval balance. A project cancelled while still merely `PROPOSED` held no reservation and releases nothing. Projects can be fetched individually or listed with filters for `order_id`, `contractor_id`, and `grant_fund_id`.

### 3.7. Contractor Certification Lifecycle

Contractors are RRP-certified firms, and their standing is managed entirely by a `ProgramAdmin`. Registering a contractor records its `business_name` and EPA `rrp_certification_number`; it starts in `certification_status` `PENDING` with a null `certification_expires_at`. The certification lifecycle is driven through a single action endpoint that takes an `action` and, for activation, an `expires_at` instant.

The `ACTIVATE` action moves a `PENDING` contractor to `ACTIVE` and sets `certification_expires_at` to the supplied `expires_at`. From `ACTIVE`, the `SUSPEND` action moves it to `SUSPENDED`, and from `SUSPENDED` the `REINSTATE` action moves it back to `ACTIVE` — the cyclic edge that lets certification be paused and resumed. The `EXPIRE` action moves an `ACTIVE` contractor to `EXPIRED`, which also happens by system lapse when the logical clock passes `certification_expires_at`. The `REVOKE` action moves a contractor from either `ACTIVE` or `SUSPENDED` to the terminal `REVOKED`. Each action is valid only from its defined source state; an action requested from any other state is an invalid transition. As covered in §3.6, only an `ACTIVE`, unexpired contractor may start work.

### 3.8. Relocation and Interim Controls

While remediation is underway a family may need temporary housing. A `ProgramAdmin` registers a `RelocationUnit` with an `address` and a `bedroom_count`; its `status` may be supplied and defaults to `AVAILABLE`, the alternative being `OFFLINE`.

A `CaseManager` places a family by supplying the `case_id`, the `relocation_unit_id`, the `start_date` and `end_date` of the planned stay (ISO 8601 dates forming a closed, inclusive interval), and the `occupant_count`, which drives per-diem reimbursement and must be at least 1. Three preconditions guard placement. The chosen unit's `status` must be `AVAILABLE`, else `ERR_UNIT_UNAVAILABLE` (HTTP 409). The referenced case must not be terminal — its `case_status` must be neither `CLOSED` nor `WITHDRAWN` — else `ERR_CASE_NOT_ACTIVE` (HTTP 409). And the stay must not collide with another booking of the same unit: the placement is rejected with `ERR_RELOCATION_OVERLAP` (HTTP 409) if the unit has any other `ACTIVE` placement whose closed interval falls within a cleaning buffer of 3 days of this one — concretely, a conflict exists when the new stay's `start_date` is on or before the existing stay's `end_date` plus 3 days and the new stay's `end_date` is on or after the existing stay's `start_date` minus 3 days. When both the case-not-active and the overlap checks would fail, the case-not-active error is reported first (see §2.8). A successful placement is created in `ACTIVE` with `actual_end_date` null and `reimbursement_cents` at 0.

Ending a placement is performed by a `CaseManager`, who supplies the `actual_end_date`; it is allowed only from `ACTIVE` and only when the actual end date is on or after the `start_date`. Ending sets `status` to `ENDED`, records `actual_end_date`, and computes `reimbursement_cents`. The reimbursement is built up per night, with the rounding order pinned. First the number of nights is the whole-day count from `start_date` up to but not including `actual_end_date`. The raw daily rate is the per-diem lodging of 12000 cents plus a meal rate of 3500 cents for each occupant (that is, 3500 multiplied by `occupant_count`), and that daily sum is then multiplied by an administrative factor of 1.075. This raw daily amount is rounded half up to whole cents to produce the per-day amount, and only then is the per-day amount multiplied by the number of nights to give `reimbursement_cents`. The rounding is applied to the per-day figure before the multiplication, not to the full product. A placement that is instead cancelled — which happens as a fan-out when its case is withdrawn — moves from `ACTIVE` to `CANCELLED` and its `reimbursement_cents` stays 0. Placements can be fetched individually or listed with filters for `case_id`, `relocation_unit_id`, and `status`.

### 3.9. Closing and Withdrawing a Case; Surveillance Reporting

A case reaches its natural end when a `CaseManager` closes it. Closure is allowed only from `case_status` `ENFORCEMENT`, and only when three conditions all hold: `medical_status` is `RESOLVED`, `open_hazard_count` is 0, and at least one of the case's hazard-control orders is `CLEARED` (with every order of the case being either `CLEARED` or `VOID`). If any of these fails, closure is rejected with `ERR_CASE_NOT_RESOLVABLE` (HTTP 409). A successful close moves `case_status` from `ENFORCEMENT` to `CLOSED`. (As noted in §3.4, a case can also reach `CLOSED` directly from `INVESTIGATION` when an investigation completes with zero hazards and the medical track is already `RESOLVED`.)

Withdrawal is the escape hatch. A `CaseManager` may withdraw a case from `OPEN`, `INVESTIGATION`, or `ENFORCEMENT`, moving `case_status` to `WITHDRAWN`. Withdrawal drives a depth-three cascade that resolves synchronously. First, every investigation of the case still in `SCHEDULED` or `IN_PROGRESS` is cancelled (a fan-out to `CANCELLED`). Second, every hazard-control order of the case still in `ISSUED`, `IN_REMEDIATION`, or `CLEARANCE_PENDING` is voided — and each such void carries its own cascade: it reverts that order's `CONTROLLED` hazards to `OPEN` (adjusting the case counts) and cancels the order's non-terminal remediation projects. Third, each of those project cancellations releases the grant reservation the project held, returning `reserved_cents` and `available_cents` to their pre-approval values. Both `CLOSED` and `WITHDRAWN` are terminal for the environmental track.

Finally, a surveillance report is available to a `ProgramAdmin` or a `CaseManager`, optionally narrowed by `jurisdiction`. It aggregates over cases and the grant ledger and returns eight counts and totals: `total_cases`, `open_cases`, `class_i_count`, `class_ii_count`, `class_iii_count` (case counts by `priority_class`), `resolved_count` (cases whose `medical_status` is `RESOLVED`), and `total_reserved_cents` and `total_spent_cents` aggregated across grant funds.

## 4. Endpoint Definitions

The table below summarizes every endpoint. As a general rule, creating a new resource returns HTTP 201 with the created resource in `data`; reads and state-changing actions on existing resources return HTTP 200 with the affected (or requested) resource. Request bodies, response payloads, and side effects are intentionally omitted here — they are specified in the §3 workflow narratives, which must be read to reconstruct each call.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/api/v1/children` | Register a screened child | IntakeCoordinator, ProgramAdmin |
| GET | `/api/v1/children` | List children; filter by residence | IntakeCoordinator, CaseManager, Inspector, ProgramAdmin |
| GET | `/api/v1/children/{id}` | Fetch one child | IntakeCoordinator, CaseManager, Inspector, ProgramAdmin |
| GET | `/api/v1/children/{id}/blood-lead-tests` | List a child's blood-lead tests | IntakeCoordinator, CaseManager, Inspector, ProgramAdmin |
| POST | `/api/v1/blood-lead-tests` | Record a blood-lead result | IntakeCoordinator |
| POST | `/api/v1/dwellings` | Register a residential dwelling | IntakeCoordinator, ProgramAdmin |
| POST | `/api/v1/cases` | Open a lead case from a qualifying test | IntakeCoordinator |
| GET | `/api/v1/cases/{id}` | Fetch one case | IntakeCoordinator, CaseManager, Inspector, ProgramAdmin |
| GET | `/api/v1/cases` | List cases | IntakeCoordinator, CaseManager, Inspector, ProgramAdmin |
| POST | `/api/v1/cases/{id}/withdraw` | Withdraw a case (cascades) | CaseManager |
| POST | `/api/v1/cases/{id}/close` | Close a cleared, resolved case | CaseManager |
| POST | `/api/v1/inspectors` | Register a lead risk-assessor inspector | ProgramAdmin |
| POST | `/api/v1/investigations` | Schedule an environmental investigation | CaseManager |
| GET | `/api/v1/investigations/{id}` | Fetch one investigation | CaseManager, Inspector, ProgramAdmin |
| GET | `/api/v1/investigations` | List investigations | CaseManager, Inspector, ProgramAdmin |
| GET | `/api/v1/investigations/{id}/hazard-findings` | List an investigation's hazard findings | CaseManager, Inspector, ProgramAdmin |
| POST | `/api/v1/investigations/{id}/findings` | Record a hazard finding | Inspector |
| POST | `/api/v1/investigations/{id}/complete` | Complete an investigation | Inspector |
| GET | `/api/v1/hazard-control-orders/{id}` | Fetch one hazard-control order | CaseManager, Inspector, Contractor, ProgramAdmin |
| GET | `/api/v1/hazard-control-orders` | List orders | CaseManager, Inspector, ProgramAdmin |
| GET | `/api/v1/hazard-control-orders/{id}/clearance-tests` | List clearance tests for an order | CaseManager, Inspector, ProgramAdmin |
| POST | `/api/v1/hazard-control-orders/{id}/request-clearance` | Contractor declares work ready for clearance | Contractor |
| POST | `/api/v1/hazard-control-orders/{id}/void` | Void an order (reverts hazards, cancels projects) | CaseManager |
| POST | `/api/v1/clearance-tests` | Sign off a dust-wipe clearance test | Inspector |
| POST | `/api/v1/relocation-units` | Register a temporary relocation unit | ProgramAdmin |
| POST | `/api/v1/relocation-placements` | Place a family in a relocation unit | CaseManager |
| GET | `/api/v1/relocation-placements/{id}` | Fetch one relocation placement | CaseManager, ProgramAdmin |
| GET | `/api/v1/relocation-placements` | List placements | CaseManager, ProgramAdmin |
| POST | `/api/v1/relocation-placements/{id}/end` | End a placement and compute reimbursement | CaseManager |
| POST | `/api/v1/contractors` | Register an RRP remediation contractor | ProgramAdmin |
| POST | `/api/v1/contractors/{id}/certification` | Drive the RRP certification lifecycle | ProgramAdmin |
| POST | `/api/v1/grant-funds` | Create a remediation grant fund | ProgramAdmin |
| GET | `/api/v1/grant-funds/{id}` | Fetch a grant fund (version + ledger) | ProgramAdmin, CaseManager |
| POST | `/api/v1/remediation-projects` | Propose a grant-funded remediation project | CaseManager |
| GET | `/api/v1/remediation-projects/{id}` | Fetch one remediation project | CaseManager, Contractor, ProgramAdmin |
| GET | `/api/v1/remediation-projects` | List projects | CaseManager, Contractor, ProgramAdmin |
| POST | `/api/v1/remediation-projects/{id}/approve` | Approve a project; reserve subsidy (OCC) | CaseManager |
| POST | `/api/v1/remediation-projects/{id}/start` | Start approved work (requires ACTIVE certification) | Contractor |
| POST | `/api/v1/remediation-projects/{id}/complete` | Complete work; finalize cost | Contractor |
| POST | `/api/v1/remediation-projects/{id}/cancel` | Cancel a project; release reserved subsidy | CaseManager |
| GET | `/api/v1/reports/surveillance` | Aggregate surveillance report | ProgramAdmin, CaseManager |
| POST | `/api/v1/_clock/set_current_utc` | Set the server's logical clock | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SOD_CONFLICT` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_GRANT_VERSION` | 412 |
| `ERR_QUALIFYING_TEST_MISMATCH` | 422 |
| `ERR_BLL_BELOW_THRESHOLD` | 422 |
| `ERR_CONTRACTOR_NOT_CERTIFIED` | 409 |
| `ERR_UNIT_UNAVAILABLE` | 409 |
| `ERR_CASE_NOT_ACTIVE` | 409 |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 |
| `ERR_RELOCATION_OVERLAP` | 409 |
| `ERR_CASE_NOT_RESOLVABLE` | 409 |
| `ERR_GRANT_INSUFFICIENT` | 402 |
| `ERR_CHILD_NOT_FOUND` | 404 |
| `ERR_DWELLING_NOT_FOUND` | 404 |
| `ERR_TEST_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_INSPECTOR_NOT_FOUND` | 404 |
| `ERR_INVESTIGATION_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_PLACEMENT_NOT_FOUND` | 404 |
| `ERR_CONTRACTOR_NOT_FOUND` | 404 |
| `ERR_GRANT_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |

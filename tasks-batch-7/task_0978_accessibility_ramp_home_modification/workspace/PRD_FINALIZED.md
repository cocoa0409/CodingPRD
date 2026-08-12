# Accessibility Ramp & Home Modification API — Product Requirements Document

## 1. Introduction

Home-accessibility work sits at the intersection of clinical judgement, construction logistics, and multi-payer funding. An occupational therapist identifies that a client cannot safely leave their home; a CAPS-certified assessor measures doorways and elevations; a project manager prices a modular ramp or a bathroom remodel; a funding coordinator chases Medicaid waivers, VA benefits, state grants, and charitable funds; a crew lead builds; an inspector certifies; a billing coordinator collects. Today each of these hand-offs lives in spreadsheets and phone calls, and the consequences of a lost update are concrete: a crew arrives before the permit is issued, a quote is approved against funding that was already withdrawn, a rental ramp sits in a driveway for months after the client has moved to a facility, or a warranty call is answered by someone who cannot see what was actually installed.

This document specifies an API that runs the entire engagement as a single case file. A case opens at intake, is assessed clinically, is priced through versioned quotes, is financed through prioritized funding sources whose allocations are committed only when a quote is approved, and is executed through permitted installation jobs whose completion triggers inspection, warranty activation, and a scheduled post-install reassessment. A parallel rental-ramp program manages a physical inventory fleet, tiered monthly pricing, deposits, and pickup logistics. Billing runs against the same case file so that every dollar quoted, funded, billed, and collected is reconciled on one ledger. The intended readers are the engineers who will implement this service; every rule below is stated as unambiguous prose, and the endpoint table in §4 and the error catalogue in §5 are the definitive structural contracts.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role under which the operator acts. A request in which either header is missing or carries an unrecognized value is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). A request whose role is recognized but not permitted to perform the requested operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Authorization is role-based only: the server does not perform per-resource ownership checks for any role, because no role's identity is backed by a persisted entity.

The recognized roles, spelled exactly as the `X-User-Role` header must carry them, are:

- **IntakeCoordinator** — handles case intake and schedules assessments and consultations. When `X-User-Role` is `IntakeCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- **Assessor** — an OT or CAPS professional who performs assessments and completes consultations. When `X-User-Role` is `Assessor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **ProjectManager** — manages quotes, installation jobs, and the case lifecycle. When `X-User-Role` is `ProjectManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **FundingCoordinator** — manages funding sources, allocations, and quote approval decisions. When `X-User-Role` is `FundingCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **CrewLead** — leads installation and warranty crews. When `X-User-Role` is `CrewLead`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **LogisticsCoordinator** — manages the rental inventory fleet and rental logistics. When `X-User-Role` is `LogisticsCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **Inspector** — schedules and records inspections. When `X-User-Role` is `Inspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **BillingCoordinator** — manages invoicing and payment collection. When `X-User-Role` is `BillingCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **Client** — the person receiving services; may dispute invoices and open warranty claims. When `X-User-Role` is `Client`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **SystemAdmin** — administrative role reserved for test-driving capabilities such as the logical clock. When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **Any** — not a real operator role but the shared read access tier: every read endpoint (all list and get operations) is available to any request that carries a valid user context, regardless of which of the roles above is presented.

Write operations are exclusive to the roles named in §4; the `Any` tier grants read access only.

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

All list endpoints accept two query parameters. `limit` controls the page size: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. `offset` controls how many records are skipped before the page begins and defaults to 0. List responses report `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` is the full count of matching records and `has_more` indicates whether further records exist beyond the returned page.

Every list is sorted by `created_at` ascending — the oldest record first — with no option to change the ordering. Several list endpoints additionally accept domain filters: the case list accepts optional `status` and `funding_posture` filters, the quote list and the invoice list each accept an optional `status` filter, and the inventory-unit list accepts optional `status` and `ramp_type` filters. Filter values must match the enumeration strings exactly.

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

Every resource in this API — Case, Assessment, Quote, QuoteLineItem, FundingSource, FundingAllocation, InstallationJob, RentalRamp, InventoryUnit, Inspection, Invoice, InvoiceLineItem, WarrantyClaim, OTConsultation, and ReassessmentSchedule — carries the same four system-managed properties. `id` is a server-minted UUID rendered in the canonical RFC 4122 string form — hyphenated 8-4-4-4-12 lowercase hexadecimal — with no type prefix; clients never supply it. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is the same kind of timestamp, refreshed on every mutation of the resource. `version` is an integer that starts at 1 when the resource is created and increments by one on every mutation. Fields whose value has not yet been determined (for example a funding source's `approved_cents` before its decision, or an inspection's `completed_date` before it is recorded) are returned as null.

Three write operations are guarded by optimistic concurrency control against the parent case, and each names the guard field explicitly in its request body:

- Creating a quote (`POST /cases/{caseId}/quotes`) requires `expected_case_version`, carrying the `version` of the case as the client last observed it.
- Approving a funding source (`POST /cases/{caseId}/funding-sources/{sourceId}/approve`) requires `expected_case_version` on the same terms.
- Sending an invoice (`POST /cases/{caseId}/invoices/{invoiceId}/send`) requires `expected_case_version` on the same terms.

On each of these three endpoints, if the supplied `expected_case_version` does not equal the case's current `version` — meaning another writer has advanced the case since the client last read it, for example by completing an assessment, changing funding, or sending another invoice — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no change is applied. Creating an invoice (`POST /cases/{caseId}/invoices`) also carries `expected_case_version` in its request body and is validated against the case's current `version` under the same rule and the same `ERR_STALE_VERSION` rejection. Endpoints not named in this subsection do not take a version field at all.

### 2.5. Monetary Representation, Precision, and Rounding

All money is represented as integer cents — `total_cents`, `amount_cents`, `unit_price_cents`, and every other `*_cents` field are whole numbers with zero decimal places. Wherever a monetary computation produces a fraction, the result is rounded half up to the nearest whole cent. Quote and invoice arithmetic is performed per line: each line's extended price and each line's tax are rounded half up to whole cents independently before any summation takes place, and totals are sums of those already-rounded line amounts. The system never sums raw unrounded products and rounds only at the total level, because per-line rounding is what the client's paperwork shows.

Two non-monetary scores follow their own precision rules. The ADA compliance percentage is carried at two decimal places as an intermediate value and rounded to a whole number for the case-level scope score. The safety risk index is carried at one decimal place.

### 2.6. Request Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed order and returns the first failure encountered. A request that is malformed, missing required fields, or carrying invalid values is rejected as `ERR_INVALID_REQUEST` (HTTP 400). Beyond that, the precedence ladder is:

1. **User context.** The `X-User-ID` and `X-User-Role` headers must be present and valid on every endpoint; failure is `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400).
2. **Role permission.** The presented role must be permitted to perform the operation on every endpoint; failure is `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).
3. **Path existence.** Every resource identifier in the URL path must exist, validated left to right — the case first, then each nested identifier in path order; failure is the 404 error for the segment that failed (see §2.7).
4. **Parent case state.** The parent case must be in a state that allows the child operation; failure is one of `ERR_CASE_NOT_ACTIVE`, `ERR_CASE_NOT_ASSESSED`, `ERR_CASE_NOT_FUNDED`, or `ERR_CASE_ALREADY_CLOSED` (HTTP 409), as described in the workflow sections.
5. **Target resource state.** The resource being acted on must be in a state from which the requested transition exists; failure is one of `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`, `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409).
6. **Business constraints, in the following order.** (6a) submitting a quote that has no line items fails with `ERR_QUOTE_EMPTY` (HTTP 422); (6b) adding a quote line item whose quantity or unit price is not positive fails with `ERR_INVALID_LINE_ITEM` (HTTP 422); then (7) scheduling an assessment whose `scheduled_date` lies in the past fails with `ERR_INVALID_SCHEDULE_DATE` (HTTP 422); (8) creating a rental ramp when the case's assessment indicates a permanent installation is medically necessary fails with `ERR_RENTAL_NOT_CLINICALLY_INDICATED` (HTTP 422); (9) allocating a funding source to line items its restrictions prohibit fails with `ERR_FUNDING_RESTRICTION_VIOLATION` (HTTP 422); (10) allocating more than a funding source's remaining balance fails with `ERR_ALLOCATION_EXCEEDS_REMAINING` (HTTP 422); (11) creating a third-party invoice whose total exceeds the case's funded amount fails with `ERR_INVOICE_EXCEEDS_FUNDING` (HTTP 422); (12) completing an installation job with unresolved safety-critical punch items fails with `ERR_SAFETY_ITEMS_UNRESOLVED` (HTTP 422); (13) reserving an inventory unit over a period that overlaps an existing active rental of the same unit fails with `ERR_UNIT_UNAVAILABLE` (HTTP 409); and (14) scheduling a final inspection before the installation job has actually finished fails with `ERR_INSPECTION_BEFORE_COMPLETION` (HTTP 422).

Because the ladder is ordered, a single request can only ever surface the earliest failing check — for example, a non-existent case always produces `ERR_CASE_NOT_FOUND`, never a business-rule error, and a forbidden role always surfaces before any not-found error.

### 2.7. Nested Resource Addressing

Most resources live beneath a case in the URL hierarchy, and some live two levels deep (a funding allocation beneath its funding source beneath the case). Path parameters are validated strictly left to right: the `{caseId}` segment is checked first, then the next nested identifier, then the next. The first segment that does not resolve produces the 404 for that resource type and evaluation stops. The not-found errors are: `ERR_CASE_NOT_FOUND` for a case, `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND` for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp, `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404. Inventory units are the only top-level resources outside the case hierarchy; every other resource is addressed through its parent case. The stored records mirror that hierarchy: every case-child record persists its parent linkage in a `case_id` field, and deeper records carry their own parent keys — a quote line item its `quote_id`, an invoice line item its `invoice_id`, a funding allocation its `funding_source_id` — so the URL path and the stored references always agree about which aggregate a record belongs to.

### 2.8. Derived Case Totals and Funding Posture

Each case maintains a small ledger of derived totals, recomputed whenever the underlying records change. `total_quoted_cents` is the sum of all line items across the case's active quotes. `total_funded_cents` is the sum of the approved amounts of all of the case's funding sources whose status is APPROVED. `total_billed_cents` is the sum of the totals of all invoices in SENT or PAID status, and `total_paid_cents` is the sum of the totals of all invoices in PAID status. `balance_due_cents` is the billed total minus the paid total and is never allowed to go negative.

From the quoted and funded totals the case derives its `funding_posture`, one of four exact values. When `total_funded_cents` is zero the posture is `UNFUNDED`. When the funded amount is greater than zero but strictly less than `total_quoted_cents` the posture is `PARTIALLY_FUNDED`. When the funded amount exactly equals the quoted total the posture is `FULLY_FUNDED`. When the funded amount exceeds the quoted total the posture is `OVERFUNDED`. The posture is recomputed every time a funding source is approved, denied, or withdrawn, and every time an allocation is committed or reversed.

### 2.9. The Logical Clock and Time-Driven Transitions

Several lifecycle rules depend on the current date: quotes expire, rentals activate, invoices go overdue, consultations become no-shows, and reassessments become overdue. To make these deterministic, the server keeps a logical clock. On startup the logical clock reads 2026-05-01T00:00:00Z, and a `SystemAdmin` may advance it through a test-driving capability that sets the current UTC instant to a supplied `to_iso8601` value. Every date comparison in this document — "in the past", "reached", "passes" — is evaluated against this logical clock.

The time-driven transitions are: a quote in DRAFT, SUBMITTED, or UNDER_REVIEW whose `valid_until` has passed becomes EXPIRED; an invoice in SENT or PARTIALLY_PAID whose `due_date` has passed with a positive balance becomes OVERDUE; an OT consultation still SCHEDULED once its `scheduled_date` has passed becomes NO_SHOW; a reassessment schedule in PENDING or SCHEDULED whose `due_date` has passed becomes OVERDUE; and an installed rental ramp becomes IN_USE automatically while its rental period is active.

## 3. Business Logic & Workflows

### 3.1. Case Intake and Clinical Assessment

An `IntakeCoordinator` opens a case by supplying the client's `client_name`, `client_address`, and `client_phone`, plus an optional `referral_source` drawn from `PHYSICIAN`, `OT`, `VA`, `SELF`, and `AGENCY`; when no referral source is supplied it defaults to `SELF`. The new case starts in `INTAKE` status with its computed fields initialized: all ledger totals at zero and `funding_posture` at `UNFUNDED`. From this point the case's `status` walks a fixed corridor — `INTAKE` → `ASSESSMENT_SCHEDULED` → `ASSESSED` → `QUOTE_DRAFTED` → `QUOTE_SUBMITTED` → `FUNDING_PENDING` → `FUNDING_APPROVED` → `INSTALLATION_SCHEDULED` → `INSTALLED` → `INSPECTED` → `WARRANT_ACTIVE` → `CLOSED` — with `CANCELLED` reachable from every state up to and including `INSTALLATION_SCHEDULED`. `CLOSED` and `CANCELLED` are terminal.

Clinical evaluation begins when an `IntakeCoordinator` or an `Assessor` creates an assessment under the case, providing `assessor_id`, an `assessor_role` of `OT`, `CAPS`, or `BOTH`, an `assessment_type` of `INITIAL`, `REASSESSMENT`, or `POST_INSTALL`, a `scheduled_date`, the baseline `mobility_score` (a 0–100 measure of mobility limitation) and `hazard_count`, and optionally a list of `recommended_modifications` codes and free-text `notes`. A `scheduled_date` in the past is rejected with `ERR_INVALID_SCHEDULE_DATE`. The assessment is created in `SCHEDULED` status, and creating it moves the case from `INTAKE` to `ASSESSMENT_SCHEDULED`.

When the scheduled day arrives — the `scheduled_date` must have been reached — the assigned `Assessor` starts the assessment, moving it from `SCHEDULED` to `IN_PROGRESS`; attempting to start an assessment that is not in `SCHEDULED` fails with `ERR_ASSESSMENT_NOT_SCHEDULED`. Completing the assessment requires all required scores: the assessor submits the final `mobility_score`, `hazard_count`, and `recommended_modifications`, with optional `notes`. On completion the assessment moves to `COMPLETED`, its `completed_date` is stamped, and the server computes four derived values. First, `ada_compliance_pct`: five aspects of the home are each scored from 0 to 100 — entrance access weighted at 25 percent, interior circulation at 20 percent, bathroom access at 25 percent, kitchen access at 15 percent, and bedroom access at 15 percent — and the percentage is the weighted sum of those five factor scores, held at two decimal places. Second, `caps_recommendation_score`, a 0–100 CAPS scope recommendation derived from the same visit. Third and fourth, two booleans: `rental_eligible`, whether a rental ramp is clinically appropriate for this client, and `purchase_required`, whether a permanent installation is medically necessary. The safety risk of the household is captured as `safety_risk_index` on the case: each identified hazard contributes half a point (the `hazard_count` multiplied by 0.5), and the shortfall of the `mobility_score` below 100 contributes five hundredths of a point per point of shortfall (multiplied by 0.05); the sum is clamped so it never falls below 0.0 and never exceeds 10.0, then rounded to one decimal place.

Completing an assessment also re-evaluates the parent case. When every `INITIAL` assessment on the case has reached `COMPLETED`, the case advances from `ASSESSMENT_SCHEDULED` to `ASSESSED`; at that moment the case's `ada_scope_score` is set to the whole-number rounding of the most recent assessment's `ada_compliance_pct`, its `caps_scope_score` is taken from the latest assessment, and its `safety_risk_index` is recomputed as described above. An assessment that will not happen can be cancelled by an `IntakeCoordinator` from either `SCHEDULED` or `IN_PROGRESS`, moving it to `CANCELLED`.

### 3.2. Occupational Therapy Collaboration

Alongside formal assessments, a case may involve occupational therapists in an advisory capacity. An `IntakeCoordinator` or an `Assessor` schedules an OT consultation by providing the `ot_provider_id`, a `consultation_type` of `INITIAL_EVAL`, `FOLLOW_UP`, `DISCHARGE_PLANNING`, or `HOME_SAFETY`, a `scheduled_date`, and the therapy `goals` as a list. The consultation is created in `SCHEDULED` status.

Three endings exist. An `Assessor` completes the consultation by submitting the therapist's `recommendations`; the consultation moves to `COMPLETED`, its `completed_date` is stamped, and the server records in `clearance_given` whether the therapist cleared the client for discharge. An `IntakeCoordinator` may instead cancel a scheduled consultation, moving it to `CANCELLED`. And if the `scheduled_date` passes with no completion recorded, the consultation becomes `NO_SHOW` on its own. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are all terminal.

### 3.3. Quoting, Revisions, and Cost Composition

Once a case is `ASSESSED` — with at least one `COMPLETED` assessment on file — a `ProjectManager` drafts a quote. The create request carries the quote's `valid_until` expiration date, an optional `contingency_pct`, and the concurrency guard `expected_case_version` described in §2.4; quoting a case that has not reached `ASSESSED` is rejected with `ERR_CASE_NOT_ASSESSED`, and a stale guard value is rejected with `ERR_STALE_VERSION`. The server assigns a human-readable `quote_number` in the format Q-YYYYMMDD-NNN and a `revision` number: the first quote on a case is revision 1, and each subsequent quote created for the same case increments the revision. Creating a new revision has an immediate consequence for its predecessor — any existing quote of the same case still in `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW` is moved to `SUPERSEDED`, its `superseded_by_id` is pointed at the new quote, and every still-`PENDING` funding allocation attached to the old quote is `RELEASED`. Drafting the first quote moves the case from `ASSESSED` to `QUOTE_DRAFTED`, and the quote itself is born in `DRAFT`.

A quote is priced line by line. A `ProjectManager` adds line items to a `DRAFT` quote — attempting to add one to a quote in any other state fails with `ERR_QUOTE_NOT_DRAFT` — supplying `line_type` (one of `LABOR`, `MATERIAL`, `PERMIT`, `EQUIPMENT_RENTAL`, `EQUIPMENT_PURCHASE`, `DEMOLITION`, `ELECTRICAL`, `PLUMBING`), a free-text `description`, a `quantity`, a `unit` of measure such as hour, sqft, each, or day, the `unit_price_cents`, a `sort_order` controlling display order, and optionally `is_taxable` (defaulting to true), `tax_rate_pct` (defaulting to 0.0), and `funding_eligible` (defaulting to true, marking the line as eligible for waiver, VA, or grant money). Both `quantity` and `unit_price_cents` must be positive; a line violating this is rejected with `ERR_INVALID_LINE_ITEM`.

Every line addition or modification recomputes the quote's money fields, and the arithmetic is precise. Each line's `extended_price_cents` is its `quantity` multiplied by its `unit_price_cents`, rounded half up to whole cents. Each line's `tax_cents` is that extended price multiplied by the line's `tax_rate_pct` and divided by 100, rounded half up to whole cents — but only when `is_taxable` is true; a non-taxable line's tax is exactly zero. The quote's `labor_cost_cents` is the sum of the extended prices of all `LABOR` lines, `material_cost_cents` the sum over `MATERIAL` lines, `permit_fee_cents` the sum over `PERMIT` lines, and `equipment_cost_cents` the sum over `EQUIPMENT_RENTAL` and `EQUIPMENT_PURCHASE` lines together. The `subtotal_cents` adds up the extended prices of every line — labor, material, permit, equipment, demolition, electrical, and plumbing alike. The `contingency_cents` is the subtotal multiplied by `contingency_pct` and divided by 100, rounded half up to whole cents; the contingency percentage defaults to 10.0 when not supplied and may never exceed 25.0. Finally, `total_cents` is the subtotal plus the contingency minus any applied `discount_cents`, and the quote's total tax is the sum of all line tax amounts.

Submitting the quote is a `ProjectManager` action with two preconditions, evaluated in the order given in §2.6: the quote must contain at least one line item (otherwise `ERR_QUOTE_EMPTY`), and `valid_until` must still lie in the future. Submission moves the quote from `DRAFT` to `SUBMITTED`, stamps `submitted_at`, computes `funding_gap_cents` as the quote's `total_cents` minus the case's `total_funded_cents` with the result floored at zero so it can never be negative, and moves the case from `QUOTE_DRAFTED` to `QUOTE_SUBMITTED`. When funding is sought for the submitted quote, the case moves on to `FUNDING_PENDING`.

Review belongs to the `FundingCoordinator`. Starting review moves the quote from `SUBMITTED` to `UNDER_REVIEW`. Approving the quote requires that sufficient funding has been allocated — or that self-pay has been approved — to cover the total; an approval attempt without sufficient funding behind it is rejected with `ERR_INSUFFICIENT_FUNDING` (HTTP 402). A successful approval moves the quote to `APPROVED`, stamps `decided_at`, and commits money: every `PENDING` funding allocation attached to the quote becomes `COMMITTED`, each such allocation's `committed_at` is stamped, and each allocation's amount is subtracted from its funding source's `remaining_cents`. Rejection moves the quote from `UNDER_REVIEW` to `REJECTED`, stamps `decided_at`, and releases every `PENDING` allocation back to `RELEASED`. Independently of review, if the current date passes a quote's `valid_until` while it sits in `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW`, the quote becomes `EXPIRED` and its pending allocations are likewise released. `APPROVED`, `REJECTED`, `SUPERSEDED`, and `EXPIRED` are all terminal for a quote.

### 3.4. Funding Sources, Allocation, and the Draw Waterfall

Few clients pay cash for a ramp; most cases assemble money from several programs. A `FundingCoordinator` registers each source under the case with a `source_type` of `MEDICAID_WAIVER`, `VA_BENEFIT`, `STATE_GRANT`, `PRIVATE_INSURANCE`, `SELF_PAY`, or `CHARITY`, the specific `program_name`, the `requested_cents` sought, and a `priority_rank` fixing the draw order — rank 1 draws first. Optional fields are the external `application_number`, an `expiration_date` after which the money lapses, and a list of `restrictions` codes such as NO_RENTAL or PERMANENT_ONLY. The source is created in `PENDING` status.

Decisions are `FundingCoordinator` actions. Approving a source requires a positive `approved_cents` in the request — a request missing it or carrying a non-positive value fails as `ERR_INVALID_REQUEST` — and carries the `expected_case_version` guard from §2.4, rejected with `ERR_STALE_VERSION` when stale. Approval moves the source from `PENDING` to `APPROVED`, stamps `decision_date`, and initializes `remaining_cents` equal to the full `approved_cents`; the case's `funding_posture` is then recomputed. Denial moves the source from `PENDING` to `DENIED`, stamps `decision_date`, and likewise recomputes the posture. Withdrawal moves a `PENDING` source to `WITHDRAWN` and releases every `PENDING` allocation it held. Once an approved source's `remaining_cents` is drawn down to exactly zero, the source moves from `APPROVED` to `EXHAUSTED` on its own. `APPROVED`, `DENIED`, `WITHDRAWN`, and `EXHAUSTED` are all terminal. The moment the sum of approved funding across the case reaches or exceeds the submitted quote's `total_cents`, the case advances from `FUNDING_PENDING` to `FUNDING_APPROVED` and its posture reads `FULLY_FUNDED`.

Allocations connect sources to quotes. A `FundingCoordinator` creates an allocation under a funding source by naming the `quote_id` being funded, the `amount_cents`, and an `allocation_type` of `QUOTE_LEVEL` or `LINE_LEVEL`; a line-level allocation additionally names the specific `quote_line_item_id` it pays for. Two guards apply. The amount must not exceed the source's `remaining_cents`, or the create fails with `ERR_ALLOCATION_EXCEEDS_REMAINING`. And the source's `restrictions` must permit the target: a source carrying the NO_RENTAL restriction can never be allocated to rental line items, and any allocation that conflicts with a restriction fails with `ERR_FUNDING_RESTRICTION_VIOLATION`. A new allocation starts in `PENDING` and stays there until the quote's decision: quote approval commits allocations as described in §3.3, while rejection, supersession, expiry, or source withdrawal releases them — a `RELEASED` allocation returns its buying power to the source.

When a quote is approved with more funding available than a single source provides, the server draws the sources down as a waterfall. Funding sources are ordered by `priority_rank` ascending — the source ranked 1 draws first — and ties are broken by `created_at` ascending, the earliest-registered source first. Walking that order, each source with a positive `remaining_cents` contributes the lesser of its remaining balance and the quote's still-unfunded need, an allocation of that amount is created against it, and both the source's remainder and the quote's need are reduced accordingly. The walk stops as soon as the quote is fully funded or no source with money remains, and restriction codes are honored throughout, so a NO_RENTAL source is simply skipped over rental lines.

A committed allocation is not irrevocable. A `FundingCoordinator` may reverse a `COMMITTED` allocation provided no invoice has yet been paid against it; reversal moves the allocation to `REVERSED`, adds its `amount_cents` back to the source's `remaining_cents`, and recomputes the case's `total_funded_cents`. `COMMITTED`, `RELEASED`, and `REVERSED` are the allocation's terminal states.

### 3.5. Installation, Permits, and Inspection

With funding secured — the case in `FUNDING_APPROVED`, or an approved self-pay source covering the work — a `ProjectManager` schedules the build. Scheduling against a case without approved funding fails with `ERR_CASE_NOT_FUNDED`, and the permit situation must be clean: the job's `permit_status` must be `NOT_REQUIRED` or `ISSUED` at scheduling time. The create request names the governing `quote_id`, the `scheduled_start` and `scheduled_end` dates, the `crew_lead_id` of the lead installer, and optionally the `permit_number` and a `warranty_months` duration that defaults to 12 months when omitted. The server assigns a human-readable `job_number`, derives `inspection_required` (whether a final inspection is needed), and tracks `progress_pct` as a 0–100 completion percentage. The job starts in `SCHEDULED` with `permit_status` drawn from `NOT_REQUIRED`, `PENDING`, `ISSUED`, `EXPIRED`, and `CLOSED`, and an `inspection_status` drawn from `NOT_SCHEDULED`, `SCHEDULED`, `PASSED`, `FAILED`, and `WAIVED`; scheduling it moves the case from `FUNDING_APPROVED` to `INSTALLATION_SCHEDULED`.

The build itself is driven by the crew. The `ProjectManager` marks materials ordered, moving the job from `SCHEDULED` to `MATERIALS_ORDERED`. On or after the `scheduled_start` date the `CrewLead` starts work: the job moves from `MATERIALS_ORDERED` to `IN_PROGRESS` and `actual_start` is stamped. When the remaining work reduces to corrective items the `CrewLead` enters the punch-list phase, moving the job from `IN_PROGRESS` to `PUNCH_LIST` — requesting that transition while the job is not `IN_PROGRESS` fails with `ERR_JOB_NOT_IN_PROGRESS`. Completion is allowed from either `IN_PROGRESS` or `PUNCH_LIST`, but only when `progress_pct` has reached 100 and no safety-critical punch-list items remain unresolved; unresolved safety items block completion with `ERR_SAFETY_ITEMS_UNRESOLVED`. A successful completion stamps `actual_end`, sets the job's `warranty_start_date` equal to `actual_end`, moves the job to `COMPLETED`, moves the case from `INSTALLATION_SCHEDULED` to `INSTALLED`, and automatically creates a post-install reassessment schedule due 30 days after completion (see §3.9). A job that has not yet started — `actual_start` still null — may be cancelled by the `ProjectManager` from `SCHEDULED` or `MATERIALS_ORDERED`; cancellation moves it to `CANCELLED` and reverses all committed funding allocations tied to the work, returning their amounts to the sources.

Inspections stand beside the job. An `Inspector` or `ProjectManager` schedules one with an `inspection_type` of `PRE_INSTALL`, `ROUGH`, `FINAL`, `WARRANTY`, or `REASSESSMENT`, the `inspector_id`, a `scheduled_date`, and optionally the `installation_job_id` being inspected; a `FINAL` inspection whose `scheduled_date` does not fall after the job's `actual_end` is rejected with `ERR_INSPECTION_BEFORE_COMPLETION`. The inspection is created with its `outcome` at `PENDING` — the full outcome vocabulary being `PENDING`, `PASSED`, `FAILED`, and `CONDITIONAL_PASS` — and may carry a list of `deficiencies` codes.

Recording the outcome is the `Inspector`'s call. Passing requires that no safety-critical deficiencies stand; the inspection moves from `PENDING` to `PASSED`, its `completed_date` is stamped, and `ada_compliant` is set to true. When the passed inspection is of `FINAL` type, two cascades follow: the installation job's `inspection_status` becomes `PASSED`, and the case advances from `INSTALLED` to `INSPECTED` and then, automatically and without further action, to `WARRANT_ACTIVE` as the warranty period begins. Failing needs no precondition: the `Inspector` supplies the `deficiencies` list and a `correction_deadline`, the inspection moves from `PENDING` to `FAILED`, `completed_date` is stamped, `reinspection_required` is set to true, and when the failed inspection is of `FINAL` type the linked installation job remains in `IN_PROGRESS` rather than advancing. `PASSED` and `FAILED` are terminal outcomes.

### 3.6. The Rental Ramp Program and Inventory Fleet

Some clients need a ramp for months, not forever — post-surgical recovery, a visiting relative, a hospice situation. For them the program maintains a physical fleet. A `LogisticsCoordinator` registers each unit with its `unit_tag` asset label, a `ramp_type` of `MODULAR_ALUMINUM`, `PORTABLE_THRESHOLD`, `SUITCASE`, or `CUSTOM_WOOD`, the `length_feet` and `width_inches` dimensions, the `weight_capacity_lbs` rating, the standard `monthly_rate_cents`, the `purchase_price_cents` if sold, and optionally a `condition_grade` of `A`, `B`, `C`, or `D` that defaults to `A`. Units are created `AVAILABLE` and accumulate `total_rental_days` over their service life; while deployed, `current_case_id` identifies the case the unit is serving. Fleet housekeeping belongs to the `LogisticsCoordinator`: a unit in `AVAILABLE` or `DEPLOYED` may be sent to `MAINTENANCE`, a unit in `MAINTENANCE` may be returned to `AVAILABLE`, and a unit in `AVAILABLE` or `MAINTENANCE` may be `RETIRED`, which is terminal.

A rental reservation is created under a case by a `LogisticsCoordinator` naming the `inventory_unit_id`, the `rental_start` and `rental_end` dates, and optionally the `billing_cycle_day` of the month on which billing recurs, defaulting to 1. Two clinical and logistical guards apply, in the order of §2.6: if the case's assessment indicates `purchase_required` — permanent installation is medically necessary — the reservation is refused with `ERR_RENTAL_NOT_CLINICALLY_INDICATED`, and if the requested period overlaps an existing active rental of the same unit the reservation is refused with `ERR_UNIT_UNAVAILABLE` (HTTP 409).

Pricing follows a duration-tiered schedule computed at reservation time. The base rate is the unit's `monthly_rate_cents`. A rental of one to three months bills at 100 percent of that base rate; four to six months bills at 90 percent; seven to twelve months bills at 80 percent; and thirteen months or longer bills at 70 percent. The reservation's `monthly_rate_cents` is the base rate multiplied by the applicable tier multiplier, rounded half up to whole cents. The `deposit_cents` is the lesser of two months of the computed monthly rate and 20 percent of the unit's `purchase_price_cents`. The reservation starts in `RESERVED` with its `deposit_status` at `HELD`, and creating it moves the referenced unit from `AVAILABLE` to `RESERVED`.

From there the rental has a physical lifecycle. On or after `rental_start`, and while the unit still reads `RESERVED`, a `LogisticsCoordinator` records delivery: the rental moves from `RESERVED` to `DELIVERED` and the unit from `RESERVED` to `DEPLOYED`. A `CrewLead` then installs the ramp, moving the rental from `DELIVERED` to `INSTALLED`, and while the rental period is active the system moves the rental from `INSTALLED` to `IN_USE` on its own. When the ramp is no longer needed a `LogisticsCoordinator` schedules pickup, moving the rental from `IN_USE` or `INSTALLED` to `PICKUP_SCHEDULED`, and later confirms pickup: the rental moves to `RETURNED`, `actual_pickup` is stamped, the unit returns from `DEPLOYED` to `AVAILABLE` with the rental's duration added to its `total_rental_days` — that duration is the number of whole days elapsed between the reservation's `rental_start` and the logical-clock instant at which pickup is confirmed, never less than zero, the deposit's `deposit_status` becomes `REFUNDED` or `FORFEITED` according to the unit's returned condition, and a final invoice is generated for any unbilled period (see §3.7). A reservation that has not been delivered may instead be cancelled by a `LogisticsCoordinator`, moving the rental from `RESERVED` to `CANCELLED`, the unit back to `AVAILABLE`, and the deposit to `REFUNDED`. `RETURNED` and `CANCELLED` are terminal.

### 3.7. Invoicing, Payments, and Rental Billing Cycles

Billing is case-centric: every invoice hangs under a case and feeds the case ledger of §2.8. A `BillingCoordinator` creates an invoice with an `invoice_type` of `INSTALLATION`, `RENTAL_MONTHLY`, `RENTAL_FINAL`, `SERVICE_CALL`, or `WARRANTY_WORK`, a `due_date`, and the `expected_case_version` guard; when billing a third party the invoice names the `funding_source_id` to charge, and it may also reference the originating `quote_id` or `rental_ramp_id`. The server assigns a human-readable `invoice_number`, stamps nothing yet, and creates the invoice in `DRAFT`. One fiscal guard applies at creation: an invoice billed to a funding source must not total more than the case's `total_funded_cents`, or the create fails with `ERR_INVOICE_EXCEEDS_FUNDING`.

Lines are added to the draft with a `description`, `quantity`, and `unit_price_cents`, plus an optional `tax_rate_pct` and, for rental billing, the service window's `period_start` and `period_end`. Each line's `extended_price_cents` is its quantity multiplied by its unit price, rounded half up to whole cents; its `tax_cents` is the extended price multiplied by the supplied tax rate and divided by 100, rounded half up to whole cents; and its `line_total_cents` is the extended price plus the tax. The invoice's `subtotal_cents` is the sum of all extended prices, its `tax_cents` the sum of all line taxes, and its `total_cents` the subtotal plus the tax. Its `balance_cents` is the total minus `amount_paid_cents`, which starts at zero.

Sending requires at least one line item and carries the `expected_case_version` guard from §2.4, rejected with `ERR_STALE_VERSION` when stale. Sending moves the invoice from `DRAFT` to `SENT`, stamps `issue_date`, adds the invoice's `total_cents` into the case's `total_billed_cents`, and recomputes the case's `balance_due_cents`.

Collection is incremental. A `BillingCoordinator` records a payment of `amount_cents` against a `SENT` or `PARTIALLY_PAID` invoice. A payment larger than the outstanding balance is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. A positive payment smaller than the balance moves the invoice to `PARTIALLY_PAID`, adds the payment into `amount_paid_cents` and into the case's `total_paid_cents`, and recomputes the balance due. A payment exactly equal to the balance moves the invoice to `PAID`, stamps `paid_date`, brings `amount_paid_cents` level with `total_cents`, and recomputes the case totals. Should the `due_date` pass with money still outstanding, an invoice in `SENT` or `PARTIALLY_PAID` becomes `OVERDUE` on its own.

Two escapes exist. A `BillingCoordinator` may void an invoice in `DRAFT`, `SENT`, `PARTIALLY_PAID`, or `OVERDUE` provided nothing has been paid against it — `amount_paid_cents` must be zero — which moves it to `VOID` and subtracts its total back out of the case's `total_billed_cents`, recomputing the balance due. And the `Client` may dispute a `SENT` invoice, moving it to `DISPUTED`. `PAID` and `VOID` are terminal.

Rental billing runs on a monthly cycle driven by the logical clock. For each rental ramp in active use, the run counts the days between the rental's `last_billed_date` and the current date, and prices the period as the rental's `monthly_rate_cents` multiplied by those days and divided by the number of days in the month, rounded half up to whole cents. Each period becomes an invoice line carrying its `period_start` and `period_end`, the lines are grouped by case into a single `RENTAL_MONTHLY` invoice per case, and each rental's `last_billed_date` advances to the billed-through date. When a rental is returned, any unbilled tail period is invoiced at once as a `RENTAL_FINAL` invoice as part of pickup confirmation.

### 3.8. Warranty Service and Case Closure

Every completed installation carries a warranty running `warranty_months` months — twelve unless the job specified otherwise — from the job's `warranty_start_date`, and the case sits in `WARRANT_ACTIVE` for that period. When something goes wrong, the `Client` or a `ProjectManager` opens a warranty claim naming the `installation_job_id` under warranty, an `issue_description`, and a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `SAFETY_CRITICAL`. The server assigns a human-readable `claim_number`, stamps `reported_date`, determines whether the claim falls under the warranty terms and records that in `covered_by_warranty`, and opens the claim in `OPEN` status.

Work flows through the crew. A `ProjectManager` assigns the claim, moving it from `OPEN` to `ASSIGNED`; the `CrewLead` starts the work, moving it from `ASSIGNED` to `IN_PROGRESS`; and the `CrewLead` resolves it by supplying a `resolution_type` of `REPAIR`, `REPLACE`, `REFUND`, or `DENIED` together with the `cost_cents` of the resolution — both are required — which stamps `resolved_date` and moves the claim to `RESOLVED`. When the resolved claim was not covered by the warranty, resolution additionally generates an invoice for the resolution cost so the client is billed. A `ProjectManager` may instead deny a claim in `OPEN` or `ASSIGNED`, moving it to `DENIED`, or close a claim in `OPEN`, `ASSIGNED`, or `IN_PROGRESS`, moving it to `CLOSED`. `RESOLVED`, `DENIED`, and `CLOSED` are terminal.

Closing the whole case is a `ProjectManager` action available once the case is `WARRANT_ACTIVE`, and it is guarded on three fronts: no warranty claim may still stand in `OPEN` status, no invoice may remain unpaid with a balance above zero, and every rental ramp on the case must be `RETURNED` or `CANCELLED`. Meeting all three moves the case from `WARRANT_ACTIVE` to `CLOSED`. Attempts to keep operating a case that has already reached `CLOSED` or `CANCELLED` are rejected with `ERR_CASE_ALREADY_CLOSED`, and any child operation against a case in a terminal state is rejected with `ERR_CASE_NOT_ACTIVE`.

Cancellation is the other ending, and it is deliberately destructive. A `ProjectManager` may cancel a case from any state from `INTAKE` through `INSTALLATION_SCHEDULED` inclusive, provided no installation job sits in a non-terminal state and no rental ramp is still active. Cancellation moves the case to `CANCELLED` and cascades: every non-terminal assessment becomes `CANCELLED`, every quote in `DRAFT` or `SUBMITTED` becomes `SUPERSEDED`, every `PENDING` funding source becomes `WITHDRAWN`, and every `SCHEDULED` OT consultation becomes `CANCELLED`.

### 3.9. Reassessment and Long-Term Follow-Up

Accessibility needs drift — conditions progress, equipment wears, families rearrange furniture. The system tracks follow-up through reassessment schedules. One is created automatically, with `auto_generated` set to true and `trigger_event` of `POST_INSTALL`, whenever an installation job completes: its `due_date` falls 30 days after the job's completion. An `IntakeCoordinator` or `ProjectManager` may also create one manually, supplying a `trigger_event` of `POST_INSTALL`, `TIME_BASED`, `CONDITION_CHANGE`, or `REQUEST`, a `due_date`, and optionally a `priority` of `ROUTINE`, `URGENT`, or `EMERGENT` that defaults to `ROUTINE`. Every schedule starts in `PENDING`.

An `IntakeCoordinator` schedules the follow-up visit, moving the schedule from `PENDING` to `SCHEDULED`. When the reassessment itself — an assessment created under the same case, typically of `assessment_type` `REASSESSMENT` or `POST_INSTALL` — is completed, the schedule moves from `PENDING` or `SCHEDULED` to `COMPLETED` and its `linked_assessment_id` identifies the assessment that satisfied it. If the `due_date` passes while the schedule is still `PENDING` or `SCHEDULED`, it becomes `OVERDUE`. A `ProjectManager` may waive a schedule in `PENDING`, `SCHEDULED`, or `OVERDUE`, moving it to `WAIVED`. `COMPLETED` and `WAIVED` are terminal.

## 4. Endpoint Definitions

All endpoints share the mount prefixes shown below. Operations that create a new resource respond with HTTP 201; operations that modify, transition, or act on an existing resource respond with HTTP 200; reads respond with HTTP 200. Unless a row says otherwise, the response body carries the affected resource in the standard envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/cases` | Create a new case | IntakeCoordinator |
| GET | `/cases` | List all cases | Any |
| GET | `/cases/{caseId}` | Get a specific case | Any |
| POST | `/cases/{caseId}/cancel` | Cancel a case | ProjectManager |
| POST | `/cases/{caseId}/close` | Close a case from WARRANTY_ACTIVE | ProjectManager |
| POST | `/cases/{caseId}/assessments` | Create an assessment | IntakeCoordinator, Assessor |
| GET | `/cases/{caseId}/assessments` | List assessments for a case | Any |
| GET | `/cases/{caseId}/assessments/{assessmentId}` | Get a specific assessment | Any |
| POST | `/cases/{caseId}/assessments/{assessmentId}/start` | Start an assessment | Assessor |
| POST | `/cases/{caseId}/assessments/{assessmentId}/complete` | Complete an assessment | Assessor |
| POST | `/cases/{caseId}/assessments/{assessmentId}/cancel` | Cancel an assessment | IntakeCoordinator |
| POST | `/cases/{caseId}/quotes` | Create a quote | ProjectManager |
| GET | `/cases/{caseId}/quotes` | List quotes for a case | Any |
| GET | `/cases/{caseId}/quotes/{quoteId}` | Get a specific quote | Any |
| POST | `/cases/{caseId}/quotes/{quoteId}/line-items` | Add a line item to a quote | ProjectManager |
| POST | `/cases/{caseId}/quotes/{quoteId}/submit` | Submit a quote for review | ProjectManager |
| POST | `/cases/{caseId}/quotes/{quoteId}/start-review` | Start quote review | FundingCoordinator |
| POST | `/cases/{caseId}/quotes/{quoteId}/approve` | Approve a quote | FundingCoordinator |
| POST | `/cases/{caseId}/quotes/{quoteId}/reject` | Reject a quote | FundingCoordinator |
| POST | `/cases/{caseId}/funding-sources` | Create a funding source | FundingCoordinator |
| GET | `/cases/{caseId}/funding-sources` | List funding sources for a case | Any |
| GET | `/cases/{caseId}/funding-sources/{sourceId}` | Get a specific funding source | Any |
| POST | `/cases/{caseId}/funding-sources/{sourceId}/approve` | Approve a funding source | FundingCoordinator |
| POST | `/cases/{caseId}/funding-sources/{sourceId}/deny` | Deny a funding source | FundingCoordinator |
| POST | `/cases/{caseId}/funding-sources/{sourceId}/withdraw` | Withdraw a funding source | FundingCoordinator |
| POST | `/cases/{caseId}/funding-sources/{sourceId}/allocations` | Create a funding allocation | FundingCoordinator |
| GET | `/cases/{caseId}/funding-sources/{sourceId}/allocations` | List allocations for a funding source | Any |
| POST | `/cases/{caseId}/funding-sources/{sourceId}/allocations/{allocId}/reverse` | Reverse a committed allocation | FundingCoordinator |
| POST | `/cases/{caseId}/installation-jobs` | Create an installation job | ProjectManager |
| GET | `/cases/{caseId}/installation-jobs` | List installation jobs for a case | Any |
| GET | `/cases/{caseId}/installation-jobs/{jobId}` | Get a specific installation job | Any |
| POST | `/cases/{caseId}/installation-jobs/{jobId}/order-materials` | Mark materials ordered | ProjectManager |
| POST | `/cases/{caseId}/installation-jobs/{jobId}/start` | Start installation | CrewLead |
| POST | `/cases/{caseId}/installation-jobs/{jobId}/punch-list` | Enter punch list phase | CrewLead |
| POST | `/cases/{caseId}/installation-jobs/{jobId}/complete` | Complete installation | CrewLead |
| POST | `/cases/{caseId}/installation-jobs/{jobId}/cancel` | Cancel an installation job | ProjectManager |
| POST | `/cases/{caseId}/rental-ramps` | Create a rental ramp reservation | LogisticsCoordinator |
| GET | `/cases/{caseId}/rental-ramps` | List rental ramps for a case | Any |
| GET | `/cases/{caseId}/rental-ramps/{rampId}` | Get a specific rental ramp | Any |
| POST | `/cases/{caseId}/rental-ramps/{rampId}/deliver` | Deliver a rental ramp | LogisticsCoordinator |
| POST | `/cases/{caseId}/rental-ramps/{rampId}/install` | Install a rental ramp | CrewLead |
| POST | `/cases/{caseId}/rental-ramps/{rampId}/schedule-pickup` | Schedule rental pickup | LogisticsCoordinator |
| POST | `/cases/{caseId}/rental-ramps/{rampId}/confirm-pickup` | Confirm rental pickup | LogisticsCoordinator |
| POST | `/cases/{caseId}/rental-ramps/{rampId}/cancel` | Cancel a rental reservation | LogisticsCoordinator |
| POST | `/inventory-units` | Create an inventory unit | LogisticsCoordinator |
| GET | `/inventory-units` | List inventory units | Any |
| GET | `/inventory-units/{unitId}` | Get a specific inventory unit | Any |
| POST | `/inventory-units/{unitId}/maintenance` | Send a unit to maintenance | LogisticsCoordinator |
| POST | `/inventory-units/{unitId}/return-to-service` | Return a unit from maintenance | LogisticsCoordinator |
| POST | `/inventory-units/{unitId}/retire` | Retire an inventory unit | LogisticsCoordinator |
| POST | `/cases/{caseId}/inspections` | Schedule an inspection | Inspector, ProjectManager |
| GET | `/cases/{caseId}/inspections` | List inspections for a case | Any |
| GET | `/cases/{caseId}/inspections/{inspectionId}` | Get a specific inspection | Any |
| POST | `/cases/{caseId}/inspections/{inspectionId}/pass` | Pass an inspection | Inspector |
| POST | `/cases/{caseId}/inspections/{inspectionId}/fail` | Fail an inspection | Inspector |
| POST | `/cases/{caseId}/invoices` | Create an invoice | BillingCoordinator |
| GET | `/cases/{caseId}/invoices` | List invoices for a case | Any |
| GET | `/cases/{caseId}/invoices/{invoiceId}` | Get a specific invoice | Any |
| POST | `/cases/{caseId}/invoices/{invoiceId}/line-items` | Add a line item to an invoice | BillingCoordinator |
| POST | `/cases/{caseId}/invoices/{invoiceId}/send` | Send an invoice | BillingCoordinator |
| POST | `/cases/{caseId}/invoices/{invoiceId}/record-payment` | Record a payment | BillingCoordinator |
| POST | `/cases/{caseId}/invoices/{invoiceId}/void` | Void an invoice | BillingCoordinator |
| POST | `/cases/{caseId}/invoices/{invoiceId}/dispute` | Dispute an invoice | Client |
| POST | `/cases/{caseId}/warranty-claims` | Create a warranty claim | Client, ProjectManager |
| GET | `/cases/{caseId}/warranty-claims` | List warranty claims for a case | Any |
| GET | `/cases/{caseId}/warranty-claims/{claimId}` | Get a specific warranty claim | Any |
| POST | `/cases/{caseId}/warranty-claims/{claimId}/assign` | Assign a warranty claim | ProjectManager |
| POST | `/cases/{caseId}/warranty-claims/{claimId}/start` | Start warranty work | CrewLead |
| POST | `/cases/{caseId}/warranty-claims/{claimId}/resolve` | Resolve a warranty claim | CrewLead |
| POST | `/cases/{caseId}/warranty-claims/{claimId}/deny` | Deny a warranty claim | ProjectManager |
| POST | `/cases/{caseId}/ot-consultations` | Schedule an OT consultation | IntakeCoordinator, Assessor |
| GET | `/cases/{caseId}/ot-consultations` | List OT consultations for a case | Any |
| GET | `/cases/{caseId}/ot-consultations/{consultId}` | Get a specific OT consultation | Any |
| POST | `/cases/{caseId}/ot-consultations/{consultId}/complete` | Complete an OT consultation | Assessor |
| POST | `/cases/{caseId}/ot-consultations/{consultId}/cancel` | Cancel an OT consultation | IntakeCoordinator |
| POST | `/cases/{caseId}/reassessment-schedules` | Create a reassessment schedule | IntakeCoordinator, ProjectManager |
| GET | `/cases/{caseId}/reassessment-schedules` | List reassessment schedules for a case | Any |
| GET | `/cases/{caseId}/reassessment-schedules/{scheduleId}` | Get a specific reassessment schedule | Any |
| POST | `/cases/{caseId}/reassessment-schedules/{scheduleId}/schedule` | Schedule a reassessment | IntakeCoordinator |
| POST | `/cases/{caseId}/reassessment-schedules/{scheduleId}/waive` | Waive a reassessment | ProjectManager |
| POST | `/_clock/set_current_utc` | Set the system clock for testing | SystemAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are stated in §2 and §3 where the guarded workflow is described.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_FUNDING_SOURCE_NOT_FOUND` | 404 |
| `ERR_JOB_NOT_FOUND` | 404 |
| `ERR_RAMP_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_CONSULT_NOT_FOUND` | 404 |
| `ERR_SCHEDULE_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_ACTIVE` | 409 |
| `ERR_CASE_NOT_ASSESSED` | 409 |
| `ERR_CASE_NOT_FUNDED` | 409 |
| `ERR_CASE_ALREADY_CLOSED` | 409 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_QUOTE_NOT_DRAFT` | 409 |
| `ERR_ASSESSMENT_NOT_SCHEDULED` | 409 |
| `ERR_JOB_NOT_IN_PROGRESS` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_QUOTE_EMPTY` | 422 |
| `ERR_INVALID_LINE_ITEM` | 422 |
| `ERR_INVALID_SCHEDULE_DATE` | 422 |
| `ERR_RENTAL_NOT_CLINICALLY_INDICATED` | 422 |
| `ERR_FUNDING_RESTRICTION_VIOLATION` | 422 |
| `ERR_ALLOCATION_EXCEEDS_REMAINING` | 422 |
| `ERR_INVOICE_EXCEEDS_FUNDING` | 422 |
| `ERR_SAFETY_ITEMS_UNRESOLVED` | 422 |
| `ERR_UNIT_UNAVAILABLE` | 409 |
| `ERR_INSPECTION_BEFORE_COMPLETION` | 422 |
| `ERR_INSUFFICIENT_FUNDING` | 402 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_STALE_VERSION` | 412 |

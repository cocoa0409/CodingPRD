# State Business Entity Formation API — Product Requirements Document

## 1. Introduction

Every U.S. state operates a business registry that mints, supervises, and eventually retires the legal entities (limited liability companies, business corporations, and limited partnerships) that conduct commerce within its borders. The lifecycle is long-running, fiscally consequential, and procedurally segregated: formation must be approved by a state registrar, an EIN must be issued by a separate tax-side official, annual reports must be filed by the entity but accepted by a tax officer, franchise tax must be assessed and timely paid, beneficial owners must be disclosed and continuously kept current under federal BOI rules, and any operations conducted in a foreign state require a separate qualification supported by a recent certificate of good standing. The registry simultaneously serves as the authoritative compliance ledger — recording every consequential transition as an immutable event — and as a fee-collection system that calculates franchise tax under two competing methodologies, applies late fees over time, and reconciles pre-paid credits at the moment of payment.

This API is the system of record for the registry. It exposes the formation workflow, registered-agent management, operating-agreement attachment, EIN issuance, annual reporting, franchise tax assessment and payment, foreign qualification, beneficial-ownership disclosure, and administrative or voluntary dissolution. Because the registry must reflect the passage of time as a first-class concern (annual report anniversaries, tax due dates, BOI staleness windows, the 60-day administrative-dissolution waiting period after delinquency), it also exposes test-only clock-advancement and sweep endpoints that drive deferred transitions deterministically. Roles are deliberately segregated so that the entity acting as `Filer` cannot self-approve its own annual reports, EIN applications, or franchise tax acceptances; the registry encodes this separation of duties as a structural invariant rather than a soft guideline.

## 2. Global Specifications & System-Wide Principles

The whole API is mounted under the `/business-registry` prefix. Every request, regardless of endpoint, is subject to the rules in this section before any business logic in §3 is evaluated.

### 2.1. User and Role-Based Access Control

Every request must carry two custom headers: `X-User-ID` (the actor's stable identifier) and `X-User-Role` (the actor's role). When either header is absent, empty, or missing entirely, the request is rejected with `ERR_MISSING_AUTH` and HTTP 401 — this is the first check performed and precedes resource lookup, payload validation, and every other concern.

`X-User-Role` must take exactly one of the following five values: `Filer`, `StateRegistrar`, `TaxOfficer`, `ComplianceOfficer`, `RegisteredAgentService`. An additional role `TestHarness` exists exclusively for the clock-advancement and sweep endpoints described in §3.7. Any other value yields `ERR_INVALID_ROLE` with HTTP 403. When the role spelling is valid but the role is not authorized for the requested endpoint per the role-permission matrix in §4, the request is rejected with `ERR_FORBIDDEN` and HTTP 403.

Two roles are **entity-backed**, meaning their `X-User-ID` is the `id` of a row in a persisted entity. When `X-User-Role` is `Filer`, `X-User-ID` is the `id` of the acting `BusinessEntity`; ownership checks on any resource that references a `BusinessEntity` compare the resource's `business_entity_id` to `X-User-ID`. When `X-User-Role` is `RegisteredAgentService`, `X-User-ID` is the `id` of the acting `RegisteredAgent` row; that identifier is the agent the caller may resign or update.

The remaining three roles — `StateRegistrar`, `TaxOfficer`, and `ComplianceOfficer` — and the test-only `TestHarness` are **opaque**: `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it on `ComplianceEvent.payload` snapshots (for example, naming the officer who accepted an annual report or approved an EIN) but does not compare it to any entity's `id`. Crucially, however, the segregation-of-duties rule in §3.6 compares the **`Filer`** identifier (which IS entity-backed) against the row being acted upon, ensuring that the entity itself cannot self-accept, self-approve, or self-pay.

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

List endpoints accept two optional query parameters: `limit` and `offset`. The `limit` defaults to 10 when omitted, has a minimum of 1, and a maximum of 100; values outside this range are invalid input. The `offset` defaults to 0 and has a minimum of 0. The four pagination fields surfaced under `meta` are `limit`, `offset`, `total_count`, and `has_more`; `total_count` reflects the unfiltered cardinality after `where`-style filters apply, and `has_more` is true when more rows exist beyond the current page. All list endpoints sort by `created_at` in ascending order — the oldest row first — unless an endpoint description explicitly says otherwise (the compliance-events list, for instance, sorts by `occurred_at` ascending instead).

### 2.4. Common Resource Properties

Most resources in this registry carry the **common-field set**: a server-minted `id` (a UUID with no type prefix), `created_at` and `updated_at` (both ISO 8601 UTC timestamps with three fractional digits), and `version` (an integer that increments by exactly one on every mutation that the system regards as a stateful change to that resource). Concretely, `BusinessEntity`, `RegisteredAgent`, `EINApplication`, `AnnualReport`, `FranchiseTaxAssessment`, `ForeignQualification`, `BOIReport`, and `BeneficialOwner` all carry these four common fields. The remaining resources — `OperatingAgreement`, `BOIOwnership`, and `ComplianceEvent` — are lightweight join/audit rows that carry only `id` and `created_at`; they have neither `updated_at` nor `version` (operating agreements are immutable once attached, ownership rows are mutated only by soft-delete which writes `terminated_at`, and compliance events are append-only).

### 2.5. Optimistic Concurrency Control

The `PATCH` endpoints in this API — namely the agent update, annual-report revision, and foreign-qualification resubmit — accept an optional `version` field in the request body. When the client supplies a `version`, the server compares it to the persisted `version` on the row; if they do not match, the request is rejected with `ERR_VERSION_CONFLICT` and HTTP 409. When the client omits `version` from the body, the OCC check is skipped and the mutation proceeds against whatever the current row state happens to be. A successful mutation increments `version` by one and refreshes `updated_at` to the current clock instant.

### 2.6. Monetary Precision and Cents-Only Arithmetic

Every monetary quantity in this registry is stored and exchanged as **integer cents**. There are no decimal currency fields, and there is no implicit dollars-to-cents conversion: the credit balance is `credit_balance_cents`, the base tax is `base_tax_cents`, late fees are `late_fee_cents`, and so on. The franchise-tax calculations in §3 produce integer cents directly, and the only rounding that occurs is the `ceil`-style upward rounding pinned inside specific formulas (the assumed-par-value method rounds upward to the next million-cent block; the late-fee monthly count rounds upward to the next whole month). The beneficial-owner exposure score, by contrast, is a unitless weighted figure and is rounded to **two decimal places using the round-half-up rule** on the final sum. No other rounding mode is permitted anywhere in the system.

### 2.7. Nested Resource Retrieval and Path Validation

When an endpoint's URL nests one resource inside another — for instance, the boi-ownership endpoints that address an ownership row beneath a business entity, or the exposure-summary endpoint that lives beneath an entity — path parameters are validated **left to right**. The outer entity (`{id}` for the business entity) is resolved first; if it does not exist, the response is `ERR_NOT_FOUND` with HTTP 404 before any inner path parameter (`{ownership_id}`) is even examined. After URL-path resources are confirmed, body-referenced foreign keys (`registered_agent_id`, `business_entity_id`, `beneficial_owner_id`, `foreign_registered_agent_id`) are resolved; an unresolved foreign key likewise yields `ERR_NOT_FOUND` with HTTP 404.

### 2.8. Hierarchical Consistency and Cascade Semantics

Many transitions in this system fan out to dependent rows. When a `BusinessEntity` is voluntarily dissolved, every `ForeignQualification` belonging to it that is currently `QUALIFIED` is cascade-transitioned to `WITHDRAWN`; when the same entity is administratively dissolved, those same qualifications are instead cascade-transitioned to `REVOKED`, and the `revoked_at` timestamp is set. Every cascade is part of the same logical transaction as its triggering operation — partial failure is not permitted — and every cascade emits the appropriate `ComplianceEvent` rows just as if each transition had been requested directly. Whenever a row is mutated, its `updated_at` is set to the current clock instant and its `version` (where present) increments by exactly one; cascaded rows are mutations too, and their `version` and `updated_at` are updated identically.

### 2.9. The Compliance Ledger

Every consequential transition writes a `ComplianceEvent` row tied to the affected `business_entity_id`, carrying an `event_type` drawn from a fixed enumeration — `FORMED`, `ANNUAL_REPORT_ACCEPTED`, `ANNUAL_REPORT_REJECTED`, `TAX_ASSESSED`, `TAX_PAID`, `TAX_OVERDUE`, `TAX_DELINQUENT`, `BOI_FILED`, `BOI_STALE`, `BOI_CORRECTED`, `FOREIGN_QUALIFIED`, `FOREIGN_REVOKED`, `ADMIN_DISSOLVED`, `VOLUNTARILY_DISSOLVED`, `AGENT_RESIGNED`, and `COMPLIANCE_STATUS_CHANGED` — along with an `occurred_at` clock-time stamp and a `payload` object that snapshots whatever ancillary information the event needs (for example, the previous and new compliance posture on a posture-change event, or the cause field distinguishing a withdrawn-from-dissolution from a withdrawn-by-filer event). Compliance events are append-only: they are never updated, never deleted, and form the audit trail readable through the compliance-events listing.

### 2.10. Time-Driving and Deferred Sweep

Several lifecycles in this registry depend on the passage of time: a tax assessment becomes overdue when the clock passes its `due_date`, then delinquent ninety days later; a BOI report becomes stale thirty days after an ownership change if no corrective filing has occurred; an entity becomes eligible for administrative dissolution sixty days after its compliance posture flipped to `DELINQUENT`. To make these flows deterministic and testable, the registry exposes a clock-advance capability and a manual sweep capability. Both are described as endpoints in §4. Advancing the clock by a duration sweeps every entity in one pass, applying every overdue-tax transition, every delinquency transition, every stale-BOI transition, and every cascade those transitions imply, and finally recomputes `compliance_status` for every entity using the rule in §3.6. The manual sweep does the same work without changing the clock instant and is idempotent — running it twice produces no additional transitions.

### 2.11. Validation Ordering

Validations are applied to every incoming request in a strict priority order. The earlier a check is in the order, the sooner the request short-circuits when it fails — meaning a request with multiple problems reports the highest-priority error first. The order, from earliest to latest, is: (1) auth headers present, (2) role spelling valid, (3) role authorized for the endpoint per the matrix in §4, (4) URL-path resources exist, (5) body-referenced foreign keys exist, (6) the target resource is in a state that permits the requested operation (yielding `ERR_INVALID_STATE`), (7) the parent `BusinessEntity.formation_status` is `ACTIVE` for any child-mutating endpoint (yielding `ERR_ENTITY_NOT_ACTIVE`), (8) segregation-of-duties on accept/approve/pay operations, (9) registered-agent address is not a P.O. Box, (10) every beneficial owner being filed is at least eighteen years old, (11) the certificate of good standing supplied for a foreign qualification approval is within sixty days of the current clock, (12) the foreign agent's `service_state` matches the qualification's `foreign_state`, (13) the operating-agreement template matches the entity type, (14) annual-report year is within range and not duplicated, (15) BOI ownership sums to exactly 100 percent at filing time, (16) the foreign state is not the home state, (17) entity legal name is unique among non-dissolved entities, (18) the foreign qualification target is not already covered by a live row, (19) voluntary dissolution has no blocking dependencies, (20) tax-method choice matches entity type, (21) the CORP sanity rail against an over-selected method, and (22) tax-year uniqueness. The ordering is significant: tests assert, for example, that a request with both a missing auth header and a body-level legal-name collision is rejected with `ERR_MISSING_AUTH`, not `ERR_DUPLICATE_LEGAL_NAME`. Note in particular that `ERR_INVALID_STATE` (priority 6) takes precedence over `ERR_ENTITY_NOT_ACTIVE` (priority 7), which in turn takes precedence over segregation of duties (priority 8) and all business-safety/business-constraint checks below it.

## 3. Business Logic & Workflows

This section follows the entity lifecycle: how a business is created and made `ACTIVE`, how its registered agent is provisioned, how its operating agreement is bound, how it acquires an EIN, how annual reports and franchise tax are assessed and reconciled over time, how foreign qualifications are obtained and cascaded on dissolution, how beneficial ownership is disclosed and kept current, and how compliance posture is derived and ultimately how the entity exits the registry. Throughout, the registry's role is both narrative-record-keeper and arithmetic engine: the compliance ledger reflects what happened, and the running balances of credit and accrued penalty reflect what is owed.

### 3.1. Formation: From Paperwork to ACTIVE

A `Filer` initiates entity creation by submitting `legal_name`, `entity_type`, `home_state`, `registered_agent_id`, and — only when the entity type is `CORP` — `authorized_shares` plus the optional bookkeeping fields `total_gross_assets_cents` and `total_issued_shares`. The `legal_name` is a string between 1 and 200 characters; the `entity_type` is one of `LLC`, `CORP`, or `LP`; the `home_state` is a two-letter uppercase US state code matching the regular expression `^[A-Z]{2}$`. For `CORP` entities, `authorized_shares` is required and must be at least 1, while it is `null` for `LLC` and `LP` entities. The default for the two issued-share bookkeeping fields is 0 when not supplied.

The newly created row starts with `formation_status` of `PENDING_FORMATION` and a `compliance_status` of `null`. The `legal_name` must be unique, on a case-insensitive comparison, among all entities whose `formation_status` is **not** `DISSOLVED` and not `ADMINISTRATIVELY_DISSOLVED`; a collision yields `ERR_DUPLICATE_LEGAL_NAME` with HTTP 409. Dissolved-bucket names are explicitly freed for reuse.

Formation proper is a separate step performed by a `StateRegistrar`: it transitions the row from `PENDING_FORMATION` to `ACTIVE`. Three preconditions are checked at that moment. First, the supplied `registered_agent_id` must resolve to a `RegisteredAgent` whose `status` is `ACTIVE`. Second, that agent's `service_state` must equal the entity's `home_state` — a New York entity may not form with a Delaware-authorized agent. Third, if `entity_type` is `CORP`, `authorized_shares` must be set and at least 1. A failure of any precondition surfaces as `ERR_INVALID_STATE` if the target row is not in `PENDING_FORMATION`, or `ERR_INVALID_INPUT` for the `CORP` share-count condition.

Upon successful formation the system records `formation_date` as the current clock instant, sets `compliance_status` to `GOOD_STANDING`, computes `next_annual_report_due_date` as the one-year anniversary of `formation_date` (the so-called anniversary rule — the next deadline lands on the same month-day exactly one year forward), and emits a `ComplianceEvent` with `event_type` of `FORMED`.

### 3.2. Registered Agents and the P.O. Box Prohibition

The registry maintains its own roster of `RegisteredAgent` rows because the same agent may serve many entities and across many states. Creating an agent — done either by a `RegisteredAgentService` or by a `StateRegistrar` — requires `agent_name`, `physical_address`, and `service_state`. The `physical_address` must be a real street address between 1 and 300 characters and must **not** match the regular expression that detects a post-office box (specifically, the pattern that catches "P.O. Box", "PO Box", "P O Box", and similar prefixes — formally, the address must not start with a match of the regular expression `^P\.?O\.? Box`); a violation is rejected with `ERR_INVALID_AGENT_ADDRESS` and HTTP 422. The same address constraint applies when an agent's `physical_address` is updated via the agent-edit endpoint. The `service_state` is a two-letter uppercase US state code (the `^[A-Z]{2}$` regular expression).

Agents start with their `status` defaulted to `ACTIVE`. A `RegisteredAgentService` may resign one of its agents, which transitions `status` to `RESIGNED` and writes the current clock instant into `resignation_effective_at`. A `ComplianceEvent` of `event_type` `AGENT_RESIGNED` is emitted for every entity that still references the resigning agent. Entities whose agent has resigned must replace the agent within thirty days; the replacement is performed by editing the entity's `registered_agent_id` through the entity-update path.

### 3.3. Operating Agreement Attachment

Attaching an `OperatingAgreement` to a `BusinessEntity` is a `Filer` operation that supplies `business_entity_id`, `template_code`, and `template_version`. The `template_code` must match the entity's `entity_type` according to a fixed cross-reference: an `LLC` accepts the templates `LLC_MM` (member-managed) and `LLC_MGR` (manager-managed); a `CORP` accepts the single template `CORP_BYLAWS`; an `LP` accepts the single template `LP_AGREEMENT`. A template that does not match the entity type is rejected with `ERR_TEMPLATE_TYPE_MISMATCH` and HTTP 422. On successful attachment the system computes the SHA-256 hash of the rendered template content and stores it as `locked_template_hash`, alongside `attached_at` set to the current clock instant. Both fields are immutable once written; the `template_version` is likewise frozen at attachment time. An `OperatingAgreement` row carries only `id` and `created_at` — it has neither `updated_at` nor `version` because there is nothing to update after attachment.

### 3.4. EIN Application and Issuance

Once an entity is `ACTIVE`, its `Filer` creates an `EINApplication` carrying `business_entity_id`, `responsible_party_name`, and `responsible_party_ssn_last4`. The last-four-of-SSN field must be exactly four decimal digits, matching the regular expression `^[0-9]{4}$`; anything else is rejected with `ERR_INVALID_INPUT`. The application starts with `status` of `DRAFT` and `assigned_ein` of `null`. At most one non-`REJECTED` application may exist per entity at any moment.

The `Filer` advances the application from `DRAFT` to `SUBMITTED`, at which point the parent entity must be `ACTIVE` and the SSN-last-four field must still match the four-digit pattern. A `TaxOfficer` then approves or rejects the submission: approval transitions `SUBMITTED` to `APPROVED`, mints the next available EIN in the format `^[0-9]{2}-[0-9]{7}$`, writes that value into `assigned_ein`, and writes the same value into the parent `BusinessEntity.ein` — the EIN field on the entity is derived-and-reconciled from the application, not separately stored. Rejection transitions `SUBMITTED` to `REJECTED` without minting. The approval is governed by the segregation rule: the `TaxOfficer`'s `X-User-ID` must not equal the `BusinessEntity.id` that owns the application — that is, the entity cannot approve its own EIN — and a violation yields `ERR_SEGREGATION_OF_DUTIES` with HTTP 403. Two `TaxOfficer`s racing to approve the same `SUBMITTED` application serialize on `EINApplication.status`: exactly one wins and transitions `SUBMITTED → APPROVED`; the loser receives `ERR_INVALID_STATE` with HTTP 409 because the row is already past the `SUBMITTED` state, and EIN minting is atomic with the status transition so no two applications acquire the same EIN.

### 3.5. The Annual Report Revision Cycle

An `AnnualReport` is created by the `Filer` carrying `business_entity_id`, `report_year`, `principal_office_address`, and `officer_director_count`. The `report_year` must be strictly greater than the formation year (the year extracted from `formation_date`) and less than or equal to the current calendar year derived from the clock; the same `report_year` may not already be covered by a `SUBMITTED` or `ACCEPTED` annual report for that entity. The `officer_director_count` is the number of officers and directors (for a `CORP`) or members and managers (for an `LLC` or `LP`); it must be at least 1.

The lifecycle is `DRAFT → SUBMITTED → ACCEPTED`, with a revision loop: a `REJECTED` report cycles back to `DRAFT` and the cycle may repeat without bound. Submission, performed by the `Filer`, advances `DRAFT` to `SUBMITTED` only when the parent entity is `ACTIVE`, no prior `SUBMITTED` or `ACCEPTED` report covers the same `report_year`, and `officer_director_count` is at least 1; the system records `submitted_at` and clears `rejection_reason` to `null`.

Acceptance, performed by a `TaxOfficer`, advances `SUBMITTED` to `ACCEPTED`. The accepter's `X-User-ID` must not equal the `BusinessEntity.id` that filed the report — the entity cannot accept its own filing, and a violation surfaces as `ERR_SEGREGATION_OF_DUTIES`. The parent entity must still be `ACTIVE`. On acceptance, the system records `accepted_at` as the current clock instant, advances `next_annual_report_due_date` on the parent entity to the formation-date anniversary in the year following `report_year` (so an entity formed on June 14, 2020 that gets its 2024 report accepted will see its next due date roll to June 14, 2025), recomputes `compliance_status` per the rule in §3.6 — which can flip `NOT_IN_GOOD_STANDING` back to `GOOD_STANDING` if this acceptance closed the last open delinquency — and emits a `ComplianceEvent` of `event_type` `ANNUAL_REPORT_ACCEPTED`.

Rejection, also performed by a `TaxOfficer`, advances `SUBMITTED` to `REJECTED`. The `rejection_reason` field must be supplied as a non-empty string. A `ComplianceEvent` of `event_type` `ANNUAL_REPORT_REJECTED` is emitted. The `Filer` can then revise the report through the patch endpoint, which (when the current status is `REJECTED`) flips the row back to `DRAFT`; on the next submission, `rejection_reason` is cleared to `null`. The revision endpoint also accepts changes to `principal_office_address`, `officer_director_count`, and an optional `version` for OCC. Two `Filer`s racing to submit the same `(business_entity_id, report_year)` serialize first-writer-wins on the `submitted_at` timestamp; the loser is rejected with `ERR_DUPLICATE_ANNUAL_REPORT` and HTTP 409 because a `SUBMITTED` or `ACCEPTED` peer already exists for that `(business_entity_id, report_year)` pair.

### 3.6. Franchise Tax: Assessment, Two CORP Variants, Late Fees, and Credit Reconciliation

Franchise tax assessments are created by a `TaxOfficer` carrying `business_entity_id`, `tax_year`, and `calculation_method`. The `tax_year` is the calendar year covered, and it must be unique per entity — a second assessment with the same `tax_year` yields `ERR_DUPLICATE_TAX_YEAR` with HTTP 409. The `calculation_method` is constrained by entity type: for `LLC` and `LP` entities, the only legal value is `FLAT`; for `CORP` entities, the only legal values are `AUTHORIZED_SHARES` and `ASSUMED_PAR_VALUE` (and `FLAT` is **not** permitted). Mismatches are rejected with `ERR_INVALID_TAX_METHOD` and HTTP 422.

On creation the system computes `base_tax_cents` from the `franchise_tax_base` rule, sets `due_date` to March 1 of the year following `tax_year` (so a 2024 tax-year assessment is due March 1, 2025), initializes `status` to `ASSESSED` and `late_fee_cents` to 0, and computes `total_due_cents` per the credit-application rule.

**The FLAT method.** For an `LLC` or `LP`, `base_tax_cents` is the constant 30,000 cents — that is, three hundred dollars — drawn from the configuration constant `LLC_LP_FLAT_TAX_CENTS`. The method has no other inputs.

**The AUTHORIZED_SHARES method (CORP variant A).** For a `CORP` choosing this method, the tax is derived from the entity's `authorized_shares` alone via a tiered ladder: when authorized shares are at most 5,000, the base tax is 17,500 cents; when authorized shares are at most 10,000, the base tax is 25,000 cents; when authorized shares exceed 10,000, the base tax is 25,000 cents plus 8,500 cents for each additional block of 10,000 shares, where the additional-share count beyond 10,000 is divided by 10,000 and rounded **up** to the next whole block (so 10,001 shares already counts as one additional block, yielding 33,500 cents). The asset and issued-share fields are not consulted by this method.

**The ASSUMED_PAR_VALUE method (CORP variant B).** For a `CORP` choosing this method, the tax is derived from `total_gross_assets_cents`, `total_issued_shares`, and `authorized_shares`. If `total_issued_shares` is zero the request is rejected with `ERR_INVALID_INPUT` because the method's first step is a division by issued shares. Otherwise the system computes an "assumed par value per share" as `total_gross_assets_cents` divided by `total_issued_shares` (as an exact rational, no rounding yet), multiplies that ratio by `authorized_shares` to obtain an "assumed par value capital" figure (again, exact rational), divides that figure by 100,000,000 cents (a million dollars), rounds the quotient **up** to the next whole integer (call that count "millions"), and produces a base tax of millions multiplied by 40,000 cents. The two-method CORP design is significant: identical input records produce different `base_tax_cents` under the two methods, and the `Filer` is permitted to choose whichever method produces the lower tax. As a sanity rail, however, the chosen method's result must not exceed the **other** method's result by more than fifty percent — a CORP that elects the more expensive method by more than half-again over the cheaper alternative is rejected with `ERR_TAX_METHOD_MISMATCH` and HTTP 422.

**Late fees as time advances.** As long as a tax assessment is `ASSESSED` and the clock is at or before `due_date`, `late_fee_cents` is zero. Once the clock moves past `due_date`, the assessment transitions to `OVERDUE` (the sweep applies this on any clock-advance that crosses the date) and the late fee begins accruing per the `franchise_tax_late_fee` rule. Once the clock moves past `due_date` plus 90 days, the assessment transitions to `DELINQUENT`. Both transitions trigger a recomputation of `late_fee_cents` and `total_due_cents`.

The late-fee formula is: take the elapsed wall time from `due_date` to the current clock instant, divide by 30 days, and round **up** to the next whole month (so a partial month already counts as a full month). Cap that month count at 18 — the late-fee count never exceeds 18 months no matter how long the assessment stays unpaid. Multiply `base_tax_cents` by 0.015 (the constant `MONTHLY_INTEREST_RATE`, representing 1.5% per month) and round the product half-up to the nearest cent — this rounding is **per-line**, applied to the monthly amount **before** it is multiplied by the capped month count. Multiply that rounded monthly amount by the capped month count. Add the constant `LATE_FEE_FLAT_CENTS` of 20,000 cents (a flat 200-dollar penalty). The sum is `late_fee_cents`. For assessments whose `status` is `ASSESSED` (because the clock has not yet passed `due_date`) or `PAID`, `late_fee_cents` is forced to zero.

**The pinned evaluation order for total-due-with-credit.** Computing `total_due_cents` at any moment, including at payment time and during a read of a single assessment, follows a strict five-step order. First, compute `late_fee_cents` from the late-fee rule using the current `status` and clock instant. Second, compute a pre-credit due figure as `base_tax_cents` plus `late_fee_cents`. Third, compute a `credit_applied_cents` figure as the smaller of the entity's current `credit_balance_cents` and the pre-credit due figure — the entity may never apply more credit than it owes, and may never apply more credit than it has. Fourth, set `total_due_cents` to the pre-credit due figure minus `credit_applied_cents`. Fifth — and only on a payment — atomically decrement the entity's `credit_balance_cents` by `credit_applied_cents`. The late fee is **not** recomputed after step four; the pinned order means that the late fee that was effective at the moment of payment is the late fee that gets paid. All five steps work in integer cents; no rounding occurs anywhere in this rule because every input is already in integer cents.

**Payment and the segregation rule.** A `Filer` pays an assessment via the pay action. Payment is legal from any non-PAID state — `ASSESSED`, `OVERDUE`, or `DELINQUENT` — and transitions the row to `PAID`. The payer's `X-User-ID` must not equal the `X-User-ID` of any `TaxOfficer` who accepted an `AnnualReport` for the same entity in the same `tax_year` — a violation yields `ERR_SEGREGATION_OF_DUTIES`. On payment, the system writes `paid_at` to the current clock instant, recomputes a final `late_fee_cents` using the months-late count at `clock.now()` (capped at 18), recomputes `total_due_cents`, decrements the entity's `credit_balance_cents` by `credit_applied_cents`, and recomputes the entity's `compliance_status` — which may revert from `NOT_IN_GOOD_STANDING` back to `GOOD_STANDING` if this payment closes the last open delinquency, or from `DELINQUENT` back to `NOT_IN_GOOD_STANDING` if other open items remain. A `ComplianceEvent` of `event_type` `TAX_PAID` is emitted. The `OVERDUE → PAID` and `DELINQUENT → PAID` transitions both apply this same final-fee recomputation: the final `late_fee_cents` is the months-late count at the payment instant (still capped at 18 months) multiplied by 1.5% of `base_tax_cents` and added to the 20,000-cent flat penalty. Two `Filer`s racing to pay the same assessment serialize on `FranchiseTaxAssessment.status`; exactly one wins and the loser receives `ERR_INVALID_STATE` because the row is already `PAID`. The transition `ASSESSED → PAID` is the only path that carries the accept-vs-pay segregation precondition; the `OVERDUE → PAID` and `DELINQUENT → PAID` paths do not re-evaluate that precondition because by the time the row is overdue the accept-vs-pay segregation has already been settled at acceptance.

**Refund as compensating action.** A `TaxOfficer` may refund a `PAID` assessment, which reverses the row back to whichever non-paid status the clock dictates — `ASSESSED` if the clock is still at or before `due_date`, `OVERDUE` once past `due_date` but within 90 days, or `DELINQUENT` past 90 days — and atomically restores the entity's `credit_balance_cents` by exactly the `credit_applied_cents` figure that was deducted at payment. This is the credit-balance conservation invariant: the global sum of every entity's `credit_balance_cents` plus every PAID assessment's `credit_applied_cents` is preserved across pay-refund cycles. The refund also clears `paid_at`, recomputes status against the current clock, and recomputes `compliance_status`. The credit-deposit endpoint, accepting `amount_cents`, lets a `TaxOfficer` top up an entity's `credit_balance_cents` by the supplied amount.

### 3.7. Foreign Qualification: Out-of-State Operation

When a `BusinessEntity` wishes to operate in a state other than its `home_state`, the `Filer` files a `ForeignQualification` carrying `business_entity_id`, `foreign_state`, `foreign_registered_agent_id`, and `certificate_of_good_standing_date`. The `foreign_state` is a two-letter uppercase US state code that must **not** equal the entity's `home_state` — qualifying to do business in your own home state is meaningless, and an attempt is rejected with `ERR_FOREIGN_STATE_IS_HOME` and HTTP 422. Only one non-terminal qualification (that is, with `status` neither `WITHDRAWN` nor `REVOKED`) may exist for a given `(business_entity_id, foreign_state)` pair at a time; a second attempt yields `ERR_DUPLICATE_FOREIGN_QUALIFICATION` with HTTP 409. The `foreign_registered_agent_id` must resolve to a `RegisteredAgent` whose `service_state` equals the qualification's `foreign_state` — that is, the foreign agent must be authorized in the foreign state — and a mismatch is rejected with `ERR_AGENT_STATE_MISMATCH`. The `certificate_of_good_standing_date` is the issuance date of the home-state COGS attached to the application.

The qualification starts with `status` `PENDING`. A `StateRegistrar` approves or rejects it. Approval transitions `PENDING → QUALIFIED` and requires three concurrent conditions: the parent entity's `compliance_status` is `GOOD_STANDING` (not `NOT_IN_GOOD_STANDING` and not `DELINQUENT`), the `certificate_of_good_standing_date` is within sixty days of the current clock instant (older COGS yields `ERR_STALE_COGS`), and the foreign agent's `status` is `ACTIVE` and its `service_state` equals the qualification's `foreign_state`. On approval, `qualified_at` is set and a `ComplianceEvent` of `event_type` `FOREIGN_QUALIFIED` is emitted. Rejection transitions `PENDING → REJECTED` without preconditions; the `Filer` may then resubmit through the patch endpoint, which can carry a fresh `certificate_of_good_standing_date`, a revised `foreign_registered_agent_id`, and an optional `version` for OCC. Resubmission requires the supplied COGS date to be within sixty days of the current clock; on success the row cycles `REJECTED → PENDING` for another approval cycle.

A `Filer` may voluntarily withdraw a `QUALIFIED` qualification, transitioning it to `WITHDRAWN`. Two cascade paths from a parent entity's dissolution also drive non-terminal qualifications to terminal: voluntary dissolution drives every `QUALIFIED` qualification to `WITHDRAWN`, and administrative dissolution drives every `QUALIFIED` qualification to `REVOKED` (setting `revoked_at`). Both cascades emit `ComplianceEvent` rows of `event_type` `FOREIGN_REVOKED` with the cascade cause recorded in `payload`. Two clients racing to file qualifications for the same `(business_entity_id, foreign_state)` pair serialize first-writer-wins on creation; the loser receives `ERR_DUPLICATE_FOREIGN_QUALIFICATION`.

### 3.8. Beneficial Owners, BOI Reports, and the Stale-Disclosure Penalty

The registry maintains separately-rowed `BeneficialOwner` records, supplied by the `Filer` with `full_legal_name`, `date_of_birth`, `residential_address`, `identifying_document_type`, and `identifying_document_number`. The `date_of_birth` carries date-only semantics and must be at least eighteen years before the current clock instant — every owner included on a BOI report being filed must be at least 18 years old at the filing moment, and a younger owner yields `ERR_OWNER_UNDERAGE` with HTTP 422. The `identifying_document_type` is exactly one of `US_PASSPORT`, `STATE_DRIVERS_LICENSE`, `STATE_ID`, or `FOREIGN_PASSPORT`. The `identifying_document_number` is between 1 and 50 characters.

Ownership rows live in a separate `BOIOwnership` resource, each carrying `business_entity_id`, `beneficial_owner_id`, and `ownership_percent_basis_points` — an integer in the closed interval from 0 to 10,000, where 10,000 basis points equals 100%. Adding an ownership row stamps `effective_at` to the current clock instant; removing an ownership row is a soft-delete that stamps `terminated_at` to the current clock instant rather than removing the row. Both operations, when a `CURRENT` `BOIReport` already exists for the entity, schedule a thirty-day stale-timer for the entity's BOI status.

A `BOIReport` is created by the `Filer` carrying `business_entity_id` and `filing_type` — one of `INITIAL`, `UPDATE`, or `CORRECTION`. The `INITIAL` filing type is permitted only when no prior `BOIReport` exists for the entity with status in `FILED`, `CURRENT`, `STALE`, or `CORRECTED`. The report starts in `DRAFT` and may transition through `FILED → CURRENT → (STALE ↔ CURRENT) → CORRECTED`. Filing transitions `DRAFT → FILED → CURRENT`: the parent entity must be `ACTIVE`, the sum of active `BOIOwnership.ownership_percent_basis_points` rows for the entity (those with `terminated_at` either null or in the future relative to the current clock) must equal exactly 10,000 at the moment of filing — a violation yields `ERR_OWNERSHIP_NOT_100` with HTTP 422 — and every active beneficial owner must be at least 18 years old. On `DRAFT → FILED` the system records `filed_at` as the current clock instant and immediately auto-advances the row to `CURRENT` in the same logical transaction, emitting a `ComplianceEvent` of `event_type` `BOI_FILED`.

If a `CURRENT` BOI report is in place and a `BOIOwnership` row is added or terminated for the entity, the report becomes vulnerable to going `STALE`: thirty days after the ownership change, if no `UPDATE` or `CORRECTION` `BOIReport` has been filed in the interim, the system transitions the report `CURRENT → STALE`, sets `stale_at` to the current clock instant, drives the entity's `compliance_status` from `GOOD_STANDING` to `NOT_IN_GOOD_STANDING`, begins accruing `penalty_cents` per the BOI penalty rule, and emits a `ComplianceEvent` of `event_type` `BOI_STALE`. Conversely, when an `UPDATE`-typed report transitions `DRAFT → FILED → CURRENT` in time, the prior `STALE` report is marked `CORRECTED` in the same operation — this is the cycle `CURRENT → STALE → CURRENT` via timely update — and a `ComplianceEvent` of `event_type` `BOI_CORRECTED` is emitted.

A `CORRECTION`-typed report is the explicit corrective path: a `Filer` files a corrective `BOIReport` whose `filing_type` is `CORRECTION`, which transitions the **prior** `STALE` report to `CORRECTED` and snapshots `days_stale_at_filing` as the floor of the elapsed days between the prior report's `stale_at` and the current clock instant. The prior report's `penalty_cents` is finalized as the smaller of `days_stale_at_filing` multiplied by the daily penalty constant of 59,100 cents and the cap of 1,000,000 cents — that is, $591 per day up to a maximum of $10,000.

The penalty calculation while a report is `STALE` is computed every time the clock advances. The raw day count is the floor of the elapsed wall time since `stale_at` divided by 1 day. The day count is then capped — and the order is significant — by the integer floor of the cap constant divided by the daily-penalty constant: 1,000,000 divided by 59,100 is 16 (integer floor), so the effective day count for penalty-arithmetic purposes is the smaller of the raw day count and 16. The accrued `penalty_cents` is the effective day count multiplied by 59,100. The cap-first-then-multiply order is normative: although multiply-first-then-cap would yield the same final cap, the audit-reported "days counted" figure would differ, and the cap-first interpretation is the one the registry persists.

### 3.9. Exposure Score: Provisional vs Finalized Views

The registry exposes a computed read on every entity — the exposure summary — that produces an unitless weighted exposure score reflecting how risky the beneficial-ownership disclosure looks. The score has two variants selected by an optional `view` query parameter; when `view` is omitted the response defaults to the `finalized` variant. The `provisional` variant sums, over every currently-active `BOIOwnership` row for the entity (those with `terminated_at` either null or strictly after the current clock instant), the ownership percentage expressed as a fraction (`ownership_percent_basis_points` divided by 10,000) multiplied by a per-owner risk weight derived from the owner's `identifying_document_type`: a `FOREIGN_PASSPORT` carries a risk weight of 3 (the constant `RISK_FOREIGN_PASSPORT`), a `STATE_ID` carries a weight of 2 (the constant `RISK_STATE_ID`), and either a `US_PASSPORT` or a `STATE_DRIVERS_LICENSE` carries a default weight of 1 (the constant `RISK_DEFAULT`). The final sum is rounded to two decimal places using the round-half-up rule.

The `finalized` variant computes the same weighted sum, but over the snapshot of `BOIOwnership` rows that were active at the most recent `BOIReport.filed_at` whose `status` is either `CURRENT` or `CORRECTED` — that is, what the regulator currently sees on file. If the latest report is `STALE` or `DRAFT`, the prior `CURRENT` snapshot is used. The two variants produce identical numbers only when the latest report is `CURRENT` and no ownership change has occurred since; in any other configuration the `provisional` variant reflects pending undisclosed changes and the `finalized` variant lags behind.

### 3.10. Derived Compliance Posture

Every entity's `compliance_status` is a derived field, recomputed whenever any `FranchiseTaxAssessment.status`, `AnnualReport.status`, or `BOIReport.status` changes for the entity, and on every clock-advance pass. The derivation follows a strict ordered rule. First, check whether any `FranchiseTaxAssessment` for the entity has `status` equal to `DELINQUENT`: if so, the entity's `compliance_status` is `DELINQUENT`. Otherwise, check whether any of three sub-conditions holds — whether any `FranchiseTaxAssessment.status` is `OVERDUE`, whether the current clock instant is strictly past the entity's `next_annual_report_due_date` and no `AnnualReport` for a `report_year` at or beyond the year of that due date is in `ACCEPTED` status, or whether any `BOIReport.status` is `STALE` — and if any one holds, the entity's `compliance_status` is `NOT_IN_GOOD_STANDING`. Otherwise the entity is in `GOOD_STANDING`. Every transition of `compliance_status` from one value to another emits a `ComplianceEvent` of `event_type` `COMPLIANCE_STATUS_CHANGED` whose `payload` carries the `from` and `to` values.

The same derived-posture rule provides the bridge from tax-assessment lifecycles to the entity-level compliance posture sub-machine: an `ASSESSED → OVERDUE` transition drives the entity from `GOOD_STANDING` to `NOT_IN_GOOD_STANDING`, an `OVERDUE → DELINQUENT` transition drives the entity from `NOT_IN_GOOD_STANDING` to `DELINQUENT` (a depth-3 cascade chain from clock-advance), and a closing transition — every tax assessment now `ASSESSED` or `PAID`, every due-year annual report `ACCEPTED`, every BOI report not `STALE` — drives the entity from `NOT_IN_GOOD_STANDING` back to `GOOD_STANDING`. All such transitions emit `COMPLIANCE_STATUS_CHANGED` events.

### 3.11. Voluntary and Administrative Dissolution

A `Filer` voluntarily dissolves a `BusinessEntity` by triggering the dissolve action. The action transitions `formation_status` from `ACTIVE` to `DISSOLVED`, sets `dissolution_date` to the current clock instant, sets `compliance_status` to `null`, cascades every `QUALIFIED` foreign qualification to `WITHDRAWN`, and emits a `ComplianceEvent` of `event_type` `VOLUNTARILY_DISSOLVED`. Voluntary dissolution is **blocked** when any of three dependencies is present: any `FranchiseTaxAssessment` with `status` in `OVERDUE` or `DELINQUENT`, any `BOIReport` with `status` equal to `STALE`, or any `ForeignQualification` with `status` equal to `QUALIFIED` (the entity must withdraw the qualifications first). A blocking dependency yields `ERR_HAS_DEPENDENCIES` with HTTP 409. Two `Filer`s racing to dissolve the same entity serialize on `BusinessEntity.formation_status`; exactly one wins and the loser receives `ERR_INVALID_STATE`. When a voluntary dissolution races with the creation of a new `FranchiseTaxAssessment` for the same entity, either the dissolve succeeds and the assessment creation is rejected with `ERR_INVALID_STATE`, or the assessment is created first and the dissolve is rejected with `ERR_HAS_DEPENDENCIES` if the assessment would land in `OVERDUE` or `DELINQUENT` — the dependency check is re-evaluated under the lock.

Administrative dissolution is a `ComplianceOfficer` operation that transitions `formation_status` from `ACTIVE` to `ADMINISTRATIVELY_DISSOLVED`. Its sole precondition is that the entity has been in `compliance_status` `DELINQUENT` for at least sixty days — measured from the clock instant at which `compliance_status` first flipped to `DELINQUENT`. On execution the system sets `dissolution_date`, sets `compliance_status` to `null`, cascades every `QUALIFIED` foreign qualification to `REVOKED` (setting `revoked_at` on each), and emits a `ComplianceEvent` of `event_type` `ADMIN_DISSOLVED`. Notably, BOI reports in `CURRENT` or `STALE` are **not** cascade-corrected by administrative dissolution: the BOI penalty continues to accrue on any `STALE` report until the owner files a corrective report, even past the entity's administrative dissolution.

### 3.12. Time-Driving Capabilities

For deterministic testability, the registry exposes two infrastructure capabilities. The clock-advance capability accepts a `duration_iso8601` (an ISO 8601 duration like "P30D" or "PT1H"), advances the server clock by that duration, and runs the compliance sweep: for every entity in the registry, it transitions any `ASSESSED` `FranchiseTaxAssessment` past `due_date` to `OVERDUE`, any `OVERDUE` assessment past `due_date + 90 days` to `DELINQUENT`, any `CURRENT` `BOIReport` whose stale-timer has elapsed to `STALE`, any `QUALIFIED` `ForeignQualification` to `REVOKED` if a cascade demands it, and recomputes the derived `compliance_status` and `next_annual_report_due_date` for every entity. Each such transition emits its corresponding `ComplianceEvent`. The endpoint returns an object containing the new clock instant and the set of transitions applied.

The manual-sweep capability does the same work without advancing the clock, and is idempotent: a second invocation immediately after a first will find no further transitions to apply. The clock-advance capability is restricted to the `TestHarness` role; the manual sweep is available to both `TestHarness` and `ComplianceOfficer`.

## 4. Endpoint Definitions

New resources created via POST are returned with HTTP status code 201. Modifications to existing resources via POST action-endpoints, PATCH, and the soft-delete on ownership rows return HTTP 200 (DELETE on `BOIOwnership` returns 204 with no body). Reads via GET return HTTP 200. The status-code rules apply uniformly; deviations are called out in the description column where relevant.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/business-registry/entities` | Create a new business entity in `PENDING_FORMATION`. | `Filer` |
| GET | `/business-registry/entities/{id}` | Read a business entity including derived `compliance_status`, `next_annual_report_due_date`, and `ein`. | `Filer`, `StateRegistrar`, `TaxOfficer`, `ComplianceOfficer` |
| GET | `/business-registry/entities` | List entities, filterable by `entity_type`, `formation_status`, `compliance_status`; paginated. | `Filer`, `StateRegistrar`, `TaxOfficer`, `ComplianceOfficer` |
| POST | `/business-registry/entities/{id}/form` | Transition `PENDING_FORMATION` to `ACTIVE`; mints `formation_date`. | `StateRegistrar` |
| POST | `/business-registry/entities/{id}/dissolve` | Voluntary dissolution. | `Filer` |
| POST | `/business-registry/entities/{id}/administratively-dissolve` | Administrative dissolution after at least 60 days `DELINQUENT`. | `ComplianceOfficer` |
| GET | `/business-registry/entities/{id}/exposure-summary` | Computed read: beneficial-owner exposure score (`provisional` vs `finalized`). | `Filer`, `ComplianceOfficer` |
| POST | `/business-registry/registered-agents` | Create a registered agent. | `RegisteredAgentService`, `StateRegistrar` |
| PATCH | `/business-registry/registered-agents/{id}` | Update agent fields including `physical_address`; OCC supported. | `RegisteredAgentService`, `StateRegistrar` |
| POST | `/business-registry/registered-agents/{id}/resign` | Agent resigns; marks `status` `RESIGNED`. | `RegisteredAgentService` |
| POST | `/business-registry/operating-agreements` | Attach an operating agreement template to a business entity. | `Filer` |
| POST | `/business-registry/ein-applications` | Create an EIN application in `DRAFT`. | `Filer` |
| POST | `/business-registry/ein-applications/{id}/submit` | Transition `DRAFT` to `SUBMITTED`. | `Filer` |
| POST | `/business-registry/ein-applications/{id}/approve` | Transition `SUBMITTED` to `APPROVED`; mints `assigned_ein` and updates entity's `ein`. | `TaxOfficer` |
| POST | `/business-registry/ein-applications/{id}/reject` | Transition `SUBMITTED` to `REJECTED`. | `TaxOfficer` |
| POST | `/business-registry/annual-reports` | Create an annual report in `DRAFT`. | `Filer` |
| PATCH | `/business-registry/annual-reports/{id}` | Revise a `DRAFT` or `REJECTED` annual report (cyclic revert loop). | `Filer` |
| POST | `/business-registry/annual-reports/{id}/submit` | Transition `DRAFT` to `SUBMITTED`. | `Filer` |
| POST | `/business-registry/annual-reports/{id}/accept` | Transition `SUBMITTED` to `ACCEPTED`; advances `next_annual_report_due_date`. | `TaxOfficer` |
| POST | `/business-registry/annual-reports/{id}/reject` | Transition `SUBMITTED` to `REJECTED`; requires `rejection_reason`. | `TaxOfficer` |
| POST | `/business-registry/tax-assessments` | Create a franchise tax assessment for `(business_entity_id, tax_year)`; computes `base_tax_cents` per chosen method. | `TaxOfficer` |
| GET | `/business-registry/tax-assessments/{id}` | Read an assessment with live `total_due_cents` computation. | `Filer`, `TaxOfficer` |
| POST | `/business-registry/tax-assessments/{id}/pay` | Pay an assessment from any non-PAID state; applies entity's `credit_balance_cents`. | `Filer` |
| POST | `/business-registry/tax-assessments/{id}/refund` | Compensating action that reverses a `PAID` assessment and restores `credit_balance_cents`. | `TaxOfficer` |
| POST | `/business-registry/entities/{id}/credit-deposit` | Deposit `amount_cents` of pre-paid credit onto a business entity. | `TaxOfficer` |
| POST | `/business-registry/foreign-qualifications` | File for foreign qualification in another state. | `Filer` |
| PATCH | `/business-registry/foreign-qualifications/{id}` | Resubmit a `REJECTED` foreign qualification (cyclic `REJECTED` to `PENDING`). | `Filer` |
| POST | `/business-registry/foreign-qualifications/{id}/approve` | Transition `PENDING` to `QUALIFIED`. | `StateRegistrar` |
| POST | `/business-registry/foreign-qualifications/{id}/reject` | Transition `PENDING` to `REJECTED`. | `StateRegistrar` |
| POST | `/business-registry/foreign-qualifications/{id}/withdraw` | Transition `QUALIFIED` to `WITHDRAWN` (voluntary). | `Filer` |
| POST | `/business-registry/boi-reports` | Create a BOI report in `DRAFT` with `filing_type` `INITIAL`, `UPDATE`, or `CORRECTION`. | `Filer` |
| POST | `/business-registry/boi-reports/{id}/file` | Transition `DRAFT` to `FILED` and auto to `CURRENT`; validates ownership sum and owner age. | `Filer` |
| POST | `/business-registry/beneficial-owners` | Create a beneficial owner record. | `Filer` |
| POST | `/business-registry/entities/{id}/boi-ownership` | Add an active ownership row; schedules 30-day stale timer when a `CURRENT` BOI report exists. | `Filer` |
| DELETE | `/business-registry/entities/{id}/boi-ownership/{ownership_id}` | Soft-delete an ownership row (sets `terminated_at`); schedules 30-day stale timer. Returns 204. | `Filer` |
| GET | `/business-registry/entities/{id}/compliance-events` | List compliance events for an entity ordered by `occurred_at` ascending; filterable by `event_type`; paginated. | `Filer`, `StateRegistrar`, `TaxOfficer`, `ComplianceOfficer` |
| POST | `/business-registry/_clock/advance` | Advance the server clock by `duration_iso8601` and run the compliance sweep. | `TestHarness` |
| POST | `/business-registry/_sweep/run` | Run the compliance sweep without advancing the clock (idempotent). | `TestHarness`, `ComplianceOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_AUTH` | 401 |
| `ERR_INVALID_ROLE` | 403 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ENTITY_NOT_ACTIVE` | 409 |
| `ERR_HAS_DEPENDENCIES` | 409 |
| `ERR_DUPLICATE_LEGAL_NAME` | 409 |
| `ERR_DUPLICATE_ANNUAL_REPORT` | 409 |
| `ERR_DUPLICATE_FOREIGN_QUALIFICATION` | 409 |
| `ERR_DUPLICATE_TAX_YEAR` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_INVALID_AGENT_ADDRESS` | 422 |
| `ERR_OWNER_UNDERAGE` | 422 |
| `ERR_STALE_COGS` | 422 |
| `ERR_AGENT_STATE_MISMATCH` | 422 |
| `ERR_TEMPLATE_TYPE_MISMATCH` | 422 |
| `ERR_OWNERSHIP_NOT_100` | 422 |
| `ERR_FOREIGN_STATE_IS_HOME` | 422 |
| `ERR_INVALID_TAX_METHOD` | 422 |
| `ERR_TAX_METHOD_MISMATCH` | 422 |
| `ERR_INVALID_INPUT` | 422 |

# IP Management API — Product Requirements Document

## 1. Introduction

Modern corporate intellectual-property portfolios sprawl across patents, trademarks, and copyrights filed in multiple jurisdictions, each with its own annuity cadence, office-action correspondence, and authority filing rituals. Below the surface, the same portfolio drives transfer and licensing contracts, royalty obligations, infringement disputes, and a long tail of agent fees and authority charges that ultimately fall on specific business units' annual budgets. Tracking any one of these threads is straightforward; reconciling all of them — making sure that an unpaid annuity in Japan eventually cascades the right patent into `ABANDONED`, that the cost of a US litigation is allocated to the funding business unit in basis points, that an exclusive licensee's minimum-guarantee floor kicks in at settlement time, and that the agent responsible for any of these has been verified and is licensed in the relevant jurisdiction — is what this system exists to do.

This document specifies the IP Management API, mounted under `/ip-rights` and a small number of sibling top-level resources (`/agents`, `/contracts`, `/protection-cases`, `/costs`, `/business-units`, `/contract-templates`, `/annual-fees`, `/office-actions`, `/jurisdiction-filings`, `/royalty-schedules`, `/audit-entries`, plus internal `/_clock`, `/_sweep`, and `/_events` endpoints). It is written for engineers implementing the server side: every entity, state machine, validation, calculation, and cross-aggregate side effect that the test harness will exercise is captured here. The system is intentionally workflow-orchestrated rather than CRUD: most non-trivial endpoints drive a state transition with multiple side effects, and most validation lives in the business layer rather than in field-shape checks.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. Both headers must be present and non-empty on every endpoint except `GET /_health`; a missing or blank value is rejected with `ERR_UNAUTHENTICATED` at HTTP 401. Once the headers are present, the role is checked against the operation's authorization list (see §4); a role outside that list is rejected with `ERR_FORBIDDEN` at HTTP 403.

Six roles are defined. **`Admin`** is the platform administrator and owns the creation of business units, agents, contract templates, and the internal test-driving endpoints. **`IPManager`** prosecutes IP applications, manages contracts, and drives jurisdiction filings. **`FinanceManager`** owns annual-fee payments, royalty settlements, cost booking, and the budget-versus-actual report. **`Counsel`** manages rights-protection cases — opening them, attaching evidence, routing, resolving, and closing. **`InternalAgent`** and **`ExternalAgent`** represent IP agents (employees and third-party firm representatives respectively) who file office-action responses and contribute evidence.

For `Admin`, `IPManager`, `FinanceManager`, and `Counsel`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it in audit entries (as `actor_id` on `AuditEntry`) but does not compare it to any entity's `id`. For `InternalAgent` and `ExternalAgent`, `X-User-ID` is the `id` of the acting `Agent`; ownership checks on any resource that references an `Agent` compare the resource's `assigned_agent_id` to `X-User-ID`. Concretely, when an `InternalAgent` or `ExternalAgent` calls the office-action response endpoint, the server confirms that the targeted `ApplicationOfficeAction.assigned_agent_id` matches `X-User-ID`; mismatch is treated as `ERR_FORBIDDEN`.

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

All list endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; values outside this range are rejected as invalid input. `offset` defaults to 0 and has no upper bound. Records are returned sorted by `created_at` in ascending order. The `meta` block of list responses populates `limit`, `offset`, `total_count` (total matching rows before windowing), and `has_more` (true if more rows exist beyond `offset + limit`).

### 2.4. Common Resource Properties and Optimistic Concurrency

Most entities — `BusinessUnit`, `Agent`, `IPRight`, `JurisdictionFiling`, `ApplicationOfficeAction`, `AnnualFeeSchedule`, `Contract`, `RoyaltySchedule`, and `ProtectionCase` — share four common fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is set once on creation and `updated_at` is refreshed on every mutation. `version` is an integer that starts at 1 and increments by 1 on every mutation. Four entities — `ContractTemplate`, `Evidence`, `Cost`, and `AuditEntry` — carry only `id` and `created_at`; both `updated_at` and `version` are absent for those entities.

Endpoints that mutate a versioned entity accept an optional `version` field in the request body. When supplied, the server compares it to the row's current `version`; mismatch results in `ERR_VERSION_CONFLICT` at HTTP 409. When `version` is omitted, the concurrency check is skipped and the mutation proceeds. Two simultaneous mutations targeting the same row serialize at the storage layer; the slower of the two, if it carried a stale `version`, receives `ERR_VERSION_CONFLICT`.

### 2.5. Currency, Money, and Precision

Every monetary amount on this system is stored as an integer number of cents to avoid floating-point drift. The base currency is USD. Foreign-currency costs are stored alongside their native amount in `amount_native_cents`, an `fx_rate_to_usd` multiplier, an ISO 4217 `currency` code, and a derived `amount_usd_cents` in USD cents. The conversion is computed by multiplying `amount_native_cents` by `fx_rate_to_usd` and rounding half-up to the nearest cent; `amount_usd_cents` is the result. Any later edit that changes either input recomputes the USD amount.

Where a calculation yields a non-integer result expressed in cents, the system rounds half-up to the nearest integer cent unless otherwise stated. Where a calculation yields a decimal-valued score (notably an agent's `workload_score` and `performance_rating`), the result is rounded half-up to two decimal places.

### 2.6. Nested-Resource Path Resolution

Several endpoints are nested under a parent — for example, an annual-fee schedule is created under `/ip-rights/{id}/annual-fees`, and an office-action under `/ip-rights/{id}/office-actions`. Path parameters resolve left-to-right: the parent `id` is checked first, and only after it resolves does the server inspect any nested identifier. A non-existent path-bound id at any position returns `ERR_NOT_FOUND` at HTTP 404. By contrast, a foreign-key reference carried in the request body (`assigned_agent_id`, `ip_right_id`, `business_unit_id`, `template_id`, `jurisdiction_filing_id`, and similar) is treated as a business-input validation: a missing referent returns `ERR_REFERENCED_ENTITY_NOT_FOUND` at HTTP 422.

### 2.7. Validation Priority

When a single request would trip several checks, the server evaluates them in a fixed priority order. Authentication is evaluated first — missing or blank `X-User-ID` / `X-User-Role` headers always surface as `ERR_UNAUTHENTICATED` before any other check. Authorization comes next: a role not listed for the endpoint returns `ERR_FORBIDDEN`. Once the caller is authenticated and authorized, the server resolves every path-bound id and returns `ERR_NOT_FOUND` for any that fail. After path resolution succeeds, body-level foreign-key references are resolved and `ERR_REFERENCED_ENTITY_NOT_FOUND` is returned for any missing referent. State-machine eligibility is then checked: an action endpoint invoked on an entity that is not in a state from which the requested transition is defined returns `ERR_INVALID_STATE`. Only after all of the above pass does the server evaluate the domain-specific business safety, referential, constraint, temporal, and fiscal rules that are described throughout §3. The complete priority order is: authentication (priority 1), authorization (priority 2), path existence (priority 3), body-foreign-key existence (priority 4), state eligibility (priority 5), and then the business-layer rules in the order listed throughout §3 — agent qualification, litigation evidence, agent jurisdiction, template-type match, contract-fields-for-type, min-guarantee allowance, royalty period contiguity, fee-date validity, allocation basis-point sum, allocation business-unit activeness, budget-cap check, party-sufficiency, and IP-registration prerequisite, in that descending priority.

### 2.8. Cascading Side Effects, `updated_at`, and `version`

Many state transitions in this system propagate up and down the entity hierarchy. When a side effect mutates an entity, that entity's `updated_at` is refreshed and its `version` (if present) is incremented. A single API call may legitimately mutate several entities: registering the last open `JurisdictionFiling` of an `IPRight`, for instance, flips the filing to `REGISTERED`, lifts the parent `IPRight` to `REGISTERED`, sets its `registered_at` and `certificate_archive_url`, and auto-creates `AnnualFeeSchedule` rows for fee-year 1 — each of those rows is itself a new versioned entity. All such cascades are atomic with respect to the originating call.

### 2.9. Audit Logging

Status changes and contract records are mirrored into the `AuditEntry` table. Every audit entry records the `subject_entity` (the type name, e.g., `'IPRight'`, `'Contract'`, `'AnnualFeeSchedule'`, `'ProtectionCase'`), the `subject_id`, the `actor_role` and `actor_id` from the triggering request, an `event_type` drawn from `STATUS_CHANGE`, `CONTRACT_RECORD`, `PAYMENT_SETTLED`, `EVIDENCE_ADDED`, or `EXTERNAL_SYNC`, and a `payload` object whose shape depends on the event. For `STATUS_CHANGE` events, the prior state is recorded in `from_state` and the new state in `to_state`; for other event types, both `from_state` and `to_state` are null. The `payload` is free-form structured (for example, a contract amendment's prior-field snapshot, or an external-sync envelope).

### 2.10. External-System Synchronization and Idempotency

Two endpoints relay events from external systems back into this API. The Payment system posts a settled-payment event to mark a specific `AnnualFeeSchedule` paid; the e-signature platform posts a signing event to record a party signature on a `Contract`. Both endpoints accept an `idempotency_key` alongside the domain payload (`annual_fee_id` or the contract's `contract_id` plus `party_id`) and are idempotent on that key: a repeat call with the same `idempotency_key` returns the same outcome as the first call without applying the side effects a second time.

## 3. Business Logic & Workflows

### 3.1. Business Units, Agents, and Contract Templates as Foundational Data

A `BusinessUnit` is the smallest organizational unit that owns IP rights, sponsors protection cases, and absorbs allocated costs against an `annual_budget_cents` cap. Each unit carries a short stable `code` matching the regular pattern of two-to-sixteen uppercase letters, digits, or underscores and is unique across the system; a human-readable `name`; an `annual_budget_cents` value that must be zero or positive; and an `actual_spend_cents` running total computed by summing every `allocated_cents` from every `Cost` allocation pointing at this business unit's id. A unit starts life in `ACTIVE` status; an `Admin` may flip it to `ARCHIVED`. Archiving does not retroactively remove past cost allocations, but new cost allocations cannot target an `ARCHIVED` unit (see §3.7 budget rules).

`Agent` is the system's representation of any natural or contracted person who may be assigned to prosecute filings, draft office-action responses, run protection cases, or settle royalty obligations. Each agent has a `kind` that is either `INTERNAL` (an employee) or `EXTERNAL` (a third-party firm representative), a `full_name`, a `qualification_number` (the bar number for lawyers or IP-agent license number), a `qualification_verified` flag that starts false and is flipped true only by an `Admin`-triggered verification call, an array `jurisdictions` of ISO-like codes such as `['US','EP','CN']`, an `hourly_rate_cents` quoted fee that must be zero or positive, and an `ACTIVE` / `SUSPENDED` `status`. The system additionally computes four read-only fields on each agent: `active_case_count` (the number of `ProtectionCase` rows whose `assigned_agent_id` equals this agent and whose `status` is `OPEN` or `IN_PROGRESS`), `pending_action_count` (the count of `ApplicationOfficeAction` rows assigned to this agent with `status` `PENDING`), `upcoming_deadline_count` (the count of `AnnualFeeSchedule` rows assigned to this agent whose `due_date` falls within the next thirty days and whose `status` is `PENDING`), and the `workload_score` and `performance_rating` derived from those counts and from the agent's resolved cases.

`workload_score` is a weighted composite, computed by multiplying `active_case_count` by 0.40, `pending_action_count` by 0.30, `upcoming_deadline_count` by 0.30, summing the three products, and rounding the sum half-up to two decimal places. `performance_rating` is a rolling rating over the agent's most recent resolved cases. To compute it, take every `ProtectionCase` whose `assigned_agent_id` is this agent and whose status is either `RESOLVED` or `CLOSED`, sort them by `updated_at` descending with `id` descending as the tie-breaker, take the first ten of that ordering (use all of them if fewer than ten exist), score each case by its `outcome` — 5.0 for `WON`, 3.5 for `SETTLED`, 2.0 for `DISMISSED`, 1.0 for `LOST` — take the arithmetic mean of those scores, and round the mean half-up to two decimal places. If the agent has no resolved or closed cases, `performance_rating` is exactly 0.00. Both score and rating are recomputed and returned whenever an agent is fetched, listed, or affected by a case resolution.

A `ContractTemplate` is a reusable contract scaffold with a unique `code` (two-to-thirty-two uppercase letters, digits, or underscores), a `contract_type` taken from `TRANSFER`, `EXCLUSIVE_LICENSE`, or `NON_EXCLUSIVE_LICENSE`, and a `body` of prose with placeholders. Templates are created by an `Admin` and listed by `Admin` and `IPManager`.

### 3.2. The IP-Right Application Lifecycle

An `IPRight` represents one piece of intellectual property — a patent, trademark, or copyright — and follows a branching lifecycle: `DRAFT → MATERIALS_READY → FILED → OFFICE_ACTION → FILED → REGISTERED → TRANSFERRED` is the success path, with detours into `ABANDONED` from `OFFICE_ACTION` and from `REGISTERED`. An `IPManager` initiates a new right by supplying an `ip_type` (one of `PATENT`, `TRADEMARK`, `COPYRIGHT`), a `title`, a `handling_mode` (either `AGENCY` or `SELF`), an optional `assigned_agent_id` (required when `handling_mode` is `AGENCY` and required to be null when `handling_mode` is `SELF`), a `business_unit_id`, and a `primary_jurisdiction` code. The newly created right enters `DRAFT` status.

Marking application materials ready advances the right from `DRAFT` to `MATERIALS_READY`. The transition is gated on three preconditions: the right's required material fields (`title` and `primary_jurisdiction`, both non-empty) must be present; when `handling_mode` is `AGENCY`, the `assigned_agent_id` must resolve to an `Agent` whose `qualification_verified` is true; and when `handling_mode` is `SELF`, the `assigned_agent_id` must be null. An unverified agent on an `AGENCY` right is rejected with `ERR_AGENT_QUALIFICATION_UNVERIFIED`. An `AGENCY` right whose assigned `Agent` does not list the right's `primary_jurisdiction` in its `jurisdictions` array is rejected with `ERR_AGENT_JURISDICTION_MISMATCH` at creation time.

Filings are then created beneath the right as `JurisdictionFiling` rows. Each carries a parent `ip_right_id` (set by the path), an input `jurisdiction` code such as `'US'`, `'EP'`, `'CN'`, or `'JP'`, a `filing_number` issued by the local IP authority, a `filed_at` local filing date, and a `status` that starts at `FILED`. The very first filing created beneath a `MATERIALS_READY` right auto-transitions the parent `IPRight.status` to `FILED`.

Office actions arrive on a per-filing basis. Opening an office action under a `FILED` parent advances the right from `FILED` to `OFFICE_ACTION` and creates a new `ApplicationOfficeAction` in `PENDING` status. The opener supplies the targeted `jurisdiction_filing_id`, an `assigned_agent_id` for the responder, and a `response_due_at` deadline. The action's filing target must belong to the right and must currently be in `FILED` status. Side effects of opening an office action are layered: the targeted `JurisdictionFiling.status` becomes `OFFICE_ACTION`, the `ApplicationOfficeAction` is created in `PENDING`, and the parent `IPRight.status` becomes `OFFICE_ACTION`.

The assigned agent responds via the office-action response endpoint. Successful response requires the action to be `PENDING` and the server clock to be strictly before `response_due_at`; the caller must be the `InternalAgent` or `ExternalAgent` whose id equals the action's `assigned_agent_id`. On success, the action's `responded_at` is set to the current server time, its `status` flips to `RESPONDED`, the targeted `JurisdictionFiling.status` returns to `FILED`, and — if the parent `IPRight` has no other pending office actions remaining — the parent `IPRight.status` returns to `FILED` as well. Once the linked `JurisdictionFiling` is subsequently registered, the action moves from `RESPONDED` to `CLOSED_GRANTED`.

When `response_due_at` has elapsed without a response, the action may be abandoned. The abandonment endpoint requires the action to be `PENDING` and the server clock to be greater than or equal to `response_due_at`; the resulting transition takes the action to `CLOSED_ABANDONED`, the linked `JurisdictionFiling.status` to `ABANDONED`, and — if the `IPRight` has no remaining `FILED` or `OFFICE_ACTION` filings — bubbles the right up to `ABANDONED` as well.

A `JurisdictionFiling` reaches the end of its happy path through the register endpoint, which requires an `archive_url` body field. The filing must currently be in `FILED` status. On success the filing flips to `REGISTERED`. If, after this transition, every sibling `JurisdictionFiling` of the parent right is in either `REGISTERED` or `ABANDONED`, the parent `IPRight.status` is set to `REGISTERED`, its `registered_at` is recorded as the current server time, and its `certificate_archive_url` is set to the supplied `archive_url`. The same call auto-creates fee-year-1 `AnnualFeeSchedule` rows for every (`jurisdiction`, `ip_type`) pair represented in the right's registered filings.

### 3.3. Annual Fees, Surcharges, and Abandonment

Once an `IPRight` is `REGISTERED` it accrues annuities. Either a `FinanceManager` or an `IPManager` schedules each future annuity by supplying a `jurisdiction` code matching one of the right's filings, a `fee_year` integer of at least 1 (year 1 being the first annuity), a `base_fee_cents` schedule fee in USD cents that must be zero or positive, a `due_date` payment deadline, an optional `auto_pay_authorized` boolean (defaulting to false), and an `assigned_agent_id` who will be responsible for the filing. The schedule starts in `PENDING` status; `grace_end_date` is computed at creation as `due_date` plus 180 days, and the schedule is rejected with `ERR_FEE_DATES_INVALID` if `due_date` is not strictly less than `grace_end_date` or if `grace_end_date` does not equal `due_date` plus exactly 180 days.

A `FinanceManager` pays a `PENDING` or `LATE` schedule via the pay endpoint. Payment computes a late surcharge based on how many days late the payment is, expressed as the floor of the duration between the current server clock and `due_date` in days. When `days_late` is at most zero the `surcharge_rate` is zero. When `days_late` falls in the range from 1 to 30 inclusive (the first late tier, with maximum 30 days), the rate is 0.10. When `days_late` falls in the range from 31 to 90 inclusive (the second tier, maximum 90 days), the rate is 0.25. When `days_late` falls in the range from 91 to 180 inclusive (the third tier, bounded by the 180-day grace maximum), the rate is 0.50. The `surcharge_cents` is the `base_fee_cents` multiplied by that rate, rounded half-up to the nearest integer cent. `total_paid_cents` is then `base_fee_cents` plus `surcharge_cents`, and the schedule transitions to `PAID` with `paid_at` set to the current server time. A `Cost` row of category `ANNUAL_FEE` is booked for the `total_paid_cents`. If `days_late` exceeds 180 — that is, the payment attempt arrives strictly after `grace_end_date` — no surcharge is booked and the schedule is in `ABANDONED` rather than payable status.

Beyond a `FinanceManager`-initiated payment, the same `PENDING → PAID` or `LATE → PAID` transition fires when the external Payment system posts a settled-payment event. When `auto_pay_authorized` on the schedule is false, only `FinanceManager` may settle the fee; when `auto_pay_authorized` is true, the Payment-system event is accepted. The payment amount on either path must equal `base_fee_cents` plus the surcharge computed at the current server clock.

The annual-fee sweep is the system's deferred-action mechanism. When invoked, it scans every `PENDING` schedule whose `due_date` lies strictly before the current server clock and whose `grace_end_date` is at or after the current server clock (with `paid_at` still null), and flips each such row to `LATE`. It also scans every `LATE` schedule whose `grace_end_date` is strictly before the current server clock (with `paid_at` still null) and flips it to `ABANDONED`. When a schedule abandons, the matching jurisdiction's `JurisdictionFiling.status` is also set to `ABANDONED`; if every sibling `JurisdictionFiling` on the parent `IPRight` then sits at `ABANDONED`, the `IPRight.status` itself moves to `ABANDONED`. Crucially, the same cascade fires through a second route: when every `AnnualFeeSchedule` on a registered right has reached `ABANDONED`, the right itself is moved to `ABANDONED`.

### 3.4. Contracts: Drafting, Signing, Filing, Amendment, and Termination

A `Contract` formalizes a transfer or license over an existing `IPRight`. An `IPManager` drafts a contract by supplying the `ip_right_id` being transferred or licensed, a `template_id` of the contract template used as the drafting basis, a `contract_type` taken from `TRANSFER`, `EXCLUSIVE_LICENSE`, or `NON_EXCLUSIVE_LICENSE`, an ordered `parties` array, an optional `royalty_rate`, an optional `min_guarantee_cents`, and a `business_unit_id` that will pay agent and authority fees. Each entry in `parties` carries a `party_id`, a `role` label, a `signature_required` boolean, and a `signed_at` timestamp that starts null. The newly drafted contract enters `DRAFT` status.

Contract creation enforces several structural constraints. The contract's `contract_type` must equal the referenced template's `contract_type` (mismatch returns `ERR_TEMPLATE_TYPE_MISMATCH`). Both license variants require a non-null `royalty_rate`, while a `TRANSFER` contract requires `royalty_rate` to be null and `min_guarantee_cents` to be null (any combination violating this rule returns `ERR_CONTRACT_FIELDS_FOR_TYPE`). The `royalty_rate`, when present, must lie between 0 and 1 inclusive — for instance, 0.10 to represent a ten-percent rate. `min_guarantee_cents` may be set only on an `EXCLUSIVE_LICENSE` contract: setting it on any other contract type returns `ERR_MIN_GUARANTEE_NOT_ALLOWED`. The `parties` array must contain at least one entry with `signature_required` true and must have at least two distinct `party_id` values; either condition's violation returns `ERR_INSUFFICIENT_PARTIES`.

An `IPManager` opens signing on a `DRAFT` contract, transitioning it to `SIGNING`. The precondition is that every entry's `signed_at` is null at the moment of transition; the template's `contract_type` must still equal the contract's own. While the contract is in `SIGNING`, every party with `signature_required` true must record their signature either through the in-system signing endpoint (which sets that party's `signed_at` to the current server time when called by `IPManager` or `Admin` with a `party_id`) or through the external e-signature event. Once the last required party has signed, the contract transitions from `SIGNING` to `SIGNED`.

Filing a `SIGNED` (or `AMENDED`) contract with the authority advances it to `FILED`, sets `filed_with_authority` to true, and — when `contract_type` is `TRANSFER` — also flips the linked `IPRight.status` to `TRANSFERRED`. The referenced right must be in `REGISTERED` status at the moment of filing: filing a contract whose right is not yet registered returns `ERR_IP_NOT_REGISTERED`. The same registration prerequisite applies to license filings.

A `FILED` contract may be opened for amendment, transitioning it to `AMENDED`. The amendment side-effect writes a snapshot of the prior fields into the resulting `AuditEntry.payload` so the change is auditable. An `AMENDED` contract may be re-filed back to `FILED` through the same file-with-authority endpoint.

Termination is available from both `FILED` and `AMENDED`. An `IPManager` calling terminate transitions the contract to `TERMINATED`, but only when no `RoyaltySchedule` row on this contract is currently in `FORECAST` status with a `period_end` greater than the current server clock — that is, only when there is no future royalty period still expected. A future-period `FORECAST` schedule blocks termination.

### 3.5. Royalty Periods and Settlement

A `RoyaltySchedule` represents one royalty period under a `Contract`. An `IPManager` creates schedules by supplying a `period_index` of at least 1, a `period_start` inclusive timestamp, a `period_end` exclusive timestamp greater than `period_start`, and a `forecast_revenue_cents` licensee forecast of zero or higher in cents. The system additionally tracks `actual_revenue_cents` (settable on settlement), `provisional_royalty_cents` and `final_royalty_cents` (both computed), and a `status` that begins at `FORECAST` and ends at `SETTLED`.

When a royalty schedule is created or modified, `provisional_royalty_cents` is computed as the `forecast_revenue_cents` multiplied by the parent contract's `royalty_rate`, rounded half-up to the nearest integer cent. Royalty schedules under the same contract must not overlap and must cover a contiguous timeline — the `period_end` of period N must equal the `period_start` of period N+1, and there must be no gaps. Any violation returns `ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP`.

Settlement is performed by a `FinanceManager`, who supplies the period's `actual_revenue_cents`. On settlement, the raw actual amount is the `actual_revenue_cents` multiplied by the contract's `royalty_rate`, rounded half-up to the nearest integer cent. When the contract's `contract_type` is `EXCLUSIVE_LICENSE`, the `final_royalty_cents` is the maximum of that raw amount and the contract's `min_guarantee_cents` (the licensee's minimum-guarantee floor kicks in here). For every other contract type, the `final_royalty_cents` equals the raw amount with no floor applied. The schedule's `status` flips to `SETTLED`.

### 3.6. Rights-Protection Cases

A `ProtectionCase` exists when a `Counsel` opens enforcement against a third party. The opener supplies the `ip_right_id` alleged to be infringed, the `assigned_agent_id` of the lawyer or agent who will handle it, the `business_unit_id` sponsoring the case, and an optional `rights_holder_currency` (an ISO 4217 code defaulting to `USD`) in which the eventual `recovered_amount_cents` will be denominated. The case starts in `OPEN` status with `route` `NONE`.

Before resolution can occur, evidence is added through the evidence endpoint, which is open to `Counsel`, `InternalAgent`, and `ExternalAgent`. Each `Evidence` row carries a `kind` taken from `WITNESS`, `DOCUMENT`, `SAMPLE`, or `DIGITAL`, a `collected_at` field-collection timestamp, a `storage_uri` storage URL for the artifact, and an optional `chain_of_custody_hash`. The hash is the SHA-256 of the artifact content combined with its timestamp and is required when the case will later be routed to `LITIGATION`.

The `Counsel` then routes the case from `OPEN` to `IN_PROGRESS` by supplying a `route` of `DEMAND_LETTER`, `LITIGATION`, `MEDIATION`, or `ARBITRATION`. Three preconditions apply: the case's `assigned_agent_id` must resolve to an `Agent` whose `jurisdictions` array contains the parent `IPRight`'s `primary_jurisdiction` (failure returns `ERR_AGENT_JURISDICTION_MISMATCH`); when `route` is `LITIGATION`, at least one `Evidence` row on the case must have a non-null `chain_of_custody_hash` (failure returns `ERR_EVIDENCE_MISSING_FOR_LITIGATION`); and the case's `route` must currently be `NONE`. On success the case's `route` is set to the input value and its `status` flips to `IN_PROGRESS`.

Resolution moves the case from `IN_PROGRESS` to `RESOLVED`. The resolver supplies an `outcome` of `WON`, `LOST`, `SETTLED`, or `DISMISSED`, a `recovered_amount_cents`, the case's `legal_fees_cents` and `agent_fees_cents`, and the `punitive_cap_cents` ceiling for the punitive bucket. Resolution requires the case to currently be in `IN_PROGRESS`. The outcome implies a constraint on the recovered amount: a `WON` outcome requires `recovered_amount_cents` strictly greater than zero; `LOST` or `DISMISSED` requires `recovered_amount_cents` exactly zero.

When the outcome is `WON` or `SETTLED`, the system computes the damages-recovery waterfall and stores its output in `distributed`. The waterfall pays four fixed buckets in this order: legal, agent, punitive, and then rights-holder. Starting from a remaining balance equal to `recovered_amount_cents`, the legal bucket is paid the minimum of the remaining balance and `legal_fees_cents`, and the remaining balance is reduced by that paid amount. The agent bucket is then paid the minimum of the new remaining balance and `agent_fees_cents`, with the balance reduced again. The punitive bucket is paid the minimum of the new remaining balance and `punitive_cap_cents`, with the balance reduced again. Whatever balance is left is paid to the rights holder. The `distributed` object captures the four amounts as `legal_paid`, `agent_paid`, `punitive_paid`, and `rights_holder_paid`; their sum is exactly equal to `recovered_amount_cents`. All four inputs are already integer cents, so no rounding is required.

On resolution, a `Cost` row of category `LITIGATION` is booked for the sum of `legal_fees_cents` and `agent_fees_cents`, allocated to the right's owning `BusinessUnit`, and the agent's `performance_rating` is recomputed using the rule in §3.1. Finally, once every distributed amount has been paid (the corresponding cost rows are booked), a `Counsel` closes the case by transitioning it from `RESOLVED` to `CLOSED`.

### 3.7. Cost Booking, Allocation, and Budgets

Every quantifiable expenditure in the system is captured as a `Cost` row. A `FinanceManager` books a cost by supplying a `category` (one of `APPLICATION`, `ANNUAL_FEE`, `LITIGATION`, `AGENT_FEE`), the related entity reference appropriate to the category (`ip_right_id` for application or annual-fee categories — null otherwise; `protection_case_id` when `category` is `LITIGATION`; `agent_id` when `category` is `AGENT_FEE`), the `currency` of the native amount, the `amount_native_cents` in that currency, the `fx_rate_to_usd` multiplier with a strictly positive constraint, an ordered `allocation_rules` array, and a `booked_at` date used for periodic reporting. The system computes `amount_usd_cents` per §2.5 and the `allocations` array per the rule below.

Each entry in `allocation_rules` specifies a `business_unit_id` and a `percent_bps` value in basis points (each basis point is one hundredth of one percent, so a full hundred percent is ten thousand basis points). The array must be non-empty and the entries' `percent_bps` values must sum to exactly 10000; any violation returns `ERR_ALLOCATION_BPS_INVALID`. Every referenced business unit must have `status` equal to `ACTIVE`; an allocation targeting an `ARCHIVED` unit returns `ERR_ALLOCATION_BU_INACTIVE`.

The allocation algorithm distributes `amount_usd_cents` across the rules in their input order. For every rule except the last, the allocated portion is `amount_usd_cents` multiplied by the rule's `percent_bps` divided by 10000, with that product rounded half-up to the nearest integer cent. Each such portion is appended to the `allocations` array as an object containing the rule's `business_unit_id`, the rule's `percent_bps`, and the rounded `allocated_cents`. A running sum of these portions is maintained. The very last rule does not recompute its portion independently: it receives the remainder, computed as `amount_usd_cents` minus the running sum of all previously rounded portions. This rule — round per allocation in order, push remainder to the last entry — guarantees that the sum of all `allocated_cents` equals `amount_usd_cents` exactly, and produces results that may differ from a strategy that sums percentages first and splits the total; the per-allocation order is the contract.

For every business unit that appears in any allocation, the system updates `actual_spend_cents` by summing `allocated_cents` across every `Cost` row's `allocations` whose `business_unit_id` matches that unit. No status filter is applied — every booked cost counts. Before committing an allocation, the system simulates the resulting `actual_spend_cents` for every affected business unit; if the post-allocation value for any unit would strictly exceed that unit's `annual_budget_cents`, the entire allocation is rejected with `ERR_BUDGET_EXCEEDED`. Reallocating an existing cost recomputes `allocations` for the new rules and refreshes `actual_spend_cents` for both the previously-affected and newly-affected business units; the budget cap applies identically on reallocation.

Listing endpoints across the system accept narrow filter query parameters. The cost listing accepts `booked_from` and `booked_to` to bound `booked_at` to a closed date range. The annual-fees listing accepts `due_before` to filter schedules by `due_date`. The audit-entries listing accepts `from_time` and `to_time` to bound entries by their `created_at`. The cost-summary report is a periodic budget-versus-actual report broken down by business unit and category; callers supply `from` and `to` body fields delimiting the reporting window (inclusive of `from`, exclusive of `to`) and an optional `business_unit_id` to restrict scope.

### 3.8. Concurrency, Races, and Test-Driving the Clock

Several endpoints are designed to be raced. When two clients simultaneously attempt to set an `assigned_agent_id` on the same `ApplicationOfficeAction`, the first-writer wins on `ApplicationOfficeAction.assigned_agent_id` and the loser receives `ERR_OFFICE_ACTION_ALREADY_ASSIGNED`. When two clients call the pay endpoint on the same `AnnualFeeSchedule`, exactly one wins by first-writer on `AnnualFeeSchedule.paid_at` and the loser receives `ERR_FEE_ALREADY_PAID`. When a sign and a terminate race on the same `Contract`, exactly one wins by first-writer on `Contract.status` and the loser receives `ERR_INVALID_CONTRACT_STATE`. When two resolve calls race on the same `ProtectionCase`, the first-writer on `ProtectionCase.status` wins and the loser receives `ERR_CASE_ALREADY_RESOLVED`. When two mutations on the same `IPRight` race with stale `version` fields, only the request whose `version` matches the row's current `version` wins, and the loser receives `ERR_VERSION_CONFLICT` per §2.4.

To enable deterministic tests of date-driven behavior — surcharge tiering, sweep transitions, deadline lapses — an `Admin`-only test-driving capability advances the server's logical clock by a supplied number of `seconds`. Subsequent comparisons against `now()` use the advanced clock; the sweep endpoint can then be driven through its full state-transition arc within a single test run.

## 4. Endpoint Definitions

The endpoints below are the system's complete API surface. By convention, creation endpoints return HTTP 201 with the newly created resource in the success envelope; all other action and modification endpoints return HTTP 200 with the updated resource. List endpoints return HTTP 200 with the paginated meta block populated. Request bodies, response bodies, and side effects are described in §2 and §3 — readers needing the exact payload shape must reconstruct it from the workflow narrative there.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /business-units | Create a business unit | Admin |
| GET | /business-units | List business units | Admin, FinanceManager, IPManager, Counsel |
| GET | /business-units/{id} | Get a business unit, including computed `actual_spend_cents` | Admin, FinanceManager, IPManager, Counsel |
| POST | /business-units/{id}/archive | Flip a business unit to `ARCHIVED` status | Admin |
| POST | /agents | Create an agent profile (qualification unverified) | Admin |
| POST | /agents/{id}/verify | Admin verifies the agent's qualification | Admin |
| GET | /agents | List agents with filters and computed workload | Admin, IPManager, FinanceManager, Counsel |
| GET | /agents/{id} | Get a single agent with current workload and performance | Admin, IPManager, FinanceManager, Counsel |
| POST | /ip-rights | Create an IP right in `DRAFT` | IPManager |
| GET | /ip-rights | List IP rights | IPManager, FinanceManager, Counsel, Admin |
| GET | /ip-rights/{id} | Get an IP right with computed fields | IPManager, FinanceManager, Counsel, Admin |
| POST | /ip-rights/{id}/materials-ready | Mark application materials ready; transitions `DRAFT → MATERIALS_READY` | IPManager |
| POST | /ip-rights/{id}/jurisdiction-filings | Create a jurisdiction filing; first filing auto-transitions parent `MATERIALS_READY → FILED` | IPManager |
| POST | /jurisdiction-filings/{id}/register | Register a filing; if all siblings are settled, parent becomes `REGISTERED` | IPManager |
| POST | /ip-rights/{id}/office-actions | Open an office action against one of the right's filings | IPManager |
| POST | /office-actions/{id}/respond | Assigned agent files the response | InternalAgent, ExternalAgent |
| POST | /office-actions/{id}/abandon | Abandon an overdue office action | IPManager |
| POST | /ip-rights/{id}/annual-fees | Schedule a future annuity | FinanceManager, IPManager |
| GET | /annual-fees | List annual fees with filters | FinanceManager, IPManager, Admin |
| POST | /annual-fees/{id}/pay | Pay (or auto-pay) an annual fee | FinanceManager |
| POST | /contract-templates | Create a contract template | Admin |
| GET | /contract-templates | List templates | Admin, IPManager |
| POST | /contracts | Draft a contract | IPManager |
| POST | /contracts/{id}/start-signing | Open the contract for signatures | IPManager |
| POST | /contracts/{id}/sign | Record a party signature | IPManager, Admin |
| POST | /contracts/{id}/file-with-authority | File a SIGNED or AMENDED contract; TRANSFER also flips the right to `TRANSFERRED` | IPManager |
| POST | /contracts/{id}/amend | Open an amendment cycle | IPManager |
| POST | /contracts/{id}/terminate | Terminate a FILED or AMENDED contract | IPManager |
| POST | /contracts/{id}/royalty-schedules | Create one royalty period | IPManager |
| POST | /royalty-schedules/{id}/settle | Settle a royalty period with actual revenue | FinanceManager |
| POST | /protection-cases | Open a rights-protection case | Counsel |
| POST | /protection-cases/{id}/evidence | Add an evidence row | Counsel, InternalAgent, ExternalAgent |
| POST | /protection-cases/{id}/route | Route an OPEN case to its resolution channel | Counsel |
| POST | /protection-cases/{id}/resolve | Resolve a case with outcome; runs damages waterfall when WON/SETTLED | Counsel |
| POST | /protection-cases/{id}/close | Close a RESOLVED case | Counsel |
| POST | /costs | Book a cost row with FX and allocation | FinanceManager |
| PATCH | /costs/{id}/allocation | Reallocate an existing cost | FinanceManager |
| GET | /costs | List costs with filters | FinanceManager, Admin |
| GET | /reports/cost-summary | Periodic cost-summary report (budget vs actual per BU, by category) | FinanceManager, Admin |
| GET | /audit-entries | Query audit log (status changes + contract records) | Admin, FinanceManager, IPManager, Counsel |
| POST | /_clock/advance | Test-only: advance the server clock by N seconds | Admin |
| POST | /_sweep/annual-fees | Trigger the annual-fee sweep | Admin |
| POST | /_events/payment-settled | External Payment-system event: marks an annual fee paid; idempotent on `idempotency_key` | Admin |
| POST | /_events/esign-completed | External e-signature platform event: records a party signature; idempotent on `idempotency_key` | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCED_ENTITY_NOT_FOUND | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_INVALID_CONTRACT_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_OFFICE_ACTION_ALREADY_ASSIGNED | 409 |
| ERR_FEE_ALREADY_PAID | 409 |
| ERR_CASE_ALREADY_RESOLVED | 409 |
| ERR_AGENT_QUALIFICATION_UNVERIFIED | 422 |
| ERR_AGENT_JURISDICTION_MISMATCH | 422 |
| ERR_EVIDENCE_MISSING_FOR_LITIGATION | 422 |
| ERR_TEMPLATE_TYPE_MISMATCH | 422 |
| ERR_CONTRACT_FIELDS_FOR_TYPE | 422 |
| ERR_MIN_GUARANTEE_NOT_ALLOWED | 422 |
| ERR_INSUFFICIENT_PARTIES | 422 |
| ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP | 422 |
| ERR_FEE_DATES_INVALID | 422 |
| ERR_IP_NOT_REGISTERED | 422 |
| ERR_ALLOCATION_BPS_INVALID | 422 |
| ERR_ALLOCATION_BU_INACTIVE | 422 |
| ERR_BUDGET_EXCEEDED | 422 |

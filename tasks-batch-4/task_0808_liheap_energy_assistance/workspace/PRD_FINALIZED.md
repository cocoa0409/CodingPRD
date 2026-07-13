# LIHEAP Energy Assistance API — Product Requirements Document

## 1. Introduction

The Low Income Home Energy Assistance Program (LIHEAP) helps qualifying households keep their homes heated and cooled by paying a portion of their energy bills directly to the utilities and fuel vendors that serve them. This document specifies the backend API for a state-level LIHEAP administration platform. The platform must carry a household from first intake, through income-eligibility screening and documentation, to a finalized benefit award, and finally to money actually moving: a pledge is reserved against a seasonal funding pool, a payment is remitted to an enrolled vendor, and a credit lands on the household's utility account, drawing down arrears before current charges.

Two forces shape almost every rule below. The first is fiscal conservation: a season is funded by a fixed pool of dollars, and the platform must never reserve or disburse more than a pool holds, must release reservations cleanly when a pledge is cancelled or a payment is returned, and must expose enough of the pool's internal ledger for callers to reason about what remains. The second is time pressure: an energy crisis — no heat, a disconnection notice, an empty fuel tank — opens a 48-hour clock, and the platform must be able to resolve the crisis into an expedited payment before that clock expires, or record that the deadline was breached. Because these time-sensitive behaviors must be testable deterministically, the server runs on a logical clock rather than wall-clock time.

The platform serves four distinct actors — applying households, eligibility caseworkers, vendor agents, and program administrators — whose responsibilities do not overlap. The sections that follow define the shared response contract and cross-cutting principles first, then walk the business workflows in the order a benefit actually flows, and close with the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the caller's role. If `X-User-Role` is missing or is not one of the four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation — or an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles are `Applicant`, `Caseworker`, `VendorAgent`, and `ProgramAdmin`.

- When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Household`; ownership checks on any resource that references a `Household` compare the resource's household foreign key to `X-User-ID`. An applicant may create and submit only its own applications, upload income documents against them, and read its own household, applications, income documents, and utility accounts.
- When `X-User-Role` is `VendorAgent`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a `Vendor` compare the resource's vendor foreign key to `X-User-ID`. A vendor agent enrolls its own vendor, reports account status, and remits or returns payments.
- When `X-User-Role` is `Caseworker`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. Caseworkers own the eligibility and disbursement workflow: requesting more information, approving, denying, verifying documents, creating and cancelling pledges, initiating payments, opening and resolving crises, and creating and scheduling weatherization referrals.
- When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`. Program administrators manage funding pools, the vendor registry, season close, and the logical clock.

Detailed authorization per endpoint is given in the §4 table. Where an operation is shared, any of the listed roles may perform it subject to the ownership rules above.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and has no upper bound beyond the size of the collection. A request whose `limit` or `offset` falls outside these bounds is rejected with `ERR_VALIDATION` (HTTP 400). Results are always sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count` (the total number of records matching the filter before pagination), and `has_more` (true when unreturned records remain) inside the `meta` object.

### 2.4. Common Resource Properties, Identifiers, and the Logical Clock

Every resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits, set once at creation. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that starts at 1 and increments by 1 on each mutation. Funding pools, households, applications, income documents, vendors, utility accounts, pledges, crisis benefits, payments, bill credits, and weatherization referrals all carry the full set (`id`, `created_at`, `updated_at`, `version`). Whenever a rule below says a side effect "bumps the version" or "refreshes `updated_at`", it means the version increments by one and the update timestamp advances to the current logical-clock instant.

The server keeps a **logical clock** that is the sole source of "now" for every time-dependent rule — application submission timestamps, crisis report and deadline computation, and crisis resolve/breach decisions. At startup the clock reads exactly `2026-03-01T00:00:00Z`; before any clock-set call it holds that default and never falls back to the host wall-clock. An administrator may move the clock to a supplied instant via the `to_iso8601` field. Advancing the clock is inert on its own — it fires no cascades and changes no crisis status; a crisis only becomes overdue when a later breach action observes that the clock has passed the crisis deadline.

Path parameters are resolved left to right. For any endpoint whose URL contains a resource `id`, that id must resolve to an existing resource before any body or state check runs; an unresolved path id yields `ERR_NOT_FOUND` (HTTP 404). A request to a path that matches no defined route, or one that uses an HTTP method not defined for an otherwise-known path, likewise yields `ERR_NOT_FOUND` (HTTP 404).

### 2.5. Optimistic Concurrency on Funding Pools

Creating a pledge draws down a funding pool's available balance, and pools are the one contended resource in the system. To keep a caller from reserving funds against a stale view of a pool, the pledge-creation request must carry `expected_pool_version` holding the client's last-observed `version` of the target `FundingPool`. If `expected_pool_version` does not equal the pool's current `version` — because another pledge, a payment remittance, a cancellation, or a pool close has advanced the pool's version since the client last read it — the create is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412). The client must re-read the pool (whose detail response exposes the current `version` and derived balances) and retry with the fresh version. No other endpoint takes a version guard field.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and computed in whole cents as integers. The one derived percentage in the system, an application's `fpl_pct`, is computed to two decimal places using round-half-up. The benefit calculation rounds its size and heating components to whole dollars (that is, to the nearest multiple of 100 cents) using round-half-up before summing them, as detailed in §3.4. Where a calculation takes a minimum or maximum across several figures, the comparison is exact on the integer cent values.

### 2.7. Fund Conservation and the Pool Ledger

A `FundingPool` maintains three derived balances that together account for every cent of its `total_allocation_cents`: `reserved_cents` is the sum of `pledged_amount_cents` across all pledges drawing on the pool that are currently in `PLEDGED` status; `disbursed_cents` is the same sum across pledges in `PAID` status; and `available_cents` is `total_allocation_cents` minus `reserved_cents` minus `disbursed_cents`. This identity — allocation equals available plus reserved plus disbursed — holds after every operation. Reserving a pledge moves money from available into reserved; remitting the pledge's payment moves it from reserved into disbursed; cancelling or expiring a pledge, or returning a payment, releases money back the other way. Every such reserve, disburse, or release recomputes all three balances and re-derives the pool's `status` (see §3.1) inside the same request, so the returned pool always reflects the change.

### 2.8. Account Ledger Conservation

A `UtilityAccount` tracks three money buckets against a fixed anchor. At creation the server captures `original_obligation_cents` as `current_balance_cents` plus `arrearage_cents`, and initializes `lifetime_credited_cents` to 0 and `reconnection_eligible` to false. Thereafter the invariant `arrearage_cents + current_balance_cents + lifetime_credited_cents == original_obligation_cents` holds after every credit and every reversal: a credit shifts money out of the arrearage and current-balance buckets into lifetime-credited, and a reversal shifts it back. When a vendor agent later reports fresh balances through the account status-report operation, the anchor is re-established so the invariant continues to hold — `original_obligation_cents` is recomputed as the newly reported `current_balance_cents` plus `arrearage_cents` plus the existing `lifetime_credited_cents`.

### 2.9. Validation Ordering

When several checks could reject one request, they are evaluated in a fixed order so that the returned `error_id` is deterministic. Authentication comes first: a missing or unknown role yields `ERR_UNAUTHENTICATED` (401). Authorization comes next — a role not permitted for the operation, or an ownership-scoped role acting on a resource it does not own, yields `ERR_FORBIDDEN` (403). Then path existence: any unresolved id in the URL yields `ERR_NOT_FOUND` (404). Then, for state-transition endpoints, the generic state guard — a target not in a state that permits the transition yields `ERR_INVALID_STATE` (409) unless a more specific state rule below names a different code. Body-level checks follow: body foreign keys that do not resolve yield `ERR_INVALID_REFERENCE` (422), and component/pool mismatches yield `ERR_POOL_COMPONENT_MISMATCH` (422). Domain-specific temporal, duplicate, fiscal, and concurrency checks (detailed alongside the workflows they guard in §3) then apply. A malformed body — a missing required field, a null where a value is required, a wrong type, or an invalid enum member — is caught by `ERR_VALIDATION` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Seasonal Funding Pools and Their Lifecycle

A program administrator opens a season by creating one or more funding pools. A pool is scoped to a `season_year` and a single `program_component`, which is one of `HEATING`, `COOLING`, or `CRISIS` — the benefit component the pool bankrolls. The administrator supplies the pool's `total_allocation_cents`, which must be greater than zero, and a `depletion_threshold_cents` (zero or greater) that marks the low-water line. A new pool opens with `reserved_cents` and `disbursed_cents` at 0, `available_cents` equal to the full allocation, `version` at 1, and `status` of `OPEN`.

A pool's `status` is not set by hand except at close; it is re-derived from `available_cents` after every reserve, disburse, or release, in this order of precedence. Once the pool has been closed its status is `CLOSED` and stays there permanently. Otherwise, when `available_cents` has reached exactly 0 the status is `DEPLETED`; when `available_cents` is above 0 but at or below `depletion_threshold_cents` the status is `LOW`; and when `available_cents` is strictly above `depletion_threshold_cents` the status is `OPEN`. Because releases raise `available_cents`, a non-closed pool can climb back up the ladder — from `DEPLETED` to `LOW` to `OPEN` — exactly as reservations pushed it down from `OPEN` to `LOW` to `DEPLETED`.

Closing a pool is the administrator's end-of-season action and is available from `OPEN`, `LOW`, or `DEPLETED` (any non-closed state); attempting to close an already-closed pool is rejected by the generic state guard with `ERR_INVALID_STATE`. Closing sets `status` to `CLOSED`, which is terminal, and then cascades: every pledge still in `PLEDGED` status that draws on this pool transitions from `PLEDGED` to `EXPIRED`, and each expired pledge releases its `pledged_amount_cents` back to the pool by subtracting that amount from `reserved_cents` and letting the pool balances recompute. The close bumps the pool's `version` by one.

### 3.2. Household Intake and Application Eligibility

A caseworker (or an administrator) registers a household at intake, recording the `primary_applicant_name`, the `household_size` (at least 1), the self-reported gross `annual_income_cents` (zero or greater), the `state_code` (two-letter USPS code) and `county` of residence, and the household's `heating_source`, one of `ELECTRICITY`, `NATURAL_GAS`, `FUEL_OIL`, or `PROPANE`. Two vulnerability flags are captured: `has_elderly_or_disabled` and `has_child_under_6`, each defaulting to false when omitted. These flags feed both the benefit supplement and the weatherization-referral priority later on.

An application is created against a household by naming the household through its `household_id`, the `season_year` targeted, and the requested `program_component`, which for an application is one of `HEATING` or `COOLING`. A freshly created application is in `DRAFT` status and carries no benefit figures yet. An applicant may create only its own application; caseworkers may create on a household's behalf.

Submitting an application moves it from `DRAFT` to `SUBMITTED` (and, as described in §3.3, is also how a returned application moves from `INFO_REQUESTED` back to `SUBMITTED`). Submission is an applicant-only action on the applicant's own application. Three preconditions guard the first submit. First, a matching funding pool must exist for the application's `season_year` and `program_component` and must not be closed; if the matching pool's status is `CLOSED`, the submit is rejected with `ERR_SEASON_CLOSED`. Second, no other application for the same `household_id`, `season_year`, and `program_component` may already be in `SUBMITTED`, `INFO_REQUESTED`, or `APPROVED` status; a collision is rejected with `ERR_DUPLICATE_APPLICATION`. Third, the applicant's provisional income eligibility must pass: using the household's self-reported `annual_income_cents`, the computed `fpl_pct` must be at or below 150.00, and if it exceeds that ceiling the submit is rejected with `ERR_INCOME_INELIGIBLE`.

On a successful submit the server computes `fpl_pct` from the household's self-reported income (the income-eligibility calculation of §3.4), sets `income_eligible` to true, computes the provisional `benefit_tier` and `benefit_amount_cents` from the benefit calculation using that same self-reported income, sets `benefit_variant` to `PROVISIONAL`, and stamps `submitted_at` with the current logical-clock time. A resubmission from `INFO_REQUESTED` re-runs the season-open and provisional-income checks and recomputes `fpl_pct`, `benefit_tier`, and `benefit_amount_cents` in the same provisional manner, refreshing `submitted_at` to the current logical-clock time.

### 3.3. Income Documentation, Verification, and the Info-Request Cycle

Before an application can be approved, income has to be documented and confirmed. An applicant or caseworker uploads an income document against an application, naming it through `application_id`, giving its `doc_type` — one of `PAYSTUB`, `TAX_RETURN`, `BENEFIT_LETTER`, or `SELF_ATTESTATION` — and the `reported_income_cents` figure claimed on the document (zero or greater). A new document is in `PENDING` status and its `verified_income_cents` is not yet set.

A caseworker verifies a document by supplying an `outcome` of either `VERIFIED` or `REJECTED`; the document must be in `PENDING` status or the generic state guard rejects with `ERR_INVALID_STATE`. When the outcome is `VERIFIED`, the document moves from `PENDING` to `VERIFIED` and its `verified_income_cents` is set from the request's supplied figure; this confirmed figure is what feeds the final benefit variant at approval. When the outcome is `REJECTED`, the document moves from `PENDING` to `REJECTED` and does not count toward approval.

Between submission and a decision, a caseworker may send an application back for more information, moving it from `SUBMITTED` to `INFO_REQUESTED`; this action requires the application be in `SUBMITTED` status. From `INFO_REQUESTED` the applicant resubmits (as described in §3.2), returning the application to `SUBMITTED` — the revision cycle that lets an applicant correct or supplement a filing without starting over.

### 3.4. Approval, Benefit Finalization, and Automatic Weatherization Referral

Approval is a caseworker action that requires the application be in `SUBMITTED` status; from any other state it is rejected with `ERR_INVALID_STATE`. Two further gates apply. At least one income document for the application must be in `VERIFIED` status, or approval is rejected with `ERR_INCOME_NOT_VERIFIED`. And the applicant must remain income-eligible on verified income: the `fpl_pct` recomputed from verified income must be at or below 150.00, or approval is rejected with `ERR_INCOME_INELIGIBLE`.

On approval the benefit is recomputed as the **final** variant. Income for this final computation is the `verified_income_cents` of the verified income document with the greatest `created_at` — the most recently created among documents in `VERIFIED` status. The server recomputes `fpl_pct`, `benefit_tier`, and `benefit_amount_cents` from that verified income, sets `benefit_variant` to `FINAL`, and moves the application from `SUBMITTED` to `APPROVED`. Because verified income can differ from the self-reported figure, the final tier and `benefit_amount_cents` may land in a different band than the provisional values. If the final `benefit_tier` is `TIER_1`, approval additionally creates a weatherization referral for the household, carrying the application's `household_id` and `application_id`, a `referral_reason` of `TIER_1_AUTO`, and `REFERRED` status.

Denial is the opposite branch of the same fork: a caseworker denies an application that is in `SUBMITTED` status (otherwise `ERR_INVALID_STATE`), optionally supplying a `denial_reason`. Denial moves the application from `SUBMITTED` to `DENIED`, stores the `denial_reason`, leaves `benefit_amount_cents` at its last provisional value, and creates no pledge and no referral.

**Income eligibility (`fpl_pct`).** Eligibility is measured against the Federal Poverty Level for the household's size. The annual FPL figure in cents is looked up by household size: 1,506,000 for a size of 1; 2,044,000 for 2; 2,582,000 for 3; 3,120,000 for 4; 3,658,000 for 5; 4,196,000 for 6; 4,734,000 for 7; and 5,272,000 for 8. For a household larger than 8, the size-8 figure is used as the base and 538,000 cents is added for each person beyond the eighth. The `fpl_pct` is the applicable income in cents divided by that annual FPL figure, multiplied by 100, and rounded half-up to two decimal places. The income used is the household's self-reported `annual_income_cents` at submission and the verified income at approval. A household is `income_eligible` — and clears the eligibility gate — when `fpl_pct` is at or below 150.00 inclusive; above that it is ineligible.

**Benefit tier and award (`benefit_amount_cents`).** The `benefit_tier` follows directly from `fpl_pct`: `TIER_1` when `fpl_pct` is at or below 75, otherwise `TIER_2` when it is at or below 110, otherwise `TIER_3` when it is at or below 150, otherwise `INELIGIBLE` above 150. Each tier carries a base amount in cents — 81,500 for `TIER_1`, 61,000 for `TIER_2`, and 40,500 for `TIER_3`. From that base the server derives two components. The **size component** in cents is the base multiplied by a size multiplier equal to 1.0 plus 0.10 for each household member beyond the second (that is, 1.0 plus 0.10 times the household size minus 2, with the count of extra members never taken below zero, so households of one or two persons use a multiplier of exactly 1.0). The **heating component** in cents is the base multiplied by the heating factor of the household's `heating_source` reduced by 1.0, where the heating factors are 1.0 for `ELECTRICITY`, 1.1 for `NATURAL_GAS`, 1.3 for `FUEL_OIL`, and 1.25 for `PROPANE` (so electric-heated households add nothing from this component). A **vulnerability component** of 15,000 cents is added when the household has either the `has_elderly_or_disabled` or the `has_child_under_6` flag set, and is 0 when neither is set.

**Component rounding (order matters).** The three components are combined by rounding each of the size and heating components to the nearest whole dollar — the nearest multiple of 100 cents, round-half-up — and then summing the two rounded figures together with the vulnerability component. The vulnerability component is already a whole-dollar amount, so it is added as-is. This is a round-then-sum order: each component is rounded individually first, and only then are they added; summing first and rounding once is the wrong interpretation and will yield different awards at the boundaries. The summed figure is finally clamped to lie between a floor of 10,000 cents and a ceiling of 150,000 cents — any raw sum below the floor is raised to 10,000, and any above the ceiling is lowered to 150,000 — and the clamped result is `benefit_amount_cents`.

### 3.5. Vendors and Utility Accounts

Money reaches a household through a vendor and a utility account. A program administrator registers a vendor with its `name`, its `vendor_type` — one of `ELECTRIC`, `GAS`, `OIL`, `PROPANE`, or `WATER` — and a `remittance_account` identifier. A new vendor is in `PENDING` status. A vendor agent (or an administrator) then enrolls the vendor, moving it from `PENDING` to `ENROLLED`; enrollment requires the vendor be in `PENDING` status. Only an enrolled vendor may receive pledges and remittances, as the pledge and remittance workflows enforce below.

A utility account ties a household to a vendor. A caseworker or vendor agent creates one, naming the account holder through `household_id`, the servicing vendor through `vendor_id`, the vendor-side `account_number`, and the `service_type` — one of `HEATING`, `COOLING`, `ELECTRIC`, or `GAS`. The account's opening `current_balance_cents` and `arrearage_cents` may be supplied (each zero or greater, each defaulting to 0), along with `is_disconnected` (defaulting to false). At creation the server sets `lifetime_credited_cents` to 0, sets `reconnection_eligible` to false, and captures `original_obligation_cents` as the opening current balance plus arrearage — the ledger anchor described in §2.8.

A vendor agent can report fresh account state at any time, updating any of `current_balance_cents`, `arrearage_cents`, and `is_disconnected`. Reporting new balances re-anchors the ledger: `original_obligation_cents` is recomputed as the reported `current_balance_cents` plus `arrearage_cents` plus the existing `lifetime_credited_cents`, so the conservation invariant of §2.8 continues to hold across the change.

### 3.6. Pledges: Reserving Funds Against a Pool

A pledge is a caseworker's commitment of pool money to a specific vendor on behalf of a specific account. Creating a pledge names an optional `application_id` (present for benefit pledges, absent for crisis-driven pledges), the `vendor_id` to be paid, the `funding_pool_id` the funds draw from, and the `utility_account_id` to be credited. It carries a `pledge_type` — one of `HEATING`, `COOLING`, `CRISIS`, `RECONNECTION`, or `ARREARAGE` — a `pledged_amount_cents` greater than zero, a coverage window bounded by `benefit_period_start` and `benefit_period_end` (both inclusive), and the `expected_pool_version` OCC guard of §2.5. A new pledge is in `PLEDGED` status.

Pledge creation runs a sequence of guards. When an `application_id` is present, the referenced application must be in `APPROVED` status, or the create is rejected with `ERR_APPLICATION_NOT_APPROVED`. The referenced `vendor_id`, `funding_pool_id`, and `utility_account_id` must each resolve to an existing resource, or the create is rejected with `ERR_INVALID_REFERENCE`. The vendor must be `ENROLLED`, or the create is rejected with `ERR_VENDOR_NOT_ENROLLED`. The `pledge_type` must map to the pool's `program_component`: `HEATING` maps to a `HEATING` pool, `COOLING` to a `COOLING` pool, both `CRISIS` and `RECONNECTION` to a `CRISIS` pool, and `ARREARAGE` to a `HEATING` pool; a mismatch is rejected with `ERR_POOL_COMPONENT_MISMATCH`. The coverage window must not overlap any existing `PLEDGED` or `PAID` pledge on the same `utility_account_id`, treating both windows as closed intervals so that sharing even a single day counts as an overlap, or the create is rejected with `ERR_BENEFIT_PERIOD_OVERLAP`. A `RECONNECTION` pledge additionally requires that the utility account's `is_disconnected` be true, or the create is rejected with `ERR_ACCOUNT_NOT_DISCONNECTED`. The pool must be neither `CLOSED` nor `DEPLETED`, or the create is rejected with `ERR_POOL_DEPLETED`. The `pledged_amount_cents` must be at or below the pool's `available_cents`, or the create is rejected with `ERR_BENEFIT_EXCEEDS_AVAILABLE`. Finally, `expected_pool_version` must equal the pool's current `version`, or the create is rejected with `ERR_STALE_POOL_VERSION`.

On a successful create the pledge is set to `PLEDGED`, the pool's `reserved_cents` is increased by `pledged_amount_cents`, the pool's `available_cents` and `status` are re-derived (crossing into `LOW` or `DEPLETED` as the thresholds dictate), and the pool's `version` is bumped by one.

A caseworker may cancel a pledge that is in `PLEDGED` status (otherwise `ERR_INVALID_STATE`). Cancellation moves the pledge from `PLEDGED` to `CANCELLED`, releases the reservation by subtracting `pledged_amount_cents` from the pool's `reserved_cents`, re-derives the pool's `available_cents` and `status`, and bumps the pool's `version` by one. A pledge can also reach `EXPIRED` — not by a direct call but as the season-close cascade of §3.1, which likewise releases its reservation back to the pool.

### 3.7. Payments, Remittance, and the Bill-Credit Waterfall

A payment carries pool money the last step, to the vendor. A caseworker initiates a payment against a pledge by naming the `pledge_id` and the `amount_cents` (greater than zero); a new payment is in `INITIATED` status. A vendor agent then remits the payment, which requires the payment be in `INITIATED` status (otherwise `ERR_INVALID_STATE`), the pledge still be in `PLEDGED` status, and the pledge's vendor be `ENROLLED` (otherwise `ERR_VENDOR_NOT_ENROLLED`).

Remittance is the system's richest cascade. The payment moves from `INITIATED` to `REMITTED` and its `remitted_at` is stamped with the current logical-clock time. The pledge advances from `PLEDGED` to `PAID`, which moves its amount on the pool from reserved to disbursed — `reserved_cents` is decreased and `disbursed_cents` increased by the pledged amount — the pool `status` is re-derived, and the pool `version` is bumped by one. The server then creates a bill credit recording the `payment_id` that produced it, the `utility_account_id` credited, and a `credit_amount_cents` equal to the payment's `amount_cents`, in `APPLIED` status. That credit is applied to the account through an arrearage-first waterfall: the `applied_to_arrearage_cents` is the lesser of the credit amount and the account's current `arrearage_cents`; the remainder of the credit after arrears is the `applied_to_current_cents`, computed as the lesser of that remainder and the account's `current_balance_cents`. Any excess beyond arrearage plus current balance is left unallocated and never drives a balance negative. The account is then updated: `arrearage_cents` is decreased by `applied_to_arrearage_cents`, `current_balance_cents` is decreased by `applied_to_current_cents`, and `lifetime_credited_cents` is increased by the sum actually applied to the two buckets. If, after this application, the account's `arrearage_cents` has reached 0 and the account is disconnected (`is_disconnected` true), the account's `reconnection_eligible` is set to true — the household has cleared its arrears and may be reconnected.

Bill credits are never created directly; the only way to observe a cascade-created credit is to fetch or list them. A vendor agent may return a remitted payment, which requires the payment be in `REMITTED` status, or the return is rejected with `ERR_PAYMENT_NOT_REMITTED`. Returning moves the payment from `REMITTED` to `RETURNED` and fully compensates the ledger: the associated bill credit moves from `APPLIED` to `REVERSED`, the account's `arrearage_cents` is increased back by `applied_to_arrearage_cents`, its `current_balance_cents` is increased back by `applied_to_current_cents`, and its `lifetime_credited_cents` is decreased by `credit_amount_cents`, restoring the account conservation invariant. If after the reversal the account's `arrearage_cents` is again greater than 0, its `reconnection_eligible` is set back to false.

### 3.8. Energy Crisis Benefits and the 48-Hour Deadline

A crisis benefit is the expedited path for a household facing an energy emergency. A caseworker opens one by naming the `household_id`, the `utility_account_id` in crisis, the `funding_pool_id` to draw from, and the `crisis_type` — one of `NO_HEAT`, `DISCONNECTION_NOTICE`, or `OUT_OF_FUEL`. The three referenced resources must exist, or the create is rejected with `ERR_INVALID_REFERENCE`. The named pool must be a `CRISIS`-component pool, or the create is rejected with `ERR_POOL_COMPONENT_MISMATCH`. And the new crisis window must not overlap an existing `OPEN` crisis for the same household: each crisis occupies the half-open interval from its `reported_at` up to but not including its `resolve_by`, so two crises that merely touch at a `resolve_by` boundary are allowed, but any true overlap is rejected with `ERR_CRISIS_WINDOW_OVERLAP`.

On creation the server stamps `reported_at` with the current logical-clock time and sets `resolve_by` to exactly 48 hours after `reported_at` — the crisis deadline. It fixes `estimated_benefit_cents` at report time as the flat crisis rate for the `crisis_type`: 50,000 cents for `NO_HEAT`, 40,000 cents for `DISCONNECTION_NOTICE`, and 60,000 cents for `OUT_OF_FUEL`. The crisis opens in `OPEN` status with `resolved_benefit_cents` present and null.

Resolving a crisis is the caseworker's success branch and requires the crisis be in `OPEN` status (otherwise `ERR_INVALID_STATE`), the current logical-clock time be strictly before `resolve_by` — resolving at or after the deadline is rejected with `ERR_CRISIS_DEADLINE_PASSED` — and the crisis pool be neither `DEPLETED` nor `CLOSED`, or the resolve is rejected with `ERR_POOL_DEPLETED`. On resolve the server computes `resolved_benefit_cents` as the least of three figures: the `estimated_benefit_cents` fixed at report, the crisis pool's live `available_cents`, and the account's total owed, meaning its `current_balance_cents` plus `arrearage_cents`. Because it is a minimum against live balances, the resolved amount can be strictly less than the estimate. The server then creates an expedited pledge with no `application_id`, whose `vendor_id` is the utility account's servicing vendor, drawing on the same `funding_pool_id` and crediting the same `utility_account_id`, with a `pledge_type` of `CRISIS` and a `pledged_amount_cents` equal to `resolved_benefit_cents`, in `PLEDGED` status — reserving that amount against the crisis pool exactly as an ordinary pledge would. This expedited pledge carries `benefit_period_start`, `benefit_period_end`, and `expected_pool_version` all null, and is created directly: it does not re-run any of the ordinary pledge-creation guards (the vendor-enrolled check, the `pledge_type`-to-pool-component check, the coverage-window overlap check, the `RECONNECTION`-disconnected check, the amount-versus-available check, and the OCC `expected_pool_version` check are all skipped), and because its coverage window is null it is itself skipped by the account coverage-window overlap scan that ordinary pledge creation performs. The crisis moves from `OPEN` to `RESOLVED`.

Breaching is the deadline-missed branch and requires the crisis be in `OPEN` status (otherwise `ERR_INVALID_STATE`) and the current logical-clock time be at or after `resolve_by`; attempting to breach before the deadline has passed is rejected with `ERR_CRISIS_NOT_DUE`. Breaching moves the crisis from `OPEN` to `BREACHED`, creates no pledge, and leaves `resolved_benefit_cents` null — the crisis is escalated as a missed deadline. Advancing the logical clock past a crisis's `resolve_by` does not itself change the crisis; only an explicit breach action, observing that the clock has passed the deadline, performs the transition.

### 3.9. Weatherization Referrals

A weatherization referral flags a household for a home energy-efficiency visit. Besides the automatic `TIER_1_AUTO` referral raised at approval (§3.4), a caseworker may create one directly, naming the `household_id`, an optional source `application_id`, and a `referral_reason` — one of `HIGH_ENERGY_BURDEN`, `TIER_1_AUTO`, or `VENDOR_REPORTED`. The referenced household must exist, or the create is rejected with `ERR_INVALID_REFERENCE`; and when an `application_id` is supplied, it too must resolve to an existing application, or the create is likewise rejected with `ERR_INVALID_REFERENCE`. A new referral is in `REFERRED` status, and its `priority` is computed at creation from the reason together with the household's vulnerability: the priority is `HIGH` when the `referral_reason` is `TIER_1_AUTO` or the household has `has_elderly_or_disabled` set; otherwise it is `MEDIUM` when the household has `has_child_under_6` set; otherwise it is `LOW`. A caseworker later schedules a referred visit, moving the referral from `REFERRED` to `SCHEDULED`, which requires the referral be in `REFERRED` status.

## 4. Endpoint Definitions

All endpoints are mounted under the `/liheap` prefix, except the administrative logical-clock control. Endpoints that create a brand-new resource return HTTP 201; endpoints that read or modify an existing resource (including all state transitions and list queries) return HTTP 200. Request bodies, response bodies, and side effects are not repeated here — refer back to the §3 narratives to reconstruct each operation's inputs and effects.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/liheap/funding-pools` | Create a seasonal funding pool | ProgramAdmin |
| GET | `/liheap/funding-pools/{id}` | Fetch one funding pool (exposes version and derived balances) | ProgramAdmin, Caseworker |
| POST | `/liheap/funding-pools/{id}/close` | Close a pool at season end; expires outstanding pledges | ProgramAdmin |
| POST | `/liheap/households` | Register a household (intake) | Caseworker, ProgramAdmin |
| GET | `/liheap/households/{id}` | Fetch one household | Applicant, Caseworker, ProgramAdmin |
| POST | `/liheap/applications` | Create a benefit application (DRAFT) | Applicant, Caseworker |
| GET | `/liheap/applications/{id}` | Fetch one application | Applicant, Caseworker, ProgramAdmin |
| GET | `/liheap/applications` | List applications (filterable) | Caseworker, ProgramAdmin |
| POST | `/liheap/applications/{id}/submit` | Submit or resubmit an application | Applicant |
| POST | `/liheap/applications/{id}/request-info` | Request more information (SUBMITTED→INFO_REQUESTED) | Caseworker |
| POST | `/liheap/applications/{id}/approve` | Approve an application; finalize benefit; maybe auto-refer | Caseworker |
| POST | `/liheap/applications/{id}/deny` | Deny an application | Caseworker |
| POST | `/liheap/income-documents` | Upload an income document (PENDING) | Applicant, Caseworker |
| GET | `/liheap/income-documents/{id}` | Fetch one income document | Applicant, Caseworker |
| GET | `/liheap/income-documents` | List income documents (filter by application) | Caseworker, ProgramAdmin |
| POST | `/liheap/income-documents/{id}/verify` | Verify or reject an income document | Caseworker |
| POST | `/liheap/vendors` | Register a utility / fuel vendor (PENDING) | ProgramAdmin |
| GET | `/liheap/vendors/{id}` | Fetch one vendor | VendorAgent, Caseworker, ProgramAdmin |
| POST | `/liheap/vendors/{id}/enroll` | Enroll a vendor (PENDING→ENROLLED) | VendorAgent, ProgramAdmin |
| POST | `/liheap/utility-accounts` | Create a household's utility account | Caseworker, VendorAgent |
| GET | `/liheap/utility-accounts/{id}` | Fetch one utility account | Applicant, Caseworker, VendorAgent, ProgramAdmin |
| GET | `/liheap/utility-accounts` | List utility accounts (filter by household or vendor) | Caseworker, VendorAgent, ProgramAdmin |
| POST | `/liheap/utility-accounts/{id}/report-status` | Report current balance / arrearage / disconnection | VendorAgent |
| POST | `/liheap/pledges` | Create a benefit pledge drawing on a funding pool (OCC-guarded) | Caseworker |
| GET | `/liheap/pledges/{id}` | Fetch one pledge | Caseworker, VendorAgent, ProgramAdmin |
| GET | `/liheap/pledges` | List pledges (filterable by any FK or status) | Caseworker, VendorAgent, ProgramAdmin |
| POST | `/liheap/pledges/{id}/cancel` | Cancel a PLEDGED pledge (releases reserved funds) | Caseworker |
| POST | `/liheap/payments` | Initiate a direct-vendor payment against a pledge | Caseworker |
| GET | `/liheap/payments/{id}` | Fetch one payment | Caseworker, VendorAgent, ProgramAdmin |
| GET | `/liheap/payments` | List payments (filter by pledge) | Caseworker, VendorAgent, ProgramAdmin |
| POST | `/liheap/payments/{id}/remit` | Remit payment to vendor; create and apply the bill credit | VendorAgent |
| POST | `/liheap/payments/{id}/return` | Return a remitted payment; reverse the bill credit | VendorAgent |
| GET | `/liheap/bill-credits/{id}` | Fetch one bill credit | Caseworker, VendorAgent, ProgramAdmin |
| GET | `/liheap/bill-credits` | List bill credits (filter by payment or utility account) | Caseworker, VendorAgent, ProgramAdmin |
| POST | `/liheap/crisis-benefits` | Open a 48-hour energy crisis benefit | Caseworker |
| GET | `/liheap/crisis-benefits/{id}` | Fetch one crisis benefit | Caseworker, ProgramAdmin |
| GET | `/liheap/crisis-benefits` | List crisis benefits (filter by household / account / pool / status) | Caseworker, ProgramAdmin |
| POST | `/liheap/crisis-benefits/{id}/resolve` | Resolve an OPEN crisis before its deadline; create an expedited pledge | Caseworker |
| POST | `/liheap/crisis-benefits/{id}/breach` | Mark an OPEN crisis BREACHED after its deadline has passed | Caseworker, ProgramAdmin |
| POST | `/liheap/weatherization-referrals` | Create a weatherization referral | Caseworker |
| GET | `/liheap/weatherization-referrals/{id}` | Fetch one referral | Caseworker, ProgramAdmin |
| GET | `/liheap/weatherization-referrals` | List referrals (filter by household, application, or status) | Caseworker, ProgramAdmin |
| POST | `/liheap/weatherization-referrals/{id}/schedule` | Schedule a referred weatherization visit (REFERRED→SCHEDULED) | Caseworker |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_APPLICATION_NOT_APPROVED | 409 |
| ERR_INVALID_REFERENCE | 422 |
| ERR_POOL_COMPONENT_MISMATCH | 422 |
| ERR_SEASON_CLOSED | 409 |
| ERR_CRISIS_DEADLINE_PASSED | 409 |
| ERR_CRISIS_NOT_DUE | 409 |
| ERR_DUPLICATE_APPLICATION | 409 |
| ERR_INCOME_INELIGIBLE | 422 |
| ERR_INCOME_NOT_VERIFIED | 409 |
| ERR_CRISIS_WINDOW_OVERLAP | 409 |
| ERR_BENEFIT_PERIOD_OVERLAP | 409 |
| ERR_ACCOUNT_NOT_DISCONNECTED | 422 |
| ERR_VENDOR_NOT_ENROLLED | 409 |
| ERR_POOL_DEPLETED | 409 |
| ERR_BENEFIT_EXCEEDS_AVAILABLE | 409 |
| ERR_PAYMENT_NOT_REMITTED | 409 |
| ERR_STALE_POOL_VERSION | 412 |

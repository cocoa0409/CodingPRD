# Community Choice Aggregation Program API — Product Requirements Document

## 1. Introduction

California's Community Choice Aggregation model lets cities and counties procure electricity on behalf of their residents while the incumbent investor-owned utility continues to deliver power, read meters, and send bills. That split of responsibilities creates an unusually demanding operational surface for the CCA itself: customers are enrolled by default through statutory opt-out notice waves, rates must be set by a governing board against the incumbent's published generation rate, wholesale supply must be contracted ahead of load, billing rides on the utility's bill with cash remitted back afterward, and regulators expect auditable filings on renewable content and exit-fee forecasts. This document specifies the API that a Joint Powers Authority uses to run that entire operating cycle.

The system covers the full program arc. A `BoardDirector` bootstraps the singleton Authority and sets its rate policy; a `ProgramOperator` ingests eligible service accounts and drives statutory notice waves that sweep prospects into enrollment unless they elect out; a `RateAnalyst` drafts products and rate schedules that a `BoardDirector` adopts under a segregation-of-duties two-key chain; a `PortfolioManager` contracts supply and sizes it against forecast snapshots; a `BillingCoordinator` hands monthly generation-charge extracts to the utility and reconciles the remittance files that come back; a `FinanceController` settles cash, manages bad-debt pools, and absorbs the capped uncollectible share; and a `ComplianceOfficer` prepares CPUC filings supported by renewable-credit retirements. A `UtilityLiaison` plays the counterparty side, accepting or rejecting extracts and returning CPUC dispositions.

Three cross-cutting concerns shape nearly every workflow in this document. First, time itself is modeled: the server keeps a logical clock that drives statutory deadlines, enrollment effective dates, and contract delivery windows, so tests and operations can walk the calendar deterministically. Second, money moves through a small number of disciplined ledger paths — billed-generation ledgers per account, a rate-stabilization reserve on the Authority, and a capped bad-debt sharing split — with pinned rounding and evaluation order so that two honest implementations cannot disagree by a cent. Third, every consequential approval chain enforces segregation of duties, so the same operator can never carry a sensitive record across two adjacent steps of its lifecycle.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. The system recognizes nine roles, spelled exactly as follows: `BoardDirector`, `RateAnalyst`, `ProgramOperator`, `CustomerService`, `PortfolioManager`, `BillingCoordinator`, `FinanceController`, `ComplianceOfficer`, and `UtilityLiaison`. A request missing either header, or carrying an `X-User-Role` value outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). An authenticated request whose role is not in the target endpoint's authorized role list is rejected with `ERR_FORBIDDEN` (HTTP 403).

For every role in this system, `X-User-ID` is an **opaque** operator identifier not tied to any persisted entity. The server may record it — for example, a rate schedule stamps `proposed_by` and `adopted_by`, a compliance filing stamps `prepared_by` and `reviewed_by`, and the remittance and bad-debt workflows retain the acting operator id for their two-key chains — but the server never compares `X-User-ID` to any entity's `id`. This applies identically to `BoardDirector`, `RateAnalyst`, `ProgramOperator`, `CustomerService`, `PortfolioManager`, `BillingCoordinator`, `FinanceController`, `ComplianceOfficer`, and `UtilityLiaison`.

Segregation of duties is the reason these opaque ids are recorded at all. Several approval chains in this program — rate proposal versus adoption or rejection, filing preparation versus review, remittance reconciliation versus settlement, and pool close versus true-up — forbid the same `X-User-ID` from performing adjacent steps. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). The specific pairings are enumerated with each workflow in §3.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Out-of-range values are clamped, not rejected: a `limit` below 1 is raised to 1 and a `limit` above 100 is lowered to 100, and an `offset` below 0 is raised to 0; a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. List endpoints accept exact-match query-parameter filters on resource fields, as follows: service accounts filter on `enrollment_state`, `product_election`, `service_class`, `current_enrollment_notice_id`, and `uncollectible_flag` (the string `true`, case-insensitive, selects flagged accounts and any other value selects unflagged ones); enrollment notices on `status`; opt-out requests on `service_account_id`, `enrollment_notice_id`, `election_type`, and `reversal_of_request_id`; products on `status` and `election_key`; rate schedules on `product_id` and `status`; supply contracts on `status`, `contract_type`, and `vintage_year`; load forecasts on `forecast_variant` and `period_year`; billing extracts on `status` and `billing_month`; billing lines on `service_account_id` and `billing_extract_id`; remittance files on `status` and `remittance_period`; bad-debt pools on `status`; compliance filings on `filing_type`, `status`, and `compliance_year`; REC retirements on `compliance_filing_id` and `supply_contract_id`. The integer-valued filters (`vintage_year`, `period_year`, `compliance_year`) reject a non-integer filter value with `ERR_INVALID_REQUEST`.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Epoch-Advance Checkpoint

All statutory and contractual time gates in this program evaluate against a server-maintained **logical clock**, never against wall-clock time. At server startup the logical clock reads exactly `2026-05-01T00:00:00Z`; before any explicit set call the clock must continue to read that default and must not fall back to wall-clock time under any circumstances. A `BoardDirector` may set the logical clock by supplying a `to_iso8601` instant — the success response body is an object carrying the new reading as `current_utc` — and every timestamp the server stamps itself — `received_at` on an opt-out election, `submitted_on` on an extract, `as_of` on a forecast snapshot, `retired_on` on a REC retirement — is taken from this logical clock.

Separately from setting the clock, the system exposes an **epoch-advance ops run**, also restricted to a `BoardDirector`. This is a checkpoint that fires every scheduled transition whose time gate has been met at the current logical instant: closed notice waves flip their noticed accounts into enrollment, and supply contracts cross from execution into delivery and from delivery into closure. The run returns a summary payload containing `advanced_notices`, `flipped_accounts`, and `advanced_contracts`, each an integer count of the resources the checkpoint moved. Nothing else in the system fires these transitions — a wave that has passed its enrollment effective date simply waits for the next epoch-advance run.

### 2.5. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified. Any mutation of the resource refreshes this field.
- **`version` (integer):** A system-managed counter, starting at 1, that increments with every modification to the resource and serves as the basis for optimistic concurrency control.

The Authority, service accounts, enrollment notices, products, rate schedules, supply contracts, billing extracts, remittance files, bad-debt pools, and compliance filings all carry this full set. Two resource families are deliberately lighter: opt-out requests, load forecast snapshots, billing lines, and REC retirements are append-only records — they carry only `id` and `created_at`, and both `updated_at` and `version` are absent from them entirely. Any cascade that mutates a resource refreshes that resource's `updated_at` and increments its `version` unless the specific cascade says otherwise; §3 names each case explicitly.

### 2.6. Monetary Precision and Rounding Discipline

Money in this program is tracked in integer cents. Two rounding rules govern every computation, and they are pinned so that implementations cannot drift:

- **Round half up** is the only rounding method used anywhere in the system.
- **Round per line, then sum** — never sum-then-round. Each billing line's generation charge and PCIA charge is rounded to whole cents independently at posting time, and the parent extract's totals are the sums of those already-rounded line values. The same discipline applies wherever an accumulation occurs: per-item rounding happens first, accumulation second.

Beyond cents, the system keeps three other precision contracts. Load forecast energies are expressed to 0.001 MWh, resource-adequacy requirements are rounded up to the nearest 0.1 MW, and renewable-content attainment percentages are rounded half up to four decimal places. Wherever a basis-points quantity is computed — the rate comparison margin, the utility's billing-agent fee — the denominator is 10000 and the result is rounded half up to a whole basis point (for the margin) or a whole-cent fee amount (for the remittance fee, which is rounded once on the file, never per line).

### 2.7. The Rate Stabilization Reserve

The Authority carries a cumulative ledger balance, `climate_reserve_balance_cents`, that functions as the program's rate-stabilization reserve. It starts at zero when the Authority is bootstrapped. It is **credited** by remittance overpayments — cash remitted by the utility beyond the total of open customer balances flows into the reserve rather than being rejected; unlike a debit, this credit does not refresh the Authority's `updated_at` or increment its `version`. It is **debited** by two kinds of events: early termination of a supply contract, whose termination fee is drawn from the reserve, and bad-debt true-up, which draws the CCA's capped share of written-off balances from the reserve.

Every reserve debit is **clamped**: the debit taken is the smaller of the computed amount and the current reserve balance, so the balance can never be driven below zero. The uncovered remainder of a clamped debit is expensed — recorded, where the workflow provides one, in a dedicated field — and is otherwise discarded from the reserve's perspective. A debit against the reserve is a mutation of the Authority itself: it refreshes the Authority's `updated_at` and increments its `version` by 1.

### 2.8. Optimistic Concurrency Control

Two write operations in this program read and mutate state that a client must have observed to act safely, and both are protected by optimistic concurrency control. All other endpoints do not take a version field.

First, issuing an enrollment notice wave requires the request to carry `expected_authority_version`, holding the Authority `version` the client last observed. Issuance sweeps account state under policy fields — the rate policy, the default-product requirement — that the observed Authority version governed; if another writer has advanced the Authority's version since the client last read it, the issue is rejected with `ERR_STALE_AUTHORITY_VERSION` (HTTP 412), and the client must re-read and re-issue. Separately, the Authority's own policy-update operation also carries `expected_authority_version` and enforces the same check with the same error. In both operations the stale-version comparison is evaluated only after every other precondition of the operation has passed — state-machine legality, posture, statutory windows, default-product and field-level checks included — immediately before the mutation is applied.

Second, reconciling a remittance file requires the request to carry `expected_extract_version`, holding the current `version` of the matching billing extract. The waterfall application distributes cash against the extract's line set, and a newer extract version means that line set changed since the reconciler last observed it; a mismatch is rejected with `ERR_STALE_EXTRACT_VERSION` (HTTP 412). Here too the comparison happens after the file's own state checks and after the matching extract has been located, immediately before the waterfall runs.

### 2.9. Validation Ordering

When a request fails multiple checks, the error surfaced is determined by a fixed priority order, evaluated from first to last:

1. **Authentication** — missing or malformed `X-User-Role` / `X-User-ID`, or an undeclared role value, yields `ERR_UNAUTHENTICATED`. This applies to every endpoint in the system, the clock endpoints included.
2. **Authorization** — an authenticated role outside the endpoint's role list yields `ERR_FORBIDDEN`.
3. **Path existence** — path-parameter resources are validated left to right (product before schedule, extract before line, notice before the accounts in its sweep); the first missing id yields `ERR_NOT_FOUND`.
4. **Body reference existence** — a body-carried foreign key that does not resolve (`service_account_id`, `product_id`, `compliance_filing_id`, `supply_contract_id`, `enrollment_notice_id`, `reversal_of_request_id`) yields `ERR_REFERENCED_NOT_FOUND`.
5. **State-machine legality** — if the target's state machine has no transition for this trigger from its current state, the request yields `ERR_INVALID_STATE`.
6. **Terminal lockdown** — triggers fired against a terminal-state resource (a `SETTLED` extract or remittance, a `TRUED_UP` pool, an `ACCEPTED_BY_CPUC` filing) yield `ERR_ALREADY_TERMINAL`, an audit-distinct code kept separate from `ERR_INVALID_STATE` so closed books are visibly closed.
7. **Authority posture** — operations that require a particular program posture (notice issuance requires the Authority `ACTIVE`; line posting requires the parent extract still in `DRAFT`) yield `ERR_AUTHORITY_POSTURE` when the posture is wrong.
8. **Default-product prerequisite** — operations that require an adopted default product with a covering adopted rate schedule (Authority activation, notice issuance, product election changes, billing line posting) yield `ERR_NO_DEFAULT_PRODUCT` when none exists.
9. **Statutory windows** — timing rules tied to the statutory calendar (opt-out deadlines, notice close and cancel windows, pool close timing) yield `ERR_STATUTE_WINDOW_VIOLATION`.
10. **Segregation of duties** — adjacent-step violations of a two-key chain yield `ERR_SEGREGATION_OF_DUTIES`.
11. **Uniqueness and overlap** — unique-field collisions and adopted rate-window overlap yield `ERR_UNIQUENESS_CONFLICT`.
12. **Cross-entity referential state** — a referenced resource in the wrong state for the operation (billing a non-enrolled account, an opt-out under a notice that does not govern the account, a REC retirement against a filing past its review stage, an election to a non-adopted product) yields `ERR_REFERENTIAL_STATE`.
13. **Zero-REC claims** — preparing an annual RPS filing with no retirements attached yields `ERR_ZERO_REC_CLAIM`.
14. **Fiscal gates** — the rate-adoption margin floor and the zero-balance requirement on account close yield `ERR_FISCAL_GATE`.
15. **Dissolution preconditions** — a blocked Authority dissolution yields `ERR_DISSOLUTION_BLOCKED`.
16. **Field-level validity** — bad enum values, non-positive quantities, malformed `YYYY-MM` strings, a delivery window whose end is not after its start, and missing required fields yield `ERR_INVALID_REQUEST`.

### 2.10. Nested Resource Retrieval

The API enforces strict, hierarchical, left-to-right validation for all requests that target nested resources. When an endpoint path contains multiple resource identifiers — a rate schedule under a product, a billing line under an extract, the accounts swept under a notice — the system validates the existence of each identifier in sequence, and the request is rejected immediately with `ERR_NOT_FOUND` at the *first* identifier that does not correspond to an existing resource, before any deeper identifier or any business rule is evaluated.

## 3. Business Logic & Workflows

### 3.1. Bootstrapping the Authority and Setting Program Policy

Everything in the program hangs off a single **Authority** record — the Joint Powers Authority itself. Exactly one instance exists per deployment, created once by a `BoardDirector` through the bootstrap operation; a second bootstrap attempt collides with the singleton and is rejected with `ERR_UNIQUENESS_CONFLICT`. Bootstrap captures the authority's legal `display_name`, the `utility_territory_code` identifying the incumbent IOU territory served (one of `PGE`, `SCE`, or `SDGE`, immutable after creation), the `er_balancing_authority` used for CAISO scheduling, and the board-adopted `rate_setting_policy` — one of `COST_PLUS`, `DISCOUNT_TO_INCUMBENT`, or `VALUE_BASED`. When the policy is `DISCOUNT_TO_INCUMBENT`, the `discount_floor_bps` field matters: it is the minimum basis-points discount any adopted default-product rate must carry against the incumbent generation rate, must lie between 0 and 2000 inclusive, and defaults to 0; under the other two policies the value is still range-validated and stored but is never consulted. The authority also takes an `rps_target_pct` — the Renewable Portfolio Standard target fraction the portfolio must meet per compliance period, strictly greater than 0 and at most 1.0 — and a `bad_debt_trueup_cap_pct`, the maximum fraction of billed generation revenue the CCA absorbs as incremental uncollectible share per true-up, between 0 and 0.05 inclusive and defaulting to 0.01. At creation the authority's `status` is `FORMING` and its `climate_reserve_balance_cents` starts at 0.

A `BoardDirector` may later update the policy fields — `rate_setting_policy`, `discount_floor_bps`, `rps_target_pct`, `bad_debt_trueup_cap_pct` — through a policy patch that carries `expected_authority_version` for optimistic concurrency as described in §2.8; each successful patch increments the Authority's `version` by 1. The policy patch is permitted in any Authority `status`.

The program's own lifecycle runs `FORMING → ACTIVE → DISSOLVED`, with a `SUSPENDED` detour off `ACTIVE`. Activation requires that at least one adopted product with `election_key` equal to `DEFAULT` exists, and that at least one adopted rate schedule for that default product covers the current logical-clock date; without them the activation is rejected with `ERR_NO_DEFAULT_PRODUCT`. Suspension is permitted only when no enrollment notice is currently in `ENROLLING` status — an attempt while one is `ENROLLING` is rejected with `ERR_INVALID_STATE` — and it is deliberately disruptive: every notice in `ISSUED` is cancelled, and every account those waves had swept to `NOTICED` reverts to `PROSPECT` with its `current_enrollment_notice_id` nulled. Reinstatement from `SUSPENDED` back to `ACTIVE` has no preconditions. Activation, suspension, and reinstatement each increment the Authority's `version` by 1.

Dissolution is the program's terminal act and its strictest gate. A `BoardDirector` may dissolve an `ACTIVE` authority only when three conditions all hold: no service account exists in `ENROLLED` state; every compliance filing whose `compliance_year` is the current logical-calendar year or one of the three years preceding it sits in `ACCEPTED_BY_CPUC` or `WITHDRAWN`; and every bad-debt pool has reached `TRUED_UP`. Failure of any leg is rejected with `ERR_DISSOLUTION_BLOCKED`. Successful dissolution increments the Authority's `version` by 1 and lands it in `DISSOLVED`, terminal.

### 3.2. Notice Waves and the Opt-Out Enrollment Cycle

Customer enrollment in a CCA is statutory and inverted: eligible customers are enrolled by default unless they opt out, and the mechanism is the **EnrollmentNotice** — a wave of mailed notices with a cooling-off window and a scheduled enrollment date. A `ProgramOperator` creates a wave in `DRAFT` by supplying a human `wave_label` (for example, `2026-PHASE-2-RESIDENTIAL`), the `notice_mailed_on` date on which notices were mailed, and the `target_service_classes` array listing which service classes the wave covers. Two statutory dates are computed from the mailing date by exact timestamp arithmetic: `opt_out_deadline` is `notice_mailed_on` plus 30 days — the instant at and after which opt-out elections for this wave are rejected — and `enrollment_effective_on` is `opt_out_deadline` plus a further 30 days, the instant at which noticed accounts flip into enrollment.

Issuing a wave is the moment the statutory machine bites. A `ProgramOperator` may move a wave from `DRAFT` to `ISSUED` only when all of the following hold: the Authority is `ACTIVE`; `notice_mailed_on` is not earlier than the current logical instant (the two are compared as exact timestamps, not calendar dates); at least one adopted default product exists with an adopted rate schedule covering `enrollment_effective_on` (otherwise `ERR_NO_DEFAULT_PRODUCT`); and `target_service_classes` is non-empty. Because issuance sweeps account state under policy the client observed, the request must carry `expected_authority_version` per §2.8; a stale read is rejected with `ERR_STALE_AUTHORITY_VERSION`. On a successful issue, the system sweeps every service account that is still a `PROSPECT`, is not direct-access eligible, and whose `service_class` is in the wave's target set, transitioning each to `NOTICED` and stamping its `current_enrollment_notice_id` with this notice. The wave's `account_count_noticed` is set to the sweep count, and issuance increments the Authority's `version` by 1. An account-by-account read of the election trail is available through the reverse-reachability listing of opt-out requests under a notice.

Once the logical clock reaches the `opt_out_deadline`, the `ProgramOperator` closes the wave, moving it `ISSUED → CLOSED`. Closing before the deadline is a statutory violation and is rejected with `ERR_STATUTE_WINDOW_VIOLATION`. At close, the wave's `account_count_opted_out` is recomputed as the number of opt-out requests filed under this notice with `election_type` equal to `OPT_OUT` that have not been rescinded by a later reversal request.

The enrollment itself is not an API call — it is fired by the epoch-advance ops run (§2.4) once the logical clock reaches `enrollment_effective_on`. At that instant the wave moves `CLOSED → ENROLLING`, and every account still `NOTICED` under it that has no unreversed `OPT_OUT` request filed under the wave flips to `ENROLLED`, takes `product_election` equal to `DEFAULT`, and has its `vintage_year` stamped with the calendar year of `enrollment_effective_on`. The wave's `account_count_enrolled` records the flip count. Immediately after the sweep completes, within the same ops-run checkpoint, the wave settles into `SETTLED`, terminal. Each flipped account's enrollment transition bubbles up to refresh the Authority's `updated_at`, though this cascade link deliberately does not increment the Authority's `version` — only direct authority mutations and the cascades that explicitly say so do that.

A wave can also be abandoned. Cancellation from `ISSUED` requires the logical clock to still be before the `opt_out_deadline`; cancellation from `CLOSED` requires the clock to still be before `enrollment_effective_on`. Either way the wave lands in `CANCELLED`, terminal, and all remaining `NOTICED` accounts under it revert to `PROSPECT` with their `current_enrollment_notice_id` nulled. Cancelling outside the permitted window is `ERR_STATUTE_WINDOW_VIOLATION`.

### 3.3. Service Accounts: Ingest, Elections, and the Opt-Out Audit Trail

A **ServiceAccount** is a utility-metered customer premises eligible for CCA service. Accounts are created in bulk by a `ProgramOperator` through the enrollment-phase ingest, which accepts an `accounts` array and returns `ingested_count` plus the minted `account_ids`. Each ingested record carries the incumbent utility's `utility_account_number` (unique within the authority and immutable — a duplicate anywhere in the batch aborts the whole ingest atomically, all-or-nothing, with `ERR_UNIQUENESS_CONFLICT`), a `service_class` drawn from `RESIDENTIAL`, `SMALL_COMMERCIAL`, `LARGE_COMMERCIAL`, `INDUSTRIAL`, `AGRICULTURAL`, or `STREETLIGHT`, a forecast `annual_kwh_estimate` (an integer, at least zero) and `annual_peak_kw` (a number, at least zero), and a `da_eligible` flag. Direct-access-eligible accounts are deliberately excluded from opt-out enrollment waves — the sweep in §3.2 skips any account whose `da_eligible` is true. Every ingested account begins life as a `PROSPECT`, with `product_election` at `DEFAULT`, its cumulative billed and remitted ledgers at zero, and `uncollectible_flag` false.

The account carries two parallel state dimensions on one row. The enrollment dimension — `enrollment_state` — runs `PROSPECT → NOTICED → ENROLLED → CLOSED`, with `OPTED_OUT` and `OPTED_BACK_TO_BUNDLED` as exits. The product dimension — `product_election` — takes values `DEFAULT`, `OPT_UP_100`, or `OPT_DOWN_ECONOMY` and is mutable only while the account is `ENROLLED`.

Opt-outs and returns to bundled service are recorded as **OptOutRequest** rows — an append-only, immutable audit trail for enrollment disputes. A `CustomerService` operator records an election by supplying the `service_account_id`, the `enrollment_notice_id` under whose window the election is made, an `election_type` of `OPT_OUT` or `OPT_BACK_TO_BUNDLED`, the `channel` (`WEB`, `PHONE`, or `MAIL`), and optionally a `reversal_of_request_id`. The server stamps `received_at` from the logical clock. For a `NOTICED` account, an `OPT_OUT` election requires that the clock still be before the governing notice's `opt_out_deadline` and that the payload's `enrollment_notice_id` equal the account's `current_enrollment_notice_id` — an election filed under the wrong wave is `ERR_REFERENTIAL_STATE`, and one filed after the deadline is `ERR_STATUTE_WINDOW_VIOLATION`. A successful opt-out moves the account to `OPTED_OUT`; its `current_enrollment_notice_id` stays set for audit, but the account is excluded from the enrolling sweep. A rescission — a new request whose `reversal_of_request_id` references an earlier `OPT_OUT` request belonging to the same account, made while the clock is still before the deadline — leaves the account `NOTICED` and re-admits it to the sweep, marking the earlier request reversed through the new row. A request carrying a resolvable `reversal_of_request_id` is treated as a rescission regardless of its `election_type`; it requires the account to currently be `OPTED_OUT` (otherwise `ERR_INVALID_STATE`) and the payload's `enrollment_notice_id` to equal the account's `current_enrollment_notice_id` (otherwise `ERR_REFERENTIAL_STATE`). For an already-`ENROLLED` account, an `OPT_BACK_TO_BUNDLED` election moves it to `OPTED_BACK_TO_BUNDLED`, which cascades in two hops: first, the account becomes ineligible for any future billing line posting, so line creation against it is rejected; second, the next actual-trued load forecast snapshot excludes the account entirely, which itself shifts that snapshot's coverage position.

While `ENROLLED`, a customer may change products through a `CustomerService`-driven election change carrying the target `product_election`. The change requires the account to be `ENROLLED`; requires that a product exist in `ADOPTED` status whose `election_key` equals the requested value; and requires an adopted rate schedule for that product covering the current logical-clock date — a missing default-side prerequisite surfaces as `ERR_NO_DEFAULT_PRODUCT`, a non-adopted or uncovered target as `ERR_REFERENTIAL_STATE`. The change applies to future billing lines only — history is never rewritten, because each posted line snapshots `product_election_at_billing` — and it increments the account's `version` by 1.

Closing an account — from either `ENROLLED` or `OPTED_BACK_TO_BUNDLED` — is a fiscal act: it requires the open balance, `cumulative_billed_cents` minus `cumulative_remitted_cents`, to be exactly zero. A nonzero balance is rejected with `ERR_FISCAL_GATE`. Closure lands the account in `CLOSED`, terminal. Separately, a `FinanceController` may write an account off: the write-off operation sets `uncollectible_flag` true — a one-way flag that is never reset — and records the calendar quarter containing the current logical date as the write-off's pool period; the operation succeeds whether or not an `ACCRUING` pool for that quarter exists, and a repeated write-off of an already-flagged account is a no-op that returns the account unchanged.

### 3.4. Products, Rate Schedules, and Board Rate Setting

A **Product** is a retail generation rate schedule offered by the authority — a default 50%-renewable product, an opt-up 100%-renewable product, an economy product, and so on. A `RateAnalyst` creates a product in `DRAFT` with a stable `product_code` (unique per authority), an `election_key` mapping the product to one of the three account election values (also unique per authority), and a `renewable_pct` between 0 and 1.0 inclusive. The `is_default` flag is system-managed: exactly one adopted product with `election_key` equal to `DEFAULT` must exist per authority before any notice wave may be issued.

Product adoption is a board act. A `BoardDirector` moves a product `DRAFT → ADOPTED` only when at least one adopted rate schedule exists for it (otherwise `ERR_REFERENTIAL_STATE`) and, for a default product, no other adopted default product already exists for the authority (otherwise `ERR_UNIQUENESS_CONFLICT`); adoption sets `is_default` true when the `election_key` is `DEFAULT`. Retirement moves a product `ADOPTED → RETIRED`, requires that no `ENROLLED` account currently takes that product's election (otherwise `ERR_REFERENTIAL_STATE`), and — if the product is the default — requires that another adopted default product already exist (otherwise `ERR_NO_DEFAULT_PRODUCT`); retirement clears `is_default` to false. Retired products keep their historical reads.

Each product's prices live in versioned **RateSchedule** rows — board-adopted tariff sheets for a calendar window. A `RateAnalyst` creates a schedule in `DRAFT` under a product by supplying the `product_id`, an inclusive `period_start`, an exclusive `period_end`, and three rates: `energy_rate_cents_per_kwh` (strictly positive), `pcia_rate_cents_per_kwh` (the Power Charge Indifference Adjustment exit-fee passthrough collected on behalf of the incumbent, at least zero), and `incumbent_benchmark_rate_cents_per_kwh` (the incumbent's published generation rate used as the comparison baseline, strictly positive). Every schedule carries a computed `comparison_margin_bps`: ten thousand times the difference between the incumbent benchmark and the energy rate, divided by the incumbent benchmark, rounded half up to a whole basis point. A positive margin means the CCA is cheaper than the incumbent. A draft schedule may be updated — window or rates, as a partial patch whose supplied fields merge onto the current values before validation — which recomputes the margin from the updated inputs; updates are only possible while the schedule remains in `DRAFT`.

The schedule lifecycle runs `DRAFT → PROPOSED → ADOPTED`, with a `REJECTED` branch off `PROPOSED` and a terminal `SUPERSEDED` state reached only by cascade. Proposing requires the window to be well-formed (`period_end` strictly after `period_start`) and the parent product to be `DRAFT` or `ADOPTED`; it stamps `proposed_by` with the proposing `RateAnalyst`'s id and computes the comparison margin. Adoption and rejection are both board acts with segregation of duties: the acting `BoardDirector`'s id must differ from `proposed_by`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Adoption carries two further gates. Under a `DISCOUNT_TO_INCUMBENT` rate policy, the schedule's `comparison_margin_bps` must be at least the authority's `discount_floor_bps`, or adoption is rejected with `ERR_FISCAL_GATE`; under the other policies no floor applies. And no other adopted schedule for the same product may have an overlapping half-open window — with one exception: an adopted schedule whose window is fully contained inside the new one is not a conflict, since the cascade below supersedes it; any other overlap is `ERR_UNIQUENESS_CONFLICT`, while adjacency, where one schedule's `period_end` equals another's `period_start`, is allowed. Successful adoption stamps `adopted_by` and cascades in two hops: any previously adopted schedule for the same product whose window is fully contained inside the new window transitions to `SUPERSEDED`, and that supersession refreshes the parent product's `updated_at` and re-evaluates whether the product still has any adopted schedule — the same condition the product-adoption and authority-activation preconditions consult. Rejection has no cascade; the schedule is simply terminal.

### 3.5. The Supply Portfolio and Load Forecasting

The authority buys power through **SupplyContract** records. A `PortfolioManager` creates a contract in `NEGOTIATING` with a `counterparty` name, a `contract_type` of `ENERGY_BLOCK` (energy only), `RA_CAPACITY` (resource-adequacy capacity), `REC_ONLY` (unbundled renewable credits), or `PPA` (bundled energy plus RECs); an inclusive `delivery_start` and exclusive `delivery_end`; a `capacity_mw` strictly positive; a `total_mwh` at least zero (zero is the norm for pure `RA_CAPACITY` contracts); a `price_dollars_per_mwh` at least zero; an `rps_eligible_pct` between 0 and 1.0 inclusive giving the fraction of delivered energy carrying RPS-eligible attributes; and an integer `vintage_year` capturing the PCIA-relevant commitment vintage — contracts committed in or before an account's vintage year raise that vintage's exit fee.

Execution moves a contract `NEGOTIATING → EXECUTED`. It requires a well-formed delivery window, and type-specific substance: a `REC_ONLY` or `PPA` contract must carry a positive `rps_eligible_pct`; an `RA_CAPACITY` contract must carry positive `capacity_mw`; every other type must carry positive `total_mwh`. Once executed, a contract becomes visible to the coverage computation on the next forecast snapshot. From there the calendar takes over: the epoch-advance ops run moves an executed contract `EXECUTED → DELIVERING` once the logical clock reaches `delivery_start`, and `DELIVERING → CLOSED` once it reaches `delivery_end`; both transitions are evaluated within a single run, so a contract whose entire window has already passed moves `EXECUTED → DELIVERING → CLOSED` in one checkpoint.

A contract can also be terminated early, from either `EXECUTED` or `DELIVERING`, by a `PortfolioManager`. Termination computes a `termination_fee_cents` with a pinned evaluation order. First, the remaining fraction of the delivery window is found: the number of whole days from the logical clock to `delivery_end` (never below zero) divided by the total window length in whole days. Second, that fraction is applied to `total_mwh` to get the undelivered energy. Third, the fee in dollars is that remaining energy times the contract price times a fixed termination charge of twenty percent, and `termination_fee_cents` is that dollar figure converted to cents and rounded half up — the only rounding in the computation. Then the cascade: the Authority's `climate_reserve_balance_cents` is debited by the smaller of the fee and the current balance, per the clamping rule in §2.7, with any uncovered remainder expensed and discarded; and that reserve debit refreshes the Authority's `updated_at` and increments its `version` by 1. The fee computation is identical whether the contract was merely executed or already delivering — the remaining-window fraction shrinks as delivery proceeds.

Sizing the portfolio is the job of the **LoadForecast**, an append-only snapshot of the load used for procurement planning. A `PortfolioManager` creates a snapshot by supplying a `snapshot_label` (such as `PLAN-2027` or `TRUEUP-2026-Q2`), a `forecast_variant`, and the integer `period_year` being forecast; the server stamps `as_of` from the logical clock and computes the snapshot. The in-scope account set is every account whose `enrollment_state` is `NOTICED` or `ENROLLED`. The snapshot's `total_energy_mwh` is the sum of the in-scope accounts' effective annual energy, converted from kWh to MWh at a thousand kWh per MWh and rounded to 0.001. Its `coincident_peak_mw` is the sum of the accounts' `annual_peak_kw`, converted kW to MW and likewise rounded to 0.001. The `ra_requirement_mw` is the coincident peak grossed up by a fifteen-percent planning reserve margin and rounded up to the nearest 0.1 MW. And `coverage_gap_mwh` — negative meaning short — is the total energy rounded to whole MWh, minus the sum of `total_mwh` over every `EXECUTED` or `DELIVERING` contract whose delivery window overlaps any part of the forecast year.

The two forecast variants diverge on exactly one question: what counts as an account's effective annual energy. Under `ADOPTED_PLAN`, every in-scope account contributes its `annual_kwh_estimate` verbatim. Under `ACTUAL_TRUED`, an account that has at least one billing line in a settled extract instead contributes its trailing actuals — the sum of `usage_kwh` over its settled lines, annualized by multiplying by twelve and dividing by the count of distinct billed months — while accounts without settled billing history fall back to the estimate. Identical accounts can therefore produce divergent totals and coverage gaps across the two variants, which is the point: the adopted-plan variant measures the filed program, the actual-trued variant measures the lived one. The `ERRA_FORECAST` and `PSD` filing types carry no server-computed projection: preparing either simply stamps `prepared_by` and advances the filing, and the attainment computation described in §3.9 runs only for `RPS_ANNUAL`.

### 3.6. Monthly Billing: Extracts and Lines

The CCA does not bill customers directly; it hands a monthly generation-charge file to the incumbent utility, which bills on the CCA's behalf. That file is the **BillingExtract**. A `BillingCoordinator` creates an extract in `DRAFT` for a `billing_month` given in `YYYY-MM` form; no uniqueness is enforced on `billing_month`, so several extracts for the same month may coexist. Lines are posted into the draft one account at a time: each **BillingLine** carries the `service_account_id` and the metered `usage_kwh` for the month (an integer, strictly positive), and its charges are computed at posting time. The `generation_charge_cents` is the usage multiplied by the adopted `energy_rate_cents_per_kwh` for the product matching the account's current `product_election`, where the schedule's window covers the first day of the service month, rounded half up to whole cents. The `pcia_charge_cents` is the usage multiplied by the `pcia_rate_cents_per_kwh` on that same adopted schedule — the one covering the first day of the service month for the account's elected product; the account's `vintage_year` is not consulted at posting time — likewise rounded half up per line. Rounding order is pinned per §2.6: each line rounds independently, and the extract's totals sum the already-rounded lines. Posting a line requires the parent extract to be in `DRAFT` and the account to be `ENROLLED` for the billed month — a line against a non-enrolled account is `ERR_REFERENTIAL_STATE`, and the adopted-schedule prerequisites surface as `ERR_NO_DEFAULT_PRODUCT` or `ERR_REFERENTIAL_STATE` as applicable. Each line's `billing_extract_id` is set by the system from the nested path of the posting operation rather than from the payload. Each line snapshots `product_election_at_billing` so that later election changes never rewrite history, and each posting refreshes the extract's `line_count`, `total_billed_cents`, and `total_pcia_collected_cents` — the PCIA total being money owed to the incumbent, not CCA revenue. Lines are also reachable in aggregate through a filtered listing that accepts `service_account_id` or `billing_extract_id` as filters, giving reverse reachability from an account to its billing history.

Submission moves the extract `DRAFT → SUBMITTED`, requires at least one line and an `ACTIVE` authority, and stamps `submitted_on` from the logical clock. From there the `UtilityLiaison` speaks for the utility side: acceptance moves the extract `SUBMITTED → ACCEPTED` and cascades every child line's `generation_charge_cents` onto its account's `cumulative_billed_cents`, refreshing each affected account's `updated_at` and incrementing each account's `version`; rejection moves it `SUBMITTED → REJECTED_BY_UTILITY` with no cascade. A rejected extract is not dead — a `BillingCoordinator` reopens it, returning it to `DRAFT` so lines can be added or removed again. The extract's final move, `ACCEPTED → SETTLED`, is not a direct call: it fires when a remittance file for the same month settles, as the next subsection describes.

### 3.7. Remittance: the Cash Waterfall and Settlement

After collecting on the CCA's behalf, the incumbent utility sends cash back as a **RemittanceFile**. A `BillingCoordinator` registers an incoming file — initial status `RECEIVED` — by supplying the `remittance_period` in `YYYY-MM` form (which must match an accepted extract's billing month before the file can reconcile; no uniqueness is enforced, so multiple files for the same period may be registered), the integer `gross_remittance_cents` remitted (at least zero), and the integer `utility_fee_bps` billing-agent fee, which must lie between 0 and 300 basis points inclusive. The file's `net_remittance_cents` is the gross minus the fee, where the fee is the gross times the basis points over ten thousand, rounded half up once on the file — never per line.

Reconciliation is where cash meets ledgers, and it is OCC-protected: the request must carry `expected_extract_version` matching the current version of the accepted extract whose `billing_month` equals the `remittance_period`, or it is rejected with `ERR_STALE_EXTRACT_VERSION` per §2.8. Reconciliation requires that an accepted — or already settled — extract exist for the period; when several extracts share the period, the earliest-created `ACCEPTED` extract matches, and only when none is `ACCEPTED` does the earliest-created `SETTLED` extract match. It then applies the net cash as a waterfall: eligible accounts are those with billing lines in the matching month's extract and a positive open balance (billed minus remitted), among both `ENROLLED` and `OPTED_BACK_TO_BUNDLED` accounts; they are filled in order of account `created_at` ascending — a tie is impossible at one-millisecond resolution, but if one ever occurred the fallback is `updated_at` ascending, never `id` — each credit incrementing the account's `cumulative_remitted_cents`. Any remainder after every eligible balance is zeroed is not rejected; it is credited to the Authority's `climate_reserve_balance_cents` as the overpayment reserve credit described in §2.7, which is why the same file can produce different reserve balances depending on account balance state. The file's `applied_cents` is set to the full `net_remittance_cents`, and reconciliation increments the matching extract's `version` by 1.

Two reversals live off the reconciled state. A `UtilityLiaison` may dispute the file, moving it `RECONCILED → DISPUTED`, and the dispute compensates: every remittance credit applied at reconciliation is reversed from the affected accounts, and `applied_cents` returns to 0; any overpayment previously credited to the rate-stabilization reserve is not reversed. A `BillingCoordinator` may then reopen a disputed file, returning it `DISPUTED → RECEIVED` with no further effects, free to be reconciled afresh.

Settlement is the fiscal close of the loop and belongs to a `FinanceController` — with segregation of duties against whoever reconciled the file: the acting id must differ from the reconciler's id recorded on the file, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Settlement also requires `applied_cents` to equal `net_remittance_cents` (otherwise `ERR_INVALID_STATE`). Its cascade has two hops: the matching billing extract — the earliest-created `ACCEPTED` extract for the period — transitions `ACCEPTED → SETTLED`, and that extract settlement attributes its `total_billed_cents` to the quarter containing the billing month, incrementing the `billed_generation_cents` of the `ACCRUING` pool for that quarter if one exists (if no pool is accruing for the quarter, the attribution is skipped). Both file and extract end in `SETTLED`, terminal.

### 3.8. Bad Debt: Write-Offs, Pool Close, and the True-Up Split

Uncollectible balances are handled in quarterly **BadDebtPool** records, which run `ACCRUING → CLOSED → TRUED_UP`. A `FinanceController` opens a pool by supplying a `pool_period` quarter label such as `2026-Q3`, unique per authority. While a pool is accruing, individual account write-offs (§3.3) attach to it by date attribution.

Closing the pool is permitted once the logical clock reaches the first instant of the quarter following the pool period — an early close is `ERR_STATUTE_WINDOW_VIOLATION`. At close, the pool sweeps every account whose `uncollectible_flag` is set and whose write-off was recorded inside the pool period, summing each account's open balance into `written_off_cents`. The pool's `billed_generation_cents` is the total billed generation revenue across every `SETTLED` extract whose billing month falls inside the pool period — the denominator for the statutory cap. The sharing split is then computed: the CCA's share, `cca_share_cents`, is the smaller of the written-off total and the cap, where the cap is `billed_generation_cents` times the authority's `bad_debt_trueup_cap_pct` rounded half up to whole cents. The boundary is inclusive of the cap — when the written-off total equals the cap exactly, the CCA absorbs all of it. The utility's share, `utility_share_cents`, is whatever remains of the written-off total after the CCA share.

True-up turns the split into cash movement and belongs to a `FinanceController` who is not the operator who closed the pool — the closer's id is recorded on the pool, and a same-id true-up is rejected with `ERR_SEGREGATION_OF_DUTIES`. The cascade has three hops: the Authority's `climate_reserve_balance_cents` is debited by `reserve_draw_cents`, which equals the CCA share clamped to the reserve balance per §2.7; that debit increments the Authority's `version` by 1 and refreshes its `updated_at`; and `expensed_cents` is recorded as the CCA share minus the reserve draw — the portion of the share the reserve could not cover. The pool then sits in `TRUED_UP`, terminal.

### 3.9. Regulatory Compliance: Filings and REC Retirements

The program answers to the CPUC through **ComplianceFiling** records. Three filing types exist: `RPS_ANNUAL`, the renewable-content claim and report; `ERRA_FORECAST`, the exit-fee forecast filing; and `PSD`, the Power Source Disclosure label filing. A `ComplianceOfficer` creates a filing in `DRAFT` with its `filing_type` and the integer `compliance_year` it covers.

The filing lifecycle is a two-key approval chain with a cyclic revision loop: `DRAFT → PREPARED → REVIEWED → FILED → ACCEPTED_BY_CPUC`, with `REJECTED_BY_CPUC` looping back to `DRAFT` and `WITHDRAWN` as a terminal exit off `DRAFT`. Preparation is a `ComplianceOfficer` act that stamps `prepared_by`. For an `RPS_ANNUAL` filing, preparation is gated on substance: at least one REC retirement must already reference the filing, or the prepare is rejected with `ERR_ZERO_REC_CLAIM` — zero-REC claims are not preparable. Preparation also computes the filing's renewable attainment: `rps_actual_pct` and `rps_shortfall_mwh`. Review is a second `ComplianceOfficer` act, segregated from the first — the reviewer's id must differ from `prepared_by`, or `ERR_SEGREGATION_OF_DUTIES` — and stamps `reviewed_by`. Filing to the CPUC is a `BoardDirector` act; acceptance and rejection come back through the `UtilityLiaison`. A rejection is not the end: revising a rejected filing returns it to `DRAFT`, increments its `revision_count` by 1, and clears both `prepared_by` and `reviewed_by` so the new cycle requires a fresh two-key chain; any previously computed `rps_actual_pct` and `rps_shortfall_mwh` are retained until a subsequent prepare recomputes them. Withdrawal from `DRAFT` is unconditional and terminal.

The attainment computation behind an `RPS_ANNUAL` filing runs at prepare time. Total retired energy is the sum of `retired_mwh` over the filing's retirements. Retail energy served is the sum of `usage_kwh` over every billing line whose parent extract is `SETTLED` and whose billing month falls inside the compliance year, converted kWh to MWh. The RPS-eligible energy is the smaller of the retired total and the attribute-weighted sum across the referenced contracts — each retirement's `retired_mwh` multiplied by its contract's `rps_eligible_pct`. The `rps_actual_pct` is the eligible energy divided by retail energy, rounded half up to four decimal places, and is 0 when retail energy is 0. The `rps_shortfall_mwh` is the amount by which the target — the authority's `rps_target_pct` times retail energy — exceeds the eligible energy, never below zero, rounded up to whole MWh.

A **RECRetirement** is an immutable, WREGIS-style retirement of renewable credits against a compliance year's claim. A `ComplianceOfficer` records one by supplying the `compliance_filing_id` of the RPS filing it supports, the `supply_contract_id` the attributes come from (a `PPA` or `REC_ONLY` contract), the `retired_mwh` (a number, strictly positive), and the external registry's `retirement_serial`, unique per authority; the server stamps `retired_on` from the logical clock. Retirements attach early, before the two-key chain completes: the referenced filing must be in `DRAFT`, `PREPARED`, or `REVIEWED` — once a filing is `FILED` or beyond, its retirement set is locked, and an attempt to attach is `ERR_REFERENTIAL_STATE`. Retirements are reachable in reverse from both sides — all retirements supporting a filing, and all retirements drawn from a contract.

## 4. Endpoint Definitions

Operations that create new resources — the Authority singleton, accounts, notices, opt-out requests, products, rate schedules, supply contracts, load forecasts, billing extracts, billing lines, remittance files, bad-debt pools, compliance filings, and REC retirements — return `201 Created`. Operations that modify an existing resource, including every state-transition action and the policy patch, return `200 OK`. The Authority read returns an array of length 1, or of length 0 before bootstrap.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cca/authority` | Bootstrap: create the singleton Authority | BoardDirector |
| GET | `/cca/authority` | Read the singleton authority (array of length 1) | BoardDirector, RateAnalyst, ProgramOperator, PortfolioManager, BillingCoordinator, FinanceController, ComplianceOfficer, UtilityLiaison, CustomerService |
| PATCH | `/cca/authority` | Update policy fields; carries OCC `expected_authority_version` | BoardDirector |
| POST | `/cca/authority/activate` | `FORMING` → `ACTIVE`; requires adopted default product and covering schedule | BoardDirector |
| POST | `/cca/authority/suspend` | `ACTIVE` → `SUSPENDED`; cancels issued waves and reverts their noticed accounts | BoardDirector |
| POST | `/cca/authority/reinstate` | `SUSPENDED` → `ACTIVE` | BoardDirector |
| POST | `/cca/authority/dissolve` | `ACTIVE` → `DISSOLVED` under strict preconditions | BoardDirector |
| POST | `/cca/_clock/set_current_utc` | Set the logical clock (test-driving; startup default 2026-05-01T00:00:00Z) | BoardDirector |
| POST | `/cca/_clock/advance_epoch` | Run the epoch-advance ops checkpoint at the current logical time | BoardDirector |
| POST | `/cca/service-accounts/ingest` | Bulk ingest of eligible accounts; duplicate account numbers abort atomically | ProgramOperator |
| GET | `/cca/service-accounts` | List accounts with filters | ProgramOperator, CustomerService, BillingCoordinator, FinanceController, PortfolioManager |
| GET | `/cca/service-accounts/{id}` | Read one account | ProgramOperator, CustomerService, BillingCoordinator, FinanceController |
| POST | `/cca/service-accounts/{id}/product-election` | Change product election while enrolled | CustomerService |
| POST | `/cca/service-accounts/{id}/close` | Close account; requires zero open balance | CustomerService |
| POST | `/cca/service-accounts/{id}/write-off` | Flag account uncollectible into the accruing pool | FinanceController |
| POST | `/cca/enrollment-notices` | Create a notice wave in `DRAFT` | ProgramOperator |
| GET | `/cca/enrollment-notices` | List notices | ProgramOperator, CustomerService, ComplianceOfficer |
| GET | `/cca/enrollment-notices/{id}` | Read one notice | ProgramOperator, CustomerService, ComplianceOfficer |
| POST | `/cca/enrollment-notices/{id}/issue` | `DRAFT` → `ISSUED`; sweeps eligible prospects; OCC on Authority version | ProgramOperator |
| POST | `/cca/enrollment-notices/{id}/close` | `ISSUED` → `CLOSED` once the opt-out deadline has passed | ProgramOperator |
| POST | `/cca/enrollment-notices/{id}/cancel` | `ISSUED`/`CLOSED` → `CANCELLED` before enrollment effective; reverts accounts | ProgramOperator |
| GET | `/cca/enrollment-notices/{id}/opt-out-requests` | List opt-out requests under this notice | ProgramOperator, CustomerService |
| POST | `/cca/opt-out-requests` | Record an opt-out, return-to-bundled, or rescission | CustomerService |
| GET | `/cca/opt-out-requests` | Filtered list of opt-out requests | CustomerService, ProgramOperator |
| GET | `/cca/opt-out-requests/{id}` | Read one opt-out request | CustomerService, ProgramOperator |
| POST | `/cca/products` | Create a product in `DRAFT` | RateAnalyst |
| GET | `/cca/products` | List products | RateAnalyst, BoardDirector, CustomerService, ProgramOperator |
| GET | `/cca/products/{id}` | Read one product | RateAnalyst, BoardDirector, CustomerService |
| POST | `/cca/products/{id}/adopt` | `DRAFT` → `ADOPTED` | BoardDirector |
| POST | `/cca/products/{id}/retire` | `ADOPTED` → `RETIRED` | BoardDirector |
| GET | `/cca/products/{id}/rate-schedules` | List schedules of a product | RateAnalyst, BoardDirector, CustomerService |
| POST | `/cca/rate-schedules` | Create a schedule in `DRAFT` under a product | RateAnalyst |
| GET | `/cca/rate-schedules` | Filtered list of schedules | RateAnalyst, BoardDirector, CustomerService |
| GET | `/cca/rate-schedules/{id}` | Read one schedule | RateAnalyst, BoardDirector, CustomerService |
| PUT | `/cca/rate-schedules/{id}` | Update a `DRAFT` schedule; recomputes the comparison margin | RateAnalyst |
| POST | `/cca/rate-schedules/{id}/propose` | `DRAFT` → `PROPOSED` | RateAnalyst |
| POST | `/cca/rate-schedules/{id}/adopt` | `PROPOSED` → `ADOPTED`; segregation of duties; margin floor; supersedes contained schedules | BoardDirector |
| POST | `/cca/rate-schedules/{id}/reject` | `PROPOSED` → `REJECTED`; segregation of duties | BoardDirector |
| POST | `/cca/supply-contracts` | Create a contract in `NEGOTIATING` | PortfolioManager |
| GET | `/cca/supply-contracts` | List contracts | PortfolioManager, FinanceController, ComplianceOfficer |
| GET | `/cca/supply-contracts/{id}` | Read one contract | PortfolioManager, FinanceController, ComplianceOfficer |
| POST | `/cca/supply-contracts/{id}/execute` | `NEGOTIATING` → `EXECUTED` | PortfolioManager |
| POST | `/cca/supply-contracts/{id}/terminate` | `EXECUTED`/`DELIVERING` → `TERMINATED`; fee computed; reserve debited | PortfolioManager |
| GET | `/cca/supply-contracts/{id}/rec-retirements` | List retirements referencing this contract | ComplianceOfficer, PortfolioManager |
| POST | `/cca/load-forecasts` | Compute and persist a forecast snapshot (`ADOPTED_PLAN` or `ACTUAL_TRUED`) | PortfolioManager |
| GET | `/cca/load-forecasts` | List snapshots | PortfolioManager, RateAnalyst, FinanceController |
| GET | `/cca/load-forecasts/{id}` | Read one snapshot | PortfolioManager, RateAnalyst, FinanceController |
| POST | `/cca/billing-extracts` | Create a `DRAFT` extract for a billing month | BillingCoordinator |
| GET | `/cca/billing-extracts` | List extracts | BillingCoordinator, FinanceController, UtilityLiaison |
| GET | `/cca/billing-extracts/{id}` | Read one extract | BillingCoordinator, FinanceController, UtilityLiaison |
| POST | `/cca/billing-extracts/{id}/lines` | Post a billing line into a `DRAFT` extract; computes charges | BillingCoordinator |
| GET | `/cca/billing-extracts/{id}/lines` | List lines of an extract | BillingCoordinator, FinanceController, UtilityLiaison |
| GET | `/cca/billing-lines` | Filtered list of billing lines | BillingCoordinator, FinanceController, CustomerService |
| GET | `/cca/billing-lines/{id}` | Read one billing line | BillingCoordinator, FinanceController, CustomerService |
| POST | `/cca/billing-extracts/{id}/submit` | `DRAFT` → `SUBMITTED` | BillingCoordinator |
| POST | `/cca/billing-extracts/{id}/utility-accept` | `SUBMITTED` → `ACCEPTED`; cascades billed cents onto account ledgers | UtilityLiaison |
| POST | `/cca/billing-extracts/{id}/utility-reject` | `SUBMITTED` → `REJECTED_BY_UTILITY` | UtilityLiaison |
| POST | `/cca/billing-extracts/{id}/reopen` | `REJECTED_BY_UTILITY` → `DRAFT` | BillingCoordinator |
| POST | `/cca/remittance-files` | Register an incoming utility remittance (`RECEIVED`) | BillingCoordinator |
| GET | `/cca/remittance-files` | List remittance files | BillingCoordinator, FinanceController, UtilityLiaison |
| GET | `/cca/remittance-files/{id}` | Read one remittance file | BillingCoordinator, FinanceController, UtilityLiaison |
| POST | `/cca/remittance-files/{id}/reconcile` | `RECEIVED` → `RECONCILED`; waterfall-applies cash; OCC on the extract version | BillingCoordinator |
| POST | `/cca/remittance-files/{id}/dispute` | `RECONCILED` → `DISPUTED`; reverses applied credits | UtilityLiaison |
| POST | `/cca/remittance-files/{id}/reopen` | `DISPUTED` → `RECEIVED` | BillingCoordinator |
| POST | `/cca/remittance-files/{id}/settle` | `RECONCILED` → `SETTLED`; segregation of duties; cascades extract settlement and pool attribution | FinanceController |
| POST | `/cca/bad-debt-pools` | Open an `ACCRUING` pool for a quarter | FinanceController |
| GET | `/cca/bad-debt-pools` | List pools | FinanceController, UtilityLiaison, BoardDirector |
| GET | `/cca/bad-debt-pools/{id}` | Read one pool | FinanceController, UtilityLiaison, BoardDirector |
| POST | `/cca/bad-debt-pools/{id}/close` | `ACCRUING` → `CLOSED`; computes the sharing split | FinanceController |
| POST | `/cca/bad-debt-pools/{id}/true-up` | `CLOSED` → `TRUED_UP`; segregation of duties; reserve draw cascade | FinanceController |
| POST | `/cca/compliance-filings` | Create a filing in `DRAFT` | ComplianceOfficer |
| GET | `/cca/compliance-filings` | List filings | ComplianceOfficer, BoardDirector, UtilityLiaison |
| GET | `/cca/compliance-filings/{id}` | Read one filing | ComplianceOfficer, BoardDirector, UtilityLiaison |
| GET | `/cca/compliance-filings/{id}/rec-retirements` | List retirements supporting this filing | ComplianceOfficer, BoardDirector |
| POST | `/cca/compliance-filings/{id}/prepare` | `DRAFT` → `PREPARED`; computes RPS attainment for `RPS_ANNUAL` | ComplianceOfficer |
| POST | `/cca/compliance-filings/{id}/review` | `PREPARED` → `REVIEWED`; segregation of duties | ComplianceOfficer |
| POST | `/cca/compliance-filings/{id}/file` | `REVIEWED` → `FILED` | BoardDirector |
| POST | `/cca/compliance-filings/{id}/cpuc-accept` | `FILED` → `ACCEPTED_BY_CPUC` | UtilityLiaison |
| POST | `/cca/compliance-filings/{id}/cpuc-reject` | `FILED` → `REJECTED_BY_CPUC` | UtilityLiaison |
| POST | `/cca/compliance-filings/{id}/revise` | `REJECTED_BY_CPUC` → `DRAFT`; increments the revision count | ComplianceOfficer |
| POST | `/cca/compliance-filings/{id}/withdraw` | `DRAFT` → `WITHDRAWN` | ComplianceOfficer |
| POST | `/cca/rec-retirements` | Record a REC retirement against an `RPS_ANNUAL` filing | ComplianceOfficer |
| GET | `/cca/rec-retirements` | Filtered list of retirements | ComplianceOfficer, BoardDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_AUTHORITY_POSTURE` | 409 Conflict |
| `ERR_STATUTE_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_UNIQUENESS_CONFLICT` | 409 Conflict |
| `ERR_REFERENTIAL_STATE` | 422 Unprocessable Entity |
| `ERR_FISCAL_GATE` | 422 Unprocessable Entity |
| `ERR_STALE_AUTHORITY_VERSION` | 412 Precondition Failed |
| `ERR_STALE_EXTRACT_VERSION` | 412 Precondition Failed |
| `ERR_NO_DEFAULT_PRODUCT` | 422 Unprocessable Entity |
| `ERR_ZERO_REC_CLAIM` | 422 Unprocessable Entity |
| `ERR_DISSOLUTION_BLOCKED` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |

# Securities Filings & Section 16 Reporting API — Product Requirements Document

## 1. Introduction

Public-company compliance teams operate under unforgiving disclosure clocks. Every officer, director, and greater-than-ten-percent owner of a public issuer must report trades in that issuer's equity to the SEC quickly and accurately: Form 4 is due within two business days of a trade, Form 3 follows designation as a reporting person, Form 5 sweeps up the exempt residue once a year, and a late filing follows the named individual into the proxy statement. Around those filings sits a broader web of obligations — Rule 10b5-1 trading plans with mandatory cooling-off periods, blackout windows around earnings, Schedule 13D/13G monitoring for large holders, and Section 16(b) short-swing profit exposure — all of which a corporate secretary's office must coordinate with outside filing agents who actually transmit to EDGAR.

This document specifies an API that supports that office end to end: maintaining the insider roster and each person's designation lifecycle, ingesting equity transactions from the equity plan feed or by manual keying, generating draft filings automatically as events occur, enforcing segregation of duties between preparers and submitters, tracking deadlines against exchange holiday calendars, recording EDGAR acceptances and rejections, administering 10b5-1 plans, monitoring beneficial-ownership thresholds, quantifying short-swing profit, and running the annual Form 5 sweep. The system is deliberately built on a controllable logical clock rather than wall-clock time, on an append-only event model for ownership figures, and on optimistic concurrency for the small set of records whose updates can silently clobber one another.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, formats, and cross-cutting principles that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly five roles: `ComplianceOfficer`, `FilingCoordinator`, `FilingAgent`, `EquityPlanAdmin`, and `ReportingInsider`. Invoking an operation one's role does not permit is rejected with `ERR_FORBIDDEN_ROLE`.

- `ComplianceOfficer` — the corporate secretary's Section 16 compliance officer. This role owns issuer registration and configuration, blackout windows, insider designations and exits, transaction confirmation and voiding, 10b5-1 plan approvals and lifecycle actions, beneficial-owner monitoring and schedule recording, annual sweeps, filing-agent authorizations, and the logical clock. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- `FilingCoordinator` — prepares, readies, reopens, discards, and amends filings, and may also key manual transactions; this role never submits to EDGAR. When `X-User-Role` is `FilingCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `prepared_by_user_id` on manually created filings and amendments, and as `ingested_by_user_id` on transactions the coordinator keys.
- `FilingAgent` — an external filing-agent operator who submits ready filings with the EDGAR CCC and records EDGAR dispositions; the agent must hold an `ACTIVE` FilingAgentAuthorization for the filing's issuer. When `X-User-Role` is `FilingAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `submitted_by_user_id` on submission and matches it against `agent_user_id` on authorizations.
- `EquityPlanAdmin` — the equity plan administrator pushing the equity transaction feed. When `X-User-Role` is `EquityPlanAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `ingested_by_user_id` on ingested transactions.
- `ReportingInsider` — the insider themself, who drafts and manages their own 10b5-1 trading plans. When `X-User-Role` is `ReportingInsider`, `X-User-ID` is the `id` of the acting `ReportingPerson`; ownership checks on any resource that references a `ReportingPerson` compare the resource's `reporting_person_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_ROLE`.

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

Endpoints that return lists of resources are paginated through query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Many list endpoints also accept filter parameters naming an owning resource or a lifecycle state — for example `issuer_id`, `reporting_person_id`, `filing_id`, `plan_id`, `holder_id`, `status`, `form_type`, or `amends_filing_id` — as itemized per endpoint in §4.

### 2.4. Common Resource Properties

Every primary resource — Issuer, ReportingPerson, SecurityTransaction, SecuritiesFiling, TradingPlan10b5_1, BlackoutWindow, BeneficialHolder, AnnualSweep, and FilingAgentAuthorization — carries a standard set of system-managed fields:

- `id`: a unique server-minted identifier, formatted as a UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource, including cascaded changes.
- `version`: a system-managed integer that increments by one on every modification of the resource, whether the modification comes from a direct client write or from a system cascade.

The `PositionChange` event is the sole exception. It is immutable once posted and carries only `id` and `created_at`; both `updated_at` and `version` are absent, and the resource is never modified after creation.

### 2.5. The Logical Clock

All system-assigned dates and timestamps read a server-side logical clock, never wall-clock time. On server startup the clock reads exactly 2026-08-01T00:00:00Z; before it has ever been set, reads return that default and the clock never falls back to wall-clock time. A `ComplianceOfficer` may set the clock to any ISO 8601 instant by supplying `to_iso8601`; the capability answers 200 with the resulting `current_utc`.

Every stamp the server writes — `designation_date`, `exit_date`, `adoption_date`, `termination_date`, `submitted_at`, `accepted_at`, `run_at` — is taken from this clock, as are the timeliness comparisons against filing deadlines and the future-date guards. Comparisons between dates are made at whole-calendar-day granularity on `YYYY-MM-DD` values.

### 2.6. Exchange Calendars and Business-Day Arithmetic

Form 4 deadlines and the officer/director cooling-off extension count business days against the filing issuer's exchange calendar. Advancing a date by a given number of business days works as an iterative routine: for each business day owed, move the date forward by one calendar day; if the landing day is a Saturday, a Sunday, or a date listed in the issuer's `holiday_dates` (a list of `YYYY-MM-DD` strings), keep moving forward one calendar day at a time — still within the same step — until the date falls on a weekday that is not a listed holiday; that completes one step, and the routine repeats until the full number of owed steps has elapsed. Deadlines expressed in calendar days (Forms 3 and 5) apply no such shifting.

### 2.7. Numeric Precision and Rounding

Monetary amounts and ownership percentages are rounded half-up to exactly two decimal places and are represented in API responses as numbers. One rounding order is pinned and may not be varied: in the short-swing analysis, each matched pair's profit is rounded half-up to two decimal places first, and the rounded per-pair values are then summed. Share counts, filing counts, sweep result counts, and running share balances are integers. Configuration values supplied by clients (such as a price or a holiday list) preserve their input form.

### 2.8. Validation Order and Error Selection

When several checks could fail on the same request, the first check in the following fixed order determines the rejection, so an early failure is never masked by a later one:

1. **Header presence.** `X-User-ID` and `X-User-Role` must be present and non-empty on every endpoint, failing with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The role must be permitted for the operation; additionally, when the role is `ReportingInsider`, the `X-User-ID` must equal the `reporting_person_id` of the target resource (the plan being created or transitioned). Violations fail with `ERR_FORBIDDEN_ROLE`.
3. **Path existence, left to right.** Every identifier appearing in the URL path — `issuerId`, `blackoutWindowId`, `personId`, `transactionId`, `filingId`, `planId`, `holderId`, `positionChangeId`, `sweepId`, `authorizationId` — is verified to exist, validated left to right; the first missing identifier yields `ERR_NOT_FOUND` before any body or business validation runs.
4. **Request body shape.** On every mutation, required fields must be present, enum values must be valid, dates must be well-formed, a blackout's `start_date` must not be later than its `end_date`, `shares` must be greater than zero, `shares_delta` must not be zero, and `price_per_share` must be present for transaction codes `P` and `S`. Violations yield `ERR_INVALID_REQUEST`.
5. **Optimistic concurrency.** Where an endpoint requires an expected-version field (§2.9), that value must equal the parent resource's current `version`; this check runs before any business rule, and a mismatch yields `ERR_STALE_VERSION`.
6. **Target entity state.** The resource addressed must be in a state that permits the requested transition, failing with the machine's state error: `ERR_PERSON_INVALID_STATE`, `ERR_TRANSACTION_INVALID_STATE`, `ERR_FILING_INVALID_STATE`, `ERR_PLAN_INVALID_STATE`, `ERR_SWEEP_INVALID_STATE`, or `ERR_AUTHORIZATION_INVALID_STATE`.
7. **Cross-entity state.** The operation's counterparties must be in supporting states: confirming a transaction or creating a manual filing requires the reporting person `ACTIVE` (`ERR_PERSON_NOT_ACTIVE`), and submitting or recording an EDGAR result requires an `ACTIVE` filing-agent authorization for the issuer and the acting agent (`ERR_AGENT_NOT_AUTHORIZED`).
8. **Compliance guards**, evaluated in their own fixed sub-order: the confirmer must differ from the ingester (`ERR_SOD_INGESTER_CONFIRMER`); the submitter must differ from a non-null preparer (`ERR_SOD_PREPARER_SUBMITTER`); a plan-affiliated transaction requires its plan `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`); plan activation requires the cooling-off period satisfied (`ERR_COOLING_OFF_NOT_SATISFIED`); and a non-plan transaction's date must not fall inside an issuer blackout window (`ERR_BLACKOUT_PERIOD`).
9. **Temporal guards.** A transaction's `transaction_date` at confirmation and a position change's `effective_date` at posting must not be later than the logical clock date, failing with `ERR_FUTURE_TRANSACTION_DATE` and `ERR_FUTURE_EFFECTIVE_DATE` respectively.
10. **Business constraints.** Duplicate and overlap rules, amendment-target state, EDGAR credential currency, and schedule-necessity rules: `ERR_PLAN_WINDOW_OVERLAP`, `ERR_BLACKOUT_WINDOW_OVERLAP`, `ERR_DUPLICATE_SWEEP`, `ERR_AMENDMENT_TARGET_NOT_ACCEPTED`, `ERR_EDGAR_CREDENTIAL_MISMATCH`, and `ERR_SCHEDULE_NOT_REQUIRED`.
11. **Referential integrity.** Every entity identifier referenced in a request body must exist (`ERR_INVALID_REQUEST`); a plan-affiliated confirmed transaction's plan must belong to the same person (`ERR_PLAN_PERSON_MISMATCH`); and the transactions named for a manual Form 4 must be attachable (`ERR_TRANSACTION_NOT_ATTACHABLE`).

The HTTP status carried by each error identifier is listed in §5.

### 2.9. Optimistic Concurrency Control

Two write operations are version-guarded, because the records they touch can legitimately be updated through independent paths and a client holding a stale observation must be told to re-read rather than overwrite state it has not seen:

- Updating an issuer — `PUT /issuers/{issuerId}` — requires the request to carry `expected_issuer_version` equal to the issuer's current `version`. Issuer configuration is freely editable, so both an older and a newer write would legitimately succeed on product semantics; if the issuer's `version` has advanced since the client last observed it, the update is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating an amendment — `POST /filings/{filingId}/amendments` — requires `expected_filing_version` equal to the amended filing's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because a new amendment supersedes any earlier pending amendment work. Successful amendment creation itself increments the amended filing's `version` by one.

Endpoints not named here do not take an expected-version field.

### 2.10. Segregation of Duties

Two four-eyes controls run through the filing supply chain. First, transaction confirmation: the `ComplianceOfficer` confirming a transaction must not be the operator who ingested it — the caller's `X-User-ID` must differ from the transaction's `ingested_by_user_id`, failing with `ERR_SOD_INGESTER_CONFIRMER`. Second, filing submission: the `FilingAgent` submitting a filing must not be the operator who prepared it — the caller's `X-User-ID` must differ from a non-null `prepared_by_user_id`, failing with `ERR_SOD_PREPARER_SUBMITTER`. Because system-generated drafts (the automatic Form 4 on confirmation, the Form 3 on designation or reinstatement, the Form 5 on sweep) carry a null `prepared_by_user_id`, any properly authorized agent may submit them.

### 2.11. Derived Figures and Cross-Entity Cascades

Several figures on person and holder records are maintained by the server rather than written by clients, and understanding their triggers is essential to predicting state:

- `open_obligation_count` on a reporting person counts that person's filings in `DRAFT`, `READY`, or `SUBMITTED` status; filings in `ACCEPTED`, `REJECTED`, `SUPERSEDED`, or `DISCARDED` do not count. It is recomputed on every filing creation and every filing status change affecting the person: a created draft (automatic or manual) raises it by one, while acceptance or discard lowers it by one.
- `late_filing_count` on a reporting person is a lifetime count of that person's filings accepted late. It never decrements — subsequent timely filings do not reduce it, and supersession of a late filing by an amendment does not reduce it either. Once `late_filing_count` reaches two, the person's `delinquent_flag` becomes true and is sticky: it never auto-clears.
- `shares_owned_after` maintains a running insider balance per person-and-security-type chain, recomputed on transaction confirmation and voiding (§3.3).
- Updating an issuer's `shares_outstanding` recomputes `current_pct` and `fully_diluted_pct` for every beneficial holder of that issuer and re-evaluates their threshold transitions (§3.7).

Every such mutation — whether the primary write or a cascade hop — refreshes `updated_at` and increments `version` on the affected resource.

## 3. Business Logic & Workflows

### 3.1. Issuer Onboarding and Configuration Stewardship

A `ComplianceOfficer` registers each public company as an Issuer, supplying its legal `name`, the exchange `ticker` symbol, the ten-digit SEC Central Index Key `cik`, the current EDGAR confirmation code `edgar_ccc`, the common-share count `shares_outstanding` (which must be greater than zero and serves as the denominator of the basic ownership percentage), and the `fiscal_year_end_month` as an integer from 1 to 12, where 12 denotes a December 31 fiscal year end. Two optional attributes complete the profile: `holiday_dates`, a list of exchange holiday dates as `YYYY-MM-DD` strings that the business-day routine skips (empty when omitted), and `next_earnings_filing_date`, the date of the issuer's next periodic earnings report, which feeds the officer/director cooling-off extension and may remain unset.

Issuer configuration stays editable by a `ComplianceOfficer` throughout the issuer's life — `name`, `ticker`, `shares_outstanding`, `fiscal_year_end_month`, `edgar_ccc`, `holiday_dates`, and `next_earnings_filing_date` may all be changed. The update is guarded by the issuer's expected version as described in §2.9 and increments the issuer's `version` by one on success. Two fields have immediate downstream effects. Because every EDGAR submission must present the issuer's current confirmation code, changing `edgar_ccc` changes what a filing agent must supply from that moment on. And changing `shares_outstanding` recomputes `current_pct` and `fully_diluted_pct` for every beneficial holder of the issuer and re-evaluates their threshold transitions (§3.7).

### 3.2. Insider Roster and the Designation Lifecycle

Before anyone can report, a `ComplianceOfficer` places the insider on the roster with the `issuer_id` of the issuer whose securities they report on, the insider's `full_name`, their individual SEC `person_cik`, and three flags that default to false when omitted: `is_director` for board directors, `is_officer` for Section 16 officers, and `is_ten_pct_owner` for greater-than-ten-percent beneficial owners. The officer and director flags drive the extended 10b5-1 cooling-off computation in §3.6. A newly created insider sits in `PROPOSED` status — known to the system but not yet subject to Section 16.

The designation lifecycle is driven through a transitions capability taking an `action` of `DESIGNATE`, `EXIT`, or `REINSTATE`. Designation moves a person from `PROPOSED` to `ACTIVE`, stamps `designation_date` with the logical clock date, and — because a new insider owes an initial statement — causes the system to create a `DRAFT` `FORM_3` filing with a null `prepared_by_user_id` whose `filing_deadline` falls ten calendar days after the designation date; the person's `open_obligation_count` rises by one for the new draft. When an insider's status ends, `EXIT` moves the person from `ACTIVE` to `EXITED` and stamps `exit_date` with the logical clock date. Reinstatement closes the loop: `REINSTATE` moves a person from `EXITED` back to `ACTIVE`, re-stamps `designation_date` with the logical clock date, clears `exit_date` to null, and again creates a `DRAFT` `FORM_3` on the same ten-calendar-day deadline with the same `open_obligation_count` increment. The cycle `ACTIVE` → `EXITED` → `ACTIVE` makes this machine cyclic, with no terminal state. Any of these actions attempted from a state that does not allow it is rejected with `ERR_PERSON_INVALID_STATE`.

Two counters ride on the person record for disclosure purposes: `late_filing_count`, the lifetime tally of the person's filings accepted late, and `delinquent_flag`, which latches true once that tally reaches two and never auto-clears (§3.4). Because both transaction confirmation and manual filing creation require an `ACTIVE` person, a `PROPOSED` or `EXITED` insider blocks those flows with `ERR_PERSON_NOT_ACTIVE`.

### 3.3. Transaction Intake, Confirmation, and Voiding

Equity transactions enter through two channels: an `EquityPlanAdmin` pushes the equity plan feed, or a `FilingCoordinator` keys a trade by hand; the channel is recorded in `source` as `EQUITY_PLAN_FEED` or `MANUAL`, defaulting to `MANUAL`. The intake payload names the `reporting_person_id`, the `transaction_date` (which may be earlier than the logical clock date but never later — the future-date rule bites at confirmation), the `transaction_code`, the `security_type` as one of `COMMON_STOCK`, `OPTION`, `RSU`, or `DERIVATIVE_OTHER`, the `shares` transacted, an optional `price_per_share` (required for codes `P` and `S`, optional otherwise), and an optional `plan_id` when the trade executed under a 10b5-1 plan. At intake the issuer is denormalized from the reporting person onto the transaction's `issuer_id`, the creator's `X-User-ID` is captured as `ingested_by_user_id` to feed the segregation-of-duties check, and the transaction lands in `INGESTED` with `filing_id` unset.

The `transaction_code` vocabulary carries its regulatory meaning: `P` is an open-market purchase, `S` a sale, `A` a grant or award, `M` an option exercise, `F` a tax-withholding disposition, `G` a gift, and `V` a vest. From the code the system derives `direction`: codes `P`, `A`, `M`, and `V` are `ACQUIRED`, while codes `S`, `F`, and `G` are `DISPOSED`.

Confirmation by a `ComplianceOfficer` moves a transaction from `INGESTED` to `CONFIRMED` and is the most heavily guarded transition in the system. Its checks are evaluated in order, so an early failure surfaces rather than being masked by a later one: the transaction must be `INGESTED` (`ERR_TRANSACTION_INVALID_STATE`); its reporting person must be `ACTIVE` (`ERR_PERSON_NOT_ACTIVE`); the confirmer's `X-User-ID` must differ from the transaction's `ingested_by_user_id` (`ERR_SOD_INGESTER_CONFIRMER`); when a `plan_id` is set, the referenced plan must be `ACTIVE` (`ERR_PLAN_NOT_ACTIVE` — this catches trades under plans still cooling off in `ADOPTED` or parked in `SUSPENDED`); when no `plan_id` is set, the `transaction_date` must not fall inside any of the issuer's blackout windows, whose start and end dates are both inclusive (`ERR_BLACKOUT_PERIOD`); the `transaction_date` must not be later than the logical clock date (`ERR_FUTURE_TRANSACTION_DATE`); and finally a plan-affiliated transaction's plan must belong to the same reporting person as the transaction (`ERR_PLAN_PERSON_MISMATCH`).

A successful confirmation fires a two-hop cascade. First the system computes `direction`, recomputes the running-balance chain described below, and — for every code except `G` — automatically creates a `DRAFT` `FORM_4` filing with a null `prepared_by_user_id`, attaches the transaction by setting its `filing_id`, and fixes the deadline two business days after the transaction date per §3.4; an auto-generated Form 4 covers exactly one transaction. Second, that filing creation itself raises the person's `open_obligation_count` by one. Gifts (code `G`) generate no Form 4; they wait for the annual Form 5 sweep in §3.8.

The running balance `shares_owned_after` tracks the insider's position per person-and-`security_type` chain. Recomputation considers that person's transactions of the given security type in `CONFIRMED` or `REPORTED` status, ordered by `transaction_date` ascending with ties broken by `created_at` ascending — never by `id`; a running total starts at zero, each transaction adds its `shares` when its `direction` is `ACQUIRED` and subtracts them when `DISPOSED`, and the resulting total is stored on the transaction as `shares_owned_after`. Confirming an earlier-dated transaction after a later-dated one therefore recomputes the whole chain. While a transaction is `INGESTED` or `VOID`, its `shares_owned_after` is null.

Voiding compensates the confirmation cascade. A `ComplianceOfficer` may void a transaction in `INGESTED` or `CONFIRMED` status, optionally recording a `reason`; any other starting state fails with `ERR_TRANSACTION_INVALID_STATE`. Voiding a `CONFIRMED` transaction carries an extra guard: when a linked filing exists and has already reached `SUBMITTED` or `ACCEPTED`, the void is blocked with `ERR_TRANSACTION_INVALID_STATE`, because a reported trade cannot be un-happened. When the void proceeds against a `CONFIRMED` transaction, its linked `DRAFT` or `READY` filing moves to `DISCARDED` and its transactions are detached (their `filing_id` cleared), that discard lowers the person's `open_obligation_count` by one as exact compensation for the confirm-time increment, and the balance chain is recomputed. `VOID` and `REPORTED` are the terminal states of a transaction; the move from `CONFIRMED` to `REPORTED` is automatic when the linked filing is accepted (§3.5).

### 3.4. Filing Deadlines, Timeliness, and Delinquency

Every filing carries a computed `filing_deadline`, and the formula depends on the form. A `FORM_4` is due two business days after the earliest `transaction_date` among the transactions it covers, advanced per the business-day routine of §2.6 against the issuer's `holiday_dates` as they stood when the filing was created. A `FORM_3` is due ten calendar days after the person's `designation_date`, with no business-day shifting. A `FORM_5` is due forty-five calendar days after the fiscal year end; a manually created Form 5 resolves its supplied `fiscal_year` against the issuer's fiscal calendar to locate that year end.

Timeliness is judged exactly once, at acceptance: `is_late` is true precisely when the calendar date of `accepted_at` is strictly later than `filing_deadline`, so a filing accepted on its deadline date is timely. The flag is never recomputed afterwards. Each late acceptance increases the person's `late_filing_count` by one, and the moment that count reaches two the `delinquent_flag` latches true. Both are permanent: later timely filings never clear the flag, and a late filing that is subsequently superseded by an amendment still counts.

### 3.5. The Filing Pipeline: Preparation, Submission, EDGAR Disposition, and Amendment

Beyond the drafts the system generates, a `FilingCoordinator` may create a `DRAFT` filing manually by naming the `issuer_id`, the `reporting_person_id`, and a `form_type` of `FORM_3`, `FORM_4`, or `FORM_5`; the reporting person must be `ACTIVE` (`ERR_PERSON_NOT_ACTIVE`). A manual `FORM_4` must carry `transaction_ids` naming transactions that are all `CONFIRMED`, all still unattached to any filing, and all belonging to the same person as the filing — any shortfall is rejected with `ERR_TRANSACTION_NOT_ATTACHABLE` — and its deadline derives from the earliest covered `transaction_date`. A manual `FORM_5` carries `fiscal_year` instead. Manual creation stamps `prepared_by_user_id` with the coordinator's `X-User-ID`, attaches the covered transactions, computes `filing_deadline`, and raises the person's `open_obligation_count` by one.

Preparation then proceeds as a small state walk. Marking ready moves a filing from `DRAFT` to `READY` (any other starting state fails with `ERR_FILING_INVALID_STATE`). Reopening returns a `READY` or `REJECTED` filing to `DRAFT` for editing, clearing `submitted_at`, `submitted_by_user_id`, and `rejection_reason`. Discarding moves a `DRAFT` filing to the terminal `DISCARDED` state, detaches its covered transactions so they become re-fileable, and lowers the person's `open_obligation_count` by one.

Submission belongs to a `FilingAgent` holding an `ACTIVE` FilingAgentAuthorization for the filing's issuer. A `ComplianceOfficer` creates such authorizations by pairing an `issuer_id` with the agent's opaque `agent_user_id`; they start `ACTIVE`, and revocation — permitted only while `ACTIVE`, failing otherwise with `ERR_AUTHORIZATION_INVALID_STATE` — moves one to the terminal `REVOKED` state, after which that agent can no longer submit or record EDGAR results for the issuer. At submit time the filing must be `READY` (`ERR_FILING_INVALID_STATE`), and the remaining checks run in order: an `ACTIVE` authorization must exist pairing the filing's `issuer_id` with the caller's `X-User-ID` (`ERR_AGENT_NOT_AUTHORIZED`); the submitter must differ from a non-null `prepared_by_user_id` (`ERR_SOD_PREPARER_SUBMITTER`); and the payload `edgar_ccc` must equal the issuer's current `edgar_ccc` (`ERR_EDGAR_CREDENTIAL_MISMATCH`). A successful submission stamps `submitted_at` from the logical clock and `submitted_by_user_id` from the acting agent, moving the filing to `SUBMITTED`.

EDGAR's disposition is recorded by an authorized `FilingAgent` against a `SUBMITTED` filing — any other filing state fails with `ERR_FILING_INVALID_STATE`, and the same `ACTIVE` authorization requirement applies (`ERR_AGENT_NOT_AUTHORIZED`) — by passing an `outcome` of `ACCEPTED` or `REJECTED`. A rejection records the supplied `rejection_reason` and moves the filing to `REJECTED`, from which reopening restarts the revision loop `DRAFT` → `READY` → `SUBMITTED` → `REJECTED` → `DRAFT`, making the machine cyclic. An acceptance stamps `accepted_at` from the logical clock, records the supplied `accession_number`, and fires the acceptance cascade in order: `is_late` is computed once against `filing_deadline`; if the filing is late, the person's `late_filing_count` rises by one; if that count thereby reaches two, `delinquent_flag` latches true; every transaction attached to the filing moves from `CONFIRMED` to `REPORTED`; when the accepted filing is an amendment (its `amends_filing_id` set), the filing it amends moves automatically from `ACCEPTED` to the terminal `SUPERSEDED` state; and the person's `open_obligation_count` drops by one.

Amendments are born from accepted filings. A `FilingCoordinator` creates an amendment draft against a filing in `ACCEPTED` status — any other target state is rejected with `ERR_AMENDMENT_TARGET_NOT_ACCEPTED` — carrying `expected_filing_version` per §2.9. Creation increments the amended filing's `version` by one; the new `DRAFT` copies the amended filing's `issuer_id`, `reporting_person_id`, `form_type`, and `filing_deadline`, records `amends_filing_id` pointing at the amended filing, stamps `prepared_by_user_id` with the coordinator, and raises the person's `open_obligation_count` by one. The amendment then flows through the same prepare-submit-record pipeline, and its acceptance supersedes the original.

### 3.6. Trading Controls: Blackout Windows and Rule 10b5-1 Plans

Around earnings and other sensitive periods, a `ComplianceOfficer` declares issuer trading blackouts as closed-interval windows naming the `issuer_id`, a `start_date`, and an `end_date` — both bounds inclusive, with `end_date` no earlier than `start_date` — plus an optional `reason`. Two windows of the same issuer conflict when they share at least one calendar date, and a conflicting creation is rejected with `ERR_BLACKOUT_WINDOW_OVERLAP`. Confirming a transaction that carries no `plan_id` whose `transaction_date` lands inside any of the issuer's blackout windows fails with `ERR_BLACKOUT_PERIOD` (§3.3); trades executed under a 10b5-1 plan skip the blackout check entirely.

A `ReportingInsider` drafts a Rule 10b5-1 plan for themself — the body's `reporting_person_id` must equal the caller's `X-User-ID`, failing with `ERR_FORBIDDEN_ROLE` otherwise — supplying a human-readable `plan_name`, a `first_trade_date`, and an `expiration_date`, which together describe a half-open trading window that runs from `first_trade_date` up to but not including `expiration_date`. The issuer is denormalized from the person onto the plan's `issuer_id` at creation, and the new plan starts in `DRAFT`.

The plan lifecycle is driven through a transitions capability taking an `action`. The owning insider submits the draft for adoption (`SUBMIT_ADOPTION`), moving the plan from `DRAFT` to `PENDING_APPROVAL`; a draft in any other state fails with `ERR_PLAN_INVALID_STATE`. A `ComplianceOfficer` then approves or rejects it. Approval (`APPROVE`) requires `PENDING_APPROVAL` and enforces window exclusivity across the person's book: no other plan of the same `reporting_person_id` in `ADOPTED`, `ACTIVE`, or `SUSPENDED` status may have a window intersecting this plan's window, where two windows intersect exactly when the first plan's `first_trade_date` falls before the second plan's `expiration_date` and the second plan's `first_trade_date` falls before the first plan's `expiration_date`; an intersecting approval is rejected with `ERR_PLAN_WINDOW_OVERLAP`. Approval stamps `adoption_date` with the logical clock date and computes `cooling_off_end_date`, which is frozen from that moment onward. Rejection (`REJECT`) moves a `PENDING_APPROVAL` plan to the terminal `REJECTED` state.

The cooling-off end is computed once, at approval, as follows. The base end is `adoption_date` plus 90 calendar days. When the plan's reporting person is flagged as an officer (`is_officer`) or a director (`is_director`), an earnings-based end is computed by advancing the issuer's `next_earnings_filing_date` by two business days using the same business-day routine as filing deadlines; the extended end is the later of the base end and the earnings-based end, and `cooling_off_end_date` becomes the earlier of that extended end and `adoption_date` plus 120 calendar days. When the person is neither an officer nor a director — a pure ten-percent owner or an unflagged insider — `cooling_off_end_date` is simply the base end. If the person is an officer or director but the issuer's `next_earnings_filing_date` is not set, the earnings-based end is treated as the base end, meaning no extension applies.

Activation (`ACTIVATE`) moves an `ADOPTED` plan to `ACTIVE` once the logical clock date has reached `cooling_off_end_date` — equality satisfies the rule — and attempting activation earlier fails with `ERR_COOLING_OFF_NOT_SATISFIED`. From `ACTIVE`, a compliance hold suspends the plan (`SUSPEND` moves `ACTIVE` to `SUSPENDED`), and a later `REINSTATE` moves `SUSPENDED` back to `ACTIVE`; both actions must leave `cooling_off_end_date` unchanged, so a hold never resets the cooling-off clock. Termination (`TERMINATE`) is available to a `ComplianceOfficer` or to the owning insider from `ADOPTED`, `ACTIVE`, or `SUSPENDED`, stamps `termination_date` with the logical clock date, and lands in the terminal `TERMINATED` state; from any other source state it fails with `ERR_PLAN_INVALID_STATE`. Trades under a plan carry its `plan_id` at intake, and their confirmation requires the plan to be `ACTIVE` at that moment (`ERR_PLAN_NOT_ACTIVE`) and to belong to the transacting person (`ERR_PLAN_PERSON_MISMATCH`).

### 3.7. Beneficial Ownership Monitoring and Schedule 13D/G

For holders who are not necessarily Section 16 insiders, a `ComplianceOfficer` begins threshold monitoring by creating a BeneficialHolder with the `issuer_id`, the `holder_name` (fund, individual, or entity), and an optional `holder_cik`. The holder starts in `MONITORING` with zeroed positions and neither a `last_reported_pct` nor a `schedule_type`.

Ownership is event-sourced. Every movement is appended as an immutable `PositionChange` naming the `holder_id`, a signed `shares_delta` (never zero; positive for acquisitions, negative for dispositions), an optional signed `derivative_shares_delta` tracking sixty-day-exercisable derivative shares (zero when omitted), the `effective_date` of the change — which must not be later than the logical clock date, failing with `ERR_FUTURE_EFFECTIVE_DATE` — and an optional `note`. Posting a change recomputes the holder's derived figures: `shares_beneficially_owned` is the sum of every `shares_delta` ever posted for the holder (the log is append-only and no status filter applies); `exercisable_derivative_shares` is the corresponding sum of `derivative_shares_delta`; `current_pct` is one hundred times `shares_beneficially_owned` divided by the issuer's current `shares_outstanding`, rounded half-up to two decimal places; and `fully_diluted_pct` is one hundred times the sum of `shares_beneficially_owned` and `exercisable_derivative_shares` divided by the sum of `shares_outstanding` and `exercisable_derivative_shares`, rounded the same way. The fully diluted figure is informational only and never gates thresholds — it diverges from the basic figure whenever the holder has exercisable derivatives. The same recomputation is triggered when the issuer's `shares_outstanding` changes (§3.1).

Two thresholds drive the holder's `status`, and both evaluate `current_pct` alone. When a posting leaves `current_pct` at 5.00 or higher — equality triggers — the holder moves automatically from `MONITORING` to `FILING_REQUIRED`. Once a schedule is on file, drift matters instead: when the absolute difference between `current_pct` and the `last_reported_pct` snapshot reaches 1.00 or more — again with equality triggering — the holder moves automatically from `FILED` to `AMENDMENT_REQUIRED`, and the loop between `FILED` and `AMENDMENT_REQUIRED` keeps the machine cyclic.

Recording the Schedule 13D or 13G itself is a `ComplianceOfficer` action that supplies the `schedule_type`, either `SCHEDULE_13D` or `SCHEDULE_13G`. It is permitted only while the holder is `FILING_REQUIRED` or `AMENDMENT_REQUIRED`; from any other state it fails with `ERR_SCHEDULE_NOT_REQUIRED`. On success the holder moves to `FILED`, `last_reported_pct` snapshots the then-current `current_pct`, and the supplied `schedule_type` is stored — that snapshot becoming the basis for the next drift evaluation.

### 3.8. The Annual Form 3/5 Sweep

After fiscal year end, a `ComplianceOfficer` opens an AnnualSweep for an issuer by supplying the `issuer_id` and the `fiscal_year`. The system computes the fiscal window at creation: `fy_end_date` is the last calendar day of the issuer's `fiscal_year_end_month` in that `fiscal_year`, and `fy_start_date` is the day after the prior fiscal year's end — equivalently one year before `fy_end_date` plus one day — with both bounds inclusive. The sweep starts `OPEN`. Only one sweep may exist per issuer and fiscal year across the `OPEN` and `COMPLETED` states; a duplicate creation is rejected with `ERR_DUPLICATE_SWEEP`.

Running the sweep is permitted only while it is `OPEN` (otherwise `ERR_SWEEP_INVALID_STATE`); the run stamps `run_at` from the logical clock, computes one result row per in-scope person, and moves the sweep to the terminal `COMPLETED` state. In-scope persons are the issuer's reporting persons in `ACTIVE` or `EXITED` status whose `designation_date` falls on or before `fy_end_date` and who either have no `exit_date` or whose `exit_date` falls on or after `fy_start_date`.

Each row of the sweep's `results` array records the person's `reporting_person_id`; a window-scoped `late_filing_count` — the count of the person's filings in `ACCEPTED` or `SUPERSEDED` status with `is_late` true whose `accepted_at` date falls within the fiscal window; an `unreported_exempt_count` — the count of the person's gift transactions (transaction code `G`) that are `CONFIRMED`, still unattached to any filing, and dated within the fiscal window; a `needs_form5` flag that is true exactly when the unreported exempt count is greater than zero; a `delinquent` flag that is true exactly when the window late-filing count is greater than zero; and a `form5_filing_id` that stays null unless the run creates a Form 5 for the person. Rows are emitted ordered by the person's `full_name` ascending, with ties broken by `created_at` ascending.

For each person flagged `needs_form5`, the run automatically creates a `DRAFT` `FORM_5` filing with a null `prepared_by_user_id`, attaches that person's unreported exempt transactions, sets the `filing_deadline` forty-five calendar days after `fy_end_date`, records the new filing's id in the row's `form5_filing_id`, and raises that person's `open_obligation_count` by one. Those drafts then flow through the ordinary pipeline of §3.5.

### 3.9. Short-Swing Profit Analysis Under Section 16(b)

On demand, any role may read a computed Section 16(b) short-swing analysis over a reporting person's eligible transactions: open-market purchases (code `P`) and sales (code `S`) in `CONFIRMED` or `REPORTED` status. `INGESTED` and `VOID` transactions never participate. The response identifies the person by `reporting_person_id`, carries the `as_of_date` of the computation, reports the `matchable_pair_count` of matched pairs, presents both profit figures described below, and enumerates the underlying `pairs`.

A purchase and a sale are matchable when their transaction dates lie strictly less than six calendar months apart, in either order: the sale's date falls before the purchase's date plus six calendar months, or the purchase's date falls before the sale's date plus six calendar months. Adding calendar months clamps the day to the end of the resulting month when that month is shorter. A purchase and a sale exactly six calendar months apart are not matchable. Only pairs in which the sale's `price_per_share` exceeds the purchase's `price_per_share` participate in the profit total. Within a pair, the matched share count is the smaller of the purchase's remaining unmatched shares and the sale's remaining unmatched shares, and the pair's profit is the difference between the sale's and the purchase's `price_per_share` multiplied by the matched shares — rounded half-up to two decimal places per pair first, with the rounded per-pair values then summed, in that pinned order.

Two matching variants are reported side by side. `short_swing_profit` is the authoritative recovery figure under the maximum-recovery rule: sales are processed in descending `price_per_share` order with ties broken by `created_at` ascending, and each sale is matched against the remaining purchase with the lowest `price_per_share` that is both matchable with the sale and yields a positive spread, ties again broken by `created_at` ascending. `short_swing_profit_fifo` is the chronological comparison figure: sales are processed in ascending `transaction_date` order with ties broken by `created_at` ascending, and each sale is matched against the earliest remaining purchase that is matchable and yields a positive spread — earliest by `transaction_date`, ties by `created_at`. The two variants can produce different totals for identical inputs, which is exactly why both are reported.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read, modify, or transition an existing resource return `200 OK`. The table below is deliberately minimal: request payloads, preconditions, side effects, and cascades for each operation are specified by the narratives in §2 and §3, which are the authoritative source. "All roles" means any of the five roles enumerated in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ComplianceOfficer |
| POST | `/issuers` | Register a public company issuer | ComplianceOfficer |
| GET | `/issuers` | List issuers (paginated) | All roles |
| GET | `/issuers/{issuerId}` | Get one issuer | All roles |
| PUT | `/issuers/{issuerId}` | Update issuer configuration (OCC-guarded) | ComplianceOfficer |
| POST | `/blackout-windows` | Create an issuer trading blackout window | ComplianceOfficer |
| GET | `/blackout-windows` | List blackout windows, filterable by issuer | All roles |
| GET | `/blackout-windows/{blackoutWindowId}` | Get one blackout window | All roles |
| POST | `/reporting-persons` | Create a proposed insider | ComplianceOfficer |
| GET | `/reporting-persons` | List reporting persons, filterable | All roles |
| GET | `/reporting-persons/{personId}` | Get one reporting person | All roles |
| POST | `/reporting-persons/{personId}/transitions` | Drive the designation lifecycle (DESIGNATE / EXIT / REINSTATE) | ComplianceOfficer |
| GET | `/reporting-persons/{personId}/short-swing-analysis` | Computed Section 16(b) short-swing profit analysis (both variants) | All roles |
| POST | `/transactions` | Ingest an equity transaction (feed or manual) | EquityPlanAdmin, FilingCoordinator |
| GET | `/transactions` | List transactions, filterable | All roles |
| GET | `/transactions/{transactionId}` | Get one transaction | All roles |
| POST | `/transactions/{transactionId}/confirm` | Confirm an ingested transaction (four-eyes) | ComplianceOfficer |
| POST | `/transactions/{transactionId}/void` | Void a transaction before it is reported | ComplianceOfficer |
| POST | `/filings` | Manually create a DRAFT filing (FORM_3 / FORM_4 / FORM_5) | FilingCoordinator |
| GET | `/filings` | List filings, filterable | All roles |
| GET | `/filings/{filingId}` | Get one filing | All roles |
| POST | `/filings/{filingId}/ready` | Mark a DRAFT filing READY for submission | FilingCoordinator |
| POST | `/filings/{filingId}/reopen` | Return a READY or REJECTED filing to DRAFT | FilingCoordinator |
| POST | `/filings/{filingId}/discard` | Discard a DRAFT filing; covered transactions detach | FilingCoordinator |
| POST | `/filings/{filingId}/submit` | Submit a READY filing to EDGAR | FilingAgent |
| POST | `/filings/{filingId}/record-edgar-result` | Record the EDGAR disposition for a SUBMITTED filing | FilingAgent |
| POST | `/filings/{filingId}/amendments` | Create an amendment DRAFT targeting an ACCEPTED filing (OCC-guarded) | FilingCoordinator |
| POST | `/trading-plans` | Insider drafts a 10b5-1 trading plan | ReportingInsider |
| GET | `/trading-plans` | List trading plans, filterable | All roles |
| GET | `/trading-plans/{planId}` | Get one trading plan | All roles |
| POST | `/trading-plans/{planId}/transitions` | Drive the plan lifecycle (SUBMIT_ADOPTION / APPROVE / REJECT / ACTIVATE / SUSPEND / REINSTATE / TERMINATE) | ReportingInsider, ComplianceOfficer |
| POST | `/beneficial-holders` | Start monitoring a beneficial owner | ComplianceOfficer |
| GET | `/beneficial-holders` | List beneficial holders, filterable | All roles |
| GET | `/beneficial-holders/{holderId}` | Get one beneficial holder | All roles |
| POST | `/beneficial-holders/{holderId}/positions` | Append a position change event | ComplianceOfficer |
| GET | `/position-changes` | List position change events, filterable by holder | All roles |
| GET | `/position-changes/{positionChangeId}` | Get one position change event (immutable) | All roles |
| POST | `/beneficial-holders/{holderId}/file-schedule` | Record a Schedule 13D/13G filing | ComplianceOfficer |
| POST | `/annual-sweeps` | Open an annual Form 3/5 sweep for an issuer and fiscal year | ComplianceOfficer |
| GET | `/annual-sweeps` | List annual sweeps, filterable | All roles |
| GET | `/annual-sweeps/{sweepId}` | Get one annual sweep including results | All roles |
| POST | `/annual-sweeps/{sweepId}/run` | Execute the sweep and auto-create needed Form 5 drafts | ComplianceOfficer |
| POST | `/filing-agent-authorizations` | Authorize a filing agent operator for an issuer | ComplianceOfficer |
| GET | `/filing-agent-authorizations` | List authorizations, filterable | All roles |
| GET | `/filing-agent-authorizations/{authorizationId}` | Get one authorization | All roles |
| POST | `/filing-agent-authorizations/{authorizationId}/revoke` | Revoke an ACTIVE authorization | ComplianceOfficer |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PERSON_INVALID_STATE` | 409 Conflict |
| `ERR_PERSON_NOT_ACTIVE` | 409 Conflict |
| `ERR_TRANSACTION_INVALID_STATE` | 409 Conflict |
| `ERR_FILING_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_INVALID_STATE` | 409 Conflict |
| `ERR_SWEEP_INVALID_STATE` | 409 Conflict |
| `ERR_AUTHORIZATION_INVALID_STATE` | 409 Conflict |
| `ERR_FUTURE_TRANSACTION_DATE` | 422 Unprocessable Entity |
| `ERR_FUTURE_EFFECTIVE_DATE` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_PLAN_PERSON_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COOLING_OFF_NOT_SATISFIED` | 422 Unprocessable Entity |
| `ERR_BLACKOUT_PERIOD` | 422 Unprocessable Entity |
| `ERR_BLACKOUT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PLAN_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_SWEEP` | 409 Conflict |
| `ERR_AMENDMENT_TARGET_NOT_ACCEPTED` | 409 Conflict |
| `ERR_EDGAR_CREDENTIAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_AGENT_NOT_AUTHORIZED` | 403 Forbidden |
| `ERR_SOD_PREPARER_SUBMITTER` | 403 Forbidden |
| `ERR_SOD_INGESTER_CONFIRMER` | 403 Forbidden |
| `ERR_SCHEDULE_NOT_REQUIRED` | 409 Conflict |
| `ERR_TRANSACTION_NOT_ATTACHABLE` | 422 Unprocessable Entity |

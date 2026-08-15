# IP Portfolio Docketing & Annuity Payments API — Product Requirements Document

## 1. Introduction

A patent firm's docketing department lives and dies by dates. Every office action carries a statutory response window; every granted patent accumulates annuity and maintenance obligations that differ by jurisdiction, by period year, and by the applicant's entity size; every foreign-filing decision is boxed in by Paris Convention and PCT priority windows that close on a fixed day whether anyone noticed or not. Around those dates orbit the supporting disciplines: recording inventor assignments against official registers, instructing outside counsel and confirming their execution, auditing the internal docket against the official registers, deciding which applications to abandon and which families to prune, and forecasting what the committed portfolio will cost. A single missed statutory deadline can forfeit a client's rights outright, so the cost of an ambiguous rule is measured in lost patents.

This document specifies the IP Portfolio Docketing & Annuity Payments API, the system of record for that department. The portfolio is organized as clients owning patent families, families owning applications, and applications owning docket entries, office actions, annuity obligations, payment authorizations, outside counsel instructions, abandonment reviews, assignment records, and docket audits. Jurisdiction rules supply the statutory parameters — response periods, extension limits, fee tiers, surcharge schedules, priority windows, exchange rates, and recordation gates — that drive every computation. Date-dependent behavior is evaluated against a server-held logical clock, never the wall clock, and an operator-run docket sweep lapses what has gone overdue. The API enforces segregation of duties on controlled approval pairs, optimistic concurrency on the two writes that open financial or pruning workflows, a hard per-family budget cap on committed annuity spend, and computed read models for per-family budget forecasts and per-client docket risk scores.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven role names with these exact spellings: `PlatformAdmin`, `DocketingClerk`, `DocketingManager`, `RecordsSpecialist`, `FinanceOfficer`, `ClientApprover`, and `OutsideCounsel`. An eighth name, `Any`, appears in the endpoint catalogue to denote the shared read-only surface; it is not a role a caller presents in a header but indicates that every successfully authenticated caller may use the endpoint. Failure to provide both headers, presenting an `X-User-Role` value that is not one of the declared role names, or — for the entity-backed roles below — presenting an `X-User-ID` that does not reference an existing instance of the backing entity is rejected with an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error. Furthermore, access to specific operations is restricted by role; an attempt to perform an action outside of the caller's designated role is rejected with an `ERR_FORBIDDEN_FOR_ROLE` error.

The relationship between `X-User-ID` and persisted resources depends on the role. When `X-User-Role` is `ClientApprover`, `X-User-ID` is the `id` of the acting ClientContact; ownership checks on a resource compare the contact's `client_id` to the client that owns the resource's patent family, and a mismatch is a scope violation. When `X-User-Role` is `OutsideCounsel`, `X-User-ID` is the `id` of the acting CounselFirm; scope checks compare it to the `counsel_firm_id` recorded on the instruction being acted upon. When `X-User-Role` is `PlatformAdmin`, `DocketingClerk`, `DocketingManager`, `RecordsSpecialist`, or `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `requested_by_user_id` on a payment authorization, `decided_by_user_id` when a decision is rendered, `submitted_by_user_id` on an abandonment review, or `executed_by_user_id` on an assignment record — but it never compares the value to any entity's `id`. The segregation-of-duties rules in §3 compare these recorded opaque identifiers against the acting `X-User-ID` for controlled approve/record steps.

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

### 2.3. Pagination and List Ordering

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Two list surfaces deviate from the default: the list of annuity obligations under an application is ordered by `period_year` ascending, and the cross-portfolio annuity-obligation list is ordered by the owning application's `created_at` ascending and then by `period_year` ascending within each application.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. `has_more` is true exactly when `offset` + `limit` is strictly less than `total_count`. A `limit` or `offset` that is not an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Six list surfaces are non-paginated and always return every matching item, ignoring any pagination parameters: the office actions of a docket entry, the instructions of a docket entry, the authorizations of an obligation, the abandonment reviews of an application, the assignment records of an application, and the audits of an application; on these surfaces `meta.limit` equals `total_count`, `meta.offset` is 0, and `has_more` is false.

### 2.4. The Logical Clock

Every date-dependent rule in this document — deadline discipline, extension windows, priority windows, surcharge windows, audit windows, sweep lapse checks, and risk-score urgency — is evaluated against a server-held **logical clock**, never against wall-clock time. Before any call has set it, the logical clock reads exactly 2026-08-01T00:00:00Z; that is the server startup default and the server never falls back to wall-clock. A `PlatformAdmin`-only, test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the resulting logical time as `current_utc`, rendered in ISO 8601 UTC at whole-second precision (for example `2026-08-01T00:00:00Z`). Throughout this document, the word "today" means the calendar date, in UTC, of the logical clock at the moment the rule is evaluated.

### 2.5. Jurisdiction Rules: The Regulatory Backbone

A **JurisdictionRule** is the configuration record for one supported jurisdiction. The `jurisdiction` field carries one of the six jurisdiction codes — `US`, `EP`, `JP`, `CN`, `KR`, or `PCT` — and the code is unique across all jurisdiction rules; creating a second rule for an already-registered jurisdiction is rejected with `ERR_INVALID_REQUEST`. A rule fixes the statutory office-action response period in months (`oa_response_months`); the extension policy for office-action-response docket entries, namely the maximum number of extensions per entry (`max_extensions`), the months added to the current due date per extension (`extension_months`), and the official fee charged per extension request in local-currency cents (`extension_fee_cents`); the annuity schedule bounds, from the first period year carrying an annuity obligation (`annuity_start_year`) through the last (`term_years`, the statutory term); the surcharge policy, namely the months after a due date during which payment with surcharge is still accepted (`surcharge_window_months`), the surcharge in basis points of the base fee when payment is exactly one month late (`surcharge_bps_month_1`), and the surcharge in basis points when payment is two or more months late (`surcharge_bps_late`); the fee multiplier in basis points applied when an application's entity size is small (`small_entity_multiplier_bps`); the tiered annuity fee schedule, expressed as `fee_tier_bounds` — a pipe-separated string of four inclusive period-year ranges for tiers one through four, for example `1-3|4-7|8-12|13-20` (a value that does not parse as exactly four pipe-separated ranges is rejected with `ERR_INVALID_REQUEST`) — together with the base annuity fee in local-currency cents for each tier (`fee_tier_1_cents`, `fee_tier_2_cents`, `fee_tier_3_cents`, `fee_tier_4_cents`); the Paris Convention priority window in months (`paris_window_months`) and the PCT national-phase window in months from the priority date (`pct_window_months`); and the exchange rate `fx_to_usd_cents_bps`, which converts a local-currency-cent amount to USD cents by multiplying by the rate and dividing by ten thousand, rounding half up.

Three boolean gates complete the rule, each defaulting to false: `requires_recorded_assignment_for_grant` makes a recorded assignment a precondition to granting an application; `requires_recorded_assignment_for_payment` makes a recorded assignment a precondition to instructing an annuity payment; and `requires_confirmed_instruction_for_payment` makes a confirmed annuity-payment instruction to outside counsel a precondition to instructing payment. §3.4, §3.5, and §3.8 describe where each gate bites.

Jurisdiction rules are created and updated by a `PlatformAdmin` and are readable by anyone. An update may change the response period, the extension policy, the surcharge policy, the entity-size multiplier, the four tier fees, the exchange rate, and the three gates; the `jurisdiction` code, the annuity schedule bounds (`annuity_start_year`, `term_years`), the tier-bound layout (`fee_tier_bounds`), and the two priority windows (`paris_window_months`, `pct_window_months`) are fixed at creation and cannot be patched — an update payload naming any of those fixed fields is rejected with `ERR_INVALID_REQUEST` as an undeclared field of the update operation. Updating a rule never retroactively changes annuity obligations that were already generated: the fee schedule in force at grant time remains attached to those rows. The rule list may be filtered by `jurisdiction`.

### 2.6. Common Resource Properties

Every resource in the system — jurisdiction rules, clients, client contacts, counsel firms, inventors, patent families, applications, docket entries, office actions, annuity obligations, payment authorizations, outside counsel instructions, abandonment reviews, assignment records, and docket audits — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, in the same format, indicating when the resource was last modified; it refreshes upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource.

The `created_at` and `updated_at` values are stamped from the logical clock of §2.4 — never from wall-clock time — so all records created or modified at the same logical instant carry identical timestamps.

Every state transition, every derived-field reconciliation (for example an application's `open_docket_count` or a family's `committed_forecast_cents`), and every cascade touch counts as a modification of each affected resource and therefore refreshes its `updated_at` and increments its `version`.

### 2.7. Money, Precision, and Currency Conversion

All monetary values in the system are integer cents — local-currency official fees in local cents, USD amounts in USD cents — and no fractional cents ever persist. All rounding uses the round-half-up method, and the fee computation in §3.4 pins its rounding order: the entity-size multiplier is applied and rounded first, the surcharge is computed on that rounded base and itself rounded, and the currency conversion is applied and rounded last, so each step emits whole cents before the next step consumes it. All basis-point rates are divided by exactly ten thousand. Aggregations such as the family budget forecast and the committed-spend rollup never re-round: they sum per-line integer-cent amounts that were already rounded at their own computation step.

A client's `default_currency` defaults to USD and USD is the only currency the calculations support; all authorized, paid, committed, forecast, and savings figures are USD cents. The one exception to integer presentation is the client risk score of §3.9, which is kept internally as an exact rational value and reported with two decimal places, rounded half up only at final presentation.

### 2.8. Optimistic Concurrency Control

Two write operations carry an obligatory optimistic-concurrency field, and no other endpoint accepts a version field.

First, requesting a payment authorization against an annuity obligation requires the non-optional field `expected_annuity_obligation_version`, carrying the `version` of the obligation as the client last observed it. If the obligation's current `version` has advanced since that read — for example because another writer has just requested an authorization, which moves the obligation to `PENDING_AUTHORIZATION` and increments its version, or because a recalculation touched the obligation — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on an obligation state it has not observed.

Second, proposing an abandonment review against an application requires the non-optional field `expected_application_version`, carrying the `version` of the application as the client last observed it. A prior review proposal legitimately opened review state on the application and incremented its version, so a creator holding an older version works from a stale read; the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Request Validation Order and Nested Resource Retrieval

When a request fails several checks at once, the rejection returned is decided by a fixed validation order; lower-numbered checks win. The order is:

1. **User context.** Both authentication headers present, the role declared, and any entity-backed identifier resolving to an existing instance — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The acting role is permitted on the endpoint — otherwise `ERR_FORBIDDEN_FOR_ROLE`.
3. **Entity-backed scope.** On the five scope-gated operations (approving or rejecting a payment authorization; acknowledging, confirming, or declining an instruction), the acting contact or firm matches the resource's owning scope — otherwise `ERR_SCOPE_VIOLATION`.
4. **Existence.** Path identifiers are validated left to right, and the request is rejected with `ERR_NOT_FOUND` for the first identifier that does not resolve; only then are body-supplied references — `parent_application_id`, `counsel_firm_id`, `docket_entry_id`, each element of `inventor_ids`, and (on application creation) the jurisdiction rule backing the supplied `jurisdiction` code — resolved, each failure also producing `ERR_NOT_FOUND`. On a nested path such as an application inside a family inside a client, a missing client is reported before a missing family, and a missing family before a missing application.
5. **Optimistic concurrency.** On the two version-gated writes of §2.8, a stale expected version is rejected with `ERR_STALE_VERSION`.
6. **Request-body shape.** Required fields present, no undeclared fields, enum values within their declared sets, date fields in ISO YYYY-MM-DD form, integers where integers are declared, and — on docket audits — `window_start` strictly earlier than `window_end`; violations are rejected with `ERR_INVALID_REQUEST`.
7. **State.** The target resource must be in a from-state that defines the requested transition; an undefined transition is rejected with `ERR_INVALID_STATE`, and any transition attempted on a resource already in a terminal state is rejected with `ERR_ALREADY_TERMINAL`.
8. **Segregation of duties.** On the controlled pairs of §3.6 and §3.8, the deciding user must differ from the recorded first actor — otherwise `ERR_SEGREGATION_OF_DUTIES`.

Only after all eight universal layers pass are business rules evaluated, and they too run in a fixed order: counsel accreditation (`ERR_COUNSEL_NOT_ACCREDITED`), then foreign-filing priority windows (`ERR_PRIORITY_WINDOW_EXPIRED`), then deadline discipline (`ERR_DEADLINE_PASSED`), then the surcharge window (`ERR_SURCHARGE_WINDOW_CLOSED`), then audit-window overlap (`ERR_AUDIT_WINDOW_OVERLAP`), then instruction exclusivity (`ERR_INSTRUCTION_EXCLUSIVE_CONFLICT`), then extension policy (`ERR_EXTENSION_NOT_ALLOWED_TYPE` and `ERR_EXTENSION_LIMIT_REACHED`), then duplicate application numbers (`ERR_DUPLICATE_APPLICATION_NUMBER`), then continuation-chain integrity (`ERR_PARENT_APPLICATION_LAPSED`, `ERR_PARENT_FAMILY_MISMATCH`, `ERR_PRIORITY_CHAIN_CYCLE`, `ERR_PARENT_NOT_PCT`), then the open-review check (`ERR_REVIEW_ALREADY_OPEN`), then entry cancellability (`ERR_ENTRY_NOT_CANCELLABLE`), then inventor-client membership (`ERR_INVENTOR_CLIENT_MISMATCH`), then the released-authorization gate (`ERR_AUTHORIZATION_NOT_RELEASED`), then the jurisdiction-conditional recordation and instruction gates (`ERR_ASSIGNMENT_RECORDATION_REQUIRED`, `ERR_COUNSEL_INSTRUCTION_REQUIRED`), then the family budget cap (`ERR_FAMILY_BUDGET_EXCEEDED`), then the suspended-client gate (`ERR_CLIENT_SUSPENDED`), then the family lifecycle gates (`ERR_FAMILY_HAS_APPROVED_REVIEWS`, `ERR_FAMILY_HAS_OPEN_APPLICATIONS`, `ERR_FAMILY_NOT_IN_PRUNING_REVIEW`), and finally the application-open gates (`ERR_APPLICATION_NOT_OPEN`).

### 2.10. Hierarchical Consistency and Cascading State Changes

The portfolio forms a strict tree: a Client owns ClientContacts, Inventors, and PatentFamilies; a PatentFamily owns Applications; an Application owns DocketEntries, OfficeActions, AnnuityObligations, OutsideCounselInstructions, AbandonmentReviews, AssignmentRecords, and DocketAudits. CounselFirm stands outside the tree as a peer registry that instructions reference, and an Application may reference another Application as its parent in a continuation chain.

When a parent becomes non-operational, the system resolves everything open beneath it rather than leaving orphans: abandoning or lapsing an application cancels its open docket entries, annuity obligations, and instructions, closes its open office actions, and compensates the family's committed-spend rollup. Cascades are transitive — a cancelled docket entry in turn cancels instructions linked to it and closes an office action that references it — and each cascade step is an ordinary mutation of every affected resource, refreshing `updated_at` and incrementing `version` as §2.6 requires. Derived counters are reconciled by the same write that changes their inputs, so an application's open-entry count and a family's committed forecast are never left stale. Conversely, child events can move a parent: a statutory deadline lapsing takes its whole application down with it, and an annuity obligation lapsing past its surcharge window takes a granted application down with it.

## 3. Business Logic & Workflows

### 3.1. Clients, Contacts, and Patent Families

Everything in the portfolio hangs off a **Client**. A `PlatformAdmin` creates a client with a `display_name` and an optional `default_currency`; the currency defaults to USD and is the only currency the calculations support. A new client's `status` is `ACTIVE`. Suspension moves a client `ACTIVE → SUSPENDED`, and reactivation moves `SUSPENDED → ACTIVE`; both are `PlatformAdmin` operations and the client has no terminal state. While a client is `SUSPENDED`, every creation scoped beneath it — patent families, applications, docket entries, office actions, payment authorizations, outside counsel instructions, abandonment reviews, assignment records, and docket audits — is rejected with `ERR_CLIENT_SUSPENDED`.

**ClientContact** rows back the client-side approver identity of §2.1. A `PlatformAdmin` registers a contact under a client with a `full_name` and an `email`, and the contact's `client_id` is bound by the client in whose path it was created. Contacts can be listed per client, or across the portfolio filtered by `client_id`.

A **PatentFamily** groups one client's applications around a shared priority claim. A `DocketingManager` creates a family under an active client — a suspended client rejects the creation with `ERR_CLIENT_SUSPENDED` — supplying a `title`, a `first_priority_date` in YYYY-MM-DD form (the earliest priority date, which anchors the Paris and PCT windows of §3.2), and `budget_cap_cents`, a hard cap in USD cents on the family's committed annuity spend. A new family's `status` is `ACTIVE` and its `committed_forecast_cents` starts at zero.

Family posture is managed by the `DocketingManager`. Entering pruning review moves a family `ACTIVE → PRUNING_REVIEW`. Exiting moves `PRUNING_REVIEW → ACTIVE`, but the exit is blocked while any application of the family carries an abandonment review in `APPROVED` status, surfacing `ERR_FAMILY_HAS_APPROVED_REVIEWS`. Closing a family — defined from both `ACTIVE` and `PRUNING_REVIEW` — requires every application of the family to already sit in a terminal state, that is `ABANDONED`, `LAPSED`, or `WITHDRAWN`; if any application is still open, the close is rejected with `ERR_FAMILY_HAS_OPEN_APPLICATIONS`. `CLOSED` is terminal.

Families are listed per client, or across the portfolio filtered by `client_id` or `status`.

### 3.2. Filing Applications: Types, Priority Windows, and Continuation Chains

A `DocketingClerk` creates an application inside a family, supplying the `jurisdiction` code, an `application_type` of `ORIGINAL`, `PARIS_CONVENTION`, `PCT_INTERNATIONAL`, `PCT_NATIONAL_PHASE`, `CONTINUATION`, or `DIVISIONAL`, the `filing_date`, an `application_number`, and an `entity_size` of `LARGE` or `SMALL`. The supplied jurisdiction must be one of the six supported codes and a jurisdiction rule for it must already exist, because every downstream computation reads that rule; a supported code whose rule has not been created yet is rejected with `ERR_NOT_FOUND`. A new application's `status` is `DRAFT` and its `open_docket_count` starts at zero. Creation is rejected with `ERR_CLIENT_SUSPENDED` when the owning client is suspended.

Within a family, `application_number` must be unique among the applications that are not `WITHDRAWN`; a number already carried by a live sibling — and equally by an abandoned or lapsed one — collides and is rejected with `ERR_DUPLICATE_APPLICATION_NUMBER`.

Foreign-filing deadlines anchor to the family's `first_priority_date`. For a `PARIS_CONVENTION` filing, the deadline is the priority date shifted forward by the new application's jurisdiction rule `paris_window_months`; for a `PCT_NATIONAL_PHASE` filing, it is the priority date shifted forward by `pct_window_months`. Filing is permitted when the `filing_date` falls on or before that deadline — the boundary day itself is allowed — and a later filing date is rejected with `ERR_PRIORITY_WINDOW_EXPIRED`. The window lengths come from the rule of the new application's jurisdiction, not the parent's.

Continuation-type filings form a self-referential chain. The `parent_application_id` field identifies the parent application for `CONTINUATION`, `DIVISIONAL`, and `PCT_NATIONAL_PHASE` filings and is omitted for the other types. Whenever a parent is supplied — at creation, or later when a clerk re-parents a draft — the chain is validated by walking the parent links upward from the proposed parent. Every link must resolve to an existing application (`ERR_NOT_FOUND` otherwise); the proposed parent must not be in `LAPSED` status (`ERR_PARENT_APPLICATION_LAPSED`); the proposed parent must belong to the same patent family as the child (`ERR_PARENT_FAMILY_MISMATCH`); the chain must remain acyclic — if following parent links from the proposed parent would arrive back at the application being created or re-parented, the write is rejected with `ERR_PRIORITY_CHAIN_CYCLE`; and a `PCT_NATIONAL_PHASE` filing requires the proposed parent's `application_type` to be `PCT_INTERNATIONAL` (`ERR_PARENT_NOT_PCT`). Re-parenting is defined only while the application is `DRAFT` — any other status fails with `ERR_INVALID_STATE` — and re-runs the entire chain check, including cycle detection, against the new parent; supplying a `parent_application_id` of null instead clears the parent and runs no chain check.

Filing moves an application `DRAFT → PENDING` and is permitted only while the family is `ACTIVE` or `PRUNING_REVIEW` and the owning client is `ACTIVE` (`ERR_CLIENT_SUSPENDED` otherwise); filing under a family in any other status — that is, `CLOSED` — is rejected with `ERR_INVALID_STATE`. A clerk may also withdraw a draft, moving `DRAFT → WITHDRAWN` with no further preconditions; `WITHDRAWN` is terminal, as are `ABANDONED` and `LAPSED`, which §3.6 and §3.9 cover.

Applications are listed per family — optionally filtered by `status` — or across the portfolio filtered by `family_id`, `parent_application_id`, or `status`.

### 3.3. Docket Entries and Office Action Responses

The docket calendar is built from **DocketEntry** resources. A `DocketingClerk` creates an entry under an application with an `entry_type` of `OFFICE_ACTION_RESPONSE`, `STATUTORY`, `PARIS_PRIORITY`, `PCT_PHASE`, `ANNUITY`, or `RECORDATION`, plus a `title` and a `base_due_date`. A new entry starts `PENDING` with `extension_count` at zero, `extension_fees_total_cents` at zero, and `current_due_date` equal to its `base_due_date`, and the parent application's `open_docket_count` increases by one. The count is maintained operationally: it increments on every entry creation, decrements when an entry completes, and decrements when an entry in `PENDING` or `IN_PROGRESS` is cancelled or lapses. Recording a response (`IN_PROGRESS → RESPONSE_FILED`) leaves the count unchanged, so a `RESPONSE_FILED` entry remains counted until it completes; symmetrically, a cancellation that reaches an entry already in `RESPONSE_FILED` (possible only through the abandonment/lapse cascades of §3.6 and §3.9, since direct cancellation is defined only from `PENDING` and `IN_PROGRESS`) does not decrement the count. Creation requires an active client (`ERR_CLIENT_SUSPENDED`) and a non-terminal application (`ERR_APPLICATION_NOT_OPEN`).

Starting work moves an entry `PENDING → IN_PROGRESS`; it requires the application to be `PENDING` or `GRANTED` (`ERR_APPLICATION_NOT_OPEN`). When the entry tracks an office action of one of the rejection types, that office action automatically moves `RECEIVED → UNDER_RESPONSE` as the entry starts.

Extensions of time are available only on `OFFICE_ACTION_RESPONSE` entries; requesting one on any other type is rejected with `ERR_EXTENSION_NOT_ALLOWED_TYPE`. The jurisdiction rule's `max_extensions` bounds the grant count: a request that would raise `extension_count` to exactly the maximum succeeds, and the request beyond it fails with `ERR_EXTENSION_LIMIT_REACHED`. The entry's `current_due_date` must not have passed — a request made on the due date itself is still permitted, a later one is rejected with `ERR_DEADLINE_PASSED` — and the application must be `PENDING` or `GRANTED` (`ERR_APPLICATION_NOT_OPEN`). Each granted extension increments `extension_count` by one, recomputes `current_due_date` as the `base_due_date` shifted forward by `extension_count` times the rule's `extension_months`, and adds the rule's `extension_fee_cents` to `extension_fees_total_cents`. Extension requests are defined from both `PENDING` and `IN_PROGRESS` with identical preconditions and effects.

Recording a filed response moves `IN_PROGRESS → RESPONSE_FILED`; the request carries the `response_filed_date`, which must fall on or before the `current_due_date` (`ERR_DEADLINE_PASSED`), and the application must be `PENDING` (`ERR_APPLICATION_NOT_OPEN`). If the office rejects the filed response, recording that rejection moves the entry `RESPONSE_FILED → IN_PROGRESS`: the request supplies a `new_base_due_date`, both `base_due_date` and `current_due_date` reset to it, and `extension_count` resets to zero; `extension_fees_total_cents` is unaffected — extension fees already incurred persist across the reset. This revision loop may repeat without limit. Completing the entry moves `RESPONSE_FILED → COMPLETED`, decrements the application's `open_docket_count` by one, and — when an office action references the entry and is `UNDER_RESPONSE` — closes that office action to `CLOSED`.

Cancellation is a `DocketingManager` decision defined from `PENDING` and `IN_PROGRESS`. It is blocked while any outside counsel instruction linked to the entry is in `DRAFT`, `SENT`, `ACKNOWLEDGED`, or `CONFIRMED` status, surfacing `ERR_ENTRY_NOT_CANCELLABLE`; a successful cancellation moves the entry to `CANCELLED` and decrements `open_docket_count`. When the logical clock's today passes an entry's `current_due_date`, the docket sweep of §3.9 lapses the entry — `PENDING → LAPSED` or `IN_PROGRESS → LAPSED` — again decrementing `open_docket_count`, and if the lapsed entry is of type `STATUTORY`, its parent application lapses with it when the application is `PENDING` or `GRANTED` (the overdue entry of a `DRAFT` application lapses alone). `COMPLETED`, `CANCELLED`, and `LAPSED` are terminal.

**OfficeAction** resources record what the patent office mailed. A clerk records an action with an `action_type` of `NON_FINAL_REJECTION`, `FINAL_REJECTION`, `NOTICE_OF_ALLOWANCE`, or `INFORMATIONAL`, plus the `mail_date`; the action starts in `RECEIVED`. Recording an office action carries only the suspended-client gate of §3.1 — the application's own status is not gated. For the two rejection types, the system auto-creates a response-tracking docket entry of type `OFFICE_ACTION_RESPONSE` whose `title` reads `Office Action Response (<action_type>)` and whose `base_due_date` is the action's `mail_date` shifted forward by the jurisdiction rule's `oa_response_months` — month arithmetic preserves the day of month, clamping to the last day of the target month when that month is shorter — increments the application's `open_docket_count` by one, and stores the new entry's identifier in the action's `docket_entry_id`; for `NOTICE_OF_ALLOWANCE` and `INFORMATIONAL` actions the `docket_entry_id` remains null. A clerk may close an `INFORMATIONAL` or `NOTICE_OF_ALLOWANCE` action directly (`RECEIVED → CLOSED`); attempting that closure on a rejection type is rejected with `ERR_INVALID_STATE`. Once a rejection-type action is `UNDER_RESPONSE`, it closes automatically when its tracked entry completes. `CLOSED` is terminal.

Entries are listed per application — filtered by `status` or `entry_type` — or across the portfolio filtered by `application_id`, `status`, or `entry_type`. Office actions are listed per application, per tracking entry (at most one action references an entry), or across the portfolio filtered by `application_id` or `docket_entry_id`; the instructions linked to an entry are likewise listed from the entry.

### 3.4. Grant and the Annuity Obligation Schedule

Granting moves an application `PENDING → GRANTED`; the request carries the `grant_date`, which is stored on the application. When the application's jurisdiction rule enables `requires_recorded_assignment_for_grant`, grant is blocked until a `RECORDED` assignment record exists for the application (`ERR_ASSIGNMENT_RECORDATION_REQUIRED`).

Grant is also the moment the annuity schedule materializes. The system generates one **AnnuityObligation** per `period_year`, from the rule's `annuity_start_year` through its `term_years` inclusive, produced in ascending period-year order and each starting in `SCHEDULED` status under the granted application. Each obligation's `due_date` is the application's `grant_date` shifted forward by twelve times the period year minus six months, using the same day-preserving month arithmetic as §3.3, clamping to the target month's last day when needed. Each obligation's `surcharge_window_end` is its `due_date` shifted forward by the rule's `surcharge_window_months`. Two fee figures are computed at generation: `base_fee_local_cents`, the tiered base fee in local-currency cents with the entity-size adjustment applied, and `estimated_amount_usd_cents`, the on-time USD estimate.

The fee computation runs identically at generation — where no paid date exists and the on-time estimate results — and at payment confirmation, where the actual paid date drives the surcharge. First, the obligation's `period_year` selects its tier: the year falls inside exactly one of the four inclusive pipe-separated ranges of the rule's `fee_tier_bounds`, and the base fee is the corresponding `fee_tier_1_cents`, `fee_tier_2_cents`, `fee_tier_3_cents`, or `fee_tier_4_cents`; a period year falling outside every declared range uses the fourth tier's fee. Second, when the application's `entity_size` is `SMALL`, the base is multiplied by the rule's `small_entity_multiplier_bps` and divided by ten thousand, rounded half up to whole local cents; a `LARGE` application pays the tier fee unadjusted. Third, the surcharge: when there is no paid date yet, or the paid date falls on or before the `due_date`, the surcharge is zero. Otherwise the number of months late is the count of calendar months begun after the due date up to the paid date — take the whole calendar months between the two dates and add one whenever any day remainder exists, so any paid date strictly after the due date yields at least one month late. Exactly one month late uses the rule's `surcharge_bps_month_1`; two or more months late uses `surcharge_bps_late`. The surcharge is the entity-adjusted base multiplied by the applicable basis-point rate and divided by ten thousand, rounded half up. The total in local cents is the base plus the surcharge, and the USD amount converts it by multiplying by the rule's `fx_to_usd_cents_bps`, dividing by ten thousand, and rounding half up. The rounding order is pinned exactly as written — entity-size adjustment first, surcharge next, conversion last — and each step emits whole cents before the next consumes them.

### 3.5. Authorizing and Disbursing Annuity Payments

Paying an obligation is a five-party workflow with segregation between those who request, those who approve, and those who disburse.

A `DocketingManager` or `FinanceOfficer` requests payment authorization for a `SCHEDULED` obligation, supplying `amount_cents` — the USD amount requested — together with the OCC field `expected_annuity_obligation_version` described in §2.8; a stale version is rejected with `ERR_STALE_VERSION`, and a suspended client rejects the request with `ERR_CLIENT_SUSPENDED`. No separate grant-state gate exists: obligations are generated only at grant and the lapse and abandonment cascades cancel them, so a `SCHEDULED` obligation always sits under a `GRANTED` application. The request creates a **PaymentAuthorization** in `REQUESTED` status, records the acting header as its `requested_by_user_id`, binds it to the obligation via `annuity_obligation_id`, moves the obligation `SCHEDULED → PENDING_AUTHORIZATION`, and increments the obligation's `version` by one.

Decision belongs to the client's side. A `ClientApprover` approves or rejects, and both operations are defined only while the authorization is `REQUESTED`. The scope check requires the acting contact's `client_id` to equal the client owning the obligation's family (`ERR_SCOPE_VIOLATION`). Approval additionally requires the obligation to still be `PENDING_AUTHORIZATION` (`ERR_INVALID_STATE`) and then runs the budget gate in a pinned evaluation order: read the family's current `committed_forecast_cents` — which already includes every currently committed obligation — add the authorization's `amount_cents`, and reject with `ERR_FAMILY_BUDGET_EXCEEDED` when that sum strictly exceeds the family's `budget_cap_cents`, changing nothing; a sum exactly equal to the cap is permitted. On approval, `decided_by_user_id` records the approver, the authorization becomes `APPROVED`, and the cascade moves the obligation to `AUTHORIZED`, copies the authorization's `amount_cents` into the obligation's `authorized_amount_cents`, and adds the amount into the family's `committed_forecast_cents` — so the gated sum becomes the new stored rollup and the check never observes a half-updated value. Rejection records `decided_by_user_id`, marks the authorization `REJECTED`, and returns the obligation to `SCHEDULED`; a fresh authorization may then be requested, forming a revision loop.

Disbursement is finance's side. A `FinanceOfficer` releases an `APPROVED` authorization, moving it to `RELEASED`. A `DocketingManager` may unwind an authorization entirely: deauthorizing moves the obligation `AUTHORIZED → SCHEDULED`, subtracts its `authorized_amount_cents` from the family's `committed_forecast_cents`, clears `authorized_amount_cents` back to null, and supersedes the current authorization whether it was `APPROVED` or `RELEASED` (→ `SUPERSEDED`).

Instructing payment moves the obligation `AUTHORIZED → PAYMENT_INSTRUCTED` and is gated three ways: the current authorization must be `RELEASED` (`ERR_AUTHORIZATION_NOT_RELEASED`); when the jurisdiction rule enables `requires_recorded_assignment_for_payment`, a `RECORDED` assignment record must exist for the application (`ERR_ASSIGNMENT_RECORDATION_REQUIRED`); and when the rule enables `requires_confirmed_instruction_for_payment`, an outside counsel instruction of type `ANNUITY_PAYMENT` on the application must be `CONFIRMED` or `COMPLETED` (`ERR_COUNSEL_INSTRUCTION_REQUIRED`). If confirmation from the register or counsel stalls, a `FinanceOfficer` may raise a confirmation query (`PAYMENT_INSTRUCTED → CONFIRMATION_QUERY`) and later reinstruct (`CONFIRMATION_QUERY → PAYMENT_INSTRUCTED`); the pair may cycle repeatedly.

Confirming payment is the terminal act, defined only from `PAYMENT_INSTRUCTED` — an obligation sitting in `CONFIRMATION_QUERY` must first be re-instructed before it can be confirmed: a `FinanceOfficer` supplies the `paid_date`, which must fall on or before the obligation's `surcharge_window_end` (`ERR_SURCHARGE_WINDOW_CLOSED`). The obligation becomes `PAID_CONFIRMED`; its `paid_amount_cents` is the full §3.4 computation — tier, entity size, surcharge for lateness, conversion — evaluated with the actual `paid_date` and expressed in USD cents; the family's `committed_forecast_cents` adjusts by the difference between `paid_amount_cents` and the previously committed `authorized_amount_cents`; and `authorized_amount_cents` clears to null. An obligation's `authorized_amount_cents` is non-null only while the obligation is `AUTHORIZED`, `PAYMENT_INSTRUCTED`, or `CONFIRMATION_QUERY` — it clears back to null on deauthorization, on payment confirmation, and on cascade cancellation — and its `paid_amount_cents` is null unless `PAID_CONFIRMED`. `PAID_CONFIRMED`, `LAPSED`, and `CANCELLED` are terminal for obligations; `RELEASED`, `REJECTED`, and `SUPERSEDED` are terminal for authorizations.

Obligations also lapse: when the logical clock's today passes an obligation's `surcharge_window_end`, the docket sweep moves a `SCHEDULED` obligation to `LAPSED` with no budget effect — nothing was committed — and moves a `PENDING_AUTHORIZATION` obligation to `LAPSED` while superseding its still-`REQUESTED` authorization (→ `SUPERSEDED`). Beyond those flows, a family's `committed_forecast_cents` is a maintained rollup: at all times it equals the sum of `authorized_amount_cents` over the family's obligations in `AUTHORIZED`, `PAYMENT_INSTRUCTED`, or `CONFIRMATION_QUERY` status, plus the sum of `paid_amount_cents` over obligations in `PAID_CONFIRMED`. It is maintained incrementally by every transition that changes membership or amounts — approval adds, deauthorization subtracts, confirmation swaps the authorized figure for the paid figure as a delta, and the abandonment and lapse cascades subtract the authorized amounts of cancelled committed obligations — and it never re-rounds, because every contributing amount is already an integer-cent value.

Obligations are listed per application — ordered by `period_year` ascending, optionally filtered by `status` — or across the portfolio filtered by `application_id` or `status`. Authorizations are listed per obligation, or across the portfolio filtered by `annuity_obligation_id` or `status`.

### 3.6. Portfolio Pruning: Abandonment Review and Execution

Pruning begins when a `DocketingManager` proposes an **AbandonmentReview** on an application, supplying the business `rationale` and the OCC field `expected_application_version` of §2.8; a stale version is rejected with `ERR_STALE_VERSION`. At most one review per application may be open at a time — open meaning any of `PROPOSED`, `UNDER_REVIEW`, or `APPROVED` — and a second proposal while one is open is rejected with `ERR_REVIEW_ALREADY_OPEN`. The review starts `PROPOSED`, and its creation increments the application's `version` by one, which is precisely what makes a second proposer's older read stale.

At creation the review freezes its `estimated_savings_usd_cents`: the sum of `estimated_amount_usd_cents` over the application's obligations currently in `SCHEDULED` status, minus a fixed pruning administration fee of 15000 cents, floored at zero so a heavily committed application never shows negative savings. Obligations already `PENDING_AUTHORIZATION` or `AUTHORIZED` contribute nothing to the estimate — their spend is already committed — and the figure never recomputes afterwards.

Submitting moves the review `PROPOSED → UNDER_REVIEW` and records the acting manager's header as `submitted_by_user_id`. Approving (`UNDER_REVIEW → APPROVED`) and rejecting (`UNDER_REVIEW → REJECTED`) are segregation-of-duties gated: the deciding user's `X-User-ID` must differ from the recorded `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. `REJECTED` is terminal.

Executing an approved review requires the family to be in `PRUNING_REVIEW` (`ERR_FAMILY_NOT_IN_PRUNING_REVIEW`) and fires the abandonment cascade in hops. Hop one: the application becomes `ABANDONED` — the cascade is identical whether it was `PENDING` or `GRANTED`; if the application is in any other status at execution time (still `DRAFT`, or already terminal), no application cascade runs and the review nonetheless becomes `EXECUTED`. Hop two: every non-terminal docket entry of the application — `PENDING`, `IN_PROGRESS`, or `RESPONSE_FILED` — moves to `CANCELLED`, each entry that was `PENDING` or `IN_PROGRESS` decrementing the application's `open_docket_count` while a `RESPONSE_FILED` entry's cancellation leaves the count unchanged (per §3.3); and every non-terminal annuity obligation — `SCHEDULED`, `PENDING_AUTHORIZATION`, `AUTHORIZED`, `PAYMENT_INSTRUCTED`, or `CONFIRMATION_QUERY` — moves to `CANCELLED`, where obligations in the three committed states additionally subtract their `authorized_amount_cents` from the family's `committed_forecast_cents` and supersede their current authorization (→ `SUPERSEDED`). Hop three: each entry cancellation cancels any instruction linked to that entry while the instruction is `DRAFT`, `SENT`, `ACKNOWLEDGED`, or `CONFIRMED` (→ `CANCELLED`), and closes any office action referencing the entry while it is `RECEIVED` or `UNDER_RESPONSE` (→ `CLOSED`). Finally, any remaining non-terminal instructions of the application that were never linked to an entry are cancelled as well. The review ends `EXECUTED`, which is terminal.

Reviews are listed per application, or across the portfolio filtered by `application_id` or `status`.

### 3.7. Outside Counsel Instructions and the Exclusivity Window

Before any instruction can be routed, a `PlatformAdmin` registers each **CounselFirm** with a `display_name` and its `accredited_jurisdictions` — the array of jurisdiction codes the firm may serve.

A `DocketingClerk` or `DocketingManager` creates an **OutsideCounselInstruction** under an application, naming the firm via `counsel_firm_id`, an `instruction_type` of `FILING`, `OA_RESPONSE`, `ANNUITY_PAYMENT`, or `RECORDATION`, a `due_date`, and optionally the `docket_entry_id` of the docket entry the instruction services — only the entry's existence is enforced; it need not belong to the same application; the new instruction starts in `DRAFT`. Two creation gates apply. The firm must be accredited for the application's jurisdiction (`ERR_COUNSEL_NOT_ACCREDITED`). And for the same application and instruction type, instructions enjoy an exclusivity window: the closed interval from the new instruction's creation date through its `due_date` — both endpoint dates included — must not share a single calendar date with the corresponding closed window of any existing instruction of that application and type that is still `DRAFT`, `SENT`, `ACKNOWLEDGED`, or `CONFIRMED`; because both intervals are closed, windows that merely touch at an endpoint already conflict and are rejected with `ERR_INSTRUCTION_EXCLUSIVE_CONFLICT`. A suspended client rejects the creation with `ERR_CLIENT_SUSPENDED`.

Sending is a clerk's action (`DRAFT → SENT`) and requires the application to be `DRAFT`, `PENDING`, or `GRANTED` (`ERR_APPLICATION_NOT_OPEN`). From there the instructed firm speaks: acknowledging moves `SENT → ACKNOWLEDGED`, declining moves `SENT → DECLINED`, and confirming readiness moves `ACKNOWLEDGED → CONFIRMED`. All three counsel actions are scope-checked — the acting `X-User-ID` must be the `id` of the counsel firm recorded on the instruction (`ERR_SCOPE_VIOLATION`). A clerk marks a `CONFIRMED` instruction as `COMPLETED`. Cancellation by a clerk or manager is defined while the instruction is `DRAFT` or `SENT`; instructions in `ACKNOWLEDGED` or `CONFIRMED` are cancelled only by the system cascades — a linked docket entry's cancellation, or the application's abandonment or lapse. `COMPLETED`, `DECLINED`, and `CANCELLED` are terminal.

Instructions are listed per application — filtered by `status` — per counsel firm, per linked docket entry, or across the portfolio filtered by `application_id`, `counsel_firm_id`, `docket_entry_id`, or `status`.

### 3.8. Inventors and Assignment Recordation

A `RecordsSpecialist` registers each **Inventor** under a client with a `full_name` and an `email`, the inventor's `client_id` bound by the path. Inventors are listed per client or across the portfolio filtered by `client_id`, and the assignment records referencing a given inventor are listed from the inventor.

An **AssignmentRecord** documents the transfer of rights. A `RecordsSpecialist` creates one under an application with the `assignee_name`, the `execution_date`, and the array `inventor_ids`; every element of `inventor_ids` must resolve to an existing inventor and belong to the same client as the application, else `ERR_INVENTOR_CLIENT_MISMATCH` — and a suspended client rejects the creation with `ERR_CLIENT_SUSPENDED`. The record starts in `DRAFT`.

Executing the assignment moves `DRAFT → EXECUTED` and records the acting specialist's header as `executed_by_user_id`. Recording it against the official register moves `EXECUTED → RECORDED`; the request carries the `register_recordation_number` issued by the register, and the recording specialist's `X-User-ID` must differ from the recorded `executed_by_user_id` — the same user performing both steps is rejected with `ERR_SEGREGATION_OF_DUTIES`. `RECORDED` is terminal. When the register rejects a submission, recording that rejection moves the record from `EXECUTED` to `RECORDATION_REJECTED`; an assignment sitting in `RECORDATION_REJECTED` may be re-executed — `RECORDATION_REJECTED → EXECUTED`, recording a fresh `executed_by_user_id` — and then recorded again, forming a re-execution loop.

These records feed the jurisdiction gates of §2.5: a rule with `requires_recorded_assignment_for_grant` blocks the grant of §3.4 until a `RECORDED` assignment exists, and a rule with `requires_recorded_assignment_for_payment` blocks payment instruction of §3.5 the same way, both surfacing `ERR_ASSIGNMENT_RECORDATION_REQUIRED`.

Assignments are listed per application, per inventor, or across the portfolio filtered by `application_id` or by `inventor_ids`, where the latter accepts a comma-separated list of inventor ids and matches records containing at least one of the listed inventors.

### 3.9. Docket Audits, the Sweep, and Portfolio Reporting

A **DocketAudit** reconciles the internal docket against an official register snapshot. A `DocketingClerk` or `DocketingManager` opens an audit on an application with a `window_start`, a `window_end`, and `register_entries` — an array of register rows, each carrying an `entry_type` and a `due_date`; the audit stores the supplied `register_entries` and returns them on reads. The window is half-open: the start date is included and the end date excluded, and `window_start` must be strictly earlier than `window_end` (`ERR_INVALID_REQUEST`). A new audit's window must not intersect the window of any non-terminal audit on the same application; intersection is rejected with `ERR_AUDIT_WINDOW_OVERLAP`, while pure adjacency — the new `window_start` equalling an existing window's `window_end` — touches no shared date and is allowed.

Variances are computed once, at creation. The internal candidates are the application's docket entries in `PENDING`, `IN_PROGRESS`, `RESPONSE_FILED`, or `COMPLETED` status whose `current_due_date` falls inside the window; the register candidates are the snapshot rows whose `due_date` falls inside the window. Rows are matched on the pair of entry type and due date. Each variance object carries a `kind` field naming the variance kind (`DATE_MISMATCH`, `MISSING_INTERNAL`, or `MISSING_REGISTER`) and the `entry_type`, alongside the due-date fields named below. A register row with no exactly matching internal row produces a `DATE_MISMATCH` variance when an internal row of the same `entry_type` but a different due date exists — choosing the internal row with the smallest absolute difference in due dates and breaking remaining ties by the earliest entry `created_at` — carrying both `internal_due_date` and `register_due_date`; otherwise it produces a `MISSING_INTERNAL` variance carrying the `register_due_date`. After that matching pass, an internal row left without a register match produces a `MISSING_REGISTER` variance carrying the `internal_due_date`. The resulting `variances` list is sorted by entry type ascending and then by due date ascending, taking the internal due date when present and the register due date otherwise. When the computed list is empty the audit stays `OPEN`; otherwise it auto-advances to `VARIANCE_FOUND` at creation. A `DocketingManager` resolves a `VARIANCE_FOUND` audit with a `resolution_note` (→ `RESOLVED`) or closes an `OPEN` audit as clean (→ `CLOSED_CLEAN`); both outcomes are terminal. Audits are listed per application, or across the portfolio filtered by `application_id` or `status`.

The **docket sweep** is the operator-run checkpoint that lapses whatever the logical clock has overtaken, and it is restricted to `PlatformAdmin`. Against the current logical clock it lapses every docket entry in `PENDING` or `IN_PROGRESS` whose `current_due_date` is before today, processing candidates in ascending due-date order with ties broken by ascending `created_at`. Cascade mutations take effect immediately, so an entry already cancelled by an application-lapse cascade before its turn arrives is skipped and counted as cancelled, not lapsed. A lapsed `STATUTORY` entry pulls its parent application to `LAPSED` when the application is `PENDING` or `GRANTED` (a `DRAFT` application is not pulled; the entry lapses alone). The sweep also lapses every annuity obligation in `SCHEDULED` or `PENDING_AUTHORIZATION` whose `surcharge_window_end` is before today — the latter superseding its `REQUESTED` authorization — processing candidates in ascending `surcharge_window_end` order with ties broken by ascending `created_at`, an obligation cancelled by an application-lapse cascade before its turn being skipped and not counted as lapsed; and any `GRANTED` application that had an obligation lapse in this run becomes `LAPSED`, firing the full application-lapse cascade. The run reports `entries_lapsed`, `obligations_lapsed`, `applications_lapsed`, and `obligations_superseded_authorizations`.

Application lapse itself — whether recorded by a clerk against a `GRANTED` application on the strength of the official register, or fired by the sweep — mirrors the §3.6 abandonment cascade: every non-terminal obligation moves to `CANCELLED` with the committed-rollup subtraction and authorization supersession for committed states, every non-terminal docket entry moves to `CANCELLED` with its linked-instruction cancellation and office-action closure cascade, and every unlinked non-terminal instruction is cancelled. The same applies when a statutory entry lapses a still-`PENDING` application; such an application's obligations can only be `SCHEDULED`, but the cancellation rule applies uniformly.

Two computed read models close the loop, both evaluated on read with no caching; on either model, a missing or unrecognized `variant` value is rejected with `ERR_INVALID_REQUEST`. The **family budget forecast** requires a `variant` query value and considers only the family's applications in `PENDING` or `GRANTED` — abandoned, lapsed, and withdrawn applications are excluded, and drafts are excluded because no obligations exist for them. Under `variant` value `COMMITTED`, obligations in `AUTHORIZED`, `PAYMENT_INSTRUCTED`, or `CONFIRMATION_QUERY` contribute their `authorized_amount_cents` and `PAID_CONFIRMED` obligations contribute their `paid_amount_cents`, while `SCHEDULED` and `PENDING_AUTHORIZATION` obligations contribute nothing. Under `variant` value `PROJECTED`, `SCHEDULED` and `PENDING_AUTHORIZATION` obligations additionally contribute their `estimated_amount_usd_cents`. The response carries the `variant`, the `total_usd_cents` — the sum of the contributed per-obligation amounts, summed as already-rounded integer cents and never re-rounded — and `per_application`, one entry per considered application in ascending application `created_at` order, each entry carrying `application_id` and its subtotal as `total_usd_cents`, and each considered application appearing even when its subtotal is zero.

The **client risk score** also requires a `variant` query value. It considers every docket entry in `PENDING` or `IN_PROGRESS` whose parent application is non-terminal and belongs to a family of this client. Each entry contributes a weight by type — `STATUTORY` ten, `OFFICE_ACTION_RESPONSE` four, `PARIS_PRIORITY` eight, `PCT_PHASE` eight, `ANNUITY` six, `RECORDATION` two — multiplied by an urgency factor driven by the calendar days between today and the entry's `current_due_date`: an overdue entry, where the difference is negative, multiplies its weight by eight; due today or within the coming seven days multiplies by four; eight to thirty days out multiplies by two; thirty-one to ninety days out multiplies by one; more than ninety days out contributes half its weight. The `score` is the sum of those weighted contributions: under `variant` value `STATUTORY_ONLY` only `STATUTORY` entries contribute, while under `ALL_DEADLINES` all six types do. The score is kept as an exact rational — the half-weight band can produce half-point steps — and is reported with two decimal places, rounded half up only at final presentation. The reported `tier` is `CRITICAL` for a score of fifty or more, `ELEVATED` for a score of at least twenty but below fifty, and `NORMAL` below twenty. The response carries the `variant`, the `score`, the `tier`, and `per_family` — a list with one entry per family of the client, whatever the family's status and including families whose considered entries contribute nothing, each entry carrying `family_id` and its subtotal as `score` under the same two-decimal half-up presentation, ordered by ascending family `created_at`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; this includes the docket sweep, which returns `201` with its run summary. Operations that modify an existing resource — all state transitions, updates, and the clock-setting capability — return `200 OK`, as do all reads. The table below is a summary only: request payloads, response shapes, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/docket-sweeps` | Run the docket sweep batch against the logical clock | PlatformAdmin |
| POST | `/jurisdiction-rules` | Create a jurisdiction rule | PlatformAdmin |
| GET | `/jurisdiction-rules` | List jurisdiction rules | Any |
| GET | `/jurisdiction-rules/{ruleId}` | Get a jurisdiction rule | Any |
| PATCH | `/jurisdiction-rules/{ruleId}` | Update a jurisdiction rule's fee and gate fields | PlatformAdmin |
| POST | `/clients` | Create a client | PlatformAdmin |
| GET | `/clients` | List clients | Any |
| GET | `/clients/{clientId}` | Get a client | Any |
| POST | `/clients/{clientId}/suspend` | Suspend a client | PlatformAdmin |
| POST | `/clients/{clientId}/reactivate` | Reactivate a suspended client | PlatformAdmin |
| GET | `/clients/{clientId}/risk-score` | Compute the client's docket risk score | Any |
| POST | `/clients/{clientId}/contacts` | Create a client contact | PlatformAdmin |
| GET | `/clients/{clientId}/contacts` | List a client's contacts | Any |
| GET | `/contacts/{contactId}` | Get a contact | Any |
| POST | `/counsel-firms` | Register an outside counsel firm | PlatformAdmin |
| GET | `/counsel-firms/{firmId}` | Get a counsel firm | Any |
| GET | `/counsel-firms/{firmId}/instructions` | List instructions assigned to a firm | Any |
| POST | `/clients/{clientId}/inventors` | Register an inventor | RecordsSpecialist |
| GET | `/clients/{clientId}/inventors` | List a client's inventors | Any |
| GET | `/inventors/{inventorId}` | Get an inventor | Any |
| GET | `/inventors/{inventorId}/assignments` | List assignment records referencing an inventor | Any |
| POST | `/clients/{clientId}/families` | Create a patent family | DocketingManager |
| GET | `/clients/{clientId}/families` | List a client's families | Any |
| GET | `/families/{familyId}` | Get a family | Any |
| POST | `/families/{familyId}/enter-pruning-review` | Move a family into pruning review | DocketingManager |
| POST | `/families/{familyId}/exit-pruning-review` | Move a family out of pruning review | DocketingManager |
| POST | `/families/{familyId}/close` | Close a family | DocketingManager |
| GET | `/families/{familyId}/budget-forecast` | Compute the family's budget forecast | Any |
| POST | `/families/{familyId}/applications` | Create an application | DocketingClerk |
| GET | `/families/{familyId}/applications` | List a family's applications | Any |
| GET | `/applications` | List applications across the portfolio | Any |
| GET | `/applications/{applicationId}` | Get an application | Any |
| PATCH | `/applications/{applicationId}` | Re-parent a draft application | DocketingClerk |
| POST | `/applications/{applicationId}/file` | File a draft application | DocketingClerk |
| POST | `/applications/{applicationId}/grant` | Grant a pending application and generate the annuity schedule | DocketingClerk |
| POST | `/applications/{applicationId}/record-lapse` | Record official-register lapse of a granted application | DocketingClerk |
| POST | `/applications/{applicationId}/withdraw` | Withdraw a draft application | DocketingClerk |
| POST | `/applications/{applicationId}/docket-entries` | Create a docket entry | DocketingClerk |
| GET | `/applications/{applicationId}/docket-entries` | List an application's docket entries | Any |
| GET | `/docket-entries/{entryId}` | Get a docket entry | Any |
| POST | `/docket-entries/{entryId}/start` | Start work on an entry | DocketingClerk |
| POST | `/docket-entries/{entryId}/request-extension` | Request an extension of time | DocketingClerk |
| POST | `/docket-entries/{entryId}/record-response` | Record a filed response | DocketingClerk |
| POST | `/docket-entries/{entryId}/record-rejection` | Record an office rejection of a filed response | DocketingClerk |
| POST | `/docket-entries/{entryId}/complete` | Complete an entry | DocketingClerk |
| POST | `/docket-entries/{entryId}/cancel` | Cancel an open entry | DocketingManager |
| GET | `/docket-entries/{entryId}/office-actions` | List office actions tracked by an entry | Any |
| GET | `/docket-entries/{entryId}/instructions` | List instructions linked to an entry | Any |
| POST | `/applications/{applicationId}/office-actions` | Record a received office action | DocketingClerk |
| GET | `/applications/{applicationId}/office-actions` | List an application's office actions | Any |
| GET | `/office-actions/{officeActionId}` | Get an office action | Any |
| POST | `/office-actions/{officeActionId}/close-informational` | Close an informational or allowance action | DocketingClerk |
| GET | `/applications/{applicationId}/annuity-obligations` | List an application's annuity obligations | Any |
| GET | `/annuity-obligations/{obligationId}` | Get an annuity obligation | Any |
| POST | `/annuity-obligations/{obligationId}/authorizations` | Request payment authorization for an obligation | DocketingManager, FinanceOfficer |
| GET | `/annuity-obligations/{obligationId}/authorizations` | List an obligation's authorizations | Any |
| GET | `/authorizations/{authorizationId}` | Get a payment authorization | Any |
| POST | `/authorizations/{authorizationId}/approve` | Client approves an authorization | ClientApprover |
| POST | `/authorizations/{authorizationId}/reject` | Client rejects an authorization | ClientApprover |
| POST | `/authorizations/{authorizationId}/release` | Release funds for an approved authorization | FinanceOfficer |
| POST | `/annuity-obligations/{obligationId}/deauthorize` | Withdraw an obligation's authorization | DocketingManager |
| POST | `/annuity-obligations/{obligationId}/instruct-payment` | Instruct payment of an authorized obligation | FinanceOfficer |
| POST | `/annuity-obligations/{obligationId}/raise-confirmation-query` | Raise a confirmation query on an instructed payment | FinanceOfficer |
| POST | `/annuity-obligations/{obligationId}/reinstruct` | Re-instruct after a confirmation query | FinanceOfficer |
| POST | `/annuity-obligations/{obligationId}/confirm-payment` | Confirm payment with the actual paid date | FinanceOfficer |
| POST | `/applications/{applicationId}/instructions` | Create an outside counsel instruction | DocketingClerk, DocketingManager |
| GET | `/applications/{applicationId}/instructions` | List an application's instructions | Any |
| GET | `/instructions/{instructionId}` | Get an instruction | Any |
| POST | `/instructions/{instructionId}/send` | Send an instruction | DocketingClerk |
| POST | `/instructions/{instructionId}/acknowledge` | Counsel acknowledges an instruction | OutsideCounsel |
| POST | `/instructions/{instructionId}/confirm` | Counsel confirms execution readiness | OutsideCounsel |
| POST | `/instructions/{instructionId}/decline` | Counsel declines an instruction | OutsideCounsel |
| POST | `/instructions/{instructionId}/complete` | Mark a confirmed instruction completed | DocketingClerk |
| POST | `/instructions/{instructionId}/cancel` | Cancel an unsent or sent instruction | DocketingClerk, DocketingManager |
| POST | `/applications/{applicationId}/abandonment-reviews` | Propose an abandonment review | DocketingManager |
| GET | `/applications/{applicationId}/abandonment-reviews` | List an application's abandonment reviews | Any |
| GET | `/abandonment-reviews/{reviewId}` | Get an abandonment review | Any |
| POST | `/abandonment-reviews/{reviewId}/submit` | Submit a proposed review | DocketingManager |
| POST | `/abandonment-reviews/{reviewId}/approve` | Approve a submitted review | DocketingManager |
| POST | `/abandonment-reviews/{reviewId}/reject` | Reject a submitted review | DocketingManager |
| POST | `/abandonment-reviews/{reviewId}/execute` | Execute an approved review | DocketingManager |
| POST | `/applications/{applicationId}/assignments` | Create an assignment record | RecordsSpecialist |
| GET | `/applications/{applicationId}/assignments` | List an application's assignment records | Any |
| GET | `/assignments/{assignmentId}` | Get an assignment record | Any |
| POST | `/assignments/{assignmentId}/execute` | Execute an assignment | RecordsSpecialist |
| POST | `/assignments/{assignmentId}/record` | Record an executed assignment against the register | RecordsSpecialist |
| POST | `/assignments/{assignmentId}/record-rejection` | Record a register rejection | RecordsSpecialist |
| POST | `/applications/{applicationId}/audits` | Open a docket audit against a register snapshot | DocketingClerk, DocketingManager |
| GET | `/applications/{applicationId}/audits` | List an application's audits | Any |
| GET | `/audits/{auditId}` | Get an audit | Any |
| POST | `/audits/{auditId}/resolve` | Resolve a variance-found audit | DocketingManager |
| POST | `/audits/{auditId}/close` | Close a clean audit | DocketingManager |
| GET | `/contacts` | List contacts across the portfolio | Any |
| GET | `/inventors` | List inventors across the portfolio | Any |
| GET | `/families` | List families across the portfolio | Any |
| GET | `/docket-entries` | List docket entries across the portfolio | Any |
| GET | `/office-actions` | List office actions across the portfolio | Any |
| GET | `/annuity-obligations` | List annuity obligations across the portfolio | Any |
| GET | `/authorizations` | List payment authorizations across the portfolio | Any |
| GET | `/instructions` | List instructions across the portfolio | Any |
| GET | `/abandonment-reviews` | List abandonment reviews across the portfolio | Any |
| GET | `/assignments` | List assignment records across the portfolio | Any |
| GET | `/audits` | List docket audits across the portfolio | Any |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions under which each error is raised are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_COUNSEL_NOT_ACCREDITED` | 422 Unprocessable Entity |
| `ERR_PRIORITY_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_SURCHARGE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_AUDIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INSTRUCTION_EXCLUSIVE_CONFLICT` | 409 Conflict |
| `ERR_EXTENSION_NOT_ALLOWED_TYPE` | 422 Unprocessable Entity |
| `ERR_EXTENSION_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_APPLICATION_NUMBER` | 409 Conflict |
| `ERR_PARENT_APPLICATION_LAPSED` | 422 Unprocessable Entity |
| `ERR_PARENT_FAMILY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PRIORITY_CHAIN_CYCLE` | 422 Unprocessable Entity |
| `ERR_PARENT_NOT_PCT` | 422 Unprocessable Entity |
| `ERR_REVIEW_ALREADY_OPEN` | 409 Conflict |
| `ERR_ENTRY_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_INVENTOR_CLIENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_AUTHORIZATION_NOT_RELEASED` | 409 Conflict |
| `ERR_ASSIGNMENT_RECORDATION_REQUIRED` | 409 Conflict |
| `ERR_COUNSEL_INSTRUCTION_REQUIRED` | 409 Conflict |
| `ERR_FAMILY_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CLIENT_SUSPENDED` | 409 Conflict |
| `ERR_FAMILY_HAS_APPROVED_REVIEWS` | 409 Conflict |
| `ERR_FAMILY_HAS_OPEN_APPLICATIONS` | 409 Conflict |
| `ERR_FAMILY_NOT_IN_PRUNING_REVIEW` | 409 Conflict |
| `ERR_APPLICATION_NOT_OPEN` | 409 Conflict |

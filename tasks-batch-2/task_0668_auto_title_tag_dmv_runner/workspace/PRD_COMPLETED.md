# Auto Title & Tag DMV Runner API — Product Requirements Document

## 1. Introduction

The Auto Title & Tag DMV Runner service exists to take the friction out of the most paperwork-heavy moment of vehicle ownership. When a customer needs a new title issued, a registration renewed, a title transferred between owners, or a security interest recorded, our operations staff collect and verify the supporting documents, price the transaction against the governing state fee schedule, file it physically at the correct Department of Motor Vehicles office via a routed runner, and chase rejected filings through rework until they are accepted. This API is the system of record behind that operation: it tracks every transaction through its workflow, computes the quoted and final fees, orchestrates the dispatch queue of physical runner trips to DMV offices, perfects lender lien packets, and reconciles the money owed by each customer account.

The domain naturally splits across several specialist roles, and the platform is built around that division of labor. Intake staff own document collection and submission; pricing analysts own the fee math and the moment a transaction is settled; a dispatch desk owns the physical logistics of getting filings to a DMV office and recording the outcome; and a separate lien officer perfects lender packets under a strict segregation-of-duties rule. Layered on top are two customer profiles — straightforward retail customers who prepay, and business or fleet accounts that may run a postpaid balance and earn volume discounts as they push more work through the system. A single platform administrator configures fee schedules, opens accounts, and drives the logical clock and fee periods that the rest of the system reads.

All resources in this API are mounted under the `/dmv` path prefix. The sections below define the global contract every endpoint obeys, the business rules that govern each workflow, and the complete endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and contractual boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly six roles, spelled precisely as follows: `PlatformAdmin`, `IntakeClerk`, `FeeAnalyst`, `RunnerDispatcher`, `LienOfficer`, and `AccountHolder`. These are peer roles: each owns a distinct slice of the workflow rather than sitting in a strict hierarchy. A `PlatformAdmin` is the operational superset for configuration — fee schedules, accounts, the logical clock, and fee-period advances — and may read everything. An `IntakeClerk` owns intake: opening transactions, uploading and verifying documents, and submitting or rework-resubmitting. A `FeeAnalyst` owns pricing: computing estimate quotes and completing transactions. A `RunnerDispatcher` owns the runner queue: building trips, attaching legs, dispatching, returning, closing, and recording DMV decisions. A `LienOfficer` owns lien perfection and is deliberately kept separate from the clerk who submitted the transaction. An `AccountHolder` is the customer.

Five of the six roles carry an **opaque** identity. When `X-User-Role` is `PlatformAdmin`, `IntakeClerk`, `FeeAnalyst`, `RunnerDispatcher`, or `LienOfficer`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier — for example, the submitting clerk's `X-User-ID` is stamped onto a transaction as `submitted_by_user_id` when it is submitted, and the perfecting officer's `X-User-ID` is recorded as `perfected_by_user_id` on a lien packet — but it never compares that identifier to any entity's `id`. The lone exception is the customer: when `X-User-Role` is `AccountHolder`, the `X-User-ID` is the `id` of the acting `Account`. Ownership checks on any resource that references an `Account` compare the resource's account foreign key to `X-User-ID`. Concretely, an `AccountHolder` acting on a transaction must own it — the transaction's `account_id` must equal the caller's `X-User-ID` — and a violation is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership rule guards transaction cancellation and the recording of account payments.

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

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` or `offset` outside its permitted range is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Almost every resource in the system carries a standard set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification, and the `version` field is an integer that starts at its initial value and increments by one on every mutation of the resource. These standard fields are present on the `Account`, `FeeSchedule`, `Transaction`, `DocumentItem`, `FeeQuote`, `Submission`, `RunnerTrip`, `RunnerLeg`, and `LienPacket` resources.

The `Payment` resource is the exception. A payment is immutable once recorded, so it carries only an `id` (UUID) and a `created_at` timestamp; it has neither an `updated_at` field nor a `version` field. Implementations must not invent those two fields for payments.

The platform runs on a **logical clock** rather than wall-clock time. At server startup the clock reads exactly `2026-04-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real-world time. A `PlatformAdmin` advances the clock by supplying a target instant in the `to_iso8601` field. Every time-dependent computation in the system — SLA deadlines and SLA-window checks in particular — reads "now" from this logical clock. The logical clock governs only those domain computations; server-managed record timestamps (`created_at`, `updated_at`) and the envelope's `api_request_timestamp` are stamped from real wall-clock UTC and are unaffected by clock-setting calls.

### 2.5. Hierarchical Consistency, Derived Fields, and Concurrency

Many operations in this system mutate more than one resource at once. The guiding principle is immediate consistency: when one operation has downstream effects, those effects are applied within the same request, and each mutated resource independently refreshes its `updated_at` and increments its `version`. For example, recording a DMV decision mutates the `Submission`, resolves the attached `RunnerLeg`, and reflects a state change onto the `Transaction`; completing a transaction mutates the `FeeQuote`, the `Transaction`, and the owning `Account`. Each such ripple is spelled out in the relevant workflow narrative in §3.

Two denormalized fields are reconciled rather than directly set by clients. An account's `outstanding_balance_cents` is recomputed from the underlying payments and settled quotes whenever a transaction is completed, a payment is recorded, or a refund is issued. A trip's `assigned_leg_count` is reconciled on every leg attach so it always equals the number of legs currently attached to that trip. Because these are derived, clients never write them directly.

The system enforces **optimistic concurrency control** on two specific write operations, each guarded by a non-optional version field in the request body. First, attaching a leg to a runner trip requires `expected_runnertrip_version`, which must carry the client's last observed `version` of the target `RunnerTrip`; if a prior leg attach has advanced the trip's `version` since the dispatcher last read it, the attach is rejected with `ERR_STALE_VERSION` (HTTP 412), so two attaches cannot both believe they took the last free capacity slot. Second, generating a new fee quote requires `expected_transaction_version`, which must carry the client's last observed `version` of the target `Transaction`; if another writer has advanced the transaction's `version` since the analyst last read it — for instance because its `rejection_round` or `document_status` moved underneath them — the quote is rejected with `ERR_STALE_VERSION` (HTTP 412), so the surcharge inputs the quote freezes are never computed against an outdated snapshot. No other endpoint accepts or requires a version field; only these two carry an OCC guard.

### 2.6. Nested Resource Retrieval and Validation Ordering

Resource URLs are flat collections (for example, a single transaction is addressed directly by its identifier), but several read and write paths still embed a parent identifier followed by a sub-collection — fetching the documents, fee quotes, submissions, or lien packets of a given transaction, or the legs of a given trip. For any such request, path-referenced resources are validated left-to-right: the parent identifier in the path is checked first, and only then are body foreign-key references resolved. A missing path or body reference yields `ERR_NOT_FOUND` (HTTP 404).

Validation across the whole API follows a fixed priority order, so that when several conditions could fail, the earliest-priority one is the one reported. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of referenced resources (`ERR_NOT_FOUND`), then resource ownership for an `AccountHolder` (`ERR_NOT_RESOURCE_OWNER`), then whether the target resource is in a state from which the requested transition is legal (`ERR_INVALID_STATE`). State-machine eligibility for the lifecycle, document, trip, submission, and packet dimensions is therefore evaluated before any domain-specific business rule that follows it. The remaining business rules — described in their natural workflow homes in §3 — are layered after these, in the priority order their narratives imply.

### 2.7. Money, Precision, and Rounding

All monetary amounts in the system are integers expressed in whole cents; there are no fractional-cent values stored or returned. Tax rates and fleet discounts are expressed in **basis points**, where 10,000 basis points equal one whole multiplier (that is, a rate is applied by multiplying by the basis-point figure and dividing by 10,000). Two — and only two — lines within a fee quote are produced by rounding: the tax line and the service-fee line, each rounded half-up to a whole cent. The quote total is then formed as the integer sum of three already-whole-cent lines and is never rounded a second time. The precise composition of each line is given in §3.5 and §3.6. Derived balances are clamped so they never fall below zero.

### 2.8. Transaction Status Dimensions

A `Transaction` is tracked along two independent status dimensions at once, and implementations must keep them separate. The `lifecycle_status` is the primary workflow dimension and is one of `DRAFT`, `QUOTED`, `SUBMITTED`, `REJECTED`, `APPROVED`, `COMPLETED`, or `CANCELLED`; it begins at `DRAFT`, and `COMPLETED` and `CANCELLED` are terminal. The `document_status` is a parallel dimension tracking document collection and is one of `COLLECTING`, `VERIFIED`, or `INCOMPLETE`; it begins at `COLLECTING`. These two dimensions advance on different triggers and interact only where §3 explicitly says so (for example, a DMV rejection both moves the lifecycle back to `REJECTED` and resets the document dimension to `INCOMPLETE`).

### 2.9. Enumerations

Every enumerated value below appears exactly as written. An account's `account_type` is `RETAIL` or `FLEET`, and its `status` is `ACTIVE` or `SUSPENDED`. A fee schedule's `status` is `ACTIVE` or `SUPERSEDED`. A transaction's `transaction_type` is `TITLE`, `REGISTRATION`, `TRANSFER`, or `LIEN`. A document's `checklist_code` is one of `TITLE_CERT`, `BILL_OF_SALE`, `ODOMETER`, `ID_PROOF`, `INSURANCE`, `LIEN_RELEASE`, `LIEN_INSTRUMENT`, or `POWER_OF_ATTORNEY`, and its `doc_status` is `PENDING`, `VERIFIED`, or `REJECTED`. A fee quote's `variant` is `ESTIMATE` or `FINAL`, and its `status` is `ACTIVE`, `SUPERSEDED`, or `SETTLED`. A submission's `submission_status` is `QUEUED`, `ASSIGNED`, `ACCEPTED`, `DMV_REJECTED`, or `SUPERSEDED`, and its `priority_class` is `EXPEDITE` or `STANDARD`. A trip's `trip_status` is `PLANNED`, `DISPATCHED`, `RETURNED`, or `CLOSED`. A leg's `leg_status` is `ATTACHED`, `FILED`, or `RESOLVED`. A lien packet's `packet_status` is `DRAFT`, `PERFECTED`, or `VOIDED`. A payment's `kind` is `CHARGE` or `REFUND`. Submitting an unrecognized enum value for any of these is a malformed request rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Accounts, Fee Schedules, and the Configuration Backbone

Before any transaction can be priced, a `PlatformAdmin` must establish the configuration backbone. Accounts are opened with an `account_type` of either `RETAIL` or `FLEET`, a `legal_name`, and a two-letter `state_code` that names the US state the account is domiciled in; that state code drives which tax and fee schedule applies and must match the `state_code` of a currently `ACTIVE` fee schedule (a state with only `SUPERSEDED` schedules, or none at all, does not qualify); a state code that matches no `ACTIVE` schedule is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A new account begins with `status` set to `ACTIVE`, and both its `ytd_completed_count` and `outstanding_balance_cents` start at zero. Two further inputs govern credit: `credit_terms` is a boolean that defaults to false, and `credit_limit_cents` defaults to zero, must be zero or greater (a negative value fails the typed constraint and is rejected with `ERR_VALIDATION`, HTTP 422), and is ignored unless credit terms are in effect. Only fleet accounts may run a postpaid balance — when `credit_terms` is true the account may carry an outstanding balance up to its credit limit — whereas retail accounts must prepay.

An account's `status` is a computed reflection of its financial health. It is `ACTIVE` on creation, moves to `SUSPENDED` when its `outstanding_balance_cents` exceeds its `credit_limit_cents`, and returns to `ACTIVE` only when a `PlatformAdmin` reinstates it. Reinstatement refreshes `updated_at` and bumps the account's `version`.

Fee schedules are the pricing reference for a state. A `PlatformAdmin` publishes a schedule by supplying the `state_code` it governs, four flat fees — `title_fee_cents`, `registration_fee_cents`, `transfer_fee_cents`, and `lien_recording_fee_cents` — a `use_tax_rate_bps` value (the sales/use tax rate in basis points, which must be zero or greater — a negative value fails the typed constraint and is rejected with `ERR_VALIDATION`, HTTP 422), and an optional `trade_in_credit_allowed` boolean that defaults to true. The lien recording fee is the flat fee added when a lien is being perfected. A schedule's `status` is `ACTIVE` on creation; publishing a newer schedule for the same `state_code` moves any prior schedule for that state to `SUPERSEDED`, so that at most one schedule per state is `ACTIVE` at a time. The four flat fees and the tax rate together feed the fee calculation described in §3.5 and §3.6.

The administrator also controls two time-like levers. The logical clock is set as described in §2.4 by supplying a `to_iso8601` instant. Separately, advancing the **fee period** is the volume-discount reset event: it sets every account's `ytd_completed_count` back to zero and bumps each account's `version`. Two test-driving capabilities let an operator shortcut otherwise-lengthy setups: one directly sets a target account's `ytd_completed_count` to a supplied value (identified by `account_id` and the target `ytd_completed_count`), recomputes that account's fleet-tier eligibility, bumps its `version`, and returns the updated account; the other directly sets a target transaction's `rejection_round` (identified by `transaction_id` and the target `rejection_round`), bumps the transaction's `version`, and returns the updated transaction. Each supplied target must be a non-negative integer; a negative value fails the typed constraint and is rejected with `ERR_VALIDATION` (HTTP 422), and a target `account_id` or `transaction_id` that names no existing entity is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 3.2. Opening a Transaction and Collecting Documents

An `IntakeClerk` opens a transaction by naming the owning `account_id`, the `transaction_type`, the 17-character `vin`, and optionally the `declared_price_cents`, the `trade_in_allowance_cents`, and the `expedite` flag. A newly opened transaction begins with `lifecycle_status` of `DRAFT` and `document_status` of `COLLECTING`. The `expedite` flag defaults to false and signals that the customer has purchased priority handling, an SLA, and a surcharge. Both money inputs default to zero.

At creation the transaction's fields are validated together. The VIN must be exactly 17 characters long. The declared price must be greater than zero for a `TITLE` or `TRANSFER` transaction and must be exactly zero for a `REGISTRATION` or `LIEN` transaction. The `trade_in_allowance_cents` may not exceed `declared_price_cents`. Any of these failing rejects creation with `ERR_INVALID_TRANSACTION_FIELDS` (HTTP 422). Separately, a negative `trade_in_allowance_cents` fails the typed non-negative constraint and is rejected with `ERR_VALIDATION` (HTTP 422), checked after the exceed-declared-price rule.

Documents are uploaded individually. An `IntakeClerk` uploads a `DocumentItem` by supplying the owning `transaction_id`, the `checklist_code` slot it fills, and an opaque `file_ref` pointing at the stored file; a freshly uploaded document has `doc_status` of `PENDING`. The clerk then renders a decision on each document, supplying a `decision` whose value is one of the literal tokens `VERIFIED`, `REJECTED`, or `RESET` (any other value is a malformed request rejected with `ERR_INVALID_REQUEST`, HTTP 400). Verifying moves a `PENDING` document to `VERIFIED`; rejecting moves it to `REJECTED` (for example, when the scan is illegible); and a reset moves a `REJECTED` document back to `PENDING` after the customer re-uploads. Each of these is itself a state-machine transition: verifying or rejecting is permitted only from `PENDING`, and resetting only from `REJECTED`, with any other source state rejected with `ERR_INVALID_STATE` (HTTP 409). Each such decision bumps the document's `version`, and every one of these document decisions is permitted only while the owning transaction's `lifecycle_status` is `DRAFT`, `QUOTED`, or `REJECTED`.

Which documents a transaction actually needs depends on its type — the checklist is **polymorphic** on `transaction_type`. A `TITLE` transaction requires `TITLE_CERT`, `BILL_OF_SALE`, `ODOMETER`, and `ID_PROOF`. A `REGISTRATION` transaction requires `ID_PROOF` and `INSURANCE`. A `TRANSFER` transaction requires `TITLE_CERT`, `BILL_OF_SALE`, and `ID_PROOF`. A `LIEN` transaction requires `LIEN_INSTRUMENT` and `ID_PROOF`. Documents uploaded beyond the required set are simply ignored when judging completeness.

The clerk asks the system to evaluate the checklist as a discrete step, permitted only while the `document_status` is `COLLECTING` or `INCOMPLETE`; evaluating a transaction whose `document_status` is already `VERIFIED` is rejected with `ERR_INVALID_STATE` (HTTP 409). That evaluation drives the `document_status` dimension and is deterministic: the same set of documents always yields the same outcome. From `COLLECTING`, the transaction moves to `VERIFIED` when every required `checklist_code` for the transaction's type has a `DocumentItem` whose `doc_status` is `VERIFIED` and no document on the transaction is `REJECTED`; otherwise — if at least one required `checklist_code` is missing, or any required document is still `PENDING` or is `REJECTED` — it moves to `INCOMPLETE`. The same two outcomes apply when re-evaluating from an `INCOMPLETE` state after missing or replacement documents are uploaded: it reaches `VERIFIED` only once every required slot has a `VERIFIED` document and none is `REJECTED`. Each evaluation refreshes the transaction's `version`. (A `VERIFIED` document dimension can later be knocked back to `INCOMPLETE` by a DMV rejection, as described in §3.4.)

### 3.3. Pricing: Estimate Quotes and the Quote History

Pricing is the `FeeAnalyst`'s domain. From a `DRAFT` transaction, the analyst computes the first **estimate** quote, which advances the lifecycle to `QUOTED`; from a `QUOTED` transaction, the analyst may recompute, leaving the lifecycle at `QUOTED`; and from a `REJECTED` transaction, the analyst may recompute the re-run estimate that rework requires (§3.4), leaving the lifecycle at `REJECTED`. A quote is permitted only while the transaction's `lifecycle_status` is `DRAFT`, `QUOTED`, or `REJECTED`. In each case the request must carry `expected_transaction_version` matching the transaction's current `version` per the OCC rule in §2.5. Each quote computation produces a new `FeeQuote` whose `variant` is `ESTIMATE` and whose `status` is `ACTIVE`, sets any previously `ACTIVE` quote for that transaction to `SUPERSEDED`, and updates the transaction's `active_quote_id` to point at the new quote. Quoting requires that an `ACTIVE` fee schedule exist for the owning account's `state_code`; if none does, the quote is rejected with `ERR_INVALID_STATE` (HTTP 409). Computing the first quote increments the transaction's `version`; recomputing does likewise.

A fee quote captures its component breakdown. It records the `transaction_id` it prices, the `variant`, and a `schedule_id` — a denormalized version-pin pointing at the exact fee-schedule version that was frozen at the moment the quote was computed. Its money components are `tax_cents` (the computed use/sales tax), `state_fees_cents` (the sum of the applicable flat state fees), `service_fee_cents` (the runner service fee after surcharges and any fleet discount), and `total_cents` (the sum of those three). The arithmetic that fills these fields is laid out in §3.5 and §3.6.

The full history of quotes for a transaction — both estimate iterations and the eventual final quote — is retrievable as a list, and the transaction's `active_quote_id` is null until the first quote is produced. Because quotes are discovered through that list rather than through a nested child path, the `active_quote_id` is a pointer, not a parent-child key.

### 3.4. Submission, the Runner Queue, and DMV Decisions

Once documents are verified and a quote is in hand, an `IntakeClerk` submits the transaction to the DMV. Submission is permitted only when the transaction's `lifecycle_status` is `QUOTED` or `REJECTED` (the latter is the rework path of the next paragraph), its `document_status` is `VERIFIED`, its `active_quote_id` is not null, and the owning account's `status` is `ACTIVE`; submitting when the `document_status` is not `VERIFIED` or when `active_quote_id` is null is rejected with `ERR_DOCUMENTS_INCOMPLETE` (HTTP 409), whereas an owning account whose `status` is not `ACTIVE` is rejected with `ERR_INVALID_STATE` (HTTP 409). Submitting advances the lifecycle from `QUOTED` to `SUBMITTED`, creates a `Submission` with `submission_status` of `QUEUED`, stamps the submitting clerk's `X-User-ID` onto the transaction as `submitted_by_user_id` (the anchor for the later segregation-of-duties check), and increments the transaction's `version`. The new submission's `priority_class` is derived from the transaction's `expedite` flag: `EXPEDITE` when expedited, otherwise `STANDARD`. When the submission is expedited, its `sla_deadline_at` is set to the logical clock's current instant plus the expedite SLA window of 48 hours, rendered as an ISO 8601 UTC timestamp with three fractional digits (the same format as `created_at`); for a standard submission `sla_deadline_at` is null.

The `RunnerDispatcher` runs the physical queue. A trip is created for a particular `dmv_office_code` over a planned window defined by `window_start_at` and `window_end_at`, with a `capacity` of at least one leg; a new trip begins with `trip_status` of `PLANNED` and an `assigned_leg_count` of zero, and `window_end_at` must be strictly after `window_start_at`. A `capacity` below one fails the typed constraint and is rejected with `ERR_VALIDATION` (HTTP 422). The trip's occupation interval is the **half-open** interval running from `window_start_at` up to but not including `window_end_at`: a new trip to the same `dmv_office_code` is rejected with `ERR_TRIP_WINDOW_OVERLAP` (HTTP 409) if its half-open window overlaps that of any existing trip to the same office whose `trip_status` is `PLANNED`, `DISPATCHED`, or `RETURNED`. Because the interval is half-open, a trip that begins exactly when another ends does not overlap and is allowed.

Attaching a submission to a trip creates a `RunnerLeg`. The dispatcher names the `submission_id` to attach and supplies `expected_runnertrip_version` for the OCC guard of §2.5. The attach is permitted only when the submission's `submission_status` is `QUEUED` and the target trip's `trip_status` is `PLANNED`. Several guards fire here in addition to the stale-version check: if the submission is expedited, attaching is allowed only while the logical clock's current instant is strictly before the submission's `sla_deadline_at`, and attaching at or after that deadline is rejected as an expired window with `ERR_SLA_EXPIRED` (HTTP 409); and the attach is rejected with `ERR_TRIP_AT_CAPACITY` (HTTP 409) when the trip's `assigned_leg_count` is already at or above its `capacity` (an attach is only allowed while the count is strictly less than capacity). A successful attach creates the leg with `leg_status` of `ATTACHED`, assigns its `sequence_index` by queue priority and then by creation time ascending so that lower indices file first, marks the submission `ASSIGNED` and records the chosen leg on the submission via `leg_id`, increments the trip's `assigned_leg_count` by one, and increments the trip's `version`. Each leg records the `trip_id` of the trip carrying it and the `submission_id` it files, and the legs of a trip can be listed in `sequence_index` order or filtered across the system by `trip_id` or `submission_id`.

The trip then moves through a fork-join lifecycle driven by the dispatcher. Dispatching a `PLANNED` trip that carries at least one leg fans out: every attached leg advances to `FILED`, the trip moves to `DISPATCHED`, and the trip's `version` increments. Returning a `DISPATCHED` trip moves it to `RETURNED` so that per-leg DMV decisions can be recorded, again bumping the trip's `version`. Closing a `RETURNED` trip moves it to `CLOSED` and bumps its `version`, but is permitted only once every attached leg's `leg_status` is `RESOLVED` — the join condition that all branches have completed.

DMV outcomes are recorded one submission at a time, and a decision may only be taken once the submission is `ASSIGNED` and its leg's trip has reached `RETURNED`; recording a decision before the trip is returned is rejected with `ERR_TRIP_NOT_RETURNED` (HTTP 409). The dispatcher supplies an `outcome` whose value is one of the literal tokens `ACCEPTED` (acceptance) or `DMV_REJECTED` (rejection); any other value is a malformed request rejected with `ERR_INVALID_REQUEST` (HTTP 400). On an accepting decision, the submission moves to `ACCEPTED`, its leg becomes `RESOLVED`, and the result reflects onto the transaction by advancing its lifecycle from `SUBMITTED` to `APPROVED` (a `DRAFT` lien packet, if one exists, is left in `DRAFT` to await perfection), incrementing the transaction's `version`. On a rejecting decision a `rejection_reason` must be provided (and is stored on the submission); the submission moves to `DMV_REJECTED`, its leg becomes `RESOLVED`, and the rejection cascades onto the transaction: the lifecycle moves from `SUBMITTED` back to `REJECTED`, the transaction's `rejection_round` increments by one, its `document_status` is forced to `INCOMPLETE` so the documents must be re-verified for rework, and its `version` increments. That bump to `rejection_round` is the origin of a downstream pricing change — the next quote will carry a larger rework surcharge, as §3.5 describes.

A rejected transaction can be reworked. An `IntakeClerk` rework-resubmits only when the transaction's `lifecycle_status` is `REJECTED`, its `document_status` has returned to `VERIFIED`, a re-run quote reflecting the current `rejection_round` surcharge exists, and the `rejection_round` is strictly less than the rework cap of three rounds; a resubmit attempted at or above three rounds is rejected with `ERR_REWORK_LIMIT_REACHED` (HTTP 409). A successful rework supersedes the prior submission (setting its `submission_status` to `SUPERSEDED`), creates a fresh `QUEUED` submission, advances the lifecycle from `REJECTED` back to `SUBMITTED`, and increments the transaction's `version`. This `REJECTED → SUBMITTED` edge is the rework loop. If, however, a `DMV_REJECTED` decision is recorded at the moment the transaction's `rejection_round` reaches the cap of three, the system auto-cancels the transaction: the lifecycle moves to `CANCELLED`, any `DRAFT` lien packet is voided to `VOIDED`, and the transaction's `version` increments.

### 3.5. Fee Composition: Tax, State Fees, and the Service Fee

Every quote — estimate or final — is built in a fixed five-step order: first the taxable base, then the tax, then the state fees, then the service fee with its fleet discount and surcharges, and finally the total. The governing fee schedule is the `ACTIVE` schedule for the account's `state_code`, and the version used is pinned onto the quote as `schedule_id`.

The taxable base applies only to `TITLE` and `TRANSFER` transactions; for `REGISTRATION` and `LIEN` the base is zero. For a taxable transaction the base starts as the `declared_price_cents`. When the governing schedule's `trade_in_credit_allowed` is true, the base is instead the declared price minus the `trade_in_allowance_cents`, floored at zero so it can never go negative; when trade-in credit is not allowed in that state, the trade-in allowance does not reduce the base. The tax line, `tax_cents`, is the base multiplied by the schedule's `use_tax_rate_bps` and divided by 10,000, with that single line rounded half-up to whole cents.

The state-fee line, `state_fees_cents`, is the sum of the flat fees that apply to the transaction's type: the schedule's `title_fee_cents` for a `TITLE`, its `transfer_fee_cents` for a `TRANSFER`, its `registration_fee_cents` for a `REGISTRATION`, and, for a `LIEN` transaction — or for any transaction that has a lien packet associated with it whose `packet_status` is not `VOIDED` — the schedule's `lien_recording_fee_cents`. Each transaction type contributes its single matching flat fee, with the lien recording fee added on top whenever a lien is in play; a packet in any state other than `VOIDED` (that is, `DRAFT` or `PERFECTED`) counts as a lien in play, while a `VOIDED` packet does not.

The service fee is where surcharges and the fleet discount combine, and the rounding order is mandatory. Begin with a base service fee of 4,500 cents. If the transaction is expedited, add an expedite surcharge of 6,000 cents. Then add the rework surcharge, which is 2,500 cents multiplied by the transaction's `rejection_round` (so a transaction on its second rejection round carries 5,000 cents of rework surcharge, and a never-rejected transaction carries none). These three components are summed first, while still undiscounted, into a single pre-discount service amount. The fleet volume discount (§3.6) is then applied to that whole sum as a single basis-point rate, and the discounted amount is rounded half-up to a whole cent exactly once. This sum-then-round order is required: rounding each surcharge line separately and then summing is forbidden, because at fractional discount tiers it produces a different final cent. The result is `service_fee_cents`.

Finally, `total_cents` is the integer sum of the three already-whole-cent lines — `tax_cents` plus `state_fees_cents` plus `service_fee_cents` — with no further rounding applied.

### 3.6. The Fleet Volume Discount

The fleet volume discount rewards business accounts for throughput, and it is keyed entirely on the count of transactions the account has completed in the current fee period, `ytd_completed_count`. A retail account never receives a discount: the discount rate is zero basis points whenever the account's `account_type` is not `FLEET`. For a fleet account, the rate is selected by tier using at-or-above thresholds: a count of at least 50 completed transactions earns 1,875 basis points (18.75%); a count of at least 20 but below 50 earns 1,250 basis points (12.5%); a count of at least 5 but below 20 earns 625 basis points (6.25%); and a count below 5 earns no discount. The thresholds are inclusive at their lower edge — a count of exactly 5 already qualifies for the first tier, while a count of 4 earns nothing — and the discount is a single flat rate applied to the entire pre-discount service-fee sum, not a marginal rate layered across tiers.

The estimate quote and the final quote differ in exactly which count they feed into this tier selection, and in which fee schedule they pin. An **estimate** quote uses the account's `ytd_completed_count` exactly as it stands at quote time, and its rework component reflects the transaction's current `rejection_round`; the resulting quote has `variant` of `ESTIMATE` and `status` of `ACTIVE`. The **final** quote, computed when a transaction is completed, runs the same five-step arithmetic but selects the fleet tier from the account's `ytd_completed_count` as it stands before this completion's increment — the transaction being completed must not discount itself — and freezes the rework component at the final `rejection_round`. The final quote also re-pins the governing fee schedule by re-reading the `ACTIVE` schedule at completion time, which may differ from the schedule the estimate froze if a newer schedule was published in between; consequently the same transaction can yield a different final total than its estimate. The final quote has `variant` of `FINAL` and `status` of `SETTLED`.

### 3.7. Completion, Settlement, and Account Reconciliation

Completing a transaction is the `FeeAnalyst`'s closing act and is permitted only when the transaction's `lifecycle_status` is `APPROVED`. If the transaction's `transaction_type` is `LIEN`, completion additionally requires that the associated lien packet's `packet_status` already be `PERFECTED`; a `LIEN` transaction with no `PERFECTED` packet is rejected with `ERR_INVALID_STATE` (HTTP 409). Completion also requires an `ACTIVE` fee schedule for the owning account's `state_code`, and its absence is likewise rejected with `ERR_INVALID_STATE` (HTTP 409). Completion computes the final fee quote per §3.5 and §3.6, supersedes the `ACTIVE` estimate, records the new `FINAL` quote with `status` of `SETTLED`, repoints the transaction's `active_quote_id` at it, increments the owning account's `ytd_completed_count` by one, and advances the lifecycle from `APPROVED` to `COMPLETED`, incrementing the transaction's `version`.

Completion then reconciles the owning account's `outstanding_balance_cents`. That balance is a pure aggregation, order-independent: it is the sum of the `total_cents` of all `SETTLED` fee quotes belonging to the account's `COMPLETED` transactions, reduced by the sum of all `CHARGE` payments applied to the account and restored by the sum of all `REFUND` payments, with the result clamped so it never falls below zero. For a postpaid fleet account (one whose `credit_terms` is true), completion adds the settled total to the outstanding balance directly, and a later charge payment draws it back down. For a prepaid retail account (one whose `credit_terms` is false), a charge payment equal to the settled total must be recorded in the same exchange so that the outstanding balance nets back to zero immediately at completion. If completing a postpaid account's transaction would push its `outstanding_balance_cents` above its `credit_limit_cents`, the completion is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 409); otherwise, should the recomputed balance exceed the credit limit, the account's `status` is set to `SUSPENDED`.

Payments are recorded against an account by a `PlatformAdmin` or by the owning `AccountHolder`. A payment names the `account_id` it applies to, the `transaction_id` it settles, an `amount_cents`, and a `kind` of either `CHARGE` (which reduces the outstanding balance) or `REFUND` (which increases it, as compensation on cancellation). The amount must be at least one cent — an `amount_cents` below one fails the typed constraint and is rejected with `ERR_VALIDATION` (HTTP 422), checked before the transaction-state and amount-match rules. The referenced transaction must then be `COMPLETED`, and the amount must equal the `total_cents` of that transaction's `SETTLED` fee quote; a transaction that is not `COMPLETED`, the absence of a `SETTLED` quote, or an amount that does not equal that settled total is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). Either `kind` is accepted for an account regardless of its terms — the system does not reject a `CHARGE` or `REFUND` on the basis of whether the account is prepaid or postpaid. Recording a payment recomputes the account's `outstanding_balance_cents` and bumps the account's `version`, but does not by itself flip a `SUSPENDED` account back to `ACTIVE` even when the recomputed balance no longer exceeds the credit limit; a `SUSPENDED` account returns to `ACTIVE` only through an explicit `PlatformAdmin` reinstatement.

### 3.8. Lien Perfection and Segregation of Duties

A lender packet captures the secured-lender side of a lien or title transaction. A `LienOfficer` or an `IntakeClerk` creates one by naming the owning `transaction_id`, the `lender_name`, and the `lien_amount_cents` (the principal, which must be at least one cent — a value below one fails the typed constraint and is rejected with `ERR_VALIDATION`, HTTP 422); a new packet begins with `packet_status` of `DRAFT`. The presence of a packet on a transaction also pulls the lien recording fee into the state-fee line, as noted in §3.5.

Perfection is reserved to a `LienOfficer` and is the enforcement point for **segregation of duties**. A packet may be perfected only when its owning transaction's `lifecycle_status` is `APPROVED` and that transaction's submission has reached `ACCEPTED`. Critically, the perfecting officer must not be the same person who submitted the transaction: the acting `X-User-ID` must differ from the transaction's `submitted_by_user_id`, and an attempt by the submitting user to perfect is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A successful perfection sets `packet_status` to `PERFECTED`, records the acting `X-User-ID` as `perfected_by_user_id`, and increments the packet's `version`. Only a `PERFECTED` packet satisfies the completion precondition for a `LIEN` transaction described in §3.7.

Packets are voided automatically when their transaction is cancelled. Any `DRAFT` packet is voided to `VOIDED` when its transaction transitions to `CANCELLED` — whether by an explicit cancel or by the rework auto-cancel — and a `PERFECTED` packet is voided to `VOIDED` specifically when a `COMPLETED` transaction is later cancelled.

### 3.9. Cancellation and Compensating Reversals

Cancellation is the `AccountHolder`'s prerogative over their own transactions, and it behaves differently depending on where the transaction sits in its lifecycle. From `DRAFT`, `QUOTED`, or `REJECTED`, cancelling moves the transaction to `CANCELLED`, sets the `ACTIVE` fee quote to `SUPERSEDED`, and voids any `DRAFT` lien packet to `VOIDED`, incrementing the transaction's `version`. Attempting any cancellation from a lifecycle state outside the permitted set is rejected with `ERR_INVALID_STATE` (HTTP 409).

A post-completion reversal is the more delicate path. A `COMPLETED` transaction may be cancelled only if a `CHARGE` payment exists for it, so that a compensating refund is possible; without such a charge the reversal is rejected with `ERR_NO_CHARGE_TO_REFUND` (HTTP 409). When the reversal proceeds, the system creates a `REFUND` payment for the settled total — which restores the account's `outstanding_balance_cents` to its pre-charge value, the compensating invariant that returns that transaction's net contribution to zero — decrements the owning account's `ytd_completed_count` by one to undo the completion's increment, voids any `PERFECTED` lien packet to `VOIDED`, and increments the transaction's `version`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource, drive a state transition, or perform a configuration action return a `200 OK` status code. The request body, response body, and side effects of each endpoint are not restated here — they are governed by the narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dmv/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/dmv/_fee-periods/advance` | Advance the fleet fee period; reset every account's completed count | PlatformAdmin |
| POST | `/dmv/_inject/account_counters` | Test-driving: set an account's completed count directly | PlatformAdmin |
| POST | `/dmv/_inject/rejection_round` | Test-driving: set a transaction's rejection round directly | PlatformAdmin |
| POST | `/dmv/fee-schedules` | Publish a fee schedule for a state | PlatformAdmin |
| GET | `/dmv/fee-schedules` | List fee schedules | PlatformAdmin, FeeAnalyst |
| GET | `/dmv/fee-schedules/{id}` | Fetch one fee schedule | PlatformAdmin, FeeAnalyst |
| POST | `/dmv/accounts` | Create a RETAIL or FLEET account | PlatformAdmin |
| GET | `/dmv/accounts/{id}` | Fetch an account with balance and counters | PlatformAdmin, FeeAnalyst, AccountHolder |
| POST | `/dmv/accounts/{id}/reinstate` | Reinstate a suspended account | PlatformAdmin |
| POST | `/dmv/accounts/{id}/payments` | Record a charge or refund payment | PlatformAdmin, AccountHolder |
| GET | `/dmv/payments` | List payments | PlatformAdmin, FeeAnalyst, AccountHolder |
| GET | `/dmv/payments/{id}` | Fetch one payment | PlatformAdmin, FeeAnalyst, AccountHolder |
| GET | `/dmv/transactions` | List transactions | PlatformAdmin, FeeAnalyst, IntakeClerk, AccountHolder |
| POST | `/dmv/transactions` | Open a transaction | IntakeClerk |
| GET | `/dmv/transactions/{id}` | Fetch a transaction | PlatformAdmin, FeeAnalyst, IntakeClerk, AccountHolder, RunnerDispatcher, LienOfficer |
| POST | `/dmv/transactions/{id}/quote` | Compute/refresh the estimate quote (OCC-guarded) | FeeAnalyst |
| POST | `/dmv/transactions/{id}/verify-documents` | Evaluate the document checklist | IntakeClerk |
| POST | `/dmv/transactions/{id}/submit` | Submit or rework-resubmit to the DMV | IntakeClerk |
| POST | `/dmv/transactions/{id}/complete` | Complete an approved transaction | FeeAnalyst |
| POST | `/dmv/transactions/{id}/cancel` | Cancel a transaction | AccountHolder |
| GET | `/dmv/transactions/{id}/fee-quotes` | List a transaction's fee quotes | PlatformAdmin, FeeAnalyst, AccountHolder |
| GET | `/dmv/transactions/{id}/documents` | List a transaction's documents | PlatformAdmin, FeeAnalyst, IntakeClerk, AccountHolder |
| GET | `/dmv/transactions/{id}/submissions` | List a transaction's submissions | PlatformAdmin, FeeAnalyst, IntakeClerk, RunnerDispatcher |
| GET | `/dmv/transactions/{id}/lien-packets` | List a transaction's lien packets | PlatformAdmin, FeeAnalyst, LienOfficer, AccountHolder |
| POST | `/dmv/documents` | Upload a document item | IntakeClerk |
| GET | `/dmv/documents/{id}` | Fetch a document item | PlatformAdmin, FeeAnalyst, IntakeClerk, AccountHolder |
| POST | `/dmv/documents/{id}/verify` | Verify, reject, or reset a document | IntakeClerk |
| GET | `/dmv/fee-quotes` | List fee quotes | PlatformAdmin, FeeAnalyst, AccountHolder |
| GET | `/dmv/fee-quotes/{id}` | Fetch one fee quote | PlatformAdmin, FeeAnalyst, AccountHolder |
| GET | `/dmv/submissions` | List submissions | PlatformAdmin, RunnerDispatcher, IntakeClerk |
| GET | `/dmv/submissions/{id}` | Fetch a submission | PlatformAdmin, RunnerDispatcher, IntakeClerk, FeeAnalyst |
| POST | `/dmv/submissions/{id}/decision` | Record the DMV decision | RunnerDispatcher |
| POST | `/dmv/runner-trips` | Create a runner trip | RunnerDispatcher |
| GET | `/dmv/runner-trips/{id}` | Fetch a runner trip | PlatformAdmin, RunnerDispatcher |
| POST | `/dmv/runner-trips/{id}/legs` | Attach a queued submission as a leg (OCC-guarded) | RunnerDispatcher |
| GET | `/dmv/runner-trips/{id}/legs` | List a trip's legs | PlatformAdmin, RunnerDispatcher |
| POST | `/dmv/runner-trips/{id}/dispatch` | Dispatch a planned trip | RunnerDispatcher |
| POST | `/dmv/runner-trips/{id}/return` | Mark a dispatched trip returned | RunnerDispatcher |
| POST | `/dmv/runner-trips/{id}/close` | Close a returned trip | RunnerDispatcher |
| GET | `/dmv/runner-legs` | List runner legs | PlatformAdmin, RunnerDispatcher |
| GET | `/dmv/runner-legs/{id}` | Fetch one runner leg | PlatformAdmin, RunnerDispatcher |
| POST | `/dmv/lien-packets` | Create a draft lien packet | LienOfficer, IntakeClerk |
| GET | `/dmv/lien-packets/{id}` | Fetch a lien packet | PlatformAdmin, LienOfficer, FeeAnalyst, AccountHolder |
| POST | `/dmv/lien-packets/{id}/perfect` | Perfect a draft lien packet | LienOfficer |
| GET | `/dmv/lien-packets` | List lien packets | PlatformAdmin, LienOfficer, FeeAnalyst, AccountHolder |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NO_CHARGE_TO_REFUND` | 409 Conflict |
| `ERR_DOCUMENTS_INCOMPLETE` | 409 Conflict |
| `ERR_TRIP_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SLA_EXPIRED` | 409 Conflict |
| `ERR_TRIP_AT_CAPACITY` | 409 Conflict |
| `ERR_REWORK_LIMIT_REACHED` | 409 Conflict |
| `ERR_TRIP_NOT_RETURNED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_INVALID_TRANSACTION_FIELDS` | 422 Unprocessable Entity |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_VALIDATION` | 422 Unprocessable Entity |

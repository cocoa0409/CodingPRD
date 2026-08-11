# Document Digitization & Scanning Bureau API — Product Requirements Document

## 1. Introduction

A document digitization bureau operates at the intersection of physical logistics and regulated data handling. Clients — hospitals, law firms, insurers, government offices — hand over bankers' boxes full of paper; the bureau intakes each box onto a tracked shelf, prepares and scans every page, indexes the resulting images with searchable metadata, delivers the digital corpus to the client through a controlled download channel, and finally disposes of the physical stock either by certified destruction or by return courier. Throughout that pipeline the bureau is accountable for a defensible chain of custody: at every moment it must be able to say which staffer touched which box, and for HIPAA-covered clients it must prove that no single individual ever authored two consecutive custody links on the same box, and that destruction was witnessed by a second staffer independent of the one who recorded it.

This document specifies the REST API that backs that operation. It covers client onboarding and service-agreement terms, batch and box intake, shelf-slot capacity management, scan-session bookkeeping with optimistic concurrency on the batch ledger, the quality-assurance rework loop, indexing with OCR-confidence gating, per-page invoicing with a provisional-versus-final pricing split, clock-driven disposition of retained stock, and client-facing access grants with vault-only restrictions for protected health information. The intended readers are the engineers implementing the service; every rule below is normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the acting user, and `X-User-Role` naming the acting role. A request missing either header, or carrying a role string outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint — or a `ClientUser` acting outside its own client subtree — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles are exactly: `PlatformAdmin`, `IntakeClerk`, `PrepTechnician`, `ScanOperator`, `QAReviewer`, `Indexer`, `DestructionSpecialist`, `ComplianceOfficer`, `BillingClerk`, and `ClientUser`.

For nine of the ten roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it (for example, as `actor_user_id` on a custody event or as `operator_id` on a scan session) but never compares it to any entity's `id`. This applies to `PlatformAdmin`, `IntakeClerk`, `PrepTechnician`, `ScanOperator`, `QAReviewer`, `Indexer`, `DestructionSpecialist`, `ComplianceOfficer`, and `BillingClerk`. The exception is `ClientUser`: when `X-User-Role` is `ClientUser`, `X-User-ID` is the `id` of the acting `Client`, and every ownership check on a resource that references a client compares the resource's `client_id` to `X-User-ID`. A `ClientUser` may read only its own client subtree and may act (request returns, create or revoke grants, download) only within it.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Non-integer values fall back to the defaults, and out-of-range values are clamped into range (`limit` below 1 becomes 1, above 100 becomes 100; `offset` below 0 becomes 0) rather than rejected. Results are always sorted by `created_at` ascending (ties — routine under the frozen logical clock — fall back to `id`, except that a box's custody trail is always emitted in the order its events were recorded). The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of returned items is still below `total_count`. Beyond the filters named in §4, the list endpoints for a client's batches, a client's access grants, a client's or a batch's invoices, a batch's boxes and scan sessions, a box's documents, and a box's or a slot's shelf assignments also accept an exact-match `status` query parameter.

### 2.4. Resource Identity and Common Properties

Most persisted resources carry four server-managed properties in addition to their domain fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, the same timestamp format refreshed on every mutation; and `version`, an integer that starts at 1 at creation and increments by exactly 1 on every mutation of the resource. Two resource kinds are deliberately append-only event logs and carry only `id` and `created_at`: a `PageLog` row and a `CustodyEvent` row have neither `updated_at` nor `version`.

### 2.5. The Logical Clock

The service never consults wall-clock time. All temporal behavior — storage-fee accrual, grant expiry, the disposition sweep, and every `started_at` / `ended_at` / `placed_at` / `released_at` / `issued_at` / `delivered_at` / `destroyed_at` timestamp — is driven by a single logical clock readable as `current_utc`. The clock's startup default, before anyone has set it, is exactly `2026-05-01T00:00:00Z`, and the server must not silently fall back to the host's wall clock.

A `PlatformAdmin` advances the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and sets `current_utc` to it, returning the new `current_utc` in the response. Advancing the clock is not a passive bookkeeping act: it fires the disposition sweep described in §3.7 for every batch whose `disposition_at` has been reached, and it is the reference instant against which grant `expires_at` and storage accrual are evaluated.

### 2.6. Monetary Precision and Rounding

All money is represented as integer cents; the API never emits fractional-cent amounts. Per-page pricing is computed by rounding each document's charge to cents first — the document's page count multiplied by the applicable per-page dollar rate, multiplied by 100, rounded half-up to the nearest integer — and only then summing those rounded per-document amounts across the document set. Summing first and rounding once at the end yields different cents and is incorrect. Storage fees are pure integer arithmetic over whole days and integer cent rates, so they require no rounding step at all.

### 2.7. Optimistic Concurrency Control on the Batch Ledger

Exactly one endpoint participates in optimistic concurrency control: committing a scan session. A commit request must carry `expected_batch_version`, a non-optional input field holding the batch `version` the client last observed. If that value does not equal the batch's current `version` — because another writer has advanced the batch since the client read it — the commit is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is persisted. No other endpoint accepts a version field.

### 2.8. Validation Ordering

When several validations could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic: first authentication (missing or malformed identity headers, `ERR_UNAUTHENTICATED`), then endpoint-level role permission (`ERR_FORBIDDEN`) — ClientUser subtree scoping, however, is evaluated only once the target resource has been loaded, so a nonexistent resource answers `ERR_NOT_FOUND` even to an out-of-subtree ClientUser — then existence and nesting of path-parameter ids (`ERR_NOT_FOUND`), then request-body well-formedness — required fields present, strings non-empty, types correct, enums within their declared sets, numeric ranges honored, and, on endpoints that declare a request-body schema, no unknown or server-computed keys in the payload (`ERR_INVALID_REQUEST`); bodyless action endpoints (the pipeline transitions, suspend/reactivate, return requests, custody-flag clearing, begin-destruction, mark-returned, assignment release, session void, invoice issue, grant revoke) accept and ignore any JSON object body. Ids referenced inside the request body (`client_id`, `scanner_id`, `shelf_slot_id`, `document_id`, `batch_id`) are validated where each workflow first needs them — always after body well-formedness, but in some workflows before and in others after the suspension and state checks below. After well-formedness comes client suspension (`ERR_CLIENT_SUSPENDED`), then temporal windows (`ERR_RETURN_WINDOW_EXPIRED` / `ERR_GRANT_EXPIRED`), then state-machine legality (`ERR_INVALID_STATE`, or `ERR_DOCUMENT_NOT_DELIVERED` on the download path), then optimistic concurrency on scan-session commit (`ERR_STALE_VERSION`), then the business-safety checks in the order custody segregation (`ERR_CUSTODY_SEGREGATION` / `ERR_WITNESS_SEGREGATION`), custody flag (`ERR_CUSTODY_FLAGGED`) — except that destruction-certificate recording checks the custody flag before the segregation checks — return commitment (`ERR_BOX_RETURN_COMMITTED` / `ERR_BOX_NOT_RETURN_COMMITTED`), and vault-zone / grant-channel / scope (`ERR_VAULT_ZONE_REQUIRED` / `ERR_GRANT_VAULT_ONLY` / `ERR_SCOPE_INSUFFICIENT`), then metadata completeness (`ERR_METADATA_INCOMPLETE`), then capacity and uniqueness ceilings (`ERR_EMPTY_SCAN_SESSION`, `ERR_SCANNER_OVER_CAPACITY`, `ERR_SHELF_OVER_CAPACITY`, `ERR_MAX_BOXES_EXCEEDED`, `ERR_RUSH_CAPACITY_FULL`, `ERR_SCANNER_UNAVAILABLE`, `ERR_SCANNER_BUSY`, `ERR_AGREEMENT_EXISTS`), and finally fiscal checks on payments (`ERR_PAYMENT_EXCEEDS_BALANCE`, `ERR_INVOICE_NOT_ISSUED`).

### 2.9. Nested Resources and Existence

Where a URL nests a resource under a parent, path parameters are validated left to right: each id must exist, and each child must actually belong to the named parent. A wrong-parent id is reported as `ERR_NOT_FOUND` (HTTP 404), never as a malformed-request 400. The same `ERR_NOT_FOUND` treatment applies to ids referenced in request bodies — `scanner_id`, `shelf_slot_id`, `document_id`, and `batch_id` must exist and belong to the operation's scope. Unknown paths, and methods not supported by a known path, are likewise answered with `ERR_NOT_FOUND` (HTTP 404).

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Service Agreements

A `PlatformAdmin` onboards a client by supplying the organization `name` and a `hipaa_covered` flag. The flag is not decorative: it drives vault-only shelf placement for PHI-bearing boxes, forces the `vault_only` computation on access grants, and sharpens the segregation-of-duties emphasis across the custody trail. A new client starts in `ACTIVE` status; the platform may later suspend it, moving the client to `SUSPENDED`, or reactivate it back to `ACTIVE`. Suspension is legal only from `ACTIVE` and reactivation only from `SUSPENDED`; any other attempt is rejected with `ERR_INVALID_STATE` (HTTP 409). While a client is `SUSPENDED`, every mutation on its subtree and every use of its access grants is rejected with `ERR_CLIENT_SUSPENDED` (HTTP 403) — with three exceptions that remain available during suspension: creating the client's service agreement, manually releasing a shelf assignment, and clearing a custody flag.

Each client is governed by at most one service agreement. The agreement creation payload carries `price_tier` (either `STANDARD` or `VOLUME`), a `rush_multiplier` applied to per-page rates for rush batches, `storage_free_days` of complimentary post-delivery storage, a `storage_daily_rate_cents` charge levied per box per day after the free window, `retention_days` after which physical disposition becomes mandatory, and `max_boxes_per_batch` capping batch intake. `rush_multiplier` accepts any JSON number; `storage_free_days`, `storage_daily_rate_cents`, and `retention_days` are integers of at least 0, and `max_boxes_per_batch` an integer of at least 1. Attempting to create a second agreement for a client that already has one is rejected with `ERR_AGREEMENT_EXISTS` (HTTP 409). Until a client has an agreement, batch intake for that client enforces no box ceiling, invoice-subtotal recomputation is skipped (subtotals keep their stored values), projected storage fees read as 0, and delivery treats `retention_days` as 0. Agreements are readable by `PlatformAdmin`, `BillingClerk`, and `ComplianceOfficer`.

### 3.2. Batch Intake and Box Shelving

An `IntakeClerk` opens a batch by naming the owning `client_id` and a `priority` of `STANDARD` or `RUSH`. The batch is born in `INTAKE` status, and two things happen alongside its creation. First, a `DRAFT` invoice is auto-created and linked one-to-one to the batch; it will accumulate page and storage charges as the pipeline runs. Second, when the requested priority is `RUSH`, an admission window is enforced: the bureau admits rush work only while the count of batches with `priority` `RUSH` sitting in `INTAKE`, `PREPPING`, `SCANNING`, `QA`, or `INDEXING` is strictly below the rush admission limit of 3. The request that brings that count to exactly 3 is the last one admitted; the next rush create is rejected with `ERR_RUSH_CAPACITY_FULL` (HTTP 409). `STANDARD` batches are never counted by this rule and never rejected by it.

With a batch open in `INTAKE`, the intake desk registers boxes into it, one payload of `box_label` and `intake_weight_grams` at a time; the label must be unique within the batch (a duplicate label is rejected with `ERR_INVALID_REQUEST`, HTTP 400), and the weight must be at least 1 gram. Each registered box starts in `RECEIVED` status, and its creation automatically appends the first link of its custody trail: a `CustodyEvent` whose `from_stage` and `to_stage` are both `INTAKE`, stamped with the registering clerk's identity. This auto-intake event is what later satisfies the chain-of-custody precondition on starting prep. Intake respects the agreement's ceiling — a box that would push the batch past `max_boxes_per_batch` is rejected with `ERR_MAX_BOXES_EXCEEDED` (HTTP 409).

Shelving moves a box from `RECEIVED` to `STORED`. The clerk picks a `shelf_slot_id`; the server creates an `ACTIVE` `ShelfAssignment` stamped with `placed_at` from the logical clock, adds the box's `intake_weight_grams` to the slot's `occupied_weight_grams`, and appends a custody event whose `to_stage` is `STORAGE`. Two capacity and compliance rules guard placement. A slot admits the box only when its remaining capacity — `capacity_grams` minus `occupied_weight_grams` — is at least the box's weight; equality is admitted, and only a placement that would strictly exceed capacity is rejected with `ERR_SHELF_OVER_CAPACITY` (HTTP 409). And when the batch's client is `hipaa_covered` and any document in the box has `contains_phi` set, the chosen slot's `zone` must be `VAULT`; placing such a box on a `GENERAL` shelf is rejected with `ERR_VAULT_ZONE_REQUIRED` (HTTP 422). Shelf slots themselves are provisioned by the platform with a unique `shelf_code` (a duplicate is rejected with `ERR_INVALID_STATE`, HTTP 409), a `zone` of `GENERAL` or `VAULT`, and a `capacity_grams` of at least 1; their live `occupied_weight_grams` is the sum of `intake_weight_grams` over that slot's `ACTIVE` assignments. An assignment can also be released manually by an `IntakeClerk` — only while it is `ACTIVE`, otherwise `ERR_INVALID_STATE` (HTTP 409) — which flips it to `RELEASED`, stamps `released_at` from the clock, and debits the box weight back off the slot (occupied weight never drops below zero).

### 3.3. Preparation, Scanning, and the Session Ledger

Physical work on a box proceeds as a custody relay recorded one link at a time. Each link is a `CustodyEvent` carrying the `box_id` it belongs to, the `from_stage` and `to_stage` of the hand-off, the acting user's `actor_user_id` taken from `X-User-ID`, the acting user's `actor_role` taken from `X-User-Role`, and an optional free-text `notes`. A custody hand-off submission carries a `to_stage` of `PREP`, `SCAN`, or `STORAGE`, plus the optional `notes`, and it drives the box's state machine: `STORED` to `IN_PREP` when a `PrepTechnician` records `PREP`; `IN_PREP` to `IN_SCAN` when a `ScanOperator` records `SCAN`; `IN_SCAN` to `SCAN_COMPLETE` when an `IntakeClerk` records `STORAGE`, returning the post-scan box to storage shelving without tracking new shelf occupancy. The `to_stage`-to-role pairing is enforced as `ERR_FORBIDDEN` (HTTP 403) — after the client-suspension check and before the box-state check — and any other `to_stage` value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The recorded `from_stage` is derived server-side from the `to_stage`: `PREP` records from `STORAGE`, `SCAN` from `PREP`, and `STORAGE` from `SCAN`. Pulling a box from storage for prep also releases its `ACTIVE` shelf assignment — `released_at` stamped from the clock and the box's weight debited from the slot — so the density ledger always reflects what is actually on shelves.

Chain-of-custody segregation is enforced on every explicit hand-off: the actor recording a custody event may not be the same user who authored the immediately preceding custody event on that box. Violations are rejected with `ERR_CUSTODY_SEGREGATION` (HTTP 422). System-generated events — the auto-intake link (`INTAKE` → `INTAKE`), the shelf-placement link (`INTAKE` → `STORAGE`), the begin-destruction link (`STORAGE` → `DESTRUCTION`), and the mark-returned link (`STORAGE` → `RETURN`) — are recorded with the acting user's id and do count as the previous link for the next explicit check, but are never themselves rejected. The adjacency check itself applies only to the explicit custody-events endpoint and to destruction-certificate recording; it looks at the box's most recently recorded custody event — the event with the greatest `created_at`, with simultaneous `created_at` values broken in favor of the event recorded later, since under the logical clock `created_at` ties are routine.

Meanwhile, documents enter the batch during `INTAKE` or `PREPPING` only: an `IntakeClerk` or `PrepTechnician` registers each document into its box with a `doc_type` of `MEDICAL_RECORD`, `INVOICE`, `CONTRACT`, `CORRESPONDENCE`, or `OTHER`, a declared physical `pages` count of at least 1, a `contains_phi` flag, and a declared `ocr_confidence` between 0 and 100. The document starts `REGISTERED`, and its `batch_id` is denormalized from its box so reconciliation queries never need to walk the hierarchy.

Scanning is booked through sessions, not loose page counts. A `ScanOperator` opens a scan session against a batch in `SCANNING` by naming a `scanner_id`; the scanner unit must exist and be `AVAILABLE` (a unit in `MAINTENANCE` rejects both session open and commit with `ERR_SCANNER_UNAVAILABLE`, HTTP 409), and a scanner already occupied by an `OPEN` session on any batch rejects a second open with `ERR_SCANNER_BUSY` (HTTP 409). The new session starts `OPEN`, stamped with `started_at` from the clock and `operator_id` from the acting user's `X-User-ID`. Scanner units are platform-provisioned with a unique `scanner_code` (a duplicate is rejected with `ERR_INVALID_STATE`, HTTP 409) and a `capacity_pages_per_session` of at least 1, and a `PlatformAdmin` flips a unit between `AVAILABLE` and `MAINTENANCE` through its maintenance control — the flip is unconditional and is permitted even while a session is `OPEN` on the unit; the availability guard bites at session open and at commit.

While a session is `OPEN`, the operator logs pages against it, one entry per document: each log carries its owning `session_id`, a denormalized `batch_id` for reconciliation queries, a `document_id`, and a `pages` count of at least 1; the document must belong to the session's batch, and each accepted entry adds its `pages` to the session's `page_count`. Committing the session is the pivotal ledger act. The commit requires `expected_batch_version` per §2.7, requires the session still `OPEN` and the batch still in `SCANNING`, requires `page_count` strictly greater than 0 (else `ERR_EMPTY_SCAN_SESSION`, HTTP 409) and no greater than the scanner's `capacity_pages_per_session` (else `ERR_SCANNER_OVER_CAPACITY`, HTTP 409), and re-checks that the scanner is still `AVAILABLE`. On commit the session moves to `COMMITTED` with `ended_at` stamped; every document whose cumulative committed-session pages now reach its declared `pages` transitions from `REGISTERED` — or, on the rework path, from `QA_FAILED`, where only pages committed after the document entered `QA_FAILED` count toward coverage — to `SCANNED`; the batch's page ledgers are reconciled as described below; the draft invoice's `page_subtotal_cents` is recomputed under the provisional pricing variant; and the batch's `version` increments by 1. An operator may instead void an open session, moving it to `VOIDED` with `ended_at` stamped; a voided session's page logs are retained for audit but excluded from every aggregate.

The batch keeps two page ledgers, and the distinction is fiscal. `scanned_pages` tracks produced material: it grows by a document's `pages` on every transition of that document into `SCANNED`, including each rework rescan. `billable_scanned_pages` is a count-once ledger: it grows by the document's `pages` only on that document's first transition into `SCANNED`, and rework rescans never double-count. Both start at 0.

### 3.4. Quality Review and the Rework Loop

Batch pipeline advancement is gated by explicit checks. An `IntakeClerk` starts prep, moving the batch `INTAKE → PREPPING`, only when the batch has at least one box (else `ERR_BATCH_EMPTY`, HTTP 409) and every box has at least one custody event — satisfied in practice by the auto-intake link, with a gap surfaced as `ERR_CUSTODY_GAP` (HTTP 422). A `ScanOperator` starts scanning, `PREPPING → SCANNING`, only when the batch has at least one registered document (again `ERR_BATCH_EMPTY`). Submitting for QA, `SCANNING → QA`, requires that no scan session of the batch is still `OPEN` (else `ERR_OPEN_SCAN_SESSION_EXISTS`, HTTP 409) and that every document of the batch sits in `SCANNED`, `QA_FAILED`, or `REJECTED` (else `ERR_DOCUMENTS_INCOMPLETE`, HTTP 409). Each of these transitions, like every batch transition, increments the batch's `version` by 1.

While the batch is in `SCANNING` or `QA`, a `QAReviewer` may flag an individual `SCANNED` document as `QA_FAILED`; both page ledgers stay unchanged — the pages remain billed, because rework is free for the client. At the batch level the reviewer then chooses between two sibling outcomes. Passing QA, `QA → INDEXING`, requires that no document of the batch is `QA_FAILED` (else `ERR_DOCUMENTS_INCOMPLETE`). Failing QA, `QA → SCANNING`, requires that at least one document is `QA_FAILED` (else `ERR_BATCH_NOT_REWORKABLE`, HTTP 409); it bumps the batch's `rework_cycle_count` by 1, leaves both page ledgers untouched, and leaves the `QA_FAILED` documents in `QA_FAILED` — they become `SCANNED` again only through a rework scan-session commit that covers the document's declared page count with pages committed after the document entered `QA_FAILED` (measured against the cumulative committed-page total captured at the moment the document entered `QA_FAILED`, since the logical clock's timestamps cannot express "after").

### 3.5. Indexing, Metadata, and Rejection

Once the batch reaches `INDEXING`, an `Indexer` attaches metadata to each `SCANNED` document. The submission carries `metadata_json` — which must be a JSON object containing the keys `title`, `record_date`, and `subject`, with a non-object value or a missing key rejected as `ERR_METADATA_INCOMPLETE` (HTTP 422) — and an `ocr_text_ref`, an opaque pointer to the OCR full-text blob in cloud storage. What happens next forks on the document's declared `ocr_confidence`. When `ocr_confidence` is at least the minimum OCR confidence of 70, an `IndexRecord` is created one-to-one with the document and the document transitions `SCANNED → INDEXED`. When `ocr_confidence` is below 70, the document instead transitions `SCANNED → REJECTED`: no index record is created, and the submission responds with HTTP 200 carrying the document itself rather than an index record. A rejected document is permanently excluded from delivery; its pages remain in the provisional billing set but are removed from the final billing set at delivery, per §3.6.

### 3.6. Delivery, Pricing, and Invoicing

Delivery is the fiscal pivot of the whole pipeline. A `QAReviewer` delivers a batch, `INDEXING → DELIVERED`, only when the batch is indexable: it has at least one document; every document is in `INDEXED`, `DELIVERED`, or `REJECTED`; and the number of `REJECTED` documents is at most the rejection allowance, defined as the larger of 1 and the floor of one tenth of the batch's total document count. The boundary is exact: a 10-document batch tolerates exactly 1 rejection, a 20-document batch tolerates exactly 2, and 21 documents tolerate 2. A batch failing any leg of that check is rejected with `ERR_BATCH_NOT_INDEXABLE` (HTTP 409).

A successful delivery fans out across the batch. Every `INDEXED` document transitions to `DELIVERED` with its `delivered_at` stamped from the logical clock; the batch's own `delivered_at` is stamped the same way; the batch's `disposition_at` is computed as `delivered_at` plus the agreement's `retention_days` — the instant at which all remaining physical material must be destroyed or returned; and the batch's parallel `delivery_status` dimension — `PENDING` from batch creation until then — is set once, to `COMPLETE` when zero documents are `REJECTED` and to `PARTIAL` otherwise. A batch delivered `PARTIAL` keeps its rejected documents undelivered forever.

Page pricing runs in two variants, and the batch's state — never a request flag — selects between them. The applicable per-page rate depends only on the batch and its agreement: the base rate is 0.30 dollars per page when the agreement's `price_tier` is `VOLUME` and 0.45 dollars per page when it is `STANDARD`, and for a `RUSH` batch that base is then multiplied by the agreement's `rush_multiplier`. Each document's charge is its `pages` times that rate times 100, rounded half-up to integer cents per §2.6, and the `page_subtotal_cents` is the sum of those per-document amounts. While the batch has not yet reached `DELIVERED`, the provisional variant bills everything produced so far: the document set is `SCANNED`, `QA_FAILED`, `INDEXED`, `DELIVERED`, and `REJECTED` — rejected pages were work produced, and QA-failed pages are still billable. From delivery onward, the final variant's document set is `SCANNED`, `INDEXED`, and `DELIVERED` only; rejected documents are removed from the bill because undeliverable work is not charged at settlement. For a batch with rejected pages, the final subtotal is therefore strictly smaller than the last provisional read that still contained a rejected document. The provisional figure is recomputed on every scan-session commit and on every draft-invoice read; the final figure is locked at delivery and frozen into the invoice at issue.

Storage accrual is a separate, box-grained computation. For a given as-of instant, a box's chargeable days are the whole days fully elapsed between the batch's `delivered_at` and the as-of instant, minus the agreement's `storage_free_days`, floored at zero — a box becomes chargeable only after `delivered_at` plus the free window has fully elapsed, and partial days never count. Each chargeable day costs the agreement's `storage_daily_rate_cents`. The batch total sums that fee over the batch's boxes whose status is `STORED`, `SCAN_COMPLETE`, or `AWAITING_DISPOSITION`; `DESTROYED` and `RETURNED` boxes stop accruing, and pre-delivery states are excluded defensively since they cannot exist post-delivery in a well-formed run. This total appears in two variants. The projected variant evaluates the accrual as of the current logical clock: it surfaces on batch reads as `projected_storage_fee_cents` and on a `DRAFT` invoice as `storage_subtotal_cents`, grows as the clock advances, and shrinks when boxes reach `DESTROYED` or `RETURNED`. The actual-at-issue variant evaluates the same formula as of the invoice's `issued_at` and freezes it into `storage_subtotal_cents` at issue time; once issued the figure is immutable, two reads of an issued invoice at different clocks agree, and a projected read taken after a destruction is strictly smaller than the frozen issued value.

An invoice is born `DRAFT` with the batch and carries `page_subtotal_cents`, `storage_subtotal_cents`, their sum `total_cents`, and `amount_paid_cents` starting at 0. While `DRAFT`, every read recomputes the page subtotal under the variant selected by batch state and the storage subtotal projected at the current clock, and the recomputed figures are persisted (refreshing the invoice's `updated_at` and `version` whenever they change). A `BillingClerk` issues the invoice — permitted only once the batch is `DELIVERED`, `DISPOSITION_PENDING`, or `CLOSED`, and only from `DRAFT` — which stamps `issued_at` from the clock and freezes both subtotals. Payments against an `ISSUED` or `PARTIALLY_PAID` invoice carry `amount_cents` of at least 1 and no more than the outstanding balance (`total_cents` minus `amount_paid_cents`); an overpayment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422), and a payment attempted on a `DRAFT` or `VOID` invoice is rejected with `ERR_INVOICE_NOT_ISSUED` (HTTP 409). Each accepted payment adds `amount_cents` to `amount_paid_cents`; a payment smaller than the outstanding balance moves the invoice to `PARTIALLY_PAID`, and one exactly equal to the outstanding balance moves it to `PAID`. A clerk may also void a `DRAFT` invoice with a recorded `void_reason`, ending its lifecycle as `VOID`.

### 3.7. Retention, Disposition, and Certified Destruction

The disposition sweep is clock-driven. When the logical clock reaches a delivered batch's `disposition_at`, the batch automatically transitions `DELIVERED → DISPOSITION_PENDING`. Every box of the batch sitting in `STORED` or `SCAN_COMPLETE` moves to `AWAITING_DISPOSITION`; every `ACTIVE` shelf assignment of those boxes is released with `released_at` stamped and the slot's occupied weight debited per box; and the batch's `version` increments.

A client that prefers its paper back rather than destroyed may elect return on a per-box basis: a `ClientUser` records a return request, which sets the box's `return_requested` flag and pins that box's disposition branch to return. The request is temporal — it must be recorded before the batch reaches `DISPOSITION_PENDING` or `CLOSED`, and a late request is rejected with `ERR_RETURN_WINDOW_EXPIRED` (HTTP 409). When the batch is already `DELIVERED`, a return request on a `STORED` or `SCAN_COMPLETE` box moves it to `AWAITING_DISPOSITION` immediately, releasing its shelf assignment if it has one. From `AWAITING_DISPOSITION` the two branches diverge: an `IntakeClerk` marks the box returned, requiring `return_requested` set (else `ERR_BOX_NOT_RETURN_COMMITTED`, HTTP 409), moving the box to `RETURNED` and appending a `RETURN` custody link; or a `DestructionSpecialist` begins destruction, requiring `return_requested` unset (else `ERR_BOX_RETURN_COMMITTED`, HTTP 409), moving the box to `IN_DESTRUCTION` and appending a `DESTRUCTION` custody link.

Certified destruction completes the destruction branch. A `DestructionSpecialist` records a certificate naming a `witness_user_id` and a `method` of `SHRED`, `INCINERATE`, or `PULP`. Segregation of duties binds here twice: the general custody-adjacency check applies to this recording, and additionally the witness must be a different bureau staffer than the recording actor — a `witness_user_id` equal to the actor's `X-User-ID` is rejected with `ERR_WITNESS_SEGREGATION` (HTTP 422). On acceptance the box moves `IN_DESTRUCTION → DESTROYED`, the certificate is minted with a unique server-generated `certificate_code` (the string `CERT-` followed by 16 uppercase hexadecimal characters) and `destroyed_at` stamped from the clock, and a client-wide cascade fires: every other non-final box — any box not yet `DESTROYED` or `RETURNED` — belonging to any non-`CLOSED` batch of the same client has its `custody_flagged` raised.

A flagged box is frozen mid-custody: custody hand-offs, begin-destruction, destruction-certificate recording, and shelf-assignment creation on it are all rejected with `ERR_CUSTODY_FLAGGED` (HTTP 409) until a `ComplianceOfficer` clears the flag through the clear-custody-flag action, restoring `custody_flagged` to false. The cascade and the clear together form the bureau's post-destruction audit gate: one certified destruction pauses all other physical handling for that client until compliance has reviewed it. Finally, once every box of a `DISPOSITION_PENDING` batch is `DESTROYED` or `RETURNED` — with any shortfall rejected as `ERR_BOXES_NOT_FINAL` (HTTP 409) — a `ComplianceOfficer` closes the batch, moving it to `CLOSED`, the terminal pipeline state.

### 3.8. Client Access, Grants, and Download

Delivered documents reach the client through access grants. A `ClientUser` creates a grant against its own client by naming a `batch_id`, a `scope` of `METADATA_ONLY` or `FULL_IMAGE`, and an `expires_at` instant; the grant starts `ACTIVE`, and its `vault_only` flag is computed server-side — true exactly when the client is `hipaa_covered` and any document in the referenced batch has `contains_phi` set. Grants are lazily time-aware: when the logical clock has passed a grant's `expires_at` (strictly — a grant whose `expires_at` equals the current clock is still active), the next use — including a plain read of the grant — transitions it to `EXPIRED`; using an expired grant is rejected with `ERR_GRANT_EXPIRED` (HTTP 409), while using a `REVOKED` grant is rejected with `ERR_INVALID_STATE` (HTTP 409). The client may also revoke an `ACTIVE` grant outright, moving it to `REVOKED`; revoking a grant that is no longer `ACTIVE` (including one already `EXPIRED` or `REVOKED`) is rejected with `ERR_INVALID_STATE` (HTTP 409).

The grant exposes two channels. The metadata channel lists the documents visible under the grant — every document of the referenced batch, whatever its status (including `REJECTED`) — and it requires the grant `ACTIVE` and unexpired. The download channel addresses a single document by its `docId` path parameter within the grant's context and returns that document's image as a payload of `document_id`, a `download_url`, and an `expires_in_seconds` lifetime fixed at 300; it is the most heavily guarded read in the system. Download requires the grant `ACTIVE` and unexpired, the scope `FULL_IMAGE` — a `METADATA_ONLY` grant serves only the documents list, and attempting a download with one is rejected with `ERR_SCOPE_INSUFFICIENT` (HTTP 403) — the grant not `vault_only` (a vault-only grant used on the public download channel is rejected with `ERR_GRANT_VAULT_ONLY`, HTTP 422), the document itself in `DELIVERED` status (else `ERR_DOCUMENT_NOT_DELIVERED`, HTTP 409), and the owning client not `SUSPENDED`. These guards are evaluated in the order: client suspension, document existence under the grant, grant expiry and `ACTIVE`-ness, document `DELIVERED`, `vault_only`, then scope.

## 4. Endpoint Definitions

All endpoints are served under the API root. Creating a new resource returns HTTP 201; actions that modify an existing resource, and all reads, return HTTP 200 — with one exception: `POST /batches/{id}/qa-reviews` persists no separate review resource and responds HTTP 201 carrying the updated document. Error responses carry the status codes listed in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default 2026-05-01T00:00:00Z; drives disposition sweeps, grant expiry, storage accrual) | PlatformAdmin |
| POST | `/scanner-units` | Register a scanner unit | PlatformAdmin |
| GET | `/scanner-units` | List scanner units | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/scanner-units/{id}` | Get a scanner unit | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| POST | `/scanner-units/{id}/maintenance` | Set scanner availability (`AVAILABLE` or `MAINTENANCE`) | PlatformAdmin |
| GET | `/scanner-units/{id}/scan-sessions` | List scan sessions that occupied this scanner | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk |
| POST | `/shelf-slots` | Register a shelf slot | PlatformAdmin |
| GET | `/shelf-slots` | List shelf slots (filterable by `zone`) | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/shelf-slots/{id}` | Get a shelf slot (includes `occupied_weight_grams`) | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/shelf-slots/{id}/shelf-assignments` | List shelf assignments occupying this slot | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| POST | `/clients` | Onboard a client | PlatformAdmin |
| GET | `/clients` | List clients | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk |
| GET | `/clients/{id}` | Get a client | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| POST | `/clients/{id}/suspend` | Suspend a client (blocks all client-subtree mutations and grant usage) | PlatformAdmin |
| POST | `/clients/{id}/reactivate` | Reactivate a suspended client | PlatformAdmin |
| POST | `/clients/{id}/service-agreements` | Create the client's service agreement (at most one per client) | PlatformAdmin |
| GET | `/clients/{id}/service-agreements` | List service agreements of a client | PlatformAdmin, BillingClerk, ComplianceOfficer |
| GET | `/service-agreements/{id}` | Get a service agreement | PlatformAdmin, BillingClerk, ComplianceOfficer |
| GET | `/clients/{id}/batches` | List batches of a client | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/clients/{id}/access-grants` | List access grants of a client | PlatformAdmin, ComplianceOfficer, ClientUser |
| POST | `/clients/{id}/access-grants` | Grant client access to a batch's documents (`vault_only` computed server-side) | ClientUser |
| GET | `/clients/{id}/invoices` | List invoices of a client | PlatformAdmin, BillingClerk, ClientUser |
| POST | `/batches` | Create a batch (rush admission enforced; auto-creates a `DRAFT` invoice) | IntakeClerk |
| GET | `/batches` | List batches (filterable by `client_id`, `status`) | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk |
| GET | `/batches/{id}` | Get a batch (includes `scanned_pages`, `billable_scanned_pages`, `projected_storage_fee_cents`, `disposition_at`) | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| POST | `/batches/{id}/start-prep` | `INTAKE → PREPPING` | IntakeClerk |
| POST | `/batches/{id}/start-scan` | `PREPPING → SCANNING` | ScanOperator |
| POST | `/batches/{id}/submit-qa` | `SCANNING → QA` | ScanOperator |
| POST | `/batches/{id}/pass-qa` | `QA → INDEXING` | QAReviewer |
| POST | `/batches/{id}/fail-qa` | `QA → SCANNING` (cyclic rework) | QAReviewer |
| POST | `/batches/{id}/deliver` | `INDEXING → DELIVERED`; delivers `INDEXED` documents, locks final pricing, stamps `delivered_at` and `disposition_at` | QAReviewer |
| POST | `/batches/{id}/close` | `DISPOSITION_PENDING → CLOSED` | ComplianceOfficer |
| GET | `/batches/{id}/boxes` | List boxes of a batch | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/batches/{id}/documents` | List documents of a batch (filterable by `status`, `box_id`) | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/batches/{id}/index-records` | List index records of a batch | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/batches/{id}/scan-sessions` | List scan sessions of a batch | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk |
| GET | `/batches/{id}/page-logs` | List page logs of a batch (all sessions) | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk |
| GET | `/batches/{id}/access-grants` | List access grants referencing a batch | PlatformAdmin, ComplianceOfficer |
| GET | `/batches/{id}/destruction-certificates` | List destruction certificates of a batch | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/batches/{id}/invoices` | List invoices of a batch (0 or 1 entries) | PlatformAdmin, BillingClerk, ClientUser |
| POST | `/batches/{id}/qa-reviews` | Mark a document `QA_FAILED` (batch `SCANNING` or `QA`) | QAReviewer |
| POST | `/batches/{id}/boxes` | Intake a box into a batch (batch `INTAKE` only; capacity enforced; auto custody event) | IntakeClerk |
| GET | `/boxes/{id}` | Get a box | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| POST | `/boxes/{id}/request-return` | Client elects return instead of destruction (rejected once the batch is `DISPOSITION_PENDING` or `CLOSED`) | ClientUser |
| POST | `/boxes/{id}/custody-events` | Record a custody hand-off (`to_stage` in `PREP`, `SCAN`, or `STORAGE`) | PrepTechnician, ScanOperator, IntakeClerk |
| GET | `/boxes/{id}/custody-events` | Custody trail of a box (append-only, chronological) | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| POST | `/boxes/{id}/clear-custody-flag` | Clear the post-destruction custody flag on a box | ComplianceOfficer |
| POST | `/boxes/{id}/begin-destruction` | `AWAITING_DISPOSITION → IN_DESTRUCTION` | DestructionSpecialist |
| POST | `/boxes/{id}/destruction-certificates` | Record certified destruction (`IN_DESTRUCTION → DESTROYED`; witness segregation; client-wide custody-flag cascade) | DestructionSpecialist |
| GET | `/boxes/{id}/destruction-certificates` | Get destruction certificate of a box (0 or 1 entries) | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| POST | `/boxes/{id}/mark-returned` | `AWAITING_DISPOSITION → RETURNED` (requires `return_requested`) | IntakeClerk |
| POST | `/boxes/{id}/shelf-assignments` | Shelve a `RECEIVED` box (`RECEIVED → STORED`; capacity and vault-zone checks; appends `STORAGE` custody event) | IntakeClerk |
| GET | `/boxes/{id}/shelf-assignments` | List shelf assignments of a box | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/shelf-assignments/{id}` | Get a shelf assignment | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| POST | `/shelf-assignments/{id}/release` | Manually release an `ACTIVE` shelf assignment | IntakeClerk |
| POST | `/boxes/{id}/documents` | Register a document in a box (batch `INTAKE` or `PREPPING` only) | IntakeClerk, PrepTechnician |
| GET | `/boxes/{id}/documents` | List documents of a box | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/documents/{id}` | Get a document | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| POST | `/documents/{id}/index-records` | Submit indexing metadata (`SCANNED → INDEXED`, or `SCANNED → REJECTED` when `ocr_confidence` is below 70; on the reject branch the response is 200 carrying the document) | Indexer |
| GET | `/documents/{id}/index-records` | Get the index record of a document (0 or 1 entries) | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/index-records/{id}` | Get an index record | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk, ClientUser |
| GET | `/documents/{id}/page-logs` | List page logs referencing a document | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk |
| POST | `/batches/{id}/scan-sessions` | Open a scan session (batch `SCANNING`; one `OPEN` session per scanner; scanner `AVAILABLE`) | ScanOperator |
| GET | `/scan-sessions/{id}` | Get a scan session | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk |
| POST | `/scan-sessions/{id}/page-logs` | Log pages scanned for a document in this session | ScanOperator |
| GET | `/scan-sessions/{id}/page-logs` | List page logs of a session | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk |
| GET | `/page-logs/{id}` | Get a page log | PlatformAdmin, IntakeClerk, PrepTechnician, ScanOperator, QAReviewer, Indexer, DestructionSpecialist, ComplianceOfficer, BillingClerk |
| POST | `/scan-sessions/{id}/commit` | Commit the session (OCC on the batch via `expected_batch_version`) | ScanOperator |
| POST | `/scan-sessions/{id}/void` | Void an open session (its pages excluded from all aggregates) | ScanOperator |
| GET | `/access-grants/{id}` | Get an access grant | PlatformAdmin, ComplianceOfficer, ClientUser |
| POST | `/access-grants/{id}/revoke` | Revoke an access grant | ClientUser |
| GET | `/access-grants/{id}/documents` | List documents visible under a grant (metadata channel; lazy expiry evaluated; grant must be `ACTIVE`) | ClientUser |
| GET | `/access-grants/{id}/documents/{docId}/download` | Download a document image (grant active and unexpired, `FULL_IMAGE` scope, not `vault_only`, document `DELIVERED`, client not suspended) | ClientUser |
| GET | `/invoices/{id}` | Get an invoice (a `DRAFT` invoice recomputes subtotals on every read; issued invoices are frozen) | PlatformAdmin, BillingClerk, ClientUser |
| POST | `/invoices/{id}/issue` | Issue the invoice (`DRAFT → ISSUED`; final pricing variant; storage accrual frozen at `issued_at`) | BillingClerk |
| POST | `/invoices/{id}/payments` | Capture a payment against the invoice | BillingClerk |
| POST | `/invoices/{id}/void` | Void a `DRAFT` invoice | BillingClerk |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow is described.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CLIENT_SUSPENDED | 403 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_BATCH_EMPTY | 409 |
| ERR_CUSTODY_GAP | 422 |
| ERR_OPEN_SCAN_SESSION_EXISTS | 409 |
| ERR_DOCUMENTS_INCOMPLETE | 409 |
| ERR_BATCH_NOT_REWORKABLE | 409 |
| ERR_BATCH_NOT_INDEXABLE | 409 |
| ERR_BOXES_NOT_FINAL | 409 |
| ERR_SCANNER_BUSY | 409 |
| ERR_SCANNER_UNAVAILABLE | 409 |
| ERR_SCANNER_OVER_CAPACITY | 409 |
| ERR_EMPTY_SCAN_SESSION | 409 |
| ERR_SHELF_OVER_CAPACITY | 409 |
| ERR_VAULT_ZONE_REQUIRED | 422 |
| ERR_MAX_BOXES_EXCEEDED | 409 |
| ERR_RUSH_CAPACITY_FULL | 409 |
| ERR_CUSTODY_SEGREGATION | 422 |
| ERR_WITNESS_SEGREGATION | 422 |
| ERR_CUSTODY_FLAGGED | 409 |
| ERR_BOX_RETURN_COMMITTED | 409 |
| ERR_BOX_NOT_RETURN_COMMITTED | 409 |
| ERR_RETURN_WINDOW_EXPIRED | 409 |
| ERR_METADATA_INCOMPLETE | 422 |
| ERR_GRANT_EXPIRED | 409 |
| ERR_GRANT_VAULT_ONLY | 422 |
| ERR_SCOPE_INSUFFICIENT | 403 |
| ERR_DOCUMENT_NOT_DELIVERED | 409 |
| ERR_PAYMENT_EXCEEDS_BALANCE | 422 |
| ERR_INVOICE_NOT_ISSUED | 409 |
| ERR_AGREEMENT_EXISTS | 409 |

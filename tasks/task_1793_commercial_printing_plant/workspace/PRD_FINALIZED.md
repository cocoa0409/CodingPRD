# Commercial Printing Plant API — Product Requirements Document

## 1. Introduction

Commercial printing lives in the seams between estimating, prepress, the pressroom, the bindery, the mailstream, and the back office. A misestimated impression count ripples through paper purchase orders; a delayed proof approval stalls plating and pushes a press window into another customer's slot; a sloppy gang run quietly eats make-ready time that someone still has to pay for. The system described here is the operating API for a commercial printing plant that runs both web and sheetfed work, and it treats every one of those seams as a first-class, queryable workflow rather than a spreadsheet.

The API covers the entire lifecycle of a job: an `Estimator` prices a job by signature and impression, applies make-ready charges and a spoilage allowance, and sends a quote to the customer; the customer accepts and a production job is born; prepress uploads proofs and the customer approves or requests changes; the pressroom schedules solo runs or consolidates compatible work into gang runs with a shared make-ready allocation; paper lots are reserved, drawn first-in-first-out, and replenished automatically when stocks run low; the bindery walks its routing steps in strict sequence; mail pieces are presorted into tiered postage rates and dropped under a daily capacity ceiling; finally, the plant bills the customer against an overrun/underrun tolerance band and adjudicates reprint claims with segregation of duties. Throughout, the system keeps one eye on each customer's credit exposure, halting new acceptances when exposure crosses the credit limit.

This document is the only specification an implementer needs. It is written for engineers and assumes no access to internal tables, schemas, or rule databases — every rule stated here is intended to be reconstructed from the prose alone.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the operational capacity in which that principal acts. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not authorized for the targeted endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly seven roles, spelled precisely as follows: `Estimator`, `Customer`, `PrepressOperator`, `PressScheduler`, `PurchasingManager`, `MailSpecialist`, and `PlantManager`.

Identity semantics differ per role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; any resource that carries a `customer_id` foreign key is owned by that customer, and ownership checks compare the resource's `customer_id` to `X-User-ID`. When a `Customer` attempts to read or act on a resource whose `customer_id` does not match their `X-User-ID`, the request is rejected with `ERR_NOT_OWN_RESOURCE` (HTTP 403). Customer ownership checks apply to estimates, jobs, proofs, invoices, reprint claims, mail drops, and bindery tickets — both on direct reads and on customer-driven actions such as accept, approve, request-changes, dispute, and claim filing. For the six remaining roles — `Estimator`, `PrepressOperator`, `PressScheduler`, `PurchasingManager`, `MailSpecialist`, and `PlantManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow calls for it (for example, the `reviewed_by` field written onto a `ReprintClaim` when a `PlantManager` moves the claim forward), but it is never compared against any entity's `id` for ownership purposes.

Within claim adjudication, the segregation-of-duties rule further constrains `PlantManager` actions: the operator who moves a claim from `FILED` to `UNDER_REVIEW` is recorded as `reviewed_by`, and any subsequent approve or deny attempt carrying that same `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A different `PlantManager` principal must complete the adjudication.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter controls the maximum number of items returned; if omitted, it defaults to 10, with a minimum accepted value of 1 and a maximum accepted value of 100. The `offset` parameter controls how many items are skipped before the page begins and defaults to 0. All list endpoints return resources sorted by `created_at` ascending unless otherwise stated. The `meta` object of a list response carries exactly four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every top-level resource in this system — `Customer`, `Estimate`, `Job`, `Proof`, `PaperStock`, `PaperPurchaseOrder`, `PaperLot`, `Press`, `PressRun`, `GangRun`, `BinderyTicket`, `MailDrop`, `Invoice`, `ReprintClaim` — carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, set once at creation. `updated_at` is an ISO 8601 UTC timestamp that refreshes on any mutation. `version` is an integer incremented by exactly 1 on every mutation of the resource — whether that mutation originates from a client call or from an internal cascade triggered by another entity's state transition. Cascading transitions on jobs, proofs, invoices, gang runs, press runs, customers, and estimates all bump the affected entity's `version` and refresh its `updated_at`, even when the initiating request targeted a different resource.

Because these properties are system-managed, they are never accepted from the client: a request body that carries `id`, `created_at`, `updated_at`, `version`, or any other key the endpoint does not define is processed as if that key were absent — the server mints its own values and silently ignores the extra keys. Unrecognized or system-managed fields in a request body are therefore never a reason to reject the request (in particular they never produce `ERR_VALIDATION`).

Three write endpoints take a non-optional optimistic concurrency field, and only those three. A revision to a `DRAFT` estimate must carry `expected_estimate_version` equal to the estimate's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Adding a member job to a `FORMING` gang run must carry `expected_gang_run_version` matching the gang run's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Scheduling a press run must carry `expected_press_version` matching the target press's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named in this paragraph do not take a version field. The rationale is consistent across all three: the client's view of the parent resource may have advanced since it was last read, and the server refuses to let the write proceed on a stale basis.

### 2.5. Logical Clock and Time Semantics

The server maintains its own logical clock rather than consulting wall-clock time. At startup the logical clock is exactly `2026-08-01T00:00:00Z`, and it advances only when a `PlantManager` invokes the test-driving clock endpoint with a target instant `to_iso8601`. The clock never falls back to wall-clock time. Anywhere in this document that says "current clock," "now," or "today" refers to this logical clock. Estimate expiry, in particular, is evaluated lazily against this clock: the transition to `EXPIRED` is observed when an accept is attempted after `expires_at` or when the clock has advanced past `expires_at`, not by a background timer.

### 2.6. Monetary Units, Precision, and Rounding

All monetary values are represented as integer cents — `credit_limit_cents`, `total_price_cents`, `make_ready_total_cents`, `subtotal_cents`, `cost_per_sheet_cents`, `amount_paid_cents`, `credit_applied_cents`, `amount_outstanding_cents`, `total_due_cents`, `base_amount_cents`, `postage_cents`, `proof_overage_cents`, `shortage_credit_cents`, `gang_make_ready_allocated_cents`, `allocated_make_ready_cents`, `provisional_credit_cents`, `final_credit_cents`, `reprint_credit_balance_cents`, and `exposure_cents` are all integer-cent quantities. Wherever a calculation produces a fractional cent, the rounding rule is round-half-up — never banker's rounding, never truncation. Percentages such as `press_spoilage_pct`, `bindery_spoilage_pct`, `discount_pct`, `default_tolerance_pct`, `tolerance_pct`, and `liability_pct` are stored as numbers where a value of 3 means three percent.

### 2.7. Validation Order and Error Precedence

When multiple checks could fail on the same request, the server evaluates them in a strict priority order so that the same request always yields the same error. Authentication of headers comes first (`ERR_UNAUTHENTICATED`), followed by role authorization (`ERR_FORBIDDEN_ROLE`), followed by customer ownership (`ERR_NOT_OWN_RESOURCE`). Only after identity is established does the server check existence: path parameters and body foreign-key references must resolve to existing resources, validated left-to-right — path first, then body — with the first unresolved reference producing `ERR_NOT_FOUND`. Optimistic concurrency (`ERR_STALE_VERSION`) is checked next, ahead of any state-machine evaluation. State-machine validity follows, where the target entity must be in the required state for the operation — rejections here surface as `ERR_INVALID_STATE` or one of the state-specific codes named later in this document. Cross-entity referential consistency comes after that, then temporal rules (estimate expiry, gang due-date window, press window conflict), then sequencing and resource constraints (gang size, bindery sequence, paper availability, press availability, mail capacity, over-receipt cap, duplicate invoice, cancel-point rules, claim uniqueness, defect-quantity bounds, gang run-quantity match, segregation of duties), and then fiscal checks (`ERR_CREDIT_HOLD`, `ERR_OVERPAYMENT`, `ERR_CREDIT_APPLICATION_INVALID`). Finally, generic field-level request validity — missing required fields, bad enums, out-of-range numerics, malformed payloads — is enforced with `ERR_VALIDATION` (HTTP 400). Malformed payloads fail fast per-field; when both a business rule and a field-format rule would fail, the business rule wins.

### 2.8. Hierarchical Consistency and Cascading State

State in this system propagates. When a proof is approved, the job advances from `PROOF_REVIEW` to `PLATED` without a separate call; when an invoice reaches `PAID`, the job's `billing_status` moves to `SETTLED`, and if the job has already been `FULFILLED`, its `production_status` simultaneously moves to `CLOSED`. The system never leaves a parent in a state inconsistent with its children: cancelling a job in `PRESS_SCHEDULED` cancels every `SCHEDULED` press run of that job and releases their lot reservations; completing the last `QUEUED` bindery ticket of a job moves the job to `READY_TO_SHIP`. Each cascade updates the touched entities' `version` and `updated_at` fields. Reverse reads of these relationships are performed through filtered list endpoints — for example, listing jobs by `gang_run_id` or by `parent_job_id` — rather than through nested URL hierarchies, because all resources are top-level.

### 2.9. Status Codes

Creating a new, stand-alone resource returns `201 Created`. Mutations of an existing resource — state transitions, revisions, payments, receipts, membership changes — return `200 OK`. Error responses use the 4xx codes named in §5.

## 3. Business Logic & Workflows

### 3.1. Customers and the Credit Posture

A `PlantManager` onboards a customer by creating a `Customer` record with a `name`, a `credit_limit_cents` expressed in integer cents, and optionally a `default_tolerance_pct` used to set the overrun/underrun tolerance on each accepted job; when omitted, `default_tolerance_pct` is 5. Customers can be listed and filtered by `posture`.

Every customer carries two continuously recomputed quantities. The `exposure_cents` is the sum of `amount_outstanding_cents` across all of the customer's invoices in `ISSUED`, `PARTIALLY_PAID`, or `DISPUTED` status, plus the sum of `total_price_cents` across the customer's jobs whose `billing_status` is `UNBILLED` and whose `production_status` is neither `CLOSED` nor `CANCELLED`. The customer's `posture` is `ACTIVE` when `exposure_cents` is less than or equal to `credit_limit_cents`, and flips to `CREDIT_HOLD` exactly when exposure strictly exceeds the credit limit — equality stays `ACTIVE`. The posture gates new work: a customer in `CREDIT_HOLD` cannot accept an estimate, and the attempt is rejected with `ERR_CREDIT_HOLD` (HTTP 409). A customer also accumulates a `reprint_credit_balance_cents` — the unapplied remainder of reprint credits not absorbed by an invoice at adjudication time — which starts at 0 and grows or shrinks as reprint claims are resolved and as `PlantManager` operators apply credits to open invoices.

### 3.2. Estimating: Signatures, Impressions, and Provisional Pricing

An `Estimator` creates an estimate in `DRAFT` status with a `customer_id`, a free-form `job_name`, the `quantity_ordered` (at least 1 piece), a `press_type` of either `WEB` or `SHEETFED`, a `binding_method` of `SADDLE_STITCH`, `PERFECT_BIND`, `CASE_BIND`, or `PLASTIC_COIL`, a `fulfillment_type` of `SHIP` or `MAIL`, the customer's `due_date` in ISO 8601, the `press_spoilage_pct` and `bindery_spoilage_pct` (each at least 0), an optional `included_proof_rounds` (default 2), an optional `quote_valid_days` (default 30), an optional `finishing_options` array (default empty), and a non-empty `signatures` array. Each signature entry names the signature and carries its `pages`, its `up_count` (at least 1), its `paper_stock_id`, its `make_ready_cents` (at least 0), and its `rate_per_thousand_cents` (at least 0). Finishing options are drawn from `PERF`, `SCORE`, `UV_COAT`, `LAMINATE`, `FOIL`, and `DIE_CUT`.

From these inputs the server derives the full pricing immediately, on both create and revise. Impressions are computed per signature: each signature's impression count is `quantity_ordered` divided by that signature's `up_count`, rounded up to a whole impression, and the resulting per-signature impressions appear in the `impressions_per_signature` array in the same order as the submitted `signatures`. The `total_impressions` is the sum of those per-signature impressions. Running cost is computed per signature as the signature's impressions multiplied by its `rate_per_thousand_cents` and divided by 1000, with the division rounded half-up to a whole cent per signature; only after each per-signature running cost has been rounded are they summed into `running_cost_cents` — rounding the sum of unrounded values is forbidden. Make-ready is simpler: `make_ready_total_cents` is the sum of each signature's `make_ready_cents`.

Paper is priced through a separate compounding path. For each signature, the press-stage sheet count is that signature's impressions multiplied by one plus `press_spoilage_pct` hundredths, rounded up to a whole sheet. The bindery-stage sheet count is then the press-stage count multiplied by one plus `bindery_spoilage_pct` hundredths, again rounded up. The compounding order — ceiling after the press stage, then ceiling after the bindery stage — is pinned, and a single combined multiplier is forbidden. The sum of those per-signature bindery-stage counts across all signatures is `paper_sheets_total`. Paper cost in cents, `paper_cost_cents`, is the per-signature sheet count multiplied by that signature's referenced stock's `cost_per_sheet_cents`, summed across signatures — an integer multiplication with no rounding.

Finishing is a flat-fee schedule. `finishing_cost_cents` is the sum of the per-option flat fee for every entry in `finishing_options`: `PERF` costs 18000 cents, `SCORE` 12000, `UV_COAT` 40000, `LAMINATE` 55000, `FOIL` 75000, and `DIE_CUT` 60000. The `subtotal_cents` is the sum of `make_ready_total_cents`, `running_cost_cents`, `paper_cost_cents`, and `finishing_cost_cents`. A volume discount is then applied as a tiered percentage keyed on the pre-discount subtotal: a subtotal below 500000 cents earns `discount_pct` of 0, a subtotal at or above 500000 but strictly below 2000000 cents earns 3, and a subtotal at or above 2000000 cents earns 5. The `total_price_cents` is the subtotal multiplied by one minus `discount_pct` hundredths, rounded half-up to a whole cent. An `expires_at` field is null while the estimate is in `DRAFT`; `quoted_at` is likewise unset until quoting.

An `Estimator` revises a `DRAFT` estimate with an optimistic-concurrency guard. The request must carry `expected_estimate_version` matching the estimate's current `version`, and may touch any subset of `quantity_ordered`, `signatures`, `finishing_options`, `press_spoilage_pct`, `bindery_spoilage_pct`, `due_date`, `quote_valid_days`, `press_type`, `binding_method`, `fulfillment_type`, and `included_proof_rounds`. A stale version is rejected with `ERR_STALE_VERSION`; a successful revision recomputes every derived pricing field and bumps the estimate's `version`. Estimates may be listed and filtered by `customer_id` and `status`; a `Customer` reading the list sees only their own estimates.

When the `Estimator` sends the quote, the estimate moves `DRAFT → QUOTED`, `quoted_at` is stamped with the current logical clock, `expires_at` is computed as `quoted_at` plus `quote_valid_days` days, and the estimate's `version` increments. Both `quoted_at` and `expires_at` are rendered as ISO 8601 UTC timestamps with three fractional digits — the same format as `created_at`. Quoting requires the estimate to have at least one signature, which is guaranteed by create validation.

### 3.3. Accept, Decline, Expire: From Estimate to Job

A `Customer` accepts a `QUOTED` estimate. The server enforces accept-time preconditions in a specific order: ownership first (the acting customer's `id` must equal the estimate's `customer_id`, else `ERR_NOT_OWN_RESOURCE`), then expiry (if the current clock is past `expires_at`, the estimate is transitioned to `EXPIRED` and the call fails with `ERR_ESTIMATE_EXPIRED`), then credit posture (the customer's `posture` must be `ACTIVE`, else `ERR_CREDIT_HOLD`). On a successful accept, the system creates a `Job` snapshotting the estimate: `estimate_id` is set, `parent_job_id` is null, `customer_id` is denormalized from the estimate, `zero_charge` is false, `quantity_ordered`, `due_date`, `press_type`, `fulfillment_type`, `binding_method`, the `signatures` array, `press_spoilage_pct`, `bindery_spoilage_pct`, `included_proof_rounds`, `total_impressions`, `make_ready_total_cents`, `total_price_cents`, `discount_pct`, and `subtotal_cents` are all copied across, and `tolerance_pct` is the customer's `default_tolerance_pct` at the moment of acceptance. The job begins with `production_status` `PREPRESS` and `billing_status` `UNBILLED`. The job's `gang_run_id`, `allocated_make_ready_cents`, and `delivered_quantity` are all null at this point, and `proof_rounds_used` starts at 0. Accepting bumps the estimate's `version` by 1 and immediately triggers recomputation of the customer's `exposure_cents` and `posture`, because the new `UNBILLED` job's `total_price_cents` now counts against the credit limit.

Decline is simpler: the same ownership precondition applies, the estimate moves `QUOTED → DECLINED`, and its `version` increments. Expiry is system-driven: any time the logical clock has advanced past `expires_at` — observed at the next accept attempt or on access after a clock advance — the estimate transitions `QUOTED → EXPIRED` and its `version` increments. Both `DECLINED` and `EXPIRED` are terminal, as is `ACCEPTED`.

### 3.4. Prepress Proofs and the Revision Loop

A `PrepressOperator` uploads a proof for a job by submitting the `job_id` and a `file_uri`. The job must be in `PREPRESS` or `PROOF_REVIEW`. The new proof enters in `AWAITING_CUSTOMER` status. Its `round_number` is one more than the maximum existing `round_number` for the job, or 1 for the first proof; `decided_at` is null until the customer decides. Each upload increments the job's `proof_rounds_used` by 1. If a prior proof of the same job is currently in `AWAITING_CUSTOMER` or `CHANGES_REQUESTED`, that prior proof is moved to `SUPERSEDED`. On the very first upload for a job, the job transitions `PREPRESS → PROOF_REVIEW`, bumping its `version`.

A `Customer` acts on an `AWAITING_CUSTOMER` proof of their own job — both approve and request-changes require that the acting customer's `id` match the job's `customer_id` (else `ERR_NOT_OWN_RESOURCE`) and that the job currently be in `PROOF_REVIEW` (else `ERR_JOB_INVALID_STATE`). Approving moves the proof `AWAITING_CUSTOMER → APPROVED`, sets `decided_at`, bumps the proof's `version`, and drives the job `PROOF_REVIEW → PLATED`. Requesting changes — optionally with `notes` — moves the proof `AWAITING_CUSTOMER → CHANGES_REQUESTED`, sets `decided_at`, and bumps the proof's `version`; the job stays in `PROOF_REVIEW`, and the cycle continues when the prepress operator uploads a new proof, which supersedes the prior one. Actions on a proof no longer in `AWAITING_CUSTOMER` are rejected with `ERR_PROOF_NOT_AWAITING`. On approve and request-changes this proof-state check is evaluated after the ownership check but before the job's `PROOF_REVIEW` requirement, so a request that would fail both state checks yields `ERR_PROOF_NOT_AWAITING`. Proofs may be listed filtered by `job_id` and `status`.

### 3.5. Paper Catalog, Purchase Orders, and Lot Ledger

A `PurchasingManager` maintains the paper catalog. Creating a `PaperStock` requires a `name` (for example, an 80-pound gloss text), a `grade` of `COATED`, `UNCOATED`, or `NEWSPRINT`, a `cost_per_sheet_cents` of at least 0, a `reorder_threshold_sheets` of at least 0, and a `reorder_quantity_sheets` of at least 1. The stock's `available_sheets` is a derived quantity: the sum of `remaining_sheets` across all lots of that stock.

Paper enters the plant through purchase orders. A `PurchasingManager` creates a `PaperPurchaseOrder` with a `paper_stock_id`, an `ordered_sheets` of at least 1, and a `cost_per_sheet_cents` of at least 0; the order lands in `ORDERED` status with `received_sheets_total` at 0 and `source` `MANUAL`. A separate `source` value, `AUTO_REPLENISH`, marks orders the system itself creates — see the auto-replenishment rule under press-run completion. Receipts against an order accept `sheets_received` and optionally `sheets_damaged`. Over-receipt is capped: cumulative `received_sheets_total` plus the new `sheets_received` may not exceed `ordered_sheets` multiplied by 1.10 and rounded down to a whole sheet — exceeding that cap is rejected with `ERR_OVER_RECEIPT` (HTTP 422). A receipt that leaves `received_sheets_total` still below `ordered_sheets` moves the order `ORDERED → PARTIALLY_RECEIVED` (or keeps it in `PARTIALLY_RECEIVED` on subsequent partial receipts); a receipt that reaches or exceeds `ordered_sheets` moves the order to `RECEIVED`. Each receipt updates the order's paper lot: the `PaperLot` for this order is created on first receive — one lot per purchase order — and reused thereafter, with `received_sheets` incremented by `sheets_received` and `damaged_sheets` incremented by `sheets_damaged`. The lot's `remaining_sheets` is a conservation invariant: `received_sheets` minus `reserved_sheets` minus `consumed_sheets` minus `damaged_sheets`. The stock's `available_sheets` is recomputed on every receipt. Every receive bumps the purchase order's `version`.

A purchase order may be cancelled from `ORDERED` or `PARTIALLY_RECEIVED`; a `PARTIALLY_RECEIVED` order's existing lot is preserved unchanged when the order is cancelled, because no further receives are possible and the conservation invariant is preserved. Receive or cancel attempted on an order already in `RECEIVED` or `CANCELLED` is rejected with `ERR_PO_STATE`. Lots can be listed filtered by `paper_stock_id` or `paper_purchase_order_id`; orders can be listed filtered by `paper_stock_id`, `status`, or `source`.

### 3.6. Presses and Solo Press Runs

A `PlantManager` registers a `Press` with a `name`, a `press_type` of `WEB` or `SHEETFED`, a `rated_impressions_per_hour` of at least 1, a `make_ready_minutes_base` of at least 0, a `washup_buffer_minutes` of at least 0, and an optional `status` defaulting to `AVAILABLE` (the alternative is `DOWN`). Presses may be listed filtered by `press_type`.

A `PressScheduler` schedules a solo press run by supplying the `press_id`, the target `job_id`, the `run_quantity`, the `scheduled_start`, and the OCC field `expected_press_version` matching the press's current `version` — a stale press version is rejected with `ERR_STALE_VERSION`. Exactly one of `job_id` or `gang_run_id` is set on any given run; for a solo run, `gang_run_id` is null and `run_quantity` must be at least 1 and at most the job's `quantity_ordered`. The press's `press_type` must match the job's `press_type`, else `ERR_PRESS_TYPE_MISMATCH`. The press must be `AVAILABLE`, else `ERR_PRESS_UNAVAILABLE`. The job must be in `PLATED` state.

Duration and window are derived quantities. For a solo run, `planned_impressions` is the sum across the job's signatures of `run_quantity` divided by the signature's `up_count`, rounded up to a whole impression per signature. The `duration_minutes` is the press's `make_ready_minutes_base` plus the run's `planned_impressions` divided by the press's `rated_impressions_per_hour` and multiplied by 60, with that division-multiplication rounded up to a whole minute. The `scheduled_end` is `scheduled_start` plus `duration_minutes`. The `planned_sheets` reserved for the run is the spoilage-compounded sheet count — for each signature, the press-stage sheets are the signature's impressions multiplied by one plus the press spoilage percent, rounded up; the bindery-stage sheets are the press-stage sheets multiplied by one plus the bindery spoilage percent, rounded up — summed across signatures.

Window conflicts are evaluated against other `SCHEDULED` runs on the same press. Each existing run occupies the half-open interval from its `scheduled_start` to its `scheduled_end` plus the press's `washup_buffer_minutes` — a trailing washup buffer. A candidate run conflicts when its `scheduled_start` is strictly before some existing run's buffered end and its `scheduled_end` is strictly after that same run's start; such a conflict is rejected with `ERR_PRESS_WINDOW_CONFLICT`. A candidate starting exactly at an existing run's buffered end is allowed. `COMPLETE` and `CANCELLED` runs occupy nothing.

Scheduling a run also reserves paper. Reservations draw lots of the required stocks first-in-first-out by lot `created_at` ascending — earliest first, with ties broken by `created_at` only and never by id. Drawing across lots continues until the planned sheets are satisfied; if the aggregate `remaining_sheets` across lots of a required stock cannot cover the reservation, scheduling is rejected with `ERR_PAPER_INSUFFICIENT`. Successful scheduling transitions the job `PLATED → PRESS_SCHEDULED`, bumps the press's `version` by 1, and records the new run in `SCHEDULED` status.

A run is completed by a `PressScheduler` submitting actuals: `gross_impressions`, `sheets_used`, and `waste_sheets`. Waste cannot exceed usage — `waste_sheets` greater than `sheets_used` is rejected with `ERR_VALIDATION`. If `sheets_used` exceeds the reserved amount, the unreserved remainder must be coverable from available lots in FIFO order, else the completion is rejected with `ERR_PAPER_INSUFFICIENT`. On a successful completion the run moves `SCHEDULED → COMPLETE`: reserved sheets convert from reserved to consumed per lot according to the FIFO draw recorded at schedule time, any excess beyond the reservation draws additional sheets FIFO by lot `created_at` ascending, and any unused reservation is released. If no other `SCHEDULED` press run references the same job, the job transitions `PRESS_SCHEDULED → BINDERY` — for a gang run, all member jobs transition together, and the gang run itself moves `LOCKED → CONSUMED`. Consumption then triggers auto-replenishment: for each stock consumed, `available_sheets` is recomputed, and if it has dropped strictly below the stock's `reorder_threshold_sheets` and no open auto-replenishment purchase order (one in `ORDERED` or `PARTIALLY_RECEIVED` with `source` `AUTO_REPLENISH`) already exists for the stock, the system creates one with `ordered_sheets` equal to the stock's `reorder_quantity_sheets`, `cost_per_sheet_cents` equal to the stock's `cost_per_sheet_cents`, `source` `AUTO_REPLENISH`, and status `ORDERED`. Completion bumps the run's `version`.

A `PressScheduler` may also cancel a `SCHEDULED` run. Cancelling releases all of the run's lot reservations — reserved sheets decrease, remaining sheets rise accordingly — and bumps the run's `version`. A solo job whose run is cancelled remains in `PRESS_SCHEDULED`; the system does not auto-revert. The system likewise cancels runs when their owning job is cancelled.

### 3.7. Gang Runs: Consolidation, Allocation, and the Lock/Unlock Cycle

A gang run consolidates compatible jobs onto one press sheet so that make-ready time is shared. A `PressScheduler` creates a `GangRun` in `FORMING` status by naming the shared `paper_stock_id`, the shared `press_type`, and an `anchor_due_date`. The `members` array starts empty, and `make_ready_total_cents` is null until lock.

Adding a member is an OCC-guarded write: the request carries the `job_id` and `expected_gang_run_version` matching the gang's current `version`, with stale versions rejected via `ERR_STALE_VERSION`. Membership mutations are permitted only while the gang is `FORMING`; attempting one against a `LOCKED` or `CONSUMED` gang is rejected with `ERR_GANG_NOT_FORMING`. A job is eligible only if every signature of the job uses the gang's `paper_stock_id`, the job's `press_type` matches the gang's `press_type`, the job is not already a member of another gang, and the job's `production_status` is `PLATED` — any violation is rejected with `ERR_GANG_INELIGIBLE_JOB`. The job's `due_date` must also fall within three days of the gang's `anchor_due_date`, inclusive on both sides; a job outside that window is rejected with `ERR_GANG_DUE_WINDOW_EXCEEDED`. A successful add appends a member entry to the gang's `members` array carrying the member's `job_id`, the timestamp `added_at` at which the membership was recorded, and an `allocated_make_ready_cents` field that remains null until lock; the add also sets the job's `gang_run_id` and bumps both the gang's and the job's `version`. Removal from a `FORMING` gang is the mirror operation: it carries `job_id` and `expected_gang_run_version`, clears the job's `gang_run_id`, and bumps the gang's `version`.

Locking a gang freezes its membership and prices the shared make-ready. Locking requires at least 2 members (else `ERR_GANG_TOO_SMALL`) and at most 6 (else `ERR_GANG_FULL`), and every member job must still be in `PLATED` (else `ERR_GANG_INELIGIBLE_JOB`). On lock, the gang transitions `FORMING → LOCKED`, its `make_ready_total_cents` becomes the maximum of the members' individual `make_ready_total_cents` values, and each member's `allocated_make_ready_cents` is computed by a waterfall. Each member's raw share is the gang's `make_ready_total_cents` multiplied by that member's `total_impressions` and divided by the sum of all members' `total_impressions`; each share is rounded half-up to a whole cent; the remainder — the gang make-ready total minus the sum of the rounded shares, which may be negative — is assigned to the member whose job has the earliest `created_at` (millisecond precision makes ties a non-issue; ids are never used as a tiebreak). The conservation invariant holds exactly: the sum of `allocated_make_ready_cents` across members equals the gang's `make_ready_total_cents`. Locking bumps the gang's `version` and increments each member job's `version` as its allocation is set.

Unlocking is permitted while no `SCHEDULED` press run references the gang — attempting unlock with one present is rejected with `ERR_GANG_HAS_SCHEDULED_RUN`. A successful unlock moves the gang `LOCKED → FORMING`, clears every member's `allocated_make_ready_cents` back to null, clears the gang's `make_ready_total_cents` back to null, and bumps the gang's `version`. When a press run referencing a `LOCKED` gang completes, the gang moves `LOCKED → CONSUMED`, which is terminal.

A gang press run is created by a `PressScheduler` supplying `gang_run_id` instead of `job_id`. The gang must be `LOCKED` — scheduling against a non-locked gang is rejected with `ERR_GANG_NOT_LOCKED`. The gang run's `run_quantity` must equal the sum of the member jobs' `quantity_ordered` values exactly, else `ERR_GANG_RUN_QUANTITY_MISMATCH`. The press's `press_type` must match the gang's `press_type` (else `ERR_PRESS_TYPE_MISMATCH`), the press must be `AVAILABLE`, the same press-window conflict rule applies, and paper is reserved FIFO across the stocks required by member jobs' signatures. For a gang run, `planned_impressions` is the sum of the member jobs' `total_impressions` values, and `planned_sheets` is the sum of the spoilage-compounded per-signature sheet counts across all member jobs. Creating the gang run transitions every member job `PLATED → PRESS_SCHEDULED` and bumps the press's `version`. Gang runs may be listed filtered by `status` and `paper_stock_id`.

### 3.8. Bindery Routing and Completion

Bindery work is modelled as a per-job routing of `BinderyTicket` records. A `PlantManager` creates a ticket with the `job_id`, an `operation` drawn from `FOLD`, `STITCH`, `TRIM`, `PERF`, `SCORE`, `UV_COAT`, `LAMINATE`, `FOIL`, `DIE_CUT`, `COLLATE`, and `PAD`, and a `sequence_no` of at least 1 that is unique within the job. Ticket creation is allowed while the job's `production_status` is anywhere from `PREPRESS` through `BINDERY`. A new ticket enters in `QUEUED`.

Completion is strictly ordered. A `PlantManager` completes a ticket by submitting `pieces_completed` (at least 0). The job must currently be in `BINDERY` (else `ERR_JOB_INVALID_STATE`), and every ticket of the same job with a lower `sequence_no` must already be `COMPLETE` — completing out of order is rejected with `ERR_BINDERY_SEQUENCE`. When the completing ticket is the last non-`COMPLETE` ticket of the job, the job transitions `BINDERY → READY_TO_SHIP`. Each completion bumps the ticket's `version`. Tickets may be listed filtered by `job_id` and `status`.

### 3.9. Mail Drops: Presort Tiers, Daily Capacity, and Drop

For a job whose `fulfillment_type` is `MAIL`, a `MailSpecialist` plans a `MailDrop` by supplying the `job_id`, a `drop_date` as a calendar date in `YYYY-MM-DD` form, a `destination_entry` of `NONE`, `BMC`, `SCF`, or `DDU`, an informational `piece_weight_oz`, and a non-empty `zip_counts` array of entries, each pairing a `zip5` five-digit ZIP prefix string with a `pieces` count of at least 1. Creating a mail drop on a job whose `fulfillment_type` is not `MAIL` is rejected with `ERR_FULFILLMENT_CHANNEL_MISMATCH`. The drop lands in `PLANNED` with `total_pieces` computed as the sum of the per-entry piece counts; `tier_breakdown` and `postage_cents` are null until presort.

Presorting computes postage through a tier waterfall. The rates are 24 cents per piece at the five-digit tier, 28 cents per piece at the three-digit tier, and 31 cents per piece at the AADC tier, with a tier minimum of 150 pieces and a global minimum of 500 total pieces. The waterfall runs in order. First, if the drop's `total_pieces` is below the global minimum of 500, every piece is priced at the AADC rate and the waterfall stops. Otherwise, each `zip_counts` entry whose piece count is at least 150 qualifies entirely at the five-digit rate, and its pieces are removed from the pool. The remaining pieces are then pooled by the first three digits of the ZIP prefix, and each three-digit pool with at least 150 pieces qualifies entirely at the three-digit rate. All remaining pieces fall to the AADC rate. The `tier_breakdown` records the resulting `five_digit_pieces`, `three_digit_pieces`, and `aadc_pieces`, and `postage_cents` is `five_digit_pieces` times 24 plus `three_digit_pieces` times 28 plus `aadc_pieces` times 31 — integer arithmetic with no rounding.

Presort is also where the daily capacity check runs. The committed volume for a calendar date is the sum of `total_pieces` across all mail drops in `PRESORTED` or `DROPPED` status sharing the same `drop_date`. Presorting is rejected with `ERR_MAIL_CAPACITY_EXCEEDED` exactly when committed plus this drop's `total_pieces` would exceed 100000 pieces; equality is allowed. The capacity is a per-calendar-date aggregate, not a pairwise interval check — adjacent dates are independent. A successful presort moves the drop `PLANNED → PRESORTED` and bumps its `version`.

Executing the drop requires the job to be in `READY_TO_SHIP` with `fulfillment_type` `MAIL` (else `ERR_JOB_INVALID_STATE`). The drop moves `PRESORTED → DROPPED`, the job transitions `READY_TO_SHIP → FULFILLED`, and the job's `delivered_quantity` is set to the drop's `total_pieces`. Mail drops may be listed filtered by `job_id`, `status`, or `drop_date`.

### 3.10. Delivery for Ship Jobs and the Fulfillment Boundary

For a job whose `fulfillment_type` is `SHIP`, fulfillment is recorded by a `PlantManager` calling record-delivery with a `delivered_quantity` of at least 1. The job must be in `READY_TO_SHIP`, and recording delivery on a job whose `fulfillment_type` is not `SHIP` is rejected with `ERR_FULFILLMENT_CHANNEL_MISMATCH`. The job transitions `READY_TO_SHIP → FULFILLED`, stores the `delivered_quantity`, and bumps its `version`. This is the mirror of the mail-drop path: `SHIP` jobs are fulfilled by an explicit delivery record, `MAIL` jobs are fulfilled by the drop transition, and the two channels may not be crossed.

### 3.11. Job Cancellation and Its Compensation Cascade

A `PlantManager` may cancel a job from `PREPRESS`, `PROOF_REVIEW`, `PLATED`, or `PRESS_SCHEDULED`, optionally supplying a `reason`. Cancelling from `BINDERY` or later is rejected with `ERR_JOB_PAST_CANCEL_POINT`. A job that is a member of a `LOCKED` or `CONSUMED` gang cannot be cancelled — the attempt is rejected with `ERR_JOB_IN_LOCKED_GANG`.

The compensation cascade depends on the stage. Cancelling from `PREPRESS` incurs no fee: the job moves to `CANCELLED`, its `billing_status` becomes `NOT_BILLABLE`, and no invoice is created. Cancelling from `PROOF_REVIEW` is likewise fee-free and additionally supersedes any non-terminal proofs of the job — proofs in `AWAITING_CUSTOMER` or `CHANGES_REQUESTED` move to `SUPERSEDED`. Cancelling from `PLATED` first removes the job from any `FORMING` gang it belongs to — the job is removed from the gang's `members` and the gang's `version` increments — and then auto-creates a `CANCELLATION_FEE` invoice in `ISSUED` status whose `total_due_cents` is exactly the job's `make_ready_total_cents`; the job's `billing_status` becomes `INVOICED`. Cancelling from `PRESS_SCHEDULED` performs the same fee invoice creation and additionally cancels every `SCHEDULED` press run of the job, releasing each run's lot reservations — reserved sheets decrease and remaining sheets increase accordingly. In every case the customer's `exposure_cents` and `posture` are recomputed, and the job's `version` increments.

### 3.12. Invoicing: Tolerance Billing, Proof Overage, and Postage

A `PlantManager` generates a production invoice for a job by submitting its `job_id`. The job must be `FULFILLED` and `UNBILLED`, and a job may carry only one production invoice. These preconditions are enforced in a fixed order: a job whose `production_status` is not `FULFILLED` is rejected with `ERR_JOB_INVALID_STATE`; a `FULFILLED` job whose `billing_status` is not `UNBILLED` is rejected with `ERR_INVOICE_STATE`; and only then does the one-invoice rule apply — generating a second production invoice is rejected with `ERR_DUPLICATE_INVOICE`. Because issuing the first production invoice moves the job's `billing_status` to `INVOICED`, the duplicate rule fires in practice only while the first production invoice is still in `DRAFT`. The new invoice is created in `DRAFT` status, with `kind` `PRODUCTION`, `customer_id` denormalized from the job, `quantity_ordered` and `delivered_quantity` snapshotted from the job, `amount_paid_cents` and `credit_applied_cents` starting at 0, and `postage_cents` set to the sum of `postage_cents` over the job's mail drops in `DROPPED` status at generation time (zero when there are none).

The billable quantity is tolerance-adjusted. Let `Q` be the job's `quantity_ordered`, `D` its `delivered_quantity`, and `t` its `tolerance_pct`. The allowed deviation is `Q` multiplied by `t` and divided by 100, rounded down to a whole piece. The tolerance band runs from `Q` minus the allowed deviation to `Q` plus the allowed deviation, both bounds inclusive. When delivery exceeds the upper bound, `billable_quantity` is capped at `Q` plus the allowed deviation — pieces above the cap are free — and `shortage_credit_cents` is 0. When delivery falls below the lower bound, `billable_quantity` is `D`, and a shortage credit is computed as the job's total basis multiplied by the number of missing-to-band pieces (that is, `Q` minus the allowed deviation minus `D`) and divided by `Q`, rounded half-up to a whole cent. When delivery is inside the inclusive band, `billable_quantity` is `D` and `shortage_credit_cents` is 0.

The job's total basis for billing is `job.total_price_cents` for a non-gang job, or a gang-adjusted total when the job was ganged. The gang-adjusted total re-runs the provisional pricing pipeline with the member's `allocated_make_ready_cents` substituted for the standalone make-ready total, and re-derives the discount tier from the adjusted subtotal before applying it. Only the make-ready component is substituted — the running, paper, and finishing components carry over unchanged — so the adjusted subtotal is exactly the job's snapshot `subtotal_cents` minus its standalone `make_ready_total_cents` plus the member's `allocated_make_ready_cents`; the discount tier is then re-derived from that adjusted subtotal using the same thresholds as at estimate time, and the gang-adjusted total is the adjusted subtotal multiplied by one minus the re-derived `discount_pct` hundredths, rounded half-up to a whole cent. The invoice's `gang_make_ready_allocated_cents` carries the member's allocation when ganged and is null otherwise. The `base_amount_cents` is the job total basis multiplied by `billable_quantity` and divided by `quantity_ordered`, rounded half-up to a whole cent. Proof overage is charged when the job consumed more rounds than included: `proof_overage_cents` is the excess of `proof_rounds_used` over `included_proof_rounds`, floored at zero, multiplied by 12500 cents per excess round. The invoice's `total_due_cents` is `base_amount_cents` plus `postage_cents` plus `proof_overage_cents` minus `shortage_credit_cents`. For a `CANCELLATION_FEE` invoice, `total_due_cents` is exactly the job's `make_ready_total_cents` and no tolerance billing math runs.

The `amount_outstanding_cents` is a monetary conservation invariant: `total_due_cents` minus `amount_paid_cents` minus `credit_applied_cents`. A `PlantManager` issues a `DRAFT` invoice, moving it `DRAFT → ISSUED`, which moves the job's `billing_status` from `UNBILLED` to `INVOICED`, recomputes the customer's exposure and posture, and bumps the invoice's `version`. Invoice operations attempted from a state that does not support them — paying a `DRAFT` invoice, disputing a `PAID` invoice, issuing an already-issued invoice — are rejected with `ERR_INVOICE_STATE`.

### 3.13. Payments, Credit Application, and Disputes

A `PlantManager` records a payment against an invoice by submitting `amount_cents`. The invoice must be in `ISSUED`, `PARTIALLY_PAID`, or `DISPUTED`. The payment amount must be at least 1 and at most the invoice's `amount_outstanding_cents`; a payment outside that range is rejected with `ERR_OVERPAYMENT` (HTTP 422). A partial payment — one strictly below the outstanding amount — moves the invoice to `PARTIALLY_PAID`, increments `amount_paid_cents` by the payment, recomputes `amount_outstanding_cents`, and recomputes the customer's exposure and posture. A payment covering the exact outstanding amount moves the invoice to `PAID`, which cascades: the job's `billing_status` becomes `SETTLED`, and if the job's `production_status` is `FULFILLED`, the job closes to `CLOSED`. The same `SETTLED`/close cascade fires from `ISSUED` and from `PARTIALLY_PAID`. The `SETTLED` billing transition is evaluated on every payment or credit application, so the cascade fires the moment the last open invoice of a job reaches `PAID`.

Applying reprint credit is the parallel mechanism that draws down the customer's `reprint_credit_balance_cents`. A `PlantManager` applies credit by submitting `amount_cents`. The amount may not exceed the smaller of the customer's `reprint_credit_balance_cents` and the invoice's `amount_outstanding_cents`; violating that bound is rejected with `ERR_CREDIT_APPLICATION_INVALID` (HTTP 422). A successful application increments the invoice's `credit_applied_cents`, decrements the customer's balance, recomputes the outstanding amount, and triggers the same `PAID` cascade when outstanding reaches zero.

Either the `Customer` who owns the invoice or a `PlantManager` may dispute an `ISSUED` invoice; the customer-side attempt requires ownership (else `ERR_NOT_OWN_RESOURCE`). The request carries a `reason`. Disputing moves the invoice `ISSUED → DISPUTED` and bumps its `version`; a disputed invoice remains payable — both partial and exact payments apply from `DISPUTED` as they do from `ISSUED`, with the same cascades.

### 3.14. Reprint Claims: Filing, Review, and Segregated Adjudication

A `Customer` files a reprint claim against one of their own jobs whose `production_status` is `FULFILLED` or `CLOSED`. The request carries the `job_id`, a `claimed_defect` drawn from `MISREGISTER`, `COLOR_SHIFT`, `TRIM_ERROR`, `BINDING_DEFECT`, `PAPER_STOCK_WRONG`, and `SHORTAGE`, and a `defect_qty`. The defect quantity must be at least 1 and at most the job's `delivered_quantity`; out-of-range values are rejected with `ERR_DEFECT_QTY_INVALID` (HTTP 422). Only one open claim may exist per job — filing while another claim for the same job is in `FILED` or `UNDER_REVIEW` is rejected with `ERR_CLAIM_ALREADY_OPEN`. A new claim enters in `FILED` with `invoice_id`, `reviewed_by`, `resolution`, `liability_pct`, `provisional_credit_cents`, `final_credit_cents`, and `reprint_job_id` all null. Claim operations attempted from a state that does not support them — approving a claim still in `FILED`, reviewing a claim already `UNDER_REVIEW` — are rejected with `ERR_CLAIM_STATE`.

A `PlantManager` moves a `FILED` claim to `UNDER_REVIEW`, which stamps `reviewed_by` with the acting operator's `X-User-ID` and bumps the claim's `version`. Adjudication then requires a different `PlantManager`: both approve and deny are rejected with `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID` equals `reviewed_by`. Denial moves the claim from `UNDER_REVIEW` to the terminal `DENIED` state with a required `reason` and bumps the version. Approval moves the claim from `UNDER_REVIEW` to the terminal `APPROVED` state and requires a `resolution` of `REPRINT` or `CREDIT` together with a `liability_pct` of exactly 25, 50, or 100 (any other value is rejected with `ERR_VALIDATION`).

Approval with resolution `REPRINT` creates a reprint job: `parent_job_id` set to the original job's `id`, `estimate_id` null, `quantity_ordered` set to the claim's `defect_qty`, `zero_charge` true (such jobs are never invoiced), `billing_status` `NOT_BILLABLE`, `production_status` `PREPRESS`, `customer_id` denormalized from the parent job, and the specification fields — `due_date`, `press_type`, `fulfillment_type`, `binding_method`, `signatures`, `press_spoilage_pct`, `bindery_spoilage_pct`, `included_proof_rounds`, `tolerance_pct`, `total_impressions`, `make_ready_total_cents`, `total_price_cents`, `discount_pct`, `subtotal_cents` — snapshotted from the parent job. The claim's `reprint_job_id` is set to the new job's `id`.

Approval with resolution `CREDIT` first requires that the job's production invoice exist with status `ISSUED`, `PARTIALLY_PAID`, or `DISPUTED` and an `amount_outstanding_cents` strictly greater than zero; if none exists, the approval is rejected with `ERR_CLAIM_NO_OPEN_INVOICE`. The claim's `invoice_id` is bound to that invoice at approve time. Two credit figures are computed. The provisional credit — stored as `provisional_credit_cents` — is the invoice's `base_amount_cents` multiplied by `liability_pct` hundredths, multiplied by the claim's `defect_qty`, and divided by the invoice's `delivered_quantity`, rounded half-up; it keys off the base amount only, excluding postage and proof overage. The final credit — stored as `final_credit_cents` — is computed identically except that it keys off the invoice's `total_due_cents` rather than `base_amount_cents`, and is capped at `total_due_cents`; whenever postage or proof overage is non-zero the final figure diverges from the provisional one. The credit is issued in the same approval transaction: the amount applied to the invoice is the smaller of `final_credit_cents` and the invoice's `amount_outstanding_cents`; `credit_applied_cents` increases by the applied amount; if the invoice's outstanding reaches zero it moves to `PAID`; and any remainder — final credit minus applied — is added to the customer's `reprint_credit_balance_cents`. The `PAID` transition cascades as usual: the job's `billing_status` becomes `SETTLED`, a `FULFILLED` job closes to `CLOSED`, and the customer's exposure and posture are recomputed. Either resolution bumps the claim's `version`. Claims may be listed filtered by `job_id`, `invoice_id`, `reprint_job_id`, or `status`.

### 3.15. Job Lifecycle Overview and Reverse Reads

Taken end to end, a job's `production_status` walks `PREPRESS → PROOF_REVIEW → PLATED → PRESS_SCHEDULED → BINDERY → READY_TO_SHIP → FULFILLED → CLOSED`, with `CANCELLED` reachable from the four earliest states. The `billing_status` dimension evolves in parallel: `UNBILLED → INVOICED → SETTLED`, or `UNBILLED → NOT_BILLABLE` when a job is cancelled before any invoice or is created as a zero-charge reprint. Reprint jobs skip the estimate entirely and never enter the invoicing path. Jobs may be listed filtered by `customer_id`, `estimate_id`, `gang_run_id`, `parent_job_id`, `production_status`, or `billing_status`; a `Customer` sees only their own. Because all resources are top-level, reverse traversal — "which jobs belong to this gang," "which claims reference this invoice," "which reprint job came from this job" — is expressed through those filtered lists rather than through nested URLs.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources return `201 Created`. Operations that modify an existing resource — state transitions, revisions, payments, receipts, membership changes, applications of credit — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create customer | PlantManager |
| GET | `/customers/{id}` | Get customer (computed exposure/posture current) | Estimator, Customer, PrepressOperator, PressScheduler, PurchasingManager, MailSpecialist, PlantManager |
| GET | `/customers` | List customers (paginated; filter `posture`) | Estimator, Customer, PrepressOperator, PressScheduler, PurchasingManager, MailSpecialist, PlantManager |
| POST | `/estimates` | Create DRAFT estimate; all computed pricing fields resolved immediately | Estimator |
| GET | `/estimates/{id}` | Get estimate | Estimator, Customer, PlantManager |
| GET | `/estimates` | List estimates; Customer role sees own only | Estimator, Customer, PlantManager |
| PUT | `/estimates/{id}` | Revise DRAFT estimate (OCC on estimate version); recomputes all pricing | Estimator |
| POST | `/estimates/{id}/quote` | DRAFT → QUOTED | Estimator |
| POST | `/estimates/{id}/accept` | QUOTED → ACCEPTED; creates Job; expiry evaluated before fiscal | Customer |
| POST | `/estimates/{id}/decline` | QUOTED → DECLINED | Customer |
| GET | `/jobs/{id}` | Get job | Estimator, Customer, PrepressOperator, PressScheduler, PurchasingManager, MailSpecialist, PlantManager |
| GET | `/jobs` | List jobs with filters; Customer role sees own only | Estimator, Customer, PrepressOperator, PressScheduler, PurchasingManager, MailSpecialist, PlantManager |
| POST | `/jobs/{id}/record-delivery` | SHIP jobs: READY_TO_SHIP → FULFILLED with delivered quantity | PlantManager |
| POST | `/jobs/{id}/cancel` | Cancel job from PREPRESS/PROOF_REVIEW/PLATED/PRESS_SCHEDULED with compensation cascade | PlantManager |
| POST | `/proofs` | Upload proof; supersedes prior open proof; first upload moves job to PROOF_REVIEW | PrepressOperator |
| GET | `/proofs/{id}` | Get proof | Estimator, Customer, PrepressOperator, PlantManager |
| GET | `/proofs` | List proofs (filter by job) | Estimator, Customer, PrepressOperator, PlantManager |
| POST | `/proofs/{id}/approve` | Customer approves proof; job → PLATED | Customer |
| POST | `/proofs/{id}/request-changes` | Customer requests changes; proof → CHANGES_REQUESTED | Customer |
| POST | `/paper-stocks` | Create paper stock catalog entry | PurchasingManager |
| GET | `/paper-stocks/{id}` | Get paper stock (available_sheets current) | Estimator, PressScheduler, PurchasingManager, PlantManager |
| GET | `/paper-stocks` | List paper stocks | Estimator, PressScheduler, PurchasingManager, PlantManager |
| POST | `/paper-purchase-orders` | Create PO in ORDERED | PurchasingManager |
| GET | `/paper-purchase-orders/{id}` | Get PO | PurchasingManager, PlantManager |
| GET | `/paper-purchase-orders` | List POs | PurchasingManager, PlantManager |
| POST | `/paper-purchase-orders/{id}/receive` | Receive sheets (partial allowed; over-receipt capped); creates/updates lot | PurchasingManager |
| POST | `/paper-purchase-orders/{id}/cancel` | Cancel PO from ORDERED or PARTIALLY_RECEIVED; existing lot preserved | PurchasingManager |
| GET | `/paper-lots/{id}` | Get paper lot | PurchasingManager, PressScheduler, PlantManager |
| GET | `/paper-lots` | List lots (filter by stock or PO) | PurchasingManager, PressScheduler, PlantManager |
| POST | `/presses` | Create press | PlantManager |
| GET | `/presses/{id}` | Get press | PressScheduler, PlantManager |
| GET | `/presses` | List presses | PressScheduler, PlantManager |
| POST | `/press-runs` | Schedule press run (solo or gang); OCC on press version; reserves paper FIFO | PressScheduler |
| GET | `/press-runs/{id}` | Get press run | PressScheduler, PlantManager |
| GET | `/press-runs` | List press runs | PressScheduler, PlantManager |
| POST | `/press-runs/{id}/complete` | Complete run with actuals; consumes paper; advances jobs; triggers auto-replenishment | PressScheduler |
| POST | `/press-runs/{id}/cancel` | Cancel SCHEDULED run; releases reservations | PressScheduler |
| POST | `/gang-runs` | Create gang run in FORMING | PressScheduler |
| GET | `/gang-runs/{id}` | Get gang run incl. members and allocations | PressScheduler, PlantManager, Estimator |
| GET | `/gang-runs` | List gang runs | PressScheduler, PlantManager, Estimator |
| POST | `/gang-runs/{id}/members` | Add member job to FORMING gang (OCC on gang version) | PressScheduler |
| POST | `/gang-runs/{id}/remove-member` | Remove member job from FORMING gang (OCC on gang version) | PressScheduler |
| POST | `/gang-runs/{id}/lock` | FORMING → LOCKED; computes make-ready allocation | PressScheduler |
| POST | `/gang-runs/{id}/unlock` | LOCKED → FORMING when no SCHEDULED press run references the gang | PressScheduler |
| POST | `/bindery-tickets` | Create bindery routing step for a job | PlantManager |
| GET | `/bindery-tickets/{id}` | Get bindery ticket | PlantManager, PressScheduler |
| GET | `/bindery-tickets` | List bindery tickets (filter by job) | PlantManager, PressScheduler, Customer |
| POST | `/bindery-tickets/{id}/complete` | Complete ticket in ascending sequence order; last completion moves job to READY_TO_SHIP | PlantManager |
| POST | `/mail-drops` | Plan a mail drop for a MAIL-fulfillment job | MailSpecialist |
| GET | `/mail-drops/{id}` | Get mail drop | MailSpecialist, PlantManager, Customer |
| GET | `/mail-drops` | List mail drops | MailSpecialist, PlantManager, Customer |
| POST | `/mail-drops/{id}/presort` | Compute presort tiers + postage; enforces daily aggregate capacity | MailSpecialist |
| POST | `/mail-drops/{id}/drop` | Execute drop; MAIL job READY_TO_SHIP → FULFILLED | MailSpecialist |
| POST | `/invoices` | Generate PRODUCTION invoice (DRAFT) for a FULFILLED, UNBILLED job | PlantManager |
| GET | `/invoices/{id}` | Get invoice | PlantManager, Customer, Estimator |
| GET | `/invoices` | List invoices; Customer role sees own only | PlantManager, Customer, Estimator |
| POST | `/invoices/{id}/issue` | DRAFT → ISSUED | PlantManager |
| POST | `/invoices/{id}/payments` | Record payment (1..outstanding); exact outstanding → PAID | PlantManager |
| POST | `/invoices/{id}/apply-credit` | Apply customer reprint credit balance to an open invoice | PlantManager |
| POST | `/invoices/{id}/dispute` | ISSUED → DISPUTED | Customer, PlantManager |
| POST | `/reprint-claims` | Customer files claim on a FULFILLED/CLOSED own job | Customer |
| GET | `/reprint-claims/{id}` | Get claim | PlantManager, Customer |
| GET | `/reprint-claims` | List claims; Customer role sees own only | PlantManager, Customer |
| POST | `/reprint-claims/{id}/review` | FILED → UNDER_REVIEW; records reviewed_by | PlantManager |
| POST | `/reprint-claims/{id}/approve` | UNDER_REVIEW → APPROVED; approver differs from reviewer | PlantManager |
| POST | `/reprint-claims/{id}/deny` | UNDER_REVIEW → DENIED; denier differs from reviewer | PlantManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving endpoint) | PlantManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_OWN_RESOURCE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ESTIMATE_EXPIRED` | 409 |
| `ERR_CREDIT_HOLD` | 409 |
| `ERR_JOB_INVALID_STATE` | 409 |
| `ERR_JOB_PAST_CANCEL_POINT` | 409 |
| `ERR_JOB_IN_LOCKED_GANG` | 409 |
| `ERR_PROOF_NOT_AWAITING` | 409 |
| `ERR_PRESS_UNAVAILABLE` | 409 |
| `ERR_PRESS_TYPE_MISMATCH` | 409 |
| `ERR_PRESS_WINDOW_CONFLICT` | 409 |
| `ERR_PAPER_INSUFFICIENT` | 409 |
| `ERR_PO_STATE` | 409 |
| `ERR_OVER_RECEIPT` | 422 |
| `ERR_GANG_TOO_SMALL` | 409 |
| `ERR_GANG_FULL` | 409 |
| `ERR_GANG_NOT_FORMING` | 409 |
| `ERR_GANG_NOT_LOCKED` | 409 |
| `ERR_GANG_INELIGIBLE_JOB` | 409 |
| `ERR_GANG_DUE_WINDOW_EXCEEDED` | 409 |
| `ERR_GANG_HAS_SCHEDULED_RUN` | 409 |
| `ERR_GANG_RUN_QUANTITY_MISMATCH` | 409 |
| `ERR_BINDERY_SEQUENCE` | 409 |
| `ERR_MAIL_CAPACITY_EXCEEDED` | 409 |
| `ERR_FULFILLMENT_CHANNEL_MISMATCH` | 409 |
| `ERR_DUPLICATE_INVOICE` | 409 |
| `ERR_INVOICE_STATE` | 409 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_CREDIT_APPLICATION_INVALID` | 422 |
| `ERR_CLAIM_STATE` | 409 |
| `ERR_CLAIM_ALREADY_OPEN` | 409 |
| `ERR_CLAIM_NO_OPEN_INVOICE` | 409 |
| `ERR_DEFECT_QTY_INVALID` | 422 |

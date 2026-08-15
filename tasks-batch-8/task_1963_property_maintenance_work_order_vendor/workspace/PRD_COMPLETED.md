# Property Maintenance Work Order & Vendor Dispatch API — Product Requirements Document

## 1. Introduction

Residential property operations live and die by response time. A burst pipe at 2 a.m., an air-conditioning failure in the first heat wave of August, a broken intercom in a lobby full of packages: every one of these starts as a phone call or portal message from a resident, and every one becomes a liability if the maintenance team cannot prove when it was acknowledged, who it was assigned to, and what was done about it. This document specifies a REST API for a property maintenance department that receives resident repair requests, classifies them by priority, assigns them to an in-house technician or an external vendor, tracks the parts they consume and the purchases they need, and — where a resident caused damage — converts the repair cost into a documented chargeback against that resident's account.

The product serves five distinct audiences. Unit occupants file requests and sign off on the finished work before it is accepted as complete. Dispatch coordinators triage incoming requests, route them to the right trade, and arbitrate the recall window when a resident reports that the same problem has come back. In-house technicians and external vendor crews share the same execution workflow but with different eligibility gates — vendors carry insurance validity requirements, and every vendor job needs a travel buffer against the next commitment. The property manager owns the master data, approves purchases above a configurable threshold, finalizes chargebacks into line-item bills, and closes out completed work. Behind the scenes, the system keeps a strict stock ledger over stocked parts, a per-property SLA configuration with per-priority response and completion targets, and a logical clock that drives every deadline, notice-period, and recall-window evaluation.

Because this system touches money (chargebacks, purchase approvals), safety (entry authorization rules), and resident relations (sign-off, dispute handling), every rule in this document is stated precisely. Where the prose describes a comparison, the reader can assume the comparison is exact — inclusive or strict — as written, and that derived values are recomputed at the moment the triggering action commits.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers. Every request must carry `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the operational capacity in which they are acting. The system recognizes five roles, spelled exactly as follows: `Resident`, `Dispatcher`, `Technician`, `Vendor`, and `PropertyManager`. A request that is missing either header, or that supplies a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not permitted on the targeted endpoint per §4 is rejected with `ERR_FORBIDDEN` (HTTP 403).

The `X-User-ID` header has two distinct meanings depending on the role:

- When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting Resident; ownership checks on any resource that references a Resident compare the resource's resident foreign-key field to `X-User-ID`. A resident filing a work order must supply their own id as the payload's `resident_id`; a resident signing off, reopening, cancelling, disputing, or paying does so against their own records only, and any mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting Technician; ownership checks on any resource that references a Technician compare the work order's `assigned_technician_id` to `X-User-ID`. Similarly, when `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting Vendor, and the work order's `assigned_vendor_id` is compared.
- When `X-User-Role` is `Dispatcher` or `PropertyManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it against any entity's `id`.

Ownership checks are applied only where this document states them; reads are never ownership-restricted, so any role authorized on a read endpoint may read any record it resolves. Entity-backed ownership checks (the `ERR_NOT_RESOURCE_OWNER` cases) are applied after authentication and authorization and before any existence, state, or business-rule validation. The precedence among all validation categories — authentication, authorization, ownership, existence, concurrency, state, business safety, business temporal, business constraint, business fiscal, and finally general shape validation — is honored across every endpoint: an unauthenticated request is rejected before a forbidden one, a forbidden one before a non-owner one, and so on, with malformed-payload errors of the general `ERR_VALIDATION` category evaluated last. A request body that is not a well-formed JSON object is treated as an empty object and therefore fails general shape validation.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock of §2.4.
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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Ties in `created_at` are broken by creation (insertion) order. `total_count` is the full number of matching items across all pages, and `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. The Logical Clock and Time-Driven Rules

The server maintains a logical clock that is the single source of "now" for the entire system. On server boot the logical clock starts at the fixed default `2026-08-01T00:00:00Z`; it does not read wall-clock time and must not fall back to it. A `PropertyManager` may advance the logical clock to a supplied `to_iso8601` instant through an admin-only test-driving capability — any well-formed instant is accepted, including one earlier than the current value, and an unparseable `to_iso8601` is rejected with `ERR_VALIDATION` (HTTP 400); the response echoes the new clock as `current_utc`. Every SLA deadline comparison, every entry-notice lead-time check, and every recall-window evaluation in this document reads the logical clock at the moment the action is evaluated.

### 2.5. Common Resource Properties

Every top-level resource — Property, Resident, Technician, Vendor, Part, WorkOrder, WorkOrderPart, PurchaseRequest, and Chargeback — carries a standard set of system-managed fields:

- `id` (string): a unique server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by exactly one on every mutation of the resource. Recomputations of derived fields that are triggered by a mutation of a *different* resource (for example, a Part's `restock_status` flipping because a work order was completed) count as mutations of that other resource and increment that other resource's `version` accordingly.

### 2.6. Money, Rounding, and Units

All monetary values in this system are integer cents — never floating-point dollars. Purchase totals, chargeback amounts, part costs, shipping fees, and resident balances are all expressed and stored as integer numbers of cents. Wherever a calculation produces a fractional cent (the handling fee on small purchase orders, and the per-line resident share of a chargeback), the result is rounded half-up to the nearest cent at the point the rule specifies; the rounding step is never deferred and never applied twice. Dates and datetimes are ISO 8601 UTC strings with three fractional digits. On input, datetime strings are accepted with fractional digits and the timezone designator optional: a missing designator is read as UTC, and numeric offsets are converted to UTC. Quantities of parts are whole units.

### 2.7. Optimistic Concurrency Control on the Work Order

Two write operations are guarded by optimistic concurrency control against the work order's `version`, and both use the same guard field and the same rejection error. Any triage edit of a work order — the Dispatcher-facing modification of `priority`, `category`, or `description` while the work order is `TRIAGED` — must carry `expected_work_order_version` as a non-optional request field, holding the `version` the client last observed on the work order. Any creation of a purchase request against a work order must likewise carry `expected_work_order_version` as a non-optional field. In both cases, if the supplied value does not equal the work order's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is applied. No other endpoint accepts a version field; optimistic locking applies to these two write operations only.

### 2.8. Stock Ledger Integrity

The parts inventory is kept as a strict ledger per Part. Every quantity change is one of four ledger events: a reservation (stock is earmarked for a work order), a release (the earmark is cancelled and the stock returns to the shelf), a consumption (the earmarked stock is written off as used when the work order completes), and a purchase receipt (new stock arrives). A reservation decreases `quantity_on_hand` and increases `reserved_quantity` by the reserved amount. A release reverses a reservation exactly, so a reserve followed by its compensating release leaves the sum of `quantity_on_hand` plus `reserved_quantity` unchanged. A consumption decreases `reserved_quantity` only — `quantity_on_hand` was already debited at reserve time, and the consumption writes the stock off the books. A purchase receipt increases `quantity_on_hand` by the received quantity and does not touch `reserved_quantity`. After every ledger event, the part's `restock_status` is recomputed: it is `LOW_STOCK` whenever `quantity_on_hand` is less than or equal to the part's `reorder_level` (equality counts as low stock), and `IN_STOCK` otherwise. The recomputation can flip the status in either direction — a release or a purchase receipt can lift a part back to `IN_STOCK`, and a reservation can push it down to `LOW_STOCK`.

### 2.9. Cascading Side Effects and Hierarchical Consistency

State changes in this system rarely stop at one entity. Three cascades are load-bearing and are described fully in §3 but stated here as a system-wide principle: completing a work order consumes every reserved part line against it, writes the stock off the ledger, recomputes every affected part's `restock_status`, recomputes the work order's `parts_total_cents`, and may spawn a pending chargeback in the same transaction. Cancelling an assigned work order — and suspending a vendor — both release every reserved part line, restore `quantity_on_hand`, and recompute `restock_status` for every affected part. All side effects of a single operation commit atomically with the primary transition and are visible in the response and in every subsequent read. Each entity mutated by a cascade has its own `updated_at` refreshed and its own `version` incremented.

### 2.10. Resource Lookup and Existence

Every URL path identifier and every foreign-key identifier in a request payload must resolve to an existing resource of the right type; otherwise the request is rejected with `ERR_NOT_FOUND` (HTTP 404). Because the resource graph is flat — properties, residents, technicians, vendors, parts, work orders, work-order-part lines, purchase requests, and chargebacks are all top-level resources joined by foreign keys — existence is checked against the named resource directly, and existence failures surface before state or business-rule checks. A request to an undeclared path, or to a declared path under a method it does not declare, is likewise rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.11. Cross-Property Isolation and Trade Matching

A maintenance operation never crosses property boundaries. The technician or vendor assigned to a work order must belong to the same property as the work order. A part reserved against a work order must be stocked by the same property as the work order; a reservation request naming a part from a different property is rejected with `ERR_PART_INSUFFICIENT_STOCK` (HTTP 409). Within a property, assignment additionally requires a trade match: the technician's or vendor's `trade` must equal the work order's `category`, or dispatch is rejected with `ERR_TRADE_MISMATCH` (HTTP 409). Trades and categories share the same five-value vocabulary: `PLUMBING`, `ELECTRICAL`, `HVAC`, `APPLIANCE`, and `GENERAL`.

## 3. Business Logic & Workflows

### 3.1. Setting Up a Property and Its Policies

Everything begins with a PropertyManager registering a property. The only mandatory input is the property's `name`; every policy field carries a default and may be omitted at creation, and when supplied each policy field must be an integer — any integer value is accepted, with no range restriction. The SLA configuration is expressed as six hour-valued fields: `emergency_response_hours` defaults to 4, `emergency_completion_hours` defaults to 24, `urgent_response_hours` defaults to 24, `urgent_completion_hours` defaults to 72, `routine_response_hours` defaults to 72, and `routine_completion_hours` defaults to 168. Three further policy knobs govern the financial and scheduling rules: `purchase_auto_approve_threshold_cents` defaults to 50000 (five hundred dollars) and is the ceiling at or under which a purchase request approves itself without manager involvement; `recall_window_days` defaults to 30 and bounds how long after completion a work order can be reopened as a recall; `vendor_travel_buffer_minutes` defaults to 60 and is the minimum gap between consecutive jobs assigned to the same vendor. Finally, `entry_notice_min_hours` defaults to 24 and sets the minimum lead time between posting an entry notice and the start of the scheduled window when entry is by posted notice.

With the property in place, the manager populates the people and the stockroom. A resident is created with `property_id`, `unit_number` (the unit identifier, e.g. "101"), `full_name`, and `email`; their `chargeback_balance_cents` starts at 0. A technician is created with `property_id`, `full_name`, and a `trade`. A vendor is created with `property_id`, `company_name`, `trade`, and `insurance_valid_until` — the insurance expiry timestamp that gates dispatch eligibility — and comes into the world with `status` set to `ACTIVE`. A part is created with `property_id`, a `sku` that must be unique within its property (a duplicate is rejected with `ERR_DUPLICATE_SKU`, HTTP 409), a display `name`, the current standard `unit_cost_cents` (a non-negative integer), an optional `reorder_level` defaulting to 0, and an optional `initial_stock` defaulting to 0 (each a non-negative integer when supplied). At creation the part's `quantity_on_hand` is seeded to `initial_stock`, `reserved_quantity` starts at 0, and `restock_status` is computed immediately per the ledger rule of §2.8.

### 3.2. Filing a Request and the Triage Step

A resident files a maintenance request by supplying `property_id`, their own `resident_id`, a `category` drawn from the five-trade vocabulary, a `priority` of `EMERGENCY`, `URGENT`, or `ROUTINE`, and a free-text `description` of the problem. If the payload's `resident_id` does not match the caller's `X-User-ID`, the create is rejected with `ERR_NOT_RESOURCE_OWNER`. The resident's own property affiliation is not cross-checked against the payload's `property_id` at intake. On acceptance the work order enters `TRIAGED` status. The system snapshots the resident's current `unit_number` onto the work order so later unit reassignments do not rewrite history, initializes `recall_count` to 0, `resident_signoff` to false, `photo_urls` to empty, `damage_reported` to false, `estimated_damage_cost_cents` to null, and `parts_total_cents` to 0, and computes the two SLA due timestamps: `response_due_at` is the work order's `created_at` plus the property's response-hours value for the chosen priority, and `completion_due_at` is `created_at` plus the property's completion-hours value for that priority. Before the first dispatch, `response_sla_breached` is false; before any completion, `completion_sla_breached` is false. Both breach flags use a strictly-greater comparison — landing exactly on the due timestamp is compliant.

While the work order remains `TRIAGED`, a Dispatcher may revise `priority`, `category`, or `description` through the triage-edit operation. This is the first of the two OCC-guarded writes: the request must carry `expected_work_order_version` equal to the work order's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful edit increments the work order's `version` by one, and when `priority` changed, both `response_due_at` and `completion_due_at` are recomputed from the original `created_at` and the new priority's configured hours — the SLA clock always starts at intake, never at reclassification. Editing is only available while `TRIAGED`; on a work order in any other status the same call is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. Dispatch: Choosing In-House or Vendor

Dispatch is the Dispatcher's core act and moves the work order from `TRIAGED` — or from `REOPENED` on a recall — to `ASSIGNED`. The dispatch payload names the `assignment_type` (`IN_HOUSE` or `VENDOR`), the assignee (`technician_id` for in-house, `vendor_id` for a vendor), the scheduled window as `scheduled_start_at` and `scheduled_end_at`, the `entry_authorization` mode (`EMERGENCY_ACCESS`, `RESIDENT_CONSENT`, or `NOTICE_POSTED`), and, when entry is by notice, the `notice_posted_at` timestamp. The scheduled window must be well-formed: `scheduled_end_at` must be strictly later than `scheduled_start_at`, or the request fails `ERR_VALIDATION` (HTTP 400).

Eligibility gates differ by assignment type. For an in-house dispatch, the technician must exist, belong to the same property as the work order, and match the work order's `category` by trade — otherwise `ERR_TRADE_MISMATCH`. The technician's calendar is then checked under a half-open overlap rule: dispatch is rejected with `ERR_TECHNICIAN_SCHEDULE_CONFLICT` (HTTP 409) if any other work order assigned to the same technician in `ASSIGNED` or `IN_PROGRESS` status has an existing window that starts before the new window ends and ends after the new window starts. Adjacent windows — one ending exactly when the next begins — are allowed, because the overlap test is strict on both sides.

For a vendor dispatch, the same existence, same-property, and trade-match checks apply, plus two vendor-specific gates. The vendor's `status` must be `ACTIVE`; dispatching to a `SUSPENDED` vendor is rejected with `ERR_VENDOR_NOT_ACTIVE` (HTTP 409). The vendor's insurance must cover the start of the job: `insurance_valid_until` must be at or after `scheduled_start_at`, or the dispatch fails with `ERR_VENDOR_INSURANCE_EXPIRED` (HTTP 409). The vendor's calendar is then checked under a travel-buffer rule rather than raw overlap: dispatch is rejected with `ERR_VENDOR_SCHEDULE_CONFLICT` (HTTP 409) if any other work order assigned to the same vendor in `ASSIGNED` or `IN_PROGRESS` status sits closer to the new window than the property's `vendor_travel_buffer_minutes` — concretely, the new window must start no earlier than the existing window's end plus the buffer, or end no later than the existing window's start minus the buffer. A gap of exactly the buffer duration is allowed.

Entry authorization adds a third layer. The dispatch validation order is fixed: entry-rule violations are judged first, then the notice lead-time check, then vendor activity and vendor insurance, then the two calendar-conflict checks (technician before vendor), and trade matching after the temporal checks — so a dispatch that would violate an entry rule surfaces `ERR_ENTRY_RULE_VIOLATION` even when the assignee's trade would also mismatch. `EMERGENCY_ACCESS` is lawful only when the work order's `priority` is `EMERGENCY`; on any other priority the dispatch is rejected with `ERR_ENTRY_RULE_VIOLATION` (HTTP 422). `NOTICE_POSTED` requires `notice_posted_at` to be present and the scheduled start to be at least the property's `entry_notice_min_hours` after the notice timestamp; a missing notice timestamp or a window that starts inside the lead time is rejected with `ERR_ENTRY_NOTICE_TOO_SHORT` (HTTP 422).

On a successful dispatch the system writes the assignment onto the work order: `assignment_type`, the chosen assignee field (`assigned_technician_id` or `assigned_vendor_id`, with the other assignee field cleared to null), `scheduled_start_at`, `scheduled_end_at`, `entry_authorization`, and `notice_posted_at` — the last stored only when `entry_authorization` is `NOTICE_POSTED` and otherwise set to null. The first dispatch of a work order also stamps `first_responded_at` with the current logical clock and immediately recomputes `response_sla_breached` as whether that stamp is strictly later than `response_due_at`. A re-dispatch after a recall never overwrites `first_responded_at` — the response SLA measures the first response to the original request, permanently. Every successful dispatch increments the work order's `version` by one.

### 3.4. Doing the Work: Start, Sign-Off, and Completion

Work starts when the assigned party starts it. Starting moves the work order from `ASSIGNED` to `IN_PROGRESS` and stamps `started_at` with the current logical clock. The caller must be the assigned party: on an in-house job the caller's `X-User-ID` must equal `assigned_technician_id`, and on a vendor job it must equal `assigned_vendor_id`; anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`. Entry permission is enforced a second time at the moment work begins. If the dispatch was authorized by `RESIDENT_CONSENT`, the start payload must carry `resident_consent_confirmed` set to true, or the start is rejected with `ERR_ENTRY_RULE_VIOLATION`. If the dispatch was authorized by `NOTICE_POSTED`, the current logical clock at start time must have reached at least `notice_posted_at` plus the property's `entry_notice_min_hours`; starting earlier is likewise `ERR_ENTRY_RULE_VIOLATION`.

Resident sign-off is a self-transition: while the work order is `IN_PROGRESS`, the reporting resident — and only the reporting resident, matching `X-User-ID` against the work order's `resident_id` — records approval, which sets `resident_signoff` to true and leaves the status at `IN_PROGRESS`. Each sign-off increments the work order's `version`. Sign-off is not optional decoration: completion is impossible without it.

Completion is the heaviest transaction in the system. The assigned party completes the work order with a payload carrying `photo_urls`, a `damage_reported` flag, an optional `estimated_damage_cost_cents`, and optional free-text `notes`. Five preconditions gate the transition from `IN_PROGRESS` to `COMPLETED`, evaluated in a fixed order: the state check comes first (a completion attempted on a work order that is not `IN_PROGRESS` is `ERR_INVALID_STATE`), then ownership, then the open-purchase-request block, then the sign-off requirement, then the photo requirement, and finally the damage-estimate shape check. The caller must be the assigned party, as at start. Every purchase request raised against this work order must already be in `RECEIVED`, `REJECTED`, or `SUPERSEDED` status — a `PENDING` or `APPROVED` purchase request blocks completion with `ERR_OPEN_PURCHASE_REQUESTS` (HTTP 409), because stock cannot be written off while procurement is still in flight. `resident_signoff` must be true; otherwise the completion is rejected with `ERR_RESIDENT_SIGNOFF_REQUIRED` (HTTP 409). At least one photo URL must be supplied; an empty `photo_urls` array is rejected with `ERR_COMPLETION_PHOTOS_REQUIRED` (HTTP 422). And when `damage_reported` is true, `estimated_damage_cost_cents` must be present and greater than zero, or the request fails with `ERR_CHARGEBACK_LINES_REQUIRED` (HTTP 422). Beyond these gates, `photo_urls` must be an array of strings and `damage_reported`, when supplied, must be a boolean — violations are malformed payloads (`ERR_VALIDATION`, HTTP 400) — and the optional `notes` field is accepted but not persisted.

A successful completion stamps `completed_at` with the current logical clock and computes `completion_sla_breached` as whether that stamp is strictly later than `completion_due_at`. The payload's `photo_urls`, `damage_reported`, and `estimated_damage_cost_cents` are stored on the work order, with `estimated_damage_cost_cents` stored as null whenever `damage_reported` is false. Then the stock cascade runs: every work-order-part line of this work order still in `RESERVED` status moves to `CONSUMED`; for each consumed line the part's `reserved_quantity` decreases by the line's quantity (its `quantity_on_hand` is unchanged, having been debited at reservation time); every mutated part's `restock_status` is recomputed per the ledger rule; and the work order's `parts_total_cents` is recomputed as the sum of `line_total_cents` over all its `CONSUMED` lines. Finally, if `damage_reported` is true, a Chargeback springs into existence in `PENDING` status, bound to this work order and to the work order's `resident_id`, with `provisional_amount_cents` set to the raw `estimated_damage_cost_cents` from the completion payload — the technician's unrounded field estimate, captured as-is with no rounding applied. The chargeback is born with `line_items` empty and `final_amount_cents` null. Completion increments the work order's `version` by one.

### 3.5. Recall, Closure, and Cancellation

A completed work order is not necessarily finished. Within the property's recall window, the reporting resident or a Dispatcher can reopen it, moving the status from `COMPLETED` to `REOPENED`. The window test compares the current logical clock against `completed_at`: the elapsed time must be at most `recall_window_days`, with exactly-on-the-boundary allowed; a reopen after the window is rejected with `ERR_RECALL_WINDOW_EXPIRED` (HTTP 409). A resident caller must be the reporting resident or the request fails `ERR_NOT_RESOURCE_OWNER`. Reopening increments `recall_count` by one, resets `resident_signoff` to false — the resident must sign off again on the rework — and clears every assignment field: `assignment_type`, `assigned_technician_id`, `assigned_vendor_id`, the scheduled window, `entry_authorization`, and `notice_posted_at` all return to null. The `first_responded_at` stamp survives; only a fresh dispatch can reassign the work order, and a `REOPENED` work order dispatches under exactly the same assignment, entry, trade, insurance, and schedule-conflict rules as a `TRIAGED` one. A work order that has been reopened and completed again carries the `completed_at` of its most recent completion, and the recall window measures from that most recent stamp.

Closure is the manager's quiet end-state: a PropertyManager closes a `COMPLETED` work order, stamping `closed_at` with the current logical clock and moving the status to `CLOSED`, a terminal state. Closure does not touch sign-off, parts, or chargebacks.

Cancellation is available only before work starts — from `TRIAGED`, from `ASSIGNED`, or from `REOPENED` — and moves the work order to the terminal `CANCELLED` status. A resident caller must again be the reporting resident. Cancelling from `ASSIGNED` carries a release cascade: every work-order-part line still `RESERVED` moves to `RELEASED`, each released line's quantity is added back to its part's `quantity_on_hand` and subtracted from `reserved_quantity`, and each affected part's `restock_status` is recomputed; the assignment fields are cleared. Cancelling from `TRIAGED` or `REOPENED` has no assignment to clear and no reservations to release, since reservations only exist against dispatched work. Every transition in this subsection increments the work order's `version` by one. Attempting any transition from a status that does not allow it — reopening an `IN_PROGRESS` order, closing a `TRIAGED` one, cancelling a `COMPLETED` one, and so on — is rejected with `ERR_INVALID_STATE`.

### 3.6. Reserving Parts and the Stock Ledger in Practice

Once a work order is `ASSIGNED` or `IN_PROGRESS`, the assigned party — the in-house technician or the vendor crew, identified by `X-User-ID` matching the work order's assignee field — can reserve stock against it. The reservation payload names a `part_id` and a `quantity` of at least 1. The part must belong to the same property as the work order, and its `quantity_on_hand` must be at least the requested quantity — taking the last unit on the shelf is allowed; a shortfall, a foreign-property part, or an integer quantity below 1 is rejected with `ERR_PART_INSUFFICIENT_STOCK` (HTTP 409), while a non-integer quantity is malformed and fails `ERR_VALIDATION` (HTTP 400). The created line captures `unit_cost_cents_snapshot` from the part's current `unit_cost_cents` at reservation time — later price changes do not rewrite committed work — computes `line_total_cents` as the quantity times that snapshot, and enters `RESERVED` status. The ledger debits immediately: `quantity_on_hand` falls by the quantity, `reserved_quantity` rises by the same amount, and `restock_status` is recomputed.

A reservation can be released while it is still `RESERVED`, either manually by the assigned party or a Dispatcher, or automatically as part of the cancellation and vendor-suspension cascades. A manual release restores the stock exactly: `quantity_on_hand` rises by the line's quantity, `reserved_quantity` falls by the same amount, and `restock_status` is recomputed. Releasing a line that is already `CONSUMED` or `RELEASED` is an invalid state and is rejected with `ERR_INVALID_STATE`. Anyone other than the assigned party or a Dispatcher attempting a manual release is rejected with `ERR_NOT_RESOURCE_OWNER`. Work-order-part lines are readable as a collection, filterable by `work_order_id` or `part_id`.

### 3.7. Purchase Requests: Auto-Approval, Decisions, and Receipts

When the needed part is not on the shelf — or the job requires a special order — the assigned party raises a purchase request against the work order, naming `part_id`, a `quantity` of at least 1, the supplier's `quoted_unit_cost_cents`, and an optional `shipping_fee_cents` defaulting to 0. The named part must exist, but — unlike a reservation — it is not required to belong to the work order's property. This is the second OCC-guarded write: the payload must carry `expected_work_order_version` equal to the work order's current `version`, or the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The work order must be `ASSIGNED` or `IN_PROGRESS`, and the caller must be the assigned party.

Three computed amounts appear on every purchase request. `items_subtotal_cents` is the quantity times the quoted unit cost. `handling_fee_cents` is zero when the quantity is at least 10; below that bulk threshold it is the items subtotal multiplied by eight percent, rounded half-up to the nearest cent. `estimated_total_cents` is the sum of the items subtotal, the shipping fee, and the handling fee. The total drives the approval routing: when `estimated_total_cents` is at or under the property's `purchase_auto_approve_threshold_cents` — equality approves — the request is born `APPROVED` with `auto_approved` set to true; otherwise it is born `PENDING` with `auto_approved` false and waits for a manager.

Creation also enforces one active negotiation per part per work order: any earlier purchase request still `PENDING` for the same work order and part is moved to `SUPERSEDED` in the same transaction. Creating the request increments the work order's `version` by one.

A PropertyManager decides the pending queue through lifecycle events. Approving a `PENDING` request moves it to `APPROVED` with `auto_approved` false. Rejecting a `PENDING` request moves it to `REJECTED` and stores the payload's `decision_reason`. Receiving an `APPROVED` request moves it to `RECEIVED` and posts the stock: the part's `quantity_on_hand` rises by the purchased quantity and its `restock_status` is recomputed — this is the receipt event that can lift a depleted part back to `IN_STOCK`. Each event targets the purchase request named in the path; acting on a request not in the event's required from-status is `ERR_INVALID_STATE`. Note the asymmetry the completion rule relies on: a `REJECTED` or `SUPERSEDED` request never blocks completion, but an `APPROVED` one does until it is received.

### 3.8. Vendor Suspension and Its Fallout

A PropertyManager can suspend a vendor or reinstate one through vendor lifecycle events carrying an `event_type` of `SUSPEND` or `REINSTATE` plus an optional `reason` (accepted but not persisted). Suspending requires the vendor to be `ACTIVE`; the transition to `SUSPENDED` fires a three-link cascade across the vendor's book of work. Every work order currently `ASSIGNED` to this vendor reverts to `TRIAGED` with its assignment fields cleared — `assignment_type`, `assigned_vendor_id`, the scheduled window, `entry_authorization`, and `notice_posted_at` all become null — while its `first_responded_at` is retained, because the response SLA was already earned or breached at the original dispatch. Each reverted work order's still-`RESERVED` part lines move to `RELEASED`, restoring each part's `quantity_on_hand` and reducing its `reserved_quantity` by the released amounts, with `restock_status` recomputed per part — which may flip a part from `LOW_STOCK` back to `IN_STOCK`. Work orders already `IN_PROGRESS` with this vendor are deliberately not touched; a crew mid-job finishes the job. The vendor's own `version` increments on the transition.

Reinstating requires the vendor to be `SUSPENDED` and returns it to `ACTIVE`. Nothing is auto-restored: work orders that reverted to `TRIAGED` stay triaged and require a fresh dispatch, subject to all the usual gates including the now-current insurance check.

### 3.9. Chargebacks: From Field Estimate to Final Bill

A chargeback exists because a completed work order reported resident-caused damage; it is born `PENDING` with `provisional_amount_cents` holding the field estimate. The PropertyManager turns the estimate into a bill by supplying `line_items` — a non-empty array of lines, each carrying `description`, a `quantity` of at least 1, a `unit_cost_cents` of at least 0, and a `resident_share_pct` between 0 and 1 inclusive. Billing without lines, or with an invalid line, is rejected with `ERR_CHARGEBACK_LINES_REQUIRED` (HTTP 422). The billed amount, `final_amount_cents`, is computed per line and then summed: each line's amount is its quantity times its unit cost times its resident share, rounded half-up to the nearest cent, and the rounded line amounts are added together. The per-line-then-sum order is the rule — summing raw amounts and rounding once at the end is not used. Billing moves the chargeback from `PENDING` to `BILLED`, stores the lines (each stored line carries exactly `description`, `quantity`, `unit_cost_cents`, and `resident_share_pct`), and recomputes the resident's `chargeback_balance_cents`, which rises by the new final amount.

From `BILLED`, the chargeback can travel three paths. The charged resident — matching `X-User-ID` against the chargeback's `resident_id` — may dispute it, supplying a `dispute_reason`; the status moves to `DISPUTED` and the balance does not change, because a disputed amount is still owed. A PropertyManager may uphold a dispute, moving `DISPUTED` back to `BILLED` with the balance again unchanged and the recorded `dispute_reason` retained. A PropertyManager may waive the chargeback from either `BILLED` or `DISPUTED`, moving it to `WAIVED` and recomputing the balance, which falls by the final amount. Or the resident may pay from `BILLED`, moving the chargeback to `PAID` and likewise reducing the balance by the final amount. `PAID` and `WAIVED` are terminal; `PENDING` is never part of the balance either. Formally, a resident's `chargeback_balance_cents` is the sum of `final_amount_cents` over all their chargebacks in `BILLED` or `DISPUTED` status — nothing more, nothing less — and is recomputed on every bill, waive, and pay event. An event invoked by a role not permitted for it — a Resident attempting BILL, UPHOLD, or WAIVE, or a PropertyManager attempting DISPUTE or PAY — is rejected with `ERR_FORBIDDEN` (HTTP 403).

### 3.10. SLA Compliance Reporting

Dispatchers and PropertyManagers can pull an SLA compliance report for a property over a creation window. The report request supplies `window_start` and `window_end` as required query parameters — each a well-formed ISO 8601 datetime — and an optional `basis` query parameter that defaults to `OPEN_INCLUSIVE` and must otherwise be `CLOSED_ONLY`; violations are rejected with `ERR_VALIDATION` (HTTP 400). No ordering constraint is imposed on the bounds: an inverted window simply matches no work orders. The response carries the `property_id`, the window echoed verbatim as supplied, the `basis`, a `generated_at` timestamp, and a `metrics` array with one entry per priority — `EMERGENCY`, `URGENT`, and `ROUTINE` each get their own row — where each entry carries `priority`, `eligible_count`, `response_compliance_pct`, and `completion_compliance_pct`.

Eligibility is by creation time: a work order counts toward a priority's row when its `priority` equals that row's priority and its `created_at` falls at or after `window_start` and strictly before `window_end` — the window is half-open. The basis selects the population. Under `CLOSED_ONLY`, only work orders in `COMPLETED` or `CLOSED` status are eligible; open work is excluded entirely. Under `OPEN_INCLUSIVE`, work orders in `TRIAGED`, `ASSIGNED`, `IN_PROGRESS`, or `REOPENED` status also enter the denominator.

Compliance is judged per work order. For a work order in `COMPLETED` or `CLOSED` status, it is response-compliant when its stored `response_sla_breached` flag is false, and completion-compliant when its stored `completion_sla_breached` flag is false. For an open work order under the inclusive basis, each dimension is evaluated live against the logical clock: it is response-compliant when its `first_responded_at` is set and not later than `response_due_at`, or — if never yet dispatched — when the current time has not passed `response_due_at`; and completion-compliant when its `completed_at` is set and not later than `completion_due_at`, or — if not yet completed — when the current time has not passed `completion_due_at`. Each row reports `response_compliance_pct` and `completion_compliance_pct`, each computed as one hundred times the number of compliant work orders divided by the number eligible, rounded half-up to two decimal places. When a priority has no eligible work orders at all, both percentages report as 100.00.

## 4. Endpoint Definitions

Operations that create a new resource — registering a property, resident, technician, vendor, or part; filing a work order; reserving a part line; raising a purchase request — return `201 Created`. Operations that modify an existing resource or drive a lifecycle event — dispatch, start, sign-off, complete, reopen, close, cancel, release, triage edit, vendor events, purchase-request events, chargeback events, and the clock setter — return `200 OK`. All reads return `200 OK`. Lifecycle-event endpoints reject an `event_type` outside their declared set with `ERR_VALIDATION` (HTTP 400). List-endpoint filters are exact-match query parameters named by the filtered field (`property_id`, `resident_id`, `assigned_technician_id`, `assigned_vendor_id`, `status`, `work_order_id`, or `part_id`, as applicable per endpoint); multiple filters combine conjunctively, and a filter that matches nothing yields an empty page rather than an error.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/properties` | Create a property with SLA/threshold policy configuration (defaults applied when omitted) | PropertyManager |
| GET | `/properties/{id}` | Get a property | Resident, Dispatcher, Technician, Vendor, PropertyManager |
| GET | `/properties/{id}/sla-report` | Response/completion SLA compliance per priority over a created_at window; basis selects the calculation variant | Dispatcher, PropertyManager |
| POST | `/residents` | Create a resident | PropertyManager |
| GET | `/residents` | List residents, optionally filtered by property | Dispatcher, PropertyManager |
| GET | `/residents/{id}` | Get a resident (includes chargeback balance) | Resident, Dispatcher, PropertyManager |
| POST | `/technicians` | Create an in-house technician | PropertyManager |
| GET | `/technicians` | List technicians, optionally filtered by property | Dispatcher, PropertyManager |
| GET | `/technicians/{id}` | Get a technician | Dispatcher, Technician, PropertyManager |
| POST | `/vendors` | Create a vendor | PropertyManager |
| GET | `/vendors` | List vendors, optionally filtered by property | Dispatcher, PropertyManager |
| GET | `/vendors/{id}` | Get a vendor | Dispatcher, Vendor, PropertyManager |
| POST | `/vendors/{id}/events` | Vendor lifecycle event (SUSPEND or REINSTATE) | PropertyManager |
| POST | `/parts` | Create a stocked part | PropertyManager |
| GET | `/parts` | List parts, optionally filtered by property | Dispatcher, Technician, Vendor, PropertyManager |
| GET | `/parts/{id}` | Get a part | Dispatcher, Technician, Vendor, PropertyManager |
| POST | `/work-orders` | Resident files a maintenance request; classified with priority at intake | Resident |
| GET | `/work-orders` | List work orders with filters (property, resident, assignee, status) | Resident, Dispatcher, Technician, Vendor, PropertyManager |
| GET | `/work-orders/{id}` | Get a work order | Resident, Dispatcher, Technician, Vendor, PropertyManager |
| PATCH | `/work-orders/{id}` | Triage edit of priority/category/description while TRIAGED; OCC-guarded | Dispatcher |
| POST | `/work-orders/{id}/dispatch` | Assign the work order to an in-house technician or a vendor with a scheduled window and entry authorization | Dispatcher |
| POST | `/work-orders/{id}/start` | Assigned party starts work; entry permission enforced | Technician, Vendor |
| POST | `/work-orders/{id}/sign-off` | Reporting resident signs off on completed work (required before completion) | Resident |
| POST | `/work-orders/{id}/complete` | Assigned party completes with photo documentation and optional damage report | Technician, Vendor |
| POST | `/work-orders/{id}/reopen` | Re-open a completed work order as a recall within the property recall window | Resident, Dispatcher |
| POST | `/work-orders/{id}/close` | Manager closes a completed work order | PropertyManager |
| POST | `/work-orders/{id}/cancel` | Cancel a work order before work starts | Resident, Dispatcher |
| POST | `/work-orders/{id}/parts` | Reserve stock of a part against an assigned/in-progress work order | Technician, Vendor |
| POST | `/work-orders/{id}/parts/{wop_id}/release` | Release a reservation, returning stock | Technician, Vendor, Dispatcher |
| GET | `/work-order-parts` | List work-order-part lines, filtered by work order or part | Dispatcher, Technician, Vendor, PropertyManager |
| GET | `/work-order-parts/{id}` | Get a work-order-part line | Dispatcher, Technician, Vendor, PropertyManager |
| POST | `/work-orders/{id}/purchase-requests` | Assigned party requests a parts purchase; auto-approves at or under the property threshold; OCC-guarded | Technician, Vendor |
| GET | `/purchase-requests` | List purchase requests, filtered by work order or part | Dispatcher, Technician, Vendor, PropertyManager |
| GET | `/purchase-requests/{id}` | Get a purchase request | Dispatcher, Technician, Vendor, PropertyManager |
| POST | `/purchase-requests/{id}/events` | Purchase request lifecycle event (APPROVE, REJECT, or RECEIVE) | PropertyManager |
| GET | `/chargebacks` | List chargebacks, filtered by resident or work order | Resident, Dispatcher, PropertyManager |
| GET | `/chargebacks/{id}` | Get a chargeback | Resident, Dispatcher, PropertyManager |
| POST | `/chargebacks/{id}/events` | Chargeback lifecycle event (BILL, DISPUTE, UPHOLD, WAIVE, or PAY) | Resident, PropertyManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (starts at 2026-08-01T00:00:00Z on boot; all SLA, notice, and recall-window evaluations read this clock) | PropertyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ENTRY_RULE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_ENTRY_NOTICE_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_VENDOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_VENDOR_INSURANCE_EXPIRED` | 409 Conflict |
| `ERR_TECHNICIAN_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_VENDOR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_RECALL_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_TRADE_MISMATCH` | 409 Conflict |
| `ERR_PART_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_OPEN_PURCHASE_REQUESTS` | 409 Conflict |
| `ERR_RESIDENT_SIGNOFF_REQUIRED` | 409 Conflict |
| `ERR_COMPLETION_PHOTOS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CHARGEBACK_LINES_REQUIRED` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 400 Bad Request |

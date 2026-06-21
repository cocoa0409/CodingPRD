# Procurement 3-Way Match API — Product Requirements Document

## 1. Introduction

Enterprise procurement turns a stated business need into a paid vendor invoice, and every hop along that chain — requisition, competitive quotation, purchase-order commitment, physical receipt, and finally the three-way match that authorizes payment — is a control point that auditors, finance, and operations all care about. This document specifies a REST API that models the full source-to-settle lifecycle as a set of cooperating resources mounted under `/procurement`. The central guarantee the platform provides is **segregation of duties**: the buyer who raises a need may not approve their own spend, the approver may not post the receipt that closes the loop, and the person who posts a receipt may not later waive the very exception that receipt produced. These separations are enforced through caller identity on every state-changing operation, not by convention.

The platform's second pillar is the **3-way match**, the reconciliation that compares what was ordered (the purchase order), what arrived (the goods receipt), and what is being billed (the invoice). A match either passes within tolerance and clears the invoice for payment, or it fails and opens an auditable exception that follows the offending vendor onto its scorecard and, if exceptions accumulate, onto probation. Around this core the system layers competitive sourcing (RFQs and vendor quotes), two flavors of purchase order (one-off STANDARD orders and reusable BLANKET agreements drawn down by releases), receipt tolerances, blanket-ceiling accounting, and a weighted vendor scorecard. Because several of these flows mutate more than one resource at once — a rejected requisition cancels its open sourcing rounds, a blanket cancellation restores ceiling headroom, a match failure bumps a vendor toward probation — the specification is explicit about every cascade.

This document is written for the engineers building the service. Section 2 fixes the cross-cutting contracts (auth, envelope, pagination, concurrency, precision); Section 3 narrates the business workflows where the detailed rules live; Sections 4 and 5 summarize the endpoint surface and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an opaque string identifying the acting user, and `X-User-Role`, naming the role under which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 401) before any other processing. If the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

There are exactly six roles, spelled precisely as follows: `ProcurementAdmin`, `Buyer`, `Approver`, `Receiver`, `Matcher`, and `PayablesClerk`. `ProcurementAdmin` governs master data — spend categories, vendor registration and blocking, scorecards, and the test clock. `Buyer` raises requisitions, runs sourcing (RFQs and quotes), and issues and manages purchase orders and releases. `Approver` decides requisition approval steps. `Receiver` posts and reverses goods receipts. `Matcher` runs the 3-way match and resolves or waives exceptions. `PayablesClerk` records invoices and drives the payment dimension (approve, reject, pay). All six roles may issue read (GET) requests across the resource surface.

Every role in this system has an **opaque** identity. When `X-User-Role` is `ProcurementAdmin`, `Buyer`, `Approver`, `Receiver`, `Matcher`, or `PayablesClerk`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity's `id`. The server records these identifiers where the workflow demands an audit anchor — for example, the creating buyer's identifier is stored as `requester_id` on a `Requisition`, the deciding approver's as `decided_by_id` on an `ApprovalStep`, and the posting receiver's as `posted_by_id` on a `GoodsReceipt` — but it never compares `X-User-ID` to any entity's `id`. Where segregation-of-duties checks apply, they compare one recorded operator identifier against another (for example, the acting caller's `X-User-ID` against a stored `requester_id` or `posted_by_id`), never against a primary key.

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

List endpoints accept two pagination query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a requested limit above 100 is capped at 100. `offset` defaults to 0 and has no upper bound beyond the size of the result set. Collections are returned sorted by `created_at` in ascending order (oldest first) unless a more specific ordering is stated for a particular collection. The `meta` block of a list response carries the four pagination fields `limit`, `offset`, `total_count` (the count of all matching resources before the page window is applied), and `has_more` (true when resources remain beyond the current window).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is a UUID with no type prefix. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at creation. All entities in this system are fully versioned: each additionally carries an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by exactly 1 on every successful mutation of that resource. Whenever a side effect described in Section 3 mutates a resource — even a resource other than the one named in the request path, such as a blanket purchase order whose remaining ceiling is drawn down by a release — that resource's `updated_at` is refreshed and its `version` is incremented.

The `created_at` stamp is drawn from the server's current clock. For deterministic time-based testing, an administrative capability allows `ProcurementAdmin` to set that clock to a supplied instant, passed as the `to_iso8601` field; thereafter the server's notion of "now" returns that instant for subsequent `created_at` stamping and for any time comparison (delivery on-time scoring, blanket validity, scorecard windows).

### 2.5. Nested Resource Retrieval and Referential Existence

All resources are peers addressed directly under their own collection; there is no URL nesting. When a request references other resources — by a path id or by a foreign-key field in the body — every referenced id must resolve to an existing resource. Ids are validated left-to-right in the order they appear (path id first, then body references in declaration order), and the first id that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404). This existence check runs after authentication and authorization but is part of the request's foundational validation, ahead of business-rule evaluation.

### 2.6. Request Validation Ordering

The platform evaluates a request through a fixed ladder of checks, and the **first** check to fail determines the error returned. The ladder is: (1) user context — both auth headers present and well-formed, else `ERR_MISSING_USER_CONTEXT` (401); (2) role authorization — the caller's role is permitted for the endpoint, else `ERR_FORBIDDEN_FOR_ROLE` (403); (3) existence — every path or body resource id resolves, validated left-to-right, else `ERR_NOT_FOUND` (404); (4) request well-formedness — required fields present, all quantities and prices strictly greater than zero, enum values drawn from their permitted sets, BLANKET purchase orders carrying their ceiling and validity fields, a release's line amounts summing to its declared amount, else `ERR_INVALID_REQUEST` (400); (5) segregation of duties, else `ERR_SEGREGATION_OF_DUTIES` (403); (6) state legality — the target resource is in a state from which the requested transition is allowed, else `ERR_INVALID_STATE` (409). Checks specific to individual workflows (blanket-PO references, requisition approval state, quote windows, period overlaps, tolerances, ceilings, stale versions, receipt presence, match status) are layered on top of this ladder and are described with the workflows that own them in Section 3. Where a more specific business check would fire, it does so only after the foundational ladder above has passed.

### 2.7. Optimistic Concurrency on Blanket Draws

Creating a release against a blanket purchase order is the one operation in this system guarded by optimistic concurrency control. The release-creation request must carry an `expected_purchase_order_version` field whose value is the client's last observed `version` of the target blanket purchase order; this field is mandatory for that operation and is not accepted on any other endpoint. If `expected_purchase_order_version` does not equal the blanket purchase order's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The rationale is concrete: a prior release legitimately drew down the blanket's `remaining_amount_cents` and incremented its `version`, so a client that read the blanket before that draw is working from a stale view of the remaining ceiling and must re-read before its own draw can be admitted. No endpoint other than release creation accepts or requires a version field.

### 2.8. Monetary Precision

All monetary values in this system are integer cents; there are no fractional-cent fields. Requisition, quote, purchase-order, release, and invoice totals are computed as exact integer-cent aggregations with no rounding. Where a tolerance ceiling is computed (the price and amount ceilings in the 3-way match), the ceiling is taken to the next-lower whole cent — that is, the floor of the percentage-inflated base — before any comparison. Where a percentage or weighted score is computed (delivery on-time rate, composite score), the result is an integer obtained by rounding half up: a fractional part of exactly one-half rounds away from zero to the next integer.

### 2.9. Spend-Category and Vendor Governance

Spend categories and vendors are the system's master data, owned by `ProcurementAdmin`. A spend category carries a display `name`, a `code` that must be unique (uppercase) across all non-archived categories, two approval thresholds, an optional `preferred_vendor_id`, and a `status` that is `ACTIVE` on creation and becomes `ARCHIVED` when archived. The `approval_threshold_cents` is the committed amount strictly above which a director-level approval is required, and `director_threshold_cents` is the committed amount strictly above which a CFO-level approval is required; a category is rejected at creation with `ERR_INVALID_REQUEST` if `director_threshold_cents` is less than `approval_threshold_cents`, and likewise if its `code` duplicates that of an existing non-archived category. Both thresholds are non-negative integers, and `director_threshold_cents` must be at least `approval_threshold_cents`. The `preferred_vendor_id` names the contracted vendor for the category and is the reference point for the maverick-spend flag.

A vendor carries a legal `name`, a `tax_id` unique across all non-terminal vendors (a registration whose `tax_id` duplicates a non-terminal vendor's is rejected with `ERR_INVALID_REQUEST`), an optional `grace_days` delivery-grace window that defaults to 0 and must be non-negative, a computed `exception_count` that starts at 0, and a `status` that is `APPROVED` on registration. A vendor's status moves to `PROBATION` automatically when its open-exception count crosses the probation threshold and back to `APPROVED` when that count recedes; a `ProcurementAdmin` may move an `APPROVED` or `PROBATION` vendor to the terminal `BLOCKED` status manually. The probation threshold is **three open exceptions**: a vendor enters `PROBATION` once its `exception_count` rises above three (that is, on the fourth open exception) and leaves `PROBATION` once its `exception_count` falls back to three or fewer.

## 3. Business Logic & Workflows

### 3.1. Raising and Approving a Requisition

A `Buyer` opens the procurement cycle by creating a `Requisition`, supplying the `spend_category_id` it charges against, a short `title`, and an array of `lines`. Each line names a `sku`, a free-text `description`, a `quantity`, and an `estimated_unit_price_cents` — the buyer's price guess. Both `quantity` and `estimated_unit_price_cents` on every line must be strictly positive. On creation the requisition is born in `DRAFT`, its `requester_id` is set to the creating buyer's `X-User-ID`, and its `revision_count` is initialized to 0. The requisition's `committed_total_cents` remains null until a purchase order is later issued from it.

Submitting a draft advances the requisition from `DRAFT` to `PENDING_APPROVAL`. Three preconditions guard the submit: the acting buyer's `X-User-ID` must equal the requisition's `requester_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`); the requisition's `lines` must be non-empty (otherwise `ERR_INVALID_REQUEST`); and the charged spend category must be `ACTIVE` (otherwise `ERR_INVALID_STATE`). Submission triggers two computations and a fan-out. First, the **estimated total** is computed as the sum, over every requisition line, of that line's `quantity` multiplied by its `estimated_unit_price_cents`, and stored as `estimated_total_cents`; the inputs are whole-cent integers and the sum is exact with no rounding. Second, the **approval matrix** computation reads `estimated_total_cents` (since `committed_total_cents` is still null at submit time) against the category's thresholds to set `required_levels`: it always requires at least one level (the manager level); if the base amount is strictly greater than `approval_threshold_cents` it requires a second level; and if the base amount is strictly greater than `director_threshold_cents` it requires a third level. The comparison is strict, so a base exactly equal to `approval_threshold_cents` needs only one level, while a base one cent greater needs two. Finally, the system creates exactly `required_levels` `ApprovalStep` rows for the requisition, one per tier, with ascending `level` values 1, 2, and 3 mapping to `required_role` values `MANAGER`, `DIRECTOR`, and `CFO` respectively; each new step is born `PENDING` with a null `decided_by_id` and a null `decided_at`. Each step also records the `requisition_id` it belongs to.

An `Approver` decides the pending steps in ascending level order. When deciding a step to approve, the acting approver's identifier is recorded as the step's `decided_by_id` and the decision instant as `decided_at`, and the step moves to `APPROVED`. Once the decision under consideration leaves **all** of the requisition's approval steps in `APPROVED`, the requisition itself advances from `PENDING_APPROVAL` to `APPROVED`. Attempting to drive the requisition to `APPROVED` while any required step is still `PENDING` — for instance approving an upper level before a lower one — is rejected with `ERR_APPROVAL_INCOMPLETE`. An approver may instead reject: the approve operation accepts an optional `decision` field, and a value routing to rejection (equivalently, the dedicated reject operation) carries the requisition from `PENDING_APPROVAL` to `REJECTED`. On rejection the decided step's `status` becomes `REJECTED`, every remaining `PENDING` step is set to `SKIPPED`, and the requisition's `status` becomes `REJECTED`. An approver may never decide a requisition they themselves raised: if the acting approver's `X-User-ID` equals the requisition's `requester_id`, the decision is refused with `ERR_SEGREGATION_OF_DUTIES`.

Rejection is not the end of the line. The `Buyer` who owns a `REJECTED` requisition may revise it, returning it from `REJECTED` to `DRAFT`; this is the cyclic revise loop that lets a need be re-shopped and resubmitted. Revising increments `revision_count` by one and clears the prior `ApprovalStep` rows so that the next submission begins a fresh approval cycle (with `required_levels` recomputed against the then-current estimate). Only the original requester may revise; a mismatch between the caller's `X-User-ID` and `requester_id` yields `ERR_SEGREGATION_OF_DUTIES`. The same requester may cancel a requisition from either `DRAFT` or `PENDING_APPROVAL`, driving it to the terminal `CANCELLED` state; cancelling from `PENDING_APPROVAL` first sets every remaining `PENDING` approval step to `SKIPPED`. Cancellation also cascades into sourcing: any `OPEN` RFQ for the requisition is cancelled, and each cancelled RFQ in turn voids its `SUBMITTED` quotes. A rejection cascades the same way — any `OPEN` RFQ for the requisition is moved to `CANCELLED`, which voids its `SUBMITTED` quotes. As with all cancel-style operations, the cancel is refused with `ERR_SEGREGATION_OF_DUTIES` unless the caller is the requester. Approval steps can be retrieved individually or listed; the listing can be narrowed by `requisition_id` and by step `status`.

### 3.2. Competitive Sourcing: RFQs and Vendor Quotes

Once a need exists, a `Buyer` solicits competitive pricing by opening a **Request for Quotation** against a requisition. The RFQ create supplies the `requisition_id` and a quote-collection window: an inclusive `open_at` and an exclusive `close_at`, where `close_at` must be strictly after `open_at` (otherwise `ERR_INVALID_REQUEST`). The new RFQ is born `OPEN`, and its `round_index` is set to the count of RFQs already opened for that requisition — a 0-based negotiation round that lets a buyer run successive sourcing rounds. The `awarded_quote_id` is null until the round is awarded. RFQs can be listed and filtered by `requisition_id`, by `awarded_quote_id`, and by `status`.

Vendors' prices enter as `Quote` rows. A quote names the `rfq_id` it answers, the `vendor_id` quoting, the `submitted_at` instant, and an array of `unit_prices` giving per-line pricing as `{ sku, unit_price_cents, promised_lead_days }`, where every `unit_price_cents` must be strictly positive. The submission instant must fall within the RFQ's half-open window — at or after `open_at` and strictly before `close_at`; a `submitted_at` outside that window is rejected with `ERR_QUOTE_OUTSIDE_WINDOW`. A new quote is born `SUBMITTED`, and its `quoted_total_cents` is computed as the sum over its priced lines of `unit_price_cents` multiplied by the matching requisition line's `quantity` for that `sku`. Quotes can be retrieved, or listed and filtered by `rfq_id`, by `vendor_id`, and by `status`.

Awarding closes the competition. A `Buyer` awards an `OPEN` RFQ by supplying the winning `awarded_quote_id`; this transitions the RFQ from `OPEN` to `AWARDED`. Two preconditions guard the award: the underlying requisition must already be `APPROVED` (otherwise `ERR_REQUISITION_NOT_APPROVED`), and the nominated quote must belong to this RFQ and still be `SUBMITTED` (otherwise `ERR_INVALID_STATE`). On award, the RFQ's `awarded_quote_id` is set, the winning quote moves to `AWARDED`, and every other `SUBMITTED` quote on the same RFQ is moved to `VOIDED`. A buyer may also cancel an `OPEN` RFQ outright — moving it from `OPEN` to `CANCELLED` and voiding its `SUBMITTED` quotes — or close it with no award, moving it from `OPEN` to `CLOSED_NO_AWARD` (permitted only while no `awarded_quote_id` has been set) and likewise voiding its `SUBMITTED` quotes. The cancel path is also the one the requisition cascade uses when a requisition is rejected or cancelled.

### 3.3. Committing Spend: Issuing Purchase Orders

A `PurchaseOrder` is the binding commitment. The system supports two issuance variants over a shared create operation, distinguished by `po_type`. A **STANDARD** order (`po_type` of `STANDARD`) is issued from a single approved requisition against its winning quote: the buyer supplies `vendor_id`, `spend_category_id`, the `requisition_id`, and the awarded `source_quote_id`. The requisition must be `APPROVED` and the `source_quote_id` must be an awarded quote. At issuance the order's `lines` are assembled by copying each awarded-quote line's `sku` and `unit_price_cents` together with the matching requisition `quantity`, with each line's running `received_total` initialized to 0. The order's `total_amount_cents` is the sum over those lines of `quantity` multiplied by `unit_price_cents`. Issuing a STANDARD order also computes the **committed total** for the source requisition — the sum, over the awarded quote's priced lines, of the requisition `quantity` for each `sku` multiplied by that line's quoted `unit_price_cents` — and writes it onto the requisition's `committed_total_cents`. This committed figure uses the winning vendor's actual prices and therefore diverges from the earlier `estimated_total_cents` whenever the quoted price differs from the buyer's estimate; both numbers are exact integer-cent sums.

A **BLANKET** order (`po_type` of `BLANKET`) is a standing agreement rather than a one-off purchase, so it carries no requisition or source quote. The buyer must supply a `ceiling_amount_cents` (strictly positive) capping the cumulative value of releases, plus a validity interval given by an inclusive `valid_from` and an inclusive `valid_to`, where `valid_to` must be after `valid_from`. A BLANKET order is rejected with `ERR_INVALID_REQUEST` if any of `ceiling_amount_cents`, `valid_from`, or `valid_to` is missing. On issuance its `total_amount_cents` is set equal to `ceiling_amount_cents`, and its `remaining_amount_cents` is initialized to the full ceiling (it will be drawn down by releases). To prevent overlapping standing agreements, a new BLANKET order is rejected with `ERR_BLANKET_PERIOD_OVERLAP` if its closed `[valid_from, valid_to]` interval overlaps the interval of any existing `ISSUED` blanket for the **same** vendor and spend category; because the interval is treated as closed, two intervals that merely touch at an endpoint (adjacency) count as overlapping.

Both variants are born `ISSUED`. At issuance the system also sets the `is_maverick` flag: it is true when the order's `vendor_id` differs from the charged spend category's `preferred_vendor_id`, and false otherwise — this is the maverick-spend signal that surfaces off-contract buying. Purchase orders can be retrieved and listed, with the listing filterable by `vendor_id`, `spend_category_id`, `requisition_id`, `source_quote_id`, `po_type`, `status`, and the boolean `is_maverick`.

A purchase order leaves `ISSUED` in one of two ways. A `Buyer` may close it, moving it from `ISSUED` to `CLOSED`. For a STANDARD order, closing requires that every PO line's `received_total` has reached at least its ordered `quantity`, unless the buyer supplies a truthy `force` flag to override — without full receipt and without `force` the close is refused with `ERR_PO_NOT_FULLY_RECEIVED`. For a BLANKET order, closing requires that no `OPEN` release remains against it, otherwise `ERR_BLANKET_HAS_OPEN_RELEASES`. Alternatively a buyer may cancel an `ISSUED` order, moving it to `CANCELLED`; cancellation is refused with `ERR_PO_HAS_RECEIPTS` if any `POSTED` goods receipt references the order. Cancelling a BLANKET order cascades to every `OPEN` release against it: each such release is moved to `CANCELLED`, and as each is cancelled the release's `amount_cents` is added back to the blanket's `remaining_amount_cents` as a compensating restore.

### 3.4. Drawing Down a Blanket: Release Orders

A blanket agreement is consumed through `ReleaseOrder` draws, each created by a `Buyer`. A release names the `blanket_po_id` it draws from, an `amount_cents` to draw (strictly positive), and an array of `lines` of `{ sku, quantity, unit_price_cents }` where every `quantity` is strictly positive and the sum over the lines of `quantity` multiplied by `unit_price_cents` must equal the declared `amount_cents` exactly — a mismatch is rejected with `ERR_INVALID_REQUEST`. The referenced purchase order must itself be a blanket: if `blanket_po_id` points at a non-BLANKET order, the release is refused with `ERR_NOT_BLANKET_PO`. The draw may not exceed the headroom remaining on the blanket — if `amount_cents` is greater than the blanket's current `remaining_amount_cents`, the release is refused with `ERR_RELEASE_EXCEEDS_CEILING`.

Release creation is the system's one optimistic-concurrency point. The request must carry `expected_purchase_order_version` equal to the blanket's current `version`; if another release has advanced the blanket's `version` since the client last read it, the draw is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing a re-read before the stale draw can proceed. On a successful create the release is born `OPEN`, the blanket's `remaining_amount_cents` is decremented by `amount_cents`, and the blanket's `version` is incremented by one (its `updated_at` refreshing accordingly). Releases can be retrieved and listed, the listing filterable by `blanket_po_id` and by `status`.

A buyer may cancel an `OPEN` release, moving it from `OPEN` to `CANCELLED`; this is refused with `ERR_RELEASE_HAS_RECEIPTS` if any `POSTED` goods receipt references the release. Cancelling a release restores its `amount_cents` to the parent blanket's `remaining_amount_cents` and increments that blanket's `version` by one. A release also leaves `OPEN` for `RECEIVED` automatically: when a `POSTED` goods receipt fully covers the release's lines, the system flips that release from `OPEN` to `RECEIVED`. The same blanket-cancel cascade described above also drives `OPEN` releases to `CANCELLED` with the matching ceiling restore.

### 3.5. Receiving Goods and the Conserved Quantity Ledger

A `Receiver` records the physical arrival of ordered goods as a `GoodsReceipt`. The receipt names the `purchase_order_id` it satisfies, optionally a `release_order_id`, an array of `received_lines` of `{ sku, received_qty }` where every `received_qty` is strictly positive, and the actual `received_at` instant. The receipt is born `POSTED` and records the posting receiver's identifier as `posted_by_id`. Several preconditions guard posting: the purchase order must be `ISSUED` (otherwise `ERR_INVALID_STATE`); when the purchase order is a blanket, a `release_order_id` is required and its absence is rejected with `ERR_INVALID_REQUEST`; and segregation of duties forbids the receiver from being the requisition requester of the order being received — if the acting receiver's `X-User-ID` equals the `requester_id` of the requisition behind the linked purchase order, the post is refused with `ERR_SEGREGATION_OF_DUTIES`.

Receiving maintains a **conserved received-quantity ledger** on the purchase order. Posting a receipt increments each affected PO line's `received_total` by the `received_qty` for that `sku`. The cumulative `received_qty` per `sku` may not exceed the ordered `quantity` beyond the receipt tolerance; an over-delivery beyond what tolerance permits is rejected with `ERR_RECEIPT_OVER_TOLERANCE`. If a posted receipt fully covers a linked release order, that release moves from `OPEN` to `RECEIVED` as part of the same operation. Goods receipts can be retrieved and listed, the listing filterable by `purchase_order_id`, by `release_order_id`, and by `status`.

A receiver may reverse a `POSTED` receipt, moving it from `POSTED` to the terminal `REVERSED`. A reversal is refused with `ERR_RECEIPT_HAS_INVOICE` if any invoice that is `MATCHED` or in `EXCEPTION` references the receipt — once a receipt has anchored a completed or failed match it can no longer be unwound. Reversing decrements each affected PO line's `received_total` by that receipt's `received_qty` per `sku`, the compensating restore that keeps the quantity ledger conserved, and if a linked release order had been moved to `RECEIVED` solely by this receipt, that release is reverted to `OPEN`.

### 3.6. The 3-Way Match and Tolerance Evaluation

A `PayablesClerk` records a vendor's bill as an `Invoice`, supplying the `vendor_id`, the `purchase_order_id`, the `goods_receipt_id` the invoice is matched against, a vendor-unique `invoice_number`, and an array of `lines` of `{ sku, billed_qty, billed_unit_price_cents }` where every `billed_qty` and `billed_unit_price_cents` is strictly positive. An invoice is born with `match_status` of `UNMATCHED` and `payment_status` of `PENDING` — these are two independent dimensions on one row that evolve separately. Its `invoice_number` must be unique for that vendor across all non-void invoices; a duplicate is rejected with `ERR_INVALID_REQUEST`. The `invoice_total_cents` is computed by rounding each line's `billed_qty` multiplied by `billed_unit_price_cents` to whole cents and then summing those per-line amounts. Invoices can be retrieved and listed, the listing filterable by `vendor_id`, `purchase_order_id`, `goods_receipt_id`, `match_status`, and `payment_status`.

A `Matcher` runs the **3-way match**, which compares ordered-versus-received-versus-billed for the invoice and either passes it to `MATCHED` or fails it to `EXCEPTION` along the match dimension, starting from `UNMATCHED`. The match first requires that a `POSTED` goods receipt is referenced by the invoice's `goods_receipt_id`; if none exists the match cannot proceed and yields `ERR_NO_RECEIPT`. Each invoice line is then joined by `sku` to its purchase-order line (which supplies the ordered `unit_price_cents`) and to the matched receipt's `received_qty`. Two per-line gates and one invoice-wide gate decide the outcome:

- **Price gate.** A line's billed unit price is within tolerance when `billed_unit_price_cents` is at most the price ceiling, where the price ceiling is the floor of the PO line's ordered `unit_price_cents` multiplied by one plus the price-tolerance percentage. The price tolerance is **5 percent**, so the ceiling is the floor of the ordered unit price times 1.05; a billed price exactly at that floored ceiling passes, and one cent above it fails.
- **Quantity gate.** A line's billed quantity is within tolerance when `billed_qty` is at most the matched receipt's `received_qty` for that `sku`. The quantity tolerance is **zero percent** — a vendor may never bill more than was received.
- **Amount gate.** As a secondary, invoice-wide check, the `invoice_total_cents` must be at most the amount ceiling, where the amount ceiling is the floor of the matched PO amount multiplied by one plus the amount-tolerance percentage. The matched PO amount is the sum, over the matched `sku`s, of the receipt's `received_qty` for that `sku` multiplied by the PO line's ordered `unit_price_cents`. The amount tolerance is **2 percent**, so the ceiling is the floor of the matched PO amount times 1.02.

The match **passes** only when every line clears both its price gate and its quantity gate, the invoice-wide amount gate also holds, and a `POSTED` receipt exists; passing moves `match_status` to `MATCHED`. Otherwise it **fails**, moving `match_status` to `EXCEPTION` and opening a `MatchException`. When the match fails, the reason recorded is determined by the **first** failing gate in this fixed priority order: missing posted receipt first (`NO_RECEIPT`), then a price-tolerance breach on the first offending line taken in ascending `sku` order (`PRICE_OVER_TOLERANCE`), then a quantity breach on the first offending line in ascending `sku` order (`QTY_OVER_TOLERANCE`), and finally an amount-tolerance breach (`AMOUNT_OVER_TOLERANCE`). All gate ceilings are floored to whole cents before comparison.

### 3.7. Exceptions, Vendor Probation, and Closing the Match

When a match fails, the cascade is precise. A `MatchException` is created in `OPEN` status, recording the `invoice_id`, the offending `reason` drawn from `PRICE_OVER_TOLERANCE`, `QTY_OVER_TOLERANCE`, `AMOUNT_OVER_TOLERANCE`, or `NO_RECEIPT`, and a human-readable `detail` naming the offending `sku` and computed delta. The exception denormalizes the `vendor_id` from the invoice so that it can be attributed to the vendor's scorecard. Creating the exception then recomputes the offending vendor's `exception_count` (its count of open exceptions); if that count rises above the probation threshold of three open exceptions, the vendor moves from `APPROVED` to `PROBATION`. This serialization — match failure to exception creation to vendor probation — is the intended chain that lets accumulating disputes throttle a vendor automatically.

A `Matcher` clears an exception by resolving or waiving it. Resolving an `OPEN` exception moves it to `RESOLVED`; waiving an `OPEN` exception moves it to `WAIVED`. Waiving carries a segregation-of-duties guard: the acting matcher may not be the receiver who posted the receipt behind the match — if the matcher's `X-User-ID` equals the matched receipt's `posted_by_id`, the waive is refused with `ERR_SEGREGATION_OF_DUTIES`. Both resolving and waiving recompute the vendor's `exception_count`; if that count falls to three or fewer open exceptions and the vendor is in `PROBATION`, the vendor returns from `PROBATION` to `APPROVED`. Both also check whether any `OPEN` exception remains for the invoice: when none does, the invoice's match dimension moves from `EXCEPTION` to `MATCHED`. Match exceptions can be retrieved and listed, the listing filterable by `invoice_id`, by `vendor_id`, and by `status`.

The payment dimension runs independently of the match dimension. A `PayablesClerk` may approve a matched invoice for payment, moving `payment_status` from `PENDING` to `APPROVED_FOR_PAY`; this requires the invoice's `match_status` to be `MATCHED` and is otherwise refused with `ERR_INVOICE_NOT_MATCHED`. A clerk may instead reject an invoice for payment from `PENDING`, moving `payment_status` to `REJECTED` (no match precondition applies to a rejection). Finally a clerk pays an approved invoice, moving `payment_status` from `APPROVED_FOR_PAY` to `PAID`; attempting to pay an invoice that is not in `APPROVED_FOR_PAY` is refused with `ERR_INVALID_STATE`.

### 3.8. Vendor Scorecards and Performance Scoring

A `ProcurementAdmin` snapshots a vendor's performance over a window by creating an immutable `VendorScorecard`. The create supplies the `vendor_id`, an inclusive `period_start`, an exclusive `period_end` (which must be after `period_start`), and an optional `on_time_variant` selecting the delivery-scoring algorithm, defaulting to `STRICT`. Periods for a single vendor must tile without overlap: a new period whose half-open `[period_start, period_end)` window overlaps an existing scorecard period for the same vendor is rejected with `ERR_SCORECARD_PERIOD_OVERLAP`; because the window is half-open, adjacency (one period's end equal to the next period's start) is allowed. A scorecard is born `FINAL` and is never mutated thereafter. Scorecards can be retrieved and listed, the listing filterable by `vendor_id`.

The scorecard computes four figures over the `POSTED` goods receipts whose `received_at` falls in the half-open period window for this vendor's purchase orders. The **on-time delivery rate**, stored as `on_time_rate_pct`, considers each such receipt: from the awarded quote line it reads the `promised_lead_days`, and the promised delivery date is the purchase order's issuance date plus that many days. Under the `STRICT` variant a receipt is on time when its `received_at` is at or before the promised date; under the `GRACE` variant the promised date is extended by the vendor's `grace_days` before the comparison, so the same data yields an on-time rate at least as high as `STRICT`. The on-time rate is then 100 multiplied by the on-time count divided by the total receipt count, rounded half up to an integer percentage; when there are no receipts in the period the on-time rate is defined to be 100. The **price-compliance percentage**, stored as `price_compliance_pct`, is the percentage of matched invoice lines that fell within price tolerance over the period, and the **exception percentage**, stored as `exception_pct`, is the percentage of period receipts that produced a match exception; both are integer percentages in the range 0 to 100.

The **composite score**, stored as `composite_score`, weights three components: the on-time rate, the price-compliance percentage, and a reliability term equal to 100 minus `exception_pct`. The weights are 0.5 for on-time delivery, 0.3 for price compliance, and 0.2 for reliability. The composite is computed by the round-each-then-sum rule, in this pinned order: round half up the on-time rate times 0.5 to an integer, round half up the price-compliance percentage times 0.3 to an integer, round half up the reliability term times 0.2 to an integer, then add the three rounded integers to obtain `composite_score`. The per-component rounding is mandatory and is not the same as summing the weighted figures and rounding once — the two can differ by a point, and the per-component order is the contract.

## 4. Endpoint Definitions

All endpoints are mounted under `/procurement`. A request that creates a new resource returns HTTP 201; a request that reads or modifies an existing resource returns HTTP 200. Request bodies, response payloads, and side effects are not restated in this table — they are specified in the Section 3 workflow narratives and must be reconstructed from there. Every endpoint requires the `X-User-ID` and `X-User-Role` headers described in Section 2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /procurement/spend-categories | Create a spend category with approval thresholds | ProcurementAdmin |
| GET | /procurement/spend-categories/{id} | Get a spend category | ProcurementAdmin, Buyer, Approver, Receiver, Matcher, PayablesClerk |
| GET | /procurement/spend-categories | List spend categories | ProcurementAdmin, Buyer, Approver, Receiver, Matcher, PayablesClerk |
| POST | /procurement/spend-categories/{id}/archive | Archive a spend category | ProcurementAdmin |
| POST | /procurement/vendors | Register a vendor | ProcurementAdmin |
| GET | /procurement/vendors/{id} | Get a vendor | ProcurementAdmin, Buyer, Approver, Receiver, Matcher, PayablesClerk |
| GET | /procurement/vendors | List vendors | ProcurementAdmin, Buyer, Approver, Receiver, Matcher, PayablesClerk |
| POST | /procurement/vendors/{id}/block | Block a vendor | ProcurementAdmin |
| POST | /procurement/requisitions | Create a draft requisition | Buyer |
| GET | /procurement/requisitions/{id} | Get a requisition | ProcurementAdmin, Buyer, Approver, Receiver, Matcher, PayablesClerk |
| GET | /procurement/requisitions | List requisitions | ProcurementAdmin, Buyer, Approver, Receiver, Matcher, PayablesClerk |
| POST | /procurement/requisitions/{id}/submit | Submit requisition for approval | Buyer |
| POST | /procurement/requisitions/{id}/approve | Approve the current pending approval step | Approver |
| POST | /procurement/requisitions/{id}/reject | Reject the requisition at the current step | Approver |
| POST | /procurement/requisitions/{id}/revise | Return a rejected requisition to draft | Buyer |
| POST | /procurement/requisitions/{id}/cancel | Cancel a requisition | Buyer |
| GET | /procurement/approval-steps/{id} | Get an approval step | ProcurementAdmin, Buyer, Approver |
| GET | /procurement/approval-steps | List approval steps, filterable by requisition | ProcurementAdmin, Buyer, Approver |
| POST | /procurement/rfqs | Open an RFQ round against a requisition | Buyer |
| GET | /procurement/rfqs/{id} | Get an RFQ | ProcurementAdmin, Buyer, Approver |
| GET | /procurement/rfqs | List RFQs | ProcurementAdmin, Buyer, Approver |
| POST | /procurement/rfqs/{id}/award | Award an RFQ to a quote | Buyer |
| POST | /procurement/rfqs/{id}/cancel | Cancel an RFQ | Buyer |
| POST | /procurement/rfqs/{id}/close_no_award | Close an RFQ with no award | Buyer |
| POST | /procurement/quotes | Submit a vendor quote against an RFQ | Buyer |
| GET | /procurement/quotes/{id} | Get a quote | ProcurementAdmin, Buyer, Approver |
| GET | /procurement/quotes | List quotes | ProcurementAdmin, Buyer, Approver |
| POST | /procurement/purchase-orders | Issue a STANDARD or BLANKET purchase order | Buyer |
| GET | /procurement/purchase-orders/{id} | Get a purchase order | ProcurementAdmin, Buyer, Approver, Receiver, Matcher, PayablesClerk |
| GET | /procurement/purchase-orders | List purchase orders | ProcurementAdmin, Buyer, Approver, Receiver, Matcher, PayablesClerk |
| POST | /procurement/purchase-orders/{id}/close | Close a purchase order | Buyer |
| POST | /procurement/purchase-orders/{id}/cancel | Cancel a purchase order | Buyer |
| POST | /procurement/release-orders | Create a release against a blanket PO | Buyer |
| GET | /procurement/release-orders/{id} | Get a release order | ProcurementAdmin, Buyer, Receiver, Matcher |
| GET | /procurement/release-orders | List release orders | ProcurementAdmin, Buyer, Receiver, Matcher |
| POST | /procurement/release-orders/{id}/cancel | Cancel a release order | Buyer |
| POST | /procurement/goods-receipts | Post a goods receipt against a PO | Receiver |
| GET | /procurement/goods-receipts/{id} | Get a goods receipt | ProcurementAdmin, Buyer, Receiver, Matcher, PayablesClerk |
| GET | /procurement/goods-receipts | List goods receipts | ProcurementAdmin, Buyer, Receiver, Matcher, PayablesClerk |
| POST | /procurement/goods-receipts/{id}/reverse | Reverse a goods receipt | Receiver |
| POST | /procurement/invoices | Record a vendor invoice | PayablesClerk |
| GET | /procurement/invoices/{id} | Get an invoice | ProcurementAdmin, Buyer, Matcher, PayablesClerk |
| GET | /procurement/invoices | List invoices | ProcurementAdmin, Buyer, Matcher, PayablesClerk |
| POST | /procurement/invoices/{id}/match | Run the 3-way match | Matcher |
| POST | /procurement/invoices/{id}/approve-payment | Approve a matched invoice for payment | PayablesClerk |
| POST | /procurement/invoices/{id}/reject-payment | Reject an invoice for payment | PayablesClerk |
| POST | /procurement/invoices/{id}/pay | Mark an approved invoice paid | PayablesClerk |
| GET | /procurement/match-exceptions/{id} | Get a match exception | ProcurementAdmin, Buyer, Matcher, PayablesClerk |
| GET | /procurement/match-exceptions | List match exceptions | ProcurementAdmin, Buyer, Matcher, PayablesClerk |
| POST | /procurement/match-exceptions/{id}/resolve | Resolve a match exception | Matcher |
| POST | /procurement/match-exceptions/{id}/waive | Waive a match exception | Matcher |
| POST | /procurement/vendor-scorecards | Create an immutable vendor scorecard snapshot | ProcurementAdmin |
| GET | /procurement/vendor-scorecards/{id} | Get a vendor scorecard | ProcurementAdmin, Buyer, Approver |
| GET | /procurement/vendor-scorecards | List vendor scorecards | ProcurementAdmin, Buyer, Approver |
| POST | /procurement/_clock/set_current_utc | Set the server clock for deterministic time-based tests | ProcurementAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_USER_CONTEXT | 401 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_INVALID_STATE | 409 |
| ERR_NOT_BLANKET_PO | 409 |
| ERR_REQUISITION_NOT_APPROVED | 409 |
| ERR_QUOTE_OUTSIDE_WINDOW | 409 |
| ERR_BLANKET_PERIOD_OVERLAP | 409 |
| ERR_SCORECARD_PERIOD_OVERLAP | 409 |
| ERR_APPROVAL_INCOMPLETE | 409 |
| ERR_RECEIPT_OVER_TOLERANCE | 409 |
| ERR_RELEASE_EXCEEDS_CEILING | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_NO_RECEIPT | 409 |
| ERR_INVOICE_NOT_MATCHED | 409 |
| ERR_PO_NOT_FULLY_RECEIVED | 409 |
| ERR_BLANKET_HAS_OPEN_RELEASES | 409 |
| ERR_PO_HAS_RECEIPTS | 409 |
| ERR_RELEASE_HAS_RECEIPTS | 409 |
| ERR_RECEIPT_HAS_INVOICE | 409 |

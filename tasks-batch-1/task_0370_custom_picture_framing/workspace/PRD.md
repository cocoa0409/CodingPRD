# Custom Picture Framing API — Product Requirements Document

## 1. Introduction

This document specifies the Custom Picture Framing API, a back-office system for a frame shop that takes a customer's artwork through intake, measurement, pricing, production scheduling, payment, and pickup. The business has a recurring tension: an estimate quoted at the front counter from a customer's stated dimensions is rarely the same as the invoice produced once a bench technician measures the piece and cuts the mat. The API formalizes both numbers — a forward-looking quote estimate and a measured final invoice — and the rules that govern how an order moves between them.

A framing order is more than a price. Each piece of artwork becomes a line on the order with its own mat, glass, molding, and mounting choices; some pieces are fragile (antique works, hand-blown glass art, or anything mounted behind museum-grade glass) and demand special handling on a dedicated glass-cutting bench with a clean-handling buffer around every job. Production is scheduled against a finite pool of workbenches, deposits gate the start of work, and the shop tracks each customer's reliability so that a history of abandoned orders raises their projected no-show risk. The system therefore behaves simultaneously as a **pricing engine** and a **workflow orchestrator**, and the two responsibilities are deliberately interleaved across the lifecycle of every order.

The remainder of this document defines the global contracts that every endpoint honors (Section 2), the business workflows and their scattered rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_CONTEXT`. The system recognizes exactly four roles, spelled precisely as follows: `FrameDesigner`, `FrameProductionTech`, `FrontDeskClerk`, and `Customer`. When a request carries a recognized role but that role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Three of these roles are staff identities whose `X-User-ID` is an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `FrameDesigner`, `X-User-ID` is an opaque identifier; the server may record it but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `FrameProductionTech` and when `X-User-Role` is `FrontDeskClerk`: in both cases `X-User-ID` is an opaque operator identifier with no entity backing. A `FrameDesigner` owns artwork intake, line management (add, measure, void), quoting, and reorder cloning. A `FrameProductionTech` owns workbench creation, production-task scheduling and completion, and the production lifecycle transitions (start production, mark ready). A `FrontDeskClerk` owns deposits and payments, pickup, cancellation, and the customer-facing notifications. Order and customer creation, as well as reorder cloning, are shared between `FrameDesigner` and `FrontDeskClerk`.

The fourth role is entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare the resource's owning-customer foreign key to `X-User-ID`. A `Customer` may only read, never write: they may retrieve their own profile (the `X-User-ID` must equal the addressed customer), list and read their own framing orders (the order's `customer_id` must equal `X-User-ID`), and read the lines, payments, notifications, and production tasks of orders they own. A `Customer` request that addresses an order, line, payment, or task belonging to a different customer is rejected with `ERR_FORBIDDEN_ROLE`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0 with a minimum of 0. Unless a workflow states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in the system — Customers, Workbenches, Framing Orders, Frame Lines, Production Tasks, and Payments — carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix, serving as identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recorded at creation and never changed afterward; for the chronological calculations described later, `created_at` is the ordering and tie-break key. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation, including mutations that arrive as cascades from another operation. The `version` field is an integer that starts at 1 and increases by one on every mutation of the resource.

The **Notification** resource is the single exception. A notification is an append-only record and therefore carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field. Whenever a derived field on a resource is recomputed — an order's `balance_due`, a customer's `no_show_risk_score`, or any other computed value — that recomputation is a mutation: it refreshes `updated_at` and increments `version` on the resource that owns the field.

### 2.5. Nested Resource Retrieval and Left-to-Right Validation

Many endpoints address resources through a path that names a parent before a child — an order before its lines, payments, notifications, or production tasks; a customer before their orders; a workbench before its tasks. The system validates the identifiers in such a path strictly left to right and rejects the request at the first identifier that does not resolve to an existing resource. A request for the lines of a non-existent order fails with `ERR_ORDER_NOT_FOUND` before any line is consulted. The not-found codes are resource-specific: `ERR_ORDER_NOT_FOUND` for a framing order, `ERR_LINE_NOT_FOUND` for a frame line, `ERR_TASK_NOT_FOUND` for a production task, `ERR_PAYMENT_NOT_FOUND` for a payment, `ERR_CUSTOMER_NOT_FOUND` for a customer (whether named in the path or referenced as a body `customer_id`), and `ERR_WORKBENCH_NOT_FOUND` for a workbench (whether named in the path or referenced as a body `workbench_id`). Existence is checked in the same left-to-right order for body references as well: the order is resolved first, then any line, task, or payment, then customer and workbench references in the body.

### 2.6. Validation Ordering

When several validation classes could apply to one request, they are evaluated in a fixed priority order so that the reported error is always the highest-priority failure. The order is: first, authentication — the presence and well-formedness of `X-User-ID` and `X-User-Role` (`ERR_MISSING_AUTH_CONTEXT`, HTTP 401); second, authorization — whether the role is permitted for the operation, and for a `Customer` whether `X-User-ID` owns the addressed order (`ERR_FORBIDDEN_ROLE`, HTTP 403); third, existence of every path and body resource id, validated left-to-right (the 404 family above); fourth, request-body well-formedness — required fields present, enums valid, numeric dimensions strictly positive, and `deposit_pct` within its allowed range (`ERR_INVALID_REQUEST`, HTTP 400); fifth, the optimistic-concurrency check on frame-line add (`ERR_STALE_ORDER_VERSION`, HTTP 412); sixth, the target resource's state being valid for the requested transition — a transition attempted from a state that does not allow it fails in the 409 state family, defaulting to `ERR_INVALID_STATE` when no more specific state error (`ERR_ORDER_NOT_EDITABLE`, `ERR_NOT_QUOTED`, `ERR_ORDER_NOT_IN_PRODUCTION`, `ERR_DEPOSIT_ALREADY_PAID`, `ERR_DEPOSIT_NOT_PAID`, or `ERR_NOT_PICKED_UP`) applies; seventh, cross-entity referential preconditions such as "every line measured" or "every task completed" (HTTP 409); eighth, the fragile-handling bench requirement (`ERR_FRAGILE_REQUIRES_GLASS_BENCH`, HTTP 409); ninth, workbench interval availability (`ERR_WORKBENCH_CONFLICT`, HTTP 409); and tenth and eleventh, the fiscal checks on deposits, balances, and pickup (the 402 family). A lower-priority check is never reported while a higher-priority one is failing.

### 2.7. Monetary Precision and Rounding

All dollar amounts the system computes — per-line subtotals, estimate and invoice totals, deposits, ledger balances — are rounded to exactly 2 decimal places using the round-half-up method, and are returned in response bodies as numbers, not strings. Customer-supplied rate and configuration inputs such as `molding_rate_per_ui` retain the precision they were submitted with. Two rounding disciplines coexist in this system and must not be conflated: the quote estimate sums every line first and rounds once at the very end (a sum-then-round discipline), whereas the final invoice rounds each discounted line to cents before summing them (a round-per-line-then-sum discipline). These two disciplines, defined precisely in Section 3, can produce different totals for the very same set of lines, which is intended.

### 2.8. Optimistic Concurrency on Frame-Line Additions

Adding a frame line to an order is the one write in this system guarded by optimistic concurrency control, because a new line changes the set of lines the estimate is computed from and therefore supersedes the prior quote snapshot. A request to add a frame line to an order must include the field `expected_order_version`, carrying the client's last observed `version` of the target `FramingOrder`. This field is mandatory on that operation; no other endpoint accepts it. If `expected_order_version` does not equal the order's current `version` — that is, if another writer has advanced the order's version since the client last read it — the addition is rejected with `ERR_STALE_ORDER_VERSION` and HTTP status 412, forcing the writer to re-read the order before adding a line it has not observed. Endpoints that are not the frame-line add never take a version field and never perform this check.

### 2.9. Fragile and Glass Handling

An order is considered to contain fragile work — exposed through the order's `has_fragile_line` flag — when at least one of its frame lines that is not voided either is mounted behind `MUSEUM` glass or carries an explicit `is_fragile` mark of true. Museum glass always implies fragility even when `is_fragile` was left false. This flag is recomputed whenever the line set changes: when a line is added, voided, or otherwise revised. Fragility has three downstream consequences described in Section 3: it raises the deposit floor, it extends the promised turnaround, and it forces any production task for the order onto a glass-cutting bench. Workbenches come in two kinds, recorded in `bench_type`: an `ASSEMBLY` bench and a `GLASS_CUTTING` bench. A glass-cutting bench enforces a clean-handling buffer, the `clean_buffer_minutes` idle gap required before and after any job on it, in keeping with safe handling of fragile pieces and freshly cut glass.

## 3. Business Logic & Workflows

### 3.1. Customers, Loyalty, and Reliability Scoring

A customer record is created by a `FrontDeskClerk` or a `FrameDesigner` with a `full_name`, an `email`, and a `phone`; the email is what the shop later uses to reach the customer with a ready notification. A customer may optionally be placed in a loyalty tier through `loyalty_tier`, which is one of `STANDARD`, `PREFERRED`, or `TRADE` and defaults to `STANDARD` when omitted. The tier determines the customer's `loyalty_discount_pct`, a derived field: a `STANDARD` customer receives a discount fraction of 0.00, a `PREFERRED` customer 0.10, and a `TRADE` customer 0.15. At creation the customer's reliability fields are seeded — `no_show_risk_score` starts at 0 and `settled_reputation_score` starts at 50 — and `open_order_count` starts at 0.

The customer carries three computed reliability fields that the system keeps current. The **open order count**, `open_order_count`, is the number of this customer's framing orders whose `production_status` is neither `PICKED_UP` nor `CANCELLED`. The **forward-looking no-show risk**, `no_show_risk_score`, is a projection over those same open orders: it weights every open order by 5 points and additionally weights each open order that is simultaneously in `READY` status and not yet `PAID_IN_FULL` by a further 15 points, then clamps the result at a ceiling of 100. Concretely, the score is the count of open orders multiplied by 5, plus the count of ready-but-unpaid open orders multiplied by 15, with the smaller of that sum and 100 taken as the final value. This score is recomputed whenever an order is created, quoted, picked up, or cancelled, since each of those events changes the open set or its ready-unpaid subset.

The **settled reputation**, `settled_reputation_score`, is a chronological replay rather than a snapshot. It begins from a seed base of 50 and walks the customer's settled outcomes in the order their orders reached a terminal state, ordered by the terminal transition's `created_at` ascending. Each order that was picked up contributes an on-time outcome and each order that was cancelled contributes an abandon outcome. Processing the outcomes one at a time in that chronological order, an on-time outcome subtracts 10 from the running score and an abandon outcome adds 20 to it; after each individual step the running score is clamped to the range from 0 to 100. Because the clamp is applied after every step rather than once at the end, the order of outcomes can change the final number, so the replay must always proceed chronologically. The resulting clamped value is the customer's settled reputation. A lower no-show risk and a lower settled reputation each describe a more reliable customer relationship, and these scores are surfaced freshly on every read of the customer.

### 3.2. Intake: Opening an Order and Building Its Lines

A framing order begins life when a `FrameDesigner` or `FrontDeskClerk` opens an intake for a customer, supplying the `customer_id` of the owning customer and optionally `rush_requested` and `deposit_pct`. A new order starts with `production_status` of `INTAKE` and `payment_status` of `UNBILLED`. The `rush_requested` flag defaults to false; when true, a rush surcharge later applies to both the estimate and the final invoice. The `deposit_pct` is the requested deposit fraction of the estimate and defaults to 0.30; it must be at least 0.10 and at most 1.00, and a value outside that closed range is rejected as an invalid request. Opening an order also recomputes the owning customer's `open_order_count` and `no_show_risk_score`, since a fresh open order has joined the customer's open set. Each order also carries `reorder_of_order_id`, which is null for a normally-opened order and is set only when the order was cloned from a prior picked-up order (see Section 3.8).

While the order sits in `INTAKE`, a `FrameDesigner` builds it up one artwork piece at a time. Each piece becomes a **frame line** carrying an `artwork_label` describing the piece, the customer-stated intake dimensions `nominal_width_in` and `nominal_height_in` (each strictly greater than zero, in inches), and a `molding_rate_per_ui`, the molding price per united inch in dollars (at least zero). Several material choices accompany each line: `mat_border_in` is the mat reveal added to each side of the artwork in inches (at least zero, defaulting to 2); `mat_layers` is the count of stacked mat boards (an integer of at least 1, defaulting to 1); `glass_type` is one of `REGULAR`, `CONSERVATION`, or `MUSEUM` and defaults to `REGULAR`; `mounting_type` is one of `NONE`, `PLAIN`, `DRY_MOUNT`, or `CONSERVATION_HINGE` and defaults to `NONE`; `conservation_package` is a boolean defaulting to false; and `is_fragile` is a boolean defaulting to false. A newly added line starts in `line_status` of `DRAFT`. The act of adding a line supersedes the order's prior quote snapshot, so it requires the client to present `expected_order_version` matching the order's current `version`; a mismatch is the stale-version rejection described in Section 2.8. On a successful add, the line's `estimate_subtotal` is computed immediately from the nominal dimensions (the nominal pricing variant of Section 3.3), the order's `has_fragile_line` flag is recomputed, and the order's `version` is incremented by one.

Two further edits are available to the `FrameDesigner` while the owning order's `production_status` is `INTAKE` or `QUOTED`; attempting either while the order is in any other production state is rejected with `ERR_ORDER_NOT_EDITABLE`. The first is **measuring** a line, which advances it from `DRAFT` to `MEASURED`: the bench technician records `measured_width_in` and `measured_height_in` (each strictly greater than zero, in inches — a non-positive value is rejected with `ERR_INVALID_DIMENSIONS`), which sets those fields, recomputes the line's `final_subtotal` from the measured pricing variant of Section 3.3, and increments the line's `version`. The second is **voiding** a line, which advances it from `DRAFT` to `VOID`; voiding recomputes the owning order's `has_fragile_line` and increments the line's `version`. A voided line is excluded from every total and from the fragility determination.

### 3.3. Per-Line Pricing

The price of a single frame line is built up the same way for both pricing variants; only the dimensions differ. The nominal variant uses `nominal_width_in` and `nominal_height_in` and produces `estimate_subtotal`; it runs when a line is created and again for every non-voided line when the order is quoted. The measured variant uses `measured_width_in` and `measured_height_in` (which must already be set) and produces `final_subtotal`; it runs when a line is measured and feeds the final invoice. Because measured dimensions generally differ from the nominal ones, the two subtotals generally differ for the same line.

Take the line's width and height for the active variant. The outer width is the artwork width plus twice `mat_border_in`, and the outer height is the artwork height plus twice `mat_border_in`. The number of **united inches** for the line is the outer width plus the outer height. The framed **area in square feet** is the outer width multiplied by the outer height, divided by 144. From these:

- The **molding cost** is the united inches multiplied by `molding_rate_per_ui`, rounded to two decimal places.
- The **mat cost** is the area in square feet multiplied by a mat rate of 6.00 dollars per square foot, multiplied by `mat_layers`, rounded to two decimal places.
- The **glass cost** is the area in square feet multiplied by a per-glass-type rate, rounded to two decimal places. The glass rate is 4.00 dollars per square foot for `REGULAR`, 9.00 for `CONSERVATION`, and 18.00 for `MUSEUM`.
- The **oversize surcharge** is tiered on united inches and is non-additive — only the single highest tier the line crosses applies. If the united inches are at least 120, the surcharge is 95.00. Otherwise, if the united inches are at least 80, the surcharge is 40.00. Otherwise the surcharge is 0.00.
- The **mounting upcharge** is a flat amount keyed to `mounting_type`: 0.00 for `NONE`, 15.00 for `PLAIN`, 35.00 for `DRY_MOUNT`, and 55.00 for `CONSERVATION_HINGE`.

The line's **materials** figure is the mat cost plus the glass cost. If `conservation_package` is true on the line, the materials figure is multiplied by a conservation multiplier of 1.20 and the product rounded to two decimal places before proceeding; the conservation package therefore inflates only the mat and glass portion, not the molding, surcharge, or mounting. The line subtotal is then the sum of the molding cost, the (possibly conservation-adjusted) materials figure, the oversize surcharge, the mounting upcharge, and a flat labor charge of 45.00 dollars per line, with that sum rounded to two decimal places. All per-line monetary rounding uses round-half-up.

### 3.4. Quoting: The Estimate Total, Deposit, and Turnaround

Quoting an order is the `FrameDesigner` action that advances `production_status` from `INTAKE` to `QUOTED`. It is permitted only when the order has at least one frame line that is not voided; an order with no such line is rejected with `ERR_NO_LINES`. Quoting runs a battery of computations and side effects, then increments the order's `version`.

The **estimate total**, stored in `estimate_total`, is computed over the order's non-voided frame lines ordered by `created_at` ascending, using each line's nominal `estimate_subtotal`. The raw sum is the total of those subtotals. If `rush_requested` is true, the raw sum is multiplied by 1.15 (a 15 percent rush surcharge) to yield a rushed sum; otherwise the rushed sum equals the raw sum. The owning customer's `loyalty_discount_pct` is then applied to the rushed sum by multiplying it by one minus that discount fraction, and the result is rounded once to two decimal places. This is the sum-then-round discipline: every line is summed, the rush and discount are applied to the aggregate, and a single final rounding is performed after the discount.

The **deposit required**, stored in `deposit_required`, is derived from the estimate. Start from the requested `deposit_pct`. If the order has a fragile line and the requested fraction is below a fragile deposit floor of 0.50, raise the fraction to 0.50; otherwise keep the requested fraction. Multiply `estimate_total` by the resulting fraction and round to two decimal places to obtain a raw deposit, then take the larger of a minimum deposit of 25.00 dollars and that raw figure. The minimum deposit itself is acceptable — the floor is a "no less than 25.00" rule, so a raw figure equal to 25.00 passes unchanged.

The **promised turnaround**, stored in `turnaround_days`, is an integer count of days. Begin from a base turnaround of 14 days. If `rush_requested` is true, replace the base with the base divided by two and rounded up to a whole number (so 14 becomes 7). If the order has a fragile line, add a further 5 fragile-handling days to the running figure. The result is the promised turnaround.

Quoting also recomputes `has_fragile_line` over the current line set, recomputes `balance_due` (which at this stage equals `estimate_total` minus `amount_paid`), and — if the order's `payment_status` is still `UNBILLED` — advances `payment_status` to `DEPOSIT_DUE`, opening the order for its deposit.

A quoted order is not yet locked. A `FrameDesigner` may **reopen** a quoted order back to `INTAKE` for revision, which is allowed only while `payment_status` is `UNBILLED` or `DEPOSIT_DUE` — that is, while no deposit has yet been paid. Once a deposit has been collected, reopening is rejected with `ERR_DEPOSIT_ALREADY_PAID`. Reopening returns the order to the editable `INTAKE` state so that lines may again be added or measured, and increments the order's `version`. This intake-to-quote revision loop may repeat until a deposit is taken.

### 3.5. The Order Ledger: Payments, Balance, and the Payment Dimension

An order's payment dimension, `payment_status`, runs independently of its production dimension and takes one of `UNBILLED`, `DEPOSIT_DUE`, `DEPOSIT_PAID`, `PAID_IN_FULL`, or `REFUNDED`. A new order is `UNBILLED`; quoting moves it to `DEPOSIT_DUE` as described above.

All money on an order is reconciled through a ledger over its payments. A **payment** is applied by a `FrontDeskClerk` against an order and carries a `kind` of `DEPOSIT`, `BALANCE`, or `REFUND` and a positive `amount` in dollars (a refund's `amount` is also positive; the direction is carried by `kind`). Each payment has a `payment_status` of `APPLIED` or `VOID`, where a voided payment is excluded from the ledger. The order's `amount_paid` is computed by summing the `amount` of every applied `DEPOSIT` and `BALANCE` payment, subtracting the `amount` of every applied `REFUND` payment, and rounding the difference to two decimal places. The order's effective total is the `final_invoice_total` when it has been set to a positive value, and otherwise the `estimate_total`. The `balance_due` is that effective total minus `amount_paid`, rounded to two decimal places. The ledger is reconciled on every payment application, void, or refund, and also when the order is quoted and when it is marked ready, since those events change the effective total. Payments are replayed in `created_at` order.

A **deposit** payment advances `payment_status` from `DEPOSIT_DUE` to `DEPOSIT_PAID`. It is permitted only when the order's `production_status` is `QUOTED` — a deposit on an order that has not been quoted is rejected with `ERR_NOT_QUOTED` — and the deposit's `amount` must be at least the order's `deposit_required`; an amount below the required deposit is rejected with `ERR_DEPOSIT_TOO_LOW`. A successful deposit recomputes `amount_paid` and `balance_due` and emits a deposit-receipt notification to the customer.

A **balance** payment advances `payment_status` to `PAID_IN_FULL`, and is allowed from `DEPOSIT_PAID`, `DEPOSIT_DUE`, or even directly from a state where only the deposit has been recorded as due, provided the money clears. The rule is that after applying this payment the order's `amount_paid` must reach at least the effective total — the `final_invoice_total` if it has been set, otherwise the `estimate_total`. A balance payment that does not bring `amount_paid` up to the effective total is rejected with `ERR_PAYMENT_INSUFFICIENT`. This means a balance may be paid before the order is marked ready only if it covers the estimate total; otherwise it is paid after the final invoice total has been set. A successful balance payment recomputes `amount_paid` and `balance_due`.

### 3.6. Production: Scheduling Tasks on Workbenches

Production scheduling is the province of the `FrameProductionTech`, who first creates the **workbenches** the shop owns. A workbench carries a `bench_name` label, a `bench_type` of `ASSEMBLY` or `GLASS_CUTTING`, and a `clean_buffer_minutes` idle buffer that defaults to 0. The buffer is meaningful only on a glass-cutting bench, where it guards fragile pieces and freshly cut glass.

Before any production task can be scheduled, the order must be ready for it. An order moves from `QUOTED` to `IN_PRODUCTION` only when its `payment_status` is `DEPOSIT_PAID` or `PAID_IN_FULL` — a deposit (or full payment) must be in hand, or the start is rejected with `ERR_DEPOSIT_NOT_PAID` — and when every non-voided frame line has `line_status` of `MEASURED`, with any unmeasured non-voided line causing rejection with `ERR_LINES_NOT_MEASURED`. Starting production increments the order's `version`.

A **production task** reserves a workbench interval for an order. It is created with the `order_id` it builds, the `workbench_id` it reserves, and a half-open reservation interval given by `start_minute` and `end_minute`, both absolute integer minute offsets where `start_minute` is at least 0 and `end_minute` is strictly greater than `start_minute`. The interval is half-open, covering `start_minute` up to but not including `end_minute`. A new task starts in `task_status` of `SCHEDULED`. Scheduling runs two gating checks in order. First, fragile handling: if the order has a fragile line, the chosen workbench must be of type `GLASS_CUTTING`; choosing any other bench for a fragile order is rejected with `ERR_FRAGILE_REQUIRES_GLASS_BENCH`. Second, interval availability against the other `SCHEDULED` or `COMPLETED` tasks already on that same bench. On an assembly bench, the new half-open interval may not overlap any existing task's half-open interval on the bench. On a glass-cutting bench the rule is stricter: the gap between the new interval and every neighboring task on the bench must be at least the bench's `clean_buffer_minutes`, so two jobs that merely abut, or sit closer than the buffer, conflict. Either form of collision is rejected with `ERR_WORKBENCH_CONFLICT`.

A scheduled task is advanced to `COMPLETED` by the `FrameProductionTech`, which is permitted only while the owning order's `production_status` is `IN_PRODUCTION`; attempting completion otherwise is rejected with `ERR_ORDER_NOT_IN_PRODUCTION`. Completing a task does not itself cascade; it simply records the work as done.

### 3.7. Marking Ready, the Final Invoice, and Pickup

Once production is finished, the `FrameProductionTech` marks the order ready, advancing `production_status` from `IN_PRODUCTION` to `READY`. This is allowed only when every production task belonging to the order has `task_status` of `COMPLETED`; any incomplete task causes rejection with `ERR_TASKS_INCOMPLETE`. Marking ready computes the order's `final_invoice_total`, recomputes `balance_due` against that new total, emits a ready notification to the customer, and increments the order's `version`. The order's `payment_status` is unaffected by marking ready; if it was `DEPOSIT_PAID`, it remains `DEPOSIT_PAID` and the freshly computed balance is now owed.

The **final invoice total**, stored in `final_invoice_total`, is computed over the order's frame lines whose `line_status` is `MEASURED`, ordered by `created_at` ascending, using each line's measured `final_subtotal`. This computation uses the round-per-line-then-sum discipline, which differs from the estimate's discipline in two ways at once — it uses measured rather than nominal dimensions, and it allocates the loyalty discount per line rather than to the aggregate. For each measured line, multiply its `final_subtotal` by one minus the owning customer's `loyalty_discount_pct` and round that discounted line value to two decimal places; sum those per-line rounded values to obtain the discounted sum. If `rush_requested` is true, multiply the discounted sum by 1.15 and round to two decimal places to obtain the final invoice total; otherwise round the discounted sum to two decimal places. Because the discount is rounded into each line before summation, and because the measured dimensions differ from the nominal ones, the final invoice total can differ from the quote estimate even for an identical line configuration.

The terminal handoff is **pickup**, performed by a `FrontDeskClerk`, which advances `production_status` from `READY` to `PICKED_UP`. Pickup is permitted only when the order's `payment_status` is `PAID_IN_FULL`; an order with any outstanding balance is rejected with `ERR_BALANCE_OUTSTANDING`. Pickup is a terminal production state and triggers a cascade into the customer's reliability fields: the owning customer's `open_order_count` is recomputed because this order has left the open set, the customer's `no_show_risk_score` is recomputed because the projected open set has shrunk, an on-time outcome is appended to the customer's settled history and the customer's `settled_reputation_score` is recomputed by the chronological replay of Section 3.1, and the order's `version` is incremented. The chained recompute runs from the order through the customer's open-order count into the customer's no-show risk.

### 3.8. Cancellation, Refunds, and Reorder

An order may be **cancelled** by a `FrontDeskClerk` from any non-terminal production state — `INTAKE`, `QUOTED`, `IN_PRODUCTION`, or `READY` — with no further state precondition. Cancellation drives a fan-out of side effects. Every production task for the order that is `SCHEDULED` or `COMPLETED` is moved to `RELEASED`, which frees its half-open interval on the workbench so the bench becomes available again. If the order's `amount_paid` is greater than zero, the system creates an applied refund payment whose `kind` is `REFUND` and whose `amount` equals the current `amount_paid`, then recomputes `amount_paid` and `balance_due` from the ledger and sets the order's `payment_status` to `REFUNDED`. Cancellation also recomputes the owning customer's `open_order_count` and `no_show_risk_score` because the order has left the open set, appends an abandon outcome to the customer's settled history and recomputes the customer's `settled_reputation_score`, and increments the order's `version`. The refund branch is a chained ledger recompute: the system-created refund payment flows into the order's `amount_paid`, which flows into the order's `balance_due`.

A picked-up order can seed a fresh one through **reorder**, available to a `FrameDesigner` or `FrontDeskClerk`. Reorder clones a source order that is in `PICKED_UP` state into a brand-new order; a source order in any other state is rejected with `ERR_NOT_PICKED_UP`. The new order opens in `production_status` of `INTAKE` with its `reorder_of_order_id` set to the source order's id, and the source order's non-voided frame lines are copied as fresh `DRAFT` lines on the new order. The reorder accepts optional `rush_requested` and `deposit_pct` for the new order, defaulting as a normal intake would. Like opening any order, a reorder recomputes the owning customer's `open_order_count` and `no_show_risk_score` because a new open order has joined the set.

### 3.9. Notifications

The shop keeps an append-only trail of the messages it sends a customer about an order. A **notification** records the `order_id` it concerns, a `channel` of `EMAIL` or `SMS` chosen from the customer's contact details at send time, a `kind` of `READY` or `DEPOSIT_RECEIPT`, and a `sent_to` value — the email or phone copied from the customer at the moment of emission. A `DEPOSIT_RECEIPT` notification is emitted when a deposit payment is applied, and a `READY` notification is emitted when the order transitions into `READY`. Notifications are read-only to clients and are listed in `created_at` order; as noted in Section 2.4 they carry only `id` and `created_at` and no `version` or `updated_at`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a customer, a workbench, a framing order, a frame line, a production task, a payment, or a reorder clone — return a `201 Created` status code. Operations that modify an existing resource, including every state-transition action on an order, line, or task, return a `200 OK` status code. List and retrieval operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a Customer | FrontDeskClerk, FrameDesigner |
| GET | `/customers` | List Customers | FrontDeskClerk, FrameDesigner, FrameProductionTech |
| GET | `/customers/{customerId}` | Get a Customer (recomputed scores) | FrontDeskClerk, FrameDesigner, FrameProductionTech, Customer |
| GET | `/customers/{id}/framing-orders` | List a customer's FramingOrders | FrontDeskClerk, FrameDesigner, FrameProductionTech, Customer |
| POST | `/workbenches` | Create a Workbench | FrameProductionTech |
| GET | `/workbenches` | List Workbenches | FrameProductionTech, FrameDesigner, FrontDeskClerk |
| GET | `/workbenches/{workbenchId}` | Get a Workbench | FrameProductionTech, FrameDesigner, FrontDeskClerk |
| GET | `/workbenches/{id}/production-tasks` | List a workbench's ProductionTasks | FrameProductionTech, FrameDesigner, FrontDeskClerk |
| POST | `/framing-orders` | Create a FramingOrder (intake) | FrameDesigner, FrontDeskClerk |
| GET | `/framing-orders` | List FramingOrders (filterable) | FrameDesigner, FrontDeskClerk, FrameProductionTech |
| GET | `/framing-orders/{orderId}` | Get a FramingOrder (recomputed derived fields) | FrameDesigner, FrontDeskClerk, FrameProductionTech, Customer |
| POST | `/framing-orders/{orderId}/quote` | Quote the order | FrameDesigner |
| POST | `/framing-orders/{orderId}/reopen-intake` | Revert QUOTED to INTAKE | FrameDesigner |
| POST | `/framing-orders/{orderId}/start-production` | Start production | FrameProductionTech |
| POST | `/framing-orders/{orderId}/mark-ready` | Mark the order ready | FrameProductionTech |
| POST | `/framing-orders/{orderId}/pickup` | Pick up the order | FrontDeskClerk |
| POST | `/framing-orders/{orderId}/cancel` | Cancel the order | FrontDeskClerk |
| POST | `/framing-orders/{orderId}/reorder` | Clone a PICKED_UP order | FrameDesigner, FrontDeskClerk |
| POST | `/framing-orders/{orderId}/frame-lines` | Add a FrameLine (OCC-guarded) | FrameDesigner |
| GET | `/framing-orders/{id}/frame-lines` | List an order's FrameLines | FrameDesigner, FrontDeskClerk, FrameProductionTech, Customer |
| GET | `/frame-lines/{lineId}` | Get a FrameLine | FrameDesigner, FrontDeskClerk, FrameProductionTech, Customer |
| POST | `/frame-lines/{lineId}/measure` | Record measured dimensions | FrameDesigner |
| POST | `/frame-lines/{lineId}/void` | Void a DRAFT line | FrameDesigner |
| POST | `/production-tasks` | Schedule a ProductionTask | FrameProductionTech |
| GET | `/framing-orders/{id}/production-tasks` | List an order's ProductionTasks | FrameProductionTech, FrameDesigner, FrontDeskClerk, Customer |
| GET | `/production-tasks/{taskId}` | Get a ProductionTask | FrameProductionTech, FrameDesigner, FrontDeskClerk |
| POST | `/production-tasks/{taskId}/complete` | Mark a ProductionTask completed | FrameProductionTech |
| POST | `/framing-orders/{orderId}/payments` | Apply a Payment (DEPOSIT or BALANCE) | FrontDeskClerk |
| GET | `/framing-orders/{id}/payments` | List an order's Payments | FrontDeskClerk, FrameDesigner, Customer |
| GET | `/payments/{paymentId}` | Get a Payment | FrontDeskClerk, FrameDesigner, Customer |
| GET | `/framing-orders/{id}/notifications` | List an order's Notifications | FrontDeskClerk, FrameDesigner, FrameProductionTech, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_TASK_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_WORKBENCH_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DIMENSIONS` | 400 Bad Request |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_EDITABLE` | 409 Conflict |
| `ERR_NOT_QUOTED` | 409 Conflict |
| `ERR_ORDER_NOT_IN_PRODUCTION` | 409 Conflict |
| `ERR_DEPOSIT_ALREADY_PAID` | 409 Conflict |
| `ERR_DEPOSIT_NOT_PAID` | 409 Conflict |
| `ERR_NOT_PICKED_UP` | 409 Conflict |
| `ERR_NO_LINES` | 409 Conflict |
| `ERR_LINES_NOT_MEASURED` | 409 Conflict |
| `ERR_TASKS_INCOMPLETE` | 409 Conflict |
| `ERR_FRAGILE_REQUIRES_GLASS_BENCH` | 409 Conflict |
| `ERR_WORKBENCH_CONFLICT` | 409 Conflict |
| `ERR_DEPOSIT_TOO_LOW` | 402 Payment Required |
| `ERR_PAYMENT_INSUFFICIENT` | 402 Payment Required |
| `ERR_BALANCE_OUTSTANDING` | 402 Payment Required |

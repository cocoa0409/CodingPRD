# Bookstore API — Product Requirements Document

## 1. Introduction

This document specifies the Bookstore API, the operational backbone for an independent-style bookshop that blends a Barnes & Noble breadth of services with the high-touch operations of a neighborhood store. A single store runs many overlapping businesses at once: a catalog of titles and the physical copies that stock them, special orders sourced either through a distributor or printed on demand, returns of unsold stock to publishers for credit, ticketed author events and signings, a café and sideline merchandise line, a used-book buyback desk that pays out in store credit, a membership and loyalty program, and a consignment arrangement for local authors who shelve their own books.

The recurring challenge across all of these is that money, inventory, and customer credit must stay reconciled even as copies move between shelves, orders, returns, and events. A physical copy received from a distributor may later be reserved for a sales order, sold, or returned to its publisher; a copy taken in at the buyback desk re-enters the same shelf as fresh inventory; a consigned copy belongs to its author until it sells. Store credit is a ledger, loyalty points accrue against spending, and an author's payout depends on how many of their books have already sold. The API exists to make every one of these movements explicit, auditable, and consistent, so that the count of books on the shelf, the balance on a member's account, and the credit owed to a publisher always agree with the history of operations that produced them.

This API serves four operator personas — floor booksellers, inventory managers, store administrators — alongside the members who shop, attend events, sell back used books, and consign their own titles. The sections below define the global contract every endpoint obeys, the business rules that govern each workflow, and the complete endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API, with the two exceptions noted below, must be authenticated through a pair of mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the capacity in which they act. When either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The two endpoints that do not require authentication are member self-registration and the administrative clock-setting capability described in §3.

The system recognizes five roles, spelled exactly as follows: `Anonymous`, `Member`, `Bookseller`, `InventoryManager`, and `StoreAdmin`. Once a request is authenticated, the system checks whether the acting role is permitted to perform the requested operation per the authorization table in §4; if it is not, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The roles differ in how `X-User-ID` relates to stored data. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's owning member foreign key to `X-User-ID`. Concretely, a `Member` may only act on a sales order, event ticket, buyback transaction, or special order whose `member_id` equals their `X-User-ID`; a violation is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The same ownership scope also narrows list reads: when a `Member` lists a member-scoped collection (sales orders, order lines, special orders, buyback transactions, or event tickets), the response is silently filtered to only the rows owned by that `X-User-ID`, rather than rejected. The other four roles carry opaque identity. When `X-User-Role` is `Anonymous`, `Bookseller`, `InventoryManager`, or `StoreAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. `Anonymous` exists only to permit member self-registration. `Bookseller` runs the sales floor — inventory intake, special-order quoting and receiving, buyback intake, sales reservation and fulfillment, and event check-in. `InventoryManager` owns the publisher-return and consignment lifecycles. `StoreAdmin` is the operator superset and may perform any operation, including setting the clock and adjusting member credit.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system are top-level collections linked by foreign keys rather than nested under one another. Every persisted resource carries an `id`: a server-minted UUID with no type prefix, used for identity only. Clients never supply an `id`; the server mints it on creation.

Most resources additionally carry the standard system-managed timestamps and concurrency token:

- `created_at` — an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-01-01T00:00:00.000Z`) recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp, in the same format, recording when the resource was last modified. Any mutation to the resource refreshes this value.
- `version` — an integer that begins at its initial value on creation and increases by one with every mutation of the resource. This is the token used for optimistic concurrency control (§2.10).

One resource type is the exception. A `CreditLedgerEntry` is an immutable, append-only record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written it is never modified. Every other resource — `Title`, `StockItem`, `Member`, `SalesOrder`, `OrderLine`, `SpecialOrder`, `PublisherReturn`, `AuthorEvent`, `EventTicket`, `BuybackTransaction`, `BuybackLine`, `ConsignmentAgreement`, and `ConsignmentCopy` — carries the full `created_at`, `updated_at`, and `version` set.

Whenever the server recomputes a derived field on a resource (for example, refreshing a title's stock counts), that recomputation is a mutation of the affected resource: it refreshes `updated_at` and increments `version` on that resource, exactly as a direct edit would. A `Member`'s computed `store_credit_cents` and `loyalty_points` are the exception: they are recomputed read-side from the live ledger and award totals, so a change to a member's credit balance through ledger activity does not by itself refresh that member's `updated_at` or increment its `version` (the member's `version` advances only on a direct member mutation, such as suspension, or when a finalized loyalty award is posted at order fulfillment).

### 2.5. Nested Resource Retrieval and Existence Ordering

Although the topology is flat, several endpoints address a child through its owner's path (for example, the lines under a sales order, or the tickets under an author event). For any request whose path contains more than one resource identifier, the system validates each identifier in left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. The same rule governs foreign keys supplied in a request body: every path identifier and every referenced foreign key must resolve to an existing resource, validated left-to-right, before any business rule is evaluated. A request that names a line under a non-existent order, for instance, fails on the missing order before the line is ever considered.

The relative ordering of the universal checks is fixed and applies to every endpoint that performs them. Authentication is checked first (`ERR_UNAUTHENTICATED`, 401). Role permission is checked next (`ERR_FORBIDDEN`, 403). For a `Member` acting on a specific resource, resource ownership is checked next (`ERR_NOT_RESOURCE_OWNER`, 403). Existence of all path and foreign-key resources is checked next (`ERR_NOT_FOUND`, 404). Only then does the system check that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, 409). Domain-specific business validations follow, and last of all comes the generic body-shape check (`ERR_INVALID_REQUEST`, 400) for any required field that is missing, ill-typed, carries a `quantity` below 1, or supplies a bad enum value. Where a single operation is guarded by several domain validations, their relative precedence is stated alongside the workflow they guard in §3.

### 2.6. Monetary Values, Counts, and Rounding

All monetary amounts in the system are stored and exchanged as integer cents — fields whose names end in `_cents` are always whole-cent integers, never fractional. Any calculation that produces a fractional cent is rounded to a whole cent using the round-half-up convention (a value of exactly one-half cent rounds up to the next whole cent). Where a calculation specifies an order of operations — for example, rounding a per-copy figure before multiplying by a quantity — that order is binding, because rounding at a different step yields a different total. Each calculation in §3 states its own rounding points explicitly; the global rule is simply that every rounding step uses round-half-up to whole cents unless a step is explicitly an integer floor.

Counts such as `on_hand_qty`, `reserved_qty`, `tickets_sold`, `units_sold_to_date`, `quantity`, and `revision_count` are non-negative integers. Loyalty points are whole integers, computed with an integer floor as described in §3.

### 2.7. Inventory as the Single Source of Truth

Physical inventory is modeled as individual `StockItem` rows, one per physical copy. Each stock item records the `title_id` it stocks, its `source` (one of `DISTRIBUTOR`, `BUYBACK`, or `CONSIGNMENT`), its acquisition `cost_cents`, and its `state` (one of `AVAILABLE`, `RESERVED`, `SOLD`, or `RETURNED_TO_PUBLISHER`). While a copy is held for an order, its `reserved_order_line_id` points at the owning order line; otherwise that field is cleared. A copy that came in through consignment additionally carries a `consignment_copy_id` linking it to the `ConsignmentCopy` it backs; for all other copies that field is absent.

A title never stores its own stock counts as authored input. A `Title`'s `on_hand_qty` is always the live count of that title's stock items in `AVAILABLE` state, and its `reserved_qty` is the live count in `RESERVED` state. Whenever copies change state — through reservation, fulfillment, cancellation, buyback intake, special-order receipt, publisher return, or consignment movement — the affected title's `on_hand_qty` and `reserved_qty` are recomputed from the underlying stock items, and (per §2.4) that recomputation increments the title's `version` and refreshes its `updated_at`. The same one-to-many discipline applies to an order line: an `OrderLine`'s `reserved_qty` is the live count of stock items reserved against that line.

When copies must be selected to satisfy a reservation or a publisher return, the system always picks the oldest `AVAILABLE` copies first — that is, those with the earliest `created_at`.

### 2.8. The Store-Credit Ledger

Store credit is never edited in place. Each `Member` carries a computed `store_credit_cents` balance that is, at all times, the sum of the `delta_cents` of every `CreditLedgerEntry` belonging to that member. A ledger entry records the owning `member_id`, the signed `delta_cents` (positive when credit is issued, negative when it is redeemed), a `reason` (one of `BUYBACK`, `REDEMPTION`, `EVENT_REFUND`, or `ADJUSTMENT`), and a `ref_id` pointing at the entity that caused the entry (a buyback transaction, a sales order, or an event ticket). The ledger is the sole mutator of a member's balance: any operation that issues or consumes credit does so by appending a new entry and then recomputing the balance. A member's `store_credit_cents` is never allowed to be driven negative; the validations in §3 that guard credit redemption exist precisely to keep the balance from going below zero.

A `Member` also carries `loyalty_points`, a computed running total equal to the sum of finalized point awards minus redemptions. Points are awarded only when an order is finalized, as described in §3.

### 2.9. Loyalty Tier Effects

A member's `tier` is either `REGULAR` or `GOLD`. The tier has two pervasive effects that surface across several workflows: a `GOLD` member receives a five-percent discount on qualifying charges, and a `GOLD` member earns loyalty points at twice the base rate. These effects are applied at the specific points described in the sales-order pricing, ticket-pricing, and loyalty-points rules in §3; they are mentioned here so the reader expects the tier to matter wherever money or points are computed.

### 2.10. Optimistic Concurrency Control

Two operations in the system are guarded by optimistic concurrency control because they reserve scarce inventory off the back of a resource whose state a prior writer may already have advanced. Each such operation requires a version token in its request body that the client must set to the `version` of the parent resource it last observed.

Reserving inventory against a sales order requires the request body to carry `expected_sales_order_version`, set to the client's last-observed `version` of that `SalesOrder`. If another writer has advanced the order's `version` since the client read it — for instance by paying or reserving it, which pulls stock and bumps the version — the reserve is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a reservation state it has not actually observed.

Submitting a publisher return requires the request body to carry `expected_publisher_return_version`, set to the client's last-observed `version` of that `PublisherReturn`. If another writer has advanced the return's `version` since the client read it — for instance by already submitting it, which reserves the available copies and snapshots the credit — the submit is rejected with `ERR_STALE_VERSION` (HTTP 412).

These are the only two endpoints that take a version field. Every other mutating endpoint omits the version field entirely and performs no concurrency check.

## 3. Business Logic & Workflows

### 3.1. The Logical Clock

The system runs on a logical clock rather than wall-clock time, so that quoted lead times and event-timing checks are deterministic and testable. At startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it stays at that default — it never falls back to real-world time. A `StoreAdmin` may move the clock to any instant by supplying a `to_iso8601` timestamp through the administrative clock-setting capability; this resets the logical clock to the given instant. Every rule in this document that speaks of "the current clock" or a "promised arrival" reads this logical clock.

### 3.2. Members, Credit, and Loyalty Accounts

Anyone may register a member through self-registration, which is open to an `Anonymous` caller and also available to a `StoreAdmin`. Registration takes an `email` (recorded as supplied; the API does not enforce uniqueness across members, so a duplicate email is accepted rather than rejected) and a `full_name`, and optionally a `tier` and an `is_local_author` flag. When `tier` is omitted it defaults to `REGULAR`; when `is_local_author` is omitted it defaults to false. A newly registered member is created in `ACTIVE` status with `store_credit_cents` of zero and `loyalty_points` of zero. The `is_local_author` flag matters later: only a member for whom it is true may stand as the author on a consignment agreement.

Reading a member returns the live computed `store_credit_cents` and `loyalty_points`. A member's credit history is available as a paginated list of that member's `CreditLedgerEntry` rows. A `StoreAdmin` may directly adjust a member's balance by posting a credit adjustment carrying a signed `delta_cents`; this appends a `CreditLedgerEntry` with `reason` `ADJUSTMENT` (its `ref_id` is null, since no transaction caused it) and recomputes the member's `store_credit_cents`. This operation returns `201 Created` with the newly appended `CreditLedgerEntry` as its `data` object (not the member). A `StoreAdmin` may also suspend a member, moving `status` from `ACTIVE` to `SUSPENDED` and incrementing the member's `version`; suspension's practical effect is that a buyback can no longer be completed for that member, as described in §3.6.

### 3.3. The Catalog and Receiving Stock

A `Bookseller`, `InventoryManager`, or `StoreAdmin` builds the catalog by creating titles. A `Title` is created with an `isbn13`, a `name`, a `list_price_cents`, and optionally a `category`, a `returnable` flag, a `demand_flag`, and a `pod_eligible` flag. The `isbn13` must be exactly thirteen digits and must be unique across the catalog: a value that is not exactly thirteen digits is rejected as a malformed request, while a thirteen-digit value that duplicates an existing title is rejected with `ERR_DUPLICATE_ISBN` (HTTP 409). The `category` is one of `BOOK`, `CAFE`, or `SIDELINE` and defaults to `BOOK`, letting the same catalog hold books, café items, and sideline merchandise. The `list_price_cents` must be zero or greater. The `returnable` flag defaults to true and governs whether copies of this title may ever be returned to the publisher for credit. The `demand_flag` is one of `HIGH` or `NORMAL`, defaults to `NORMAL`, and drives both the buyback demand bonus and the event-ticket surcharge described later. The `pod_eligible` flag defaults to false and governs whether the title may be sourced through print-on-demand. Every new title starts in `ACTIVE` status with `on_hand_qty` and `reserved_qty` both at zero; the alternate status value a title may hold is `DISCONTINUED`.

A title's physical copies are received through stock intake. Receiving distributor stock for a title creates a requested `quantity` of new `StockItem` rows, each with `source` `DISTRIBUTOR` and `state` `AVAILABLE`, optionally stamped with a `cost_cents` acquisition cost (defaulting to zero when omitted), after which the title's `on_hand_qty` is recomputed; the operation returns `201 Created` with a single `StockItem` — the last of the rows it created — as its `data` object. Stock items can be listed for a title or across the store, filterable by `state`, and a single stock item may be read directly. The cross-store stock listing additionally accepts `title_id`, `reserved_order_line_id`, and `consignment_copy_id` filters so an operator can trace which copies back a particular line or consigned copy.

### 3.4. Sales Orders: The Two Independent Axes

A sales order tracks two completely independent lifecycles at once. The **payment axis**, `payment_status`, moves through `UNPAID`, `PAID`, and `REFUNDED`. The **fulfillment axis**, `fulfillment_status`, moves through `OPEN`, `RESERVED`, `FULFILLED`, and `CANCELLED`. The two axes evolve independently except where a rule explicitly bridges them.

A `Member` (acting on their own account), a `Bookseller`, or a `StoreAdmin` opens an order for a member by supplying that member's `member_id` and optionally a `credit_redeemed_cents` amount the member elects to apply at checkout (defaulting to zero). A fresh order is created with `payment_status` `UNPAID` and `fulfillment_status` `OPEN`. Lines are then added to an open, unpaid order by supplying a `title_id` and a `quantity` of at least one; adding a line snapshots `unit_price_cents` from the current `Title.list_price_cents`, sets `line_total_cents` to that unit price multiplied by the line's `quantity`, and refreshes the order's `subtotal_cents`. This `subtotal_cents` refresh refreshes the order's `updated_at` but does not increment the order's `version` (so the create-time version remains a valid `expected_sales_order_version` for a subsequent reserve); the new `OrderLine` itself is returned as the `201 Created` `data` object. Order lines can be listed under their order or across the store filtered by `title_id` and `order_id`, and a single `OrderLine` can be read directly; each line also exposes its `id`, its owning `order_id`, and its `reserved_qty`.

**Paying** an order moves `payment_status` from `UNPAID` to `PAID` and is performed by the owning `Member` or a `StoreAdmin`. Payment is allowed only when the order is `UNPAID`, has at least one order line, and the member holds enough credit to cover whatever they elected to redeem. An attempt to pay an order with zero lines is rejected with `ERR_EMPTY_TRANSACTION` (HTTP 422). If the `credit_redeemed_cents` the member elected exceeds the member's `store_credit_cents`, the payment is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 422). On a successful payment the system prices the order (the order-pricing calculation below), computes provisional loyalty points, and — only if `credit_redeemed_cents` is greater than zero — appends a `CreditLedgerEntry` with `reason` `REDEMPTION` and a `delta_cents` equal to the negative of the redeemed amount, then recomputes the member's `store_credit_cents`. The order's `version` increments.

The **order-pricing** calculation runs at payment. It first sets `subtotal_cents` to the sum, over every order line, of that line's `unit_price_cents` multiplied by its `quantity`. It then sets `member_discount_cents`: for a `GOLD` member this is five percent of the subtotal, rounded half-up to whole cents; for a `REGULAR` member it is zero. It then sets `net_paid_cents` to the subtotal minus the member discount minus `credit_redeemed_cents`, floored at zero so the net can never go below zero. The evaluation order is binding: subtotal first, then the discount taken from the subtotal, then the credit subtracted, then the floor at zero.

### 3.5. Reserving, Fulfilling, Cancelling, and Refunding Orders

**Reserving** an order moves `fulfillment_status` from `OPEN` to `RESERVED` and is performed by a `Bookseller` or `StoreAdmin`. This is one of the two optimistic-concurrency-guarded operations: the request must carry `expected_sales_order_version` matching the order's current `version`, failing which the reserve is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.10. Reservation is allowed only when the order is `OPEN` and only when, for every order line, the line's `Title.on_hand_qty` (its count of `AVAILABLE` copies) is at least the line's `quantity`; if any line cannot be covered the reserve is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 422). When these checks pass, the system flips, for each line, that line's `quantity` of stock items from `AVAILABLE` to `RESERVED`, choosing the oldest copies first and setting each flipped copy's `reserved_order_line_id` to the line; it then recomputes each affected `Title.on_hand_qty` and `reserved_qty` and each `OrderLine.reserved_qty`, and increments the order's `version`. The precedence among the reserve checks is fixed: the order must exist and resolve, then it must be `OPEN` (`ERR_INVALID_STATE`), then the version token must match (`ERR_STALE_VERSION`), then sufficient stock must exist (`ERR_INSUFFICIENT_STOCK`).

**Fulfilling** an order moves `fulfillment_status` from `RESERVED` to `FULFILLED` and is performed by a `Bookseller` or `StoreAdmin`. Fulfillment carries a cross-axis guard: it is allowed only when the order is `RESERVED` on the fulfillment axis and, simultaneously, `PAID` on the payment axis. When it proceeds, every `RESERVED` stock item on the order flips from `RESERVED` to `SOLD`. For any sold copy whose `source` is `CONSIGNMENT`, the system cascades into its backing `ConsignmentCopy`, transitioning that copy from `ON_SHELF` to `SOLD`, which computes the copy's `payout_cents` and bumps its agreement's `units_sold_to_date` and `total_payout_cents` (the consignment-payout calculation in §3.9). The system then finalizes loyalty points — computing the final points and adding them to the member's `loyalty_points` — and recomputes each affected `Title.on_hand_qty` and `reserved_qty`. The order's `version` increments.

The **loyalty-points** calculation has two variants that run at two different moments. At payment, the *provisional* variant estimates points from the order's `net_paid_cents` as it stands at pay time; the result is stored in `points_provisional` and is an estimate only — it is never added to the member's `loyalty_points`. At fulfillment, the *final* variant recomputes points from the order's `net_paid_cents` as it stands at fulfill time; the result is stored in `points_final` and is the awarded value that is added to the member's `loyalty_points`. Both variants compute identically: take `net_paid_cents`, divide by one hundred and take the integer floor to get base points, multiply by a tier multiplier of two for a `GOLD` member or one for a `REGULAR` member, and finally cap the result at a monthly ceiling of one thousand points (the smaller of the computed value and one thousand is used). The two variants can diverge whenever `net_paid_cents` differs between pay and fulfill — for example if a line changes between the two — which is exactly why `points_final`, not `points_provisional`, is the figure credited to the member.

**Cancelling** an order is performed by the owning `Member` or a `StoreAdmin` and is permitted from either `OPEN` or `RESERVED` on the fulfillment axis, moving it to `CANCELLED`. Cancelling an order that was merely `OPEN` simply sets `fulfillment_status` to `CANCELLED` and increments `version`, since no stock was held. Cancelling an order that was `RESERVED` additionally releases every `RESERVED` stock item on the order's lines back to `AVAILABLE`, clears each released copy's `reserved_order_line_id`, recomputes the affected titles' `on_hand_qty` and `reserved_qty`, and then increments `version`.

**Refunding** an order moves `payment_status` from `PAID` to `REFUNDED` and is performed by a `Bookseller` or `StoreAdmin`. It is permitted only when the order is `PAID` and has not yet been fulfilled (its `fulfillment_status` is anything other than `FULFILLED`). A refund does three things: if the order had redeemed credit (its `credit_redeemed_cents` is greater than zero) it appends a `CreditLedgerEntry` with `reason` `ADJUSTMENT` and a positive `delta_cents` equal to the redeemed amount, restoring that credit, and recomputes the member's `store_credit_cents`; it cascades onto the fulfillment axis by setting `fulfillment_status` to `CANCELLED`; and it releases every `RESERVED` stock item on the order's lines back to `AVAILABLE`. The order's `version` increments.

### 3.6. Used-Book Buyback

The buyback desk lets a member sell used books for store credit. A `Bookseller` or `StoreAdmin` opens a `BuybackTransaction` for a member by supplying that member's `member_id`; it starts in `PENDING`. Lines are added to a pending transaction by supplying a `title_id`, a `condition_grade` (one of `LIKE_NEW`, `GOOD`, or `FAIR`), and a `quantity` of at least one; each `BuybackLine` records its owning `buyback_id` and, once the offer runs, a computed `line_offer_cents`. Buyback lines can be listed under their transaction or across the store filtered by `title_id` and `buyback_id`, and a single `BuybackLine` can be read directly.

**Making the offer** moves the transaction from `PENDING` to `OFFERED` and computes `offer_total_cents`. The offer is allowed only when the transaction is `PENDING` and has at least one line; an offer attempt on a transaction with no lines is rejected with `ERR_EMPTY_TRANSACTION` (HTTP 422). The **buyback-offer** calculation works per line and then sums, with the rounding order pinned. For each line, the system forms a rate equal to a base rate of thirty hundredths plus, only when that line's title has `demand_flag` `HIGH`, a demand bonus of ten hundredths (so a high-demand title's rate is forty hundredths and a normal title's is thirty hundredths). It multiplies a grade multiplier into that rate: `LIKE_NEW` uses a multiplier of one, `GOOD` uses seventy hundredths, and `FAIR` uses forty hundredths. The per-copy offer for the line is the title's `list_price_cents` multiplied by the rate multiplied by the grade multiplier, rounded half-up to whole cents at this point. The line's `line_offer_cents` is that rounded per-copy offer multiplied by the line's `quantity`. The transaction's `offer_total_cents` is the sum of every line's `line_offer_cents`. The order is binding: round each per-copy offer first, then multiply by quantity, then sum across lines — summing raw amounts and rounding once at the end would yield a different total and is not used.

**Completing** the buyback moves it from `OFFERED` to `COMPLETED` and is allowed only when the transaction is `OFFERED` and the selling member is still `ACTIVE`; a completion attempt for a `SUSPENDED` member is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 422). On completion, for each line the system creates one `StockItem` per unit of `quantity` for that line's title, each with `source` `BUYBACK`, `state` `AVAILABLE`, and a `cost_cents` equal to the line's offer divided by its quantity; it appends a single `CreditLedgerEntry` with `reason` `BUYBACK` and a positive `delta_cents` equal to the transaction's `offer_total_cents` and recomputes the member's `store_credit_cents`; it recomputes the affected titles' `on_hand_qty`; and it increments the transaction's `version`. A buyback may instead be **voided** from either `PENDING` or `OFFERED`, moving it to `VOIDED` and incrementing `version` with no other effect.

### 3.7. Special Orders and Print-on-Demand

A special order sources a title the store does not have on the shelf, either through a distributor or through print-on-demand. A `Member` (on their own behalf), a `Bookseller`, or a `StoreAdmin` creates a `SpecialOrder` by supplying a `member_id`, a `title_id`, a `quantity` of at least one, and a `fulfillment_method` of either `DISTRIBUTOR` or `POD`; it starts in `DRAFT` with `revision_count` zero. A special order moves through `DRAFT`, `QUOTED`, `CONFIRMED`, and `RECEIVED`, and may be `CANCELLED`. Special orders can be listed filtered by `member_id` and `title_id`, and a single one can be read directly.

**Quoting** a draft is performed by a `Bookseller` or `StoreAdmin` and moves it from `DRAFT` to `QUOTED`, computing `quoted_unit_cents` and `promised_eta`. A quote is allowed only when the order is `DRAFT`; additionally, when the `fulfillment_method` is `POD`, the title must be print-on-demand eligible (its `pod_eligible` is true), failing which the quote is rejected with `ERR_TITLE_NOT_POD_ELIGIBLE` (HTTP 422). The **special-order-quote** calculation has two variants by method. For a `DISTRIBUTOR` order, `quoted_unit_cents` is the title's `list_price_cents` taken at list (multiplied by one), rounded half-up to whole cents, and `promised_eta` is the current logical clock plus seven days. For a `POD` order, `quoted_unit_cents` is the title's `list_price_cents` multiplied by a print-on-demand markup of one and twenty hundredths, rounded half-up to whole cents, and `promised_eta` is the current logical clock plus three days.

**Revising** a quote is a renegotiation loop performed by the owning `Member` or a `StoreAdmin`: it bounces the order from `QUOTED` back to `DRAFT`. A revision is allowed only when the order is `QUOTED` and only while its `revision_count` is below three; a revision attempt once the count has reached three is rejected with `ERR_REVISION_LIMIT` (HTTP 422). On a successful revision the system clears `quoted_unit_cents` and `promised_eta`, increments `revision_count` by one, and increments `version`.

**Confirming** a quote, performed by the owning `Member` or a `StoreAdmin`, moves it from `QUOTED` to `CONFIRMED` and increments `version`. **Receiving** a confirmed order, performed by a `Bookseller` or `StoreAdmin`, moves it from `CONFIRMED` to `RECEIVED`: it creates the order's `quantity` of new `StockItem` rows for the title in `AVAILABLE` state with `source` `DISTRIBUTOR` and `cost_cents` equal to `quoted_unit_cents`, recomputes the title's `on_hand_qty`, and increments `version`. A special order may instead be **cancelled** from `DRAFT` or `QUOTED`, moving it to `CANCELLED` and incrementing `version`.

### 3.8. Returns to Publisher

When unsold stock is to be sent back to its publisher for credit, an `InventoryManager` or `StoreAdmin` drives a publisher return through a guarded branch. A `PublisherReturn` is created with a `title_id` and a `quantity` of at least one, starting in `DRAFT`. The lifecycle runs `DRAFT`, then `SUBMITTED`, then a branch into either `ACCEPTED` or `REJECTED`. Publisher returns can be listed filtered by `title_id` and read directly.

**Submitting** a return moves it from `DRAFT` to `SUBMITTED` and is the second optimistic-concurrency-guarded operation: the request must carry `expected_publisher_return_version` matching the return's current `version`, failing which it is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.10. A submit is allowed only when the return is `DRAFT`, only when the title is returnable (its `returnable` is true), and only when the title has at least `quantity` copies `AVAILABLE`. A return submitted against a non-returnable title is rejected with `ERR_TITLE_NOT_RETURNABLE` (HTTP 422); a return whose quantity exceeds the title's `on_hand_qty` is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 422). The precedence among the submit checks is fixed: the return must exist and resolve, then be `DRAFT` (`ERR_INVALID_STATE`), then the version token must match (`ERR_STALE_VERSION`), then the title must be returnable (`ERR_TITLE_NOT_RETURNABLE`), then enough copies must be available (`ERR_INSUFFICIENT_STOCK`). On a successful submit the system snapshots `credit_unit_cents` and `credit_total_cents` (the return-credit calculation below), reserves the return's `quantity` of `AVAILABLE` copies by flipping the oldest first to `RESERVED` while leaving their `reserved_order_line_id` null, recomputes the title's `on_hand_qty` and `reserved_qty`, and increments `version`.

The **return-credit** calculation snapshots the per-copy credit as the title's `list_price_cents` multiplied by a publisher credit rate of fifty hundredths, rounded half-up to whole cents, stored in `credit_unit_cents`; the `credit_total_cents` is that per-unit credit multiplied by the return's `quantity`. This credit is only a snapshot at submission — it is realized only if the publisher accepts.

**Accepting** a submitted return moves it from `SUBMITTED` to `ACCEPTED`: the return's reserved copies leave inventory permanently, flipping from `RESERVED` to `RETURNED_TO_PUBLISHER`, after which the title's `reserved_qty` is recomputed and `version` increments; the previously snapshotted `credit_total_cents` stands as realized. **Rejecting** a submitted return moves it from `SUBMITTED` to `REJECTED` as the compensating branch: the return's reserved copies are released back to `AVAILABLE`, the `credit_total_cents` is zeroed out because no credit is realized on rejection, the title's `on_hand_qty` and `reserved_qty` are recomputed, and `version` increments. Both branches require the return to be `SUBMITTED`.

### 3.9. Local-Author Consignment

A consignment arrangement lets a local author shelve their own titles and be paid a share of each sale. An `InventoryManager` or `StoreAdmin` creates a `ConsignmentAgreement` by supplying an `author_member_id` and a `title_id`; the agreement starts `ACTIVE` with `units_sold_to_date` and `total_payout_cents` at zero. The named author must be a member whose `is_local_author` is true; otherwise creation is rejected with `ERR_NOT_LOCAL_AUTHOR` (HTTP 422). Agreements can be listed filtered by `author_member_id` and `title_id` and read directly with their live counters.

Copies are shelved against an active agreement by an `InventoryManager` or `StoreAdmin`, who supplies a `sale_price_cents` shelf price for the copy. Shelving creates a `ConsignmentCopy`, whose `agreement_id` records its owning agreement, in `ON_SHELF` state and, behind it, a backing `StockItem` with `source` `CONSIGNMENT` and `state` `AVAILABLE` linked to the copy through `consignment_copy_id`, then recomputes the title's `on_hand_qty`. A consigned copy moves through `ON_SHELF`, `SOLD`, and `RETURNED_TO_AUTHOR`, and carries a computed `payout_cents` realized when it sells. Copies can be listed under their agreement filtered by `state`.

A consigned copy is marked sold in one of two ways: as a cascade when a sales order that reserved its backing stock item is fulfilled (§3.5), or directly by a `Bookseller` or `StoreAdmin` marking an on-shelf copy sold. Either path moves the copy from `ON_SHELF` to `SOLD`, computes its `payout_cents`, flips the backing stock item to `SOLD`, bumps the agreement's `units_sold_to_date` and `total_payout_cents`, and recomputes the title's `on_hand_qty`. The **consignment-payout** calculation selects a commission tier from the agreement's `units_sold_to_date` measured *before* the selling copy is counted: when fewer than ten units have sold the commission rate is forty hundredths, when at least ten but fewer than twenty-five units have sold it is thirty-five hundredths, and at twenty-five or more it is thirty hundredths. The copy's `payout_cents` is its `sale_price_cents` multiplied by one minus the selected commission rate, rounded half-up to whole cents. The boundary is exact: the tenth unit to sell (nine sold before it) still earns the forty-hundredths tier, and the eleventh unit (ten sold before it) earns the thirty-five-hundredths tier.

**Terminating** an agreement is performed by an `InventoryManager` or `StoreAdmin` and is allowed only when the agreement is `ACTIVE`, moving it to `TERMINATED`. Termination returns every `ON_SHELF` copy to its author by cascading each from `ON_SHELF` to `RETURNED_TO_AUTHOR`; for any backing stock item still `AVAILABLE` it removes that copy from inventory by flipping it to `RETURNED_TO_PUBLISHER`. The title's `on_hand_qty` is then recomputed and the agreement's `version` increments. A terminated agreement accepts no new copies and no new sales.

### 3.10. Author Events and Ticketing

An author event is a capacity-limited ticketed signing. A `Bookseller` or `StoreAdmin` schedules an `AuthorEvent` for a featured title by supplying a `title_id`, a `name`, a `starts_at` start timestamp, a `capacity` of at least one seat, and a `base_price_cents` base ticket price. The event starts `SCHEDULED` with `tickets_sold` at zero; its alternate state is `CANCELLED`. Events can be listed filtered by `title_id` and read directly with their live `tickets_sold`, which is always the count of that event's tickets currently in `BOOKED` state — a ticket that has been refunded or checked in no longer counts toward `tickets_sold`.

**Booking a ticket** for a member creates a `BOOKED` `EventTicket` and is performed by the booking `Member`, a `Bookseller`, or a `StoreAdmin`; the request supplies the holder's `member_id`. Two business checks guard booking. First, the event must lie in the future: its `starts_at` must be strictly after the current logical clock, and a booking on an event that does not start strictly after now is rejected with `ERR_EVENT_PAST` (HTTP 422). Second, a seat must be available: the event's `tickets_sold` must be below its `capacity`, and a booking once sold-out is rejected with `ERR_EVENT_SOLD_OUT` (HTTP 422). On a successful booking the system computes the ticket's `price_paid_cents` (the ticket-price calculation below) and recomputes the event's `tickets_sold`. Tickets can be listed for an event or across the store filtered by `member_id` and `event_id`, and a single `EventTicket` can be read directly.

The **ticket-price** calculation runs at booking with its evaluation order pinned. It first forms a surcharge: when the featured title's `demand_flag` is `HIGH`, the surcharge is the event's `base_price_cents` multiplied by a high-demand surcharge of twenty-five hundredths, rounded half-up to whole cents; otherwise the surcharge is zero. The gross price is the `base_price_cents` plus that surcharge. It then forms a discount: for a `GOLD` member the discount is the gross multiplied by five hundredths, rounded half-up to whole cents; for a `REGULAR` member it is zero. The ticket's `price_paid_cents` is the gross minus the discount, floored at zero. The order is binding: surcharge from the base, add to get gross, discount from the gross, subtract.

A booked ticket has two fates. **Checking in** at the event, performed by a `Bookseller` or `StoreAdmin`, moves a ticket from `BOOKED` to `CHECKED_IN`; a cross-entity guard requires the event to still be `SCHEDULED`, so a ticket cannot be checked into a cancelled event. **Refunding** a ticket, performed by the holding `Member` or a `StoreAdmin`, moves it from `BOOKED` to `REFUNDED`: it appends a `CreditLedgerEntry` with `reason` `EVENT_REFUND` and a positive `delta_cents` equal to the ticket's `price_paid_cents`, recomputes the holder's `store_credit_cents`, recomputes the event's `tickets_sold`, and increments `version`.

**Cancelling** the whole event, performed by a `Bookseller` or `StoreAdmin`, moves it from `SCHEDULED` to `CANCELLED` and cascades a refund to every still-booked seat: each `BOOKED` ticket transitions to `REFUNDED`, each appending a `CreditLedgerEntry` with `reason` `EVENT_REFUND` and a positive `delta_cents` equal to that ticket's `price_paid_cents` to its holder and recomputing that holder's `store_credit_cents`. The event's `tickets_sold` is then recomputed and its `version` increments.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new distinct resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including all state transitions — return a `200 OK` status code. The administrative clock-setting capability also returns `200 OK`. The complete request and response shapes for each operation are determined by the workflow narratives in §3; the table below lists only the method, path, purpose, and the roles authorized to call it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreAdmin |
| POST | `/members` | Register a member | Anonymous, StoreAdmin |
| GET | `/members/{id}` | Read a member with computed credit and points | Member, Bookseller, InventoryManager, StoreAdmin |
| GET | `/members/{id}/credit-ledger` | List a member's credit-ledger entries | Member, Bookseller, InventoryManager, StoreAdmin |
| POST | `/members/{id}/credit-adjustments` | Adjust a member's store credit | StoreAdmin |
| POST | `/members/{id}/suspend` | Suspend a member | StoreAdmin |
| POST | `/titles` | Create a catalog title | Bookseller, InventoryManager, StoreAdmin |
| GET | `/titles/{id}` | Read a title with computed stock counts | Member, Bookseller, InventoryManager, StoreAdmin |
| GET | `/titles` | List titles | Member, Bookseller, InventoryManager, StoreAdmin |
| POST | `/titles/{id}/stock-items` | Receive distributor stock for a title | Bookseller, InventoryManager, StoreAdmin |
| GET | `/titles/{id}/stock-items` | List stock items for a title | Member, Bookseller, InventoryManager, StoreAdmin |
| GET | `/stock-items/{id}` | Read a single stock item | Bookseller, InventoryManager, StoreAdmin |
| GET | `/stock-items` | List stock items across the store | Bookseller, InventoryManager, StoreAdmin |
| POST | `/sales-orders` | Create an open, unpaid sales order | Member, Bookseller, StoreAdmin |
| GET | `/sales-orders/{id}` | Read a sales order with pricing and points | Member, Bookseller, StoreAdmin |
| GET | `/sales-orders` | List sales orders | Member, Bookseller, StoreAdmin |
| POST | `/sales-orders/{id}/lines` | Add a line to an open, unpaid order | Member, Bookseller, StoreAdmin |
| GET | `/sales-orders/{id}/lines` | List a sales order's lines | Member, Bookseller, StoreAdmin |
| GET | `/order-lines/{id}` | Read a single order line | Member, Bookseller, StoreAdmin |
| GET | `/order-lines` | List order lines across the store | Member, Bookseller, StoreAdmin |
| POST | `/sales-orders/{id}/pay` | Pay an order, price it, redeem credit | Member, StoreAdmin |
| POST | `/sales-orders/{id}/reserve` | Reserve inventory for an open order (OCC-guarded) | Bookseller, StoreAdmin |
| POST | `/sales-orders/{id}/fulfill` | Fulfill a reserved, paid order | Bookseller, StoreAdmin |
| POST | `/sales-orders/{id}/cancel` | Cancel an open or reserved order | Member, StoreAdmin |
| POST | `/sales-orders/{id}/refund` | Refund a paid, not-yet-fulfilled order | Bookseller, StoreAdmin |
| POST | `/special-orders` | Create a draft special order | Member, Bookseller, StoreAdmin |
| GET | `/special-orders/{id}` | Read a special order | Member, Bookseller, StoreAdmin |
| GET | `/special-orders` | List special orders | Member, Bookseller, StoreAdmin |
| POST | `/special-orders/{id}/quote` | Quote a draft special order | Bookseller, StoreAdmin |
| POST | `/special-orders/{id}/revise` | Bounce a quoted order back to draft | Member, StoreAdmin |
| POST | `/special-orders/{id}/confirm` | Confirm a quoted order | Member, StoreAdmin |
| POST | `/special-orders/{id}/receive` | Receive a confirmed order's stock | Bookseller, StoreAdmin |
| POST | `/special-orders/{id}/cancel` | Cancel a draft or quoted special order | Member, StoreAdmin |
| POST | `/publisher-returns` | Create a draft publisher return | InventoryManager, StoreAdmin |
| GET | `/publisher-returns/{id}` | Read a publisher return | InventoryManager, StoreAdmin |
| GET | `/publisher-returns` | List publisher returns | InventoryManager, StoreAdmin |
| POST | `/publisher-returns/{id}/submit` | Submit a return (OCC-guarded) | InventoryManager, StoreAdmin |
| POST | `/publisher-returns/{id}/accept` | Accept a submitted return | InventoryManager, StoreAdmin |
| POST | `/publisher-returns/{id}/reject` | Reject a submitted return | InventoryManager, StoreAdmin |
| POST | `/buybacks` | Create a pending buyback transaction | Bookseller, StoreAdmin |
| GET | `/buybacks/{id}` | Read a buyback transaction | Member, Bookseller, StoreAdmin |
| GET | `/buybacks` | List buyback transactions | Member, Bookseller, StoreAdmin |
| POST | `/buybacks/{id}/lines` | Add a line to a pending buyback | Bookseller, StoreAdmin |
| GET | `/buybacks/{id}/lines` | List a buyback's lines | Member, Bookseller, StoreAdmin |
| GET | `/buyback-lines/{id}` | Read a single buyback line | Bookseller, StoreAdmin |
| GET | `/buyback-lines` | List buyback lines across the store | Bookseller, StoreAdmin |
| POST | `/buybacks/{id}/offer` | Compute the buyback offer | Bookseller, StoreAdmin |
| POST | `/buybacks/{id}/complete` | Complete a buyback, issue store credit | Bookseller, StoreAdmin |
| POST | `/buybacks/{id}/void` | Void a pending or offered buyback | Bookseller, StoreAdmin |
| POST | `/author-events` | Schedule an author event | Bookseller, StoreAdmin |
| GET | `/author-events/{id}` | Read an author event with computed tickets sold | Member, Bookseller, StoreAdmin |
| GET | `/author-events` | List author events | Member, Bookseller, StoreAdmin |
| POST | `/author-events/{id}/tickets` | Book a ticket for a member | Member, Bookseller, StoreAdmin |
| GET | `/author-events/{id}/tickets` | List an event's tickets | Bookseller, StoreAdmin |
| GET | `/event-tickets/{id}` | Read a single event ticket | Member, Bookseller, StoreAdmin |
| GET | `/event-tickets` | List event tickets across the store | Member, Bookseller, StoreAdmin |
| POST | `/event-tickets/{id}/check-in` | Check a booked ticket in | Bookseller, StoreAdmin |
| POST | `/event-tickets/{id}/refund` | Refund a booked ticket to store credit | Member, StoreAdmin |
| POST | `/author-events/{id}/cancel` | Cancel an event, refund booked tickets | Bookseller, StoreAdmin |
| POST | `/consignment-agreements` | Create a consignment agreement | InventoryManager, StoreAdmin |
| GET | `/consignment-agreements/{id}` | Read a consignment agreement | Member, InventoryManager, StoreAdmin |
| GET | `/consignment-agreements` | List consignment agreements | Member, InventoryManager, StoreAdmin |
| POST | `/consignment-agreements/{id}/copies` | Shelve a consigned copy | InventoryManager, StoreAdmin |
| GET | `/consignment-agreements/{id}/copies` | List an agreement's copies | Member, InventoryManager, StoreAdmin |
| POST | `/consignment-copies/{id}/mark-sold` | Mark an on-shelf consigned copy sold | Bookseller, StoreAdmin |
| POST | `/consignment-agreements/{id}/terminate` | Terminate an agreement | InventoryManager, StoreAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_ISBN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NOT_LOCAL_AUTHOR` | 422 |
| `ERR_TITLE_NOT_RETURNABLE` | 422 |
| `ERR_TITLE_NOT_POD_ELIGIBLE` | 422 |
| `ERR_REVISION_LIMIT` | 422 |
| `ERR_EVENT_PAST` | 422 |
| `ERR_INSUFFICIENT_STOCK` | 422 |
| `ERR_EVENT_SOLD_OUT` | 422 |
| `ERR_INSUFFICIENT_CREDIT` | 422 |
| `ERR_EMPTY_TRANSACTION` | 422 |
| `ERR_MEMBER_SUSPENDED` | 422 |
| `ERR_INVALID_REQUEST` | 400 |

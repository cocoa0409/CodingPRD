# Packaging & Shipping Supply Distribution API — Product Requirements Document

## 1. Introduction

Distributors of packaging and shipping supplies operate on thin margins and fast promises: a buyer who orders corrugated boxes, mailers, tape, and labels before a warehouse's daily cutoff expects the cartons on a truck the same day, sourced from whichever facility is closest to the destination zone. This document specifies an API for such a distribution platform — a broad catalog with quantity-break pricing and pallet incentives, multi-warehouse sourcing driven by parcel zone distance, custom-print production with press scheduling and over/under ship tolerances, freight-class rating with oversize surcharges, corporate accounts governed by purchase-order approval chains and credit limits, back-in-stock notifications, and a returns flow that treats stock cartons and made-to-order printed goods very differently.

The platform is exposed as a single REST API mounted under `/packaging-distribution`. It serves platform operators, catalog managers, buyers, corporate approvers, distribution-center staff, and customer-service agents. Because pricing windows, same-day cutoffs, lead-time projections, press occupancy, and the thirty-day return window all depend on the current time, the system evaluates every temporal rule against a server-held **logical clock** rather than wall-clock time, so that behavior is deterministic and testable. All monetary amounts are carried as integer cents, and every calculation in this document is pinned to an exact rounding policy so that two independent implementations agree to the cent.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelopes, pagination, resource anatomy, timekeeping, rounding, concurrency, and the order in which validations fire.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The declared role names are `Anonymous`, `PlatformAdmin`, `CatalogManager`, `Buyer`, `AccountApprover`, `WarehouseOps`, and `CustomerService`. A request with missing headers, or with a role that is not one of these declared names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403). `Anonymous` is an unauthenticated stand-in admitted by no endpoint: every operation requires one of the six authenticated roles.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an account (an order's `account_id`, a return's owning order, a subscription's `account_id`) compare that foreign-key field to `X-User-ID`, and a `Buyer` touching another account's resource is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `AccountApprover`, `X-User-ID` is likewise the `id` of the acting `Account`, and the same ownership comparison applies; the approver is segregated from the submitting buyer within a corporate account. When `X-User-Role` is `PlatformAdmin`, `CatalogManager`, `WarehouseOps`, or `CustomerService` — and likewise for the unauthenticated `Anonymous` stand-in — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The ownership comparison fires at the first point the owning account id is known: when the account id is itself the addressed resource or is carried in the request body, the check precedes any fetch; for a resource reached through an owning parent (an order, a return, a subscription), the parent is resolved first, so a missing parent surfaces `ERR_NOT_FOUND` before the ownership check can apply. On list endpoints, an entity-backed caller's view is silently scoped to their own account — orders, order lines, returns, return lines, and restock subscriptions belonging to other accounts are excluded from the listing rather than rejected.

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
- Requests to undefined paths, or to defined paths with an unsupported method, are likewise rejected in this envelope with `ERR_NOT_FOUND` (HTTP 404).

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, with ties on the timestamp broken by insertion order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; `total_count` is the full count of matching resources before pagination, and `has_more` is true exactly when `offset` plus the number of returned items is still below `total_count`. Filter parameters that name an enumerated value (`status`, `account_type`, `category`, `is_custom_print`) reject an unrecognized value with `ERR_INVALID_REQUEST`; identifier-valued filters match literally.

### 2.4. Common Resource Properties

Every primary resource — accounts, products, warehouses, inventory rows, orders, order lines, custom print jobs, returns, return lines, and restock notifications — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation of the resource, and underpins optimistic concurrency control where it applies.

Quantity breaks are the single exception: a quantity break carries only `id` and `created_at`; both `updated_at` and `version` are absent. Separately, note that on an order, a refresh of derived totals caused by adding or editing a line while the order is still a draft is not a mutation of the order itself — only lifecycle transitions increment the order's `version`.

### 2.5. The Logical Clock and Business Days

All time-dependent behavior — price-window membership, same-day cutoffs, lead-time projection, press occupancy, the return window — is evaluated against a server-held logical clock. At startup the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `PlatformAdmin`-only, test-driving capability advances the clock to a supplied `to_iso8601` instant and echoes the new reading as `current_utc` — whole-second readings rendered to seconds precision, fractional readings with three fractional digits; it mutates no entity. Throughout this document, a "business day" skips Saturdays and Sundays, and "N business days after a date" counts that date itself as day zero.

### 2.6. Money, Integer Cents, and Rounding Order

All monetary values are integer cents. Rounding policy is pinned per calculation and always applied per unit or per line **before** any summation; grand totals are then exact integer addition with no second rounding pass. The custom-print surcharge rounds up to the next cent per unit; the pallet rebate rounds down to the whole cent per pallet; return credits round half-up per line and are summed only after that per-line rounding. Freight estimates are computed with exact decimal or rational arithmetic — rates held as cents per pound, the zone factor as an exact ratio, the provisional uplift as the exact fraction eleven-tenths — and a single ceiling is applied once to the exact final product, with no intermediate floating-point rounding.

### 2.7. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and no other endpoint accepts a version field. The full catalog update of a product requires the client to send `expected_product_version` carrying the version of the product record it last observed; if the product's current `version` has advanced since that read — for example because another catalog change altered pricing or pallet configuration — the update is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently discarding the newer state. The cycle-count adjustment of an inventory row likewise requires `expected_inventory_version`; because another writer may have just received stock or a reservation may have moved the reserved quantity, a mismatch with the row's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) instead of applying the delta to a stale baseline. On both endpoints the expected-version field is itself validated first — a missing or non-integer value is `ERR_INVALID_REQUEST` — and the staleness comparison then fires ahead of the remaining field-level validation, with one nuance on the cycle-count adjustment: the presence and integer type of `delta_qty` are validated before the staleness comparison, while the floor rule (the resulting on-hand quantity must stay at or above the reserved quantity) is checked only after it.

### 2.8. Nested Resource Retrieval

Requests that address nested resources are validated strictly left to right along the path. For example, a request to a path such as `/packaging-distribution/orders/{id}/lines/{lineId}` first confirms that the `id` segment identifies an existing order and only then resolves `lineId` within it; the request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first path segment that does not correspond to an existing resource. The same left-to-right existence rule applies to resources referenced in request bodies — accounts, products, warehouses, orders, lines, jobs, and returns must all exist before any business rule is evaluated.

### 2.9. Validation Order

When several checks apply to the same request, the system evaluates them in a fixed global order, and the earliest failing check is the one the caller sees. First come authentication (`ERR_UNAUTHENTICATED`) and authorization (`ERR_UNAUTHORIZED`). Next, all referenced resources must exist, validated left to right (`ERR_NOT_FOUND`). Next, the requested transition must exist from the target resource's current state, including terminal-state lockdown (`ERR_INVALID_STATE`). Only then do the domain rules fire, in this relative order: suspended-account gating (`ERR_ACCOUNT_SUSPENDED`), empty-order gating (`ERR_ORDER_EMPTY`), purchase-order presence (`ERR_PO_REQUIRED`), purchase-order uniqueness (`ERR_DUPLICATE_PO`), the credit check (`ERR_CREDIT_LIMIT_EXCEEDED`), case-quantity multiples (`ERR_CASE_QTY_MISMATCH`), custom-print artwork and tolerance (`ERR_ARTWORK_REQUIRED`), duplicate restock subscriptions (`ERR_DUPLICATE_SUBSCRIPTION`), overlapping price windows (`ERR_OVERLAPPING_PRICE_WINDOW`), warehouse sourcing capability (`ERR_NO_WAREHOUSE_CAPABLE`), uncovered non-backorderable lines (`ERR_BACKORDER_NOT_ALLOWED`), press occupancy (`ERR_PRESS_OCCUPIED`), the return window (`ERR_RETURN_WINDOW_EXPIRED`), return-line order matching (`ERR_RETURN_LINE_MISMATCH`), custom-versus-stock return eligibility (`ERR_CUSTOM_NOT_RETURNABLE`), custom production already started (`ERR_CUSTOM_PRODUCTION_STARTED`), and return quantity limits (`ERR_RETURN_QTY_EXCEEDED`). Malformed payloads — missing required fields, wrong types, enum violations, out-of-range numbers — surface as `ERR_INVALID_REQUEST` (HTTP 400); each field's well-formedness is checked at the point the endpoint first consumes that field rather than in a strictly final pass, so a malformed field can surface ahead of a later-listed domain rule — or, on action endpoints that validate their payload before the transition guard, ahead of the state check — while the relative order among the domain rules above is preserved as listed.

### 2.10. Freight Classification Reference

Every order line is assigned an NMFC freight class from its product's density in pounds per cubic foot. Each interval below is open at its lower bound and closed at its upper bound: a density exactly equal to a table bound belongs to the interval whose upper bound it is.

| Density in pounds per cubic foot | Freight class |
| -------------------------------- | ------------- |
| greater than 50 | `50` |
| greater than 35, at most 50 | `55` |
| greater than 30, at most 35 | `60` |
| greater than 22.5, at most 30 | `65` |
| greater than 18, at most 22.5 | `70` |
| greater than 15, at most 18 | `77.5` |
| greater than 13.5, at most 15 | `85` |
| greater than 12, at most 13.5 | `92.5` |
| greater than 10.5, at most 12 | `100` |
| greater than 9, at most 10.5 | `110` |
| greater than 8, at most 9 | `125` |
| greater than 7, at most 8 | `150` |
| greater than 6, at most 7 | `175` |
| greater than 5, at most 6 | `200` |
| greater than 4, at most 5 | `250` |
| greater than 3, at most 4 | `300` |
| greater than 2, at most 3 | `400` |
| at least 1, at most 2 | `500` |

Worked boundary pins: a density of exactly 15.0 resolves to class `85`; 15.0001 resolves to `77.5`; exactly 50.0 resolves to `55`; exactly 8.0 resolves to `150`; exactly 1.0 resolves to `500`. A product whose density falls below 1 pound per cubic foot cannot be rated; any line referencing it is rejected with `ERR_INVALID_REQUEST`. The resolved class is stored on the line as the string field `freight_class` (values such as `50`, `65`, up to `500`).

## 3. Business Logic & Workflows

### 3.1. Corporate Accounts, Credit, and Suspension

A `PlatformAdmin` onboards a buyer organization as an **Account**, supplying the `company_name`, an `account_type` of `CORPORATE` or `RETAIL`, a `credit_limit_cents` that may not be negative, and a `default_warehouse_code` naming the preferred sourcing facility — one of `ATL`, `RNO`, or `DFW`, and it must exist in the warehouse registry. A value outside those three names is rejected with `ERR_INVALID_REQUEST`; a well-formed name with no registered warehouse is rejected with `ERR_NOT_FOUND`. When `po_required` is set (it defaults to false), every order the account submits must reference a purchase-order number. New accounts start `ACTIVE`; an account may also be `SUSPENDED`. The account record continuously exposes `open_receivable_cents`, a computed figure maintained in full on every triggering event — order submit, ship, cancel, return restock, invoice payment, and purchase-order approval — as the sum of `grand_total_cents` over the account's orders whose `invoice_status` is `OPEN` and whose order status is one of `STOCK_RESERVED`, `PARTIALLY_BACKORDERED`, `CUSTOM_PRODUCTION`, or `SHIPPED`. Drafts, pending orders, and orders awaiting review are not yet receivables; cancelled and returned orders carry invoices in `VOID` status; all are excluded, and the figure is recomputed wholesale each time so it cannot drift incrementally. A `PlatformAdmin` may later patch the mutable fields `credit_limit_cents`, `po_required`, and `default_warehouse_code`, each patch incrementing the account's `version`. The account list endpoint accepts optional `status` and `account_type` filters alongside the standard pagination parameters.

Suspension is a `PlatformAdmin` action that moves an `ACTIVE` account to `SUSPENDED` and increments its `version`; reactivation reverses it, again with a version increment. A suspended account is blocked from submitting orders and from approving purchase-order reviews — both attempts fail with `ERR_ACCOUNT_SUSPENDED` (HTTP 409) — while its existing in-flight orders are left untouched.

### 3.2. Catalog Stewardship: Products and Quantity Breaks

The `CatalogManager` owns the catalog. Creating a **Product** takes a catalog-unique `sku` (a duplicate is rejected with `ERR_INVALID_REQUEST`), a display `name`, a merchandising `category` of `BOXES`, `MAILERS`, `TAPE`, `CUSHIONING`, or `LABELS`, a strictly positive `base_price_cents`, a selling unit of measure `uom` of `EACH` or `CASE`, a `case_qty` of at least one (exactly one when selling by each), a `pallet_qty` of at least one sellable unit per full pallet, a strictly positive `weight_lbs_per_unit`, and a strictly positive `density_pcf` that drives freight classification. Two flags change downstream behavior: `oversize` (default false) marks items whose dimensions exceed carrier standard limits, and `is_custom_print` (default false) marks made-to-order printed items. `lead_time_days` defaults to zero, must remain zero for stock items, and must be strictly positive for custom-print items. The system derives `ship_method` from the oversize flag — `PARCEL` when the item is not oversize, `FREIGHT` when it is — both at creation and again on any catalog update that changes the flag. Products are created `ACTIVE`; a `DISCONTINUED` product is read-only and no longer orderable — attempts to update it, to add a quantity break to it, or to add an order line for it are rejected with `ERR_INVALID_STATE`. The product list supports `category`, `status`, and `is_custom_print` filters.

A full catalog update reprices future orders and therefore runs under optimistic concurrency control (§2.7): the request must carry `expected_product_version`, and a stale value is rejected with `ERR_STALE_VERSION`. The update may revise `name`, `base_price_cents`, `case_qty`, `pallet_qty`, `weight_lbs_per_unit`, `density_pcf`, `oversize`, and `lead_time_days`; `sku`, `category`, `uom`, and `is_custom_print` are not updatable, and payload fields outside the updatable set are ignored rather than rejected. A successful update recomputes `ship_method` if the oversize flag changed and increments the product's `version`. Discontinuation is allowed only while no order line referencing the product sits in `OPEN`, `ALLOCATED`, or `IN_PRODUCTION` status; with live pipeline lines the transition does not exist and the attempt is rejected with `ERR_INVALID_STATE` (HTTP 409).

**Quantity breaks** give volume pricing. Each break declares a `min_qty` of at least one (the break applies when a line's quantity reaches that bound), a strictly positive `unit_price_cents`, an author-declared integer `sort_seq` (accepted as declared — its ordering against `min_qty` is not validated), and a half-open effective window from `effective_from` (inclusive) to `effective_to` (exclusive); a null `effective_to` means the window is open-ended, and a supplied `effective_to` that is not strictly after `effective_from` is rejected with `ERR_INVALID_REQUEST`. Two breaks for the same product at the same `min_qty` may not have overlapping windows — the attempt is rejected with `ERR_OVERLAPPING_PRICE_WINDOW` (HTTP 422) — though pure adjacency, where one break's window ends exactly as the next begins, is allowed. The selected break's price is a flat per-unit price for the entire line, never a marginal per-tier rate, and it may legitimately exceed the base price for a premium pack. At pricing time the candidate set for a line is every break of that product whose `min_qty` is at most the line quantity and whose window contains the current logical clock; the candidate with the largest `min_qty` wins, with ties broken by the smallest `sort_seq` and then the earliest created (insertion order). A product's breaks are listed in ascending `min_qty` order — ties ascending by `sort_seq`, then by creation order — and removing a break returns 204 with no content.

### 3.3. Warehouses, Inventory, and Replenishment Signals

A `PlatformAdmin` registers each **Warehouse** with a unique `code` of `ATL`, `RNO`, or `DFW` (a duplicate code is rejected with `ERR_INVALID_REQUEST`), a human-readable `name`, the facility's own parcel `zone` from 1 through 8 (the baseline for zone-distance rating), a local same-day `ship_cutoff_time` in HH:MM 24-hour format, and the IANA `timezone` used to interpret that cutoff. Facilities default to `oversize_capable` true, and each declares a `press_count` — default one, always at least one — capping how many custom-print jobs may occupy press time there at once. Warehouses start `ACTIVE`; deactivation moves one to `INACTIVE`, which excludes it from every future sourcing candidate set while leaving existing reservations untouched, and activation restores it. The warehouse list accepts a `status` filter.

**Inventory** is tracked one row per (product, warehouse) pair — the `product_id` and `warehouse_id` combination is unique, and a duplicate creation attempt is rejected with `ERR_INVALID_REQUEST`. Creating a row requires an initial `on_hand_qty` of at least zero. A row records `on_hand_qty` (never negative), a system-managed `reserved_qty` that starts at zero and changes only through the reserve, release, confirm, and decrement flows described below, and an `available_qty` that is always computed on read as the on-hand quantity minus the reserved quantity, never stored divergently. The `backorderable` flag (default false) decides whether lines short at that facility may be placed on backorder rather than failing, and `reorder_point_qty` (default zero, and never negative) is the restock threshold. Receiving stock adds the supplied `qty` — a strictly positive integer — to `on_hand_qty` and increments the row's `version`. A cycle-count adjustment adds `delta_qty` — which may be negative, provided the resulting on-hand quantity stays at or above the current `reserved_qty`, otherwise the adjustment is rejected as `ERR_INVALID_REQUEST` — records an optional free-text `reason`, and also increments `version`; it runs under optimistic concurrency control and must carry `expected_inventory_version` (§2.7). The inventory list accepts `product_id` and `warehouse_id` filters.

Both receiving and adjusting run the replenishment threshold check: whenever a stock movement — a receipt, an adjustment, a reservation release on cancellation, or a return restock — lifts a row's `available_qty` from strictly below its `reorder_point_qty` to at or above it, every active subscription watching that product fires, as detailed in §3.9.

### 3.4. Drafting and Submitting an Order

A `Buyer` opens an **Order** for their account by supplying `account_id`, a destination `ship_zone` from 1 through 8, and optionally a `po_number`, whose uniqueness among the account's non-draft orders is enforced at submit rather than at drafting. The order is born `DRAFT` with all computed totals at zero and `invoice_status` `OPEN`. Order lines are added while the order remains a draft; each line names a `product_id`, a `qty` of at least one sellable unit (a quantity below one is `ERR_INVALID_REQUEST` for an `EACH`-sold product but folds into the case-multiple rule below for a `CASE`-sold one), and may carry a `requested_warehouse_code` sourcing override — an unrecognized code name is `ERR_INVALID_REQUEST`, a well-formed code with no registered warehouse is `ERR_NOT_FOUND`, and for an oversize product a facility that is not oversize-capable is `ERR_NO_WAREHOUSE_CAPABLE`. When the product sells by the case, the quantity must be a whole multiple of the product's `case_qty`, or the line is rejected with `ERR_CASE_QTY_MISMATCH` (HTTP 422) — this holds both when the line is added and when it is later updated. A line on a custom-print product must supply a `print_artwork_ref` and an `over_under_tolerance_pct` between 0 and 20 inclusive; a missing artwork reference or an out-of-range tolerance at line-add time is rejected with `ERR_ARTWORK_REQUIRED` (HTTP 422), while an out-of-range tolerance on a subsequent line update is a malformed-payload `ERR_INVALID_REQUEST`. A line update on a draft order may revise `qty`, `requested_warehouse_code`, `print_artwork_ref`, and `over_under_tolerance_pct`; setting `print_artwork_ref` to null on update clears it — the artwork requirement is enforced only at line-add time. Each line starts `OPEN`; its `unit_price_cents` and `freight_class` are computed, and its `allocated_warehouse_id` stays null until the allocation pass runs. Adding or updating a line on a draft recomputes the order's derived totals but does not increment the order's `version` — only lifecycle transitions do. Beyond the per-order line listing, a flat cross-order line listing supports `order_id`, `product_id`, `allocated_warehouse_id`, and `status` filters, and the order list itself supports `account_id` and `status` filters.

Pricing is resolved per line, always in the pinned order — quantity break first, custom-print surcharge second, pallet incentive third — and recomputed on line add or update in draft, at submit, at approval, and when a custom line's quantity adjusts at production receive. The line's unit price is the winning quantity break's `unit_price_cents` when a candidate exists (§3.2), otherwise the product's `base_price_cents`. For a custom-print product the resolved unit price is then uplifted by fifteen percent, rounding up to the next cent per unit. The line extension is that unit price multiplied by the line quantity. The pallet incentive then rewards full pallets: the number of complete pallets on the line — the line quantity divided by the product's `pallet_qty`, rounded down to a whole number — is multiplied by three percent of the resolved unit price rounded down to a whole cent per pallet. Summing over the order's non-cancelled lines yields `subtotal_cents` from the extensions and `pallet_discount_cents` from the incentives, and the order's `grand_total_cents` is the subtotal minus the pallet discount plus `oversize_surcharge_cents` plus `freight_estimate_cents`. Because all rounding happens per unit and per pallet before summation, the grand total is exact integer addition.

Submission by the `Buyer` triggers a cascade. The gate checks fire in the order of §2.9: the account must be `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`), at least one line must be `OPEN` (else `ERR_ORDER_EMPTY`, HTTP 422), a `CORPORATE` account with `po_required` set must have a `po_number` on the order (else `ERR_PO_REQUIRED`, HTTP 422), and that `po_number` must be unique among the account's non-draft orders (else `ERR_DUPLICATE_PO`, HTTP 409). Pricing and the provisional freight estimate always run. One routing check decides what happens next: on a `po_required` corporate account whose computed `grand_total_cents` exceeds one million cents — ten thousand dollars — the order moves to `PO_REVIEW` — its `promised_ship_date` staying unset — and the allocation pass is deferred until approval (§3.5).

Otherwise the allocation pass runs immediately. For each non-custom `OPEN` line the deterministic sourcing selector builds a candidate set: warehouses that are `ACTIVE`, that match the line's `requested_warehouse_code` when one was given, that are oversize-capable when the product is oversize, and that hold an inventory row for the product. Candidates are ranked by full cover first — those whose `available_qty` reaches the line quantity outrank those that fall short — then by nearest zone, the absolute difference between the order's `ship_zone` and the warehouse's `zone`, ascending; then by preference for the account's `default_warehouse_code`; and finally by warehouse `code` ascending as the deterministic tie-break. An empty candidate set rejects the submit with `ERR_NO_WAREHOUSE_CAPABLE` (HTTP 422). Lines are evaluated sequentially in their creation order within the pass, and each reservation a line would take reduces the availability later lines see at the same row. A covered line becomes `ALLOCATED` and the chosen row's `reserved_qty` increases by the line quantity. A short line remains `OPEN` for the split check: if the inventory row at its selected warehouse is `backorderable`, the line becomes `BACKORDERED`; if not, the entire submit is rejected with `ERR_BACKORDER_NOT_ALLOWED` (HTTP 422) and no reservations persist at all. Custom-print lines bypass stock cover entirely — they are made to order, so no inventory row is required: the selector ranks candidates by nearest zone, then the default-warehouse preference, then code ascending; one custom print job is created `QUEUED` with its `warehouse_id` copied from the line's chosen facility, and the line becomes `IN_PRODUCTION`. The order's final status derives from the post-allocation lines: any custom line puts the order in `CUSTOM_PRODUCTION`; otherwise any `BACKORDERED` line puts it in `PARTIALLY_BACKORDERED`; otherwise it lands in `STOCK_RESERVED`.

Submitting stamps `submitted_at` from the logical clock and computes the `promised_ship_date`, which is rendered on the order as an ISO 8601 UTC timestamp at midnight of the promised calendar date. For stock lines, the clock reading is rendered in the selected warehouse's `timezone`; if the local time-of-day is strictly earlier than that facility's `ship_cutoff_time`, the promise is that same calendar date, otherwise it is the next business day. An order sourced from several warehouses promises the latest of the per-warehouse dates. A custom-print line overrides the stock promise whenever its lead-time projection — the product's `lead_time_days` business days after the submit date, counting the submit day as day zero and skipping weekends — lands later. The account's open receivable is then refreshed and the order's `version` increments.

### 3.5. The Corporate Approval Chain

An order parked in `PO_REVIEW` waits for an `AccountApprover` of the same corporate account — a role deliberately segregated from the `Buyer` who submitted it. Approval first confirms the order is actually in `PO_REVIEW` (any other state yields `ERR_INVALID_STATE`), that the account is still `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`), and then runs the credit check: the account's `open_receivable_cents` plus the order's `grand_total_cents` must be at or below the account's `credit_limit_cents`. Sitting exactly at the limit passes; exceeding it rejects the approval with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422). On success the deferred allocation pass runs exactly as it would have at submit — sourcing selection, reservations, the backorder split check with the same `ERR_NO_WAREHOUSE_CAPABLE` and `ERR_BACKORDER_NOT_ALLOWED` outcomes, custom job creation, and a full pricing and provisional freight recompute — followed by an open-receivable refresh and a `version` increment. Rejection, which may carry an optional `reason`, returns the order to `DRAFT`: no reservation was ever taken, the invoice stays `OPEN` with totals recomputed, the `promised_ship_date` is cleared while `submitted_at` is retained, and the `version` increments — a deliberate revise-and-resubmit loop between buyer and approver.

### 3.6. Custom Print Production

Each custom-print line spawns exactly one live **CustomPrintJob** at a time, linked by `order_line_id`, produced at the facility recorded in `warehouse_id`. The job lifecycle runs `QUEUED` → `PLATING` → `PRINTING` → `COMPLETED`, with `SCRAPPED` as the alternate terminal state, and every step is executed by `WarehouseOps`. Starting a job — `QUEUED` to `PLATING` — enforces press occupancy: at the job's warehouse, the count of *other* jobs in `PLATING` or `PRINTING` whose half-open occupancy intervals from `started_at` to `occupied_until` intersect the new job's prospective occupancy — from now through the instant `lead_time_days` business days after now — must be less than the facility's `press_count`. Back-to-back scheduling is not an intersection: a new job starting exactly when another's `occupied_until` arrives is allowed. A start that would exceed the press budget is rejected with `ERR_PRESS_OCCUPIED` (HTTP 409). A successful start stamps `started_at` from the logical clock, computes `occupied_until` as `lead_time_days` business days after that start, and increments the job's `version`. Advancing moves `PLATING` to `PRINTING` with a version increment.

The production receive step accepts an `actual_qty` — a non-negative integer — and an optional operator `receive_note`, and is defined only from `PRINTING`. It compares `actual_qty` against the tolerance band: the line's quantity scaled up and down by `over_under_tolerance_pct` percent, with the band edges computed using decimal arithmetic rounded half-up to whole units. Inside the band, the job becomes `COMPLETED` with `actual_qty` recorded; the line becomes `ALLOCATED` with its billing quantity adjusted to `actual_qty`; order pricing is recomputed on the new quantity; and a reservation of `actual_qty` is taken at the allocated warehouse — but only when an inventory row exists there for the product, since made-to-order items may have none, in which case the reservation is skipped. Outside the band, the run is a loss: the job becomes `SCRAPPED`, a replacement job is created `QUEUED` for the same line with `warehouse_id` copied over, and the line cycles from `IN_PRODUCTION` back to `OPEN` and immediately into `IN_PRODUCTION` again under the new job — a rework loop that may repeat. A scrap also resets the lead-time baseline: the order's promise is re-projected from the scrap date. Either outcome increments the job's `version`. The job list supports `order_line_id`, `warehouse_id`, and `status` filters.

Because production consumes press capacity and materials, cancellation is guarded: an order carrying a custom-print line cannot be cancelled once that line's job has left `QUEUED`, and the attempt is rejected with `ERR_CUSTOM_PRODUCTION_STARTED` (HTTP 409).

### 3.7. Shipment Execution and Freight Settlement

`WarehouseOps` ships an order once its lines are ready. From `STOCK_RESERVED`, every line must be `ALLOCATED`. From `CUSTOM_PRODUCTION`, every custom line's job must be `COMPLETED` — leaving each custom line `ALLOCATED` at its produced quantity — and every non-custom line must be `ALLOCATED`. From `PARTIALLY_BACKORDERED`, every line that is not `BACKORDERED` must be `ALLOCATED`; backordered lines stay `BACKORDERED`, hold no reservation, and simply do not ship in this pass — the platform ships the covered portion, and the backordered remainder stays `BACKORDERED` on the shipped order; later stock receipts do not automatically allocate it. For each line that ships, the inventory row at its allocated facility loses the shipped quantity from both `on_hand_qty` and `reserved_qty` — custom lines decrement by their produced quantity, and a made-to-order line with no inventory row at its facility skips the decrement — the line becomes `SHIPPED`, and its `shipped_qty` is recorded.

Freight settles at ship time in its final variant. The billable weight is the sum over the lines that actually shipped of shipped quantity times `weight_lbs_per_unit`. The rating class is the numerically highest `freight_class` among those lines, and the per-pound rate is: class `50` at $0.90, class `55` at $1.05, classes `60` through `92.5` at $1.20, classes `100` through `125` at $1.45, classes `150` through `200` at $1.75, and classes `250` and above at $2.10. The zone factor is one plus twelve hundredths times the zone distance minus one, where the zone distance is the absolute difference between the order's `ship_zone` and the `zone` of the ship-from warehouse carrying the greatest total units of the rated line set — the sourcing-selected warehouses for the provisional figure, the allocated warehouses at settle time, with quantity ties broken by warehouse code ascending — and is always at least one. The final `freight_estimate_cents` is the ceiling of weight times rate times zone factor, computed with exact rational arithmetic and a single ceiling applied once. The provisional variant computed at submit differs in exactly two ways: it covers all non-cancelled lines rather than only shipped ones, and it applies an additional eleven-tenths uplift — which makes the provisional figure strictly at least the final figure for identical inputs.

Oversize handling is surcharged per order. When the order contains oversize lines shipping `FREIGHT`, `oversize_surcharge_cents` starts at 8,900 cents, gains another 2,500 cents when the zone distance is at least 4, and gains another 5,000 cents when any single line's total weight — its quantity times `weight_lbs_per_unit` — exceeds 150 pounds; with no oversize freight lines the surcharge is zero. Shipping also refreshes the account's open receivable and increments the order's `version`.

A `Buyer` may cancel an order, with an optional `reason`, from `DRAFT`, `PENDING`, `STOCK_RESERVED`, `PARTIALLY_BACKORDERED`, or `CUSTOM_PRODUCTION` — subject to the custom-production guard of §3.6, which alone can bar a `CUSTOM_PRODUCTION` order. Cancellation releases every allocated line's reservation (each affected row's `reserved_qty` drops, the lines become `CANCELLED`, the freed stock raises `available_qty` and runs the replenishment threshold check), scraps every still-`QUEUED` print job, sets `invoice_status` to `VOID`, refreshes the receivable, and increments `version`. Once an order is `SHIPPED`, an `AccountApprover` or `PlatformAdmin` marks its invoice `PAID`, which likewise refreshes the receivable and increments `version`; attempting payment on an order that has not shipped — or whose invoice is no longer `OPEN` — is rejected with `ERR_INVALID_STATE`.

### 3.8. Returns, Refunds, and Restocking

A `Buyer` — or a `CustomerService` agent acting on the account's behalf — requests a **Return** against a shipped order, supplying the `order_id`, a `return_type` of `STOCK` or `CUSTOM`, a free-form `reason_code`, and a `lines` payload — a non-empty array — in which each entry names an `order_line_id` and a `qty`; repeated entries naming the same order line accumulate against that line's remaining returnable quantity within the request. The referenced order must be `SHIPPED`; requesting a return against an order in any other state is rejected with `ERR_INVALID_STATE`. Every entry's line must belong to the return's order, or the request fails with `ERR_RETURN_LINE_MISMATCH` (HTTP 422). Each requested `qty` must be at least one and may not exceed the order line's `shipped_qty` minus the quantities already carried on that line's prior non-`REJECTED` returns, or the request fails with `ERR_RETURN_QTY_EXCEEDED` (HTTP 422). Type eligibility is enforced both at request time and again at approval: a `CUSTOM` return may reference only custom-print lines and a `STOCK` return only stock lines — any mismatch is `ERR_CUSTOM_NOT_RETURNABLE` (HTTP 422). A new return is stamped `requested_at` from the logical clock and starts `REQUESTED`. The returns list supports `order_id` and `status` filters; return lines are also reachable through a flat listing filtered by `return_id` or `order_line_id`.

Approval is a `CustomerService` action defined only from `REQUESTED`. The request must be no older than thirty calendar days — `requested_at` must sit at or after the instant thirty days before the current clock — or approval fails with `ERR_RETURN_WINDOW_EXPIRED` (HTTP 422). Approval computes the financials: per return line, the credit is the returned quantity times the order line's `unit_price_cents`, scaled by one minus the restocking percentage — fifteen percent for `CUSTOM` returns, zero for `STOCK` — rounded half-up to a whole cent per line; `refund_cents` is the sum of those per-line credits, and `restock_fee_cents` is the sum over lines of the returned quantity times the unit price times the restocking percentage, likewise rounded half-up per line before summing. The pinned order is round-per-line-then-sum, which differs by design from summing first and rounding once. Rejection, with an optional `reason`, moves the return to `REJECTED`, a terminal state.

`WarehouseOps` then receives the physical goods, moving `APPROVED` to `RECEIVED` and finalizing `refund_cents` under the same per-line-then-sum rule. Restocking moves `RECEIVED` to `RESTOCKED`: for a `STOCK` return each line adds its `qty` back to `on_hand_qty` at the order line's originally allocated warehouse, raising `available_qty` and running the replenishment threshold check; a `CUSTOM` return is simply scrapped and touches no inventory. When every line of the parent order has been fully covered by restocked return quantities — the returned total equals each line's `shipped_qty` — the order itself transitions from `SHIPPED` to `RETURNED`, its `invoice_status` becomes `VOID`, the account's open receivable is refreshed, and the order's `version` increments.

### 3.9. Back-in-Stock Subscriptions

A `Buyer` registers a **RestockNotification** by naming an `account_id` and a `product_id`, subscribing the account to a restock alert for that product. Only one `ACTIVE` subscription may exist per (account, product) pair; a duplicate is rejected with `ERR_DUPLICATE_SUBSCRIPTION` (HTTP 409). Subscriptions start `ACTIVE`. Whenever a stock movement at any warehouse — a receipt, an adjustment, a reservation release on cancellation, or a return restock — lifts the row's `available_qty` from strictly below its `reorder_point_qty` to at or above it, every `ACTIVE` subscription watching that product fires exactly once: the status becomes `NOTIFIED` and `notified_at` is stamped from the logical clock. A `Buyer` may cancel an `ACTIVE` subscription, but only one belonging to their own account; acting on another account's subscription is `ERR_UNAUTHORIZED`. `NOTIFIED` and `CANCELLED` are terminal. The subscription list accepts `account_id`, `product_id`, and `status` filters.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or act on an existing resource return `200 OK`. The one deletion endpoint — removing a quantity break — returns `204 No Content`. All endpoints are mounted under the `/packaging-distribution` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/packaging-distribution/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| POST | `/packaging-distribution/accounts` | Create a corporate or retail account | PlatformAdmin |
| GET | `/packaging-distribution/accounts` | List accounts with optional filters | PlatformAdmin, CustomerService |
| GET | `/packaging-distribution/accounts/{id}` | Fetch one account with its computed open receivable | PlatformAdmin, CustomerService, AccountApprover, Buyer |
| PATCH | `/packaging-distribution/accounts/{id}` | Update mutable account fields | PlatformAdmin |
| POST | `/packaging-distribution/accounts/{id}/suspend` | Suspend an active account | PlatformAdmin |
| POST | `/packaging-distribution/accounts/{id}/reactivate` | Reactivate a suspended account | PlatformAdmin |
| POST | `/packaging-distribution/products` | Create a catalog product | CatalogManager |
| GET | `/packaging-distribution/products` | List products with optional filters | PlatformAdmin, CatalogManager, CustomerService, Buyer, AccountApprover, WarehouseOps |
| GET | `/packaging-distribution/products/{id}` | Fetch one product | PlatformAdmin, CatalogManager, CustomerService, Buyer, AccountApprover, WarehouseOps |
| PUT | `/packaging-distribution/products/{id}` | Full catalog update under optimistic concurrency | CatalogManager |
| POST | `/packaging-distribution/products/{id}/discontinue` | Discontinue an active product | CatalogManager |
| POST | `/packaging-distribution/products/{id}/quantity-breaks` | Add a quantity break with a half-open price window | CatalogManager |
| GET | `/packaging-distribution/products/{id}/quantity-breaks` | List a product's quantity breaks in ascending minimum-quantity order | PlatformAdmin, CatalogManager, CustomerService, Buyer, AccountApprover |
| DELETE | `/packaging-distribution/quantity-breaks/{id}` | Remove a quantity break | CatalogManager |
| POST | `/packaging-distribution/warehouses` | Register a warehouse | PlatformAdmin |
| GET | `/packaging-distribution/warehouses` | List warehouses | PlatformAdmin, CatalogManager, CustomerService, WarehouseOps, Buyer, AccountApprover |
| GET | `/packaging-distribution/warehouses/{id}` | Fetch one warehouse | PlatformAdmin, CatalogManager, CustomerService, WarehouseOps |
| POST | `/packaging-distribution/warehouses/{id}/deactivate` | Deactivate a warehouse, excluding it from future sourcing | PlatformAdmin |
| POST | `/packaging-distribution/warehouses/{id}/activate` | Reactivate a warehouse | PlatformAdmin |
| POST | `/packaging-distribution/inventory` | Create an inventory row for a product at a warehouse | WarehouseOps, PlatformAdmin |
| GET | `/packaging-distribution/inventory` | List inventory rows with optional filters | PlatformAdmin, WarehouseOps, CustomerService |
| GET | `/packaging-distribution/inventory/{id}` | Fetch one inventory row with its computed availability | PlatformAdmin, WarehouseOps, CustomerService |
| POST | `/packaging-distribution/inventory/{id}/receive` | Receive stock into a row | WarehouseOps |
| POST | `/packaging-distribution/inventory/{id}/adjust` | Cycle-count adjustment under optimistic concurrency | WarehouseOps |
| POST | `/packaging-distribution/orders` | Create a draft order | Buyer |
| GET | `/packaging-distribution/orders` | List orders with optional filters | PlatformAdmin, CustomerService, WarehouseOps, Buyer, AccountApprover |
| GET | `/packaging-distribution/orders/{id}` | Fetch one order with computed totals | PlatformAdmin, CustomerService, WarehouseOps, Buyer, AccountApprover |
| POST | `/packaging-distribution/orders/{id}/lines` | Add a line to a draft order | Buyer |
| GET | `/packaging-distribution/orders/{id}/lines` | List an order's lines | PlatformAdmin, CustomerService, WarehouseOps, Buyer, AccountApprover |
| GET | `/packaging-distribution/order-lines` | Flat filtered list of order lines across orders | PlatformAdmin, CustomerService, WarehouseOps, Buyer, AccountApprover |
| GET | `/packaging-distribution/order-lines/{id}` | Fetch one order line | PlatformAdmin, CustomerService, WarehouseOps, Buyer, AccountApprover |
| PUT | `/packaging-distribution/orders/{id}/lines/{lineId}` | Update quantity or artwork on a draft order line | Buyer |
| POST | `/packaging-distribution/orders/{id}/submit` | Submit a draft order: pricing, allocation, provisional freight, promise date | Buyer |
| POST | `/packaging-distribution/orders/{id}/approve` | Approve a purchase-order review | AccountApprover |
| POST | `/packaging-distribution/orders/{id}/reject` | Reject a purchase-order review back to draft | AccountApprover |
| POST | `/packaging-distribution/orders/{id}/ship` | Ship allocated lines, decrement stock, settle final freight | WarehouseOps |
| POST | `/packaging-distribution/orders/{id}/cancel` | Cancel a pre-ship order, releasing reservations and voiding the invoice | Buyer |
| POST | `/packaging-distribution/orders/{id}/invoice/pay` | Mark a shipped order's invoice paid | AccountApprover, PlatformAdmin |
| GET | `/packaging-distribution/custom-print-jobs` | List custom print jobs with optional filters | PlatformAdmin, WarehouseOps, CustomerService |
| GET | `/packaging-distribution/custom-print-jobs/{id}` | Fetch one custom print job | PlatformAdmin, WarehouseOps, CustomerService |
| POST | `/packaging-distribution/custom-print-jobs/{id}/start` | Start a queued job, enforcing press occupancy | WarehouseOps |
| POST | `/packaging-distribution/custom-print-jobs/{id}/advance` | Advance a plating job to printing | WarehouseOps |
| POST | `/packaging-distribution/custom-print-jobs/{id}/receive` | Receive a printing job: complete in tolerance, or scrap and re-queue | WarehouseOps |
| POST | `/packaging-distribution/returns` | Request a return against a shipped order | Buyer, CustomerService |
| GET | `/packaging-distribution/returns` | List returns with optional filters | PlatformAdmin, CustomerService, WarehouseOps, Buyer |
| GET | `/packaging-distribution/returns/{id}` | Fetch one return | PlatformAdmin, CustomerService, WarehouseOps, Buyer |
| GET | `/packaging-distribution/returns/{id}/lines` | List a return's lines | PlatformAdmin, CustomerService, WarehouseOps, Buyer |
| GET | `/packaging-distribution/return-lines` | Flat filtered list of return lines | PlatformAdmin, CustomerService, WarehouseOps, Buyer |
| GET | `/packaging-distribution/return-lines/{id}` | Fetch one return line | PlatformAdmin, CustomerService, WarehouseOps, Buyer |
| POST | `/packaging-distribution/returns/{id}/approve` | Approve a requested return, computing fee and refund | CustomerService |
| POST | `/packaging-distribution/returns/{id}/reject` | Reject a requested return | CustomerService |
| POST | `/packaging-distribution/returns/{id}/receive` | Receive an approved return, finalizing the refund | WarehouseOps |
| POST | `/packaging-distribution/returns/{id}/restock` | Restock a received return; full-order restock returns the order | WarehouseOps |
| POST | `/packaging-distribution/restock-notifications` | Subscribe an account to a product restock alert | Buyer |
| GET | `/packaging-distribution/restock-notifications` | List subscriptions with optional filters | PlatformAdmin, CustomerService, Buyer |
| GET | `/packaging-distribution/restock-notifications/{id}` | Fetch one subscription | PlatformAdmin, CustomerService, Buyer |
| POST | `/packaging-distribution/restock-notifications/{id}/cancel` | Cancel an active subscription | Buyer |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3; this table is the identifier-to-status reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_SUSPENDED` | 409 Conflict |
| `ERR_ORDER_EMPTY` | 422 Unprocessable Entity |
| `ERR_PO_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PO` | 409 Conflict |
| `ERR_CASE_QTY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ARTWORK_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SUBSCRIPTION` | 409 Conflict |
| `ERR_NO_WAREHOUSE_CAPABLE` | 422 Unprocessable Entity |
| `ERR_BACKORDER_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RETURN_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_RETURN_LINE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CUSTOM_NOT_RETURNABLE` | 422 Unprocessable Entity |
| `ERR_CUSTOM_PRODUCTION_STARTED` | 409 Conflict |
| `ERR_RETURN_QTY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_OVERLAPPING_PRICE_WINDOW` | 422 Unprocessable Entity |
| `ERR_PRESS_OCCUPIED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

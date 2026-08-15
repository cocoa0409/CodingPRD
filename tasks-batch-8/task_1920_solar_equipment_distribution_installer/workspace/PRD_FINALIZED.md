# Solar Distribution Installer API — Product Requirements Document

## 1. Introduction

Solar equipment distribution is a working-capital business conducted against a moving cost basis. A distributor books ocean containers of modules, inverters, racking, and balance-of-system hardware months before the freight arrives; tariff rates can change while a container is still on the water, module technology generations turn over on a calendar measured in quarters, and installer customers buy on open-account credit terms that must be enforced allocation by allocation. On top of that, every warehouse lot is a finite pool that multiple installer projects compete for, and every design decision — which module pairs with which inverter, in what string size — is constrained by manufacturer compatibility data.

This document specifies the Solar Distribution Installer API, mounted under `/solar-dist`, which manages that entire operating loop for a distribution warehouse and its installer channel. The API governs the product catalog and the module–inverter compatibility rules that make a design buildable; the booking, tracking, and receipt of ocean containers, including the reconciliation between the provisional landed cost estimated at booking and the final landed cost computed at receipt; the installer credit ledger, with progress billing at delivery and the remainder due at permission-to-operate; warranty returns credited through manufacturers; permit-package assembly for each jurisdiction; damaged-in-transit claims against carriers; and the orderly retirement of stranded, technologically obsolete inventory. Every state change is atomic within a single request, and every derived figure — credit exposure, available quantity, allocated value — is refreshed inside the same transaction that triggered it.

## 2. Global Specifications & System-Wide Principles

This section defines the structural contract of the API: authentication, the response envelope, pagination, common resource metadata, monetary precision, existence checking, derived-field reconciliation, optimistic concurrency, the order in which rules are evaluated, and the logical clock.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or invalid is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly four roles: `DistributionAdmin`, `ChannelManager`, `InstallerRep`, and `CreditOfficer`. Authorization is per-operation, and a request whose role is not permitted for the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The four roles divide the operating loop. A `DistributionAdmin` runs the warehouse side: the product catalog, compatibility rules, tariff rates, container booking and receipt, allocation shipment, damage-claim filing, and the administrative clock. A `ChannelManager` manages the installer channel: installer onboarding and activation, project oversight, permission-to-operate invoicing, RMA adjudication, and permit approval. An `InstallerRep` acts on behalf of one installer company: designing projects, allocating inventory, assembling permit packages, filing RMA claims, and posting payments. A `CreditOfficer` is an orthogonal gate over credit: suspending, reinstating, and terminating installers, voiding invoices, reversing payments, issuing RMA credits, writing off stranded lots and bad debt, and settling or denying damage claims.

When `X-User-Role` is `InstallerRep`, `X-User-ID` is the `id` of the acting `Installer`; ownership checks on any resource that references an `Installer` compare the resource's foreign-key field to `X-User-ID`. Consequently, an `InstallerRep` may create a project only under their own installer — the owning installer of the new project must equal `X-User-ID`, otherwise the request fails with `ERR_INSUFFICIENT_PERMISSIONS` — may lock a design, cancel a project, place an allocation, or release an allocation only on their own installer's projects, may post a payment only against their own installer's invoices, and must name their own installer as the claimant when creating an RMA claim. When `X-User-Role` is `DistributionAdmin`, `ChannelManager`, or `CreditOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. A `ChannelManager` shares the project-creation, design-lock, cancellation, allocation, and release operations with `InstallerRep` but without the ownership restriction, and a `CreditOfficer` shares payment posting.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — Product, CompatibilityRule, TariffRate, Installer, InventoryLot, Container, ContainerLine, Project, Allocation, Invoice, Payment, RmaClaim, PermitPackage, and DamageClaim — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, uniquely identifying the resource.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource.

Recomputation of a derived field counts as a modification: when a triggered recalculation writes a new value onto a resource, that resource's `updated_at` refreshes and its `version` increments. Timestamps such as `actual_arrival_utc`, `received_at`, `stranded_at`, `design_locked_at`, `allocated_at`, `released_at`, `shipped_at`, `submitted_at`, `approved_at`, `filed_at`, `settled_at`, and `reversed_at` are null until the event they record occurs, and `effective_to` and `manufacturer_rma_number` may remain null indefinitely.

### 2.5. Money, Basis Points, and Rounding

All monetary values in the system are integer cents — list prices, declared customs values, freight and insurance costs, per-unit landed costs, invoice amounts and balances, payments, credits, and claim amounts alike. Percentage rates are expressed in basis points, where one basis point is one-hundredth of one percent and ten thousand basis points make a whole: a duty rate of 1450 basis points is a 14.50% duty, and a progress-payment percentage of 8000 basis points means 80% of the allocated value is billed at delivery. Every division performed inside a calculation rounds half up to a whole cent, and multi-step calculations round at each division step rather than only at the end, so that every intermediate figure is itself a whole-cent amount.

### 2.6. Nested Resource Retrieval and Existence Order

For any endpoint whose path names more than one resource, the identifiers in the path are validated strictly from left to right. The request is rejected immediately with a `404 Not Found` for the first identifier that does not resolve to an existing resource, before any later identifier — and before any business rule — is examined. Each resource type has its own not-found error: `ERR_PRODUCT_NOT_FOUND`, `ERR_RULE_NOT_FOUND`, `ERR_TARIFF_NOT_FOUND`, `ERR_INSTALLER_NOT_FOUND`, `ERR_CONTAINER_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_RMA_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, and `ERR_CLAIM_NOT_FOUND`. Independently of path resolution, a request that is structurally malformed — a required field missing, or a value of the wrong type — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Derived Fields and Same-Transaction Reconciliation

The system maintains a family of derived figures, and each is recomputed inside the same transaction as the event that could change it; there is no eventual-consistency window anywhere in the API. An installer carries `credit_exposure_cents` and the boolean `credit_hold`; an inventory lot carries `qty_available` plus the unit-cost pair `unit_cost_cents_provisional` and `unit_cost_cents_final`; a project carries `allocated_value_cents`, `invoiced_value_cents`, and `paid_value_cents`; an invoice carries `balance_due_cents` and `due_date`; a project also carries `system_size_kw_dc` once its design is locked; and claims carry `claimed_amount_cents` and `credit_amount_cents`. The precise formulas live in §3 alongside the workflows that trigger them.

State changes that originate in one aggregate propagate to others within the same transaction. Cancelling a container writes off its inventory lots; suspending an installer cancels that installer's open allocations; discontinuing a product retires its active compatibility rules; shipping an allocation can advance a project's fulfillment and issue an invoice. Each such reconciliation independently mutates every affected resource, refreshing its `updated_at` and incrementing its `version`.

### 2.8. Optimistic Concurrency Control

Exactly two write operations in the API are guarded by optimistic concurrency control.

Creating an allocation against an inventory lot requires the request to carry `expected_lot_version`, the `version` of the target `InventoryLot` that the client last observed. If the lot's current `version` does not match the supplied value — because another writer has since placed, released, or shipped an allocation against the same lot, each of which legitimately mutates the reserved quantity and therefore the client's observed availability — the create is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412), preventing the client from reserving against a lot state it has not observed.

Receiving a container requires the request to carry `expected_container_version`, the `version` of the `Container` that the client last observed. If the container's current `version` does not match — because another writer has since marked it departed, marked it arrived, or revised its ETA or cost figures — the receipt is rejected with `ERR_STALE_CONTAINER_VERSION` (HTTP 412).

Endpoints not named in these two rules do not accept a version field.

### 2.9. Order of Rule Evaluation

When several rules bear on a single request, the server evaluates them in a fixed order and reports the first failure encountered. The evaluation order is:

1. Presence and validity of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the operation (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Existence of every resource named in the path, validated left to right (the per-resource `ERR_*_NOT_FOUND` errors of §2.6).
4. State-machine preconditions on the target resource (the various 409 state errors, such as `ERR_PRODUCT_NOT_ACTIVE`, `ERR_INSTALLER_NOT_ACTIVE`, `ERR_ALLOCATION_NOT_OPEN`, the `ERR_CONTAINER_NOT_*` family, and their peers on invoices, RMA claims, permit packages, and damage claims).
5. Design-lock safety: that a covering compatibility rule exists and the string size is within bounds (`ERR_NO_COMPATIBILITY_RULE`, `ERR_STRING_SIZE_VIOLATION`).
6. Referential integrity: referenced products must be `ACTIVE`, and every foreign-key chain — project to installer, allocation to lot, container line to lot, RMA claim to allocation, damage claim to container line — must be intact and non-terminal. This check runs at design lock, allocation creation, allocation shipment, RMA submission, and damage-claim filing.
7. The credit gate on allocation creation (`ERR_CREDIT_LIMIT_EXCEEDED`).
8. Inventory availability (`ERR_INSUFFICIENT_QTY`), evaluated both when an allocation is created and when one is shipped.
9. Temporal reconciliation: per-line receipt quantities on container receipt (`ERR_RECEIPT_QTY_MISMATCH`), and the update window on container edits (`ERR_CONTAINER_NOT_UPDATABLE`).
10. Payment amount bounds (`ERR_INVALID_PAYMENT_AMOUNT`, `ERR_INVOICE_VOID`).
11. The compound preconditions of PTO invoicing (`ERR_PROGRESS_NOT_BILLED`, `ERR_PERMIT_NOT_APPROVED`).
12. The installer-termination gate (`ERR_OUTSTANDING_BALANCE`).
13. Permit-submission completeness (`ERR_MISSING_REQUIRED_DOCS`, `ERR_DESIGN_NOT_LOCKED`).
14. Optimistic-concurrency version checks (`ERR_STALE_LOT_VERSION`, `ERR_STALE_CONTAINER_VERSION`), always the last gate before a guarded write commits.

So, for example, an allocation request that would fail both the credit gate and the availability check reports the credit failure, and a stale version surfaces only after every other rule on that request has passed.

### 2.10. The Logical Clock and Scheduled Reconciliation

All timestamps the system computes — arrival stamps, due dates, sweep thresholds — are read from a logical UTC clock rather than the wall clock. At startup the logical clock reads 2026-08-01T00:00:00Z. A `DistributionAdmin`-only, test-driving capability moves the clock to a supplied `to_iso8601` instant and returns the new `current_utc`, letting tests advance past an ETA, a `due_date`, an obsolescence lag, or a stranded-age threshold without wall-clock waits. Immediately after any clock move, the obsolescence sweep (§3.1, §3.3) and the past-due invoice marking (§3.7) re-run against the new time.

Independently of explicit clock moves, the obsolescence sweep runs at the end of each UTC day, and an invoice in `OPEN` or `PARTIALLY_PAID` whose `due_date` has passed with a balance still outstanding is marked `PAST_DUE` as time advances.

## 3. Business Logic & Workflows

### 3.1. Catalog Stewardship: Products, Compatibility Rules, and Tariff Rates

A `DistributionAdmin` builds the catalog product by product. Each product is created with a manufacturer `sku`, unique per product; a `product_kind` of `MODULE`, `INVERTER`, `RACKING`, or `BOS`; the `manufacturer_name` in its legal form, which is what appears on warranty registrations and RMA correspondence; a `technology_generation` index that increases monotonically from 1 upward, where a lower number is an older generation; the `hts_code` that drives tariff-rate lookup; and the distributor `list_price_cents` per unit. Kind-specific electrical ratings follow the kind: `wattage_w`, the module nameplate watts, is required when the product is a `MODULE` and is otherwise 0, while `ac_output_w` and `dc_input_max_w` — the inverter's continuous AC output and maximum DC input watts — are required when the product is an `INVERTER` and are otherwise 0. A newly created product is `ACTIVE`. The catalog listing can be filtered by `product_kind`, `status`, and `manufacturer_name`.

Discontinuing a product is a `DistributionAdmin` action allowed only from `ACTIVE`; attempting it on a product in any other state is rejected with `ERR_PRODUCT_NOT_ACTIVE`. Discontinuation moves the product `ACTIVE` → `DISCONTINUED` and, in the same transaction, retires every `ACTIVE` compatibility rule that references the product, setting each such rule's `effective_to` to the current time.

The end-of-day obsolescence sweep carries products from `DISCONTINUED` to `OBSOLETE`. For each `DISCONTINUED` product, the sweep compares its `technology_generation` against the current maximum `technology_generation` across all products of the same `product_kind`, regardless of those products' statuses: if the product's generation is less than that maximum minus two, and no inventory lot in any state except `WRITTEN_OFF` references the product with `qty_on_hand` greater than zero, the product becomes `OBSOLETE`. Obsolescence cascades immediately: every `OPEN` allocation referencing lots of the newly obsolete product moves to `CANCELLED`, and `allocated_value_cents` is recomputed for each affected project. `OBSOLETE` is terminal.

**Compatibility rules** are the distributor's published statement of which module pairs with which inverter. Creating one takes the `module_product_id` and `inverter_product_id` of the pair, the `max_modules_per_inverter` and `min_modules_per_inverter` string-size bounds, an `effective_from` timestamp, and an optional `effective_to` — left null, the rule is open-ended. Creation validates that both referenced products exist, are of the correct kinds (a `MODULE` and an `INVERTER` respectively), and are `ACTIVE`; the new rule starts `ACTIVE`. Rules can be listed with filters on `module_product_id`, `inverter_product_id`, and `status`. A `DistributionAdmin` retires a rule — moving it `ACTIVE` → `RETIRED`, terminal — only while it is `ACTIVE`, failing with `ERR_RULE_NOT_ACTIVE` otherwise; retirement sets `effective_to` to the current time if it was open-ended. Retirement is refused with `ERR_RULE_IN_USE` while any project has pinned the rule into its design but has not yet locked that design.

**Tariff rates** map an `hts_code` to a `duty_rate_bp` over an effective window: `effective_from` marks the start, and an optional `effective_to` marks the end (null means open-ended). A newly created rate is `ACTIVE`; the only other status value is `SUPERSEDED`. Creation is rejected with `ERR_TARIFF_WINDOW_OVERLAP` when another `ACTIVE` rate for the same `hts_code` already covers any part of the proposed window. Rates can be listed filtered by `hts_code` and `status`. Wherever the system looks up "the tariff in effect at an instant" — booking time for provisional cost, arrival time for final cost — it selects the rate whose `hts_code` matches the product's `hts_code`, whose `effective_from` is at or before the instant, and whose window has not yet closed (`effective_to` null, or the instant strictly before `effective_to`); if several rates qualify, the one with the most recent `effective_from` wins, with ties broken by the most recently created rate.

### 3.2. The Installer Lifecycle and the Credit Ledger

A `ChannelManager` onboards an installer by supplying its `legal_name`, its state contractor `license_number`, the approved open-account `credit_limit_cents`, the `progress_payment_pct_bp` governing how much is billed at delivery — expressed in basis points, so 8000 means 80% at delivery with the remaining 20% due at permission-to-operate — and `payment_terms_days`, the net-N terms that set each invoice's due date. A new installer begins in `ONBOARDING` with `credit_exposure_cents` at 0 and `credit_hold` false. Installers can be listed with a `status` filter.

Activation moves the installer `ONBOARDING` → `ACTIVE` and enforces three checks: `credit_limit_cents` must be greater than zero, or the request fails with `ERR_CREDIT_LIMIT_REQUIRED`; `progress_payment_pct_bp` must lie between 0 and 10000 inclusive, or `ERR_INVALID_PROGRESS_PCT`; and `payment_terms_days` must be greater than zero, or `ERR_INVALID_PAYMENT_TERMS`. Activation initializes `credit_exposure_cents` to 0 and sets `credit_hold` to false.

Suspension and termination are `CreditOfficer` actions. Suspending requires the installer to be `ACTIVE` (otherwise `ERR_INSTALLER_NOT_ACTIVE`) and moves it `ACTIVE` → `SUSPENDED`; in the same transaction, every `OPEN` allocation on the installer's projects is cancelled, and any project whose allocations have all reached terminal states while its `payment_status` is still `UNBILLED` has its `fulfillment_status` moved to `CANCELLED`. Reinstating requires the installer to be `SUSPENDED` (otherwise `ERR_INSTALLER_NOT_SUSPENDED`) and is refused with `ERR_CREDIT_LIMIT_EXCEEDED` unless the installer's `credit_exposure_cents` is strictly below its `credit_limit_cents`. Termination is permitted from either `ACTIVE` or `SUSPENDED` and moves the installer to `TERMINATED`, which is terminal; it requires the installer's `credit_exposure_cents` to be exactly zero, failing with `ERR_OUTSTANDING_BALANCE` otherwise, and it requires that no project of the installer's is still in flight — every project must have reached a financial terminal state (`PAID_IN_FULL` or `WRITTEN_OFF`) and an operational terminal state (`COMPLETE` or `CANCELLED`). Terminating from `ACTIVE` additionally cancels any remaining `OPEN` allocations.

The credit ledger itself is a derived figure, not a stored balance anyone edits. An installer's `credit_exposure_cents` is the sum of `balance_due_cents` across that installer's invoices in `OPEN`, `PARTIALLY_PAID`, or `PAST_DUE` status, excluding `WRITE_OFF` invoices entirely — a write-off has already recognized the loss, so it must not keep weighing on exposure. The exposure is recomputed on every invoice issue, payment posting or reversal, invoice void, RMA credit issue, and project write-off. The boolean `credit_hold` is true exactly when `credit_exposure_cents` reaches or exceeds `credit_limit_cents`: the hold engages at equality, not above it. An installer on credit hold cannot place new allocations, as detailed in §3.6.

### 3.3. Ocean Freight: Booking, Lines, and Container Receipt

Freight enters the system when a `DistributionAdmin` books a container with its `container_number`, unique per shipment; the `bol_number` of the bill of lading; the `origin_port`; the current best-estimate `eta_utc`; and the total `freight_cost_cents` and `insurance_cost_cents` for the container. A new container is `BOOKED`, and the container listing can be filtered by `status`.

Each booked container is built up line by line. Adding a line takes a `product_id`, a `qty_booked`, and the `declared_unit_value_cents` per unit used for customs duty computation. Creating a line provisions the corresponding `InventoryLot` for that product in the same transaction — status `IN_TRANSIT`, `qty_on_hand` 0, and a `unit_cost_cents_provisional` computed per §3.4 using the tariff in effect at booking time — and the line records its `container_id` and the `inventory_lot_id` of that lot. The line also keeps its own `product_id`, redundant with the lot's product and retained for receipt-time audit, and tracks `qty_received` and `qty_damaged`, both 0 until the receipt call sets them. Lines are listed per container, and a top-level line listing exists filterable by `container_id`, `inventory_lot_id`, and `product_id`.

While a container is `BOOKED` or `IN_TRANSIT`, a `DistributionAdmin` may revise its `eta_utc`, `freight_cost_cents`, or `insurance_cost_cents`; from any later state the edit is rejected with `ERR_CONTAINER_NOT_UPDATABLE`. Each accepted edit recomputes the provisional landed cost on every attached lot — the booking-time tariff stays fixed, and only the freight and insurance shares move — and increments the container's `version` by 1.

From `BOOKED`, marking departure moves the container to `IN_TRANSIT`; the request fails with `ERR_CONTAINER_NOT_BOOKED` from any other state, and the container's `version` increments. Marking arrival requires `IN_TRANSIT` — otherwise `ERR_CONTAINER_NOT_IN_TRANSIT` — moves the container to `ARRIVED`, stamps `actual_arrival_utc` with the current logical time, and increments `version` again.

Receipt is the pivotal event. The receipt request carries `expected_container_version` for optimistic concurrency (§2.8) and a `line_receipts` list with one entry per line, each naming the `container_line_id` and its `qty_received` and `qty_damaged` counts. The container must be `ARRIVED`, failing with `ERR_CONTAINER_NOT_ARRIVED` otherwise, and every line must reconcile — for each line, the received quantity plus the damaged quantity must equal exactly the booked quantity, or the entire receipt is rejected with `ERR_RECEIPT_QTY_MISMATCH`. On acceptance, and for each line, the system computes the final landed cost per §3.4; increases the lot's `qty_on_hand` by the received quantity; increases the lot's `qty_quarantined` by the damaged quantity, those units being held for inspection and unavailable for allocation; sets the lot's `unit_cost_cents_final`; stamps the lot's `received_at`; and transitions the lot `IN_TRANSIT` → `ON_HAND`. Every project holding `OPEN` allocations against any of these lots then has its `allocated_value_cents` recomputed, since the final cost replaces the provisional one going forward — the frozen `unit_cost_cents_at_allocation` snapshots on existing allocations do not move. The container lands in `RECEIVED`, with its `version` incremented by 1.

A `RECEIVED` container is closed once every damage claim against it has reached `SETTLED` or `DENIED`; while any claim remains unsettled, closing fails with `ERR_OPEN_DAMAGE_CLAIMS`. Separately, a container still `BOOKED` can be cancelled to `CANCELLED` — from any other state the attempt fails with `ERR_CONTAINER_NOT_CANCELLABLE` — and cancellation writes off every attached lot, moving each to `WRITTEN_OFF` with `qty_on_hand` zeroed. `RECEIVED`, `CLOSED`, and `CANCELLED` are the container's terminal states.

Each `InventoryLot` carries the manufacturer's physical `lot_code`, its `product_id`, and four quantity counters: `qty_on_hand` (physical units in the warehouse, increased at container receipt and decreased by shipment and damage write-off), `qty_allocated` (units reserved to non-terminal projects), `qty_quarantined` (units held for damage or RMA inspection), and the derived `qty_available`, which is `qty_on_hand` minus `qty_allocated` minus `qty_quarantined` and is never negative. A lot's `unit_cost_cents_final` and `received_at` stay null until receipt; its `stranded_at` stays null unless the sweep strands it. An `ON_HAND` lot becomes `DEPLETED` automatically the moment all three physical counters — on-hand, allocated, and quarantined — stand at zero. The sweep moves an `ON_HAND` lot with `qty_on_hand` greater than zero to `STRANDED` when its product has been `DISCONTINUED` for at least ninety days; stranding stamps `stranded_at` and cancels every `OPEN` allocation against the lot, releasing the reserved units back. From `STRANDED`, a `CreditOfficer` may write the lot off: the lot must be `STRANDED` (`ERR_LOT_NOT_STRANDED` otherwise) and must have `qty_allocated` at zero (`ERR_ALLOCATIONS_OUTSTANDING` otherwise); the write-off zeroes `qty_on_hand` and `qty_quarantined` and recognizes the loss on the distribution ledger without touching any other entity. `DEPLETED` and `WRITTEN_OFF` are terminal. Lots can be listed filtered by `product_id` and `status`.

### 3.4. Landed Cost: Provisional Estimates and Final Reconciliation

Landed cost is computed as a waterfall over the container's lines, processed in the order the lines were created — by `created_at` ascending, then by line index for lines created in the same instant. For each line, the base cost is the booked quantity multiplied by the declared per-unit customs value. The duty is the base cost multiplied by the applicable `duty_rate_bp` and divided by ten thousand, rounded half up to a whole cent. The freight share is the container's total `freight_cost_cents` multiplied by the proportion that this line's base cost bears to the total declared value across all of the container's lines, rounded half up; the insurance share is the same construction over `insurance_cost_cents`, also rounded half up. The landed total is the sum of the base cost, the duty, the freight share, and the insurance share.

The two variants differ in tariff selection and denominator. The **final** landed cost, computed at receipt and stored as `unit_cost_cents_final`, uses the tariff rate effective at the container's `actual_arrival_utc` (window and tie-breaking per §3.1) and divides the landed total by the line's *received* quantity — not the booked quantity — rounding half up to a whole cent. The **provisional** landed cost, computed at booking time and refreshed by pre-receipt edits, is stored as `unit_cost_cents_provisional`; it uses the tariff rate effective at the container's booking time (its `created_at`), applies the same freight and insurance waterfall against the total declared value across all lines, and divides by the booked quantity, since the received count is unknowable before receipt. Provisional and final figures therefore diverge exactly when the tariff rate changed between booking and arrival, or when the received quantity differs from the booked quantity because of damage or short shipment.

### 3.5. Project Design and the Compatibility Gate

An installer project begins when an `InstallerRep` (for their own installer only) or a `ChannelManager` creates it with a `project_name`, the job-site `site_postal_code` that drives the permitting jurisdiction, the chosen `module_product_id` and `inverter_product_id`, and the `module_qty` and `inverter_qty` of the design. The owning installer must be `ACTIVE`, failing with `ERR_INSTALLER_NOT_ACTIVE` otherwise. A new project starts with `fulfillment_status` `DESIGN` and `payment_status` `UNBILLED`. Projects are listed per installer, and a top-level listing spans installers with filters on `installer_id`, `module_product_id`, `inverter_product_id`, `compatibility_rule_id`, `fulfillment_status`, and `payment_status`.

Locking the design runs the compatibility gate. The system looks for an `ACTIVE` compatibility rule whose `module_product_id` and `inverter_product_id` equal the project's choices and whose window covers the current instant — `effective_from` at or before now, and either open-ended or `effective_to` strictly after now; when several rules match, the one with the latest `effective_from` wins, with ties broken by the most recently created rule. If no rule covers the pair, the lock is rejected with `ERR_NO_COMPATIBILITY_RULE`. If a rule covers the pair, the string size is checked: the project's `module_qty` must be at least the rule's `min_modules_per_inverter` multiplied by the project's `inverter_qty`, and at most the rule's `max_modules_per_inverter` multiplied by `inverter_qty`; falling outside those bounds fails with `ERR_STRING_SIZE_VIOLATION`. If either the chosen module or the chosen inverter is not `ACTIVE`, the lock fails with `ERR_PRODUCT_NOT_ACTIVE`. A successful lock pins the winning rule's id into the project's `compatibility_rule_id` — immutable thereafter — stamps `design_locked_at`, computes `system_size_kw_dc` as the total module nameplate DC watts of the design divided by one thousand, and automatically creates the project's permit package in `ASSEMBLING` with `required_documents` derived from the module and inverter product documentation (§3.8).

Cancellation is open to an `InstallerRep` (own projects) or a `ChannelManager` while the project's `fulfillment_status` is `DESIGN` or `ALLOCATED`; from any later state the attempt fails with `ERR_PROJECT_NOT_CANCELLABLE`, and if any allocation has already `SHIPPED` the attempt fails with `ERR_SHIPPED_ALLOCATIONS_EXIST`. Cancelling moves the project to `CANCELLED`, terminal, and cascades: every `OPEN` allocation on the project moves to `CANCELLED` with its reserved units released on each lot, and the project's `allocated_value_cents` recomputes to zero.

The fulfillment dimension otherwise advances on its own. A project whose design is locked moves `DESIGN` → `ALLOCATED` as soon as at least one allocation exists in `OPEN`. It moves `ALLOCATED` → `PARTIALLY_SHIPPED` when at least one allocation has shipped while at least one remains `OPEN`, and `ALLOCATED` → `SHIPPED` when every non-cancelled allocation has shipped — the moment that also issues the progress invoice (§3.7). From `PARTIALLY_SHIPPED`, the project reaches `SHIPPED` when its last `OPEN` allocation ships, issuing the progress invoice if that has not yet happened and otherwise doing nothing further. `COMPLETE` and `CANCELLED` are terminal.

### 3.6. Allocating Inventory and Shipping the Project

Placing an allocation — the act that reserves warehouse units to a project — is open to an `InstallerRep` on their own projects and to a `ChannelManager`, and its payload carries the target `inventory_lot_id`, the `qty_allocated` to reserve, and the `expected_lot_version` concurrency guard. The checks land in the §2.9 order: the project's design must be locked, failing with `ERR_DESIGN_NOT_LOCKED` while it is not; the referenced lot must exist with its foreign-key chain intact and non-terminal; the credit gate then requires that the installer not be on `credit_hold` and that the installer's current `credit_exposure_cents` plus the prospective allocation's value — the requested units priced at the lot's `unit_cost_cents_provisional` — remain strictly below `credit_limit_cents`, failing with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) at equality or beyond; the availability check then requires the lot's `qty_available` to be at least the requested `qty_allocated`, failing with `ERR_INSUFFICIENT_QTY` otherwise; and the stale-version guard of §2.8 runs last. On success the allocation starts `OPEN` with `allocated_at` stamped; its `unit_cost_cents_at_allocation` freezes to the lot's `unit_cost_cents_final` when that is set and to `unit_cost_cents_provisional` otherwise, and the snapshot is immutable thereafter; the lot's `qty_allocated` increases by the reserved quantity; the project's `allocated_value_cents` recomputes; if the design is locked and this is the project's first `OPEN` allocation, fulfillment moves `DESIGN` → `ALLOCATED`; the installer's `credit_hold` is re-evaluated; and the lot's `version` increments by 1.

A project's `allocated_value_cents` is the sum, over its allocations in `OPEN` or `SHIPPED`, of each allocation's `qty_allocated` multiplied by its frozen `unit_cost_cents_at_allocation`. The figure refreshes on allocation create, ship, release, and cancel, and again at container receipt when final costs replace provisional ones going forward. Allocations are listed per project with a `status` filter, and a top-level listing is filterable by `project_id`, `inventory_lot_id`, and `status`.

Shipping is a `DistributionAdmin` action on an `OPEN` allocation — anything else fails with `ERR_ALLOCATION_NOT_OPEN`. The lot must be `ON_HAND` (`ERR_LOT_NOT_ON_HAND` otherwise), and it must still be able to back the shipment at ship time (`ERR_INSUFFICIENT_QTY` otherwise): because the units that leave the building are exactly the units this allocation has reserved, the allocation's own reservation counts toward availability for this check — the ship is rejected only when the lot's `qty_available`, with this allocation's own `qty_allocated` added back, is still less than the allocation's `qty_allocated`, equivalently only when the lot's `qty_available` has been driven below zero. Shipping stamps `shipped_at`, moves the allocation `OPEN` → `SHIPPED`, and decreases both the lot's `qty_on_hand` and its `qty_allocated` by the shipped quantity — the units leave the building and the reservation is released at once. The project's `allocated_value_cents` recomputes, with the allocation now contributing through the shipped path, and the project's `fulfillment_status` re-evaluates to `PARTIALLY_SHIPPED` or `SHIPPED` per §3.5 — reaching `SHIPPED` cascades into progress-invoice issue. The lot's `version` and the allocation's `version` each increment by 1.

Release is the inverse gesture, open to an `InstallerRep` on their own projects and to a `ChannelManager`, and likewise requires an `OPEN` allocation (`ERR_ALLOCATION_NOT_OPEN` otherwise). Releasing moves the allocation to `RELEASED`, stamps `released_at`, decreases the lot's `qty_allocated` by the released quantity so the units return to the available pool, recomputes the project's `allocated_value_cents`, and increments the lot's `version` by 1.

Allocations also move `OPEN` → `CANCELLED` without any client call, cascaded from four sources covered elsewhere: the parent project's cancellation, the owning installer's suspension or termination, the product's obsolescence sweep, and the lot's stranding. Each such cancellation decreases the lot's `qty_allocated` by the allocation's quantity and recomputes the project's `allocated_value_cents`. `SHIPPED`, `RELEASED`, and `CANCELLED` are all terminal.

### 3.7. Progress Billing, Payments, and Debt Workout

When a project's fulfillment reaches `SHIPPED`, the system issues its progress invoice. The invoice's `amount_cents` is the project's `allocated_value_cents` at issue time — computed from shipped allocations' frozen `unit_cost_cents_at_allocation` values, each of which reflects the lot's final unit cost when set and its provisional cost otherwise — multiplied by the installer's `progress_payment_pct_bp` and divided by ten thousand, rounded half up to a whole cent. Issuing the invoice moves `payment_status` `UNBILLED` → `PROGRESS_BILLED`. Every invoice carries its `project_id` and a denormalized `installer_id` for the credit ledger; an `invoice_kind` of `PROGRESS`, `PTO`, `CREDIT_MEMO`, or `WRITE_OFF`; an `invoice_date` stamped at issue; a `due_date` computed as `invoice_date` plus the installer's `payment_terms_days` — recomputed if the installer's terms change before the invoice is issued; and a `balance_due_cents` that starts at `amount_cents` and falls as posted payments land. `PROGRESS` and `PTO` amounts are system-computed; `CREDIT_MEMO` and `WRITE_OFF` amounts are supplied by the issuer. New invoices are `OPEN`. Invoices are listed per project and per installer — the latter being the credit-ledger view — each filterable by `status` and `invoice_kind`, and a top-level listing adds filters on `project_id` and `installer_id`.

The permission-to-operate invoice is issued by a `ChannelManager` and requires three conditions: the project's `payment_status` must be `PROGRESS_BILLED` (otherwise `ERR_PROGRESS_NOT_BILLED`), the project's permit package must be `APPROVED` (otherwise `ERR_PERMIT_NOT_APPROVED`), and `fulfillment_status` must be `SHIPPED`. The PTO amount is the remainder — the project's `allocated_value_cents` minus the progress invoice amount — not a second percentage computation, so the two invoices sum exactly to the allocated value and any rounding residue lands on the PTO invoice. Issuing it moves `payment_status` `PROGRESS_BILLED` → `PTO_BILLED` and recomputes the installer's `credit_exposure_cents`.

Payments are posted by an `InstallerRep` against their own installer's invoices, or by a `CreditOfficer`, with a payload of `amount_cents`. The amount must be greater than zero and no more than the invoice's current `balance_due_cents` at post time, failing with `ERR_INVALID_PAYMENT_AMOUNT` otherwise, and the invoice must not be `VOID`, failing with `ERR_INVOICE_VOID`. A posted payment stamps `posted_at`, holds status `POSTED`, and reduces the invoice's `balance_due_cents` by its amount. The first partial payment moves the invoice `OPEN` → `PARTIALLY_PAID`; any posted payment that brings the balance to zero moves it to `PAID` from `OPEN`, `PARTIALLY_PAID`, or `PAST_DUE` alike. Each posting recomputes the installer's `credit_exposure_cents` and the project's `paid_value_cents` — the sum of `amount_cents` over the project's posted payments — and re-evaluates the project's `payment_status`: from `PTO_BILLED` it advances to `PAID_IN_FULL` when the posted payments across all of the project's invoices equal `invoiced_value_cents` and that invoiced value is greater than zero. A project can also reach `PAID_IN_FULL` directly from `PROGRESS_BILLED`: when a full RMA credit has reduced its `allocated_value_cents` to zero and every one of its invoices is `PAID` or `VOID`, the dimension closes itself. A project's `invoiced_value_cents` is the sum of `amount_cents` over its invoices that have not reached a terminal state — those in `OPEN`, `PARTIALLY_PAID`, or `PAST_DUE` — and refreshes on invoice issue and void. Payments are listed per invoice, and a top-level listing is filterable by `invoice_id` and `status`.

Time works against open invoices. An invoice in `OPEN` or `PARTIALLY_PAID` whose `due_date` has passed while `balance_due_cents` remains greater than zero moves to `PAST_DUE` automatically, and the installer's `credit_hold` is re-evaluated — though the hold's rule does not change: past-due is a state, not a separate hold. A `PAST_DUE` invoice is still payable to `PAID` on the same zero-balance condition.

A `CreditOfficer` may void an invoice that is `OPEN` with no payments posted — its `balance_due_cents` still equal to its `amount_cents`. Voiding moves it to `VOID`, terminal, and recomputes both the installer's `credit_exposure_cents` and the project's `invoiced_value_cents`.

Reversal unwinds a payment. A `CreditOfficer` may reverse a payment only while it is `POSTED` (`ERR_PAYMENT_NOT_POSTED` otherwise), and the server refuses the reversal when the invoice stands `PAID` with every other payment on it already `REVERSED`, since that would drive the project's `paid_value_cents` negative. A reversal stamps `reversed_at`, moves the payment to `REVERSED`, terminal, adds its amount back to the invoice's `balance_due_cents`, reverts an invoice that had been `PAID` to `PARTIALLY_PAID` or `OPEN` according to the remaining balance, and recomputes the installer's `credit_exposure_cents`, the project's `paid_value_cents`, and the project's `payment_status`.

When an installer is `SUSPENDED` or `TERMINATED` and a project still carries an outstanding balance greater than zero, a `CreditOfficer` may write the project off. The write-off issues a `WRITE_OFF` invoice exactly equal to the outstanding balance, offsetting it to zero net recognized; moves `payment_status` from `PROGRESS_BILLED` or `PTO_BILLED` to `WRITTEN_OFF`; and recomputes the installer's `credit_exposure_cents` — from which the write-off invoice itself is excluded by the exposure rule of §3.2.

### 3.8. Permitting and Project Completion

Design lock creates the project's permit package automatically, in `ASSEMBLING`. The package records the `ahj_code` — the Authority Having Jurisdiction, the city or county permit office for the jurisdiction that the project's `site_postal_code` implies — together with `required_documents`, the list of document slugs this AHJ demands, derived at creation from the module and inverter product documentation; `submitted_documents`, the slugs uploaded so far, initially empty; and `submitted_at` and `approved_at`, both null until their events. Packages are listed per project, and a top-level listing is filterable by `project_id` and `status`.

An `InstallerRep` assembles the package document by document: each upload names one `document_slug`, which is appended to `submitted_documents`, and re-uploading a slug already present is idempotent — the list does not duplicate it.

Submission moves the package `ASSEMBLING` → `SUBMITTED` and stamps `submitted_at`. It requires the project's design to be locked, failing with `ERR_DESIGN_NOT_LOCKED` while `design_locked_at` is null, and requires `submitted_documents` to cover every entry in `required_documents`, failing with `ERR_MISSING_REQUIRED_DOCS` on any gap.

Adjudication is a `ChannelManager` action. Approval requires a `SUBMITTED` package (`ERR_PACKAGE_NOT_SUBMITTED` otherwise), moves it to `APPROVED`, and stamps `approved_at`; approval is what makes the project's PTO billing path eligible. Rejection likewise requires `SUBMITTED` and moves the package to `REJECTED`. From `REJECTED`, an `InstallerRep` may reassemble the package back into `ASSEMBLING`: `submitted_at` is cleared, the accumulated `submitted_documents` are preserved, and `required_documents` is recomputed if the design has changed in the meantime. An `InstallerRep` may instead withdraw a package from `ASSEMBLING` or `REJECTED`, moving it to `WITHDRAWN`, terminal.

Completion is the project's final milestone and belongs to the `InstallerRep`. It requires `fulfillment_status` `SHIPPED`, `payment_status` `PAID_IN_FULL` — failing with `ERR_UNPAID_BALANCE` while any balance stands — and an `APPROVED` permit package, failing with `ERR_PERMIT_NOT_APPROVED` otherwise. On success the project's `fulfillment_status` moves `SHIPPED` → `COMPLETE`, terminal.

### 3.9. Warranty Returns and In-Transit Damage Claims

An RMA claim begins when an `InstallerRep` creates one with the claiming `installer_id` — which must equal the caller's `X-User-ID` — the defective `product_id`, the `allocation_id` of the shipped allocation that delivered the units, and the `qty_claimed`. A new claim is `DRAFT`, and the claims listing is filterable by `installer_id`, `product_id`, `allocation_id`, and `status`.

Submitting the claim to the manufacturer requires the referenced allocation to be `SHIPPED` (`ERR_ALLOCATION_NOT_SHIPPED` otherwise) and requires `qty_claimed` to be greater than zero and no more than the quantity on that allocation (`ERR_INVALID_QTY_CLAIMED` otherwise). Submission moves the claim `DRAFT` → `SUBMITTED`, and the issuer may populate `manufacturer_rma_number` at this point; it otherwise stays null until the manufacturer responds.

A `ChannelManager` adjudicates a `SUBMITTED` claim — either action fails with `ERR_RMA_NOT_SUBMITTED` on a claim in any other state. Approval supplies the `qty_approved`, which must be greater than zero and no more than `qty_claimed`, and may carry the `manufacturer_rma_number`; it sets `qty_approved`, computes the claim's `credit_amount_cents` as the approved quantity multiplied by the allocation's frozen `unit_cost_cents_at_allocation` — snapshot pricing, the price the installer actually paid rather than any current replacement cost — and moves the claim to `APPROVED`. Rejection moves the claim to `REJECTED`, terminal.

Credit issuance belongs to the `CreditOfficer` and requires an `APPROVED` claim (`ERR_RMA_NOT_APPROVED` otherwise). Issuing credit creates an invoice with `invoice_kind` `CREDIT_MEMO` whose `amount_cents` is the negative of the claim's `credit_amount_cents`, then applies that credit against the installer's open invoices — those in `OPEN`, `PARTIALLY_PAID`, or `PAST_DUE` — oldest first, ordered by `invoice_date` ascending and then `created_at` ascending, reducing each target invoice's `balance_due_cents` but never below zero; any residual credit remains standing as a negative-balance invoice. The claim moves to `CREDIT_ISSUED`, the installer's `credit_exposure_cents` recomputes, and the project's `allocated_value_cents` is deliberately *not* adjusted: the units have already shipped, so this is a credit, not a return to stock. Closing the claim — `CREDIT_ISSUED` → `CLOSED`, terminal — is likewise a `CreditOfficer` action.

Damage claims run against a container, not an installer. A `DistributionAdmin` creates one by naming the `container_line_id` with the damage and the `qty_damaged`; the claim starts `DRAFT`. Filing it requires the container to be `RECEIVED` (`ERR_CONTAINER_NOT_RECEIVED` otherwise) and requires the claim's `qty_damaged` to equal exactly the `qty_damaged` recorded on the container line at receipt (`ERR_CLAIM_QTY_MISMATCH` otherwise). Filing stamps `filed_at`, moves the claim `DRAFT` → `FILED`, and computes its `claimed_amount_cents`: the freight per unit is the container's total `freight_cost_cents` divided by the total booked units across all of its lines, rounded half up to a whole cent, and the claim amount is the damaged quantity multiplied by the sum of the line's `declared_unit_value_cents` and that freight-per-unit figure. Marine insurance is deliberately excluded from damage claims — the claim recovers base value plus freight only.

Resolution belongs to the `CreditOfficer` and requires a `FILED` claim (`ERR_CLAIM_NOT_FILED` otherwise). Settling stamps `settled_at`, moves the claim to `SETTLED`, and removes the damaged units from the warehouse without returning them to sellable stock: the lot's `qty_quarantined` and `qty_on_hand` each decrease by the claim's `qty_damaged`. Denying moves the claim to `DENIED` and applies the same two decrements — the units are written off as shrinkage either way. `SETTLED` and `DENIED` are terminal. Damage claims are listed per container with a `status` filter, and a top-level listing adds filters on `container_id` and `container_line_id`.

## 4. Endpoint Definitions

Operations that create a new resource in a collection return a `201 Created` status code — this covers products, compatibility rules, tariff rates, installers, containers, container lines, projects, allocations, payments, RMA claims, and damage claims. Operations that modify an existing resource or drive a state transition return `200 OK`, even when the transition causes a new resource (such as an invoice issued by the PTO, write-off, or credit-issuance workflows) to be created as a side effect. All read endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/solar-dist/_clock/set_current_utc` | Advance the server's logical UTC clock | DistributionAdmin |
| POST | `/solar-dist/products` | Create a product | DistributionAdmin |
| GET | `/solar-dist/products` | List products, with optional filters | All roles |
| GET | `/solar-dist/products/{productId}` | Get a product | All roles |
| POST | `/solar-dist/products/{productId}/discontinue` | Discontinue a product; retires its active compatibility rules | DistributionAdmin |
| POST | `/solar-dist/compatibility-rules` | Create a module–inverter compatibility rule | DistributionAdmin |
| GET | `/solar-dist/compatibility-rules` | List compatibility rules | All roles |
| GET | `/solar-dist/compatibility-rules/{ruleId}` | Get a compatibility rule | All roles |
| POST | `/solar-dist/compatibility-rules/{ruleId}/retire` | Retire a compatibility rule | DistributionAdmin |
| POST | `/solar-dist/tariff-rates` | Create a tariff rate | DistributionAdmin |
| GET | `/solar-dist/tariff-rates` | List tariff rates | All roles |
| GET | `/solar-dist/tariff-rates/{rateId}` | Get a tariff rate | All roles |
| POST | `/solar-dist/installers` | Create an installer in `ONBOARDING` | ChannelManager |
| GET | `/solar-dist/installers` | List installers | All roles |
| GET | `/solar-dist/installers/{installerId}` | Get an installer | All roles |
| POST | `/solar-dist/installers/{installerId}/activate` | Activate an installer | ChannelManager |
| POST | `/solar-dist/installers/{installerId}/suspend` | Suspend an installer; cancels their open allocations | CreditOfficer |
| POST | `/solar-dist/installers/{installerId}/reinstate` | Reinstate a suspended installer | CreditOfficer |
| POST | `/solar-dist/installers/{installerId}/terminate` | Terminate an installer with zero exposure and no in-flight projects | CreditOfficer |
| POST | `/solar-dist/containers` | Book a container | DistributionAdmin |
| GET | `/solar-dist/containers` | List containers | All roles |
| GET | `/solar-dist/containers/{containerId}` | Get a container | All roles |
| PATCH | `/solar-dist/containers/{containerId}` | Update container ETA or cost figures while `BOOKED` or `IN_TRANSIT` | DistributionAdmin |
| POST | `/solar-dist/containers/{containerId}/depart` | Mark container departed from origin | DistributionAdmin |
| POST | `/solar-dist/containers/{containerId}/arrive` | Mark container arrived at destination port | DistributionAdmin |
| POST | `/solar-dist/containers/{containerId}/receive` | Receive a container: reconcile lines, compute final landed cost, move lots to `ON_HAND` | DistributionAdmin |
| POST | `/solar-dist/containers/{containerId}/close` | Close a received container after all damage claims resolve | DistributionAdmin |
| POST | `/solar-dist/containers/{containerId}/cancel` | Cancel a booked container | DistributionAdmin |
| POST | `/solar-dist/containers/{containerId}/lines` | Add a container line; provisions the corresponding inventory lot | DistributionAdmin |
| GET | `/solar-dist/containers/{containerId}/lines` | List lines on a container | All roles |
| GET | `/solar-dist/containers/{containerId}/lines/{lineId}` | Get a container line | All roles |
| GET | `/solar-dist/container-lines` | List all container lines, filterable | All roles |
| GET | `/solar-dist/container-lines/{lineId}` | Get a container line by id | All roles |
| GET | `/solar-dist/inventory-lots` | List inventory lots | All roles |
| GET | `/solar-dist/inventory-lots/{lotId}` | Get an inventory lot | All roles |
| POST | `/solar-dist/inventory-lots/{lotId}/write-off` | Write off a stranded lot | CreditOfficer |
| POST | `/solar-dist/installers/{installerId}/projects` | Create a project in `DESIGN` | InstallerRep, ChannelManager |
| GET | `/solar-dist/installers/{installerId}/projects` | List an installer's projects | All roles |
| GET | `/solar-dist/projects/{projectId}` | Get a project | All roles |
| GET | `/solar-dist/projects` | List all projects across installers, filterable | All roles |
| POST | `/solar-dist/projects/{projectId}/lock-design` | Lock the design: compatibility gate, rule pinning, system size, permit package creation | InstallerRep, ChannelManager |
| POST | `/solar-dist/projects/{projectId}/cancel` | Cancel a project in `DESIGN` or `ALLOCATED` | InstallerRep, ChannelManager |
| POST | `/solar-dist/projects/{projectId}/complete` | Mark a shipped, fully paid, permit-approved project complete | InstallerRep |
| POST | `/solar-dist/projects/{projectId}/invoice-pto` | Issue the permission-to-operate invoice for the remainder | ChannelManager |
| POST | `/solar-dist/projects/{projectId}/write-off` | Write off a project's outstanding balance | CreditOfficer |
| POST | `/solar-dist/projects/{projectId}/allocations` | Create an allocation against an inventory lot | InstallerRep, ChannelManager |
| GET | `/solar-dist/projects/{projectId}/allocations` | List allocations on a project | All roles |
| GET | `/solar-dist/allocations/{allocationId}` | Get an allocation | All roles |
| GET | `/solar-dist/allocations` | List all allocations, filterable | All roles |
| POST | `/solar-dist/allocations/{allocationId}/ship` | Ship an open allocation | DistributionAdmin |
| POST | `/solar-dist/allocations/{allocationId}/release` | Release an open allocation back to the available pool | InstallerRep, ChannelManager |
| GET | `/solar-dist/projects/{projectId}/invoices` | List invoices on a project | All roles |
| GET | `/solar-dist/installers/{installerId}/invoices` | List an installer's invoices (credit ledger view) | All roles |
| GET | `/solar-dist/invoices/{invoiceId}` | Get an invoice | All roles |
| GET | `/solar-dist/invoices` | List all invoices, filterable | All roles |
| POST | `/solar-dist/invoices/{invoiceId}/void` | Void an open invoice with no payments posted | CreditOfficer |
| POST | `/solar-dist/invoices/{invoiceId}/payments` | Post a payment against an invoice | InstallerRep, CreditOfficer |
| GET | `/solar-dist/invoices/{invoiceId}/payments` | List payments on an invoice | All roles |
| GET | `/solar-dist/payments/{paymentId}` | Get a payment | All roles |
| GET | `/solar-dist/payments` | List all payments, filterable | All roles |
| POST | `/solar-dist/payments/{paymentId}/reverse` | Reverse a posted payment | CreditOfficer |
| POST | `/solar-dist/rma-claims` | Create an RMA claim in `DRAFT` | InstallerRep |
| GET | `/solar-dist/rma-claims` | List RMA claims | All roles |
| GET | `/solar-dist/rma-claims/{rmaId}` | Get an RMA claim | All roles |
| POST | `/solar-dist/rma-claims/{rmaId}/submit` | Submit a draft claim to the manufacturer | InstallerRep |
| POST | `/solar-dist/rma-claims/{rmaId}/approve` | Approve a submitted claim on manufacturer response | ChannelManager |
| POST | `/solar-dist/rma-claims/{rmaId}/reject` | Reject a submitted claim | ChannelManager |
| POST | `/solar-dist/rma-claims/{rmaId}/issue-credit` | Issue the credit memo against the installer's open invoices | CreditOfficer |
| POST | `/solar-dist/rma-claims/{rmaId}/close` | Close a credit-issued claim | CreditOfficer |
| GET | `/solar-dist/projects/{projectId}/permit-packages` | List permit packages for a project | All roles |
| GET | `/solar-dist/permit-packages/{packageId}` | Get a permit package | All roles |
| GET | `/solar-dist/permit-packages` | List all permit packages, filterable | All roles |
| POST | `/solar-dist/permit-packages/{packageId}/documents` | Upload a document to the package | InstallerRep |
| POST | `/solar-dist/permit-packages/{packageId}/submit` | Submit the package to the AHJ | InstallerRep |
| POST | `/solar-dist/permit-packages/{packageId}/approve` | Mark the package approved by the AHJ | ChannelManager |
| POST | `/solar-dist/permit-packages/{packageId}/reject` | Mark the package rejected by the AHJ | ChannelManager |
| POST | `/solar-dist/permit-packages/{packageId}/reassemble` | Re-open a rejected package | InstallerRep |
| POST | `/solar-dist/permit-packages/{packageId}/withdraw` | Withdraw an assembling or rejected package | InstallerRep |
| POST | `/solar-dist/containers/{containerId}/damage-claims` | Create a damage claim against a container line | DistributionAdmin |
| GET | `/solar-dist/containers/{containerId}/damage-claims` | List damage claims on a container | All roles |
| GET | `/solar-dist/damage-claims/{claimId}` | Get a damage claim | All roles |
| GET | `/solar-dist/damage-claims` | List all damage claims, filterable | All roles |
| POST | `/solar-dist/damage-claims/{claimId}/file` | File a draft damage claim | DistributionAdmin |
| POST | `/solar-dist/damage-claims/{claimId}/settle` | Settle a filed damage claim | CreditOfficer |
| POST | `/solar-dist/damage-claims/{claimId}/deny` | Deny a filed damage claim | CreditOfficer |

In the table above, "All roles" means any of the four roles defined in §2.1 — `DistributionAdmin`, `ChannelManager`, `InstallerRep`, and `CreditOfficer` — may perform the read.

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PROGRESS_PCT` | 400 Bad Request |
| `ERR_INVALID_PAYMENT_TERMS` | 400 Bad Request |
| `ERR_CREDIT_LIMIT_REQUIRED` | 400 Bad Request |
| `ERR_INVALID_QTY_CLAIMED` | 422 Unprocessable Entity |
| `ERR_INVALID_PAYMENT_AMOUNT` | 422 Unprocessable Entity |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_RULE_NOT_FOUND` | 404 Not Found |
| `ERR_TARIFF_NOT_FOUND` | 404 Not Found |
| `ERR_INSTALLER_NOT_FOUND` | 404 Not Found |
| `ERR_CONTAINER_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RMA_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_ACTIVE` | 409 Conflict |
| `ERR_RULE_NOT_ACTIVE` | 409 Conflict |
| `ERR_RULE_IN_USE` | 409 Conflict |
| `ERR_INSTALLER_NOT_ACTIVE` | 409 Conflict |
| `ERR_INSTALLER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_CONTAINER_NOT_BOOKED` | 409 Conflict |
| `ERR_CONTAINER_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_CONTAINER_NOT_ARRIVED` | 409 Conflict |
| `ERR_CONTAINER_NOT_RECEIVED` | 409 Conflict |
| `ERR_CONTAINER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_CONTAINER_NOT_UPDATABLE` | 409 Conflict |
| `ERR_RECEIPT_QTY_MISMATCH` | 409 Conflict |
| `ERR_LOT_NOT_ON_HAND` | 409 Conflict |
| `ERR_LOT_NOT_STRANDED` | 409 Conflict |
| `ERR_ALLOCATIONS_OUTSTANDING` | 409 Conflict |
| `ERR_PROJECT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SHIPPED_ALLOCATIONS_EXIST` | 409 Conflict |
| `ERR_ALLOCATION_NOT_OPEN` | 409 Conflict |
| `ERR_ALLOCATION_NOT_SHIPPED` | 409 Conflict |
| `ERR_PROGRESS_NOT_BILLED` | 409 Conflict |
| `ERR_PERMIT_NOT_APPROVED` | 409 Conflict |
| `ERR_UNPAID_BALANCE` | 409 Conflict |
| `ERR_INVOICE_VOID` | 409 Conflict |
| `ERR_PAYMENT_NOT_POSTED` | 409 Conflict |
| `ERR_RMA_NOT_SUBMITTED` | 409 Conflict |
| `ERR_RMA_NOT_APPROVED` | 409 Conflict |
| `ERR_PACKAGE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_DESIGN_NOT_LOCKED` | 409 Conflict |
| `ERR_CLAIM_NOT_FILED` | 409 Conflict |
| `ERR_CLAIM_QTY_MISMATCH` | 409 Conflict |
| `ERR_OPEN_DAMAGE_CLAIMS` | 409 Conflict |
| `ERR_OUTSTANDING_BALANCE` | 402 Payment Required |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_INSUFFICIENT_QTY` | 409 Conflict |
| `ERR_NO_COMPATIBILITY_RULE` | 422 Unprocessable Entity |
| `ERR_STRING_SIZE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_MISSING_REQUIRED_DOCS` | 422 Unprocessable Entity |
| `ERR_TARIFF_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CONTAINER_VERSION` | 412 Precondition Failed |

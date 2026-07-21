# Natural-Grocery Coop API — Product Requirements Document

## 1. Introduction

The Natural-Grocery & Consumer Co-op API is the operational backbone of a member-owned grocery cooperative. Unlike a conventional retailer, a co-op weaves together three concerns that are normally kept apart: the retail floor (a point-of-sale system pricing bulk bins by net weight, honoring weekly ads and member-only deals, and drawing down direct-store-delivery inventory), the member-owner relationship (equity shares, patronage-eligible spend, working-member volunteer standing, and the year-end patronage dividend), and cooperative governance (a board that drafts, debates, and votes proposals under quorum rules). Each of these touches the others: a checkout accrues patronage that later becomes a dividend; a dividend retains part of itself back into member equity; a volunteer shift earns a standing discount that changes the price rung at the register.

This document specifies the complete contract for that system. It defines how fiscal years open and close, how members move from prospective to active to lapsed, how inventory flows from an approved vendor's delivery through the shelf to a sale or a shrink write-off, and how surplus is distributed at year end. Because so many quantities are conserved — total equity across members, units across a lot's lifetime, patronage across the fiscal year — the specification is precise about the exact cascade each operation triggers and the exact order in which validations are evaluated. Downstream implementations are expected to reproduce these rules faithfully; the narrative below is the single source of truth.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting invariants that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes six roles, spelled exactly as follows: `CoopAdmin`, `FinanceManager`, `InventoryManager`, `Cashier`, `BoardAdmin`, and `Member`. When a role is authenticated but not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

Five of these roles are operator roles whose identity is opaque. When `X-User-Role` is `CoopAdmin`, `FinanceManager`, `InventoryManager`, `Cashier`, or `BoardAdmin`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it but never compares it to any resource's `id`. The `Member` role is different: its identity is entity-backed. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`, and any operation that acts on that member's own behalf compares the referenced member to `X-User-ID`. In particular, when a member casts a board vote, the `member_id` supplied in the request body must equal the `X-User-ID` of the caller; a mismatch is an authorization failure.

Read operations (all `GET` endpoints) are available to every role. Write operations are partitioned by role: co-op administration (fiscal-year creation, member registration, approval, and dropping) belongs to `CoopAdmin`; finance operations (fiscal-year close, equity contributions, and patronage allocation) belong to `FinanceManager`; merchandising (vendors, products, inventory lots, promotions, and shrink) belongs to `InventoryManager`; point-of-sale operations belong to `Cashier`; governance operations belong to `BoardAdmin`; and members schedule their own working shifts and cast their own votes. Working-shift scheduling is shared between `Member` and `CoopAdmin`, and marking a shift complete is shared between `InventoryManager` and `CoopAdmin`. The exact authorized role(s) for each endpoint appear in the table in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are ordered by their creation timestamp (`created_at`) in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every entity in this system — fiscal years, members, vendors, products, inventory lots, registers, sales, promotions, working shifts, board proposals, and patronage allocations — is a top-level resource that carries a standard set of system-managed fields. Each has an `id`, a server-minted UUID that serves as identity only and carries no type prefix. Each has a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created, and an `updated_at`, an ISO 8601 UTC timestamp recording the most recent modification. Each also carries a `version`, an integer that begins at creation and increments by one on every mutation of the resource.

The `version` field is significant because many fields in this system are derived. When an operation recomputes a derived field on a resource — for example a product's `qty_on_hand_total` after a lot is posted, or a fiscal year's `total_equity_cents` after an equity contribution — that recomputation is a mutation: it refreshes `updated_at` and increments `version` on the resource whose derived field changed. A single business action can therefore mutate several resources at once, and each affected resource independently advances its own `version` and `updated_at`.

### 2.5. Monetary Amounts, Weights, and Rounding

All monetary quantities in this system are expressed as integer cents (for example `base_price_cents`, `equity_paid_in_cents`, `line_subtotal_cents`). Wherever a calculation multiplies a rate or a weight into a cent figure, the result is rounded to a whole number of cents using the round-half-up rule (a fractional half-cent rounds up). This applies to line pricing, tax, working-member discounts, patronage dividends, and retained-equity portions alike.

Weight-priced products are sold by net weight in kilograms. Gross weight is captured in grams; the net weight in grams is the gross weight less the product's container tare, and the billable quantity in kilograms is that net-gram figure divided by 1000. Volunteer shift durations are expressed in hours to two decimal places, computed from the elapsed time between the shift's start and end instants. Vote counts, quorum figures, and inventory unit counts are whole integers; where a quorum threshold requires a fractional member count it is rounded up to the next whole vote.

### 2.6. The Logical Clock and Time Windows

All time-window, expiry, and eligibility rules read a single server-maintained logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-07-01T00:00:00Z`, and it holds that value until it is explicitly set; it never silently falls back to the real-world time. An administrative test-driving capability lets a `CoopAdmin` set the clock to a supplied instant, provided in the `to_iso8601` field. Promotion windows, working-shift scheduling checks, and certification-style date comparisons all evaluate against whatever value the logical clock currently holds.

A promotion window is half-open: a promotion is active when the current clock is at or after its `start_date` and strictly before its `end_date`. The same half-open convention governs whether two promotion windows on the same product are considered to overlap.

### 2.7. Cascading Recalculation and Conserved Quantities

Several quantities in this system are invariants that must remain exactly conserved after every mutation, and the endpoints that touch them are specified as compensating pairs so the invariant never drifts.

**Member equity is conserved against the fiscal year.** At all times, the OPEN fiscal year's `total_equity_cents` equals the sum of `equity_paid_in_cents` over all members whose `membership_status` is not `DROPPED`. An equity contribution adds its amount to the member and to the fiscal year in lockstep; dropping a member subtracts that member's entire equity from the fiscal year and then zeroes the member's equity; and a finalized patronage dividend credits each member's retained portion to both the member and the fiscal year. Each of these is a matched pair that preserves the invariant exactly.

**Lot units are conserved across a lot's lifetime.** For every posted inventory lot, the received quantity equals the sum of the units still on hand, the units sold, and the units shrunk. Selling draws down on-hand and raises sold; refunding a sale reverses that exact movement; and a shrink write-off moves units from on-hand into shrunk. No operation may create or destroy units outside these movements.

**Patronage is conserved across the fiscal year.** When a member's patronage-eligible spend is accrued at sale finalize, the same amount is added to the OPEN fiscal year's `total_patronage_cents`; when that sale is refunded, both are decremented by the same amount.

Because product-level figures (`qty_on_hand_total`, `needs_reorder`, `inventory_value_cents`) are aggregates over a product's posted lots, they are recomputed automatically whenever any underlying lot changes — on lot posting, on sale finalize, on refund, and on shrink. The system performs these recomputations without a separate client request against the product.

### 2.8. Optimistic Concurrency for Patronage Allocation

Creating a patronage allocation is the one operation in this system guarded by optimistic concurrency control, because a fresh allocation run legitimately supersedes an earlier draft and advances the fiscal year's `version` as it does so. The create request must carry `expected_fiscal_year_version`, a non-optional field holding the `version` of the target fiscal year that the client last observed. If that value does not match the fiscal year's current `version` — because another allocation run has advanced it since the client last read it — the create is rejected with `ERR_STALE_FISCAL_YEAR_VERSION` at HTTP status 412, preventing a client from building a distribution on a fiscal-year view it has not actually seen. No other endpoint in this system accepts or requires a version field; only patronage-allocation creation performs this check.

### 2.9. Validation Ordering and Path Resolution

When several validations could apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) user-context headers are present and well-formed, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) the acting role is permitted for the operation, else `ERR_UNAUTHORIZED`; (3) every identifier in the path and every foreign key in the body resolves to an existing resource, checked left to right, else the corresponding not-found error; (4) the target resource and any gating resource are in the correct state for the transition, else the applicable state error; (5) business-safety — no line references a recalled product; (6) business-temporal — promotion windows must not overlap and working shifts must respect the rest buffer; (7) business-referential integrity — an approved vendor, a matching lot-and-product, an eligible voter; (8) business-constraint — one vote per proposal, quorum for tally, a single OPEN fiscal year, and the stale-version guard on allocation creation; and finally (9) fiscal scarcity — sufficient inventory, sufficient equity, and a present declared rate. Malformed bodies, missing required fields, or bad enum/type values are rejected with `ERR_INVALID_REQUEST`.

Path identifiers are resolved before body foreign keys, and both are resolved before any state or business rule runs. A request naming a nonexistent resource in its path fails with that resource's not-found error before the system inspects the body or the resource's state.

## 3. Business Logic & Workflows

### 3.1. Fiscal Years and the Membership Lifecycle

The fiscal year is the accounting frame for equity and patronage. A `CoopAdmin` opens a fiscal year by supplying its `year` label (for example 2026), an interim `patronage_rate` strictly between 0 and 1 (the server stores the supplied numeric value as given and does not itself reject a rate outside that open interval), and an `equity_share_price_cents` — the price of one member-owner equity share, which doubles as the minimum equity a member must have paid in to become active. A new fiscal year opens in `OPEN` status with `total_equity_cents` and `total_patronage_cents` both at zero. At most one fiscal year may be `OPEN` at any time; attempting to open a second while one is already `OPEN` is rejected with `ERR_OPEN_FISCAL_YEAR_EXISTS`.

Closing a fiscal year is a `FinanceManager` action that moves it from `OPEN` to `CLOSED`. Closing runs a participation sweep: every member who is `ACTIVE` but whose year-to-date patronage-eligible spend is below the minimum participation threshold of 5000 cents is transitioned from `ACTIVE` to `LAPSED`. Once closed, the year is read-only for accrual purposes — interim (`ESTIMATED`) allocations can no longer be created against it, while year-end (`FINAL`) allocations become creatable. A close may only be applied to a year that is `OPEN`.

A prospective member-owner is registered by a `CoopAdmin`, who supplies the member's `full_name`, `email`, and optionally whether the member `is_board_member` (defaulting to not a board member). Registration creates the member in `PENDING` status with `equity_paid_in_cents` at zero and assigns a `member_number`: a co-op-scoped integer beginning at 1 and handed out monotonically in creation order (earliest `created_at` first). A member also carries derived standing fields — `patronage_cents_ytd`, `working_hours_balance`, `is_working_member`, and `patronage_dividend_cents` — all beginning at their zero/false baselines.

Equity is accumulated through a `FinanceManager` recording an equity contribution against the OPEN fiscal year, supplying the `amount_cents` to add. A contribution raises the member's `equity_paid_in_cents` and the fiscal year's `total_equity_cents` by that same amount; it does not by itself change the member's `membership_status`. Equity contribution requires an OPEN fiscal year, else `ERR_FISCAL_YEAR_NOT_OPEN`.

Approving a member is a `CoopAdmin` action that moves a member from `PENDING` or `LAPSED` to `ACTIVE`; the same endpoint therefore serves both first-time approval and reactivation of a lapsed member. Two conditions gate it, evaluated in priority order: the member must currently be in `PENDING` or `LAPSED` (otherwise `ERR_MEMBER_NOT_APPROVABLE`), and the member's `equity_paid_in_cents` must be at least the `equity_share_price_cents` of the current or most-recent fiscal year, treated as zero when no fiscal year exists yet (otherwise `ERR_EQUITY_BELOW_SHARE_PRICE`). Becoming `ACTIVE` makes the member eligible to earn patronage and, if a board member, to vote. Separately, the close sweep described above is the system-driven path by which an `ACTIVE` member becomes `LAPSED`.

Dropping a member is a `CoopAdmin` action available from `PENDING`, `ACTIVE`, or `LAPSED`, moving the member to the terminal `DROPPED` status; dropping a member that is already `DROPPED` is an idempotent no-op that returns the member unchanged. Dropping refunds equity: when a fiscal year is OPEN its `total_equity_cents` is reduced by the member's `equity_paid_in_cents` (when no fiscal year is OPEN this reduction is skipped), and then the member's `equity_paid_in_cents` is set to zero — a compensating pair that keeps total equity equal to the sum over non-dropped members.

### 3.2. Vendors, Products, and DSD Receiving

Local vendors and direct-store-delivery suppliers are onboarded by an `InventoryManager`, who creates a vendor with a `name`. A vendor begins in `PENDING`. Through a set-status action the `InventoryManager` moves a vendor along its lifecycle by supplying the target `status`: `PENDING` may be approved to `APPROVED`, `APPROVED` may be suspended to `SUSPENDED`, and a `SUSPENDED` vendor may be restored to `APPROVED`. The supplied `status` must be `APPROVED` or `SUSPENDED` — any other value is rejected with `ERR_INVALID_REQUEST` — and it is applied regardless of the vendor's current status; no originating-state check is enforced.

Products (SKUs) are created by an `InventoryManager` with a supplying `vendor_id`, a `sku` code, a display `name`, a `department` (one of `GROCERY`, `PRODUCE`, `BULK`, or `CAFE_DELI`), a `unit_type`, a `base_price_cents`, a `reorder_point`, and a `reorder_qty`. Three flags are optional at creation: `tare_grams` (the container tare deducted from gross weight, defaulting to 0 and relevant only to weight items), `is_taxable` (defaulting to false), and `is_prepared_food` (defaulting to false; when true the product is not patronage-eligible). The `unit_type` is either `EACH`, meaning the product is priced per unit, or `WEIGHT`, meaning it is priced per kilogram of net weight after tare. A new product is `ACTIVE`, with `qty_on_hand_total` at zero and `needs_reorder` computed against its reorder point. Products also expose the derived `inventory_value_cents` and `last_shrink_cost_cents`, discussed in §3.3.

An `InventoryManager` updates a product's `base_price_cents`, `reorder_point`, `reorder_qty`, or `status`. The status field records the product state machine: an `ACTIVE` product may be recalled to `RECALLED`, a `RECALLED` product may be restored to `ACTIVE`, and a product that is `ACTIVE` or `RECALLED` may be discontinued to `DISCONTINUED`. The supplied status may be `ACTIVE`, `RECALLED`, or `DISCONTINUED` (any other value → `ERR_INVALID_REQUEST`) and is applied regardless of the product's current status; no originating-state check is enforced. A `RECALLED` product may not be added to a building sale and blocks that sale from finalizing, as a safety measure. A `DISCONTINUED` status is recorded but is not itself enforced elsewhere: such a product still accepts new lots, may have those lots posted, and may still have its price updated. When `reorder_point` changes, `needs_reorder` is recomputed.

Inventory arrives as lots. An `InventoryManager` records a direct-store-delivery lot by supplying the `product_id` it stocks, the `vendor_id` that delivered it, the `received_qty`, the `unit_cost_cents` (landed cost per unit), and optionally an `expiry_date` (defaulting to none). A new lot is in `DRAFT` and holds no shelf units yet. Posting a lot is a separate `InventoryManager` action that moves it from `DRAFT` to `POSTED`. Posting is gated by two conditions: the lot must be in `DRAFT` (else `ERR_LOT_NOT_DRAFT`) and the lot's vendor must be `APPROVED` (else `ERR_VENDOR_NOT_APPROVED`); the product's status is not checked at posting. On posting, the lot's `qty_on_hand` is set to its `received_qty`, while `qty_sold` and `qty_shrunk` are set to zero, and the product's `qty_on_hand_total`, `needs_reorder`, and `inventory_value_cents` are recomputed.

A product's `qty_on_hand_total` is the sum of `qty_on_hand` across its posted lots, and `needs_reorder` is true precisely when that total is at or below the product's `reorder_point` — the boundary flags at the point itself, not only below it. The product's `inventory_value_cents` is the sum, over its posted lots, of each lot's `qty_on_hand` multiplied by its `unit_cost_cents`. These three fields are re-derived on lot posting, on sale finalize, on refund, and on shrink.

### 3.3. Shrink and Inventory Valuation

Shrink and spoilage are recorded by an `InventoryManager`, who supplies the `quantity` of units to write off a product. The write-off consumes on-hand units from the product's posted lots oldest first — first-in, first-out, ordered by lot `created_at` ascending, never by identifier. Beginning with the oldest lot, the system takes the smaller of the remaining shrink quantity and that lot's `qty_on_hand`, adds the taken units multiplied by that lot's `unit_cost_cents` to a running cost, reduces the lot's `qty_on_hand` by the taken amount, increases its `qty_shrunk` by the same amount, and moves on to the next lot until the requested quantity is fully consumed. The accumulated cost becomes the product's `last_shrink_cost_cents`. After depletion, the product's `qty_on_hand_total`, `needs_reorder`, and `inventory_value_cents` are recomputed.

Two valuation bases coexist for the same units and must not be conflated. The applied write-off cost recorded in `last_shrink_cost_cents` is strictly the first-in-first-out figure described above — the sum over consumed lots of units taken times that lot's own `unit_cost_cents`. The reported `inventory_value_cents` metric, by contrast, is a weighted-average reference: it values on-hand units at the pooled cost across posted lots. For lots that differ in `unit_cost_cents`, these two bases yield different figures for the same physical shrink quantity, and each is used only for its stated purpose.

### 3.4. Weekly Ads, Member Deals, and Working-Member Standing

Promotions price a product for a bounded window. An `InventoryManager` creates a promotion by supplying the `product_id`, a `deal_type`, a `promo_price_cents` fixed unit price, a `start_date`, an `end_date`, and optionally `member_only`. The `deal_type` is either `AD` — a weekly ad available to everyone — or `MEMBER_DEAL`, a member-only deal. A `MEMBER_DEAL` sets `member_only` to true; such a deal applies only to active members and blocks the working-member discount described below. A new promotion may not overlap an existing promotion on the same product; because windows are half-open (active from `start_date` inclusive to `end_date` exclusive), two windows that merely abut at an instant do not overlap, but any true overlap is rejected with `ERR_PROMO_WINDOW_OVERLAP`.

Working-member standing is earned through volunteer shifts. A shift is scheduled either by the `Member` themselves or by a `CoopAdmin`, supplying the `member_id`, the `department` (one of `GROCERY`, `PRODUCE`, `BULK`, or `CAFE_DELI`), a `start_at`, and an `end_at`. A new shift is `SCHEDULED`, and its `hours` are computed as the elapsed time between start and end expressed in hours to two decimals; `end_at` must be strictly after `start_at`, else `ERR_INVALID_REQUEST`. A shift may not be scheduled too close in time to another of the same member's shifts: if the gap to any other shift is smaller than the mandated rest buffer of 60 minutes, the request is rejected with `ERR_SHIFT_OVERLAP`; shifts exactly 60 minutes apart are acceptable.

Completing a shift is an `InventoryManager` or `CoopAdmin` action that moves a `SCHEDULED` shift to `COMPLETED`; completing a shift that is not `SCHEDULED` is rejected with `ERR_INVALID_REQUEST`. On completion, the member's `working_hours_balance` — the sum of `hours` over all that member's `COMPLETED` shifts, not scoped to any fiscal year — is increased by the shift's hours, and `is_working_member` is recomputed. A member is a working member exactly when their `working_hours_balance` is at least the qualifying threshold of 12 hours; a member sitting exactly at the threshold qualifies.

### 3.5. Point of Sale: Building, Pricing, and Finalizing a Sale

Registers are the tills of the store. A `Cashier` creates a register with a `name`; it begins `CLOSED`. A `Cashier` opens or closes a register through a set-open action carrying an `is_open` flag, moving `status` between `OPEN` and `CLOSED`.

A sale is opened by a `Cashier` on a register, supplying the `register_id` and optionally a `member_id` (a null member is a non-member walk-in sale). A new sale carries two independent status dimensions: its fulfillment `checkout_status` starts `BUILDING` and its `payment_status` starts `UNPAID`, and it begins with empty `lines`. These two dimensions advance independently — paying and finalizing are separate transitions that do not gate one another except where explicitly stated.

Lines are added to a `BUILDING` sale by a `Cashier`, who supplies the `product_id`, the `inventory_lot_id` the units are drawn from, and, depending on the product's unit type, either a `quantity` (for an `EACH` product) or a `gross_weight_grams` (for a `WEIGHT` product). Supplying the wrong measure for the product's unit type — a weight item with no gross weight, or an each item with no quantity — is rejected with `ERR_LINE_UNIT_INPUT_INVALID`. The referenced `inventory_lot_id` must belong to the same product named by `product_id`, else `ERR_LOT_PRODUCT_MISMATCH`. A line referencing a `RECALLED` product is refused with `ERR_PRODUCT_RECALLED`.

Each line is priced immediately as it is added, and the resulting figures are stored on the line. Pricing proceeds in stages. First the applicable promotion is resolved: among promotions on the line's product that are active at the current clock — and, for a member-only promotion, only when the sale has a member whose `membership_status` is `ACTIVE` — the candidate with the lowest `promo_price_cents` wins, breaking ties by earliest `start_date` and then earliest `created_at`, never by identifier. If a promotion applies, the unit price is its `promo_price_cents` and the line's `applied_member_only` records whether the winning promotion was member-only; if no promotion applies, the unit price is the product's `base_price_cents` and `applied_member_only` is false. Next, the working-member discount is considered: when the sale has a member who is a working member and the applied price did not come from a member-only deal, the unit price is reduced by the working-member discount of ten percent, that is multiplied by nine-tenths and rounded half up to whole cents. The discount stacks on the shelf price and on an `AD` promotion, but never on a `MEMBER_DEAL`.

The billable quantity, `units`, is then established. For an `EACH` product, `units` equals the supplied `quantity`. For a `WEIGHT` product, the `net_weight_grams` is the `gross_weight_grams` minus the product's `tare_grams`, and `units` is that net-gram figure divided by 1000 to yield kilograms. The line's `unit_price_cents` records the resolved per-unit price. The `line_subtotal_cents` is the unit price multiplied by `units`, rounded half up to whole cents. The `line_tax_cents` is the line subtotal multiplied by the tax rate of eight percent and rounded half up when the product is taxable, and zero otherwise. The `line_total_cents` is the line subtotal plus the line tax. Finally, `is_patronage_eligible` on the line is true exactly when the product is not prepared food.

Whenever the lines change — on every line addition and again at finalize — the sale's running totals are refreshed by summing already-rounded line values, with no re-rounding at the sale level. The `subtotal_cents` is the sum of `line_subtotal_cents` across lines, the `tax_total_cents` is the sum of `line_tax_cents`, the `total_cents` is the subtotal plus the tax total, and the `patronage_eligible_cents` is the sum of `line_subtotal_cents` over only those lines that are patronage-eligible. This round-per-line-then-sum order is deliberate and must not be replaced by summing raw values and rounding once.

Finalizing a sale is a `Cashier` action moving `checkout_status` from `BUILDING` to `FINALIZED`. Four conditions gate it: the sale must be `BUILDING` (else `ERR_SALE_NOT_BUILDING`), the sale's register must be `OPEN` (else `ERR_REGISTER_CLOSED`), no line may reference a `RECALLED` product (else `ERR_PRODUCT_RECALLED`), and for every line the referenced lot's `qty_on_hand` must be at least the line's `units` (else `ERR_INSUFFICIENT_INVENTORY`). On finalize, for each line the lot's `qty_sold` is increased and its `qty_on_hand` decreased by the line's `units`, and every affected product's `qty_on_hand_total`, `needs_reorder`, and `inventory_value_cents` are recomputed as the reorder cascade propagates from lot depletion. If the sale has a member who is `ACTIVE`, that member's `patronage_cents_ytd` is increased by the sale's `patronage_eligible_cents`, and the OPEN fiscal year's `total_patronage_cents` is increased by the same amount.

Payment and refund are the payment dimension. A `Cashier` marks a sale paid, moving `payment_status` from `UNPAID` to `PAID`; paying a sale that is not `UNPAID` is rejected with `ERR_PAYMENT_NOT_UNPAID`. A `Cashier` refunds a sale, moving `payment_status` from `PAID` to `REFUNDED`; refunding requires the sale to be `PAID` (else `ERR_PAYMENT_NOT_PAID`) and to be `FINALIZED` (else `ERR_SALE_NOT_FINALIZED`), so that inventory that was never drawn cannot be refunded. A refund reverses the finalize movements exactly: for each line the lot's `qty_sold` is decreased and its `qty_on_hand` increased by the line's `units`, every affected product is recomputed, and — if the sale has an `ACTIVE` member — that member's `patronage_cents_ytd` and the OPEN fiscal year's `total_patronage_cents` are each decreased by the sale's `patronage_eligible_cents`.

### 3.6. Board Governance and Proposal Voting

Governance flows through board proposals. A `BoardAdmin` creates a proposal with a `title` and a `proposal_type` — one of `BYLAW`, `BUDGET`, or `POLICY` — and it begins in `DRAFT` with `outcome` set to `PENDING` (its `outcome` becomes `APPROVED` or `REJECTED` only at tally). A single advance action, carrying an `action` verb, drives the proposal's lifecycle. Submitting (`SUBMIT`) moves a proposal from `DRAFT` to `UNDER_REVIEW`. Requesting revisions (`REQUEST_REVISIONS`) sends it from `UNDER_REVIEW` back to `DRAFT`, forming a revision loop. Opening voting (`OPEN_VOTING`) moves it from `UNDER_REVIEW` to `VOTING` and, at that moment, snapshots `eligible_board_member_count` as the count of members who both `is_board_member` and are `ACTIVE`. Withdrawing (`WITHDRAW`) moves a proposal from `DRAFT`, `UNDER_REVIEW`, or `VOTING` to the terminal `WITHDRAWN`. An advance action that is not legal from the proposal's current status is rejected with `ERR_PROPOSAL_INVALID_ACTION`.

Voting is a `Member` action. A member casts a vote by supplying their `member_id` and a `vote` of `FOR`, `AGAINST`, or `ABSTAIN`; recall from §2.1 that the `member_id` must equal the caller's `X-User-ID`. Three conditions guard a vote: the proposal must be in `VOTING` (else `ERR_PROPOSAL_NOT_VOTING`), the voter must be an `ACTIVE` board member (else `ERR_NOT_ELIGIBLE_VOTER`), and the member must not have already voted on this proposal (else `ERR_ALREADY_VOTED`). A cast vote increments the matching tally — `for_count`, `against_count`, or `abstain_count` — appends the member to `voter_member_ids` as a double-vote guard, and recomputes `quorum_met`.

A `BoardAdmin` tallies a proposal in `VOTING`, resolving it to `APPROVED` or `REJECTED` and setting its `outcome`. Quorum is required: the total votes cast (`for_count` plus `against_count` plus `abstain_count`) must be at least the quorum requirement, which is the eligible board-member count multiplied by one-half and rounded up to the next whole vote. If quorum is not met, the tally is rejected with `ERR_QUORUM_NOT_MET` and `quorum_met` remains false. When quorum is met, the outcome is `APPROVED` if the `for_count` is strictly greater than the `against_count`, and `REJECTED` otherwise; abstentions count toward quorum but are excluded from this majority comparison.

### 3.7. Patronage Allocation and Dividend Distribution

At interim and at year end, surplus is distributed to members as a patronage dividend. A `FinanceManager` creates an allocation run against a fiscal year, supplying the `fiscal_year_id`, a `method`, the `expected_fiscal_year_version` for the concurrency check of §2.8, and — for a final run — a `declared_rate`. The `method` is either `ESTIMATED`, an interim run that uses the fiscal year's own `patronage_rate` and requires the year to be `OPEN`, or `FINAL`, a year-end run that uses the board-declared `declared_rate` and requires the year to be `CLOSED`. A new allocation is in `DRAFT`. Creating a fresh run supersedes any prior `DRAFT` allocation for the same fiscal year — that prior draft transitions to `SUPERSEDED` — and increments the fiscal year's `version` by one, which is precisely why a later create carrying a stale `expected_fiscal_year_version` is refused.

Finalizing an allocation is a `FinanceManager` action moving it from `DRAFT` to `FINALIZED`. It requires the allocation to be in `DRAFT` (else `ERR_ALLOCATION_NOT_DRAFT`); an `ESTIMATED` run additionally requires its fiscal year to be `OPEN` (else `ERR_FISCAL_YEAR_NOT_OPEN`) and a `FINAL` run requires its fiscal year to be `CLOSED` (else `ERR_FISCAL_YEAR_NOT_CLOSED`). A `FINAL` run also requires a `declared_rate` to be present (else `ERR_DECLARED_RATE_REQUIRED`); the field is ignored for an `ESTIMATED` run.

On finalize, the run identifies its eligible members — those whose `membership_status` is `ACTIVE` and whose `patronage_cents_ytd` is at least the minimum participation threshold of 5000 cents. The applicable rate is the fiscal year's `patronage_rate` for an `ESTIMATED` run and the allocation's `declared_rate` for a `FINAL` run; because these rates differ, the same member's patronage produces a different dividend under the two methods. For each eligible member, the dividend is the rate multiplied by that member's `patronage_cents_ytd`, rounded half up to whole cents, and stored as the member's `patronage_dividend_cents`. A retained portion — the dividend multiplied by the retention fraction of twenty percent, rounded half up — is then credited back to member equity: the member's `equity_paid_in_cents` is increased by the retained amount, and, in the same movement, the allocation's fiscal year's `total_equity_cents` is increased by that retained amount, preserving the equity invariant. Across all eligible members the run records `total_dividend_cents`, `total_retained_cents`, and `member_count`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions, line additions, votes, and shrink write-offs — return `200 OK`. Read operations return `200 OK`. All `GET` endpoints are available to every role; write endpoints are restricted as shown.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | CoopAdmin |
| POST | `/coop/fiscal-years` | Create a fiscal year (OPEN) | CoopAdmin |
| GET | `/coop/fiscal-years/{id}` | Fetch a fiscal year | Any |
| POST | `/coop/fiscal-years/{id}/close` | Close the year; lapse under-funded active members | FinanceManager |
| POST | `/coop/members` | Register a prospective member-owner (PENDING) | CoopAdmin |
| GET | `/coop/members/{id}` | Fetch a member | Any |
| POST | `/coop/members/{id}/approve` | Approve or reactivate a member to ACTIVE | CoopAdmin |
| POST | `/coop/members/{id}/equity-contribution` | Record an equity contribution | FinanceManager |
| POST | `/coop/members/{id}/drop` | Drop a membership and refund equity | CoopAdmin |
| POST | `/coop/vendors` | Create a vendor / DSD supplier (PENDING) | InventoryManager |
| GET | `/coop/vendors/{id}` | Fetch a vendor | Any |
| POST | `/coop/vendors/{id}/set-status` | Approve or suspend a vendor | InventoryManager |
| POST | `/coop/products` | Create a SKU (ACTIVE) | InventoryManager |
| GET | `/coop/products` | List products; filter by vendor_id | Any |
| GET | `/coop/products/{id}` | Fetch a product | Any |
| PATCH | `/coop/products/{id}` | Update price / reorder / status | InventoryManager |
| POST | `/coop/products/{id}/shrink` | Record shrink; FIFO write-off | InventoryManager |
| POST | `/coop/inventory-lots` | Create a DSD receiving lot (DRAFT) | InventoryManager |
| GET | `/coop/inventory-lots` | List lots; filter by product_id and/or vendor_id | Any |
| GET | `/coop/inventory-lots/{id}` | Fetch a lot | Any |
| POST | `/coop/inventory-lots/{id}/post` | Post a DRAFT lot to the shelf | InventoryManager |
| POST | `/coop/registers` | Create a POS register (CLOSED) | Cashier |
| GET | `/coop/registers/{id}` | Fetch a register | Any |
| POST | `/coop/registers/{id}/set-open` | Open or close a register | Cashier |
| POST | `/coop/sales` | Open a basket on a register | Cashier |
| GET | `/coop/sales` | List sales; filter by member_id and/or register_id | Any |
| GET | `/coop/sales/{id}` | Fetch a sale with lines | Any |
| POST | `/coop/sales/{id}/lines` | Add a priced line to a BUILDING sale | Cashier |
| POST | `/coop/sales/{id}/finalize` | Finalize the basket; draw inventory, accrue patronage | Cashier |
| POST | `/coop/sales/{id}/pay` | Mark the sale paid | Cashier |
| POST | `/coop/sales/{id}/refund` | Refund a paid, finalized sale | Cashier |
| POST | `/coop/promotions` | Create a weekly-ad or member deal | InventoryManager |
| GET | `/coop/promotions` | List promotions; filter by product_id | Any |
| GET | `/coop/promotions/{id}` | Fetch a promotion | Any |
| POST | `/coop/working-shifts` | Schedule a working-member shift | Member, CoopAdmin |
| GET | `/coop/working-shifts` | List shifts; filter by member_id | Any |
| GET | `/coop/working-shifts/{id}` | Fetch a shift | Any |
| POST | `/coop/working-shifts/{id}/complete` | Mark a shift COMPLETED; credit hours | InventoryManager, CoopAdmin |
| POST | `/coop/board-proposals` | Create a board proposal (DRAFT) | BoardAdmin |
| GET | `/coop/board-proposals/{id}` | Fetch a proposal with vote counts | Any |
| POST | `/coop/board-proposals/{id}/advance` | Advance proposal lifecycle | BoardAdmin |
| POST | `/coop/board-proposals/{id}/votes` | Cast a board vote | Member |
| POST | `/coop/board-proposals/{id}/tally` | Tally votes; requires quorum | BoardAdmin |
| POST | `/coop/patronage-allocations` | Create a patronage allocation run (DRAFT) | FinanceManager |
| GET | `/coop/patronage-allocations` | List allocations; filter by fiscal_year_id | Any |
| GET | `/coop/patronage-allocations/{id}` | Fetch an allocation | Any |
| POST | `/coop/patronage-allocations/{id}/finalize` | Finalize; post dividends and retained equity | FinanceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_LINE_UNIT_INPUT_INVALID` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_FISCAL_YEAR_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_REGISTER_NOT_FOUND` | 404 Not Found |
| `ERR_SALE_NOT_FOUND` | 404 Not Found |
| `ERR_PROMOTION_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_NOT_FOUND` | 404 Not Found |
| `ERR_PROPOSAL_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_APPROVABLE` | 409 Conflict |
| `ERR_FISCAL_YEAR_NOT_OPEN` | 409 Conflict |
| `ERR_FISCAL_YEAR_NOT_CLOSED` | 409 Conflict |
| `ERR_LOT_NOT_DRAFT` | 409 Conflict |
| `ERR_REGISTER_CLOSED` | 409 Conflict |
| `ERR_SALE_NOT_BUILDING` | 409 Conflict |
| `ERR_PAYMENT_NOT_UNPAID` | 409 Conflict |
| `ERR_PAYMENT_NOT_PAID` | 409 Conflict |
| `ERR_SALE_NOT_FINALIZED` | 409 Conflict |
| `ERR_PROPOSAL_INVALID_ACTION` | 409 Conflict |
| `ERR_PROPOSAL_NOT_VOTING` | 409 Conflict |
| `ERR_ALLOCATION_NOT_DRAFT` | 409 Conflict |
| `ERR_PROMO_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_VENDOR_NOT_APPROVED` | 409 Conflict |
| `ERR_LOT_PRODUCT_MISMATCH` | 409 Conflict |
| `ERR_NOT_ELIGIBLE_VOTER` | 409 Conflict |
| `ERR_ALREADY_VOTED` | 409 Conflict |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_OPEN_FISCAL_YEAR_EXISTS` | 409 Conflict |
| `ERR_STALE_FISCAL_YEAR_VERSION` | 412 Precondition Failed |
| `ERR_PRODUCT_RECALLED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_INVENTORY` | 422 Unprocessable Entity |
| `ERR_EQUITY_BELOW_SHARE_PRICE` | 422 Unprocessable Entity |
| `ERR_DECLARED_RATE_REQUIRED` | 422 Unprocessable Entity |

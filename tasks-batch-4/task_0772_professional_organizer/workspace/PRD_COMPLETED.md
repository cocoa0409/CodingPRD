# Professional Organizer & Decluttering Service API — Product Requirements Document

## 1. Introduction

Professional organizing engagements are messy to bill. A single job begins with an in-home assessment that captures which rooms are in scope, proceeds through a series of hands-on working sessions, and generates a stream of physical outcomes along the way — items hauled away, goods donated for a tax credit, storage products (bins, shelving, labeling systems) sourced at a markup, and an optional move or downsizing add-on. Some clients are billed by the hour, others at a flat project price. This API is the system of record that ties all of that together, so that when the final invoice is issued it reflects exactly the labor, products, hauling, donations, and add-ons that actually occurred.

The service models the engagement as a **Project** that accumulates several running ledgers — labor hours, projected product cost, projected hauling cost, and donation credit — as fieldwork is logged. Four operational roles collaborate over the project's life: an operations manager sets up clients and organizers and owns the project lifecycle, a field organizer runs sessions and logs inventory and products, a billing administrator issues invoices, and the client reads and settles them. The document below specifies the global contracts every endpoint honors (Section 2), then walks the business workflows where the domain rules live (Section 3), before summarizing the endpoint surface (Section 4) and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers that establish the caller's identity and capacity: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational role. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles: `OperationsManager`, `Organizer`, `BillingAdmin`, and `Client`. Their write surfaces do not overlap. An `OperationsManager` owns client and organizer setup plus the entire project lifecycle (creating, activating, and cancelling projects, and authoring maintenance plans). An `Organizer` performs fieldwork: running sessions, completing them with logged hours, logging inventory items and scheduling and confirming their disposition, and sourcing product lines. A `BillingAdmin` owns invoice issuance. A `Client` is the paying party and may settle or dispute their invoices. Reads (GET endpoints) are broadly available to the relevant roles as summarized in Section 4.

Two of the four roles are **entity-backed**, meaning `X-User-ID` refers to a persisted record and is used for ownership checks:

- When `X-User-Role` is `Organizer`, `X-User-ID` is the `id` of the acting `Organizer`; ownership checks on any resource that references an `Organizer` compare the resource's organizer foreign key to `X-User-ID`. In particular, completing a session is restricted to the organizer assigned to that session — the session's `organizer_id` must equal `X-User-ID`.
- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's client foreign key to `X-User-ID`. A client acts only on invoices belonging to a project whose `client_id` is their own `X-User-ID`.

The other two roles are **opaque**: when `X-User-Role` is `OperationsManager` or `BillingAdmin`, `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server may accept and log it, but it is not compared against any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Out-of-range values are clamped rather than rejected — a `limit` below 1 becomes 1 and a `limit` above 100 becomes 100, while a negative `offset` becomes 0 — and a `limit` or `offset` that is missing or cannot be parsed as an integer falls back to its default (10 and 0 respectively).

Unless a specific workflow states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All eight resource types in this system — `Client`, `Organizer`, `Project`, `Session`, `InventoryItem`, `ProductLine`, `Invoice`, and `MaintenancePlan` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version`. The `updated_at` field is refreshed on every mutation, and `version` starts at 1 (its value at creation) and increments by one on every mutation of the resource, including mutations to computed ledger fields. A resource's `version` is the value used for optimistic concurrency control described in Section 2.7.

Whenever a computed field on a `Project` changes as a side effect of activity elsewhere — for example when a session completion updates `accrued_labor_hours`, or a product cancellation reduces `projected_product_cost_cents` — that counts as a mutation of the project: its `updated_at` advances and, except where a specific lifecycle transition already accounts for the version bump, its `version` reflects the change.

### 2.5. Monetary Values, Rates, and Rounding

All monetary amounts are stored and returned as integer cents. Hours are represented as plain numbers. Wherever a calculation requires rounding, the system uses the **round half up** method: a value whose fractional part is exactly one-half rounds away from zero to the next whole cent. Rounding is applied at the precise points named in the calculation narratives of Section 3 — for example, labor is rounded per component (regular and overtime) before they are summed and before any weekend multiplier is applied, and a product line's per-unit marked price is rounded before it is multiplied by quantity. Percentages such as markup, the weekend surcharge, the overtime multiplier, the donation credit rate, the discount rates, and the tax rate are applied as exact fractions and only the results are rounded, at the steps specified.

### 2.6. The Project Ledger

A `Project` is the financial hub of an engagement and maintains four running ledger fields, all initialized to 0 at creation and kept continuously reconciled as fieldwork is recorded:

- `accrued_labor_hours` is the sum of `logged_hours` across the project's sessions that are in `COMPLETED` status.
- `projected_product_cost_cents` is the sum of `client_price_cents` across the project's product lines whose status is `QUOTED`, `ORDERED`, or `DELIVERED`.
- `projected_haul_cost_cents` is the sum of `haul_fee_cents` across the project's inventory items whose status is `SCHEDULED_HAUL` or `HAULED`.
- `donation_credit_cents` is the sum of the final donation credits across the project's inventory items in `DONATED` status.

These ledgers are maintained **incrementally**: an amount is added when a contributing event occurs and subtracted when it is compensated. After any reversal, the invariant still holds that each ledger equals the aggregate of its contributing records — for example, `accrued_labor_hours` always equals the sum of `logged_hours` over the project's `COMPLETED` sessions, and `projected_product_cost_cents` always equals the sum of `client_price_cents` over its `QUOTED`, `ORDERED`, and `DELIVERED` product lines. Note that the project's `projected_product_cost_cents` ledger includes `QUOTED` lines, whereas the invoice's product subtotal (Section 3.7) counts only `ORDERED` and `DELIVERED` lines; the two are deliberately scoped differently.

### 2.7. Optimistic Concurrency at Invoice Issuance

Issuing an invoice is the one operation guarded by optimistic concurrency control. A request to issue an invoice must include `expected_project_version`, carrying the `version` of the target `Project` that the client last observed. The server compares this value against the project's current `version`. If they do not match — because some other writer has advanced the project since the client last read it — the issuance is rejected with `ERR_STALE_PROJECT_VERSION` at HTTP status 412. This prevents a second issue attempt that still carries an old version from overwriting a billing view it never saw: the first successful issuance legitimately moves the project from `ACTIVE` to `WRAP_UP` and bumps its `version`, so any later attempt bearing the earlier version is correctly recognized as stale. No other endpoint takes a version field or performs this check.

### 2.8. Cascading Lifecycle Consistency

Several operations mutate more than one resource. When a project is cancelled, the cancellation fans out to the project's dependents (Section 3.8). When an invoice is paid, payment cascades to close the project and, in turn, to activate a drafted maintenance plan (Section 3.8). Each entity touched by a cascade undergoes its own state transition, and each such mutation independently refreshes that entity's `updated_at` and increments its `version`. Ledger reversals that accompany a cancellation keep the Project ledgers in Section 2.6 consistent with the surviving records.

### 2.9. Resource Existence and Referential Integrity

For any endpoint whose path names a resource by `id`, the system validates path identifiers left to right and rejects the first one that does not resolve, returning the not-found error specific to that resource type: `ERR_CLIENT_NOT_FOUND`, `ERR_ORGANIZER_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_PLAN_NOT_FOUND`. Foreign keys supplied in a request body — such as `client_id` and `lead_organizer_id` when creating a project, or `project_id` and `organizer_id` when creating a session — are likewise checked against existing records, and an unresolved reference is rejected with the corresponding not-found error (`ERR_CLIENT_NOT_FOUND`, `ERR_ORGANIZER_NOT_FOUND`, or `ERR_PROJECT_NOT_FOUND`).

### 2.10. Request Validation and Evaluation Order

Every write request is checked in a fixed priority order so that failures surface deterministically. Authentication (Section 2.1) is evaluated first, and authorization second: a request with missing or unknown headers fails with `ERR_UNAUTHENTICATED` before any permission or ownership check yields `ERR_FORBIDDEN`. Third, the request body is validated for well-formedness — required fields present, enum values legal, numeric ranges honored, and, for sessions, `scheduled_end` strictly later than `scheduled_start`; any violation is `ERR_VALIDATION` at HTTP 422. Fourth, path resource ids are resolved (Section 2.9), and fifth, request-body foreign keys are resolved (Section 2.9). Only after all of these pass does the system evaluate the state and business rules specific to each workflow, described in Section 3. Role-based permission (whether the caller's role may invoke the operation at all) is the authorization check performed second; entity-level ownership checks — those that compare `X-User-ID` against a foreign key on an already-fetched resource, such as a session's `organizer_id` on completion or an invoice's owning `client_id` — are necessarily deferred until after that resource is resolved (steps four and five). Consequently an ownership `ERR_FORBIDDEN` surfaces only once body validation and existence resolution have passed. Where a single workflow layers several business checks — most notably invoice issuance — the narrative in Section 3 states their relative order explicitly.

## 3. Business Logic & Workflows

### 3.1. Onboarding Clients and Organizers

An `OperationsManager` seeds the system with the two participant types an engagement needs. A **client** record is created with a `full_name`, a contact `email`, a `home_address`, and optional `access_notes` (free-text entry instructions that default to an empty string when omitted). The `home_address` identifies the physical home, which matters later because the system enforces whole-day scheduling exclusivity per home.

An **organizer** record captures a `full_name`, a contact `email`, an `hourly_rate_cents` labor rate that must be strictly greater than zero, and an `active` flag indicating whether the organizer may be assigned to new sessions; `active` defaults to true when omitted. This flag is advisory metadata only and is not enforced at scheduling time — session creation does not consult it, so an organizer whose `active` is false can still be assigned to a session. The organizer's `hourly_rate_cents` is the rate applied when computing labor cost for the sessions they run.

### 3.2. Scoping and Activating a Project

A **project** is opened by an `OperationsManager` and begins life in the `SCOPING` state. Creation records the `client_id` and `lead_organizer_id` the engagement is tied to, a `title`, and the `billing_mode`, which is either `HOURLY` or `PROJECT` and selects how labor is billed. When `billing_mode` is `PROJECT`, a `flat_price_cents` fixed labor price applies (defaulting to 0, required to be zero or greater at creation, and ignored entirely under `HOURLY`). The in-home assessment populates `scope_rooms`, an array of room-scope strings (defaulting to an empty array). The optional move/downsizing add-on is captured by `move_addon_requested` (default false) and `move_box_count`, the number of packing boxes, which must be zero or greater and defaults to 0. At creation the project's four ledger fields — `accrued_labor_hours`, `projected_product_cost_cents`, `projected_haul_cost_cents`, and `donation_credit_cents` — are initialized to 0, and `status` is set to `SCOPING`.

Activation moves the project from `SCOPING` to `ACTIVE` and is performed by an `OperationsManager`. Activation is only valid from `SCOPING`; attempting it from any other state is rejected with `ERR_PROJECT_NOT_IN_SCOPING`. Two preconditions gate the transition: the `scope_rooms` array must be non-empty — at least one room must have been captured during the in-home assessment, otherwise the request fails with `ERR_SCOPE_EMPTY` — and, when `billing_mode` is `PROJECT`, `flat_price_cents` must be strictly greater than zero, otherwise the request fails with `ERR_FLAT_PRICE_REQUIRED`. A successful activation increments the project's `version` by one. Activation is not a hard gate on downstream creation, however: session scheduling is permitted while the project is `SCOPING` or `ACTIVE` (Section 3.3), and inventory-item and product-line creation perform no project-status check at all — they are accepted against a project in any state so long as the referenced project exists.

### 3.3. Scheduling Sessions and Guarding the Calendar

A **session** is a scheduled block of fieldwork tied to a project and an organizer. An `OperationsManager` or an `Organizer` schedules one by supplying `project_id`, `organizer_id`, `scheduled_start`, and `scheduled_end` (both ISO 8601 UTC instants); `scheduled_end` must be strictly after `scheduled_start`, or the request is rejected as `ERR_VALIDATION`. A session may be scheduled while its parent project is in either `SCOPING` or `ACTIVE`; scheduling against a project in `WRAP_UP` is rejected with `ERR_PROJECT_NOT_ACTIVE`, and against a `CLOSED` or `CANCELLED` project with `ERR_PROJECT_TERMINAL`. A new session begins in `SCHEDULED` status with `logged_hours` defaulting to 0 and `labor_cost_cents` at 0.

Two exclusivity guards run at scheduling time, in this order. First, an **organizer double-booking** check: treating each session's occupied time as the half-open interval from `scheduled_start` up to but not including `scheduled_end`, no other non-cancelled session for the same `organizer_id` may sit within a 30-minute travel buffer of the new one — that is, the gap between this session and any adjacent session of the same organizer must be at least 30 minutes on either side. A violation is rejected with `ERR_ORGANIZER_DOUBLE_BOOKED`. Second, a **client home whole-day exclusivity** check: no other non-cancelled session belonging to any project of the same client may fall on the same UTC calendar date as this session's `scheduled_start`; a violation is rejected with `ERR_CLIENT_HOME_DOUBLE_BOOKED`. The organizer buffer check is evaluated before the client whole-day check.

### 3.4. Running and Completing Sessions; Labor Accounting

Fieldwork on a session may only begin once the parent project is `ACTIVE`. Starting a session advances it from `SCHEDULED` to `IN_PROGRESS`; this is done by an `OperationsManager` or an `Organizer`, and it requires the parent project to be in `ACTIVE`, failing otherwise with `ERR_PROJECT_NOT_ACTIVE`. Any session status change that the state machine does not permit from the current state is rejected with `ERR_INVALID_SESSION_TRANSITION`.

Completing a session, performed by the assigned `Organizer`, advances it from `IN_PROGRESS` to `COMPLETED` and carries the `logged_hours` actually worked. The parent project must be `ACTIVE` (otherwise `ERR_PROJECT_NOT_ACTIVE`), and `logged_hours` must be zero or greater (otherwise `ERR_VALIDATION`). On completion the system computes the session's `labor_cost_cents` and its `is_overtime` flag, and adds the session's `logged_hours` to the project's `accrued_labor_hours` ledger.

The labor cost is derived from the assigned organizer's `hourly_rate_cents` and the hours worked, with an overtime threshold of 8 hours. The portion of `logged_hours` up to 8 hours is the regular portion, and any hours beyond 8 are the overtime portion. The `is_overtime` flag is true only when `logged_hours` is strictly greater than 8 hours. The regular charge is the regular hours multiplied by the hourly rate, rounded half up to whole cents. The overtime charge is the overtime hours multiplied by the hourly rate and then by an overtime multiplier of 1.5, rounded half up to whole cents. These two rounded components are summed into a subtotal. Finally, a weekend surcharge is applied when the session's `scheduled_start`, evaluated in UTC, falls on a Saturday or Sunday: in that case the final `labor_cost_cents` is the subtotal multiplied by 1.20 (a 20% surcharge), rounded half up; on a weekday, `labor_cost_cents` equals the subtotal with no surcharge.

A completed session can be voided. Cancelling a session moves it to `CANCELLED` and may be done by an `OperationsManager` or an `Organizer`. When the session being cancelled was still `SCHEDULED` or `IN_PROGRESS`, no labor had accrued, so nothing is reversed. When the session being cancelled was `COMPLETED`, the cancellation is compensating: the system subtracts that session's `logged_hours` back out of the project's `accrued_labor_hours` and resets the session's `labor_cost_cents` to 0, preserving the invariant that `accrued_labor_hours` equals the sum of `logged_hours` over the project's remaining `COMPLETED` sessions.

### 3.5. Logging Inventory and Its Disposition Fork

As an organizer clears a room they log **inventory items**. An `Organizer` records each item against a `project_id`, with a `room_label` naming the scope room it came from, a `description`, a `disposition`, and an optional `estimated_value_cents` provisional fair-market estimate (zero or greater, defaulting to 0). The `disposition` is one of `KEEP`, `HAUL`, `DONATE`, or `SELL` and drives everything that follows. An item logged as `KEEP` is terminal immediately: it is created directly in `KEPT` status. Every other disposition starts the item in `LOGGED`.

From `LOGGED`, an `Organizer` schedules the item's disposition, and the target state forks by disposition. For an item whose disposition is `HAUL` or `SELL`, scheduling advances it to `SCHEDULED_HAUL`; if the disposition is anything else the request is rejected with `ERR_DISPOSITION_MISMATCH`. Scheduling for hauling books a flat haul fee of 2,500 cents ($25) into the item's `haul_fee_cents` and adds that fee to the project's `projected_haul_cost_cents` ledger. For an item whose disposition is `DONATE`, scheduling advances it to `SCHEDULED_DONATION` (any other disposition here is again `ERR_DISPOSITION_MISMATCH`); no haul fee applies, and a provisional donation value is computed as the item's `estimated_value_cents` multiplied by the 10% donation credit rate, rounded half up. This provisional credit is for planning only and is **not** added to the project's `donation_credit_cents` ledger or to any invoice.

Confirmation completes the disposition. Confirming a `SCHEDULED_HAUL` item advances it to `HAULED`, and its `haul_fee_cents` remains booked in `projected_haul_cost_cents`. Confirming a `SCHEDULED_DONATION` item advances it to `DONATED` and carries an appraised `final_value_cents`, which must be zero or greater (otherwise `ERR_VALIDATION`). On donation confirmation the system stores `final_value_cents` and computes the final donation credit as `final_value_cents` multiplied by the same 10% donation credit rate, rounded half up; this final credit is added to the project's `donation_credit_cents` ledger and is the amount that reduces the invoice. Any inventory transition the state machine does not allow from the item's current state is rejected with `ERR_INVALID_ITEM_TRANSITION`.

### 3.6. Sourcing Products at a Markup

An `Organizer` sources storage products as **product lines**. Each line is created against a `project_id` with a `product_name`, a `category` (one of `BIN`, `SHELVING`, `SYSTEM`, or `LABELING`), a per-unit `wholesale_cost_cents` that must be strictly greater than zero, a `quantity` of at least 1, and a `markup_pct` expressed as a fraction (for example, 0.35 means a 35% markup) that must be zero or greater. A new line begins in `QUOTED` status.

The billed `client_price_cents` is computed at creation with a pinned rounding order: first the per-unit marked price is computed as `wholesale_cost_cents` multiplied by one plus `markup_pct` and rounded half up to whole cents; then that rounded per-unit price is multiplied by `quantity`. The rounding happens on the per-unit price only — never on the final total — and the final multiplication by quantity is exact integer arithmetic. On creation the line's `client_price_cents` is added to the project's `projected_product_cost_cents` ledger.

An `Organizer` or an `OperationsManager` advances a line through its lifecycle: from `QUOTED` to `ORDERED`, and from `ORDERED` to `DELIVERED`. A line that is still `QUOTED` or `ORDERED` may be cancelled to `CANCELLED`; a delivered line cannot be cancelled. Cancelling a line is compensating: its `client_price_cents` is subtracted back out of the project's `projected_product_cost_cents`, keeping that ledger equal to the sum of `client_price_cents` over the project's `QUOTED`, `ORDERED`, and `DELIVERED` lines. A transition the state machine does not permit is rejected with `ERR_INVALID_PRODUCT_TRANSITION`.

### 3.7. Issuing the Invoice

A `BillingAdmin` issues an **invoice** for a project, supplying `project_id` and `expected_project_version`. Issuance both creates the invoice in `ISSUED` status and transitions the project from `ACTIVE` to `WRAP_UP`, freezing further session creation for that project and incrementing the project's `version` by one. The invoice copies the project's `billing_mode` into its own `billing_mode` at issue time.

Beyond authentication, authorization, body validation, and existence checks (Section 2.10), issuance layers five business checks, evaluated in this relative order:

1. If the project is already terminal (`CLOSED` or `CANCELLED`) the issuance is rejected with `ERR_PROJECT_TERMINAL`. This terminal check runs first, before the optimistic-concurrency guard.
2. The `expected_project_version` optimistic-concurrency guard of Section 2.7 is checked next; a mismatch yields `ERR_STALE_PROJECT_VERSION` at HTTP 412. Because this precedes the `ACTIVE`-state check below, a stale re-issue against a project that a prior issuance already advanced to `WRAP_UP` is reported as `ERR_STALE_PROJECT_VERSION` (consistent with Section 2.7) rather than as a state error.
3. The project must be in a state from which it can move to `WRAP_UP` — that is, `ACTIVE`. A non-terminal project that is not `ACTIVE` (for example `SCOPING` or `WRAP_UP`) is rejected with `ERR_PROJECT_NOT_ACTIVE`.
4. There must be no session for the project still in `SCHEDULED` or `IN_PROGRESS`; any unresolved session blocks issuance with `ERR_UNRESOLVED_SESSIONS`.
5. There must be billable work: under `HOURLY` billing at least one `COMPLETED` session must exist, and under `PROJECT` billing `flat_price_cents` must be strictly greater than zero. If neither condition is met the issuance is rejected with `ERR_NO_BILLABLE_WORK`.

When the checks pass, the system computes the invoice components and stores them on the invoice. The `product_subtotal_cents` is the sum of `client_price_cents` over the project's product lines in `ORDERED` or `DELIVERED` status (note that `QUOTED` lines are excluded here, even though they count toward the project ledger). The `haul_subtotal_cents` is the sum of `haul_fee_cents` over inventory items in `SCHEDULED_HAUL` or `HAULED` status. The `donation_credit_cents` on the invoice is the sum of the final donation credits over inventory items in `DONATED` status, and it is subtracted from the subtotal. The `move_addon_cents` packing charge is `move_box_count` multiplied by a per-box rate of 500 cents ($5) when `move_addon_requested` is true, and 0 otherwise.

The `labor_subtotal_cents` depends on the invoice's `billing_mode`. Under `HOURLY`, the labor subtotal is the sum of `labor_cost_cents` over the project's `COMPLETED` sessions. Under `PROJECT`, the labor subtotal is the project's `flat_price_cents`, and the actual logged hours are ignored entirely.

The invoice total is then assembled in a pinned order. First the `subtotal_cents` is the labor subtotal plus the product subtotal plus the haul subtotal plus the move add-on charge, minus the donation credit. Next a volume discount is keyed on that subtotal: if `subtotal_cents` is at least 500,000 cents the discount rate is 10%; otherwise if it is at least 200,000 cents the discount rate is 5%; otherwise there is no discount. Both tier comparisons are inclusive of the boundary. The `discount_cents` is the subtotal multiplied by the applicable discount rate, rounded half up. The taxable amount is `subtotal_cents` minus `discount_cents`. The `tax_cents` is that taxable amount multiplied by an 8% tax rate, rounded half up. Finally the `grand_total_cents` is the taxable amount plus the tax. An invoice status transition the state machine does not allow from its current state is rejected with `ERR_INVALID_INVOICE_TRANSITION`.

### 3.8. Disputes, Payment, Closure, and Cancellation

Once issued, an invoice can be **disputed** and re-issued in a cycle. A `Client` or a `BillingAdmin` may move an `ISSUED` invoice to `DISPUTED`, and may resolve a `DISPUTED` invoice back to `ISSUED` for re-review. Payment is only permitted on an invoice that is currently `ISSUED`: attempting to pay a `DISPUTED` invoice is rejected with `ERR_INVOICE_NOT_PAYABLE`, so a disputed invoice must first be resolved back to `ISSUED`.

Paying an invoice, done by a `Client` or a `BillingAdmin`, advances it from `ISSUED` to `PAID` and sets off a cascade. Payment closes the parent project, moving it from `WRAP_UP` to `CLOSED`. If that project has a maintenance plan sitting in `DRAFT`, closure in turn activates it, transitioning the plan from `DRAFT` to `ACTIVE`. Each of these transitions is a distinct mutation that refreshes the affected resource's `updated_at` and increments its `version`.

Cancellation is the other terminal path for a project. An `OperationsManager` may cancel a project from `SCOPING`, `ACTIVE`, or `WRAP_UP`; a project already in a terminal state (`CLOSED` or `CANCELLED`) cannot be cancelled and the attempt is rejected with `ERR_PROJECT_TERMINAL`. Cancellation moves the project to `CANCELLED`, increments its `version` by one, and fans out to its dependents: every session still in `SCHEDULED` or `IN_PROGRESS` is moved to `CANCELLED` (these carry no accrued labor, so there is nothing to reverse); every product line still in `QUOTED` or `ORDERED` is moved to `CANCELLED`, and each such cancellation subtracts that line's `client_price_cents` from the project's `projected_product_cost_cents` ledger; and any maintenance plan in `DRAFT` or `ACTIVE` is moved to `CANCELLED`.

### 3.9. The Maintenance Plan

A conceptually one-to-one **maintenance plan** captures the before/after follow-up arrangement for a project. This one-per-project relationship is not enforced by the system: creating a maintenance plan performs no check for an existing plan on the same project, so multiple plans may coexist for one project, and the closure and cancellation cascades of Section 3.8 act on every qualifying plan of the project rather than a single one. An `OperationsManager` creates it against a `project_id` with a `cadence` (`MONTHLY`, `QUARTERLY`, or `BIANNUAL`), a recurring `monthly_fee_cents` (zero or greater), and an optional `next_followup_note` free-text note for the first follow-up visit (defaulting to an empty string). The plan is created in `DRAFT` status, and its `visits_per_year` is derived from the cadence: `MONTHLY` yields 12 visits per year, `QUARTERLY` yields 4, and `BIANNUAL` yields 2.

A plan in `DRAFT` is promoted to `ACTIVE` automatically when its project closes on invoice payment, as described in Section 3.8. An `OperationsManager` may also cancel a plan directly, moving it from `DRAFT` or `ACTIVE` to `CANCELLED`; the same terminal state is reached automatically when the parent project is cancelled. A plan transition the state machine does not allow from its current state is rejected with `ERR_INVALID_PLAN_TRANSITION`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or transition an existing resource, including lifecycle actions and reads, return `200 OK`. All endpoints honor the response envelope, authentication, and validation contracts of Section 2, and the business rules of Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Create a client | OperationsManager |
| GET | `/clients/{id}` | Get a client | OperationsManager, Organizer, BillingAdmin, Client |
| POST | `/organizers` | Create an organizer | OperationsManager |
| GET | `/organizers/{id}` | Get an organizer | OperationsManager, Organizer, BillingAdmin |
| POST | `/projects` | Create a project (starts in SCOPING) | OperationsManager |
| GET | `/projects` | List projects; filter by client, lead organizer, or status | OperationsManager, Organizer, BillingAdmin, Client |
| GET | `/projects/{id}` | Get a project, including ledger fields | OperationsManager, Organizer, BillingAdmin, Client |
| POST | `/projects/{id}/activate` | Activate a project (SCOPING to ACTIVE) | OperationsManager |
| POST | `/projects/{id}/cancel` | Cancel a project; cascades to sessions, product lines, ledgers, and maintenance plan | OperationsManager |
| POST | `/sessions` | Schedule a session for a project and organizer | OperationsManager, Organizer |
| GET | `/sessions` | List sessions; filter by project, organizer, or status | OperationsManager, Organizer, BillingAdmin, Client |
| GET | `/sessions/{id}` | Get a session | OperationsManager, Organizer, BillingAdmin, Client |
| POST | `/sessions/{id}/complete` | Complete an in-progress session and log hours | Organizer |
| PATCH | `/sessions/{id}` | Transition a session (start or cancel, including compensating void) | OperationsManager, Organizer |
| POST | `/inventory-items` | Log an inventory item removed from a room | Organizer |
| GET | `/inventory-items` | List inventory items; filter by project, disposition, or status | OperationsManager, Organizer, BillingAdmin, Client |
| GET | `/inventory-items/{id}` | Get an inventory item | OperationsManager, Organizer, BillingAdmin, Client |
| POST | `/inventory-items/{id}/schedule` | Schedule item disposition (forks by disposition) | Organizer |
| POST | `/inventory-items/{id}/confirm` | Confirm disposition (haul or donation with appraised value) | Organizer |
| POST | `/product-lines` | Add a product line with markup | Organizer |
| GET | `/product-lines` | List product lines; filter by project or status | OperationsManager, Organizer, BillingAdmin, Client |
| GET | `/product-lines/{id}` | Get a product line | OperationsManager, Organizer, BillingAdmin, Client |
| PATCH | `/product-lines/{id}` | Transition a product line (ordered, delivered, cancelled) | Organizer, OperationsManager |
| POST | `/invoices` | Issue an invoice for a project (OCC-guarded; moves project ACTIVE to WRAP_UP) | BillingAdmin |
| GET | `/invoices` | List invoices; filter by project or status | OperationsManager, BillingAdmin, Client |
| GET | `/invoices/{id}` | Get an invoice | OperationsManager, BillingAdmin, Client |
| POST | `/invoices/{id}/pay` | Pay an issued invoice (cascades project close and maintenance-plan activation) | BillingAdmin, Client |
| PATCH | `/invoices/{id}` | Transition an invoice (dispute or resolve) | BillingAdmin, Client |
| POST | `/maintenance-plans` | Create the maintenance plan for a project (starts DRAFT) | OperationsManager |
| GET | `/maintenance-plans` | List maintenance plans; filter by project or status | OperationsManager, BillingAdmin, Client |
| GET | `/maintenance-plans/{id}` | Get a maintenance plan | OperationsManager, BillingAdmin, Client |
| PATCH | `/maintenance-plans/{id}` | Transition a maintenance plan (cancel) | OperationsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_ORGANIZER_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_ITEM_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_IN_SCOPING` | 409 |
| `ERR_SCOPE_EMPTY` | 409 |
| `ERR_FLAT_PRICE_REQUIRED` | 409 |
| `ERR_PROJECT_NOT_ACTIVE` | 409 |
| `ERR_PROJECT_TERMINAL` | 409 |
| `ERR_INVALID_SESSION_TRANSITION` | 409 |
| `ERR_INVALID_ITEM_TRANSITION` | 409 |
| `ERR_DISPOSITION_MISMATCH` | 409 |
| `ERR_INVALID_PRODUCT_TRANSITION` | 409 |
| `ERR_INVALID_INVOICE_TRANSITION` | 409 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_ORGANIZER_DOUBLE_BOOKED` | 409 |
| `ERR_CLIENT_HOME_DOUBLE_BOOKED` | 409 |
| `ERR_UNRESOLVED_SESSIONS` | 409 |
| `ERR_NO_BILLABLE_WORK` | 422 |
| `ERR_INVALID_PLAN_TRANSITION` | 409 |

# Subscription Box Fulfillment API — Product Requirements Document

## 1. Introduction

Subscription-box brands live and die by their monthly cadence: every cycle, a curated set of components must be kitted into thousands of individual boxes, labeled, handed to carriers, and billed — while subscriber counts shift, stock runs short, and boxes come back damaged or lost. This document specifies the Subscription Box Fulfillment & Kitting API, the operational backbone that brand operators and fulfillment-center staff use to run that cadence end to end. The API covers client onboarding with a prepaid wallet, box plans and their versioned kit bills of materials, component inventory with reservation semantics, subscriber list imports and churn, monthly assembly runs with a rework loop, carrier shipping waves with purchasable and voidable labels, return and replacement adjudication, per-box billing with provisional and final statement variants, and a per-period fulfillment report.

Two design pressures shape every workflow below. First, component stock is finite and shared across clients: reserving, committing, and releasing units must be exact, because a run that locks against stock it cannot actually consume strands an entire month's shipments. Second, billing is a reconciliation exercise, not a single invoice: statements begin as optimistic provisional estimates, absorb postage and refund events as they happen, and are only frozen into a final, wallet-debiting amount once the period closes — with a dispute cycle for when the client disagrees. Five operator roles divide this work, and an optimistic-concurrency discipline guards the two write paths where a stale reader could silently overwrite a peer's decision.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to every resource and every request.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role string the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles, spelled precisely as follows: `PlatformAdmin`, `ClientOps`, `WarehouseOps`, `BillingAdmin`, and `CustomerService`. Each endpoint admits a defined subset of these roles; an authenticated caller whose role is not admitted, or who violates the ownership rule below, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The roles divide the operational surface. A `PlatformAdmin` is the platform operator with superset read access, owning client onboarding, wallet top-ups, and the logical clock. A `ClientOps` is a brand-side operator who manages their own plans, kit revisions, subscriber imports, pause/resume/churn actions, and disputes of their own statements. A `WarehouseOps` operator runs the fulfillment center: components, stock receipts, assembly runs, shipping waves, labels, carrier scans, and return receiving. A `BillingAdmin` is the finance operator who owns the statement lifecycle — finalize, resolve-dispute, mark-paid — and shares wallet-adjustment authority with `PlatformAdmin`. A `CustomerService` agent opens and adjudicates return cases.

When `X-User-Role` is `ClientOps`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's owning-client foreign key to `X-User-ID`. Plans, subscribers, import batches, and billing statements are all owned through their client, so a `ClientOps` caller may act only on resources belonging to the client whose `id` they present — including reading a client record, which for `ClientOps` is restricted to their own `id`. Likewise, when a `ClientOps` caller creates a box plan, the `client_id` in the request body must equal their `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `WarehouseOps`, `BillingAdmin`, or `CustomerService`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. On list endpoints, a `ClientOps` caller's result set is implicitly restricted to resources owned by their own client; this scoping is never an error by itself. Two filters escalate instead: a `client_id` filter on `GET /box-plans` naming another client, and a `plan_id` filter on `GET /kit-revisions` or `GET /subscribers` naming an existing plan of another client, are each rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints paginate through two query parameters. The `limit` parameter caps how many items one page returns; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip before the page begins and defaults to 0. Both are integers; a non-integer value falls under the generic malformed-payload rejection, while an integer outside the allowed range is clamped to the nearest bound (`limit` into [1, 100], `offset` up to 0) rather than rejected.

Unless an endpoint states otherwise, every list is sorted by creation timestamp in ascending order, with equal timestamps broken by creation (insertion) order — this includes the chronological inventory-event ledgers. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

### 2.4. Common Resource Properties

Every primary resource — Client, BoxPlan, KitRevision, Component, ImportBatch, Subscriber, AssemblyRun, Shipment, ShippingWave, ReturnCase, and BillingStatement — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that starts at 1 when the resource is created and increments with every modification. Business narratives in §3 call out the specific transitions that bump a resource's `version`; those bumps are ordinary mutations and therefore also refresh `updated_at`.

Two resources are deliberately lighter. A KitBOMLine and an InventoryEvent each carry only `id` and `created_at`: both `updated_at` and `version` are absent for them, because a BOM line set is replaced wholesale rather than patched and an inventory event is an immutable ledger entry.

### 2.5. The Logical Clock

No rule in this system reads the wall clock. Every timestamp the server stamps and every temporal gate it enforces draws from a single server-side logical clock. Before it has ever been set, that clock reads exactly 2026-05-01T00:00:00Z; it never initializes from real time.

A `PlatformAdmin` advances the clock through an admin-only clock-setting capability that takes a `to_iso8601` instant. The supplied instant must be at or after the clock's current reading; a request that would move the clock backwards is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A successful call returns the clock's new reading as `current_utc`. Everything downstream — `approved_at` on revisions, `locked_at` on runs, `churned_at` on subscribers, `delivered_at` on shipments, the thirty-day return window, the statement period-end gate, shipping-wave pickup windows, and the report's churned-in-period window — reads this same clock, so tests and operators experience one consistent timeline.

### 2.6. Inventory Posture: the Component Ledger, Reservations, and Availability

Each component tracks two physical counters: `on_hand_units`, the units physically present, and `reserved_units`, the units promised to locked assembly runs. These counters change only through an append-only ledger of inventory events. Four event types exist, recorded in each event's `event_type` field: `RECEIPT`, `RESERVE`, `RELEASE`, and `COMMIT`. A `RECEIPT` adds its units to `on_hand_units`; a `COMMIT` removes its units from `on_hand_units`; `on_hand_units` never changes through any other event type. A `RESERVE` adds its units to `reserved_units`; a `RELEASE` subtracts its units from `reserved_units`; and a `COMMIT` also subtracts its units from `reserved_units` whenever the committed units had previously been reserved. Each event records the affected `component_id`, a signed `quantity_delta` describing exactly what it applied — positive for `RECEIPT` and `RESERVE` events, negative for `RELEASE` and `COMMIT` events — the `run_id` of the assembly run it belongs to (null for receipts, which exist outside any run), and an optional human `note` — receipts in particular may supply one. The ledger of a component is readable in chronological order, and the events belonging to a single run are equally readable through that run.

From these counters the server derives two availability figures, both integer unit counts with no rounding. `available_units` is `on_hand_units` minus `reserved_units` — the instantaneous view of what can be promised right now. `projected_available_units` is a forward-looking planning view: start from `available_units` and subtract the not-yet-reserved demand of every assembly run still in `DRAFT`. Each such run contributes, per BOM line of its plan's currently active revision that references this component, that line's `qty_per_box` multiplied by the number of the plan's subscribers currently in `ACTIVE` status; the contributions are summed across all qualifying draft runs and deducted. Only `DRAFT` runs feed this deduction: `LOCKED` runs are already reflected inside `reserved_units`, `KITTING` and `KITTED` runs are committed or in progress, and `CLOSED` or `CANCELLED` runs are excluded entirely. Consequently, identical physical inventory shows a lower `projected_available_units` whenever a draft run exists, while `available_units` ignores draft-run demand entirely. Reading a component returns both figures alongside `stock_status`, which reads `LOW` when `available_units` is less than or equal to the component's `reorder_point_units` and `OK` otherwise. Both figures are recomputed on every inventory event appended for that component. The hard gates in §3 — run locking and replacement resolution — always consult the instantaneous `available_units`; the projected figure informs planning only.

Two write-off principles keep the ledger honest. Kitted stock that has been committed for a box whose shipment is later cancelled is written off, never restocked into `on_hand_units`. And sending a run back for rework does not release inventory already committed — the reservation bookkeeping only ever moves forward.

### 2.7. Money, Precision, and the Prepaid Client Wallet

All monetary amounts in this system — prices, postage, credits, statement lines, and the wallet itself — are integer numbers of cents. Wherever a monetary computation can produce a fraction, the result is rounded half-up to whole cents; statement line items in particular are each rounded half-up to integer cents before any summation, per the pinned order in §3.7. The single non-integer numeric in the system is the report's fill-rate percentage, rounded half-up to one decimal place.

Every client holds a prepaid wallet, `credit_balance_cents`, which starts at exactly zero when the client is registered and can never be set directly at creation. Only four flows mutate it: explicit credit-adjustments, statement finalization, statement dispute, and dispute resolution. Of those flows, only statement finalization is gated on the wallet holding enough funds — run locking (§3.4) applies the same gate without moving money — while credit-adjustments and the dispute-cycle debits are never gated and may drive the balance below zero; the balance is both a balance and a credit check.

### 2.8. Optimistic Concurrency Control

Exactly two write endpoints carry an optimistic-concurrency guard, each keyed to its parent entity's `version`.

Creating a kit revision against a box plan requires the request to carry `expected_box_plan_version` holding the plan's `version` as the client last observed it. If the plan's `version` has advanced since that observation, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because creating a revision legitimately supersedes the plan's current draft revision, moving it to `RETIRED`; a writer holding a stale plan version must re-observe the plan before being allowed to supersede anything.

Recording a stock receipt against a component requires the request to carry `expected_component_version` holding the component's `version` as the client last observed it. A mismatch with the component's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Receipts legitimately accumulate — each one raises `on_hand_units` — so a stale writer would silently lose the intervening receipt's context; the stale request must re-observe first.

No other endpoint accepts a version field of any kind; all other mutations proceed without an OCC check.

### 2.9. Validation Order and Nested Resource Resolution

When several checks could reject the same request, the server evaluates them in one fixed priority order, and the earliest failing tier determines the error the caller sees:

1. **Authentication** — `X-User-Role` present and a declared role, `X-User-ID` present; failures yield `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization** — the role is admitted on the endpoint and, for an entity-backed `ClientOps` caller, the `X-User-ID` equals the owning client's `id` of the target plan, subscriber, import batch, or statement; failures yield `ERR_FORBIDDEN` (HTTP 403).
3. **Existence** — every identifier in the path template and every foreign key in the body — `client_id`, `plan_id`, `shipment_id`, each entry of `shipment_ids`, and each `component_id` inside `lines` — resolves to an existing resource; failures yield `ERR_NOT_FOUND` (HTTP 404).
4. **State** — the target entity sits in a valid from-state for the requested transition. The generic wrong-state rejection is `ERR_INVALID_STATE` (HTTP 409); domain-pinned state rejections are `ERR_PLAN_NOT_ACTIVE`, `ERR_PLAN_HAS_NO_APPROVED_REVISION`, `ERR_PLAN_HAS_OPEN_RUNS`, `ERR_REVISION_EMPTY_BOM`, `ERR_IMPORT_ALREADY_COMMITTED`, `ERR_LABEL_NOT_VOIDABLE`, `ERR_SHIPMENT_NOT_DELIVERED`, `ERR_RUN_HAS_COMMITTED_SHIPMENTS`, and `ERR_RUN_HAS_OPEN_SHIPMENTS`.
5. **Well-formedness and uniqueness** — domain invariants on the payload and its uniqueness footprint: a pickup window whose end is not strictly after its start (`ERR_INVALID_WINDOW`, HTTP 400); quantities that must be positive (`ERR_INVALID_QUANTITY`, HTTP 400); a kitted count above the plan (`ERR_KIT_COUNT_MISMATCH`); a rework re-completion below the previously kitted count (`ERR_REWORK_REGRESS`); plan and component SKU collisions (`ERR_DUPLICATE_SKU`); a second non-cancelled run for the same plan and period (`ERR_RUN_PERIOD_CONFLICT`); locking with no active subscribers (`ERR_RUN_EMPTY`); manifesting an empty wave (`ERR_WAVE_EMPTY`); and, riding with this same emptiness family, approving a revision that has no BOM lines (`ERR_REVISION_EMPTY_BOM`).
6. **Temporal rules** — same-carrier pickup-window collisions and insufficient gaps (`ERR_WAVE_WINDOW_CONFLICT`), a return approved beyond its thirty-day window (`ERR_RETURN_WINDOW_EXPIRED`), and a statement finalized before its period has ended (`ERR_STATEMENT_PERIOD_OPEN`).
7. **Money and capacity** — last of all, the fiscal and stock gates: an insufficient wallet at run lock or finalization (`ERR_INSUFFICIENT_CREDIT`) and insufficient available stock at run lock or replacement resolution (`ERR_COMPONENT_SHORTAGE`).

Two check families sit outside the numbered tiers. The generic malformed-payload rejection — a non-object JSON body, a missing required field, a wrongly typed value, or an unknown enum value — is `ERR_INVALID_REQUEST` (HTTP 400); it fires where the body is parsed, which is after path-identifier existence and authorization but before any foreign key carried in the body is resolved, and before the state check on `POST /subscribers/{id}/churn`, `POST /shipments/{id}/scan`, and `PUT /kit-revisions/{id}/bom-lines` (on all other transition endpoints the state check fires first). The optimistic-concurrency check of §2.8 sits immediately after basic payload validation and before the domain value checks of tier 5, so a stale `expected_*_version` paired with, for example, a non-positive receipt quantity is rejected with `ERR_STALE_VERSION`, not `ERR_INVALID_QUANTITY`.

For nested paths, identifiers are validated strictly left to right: the server confirms the parent resource exists before it ever looks for the child, and the first identifier that fails to resolve produces the `ERR_NOT_FOUND` rejection. This ordering applies equally to creation and modification calls under a parent collection.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and the Prepaid Wallet

A `PlatformAdmin` registers a brand client by supplying a display `name` and a `billing_email` for invoice delivery. The new client's `credit_balance_cents` is zero, and no creation payload may set it directly — a creation payload containing `credit_balance_cents` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Funds move through wallet adjustments. A `PlatformAdmin` or `BillingAdmin` posts a credit-adjustment with an `amount_cents` — positive to top the wallet up, negative to debit it, zero to change nothing — together with a free-text `reason`, which must be present but may be empty. The amount is added to `credit_balance_cents`, and the client's `version` increments by one. These adjustments are the only way funds enter the wallet outside the statement dispute cycle described in §3.7.

Client records are readable by `PlatformAdmin` and `BillingAdmin`, and by the owning `ClientOps` — a `ClientOps` caller presenting any other client's `id` is turned away with `ERR_FORBIDDEN`. A client's billing statements are listable under the client with optional `period` and `status` filters, and the client's per-period fulfillment report (§3.8) hangs off the same parent.

### 3.2. Box Plans and the Kit Revision Pipeline

A `ClientOps` operator defines what subscribers receive by creating a box plan: the owning `client_id` (which must equal the caller's own `X-User-ID`), a product `name`, a globally unique `sku`, the per-box kitting charge `price_per_box_cents` (must be greater than zero), and the packed `shipping_weight_grams` that later drives postage (must be greater than zero). A `sku` already in use by any box plan is rejected with `ERR_DUPLICATE_SKU`. New plans are born in `DRAFT` status with no `active_revision_id`. The plan directory supports listing with optional `client_id`, `status`, and `active_revision_id` filters, and any of the five roles can read a single plan.

What a box physically contains is versioned through kit revisions. Creating a new revision for a plan is OCC-guarded per §2.8 — the request must carry `expected_box_plan_version` — and always produces a fresh revision in `DRAFT`. Each revision receives a `revision_no`, a per-plan monotone counter starting at 1 for the plan's first revision and set to one greater than the highest existing `revision_no` of the plan thereafter. If the plan currently holds another `DRAFT` revision, that older draft automatically transitions `DRAFT → RETIRED` at the moment of creation, and the new revision's `supersedes_revision_id` (null when nothing was superseded) points at the retired draft; creating the revision also increments the plan's `version` by one. A plan's revisions are listable under it with an optional `status` filter, and a global revision listing supports `plan_id`, `supersedes_revision_id`, and `status` filters — the last of these enabling supersession lookups that answer "which revision replaced this one".

The bill of materials is authored in bulk: replacing the full BOM line set of a revision is a single transactional write — if any one line is invalid, the entire write is rejected and nothing changes. Each line names a `component_id` and a `qty_per_box`, the units of that component consumed per kitted box, which must be greater than zero; the same component may appear only once per revision, so the pairing of `revision_id` and `component_id` is unique across the line set — a repeated `component_id` within a submitted line set is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Only a `DRAFT` revision accepts a line-set replacement — attempting it on an `APPROVED` or `RETIRED` revision is rejected with `ERR_INVALID_STATE`. The previous lines of the revision are deleted and replaced wholesale, the response carries the full new line set as an array, and the replacement does not modify the KitRevision itself — its `version` and `updated_at` are left unchanged. BOM lines are listable per revision, and — from the warehouse's perspective — all lines referencing a given component are listable under that component.

Approval pins a revision as the plan's active BOM. Approving moves the revision `DRAFT → APPROVED` and is permitted only when the revision has at least one BOM line (an empty bill of materials is rejected with `ERR_REVISION_EMPTY_BOM`) and the owning plan is in `DRAFT` or `ACTIVE` status (otherwise `ERR_PLAN_NOT_ACTIVE`). Approval ripples outward: the plan's `active_revision_id` is set to this revision — it is set when a revision is approved and is never cleared afterward; the previously `APPROVED` revision of the same plan, if one exists, automatically transitions `APPROVED → RETIRED`; the newly approved revision's `approved_at` stamps the current clock (it stays null for any revision never approved); and both the plan's `version` and the revision's `version` increment by one.

Two lifecycle actions bracket a plan's selling life. Activation moves the plan `DRAFT → ACTIVE` and requires `active_revision_id` to be set — a plan with no approved revision is rejected with `ERR_PLAN_HAS_NO_APPROVED_REVISION` — and increments the plan's `version` by one. Retirement moves the plan `ACTIVE → RETIRED`, a terminal state, and is blocked while any assembly run of the plan stands in `LOCKED`, `KITTING`, or `KITTED` (rejected with `ERR_PLAN_HAS_OPEN_RUNS`); a successful retirement likewise increments the plan's `version` by one.

### 3.3. Subscriber Imports, Pause/Resume, and Churn

Subscriber lists arrive as bulk uploads. A `ClientOps` operator uploads a batch of raw `rows` against a plan — permitted whatever the plan's status; each row carries an `email`, an integer `zone` between 1 and 8 inclusive (the shipping zone that postage later reads), and an optional `full_name`. The batch is born `UPLOADED`, bound to the plan from the path as its `plan_id`, with its `total_rows` fixed at upload time as the number of rows submitted, both `accepted_count` and `rejected_count` standing at zero until a commit freezes them, and the submitted rows retained verbatim on the batch and returned as `rows` on every read. Batches of a plan are listable with an optional `status` filter.

Committing an `UPLOADED` batch performs the upsert, keyed on the pairing of `plan_id` and `email` — a subscriber's `email` is unique per plan and serves as the upsert key. Rows whose email is new to the plan create subscribers in `ACTIVE` status. Rows whose email matches an existing `ACTIVE` or `PAUSED` subscriber update that subscriber's `zone` and `full_name` (a row omitting `full_name` resets it to null) and refresh the subscriber's `import_batch_id` to this batch — `import_batch_id` always names the batch that created or last touched the subscriber. Four kinds of rows are skipped instead: a malformed email, a zone outside the 1-to-8 range, a duplicate email within the same file, or an email that is already `CHURNED` on this plan. Once the commit finishes, `accepted_count` (rows upserted) and `rejected_count` (rows skipped) are recomputed and frozen, and the batch moves `UPLOADED → COMMITTED`, which is terminal. Committing an already-committed batch is rejected with `ERR_IMPORT_ALREADY_COMMITTED`; reading a batch back shows the frozen counts.

The subscriber directory is listable with optional `plan_id`, `import_batch_id`, and `status` filters, and individual subscribers are readable by platform, brand, warehouse, and support roles. Within a plan, a subscriber moves `ACTIVE → PAUSED` on pause and `PAUSED → ACTIVE` on resume; each transition increments the subscriber's `version` by one. Churn — `ACTIVE → CHURNED` or `PAUSED → CHURNED` — is terminal: the operator must supply a `reason`, recorded into `churn_reason` as one of `PRICE`, `PRODUCT`, `MOVED`, or `OTHER` (`churn_reason` stays null for any subscriber never churned); the server stamps `churned_at` with the current clock (null for any subscriber never churned) and increments the subscriber's `version` by one. Churning from `ACTIVE` deliberately does not cancel any already-`QUEUED` shipments of that subscriber — locked run snapshots are honored, so a box already planned still ships. A subscriber's shipments are listable with an optional `fulfill_status` filter.

### 3.4. The Monthly Assembly Run

Before any run can lock, the warehouse builds its stock position. A `WarehouseOps` operator registers each component with a globally unique `sku` (collisions rejected with `ERR_DUPLICATE_SKU`), a display `name`, a `unit_cost_cents` reference cost used for replacement and restock decisions (zero is acceptable; negative is not), and an optional `reorder_point_units` threshold that defaults to 0 and must not be negative. A fresh component starts with `on_hand_units` 0 and `reserved_units` 0.

Stock arrives through receipts, the OCC-guarded write of §2.8: the request carries a `quantity`, the `expected_component_version`, and an optional `note`. The `quantity` must be a positive integer — anything else is rejected with `ERR_INVALID_QUANTITY` (HTTP 400) — and a version mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful receipt appends a `RECEIPT` inventory event whose `quantity_delta` is the received quantity and whose `run_id` is null, raises `on_hand_units` by that quantity, recomputes the component's availability figures and `stock_status`, and increments the component's `version` by one. A component's full ledger is readable chronologically with an optional `event_type` filter, and the events a run generated are equally listable under that run with the same optional `event_type` filter.

A monthly run begins when `WarehouseOps` creates an assembly run with a `plan_id` and a `period` — a year-and-month string in `YYYY-MM` format naming the billing and kitting month — permitted against a plan in any status, since the plan gates fire at lock, not at creation. Only one run per plan and period may exist outside the `CANCELLED` state; a second non-cancelled run for the same pairing is rejected with `ERR_RUN_PERIOD_CONFLICT`. New runs stand in `DRAFT` with `planned_box_count`, `kitted_box_count`, and `estimate_cents` all at 0. Runs of a plan are listable under it with optional `period` and `status` filters, and single runs are readable by platform, brand, warehouse, and finance roles.

Locking a run — `DRAFT → LOCKED` — is the most heavily gated transition in the system, and its checks fire in the priority order of §2.9: the plan must be `ACTIVE` (else `ERR_PLAN_NOT_ACTIVE`); the plan's `active_revision_id` must be set (else `ERR_PLAN_HAS_NO_APPROVED_REVISION`); at least one subscriber of the plan must be `ACTIVE` (else `ERR_RUN_EMPTY`); and only then do the money and capacity gates run. The lock first snapshots demand: `planned_box_count` becomes the count of the plan's subscribers in `ACTIVE` status at the lock instant — `PAUSED` and `CHURNED` subscribers are excluded. From that snapshot the estimate freezes: `estimate_cents` becomes `planned_box_count` multiplied by the plan's `price_per_box_cents`, and `locked_at` stamps the clock (it stays null until a run locks). The credit gate requires the client's `credit_balance_cents` to be at least `estimate_cents` — equality passes — and rejects otherwise with `ERR_INSUFFICIENT_CREDIT`. The shortage gate requires, for every BOM line of the active revision, that the component's `available_units` be at least the line's `qty_per_box` multiplied by `planned_box_count`, rejecting with `ERR_COMPONENT_SHORTAGE` on any shortfall.

A successful lock does five things atomically. It appends one `RESERVE` inventory event per BOM line, with a positive `quantity_delta` equal to that line's required units, and raises each component's `reserved_units` by the same amount, recomputing `available_units`, `projected_available_units`, and `stock_status` for every touched component. It creates one shipment per snapshotted subscriber — iterating subscribers by `created_at` ascending with ties broken by creation (insertion) order — each shipment born with `fulfill_status` `QUEUED`, `label_status` `NONE`, and `postage_cents` 0. It finds-or-creates the client's billing statement for the run's `period` in `PROVISIONAL` status and immediately runs the provisional statement variant (§3.7), storing the computed amounts. And it increments the run's `version` by one.

Kitting then proceeds in two beats. Starting kitting moves `LOCKED → KITTING` and increments the run's `version`. Completing kitting moves `KITTING → KITTED` on a supplied `actual_kitted_count`. The count must be at least 1 (else `ERR_INVALID_QUANTITY`, HTTP 400) and no more than `planned_box_count` (else `ERR_KIT_COUNT_MISMATCH`). When completion follows a rework loop, two further guards apply: the new count must not fall below the run's current `kitted_box_count` (else `ERR_REWORK_REGRESS`), and every BOM line's component must have `available_units` of at least `qty_per_box` multiplied by the difference between `actual_kitted_count` and `kitted_box_count` (else `ERR_COMPONENT_SHORTAGE`).

Completion's inventory effects depend on whether it is the first. The newly committed quantity per line is always `actual_kitted_count` minus the run's current `kitted_box_count`; on a first completion that difference equals `actual_kitted_count` itself, and whenever the difference is zero nothing is consumed. On a first completion — when `kitted_box_count` was 0 — `COMMIT` events consume from the run's own reservation: per BOM line, `on_hand_units` and `reserved_units` each drop by `qty_per_box` multiplied by the committed quantity. `RELEASE` events then release the remaining reservation — `planned_box_count` minus `actual_kitted_count` units per line — leaving the run with zero open reservation. On a completion after rework, the reservation is already gone, so `COMMIT` events draw straight from stock: `on_hand_units` alone drops by the delta quantity per line. A first completion that kitted fewer boxes than planned also triggers excess shipment selection, exactly once per run: the excess is `planned_box_count` minus `actual_kitted_count`, the candidates are the run's shipments still in `QUEUED`, ordered by their subscriber's `created_at` descending with ties broken by reverse creation (insertion) order — so the most recently created subscribers are cancelled first — and the first excess-count candidates are cancelled to `CANCELLED`. This selection never re-runs and never un-cancels; re-completions after a rework loop commit deltas only. Shipments the run keeps move `QUEUED → STAGED` at completion. Finally, `kitted_box_count` is set to `actual_kitted_count`, touched components recompute their `stock_status`, and the run's `version` increments by one.

A run that failed quality checks can be sent back: rework moves `KITTED → KITTING`, accepts a free-text `note` (accepted but not persisted anywhere), and increments the run's `version` — but only while no shipment of the run stands in `ASSIGNED`, `MANIFESTED`, `SHIPPED`, `DELIVERED`, or `RETURNED` (else `ERR_RUN_HAS_COMMITTED_SHIPMENTS`). Inventory committed so far is not released back; the next completion commits only the positive delta from unreserved stock.

Closing a run — `KITTED → CLOSED`, terminal — is the administrative end state, permitted only once every shipment of the run is settled, meaning none stands in `QUEUED`, `STAGED`, `ASSIGNED`, or `MANIFESTED` (else `ERR_RUN_HAS_OPEN_SHIPMENTS`); the run's `version` increments by one. Cancelling is the other exit: a `DRAFT → CANCELLED` cancellation carries only a version increment, while a `LOCKED → CANCELLED` cancellation appends `RELEASE` events for the full remaining reservation of every BOM line of the plan's active revision at the moment of cancellation (lowering each component's `reserved_units` accordingly), moves the run's `QUEUED` shipments to `CANCELLED`, recomputes the touched components' `stock_status`, and increments the run's `version`. Because the period-conflict rule counts only non-cancelled runs, a cancelled run frees its plan-and-period pairing for a future attempt.

### 3.5. Shipping Waves, Labels, and Carrier Scans

Outbound logistics is organized into shipping waves, each a carrier pickup appointment. Scheduling a wave takes a `carrier` — `USPS`, `UPS`, or `FEDEX`, the resource whose pickup windows cannot collide — a `service_level` of `GROUND` or `EXPRESS`, and the half-open pickup window `pickup_start` to `pickup_end`: the window includes its start instant and excludes its end instant, and the end must be strictly later than the start, with a malformed interval rejected as `ERR_INVALID_WINDOW` (HTTP 400). A malformed window takes precedence over any overlap finding. Against every non-`CANCELLED` wave of the same carrier, a new window may not overlap — half-open comparisons, so one window ending exactly as another begins is not an overlap — and the gap between one window's end and the next window's start must be at least thirty minutes; either violation is rejected with `ERR_WAVE_WINDOW_CONFLICT` (HTTP 409). A new wave stands in `SCHEDULED` with `assigned_count` 0 — the count of its linked shipments in `ASSIGNED` or `MANIFESTED` — and both the wave and its currently linked shipments (optionally filtered by `fulfill_status`) are readable thereafter.

Staged boxes join a wave through a bulk assignment by `WarehouseOps`, naming the shipments by `shipment_ids`. The call is transactional: if any named shipment is ineligible, the whole assignment is rejected. A shipment is eligible only when the wave is `SCHEDULED`, the shipment itself stands in `STAGED` with a `label_status` of `NONE` or `VOIDED`, and its owning run stands in `KITTING`, `KITTED`, or `CLOSED`; each violation surfaces as `ERR_INVALID_STATE` (HTTP 409). Each assigned shipment moves `STAGED → ASSIGNED`, its `wave_id` (null until first assignment) is set to the wave, and the wave's `assigned_count` is recomputed. The response carries the wave, with its recomputed `assigned_count`.

Manifesting the wave — `SCHEDULED → MANIFESTED` — requires at least one assigned shipment (an empty wave is rejected with `ERR_WAVE_EMPTY`) and purchases one label per assigned shipment. For each, the shipment moves `ASSIGNED → MANIFESTED`, its postage is computed and stored in `postage_cents`, its `label_status` becomes `PURCHASED`, and a fresh `tracking_code` is minted — null until the first purchase, and re-minted at every subsequent purchase. The period's billing statement, if one exists, recomputes its provisional postage. The wave's `version` increments by one.

Postage pricing is tiered and computed in integer cents. The packed weight from the plan's `shipping_weight_grams` is divided into 500-gram slabs, rounding up to a whole number of slabs. A service base applies — 320 cents for `GROUND`, 745 cents for `EXPRESS` — plus a per-slab rate read from the subscriber's `zone`: 25 cents for zone 1, 40 for zone 2, 55 for zone 3, 75 for zone 4, 95 for zone 5, 120 for zone 6, 150 for zone 7, and 185 for zone 8. The raw charge is the base plus the zone rate multiplied by the slab count, and it is then raised to the service minimum if it falls short — 450 cents for `GROUND`, 990 cents for `EXPRESS`. Finally, an `EXPRESS` shipment to zone 5 or higher attracts a 200-cent remote surcharge. The only rounding anywhere in this calculation is the upward rounding of the weight division into whole slabs.

Tendering — `MANIFESTED → TENDERED`, terminal for the wave — hands the wave to the carrier: every `MANIFESTED` shipment of the wave moves `MANIFESTED → SHIPPED`, and the wave's `version` increments. Cancelling unwinds differently depending on where the wave stood, and in both cases the wave itself settles in `CANCELLED`, which — like `TENDERED` — is terminal. From `SCHEDULED` (`SCHEDULED → CANCELLED`), each assigned shipment reverts `ASSIGNED → STAGED` with its `wave_id` cleared back to null, and the wave's `version` increments. From `MANIFESTED` (`MANIFESTED → CANCELLED`), each manifested shipment likewise reverts `MANIFESTED → STAGED` with `wave_id` cleared, every `PURCHASED` label flips to `VOIDED`, the period's statement (if any) recomputes its provisional postage, and the wave's `version` increments.

Labels live on a parallel dimension of the shipment, independent of fulfillment: `label_status` walks `NONE → PURCHASED → VOIDED`, with `VOIDED → PURCHASED` additionally allowed when a shipment is re-manifested after a void or wave cancel. Fulfillment transitions never read `label_status`, and label transitions never read `fulfill_status` beyond one guard: voiding a label is permitted only while the shipment's `fulfill_status` is `MANIFESTED` and its `label_status` is `PURCHASED`, anything else being rejected with `ERR_LABEL_NOT_VOIDABLE`. A void leaves `fulfill_status` untouched, flips the label to `VOIDED`, keeps the last purchased `postage_cents` on the shipment for audit, and triggers the period statement's provisional postage recompute.

Two shipment-level actions close out the lifecycle. Cancelling a shipment — `QUEUED → CANCELLED` or `STAGED → CANCELLED`, and rejected from any other `fulfill_status` with `ERR_INVALID_STATE` — abandons an unshipped box; kitted stock already committed for that box is written off, not restocked. Carrier scans move `SHIPPED` boxes to their terminal state: a `scan_type` of `DELIVERED` moves the shipment `SHIPPED → DELIVERED` and stamps `delivered_at` with the current clock (null until that scan), while a `scan_type` of `RETURNED` moves it `SHIPPED → RETURNED`; a scan against a shipment in any other `fulfill_status` is rejected with `ERR_INVALID_STATE` (HTTP 409). `DELIVERED`, `RETURNED`, and `CANCELLED` are the shipment's terminal fulfillments. Runs and subscribers each expose their shipment listings — a run's list accepts optional `fulfill_status` and `label_status` filters — and individual shipments are readable by platform, brand, warehouse, and support roles.

### 3.6. Returns and Replacements

When a delivered box comes back, a `CustomerService` agent opens a return case naming the `shipment_id` of the delivered box, a `reason` of `DAMAGED`, `LOST`, `WRONG_ITEM`, or `OTHER`, and a `requested_resolution` of `REPLACE` or `REFUND`. The case is born `REQUESTED`. Opening a case performs no fulfillment-state check on the shipment — the `DELIVERED` gate fires only at approval — and one shipment may accumulate any number of cases. The case register supports listing with optional `shipment_id`, `replacement_shipment_id`, and `status` filters.

Adjudication has two doors. Approving moves `REQUESTED → APPROVED` and is guarded twice, in §2.9 order: the referenced shipment must stand in `DELIVERED` (else `ERR_SHIPMENT_NOT_DELIVERED`), and the current clock must read no later than thirty days after that shipment's `delivered_at` (else `ERR_RETURN_WINDOW_EXPIRED`); approval increments the case's `version`. Rejecting moves `REQUESTED → REJECTED`, terminal, accepts an optional `note` (accepted but not persisted), and likewise increments the case's `version`.

An approved case waits for the physical box: a `WarehouseOps` receiving action moves `APPROVED → RECEIVED` and increments the case's `version`. Resolution — `RECEIVED → RESOLVED`, terminal, by `CustomerService` — then branches on the requested resolution, and both branches increment the case's `version` by one.

The `REPLACE` branch first re-checks stock against the plan's active revision: for every BOM line, the component's `available_units` must be at least the line's `qty_per_box` — one box's worth — else the resolution is rejected with `ERR_COMPONENT_SHORTAGE`. On success the server creates a replacement shipment bound to the same `run_id` and `subscriber_id` as the original, flagged `is_replacement` true (a flag that is false on every ordinary shipment), standing in `STAGED` with `label_status` `NONE`; appends `COMMIT` inventory events per BOM line for one box, dropping each component's `on_hand_units` by the line's `qty_per_box`; recomputes the touched components' `stock_status`; records the new shipment's `id` in `replacement_shipment_id` (null on cases resolved any other way); and stamps `resolution_applied` as `REPLACED`.

The `REFUND` branch sets the case's `credit_cents` (zero until resolution) to the plan's `price_per_box_cents`, adds that amount into the period billing statement's `refund_credit_cents` when a statement exists, triggers the statement's provisional recompute, and stamps `resolution_applied` as `REFUNDED`. `resolution_applied` stays null until a case resolves.

### 3.7. Per-Box Billing: Statements, Finalization, and Disputes

Billing accumulates on the BillingStatement, one per client per period — the pairing of `client_id` and `period` is unique per client. A statement is found-or-created in `PROVISIONAL` status the first time a run of that client and period locks, with `box_charge_cents`, `postage_cents`, `refund_credit_cents`, `discount_pct`, `adjustment_credit_cents`, and `net_cents` all starting at 0 before the first recompute stores real amounts. Thereafter, while the statement is `PROVISIONAL`, five events each trigger a full provisional recompute: a run lock (the find-or-create itself), a label purchase at wave manifest, a label void, a wave cancel, and a return resolved as `REFUND`. A provisional recompute stores the recomputed figures and increments the statement's `version` only when at least one computed figure actually changed; an idempotent recompute leaves the statement untouched.

The statement computation itself has two variants — provisional and final — and a pinned eight-step evaluation order that resolves the otherwise circular dependency between volume tiers and line charges. Step one fixes the run set: the client's assembly runs whose `period` equals the statement's `period` and whose status is `KITTED` or `CLOSED`. Step two fixes the volume basis: the sum of `planned_box_count` across the run set in the provisional variant, or of `kitted_box_count` in the final variant. Step three sets `discount_pct`: 10 when the volume basis reaches at least 500 boxes, else 5 when it reaches at least 200 boxes, else 0. Step four prices each run in the set: the run's boxes are its `planned_box_count` in the provisional variant or its `kitted_box_count` in the final variant, and the line charge is the plan's `price_per_box_cents` multiplied by those boxes and then reduced by `discount_pct` percent. Each run's line charge is rounded half-up to whole cents first, and only then are the rounded line charges summed — summing unrounded amounts and rounding once at the end is a rejected interpretation. Step five sums those rounded lines into `box_charge_cents`. Step six sums, into `postage_cents`, the `postage_cents` of every shipment of the run set whose `label_status` is `PURCHASED` — identical in both variants, which is why voided labels and wave cancels move the provisional number. Step seven sums, into `refund_credit_cents`, the `credit_cents` of every return case in `RESOLVED` status with `resolution_applied` `REFUNDED` whose shipment belongs to a run in the set. Step eight computes `net_cents` as `box_charge_cents` plus `postage_cents` minus `refund_credit_cents` minus `adjustment_credit_cents`. Because the two variants differ only in using planned versus actually-kitted box counts, identical inputs yield a different net whenever kitted and planned disagree or the discount tier flips between them.

Finalization — `PROVISIONAL → FINALIZED`, by `BillingAdmin` — is gated on time and money. The current clock must read at or after the first instant of the month following the statement's `period` (else `ERR_STATEMENT_PERIOD_OPEN`). The final variant then recomputes and overwrites `box_charge_cents`, `postage_cents`, `refund_credit_cents`, `discount_pct`, and `net_cents`, and the client's `credit_balance_cents` must be at least that freshly computed `net_cents` (else `ERR_INSUFFICIENT_CREDIT`). On success the wallet is debited by `net_cents` and the statement's `version` increments by one.

A client that disagrees disputes: a `ClientOps` caller of the statement's own client — anyone else is rejected with `ERR_FORBIDDEN` — moves the statement `FINALIZED → DISPUTED`, which credits the wallet back in full by adding `net_cents` to `credit_balance_cents` as a provisional refund while the dispute is open, and increments the statement's `version`. A `BillingAdmin` then resolves the dispute by supplying an `adjustment_credit_cents` goodwill amount that must lie between zero and the statement's `net_cents`, both ends inclusive (outside that range, `ERR_INVALID_QUANTITY`, HTTP 400). Resolution records the adjustment, reduces `net_cents` by it, re-debits the reduced `net_cents` from the wallet, moves the statement `DISPUTED → FINALIZED`, and increments its `version`. Finally, once external payment is acknowledged, marking paid moves `FINALIZED → PAID` — the terminal state — leaving the wallet untouched and incrementing the statement's `version`.

### 3.8. Fulfillment Reporting

Operations reviews run on a per-client, per-period fulfillment report, readable by `PlatformAdmin`, `ClientOps`, and `WarehouseOps` for a supplied `period`. The report's run set is the client's assembly runs for that period standing in `LOCKED`, `KITTING`, `KITTED`, or `CLOSED`; `DRAFT` and `CANCELLED` runs are excluded.

Seven figures come back. `period` echoes the requested period. `planned_boxes` sums the run set's `planned_box_count`, and `kitted_boxes` sums its `kitted_box_count`. `shipped_boxes` counts the run set's shipments in `SHIPPED`, `DELIVERED`, or `RETURNED`, while `returned_boxes` counts those in `RETURNED` alone. `active_subscribers` counts subscribers across all of the client's plans currently in `ACTIVE`. `churned_in_period` counts subscribers of the client's plans whose `churned_at` falls inside the period — from midnight UTC on the first day of the period up to but not including the first instant of the following month. `fill_rate_pct` divides `kitted_boxes` by `planned_boxes`, multiplies by 100, and rounds half-up to one decimal place; when `planned_boxes` is zero it reports 0.0. All counts are integers.

## 4. Endpoint Definitions

Endpoints that create a brand-new resource — registering a client, creating a box plan, minting a kit revision, uploading an import batch, registering a component, creating an assembly run, scheduling a shipping wave, or opening a return case — return `201 Created`. Every other successful operation — reads, state transitions, and mutations of existing resources — returns `200 OK`. The table below summarizes the HTTP contract only; request payloads, response contents, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/clients` | Register a brand client | PlatformAdmin |
| GET | `/clients/{id}` | Read a client | PlatformAdmin, ClientOps, BillingAdmin |
| POST | `/clients/{id}/credit-adjustments` | Top up or debit the client's prepaid wallet | PlatformAdmin, BillingAdmin |
| GET | `/clients/{id}/billing-statements` | List billing statements of a client | PlatformAdmin, ClientOps, BillingAdmin |
| GET | `/clients/{id}/reports/fulfillment-summary` | Computed per-period fulfillment report | PlatformAdmin, ClientOps, WarehouseOps |
| POST | `/box-plans` | Create a box plan (status DRAFT) | ClientOps, PlatformAdmin |
| GET | `/box-plans` | List and filter box plans | PlatformAdmin, ClientOps, WarehouseOps, BillingAdmin |
| GET | `/box-plans/{id}` | Read a box plan | PlatformAdmin, ClientOps, WarehouseOps, BillingAdmin, CustomerService |
| POST | `/box-plans/{id}/activate` | Activate a plan (requires an APPROVED revision) | ClientOps |
| POST | `/box-plans/{id}/retire` | Retire a plan (blocked while a run is LOCKED/KITTING/KITTED) | ClientOps |
| POST | `/box-plans/{id}/kit-revisions` | Create a new DRAFT kit revision, superseding the current draft (OCC-guarded) | ClientOps |
| GET | `/box-plans/{id}/kit-revisions` | List revisions of a plan | PlatformAdmin, ClientOps, WarehouseOps |
| POST | `/box-plans/{id}/import-batches` | Upload a subscriber list for this plan | ClientOps |
| GET | `/box-plans/{id}/import-batches` | List import batches of a plan | PlatformAdmin, ClientOps |
| GET | `/box-plans/{id}/assembly-runs` | List assembly runs of a plan | PlatformAdmin, ClientOps, WarehouseOps |
| GET | `/kit-revisions/{id}` | Read a kit revision | PlatformAdmin, ClientOps, WarehouseOps |
| GET | `/kit-revisions` | List and filter kit revisions, including supersession lookups | PlatformAdmin, ClientOps, WarehouseOps |
| POST | `/kit-revisions/{id}/approve` | Approve a DRAFT revision as the plan's active BOM | ClientOps |
| PUT | `/kit-revisions/{id}/bom-lines` | Replace the full BOM line set of a DRAFT revision | ClientOps |
| GET | `/kit-revisions/{id}/bom-lines` | List BOM lines of a revision | PlatformAdmin, ClientOps, WarehouseOps |
| POST | `/components` | Register a component | WarehouseOps |
| GET | `/components/{id}` | Read a component, including availability figures and stock status | PlatformAdmin, ClientOps, WarehouseOps, BillingAdmin |
| GET | `/components/{id}/bom-lines` | List BOM lines referencing this component | PlatformAdmin, ClientOps, WarehouseOps |
| POST | `/components/{id}/receipts` | Record a stock receipt (OCC-guarded) | WarehouseOps |
| GET | `/components/{id}/inventory-events` | Chronological inventory-event ledger of the component | PlatformAdmin, ClientOps, WarehouseOps |
| GET | `/import-batches/{id}` | Read an import batch, including counts after commit | PlatformAdmin, ClientOps |
| POST | `/import-batches/{id}/commit` | Commit an UPLOADED batch, upserting subscribers | ClientOps |
| GET | `/subscribers` | List and filter subscribers | PlatformAdmin, ClientOps, WarehouseOps, CustomerService |
| GET | `/subscribers/{id}` | Read a subscriber | PlatformAdmin, ClientOps, WarehouseOps, CustomerService |
| POST | `/subscribers/{id}/pause` | Pause an ACTIVE subscriber | ClientOps |
| POST | `/subscribers/{id}/resume` | Resume a PAUSED subscriber | ClientOps |
| POST | `/subscribers/{id}/churn` | Churn a subscriber (terminal) | ClientOps |
| GET | `/subscribers/{id}/shipments` | List shipments of a subscriber | PlatformAdmin, ClientOps, WarehouseOps, CustomerService |
| POST | `/assembly-runs` | Create a DRAFT assembly run for a plan and period | WarehouseOps |
| GET | `/assembly-runs/{id}` | Read an assembly run | PlatformAdmin, ClientOps, WarehouseOps, BillingAdmin |
| GET | `/assembly-runs/{id}/shipments` | List shipments of a run | PlatformAdmin, ClientOps, WarehouseOps, CustomerService |
| GET | `/assembly-runs/{id}/inventory-events` | List inventory events tagged with this run | PlatformAdmin, ClientOps, WarehouseOps |
| POST | `/assembly-runs/{id}/lock` | Lock a run: snapshot subscribers, reserve components, freeze estimate | WarehouseOps |
| POST | `/assembly-runs/{id}/start-kitting` | Move a LOCKED run to KITTING | WarehouseOps |
| POST | `/assembly-runs/{id}/complete-kitting` | Complete kitting: commit inventory, release excess, cancel excess shipments | WarehouseOps |
| POST | `/assembly-runs/{id}/rework` | Send a KITTED run back to KITTING | WarehouseOps |
| POST | `/assembly-runs/{id}/close` | Close a KITTED run whose shipments are all settled | WarehouseOps |
| POST | `/assembly-runs/{id}/cancel` | Cancel a DRAFT or LOCKED run, releasing reservations | WarehouseOps |
| POST | `/shipping-waves` | Schedule a shipping wave with a non-colliding pickup window | WarehouseOps |
| GET | `/shipping-waves/{id}` | Read a shipping wave | PlatformAdmin, ClientOps, WarehouseOps |
| GET | `/shipping-waves/{id}/shipments` | List shipments currently linked to the wave | PlatformAdmin, ClientOps, WarehouseOps, CustomerService |
| POST | `/shipping-waves/{id}/assign-shipments` | Assign STAGED shipments to a SCHEDULED wave (bulk, transactional) | WarehouseOps |
| POST | `/shipping-waves/{id}/manifest` | Manifest a wave, purchasing a label per assigned shipment | WarehouseOps |
| POST | `/shipping-waves/{id}/tender` | Tender a manifested wave to the carrier | WarehouseOps |
| POST | `/shipping-waves/{id}/cancel` | Cancel a wave, reverting shipments and voiding labels | WarehouseOps |
| GET | `/shipments/{id}` | Read a shipment | PlatformAdmin, ClientOps, WarehouseOps, CustomerService |
| POST | `/shipments/{id}/cancel` | Cancel an unshipped shipment (committed stock written off) | WarehouseOps |
| POST | `/shipments/{id}/void-label` | Void a purchased label while still MANIFESTED | WarehouseOps |
| POST | `/shipments/{id}/scan` | Record a carrier scan: delivered or returned | WarehouseOps |
| POST | `/return-cases` | Open a return or replacement case against a shipment | CustomerService |
| GET | `/return-cases` | List and filter return cases | PlatformAdmin, ClientOps, WarehouseOps, CustomerService |
| GET | `/return-cases/{id}` | Read a return case | PlatformAdmin, ClientOps, WarehouseOps, CustomerService |
| POST | `/return-cases/{id}/approve` | Approve a requested return (DELIVERED, within 30 days) | CustomerService |
| POST | `/return-cases/{id}/reject` | Reject a requested return | CustomerService |
| POST | `/return-cases/{id}/receive` | Mark an approved return as physically received | WarehouseOps |
| POST | `/return-cases/{id}/resolve` | Resolve a received return: replacement or refund | CustomerService |
| GET | `/billing-statements/{id}` | Read a billing statement | PlatformAdmin, ClientOps, BillingAdmin |
| POST | `/billing-statements/{id}/finalize` | Finalize a provisional statement (final recompute and wallet debit) | BillingAdmin |
| POST | `/billing-statements/{id}/dispute` | Dispute a finalized statement (full provisional wallet refund) | ClientOps |
| POST | `/billing-statements/{id}/resolve-dispute` | Resolve a dispute with a goodwill adjustment | BillingAdmin |
| POST | `/billing-statements/{id}/mark-paid` | Mark a finalized statement as paid | BillingAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions for each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_HAS_NO_APPROVED_REVISION` | 409 Conflict |
| `ERR_PLAN_HAS_OPEN_RUNS` | 409 Conflict |
| `ERR_REVISION_EMPTY_BOM` | 409 Conflict |
| `ERR_IMPORT_ALREADY_COMMITTED` | 409 Conflict |
| `ERR_RUN_PERIOD_CONFLICT` | 409 Conflict |
| `ERR_RUN_EMPTY` | 409 Conflict |
| `ERR_INVALID_QUANTITY` | 400 Bad Request |
| `ERR_KIT_COUNT_MISMATCH` | 409 Conflict |
| `ERR_REWORK_REGRESS` | 409 Conflict |
| `ERR_RUN_HAS_COMMITTED_SHIPMENTS` | 409 Conflict |
| `ERR_RUN_HAS_OPEN_SHIPMENTS` | 409 Conflict |
| `ERR_COMPONENT_SHORTAGE` | 409 Conflict |
| `ERR_INSUFFICIENT_CREDIT` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_WAVE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_WAVE_EMPTY` | 409 Conflict |
| `ERR_LABEL_NOT_VOIDABLE` | 409 Conflict |
| `ERR_SHIPMENT_NOT_DELIVERED` | 409 Conflict |
| `ERR_RETURN_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_STATEMENT_PERIOD_OPEN` | 409 Conflict |

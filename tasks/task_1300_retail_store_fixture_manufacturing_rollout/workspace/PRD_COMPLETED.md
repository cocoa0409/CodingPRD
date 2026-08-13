# Fixture Rollout API — Product Requirements Document

## 1. Introduction

A store fixture manufacturer lives and dies by the rollout calendar. When a retail chain signs off on a refresh program — new gondolas, endcaps, and shelving across hundreds of stores — the manufacturer must shepherd each fixture from a prototype drawing through value engineering, derive a kit configuration for every individual store, book factory capacity in production waves, stage finished kits in warehouse bays, deliver them with install crews, and absorb the inevitable damage and missing-part calls from the field. At the end of the program, leftover "attic stock" held at each store must be valued, disposed of, and reconciled against the program budget. Today this work is coordinated over spreadsheets and phone calls, and the financial leakage — unbudgeted freight, unbilled rush production, unrecovered attic stock — is significant.

This document specifies the Fixture Rollout API, the system of record for that entire lifecycle. It governs nine resource types — rollout programs, fixture prototypes, store kit configurations, production waves, staging reservations, install deliveries, damage claims, installation signoffs, and attic stock ledgers — and the approval chains that connect them: engineers and coordinators submit, program managers and store managers approve, and the server itself advances resources when time, capacity, or cascade criteria are met. The API enforces segregated duties, optimistic concurrency on the two resources that field staff edit most aggressively, tiered production pricing that responds to wave utilization, and a strict validation precedence so that an operator always learns about the most fundamental problem first. It is written for the engineering team that will implement the service; every behavioral rule stated here is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contract that applies to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request in which either header is missing, empty, or whitespace-only is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other processing occurs. The system recognizes exactly nine roles, spelled as follows: `ProgramManager`, `FixtureEngineer`, `ConfigCoordinator`, `ProductionPlanner`, `WarehouseLead`, `InstallCrewLead`, `HotlineAgent`, `StoreManager`, and `PlatformAdmin`. When the role named in `X-User-Role` is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403); a role header value naming none of the nine recognized roles is treated as not permitted on every endpoint, reads included.

For every one of these nine roles — `ProgramManager`, `FixtureEngineer`, `ConfigCoordinator`, `ProductionPlanner`, `WarehouseLead`, `InstallCrewLead`, `HotlineAgent`, `StoreManager`, and `PlatformAdmin` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared against any resource's `id`. The server does record the header on resources where a transition captures an actor — for example `submitted_by_user_id` on a prototype or signoff, `approved_by_user_id` on a prototype, and `reviewed_by_user_id` on a signoff — and the segregation-of-duties rules described in §3 compare the incoming `X-User-ID` against those recorded values, but no ownership check against an entity identifier is ever performed.

Read endpoints (single-resource retrieval and list retrieval) are available to any authenticated caller presenting one of the nine roles. Write operations are restricted per the endpoint table in §4.

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

Requests that match no defined route are rejected with `ERR_NOT_FOUND` (HTTP 404), requests that use an unsupported method on a defined route with `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and an unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500); all three use this same error envelope.

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`; an empty `limit` or `offset` value is treated as omitted. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id` in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items in the returned page is less than `total_count`.

List endpoints also accept resource-specific filter parameters. Each filter is an exact-match equality test on the named resource field, and a filter parameter with an empty value is ignored. Programs filter by `status`. Prototypes filter by `program_id` and `status`. Kit configurations filter by `program_id`, `prototype_id`, `wave_id`, and `status`. Production waves filter by `program_id` and `status`. Staging reservations filter by `kit_id`, `staging_bay_code`, and `status`. Install deliveries filter by `kit_id`, `crew_code`, `delivery_date`, and `status`. Damage claims and install signoffs each filter by `delivery_id` and `status`. Attic stock ledgers filter by `kit_id` and `status`.

### 2.4. Common Resource Properties

Every resource in this API — rollout program, fixture prototype, store kit configuration, production wave, staging reservation, install delivery, damage claim, install signoff, and attic stock ledger — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted UUID with no type prefix, assigned at creation.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource. Both timestamps are recorded from wall-clock UTC and are independent of the logical clock described in §2.8.
- **`version` (integer):** a system-managed integer that starts at 1 at creation and increments by one on every mutation, whether the mutation comes from a direct client action or from an automatic cascade touching the resource.

This uniform audit trail is what the optimistic concurrency rules in §2.6 build upon.

### 2.5. Monetary Precision and Rounding Discipline

All monetary amounts in the system are integer counts of cents. Wherever a calculation produces a fractional cent, the result is rounded half up to a whole cent — a discarded fraction of exactly one-half cent rounds away from zero. Two aggregation rules in this domain pin the rounding order explicitly, because the order changes the answer: prototype cost estimates and kit cost totals both round each individual line to a whole cent first and then sum the rounded line amounts. Summing raw unrounded line amounts and rounding once at the end is not an acceptable substitute and will be treated as a defect, since it yields a different cent value whenever two or more lines produce fractional cents.

Utilization percentages are the one non-monetary exception to integer precision: a wave's `utilization_pct` is rounded half up to exactly one decimal place. Timestamps are compared exactly as ISO 8601 instants with no tolerance window.

### 2.6. Optimistic Concurrency Control

Two write operations in the API are protected by optimistic concurrency control, and both work the same way: the request body must carry the caller's last-observed `version` of the resource being modified, and the server rejects the write when that expectation no longer matches the resource's current `version`. On either operation a missing or non-integer expectation is rejected with `ERR_INVALID_REQUEST`, and the version match is evaluated only after the target resource's own state gate and the body's other required fields have been validated — on ledger adjustment it fires before the stock-underflow rule.

The first protected operation is `PATCH /store-kit-configs/{id}`. Its request body must include `expected_config_version`, a non-optional field carrying the kit configuration's `version` as the client last read it. A writer whose expectation is older than the kit's current version has missed an intervening patch or cascade; the patch is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the kit before writing.

The second protected operation is `POST /attic-stock-ledgers/{id}/adjust`. Its request body must include `expected_ledger_version`, likewise non-optional, so that every quantity or reorder-point change builds on the latest observed ledger state. A mismatch with the ledger's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint in the API accepts a version field; these two are the complete list.

### 2.7. Validation Order and Error Precedence

When a single request violates several rules at once, the server does not choose a failure arbitrarily — checks are evaluated in a fixed precedence, and the earliest failing category determines the error returned. The order is:

1. **Credentials first.** Presence and non-emptiness of `X-User-ID` and `X-User-Role` (§2.1). A failure here yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and nothing else is examined.
2. **Role authorization second.** Whether the authenticated role may perform this operation at all; failure yields `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Path existence third.** Identifiers embedded in the URL are resolved strictly left to right; the first identifier that does not correspond to an existing resource produces that resource's not-found error — `ERR_PROGRAM_NOT_FOUND`, `ERR_PROTOTYPE_NOT_FOUND`, `ERR_KIT_CONFIG_NOT_FOUND`, `ERR_WAVE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_SIGNOFF_NOT_FOUND`, or `ERR_LEDGER_NOT_FOUND` — and later path segments are never evaluated.
4. **Body-referenced existence fourth.** Identifiers supplied in the request body are checked next: on kit creation the `program_id` first and then the `prototype_id`, the `program_id` on prototype and wave creation, the `kit_id` on reservation and delivery creation, and the `delivery_id` on claim and signoff creation. A wave reference that exists but belongs to a different program than the releasing kit is reported as `ERR_WAVE_NOT_FOUND`, not as a permission or state failure. On kit release the `wave_id` reference is resolved only after the releasing kit's own `FROZEN` gate passes, as narrated in §3.4. One refinement positions the creation endpoints precisely: a creation request's body is structurally validated — required fields present, strings non-empty, numbers integral and within their declared minimum bounds, enum values drawn from their declared sets, BOM and configuration lines well-formed, dates and timestamps well-formed, and photo evidence present on signoff creation — immediately after role authorization and before any body-referenced identifier is resolved, so a malformed creation body reports `ERR_INVALID_REQUEST` (or `ERR_PHOTO_EVIDENCE_REQUIRED` on signoff creation) even when a referenced identifier would also miss; the lone exception is wave creation, where the `capacity_units` minimum and the window check are evaluated only after the program reference resolves, as narrated in §3.4.
5. **State preconditions fifth.** The target resource must occupy the lifecycle state its operation requires — the state-machine gates scattered through §3, such as program activation gates, kit freeze and release states, prototype review states, wave commit states, claim openness, signoff submission states, delivery progression, ledger adjustability, and reservation holds.
6. **Segregation of duties and recall holds sixth.** A prototype approver who is also its most recent submitter fails with `ERR_PROTOTYPE_SELF_APPROVAL`; a signoff approver who submitted it fails with `ERR_SIGNOFF_SELF_APPROVAL`; a claim whose part sits on the program's recall hold list fails with `ERR_PART_RECALL_HOLD`.
7. **Request shape and consistency seventh.** Required fields present and correctly typed — required strings must be non-empty, calendar dates must be well-formed `YYYY-MM-DD` dates, and timestamp fields must be well-formed ISO 8601 instants — enum values drawn from their declared sets, quantities of at least 1, windows whose end is strictly after their start (`ERR_INVALID_WINDOW`), and the domain shape rules — value engineering only when the list-price estimate exceeds target (`ERR_VE_NOT_REQUIRED`), a non-empty kit at freeze (`ERR_KIT_EMPTY`), photo evidence present (`ERR_PHOTO_EVIDENCE_REQUIRED`), no second pending signoff for a delivery (`ERR_SIGNOFF_ALREADY_PENDING`), and no ledger adjustment that would drive stock below zero (`ERR_STOCK_UNDERFLOW`). Malformed or mistyped input in this category reports `ERR_INVALID_REQUEST`. On operations acting on an existing resource the whole category sits here, after the state gates; on the creation endpoints its structural portion was already evaluated earlier, per the refinement in category 4.
8. **Temporal resource conflicts eighth.** Staging-bay window overlap (`ERR_STAGING_BAY_OVERLAP`) and crew daily capacity (`ERR_CREW_CAPACITY_EXCEEDED`).
9. **Money last.** Only after every category above has passed does the server evaluate fiscal constraints: the freeze and release budget checks (`ERR_BUDGET_EXCEEDED`), the wave capacity check (`ERR_WAVE_CAPACITY_EXCEEDED`), and the contingency check on claim approval (`ERR_CONTINGENCY_EXCEEDED`). A request that fails both a shape rule and a budget rule therefore always surfaces the shape error first.

### 2.8. The Logical Clock and Time-Driven Transitions

The server maintains a logical clock independent of wall-clock time. Before any operator action, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own. A `PlatformAdmin` may advance it through a test-driving capability that accepts a `to_iso8601` instant and sets the server's current time to that value; the response reports the resulting `current_utc`.

Advancing the logical clock fires two automatic transitions. Any production wave in `COMMITTED` status whose `start_date` has been reached — the new current time falls on or after the wave's start date — moves to `IN_PRODUCTION` without any client action on the wave. Any staging reservation still in `HELD` status whose `end_ts` has been reached or passed moves to `EXPIRED`. Both transitions are ordinary mutations: each affected resource's `updated_at` refreshes and its `version` increments.

### 2.9. Program Finances: Budget, Contingency, and Recovery

A rollout program carries four read-only fiscal aggregates that the server maintains continuously, plus a fifth that exists only at the end of the program's life. `remaining_budget_cents` starts equal to `budget_total_cents` at creation and thereafter equals the total budget minus the `kit_total_cost_cents` of every kit in `FROZEN`, `RELEASED`, or `FULFILLED` status, minus the `wave_release_charge_cents` of every released kit; kits still in `DRAFT` and kits that were `CANCELLED` contribute nothing to the deduction. `contingency_spent_cents` is the running sum of `replacement_cost_cents` over the program's `APPROVED` damage claims, drawn against the separate `contingency_budget_cents` reserve. `closeout_recovery_cents` accumulates the `recovery_value_cents` of attic stock ledgers as they reach `DISPOSED`. `fulfilled_kit_count` counts kits that have reached `FULFILLED`. Finally, `final_reconciliation_cents` remains null until closeout is finalized, at which point it is computed once as described in §3.8. None of these aggregates is writable by clients; each changes only as a side effect of the workflows in §3, and each change is a mutation that refreshes the program's `updated_at` and increments its `version`.

### 2.10. Cross-Entity Cascades and Automatic Transitions

Several operations in this domain mutate more than one resource in a single atomic act, and the server also transitions resources on its own when criteria are met. Implementers should expect, at minimum, the following multi-resource effects, each detailed where its workflow lives in §3: freezing a kit debits the program budget and, when it is the first frozen kit derived from its prototype, locks the prototype; releasing a kit debits a production surcharge from the program, adds the kit's component count to the wave's committed load, and recomputes the wave's utilization posture; approving a damage claim adds to the program's contingency spend and to the carrying wave's committed load, again recomputing utilization; approving an installation signoff completes the delivery, fulfills the kit, increments the program's fulfilled count, and creates an attic stock ledger; disposing of a ledger adds its recovery value to the program's closeout recovery. Automatic transitions without any client request on the affected resource include the clock-driven wave and reservation transitions of §2.8, the prototype lock on first kit freeze, the delivery completion and kit fulfillment fired by signoff approval, and the attic ledger's own oscillation between `ACTIVE` and `DEPLETED` as its quantity crosses zero. Every cascade hop mutates the affected resource in the ordinary way — `updated_at` refreshes and `version` increments — so a client watching version numbers will observe each hop.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Rollout Program

Everything begins with the **rollout program**, the fiscal and organizational container for one retail chain's fixture rollout. A `ProgramManager` creates it with a human-readable `program_name`, the `retailer_code` of the chain being served, a `budget_total_cents` covering all fixture spend, and a `contingency_budget_cents` reserved specifically for damage and missing-part replacements. The total budget must be a positive number of cents and the contingency reserve must be zero or greater; input that violates these bounds, omits required fields, or supplies an invalid enum value is rejected with `ERR_INVALID_REQUEST`. Two optional fields shape later behavior: `recalled_part_numbers`, a list of part numbers under recall hold that defaults to an empty list when omitted, and `attic_valuation_method`, which selects how leftover attic stock will be valued at disposition — `PROGRAM_AVERAGE` or `LIQUIDATION` — and defaults to `PROGRAM_AVERAGE`.

A new program is born in `DRAFT` status with its computed fields initialized: `remaining_budget_cents` equals `budget_total_cents`, while `contingency_spent_cents`, `fulfilled_kit_count`, and `closeout_recovery_cents` all start at zero, and `final_reconciliation_cents` stays null. Engineers may create prototypes against a program, coordinators may create kit configurations, and planners may create production waves regardless of the program's status — these creation flows are not gated on program state, and they are the only write operations reachable before activation, since kit freezes and wave commits both require an `ACTIVE` program.

Activation moves the program `DRAFT → ACTIVE` and is restricted to a `ProgramManager`. Activation requires the program to still be in `DRAFT` — attempting it from any other state fails with `ERR_PROGRAM_NOT_ACTIVE` — and requires `budget_total_cents` to be positive, else `ERR_INVALID_REQUEST`. Once `ACTIVE`, the program accepts kit freezes and wave commits, the two operations that begin committing real money and real factory capacity.

### 3.2. Prototype Engineering and the Value-Engineering Loop

A **fixture prototype** is one fixture model designed for a program. A `FixtureEngineer` creates it with the `program_id` of its program (an unknown program is rejected with `ERR_PROGRAM_NOT_FOUND`), a `fixture_code` such as a gondola model designation, a cost `target_cost_cents`, and the bill of materials `bom_lines`. Each BOM line carries a `part_number`, a `quantity` of at least 1, a `list_unit_cost_cents`, and optionally a `negotiated_unit_cost_cents` capturing a supplier-negotiated price; `bom_lines` itself may be empty, in which case both cost estimates are zero. The prototype is born in `DRAFT` with `ve_round_count` at zero and `approved_by_user_id` null.

Two cost estimates are maintained on every prototype, both computed at creation and both recomputed whenever the BOM is patched. The `provisional_cost_cents` is the list-price basis: for each BOM line, the line's `quantity` multiplied by its `list_unit_cost_cents`, rounded half up to a whole cent, and then summed across lines. It is never rewritten by value-engineering activity. The `engineered_cost_cents` follows the same per-line-round-then-sum discipline but uses each line's `negotiated_unit_cost_cents` where one is present and falls back to `list_unit_cost_cents` where it is not; it therefore diverges from the provisional figure as soon as any negotiated price differs from list. A third figure, `final_cost_cents`, stays null until approval.

An engineer may patch a prototype's `bom_lines` or `target_cost_cents` only while the prototype is in `DRAFT` or `VALUE_ENGINEERING`; a patch attempted in any other state — including after the prototype has locked — is rejected with `ERR_PROTOTYPE_INVALID_STATE`. In the patch body a field explicitly set to null is treated as omitted. Every accepted patch recomputes both cost variants and increments the prototype's `version`.

When the design is ready, the engineer submits it for review, moving the prototype `DRAFT → ENGINEERING_REVIEW` and recording their own `X-User-ID` in `submitted_by_user_id`; submission from any state other than `DRAFT` or `VALUE_ENGINEERING` is rejected with `ERR_PROTOTYPE_INVALID_STATE`. Review has two possible outcomes, both driven by a `ProgramManager`. If the prototype's list-price estimate exceeds its cost target — that is, `provisional_cost_cents` is strictly greater than `target_cost_cents` — the manager may send it into a value-engineering round, moving it `ENGINEERING_REVIEW → VALUE_ENGINEERING` and incrementing `ve_round_count` by one. Requesting value engineering when the provisional estimate has not exceeded the target is rejected with `ERR_VE_NOT_REQUIRED`, and requesting it from any state other than `ENGINEERING_REVIEW` is rejected with `ERR_PROTOTYPE_INVALID_STATE`. During the round the engineer patches negotiated prices into the BOM and then resubmits, moving `VALUE_ENGINEERING → ENGINEERING_REVIEW`; resubmission recomputes `engineered_cost_cents` from the current `bom_lines` and refreshes `submitted_by_user_id` with the resubmitting engineer's `X-User-ID`.

Approval moves the prototype to `APPROVED` from either `ENGINEERING_REVIEW` or `VALUE_ENGINEERING`. Segregation of duties is enforced: the approving manager's `X-User-ID` must differ from the prototype's recorded `submitted_by_user_id`, and a violation is rejected with `ERR_PROTOTYPE_SELF_APPROVAL` (HTTP 403). Approval finalizes `final_cost_cents`: when the prototype has been through at least one value-engineering round — `ve_round_count` greater than zero — the final cost is the `engineered_cost_cents`; otherwise it is the `provisional_cost_cents`. The approver's identity is recorded in `approved_by_user_id`.

An approved prototype remains editable nowhere: the moment the first kit configuration derived from it is frozen, the prototype automatically transitions `APPROVED → LOCKED`, after which `bom_lines` and `target_cost_cents` are immutable and any patch attempt fails with `ERR_PROTOTYPE_INVALID_STATE`. A prototype has no terminal state beyond this — locking simply seals the design that production will build.

### 3.3. Store Kit Configuration and Budget Commitment

With an approved prototype in hand, a `ConfigCoordinator` builds a **store kit configuration** for each destination store. Creation takes the `program_id`, the `prototype_id` the kit derives from (unknown program or prototype identifiers are rejected with `ERR_PROGRAM_NOT_FOUND` or `ERR_PROTOTYPE_NOT_FOUND` respectively), the destination `store_code`, and optionally an initial set of `config_lines`, which defaults to an empty list. Each configuration line carries a `part_number`, a `quantity` of at least 1, and a `unit_cost_cents`. The kit is born in `DRAFT`, and its cost figures are computed immediately from whatever lines were supplied — zero when none were.

Two computed fields describe the kit's size and price. `total_components` is the plain integer sum of the `quantity` across all configuration lines, with no rounding involved. `kit_total_cost_cents` prices the kit with a handling surcharge: for each line, the line's `quantity` is multiplied by its `unit_cost_cents` and by a factor of 1.06 — a six percent handling uplift — and the result is rounded half up to a whole cent; the kit total is then the integer sum of those per-line amounts. The rounding order is pinned: per line first, then sum. Rounding once after summing raw line amounts is forbidden, because it produces a different cent value whenever two or more lines yield fractional cents. These figures recompute on every successful patch of the kit's lines.

While the kit remains in `DRAFT`, the coordinator may replace its `config_lines` by patching the kit — the patch body must carry `config_lines` as an array, failing `ERR_INVALID_REQUEST` otherwise; patching from any other state fails with `ERR_KIT_INVALID_STATE`. This is one of the two optimistic-concurrency-protected writes in the system (§2.6): the patch body must carry `expected_config_version` equal to the kit's current `version`, and a stale expectation is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful patch recomputes the kit totals and increments the kit's `version`.

Freezing is the act that commits program money to a store. A coordinator may freeze only a kit in `DRAFT` (any other state: `ERR_KIT_INVALID_STATE`), and only when three further conditions hold: the program is `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE` otherwise), the source prototype is `APPROVED` or `LOCKED` (`ERR_PROTOTYPE_NOT_APPROVED` otherwise), and the kit contains at least one configuration line (`ERR_KIT_EMPTY`, HTTP 422, when `config_lines` is empty). Fiscally, the kit's `kit_total_cost_cents` must not exceed the program's `remaining_budget_cents` — a kit whose total lands exactly on the remaining budget is allowed — and a shortfall is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 402). A successful freeze moves the kit `DRAFT → FROZEN`, deducts `kit_total_cost_cents` from the program's `remaining_budget_cents`, and — when this is the first kit derived from its prototype to be frozen — bubbles up to lock the prototype, moving it `APPROVED → LOCKED` as described in §3.2.

Cancellation is available from `DRAFT` or `FROZEN` and from nowhere else (`ERR_KIT_INVALID_STATE`). Cancelling a `DRAFT` kit simply moves it to `CANCELLED` with no fiscal effect, since nothing was ever debited. Cancelling a `FROZEN` kit additionally refunds the freeze debit: the kit's `kit_total_cost_cents` is added back to the program's `remaining_budget_cents` before the kit lands in `CANCELLED`. A kit that has been released can no longer be cancelled through this path at all.

### 3.4. Production Waves, Utilization, and Release Charging

Manufacturing capacity is organized into **production waves**, each a dated window aligned to the rollout calendar. A `ProductionPlanner` creates a wave with its `program_id` (unknown program: `ERR_PROGRAM_NOT_FOUND`), a `wave_label` such as a regional designation, a `start_date` and an `end_date` as ISO calendar dates, and a `capacity_units` expressing the maximum component units the wave can produce. The end date must be strictly after the start date — a non-forward window fails with `ERR_INVALID_WINDOW` — and the capacity must be at least 1. A new wave starts in `PLANNED` with `committed_units` at zero, `utilization_pct` at zero, and `utilization_posture` at `NORMAL`.

A planner commits a wave to signal the factory may begin scheduling against it; commitment requires the wave to be `PLANNED` (otherwise `ERR_WAVE_INVALID_STATE`) and the program to be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`), and moves the wave `PLANNED → COMMITTED`. Thereafter the wave is armed against the logical clock: when the clock reaches the wave's `start_date`, a `COMMITTED` wave automatically moves `COMMITTED → IN_PRODUCTION` (§2.8). A planner may mark a wave complete from either `COMMITTED` or `IN_PRODUCTION`, moving it to `COMPLETED`'s sibling terminal state `COMPLETE` — completion from any other state is `ERR_WAVE_INVALID_STATE`. Cancellation is deliberately narrow: only a `PLANNED` wave may be cancelled to `CANCELLED`, because a committed wave may already hold released kits; cancelling from any other state fails with `ERR_WAVE_INVALID_STATE`.

A wave's loading is tracked continuously. `committed_units` is the sum of `total_components` over all `RELEASED` kits riding the wave plus the sum of `replacement_component_count` over `APPROVED` damage claims whose kits ride the wave. `utilization_pct` divides `committed_units` by `capacity_units`, expresses the result as a percentage, and rounds half up to one decimal place. When that percentage reaches 90.0 — the boundary is inclusive, so exactly 90.0 counts — the `utilization_posture` becomes `AT_RISK`; below it the posture is `NORMAL`. Utilization is recomputed at wave creation, at every kit release, and at every damage-claim approval that adds replacement load; a cancellation of a released kit is impossible, so committed load never subtracts.

Releasing a frozen kit onto a wave is the operation that books factory capacity, and it is the most heavily gated transition in the system. The kit must be `FROZEN` (`ERR_KIT_INVALID_STATE` otherwise). The request names a `wave_id`, which must exist and must belong to the same program as the kit — either failure reports `ERR_WAVE_NOT_FOUND`. The wave must be `COMMITTED` or `IN_PRODUCTION` (`ERR_WAVE_NOT_RELEASABLE` otherwise). The wave must have room: `committed_units` plus the kit's `total_components` must not exceed `capacity_units`, with a release that lands exactly at full capacity allowed; overshoot fails with `ERR_WAVE_CAPACITY_EXCEEDED`. Finally the release surcharge itself must fit the program's `remaining_budget_cents`, with equality allowed, else `ERR_BUDGET_EXCEEDED`.

That surcharge, recorded on the kit as `wave_release_charge_cents`, is priced from the wave's loading after the release. The kit carries no wave affiliation or surcharge before this point: both `wave_id` and `wave_release_charge_cents` remain null until the kit is released. The post-release utilization is the wave's `committed_units` plus the releasing kit's `total_components`, divided by `capacity_units` and expressed as a percentage; the tier boundaries are evaluated on this unrounded percentage, not on the one-decimal `utilization_pct`. Below seventy percent the tier multiplier is 1.0; at seventy percent or above but below ninety percent it is 1.15; at ninety percent or above it is 1.35. Independently, if the wave is already `IN_PRODUCTION` at release time a rush multiplier of 1.25 applies, and 1.0 otherwise. The charge is then the kit's `total_components` multiplied by a base rate of 150 cents per component, multiplied by the tier multiplier, multiplied by the rush multiplier, rounded half up to a whole cent. On a successful release the charge is debited from the program's `remaining_budget_cents`, the kit's `wave_id` is set to the wave it joined, the wave's `committed_units` grows by the kit's `total_components`, the wave's utilization and posture are recomputed — the posture may flip `NORMAL → AT_RISK` as a consequence — and the kit moves `FROZEN → RELEASED`.

### 3.5. Warehouse Staging and Install-Crew Delivery

Finished kits flow through warehouse staging bays before a crew ever sees them. A `WarehouseLead` holds a staging window by creating a **staging reservation** naming the released kit via `kit_id` (a kit that is not `RELEASED` is rejected with `ERR_KIT_INVALID_STATE`; an unknown kit with `ERR_KIT_CONFIG_NOT_FOUND`), the `staging_bay_code` of the bay being occupied, and the window bounds `start_ts` and `end_ts`, both ISO 8601 UTC instants. The end of the window must be strictly after its start, else `ERR_INVALID_WINDOW`. Reservation windows are half-open: the bay is occupied from `start_ts` up to but not including `end_ts`. A new reservation conflicts with an existing `HELD` reservation on the same `staging_bay_code` when the new window's start falls before the existing window's end and the existing window's start falls before the new window's end; such a conflict is rejected with `ERR_STAGING_BAY_OVERLAP`. Windows that merely touch — the new start landing exactly on an existing end, or the new end landing exactly on an existing start — are adjacent, not overlapping, and are allowed. Only `HELD` reservations occupy a bay; windows in `CONSUMED`, `RELEASED`, or `EXPIRED` status impose no constraint. A successfully created reservation starts in `HELD`.

A lead may voluntarily release a reservation, moving it `HELD → RELEASED`; attempting that on a reservation in any other state fails with `ERR_RESERVATION_NOT_HELD`. Two system-driven transitions also terminate a hold: when the logical clock reaches or passes a `HELD` reservation's `end_ts`, the reservation moves to `EXPIRED` (§2.8), and when an install delivery is created for the same kit, the reservation is consumed as described below.

An `InstallCrewLead` schedules an **install delivery** for a released kit by supplying its `kit_id` (non-`RELEASED` kits: `ERR_KIT_INVALID_STATE`), the `crew_code` of the crew whose day will be consumed, the `delivery_date` as an ISO calendar date, and the `estimated_install_hours` booked against that crew-day, which must be at least 1. Crew capacity is enforced as an aggregate per crew per calendar date, not as pairwise window overlap: the committed hours for a `crew_code` on a `delivery_date` are the sum of `estimated_install_hours` over that crew's deliveries on that date in `SCHEDULED`, `DISPATCHED`, or `DELIVERED` status, and a new booking is rejected with `ERR_CREW_CAPACITY_EXCEEDED` when the committed hours plus the new booking's `estimated_install_hours` would exceed eight hours — the standard crew day. A booking that brings the crew-day to exactly eight hours is allowed. `FAILED` and `COMPLETE` deliveries consume no capacity.

Creating a delivery also resolves the kit's staging: the kit's `HELD` reservation with the earliest `start_ts` — ties broken by the earliest `created_at` — automatically moves `HELD → CONSUMED`; when the kit has no `HELD` reservation at that moment, no reservation is consumed and the delivery is created anyway. The delivery itself is born in `SCHEDULED`. From there the crew lead walks it through its route: dispatch moves `SCHEDULED → DISPATCHED`, confirming arrival moves `DISPATCHED → DELIVERED`, and either action attempted from the wrong state fails with `ERR_DELIVERY_INVALID_STATE`. A delivery that falls through may be failed from `SCHEDULED` or `DISPATCHED` — failing from any other state is likewise `ERR_DELIVERY_INVALID_STATE` — moving it to `FAILED`, at which point its `estimated_install_hours` stop counting toward crew-day capacity and the hours are available for rebooking. The final step, `DELIVERED → COMPLETE`, is not taken by the crew at all: it fires automatically when the installation's photo signoff is approved, as §3.7 describes.

### 3.6. Damage and Missing-Part Hotline

Field problems arrive through the hotline. A `HotlineAgent` files a **damage claim** against a delivery by providing the `delivery_id` (unknown delivery: `ERR_DELIVERY_NOT_FOUND`), the affected `part_number`, a `claim_type` of `DAMAGED` or `MISSING`, the `replacement_component_count` to remanufacture (at least 1), and the quoted `replacement_cost_cents` (zero or greater). Claims may be filed only against deliveries in `DELIVERED` or `COMPLETE` status; filing against a delivery in any other state is rejected with `ERR_DELIVERY_INVALID_STATE`. A new claim starts in `OPEN`, carrying no fiscal or capacity effect yet.

Adjudication belongs to the `ProgramManager`, and approval is where the money moves. Three gates guard it, in precedence order (§2.7): the claim must still be `OPEN` (`ERR_CLAIM_NOT_OPEN` otherwise); the claimed `part_number` must not appear on the program's `recalled_part_numbers` hold list, since recalled parts cannot be re-manufactured into the field (`ERR_PART_RECALL_HOLD`, HTTP 422); and the `replacement_cost_cents` must fit within the program's remaining contingency — that is, within `contingency_budget_cents` minus `contingency_spent_cents`, with a claim landing exactly on the remaining reserve allowed — else `ERR_CONTINGENCY_EXCEEDED` (HTTP 402).

Approving a claim fires a three-hop cascade. First, the claim's `replacement_cost_cents` is added to the program's `contingency_spent_cents`. Second, the wave carrying the claim's kit — found by following the claim's `delivery_id` to its delivery, the delivery's kit, and the kit's `wave_id` — has the claim's `replacement_component_count` added to its `committed_units`; emergency replacement deliberately bypasses the release-time capacity check, so this addition may push `committed_units` above `capacity_units`. Third, that wave's `utilization_pct` and `utilization_posture` are recomputed, and the posture may flip `NORMAL → AT_RISK`. The claim itself moves `OPEN → APPROVED`.

Rejection is the quiet sibling: a manager may reject any `OPEN` claim (`ERR_CLAIM_NOT_OPEN` otherwise), moving it `OPEN → REJECTED` with the rejection recorded and with no budget or capacity side effects of any kind. Both `APPROVED` and `REJECTED` are terminal.

### 3.7. Installation Signoff and the Fulfillment Cascade

The retail side of the house confirms completed installations through photographic evidence. An `InstallCrewLead` submits an **install signoff** for a delivery that has reached `DELIVERED` (submitting against a delivery in any other state fails with `ERR_DELIVERY_INVALID_STATE`), supplying the `delivery_id`, a `photo_urls` list of evidence links, and optional free-text `notes`, which default to null when omitted. The evidence list must contain at least one entry; an empty or absent list is rejected with `ERR_PHOTO_EVIDENCE_REQUIRED` (HTTP 422). A delivery may have at most one signoff awaiting review: while a `SUBMITTED` signoff exists for the same delivery, a further submission is rejected with `ERR_SIGNOFF_ALREADY_PENDING`. A freshly created signoff starts in `SUBMITTED` with `submission_count` at 1, the submitter's `X-User-ID` captured in `submitted_by_user_id`, `reviewed_by_user_id` still null, and `rejection_reason` null.

Review belongs to the `StoreManager`. Approving a signoff requires it to be `SUBMITTED` (`ERR_SIGNOFF_INVALID_STATE` otherwise) and enforces segregation of duties: the approver's `X-User-ID` must differ from the signoff's `submitted_by_user_id`, or the approval fails with `ERR_SIGNOFF_SELF_APPROVAL` (HTTP 403). Approval records the reviewer in `reviewed_by_user_id`, moves the signoff `SUBMITTED → APPROVED`, and then fires the longest cascade in the system, four hops in one atomic act. The delivery evidenced by the signoff moves `DELIVERED → COMPLETE`. The kit that delivery carried moves `RELEASED → FULFILLED`, and the program's `fulfilled_kit_count` is incremented by one. Finally, an attic stock ledger is automatically created for the fulfilled kit — exactly one per kit — with its `store_code` copied from the kit, its `quantity_on_hand` initialized to five percent of the kit's `total_components` rounded up to a whole unit, its `unit_cost_cents` set to the kit's `kit_total_cost_cents` divided by its `total_components` and rounded half up to a whole cent, its `reorder_point` defaulted to 2, its `reorder_required` evaluated immediately per §3.8, and its status `ACTIVE`.

Rejection is the other half of the loop. A `StoreManager` may reject a `SUBMITTED` signoff (`ERR_SIGNOFF_INVALID_STATE` otherwise) by supplying a `reason` — an absent, empty, or non-string reason fails with `ERR_INVALID_REQUEST` — which is recorded on the signoff as `rejection_reason` alongside the reviewer's identity in `reviewed_by_user_id`; the signoff moves `SUBMITTED → REJECTED`. Rejection is not terminal: an `InstallCrewLead` may resubmit a `REJECTED` signoff (from any other state, `ERR_SIGNOFF_INVALID_STATE`) with fresh `photo_urls` — again required to contain at least one entry, else `ERR_PHOTO_EVIDENCE_REQUIRED` — and optionally updated `notes`, the previous `notes` value being retained when the field is omitted or null. Resubmission replaces the photo evidence, clears `rejection_reason`, stamps `submitted_by_user_id` with the resubmitter's `X-User-ID`, increments `submission_count` by one, and returns the signoff to `SUBMITTED`, where it awaits a fresh review under the same self-approval guard against its most recent submitter.

### 3.8. Attic Stock, Disposition, and Program Closeout

Every fulfilled kit leaves behind a small reserve of spare parts at the store — the attic stock — tracked one ledger per kit. A `WarehouseLead` keeps the count honest through adjustments whose body carries a `delta` to apply to `quantity_on_hand`, an optional new `reorder_point`, and the mandatory `expected_ledger_version` implementing the optimistic concurrency rule of §2.6; a stale expectation is rejected with `ERR_STALE_VERSION` (HTTP 412). Adjustment requires the ledger to be in `ACTIVE` or `DEPLETED` status, failing with `ERR_LEDGER_INVALID_STATE` otherwise. The `delta` is added to `quantity_on_hand`, and the result may never drop below zero — an adjustment that would drive stock negative is rejected with `ERR_STOCK_UNDERFLOW` (HTTP 422). Within one adjustment request the checks fire in this order: the ledger's state gate, then the presence and integral type of `delta` and `expected_ledger_version`, then the version match, then the underflow rule, and finally the optional `reorder_point`'s type.

Two computed behaviors ride on every adjustment (and on ledger creation). The reorder flag `reorder_required` becomes true whenever `quantity_on_hand` falls to the `reorder_point` or below — the boundary is inclusive, so a quantity exactly equal to the reorder point demands replenishment — and when an adjustment also supplies a new `reorder_point`, the flag is re-evaluated against that new point. And the ledger's own status oscillates automatically: an adjustment that drives `quantity_on_hand` to exactly zero moves the ledger `ACTIVE → DEPLETED`, while an adjustment that raises the quantity above zero moves a `DEPLETED` ledger back to `ACTIVE`.

Disposition happens only during program closeout and belongs to the `ProgramManager`. A ledger may be disposed from either `ACTIVE` or `DEPLETED` (`ERR_LEDGER_INVALID_STATE` otherwise). The manager names a `disposition_type` — `RETURN_VENDOR`, `SCRAP`, or `DONATE`, with an absent or invalid value failing `ERR_INVALID_REQUEST` — and the disposition is permitted only while the program of the ledger's kit sits in `CLOSEOUT_PENDING` (`ERR_PROGRAM_NOT_CLOSEOUT_PENDING` otherwise), a gate the server evaluates after the ledger's state and the `disposition_type`'s validity. The server computes `recovery_value_cents` from the disposition type; both fields are null on the ledger until the moment of disposition. The recovery rate is eighty percent of unit value for `RETURN_VENDOR`, five percent for `SCRAP`, and zero for `DONATE`. The unit value depends on the program's `attic_valuation_method`: under the default `PROGRAM_AVERAGE` variant the stock is valued at the ledger's own `unit_cost_cents` — the source kit's average unit cost — so the recovery is `quantity_on_hand` multiplied by `unit_cost_cents` multiplied by the recovery rate, rounded half up to a whole cent; under the `LIQUIDATION` variant the stock is valued at a flat market rate of 2,500 cents per unit regardless of kit cost, so the recovery is `quantity_on_hand` multiplied by 2,500 and by the recovery rate, again rounded half up to a whole cent. The two variants diverge whenever the kit's average unit cost differs from 2,500 cents. A `DEPLETED` ledger, holding zero units, recovers zero cents regardless of method. Disposition adds the computed recovery to the program's `closeout_recovery_cents`, stamps the ledger's `disposition_type`, and moves the ledger to `DISPOSED`, its terminal state.

Closeout itself is a two-step gate guarded by the program's `ProgramManager`. Initiating closeout moves an `ACTIVE` program `ACTIVE → CLOSEOUT_PENDING` — attempting it from any other state fails with `ERR_PROGRAM_NOT_ACTIVE` — and is permitted only when the program's operational work is fully resolved: no kit of the program may remain in `DRAFT`, `FROZEN`, or `RELEASED`, no damage claim belonging to the program (reached through the claim's delivery, that delivery's kit, and the kit's program) may still be `OPEN`, and every production wave of the program must be `COMPLETE` or `CANCELLED`. Any violation blocks the transition with `ERR_CLOSEOUT_BLOCKED`.

Finalizing closeout moves the program `CLOSEOUT_PENDING → CLOSED`, its terminal state. Finalization requires the program to actually be in `CLOSEOUT_PENDING` (`ERR_PROGRAM_NOT_CLOSEOUT_PENDING` otherwise) and requires every attic stock ledger of the program's kits to have reached `DEPLETED` or `DISPOSED`; any ledger still `ACTIVE` blocks finalization with `ERR_UNDISPOSED_STOCK_REMAINS`. On success the server computes the program's `final_reconciliation_cents` — null until this moment — as the program's `remaining_budget_cents` minus its `contingency_spent_cents` plus its `closeout_recovery_cents`. The input set is pinned by status: kits in `FROZEN`, `RELEASED`, or `FULFILLED` contribute their `kit_total_cost_cents` to the remaining-budget deduction while `DRAFT` and `CANCELLED` kits contribute nothing; only `APPROVED` claims contribute to contingency spent; and only `DISPOSED` ledgers contribute recovery value. The program then lands in `CLOSED`, its books complete.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`. All responses use the envelope of §2.2, all lists paginate per §2.3, and every operation enforces the validation precedence of §2.7. Request bodies, computed fields, and side effects for each operation are specified narratively in §3; the table below is the routing and authorization contract only. A request body may carry fields the operation does not consume; such fields — including client-supplied values for server-managed computed fields — are ignored.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rollout-programs` | Create a rollout program (status `DRAFT`) | ProgramManager |
| GET | `/rollout-programs` | List rollout programs | Any |
| GET | `/rollout-programs/{id}` | Get a rollout program | Any |
| POST | `/rollout-programs/{id}/activate` | Activate a `DRAFT` program | ProgramManager |
| POST | `/rollout-programs/{id}/initiate-closeout` | Move an `ACTIVE` program to `CLOSEOUT_PENDING` when all kits, claims, and waves are resolved | ProgramManager |
| POST | `/rollout-programs/{id}/finalize-closeout` | Compute `final_reconciliation_cents` and close the program | ProgramManager |
| POST | `/fixture-prototypes` | Create a fixture prototype for a program | FixtureEngineer |
| GET | `/fixture-prototypes` | List fixture prototypes | Any |
| GET | `/fixture-prototypes/{id}` | Get a fixture prototype | Any |
| PATCH | `/fixture-prototypes/{id}` | Update `bom_lines` or `target_cost_cents` while `DRAFT` or `VALUE_ENGINEERING` | FixtureEngineer |
| POST | `/fixture-prototypes/{id}/submit-review` | Submit a prototype for engineering review, or resubmit after value engineering | FixtureEngineer |
| POST | `/fixture-prototypes/{id}/request-value-engineering` | Send a prototype into a value-engineering round | ProgramManager |
| POST | `/fixture-prototypes/{id}/approve` | Approve a prototype under review and finalize `final_cost_cents` | ProgramManager |
| POST | `/store-kit-configs` | Create a store kit configuration derived from a prototype | ConfigCoordinator |
| GET | `/store-kit-configs` | List store kit configurations | Any |
| GET | `/store-kit-configs/{id}` | Get a store kit configuration | Any |
| PATCH | `/store-kit-configs/{id}` | Replace `config_lines` while `DRAFT` (OCC via `expected_config_version`) | ConfigCoordinator |
| POST | `/store-kit-configs/{id}/freeze` | Freeze a `DRAFT` kit, debiting the program budget and locking the prototype on first freeze | ConfigCoordinator |
| POST | `/store-kit-configs/{id}/release` | Release a `FROZEN` kit to a production wave, charging the tiered surcharge | ConfigCoordinator |
| POST | `/store-kit-configs/{id}/cancel` | Cancel a `DRAFT` or `FROZEN` kit, refunding the freeze debit when applicable | ConfigCoordinator |
| POST | `/production-waves` | Create a production wave (status `PLANNED`) | ProductionPlanner |
| GET | `/production-waves` | List production waves | Any |
| GET | `/production-waves/{id}` | Get a production wave | Any |
| POST | `/production-waves/{id}/commit` | Commit a `PLANNED` wave | ProductionPlanner |
| POST | `/production-waves/{id}/complete` | Mark a `COMMITTED` or `IN_PRODUCTION` wave complete | ProductionPlanner |
| POST | `/production-waves/{id}/cancel` | Cancel a `PLANNED` wave that was never committed | ProductionPlanner |
| POST | `/staging-reservations` | Hold a half-open staging window on a warehouse bay for a `RELEASED` kit | WarehouseLead |
| GET | `/staging-reservations` | List staging reservations | Any |
| GET | `/staging-reservations/{id}` | Get a staging reservation | Any |
| POST | `/staging-reservations/{id}/release` | Release a `HELD` staging reservation | WarehouseLead |
| POST | `/install-deliveries` | Schedule an install-crew delivery for a `RELEASED` kit, consuming its earliest held reservation | InstallCrewLead |
| GET | `/install-deliveries` | List install deliveries | Any |
| GET | `/install-deliveries/{id}` | Get an install delivery | Any |
| POST | `/install-deliveries/{id}/dispatch` | Dispatch a `SCHEDULED` delivery | InstallCrewLead |
| POST | `/install-deliveries/{id}/confirm-delivery` | Confirm a `DISPATCHED` delivery as `DELIVERED` | InstallCrewLead |
| POST | `/install-deliveries/{id}/fail` | Fail a `SCHEDULED` or `DISPATCHED` delivery, releasing its crew-day capacity | InstallCrewLead |
| POST | `/damage-claims` | File a damage or missing-part claim against a `DELIVERED` or `COMPLETE` delivery | HotlineAgent |
| GET | `/damage-claims` | List damage claims | Any |
| GET | `/damage-claims/{id}` | Get a damage claim | Any |
| POST | `/damage-claims/{id}/approve` | Approve an `OPEN` claim, debiting contingency and wave capacity | ProgramManager |
| POST | `/damage-claims/{id}/reject` | Reject an `OPEN` claim with no fiscal effects | ProgramManager |
| POST | `/install-signoffs` | Submit photo signoff for a `DELIVERED` delivery | InstallCrewLead |
| GET | `/install-signoffs` | List install signoffs | Any |
| GET | `/install-signoffs/{id}` | Get an install signoff | Any |
| POST | `/install-signoffs/{id}/approve` | Approve a `SUBMITTED` signoff, firing the delivery-to-ledger cascade | StoreManager |
| POST | `/install-signoffs/{id}/reject` | Reject a `SUBMITTED` signoff with a reason | StoreManager |
| POST | `/install-signoffs/{id}/resubmit` | Resubmit a `REJECTED` signoff with fresh photo evidence | InstallCrewLead |
| GET | `/attic-stock-ledgers` | List attic stock ledgers | Any |
| GET | `/attic-stock-ledgers/{id}` | Get an attic stock ledger | Any |
| POST | `/attic-stock-ledgers/{id}/adjust` | Adjust `quantity_on_hand` or `reorder_point` (OCC via `expected_ledger_version`) | WarehouseLead |
| POST | `/attic-stock-ledgers/{id}/dispose` | Dispose of a ledger during closeout, computing its recovery value | ProgramManager |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock, firing time-driven wave and reservation transitions | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified narratively in §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_PROTOTYPE_NOT_FOUND` | 404 Not Found |
| `ERR_KIT_CONFIG_NOT_FOUND` | 404 Not Found |
| `ERR_WAVE_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_SIGNOFF_NOT_FOUND` | 404 Not Found |
| `ERR_LEDGER_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_NOT_CLOSEOUT_PENDING` | 409 Conflict |
| `ERR_CLOSEOUT_BLOCKED` | 409 Conflict |
| `ERR_UNDISPOSED_STOCK_REMAINS` | 409 Conflict |
| `ERR_PROTOTYPE_INVALID_STATE` | 409 Conflict |
| `ERR_PROTOTYPE_NOT_APPROVED` | 409 Conflict |
| `ERR_PROTOTYPE_SELF_APPROVAL` | 403 Forbidden |
| `ERR_VE_NOT_REQUIRED` | 409 Conflict |
| `ERR_KIT_INVALID_STATE` | 409 Conflict |
| `ERR_KIT_EMPTY` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_WAVE_INVALID_STATE` | 409 Conflict |
| `ERR_WAVE_NOT_RELEASABLE` | 409 Conflict |
| `ERR_WAVE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_STAGING_BAY_OVERLAP` | 409 Conflict |
| `ERR_RESERVATION_NOT_HELD` | 409 Conflict |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DELIVERY_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_NOT_OPEN` | 409 Conflict |
| `ERR_PART_RECALL_HOLD` | 422 Unprocessable Entity |
| `ERR_CONTINGENCY_EXCEEDED` | 402 Payment Required |
| `ERR_SIGNOFF_INVALID_STATE` | 409 Conflict |
| `ERR_SIGNOFF_SELF_APPROVAL` | 403 Forbidden |
| `ERR_SIGNOFF_ALREADY_PENDING` | 409 Conflict |
| `ERR_PHOTO_EVIDENCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_LEDGER_INVALID_STATE` | 409 Conflict |
| `ERR_STOCK_UNDERFLOW` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

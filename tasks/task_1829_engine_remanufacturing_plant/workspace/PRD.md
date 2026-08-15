# Engine Remanufacturing API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for an Engine Remanufacturing Plant API in the style of a Jasper Engines–type remanufacturer. The system orchestrates the full remanufacturing business loop: distributors purchase remanufactured engines and pay a core deposit; used "core" engines are returned, graded for rebuildability, and credited against the deposit; accepted cores flow into a machining and assembly pipeline with strict route sequencing and station scheduling; finished engines are dyno-tested against a build specification, sealed under quality sign-off, and sold through a server-side allocation selector. A warranty arm handles in-field failures through teardown, adjudication, and settlement as either cash credit or replacement allocation.

Two accounting ledgers ride on every mutation: each distributor carries a `deposits_held_cents` exposure total (the sum of its still-held core deposits) and a `credit_balance_cents` accumulator (grading credits, deposit refunds, and warranty credits, less dispute suspensions). Because a single action — grading a core, selling an engine, adjudicating a claim — fans out into state changes on three or four entities at once, the API must keep these cascades atomic and the ledgers exactly reconciled to their derivations after every write. Segregation of duties is enforced where quality and money meet: the quality inspector who seals an engine must not be the technician who recorded its latest dyno test, and the warranty adjuster who settles a claim must not be the technician who tore the failed unit down.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, protocols, and boilerplate that apply uniformly to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. The system recognizes six roles, spelled exactly as follows: `PlantAdmin`, `CoreInspector`, `ShopTechnician`, `QualityInspector`, `Distributor`, and `WarrantyAdjuster`. Failure to provide both headers, or presenting an `X-User-Role` value that is not one of the declared roles, will result in an `ERR_UNAUTHENTICATED` error (HTTP 401). Access to each operation is restricted by role; a caller whose role is not listed for the endpoint will be rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `Distributor`, `X-User-ID` is the `id` of the acting `Distributor` entity; ownership checks on any resource that references a `Distributor` compare the resource's foreign-key field to `X-User-ID`. A caller in the `Distributor` role may register core returns only for itself, may respond only to gradings of its own returns, may file warranty claims only on engines sold to itself, and purchases engines against its own ledger; any attempt to act on another distributor's resources is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is any of `PlantAdmin`, `CoreInspector`, `ShopTechnician`, `QualityInspector`, or `WarrantyAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `sealed_by` on a sealed engine, `teardown_by` on a warranty claim, or `recorded_by` on a dyno test — but does not compare it to any entity's `id`.

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

Endpoints returning lists of resources are paginated via query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum allowed value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — `Distributor`, `CoreReturn`, `CoreDeposit`, `BuildSpec`, `RemanWorkOrder`, `MachineOperation`, `Component`, `RemanEngine`, and `WarrantyClaim` — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any mutation of the resource.
- `version` (integer): a system-managed integer that increments by 1 on every mutation of the resource, used for optimistic concurrency control.

`DynoTest` records are the single exception: they are immutable once written, and therefore carry only `id` and `created_at`. Both `updated_at` and `version` are absent from a `DynoTest`.

### 2.5. The Logical Clock

All timestamps the server stamps itself — `graded_at`, `sold_at`, `filed_at`, `sealed_at`, `closed_at` — are read from a single logical clock, not the wall clock. Before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z; it never falls back to wall-clock time. A `PlantAdmin`-restricted test-driving capability advances the logical clock to a supplied `to_iso8601` instant and replies with the resulting `current_utc`; every subsequent stamp and every aging calculation reads from it. Age-in-days math throughout the system is computed as whole days between two UTC instants: the floor of the difference in seconds divided by 86400.

### 2.6. Monetary Values and Precision

All monetary quantities in the system are integer cents. Calculations that produce fractional intermediate results — grade multipliers applied to a base credit, aging brackets applied to a deposit, discounts applied to a list price, proration applied to a sale price — resolve to integer cents using the round-half-up method. Rounding order is pinned by rule: in the core credit calculation each missing-component deduction line is rounded half-up to whole cents before the lines are summed, and the base component is rounded half-up once; in deposit refunds, sale pricing, and warranty proration the round-half-up is applied once after the multiplication. Configuration fields such as `volume_discount_pct` and `dyno_min_oil_pressure_psi` preserve the precision supplied at input.

### 2.7. Hierarchical Consistency and Cascade Semantics

The plant's data model is flat, but its write paths are deeply cascaded: grading a core return can simultaneously mutate the return, the linked deposit, and the distributor's two ledger fields; selling an engine mutates the engine, creates a deposit, and rewrites the distributor ledger; adjudicating a claim mutates the claim, the failed engine, possibly a replacement engine, a new deposit, and the distributor ledger. The system treats each such fan-out as one atomic transaction. Wherever a cascade increments a parent's `version` (as a sale or replacement allocation does to the distributor), that increment is a first-class mutation of the parent with a refreshed `updated_at`, and any client holding a previously observed version of that parent will be stale on its next OCC-guarded write. Compensation flows are symmetric: when a grading is disputed, the previously posted credit is pulled back out of the distributor's balance; when a work order is cancelled, every component it had consumed is released back to available stock; when a work order is cancelled during assembly, the half-built engine is scrapped.

### 2.8. Nested Resource Retrieval and Validation Order

For any request whose path contains resource identifiers, existence is validated left-to-right: the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not resolve, before any body-referenced identifier is examined. After path identifiers resolve, body-referenced identifiers (`component_id`, `build_spec_id`, `core_deposit_id`, `reman_engine_id`, `distributor_id` where present) are checked for existence, each likewise producing `ERR_NOT_FOUND`. Existence checks never precede authentication and body well-formedness: missing or malformed headers yield `ERR_UNAUTHENTICATED` first, then role authorization, then request-body well-formedness (`ERR_VALIDATION`, HTTP 400 — required fields present, no undeclared fields, enum values within their declared sets, types correct, numeric ranges respected, `scheduled_end` strictly after `scheduled_start`, `ended_at` strictly after `started_at`), and only then existence. Within the business-rule tier, each endpoint's checks run in the priority order stated in §3 alongside the workflows they guard; where multiple rules could reject the same request, the one listed first in that narrative surfaces its error.

### 2.9. Optimistic Concurrency Control

Two write endpoints carry mandatory optimistic concurrency guards on a parent entity's `version`; no other endpoint takes a version field.

A purchase request — the distributor-facing engine sale — must carry `expected_distributor_version`, set to the buying distributor's `version` as last observed by the client. If the distributor's current `version` differs, the sale is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case where another writer has just completed a sale or deposit event against the same distributor (which legitimately succeeds under the product semantics) and the current writer's credit-limit view of the distributor is therefore stale.

A route-plan extension — declaring a machining operation on a work order — must carry `expected_work_order_version`, set to the work order's `version` as last observed by the client. A mismatch with the work order's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because another writer may just have added an operation and the current writer's view of the route plan is stale. Every successful operation declaration itself increments the work order's `version` by 1, so two sequential declarations must each re-read the work order.

## 3. Business Logic & Workflows

### 3.1. Distributor Accounts and the Credit Ledger

A `PlantAdmin` onboards a distribution partner by registering a distributor account with a unique `distributor_code`, a business `name`, the market's `emissions_requirement` (one of `FEDERAL` or `CALIFORNIA`), a `credit_limit_cents` ceiling (zero or greater), and a `volume_discount_pct` expressed as a fraction — 0.15 means a fifteen-percent discount — constrained to lie between 0 and 0.5 inclusive. New accounts begin with `status` `ACTIVE`, both ledger fields at zero, and `version` 1.

Two computed fields define the account's financial position at any moment. `deposits_held_cents` is the sum of `amount_cents` over exactly that distributor's core deposits whose `status` is `HELD`; closed and forfeited deposits are excluded. `credit_balance_cents` is an append-only signed accumulator over the account's history: grading a return adds its `final_credit_cents`; disputing a grading subtracts that same `final_credit_cents` back out while the dispute is open; re-grading a disputed return adds the new `final_credit_cents`, which — because the dispute already removed the prior credit — nets to the delta between old and new; closing a deposit with a refund adds the `refunded_cents`; approving a warranty claim for credit adds the `settled_credit_cents`. Both fields are maintained so that they always equal these derivations over the full history, with no drift after cascades or compensations.

A `PlantAdmin` may update an account's `credit_limit_cents`, `volume_discount_pct`, or `status`. Moving `status` from `ACTIVE` to `CREDIT_HOLD` freezes new purchases; moving it back from `CREDIT_HOLD` to `ACTIVE` re-enables them. Each such update increments the distributor's `version` by 1. While an account sits on `CREDIT_HOLD`, any purchase attempt on its behalf is rejected with `ERR_DISTRIBUTOR_CREDIT_HOLD` (HTTP 409).

### 3.2. Build Specifications: Routes, Thresholds, and Supersession

Every remanufactured engine is produced under a **build specification**, created by a `PlantAdmin` in `DRAFT` status. The spec pins the product identity — `engine_family` (for example `SBC-350`), `application_code` (for example `C1500-1996`), and `emissions_tier` (`FEDERAL` or `CALIFORNIA`) — together with the commercial terms `list_price_cents`, `core_deposit_cents`, and `core_base_credit_cents`, the last being the base credit owed for a core of this family graded `GRADE_A` with nothing missing.

The spec also encodes the shop-floor contract. `allowed_reuse_grades` lists the component reuse grades consumable under this spec, as a subset of `REUSE_OK` and `REWORK`. `allowed_interchange_groups` lists the interchange group codes whose components physically fit this application. `required_op_sequence` is the ordered machining route — an ordered list of operation types drawn from `BORE`, `DECK`, and `CRANK_GRIND` — and operations must be declared and performed in exactly this order. Finally, the spec sets the dyno pass window: measured `horsepower` must be at least `dyno_min_horsepower`, measured `oil_pressure_psi` must be at least `dyno_min_oil_pressure_psi`, and measured `coolant_temp_f` must be no more than `dyno_max_coolant_temp_f`.

Activation is the gate to production: a `PlantAdmin` activates a `DRAFT` spec, moving it to `ACTIVE` and stamping its activation time. Activation is also a supersession event — every other spec sharing the same combination of `engine_family`, `application_code`, and `emissions_tier` that is currently `ACTIVE` is retired in the same transaction, moving from `ACTIVE` to `RETIRED` with its retirement time stamped. A spec may also be retired explicitly from `ACTIVE`; explicit retirement is refused while any work order referencing the spec sits in `QUEUED`, `TEARDOWN`, `MACHINING`, `ASSEMBLY`, or `DYNO_TEST` status. `RETIRED` is terminal.

### 3.3. Core Returns: Receipt, Provisional Credit, and Grading

The reverse-logistics loop begins when a distributor ships a used core back to the plant. The distributor registers the return with its own `distributor_id`, the `build_spec_id` of the spec family the core will be rebuilt under, and — optionally — a `core_deposit_id` naming the deposit this return closes out; a null `core_deposit_id` records an unlinked core buy. Because a distributor-role caller acts only on its own account, registering a return whose `distributor_id` names a different distributor is rejected with `ERR_FORBIDDEN_OWNERSHIP`. When a `core_deposit_id` is supplied, it must name a deposit still in `HELD` status and owned by the returning distributor; anything else is rejected with `ERR_DEPOSIT_NOT_LINKABLE` (HTTP 422).

A new return enters in `RECEIVED` status, with `grade` null, `missing_components` empty, `final_credit_cents` null, `graded_at` null, and `dispute_count` at 0. At receipt the system posts an optimistic estimate into `provisional_credit_cents`: the spec's `core_base_credit_cents` multiplied by 1.00 — the provisional variant assumes a perfect `GRADE_A` core with no missing components, because inspection has not yet happened — rounded half-up to whole cents. Inspection has not happened, so the provisional figure ignores actual condition entirely.

Grading is performed by a `CoreInspector` and moves the return from `RECEIVED` to `GRADED`. The grading request supplies a `grade` — one of `GRADE_A`, `GRADE_B`, `GRADE_C`, or `REJECT` — and a `missing_components` array of part-type strings. Grading stamps `grade`, `missing_components`, and `graded_at` (read from the logical clock), then computes the final credit.

The final credit works as follows. The base component is the spec's `core_base_credit_cents` multiplied by the grade multiplier — 1.00 for `GRADE_A`, 0.60 for `GRADE_B`, 0.30 for `GRADE_C`, and 0.00 for `REJECT` — with the product rounded half-up to whole cents. Each entry in `missing_components`, processed in the order listed in the request, contributes a deduction line: a per-part deduction amount multiplied by the same grade multiplier, with each line rounded half-up to whole cents before any summing takes place. The per-part deduction amounts are 40000 cents for a `CRANKSHAFT`, 25005 cents for a `CYLINDER_HEAD`, 50000 cents for an `ENGINE_BLOCK`, and 33335 cents for a `CAMSHAFT`. The deduction lines are then summed — only after each has been individually rounded; the system never multiplies the unrounded aggregate and rounds once at the end — and the final credit is the base component minus the total deductions, floored at zero. This figure is written to `final_credit_cents`.

Grading fans out into two chains. First, the credit chain: the distributor's `credit_balance_cents` increases by `final_credit_cents`. Second, when the return carries a non-null `core_deposit_id`, the deposit chain: the linked deposit closes in the same transaction per the aging-bracket refund rules of §3.4 — moving to `CLOSED_REFUNDED` when its bracket percentage is positive, or to `FORFEITED` when the bracket percentage is zero — and the distributor's `deposits_held_cents` falls by the deposit's `amount_cents` while `credit_balance_cents` rises by the `refunded_cents`.

The distributor then responds to the grading by submitting an `action` of `ACCEPT` or `DISPUTE`. Acceptance moves the return from `GRADED` to `CLOSED`, the terminal state, with no further ledger effect. Dispute moves it from `GRADED` to `DISPUTED`, increments `dispute_count` by 1, and pulls the just-posted credit back out of `credit_balance_cents` — the credit sits in suspense while the dispute is open. Only the owning distributor may respond; a response naming a return owned by another distributor is rejected with `ERR_FORBIDDEN_OWNERSHIP`.

A disputed return can be graded again: the same grading capability moves it from `DISPUTED` back to `GRADED`, recomputing `final_credit_cents` from the new `grade` and `missing_components` and re-stamping `graded_at`. The credit chain then adds the new `final_credit_cents` to the distributor's balance; since the dispute already suspended the prior credit, the net movement relative to the pre-dispute balance is the delta between the old and new final credit. The deposit is already closed at this point — re-grading produces no further deposit side effects.

### 3.4. Core Deposits and the Aging Brackets

A core deposit is born at sale time: the system copies `amount_cents` from the spec's `core_deposit_cents`, stamps `sold_at` from the logical clock, links the deposit to the buying distributor via `distributor_id` and to the sold engine via `reman_engine_id`, and opens it in `HELD` status with `refunded_cents` at 0, `forfeited_cents` at 0, and both `age_days_at_close` and `closed_at` null. While `HELD`, the deposit's full `amount_cents` counts toward the distributor's `deposits_held_cents`.

A deposit closes in one of two ways. The normal path is the grading of a core return that names this deposit: the close runs the aging-bracket refund against the logical clock at grading time. The fallback path is the aging sweep described in §3.10, which forfeits long-held deposits.

The aging bracket is determined by the deposit's age in whole days at close — the floor of the difference between the close time and `sold_at` in seconds, divided by 86400, both timestamps read as UTC. The brackets have inclusive upper bounds: an age of at most 30 days refunds 100% of the deposit; an age of more than 30 but at most 60 days refunds 80%; an age of more than 60 but at most 90 days refunds 50%; an age of 91 days or more refunds nothing, and the deposit is forfeited. The `refunded_cents` is the `amount_cents` multiplied by the bracket percentage, rounded half-up to whole cents; the `forfeited_cents` is the `amount_cents` minus the `refunded_cents`. Exactly 30 days therefore yields a full refund, exactly 60 days yields 80%, exactly 90 days yields 50%, and 91 days or more yields zero. At close the system stamps `age_days_at_close` and `closed_at`, and the deposit moves to `CLOSED_REFUNDED` when the bracket percentage is positive or `FORFEITED` when it is zero. In the forfeiture case `refunded_cents` is 0 and `forfeited_cents` equals the full `amount_cents`.

Every close cascades to the distributor ledger: `deposits_held_cents` decreases by the deposit's `amount_cents`, and — on the refund path only — `credit_balance_cents` increases by the `refunded_cents`. A forfeiture posts no credit.

### 3.5. Work Orders: Opening the Pipeline

When a graded core is ready to be rebuilt, a `PlantAdmin` opens a remanufacturing work order by referencing the source `core_return_id`. The source return must already be `GRADED` or `CLOSED`, and its grade must be something other than `REJECT`; a return that is still `RECEIVED` or `DISPUTED`, or that was graded `REJECT`, is rejected with `ERR_CORE_RETURN_NOT_GRADED` (HTTP 409). The build spec carried on the return must be `ACTIVE` at this moment; a spec in `DRAFT` or `RETIRED` is rejected with `ERR_SPEC_NOT_ACTIVE` (HTTP 409). The new work order copies `build_spec_id` from the return, enters in `QUEUED` status, and starts with `reman_engine_id` null and `rework_count` at 0.

From `QUEUED`, a `ShopTechnician` advances the order through the pipeline by submitting the desired next state in a `target` field. The forward path is `QUEUED` → `TEARDOWN` → `MACHINING` → `ASSEMBLY` → `DYNO_TEST`, and the pipeline also admits a rework loop and a system-driven close. Each advance increments the work order's `version` by 1.

Entry into `MACHINING` from `TEARDOWN` requires that at least one machining operation has been declared on the order — the route plan must exist before machining begins. Entry into `ASSEMBLY` requires that every machining operation on the order stands in `COMPLETED` status; advancing with any operation still `PENDING` or `FAILED` is rejected with `ERR_OPERATIONS_INCOMPLETE` (HTTP 422). The first entry into `ASSEMBLY` is also the moment the engine is born: if `reman_engine_id` is still null, the system creates the `RemanEngine` — copying `build_spec_id` from the work order, minting its `serial_number`, and setting its initial `status` to `BUILT` — and links it onto the work order.

A `PlantAdmin` may cancel a work order from `QUEUED`, `TEARDOWN`, `MACHINING`, or `ASSEMBLY`, moving it to `CANCELLED`. Cancellation releases the order's component claims: every component whose `consumed_by_work_order_id` names this order flips from `CONSUMED` back to `AVAILABLE` with `consumed_by_work_order_id` cleared. Cancellation from `ASSEMBLY` is additionally destructive: if the order's `reman_engine_id` is non-null, the referenced engine moves from `BUILT` to `SCRAPPED`. Every cancellation increments the work order's `version` by 1.

### 3.6. Machining Operations: Route Declaration and Station Scheduling

While a work order is `QUEUED`, `TEARDOWN`, or `MACHINING`, a `ShopTechnician` declares the machining route one operation at a time. Each declaration supplies an `op_type` — one of `BORE`, `DECK`, or `CRANK_GRIND` — and a `sequence` giving the operation's 1-based position, which must equal the position of that `op_type` within the spec's `required_op_sequence`; a mismatch is a request-body error rejected with `ERR_VALIDATION`. Declaring an operation on a work order in any other status — `ASSEMBLY`, `DYNO_TEST`, `CLOSED`, or `CANCELLED` — is rejected with `ERR_INVALID_STATE` (HTTP 409). Declaration is OCC-guarded: the request must carry `expected_work_order_version` matching the work order's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.9. A new operation enters in `PENDING` status with `attempt_count` at 0 and `station_code`, `scheduled_start`, `scheduled_end`, and `result` all null, and its creation increments the work order's `version` by 1.

Performing an operation is the shop-floor act of occupying a machine station for a window and recording an outcome. The performer supplies the `station_code`, the occupation window as `scheduled_start` and `scheduled_end` (the end strictly after the start, on pain of `ERR_VALIDATION`), and the `result` — `PASS` or `FAIL`. Performance is allowed only while the parent work order is in `MACHINING`; any other parent status yields `ERR_INVALID_STATE`.

Two sequencing rules guard performance, and they are evaluated in this order relative to the other business checks on the endpoint. First, station occupancy: no other operation — of any status, excluding the one being performed — may hold a stored window on the same `station_code` that overlaps the requested half-open interval from `scheduled_start` up to but not including `scheduled_end`. Adjacency is explicitly allowed: an existing window ending exactly at the new window's start, or a new window ending exactly at an existing window's start, does not conflict. An actual overlap is rejected with `ERR_STATION_SCHEDULE_OVERLAP` (HTTP 409). Second, route order: every operation of the same work order with a smaller `sequence` must already be `COMPLETED`; performing out of order is rejected with `ERR_ROUTE_SEQUENCE_VIOLATION` (HTTP 422).

A `PASS` result moves the operation from `PENDING` to `COMPLETED`; a `FAIL` moves it from `PENDING` to `FAILED`. Either way the system stores the `station_code` and window and increments `attempt_count` by 1. Re-performance after a failure is the same capability applied to a `FAILED` operation: the route-order and station-overlap checks apply identically, except that the operation's own previously stored window is excluded from the overlap scan — a re-perform replaces its old window. A re-performed `PASS` moves the operation from `FAILED` to `COMPLETED`; a repeated `FAIL` leaves it `FAILED`. Each re-perform replaces the stored `station_code`, `scheduled_start`, and `scheduled_end`, records the new `result`, and increments `attempt_count` again. `COMPLETED` is terminal.

### 3.7. Components: Salvage, Inspection, Quarantine, and Consumption

Teardown yields parts. While a work order is in `TEARDOWN`, a `ShopTechnician` salvages a component by declaring its `part_type` — one of `CRANKSHAFT`, `CYLINDER_HEAD`, `ENGINE_BLOCK`, or `CAMSHAFT` — and its `interchange_group` code (for example `CRANK-SBC-3.48`). Salvage outside `TEARDOWN` is rejected with `ERR_INVALID_STATE`. A salvaged component enters in `AVAILABLE` status with `reuse_grade` null and `consumed_by_work_order_id` null.

A `QualityInspector` then inspects components, setting their `reuse_grade` — one of `REUSE_OK`, `REWORK`, or `SCRAP` — and steering their disposition with the `quarantine` flag. Inspecting with `quarantine` set true moves an `AVAILABLE` component to `QUARANTINED` and sets its `reuse_grade` to the inspected grade; inspecting with `quarantine` set false releases a `QUARANTINED` component back to `AVAILABLE` and sets its grade. Re-inspection of an `AVAILABLE` component with `quarantine` set false simply re-sets the `reuse_grade` while the component stays `AVAILABLE`. Declaring a `reuse_grade` of `SCRAP` at inspection moves the component to `SCRAPPED` — from either `AVAILABLE` or `QUARANTINED` — and `SCRAPPED` is terminal.

Consumption is the assembly-floor act of pulling a salvaged component into an engine build: a `ShopTechnician` consumes a component into a work order by naming the `component_id`. The checks on consumption run in a deliberate order. First the general state gate: the work order must be in `ASSEMBLY`, and the component must be in a state that permits the transition at all — a `CONSUMED` or `SCRAPPED` component is rejected with `ERR_INVALID_STATE` (HTTP 409). Next, the quarantine gate, which is deliberately distinct from the general state check: a `QUARANTINED` component is rejected specifically with `ERR_COMPONENT_QUARANTINED` (HTTP 422). Then the reuse gate: the component's `reuse_grade` must be non-null and a member of the work order's spec's `allowed_reuse_grades`, else `ERR_REUSE_GRADE_INSUFFICIENT` (HTTP 422). Finally the interchange gate: the component's `interchange_group` must be a member of the spec's `allowed_interchange_groups`, else `ERR_INTERCHANGE_INCOMPATIBLE` (HTTP 422). A successful consumption moves the component from `AVAILABLE` to `CONSUMED` and sets its `consumed_by_work_order_id` to the consuming work order. If that work order is later cancelled, the compensation cascade of §3.5 moves the component back from `CONSUMED` to `AVAILABLE` and clears the link.

### 3.8. Dyno Testing, Sealing, and the Serialized Unit Record

Once a work order enters `DYNO_TEST`, its engine — created at assembly entry and still in `BUILT` status — goes to the dyno cell. A `ShopTechnician` records a dyno test against the engine, supplying the `dyno_cell_code`, the test window `started_at` and `ended_at` (the end strictly after the start), and the three measurements: `horsepower`, `oil_pressure_psi`, and `coolant_temp_f`. Recording a test requires the engine to be in `BUILT` status and the parent work order to be in `DYNO_TEST`; anything else is rejected with `ERR_INVALID_STATE`.

The dyno cell is a scheduled resource with a cooldown buffer: each recorded test occupies the cell from its `started_at` until thirty minutes after its `ended_at`. A new test on the same `dyno_cell_code` conflicts whenever its buffer-extended interval intersects another test's buffer-extended interval — and because the buffers extend the ends, a new test starting exactly at a prior test's `ended_at` still conflicts. Such a conflict is rejected with `ERR_DYNO_CELL_SCHEDULE_OVERLAP` (HTTP 409).

The test's `result` is computed, not supplied: `PASS` when the measured `horsepower` is at least the spec's `dyno_min_horsepower` and the measured `oil_pressure_psi` is at least the spec's `dyno_min_oil_pressure_psi` and the measured `coolant_temp_f` is no more than the spec's `dyno_max_coolant_temp_f`; otherwise `FAIL`. The system stamps each record with `recorded_by` (the recording technician's `X-User-ID`) and a 1-based `attempt` counter over the engine's tests, and refreshes the engine's `latest_dyno_result` to the `result` of the most recent test by creation time — null if the engine has never been tested. A `PASS` moves the engine from `BUILT` to `DYNO_PASSED`. A `FAIL` leaves the engine in `BUILT` and sets `latest_dyno_result` to `FAIL`, which is exactly the condition that makes the parent work order eligible for the rework loop: advancing from `DYNO_TEST` back to `MACHINING` is permitted only when the referenced engine's `latest_dyno_result` is `FAIL`. Taking the rework loop increments the work order's `rework_count` by 1 and resets every `FAILED` machining operation on the order back to `PENDING` with its stored window fields cleared, ready to be re-performed per §3.6. Dyno records themselves are immutable — they carry no `updated_at` or `version`.

Sealing is the quality gate that turns a tested engine into sellable stock, performed by a `QualityInspector`. Two gates guard it, evaluated in this order. The quality gate doubles as the seal's state gate: the engine's `latest_dyno_result` must be `PASS` — equivalently, the engine must stand in `DYNO_PASSED`, which is reachable only via a passing dyno — and any seal attempt on an engine that is `BUILT`, untested, or whose latest test failed is reported as `ERR_DYNO_NOT_PASSED` (HTTP 422), not as a generic state error. Then segregation of duties: the sealing inspector's `X-User-ID` must differ from the `recorded_by` of the engine's most recent dyno test, else `ERR_SEALER_IS_TESTER` (HTTP 403). A successful seal moves the engine from `DYNO_PASSED` to `SEALED`, stamping `sealed_at` from the logical clock and `sealed_by` with the inspector's `X-User-ID`, and bubbles up: the parent work order — the one named by the engine's `work_order_id` — moves from `DYNO_TEST` to `CLOSED`, incrementing its `version` by 1. The sealed engine's record, keyed by its minted `serial_number`, is the plant's sealed unit record. Serial numbers are minted at engine creation as the literal prefix `RMN-` followed by a six-digit zero-padded sequence number in creation order, and are unique across all engines.

### 3.9. Engine Sales: Server-Side Allocation and the Sale Chain

A purchase is initiated by a `Distributor`-role caller naming a `build_spec_id`; the server, not the buyer, selects the unit. The allocation selector picks from the pool of engines in `SEALED` status under the requested spec, choosing the one with the earliest `sealed_at`, breaking ties by earliest `created_at`. An empty pool is rejected with `ERR_NO_ELIGIBLE_ENGINE` (HTTP 422).

The sale then passes a gauntlet of checks in a fixed order. After the generic tiers — authentication, role, body well-formedness, existence, and ownership (a distributor buys only against its own ledger, so a mismatch yields `ERR_FORBIDDEN_OWNERSHIP`) — the buyer's account must be `ACTIVE`, not on `CREDIT_HOLD` (`ERR_DISTRIBUTOR_CREDIT_HOLD`). The emissions gate follows: a buyer whose `emissions_requirement` is `CALIFORNIA` may only be sold an engine whose spec's `emissions_tier` is `CALIFORNIA`, else `ERR_EMISSIONS_TIER_MISMATCH` (HTTP 422); a buyer whose requirement is `FEDERAL` accepts either tier. The fiscal gate comes next: the buyer's current `deposits_held_cents` plus the spec's `core_deposit_cents` must not exceed the buyer's `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422). The OCC guard closes the gauntlet: the request's `expected_distributor_version` must equal the distributor's current `version`, else `ERR_STALE_VERSION` (HTTP 412).

The engine's price is computed per the sale-pricing rule: the spec's `list_price_cents` multiplied by one minus the buyer's `volume_discount_pct`, rounded half-up to whole cents, and written to `sale_price_cents`. The deposit is never part of the price — it is created separately.

A completed sale moves the engine from `SEALED` to `SOLD`, stamping `distributor_id` with the buyer, `sold_at` from the logical clock, and the computed `sale_price_cents`. The sale chain then runs: a new core deposit is created for the buyer in `HELD` status with `amount_cents` copied from the spec's `core_deposit_cents` and `sold_at` set to the sale clock; the buyer's `deposits_held_cents` increases by that `amount_cents`; and the distributor's `version` increments by 1 — which is precisely what invalidates any other client holding a pre-sale `expected_distributor_version`.

### 3.10. The Aging Sweep

Deposits that never get matched to a returned core must not linger on the books. A `PlantAdmin` triggers the aging sweep, an ops-run checkpoint that selects exactly the deposits still in `HELD` status whose age — whole days from `sold_at` to the current logical clock — exceeds 90 days, processes them in `sold_at` ascending order with `created_at` ascending as the tie-break, and forfeits each one: `HELD` to `FORFEITED` with `refunded_cents` 0, `forfeited_cents` equal to the full `amount_cents`, and `age_days_at_close` and `closed_at` stamped. Each forfeiture cascades to its distributor: `deposits_held_cents` decreases by the `amount_cents`, with no credit posted. The sweep reports how many deposits it forfeited and their identifiers — a response carrying `forfeited_count` and `forfeited_deposit_ids`.

### 3.11. Warranty Claims: Filing, Teardown, and Adjudication

When a sold engine fails in the field, the owning distributor files a warranty claim naming the `reman_engine_id`, its own `distributor_id`, and a free-text `failure_description`. The engine must currently be `SOLD` to the filing distributor; a claim filed against an engine in any other status, or owned by someone else, fails the state or ownership check respectively (`ERR_INVALID_STATE` or `ERR_FORBIDDEN_OWNERSHIP`). The warranty window is twelve 30-day months: filing is permitted only while the whole-day age of the sale — the floor of the difference between the current logical clock and the engine's `sold_at`, in seconds, divided by 86400 — is strictly less than 360 days. Filing at or after day 360 is rejected with `ERR_WARRANTY_EXPIRED` (HTTP 422). A new claim opens in `OPEN` status with `filed_at` stamped from the logical clock, and the system computes `months_in_service` as the number of whole days between `filed_at` and the engine's `sold_at`, divided by 30 and rounded down. `teardown_findings`, `teardown_by`, and `settled_credit_cents` all begin null.

A `ShopTechnician` then performs the failure teardown on an `OPEN` claim, recording `teardown_findings`; the claim moves from `OPEN` to `TEARDOWN_COMPLETE` with `teardown_by` set to the technician's `X-User-ID`, and the referenced engine leaves sellable inventory, moving from `SOLD` to `RETURNED`.

Adjudication is reserved for a `WarrantyAdjuster` and is segregation-checked: the adjudicator's `X-User-ID` must differ from the claim's `teardown_by`, else `ERR_ADJUDICATOR_IS_TEARDOWN_TECH` (HTTP 403). The adjudicator supplies an `outcome` and a `teardown_fee_cents`, and the claim moves to one of three terminal states.

An outcome of `APPROVED_CREDIT` settles in cash. The credit is computed with a pinned evaluation order: first `months_in_service` as already computed on the claim; then the remaining ratio — the twelve-month warranty term minus the months used, divided by twelve, floored at zero so a claim filed late in the term never goes negative; then the prorated amount, which is the engine's `sale_price_cents` multiplied by that remaining ratio and rounded half-up to whole cents; then the settlement, which is the prorated amount minus the `teardown_fee_cents`, floored at zero. The result is written to `settled_credit_cents` and added to the distributor's `credit_balance_cents`. The failed engine, already `RETURNED`, is scrapped — `RETURNED` to `SCRAPPED` — regardless of outcome.

An outcome of `APPROVED_REPLACEMENT` settles in kind, not cash: `settled_credit_cents` is 0, and instead the same server-side selector as a sale allocates a replacement — a `SEALED` engine whose `build_spec_id` matches the failed engine's spec, chosen by earliest `sealed_at` with `created_at` ascending as the tie-break. If the replacement pool is empty, the adjudication is rejected with `ERR_NO_ELIGIBLE_ENGINE`. The selected engine moves from `SEALED` to `SOLD` with `distributor_id` set to the claimant, `sold_at` stamped from the adjudication clock, and `sale_price_cents` set to 0 — warranty replacements bypass the sale-pricing rule entirely. The replacement chain then runs exactly as a sale chain would: a new core deposit is created for the claimant in `HELD` status with `amount_cents` copied from the spec's `core_deposit_cents`, the claimant's `deposits_held_cents` increases by that amount, and the distributor's `version` increments by 1. The failed engine is scrapped as above.

An outcome of `DENIED` grants nothing: `settled_credit_cents` is 0, no credit posts, and the failed engine is still scrapped — the torn-down unit never returns to stock under any outcome.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource, read resources, or trigger state transitions return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/distributors` | Register a distributor account | PlantAdmin |
| GET | `/distributors/{id}` | Read one distributor including computed ledger fields | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| PATCH | `/distributors/{id}` | Update credit limit, volume discount, and/or status (ACTIVE ↔ CREDIT_HOLD) | PlantAdmin |
| POST | `/core-returns` | Register a returned core; computes provisional credit | Distributor |
| GET | `/core-returns` | List core returns with filters and pagination | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| GET | `/core-returns/{id}` | Read one core return | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| POST | `/core-returns/{id}/grade` | Grade a received or disputed core; computes final credit and closes any linked deposit | CoreInspector |
| POST | `/core-returns/{id}/respond` | Distributor accepts or disputes the grading | Distributor |
| GET | `/core-deposits` | List core deposits with filters and pagination | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| GET | `/core-deposits/{id}` | Read one core deposit | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| POST | `/build-specs` | Create a build specification (DRAFT) | PlantAdmin |
| GET | `/build-specs` | List build specs with filters and pagination | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| GET | `/build-specs/{id}` | Read one build spec | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| POST | `/build-specs/{id}/activate` | Activate a DRAFT spec; retires sibling ACTIVE specs with the same key | PlantAdmin |
| POST | `/build-specs/{id}/retire` | Retire an ACTIVE spec; blocked while open work orders reference it | PlantAdmin |
| POST | `/work-orders` | Open a work order from a graded, rebuildable core return | PlantAdmin |
| GET | `/work-orders` | List work orders with filters and pagination | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| GET | `/work-orders/{id}` | Read one work order | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| POST | `/work-orders/{id}/advance` | Advance the pipeline to the named target state; rework loop requires latest dyno FAIL | ShopTechnician |
| POST | `/work-orders/{id}/cancel` | Cancel from QUEUED, TEARDOWN, MACHINING, or ASSEMBLY; releases consumed components | PlantAdmin |
| POST | `/work-orders/{id}/operations` | Declare a machining operation on the route (OCC-guarded on the work order version) | ShopTechnician |
| GET | `/work-orders/{id}/operations` | List the work order's machining operations | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| POST | `/operations/{id}/perform` | Perform or re-perform a machining operation; records station window and result | ShopTechnician |
| POST | `/work-orders/{id}/components` | Salvage a component from teardown | ShopTechnician |
| GET | `/work-orders/{id}/components` | List components salvaged by a work order's teardown | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| GET | `/components/{id}` | Read one component | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| POST | `/components/{id}/inspect` | Inspect a component: set reuse grade, quarantine or release, or scrap | QualityInspector |
| POST | `/work-orders/{id}/consume` | Consume a reusable component into the assembly | ShopTechnician |
| GET | `/reman-engines` | List remanufactured engines with filters and pagination | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| GET | `/reman-engines/{id}` | Read one engine (sealed unit record) | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| POST | `/reman-engines/{id}/dyno-tests` | Record a dyno test; result computed from spec thresholds; dyno-cell buffer enforced | ShopTechnician |
| GET | `/reman-engines/{id}/dyno-tests` | List an engine's dyno tests (immutable records) | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| POST | `/reman-engines/{id}/seal` | Quality seal of a dyno-passed engine; closes the parent work order | QualityInspector |
| POST | `/reman-engines/sell` | Distributor purchase with server-side allocation (oldest-sealed first) | Distributor |
| POST | `/warranty-claims` | File a warranty claim on a SOLD engine inside the 360-day window | Distributor |
| GET | `/warranty-claims` | List warranty claims with filters and pagination | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| GET | `/warranty-claims/{id}` | Read one warranty claim | PlantAdmin, CoreInspector, ShopTechnician, QualityInspector, WarrantyAdjuster, Distributor |
| POST | `/warranty-claims/{id}/teardown` | Record failure-teardown findings; engine SOLD → RETURNED | ShopTechnician |
| POST | `/warranty-claims/{id}/adjudicate` | Adjudicate after teardown; replacement allocates a sealed engine and new deposit | WarrantyAdjuster |
| POST | `/aging-runs` | Sweep every HELD deposit older than 90 days into FORFEITED | PlantAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock used by all stamps and aging math | PlantAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DISTRIBUTOR_CREDIT_HOLD` | 409 |
| `ERR_SPEC_NOT_ACTIVE` | 409 |
| `ERR_CORE_RETURN_NOT_GRADED` | 409 |
| `ERR_DEPOSIT_NOT_LINKABLE` | 422 |
| `ERR_COMPONENT_QUARANTINED` | 422 |
| `ERR_EMISSIONS_TIER_MISMATCH` | 422 |
| `ERR_DYNO_NOT_PASSED` | 422 |
| `ERR_SEALER_IS_TESTER` | 403 |
| `ERR_ADJUDICATOR_IS_TEARDOWN_TECH` | 403 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_STATION_SCHEDULE_OVERLAP` | 409 |
| `ERR_DYNO_CELL_SCHEDULE_OVERLAP` | 409 |
| `ERR_ROUTE_SEQUENCE_VIOLATION` | 422 |
| `ERR_OPERATIONS_INCOMPLETE` | 422 |
| `ERR_NO_ELIGIBLE_ENGINE` | 422 |
| `ERR_REUSE_GRADE_INSUFFICIENT` | 422 |
| `ERR_INTERCHANGE_INCOMPATIBLE` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_STALE_VERSION` | 412 |

# Wildlife & Nuisance-Animal Removal API — Product Requirements Document

## 1. Introduction

Nuisance-wildlife control is a field operation wrapped in a compliance shell. A homeowner reports a raccoon in the attic; a crew must inspect the structure, identify the species and the gaps it is exploiting, quote the job, set humane traps only where the law allows them, relocate captured animals within a legally bounded distance, seal the building, and stand behind the work with a warranty. Every one of those steps carries a regulatory or financial consequence if it is done out of order or outside its limits, and the back office must reconcile the money that was quoted against the work that was actually performed.

This API models that end-to-end lifecycle as a workflow-orchestration system with a strong compliance-audit spine. It coordinates four operational actors — schedulers, field crews, regulators, and the paying property owner — across a hierarchy that begins at a billing account and a physical property and descends through inspections, quotes, work orders, traps, captures, exclusion repairs, monitoring visits, and warranty claims. Because traps are physical objects drawn from a finite kit, because relocation distance is a legal band rather than a preference, and because regulated species cannot be touched without an approved permit, the system treats safety and conservation rules as hard gates rather than advisory checks. Money is conserved end to end: what is charged at acceptance is reconciled at close or refunded at cancellation, never created or destroyed.

The remainder of this document specifies the global contract (authentication, response envelope, pagination, concurrency, precision, and cross-cutting consistency rules) in Section 2, then narrates the business workflows and their embedded rules in Section 3, and finally enumerates the endpoint surface and the error catalogue in Sections 4 and 5.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles, spelled precisely as follows:

- `Dispatcher` — schedules inspections, records entry-point findings, builds and sends quotes, reopens quotes for revision, registers service accounts, properties, and technicians, and cancels work orders.
- `PropertyOwner` — the paying party; accepts, declines, or requests revisions on quotes, and files warranty claims.
- `FieldTechnician` — executes the physical field work: sets traps, records captures and relocations, pulls traps, performs exclusion/sealing repairs, and logs monitoring visits.
- `ComplianceOfficer` — owns species configuration, approves or denies permits for regulated species, and adjudicates warranty claims.

Two roles are tied to a persisted entity, and two are opaque operator identities. When `X-User-Role` is `PropertyOwner`, `X-User-ID` is the `id` of the acting `ServiceAccount`; ownership checks on any resource that traces back to a `ServiceAccount` compare the owning account against `X-User-ID`. In particular, accepting, declining, or requesting revision on a quote requires that the acting `PropertyOwner` own the `ServiceAccount` referenced (via `account_id`) by the `Property` of the quote's parent inspection. When `X-User-Role` is `FieldTechnician`, `X-User-ID` is the `id` of the acting `Technician`; resources that reference a `Technician` may be associated back to that identity. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the front of the result set; when omitted it defaults to 0.

Unless an endpoint explicitly states otherwise, every list is returned sorted by the resource's `created_at` timestamp in ascending order. The response envelope's `meta` object for a list carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the full matching set before the limit/offset window is applied and `has_more` indicates whether additional items remain beyond the returned window.

### 2.4. Common Resource Properties and Versioning

Every resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this domain additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at its initial value on creation and increments by one on every mutation. The `version` field is the basis for the optimistic-concurrency mechanism described in §2.6.

Derived fields are first-class mutations. When the server recomputes a value such as a property's `posture`, an inspection's `detected_individual_count`, a quote's `provisional_total_cents` or `final_total_cents`, a technician's `traps_deployed` or `traps_available`, a work order's risk scores or `net_charged_cents`, or any status field, that recomputation refreshes the owning resource's `updated_at` and increments its `version` exactly as a client-driven edit would.

### 2.5. Hierarchical Consistency and Nested Retrieval

Many operations mutate more than one resource at once. The system applies these cascades synchronously and immediately: by the time a write returns, every dependent resource it touched has been updated, its `updated_at` refreshed, and its `version` incremented. State that is *derived* from children — a property's `posture`, a work order's `lifecycle`, `removal_status`, and `exclusion_status` — is reconciled by the server without a separate client request whenever the underlying children change. The specific cascade and bubble rules are described inline with the workflows in Section 3.

For any request whose URL names more than one resource (for example, an entry point nested beneath an inspection, or an exclusion repair nested beneath a work order), the server validates the path identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, before any body-level foreign keys are checked. Body-referenced foreign keys are validated only after the path resolves, and a missing body reference likewise yields `ERR_NOT_FOUND`.

### 2.6. Optimistic Concurrency Control on Work-Order Cancellation

A work order's `version` advances silently as field work lands against it: setting a trap, relocating a capture, pulling a trap, and completing an exclusion repair each mutate the work order and bump its `version`. Cancellation is therefore guarded by optimistic concurrency control so that the refund math is never computed against a stale view of the performed work.

The cancel-work-order operation requires a non-optional `expected_work_order_version` field in its request body, carrying the `version` the client last observed on the target work order. If `expected_work_order_version` does not equal the work order's current `version` — that is, if any trap set, capture, pull, or repair completion advanced the work order since the client read it — the cancellation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no refund or kit restoration is performed. This is the only endpoint that takes a version field; no other write requires one.

### 2.7. Monetary Precision and Risk-Score Precision

All money in this system is expressed in integer cents, so monetary fields such as `base_trap_fee_cents`, `unit_price_cents`, `provisional_total_cents`, `final_total_cents`, and `net_charged_cents` are whole-number cents. Wherever a per-line monetary amount must be derived (the emergency surcharge applied to a line), each line is computed and rounded to the nearest whole cent using round-half-up **before** any summation; the rounded line amounts are then added together. The rounding order is fixed as round-then-sum and must not be reordered to sum-then-round.

Risk scores (`initial_risk_score` and `residual_risk_score`) are decimal numbers rounded to two decimal places using round-half-up. Relocation distance (`release_distance_miles`) is likewise rounded to two decimal places using round-half-up, and the compliance comparison is performed on the rounded value.

### 2.8. The Conserved Trap Kit

Each `Technician` owns a physical kit of traps whose size is `kit_trap_capacity`. The system maintains two derived counters on the technician: `traps_deployed`, the number of this technician's trap placements currently in the `SET` state, and `traps_available`, defined as `kit_trap_capacity` minus `traps_deployed`. The invariant `traps_deployed` plus `traps_available` equals `kit_trap_capacity` holds at all times, and `traps_available` is never negative. A trap is drawn from the kit when it is set and returned to the kit when it leaves the `SET` state (whether by capture, by pull, or by cancellation). Section 3 describes exactly which transitions decrement and restore the counters.

### 2.9. The Conserved-Money Principle

Money is neither created nor destroyed across a work order's life. At acceptance the work order's `net_charged_cents` is initialized to the quote's `provisional_total_cents`. At close it is reconciled to the quote's `final_total_cents`, which reflects only the work actually performed. At cancellation the difference between what was charged and the value of the work actually performed is refunded, and `net_charged_cents` settles to that performed value. In every path the relationship between the amount that remains charged and the amount refunded reconciles back to the originally committed provisional total, so no money is invented or lost. The exact subtotal and refund formulas live in §3.7.

### 2.10. Regulatory Posture and Compliance Gates

The system treats certain species as legally regulated (the `is_regulated` flag on a species profile). A regulated species cannot be trapped until a permit authorizing that species has been approved, and only suitably licensed technicians may work it. These gates are enforced as hard rejections rather than warnings, and they interact with a property's operational `posture`, which the server derives from the state of active work and outstanding permits. The precise gate conditions, their error codes, and the posture transitions are specified within the relevant workflows in Section 3.

### 2.11. The Logical Clock

The server keeps a logical clock that governs every time-sensitive computation — most importantly warranty-window eligibility. Before any clock is set, the logical clock reads `2026-04-01T00:00:00Z`, and it never falls back to wall-clock time. An administrative test-driving capability sets the logical clock to a supplied instant, expressed through the `to_iso8601` field. All deadline arithmetic in Section 3 is measured against this logical clock.

### 2.12. Validation Ordering

Where several checks could fail a single request, the server evaluates them in a fixed priority order so that the returned error is deterministic. Authentication is checked first: missing headers or an unknown role yield `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the endpoint yields `ERR_FORBIDDEN_ROLE`. Then existence of every referenced resource is verified left-to-right (path identifiers before body foreign keys), yielding `ERR_NOT_FOUND`. Then the target resource's state is checked against the requested transition, yielding `ERR_INVALID_STATE` if the transition is not defined from the current state. Then, on work-order cancellation only, the optimistic-concurrency check compares `expected_work_order_version` and yields `ERR_STALE_VERSION` on mismatch. Domain-specific business gates follow in this relative order: the permit-required gate (`ERR_PERMIT_REQUIRED`), the technician-certification gate (`ERR_TECH_NOT_CERTIFIED`), the relocation-distance gate (`ERR_RELOCATION_DISTANCE`), the entry-point-mismatch gate (`ERR_ENTRY_POINT_MISMATCH`), the technician-window-conflict gate (`ERR_TECH_WINDOW_CONFLICT`), the monitoring-visit-overlap gate (`ERR_VISIT_OVERLAP`), the window-well-formedness gate (`ERR_INVALID_WINDOW`), the empty-set guard (`ERR_EMPTY_SET`), and the kit-capacity gate (`ERR_KIT_EXHAUSTED`). Last of all, generic body-shape validation — missing required fields, bad enum values, out-of-range numbers, or non-positive quantities — yields `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Configuration: Species, Technicians, Accounts, and Properties

Before any field work can be quoted, the reference data must exist. A `ComplianceOfficer` defines each **species profile** with a human display `common_name` and a short `code` that must be unique across all species profiles under a case-sensitive exact-match comparison. The profile declares whether the species `is_regulated` (defaulting to not regulated), the lawful relocation band as a `relocation_min_miles` and `relocation_max_miles` pair (defaulting to a minimum of 0 and a maximum of 25 miles), the `humane_check_interval_hours` ceiling on how long a live trap may go unchecked (defaulting to 24 and never below 1), the `base_trap_fee_cents` per-trap placement fee, and the `risk_weight` each individual of this species contributes to the infestation score (defaulting to 1.0). The relocation minimum must be at least 0 and no greater than the maximum, and the maximum must be at least the minimum.

A `Dispatcher` registers each **technician** with a `full_name`, a `license_tier`, and a `kit_trap_capacity`. The license tier is one of `BASIC` or `CERTIFIED`, defaulting to `BASIC`; a `BASIC` technician may run only non-regulated removals, while a `CERTIFIED` technician may also run regulated-species removals. On registration the technician's `traps_deployed` starts at 0 and `traps_available` starts equal to `kit_trap_capacity`.

A `Dispatcher` also creates **service accounts**, each carrying an `account_name` and a `contact_email`, and **properties**, each tied to its billing account by `account_id` and located by `latitude` (between -90 and 90 inclusive) and `longitude` (between -180 and 180 inclusive). A property's geographic point is the origin for every relocation-distance compliance check on captures made there. A new property's `posture` is initialized to `OPEN`. Posture is a derived field with three values — `OPEN` when no active work is in progress, `ACTIVE_REMEDIATION` while a work order is being executed, and `REGULATORY_HOLD` while a regulated-species permit on an active work order is still awaiting decision — and a property in `REGULATORY_HOLD` blocks the completion of new inspections (see §3.2).

### 3.2. Inspection and Entry-Point Findings

A `Dispatcher` schedules an **inspection** on a property, supplying the `scheduled_for` visit time and an optional `is_emergency` flag (defaulting to false). The inspection is created with its `status` field at `DRAFT` and a `detected_individual_count` of 0; the property is recorded via `property_id`. (Each lifecycle-bearing entity — inspection, quote, permit, trap placement, warranty claim — exposes its current lifecycle value through a `status` field, except the work order, which uses the dedicated `lifecycle`, `removal_status`, and `exclusion_status` fields described below.) An emergency inspection raises the eventual quote pricing, because the emergency basis is pinned onto any quote drawn from this inspection.

During the visit, findings are recorded as **entry points**, each created by a `Dispatcher` or a `FieldTechnician` against the inspection via `inspection_id`. An entry point names the `species_id` exploiting it, a human-readable `location_label`, an access `severity` of `MINOR`, `MODERATE`, or `MAJOR` (defaulting to `MODERATE`), and the `estimated_individuals` count of animals using it (at least 0). Each entry point begins with `seal_status` of `OPEN` and becomes `SEALED` only when an exclusion repair for it completes; residual-risk accounting later counts only the entry points still `OPEN`. Whenever an entry point is added, the parent inspection's `detected_individual_count` is refreshed to the sum of `estimated_individuals` across all of that inspection's entry points.

Closing the inspection's findings advances it from `DRAFT` to `COMPLETED`. This is permitted only when the inspection is currently `DRAFT`, when it has at least one entry point (so a detected-count basis exists), and when the property is not in `REGULATORY_HOLD` posture; a hold blocks the close. On success the status becomes `COMPLETED` and `detected_individual_count` is refreshed to the sum of its entry points' `estimated_individuals`. A `Dispatcher` may instead cancel a `DRAFT` inspection, moving it to the terminal `CANCELLED` status; cancellation is permitted only from `DRAFT`. Quotes may be drawn only from a `COMPLETED` inspection. Attempting either transition from any other state is rejected with `ERR_INVALID_STATE`.

### 3.3. Quoting and the Revision Loop

A `Dispatcher` creates a **quote** against a `COMPLETED` inspection by supplying the `inspection_id` together with an `expected_inspection_version`. The quote is born in `DRAFT` status, and its `emergency_flag` is copied from the parent inspection's `is_emergency` at creation time so the surcharge basis is pinned even if the inspection later changes. Creating a new quote supersedes any prior non-terminal quote on the same inspection: any existing quote on that inspection still in `DRAFT`, `SENT`, or `REVISION_REQUESTED` is moved to `SUPERSEDED`, and the inspection's `version` is incremented by one. Because the create races against that inspection version, the supplied `expected_inspection_version` must equal the inspection's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the dispatcher from superseding quotes against an inspection it has not freshly observed.

A `Dispatcher` populates a `DRAFT` quote with **line items**, each carrying the `quote_id` it belongs to, the `species_id` it prices, a `line_type` of either `TRAP` (pricing trap placements) or `EXCLUSION` (pricing the sealing and sanitation of entry points), a `quantity` of at least 1, and a pre-surcharge `unit_price_cents` of at least 0. Each line item starts with its `performed` flag false; the flag flips true only when the corresponding work is recorded, and it gates the line's inclusion in the final billing.

Sending the quote advances it from `DRAFT` to `SENT`. A quote may be sent only while in `DRAFT` and only if it carries at least one line item; sending an empty quote is rejected with `ERR_EMPTY_SET`. On send, the system computes `provisional_total_cents` as the forward-looking estimate over **all** line items. For each line, the raw amount is the `quantity` multiplied by `unit_price_cents`, multiplied by the surcharge factor — that factor is 1 plus fifteen percent when the quote's `emergency_flag` is set, and exactly 1 otherwise. Each line's raw amount is rounded to the nearest whole cent using round-half-up, and the rounded line amounts are then summed to give `provisional_total_cents`.

The quote supports a revision loop. The `PropertyOwner` may request revisions on a `SENT` quote, moving it to `REVISION_REQUESTED`. A `Dispatcher` may then reopen a `REVISION_REQUESTED` quote back to `DRAFT`, where its line items may be edited again, closing the `DRAFT → SENT → REVISION_REQUESTED → DRAFT` cycle. From `SENT`, the owner may also decline the quote (moving it to the terminal `DECLINED` state) or accept it. Each transition is legal only from its named source state; any other source yields `ERR_INVALID_STATE`. Acceptance, declination, and revision requests are reserved to the `PropertyOwner` who owns the underlying property's service account.

### 3.4. Acceptance: Spawning the Work Order, Risk, and Permits

When a `PropertyOwner` accepts a `SENT` quote, the request body supplies the `assigned_technician_id` that will execute the job, and a cascade of creations fires in order. First the quote moves to the terminal `ACCEPTED` state. Then a **work order** is created from the quote, recording the `quote_id`, a denormalized `property_id` for convenient filtering, and the `assigned_technician_id`; it begins with `lifecycle` of `OPEN`, and both parallel dimensions — `removal_status` and `exclusion_status` — at `PENDING`.

The work order's creation triggers two further effects. Its `initial_risk_score` is computed as the forward-looking infestation score over **all** entry points of the inspection (the initial variant), and its `net_charged_cents` is initialized to the quote's `provisional_total_cents`. Separately, for each distinct regulated species appearing among the inspection's entry points, a **permit** is created on the work order in `REQUESTED` status, recording the `work_order_id` and that `species_id` (its `permit_number` is initially absent). Finally the property's posture is reconciled: if any permit was created, the parent property's `posture` becomes `REGULATORY_HOLD`; if no permit was created, the property's `posture` becomes `ACTIVE_REMEDIATION`.

The infestation risk score is a weighted sum with a non-linear severity multiplier, a regulated-species bump, and a global ceiling. For each entry point in the variant's input set, the contribution is the entry point's `estimated_individuals` multiplied by its species' `risk_weight`, multiplied by a severity factor — 1.0 for `MINOR`, 2.0 for `MODERATE`, and 3.5 for `MAJOR`. If that entry point's species `is_regulated`, the contribution is then multiplied by 1.5. The contributions are summed, the running total is capped at a maximum of 1000.0 (the score never exceeds this ceiling), and the result is rounded to two decimal places using round-half-up. The initial variant computed at acceptance sums over every entry point of the inspection (none are sealed yet); the residual variant computed at close (see §3.6) sums over only the entry points whose `seal_status` is still `OPEN`, so it diverges from the initial score by the contribution of every entry point that was sealed.

### 3.5. Permit Adjudication

A `ComplianceOfficer` adjudicates each `REQUESTED` permit. Approval requires the permit to be in `REQUESTED` status and a `permit_number` to be supplied in the request body; on success the permit moves to `APPROVED` and the regulator-issued `permit_number` is stored. After an approval, if every permit on the work order is now `APPROVED`, the parent property's `posture` bubbles up to `ACTIVE_REMEDIATION`, lifting the regulatory hold.

Denial is the divergent branch. Denying a `REQUESTED` permit moves it to `DENIED` and cascades hard: the work order's `lifecycle` is driven to `CANCELLED`, the property's `posture` is reset to `OPEN`, and every trap placement on that work order still in the `SET` state is moved to `CANCELLED` with its trap returned to the owning technician's kit (each such cancellation decrements that technician's `traps_deployed` by one and increments `traps_available` by one). A denied permit thus blocks the regulated removal entirely. Either adjudication is legal only from `REQUESTED`; adjudicating an already-decided permit yields `ERR_INVALID_STATE`.

### 3.6. Field Execution: The Two Parallel Dimensions

A work order advances along two independent dimensions that the server tracks separately and then reconciles into the compound `lifecycle`. The removal dimension (`removal_status`) runs `PENDING → TRAPPING → CLEARED`; the exclusion dimension (`exclusion_status`) runs `PENDING → SEALING → SEALED`. The work order's `lifecycle` stays `OPEN` until both dimensions reach their terminal sub-states, at which point the server auto-closes it to `CLOSED`; a cancellation instead drives `lifecycle` to `CANCELLED`.

**Setting traps.** A `FieldTechnician` sets a **trap placement** on an `OPEN` work order, supplying the target `species_id`, the `technician_id` whose kit supplies the trap, and the on-site visit window as `window_start` and `window_end`. A new placement is created in `SET` status. Setting the first trap advances `removal_status` from `PENDING` to `TRAPPING`, decrements the technician's `traps_deployed` (raising it by one) and decreases `traps_available` (lowering it by one) to draw the trap from the conserved kit. The work order must be `OPEN` (otherwise `ERR_INVALID_STATE`). Several safety and capacity gates apply here and are detailed in §3.8.

**Recording captures.** When an animal is found, a `FieldTechnician` records a **capture event** against a `SET` trap on an `OPEN` work order; the event records the originating trap via `trap_placement_id` and carries the `captured_at` time and the release site's `release_latitude` and `release_longitude`. The server computes `release_distance_miles` as the great-circle (haversine) distance from the property's coordinates to the release site, using an Earth radius of 3958.8 miles, rounded to two decimal places using round-half-up. The release is lawful only when this rounded distance is at least the species' `relocation_min_miles` and at most its `relocation_max_miles` — both band edges inclusive; a distance outside the band is rejected with `ERR_RELOCATION_DISTANCE` and no capture persists. On a compliant release a capture event is created with `disposition` of `RELOCATED` (the only disposition that ever persists), and the trap moves from `SET` to `SPENT`. As a secondary effect, the trap's exit from `SET` returns it to the kit: the technician's `traps_deployed` drops by one and `traps_available` rises by one. If no trap placement on the work order remains `SET` after this, the `removal_status` advances from `TRAPPING` to `CLEARED`, and the matching `TRAP` line item's `performed` flag is set true.

**Pulling empty traps.** Alternatively, a `FieldTechnician` pulls a `SET` trap that caught nothing on an `OPEN` work order, moving it from `SET` to `EMPTY`; the technician's `traps_deployed` drops by one and `traps_available` rises by one. If no trap placement on the work order remains `SET` and at least one trap was ever set, `removal_status` advances to `CLEARED` and the matching `TRAP` line item's `performed` flag is set true. Pulling in a way that would mark removal `CLEARED` when no trap was ever set is rejected with `ERR_EMPTY_SET`. A trap may be set or voided into the `CANCELLED` status only as part of the permit-denial or work-order-cancellation cascades, never directly.

**Exclusion repairs.** A `FieldTechnician` starts an **exclusion repair** on an `OPEN` work order, supplying the `entry_point_id` to seal and an optional `sanitation_included` flag (defaulting to false, indicating whether decontamination is bundled). The repair is created in `STARTED` status, and starting the first repair advances `exclusion_status` from `PENDING` to `SEALING`. A repair may only target an entry point that belongs to the inspection underlying this work order's quote and whose `seal_status` is still `OPEN`; targeting an entry point from a different inspection, or one already `SEALED`, is rejected with `ERR_ENTRY_POINT_MISMATCH`. Completing a repair (the repair is named by its own `repair_id` in the path) requires the work order to be `OPEN`, the repair's `status` to be `STARTED`, and — crucially — the removal dimension to have reached `CLEARED` first, because sealing the building before the animals are cleared would trap them inside; completing while `removal_status` is not `CLEARED` is rejected with `ERR_INVALID_STATE`. On completion the repair's `status` moves to `COMPLETED`, the targeted entry point's `seal_status` becomes `SEALED`, and the matching `EXCLUSION` line item's `performed` flag is set true. When all of the open entry points targeted by repairs are sealed, `exclusion_status` advances from `SEALING` to `SEALED`.

**Auto-close.** The moment `removal_status` is `CLEARED` and `exclusion_status` is `SEALED`, the server fires the work order's `OPEN → CLOSED` transition without any explicit client request. On close, `final_total_cents` is computed (see §3.7) over the performed line items and stored on the quote; the work order's `net_charged_cents` is reconciled to that final total; the `residual_risk_score` is recomputed using the residual variant of the infestation score over only the entry points whose `seal_status` remains `OPEN`; and the property's `posture` returns to `OPEN`.

### 3.7. Money: Provisional, Final, Cancellation Refund

Two monetary totals describe a job. The provisional total, computed when the quote is sent (see §3.3), is the forward-looking estimate over every line item. The **final total** is computed when the work order auto-closes and is the chronological actual: it sums only the line items whose `performed` flag is true. For each performed line, the raw amount is `quantity` multiplied by `unit_price_cents` multiplied by the same surcharge factor (1 plus fifteen percent when the quote's `emergency_flag` is set, otherwise 1), each line rounded to the nearest whole cent using round-half-up, and the rounded performed-line amounts summed to give `final_total_cents`. The final total diverges from the provisional whenever any quoted line went unperformed.

Cancellation reconciles the money along a different path. When a `Dispatcher` cancels an `OPEN` work order — supplying the matching `expected_work_order_version` per §2.6 — the system computes the **performed subtotal**: for each line item whose `performed` flag is true, the raw amount (`quantity` times `unit_price_cents` times the surcharge factor) is rounded to the nearest whole cent using round-half-up, and these rounded amounts are summed; then a flat sanitation fee of 7500 cents is added for each `COMPLETED` exclusion repair whose `sanitation_included` flag is true. The refund is the work order's current `net_charged_cents` minus this performed subtotal, and `net_charged_cents` settles down to the performed subtotal. Because the work order's `net_charged_cents` plus the refund equals the originally committed provisional total, no money is created or destroyed.

The cancellation cascade also drives `lifecycle` to `CANCELLED`; moves every `SET` trap placement on the work order to `CANCELLED`, restoring each to its technician's kit (each decrements `traps_deployed` by one and increments `traps_available` by one); resets the property's `posture` to `OPEN`; and increments the work order's `version` by one. Cancellation is legal only while `lifecycle` is `OPEN`; from any other lifecycle it is rejected with `ERR_INVALID_STATE`.

### 3.8. Safety and Capacity Gates on Trap Placement

Setting a trap is the most heavily guarded operation in the system, and its checks are evaluated in the global priority order described in §2.12, after authentication, authorization, existence, and the work-order `OPEN` state check have all passed. Four domain-specific gates then apply, in this order. First, the permit gate: if the trap's species `is_regulated`, a permit for that species on this work order must be `APPROVED`; otherwise the set is rejected with `ERR_PERMIT_REQUIRED`. Second, the certification gate: a `BASIC`-tier technician may not set a trap for a regulated species — that requires a `CERTIFIED` technician — and an attempt is rejected with `ERR_TECH_NOT_CERTIFIED`. Third, the technician-window-conflict gate: the trap's visit window, taken as the closed interval from `window_start` to `window_end` and inflated by a buffer on each side, must not overlap the buffered window of any other `SET` trap on the same technician; an overlap is rejected with `ERR_TECH_WINDOW_CONFLICT`. The buffer applied on each side is fifteen minutes. Fourth, the kit-capacity gate: a set that would drive the assigned technician's `traps_available` below 0 is rejected with `ERR_KIT_EXHAUSTED`.

Independently, the visit window itself must be well formed: `window_end` must be strictly after `window_start`, or the request is rejected with `ERR_INVALID_WINDOW`. The same well-formedness rule applies to monitoring visits (`visit_end` strictly after `visit_start`).

### 3.9. Recurring Monitoring and Warranty

After a work order closes, it enters a monitoring-and-warranty phase. A `FieldTechnician` logs a **monitoring visit** against the closed work order, recording the `work_order_id`, the `property_id` visited, the `visit_start` and `visit_end` window, and an informational `traps_reset` count of traps re-set during the visit (defaulting to 0). A monitoring visit's window is treated as the half-open interval from `visit_start` up to but not including `visit_end`, with no buffer; it must not overlap any other monitoring visit on the same property, and an overlap is rejected with `ERR_VISIT_OVERLAP`.

The `PropertyOwner` may file a **warranty claim** against a closed work order, supplying the `reported_at` time of the recurrence and a free-text `description`; the claim is created in `FILED` status. A `ComplianceOfficer` adjudicates a `FILED` claim against two conditions. The claim is eligible when its `reported_at` is at or before the warranty deadline, where the deadline is the work order's close timestamp plus thirty days and the boundary is inclusive (a `reported_at` exactly equal to the deadline still accepts). The claim is qualified only when the work order actually sealed something — that is, at least one `EXCLUSION` line item was performed on it. The claim is accepted (status `ACCEPTED`) only when it is both eligible and qualified; otherwise — if `reported_at` is after the deadline, or the work order's `lifecycle` is not `CLOSED`, or nothing was sealed — it is rejected (status `REJECTED`). Adjudication is legal only from `FILED`; re-adjudicating yields `ERR_INVALID_STATE`.

### 3.10. Listing and Cross-Reference Retrieval

Beyond the workflows above, the system exposes read access across the hierarchy so operators can navigate it. Properties may be listed and narrowed by an `account_id` filter; entry points, quote line items, permits, and trap placements may each be narrowed by a `species_id` filter; quotes by an `inspection_id` filter; trap placements additionally by a `technician_id` filter; work orders by `quote_id`, `property_id`, or `assigned_technician_id` filters; exclusion repairs by an `entry_point_id` filter; and monitoring visits by a `property_id` filter. A single line item or a single monitoring visit may also be fetched directly by its own identifier so that those collection segments resolve. All such lists honor the pagination and ordering rules of §2.3.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`; operations that modify or transition an existing resource (including the various lifecycle actions and the clock-set capability) return `200 OK`. List and fetch reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/species-profiles` | Create a species profile | ComplianceOfficer |
| GET | `/species-profiles/{id}` | Fetch a species profile | ComplianceOfficer, Dispatcher, FieldTechnician, PropertyOwner |
| GET | `/species-profiles` | List species profiles | ComplianceOfficer, Dispatcher, FieldTechnician, PropertyOwner |
| POST | `/technicians` | Register a field technician | Dispatcher |
| GET | `/technicians/{id}` | Fetch a technician with live kit counts | Dispatcher, FieldTechnician, ComplianceOfficer |
| GET | `/technicians` | List technicians | Dispatcher, FieldTechnician, ComplianceOfficer |
| POST | `/service-accounts` | Create a billing account | Dispatcher |
| GET | `/service-accounts/{id}` | Fetch a service account | Dispatcher, PropertyOwner, ComplianceOfficer |
| POST | `/properties` | Create a property under an account | Dispatcher |
| GET | `/properties/{id}` | Fetch a property including posture | Dispatcher, PropertyOwner, ComplianceOfficer, FieldTechnician |
| GET | `/properties` | List properties (optional account filter) | Dispatcher, PropertyOwner, ComplianceOfficer |
| POST | `/properties/{id}/inspections` | Schedule an inspection on a property | Dispatcher |
| GET | `/properties/{id}/inspections` | List a property's inspections | Dispatcher, PropertyOwner, ComplianceOfficer, FieldTechnician |
| GET | `/inspections/{id}` | Fetch an inspection | Dispatcher, PropertyOwner, ComplianceOfficer, FieldTechnician |
| POST | `/properties/{id}/inspections/{inspection_id}/complete` | Close an inspection's findings | Dispatcher |
| POST | `/properties/{id}/inspections/{inspection_id}/cancel` | Cancel a draft inspection | Dispatcher |
| POST | `/inspections/{id}/entry-points` | Record an entry point | Dispatcher, FieldTechnician |
| GET | `/inspections/{id}/entry-points` | List an inspection's entry points | Dispatcher, PropertyOwner, ComplianceOfficer, FieldTechnician |
| GET | `/entry-points/{id}` | Fetch an entry point | Dispatcher, PropertyOwner, ComplianceOfficer, FieldTechnician |
| GET | `/entry-points` | List entry points (optional species filter) | Dispatcher, ComplianceOfficer, FieldTechnician |
| POST | `/quotes` | Create a quote against a completed inspection | Dispatcher |
| GET | `/quotes/{id}` | Fetch a quote with totals | Dispatcher, PropertyOwner, ComplianceOfficer |
| GET | `/quotes` | List quotes (optional inspection filter) | Dispatcher, PropertyOwner, ComplianceOfficer |
| POST | `/quotes/{id}/line-items` | Add a line item to a draft quote | Dispatcher |
| GET | `/quotes/{id}/line-items` | List a quote's line items | Dispatcher, PropertyOwner, ComplianceOfficer |
| GET | `/line-items/{id}` | Fetch a single line item | Dispatcher, ComplianceOfficer, PropertyOwner |
| GET | `/line-items` | List line items (optional species filter) | Dispatcher, ComplianceOfficer |
| POST | `/quotes/{id}/send` | Send a draft quote; compute provisional total | Dispatcher |
| POST | `/quotes/{id}/request-revision` | Request revisions on a sent quote | PropertyOwner |
| POST | `/quotes/{id}/reopen` | Reopen a revision-requested quote to draft | Dispatcher |
| POST | `/quotes/{id}/accept` | Accept a sent quote; spawn work order and permits | PropertyOwner |
| POST | `/quotes/{id}/decline` | Decline a sent quote | PropertyOwner |
| GET | `/work-orders/{id}` | Fetch a work order | Dispatcher, PropertyOwner, ComplianceOfficer, FieldTechnician |
| GET | `/work-orders` | List work orders (optional quote/property/technician filters) | Dispatcher, ComplianceOfficer, FieldTechnician, PropertyOwner |
| POST | `/work-orders/{id}/cancel` | Cancel an open work order; refund and restore kit | Dispatcher |
| GET | `/work-orders/{id}/permits` | List a work order's permits | ComplianceOfficer, Dispatcher, FieldTechnician |
| GET | `/permits/{id}` | Fetch a permit | ComplianceOfficer, Dispatcher, FieldTechnician |
| GET | `/permits` | List permits (optional species filter) | ComplianceOfficer, Dispatcher |
| POST | `/permits/{id}/approve` | Approve a requested permit | ComplianceOfficer |
| POST | `/permits/{id}/deny` | Deny a requested permit; cancel the work order | ComplianceOfficer |
| POST | `/work-orders/{id}/trap-placements` | Set a trap on an open work order | FieldTechnician |
| GET | `/work-orders/{id}/trap-placements` | List a work order's trap placements | FieldTechnician, Dispatcher, ComplianceOfficer |
| GET | `/trap-placements/{id}` | Fetch a trap placement | FieldTechnician, Dispatcher, ComplianceOfficer |
| GET | `/trap-placements` | List trap placements (optional species/technician filters) | FieldTechnician, Dispatcher, ComplianceOfficer |
| POST | `/trap-placements/{id}/captures` | Record a humane capture and relocation | FieldTechnician |
| POST | `/trap-placements/{id}/pull` | Pull an empty trap | FieldTechnician |
| GET | `/trap-placements/{id}/captures` | List a trap's capture events | FieldTechnician, Dispatcher, ComplianceOfficer |
| POST | `/work-orders/{id}/exclusion-repairs` | Start an exclusion/sealing repair | FieldTechnician |
| GET | `/work-orders/{id}/exclusion-repairs` | List a work order's exclusion repairs | FieldTechnician, Dispatcher, ComplianceOfficer |
| GET | `/exclusion-repairs/{id}` | Fetch an exclusion repair | FieldTechnician, Dispatcher, ComplianceOfficer |
| GET | `/exclusion-repairs` | List exclusion repairs (optional entry-point filter) | FieldTechnician, Dispatcher, ComplianceOfficer |
| POST | `/work-orders/{id}/exclusion-repairs/{repair_id}/complete` | Complete a sealing repair; may auto-close work order | FieldTechnician |
| POST | `/work-orders/{id}/monitoring-visits` | Record a monitoring/re-set visit | FieldTechnician |
| GET | `/work-orders/{id}/monitoring-visits` | List a work order's monitoring visits | FieldTechnician, Dispatcher, ComplianceOfficer, PropertyOwner |
| GET | `/monitoring-visits/{id}` | Fetch a single monitoring visit | FieldTechnician, Dispatcher, ComplianceOfficer, PropertyOwner |
| GET | `/monitoring-visits` | List monitoring visits (optional property filter) | FieldTechnician, Dispatcher, ComplianceOfficer, PropertyOwner |
| POST | `/work-orders/{id}/warranty-claims` | File a warranty/callback claim | PropertyOwner |
| GET | `/work-orders/{id}/warranty-claims` | List a work order's warranty claims | PropertyOwner, Dispatcher, ComplianceOfficer |
| GET | `/warranty-claims/{id}` | Fetch a warranty claim | PropertyOwner, Dispatcher, ComplianceOfficer |
| POST | `/warranty-claims/{id}/adjudicate` | Adjudicate a filed warranty claim | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Dispatcher, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PERMIT_REQUIRED` | 409 |
| `ERR_TECH_NOT_CERTIFIED` | 409 |
| `ERR_RELOCATION_DISTANCE` | 422 |
| `ERR_ENTRY_POINT_MISMATCH` | 409 |
| `ERR_TECH_WINDOW_CONFLICT` | 409 |
| `ERR_VISIT_OVERLAP` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_EMPTY_SET` | 409 |
| `ERR_KIT_EXHAUSTED` | 409 |
| `ERR_INVALID_REQUEST` | 422 |

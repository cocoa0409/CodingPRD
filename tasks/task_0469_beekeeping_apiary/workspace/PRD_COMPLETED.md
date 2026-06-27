# Beekeeping Apiary API — Product Requirements Document

## 1. Introduction

Commercial beekeeping is a business of moving living colonies through a calendar of biological deadlines: mites surge in late summer, queens fail unpredictably, almond bloom opens a two-week pollination window worth more than a year of honey, and a single mis-timed miticide application can render an entire honey lot unsellable. This document specifies the Beekeeping & Pollination Service API, a system of record that ties together yard locations, individual colonies, their health and queen lifecycles, mite inspections and chemical treatments, honey extraction lots, almond pollination contracts and the physical placement of hives on orchards, queen and nucleus-colony sales, supplemental feeding, requeening schedules, and state apiary registration.

The system serves four cooperating parties: the beekeeper who runs the day-to-day apiary, the state authority who licenses each yard, the contract coordinator who brokers pollination work and live-bee sales, and a platform operator who controls the system's logical clock. Because nearly every rule in this domain is time-gated — a treatment must cure before a colony can be harvested, a registration must be current before a hive can be placed, a contract can only be fulfilled after bloom ends — the system does not read the wall clock. Instead it maintains a single logical clock that an operator advances explicitly, so that the full seasonal calendar can be exercised deterministically.

A central design concern is **conservation**: the count of living colonies in a yard, and the mass of honey rolled into a lot, are quantities that must stay consistent across every cascade, revert, and compensation. When a colony dies, when a nucleus is sold off, when a harvest is voided, the affected aggregate totals must be recomputed so they never drift away from the underlying truth. The sections that follow define the global contract that all endpoints share, the cross-cutting principles that govern consistency and safety, and the business workflows for each part of the operation.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All collections are mounted directly under the service root; there is no single nesting parent.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `PlatformAdmin`, `ApiaryManager`, `StateApiarist`, and `ContractCoordinator`.

`PlatformAdmin` is the operational superuser. It alone controls the logical clock, it can register apiaries, and it can read everything. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

`ApiaryManager` is the beekeeper who operates a specific yard, acting *as* that apiary. When `X-User-Role` is `ApiaryManager`, `X-User-ID` is the `id` of the acting `Apiary`; ownership checks on any resource that references an `Apiary` compare the resource's owning apiary to `X-User-ID`. Concretely, for every `ApiaryManager`-initiated mutation on hives, inspections, treatments, harvests, honey lots, feedings, requeen schedules, and queen/nucleus sales, the system verifies that `X-User-ID` equals the `apiary_id` of the apiary that owns the target resource; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. A hive's, treatment's, inspection's, feeding's, requeen-schedule's, harvest's, or honey lot's owning apiary is resolved through its chain of foreign keys back to an `Apiary`.

`StateApiarist` is the state apiary-registration authority that files, approves, expires, and revokes registrations. `ContractCoordinator` manages pollination contracts, hive placements, and queen and nucleus sales. For both `StateApiarist` and `ContractCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system carry a standard set of system-managed fields. The `id` is a unique, server-minted identifier formatted as a UUID with no type prefix. The `created_at` field is an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification; it is refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every modification to the resource, and it is the basis for optimistic concurrency control.

Two entities are deliberate exceptions: an `Inspection` and a `Feeding` are immutable, append-only event records. Each carries only `id` and `created_at` — neither `updated_at` nor `version` is present on these two, because once written they are never modified.

Because every temporal rule in this domain depends on "now", the system maintains a single **logical clock** rather than reading the host's wall clock. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it remains at exactly this default and never falls back to wall-clock time. An operator may set the clock to an explicit UTC instant, supplied as the `to_iso8601` field; reading the clock returns its current value. Both the set and the read return the current clock value in the response `data` as a single `current_utc` field (an ISO 8601 UTC timestamp with three fractional digits), and both return `200 OK`. Whenever the clock is advanced, the system re-evaluates time-driven state — most importantly, registrations whose validity window has elapsed (see §2.5). Time-gated transitions throughout the system compare against this clock; attempting one before the clock has reached the required date is rejected with `ERR_TOO_EARLY`.

### 2.5. State Apiary Registration and Jurisdiction

Each yard physically sits in a US state, identified by its two-letter uppercase `state_code` (for example `CA`, `OR`, or `ND`), which drives its registration jurisdiction. A yard's `registration_status` is a computed mirror of its registration lifecycle and is one of `UNREGISTERED`, `PENDING`, `ACTIVE`, or `EXPIRED`; a freshly created apiary is `UNREGISTERED`.

A `StateRegistration` carries the state-issued `registration_number`, an `effective_date` (the first instant the registration is valid, inclusive), and an `expiry_date` (the instant validity ceases, treated as an exclusive upper bound). Its own `status` lifecycle is one of `PENDING`, `ACTIVE`, `EXPIRED`, or `REVOKED`. A registration becomes valid only inside the half-open window from `effective_date` (inclusive) up to `expiry_date` (exclusive). Filing a registration, approving it, expiring it, and revoking it are detailed in §3.

A key consistency rule lives here: whenever the logical clock is advanced, any `StateRegistration` currently in `ACTIVE` whose `expiry_date` is at or before the new clock value transitions from `ACTIVE` to `EXPIRED`, and the owning apiary's `registration_status` is set to `EXPIRED` in the same step. This is the system-driven re-evaluation referenced in §2.4.

### 2.6. Parallel Colony Lifecycle and Hierarchical Consistency

A colony (`Hive`) carries two **independent** state axes that evolve separately. The health axis, `health_status`, is one of `HEALTHY`, `TREATMENT`, `QUARANTINE`, or `DEADOUT`; a new colony starts `HEALTHY`. The queen axis, `queen_status`, is one of `QUEENRIGHT`, `QUEENLESS`, or `REQUEENING`; a new colony starts `QUEENRIGHT`. A change on one axis does not, by itself, move the other — for example marking a colony `QUEENLESS` leaves `health_status` untouched. The single exception is that `DEADOUT` on the health axis is terminal for the whole colony: once a hive is `DEADOUT` no further transition on either axis is permitted, and the queen axis is frozen wherever it stood.

Many operations cascade across the resource hierarchy. When a single operation changes more than one entity, every affected entity is mutated, its `updated_at` refreshed, and its `version` incremented (for those entities that carry `version`). Computed roll-ups — an apiary's `active_colony_count`, a contract's `placed_strong_hives` and `projected_payout_cents`, a lot's `gross_weight_kg` and yield fields — are recomputed as part of the same operation that triggers them, so the system is always immediately consistent. The detailed cascades (colony death rippling into placements and contracts; a treatment freezing dependent honey lots; a void restoring conserved totals) are described in §3 alongside the workflows that drive them.

### 2.7. Nested Resource Retrieval and Existence

Several paths address a resource through a chain of identifiers — for instance a registration beneath an apiary, a placement beneath a contract, or a sub-resource beneath a hive. The system validates the existence of each path identifier in strict left-to-right order and rejects the request at the **first** identifier that does not resolve, returning `ERR_NOT_FOUND`. A registration request under a non-existent apiary therefore fails on the apiary before the registration is ever consulted.

Separately, when a create request carries a foreign key in its body — such as `apiary_id`, `hive_id`, `source_hive_id`, `contract_id`, or `lot_id` — and that key does not reference an existing resource, the request is rejected with `ERR_FK_NOT_FOUND`. Path-identifier failures and body-foreign-key failures are distinct: the former is `ERR_NOT_FOUND`, the latter is `ERR_FK_NOT_FOUND`.

### 2.8. Validation Ordering

When several checks apply to one operation, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. The order is: first, authentication of the request headers (`ERR_UNAUTHENTICATED`); then role authorization for the operation (`ERR_FORBIDDEN_ROLE`); then, for `ApiaryManager` mutations, resource ownership (`ERR_NOT_RESOURCE_OWNER`); then existence of every path-referenced resource, left to right (`ERR_NOT_FOUND`); then existence of every body foreign key (`ERR_FK_NOT_FOUND`); then that the target is not already in a terminal state (`ERR_TERMINAL_STATE`); then that the target resource is otherwise in a state from which the requested transition is allowed (`ERR_INVALID_STATE`). Because an `ApiaryManager`'s ownership target is the apiary reached through the target resource (and, for a resource owned via a body foreign key, through that key), the system must first resolve the target's existence — and the body foreign key's existence — in order to evaluate ownership at all; consequently a path-existence failure (`ERR_NOT_FOUND`) or a body-foreign-key failure (`ERR_FK_NOT_FOUND`) on the owning resource is reported before `ERR_NOT_RESOURCE_OWNER`. The terminal-state check is evaluated before the allowed-state check, so a transition attempted on a resource already in a terminal state surfaces as `ERR_TERMINAL_STATE` rather than `ERR_INVALID_STATE`. Only after these structural checks pass does the system evaluate the domain-specific business rules — withdrawal blocks, registration currency, placement eligibility, double-booking, site capacity, brood sufficiency, yard capacity, empty-lot, time gates, optimistic concurrency, and finally well-formedness and uniqueness of the request body. The business rules carry their own dedicated error codes, introduced in context throughout §3; where two business rules could both apply, the lower-numbered concern in this ordering is reported first.

### 2.9. Honey-Mass and Colony Conservation

Two quantities are conserved invariants that the system guarantees never drift. The first is an apiary's `active_colony_count`: the number of hives in the yard whose `health_status` is not `DEADOUT`. It starts at zero, rises by one when a colony is created in the yard, and is recomputed whenever a colony dies or a nucleus sale removes or restores a colony. A yard also carries `max_yard_colonies`, an integer of at least one that caps how many non-`DEADOUT` colonies the yard may hold; operations that would push the count above this cap are rejected.

The second conserved quantity is a honey lot's `gross_weight_kg`: the running sum of the `weight_kg` of every non-voided harvest contribution rolled into the lot. Crediting a harvest raises it; voiding a harvest, or voiding the whole lot, lowers it back so the sum always reflects exactly the live contributions. Voiding the entire lot voids each of its recorded harvests and restores `gross_weight_kg` to zero.

### 2.10. Precision and Monetary Rules

All weight-based yields (`provisional_yield_kg`, `final_yield_kg`) are rounded to exactly two decimal places using the round-half-up method. Monetary amounts are stored as integer cents: `base_rate_cents`, `price_per_kg_cents`, `price_cents`, `gross_revenue_cents`, `net_revenue_cents`, and `projected_payout_cents` are whole cents. Wherever a calculation reduces a fractional cents value to an integer, the round-half-up method is used, and the precise rounding *order* for each calculation is pinned in §3 — for payout, each per-hive amount is rounded before the sum is taken, never after; for honey revenue, the gross is rounded first, the discount tier is selected from that rounded gross, and the discount is then rounded and subtracted. A colony strength score is an integer in the inclusive range from 0 to 100 with no fractional points.

### 2.11. Optimistic Concurrency on Placement Confirmation

Confirming a hive placement is guarded by optimistic concurrency control against the parent pollination contract. Each confirmation legitimately consumes site capacity and advances the contract — it can raise `placed_strong_hives` and it always increments the contract's `version`. Because of this, a confirmation request must carry `expected_contract_version`, a non-optional field that holds the contract `version` the client last observed. If `expected_contract_version` does not equal the contract's current `version` — meaning another writer has advanced the contract since the client last read it — the confirmation is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), forcing the client to re-read before acting on out-of-date capacity. No other endpoint accepts a version field; placement confirmation is the only operation under optimistic concurrency control.

## 3. Business Logic & Workflows

### 3.1. Establishing a Yard and Its Registration

A yard is established by registering an `Apiary`, supplying its `name`, the two-letter `state_code`, its `latitude` and `longitude` in decimal degrees, and its `max_yard_colonies`. On creation the yard's `registration_status` is `UNREGISTERED` and its `active_colony_count` is zero. This operation is available to a platform operator or to a beekeeper.

Bringing a yard into compliance is the state authority's lifecycle. The authority files a registration against the apiary, supplying the `registration_number`, the `effective_date`, and the `expiry_date`; the new registration begins in `PENDING`, and if the apiary was previously `UNREGISTERED` its `registration_status` becomes `PENDING`. Approving a registration moves it from `PENDING` to `ACTIVE`; this is permitted only when the registration is still `PENDING`, when the logical clock is at or after the `effective_date`, and when the clock is strictly before the `expiry_date`. Approval sets the owning apiary's `registration_status` to `ACTIVE` and increments the registration's `version`. Attempting approval outside the window surfaces as `ERR_TOO_EARLY` when the clock has not yet reached `effective_date`; attempting it when the clock is at or past `expiry_date` is an `ERR_INVALID_STATE`; and attempting it on a registration that is not `PENDING` is an `ERR_INVALID_STATE`.

Expiring an `ACTIVE` registration moves it to `EXPIRED` and sets the apiary's `registration_status` to `EXPIRED`, incrementing the registration's `version`; this happens either when an authority or platform operator expires it explicitly, or automatically when the clock is advanced to or past the `expiry_date` as described in §2.5. The explicit expiry transition requires the registration to currently be `ACTIVE` (otherwise `ERR_INVALID_STATE`, or `ERR_TERMINAL_STATE` if it is the terminal `REVOKED`) and the clock to be at or after `expiry_date` (attempting it earlier is `ERR_TOO_EARLY`). Revoking a `PENDING` registration moves it to `REVOKED`, which is a terminal state; if no other registration on that apiary remains `ACTIVE`, the apiary's `registration_status` falls back to `UNREGISTERED`. Revocation is permitted only while the registration is `PENDING`. Registrations can be listed for an apiary, which is also how a registration is located through its `apiary_id`.

### 3.2. Colonies: Births, Splits, and the Two State Axes

A colony is created within a yard by referencing the owning `apiary_id` and giving it a physical `tag` that must be unique within that apiary; optionally an initial `brood_frames` count (a non-negative integer, defaulting to zero) and a `source_hive_id` may be supplied. The `source_hive_id` points back to the parent colony a nucleus was split from, making the hive self-referential; it is null for a wild or purchased colony. On creation `health_status` is `HEALTHY`, `queen_status` is `QUEENRIGHT`, `honey_frames` is zero, `inspection_strength` is zero, `last_mite_count` and `harvest_blocked_until` are null, and the owning apiary's `active_colony_count` rises by one. Hives can be listed and filtered by `apiary_id` (to enumerate a yard's colonies), by `source_hive_id` (to find the nucleus splits of a parent colony), and by `health_status`.

The queen axis cycles independently of health. A queenright colony can be marked `QUEENLESS` directly, or it falls to `QUEENLESS` automatically when an inspection records that the queen was not seen (see §3.3); either path requires only that the colony is not `DEADOUT`. From `QUEENLESS` the colony advances to `REQUEENING` only by starting a due requeen schedule (see §3.7). From `REQUEENING` the colony returns to `QUEENRIGHT` by completing the requeening, which requires the colony to currently be `REQUEENING` and not `DEADOUT`. The full cycle is `QUEENRIGHT → QUEENLESS → REQUEENING → QUEENRIGHT`.

Quarantining a colony moves `health_status` from `HEALTHY` to `QUARANTINE` and, as a side effect, cancels any `PROPOSED` hive placement of that colony. Quarantine is permitted only from `HEALTHY`.

Marking a colony `DEADOUT` is the overwinter-loss event and the most consequential cascade in the system. It is permitted from any non-`DEADOUT` health state. Its effects unfold in three hops. First, the owning apiary's `active_colony_count` is recomputed as the count of its non-`DEADOUT` hives, decrementing it. Second, for every `CONFIRMED` hive placement of the dead colony, that placement transitions from `CONFIRMED` to `REMOVED`, and if its `grade` was `CONTRACT_GRADE` the parent contract's `placed_strong_hives` is decremented. Third, for each contract so affected, its `placed_strong_hives` is recomputed from its remaining `CONFIRMED` `CONTRACT_GRADE` placements, its `projected_payout_cents` is recomputed from the remaining confirmed placements, and its `version` is incremented — this recompute runs for every affected contract regardless of its current status; additionally, if the contract is currently in `PLACED` and its recomputed `placed_strong_hives` has fallen below its `required_strong_hives`, the contract transitions from `PLACED` to `UNDERSTAFFED`. All three hops complete within the single death operation.

### 3.3. Inspections and Colony Strength

An inspection is an immutable record of a single visit to a colony. The inspector supplies the `inspected_at` instant (which orders inspections chronologically), the measured `mites_per_100_bees` (a non-negative number from an alcohol-wash count), the `brood_frames_observed` (a non-negative integer), optionally the `honey_frames_observed` (a non-negative integer defaulting to zero), and the boolean `queen_seen` indicating whether the queen was observed laying. Each inspection references its colony through `hive_id`, and a hive's inspections can be listed.

Recording an inspection writes through to the colony: the hive's `brood_frames` is set to the observed brood frames, its `honey_frames` is set to the observed honey frames, and its `last_mite_count` is set to this inspection's mite reading. The inspection also computes a boolean `treatment_recommended`, which is true exactly when `mites_per_100_bees` is at or above the mite-treatment threshold of 3.0 mites per 100 bees, and false otherwise — this is a precise boundary, so a reading of exactly 3.0 recommends treatment. If `queen_seen` is false and the colony is currently `QUEENRIGHT`, the queen axis flips to `QUEENLESS` as part of the same inspection.

Each inspection also recomputes the colony's point-in-time strength score, stored in `inspection_strength`. The score is built from integer frame counts and the latest mite reading. The base is the brood-frame count weighted by 8 plus the honey-frame count weighted by 3. From this base a mite penalty of 25 points is subtracted when the colony's most recent mite reading (`last_mite_count`) is at or above the 3.0 threshold, and zero is subtracted otherwise. A queen bonus of 10 points is added when the colony is `QUEENRIGHT`, and zero is added otherwise; the queen status used here is the colony's status *after* this inspection's queen flip has been applied, so an inspection that drives a colony `QUEENRIGHT → QUEENLESS` scores with no queen bonus. The raw result is the base minus the mite penalty plus the queen bonus, and the final score is that raw value clamped into the inclusive range from 0 to 100 — any value below 0 becomes 0 and any value above 100 becomes 100. The point-in-time variant uses the brood and honey frame counts exactly as observed at this inspection, with the mite reading taken from this inspection. (The same scoring formula is reused with a forward-looking input set at placement confirmation; see §3.5.)

### 3.4. Mite Treatments, Withdrawal Windows, and Honey-Lot Blocking

When mites cross the action threshold, the beekeeper applies a miticide. Applying a treatment to a colony records a `Treatment` with its `product` (one of `APIVAR`, `FORMIC_PRO`, or `OXALIC_ACID`), the `applied_at` instant, and the `duration_days` the product remains on the hive (an integer of at least one). The new treatment starts `ACTIVE`. A treatment may be applied while the colony's `health_status` is `HEALTHY` or `QUARANTINE`, and applying it sets `health_status` to `TREATMENT`. Treatments for a hive can be listed and filtered by `status`.

Each product carries a chemical residue `withdrawal_days`: `APIVAR` requires 14 withdrawal days, while `FORMIC_PRO` and `OXALIC_ACID` require zero. The treatment computes `harvest_clear_at` as the `applied_at` instant advanced by `duration_days` days and then by `withdrawal_days` days. The colony's `harvest_blocked_until` field is then set to the latest (maximum) `harvest_clear_at` across all of the colony's `ACTIVE` treatments — the instant, exclusive, before which honey may not be pulled from this colony. Honey may not be harvested while that instant lies in the future relative to the logical clock.

Applying a treatment also cascades into honey lots: if any `DRAFT` honey lot already holds a `RECORDED` harvest drawn from this colony, that lot transitions from `DRAFT` to `BLOCKED`, freezing it for extraction until the colony clears. This is the system cascade that puts a lot into `BLOCKED`.

Completing a treatment moves it from `ACTIVE` to `COMPLETED`. It is permitted only while the treatment is `ACTIVE` and only once the logical clock has reached or passed the `applied_at` instant advanced by `duration_days` days; attempting it earlier is `ERR_TOO_EARLY`. Completion recomputes the colony's `harvest_blocked_until` from the remaining `ACTIVE` treatments, and if no `ACTIVE` treatments remain the colony's `health_status` returns to `HEALTHY`. Voiding a treatment (for a mis-recording) moves an `ACTIVE` treatment to `VOIDED` and likewise recomputes `harvest_blocked_until` from the remaining `ACTIVE` treatments; if that leaves the colony clear (its block now null or in the past), a `BLOCKED` lot fed only by now-clear colonies becomes eligible to be returned to `DRAFT`. Both `COMPLETED` and `VOIDED` are terminal for a treatment.

Returning a blocked lot to draft is a manual step once the chemistry has cleared: a `BLOCKED` lot moves back to `DRAFT` only when no contributing colony still has its `harvest_blocked_until` in the future relative to the clock. While a lot sits in `BLOCKED`, attempting to extract it or to add a new harvest from a still-blocked colony is rejected with `ERR_HARVEST_BLOCKED_WITHDRAWAL`.

### 3.5. Pollination Contracts and Hive Placement

A pollination contract captures a grower's bloom-window order. The coordinator creates one with the `grower_name`, the orchard's `orchard_state_code`, the `bloom_start` (inclusive) and `bloom_end` (exclusive) instants of the contracted window, the `required_strong_hives` count (an integer of at least one), the `max_hives_on_site` aggregate cap (an integer of at least one), and the `base_rate_cents` per-hive rate for a contract-grade hive (a non-negative integer). A new contract is `DRAFT`, with `placed_strong_hives` and `projected_payout_cents` both zero. Its lifecycle is one of `DRAFT`, `SIGNED`, `PLACED`, `UNDERSTAFFED`, `FULFILLED`, `DISPUTED`, or `CANCELLED`, and it is cyclic via the dispute loop. Contracts can be listed and filtered by `status`.

Signing a contract moves it from `DRAFT` to `SIGNED`; this requires the contract to be `DRAFT` and the `bloom_end` to be strictly after the `bloom_start`. Once `SIGNED`, the contract is open for placements. The coordinator proposes a placement against the contract by supplying the `hive_id`, the `placement_start` (inclusive) and the `removal_due` (exclusive) instants framing the on-orchard window; the new placement is `PROPOSED`. A placement carries a computed `grade` (`CONTRACT_GRADE` or `SUB_GRADE`) and a computed `contract_rated_strength`, both snapshotted at confirmation; its lifecycle is `PROPOSED`, `CONFIRMED`, `REMOVED`, or `CANCELLED`. Placements for a contract can be listed, and placements can also be filtered globally by `hive_id` or `contract_id`.

Confirming a placement is the system's most heavily guarded transition and moves it from `PROPOSED` to `CONFIRMED`. Beyond the optimistic-concurrency requirement on `expected_contract_version` from §2.11, confirmation enforces a sequence of business preconditions, each with its own rejection code, evaluated in this order: first, the colony's owning apiary must have `registration_status` equal to `ACTIVE`, else `ERR_APIARY_NOT_REGISTERED`; then the parent contract must be in `SIGNED` or `UNDERSTAFFED` and the colony must be `HEALTHY` (and the placement's hive and contract must be distinct, existing, non-terminal resources), else `ERR_HIVE_NOT_PLACEABLE` — the contract-state failure and the non-`HEALTHY` failure both surface as `ERR_HIVE_NOT_PLACEABLE`, with the contract-state check evaluated first; then the colony must not already be `CONFIRMED` on another placement whose window overlaps the requested half-open window from `placement_start` up to `removal_due`, else `ERR_HIVE_DOUBLE_BOOKED` — note that mere adjacency, where one placement's `removal_due` equals another's `placement_start`, does not count as an overlap and is allowed; and confirming must not push the aggregate count of hives whose windows overlap the new window to a value that meets or exceeds `max_hives_on_site`, else `ERR_SITE_CAPACITY_EXCEEDED` — this overlap count is taken over the parent contract's other `CONFIRMED` placements only (placements on other contracts do not count toward this site cap), and the candidate placement itself is included in the count being compared.

On a successful confirmation the system snapshots the placement's `grade` and `contract_rated_strength` using the **forward-projected** variant of the colony strength score, increments the contract's `placed_strong_hives` by one when the resulting `grade` is `CONTRACT_GRADE`, and increments the contract's `version`. The forward-projected variant reuses the same scoring formula as the point-in-time variant in §3.3 but on a forward-looking input set: the colony's `brood_frames` is first projected forward to `bloom_start`, growing by 2 frames per whole week from the clock to `bloom_start` (using the floor of the number of whole weeks, so a partial week adds no growth) and capped at a maximum of 20 brood frames, and only then is the score computed. The grade is `CONTRACT_GRADE` when the projected score is at or above the contract-grade minimum of 60, and `SUB_GRADE` otherwise. Because the input set is forward-looking, the same colony can score `SUB_GRADE` today yet `CONTRACT_GRADE` at bloom.

A confirmed placement can be removed by the coordinator, moving it from `CONFIRMED` to `REMOVED`; if its `grade` was `CONTRACT_GRADE`, the contract's `placed_strong_hives` is decremented. A proposed placement can instead be cancelled, moving it from `PROPOSED` to `CANCELLED` with no further effect. Both `REMOVED` and `CANCELLED` are terminal for a placement.

### 3.6. Contract Progression, Payout, and the Dispute Loop

Once enough strong hives are placed, the coordinator finalizes placement, moving the contract from `SIGNED` (or back from `UNDERSTAFFED`) to `PLACED`; this is permitted only when `placed_strong_hives` is at or above `required_strong_hives`. Finalizing recomputes `projected_payout_cents` and increments the contract's `version`. If a colony death later drives `placed_strong_hives` below `required_strong_hives` while the contract is `PLACED`, the system cascade moves the contract from `PLACED` to `UNDERSTAFFED` and recomputes the payout from the remaining confirmed placements (the third hop of §3.2). Backfilling additional confirmed placements and finalizing again returns the contract from `UNDERSTAFFED` to `PLACED`.

The projected payout is computed only from the contract's `CONFIRMED` placements. For each confirmed placement, a per-hive cents amount is formed: a contract-grade hive earns the contract's `base_rate_cents` multiplied by a strong multiplier of 1.20 when its `contract_rated_strength` is at or above the strong-bonus minimum of 80, and by 1.00 otherwise; a sub-grade hive earns the `base_rate_cents` multiplied by the sub-grade multiplier of 0.50. Each per-hive amount is rounded half-up to whole cents **before** any summation. The subtotal is the sum of those rounded per-hive amounts. A shortfall is the greater of zero and `required_strong_hives` minus `placed_strong_hives`; the penalty is that shortfall multiplied by 5000 cents. A fulfillment bonus of 10000 cents is added when `placed_strong_hives` is at or above `required_strong_hives`, and zero otherwise. The `projected_payout_cents` is the greater of zero and the subtotal plus the fulfillment bonus minus the penalty. This same payout computation runs on every transition into or within `PLACED` — finalize-placement, resolve-dispute, and the understaffed recompute.

A `PLACED` contract may be disputed, moving it from `PLACED` to `DISPUTED` and freezing the payout pending re-placement. Resolving the dispute moves it back from `DISPUTED` to `PLACED` (the cyclic loop), permitted only when `placed_strong_hives` is again at or above `required_strong_hives`, and recomputes the payout. A `PLACED` contract is fulfilled — moving from `PLACED` to `FULFILLED`, a terminal state that locks the payout as final — only when the logical clock has reached or passed `bloom_end` and every `CONFIRMED` placement is already `REMOVED` or its `removal_due` is at or before the clock; fulfilling too early is `ERR_TOO_EARLY`. Cancelling a contract is permitted while it is `DRAFT`, `SIGNED`, or `UNDERSTAFFED`; it moves to the terminal `CANCELLED` state, cancels all of the contract's proposed and confirmed placements, and resets `placed_strong_hives` to zero.

### 3.7. Honey Lots: Harvest, Extraction, and Sale

An extraction lot is opened against a yard by supplying the `apiary_id`, a `lot_code` unique within that apiary, and the declared `floral_source` (one of `WILDFLOWER`, `ALMOND`, `CLOVER`, or `ORANGE_BLOSSOM`). A new lot is `DRAFT`, with `provisional_yield_kg` and `gross_weight_kg` both zero, `price_per_kg_cents` zero, and `final_yield_kg`, `gross_revenue_cents`, and `net_revenue_cents` all null. The lot lifecycle is one of `DRAFT`, `BLOCKED`, `EXTRACTED`, `SOLD`, or `VOIDED`. Lots can be listed and filtered by `apiary_id` and by `status`.

Honey is rolled into a lot as harvest contributions. A harvest references the lot it rolls into through `lot_id` and the colony supers were pulled from through `hive_id`, and records the `frames_pulled` (an integer of at least one) and the net `weight_kg` (a positive number); the new contribution is `RECORDED`. A harvest may not be recorded while the contributing colony has its `harvest_blocked_until` in the future relative to the clock — that attempt is `ERR_HARVEST_BLOCKED_WITHDRAWAL`. Recording a harvest credits the lot's `gross_weight_kg` by the contribution's `weight_kg` and recomputes the lot's provisional yield. Harvests can be listed for a lot, read individually, and listed globally with filters on `hive_id`, `lot_id`, and `status`.

The lot's `provisional_yield_kg` is an estimate computed from frame counts at draft time: it is the sum of `frames_pulled` across the lot's `RECORDED` (non-void) harvests, multiplied by the per-frame estimate of 2.5 kilograms per frame, and rounded half-up to two decimal places. It ignores measured weight entirely. Note that a harvest records `weight_kg` for mass conservation but does not debit the hive's `honey_frames` field, which is purely a strength-scoring input updated only by inspections.

Voiding a single harvest moves it from `RECORDED` to the terminal `VOID`, but only while its parent lot is `DRAFT` or `BLOCKED`; doing so subtracts the contribution's `weight_kg` from the lot's `gross_weight_kg` and recomputes the provisional yield, preserving honey-mass conservation. Voiding the whole lot is permitted while the lot is `DRAFT` or `BLOCKED`, moves it to the terminal `VOIDED`, and voids every one of its `RECORDED` harvests, restoring `gross_weight_kg` to zero.

Extracting a lot moves it from `DRAFT` to `EXTRACTED`. It is permitted only when the lot is `DRAFT`, when no contributing colony still has its `harvest_blocked_until` in the future relative to the clock, else `ERR_HARVEST_BLOCKED_WITHDRAWAL`, and when it has at least one `RECORDED` harvest — an extraction attempt on a lot with no recorded contributions is rejected with `ERR_EMPTY_LOT`; consistent with the validation ordering of §2.8, the withdrawal-block check is evaluated before the empty-lot check. Extraction computes the lot's `final_yield_kg` using the **final** variant of the yield calculation: the measured `gross_weight_kg` reduced by a 4% extraction loss — that is, the gross weight multiplied by 0.96 — rounded half-up to two decimal places. The `final_yield_kg` is null until the lot is extracted, and it diverges from the frame-based provisional estimate for the same lot.

Selling an extracted lot moves it from `EXTRACTED` to the terminal `SOLD`, and requires the supplied `price_per_kg_cents` to be at least 1. Selling computes two revenue figures. The `gross_revenue_cents` is the `final_yield_kg` multiplied by `price_per_kg_cents`, rounded half-up to whole cents. A volume discount is then keyed on that gross figure with a pinned evaluation order: compute the gross first, select the tier from the gross, then apply. If `gross_revenue_cents` is at or above 500000 cents the discount is 10%; otherwise if it is at or above 100000 cents the discount is 5%; otherwise the discount is zero. The `net_revenue_cents` is `gross_revenue_cents` minus the discount, where the discount is `gross_revenue_cents` multiplied by the discount percentage and rounded half-up to whole cents. Both `gross_revenue_cents` and `net_revenue_cents` are null until the lot is sold.

### 3.8. Queen and Nucleus Sales

The coordinator or the beekeeper sells live bees from a yard by reserving a sale against the apiary, supplying the `source_hive_id` of the colony the unit is drawn from, the `product_type` (either `QUEEN` for a mated queen alone or `NUC` for a full nucleus with frames and bees), optionally the `frames_drawn` brood frames to pull for a nucleus (a non-negative integer defaulting to zero, and zero for a queen-only sale), and the `price_cents` (a non-negative integer). The sale also records the `apiary_id` of the yard it ships from. A new sale is `RESERVED`, and the lifecycle is one of `RESERVED`, `SHIPPED`, or `VOIDED`. Sales for an apiary can be listed, read individually, and listed globally with filters on `source_hive_id`, `apiary_id`, and `status`.

Shipping a sale moves it from `RESERVED` to `SHIPPED`. It requires the source colony to be non-`DEADOUT` — a `DEADOUT` source colony is rejected with `ERR_INVALID_STATE` — and for a nucleus sale it requires the source colony's `brood_frames` to be at least the `frames_drawn`; drawing more brood frames than the colony holds is rejected with `ERR_INSUFFICIENT_BROOD_FRAMES`. For a nucleus sale, shipping decrements the source colony's `brood_frames` by `frames_drawn` and decrements the owning apiary's `active_colony_count` by one, because the nucleus leaves the yard as a new colony.

Voiding a shipped sale moves it from `SHIPPED` to the terminal `VOIDED` and compensates the conserved totals: for a nucleus sale it restores the source colony's `brood_frames` by `frames_drawn` and increments the apiary's `active_colony_count` by one. Because restoring a colony could overrun the yard, voiding is rejected with `ERR_YARD_CAPACITY_EXCEEDED` when restoring would push `active_colony_count` above the yard's `max_yard_colonies`.

### 3.9. Feeding and Requeening Schedules

Supplemental feeding is recorded as an immutable event against a colony: the beekeeper supplies the `fed_at` instant, the `feed_type` (one of `SYRUP_1_1`, `SYRUP_2_1`, `FONDANT`, or `POLLEN_PATTY`), and the `quantity_kg` of feed (a positive number). Feedings for a hive can be listed; they are append-only and carry no further lifecycle.

Requeening is a scheduled, deferred action. The beekeeper schedules a requeen for a colony by supplying the `due_date` and the `reason` (one of `AGE`, `FAILING`, `QUEENLESS`, or `GENETICS`); the new schedule is `SCHEDULED`, and its lifecycle is one of `SCHEDULED`, `COMPLETED`, or `CANCELLED`. Schedules for a hive can be listed and filtered by `status`. Starting a scheduled requeen moves the schedule from `SCHEDULED` to the terminal `COMPLETED`, but only when the schedule is `SCHEDULED`, the colony is not `DEADOUT` (a `DEADOUT` colony is rejected with `ERR_INVALID_STATE`, checked before the time gate), the logical clock has reached or passed the `due_date` (otherwise `ERR_TOO_EARLY`), and the colony is currently `QUEENLESS` (otherwise `ERR_INVALID_STATE`). Starting the schedule drives the colony's queen axis from `QUEENLESS` to `REQUEENING`, the bridge into the requeening phase described in §3.2; the colony later returns to `QUEENRIGHT` when the beekeeper completes the requeening. A scheduled requeen that is no longer needed can instead be cancelled, moving the schedule from `SCHEDULED` to the terminal `CANCELLED` with no side effect.

### 3.10. Well-Formedness and Uniqueness

Across all create operations, the system finally checks that the request body is well-formed — required fields present, field types correct, and enum values drawn from their permitted sets — and that uniqueness constraints hold: a hive's `tag` is unique within its apiary, a honey lot's `lot_code` is unique within its apiary, and a registration's `registration_number` is unique. A violation of any of these is rejected with `ERR_INVALID_REQUEST`. Field-level value violations that are not about structure — a negative quantity, a `removal_due` at or before its `placement_start`, or a `bloom_end` at or before its `bloom_start` — are rejected with `ERR_VALIDATION`. The `removal_due` versus `placement_start` ordering is checked when a placement is proposed, but the `bloom_end` versus `bloom_start` ordering is not checked at contract creation — a contract may be created `DRAFT` with any bloom instants, and the ordering is enforced only when the contract is signed (where a `bloom_end` at or before `bloom_start` yields `ERR_VALIDATION`).

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify or transition an existing resource, and all reads, return a `200 OK` status code. The logical-clock endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to an explicit UTC instant; re-evaluates active registrations for expiry | PlatformAdmin |
| GET | `/_clock/now` | Read the current logical clock | PlatformAdmin, ApiaryManager, StateApiarist, ContractCoordinator |
| POST | `/apiaries` | Register a new apiary/yard | PlatformAdmin, ApiaryManager |
| GET | `/apiaries/{id}` | Read an apiary | PlatformAdmin, ApiaryManager, StateApiarist, ContractCoordinator |
| GET | `/apiaries` | List apiaries, filterable by state_code | PlatformAdmin, ApiaryManager, StateApiarist, ContractCoordinator |
| POST | `/apiaries/{id}/registrations` | File a state apiary registration (starts PENDING) | PlatformAdmin, StateApiarist |
| GET | `/apiaries/{id}/registrations` | List registrations for an apiary | PlatformAdmin, StateApiarist, ApiaryManager, ContractCoordinator |
| POST | `/apiaries/{id}/registrations/{rid}/approve` | Approve a PENDING registration | StateApiarist |
| POST | `/apiaries/{id}/registrations/{rid}/expire` | Expire an ACTIVE registration | StateApiarist, PlatformAdmin |
| POST | `/apiaries/{id}/registrations/{rid}/revoke` | Revoke a PENDING registration | StateApiarist |
| POST | `/hives` | Create a colony in an apiary | ApiaryManager |
| GET | `/hives/{id}` | Read a hive | ApiaryManager, ContractCoordinator, PlatformAdmin |
| GET | `/hives` | List hives, filterable by apiary_id, source_hive_id, health_status | ApiaryManager, ContractCoordinator, PlatformAdmin |
| POST | `/hives/{id}/quarantine` | Move a HEALTHY hive to QUARANTINE | ApiaryManager |
| POST | `/hives/{id}/deadout` | Mark a colony DEADOUT; triggers the colony-loss cascade | ApiaryManager |
| POST | `/hives/{id}/mark-queenless` | Move a hive to QUEENLESS | ApiaryManager |
| POST | `/hives/{id}/requeen-complete` | Move a hive from REQUEENING to QUEENRIGHT | ApiaryManager |
| POST | `/hives/{id}/inspections` | Record an inspection | ApiaryManager |
| GET | `/hives/{id}/inspections` | List inspections for a hive | ApiaryManager, PlatformAdmin |
| POST | `/hives/{id}/treatments` | Apply a mite treatment | ApiaryManager |
| GET | `/hives/{id}/treatments` | List treatments for a hive | ApiaryManager, PlatformAdmin |
| POST | `/treatments/{id}/complete` | Complete an ACTIVE treatment after its duration | ApiaryManager |
| POST | `/treatments/{id}/void` | Void an ACTIVE treatment | ApiaryManager |
| POST | `/honey-lots` | Open an extraction lot | ApiaryManager |
| GET | `/honey-lots/{id}` | Read a lot | ApiaryManager, PlatformAdmin |
| GET | `/honey-lots` | List lots, filterable by apiary_id, status | ApiaryManager, PlatformAdmin |
| POST | `/honey-lots/{id}/unblock` | Return a BLOCKED lot to DRAFT | ApiaryManager |
| POST | `/honey-lots/{id}/extract` | Extract a DRAFT lot; computes final_yield_kg | ApiaryManager |
| POST | `/honey-lots/{id}/sell` | Sell an EXTRACTED lot; records revenue | ApiaryManager |
| POST | `/honey-lots/{id}/void` | Void a DRAFT/BLOCKED lot; voids its harvests | ApiaryManager |
| POST | `/honey-lots/{id}/harvests` | Record a harvest contribution into a DRAFT lot | ApiaryManager |
| GET | `/honey-lots/{id}/harvests` | List harvests for a lot | ApiaryManager, PlatformAdmin |
| GET | `/harvests/{id}` | Read a single harvest contribution | ApiaryManager, PlatformAdmin |
| GET | `/harvests` | List harvests, filterable by hive_id, lot_id, status | ApiaryManager, PlatformAdmin |
| POST | `/harvests/{id}/void` | Void a single RECORDED harvest | ApiaryManager |
| POST | `/pollination-contracts` | Create an almond pollination contract (DRAFT) | ContractCoordinator |
| GET | `/pollination-contracts/{id}` | Read a contract | ContractCoordinator, PlatformAdmin |
| GET | `/pollination-contracts` | List contracts, filterable by status | ContractCoordinator, PlatformAdmin |
| POST | `/pollination-contracts/{id}/sign` | Move a contract from DRAFT to SIGNED | ContractCoordinator |
| POST | `/pollination-contracts/{id}/finalize-placement` | Move SIGNED/UNDERSTAFFED to PLACED; recompute payout | ContractCoordinator |
| POST | `/pollination-contracts/{id}/dispute` | Move PLACED to DISPUTED | ContractCoordinator |
| POST | `/pollination-contracts/{id}/resolve-dispute` | Move DISPUTED back to PLACED | ContractCoordinator |
| POST | `/pollination-contracts/{id}/fulfill` | Move PLACED to FULFILLED; lock payout | ContractCoordinator |
| POST | `/pollination-contracts/{id}/cancel` | Cancel a contract; cancel placements | ContractCoordinator |
| POST | `/pollination-contracts/{id}/placements` | Propose placing a hive on a contract (PROPOSED) | ContractCoordinator |
| GET | `/pollination-contracts/{id}/placements` | List placements for a contract | ContractCoordinator, PlatformAdmin |
| GET | `/hive-placements/{id}` | Read a placement | ContractCoordinator, PlatformAdmin |
| GET | `/hive-placements` | List placements, filterable by hive_id, contract_id, status | ContractCoordinator, PlatformAdmin |
| POST | `/hive-placements/{id}/confirm` | Confirm a placement; OCC-guarded; grade and capacity checks | ContractCoordinator |
| POST | `/hive-placements/{id}/remove` | Move CONFIRMED to REMOVED | ContractCoordinator |
| POST | `/hive-placements/{id}/cancel` | Move PROPOSED to CANCELLED | ContractCoordinator |
| POST | `/apiaries/{id}/queen-nuc-sales` | Reserve a queen or nuc sale from a source hive | ContractCoordinator, ApiaryManager |
| GET | `/apiaries/{id}/queen-nuc-sales` | List sales for an apiary | ContractCoordinator, ApiaryManager, PlatformAdmin |
| GET | `/queen-nuc-sales/{id}` | Read a single queen/nuc sale | ContractCoordinator, ApiaryManager, PlatformAdmin |
| GET | `/queen-nuc-sales` | List sales, filterable by source_hive_id, apiary_id, status | ContractCoordinator, ApiaryManager, PlatformAdmin |
| POST | `/queen-nuc-sales/{id}/ship` | Ship a sale; for NUC draws frames and decrements colony count | ContractCoordinator, ApiaryManager |
| POST | `/queen-nuc-sales/{id}/void` | Void a shipped sale; restores frames and colony count | ContractCoordinator, ApiaryManager |
| POST | `/hives/{id}/feedings` | Record a feeding event | ApiaryManager |
| GET | `/hives/{id}/feedings` | List feedings for a hive | ApiaryManager, PlatformAdmin |
| POST | `/hives/{id}/requeen-schedules` | Schedule a requeening for a hive | ApiaryManager |
| GET | `/hives/{id}/requeen-schedules` | List requeen schedules for a hive | ApiaryManager, PlatformAdmin |
| POST | `/requeen-schedules/{id}/start` | Start a due requeen; drives queen_status to REQUEENING | ApiaryManager |
| POST | `/requeen-schedules/{id}/cancel` | Cancel a scheduled requeen | ApiaryManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TERMINAL_STATE` | 409 |
| `ERR_HARVEST_BLOCKED_WITHDRAWAL` | 409 |
| `ERR_APIARY_NOT_REGISTERED` | 409 |
| `ERR_HIVE_NOT_PLACEABLE` | 409 |
| `ERR_HIVE_DOUBLE_BOOKED` | 409 |
| `ERR_SITE_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_BROOD_FRAMES` | 422 |
| `ERR_YARD_CAPACITY_EXCEEDED` | 409 |
| `ERR_EMPTY_LOT` | 422 |
| `ERR_TOO_EARLY` | 409 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_VALIDATION` | 422 |
